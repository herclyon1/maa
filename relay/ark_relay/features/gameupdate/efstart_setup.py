"""Point every Endfield start at the launcher helper (efstart.py); run at each relay start.

Since client 1.6.3 (2026-10-15) the game runs only when the official launcher starts it
(efstart.py has the evidence). Three things started Endfield.exe directly; at every relay
start this module points each of them at the helper, so the machine converges by itself
after a deploy and stays converged if someone puts a path back by hand:

1. state/efstart/efstart.py, a trampoline that runs efstart.main from the code folder in
   use (rewritten when the version folder changes), and start-endfield.cmd, which runs it
   with the relay's own pythonw.exe. Both live in the data folder, so the paths written
   into AUTO-MAS and MaaEnd stay the same across versions.
2. AUTO-MAS's MaaEnd script Game.Path -> start-endfield.cmd. AUTO-MAS (account switch "MAS")
   starts Game.Path itself, sleeps Game.WaitTime, then looks for the game window; it also
   injects Game.Path as MaaEnd's first preAction (AutoProxy.py:243-274 / 950-967, v5.6.2).
   Not the pythonw.exe itself: on a failed attempt AUTO-MAS runs taskkill /F /T on every
   process whose image path equals Game.Path (kill_game_process, AutoProxy.py:1162-1169),
   and the relay runs under that pythonw.exe. With the .cmd that kill matches nothing, so
   Endfield is no longer closed between AUTO-MAS's attempts (the next attempt finds it
   running); the relay's make-up still closes it first (makeup.py). Game.WaitTime is
   raised to WAIT_FLOOR_S when lower, so the window is there when AUTO-MAS looks.
3. The MaaEnd master's preAction that ran Endfield.exe -> the helper under pythonw.exe with
   waitForExit (MXU waits for it, no timeout: src-tauri/src/commands/system.rs:591-623,
   MXU v2.7.1) and skipIfRunning off (MXU compares the full program path, and the relay's
   own pythonw.exe is always running). AUTO-MAS's injected entry (id automas-endfield) is
   never touched.

What each place held before is kept in state/efstart/target.json ("original"), written
once, and restore() puts it back.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path, PureWindowsPath

from ark_relay.core.config import atomic_write_bytes, atomic_write_text
from ark_relay.features.gameupdate import efstart

log = logging.getLogger("ark.efstart_setup")

# The game and launcher paths are Windows paths read from AUTO-MAS and MaaEnd; the day
# simulator replaces these two to answer them from its sim tree.
_is_file = os.path.isfile


def _find_pythonw() -> "Path | None":
    from ark_relay.features.preupdate.preupdate_common import _pythonw  # noqa: PLC0415
    return _pythonw()

CMD = "start-endfield.cmd"
AUTOMAS_PREACTION_ID = "automas-endfield"     # AUTO-MAS's own entry (AutoProxy.py:243-274)
OUR_PREACTION_ID = "ark-efstart"
PREACTION_NAME = "▶️ 经官方启动器启动终末地（中继）"
# Measured 10-15 15:19-15:21 (the parent session, by hand): Launcher.exe to the game window
# took about 2 minutes. AUTO-MAS looks for the window once, WaitTime after starting Game.Path
# (AutoProxy.py:957-967, then login() FindWindow), so it gets that plus a minute.
WAIT_FLOOR_S = 180


def _is_game(prog: str) -> bool:
    return PureWindowsPath(str(prog or "")).name.lower() == efstart.GAME_EXE.lower()


def _ours(action: dict) -> bool:
    return efstart.TRAMPOLINE in str(action.get("args") or "")


def desired_preaction(pythonw: Path, trampoline: Path, action_id: str = OUR_PREACTION_ID) -> dict:
    # MXU splits `args` with shell rules (shell_words::split, system.rs:573-574), so the
    # trampoline path, which may hold spaces, is quoted.
    return {"id": action_id, "customName": PREACTION_NAME, "enabled": True,
            "program": str(pythonw), "args": f'"{trampoline}" --caller maaend',
            "waitForExit": True, "skipIfRunning": False, "useCmd": False}


def rewrite_preactions(doc: dict, pythonw: Path, trampoline: Path) -> "tuple[bool, list[dict]]":
    """Point each instance's game-starting preAction at the helper, in place.

    The first entry that starts Endfield.exe (or is ours already) becomes ours, keeping its
    id; any later such entry is dropped (they would all be the same helper); an instance
    without one gets ours appended. Returns (changed, the entries it replaced or dropped)."""
    changed, replaced = False, []
    for inst in doc.get("instances") or []:
        if not isinstance(inst, dict):
            continue
        acts = inst.get("preActions") if isinstance(inst.get("preActions"), list) else []
        out, placed = [], False
        for a in acts:
            mine = (isinstance(a, dict) and a.get("id") != AUTOMAS_PREACTION_ID
                    and (_is_game(str(a.get("program") or "")) or _ours(a)))
            if not mine:
                out.append(a)
                continue
            want = desired_preaction(pythonw, trampoline, str(a.get("id") or OUR_PREACTION_ID))
            if placed:
                changed = True
                if not _ours(a):
                    replaced.append(a)
                continue
            placed = True
            if a != want:
                changed = True
                if not _ours(a):
                    replaced.append(a)
            out.append(want)
        if not placed:
            out.append(desired_preaction(pythonw, trampoline))
            changed = True
        inst["preActions"] = out
    return changed, replaced


def trampoline_text(code_root: Path) -> str:
    return ("# Written by the relay at every start (ark_relay/features/gameupdate/efstart_setup.py).\n"
            "# Runs the launcher helper from the code folder in use; do not edit.\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(code_root)!r})\n"
            "from ark_relay.features.gameupdate import efstart\n"
            "sys.exit(efstart.main(['--home', str(Path(__file__).resolve().parent)] + sys.argv[1:]))\n")


def cmd_text(pythonw: Path, trampoline: Path) -> str:
    # Batch files run each command to its end and keep its exit code; AUTO-MAS's
    # Game.Arguments, passed after the .cmd, are not forwarded.
    return ("@echo off\r\n"
            "rem Written by the relay at every start (efstart_setup.py): AUTO-MAS starts this\r\n"
            "rem as the MaaEnd game, so the game comes up through the official launcher.\r\n"
            f'"{pythonw}" "{trampoline}" --caller automas\r\n'
            "exit /b %ERRORLEVEL%\r\n")


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
    cands = [str(target.get("game") or ""), mas_game]
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


def install(cfg, *, pythonw: "Path | None" = None, code_root: "Path | None" = None) -> "tuple[bool, list[str]]":
    """Make every Endfield start go through the helper. (all done, what was done or not).

    Nothing is written into AUTO-MAS or MaaEnd unless the helper's own files are in place.
    Each write is read back."""
    from ark_relay.core import mastercfg  # noqa: PLC0415
    from ark_relay.features.phone import commands  # noqa: PLC0415

    notes: list[str] = []
    home = Path(cfg.state_dir) / efstart.HOME
    home.mkdir(parents=True, exist_ok=True)
    target = efstart._read_json(home / efstart.TARGET)
    original = dict(target.get("original") or {})

    reply, why = commands._backend_scripts()
    script = _mas_script(reply) if reply is not None else None
    mas_game = str(((script or {}).get("Game") or {}).get("Path") or "")
    mfile = mastercfg.maaend_master(cfg.automas_dir)
    try:
        master = json.loads(mfile.read_text(encoding="utf-8")) if mfile and mfile.is_file() else None
    except (OSError, ValueError) as exc:
        return False, [f"MaaEnd 母本读不了（{mfile}：{exc}），没改终末地的启动方式"]
    game = _game_path(cfg, target, mas_game, master)
    if game is None:
        return False, ["找不到 Endfield.exe 的位置（记录、调度程序、MaaEnd 都没有），没改终末地的启动方式"]
    # D:\endfield\Hypergryph Launcher\games\Endfield Game\Endfield.exe: three levels up
    # is the launcher's folder (gameupdate_games.endfield_paths).
    wgame = PureWindowsPath(str(game))
    launcher = wgame.parents[2] / "Launcher.exe" if len(wgame.parents) >= 3 else None
    if launcher is None or not _is_file(str(launcher)):
        return False, [f"找不到官方启动器（{launcher}），没改终末地的启动方式"]
    pyw = pythonw or _find_pythonw()
    if pyw is None:
        return False, ["中继自带的 pythonw.exe 找不到，没改终末地的启动方式"]
    import ark_relay  # noqa: PLC0415
    root = code_root or Path(ark_relay.__file__).resolve().parents[1]
    trampoline = home / efstart.TRAMPOLINE
    cmd = home / CMD
    if not (str(pyw).isascii() and str(trampoline).isascii()):
        # cmd.exe reads a batch file in the console code page, not UTF-8.
        return False, [f"路径里有非英文字符（{pyw}，{trampoline}），批处理读不对，没改终末地的启动方式"]
    if _write_if_changed(trampoline, trampoline_text(root)):
        notes.append(f"开游戏助手的入口已指向 {root}")
    _write_if_changed(cmd, cmd_text(pyw, trampoline))

    ok = True
    # MaaEnd master: the preAction.
    if master is None:
        ok = False
        notes.append("MaaEnd 母本找不到，它的前置程序没改")
    else:
        changed, replaced = rewrite_preactions(master, pyw, trampoline)
        if replaced and "preactions" not in original:
            original["preactions"] = replaced
        if changed:
            bak = mfile.with_name(mfile.name + f".bak-efstart-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            bak.write_bytes(mfile.read_bytes())
            atomic_write_text(mfile, json.dumps(master, ensure_ascii=False, indent=2))
            back = json.loads(mfile.read_text(encoding="utf-8"))
            if rewrite_preactions(back, pyw, trampoline)[0]:
                ok = False
                notes.append(f"MaaEnd 母本的前置程序写进去读出来不对，{bak.name} 是原样")
            else:
                notes.append(f"MaaEnd 的前置程序已改成经官方启动器开游戏（原文件备份 {bak.name}）")

    # AUTO-MAS: Game.Path and the floor of Game.WaitTime.
    if reply is None:
        ok = False
        notes.append(f"调度程序没应答，它的终末地路径没改：{why or '连不上'}")
    elif script is None:
        ok = False
        notes.append("调度程序里没有 MaaEnd 脚本，它的终末地路径没改")
    else:
        if mas_game != str(cmd):
            if "game_path" not in original:
                original["game_path"] = mas_game
            done, text = commands._script_item_via_api(reply, "MaaEnd", "Game.Path", str(cmd))
            ok &= done
            notes.append(("调度程序的终末地路径已改成经官方启动器开：" if done else "调度程序的终末地路径没改成：") + text)
        wait = (script.get("Game") or {}).get("WaitTime")
        if isinstance(wait, int) and wait < WAIT_FLOOR_S:
            if "wait_time" not in original:
                original["wait_time"] = wait
            done, text = commands._script_item_via_api(reply, "MaaEnd", "Game.WaitTime", WAIT_FLOOR_S)
            ok &= done
            notes.append(text if done else f"终末地启动后等待没改成 {WAIT_FLOOR_S} 秒：{text}")
    new_target = {"game": str(game), "launcher": str(launcher), "cmd": str(cmd),
                  "trampoline": str(trampoline), "original": original}
    if new_target != target:
        atomic_write_text(home / efstart.TARGET, json.dumps(new_target, ensure_ascii=False, indent=1))
    return ok, notes


def restore(cfg) -> "tuple[bool, list[str]]":
    """Put back what install() replaced: AUTO-MAS's Game.Path and Game.WaitTime, and the
    master's preAction(s). For going back by hand; nothing calls it on its own."""
    from ark_relay.core import mastercfg  # noqa: PLC0415
    from ark_relay.features.phone import commands  # noqa: PLC0415

    home = Path(cfg.state_dir) / efstart.HOME
    original = efstart._read_json(home / efstart.TARGET).get("original") or {}
    notes, ok = [], True
    mfile = mastercfg.maaend_master(cfg.automas_dir)
    if mfile and mfile.is_file() and original.get("preactions"):
        doc = json.loads(mfile.read_text(encoding="utf-8"))
        for inst in doc.get("instances") or []:
            acts = [a for a in inst.get("preActions") or [] if not (isinstance(a, dict) and _ours(a))]
            inst["preActions"] = acts + list(original["preactions"])
        atomic_write_text(mfile, json.dumps(doc, ensure_ascii=False, indent=2))
        notes.append("MaaEnd 的前置程序已改回")
    reply, why = commands._backend_scripts()
    if reply is None:
        return False, notes + [f"调度程序没应答：{why or '连不上'}"]
    for key, path in (("game_path", "Game.Path"), ("wait_time", "Game.WaitTime")):
        if key in original:
            done, text = commands._script_item_via_api(reply, "MaaEnd", path, original[key])
            ok &= done
            notes.append(text)
    return ok, notes
