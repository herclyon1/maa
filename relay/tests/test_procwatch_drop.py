"""The process-start listener: a shutdown is not a fault; a real drop is INFO with its evidence and decided by whether it comes back.

Real records:
* 2026-09-17 10:48:40 and 2026-09-18 02:20 (a `shutdown /s` typed by hand): the
  listener logged ERROR when Windows took WMI down at shutdown; the second one
  rang the group. The fix of the day relied on SERVICE_CONTROL_SHUTDOWN
  reaching SvcStop, but pywin32 (311, ServiceFramework.GetAcceptedControls)
  only accepts that control when the class defines SvcShutdown - it did not,
  so the SCM never sent it.
* 2026-10-05 22:45:46, 37 s after a service restart: 「进程启动事件监听中断」, the
  74th since August, com_error scode 0x800706BE 「远程过程调用失败」; resubscribed
  5 s later. Every ERROR and WARNING now reaches the group (2026-10-06), so the
  line has to read as plain Chinese and carry what tells its causes apart.

* the user, 2026-10-06 05:07, on faults the relay recovered from by itself:
  「报错后自己好了的，只进日报、不进群」. So the drop is INFO with its evidence;
  resubscribed by itself it is ONE WARNING marked errwatch.recovered() (daily
  report only) carrying that evidence; still down after 10 minutes, or when
  the service stops (a shutdown by hand), it is an ERROR (pushed).

Everything runs on the main thread: threading.Thread is swapped for one that
runs its target in start(), and time is a virtual clock, so the old and the new
code take exactly the same path and nothing waits for real.
"""
import gc
import logging
import subprocess
import sys
import threading
import types
import weakref
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


# ---------- fakes: pywin32's service framework (311, verbatim logic), WMI ----------

w32svc = _Stub("win32service")
w32svc.SERVICE_ACCEPT_STOP, w32svc.SERVICE_ACCEPT_PAUSE_CONTINUE, w32svc.SERVICE_ACCEPT_SHUTDOWN = 1, 2, 4
(w32svc.SERVICE_CONTROL_STOP, w32svc.SERVICE_CONTROL_PAUSE, w32svc.SERVICE_CONTROL_CONTINUE,
 w32svc.SERVICE_CONTROL_INTERROGATE, w32svc.SERVICE_CONTROL_SHUTDOWN) = 1, 2, 3, 4, 5
w32svc.SC_MANAGER_CONNECT, w32svc.SERVICE_QUERY_STATUS = 1, 4
w32svc.OpenSCManager = lambda *a: "scm"
w32svc.OpenService = lambda scm, name, access: f"svc:{name}"
w32svc.QueryServiceStatusEx = lambda h: {"ProcessId": 1234} if h == "svc:winmgmt" else {}
w32svc.CloseServiceHandle = lambda h: None


class ServiceFramework:
    """GetAcceptedControls and ServiceCtrlHandlerEx as pywin32 311 has them (win32/lib/win32serviceutil.py)."""

    def GetAcceptedControls(self):  # noqa: N802 - pywin32's name
        accepted = 0
        if hasattr(self, "SvcStop"):
            accepted |= w32svc.SERVICE_ACCEPT_STOP
        if hasattr(self, "SvcPause") and hasattr(self, "SvcContinue"):
            accepted |= w32svc.SERVICE_ACCEPT_PAUSE_CONTINUE
        if hasattr(self, "SvcShutdown"):
            accepted |= w32svc.SERVICE_ACCEPT_SHUTDOWN
        return accepted

    def ServiceCtrlHandlerEx(self, control, event_type, data):  # noqa: N802 - pywin32's name
        if control == w32svc.SERVICE_CONTROL_STOP:
            return self.SvcStop()
        elif control == w32svc.SERVICE_CONTROL_PAUSE:
            return self.SvcPause()
        elif control == w32svc.SERVICE_CONTROL_CONTINUE:
            return self.SvcContinue()
        elif control == w32svc.SERVICE_CONTROL_INTERROGATE:
            return self.SvcInterrogate()
        elif control == w32svc.SERVICE_CONTROL_SHUTDOWN:
            return self.SvcShutdown()
        return None


