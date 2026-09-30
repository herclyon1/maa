"""WuWa client update through the Kuro launcher: the ready word, and closing for real.

2026-09-30 16:58, measured on the machine with launcher 3.7: after the update the
button reads 「进入游戏」, not 「开始游戏」, so update_wuwa sat out its 40 minutes with
the update done. The launcher then runs as launcher_main.exe in a version folder
(D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe), which the old full-path match on
…\\Wuthering Waves\\launcher.exe missed. And the timeout note said 「已关掉启动器和游戏」
without looking: taskkill from session 0 does not reach the game under its
anti-cheat (echofarm._kill_on_desktop, 2026-09-09), and its return code was never read.
"""
import json
import subprocess
import sys
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import echofarm
from ark_relay import gameupdate_games as gug
from ark_relay import preupdate_okww as pk
from ark_relay.desktop import Line, Screen

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class FakeDesk:
    def __init__(self, screens):
        self.screens = list(screens)
        self.clicks = []

    def read(self, focus=None, settle_ms=0):
        texts = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        return Screen([Line(t, 100, 100 + 30 * i, 80, 20) for i, t in enumerate(texts)], Path("x.png"))

    def click_text(self, text, focus=None):
        self.clicks.append(text)
        return True

    def click(self, x, y, focus=None):
        self.clicks.append((x, y))
        return True


nosleep = lambda s: None  # noqa: E731
LAUNCHER = PureWindowsPath("D:/Wuthering Waves/launcher.exe")
gug._spawn = lambda exe, cwd=None: True
gug.wait_ready = lambda *a, **k: "读到「点击连接」"
closes = []
left_after = []


def fake_close(sleep=None, launcher_root=None):
    closes.append(launcher_root)
    return list(left_after)


real_close = pk._okww_close
pk._okww_close = fake_close

print("[就绪词：「进入游戏」和「开始游戏」都算，「进入中」不算]")
check("进入游戏", gug._ww_ready(Screen([Line("进入游戏", 0, 0, 10, 10)])), "进入游戏")
check("开始游戏", gug._ww_ready(Screen([Line("开始游戏", 0, 0, 10, 10)])), "开始游戏")
for busy in ("进入中", "检查游戏版本和文件", "下载中", "解压中", "更新游戏"):
    check(f"「{busy}」不是就绪", gug._ww_ready(Screen([Line(busy, 0, 0, 10, 10)])), "")

print("[装完读到「进入游戏」：点它，不再空等 40 分钟（09-30 16:58 实测）]")
d = FakeDesk([["公告", "立即更新"], ["下载中"], ["解压中"], ["进入游戏"], ["进入中"]])
probs = []
closes.clear()
out = gug.update_wuwa(d, LAUNCHER, poll_s=0, problems=probs, sleep=nosleep)
check("报了更新", out, "鸣潮 客户端已通过启动器更新，已到登录界面（读到「点击连接」）")
check("点的是「进入游戏」", d.clicks[1:], ["进入游戏"])
check("没有问题", probs, [])
check("按启动器所在目录关（同一个 wuwa_launcher 来源）", closes, [LAUNCHER.parent])

print("[已是最新：「进入游戏」也算，不点更新]")
d = FakeDesk([["公告", "进入游戏"]])
closes.clear()
check("返回空", gug.update_wuwa(d, LAUNCHER, poll_s=0, problems=[], sleep=nosleep), "")
check("什么都没点", d.clicks, [])
check("关了一次", len(closes), 1)

print("[超时：关掉了才写「已关掉」]")
d = FakeDesk([["公告", "立即更新"], ["下载中"]])
probs = []
gug.update_wuwa(d, LAUNCHER, budget_s=0.2, poll_s=0.05, problems=probs,
                sleep=lambda s: __import__("time").sleep(min(s, 0.05)))
check("写已关掉", len(probs) == 1 and "已关掉启动器和游戏" in probs[0], True)
check("写两种就绪词", "「开始游戏」或「进入游戏」" in probs[0], True)

print("[超时：没关掉就如实说哪几个还在]")
left_after[:] = ["Client-Win64-Shipping.exe", "launcher_main.exe"]
d = FakeDesk([["公告", "立即更新"], ["下载中"]])
probs = []
gug.update_wuwa(d, LAUNCHER, budget_s=0.2, poll_s=0.05, problems=probs,
                sleep=lambda s: __import__("time").sleep(min(s, 0.05)))
check("不写已关掉", any("已关掉" in p for p in probs), False)
check("写没关掉和名字", len(probs) == 1 and "没关掉：Client-Win64-Shipping.exe、launcher_main.exe 还在" in probs[0], True)

print("[更新成功但没关掉：写进通知那句，不当问题（问题会让整轮更新 10 分钟后重来）]")
d = FakeDesk([["公告", "立即更新"], ["进入游戏"]])
probs = []
out = gug.update_wuwa(d, LAUNCHER, poll_s=0, problems=probs, sleep=nosleep)
check("通知末尾说没关掉", out.endswith("；没关掉：Client-Win64-Shipping.exe、launcher_main.exe 还在"), True)
check("问题里没有", probs, [])
left_after.clear()
pk._okww_close = real_close

