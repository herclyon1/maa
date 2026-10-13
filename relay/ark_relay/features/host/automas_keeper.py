"""Keeping the AUTO-MAS backend alive: hold its handle, notice it gone, revive it with backoff, alert after repeated failures (_AutomasKeeper).

Split out of relay/service.py (2026-10-11); behaviour unchanged.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

import win32api
import win32event

import boot_stages  # relay/boot_stages.py; service.py / app_main.py put relay/ on sys.path

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.host import automas_procs
from ark_relay.features.host import procwatch
from ark_relay.features.host import shutdown_signs
from ark_relay.features.host import wmi_diag

# service.py's logger: these lines were always ark.service, and machine checks and tests read them there.
log = logging.getLogger("ark.service")


# When AUTO-MAS is missing, how long to give it (or our own revival of it)
# before trying again. Doubles on each failed revival - this is failure
# backoff, not an interval; it resets the moment a backend handle is held.
# A check that revived nothing (an installer or the window's grace held it off)
# re-arms with the wait as it stands; one that found the backend up but could
# not attach to it re-arms with procwatch.AUTOMAS_CHECK_SECONDS. Until 2026-10-13
# every handle-less check doubled it: 10-10 16:14-17:21 the process list was
# unreadable while the API answered, nothing was revived, and the checks drifted
# out to every 30 minutes without a line in the log (audit s15 #1).
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


# An AUTO-MAS exit this close before a Windows shutdown's stop notice is said to be
# the shutdown's doing. Windows closes the user's applications first and tells the
# services only after that ("This notification is received when the running
# applications are shutting down, which occurs before services are shut down.",
# https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nc-winsvc-lphandler_function_ex).
# 2026-10-10 04:28 (one sample, inferred: the exit line is logged after the 15 s settle
# wait) the stop notice came about 16 s after the exit.
EXIT_BEFORE_SHUTDOWN_SECONDS = 60.0


# After such an exit the backend is not revived while the shutdown runs; if the machine
# is still up this long after the exit (the shutdown did not happen), the exit is
# handled as an unexpected one from then on.
SHUTDOWN_NO_SHOW_SECONDS = 180.0


class _AutomasKeeper:
    """Keeping the AUTO-MAS backend alive: hold the handle, detect absence, revive with backoff, alert after repeated failures.

    Split out of `_loop` (2026-09-08); not a word of behaviour changed.

    Two of the four things that can wake the loop live here: the backend dying,
    and a python.exe starting (so a freshly launched backend gets its handle
    immediately instead of at the next liveness check).
    """

    def __init__(self, log, notifier):
        self.log, self.notifier = log, notifier
        self.handle = automas_procs._automas_handle()
        if self.handle:
            log.info("已挂上 AUTO-MAS 进程句柄，它一退出立即拉起")
        self.proc_evt = win32event.CreateEvent(None, 0, 0, None)
        # True before the listener starts, not after: its thread can find the
        # subscription broken (and set False) before _start_process_watch
        # returns, and assigning the return value afterwards overwrote that
        # with True - the loop then trusted a listener that was down.
        self.wmi_alive = {"ok": True}
        if procwatch._start_process_watch(self.proc_evt, self.wmi_alive, log):
            log.info("已订阅进程启动事件（WMI 内核 trace），AUTO-MAS 一启动立即挂句柄")
        else:
            self.wmi_alive["ok"] = False
            log.warning("系统的程序启动通知用不了，AUTO-MAS 在不在改为每 %d 秒查一次",
                        procwatch.AUTOMAS_CHECK_SECONDS)
        # One-shot deadline for "AUTO-MAS should have appeared by now" - armed
        # only while no handle is held. Doubles on every failed revival so a
        # broken backend is retried with backoff, never on a beat.
        self.revive_wait = float(REVIVE_FIRST_WAIT)
        self.revive_deadline = (time.monotonic() + self.revive_wait) if not self.handle else None
        self.revive_failures = 0
        self.revive_alerted = False
        # The backend was seen up but its handle could not be taken: said once
        # (INFO), until a handle is held again (_adopted).
        self.unattached_noted = False
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
            return min(wait_s, procwatch.AUTOMAS_CHECK_SECONDS)
        return wait_s

    def _adopted(self) -> None:
        gone, self.gone = self.gone, None
        if gone is not None:
            # Back after an exit nothing explained: the exit's cause is not known,
            # so it is pushed (until 2026-10-10 it was daily-report-only). Back
            # after an installer ran (AUTO-MAS updating itself) is the update, not a
            # fault: daily report only, and so is the end of an exit already pushed
            # meanwhile (decided) - one fault, one push.
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415
            down = wmi_diag._span(time.monotonic() - gone["at"])
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
        self.unattached_noted = False

    def on_process_started(self) -> None:
        """A python.exe has started: if it is the backend, take the handle at once instead of waiting for the next liveness check."""
        if self.handle:
            return
        self.handle = automas_procs._automas_handle()
        if self.handle:
            self.log.info("AUTO-MAS 已启动，进程句柄已挂上")
            self._adopted()

    def check(self, died: bool, now: float) -> None:
        """The backend died, or the moment it should have appeared has arrived: check once, and revive if needed."""
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        if died:
            self._exited()
        gone = self.gone
        if self.handle is None and gone is not None and gone.get("shutdown") and not gone["decided"]:
            if time.monotonic() - gone["at"] < SHUTDOWN_NO_SHOW_SECONDS:
                self.revive_deadline = now + procwatch.AUTOMAS_CHECK_SECONDS
                self.next_check = now + procwatch.AUTOMAS_CHECK_SECONDS
                return
            # The machine is still up: the shutdown did not happen (cancelled without a
            # 1075, or refused). From here it is an exit nothing explained.
            gone["shutdown"] = None
            gone["how"] = (f"{wmi_diag._span(time.monotonic() - gone['at'])}前系统日志说要关机，但机器到现在没关，"
                           "也没在装更新")
            self.log.info("AUTO-MAS 后台退出 %s 后机器还没关机，按没在关机处理，重新打开它",
                          wmi_diag._span(time.monotonic() - gone["at"]))
            died = True
        if self.handle is None and errwatch.relay_shutdown_issued():
            # The relay's own power-off is under way: there is nothing to
            # revive into (the exit itself was logged by _exited). Reviving here ran taskkill and
            # `schtasks /run` against a session Windows was closing, and logged
            # both steps as faults at every power-off. A deadline that has
            # passed is pushed on, or cap_wait would wake the loop every second;
            # none at all (an exit _exited put down to this power-off) is armed, so
            # a power-off that does not go ahead (cancelled) leads to a check that
            # revives the backend and says it was gone.
            if self.revive_deadline is None or now >= self.revive_deadline:
                self.revive_deadline = now + procwatch.AUTOMAS_CHECK_SECONDS
            return
        due_check = (
            self.handle is None
            and ((self.wmi_alive["ok"] and self.revive_deadline is not None
                  and now >= self.revive_deadline)
                 or (not self.wmi_alive["ok"] and now >= self.next_check)))
        if not (died or due_check):
            return
        self.next_check = now + procwatch.AUTOMAS_CHECK_SECONDS
        running = automas_procs._automas_running()
        revived_before = self.revive_failures
        if not running:
            self._revive(now, after_exit=died)
        revived = self.revive_failures > revived_before
        # Adopt whichever backend now exists - our revival, or one that
        # was there all along. A revived backend is a new process, so
        # the old handle (already closed above) never signals again.
        self.handle = automas_procs._automas_handle()
        if self.handle:
            self.log.info("AUTO-MAS 进程句柄已挂上")
            self._adopted()
        elif revived:
            # Arm with the CURRENT wait, then double for the next
            # failure - doubling first made the very first retry gap
            # 360s instead of the documented 180s.
            self.revive_deadline = now + self.revive_wait
            self.revive_wait = min(self.revive_wait * 2, float(REVIVE_MAX_WAIT))
        elif running:
            # Up (by the process list or, when that cannot be read, by its API)
            # but not attachable: nothing failed to revive, so no backoff - the
            # liveness check keeps its own beat until the handle can be taken.
            if not self.unattached_noted:
                self.unattached_noted = True
                self.log.info("AUTO-MAS 后台在运行，但挂不上它的进程句柄（进程列表读不到或打不开进程），"
                              "改为每 %d 秒查一次它在不在", procwatch.AUTOMAS_CHECK_SECONDS)
            self.revive_deadline = now + procwatch.AUTOMAS_CHECK_SECONDS
        else:
            # Held off (an installer on screen, the window's grace, an unreadable
            # process list): no revival ran, so the wait is not doubled.
            self.revive_deadline = now + self.revive_wait

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
        code = automas_procs._exit_code(self.handle)
        win32api.CloseHandle(self.handle)
        self.handle = None
        said = f"0x{code & 0xFFFFFFFF:X}" if code is not None else "读不到"
        if shutdown_signs._going_down_soon():
            self.log.info("%s，AUTO-MAS 后台此时退出（退出码 %s），按关机处理，不算故障，不再重新打开它",
                          shutdown_signs._down_reason(), said)
            return
        xmls = shutdown_signs._shutdown_event_xml()
        asked = shutdown_signs.shutdown_requested(xmls) if xmls else None
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
        out = automas_procs._tasklist()
        installer = out is not None and any(h in out for h in automas_procs.INSTALLER_HINTS)
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
                f"退出码 {g.get('said', '')}，{g.get('how', '')}），到现在 {wmi_diag._span(time.monotonic() - g.get('at', 0))}")

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
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415
            before = time.monotonic() - self.gone["at"]
            asked = self.gone.get("shutdown")
            if asked is not None:
                self.log.warning("Windows 关机（%s，账户 %s，于 %s 发起）：AUTO-MAS 后台在关机通知前 %s 被关掉"
                                 "（%s 退出，退出码 %s）", asked["process"] or "发起程序读不到",
                                 asked["user"] or "读不到", asked["clock"] or "时刻读不到", wmi_diag._span(before),
                                 self.gone["clock"], self.gone["said"])
                return
            if errwatch.os_shutdown() and before <= EXIT_BEFORE_SHUTDOWN_SECONDS:
                # Still pushed (only the relay's own power-off may skip the group), but
                # said as what it is: 2026-10-10 04:28 this read 「意外退出…当时机器没在关机」
                # for an exit Windows' own shutdown caused.
                self.log.warning("Windows 关机（不是中继下的关机令）：AUTO-MAS 后台在关机通知前 %s 被关掉"
                                 "（%s 退出，退出码 %s），中继停下时它没再起来",
                                 wmi_diag._span(before), self.gone["clock"], self.gone["said"])
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
        installer = automas_procs._installer_running()
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
        elif automas_procs._automas_shell_running():
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
