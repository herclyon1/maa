"""The process-start listener never leaves a live WMI subscription behind when the relay exits.

The incident (relay.log and the machine's event logs, 2026-10-06, Beijing time):
    18:07:28 the stop line 「主流程已返回…还活着的线程：…、proc-watch」
             - the process exits with the listener still blocked in
             SWbemEventSource.NextEvent() on a live semisynchronous subscription
    18:07:47 the new relay process subscribes again
    18:08:04 System log 7031: the Windows Management Instrumentation service
             terminated unexpectedly (Application Error 1000: svchost.exe_Winmgmt,
             ntdll.dll, 0xc0000005, the same WER bucket every time)
    18:08:22 the relay's own drop line, with Windows' error 0x800706BE:
             「…程序启动通知断了（远程过程调用失败…）」 (remote procedure call failed)
11 of the 12 Winmgmt crashes since 08-24 came 6-100 s after such a restart.

Pinned here, with the real listener thread and the real asynchronous
subscription code (_AsyncSubscription) running on fake COM / win32event:
1. stopping() cancels the live subscription (SWbemSink.Cancel, on the
   listener's own thread), the listener drops it, uninitialises COM on that
   thread, and the thread has ended before stopping() returns - one INFO line;
2. a dropped subscription (OnCompleted with 0x800706BE) is cancelled and
   released, then resubscribed exactly as before, with the same drop line;
3. OnObjectReady sets the wake-up event the main loop waits on;
4. the WMI service host exiting under the subscription is a drop as well;
5. a stop during the backoff waits for nothing and subscribes nothing new;
6. a cancel that cannot finish within the bound is one WARNING, and the stop
   goes on.
"""
import gc
import logging
import sys
import threading
import time
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


# ---------- a fake kernel: waitable objects and one STA message queue ----------

COND = threading.Condition()
MESSAGES = []          # callbacks COM would deliver to the listener's STA as window messages


class Waitable:
    def __init__(self, name):
        self.name, self.signalled = name, False

    def set(self):
        with COND:
            self.signalled = True
            COND.notify_all()


def post(fn):
    """WMI calling back into the sink: delivered only when the STA pumps."""
    with COND:
        MESSAGES.append(fn)
        COND.notify_all()


w32event = _Stub("win32event")
w32event.WAIT_OBJECT_0, w32event.INFINITE, w32event.QS_ALLINPUT = 0, 0xFFFFFFFF, 0x04FF
set_events = []


def _create_event(sa, manual, initial, name):
    return Waitable("event")


def _set_event(h):
    set_events.append(h)
    if isinstance(h, Waitable):
        h.set()


waits = []


def _msg_wait(handles, wait_all, ms, mask):
    """MsgWaitForMultipleObjects: the first signalled handle's index, or len(handles) for a message."""
    waits.append((threading.current_thread().name, ms, mask))
    deadline = time.time() + 10      # a hung test fails instead of hanging
    with COND:
        while time.time() < deadline:
            for i, h in enumerate(handles):
                if isinstance(h, Waitable) and h.signalled:
                    return w32event.WAIT_OBJECT_0 + i
            if MESSAGES:
                return w32event.WAIT_OBJECT_0 + len(handles)
            COND.wait(0.05)
    raise RuntimeError("fake MsgWaitForMultipleObjects: nothing happened in 10 s")


w32event.CreateEvent, w32event.SetEvent, w32event.MsgWaitForMultipleObjects = _create_event, _set_event, _msg_wait

calls = []      # (what, thread name) in order


pythoncom = types.ModuleType("pythoncom")
pythoncom.CoInitialize = lambda: calls.append(("CoInitialize", threading.current_thread().name))
pythoncom.CoUninitialize = lambda: calls.append(("CoUninitialize", threading.current_thread().name))


def _pump():
    with COND:
        todo = MESSAGES[:]
        MESSAGES.clear()
    for fn in todo:
        fn()
    return 0


pythoncom.PumpWaitingMessages = _pump


class com_error(Exception):   # pywintypes' own name, which the code matches on
    pass


