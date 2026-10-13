"""A watchdog service that vanishes after the relay saw it installed is pushed once.

Audit s24 F3 (10-13): Guard.tick returned "missing" with no log line at every look,
right for a machine where the service was never installed (a dev run, the old relay),
but on the game machine the service is installed (switch.log 10-11 10:04:35). If it
were deleted, nothing would start the relay again and nobody would hear of it. Now the
first look that finds it MISSING after a look that found it installed logs one WARNING
(errwatch pushes it), unless a stop marker from this boot says it was taken down on
purpose (switch.py uninstall stops it with the marker before removing it).
"""
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))

import watchdog_guard as G  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Logs:
    def __enter__(self):
        self.lines = []
        self.real = G.log.info, G.log.warning, G.log.error
        G.log.info = lambda msg, *a, **k: self.lines.append(("INFO", msg % a))
        G.log.warning = lambda msg, *a, **k: self.lines.append(("WARNING", msg % a))
        G.log.error = lambda msg, *a, **k: self.lines.append(("ERROR", msg % a))
        return self

    def __exit__(self, *exc):
        G.log.info, G.log.warning, G.log.error = self.real


def run(states, marker=False):
    states = list(states)
    g = G.Guard(lambda: states.pop(0), lambda: "", lambda: marker)
    with Logs() as logs:
        got = [g.tick() for _ in range(len(states))]
    return got, [lvl for lvl, _ in logs.lines if lvl != "INFO"], logs.lines


R, M, S = ("RUNNING", "AUTO"), ("MISSING", "OTHER"), ("STOPPED", "AUTO")

print("[never installed (dev run, old relay): quiet]")
got, loud, _ = run([M, M, M])
check("missing at every look", got, ["missing"] * 3)
check("no WARNING or ERROR", loud, [])

print("[installed, then gone: one WARNING, not one per look]")
got, loud, lines = run([R, M, M, M])
check("looks", got, ["running", "missing", "missing", "missing"])
check("one WARNING", loud, ["WARNING"])
check("it says the service is gone and our side has it",
      [("不见了" in m and "已交给我们这边" in m) for lvl, m in lines if lvl == "WARNING"], [True])

print("[seen stopped counts as installed too]")
got, loud, _ = run([S, M])
check("STOPPED_UNASKED, then one WARNING for the gone service", loud, ["WARNING", "WARNING"])

print("[back, then gone again: a second WARNING]")
got, loud, _ = run([R, M, R, M])
check("two WARNINGs", loud, ["WARNING", "WARNING"])

print("[removed on purpose (stop marker from this boot): quiet]")
got, loud, _ = run([R, M, M], marker=True)
check("no WARNING", loud, [])

if fails:
    print("FAIL:", fails)
    sys.exit(1)
print("all checks passed")
