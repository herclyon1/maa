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


def _automas_shell_running() -> bool:
    """True if the Electron shell is up, whatever the backend is doing."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq AUTO-MAS.exe", "/NH"],
            capture_output=True, timeout=25,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True   # cannot tell -> assume it is there, i.e. do not kill
    return b"AUTO-MAS.exe" in out


def _installer_running() -> bool:
    """True while a setup or uninstaller is on screen. Never touch it."""
    try:
        out = subprocess.run(["tasklist", "/NH"], capture_output=True,
                             timeout=25).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return True   # cannot tell -> assume yes, i.e. keep hands off
    return any(h in out for h in INSTALLER_HINTS)


def _automas_running() -> bool:
    """True if AUTO-MAS's Python backend is up.

    Checks the backend rather than the Electron shell: the shell can sit there
    perfectly happily with a dead backend, which is precisely the state the
    machine was found in - the UI looked fine and nothing was scheduling runs.

    tasklist prints in the console's ANSI codepage (GBK here), so the output is
    never decoded; a UnicodeDecodeError in the watchdog would be the watchdog
    killing itself.
    """
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "commandline"],
            capture_output=True, timeout=25,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell -> assume alive rather than launch a duplicate
    return b"main.py" in out


def _automas_handle():
    """A waitable handle on the AUTO-MAS backend, or None if it is not up.

    Waiting on the process itself replaces asking every two minutes whether it
    is still there. Windows signals the handle the instant the process exits,
    so a backend that dies at 09:05 is revived at 09:05 rather than at 09:07 -
    and in between, the relay is not doing anything at all.
    """
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'",
             "get", "processid,commandline"],
            capture_output=True, timeout=25,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for raw in out.splitlines():
        if b"main.py" not in raw:
            continue
        pid = raw.split()[-1]
        try:
            return win32api.OpenProcess(win32con.SYNCHRONIZE, False, int(pid))
        except (ValueError, Exception):  # noqa: BLE001
            return None
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


def _start_process_watch(evt, alive: dict, log) -> bool:
    """Signal `evt` whenever a python.exe process starts anywhere on the box.

    Win32_ProcessStartTrace is a kernel-trace push event - WMI delivers it the
    instant the process is created, with no WITHIN-style polling underneath
    (unlike __InstanceCreationEvent, which would just move the timer into
    WMI). It needs admin rights; the service runs as LocalSystem, which has
    them. python.exe starts are rare on this machine (AUTO-MAS's backend and
    nothing else), so the wake-ups cost nothing.

    Returns False when the subscription cannot be created at all; if the
    listener thread dies later it flips alive["ok"] and fires `evt` once more,
    so the main loop notices and falls back to the liveness timer instead of
    trusting a watcher that no longer exists.
    """
    try:
        import pythoncom  # noqa: PLC0415 - optional capability probe
        import win32com.client  # noqa: PLC0415
    except ImportError:
        return False

    def run() -> None:
        """Subscribe, listen, and resubscribe when it drops - one dropped listener must not degrade us for good.

        来龙去脉见 docs/CODE-HISTORY.md「service.py:run」。
        """
        pythoncom.CoInitialize()
        delay = 5.0
        logged_detail = False
        try:
            while True:
                try:
                    wmi = win32com.client.GetObject(
                        "winmgmts:\\\\.\\root\\cimv2")
                    watcher = wmi.ExecNotificationQuery(
                        "SELECT * FROM Win32_ProcessStartTrace"
                        " WHERE ProcessName = 'python.exe'")
                    if not alive["ok"]:
                        alive["ok"] = True
                        log.info("进程启动事件订阅已恢复，不再走 %d 秒轮询",
                                 AUTOMAS_CHECK_SECONDS)
                    delay, logged_detail = 5.0, False
                    while True:
                        watcher.NextEvent()   # blocks until the kernel reports a process start
                        win32event.SetEvent(evt)
                except Exception:
                    # Full stack trace only the first time, one line after
                    # that: if WMI is properly broken, retrying every 60
                    # seconds would flood the log.
                    if not logged_detail:
                        log.exception(
                            "进程启动事件监听中断，改用 %d 秒活性检查，"
                            "%.0f 秒后重订阅",
                            AUTOMAS_CHECK_SECONDS, delay)
                        logged_detail = True
                    else:
                        log.warning("进程启动事件重订阅失败，%.0f 秒后再试", delay)
                    alive["ok"] = False
                    win32event.SetEvent(evt)   # wake the main loop so it sees the degradation
                    time.sleep(delay)
                    delay = min(delay * 2, 60.0)
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
    import threading  # noqa: PLC0415
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
        boot_stages._stage_announce_update(notifier, log)
        inbox, collect, deferred = boot_stages._stage_inbox_and_phone(self, cfg, engine, notifier, log)
        boot_stages._stage_preupdate(cfg, notifier, log)
        boot_stages._stage_reenable_maaend(cfg, notifier, log)
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
        self.wmi_alive = {"ok": False}
        self.wmi_alive["ok"] = _start_process_watch(self.proc_evt, self.wmi_alive, log)
        if self.wmi_alive["ok"]:
            log.info("已订阅进程启动事件（WMI 内核 trace），AUTO-MAS 一启动立即挂句柄")
        else:
            log.warning("进程启动事件订阅不可用，AUTO-MAS 缺席时退回 %d 秒活性检查",
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
        if died:
            self.log.warning("AUTO-MAS 后端退出了")
            win32api.CloseHandle(self.handle)
            self.handle = None
        due_check = (
            self.handle is None
            and ((self.wmi_alive["ok"] and self.revive_deadline is not None
                  and now >= self.revive_deadline)
                 or (not self.wmi_alive["ok"] and now >= self.next_check)))
        if not (died or due_check):
            return
        self.next_check = now + AUTOMAS_CHECK_SECONDS
        if not _automas_running():
            self._revive(now)
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

    def _revive(self, now: float) -> None:
        # Two gates before the force-kill, because reviving is not
        # free: it kills a window somebody may be looking at.
        if _installer_running():
            self.log.warning("AUTO-MAS 后端不在，但安装程序正在运行——不动它")
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
                    self.log.warning(
                        "AUTO-MAS 窗口在、后端不在，先等 %d 分钟再动"
                        "（可能正在首次配置或更新）",
                        SHELL_GRACE_SECONDS // 60)
            else:
                self.log.warning("AUTO-MAS 窗口在、后端已缺席 %d 分钟，"
                                 "正在拉起（第 %d 次）",
                                 int(waited // 60), self.revive_failures + 1)
                boot_stages._revive_automas()
                self.revive_failures += 1
        else:
            # No shell at all: nothing to kill, so revive at once.
            self.log.warning("AUTO-MAS 后端不在，正在拉起（第 %d 次）",
                             self.revive_failures + 1)
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
