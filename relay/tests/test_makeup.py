"""A MAA / MaaEnd failure gets one make-up run, then goes to the daily report only.

The user, 2026-10-05 13:07: 「中继我就要求一个，他不要再报错了……几乎就是遇到
一点小毛病就停下来报错」. 2026-09-25: MaaEnd's 赠送干员礼物 / 基质刷取 /
日常奖励领取 failed 3/3 (tests/fixtures/maaend_bagfull_2026-09-25.log) and the
group got 「最终失败」. Here the same three names are mapped onto the real master
(tests/fixtures/maaend-2026-09-10/master-before.json, with that install's own
zh_cn.json), the master is narrowed and put back, and the alarm path is replayed
before and after the make-up.
"""
import copy
import json
import os
import shutil
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
HIST = TMP / "history"
HIST.mkdir()
os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import core, handle, makeup, report, shutdown, texts   # noqa: E402
from ark_relay import engine as eng_mod                               # noqa: E402
from ark_relay.collector_maaend import BAG_FULL                       # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord             # noqa: E402
from ark_relay.core import State                                      # noqa: E402
from ark_relay.notify import route_of                                 # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


FX = Path(__file__).resolve().parent / "fixtures" / "maaend-2026-09-10"
MASTER = json.loads((FX / "master-before.json").read_text(encoding="utf-8"))
THREE = ["赠送干员礼物", "基质刷取", "日常奖励领取"]          # 2026-09-25, as MaaEnd prints them, emoji stripped
# Noon today: every stamp below stays on today's date whatever the hour the suite runs.
NOW = datetime.now(tz=SERVER_TZ).replace(hour=12, minute=0, second=0, microsecond=0)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []


class Src:
    def fetch(self, seen):
        return []


