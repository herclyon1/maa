"""Shifts and their days: the day roll's skips, due weekdays everywhere, the shift clock after a retry, the shift check, an overdue run after an update.

One part per former file, each run on its own (tests/_parts.py): test_dayroll_skips.py, test_due_weekdays_everywhere.py, test_shift_clock_after_retry.py, test_shiftcheck.py, test_overdue_after_update_rerun.py.
"""
from __future__ import annotations

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


def _part_dayroll_skips():
    """A machine left on past midnight puts back the queue-command skips of the day before.

Review fix 6 of the 2026-10-11 hand-over: the put-back of a phone queue command's
today-only skip (gameupdate.restore_skips(before_day=...)) ran only at boot, so on
a machine left running for days the queue item kept that weekday off. The main
loop's _DayRoll wakes just past local midnight and puts them back; the game
update's own hold is left to run_deferred.

    Formerly test_dayroll_skips.py.
    """
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    from ark_relay.features.host import day_roll
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.features.phone import commands


    class Log:
        def __init__(self): self.lines = []
        def info(self, msg, *a, **k): self.lines.append(msg % a)
        def warning(self, *a, **k): pass
        def exception(self, *a, **k): self.lines.append("exception")


    D = datetime(2026, 10, 12, 23, 0, tzinfo=SERVER_TZ)
    state = tmpdir()


    def rec(script, item, **kw):
        return dict({"queue": "早班", "queueId": "q1", "queueItemId": item, "script": script, "scriptId": "s-" + item,
                     "position": 0, "day": "2026-10-12", "days": ["Monday"]}, **kw)


    gameupdate._add_skip(state, rec("MaaEnd", "i2", source="queue"))       # a queue command's skip
    gameupdate._add_skip(state, rec("OK-WW", "i3", why="维护"))           # the update's
    gameupdate._add_skip(state, rec("MAA", "i1", why="维护"))
    gameupdate._add_skip(state, rec("MAA", "i1", source="queue"))          # held by both

    put = []
    ok_restore = [False]


    def restorer(r):
        put.append(r["script"])
        return ok_restore[0]


    commands.restore_script_in_queue = restorer
    cfg = types.SimpleNamespace(state_dir=state)
    log = Log()
    roll = day_roll._DayRoll(cfg, log, now=D)

    print("[the loop wakes just past midnight]")
    check("23:59:30 with an hour to sleep: 31 s", roll.cap_wait(3600, D.replace(minute=59, second=30)), 31.0)
    check("a nearer alarm stays", roll.cap_wait(10, D.replace(minute=59, second=30)), 10)

    print("\n[before midnight nothing is put back]")
    check("23:59:59, first check after start (today's records only)",
          (roll.check(D.replace(minute=59, second=59)), put, roll.pending), ([], [], False))

    print("\n[a relay restart (not a reboot) after midnight puts back the day before's at once]")
    fresh = day_roll._DayRoll(cfg, Log(), now=D + timedelta(hours=1))
    ok_restore[0] = True
    check("first check", fresh.check(D + timedelta(hours=1)), ["MaaEnd→「早班」"])
    gameupdate._add_skip(state, rec("MaaEnd", "i2", source="queue"))       # same state again for the rest
    ok_restore[0] = False
    put.clear()
    for r in gameupdate.skips(state):
        if r["script"] == "MAA":
            gameupdate._add_skip(state, dict(r, source="queue", sources=["queue"]))

    print("\n[past midnight: AUTO-MAS not answering, kept and tried again]")
    n1 = D + timedelta(hours=1, seconds=1)
    check("first try fails", (roll.check(n1), put, roll.pending), ([], ["MaaEnd"], True))
    check("…and the loop wakes in 2 minutes to try again, not at the next alarm (清单-1108 A-04)",
          roll.cap_wait(3600, n1), day_roll._DayRoll.RETRY_S)
    ok_restore[0] = True
    put.clear()
    check("the next wake puts it back", (roll.check(n1 + timedelta(minutes=5)), put),
          (["MaaEnd→「早班」"], ["MaaEnd"]))
    check("…and logs it", any("过了零点" in line for line in log.lines), True)
    left = sorted((r["script"], tuple(sorted(gameupdate._sources(r)))) for r in gameupdate.skips(state))
    check("the update's holds stay (MAA keeps the update's, loses the queue's)", left,
          [("MAA", ("update",)), ("OK-WW", ("update",))])
    put.clear()
    check("nothing more the same day", (roll.check(n1 + timedelta(hours=3)), put, roll.pending), ([], [], False))
    check("nothing open: no 2-minute wakes", roll.cap_wait(3600, n1 + timedelta(hours=3)), 3600)


