"""Endfield starts windowed through MaaEnd's own launcher pretask, and goes back to fullscreen (10-17).

DECISIONS D-1016-终末地等AUTO-MAS新版 (the owner said 「好」 on 10-16): the launcher's
「DirectX 11 启动」 box is to be unticked, so the game must run windowed below the 1920x1080
desktop, which MaaEnd reads on any graphics API. AUTO-MAS v5.7.0-beta.5's Game.LaunchMode
"MaaEnd" does that: MaaEnd's pretask LaunchGamePC writes a 1280x720 window, starts the real
launcher and clicks 「开始游戏」 (Games.exe stays the parent), and CloseGamePC writes Fullscreen
1920x1080 back after the run. The machine ran it once on 2026-10-17 11:31-11:35 Beijing:
go-service.log 11:31:05 「Pretask invoked」 with MACHINE_ARGS below, 11:33:31 「CloseGameAction:
applied game settings」 Fullscreen 1920x1080.

Pinned here:
* maaend_launch builds exactly the pretask arguments AUTO-MAS sent that day from MaaEnd
  v2.33.0's own files (fixtures/maaend-v2.33.0-launch), and refuses, in plain Chinese, a MaaEnd
  that no longer declares a name it needs;
* efstart_setup puts AUTO-MAS on 「MaaEnd 启动」 with the four window settings (written before the
  mode, each read back), and when MaaEnd cannot do it, keeps 「启动器启动」 with a WARNING (the
  group): with the box unticked every run of that mode fails;
* the relay's own start (the gathering retry, efstart) runs the same pretask on the desktop,
  checks its exit code and never touches the DirectX 11 box; collect_retry puts fullscreen back
  through CloseGamePC before MaaEnd is closed, and says so when it could not.
"""
import json
import logging
import shutil
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from _tmp import tmpdir  # noqa: E402 - after the sys.path lines above

from ark_relay.core import texts  # noqa: E402
from ark_relay.features.gameupdate import efstart as ef  # noqa: E402
from ark_relay.features.gameupdate import efstart_setup as setup  # noqa: E402
from ark_relay.features.makeup import collect_retry as cr  # noqa: E402
from ark_relay.features.phone import commands  # noqa: E402
try:
    from ark_relay.features.gameupdate import maaend_launch as ml
except ImportError:                 # the code before this change
    ml = None

fails = []
# Names this change brings in, looked up so the file runs (and fails check by check) on the code before it.
NO_MAAEND_START = getattr(texts, "ENDFIELD_NO_MAAEND_START", "\0 not defined")
PRETASK = getattr(ef, "PRETASK", -5)


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


FX = HERE / "fixtures" / "maaend-v2.33.0-launch"
BETA2 = HERE / "gamesim" / "upstream" / "maaend-v2.33.0-beta.2"     # still the old GameSetting pretask
# go-service.log on the machine, 2026-10-17 11:31:05 (AUTO-MAS v5.7.0-beta.5, 「Pretask invoked」 args).
MACHINE_ARGS = ('{"LaunchGamePCRegion":"CN","LaunchGamePCLauncherPath":"Auto","LaunchGamePCGameSetting":"Yes",'
                '"LaunchGamePCLanguage":"Unchanged","LaunchGamePCDisplayType":"Window","LaunchGamePCResolution":"1280x720",'
                '"LaunchGamePCGraphicsQuality":"Unchanged","LaunchGamePCFrameRate":"Unchanged","LaunchGamePCAutoHDR":"Unchanged"}')
RESTORE = {"CloseGamePC": {"attach": {"ApplyGameSetting": True, "GameSettingRegion": "CN",
                                      "GameSettingLanguage": "Unchanged", "GameSettingDisplayType": "Fullscreen",
                                      "ResolutionWidth": 1920, "ResolutionHeight": 1080}}}


def maaend_copy(edit=None) -> Path:
    """The fixture MaaEnd in a temp folder, with go-service.exe where AUTO-MAS finds it."""
    d = tmpdir() / "maaend"
    shutil.copytree(FX, d)
    (d / "agent").mkdir()
    (d / "agent" / "go-service.exe").write_bytes(b"")
    if edit:
        edit(d)
    return d