def put_master(doc) -> Path:
    """A fresh AUTO-MAS data dir holding `doc` as the MaaEnd master; returns its root."""
    root = tmpdir()
    d = root / "data" / "sid" / "Default" / "ConfigFile"
    d.mkdir(parents=True)
    (d / "mxu-MaaEnd.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def master_of(root: Path) -> dict:
    return json.loads((root / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json").read_text(encoding="utf-8"))


def enabled(doc) -> list[str]:
    return [t["taskName"] for t in doc["instances"][0]["tasks"]
            if t.get("enabled") and not t["taskName"].startswith("__")]


def build(automas=None):
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.automas_dir = automas
    cfg.maaend_dir = FX
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._unfinished_queues = lambda now, entries: []
    e._deferred_update_busy = lambda: False
    return e


def rec(script, started, ok=False, failed=None, raw=None, user=None, run_id=None):
    user = user or {"MAA": "arknights", "MaaEnd": "endfield", "OK-WW": "wuwa"}[script]
    return RunRecord(run_id=run_id or f"{started:%Y-%m-%d}/{user}/{script}-{started:%H-%M-%S}",
                     script=script, user=user, started=started, finished=started + timedelta(minutes=5),
                     ok=ok, failed_tasks=list(failed or ([] if ok else ["x"])), raw=dict(raw or {}))


def hold(e, r):
    e.state.append_ledger(r)
    e._pending[(r.script, r.user)] = r


def alarms(e):
    return [t for t, _, a in e.notifier.sent if a]


handle._ship_evidence = lambda eng, rec: ""
real_dispatch, real_kill = makeup._dispatch, makeup._kill_game
dispatched, killed = [], []
makeup._kill_game = lambda: killed.append(makeup.GAME_EXE)
earlier = NOW - timedelta(hours=1)

print("[哪些失败要补跑：今天的明日方舟 / 终末地，维护、进不了游戏、停一切停的不补，鸣潮不归这里]")
check("今天的终末地", makeup.eligible(rec("MaaEnd", earlier), NOW))
check("今天的明日方舟", makeup.eligible(rec("MAA", earlier), NOW))
check("鸣潮不补", makeup.eligible(rec("OK-WW", earlier), NOW), False)
check("昨天的不补", makeup.eligible(rec("MaaEnd", NOW - timedelta(days=1)), NOW), False)
check("维护日不补", makeup.eligible(rec("MaaEnd", earlier, raw={"maintenance": "维护"}), NOW), False)
check("进不了游戏不补", makeup.eligible(rec("MaaEnd", earlier, raw={"maaend_unreachable": True}), NOW), False)
check("停一切停的不补", makeup.eligible(rec("MAA", earlier, raw={"manual_stop": "10:00 停一切"}), NOW), False)

print("\n[终末地失败的三项对到真母本：只开这三项，MXU 自己的条目不动，改回逐字节一样]")
labels = makeup._labels(FX)
check("语言包里的名字", (labels.get("GiftOperator"), labels.get("AutoEssence"), labels.get("DailyRewards")),
      ("赠送干员礼物", "基质刷取", "日常奖励领取"))
want, unmapped = makeup.plan_maaend(MASTER, THREE + ["根本没有这一项"], {}, labels)
check("对上三项", want, ["GiftOperator", "AutoEssence", "DailyRewards"])
check("对不上的单列", unmapped, ["根本没有这一项"])
check("自动采集归采集补跑，不在这里补", makeup.plan_maaend(MASTER, ["自动采集"], {}, labels), ([], []))
root = put_master(MASTER)
before_bytes = (root / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json").read_text(encoding="utf-8")
cfg = types.SimpleNamespace(automas_dir=root, state_dir=tmpdir(), maaend_dir=FX)
line = makeup.narrow_master(cfg, want, "run-1", NOW)
doc = master_of(root)
check("有说明", "GiftOperator" in line)
check("只开三项", enabled(doc), ["GiftOperator", "AutoEssence", "DailyRewards"])
by = {t["taskName"]: t for t in doc["instances"][0]["tasks"] if not t["taskName"].startswith("__")}
check("控制器那份也跟着关", by["GearAssembly"]["enabledByController"], {"Win32-Front": False})
check("布尔写法的控制器开关也跟着改", (by["TrialOfSwordmancy"]["enabledByController"], by["AutoEssence"]["enabledByController"]), (False, True))
kp = [t for t in doc["instances"][0]["tasks"] if t["taskName"] == "__MXU_KILLPROC__"][0]
check("MXU 的结束进程条目原样", kp["enabled"], True)
check("收窄记录存了", (cfg.state_dir / "makeup" / "narrow.json").is_file())
makeup.narrow_master(cfg, ["GiftOperator"], "run-2", NOW)
check("第二次收窄不覆盖原始记录", json.loads((cfg.state_dir / "makeup" / "narrow.json").read_text(encoding="utf-8"))["run_id"], "run-1")
back = makeup.restore(cfg)
check("改回有说明", "改回原样" in back)
check("改回后和原来一模一样", master_of(root), MASTER)
check("收窄记录删掉", (cfg.state_dir / "makeup" / "narrow.json").exists(), False)
check("没有记录时改回是空操作", makeup.restore(cfg), "")
check("原文件内容没被别处碰过", before_bytes == json.dumps(MASTER, ensure_ascii=False, indent=2))

print("\n[背包满了：母本里有「存放背包」才开它，并挪到领奖前面；没有就不加；拆解基质永远不开]")
check("母本里没有存放背包 → 不加", makeup.plan_maaend(MASTER, ["基质刷取"], {"基质刷取": BAG_FULL}, labels)[0], ["AutoEssence"])
m2 = copy.deepcopy(MASTER)
tasks = m2["instances"][0]["tasks"]
tasks.insert(len(tasks) - 1, {"id": "stash01", "taskName": "StashBackpack", "enabled": False,
                              "enabledByController": {"Win32-Front": False}})
tasks.insert(len(tasks) - 1, {"id": "decomp1", "taskName": "DecomposeWeaponEssence", "enabled": True,
                              "enabledByController": {"Win32-Front": True}})
want2, _ = makeup.plan_maaend(m2, ["基质刷取"], {"基质刷取": BAG_FULL}, labels)
check("有存放背包 → 一起开", want2, ["StashBackpack", "AutoEssence"])
check("没背包满就不开存放背包", makeup.plan_maaend(m2, ["基质刷取"], {}, labels)[0], ["AutoEssence"])
root2 = put_master(m2)
cfg2 = types.SimpleNamespace(automas_dir=root2, state_dir=tmpdir(), maaend_dir=FX)
makeup.narrow_master(cfg2, want2 + ["DecomposeWeaponEssence"], "run-3", NOW)
d2 = master_of(root2)
names = [t["taskName"] for t in d2["instances"][0]["tasks"]]
check("存放背包挪到基质刷取前面", names.index("StashBackpack") < names.index("AutoEssence"))
check("只开存放背包和基质刷取（拆解基质哪怕点名也不开）", enabled(d2), ["StashBackpack", "AutoEssence"])
makeup.restore(cfg2)
check("顺序和开关都改回", master_of(root2), m2)

print("\n[补跑一天一次：没派下去不算一次，派下去了就算]")
day = f"{NOW:%Y-%m-%d}"
e = build(put_master(MASTER))
r = rec("MaaEnd", earlier, failed=THREE)
hold(e, r)
check("还没补过 → 压着", makeup.holding(e, r, NOW))
makeup._dispatch = lambda script: (dispatched.append(script), (False, "连不上 AUTO-MAS"))[1]
check("没派下去 → 下一轮再试", makeup.maybe_run(e, NOW), True)
mk = makeup.read_marker(e.cfg.state_dir, day)["MaaEnd"]
check("记成没能开跑", (mk["result"], mk["tries"]), (makeup.COULDNT_RUN, 1))
check("没能开跑不算补过 → 仍压着", makeup.holding(e, r, NOW))
check("没派下去就把母本改回", enabled(master_of(e.cfg.automas_dir)), enabled(MASTER))
check("两分钟内不再派", (makeup.maybe_run(e, NOW + timedelta(seconds=30)), len(dispatched)), (True, 1))
check("闹钟定在两分钟后", makeup.next_moment(e.cfg.state_dir, NOW)[0], NOW + timedelta(seconds=makeup.RETRY_GAP_S))
makeup._dispatch = lambda script: (dispatched.append(script), (True, f"脚本「{script}」已单独开跑"))[1]
t2 = NOW + timedelta(seconds=makeup.RETRY_GAP_S + 1)
check("过了两分钟再派，派下去了", makeup.maybe_run(e, t2), True)
mk = makeup.read_marker(e.cfg.state_dir, day)["MaaEnd"]
check("记成已派、第 2 次", (mk["result"], mk["tries"]), (makeup.DISPATCHED, 2))
check("补的是这三项", mk["tasks"], THREE)
check("先关了游戏", killed[-1:], ["Endfield.exe"])
check("母本只开这三项", enabled(master_of(e.cfg.automas_dir)), ["GiftOperator", "AutoEssence", "DailyRewards"])
check("不再借更新重跑的时刻（那会让整次开机后面的手动轮都不算手动）", hasattr(e, "_gu_rerun_at"), False)
check("派下去了 → 不再压着", makeup.holding(e, r, t2), False)
check("在跑 → 日报和关机都等它", makeup.in_flight(e.cfg.state_dir, t2), ["MaaEnd"])
check("再来一轮不会派第二次", (makeup.maybe_run(e, t2 + timedelta(seconds=5)), dispatched.count("MaaEnd")), (False, 2))
check("在跑的时候母本不改回", enabled(master_of(e.cfg.automas_dir)), ["GiftOperator", "AutoEssence", "DailyRewards"])

print("\n[补跑的记录落盘：走通 → 前面那几趟记成补跑做成了，母本改回]")
mr = rec("MaaEnd", t2 + timedelta(minutes=1), ok=True, raw={"tasks_done": THREE})
e._verify_outcome = lambda x: None
handle._weekly_gates = lambda eng, rec: None
handle._handle(e, mr)
mk = makeup.read_marker(e.cfg.state_dir, day)["MaaEnd"]
check("记成走通", mk["result"], makeup.OK)
check("母本改回原样", master_of(e.cfg.automas_dir), MASTER)
row = {x["run_id"]: x for x in e.state.read_ledger(day)}[r.run_id]
check("原来那趟记上补跑做成的时间", bool((row.get("raw") or {}).get("makeup_ok")))
check("压着的那条转成自愈（只记日志）", list(e._recovered), [("MaaEnd", "endfield")])
check("自愈那条只记日志", route_of(texts.self_healed("MaaEnd")), "log")
check("不在跑了", makeup.in_flight(e.cfg.state_dir, t2 + timedelta(minutes=2)), [])
title, body = core.format_daily(day, e.state.read_ledger(day))
check("日报标题是全绿", "全绿" in title and "失败" not in title)
check("补跑那一行", report.makeup_line(e.cfg.state_dir, day), "补跑：终末地 赠送干员礼物、基质刷取、日常奖励领取 → 走通")

print("\n[积压告警：补跑前压着不推，补跑后仍没成只进日报不进群]")
e = build()
m = rec("MAA", earlier, failed=["MAA 未能正确登录 PRTS"])
hold(e, m)
e._flush_pending()
check("补跑前：不推", e.notifier.sent, [])
check("补跑前：还压着", list(e._pending), [("MAA", "arknights")])
dispatched.clear()
n_killed = len(killed)
makeup.maybe_run(e)
check("明日方舟整个再跑一遍", (dispatched, makeup.read_marker(e.cfg.state_dir, day)["MAA"]["tasks"]), (["MAA"], ["整个 MAA"]))
check("明日方舟不关终末地", len(killed), n_killed)
m2r = rec("MAA", datetime.now(tz=SERVER_TZ) + timedelta(seconds=1), failed=["MAA 未能正确登录 PRTS"])
handle._handle(e, m2r)
check("补跑没成记成仍没成", makeup.read_marker(e.cfg.state_dir, day)["MAA"]["result"], makeup.FAILED)
e._flush_pending()
check("补跑后：不进群", alarms(e), [])
check("补跑后：什么都不推", e.notifier.sent, [])
check("补跑后：不再压着", dict(e._pending), {})
check("日报那一行", report.makeup_line(e.cfg.state_dir, day), "补跑：明日方舟 整个 MAA → 仍没成（MAA 未能正确登录 PRTS）")

print("\n[过了一天：昨天压着的直接放下，不推]")
e = build()
hold(e, rec("MaaEnd", NOW - timedelta(days=1), failed=THREE))
e._flush_pending()
check("不推", e.notifier.sent, [])
check("放下了", dict(e._pending), {})

print("\n[鸣潮照旧：最终失败照样进群]")
e = build()
hold(e, rec("OK-WW", earlier, failed=["OK-WW 运行超时"]))
e._flush_pending()
check("推了一条报警", len(alarms(e)), 1)

print("\n[终末地「这一轮没干完」：不进群；鸣潮照旧进群]")
for script, want_n in (("MaaEnd", 0), ("OK-WW", 1)):
    e = build()
    x = rec(script, earlier, ok=True)
    e.state.append_ledger(x)
    e._verify_outcome = lambda r: "有 1 项没干成"
    handle._handle_success(e, x, (x.script, x.user))
    check(f"{script} 推了 {want_n} 条「这一轮没干完」",
          len([t for t, _, a in e.notifier.sent if t == texts.ROUND_INCOMPLETE and a]), want_n)
    check(f"{script} 账本记了没干完", e.state.read_ledger(f"{earlier:%Y-%m-%d}")[0].get("incomplete"), "有 1 项没干成")

print("\n[自动采集补跑没走通、复发：不进群，日报那行带上]")
src = (Path(__file__).resolve().parents[1] / "ark_relay" / "collect_retry.py").read_text(encoding="utf-8")
check("collect_retry 里不再有 alert=True", "alert=True" in src, False)
check("补跑仍没走通：只记日志", route_of(texts.COLLECT_RETRY_FAILED), "log")
check("复发：只记日志", route_of(texts.COLLECT_RECURRENT), "log")
sd = tmpdir()
(sd / "collect-retry").mkdir()
(sd / "collect-retry" / f"{day}.json").write_text(json.dumps(
    {"passed": [], "failed": ["AutoCollectRoute15"], "unknown": [], "recurrent": ["AutoCollectRoute15"]}), encoding="utf-8")
check("日报那行说连续两天", "连续两天没走通 AutoCollectRoute15" in report.retry_line(sd, day))

print("\n[晚上 21:30 之后 MAA 失败：关机判断等补跑，不报「今晚不关机」]")
e = build()
e.cfg.shutdown_after_run = True
e._handled_any = True
e._started_at = NOW - timedelta(hours=3)
e.cfg.shutdown_min_uptime = 0
e._report_cutoff = lambda now: now - timedelta(minutes=5)
e._last_round_manual = lambda now, entries: False
hold(e, rec("MAA", earlier, failed=["MAA 未能正确登录 PRTS"]))
v = shutdown.decide(e, NOW)
check("判的是等补跑，不是「还有告警没推出去」", v.code, "makeup")
shutdown._say_if_moment_passed(e, NOW, v)
check("没有推「今晚不关机」", [t for t, _, a in e.notifier.sent if t == texts.NO_SHUTDOWN], [])
dispatched.clear()
e._maybe_makeup(NOW)
check("补跑派下去了", dispatched, ["MAA"])
check("派下去之后还是等补跑", shutdown.decide(e, NOW).code, "makeup")
e._scripts_running = lambda: True
v = shutdown.decide(e, NOW)
check("补跑跑着的时候也是等补跑，不是「还有脚本在跑」", v.code, "makeup")
shutdown._say_if_moment_passed(e, NOW, v)
check("补跑跑着也不推「今晚不关机」", [t for t, _, a in e.notifier.sent if t == texts.NO_SHUTDOWN], [])
e._scripts_running = lambda: False
e._report_cutoff = lambda now: now - timedelta(minutes=5)
e.state.append_ledger(rec("MAA", earlier - timedelta(minutes=1), ok=True, run_id=f"{day}/arknights/MAA-ok"))
report._maybe_daily_report(e, NOW)
check("日报等补跑出结果", e.state.report_sent(day), False)
stale = NOW + timedelta(minutes=makeup.STALE_MIN + 1)
check("一直没出记录：十分钟后有闹钟", makeup.next_moment(e.cfg.state_dir, NOW)[0], NOW + timedelta(minutes=makeup.STALE_MIN, seconds=1))
makeup.maybe_run(e, stale)
check("十分钟没跑出记录 → 收尾", makeup.read_marker(e.cfg.state_dir, day)["MAA"]["result"], makeup.NO_RECORD)
check("收尾后不再等", makeup.waiting(e, stale), [])
check("日报那一行", report.makeup_line(e.cfg.state_dir, day), f"补跑：明日方舟 整个 MAA → 派下去了，{makeup.STALE_MIN} 分钟没跑出记录")

print("\n[还有脚本在跑：不补]")
e = build()
hold(e, rec("MAA", earlier, failed=["x"]))
e._scripts_running = lambda: True
dispatched.clear()
check("在跑不派", (makeup.maybe_run(e, NOW), dispatched), (False, []))

print("\n[母本读不出来：记成放弃，不每轮报错，也不再压着]")
e = build(put_master(MASTER))
bad = rec("MaaEnd", earlier, failed=THREE)
hold(e, bad)
real_prepare = makeup._prepare_maaend
def boom(*a, **k):
    raise ValueError("Expecting value: line 1 column 1")
makeup._prepare_maaend = boom
dispatched.clear()
check("不派、不抛", (makeup.maybe_run(e, NOW), dispatched), (False, []))
mk = makeup.read_marker(e.cfg.state_dir, day)["MaaEnd"]
check("记成放弃，带原因", (mk["result"], "ValueError" in mk["note"]), (makeup.GAVE_UP, True))
check("不再压着", makeup.holding(e, bad, NOW), False)
e._flush_pending()
check("放下了也不进群", (alarms(e), dict(e._pending)), ([], {}))
check("日报那一行", report.makeup_line(e.cfg.state_dir, day).startswith("补跑：终末地 赠送干员礼物、基质刷取、日常奖励领取 → 没能开跑（母本读写出错"))
makeup._prepare_maaend = real_prepare

import subprocess as _real_sub   # noqa: E402
import time                      # noqa: E402


def mpath(root: Path) -> Path:
    return root / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"


def mk_of(e, script, d=None):
    return makeup.read_marker(e.cfg.state_dir, d or day).get(script) or {}


class Log:
    def __init__(self):
        self.lines = []

    def _rec(self, fmt, *a, **k):
        self.lines.append(fmt % a if a else fmt)

    info = warning = debug = error = _rec

    def exception(self, fmt, *a, **k):
        self.lines.append("EXC " + (fmt % a if a else fmt))


print("\n[补跑派下去之后，「有没有在跑」的三秒缓存作废：同一轮的关机判断重新问 AUTO-MAS]")
asked = []
real_os, real_busy, real_subp = eng_mod.os, eng_mod._automas_busy, eng_mod.subprocess
try:
    eng_mod.os = types.SimpleNamespace(name="nt")
    answer = {"v": False}
    eng_mod._automas_busy = lambda: (asked.append(1), answer["v"])[1]
    eng_mod.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(stdout=b""),
                                               SubprocessError=_real_sub.SubprocessError)
    eng_mod._SCRIPTS_CACHE.update(at=-1e9, val=False)
    check("派单前问了一次：没在跑", (eng_mod.Engine._scripts_running(), len(asked)), (False, 1))
    e = build()
    hold(e, rec("MAA", earlier, failed=["MAA 未能正确登录 PRTS"]))
    dispatched.clear()
    answer["v"] = True             # AUTO-MAS has started the make-up
    check("派下去了", (makeup.maybe_run(e, NOW), dispatched), (True, ["MAA"]))
    check("三秒内再问：不用旧的「没在跑」，重新问到「在跑」", (eng_mod.Engine._scripts_running(), len(asked)), (True, 2))
finally:
    eng_mod.os, eng_mod._automas_busy, eng_mod.subprocess = real_os, real_busy, real_subp
    eng_mod._SCRIPTS_CACHE.update(at=-1e9, val=False)

print("\n[明日方舟：只有「根本没开始干活」才整个再跑；开始干活了的不补，免得再吃一份理智药]")
LOGIN = ["MAA 未能正确登录 PRTS"]
for label, r_, want in (
        ("登录没成、记录里没打过仗 → 补", rec("MAA", earlier, failed=LOGIN), ""),
        ("模拟器起不来 → 补", rec("MAA", earlier, failed=["模拟器启动失败"]), ""),
        ("「部分任务执行失败」拿不准 → 不补", rec("MAA", earlier, failed=["MAA 部分任务执行失败"]), "x"),
        ("登录没成但记录里花过理智 → 不补", rec("MAA", earlier, failed=LOGIN, raw={"sanity_spent": 72}), "x"),
        ("登录没成但有掉落 → 不补", rec("MAA", earlier, failed=LOGIN, raw={"drop_statistics": {"龙门币": 864}}), "x"),
        ("吃过理智药 → 不补", rec("MAA", earlier, failed=LOGIN, raw={"medicine_used": 1}), "x"),
        ("没写失败项 → 不补", rec("MAA", earlier, failed=[""]), "x")):
    e = build()
    hold(e, r_)
    check(label, bool(makeup.maa_work_done(e, r_)), bool(want))
e = build()
first = rec("MAA", earlier - timedelta(minutes=30), failed=LOGIN,
            raw={"sanity_spent": 120, "medicine_used": 2}, run_id=f"{day}/arknights/MAA-a1")
last = rec("MAA", earlier, failed=LOGIN)
e.state.append_ledger(first)
hold(e, last)
check("同一轮前一次打过仗（AUTO-MAS 的第一次）→ 不补", "开始干活" in makeup.maa_work_done(e, last))
dispatched.clear()
check("不派", (makeup.maybe_run(e, NOW), dispatched), (False, []))
mk = mk_of(e, "MAA")
check("记成放弃，写明为什么不补", (mk.get("result"), mk.get("note", "").startswith("不补跑：")), (makeup.GAVE_UP, True))
check("不再压着", makeup.holding(e, last, NOW), False)
e._flush_pending()
check("放下了，不进群", (alarms(e), dict(e._pending)), ([], {}))
line = report.makeup_line(e.cfg.state_dir, day)
check("日报那一行说不补跑和原因", "→ 不补跑：" in line and "理智药" in line, True)
check("日报那一行没有英文字段名", [w for w in ("sanity", "medicine", "drop") if w in line], [])
e = build()
e.state.append_ledger(rec("MAA", earlier - timedelta(hours=3), ok=True, raw={"sanity_spent": 200},
                          run_id=f"{day}/arknights/MAA-morning"))
last2 = rec("MAA", earlier, failed=LOGIN)
hold(e, last2)
check("前一轮（走通的那轮）花的理智不算这一轮的 → 补", makeup.maa_work_done(e, last2), "")
dispatched.clear()
makeup.maybe_run(e, NOW)
check("派下去了", dispatched, ["MAA"])

print("\n[收窄记录原子写，收窄前先存一份完整母本；记录读不出来就用完整备份改回]")
root = put_master(MASTER)
text0 = mpath(root).read_text(encoding="utf-8")
cfg = types.SimpleNamespace(automas_dir=root, state_dir=tmpdir(), maaend_dir=FX)
nf, bf = cfg.state_dir / "makeup" / "narrow.json", cfg.state_dir / "makeup" / "master-backup.json"
written = []
real_aw = makeup.atomic_write_text
makeup.atomic_write_text = lambda path, data: (written.append(Path(path).name), real_aw(path, data))[1]
makeup.narrow_master(cfg, ["GiftOperator"], "run-b", NOW)
makeup.atomic_write_text = real_aw
check("先完整备份，再收窄记录，再母本，都走原子写", written, ["master-backup.json", "narrow.json", "mxu-MaaEnd.json"])
check("完整备份逐字节是原来的母本", bf.read_text(encoding="utf-8") == text0)
nf.write_text("{坏的", encoding="utf-8")
back, err = makeup.try_restore(cfg)
check("用完整备份改回", ("完整备份" in back, err), (True, ""))
check("母本逐字节回到原样", mpath(root).read_text(encoding="utf-8") == text0)
check("两份都清掉", (nf.exists(), bf.exists()), (False, False))

print("\n[收窄记录和完整备份都读不出来：推一条真报警（只推一次），之后不再收窄，等人看]")
makeup.narrow_master(cfg, ["GiftOperator"], "run-c", NOW)
nf.write_text("{坏", encoding="utf-8")
bf.write_text("坏", encoding="utf-8")
notes = Notes()
back, err = makeup.try_restore(cfg, notes)
check("改不回，说明原因", (back, "都读不出来" in err), ("", True))
check("推了一条真报警", [(t, a) for t, _, a in notes.sent], [(texts.MAKEUP_RESTORE_FAILED, True)])
check("报警进群", route_of(texts.MAKEUP_RESTORE_FAILED, alert=True), "group")
check("正文是人话、带文件路径（Windows 路径的人话检查在 test_texts_gate）",
      ("自动改回失败，需要人看一下" in notes.sent[0][1], str(nf) in notes.sent[0][1]), (True, True))
makeup.try_restore(cfg, notes)
makeup.restore(cfg, Notes())
check("只推一次", len(notes.sent), 1)
check("记下了要人看", makeup.restore_broken(cfg.state_dir))
check("之后不再收窄", makeup.narrow_master(cfg, ["AutoEssence"], "run-d", NOW), "")
check("母本没被再改", enabled(master_of(root)), ["GiftOperator"])
e = build(root)
e.cfg.state_dir = cfg.state_dir
bad = rec("MaaEnd", earlier, failed=THREE)
hold(e, bad)
dispatched.clear()
check("这时有终末地失败：补跑不派", (makeup.maybe_run(e, NOW), dispatched), (False, []))
mk = mk_of(e, "MaaEnd")
check("记成放弃，写明设置没改回", (mk.get("result"), "没能改回" in mk.get("note", "")), (makeup.GAVE_UP, True))
check("不再压着、关机不等它", (makeup.holding(e, bad, NOW), makeup.waiting(e, NOW)), (False, []))
check("报警没有再推", alarms(e), [])
nf.unlink()
makeup.restore(cfg)
check("人删掉那份记录后，补跑恢复", makeup.restore_broken(cfg.state_dir), False)

print("\n[母本本身读不出来：不抛，说明原因，收窄记录留着下次再改回]")
root5 = put_master(MASTER)
cfg5 = types.SimpleNamespace(automas_dir=root5, state_dir=tmpdir(), maaend_dir=FX)
makeup.narrow_master(cfg5, ["GiftOperator"], "run-e", NOW)
mpath(root5).write_text("{坏", encoding="utf-8")
back, err = makeup.try_restore(cfg5)
check("没改回、有原因、记录留着", (back, "读写不成" in err, (cfg5.state_dir / "makeup" / "narrow.json").exists()),
      ("", True, True))
mpath(root5).write_text(json.dumps(MASTER, ensure_ascii=False), encoding="utf-8")
real_unlink = Path.unlink
Path.unlink = lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(13, "文件被占用"))
try:
    back, err = makeup.try_restore(cfg5)
finally:
    Path.unlink = real_unlink
check("改回后删记录时文件被占用：不抛，带原因（调用方不会记 ERROR 进群）",
      (back, "PermissionError" in err), ("", True))

print("\n[开头改回母本时出错：当天终末地补跑记成放弃，关机和日报不等到半夜]")
e = build(put_master(MASTER))
r5 = rec("MaaEnd", earlier, failed=THREE)
hold(e, r5)
real_try = makeup.try_restore
def _locked(cfg, notifier=None):
    raise OSError("文件被占用")
makeup.try_restore = _locked
try:
    check("不抛、不派", makeup.maybe_run(e, NOW), False)
finally:
    makeup.try_restore = real_try
mk = mk_of(e, "MaaEnd")
check("记成放弃，带原因", (mk.get("result"), "文件被占用" in mk.get("note", "")), (makeup.GAVE_UP, True))
check("关机不再等终末地补跑", makeup.waiting(e, NOW), [])
check("不再压着", makeup.holding(e, r5, NOW), False)
check("没有闹钟（不会一直等）", makeup.next_moment(e.cfg.state_dir, NOW), None)

print("\n[跨午夜：23:55 派的补跑，00:02 还算在跑，不去改回；零点后开始的记录记进昨天那份]")
mid = NOW.replace(hour=0, minute=2)
y_disp = mid - timedelta(minutes=7)
yday = f"{y_disp:%Y-%m-%d}"
root6 = put_master(MASTER)
e = build(root6)
y_rec = rec("MaaEnd", y_disp - timedelta(hours=1), failed=THREE)
e.state.append_ledger(y_rec)
WANT3 = ["GiftOperator", "AutoEssence", "DailyRewards"]
makeup.narrow_master(e.cfg, WANT3, y_rec.run_id, y_disp)
makeup._write_marker(e.cfg.state_dir, yday, {"MaaEnd": {"dispatched_at": y_disp.isoformat(), "result": makeup.DISPATCHED,
                                                       "tries": 1, "run_id": y_rec.run_id, "tasks": THREE}})
check("过了零点还算在跑", makeup.in_flight(e.cfg.state_dir, mid), ["MaaEnd"])
check("闹钟也看昨天那份", makeup.next_moment(e.cfg.state_dir, mid)[0],
      y_disp + timedelta(minutes=makeup.STALE_MIN, seconds=1))
makeup.maybe_run(e, mid)
check("在跑的时候不改回", enabled(master_of(root6)), WANT3)
e._script_running = lambda name: name == "MaaEnd"
makeup.maybe_run(e, mid + timedelta(minutes=9))
check("看到在跑，记在昨天那份里", bool(mk_of(e, "MaaEnd", yday).get("seen_running_at")))
check("仍算在跑", makeup.in_flight(e.cfg.state_dir, mid + timedelta(minutes=15)), ["MaaEnd"])
r_mid = rec("MaaEnd", mid + timedelta(minutes=1), ok=True)
makeup.on_record(e, r_mid)
check("零点后开始的记录也记进昨天那份", mk_of(e, "MaaEnd", yday).get("result"), makeup.OK)
row = {x["run_id"]: x for x in e.state.read_ledger(yday)}[y_rec.run_id]
check("昨天那条失败记上补跑做成", bool((row.get("raw") or {}).get("makeup_ok")))
e = build()
makeup._write_marker(e.cfg.state_dir, yday, {"MaaEnd": {"dispatched_at": y_disp.isoformat(),
                                                       "result": makeup.DISPATCHED, "tries": 1}})
makeup.maybe_run(e, mid + timedelta(minutes=20))
check("过了零点一直没跑出记录：照样收尾", mk_of(e, "MaaEnd", yday).get("result"), makeup.NO_RECORD)

print("\n[开机改回：补跑还在跑（中继重启、机器没关）就不改回；AUTO-MAS 问不到或已跑完就照旧改回]")
class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()
class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any
for _n in ("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
           "servicemanager", "win32process", "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(_n, _Stub(_n))
import boot_stages                                    # noqa: E402
from ark_relay import collect_retry, gameupdate, mastercfg   # noqa: E402
saved_fns = (gameupdate.maaend_reenable_if_updated, gameupdate.maaend_reenable_next_boot,
             gameupdate.maaend_reenable_spmed_if_updated, mastercfg.prune_maaend_orphans,
             mastercfg.migrate_maaend_options, collect_retry.restore_master, eng_mod._automas_snapshot)
gameupdate.maaend_reenable_if_updated = gameupdate.maaend_reenable_next_boot = \
    gameupdate.maaend_reenable_spmed_if_updated = lambda cfg: ""
mastercfg.prune_maaend_orphans = mastercfg.migrate_maaend_options = lambda a, b: (0, "")
collect_retry.restore_master = lambda cfg: ""
try:
    for label, snap, ago, restored in (
            ("补跑 2 分钟前派出、AUTO-MAS 说终末地还在跑 → 不改回",
             {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}, 2, False),
            ("AUTO-MAS 说终末地跑完了 → 改回",
             {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "完成"}]}]}, 2, True),
            ("AUTO-MAS 问不到（刚开机）→ 改回", None, 2, True),
            ("补跑是 30 分钟前派的、早没动静 → 改回",
             {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}, 30, True)):
        root7 = put_master(MASTER)
        cfg7 = types.SimpleNamespace(automas_dir=root7, state_dir=tmpdir(), maaend_dir=FX)
        now7 = datetime.now(tz=SERVER_TZ)
        makeup.narrow_master(cfg7, ["GiftOperator"], "run-f", now7)
        makeup._write_marker(cfg7.state_dir, f"{now7 - timedelta(minutes=ago):%Y-%m-%d}",
                             {"MaaEnd": {"dispatched_at": (now7 - timedelta(minutes=ago)).isoformat(),
                                         "result": makeup.DISPATCHED, "tries": 1}})
        eng_mod._automas_snapshot = lambda snap=snap: snap
        boot_stages._stage_reenable_maaend(cfg7, Notes(), Log())
        check(label, master_of(root7) == MASTER, restored)
