"""Endfield is started through the official launcher, never as Endfield.exe (2026-10-15).

Client 1.6.3 refuses a start whose parent is not the Hypergryph launcher: on 2026-10-15
15:14 AUTO-MAS started Endfield.exe directly, the game showed 「游戏启动失败」
「请通过官方启动器打开游戏」 and every MaaEnd task failed. At 15:33 a game started from
the launcher without 「DirectX 11 启动」 ticked reached the title, and MaaEnd failed with
「当前环境识别异常，请使用 D3D11 启动游戏…」. Both measured by the parent session.

Fake desktop, fake processes, fake clock: no Windows. The screens are built from the
words the parent session read off the launcher and the game that day (开始游戏, the
DirectX option under it, 游戏协议条款提示 / 同意并继续, 点击任意位置继续) and the
refusal dialog's two lines; the login screen's words are the module's guess (LOGIN_WORDS).
"""
import json
import sys
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _tmp import tmpdir

from ark_relay.core.desktop import Line, Screen
from ark_relay.features.gameupdate import efstart as ef
from ark_relay.features.gameupdate import efstart_setup as setup

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


START_XY = (1407, 796)            # middle of 「开始游戏」 on the 1920x1080 desktop (10-15 15:36)
BOX_XY = (START_XY[0] + ef.D3D11_BOX_FROM_START[0], START_XY[1] + ef.D3D11_BOX_FROM_START[1])
LAUNCHER = ["鹰角启动器", "开始游戏", "DirectX11启动（游戏异常时使用）"]
REFUSAL = ["游戏启动失败", "请通过官方启动器打开游戏"]
LOADING = ["正在编译着色器"]
AGREEMENT = ["游戏协议条款提示", "同意并继续"]
TITLE = ["点击任意位置继续"]
LOGIN = ["手机号", "获取验证码", "登录"]


class World:
    """The machine: which processes run, which screens the launcher and the game show,
    and whether the DirectX 11 box is ticked. A click on 「开始游戏」 starts the game."""

    def __init__(self, *, game=False, launcher=False, game_screens=(TITLE,), ticked=True,
                 launcher_screens=(LAUNCHER,)):
        self.game, self.launcher = game, launcher
        self.game_screens = list(game_screens)
        self.launcher_screens = list(launcher_screens)
        self.ticked = ticked
        self.t = 0.0
        self.events = []

    # ---- probes
    def running(self, names):
        have = {"Endfield.exe"} if self.game else set()
        if self.launcher:
            have.add("Games.exe")
        return {n for n in names if n in have}

    def window(self):
        return self.game

    def spawn(self, exe, *a):
        self.events.append(("spawn", Path(exe).name))
        self.launcher = True
        return True

    def kill(self, *names):
        self.events.append(("kill",) + names)
        if "Endfield.exe" in names:
            self.game = False
        return True

    def box(self, shot, x, y, half):
        # A ticked box is filled: brighter. Only the measured spot reads the box.
        return (200.0 if self.ticked else 40.0) if (x, y) == BOX_XY else 90.0

    def sleep(self, s):
        self.t += s

    def clock(self):
        return self.t

    def probes(self, calib=None):
        return ef.Probes(running=self.running, window=self.window, spawn=self.spawn, kill=self.kill,
                         box=self.box, calib=dict(calib or {}), sleep=self.sleep, clock=self.clock)

    # ---- desktop
    def _screen(self, texts):
        lines = []
        for i, t in enumerate(texts):
            if t == "开始游戏":
                lines.append(Line(t, START_XY[0] - 40, START_XY[1] - 12, 80, 24))
            else:
                lines.append(Line(t, 100, 100 + 30 * i, 80, 20))
        return Screen(lines, Path("shot-x.png"))

    def read(self, focus=None, settle_ms=0):
        self.events.append(("read", focus))
        if focus == "Games":
            if not self.launcher:
                return Screen([], Path("shot-x.png"), focus_missing=True)
            q = self.launcher_screens
        else:
            if not self.game:
                return Screen([], Path("shot-x.png"), focus_missing=True)
            q = self.game_screens
        texts = q.pop(0) if len(q) > 1 else q[0]
        return self._screen(texts)

    def click_text(self, text, focus=None):
        self.events.append(("click", text))
        if text == "开始游戏" and self.launcher:
            self.game = True
        return True

    def click(self, x, y, focus=None):
        self.events.append(("click", (x, y)))
        if (x, y) == BOX_XY:
            self.ticked = not self.ticked
        return True

    def clicks(self):
        return [e[1] for e in self.events if e[0] == "click"]


