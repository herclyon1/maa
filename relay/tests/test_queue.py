"""Queues: apply through the backend and run-now, names, rows and times, skip holders, partial skips and their receipts, skip scripts.

One part per former file, each run on its own (tests/_parts.py): test_queue_apply_backend.py, test_queue_apply_runnow.py, test_queue_names.py, test_queue_rows_times.py, test_queue_skip_holders.py, test_queue_skip_partial.py, test_queue_skip_partial_receipt.py, test_queue_skip_scripts.py.
"""
from __future__ import annotations
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tmp  # loaded before the parts: its atexit cleanup and env default stay
from _parts import run_parts

_BEFORE_THE_PARTS = (_tmp,)


def _part_queue_apply_backend():
    """A queue switch must reach the running AUTO-MAS, not just the file.

2026-09-30: "skip today" disabled the morning queue by editing QueueConfig.json
at 08:51:34 while AUTO-MAS was up (timer armed 08:48:59). AUTO-MAS never
re-read the file, started the queue at 09:00:00 and wrote its in-memory copy
back; the relay log said the queue was disabled. With the backend up,
queues.apply now goes through /api/queue/update and only reports success once
/api/queue/get reads the new value back.

    Formerly test_queue_apply_backend.py.
    """
    import json
    import sys
    import urllib.error
    from datetime import datetime
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.phone import commands
    from ark_relay.features.modes import modes
    from ark_relay.features.schedule import queues
    from ark_relay.core import plan as _plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir

    fails = []
    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
        if not ok:
            fails.append(label)


    def automas_dir():
        d = tmpdir()
        (d / "config").mkdir()
        (d / "config" / "QueueConfig.json").write_text(json.dumps({
            "instances": [{"uid": "q1"}, {"uid": "q2"}],
            "q1": {"Info": {"Name": "早班", "TimeEnabled": True}},
            "q2": {"Info": {"Name": "晚班", "TimeEnabled": True}},
        }, ensure_ascii=False), encoding="utf-8")
        return d


    def file_enabled(d, qid):
        return json.loads((d / "config" / "QueueConfig.json").read_text(encoding="utf-8"))[qid]["Info"]["TimeEnabled"]


    class Backend:
        """Fake AUTO-MAS backend. `sticks=False` accepts updates but never applies them."""
        def __init__(self, sticks=True):
            self.sticks = sticks
            self.calls = []
            self.mem = {"q1": {"Info": {"Name": "早班", "TimeEnabled": True}},
                        "q2": {"Info": {"Name": "晚班", "TimeEnabled": True}}}

        def __call__(self, path, body=None, timeout=20):
            self.calls.append((path, body))
            if path == "/api/queue/get":
                return {"code": 200, "data": json.loads(json.dumps(self.mem))}
            if path == "/api/queue/update":
                if self.sticks:
                    self.mem[body["queueId"]]["Info"].update(body["data"]["Info"])
                return {"code": 200}
            raise AssertionError(path)


    def down(path, body=None, timeout=20):
        raise ConnectionRefusedError("backend down")


    real_mas = commands._mas
    try:
        print("\n[backend up] the switch goes through /api/queue/update and is read back")
        d = automas_dir()
        be = Backend()
        commands._mas = be
        ok, msg = queues.apply(d, "早班", enabled=False)
        check("reports success", ok, True)
        check("says it was read back", "调度程序已确认" in msg, True)
        check("update call body", ("/api/queue/update", {"queueId": "q1", "data": {"Info": {"TimeEnabled": False}}}) in be.calls, True)
        check("backend memory now off", be.mem["q1"]["Info"]["TimeEnabled"], False)
        check("file left alone (AUTO-MAS owns it while up)", file_enabled(d, "q1"), True)
        ok, msg = queues.apply(d, "早班", enabled=False)
        check("same value again: no second update", (ok, sum(c[0] == "/api/queue/update" for c in be.calls)), (True, 1))
        ok, msg = queues.apply(d, "新队列", enabled=True)
        check("old name maps to 早班 and re-enables", (ok, be.mem["q1"]["Info"]["TimeEnabled"]), (True, True))
        ok, msg = queues.apply(d, "不存在", enabled=False)
        check("unknown queue fails and lists what exists", (ok, "早班" in msg and "晚班" in msg), (False, True))
        ok, msg = queues.apply(d, "早班", enabled="false")
        check("non-bool rejected before any backend write", (ok, sum(c[0] == "/api/queue/update" for c in be.calls)), (False, 2))

        print("\n[backend up, update does not stick] reported as a failure")
        d = automas_dir()
        be = Backend(sticks=False)
        commands._mas = be
        ok, msg = queues.apply(d, "早班", enabled=False)
        check("reports failure", ok, False)
        check("says the read-back value", "没生效" in msg and "仍是开启" in msg, True)

        print("\n[backend down] falls back to editing the file")
        d = automas_dir()
        commands._mas = down
        ok, msg = queues.apply(d, "晚班", enabled=False)
        check("reports success", ok, True)
        check("file now off", file_enabled(d, "q2"), False)

        # docs/SILENT-FAILURES-AUDIT.md queues.py:127 - only a refused connection is
        # "down". A live AUTO-MAS that times out would overwrite a file edit from memory.
        print("\n[backend answers slowly or with an error] not edited, reported as a failure")
        for label, exc in (("timeout", TimeoutError("timed out")),
                           ("HTTP 500", urllib.error.HTTPError("http://x", 500, "err", {}, None))):
            def broken(path, body=None, timeout=20, exc=exc):
                raise exc
            d = automas_dir()
            commands._mas = broken
            ok, msg = queues.apply(d, "早班", enabled=False)
            check(f"{label}: reports failure", ok, False)
            check(f"{label}: says the scheduler did not answer", "调度程序没应答" in msg, True)
            check(f"{label}: file left alone", file_enabled(d, "q1"), True)
        d = automas_dir()
        commands._mas = lambda path, body=None, timeout=20: {"code": 200, "data": ["not", "a", "dict"]}
        ok, msg = queues.apply(d, "早班", enabled=False)
        check("odd answer: reports failure, file left alone", (ok, file_enabled(d, "q1")), (False, True))
        d = automas_dir()
        commands._mas = lambda path, body=None, timeout=20: (_ for _ in ()).throw(
            urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")))
        ok, msg = queues.apply(d, "早班", enabled=False)
        check("refused as urllib raises it: still the file path", (ok, file_enabled(d, "q1")), (True, False))

        print("\n[skip engage] a read-back mismatch drops the flag and says 跳过失败")
        S = tmpdir() / "state"; S.mkdir(parents=True)
        d = automas_dir()
        be = Backend(sticks=False)
        commands._mas = be
        real_sched = _plan.schedule
        _plan.schedule = lambda _d: [{"name": "早班", "times": ["09:00"]}, {"name": "晚班", "times": ["21:30"]}]
        try:
            T0 = datetime(2026, 9, 30, 8, 51, tzinfo=SERVER_TZ)
            day = T0.strftime("%Y-%m-%d")
            modes.add_day_queue(S, day, "早班")
            msgs = modes.process_skip(S, d, T0)
            check("message says 跳过失败", any("跳过「早班」失败" in m for m in msgs), True)
            check("never claims 已临时停用", any("已临时停用" in m for m in msgs), False)
            check("flag dropped: the page shows the queue running today",
                  StateStore(S).get("queues", f"skip_day:{day}"), None)
            check("no restore marker left behind", StateStore(S).get("queues", "skip_restore"), None)
            be.sticks = True
            modes.add_day_queue(S, day, "早班")      # the operator presses the switch again
            msgs = modes.process_skip(S, d, T0)
            check("retry succeeds: 已临时停用 only now", any("已临时停用" in m for m in msgs), True)
            check("backend memory off", be.mem["q1"]["Info"]["TimeEnabled"], False)
            msgs = modes.process_skip(S, d, datetime(2026, 9, 30, 9, 31, tzinfo=SERVER_TZ))
            check("restore goes through the backend too", be.mem["q1"]["Info"]["TimeEnabled"], True)
            check("marker cleared", StateStore(S).get("queues", "skip_restore"), None)
        finally:
            _plan.schedule = real_sched
    finally:
        commands._mas = real_mas

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_queue_apply_runnow():
    """队列启停和「现在跑一趟」不能一调用就崩。

2026-09-02 加 names 模块（队列改名早班/晚班）时，queues.apply 和
commands._run_now 里各留着一个叫 names 的局部列表。Python 把它当整个函数的
局部变量，函数第一行 names.canonical() 就 UnboundLocalError——四天里
跳过队列、待办里的队列开关、手机上的「现在跑一趟」每次都崩。
61 个测试全绿，因为没有一个测试真的调用过这两个函数。

    Formerly test_queue_apply_runnow.py.
    """
    import json
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

    from ark_relay.features.phone import commands
    from ark_relay.features.schedule import queues
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from _tmp import tmpdir

    fails = []

    # ---- queues.apply：真跑一遍，改完读回 ----
    tmp = tmpdir()
    (tmp / "config").mkdir()
    (tmp / "config" / "QueueConfig.json").write_text(json.dumps({
        "instances": [{"uid": "q1"}],
        "q1": {"Info": {"Name": "早班", "TimeEnabled": True},
               "SubConfigsInfo": {"TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "09:00"}}},
                                  "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}},
    }, ensure_ascii=False), encoding="utf-8")
    (tmp / "config" / "ScriptConfig.json").write_text(json.dumps({
        "instances": [{"uid": "s1"}],
        "s1": {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"}, "SubConfigsInfo": {"UserData": {}}},
    }), encoding="utf-8")

    try:
        ok, msg = queues.apply(tmp, "早班", enabled=False)
    except Exception as exc:  # noqa: BLE001
        fails.append(f"queues.apply 抛异常：{type(exc).__name__}: {exc}")
    else:
        if not ok:
            fails.append(f"queues.apply 应成功：{msg}")
        got = json.loads((tmp / "config" / "QueueConfig.json").read_text(encoding="utf-8"))
        if got["q1"]["Info"]["TimeEnabled"] is not False:
            fails.append("queues.apply 没把定时关掉")
        # 旧名字要能认（names.canonical 的用武之地）
        ok2, msg2 = queues.apply(tmp, "新队列", enabled=True)
        if not ok2 or "早班" not in msg2:
            fails.append(f"旧名「新队列」没被换成早班：{ok2} {msg2}")
        # 不存在的队列：报错里要列出现有的
        ok3, msg3 = queues.apply(tmp, "不存在", enabled=True)
        if ok3 or "早班" not in msg3:
            fails.append(f"不存在的队列应失败并列出现有队列：{msg3}")

    # ---- commands._run_now：把后端接口换成假的 ----
    calls = []
    def fake_mas(path, body=None, timeout=20):
        calls.append((path, body))
        if path == "/api/queue/get":
            return {"data": {"qid1": {"Info": {"Name": "早班"}}, "qid2": {"Info": {"Name": "晚班"}}}}
        if path == "/api/dispatch/start":
            return {"status": "success"}
        raise AssertionError(path)
    commands._mas = fake_mas
    try:
        ok, msg = commands._run_now("Evening-MAA")   # 旧名
    except Exception as exc:  # noqa: BLE001
        fails.append(f"_run_now 抛异常：{type(exc).__name__}: {exc}")
    else:
        if not ok or "晚班" not in msg:
            fails.append(f"_run_now 旧名应映射到晚班并成功：{ok} {msg}")
        if ("/api/dispatch/start", {"taskId": "qid2", "mode": "AutoProxy"}) not in calls:
            fails.append(f"没有派发晚班：{calls}")
        ok4, msg4 = commands._run_now("没有的队列")
        if ok4 or "早班" not in msg4 or "晚班" not in msg4:
            fails.append(f"不存在的队列应失败并列出现有队列：{msg4}")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_queue_names():
    """队列改名「早班/晚班」后，旧名字（新队列 / Evening-MAA）仍然被认。

排队中的手机指令、跳过标记、恢复标记里都可能还是旧名；改名不能让它们
变成「没有这个队列」。

    Formerly test_queue_names.py.
    """
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir
    STATE = tmpdir()
    os.environ["ARK_STATE_DIR"] = str(STATE)
    from ark_relay.features.phone import commands
    from ark_relay.core import names
    from ark_relay.core.statestore import StateStore

    fails = []
    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
        if not ok:
            fails.append(label)

    print("[canonical]")
    check("新队列→早班", names.canonical("新队列"), "早班")
    check("Evening-MAA→晚班", names.canonical("Evening-MAA"), "晚班")
    check("现名原样", names.canonical("早班"), "早班")
    check("带空白也认", names.canonical(" 新队列 "), "早班")
    check("未知名原样", names.canonical("别的"), "别的")
    check("空→空", names.canonical(""), "")

    print("[skip_today 落盘的是现名]")
    ok, msg = commands._skip_today("Evening-MAA")
    marks = {k: v for k, v in StateStore(STATE).section("queues").items() if k.startswith("skip_day:")}
    check("成功", ok, True)
    check("标记内容", list(marks.values()), ["晚班"])
    check("提示用现名", "「晚班」" in msg, True)

    print("[默认队列是早班]")
    # Clear the 晚班 skip above so the default queue is the only one flagged.
    for k in marks:
        StateStore(STATE).pop("queues", k)
    ok, msg = commands.apply_command({"action": "skip_today"})
    check("默认早班", any(v == "早班" for k, v in StateStore(STATE).section("queues").items()
                        if k.startswith("skip_day:")), True)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_queue_rows_times():
    """queue_rows gives each queue its start times (「时刻」), also while its timer is off.

A skip for today turns the queue's timer off (modes.py), and next_plan lists timed
queues only, so the phone's row of a skipped shift had no time to show (App review
10-14, 状态 page). Base data: the real 10-11 AUTO-MAS config (早班 09:00, 晚班 21:30).

    Formerly test_queue_rows_times.py.
    """
    #!/usr/bin/env python3

    import json
    import shutil
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from _tmp import tmpdir
    from ark_relay.core import plan

    FAILED: list[str] = []
    REAL = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11"


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    print("[real 10-11 config]")
    rows = plan.queue_rows(REAL)
    want = {q["name"]: q["times"] for q in plan._queues(REAL / "config")}
    require("each queue has its times, as the plan reads them",
            all(r.get("时刻") == want[r["名"]] for r in rows) and all(r.get("时刻") for r in rows), repr(rows))

    print("[a queue skipped today: timer off, times kept]")
    root = tmpdir()
    shutil.copytree(REAL, root / "a")
    qf = root / "a" / "config" / "QueueConfig.json"
    d = json.loads(qf.read_text(encoding="utf-8"))
    uid = d["instances"][0]["uid"]
    d[uid]["Info"]["TimeEnabled"] = False
    qf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    off = plan.queue_rows(root / "a")
    require("定时 off but 时刻 still there", off[0]["定时"] is False and off[0].get("时刻") == rows[0].get("时刻"), repr(off[0]))

    print("all checks passed" if not FAILED else "FAILED: " + ", ".join(FAILED))
    sys.exit(1 if FAILED else 0)


def _part_queue_skip_holders():
    """Today-only queue skips held by two sources, across days, and over repeated items.

Review of the 2026-10-11 hand-over (Schedule.Days skips, item 16) found three ways
a skip was lost or a weekday stayed removed:

1. A queue command replayed at the next boot skipped again while the earlier
   day's record was still open; the new record was dropped (same item) and the
   boot restore of the earlier day's record then gave today back.
4. A queue command listing a script the game update had skipped for maintenance
   undid the maintenance skip; and a queue command skipping a script the update
   already held was lost when the update's re-run put the item back.
5. A script that sits in one queue twice had only its first item skipped.

The fake below is AUTO-MAS's backend as commands._mas sees it (shapes from
AUTO-MAS app/api/queue.py item/get, item/update), as in test_queue_skip_scripts.py.
The clock is pinned through each module's `datetime`.

    Formerly test_queue_skip_holders.py.
    """
    import json
    import sys
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir
    from ark_relay.features.phone import commands
    from ark_relay.features.schedule import queues
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.gameupdate import gameupdate

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}" + ("" if ok else f", want {want!r}"))
        if not ok:
            fails.append(label)


    ALL = list(commands.WEEKDAYS)


    class Clock(datetime):
        at = None

        @classmethod
        def now(cls, tz=None):
            return cls.at


    commands.datetime = Clock
    queues.datetime = Clock
    D = datetime(2026, 10, 12, 10, 0, tzinfo=SERVER_TZ)          # a Monday
    D1 = D + timedelta(days=1)
    D2 = D + timedelta(days=2)
    WD = commands.WEEKDAYS


    def day(t):
        return t.strftime("%Y-%m-%d")


    class Backend:
        def __init__(self, extra=None):
            self.scripts = {"s-maa": {"Info": {"Name": "MAA"}}, "s-end": {"Info": {"Name": "MaaEnd"}},
                            "s-ww": {"Info": {"Name": "OK-WW"}}}
            self.queues = {"q1": {"Info": {"Name": "早班"}}}
            self.items = {"i1": {"Info": {"ScriptId": "s-maa"}, "Schedule": {"Days": list(ALL)}},
                          "i2": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}},
                          "i3": {"Info": {"ScriptId": "s-ww"}, "Schedule": {"Days": list(ALL)}}}
            self.items.update(extra or {})

        def __call__(self, path, body=None, timeout=20):
            if path == "/api/queue/get":
                return {"data": self.queues}
            if path == "/api/scripts/get":
                return {"data": self.scripts}
            if path == "/api/queue/item/get":
                return {"index": [{"uid": u} for u in self.items], "data": json.loads(json.dumps(self.items))}
            if path == "/api/queue/item/update":
                for sec, val in body["data"].items():
                    self.items[body["queueItemId"]].setdefault(sec, {}).update(val)
                return {"status": "success"}
            raise AssertionError(f"unexpected call {path}")

        def days(self, uid):
            return self.items[uid]["Schedule"]["Days"]


    real = commands._mas


    def run(be, fn, at):
        commands._mas, Clock.at = be, at
        try:
            return fn()
        finally:
            commands._mas = real


    automas = tmpdir()

    print("[fix 1: a queue command replayed at the next boot keeps today's skip]")
    state, be = tmpdir(), Backend()
    run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state), D)
    check("day D: MaaEnd loses Monday", WD[D.weekday()] in be.days("i2"), False)
    # Boot on D+1: the mailbox replays the same command before boot_check's restore.
    ok, _msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state), D1.replace(hour=8))
    check("the replay succeeds", ok, True)
    rec = next(r for r in gameupdate.skips(state) if r["script"] == "MaaEnd")
    check("the record moves to D+1 and keeps the true original days", (rec["day"], rec["days"]), (day(D1), ALL))
    done = run(be, lambda: (gameupdate.restore_skips(state, before_day=day(D1), manual_too=False)
                            + gameupdate.restore_skips(state, before_day=day(D1))), D1.replace(hour=8))
    check("the boot restore of earlier days leaves it", done, [])
    check("MaaEnd still does not run on D+1", WD[D1.weekday()] in be.days("i2"), False)
    done = run(be, lambda: gameupdate.restore_skips(state, before_day=day(D2)), D2.replace(hour=8))
    check("D+2's restore gives every weekday back (none lost for good)", (be.days("i2"), be.days("i3")), (ALL, ALL))
    check("nothing left recorded", gameupdate.skips(state), [])

    print("\n[fix 4: a queue command never undoes a maintenance skip]")
    state, be = tmpdir(), Backend()
    r = run(be, lambda: commands.skip_script_in_queue("早班", "MaaEnd"), D)
    r["why"] = "维护"
    gameupdate._add_skip(state, r)
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "MaaEnd"], state_dir=state), D)
    check("listing MaaEnd succeeds", ok, True)
    check("MaaEnd stays out today (maintenance)", WD[D.weekday()] in be.days("i2"), False)
    check("the maintenance record is kept as the update's",
          [gameupdate._sources(r) for r in gameupdate.skips(state) if r["script"] == "MaaEnd"], [{"update"}])
    check("the receipt does not claim it was put back", "恢复 MaaEnd" in msg, False)
    check("…and says why MaaEnd will not run", "MaaEnd 今天为游戏更新先跳过" in msg, True)

    print("\n[fix 4: a queue skip of an item the update holds survives the update's put-back]")
    state, be = tmpdir(), Backend()
    gameupdate._add_skip(state, run(be, lambda: commands.skip_script_in_queue("早班", "OK-WW"), D))
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "MaaEnd"], state_dir=state), D)
    check("skipping OK-WW is reported", (ok, "今天跳过 OK-WW" in msg), (True, True))
    check("one record, held by both", [gameupdate._sources(r) for r in gameupdate.skips(state)], [{"queue", "update"}])
    check("no re-run asked for (he said skip it)", gameupdate.needs_rerun(state, D, "OK-WW"), False)
    done = run(be, lambda: gameupdate.restore_skips(state, manual_too=False), D)
    check("the update's put-back leaves OK-WW out today", (done, WD[D.weekday()] in be.days("i3")), ([], False))
    check("the record stays, held by the queue command", [gameupdate._sources(r) for r in gameupdate.skips(state)],
          [{"queue"}])
    done = run(be, lambda: gameupdate.restore_skips(state, before_day=day(D1)), D1)
    check("the next day's restore gives it back", (done, be.days("i3")), (["OK-WW→「早班」"], ALL))

    print("\n[fix 5: a script in the queue twice: both items skip, each recorded]")
    state = tmpdir()
    be = Backend({"i4": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}}})
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "OK-WW"], state_dir=state), D)
    check("succeeds, one line for MaaEnd", (ok, msg.count("今天跳过 MaaEnd")), (True, 1))
    check("both MaaEnd items lose today", (WD[D.weekday()] in be.days("i2"), WD[D.weekday()] in be.days("i4")),
          (False, False))
    check("one record per item", sorted(r["queueItemId"] for r in gameupdate.skips(state)), ["i2", "i4"])
    done = run(be, lambda: gameupdate.restore_skips(state, before_day=day(D1)), D1)
    check("both get their days back the next day", (len(done), be.days("i2"), be.days("i4")), (2, ALL, ALL))
    be = Backend({"i4": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}}})
    recs = run(be, lambda: gameupdate._skip_default("早班", "MaaEnd"), D)
    check("the maintenance skip covers both items too", sorted(r["queueItemId"] for r in recs), ["i2", "i4"])

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_queue_skip_partial():
    """A today-only queue skip that fails part-way keeps its undo record.

Audit 9 (2026-10-13, A1): skip_script_in_queue wrote Schedule.Days first and
built the undo record only after the read-back; a read-back that raised lost the
record of a write that had landed. skip_script_all_items threw away the record
of the first item when the second failed. Both callers (queues.apply and the
maintenance skip in gameupdate.boot_check) then had nothing to put back, and
the item lost that weekday for good.

The fake is AUTO-MAS's backend as commands._mas sees it, as in
test_queue_skip_holders.py; `fail` makes one call raise after the write.

    Formerly test_queue_skip_partial.py.
    """
    import json
    import sys
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.features.phone import commands
    from ark_relay.features.schedule import queues

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}" + ("" if ok else f", want {want!r}"))
        if not ok:
            fails.append(label)


    ALL = list(commands.WEEKDAYS)


    class Clock(datetime):
        at = None

        @classmethod
        def now(cls, tz=None):
            return cls.at


    commands.datetime = Clock
    queues.datetime = Clock
    D = datetime(2026, 10, 12, 10, 0, tzinfo=SERVER_TZ)          # a Monday
    D1 = D + timedelta(days=1)
    MON = commands.WEEKDAYS[D.weekday()]


    class Backend:
        """`fail_get_after_update`: the item/get after the n-th update raises (the
    write landed, the read-back timed out). `fail_update`: the n-th update
    lands and then raises (the reply was lost)."""

        def __init__(self, extra=None, fail_get_after_update=0, fail_update=0):
            self.scripts = {"s-maa": {"Info": {"Name": "MAA"}}, "s-end": {"Info": {"Name": "MaaEnd"}}}
            self.queues = {"q1": {"Info": {"Name": "早班"}}}
            self.items = {"i1": {"Info": {"ScriptId": "s-maa"}, "Schedule": {"Days": list(ALL)}},
                          "i2": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}}}
            self.items.update(extra or {})
            self.updates = 0
            self.fail_get, self.fail_update = fail_get_after_update, fail_update

        def __call__(self, path, body=None, timeout=20):
            if path == "/api/queue/get":
                return {"data": self.queues}
            if path == "/api/scripts/get":
                return {"data": self.scripts}
            if path == "/api/queue/item/get":
                if self.fail_get and self.updates == self.fail_get:
                    self.fail_get = 0
                    raise TimeoutError("timed out")
                return {"index": [{"uid": u} for u in self.items], "data": json.loads(json.dumps(self.items))}
            if path == "/api/queue/item/update":
                for sec, val in body["data"].items():
                    self.items[body["queueItemId"]].setdefault(sec, {}).update(val)
                self.updates += 1
                if self.fail_update and self.updates == self.fail_update:
                    raise ConnectionResetError("reply lost")
                return {"status": "success"}
            raise AssertionError(f"unexpected call {path}")

        def days(self, uid):
            return self.items[uid]["Schedule"]["Days"]


    real = commands._mas


    def run(be, fn, at):
        commands._mas, Clock.at = be, at
        try:
            return fn()
        finally:
            commands._mas = real


    def caught(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            return exc
        return None


    automas = tmpdir()

    print("[one item: the write lands, the read-back times out]")
    be = Backend(fail_get_after_update=1)
    exc = run(be, lambda: caught(lambda: commands.skip_script_in_queue("早班", "MaaEnd")), D)
    check("the write landed (Monday removed)", MON in be.days("i2"), False)
    check("the error carries the undo record with the original days",
          [(r["queueItemId"], r["days"]) for r in getattr(exc, "recs", [])], [("i2", ALL)])

    print("\n[two items of one script: the second item's reply is lost]")
    be = Backend({"i3": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}}}, fail_update=2)
    exc = run(be, lambda: caught(lambda: commands.skip_script_all_items("早班", "MaaEnd")), D)
    check("both writes landed", (MON in be.days("i2"), MON in be.days("i3")), (False, False))
    check("the error carries both records (the first is not thrown away)",
          sorted(r["queueItemId"] for r in getattr(exc, "recs", [])), ["i2", "i3"])

    print("\n[queues.apply keeps the records of a skip that failed part-way]")
    state = tmpdir()
    be = Backend({"i3": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}}}, fail_get_after_update=2)
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state), D)
    check("the reply says it failed", (ok, "失败" in msg), (False, True))
    kept = gameupdate.skips(state)
    check("both items' records are kept, held by the queue command",
          sorted((r["queueItemId"], r["days"], tuple(gameupdate._sources(r))) for r in kept),
          [("i2", ALL, ("queue",)), ("i3", ALL, ("queue",))])
    run(be, lambda: gameupdate.restore_skips(state, before_day=D1.strftime("%Y-%m-%d")), D1)
    check("the next day's restore gives Monday back to both", (be.days("i2"), be.days("i3")), (ALL, ALL))

    print("\n[gameupdate's maintenance skip keeps the record of a skip that failed part-way]")
    import ark_relay.core.plan as plan

    state = tmpdir()
    be = Backend(fail_get_after_update=1)


    class Cfg:
        pass


    cfg = Cfg()
    cfg.state_dir, cfg.automas_dir, cfg.maa_dir, cfg.maaend_dir, cfg.okww_dir = state, state, None, None, None
    plan_backup = plan.schedule
    plan.schedule = lambda d: [{"name": "早班", "times": ["11:00"], "items": ["s1"]}]
    src = {"终末地": lambda n: (D.replace(hour=10), D.replace(hour=12), "官方公告")}
    try:
        notes, probs = run(be, lambda: gameupdate.boot_check(cfg, budget_s=0, now=D, maint_sources=src,
                                                             hint=lambda n: ""), D)
    finally:
        plan.schedule = plan_backup
    check("the failure is reported", any("跳过 MaaEnd 失败" in p for p in probs), True)
    check("the record is kept with the original days",
          [(r["queueItemId"], r["days"], r.get("why")) for r in gameupdate.skips(state)], [("i2", ALL, "官方公告")])

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_queue_skip_partial_receipt():
    """A queue's today-only script list that fails part-way names what it had already changed.

queues._scripts_via_backend restores the listed scripts it had skipped and then skips
the rest. When a later step failed it returned only that step's error, so the phone's
receipt read as "nothing changed" while AUTO-MAS had already been changed (audit s19 #4,
2026-10-13; relay.log 08-15..10-13 has no use of this path). The fake backend is the
one of test_queue_skip_holders.py; here the update of the OK-WW item fails.

    Formerly test_queue_skip_partial_receipt.py.
    """
    import json
    import sys
    from datetime import datetime
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir
    from ark_relay.features.phone import commands
    from ark_relay.features.schedule import queues
    from ark_relay.core.config import SERVER_TZ

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}" + ("" if ok else f", want {want!r}"))
        if not ok:
            fails.append(label)


    ALL = list(commands.WEEKDAYS)


    class Clock(datetime):
        at = None

        @classmethod
        def now(cls, tz=None):
            return cls.at


    commands.datetime = Clock
    queues.datetime = Clock
    D = datetime(2026, 10, 12, 10, 0, tzinfo=SERVER_TZ)          # a Monday
    WD = commands.WEEKDAYS


    def day(t):
        return t.strftime("%Y-%m-%d")


    class Backend:
        def __init__(self, extra=None):
            self.scripts = {"s-maa": {"Info": {"Name": "MAA"}}, "s-end": {"Info": {"Name": "MaaEnd"}},
                            "s-ww": {"Info": {"Name": "OK-WW"}}}
            self.queues = {"q1": {"Info": {"Name": "早班"}}}
            self.items = {"i1": {"Info": {"ScriptId": "s-maa"}, "Schedule": {"Days": list(ALL)}},
                          "i2": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}},
                          "i3": {"Info": {"ScriptId": "s-ww"}, "Schedule": {"Days": list(ALL)}}}
            self.items.update(extra or {})

        def __call__(self, path, body=None, timeout=20):
            if path == "/api/queue/get":
                return {"data": self.queues}
            if path == "/api/scripts/get":
                return {"data": self.scripts}
            if path == "/api/queue/item/get":
                return {"index": [{"uid": u} for u in self.items], "data": json.loads(json.dumps(self.items))}
            if path == "/api/queue/item/update":
                for sec, val in body["data"].items():
                    self.items[body["queueItemId"]].setdefault(sec, {}).update(val)
                return {"status": "success"}
            raise AssertionError(f"unexpected call {path}")

        def days(self, uid):
            return self.items[uid]["Schedule"]["Days"]


    real = commands._mas


    def run(be, fn, at):
        commands._mas, Clock.at = be, at
        try:
            return fn()
        finally:
            commands._mas = real


    automas = tmpdir()


    class Failing(Backend):
        fail_item = ""

        def __call__(self, path, body=None, timeout=20):
            if path == "/api/queue/item/update" and body["queueItemId"] == self.fail_item:
                raise ConnectionResetError("调度程序没应答")
            return super().__call__(path, body, timeout)


    print("[restore MaaEnd lands, then skipping OK-WW fails]")
    state, be = tmpdir(), Failing()
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "OK-WW"], state_dir=state), D)
    check("setup: MaaEnd skipped today", (ok, WD[D.weekday()] in be.days("i2")), (True, False))
    be.fail_item = "i3"
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "MaaEnd"], state_dir=state), D)
    check("reported as failed", ok, False)
    check("MaaEnd really was put back in AUTO-MAS", WD[D.weekday()] in be.days("i2"), True)
    check("the receipt names the failing step", "跳过 OK-WW 失败" in msg, True)
    check("the receipt also says MaaEnd was already put back", "这之前已经改了：恢复 MaaEnd" in msg, True)

    print("[nothing landed before the failure -> the receipt is the error alone]")
    state, be = tmpdir(), Failing()
    be.fail_item = "i2"
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state), D)
    check("failed, no 「这之前已经改了」", (ok, "这之前已经改了" in msg), (False, False))

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
    sys.exit(1 if fails else 0)


