"""Farm 4-cost boss echoes until a wall-clock time.

Farm to a clock time, not to a repeat count; the user's words on 2026-09-09:
「刷的时候不要按次数，而是时间来， (not by count but by time,
比如说刷到北京时间八点半这种」 (say, until half past eight Beijing time). OK-WW only understands
`Repeat Farm Count`, so the count is set high and **this** decides when to stop:
the engine checks the deadline on every tick and stops the run when it passes.

Two rules:

* **The previous FarmEchoTask config is saved and put back.** That file is shared
  with the daily's weekly-boss step, so leaving it pointed at an overworld boss
  would silently change what the 09:00 run does.
* **Starting is a session-1 problem.** The relay lives in session 0 and has no
  desktop, so OK-WW is launched the way AUTO-MAS is revived - a .bat run through
  a scheduled task - not with Popen, which would start a process that can never
  see the game window.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.echofarm")

TASK_NAME = "ark-okww-farm"
BAT = r"C:\ProgramData\ark-okww-farm.bat"
# FarmEchoTask is one-time task 2 in OK-WW's own list (okww-task.sh --list).
OKWW_TASK_INDEX = 2
# High enough that the clock always ends the run, low enough to be a real number.
BIG_COUNT = 100000
# While this file exists the claim patch in FarmEchoTask refuses to claim the boss
# reward. Farming 4-cost echoes is free; claiming costs 60 waveplates every time, and
# an unattended overnight loop would empty both the waveplates and the reserve.
NO_CLAIM = r"C:\ProgramData\ark-okww-farm.no-claim"
# Give up only after restarts have genuinely had their chance. From the second
# restart the game is killed too, so half an hour with no lap at all means neither
# the script nor a fresh client can get anywhere - worth stopping and saying so.
STALL_MINUTES = 30
# OK-WW v3.7.4 gets back up after a death by itself only up to 3 times, and only
# with teleport-to-boss on (FarmEchoTask.do_run, max_recovery_retries=3,
# FarmEchoTask.py:209-222); after that it logs 「exceeded recovery retries」 and
# stops, and any other failure ends the task. So an unattended farm still has to
# get back up on its own: silence this long relaunches it. A lap takes about a
# minute; a death plus a revive about two. Five minutes without a single lap means
# it is stuck, however busy the log looks.
RESTART_QUIET_MINUTES = 5
# Enough to cover a night, few enough that something genuinely broken still gives up
# and says so instead of relaunching into a wall until morning.
MAX_RESTARTS = 40
# The lowest boss level that drops an echo. OK-WW's own description of the field is
# "Choose the Lowest that Drop a Echo" (FarmEchoTask.py:38, v3.7.4), i.e. some lower
# levels drop none, and its default for the field is "80" (:24). The user, 2026-10-13:
# 「刷声骸确实是80级才能刷，50级不可能刷」. The earlier "50" (868d09f5) had no source and
# would have farmed all night for nothing. The original value is restored when the
# farm ends. It is only the value written to FarmEchoTask.json: it applies where a
# level page appears (the override picks it there, 35d6166b). Boss 1 天傀劫煞's book
# entry opens the team screen directly, and the 10-13 run fought at the game's
# remembered Lv.90 with 80 set - so what owners read is the level the game showed
# (level_since), never this.
FARM_LEVEL = "80"


# OK-WW's live config lives under its pyappify working directory, not at the
# install root - the same working directory okww_overlay.py installs into.
_WORKING = ("data", "apps", "ok-ww", "working")


def _cfg_path(okww_dir) -> "Path | None":
    if not okww_dir:
        return None
    root = Path(okww_dir)
    here = root.joinpath(*_WORKING, "configs", "FarmEchoTask.json")
    if here.is_file():
        return here
    # A directory that already points inside working/ is accepted as it is.
    flat = root / "configs" / "FarmEchoTask.json"
    return flat if flat.is_file() else here


def _store(state_dir):
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415 - avoids an import cycle
    return StateStore(Path(state_dir))


def current(state_dir) -> dict:
    """The farm in progress, or {}."""
    rec = _store(state_dir).get("queues", "echo_farm")
    return dict(rec) if isinstance(rec, dict) else {}


def deadline_of(rec: dict) -> datetime | None:
    try:
        return datetime.strptime(str(rec.get("until")), "%Y-%m-%d %H:%M").replace(tzinfo=SERVER_TZ)
    except (TypeError, ValueError):
        return None


def _stamp(text) -> datetime | None:
    try:
        return datetime.strptime(str(text), "%Y-%m-%d %H:%M").replace(tzinfo=SERVER_TZ)
    except (TypeError, ValueError):
        return None


def _started_at(rec: dict) -> datetime | None:
    return _stamp(rec.get("started"))


def resolve_until(hhmm: str, now: datetime | None = None) -> datetime | None:
    """'08:30' -> the next moment it is 08:30 on the machine's clock."""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    try:
        hh, mm = (int(x) for x in str(hhmm).strip().split(":"))
    except (TypeError, ValueError):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return when if when > now else when + timedelta(days=1)