finally:
    (gameupdate.maaend_reenable_if_updated, gameupdate.maaend_reenable_next_boot,
     gameupdate.maaend_reenable_spmed_if_updated, mastercfg.prune_maaend_orphans,
     mastercfg.migrate_maaend_options, collect_retry.restore_master, eng_mod._automas_snapshot) = saved_fns

print("\n[补跑算中继自己派的：commands.run_script 记下「脚本 MaaEnd」，关机判断读它，不靠更新重跑的时刻]")
from ark_relay import commands, trigger   # noqa: E402
sd8 = tmpdir()
old_env = os.environ.get("ARK_STATE_DIR")
os.environ["ARK_STATE_DIR"] = str(sd8)
real_mas = commands._mas
commands._mas = lambda path, body=None, timeout=20: (
    {"data": {"sid1": {"Info": {"Name": "MaaEnd"}}}} if path == "/api/scripts/get" else {"status": "success"})
try:
    ok8, _ = commands.run_script("MaaEnd")
finally:
    commands._mas = real_mas
    os.environ["ARK_STATE_DIR"] = old_env
notes8 = trigger._read_dispatches(sd8)
check("派下去了，记下是中继派的", (ok8, [d["what"] for d in notes8]), (True, ["脚本 MaaEnd"]))
at8 = datetime.fromisoformat(notes8[0]["at"])
e = build()
e.cfg.state_dir = sd8
e._round_is_manual = lambda group: True          # by the schedule alone the make-up's round reads as manual
rows = [{"run_id": "m", "script": "MAA", "user": "arknights", "ok": True,
         "started": (at8 - timedelta(hours=4)).isoformat(), "finished": (at8 - timedelta(hours=3, minutes=45)).isoformat()},
        {"run_id": "mk", "script": "MaaEnd", "user": "endfield", "ok": True,
         "started": (at8 + timedelta(minutes=3)).isoformat(), "finished": (at8 + timedelta(minutes=20)).isoformat()}]
