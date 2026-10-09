"""A relay.log rotation that keeps failing is said through logging, once per
failure streak (audit docs/SILENT-FAILURES-AUDIT.md, logfile.py:63).

The line used to be written straight into the file from inside the handler,
so errwatch (a handler on the "ark" logger) never saw it and nobody was told
that relay.log had stopped rotating.
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay import logfile

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append((record.levelno, record.getMessage()))

    def take(self, level):
        out = [m for lv, m in self.records if lv == level]
        self.records.clear()
        return out


d = tmpdir()
h = logfile.RelayLogHandler(d / "relay.log", max_bytes=2000, backups=2)
h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s", "%m-%d %H:%M:%S"))
# As in production (__main__._setup_logging puts it on the root logger): the
# lines of every ark.* logger, ark.logfile included, reach this handler.
src = logging.getLogger("ark.test_logfile_silent")
lf = logging.getLogger("ark.logfile")
saved_prop = src.propagate, lf.propagate
src.propagate = lf.propagate = False
src.addHandler(h)
lf.addHandler(h)
grab = Grab()
lf.addHandler(grab)
real_rotate = h.rotate


def locked(src_, dst):
    raise PermissionError(32, "being used by another process")


try:
    print("[rotation keeps failing: one WARNING through logging]")
    h.rotate = locked
    for i in range(60):
        src.warning("held %03d %s", i, "y" * 40)
    w = grab.take(logging.WARNING)
    check("one WARNING on ark.logfile (errwatch sees ark.*)", len(w), 1)
    check("it says the rotation failed", bool(w) and "轮转没成" in w[0], True)
    text = (d / "relay.log").read_text(encoding="utf-8")
    check("the file still has every line", sum(f"held {i:03d}" in text for i in range(60)), 60)
    check("the file has the line too", "轮转没成" in text, True)

    print("[the retry fails again: no second WARNING]")
    h._retry_at = time.monotonic() - 1
    src.warning("still held")
    check("no second WARNING in the same streak", grab.take(logging.WARNING), [])

    print("[the lock clears: rotated; a new streak warns again]")
    h.rotate = real_rotate
    h._retry_at = time.monotonic() - 1
    src.warning("after the lock")
    check("rotated", (d / "relay.log.1").exists(), True)
    check("no WARNING on success", grab.take(logging.WARNING), [])
    h.rotate = locked
    for i in range(60):
        src.warning("held again %03d %s", i, "z" * 40)
    check("a new streak -> WARNING again", len(grab.take(logging.WARNING)), 1)
finally:
    src.removeHandler(h)
    lf.removeHandler(h)
    lf.removeHandler(grab)
    src.propagate, lf.propagate = saved_prop
    h.close()

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