def _part_due_weekdays_everywhere():
    """Every place that reads a queue's times asks plan.runs_at whether the time runs anything
that day (audit 10-13: raw queue times were read without the weekday rule in five places,
and the daily report's 「明日安排」 listed skipped items).

AUTO-MAS fires a time only on its TimeSet Days and skips an item whose Schedule.Days leave
out the day (the relay's own one-day skip writes exactly that); test_plan.py
covers plan itself. Here: the shift / hand-start split (shutdown._near_due), the loop's
missed-run wake-up (Engine.next_deadline), the overrun watch (runwatch.overrun_moments),
the pre-update's 「a queue still to come runs OK-WW」 (preupdate.wanted_today), the
maintenance skip (gameupdate._queues_today) and plan.next_plan.

Config: tests/fixtures/automas-config-2026-10-11 (the machine's own, see SOURCE.txt).

    Formerly test_due_weekdays_everywhere.py.
    """
    #!/usr/bin/env python3

    import json
    import os
    import shutil
    from datetime import datetime
    from unittest import mock


    FX = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11"
    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    shutil.copytree(FX / "config", AUTOMAS / "config")
    STATE = TMP / "state"; STATE.mkdir()
    HIST = TMP / "history"; HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(STATE), SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import plan
    from ark_relay.core.config import Config, SERVER_TZ
    from ark_relay.core.engine import Engine
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import Notifier
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.features.preupdate import preupdate
    from ark_relay.features.run import runwatch
    from ark_relay.features.shutdown import shutdown

    # next_plan's maintenance notices come from the official sites; nothing here is about
    # them, and no relay test may reach the internet (run 38363145659 sat in those
    # fetches on Windows until the 180 s limit).
    plan.maintenance_lines = lambda day: []

    QC = AUTOMAS / "config" / "QueueConfig.json"
    PRISTINE = QC.read_text(encoding="utf-8")
    MORNING = "cc32e55a-55d0-408d-980d-642e66d111ae"       # 早班 09:00: MAA, OK-WW, MaaEnd
    EVENING = "6f09a385-b0ae-4ff6-9890-50339bdaddeb"       # 晚班 21:30: MAA
    MAAEND_ITEM = "572b030a-6eb2-4122-954e-07b3010c8d88"
    ALL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


    def at(day: int, hh: int, mm: int) -> datetime:
        return datetime(2026, 10, day, hh, mm, tzinfo=SERVER_TZ)   # 10-12 is a Monday


    def edit(fn) -> None:
        doc = json.loads(PRISTINE)
        fn(doc)
        QC.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


    def timeset(doc, queue):
        ts = doc[queue]["SubConfigsInfo"]["TimeSet"]
        return ts[ts["instances"][0]["uid"]]["Info"]


    def without(day):
        return [d for d in ALL if d != day]


    def morning_off_monday(d):
        timeset(d, MORNING).update(Days=without("Monday"))


    def maaend_off_tuesday(d):
        d[MORNING]["SubConfigsInfo"]["QueueItem"][MAAEND_ITEM]["Schedule"].update(Days=without("Tuesday"))


    def dues_today(now):
        return {q["name"]: [x.strftime("%H:%M") for x in q["dues"]] for q in gameupdate._queues_today(AUTOMAS, now)}


    class QuietNotifier(Notifier):
        def send(self, title, body, *, alert=False, daily=False):
            return []


    cfg = Config()
    E = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=QuietNotifier(cfg))

    print("[shutdown: a start next to a time that does not fire that day is a hand start]")
    edit(lambda d: timeset(d, EVENING).update(Days=["Monday"]))
    times = shutdown._schedule_times(E)
    check("Monday 21:35 is next to Monday's 晚班", shutdown._near_due(at(12, 21, 35), times), True)
    check("Tuesday 21:35 is not (晚班 runs on Mondays only)", shutdown._near_due(at(13, 21, 35), times), False)

    print("[engine: no missed-run wake-up for a time that runs nothing that day]")
    edit(lambda d: None)
    first = E.next_deadline(at(12, 8, 59))
    check("control: Monday 08:59 wakes for 早班 09:00", "早班" in (first or (None, ""))[1], True)
    edit(morning_off_monday)
    first = E.next_deadline(at(12, 8, 59))
    check("早班 off on Monday: that wake-up is gone", "早班" in (first or (None, ""))[1], False)

    print("[runwatch: no overrun watch over a time that ran nothing]")
    with mock.patch.object(runwatch, "planned_minutes", lambda *a: (60, 0)):
        edit(lambda d: None)
        got = [(q["name"], hhmm) for q, hhmm, *_ in runwatch.overrun_moments(E, at(12, 12, 0))]
        check("control: Monday noon watches 早班 09:00", ("早班", "09:00") in got, True)
        edit(morning_off_monday)
        got = [(q["name"], hhmm) for q, hhmm, *_ in runwatch.overrun_moments(E, at(12, 12, 0))]
        check("早班 off on Monday: not watched", ("早班", "09:00") in got, False)
        check("晚班 (Sunday 21:30) still watched", ("晚班", "21:30") in got, True)

    print("[preupdate: only a time that runs OK-WW that day wants the pre-update]")
    edit(lambda d: None)
    check("control: Monday 08:00, 早班 runs OK-WW", preupdate.wanted_today(AUTOMAS, at(12, 8, 0)), True)
    edit(morning_off_monday)
    check("早班 off on Monday: no pre-update wanted", preupdate.wanted_today(AUTOMAS, at(12, 8, 0)), False)

    print("[gameupdate: the maintenance skip only sees today's dues that run something]")
    edit(lambda d: None)
    check("control: Monday 08:00 sees 早班 09:00", dues_today(at(12, 8, 0)).get("早班"), ["09:00"])
    edit(morning_off_monday)
    check("早班 off on Monday: no 早班 due", dues_today(at(12, 8, 0)).get("早班"), [])
    check("晚班 21:30 still there", dues_today(at(12, 8, 0)).get("晚班"), ["21:30"])

    print("[明日安排: tomorrow's skipped item and off time are not listed]")
    with mock.patch.object(plan, "_tomorrow", lambda: at(13, 12, 0)):     # a Tuesday
        edit(lambda d: None)
        text = plan.next_plan(AUTOMAS)
        check("control: 终末地 listed under 早班", "▸ 终末地" in text, True)
        edit(maaend_off_tuesday)
        text = plan.next_plan(AUTOMAS)
        check("MaaEnd skipped on Tuesday: not listed", "▸ 终末地" in text, False)
        check("the rest of 早班 still listed", ("🕘 09:00" in text, "▸ 鸣潮" in text), (True, True))
        edit(lambda d: timeset(d, MORNING).update(Days=without("Tuesday")))
        text = plan.next_plan(AUTOMAS)
        check("早班 off on Tuesday: its time is not listed", "🕘 09:00" in text, False)
        check("晚班 still listed", "🕘 21:30" in text, True)

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_shift_clock_after_retry():
    """A script that timed out and was retried by AUTO-MAS restarts the shift's clock (ledger #138).

2026-11-05 09:00 早班: MAA's first attempt hung at StartUp (asst.log: 609 clicks of 开始唤醒) until
AUTO-MAS's timeout at 09:48 and a retry, which then passed StartUp at 09:51 and finished at 10:08.
MaaEnd started only at 10:22, and at 10:57 both runwatch's overrun alarm and shutdown's no-result
alarm counted 87 + 30 minutes from 09:00 - on top of the timeout alarm already pushed for MAA.

Checked here: runwatch.retry_clock reads the 「超时|<script>|<HH:MM:SS>」 marks check_timeouts leaves;
only a timeout between the shift's time and its planned end counts; the latest one wins; the
no-result clock (shutdown._overdue_from) and the overrun deadline (runwatch.overrun_moments) both
start from it; without a retry everything is as before, texts included.

    Formerly test_shift_clock_after_retry.py.
    """
    import json
    import types
    from datetime import datetime, timedelta
    from unittest import mock


    TMP = tmpdir()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.run import runwatch
    from ark_relay.features.shutdown import shutdown


    class Store:
        def __init__(self, marks):
            self.marks = marks

        def get(self, ns, key):
            return self.marks.get(key) if ns == "marks" else None


    def eng_with(marks):
        return types.SimpleNamespace(state=types.SimpleNamespace(store=Store(marks)))


    def t(h, m, s=0, day=5):
        return datetime(2026, 11, day, h, m, s, tzinfo=SERVER_TZ)


    due = t(9, 0)
    LIMIT = 87          # 「近 7 天最长 87 分钟跑完」 in the 10:57 alarm
    DAY = "alerted:2026-11-05"

    print("[retry_clock]")
    check("no marks: nothing restarts the clock", runwatch.retry_clock(eng_with({}), due, LIMIT), None)
    check("no state at all (bare engine): None", runwatch.retry_clock(types.SimpleNamespace(), due, LIMIT), None)
    e = eng_with({DAY: ["超时|MAA|09:48:12", "队列超时|早班|09:00"]})
    check("MAA timed out at 09:48 and was retried: from 09:48", runwatch.retry_clock(e, due, LIMIT), t(9, 48, 12))
    e = eng_with({DAY: ["超时|MAA|09:48:12", "超时|MAA|10:30:00"]})
    check("two timeouts in the run: the later one", runwatch.retry_clock(e, due, LIMIT), t(10, 30))
    e = eng_with({DAY: ["超时|MAA|08:59:59"]})
    check("a timeout before the shift's time does not count", runwatch.retry_clock(e, due, LIMIT), None)
    e = eng_with({DAY: ["超时|MaaEnd|10:57:01"]})
    check("a timeout after the planned end (10:57) moves nothing", runwatch.retry_clock(e, due, LIMIT), None)
    e = eng_with({DAY: ["超时|MAA|bad", "nonsense"]})
    check("malformed marks are skipped", runwatch.retry_clock(e, due, LIMIT), None)
    eve = t(21, 20)
    e = eng_with({DAY: [], "alerted:2026-11-06": ["超时|OK-WW|00:10:00"]})
    check("an evening shift's timeout after midnight is read from the next day",
          runwatch.retry_clock(e, eve, 180), t(0, 10, 0, day=6))

    print("[shutdown._overdue_from: the no-result clock]")
    e = eng_with({DAY: ["超时|MAA|09:48:12"]})
    check("without the limit: the queue's time, as before", shutdown._overdue_from(e, due, ["MaaEnd"]), due)
    check("with the limit: from the retry", shutdown._overdue_from(e, due, ["MaaEnd"], LIMIT), t(9, 48, 12))
    e._gu_rerun_at, e._gu_reran = t(12, 2, 15), {"MaaEnd"}
    check("a later update re-run still wins", shutdown._overdue_from(e, due, ["MaaEnd"], LIMIT), t(12, 2, 15))
    e._gu_rerun_at = t(9, 30)
    check("an earlier update re-run loses to the later retry", shutdown._overdue_from(e, due, ["MaaEnd"], LIMIT), t(9, 48, 12))
    deadline = shutdown._overdue_from(eng_with({DAY: ["超时|MAA|09:48:12"]}), due, ["MaaEnd"], LIMIT) \
        + timedelta(minutes=LIMIT + runwatch.OVERRUN_SLACK_MIN)
    check("the 11-05 case: no alarm at 10:57", t(10, 57) < deadline, True)
    check("a MaaEnd that hangs after the retry is still caught (11:45)", deadline, t(11, 45, 12))

    print("[runwatch.overrun_moments: the overrun deadline]")
    auto = TMP / "automas"
    (auto / "config").mkdir(parents=True)
    doc = {"instances": [{"uid": "q1", "type": "QueueConfig"}],
           "q1": {"Info": {"Name": "早班", "TimeEnabled": True},
                  "SubConfigsInfo": {"TimeSet": {"0": {"Info": {"Enabled": True, "Time": "09:00"}}},
                                     "QueueItem": {"0": {"Info": {"ScriptId": "s0"}}}}}}
    (auto / "config" / "QueueConfig.json").write_text(json.dumps(doc), encoding="utf-8")
    with mock.patch.object(runwatch, "planned_minutes", lambda *a: (LIMIT, 7)):
        for label, marks, want in (("no retry: 09:00 + 87 + 30", {}, t(10, 57)),
                                   ("MAA retried at 09:48: 09:48 + 87 + 30", {DAY: ["超时|MAA|09:48:12"]}, t(11, 45, 12))):
            stub = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=auto), state=types.SimpleNamespace(store=Store(marks)))
            got = [dl for _, hhmm, _, d, _, dl, _ in runwatch.overrun_moments(stub, t(10, 57)) if hhmm == "09:00"]
            check(label, got, [want])

    print("[texts: what the alarm says]")
    old = texts.shift_no_result_body("早班", due, t(11, 50), "MaaEnd", LIMIT, 30, 7)
    check("no retry: the no-result text has no restart clause", "重新算" in old, False)
    new = texts.shift_no_result_body("早班", due, t(11, 50), "MaaEnd", LIMIT, 30, 7, restarted=t(9, 48, 12))
    check("after a retry it says when the clock restarted", "AUTO-MAS 09:48 重试，从那时重新算" in new, True)
    ov = texts.shift_overrun_body("早班", due, t(11, 50), LIMIT, 30, "", "", 7, restarted=t(9, 48, 12))
    check("the overrun text ends at the restarted deadline", "该在 11:45 前结束" in ov, True)
    ov0 = texts.shift_overrun_body("早班", due, t(11, 50), LIMIT, 30, "", "", 7)
    check("without a retry the overrun deadline is 10:57 as before", "该在 10:57 前结束" in ov0 and "重新算" not in ov0, True)

    print("all checks passed" if not fails else f"FAILED: {fails}")


