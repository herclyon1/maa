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

print("[登记：哪个游戏要更新]")
from datetime import datetime as _dt
check("空", gu.pending(ST), {})
check("登记", gu.mark_pending(ST, "终末地", "公告说今天版本更新"), True)
check("重复登记不算", gu.mark_pending(ST, "终末地", "又来"), False)
check("读回", gu.pending(ST), {"终末地": "公告说今天版本更新"})
gu.clear_pending(ST, "终末地"); check("清掉", gu.pending(ST), {})

print("[开机只做便宜判断：不开启动器，只登记]")
class Cfg: pass
cfg = Cfg(); cfg.state_dir = ST; cfg.maa_dir = None; cfg.maaend_dir = None; cfg.okww_dir = None
now = _dt(2026, 9, 2, 8, 46)
notes, probs = gu.boot_check(cfg, budget_s=600, now=now, maint_sources={}, hint=lambda n: "官方公告：今天 09:00 版本更新")
check("公告有版本更新 → 登记终末地", gu.pending(ST), {"终末地": "官方公告：今天 09:00 版本更新"})
check("开机不发更新通知", notes, [])
gu.clear_pending(ST, "终末地")
notes, probs = gu.boot_check(cfg, budget_s=600, now=now, maint_sources={}, hint=lambda n: "")
check("公告没说 → 不登记", gu.pending(ST), {})

print("[队列跑完后：更新 + 只在当天没跑成时重跑]")
cfg.maaend_dir = ST / "maaend"; (cfg.maaend_dir / "config").mkdir(parents=True, exist_ok=True)
game = ST / "hg" / "games" / "Endfield Game" / "Endfield.exe"; game.parent.mkdir(parents=True, exist_ok=True); game.write_bytes(b"")
(ST / "hg" / "Launcher.exe").write_bytes(b"")
(cfg.maaend_dir / "config" / "mxu-MaaEnd.json").write_text(json.dumps({"connectedProgramPath": str(game)}), encoding="utf-8")
(ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "MaaEnd", "ok": False, "raw": {"maaend_unreachable": True}}) + "\n", encoding="utf-8")
gu.mark_pending(ST, "终末地", "今天 MaaEnd 进不了游戏")
dispatched = []
d = FakeDesk([["登录", "更新游戏"], ["正在下载"], ["开始游戏"], ["请重启游戏", "确认"], ["点击任意位置继续"]])
notes, probs, reran = gu.run_deferred(cfg, now=now, desk=d, dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=nosleep)
check("更新通知带依据", notes, ["终末地 客户端已通过启动器更新（依据：今天 MaaEnd 进不了游戏）"])
check("当天因客户端过时没跑成 → 重跑 MaaEnd", reran, ["MaaEnd"])
check("登记已清", gu.pending(ST), {})
# 当天已经成功过：启动器说已是最新，不重跑
(ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "MaaEnd", "ok": True, "raw": {}}) + "\n", encoding="utf-8")
gu.mark_pending(ST, "终末地", "公告说今天版本更新")
dispatched.clear()
notes, probs, reran = gu.run_deferred(cfg, now=now, desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=nosleep)
check("已是最新 → 不发更新通知", notes, [])
check("当天成功过 → 不重跑", reran, [])
check("登记也清了", gu.pending(ST), {})

print("[普通任务失败不重跑（09-02 晚上把用户挤下线的教训）]")
(ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "MaaEnd", "ok": False, "failed_tasks": ["赠送干员礼物"], "raw": {}}) + "\n", encoding="utf-8")
gu.mark_pending(ST, "终末地", "公告说今天版本更新")
dispatched.clear()
notes, probs, reran = gu.run_deferred(cfg, now=now, desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=nosleep)
check("普通失败 → 不重跑", reran, [])
check("登记清掉", gu.pending(ST), {})
notes, probs = gu.boot_check(cfg, budget_s=600, now=now, maint_sources={}, hint=lambda n: "官方公告：今天 09:00 版本更新")
check("普通失败的日子开机仍会登记（由 needs_rerun 拦）", gu.pending(ST), {"终末地": "官方公告：今天 09:00 版本更新"})
gu.clear_pending(ST, "终末地")
(ST / "gameupdate-off.flag").write_text("", encoding="utf-8")
gu.mark_pending(ST, "终末地", "x")
check("总开关关着 → 什么都不做", gu.run_deferred(cfg, now=now, desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: (True, "ok"), sleep=nosleep), ([], [], []))
(ST / "gameupdate-off.flag").unlink(); gu.clear_pending(ST, "终末地")

print("[鸣潮：公告更新维护日 + 等不到窗口才重跑]")
notice = {"game": [{"tabTitle": "「甲」3.7版本内容说明", "content": "<p>更新维护时间：2026年9月2日04:00 ~ 2026年9月2日11:00（UTC+8）</p>"},
                   {"tabTitle": "「乙」3.6版本内容说明", "content": "更新维护时间：2026年8月20日04:00 ~ …"}]}
