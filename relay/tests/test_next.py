"""The next moments: the deadline, plan imports, queue weekdays.

One part per former file, each run on its own (tests/_parts.py): test_next_deadline.py, test_next_plan_imports.py, test_next_queue_weekdays.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_next_deadline():
    """When the loop is allowed to sleep until - the one number that decides
whether the relay wakes up at all.

`Engine.next_deadline` replaced polling: instead of waking every few minutes to
ask the clock, the loop sleeps until the exact moment a purely time-based
decision can change. That makes it the single point where two opposite failures
live, and no test had ever called it.

* Return a moment that is already past and the loop busy-spins.
* Return None, or a moment too late, and the relay sleeps through the daily
  report - and because shutdown waits for the report, the machine stays on all
  night. That exact outcome happened on 2026-09-04 through a different route.

The queue times here are read from a fake AUTO-MAS config on disk, the same way
the real one reads them, so "moving a queue in AUTO-MAS moves the deadline with
it" is covered too.

    Formerly test_next_deadline.py.
    """
    import json
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)


    def write_queues(times_by_name):
        """A QueueConfig.json shaped the way AUTO-MAS writes it."""
        doc = {"instances": []}
        for i, (name, times) in enumerate(times_by_name.items()):
            uid = f"q{i}"
            doc["instances"].append({"uid": uid})
            doc[uid] = {
                "Info": {"Name": name, "TimeEnabled": True},
                "SubConfigsInfo": {
                    "TimeSet": {str(n): {"Info": {"Enabled": True, "Time": t}}
                                for n, t in enumerate(times)},
                    "QueueItem": {"0": {"Info": {"ScriptId": "s0"}}},
                },
            }
        (AUTOMAS / "config" / "QueueConfig.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")


    write_queues({"早班": ["09:00"], "晚班": ["21:30"]})
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(
        json.dumps({"instances": []}), encoding="utf-8")

    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    (TMP / "history").mkdir(exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features.alarm.missed import MISSED_GRACE_MIN


    class Notes:
        def send(self, title, body="", **kw):
            return False


    class Src:
        def fetch(self, seen):
            return []


    def build(state_dir=None):
        cfg = Config()
        cfg.state_dir = state_dir or tmpdir()
        e = eng.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        return e


    def at(hh, mm, day=8):
        return datetime(2026, 9, day, hh, mm, tzinfo=SERVER_TZ)


    print("[08:00: the next moment is 「早班漏没漏跑」 (09:25); no wake-up checkpoint since 2026-10-10]")
    # The 09:02 / 21:32 checkpoints judged 「woken with nothing scheduled -> power off」; under
    # the user's 2026-10-10 18:31 rule only a finished shift powers off, so nothing wakes for them.
    e = build()
    when, why = e.next_deadline(at(8, 0))
    check("时刻", when, at(9, 0) + timedelta(minutes=MISSED_GRACE_MIN))
    check("理由点名了队列", "早班" in why, True)
    check("no checkpoint reason", "检查点" in why, False)

    print("\n[09:10: still 「早班漏没漏跑」 (09:25)]")
    when, why = e.next_deadline(at(9, 10))
    check("时刻", when, at(9, 0) + timedelta(minutes=MISSED_GRACE_MIN))

    print("\n[已经告警过的队列不再排队，否则同一件事反复叫醒]")
    e._missed_alerted.add("2026-09-08/早班/09:00")
    when, why = e.next_deadline(at(9, 10))
    check("跳到晚班那一档", when.hour >= 21, True)

    print("\n[日报没发时，21:30 的截止时刻必须在候选里]")
    e2 = build()
    when, why = e2.next_deadline(at(21, 0))
    check("21:30 截止", (when, why), (at(21, 30), "日报截止"))

    print("\n[日报发过了就不再为它醒——不然每轮都算一遍已经做完的事]")
    e2.state.mark_report_sent("2026-09-08")
    when, why = e2.next_deadline(at(21, 0))
    check("换成别的理由", why != "日报截止", True)
    check("仍然有下一个时刻", when is not None, True)

    print("\n[永远不给一个已经过去的时刻：给了循环就空转]")
    e3 = build()
    bad = []
    for hh in range(24):
        for mm in (0, 1, 29, 30, 31, 59):
            now = at(hh, mm)
            got = e3.next_deadline(now)
            if got is None:
                bad.append(f"{hh:02d}:{mm:02d} 没有下一个时刻")
            elif got[0] <= now:
                bad.append(f"{hh:02d}:{mm:02d} 给了过去的 {got[0]}")
    check("一天 144 个时刻全部合法", bad[:3], [])

    print("\n[今天的都过完了就滚到明天，不许返回 None]")
    when, why = e3.next_deadline(at(23, 59))
    check("落在明天", when.date(), at(0, 0, day=9).date())

    print("\n[已经下过关机令就别再醒了——机器马上就没了]")
    e4 = build()
    e4._shutdown_issued = True
    check("返回 None", e4.next_deadline(at(9, 0)), None)

    print("\n[关机令发出后只醒一次：到点核对关机有没有关下去（audit s2 F2）]")
    e4._shutdown_issued_at = at(9, 0)
    from ark_relay.features.shutdown.shutdown import ISSUED_STUCK_MIN
    got = e4.next_deadline(at(9, 1))
    check("醒在发令后 ISSUED_STUCK_MIN 分钟", got and got[0], at(9, 0) + timedelta(minutes=ISSUED_STUCK_MIN))
    check("那一刻过了就不再给过去的时刻", e4.next_deadline(at(9, 0) + timedelta(minutes=ISSUED_STUCK_MIN)), None)

    print("\n[队列时间改了，醒来的时刻跟着改（读的是 AUTO-MAS 自己那份）]")
    write_queues({"早班": ["07:15"], "晚班": ["21:30"]})
    e5 = build()
    when, why = e5.next_deadline(at(6, 0))
    check("跟着挪到 07:15 那一档", when, at(7, 15) + timedelta(minutes=MISSED_GRACE_MIN))
    check("理由点名新队列时刻", "07:15" in why, True)
    write_queues({"早班": ["09:00"], "晚班": ["21:30"]})

    print("\n[队列时间写坏了不许把整个循环带走]")
    doc = json.loads((AUTOMAS / "config" / "QueueConfig.json").read_text(encoding="utf-8"))
    doc["q0"]["SubConfigsInfo"]["TimeSet"]["0"]["Info"]["Time"] = "坏掉的时刻"
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False),
                                                         encoding="utf-8")
    e6 = build()
    raised = ""
    try:
        got = e6.next_deadline(at(6, 0))
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    check("不抛异常", raised, "")
    check("坏的那档被跳过，好的还在", got is not None, True)

    print("\n[正在刷声骸时，收工时刻和「看一眼还活着没」都要能把循环叫醒]")
    # 2026-09-09: neither of the farm's moments was registered here, so the loop
    # slept until the next queue alarm - 21 minutes measured. OK-WW stopped at
    # 06:45 and nothing looked at it until 07:06.
    from ark_relay.features.echofarm import echofarm
    e7 = build()
    _store = echofarm._store(e7.cfg.state_dir)
    _store.set("queues", "echo_farm", {"boss": 1, "name": "天傀劫煞",
                                       "until": at(8, 30).strftime("%Y-%m-%d %H:%M"),
                                       "started": at(6, 2).strftime("%Y-%m-%d %H:%M"),
                                       "saved": {}})
    try:
        when, why = e7.next_deadline(at(7, 0))
        check("先去看一眼它还活着没", "刷声骸" in why, True)
        check("而且很快就看", (when - at(7, 0)).total_seconds() / 60.0,
              float(echofarm.RESTART_QUIET_MINUTES))
        when2, why2 = e7.next_deadline(at(8, 29))
        check("快到点时叫醒的是收工那一下", "收工" in why2, True)
        check("就是 08:30 那一刻", when2.strftime("%H:%M"), "08:30")
    finally:
        _store.pop("queues", "echo_farm")
    check("没在刷的时候不多这两个闹钟", "刷声骸" in build().next_deadline(at(7, 0))[1], False)


def _part_next_plan_imports():
    """next_plan 能不能被调起来——2026-09-04 就是这里断的。

