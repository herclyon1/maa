"""Leave Endfield's start to AUTO-MAS's 「MaaEnd 启动」 mode, windowed; run at each relay start.

Since client 1.6.3 (2026-10-15) the game runs only when the official launcher starts it
(efstart.py has the evidence). From 10-15 to 10-16 the relay pointed AUTO-MAS's MaaEnd
Game.Path at its own helper (state/efstart/start-endfield.cmd) and put the helper in the
MaaEnd master as a preAction; AUTO-MAS v5.7.0-beta.4's pre-run check found no launcher from
the .cmd, and the morning MaaEnd run was skipped (its app.log, 10-16 09:34:05:
「未通过配置检查: 未找到终末地官方启动器」). From 10-16 to 10-17 the relay kept AUTO-MAS on
Game.LaunchMode "Launcher" (AUTO-MAS clicks 「开始游戏」 itself), with the launcher's 「DirectX 11 启动」 box ticked by hand: MaaEnd reads a fullscreen non-DX11 game
as 「当前环境识别异常」, and the launcher remembers the tick, so the owner's own play started
in DX11 too.

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
from datetime import datetime
from pathlib import Path, PureWindowsPath

from ark_relay.core import texts
from ark_relay.core.config import atomic_write_bytes, atomic_write_text
from ark_relay.features.gameupdate import efstart, maaend_launch

log = logging.getLogger("ark.efstart_setup")

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
# Script-level Game settings 「MaaEnd 启动」 needs (AUTO-MAS v5.7.0-beta.5 app/models/config.py
# MaaEndConfig; values as set and run on the machine 10-17 11:31). Written before LaunchMode.
WINDOWED = {"SetResolution": True, "CloseOnFinish": True,
            "RestoreDisplayType": "Fullscreen", "RestoreResolution": "1920x1080"}
# Their values before the relay set them (AUTO-MAS API read 10-17 10:2x Beijing): restore().
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
            "from ark_relay.features.gameupdate import efstart\n"
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
        from ark_relay.features.makeup.collect_retry import _game_exe  # noqa: PLC0415
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
    from ark_relay.features.phone import commands  # noqa: PLC0415

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
        log.info("调度程序还没有「开终末地的方式」这一项（比 v5.7.0-beta.4 旧），没改")
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
        log.info("按调度程序的规矩从游戏位置找不到官方启动器（%s）；由 MaaEnd 开游戏时它自己找，不影响",
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
    from ark_relay.features.phone import commands  # noqa: PLC0415

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
