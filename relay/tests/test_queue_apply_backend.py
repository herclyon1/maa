"""A queue switch must reach the running AUTO-MAS, not just the file.

2026-09-30: "skip today" disabled the morning queue by editing QueueConfig.json
at 08:51:34 while AUTO-MAS was up (timer armed 08:48:59). AUTO-MAS never
re-read the file, started the queue at 09:00:00 and wrote its in-memory copy
back; the relay log said the queue was disabled. With the backend up,
queues.apply now goes through /api/queue/update and only reports success once
/api/queue/get reads the new value back.
"""
import json
import sys
import urllib.error
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import commands, modes, queues
from ark_relay import plan as _plan
from ark_relay.config import SERVER_TZ
from ark_relay.statestore import StateStore
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