ON = {"on": 200.0, "off": 40.0}
L = Path("Launcher.exe")

print("[游戏窗口已经在、不是拒绝框 → 0，不点、不开启动器]")
w = World(game=True, launcher=True)
r = ef.start_via_launcher(w, L, w.probes(ON))
check("退出码 0", r.code, ef.OK)
check("一下都没点", w.clicks(), [])
check("没启动任何程序", [e for e in w.events if e[0] == "spawn"], [])

print("\n[启动器没开 → 起启动器、确认 DirectX 11 勾着、点开始游戏、等到标题画面 → 0]")
w = World(game_screens=(LOADING, LOADING, TITLE))
r = ef.start_via_launcher(w, L, w.probes(ON))
check("退出码 0", (r.code, r.reason), (ef.OK, "终末地已经由官方启动器开到标题画面"))
check("起的是 Launcher.exe", [e[1] for e in w.events if e[0] == "spawn"], ["Launcher.exe"])
check("勾着就不点勾，只点开始游戏", w.clicks(), ["开始游戏"])
check("从没直接开 Endfield.exe", any(e[0] == "spawn" and e[1] == "Endfield.exe" for e in w.events), False)

print("\n[DirectX 11 没勾（之前记下过两种样子）→ 先点勾再点开始游戏]")
w = World(ticked=False)
r = ef.start_via_launcher(w, L, w.probes(ON))
check("退出码 0", r.code, ef.OK)
check("先点勾、再点开始游戏", w.clicks(), [BOX_XY, "开始游戏"])
check("勾上了", w.ticked, True)

print("\n[第一次：两种样子没记过，原来勾着 → 点掉、记下、再勾上，然后开]")
w = World(ticked=True)
p = w.probes()
r = ef.start_via_launcher(w, L, p)
check("退出码 0", r.code, ef.OK)
check("点了两下勾，再点开始游戏", w.clicks(), [BOX_XY, BOX_XY, "开始游戏"])
check("记下了勾上 / 没勾的亮度", (p.calib["on"], p.calib["off"]), (200.0, 40.0))
check("记下了两张截图和勾的位置", (p.calib["shots"], p.calib["box"]), (["shot-x.png", "shot-x.png"], list(BOX_XY)))
check("最后是勾着的", w.ticked, True)

print("\n[第一次：原来没勾 → 点一下就勾上、记下]")
w = World(ticked=False)
p = w.probes()
r = ef.start_via_launcher(w, L, p)
check("退出码 0", r.code, ef.OK)
check("点一下勾，再点开始游戏", w.clicks(), [BOX_XY, "开始游戏"])
check("勾着", w.ticked, True)

print("\n[启动器上读不到 DirectX 那一项、又不知道勾没勾 → 不瞎点，非 0]")
w = World(launcher_screens=(["鹰角启动器", "开始游戏"],))
r = ef.start_via_launcher(w, L, w.probes())
check("退出码是启动器问题", r.code, ef.LAUNCHER)
check("什么都没点", w.clicks(), [])

print("\n[游戏协议条款提示 → 点同意并继续，再到标题画面 → 0]")
w = World(game_screens=(LOADING, AGREEMENT, TITLE))
r = ef.start_via_launcher(w, L, w.probes(ON))
check("退出码 0", r.code, ef.OK)
check("点了同意并继续", w.clicks(), ["开始游戏", "同意并继续"])

