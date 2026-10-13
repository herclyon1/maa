"""Day simulator: pywin32, pythoncom, win32com's WMI and ctypes.windll, backed by a WinState.

FakeWin(sched, win).install() puts fake modules into sys.modules before the relay is
imported: win32event, win32api, win32con, win32file, win32process, win32evtlog,
win32service, win32serviceutil, servicemanager, winerror, pythoncom, win32com(.client),
pywintypes, win32security, win32ts, win32profile, win32gui; and sets ctypes.windll.

What they answer, and from where:
  - WMI: GetObject("winmgmts:...").ExecQuery("SELECT .. FROM Win32_Process WHERE Name=..")
    returns rows of the process table (read through Properties_, as procs.py does);
    ExecNotificationQueryAsync on Win32_ProcessStartTrace registers the sink of the
    calling thread, and every matching start in the table queues OnObjectReady for that
    thread, delivered by its PumpWaitingMessages - as COM does in a single-threaded
    apartment. The subscription succeeds unless the World says WMI is down: a failing
    sink made the probe push a real ERROR after 15 sim-minutes.
  - Process handles (OpenProcess) are signalled when the table process ends;
    GetExitCodeProcess reads STILL_ACTIVE or the exit code.
  - Directory change handles (win32file.FindFirstChangeNotification and kernel32's
    FindFirstChangeNotificationW) are signalled by files_changed(path), which the World
    calls after it drops or appends a file.
  - GetTickCount64 = sim now - WinState.power_on; GetSystemMetrics(SM_SHUTTINGDOWN) is 1
    only once the shutdown countdown has run out; EvtQuery reads WinState.sys_events.
  - WTSQueryUserToken fails with 1314, as it does for the relay's service on the machine.

Waits go through W1's scheduler (design section 2), and are the only place the fakes block:
  main thread:  sched.advance(handles_ready, timeout_ms) - handles_ready() is side-effect
                free and returns the index of the first signalled handle (len(handles)
                for a queued COM message) or None; timeout_ms is None for INFINITE.
  helpers:      sched.park(timeout_s, ready) - ready() -> bool; timeout_s None = INFINITE.
Whatever either returns, the fake re-reads handles_ready() afterwards, so the result
convention of advance/park does not matter. After any signal or queued message the fake
calls sched.kick() when the scheduler has one (an optional extra, not part of the
contract) so a parked helper can be re-checked at once.

A Windows call this file does not model records "sim_errors" and raises SimAbort.
"""
from __future__ import annotations

import collections
import ctypes
import os
import re
import sys
import threading
import types

from fake_proc import SM_SHUTTINGDOWN
from fake_proc import STILL_ACTIVE
from fake_proc import Proc
from fake_proc import WinState
from fake_proc import sim_error
from fake_proc import stamp

WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
INFINITE = 0xFFFFFFFF
INVALID_HANDLE = ctypes.c_void_p(-1).value
PROC_START_QUERY = re.compile(
    r"SELECT \* FROM Win32_ProcessStartTrace WHERE ProcessName\s*=\s*'([^']+)'", re.I)
PROC_QUERY = re.compile(r"SELECT ([\w, ]+) FROM Win32_Process WHERE (.+)", re.I)
# What FormatMessage says on the machine's Chinese Windows, for the codes the relay hands it.
MESSAGES = {-2147023170: "远程过程调用失败。", 5: "拒绝访问。", 2: "系统找不到指定的文件。",
            1314: "客户端没有所需的特权。", 1060: "指定的服务未安装。"}


class error(Exception):
    """pywintypes.error: (winerror, funcname, strerror), each also an attribute."""

    def __init__(self, winerror: int = 0, funcname: str = "", strerror: str = ""):
        super().__init__(winerror, funcname, strerror)
        self.winerror, self.funcname, self.strerror = winerror, funcname, strerror


class com_error(Exception):
    """pywintypes.com_error: (hresult, strerror, excepinfo, argerror)."""

    def __init__(self, hresult: int = 0, strerror: str = "", excepinfo=None, argerror=None):
        super().__init__(hresult, strerror, excepinfo, argerror)
        self.hresult, self.strerror, self.excepinfo, self.argerror = hresult, strerror, excepinfo, argerror


