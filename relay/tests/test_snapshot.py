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

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
