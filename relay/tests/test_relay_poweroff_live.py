"""Only the power-off the relay itself issued may keep a teardown out of the group (2026-10-06).

The user, 2026-10-06: only the planned machine power-off teardown may skip the
group, and only when the relay itself started the shutdown. errwatch.relay_shutdown_issued()
is that test; boot_stages._relay_poweroff_live feeds it from the engine.
"""
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
              "win32con", "win32file", "servicemanager", "win32process",
              "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(_name, _Stub(_name))

import boot_stages  # noqa: E402
from ark_relay import errwatch, shutdown  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


now = datetime(2026, 10, 6, 22, 0, tzinfo=SERVER_TZ)
eng = types.SimpleNamespace(_shutdown_issued=False, _shutdown_issued_at=None)
print("[the relay has not issued a power-off]")
check("not ours", boot_stages._relay_poweroff_live(eng, now), False)
print("[issued a minute ago]")
eng._shutdown_issued, eng._shutdown_issued_at = True, now - timedelta(minutes=1)
check("ours, under way", boot_stages._relay_poweroff_live(eng, now), True)
print("[issued long ago and the machine is still up: no longer excused]")
eng._shutdown_issued_at = now - timedelta(minutes=shutdown.ISSUED_STUCK_MIN)
check("not excused any more", boot_stages._relay_poweroff_live(eng, now), False)

print("[errwatch: a stop or Windows' shutdown alone is not the relay's power-off]")
errwatch._relay_poweroff[0] = lambda: False
errwatch.mark_stopping()
try:
    check("going_down() says yes", errwatch.going_down(), True)
    check("relay_shutdown_issued() says no", errwatch.relay_shutdown_issued(), False)
finally:
    errwatch._stopping.clear()
print("[install wires the probe in]")


class _N:
    def send(self, *a, **k):
        return []


h = errwatch.install(_N(), lambda: True)
try:
    check("relay_shutdown_issued() follows the probe", errwatch.relay_shutdown_issued(), True)
finally:
    import logging
    logging.getLogger(errwatch.ARK).removeHandler(h)
    errwatch._relay_poweroff[0] = lambda: False
errwatch._relay_poweroff[0] = lambda: 1 / 0
check("a broken probe answers 「not ours」, so it pushes", errwatch.relay_shutdown_issued(), False)
errwatch._relay_poweroff[0] = lambda: False

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
