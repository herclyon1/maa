"""Config changes queued from anywhere, applied when the machine next boots.

The machine is powered off most of the day, and the person who wants to change
what it farms is in another country. Neither end can rely on the other being
awake, so the instruction goes somewhere that is always up and the machine
collects it on its own.

That somewhere is a plain file in the project's GitHub repo, fetched over a
CDN mirror of it. Three things decided it, all measured from the machine
itself rather than assumed:

  * github.com is unreachable from there (TCP timeout), so `git clone`/`pull`
    can never work - fetching one file over HTTPS is a different route.
    raw.githubusercontent itself is barely usable from that line (measured
    2026-08-21: 2/8, average 38s), so the jsDelivr mirrors go first and raw
    is kept only as an always-fresh last resort. See _alternates().
  * a public repo needs no token, so nothing secret has to live on someone
    else's PC.
  * the file is written by a person, occasionally, and a repo gives that
    person a web editor, a diff and a history for free.

The one thing this design cannot promise is delivery: that same raw endpoint
timed out earlier the same day. So the applied version is reported in the daily
push. A change that silently failed to arrive is then visible as a version that
did not move, instead of a machine quietly farming last week's plan.
"""
from __future__ import annotations

import http.client
import json
from datetime import datetime
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import SERVER_TZ, atomic_write_text, both_clocks
from . import maaend, queues, sanity_plan
from .commands import apply_command

log = logging.getLogger("ark.inbox")


def label_version(version: int) -> str:
    """2026081702 -> '08-17 v2'. Falls back to the raw number.

    The version has to be an integer so "strictly newer" can be decided without
    ambiguity - raw.githubusercontent is a CDN and can hand back a stale copy,
    and comparing dates as text invites the wrong answer at a month boundary.
    Encoding the date into the integer as YYYYMMDDNN keeps that property while
    letting the push say when the change was made instead of "v1", which tells
    the reader nothing.
    """
    text = str(version)
    if len(text) != 10:
        return f"v{version}"
    try:
        return f"{text[4:6]}-{text[6:8]} v{int(text[8:10])}"
    except ValueError:
        return f"v{version}"

DEFAULT_URL = ("https://raw.githubusercontent.com/herclyon1/maa/main/"
               "queue/config.json")


