#!/usr/bin/env python3
"""Run the relay as a Windows service, so the OS keeps it alive.

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
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)

import servicemanager  # noqa: E402
import win32event  # noqa: E402
import win32service  # noqa: E402
import win32serviceutil  # noqa: E402


# The boot sequence lives in its own module, imported by name because it
# sits next to this file rather than inside the ark_relay package - the
# sys.path line above is what makes that work, so this import has to follow
# it. The dependency is one-way: boot_stages never imports service.
import boot_stages  # noqa: E402
from ark_relay.features.automas_keeper import _loop  # noqa: E402

# The module logger, so tests can capture it as <module>.log (scripts/mac/lib/loggernames.py).
log = logging.getLogger("ark.service")

# How long the main thread, once the loop has returned on a stop, waits for
# SvcStop's last state push before it ends the process. SvcStop pushes on the
# SCM's thread while the main thread runs on to os._exit; without this wait the
# push (a state takes ~5-20 s to read and post) was cut short. Below the 15 s
# backstop in SvcStop.
STOP_PUSH_WAIT_S = 10.0
# The first words of the line SvcStop logs. The machine check of the last state
# push (machinechecks/system.py, #11) finds a stop by it; keep them.
STOP_NOTICE = "收到停止通知"


def _wait_for_network(log, timeout: float = 90.0) -> bool:
    """Block until DNS answers, or give up. True if the network came up; False when it
    did not within `timeout`, or at once when the service is stopping.

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
                log.warning("等了 %.0f 秒 DNS 仍不通（%s），照样试一次取件，取不到就下次开机再取",
                            timeout, exc)
                return False
            if not waited:
                log.info("刚开机，DNS 还没起来，最多等 %.0f 秒", timeout)
                waited = True
            until = time.monotonic() + min(delay, left)
            while (rest := until - time.monotonic()) > 0:
                if boot_stages._stop_requested():
                    log.info("服务正在停止，不再等网络")
                    return False
                time.sleep(min(1.0, rest))
            delay = min(delay * 2, 15.0)


