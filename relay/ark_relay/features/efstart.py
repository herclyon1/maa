"""Leave Endfield's start to AUTO-MAS's 「MaaEnd 启动」 mode, windowed; run at each relay start.

Since 10-17 (DECISIONS D-1016-终末地等AUTO-MAS新版; the owner said 「好」 on 10-16) the game
runs windowed below the desktop for script runs instead, which MaaEnd reads on any graphics
API, and the box is to be unticked. AUTO-MAS v5.7.0-beta.5's Game.LaunchMode "MaaEnd" runs
MaaEnd's own pretask LaunchGamePC before a run (a 1280x720 window, then the real launcher's
「开始游戏」, so Games.exe stays the parent) and CloseGamePC after it (fullscreen 1920x1080
back); maaend_launch.py has the options and the 10-17 11:31 run that proved them.

So, at every relay start and right after the pre-update installs a new AUTO-MAS
(boot_stages), this module converges AUTO-MAS's MaaEnd script, each write read back
(commands._script_item_via_api):

1. Game.Path -> Endfield.exe (target.json "game", which is original.game_path);
2. when the installed MaaEnd still declares the pretask, its options and CloseGamePC's
   restore for AUTO-MAS's Game.ControllerType, its default cases are the window ones
   (maaend_launch.check) and the MaaEnd master stores no other value for them
   (maaend_launch.stored_override; AUTO-MAS sends only LaunchGamePCGameSetting itself): Game.SetResolution
   true, Game.CloseOnFinish true, Game.RestoreDisplayType "Fullscreen",
   Game.RestoreResolution "1920x1080" (not "Original": that takes the registry as found
   at run start, so one run that died windowed would keep the game windowed), and only
   once all four hold, Game.LaunchMode "MaaEnd". When the check fails, Game.LaunchMode
   "Launcher" and a WARNING (the group): with the box unticked every MaaEnd run of that
   mode starts fullscreen on Vulkan and fails;
3. Game.WaitTime -> its value before 10-15 (original.wait_time);
4. the relay's own preAction (the helper, found by its trampoline in args) is removed from
   the MaaEnd master and not added back; the direct Endfield.exe start it once replaced is
   never put back: 1.6.3 refuses it.

In "Launcher" mode it also applies upstream's launcher discovery rule
(app/services/endfield_launcher.py) to what AUTO-MAS now holds; when it fails, AUTO-MAS
refuses every MaaEnd run of that mode, and the relay says so at boot (a WARNING). In
"MaaEnd" mode MaaEnd finds the launcher itself (AUTO-MAS manager.py: 「原生模式由 MaaEnd
自行定位」), so a miss there is only logged.

The trampoline state/efstart/efstart.py stays: the relay's own start (collect_retry's
gathering retry, through efstart.run_on_desktop) runs the same pretask through it.
"""
from __future__ import annotations

import json
import logging
import os
import argparse
import contextlib
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path, PureWindowsPath
from ark_relay.core import texts
from ark_relay.core.config import atomic_write_bytes, atomic_write_text
from ark_relay.features import efstart, maaend_launch
from dataclasses import dataclass
from typing import Callable

_log_efstart_setup = logging.getLogger("ark.efstart_setup")

# The game and launcher paths are Windows paths read from AUTO-MAS and MaaEnd; the day
# simulator replaces these to answer them from its sim tree.
_is_file = os.path.isfile


def _subdirs(path: str) -> "list[str]":
    """The folders directly inside `path` (upstream _has_version_dir walks root.iterdir())."""
    try:
        return [e.path for e in os.scandir(path) if e.is_dir()]
    except OSError:
        return []


AUTOMAS_PREACTION_ID = "automas-endfield"     # AUTO-MAS's own entry (AutoProxy.py:301-327)
LAUNCH_MODE = "MaaEnd"                        # AUTO-MAS v5.7.0-beta.5 Game.LaunchMode 「MaaEnd 启动」
FALLBACK_MODE = "Launcher"                    # 「启动器启动」 (v5.7.0-beta.4, PR #1394)
WINDOWED = {"SetResolution": True, "CloseOnFinish": True,
            "RestoreDisplayType": "Fullscreen", "RestoreResolution": "1920x1080"}
