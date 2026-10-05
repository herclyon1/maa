"""大版本更新自动化：决策逻辑用假桌面/假命令跑一遍，不碰网络不碰机器。"""
import json
import types
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import gameupdate as gu
from ark_relay import gameupdate_games as gug
from ark_relay.desktop import Line, Screen

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

# 打桩要打在名字真正被查找的那个模块上：2026-09-08 三家游戏的更新流程搬进了
# gameupdate_games，update_endfield 查的是那边的 _spawn/kill；run_deferred 还在
# gameupdate 里，它用的 kill 得单独打一份。
spawned = []
gug._spawn = lambda exe, cwd=None: spawned.append(exe.name) or True
gug.kill = lambda *names: None
gu.kill = lambda *names: None
nosleep = lambda s: None  # noqa: E731

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
# 打在 preupdate_okww 上：update_wuwa 是 `from .preupdate_okww import _okww_quiesce`，
# 查的是那个模块的属性。这里原来打在 preupdate 上，而 preupdate 早已不再转发私有名，
# 于是打了个谁也不看的属性，真正跑的是**真**的 _okww_quiesce——在 Windows 上跑测试
# 会把用户正开着的鸣潮进程杀掉。
import ark_relay.preupdate_okww as pok  # noqa: E402
pok._okww_quiesce = lambda **k: None
pok._okww_close = lambda **k: []      # update_wuwa closes through this since 2026-09-30
d = FakeDesk([["公告", "立即更新"], ["下载中"], ["开始游戏"], ["点击连接"]]); probs = []
out = gu.update_wuwa(d, Path("Wuthering Waves.exe"), poll_s=0, problems=probs, sleep=nosleep)
check("报了更新", out.startswith("鸣潮 客户端已通过启动器更新"), True)
check("点的是按钮中心", d.clicks[0], (140, 140))

print("[明日方舟：版本记录、比对、装包（按 09-03 实测的 adb 路径）]")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402
ST = tmpdir()
calls = []
state = {"ver": "2.7.61", "up": False}
def run(args):
    calls.append(args)
    s = " ".join(map(str, args))
    if s.endswith("devices"):
        return "List of devices attached\nemulator-7554\tdevice\n" if state["up"] else "List of devices attached\n"
    if "dumpsys" in s:
        return f"versionName={state['ver']}\n" if state["up"] else ""
    if " install " in s: state["ver"] = "2.8.01"
    if "taskkill" in s or "quit" in s: state["up"] = False
    return ""
spawn = lambda exe, args: state.__setitem__("up", True) or True  # noqa: E731
fetch = lambda: {"clientVersion": "2.7.61", "resVersion": "x"}  # noqa: E731
out = gu.update_arknights(ST, Path("ldconsole.exe"), 1000, fetch=fetch, run=run, sleep=nosleep, downloader=lambda *a, **k: True, spawn=spawn)
check("首次：只记录不更新", out, "")
check("记录了已装版本", gu.recorded_ak_version(ST), "2.7.61")
check("首次读完关掉了模拟器", any("taskkill" in " ".join(map(str, c)) for c in calls), True)
calls.clear()
out = gu.update_arknights(ST, Path("ldconsole.exe"), 1000, fetch=fetch, run=run, sleep=nosleep, downloader=lambda *a, **k: True, spawn=spawn)
check("同版本：不动", out, ""); check("同版本不起模拟器", calls, [])
fetch2 = lambda: {"clientVersion": "2.8.01"}  # noqa: E731
dl = []
def downloader(url, dest, timeout=0):
    dl.append(dest.name); dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(b"apk"); return True
out = gu.update_arknights(ST, Path("ldconsole.exe"), 1000, fetch=fetch2, run=run, sleep=nosleep, downloader=downloader, spawn=spawn)
check("新版本：下载→adb install→核对", out, "明日方舟 已更新：2.7.61 → 2.8.01（APK 已装进雷电）")
check("下的是新版包", dl, ["arknights-2.8.01.apk"])
check("用 adb install 装", any(" install " in " ".join(map(str, c)) for c in calls), True)
check("装完记录更新", gu.recorded_ak_version(ST), "2.8.01")
check("装完删了包", (ST / "apk" / "arknights-2.8.01.apk").exists(), False)

print("[登记：哪个游戏要更新]")
from datetime import datetime as _dt  # noqa: E402
check("空", gu.pending(ST), {})
check("登记", gu.mark_pending(ST, "终末地", "公告说今天版本更新"), True)
check("重复登记不算", gu.mark_pending(ST, "终末地", "又来"), False)
check("读回", gu.pending(ST), {"终末地": "公告说今天版本更新"})
gu.clear_pending(ST, "终末地"); check("清掉", gu.pending(ST), {})