def _write_cfg(path: Path, values: dict) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(values)
    atomic_write_text(path, json.dumps(doc, ensure_ascii=False, indent=1))
    return json.loads(path.read_text(encoding="utf-8"))


def _launch() -> tuple[bool, str]:
    """Start OK-WW's FarmEchoTask on the interactive desktop."""
    root = Path(os.environ.get("ARK_OKWW_DIR") or r"D:\ark\okww")
    py = root / "data" / "apps" / "ok-ww" / "python" / "pythonw.exe"
    main = root.joinpath(*_WORKING, "main.py")
    if not py.is_file() or not main.is_file():
        return False, f"找不到 OK-WW 的程序（{py} / {main}）"
    # `start ""` and nothing else: the .bat must hand OK-WW off and end immediately.
    # A .bat that waited on pythonw would keep cmd.exe's console window open over the
    # game, and OK-WW, which screenshots the game window, would read the console
    # instead (every teleport then fails). pythonw.exe has no console of its own, so
    # once the .bat exits nothing covers the game.
    Path(BAT).write_text(
        f'@echo off\r\ncd /d "{main.parent}"\r\n'
        f'start "" "{py}" "{main}" -t {OKWW_TASK_INDEX} -e\r\n',
        encoding="utf-8")
    subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"], capture_output=True)
    mk = subprocess.run(["schtasks", "/create", "/tn", TASK_NAME, "/tr", BAT, "/sc", "once",
                         "/st", "00:00", "/ru", "Administrator", "/it", "/f"], capture_output=True)
    if mk.returncode != 0:
        return False, f"建计划任务失败：{mk.stderr.decode('utf-8', 'replace')[:120]}"
    run = subprocess.run(["schtasks", "/run", "/tn", TASK_NAME], capture_output=True)
    if run.returncode != 0:
        return False, f"启动计划任务失败：{run.stderr.decode('utf-8', 'replace')[:120]}"
    return True, ""


def _set_no_claim(on: bool) -> None:
    """Turn the do-not-claim marker on or off. Never raises: a farm must still stop
    even when the marker cannot be removed, and the removal is reported instead."""
    try:
        if on:
            Path(NO_CLAIM).write_text("farming 4c echoes, do not spend waveplates\n",
                                      encoding="utf-8")
        else:
            Path(NO_CLAIM).unlink(missing_ok=True)
    except OSError:
        log.warning("不领奖标记文件 %s 写不动（on=%s）", NO_CLAIM, on)


def no_claim_on() -> bool:
    return Path(NO_CLAIM).exists()


