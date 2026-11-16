"""Is the machine going down? The relay's own power-off (errwatch) and the System log's 1074 / 1075, so an exit or a dropped listener that a shutdown explains is not pushed as a fault.

Split out of relay/service.py (2026-10-11); behaviour unchanged.
"""
from __future__ import annotations

import sys as _sys
import time
import subprocess
import logging
import threading
try:
    import win32api
    import win32service
    import win32con
    import win32event
except ImportError:
    win32api = win32service = win32con = win32event = None  # type: ignore[assignment]
from datetime import datetime, timedelta, timezone
from ark_relay.core.config import SERVER_TZ
wmi_diag = _sys.modules[__name__]
shutdown_signs = _sys.modules[__name__]
wmi_subscription = _sys.modules[__name__]

# How long a failure that a shutdown would also explain - the process-start
# listener dropping, the AUTO-MAS backend exiting - waits for a sign that the
# machine is going down before it is logged as a fault. On a shutdown Windows
# closes the logged-on session and tells services to stop in no fixed order with
# each other or with WMI going down (2026-10-10 04:28 the AUTO-MAS exit came ~16 s
# before the stop notice; in the ten Windows-shutdown stops from 10-10 23:31 to
# 10-13 11:14 the stop notice came first), so either can reach us before any flag
# (errwatch.going_down) is set. The first sign ends the wait at once; no sign at
# all means it was not a shutdown, and it is logged as the fault it is.
GOING_DOWN_SETTLE_SECONDS = 15.0


# A System-log 1074 ("shutdown requested") this recent, with no 1075 ("aborted") and no
# boot (6005) after it, means an AUTO-MAS exit is the shutdown's doing. 2026-10-10:
# `shutdown /s /t 60` by hand wrote its 1074 at 04:27:24 (machine clock), AUTO-MAS exited
# ~04:28:29, the stop notice came 04:28:45; the relay's own power-offs of 10-09 21:41:51 /
# 21:49:11 wrote one too (docs/OPERATIONS.md, the 6005 / 6006 / 1074 check). The 1074 is
# written when the command is given, the countdown earlier: 120 s (until 2026-10-13)
# missed `shutdown /s /t 300` and read its exit as unexpected (audit s15 #5), so this is
# the same hour as SHUTDOWN_BEFORE_WINDOW_SECONDS. A 6005 (the Event Log service started:
# a boot) newer than the 1074 ends it - a request from before this boot is over.
# Measured (10-10, above): after a `/t 60` 1074 AUTO-MAS was gone 65 s later.
SHUTDOWN_EVENT_WINDOW_SECONDS = 3600


# The System-log events read for a standing request: requested, aborted, booted.
SHUTDOWN_EVENT_IDS = (1074, 1075, 6005)


_EVT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"


_SETTLE_STEP = 0.5


def _going_down_soon(seconds: "float | None" = None) -> bool:
    """True when the relay ITSELF has issued the machine power-off, now or within `seconds`.

    The only case where a dropped WMI link or AUTO-MAS exiting is logged at INFO
    instead of being pushed (the user, 2026-10-06: only the planned power-off the
    relay started may stay out of the group). A shutdown by hand, `sc stop` or
    Windows' own shutdown is NOT that: errwatch.relay_shutdown_issued() is false
    for them, so the event is a WARNING/ERROR and reaches the group.
    """
    from ark_relay.features import errwatch  # noqa: PLC0415
    if seconds is None:
        seconds = GOING_DOWN_SETTLE_SECONDS
    deadline = time.monotonic() + seconds
    while not errwatch.relay_shutdown_issued():
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        time.sleep(min(_SETTLE_STEP, left))
    return True


def _down_reason() -> str:
    """The words the log line uses for the relay's own power-off."""
    return "中继自己发出了关机命令"


def _shutdown_event_xml(window_s: int = SHUTDOWN_EVENT_WINDOW_SECONDS) -> "list[str] | None":
    """The System log's 1074 / 1075 / 6005 events of the last `window_s` seconds, newest first,
    as event XML; None when it cannot be read (ark_relay.features.shutdown.shutdown.shutdown_event_xml)."""
    from ark_relay.features import shutdown  # noqa: PLC0415
    return shutdown.shutdown_event_xml(window_s, SHUTDOWN_EVENT_IDS)


