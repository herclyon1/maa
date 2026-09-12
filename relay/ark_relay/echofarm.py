"""Farm 4-cost boss echoes until a wall-clock time.

Asked for on 2026-09-09 in these words: 「刷的时候不要按次数，而是时间来，
比如说刷到北京时间八点半这种」 - farm to a clock time, not to a repeat count.
OK-WW only understands `Repeat Farm Count`, so the count is set high and **this**
decides when to stop: the engine checks the deadline on every tick and stops the
run when it passes.

Two things this owes the operator, both learned the hard way elsewhere in this
repo:

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
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ, atomic_write_text

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
# OK-WW stops the whole task when the character dies: 2026-09-09 it farmed eleven laps
# and then died once, and everything stood still for the rest of the night. A farm that
# runs unattended has to get back up on its own, so silence this long relaunches it.
# A lap takes about a minute; a death plus a revive about two. Five minutes
# without a single lap means it is stuck, however busy the log looks.
RESTART_QUIET_MINUTES = 5
# Enough to cover a night, few enough that something genuinely broken still gives up
# and says so instead of relaunching into a wall until morning.
MAX_RESTARTS = 40
# The lowest level OK-WW offers. A boss's level does not change whether it drops an
# echo or what class the echo is - that is set by the data bank level - so a higher
# level only makes the fight harder. OK-WW's own description of the field says as
# much: "Choose the Lowest that Drop a Echo". On 2026-09-09 the saved config was at
# 90 and the team was killed by 天傀劫煞 in 36 seconds, twice, with the boss still
# above half health. The original value is restored when the farm ends.
FARM_LEVEL = "50"


# OK-WW's live config lives under its pyappify working directory, not at the
# install root - the same place okww_patches/core.py reaches for `src/task`.
# Getting this wrong cost the first attempt on 2026-09-09: the command answered
# 「找不到 OK-WW 的 FarmEchoTask 配置」 and nothing ran.
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
    from .statestore import StateStore  # noqa: PLC0415 - avoids an import cycle
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
    # 2026-09-09: running pythonw in the foreground kept cmd.exe's console window open
    # on top of the game for the whole run, right over the middle of the screen. OK-WW
    # screenshots the game window, read the black console instead of the game, and
    # every single teleport failed with 「Teleport to boss failed」 - three runs, no
    # echoes, and nothing in the log pointing at the window. pythonw.exe has no console
    # of its own, so once the .bat exits there is nothing covering the game.
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
# moving」 is not the same as 「the farm is moving」. On 2026-09-09 the game hung on a
# loading screen for sixteen minutes while the log kept scrolling, and a watchdog
# that only measured silence never fired once.
PROGRESS = ("farm echo", "enter combat", "刷声骸模式", "已经在场地里")
_TAIL_BYTES = 300_000


def quiet_minutes(now: datetime | None = None) -> "float | None":
    """Minutes since the farm last got anywhere. None when there is no log to read.

    Measured from the newest line that says something actually happened, not from
    the file's mtime: a stuck game is noisy, and noise is not progress.
    """
    from .weeklyboss import _okww_log  # noqa: PLC0415 - avoids an import cycle
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
    stamp = ""
    for line in tail.splitlines():
        if any(k in line for k in PROGRESS):
            stamp = line[:19]
    if not stamp:
        # Nothing in the whole tail: either the run just started (the caller已经
        # 用开跑时刻挡住这种) or it has been stuck for longer than the tail covers.
        try:
            touched = datetime.fromtimestamp(f.stat().st_mtime, tz=SERVER_TZ)
        except OSError:
            return None
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        return (now - touched).total_seconds() / 60.0
    try:
        last = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SERVER_TZ)
    except ValueError:
        return None
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    return (now - last).total_seconds() / 60.0


# What 「收工」 has to leave behind: nothing of OK-WW's and nothing of the game's.
GAME_PROCS = ("ok-ww.exe", "Wuthering Waves.exe",
              "Client-Win64-Shipping.exe", "KRSDKExternal.exe")
STOP_BAT = r"C:\ProgramData\ark-okww-stop.bat"
STOP_TASK = "ark-okww-stop"


def game_alive() -> "list[str]":
    """Which of the game's processes are still up. [] when the desktop is clean."""
    try:
        out = subprocess.run(["tasklist"], capture_output=True, timeout=30).stdout
        low = (out or b"").decode("utf-8", "replace").lower()
    except (OSError, AttributeError, subprocess.SubprocessError):
        return []
    return [n for n in GAME_PROCS if n.lower() in low]


