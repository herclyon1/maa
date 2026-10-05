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
from datetime import datetime
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
_SETTLE_STEP = 0.5
# A listener outage this long gets one more fault line (the first drop already
# had one): by then it is not a blip that the 5-second resubscribe will fix.
OUTAGE_ALARM_SECONDS = 600.0
# OpenProcess right that lets GetExitCodeProcess read the backend's exit code
# (PROCESS_QUERY_LIMITED_INFORMATION; not every win32con build names it).
_QUERY_LIMITED = 0x1000
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


def _wmi_hosts() -> str:
    """The WMI service's process id and every WmiPrvSE.exe provider host's, right now.

    Taken when the listener subscribes and again when it drops: a changed
    winmgmt pid means the WMI service itself restarted, a WmiPrvSE pid that is
    gone means a provider host died under the subscription. Neither is read
    through WMI, which may be the very thing that just broke.
    """
    parts = []
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            h = win32service.OpenService(scm, "winmgmt", win32service.SERVICE_QUERY_STATUS)
            try:
                pid = int(win32service.QueryServiceStatusEx(h)["ProcessId"])
            finally:
                win32service.CloseServiceHandle(h)
        finally:
            win32service.CloseServiceHandle(scm)
        parts.append(f"winmgmt pid {pid}")
    except Exception:  # noqa: BLE001 - diagnostics only
        parts.append("winmgmt pid ?")
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WmiPrvSE.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, timeout=25).stdout.decode("ascii", "replace")
        pids = sorted(int(row.split('","')[1]) for row in out.splitlines()
                      if row.lower().startswith('"wmiprvse.exe"'))
        parts.append("WmiPrvSE pids " + (",".join(map(str, pids)) or "none"))
    except Exception:  # noqa: BLE001 - diagnostics only
        parts.append("WmiPrvSE pids ?")
    return "; ".join(parts)


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
    said = text.rstrip("。. ")
    plain = said and not any(c.isascii() and c.isalpha() for c in said)
    why = f"{said}，{code}" if plain else f"错误码 {code}"
    detail = (f"hresult 0x{int(hresult or 0) & 0xFFFFFFFF:08X}, scode {code}, "
              f"source {info[1] or '-'}, text {text or '-'}")
    return why, detail


def _automas_shell_running() -> bool:
    """True if the Electron shell is up, whatever the backend is doing."""
    return boot_stages.shell_running()