def shutdown_requested(xmls: "list[str]") -> "dict | None":
    """From 1074 / 1075 / 6005 event XML, newest first: the shutdown request still standing, or None.

    1074 (User32): "The process <param1> has initiated the power off of computer ... on
    behalf of user <param7>"; 1075: that shutdown was aborted; 6005: the machine booted
    (the request before it is over). The newest of the three decides. Returns
    {"clock": HH:MM:SS on the relay's clock, "process": ..., "user": ...}."""
    import xml.etree.ElementTree as ET  # noqa: PLC0415
    for x in xmls:
        try:
            ev = ET.fromstring(x)
        except ET.ParseError:
            continue
        eid = (ev.findtext(f"{_EVT_NS}System/{_EVT_NS}EventID") or "").strip()
        if eid in ("1075", "6005"):
            return None
        if eid != "1074":
            continue
        data = [d.text or "" for d in ev.iter(f"{_EVT_NS}Data")]
        stamp = ev.find(f"{_EVT_NS}System/{_EVT_NS}TimeCreated")
        clock, when = "", None
        if stamp is not None and stamp.get("SystemTime"):
            raw = stamp.get("SystemTime").rstrip("Z")
            head = raw.split(".")[0]
            try:
                when = datetime.fromisoformat(head).replace(tzinfo=timezone.utc)
                clock = when.astimezone(SERVER_TZ).strftime("%H:%M:%S")
            except ValueError:
                clock, when = "", None
        return {"clock": clock, "at": when, "process": data[0] if data else "",
                "user": data[6] if len(data) > 6 else ""}
    return None


# Our own Arknights farm scripts (the Mac-side farm scripts spa_run.py, is_run.py) power the machine off at their
# deadline (08:20, before the 08:40 plug cut) and leave this mark right before `shutdown /s`. 2026-11-13
# 08:22:20 the AUTO-MAS exit that followed one went to the group as a relay fault. Gemini 10:19: such a
# power-off is ours like the relay's own, so it stays out of the group - only when the mark names a farm
# script, its outcome is a normal end (not "failed"), the request came from shutdown.exe, and the mark was
# left at most FARM_POWEROFF_MAX_LEAD_SECONDS before that request. Anything else is pushed as before.
FARM_POWEROFF_MARK = "ark-farm-poweroff.json"
FARM_POWEROFF_SCRIPTS = ("spa_run.py", "is_run.py")
# Measured: 2026-11-13 relay.log 1074 at 08:20:06 for the farm's `shutdown /s /t 120`; the farm writes the mark
# in the same second, right before that command. 1800 s is the cap Gemini set (2026-11-13 10:19), so a mark
# from an earlier night or an earlier run never explains a later power-off.
FARM_POWEROFF_MAX_LEAD_SECONDS = 1800


def farm_poweroff_planned(asked: "dict | None", base=None) -> "dict | None":
    """The farm's own power-off mark that explains the standing request `asked` (shutdown_requested), else None.
    -> {"by": script, "at": HH:MM:SS on the relay's clock, "outcome": ...}."""
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    from ark_relay.core.config import PROGRAMDATA  # noqa: PLC0415
    if not asked or "shutdown.exe" not in str(asked.get("process") or "").lower() or asked.get("at") is None:
        return None
    try:
        mark = json.loads((Path(base or PROGRAMDATA) / FARM_POWEROFF_MARK).read_text(encoding="utf-8"))
        at = float(mark.get("at") or 0)
        by, outcome = str(mark.get("by") or ""), str(mark.get("outcome") or "")
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    lead = asked["at"].timestamp() - at
    if by not in FARM_POWEROFF_SCRIPTS or not outcome or outcome == "failed" \
            or not -SHUTDOWN_BEFORE_SLACK_SECONDS <= lead <= FARM_POWEROFF_MAX_LEAD_SECONDS:
        return None
    return {"by": by, "at": datetime.fromtimestamp(at, SERVER_TZ).strftime("%H:%M:%S"), "outcome": outcome}


# A power-off request logged up to this long after the drop began still counts as
# before it: the 1074 stamp and the monotonic drop time are read on different clocks.
SHUTDOWN_BEFORE_SLACK_SECONDS = 2


# How far back the 1074 is looked for: `shutdown -s -t N` is logged when given, N earlier.
SHUTDOWN_BEFORE_WINDOW_SECONDS = 3600


def _shutdown_before(since_mono: float) -> "dict | None":
    """The standing Windows power-off request (shutdown_requested) when Windows is shutting
    down (SvcShutdown ran) and the request was logged before the moment `since_mono`
    (time.monotonic()); else None. Unreadable System log -> None, so the caller pushes."""
    from ark_relay.features import errwatch  # noqa: PLC0415
    if not errwatch.os_shutdown():
        return None
    xmls = _shutdown_event_xml(SHUTDOWN_BEFORE_WINDOW_SECONDS)
    asked = shutdown_requested(xmls) if xmls else None
    if asked is None or asked.get("at") is None:
        return None
    began = datetime.now(tz=timezone.utc) - timedelta(seconds=time.monotonic() - since_mono)
    return asked if asked["at"] <= began + timedelta(seconds=SHUTDOWN_BEFORE_SLACK_SECONDS) else None


def _span(seconds: float) -> str:
    """A duration in words: 「45 秒」 under two minutes, 「12 分钟」 after."""
    seconds = max(0.0, float(seconds))
    return f"{seconds:.0f} 秒" if seconds < 120 else f"{seconds / 60:.0f} 分钟"