check("隔了几小时的补跑那一轮：不算手动", shutdown._last_round_manual(e, at8 + timedelta(minutes=25), rows), False)
check("引擎上没有更新重跑的时刻", getattr(e, "_gu_rerun_at", None), None)
later = rows + [{"run_id": "h", "script": "MaaEnd", "user": "endfield", "ok": True,
                 "started": (at8 + timedelta(hours=3)).isoformat(), "finished": (at8 + timedelta(hours=3, minutes=20)).isoformat()}]
check("补跑之后有人手动再跑一趟：仍算手动（不被补跑连带）",
      shutdown._last_round_manual(e, at8 + timedelta(hours=4), later), True)

print("\n[补跑的结果只认它自己的记录：走通就定了；没成时只有 AUTO-MAS 紧跟着的重试能改；晚班改不了]")
def booked(seq, start_result=makeup.DISPATCHED):
    e = build()
    ent = {"dispatched_at": NOW.isoformat(), "result": start_result, "tries": 1, "tasks": ["整个 MAA"]}
    makeup._write_marker(e.cfg.state_dir, day, {"MAA": ent})
    out = []
    for r_ in seq:
        makeup.on_record(e, r_)
        out.append(mk_of(e, "MAA").get("result"))
    return out
a1 = rec("MAA", NOW + timedelta(minutes=1), failed=LOGIN)
a2 = rec("MAA", a1.finished + timedelta(seconds=5), ok=True)
eve_fail = rec("MAA", NOW + timedelta(hours=5), failed=["MAA 部分任务执行失败"])
eve_ok = rec("MAA", NOW + timedelta(hours=5), ok=True)
check("第一次没成、AUTO-MAS 紧跟着重试走通 → 走通", booked([a1, a2]), [makeup.FAILED, makeup.OK])
check("走通之后晚班失败 → 仍是走通", booked([a2, eve_fail]), [makeup.OK, makeup.OK])
check("没成之后晚班走通 → 仍是没成", booked([a1, eve_ok]), [makeup.FAILED, makeup.FAILED])
check("同一条记录来两次不重复改", booked([a1, a1]), [makeup.FAILED, makeup.FAILED])
check("十分钟没跑出记录后，晚班的记录不算它的", booked([eve_ok], makeup.NO_RECORD), [makeup.NO_RECORD])

