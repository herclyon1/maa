"""Local midnight in the main loop: put back the queue-command skips of the day before (_DayRoll).

Split out of relay/service.py (2026-10-11); behaviour unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ark_relay.core.config import SERVER_TZ

# service.py's logger: these lines were always ark.service, and machine checks and tests read them there.
log = logging.getLogger("ark.service")


class _DayRoll:
    """Local midnight in the main loop: put back the queue-command skips of the day before.

    The boot restore (gameupdate.boot_check) only runs at boot, so on a machine
    left on for days a skip a phone queue command made would keep that weekday
    off the queue item. cap_wait makes the loop wake just past midnight; check
    runs the put-back on the first wake of a new day, and again on later wakes
    while one is still open (AUTO-MAS not answering at midnight).
    """

    def __init__(self, cfg, log, now: datetime | None = None):
        self.cfg, self.log = cfg, log
        self.day = (now or datetime.now(tz=SERVER_TZ)).date()
        # True: the first check also puts back earlier days' holds. A relay restart
        # (not a reboot) skips boot_check's restore - gameupdate.should_run is once
        # per machine boot - and the put-back only touches earlier days' records.
        self.pending = True

    def cap_wait(self, wait_s: float, now: datetime | None = None) -> float:
        now = now or datetime.now(tz=SERVER_TZ)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return min(wait_s, max((midnight - now).total_seconds() + 1, 1.0))

    def check(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(tz=SERVER_TZ)
        if now.date() != self.day:
            self.day, self.pending = now.date(), True
        if not self.pending or not getattr(self.cfg, "state_dir", None):
            return []
        try:
            from ark_relay.features.gameupdate import gameupdate  # noqa: PLC0415
            done, self.pending = gameupdate.restore_queue_skips_new_day(self.cfg.state_dir, now)
        except Exception:
            self.log.exception("过了零点改回队列跳过时出错，下次醒来再试")
            return []
        if done:
            self.log.info("游戏更新：过了零点，前一天按指令在队列里跳过的改回了：%s", "、".join(done))
        return done
