#!/usr/bin/env python3
"""Run the relay as a Windows service, so the OS keeps it alive.

Why a service and not a scheduled task: a task starts the relay once and then
forgets it. Nothing notices when the process dies - which is exactly what
happened on 2026-08-15, when the relay and AUTO-MAS both stopped mid-evening
and the 21:30 run was lost with no alert, because the thing that alerts was
the thing that died.

A service is different in kind, not degree. The Service Control Manager holds
the process handle, so the kernel tells it the instant the process exits -
there is no poll interval to wait out. Paired with failure actions
(`sc failure ... restart/5000/...`) the relay comes back within seconds of
being killed, by anything, including us.

This file adds nothing to the relay but the ability to answer the SCM. The
engine, the polling loop and every decision it makes are unchanged; see
__main__.cmd_local for the same loop without the service plumbing.

    install:  python service.py install
    start:    python service.py start
    remove:   python service.py stop && python service.py remove

AUTO-MAS cannot be a service at all: it drives the emulator and the game
window, and services run in session 0 where there is no desktop. ToDesk solves
the same problem by splitting itself in two - `ToDesk.exe --runservice` in
session 0 supervises, and it spawns `ToDesk.exe --show` into session 1 to do
the on-screen work. We follow that shape: this service supervises, and revives
AUTO-MAS through its scheduled task, which runs in the interactive session.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)

import servicemanager  # noqa: E402
import win32api  # noqa: E402
import win32con  # noqa: E402
import win32event  # noqa: E402
import win32file  # noqa: E402
import win32service  # noqa: E402
import win32serviceutil  # noqa: E402

from ark_relay import texts  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402

# The boot sequence lives in its own module, imported by name because it
# sits next to this file rather than inside the ark_relay package - the
# sys.path line above is what makes that work, so this import has to follow
# it. The dependency is one-way: boot_stages never imports service.
import boot_stages  # noqa: E402

# The module logger, so tests can capture it as <module>.log (scripts/mac/lib/loggernames.py).
log = logging.getLogger("ark.service")

# Degraded path only: how often to re-check AUTO-MAS liveness when the WMI
# process-start subscription below could not be set up. On the healthy path
# a start is announced by the kernel and this number never ticks.
AUTOMAS_CHECK_SECONDS = 120
# When AUTO-MAS is missing, how long to give it (or our own revival of it)
# before trying again. Doubles on each failed revival - this is failure
# backoff, not an interval; it resets the moment a backend handle is held.
REVIVE_FIRST_WAIT = 180
REVIVE_MAX_WAIT = 1800
# After this many failed revivals in a row, tell the operator. Before this
# alert existed, a backend that refused to come back was discovered only by
# the runs it failed to schedule.
REVIVE_ALERT_AFTER = 3
# How long a live Electron shell with no backend behind it may sit before we are
# allowed to force-kill it. 15 minutes, because the first-run environment wizard
# (installing Python, pip and git, then cloning the backend) legitimately spends
# several minutes with no backend and looks exactly like being stuck.
# 来龙去脉见 docs/CODE-HISTORY.md「service.py:(模块级)」
SHELL_GRACE_SECONDS = 900
# Processes whose presence vetoes any revival outright.
INSTALLER_HINTS = (b"auto-mas-setup", b"unins")
# How long a failure that a shutdown would also explain - the process-start
# listener dropping, the AUTO-MAS backend exiting - waits for a sign that the
# machine is going down before it is logged as a fault. On a shutdown Windows
# closes the logged-on session before it tells services to stop, and tears WMI
# down in no fixed order with that, so either can reach us before any flag
# (errwatch.going_down) is set. The first sign ends the wait at once; no sign at
# all means it was not a shutdown, and it is logged as the fault it is.
GOING_DOWN_SETTLE_SECONDS = 15.0
# An AUTO-MAS exit this close before a Windows shutdown's stop notice is said to be
# the shutdown's doing. Windows closes the user's applications first and tells the
# services only after that ("This notification is received when the running
# applications are shutting down, which occurs before services are shut down.",
# https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nc-winsvc-lphandler_function_ex).
# 2026-10-10 04:28 (one sample, inferred: the exit line is logged after the 15 s settle
# wait) the stop notice came about 16 s after the exit.
EXIT_BEFORE_SHUTDOWN_SECONDS = 60.0
# A System-log 1074 ("shutdown requested") this recent, with no 1075 ("aborted") after it,
# means an AUTO-MAS exit is the shutdown's doing. 2026-10-10: `shutdown /s /t 60` by hand
# wrote its 1074 at 04:27:24 (machine clock), AUTO-MAS exited ~04:28:29, the stop notice
# came 04:28:45; the relay's own power-offs of 10-09 21:41:51 / 21:49:11 wrote one too
# (docs/OPERATIONS.md, the 6005 / 6006 / 1074 check).
SHUTDOWN_EVENT_WINDOW_SECONDS = 120
# After such an exit the backend is not revived while the shutdown runs; if the machine
# is still up this long after the exit (the shutdown did not happen), the exit is
# handled as an unexpected one from then on.
SHUTDOWN_NO_SHOW_SECONDS = 180.0
_EVT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"
_SETTLE_STEP = 0.5
# A listener outage this long is pushed: by then it is not a blip that the
# 5-second resubscribe will fix. The drop itself is INFO; a resubscribe before
# this is pushed too since 2026-10-10 (why it drops is not known). The directory
# watch (_DirWatch) uses the same bound.
OUTAGE_ALARM_SECONDS = 600.0
# The process-start subscription (_AsyncSubscription).
PROC_START_QUERY = "SELECT * FROM Win32_ProcessStartTrace WHERE ProcessName = 'python.exe'"
# How long the service's stop waits for the listener to cancel its WMI
# subscription and end (_ProcessWatch.stopping). Well inside SvcStop's 15 s
# backstop; a cancel is one call to the local WMI service.
CANCEL_WAIT_SECONDS = 2.0
# OpenProcess right that lets GetExitCodeProcess read the backend's exit code
# (PROCESS_QUERY_LIMITED_INFORMATION; not every win32con build names it).
_QUERY_LIMITED = 0x1000
# How long the main thread, once the loop has returned on a stop, waits for
# SvcStop's last state push before it ends the process. SvcStop pushes on the
# SCM's thread while the main thread runs on to os._exit; without this wait the
# push (a state takes ~5-20 s to read and post) was cut short. Below the 15 s
# backstop in SvcStop.
STOP_PUSH_WAIT_S = 10.0
# The first words of the line SvcStop logs. The machine check of the last state
# push (machinechecks/system.py, #11) finds a stop by it; keep them.
STOP_NOTICE = "收到停止通知"
# When this process started, for the listener's diagnostics.
_STARTED = time.monotonic()


def _going_down_soon(seconds: "float | None" = None) -> bool:
    """True when the relay ITSELF has issued the machine power-off, now or within `seconds`.

    The only case where a dropped WMI link or AUTO-MAS exiting is logged at INFO
    instead of being pushed (the user, 2026-10-06: only the planned power-off the
    relay started may stay out of the group). A shutdown by hand, `sc stop` or
    Windows' own shutdown is NOT that: errwatch.relay_shutdown_issued() is false
    for them, so the event is a WARNING/ERROR and reaches the group.
    """
    from ark_relay import errwatch  # noqa: PLC0415
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


def _automas_shell_running() -> bool:
    """True if the Electron shell is up, whatever the backend is doing."""
    return boot_stages.shell_running()


def _installer_running() -> "bool | None":
    """True while a setup or uninstaller is on screen (never touch it); None when
    the process list cannot be read.

    None used to be True, and _revive then logged 「安装程序正在运行」 for a list
    it had not read - the "cannot tell" read as a definite answer that procs.py
    records (three weeks blind). The caller still keeps its hands off on None,
    but says why."""
    out = _tasklist()
    if out is None:
        return None
    return any(h in out for h in INSTALLER_HINTS)


def _python_processes() -> "list[tuple[int, str]] | None":
    """(pid, command line) of every python.exe, or None when the query itself failed. See procs.py."""
    from ark_relay import procs  # noqa: PLC0415
    return procs.python_processes()


def _automas_running() -> bool:
    """True if AUTO-MAS's Python backend is up.

    Checks the backend rather than the Electron shell: the shell can sit there
    perfectly happily with a dead backend, which is precisely the state the
    machine was found in - the UI looked fine and nothing was scheduling runs.

    When the process list cannot be read at all, the API answers instead: an
    answering API is a live backend by definition, and a silent one is not
    assumed alive any more (that assumption is what blinded the keeper, see
    _python_processes).
    """
    procs = _python_processes()
    if procs is None:
        from ark_relay import commands  # noqa: PLC0415
        return commands.mas_up()
    return any("main.py" in cmd for _, cmd in procs)


def _automas_handle():
    """A waitable handle on the AUTO-MAS backend, or None if it is not up.

    Waiting on the process itself replaces asking every two minutes whether it
    is still there. Windows signals the handle the instant the process exits,
    so a backend that dies at 09:05 is revived at 09:05 rather than at 09:07 -
    and in between, the relay is not doing anything at all.
    """
    for pid, cmd in (_python_processes() or []):
        if "main.py" not in cmd:
            continue
        # With the query right as well, its exit code can be read when it goes
        # (_exit_code); without it only the exit itself is visible.
        for access in (lambda: win32con.SYNCHRONIZE | _QUERY_LIMITED, lambda: win32con.SYNCHRONIZE):
            try:
                return win32api.OpenProcess(access(), False, pid)
            except Exception:  # noqa: BLE001
                continue
        return None
    return None


def _exit_code(handle) -> "int | None":
    """The exited backend's exit code, None where it cannot be read."""
    try:
        import win32process  # noqa: PLC0415
        return int(win32process.GetExitCodeProcess(handle))
    except Exception:  # noqa: BLE001 - evidence only; never stops the revival
        return None


