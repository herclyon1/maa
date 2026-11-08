"""The run watch; the chain retry, the run limit, the run probe.

One part per former file, each run on its own (tests/_parts.py): test_runwatch.py, test_runwatch_chain_retry.py, test_run_limit.py, test_run_probe.py.
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


def _part_main():
    """Watch a running queue: push every timeout at once, and a shift that overruns.

Every timeout, not only the first of the day: the rule the user set on 2026-10-06 reads 「不论多少次什么错误都要发」.

Replays 2026-10-01: OK-WW timed out at 11:20, 13:21 and 15:23 (two hours each),
MaaEnd at 16:10, and the morning shift that normally ends within an hour was
still running past 16:00. Not one alarm went out that day. The app.log lines
below are copied from the machine; the ledger shapes from 09-24..09-30.

    Formerly test_runwatch.py.
    """
    import json
    import os
    import types
    from datetime import datetime, timedelta


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "debug").mkdir()
    MORNING_UID, EVENING_UID = "cc32e55a-55d0-408d-980d-642e66d111ae", "6f09a385-b0ae-4ff6-9890-50339bdaddeb"
    doc = {"instances": [{"uid": MORNING_UID, "type": "QueueConfig"}, {"uid": EVENING_UID, "type": "QueueConfig"}]}
    for uid, name, t in ((MORNING_UID, "早班", "09:00"), (EVENING_UID, "晚班", "21:30")):
        doc[uid] = {"Info": {"Name": name, "TimeEnabled": True},
                    "SubConfigsInfo": {"TimeSet": {"0": {"Info": {"Enabled": True, "Time": t}}},
                                       "QueueItem": {"0": {"Info": {"ScriptId": "s0"}}}}}
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features.selfcheck import machinecheck as _mc
    _mc.load()
    _mc_real = dict(_mc.CHECKS)   # put back at the end: the coverage pass runs every test file in one process
    _mc.CHECKS.clear()   # the alarms themselves are tested here; the machine checks in tests/test_mc.py


    class Notes:
        def __init__(self):
            self.sent = []
            self.fail = False

        def send(self, title, body="", **kw):
            if self.fail:
                return ["群机器人发送失败"]
            self.sent.append((title, body, kw.get("alert", False)))
            return False


    class Src:
        def fetch(self, seen):
            return []


    APPLOG = AUTOMAS / "debug" / "app.log"
    # Verbatim from D:\ark\automas\debug\app.log, 2026-10-01.
    LINES = [
        "2026-10-01 09:18:20.376 | INFO     | OK-WW 自动代理 | 用户 wuwa - 尝试次数: 1/3",
        "2026-10-01 09:18:20.701 | INFO     | OK-WW 自动代理 | 启动 OK-WW 进程: D:\\ark\\okww\\ok-ww.exe -t 1 -e",
        "2026-10-01 11:20:12.246 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 11:20:12.255 | WARNING  | OK-WW 自动代理 | 用户 wuwa - OK-WW 代理异常: OK-WW 运行超时",
        "2026-10-01 11:20:22.291 | INFO     | OK-WW 自动代理 | 用户 wuwa - 尝试次数: 2/3",
        "2026-10-01 13:21:12.400 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 13:21:22.468 | INFO     | OK-WW 自动代理 | 用户 wuwa - 尝试次数: 3/3",
        "2026-10-01 15:23:06.615 | INFO     | OK-WW 自动代理 | OK-WW 任务结果: OK-WW 运行超时, 日志锁已释放",
        "2026-10-01 15:23:07.031 | INFO     | MaaEnd 自动代理 | 用户 endfield - 原配置阶段尝试次数: 1/3",
        "2026-10-01 16:10:00.012 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: MaaEnd 进程超时, 日志锁已释放",
        "2026-10-01 16:10:02.996 | INFO     | MaaEnd 自动代理 | 用户 endfield - 原配置阶段尝试次数: 2/3",
    ]


    def at(hh, mm, day=1, month=10):
        return datetime(2026, month, day, hh, mm, tzinfo=SERVER_TZ)


    def write_log(upto):
        APPLOG.write_text("".join(l + "\n" for l in LINES[:upto]), encoding="utf-8")


    def append_log(frm, upto):
        with APPLOG.open("a", encoding="utf-8") as fh:
            fh.write("".join(l + "\n" for l in LINES[frm:upto]))


    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        e._scripts_running = lambda: False
        return e


    def run_watch(e, now):
        step = getattr(e, "_run_watch", None)     # absent before the fix: nothing ever looks
        if step is not None:
            step(now)


    def alarms(e):
        return [(t, b) for t, b, a in e.notifier.sent if a]


    print("[10-01 replay: OK-WW's first timeout at 11:20 is pushed at once]")
    write_log(4)
    e = build()
    run_watch(e, at(11, 21))
    got = alarms(e)
    check("one alarm", len(got), 1)
    check("names the game and script", bool(got) and "鸣潮（OK-WW）" in got[0][0], True)
    check("says attempt 1/3, start and end", bool(got) and "第 1/3 次跑超时：09:18 开跑，11:20" in got[0][1], True)
    check("says how many retries are left", bool(got) and "再试 2 次" in got[0][1], True)

    print("\n[the second and third OK-WW timeouts the same day are pushed too]")
    append_log(4, 8)
    run_watch(e, at(13, 22))
    run_watch(e, at(15, 24))
    got = alarms(e)
    check("three alarms", len(got), 3)
    check("second: attempt 2/3", len(got) > 1 and "第 2/3 次跑超时：11:20 开跑，13:21" in got[1][1], True)
    check("third: the last attempt", len(got) > 2 and "第 3/3 次跑超时" in got[2][1] and "这已是最后一次" in got[2][1], True)
    check("no 「不重复报」 promise any more", any("不重复报" in b for _, b in got), False)
    run_watch(e, at(15, 25))
    check("the same line is not pushed twice", len(alarms(e)), 3)

    print("\n[MaaEnd's first timeout at 16:10 is its own alarm]")
    append_log(8, 11)
    run_watch(e, at(16, 11))
    got = alarms(e)
    check("four alarms now", len(got), 4)
    check("the fourth is 终末地", len(got) == 4 and "终末地（MaaEnd）" in got[3][0], True)
    check("first attempt, 15:23 to 16:10", len(got) == 4 and "第 1/3 次跑超时：15:23 开跑，16:10" in got[3][1], True)

    print("\n[a relay started later does not replay the morning]")
    write_log(11)
    e2 = build()
    run_watch(e2, at(17, 30))
    check("nothing older than 30 minutes is news", alarms(e2), [])

    print("\n[an alarm that could not be sent is retried next tick]")
    write_log(4)
    e3 = build()
    e3.notifier.fail = True
    run_watch(e3, at(11, 21))
    check("nothing sent while the channel fails", alarms(e3), [])
    e3.notifier.fail = False
    run_watch(e3, at(11, 22))
    check("sent on the next tick", len(alarms(e3)), 1)

    print("\n[an alarm still unsent when it goes stale: one WARNING, not dropped silently (audit s18 F3)]")
    import logging as _logging
    from ark_relay.features.run import runwatch
    _said = []
    _h = type("H", (_logging.Handler,), {"emit": lambda self, r: _said.append((r.levelno, r.getMessage()))})()
    runwatch.log.addHandler(_h)
    try:
        write_log(4)
        e3b = build()
        e3b.notifier.fail = True
        run_watch(e3b, at(11, 21))
        _said.clear()
        run_watch(e3b, at(12, 0))
        gave_up = [m for lv, m in _said if lv == _logging.WARNING and "不再重试" in m]
        check("one WARNING says the timeout alarm was given up", len(gave_up), 1)
        check("it names the script and the time", bool(gave_up) and "OK-WW 11:20" in gave_up[0], True)
        _said.clear()
        run_watch(e3b, at(12, 1))
        check("not said again", [m for lv, m in _said if "不再重试" in m], [])
        check("a stale line read fresh from app.log is still dropped quietly",
              runwatch.check_timeouts(e3b, [runwatch.Timeout(at(9, 0), "MAA", "进程超时")], at(12, 0)), [])
        check("... with no WARNING", [m for lv, m in _said if "不再重试" in m], [])
    finally:
        runwatch.log.removeHandler(_h)

    print("\n[app.log rotated (AUTO-MAS restarted): read from the start again]")
    write_log(0)
    e4 = build()
    run_watch(e4, at(11, 0))
    write_log(4)
    run_watch(e4, at(11, 21))
    check("timeout found in the new file", len(alarms(e4)), 1)

    # ---------------------------------------------------------------- shift overrun
    from ark_relay.features.run import runwatch


    def ledger(state, day, rows):
        lines = [json.dumps({"run_id": f"r{i}", "script": s, "started": a.isoformat(),
                             "finished": b.isoformat(), "ok": True}) for i, (s, a, b) in enumerate(rows)]
        state.ledger_path(day.strftime("%Y-%m-%d")).write_text("\n".join(lines) + "\n", encoding="utf-8")


    def t(day, hh, mm, ss=0, month=9):
        return datetime(2026, month, day, hh, mm, ss, tzinfo=SERVER_TZ)


    def seed(state):
        """Ledger shapes of 09-24..09-30 (morning) plus a 21:30 evening run each day."""
        morning_end = {24: (10, 50), 25: (10, 0), 26: (9, 49), 27: (9, 53), 29: (9, 49), 30: (9, 47)}
        for d, (hh, mm) in morning_end.items():
            rows = [("MAA", t(d, 9, 0, 50), t(d, 9, 18)), ("OK-WW", t(d, 9, 18, 30), t(d, 9, 30)),
                    ("MaaEnd", t(d, 9, 31), t(d, hh, mm))]
            if d == 30:     # a make-up run hours later is not part of the shift
                rows.append(("MaaEnd", t(d, 15, 33), t(d, 15, 48)))
            rows.append(("MAA", t(d, 21, 30, 50), t(d, 21, 45 + d % 5)))
            ledger(state, t(d, 0, 0), rows)
        # 09-28 verbatim: a 41-minute hole between two MaaEnd records of the same shift
        ledger(state, t(28, 0, 0), [
            ("MAA", t(28, 9, 0, 52), t(28, 9, 4, 4)), ("MAA", t(28, 9, 4, 8), t(28, 9, 27, 32)),
            ("OK-WW", t(28, 9, 27, 53), t(28, 10, 28, 37)), ("MaaEnd", t(28, 10, 29, 47), t(28, 11, 22, 10)),
            ("MaaEnd", t(28, 12, 3, 14), t(28, 12, 40, 2)), ("MAA", t(28, 21, 30, 54), t(28, 21, 46, 29))])


    def snap(okww, maaend, queue=MORNING_UID):
        return {"tasks": [{"taskId": "8f47a684", "mode": "AutoProxy", "queueId": queue, "log": "正在启动游戏...",
                           "task_info": [{"name": "MAA", "status": "完成"}, {"name": "OK-WW", "status": okww},
                                         {"name": "MaaEnd", "status": maaend}]}]}


    print("\n[planned end = longest finish of the last 7 days, from the ledger]")
    e5 = build()
    seed(e5.state)
    check("早班: 220 minutes (09-28, hole included)", runwatch.planned_minutes(e5, 9, 0, at(9, 0)), (220, 7))
    check("晚班: 19 minutes", runwatch.planned_minutes(e5, 21, 30, at(21, 30))[0], 19)
    check("make-up run on 09-30 is not counted",
          runwatch.run_minutes(e5.state.read_ledger("2026-09-30"), t(30, 9, 0)), 47)
    check("no history -> fallback", runwatch.planned_minutes(build(), 9, 0, at(9, 0)), (180, 0))

    print("\n[10-01 itself (failed, seven hours) does not become tomorrow's limit]")
    ledger(e5.state, at(0, 0), [
        ("MAA", at(9, 0), at(9, 18)),
        ("OK-WW", at(9, 18), at(11, 20)), ("OK-WW", at(11, 20), at(13, 21)), ("OK-WW", at(13, 21), at(15, 23))])
    rows = [json.loads(x) for x in e5.state.ledger_path("2026-10-01").read_text(encoding="utf-8").splitlines()]
    for r in rows[1:]:
        r["ok"], r["failed_tasks"] = False, ["OK-WW 运行超时"]
    rows.append({"run_id": "me", "script": "MaaEnd", "started": at(15, 23).isoformat(),
                 "finished": at(17, 40).isoformat(), "ok": True})
    e5.state.ledger_path("2026-10-01").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    check("10-02 早班 limit stays 220", runwatch.planned_minutes(e5, 9, 0, at(9, 0, day=2))[0], 220)
    e5.state.ledger_path("2026-10-01").unlink()

    print("\n[a MaaEnd that did every task and then hung (booked ok) is a timeout, not a clean day (audit 11-08 B-D17)]")
    ledger(e5.state, at(0, 0), [("MAA", at(9, 0), at(9, 18)), ("OK-WW", at(9, 18), at(10, 20)),
                                ("MaaEnd", at(10, 20), at(15, 40))])
    rows = [json.loads(x) for x in e5.state.ledger_path("2026-10-01").read_text(encoding="utf-8").splitlines()]
    rows[-1]["raw"] = {"maaend_result": "MaaEnd 进程超时", "maaend_done_then_hung": True}
    e5.state.ledger_path("2026-10-01").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    check("the hung record reads as a timeout", runwatch._timed_out(rows[-1]), True)
    check("……so 10-01's 400 minutes do not raise 10-02's 早班 limit", runwatch.planned_minutes(e5, 9, 0, at(9, 0, day=2))[0], 220)
    check("an MAA record whose own result says 超时 too", runwatch._timed_out({"ok": True, "raw": {"maa_result": "MAA 进程超时"}}), True)
    check("a plain clean record is not", runwatch._timed_out({"ok": True, "raw": {"maaend_result": "Success!"}}), False)
    e5.state.ledger_path("2026-10-01").unlink()


    def fail_day(state, day, timeout=False):
        """Mark every record of 09-<day> failed, the way a retry day looks in the ledger."""
        p = state.ledger_path(f"2026-09-{day}")
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
        for r in rows:
            r["ok"], r["failed_tasks"] = False, ["OK-WW 运行超时" if timeout else "MAA 未能正确登录 PRTS"]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


    print("\n[the real 09-24..09-30 mix: only 26/27/28 clean in the morning -> still 220]")
    e9 = build()
    seed(e9.state)
    for d in (24, 25, 29, 30):
        fail_day(e9.state, d)
    check("three clean days are enough", runwatch.planned_minutes(e9, 9, 0, at(9, 0)), (220, 3))

    print("\n[fewer than three clean days: every day that did not time out, never the 180 default]")
    fail_day(e9.state, 26)
    check("2 clean -> the 7 non-timeout days", runwatch.planned_minutes(e9, 9, 0, at(9, 0)), (220, 7))
    fail_day(e9.state, 28, timeout=True)
    check("a timed-out day never counts", runwatch.planned_minutes(e9, 9, 0, at(9, 0)), (110, 6))
    for d in (24, 25, 26, 27, 29, 30):
        fail_day(e9.state, d, timeout=True)
    check("only when every day timed out -> 180", runwatch.planned_minutes(e9, 9, 0, at(9, 0)), (180, 0))

    print("\n[10-01: still running at 13:10 (09:00 + 220 + 30) -> one alarm]")
    real_win, real_snap = eng.config.IS_WINDOWS, eng._automas_snapshot
    try:
        eng.config.IS_WINDOWS = True
        write_log(0)
        eng._automas_snapshot = lambda: snap("运行", "等待")
        run_watch(e5, at(13, 9))
        check("13:09: not yet", alarms(e5), [])
        run_watch(e5, at(13, 10))
        got = alarms(e5)
        check("13:10: one alarm", len(got), 1)
        check("title", bool(got) and got[0][0] == "⏰ 早班超时还没跑完", True)
        check("body has the numbers", bool(got) and "已跑 250 分钟" in got[0][1] and "220 + 30" in got[0][1], True)
        check("body has each script's state", bool(got) and "OK-WW 运行" in got[0][1], True)
        run_watch(e5, at(14, 0))
        check("not repeated the same day", len(alarms(e5)), 1)

        print("\n[the shift already finished, or another queue is the one running -> nothing]")
        e6 = build()
        seed(e6.state)
        eng._automas_snapshot = lambda: snap("异常", "完成")
        run_watch(e6, at(13, 30))
        check("finished queue", alarms(e6), [])
        eng._automas_snapshot = lambda: snap("运行", "等待", queue="someone-else")
        run_watch(e6, at(13, 30))
        check("a task of another queue", alarms(e6), [])
        eng._automas_snapshot = lambda: None
        run_watch(e6, at(13, 30))
        check("AUTO-MAS cannot be asked", alarms(e6), [])

        print("\n[晚班: 21:30 + 19 + 30 = 22:19]")
        e7 = build()
        seed(e7.state)
        eng._automas_snapshot = lambda: snap("等待", "等待", queue=EVENING_UID)
        run_watch(e7, at(22, 18))
        check("22:18: not yet", alarms(e7), [])
        run_watch(e7, at(22, 19))
        check("22:19: alarm", [x[0] for x in alarms(e7)], ["⏰ 晚班超时还没跑完"])

        print("\n[no usable day: the body says the 180 is a default, not a 7-day record (audit s1 #4)]")
        e10 = build()
        eng._automas_snapshot = lambda: snap("运行", "等待")
        run_watch(e10, at(12, 30))
        got = alarms(e10)
        check("no history: 09:00 + 180 + 30 -> alarm at 12:30", len(got), 1)
        check("no history: says there is no record to go by",
              bool(got) and "没有可参考的记录，按 180 分钟算" in got[0][1] and "近 7 天" not in got[0][1], True)
        check("with history: still quotes the 7 days", "近 7 天最长 220 分钟跑完" in alarms(e5)[0][1], True)
    finally:
        eng.config.IS_WINDOWS, eng._automas_snapshot = real_win, real_snap

    print("\n[the loop comes back every minute while something runs, never when idle]")
    e8 = build()
    e8._scripts_running = lambda: True
    d = e8.next_deadline(at(10, 0))
    check("next moment one minute away", d and d[0] == at(10, 0) + timedelta(seconds=60), True)
    e8._scripts_running = lambda: False
    d = e8.next_deadline(at(10, 0))
    check("idle: no one-minute wake", bool(d) and d[0] == at(10, 0) + timedelta(seconds=60), False)

    print("\n[a queue time not exactly HH:MM: still watched, or said once (audit row runwatch.py:250)]")
    import logging
    from unittest import mock
    from ark_relay.core import plan as _plan
    from ark_relay.features.run import runwatch as _rw

    odd = TMP / "odd-automas"
    (odd / "config").mkdir(parents=True)
    odd_doc = {"instances": [{"uid": "q1", "type": "QueueConfig"}]}
    odd_doc["q1"] = {"Info": {"Name": "早班", "TimeEnabled": True},
                     "SubConfigsInfo": {"TimeSet": {"0": {"Info": {"Enabled": True, "Time": "09:00:00"}},
                                                    "1": {"Info": {"Enabled": True, "Time": "nine"}}},
                                        "QueueItem": {"0": {"Info": {"ScriptId": "s0"}}}}}
    (odd / "config" / "QueueConfig.json").write_text(json.dumps(odd_doc), encoding="utf-8")
    warned = []
    wh = type("W", (logging.Handler,), {"emit": lambda self, r: warned.append(r.getMessage())})(level=logging.WARNING)
    _plan.log.addHandler(wh)
    try:
        getattr(_plan, "_last_error", {}).clear()
        stub = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=odd))
        at = datetime(2026, 10, 10, 12, 0, tzinfo=SERVER_TZ)
        with mock.patch.object(_rw, "planned_minutes", lambda *a: (60, 0)):
            got = [(hhmm, due.strftime("%H:%M")) for _, hhmm, _, due, _, _, _ in _rw.overrun_moments(stub, at)]
            check("09:00:00 is watched as 09:00", got, [("09:00", "09:00")])
            check("an unparsable time is said, naming it", sum("nine" in w for w in warned), 1)
            list(_rw.overrun_moments(stub, at))
            check("same condition again -> no second WARNING", sum("nine" in w for w in warned), 1)
    finally:
        _plan.log.removeHandler(wh)

    _mc.CHECKS.update(_mc_real)


def _part_runwatch_chain_retry():
    """The overrun limit counts a shift whose failed attempt AUTO-MAS retried successfully as clean.