w32su = _Stub("win32serviceutil")
w32su.ServiceFramework = ServiceFramework

w32event = _Stub("win32event")
set_events = []
w32event.SetEvent = lambda h: set_events.append(h)
w32event.CreateEvent = lambda *a: object()
w32event.WAIT_OBJECT_0, w32event.INFINITE, w32event.QS_ALLINPUT = 0, 0xFFFFFFFF, 0x04FF
# Every wait ends on "a message is waiting": the pump below then delivers the
# subscription's next scripted callback, or raises what ends it.
w32event.MsgWaitForMultipleObjects = lambda handles, wait_all, ms, mask: len(handles)

pythoncom = types.ModuleType("pythoncom")
co = {"init": 0, "uninit": 0}
pythoncom.CoInitialize = lambda: co.__setitem__("init", co["init"] + 1)
pythoncom.CoUninitialize = lambda: co.__setitem__("uninit", co["uninit"] + 1)
live = []     # the SWbemSink of the subscription made last


def _pump():
    """PumpWaitingMessages: WMI's next callback into the live sink (Source.deliver)."""
    if live:
        live[-1]._src.deliver(live[-1])
    return 0


pythoncom.PumpWaitingMessages = _pump


class com_error(Exception):   # pywintypes' own name, which the code matches on
    pass


# relay.log / docs/PITFALLS.md, verbatim
RPC_FAILED = (-2147352567, "发生意外。", (0, "SWbemEventSource", "远程过程调用失败。 ", None, 0, -2147023170), None)


class _Stop(BaseException):
    """Ends a scenario: neither the old nor the new listener catches it."""


class VClock:
    """time.monotonic / time.sleep on a virtual clock, with callbacks due at given moments."""

    def __init__(self):
        self.now, self.due = 1000.0, []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.now += max(0.0, s)
        for item in [d for d in self.due if d[0] <= self.now]:
            self.due.remove(item)
            item[1]()

    def at(self, delay, fn):
        self.due.append((self.now + delay, fn))

    def time(self):
        return self.now


class Source:
    """What WMI does with one asynchronous subscription: `events` OnObjectReady
    callbacks, then the pump raises a fresh `then()` (what ended the old
    semisynchronous NextEvent - the drop's com_error, a Python error, or _Stop).

    Fresh, and not kept here: an exception stored on the source would hold the
    source through its own traceback, and the release check would see a cycle
    rather than the listener's reference.
    """
    made = []

    def __init__(self, events, then, on_raise=None):
        self.left, self.then, self.on_raise = events, then, on_raise
        Source.made.append(weakref.ref(self))

    def deliver(self, sink):
        if self.left:
            self.left -= 1
            sink.OnObjectReady(object(), None)
            return
        if self.on_raise:
            self.on_raise()
        raise self.then()


class Sink:
    """The makepy SWbemSink class in front of the listener's handler class."""

    def Cancel(self):  # noqa: N802 - the COM method's name
        self._src = None
        if live and live[-1] is self:
            live.pop()


class Services:
    def __init__(self, script, seen):
        self.script, self.seen = script, seen

    def ExecNotificationQueryAsync(self, sink, q):  # noqa: N802
        # Which earlier subscriptions are still referenced while this one is registered.
        self.seen.append(sum(1 for r in Source.made if r() is not None))
        step = self.script.pop(0)
        if isinstance(step, type) and issubclass(step, BaseException):
            raise step()
        if isinstance(step, tuple):
            raise com_error(*step)
        sink._src = step()
        live.append(sink)


def make_client(script, seen):
    client = types.ModuleType("win32com.client")
    client.GetObject = lambda moniker: Services(script, seen)
    client.DispatchWithEvents = lambda progid, user_class: type("COMEventClass", (Sink, user_class), {})()
    pkg = types.ModuleType("win32com")
    pkg.client = client
    return pkg, client


class SyncThread:
    def __init__(self, target=None, name=None, daemon=None, **kw):
        self._target = target

    def start(self):
        self._target()


FAKES = {"win32service": w32svc, "win32serviceutil": w32su, "win32event": w32event,
         "pythoncom": pythoncom}
