"""A today-only queue skip that fails part-way keeps its undo record.

Audit 9 (2026-10-13, A1): skip_script_in_queue wrote Schedule.Days first and
built the undo record only after the read-back; a read-back that raised lost the
record of a write that had landed. skip_script_all_items threw away the record
of the first item when the second failed. Both callers (queues.apply and the
maintenance skip in gameupdate.boot_check) then had nothing to put back, and
the item lost that weekday for good.

The fake is AUTO-MAS's backend as commands._mas sees it, as in
test_queue_skip_holders.py; `fail` makes one call raise after the write.
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
done = run(be, lambda: gameupdate.restore_skips(state, before_day=D1.strftime("%Y-%m-%d")), D1)
check("the next day's restore gives Monday back to both", (be.days("i2"), be.days("i3")), (ALL, ALL))

print("\n[gameupdate's maintenance skip keeps the record of a skip that failed part-way]")
import ark_relay.core.plan as plan  # noqa: E402

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