print("\n[手机号登录画面 → 非 0，说要人登录，不乱点]")
w = World(game_screens=(LOADING, LOGIN))
r = ef.start_via_launcher(w, L, w.probes(ON))
check("退出码是登录", r.code, ef.LOGIN)
check("说要人登录", "要人登录" in r.reason)
check("带截图", r.shot, "shot-x.png")
check("只点了开始游戏", w.clicks(), ["开始游戏"])

print("\n[游戏开着但停在「请通过官方启动器打开游戏」→ 关掉，经启动器重开]")
w = World(game=True, game_screens=(REFUSAL, LOADING, TITLE))
w.window = lambda: False
r = ef.start_via_launcher(w, L, w.probes(ON))
check("退出码 0", r.code, ef.OK)
check("先关了游戏", ("kill", "Endfield.exe") in w.events)
check("经启动器开", [e[1] for e in w.events if e[0] == "spawn"], ["Launcher.exe"])
check("点了开始游戏", w.clicks(), ["开始游戏"])

print("\n[经启动器开的游戏还说要官方启动器 → 非 0]")
w = World(game_screens=(REFUSAL,))
r = ef.start_via_launcher(w, L, w.probes(ON))
check("退出码是被拒", r.code, ef.REFUSED)

print("\n[启动器要先更新客户端 → 非 0，不点更新]")
w = World(launcher_screens=(["鹰角启动器", "更新游戏"],))
r = ef.start_via_launcher(w, L, w.probes(ON))
check("退出码是要更新", r.code, ef.UPDATE)
check("什么都没点", w.clicks(), [])

print("\n[一直到不了标题画面 → 超时非 0，带最后一屏的截图]")
w = World(game_screens=(LOADING,))
r = ef.start_via_launcher(w, L, w.probes(ON))
check("退出码是超时", r.code, ef.TIMED_OUT)
check("带截图", r.shot, "shot-x.png")

print("\n[读不到进程列表 → 什么都不动，非 0]")
w = World()
w.running = lambda names: None
r = ef.start_via_launcher(w, L, w.probes(ON))
check("退出码是读不到", r.code, ef.UNREADABLE)
check("什么都没做", [e for e in w.events if e[0] != "read"], [])

print("\n[勾的亮度从截图里量：填满的框比空框亮；截图读不了 → 不知道]")
from PIL import Image, ImageDraw  # noqa: E402

png = tmpdir() / "launcher.png"
im = Image.new("RGB", (1920, 1080), (30, 30, 30))
d = ImageDraw.Draw(im)
d.rectangle((BOX_XY[0] - 8, BOX_XY[1] - 8, BOX_XY[0] + 8, BOX_XY[1] + 8), outline=(220, 220, 220))
im.save(png)
empty = ef.box_brightness(str(png), *BOX_XY, ef.D3D11_BOX_HALF)
d.rectangle((BOX_XY[0] - 8, BOX_XY[1] - 8, BOX_XY[0] + 8, BOX_XY[1] + 8), fill=(250, 200, 40))
im.save(png)
full = ef.box_brightness(str(png), *BOX_XY, ef.D3D11_BOX_HALF)
check("填满的框比空框亮出一个门槛以上", full - empty >= ef.D3D11_MARGIN, True)
check("截图不在 → None", ef.box_brightness(str(png) + ".gone", *BOX_XY, 7), None)

print("\n[一次开游戏：running.json 只在开的时候有；没写启动器位置 → 2]")
home = tmpdir() / "efstart"
home.mkdir()
w = World(game=True, launcher=True)
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


