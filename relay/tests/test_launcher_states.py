"""Launcher screens the update flows must not misread (audit 2026-10-06).

When the game screen is unknown or unreadable, update_endfield / update_wuwa /
ak_prewarm must not claim "up to date", must not click blindly and must not kill
a launcher that is downloading. Fake desktop only: no Windows, no processes.

Where the screens come from:
* The words 正在下载 / 安装中 (Hypergryph) and 下载中 / 解压中 / 进入中 / 进入游戏
  (Kuro) were read off the machine on 2026-09-02 / 2026-09-30 and are quoted in
  gameupdate_games.py; no relay.log line carries a whole launcher screen, so those
  screens are built from those words.
* relay-log-1006/relay.log lines 5356-5397 (09-02 15:48-15:50): the desktop agent
  timed out (「桌面助手 … 超时没有结果」) and both launchers were reported as
  「启动器画面没读到按钮」 with an empty or garbage dump - the "unreadable" case.
* relay-log-1006/relay.log lines 10430-10437 (09-04 12:38:55-12:40:17): a real
  Arknights prewarm, three bottom taps and then 「开始唤醒」. Replayed below.
* The focus-missing screen is built from AGENT_PS's fields (the agent logs
  「focus: 没有 $f 的窗口」 and, since this audit, sets focus_missing); no real line.
"""
import logging
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import gameupdate_games as gug
import ark_relay.preupdate_okww as pok
from ark_relay.desktop import Line, Screen

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


# ── a clock that only moves when the code sleeps, so every budget runs out ──
clock = {"t": 0.0}
slept = []


def fake_sleep(s):
    slept.append(s)
    clock["t"] += s


gug.time = types.SimpleNamespace(monotonic=lambda: clock["t"], sleep=fake_sleep)

# ── what was killed / closed / spawned, in order with the clicks ──
events = []
gug.kill = lambda *names: events.append(("kill",) + names)
gug._spawn = lambda exe, cwd=None: events.append(("spawn", exe.name)) or True
pok._okww_quiesce = lambda **k: None
pok._okww_close = lambda **k: events.append(("close",)) or []
_real_alive = gug._alive
gug._alive = lambda exe: (lambda: True)


class FakeDesk:
    """Replays screens in order (the last one repeats). A screen is a list of
    OCR lines, or ("missing", [lines]) for a read whose focus window was not found
    - its lines then belong to whatever window was in front."""

    def __init__(self, screens, click_ok=True):
        self.screens = list(screens)
        self.click_ok = click_ok
        self.clicks = []

    def read(self, focus=None, settle_ms=0):
        spec = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        missing = isinstance(spec, tuple) and spec[0] == "missing"
        if isinstance(spec, tuple) and spec[0] == "error":
            # The desktop agent failed (Desktop.read: ok false -> Screen.error)
            events.append(("read", focus, ("<error>",)))
            return Screen([], Path("shot-x.png"), error=spec[1])
        texts = spec[1] if missing else spec
        scr = Screen([Line(t, 100, 100 + 30 * i, 80, 20) for i, t in enumerate(texts)], Path("shot-x.png"))
        scr.focus_missing = missing
        events.append(("read", focus, tuple(texts)))
        return scr

    def _ok(self, what):
        ok = self.click_ok(what) if callable(self.click_ok) else self.click_ok
        self.clicks.append(what)
        events.append(("click", what, ok))
        return ok

    def click_text(self, text, focus=None):
        return self._ok(text)

    def click(self, x, y, focus=None):
        return self._ok((x, y))


def reset():
    events.clear()
    slept.clear()
    clock["t"] = 0.0


def before_first_click(kind):
    """Events of `kind` that happened before anything was clicked."""
    out = []
    for e in events:
        if e[0] == "click":
            break
        if e[0] == kind:
            out.append(e)
    return out


EF = (Path("Endfield.exe"), Path("Launcher.exe"))
WW = Path(r"D:\Wuthering Waves\launcher.exe")