def _tasklist() -> "bytes | None":
    """`tasklist /NH`, lowercased; None when it could not be run."""
    try:
        return subprocess.run(["tasklist", "/NH"], capture_output=True,
                              timeout=25).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return None


def _shutdown_event_xml(window_s: int = SHUTDOWN_EVENT_WINDOW_SECONDS) -> "list[str] | None":
    """The System log's 1074 / 1075 events of the last `window_s` seconds, newest first, as
    event XML; None when it cannot be read (ark_relay.shutdown.shutdown_event_xml)."""
    from ark_relay import shutdown  # noqa: PLC0415
    return shutdown.shutdown_event_xml(window_s)


def shutdown_requested(xmls: "list[str]") -> "dict | None":
    """From 1074 / 1075 event XML, newest first: the shutdown request still standing, or None.

    1074 (User32): "The process <param1> has initiated the power off of computer ... on
    behalf of user <param7>"; 1075: that shutdown was aborted. The newest of the two
    decides. Returns {"clock": HH:MM:SS on the relay's clock, "process": ..., "user": ...}."""
    import xml.etree.ElementTree as ET  # noqa: PLC0415
    for x in xmls:
        try:
            ev = ET.fromstring(x)
        except ET.ParseError:
            continue
        eid = (ev.findtext(f"{_EVT_NS}System/{_EVT_NS}EventID") or "").strip()
        if eid == "1075":
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


# A power-off request logged up to this long after the drop began still counts as
# before it: the 1074 stamp and the monotonic drop time are read on different clocks.
SHUTDOWN_BEFORE_SLACK_SECONDS = 2
# How far back the 1074 is looked for: `shutdown -s -t N` is logged when given, N earlier.
SHUTDOWN_BEFORE_WINDOW_SECONDS = 3600


def _shutdown_before(since_mono: float) -> "dict | None":
    """The standing Windows power-off request (shutdown_requested) when Windows is shutting
    down (SvcShutdown ran) and the request was logged before the moment `since_mono`
    (time.monotonic()); else None. Unreadable System log -> None, so the caller pushes."""
    from ark_relay import errwatch  # noqa: PLC0415
    if not errwatch.os_shutdown():
        return None
    xmls = _shutdown_event_xml(SHUTDOWN_BEFORE_WINDOW_SECONDS)
    asked = shutdown_requested(xmls) if xmls else None
    if asked is None or asked.get("at") is None:
        return None
    began = datetime.now(tz=timezone.utc) - timedelta(seconds=time.monotonic() - since_mono)
    return asked if asked["at"] <= began + timedelta(seconds=SHUTDOWN_BEFORE_SLACK_SECONDS) else None


