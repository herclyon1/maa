"""snapshot.read() skips the AUTO-MAS sections once the relay issued its own shutdown.

2026-10-06 06:21:34/36: after the relay issued the shutdown order the AUTO-MAS backend
was already gone, so `_MAS错误`/`_队列错误` failed with ConnectionRefused and two
WARNINGs went to the group. The read never asked errwatch.relay_shutdown_issued(),
which was True then. The fix: skip exactly those two sections while stopping; the
other two (`_OKWW错误` reads files, `_运行时错误` reads Windows services) still run.

2026-10-10 04:28:47: the same WARNING again, from a shutdown by hand (relay.log 04:28:45
「收到停止通知（Windows 关机）」, i.e. errwatch.mark_stopping()). relay_shutdown_issued()
was False, so the read went ahead and pushed. Any shutdown (errwatch.going_down()) now
skips those two sections, and a section failing once the shutdown has begun is INFO.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import errwatch, snapshot

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
    if not ok:
        fails.append(label)


class Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.warned: list[str] = []

    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.warned.append(record.getMessage())


grab = Grab()
snapshot.log.addHandler(grab)
snapshot.log.propagate = False

calls: list[str] = []


def fake(label):
    def f(out):
        calls.append(label)
        out[label] = "ok"
    return f


saved = (snapshot._mas, snapshot._queues, snapshot._okww, snapshot._runtime,
         errwatch.relay_shutdown_issued, errwatch.going_down)
errwatch.going_down = lambda extra=lambda: False: False

snapshot._mas, snapshot._queues = fake("_mas"), fake("_queues")
snapshot._okww, snapshot._runtime = fake("_okww"), fake("_runtime")

errwatch.relay_shutdown_issued = lambda: False
calls.clear()
out = snapshot.read()
check("没关机：四个都读", calls, ["_mas", "_queues", "_okww", "_runtime"])
check("没关机：无 WARNING", grab.warned, [])

errwatch.relay_shutdown_issued = lambda: True
calls.clear()
grab.warned.clear()
out = snapshot.read()
check("关机令已发：只读 _okww/_runtime，不碰 _mas/_queues", calls, ["_okww", "_runtime"])
check("关机令已发：无 WARNING", grab.warned, [])
check("_mas/_queues 不再写进结果", all(k not in out for k in ("_mas", "_queues")), True)
check("_okww/_runtime 还在", ("_okww" in out, "_runtime" in out), (True, True))

print("[10-10 04:28:47: Windows shutdown by hand, not the relay's own]")
errwatch.relay_shutdown_issued = lambda: False
errwatch.going_down = lambda extra=lambda: False: True
calls.clear()
grab.warned.clear()
out = snapshot.read()
check("手动关机：不碰 _mas/_queues", calls, ["_okww", "_runtime"])
check("手动关机：无 WARNING", grab.warned, [])

print("[the shutdown begins while a section is being read]")
state = {"down": False}
errwatch.going_down = lambda extra=lambda: False: state["down"]


def gone(out):
    state["down"] = True
    raise ConnectionRefusedError("AUTO-MAS backend gone")


snapshot._mas = gone
grab.warned.clear()
out = snapshot.read()
check("读到一半开始关机：无 WARNING", grab.warned, [])
check("读到一半开始关机：错误仍记进结果", "_MAS错误" in out, True)

print("[not shutting down: a failing section still warns]")
state["down"] = False


def refused(out):
    raise ConnectionRefusedError("x")


snapshot._mas = refused
grab.warned.clear()
out = snapshot.read()
check("没关机时读不到：照样 WARNING", len(grab.warned), 1)

(snapshot._mas, snapshot._queues, snapshot._okww, snapshot._runtime,
 errwatch.relay_shutdown_issued, errwatch.going_down) = saved
snapshot.log.removeHandler(grab)

print("[_queues: one queue's item list unreadable]")
import urllib.error  # noqa: E402
from unittest import mock  # noqa: E402

item_err = {"exc": None}


def fake_post(path, body=None, timeout=15):
    if path == "/api/scripts/get":
        return {"data": {"s1": {"Info": {"Name": "MAA"}}}}
    if path == "/api/queue/get":
        return {"data": {"q1": {"Info": {"Name": "早班", "TimeEnabled": True, "StartUpEnabled": False}}}}
    if item_err["exc"] is not None:
        raise item_err["exc"]
    return {"data": {"i1": {"Info": {"ScriptId": "s1"}}}}


class Grab2(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.warned = []

    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.warned.append(record)


g2 = Grab2()
snapshot.log.addHandler(g2)
getattr(snapshot, "_last_error", {}).clear()
with mock.patch.object(snapshot, "_post", fake_post), \
        mock.patch.object(errwatch, "relay_shutdown_issued", lambda: False), \
        mock.patch.object(errwatch, "going_down", lambda: False):
    item_err["exc"] = urllib.error.HTTPError("u", 500, "boom", {}, None)
    out = {}
    snapshot._queues(out)
    q = out["队列"]["早班"]
    check("unreadable -> 脚本 stays [] (shape) and is marked", (q["脚本"], "脚本读不到" in q), ([], True))
    check("unreadable -> one WARNING", len(g2.warned), 1)
    snapshot._queues({})
    check("same condition again -> no second WARNING", len(g2.warned), 1)
    item_err["exc"] = None
    out = {}
    snapshot._queues(out)
    check("readable -> the list, no mark", (out["队列"]["早班"]["脚本"], "脚本读不到" in out["队列"]["早班"]),
          (["MAA"], False))
    item_err["exc"] = urllib.error.HTTPError("u", 500, "boom", {}, None)
    snapshot._queues({})
    check("broken again after a good read -> WARNING again", len(g2.warned), 2)
    item_err["exc"] = urllib.error.URLError(ConnectionRefusedError(61, "refused"))
    raised = False
    try:
        snapshot._queues({})
    except Exception:  # noqa: BLE001
        raised = True
    check("backend gone (connection refused) -> the section fails as before", raised, True)
snapshot.log.removeHandler(g2)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