def _kill_on_desktop() -> None:
    """Kill the game from the interactive desktop instead of from session 0.

    2026-09-09: 收工 reported success twice and 鸣潮 stayed on screen. The relay is a
    service in session 0, and `taskkill /F /IM` fired from there does not reach the
    game - it runs under the anti-cheat, in the logged-in session. Nothing noticed,
    because the return code was never looked at. So the kill goes out the same door
    the launch does: a .bat run by a scheduled task in the interactive session.
    """
    try:
        Path(STOP_BAT).write_text(
            "@echo off\r\n"
            + "\r\n".join(f'taskkill /F /IM "{n}"' for n in GAME_PROCS) + "\r\n",
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


def stop_okww(sleep=time.sleep) -> str:
    """End the farm and the game. '' when the desktop really is clean, otherwise a
    line saying what is still up - saying 「已收工」 over a running game is a lie."""
    subprocess.run(["schtasks", "/end", "/tn", TASK_NAME], capture_output=True)
    from .preupdate_okww import _okww_quiesce  # noqa: PLC0415
    _okww_quiesce()
    if not game_alive():
        return ""
    _kill_on_desktop()
    for _ in range(10):
        left = game_alive()
        if not left:
            return ""
        sleep(1)
    return "；**游戏没关掉（" + "、".join(game_alive()) + "），得去机器上手动关**"


def start(cfg, boss: int, until_hhmm: str, name: str = "",
          now: datetime | None = None) -> tuple[bool, str]:
    """Point OK-WW at one overworld boss and farm it until `until_hhmm`.

    `now` exists so the deadline can be pinned in a test. Without it the test had
    to trust the wall clock, and it started failing the moment the real time went
    past 08:30 - a test that only passes in the morning is not a test.
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
    until = resolve_until(until_hhmm, now)
    if until is None:
        return False, f"结束时刻看不懂：{until_hhmm!r}（要 08:30 这种）"
    running = current(cfg.state_dir)
    if running:
        return False, (f"已经在刷{running.get('name') or ''}了，刷到 {running.get('until')}。"
                       "要换目标先停掉现在这一趟")

    saved = json.loads(path.read_text(encoding="utf-8"))
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

    Asked for on 2026-09-09: 「他在跑刷声骸了，我想改一下时间，提前或者延后」. Stopping
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


def finish(cfg, why: str) -> str:
    """Stop the farm and put the config back. '' when nothing was running."""
    rec = current(cfg.state_dir)
    if not rec:
        return ""
    note = stop_okww() or ""
    _set_no_claim(False)
    note += "" if not no_claim_on() else "；**不领奖标记没删掉，周本会不领奖，去删 " + NO_CLAIM + "**"
    path = _cfg_path(getattr(cfg, "okww_dir", None) or os.environ.get("ARK_OKWW_DIR"))
    saved = rec.get("saved")
    if path and path.is_file() and isinstance(saved, dict):
        try:
            atomic_write_text(path, json.dumps(saved, ensure_ascii=False, indent=1))
            back = json.loads(path.read_text(encoding="utf-8"))
            if back.get("Teleport to Boss") != saved.get("Teleport to Boss"):
                note = "；**刷声骸用的 Boss 设置没改回去，明早的周本会去打今晚刷声骸的那个 Boss，需要人工改回**"
        except OSError:
            note = "；**刷声骸用的 Boss 设置没能改回去，明早的周本会去打今晚刷声骸的那个 Boss，需要人工改回**"
    else:
        note = "；**找不到配置文件，没能还原**"
    _store(cfg.state_dir).pop("queues", "echo_farm")
    started = rec.get("started") or "?"
    tries = int(rec.get("restarts") or 0)
    again = f"，中途角色阵亡重开了 {tries} 次" if tries else ""
    return f"刷{rec.get('name') or ''}结束（{why}）。{started} 开始{again}，配置已还原{note}"


def tick(cfg, now: datetime | None = None) -> str:
    """Called every engine tick. Returns a line to push when the farm just ended."""
    rec = current(cfg.state_dir)
    if not rec:
        return ""
    until = deadline_of(rec)
    if until is None:
        return finish(cfg, "结束时刻读不出来，为安全起见停掉")
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    if now >= until:
        return finish(cfg, f"到点了（{until:%H:%M}）")
    quiet = quiet_minutes(now)
    if quiet is None or quiet < RESTART_QUIET_MINUTES:
        return ""
    # Do not judge a run that only just started, and leave a relaunch time to write
    # its first line before deciding it is quiet again.
    for key in ("restarted", "started"):
        when = _stamp(rec.get(key))
        if when is not None:
            if (now - when).total_seconds() / 60.0 < RESTART_QUIET_MINUTES:
                return ""
            break
    tries = int(rec.get("restarts") or 0)
    if tries >= MAX_RESTARTS or (tries and quiet >= STALL_MINUTES):
        return finish(cfg, f"已经 {quiet:.0f} 分钟没刷到任何东西"
                           + (f"，重开 {tries} 次都没救回来" if tries else "")
                           + "，先停下来")
    # The first relaunch restarts OK-WW only, which is cheap and fixes the common
    # case (the script died, the game is fine). From the second on, the game is
    # restarted too: on 2026-09-09 the game itself wedged on a loading screen -
    # 「等不到回大世界」 - and relaunching the script against a wedged client did
    # nothing at all, twice, while the farm stood still for sixteen minutes.
    if tries >= 1:
        log.warning("刷声骸：重开脚本没用，连游戏一起重启（第 %d 次）", tries + 1)
        stop_okww()
    ok, why = _launch()
    rec["restarts"] = tries + 1
    rec["restarted"] = now.strftime("%Y-%m-%d %H:%M")
    _store(cfg.state_dir).set("queues", "echo_farm", rec)
    if ok:
        log.warning("刷声骸：OK-WW 停了 %.0f 分钟，已经重开第 %d 次", quiet, tries + 1)
        return ""
    return finish(cfg, f"OK-WW 停了，重开也失败了：{why}")