def _uptime() -> str:
    """Time since Windows booted, h:mm:ss, or '?' where it cannot be read."""
    try:
        import ctypes  # noqa: PLC0415
        k = ctypes.windll.kernel32
        k.GetTickCount64.restype = ctypes.c_ulonglong   # 64-bit; do not truncate
        s = int(k.GetTickCount64()) // 1000
    except Exception:  # noqa: BLE001 - not Windows
        return "?"
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def _winmgmt_pid() -> "int | None":
    """The WMI service's process id, as the SCM reports it; None when it cannot be read (0 when it is not running)."""
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            h = win32service.OpenService(scm, "winmgmt", win32service.SERVICE_QUERY_STATUS)
            try:
                return int(win32service.QueryServiceStatusEx(h)["ProcessId"])
            finally:
                win32service.CloseServiceHandle(h)
        finally:
            win32service.CloseServiceHandle(scm)
    except Exception:  # noqa: BLE001 - diagnostics and an optional wait handle only
        return None


def _wmi_hosts() -> str:
    """The WMI service's process id and every WmiPrvSE.exe provider host's, right now.

    Taken when the listener subscribes and again when it drops: a changed
    winmgmt pid means the WMI service itself restarted, a WmiPrvSE pid that is
    gone means a provider host died under the subscription. Neither is read
    through WMI, which may be the very thing that just broke.
    """
    parts = []
    pid = _winmgmt_pid()
    parts.append(f"winmgmt pid {pid}" if pid is not None else "winmgmt pid ?")
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WmiPrvSE.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, timeout=25).stdout.decode("ascii", "replace")
        pids = sorted(int(row.split('","')[1]) for row in out.splitlines()
                      if row.lower().startswith('"wmiprvse.exe"'))
        parts.append("WmiPrvSE pids " + (",".join(map(str, pids)) or "none"))
    except Exception:  # noqa: BLE001 - diagnostics only
        parts.append("WmiPrvSE pids ?")
    return "; ".join(parts)


def _wmi_pids(hosts: str) -> "tuple[str | None, set[str] | None]":
    """(winmgmt pid, WmiPrvSE pids) out of a _wmi_hosts() string; None for a part it could not read."""
    import re  # noqa: PLC0415
    m = re.search(r"winmgmt pid (\d+)", hosts or "")
    svc = m.group(1) if m else None
    m = re.search(r"WmiPrvSE pids ([\d,]+|none)", hosts or "")
    prv = None if not m else (set() if m.group(1) == "none" else set(m.group(1).split(",")))
    return svc, prv


def _wmi_hypothesis(at_subscribe: str, now: str) -> str:
    """Which of the causes _wmi_hosts tells apart fits a dropped subscription.

    H1: the WMI service itself restarted (its winmgmt pid changed); H2: a
    WmiPrvSE provider host that was there at subscribe is gone; H3: neither
    changed. 'unknown' when either reading could not be taken. The diag line
    carries it, so the log names the case without a person comparing pids.
    """
    svc0, prv0 = _wmi_pids(at_subscribe)
    svc1, prv1 = _wmi_pids(now)
    if svc0 is None or svc1 is None or prv0 is None or prv1 is None:
        return "unknown (WMI hosts unreadable)"
    if svc0 != svc1:
        return f"H1 WMI service restarted (winmgmt pid {svc0} -> {svc1})"
    if gone := sorted(prv0 - prv1, key=int):
        return f"H2 WMI provider host gone (WmiPrvSE pid {','.join(gone)})"
    return "H3 WMI service and provider hosts unchanged"


# How far back the System log is read when the subscription drops. The two drops
# of 10-06 (16:16:59, 18:08:22) came 18-19 s after subscribing; five minutes
# covers whatever stopped or crashed winmgmt before that.
SCM_LOOKBACK_MS = 300_000


# Service Control Manager events that say what happened to a service:
# 7031/7034 it terminated unexpectedly, 7036 it entered running/stopped,
# 7040 its start type was changed, 7009/7011 a start or a control timed out.
SCM_EVENT_IDS = {"7009", "7011", "7031", "7034", "7036", "7040"}


def _scm_winmgmt(xml: str, limit: int = 8) -> str:
    """The winmgmt lines out of `wevtutil qe System /f:xml` output, oldest first.

    An SCM event names the service in its EventData (the display name, or the key
    name in 7040) and, for 7036, in <Binary> as UTF-16LE hex of 「winmgmt/N」 - so
    both are looked at, and the display name is not trusted alone on a Chinese
    Windows. Returns 「SCM winmgmt: none in 5 min」 when nothing matched.
    """
    import re  # noqa: PLC0415
    rows = []
    for ev in re.findall(r"<Event[ >].*?</Event>", xml or "", re.S):
        eid = re.search(r"<EventID[^>]*>(\d+)</EventID>", ev)
        if not eid or eid.group(1) not in SCM_EVENT_IDS:
            continue
        data = [d.strip() for d in re.findall(r"<Data[^>]*>([^<]*)</Data>", ev)]
        names = " ".join(data).lower()
        b = re.search(r"<Binary>([0-9A-Fa-f]+)</Binary>", ev)
        if b:
            try:
                names += " " + bytes.fromhex(b.group(1)).decode("utf-16-le", "replace").lower()
            except ValueError:
                pass
        if "winmgmt" not in names and "windows management instrumentation" not in names:
            continue
        t = re.search(r"SystemTime=['\"]([^'\"]+)['\"]", ev)
        rows.append(f"{eid.group(1)} {t.group(1)[11:19] if t else '?'}Z {'|'.join(d for d in data if d)}")
    if not rows:
        return "SCM winmgmt: none in 5 min"
    return "SCM winmgmt: " + "; ".join(rows[-limit:])