def _force_exit() -> None:
    """SvcStop's hard exit: the main loop did not come out of tick() within 15 seconds
    (it happened once at 2026-09-07 10:29, with no clue at all in the log). Print the
    line each thread is stuck on, so next time there is nothing to guess."""
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
        self.wake_event = win32event.CreateEvent(None, 0, 0, None)
        self._shutdown_watch = None
        # What told the service to stop, for SvcStop's log line: SvcShutdown
        # sets the Windows shutdown; anything else (sc stop, a deploy) is a stop.
        self._stop_how = "停止服务"
        # Set when a stop arrives / when SvcStop's last state push is over, so
        # that SvcDoRun does not end the process under that push (STOP_PUSH_WAIT_S).
        self._stop_asked = threading.Event()
        self._stop_pushed = threading.Event()
        self._stop_once = threading.Lock()      # SvcStop runs once per process

    def SvcStop(self):  # noqa: N802 - name required by the framework
        # pywin32 routes SERVICE_CONTROL_SHUTDOWN to SvcShutdown, which calls
        # this, so this is also where a Windows shutdown first shows up.
        from ark_relay.features import errwatch  # noqa: PLC0415
        # Once per process. The installed relay (app_main.py) reaches this from two
        # threads that can both fire - WM_ENDSESSION and the stop request - and a
        # second run pushed the state again and armed a second hard exit (BOARD list A-07).
        if not self._stop_once.acquire(blocking=False):
            logging.getLogger("ark.service").info("又收到一次停止（%s），第一次的停止还在做", self._stop_how)
            return
        errwatch.mark_stopping()
        self._stop_asked.set()
        killer = threading.Timer(15, _force_exit)
        killer.daemon = True     # it must not itself hold up the exit
        killer.start()
        # The line the machine check of the last state push (#11) starts from:
        # it also shows that a Windows shutdown reached SvcShutdown at all.
        logging.getLogger("ark.service").info("%s（%s）", STOP_NOTICE, self._stop_how)
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
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

    def SvcShutdown(self):  # noqa: N802 - name required by the framework
        """Windows is shutting down: stop exactly as for `sc stop`."""
        self._stop_how = "Windows 关机"
        from ark_relay.features import errwatch  # noqa: PLC0415
        errwatch.mark_os_shutdown()
        self.SvcStop()

    def _wait_stop_push(self) -> None:
        """When a stop ended the main loop, let SvcStop's last state push finish
        (STOP_PUSH_WAIT_S at most) before the process is ended.

SvcStop sets the stop event and only then pushes, on the SCM's thread; the
        main thread came out of the loop at once and went straight on to
        os._exit, so the 「停止前」 state was cut off unless it took under the
        heartbeat's 3 s join. Not waited for when no stop was asked (the
        self-update restart returns from main by itself).
        """
        if not self._stop_asked.is_set() or self._stop_pushed.wait(STOP_PUSH_WAIT_S):
            return
        logging.getLogger("ark.service").info(
            "停止前那份状态 %.0f 秒还没发完，中继不再等，手机上可能还是上一份状态", STOP_PUSH_WAIT_S)

    # Not run by the installed relay (app_main.py hosts main and does this ending itself); called by tests/test_mc.py and tests/test_stop_push_watchdog.py.
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
        logging.getLogger("ark.service").info(
            "主流程已返回，向 SCM 报告已停止；还活着的线程：%s",
            "、".join(t.name for t in threading.enumerate() if t is not threading.current_thread()))
        self._wait_stop_push()
        for t in threading.enumerate():
            if t.name == "phone-heartbeat":
                t.join(3)          # time for it to send the offline heartbeat (bye)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)
        from ark_relay.features import errwatch  # noqa: PLC0415
        errwatch.drain(2.0)
        logging.shutdown()
        os._exit(0)

    def wake(self) -> None:
        """Wake the main loop immediately (e.g. after clearing alarm_hold)."""
        evt = getattr(self, "wake_event", None)
        if evt is not None:
            try:
                win32event.SetEvent(evt)
            except Exception:  # noqa: BLE001 - wake must never raise into phone thread
                pass

    def _stop_in_boot(self, log) -> bool:
        """A stop has arrived while the boot sequence is still running: skip the rest."""
        asked = getattr(self, "_stop_asked", None)
        if asked is None or not asked.is_set():
            return False
        log.info("开机还没走完就收到停止，后面几步不做了，直接退出")
        return True

    def main(self) -> None:
        """The boot sequence. One function per step, in exactly the order written here."""
        booted = boot_stages._stage_bootstrap()
        if booted is None:
            return
        log, cfg, notifier, engine = booted
        # The self-update has to come before anything uses the new code, and
        # the network wait has to come before the self-update (a cold boot has
        # no DNS yet). The order of these two lines is itself the rule: do not
        # move them.
        # 来龙去脉见 docs/CODE-HISTORY.md「service.py:main」
        _wait_for_network(log)
        if self._stop_in_boot(log) or boot_stages._stage_selfupdate(log):
            return
        if self._stop_in_boot(log):         # a stop that came while it fetched
            return
        boot_stages.audit_boot_alarm_hold(cfg, notifier, log)
        from ark_relay.features import procwatch  # noqa: PLC0415
        self._shutdown_watch = procwatch.start_shutdown_guard(cfg, engine, notifier, log)
        try:
            self._main_after_selfupdate(cfg, engine, notifier, log)
        finally:
            w = getattr(self, "_shutdown_watch", None)
            if w is not None:
                w.stop()

    def _main_after_selfupdate(self, cfg, engine, notifier, log) -> None:
        boot_stages._stage_flush_copies(notifier, log)
        boot_stages._stage_patch_okww(cfg, notifier, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_automas_jobfix(cfg, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_backfill_manual_stops(engine, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_announce_update(notifier, log, cfg.state_dir)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_evidence_sources(cfg, notifier, log)
        if self._stop_in_boot(log):
            return
        inbox, collect, deferred = boot_stages._stage_inbox_and_phone(self, cfg, engine, notifier, log)
        if self._stop_in_boot(log):
            return
        # AUTO-MAS answers from here on; before the pre-update, which can take the
        # boot window up to the queue time (stagegate.py, "Where it runs").
        boot_stages._stage_stagegate(engine, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_endfield_start(cfg, notifier, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_selfcheck(cfg, notifier, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_preupdate(cfg, notifier, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_reenable_maaend(cfg, notifier, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_collect_watch(cfg, notifier, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_display_wake(cfg, notifier, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_maa_start_watch(cfg, notifier, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_gameupdate(cfg, notifier, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_annihilation(engine, notifier, log)
        if self._stop_in_boot(log):
            return
        boot_stages._stage_machinecheck(cfg, notifier, log)
        _loop(self, cfg, engine, notifier, inbox, collect, deferred, log)
