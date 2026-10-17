"""Start Endfield (终末地) windowed through MaaEnd's own launcher pretask, for the relay's own starts.

Client 1.6.3 (「丹青渡」, 2026-10-15) refuses to run unless its parent process is the
running official launcher (MaaEnd/MaaEnd#6469). AUTO-MAS starts the game for its own runs
(efstart_setup.py sets its Game.LaunchMode); this helper serves the one start the relay
makes itself: the gathering retry (collect_retry), through run_on_desktop.

Until 2026-10-17 this helper drove the launcher by OCR and made sure the launcher's
「DirectX 11 启动」 box was ticked, because MaaEnd read a fullscreen non-DX11 game as
「当前环境识别异常」. The box is to stay unticked now (the launcher remembers it, so the
owner's own play started in DX11 too), and the game runs windowed below the desktop
instead, which MaaEnd reads on any graphics API. The start is MaaEnd's own pretask
LaunchGamePC, exactly as AUTO-MAS v5.7.0-beta.5's 「MaaEnd 启动」 runs it (maaend_launch.py
has the options and the evidence): it writes a 1280x720 window into the game's display
settings, starts Launcher.exe and clicks 「开始游戏」 in the real launcher, so Games.exe stays
the parent; exit code 0 once the game window is up. collect_retry puts fullscreen back
afterwards through MaaEnd's CloseGamePC task.

What one start does (start_via_maaend):

* Refuses, with a reason, when the installed MaaEnd no longer declares the pretask or one
  of its options, or its program is not in the MaaEnd folder (nothing is guessed).
* Closes a running Endfield.exe first: the pretask skips everything, the window settings
  included, when the game already runs (launchgamepc.go), and the game would then stay
  fullscreen.
* Wakes the display: the launcher keeps its window hidden while the power plan has turned
  the display off (display_wake.py has the evidence), and the pretask finds the launcher
  by its window. One wake keeps it on for the 300 s idle time, longer than the pretask's
  own waits (60 s launcher + 120 s game).
* Runs the pretask from the MaaEnd folder (AUTO-MAS's cwd) with AUTO-MAS's 240 s limit
  and reports its exit code.

Several starters fire at once, so a named mutex lets one drive; a later one waits for it.
The helper runs on the interactive desktop (the launcher and the game must open there)
with the relay's own pythonw.exe, from the trampoline efstart_setup writes into
state/efstart/. pythonw has no stdout, so the outcome is a file: the log
state/efstart/efstart.log and the last result state/efstart/last.json.
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ark_relay.features.gameupdate import maaend_launch

log = logging.getLogger("ark.efstart")

GAME_EXE = "Endfield.exe"

# Exit codes. Every non-zero one comes with a reason in efstart.log and last.json.
OK = 0
SETUP = 2          # MaaEnd's launcher pretask is not there to run (folder, declaration, program)
PRETASK = 5        # the pretask ran and exited non-zero
LAUNCHER = 6       # the helper could not start, or the game could not be closed first
TIMED_OUT = 7      # the pretask (or the helper) did not end in time
UNREADABLE = 8     # the process list could not be read; nothing was touched
BUSY = 9           # another start held the lock past the whole budget
# The pretask ran (or may still run): it writes the window settings before starting the
# launcher, so the caller has fullscreen to put back even though the start failed.
RAN = (PRETASK, TIMED_OUT)

# AUTO-MAS v5.7.0-beta.5 gives the launching pretask 240 s (AutoProxy.py
# _apply_launcher_game_settings, https://github.com/AUTO-MAS-Project/AUTO-MAS/blob/v5.7.0-beta.5/app/task/MaaEnd/AutoProxy.py);
# the pretask itself waits up to 60 s for the launcher and 120 s for the game window
# (launchgamepc.go launcherWindowTimeout / gameWindowTimeout). Measured on the machine 10-17:
# 25 s from 「Pretask invoked」 11:31:05 to 「Pretask succeeded」 11:31:30 (go-service.log).
PRETASK_TIMEOUT_S = 240
# After closing a running game: MaaEnd's own close waits up to 5 s for Endfield.exe to go
# (https://github.com/MaaEnd/MaaEnd/blob/v2.33.0/agent/go-service/common/closegame/action.go
# waitEndfieldExit); twice that before looking again.
GAME_EXIT_S = 10
# The tail of the pretask's own output kept in efstart.log on a failure.
OUTPUT_TAIL = 2000


@dataclass
class Result:
    code: int
    reason: str
    shot: str = ""


@dataclass
class Probes:
    """Everything outside this process: injectable, so the flow runs without Windows."""
    running: Callable[[tuple], "set[str] | None"]     # names among those running; None = unreadable
    kill: Callable[..., bool]
    run: Callable[..., "tuple[int | None, str]"]      # (argv, cwd, timeout) -> (exit code, None = timed out; output)
    wake: Callable[[], bool]                           # wake the display
    sleep: Callable[[float], None] = time.sleep


# ─────────────────────────── the flow ───────────────────────────

def start_via_maaend(maaend_dir, p: Probes) -> Result:
    """Bring the game up windowed through MaaEnd's pretask; Result(OK) when it exited 0."""
    plan, why = maaend_launch.launch_plan(maaend_dir)
    if plan is None:
        return Result(SETUP, f"{why}，游戏没开")
    exe = maaend_launch.executable(maaend_dir, plan["exec"])
    if exe is None:
        return Result(SETUP, f"MaaEnd 文件夹里没有它开游戏用的程序（{Path(str(maaend_dir)) / plan['exec']}），游戏没开")
    procs = p.running((GAME_EXE,))
    if procs is None:
        return Result(UNREADABLE, "读不到电脑上在运行哪些程序，没动游戏")
    if GAME_EXE in procs:
        log.info("终末地：游戏已经开着，先关掉（开着时 MaaEnd 不改窗口设置也不重开）")
        p.kill(GAME_EXE)
        p.sleep(GAME_EXIT_S)
        after = p.running((GAME_EXE,))
        if after is None or GAME_EXE in after:
            return Result(LAUNCHER, "开着的游戏关不掉，没法按窗口重开")
    if not p.wake():
        log.info("终末地：叫醒屏幕没成功，照样开（屏幕关着时启动器不显示窗口，MaaEnd 就找不到它）")
    argv = [str(exe), *plan["args"]]
    log.info("终末地：由 MaaEnd 开游戏（1280×720 窗口）：%s", " ".join(argv))
    t0 = time.monotonic()
    code, out = p.run(argv, cwd=str(maaend_dir), timeout=PRETASK_TIMEOUT_S)
    took = time.monotonic() - t0
    if code is None:
        log.info("终末地：MaaEnd 开游戏的输出：%s", out[-OUTPUT_TAIL:])
        return Result(TIMED_OUT, f"MaaEnd 开游戏 {PRETASK_TIMEOUT_S // 60} 分钟没结束，已停下")
    if code != 0:
        log.info("终末地：MaaEnd 开游戏的输出：%s", out[-OUTPUT_TAIL:])
        return Result(PRETASK, f"MaaEnd 开游戏没成功（退出码 {code}），它自己的日志在 MaaEnd 的 debug\\go-service.log")
    log.info("终末地：MaaEnd 开游戏用了 %.0f 秒", took)
    return Result(OK, "MaaEnd 已经经官方启动器把游戏开成 1280×720 的窗口")


