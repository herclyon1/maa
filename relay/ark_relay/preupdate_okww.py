"""preupdate_okww：从 preupdate.py 拆出（2026-09-08，只搬不改）。"""
from __future__ import annotations

import json
from .config import atomic_write_text
import subprocess
import time
from pathlib import Path


from .preupdate_common import _note, _pwsh, _spawn_interactive, log
from .preupdate_maaend import _close, _span



# OK-WW (鸣潮) is the fourth program and updates unlike any of the other three:
# not MirrorChyan, not a delegated updater, but pyappify pulling from a CNB git
# mirror (`https://cnb.cool/ok-oldking/ok-ww-update2.git`, reachable from this
# machine in 0.3s where GitHub is not reachable at all). app.json carries
# "update_method": "AUTO_UPDATE", so it updates itself when launched.
#
# Two things make the launch delicate:
#   1. The update only happens through ok-ww.exe, the pyappify shell. Running
#      the bundled python directly - which is how tasks run headlessly - leaves
#      pyappify uninitialised and /api/updates answers
#      "pyappify_version: None".
#   2. ok-ww.exe honours "Auto Start Game When App Starts", which is on here.
#      Launching it at 08:45 would start 鸣潮 itself. Same shape of hazard as
#      MAA's RunDirectly and MaaEnd's autostart, and handled the same way.
_OKWW_BASIC = ("data", "apps", "ok-ww", "working", "configs", "Basic Options.json")
_OKWW_APPJSON = ("data", "apps", "ok-ww", "app.json")
_OKWW_AUTOSTART_KEY = "Auto Start Game When App Starts"
OKWW_BUDGET_SECONDS = 240
# OK-WW 的更新检查是窗口显示后 30 秒才排的（它自己的日志：
# 「schedule pyappify update check in 30000ms」）。app.json 一启动就会被重写，
# 「文件动了」在 3 秒内就成立——2026-09-06 08:46:43 启动、08:46:46 就判「无需更新（v3.6.6）」
# 关掉了，30 秒后的检查根本没跑到；09:20 真跑时它自己装了 v3.6.7-beta.2，
# 把补丁全冲掉，那趟裸跑。所以「查过了」这个结论至少要等它过了那 30 秒。
OKWW_MIN_WAIT_SECONDS = 45


def _okww_quiesce() -> None:
    """Stop anything that would rewrite OK-WW's config from memory.

    Learned the hard way on 2026-08-24: a leftover `ok web` instance held the
    settings in memory and wrote them back, so flipping
    "Auto Start Game When App Starts" in the JSON had no effect - ok-ww.exe read
    the restored True and launched 鸣潮 during what was supposed to be a
    windowless update check. Same shape as MAA's master-copy problem: editing a
    file that a running process owns is editing a copy.
    """
    for name in ("ok-ww.exe", "Wuthering Waves.exe",
                 "Client-Win64-Shipping.exe", "KRSDKExternal.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", name],  # noqa: S603, S607
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    # The headless task/web runners are plain python; match them by command line.
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*ok-ww*' -or "
          "$_.CommandLine -like '*-m ok *' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run([_pwsh(), "-NoProfile", "-Command", ps],  # noqa: S603, S607
                       capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass
    time.sleep(2)


def _okww_autostart(okww_dir: Path, value: bool) -> bool | None:
    """Set OK-WW's auto-start-game flag, returning what it was. None if it could not."""
    cfg = Path(okww_dir).joinpath(*_OKWW_BASIC)
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        was = bool(data.get(_OKWW_AUTOSTART_KEY, False))
    except (OSError, ValueError, TypeError):
        log.warning("预更新：读不到 OK-WW 的 Basic Options，跳过 OK-WW")
        return None
    if was == value:
        return was
    data[_OKWW_AUTOSTART_KEY] = value
    try:
        atomic_write_text(cfg, json.dumps(data, ensure_ascii=False, indent=4))
    except OSError:
        log.warning("预更新：写不回 OK-WW 的 Basic Options，跳过 OK-WW", exc_info=True)
        return None
    return was


