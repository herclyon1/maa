"""The process-start listener: wakes the main loop when a python.exe starts, and says why when its WMI subscription fails (_ProcessWatch, _start_process_watch).

Split out of relay/service.py (2026-10-11); behaviour unchanged.
"""
from __future__ import annotations

import logging
import threading
import time

import win32event

from ark_relay.features.host import shutdown_signs
from ark_relay.features.host import wmi_diag
from ark_relay.features.host import wmi_subscription

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
                from ark_relay.features.alarm import errwatch  # noqa: PLC0415
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
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
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
        if shutdown_signs._going_down_soon():
            # The power-off this relay issued itself: WMI goes down with the
            # machine (relay.log 09-20 10:11:05, about a minute after the relay
            # announced its 60-second shutdown). A shutdown by hand or `sc stop`
            # does not get here - it is pushed (the user, 2026-10-06).
            self.alarmed, self.fault = True, None
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