for name in ("win32api", "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi"):
    FAKES[name] = _Stub(name)
saved = {k: sys.modules.get(k) for k in [*FAKES, "win32com", "win32com.client", "service"]}
sys.modules.update(FAKES)
sys.modules.pop("service", None)
import service  # noqa: E402 - a fresh copy built on the fakes above
from ark_relay import errwatch, texts  # noqa: E402

orig_ssd, orig_time, orig_run = errwatch.system_shutting_down, service.time, subprocess.run
errwatch.system_shutting_down = lambda: False


def fake_run(cmd, **kw):
    key = " ".join(cmd).lower()
    out = b""
    if "wmiprvse" in key:
        out = b'"WmiPrvSE.exe","5","Services","0","9,000 K"\r\n"WmiPrvSE.exe","6","Services","0","9,000 K"\r\n'
    return types.SimpleNamespace(stdout=out, returncode=0)


subprocess.run = fake_run


class Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def at(self, level):
        return [r for r in self.records if r.levelno == level]

    def faults(self):
        return [r for r in self.records if r.levelno >= logging.WARNING]

    def loud(self):
        """What errwatch pushes to the group: WARNING / ERROR not marked recovered."""
        return [r for r in self.faults() if not getattr(r, errwatch.RECOVERED, False)]

    def recovered(self):
        return [r for r in self.faults() if getattr(r, errwatch.RECOVERED, False)]


def stop(alive):
    """The service's stop reaching the listener (_AutomasKeeper.stopping); absent before 2026-10-06."""
    watch = alive.get("watch")
    if watch is not None and hasattr(watch, "stopping"):
        watch.stopping()


def scenario(script, before=None):
    """Run the listener over `script` until it ends; returns (records, alive, refs seen at each subscribe)."""
    rec = Records()
    gc.collect()
    Source.made.clear()
    live.clear()
    log = logging.getLogger(f"ark.test.procwatch.{id(script)}")
    log.propagate = False
    log.setLevel(logging.DEBUG)
    log.addHandler(rec)
    seen = []
    pkg, client = make_client(script, seen)
    sys.modules["win32com"], sys.modules["win32com.client"] = pkg, client
    vt = VClock()
    scenario.vt = vt      # a stop() after the run reads the same clock (stop_on_clock)
    service.time = vt
    if before:
        before(vt)
    alive = {"ok": True}
    real_thread = threading.Thread
    threading.Thread = SyncThread
    try:
        service._start_process_watch(object(), alive, log)
    except _Stop:
        pass
    finally:
        threading.Thread = real_thread
        service.time = orig_time
        errwatch._stopping.clear()
        errwatch._relay_poweroff[0] = lambda: False
    return rec, alive, seen


def stop_on_clock(alive):
    """stop() on the virtual clock the scenario ran on: the drop time is on that clock."""
    service.time = scenario.vt
    try:
        stop(alive)
    finally:
        service.time = orig_time


def relay_poweroff():
    """The relay itself issued the machine power-off (errwatch.relay_shutdown_issued)."""
    errwatch._relay_poweroff[0] = lambda: True


def first(record):
    return record.getMessage().splitlines()[0]