# What counts as the farm getting somewhere. A wedged game still produces plenty of
# log lines - window-size changes, update checks, feature loads - so 「the log is
# moving」 is not the same as 「the farm is moving」: a game hung on a loading screen
# keeps the log scrolling.
# Each entry is a sentence OK-WW v3.7.4 or the overrides write today:
#   farm echo / enter combat       a lap picked up / fought (FarmEchoTask.py:188-200,
#                                  combat/CombatCheck.py:181)
#   teleport_to_boss prepared as   back in the realm (FarmEchoTask.py:271)
#   限时提前开放：确认后直接进场       the early-open entry put us in the arena (overrides)
#   刷声骸模式：复活成功               revived and farming on (overrides)
# Not the bare 「刷声骸模式」 prefix: its other sentences are 「not recognised, not
# clicking」, which is the farm stuck, not moving.
PROGRESS = ("farm echo", "enter combat", "teleport_to_boss prepared as",
            "限时提前开放：确认后直接进场", "刷声骸模式：复活成功")
_TAIL_BYTES = 300_000


def _line_time(line: str) -> "datetime | None":
    """The timestamp an OK-WW log line starts with (「2026-09-07 10:06:52,779 INFO …」)."""
    try:
        return datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=SERVER_TZ)
    except ValueError:
        return None


def quiet_minutes(now: datetime | None = None, since: "datetime | None" = None) -> "float | None":
    """Minutes since the farm last got anywhere. None when there is no log to read,
    or nothing to measure from.

    Measured from the newest line that says something actually happened, not from
    the file's mtime: a stuck game is noisy, and noise is not progress.

    `since` is when this launch began (the run record's `restarted`, else `started`).
    When the tail holds no progress line since then, the farm has got nowhere since
    at least then, so the quiet time is measured from it. The file's mtime cannot stand
    in: a game stuck in a retry loop logs 20-39 KB a minute, so the 300 KB tail spans
    only 8-35 minutes and the file is always fresh - quiet read about 0 and neither
    the restart nor the stall stop ever fired. Without `since`, the first timestamp
    in the tail is the floor (no progress at least since then).
    """
    from ark_relay.features.weekly.weeklyboss import _okww_log  # noqa: PLC0415 - avoids an import cycle
    f = _okww_log()
    if not f:
        return None
    try:
        size = f.stat().st_size
        with f.open("rb") as fh:
            if size > _TAIL_BYTES:
                fh.seek(size - _TAIL_BYTES)
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    last = None
    first = None
    for line in tail.splitlines():
        at = _line_time(line)
        if at is None:
            continue
        first = first or at
        if any(k in line for k in PROGRESS):
            last = at
    if last is None:
        # Nothing in the whole tail: either the run just started (tick already skips
        # a run that young) or it has been stuck for longer than the tail covers.
        last = since or first
        if last is None:
            return None
    elif since is not None and last < since:
        # Progress from an earlier session in the same day's file says nothing about
        # this launch. 10-12: farm started 15:23 after a morning run; its log, cut
        # at 15:25:32 and read with a 15:28 restart at 15:33:30, gave 225.6 minutes
        # from an 11:47 line instead of 5.5 from the restart.
        last = since
    return (now - last).total_seconds() / 60.0


def progress_since(started: "datetime | None") -> "int | None":
    """How many progress lines (PROGRESS) OK-WW logged since `started`; None when
    that cannot be told (no start time, no log, unreadable). Every log file in the
    folder written since the start is read, so a night that crosses OK-WW's log
    rotation is counted whole."""
    lines = _lines_since(started)
    if lines is None:
        return None
    return sum(1 for _at, line in lines if any(k in line for k in PROGRESS))


def _lines_since(started: "datetime | None") -> "list[tuple[datetime, str]] | None":
    """(time, line) of every OK-WW log line since `started`, oldest first, from every
    log file written since then; None when that cannot be read."""
    from ark_relay.features.weekly.weeklyboss import _okww_log  # noqa: PLC0415 - avoids an import cycle
    f = _okww_log()
    if started is None or not f:
        return None
    try:
        files = {f} | {q for q in f.parent.glob("*.log*")
                       if q.is_file() and q.stat().st_mtime >= started.timestamp()}
        out = []
        for q in files:
            for line in q.read_text(encoding="utf-8", errors="replace").splitlines():
                at = _line_time(line)
                if at is not None and at >= started:
                    out.append((at, line))
        out.sort(key=lambda x: x[0])
        return out
    except OSError:
        return None