def _part_shiftcheck():
    """After-shift check (selfcheck/shiftcheck.py): the four sign-off items the relay had no
check for, judged once after every finished morning / evening shift.

The four come from scripts/mac/lib/healthcheck.py sections 3 and 6 (the 游戏-中继二
scope cut of 10-10 23:3x, less MAA's IfActivityFirst and IfFight - his own phone
settings, dropped by 验收 on 10-11). Each item has a red and a green case; the run is tied to
the shutdown decision's own "this shift finished" test (shutdown._not_shift), so a
round started by hand or a shift whose records this boot never saw land is not
checked; the line reaches the daily report's relay section and is never pushed.

    Formerly test_shiftcheck.py.
    """
    import inspect
    import json
    import logging
    import tempfile
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore
    from ark_relay.features.selfcheck import selfcheck, shiftcheck
    from ark_relay.features.shutdown import shutdown


    def by_name(checks, name):
        return next(c for c in checks if c.name == name)


    print("[each item: green, red, unreadable]")
    green = shiftcheck.judge("", False, False, "", [])
    check("four items", len(green), 4)
    check("all green", [c.ok for c in green], [True] * 4)
    check("all green -> one line saying so", shiftcheck.summary("晚班", green), "收工体检（晚班）4 项都对")
    check("his own MAA settings are not judged (活动关优先 / 作战开关)",
          [c.name for c in green if "活动关" in c.name or "作战" in c.name], [])

    red = shiftcheck.judge(texts.annihilation_off_body("明日方舟 · 剿灭"), True, True, "2026-10-11 20:50",
                           [{"since": "2026-10-11 09:12:00", "until": "2026-10-11 09:40:00"},
                            {"since": "2026-10-11 10:00:00", "until": None}])
    check("annihilation Close, week not done -> red with the boot alarm's words",
          (by_name(red, texts.SHIFTCHECK_ANNIHILATION).ok, by_name(red, texts.SHIFTCHECK_ANNIHILATION).detail),
          (False, texts.annihilation_off_body("明日方舟 · 剿灭")))
    # Audit s13 #2 (10-13 10:00:31 「4 项里 1 项不对…「下次跑完不关机」」): his own switches are notes.
    check("「下次跑完不关机」 armed -> holds, with a note", by_name(red, texts.SHIFTCHECK_SKIP).ok, True)
    check("debug mode on -> holds, the note says until when",
          (by_name(red, texts.SHIFTCHECK_DEBUG).ok, "2026-10-11 20:50" in by_name(red, texts.SHIFTCHECK_DEBUG).detail),
          (True, True))
    check("switches off -> no note", [c.detail for c in green], [""] * 4)
    check("a test window still open -> red, names the open one (not the closed one)",
          (by_name(red, texts.SHIFTCHECK_TEST_WINDOW).ok, "10:00:00" in by_name(red, texts.SHIFTCHECK_TEST_WINDOW).detail),
          (False, True))
    check("closed test windows only -> green",
          by_name(shiftcheck.judge("", False, False, "", [{"since": "a", "until": "b"}]),
                  texts.SHIFTCHECK_TEST_WINDOW).ok, True)
    line = shiftcheck.summary("早班", red)
    check("red line counts two not held", line.startswith("收工体检（早班）4 项里 2 项不对、0 项判不了："), True)
    check("his switches follow as a note, not among 不对",
          line.split("；你自己开着的：")[1:], [f"{texts.SHIFTCHECK_SKIP}：{texts.SHIFTCHECK_SKIP_ON}；"
                                            f"{texts.SHIFTCHECK_DEBUG}：{texts.shiftcheck_debug_on('2026-10-11 20:50')}"])
    skip_only = shiftcheck.summary("早班", shiftcheck.judge("", True, False, "", []))
    check("only the skip mark armed -> 都对 plus the note (10-13 10:00:31 said 1 项不对)",
          skip_only, f"收工体检（早班）4 项都对；你自己开着的：{texts.SHIFTCHECK_SKIP}：{texts.SHIFTCHECK_SKIP_ON}")
    check("red line is plain language", texts.plain(line), [])
    check("red line is one line (the daily report reads relay.log line by line)", "\n" in line, False)

    unread = shiftcheck.judge(None, False, False, "", [])
    check("annihilation switch unreadable -> cannot be judged (None), not green",
          by_name(unread, texts.SHIFTCHECK_ANNIHILATION).ok, None)
    check("unreadable line says 判不了", "1 项判不了" in shiftcheck.summary("晚班", unread), True)

    print("\n[once per finished shift, on the tick, before the report and the shutdown]")
    src = inspect.getsource(__import__("ark_relay.core.engine", fromlist=["Engine"]).Engine.tick)
    check("tick runs 收工体检 before 日报 and 关机",
          0 < src.index('"收工体检"') < src.index('"日报"') < src.index('"关机"'), True)


    class Gate:
        def __init__(self, line=""):
            self.line = line

        def switch_off_line(self, now=None):
            return self.line


    class Rec(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)


    rec = Rec()
    shiftcheck.log.addHandler(rec)
    shiftcheck.log.setLevel(logging.DEBUG)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "automas" / "config").mkdir(parents=True)

        due = datetime(2026, 10, 11, 21, 30, tzinfo=SERVER_TZ)
        booted = due - timedelta(minutes=15)
        now = due + timedelta(hours=1)
        store = StateStore(td)
        eng = SimpleNamespace(
            cfg=SimpleNamespace(state_dir=td, automas_dir=td / "automas"),
            state=SimpleNamespace(store=store, dir=td),
            _annihilation=Gate(""), _handled_any=True,
            _boot_time=lambda now: booted,
            _recent_entries=lambda now: [{"script": "MAA", "started": (due + timedelta(minutes=2)).isoformat()}],
            _last_round_manual=lambda now, entries: False,
        )
        real_queues = shutdown._shift_queues
        shutdown._shift_queues = lambda e, n, b: [{"name": "晚班", "due": due, "kinds": ["MAA"]}]
        try:
            got = shiftcheck.maybe_run(eng, now)
            check("finished shift -> checked", got is not None and [c.ok for c in got], [True] * 4)
            check("the line went to relay.log at INFO", [(r.levelno, r.getMessage()) for r in rec.records],
                  [(logging.INFO, "收工体检（晚班）4 项都对")])
            check("second tick of the same shift -> not again", shiftcheck.maybe_run(eng, now + timedelta(minutes=1)), None)
            check("the shift is remembered across a restart (state.json marks)",
                  StateStore(td).get("marks", shiftcheck.MARK), due.isoformat())

            # A new shift (next morning) is checked again; this one with every item red.
            due2 = datetime(2026, 10, 12, 5, 0, tzinfo=SERVER_TZ)
            shutdown._shift_queues = lambda e, n, b: [{"name": "早班", "due": due2, "kinds": ["MAA"]}]
            eng._boot_time = lambda now: due2 - timedelta(minutes=15)
            eng._recent_entries = lambda now: [{"script": "MAA", "started": (due2 + timedelta(minutes=1)).isoformat()}]
            eng._annihilation = Gate(texts.annihilation_off_body("明日方舟 · 剿灭"))
            store.set("modes", "skip_next_shutdown", True)
            store.set("modes", "debug_until", "2099-01-01 00:00")
            (td / "test-windows.json").write_text(json.dumps([{"since": "2026-10-12 04:50:00", "until": None}]),
                                                  encoding="utf-8")
            rec.records.clear()
            got = shiftcheck.maybe_run(eng, due2 + timedelta(hours=2))
            check("next shift, faults red and switches noted, read from the state files", got and [c.ok for c in got],
                  [False, True, True, False])
            check("switch notes read from the state files", got and [bool(c.detail) for c in got][1:3], [True, True])
            # D210 / audit 11-08 C-07: a red item is a WARNING, so errwatch takes it to the group.
            check("red goes out as a WARNING (errwatch takes it to the group)",
                  [r.levelno for r in rec.records], [logging.WARNING])
            check("red line names the morning shift", rec.records[0].getMessage().startswith("收工体检（早班）4 项里 2 项不对"),
                  True)

            # Not finished / not a scheduled shift: nothing.
            due3 = due2 + timedelta(hours=16, minutes=30)
            shutdown._shift_queues = lambda e, n, b: [{"name": "晚班", "due": due3, "kinds": ["MAA", "OK-WW"]}]
            eng._boot_time = lambda now: due3 - timedelta(minutes=15)
            eng._recent_entries = lambda now: [{"script": "MAA", "started": (due3 + timedelta(minutes=1)).isoformat()}]
            check("a script of the shift not recorded yet -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)),
                  None)
            check("still running -> no line (it may yet finish)", rec.records[-1:] and rec.records[-1].getMessage().startswith(
                "收工体检（早班）"), True)
            rec.records.clear()
            eng._recent_entries = lambda now: [{"script": k, "started": (due3 + timedelta(minutes=1)).isoformat()}
                                               for k in ("MAA", "OK-WW")]
            eng._last_round_manual = lambda now, entries: True
            check("last round started by hand -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)
            # Audit s13 #1 (10-12 21:45): the evening shift went unchecked and nothing said so.
            check("a due shift not judged says so once at INFO, in words the daily report quotes",
                  [(r.levelno, r.getMessage()) for r in rec.records],
                  [(logging.INFO, "收工体检（晚班）这班没查：最近一轮是手动触发的")])
            shiftcheck.maybe_run(eng, due3 + timedelta(hours=1, minutes=1))
            check("not repeated on the next tick", len(rec.records), 1)
            check("the daily report quotes it",
                  selfcheck.daily_lines("2026-10-12", "10-12 22:31:05 INFO    ark.shiftcheck  " + rec.records[0].getMessage()
                                        + "\n")[2:], ["· 收工体检（晚班）这班没查：最近一轮是手动触发的"])
            rec.records.clear()
            eng._last_round_manual = lambda now, entries: False
            eng._handled_any = False
            check("records never seen landing on this boot (relay restarted after the shift) -> not checked",
                  shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)
            eng._handled_any = True
            eng._boot_time = lambda now: None
            check("boot time unknown -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)
            eng._boot_time = lambda now: due3 - timedelta(minutes=15)
            shutdown._shift_queues = lambda e, n, b: []
            check("no scheduled shift on this boot -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)

            # A queue with no name (plan gives "?"): labelled by its time.
            due4 = due3 + timedelta(hours=8)
            shutdown._shift_queues = lambda e, n, b: [{"name": "?", "due": due4, "kinds": ["MAA"]}]
            eng._boot_time = lambda now: due4 - timedelta(minutes=15)
            eng._recent_entries = lambda now: [{"script": "MAA", "started": (due4 + timedelta(minutes=1)).isoformat()}]
            rec.records.clear()
            shiftcheck.maybe_run(eng, due4 + timedelta(hours=1))
            check("unnamed 05:xx queue -> 早班", rec.records and rec.records[0].getMessage().startswith("收工体检（早班）"), True)
            eng._boot_time = lambda now: due3 - timedelta(minutes=15)
            eng._recent_entries = lambda now: [{"script": k, "started": (due3 + timedelta(minutes=1)).isoformat()}
                                               for k in ("MAA", "OK-WW")]

            # A crash inside the check: ERROR, said in the line, not run again on the next tick.
            shutdown._shift_queues = lambda e, n, b: [{"name": "晚班", "due": due3, "kinds": ["MAA", "OK-WW"]}]
            real_read = shiftcheck.read
            shiftcheck.read = lambda e, n: 1 / 0
            rec.records.clear()
            try:
                check("crash -> []", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), [])
            finally:
                shiftcheck.read = real_read
            check("crash is a relay fault: ERROR with its traceback (errwatch pushes it), saying the shift was not checked",
                  [(r.levelno, r.getMessage(), bool(r.exc_info)) for r in rec.records],
                  [(logging.ERROR, texts.shiftcheck_broken("晚班"), True)])
            check("crashed shift not retried on every tick", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1, minutes=1)),
                  None)
        finally:
            shutdown._shift_queues = real_queues

    print("\n[the daily report's relay section quotes each shift's line]")
    log = """10-11 21:20:00 INFO    ark.service  服务模式启动
10-11 21:21:00 INFO    ark.service  AUTO-MAS 自己起来了（等了 21 秒）
10-11 22:31:05 INFO    ark.shiftcheck  收工体检（晚班）4 项里 1 项不对、0 项判不了：调试模式：开着，到 2026-10-12 04:50，这期间跑完不关机
10-10 22:31:05 INFO    ark.shiftcheck  收工体检（晚班）4 项都对
10-11 06:40:00 INFO    ark.shiftcheck  收工体检（早班）4 项都对
"""
    lines = selfcheck.daily_lines("2026-10-11", log)
    check("both shifts of the day quoted after the two relay lines, not yesterday's",
          lines[2:], ["· 收工体检（晚班）4 项里 1 项不对、0 项判不了：调试模式：开着，到 2026-10-12 04:50，这期间跑完不关机",
                      "· 收工体检（早班）4 项都对"])
    check("the shift line does not count as a boot", lines[1], "· 调度程序开机：21:21 自己起来了（等了 21 秒）")
    check("no shift line -> still the two lines", len(selfcheck.daily_lines("2026-10-09", log)), 2)

    print("\n[audit 11-08 C-07: a test window left open does not take later scheduled runs out of the report]")
    from ark_relay.core import ledger_report as _lr
    _open = [{"since": "2026-10-12T04:50:00+08:00", "until": None}]
    _test_run = {"run_id": "t", "started": "2026-10-12T05:10:00+08:00"}
    _shift_run = {"run_id": "s", "started": "2026-10-12T09:00:00+08:00"}
    _real, _tests = _lr.split_test([_test_run, _shift_run], _open)
    check("the run inside the window is a test", [e["run_id"] for e in _tests], ["t"])
    check("the 09:00 shift, 4 h after it opened, is real", [e["run_id"] for e in _real], ["s"])


