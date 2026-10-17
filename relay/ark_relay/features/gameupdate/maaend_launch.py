"""MaaEnd's own windowed start of Endfield and its fullscreen restore, read from MaaEnd's files.

Why windowed (2026-10-16/17): with the launcher's 「DirectX 11 启动」 box unticked the game
runs on Vulkan, and MaaEnd reads a fullscreen Vulkan game as 「当前环境识别异常」. MaaEnd's
own hint names the way out: a window smaller than the desktop. MaaEnd v2.33.0 ships both
halves:

* the pretask LaunchGamePC (assets/tasks/pretasks/LaunchGamePC.json, exec agent/go-service
  with args ["--pretask", "LaunchGamePC", <options as JSON>]; exit code 0 = success,
  agent/go-service/pretask/pretask.go). With LaunchGamePCGameSetting "Yes" it writes the
  display settings into the registry, starts Launcher.exe and clicks 「开始游戏」 in the real
  launcher, so Games.exe stays the game's parent (client 1.6.3 refuses any other parent).
  It skips everything when Endfield.exe already runs (launchgamepc.go Run).
* the task CloseGamePC (assets/tasks/CloseGamePC.json, custom action CloseGameAction in
  go-service, common/closegame/action.go): kills Endfield.exe and, with
  attach.ApplyGameSetting, writes the display type and the resolution back.

AUTO-MAS v5.7.0-beta.5's Game.LaunchMode "MaaEnd" runs the first before a MaaEnd run and
the second after it (AutoProxy.py:502-519, 557-658, 2215-2222, 1937-2031). The machine ran
that once on 2026-10-17 11:31-11:35 Beijing (go-service.log): LAUNCH_VALUES below are the
options it sent, a 1280x720 window came up with Games.exe as the parent, and CloseGamePC
wrote Fullscreen 1920x1080 back. The relay's own gathering retry (collect_retry) starts
and closes the game the same way (efstart.py), and efstart_setup checks before switching
AUTO-MAS to that mode that the installed MaaEnd still declares every name used here.

Nothing here guesses: a name or case MaaEnd no longer declares is a reason, said in Chinese
(the WARNING the group hears); the technical detail goes to the log.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("ark.maaend_launch")

PRETASK = "LaunchGamePC"
CLOSE_TASK = "CloseGamePC"
# The options AUTO-MAS v5.7.0-beta.5 sent on 2026-10-17 11:31:05 (go-service.log
# 「Pretask invoked」): its own SetResolution switch sets LaunchGamePCGameSetting, the rest
# are LaunchGamePC.json's default cases. Window 1280x720 is the only listed size below the
# machine's 1920x1080 desktop. Options not named here take their default case, as AUTO-MAS
# does (run_plan._collect_pretask_option_values); for v2.33.0 that is "Unchanged" for the
# language, graphics quality, frame rate and Auto HDR.
LAUNCH_VALUES = {
    "LaunchGamePCRegion": "CN",
    "LaunchGamePCLauncherPath": "Auto",
    "LaunchGamePCGameSetting": "Yes",
    "LaunchGamePCDisplayType": "Window",
    "LaunchGamePCResolution": "1280x720",
}
# What CloseGamePC writes back: the owner's own settings, fullscreen 1920x1080 (registry on
# 2026-10-17 10:2x: Screenmanager Fullscreen mode 1, 1920x1080). Both width and height, or
# CloseGameAction refuses before closing the game ("incomplete or invalid resolution
# attach"); region and language as CloseGameAction defaults them (CN, Unchanged); graphics
# quality, frame rate and Auto HDR left out = unchanged (loadAttach).
RESTORE_ATTACH = {
    "ApplyGameSetting": True,
    "GameSettingRegion": "CN",
    "GameSettingLanguage": "Unchanged",
    "GameSettingDisplayType": "Fullscreen",
    "ResolutionWidth": 1920,
    "ResolutionHeight": 1080,
}
# The CloseGamePC options whose pipeline_override carries those attach keys (CloseGamePC.json).
_RESTORE_OPTIONS = {
    "CloseGamePCApplyGameSetting": ("Yes", {"ApplyGameSetting"}),
    "CloseGamePCGameSettingDisplayType": ("Fullscreen", {"GameSettingDisplayType"}),
    "CloseGamePCGameSettingResolution": (None, {"ResolutionWidth", "ResolutionHeight"}),
}


def read_decls(maaend_dir) -> "tuple[list[dict], dict, dict, list[str], str]":
    """(pretasks, options, tasks, controller names, why) from MaaEnd's interface.json and
    the files it imports. why is "" when interface.json could be read."""
    from ark_relay.core.mastercfg import _jsonc  # noqa: PLC0415 - MaaEnd's files are JSON with comments
    if not maaend_dir:
        return [], {}, {}, [], "不知道 MaaEnd 装在哪"
    root = Path(str(maaend_dir))
    try:
        iface = _jsonc(root / "interface.json")
    except (OSError, ValueError, TypeError) as exc:
        log.info("MaaEnd 的 interface.json 读不了：%s: %s", type(exc).__name__, exc)
        return [], {}, {}, [], "读不到 MaaEnd 的定义文件清单"
    pretasks: list[dict] = []
    opts: dict = {}
    tasks: dict = {}

    def take(d: dict) -> None:
        pre = d.get("pretask")
        pretasks.extend(p for p in (pre if isinstance(pre, list) else [pre]) if isinstance(p, dict))
        for name, spec in (d.get("option") or {}).items():
            opts.setdefault(name, spec if isinstance(spec, dict) else {})
        for t in d.get("task") or []:
            if isinstance(t, dict) and t.get("name"):
                tasks.setdefault(t["name"], t)
    take(iface)
    for rel in iface.get("import") or []:
        if not isinstance(rel, str):
            continue
        try:
            take(_jsonc(root / rel))
        except (OSError, ValueError, TypeError) as exc:
            log.info("MaaEnd 的定义文件 %s 读不了：%s", rel, exc)
    controllers = [str(c.get("name")) for c in iface.get("controller") or [] if isinstance(c, dict)]
    return pretasks, opts, tasks, controllers, ""


def _cases(spec: dict) -> dict:
    return {str(c.get("name")): c for c in spec.get("cases") or [] if isinstance(c, dict)}


def launch_options(pretask: dict, opts: dict) -> "tuple[dict | None, str]":
    """The pretask's option values, built the way AUTO-MAS builds them: every option the
    pretask lists, then the options of each chosen case, depth first; LAUNCH_VALUES where
    named, else the option's default case. (None, why) when a named option or case is missing."""
    values: dict = {}
    missing: list[str] = []

    def collect(name: str) -> None:
        if name in values:
            return
        spec = opts.get(name)
        if not isinstance(spec, dict) or spec.get("type") not in ("select", "switch"):
            missing.append(f"option {name}")
            return
        cases = _cases(spec)
        value = LAUNCH_VALUES.get(name, spec.get("default_case"))
        if value not in cases:
            missing.append(f"{name}={value}")
            return
        values[name] = value
        for nested in cases[value].get("option") or []:
            collect(str(nested))
    for name in pretask.get("option") or []:
        collect(str(name))
    missing += [f"{k} not reached" for k in LAUNCH_VALUES
                if k not in values and not any(m.startswith(f"{k}=") or m == f"option {k}" for m in missing)]
    if missing:
        log.info("MaaEnd 的开游戏预任务对不上：%s", "; ".join(missing))
        return None, "MaaEnd 的开游戏预任务里缺了「1280×720 窗口」要用的选项"
    return values, ""


