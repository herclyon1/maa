"""The relay's main loop: wait for an event or the alarm clock, run tick, keep AUTO-MAS alive (_loop).

Split out of relay/service.py (2026-10-11); behaviour unchanged.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

import win32event

from ark_relay.core.config import SERVER_TZ
from ark_relay.features.host import automas_keeper
from ark_relay.features.host import day_roll
from ark_relay.features.host import dirwatch

# service.py's logger: these lines were always ark.service, and machine checks and tests read them there.
log = logging.getLogger("ark.service")


def _loop(svc, cfg, engine, notifier, inbox, collect, deferred_inbox, log) -> None:
    """The main loop: wait for an event or an alarm, run tick, revive AUTO-MAS.

    Four things can wake it, and none of them is a timer: the service being
    stopped, a run record landing on disk, the AUTO-MAS backend exiting, and a
    python.exe starting. The timeout is not an "interval" either, it is an alarm
    clock - the engine knows the moment at which the next purely time-based
    decision changes (a missed-run alert falling due, the daily report cutoff,
    the boot checkpoint), and the loop sleeps until exactly that moment. Local
    midnight is one such moment too (_DayRoll: the queue-command skips end).
    """
    watch = dirwatch._DirWatch(cfg, notifier, log)
    keeper = automas_keeper._AutomasKeeper(log, notifier)
    dayroll = day_roll._DayRoll(cfg, log)
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
        wait_s = dayroll.cap_wait(wait_s)
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
        dayroll.check()

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
