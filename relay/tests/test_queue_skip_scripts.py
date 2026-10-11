"""A queue command's script list skips the rest for today, through Schedule.Days.

Since the 2026-10-11 hand-over (item 16) queues.apply(scripts=[...]) deletes no
queue item and writes no removed-*.json: each unlisted item loses today's weekday
(commands.skip_script_in_queue), the record goes into updates.queue_skips with
source "queue", and the boot-time gameupdate.restore_skips(before_day=...) gives
the day back the next morning. The game-update re-run neither undoes such a skip
nor re-runs the script because of it. The fake below is AUTO-MAS's backend as
commands._mas sees it; shapes from AUTO-MAS app/api/queue.py (item/get,
item/update) and app/models/schema.py QueueItem_Schedule.Days.
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