class Handle:
    """A kernel object: event, mutex, process, dirwatch."""

    def __init__(self, hid: int, kind: str, *, manual: bool = True, name: str = "",
                 path: str = "", subtree: bool = False, pid: int = 0):
        self.id, self.kind, self.manual, self.name = hid, kind, manual, name
        self.path, self.subtree, self.pid = path, subtree, pid
        self.signaled = False
        self.closed = False

    def __int__(self) -> int:
        return self.id

    def __repr__(self) -> str:
        return f"<Handle {self.kind} {self.id:#x}{' set' if self.signaled else ''}>"


class _Prop:
    def __init__(self, value):
        self.Value = value


class _WbemObject:
    """An SWbemObject: properties through Properties_(name).Value only (procs.py's comment)."""

    def __init__(self, props: dict):
        self._props = props

    def Properties_(self, name: str):  # noqa: N802 - COM's name
        return _Prop(self._props[name])


class _Sub:
    def __init__(self, sink, thread: int, image: str):
        self.sink, self.thread, self.image, self.live = sink, thread, image, True


class _SinkBase:
    """What DispatchWithEvents adds to the handler class: the SWbemSink's own Cancel."""

    _fw: "FakeWin"

    def Cancel(self) -> None:  # noqa: N802 - COM's name
        self._fw.cancel_sink(self)


class _Services:
    """SWbemServices for root\\cimv2."""

    def __init__(self, fw: "FakeWin"):
        self._fw = fw

    def ExecQuery(self, query: str):  # noqa: N802 - COM's name
        return self._fw.exec_query(query)

    def ExecNotificationQueryAsync(self, sink, query: str):  # noqa: N802 - COM's name
        self._fw.subscribe(sink, query)


class _K32Fn:
    """One kernel32 function: callable, and takes restype/argtypes like a ctypes one."""

    def __init__(self, name: str, fn):
        self.__name__, self._fn = name, fn
        self.restype = self.argtypes = None

    def __call__(self, *a):
        return self._fn(*a)


class _Kernel32:
    def __init__(self, fw: "FakeWin"):
        self._fw = fw
        self._fns = {name: _K32Fn(name, fn) for name, fn in (
            ("GetTickCount64", fw.tick_count),
            ("FindFirstChangeNotificationW", fw.k32_find_first),
            ("FindNextChangeNotification", fw.k32_find_next),
            ("FindCloseChangeNotification", fw.k32_find_close),
            ("WaitForSingleObject", fw.k32_wait),
            ("CloseHandle", fw.k32_close),
            ("GetLastError", lambda: fw.last_error),
        )}

    def __getattr__(self, name: str):
        fn = self.__dict__.get("_fns", {}).get(name)
        if fn is None:
            # Relay code catches AttributeError as "not Windows": say it, or a gap here
            # would read as an ordinary Mac answer.
            fw = self.__dict__["_fw"]
            fw.sched.out("sim_errors", t=stamp(fw.sched.now()), what="kernel32 function not modelled",
                         detail=name)
            raise AttributeError(name)
        return fn


