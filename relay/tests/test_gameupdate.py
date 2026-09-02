"""大版本更新自动化：决策逻辑用假桌面/假命令跑一遍，不碰网络不碰机器。"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import gameupdate as gu  # noqa: E402
from ark_relay.desktop import Desktop, Line, Screen  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

class FakeDesk:
    """按顺序回放屏幕；记录点了什么。"""
    def __init__(self, screens):
        self.screens = list(screens); self.clicks = []
    def _scr(self):
        texts = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        return Screen([Line(t, 100, 100 + 30 * i, 80, 20) for i, t in enumerate(texts)], Path("x.png"))
    def read(self, focus=None, settle_ms=0):
        return self._scr()
    def click_text(self, text, focus=None):
        self.clicks.append(text); return True
    def click(self, x, y, focus=None):
        self.clicks.append((x, y)); return True

spawned = []
gu._spawn = lambda exe, cwd=None: spawned.append(exe.name) or True
gu.kill = lambda *names: None
nosleep = lambda s: None

print("[终末地：已是「开始游戏」就什么都不做]")
d = FakeDesk([["登录", "开始游戏"]])
out = gu.update_endfield(d, Path("Endfield.exe"), Path("Launcher.exe"), sleep=nosleep)
check("不更新", out, ""); check("没点任何东西", d.clicks, [])

print("[终末地：更新→装完→拉游戏→重启→标题画面]")
d = FakeDesk([["登录", "更新游戏"], ["正在下载"], ["安装中"], ["开始游戏"],
              ["资源初始化更新完成，请重启游戏", "确认"], ["正在编译着色器"], ["点击任意位置继续"]])
probs = []
out = gu.update_endfield(d, Path("Endfield.exe"), Path("Launcher.exe"), poll_s=0, problems=probs, sleep=nosleep)
check("报了更新", out, "终末地 客户端已通过启动器更新")
check("点击顺序", d.clicks, ["更新游戏", "开始游戏", "确认"])
check("重启拉了游戏", "Endfield.exe" in spawned, True)
check("没有问题", probs, [])

print("[终末地：读不到按钮要报问题]")
d = FakeDesk([["登录", "公告"]]); probs = []
out = gu.update_endfield(d, Path("Endfield.exe"), Path("Launcher.exe"), problems=probs, sleep=nosleep)
check("空", out, ""); check("问题里说没读到", any("没读到按钮" in x for x in probs), True)

print("[鸣潮：读到「更新」就点，等到「开始游戏」]")
import ark_relay.preupdate as pu
pu._okww_quiesce = lambda: None
d = FakeDesk([["公告", "立即更新"], ["下载中"], ["开始游戏"]]); probs = []
out = gu.update_wuwa(d, Path("Wuthering Waves.exe"), poll_s=0, problems=probs, sleep=nosleep)
check("报了更新", out, "鸣潮 客户端已通过启动器更新")
check("点的是按钮中心", d.clicks, [(140, 140)])

print("[明日方舟：版本记录、比对、装包]")
ST = Path(tempfile.mkdtemp())
calls = []
state = {"ver": "2.7.61"}
def run(args):
    calls.append(args)
    if "adb" in args:
        return f"versionName={state['ver']}\n" if state.get("up") else ""
    if "launch" in args: state["up"] = True
    if "installapp" in args: state["ver"] = "2.8.01"
    if "quit" in args: state["up"] = False
    return ""
fetch = lambda: {"clientVersion": "2.7.61", "resVersion": "x"}
out = gu.update_arknights(ST, Path("ldconsole.exe"), 1000, fetch=fetch, run=run, sleep=nosleep, downloader=lambda *a, **k: True)
check("首次：只记录不更新", out, "")
check("记录了已装版本", gu.recorded_ak_version(ST), "2.7.61")
check("首次读完退出了模拟器", any("quit" in c for c in calls), True)
calls.clear()
out = gu.update_arknights(ST, Path("ldconsole.exe"), 1000, fetch=fetch, run=run, sleep=nosleep, downloader=lambda *a, **k: True)
check("同版本：不动", out, ""); check("同版本不起模拟器", calls, [])
fetch2 = lambda: {"clientVersion": "2.8.01"}
dl = []
def downloader(url, dest, timeout=0):
    dl.append(dest.name); dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(b"apk"); return True
out = gu.update_arknights(ST, Path("ldconsole.exe"), 1000, fetch=fetch2, run=run, sleep=nosleep, downloader=downloader)
check("新版本：下载→装→核对", out, "明日方舟 已更新：2.7.61 → 2.8.01（APK 已装进雷电）")
check("下的是新版包", dl, ["arknights-2.8.01.apk"])
check("装完记录更新", gu.recorded_ak_version(ST), "2.8.01")
check("装完退出模拟器", any("quit" in c for c in calls), True)
check("装完删了包", (ST / "apk" / "arknights-2.8.01.apk").exists(), False)

print("[每次开机只跑一遍]")
from datetime import datetime
check("没记录→跑", gu.should_run(ST, datetime.now(), boot_id="b1"), True)
gu.mark_run(ST, datetime.now(), boot_id="b1")
check("同一次开机→不跑", gu.should_run(ST, datetime.now(), boot_id="b1"), False)
check("下一次开机→跑", gu.should_run(ST, datetime.now(), boot_id="b2"), True)

print("[桌面 Screen 匹配忽略空格]")
s = Screen([Line("更 新 游 戏", 10, 10, 50, 20)])
check("有", s.has("更新游戏"), True); check("中心", s.find("更新游戏").center, (35, 20))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
