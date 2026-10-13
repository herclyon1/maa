"""An AUTO-MAS exit looks back an hour for a Windows shutdown request, not 120 s (audit s15 #5).

_exited asked the System log for a 1074 of the last 120 s. The 1074 is written when the
command is given, the countdown before the shutdown: `shutdown /s /t 300` by hand
puts it ~300 s before AUTO-MAS is closed, outside that window, so the exit read as an
unexpected one and a revival ran into the closing session. _shutdown_before
(the WMI drop) already looks back SHUTDOWN_BEFORE_WINDOW_SECONDS (an hour).

The 1074 is the real one of 2026-10-10 04:27:24 (machine clock; `shutdown /s /t 60` by
hand, tests/fixtures/system-1010-0427-manual-shutdown.xml), moved to 300 s ago. With the
hour, a 1074 from before the current boot must not count: a 6005 (the Event Log service
started, docs/OPERATIONS.md "6005 boot") newer than it ends it.
"""
import logging
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
              "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
              "win32evtlog", "win32gui"):
    sys.modules.setdefault(_name, _Stub(_name))

from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.features.host import automas_keeper, automas_procs, shutdown_signs  # noqa: E402
from ark_relay.features.shutdown import shutdown  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}（要 {want!r}）" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


REAL_1074 = (Path(__file__).resolve().parent / "fixtures" /
             "system-1010-0427-manual-shutdown.xml").read_text(encoding="utf-8").strip()
NS = "http://schemas.microsoft.com/win/2004/08/events/event"


def stamp(utc: datetime) -> str:
    return utc.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def at(xml: str, utc: datetime) -> str:
    return re.sub(r"SystemTime='[^']*'", f"SystemTime='{stamp(utc)}'", xml)


def boot_event(utc: datetime) -> str:
    """A 6005 as EvtRender gives it (Provider EventLog)."""
    return (f"<Event xmlns='{NS}'><System><Provider Name='EventLog'/><EventID Qualifiers='32768'>6005</EventID>"
            f"<TimeCreated SystemTime='{stamp(utc)}'/><Channel>System</Channel></System>"
            "<EventData><Binary/></EventData></Event>")


log_events: list = []     # (utc, event id, xml) - the System log, any order


def fake_reader(window_s, ids=(1074, 1075)):
    """shutdown.shutdown_event_xml over log_events: the query's id and time filter, newest first."""
    now = datetime.now(tz=timezone.utc)
    hits = [(t, x) for t, eid, x in log_events
            if eid in ids and (now - t).total_seconds() <= window_s]
    return [x for t, x in sorted(hits, key=lambda h: h[0], reverse=True)]


shutdown.shutdown_event_xml = fake_reader
shutdown_signs.GOING_DOWN_SETTLE_SECONDS = 0.0
errwatch.relay_shutdown_issued = lambda: False
automas_procs._exit_code = lambda h: 0
automas_procs._tasklist = lambda: b"explorer.exe"
automas_keeper.win32api.CloseHandle = lambda h: None


class _Keep(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


def exit_now():
    keep = _Keep()
    log = logging.getLogger("ark.test_exit_shutdown_window")
    log.handlers[:] = [keep]
    log.setLevel(logging.INFO)
    log.propagate = False
    k = automas_keeper._AutomasKeeper.__new__(automas_keeper._AutomasKeeper)
    k.log, k.handle, k.gone = log, object(), None
    k._exited()
    return k, keep.msgs


now = datetime.now(tz=timezone.utc)

print("[shutdown /s /t 300：1074 在 AUTO-MAS 退出前 300 秒写下 → 按 Windows 关机处理，不重新打开]")
log_events[:] = [(now - timedelta(seconds=300), 1074, at(REAL_1074, now - timedelta(seconds=300)))]
k, msgs = exit_now()
check("held as a Windows shutdown", bool(k.gone and k.gone.get("shutdown")), True)
check("its initiator is named", any("shutdown.exe" in m and "发起了 Windows 关机" in m for m in msgs), True)

print("[1074 是这次开机之前的（之后有 6005）→ 不算关机]")
log_events[:] = [(now - timedelta(seconds=1500), 1074, at(REAL_1074, now - timedelta(seconds=1500))),
                 (now - timedelta(seconds=1400), 6005, boot_event(now - timedelta(seconds=1400)))]
k, msgs = exit_now()
check("not a shutdown", bool(k.gone and k.gone.get("shutdown")), False)
check("an unexpected exit", any("意外退出了" in m for m in msgs), True)

print("[更早于一小时的 1074 → 不算]")
log_events[:] = [(now - timedelta(seconds=4000), 1074, at(REAL_1074, now - timedelta(seconds=4000)))]
k, msgs = exit_now()
check("not a shutdown", bool(k.gone and k.gone.get("shutdown")), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