pythoncom.com_error = com_error

# WMI scripting: SWbemServices.ExecNotificationQueryAsync with an SWbemSink.
sinks = []
cancel_block = [None]     # a threading.Event Cancel waits on, to make it hang


class FakeSink:
    """The makepy SWbemSink class DispatchWithEvents puts in front of the user's handler class."""

    def __init__(self):
        self.cancelled = 0
        self.query = None

    def Cancel(self):  # noqa: N802 - the COM method's name
        calls.append(("Cancel", threading.current_thread().name))
        self.cancelled += 1
        if cancel_block[0] is not None:
            cancel_block[0].wait(5)


subscribed = threading.Event()
script = []      # what each ExecNotificationQueryAsync does: None = succeed, an exception = raise


class Services:
    def ExecNotificationQueryAsync(self, sink, query):  # noqa: N802 - the COM method's name
        calls.append(("ExecNotificationQueryAsync", threading.current_thread().name))
        step = script.pop(0) if script else None
        if step is not None:
            raise step
        sink.query = query
        sinks.append(sink)
        subscribed.set()


client = types.ModuleType("win32com.client")
client.GetObject = lambda moniker: Services()


def _dispatch_with_events(progid, user_class):
    calls.append((f"DispatchWithEvents {progid}", threading.current_thread().name))
    cls = type("COMEventClass", (FakeSink, user_class), {})
    inst = cls()
    if "__init__" in user_class.__dict__:
        user_class.__init__(inst)
    return inst


client.DispatchWithEvents = _dispatch_with_events
pkg = types.ModuleType("win32com")
pkg.client = client

w32api = _Stub("win32api")
host = {"proc": None}


def _open_process(access, inherit, pid):
    host["proc"] = Waitable(f"process {pid}")
    host["opened"] = (access, pid)
    return host["proc"]


w32api.OpenProcess = _open_process
w32api.CloseHandle = lambda h: calls.append(("CloseHandle", threading.current_thread().name))
# FormatMessage(0x800706BE) on a Chinese Windows; anything else is not in the system table.
w32api.FormatMessage = lambda code: "远程过程调用失败。\r\n" if code == -2147023170 else (_ for _ in ()).throw(
    Exception("no text"))
w32con = _Stub("win32con")
w32con.SYNCHRONIZE = 0x00100000

FAKES = {"win32event": w32event, "pythoncom": pythoncom, "win32com": pkg, "win32com.client": client,
         "win32api": w32api, "win32con": w32con}
for name in ("win32serviceutil", "win32service", "win32file", "servicemanager", "win32security",
             "win32ts", "win32profile", "wmi", "win32process"):
    FAKES[name] = _Stub(name)
saved = {k: sys.modules.get(k) for k in [*FAKES, "service"]}
sys.modules.update(FAKES)
sys.modules.pop("service", None)
import service  # noqa: E402 - a fresh copy built on the fakes above
from ark_relay import errwatch, texts  # noqa: E402


class FastTime:
    """time for the listener: monotonic is real plus whatever sleep skipped; sleep returns at once."""

    def __init__(self):
        self.skipped = 0.0
        self.slept = []
        self.gate = None      # a threading.Event sleep waits on (real time), to hold the listener in its backoff

    def monotonic(self):
        return time.monotonic() + self.skipped

    def time(self):
        return time.time() + self.skipped

    def sleep(self, s):
        self.slept.append(s)
        if self.gate is not None:
            self.gate.wait(5)
        self.skipped += max(0.0, s)


class Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def at(self, level):
        return [r.getMessage() for r in self.records if r.levelno == level]


orig = (service.time, service._wmi_hosts, service._uptime, service._wmi_scm_events,
        errwatch.system_shutting_down, getattr(service, "_winmgmt_pid", None))
service._wmi_hosts = lambda: "winmgmt pid 1234; WmiPrvSE pids 5,6"
service._uptime = lambda: "1:00:00"
service._wmi_scm_events = lambda: "SCM winmgmt: none in 5 min"
service._winmgmt_pid = lambda: 1234
errwatch.system_shutting_down = lambda: False


