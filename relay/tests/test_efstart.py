"""Endfield is started through the official launcher, never as Endfield.exe (2026-10-15).

Client 1.6.3 refuses a start whose parent is not the Hypergryph launcher: on 2026-10-15
15:14 AUTO-MAS started Endfield.exe directly, the game showed 「游戏启动失败」
「请通过官方启动器打开游戏」 and every MaaEnd task failed. Measured by the parent session.

Since 10-17 the relay's own start (efstart, for the gathering retry) runs MaaEnd's launcher
pretask, windowed; test_maaend_windowed_start_1017.py pins that flow. Here: the helper's lock
and running.json, the watchdog's view of it, run_on_desktop, and efstart_setup's convergence of
AUTO-MAS (its launcher discovery rule, the relay's old preAction, Game.Path and the wait).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _tmp import tmpdir

from ark_relay.features.gameupdate import efstart as ef
from ark_relay.features.gameupdate import efstart_setup as setup

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


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
import shutil  # noqa: E402
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

from ark_relay.features.run import maaend_watchdog  # noqa: E402

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
from ark_relay.features.makeup import collect_retry as cr  # noqa: E402
import types  # noqa: E402

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

print("\n[10-16：开游戏交还给调度程序自己的官方启动器方式（AUTO-MAS v5.7.0-beta.4 / #1394）]")
# The machine on 10-16 (AUTO-MAS API read, mxu-MaaEnd.json, state/efstart/target.json): Game.Path
# was the relay's .cmd, LaunchMode Launcher, LauncherPath empty, WaitTime 180; the master's
# helper entry had kept the replaced entry's id jw75pty. AUTO-MAS's pre-run check found no
# launcher from the .cmd: 09:34:05 「未找到终末地官方启动器」, the 早班 MaaEnd never ran.
from ark_relay.core import texts  # noqa: E402
from ark_relay.features.phone import commands  # noqa: E402

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
relay_dir = Path(__file__).resolve().parents[1]
import boot_stages  # noqa: E402
seen = []
saved = (setup.install, boot_stages.selfcheck if hasattr(boot_stages, "selfcheck") else None)
from ark_relay.features.selfcheck import selfcheck  # noqa: E402
saved_rc = selfcheck.report_contract
setup.install = lambda c, **k: (seen.append(c) or (True, []))
selfcheck.report_contract = lambda *a, **k: None


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
print("\nPASS" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
