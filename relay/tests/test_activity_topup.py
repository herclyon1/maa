"""A waveplate-short daily activity is topped up by the evening shift (features/makeup/activity.py).

2026-10-23: OK-WW started the morning with 98/240 waveplates and no backup (he had spent them
himself), spent 80, and the daily stopped at 80 points; the group got 「⚠️ 这一轮没干完」. He:
「中继不报警但是要在群里说一声今天早班没满活跃，晚班补。如果连晚班都没满就报警。」 The lines below
are that morning's own (ok-script.log 09:28:40-09:29:22); the queues are the machine's (早班
09:00, 晚班 21:30, AUTO-MAS v5.8 YAML).
"""
import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.makeup import activity, makeup
from ark_relay.features.verify import outcome
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


MORNING = """\
2026-10-23 09:28:35,899 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 99 >= 80
2026-10-23 09:28:40,123 INFO TaskExecutor BaseWWTask:current stamina: 19 not enough to continue
2026-10-23 09:28:44,124 INFO TaskExecutor ForgeryTask:used all stamina
2026-10-23 09:29:13,332 INFO TaskExecutor DailyTask:活跃奖励：活跃度 80
2026-10-23 09:29:22,684 INFO TaskExecutor DailyTask:活跃奖励：领完核对通过（活跃度 80，已领 20、40、60、80，各档对勾分 20:0.97，40:0.93，60:0.98，80:0.96，100:0.49）
"""
QUEUES = """\
order:
- uid: q1
  type: QueueConfig
- uid: q2
  type: QueueConfig
data:
  q1:
    Info:
      Name: 早班
      TimeEnabled: true
    TimeSet:
      order:
      - uid: t1
        type: TimeSet
      data:
        t1:
          Info:
            Enabled: true
            Time: '2000-01-01T01:00:00Z'
    QueueItem:
      order:
      - uid: i1
        type: QueueItem
      data:
        i1:
          Info:
            ScriptId: okww
  q2:
    Info:
      Name: 晚班
      TimeEnabled: true
    TimeSet:
      order:
      - uid: t2
        type: TimeSet
      data:
        t2:
          Info:
            Enabled: true
            Time: '2000-01-01T13:30:00Z'
    QueueItem:
      order:
      - uid: i2
        type: QueueItem
      data:
        i2:
          Info:
            ScriptId: maa
"""


def at(hh, mm):
    return datetime(2026, 10, 23, hh, mm, tzinfo=SERVER_TZ)


def setup():
    root = tmpdir()
    (root / "config").mkdir()
    (root / "config" / "queues.yaml").write_text(QUEUES, encoding="utf-8")
    group = []
    eng = types.SimpleNamespace(
        cfg=types.SimpleNamespace(state_dir=tmpdir(), automas_dir=root),
        notifier=types.SimpleNamespace(
            send_group=lambda t, b: (group.append((t, b)), [])[1],
            send=lambda t, b, alert=False: (group.append(("ALARM " + t if alert else t, b)), [])[1]))
    return eng, group


def rec(run_id, start, end):
    return types.SimpleNamespace(script="OK-WW", run_id=run_id, started=start, finished=end)


print("[早班：波片用完、活跃 80 → 不报警，群里说一声，记下晚班 21:30 补]")
eng, group = setup()
checks = outcome.daily_reward_checks(MORNING)
check("没改之前：活跃这一项是没干完", [c.ok for c in checks if c.label == activity.LABEL], [False])
activity.morning(eng, rec("OK-WW-05-16-50", at(9, 18), at(9, 30)), MORNING, checks)
item = next(c for c in checks if c.label == activity.LABEL)
check("这一项不再算没干完（不进「这一轮没干完」）", item.ok, True)
check("账上写着早班几分、晚班几点补", ("早班 80 分" in item.detail, "21:30" in item.detail), (True, True))
check("整轮判下来没有没干完的项", outcome.summarize(checks, "OK-WW"), None)
check("群里说了一声（通知，不是报警）", [t for t, _ in group], ["🔁 鸣潮早班活跃没满，晚班补"])
check("那一声里有分数和晚班时刻", ("80 分" in group[0][1], "21:30" in group[0][1], "晚班还没满会再报" in group[0][1]),
      (True, True, True))
booked = activity.read(eng.cfg.state_dir, "2026-10-23")
check("记下了晚班的时刻", booked.get("due", "")[11:16], "21:30")
checks2 = outcome.daily_reward_checks(MORNING)
activity.morning(eng, rec("OK-WW-05-16-50", at(9, 18), at(9, 30)), MORNING, checks2)
check("同一条记录再判一次（重放）：群里不再说第二遍", len(group), 1)
check("…而且已经记过的这一天，再短就照常算没干完", [c.ok for c in checks2 if c.label == activity.LABEL], [False])

