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
check("算作中继自己派的，不当手动", e._gu_rerun_at, t2)
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

makeup._dispatch, makeup._kill_game = real_dispatch, real_kill
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