def _wmi_scm_events() -> str:
    """What the System log says happened to winmgmt in the last SCM_LOOKBACK_MS.

    The diag's H1 (winmgmt pid changed) says the WMI service restarted but not
    why - stopped by someone, crashed (7031/7034), or a start type change. Read
    with wevtutil, not through WMI, for the same reason as _wmi_hosts.
    """
    q = ("*[System[Provider[@Name='Service Control Manager'] and "
         f"TimeCreated[timediff(@SystemTime) <= {SCM_LOOKBACK_MS}]]]")
    try:
        raw = subprocess.run(["wevtutil", "qe", "System", f"/q:{q}", "/f:xml"],
                             capture_output=True, timeout=10).stdout
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        return f"SCM winmgmt: unreadable ({type(exc).__name__})"
    # What the match needs (EventID, 「winmgmt」, the Binary hex) is ASCII, so any
    # byte-for-byte codec reads it; only a UTF-16 pipe would hide it behind NULs.
    # The Chinese in Data may come in the console code page (936) rather than UTF-8.
    if b"\x00" in raw[:200]:
        text = raw.decode("utf-16-le", "replace")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("gbk", "replace")
    return _scm_winmgmt(text)


def _wmi_error(exc: BaseException) -> "tuple[str, str]":
    """(what the user is told, the full record for relay.log) for one listener failure.

    A COM error carries two codes: the outer one is DISP_E_EXCEPTION
    (0x80020009, 「发生意外」); the one that says what happened is the scode in
    its excepinfo - 0x800706BE 「远程过程调用失败」 in every case on record
    (docs/PITFALLS.md). Windows' own Chinese text for it is quoted; English text
    (another locale, or a Python error) stays in relay.log only.
    """
    import traceback  # noqa: PLC0415
    if type(exc).__name__ != "com_error":
        return ("不是系统返回的错误，原文见中继日志",
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)[-3:]).strip())
    args = tuple(exc.args) + (None,) * 4
    hresult, outer, info = args[0], args[1], args[2]
    info = tuple(info) + (None,) * 6 if isinstance(info, (tuple, list)) else (None,) * 6
    scode = info[5] if isinstance(info[5], int) and info[5] else hresult
    text = str(info[2] or outer or "").strip()
    code = f"0x{int(scode or 0) & 0xFFFFFFFF:08X}"
    detail = (f"hresult 0x{int(hresult or 0) & 0xFFFFFFFF:08X}, scode {code}, "
              f"source {info[1] or '-'}, text {text or '-'}")
    return _said_with_code(text, code), detail


def _said_with_code(text: str, code: str) -> str:
    """Windows' own Chinese words for an error with its code, or the code alone when the words are not plain Chinese."""
    said = text.strip().rstrip("。. ")
    plain = said and not any(c.isascii() and c.isalpha() for c in said)
    return f"{said}，{code}" if plain else f"错误码 {code}"


def _hresult_failure(hresult) -> "tuple[str, str]":
    """(what the user is told, the full record) for an asynchronous call that ended with `hresult`.

    The asynchronous subscription reports its end through SWbemSink.OnCompleted
    (iHResult: "If the asynchronous call fails, this parameter contains an error
    code", https://learn.microsoft.com/en-us/windows/win32/wmisdk/swbemsink-oncompleted)
    rather than as a com_error, so there is no excepinfo text: the system
    message table supplies it (FormatMessage knows 0x800706BE, 「远程过程调用失败。」,
    on this machine's Chinese Windows; WMI's own 0x8004xxxx codes are not in it
    and are said as the code alone). Same shape as _wmi_error, so the drop
    lines and their diag read as before.
    """
    raw = int(hresult or 0) & 0xFFFFFFFF
    code = f"0x{raw:08X}"
    try:
        # pywin32 takes the code as a signed 32-bit int, the way COM hands iHResult over.
        text = str(win32api.FormatMessage(raw - (1 << 32) if raw >= 1 << 31 else raw)).strip()
    except Exception:  # noqa: BLE001 - not in the system message table
        text = ""
    return _said_with_code(text, code), f"hresult {code}, scode {code}, source SWbemSink.OnCompleted, text {text or '-'}"


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