WINDOWED_BEFORE = {"SetResolution": False, "CloseOnFinish": True,
                   "RestoreDisplayType": "Window", "RestoreResolution": "Off"}
# MaaEnd's declarations, read from its folder; the day simulator answers it from its sim tree.
_launch_check = maaend_launch.check
# upstream app/services/endfield_launcher.py @0fec00e0
_LAUNCHER_EXE = "Launcher.exe"
_LAUNCHER_EXE_NAMES = ("launcher.exe", "games.exe")
_VERSION_MARKER = "Games.exe"
# AUTO-MAS's lower bound for Game.WaitTime: RangeValidator(60, 9999) in
# https://github.com/AUTO-MAS-Project/AUTO-MAS/blob/v5.7.0-beta.4/app/models/config.py
WAIT_MIN_S = 60


def _is_game(prog: str) -> bool:
    return PureWindowsPath(str(prog or "")).name.lower() == efstart.GAME_EXE.lower()


def _ours(action: dict) -> bool:
    return efstart.TRAMPOLINE in str(action.get("args") or "")


def remove_preactions(doc: dict) -> "tuple[bool, list[dict]]":
    """Drop the relay's helper preAction (the trampoline in its args, whatever its id) from
    every instance, in place; AUTO-MAS's and anything else stay. (changed, removed)."""
    removed: list[dict] = []
    for inst in doc.get("instances") or []:
        if not isinstance(inst, dict) or not isinstance(inst.get("preActions"), list):
            continue
        removed += [a for a in inst["preActions"] if isinstance(a, dict) and _ours(a)]
        inst["preActions"] = [a for a in inst["preActions"] if not (isinstance(a, dict) and _ours(a))]
    return bool(removed), removed


def _has_version_dir(root: PureWindowsPath) -> bool:
    return any(_is_file(str(PureWindowsPath(d) / _VERSION_MARKER)) for d in _subdirs(str(root)))


def launcher_for(game_path: str, launcher_path: str = "") -> "PureWindowsPath | None":
    """The launcher AUTO-MAS will use, by its own rule (resolve_launcher_exe): a set
    LauncherPath must be Launcher.exe or Games.exe and exist (Games.exe -> the Launcher.exe
    two folders up); an empty one is found from Game.Path: the nearest folder above it
    holding Launcher.exe and a subfolder with Games.exe. None when AUTO-MAS finds none."""
    if launcher_path.strip():
        p = PureWindowsPath(launcher_path.strip())
        if p.name.lower() not in _LAUNCHER_EXE_NAMES or not _is_file(str(p)):
            return None
        if p.name.lower() == "games.exe":
            p = p.parent.parent / _LAUNCHER_EXE
            return p if _is_file(str(p)) else None
        return p
    if not str(game_path or "").strip():
        return None
    game = PureWindowsPath(str(game_path).strip())
    if not _is_file(str(game)):
        return None
    for ancestor in game.parents:
        cand = ancestor / _LAUNCHER_EXE
        if _is_file(str(cand)) and _has_version_dir(ancestor):
            return cand
    return None


def trampoline_text(code_root: Path) -> str:
    return ("# Written by the relay at every start (ark_relay/features/gameupdate/efstart_setup.py).\n"
            "# Runs the launcher helper from the code folder in use; do not edit.\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(code_root)!r})\n"
            "from ark_relay.features import efstart\n"
            "sys.exit(efstart.main(['--home', str(Path(__file__).resolve().parent)] + sys.argv[1:]))\n")


def _write_if_changed(f: Path, text: str) -> bool:
    """Write `text` (ASCII or UTF-8) byte for byte; False when the file already holds it."""
    data = text.encode("utf-8")
    try:
        if f.is_file() and f.read_bytes() == data:
            return False
    except OSError:
        pass
    atomic_write_bytes(f, data)
    return True