那天 phone.py 瘦身删掉了 plan.py 还在 import 的一个函数，
`next_plan` 一调就 ImportError，把 tick() 里排在它后面的补更新、日报、
自动关机全带走，一上午没人发现。**当时没有任何测试调过 next_plan。**

这个测试不断言排版，只断言「调得起来、不抛异常」——跨模块引用断掉、
少个 import、名字改了，都会在这里红。

    Formerly test_next_plan_imports.py.
    """
    import sys, tempfile, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.core import plan

    with tempfile.TemporaryDirectory() as d:
        # 没有 AUTO-MAS 目录也必须能返回，不能抛
        out = plan.next_plan(d)
        assert isinstance(out, str), f"next_plan 应返回字符串，得到 {type(out)}"
        out2 = plan.next_plan(None)
        assert isinstance(out2, str)
        # 那个被搬过来的辅助函数也得在，且对空输入安全
        assert plan._asar_value_labels(None, d) == {}
        assert plan._asar_value_labels(d, d) == {}
    print("✅ next_plan 调得起来 — all checks passed")


def _part_next_queue_weekdays():
    """boot_stages._seconds_to_next_queue skips a queue time that runs nothing today (audit s23 F4, 10-13).

232948ba moved five readers of queue times to plan.runs_at (a time fires only on its
weekdays, and only when some item does not sit the day out) and missed this one. Run
by the audit on a schedule of 09:00 Saturday-only plus 21:30 daily, at Tuesday 08:40:
the budget aimed at the 09:00 queue that does not fire (1110 s) instead of 21:30. The
budget decides whether a pre-update item gets its second try (_once_more).
The real QueueConfig has both times on all seven days, so this did not bite yet.

    Formerly test_next_queue_weekdays.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import boot_stages
    from ark_relay.core import plan
    from ark_relay.core.config import SERVER_TZ


    def at(day, hh, mm):
        return datetime(2026, 10, day, hh, mm, tzinfo=SERVER_TZ)     # 10-13 is a Tuesday


    ALL = list(plan._WEEKDAYS)
    SCHEDULES = {
        # 早班 09:00 fires on Saturdays only; 晚班 21:30 every day.
        "saturday_morning": [
            {"name": "早班", "times": ["09:00"], "items": ["maa"], "days": {"09:00": ["Saturday"]}},
            {"name": "晚班", "times": ["21:30"], "items": ["maa2"]},
        ],
        # 早班 fires every day, but its only item sits Tuesdays out.
        "item_off_tuesday": [
            {"name": "早班", "times": ["09:00"], "items": ["maaend"],
             "entries": [("maaend", [d for d in ALL if d != "Tuesday"])]},
            {"name": "晚班", "times": ["21:30"], "items": ["maa2"]},
        ],
    }

    real_schedule = plan.schedule
    try:
        to_evening = (at(13, 21, 30) - at(13, 8, 40)).total_seconds() - 90

        print("[09:00 fires on Saturdays only; Tuesday 08:40]")
        plan.schedule = lambda automas_dir: SCHEDULES["saturday_morning"]
        check("aims at 21:30, not the 09:00 that does not fire",
              boot_stages._seconds_to_next_queue(None, at(13, 8, 40)), to_evening)
        check("on a Saturday 08:40 the 09:00 queue counts",
              boot_stages._seconds_to_next_queue(None, at(17, 8, 40)), 20 * 60 - 90.0)

        print("[09:00's only item sits Tuesdays out]")
        plan.schedule = lambda automas_dir: SCHEDULES["item_off_tuesday"]
        check("aims at 21:30", boot_stages._seconds_to_next_queue(None, at(13, 8, 40)), to_evening)
        check("Wednesday 08:40: the 09:00 queue counts",
              boot_stages._seconds_to_next_queue(None, at(14, 8, 40)), 20 * 60 - 90.0)

        print("[unchanged: the floor, and nothing left today]")
        plan.schedule = lambda automas_dir: SCHEDULES["saturday_morning"]
        check("21:29 -> the floor", boot_stages._seconds_to_next_queue(None, at(13, 21, 29)), 120.0)
        check("after the last queue -> the no-queue-left figure",
              boot_stages._seconds_to_next_queue(None, at(13, 22, 0)), 3600.0)
    finally:
        plan.schedule = real_schedule

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


if __name__ == "__main__":
    sys.exit(run_parts([_part_next_deadline, _part_next_plan_imports, _part_next_queue_weekdays]))