def _part_queue_skip_scripts():
    """A queue command's script list skips the rest for today, through Schedule.Days.

Since the 2026-10-11 hand-over (item 16) queues.apply(scripts=[...]) deletes no
queue item and writes no removed-*.json: each unlisted item loses today's weekday
(commands.skip_script_in_queue), the record goes into updates.queue_skips with
source "queue", and the boot-time gameupdate.restore_skips(before_day=...) gives
the day back the next morning. The game-update re-run neither undoes such a skip
nor re-runs the script because of it. The fake below is AUTO-MAS's backend as
commands._mas sees it; shapes from AUTO-MAS app/api/queue.py (item/get,
item/update) and app/models/schema.py QueueItem_Schedule.Days.

    Formerly test_queue_skip_scripts.py.
    """
    import json
    import sys
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir
    from ark_relay.features.phone import commands
    from ark_relay.features.schedule import queues
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.gameupdate import gameupdate

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}" + ("" if ok else f", want {want!r}"))
        if not ok:
            fails.append(label)


    ALL = list(commands.WEEKDAYS)
    NOW = datetime.now(tz=SERVER_TZ)
    TODAY = commands.WEEKDAYS[NOW.weekday()]
    NOT_TODAY = [d for d in ALL if d != TODAY]


    class Backend:
        def __init__(self, up=True):
            self.up = up
            self.calls = []
            self.scripts = {"s-maa": {"Info": {"Name": "MAA"}}, "s-end": {"Info": {"Name": "MaaEnd"}},
                            "s-ww": {"Info": {"Name": "OK-WW"}}}
            self.queues = {"q1": {"Info": {"Name": "早班"}}}
            self.items = {"i1": {"Info": {"ScriptId": "s-maa"}, "Schedule": {"Days": list(ALL)}},
                          "i2": {"Info": {"ScriptId": "s-end"}, "Schedule": {"Days": list(ALL)}},
                          "i3": {"Info": {"ScriptId": "s-ww"}, "Schedule": {"Days": list(ALL)}}}

        def __call__(self, path, body=None, timeout=20):
            self.calls.append(path)
            if not self.up:
                raise ConnectionRefusedError(61, "Connection refused")
            if path == "/api/queue/get":
                return {"data": self.queues}
            if path == "/api/scripts/get":
                return {"data": self.scripts}
            if path == "/api/queue/item/get":
                return {"index": [{"uid": u} for u in self.items], "data": json.loads(json.dumps(self.items))}
            if path == "/api/queue/item/update":
                for sec, val in body["data"].items():
                    self.items[body["queueItemId"]].setdefault(sec, {}).update(val)
                return {"status": "success"}
            raise AssertionError(f"unexpected call {path}")

        def days(self):
            return {u: it["Schedule"]["Days"] for u, it in self.items.items()}


    real = commands._mas


    def run(be, fn):
        commands._mas = be
        try:
            return fn()
        finally:
            commands._mas = real


    automas = tmpdir()
    state = tmpdir()

    print("[run only MAA today: the other two skip today, nothing deleted]")
    be = Backend()
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["maa"], state_dir=state))
    check("succeeds", ok, True)
    check("the receipt names both skips", ("今天跳过 MaaEnd" in msg, "今天跳过 OK-WW" in msg), (True, True))
    check("MAA keeps every day, the others lose today", be.days(),
          {"i1": ALL, "i2": NOT_TODAY, "i3": NOT_TODAY})
    check("no item is deleted or added", [c for c in be.calls if c.endswith(("delete", "add", "order"))], [])
    check("no removed-*.json next to the config", list(automas.glob("**/removed-*.json")), [])
    recs = gameupdate.skips(state)
    check("two records, source queue, original days kept",
          sorted((r["script"], r["source"], r["days"] == ALL) for r in recs),
          [("MaaEnd", "queue", True), ("OK-WW", "queue", True)])

    print("\n[the game-update side leaves a queue command's skip alone]")
    check("needs_rerun ignores it", gameupdate.needs_rerun(state, NOW, "MaaEnd"), False)
    done = gameupdate.restore_skips(state, restorer=lambda r: True, manual_too=False)
    check("restore after the re-run keeps it", (done, len(gameupdate.skips(state))), ([], 2))
    done = gameupdate.restore_skips(state, restorer=lambda r: True, before_day=NOW.strftime("%Y-%m-%d"))
    check("the boot restore on the same day keeps it too", (done, len(gameupdate.skips(state))), ([], 2))

    print("\n[same command again: nothing more to do]")
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state))
    check("already so", (ok, msg), (True, "已经是这个状态，无需改动"))

    print("\n[list MaaEnd again the same day: its skip is undone, the record dropped]")
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA", "MaaEnd"], state_dir=state))
    check("succeeds and says so", (ok, "恢复 MaaEnd" in msg), (True, True))
    check("MaaEnd has today back", be.days()["i2"], ALL)
    check("only OK-WW is still recorded", [r["script"] for r in gameupdate.skips(state)], ["OK-WW"])

    print("\n[next morning's boot restore gives OK-WW its day back]")
    tomorrow = (NOW + timedelta(days=1)).strftime("%Y-%m-%d")
    done = run(be, lambda: gameupdate.restore_skips(state, before_day=tomorrow))
    check("restored", (done, be.days()["i3"], gameupdate.skips(state)), (["OK-WW→「早班」"], ALL, []))

    print("\n[refusals]")
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["Nope"], state_dir=state))
    check("an unknown script is refused and named", (ok, "Nope" in msg), (False, True))
    ok, msg = run(be, lambda: queues.apply(automas, "晚班", scripts=["MAA"], state_dir=state))
    check("an unknown queue is refused", (ok, "晚班" in msg), (False, True))
    down = Backend(up=False)
    ok, msg = run(down, lambda: queues.apply(automas, "早班", scripts=["MAA"], state_dir=state))
    check("backend down: refused, no file edit", (ok, "调度程序没应答" in msg), (False, True))
    ok, msg = run(be, lambda: queues.apply(automas, "早班", scripts=["MAA"]))
    check("no state dir: refused before touching anything", (ok, be.days()["i2"]), (False, ALL))

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_queue_apply_backend, _part_queue_apply_runnow, _part_queue_names, _part_queue_rows_times, _part_queue_skip_holders, _part_queue_skip_partial, _part_queue_skip_partial_receipt, _part_queue_skip_scripts]))