Audit s18 F1 (10-13): _chain called a run unclean when any record failed, even when
AUTO-MAS's retry of that script then succeeded, so the 09:00 shift was clean on only
2 of 13 days (10-01..10-13) and planned_minutes fell back to the longest of all
days. Each script is now judged by its last record in the chain, and a run a person
started at AUTO-MAS (raw.hand_started) is not part of the shift's chain.
Fixtures: the morning lines of the machine's ledgers 10-05, 10-08, 10-12.

    Formerly test_runwatch_chain_retry.py.
    """
    import json
    from datetime import datetime

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.run import runwatch

    FIX = RELAY / "tests" / "fixtures" / "runwatch-chain-1005-1012"


    def morning(day):
        rows = [json.loads(x) for x in (FIX / f"ledger-2026-10-{day:02d}-morning.jsonl").read_text(
            encoding="utf-8").splitlines() if x.strip()]
        return runwatch._chain(rows, datetime(2026, 10, day, 9, 0, tzinfo=SERVER_TZ))


    check("10-12: MaaEnd 10:05 failed, its 10:59 retry succeeded -> clean; "
          "the hand-started OK-WW 11:41-11:49 does not lengthen it", morning(12), (158, True, False))
    check("10-08: three failed MaaEnd attempts, the last (10:35-11:12) succeeded -> clean", morning(8),
          (132, True, False))
    check("10-05: MaaEnd's last record failed (a retry used up by its self-update) -> not clean",
          morning(5), (150, False, False))

    if fails:
        print("FAIL:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_run_limit():
    """Endfield's failure retry limit in AUTO-MAS kept at 1 (run_limit.py).