# FarmEchoTask logs what it read off the boss's level badge on every lap
# (upstream FarmEchoTask.py:721, the OCR boxes starting with "Lv"), e.g.
#   FarmEchoTask:boss_string is [Lv.90天傀劫煞_0.97]
# and, OCR'd with a stray dot, [Lv.90.天傀劫煞_0.97]; "[]" when nothing was read.
# This is the level the game fought at: "Boss Level" in FarmEchoTask.json applies only
# where a level page appears, and boss 1's book entry opens the team screen directly
# (10-13 run), so the game keeps the level it remembers for that realm.
_BOSS_STRING = re.compile(r"FarmEchoTask:boss_string is \[(.*)\]")
_BOSS_BOX = re.compile(r"^L[Vv]\.?\s*(\d{1,3})\.?\s*(.*?)_\d+(?:\.\d+)?$")


def level_since(started: "datetime | None") -> "tuple[str, str] | None":
    """(level, boss name as read) from the newest boss_string line since `started`
    that holds a level; None when none was read (or the log cannot be read)."""
    found = None
    for _at, line in _lines_since(started) or []:
        m = _BOSS_STRING.search(line)
        if not m:
            continue
        for box in m.group(1).split(", "):
            b = _BOSS_BOX.match(box.strip())
            if b:
                found = (b.group(1), b.group(2).strip())
                break
    return found


# What 「收工」 has to leave behind: nothing of OK-WW's and nothing of the game's.
GAME_PROCS = ("ok-ww.exe", "Wuthering Waves.exe",
              "Client-Win64-Shipping.exe", "KRSDKExternal.exe")
STOP_BAT = r"C:\ProgramData\ark-okww-stop.bat"
STOP_TASK = "ark-okww-stop"


# What game_alive names when tasklist itself fails: not a process name, so nothing
# is ever killed by it, and never [] - an unreadable list is not a clean desktop
# (the way preupdate_okww._okww_left names an unreadable launcher list).
UNREADABLE = "鸣潮（读不到正在运行的程序列表，查不到它还开没开着）"


# What game_alive names when OK-WW's python processes cannot be listed.
UNREADABLE_SCRIPT = "OK-WW 脚本（查不到它还开没开着）"


# What game_alive names for OK-WW's python while it runs - once, however many there
# are; the owner reads this, so no program file name and no process number.
OKWW_SCRIPT = "OK-WW 脚本"


def game_alive(timeout: "float | None" = None) -> "list[str]":
    """Which of the game's processes are still up, OK-WW's own python included.
    [] only when the desktop is clean.

    OK-WW runs as pythonw.exe, a name tasklist cannot tell from any other python,
    so it is looked for by command line (preupdate_okww.okww_python_pids). Left
    out, a stop could report clean while OK-WW lived on and later wrote its
    in-memory config over the restored FarmEchoTask.json.
    `timeout` bounds the PowerShell query (okww_python_pids); None is its guard.
    """
    try:
        out = subprocess.run(["tasklist"], capture_output=True, timeout=30).stdout
        low = (out or b"").decode("utf-8", "replace").lower()
    except (OSError, AttributeError, subprocess.SubprocessError) as exc:
        log.info("读不到正在运行的程序列表（%s: %s），游戏算作没确认关掉",
                 type(exc).__name__, exc)
        return [UNREADABLE]
    from ark_relay.features.preupdate.preupdate_okww import okww_python_pids  # noqa: PLC0415 - preupdate_okww imports this module
    pids = okww_python_pids(timeout)
    script = [UNREADABLE_SCRIPT] if pids is None else [OKWW_SCRIPT] if pids else []
    return [n for n in GAME_PROCS if n.lower() in low] + script


# The whole stop-the-old-script step, PowerShell calls included: each list call may
# otherwise run to its 60 s hang guard, and ten of them held a tick for ten minutes.
# Measured on the game machine 2026-10-13 11:08 Beijing: okww_python_pids() took
# 0.54, 0.39, 0.39, 0.41, 0.41 s (5 runs, OK-WW running, its real PID found), so
# 15 s (the bound the review of this branch set) holds the stop and ~30 looks.
STOP_SCRIPT_SECONDS = 15