# service.py's logger: these lines were always ark.service, and machine checks and tests read them there.
log = logging.getLogger("ark.service")


# Degraded path only: how often to re-check AUTO-MAS liveness when the WMI
# process-start subscription below could not be set up. On the healthy path
# a start is announced by the kernel and this number never ticks.
AUTOMAS_CHECK_SECONDS = 120


# A listener outage this long is pushed: by then it is not a blip that the
# 5-second resubscribe will fix. The drop itself is INFO; a resubscribe before
# this is pushed too since 2026-10-10 (why it drops is not known). The directory
# watch (_DirWatch) uses the same bound.
OUTAGE_ALARM_SECONDS = 600.0


# How long the service's stop waits for the listener to cancel its WMI
# subscription and end (_ProcessWatch.stopping). Well inside SvcStop's 15 s
# backstop; a cancel is one call to the local WMI service.
CANCEL_WAIT_SECONDS = 2.0


# When this process started, for the listener's diagnostics.
_STARTED = time.monotonic()


class _ProcessWatch:
    """One listener's subscription to python.exe starts, and what it says when that subscription fails.

    Split out of `_start_process_watch` (2026-10-06) so that every decision can
    be driven without Windows: `subscribe` is the only door to WMI, and it
    returns the subscription (_AsyncSubscription: wait() -> "event" / "stop" /
    ("done", failure), and cancel()); `wake` makes a wait() in progress return
    "stop".

    The subscription is cancelled before the relay exits (stopping(), since
    2026-10-10). Until then the process exited with this listener blocked in
    SWbemEventSource.NextEvent() on a live semisynchronous subscription
    (relay.log's stop line 「…还活着的线程：…、proc-watch」), the next process
    subscribed again seconds later, and Windows' WMI service host crashed soon
    after: 11 of the 12 Winmgmt crashes since 08-24 (System log 7031; Application
    Error 1000, svchost.exe_Winmgmt, ntdll.dll, 0xc0000005, one WER bucket) came
    6-100 s after an in-place restart, ~3% of ~355 such restarts. 2026-10-06:
    18:07:28 stop with proc-watch alive -> 18:07:47 new subscription -> 18:08:04
    Winmgmt crash -> 18:08:22 the relay logs the drop with Windows' error 0x800706BE
    (「远程过程调用失败」, remote procedure call failed).
    The crash itself is inside Windows (an access violation in ntdll inside the
    WMI service host); this removes the trigger the relay controls. Whether it
    stops the crashes can only be shown on the machine: no Winmgmt 7031 across
    the next ~100 restarts, and stop lines that no longer list proc-watch.

    Levels, now that every WARNING and ERROR reaches the group (the user on
    2026-10-06, between 02:46 and 03:12 Tokyo time, on what a healthy machine
    should send there: 「你正常情况应该一条都不发的」), and a fault the relay
    recovered from by itself goes to the daily report only (why each is not a
    fault: USER-SWITCHES.txt at ark_relay/features/host/procwatch.py:_ProcessWatch._subscribed):
    * the relay's own power-off takes WMI with it - INFO, not a fault;
    * a subscription that drops (or cannot be made) while the machine stays
      up - INFO at once, with the codes and timings that tell its causes apart
      on the machine (the diag line), and decided later:
      - resubscribed by itself: ONE WARNING saying how long it was down, with
        that diag line - pushed since 2026-10-10 (why it drops is not known; it
        was daily report only before), marked recovered only when the outage was
        already pushed meanwhile;
      - still down at OUTAGE_ALARM_SECONDS: ERROR, pushed (once per outage);
      - still down when the service stops (stopping()): ERROR, pushed;
    * the resubscribe attempts in between - INFO.
    """

    def __init__(self, evt, alive: dict, log, subscribe, wake=None):
        self.evt, self.alive, self.log = evt, alive, log
        self._subscribe = subscribe
        self._wake = wake          # makes a subscription's wait() return "stop"
        # The stop: set by stopping(); no subscription is made after it.
        self._stop = threading.Event()
        # True from just before a subscribe until that subscription is cancelled
        # and let go; read and written under _lock together with _stop.
        self._busy = False
        self._lock = threading.Lock()
        # Set by the thread that runs run() once it has returned and COM is
        # uninitialised on it (_start_process_watch); stopping() waits for it.
        self.ended = threading.Event()
        self.delay = 5.0
        self.down_since = None     # monotonic start of the current outage; None while subscribed
        self.alarmed = False       # the current outage was pushed (long outage) or was the power-off
        self.sub = None            # the live subscription: {"at", "events", "last"}
        self.hosts = ""            # _wmi_hosts() just before the last subscribe
        # The drop that started the current outage, while it counts as a fault:
        # {"why", "detail", "live", "t0", "diag"}. "diag" stays "" while _failed
        # is still waiting to rule out the relay's own power-off.
        self.fault = None

    def run(self) -> None:
        """Subscribe, listen, and resubscribe when it drops - one dropped listener must not degrade us for good.

        来龙去脉见 docs/CODE-HISTORY.md「service.py:run」。
        Returns once the service is stopping (stopping()).
        """
        while self.cycle():
            pass

    def cycle(self) -> bool:
        """One subscription's life: subscribe, wait for events until it fails, report, back off.

        False when the service is stopping: then nothing is subscribed, or the
        live subscription has just been cancelled and let go."""
        # Read before the subscription counts as in progress: tasklist can take
        # up to 25 s, and a stop meanwhile has nothing to wait for.
        hosts = wmi_diag._wmi_hosts()
        with self._lock:
            if self._stop.is_set():
                return False
            self._busy = True
        source, failure = None, None
        try:
            self.hosts = hosts
            source = self._subscribe()
            self.sub = {"at": time.monotonic(), "events": 0, "last": None}
            self._subscribed()
            while True:
                got = source.wait()   # sleeps until WMI reports a process start, a drop, or the stop
                if got == "event":
                    self.sub["events"] += 1
                    self.sub["last"] = time.monotonic()
                    win32event.SetEvent(self.evt)
                    continue
                if got != "stop":
                    failure = got[1]
                break
        except Exception as exc:  # noqa: BLE001 - every failure is reported in _failed
            failure = wmi_diag._wmi_error(exc)
        finally:
            # Cancel and let go of the subscription before anything else, on a
            # drop as on the stop: WMI keeps an asynchronous call until it is
            # cancelled (SWbemSink.Cancel). It used to stay referenced through
            # the whole backoff and was only released once the next one had
            # been registered, so WMI briefly held both.
            if source is not None:
                source.cancel()
            source = None   # the release is the point
            with self._lock:
                self._busy = False
        if failure is None or self._stop.is_set():
            return False    # the stop; a drop that raced it is not reported: nothing follows it
        time.sleep(self._failed(failure))
        self.delay = min(self.delay * 2, 60.0)
        return True

    def _subscribed(self) -> None:
        # A drop held for the relay's power-off that did not go ahead is a drop like any other.
        released = self._release_if_cancelled()
        if self.down_since is not None:
            down = time.monotonic() - self.down_since
            fault = self.fault
            if fault is not None and (fault["diag"] or released):
                # Back by itself, but why it dropped is not known (10-05 22:45:46,
                # 10-06 16:16:59 and 18:08:22, each 37-51 s after a restart): pushed
                # until that is fixed - until 2026-10-10 it was daily-report-only under
                # the user's 2026-10-06 05:07 rule, which covers faults that are
                # understood and fixed themselves, not ones that keep coming back.
                # An outage already pushed meanwhile (long, or at a stop) is one fault
                # with one push: this line is its end, daily report only.
                from ark_relay.features import errwatch  # noqa: PLC0415
                self.log.warning("系统的程序启动通知%s %.0f 秒（%s），已经自己%s订上%s\n%s",
                                 "断过" if fault["live"] else "订不上的情况持续了", down, fault["why"],
                                 "重新" if fault["live"] else "", "（期间报过群）" if self.alarmed else "",
                                 fault["diag"], extra=errwatch.recovered() if self.alarmed else None)
            else:
                self.log.info("系统的程序启动通知已重新订上（断了 %.0f 秒），不再每 %d 秒查一次 AUTO-MAS",
                              down, AUTOMAS_CHECK_SECONDS)
        self.down_since, self.alarmed, self.delay, self.fault = None, False, 5.0, None
        self.alive["ok"] = True

    def stopping(self) -> None:
        """The service is stopping: push a drop that did not recover (_push_open_drop),
        then cancel the live subscription and wait for the listener to end (_cancel).

        Called from the main loop when the stop signal arrives (_AutomasKeeper.
        stopping), before the service reports itself stopped."""
        self._push_open_drop()
        self._cancel()

    def _cancel(self) -> None:
        """Have the listener cancel its live subscription and end; wait CANCEL_WAIT_SECONDS at most.

        The cancel itself runs on the listener's own thread: the sink lives in
        that thread's single-threaded apartment, so this thread may not call it.
        Here the stop is marked (no subscription is made after it) and `wake`
        makes the listener's wait return; the listener calls SWbemSink.Cancel -
        "You must call the Cancel method to make WMI discontinue the operation and
        free the associated resources. This is very important with ... operations
        that never complete, such as ExecNotificationQueryAsync"
        (https://learn.microsoft.com/en-us/windows/win32/wmisdk/swbemsink-cancel) -
        drops every reference, returns, and its thread uninitialises COM and sets
        `ended`. No OnCompleted is waited for after the cancel: none of
        Microsoft's pages says one comes. Nothing live (in the backoff, or never
        subscribed): nothing to cancel, nothing waited for, nothing said.
        A second call does nothing."""
        with self._lock:
            if self._stop.is_set():
                return
            self._stop.set()
            busy = self._busy
        if not busy:
            return
        t0 = time.monotonic()
        if self._wake is not None:
            self._wake()
        if self.ended.wait(CANCEL_WAIT_SECONDS):
            self.log.info("系统的程序启动通知已取消订阅（用了 %.1f 秒），中继停下时不留订阅",
                          time.monotonic() - t0)
        else:
            # WARNING, not ERROR (every ERROR is pushed); the stop goes on regardless.
            self.log.warning("中继停下前，系统的程序启动通知的订阅 %.0f 秒内没取消完，中继照常停下",
                             CANCEL_WAIT_SECONDS)

    def _push_open_drop(self) -> None:
        """A drop that has not come back by now did not recover, so it is pushed
        (ERROR) - unless it is the relay's own power-off, or Windows is shutting
        down and its power-off request came before the drop (_shutdown_before:
        2026-10-10 04:28:51, a shutdown by hand at 04:27:24, the drop at 04:28:45
        as Windows tore things down, pushed as a fault).

        A drop that _failed has already ruled a fault (its diag is set) is pushed
        whatever comes next; one still inside _failed's wait for the power-off
        signal is pushed unless that signal is there now. An outage already
        pushed at OUTAGE_ALARM_SECONDS is not pushed again."""
        from ark_relay.features import errwatch  # noqa: PLC0415
        self._release_if_cancelled()
        fault, since = self.fault, self.down_since
        if fault is None or since is None or self.alarmed:
            return
        if not fault["diag"] and errwatch.relay_shutdown_issued():
            self.log.info("%s，系统的程序启动通知断开后中继也停下了", shutdown_signs._down_reason())
            return
        asked = shutdown_signs._shutdown_before(since)
        if asked is not None:
            self.log.info("Windows 关机（%s 于 %s 发起，账户 %s），系统的程序启动通知在那之后断开，"
                          "随后中继停下，按正常关机处理，不算故障", asked["process"] or "读不到",
                          asked["clock"] or "读不到", asked["user"] or "读不到")
            return
        self.alarmed = True
        # Without its diag yet, only what is at hand: _diag runs tasklist (up to
        # 25 s), and SvcStop's backstop ends the process 15 s after the stop.
        self.log.error("系统的程序启动通知断了 %.0f 秒（%s），到中继停下时还没重新订上\n%s",
                       time.monotonic() - since, fault["why"],
                       fault["diag"] or f"diag: {fault['detail']}; the stop came before the diag was taken")

    def _diag(self, live, detail: str, t0: float) -> str:
        """The second line of a failure record: what tells the causes apart on the machine. Ages are at the failure (t0)."""
        if live:
            last = f"{t0 - live['last']:.1f} s before" if live["last"] is not None else "-"
            sub = f"subscription up {t0 - live['at']:.1f} s, {live['events']} events, last {last}"
        else:
            sub = "subscription not made"
        now = wmi_diag._wmi_hosts()
        return (f"diag: {detail}; {sub}; relay up {t0 - _STARTED:.0f} s; machine up {wmi_diag._uptime()}; "
                f"WMI hosts at subscribe [{self.hosts}] now [{now}]; "
                f"hypothesis: {wmi_diag._wmi_hypothesis(self.hosts, now)}")

    def _left(self, t0: float) -> "tuple[float, str]":
        """(seconds still to wait before resubscribing, the same in words): the backoff counts from the failure, not from the log line."""
        left = max(0.0, self.delay - (time.monotonic() - t0))
        return left, (f"{left:.0f} 秒后" if left >= 1 else "马上")

    def _release_if_cancelled(self) -> bool:
        """A drop put down to the relay's own power-off (fault["held"]) whose power-off is
        no longer under way - cancelled (shutdown.abort_countdown) or past
        shutdown.ISSUED_STUCK_MIN - is a drop like any other again: not counted as
        pushed, so the long outage and the stop alarm on it. True when it released one."""
        from ark_relay.features import errwatch  # noqa: PLC0415
        fault = self.fault
        if fault is None or not fault.get("held") or errwatch.relay_shutdown_issued():
            return False
        fault["held"] = False
        self.alarmed = False
        self.log.info("中继自己的关机没有进行下去，系统的程序启动通知还没重新订上，按普通断开处理")
        return True

    def _failed(self, failure: "tuple[str, str]") -> float:
        """Say one failure at the level it deserves; returns the seconds to wait before resubscribing."""
        t0 = time.monotonic()
        live, self.sub = self.sub, None
        if self._release_if_cancelled():
            # Counted afresh from here, so the outage alarm is OUTAGE_ALARM_SECONDS after the cancel.
            self.down_since = None
        first = self.down_since is None
        if first:
            self.down_since = t0
        self.alive["ok"] = False
        win32event.SetEvent(self.evt)   # wake the main loop so it sees the degradation
        why, detail = failure
        long_outage = not self.alarmed and t0 - self.down_since >= OUTAGE_ALARM_SECONDS
        if not (first or long_outage):
            self.log.info("系统的程序启动通知还没重新订上（%s），%.0f 秒后再试", why, self.delay)
            return self.delay
        if first:
            # Undecided from here: stopping() pushes it if the service stops first.
            self.fault = {"why": why, "detail": detail, "live": live, "t0": t0, "diag": ""}
        if shutdown_signs._going_down_soon():
            # The power-off this relay issued itself: WMI goes down with the
            # machine (relay.log 09-20 10:11:05, about a minute after the relay
            # announced its 60-second shutdown). A shutdown by hand or `sc stop`
            # does not get here - it is pushed (the user, 2026-10-06). The record is kept
            # (held): a power-off that does not go ahead releases it (_release_if_cancelled),
            # and from then on the drop alarms like any other.
            self.alarmed = True
            self.fault["held"] = True
            self.log.info("%s，系统的程序启动通知此时断开，按关机处理，不算故障\n%s",
                          shutdown_signs._down_reason(), self._diag(live, detail, t0))
            return self._left(t0)[0]
        diag = self._diag(live, detail, t0)
        if first:
            # Not on the relay's own power-off above (WMI goes down with the
            # machine there): only a drop that is a fault gets the System log.
            diag += "; " + wmi_diag._wmi_scm_events()
        left, when = self._left(t0)
        if long_outage:
            # Not back after OUTAGE_ALARM_SECONDS: not recovered, pushed.
            self.alarmed = True
            self.log.error("系统的程序启动通知已经 %.0f 分钟没重新订上（%s），这段时间每 %d 秒查一次 "
                           "AUTO-MAS 在不在，中继还在继续试\n%s",
                           (t0 - self.down_since) / 60, why, AUTOMAS_CHECK_SECONDS, diag)
            return left
        # The drop itself: INFO with its diag line. Back by itself -> one daily-report
        # line (_subscribed); not back in OUTAGE_ALARM_SECONDS or by the stop -> ERROR.
        self.fault["diag"] = diag
        minutes = OUTAGE_ALARM_SECONDS // 60
        if live:
            self.log.info("系统的程序启动通知断了（%s），先改为每 %d 秒查一次 AUTO-MAS 在不在，"
                          "%s重新订阅；订回来了报到群里（断开的原因还没查清），%d 分钟还没订回来也报到群里\n%s",
                          why, AUTOMAS_CHECK_SECONDS, when, minutes, diag)
        else:
            self.log.info("系统的程序启动通知订不上（%s），先改为每 %d 秒查一次 AUTO-MAS 在不在，"
                          "%s再试；订上了报到群里（订不上的原因还没查清），%d 分钟还没订上也报到群里\n%s",
                          why, AUTOMAS_CHECK_SECONDS, when, minutes, diag)
        return left