try:
    print("[the relay's own power-off lands 0.3 s after WMI went: INFO, not a fault]")
    rec, alive, _ = scenario([
        lambda: Source(2, lambda: com_error(*RPC_FAILED),
                       on_raise=lambda: service.time.at(0.3, relay_poweroff)),
        _Stop])
    check("no ERROR or WARNING for it", [first(r) for r in rec.faults()], [])
    check("said at INFO as the relay's own power-off",
          any("不算故障" in r.getMessage() and "中继自己发出了关机命令" in r.getMessage()
              for r in rec.at(logging.INFO)))

    print("\n[a shutdown NOT started by the relay (by hand / sc stop, 2026-09-18 02:20): pushed at the stop]")
    # The user, 2026-10-06: only the planned power-off the relay itself started may
    # stay out of the group.
    rec, alive, _ = scenario([
        lambda: Source(2, lambda: com_error(*RPC_FAILED),
                       on_raise=lambda: service.time.at(0.3, errwatch.mark_stopping)),
        _Stop])
    stop(alive)
    check("one ERROR (reaches the group), when the service stops with it not back",
          [("到中继停下时还没重新订上" in first(r)) for r in rec.loud()], [True])
    check("not called 「not a fault」", any("不算故障" in r.getMessage() for r in rec.records), False)

    print("\n[Windows shutting down by hand (10-10 04:28:51): the power-off request came first - INFO, not pushed]")
    # Real System log event: 1074 at 2026-10-09T20:27:24Z (04:27:24 Beijing), shutdown.exe as
    # INS\\Administrator. relay.log: 04:28:45 the stop notice (Windows shutdown), 04:28:51 the ERROR
    # "listener down 6 s (RPC failed, 0x800706BE), not back when the relay stopped" - pushed.
    REAL_0427 = (Path(__file__).resolve().parent / "fixtures" /
                 "system-1010-0427-manual-shutdown.xml").read_text(encoding="utf-8").splitlines()
    orig_xml = service._shutdown_event_xml

    def windows_shutdown():
        errwatch.mark_os_shutdown()
        errwatch.mark_stopping()

    try:
        service._shutdown_event_xml = lambda *a: REAL_0427
        rec, alive, _ = scenario([
            lambda: Source(2, lambda: com_error(*RPC_FAILED),
                           on_raise=lambda: service.time.at(0.3, windows_shutdown)),
            _Stop])
        errwatch.mark_os_shutdown()     # scenario() clears stopping; SvcShutdown's mark stays
        stop_on_clock(alive)
        check("no ERROR or WARNING for it", [first(r) for r in rec.loud()], [])
        check("said at INFO: who asked for the shutdown and when",
              any("不算故障" in r.getMessage() and "04:27:24" in r.getMessage() and "INS\\Administrator" in r.getMessage()
                  for r in rec.at(logging.INFO)), True)

        print("\n[Windows shutting down, but its power-off request was logged after the drop: still pushed]")
        from datetime import datetime, timedelta, timezone
        later = (datetime.now(tz=timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
        service._shutdown_event_xml = lambda *a: [REAL_0427[0].replace("2026-10-09T20:27:24.6019833Z", later)]
        rec, alive, _ = scenario([
            lambda: Source(2, lambda: com_error(*RPC_FAILED),
                           on_raise=lambda: service.time.at(0.3, windows_shutdown)),
            _Stop])
        errwatch.mark_os_shutdown()
        stop_on_clock(alive)
        check("one ERROR, as before", [("到中继停下时还没重新订上" in first(r)) for r in rec.loud()], [True])

        print("\n[Windows shutting down, System log unreadable: pushed]")
        service._shutdown_event_xml = lambda *a: None
        rec, alive, _ = scenario([
            lambda: Source(2, lambda: com_error(*RPC_FAILED),
                           on_raise=lambda: service.time.at(0.3, windows_shutdown)),
            _Stop])
        errwatch.mark_os_shutdown()
        stop_on_clock(alive)
        check("one ERROR", len(rec.loud()), 1)
    finally:
        service._shutdown_event_xml = orig_xml
        errwatch._os_shutdown.clear()

    print("\n[the relay had already issued the power-off: INFO, and the retries stay quiet]")
    rec, alive, _ = scenario([lambda: Source(0, lambda: com_error(*RPC_FAILED))] + [RPC_FAILED] * 15 + [_Stop],
                             before=lambda vt: relay_poweroff())
    check("no ERROR or WARNING through the whole outage", [first(r) for r in rec.faults()], [])

    print("\n[a drop while the machine stays up (10-05 22:45:46), back by itself: pushed - why it drops is not known (2026-10-10)]")
    rec, alive, seen = scenario([
        lambda: Source(2, lambda: com_error(*RPC_FAILED)),
        RPC_FAILED, RPC_FAILED,
        lambda: Source(0, _Stop)])
    check("nothing marked recovered (daily report only)", [first(r) for r in rec.recovered()], [])
    drop = [r for r in rec.at(logging.INFO) if "程序启动通知断了" in r.getMessage()]
    check("the drop is INFO, naming the fallback", bool(drop) and "120 秒" in first(drop[0])
          and "AUTO-MAS" in first(drop[0]), True)
    errors = rec.loud()
    check("exactly one WARNING, for the group", len(errors), 1)
    line = first(errors[0]) if errors else ""
    check("its first line (what the daily report quotes) is plain Chinese", texts.plain(line), [])
    check("it names Windows' error and its code", "远程过程调用失败" in line and "0x800706BE" in line, True)
    check("and how long it was down", "断过" in line and "秒" in line, True)
    msg = errors[0].getMessage() if errors else ""
    check("evidence: the scode", "scode 0x800706BE" in msg)
    check("evidence: how long the subscription lived and what it delivered", "subscription up" in msg and "2 events" in msg)
    check("evidence: relay and machine uptime", "relay up" in msg and "machine up" in msg)
    check("evidence: the WMI service and provider hosts at subscribe and now",
          "WMI hosts at subscribe [winmgmt pid 1234; WmiPrvSE pids 5,6] now [winmgmt pid 1234" in msg)
    check("no traceback object riding on the record (the push would quote English)",
          bool(errors and errors[0].exc_info and errors[0].exc_info[0]), False)
    check("the resubscribe failures are INFO",
          sum("还没重新订上" in r.getMessage() for r in rec.at(logging.INFO)), 2)
    check("the recovery is said (that one WARNING)", "已经自己重新订上" in msg)
    check("the dead subscription was released before the next one was made", seen[1:], [0, 0, 0])
    check("listener marked alive again after the recovery", alive["ok"], True)

    print("\n[WMI stays broken: one ERROR after 10 minutes, not one a minute; back later: daily only]")
    rec, alive, _ = scenario([lambda: Source(0, lambda: com_error(*RPC_FAILED))] + [RPC_FAILED] * 15
                             + [lambda: Source(0, _Stop)])
    check("one ERROR: the long outage (the drop itself was INFO)", len(rec.at(logging.ERROR)), 1)
    check("it says how long", any("分钟没重新订上" in first(r) for r in rec.at(logging.ERROR)))
    check("it reads as plain Chinese", [texts.plain(first(r)) for r in rec.at(logging.ERROR)], [[]])
    check("back at last: one recovered WARNING, saying it was pushed meanwhile",
          [("期间报过群" in first(r)) for r in rec.recovered()], [True])
    check("no plain WARNING", [first(r) for r in rec.at(logging.WARNING) if r not in rec.recovered()], [])

    print("\n[cannot subscribe at all, then a Python error: both INFO, both back by themselves, both pushed, both plain]")
    rec, alive, _ = scenario([RPC_FAILED, lambda: Source(0, lambda: AttributeError("NextEvent")),
                              lambda: Source(0, _Stop)])
    check("nothing marked recovered", [first(r) for r in rec.recovered()], [])
    check("the first drop says it could not subscribe (INFO)",
          any("订不上" in first(r) for r in rec.at(logging.INFO)))
    errors = rec.loud()
    check("two WARNINGs for the group", len(errors), 2)
    check("the first says it could not subscribe for a while", bool(errors) and "订不上" in first(errors[0]))
    check("the second is not passed off as a Windows error",
          len(errors) > 1 and "不是系统返回的错误" in first(errors[1]) and "AttributeError" in errors[1].getMessage())
    check("both plain", [texts.plain(first(r)) for r in errors], [[], []])

    print("\n[Windows' shutdown control reaches the service (pywin32 311 framework)]")
    svc = service.ArkRelayService.__new__(service.ArkRelayService)
    check("the service accepts SERVICE_CONTROL_SHUTDOWN",
          bool(svc.GetAcceptedControls() & w32svc.SERVICE_ACCEPT_SHUTDOWN))
    stops = []
    svc.SvcStop = lambda: stops.append("stop")
    try:
        svc.ServiceCtrlHandlerEx(w32svc.SERVICE_CONTROL_SHUTDOWN, 0, None)
    except AttributeError as exc:
        print(f"    ({exc})")
    check("and stops the way `sc stop` does (SvcStop marks stopping)", stops, ["stop"])
finally:
    errwatch.system_shutting_down = orig_ssd
    errwatch._stopping.clear()
    subprocess.run = orig_run
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