def stop_okww_script(sleep=time.sleep, clock=time.monotonic) -> str:
    """Stop only OK-WW's python (the script), leaving the game up. '' once none is
    left; "running" when one is still listed at the end; "unreadable" when the list
    could not be read twice in a row.

    Before a relaunch: `_launch` starts a new `pythonw main.py -t 2 -e`, and an old
    one still alive would drive the same game alongside it. Every PowerShell call
    gets only the time left of STOP_SCRIPT_SECONDS (at least one second), so the
    step ends in about that long whatever pwsh does."""
    from ark_relay.features.preupdate.preupdate_okww import _stop_okww_python, okww_python_pids  # noqa: PLC0415
    end = clock() + STOP_SCRIPT_SECONDS

    def left() -> float:
        return max(1.0, end - clock())

    _stop_okww_python(timeout=left())
    misses = 0
    while True:
        pids = okww_python_pids(timeout=left())
        if pids == []:
            return ""
        if pids is None:
            misses += 1
            if misses >= 2:
                return "unreadable"
            continue            # an unreadable list is asked again at once, once
        misses = 0
        if clock() >= end:
            return "running"
        sleep(1)


def _kill_on_desktop(pids=()) -> None:
    """Kill the game from the interactive desktop instead of from session 0.

    The relay is a service in session 0, and `taskkill /F /IM` fired from there does
    not reach the game - it runs under the anti-cheat, in the logged-in session. So
    the kill goes out the same door the launch does: a .bat run by a scheduled task
    in the interactive session.

    `pids`: processes to stop by PID as well - the Kuro launcher, whose names
    (launcher.exe / launcher_main.exe) are too common to kill by name.
    """
    lines = [f'taskkill /F /IM "{n}"' for n in GAME_PROCS]
    lines += [f"taskkill /F /PID {int(p)}" for p in pids]
    try:
        Path(STOP_BAT).write_text(
            "@echo off\r\n" + "\r\n".join(lines) + "\r\n",
            encoding="utf-8")
    except OSError:
        log.warning("收工：写不出 %s，没法从桌面那边关游戏", STOP_BAT)
        return
    subprocess.run(["schtasks", "/delete", "/tn", STOP_TASK, "/f"], capture_output=True)
    mk = subprocess.run(["schtasks", "/create", "/tn", STOP_TASK, "/tr", STOP_BAT, "/sc", "once",
                         "/st", "00:00", "/ru", "Administrator", "/it", "/f"], capture_output=True)
    if mk.returncode != 0:
        log.warning("收工：建不了关游戏的计划任务")
        return
    subprocess.run(["schtasks", "/run", "/tn", STOP_TASK], capture_output=True)


# The whole wrap-up stop, PowerShell calls included. Before, the ten looks after the
# desktop kill each ran a process query free to take its 60 s guard: one tick could
# last over ten minutes. Measured on the game machine 2026-10-13 11:08 Beijing: that
# query (okww_python_pids) took 0.39-0.54 s over 5 runs, so a normal stop - three
# queries, the 2 s pause, ten one-second looks - fits in about 20 s; 60 s is that
# with room, and what one query's hang guard alone allowed before.
STOP_OKWW_SECONDS = 60


def stop_okww(sleep=time.sleep, clock=time.monotonic) -> str:
    """End the farm and the game. '' when the desktop really is clean, otherwise a
    line saying what is still up - saying 「已收工」 over a running game is a lie.

    Bounded by STOP_OKWW_SECONDS: each PowerShell call gets only the time left (at
    least one second), and the looks stop when it runs out. Out of time without a
    clean look, the line says the game or the script may still be up. The taskkill
    / tasklist / schtasks calls keep their own guards and are not cut short.
    """
    end = clock() + STOP_OKWW_SECONDS

    def left() -> float:
        return max(1.0, end - clock())

    subprocess.run(["schtasks", "/end", "/tn", TASK_NAME], capture_output=True)
    from ark_relay.features.preupdate.preupdate_okww import _okww_quiesce, okww_python_pids  # noqa: PLC0415
    _okww_quiesce(sleep=sleep, left=left)
    still = game_alive(left())
    if not still:
        return ""
    _kill_on_desktop(pids=okww_python_pids(left()) or ())
    for _ in range(10):
        if clock() >= end:
            return texts.echo_farm_stop_unconfirmed(still)
        still = game_alive(left())
        if not still:
            return ""
        sleep(1)
    return texts.echo_farm_game_left(still)


