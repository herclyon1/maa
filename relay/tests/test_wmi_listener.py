"""The WMI process-start listener (service._ProcessWatch): a drop it got over by
itself goes to the daily report only; one that did not is pushed.

#59 of the 2026-10-06 log sweep, 「系统的程序启动通知断了」: until then the first
drop was an ERROR at once, so a drop that WMI's own resubscribe fixed five
seconds later still rang the group. The user on 2026-10-06 05:07, about
faults the relay recovered from by itself: 「报错后自己好了的，只进日报、不进群」.

Pinned here, through a real errwatch handler (what it pushes, what the daily
report's 「中继自己记下的报错」 shows):
* the drop is INFO with its diag line; resubscribed by itself -> ONE WARNING
  marked recovered, saying how long it was down, with the diag line: not
  pushed, in the daily report tagged 「自己好了，只进日报」;
* still down at OUTAGE_ALARM_SECONDS -> ERROR, pushed; the resubscribe after
  that is still one daily-report line;
* still down when the service stops -> ERROR, pushed (a shutdown by hand is
  not the relay's own power-off);
* the relay's own power-off -> INFO, neither pushed nor in the report.
Virtual clock; win32 faked; nothing waits for real except errwatch's push thread.
"""
import logging
import sys
import tempfile
import time
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


FAKES = {}
for name in ("win32serviceutil", "win32service", "win32file", "servicemanager", "win32security",
             "win32ts", "win32profile", "wmi", "pythoncom", "win32com", "win32com.client",
             "win32api", "win32con", "win32process", "win32event"):
    FAKES[name] = _Stub(name)
FAKES["win32com"].client = FAKES["win32com.client"]     # `import win32com.client` reads the attribute
saved = {k: sys.modules.get(k) for k in [*FAKES, "service"]}
sys.modules.update(FAKES)
sys.modules.pop("service", None)
import service  # noqa: E402 - a fresh copy built on the fakes above
from ark_relay import errwatch  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402


class VClock:
    def __init__(self):
        self.now = 9000.0
        self.due = []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.now += max(0.0, s)
        for item in [d for d in self.due if d[0] <= self.now]:
            self.due.remove(item)
            item[1]()

    def at(self, delay, fn):
        self.due.append((self.now + delay, fn))


class Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def at(self, level):
        return [r for r in self.records if r.levelno == level]


class Pushes:
    """errwatch's notifier: what reached the group."""

    def __init__(self):
        self.sent = []

    def send(self, title, body, **k):
        self.sent.append((title, body))
        return []


def setup(name):
    """A logger with a recorder and a real errwatch handler on a fresh state dir."""
    state = Path(tempfile.mkdtemp(prefix="wmi-listener-"))
    rec, pushes = Records(), Pushes()
    lg = logging.getLogger(f"ark.test_wmi_listener.{name}")
    lg.propagate = False
    lg.setLevel(logging.DEBUG)
    lg.addHandler(rec)
    h = errwatch.ErrorKindAlert(pushes, state_dir=state, known={}, pace=0, retry=(0.05,))
    lg.addHandler(h)
    return lg, rec, pushes, h, state


def settle(h, pushes, want, secs=3.0):
    """Wait (real time) until errwatch has nothing left to send and `want` pushes went out."""
    end = time.time() + secs
    while time.time() < end and (h.pending() or len(pushes.sent) < want):
        time.sleep(0.02)
    time.sleep(0.1)


def daily(state):
    return errwatch.daily_section(state, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))


def watch(lg):
    return service._ProcessWatch(object(), {"ok": True}, lg, subscribe=lambda: None)