class FakeWin:
    """The fake Windows API; see the module docstring."""

    def __init__(self, sched, win: WinState):
        self.sched, self.win = sched, win
        self.last_error = 0
        self._lock = threading.RLock()
        self._next = 0x1000
        self._handles: dict[int, Handle] = {}
        self._named: dict[str, Handle] = {}
        self._subs: list[_Sub] = []
        self._msgs: dict[int, collections.deque] = collections.defaultdict(collections.deque)
        self.modules: dict[str, types.ModuleType] = {}
        win.procs.on_start.append(self._on_proc_start)
        win.procs.on_exit.append(self._on_proc_exit)

    # ------------------------------------------------------------ World-facing
    def files_changed(self, path) -> int:
        """A file under `path` changed: signal every directory watch that covers it. Returns how many."""
        p = os.path.abspath(str(path))
        hit = 0
        for h in list(self._handles.values()):
            if h.kind != "dirwatch" or h.closed:
                continue
            try:
                rel = os.path.relpath(p, h.path)
            except ValueError:
                continue
            if rel == os.curdir or rel.startswith(os.pardir):
                continue
            # Without the subtree flag only the directory's own entries count.
            if h.subtree or os.sep not in rel:
                h.signaled = True
                hit += 1
        if hit:
            self._kick()
        return hit

    def drop_wmi(self, hresult: int = -2147023170) -> int:
        """Every live process-start subscription ends with OnCompleted(hresult) (an outage)."""
        n = 0
        with self._lock:
            for s in self._subs:
                if s.live:
                    s.live = False
                    self._msgs[s.thread].append(lambda s=s: s.sink.OnCompleted(hresult, None, None))
                    n += 1
        self._kick()
        return n

    def hold_mutex(self, name: str) -> Handle:
        """A named mutex some other process holds (e.g. Global\\ArkRelayMain while the relay runs)."""
        return self._create("mutex", name=name)

    def live_subscriptions(self) -> int:
        return sum(1 for s in self._subs if s.live)

    # ------------------------------------------------------------ handles and waits
    def _create(self, kind: str, **kw) -> Handle:
        with self._lock:
            name = kw.get("name") or ""
            if name and name in self._named and not self._named[name].closed:
                self.last_error = 183    # ERROR_ALREADY_EXISTS
                return self._named[name]
            self.last_error = 0
            h = Handle(self._next, kind, **kw)
            self._next += 4
            self._handles[h.id] = h
            if name:
                self._named[name] = h
            return h

    def _h(self, h) -> Handle:
        got = h if isinstance(h, Handle) else self._handles.get(int(h)) if h is not None else None
        if got is None or got.closed:
            raise error(6, "WaitForSingleObject", "句柄无效。")
        return got

    def _kick(self) -> None:
        kick = getattr(self.sched, "kick", None)
        if kick is not None:
            kick()

    def _wait(self, handles, ms: int, msg_thread: "int | None" = None) -> int:
        hs = [self._h(h) for h in handles]

        def ready():
            for i, h in enumerate(hs):
                if h.signaled:
                    return i
            if msg_thread is not None and self._msgs.get(msg_thread):
                return len(hs)
            return None

        if ms != 0 and ready() is None:
            if threading.current_thread() is threading.main_thread():
                self.sched.advance(ready, None if ms == INFINITE else ms)
            else:
                self.sched.park(None if ms == INFINITE else ms / 1000.0, lambda: ready() is not None)
        idx = ready()
        if idx is None:
            return WAIT_TIMEOUT
        if idx < len(hs) and not hs[idx].manual:
            hs[idx].signaled = False      # an auto-reset event is consumed by the wait it ends
        return WAIT_OBJECT_0 + idx

    def set_event(self, h) -> None:
        self._h(h).signaled = True
        self._kick()

    def reset_event(self, h) -> None:
        self._h(h).signaled = False

    def close(self, h) -> None:
        got = h if isinstance(h, Handle) else self._handles.get(int(h))
        if got is not None:
            got.closed = True

    # ------------------------------------------------------------ processes
    def _on_proc_start(self, p: Proc) -> None:
        with self._lock:
            for s in self._subs:
                if s.live and s.image.lower() == p.image.lower():
                    obj = _WbemObject({"ProcessName": p.image, "ProcessID": p.pid,
                                       "ParentProcessID": p.parent})
                    self._msgs[s.thread].append(lambda s=s, obj=obj: s.sink.OnObjectReady(obj, None))
        self._kick()

    def _on_proc_exit(self, p: Proc) -> None:
        for h in list(self._handles.values()):
            if h.kind == "process" and h.pid == p.pid:
                h.signaled = True
        self._kick()

    def open_process(self, access: int, inherit: bool, pid: int) -> Handle:
        p = self.win.procs.get(int(pid))
        if p is None or not p.alive:
            raise error(87, "OpenProcess", "参数错误。")
        return self._create("process", pid=p.pid)

    def exit_code(self, h) -> int:
        p = self.win.procs.get(self._h(h).pid)
        if p is None:
            raise error(6, "GetExitCodeProcess", "句柄无效。")
        return STILL_ACTIVE if p.alive else int(p.exit_code or 0)

    # ------------------------------------------------------------ WMI
    def get_object(self, moniker: str):
        if not str(moniker).lower().startswith("winmgmts:"):
            raise sim_error(self.sched, "COM moniker not modelled", str(moniker))
        if not self.win.wmi_ok:
            raise com_error(-2147217405, "OLE error 0x80041003", None, None)
        return _Services(self)

    def exec_query(self, query: str) -> list:
        m = PROC_QUERY.fullmatch(query.strip())
        names = re.findall(r"Name\s*=\s*'([^']+)'", m.group(2)) if m else []
        if not m or not names or re.sub(r"Name\s*=\s*'[^']+'|\bOR\b", " ", m.group(2), flags=re.I).strip():
            raise sim_error(self.sched, "WMI query not modelled", query)
        want = {n.lower() for n in names}
        fields = [f.strip() for f in m.group(1).split(",")]
        out = []
        for p in self.win.procs.alive():
            if p.image.lower() in want:
                row = {"ProcessId": p.pid, "CommandLine": p.cmdline, "Name": p.image,
                       "ExecutablePath": p.exe or None}
                out.append(_WbemObject({k: row[k] for k in fields}))
        return out

    def subscribe(self, sink, query: str) -> None:
        m = PROC_START_QUERY.fullmatch(" ".join(query.split()))
        if not m:
            raise sim_error(self.sched, "WMI notification query not modelled", query)
        with self._lock:
            self._subs.append(_Sub(sink, getattr(sink, "_thread", threading.get_ident()), m.group(1)))

    def dispatch_with_events(self, progid: str, handler):
        if progid != "WbemScripting.SWbemSink":
            raise sim_error(self.sched, "COM object not modelled", progid)
        cls = type("SWbemSink", (handler, _SinkBase), {})
        sink = cls()
        sink._fw = self
        sink._thread = threading.get_ident()
        return sink

    def cancel_sink(self, sink) -> None:
        with self._lock:
            for s in self._subs:
                if s.sink is sink:
                    s.live = False
            self._subs = [s for s in self._subs if s.live]

    def pump(self) -> int:
        """PumpWaitingMessages: run the COM callbacks queued for this thread."""
        q = self._msgs.get(threading.get_ident())
        while q:
            q.popleft()()
        return 0

    # ------------------------------------------------------------ dir watches
    def find_first(self, path, subtree, flags) -> Handle:
        p = os.path.abspath(str(path))
        if not os.path.isdir(p):
            raise error(3, "FindFirstChangeNotification", "系统找不到指定的路径。")
        return self._create("dirwatch", path=p, subtree=bool(subtree))

    def find_next(self, h) -> None:
        got = self._h(h)
        if got.kind != "dirwatch":
            raise error(6, "FindNextChangeNotification", "句柄无效。")
        got.signaled = False

    def k32_find_first(self, path, subtree, flags) -> int:
        try:
            return self.find_first(path, subtree, flags).id
        except error as exc:
            self.last_error = exc.winerror
            return INVALID_HANDLE

    def k32_find_next(self, hid) -> int:
        try:
            self.find_next(hid)
        except error as exc:
            self.last_error = exc.winerror
            return 0
        return 1

    def k32_find_close(self, hid) -> int:
        self.close(hid)
        return 1

    def k32_wait(self, hid, ms) -> int:
        return self._wait([hid], ms)

    def k32_close(self, hid) -> int:
        self.close(hid)
        return 1

    def tick_count(self) -> int:
        return int((self.sched.now() - self.win.power_on) * 1000)

    # ------------------------------------------------------------ the System log
    def evt_query(self, path, flags, query):
        if path != "System":
            raise sim_error(self.sched, "event log channel not modelled", str(path))
        try:
            evs = self.win.query_events(query, self.sched.now(), newest_first=bool(flags & 0x200))
        except ValueError as exc:
            raise sim_error(self.sched, "event log query not modelled", str(exc)) from None
        return iter(evs)

    @staticmethod
    def evt_next(cursor, count, *a, **k) -> tuple:
        got = []
        for ev in cursor:
            got.append(ev)
            if len(got) >= count:
                break
        return tuple(got)

    # ------------------------------------------------------------ services
    def query_service(self, h) -> dict:
        svc = self.win.services.get(h.path.lower()) if isinstance(h, Handle) else None
        if svc is None:
            raise error(1060, "QueryServiceStatusEx", MESSAGES[1060])
        state = {"RUNNING": 4, "STOPPED": 1, "START_PENDING": 2, "STOP_PENDING": 3}[svc["state"]]
        return {"ServiceType": 0x20, "CurrentState": state, "ControlsAccepted": 1, "Win32ExitCode": 0,
                "ServiceSpecificExitCode": 0, "CheckPoint": 0, "WaitHint": 0,
                "ProcessId": svc["pid"] if state == 4 else 0, "ServiceFlags": 0}

    def open_service(self, scm, name: str, access: int) -> Handle:
        if name.lower() not in self.win.services:
            raise error(1060, "OpenService", MESSAGES[1060])
        return self._create("service", path=name)

    def format_message(self, code: int) -> str:
        if code in MESSAGES:
            return MESSAGES[code] + "\r\n"
        raise error(317, "FormatMessage", "系统无法在消息文件中为 %1 找到消息号为 0x%2 的消息文本。")

    # ------------------------------------------------------------ installing
    def _not_modelled(self, what: str):
        def fn(*a, **k):
            raise sim_error(self.sched, "Windows call not modelled", what)
        return fn

    def install(self) -> "FakeWin":
        mods = self.modules
        for name in ("win32event", "win32api", "win32con", "win32file", "win32process", "win32evtlog",
                     "win32service", "win32serviceutil", "servicemanager", "winerror", "pythoncom",
                     "win32com", "win32com.client", "pywintypes", "win32security", "win32ts",
                     "win32profile", "win32gui"):
            mods[name] = types.ModuleType(name)
        m = types.SimpleNamespace(**mods)
        m.win32com.client = mods["win32com.client"]

        pt = mods["pywintypes"]
        pt.error, pt.com_error, pt.HANDLE = error, com_error, int

        ev = mods["win32event"]
        ev.WAIT_OBJECT_0, ev.WAIT_TIMEOUT, ev.INFINITE = WAIT_OBJECT_0, WAIT_TIMEOUT, INFINITE
        ev.WAIT_ABANDONED_0, ev.WAIT_FAILED, ev.QS_ALLINPUT = 0x80, 0xFFFFFFFF, 0x4FF
        ev.CreateEvent = lambda sa, manual, initial, name=None: self._mk_event(manual, initial, name)
        ev.CreateMutex = lambda sa, initial, name=None: self._create("mutex", name=name or "")
        ev.OpenEvent = lambda access, inherit, name: self._open_named(name, "OpenEvent")
        ev.OpenMutex = lambda access, inherit, name: self._open_named(name, "OpenMutex")
        ev.SetEvent, ev.ResetEvent = self.set_event, self.reset_event
        ev.WaitForSingleObject = lambda h, ms: self._wait([h], ms)
        ev.WaitForMultipleObjects = self._wait_multiple
        ev.MsgWaitForMultipleObjects = lambda handles, wait_all, ms, mask: self._wait_multiple(
            handles, wait_all, ms, msg_thread=threading.get_ident())

        api = mods["win32api"]
        api.CloseHandle = self.close
        api.OpenProcess = self.open_process
        api.GetLastError = lambda: self.last_error
        api.GetSystemMetrics = lambda i: int(self.win.shutting_down) if i == SM_SHUTTINGDOWN else 0
        api.FormatMessage = self.format_message
        api.GetCurrentProcess = lambda: -1
        api.GetModuleHandle = lambda *a: 0x400000
        api.GetTickCount = lambda: self.tick_count() & 0xFFFFFFFF

        con = mods["win32con"]
        for n, v in dict(SYNCHRONIZE=0x100000, FILE_NOTIFY_CHANGE_FILE_NAME=0x1, FILE_NOTIFY_CHANGE_DIR_NAME=0x2,
                         FILE_NOTIFY_CHANGE_LAST_WRITE=0x10, MAXIMUM_ALLOWED=0x2000000, CREATE_NEW_CONSOLE=0x10,
                         STARTF_USESHOWWINDOW=1, SW_SHOWMINNOACTIVE=7, SW_HIDE=0, WM_QUERYENDSESSION=0x11,
                         WM_ENDSESSION=0x16, PROCESS_QUERY_LIMITED_INFORMATION=0x1000,
                         EVENT_MODIFY_STATE=0x2).items():
            setattr(con, n, v)

        fl = mods["win32file"]
        fl.FindFirstChangeNotification = self.find_first
        fl.FindNextChangeNotification = self.find_next
        fl.FindCloseChangeNotification = self.close

        pr = mods["win32process"]
        pr.GetExitCodeProcess = self.exit_code
        pr.STARTUPINFO = types.SimpleNamespace
        pr.CREATE_UNICODE_ENVIRONMENT, pr.CREATE_NEW_CONSOLE = 0x400, 0x10
        pr.CreateProcessAsUser = self._not_modelled("win32process.CreateProcessAsUser")

        el = mods["win32evtlog"]
        el.EvtQueryChannelPath, el.EvtQueryReverseDirection, el.EvtRenderEventXml = 0x1, 0x200, 1
        el.EvtQuery = self.evt_query
        el.EvtNext = self.evt_next
        el.EvtRender = lambda e, flags: e.xml()

        sv = mods["win32service"]
        for n, v in dict(SERVICE_STOPPED=1, SERVICE_START_PENDING=2, SERVICE_STOP_PENDING=3, SERVICE_RUNNING=4,
                         SC_MANAGER_CONNECT=0x1, SERVICE_QUERY_STATUS=0x4, SERVICE_QUERY_CONFIG=0x1,
                         SERVICE_AUTO_START=2, SERVICE_DISABLED=4).items():
            setattr(sv, n, v)
        sv.OpenSCManager = lambda machine, db, access: self._create("scm")
        sv.OpenService = self.open_service
        sv.QueryServiceStatusEx = self.query_service
        sv.CloseServiceHandle = self.close
        sv.QueryServiceConfig = self._not_modelled("win32service.QueryServiceConfig")

        su = mods["win32serviceutil"]

        class ServiceFramework:
            def __init__(self, args=None):
                pass

            def ReportServiceStatus(self, *a, **k):  # noqa: N802 - pywin32's name
                pass

        su.ServiceFramework = ServiceFramework
        su.QueryServiceStatus = lambda name: tuple(
            self.query_service(self.open_service(None, name, 0))[k]
            for k in ("ServiceType", "CurrentState", "ControlsAccepted", "Win32ExitCode",
                      "ServiceSpecificExitCode", "CheckPoint", "WaitHint"))
        su.StartService = self._not_modelled("win32serviceutil.StartService")

        sm = mods["servicemanager"]
        sm.LogMsg = sm.LogErrorMsg = sm.LogInfoMsg = lambda *a: None
        sm.EVENTLOG_INFORMATION_TYPE, sm.EVENTLOG_ERROR_TYPE, sm.PYS_SERVICE_STARTED = 4, 1, 0x1000

        we = mods["winerror"]
        we.ERROR_ALREADY_EXISTS, we.ERROR_FILE_NOT_FOUND, we.ERROR_ACCESS_DENIED = 183, 2, 5

        pc = mods["pythoncom"]
        pc.CoInitialize = pc.CoUninitialize = lambda *a: None
        pc.CoInitializeEx = lambda *a: None
        pc.PumpWaitingMessages = self.pump
        pc.com_error = com_error

        cc = mods["win32com.client"]
        cc.GetObject = self.get_object
        cc.DispatchWithEvents = self.dispatch_with_events
        cc.Dispatch = self._not_modelled("win32com.client.Dispatch")

        sec = mods["win32security"]
        for n, v in dict(TOKEN_QUERY=0x8, TOKEN_ADJUST_PRIVILEGES=0x20, SE_PRIVILEGE_ENABLED=0x2,
                         SE_TCB_NAME="SeTcbPrivilege", SecurityImpersonation=2, TokenPrivileges=3,
                         TokenPrimary=1).items():
            setattr(sec, n, v)
        sec.OpenProcessToken = lambda proc, access: self._create("token")
        sec.LookupPrivilegeValue = lambda system, name: (0, 7)
        # The service account does not hold SeTcbPrivilege on the machine (R30): none listed.
        sec.GetTokenInformation = lambda tok, cls: [] if cls == 3 else self._not_modelled(
            "win32security.GetTokenInformation")()
        sec.AdjustTokenPrivileges = self._not_modelled("win32security.AdjustTokenPrivileges")
        sec.DuplicateTokenEx = self._not_modelled("win32security.DuplicateTokenEx")

        ts = mods["win32ts"]
        ts.WTSGetActiveConsoleSessionId = lambda: 1

        def query_token(session):
            raise error(1314, "WTSQueryUserToken", MESSAGES[1314])
        ts.WTSQueryUserToken = query_token

        mods["win32profile"].CreateEnvironmentBlock = self._not_modelled("win32profile.CreateEnvironmentBlock")
        for n in ("WNDCLASS", "RegisterClass", "CreateWindow", "PumpMessages", "DefWindowProc"):
            setattr(mods["win32gui"], n, self._not_modelled(f"win32gui.{n}"))

        sys.modules.update(mods)
        ctypes.windll = types.SimpleNamespace(kernel32=_Kernel32(self))
        return self

    def _mk_event(self, manual, initial, name) -> Handle:
        h = self._create("event", manual=bool(manual), name=name or "")
        if initial and self.last_error != 183:
            h.signaled = True
        return h

    def _open_named(self, name: str, func: str) -> Handle:
        h = self._named.get(name)
        if h is None or h.closed:
            raise error(2, func, "系统找不到指定的文件。")
        return h

    def _wait_multiple(self, handles, wait_all, ms, msg_thread=None) -> int:
        if wait_all:
            raise sim_error(self.sched, "Windows call not modelled", "WaitForMultipleObjects(wait_all=True)")
        return self._wait(list(handles), ms, msg_thread)