# ─────────────────────────── the process (pythonw on the desktop) ───────────────────────────

HOME = "efstart"             # state/efstart: everything of this helper
TRAMPOLINE = "efstart.py"    # written by efstart_setup; runs main() from the current code folder
TARGET = "target.json"       # written by efstart_setup: game and launcher paths
RUNNING = "running.json"     # this helper's PID while it drives; maaend_watchdog reads it
LAST = "last.json"
LOG = "efstart.log"
LOCK_NAME = "Global\\ArkRelayEndfieldStart"
# The log file is cut back to its last half once it passes this many bytes.
LOG_KEEP = 1_000_000
# The longest one start can take, and so how long a later start waits for the lock:
# the pretask's limit, closing a running game first and the display wake's own 30 s cap.
WHOLE_S = PRETASK_TIMEOUT_S + GAME_EXIT_S + 30


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


def _run(argv: list, cwd: str, timeout: float) -> "tuple[int | None, str]":
    """Run the pretask and wait; (exit code, output), exit code None when it ran past
    `timeout` (subprocess.run then kills it)."""
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        return None, out if isinstance(out, str) else out.decode("utf-8", "replace")
    except OSError as exc:
        return -1, f"{type(exc).__name__}: {exc}"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


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


def run_once(home: Path, caller: str, maaend_dir, *, probes: Probes, single=_single) -> Result:
    """One start under the lock, with running.json written while it drives."""
    if not maaend_dir:
        return Result(SETUP, "中继没告诉开游戏助手 MaaEnd 装在哪，游戏没开")
    with single(WHOLE_S) as got:
        if not got:
            return Result(BUSY, "另一次开游戏一直没结束，这次没开")
        _write_json(home / RUNNING, {"pid": os.getpid(), "caller": caller,
                                     "started": datetime.now().isoformat(timespec="seconds")})
        try:
            return start_via_maaend(maaend_dir, probes)
        except Exception as exc:  # said in last.json, not a traceback nobody reads
            log.exception("终末地：开游戏的流程自己出错")
            return Result(LAUNCHER, f"开游戏的流程自己出错：{type(exc).__name__}: {exc}")
        finally:
            _drop(home / RUNNING)