print("[1 终末地：启动器窗口没找到，前台别的窗口有「开始游戏」→ 不算无需更新，报问题，不点不杀]")
reset(); probs = []
d = FakeDesk([("missing", ["开始游戏"])])
out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
check("返回空", out, "")
check("记了问题，点名窗口", any("没找到启动器窗口" in p and "Games" in p for p in probs))
check("问题带截图", any("shot-x.png" in p for p in probs))
check("什么都没点", d.clicks, [])
check("没杀 Games.exe", [e for e in events if e[0] == "kill" and "Games.exe" in e], [])

print("\n[1 鸣潮：启动器窗口没找到，前台别的窗口有「进入游戏」→ 报问题，不关]")
reset(); probs = []
d = FakeDesk([("missing", ["进入游戏"])])
out = gug.update_wuwa(d, WW, problems=probs, sleep=fake_sleep)
check("返回空", out, "")
check("记了问题，点名窗口", any("没找到启动器窗口" in p and "鸣潮" in p for p in probs))
check("没关启动器", [e for e in events if e[0] == "close"], [])
check("什么都没点", d.clicks, [])

print("\n[2 鸣潮：只有新闻标题「版本更新公告」→ 不当成「更新」按钮去点]")
# No real screen: built from the launcher's news strip (a title containing 更新).
reset(); probs = []
d = FakeDesk([["版本更新公告", "活动"]])
out = gug.update_wuwa(d, WW, problems=probs, sleep=fake_sleep)
check("没点", d.clicks, [])
check("报没读到按钮", any("没读到按钮" in p for p in probs))
print("  （整行就是「更新」的按钮照点）")
reset(); probs = []
d = FakeDesk([["版本更新公告", "更新"], ["下载中"], ["进入游戏"], ["点击连接"]])
out = gug.update_wuwa(d, WW, problems=probs, sleep=fake_sleep)
check("点的是第二行「更新」的中心", d.clicks[0], (140, 140))
check("报了更新", out.startswith("鸣潮 客户端已通过启动器更新"))

print("\n[3 终末地：一打开启动器就在「正在下载」→ 不点不杀，等它装完]")
reset(); probs = []
d = FakeDesk([["鹰角启动器", "正在下载 45%"], ["安装中"], ["开始游戏"], ["点击任意位置继续"]])
out = gug.update_endfield(d, *EF, poll_s=30, problems=probs, sleep=fake_sleep)
check("等到开始游戏前没杀 Games.exe", [e for e in before_first_click("kill") if "Games.exe" in e], [])
check("没点「更新游戏」", "更新游戏" in d.clicks, False)
check("没报没读到按钮", [p for p in probs if "没读到按钮" in p], [])
check("报了更新", out, "终末地 客户端已通过启动器更新")
print("  （认不出的画面照旧报问题带截图）")
reset(); probs = []
d = FakeDesk([["-以％36．。6．78678967", "么"]])   # relay.log 5397's garbage dump
out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
check("返回空", out, "")
check("报没读到按钮带截图", any("没读到按钮" in p and "shot-x.png" in p for p in probs))

print("\n[4 鸣潮：一打开启动器就在「下载中」→ 不关不杀，等它装完]")
reset(); probs = []
d = FakeDesk([["鸣潮", "下载中 3.2GB/12.0GB"], ["解压中"], ["进入游戏"], ["点击连接"]])
out = gug.update_wuwa(d, WW, problems=probs, sleep=fake_sleep)
check("点「进入游戏」之前没关启动器", before_first_click("close"), [])
check("点「进入游戏」之前没 kill", before_first_click("kill"), [])
check("点的是「进入游戏」", d.clicks, ["进入游戏"])
check("报了更新", out.startswith("鸣潮 客户端已通过启动器更新"))
check("没有问题", probs, [])

print("\n[5 终末地：装完了但「开始游戏」没点上 → 不睡 90 秒假装开了，句子里说清]")
reset(); probs = []
d = FakeDesk([["更新游戏"], ["开始游戏"]], click_ok=lambda w: w != "开始游戏")
out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
check("句子说没点上", "没点上" in out, True)
check("没睡那 90 秒", 90 in slept, False)
check("没进游戏那段（没读 Endfield 窗口）", [e for e in events if e[0] == "read" and e[1] == "Endfield"], [])
print("  （「请重启游戏」的「确认」没点上：照样关掉重开，不中断）")
reset(); probs = []
d = FakeDesk([["更新游戏"], ["开始游戏"], ["资源初始化更新完成，请重启游戏", "确认"], ["点击任意位置继续"]],
             click_ok=lambda w: w != "确认")
