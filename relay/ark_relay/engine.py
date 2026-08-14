"""The relay loop, shared by local mode and server mode.

Given a Source of run records, this decides what to say and when to say it:

    失败      立刻推
    成功      静默记账
    当天收尾  推一条日报

Judgment happens here in plain Python. The model is asked for wording only,
after the verdict is already fixed.
"""
from __future__ import annotations

import logging
from datetime import datetime

from . import collector, core, plan, summary
from .config import SERVER_TZ, Config, RunRecord
from .core import State
from .notify import Notifier
from .transport import Source

log = logging.getLogger("ark.engine")


class Engine:
    def __init__(self, cfg: Config, source: Source, state: State, notifier: Notifier):
        self.cfg = cfg
        self.source = source
        self.state = state
        self.notifier = notifier
        # Populated by the HTTP layer in server mode, where the log tail
        # arrives with the payload instead of being read off local disk.
        self.log_tails: dict[str, str] = {}

    # ---------- first ever start ----------

    def bootstrap(self) -> int:
        """Adopt whatever history already exists as already-handled.

        A fresh install must not replay past runs as new alerts. Those records
        describe problems that were either already dealt with or are simply
        old news; pushing them looks like a flood of failures that just
        happened. Only runs produced after the relay starts are news.
        """
        if self.state.seen_path.exists():
            return 0
        adopted = 0
        for rec in self.source.fetch(set()):
            self.state.mark_seen(rec.run_id)
            adopted += 1
        # Touch the file even when there is nothing, so the next start is not
        # treated as a first start.
        self.state.seen_path.touch(exist_ok=True)
        if adopted:
            log.info("首次启动：已把 %d 条历史记录标记为已处理，不会重复告警", adopted)
        return adopted

    # ---------- one pass ----------

    def tick(self) -> int:
        """Process whatever is new. Returns how many records were handled."""
        records = self.source.fetch(self.state.seen)
        for rec in records:
            try:
                self._handle(rec)
            except Exception:  # noqa: BLE001 - one bad record must not stop the loop
                log.exception("处理运行记录失败: %s", rec.run_id)
                continue
            self.state.mark_seen(rec.run_id)
        self._maybe_daily_report()
        return len(records)

    # ---------- per record ----------

    def _handle(self, rec: RunRecord) -> None:
        self.state.append_ledger(rec)

        if rec.ok:
            log.info("✅ %s %s（%d 分钟）静默记账",
                     rec.script, rec.run_id, rec.duration_min)
            return

        # Verdict is already decided; the model only explains it.
        tail = self.log_tails.pop(rec.run_id, "") or collector.log_tail(rec)
        diagnosis = summary.diagnose(self.cfg, rec.script, rec.failed_tasks, tail)
        title, body = core.format_failure(rec, diagnosis)
        errors = self.notifier.send(title, body)
        if errors:
            log.error("失败告警推送出错: %s", "；".join(errors))
        else:
            log.info("❌ %s 失败告警已推送", rec.script)

    # ---------- daily wrap-up ----------

    def _maybe_daily_report(self, now: datetime | None = None) -> None:
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        if self.state.report_sent(day):
            return
        entries = self.state.read_ledger(day)
        if not entries:
            return
        # Send once the day's final scheduled queue has finished, so the report
        # goes out before the machine powers off.
        last_finished = max(datetime.fromisoformat(e["finished"]) for e in entries)
        try:
            hh, mm = (int(x) for x in self.cfg.last_run_after.split(":"))
        except ValueError:
            hh, mm = 21, 30
        cutoff = last_finished.astimezone(SERVER_TZ).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        if last_finished.astimezone(SERVER_TZ) < cutoff:
            return

        prose = summary.daily_prose(self.cfg, entries)
        title, body = core.format_daily(day, entries, prose,
                                        plan.next_plan(self.cfg.automas_dir))
        errors = self.notifier.send(title, body)
        if errors:
            # Do not mark it sent - retry on the next tick rather than lose the day.
            log.error("日报推送失败，稍后重试: %s", "；".join(errors))
            return
        self.state.mark_report_sent(day)
        log.info("📋 %s 日报已推送（%d 条记录）", day, len(entries))

    def send_daily_now(self) -> bool:
        """Force today's report out (used by the `report` command and tests)."""
        now = datetime.now(tz=SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        entries = self.state.read_ledger(day)
        prose = summary.daily_prose(self.cfg, entries)
        title, body = core.format_daily(day, entries, prose,
                                        plan.next_plan(self.cfg.automas_dir))
        errors = self.notifier.send(title, body)
        if errors:
            log.error("日报推送失败: %s", "；".join(errors))
            return False
        self.state.mark_report_sent(day)
        return True
