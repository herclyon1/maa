"""A queue's today-only script list that fails part-way names what it had already changed.

queues._scripts_via_backend restores the listed scripts it had skipped and then skips
the rest. When a later step failed it returned only that step's error, so the phone's
receipt read as "nothing changed" while AUTO-MAS had already been changed (audit s19 #4,
2026-10-13; relay.log 08-15..10-13 has no use of this path). The fake backend is the
one of test_queue_skip_holders.py; here the update of the OK-WW item fails.
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