def _wait_for_network(log, timeout: float = 90.0) -> bool:
    """Block until DNS answers, or give up. True if the network came up.

    来龙去脉见 docs/CODE-HISTORY.md「service.py:_wait_for_network」。
    """
    import socket  # noqa: PLC0415 - only needed on this path

    deadline = time.monotonic() + timeout
    delay, waited = 2.0, False
    while True:
        try:
            socket.getaddrinfo("raw.githubusercontent.com", 443)
            if waited:
                log.info("网络已就绪（等了 %.0f 秒）", timeout - (deadline - time.monotonic()))
            return True
        except OSError as exc:
            left = deadline - time.monotonic()
            if left <= 0:
                log.warning("等了 %.0f 秒 DNS 仍不通（%s），本次跳过取件；"
                            "下次开机重试", timeout, exc)
                return False
            if not waited:
                log.info("刚开机，DNS 还没起来，最多等 %.0f 秒", timeout)
                waited = True
            time.sleep(min(delay, left))
            delay = min(delay * 2, 15.0)


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
    recovered from by itself goes to the daily report only (the user on
    2026-10-06 05:07 about such faults: 「报错后自己好了的，只进日报、不进群」):
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
        hosts = _wmi_hosts()
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
            failure = _wmi_error(exc)
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
        if self.down_since is not None:
            down = time.monotonic() - self.down_since
            fault = self.fault
            if fault is not None and fault["diag"]:
                # Back by itself, but why it dropped is not known (10-05 22:45:46,
                # 10-06 16:16:59 and 18:08:22, each 37-51 s after a restart): pushed
                # until that is fixed - until 2026-10-10 it was daily-report-only under
                # the user's 2026-10-06 05:07 rule, which covers faults that are
                # understood and fixed themselves, not ones that keep coming back.
                # An outage already pushed meanwhile (long, or at a stop) is one fault
                # with one push: this line is its end, daily report only.
                from ark_relay import errwatch  # noqa: PLC0415
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
        from ark_relay import errwatch  # noqa: PLC0415
        fault, since = self.fault, self.down_since
        if fault is None or since is None or self.alarmed:
            return
        if not fault["diag"] and errwatch.relay_shutdown_issued():
            self.log.info("%s，系统的程序启动通知断开后中继也停下了", _down_reason())
            return
        asked = _shutdown_before(since)
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
        now = _wmi_hosts()
        return (f"diag: {detail}; {sub}; relay up {t0 - _STARTED:.0f} s; machine up {_uptime()}; "
                f"WMI hosts at subscribe [{self.hosts}] now [{now}]; "
                f"hypothesis: {_wmi_hypothesis(self.hosts, now)}")

    def _left(self, t0: float) -> "tuple[float, str]":
        """(seconds still to wait before resubscribing, the same in words): the backoff counts from the failure, not from the log line."""
        left = max(0.0, self.delay - (time.monotonic() - t0))
        return left, (f"{left:.0f} 秒后" if left >= 1 else "马上")

    def _failed(self, failure: "tuple[str, str]") -> float:
        """Say one failure at the level it deserves; returns the seconds to wait before resubscribing."""
        t0 = time.monotonic()
        live, self.sub = self.sub, None
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
        if _going_down_soon():
            # The power-off this relay issued itself: WMI goes down with the
            # machine (relay.log 09-20 10:11:05, about a minute after the relay
            # announced its 60-second shutdown). A shutdown by hand or `sc stop`
            # does not get here - it is pushed (the user, 2026-10-06).
            self.alarmed, self.fault = True, None
            self.log.info("%s，系统的程序启动通知此时断开，按关机处理，不算故障\n%s",
                          _down_reason(), self._diag(live, detail, t0))
            return self._left(t0)[0]
        diag = self._diag(live, detail, t0)
        if first:
            # Not on the relay's own power-off above (WMI goes down with the
            # machine there): only a drop that is a fault gets the System log.
            diag += "; " + _wmi_scm_events()
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
        pid = _winmgmt_pid()
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
                return "done", _hresult_failure(self._box["done"])
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
    watch = _ProcessWatch(evt, alive, log, lambda: _AsyncSubscription(stop),
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


class ArkRelayService(win32serviceutil.ServiceFramework):
    _svc_name_ = "ark-relay"
    _svc_display_name_ = "Ark Relay (MAA notification relay)"
    _svc_description_ = (
        "Watches AUTO-MAS run history, silences successful runs, alerts on "
        "failures immediately, and sends one daily summary. Also revives "
        "AUTO-MAS if its backend stops."
    )

    def __init__(self, args):
        super().__init__(args)
        # The second argument, 1, means manual reset. Three threads watch this
        # event (the main loop, the phone channel, the heartbeat); with auto
        # reset whichever sees it first eats the signal and the other two wait
        # forever.
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:stop_event」
        self.stop_event = win32event.CreateEvent(None, 1, 0, None)
        # What told the service to stop, for SvcStop's log line: SvcShutdown
        # sets the Windows shutdown; anything else (sc stop, a deploy) is a stop.
        self._stop_how = "停止服务"
        # Set when a stop arrives / when SvcStop's last state push is over, so
        # that SvcDoRun does not end the process under that push (STOP_PUSH_WAIT_S).
        self._stop_asked = threading.Event()
        self._stop_pushed = threading.Event()

    def SvcStop(self):  # noqa: N802 - name required by the framework
        # pywin32 routes SERVICE_CONTROL_SHUTDOWN to SvcShutdown, which calls
        # this, so this is also where a Windows shutdown first shows up.
        from ark_relay import errwatch  # noqa: PLC0415
        errwatch.mark_stopping()
        self._stop_asked.set()
        # The line the machine check of the last state push (#11) starts from:
        # it also shows that a Windows shutdown reached SvcShutdown at all.
        logging.getLogger("ark.service").info("%s（%s）", STOP_NOTICE, self._stop_how)
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        # The phone channel's long-lived connection has to be cut deliberately,
        # otherwise it stays blocked on a socket read and the service cannot
        # stop - on 2026-08-31 it hung in STOP_PENDING several times running.
        # One last state report while the channel is still open: config edits
        # made by scripts and a shutdown issued by hand never went through
        # push_state, so the page showed hours-old state after a power-off.
        push = getattr(self, "_push_state", None)
        try:
            if push is not None:
                push("停止前")
        except Exception:  # stopping must never hang on this
            logging.getLogger("ark.service").warning("停止前上报状态失败", exc_info=True)
        finally:
            self._stop_pushed.set()
        box = getattr(self, "_mailbox", None)
        if box is not None:
            box.close()
        # Hard backstop: force the process to exit if it has not shut down
        # cleanly within 15 seconds. Hanging in STOP_PENDING is far worse than a
        # forced exit, and every piece of this process's state is written to
        # disk atomically, so a forced exit cannot corrupt anything.
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:SvcStop」
        def _force_exit() -> None:
            # Getting here means the main loop did not come out of tick()
            # within 15 seconds (it happened once at 2026-09-07 10:29, with no
            # clue at all in the log). Print the line each thread is stuck on,
            # so next time there is nothing to guess.
            import sys  # noqa: PLC0415
            import traceback  # noqa: PLC0415
            names = {t.ident: t.name for t in threading.enumerate()}
            dump = []
            for ident, frame in sys._current_frames().items():
                if ident == threading.get_ident():
                    continue
                stack = traceback.format_stack(frame)[-4:]
                dump.append(f"[{names.get(ident, ident)}]\n" + "".join(stack))
            logging.getLogger("ark.service").warning(
                "停止 15 秒后进程仍未退出，硬保险强制退出。各线程卡在：\n%s", "\n".join(dump))
            logging.shutdown()
            os._exit(0)
        killer = threading.Timer(15, _force_exit)
        killer.daemon = True     # it must not itself hold up the exit
        killer.start()

    def SvcShutdown(self):  # noqa: N802 - name required by the framework
        """Windows is shutting down: stop exactly as for `sc stop`.

        pywin32's ServiceFramework advertises SERVICE_ACCEPT_SHUTDOWN only when
        the class defines this method (GetAcceptedControls: `hasattr(self,
        "SvcShutdown")`, pywin32 311) and routes SERVICE_CONTROL_SHUTDOWN here,
        never to SvcStop. Before 2026-10-06 it was not defined, so the SCM never
        told this service the machine was going down: a shutdown issued by hand
        set no going-down flag (the WMI listener's ERROR at 2026-09-18 02:20),
        and neither SvcStop's last state push nor the offline heartbeat sent as
        the main loop ends happened on a power-off.
        """
        self._stop_how = "Windows 关机"
        from ark_relay import errwatch  # noqa: PLC0415
        errwatch.mark_os_shutdown()
        self.SvcStop()

    def _wait_stop_push(self) -> None:
        """When a stop ended the main loop, let SvcStop's last state push finish
        (STOP_PUSH_WAIT_S at most) before the process is ended.

        SvcStop sets the stop event and only then pushes, on the SCM's thread; the
        main thread came out of the loop at once and went straight on to
        os._exit, so the 「停止前」 state was cut off unless it took under the
        heartbeat's 3 s join. Not waited for when no stop was asked (the
        self-update restart returns from main by itself)."""
        if not self._stop_asked.is_set() or self._stop_pushed.wait(STOP_PUSH_WAIT_S):
            return
        logging.getLogger("ark.service").warning(
            "停止前那份状态 %.0f 秒还没发完，中继不再等，手机上可能还是上一份状态", STOP_PUSH_WAIT_S)

    def SvcDoRun(self):  # noqa: N802 - name required by the framework
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        try:
            self.main()
        except Exception:
            import traceback  # noqa: PLC0415
            servicemanager.LogErrorMsg(traceback.format_exc())
            raise
        # The gap between this line and 「收到停止信号」, and between it and the
        # stop time the SCM records, is the evidence for where stopping the
        # service actually goes (measured 2026-09-07: sc stop -> STOPPED took
        # about 20 seconds).
        logging.getLogger("ark.service").info(
            "主流程已返回，向 SCM 报告已停止；还活着的线程：%s",
            "、".join(t.name for t in threading.enumerate() if t is not threading.current_thread()))
        self._wait_stop_push()
        # Do the last step ourselves rather than leaving it to the interpreter's
        # shutdown. The remaining threads are all daemons, but they are stuck
        # inside C calls (SSL reads, WMI waits) and Py_Finalize waits for them;
        # the 15-second backstop Timer cannot get the GIL during finalization
        # and never fires. Measured 2026-09-07: sc stop -> STOPPED took 20-27
        # seconds.
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:stop_event」
        for t in threading.enumerate():
            if t.name == "phone-heartbeat":
                t.join(3)          # time for it to send the offline heartbeat (bye)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)
        # The errwatch push thread is a daemon: a batch it has just delivered to the
        # group must be persisted (queue emptied) before the hard exit, or the next
        # boot re-sends it (2026-10-06 06:21:36 came back at 08:45).
        from ark_relay import errwatch  # noqa: PLC0415
        errwatch.drain(2.0)
        logging.shutdown()
        os._exit(0)

    def main(self) -> None:
        """The boot sequence. One function per step, in exactly the order written here."""
        booted = boot_stages._stage_bootstrap()
        if booted is None:
            return
        log, cfg, notifier, engine = booted
        boot_stages._stage_patch_okww(cfg, notifier, log)
        # The self-update has to come before anything uses the new code, and
        # the network wait has to come before the self-update (a cold boot has
        # no DNS yet). The order of these two lines is itself the rule: do not
        # move them.
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:main」
        _wait_for_network(log)
        if boot_stages._stage_selfupdate(log):
            return
        boot_stages._stage_backfill_manual_stops(engine, log)
        boot_stages._stage_announce_update(notifier, log)
        boot_stages._stage_evidence_sources(cfg, notifier, log)
        inbox, collect, deferred = boot_stages._stage_inbox_and_phone(self, cfg, engine, notifier, log)
        # AUTO-MAS answers from here on; before the pre-update, which can take the
        # boot window up to the queue time (stagegate.py, "Where it runs").
        boot_stages._stage_stagegate(engine, log)
        boot_stages._stage_selfcheck(cfg, notifier, log)
        boot_stages._stage_preupdate(cfg, notifier, log)
        boot_stages._stage_reenable_maaend(cfg, notifier, log)
        boot_stages._stage_collect_watch(cfg, notifier, log)
        boot_stages._stage_gameupdate(cfg, notifier, log)
        boot_stages._stage_annihilation(engine, notifier, log)
        boot_stages._stage_machinecheck(cfg, notifier, log)
        _loop(self, cfg, engine, notifier, inbox, collect, deferred, log)


class _DirWatch:
    """Change notifications for AUTO-MAS's history directory: arming, rebuilding and re-arming all live here.

    Split out of `_loop` (2026-09-08). Not a word of behaviour changed; the
    three pieces - arm, rebuild, re-arm - were simply moved out of the middle of
    the main loop into somewhere with a name. They used to be interleaved with
    keeping AUTO-MAS alive in a single 241-line function, where changing any one
    piece meant reading the other two first.

    Wake on the directory changing, not on a timer. AUTO-MAS writes a run record
    the moment a script finishes, and Windows will say so; asking every thirty
    seconds instead was just the lazy way to find out.

    The loop's timeout stays, because some of what tick() does is genuinely
    time-based - the report cutoff, "a queue was due and produced nothing", the
    shutdown window - and none of those are announced by a file appearing.
    So: whichever comes first, a change or the interval.

    Losing the watch (it cannot be armed, or re-armed) is INFO at once and
    decided later, like the WMI listener (the user, 2026-10-06 05:07:
    「报错后自己好了的，只进日报、不进群」): rebuilt by itself -> one WARNING,
    pushed since 2026-10-10 (why it is lost is not known), marked recovered only
    when the loss was already pushed meanwhile; not rebuilt within
    OUTAGE_ALARM_SECONDS -> the 「⚠️ 中继暂时不能在脚本跑完时马上处理结果」 alarm
    (until 2026-10-06 sent at once), and each failed rebuild after it a
    WARNING; still lost when the service stops -> a WARNING (stopping()).
    """

    def __init__(self, cfg, notifier, log):
        self.cfg, self.notifier, self.log = cfg, notifier, log
        self.handle = None
        self.lost_since = None     # monotonic time the watch was lost; None while armed
        self.lost_why = ""
        self.lost_told = False     # this loss reached OUTAGE_ALARM_SECONDS and was pushed
        try:
            if cfg.history_dir:
                self.handle = win32file.FindFirstChangeNotification(
                    str(cfg.history_dir), True,   # True = include subdirectories
                    win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                    | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
                log.info("已挂上目录变更通知，记录一落盘立即处理")
        except Exception as exc:  # decided by maybe_rebuild
            self._lost(exc)
            log.info("目录变更通知挂载失败，先退回定时检查，稍后自动重试", exc_info=True)
            self.handle = None
        # The rebuild cadence. Failing to arm at boot (because the directory is
        # not ready yet, say) has to enter the retry path as well - not only the
        # "re-arming failed" path.
        self.retry_at = time.monotonic() + 5.0
        self.retry_delay = 5.0

    def maybe_rebuild(self) -> None:
        """Rebuild with backoff once the watch has dropped. After a successful rebuild, run records are processed the moment they land again."""
        if self.handle is not None or not self.cfg.history_dir:
            return
        if time.monotonic() < self.retry_at:
            return
        try:
            self.handle = win32file.FindFirstChangeNotification(
                str(self.cfg.history_dir), True,
                win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
            self.retry_delay = 5.0
        except Exception as exc:  # noqa: BLE001 - a failed rebuild just waits longer
            self.handle = None
            self.retry_delay = min(self.retry_delay * 2, 60.0)
            self._lost(exc)
            self._still_lost()
        else:
            self._rebuilt()
        self.retry_at = time.monotonic() + self.retry_delay

    def _lost(self, exc: BaseException) -> None:
        """Note the start of a loss (a later failure keeps the first one's time and reason)."""
        if self.lost_since is None:
            self.lost_since = time.monotonic()
            self.lost_why = f"{type(exc).__name__}: {exc}"

    def _rebuilt(self) -> None:
        """Armed again: a loss the relay got over by itself goes to the daily report only."""
        since, self.lost_since = self.lost_since, None
        told, self.lost_told = self.lost_told, False
        if since is None:
            self.log.info("目录变更通知已重建，恢复「记录一落盘立即处理」")
            return
        # Why it was lost is not known: pushed (until 2026-10-10 daily-report-only).
        # Already pushed meanwhile (told): one fault, one push - this end is daily only.
        from ark_relay import errwatch  # noqa: PLC0415
        self.log.warning("目录变更通知断过 %s，已经自己重建，跑完的结果又能马上处理了%s\n原因：%s",
                         _span(time.monotonic() - since), "（期间报过群）" if told else "",
                         self.lost_why, extra=errwatch.recovered() if told else None)

    def _still_lost(self) -> None:
        """A rebuild failed: INFO until the loss reaches OUTAGE_ALARM_SECONDS, then the
        group alarm once, and a WARNING for every failed rebuild after it."""
        down = time.monotonic() - (self.lost_since or time.monotonic())
        if self.lost_told:
            self.log.warning("目录变更通知重建失败，%.0f 秒后再试（已经断了 %s）",
                             self.retry_delay, _span(down))
        elif down >= OUTAGE_ALARM_SECONDS:
            self.lost_told = True
            self.log.info("目录变更通知断了 %s 还没重建（%s），报到群里", _span(down), self.lost_why)
            self.notifier.send(texts.WATCH_LOST, texts.watch_lost_body(), alert=True)
        else:
            self.log.info("目录变更通知重建失败（%s），%.0f 秒后再试；重建好了报到群里（断开的原因还没查清），"
                          "%d 分钟还没重建报到群里", self.lost_why, self.retry_delay,
                          OUTAGE_ALARM_SECONDS // 60)

    def stopping(self) -> None:
        """The service is stopping with the watch still lost and not yet pushed: not recovered, a WARNING."""
        if self.lost_since is not None and not self.lost_told:
            self.lost_told = True
            self.log.warning("目录变更通知断了 %s，到中继停下时还没重建（%s）",
                             _span(time.monotonic() - self.lost_since), self.lost_why)

    def rearm(self) -> None:
        """Re-arm immediately after a notification, then give the writer a moment.

        Re-arm before handling, so a write that lands while we work is not lost.
        A record that appears during tick() would otherwise wait for the timeout
        - the exact latency this removes.

        Re-arming can fail, and it used to fail silently: the handle then never
        signals again, the loop falls back to waking only on the alarm clock,
        and run records sit unprocessed until the next clock-based deadline - up
        to the hour-long backstop. Everything still happens, just late and with
        no indication why. Degrading quietly is the failure mode this system has
        been bitten by most, so it is said out loud - once it is known whether
        the rebuild 5 seconds later fixed it (maybe_rebuild): the daily report
        when it did, the group when it is still lost after OUTAGE_ALARM_SECONDS.
        """
        try:
            win32file.FindNextChangeNotification(self.handle)
        except Exception as exc:  # decided by maybe_rebuild
            self._lost(exc)
            self.log.info("目录变更通知重新武装失败，改用闹钟兜底，5 秒后重建；重建好了报到群里（断开的原因还没查清），"
                          "%d 分钟还没重建报到群里", OUTAGE_ALARM_SECONDS // 60, exc_info=True)
            self.close()
            self.retry_at = time.monotonic() + 5.0
            self.retry_delay = 5.0
        # AUTO-MAS writes the .json and .log separately; give it a
        # moment so the first notification does not read a half-file.
        time.sleep(2)

    def close(self) -> None:
        if self.handle is None:
            return
        try:
            win32file.FindCloseChangeNotification(self.handle)
        except Exception:  # noqa: BLE001
            pass
        self.handle = None


class _AutomasKeeper:
    """Keeping the AUTO-MAS backend alive: hold the handle, detect absence, revive with backoff, alert after repeated failures.

    Split out of `_loop` (2026-09-08); not a word of behaviour changed.

    Two of the four things that can wake the loop live here: the backend dying,
    and a python.exe starting (so a freshly launched backend gets its handle
    immediately instead of at the next liveness check).
    """

    def __init__(self, log, notifier):
        self.log, self.notifier = log, notifier
        self.handle = _automas_handle()
        if self.handle:
            log.info("已挂上 AUTO-MAS 进程句柄，它一退出立即拉起")
        self.proc_evt = win32event.CreateEvent(None, 0, 0, None)
        # True before the listener starts, not after: its thread can find the
        # subscription broken (and set False) before _start_process_watch
        # returns, and assigning the return value afterwards overwrote that
        # with True - the loop then trusted a listener that was down.
        self.wmi_alive = {"ok": True}
        if _start_process_watch(self.proc_evt, self.wmi_alive, log):
            log.info("已订阅进程启动事件（WMI 内核 trace），AUTO-MAS 一启动立即挂句柄")
        else:
            self.wmi_alive["ok"] = False
            log.warning("系统的程序启动通知用不了，AUTO-MAS 在不在改为每 %d 秒查一次",
                        AUTOMAS_CHECK_SECONDS)
        # One-shot deadline for "AUTO-MAS should have appeared by now" - armed
        # only while no handle is held. Doubles on every failed revival so a
        # broken backend is retried with backoff, never on a beat.
        self.revive_wait = float(REVIVE_FIRST_WAIT)
        self.revive_deadline = (time.monotonic() + self.revive_wait) if not self.handle else None
        self.revive_failures = 0
        self.revive_alerted = False
        # When the shell was first seen alive with no backend behind it.
        self.shell_only_since = None
        self.shell_grace_noted = False
        self.next_check = 0.0
        # An exit nothing explained (_exited), until it is decided: the backend
        # back (_adopted: daily report only), still not back at the
        # REVIVE_ALERT_AFTER-th check (_revive: group) or at the stop (stopping:
        # group). {"at", "clock", "said", "how", "installer", "checks", "decided"}.
        self.gone = None

    def cap_wait(self, wait_s: float) -> float:
        """With no handle held, do not sleep past the moment it should have appeared."""
        if self.handle:
            return wait_s
        if self.wmi_alive["ok"] and self.revive_deadline is not None:
            return min(wait_s, max(1.0, self.revive_deadline - time.monotonic()))
        if not self.wmi_alive["ok"]:
            return min(wait_s, AUTOMAS_CHECK_SECONDS)
        return wait_s

    def _adopted(self) -> None:
        gone, self.gone = self.gone, None
        if gone is not None:
            # Back after an exit nothing explained: the exit's cause is not known,
            # so it is pushed (until 2026-10-10 it was daily-report-only). Back
            # after an installer ran (AUTO-MAS updating itself) is the update, not a
            # fault: daily report only, and so is the end of an exit already pushed
            # meanwhile (decided) - one fault, one push.
            from ark_relay import errwatch  # noqa: PLC0415
            down = _span(time.monotonic() - gone["at"])
            if self.revive_failures:
                self.log.warning("AUTO-MAS 后台意外退出过（%s 退出，退出码 %s），中继已重新打开（断了 %s，"
                                 "第 %d 次打开后起来的）\n%s", gone["clock"], gone["said"], down,
                                 self.revive_failures, gone["how"],
                                 extra=errwatch.recovered() if gone["decided"] else None)
            else:
                self.log.warning("AUTO-MAS 后台%s退出过（%s 退出，退出码 %s），现在又在运行了（断了 %s，"
                                 "不是中继打开的）\n%s", "" if gone["installer"] else "意外", gone["clock"],
                                 gone["said"], down, gone["how"],
                                 extra=errwatch.recovered() if gone["installer"] or gone["decided"] else None)
        self.shell_only_since = None
        self.shell_grace_noted = False
        self.revive_deadline = None
        self.revive_wait = float(REVIVE_FIRST_WAIT)
        self.revive_failures = 0
        self.revive_alerted = False

    def on_process_started(self) -> None:
        """A python.exe has started: if it is the backend, take the handle at once instead of waiting for the next liveness check."""
        if self.handle:
            return
        self.handle = _automas_handle()
        if self.handle:
            self.log.info("AUTO-MAS 已启动，进程句柄已挂上")
            self._adopted()

    def check(self, died: bool, now: float) -> None:
        """The backend died, or the moment it should have appeared has arrived: check once, and revive if needed."""
        from ark_relay import errwatch  # noqa: PLC0415
        if died:
            self._exited()
        gone = self.gone
        if self.handle is None and gone is not None and gone.get("shutdown") and not gone["decided"]:
            if time.monotonic() - gone["at"] < SHUTDOWN_NO_SHOW_SECONDS:
                self.revive_deadline = now + AUTOMAS_CHECK_SECONDS
                self.next_check = now + AUTOMAS_CHECK_SECONDS
                return
            # The machine is still up: the shutdown did not happen (cancelled without a
            # 1075, or refused). From here it is an exit nothing explained.
            gone["shutdown"] = None
            gone["how"] = (f"{_span(time.monotonic() - gone['at'])}前系统日志说要关机，但机器到现在没关，"
                           "也没在装更新")
            self.log.info("AUTO-MAS 后台退出 %s 后机器还没关机，按没在关机处理，重新打开它",
                          _span(time.monotonic() - gone["at"]))
            died = True
        if self.handle is None and errwatch.relay_shutdown_issued():
            # The relay's own power-off is under way: there is nothing to
            # revive into (the exit itself was logged by _exited). Reviving here ran taskkill and
            # `schtasks /run` against a session Windows was closing, and logged
            # both steps as faults at every power-off. A deadline that has
            # passed is pushed on, or cap_wait would wake the loop every second.
            if self.revive_deadline is not None and now >= self.revive_deadline:
                self.revive_deadline = now + AUTOMAS_CHECK_SECONDS
            return
        due_check = (
            self.handle is None
            and ((self.wmi_alive["ok"] and self.revive_deadline is not None
                  and now >= self.revive_deadline)
                 or (not self.wmi_alive["ok"] and now >= self.next_check)))
        if not (died or due_check):
            return
        self.next_check = now + AUTOMAS_CHECK_SECONDS
        if not _automas_running():
            self._revive(now, after_exit=died)
        # Adopt whichever backend now exists - our revival, or one that
        # was there all along. A revived backend is a new process, so
        # the old handle (already closed above) never signals again.
        self.handle = _automas_handle()
        if self.handle:
            self.log.info("AUTO-MAS 进程句柄已挂上")
            self._adopted()
        else:
            # Arm with the CURRENT wait, then double for the next
            # failure - doubling first made the very first retry gap
            # 360s instead of the documented 180s.
            self.revive_deadline = now + self.revive_wait
            self.revive_wait = min(self.revive_wait * 2, float(REVIVE_MAX_WAIT))

    def _exited(self) -> None:
        """The backend's handle signalled: say why it went, as far as the relay can know, and let go of the handle.

        #37 in the 2026-10-06 log sweep: 「AUTO-MAS 后端退出了」 68 times from
        08-20 to 10-05, each at WARNING, and #38 「AUTO-MAS 后端不在，正在拉起」
        62 times. Nothing here asked whether the machine was going down, yet
        the relay powers it off after every queue (`shutdown /s /t 60`, with
        errwatch.mark_stopping at once) and Windows closes the logged-on
        session - the backend with it - when the countdown ends. Such an exit
        read as a crash, and a revival was started against a closing session.
        Now the relay's own power-off is INFO with its reason (the user, 10-06:
        not at ERROR when the relay knows the machine is going down - it is not
        a fault). Every other exit is INFO too, with the evidence it was judged
        on - the exit code, whether the window was still there, an installer or
        uninstaller on screen (AUTO-MAS installing an update; the relay keeps
        its hands off until it is done), that no shutdown or update was under
        way - and is decided later (self.gone): back by itself or by the
        relay's revival -> one WARNING (_adopted), pushed since 2026-10-10 (why
        it exits is not known), daily report only after an installer or when the
        exit was already pushed; not back by the REVIVE_ALERT_AFTER-th check
        (_revive) or by the time the service stops (stopping) -> pushed.
        """
        code = _exit_code(self.handle)
        win32api.CloseHandle(self.handle)
        self.handle = None
        said = f"0x{code & 0xFFFFFFFF:X}" if code is not None else "读不到"
        if _going_down_soon():
            self.log.info("%s，AUTO-MAS 后台此时退出（退出码 %s），按关机处理，不算故障，不再重新打开它",
                          _down_reason(), said)
            return
        xmls = _shutdown_event_xml()
        asked = shutdown_requested(xmls) if xmls else None
        if asked is not None:
            # Windows closes the user's applications before it tells the services
            # (SvcShutdown): the exit comes first, the stop notice after. Not revived
            # into the closing session; the stop says who shut the machine down.
            self.gone = {"at": time.monotonic(), "clock": datetime.now(tz=SERVER_TZ).strftime("%H:%M:%S"),
                         "said": said, "how": "Windows 正在关机", "installer": False, "checks": 0,
                         "decided": False, "shutdown": asked}
            self.log.info("AUTO-MAS 后台退出（退出码 %s）：%s 于 %s 发起了 Windows 关机（账户 %s），"
                          "关机中不重新打开它", said, asked["process"] or "读不到", asked["clock"] or "读不到",
                          asked["user"] or "读不到")
            return
        if xmls is None:
            self.log.info("AUTO-MAS 后台退出：系统日志读不到，判断不了是不是 Windows 在关机，按没在关机处理")
        out = _tasklist()
        installer = out is not None and any(h in out for h in INSTALLER_HINTS)
        if installer:
            # AUTO-MAS installs an update by starting AUTO-MAS-Setup.exe and
            # exiting (preupdate_automas.py); _revive leaves it alone meanwhile.
            how = "当时有安装或卸载程序开着，装完之前中继不去重新打开它"
        elif out is None:
            how = "窗口在不在读不到，当时机器没在关机"
        else:
            how = f"窗口{'还在' if b'auto-mas.exe' in out else '也没了'}，当时机器没在关机，也没在装更新"
        self.gone = {"at": time.monotonic(), "clock": datetime.now(tz=SERVER_TZ).strftime("%H:%M:%S"),
                     "said": said, "how": how, "installer": installer, "checks": 0, "decided": False}
        self.log.info("AUTO-MAS 后台%s退出了（退出码 %s，%s）；%s，查 %d 次还没起来报到群里",
                      "" if installer else "意外", said, how,
                      "装完更新重新起来了写进日报" if installer else "重新起来了也报到群里（退出的原因还没查清）",
                      REVIVE_ALERT_AFTER)

    def _gone_line(self) -> str:
        """The pending exit in words, for a push that says it did not recover."""
        g = self.gone or {}
        return (f"AUTO-MAS 后台{'' if g.get('installer') else '意外'}退出（{g.get('clock', '')} 退出，"
                f"退出码 {g.get('said', '')}，{g.get('how', '')}），到现在 {_span(time.monotonic() - g.get('at', 0))}")

    def stopping(self) -> None:
        """The service is stopping: what is still undecided did not recover, so it is pushed.

        The WMI listener's open drop (_ProcessWatch.stopping), and an exit
        nothing explained whose backend is not back yet: one WARNING (pushed),
        whatever stops the service - the exit itself was already ruled not to be
        the relay's own power-off when it happened (_exited)."""
        watch = self.wmi_alive.get("watch")
        if watch is not None:
            watch.stopping()
        if self.gone is not None and not self.gone["decided"]:
            self.gone["decided"] = True
            from ark_relay import errwatch  # noqa: PLC0415
            before = time.monotonic() - self.gone["at"]
            asked = self.gone.get("shutdown")
            if asked is not None:
                self.log.warning("Windows 关机（%s，账户 %s，于 %s 发起）：AUTO-MAS 后台在关机通知前 %s 被关掉"
                                 "（%s 退出，退出码 %s）", asked["process"] or "发起程序读不到",
                                 asked["user"] or "读不到", asked["clock"] or "时刻读不到", _span(before),
                                 self.gone["clock"], self.gone["said"])
                return
            if errwatch.os_shutdown() and before <= EXIT_BEFORE_SHUTDOWN_SECONDS:
                # Still pushed (only the relay's own power-off may skip the group), but
                # said as what it is: 2026-10-10 04:28 this read 「意外退出…当时机器没在关机」
                # for an exit Windows' own shutdown caused.
                self.log.warning("Windows 关机（不是中继下的关机令）：AUTO-MAS 后台在关机通知前 %s 被关掉"
                                 "（%s 退出，退出码 %s），中继停下时它没再起来",
                                 _span(before), self.gone["clock"], self.gone["said"])
                return
            self.log.warning("%s，中继停下时还没重新起来", self._gone_line())

    def _revive(self, now: float, after_exit: bool = False) -> None:
        # While an exit nothing explained is undecided (self.gone), every step
        # here is INFO: whether the backend comes back decides (_adopted: daily
        # report; the REVIVE_ALERT_AFTER-th check below: group). Reached from
        # the deadline with no such exit - or after it was pushed - AUTO-MAS did
        # not come back: a fault of its own, WARNING.
        pending = self.gone is not None and not self.gone["decided"]
        say = self.log.info if (after_exit or pending) else self.log.warning
        holding = ""     # why the relay does not revive it on this check, in words
        # Two gates before the force-kill, because reviving is not
        # free: it kills a window somebody may be looking at.
        installer = _installer_running()
        if installer is None:
            # Unknown is not "no installer": killing a window mid-install is the
            # worse mistake (test_revive_gates.py), so hands off - but said as
            # what it is. Same level rule as every step here (say); a hold that
            # outlasts REVIVE_ALERT_AFTER checks reaches the group below with
            # this `holding` as the reason.
            say("AUTO-MAS 后端不在，但读不到正在运行的程序列表，"
                "判断不了有没有安装程序开着——这次不动它，下次再查")
            self.shell_only_since = None
            self.shell_grace_noted = False
            holding = "读不到正在运行的程序列表，判断不了有没有安装程序开着，中继不去动它"
        elif installer:
            say("AUTO-MAS 后端不在，但安装程序正在运行——不动它")
            self.shell_only_since = None
            self.shell_grace_noted = False
            holding = "安装或卸载程序还开着，中继不去动它"
        elif _automas_shell_running():
            # Shell up, backend down: it may be doing first-run setup or a
            # self-update, so give it a grace period first.
            if self.shell_only_since is None:
                self.shell_only_since = now
            waited = now - self.shell_only_since
            if waited < SHELL_GRACE_SECONDS:
                if not self.shell_grace_noted:
                    self.shell_grace_noted = True
                    say(
                        "AUTO-MAS 窗口在、后端不在，先等 %d 分钟再动"
                        "（AUTO-MAS 首次配置或自己更新时会这样）",
                        SHELL_GRACE_SECONDS // 60)
                holding = f"窗口开着、后台不在，中继等满 {SHELL_GRACE_SECONDS // 60} 分钟再关掉它重新打开"
            else:
                (self.log.info if pending else self.log.warning)(
                    "AUTO-MAS 窗口开着、后台已经 %d 分钟没在运行，中继正在关掉它重新打开（第 %d 次）",
                    int(waited // 60), self.revive_failures + 1)
                boot_stages._revive_automas()
                self.revive_failures += 1
        else:
            # No shell at all: nothing to kill, so revive at once.
            say("AUTO-MAS 没在运行，中继正在重新打开它（第 %d 次%s）", self.revive_failures + 1,
                "，上一次打开后没起来" if self.revive_failures else "")
            boot_stages._revive_automas()
            self.revive_failures += 1
        if pending:
            self.gone["checks"] += 1
        if self.revive_failures >= REVIVE_ALERT_AFTER and not self.revive_alerted:
            # The give-up: REVIVE_ALERT_AFTER revivals and no backend. Not
            # recovered, so the group, with the exit that started it when there was one.
            self.revive_alerted = True
            body = texts.automas_down_body(self.revive_failures)
            if self.gone is not None:
                body += "\n起因：" + self._gone_line()
                self.gone["decided"] = True
            self.notifier.send(texts.AUTOMAS_DOWN, body, alert=True)
        elif pending and self.gone["checks"] >= REVIVE_ALERT_AFTER:
            # The same number of checks while the relay holds off (an installer
            # on screen, the window's grace) or its revivals have not all run:
            # still not back, so the group.
            self.gone["decided"] = True
            self.log.warning("%s，还没回来：%s", self._gone_line(),
                             holding or f"中继已经打开了 {self.revive_failures} 次，还没起来，接着试")


def _loop(svc, cfg, engine, notifier, inbox, collect, deferred_inbox, log) -> None:
    """The main loop: wait for an event or an alarm, run tick, revive AUTO-MAS.

    Four things can wake it, and none of them is a timer: the service being
    stopped, a run record landing on disk, the AUTO-MAS backend exiting, and a
    python.exe starting. The timeout is not an "interval" either, it is an alarm
    clock - the engine knows the moment at which the next purely time-based
    decision changes (a missed-run alert falling due, the daily report cutoff,
    the boot checkpoint), and the loop sleeps until exactly that moment.
    """
    watch = _DirWatch(cfg, notifier, log)
    keeper = _AutomasKeeper(log, notifier)
    # If every alarm is far away (or there are none), still wake
    # occasionally: an alarm-clock with a bug in it must degrade into
    # lateness, not into a relay that sleeps forever.
    backstop = 3600.0
    last_alarm_note = ""
    next_inbox_retry = 0.0
    while True:
        watch.maybe_rebuild()

        handles = [svc.stop_event, keeper.proc_evt]
        proc_idx = 1
        watch_idx = automas_idx = -1
        if watch.handle:
            handles.append(watch.handle); watch_idx = len(handles) - 1
        if keeper.handle:
            handles.append(keeper.handle); automas_idx = len(handles) - 1

        wait_s = backstop
        try:
            if alarm := engine.next_deadline():
                due, why = alarm
                # +1s so the wake lands just past the moment, not just short.
                remain = (due - datetime.now(tz=SERVER_TZ)).total_seconds() + 1
                wait_s = min(max(remain, 1.0), backstop)
                note = f"{due:%H:%M} {why}"
                if note != last_alarm_note:
                    last_alarm_note = note
                    log.info("下一个闹钟 %s", note)
        except Exception:
            log.exception("计算下一个时刻出错，退回备用间隔")
        wait_s = keeper.cap_wait(wait_s)
        if not inbox.last_fetch_ok:
            wait_s = min(wait_s, 300)   # wake in time for the fetch retry

        rc = win32event.WaitForMultipleObjects(
            handles, False, int(wait_s * 1000))
        if rc == win32event.WAIT_OBJECT_0:
            log.info("收到停止信号，退出")
            keeper.stopping()     # what has not recovered by now is pushed
            watch.stopping()
            watch.close()
            return
        if rc == win32event.WAIT_OBJECT_0 + proc_idx:
            keeper.on_process_started()
        if watch.handle and rc == win32event.WAIT_OBJECT_0 + watch_idx:
            watch.rearm()

        try:
            engine.tick()
        except Exception:
            log.exception("本轮处理出错，继续")

        # A 「暂停」 command that never got downloaded is the same as no command
        # at all - so a failed fetch has to be retried, every 5 minutes. One
        # failure must not be read as "nobody issued a command today".
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_loop」
        if not inbox.last_fetch_ok and time.monotonic() >= next_inbox_retry:
            next_inbox_retry = time.monotonic() + 300
            collect("重试")

        # Scripts have just stopped: apply the config commands that were
        # deferred, now that a write will not be clobbered.
        if deferred_inbox[0] and not engine.scripts_running():
            log.info("脚本已停，补做之前推迟的待办检查")
            collect("推迟补做")

        keeper.check(bool(keeper.handle) and rc == win32event.WAIT_OBJECT_0 + automas_idx,
                     time.monotonic())


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Launched by the SCM rather than from a shell.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ArkRelayService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(ArkRelayService)