check("版本号最大的那条写的是今天 → 有信号", bool(gu.wuwa_update_day(_dt(2026, 9, 2, 8, 46), fetch=lambda: notice)), True)
check("别的日子 → 空", gu.wuwa_update_day(_dt(2026, 9, 5, 8, 46), fetch=lambda: notice), "")
cfg.okww_dir = ST / "okww"; wwl = ST / "wwgame" / "Wuthering Waves.exe"; wwl.parent.mkdir(parents=True, exist_ok=True); wwl.write_bytes(b"")
(cfg.okww_dir / "data" / "apps" / "ok-ww" / "working" / "configs").mkdir(parents=True, exist_ok=True)
(cfg.okww_dir / "data" / "apps" / "ok-ww" / "working" / "configs" / "x.json").write_text(json.dumps({"path": str(wwl)}), encoding="utf-8")
(ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "OK-WW", "ok": False, "raw": {"okww_unreachable": True}}) + "\n", encoding="utf-8")
gu.mark_pending(ST, "鸣潮", "官方公告：今天更新维护")
dispatched.clear()
notes, probs, reran = gu.run_deferred(cfg, now=now, desk=FakeDesk([["公告", "立即更新"], ["下载中"], ["开始游戏"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=nosleep)
check("鸣潮更新了", notes, ["鸣潮 客户端已通过启动器更新（依据：官方公告：今天更新维护）"])
check("等不到窗口那种失败 → 重跑 OK-WW", reran, ["OK-WW"])
(ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "OK-WW", "ok": False, "raw": {}}) + "\n", encoding="utf-8")
gu.mark_pending(ST, "鸣潮", "x")
notes, probs, reran = gu.run_deferred(cfg, now=now, desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: (True, "ok"), sleep=nosleep)
check("普通失败 → 不重跑 OK-WW", reran, [])

print("[维护日：窗口落盘、撞上算维护、队列后等开服再补跑]")
from datetime import timedelta as _td
w_start = _dt(2026, 9, 4, 6, 0, tzinfo=gu.SERVER_TZ); w_end = _dt(2026, 9, 4, 12, 0, tzinfo=gu.SERVER_TZ)
gu.save_windows(ST, {"明日方舟": (w_start, w_end, "官方公告：09-04 06:00–12:00 停机维护")})
check("09:00 的 MAA 撞上维护", bool(gu.in_maintenance(ST, "MAA", _dt(2026, 9, 4, 9, 0, tzinfo=gu.SERVER_TZ))), True)
check("开服 45 分钟内仍算（客户端还没更新）", bool(gu.in_maintenance(ST, "MAA", _dt(2026, 9, 4, 12, 30, tzinfo=gu.SERVER_TZ))), True)
check("下午就不算", gu.in_maintenance(ST, "MAA", _dt(2026, 9, 4, 15, 0, tzinfo=gu.SERVER_TZ)), "")
check("别的游戏不受影响", gu.in_maintenance(ST, "MaaEnd", _dt(2026, 9, 4, 9, 0, tzinfo=gu.SERVER_TZ)), "")
(ST / "ledger-2026-09-04.jsonl").write_text(json.dumps({"script": "MAA", "ok": False, "raw": {"maintenance": "官方公告"}}) + "\n", encoding="utf-8")
check("撞上维护的失败 → 该补跑", gu.needs_rerun(ST, _dt(2026, 9, 4, 13, 0), "MAA"), True)
cfg.maa_dir = None
gu.mark_pending(ST, "明日方舟", "官方公告")
slept = []
notes, probs, reran = gu.run_deferred(cfg, now=_dt(2026, 9, 4, 13, 0, tzinfo=gu.SERVER_TZ), desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: (True, "ok"), sleep=lambda s: slept.append(s), clock=lambda: _dt(2026, 9, 4, 13, 0, tzinfo=gu.SERVER_TZ))
check("窗口已过就不等", sum(slept), 0)
slept.clear(); gu.mark_pending(ST, "明日方舟", "官方公告")
ticks = [_dt(2026, 9, 4, 11, 58, tzinfo=gu.SERVER_TZ)]
def clk():
    ticks.append(ticks[-1] + _td(minutes=1)); return ticks[-1]
gu.run_deferred(cfg, now=_dt(2026, 9, 4, 11, 58, tzinfo=gu.SERVER_TZ), desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: (True, "ok"), sleep=lambda s: slept.append(s), clock=clk)
check("还在停服就一分钟一分钟等到开服，再缓 5 分钟", (slept.count(60) >= 1, 300 in slept), (True, True))
gu.save_windows(ST, {})
gu.clear_pending(ST, "明日方舟")

print("[每次开机只跑一遍]")
from datetime import datetime
check("没记录→跑", gu.should_run(ST, datetime.now(), boot_id="b1"), True)
gu.mark_run(ST, datetime.now(), boot_id="b1")
check("同一次开机→不跑", gu.should_run(ST, datetime.now(), boot_id="b1"), False)
check("下一次开机→跑", gu.should_run(ST, datetime.now(), boot_id="b2"), True)

print("[桌面 Screen 匹配忽略空格]")
s = Screen([Line("更 新 游 戏", 10, 10, 50, 20)])
check("有", s.has("更新游戏"), True); check("中心", s.find("更新游戏").center, (35, 20))
s3 = Screen([Line("@丹始游戏", 1324, 782, 200, 40)])
check("错一个字仍命中（OCR 把开认成丹）", s3.find("开始游戏") is not None, True)
check("错一个字不会串到别的按钮", s3.find("更新游戏") is None, True)
check("两字以下不容错", Screen([Line("确人", 0, 0, 10, 10)]).find("确认") is None, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