def _alternates(url: str) -> list[str]:
    """The same file through a second door.

    raw.githubusercontent is half-walled from the machine's network - the
    evening of 2026-08-17 it timed out and 429'd for hours straight, and the
    operator's pause order queued that morning never arrived before the run
    it was meant to stop. jsDelivr serves the identical GitHub content over a
    CDN with far better reachability from there. The repo, its history and
    the write path stay on GitHub untouched; only the download exit changes.
    A stale CDN copy is harmless by construction: versions apply only when
    strictly newer, and selfupdate verifies every file against its SHA-1.

    (Deliberately duplicated in selfupdate.py rather than shared: selfupdate
    refuses to create new files on the machine, so a new shared module would
    never arrive there.)
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
# (Same stickiness as selfupdate.py, duplicated for the same reason the
# _alternates helper is: selfupdate cannot deliver new shared modules.)
_last_good = ""


def _netloc(url: str) -> str:
    """Host part of an http(s) URL; the URL itself when it has no host.

    Never raises: a misconfigured ARK_INBOX_URL must degrade into a failed
    fetch (which keeps last_fetch_ok False and the 5-minute retry alive), not
    an IndexError that skips the fetch and leaves last_fetch_ok stuck True.
    """
    parts = url.split("/")
    return parts[2] if len(parts) > 2 else url


def _fetch(url: str, timeout: int = 20, attempts: int = 3) -> dict | None:
    """把每扇门的待办文件都取回来，选 version 最大的那份。

    不能"哪扇门先应答就用哪份"。2026-08-21 早上就栽在这里：CDN 上还缓存着
    昨天的 config.json，收件箱取到它、看见版本号没变大，于是判定"没有新指令"
    **一声不吭地跳过**——操作者昨晚排的换关卡指令就这么没生效，而日志里连一行
    异常都没有。

    自更新那边靠 manifest 里的 SHA-1 能识破旧副本，待办文件没有这种校验：
    它就是权威本身。所以改用同一个办法——问遍所有门，取版本号最大的一份。
    版本号只增不减，落后的门自然出局，而且不需要信任任何一扇门。

    只有一扇门应答（或都没有版本号）时退回"取到什么用什么"，保持向后兼容。
    """
    global _last_good  # noqa: PLW0603 - process-lifetime stickiness by design
    urls = _alternates(url)
    urls.sort(key=lambda u: _netloc(u) != _last_good)  # stable: keeps order
    for i in range(attempts):
        best: dict | None = None
        best_ver = -1
        fallback: dict | None = None
        for u in urls:
            if (data := _fetch_once(u, timeout)) is None:
                continue
            if fallback is None:
                fallback = data
                _last_good = _netloc(u)
            try:
                ver = int(data.get("version") or 0)
            except (TypeError, ValueError):
                ver = 0
            if ver > best_ver:
                best, best_ver = data, ver
                if ver > 0:
                    _last_good = _netloc(u)
        if best is not None and best_ver > 0:
            log.debug("待办文件取自各门中最新的一份 v%s", best_ver)
            return best
        if fallback is not None:
            return fallback
        if i + 1 < attempts:
            time.sleep(3 * (i + 1))
    return None


def _fetch_once(url: str, timeout: int = 20) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ark-relay"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except (urllib.error.URLError, OSError, ValueError,
            http.client.HTTPException) as exc:
        # IncompleteRead 不是 OSError 的子类，漏掉它异常会穿出去。
        log.warning("取不到待办文件（%s）: %s", url, exc)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("待办文件不是合法 JSON: %s", exc)
        return None
    return data if isinstance(data, dict) else None


class Inbox:
    """Remembers which version has been applied; applies newer ones once."""

    def __init__(self, state_dir: Path, url: str = "", maaend_dir: Path | None = None,
                 automas_dir: Path | None = None):
        self.url = url or DEFAULT_URL
        self.marker = Path(state_dir) / "inbox-version.txt"
        self.maaend_dir = maaend_dir
        self.automas_dir = automas_dir
        # Whether the last poll actually reached the queue file. "Could not
        # fetch" and "fetched, nothing new" both return quietly from poll();
        # the caller needs to tell them apart to keep retrying the former -
        # a pause order that fails to download is not a pause order.
        self.last_fetch_ok = True

    @property
    def applied_version(self) -> int:
        try:
            return int(self.marker.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return 0

    def _remember(self, version: int) -> None:
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        # Atomic: this can run inside a shutdown countdown (service.py calls
        # the deferred collect after tick(), which may already have issued
        # `shutdown /s /t 60`). A truncated marker reads as version 0 and
        # replays the whole last batch on the next boot.
        atomic_write_text(self.marker, str(version))

    def poll(self) -> tuple[int, list[str]]:
        """Fetch, and apply if it is newer. Returns (version_now, messages).

        Messages are empty when nothing changed - the overwhelmingly common
        case. This runs on a machine that boots twice a day and is expected to
        do nothing at all on almost every one of those boots.
        """
        have = self.applied_version
        data = self._fetch_or_none()
        self.last_fetch_ok = data is not None
        if data is None:
            return have, []

        try:
            version = int(data.get("version") or 0)
        except (TypeError, ValueError):
            log.warning("待办文件的 version 不是整数，忽略")
            return have, []

        # Strictly greater, never merely different. raw.githubusercontent is a
        # CDN and can serve a stale copy for a few minutes; on "different" that
        # would re-apply an older plan and flip the machine back and forth.
        if version <= have:
            return have, []

        note = str(data.get("note") or "").strip()
        commands = data.get("commands")
        if not isinstance(commands, list):
            log.warning("待办文件 v%s 没有 commands 数组，忽略", version)
            return have, []

        name = str(data.get("name") or "").strip()
        log.info("收到待办 v%s（当前 v%s）：%s", version, have, note or "(无说明)")
        try:
            messages = self._apply(commands)
        except Exception as exc:  # noqa: BLE001 - a torn batch must still report
            # Without this, an exception mid-batch (copy2 on a locked file,
            # disk full) escaped to the caller, which swallowed it - so a
            # half-applied batch produced NO push and NO version marker, and
            # the next boot re-applied the whole thing: skip_today lands on a
            # day nobody named, edits repeat. Record the version and say what
            # happened instead.
            log.exception("待办 v%s 应用中途出错", version)
            messages = [f"✗ 应用中途出错：{exc}。此前的指令可能已生效，"
                        "本批不会重放——请核对配置，未生效的指令用新版本重发"]
        # Recorded even when a command failed. Retrying the same broken batch
        # on every boot would push the same failure every morning and never
        # get better; the failure is reported instead, and the fix is a new
        # version - which is also how the operator learns it did not land.
        self._remember(version)
        # 返回值第 0 项是推送标题，其余是正文。以前把说明塞在标题里、正文只
        # 取 messages[1:]，结果操作者自己写的那句说明被整条丢掉——而那恰恰
        # 是最像人话的一句。
        title = f"⚙️ 配置已更新：{name}" if name else "⚙️ 配置已更新"
        body = [f"{both_clocks(datetime.now(tz=SERVER_TZ))} · {label_version(version)}"]
        if note:
            body += ["", note]
        return version, [title, "", *body, "", *messages]

    def _fetch_or_none(self) -> dict | None:
        return _fetch(self.url)

    def _apply(self, commands: list) -> list[str]:
        out: list[str] = []
        # MaaEnd changes are batched so an interdependent set lands together.
        maaend_batch = [c for c in commands
                        if isinstance(c, dict) and c.get("action") == "maaend_option"]
        others = [c for c in commands
                  if isinstance(c, dict) and c.get("action") != "maaend_option"]

        if maaend_batch:
            if not self.maaend_dir:
                out.append("✗ 终末地：找不到安装路径，跳过")
            else:
                ok, detail = maaend.apply_changes(self.maaend_dir, maaend_batch)
                out.append(("✅ 终末地：" if ok else "✗ 终末地：") + detail)

        for cmd in [c for c in others if c.get("action") == "queue"]:
            if not self.automas_dir:
                out.append("✗ 队列：找不到 AUTO-MAS 目录，跳过")
                continue
            ok, detail = queues.apply(
                self.automas_dir, str(cmd.get("name") or ""),
                cmd.get("enabled"), cmd.get("scripts"))
            out.append(("✅ " if ok else "✗ ") + detail)

        for cmd in [c for c in others if c.get("action") == "sanity_plan"]:
            # The one that actually decides what MaaEnd farms. Everything it
            # writes lands in AUTO-MAS, because AUTO-MAS overwrites MaaEnd's
            # own copy on every launch.
            if not self.automas_dir:
                out.append("✗ 理智方案：找不到 AUTO-MAS 目录，跳过")
                continue
            ok, detail = sanity_plan.set_plan(
                self.automas_dir, str(cmd.get("tab") or ""),
                str(cmd.get("line") or ""), str(cmd.get("rewards_set") or ""))
            out.append(("✅ 理智方案：" if ok else "✗ 理智方案：") + detail)

        for cmd in [c for c in others
                    if c.get("action") not in ("sanity_plan", "queue")]:
            # The file can only be written by whoever can push to the repo, so
            # authorship is the confirmation that gate ② asks for.
            ok, detail = apply_command({**cmd, "confirmed": True})
            # 成功时只报人话（detail 已经是「刷取关卡：TO-5 → 1-7」这种）；
            # 失败时才带上内部动作名，那时它是排查线索而不是噪音。
            out.append(f"✅ {detail}" if ok else f"✗ {cmd.get('action')}: {detail}")
        return out
