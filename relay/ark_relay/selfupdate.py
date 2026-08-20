"""The relay updates its own code at boot, over the same route as the inbox.

Until now new code reached this machine only when the Mac happened to be awake
and pushed it. That put a laptop in another country on the critical path of a
machine that runs unattended, and made every fix wait for a window where both
were up at once.

Same channel as the inbox, and the same door order (see _alternates): the
jsDelivr mirrors first, raw.githubusercontent last - measured 2026-08-21 from
the machine, raw answered 2 of 8 at an average of 38 seconds while
fastly.jsdelivr answered 8 of 8 at 426ms. A manifest lists each file with its
SHA-1, so a file is fetched only when it actually differs - an up-to-date
relay costs one small request.

This module itself never reloads code into the running process - reloading in
place is where self-updating systems go wrong. It only lands verified files on
disk; deciding what to do about that is the caller's job. service.py restarts
the service when this returns a non-empty list, so an update takes effect
within seconds instead of waiting for the next boot (operator order
2026-08-20: 更新必须立即生效). The restart is a fresh process, not a reload.

Either every changed file lands or none does: a half-applied update leaves a
mixed-version relay, and the restart above would then boot straight into it.

Trust boundary, stated plainly: whoever can push to that repo can run code on
this machine. The repo is the operator's own and the transport is HTTPS, so the
exposure is the GitHub account itself - the same account that already decides
what the machine farms.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("ark.update")

DEFAULT_BASE = "https://raw.githubusercontent.com/herclyon1/maa/main/relay/"
MANIFEST = "manifest.json"
# 整轮自更新的总时间预算。开机时序：早班 08:47 中继起来 / 09:00 队列开跑，
# 晚班 21:22 / 21:30——短的那头只有 8 分钟。240 秒既留足余量，又足够在
# CDN 不同步、只能走 raw 的日子里把三五个文件拉下来。到点干净放弃，
# 下次启动（当天晚上那趟）重来。
BUDGET_SECONDS = 240
# 给 raw.githubusercontent 的单次超时。它是四扇门里唯一不吃 CDN 缓存的，
# CDN 落后时它是**唯一**能拿到新内容的门，所以不能掐太死——实测它成功时
# 平均要 38 秒。总时长由上面的预算兜底，这里给它一次像样的机会。
RAW_TIMEOUT = 25


def _get_once(url: str, timeout: int = 20) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ark-relay"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read()
    except (urllib.error.URLError, OSError, ValueError,
            http.client.HTTPException) as exc:
        # HTTPException 走的是 resp.read() 半截断流（IncompleteRead）那条路，
        # 不是 OSError 的子类；漏掉它会让异常穿出去，把重试机会一起丢掉。
        log.warning("取不到 %s: %s", url, exc)
        return None


def _alternates(url: str) -> list[str]:
    """The same file through a second door (jsDelivr CDN over the same repo).

    raw.githubusercontent is half-walled from the machine's network and has
    gone dark for whole evenings (2026-08-17). The repo, history and write
    path stay on GitHub; only the download exit changes. Every fetched file
    is still verified against the manifest's SHA-1, so a stale CDN copy can
    only ever mean "no update yet", never wrong code.
    (Duplicated from inbox.py on purpose: selfupdate refuses to create new
    files on the machine, so a shared module would never arrive.)
    """
    prefix = "https://raw.githubusercontent.com/"
    if not url.startswith(prefix):
        return [url]
    parts = url[len(prefix):].split("/", 3)
    if len(parts) < 4:
        return [url]
    owner, repo, branch, path = parts
    ref = f"gh/{owner}/{repo}@{branch}/{path}"
    # 顺序来自 2026-08-21 凌晨在游戏机上的实测（每门 8 次）：
    #   fastly.jsdelivr  8/8  平均 426ms      ← 最好
    #   cdn.jsdelivr     7/8  平均 1956ms
    #   gcore.jsdelivr   7/8  平均 2398ms
    #   raw.github       2/8  平均 38179ms    ← 最差，但内容永远最新
    # 所以 raw 放最后：它是唯一不吃 CDN 缓存的门，留作兜底而不是首选。
    # （jsDelivr 的缓存由 scripts/mac/purge-cdn.py 在每次推送后全局清掉。）
    return [
        f"https://fastly.jsdelivr.net/{ref}",
        f"https://cdn.jsdelivr.net/{ref}",
        f"https://gcore.jsdelivr.net/{ref}",
        url,
    ]


# Netloc of the door that answered most recently, tried first from then on.
# raw.githubusercontent goes fully dark for whole evenings (observed 08-17 and
# again 08-20, 0/6 with jsDelivr at 6/6); without stickiness every file of a
# multi-file update pays a full timeout on the dead door before the live one,
# which turns a boot-time update into minutes of waiting for nothing.
_last_good = ""


def _netloc(url: str) -> str:
    """Host part of an http(s) URL; the URL itself when it has no host.

    Never raises: a misconfigured base URL must degrade into a failed fetch
    (caught downstream), not an IndexError before any fetch is attempted.
    """
    parts = url.split("/")
    return parts[2] if len(parts) > 2 else url


def _remaining(deadline: float | None) -> float:
    """离预算耗尽还有多少秒；没有预算就当作无限。"""
    return 1e9 if deadline is None else deadline - time.monotonic()


def _get_with_retry(url: str, attempts: int = 3, timeout: int = 20,
                    expect_sha: str = "", deadline: float | None = None) -> bytes | None:
    """Fetch, retrying transient failures across both doors.

    Measured from the game machine: raw.githubusercontent answered 11 of 11 one
    hour and 7 of 10 the next, with the failures being TLS handshake and read
    timeouts rather than refusals. One attempt at boot therefore misses roughly
    a third of the time - and a boot is the only chance of the day. Three
    attempts take that under 3%, at the cost of a few seconds on the rare bad
    morning.
    """
    global _last_good  # noqa: PLW0603 - process-lifetime stickiness by design
    urls = _alternates(url)
    urls.sort(key=lambda u: _netloc(u) != _last_good)  # stable: keeps order
    for i in range(attempts):
        for u in urls:
            left = _remaining(deadline)
            if left <= 1:
                log.warning("更新时间预算用尽，放弃取 %s", url.rsplit("/", 1)[-1])
                return None
            # raw.githubusercontent 实测 2/8、平均 38 秒，是四扇门里最慢的。
            # 它只是"内容永远最新"的兜底，不值得为它把开机时间烧光——给它
            # 一个短超时，通得过算捡到，通不过立刻让位。
            per = min(timeout, left)
            if "raw.githubusercontent.com" in u:
                per = min(per, RAW_TIMEOUT)
            if (data := _get_once(u, int(max(2, per)))) is None:
                continue
            # 内容不对 = 这扇门给的是旧副本，换下一扇，而不是就此放弃。
            # jsDelivr 的刷新不是原子的（2026-08-21 实测：.py 已经是新的、
            # manifest 还是旧的），所以"取到了"和"取对了"必须分开判断。
            # 早先把校验放在这个循环外面，结果 CDN 一旦缓存不同步，整套更新
            # 就直接失败，压根不会去试永远最新的 raw.githubusercontent。
            if expect_sha and _sha1(data) != expect_sha:
                log.warning("%s 给的是旧副本（缓存未刷新），换下一扇门", _netloc(u))
                continue
            _last_good = _netloc(u)
            return data
        if i + 1 < attempts:
            nap = min(3 * (i + 1), max(0.0, _remaining(deadline) - 1))
            if nap <= 0:
                return None
            time.sleep(nap)
    return None


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()  # noqa: S324 - change detection, not security


def _atomic_write(target: Path, data: bytes) -> None:
    """临时文件 + os.replace，断电也不会留下半截 .py。

    这台机器每天自己关两次电，而半截的 .py 会让中继下次启动直接
    SyntaxError 起不来——那是没人会发现的死法（守护它的 SCM 只会一直重
    启一个必然失败的进程）。config 那边已经这么做了，代码这边同理。
    """
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)


def _safe_target(root: Path, rel: str) -> Path | None:
    """Resolve a manifest path inside `root`, or None if it escapes.

    A manifest is fetched from the network, so "../../windows/system32/..." has
    to be impossible by construction rather than by trusting the file.
    """
    if rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        return None
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _applied_version(root: Path) -> int:
    try:
        return int((root / "state" / "code-version.txt")
                   .read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def _remember_version(root: Path, version: int) -> None:
    path = root / "state" / "code-version.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, str(version).encode("utf-8"))
    except OSError:
        log.warning("记不住代码版本号，下次可能重复检查", exc_info=True)


def _best_manifest(base: str, deadline: float | None = None) -> dict | None:
    """把每扇门的 manifest 都取回来，选版本号最大的那份。

    manifest 是所有校验的基准，唯独它自己没法被校验——所以不能"哪扇门先
    应答就用哪份"。CDN 的刷新不是原子的，先应答的那扇很可能给的是上一版
    （实测 2026-08-21：文件已经是新的、manifest 还是旧的），照着旧清单去
    对新文件，每个文件都判不符，整套更新永远失败。

    版本号只增不减，所以"取最大"既能绕开落后的门，又不需要信任任何一扇。
    没有版本号的老格式退回"第一份取到的"，保持向后兼容。
    """
    best: dict | None = None
    best_ver = -1
    fallback: dict | None = None
    for url in _alternates(base + MANIFEST):
        left = _remaining(deadline)
        if left <= 1:
            log.warning("取 manifest 时预算已用尽，用手头最好的一份")
            break
        per = min(20.0, left)
        if "raw.githubusercontent.com" in url:
            per = min(per, RAW_TIMEOUT)
        if (data := _get_once(url, int(max(2, per)))) is None:
            continue
        try:
            m = json.loads(data)
        except json.JSONDecodeError:
            log.warning("%s 给的 manifest 不是合法 JSON", _netloc(url))
            continue
        if not isinstance(m, dict) or not isinstance(m.get("files"), dict):
            continue
        if fallback is None:
            fallback = m
        try:
            ver = int(m.get("version") or 0)
        except (TypeError, ValueError):
            ver = 0
        if ver > best_ver:
            best, best_ver = m, ver
    if best is not None and best_ver > 0:
        log.debug("选用 v%s 的 manifest", best_ver)
        return best
    return fallback


def check(root: Path, base_url: str = "",
          budget_s: float = BUDGET_SECONDS) -> list[str]:
    """Fetch and apply any changed files. Returns human-readable lines.

    `budget_s` 是整轮的墙钟预算，超了就干净放弃。这条在开机路径上是硬要求：
    CDN 缓存不同步时，每个文件都要把四扇门试一遍（其中 raw 很慢），21 个
    文件足够拖过 09:00 的队列时刻。宁可这次不更新，也不能耽误刷图。
    """
    base = (base_url or DEFAULT_BASE).rstrip("/") + "/"
    deadline = time.monotonic() + budget_s if budget_s else None
    manifest = _best_manifest(base, deadline)
    if manifest is None:
        return []
    files = manifest["files"]

    # 拒绝比机器上更旧的清单。下载走的是 CDN，CDN 完全可能整套缓存着上一版
    # （旧 manifest + 旧 .py，内部自洽、哈希也对得上），那样机器会被"更新"
    # 回旧代码，而且日志上看起来一切正常。版本号只增不减，这道闸让降级变成
    # 一条明确的警告而不是一次静默回滚。
    try:
        remote_ver = int(manifest.get("version") or 0)
    except (TypeError, ValueError):
        remote_ver = 0
    local_ver = _applied_version(root)
    if remote_ver and local_ver and remote_ver < local_ver:
        log.warning("拿到的是旧清单（v%s < 本机 v%s），可能是 CDN 缓存未刷新，"
                    "本次不更新", remote_ver, local_ver)
        return []

    # 先把要改的文件全部下齐并校验，一个都不落盘；全通过了再一次性写。
    #
    # 逐个下、下一个写一个是不行的：网络在中途断掉（这条线上是常态）会留下
    # 「新 engine.py + 旧 core.py」的混合版本，而 service.py 一看有文件变了
    # 就重启——重启进去的可能是一个跨版本、甚至跨不过 import 的中继。半套
    # 更新比不更新危险得多。
    # 存 (manifest 里的相对路径, 落盘目标, 内容)。相对路径必须原样留着，
    # 不能事后拿 target.relative_to(root) 反推——_safe_target 返回的是
    # resolve 过的路径，root 却未必（macOS 上 /var 是 /private/var 的符号
    # 链接），反推会抛 ValueError，而那时文件已经写下去了。
    staged: list[tuple[str, Path, bytes]] = []
    for rel, want in sorted(files.items()):
        target = _safe_target(root, rel)
        if target is None:
            log.warning("manifest 里的路径越界，已忽略: %s", rel)
            continue
        if not target.exists():
            # New files are a bigger step than updating one, and a relay that
            # can create arbitrary files is a wider door than this needs.
            log.info("跳过新增文件（需人工部署一次）: %s", rel)
            continue
        if _sha1(target.read_bytes()) == want:
            continue
        data = _get_with_retry(base + rel, expect_sha=want, deadline=deadline)
        if data is None:
            log.warning("%s 所有门都拿不到正确内容，本次更新整体放弃（已下 %d 个"
                        "文件都不落盘，下次启动重来）", rel, len(staged))
            return []
        staged.append((rel, target, data))

    updated: list[str] = []
    for rel, target, data in staged:
        try:
            _atomic_write(target, data)
        except OSError:
            # 走到这里已经全部校验通过，落盘还失败就是磁盘/权限问题。停手，
            # 让下次启动重做——继续写只会把混合版本铺得更开。
            log.exception("写入 %s 失败，停止本次更新", rel)
            break
        updated.append(rel)

    if updated:
        # Stale bytecode has run on this machine before, so clear it here too.
        for cache in root.rglob("__pycache__"):
            for pyc in cache.glob("*.pyc"):
                pyc.unlink(missing_ok=True)
        log.info("代码已更新 %d 个文件: %s", len(updated), "、".join(updated))
    # 版本号在"这套清单已完整落地"之后才记——包括本来就一致、一个文件都
    # 没改的情况（那也说明机器已是这一版）。半途 break 掉的不记，让下次重来。
    if remote_ver and len(updated) == len(staged):
        _remember_version(root, remote_ver)
    return updated