def _truth(cfg, working: Path) -> dict:
    """What FarmEchoTask.json should look like after the farm: the AUTO-MAS master.

    AUTO-MAS copies the master over the working file before every run and puts
    the working file back afterwards, so the working file is whatever the last
    farm left there; restoring a copy of it could restore another farm's settings.
    The daily runs from the master.
    """
    from ark_relay.core.config import master_config_dir  # noqa: PLC0415
    d = master_config_dir(getattr(cfg, "automas_dir", None), "DailyTask.json")
    if d and (d / "FarmEchoTask.json").is_file():
        try:
            return json.loads((d / "FarmEchoTask.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.exception("母本的 FarmEchoTask.json 读不出来，退回 working 那份")
    return json.loads(working.read_text(encoding="utf-8"))


def start(cfg, boss: int, until_hhmm: str, name: str = "",
          now: datetime | None = None, sent: datetime | None = None) -> tuple[bool, str]:
    """Point OK-WW at one overworld boss and farm it until `until_hhmm`.

    `now` pins the clock in tests.

    `sent` is when the phone sent the order. A press made while the machine was off
    waits in the mailbox until the next boot; read against the boot time, 「刷到
    08:30」 sent at 22:00 and acted on at 08:45 would roll to the next day's 08:30.
    So the deadline is resolved against `sent`, and an order whose deadline passed
    before it could be acted on is refused, as skip_today refuses a day already gone.
    """
    path = _cfg_path(getattr(cfg, "okww_dir", None) or os.environ.get("ARK_OKWW_DIR"))
    if not path or not path.is_file():
        return False, "找不到 OK-WW 的 FarmEchoTask 配置"
    try:
        boss = int(boss)
    except (TypeError, ValueError):
        return False, f"「第几个」要是数字，收到 {boss!r}"
    if not 1 <= boss <= 30:
        return False, f"「第几个」超出范围：{boss}"
    until = resolve_until(until_hhmm, sent or now)
    if until is None:
        return False, f"结束时刻看不懂：{until_hhmm!r}（要 08:30 这种）"
    at = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    if sent is not None and until <= at:
        return False, (f"这条「刷到 {until:%H:%M}」是 {sent.astimezone(SERVER_TZ):%m-%d %H:%M} 发的，"
                       f"机器 {at:%m-%d %H:%M} 才收到，那时已经过了 {until:%H:%M}，没有开刷。"
                       "要刷就再按一次")
    running = current(cfg.state_dir)
    if running:
        return False, (f"已经在刷{running.get('name') or ''}了，刷到 {running.get('until')}。"
                       "要换目标先停掉现在这一趟")

    saved = _truth(cfg, path)
    back = _write_cfg(path, {"Teleport to Boss": "Boss Challenge",
                             "Which Boss Challenge to Teleport": boss,
                             "Boss Level": FARM_LEVEL,
                             "Repeat Farm Count": BIG_COUNT})
    if back.get("Which Boss Challenge to Teleport") != boss:
        atomic_write_text(path, json.dumps(saved, ensure_ascii=False, indent=1))
        return False, "写进去之后读出来和写的不一样，设置已改回，没有开跑"

    _set_no_claim(True)
    ok, why = _launch()
    if not ok:
        _set_no_claim(False)
        atomic_write_text(path, json.dumps(saved, ensure_ascii=False, indent=1))
        return False, f"{why}；配置已还原"

    _store(cfg.state_dir).set("queues", "echo_farm", {
        "boss": boss, "name": name or f"第 {boss} 个",
        "until": until.strftime("%Y-%m-%d %H:%M"),
        "started": (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
                   .strftime("%Y-%m-%d %H:%M"),
        "saved": saved,
    })
    return True, f"开始刷{name or f'第 {boss} 个'}，刷到 {until:%H:%M} 为止（机器时间）"


def retime(cfg, until_hhmm: str, now: datetime | None = None) -> tuple[bool, str]:
    """Move a running farm's finishing time, earlier or later.

    The user, 2026-09-09: 「他在跑刷声骸了，我想改一下时间，提前或者延后」. Stopping
    and starting again would rewrite the saved config and lose the restart count, so
    the deadline is edited in place and nothing else is touched.
    """
    rec = current(cfg.state_dir)
    if not rec:
        return False, "现在没有在刷声骸，没有可改的时刻"
    until = resolve_until(until_hhmm, now)
    if until is None:
        return False, f"结束时刻看不懂：{until_hhmm!r}（要 21:00 这种）"
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    was = rec.get("until")
    rec["until"] = until.strftime("%Y-%m-%d %H:%M")
    _store(cfg.state_dir).set("queues", "echo_farm", rec)
    # A time already past rolls to tomorrow, exactly as it does when a farm is
    # started - one rule, not two. Stopping now is what the 收工 button is for.
    mins = int((until - now).total_seconds() // 60)
    return True, (f"刷{rec.get('name') or '声骸'}的收工时刻从 {str(was)[11:]} 改成 "
                  f"{until:%H:%M}（还剩 {mins // 60} 小时 {mins % 60} 分）")


# Wrap-up lines of a stop by hand (finish(): the phone's stop-farm order, the red button)
# that say something went wrong, waiting for the phone channel to push them to the
# group (push_manual_trouble) - those callers have no notifier of their own.
MANUAL_TROUBLE: list[str] = []


def finish(cfg, why: str) -> str:
    """Stop the farm and put the config back. '' when nothing was running.

    A wrap-up that went wrong is also queued on MANUAL_TROUBLE, so it reaches the group
    (the owner, 2026-10-12 20:04: an error left unreported is worse than the error)."""
    note, failed = _finish(cfg, why)
    if failed:
        MANUAL_TROUBLE.append(note)
    return note


def push_wrapup(notifier, note: str, failed: bool):
    """Push one wrap-up line: one that went wrong is a group alarm, a clean one info."""
    if failed:
        return notifier.send(texts.ECHO_FARM_TROUBLE, note, alert=True)
    return notifier.send(texts.ECHO_FARM_DONE, note)


def push_manual_trouble(notifier) -> None:
    """Push every queued failed wrap-up of a stop by hand (MANUAL_TROUBLE) to the group,
    the same alarm as at the deadline. A clean one stays on the phone receipt."""
    while MANUAL_TROUBLE:
        push_wrapup(notifier, MANUAL_TROUBLE.pop(0), True)


def _finish(cfg, why: str, failed: bool = False, judge_progress: bool = False) -> "tuple[str, bool]":
    """finish(), and whether its line says something went wrong: `failed` (the farm was
    stopped by a fault: the caller says so), the game left open, the no-claim marker left,
    the boss setting not put back, the config not found.

    The line says how many progress lines OK-WW logged since the start.
    `judge_progress` (the deadline): none, or a count that cannot be read, is a
    failure too - a night that farmed nothing used to end as a clean 「到点了」.
    A stop by hand is not judged on it: it may come minutes after the start."""
    rec = current(cfg.state_dir)
    if not rec:
        return "", False
    laps = progress_since(_started_at(rec))
    level = level_since(_started_at(rec))
    note = stop_okww() or ""
    _set_no_claim(False)
    note += "" if not no_claim_on() else texts.echo_farm_no_claim_left(NO_CLAIM)
    path = _cfg_path(getattr(cfg, "okww_dir", None) or os.environ.get("ARK_OKWW_DIR"))
    saved = rec.get("saved")
    if path and path.is_file() and isinstance(saved, dict):
        try:
            atomic_write_text(path, json.dumps(saved, ensure_ascii=False, indent=1))
            back = json.loads(path.read_text(encoding="utf-8"))
            if back.get("Teleport to Boss") != saved.get("Teleport to Boss"):
                note += texts.echo_farm_boss_not_back(True)
        except OSError:
            note += texts.echo_farm_boss_not_back(False)
    else:
        note += "；**找不到配置文件，没能还原**"
    _store(cfg.state_dir).pop("queues", "echo_farm")
    started = rec.get("started") or "?"
    tries = int(rec.get("restarts") or 0)
    again = f"，中途角色阵亡重开了 {tries} 次" if tries else ""
    if judge_progress and not laps:
        failed = True
    name = rec.get("name") or ""
    return (f"刷{name}{texts.echo_farm_level(level, name)}结束（{why}）。{started} 开始{again}，{texts.echo_farm_progress(laps)}，"
            f"配置已还原{note}", failed or bool(note))


def tick(cfg, now: datetime | None = None) -> str:
    """Called every engine tick. Returns a line to push when the farm just ended."""
    return tick_result(cfg, now)[0]


def tick_result(cfg, now: datetime | None = None) -> "tuple[str, bool]":
    """tick(), and whether the wrap-up line says something went wrong (_finish): the
    engine pushes such a line to the group, a clean one to Server酱."""
    rec = current(cfg.state_dir)
    if not rec:
        return "", False
    until = deadline_of(rec)
    if until is None:
        return _finish(cfg, "结束时刻读不出来，为安全起见停掉", failed=True)
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    if now >= until:
        return _finish(cfg, f"到点了（{until:%H:%M}）", judge_progress=True)
    quiet = quiet_minutes(now, _stamp(rec.get("restarted")) or _started_at(rec))
    if quiet is None or quiet < RESTART_QUIET_MINUTES:
        return "", False
    # Do not judge a run that only just started, and leave a relaunch time to write
    # its first line before deciding it is quiet again.
    for key in ("restarted", "started"):
        when = _stamp(rec.get(key))
        if when is not None:
            if (now - when).total_seconds() / 60.0 < RESTART_QUIET_MINUTES:
                return "", False
            break
    tries = int(rec.get("restarts") or 0)
    if tries >= MAX_RESTARTS or (tries and quiet >= STALL_MINUTES):
        return _finish(cfg, f"已经 {quiet:.0f} 分钟没刷到任何东西"
                            + (f"，重开 {tries} 次都没救回来" if tries else "")
                            + "，先停下来", failed=True)
    # The first relaunch restarts OK-WW only, which is cheap and fixes the common
    # case (the script died, the game is fine). From the second on, the game is
    # restarted too: when the game itself wedges on a loading screen
    # (「等不到回大世界」), relaunching the script against it does nothing.
    if tries >= 1:
        log.warning("刷声骸：重开脚本没用，连游戏一起重启（第 %d 次）", tries + 1)
        stop_okww()
    else:
        # The game stays up on the first try, but the old OK-WW must not: a second
        # `pythonw main.py -t 2 -e` next to a live one has two scripts driving one game.
        # A script still listed at the end, or a list unreadable twice, gets the full
        # stop instead: a relaunch next to a script nobody can see is the case above.
        why = stop_okww_script()
        if why:
            log.warning("刷声骸：旧的 OK-WW 脚本%s，连游戏一起关了再重开",
                        "停不掉" if why == "running" else "停没停查了两次都查不到")
            stop_okww()
    ok, why = _launch()
    rec["restarts"] = tries + 1
    rec["restarted"] = now.strftime("%Y-%m-%d %H:%M")
    _store(cfg.state_dir).set("queues", "echo_farm", rec)
    if ok:
        log.warning("刷声骸：OK-WW 停了 %.0f 分钟，已经重开第 %d 次", quiet, tries + 1)
        return "", False
    return _finish(cfg, f"OK-WW 停了，重开也失败了：{why}", failed=True)
