"""Endfield's start through MaaEnd's launcher pretask, windowed, and back to fullscreen.

One part per former file, each run on its own (tests/_parts.py): test_efstart.py, test_maaend_windowed_start.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_main():
    """Endfield is started through the official launcher, never as Endfield.exe (2026-10-15).

Client 1.6.3 refuses a start whose parent is not the Hypergryph launcher: on 2026-10-15
15:14 AUTO-MAS started Endfield.exe directly, the game showed 「游戏启动失败」
「请通过官方启动器打开游戏」 and every MaaEnd task failed. Measured by the parent session.

Since 10-17 the relay's own start (efstart, for the gathering retry) runs MaaEnd's launcher
pretask, windowed; test_maaend_windowed_start.py pins that flow. Here: the helper's lock
and running.json, the watchdog's view of it, run_on_desktop, and efstart_setup's convergence of
AUTO-MAS (its launcher discovery rule, the relay's old preAction, Game.Path and the wait).

    Formerly test_efstart.py.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.gameupdate import efstart as ef
    from ark_relay.features.gameupdate import efstart_setup as setup


    FX = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.33.0-launch"
    BETA2 = Path(__file__).resolve().parent / "gamesim" / "upstream" / "maaend-v2.33.0-beta.2"


    class Probe:
        """A start with nothing to do: the game is not running and the pretask exits 0."""

        def __init__(self):
            self.ran = []

        def probes(self):
            return ef.Probes(running=lambda names: set(), kill=lambda *n: True,
                             run=lambda argv, cwd, timeout: (self.ran.append(argv), (0, ""))[1],
                             wake=lambda: True, sleep=lambda s: None)


    print("\n[一次开游戏：running.json 只在开的时候有；没说 MaaEnd 在哪 → 2]")
    home = tmpdir() / "efstart"
    home.mkdir()
    md = tmpdir() / "maaend"
    import shutil
    shutil.copytree(FX, md)
    (md / "agent").mkdir()
    (md / "agent" / "go-service.exe").write_bytes(b"")
    w = Probe()
    seen = []


    class _Lock:
        def __init__(self, got):
            self.got = got

        def __call__(self, wait_s):
            return self

        def __enter__(self):
            seen.append((home / ef.RUNNING).exists())
            return self.got

        def __exit__(self, *a):
            return False


    r = ef.run_once(home, "test", "", probes=w.probes(), single=_Lock(True))
    check("没说 MaaEnd 在哪就是 2", r.code, ef.SETUP)
    r = ef.run_once(home, "test", md, probes=w.probes(), single=_Lock(True))
    check("说了就开（预任务退出 0 → 0）", (r.code, len(w.ran)), (ef.OK, 1))
    check("结束后 running.json 没了", (home / ef.RUNNING).exists(), False)
    r = ef.run_once(home, "test", md, probes=w.probes(), single=_Lock(False))
    check("锁一直被别人占着 → 9", (r.code, len(w.ran)), (ef.BUSY, 1))

    print("\n[看门狗：开游戏助手在等（running.json 的 PID 是 pythonw）→ 认得出]")
    sd = tmpdir()
    (sd / "efstart").mkdir()
    (sd / "efstart" / ef.RUNNING).write_text(json.dumps({"pid": 4242}), encoding="utf-8")
    check("PID 在、是 pythonw", ef.helper_alive(sd, [("pythonw.exe", 4242), ("MaaEnd.exe", 1)]), True)
    check("PID 不在", ef.helper_alive(sd, [("MaaEnd.exe", 1)]), False)
    check("PID 被别的程序用了", ef.helper_alive(sd, [("notepad.exe", 4242)]), False)

    from ark_relay.features.run import maaend_watchdog

    RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
    procs = [("MaaEnd.exe", 100), ("pythonw.exe", 4242)]          # no go-service yet: tasks not started
    clock = {"t": 1000.0}
    killed = []
    dbg = sd / "debug"
    dbg.mkdir()
    (dbg / "go-service.stderr.log").write_text("", encoding="utf-8")


    class _N:
        def send(self, *a, **k):
            return []


    dog = maaend_watchdog.Watchdog(_N(), dbg, clock=lambda: clock["t"], snapshot=lambda: RUNNING,
                                   processes=lambda: procs, kill=lambda pid, img: killed.append(pid) or (True, ""),
                                   plugin_paths=lambda: {}, active=True, state_dir=sd)
    for _ in range(20):                       # 20 minutes waiting on the helper, no plugin, no log line
        clock["t"] += 60
        dog.tick(0, "")
    check("助手在等的 20 分钟里不杀 MaaEnd", killed, [])
    (sd / "efstart" / ef.RUNNING).unlink()
    for _ in range(20):
        clock["t"] += 60
        dog.tick(0, "")
    check("助手结束后照旧判（插件一直没起来 → 杀）", killed, [100])

    print("\n[收集补跑：游戏由开游戏助手开，不再直接起 Endfield.exe]")
    from ark_relay.features.makeup import collect_retry as cr
    import types

    md = tmpdir() / "maaend"
    (md / "debug").mkdir(parents=True)
    started = []
    saved = (cr._running, cr._wait, cr.api, cr.mxu_port, cr.time, ef.run_on_desktop)
    cr._running = lambda names: {"MaaEnd.exe"}
    cr._wait = lambda pred, seconds, step=3.0: pred() if seconds != 60 else True
    cr.api = lambda path, body=None, timeout=30: {"instances": {}} if "state" in path else []
    cr.mxu_port = lambda d: 12701
    cr.time = types.SimpleNamespace(sleep=lambda s: None, strftime=lambda f: "00:00:00", time=lambda: 0)
    ef.run_on_desktop = lambda state_dir, spawn, *a, **k: started.append(state_dir) or ef.Result(ef.SETUP, "开游戏的助手没装好")
    spawned = []
    try:
        verdict, note = cr._bring_up_and_run(FX, ["AutoCollectRoute15"], {}, spawn=lambda exe, cwd, args: spawned.append(exe),
                                             timeout=10, evidence=None, state_dir=sd)
    finally:
        cr._running, cr._wait, cr.api, cr.mxu_port, cr.time, ef.run_on_desktop = saved
    check("经开游戏助手开", started, [sd])
    check("没直接起任何程序", spawned, [])
    check("助手没开起来就不补，说原因", note, "游戏没经官方启动器开起来：开游戏的助手没装好")

    print("\n[run_on_desktop：用中继的 pythonw 起助手入口，等它的结果文件]")
    sd2 = tmpdir()
    (sd2 / "efstart").mkdir()
    (sd2 / "efstart" / ef.TRAMPOLINE).write_text("# trampoline\n", encoding="utf-8")
    calls = []


    def fake_spawn(exe, cwd, args):
        calls.append((Path(exe).name, args[0], args[1:3]))
        res = Path(args[args.index("--result") + 1])
        res.write_text(json.dumps({"code": 0, "reason": "终末地已经开着，没再开"}), encoding="utf-8")
        return True


    r = ef.run_on_desktop(sd2, fake_spawn, md, pythonw=Path("pythonw.exe"), sleep=lambda s: None)
    check("起的是 pythonw 跑入口", calls, [("pythonw.exe", str(sd2 / "efstart" / ef.TRAMPOLINE), ("--caller", "relay"))])
    check("拿到助手的结果", (r.code, r.reason), (ef.OK, "终末地已经开着，没再开"))
    check("结果文件用完删掉", list((sd2 / "efstart").glob("result-*.json")), [])

    print("\n[run_on_desktop：中继要停了就不再等助手（审计 11-08 A-23：这一等在主循环里，停机会被拖到强退）]")
    polls = []
    r = ef.run_on_desktop(sd2, lambda exe, cwd, args: True, md, pythonw=Path("pythonw.exe"),
                          sleep=lambda s_: polls.append(s_), stopping=lambda: len(polls) >= 2)
    check("停了：不判结论，回 STOPPED", (r.code, r.code in ef.RAN, len(polls)), (ef.STOPPED, False, 2))
    check("STOPPED 不和助手的退出码撞号", ef.STOPPED not in (ef.OK, ef.SETUP, ef.PRETASK, ef.LAUNCHER, ef.TIMED_OUT,
                                                          ef.UNREADABLE, ef.BUSY), True)

    print("\n[_single：互斥锁用完，句柄关掉（PyHANDLE 自己的 Close）]")


    class _H:
        closed = False

        def Close(self):  # noqa: N802 - pywin32's name
            self.closed = True


    h = _H()
    fake_ev = types.SimpleNamespace(CreateMutex=lambda *a: h, WaitForSingleObject=lambda hh, ms: 0, WAIT_OBJECT_0=0,
                                    WAIT_ABANDONED=0x80, ReleaseMutex=lambda hh: released.append(hh))
    released = []
    saved_mod = sys.modules.get("win32event")
    sys.modules["win32event"] = fake_ev
    try:
        with ef._single(1) as got:
            pass
        check("拿到锁、放了锁、关了句柄", (got, released == [h], h.closed), (True, True, True))
        h2 = _H()
        fake_ev.CreateMutex = lambda *a: h2
        fake_ev.WaitForSingleObject = lambda hh, ms: 0x102          # WAIT_TIMEOUT
        with ef._single(1) as got:
            pass
        check("没等到锁：不放锁，照样关句柄", (got, h2.closed), (False, True))
    finally:
        if saved_mod is None:
            sys.modules.pop("win32event", None)
        else:
            sys.modules["win32event"] = saved_mod

    print("\n[10-16：开游戏交还给调度程序自己的官方启动器方式（AUTO-MAS v5.7.0-beta.4 / #1394）]")
    # The machine on 10-16 (AUTO-MAS API read, mxu-MaaEnd.json, state/efstart/target.json): Game.Path
    # was the relay's .cmd, LaunchMode Launcher, LauncherPath empty, WaitTime 180; the master's
    # helper entry had kept the replaced entry's id jw75pty. AUTO-MAS's pre-run check found no
    # launcher from the .cmd: 09:34:05 「未找到终末地官方启动器」, the 早班 MaaEnd never ran.
    from ark_relay.core import texts
    from ark_relay.features.phone import commands

    pyw = "C:\\Program Files\\ArkRelay\\runtime\\python\\pythonw.exe"
    orig = {"id": "jw75pty", "customName": "▶️ 启动 Endfield.exe", "enabled": True,
            "program": "D:\\endfield\\Hypergryph Launcher\\games\\Endfield Game\\Endfield.exe", "args": "",
            "waitForExit": False, "skipIfRunning": True, "useCmd": False}
    mas_entry = {"id": "automas-endfield", "program": "D:\\endfield\\Endfield.exe", "waitForExit": False}
    ours = {"id": "jw75pty", "customName": "▶️ 经官方启动器启动终末地（中继）", "enabled": True, "program": pyw,
            "args": '"C:\\ProgramData\\ark-relay\\state\\efstart\\efstart.py" --caller maaend',
            "waitForExit": True, "skipIfRunning": False, "useCmd": False}
    doc = {"instances": [{"name": "automas", "preActions": [dict(mas_entry), dict(ours)]}]}
    changed, removed = setup.remove_preactions(doc)
    check("母本里中继那条（id 是 jw75pty，不是 ark-efstart）删掉了", (changed, [a["id"] for a in removed]), (True, ["jw75pty"]))
    check("调度程序自己那条原样留着", doc["instances"][0]["preActions"], [mas_entry])
    check("再删一次不变", setup.remove_preactions(doc), (False, []))
    check("没有往母本里加任何东西的入口了", hasattr(setup, "rewrite_preactions"), False)

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

    print("\n[调度程序找启动器的规矩，照它 endfield_launcher.py 的写法]")
    check("游戏本体：往上找到 Launcher.exe 加带 Games.exe 的版本文件夹",
          Path(str(setup.launcher_for(game_exe)).replace("\\", "/")), lroot / "Launcher.exe")
    home = root / "state" / "efstart"
    home.mkdir(parents=True)
    cmd = home / "start-endfield.cmd"
    cmd.write_text("@echo off\r\n", encoding="utf-8")
    check("10-16 那样指着批处理：找不到（调度程序就是这样拒绝的）", setup.launcher_for(str(cmd)), None)
    check("指定 Games.exe：换成上两层的 Launcher.exe",
          Path(str(setup.launcher_for(str(cmd), str(lroot / "1.6.0" / "Games.exe"))).replace("\\", "/")),
          lroot / "Launcher.exe")
    check("指定别的程序：不算", setup.launcher_for(game_exe, str(game_dir / "Endfield.exe")), None)
    (lroot / "1.6.0" / "Games.exe").unlink()
    check("没有版本文件夹：不认（Launcher.exe 这个名字太常见）", setup.launcher_for(game_exe), None)
    (lroot / "1.6.0" / "Games.exe").write_text("", encoding="utf-8")

    print("\n[install：路径改回游戏本体、由 MaaEnd 开窗口（10-17）、等待改回、母本里的助手删掉；再跑不写；restore 不放回直接开]")
    automas = root / "automas"
    cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
    cfgdir.mkdir(parents=True)
    master = cfgdir / "mxu-MaaEnd.json"
    master.write_text(json.dumps({"instances": [{"name": "automas", "tasks": [],
                                                  "preActions": [dict(mas_entry), dict(ours)]}]},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    (home / ef.TARGET).write_text(json.dumps({
        "game": game_exe, "launcher": str(lroot / "Launcher.exe"), "cmd": str(cmd),
        "trampoline": str(home / ef.TRAMPOLINE),
        "original": {"preactions": [dict(orig, program=game_exe)], "game_path": game_exe, "wait_time": 60}}),
        encoding="utf-8")
    mas = {"data": {"s1": {"Info": {"Name": "MaaEnd", "Path": str(FX)},
                           "Game": {"Path": str(cmd), "LaunchMode": "Launcher", "LauncherPath": "",
                                    "Arguments": "", "WaitTime": 180, "ControllerType": "Win32-Front",
                                    "SetResolution": True, "CloseOnFinish": True, "RestoreDisplayType": "Fullscreen",
                                    "RestoreResolution": "1920x1080"}}}}
    writes = []


    def fake_mas(path, body=None, timeout=20):
        if path == "/api/scripts/get":
            return json.loads(json.dumps(mas))
        if path == "/api/scripts/update":
            writes.append(body)
            for k, v in body["data"].items():
                mas["data"][body["scriptId"]][k].update(v)
            return {"code": 200}
        raise AssertionError(path)


    cfg = types.SimpleNamespace(state_dir=root / "state", automas_dir=automas, maaend_dir=None)
    saved_mas = commands._mas
    commands._mas = fake_mas
    try:
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        g = mas["data"]["s1"]["Game"]
        check("全部对上", ok, True)
        check("调度程序的终末地路径改回游戏本体（不再是批处理）", g["Path"], game_exe)
        check("启动方式是由 MaaEnd 开（窗口设置本来就对）", g["LaunchMode"], "MaaEnd")
        check("启动器路径留空，让调度程序自己找", g["LauncherPath"], "")
        check("等待改回原来的 60 秒（不再提到 180）", g["WaitTime"], 60)
        check("写的只有路径、启动方式和等待（窗口设置本来就对，没写）",
              sorted(k for w in writes for k in w["data"]["Game"]), ["LaunchMode", "Path", "WaitTime"])
        back = json.loads(master.read_text(encoding="utf-8"))["instances"][0]["preActions"]
        check("母本读回来：只剩调度程序自己那条，没有助手，也没放回直接开 Endfield.exe", back, [mas_entry])
        check("批处理删了", cmd.exists(), False)
        check("开游戏助手的入口还在（中继自己的补采集要用）",
              repr(str(Path("C:/relay/versions/7"))) in (home / ef.TRAMPOLINE).read_text(encoding="utf-8"), True)
        tgt = json.loads((home / ef.TARGET).read_text(encoding="utf-8"))
        check("记录里不再有批处理", "cmd" in tgt, False)
        check("原来的值一个没丢", tgt["original"]["game_path"], game_exe)
        n_writes, master_text = len(writes), master.read_text(encoding="utf-8")
        ok2, notes2 = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("再跑一次：照样全好、什么都不说", (ok2, notes2), (True, []))
        check("再跑一次：调度程序没再写", len(writes), n_writes)
        check("再跑一次：母本没再写", master.read_text(encoding="utf-8"), master_text)

        g["LaunchMode"] = "Client"
        ok3, _ = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("启动方式被改成直接开：改回由 MaaEnd 开", (ok3, g["LaunchMode"]), (True, "MaaEnd"))

        # 「启动器启动」 (MaaEnd without its launcher pretask: the fallback) needs AUTO-MAS's own rule to find it.
        mas["data"]["s1"]["Info"]["Path"] = str(BETA2)
        (lroot / "1.6.0" / "Games.exe").unlink()
        ok4, notes4 = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("经官方启动器开、调度程序找不到启动器：不算好，说清楚它会拒绝开终末地",
              (ok4, g["LaunchMode"], any(texts.ENDFIELD_NO_LAUNCHER in n for n in notes4)), (False, "Launcher", True))
        check("这句是人话", texts.plain(texts.ENDFIELD_NO_LAUNCHER), [])
        (lroot / "1.6.0" / "Games.exe").write_text("", encoding="utf-8")
        mas["data"]["s1"]["Info"]["Path"] = str(FX)

        master.write_text(json.dumps({"instances": [{"name": "automas", "preActions": [dict(mas_entry), dict(ours)]}]}),
                          encoding="utf-8")
        g["WaitTime"] = 180
        okr, _ = setup.restore(cfg)
        back = json.loads(master.read_text(encoding="utf-8"))["instances"][0]["preActions"]
        check("restore：母本里没有直接开 Endfield.exe 的那条，也没有助手", back, [mas_entry])
        check("restore：路径还是游戏本体（不放回批处理）、等待改回", (okr, g["Path"], g["WaitTime"]), (True, game_exe, 60))
    finally:
        commands._mas = saved_mas

    print("\n[开机和调度程序升级后都核对一遍]")
    import boot_stages
    seen = []
    saved = (setup.install, boot_stages.selfcheck if hasattr(boot_stages, "selfcheck") else None)
    from ark_relay.features.selfcheck import selfcheck
    saved_rc = selfcheck.report_contract
    setup.install = lambda c, **k: (seen.append(c) or (True, []))
    selfcheck.report_contract = lambda *a, **k: None
    # The backend answers here (boot_stages.await_backend asks it before install()).
    saved_up = commands.mas_up
    commands.mas_up = lambda: True


    class _L:
        def __init__(self):
            self.warned = []

        def info(self, *a, **k):
            pass

        def warning(self, msg, *a, **k):
            self.warned.append(msg % a)

        def exception(self, *a, **k):
            self.warned.append(a[0])


    try:
        boot_stages._contract_after_update("CFG", None, _L(), "v5.7.0-beta.4")
        check("调度程序升级后（开机那次核对是对着旧版的）再核对一遍", seen, ["CFG"])
        setup.install = lambda c, **k: (False, ["一句"])
        lg = _L()
        boot_stages._contract_after_update("CFG", None, lg, "v5.7.0-beta.4")
        check("没对上：一条 WARNING（进群）", len(lg.warned), 1)
    finally:
        setup.install, selfcheck.report_contract = saved[0], saved_rc
        commands.mas_up = saved_up
    print("\nPASS" if not fails else f"\nFAILED: {fails}")


def _part_maaend_windowed_start():  # noqa: C901 - the whole body of the file this part was
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

    Formerly test_maaend_windowed_start.py.
    """
    import json
    import logging
    import shutil
    import types

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE.parent))

    from ark_relay.core import texts
    from ark_relay.features.gameupdate import efstart as ef
    from ark_relay.features.gameupdate import efstart_setup as setup
    from ark_relay.features.makeup import collect_retry as cr
    from ark_relay.features.phone import commands
    try:
        from ark_relay.features.gameupdate import maaend_launch as ml
    except ImportError:                 # the code before this change
        ml = None

    # Names this change brings in, looked up so the file runs (and fails check by check) on the code before it.
    NO_MAAEND_START = getattr(texts, "ENDFIELD_NO_MAAEND_START", "\0 not defined")
    PRETASK = getattr(ef, "PRETASK", -5)


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
        # AUTO-MAS sends only LaunchGamePCGameSetting (AutoProxy.py:2199-2207 @fdfb0fd); every other
        # option is LaunchGamePC.json's default case, so a default that is not the window case starts
        # the game that way even though the case still exists.
        for opt, other in (("LaunchGamePCDisplayType", "Fullscreen"), ("LaunchGamePCResolution", "1920x1080"),
                           ("LaunchGamePCRegion", "Global"), ("LaunchGamePCLauncherPath", "Manual")):
            reasons[f"{opt} default {other}"] = ml.check(maaend_copy(lambda d, o=opt, v=other: edit_json(
                d / "tasks" / "pretasks" / "LaunchGamePC.json",
                lambda j: j["option"][o].update(default_case=v))), "Win32-Front")
        reasons["(the relay's own start sends the values itself: still planned with DisplayType default Fullscreen)"] = (
            "" if ml.launch_plan(maaend_copy(lambda d: edit_json(
                d / "tasks" / "pretasks" / "LaunchGamePC.json",
                lambda j: j["option"]["LaunchGamePCDisplayType"].update(default_case="Fullscreen"))))[0] else "refused")
        planned = reasons.pop("(the relay's own start sends the values itself: still planned with DisplayType default Fullscreen)")
        check("the relay's own start sends every value itself: a changed default does not stop it", planned, "")
        for what, why in reasons.items():
            check(f"{what}: refused", bool(why), True)
        check("every reason is plain Chinese", {w: texts.plain(r) for w, r in reasons.items() if texts.plain(r)}, {})

        print("\n[a stored __MXU_PRETASK__LaunchGamePC entry in AUTO-MAS's MaaEnd config overrides the defaults]")
        stored = getattr(ml, "stored_override", None)
        check("maaend_launch.stored_override exists", callable(stored))
        if callable(stored):
            def doc(*ovs):
                return {"instances": [{"id": f"i{n}", "tasks": [{"taskName": "__MXU_PRETASK__LaunchGamePC",
                                                                "optionValues": ov}]} for n, ov in enumerate(ovs)]}
            check("no entry (AUTO-MAS adds an empty one): fine", stored({"instances": [{"tasks": []}]}), "")
            check("only the switch AUTO-MAS writes itself: fine",
                  stored(doc({"LaunchGamePCGameSetting": {"type": "switch", "value": False}})), "")
            check("the same window values stored: fine", stored(doc({
                "LaunchGamePCDisplayType": {"type": "select", "caseName": "Window"},
                "LaunchGamePCResolution": {"type": "select", "caseName": "1280x720"},
                "LaunchGamePCRegion": {"type": "select", "caseName": "CN"},
                "LaunchGamePCLauncherPath": {"type": "select", "caseName": "Auto"}})), "")
            overrides = {
                "DisplayType Fullscreen stored": stored(doc({"LaunchGamePCDisplayType": {"type": "select", "caseName": "Fullscreen"}})),
                "Resolution 1920x1080 stored as value": stored(doc({"LaunchGamePCResolution": {"type": "select", "value": "1920x1080"}})),
                "Region Global in a second instance": stored(doc({}, {"LaunchGamePCRegion": {"type": "select", "caseName": "Global"}})),
                "LauncherPath Manual stored": stored(doc({"LaunchGamePCLauncherPath": {"type": "select", "caseName": "Manual"}})),
                "an entry AUTO-MAS cannot read": stored(doc({"LaunchGamePCDisplayType": "Window"})),
                "no config to read": stored(None),
            }
            for what, why in overrides.items():
                check(f"{what}: refused", bool(why), True)
            check("every reason is plain Chinese", {w: texts.plain(r) for w, r in overrides.items() if texts.plain(r)}, {})

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
        if path == "/api/queue/get":    # commands.mas_up: the backend answers (boot_stages.await_backend)
            return {"code": 200, "data": {}}
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

        print("\n[MaaEnd's default is not the window: AUTO-MAS would start it fullscreen, so 「启动器启动」 stays]")
        game.update(BEFORE)
        lg.warned.clear()
        mas["data"]["59da8762"]["Info"]["Path"] = str(maaend_copy(lambda d: edit_json(
            d / "tasks" / "pretasks" / "LaunchGamePC.json",
            lambda j: j["option"]["LaunchGamePCDisplayType"].update(default_case="Fullscreen"))))
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("DisplayType default Fullscreen: not done, still 「启动器启动」", (ok, game["LaunchMode"]), (False, "Launcher"))
        check("…and said", any(NO_MAAEND_START in x for x in notes))
        boot_stages._endfield_launch(cfg, lg, "开机")
        check("…as a WARNING at boot", (len(lg.warned), NO_MAAEND_START in (lg.warned or [""])[0]), (1, True))

        print("\n[AUTO-MAS's MaaEnd config stores a fullscreen pretask value: 「启动器启动」 stays]")
        mas["data"]["59da8762"]["Info"]["Path"] = str(FX)
        mfile = cfgdir / "mxu-MaaEnd.json"
        plain_master = mfile.read_text(encoding="utf-8")

        def stored_master(ov):
            mfile.write_text(json.dumps({"instances": [{"name": "automas", "preActions": [], "tasks": [
                {"taskName": "__MXU_PRETASK__LaunchGamePC", "enabled": False, "optionValues": ov}]}]}), encoding="utf-8")
        stored_master({"LaunchGamePCDisplayType": {"type": "select", "caseName": "Fullscreen"}})
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("stored DisplayType Fullscreen: not done, still 「启动器启动」", (ok, game["LaunchMode"]), (False, "Launcher"))
        check("…and said", any(NO_MAAEND_START in x for x in notes))
        stored_master({"LaunchGamePCDisplayType": {"type": "select", "caseName": "Window"},
                       "LaunchGamePCGameSetting": {"type": "switch", "value": False}})
        ok, notes = setup.install(cfg, code_root=Path("C:/relay/versions/7"))
        check("stored Window (the same as the default): 「MaaEnd 启动」", (ok, game["LaunchMode"]), (True, "MaaEnd"))
        mfile.write_text(plain_master, encoding="utf-8")

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
    # The gathering's agents stop before CloseGamePC starts its own: MXU does not stop them, and
    # beside them the new go-service could not connect (10-22 21:56:40, ledger #111).
    check("gathering, the gathering's agents stop, CloseGamePC, then its agents stop",
          mxu.entries(), [("start", "AutoCollectSchedule"), ("stop", None), ("start", "CloseGamePC"), ("stop", None)])
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
        from datetime import datetime as _dt
        sd = tmpdir()
        zh = json.loads((HERE / "fixtures" / "collect-retry-2026-09-11" / "zh_cn.json").read_text(encoding="utf-8"))
        sent = []
        eng = types.SimpleNamespace(
            cfg=types.SimpleNamespace(state_dir=sd, maaend_dir=str(sd), history_dir=str(sd), automas_dir=None),
            state=types.SimpleNamespace(read_ledger=lambda d: [], mark_incomplete=lambda *a: True,
                                        clear_incomplete_items=lambda *a: True),
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


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_maaend_windowed_start]))