r = ef.run_once(home, "test", desk=w, probes=w.probes(ON), single=_Lock(True))
check("没写 target.json 就是 2", r.code, ef.SETUP)
(home / ef.TARGET).write_text(json.dumps({"launcher": "Launcher.exe"}), encoding="utf-8")
r = ef.run_once(home, "test", desk=w, probes=w.probes(ON), single=_Lock(True))
check("写了就开（游戏已在 → 0）", r.code, ef.OK)
check("结束后 running.json 没了", (home / ef.RUNNING).exists(), False)
r = ef.run_once(home, "test", desk=w, probes=w.probes(ON), single=_Lock(False))
check("锁一直被别人占着 → 9", r.code, ef.BUSY)

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
ef.run_on_desktop = lambda state_dir, spawn, **k: started.append(state_dir) or ef.Result(ef.LOGIN, "游戏停在手机号登录画面")
spawned = []
try:
    verdict, note = cr._bring_up_and_run(md, ["AutoCollectRoute15"], {}, spawn=lambda exe, cwd, args: spawned.append(exe),
                                         timeout=10, evidence=None, state_dir=sd)
finally:
    cr._running, cr._wait, cr.api, cr.mxu_port, cr.time, ef.run_on_desktop = saved
check("经开游戏助手开", started, [sd])
check("没直接起任何程序", spawned, [])
check("助手没开起来就不补，说原因", note, "游戏没经官方启动器开起来：游戏停在手机号登录画面")

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


r = ef.run_on_desktop(sd2, fake_spawn, pythonw=Path("pythonw.exe"), sleep=lambda s: None)
check("起的是 pythonw 跑入口", calls, [("pythonw.exe", str(sd2 / "efstart" / ef.TRAMPOLINE), ("--caller", "relay"))])
check("拿到助手的结果", (r.code, r.reason), (ef.OK, "终末地已经开着，没再开"))
check("结果文件用完删掉", list((sd2 / "efstart").glob("result-*.json")), [])

print("\n[母本前置程序改写：直接开 Endfield.exe 的那条换成助手，等它退出、不按路径跳过；再跑一次不变]")
pyw = Path("C:/Program Files/ArkRelay/runtime/python/pythonw.exe")
tramp = Path("C:/ProgramData/ark-relay/state/efstart/efstart.py")
orig = {"id": "jw75pty", "customName": "▶️ 启动 Endfield.exe", "enabled": True,
        "program": "D:\\endfield\\Hypergryph Launcher\\games\\Endfield Game\\Endfield.exe", "args": "",
        "waitForExit": False, "skipIfRunning": True, "useCmd": False}
mas_entry = {"id": "automas-endfield", "program": "C:\\x\\start-endfield.cmd", "waitForExit": False}
doc = {"instances": [{"name": "automas", "preActions": [dict(mas_entry), dict(orig)]}]}
changed, replaced = setup.rewrite_preactions(doc, pyw, tramp)
acts = doc["instances"][0]["preActions"]
check("改了", changed, True)
check("记下了原来那条", replaced, [orig])
check("AUTO-MAS 自己那条原样", acts[0], mas_entry)
check("保留原 id", acts[1]["id"], "jw75pty")
check("程序是中继的 pythonw", acts[1]["program"], str(pyw))
check("参数带引号的入口路径", acts[1]["args"], f'"{tramp}" --caller maaend')
check("等它退出", acts[1]["waitForExit"], True)
check("不按路径跳过（中继自己的 pythonw 一直在跑）", acts[1]["skipIfRunning"], False)
check("MXU 认的字段一个不少、没有多的", sorted(acts[1]), sorted(orig))
check("再改一次不变", setup.rewrite_preactions(doc, pyw, tramp), (False, []))
doc2 = {"instances": [{"name": "a"}]}
setup.rewrite_preactions(doc2, pyw, tramp)
check("没有那一条就加上", [a["id"] for a in doc2["instances"][0]["preActions"]], [setup.OUR_PREACTION_ID])

print("\n[install：母本和调度程序都改好、读回核对；再跑一次什么都不写；restore 改回原样]")
from ark_relay.features.phone import commands  # noqa: E402

