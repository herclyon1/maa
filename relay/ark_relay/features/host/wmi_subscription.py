"""One asynchronous WMI subscription to python.exe starts that another thread can cancel (_AsyncSubscription).

Split out of relay/service.py (2026-10-11); behaviour unchanged.
"""
from __future__ import annotations

import win32api
import win32con
import win32event

from ark_relay.features.host import wmi_diag


# The process-start subscription (_AsyncSubscription).
PROC_START_QUERY = "SELECT * FROM Win32_ProcessStartTrace WHERE ProcessName = 'python.exe'"


class _AsyncSubscription:
    """One asynchronous WMI subscription to python.exe starts, which can be cancelled.

    SWbemServices.ExecNotificationQueryAsync "returns immediately and the
    results and status are returned to the caller through events delivered to
    the sink" - OnObjectReady per event, OnCompleted when the call ends
    (https://learn.microsoft.com/en-us/windows/win32/wmisdk/swbemservices-execnotificationqueryasync)
    - and SWbemSink.Cancel ends it: "You cannot assign this sink to Nothing to
    cancel an asynchronous operation. You must call the Cancel method"
    (https://learn.microsoft.com/en-us/windows/win32/wmisdk/swbemsink-cancel).
    It replaced the semisynchronous ExecNotificationQuery (2026-10-10), whose
    NextEvent() blocks inside COM with no way for another thread to end it, so
    the relay exited with the subscription still live (_ProcessWatch).

    Everything here runs on the listener's thread, in its single-threaded
    apartment: COM delivers the sink's callbacks there as window messages, so
    wait() sleeps in MsgWaitForMultipleObjects on [the stop event, the WMI
    service host] plus any message (QS_ALLINPUT), with no timeout, and pumps
    the messages (PumpWaitingMessages) when one arrives. The queue is pumped
    before every wait, since a message already looked at does not wake
    MsgWaitForMultipleObjects again
    (https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-msgwaitformultipleobjects).

    The WMI service host's process is in the wait as well (opened for
    SYNCHRONIZE, the WMI service runs in its own svchost on this machine:
    svchost.exe_Winmgmt in the crash records): no Microsoft page says whether an
    asynchronous call is told through OnCompleted when that host dies, and a
    drop nobody hears would leave the main loop trusting a dead listener.
    Without the handle (pid unreadable), OnCompleted is the only drop signal.
    """

    def __init__(self, stop):
        import pythoncom  # noqa: PLC0415
        import win32com.client  # noqa: PLC0415
        self._pythoncom = pythoncom
        self._stop = stop
        box = self._box = {"events": 0, "done": None}

        class Sink:
            """The SWbemSink events this subscription needs (pywin32 DispatchWithEvents handler names)."""

            def OnObjectReady(self, objWbemObject, objWbemAsyncContext):  # noqa: N802 - COM's names
                box["events"] += 1

            def OnCompleted(self, iHResult, objWbemErrorObject, objWbemAsyncContext):  # noqa: N802 - COM's names
                box["done"] = iHResult

        self._host_pid, self._host = None, None
        pid = wmi_diag._winmgmt_pid()
        if pid:
            try:
                self._host = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
                self._host_pid = pid
            except Exception:  # noqa: BLE001 - optional: OnCompleted still reports drops
                self._host = None
        self._services = self._sink = None
        try:
            self._services = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
            self._sink = win32com.client.DispatchWithEvents("WbemScripting.SWbemSink", Sink)
            self._services.ExecNotificationQueryAsync(self._sink, PROC_START_QUERY)
        except BaseException:
            self.cancel()
            raise

    def wait(self):
        """Sleep until something happens: "event" (one process start), "stop", or ("done", (why, detail))."""
        handles = [self._stop] + ([self._host] if self._host is not None else [])
        while True:
            self._pythoncom.PumpWaitingMessages()
            if self._box["events"]:
                self._box["events"] -= 1
                return "event"
            if self._box["done"] is not None:
                return "done", wmi_diag._hresult_failure(self._box["done"])
            rc = win32event.MsgWaitForMultipleObjects(handles, False, win32event.INFINITE,
                                                      win32event.QS_ALLINPUT)
            if rc == win32event.WAIT_OBJECT_0:
                return "stop"
            if rc == win32event.WAIT_OBJECT_0 + 1 and self._host is not None:
                return "done", ("系统里发这项通知的服务停了",
                                f"winmgmt host pid {self._host_pid} exited under the subscription "
                                f"(its process handle was signalled)")
            if rc != win32event.WAIT_OBJECT_0 + len(handles):
                raise OSError(f"MsgWaitForMultipleObjects returned {rc}")
            # A message: pumped at the top of the loop.

    def cancel(self) -> None:
        """Cancel the call and let go of every COM object and handle. Never raises; a second call does nothing."""
        sink, self._sink, self._services = self._sink, None, None
        if sink is not None:
            try:
                sink.Cancel()
            except Exception:  # noqa: BLE001 - after a drop the call may be gone already
                pass
            sink = None
        host, self._host = self._host, None
        if host is not None:
            try:
                win32api.CloseHandle(host)
            except Exception:  # noqa: BLE001
                pass