def edit_json(path: Path, fn) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


print("[maaend_launch: MaaEnd v2.33.0's own files give exactly what AUTO-MAS sent on 10-17]")
check("maaend_launch exists", ml is not None)
if ml is not None:
    plan, why = ml.launch_plan(FX, "Win32-Front")
    check("the pretask's program as declared", (plan or {}).get("exec"), "agent/go-service")
    check("arguments: --pretask LaunchGamePC + the machine's 11:31:05 options, byte for byte",
          (plan or {}).get("args"), ["--pretask", "LaunchGamePC", MACHINE_ARGS])
    d = maaend_copy()
    check("its program: agent/go-service.exe in the MaaEnd folder (.exe added as AUTO-MAS adds it)",
          ml.executable(d, "agent/go-service"), d / "agent" / "go-service.exe")
    check("no program there: None", ml.executable(tmpdir(), "agent/go-service"), None)
    check("CloseGamePC override: fullscreen 1920x1080, both sizes, region/language as its defaults",
          ml.restore_override(FX), (RESTORE, ""))
    check("the machine's controller Win32-Front: everything there", ml.check(FX, "Win32-Front"), "")

    print("\n[a MaaEnd that cannot do it: refused with a plain reason, nothing guessed]")
    reasons = {
        "controller ADB": ml.check(FX, "ADB"),
        "no controller set": ml.check(FX, ""),
        "v2.33.0-beta.2 (GameSetting, no LaunchGamePC)": ml.check(BETA2, "Win32-Front"),
        "no MaaEnd folder": ml.check(tmpdir() / "nothing", "Win32-Front"),
        "1280x720 renamed": ml.check(maaend_copy(lambda d: edit_json(
            d / "tasks" / "pretasks" / "LaunchGamePC.json",
            lambda j: j["option"]["LaunchGamePCResolution"]["cases"][0].update(name="1280*720"))), "Win32-Front"),
        "Window case gone": ml.check(maaend_copy(lambda d: edit_json(
            d / "tasks" / "pretasks" / "LaunchGamePC.json",
            lambda j: j["option"]["LaunchGamePCDisplayType"]["cases"].pop(0))), "Win32-Front"),
        "CloseGamePC without the height attach": ml.check(maaend_copy(lambda d: edit_json(
            d / "tasks" / "CloseGamePC.json",
            lambda j: j["option"]["CloseGamePCGameSettingResolution"]["pipeline_override"]["CloseGamePC"]["attach"]
            .pop("ResolutionHeight"))), "Win32-Front"),
        "CloseGamePC gone": ml.check(maaend_copy(lambda d: edit_json(
            d / "interface.json", lambda j: j["import"].pop())), "Win32-Front"),
    }
    for what, why in reasons.items():
        check(f"{what}: refused", bool(why), True)
    check("every reason is plain Chinese", {w: texts.plain(r) for w, r in reasons.items() if texts.plain(r)}, {})

# ─────────────────────────── efstart_setup.install ───────────────────────────

print("\n[efstart_setup: AUTO-MAS on 「MaaEnd 启动」 with the four window settings, written before the mode]")
root = tmpdir()
lroot = root / "endfield" / "Hypergryph Launcher"
game_dir = lroot / "games" / "Endfield Game"
game_dir.mkdir(parents=True)
(game_dir / "Endfield.exe").write_text("", encoding="utf-8")
(lroot / "Launcher.exe").write_text("", encoding="utf-8")
(lroot / "1.6.0").mkdir()
(lroot / "1.6.0" / "Games.exe").write_text("", encoding="utf-8")
game_exe = str(game_dir / "Endfield.exe")
setup._is_file = lambda p: Path(str(p).replace("\\", "/")).is_file()
setup._subdirs = lambda p: [str(x) for x in Path(str(p).replace("\\", "/")).iterdir() if x.is_dir()] \
    if Path(str(p).replace("\\", "/")).is_dir() else []
automas = root / "automas"
cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
cfgdir.mkdir(parents=True)
(cfgdir / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"name": "automas", "preActions": []}]}),
                                        encoding="utf-8")
