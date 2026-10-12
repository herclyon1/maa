"""Launcher screens the update flows must not misread (audit 2026-10-06).

When the game screen is unknown or unreadable, update_endfield must not claim
"up to date", must not click blindly and must not kill a launcher that is
downloading. (update_wuwa went on 2026-10-12: AUTO-MAS updates Wuthering Waves,
item 10b.) Fake desktop only: no Windows, no processes.

Where the screens come from:
* The words 正在下载 / 安装中 (Hypergryph) were read off the machine on 2026-09-02
  and are quoted in gameupdate_games.py; no relay.log line carries a whole launcher screen, so those
  screens are built from those words.
* relay-log-1006/relay.log lines 5356-5397 (09-02 15:48-15:50): the desktop agent
  timed out (「桌面助手 … 超时没有结果」) and both launchers were reported as
  「启动器画面没读到按钮」 with an empty or garbage dump - the "unreadable" case.
* relay-log-1006/relay.log lines 10430-10437 (09-04 12:38:55-12:40:17): a real
  Arknights prewarm, three bottom taps and then 「开始唤醒」. Replayed below.
* The focus-missing screen is built from AGENT_PS's fields (the agent logs
  「focus: 没有 $f 的窗口」 and, since this audit, sets focus_missing); no real line.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.gameupdate import gameupdate_games as gug
from ark_relay.core.desktop import Line, Screen

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

print("[1 终末地：启动器窗口没找到，前台别的窗口有「开始游戏」→ 不算无需更新，报问题，不点不杀]")
reset(); probs = []
d = FakeDesk([("missing", ["开始游戏"])])
out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
check("返回空", out, "")
check("记了问题，点名窗口", any("没找到启动器窗口" in p and "Games" in p for p in probs))
check("问题带截图", any("shot-x.png" in p for p in probs))
check("什么都没点", d.clicks, [])
check("没杀 Games.exe", [e for e in events if e[0] == "kill" and "Games.exe" in e], [])

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

print("\n[桌面助手自己失败（relay.log 5356-5397：「桌面助手 … 超时没有结果」）→ 未知，不当成「没按钮」]")
reset(); probs = []
d = FakeDesk([("error", "超时")])
out = gug.update_endfield(d, *EF, problems=probs, sleep=fake_sleep)
check("终末地：返回空", out, "")
check("终末地：问题说读屏失败和原因", any("读屏失败" in p and "超时" in p for p in probs), True)
check("终末地：没说成「没读到按钮」", any("没读到按钮" in p for p in probs), False)
check("终末地：什么都没点", d.clicks, [])
check("终末地：没杀 Games.exe", [e for e in events if e[0] == "kill" and "Games.exe" in e], [])
print("\nPASS" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