def launch_plan(maaend_dir, controller: str = "", decls=None) -> "tuple[dict | None, str]":
    """{"exec": the pretask's exec as declared, "args": [...]}, or (None, why).
    `controller` (AUTO-MAS's Game.ControllerType) must be one the pretask supports: its own
    list, or every controller of the interface when it lists none (AUTO-MAS
    resource_loader.pretask_controllers)."""
    pretasks, opts, _tasks, controllers, why = decls or read_decls(maaend_dir)
    if why:
        return None, why
    pre = next((p for p in pretasks if p.get("name") == PRETASK), None)
    if pre is None:
        log.info("MaaEnd 的定义里没有预任务 %s", PRETASK)
        return None, "这个版本的 MaaEnd 没有「由 MaaEnd 开游戏」的预任务"
    if controller:
        allowed = [str(c) for c in pre.get("controller") or []] or controllers
        if controller not in allowed:
            log.info("预任务 %s 支持的控制器 %s，调度程序用的是 %s", PRETASK, allowed, controller)
            return None, "MaaEnd 的开游戏预任务不支持调度程序给终末地选的控制器"
    if not pre.get("exec"):
        return None, "MaaEnd 的开游戏预任务没写要运行的程序"
    values, why = launch_options(pre, opts)
    if values is None:
        return None, why
    args = [str(a) for a in pre.get("args") or []]
    args.append(json.dumps(values, ensure_ascii=False, separators=(",", ":")))
    return {"exec": str(pre["exec"]), "args": args}, ""