out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
check("重开了游戏", ("spawn", "Endfield.exe") in events)
check("报了更新", out, "终末地 客户端已通过启动器更新")
print("  （鸣潮：装完「进入游戏」没点上）")
reset(); probs = []
d = FakeDesk([["立即更新"], ["进入游戏"]], click_ok=lambda w: w != "进入游戏")
out = gug.update_wuwa(d, WW, problems=probs, sleep=fake_sleep)
check("句子说没点上", "没点上" in out, True)
check("没睡那 90 秒", 90 in slept, False)
print("  （鸣潮：「立即更新」没点上 → 报问题，不去等下载）")
reset(); probs = []
d = FakeDesk([["立即更新"]], click_ok=False)
out = gug.update_wuwa(d, WW, problems=probs, sleep=fake_sleep)
check("返回空", out, "")
check("报没点上", any("没点上" in p for p in probs))
check("没等下载（只读了一次）", len([e for e in events if e[0] == "read"]), 1)

print("\n[6 终末地：更新后仍「客户端版本已过时」/ 15 分钟没到标题 → 不说已更新]")
reset(); probs = []
d = FakeDesk([["更新游戏"], ["开始游戏"], ["客户端版本已过时"]])
out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
check("返回空", out, "")
check("问题保留", any("客户端已过时" in p for p in probs))
reset(); probs = []
d = FakeDesk([["更新游戏"], ["开始游戏"], ["正在编译着色器"]])
out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
check("超时返回空", out, "")
check("超时问题保留", any("15 分钟" in p for p in probs))

print("\n[7 _alive：tasklist 读不出 = 不知道，不是「进程没了」，并且记一条警告]")


class _Keep(logging.Handler):
    def __init__(self):
        super().__init__(); self.msgs = []

    def emit(self, r):
        self.msgs.append((r.levelname, r.getMessage()))


keep = _Keep()
gug.log.addHandler(keep)
gug.log.setLevel(logging.INFO)   # ak_prewarm says its last screen at INFO
real_run = subprocess.run
try:
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b"")
    keep.msgs.clear()
    check("空输出 → 不知道", _real_alive("Client-Win64-Shipping.exe")(), None)
    check("空输出记了警告", any(lv == "WARNING" for lv, _ in keep.msgs))
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 1, b"ERROR: access denied", b"")
    keep.msgs.clear()
    check("退出码非 0 → 不知道", _real_alive("Client-Win64-Shipping.exe")(), None)
    check("退出码非 0 记了警告", any(lv == "WARNING" for lv, _ in keep.msgs))

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("tasklist", 30)
    subprocess.run = boom
    keep.msgs.clear()
    check("抛异常 → 不知道", _real_alive("Client-Win64-Shipping.exe")(), None)
    check("抛异常记了警告带异常", any(lv == "WARNING" and "timed out" in m for lv, m in keep.msgs))
    listing = b"Image Name   PID\nClient-Win64-Shipping.exe  4242 Console\n"
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, b"")
    check("列表里有 → 在", _real_alive("Client-Win64-Shipping.exe")(), True)
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"Image Name   PID\nexplorer.exe 1\n", b"")
    check("列表里没有 → 没了", _real_alive("Client-Win64-Shipping.exe")(), False)
finally:
    subprocess.run = real_run

print("\n[8 明日方舟预热：只在认不出的画面点几下，弹窗不点，点满就停]")
taps = []


def adb(args, t=120):
    s = " ".join(map(str, args))
    if "input tap" in s:
        taps.append(s)
    return "Physical size: 1600x900" if "wm size" in s else ""


