"""preupdate_okww: split out of preupdate.py (2026-09-08, moved verbatim)."""
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
# OK-WW only schedules its update check 30 seconds after the window shows up (its
# own log line: "schedule pyappify update check in 30000ms"). app.json is rewritten
# the moment it starts, so "the file moved" is true within 3 seconds - on 2026-09-06
# it was launched at 08:46:43, judged 「无需更新（v3.6.6）」 at 08:46:46 and closed, so
# the check 30 seconds later never ran at all; at 09:20, on the real run, it installed
# v3.6.7-beta.2 by itself, wiped every patch, and that round ran bare. So the
# conclusion "it has checked" has to wait out those 30 seconds at the very least.
OKWW_MIN_WAIT_SECONDS = 45


def _okww_quiesce(sleep=time.sleep) -> None:
    """Stop anything that would rewrite OK-WW's config from memory.

    Learned the hard way on 2026-08-24: a leftover `ok web` instance held the
    settings in memory and wrote them back, so flipping
    "Auto Start Game When App Starts" in the JSON had no effect - ok-ww.exe read
    the restored True and launched 鸣潮 during what was supposed to be a
    windowless update check. Same shape as MAA's master-copy problem: editing a
    file that a running process owns is editing a copy.
    """
    # **The script dies first, then the game.** The other way round leaves OK-WW
    # alive for a moment with the game gone, and it starts the game again: on
    # 2026-09-09 the user stopped the farm from his phone and found 鸣潮 still on
    # screen, because the game was killed first and OK-WW brought it back.
    # `pythonw.exe` counts too - the echo farm is launched with it precisely so no
    # console window covers the game, and matching only `python.exe` left it running.
    ps = ("Get-CimInstance Win32_Process -Filter "
          "\"Name='python.exe' OR Name='pythonw.exe'\" | "
          "Where-Object { $_.CommandLine -like '*ok-ww*' -or "
          "$_.CommandLine -like '*-m ok *' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run([_pwsh(), "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass
    for name in ("ok-ww.exe", "Wuthering Waves.exe",
                 "Client-Win64-Shipping.exe", "KRSDKExternal.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", name],
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    # 等两秒让进程真的退干净。`sleep` 可注入是为了测试：2026-09-08 量到
    # test_gameupdate 里 6 秒是**纯等**（CPU 3%），全套测试有 17 秒是这类空等。
    # 部署每次都要跑这套测试，空等直接变成部署时间。
    sleep(2)


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
    """Modification time of app.json. 0 means it could not be read.

    2026-08-26: the test used to look only at whether `available_versions` changed. But
    when OK-WW is already on the newest version, **the list is identical after the
    check** - so "it checked" and "it never checked at all" look the same to the relay,
    which can then only report that there is no sign of a check.
    In that run app.json's mtime had plainly moved forward (12:36:53, exactly the
    minutes it was launched), and **the file having been written is direct evidence that
    it ran** - more reliable than comparing contents.
    """
    try:
        return Path(okww_dir).joinpath(*_OKWW_APPJSON).stat().st_mtime
    except OSError:
        return 0.0


def _okww_await_update(root: Path, budget_s: float, before_version: str,
                       before_avail: tuple[str, ...],
                       before_stamp: float) -> tuple[str, bool, str]:
    """Watch app.json until OK-WW is done: returns (new version, did it check, error).

    Its own step because it answers two different questions at once: "did an update get
    installed" and "did it ask upstream at all". The second one is why a version was
    missed on 2026-08-25. It takes three tests (the version list was refreshed, app.json
    was rewritten, the version number changed) plus surviving OKWW_MIN_WAIT_SECONDS -
    the check is only scheduled 30 seconds after launch. Wedged between the launch and
    the cleanup, that whole set of tests would be invisible in run_okww's main line.
    """
    deadline = time.monotonic() + budget_s
    launched = time.monotonic()
    settled = ""
    checked = False           # saw it actually move: state / version list / version
    failed = ""
    while time.monotonic() < deadline:
        time.sleep(3)
        version, state, err, avail = _okww_state(root)
        if err:
            log.warning("预更新：OK-WW 更新报错 %s", err[:200])
            failed = err[:200]
            break
        if avail and avail != before_avail:
            checked = True    # list refreshed = it really did ask upstream
        if before_stamp and _okww_stamp(root) > before_stamp:
            # When it is already on the newest version the list content does not
            # change, but the file gets rewritten regardless. This is the direct
            # evidence that it really did start up and check.
            checked = True
        if state and state not in ("idle", ""):
            checked = True
            continue          # downloading or installing, keep waiting
        if version and version != before_version:
            settled, checked = version, True
            break
        if (checked and state == "idle"
                and time.monotonic() - launched >= OKWW_MIN_WAIT_SECONDS):
            break             # asked, the 30s check is past, and it has settled
    return settled, checked, failed


def _okww_report(problems: list[str] | None, budget_s: float,
                 before_version: str, before_avail: tuple[str, ...],
                 settled: str, checked: bool, failed: str) -> None:
    """Write the awaited result to the log, and raise an alarm where one is due.

    Its own step because the balance between these four branches was paid for with
    incidents: silence does **not** mean there was no update, so "no sign of any check"
    and "checked, and there really is nothing" have to be two different sentences; and
    finding a new version without installing it needs a sentence of its own too. Kept
    together, editing any one of them puts the other three in front of you.
    """
    if failed:
        _note(problems, f"OK-WW 预更新：更新报错 {failed}")
    elif settled:
        log.info("预更新：OK-WW 已更新 %s → %s", before_version, settled)
    elif not checked:
        # This is exactly what slipped through on 2026-08-25: silence != no update.
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
        settled, checked, failed = _okww_await_update(
            root, budget_s, before_version, before_avail, before_stamp)
        _okww_report(problems, budget_s, before_version, before_avail,
                     settled, checked, failed)
        # Close OK-WW *and* anything it may have pulled up with it. A
        # pre-update that leaves 鸣潮 running has not left the machine alone.
        _close(exe)
        _okww_quiesce()
        return f"OK-WW 已更新：{_span(before_version, settled)}" if settled else ""
    finally:
        _okww_autostart(root, was)