print("\n[不是波片不够、或者今天后面没有排期：照常报]")
eng2, group2 = setup()
c = outcome.daily_reward_checks("2026-10-23 09:29:13,332 INFO TaskExecutor DailyTask:活跃奖励：活跃度 80\n")
activity.morning(eng2, rec("r2", at(9, 18), at(9, 30)), "活跃奖励：活跃度 80", c)
check("日志里没说波片用完 → 还是没干完、群里不说", ([x.ok for x in c if x.label == activity.LABEL], group2), ([False], []))
eng3, group3 = setup()
c = outcome.daily_reward_checks(MORNING)
activity.morning(eng3, rec("r3", at(21, 30), at(21, 45)), MORNING, c)
check("晚班之后才短（今天没有下一班）→ 照常报", ([x.ok for x in c if x.label == activity.LABEL], group3), ([False], []))

print("\n[到点、空闲才派；派一次；等它出结果才关机 / 发日报]")
sent = []
makeup._dispatch = lambda script: (sent.append(script), (True, "脚本「OK-WW」已单独开跑"))[1]
blocked = {"why": ""}
makeup._blocked = lambda e, now: blocked["why"]
import ark_relay.core.engine as _engine  # noqa: E402
_engine.forget_scripts_cache = lambda: None
check("21:30 之前：不派", activity.maybe_run(eng, at(12, 0)), False)
check("21:30 之前：关机和日报不等它（早班照常关机）", activity.holding(eng, at(12, 0)), "")
check("醒来的时刻是 21:30", activity.next_moment(eng.cfg.state_dir, at(12, 0))[0], at(21, 30))
check("21:30 到了：关机和日报等它", activity.holding(eng, at(21, 31)), "鸣潮活跃晚班补还没完")
blocked["why"] = "队列「晚班」还差 MAA"
check("晚班 MAA 还在跑：先不派", (activity.maybe_run(eng, at(21, 31)), sent), (False, []))
blocked["why"] = ""
check("跑完空闲了：派鸣潮一次", (activity.maybe_run(eng, at(21, 50)), sent), (True, ["OK-WW"]))
check("派过就不再派", (activity.maybe_run(eng, at(22, 0)), sent), (False, ["OK-WW"]))
check("还没出结果：继续等", activity.holding(eng, at(22, 0)), "鸣潮活跃晚班补还没完")
activity.on_record(eng, rec("OK-WW-13-50-12", at(21, 50), at(22, 5)))
check("补的那一趟记录到了：不再等", activity.holding(eng, at(22, 6)), "")
ev = outcome.daily_reward_checks(MORNING)
activity.morning(eng, rec("OK-WW-13-50-12", at(21, 50), at(22, 5)), MORNING, ev)
check("补完还没满：照常是没干完（「这一轮没干完」报警）", [c.ok for c in ev if c.label == activity.LABEL], [False])
check("群里没有多出一句「晚班补」", len(group), 1)

print("\n[晚班没补成也是没满：派不下去、派了没记录、那晚没开机，都报一次警]")
eng4, group4 = setup()
activity.morning(eng4, rec("r4", at(9, 18), at(9, 30)), MORNING, outcome.daily_reward_checks(MORNING))
makeup._dispatch = lambda script: (False, "调度程序没回应")
t = at(21, 40)
results = []
for k in range(3):
    activity.maybe_run(eng4, t)
    results.append(activity.read(eng4.cfg.state_dir, "2026-10-23").get("result"))
    t += timedelta(seconds=activity.RETRY_GAP_S + 1)
check("前两次记「派不下去」、第三次放手", results, ["couldnt_run", "couldnt_run", "gave_up"])
check("放手后关机和日报不再等", activity.holding(eng4, t), "")
alarms = [b for tt, b in group4 if tt.startswith("ALARM ⚠️ 这一轮没干完")]
check("三次没派下去：报一次警，说清没满和为什么", (len(alarms), "80 分" in alarms[0], "没派下去" in alarms[0]),
      (1, True, True))
activity.maybe_run(eng4, t + timedelta(minutes=30))
check("不重复报", len([1 for tt, _ in group4 if tt.startswith("ALARM")]), 1)
eng5, group5 = setup()
activity.morning(eng5, rec("r5", at(9, 18), at(9, 30)), MORNING, outcome.daily_reward_checks(MORNING))
makeup._dispatch = lambda script: (True, "ok")
activity.maybe_run(eng5, at(21, 40))
late = at(21, 40) + activity.STALE + timedelta(minutes=1)
check("派了但一直没有记录：过了 STALE 不再等", activity.holding(eng5, late), "")
activity.maybe_run(eng5, late)
check("…并且报一次警（派了没记录）", [("还没有这一趟的记录" in b) for tt, b in group5 if tt.startswith("ALARM")], [True])
eng6, group6 = setup()
activity.morning(eng6, rec("r6", at(9, 18), at(9, 30)), MORNING, outcome.daily_reward_checks(MORNING))
activity.maybe_run(eng6, datetime(2026, 10, 24, 9, 0, tzinfo=SERVER_TZ))
check("那晚没开机、第二天才醒：报一次警（晚班没补上）",
      [("晚班没补上" in b) for tt, b in group6 if tt.startswith("ALARM")], [True])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