home = root / "state" / "efstart"
home.mkdir(parents=True)
(home / ef.TARGET).write_text(json.dumps({"game": game_exe, "original": {"game_path": game_exe, "wait_time": 60}}),
                              encoding="utf-8")
# AUTO-MAS's MaaEnd script as the API read it on the machine 10-17 10:2x (Game section).
BEFORE = {"ControllerType": "Win32-Front", "LaunchMode": "Launcher", "Path": game_exe, "LauncherPath": "",
          "WaitTime": 60, "SetResolution": False, "CloseOnFinish": True, "RestoreDisplayType": "Window",
          "RestoreResolution": "Off", "RestoreResolutionWidth": 1920, "RestoreResolutionHeight": 1080,
          "IfAutoUpdate": False}
mas = {"data": {"59da8762": {"Info": {"Name": "MaaEnd", "Path": str(FX)}, "Game": dict(BEFORE)}}}
writes, refuse = [], set()


def fake_mas(path, body=None, timeout=20):
    if path == "/api/scripts/get":
        return json.loads(json.dumps(mas))
    if path == "/api/scripts/update":
        (k, v), = body["data"]["Game"].items()
        if k in refuse:
            return {"code": 500, "message": "正在运行, 无法更新配置项"}
        writes.append((k, v))
        mas["data"][body["scriptId"]]["Game"][k] = v
        return {"code": 200}
    raise AssertionError(path)


cfg = types.SimpleNamespace(state_dir=root / "state", automas_dir=automas, maaend_dir=None)
game = mas["data"]["59da8762"]["Game"]
saved_mas = commands._mas
commands._mas = fake_mas
try:
    ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
    check("all done", ok, True)
    check("LaunchMode MaaEnd and the four settings as run on 10-17",
          {k: game[k] for k in ("LaunchMode", "SetResolution", "CloseOnFinish", "RestoreDisplayType", "RestoreResolution")},
          {"LaunchMode": "MaaEnd", "SetResolution": True, "CloseOnFinish": True,
           "RestoreDisplayType": "Fullscreen", "RestoreResolution": "1920x1080"})
    check("written: the three that differed, then the mode last",
          writes, [("SetResolution", True), ("RestoreDisplayType", "Fullscreen"), ("RestoreResolution", "1920x1080"),
                   ("LaunchMode", "MaaEnd")])
    check("nothing else touched (path, launcher path, wait, the custom size)",
          {k: game[k] for k in BEFORE if k not in ("LaunchMode", "SetResolution", "RestoreDisplayType", "RestoreResolution")},
          {k: v for k, v in BEFORE.items() if k not in ("LaunchMode", "SetResolution", "RestoreDisplayType",
                                                         "RestoreResolution")})
    n = len(writes)
    check("run again: all done, nothing said", setup.install(cfg, code_root=Path("C:/relay/versions/7")), (True, []))
    check("run again: nothing written", len(writes), n)

    (lroot / "1.6.0" / "Games.exe").unlink()
    ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
    check("「MaaEnd 启动」 and AUTO-MAS's own launcher rule finds nothing: fine (MaaEnd finds it itself)",
          (ok, [x for x in notes if texts.ENDFIELD_NO_LAUNCHER in x]), (True, []))
    (lroot / "1.6.0" / "Games.exe").write_text("", encoding="utf-8")

    print("\n[MaaEnd cannot start it windowed: back to 「启动器启动」, and the group hears it]")
    mas["data"]["59da8762"]["Info"]["Path"] = str(BETA2)
    ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
    check("not done", ok, False)
    check("LaunchMode back to Launcher", game["LaunchMode"], "Launcher")
    check("said why, naming what an unticked box then does", any(NO_MAAEND_START in x for x in notes))
    check("that sentence is plain", texts.plain(NO_MAAEND_START), [])
    import boot_stages

    class _Log:
        def __init__(self):
            self.warned = []

        def info(self, *a, **k):
            pass

        def warning(self, msg, *a, **k):
            self.warned.append(msg % a)

        def exception(self, msg, *a, **k):
            self.warned.append("EXC " + msg % a)
    lg = _Log()
    boot_stages._endfield_launch(cfg, lg, "开机")
    check("at boot: one WARNING (errwatch pushes it to the group) naming it",
          (len(lg.warned), NO_MAAEND_START in (lg.warned or [""])[0]), (1, True))
    check("…said again at the next boot while it lasts (not an INFO note)",
          (boot_stages._endfield_launch(cfg, lg, "开机"), len(lg.warned)), (None, 2))

    print("\n[a window setting AUTO-MAS refuses: the mode is not switched]")
    mas["data"]["59da8762"]["Info"]["Path"] = str(FX)
    game.update(BEFORE)
    refuse.add("RestoreResolution")
    ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
    check("not done, still 「启动器启动」", (ok, game["LaunchMode"]), (False, "Launcher"))
    check("…and said", any(NO_MAAEND_START in x for x in notes))
    refuse.clear()

    print("\n[restore (by hand): back to 「启动器启动」 and the values before]")
    setup.install(cfg, code_root=Path("C:/relay/versions/7"))
    okr, _ = setup.restore(cfg)
    check("restore", (okr, {k: game[k] for k in ("LaunchMode", "SetResolution", "CloseOnFinish",
                                                 "RestoreDisplayType", "RestoreResolution")}),
          (True, {"LaunchMode": "Launcher", "SetResolution": False, "CloseOnFinish": True,
                  "RestoreDisplayType": "Window", "RestoreResolution": "Off"}))
