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
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import commands, queues
from ark_relay.config import SERVER_TZ
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