root = tmpdir()
game_dir = root / "endfield" / "Hypergryph Launcher" / "games" / "Endfield Game"
game_dir.mkdir(parents=True)
(game_dir / "Endfield.exe").write_text("", encoding="utf-8")
(root / "endfield" / "Hypergryph Launcher" / "Launcher.exe").write_text("", encoding="utf-8")
game_exe = str(game_dir / "Endfield.exe")
automas = root / "automas"
cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
cfgdir.mkdir(parents=True)
master = cfgdir / "mxu-MaaEnd.json"
master.write_text(json.dumps({"instances": [{"name": "automas", "tasks": [],
                                              "preActions": [dict(orig, program=game_exe)]}]},
                             ensure_ascii=False, indent=2), encoding="utf-8")
mas = {"data": {"s1": {"Info": {"Name": "MaaEnd"}, "Game": {"Path": game_exe, "Arguments": "", "WaitTime": 60}}}}
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
# The launcher path is built as a Windows path (backslashes) from the game's.
setup._is_file = lambda p: Path(str(p).replace("\\", "/")).is_file()
saved_mas = commands._mas
commands._mas = fake_mas
try:
    ok, notes = setup.install(cfg, pythonw=Path("C:/py/pythonw.exe"), code_root=Path("C:/relay/versions/7"))
    home = root / "state" / "efstart"
    cmd = home / setup.CMD
    check("全部改好", ok, True)
    check("调度程序的终末地路径指向批处理", mas["data"]["s1"]["Game"]["Path"], str(cmd))
    check("启动后等待提到下限", mas["data"]["s1"]["Game"]["WaitTime"], setup.WAIT_FLOOR_S)
    back = json.loads(master.read_text(encoding="utf-8"))["instances"][0]["preActions"]
    check("母本读回来是助手那条", (back[0]["program"], back[0]["waitForExit"], back[0]["skipIfRunning"]),
          (str(Path("C:/py/pythonw.exe")), True, False))
    tgt = json.loads((home / ef.TARGET).read_text(encoding="utf-8"))
    check("记下了游戏和启动器", (tgt["game"], PureWindowsPath(tgt["launcher"]).name), (game_exe, "Launcher.exe"))
    check("记下了原来的路径、等待、前置程序",
          (tgt["original"]["game_path"], tgt["original"]["wait_time"], tgt["original"]["preactions"][0]["id"]),
          (game_exe, 60, "jw75pty"))
    check("批处理用中继的 pythonw 跑入口", f'"{Path("C:/py/pythonw.exe")}" "{home / ef.TRAMPOLINE}" --caller automas'
          in cmd.read_text(encoding="utf-8"), True)
    check("入口指向当前代码目录", repr(str(Path("C:/relay/versions/7"))) in (home / ef.TRAMPOLINE).read_text(encoding="utf-8"),
          True)
    n_writes, master_text = len(writes), master.read_text(encoding="utf-8")
    ok2, notes2 = setup.install(cfg, pythonw=Path("C:/py/pythonw.exe"), code_root=Path("C:/relay/versions/7"))
    check("再跑一次：照样全好", ok2, True)
    check("再跑一次：调度程序没再写", len(writes), n_writes)
    check("再跑一次：母本没再写", master.read_text(encoding="utf-8"), master_text)
    check("再跑一次：原来的值没被盖成新值", json.loads((home / ef.TARGET).read_text(encoding="utf-8"))["original"]["game_path"],
          game_exe)
    okr, _ = setup.restore(cfg)
    check("改回：调度程序", (okr, mas["data"]["s1"]["Game"]["Path"], mas["data"]["s1"]["Game"]["WaitTime"]),
          (True, game_exe, 60))
    back = json.loads(master.read_text(encoding="utf-8"))["instances"][0]["preActions"]
    check("改回：母本前置程序", [a["program"] for a in back], [game_exe])
finally:
    commands._mas = saved_mas

print("\nPASS" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