finally:
    commands._mas = saved_mas

# ─────────────────────────── efstart: the relay's own start ───────────────────────────

print("\n[efstart: the relay's own start runs MaaEnd's pretask on the desktop and checks its exit code]")
has_flow = hasattr(ef, "start_via_maaend")
check("efstart starts the game through MaaEnd's pretask", has_flow)
check("nothing in efstart ticks the DirectX 11 box any more",
      [n for n in ("_ensure_d3d11", "_toggle_d3d11", "D3D11_BOX_FROM_START", "box_brightness") if hasattr(ef, n)], [])


class Desk:
    """The machine as the helper sees it: processes, the pretask's exit code, the display."""

    def __init__(self, *, game=False, code=0):
        self.game, self.code, self.events = game, code, []

    def running(self, names):
        return {n for n in names if n == "Endfield.exe" and self.game}

    def kill(self, *names):
        self.events.append(("kill",) + names)
        self.game = self.game and "Endfield.exe" not in names
        return True

    def run(self, argv, cwd, timeout):
        self.events.append(("run", argv, cwd, timeout))
        if self.code == 0:
            self.game = True
        return self.code, "launcher pipeline failed" if self.code else ""

    def wake(self):
        self.events.append(("wake",))
        return True

    def probes(self):
        return ef.Probes(running=self.running, kill=self.kill, run=self.run, wake=self.wake, sleep=lambda s: None)