def _start_process_watch(evt, alive: dict, log) -> bool:
    """Signal `evt` whenever a python.exe process starts anywhere on the box.

    Win32_ProcessStartTrace is a kernel-trace push event - WMI delivers it the
    instant the process is created, with no WITHIN-style polling underneath
    (unlike __InstanceCreationEvent, which would just move the timer into
    WMI). It needs admin rights; the service runs as LocalSystem, which has
    them. python.exe starts are rare on this machine (AUTO-MAS's backend and
    nothing else), so the wake-ups cost nothing.

    Returns False when WMI cannot be reached at all; if the listener drops
    later it flips alive["ok"] and fires `evt` once more, so the main loop
    notices and falls back to the liveness timer instead of trusting a watcher
    that no longer exists (_ProcessWatch).
    """
    try:
        import pythoncom  # noqa: PLC0415 - optional capability probe
        import win32com.client  # noqa: PLC0415
    except ImportError:
        return False

    # Manual reset: once the stop has set it, every later wait sees it too.
    stop = win32event.CreateEvent(None, 1, 0, None)
    watch = _ProcessWatch(evt, alive, log, lambda: wmi_subscription._AsyncSubscription(stop),
                          wake=lambda: win32event.SetEvent(stop))
    alive["watch"] = watch      # the keeper's stopping() reaches it here

    def run() -> None:
        # Its own single-threaded apartment: the objects subscribe() makes are
        # created, used, cancelled and released on this thread only.
        pythoncom.CoInitialize()
        try:
            watch.run()
        finally:
            import gc  # noqa: PLC0415
            gc.collect()    # no COM object of this apartment left in a reference cycle
            pythoncom.CoUninitialize()
            watch.ended.set()

    # Verify the subscription can actually be created before promising it
    # works: do it here, synchronously, not inside the thread.
    try:
        pythoncom.CoInitialize()
        try:
            win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
        finally:
            pythoncom.CoUninitialize()
    except Exception:  # noqa: BLE001
        return False
    threading.Thread(target=run, name="proc-watch", daemon=True).start()
    return True