print("  （真实回放 relay.log 10430-10437：点三下后读到「开始唤醒」）")
reset(); taps.clear()
d = FakeDesk([["明日方舟"], ["明日方舟"], ["明日方舟"], ["开始唤醒"]])
how = gug.ak_prewarm(Path("ldconsole.exe"), "emulator-7554", d, run=adb, sleep=fake_sleep)
check("读到开始唤醒", how, "读到「开始唤醒」")
check("点了 3 下", len(taps), 3)
print("  （一直认不出的画面：15 分钟最多点 5 下，最后一屏进警告）")
reset(); taps.clear(); keep.msgs.clear()
d = FakeDesk([["某个没见过的画面"]])
how = gug.ak_prewarm(Path("ldconsole.exe"), "emulator-7554", d, run=adb, sleep=fake_sleep)
check("返回空", how, "")
check("最多点 5 下", len(taps) <= 5, True)
# INFO since 2026-10-09: a WARNING goes to the group as 「中继自己报错了」 (errwatch);
# the failure reaches the group as update_arknights' problem instead.
check("日志带最后一屏和截图", any(lv == "INFO" and "某个没见过的画面" in m and "shot-x.png" in m
                                  for lv, m in keep.msgs), True)
check("不是 WARNING", any(lv == "WARNING" for lv, m in keep.msgs), False)
print("  （有弹窗字样：一下都不点）")
reset(); taps.clear()
d = FakeDesk([["网络连接失败", "重试"]])
how = gug.ak_prewarm(Path("ldconsole.exe"), "emulator-7554", d, run=adb, sleep=fake_sleep)
check("返回空", how, "")
check("一下都没点", taps, [])
print("  （弹窗字在长句里，「点击重试」：也不点）")
reset(); taps.clear()
d = FakeDesk([["网络连接失败，点击重试"]])
how = gug.ak_prewarm(Path("ldconsole.exe"), "emulator-7554", d, run=adb, sleep=fake_sleep)
check("长句里的弹窗字也不点", taps, [])
print("  （窗口没找到：不点）")
reset(); taps.clear()
d = FakeDesk([("missing", ["某个别的窗口"])])
how = gug.ak_prewarm(Path("ldconsole.exe"), "emulator-7554", d, run=adb, sleep=fake_sleep)
check("一下都没点", taps, [])

print("\n[桌面助手自己失败（relay.log 5356-5397：「桌面助手 … 超时没有结果」）→ 未知，不当成「没按钮」]")
reset(); probs = []
d = FakeDesk([("error", "超时")])
out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
check("终末地：返回空", out, "")
check("终末地：问题说读屏失败和原因", any("读屏失败" in p and "超时" in p for p in probs), True)
check("终末地：没说成「没读到按钮」", any("没读到按钮" in p for p in probs), False)
check("终末地：什么都没点", d.clicks, [])
check("终末地：没杀 Games.exe", [e for e in events if e[0] == "kill" and "Games.exe" in e], [])
reset(); probs = []
d = FakeDesk([("error", "超时")])
out = gug.update_wuwa(d, WW, problems=probs, sleep=fake_sleep)
check("鸣潮：返回空", out, "")
check("鸣潮：问题说读屏失败和原因", any("读屏失败" in p and "超时" in p for p in probs), True)
check("鸣潮：没关启动器", [e for e in events if e[0] == "close"], [])
check("鸣潮：什么都没点", d.clicks, [])
reset(); taps.clear()
d = FakeDesk([("error", "超时")])
how = gug.ak_prewarm(Path("ldconsole.exe"), "emulator-7554", d, run=adb, sleep=fake_sleep)
check("明日方舟：读屏失败一下都不点", (how, taps), ("", []))
check("明日方舟：日志带原因", any(lv == "INFO" and "超时" in m and "开始唤醒" in m for lv, m in keep.msgs), True)
print("  （等登录界面时读屏失败：不算到了，最后一屏写原因）")
reset(); keep.msgs.clear()
d = FakeDesk([("error", "超时")])
how = gug.wait_ready(d, "鸣潮", focus="Client-Win64-Shipping", alive=lambda: True,
                     budget_s=60, poll_s=30, sleep=fake_sleep)
check("没到", how, "")
check("最后一屏写读屏失败", any("读屏失败" in m for lv, m in keep.msgs if lv == "WARNING"), True)

print("\n[_alive：tasklist 返回的不是进程结果（别的测试换掉了 subprocess.run）→ 不知道，不崩]")
_orig_run = subprocess.run
try:
    subprocess.run = lambda *a, **k: None
    check("返回 None 不抛", _real_alive("Client-Win64-Shipping.exe")(), None)
finally:
    subprocess.run = _orig_run

print("\nPASS" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