FAILURE = ("远程过程调用失败，0x800706BE", "hresult 0x80020009, scode 0x800706BE, source -, text 远程过程调用失败。")
LIVE = {"at": 0.0, "events": 3, "last": None}
orig = (service.time, service._wmi_hosts, service._uptime, errwatch.system_shutting_down)
vt = VClock()
service.time = vt
service._wmi_hosts = lambda: "winmgmt pid 1234; WmiPrvSE pids 5,6"
service._uptime = lambda: "1:00:00"
errwatch.system_shutting_down = lambda: False
try:
    print("[a drop that resubscribes by itself within 10 minutes: daily report only]")
    lg, rec, pushes, h, state = setup("recovered")
    w = watch(lg)
    w.sub = dict(LIVE, at=vt.now - 120)
    w._failed(FAILURE)
    check("the drop itself is not a WARNING or ERROR",
          [r.getMessage() for r in rec.records if r.levelno >= logging.WARNING], [])
    drop = [r.getMessage() for r in rec.at(logging.INFO) if "程序启动通知断了" in r.getMessage()]
    check("the drop is an INFO line carrying its diag line", bool(drop) and "diag: hresult" in drop[0])
    vt.sleep(25)
    w._subscribed()
    warns = rec.at(logging.WARNING)
    check("resubscribed: exactly one WARNING", len(warns), 1)
    msg = warns[0].getMessage() if warns else ""
    check("it is marked recovered (errwatch: daily report only)", bool(warns) and getattr(warns[0], errwatch.RECOVERED, False))
    check("it says how long it was down and why", "断过" in msg and "秒" in msg and "远程过程调用失败" in msg)
    check("it carries the diag line", "\ndiag: hresult" in msg)
    settle(h, pushes, 0)
    check("nothing reached the group", pushes.sent, [])
    section = daily(state)
    check("the daily report lists it, in its own words", "系统的程序启动通知断过" in section)
    check("tagged 「自己好了，只进日报」", "自己好了，只进日报" in section)
    check("the listener is healthy again", (w.down_since, w.fault, w.alive["ok"]), (None, None, True))
    h.close()

    print("\n[still down at OUTAGE_ALARM_SECONDS: ERROR, pushed; the resubscribe after it is daily only]")
    lg, rec, pushes, h, state = setup("long")
    w = watch(lg)
    w.sub = dict(LIVE, at=vt.now - 60)
    w._failed(FAILURE)
    vt.sleep(service.OUTAGE_ALARM_SECONDS + 1)
    w._failed(FAILURE)
    errors = rec.at(logging.ERROR)
    check("one ERROR at the threshold", len(errors), 1)
    check("it says how many minutes", bool(errors) and "分钟没重新订上" in errors[0].getMessage())
    settle(h, pushes, 1)
    check("it reached the group", len(pushes.sent), 1)
    vt.sleep(100)
    w._failed(FAILURE)
    check("a later failed retry of the same outage is INFO", len(rec.at(logging.ERROR)), 1)
    w._subscribed()
    warns = rec.at(logging.WARNING)
    check("back at last: one recovered WARNING that says it was pushed meanwhile",
          [(getattr(r, errwatch.RECOVERED, False), "期间报过群" in r.getMessage()) for r in warns], [(True, True)])
    settle(h, pushes, 1)
    check("still only the one push", len(pushes.sent), 1)
    h.close()

    print("\n[the service stops (a shutdown by hand) with the drop not back: ERROR, pushed]")
    lg, rec, pushes, h, state = setup("stopped")
    w = watch(lg)
    w.sub = dict(LIVE, at=vt.now - 60)
    w._failed(FAILURE)
    vt.sleep(30)
    w.stopping()
    errors = rec.at(logging.ERROR)
    check("one ERROR", len(errors), 1)
    check("it says it was still not back when the relay stopped",
          bool(errors) and "到中继停下时还没重新订上" in errors[0].getMessage())
    check("with the diag line", bool(errors) and "\ndiag: hresult" in errors[0].getMessage())
    settle(h, pushes, 1)
    check("it reached the group", len(pushes.sent), 1)
    w.stopping()
    check("a second stop call says nothing more", len(rec.at(logging.ERROR)), 1)
    h.close()

    print("\n[the stop arrives while _failed still waits for the power-off signal: pushed too]")
    lg, rec, pushes, h, state = setup("stop-in-wait")
    w = watch(lg)
    w.sub = dict(LIVE, at=vt.now - 60)
    vt.at(2.0, w.stopping)
    w._failed(FAILURE)
    check("the stop pushed it as an ERROR (with the diag known so far)",
          [("到中继停下时" in r.getMessage(), "\ndiag: " in r.getMessage()) for r in rec.at(logging.ERROR)],
          [(True, True)])
    h.close()

    print("\n[a listener that never subscribed at all: same rules]")
    lg, rec, pushes, h, state = setup("never")
    w = watch(lg)
    w._failed(FAILURE)
    check("INFO 订不上", [r.levelno for r in rec.records if "订不上" in r.getMessage()], [logging.INFO])
    w._subscribed()
    check("subscribed later: one recovered WARNING",
          [getattr(r, errwatch.RECOVERED, False) for r in rec.at(logging.WARNING)], [True])
    h.close()

    print("\n[the relay's own power-off: INFO, nothing pushed, nothing in the report]")
    lg, rec, pushes, h, state = setup("poweroff")
    errwatch._relay_poweroff[0] = lambda: True
    w = watch(lg)
    w.sub = dict(LIVE, at=vt.now - 60)
    w._failed(FAILURE)
    w.stopping()
    check("no WARNING or ERROR", [r.getMessage() for r in rec.records if r.levelno >= logging.WARNING], [])
    check("INFO says it is the power-off", any("不算故障" in r.getMessage() for r in rec.at(logging.INFO)))
    errwatch._relay_poweroff[0] = lambda: False
    settle(h, pushes, 0)
    check("nothing pushed", pushes.sent, [])
    check("nothing in the daily report", daily(state), "")
    h.close()

    print("\n[_start_process_watch hands the listener to the keeper (alive['watch'])]")
    import pythoncom  # the stub installed above
    pythoncom.CoInitialize = lambda: None
    pythoncom.CoUninitialize = lambda: None
    threads = []
    real_thread = service.threading.Thread
    service.threading.Thread = lambda target, name, daemon: types.SimpleNamespace(
        start=lambda: threads.append(name))
    alive = {"ok": True}
    try:
        ok = service._start_process_watch(object(), alive, logging.getLogger("ark.test_wmi_listener").getChild("start"))
    finally:
        service.threading.Thread = real_thread
    check("started", (ok, threads), (True, ["proc-watch"]))
    check("the listener is reachable for stopping()", isinstance(alive.get("watch"), service._ProcessWatch))
finally:
    (service.time, service._wmi_hosts, service._uptime, errwatch.system_shutting_down) = orig
    errwatch._relay_poweroff[0] = lambda: False
    for key, v in saved.items():
        if v is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = v

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