if has_flow:
    md = maaend_copy()
    w = Desk()
    r = ef.start_via_maaend(md, w.probes())
    check("exit 0: OK", r.code, ef.OK)
    check("woke the display, then ran go-service.exe --pretask LaunchGamePC <the 10-17 options> "
          "from the MaaEnd folder with AUTO-MAS's 240 s",
          w.events, [("wake",), ("run", [str(md / "agent" / "go-service.exe"), "--pretask", "LaunchGamePC", MACHINE_ARGS],
                                str(md), 240)])
    w = Desk(game=True)
    r = ef.start_via_maaend(md, w.probes())
    check("game already open: closed first (the pretask would skip the window), then started",
          ([e[0] for e in w.events], r.code), (["kill", "wake", "run"], ef.OK))
    w = Desk(code=1)
    r = ef.start_via_maaend(md, w.probes())
    check("exit 1: failed, and counted as a start that ran (window settings written)",
          (r.code, r.code in ef.RAN), (ef.PRETASK, True))
    w = Desk(code=None)
    check("past 240 s: timed out, also counted as ran", (lambda x: (x.code, x.code in ef.RAN))(
        ef.start_via_maaend(md, w.probes())), (ef.TIMED_OUT, True))
    w = Desk()
    r = ef.start_via_maaend(maaend_copy(lambda d: (d / "agent" / "go-service.exe").unlink()), w.probes())
    check("no go-service.exe: refused before anything runs", (r.code, r.code in ef.RAN, w.events), (ef.SETUP, False, []))
    r = ef.start_via_maaend(BETA2, Desk().probes())
    check("a MaaEnd without the pretask: refused", r.code, ef.SETUP)
    check("every reason is plain", [texts.plain(x) for x in (r.reason,) if texts.plain(x)], [])
    check("no MaaEnd folder given: refused", ef.run_once(tmpdir(), "relay", "", probes=Desk().probes()).code, ef.SETUP)

    sd = tmpdir()
    (sd / "efstart").mkdir()
    (sd / "efstart" / ef.TRAMPOLINE).write_text("# trampoline\n", encoding="utf-8")
    calls = []

    def fake_spawn(exe, cwd, args):
        calls.append(args)
        Path(args[args.index("--result") + 1]).write_text(json.dumps({"code": 0, "reason": "ok"}), encoding="utf-8")
        return True
    r = ef.run_on_desktop(sd, fake_spawn, md, pythonw=Path("pythonw.exe"), sleep=lambda s: None)
    check("run_on_desktop hands the helper the MaaEnd folder",
          (r.code, calls[0][calls[0].index("--maaend") + 1] if calls and "--maaend" in calls[0] else None),
          (ef.OK, str(md)))

# ─────────────────────────── collect_retry ───────────────────────────

print("\n[collect_retry: the game starts the same way, and fullscreen is written back before MaaEnd closes]")
CLOSE_LINE = ('[2026-10-17 11:33:31.200][INF][Px1][Tx2][Utils/EventDispatcher.hpp][L65][MaaNS::EventDispatcher::notify] '
              '!!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.{}] '
              '[details={{"entry":"CloseGamePC","hash":"","task_id":200000002,"uuid":""}}]')


class MXU:
    def __init__(self, md, close="Succeeded"):
        self.md, self.close, self.calls = md, close, []
        (md / "debug").mkdir(exist_ok=True)
        (md / "debug" / "maafw.log").write_text("", encoding="utf-8")

    def __call__(self, path, body=None, timeout=30):
        self.calls.append((path, body))
        if path == "/maa/state":
            return {"instances": {"automas": {"connected": True, "resource_loaded": True, "is_running": False}}}
        if path.startswith("/maa/windows"):
            return [{"handle": 4242}]
        if path.endswith("/tasks/start") and body["tasks"][0]["entry"] == "CloseGamePC" and self.close:
            with (self.md / "debug" / "maafw.log").open("a", encoding="utf-8") as fh:
                fh.write(CLOSE_LINE.format(self.close) + "\n")
        return {}

    def entries(self):
        return [(p.rsplit("/", 1)[-1], b["tasks"][0]["entry"] if p.endswith("/tasks/start") else None)
                for p, b in self.calls if p.endswith(("/tasks/start", "/agent/stop"))]


def retry(md, mxu, started=None):
    seen, got = [], {}
    saved = (cr._running, cr._wait, cr.api, cr.mxu_port, cr.time, ef.run_on_desktop)
    cr._running = lambda names: {"MaaEnd.exe"}
    cr._wait = lambda pred, seconds, step=3.0: bool(pred())
    cr.api = mxu
    cr.mxu_port = lambda d: 12701
    cr.time = types.SimpleNamespace(sleep=lambda s: None, strftime=lambda f: "00:00:00", time=lambda: 0)
    ef.run_on_desktop = lambda state_dir, spawn, *a, **k: (seen.append((state_dir,) + a) or
                                                           (started or ef.Result(ef.OK, "开了")))
    try:
        verdict, note = cr._bring_up_and_run(md, ["AutoCollectRoute15"], {}, spawn=lambda *a: None, timeout=10,
                                             evidence=got, state_dir="SD")
    finally:
        cr._running, cr._wait, cr.api, cr.mxu_port, cr.time, ef.run_on_desktop = saved
    return seen, note, got