print("[开机只做便宜判断：不开启动器，只登记]")
class Cfg: pass
cfg = Cfg(); cfg.state_dir = ST; cfg.maa_dir = None; cfg.maaend_dir = None; cfg.okww_dir = None
now = _dt(2026, 9, 2, 8, 46)
# The WuWa notice is always faked: boot_check must not reach the network in a test.
NO_WW = lambda: {"game": []}  # noqa: E731
notes, probs = gu.boot_check(cfg, budget_s=600, now=now, maint_sources={}, hint=lambda n: "官方公告：今天 09:00 版本更新", wuwa_fetch=NO_WW)
check("公告有版本更新 → 登记终末地", gu.pending(ST), {"终末地": "官方公告：今天 09:00 版本更新"})
check("开机不发更新通知", notes, [])
gu.clear_pending(ST, "终末地")
notes, probs = gu.boot_check(cfg, budget_s=600, now=now, maint_sources={}, hint=lambda n: "", wuwa_fetch=NO_WW)
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
notes, probs = gu.boot_check(cfg, budget_s=600, now=now, maint_sources={}, hint=lambda n: "官方公告：今天 09:00 版本更新", wuwa_fetch=NO_WW)
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
notes, probs, reran = gu.run_deferred(cfg, now=now, desk=FakeDesk([["公告", "立即更新"], ["下载中"], ["开始游戏"], ["点击连接"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=nosleep)
check("鸣潮更新了", bool(notes) and notes[0].startswith("鸣潮 客户端已通过启动器更新") and notes[0].endswith("（依据：官方公告：今天更新维护）"), True)
check("等不到窗口那种失败 → 重跑 OK-WW", reran, ["OK-WW"])
(ST / "ledger-2026-09-02.jsonl").write_text(json.dumps({"script": "OK-WW", "ok": False, "raw": {}}) + "\n", encoding="utf-8")
gu.mark_pending(ST, "鸣潮", "x")
notes, probs, reran = gu.run_deferred(cfg, now=now, desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: (True, "ok"), sleep=nosleep)
check("普通失败 → 不重跑 OK-WW", reran, [])

print("[鸣潮启动器 = 有「更新」按钮的 launcher.exe，不是游戏目录里的 Wuthering Waves.exe（2026-09-30 15:50）]")
import logging  # noqa: E402


def _ww_layout(name, launcher_rel):
    """A fake install under ST/<name>: the game folder plus launcher.exe at launcher_rel
    (None = no launcher), and an OK-WW config naming the game body."""
    base = ST / name
    game = base / "Wuthering Waves Game" / "Wuthering Waves.exe"
    game.parent.mkdir(parents=True, exist_ok=True); game.write_bytes(b"")
    if launcher_rel:
        (base / launcher_rel).parent.mkdir(parents=True, exist_ok=True); (base / launcher_rel).write_bytes(b"")
    okww = base / "okww"
    (okww / "data" / "apps" / "ok-ww" / "working" / "configs").mkdir(parents=True, exist_ok=True)
    (okww / "data" / "apps" / "ok-ww" / "working" / "configs" / "x.json").write_text(
        json.dumps({"path": str(game)}), encoding="utf-8")
    return base, okww, game


base, okww, game = _ww_layout("ww-sibling", Path("Wuthering Waves") / "launcher.exe")
check("机器上的布局：D:\\Wuthering Waves\\launcher.exe 与游戏目录同级 → 用它", gug.wuwa_launcher(okww),
      base / "Wuthering Waves" / "launcher.exe")
base, okww, game = _ww_layout("ww-nested", Path("launcher.exe"))
check("库洛默认布局：游戏目录在启动器目录里 → 上一级的 launcher.exe", gug.wuwa_launcher(okww), base / "launcher.exe")


class _KeepWarn(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING); self.msgs = []
    def emit(self, record):
        self.msgs.append(record.getMessage())


kw = _KeepWarn(); gug.log.addHandler(kw)
base, okww, game = _ww_layout("ww-none", None)
check("找不到启动器 → 退回游戏本体", gug.wuwa_launcher(okww), game)
check("…并写一条 warning 说明找过哪里", len(kw.msgs) == 1 and "没找到鸣潮启动器" in kw.msgs[0]
      and str(base / "Wuthering Waves" / "launcher.exe") in kw.msgs[0], True)
gug.log.removeHandler(kw)
check("没配 OK-WW 目录 → None", gug.wuwa_launcher(None), None)

print("[维护日：窗口落盘、撞上算维护、队列后等开服再补跑]")
from datetime import timedelta as _td  # noqa: E402
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
ticks0 = [_dt(2026, 9, 4, 13, 0, tzinfo=gu.SERVER_TZ)]
def clk0():
    ticks0.append(ticks0[-1] + _td(minutes=10)); return ticks0[-1]
notes, probs, reran = gu.run_deferred(cfg, now=_dt(2026, 9, 4, 13, 0, tzinfo=gu.SERVER_TZ), desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: (True, "ok"), sleep=lambda s: slept.append(s), clock=clk0)
check("准备不了（没雷电）→ 每 10 分钟重试到截止，不补跑", (reran, 600 in slept, any("仍没准备好" in p for p in probs)), ([], True, True))
# 终末地：客户端准备好了、离开服还远 → 关游戏、一分钟一分钟等到开服、缓 2 分钟、再补跑
gu.save_windows(ST, {"终末地": (_dt(2026, 9, 4, 6, 0, tzinfo=gu.SERVER_TZ), _dt(2026, 9, 4, 12, 0, tzinfo=gu.SERVER_TZ), "官方公告")})
(ST / "ledger-2026-09-04.jsonl").write_text(json.dumps({"script": "MaaEnd", "ok": False, "raw": {"maintenance": "官方公告"}}) + "\n", encoding="utf-8")
gu.mark_pending(ST, "终末地", "官方公告")
slept.clear(); dispatched.clear()
ticks1 = [_dt(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ)]
def clk1():
    ticks1.append(ticks1[-1] + _td(minutes=1)); return ticks1[-1]
notes, probs, reran = gu.run_deferred(cfg, now=_dt(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ), desk=FakeDesk([["开始游戏"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=lambda s: slept.append(s), clock=clk1)
check("先准备好再等开服：一分钟一分钟等，开服后缓 2 分钟，然后补跑", (slept.count(60) >= 1, 120 in slept, reran), (True, True, ["MaaEnd"]))
gu.save_windows(ST, {})
gu.clear_pending(ST, "明日方舟")

print("[维护日：队列时刻落在窗口里 → 摘掉；补跑完加回]")
gu.save_windows(ST, {})
(ST / "queue-skips.json").unlink(missing_ok=True)
import ark_relay.plan as _plan  # noqa: E402
_plan_backup = _plan.schedule
_plan.schedule = lambda d: [{"name": "早班", "times": ["09:00"]}, {"name": "晚班", "times": ["21:30"]}]
cfg.automas_dir = ST
skipped = []
src_ak = {"明日方舟": lambda n: (_dt(2026, 9, 4, 6, 0, tzinfo=gu.SERVER_TZ), _dt(2026, 9, 4, 12, 0, tzinfo=gu.SERVER_TZ), "官方公告：09-04 06:00–12:00")}
notes, probs = gu.boot_check(cfg, budget_s=600, now=_dt(2026, 9, 4, 8, 46, tzinfo=gu.SERVER_TZ), maint_sources=src_ak, hint=lambda n: "", wuwa_fetch=NO_WW,
                             skipper=lambda q, sc: skipped.append((q, sc)) or {"queue": q, "queueId": "Q", "script": sc, "scriptId": "S", "position": 0})
check("早班 09:00 在窗口里 → 从早班摘掉 MAA", skipped, [("早班", "MAA")])
check("晚班 21:30 不在窗口里 → 不摘", len(skipped), 1)
check("登记了明日方舟", "明日方舟" in gu.pending(ST), True)
check("摘掉的记在案", [r["script"] for r in gu.skips(ST)], ["MAA"])
check("被摘掉的即使没失败记录也要补跑", gu.needs_rerun(ST, _dt(2026, 9, 4, 13, 0), "MAA"), True)
restored = []
dispatched.clear()
ticks = [_dt(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ)]
def clk2():
    ticks.append(ticks[-1] + _td(minutes=1)); return ticks[-1]
cfg.maa_dir = None   # 找不到雷电 → 准备失败 → 每 10 分钟重试直到截止
notes, probs, reran = gu.run_deferred(cfg, now=_dt(2026, 9, 4, 10, 30, tzinfo=gu.SERVER_TZ), desk=FakeDesk([["x"]]), dispatch=lambda s: dispatched.append(s) or (True, "ok"), sleep=lambda s: None, clock=clk2)
check("准备不了 → 不补跑、问题里说明", (reran, any("仍没准备好" in p for p in probs)), ([], True))
gu.clear_pending(ST, "明日方舟")
import ark_relay.gameupdate as _gu2  # noqa: E402
_orig_restore = _gu2.restore_skips
done = gu.restore_skips(ST, restorer=lambda rec: restored.append(rec["script"]) or True)
check("加回", (done, restored, gu.skips(ST)), (["MAA→「早班」"], ["MAA"], []))
_plan.schedule = _plan_backup

print("[停一切停掉的那趟既不算成功也不算失败（2026-09-30 鸣潮 3.7 维护日漏接）]")
import logging  # noqa: E402


class _Keep(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO); self.recs = []
    def emit(self, record):
        self.recs.append((record.levelno, record.getMessage(), record.exc_info is not None))


keep = _Keep(); gu.log.addHandler(keep); gu.log.setLevel(logging.INFO)
T = gu.SERVER_TZ
# The machine's ledger-2026-09-30.jsonl, in order (run_id is the path-like form handle.py books)
L930 = [
    {"script": "MAA", "run_id": "2026-09-30/maa/MAA-05-01-02", "started": "2026-09-30T05:01:02+08:00",
     "finished": "2026-09-30T05:39:10+08:00", "ok": True, "raw": {}},
    {"script": "OK-WW", "run_id": "2026-09-30/wuwa/OK-WW-09-19-00", "started": "2026-09-30T09:19:00+08:00",
     "finished": "2026-09-30T09:20:00+08:00", "ok": False,
     "raw": {"evidence_page": "x", "general_result": "失败", "okww_error": "进不了游戏"}},
    {"script": "OK-WW", "run_id": "2026-09-30/wuwa/OK-WW-09-30-00", "started": "2026-09-30T09:30:00+08:00",
     "finished": "2026-09-30T09:31:00+08:00", "ok": False,
     "raw": {"evidence_page": "x", "general_result": "失败", "okww_error": "进不了游戏"}},
    {"script": "OK-WW", "run_id": "2026-09-30/wuwa/OK-WW-05-40-56", "started": "2026-09-30T09:40:56+08:00",
     "finished": "2026-09-30T09:47:00+08:00", "ok": True,
     "raw": {"evidence_page": "x", "general_result": "Success!", "manual_stop": "09:46 停一切"}},
    {"script": "MaaEnd", "run_id": "2026-09-30/endfield/MaaEnd-05-46-45", "started": "2026-09-30T09:46:45+08:00",
     "finished": "2026-09-30T09:47:10+08:00", "ok": False,
     "raw": {"maaend_result": "中止", "manual_stop": "09:46 停一切"}},
]


def _ledger930(rows):
    (ST / "ledger-2026-09-30.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                                 encoding="utf-8")


_ledger930(L930)
n930 = _dt(2026, 9, 30, 8, 49, 50, tzinfo=T)
check("last_run_ok(OK-WW)：跳过停一切那趟，看前一趟 → False", gu.last_run_ok(ST, n930, "OK-WW"), False)
check("last_run_ok(MaaEnd)：唯一一趟是停一切 → 等于今天没跑过", gu.last_run_ok(ST, n930, "MaaEnd"), None)
check("last_run_ok(MAA) 不受影响", gu.last_run_ok(ST, n930, "MAA"), True)
check("needs_rerun(OK-WW)：前一趟是普通失败 → 不补跑", gu.needs_rerun(ST, n930, "OK-WW"), False)
check("needs_rerun(MaaEnd)：只有停一切那趟 → 不补跑", gu.needs_rerun(ST, n930, "MaaEnd"), False)
# Settled 2026-09-30 18:04: a script the red button stopped is not re-run after the update that day (this used to be True)
_ledger930(L930[:3] + [dict(L930[2], raw={"okww_unreachable": True})] + L930[3:])
check("needs_rerun(OK-WW)：停一切之前那趟是进不了游戏，但今天被停一切停过 → 不补跑",
      gu.needs_rerun(ST, n930, "OK-WW"), False)
_ledger930(L930[:3] + [dict(L930[2], raw={"maintenance": "官方公告：维护"})] + L930[3:])
check("needs_rerun(OK-WW)：前一趟带维护标记 + 最后一趟停一切 → 不补跑",
      gu.needs_rerun(ST, n930, "OK-WW"), False)
check("stopped_today 给出按下的时刻", gu.stopped_today(ST, n930, "OK-WW"), "09:46 停一切")
check("stopped_today：没被停过的脚本 → 空", gu.stopped_today(ST, n930, "MAA"), "")
_ledger930([r for r in L930 if r["script"] != "MaaEnd"][:3]
           + [dict(L930[2], run_id="2026-09-30/wuwa/OK-WW-09-35-00", raw={"okww_unreachable": True})])
check("needs_rerun(OK-WW)：没被停过、最后一趟进不了游戏 → 照旧补跑", gu.needs_rerun(ST, n930, "OK-WW"), True)
_ledger930(L930)
print("[被停一切停过的脚本：run_deferred 不补跑，通知里写「已停，未补」]")
_calls, _reran, _probs, _notes = [], [], [], []
gu._rerun_script(types.SimpleNamespace(state_dir=ST), n930, lambda sc: _calls.append(sc) or (True, "ok"),
                 "OK-WW", _reran, _probs, _notes)
check("没派", (_calls, _reran, _probs), ([], [], []))
check("通知写已停未补", _notes, ["OK-WW：今天 09:46 停一切停过，已停，未补"])

ww_notice = {"game": [{"tabTitle": "「甲」3.7版本内容说明",
                       "content": "<p>更新维护时间：2026年9月30日04:00 ~ 2026年9月30日11:00（UTC+8）</p>"}]}
src_ww = {"鸣潮": lambda n: (_dt(2026, 9, 30, 4, 0, tzinfo=T), _dt(2026, 9, 30, 11, 0, tzinfo=T),
                             "官方公告：「甲」3.7版本内容说明（09-30 04:00–11:00）")}
_plan.schedule = lambda d: [{"name": "早班", "times": ["09:00"]}, {"name": "晚班", "times": ["21:30"]}]
(ST / "queue-skips.json").unlink(missing_ok=True)
for g in list(gu.pending(ST)):
    gu.clear_pending(ST, g)
gu._store(ST).set("updates", "queue_skips", [])
skipped = []; keep.recs.clear()
notes, probs = gu.boot_check(cfg, budget_s=600, now=n930, maint_sources=src_ww, hint=lambda n: "",
                             wuwa_fetch=lambda: ww_notice,
                             skipper=lambda q, sc: skipped.append((q, sc)) or {"queue": q, "queueId": "Q", "script": sc, "scriptId": "S", "position": 0})
check("今天的 5 条账本 + 鸣潮维护 → 登记鸣潮", "鸣潮" in gu.pending(ST), True)
check("早班 09:00 在维护窗口里 → 从早班摘掉 OK-WW", skipped, [("早班", "OK-WW")])
msgs = [m for _l, m, _e in keep.recs]
check("日志：终末地公告说了今天没有版本更新", any("终末地公告——今天没有版本更新" in m for m in msgs), True)
check("日志：维护公告列出鸣潮窗口", any("维护公告——鸣潮 04:00–11:00" in m for m in msgs), True)
check("日志：维护那边再遇到鸣潮说已登记", any("鸣潮维护——" in m and "之前已登记" in m for m in msgs), True)

print("[对照：最后一趟 OK-WW 是真成功 → 不登记，日志写明原因]")
for g in list(gu.pending(ST)):
    gu.clear_pending(ST, g)
gu._store(ST).set("updates", "queue_skips", [])
_ledger930(L930[:3] + [dict(L930[3], raw={"evidence_page": "x", "general_result": "Success!"})] + L930[4:])
skipped = []; keep.recs.clear()
notes, probs = gu.boot_check(cfg, budget_s=600, now=n930, maint_sources=src_ww, hint=lambda n: "",
                             wuwa_fetch=lambda: ww_notice, skipper=lambda q, sc: skipped.append((q, sc)) or None)
check("今天真成功过 → 不登记鸣潮", "鸣潮" in gu.pending(ST), False)
check("也不从队列摘", skipped, [])
msgs = [m for _l, m, _e in keep.recs]
check("日志：公告那条写「已成功过，不登记」", any("鸣潮公告——" in m and "OK-WW 今天已成功过，不登记" in m for m in msgs), True)
check("日志：维护那条也写", any("鸣潮维护——" in m and "OK-WW 今天已成功过，不登记" in m for m in msgs), True)

print("[鸣潮公告：不是今天 / 没有维护时间 / 读挂了，都写日志]")
keep.recs.clear()
gu.wuwa_update_day(_dt(2026, 10, 2, 8, 0), fetch=lambda: ww_notice)
check("不是今天 → info 带公告里的日期", [m for _l, m, _e in keep.recs],
      ["游戏更新：鸣潮公告——维护日写的是 2026-09-30，今天不是维护日"])
keep.recs.clear()
gu.wuwa_update_day(n930, fetch=lambda: {"game": [{"tabTitle": "「乙」3.7版本内容说明", "content": "敬请期待"}]})
check("没写维护时间 → info 说没找到", [m for _l, m, _e in keep.recs],
      ["游戏更新：鸣潮公告——1 条「版本内容说明」，最新那条里没找到「更新维护时间」"])
keep.recs.clear()
def _boom():
    raise OSError("连不上")
check("读挂了 → 空", gu.wuwa_update_day(n930, fetch=_boom), "")
check("读挂了 → warning 带 exc_info", [(l, e) for l, _m, e in keep.recs], [(logging.WARNING, True)])
# 2026-10-06 audit: an unreadable notice used to be only a log line - "not the
# maintenance day" as far as anyone reading the pushes could tell. boot_check's
# problems (pushed as 「⚠️ 游戏更新没能确认」) now say so; checked just below.
keep.recs.clear()
gu.boot_check(cfg, budget_s=600, now=n930, maint_sources={}, hint=lambda n: "", wuwa_fetch=_boom)
check("开机检查：没有维护也写一行", any("维护公告——今天没有游戏停服维护" in m for _l, m, _e in keep.recs), True)
keep.recs.clear()
def _hint_boom(n):
    raise OSError("终末地公告连不上")
_n, _p = gu.boot_check(cfg, budget_s=600, now=n930, maint_sources={}, hint=_hint_boom, wuwa_fetch=_boom)
check("终末地公告读挂 → warning", sum(1 for l, m, _e in keep.recs if l == logging.WARNING and "终末地公告读不到" in m), 1)
check("终末地 + 鸣潮公告读挂 → 两条都进 problems", sorted(_p),
      ["终末地：官方公告读不到，今天有没有版本更新不知道", "鸣潮：官方公告读不到，今天是不是维护日不知道"])
# The log must not contradict the problem: unreadable is not "no update today"
check("终末地公告读挂 → 不再写「今天没有版本更新」",
      [m for _l, m, _e in keep.recs if "终末地公告——今天没有版本更新" in m], [])
check("公告读挂的警告不说「当作」", [m for _l, m, _e in keep.recs if "当作今天" in m], [])
import ark_relay.maintenance as _mt  # noqa: E402
_mt_today = _mt.today
_mt.today = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("维护模块坏了"))
keep.recs.clear()
gu.boot_check(cfg, budget_s=600, now=n930, maint_sources={}, hint=lambda n: "", wuwa_fetch=_boom)
check("维护公告整体读挂 → warning", sum(1 for l, m, _e in keep.recs if l == logging.WARNING and "维护公告整体读不到" in m), 1)
_mt.today = _mt_today

print("[维护公告读不到：保留今天早先存的窗口，不写「今天没有维护」]")
W_WW = (_dt(2026, 9, 30, 4, 0, tzinfo=T), _dt(2026, 9, 30, 11, 0, tzinfo=T), "官方公告：鸣潮 3.7")
W_OLD = (_dt(2026, 9, 28, 4, 0, tzinfo=T), _dt(2026, 9, 28, 11, 0, tzinfo=T), "官方公告：前天的")
gu.save_windows(ST, {"鸣潮": W_WW, "终末地": W_OLD})
keep.recs.clear()
gu.boot_check(cfg, budget_s=600, now=n930, hint=lambda n: "", wuwa_fetch=_boom,
              maint_sources={"鸣潮": lambda n: (_ for _ in ()).throw(OSError("连不上")),
                             "明日方舟": lambda n: None})
check("鸣潮读挂 → 今天的窗口还在", gu.windows(ST).get("鸣潮"), W_WW)
check("前天的窗口不沿用", "终末地" in gu.windows(ST), False)
msgs = [m for _l, m, _e in keep.recs]
check("日志说读不到、沿用", any("维护公告读不到（鸣潮），沿用已存窗口：鸣潮 04:00–11:00" in m for m in msgs), True)
check("日志不说今天没有维护", any("今天没有游戏停服维护" in m for m in msgs), False)
check("沿用的窗口不再走登记（早先登记过）", "鸣潮" in gu.pending(ST), False)
gu.save_windows(ST, {"鸣潮": W_WW})
_mt.today = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("维护模块坏了"))
keep.recs.clear()
gu.boot_check(cfg, budget_s=600, now=n930, maint_sources={}, hint=lambda n: "", wuwa_fetch=_boom)
_mt.today = _mt_today
check("整体读挂 → 窗口也还在", gu.windows(ST).get("鸣潮"), W_WW)
check("整体读挂 → 日志说全部读不到", any("维护公告读不到（全部），沿用已存窗口：鸣潮" in m for _l, m, _e in keep.recs), True)
gu.boot_check(cfg, budget_s=600, now=n930, maint_sources={"鸣潮": lambda n: None}, hint=lambda n: "",
              wuwa_fetch=_boom)
check("读到了、确实没有 → 窗口清掉", gu.windows(ST), {})
for g in list(gu.pending(ST)):
    gu.clear_pending(ST, g)
gu._store(ST).set("updates", "queue_skips", [])
gu.save_windows(ST, {})
_plan.schedule = _plan_backup
gu.log.removeHandler(keep)

print("[每次开机只跑一遍]")
from datetime import datetime  # noqa: E402
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

print("[2026-10-06 审计：读不到 ≠ 没事]")
from ark_relay import efstatus as _efs  # noqa: E402
gu.log.addHandler(keep)
A = tmpdir()
acfg = Cfg(); acfg.state_dir = A; acfg.maa_dir = A / "maa"; acfg.maaend_dir = None; acfg.okww_dir = None
acfg.automas_dir = A
# 1. Arknights: the version endpoint answers without clientVersion. Before: 「明日方舟已是 ?，无需更新」
#    and nothing pushed; update_arknights (gameupdate_games.py) calls the same case a problem.
_ld = gu.ldconsole_of
gu.ldconsole_of = lambda d: (Path("ldconsole.exe"), 1000)
gu.record_ak_version(A, "2.7.61")
keep.recs.clear()
_n, _p = gu.boot_check(acfg, budget_s=600, now=n930, fetch=lambda: {"resVersion": "x"},
                       hint=lambda n: "", wuwa_fetch=lambda: ww_notice, maint_sources={})
check("方舟远端版本空 → problems 说没有版本号", [x for x in _p if x.startswith("明日方舟")],
      ["明日方舟：官方的版本信息里没有客户端版本号"])
check("方舟远端版本空 → 不说「无需更新」", any("无需更新" in m for _l, m, _e in keep.recs), False)
keep.recs.clear()
_n, _p = gu.boot_check(acfg, budget_s=600, now=n930, fetch=lambda: {"clientVersion": "2.7.61"},
                       hint=lambda n: "", wuwa_fetch=lambda: ww_notice, maint_sources={})
check("方舟远端 = 本地 → 无需更新、无 problem", (any("明日方舟已是 2.7.61，无需更新" in m for _l, m, _e in keep.recs), _p),
      (True, []))
gu.ldconsole_of = _ld
# 2. Endfield, default hint: efstatus.update_hint swallowed every error and returned "",
#    so boot_check's own except never ran and an unreachable bulletin read as "no update".
import urllib.request as _ur  # noqa: E402
_uo = _ur.urlopen
def _no_net(*a, **k):
    raise OSError("bulletin unreachable")
_ur.urlopen = _no_net
keep.recs.clear()
try:
    _n, _p = gu.boot_check(acfg, budget_s=600, now=n930, wuwa_fetch=lambda: ww_notice, maint_sources={})
finally:
    _ur.urlopen = _uo
check("终末地默认公告接口连不上 → problems", [x for x in _p if x.startswith("终末地")],
      ["终末地：官方公告读不到，今天有没有版本更新不知道"])
check("efstatus 非 strict 仍返回空（handle.py 只拿它当旁证）",
      _efs.update_hint(fetch=_no_net), "")
# 3. MAA's unreachable flag: needs_rerun("MAA") could only be true via skips / maintenance.
_ledger_rows = [{"script": "MAA", "run_id": "2026-09-30/maa/MAA-05-01-02", "started": "2026-09-30T05:01:02+08:00",
                 "finished": "2026-09-30T05:09:10+08:00", "ok": False,
                 "raw": {"maa_unreachable": True}}]
(A / "ledger-2026-09-30.jsonl").write_text("".join(json.dumps(r) + "\n" for r in _ledger_rows), encoding="utf-8")
check("MAA 失败且 raw 带 maa_unreachable → needs_rerun", gu.needs_rerun(A, n930, "MAA"), True)
_ledger_rows[0]["raw"] = {"maa_error": "关卡失败"}
(A / "ledger-2026-09-30.jsonl").write_text("".join(json.dumps(r) + "\n" for r in _ledger_rows), encoding="utf-8")
check("MAA 普通失败 → 不重跑", gu.needs_rerun(A, n930, "MAA"), False)
# 4. spmed: the v2.28.0-beta.4 node has no recognition block at all (gameupdate.py comment,
#    read off the machine 2026-09-09). The old code switched the task on 「要是明天又失败就再关」,
#    but nothing calls maaend_set_enabled(..., False) anywhere in the relay.
E = A / "maaend"; (E / "resource" / "pipeline").mkdir(parents=True)
(E / "interface.json").write_text(json.dumps({"version": "v2.28.0-beta.4"}), encoding="utf-8")
master = A / "data" / "u1" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"; master.parent.mkdir(parents=True)
def _master(on):
    master.write_text(json.dumps({"instances": [{"tasks": [{"taskName": "AutoUseSpMedication", "enabled": on}]}]}),
                      encoding="utf-8")
def _sp_on():
    return json.loads(master.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["enabled"]
acfg.maaend_dir = E
_rec = {"tasks": ["AutoUseSpMedication"], "since": "v2.27.0-beta.5"}
(E / "resource" / "pipeline" / "nodes.json").write_text(json.dumps(
    {"AutoUseSpMedicationQuickUse": {"next": ["AutoUseSpMedicationRewardsConfirm"], "action": "Click"}}), encoding="utf-8")
_master(False); gu._store(A).set("updates", "maaend_disabled_spmed", dict(_rec))
check("认不出的写法 → spmed_fix_present None", gu.spmed_fix_present(E), None)
out = gu.maaend_reenable_spmed_if_updated(acfg)
check("认不出 → 任务继续关着", _sp_on(), False)
check("认不出 → 不说开回来", "开回来" in out, False)
check("认不出 → 记录还在、since 记成这个版本", gu._store(A).get("updates", "maaend_disabled_spmed"),
      {"tasks": ["AutoUseSpMedication"], "since": "v2.28.0-beta.4"})
gu._store(A).set("updates", "maaend_disabled_spmed", dict(_rec))
_sp = []
gu.maaend_reenable_spmed_if_updated(acfg, problems=_sp)
check("认不出 → problems 带版本和节点键", _sp,
      ["终末地：MaaEnd 已是 v2.28.0-beta.4，加强剂那一步的写法认不出（这一步里有：next、action），看不出修没修，任务继续关着"])
_sp2 = []
check("同一版本第二次开机 → 不再重复说", (gu.maaend_reenable_spmed_if_updated(acfg, problems=_sp2), _sp2), ("", []))
# Broken shape (beta.5, verbatim from the comment above spmed_fix_present) stays off silently.
gu._store(A).set("updates", "maaend_disabled_spmed", dict(_rec))
(E / "resource" / "pipeline" / "nodes.json").write_text(json.dumps({"AutoUseSpMedicationQuickUse": {"recognition": {
    "param": {"all_of": ["YellowConfirmButtonType2", {"param": {}, "type": "OCR"}]}}}}), encoding="utf-8")
check("坏的写法 → 继续关着、无 problem", (gu.maaend_reenable_spmed_if_updated(acfg, problems=_sp2), _sp_on(), _sp2), ("", False, []))
# Fixed shape (PR #5453: wrapped in recognition) → switched on, record removed.
(E / "resource" / "pipeline" / "nodes.json").write_text(json.dumps({"AutoUseSpMedicationQuickUse": {"recognition": {
    "param": {"all_of": ["YellowConfirmButtonType2", {"recognition": {"param": {}, "type": "OCR"}}]}}}}), encoding="utf-8")
check("修好的写法 → 开回来", gu.maaend_reenable_spmed_if_updated(acfg),
      "MaaEnd 已是 v2.28.0-beta.4，加强剂那一步已经修好，任务开回来")
check("修好的写法 → 母本里开了、记录删了", (_sp_on(), gu._store(A).get("updates", "maaend_disabled_spmed")), (True, None))
gu.log.removeHandler(keep)

print("[终末地：更新后说客户端过时，下一轮启动器「开始游戏」不能算就绪]")
# The problem string is the one update_endfield notes after the install
# (gameupdate_games.py 「终末地：更新后游戏仍说客户端已过时」); round two is what the
# launcher then shows, 「开始游戏」 -> prepare returns (True, "") = "no update needed".
_rounds = iter([
    lambda pr: (pr.append("终末地：更新后游戏仍说客户端已过时"), (False, ""))[1],
    lambda pr: (True, ""),
    lambda pr: (True, ""),
])
_orig_prep = gu._prepare_client
gu._prepare_client = lambda cfg, desk, game, problems, sleep: next(_rounds)(problems)
_ticks = iter(range(100))
from datetime import datetime as _dt, timedelta as _tdl  # noqa: E402
_t0 = _dt(2026, 10, 6, 9, 0)
_pr: list = []
_ready, _note = gu._prepare_until_ready(None, None, "终末地", deadline=_t0 + _tdl(minutes=15),
                                        clock=lambda: _t0 + _tdl(minutes=10 * next(_ticks)),
                                        sleep=lambda s: None, problems=_pr,
                                        expect_new=False, local0="")
gu._prepare_client = _orig_prep
check("过时之后的「无需更新」不算就绪", _ready, False)
check("留一条问题说清楚", any("客户端已过时" in x and "没准备好" in x for x in _pr), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