def start(name):
    """A fresh listener through _start_process_watch, its real thread running; returns (alive, evt, rec, clock)."""
    sinks.clear()
    calls.clear()
    set_events.clear()
    waits.clear()
    script.clear()
    subscribed.clear()
    cancel_block[0] = None
    with COND:
        MESSAGES.clear()
    clock = FastTime()
    service.time = clock
    rec = Records()
    log = logging.getLogger(f"ark.test.procwatch_cancel.{name}")
    log.propagate = False
    log.setLevel(logging.DEBUG)
    log.addHandler(rec)
    alive, evt = {"ok": True}, object()
    ok = service._start_process_watch(evt, alive, log)
    check("the listener started", ok, True)
    return alive, evt, rec, clock


def thread_alive():
    return any(t.name == "proc-watch" and t.is_alive() for t in threading.enumerate())


def wait_for(pred, secs=3.0):
    end = time.time() + secs
    while time.time() < end and not pred():
        time.sleep(0.01)
    return pred()


def names(what):
    return [c for c in calls if c[0] == what]


try:
    print("[1. the stop cancels the live subscription and the listener has ended before stop returns]")
    alive, evt, rec, clock = start("stop")
    check("subscribed asynchronously, with an SWbemSink", wait_for(lambda: len(sinks) == 1))
    check("the query is the python.exe start trace",
          bool(sinks) and sinks[0].query == "SELECT * FROM Win32_ProcessStartTrace WHERE ProcessName = 'python.exe'")
    check("the listener waits on messages without a timeout (no polling)",
          wait_for(lambda: bool(waits)) and waits[0] == ("proc-watch", w32event.INFINITE, w32event.QS_ALLINPUT))
    alive["watch"].stopping()
    check("Cancel was called exactly once", sinks[0].cancelled if sinks else 0, 1)
    check("on the listener's own thread (the sink lives in its apartment)",
          names("Cancel"), [("Cancel", "proc-watch")])
    check("the listener has ended by the time stopping() returns", thread_alive(), False)
    order = [c[0] for c in calls if c[0] in ("Cancel", "CoUninitialize") and c[1] == "proc-watch"]
    check("COM uninitialised on that thread, after the cancel",
          (order, names("CoUninitialize")[-1:]), (["Cancel", "CoUninitialize"], [("CoUninitialize", "proc-watch")]))
    check("one INFO line says the subscription was cancelled",
          [m for m in rec.at(logging.INFO) if "已取消" in m] != [], True)
    check("no WARNING or ERROR for a clean stop",
          [r.getMessage() for r in rec.records if r.levelno >= logging.WARNING], [])
    alive["watch"].stopping()
    check("a second stop call does nothing more", sinks[0].cancelled if sinks else 0, 1)
    gone = weakref.ref(sinks[0]) if sinks else (lambda: "no sink")
    sinks.clear()
    gc.collect()
    check("nothing holds the sink any more (every COM reference dropped)", gone(), None)

    print("\n[2. a dropped subscription (OnCompleted 0x800706BE) is released and resubscribed as before]")
    alive, evt, rec, clock = start("drop")
    wait_for(lambda: len(sinks) == 1)
    first = sinks[0]
    post(lambda: first.OnCompleted(-2147023170, None, None))
    check("resubscribed", wait_for(lambda: len(sinks) == 2))
    check("the dead subscription was cancelled before the next one was made",
          [c[0] for c in calls if c[0] in ("Cancel", "ExecNotificationQueryAsync")][:3],
          ["ExecNotificationQueryAsync", "Cancel", "ExecNotificationQueryAsync"])
    # The backoff counts from the failure: _failed's wait for the power-off signal
    # (GOING_DOWN_SETTLE_SECONDS) plus whatever is left of the first 5 s.
    check("after the backoff the drop asked for (5 s, counted from the drop)",
          round(sum(clock.slept), 1), max(service.GOING_DOWN_SETTLE_SECONDS, 5.0))
    drop = [m for m in rec.at(logging.INFO) if "程序启动通知断了" in m]
    check("the drop is the same INFO line, with Windows' words and code",
          bool(drop) and "远程过程调用失败，0x800706BE" in drop[0].splitlines()[0])
    check("its diag line carries the scode", bool(drop) and "scode 0x800706BE" in drop[0])
    check("back by itself: one recovered WARNING (daily report only)",
          wait_for(lambda: len(rec.at(logging.WARNING)) == 1)
          and getattr([r for r in rec.records if r.levelno == logging.WARNING][0], errwatch.RECOVERED, False))
    check("alive again", alive["ok"], True)
    alive["watch"].stopping()
    check("the stop cancels the second one", sinks[1].cancelled, 1)
    check("and the listener ended", thread_alive(), False)

    print("\n[3. OnObjectReady wakes the main loop]")
    alive, evt, rec, clock = start("event")
    wait_for(lambda: len(sinks) == 1)
    s = sinks[0]
    post(lambda: s.OnObjectReady(object(), None))
    post(lambda: s.OnObjectReady(object(), None))
    check("evt set once per process start", wait_for(lambda: set_events.count(evt) == 2), True)
    check("the events are counted", wait_for(lambda: alive["watch"].sub and alive["watch"].sub["events"] == 2), True)
    check("delivered on the listener's thread only", {w[0] for w in waits}, {"proc-watch"})
    alive["watch"].stopping()
    check("ended", thread_alive(), False)

    print("\n[4. the WMI service host exiting under the subscription is a drop]")
    alive, evt, rec, clock = start("host")
    wait_for(lambda: len(sinks) == 1)
    check("the WMI service host was opened for SYNCHRONIZE", host.get("opened"), (0x00100000, 1234))
    host["proc"].set()
    check("resubscribed after it", wait_for(lambda: len(sinks) == 2))
    drop = [m for m in rec.at(logging.INFO) if "程序启动通知断了" in m]
    check("the drop says the service stopped, in plain words", bool(drop) and "服务意外停了" in drop[0].splitlines()[0])
    check("the diag names the host pid", bool(drop) and "winmgmt host pid 1234" in drop[0])
    alive["watch"].stopping()
    check("ended", thread_alive(), False)

    print("\n[5. a stop during the backoff: nothing to cancel, nothing subscribed after it]")
    alive, evt, rec, clock = start("backoff")
    wait_for(lambda: len(sinks) == 1)
    clock.gate = threading.Event()
    first = sinks[0]
    post(lambda: first.OnCompleted(-2147023170, None, None))
    check("in the backoff", wait_for(lambda: len(clock.slept) == 1))
    t0 = time.time()
    alive["watch"].stopping()
    check("stopping() did not wait for the backoff", time.time() - t0 < 1.0)
    clock.gate.set()
    check("the listener then ends", wait_for(lambda: not thread_alive()))
    check("without subscribing again", len(sinks), 1)

    print("\n[6. a cancel that hangs past the bound: one WARNING, the stop goes on]")
    service_bound = getattr(service, "CANCEL_WAIT_SECONDS", None)
    service.CANCEL_WAIT_SECONDS = 0.3
    alive, evt, rec, clock = start("hang")
    wait_for(lambda: len(sinks) == 1)
    cancel_block[0] = threading.Event()
    t0 = time.time()
    alive["watch"].stopping()
    took = time.time() - t0
    check("stopping() returned within the bound", took < 1.5)
    warns = rec.at(logging.WARNING)
    check("one WARNING (not an ERROR)", (len(warns), rec.at(logging.ERROR)), (1, []))
    check("its first line is plain Chinese", bool(warns) and texts.plain(warns[0].splitlines()[0]) == [], True)
    cancel_block[0].set()
    wait_for(lambda: not thread_alive())
    if service_bound is not None:
        service.CANCEL_WAIT_SECONDS = service_bound
finally:
    (service.time, service._wmi_hosts, service._uptime, service._wmi_scm_events,
     errwatch.system_shutting_down) = orig[:5]
    if orig[5] is not None:
        service._winmgmt_pid = orig[5]
    errwatch._stopping.clear()
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
