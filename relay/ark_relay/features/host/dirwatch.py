"""Change notifications for AUTO-MAS's history directory: arm, rebuild, re-arm (_DirWatch).

Split out of relay/service.py (2026-10-11); behaviour unchanged.
"""
from __future__ import annotations

import logging
import time

import win32con
import win32file

from ark_relay.core import texts
from ark_relay.features.host import procwatch
from ark_relay.features.host import wmi_diag

# service.py's logger: these lines were always ark.service, and machine checks and tests read them there.
log = logging.getLogger("ark.service")


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
    decided later, like the WMI listener (USER-SWITCHES.txt at
    ark_relay/features/host/dirwatch.py:_DirWatch._rebuilt): rebuilt by itself -> one WARNING,
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
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        self.log.warning("目录变更通知断过 %s，已经自己重建，跑完的结果又能马上处理了%s\n原因：%s",
                         wmi_diag._span(time.monotonic() - since), "（期间报过群）" if told else "",
                         self.lost_why, extra=errwatch.recovered() if told else None)

    def _still_lost(self) -> None:
        """A rebuild failed: INFO until the loss reaches OUTAGE_ALARM_SECONDS, then the
        group alarm once, and a WARNING for every failed rebuild after it."""
        down = time.monotonic() - (self.lost_since or time.monotonic())
        if self.lost_told:
            self.log.warning("目录变更通知重建失败，%.0f 秒后再试（已经断了 %s）",
                             self.retry_delay, wmi_diag._span(down))
        elif down >= procwatch.OUTAGE_ALARM_SECONDS:
            self.lost_told = True
            self.log.info("目录变更通知断了 %s 还没重建（%s），报到群里", wmi_diag._span(down), self.lost_why)
            self.notifier.send(texts.WATCH_LOST, texts.watch_lost_body(), alert=True)
        else:
            self.log.info("目录变更通知重建失败（%s），%.0f 秒后再试；重建好了报到群里（断开的原因还没查清），"
                          "%d 分钟还没重建报到群里", self.lost_why, self.retry_delay,
                          procwatch.OUTAGE_ALARM_SECONDS // 60)

    def stopping(self) -> None:
        """The service is stopping with the watch still lost and not yet pushed: not recovered, a WARNING."""
        if self.lost_since is not None and not self.lost_told:
            self.lost_told = True
            self.log.warning("目录变更通知断了 %s，到中继停下时还没重建（%s）",
                             wmi_diag._span(time.monotonic() - self.lost_since), self.lost_why)

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
                          "%d 分钟还没重建报到群里", procwatch.OUTAGE_ALARM_SECONDS // 60, exc_info=True)
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
