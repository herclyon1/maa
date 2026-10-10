"""procs.python_processes: a failed WMI query is tried again after a pause.

2026-10-10 16:14:07 (relay.log): right after a restart, the new relay's first
Win32_Process query failed with WBEM_E_CALL_CANCELLED (0x80041032, WMI-Activity
log, pid 1436) while WMI was still tearing down the subscription the old relay
had cancelled at 16:13:49. The boot self-check went red and the keeper never
attached its handle to AUTO-MAS (no 「已挂上 AUTO-MAS 进程句柄」 after 16:14:10).
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import procs

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class _ComError(Exception):
    def __init__(self, hresult):
        super().__init__(hresult)
        self.hresult = hresult


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def run(results):
    """Feed procs._query the given outcomes in turn; returns (result, sleeps, log records)."""
    seq = list(results)

    def fake_query():
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    sleeps = []
    procs._query, procs._sleep = fake_query, sleeps.append
    h = _Logs()
    procs.log.addHandler(h)
    procs.log.setLevel(logging.DEBUG)
    try:
        return procs.python_processes(), sleeps, h.records
    finally:
        procs.log.removeHandler(h)


CANCELLED = -2147217358   # 0x80041032 as pywin32 reports it (signed)
ROWS = [(6092, r"D:\ark\automas\python\python.exe main.py")]

print("[the 16:14:07 case: first try cancelled, the second reads]")
procs._warned = False
got, sleeps, recs = run([_ComError(CANCELLED), ROWS])
check("listing returned", got, ROWS)
check("paused once before the retry", sleeps, [procs.PAUSE_SECONDS])
check("no WARNING (it was read)", [r for r in recs if r.levelno >= logging.WARNING], [])
check("the cancel code is in the log", any("0x80041032" in r.getMessage() for r in recs))

print("[every try fails: None, one WARNING naming the code]")
procs._warned = False
got, sleeps, recs = run([_ComError(CANCELLED)] * procs.ATTEMPTS)
check("None", got, None)
check("paused between tries only", len(sleeps), procs.ATTEMPTS - 1)
warns = [r for r in recs if r.levelno >= logging.WARNING]
check("one WARNING", len(warns), 1)
check("WARNING names the code", bool(warns) and "0x80041032" in warns[0].getMessage())

print("[still down on the next call: no second WARNING (each one reaches the group)]")
got, _s, recs = run([_ComError(CANCELLED)] * procs.ATTEMPTS)
check("None again", got, None)
check("no new WARNING", [r for r in recs if r.levelno >= logging.WARNING], [])

print("[back, then down again: a new outage warns again]")
run([ROWS])
_g, _s, recs = run([_ComError(CANCELLED)] * procs.ATTEMPTS)
check("warned for the new outage", len([r for r in recs if r.levelno >= logging.WARNING]), 1)

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