print("[启动器进程：按启动器目录前缀认 launcher.exe 和 launcher_main.exe]")
root = PureWindowsPath("D:/Wuthering Waves")
check("版本子目录里的 launcher_main.exe", pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe", root), True)
check("入口壳 launcher.exe", pk._is_wuwa_launcher("D:\\Wuthering Waves\\launcher.exe", root), True)
check("斜杠和大小写不影响", pk._is_wuwa_launcher("d:/wuthering waves/2.6.5.0/LAUNCHER_MAIN.EXE", root), True)
check("别的目录同名不算", pk._is_wuwa_launcher("C:\\Other\\launcher_main.exe", root), False)
check("前缀要到目录边界（Wuthering Waves Game 不算）",
      pk._is_wuwa_launcher("D:\\Wuthering Waves Game\\launcher.exe", root), False)
check("同目录别的程序不算", pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\Client.exe", root), False)
check("没有目录时按 \\Wuthering Waves\\ 这一段认 launcher_main.exe",
      pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe"), True)
check("没有目录时游戏本体目录不算", pk._is_wuwa_launcher("D:\\Wuthering Waves Game\\launcher_main.exe"), False)

print("[默认目录：和 update_wuwa 一样从 wuwa_launcher 来]")
real_wl = gug.wuwa_launcher
gug.wuwa_launcher = lambda okww: PureWindowsPath("E:/Kuro/Wuthering Waves/launcher.exe")
check("找到 launcher.exe → 它的目录", pk._launcher_root(None), PureWindowsPath("E:/Kuro/Wuthering Waves"))
gug.wuwa_launcher = lambda okww: PureWindowsPath("E:/Kuro/Game/Wuthering Waves.exe")
check("只找到游戏本体 → 不当目录", pk._launcher_root(None), None)
check("给了目录就用给的", pk._launcher_root(root), root)
gug.wuwa_launcher = real_wl

print("[taskkill 看返回码：失败的不算关掉]")
PROCS = [{"ProcessId": 4242, "ExecutablePath": "D:\\Wuthering Waves\\launcher.exe"},
         {"ProcessId": 4343, "ExecutablePath": "D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe"},
         {"ProcessId": 5151, "ExecutablePath": "C:\\Program Files\\Other\\launcher_main.exe"}]


class R:
    def __init__(self, rc=0, out=b""):
        self.returncode, self.stdout, self.stderr = rc, out, b"ERROR: Access is denied."


calls = []
real_run = subprocess.run


def fake_run(cmd, *a, **k):
    calls.append(list(cmd))
    if any("launcher_main.exe" in str(x) and "CimInstance" in str(x) for x in cmd):
        return R(0, json.dumps(PROCS).encode())
    if cmd[:3] == ["taskkill", "/F", "/PID"]:
        return R(0 if cmd[3] == "4242" else 1)
    return R()


subprocess.run = fake_run
try:
    stopped = pk._stop_wuwa_launcher(root)
finally:
    subprocess.run = real_run
kills = [c for c in calls if c[:1] == ["taskkill"]]
check("两个都试了（按 PID）", [c[3] for c in kills], ["4242", "4343"])
check("只记返回 0 的那个", stopped, [4242])
check("别处的不碰", any("5151" in c for c in kills), False)
check("列进程一次查两个名字", sum(1 for c in calls if any("Name='launcher_main.exe'" in str(x) for x in c)), 1)

print("[_okww_close：关完复查，剩下的从桌面会话再关一次，再说实话]")
bat = tmpdir() / "ark-okww-stop.bat"
echofarm.STOP_BAT = str(bat)          # never the repo cwd
alive = {"game": ["Client-Win64-Shipping.exe"], "procs": [PROCS[1]]}
real_alive = echofarm.game_alive
echofarm.game_alive = lambda: list(alive["game"])
calls.clear()


def run2(cmd, *a, **k):
    calls.append(list(cmd))
    if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd):
        return R(0, json.dumps(alive["procs"]).encode())
    if cmd[:1] == ["taskkill"]:
        return R(1)                   # session 0 cannot reach it
    if cmd[:2] == ["schtasks", "/run"]:
        alive["game"], alive["procs"] = [], []    # the desktop door worked
    return R()


subprocess.run = run2
try:
    left = pk._okww_close(sleep=nosleep, launcher_root=root)
finally:
    subprocess.run = real_run
check("桌面那边关掉了 → []", left, [])
text = bat.read_text(encoding="utf-8")
check("bat 里按 PID 关启动器", "taskkill /F /PID 4343" in text, True)
check("bat 里照旧按名字关游戏", 'taskkill /F /IM "Client-Win64-Shipping.exe"' in text, True)
check("走了计划任务", any(c[:2] == ["schtasks", "/run"] for c in calls), True)

alive.update(game=["Client-Win64-Shipping.exe"], procs=[PROCS[1]])


def run3(cmd, *a, **k):
    calls.append(list(cmd))
    if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd):
        return R(0, json.dumps(alive["procs"]).encode())
    return R(1) if cmd[:1] == ["taskkill"] else R()


subprocess.run = run3
try:
    left = pk._okww_close(sleep=nosleep, launcher_root=root)
finally:
    subprocess.run = real_run
check("都没关掉 → 点名", left, ["Client-Win64-Shipping.exe", "launcher_main.exe"])

alive.update(game=[], procs=[])
subprocess.run = lambda cmd, *a, **k: (_ for _ in ()).throw(OSError("no pwsh")) \
    if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd) else R()
try:
    left, pids = pk._okww_left(root)
finally:
    subprocess.run = real_run
check("启动器列表读不到 → 说读不到，不当没了", left, ["鸣潮启动器（查不到它还开没开着）"])
check("…也没有 PID 可关", pids, [])
echofarm.game_alive = real_alive

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
