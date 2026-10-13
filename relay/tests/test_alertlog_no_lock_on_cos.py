"""alertlog: no lock held across a COS call; a failure first met on the push path
does not silence the next one.

Audit 2026-10-13 s7 #8: sync held _lock across GET and PUT (15 s each), and
record() takes the same lock on the alarm caller's thread, so a slow COS stalled
the caller after every delivered alarm. And self._ok was shared: a failure on
errwatch's copy thread (whose WARNING errwatch drops) set it, and no later
failure was ever said.
"""
import logging
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.alarm import alertlog, errwatch

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


print("[a slow PUT does not hold record() up, and what it records is not lost]")
cos: dict[str, bytes] = {}
in_put, release = threading.Event(), threading.Event()


def slow_put(key, data):
    in_put.set()
    release.wait(5)
    cos[key] = data
    return None


al = alertlog.AlertLog(tmpdir(), put=slow_put, get=lambda key: (None, ""))
al.record("❌ MAA 失败", "第一条")
syncer = threading.Thread(target=al.sync, daemon=True)
syncer.start()
in_put.wait(5)
rec = threading.Thread(target=al.record, args=("❌ MaaEnd 失败", "第二条"), daemon=True)
rec.start()
rec.join(1)
check("record() returns while the PUT is still out", rec.is_alive(), False)
release.set()
syncer.join(5)
rec.join(5)
in_put.clear()
release.set()
al.sync()
lines = b"".join(cos.values()).decode("utf-8")
check("both lines reach COS", ("第一条" in lines, "第二条" in lines), (True, True))


print("\n[a failure first met on the push path does not silence the next one]")


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, r):
        self.lines.append((r.threadName, r.getMessage()))


grab = Grab()
logging.getLogger(alertlog.log.name).addHandler(grab)
al = alertlog.AlertLog(tmpdir(), put=lambda key, data: "COS 503", get=lambda key: (None, ""))
al.record("❌ MAA 失败", "x")
t = threading.Thread(target=al.sync, name=f"{errwatch.PUSH_THREAD}-copy")
t.start()
t.join(5)
al.sync()          # on this (non-push) thread: errwatch would take this WARNING
logging.getLogger(alertlog.log.name).removeHandler(grab)
said = [n for n, m in grab.lines if "COS 没成" in m]
check("the failure is said off the push path too", said, [f"{errwatch.PUSH_THREAD}-copy", "MainThread"])

print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
