"""D206: a game that got nothing done all day goes to the group once.

Since 2026-10-05 MAA / MaaEnd failures go to the daily report only (the user,
13:07: 「中继我就要求一个，他不要再报错了」), after one make-up run (makeup.py).
D206 (主持定) keeps one exception: the same game on the same Beijing day, once
every shift that was due has run and the make-up is over, still without a
single good run (ok and not 「没干完」) -> one alarm, then nothing more about
that game that day. Pinned here, against a queue config shaped like AUTO-MAS's
own (早班 09:00 MAA + MaaEnd, 晚班 21:30 MAA):

* 早班 failed, 晚班 still to come -> wait; 晚班 went through -> no alarm;
* both shifts and the make-up failed -> one alarm, a second tick says nothing;
* MaaEnd (only 早班) failed and so did its make-up -> one alarm, with the
  evidence link of the last failure;
* any good run, or the make-up booked as passed -> no alarm;
* a held failure, a make-up still running, a script still running -> wait;
* runs a person started at AUTO-MAS or stopped with the red button are neither
  due nor good; maintenance / could not enter is not a day of failures;
* days do not mix: yesterday's failures never count for today, yesterday's
  alarm does not silence today's, and yesterday is judged only after midnight
  for a make-up that ran past it;
* a push that did not go out is tried again on the next tick.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import dayfail, makeup, texts                    # noqa: E402
from ark_relay import engine as eng_mod                         # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord       # noqa: E402
from ark_relay.core import State                                # noqa: E402
from ark_relay.notify import route_of                           # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def automas_dir(queues) -> Path:
    """An AUTO-MAS config dir: queues = [(name, [times], [script kinds])]."""
    root = tmpdir()
    (root / "config").mkdir()
    paths = {"MAA": r"D:\ark\MAA", "MaaEnd": r"D:\ark\MaaEnd", "OK-WW": r"D:\ark\okww"}
    sc = {"instances": [{"uid": f"s-{k}"} for k in paths]}
    for k, p in paths.items():
        sc[f"s-{k}"] = {"Info": {"Name": k, "Path": p}}
    qc = {"instances": []}
    for n, (name, times, kinds) in enumerate(queues):
        uid = f"q{n}"
        qc["instances"].append({"uid": uid})
        ts = {"instances": []}
        for i, t in enumerate(times):
            ts[f"t{i}"] = {"Info": {"Enabled": True, "Time": t}}
        items = {"instances": []}
        for i, k in enumerate(kinds):
            items[f"i{i}"] = {"Info": {"ScriptId": f"s-{k}"}}
        qc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                   "SubConfigsInfo": {"TimeSet": ts, "QueueItem": items}}
    (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
    (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
    return root


AUTOMAS = automas_dir([("早班", ["09:00"], ["MAA", "MaaEnd", "OK-WW"]), ("晚班", ["21:30"], ["MAA"])])
DAY = datetime(2026, 10, 5, tzinfo=SERVER_TZ)


def at(hh, mm=0, day=DAY):
    return day.replace(hour=hh, minute=mm)


class Notes:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, title, body="", **kw):
        if self.fail:
            return ["企业微信机器人：发不出去"]
        self.sent.append((title, body, kw.get("alert", False)))
        return []


class Src:
    def fetch(self, seen):
        return []


def build(notes=None, automas=AUTOMAS):
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.automas_dir = automas
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=notes or Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    return e


def run(e, script, started, ok=False, failed=None, raw=None, incomplete=""):
    user = {"MAA": "arknights", "MaaEnd": "endfield"}[script]
    r = RunRecord(run_id=f"{started:%Y-%m-%d}/{user}/{script}-{started:%H-%M-%S}", script=script, user=user,
                  started=started, finished=started + timedelta(minutes=20), ok=ok,
                  failed_tasks=list(failed if failed is not None else ([] if ok else ["开始唤醒"])),
                  raw=dict(raw or {}))
    e.state.append_ledger(r)
    if incomplete:
        e.state.mark_incomplete(f"{started:%Y-%m-%d}", r.run_id, incomplete)
    return r


def marker(e, day, script, result, note=""):
    m = makeup.read_marker(e.cfg.state_dir, day)
    m[script] = {"result": result, "note": note, "dispatched_at": at(10).isoformat(), "tries": 1}
    makeup._write_marker(e.cfg.state_dir, day, m)


def alarms(e):
    return [(t, b) for t, b, a in e.notifier.sent if a]


print("[班次从 AUTO-MAS 的队列配置读：明日方舟早晚两班，终末地只有早班]")
e = build()
check("明日方舟两班", [(t.strftime("%H:%M"), n) for t, n in dayfail.shifts(AUTOMAS, e.cfg.state_dir, "MAA", "2026-10-05")],
      [("09:00", "早班"), ("21:30", "晚班")])
check("终末地一班", [(t.strftime("%H:%M"), n) for t, n in dayfail.shifts(AUTOMAS, e.cfg.state_dir, "MaaEnd", "2026-10-05")],
      [("09:00", "早班")])
check("读不到配置就是没有班次", dayfail.shifts(None, e.cfg.state_dir, "MAA", "2026-10-05"), [])

print("\n[只早班失败、晚班成功：不报]")
e = build()
run(e, "MAA", at(9))
run(e, "MAA", at(10, 30))                       # the make-up, failed too
marker(e, "2026-10-05", "MAA", makeup.FAILED, "开始唤醒")
check("中午：晚班还没到，等", dayfail.judge(e, "MAA", "2026-10-05", at(12)), ("", "后面还有班次"))
check("中午 tick 不报", e._day_failed_alarm(at(12)), 0)
check("21:40 晚班还没出记录，等", dayfail.judge(e, "MAA", "2026-10-05", at(21, 40))[1], "最后一班还没出记录")
run(e, "MAA", at(21, 30), ok=True)
check("晚班成功后不报", e._day_failed_alarm(at(22, 30)), 0)
check("群里什么都没有", alarms(e), [])

print("\n[两班和补跑都失败：报一次，再来一轮不报]")
e = build()
run(e, "MAA", at(9))
run(e, "MAA", at(10, 30))
marker(e, "2026-10-05", "MAA", makeup.FAILED, "开始唤醒")
run(e, "MAA", at(21, 30), failed=["开始唤醒"], raw={"evidence_page": "https://gofile.io/d/evening"})
check("一条进群", e._day_failed_alarm(at(22, 30)), 1)
got = alarms(e)
check("标题", got[0][0] if got else "", "❌ 明日方舟一整天一趟都没跑成")
check("走群", route_of(got[0][0], alert=True) if got else "", "group")
check("正文", got[0][1] if got else "",
      "明日方舟今天一趟都没跑成（早班、晚班、补跑都没成），要人看一下：失败于：开始唤醒\n\n"
      "证据包：https://gofile.io/d/evening")
check("文案是人话", texts.plain(got[0][1].split("证据包")[0]) if got else ["没发"], [])
check("再来一轮不报", e._day_failed_alarm(at(22, 40)), 0)
run(e, "MAA", at(23), failed=["别的失败"])
check("当天再失败一次也不报", e._day_failed_alarm(at(23, 30)), 0)
check("总共一条", len(alarms(e)), 1)
check("记在当天的报警记录里", e._already_alerted("2026-10-05", "全天|MAA"), True)

print("\n[终末地早班 + 补跑失败：报一次，带证据包]")
e = build()
run(e, "MaaEnd", at(9), failed=["基质刷取"], raw={"evidence_page": "https://gofile.io/d/endfield"})
check("补跑还没派：等", dayfail.judge(e, "MaaEnd", "2026-10-05", at(9, 40))[1], "补跑还没结束")
marker(e, "2026-10-05", "MaaEnd", makeup.DISPATCHED)
m = makeup.read_marker(e.cfg.state_dir, "2026-10-05")
m["MaaEnd"]["dispatched_at"] = at(10).isoformat()
makeup._write_marker(e.cfg.state_dir, "2026-10-05", m)
check("补跑在跑：等", dayfail.judge(e, "MaaEnd", "2026-10-05", at(10, 5))[1], "补跑还没结束")
run(e, "MaaEnd", at(10, 1), failed=["基质刷取"])
marker(e, "2026-10-05", "MaaEnd", makeup.FAILED, "基质刷取")
check("一条进群", e._day_failed_alarm(at(10, 30)), 1)
got = alarms(e)
check("正文", got[0][1] if got else "",
      "终末地今天一趟都没跑成（早班、补跑都没成），要人看一下：失败于：基质刷取\n\n"
      "证据包：https://gofile.io/d/endfield")
check("明日方舟那边没跟着报", [t for t, _ in got], ["❌ 终末地一整天一趟都没跑成"])
check("再来一轮不报", e._day_failed_alarm(at(11)), 0)

print("\n[有一趟成功：不报]")
e = build()
run(e, "MaaEnd", at(9))
marker(e, "2026-10-05", "MaaEnd", makeup.OK)          # its record sits in tomorrow's ledger
check("补跑走通就算成", dayfail.judge(e, "MaaEnd", "2026-10-05", at(12)), ("", "有一趟跑成了"))
e = build()
run(e, "MAA", at(9), ok=True)
run(e, "MAA", at(21, 30))
check("早班成功、晚班失败", e._day_failed_alarm(at(22, 30)), 0)
e = build()
run(e, "MAA", at(9), ok=True, incomplete="· 理智没刷完")
run(e, "MAA", at(21, 30), ok=True, incomplete="· 理智没刷完")
check("两趟都「没干完」不算成功：报", e._day_failed_alarm(at(22, 30)), 1)
check("原因写没干完", "跑完了但没干完：· 理智没刷完" in alarms(e)[0][1], True)
check("这类不补跑：括号里只写两班", "（早班、晚班都没成）" in alarms(e)[0][1], True)

print("\n[还没定下来的：等]")
e = build()
r = run(e, "MaaEnd", at(9))
e._pending[(r.script, r.user)] = r
check("失败还压着", dayfail.judge(e, "MaaEnd", "2026-10-05", at(12))[1], "还有失败压着等重试或补跑")
e._pending.clear()
marker(e, "2026-10-05", "MaaEnd", makeup.FAILED)
e._script_running = lambda name: name == "MaaEnd"
check("还在跑", dayfail.judge(e, "MaaEnd", "2026-10-05", at(12))[1], "还在跑")
e._script_running = lambda name: False
check("都定了：报", bool(dayfail.judge(e, "MaaEnd", "2026-10-05", at(12))[0]), True)
e = build(automas=None)
run(e, "MaaEnd", at(9))
marker(e, "2026-10-05", "MaaEnd", makeup.FAILED)
check("读不到班次：不报", dayfail.judge(e, "MaaEnd", "2026-10-05", at(12))[1], "读不到这一天该跑的班次")

print("\n[手动开的、红按钮停的：不算该跑的，也不算成功；维护不算一天的失败]")
e = build()
run(e, "MaaEnd", at(9))
marker(e, "2026-10-05", "MaaEnd", makeup.FAILED)
run(e, "MaaEnd", at(11), ok=True, raw={"hand_started": "task-1"})
run(e, "MaaEnd", at(11, 30), ok=True, raw={"manual_stop": "11:40 停一切"})
check("手动跑成的不算成功：照报", e._day_failed_alarm(at(12)), 1)
e = build()
run(e, "MaaEnd", at(9), ok=True, raw={"hand_started": "task-1"}, failed=[])
run(e, "MaaEnd", at(9, 30), raw={"hand_started": "task-1"})
check("只有手动开的失败：不报", dayfail.judge(e, "MaaEnd", "2026-10-05", at(12)), ("", "没有算数的失败"))
e = build()
run(e, "MaaEnd", at(9), raw={"maintenance": "维护到 11:00"})
check("维护进不了游戏：不报", e._day_failed_alarm(at(12)), 0)
e = build()
run(e, "MaaEnd", at(9), failed=["自动采集"])
check("只有自动采集没做成：不报", e._day_failed_alarm(at(12)), 0)

print("\n[跨天不串]")
e = build()
y = DAY - timedelta(days=1)
run(e, "MAA", at(9, day=y))
run(e, "MAA", at(21, 30, day=y))
marker(e, "2026-10-04", "MAA", makeup.FAILED)
run(e, "MAA", at(9))
marker(e, "2026-10-05", "MAA", makeup.FAILED)
run(e, "MAA", at(21, 30), ok=True)
check("今天晚班成了：昨天的失败不算到今天", dayfail.judge(e, "MAA", "2026-10-05", at(22, 30)), ("", "有一趟跑成了"))
check("早上 6 点以后不再回头报昨天", e._day_failed_alarm(at(22, 30)), 0)
check("凌晨还会判昨天（补跑跑过了零点）", e._day_failed_alarm(at(0, 30) + timedelta(days=1)), 0)
e = build()
run(e, "MAA", at(9, day=y))
run(e, "MAA", at(21, 30, day=y))
marker(e, "2026-10-04", "MAA", makeup.FAILED)
check("零点半：昨天两班 + 补跑都没成，报昨天", e._day_failed_alarm(at(0, 30)), 1)
check("正文写日期不写今天", alarms(e)[0][1].startswith("明日方舟10-04一趟都没跑成"), True)
check("记在昨天名下", (e._already_alerted("2026-10-04", "全天|MAA"), e._already_alerted("2026-10-05", "全天|MAA")),
      (True, False))
run(e, "MAA", at(9))
marker(e, "2026-10-05", "MAA", makeup.FAILED)
run(e, "MAA", at(21, 30))
check("今天又全天没成：昨天报过不挡今天", e._day_failed_alarm(at(22, 30)), 1)
check("两天各一条", len(alarms(e)), 2)

print("\n[推不出去：不记已报，下一轮再试]")
notes = Notes(fail=True)
e = build(notes)
run(e, "MaaEnd", at(9))
marker(e, "2026-10-05", "MaaEnd", makeup.FAILED)
check("没推出去", e._day_failed_alarm(at(12)), 0)
check("没记已报", e._already_alerted("2026-10-05", "全天|MaaEnd"), False)
notes.fail = False
check("下一轮推出去", e._day_failed_alarm(at(12, 5)), 1)


print("\n[整条路走一遍：失败压着 → 补跑派下去 → 放下不进群 → 补跑的记录也没成 → 这时才报一次]")
from ark_relay import handle  # noqa: E402
handle._ship_evidence = lambda eng, rec: ""
makeup._dispatch = lambda script: (True, "已开跑")
TODAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
NOON = TODAY.replace(hour=12)
e = build(automas=automas_dir([("早班", ["09:00"], ["MAA"])]))
r1 = RunRecord(run_id=f"{TODAY:%Y-%m-%d}/arknights/MAA-09-00-00", script="MAA", user="arknights",
               started=TODAY.replace(hour=9), finished=TODAY.replace(hour=9, minute=2), ok=False,
               failed_tasks=["开始唤醒"], raw={})
handle._handle(e, r1)
e._flush_pending()
check("早班失败压着", list(e._pending), [("MAA", "arknights")])
check("压着时不报", e._day_failed_alarm(NOON), 0)
check("补跑派下去", makeup.maybe_run(e, NOON), True)
e._flush_pending()
check("补跑派下去后放下，不进群", (dict(e._pending), alarms(e)), ({}, []))
check("补跑在跑：不报", e._day_failed_alarm(NOON + timedelta(minutes=1)), 0)
r2 = RunRecord(run_id=f"{TODAY:%Y-%m-%d}/arknights/MAA-12-01-00", script="MAA", user="arknights",
               started=NOON + timedelta(minutes=1), finished=NOON + timedelta(minutes=3), ok=False,
               failed_tasks=["开始唤醒"], raw={})
handle._handle(e, r2)
check("补跑记成没成", makeup.read_marker(e.cfg.state_dir, f"{TODAY:%Y-%m-%d}")["MAA"]["result"], makeup.FAILED)
e._flush_pending()
check("补跑的失败也只进日报", alarms(e), [])
check("这时报一次", e._day_failed_alarm(NOON + timedelta(minutes=10)), 1)
check("正文", alarms(e)[0][1], "明日方舟今天一趟都没跑成（早班、补跑都没成），要人看一下：失败于：开始唤醒")
check("再来一轮不报", e._day_failed_alarm(NOON + timedelta(minutes=20)), 0)

print("\n[engine.tick 里这一步在补跑之后、日报和关机之前]")
import inspect  # noqa: E402
src = inspect.getsource(eng_mod.Engine.tick)
check("顺序", src.index('"补跑"') < src.index('"全天没成"') < src.index('"日报"') < src.index('"关机"'), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