md = maaend_copy()
mxu = MXU(md)
seen, note, got = retry(md, mxu)
check("the helper is given the MaaEnd folder", seen, [("SD", md)])
check("gathering, then CloseGamePC, then the agents stop",
      mxu.entries(), [("start", "AutoCollectSchedule"), ("start", "CloseGamePC"), ("stop", None)])
close_body = next((b for p, b in mxu.calls if p.endswith("/tasks/start") and b["tasks"][0]["entry"] == "CloseGamePC"), None)
check("CloseGamePC carries the fullscreen 1920x1080 override",
      json.loads(close_body["tasks"][0]["pipeline_override"]) if close_body else None, RESTORE)
check("…with MaaEnd's agents (CloseGameAction lives in go-service)",
      [a["child_exec"] for a in (close_body or {}).get("agent_configs", [])], ["agent/go-service", "agent/cpp-algo"])
check("succeeded: nothing to add", (note, got.get("not_restored")), ("", None))

md = maaend_copy()
seen, note, got = retry(md, MXU(md, close="Failed"))
check("CloseGamePC failed: the note says fullscreen was not written back", "没改回全屏" in note)
check("…and maybe_run hears of it", bool(got.get("not_restored")))
check("…in plain words", texts.plain(note), [])

md = maaend_copy()
seen, note, got = retry(md, MXU(md), ef.Result(PRETASK, "MaaEnd 开游戏没成功（退出码 1）"))
check("the pretask ran and failed: no window, nothing to close it with; said", ("没改回全屏" in note, bool(got)),
      (True, True))
md = maaend_copy()
seen, note, got = retry(md, MXU(md), ef.Result(ef.SETUP, "开游戏的助手没装好"))
check("the pretask never ran: nothing about fullscreen", ("没改回全屏" in note, got), (False, {}))
md = maaend_copy(lambda d: edit_json(d / "interface.json", lambda j: j["import"].pop()))
seen, note, got = retry(md, MXU(md))
check("a MaaEnd that cannot write fullscreen back: the game is not started at all", (seen, bool(note)), ([], True))

print("\n[maybe_run: every route walked but fullscreen not back → a WARNING (the group); otherwise none]")


class _Warn(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def outcome(not_restored):
    from datetime import datetime as _dt  # noqa: PLC0415
    sd = tmpdir()
    zh = json.loads((HERE / "fixtures" / "collect-retry-2026-09-11" / "zh_cn.json").read_text(encoding="utf-8"))
    sent = []
    eng = types.SimpleNamespace(
        cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(sd), history_dir=str(sd), automas_dir=None),
        state=types.SimpleNamespace(read_ledger=lambda d: [], mark_incomplete=lambda *a: True),
        notifier=types.SimpleNamespace(send=lambda t, b, **kw: sent.append((t, kw.get("alert", False))) or []),
        _scripts_running=lambda: False)

    def fake_retry(*a, evidence=None, **k):
        if not_restored and evidence is not None:
            evidence["not_restored"] = "MaaEnd 关游戏时没能把显示设置写回"
        return {"AutoCollectRoute15": True}, ""
    saved = (cr.latest_gathering_run, cr.run_retry, cr._locale, cr.restore_master)
    cr.latest_gathering_run = lambda entries, hist, labels: ({"run_id": "r1"}, ["AutoCollectRoute15"])
    cr.run_retry, cr._locale, cr.restore_master = fake_retry, (lambda d: zh), (lambda cfg: "")
    h = _Warn()
    cr.log.addHandler(h)
    try:
        cr.maybe_run(eng, now=_dt(2026, 10, 17, 21, 0).astimezone(), day="2026-10-17")
    finally:
        cr.log.removeHandler(h)
        cr.latest_gathering_run, cr.run_retry, cr._locale, cr.restore_master = saved
    return [x for x in h.lines if "全屏" in x], sent


warned, sent = outcome(True)
check("not back: one WARNING", len(warned), 1)
check("the routes still count as walked (daily report only)", sent, [(texts.COLLECT_RETRY_OK, False)])
check("back: no WARNING", outcome(False)[0], [])

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