def restore_override(maaend_dir, decls=None) -> "tuple[dict | None, str]":
    """The pipeline override that makes CloseGamePC write fullscreen 1920x1080 back, after
    checking that MaaEnd's CloseGamePC still carries those attach keys. (None, why) if not."""
    _pre, opts, tasks, _ctl, why = decls or read_decls(maaend_dir)
    if why:
        return None, why
    task = tasks.get(CLOSE_TASK)
    if not isinstance(task, dict) or task.get("entry") != CLOSE_TASK:
        log.info("MaaEnd 的定义里没有任务 %s（入口 %s）", CLOSE_TASK, CLOSE_TASK)
        return None, "这个版本的 MaaEnd 没有「关游戏」任务"
    missing = []
    for name, (case, keys) in _RESTORE_OPTIONS.items():
        spec = opts.get(name) or {}
        node = (_cases(spec).get(case) or {}) if case else spec
        attach = ((node.get("pipeline_override") or {}).get(CLOSE_TASK) or {}).get("attach") or {}
        if not keys <= set(attach):
            missing.append(f"{name}{'=' + case if case else ''} -> {sorted(keys - set(attach))}")
    if "CloseGamePCApplyGameSetting" not in (task.get("option") or []):
        missing.append("task option CloseGamePCApplyGameSetting")
    if missing:
        log.info("MaaEnd 的关游戏任务对不上：%s", "; ".join(missing))
        return None, "MaaEnd 的关游戏任务没法再把游戏改回 1920×1080 全屏"
    return {CLOSE_TASK: {"attach": dict(RESTORE_ATTACH)}}, ""


def check(maaend_dir, controller: str) -> str:
    """'' when MaaEnd can start the game windowed for this controller and put fullscreen
    back afterwards; else the Chinese reason."""
    if not controller:
        return "调度程序里终末地没选控制器"
    decls = read_decls(maaend_dir)
    _plan, why = launch_plan(maaend_dir, controller, decls)
    if why:
        return why
    _over, why = restore_override(maaend_dir, decls)
    return why


def executable(maaend_dir, raw_exec: str) -> "Path | None":
    """The pretask's program in the MaaEnd folder; ".exe" added when the declared name has
    no suffix and only the .exe exists (AUTO-MAS run_plan._resolve_pretask_executable)."""
    p = Path(str(maaend_dir)) / raw_exec
    if p.is_file():
        return p
    if not p.suffix and p.with_suffix(".exe").is_file():
        return p.with_suffix(".exe")
    return None