def _part_overdue_after_update_rerun():
    """「⏰ 一直没出结果」 after a client update: the scripts the relay re-ran itself are timed from the re-run.

2026-11-01: 明日方舟 updated, MAA was skipped in the 09:00 早班 and re-run at 12:02 (relay.log
12:02:15 「补跑 MAA → 脚本「MAA」已单独开跑」); at 12:04:27 the overdue alarm counted 142 + 30
minutes from 09:00. Checks shutdown._overdue_from, the clock start _shift_overdue uses.

    Formerly test_overdue_after_update_rerun.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.shutdown import shutdown


    class Eng:
        pass


    due = datetime(2026, 11, 1, 9, 0, tzinfo=SERVER_TZ)
    rerun = datetime(2026, 11, 1, 12, 2, 15, tzinfo=SERVER_TZ)

    e = Eng()
    check("no re-run: the queue's time", shutdown._overdue_from(e, due, ["MAA"]), due)
    e._gu_rerun_at, e._gu_reran = rerun, {"MAA"}
    check("MAA re-run after the update: from 12:02", shutdown._overdue_from(e, due, ["MAA"]), rerun)
    check("another script also missing: still from the queue's time", shutdown._overdue_from(e, due, ["MAA", "OK-WW"]), due)
    e._gu_reran = {"OK-WW"}
    check("a different script was re-run: from the queue's time", shutdown._overdue_from(e, due, ["MAA"]), due)
    e._gu_reran, e._gu_rerun_at = {"MAA"}, datetime(2026, 10, 31, 22, 0, tzinfo=SERVER_TZ)
    check("yesterday's re-run does not move today's shift", shutdown._overdue_from(e, due, ["MAA"]), due)

    print("all checks passed" if not fails else f"FAILED: {fails}")


if __name__ == "__main__":
    sys.exit(run_parts([_part_dayroll_skips, _part_due_weekdays_everywhere, _part_shift_clock_after_retry, _part_shiftcheck, _part_overdue_after_update_rerun]))