def _okww_state(okww_dir: Path) -> tuple[str, str, str, tuple[str, ...]]:
    """(current_version, update_state, update_error, available_versions).

    `available_versions` is the point of the fourth field: it is how we tell
    "checked, nothing newer" apart from "never checked at all". On 2026-08-25
    the pre-update reported 无需更新 while that list still topped out at the
    installed version and the CNB mirror already carried the next one - the
    list had simply never been refreshed.
    """
    try:
        d = json.loads(Path(okww_dir).joinpath(*_OKWW_APPJSON).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return "", "", "", ()
    avail = d.get("available_versions")
    return (str(d.get("current_version") or ""), str(d.get("update_state") or ""),
            str(d.get("update_error") or ""),
            tuple(str(x) for x in avail) if isinstance(avail, list) else ())


def _okww_stamp(okww_dir: Path) -> float:
    """app.json 的修改时间。0 表示读不到。

    2026-08-26：判据原本只看 `available_versions` 有没有变。可 OK-WW 本来就是
    最新版时，它**查过之后列表内容一模一样**——于是「查过了」和「压根没查」
    在中继眼里长得一样，只能报「没有任何检查迹象」。
    实测那次 app.json 的 mtime 明明前进了（12:36:53，正是启动它的那几分钟），
    **文件被写过就是它跑过的直接证据**，比比对内容可靠。
    """
    try:
        return Path(okww_dir).joinpath(*_OKWW_APPJSON).stat().st_mtime
    except OSError:
        return 0.0


def run_okww(okww_dir: Path | None,
             budget_s: float = OKWW_BUDGET_SECONDS,
             problems: list[str] | None = None) -> str:
    """Let OK-WW apply any pending update now, without starting the game.

    Appends to `problems` whenever the check could not be *proven* to have
    happened. Silence used to be reported as success; see `_spawn_interactive`
    for the morning that cost us a release.
    """
    if not okww_dir:
        return ""
    root = Path(okww_dir)
    exe = root / "ok-ww.exe"
    if not exe.exists():
        log.warning("预更新跳过：找不到 %s", exe)
        _note(problems, f"OK-WW 预更新跳过：找不到 {exe}")
        return ""

    before_version, _, _, before_avail = _okww_state(root)
    before_stamp = _okww_stamp(root)
    # Nothing may be holding the config in memory while we edit it.
    _okww_quiesce()
    was = _okww_autostart(root, False)
    if was is None:
        _note(problems, "OK-WW 预更新：改不动 app.json，没有检查更新")
        return ""
    try:
        # session 0 has no desktop, and OK-WW's updater simply does not run
        # there - it returns a stale version file that reads as "no update".
        if not _spawn_interactive(exe, root, require_console=True, minimized=True):
            log.warning("预更新：OK-WW 没能在控制台会话启动，本轮没有检查更新")
            _note(problems, "OK-WW 预更新：拿不到控制台会话，**没有检查更新**"
                            "（不是「无需更新」）")
            return ""
        log.info("预更新：已启动 OK-WW（已临时关掉自动开游戏），最多 %.0f 秒", budget_s)
        deadline = time.monotonic() + budget_s
        launched = time.monotonic()
        settled = ""
        checked = False           # 见到过它真的动了：状态变化 / 版本列表刷新 / 版本变化
        failed = ""
        while time.monotonic() < deadline:
            time.sleep(3)
            version, state, err, avail = _okww_state(root)
            if err:
                log.warning("预更新：OK-WW 更新报错 %s", err[:200])
                failed = err[:200]
                break
            if avail and avail != before_avail:
                checked = True    # 版本列表刷新过 = 确实向上游问过
            if before_stamp and _okww_stamp(root) > before_stamp:
                # 本来就是最新版时列表内容不会变，但文件照样会被重写。
                # 这一条才是「它确实跑起来查过了」的直接证据。
                checked = True
            if state and state not in ("idle", ""):
                checked = True
                continue          # 正在下载/安装，继续等
            if version and version != before_version:
                settled, checked = version, True
                break
            if (checked and state == "idle"
                    and time.monotonic() - launched >= OKWW_MIN_WAIT_SECONDS):
                break             # 问过了、30 秒后的那次检查也过了、已经安顿下来
        if failed:
            _note(problems, f"OK-WW 预更新：更新报错 {failed}")
        elif settled:
            log.info("预更新：OK-WW 已更新 %s → %s", before_version, settled)
        elif not checked:
            # 这正是 2026-08-25 的漏网：安静 ≠ 没有更新。
            log.warning("预更新：OK-WW %.0f 秒内没有任何检查迹象（版本列表没刷新）",
                        budget_s)
            _note(problems,
                  f"OK-WW 预更新：{budget_s:.0f} 秒内没有任何检查迹象，"
                  f"**无法确认是否检查过更新**（当前 {before_version or '版本未知'}）")
        else:
            newest = before_avail[0] if before_avail else ""
            log.info("预更新：OK-WW 无需更新（%s）", before_version or "版本未知")
            if newest and newest != before_version:
                _note(problems,
                      f"OK-WW 预更新：查到有 {newest}，但没装上"
                      f"（仍是 {before_version or '版本未知'}）")
        # Close OK-WW *and* anything it may have pulled up with it. A
        # pre-update that leaves 鸣潮 running has not left the machine alone.
        _close(exe)
        _okww_quiesce()
        return f"OK-WW 已更新：{_span(before_version, settled)}" if settled else ""
    finally:
        _okww_autostart(root, was)