def _mas_script(reply) -> "dict | None":
    data = reply.get("data") if isinstance(reply, dict) else None
    for sc in (data or {}).values() if isinstance(data, dict) else ():
        if isinstance(sc, dict) and str((sc.get("Info") or {}).get("Name") or "").lower() == "maaend":
            return sc
    return None


def _game_path(cfg, target: dict, mas_game: str, master: "dict | None") -> "Path | None":
    """Endfield.exe's path, never guessed: what was recorded, else AUTO-MAS's Game.Path,
    else the master's preAction, else what MXU saved as its connected program."""
    original = target.get("original") or {}
    cands = [str(target.get("game") or ""), str(original.get("game_path") or ""), mas_game]
    for inst in (master or {}).get("instances") or []:
        for a in (inst.get("preActions") or []) if isinstance(inst, dict) else []:
            if isinstance(a, dict):
                cands.append(str(a.get("program") or ""))
    for c in cands:
        if _is_game(c):
            return Path(c)
    if cfg.maaend_dir:
        from ark_relay.features.collect_retry import _game_exe  # noqa: PLC0415
        g = _game_exe(Path(cfg.maaend_dir))
        if g and _is_game(str(g)):
            return g
    return None


def _clean_master(mfile: "Path | None", master: "dict | None") -> "tuple[bool, list[str]]":
    """Remove the relay's helper preAction from the MaaEnd master, backed up and read back."""
    if master is None:
        return False, ["MaaEnd 母本找不到，没能确认里面不再有中继的开游戏助手"]
    changed, _removed = remove_preactions(master)
    if not changed:
        return True, []
    bak = mfile.with_name(mfile.name + f".bak-efstart-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    bak.write_bytes(mfile.read_bytes())
    atomic_write_text(mfile, json.dumps(master, ensure_ascii=False, indent=2))
    if remove_preactions(json.loads(mfile.read_text(encoding="utf-8")))[0]:
        return False, [f"MaaEnd 母本里中继的开游戏助手删了读出来还在，{bak.name} 是原样"]
    return True, [f"MaaEnd 母本里中继的开游戏助手已删掉，开游戏交给调度程序（原文件备份 {bak.name}）"]


def _read_master(mfile: "Path | None") -> "tuple[dict | None, str]":
    try:
        return (json.loads(mfile.read_text(encoding="utf-8")) if mfile and mfile.is_file() else None), ""
    except (OSError, ValueError) as exc:
        return None, f"MaaEnd 母本读不了（{mfile}：{exc}）"


def install(cfg, *, pythonw: "Path | None" = None, code_root: "Path | None" = None) -> "tuple[bool, list[str]]":
    """Converge AUTO-MAS's MaaEnd script and the MaaEnd master on AUTO-MAS's 「MaaEnd 启动」
    (module docstring). (all done and AUTO-MAS will start the game windowed, notes).
    Each write is read back. `pythonw` is accepted for the callers' sake and not used."""
    from ark_relay.core import mastercfg  # noqa: PLC0415
    from ark_relay.features import commands  # noqa: PLC0415

    notes: list[str] = []
    home = Path(cfg.state_dir) / efstart.HOME
    home.mkdir(parents=True, exist_ok=True)
    target = efstart._read_json(home / efstart.TARGET)
    original = dict(target.get("original") or {})

    # The trampoline: the relay's own starts (efstart.run_on_desktop) run the helper through it.
    import ark_relay  # noqa: PLC0415
    root = code_root or Path(ark_relay.__file__).resolve().parents[1]
    trampoline = home / efstart.TRAMPOLINE
    if _write_if_changed(trampoline, trampoline_text(root)):
        notes.append(f"开游戏助手的入口已指向 {root}")
    stale = home / "start-endfield.cmd"        # what AUTO-MAS started until 10-16
    if stale.is_file():
        try:
            stale.unlink()
        except OSError:
            pass

    mfile = mastercfg.maaend_master(cfg.automas_dir)
    master, unreadable = _read_master(mfile)
    if unreadable:
        ok = False
        notes.append(unreadable)
    else:
        ok, master_notes = _clean_master(mfile, master)
        notes += master_notes

    reply, why = commands._backend_scripts()
    script = _mas_script(reply) if reply is not None else None
    game_cfg = dict((script or {}).get("Game") or {})
    mas_game = str(game_cfg.get("Path") or "")
    if reply is None:
        return False, notes + [f"调度程序没应答，终末地的开游戏设置没核对：{why or '连不上'}"]
    if script is None:
        return False, notes + ["调度程序里没有 MaaEnd 脚本，终末地的开游戏设置没核对"]
    game = _game_path(cfg, target, mas_game, master)
    if game is None:
        return False, notes + ["找不到 Endfield.exe 的位置（记录、调度程序、MaaEnd 都没有），调度程序的终末地路径没改"]

    now_game = mas_game
    if mas_game != str(game):
        done, text = commands._script_item_via_api(reply, "MaaEnd", "Game.Path", str(game))
        ok &= done
        if done:
            now_game = str(game)
        notes.append(("调度程序的终末地路径已改回游戏本体：" if done else "调度程序的终末地路径没改成：") + text)
    mode = str(game_cfg.get("LaunchMode") or "")
    if "LaunchMode" not in game_cfg:
        # An AUTO-MAS older than v5.7.0-beta.4 has no launcher mode; the boot self-check's
        # settings line (mascontract) is the one place that says a setting is missing.
        _log_efstart_setup.info("调度程序还没有「开终末地的方式」这一项（比 v5.7.0-beta.4 旧），没改")
    else:
        maaend_dir = str((script.get("Info") or {}).get("Path") or "") or cfg.maaend_dir
        why = (_launch_check(maaend_dir, str(game_cfg.get("ControllerType") or ""))
               or maaend_launch.stored_override(master))
        want = LAUNCH_MODE
        if why:
            want = FALLBACK_MODE
            notes.append(f"{texts.ENDFIELD_NO_MAAEND_START}：{why}")
        else:
            for key, value in WINDOWED.items():
                if game_cfg.get(key) == value:
                    continue
                done, text = commands._script_item_via_api(reply, "MaaEnd", f"Game.{key}", value)
                notes.append(text if done else f"终末地跑脚本时改窗口、跑完改回全屏的设置没改成（{key}）：{text}")
                if not done:
                    want = FALLBACK_MODE
            if want != LAUNCH_MODE:
                notes.append(f"{texts.ENDFIELD_NO_MAAEND_START}：上面那项设置没改成")
        ok &= want == LAUNCH_MODE
        if mode != want:
            done, text = commands._script_item_via_api(reply, "MaaEnd", "Game.LaunchMode", want)
            ok &= done
            if done:
                mode = want
            what = "由 MaaEnd 开终末地（1280×720 窗口，跑完改回全屏）" if want == LAUNCH_MODE else "经官方启动器开终末地"
            notes.append((f"调度程序已改成{what}：" if done else f"调度程序开终末地的方式没改成{what}：") + text)
    wait = original.get("wait_time")
    if isinstance(wait, int) and wait >= WAIT_MIN_S and game_cfg.get("WaitTime") != wait:
        done, text = commands._script_item_via_api(reply, "MaaEnd", "Game.WaitTime", wait)
        ok &= done
        notes.append(text if done else f"终末地开出来后的等待没改回 {wait} 秒：{text}")

    launcher = launcher_for(now_game, str(game_cfg.get("LauncherPath") or ""))
    if launcher is None and mode == LAUNCH_MODE:
        _log_efstart_setup.info("按调度程序的规矩从游戏位置找不到官方启动器（%s）；由 MaaEnd 开游戏时它自己找，不影响",
                 now_game or "空")
    elif launcher is None:
        ok = False
        notes.append(f"{texts.ENDFIELD_NO_LAUNCHER}（调度程序里的游戏位置：{now_game or '空'}）")

    new_target = {"game": str(game), "launcher": str(launcher or target.get("launcher") or ""),
                  "trampoline": str(trampoline), "original": original}
    if new_target != target:
        atomic_write_text(home / efstart.TARGET, json.dumps(new_target, ensure_ascii=False, indent=1))
    return ok, notes


def restore(cfg) -> "tuple[bool, list[str]]":
    """Undo what the relay itself set: its helper preAction in the MaaEnd master, the raised
    Game.WaitTime, and 「MaaEnd 启动」 with its four window settings (back to 「启动器启动」 and
    WINDOWED_BEFORE; the launcher's 「DirectX 11 启动」 box must then be ticked by hand again).
    Never puts back the direct Endfield.exe start (1.6.3 refuses it) or the helper's .cmd
    as Game.Path. For going back by hand; nothing calls it on its own."""
    from ark_relay.core import mastercfg  # noqa: PLC0415
    from ark_relay.features import commands  # noqa: PLC0415

    home = Path(cfg.state_dir) / efstart.HOME
    original = efstart._read_json(home / efstart.TARGET).get("original") or {}
    mfile = mastercfg.maaend_master(cfg.automas_dir)
    master, unreadable = _read_master(mfile)
    ok, notes = (False, [unreadable]) if unreadable else _clean_master(mfile, master)
    reply, why = commands._backend_scripts()
    if reply is None:
        return False, notes + [f"调度程序没应答：{why or '连不上'}"]
    wait = original.get("wait_time")
    if isinstance(wait, int) and wait >= WAIT_MIN_S:
        done, text = commands._script_item_via_api(reply, "MaaEnd", "Game.WaitTime", wait)
        ok &= done
        notes.append(text)
    script = _mas_script(reply) or {}
    if "LaunchMode" in (script.get("Game") or {}):
        for key, value in [("LaunchMode", FALLBACK_MODE), *WINDOWED_BEFORE.items()]:
            done, text = commands._script_item_via_api(reply, "MaaEnd", f"Game.{key}", value)
            ok &= done
            notes.append(text)
    return ok, notes


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
# Not an exit code of the helper: run_on_desktop stopped waiting for it because the relay
# is stopping (nothing judged; collect_retry leaves its stamp open for the next start).
STOPPED = 10
# The pretask ran (or may still run): it writes the window settings before starting the
# launcher, so the caller has fullscreen to put back even though the start failed.
RAN = (PRETASK, TIMED_OUT)

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
    from ark_relay.features.preupdate import _spawn_via_task  # noqa: PLC0415

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
        try:
            if got:
                win32event.ReleaseMutex(h)
        finally:
            h.Close()


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
                   clock=time.monotonic, pythonw=None, poll_s: float = 5.0, stopping=None) -> Result:
    """Run the helper on the interactive desktop from the relay's service and wait for its
    result. `spawn(exe, cwd, args)` is preupdate_common._spawn_interactive in production.
    wait_s: the helper may first wait WHOLE_S for another start's lock, then start.
    poll_s: how often the result file is looked for; a start takes minutes.
    stopping (default preupdate_common.going_down): asked at every poll; a stopping relay
    stops waiting with STOPPED. This wait runs on the main loop's thread (the shutdown
    decision's gathering retry), where until 11-08 a stop sat it out to the 15 s hard
    exit (audit 11-08 A-23)."""
    if stopping is None:
        from ark_relay.features.preupdate import going_down as stopping  # noqa: PLC0415
    if pythonw is None:
        from ark_relay.features.preupdate import _pythonw  # noqa: PLC0415
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
        if stopping():
            return Result(STOPPED, "中继正在停止，不等开游戏的助手了")
        if result.is_file():
            d = _read_json(result)
            _drop(result)
            return Result(int(d.get("code", LAUNCHER)), str(d.get("reason") or ""), str(d.get("shot") or ""))
        sleep(poll_s)
    return Result(TIMED_OUT, f"开游戏的助手 {wait_s / 60:.0f} 分钟没给结果")
