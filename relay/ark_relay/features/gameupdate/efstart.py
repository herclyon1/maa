"""Start Endfield (终末地) through the official Hypergryph launcher, for the relay's own starts.

Client 1.6.3 (「丹青渡」, 2026-10-15) refuses to run unless its parent process is the
running launcher: started as Endfield.exe directly it shows 「游戏启动失败」
「请通过官方启动器打开游戏」 (MaaEnd/MaaEnd#6469; #6457 traces it to the SDK checking
the direct parent process). On 2026-10-15 15:14 AUTO-MAS started Endfield.exe itself
(account switch "MAS": Game.Path, app/task/MaaEnd/AutoProxy.py:950-967 in v5.6.2) and
every MaaEnd task failed. From 10-15 to 10-16 every such start ran this helper instead;
since AUTO-MAS v5.7.0-beta.4 (Game.LaunchMode "Launcher", PR #1394) AUTO-MAS starts the
game through the launcher itself for its runs, and efstart_setup.py hands those back to it
(Game.Path on Endfield.exe again, the helper's preAction out of the MaaEnd master). The
helper still serves the relay's own start: the gathering retry (collect_retry), through
run_on_desktop.

What one start does (start_via_launcher):

* The game window is up (FindWindow UnityWndClass / "Endfield", what AUTO-MAS's login()
  looks for) and is not the refusal dialog: exit 0, nothing clicked.
* Endfield.exe runs but shows the refusal dialog, or has no window for
  RUNNING_NO_WINDOW_S: it is closed and started again through the launcher.
* Otherwise: Launcher.exe is started when Games.exe is not running, 「DirectX 11 启动」
  under 「开始游戏」 is made sure to be ticked (2026-10-15 15:33: a game started without
  it reached the title, and MaaEnd then failed with 「当前环境识别异常，请使用 D3D11
  启动游戏…」), 「开始游戏」 is clicked, and the game is watched up to its title screen
  「点击任意位置继续」; on the terms prompt 「游戏协议条款提示」 its button 「同意并继续」 is
  clicked (the owner, 10-15: not to be asked about it), 「请重启游戏」 restarts it once through the launcher.
* Exits non-zero, with a log line and a screenshot path, on a phone-number login screen
  (needs a person), a launcher or game that wants a client update first (the relay's
  game update does that after the queue), the refusal dialog after a launcher start, a
  launcher that cannot be driven, or a timeout.

Several starters fire at once, so a named mutex lets one drive; a later one waits for it
and then looks again. The helper runs on the interactive desktop with the relay's own
pythonw.exe, from the trampoline efstart_setup writes into state/efstart/. pythonw has no
stdout and MXU discards the child's output anyway, so the outcome is a file: the log
state/efstart/efstart.log and the last result state/efstart/last.json.

The OCR words of the launcher and the game were read off the real screens (the update
flow in gameupdate_games.py, and the parent session on 2026-10-15) except LOGIN_WORDS,
which nobody has seen on this machine: a guess that only ever ends a start with a
message, never clicks.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from ark_relay.features.gameupdate import gameupdate_games as gug

log = logging.getLogger("ark.efstart")

GAME_EXE = "Endfield.exe"
LAUNCHER_EXE = "Games.exe"          # the Hypergryph launcher's process (Launcher.exe starts it)
GAME_FOCUS = "Endfield"
LAUNCHER_FOCUS = "Games"

# Exit codes. Every non-zero one comes with a reason in efstart.log and last.json.
OK = 0
SETUP = 2          # no game / launcher path written by the relay
LOGIN = 3          # phone-number login screen: needs a person
UPDATE = 4         # the launcher or the game wants a client update first
REFUSED = 5        # the game refused a start even through the launcher
LAUNCHER = 6       # the launcher could not be started or driven
TIMED_OUT = 7      # the game did not reach its title screen in time
UNREADABLE = 8     # the process list could not be read; nothing was touched
BUSY = 9           # another start held the lock past the whole budget

START_WORD = "开始游戏"
D3D11_WORD = "DirectX"              # the option line under the start button reads DirectX 11 ...
UPDATE_WORDS = ("更新游戏",) + gug._EF_SPACE_WORDS
REFUSED_WORDS = ("请通过官方启动器", "游戏启动失败")
AGREEMENT_WORDS = ("游戏协议条款提示",)
AGREE_BUTTON = "同意并继续"
LOGIN_WORDS = ("手机号", "获取验证码")
RESTART_WORDS = ("请重启游戏",)
OUTDATED_WORDS = ("客户端版本已过时",)
READY_WORDS = gug.READY_WORDS["终末地"]

# Measured 10-15 15:19-15:21 (the parent session, by hand): from starting Launcher.exe
# to the game window took about 2 minutes. The launcher gets three times that to show
# its start button.
LAUNCHER_BUDGET_S = 360
# After 「开始游戏」 the game has as long as update_endfield gives it to reach the title
# (900 s, gameupdate_games.py). Measured 10-15 15:21 onward: the first start of 1.6.3 ran
# an ~850 MB hot update, then 「正在编译着色器」, inside that.
GAME_BUDGET_S = 900
# Measured 10-15 15:19-15:21: the game process came up seconds after the click; a
# minute without Endfield.exe means the click did not take.
NO_GAME_AFTER_CLICK_S = 60
# A running Endfield.exe with no game window this long (and no refusal dialog) is not
# coming up: measured 10-15 15:19-15:21, the window followed the process within seconds;
# twice the minute above.
RUNNING_NO_WINDOW_S = 120
# Launcher.exe is started again when its window has not shown this long after the last
# start: measured 2026-09-02, update_endfield's first read 25 s after the start found it.
LAUNCHER_RESPAWN_S = 45
# Clicks of one button before it is reported as not clickable: the same three tries
# update_endfield gives the disk-space 「确认」 (_EF_CONFIRM_TRIES).
CLICK_TRIES = gug._EF_CONFIRM_TRIES

# The 「DirectX 11 启动」 checkbox, from the middle of 「开始游戏」: measured 10-15 15:36 by
# the parent session on the 1920x1080 desktop, 「开始游戏」 at about (1407, 796) and the
# box at about (1315, 843). The launcher window has a fixed size in pixels (c47dfca6).
D3D11_BOX_FROM_START = (-92, 47)
# Half the side of the square sampled around that point. Not measured: the parent gave
# the box's position as 「about」, so the square is kept small (15 px) to stay on the box.
D3D11_BOX_HALF = 7
# Mean brightness (0-255) two readings of the box must differ by to count as two states.
# Not measured: a tick turns a dark box into a filled one, which moves the mean of a
# 15 px square by far more than this; two reads of an unchanged screen move it by ~0.
D3D11_MARGIN = 20.0


@dataclass
class Result:
    code: int
    reason: str
    shot: str = ""


@dataclass
class Probes:
    """Everything outside the screen: injectable, so the flow runs without Windows."""
    running: Callable[[tuple], "set[str] | None"]    # names among those running; None = unreadable
    window: Callable[[], "bool | None"]               # the game window is there; None = cannot tell
    spawn: Callable[[Path], bool]                     # start a program on the desktop
    kill: Callable[..., bool]
    box: Callable[[str, int, int, int], "float | None"]  # mean brightness of a square of a screenshot
    calib: dict = field(default_factory=dict)          # the D3D11 box's two readings, remembered
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic


def _unread(scr) -> bool:
    return bool(gug._unread(scr))


def _shot(scr) -> str:
    return str(getattr(scr, "shot", "") or "")


# ─────────────────────────── the flow ───────────────────────────

def start_via_launcher(desk, launcher: Path, p: Probes, *, budget_s: float = GAME_BUDGET_S,
                       launcher_s: float = LAUNCHER_BUDGET_S, poll_s: float = 10.0,
                       settle_s: float = 25.0) -> Result:
    """Bring the game up through the launcher; Result(OK) when it is up (see the module doc).

    poll_s: one desktop read is itself a few seconds of agent start and OCR, so a read
    every 10 s keeps the agent busy about half the time. settle_s: update_endfield's
    first look 25 s after starting the launcher."""
    procs = p.running((GAME_EXE, LAUNCHER_EXE))
    if procs is None:
        return Result(UNREADABLE, "读不到电脑上在运行哪些程序，没动游戏")
    if GAME_EXE in procs:
        res = _check_running(desk, p, poll_s)
        if res is not None:
            return res
        procs = p.running((GAME_EXE, LAUNCHER_EXE)) or set()
    spawned_at = None
    if LAUNCHER_EXE not in procs:
        if not p.spawn(launcher):
            return Result(LAUNCHER, "官方启动器没能在桌面会话里起来，游戏没开")
        log.info("终末地：已启动官方启动器 %s", launcher)
        spawned_at = p.clock()
        p.sleep(settle_s)
    res = _click_start(desk, launcher, p, launcher_s, poll_s, spawned_at)
    if res is not None:
        return res
    return _wait_game(desk, launcher, p, budget_s, launcher_s, poll_s)


def _check_running(desk, p: Probes, poll_s: float) -> "Result | None":
    """Endfield.exe is running. Result(OK) when its window is up and is not the refusal
    dialog; None after closing it (refusal dialog, or no window in RUNNING_NO_WINDOW_S),
    for the caller to start it through the launcher."""
    deadline = p.clock() + RUNNING_NO_WINDOW_S
    while True:
        win = p.window()
        scr = desk.read(focus=GAME_FOCUS)
        if not _unread(scr) and scr.has(*REFUSED_WORDS):
            log.warning("终末地开着，但停在「请通过官方启动器打开游戏」（不是经启动器开的），关掉经启动器重开（截图 %s）",
                        _shot(scr))
            p.kill(GAME_EXE)
            p.sleep(poll_s)
            return None
        if win or win is None:
            # Up (or no way to look for the window, and the screen is not the dialog):
            # the run goes on with this game.
            return Result(OK, "终末地已经开着，没再开")
        if p.clock() >= deadline:
            log.warning("终末地开着，但 %d 秒没有游戏窗口，关掉经启动器重开（截图 %s）",
                        RUNNING_NO_WINDOW_S, _shot(scr))
            p.kill(GAME_EXE)
            p.sleep(poll_s)
            return None
        p.sleep(poll_s)


def _click_start(desk, launcher: Path, p: Probes, launcher_s: float, poll_s: float,
                 spawned_at: "float | None") -> "Result | None":
    """Wait for 「开始游戏」 on the launcher, make sure DirectX 11 is ticked, click it.
    None when clicked; a Result when it cannot be."""
    deadline = p.clock() + launcher_s
    misses = 0
    scr = None
    while True:
        scr = desk.read(focus=LAUNCHER_FOCUS)
        if gug._focus_missing(scr):
            # In the tray, or still opening: Launcher.exe again brings its window up.
            if spawned_at is None or p.clock() - spawned_at >= LAUNCHER_RESPAWN_S:
                log.info("终末地：没找到启动器窗口，再启动一次 %s", launcher.name)
                p.spawn(launcher)
                spawned_at = p.clock()
        elif not _unread(scr):
            if scr.has(*UPDATE_WORDS):
                return Result(UPDATE, f"官方启动器要先更新客户端（{scr.dump(6)}），游戏没开；客户端更新由中继在队列后做",
                              _shot(scr))
            start = scr.find(START_WORD)
            if start is not None:
                res = _ensure_d3d11(desk, p, scr, start)
                if res is not None:
                    return res
                if desk.click_text(START_WORD, focus=LAUNCHER_FOCUS):
                    log.info("终末地：已在官方启动器点「开始游戏」")
                    return None
                misses += 1
                if misses >= CLICK_TRIES:
                    return Result(LAUNCHER, f"官方启动器的「开始游戏」点了 {misses} 次没点上", _shot(scr))
            else:
                log.info("终末地：启动器还没到「开始游戏」：%s", scr.dump(4))
        if p.clock() >= deadline:
            why = "窗口没找到" if gug._focus_missing(scr) else (gug._unread(scr) or scr.dump(6))
            return Result(LAUNCHER, f"官方启动器 {launcher_s / 60:.0f} 分钟没出现「开始游戏」（{why}）", _shot(scr))
        p.sleep(poll_s)


def _ensure_d3d11(desk, p: Probes, scr, start) -> "Result | None":
    """Make sure 「DirectX 11 启动」 is ticked before 「开始游戏」. None when it is.

    The tick is a picture, not text, so the box is judged by the mean brightness of a
    square around it on the launcher screenshot. A fixed threshold would be a guess, so
    the two states are learnt once by clicking the box and reading it again (the brighter
    one is ticked: a filled box with a check mark), and remembered in p.calib; a later
    start compares with them and clicks only when the box is in the unticked state."""
    x = start.center[0] + D3D11_BOX_FROM_START[0]
    y = start.center[1] + D3D11_BOX_FROM_START[1]
    now = p.box(_shot(scr), x, y, D3D11_BOX_HALF)
    if now is None:
        return Result(LAUNCHER, "读不了启动器截图里「DirectX 11 启动」的勾", _shot(scr))
    on, off = p.calib.get("on"), p.calib.get("off")
    learnt = on is not None and off is not None and abs(on - off) >= D3D11_MARGIN
    if learnt and abs(now - on) <= abs(now - off):
        return None
    if not scr.has(D3D11_WORD):
        # Nothing is clicked where the option was not read: it sits under 「开始游戏」 on
        # this launcher, and a launcher that moved it would take the click somewhere else.
        return Result(LAUNCHER, "官方启动器上没读到「DirectX 11 启动」，没法确认勾上，游戏没开（不勾 MaaEnd 认不出游戏画面）",
                      _shot(scr))
    # Learnt and unticked: one click. Not learnt yet: click, read again, keep it ticked.
    return _toggle_d3d11(desk, p, x, y, now, learn=not learnt, before_shot=_shot(scr))


def _toggle_d3d11(desk, p: Probes, x: int, y: int, before: float, *, learn: bool,
                  before_shot: str = "") -> "Result | None":
    for _ in range(CLICK_TRIES + 1):
        if not desk.click(x, y, focus=LAUNCHER_FOCUS):
            continue
        p.sleep(1)
        scr = desk.read(focus=LAUNCHER_FOCUS)
        after = None if _unread(scr) else p.box(_shot(scr), x, y, D3D11_BOX_HALF)
        if after is None:
            continue
        if abs(after - before) < D3D11_MARGIN:
            log.info("终末地：点了「DirectX 11 启动」的勾，读出来没变（%.0f → %.0f）", before, after)
            continue
        if learn:
            # Learnt: the brighter reading is the ticked one.
            # Both screenshots are kept in the calibration and the log, so a person can
            # check once that the brighter one really shows the tick.
            p.calib.update(on=max(before, after), off=min(before, after),
                           shots=[before_shot, _shot(scr)], box=[x, y])
            learn = False
            log.info("终末地：「DirectX 11 启动」两种样子记下了（勾上 %.0f，没勾 %.0f；点之前 %s，点之后 %s）",
                     p.calib["on"], p.calib["off"], before_shot, _shot(scr))
        if abs(after - p.calib["on"]) <= abs(after - p.calib["off"]):
            log.info("终末地：已勾上「DirectX 11 启动」")
            return None
        # It had been ticked and this click took it off: click once more.
        before = after
    return Result(LAUNCHER, "官方启动器的「DirectX 11 启动」点了几次没确认勾上，游戏没开")


def _wait_game(desk, launcher: Path, p: Probes, budget_s: float, launcher_s: float,
               poll_s: float) -> Result:
    """After 「开始游戏」: watch the game up to its title screen."""
    deadline = p.clock() + budget_s
    clicked_at = p.clock()
    restarted = reclicked = False
    agreed = 0
    scr = None
    while p.clock() < deadline:
        p.sleep(poll_s)
        procs = p.running((GAME_EXE,))
        if procs is not None and GAME_EXE not in procs:
            if p.clock() - clicked_at < NO_GAME_AFTER_CLICK_S:
                continue
            if reclicked:
                return Result(LAUNCHER, "官方启动器「开始游戏」点了两回，游戏都没起来", _shot(scr))
            reclicked = True
            log.info("终末地：点了「开始游戏」%d 秒游戏还没起来，再点一次", NO_GAME_AFTER_CLICK_S)
            res = _click_start(desk, launcher, p, launcher_s, poll_s, None)
            if res is not None:
                return res
            clicked_at = p.clock()
            continue
        scr = desk.read(focus=GAME_FOCUS)
        if _unread(scr):
            continue
        if scr.has(*REFUSED_WORDS):
            return Result(REFUSED, "经官方启动器开的游戏还是说「请通过官方启动器打开游戏」", _shot(scr))
        if scr.has(*AGREEMENT_WORDS) or scr.has(AGREE_BUTTON):
            agreed += 1
            if agreed > CLICK_TRIES:
                return Result(TIMED_OUT, f"「游戏协议条款提示」点了 {CLICK_TRIES} 次「同意并继续」还在", _shot(scr))
            ok = desk.click_text(AGREE_BUTTON, focus=GAME_FOCUS)
            log.info("终末地：弹了「游戏协议条款提示」，%s", "已点「同意并继续」" if ok else "「同意并继续」没点上，下一轮再点")
            continue
        if scr.has(*LOGIN_WORDS):
            return Result(LOGIN, "游戏停在手机号登录画面，要人登录一次（这一步自动做不了）", _shot(scr))
        if scr.has(*OUTDATED_WORDS):
            return Result(UPDATE, "游戏说客户端版本已过时，要先更新；客户端更新由中继在队列后做", _shot(scr))
        if scr.has(*RESTART_WORDS):
            if restarted:
                return Result(TIMED_OUT, "游戏重开一次后又要「请重启游戏」", _shot(scr))
            restarted = True
            log.info("终末地：游戏要「请重启游戏」，点「确认」后经官方启动器重开")
            desk.click_text("确认", focus=GAME_FOCUS)
            p.sleep(poll_s)
            p.kill(GAME_EXE)
            p.sleep(poll_s)
            res = _click_start(desk, launcher, p, launcher_s, poll_s, None)
            if res is not None:
                return res
            clicked_at = p.clock()
            continue
        if scr.has(*READY_WORDS):
            return Result(OK, "终末地已经由官方启动器开到标题画面")
        log.info("终末地：还在加载：%s", scr.dump(4))
    last = scr.dump(6) if scr is not None else ""
    return Result(TIMED_OUT, f"点「开始游戏」后 {budget_s / 60:.0f} 分钟没到标题画面（最后一屏：{last}）", _shot(scr))


# ─────────────────────────── the process (pythonw on the desktop) ───────────────────────────

HOME = "efstart"             # state/efstart: everything of this helper
TRAMPOLINE = "efstart.py"    # written by efstart_setup; runs main() from the current code folder
TARGET = "target.json"       # written by efstart_setup: game and launcher paths
RUNNING = "running.json"     # this helper's PID while it drives; maaend_watchdog reads it
LAST = "last.json"
LOG = "efstart.log"
CALIB = "d3d11.json"
LOCK_NAME = "Global\\ArkRelayEndfieldStart"
# The log file is cut back to its last half once it passes this many bytes.
LOG_KEEP = 1_000_000
# The longest one start can take, and so how long a later start waits for the lock.
WHOLE_S = LAUNCHER_BUDGET_S + GAME_BUDGET_S + RUNNING_NO_WINDOW_S


def _tasklist(names: tuple) -> "set[str] | None":
    try:
        # Measured 10-13 on the game PC (desktop.kill): taskkill answers in 0.05 s; tasklist
        # gets the same 30 s cap the relay gives those calls.
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if not out.strip():
        return None
    have = {ln.split('","')[0].lstrip('"').lower() for ln in out.splitlines() if ln}
    return {n for n in names if n.lower() in have}


def _find_window() -> "bool | None":
    try:
        import win32gui  # noqa: PLC0415 - Windows only
        return bool(win32gui.FindWindow("UnityWndClass", "Endfield"))
    except Exception:  # noqa: BLE001 - no pywin32, or no desktop: cannot tell
        return None


def box_brightness(shot: str, x: int, y: int, half: int) -> "float | None":
    """Mean brightness (0-255) of the (2*half+1)-pixel square at (x, y) of a screenshot."""
    try:
        from PIL import Image  # noqa: PLC0415 - the relay's runtime ships Pillow
        with Image.open(shot) as im:
            vals = list(im.convert("L").crop((x - half, y - half, x + half + 1, y + half + 1)).getdata())
    except Exception:  # noqa: BLE001 - a missing or broken screenshot is "cannot tell"
        return None
    return sum(vals) / len(vals) if vals else None


def _spawn_desktop(task: str):
    """Start a program on the interactive desktop: the relay's scheduled-task route
    (elevated, measured to reach the launcher in c47dfca6), under a task name of its own
    so the relay's agents and this helper never unregister each other's task; else a
    plain start from this process, which already runs on that desktop."""
    from ark_relay.features.preupdate.preupdate_common import _spawn_via_task  # noqa: PLC0415

    def spawn(exe: Path, cwd: "Path | None" = None, args: tuple = ()) -> bool:
        if _spawn_via_task(Path(exe), Path(cwd or Path(exe).parent), tuple(args), task=task):
            return True
        try:
            subprocess.Popen([str(exe), *args], cwd=str(cwd or Path(exe).parent),
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            return True
        except OSError:
            log.warning("终末地：%s 没能启动", exe, exc_info=True)
            return False
    return spawn


@contextlib.contextmanager
def _single(wait_s: float):
    """Hold the one-start-at-a-time mutex; yields False when another start kept it past wait_s."""
    try:
        import win32event  # noqa: PLC0415 - Windows only
    except ImportError:
        yield True
        return
    try:
        h = win32event.CreateMutex(None, False, LOCK_NAME)
    except Exception:
        log.warning("终末地：建不了互斥锁，不排队直接开", exc_info=True)
        yield True
        return
    r = win32event.WaitForSingleObject(h, int(wait_s * 1000))
    got = r in (win32event.WAIT_OBJECT_0, getattr(win32event, "WAIT_ABANDONED", 0x80))
    try:
        yield got
    finally:
        if got:
            win32event.ReleaseMutex(h)


def _setup_log(home: Path) -> None:
    f = home / LOG
    try:
        if f.is_file() and f.stat().st_size > LOG_KEEP:
            f.write_bytes(f.read_bytes()[-LOG_KEEP // 2:])
    except OSError:
        pass
    h = logging.FileHandler(f, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(process)d] %(message)s"))
    root = logging.getLogger()
    root.addHandler(h)
    root.setLevel(logging.INFO)


def _drop(f: Path) -> None:
    """Remove a file of this helper; one held open is left for the next run to overwrite."""
    try:
        Path(f).unlink(missing_ok=True)
    except OSError:
        log.debug("终末地：%s 没删掉", f, exc_info=True)


def _read_json(f: Path) -> dict:
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(f: Path, data: dict) -> None:
    from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
    try:
        atomic_write_text(Path(f), json.dumps(data, ensure_ascii=False, indent=1))
    except OSError:
        log.warning("终末地：写不了 %s", f, exc_info=True)


def run_once(home: Path, caller: str, *, desk, probes: Probes, single=_single) -> Result:
    """One start under the lock, with running.json written while it drives."""
    target = _read_json(home / TARGET)
    if not target.get("launcher"):
        return Result(SETUP, f"中继没写启动器位置（{home / TARGET}），游戏没开")
    with single(WHOLE_S) as got:
        if not got:
            return Result(BUSY, "另一次开游戏一直没结束，这次没开")
        _write_json(home / RUNNING, {"pid": os.getpid(), "caller": caller,
                                     "started": datetime.now().isoformat(timespec="seconds")})
        try:
            return start_via_launcher(desk, Path(str(target["launcher"])), probes)
        except Exception as exc:  # said in last.json, not a traceback nobody reads
            log.exception("终末地：开游戏的流程自己出错")
            return Result(LAUNCHER, f"开游戏的流程自己出错：{type(exc).__name__}: {exc}")
        finally:
            _drop(home / RUNNING)


def main(argv: "list[str] | None" = None) -> int:
    """The helper process. `--home` is state/efstart (the trampoline passes it); anything
    after the known options is ignored (AUTO-MAS appends Game.Arguments)."""
    ap = argparse.ArgumentParser(prog="efstart")
    ap.add_argument("--home", required=True)
    ap.add_argument("--caller", default="")
    ap.add_argument("--result", default="")
    args, _rest = ap.parse_known_args(argv)
    home = Path(args.home)
    home.mkdir(parents=True, exist_ok=True)
    _setup_log(home)
    log.info("终末地：开始（调用方 %s）", args.caller or "?")
    from ark_relay.core.desktop import Desktop, kill  # noqa: PLC0415
    calib = _read_json(home / CALIB)
    probes = Probes(running=_tasklist, window=_find_window, spawn=_spawn_desktop("ark-efstart-launcher"),
                    kill=kill, box=box_brightness, calib=dict(calib))
    res = run_once(home, args.caller, desk=Desktop(home, spawn=_spawn_desktop("ark-efstart-agent")),
                   probes=probes)
    if probes.calib != calib:
        _write_json(home / CALIB, probes.calib)
    out = {"at": datetime.now().isoformat(timespec="seconds"), "caller": args.caller,
           "code": res.code, "reason": res.reason, "shot": res.shot}
    _write_json(home / LAST, out)
    if args.result:
        _write_json(Path(args.result), out)
    (log.info if res.code == OK else log.warning)("终末地：结束 %d：%s%s", res.code, res.reason,
                                                   f"（截图 {res.shot}）" if res.shot else "")
    return res.code


# ─────────────────────────── for the relay ───────────────────────────

def helper_alive(state_dir, procs) -> bool:
    """A helper is driving a start now: its running.json names a PID that is a python
    process in `procs` ((image, PID) pairs). maaend_watchdog holds its clocks meanwhile."""
    if not state_dir:
        return False
    pid = _read_json(Path(state_dir) / HOME / RUNNING).get("pid")
    return any(p == pid and str(n).lower() in ("pythonw.exe", "python.exe") for n, p in procs or ())


def run_on_desktop(state_dir, spawn, *, wait_s: float = WHOLE_S, sleep=time.sleep,
                   clock=time.monotonic, pythonw=None, poll_s: float = 5.0) -> Result:
    """Run the helper on the interactive desktop from the relay's service and wait for its
    result. `spawn(exe, cwd, args)` is preupdate_common._spawn_interactive in production.
    poll_s: how often the result file is looked for; a start takes minutes."""
    if pythonw is None:
        from ark_relay.features.preupdate.preupdate_common import _pythonw  # noqa: PLC0415
        pythonw = _pythonw()
    home = Path(state_dir) / HOME
    trampoline = home / TRAMPOLINE
    if pythonw is None or not trampoline.is_file():
        return Result(SETUP, f"开游戏的助手没装好（{pythonw or '没有 pythonw.exe'}，{trampoline}）")
    result = home / f"result-{uuid.uuid4().hex[:8]}.json"
    if not spawn(Path(pythonw), home, (str(trampoline), "--caller", "relay", "--result", str(result))):
        return Result(LAUNCHER, "开游戏的助手没能在桌面会话里起来")
    deadline = clock() + wait_s
    while clock() < deadline:
        if result.is_file():
            d = _read_json(result)
            _drop(result)
            return Result(int(d.get("code", LAUNCHER)), str(d.get("reason") or ""), str(d.get("shot") or ""))
        sleep(poll_s)
    return Result(TIMED_OUT, f"开游戏的助手 {wait_s / 60:.0f} 分钟没给结果")