2026-11-05 morning one failed Endfield round ran three times under AUTO-MAS's
Run.RunTimesLimit=3, five with the make-up. The limit went to 1 that day, through
AUTO-MAS's API: an AUTO-MAS update or one click in its window puts it back. The backend's
read and write are stand-ins here. Checked:
* at 1: no write, nothing said;
* back at 3: written back to 1, one Server酱 line (not the group), once a day however often;
* refused while the script runs (「正在运行」): no count, the next tick writes it;
* refused for another reason ALARM_AFTER ticks in a row: one group alarm, not repeated;
* backend down or no such script: nothing;
* a replayed day before 2026-11-05 (the decision's day): nothing.

    Formerly test_run_limit.py.
    """
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.notify import route_of
    from ark_relay.features.phone import commands
    from ark_relay.features.schedule import run_limit as R


    class Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert))
            return []


    class Eng:
        def __init__(self):
            self.notifier = Notifier()


    state = {"limit": 1, "up": True, "refuse": "", "writes": 0}


    def fake_backend():
        if not state["up"]:
            return None, ""
        return {"data": {"sid-end": {"Info": {"Name": "MaaEnd"}, "Run": {"RunTimesLimit": state["limit"]}},
                         "sid-ark": {"Info": {"Name": "MAA"}, "Run": {"RunTimesLimit": 3}}}}, ""


    def fake_write(reply, script, path, value):
        state["writes"] += 1
        check("只改终末地的 Run.RunTimesLimit、改成 1", (script, path, value), ("MaaEnd", "Run.RunTimesLimit", 1))
        if state["refuse"]:
            return False, "调度程序没有接受这次修改：" + state["refuse"]
        state["limit"] = value
        return True, "失败重试上限 3 → 1（调度程序已确认）"


    commands._backend_scripts = fake_backend
    commands._script_item_via_api = fake_write
    DAY = datetime(2026, 11, 6, 9, 0, tzinfo=SERVER_TZ)
    NEXT_DAY = datetime(2026, 11, 7, 9, 0, tzinfo=SERVER_TZ)

    print("[是 1：不写、不通知]")
    e = Eng()
    R.step(e, DAY)
    check("没写", state["writes"], 0)
    check("没通知", e.notifier.sent, [])

    print("\n[被改回 3：改回 1，Server酱说一句，同一天只说一次]")
    state["limit"] = 3
    R.step(e, DAY)
    check("改回 1", (state["writes"], state["limit"]), (1, 1))
    check("说了一句，不进群", [(t, a) for t, _, a in e.notifier.sent], [(texts.RUN_LIMIT_RESET, False)])
    check("这句走 Server酱", route_of(texts.RUN_LIMIT_RESET), "info")
    check("说清楚是几改回几", "变成了 3" in e.notifier.sent[0][1] and "改回 1" in e.notifier.sent[0][1], True)
    state["limit"] = 3
    R.step(e, DAY)
    check("同一天又被改回：照改", (state["writes"], state["limit"]), (2, 1))
    check("同一天不再说第二遍", len(e.notifier.sent), 1)
    state["limit"] = 3
    R.step(e, NEXT_DAY)
    check("第二天又被改回：再说一句", len(e.notifier.sent), 2)

    print("\n[调度程序在跑、不收改动：不算失败，下一轮改]")
    e = Eng()
    state.update(limit=3, refuse="正在运行，无法更新配置项", writes=0)
    for _ in range(R.ALARM_AFTER + 1):
        R.step(e, DAY)
    check("每一轮都试了", state["writes"], R.ALARM_AFTER + 1)
    check("在跑时改不了：不报警", e.notifier.sent, [])
    state["refuse"] = ""
    R.step(e, DAY)
    check("跑完那一轮改回去了", state["limit"], 1)
    check("改回来了说一句", [t for t, _, _ in e.notifier.sent], [texts.RUN_LIMIT_RESET])

    print("\n[别的原因连着改不回来：进群一次]")
    e = Eng()
    state.update(limit=3, refuse="写入失败: 连接被拒绝", writes=0)
    for _ in range(R.ALARM_AFTER):
        R.step(e, DAY)
    check("第 3 次进群报警一次", [(t, a) for t, _, a in e.notifier.sent], [(texts.RUN_LIMIT_STUCK, True)])
    check("报警进群", route_of(texts.RUN_LIMIT_STUCK, alert=True), "group")
    check("报警里有调度程序的原话", "连接被拒绝" in e.notifier.sent[0][1], True)
    R.step(e, DAY)
    check("第 4 次不再重复报", len(e.notifier.sent), 1)

    print("\n[读不到调度程序、或者回放 11-05 以前的日子：什么都不做]")
    e = Eng()
    state.update(limit=3, up=False, refuse="", writes=0)
    R.step(e, DAY)
    check("调度程序没开：没写", state["writes"], 0)
    state["up"] = True
    R.step(e, datetime(2026, 10, 13, 8, 55, tzinfo=SERVER_TZ))
    check("11-05 以前的日子：没写", state["writes"], 0)
    check("什么都没说", e.notifier.sent, [])

    print("\n[文案]")
    for s in (texts.run_limit_reset_body("终末地", 3, 1), texts.run_limit_stuck_body("终末地", 3, 1, "x")):
        check("没有英文变量名", "RunTimesLimit" in s, False)

    print("\n[audit 11-08 B-07: an alarm whose send failed is sent again on the next failed tick]")
    e = Eng()
    _down = {"n": 0}


    def _send_fails_once(title, body, *, alert=False, daily=False):
        _down["n"] += 1
        e.notifier.sent.append((title, body, alert))
        return ["群机器人没回"] if _down["n"] == 1 else []


    e.notifier.send = _send_fails_once
    state.update(limit=3, refuse="写入失败: 连接被拒绝", writes=0)
    for _ in range(R.ALARM_AFTER + 2):
        R.step(e, DAY)
    check("the 3rd tick's send failed, the 4th sent it, the 5th is quiet",
          [t for t, _, _ in e.notifier.sent], [texts.RUN_LIMIT_STUCK, texts.RUN_LIMIT_STUCK])


def _part_run_probe():
    """run-probe.py (watch-run.sh's probe on the game machine): a MaaEnd update install is UPD, not FAIL.

Run over the real records of 2026-10-06..13, 6 of 38 came out `ok=0` with
「[更新] Success!」 (10-13 MaaEnd-05-59-12 among them), so watch-run.sh printed a FAIL
for every MaaEnd update the relay itself logs as 「不算一趟运行」 (collector.py
_judge_result). The records here are real results (10-13 05-59-12 and MAA-05-00-23,
10-10 05-13-19, 10-08 05-29-15), gathered under one day folder, copied from
the machine's AUTO-MAS history (fixtures/automas-runprobe/).

    Formerly test_run_probe.py.
    """
    import contextlib
    import importlib.util
    import io
    import json

    ROOT = Path(__file__).resolve().parents[2]
    FIX = Path(__file__).resolve().parent / "fixtures" / "automas-runprobe"
    spec = importlib.util.spec_from_file_location("run_probe", ROOT / "scripts" / "windows" / "run-probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)


    def lines(day):
        probe.HISTORY = str(FIX)
        out = io.StringIO()
        sys.argv = ["run-probe.py", day]
        with contextlib.redirect_stdout(out):
            probe.main()
        rows = {}
        for ln in out.getvalue().splitlines():
            tag, stem, kind, ok, res = ln.split("|", 4)
            rows[stem] = (tag, kind, ok, json.loads(res))
        return rows


    rows = lines("2026-10-13")
    print("[the 10-13 MaaEnd update record]")
    check("UPD, ok 1, not a FAIL", rows.get("MaaEnd-05-59-12"), ("UPD", "MaaEnd", "1", "[更新] Success!"))
    print("[real runs are judged as before]")
    check("MaaEnd Success!: REC ok", rows.get("MaaEnd-05-13-19"), ("REC", "MaaEnd", "1", "Success!"))
    check("MaaEnd partial failure: REC fail", rows.get("MaaEnd-05-29-15", ("",) * 4)[:3], ("REC", "MaaEnd", "0"))
    check("MAA Success!: REC ok", rows.get("MAA-05-00-23", ("",) * 4)[:3], ("REC", "MAA", "1"))
    print("[the same rule as the relay's collector]")
    check("「[更新] 跳过更新」 is not a run either", probe.judge("MaaEnd", "[更新] 跳过更新"), ("UPD", "1"))
    check("a failed update is a failed record", probe.judge("MaaEnd", "[更新] MaaEnd 更新失败，已停止后续任务: x"), ("REC", "0"))
    check("a stage-labelled success is a success", probe.judge("MaaEnd", "[日常] Success!"), ("REC", "1"))
    check("an unknown label is a failure (as collector._split_stage)", probe.judge("MaaEnd", "[新阶段] Success!"), ("REC", "0"))
    sys.path.insert(0, str(ROOT / "relay"))
    from ark_relay.core import collector
    check("the labels match collector.py", (probe.STAGE_LABELS, probe.UPDATE_LABEL, probe.UPDATE_FINE),
          (collector._STAGE_LABELS, collector._UPDATE_LABEL, collector._UPDATE_FINE))


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_runwatch_chain_retry, _part_run_limit, _part_run_probe]))
