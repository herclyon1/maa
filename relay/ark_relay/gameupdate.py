"""大版本更新日，把三个游戏的客户端自己更新掉。

用户 2026-09-02：「大版本鸣潮和终末地都有启动器去更新，明日方舟是通过模拟器
里面去更新安装包然后再手动点进去更新……希望你能帮我实现自动化。」

三家三条路，都在开机窗口（预更新之后、队列之前）跑：

* 终末地：鹰角启动器（进程 Games，窗口「鹰角启动器」）。读屏：按钮是
  「更新游戏」就点，等它变成「开始游戏」；然后拉一次游戏过「资源初始化
  更新完成，请重启游戏」和着色器编译，看到「点击任意位置继续」才算完。
  2026-09-02 手动走过一遍，每一步的字都是当天屏幕上读到的。
* 鸣潮：库洛启动器（Wuthering Waves.exe 是壳）。同样读屏点「更新」，
  等「开始游戏」。OK-WW 自己也会处理更新，这里只是让它别撞上正在下载。
* 明日方舟：不点模拟器界面。官方版本接口给 clientVersion，和上次记下的
  已装版本比，不同就下载 APK（官方直链，2 GB 上下，支持断点续传），
  起雷电、`ldconsole installapp` 装进去，装完读 dumpsys 核对版本，再退出
  模拟器。第一次没有记录时先起模拟器读一次已装版本记下来。

每一步的结论都写日志；没能确认的进 problems，由调用方发「⚠️ 没能确认」。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ
from .desktop import Desktop, kill
from .config import atomic_write_text

log = logging.getLogger("ark.gameupdate")

_UA = "Mozilla/5.0"
AK_VERSION_URL = "https://ak-conf.hypergryph.com/config/prod/official/Android/version"
AK_APK_URL = "https://ak.hypergryph.com/downloads/android_lastest"
AK_PACKAGE = "com.hypergryph.arknights"


# ─────────────────────────── 通用 ───────────────────────────

def _spawn(exe: Path, cwd: Path | None = None) -> bool:
    from .preupdate import _spawn_interactive  # noqa: PLC0415
    return _spawn_interactive(exe, cwd or exe.parent, require_console=True)


def _note(problems: list[str] | None, msg: str) -> None:
    if problems is not None:
        problems.append(msg)


# ─────────────────────────── 终末地 ───────────────────────────

def endfield_paths(maaend_dir: Path | None) -> tuple[Path | None, Path | None]:
    """(游戏 exe, 启动器 exe)。游戏路径从 MaaEnd 自己的配置读，不猜。"""
    if not maaend_dir:
        return None, None
    cfg = Path(maaend_dir) / "config" / "mxu-MaaEnd.json"
    try:
        m = re.search(r'"connectedProgramPath"\s*:\s*"([^"]+)"', cfg.read_text(encoding="utf-8"))
    except OSError:
        return None, None
    if not m:
        return None, None
    game = Path(m.group(1).replace("\\\\", "\\"))
    # D:\endfield\Hypergryph Launcher\games\Endfield Game\Endfield.exe → 上三级是启动器目录
    launcher = game.parents[2] / "Launcher.exe" if len(game.parents) >= 3 else None
    return game, (launcher if launcher and launcher.exists() else None)


def update_endfield(desk: Desktop, game: Path, launcher: Path, *,
                    budget_s: float = 2400, poll_s: float = 30,
                    problems: list[str] | None = None, sleep=time.sleep) -> str:
    """返回给人看的一句话；没更新返回空串。"""
    kill("Endfield.exe")
    if not _spawn(launcher):
        _note(problems, "终末地：启动器没能在桌面会话里起来")
        return ""
    sleep(25)
    scr = desk.read(focus="Games")
    if scr.has("开始游戏"):
        log.info("游戏更新：终末地启动器已是「开始游戏」，无需更新")
        kill("Games.exe")
        return ""
    if not scr.has("更新游戏"):
        _note(problems, f"终末地：启动器画面没读到按钮（截图 {scr.shot}）：{scr.dump(12)}")
        kill("Games.exe")
        return ""
    if not desk.click_text("更新游戏", focus="Games"):
        _note(problems, "终末地：点「更新游戏」没点上")
        kill("Games.exe")
        return ""
    log.info("游戏更新：终末地已点「更新游戏」，等它下载安装")
    deadline = time.monotonic() + budget_s
    ready = False
    while time.monotonic() < deadline:
        sleep(poll_s)
        scr = desk.read(focus="Games")
        if scr.has("开始游戏"):
            ready = True
            break
        log.info("游戏更新：终末地启动器 %s", scr.find("正在下载") or scr.find("安装中") or scr.dump(4))
    if not ready:
        _note(problems, f"终末地：{budget_s / 60:.0f} 分钟内没等到「开始游戏」，启动器留在后台继续下，下次开机再确认")
        return ""
    # 装完了。拉一次游戏把「资源初始化」和着色器编译做掉，否则早班第一趟必卡。
    desk.click_text("开始游戏", focus="Games")
    sleep(90)
    deadline = time.monotonic() + 900
    restarted = False
    while time.monotonic() < deadline:
        scr = desk.read(focus="Endfield")
        if scr.has("点击任意位置继续"):
            log.info("游戏更新：终末地已到标题画面，客户端可用")
            break
        if scr.has("请重启游戏") and not restarted:
            desk.click_text("确认", focus="Endfield")
            sleep(8)
            kill("Endfield.exe")
            sleep(3)
            _spawn(game)
            restarted = True
            sleep(60)
            continue
        if scr.has("客户端版本已过时"):
            _note(problems, "终末地：更新后游戏仍说客户端已过时")
            break
        sleep(poll_s)
    else:
        _note(problems, "终末地：更新后 15 分钟没走到标题画面（可能还在编译着色器）")
    kill("Endfield.exe", "Games.exe")
    return "终末地 客户端已通过启动器更新"


# ─────────────────────────── 鸣潮 ───────────────────────────

def wuwa_launcher(okww_dir: Path | None) -> Path | None:
    """启动器（壳）路径：从 OK-WW 自己的配置里找以 Wuthering Waves.exe 结尾的值。"""
    if not okww_dir:
        return None
    root = Path(okww_dir) / "data" / "apps" / "ok-ww" / "working" / "configs"
    for f in root.glob("*.json"):
        try:
            m = re.search(r'"([^"]*Wuthering Waves\.exe)"', f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if m:
            p = Path(m.group(1).replace("\\\\", "\\"))
            if p.exists():
                return p
    fallback = Path(r"D:\Wuthering Waves Game\Wuthering Waves.exe")
    return fallback if fallback.exists() else None


def update_wuwa(desk: Desktop, launcher: Path, *, budget_s: float = 2400, poll_s: float = 30,
                problems: list[str] | None = None, sleep=time.sleep) -> str:
    from .preupdate import _okww_quiesce  # noqa: PLC0415 - 关壳和游戏进程的现成办法
    if not _spawn(launcher):
        _note(problems, "鸣潮：启动器没能在桌面会话里起来")
        return ""
    sleep(30)
    scr = desk.read(focus="title:鸣潮")
    if scr.has("开始游戏"):
        log.info("游戏更新：鸣潮启动器已是「开始游戏」，无需更新")
        _okww_quiesce()
        return ""
    btn = scr.find("立即更新") or scr.find("更新游戏") or scr.find("更新")
    if btn is None:
        _note(problems, f"鸣潮：启动器画面没读到按钮（截图 {scr.shot}）：{scr.dump(12)}")
        _okww_quiesce()
        return ""
    desk.click(*btn.center, focus="title:鸣潮")
    log.info("游戏更新：鸣潮已点「%s」，等它下载安装", btn.text)
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        sleep(poll_s)
        scr = desk.read(focus="title:鸣潮")
        if scr.has("开始游戏"):
            _okww_quiesce()
            return "鸣潮 客户端已通过启动器更新"
    _note(problems, f"鸣潮：{budget_s / 60:.0f} 分钟内没等到「开始游戏」，先把启动器关掉免得和 OK-WW 撞车")
    _okww_quiesce()
    return ""


# ─────────────────────────── 明日方舟 ───────────────────────────

def ldconsole_of(maa_dir: Path | None) -> tuple[Path | None, int]:
    """(ldconsole.exe, 实例序号)。从 MAA 自己的配置读 AdbPath / 雷电快捷方式。"""
    if not maa_dir:
        return None, 0
    try:
        text = (Path(maa_dir) / "config" / "gui.new.json").read_text(encoding="utf-8")
    except OSError:
        return None, 0
    m = re.search(r'"AdbPath"\s*:\s*"([^"]+)"', text)
    if not m:
        return None, 0
    exe = Path(m.group(1).replace("\\\\", "\\")).parent / "ldconsole.exe"
    idx = 0
    if mi := re.search(r"雷电模拟器-(\d+)\.lnk", text):
        idx = int(mi.group(1))
    return (exe if exe.exists() else None), idx


def remote_ak_version(fetch=None) -> str:
    data = fetch() if fetch else json.loads(
        urllib.request.urlopen(urllib.request.Request(  # noqa: S310
            AK_VERSION_URL, headers={"User-Agent": _UA}), timeout=20).read())
    return str((data or {}).get("clientVersion") or "")


def installed_ak_version(ldconsole: Path, idx: int, run=None) -> str:
    """dumpsys 里的 versionName。模拟器没起来就返回空串。"""
    run = run or (lambda args: subprocess.run(args, capture_output=True, text=True,
                                              errors="replace", timeout=60).stdout)
    out = run([str(ldconsole), "adb", "--index", str(idx), "--command",
               f"shell dumpsys package {AK_PACKAGE}"])
    hits = re.findall(r"versionName=(\S+)", out or "")
    return hits[0] if hits else ""


def _record_path(state_dir: Path) -> Path:
    return Path(state_dir) / "arknights-client.json"


def recorded_ak_version(state_dir: Path) -> str:
    try:
        return str(json.loads(_record_path(state_dir).read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def record_ak_version(state_dir: Path, version: str) -> None:
    atomic_write_text(_record_path(state_dir), json.dumps(
        {"version": version, "at": datetime.now(tz=SERVER_TZ).isoformat()}, ensure_ascii=False))


def download(url: str, dest: Path, *, timeout: float = 1500) -> bool:
    """断点续传下到 dest。完成后按 Content-Length 核对大小。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Range": f"bytes={have}-"})
    deadline = time.monotonic() + timeout
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        cr = r.headers.get("Content-Range") or ""
        total = int(cr.rsplit("/", 1)[-1]) if "/" in cr else have + int(r.headers.get("Content-Length") or 0)
        if r.status == 200:
            have = 0                      # 服务器不认 Range，从头来
        with open(part, "ab" if have else "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                if time.monotonic() > deadline:
                    log.warning("下载 %s 超过预算，先停在 %d/%d，下次接着下", dest.name, have, total)
                    return False
    if total and have != total:
        log.warning("下载 %s 大小不对：%d != %d", dest.name, have, total)
        return False
    part.replace(dest)
    return True


def update_arknights(state_dir: Path, ldconsole: Path, idx: int, *,
                     budget_s: float = 900, problems: list[str] | None = None,
                     fetch=None, run=None, sleep=time.sleep, downloader=download) -> str:
    """返回「明日方舟 已更新：旧 → 新」或空串。"""
    run = run or (lambda args: subprocess.run(args, capture_output=True, text=True,
                                              errors="replace", timeout=120).stdout)
    try:
        remote = remote_ak_version(fetch)
    except Exception as exc:  # noqa: BLE001
        _note(problems, f"明日方舟：官方版本接口取不到（{exc}）")
        return ""
    if not remote:
        _note(problems, "明日方舟：官方版本接口没给 clientVersion")
        return ""
    local = recorded_ak_version(state_dir)

    def boot() -> bool:
        run([str(ldconsole), "launch", "--index", str(idx)])
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            sleep(10)
            if installed_ak_version(ldconsole, idx, run):
                return True
        return False

    if not local:
        # 第一次：起模拟器读一次已装版本记下来，之后才有得比
        if not boot():
            _note(problems, "明日方舟：起雷电读已装版本没成功（4 分钟内 adb 没通）")
            return ""
        local = installed_ak_version(ldconsole, idx, run)
        run([str(ldconsole), "quit", "--index", str(idx)])
        if local:
            record_ak_version(state_dir, local)
            log.info("游戏更新：明日方舟已装 %s（首次记录）", local)
        if not local or local == remote:
            return ""
    if local == remote:
        log.info("游戏更新：明日方舟已是 %s，无需更新", remote)
        return ""

    log.info("游戏更新：明日方舟 %s → %s，下载 APK", local, remote)
    apk = Path(state_dir) / "apk" / f"arknights-{remote}.apk"
    if not apk.exists():
        try:
            if not downloader(AK_APK_URL, apk, timeout=budget_s):
                _note(problems, f"明日方舟：APK 没下完（{local} → {remote}），下次开机接着下")
                return ""
        except Exception as exc:  # noqa: BLE001
            _note(problems, f"明日方舟：下载 APK 失败（{exc}）")
            return ""
    if not boot():
        _note(problems, "明日方舟：起雷电装包没成功（adb 没通）")
        return ""
    run([str(ldconsole), "installapp", "--index", str(idx), "--filename", str(apk)])
    deadline = time.monotonic() + 600
    now_ver = ""
    while time.monotonic() < deadline:
        sleep(15)
        now_ver = installed_ak_version(ldconsole, idx, run)
        if now_ver == remote:
            break
    run([str(ldconsole), "quit", "--index", str(idx)])
    if now_ver != remote:
        _note(problems, f"明日方舟：装完读到的版本是 {now_ver or '空'}，不是 {remote}")
        return ""
    record_ak_version(state_dir, remote)
    try:
        apk.unlink()
    except OSError:
        pass
    return f"明日方舟 已更新：{local} → {remote}（APK 已装进雷电）"


# ─────────────────────────── 调度 ───────────────────────────

def _stamp(state_dir: Path) -> Path:
    return Path(state_dir) / "gameupdate.json"


def should_run(state_dir: Path | None, now: datetime, *, boot_id: str) -> bool:
    """每次开机跑一遍；同一次开机不重跑（部署重启服务不算新开机）。"""
    if not state_dir:
        return False
    try:
        d = json.loads(_stamp(state_dir).read_text(encoding="utf-8"))
        return d.get("boot") != boot_id
    except (OSError, ValueError):
        return True


def mark_run(state_dir: Path | None, now: datetime, *, boot_id: str) -> None:
    if state_dir:
        atomic_write_text(_stamp(state_dir), json.dumps(
            {"boot": boot_id, "at": now.isoformat()}, ensure_ascii=False))


# ─────────────────────────── 登记：哪个游戏要更新 ───────────────────────────
# 用户 2026-09-02：「预更新的窗口只有几分钟，更新游戏来不及。检测到有更新之后
# 直接先跳过这个游戏，等所有其他游戏跑完之后，再单独拉这个游戏进行更新，
# 然后再去重跑。」所以：开机只登记，队列跑完引擎再来做（run_deferred）。

def _pending_path(state_dir: Path) -> Path:
    return Path(state_dir) / "gameupdate-pending.json"


def pending(state_dir: Path) -> dict[str, str]:
    """{游戏: 为什么}。"""
    try:
        d = json.loads(_pending_path(state_dir).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in (d or {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def mark_pending(state_dir: Path, game: str, why: str) -> bool:
    """登记一条；已经登记过同一个游戏就不重复。返回是否新登记。"""
    d = pending(state_dir)
    if game in d:
        return False
    d[game] = why
    atomic_write_text(_pending_path(state_dir), json.dumps(d, ensure_ascii=False))
    log.info("游戏更新：已登记 %s 待更新（%s）", game, why)
    return True


def clear_pending(state_dir: Path, game: str) -> None:
    d = pending(state_dir)
    if game in d:
        d.pop(game)
        atomic_write_text(_pending_path(state_dir), json.dumps(d, ensure_ascii=False))


def last_run_ok(state_dir: Path, now: datetime, script: str) -> bool | None:
    """今天这个脚本最后一趟成没成；今天没跑过返回 None。"""
    last = None
    for e in _today(state_dir, now):
        if e.get("script") == script:
            last = bool(e.get("ok"))
    return last


def _today(state_dir: Path, now: datetime) -> list[dict]:
    p = Path(state_dir) / f"ledger-{now:%Y-%m-%d}.jsonl"
    try:
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []


_UNREACHABLE_FLAG = {"MaaEnd": "maaend_unreachable", "OK-WW": "okww_unreachable"}


def needs_rerun(state_dir: Path, now: datetime, script: str) -> bool:
    """只有「今天最后一趟是因为客户端过时进不了游戏」才值得更新后重跑。

    2026-09-02 晚上的事故：MaaEnd 因为上游没适配新版本，四个任务真失败了；
    我按「最后一趟没成功就重跑」把它又派发了一遍，把正在玩的用户挤下线。
    普通任务失败重跑也还是失败，只会白白抢号——那种失败不归更新管。
    """
    if any(r.get("script") == script for r in skips(state_dir)):
        return True                     # 今天从队列里摘掉的，更新完必须补跑
    last = None
    for e in _today(state_dir, now):
        if e.get("script") == script:
            last = e
    if last is None or last.get("ok"):
        return False
    raw = last.get("raw") or {}
    return bool(raw.get(_UNREACHABLE_FLAG.get(script, "")) or raw.get("maintenance"))


def off(state_dir: Path) -> bool:
    """总开关：state/gameupdate-off.flag 存在就整套不动。"""
    return (Path(state_dir) / "gameupdate-off.flag").exists()


# ─────────────────────────── 鸣潮：官方公告里的更新维护日 ───────────────────────────
_WW_NOTICE_URL = ("https://aki-gm-resources-back.aki-game.com/gamenotice/G152/"
                  "76402e5b20be2c39f095a152090afddc/zh-Hans.json")
_WW_MAINT = re.compile(r"更新维护时间[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日")


def wuwa_update_day(now: datetime, fetch=None) -> str:
    """公告里最新的「版本内容说明」写的更新维护日是今天 → 返回依据句；否则空串。

    公告是提前几天发的，写法固定：「更新维护时间：2026年8月20日04:00 ~ …」
    （2026-09-02 核对）。一个 HTTP 请求，不开启动器。
    """
    try:
        data = fetch() if fetch else json.loads(
            urllib.request.urlopen(urllib.request.Request(  # noqa: S310
                _WW_NOTICE_URL, headers={"User-Agent": _UA}), timeout=20).read())
        items = [(str(n.get("tabTitle") or ""), str(n.get("content") or ""))
                 for n in (data.get("game") or []) if "版本内容说明" in str(n.get("tabTitle") or "")]
        from .banners import newest_version  # noqa: PLC0415
        body = newest_version(items)
        m = _WW_MAINT.search(re.sub(r"<[^>]+>", " ", body))
        if not m:
            return ""
        y, mo, d = (int(x) for x in m.groups())
        if (y, mo, d) == (now.year, now.month, now.day):
            ver = next((t for t, _ in items if body == dict(items).get(t)), "")
            return f"官方公告：今天更新维护（{ver.strip().splitlines()[-1] if ver else '新版本'}）"
    except Exception:  # noqa: BLE001 - 只是信号
        return ""
    return ""


# ─────────────────────────── 开机：只做便宜的判断 ───────────────────────────

def boot_check(cfg, *, budget_s: float, now: datetime | None = None,
               hint=None, fetch=None, wuwa_fetch=None, maint_sources=None,
               skipper=None) -> tuple[list[str], list[str]]:
    """开机窗口里做的事：一个 HTTP 读方舟版本号、一个 HTTP 读终末地公告。

    方舟版本不同：窗口够（≥10 分钟）就当场装，不够就登记；
    终末地公告说今天版本更新：登记；启动器一次都不开。
    鸣潮：公告写的更新维护日是今天就登记（OK-WW 只会点游戏内的「即将重启」，
    不会点启动器上的「更新」——用户 2026-09-02 指出的）。
    """
    now = now or datetime.now(tz=SERVER_TZ)
    notes: list[str] = []
    problems: list[str] = []
    if off(cfg.state_dir):
        log.info("游戏更新：总开关关着（gameupdate-off.flag），不检查")
        return notes, problems
    ld, idx = ldconsole_of(cfg.maa_dir)
    if ld:
        try:
            remote = remote_ak_version(fetch)
            local = recorded_ak_version(cfg.state_dir)
            if remote and local and remote != local:
                # 用户 2026-09-02：「你能保证 10 分钟之内更新完吗？」——不能。一律延后。
                mark_pending(cfg.state_dir, "明日方舟", f"官方版本 {remote}，已装 {local}")
            elif remote and not local:
                # 第一次：起模拟器记一次已装版本（约一分钟）
                if n := update_arknights(cfg.state_dir, ld, idx, budget_s=min(budget_s, 300),
                                         problems=problems, fetch=fetch):
                    notes.append(n)
            else:
                log.info("游戏更新：明日方舟已是 %s，无需更新", remote or "?")
        except Exception:  # noqa: BLE001
            log.exception("游戏更新：明日方舟开机检查出错")
            problems.append("明日方舟：开机检查出错（见日志）")
    from . import efstatus  # noqa: PLC0415
    n0 = now.replace(tzinfo=None) if now.tzinfo else now
    try:
        h = (hint or efstatus.update_hint)(n0)
    except Exception:  # noqa: BLE001
        h = ""
    if h and last_run_ok(cfg.state_dir, now, "MaaEnd") is not True:
        # 今天已经成功过就不登记；普通任务失败也不归更新管（needs_rerun 会再拦一道）
        mark_pending(cfg.state_dir, "终末地", h)
    w = wuwa_update_day(n0, fetch=None if wuwa_fetch is None else wuwa_fetch)
    if w and last_run_ok(cfg.state_dir, now, "OK-WW") is not True:
        mark_pending(cfg.state_dir, "鸣潮", w)
    # 三家官方停服维护公告（maintenance.py）：今天在维护的游戏，把窗口落盘并登记。
    # 用户 2026-09-02 定的：维护中不算失败；队列跑完后等到开服，更新，补跑，再关机。
    try:
        from . import maintenance  # noqa: PLC0415
        wins = maintenance.today(now, sources=maint_sources) if maint_sources is not None else maintenance.today(now)
    except Exception:  # noqa: BLE001
        wins = {}
    save_windows(cfg.state_dir, wins)
    for game, (start, end, why) in wins.items():
        script = maintenance.SCRIPT_OF[game]
        if last_run_ok(cfg.state_dir, now, script) is True:
            continue
        mark_pending(cfg.state_dir, game, why)
        # 用户 2026-09-03：「当天队列里不跑他」。今天队列时刻落在维护窗口
        # （开服后再算 45 分钟客户端更新）里的，经接口把它从队列摘掉；
        # 补跑完再加回（restore_skips）。摘/加回 09-03 在早班上实测可逆。
        from datetime import timedelta as _td  # noqa: PLC0415
        for q in _queues_today(cfg.automas_dir, now):
            for due in q["dues"]:
                if start - _td(minutes=30) <= due <= end + _td(minutes=45):
                    try:
                        rec = skipper(q["name"], script) if skipper else _skip_default(q["name"], script)
                    except Exception as exc:  # noqa: BLE001
                        problems.append(f"{game}：从队列「{q['name']}」摘掉 {script} 失败（{exc}）")
                        continue
                    if rec:
                        rec["why"] = why
                        _add_skip(cfg.state_dir, rec)
                        log.info("游戏更新：%s 维护（%s），今天从队列「%s」摘掉 %s", game, why, q["name"], script)
                    break
    return notes, problems


def _skip_default(queue: str, script: str):
    from . import commands  # noqa: PLC0415
    return commands.skip_script_in_queue(queue, script)


def _queues_today(automas_dir, now: datetime) -> list[dict]:
    """今天还没到的队列时刻：[{name, dues:[datetime]}]。"""
    from . import plan  # noqa: PLC0415
    out = []
    for q in plan.schedule(automas_dir) if automas_dir else []:
        dues = []
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due >= now:
                dues.append(due)
        out.append({"name": q["name"], "dues": dues})
    return out


def _skips_path(state_dir: Path) -> Path:
    return Path(state_dir) / "queue-skips.json"


def skips(state_dir: Path) -> list[dict]:
    try:
        return list(json.loads(_skips_path(state_dir).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def _add_skip(state_dir: Path, rec: dict) -> None:
    lst = skips(state_dir)
    if not any(r.get("queueId") == rec.get("queueId") and r.get("scriptId") == rec.get("scriptId") for r in lst):
        lst.append(rec)
    atomic_write_text(_skips_path(state_dir), json.dumps(lst, ensure_ascii=False))


def restore_skips(state_dir: Path, restorer=None) -> list[str]:
    """把今天摘掉的都加回去。返回加回了谁。每次调用都试，成功的才从记录里去掉。"""
    from . import commands  # noqa: PLC0415
    restorer = restorer or commands.restore_script_in_queue
    left, done = [], []
    for rec in skips(state_dir):
        try:
            if restorer(rec):
                done.append(f"{rec['script']}→「{rec['queue']}」")
                continue
        except Exception:  # noqa: BLE001
            log.exception("加回队列失败：%s", rec)
        left.append(rec)
    atomic_write_text(_skips_path(state_dir), json.dumps(left, ensure_ascii=False))
    return done


def _windows_path(state_dir: Path) -> Path:
    return Path(state_dir) / "maintenance-today.json"


def save_windows(state_dir: Path, wins: dict) -> None:
    atomic_write_text(_windows_path(state_dir), json.dumps(
        {g: {"start": w[0].isoformat(), "end": w[1].isoformat(), "why": w[2]} for g, w in wins.items()},
        ensure_ascii=False))


def windows(state_dir: Path) -> dict[str, tuple[datetime, datetime, str]]:
    try:
        d = json.loads(_windows_path(state_dir).read_text(encoding="utf-8"))
        return {g: (datetime.fromisoformat(v["start"]), datetime.fromisoformat(v["end"]), str(v.get("why") or ""))
                for g, v in d.items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def in_maintenance(state_dir: Path, script: str, at: datetime) -> str:
    """这个脚本在这一刻是不是撞上了官方停服维护（开服后再宽限 45 分钟给客户端更新）。
    返回依据句；不是返回空串。"""
    from . import maintenance  # noqa: PLC0415
    from datetime import timedelta  # noqa: PLC0415
    game = next((g for g, s in maintenance.SCRIPT_OF.items() if s == script), "")
    w = windows(state_dir).get(game)
    if not w:
        return ""
    start, end, why = w
    if start - timedelta(minutes=30) <= at.astimezone(start.tzinfo) <= end + timedelta(minutes=45):
        return why
    return ""


# ─────────────────────────── 队列跑完之后：更新 + 重跑 ───────────────────────────

def run_deferred(cfg, *, now: datetime | None = None, desk: Desktop | None = None,
                 dispatch=None, sleep=time.sleep, clock=None) -> tuple[list[str], list[str], list[str]]:
    """把登记过的都做掉。返回 (更新通知, 问题, 重跑了哪些脚本)。

    用户 2026-09-03 定的顺序：**队列跑完立刻更新**（下载、安装、拉起游戏过
    着色器编译，到「点击任意位置继续」的登录界面才算准备好），不等开服；
    准备好之后如果离开服还超过 10 分钟就先把游戏关掉，到点再单独补跑。
    更新包还没放出来（维护中常见）就每 10 分钟再试，最多试到开服后 2 小时。
    """
    now = now or datetime.now(tz=SERVER_TZ)
    clock = clock or (lambda: datetime.now(tz=SERVER_TZ))
    notes: list[str] = []
    problems: list[str] = []
    reran: list[str] = []
    todo = pending(cfg.state_dir)
    if not todo or off(cfg.state_dir):
        return notes, problems, reran
    desk = desk or Desktop(cfg.state_dir)
    wins = windows(cfg.state_dir)
    from datetime import timedelta as _td  # noqa: PLC0415

    def prepare(game: str) -> tuple[bool, str]:
        """更新到登录界面。返回 (准备好了没, 通知句)。没准备好时 problems 里有原因。"""
        before = len(problems)
        if game == "终末地":
            g, l = endfield_paths(cfg.maaend_dir)
            if not (g and l):
                problems.append("终末地：找不到启动器"); return False, ""
            n = update_endfield(desk, g, l, budget_s=2400, problems=problems, sleep=sleep)
        elif game == "鸣潮":
            l = wuwa_launcher(cfg.okww_dir)
            if not l:
                problems.append("鸣潮：找不到启动器"); return False, ""
            n = update_wuwa(desk, l, budget_s=2400, problems=problems, sleep=sleep)
        else:
            ld, idx = ldconsole_of(cfg.maa_dir)
            if not ld:
                problems.append("明日方舟：找不到雷电 ldconsole"); return False, ""
            n = update_arknights(cfg.state_dir, ld, idx, budget_s=1800, problems=problems, sleep=sleep)
        return len(problems) == before, n

    def rerun(script: str) -> None:
        if needs_rerun(cfg.state_dir, now, script) and dispatch is not None:
            ok, msg = dispatch(script)
            log.info("游戏更新：补跑 %s → %s", script, msg)
            if ok:
                reran.append(script)
            else:
                problems.append(f"{script}：更新后没能补跑（{msg}）")

    from . import maintenance  # noqa: PLC0415
    for game, why in list(todo.items()):
        script = maintenance.SCRIPT_OF.get(game, "")
        start, end = (wins.get(game) or (None, None, ""))[:2]
        deadline = (end + _td(hours=2)) if end else clock() + _td(hours=1)
        ready, note = False, ""
        while True:
            ready, note = prepare(game)
            if ready or clock() >= deadline:
                break
            # 更新包多半还没放出来：把这轮的问题收回，10 分钟后再试
            log.info("游戏更新：%s 还没准备好（%s），10 分钟后再试", game, problems[-1] if problems else "")
            del problems[len(problems) - 1:]
            sleep(600)
        if note:
            notes.append(note + f"（依据：{why}）")
        if not ready:
            problems.append(f"{game}：到 {deadline:%m-%d %H:%M} 仍没准备好客户端，今天不补跑")
            continue
        # 准备好了。离开服还远就先关游戏等着；到点补跑
        if end and clock() < end:
            if end - clock() > _td(minutes=10):
                kill("Endfield.exe", "Client-Win64-Shipping.exe")
            log.info("游戏更新：%s 客户端已就绪，等 %s 开服再补跑", game, end.strftime("%H:%M"))
            while clock() < end:
                sleep(60)
            sleep(120)
        rerun(script)
        clear_pending(cfg.state_dir, game)
    if done := restore_skips(cfg.state_dir):
        log.info("游戏更新：已把摘掉的加回队列：%s", "、".join(done))
    return notes, problems, reran