print("\n[没有 id 的任务：按名字和位置存原状，收窄时一起关、照样挪位置，改回一模一样]")
m3 = copy.deepcopy(MASTER)
t3 = m3["instances"][0]["tasks"]
t3.insert(3, {"taskName": "VisitFriends", "enabled": True})
t3.insert(5, {"taskName": "SellProduct", "enabled": True, "enabledByController": {"Win32-Front": True}})
t3.append({"taskName": "StashBackpack", "enabled": False})
root3 = put_master(m3)
cfg3 = types.SimpleNamespace(automas_dir=root3, state_dir=tmpdir(), maaend_dir=FX)
check("收窄成了", bool(makeup.narrow_master(cfg3, ["StashBackpack", "AutoEssence"], "run-g", NOW)))
d3 = master_of(root3)
noid = [t for t in d3["instances"][0]["tasks"] if "id" not in t]
check("没 id 的也关掉（存放背包除外）", [(t["taskName"], t["enabled"]) for t in noid],
      [("VisitFriends", False), ("SellProduct", False), ("StashBackpack", True)])
check("没 id 的控制器开关也跟着关", noid[1]["enabledByController"], {"Win32-Front": False})
names3 = [t["taskName"] for t in d3["instances"][0]["tasks"]]
check("没 id 的存放背包挪到基质刷取前面", names3.index("StashBackpack") < names3.index("AutoEssence"))
check("开着的只有这两项", enabled(d3), ["StashBackpack", "AutoEssence"])
makeup.restore(cfg3)
check("改回和原来一模一样（顺序、开关、没有的键）", master_of(root3), m3)
makeup._dispatch, makeup._kill_game = real_dispatch, real_kill
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