def _installer_running() -> bool:
    """True while a setup or uninstaller is on screen. Never touch it."""
    out = _tasklist()
    if out is None:
        return True   # cannot tell -> assume yes, i.e. keep hands off
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
    returns the event source.

    Levels, now that every WARNING and ERROR reaches the group (the user on
    2026-10-06, between 02:46 and 03:12 Tokyo time, on what a healthy machine
    should send there: 「你正常情况应该一条都不发的」):
    * the machine going down takes WMI with it - INFO, not a fault;
    * a subscription that drops (or cannot be made) while the machine stays
      up - ERROR, once per outage, with the codes and timings that tell its
      causes apart on the machine;
    * the resubscribe attempts after that - INFO, so a broken WMI does not ring
      the group every minute; one more ERROR if the outage reaches
      OUTAGE_ALARM_SECONDS.
    """

    def __init__(self, evt, alive: dict, log, subscribe):
        self.evt, self.alive, self.log = evt, alive, log
        self._subscribe = subscribe
        self.delay = 5.0
        self.down_since = None     # monotonic start of the current outage; None while subscribed
        self.alarmed = False       # the current outage already had its long-outage line
        self.sub = None            # the live subscription: {"at", "events", "last"}
        self.hosts = ""            # _wmi_hosts() just before the last subscribe

    def run(self) -> None:
        """Subscribe, listen, and resubscribe when it drops - one dropped listener must not degrade us for good.

        来龙去脉见 docs/CODE-HISTORY.md「service.py:run」。
        """
        while True:
            self.cycle()

    def cycle(self) -> None:
        """One subscription's life: subscribe, wait for events until it fails, report, back off."""
        source, failure = None, ("", "")
        try:
            self.hosts = _wmi_hosts()
            source = self._subscribe()
            self.sub = {"at": time.monotonic(), "events": 0, "last": None}
            self._subscribed()
            while True:
                source.NextEvent()   # blocks until the kernel reports a process start
                self.sub["events"] += 1
                self.sub["last"] = time.monotonic()
                win32event.SetEvent(self.evt)
        except Exception as exc:  # noqa: BLE001 - every failure is reported in _failed
            failure = _wmi_error(exc)
        # Let go of the dead subscription before anything else. It used to stay
        # referenced through the whole backoff and was only released once the
        # next one had been registered, so WMI briefly held both.
        source = None   # the release is the point
        time.sleep(self._failed(failure))
        self.delay = min(self.delay * 2, 60.0)

    def _subscribed(self) -> None:
        if self.down_since is not None:
            self.log.info("系统的程序启动通知已重新订上（断了 %.0f 秒），不再每 %d 秒查一次 AUTO-MAS",
                          time.monotonic() - self.down_since, AUTOMAS_CHECK_SECONDS)
        self.down_since, self.alarmed, self.delay = None, False, 5.0
        self.alive["ok"] = True

    def _diag(self, live, detail: str, t0: float) -> str:
        """The second line of a failure record: what tells the causes apart on the machine. Ages are at the failure (t0)."""
        if live:
            last = f"{t0 - live['last']:.1f} s before" if live["last"] is not None else "-"
            sub = f"subscription up {t0 - live['at']:.1f} s, {live['events']} events, last {last}"
        else:
            sub = "subscription not made"
        return (f"diag: {detail}; {sub}; relay up {t0 - _STARTED:.0f} s; machine up {_uptime()}; "
                f"WMI hosts at subscribe [{self.hosts}] now [{_wmi_hosts()}]")

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
        if _going_down_soon():
            # The power-off this relay issued itself: WMI goes down with the
            # machine (relay.log 09-20 10:11:05, about a minute after the relay
            # announced its 60-second shutdown). A shutdown by hand or `sc stop`
            # does not get here - it is pushed (the user, 2026-10-06).
            self.alarmed = True
            self.log.info("%s，系统的程序启动通知此时断开，按关机处理，不算故障\n%s",
                          _down_reason(), self._diag(live, detail, t0))
            return self._left(t0)[0]
        diag = self._diag(live, detail, t0)
        left, when = self._left(t0)
        if long_outage:
            self.alarmed = True
            self.log.error("系统的程序启动通知已经 %.0f 分钟没重新订上（%s），这段时间每 %d 秒查一次 "
                           "AUTO-MAS 在不在，中继还在继续试\n%s",
                           (t0 - self.down_since) / 60, why, AUTOMAS_CHECK_SECONDS, diag)
        elif live:
            self.log.error("系统的程序启动通知断了（%s），先改为每 %d 秒查一次 AUTO-MAS 在不在，"
                           "%s重新订阅\n%s", why, AUTOMAS_CHECK_SECONDS, when, diag)
        else:
            self.log.error("系统的程序启动通知订不上（%s），先改为每 %d 秒查一次 AUTO-MAS 在不在，"
                           "%s再试\n%s", why, AUTOMAS_CHECK_SECONDS, when, diag)
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

    def subscribe():
        wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
        return wmi.ExecNotificationQuery(
            "SELECT * FROM Win32_ProcessStartTrace WHERE ProcessName = 'python.exe'")

    watch = _ProcessWatch(evt, alive, log, subscribe)

    def run() -> None:
        # Its own single-threaded apartment: the objects subscribe() makes are
        # created, used and released on this thread only.
        pythoncom.CoInitialize()
        try:
            watch.run()
        finally:
            pythoncom.CoUninitialize()

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

    def SvcStop(self):  # noqa: N802 - name required by the framework
        # pywin32 routes SERVICE_CONTROL_SHUTDOWN here as well (SvcShutdown ->
        # SvcStop), so this is also where a Windows shutdown first shows up.
        from ark_relay import errwatch  # noqa: PLC0415
        errwatch.mark_stopping()
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        # The phone channel's long-lived connection has to be cut deliberately,
        # otherwise it stays blocked on a socket read and the service cannot
        # stop - on 2026-08-31 it hung in STOP_PENDING several times running.
        # One last state report while the channel is still open: config edits
        # made by scripts and a shutdown issued by hand never went through
        # push_state, so the page showed hours-old state after a power-off.
        push = getattr(self, "_push_state", None)
        if push is not None:
            try:
                push("停止前")
            except Exception:  # stopping must never hang on this
                logging.getLogger("ark.service").warning("停止前上报状态失败", exc_info=True)
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
        self.SvcStop()

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
        boot_stages._stage_selfcheck(cfg, notifier, log)
        boot_stages._stage_preupdate(cfg, notifier, log)
        boot_stages._stage_reenable_maaend(cfg, notifier, log)
        boot_stages._stage_collect_watch(cfg, notifier, log)
        boot_stages._stage_gameupdate(cfg, notifier, log)
        boot_stages._stage_annihilation(engine, notifier, log)
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
    """

    def __init__(self, cfg, notifier, log):
        self.cfg, self.notifier, self.log = cfg, notifier, log
        self.handle = None
        try:
            if cfg.history_dir:
                self.handle = win32file.FindFirstChangeNotification(
                    str(cfg.history_dir), True,   # True = include subdirectories
                    win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                    | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)
                log.info("已挂上目录变更通知，记录一落盘立即处理")
        except Exception:
            log.exception("目录变更通知挂载失败，先退回定时检查，稍后自动重试")
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
            self.log.info("目录变更通知已重建，恢复「记录一落盘立即处理」")
            self.retry_delay = 5.0
        except Exception:  # noqa: BLE001 - a failed rebuild just waits longer; do not flood the log
            self.handle = None
            self.retry_delay = min(self.retry_delay * 2, 60.0)
            self.log.warning("目录变更通知重建失败，%.0f 秒后再试",
                             self.retry_delay)
        self.retry_at = time.monotonic() + self.retry_delay

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
        been bitten by most, so say it out loud.
        """
        try:
            win32file.FindNextChangeNotification(self.handle)
        except Exception:
            self.log.exception("目录变更通知重新武装失败，改用闹钟兜底")
            self.close()
            self.retry_at = time.monotonic() + 5.0
            self.retry_delay = 5.0
            self.notifier.send(texts.WATCH_LOST, texts.watch_lost_body(), alert=True)
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
        Now the machine going down is INFO with its reason (the user, 10-06: not
        at ERROR when the relay knows the machine is going down - it is not a
        fault). Every other exit is a WARNING, so it reaches the group: one with
        an installer or uninstaller on screen says so (most likely an update, and
        the relay keeps its hands off until it is done), an exit nothing here
        explains carries the evidence its level was decided on: the exit code,
        whether the window was still there, and that no shutdown or update was
        under way.
        """
        code = _exit_code(self.handle)
        win32api.CloseHandle(self.handle)
        self.handle = None
        said = f"0x{code & 0xFFFFFFFF:X}" if code is not None else "读不到"
        if _going_down_soon():
            self.log.info("%s，AUTO-MAS 后台此时退出（退出码 %s），按关机处理，不算故障，不再重新打开它",
                          _down_reason(), said)
            return
        out = _tasklist()
        if out is not None and any(h in out for h in INSTALLER_HINTS):
            # AUTO-MAS installs an update by starting AUTO-MAS-Setup.exe and
            # exiting (preupdate_automas.py); _revive leaves it alone meanwhile.
            # Still the backend going away while the machine is up: pushed (2026-10-06).
            self.log.warning("AUTO-MAS 后台退出了（退出码 %s），当时有安装或卸载程序开着，多半是在装更新；"
                             "装完之前中继不去重新打开它", said)
            return
        if out is None:
            self.log.warning("AUTO-MAS 后台意外退出了（退出码 %s，窗口在不在读不到），当时机器没在关机", said)
        else:
            self.log.warning("AUTO-MAS 后台意外退出了（退出码 %s，窗口%s），当时机器没在关机，也没在装更新",
                             said, "还在" if b"auto-mas.exe" in out else "也没了")

    def _revive(self, now: float, after_exit: bool = False) -> None:
        # Right after _exited reported the exit, what is done about it is
        # INFO: the exit line was the fault, this is the remedy. Reached from
        # the deadline instead, AUTO-MAS did not come back - a fault of its own.
        say = self.log.info if after_exit else self.log.warning
        # Two gates before the force-kill, because reviving is not
        # free: it kills a window somebody may be looking at.
        if _installer_running():
            say("AUTO-MAS 后端不在，但安装程序正在运行——不动它")
            self.shell_only_since = None
            self.shell_grace_noted = False
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
            else:
                self.log.warning("AUTO-MAS 窗口开着、后台已经 %d 分钟没在运行，"
                                 "中继正在关掉它重新打开（第 %d 次）",
                                 int(waited // 60), self.revive_failures + 1)
                boot_stages._revive_automas()
                self.revive_failures += 1
        else:
            # No shell at all: nothing to kill, so revive at once.
            say("AUTO-MAS 没在运行，中继正在重新打开它（第 %d 次%s）", self.revive_failures + 1,
                "，上一次打开后没起来" if self.revive_failures else "")
            boot_stages._revive_automas()
            self.revive_failures += 1
        if self.revive_failures >= REVIVE_ALERT_AFTER and not self.revive_alerted:
            self.revive_alerted = True
            self.notifier.send(texts.AUTOMAS_DOWN,
                               texts.automas_down_body(self.revive_failures), alert=True)


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