def main(argv: "list[str] | None" = None) -> int:
    """The helper process. `--home` is state/efstart (the trampoline passes it), `--maaend`
    the MaaEnd folder; anything after the known options is ignored."""
    ap = argparse.ArgumentParser(prog="efstart")
    ap.add_argument("--home", required=True)
    ap.add_argument("--caller", default="")
    ap.add_argument("--result", default="")
    ap.add_argument("--maaend", default="")
    args, _rest = ap.parse_known_args(argv)
    home = Path(args.home)
    home.mkdir(parents=True, exist_ok=True)
    _setup_log(home)
    log.info("终末地：开始（调用方 %s）", args.caller or "?")
    from ark_relay.core.desktop import Desktop, kill  # noqa: PLC0415
    desk = Desktop(home, spawn=_spawn_desktop("ark-efstart-agent"))
    probes = Probes(running=_tasklist, kill=kill, run=_run, wake=desk.wake)
    res = run_once(home, args.caller, args.maaend, probes=probes)
    out = {"at": datetime.now().isoformat(timespec="seconds"), "caller": args.caller,
           "code": res.code, "reason": res.reason, "shot": res.shot}
    _write_json(home / LAST, out)
    if args.result:
        _write_json(Path(args.result), out)
    (log.info if res.code == OK else log.warning)("终末地：结束 %d：%s", res.code, res.reason)
    return res.code


# ─────────────────────────── for the relay ───────────────────────────

def helper_alive(state_dir, procs) -> bool:
    """A helper is driving a start now: its running.json names a PID that is a python
    process in `procs` ((image, PID) pairs). maaend_watchdog holds its clocks meanwhile."""
    if not state_dir:
        return False
    pid = _read_json(Path(state_dir) / HOME / RUNNING).get("pid")
    return any(p == pid and str(n).lower() in ("pythonw.exe", "python.exe") for n, p in procs or ())


def run_on_desktop(state_dir, spawn, maaend_dir, *, wait_s: float = 2 * WHOLE_S, sleep=time.sleep,
                   clock=time.monotonic, pythonw=None, poll_s: float = 5.0) -> Result:
    """Run the helper on the interactive desktop from the relay's service and wait for its
    result. `spawn(exe, cwd, args)` is preupdate_common._spawn_interactive in production.
    wait_s: the helper may first wait WHOLE_S for another start's lock, then start.
    poll_s: how often the result file is looked for; a start takes minutes."""
    if pythonw is None:
        from ark_relay.features.preupdate.preupdate_common import _pythonw  # noqa: PLC0415
        pythonw = _pythonw()
    home = Path(state_dir) / HOME
    trampoline = home / TRAMPOLINE
    if pythonw is None or not trampoline.is_file():
        return Result(SETUP, f"开游戏的助手没装好（{pythonw or '没有 pythonw.exe'}，{trampoline}）")
    result = home / f"result-{uuid.uuid4().hex[:8]}.json"
    if not spawn(Path(pythonw), home, (str(trampoline), "--caller", "relay", "--maaend", str(maaend_dir),
                                       "--result", str(result))):
        return Result(LAUNCHER, "开游戏的助手没能在桌面会话里起来")
    deadline = clock() + wait_s
    while clock() < deadline:
        if result.is_file():
            d = _read_json(result)
            _drop(result)
            return Result(int(d.get("code", LAUNCHER)), str(d.get("reason") or ""), str(d.get("shot") or ""))
        sleep(poll_s)
    return Result(TIMED_OUT, f"开游戏的助手 {wait_s / 60:.0f} 分钟没给结果")
