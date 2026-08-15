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
import os
import subprocess
from datetime import datetime, timedelta

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
        # Failures held back until we know whether a retry rescued them.
        # AUTO-MAS retries a failed script up to RunTimesLimit times; alerting
        # on the first attempt turns a self-healing hiccup into a false alarm.
        self._pending: dict[tuple[str, str], RunRecord] = {}
        # Failures that a later retry got past. Still reported, and reported as
        # an unresolved fault - the run survived, the bug did not go away.
        self._recovered: dict[tuple[str, str], RunRecord] = {}
        self._restore_pending()
        self._missed_alerted: set[str] = set()
        self._started_at = datetime.now(tz=SERVER_TZ)
        self._handled_any = False   # nothing ran this session -> nothing to shut down for

    # ---------- survive restarts ----------

    def _restore_pending(self) -> None:
        """Reload alerts that were queued but never delivered."""
        from .transport import payload_to_record  # noqa: PLC0415 - avoid cycle
        data = self.state.load_pending()
        for bucket, target in (("pending", self._pending), ("recovered", self._recovered)):
            for item in data.get(bucket, []):
                try:
                    rec = payload_to_record(item)
                except (KeyError, ValueError, TypeError):
                    continue
                target[(rec.script, rec.user)] = rec
        if self._pending or self._recovered:
            log.info("从磁盘恢复了 %d 条未送达的告警",
                     len(self._pending) + len(self._recovered))

    def _persist_pending(self) -> None:
        from .transport import record_to_payload  # noqa: PLC0415 - avoid cycle
        self.state.save_pending({
            "pending": [record_to_payload(r) for r in self._pending.values()],
            "recovered": [record_to_payload(r) for r in self._recovered.values()],
        })

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
            self._handled_any = True
        self._flush_pending()
        self._check_missed_runs()
        self._maybe_daily_report()
        self._maybe_shutdown()
        return len(records)

    # ---------- per record ----------

    def _handle(self, rec: RunRecord) -> None:
        self.state.append_ledger(rec)
        key = (rec.script, rec.user)

        if rec.ok:
            # A later success means AUTO-MAS got past it on its own. Report it
            # anyway - once for the whole event, not once per failed attempt.
            if (bad := self._pending.pop(key, None)) is not None:
                self._recovered[key] = bad
                self._persist_pending()
                log.info("↩️ %s 重试后成功，改为自愈通知", rec.script)
            log.info("✅ %s %s（%d 分钟）静默记账",
                     rec.script, rec.run_id, rec.duration_min)
            return

        # Hold it. Only alert once the script has stopped retrying entirely.
        self._pending[key] = rec
        self._persist_pending()   # queued to disk before anything else can go wrong
        log.info("⏳ %s 失败，暂不推送，等重试结果", rec.script)

    # ---------- a run that should have happened and did not ----------

    def _check_missed_runs(self, now: datetime | None = None,
                           grace_min: int = 25) -> None:
        """Alert when a scheduled queue produced nothing.

        "Did not run" is as much a fault as "ran and failed", and it is the
        one the operator is least likely to notice on their own - silence
        looks exactly like everything being fine.

        Only covers windows while the relay itself is up. A machine that never
        powered on cannot be caught from inside it; that needs the off-box
        heartbeat.
        """
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        entries = self.state.read_ledger(day)
        for q in plan.schedule(self.cfg.automas_dir):
            for hhmm in q.get("times", []):
                try:
                    hh, mm = (int(x) for x in hhmm.split(":"))
                except ValueError:
                    continue
                due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if now < due + timedelta(minutes=grace_min):
                    continue  # not late yet
                key = f"{day}/{q['name']}/{hhmm}"
                if key in self._missed_alerted:
                    continue
                # Anything recorded after the scheduled time counts as "it ran".
                ran = any(datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                          >= due - timedelta(minutes=5) for e in entries)
                if ran:
                    self._missed_alerted.add(key)   # settled, stop checking
                    continue
                # The relay may have started after the window closed (machine
                # was off then, or it was restarted) - it cannot know whether
                # the run happened, so it must not claim it did not.
                if self._started_at > due:
                    self._missed_alerted.add(key)
                    continue
                late = int((now - due).total_seconds() // 60)
                title, body = core.format_missing(
                    f"{q['name']} 没有运行", due,
                    f"已经晚了 {late} 分钟，今天没有任何该时段的运行记录。\n"
                    "可能原因：AUTO-MAS 没启动、定时没触发、模拟器或游戏起不来。")
                if not self.notifier.send(title, body):
                    self._missed_alerted.add(key)
                    log.warning("🔌 %s 该跑没跑，已告警", q["name"])

    # ---------- decide held-back failures ----------

    @staticmethod
    def _scripts_running() -> bool:
        """True while any managed script is still working.

        A failure is only worth reporting once nothing is still trying. This is
        deliberately a process check rather than a timer: a retry run can take
        20+ minutes, so any fixed grace period would either fire early or delay
        real alerts past usefulness.
        """
        if os.name != "nt":
            return False
        try:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                                 capture_output=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return True  # cannot tell -> wait rather than cry wolf
        return any(n in out for n in (b"MAA.exe", b"MaaEnd.exe"))

    def _flush_pending(self) -> None:
        if not (self._pending or self._recovered) or self._scripts_running():
            return

        for rec in list(self._recovered.values()):
            day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
            attempts = sum(1 for e in self.state.read_ledger(day)
                           if e["script"] == rec.script and e["user"] == rec.user)
            _, body = core.format_failure(rec)
            # Self-healed is not the same as fine: the fault happened and will
            # happen again. Report it as an unresolved problem that this run
            # got past, never as "nothing to do".
            body = (f"第 1 次失败，第 {attempts} 次才成功。"
                    f"这次自己缓过来了，但问题依然存在。\n") + body
            if self.notifier.send(f"⚠️ {rec.script} 出错（本次自愈，问题未解决）", body):
                return  # keep it on disk; retry next tick
            self._recovered.pop((rec.script, rec.user), None)
            self._persist_pending()   # only now is it safe to forget
            log.info("⚠️ %s 自愈通知已推送", rec.script)

        for rec in list(self._pending.values()):
            day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
            attempts = sum(1 for e in self.state.read_ledger(day)
                           if e["script"] == rec.script and e["user"] == rec.user)
            tail = self.log_tails.pop(rec.run_id, "") or collector.log_tail(rec)
            diagnosis = summary.diagnose(self.cfg, rec.script, rec.failed_tasks, tail)
            title, body = core.format_failure(rec, diagnosis)
            body = (f"重试 {attempts} 次全部失败，需要处理。\n" if attempts > 1
                    else "需要处理。\n") + body
            errors = self.notifier.send(title, body)
            if errors:
                log.error("告警推送出错，保留待重发: %s", "；".join(errors))
                return  # still on disk, retry next tick
            self._pending.pop((rec.script, rec.user), None)
            self._persist_pending()   # only now is it safe to forget
            log.info("❌ %s 最终失败，告警已推送（尝试 %d 次）", rec.script, attempts)

    # ---------- daily wrap-up ----------

    def _report_cutoff(self, now: datetime) -> datetime:
        """The time of day after which the report is due.

        Taken from AUTO-MAS's own last scheduled queue time whenever that can
        be read, so moving a queue inside AUTO-MAS moves the report with it.
        ARK_LAST_RUN_AFTER is only the fallback.

        Both this method's callers used to compute the cutoff themselves, from
        two different starting points - one of them from the *finish time of
        the last run* rather than from the clock. That made the report
        undeliverable whenever the evening queue finished earlier than the
        configured hour: the condition could never become true, so the report
        was never sent, and because shutdown waits for the report, the machine
        never powered off either.
        """
        times = sorted(t for q in plan.schedule(self.cfg.automas_dir)
                       for t in q.get("times", []))
        hhmm = times[-1] if times else self.cfg.last_run_after
        try:
            hh, mm = (int(x) for x in hhmm.split(":"))
        except ValueError:
            hh, mm = 21, 30
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0)

    def _maybe_daily_report(self, now: datetime | None = None) -> None:
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        if self.state.report_sent(day):
            return
        entries = self.state.read_ledger(day)
        if not entries:
            return
        # Due once the clock is past the day's last queue and nothing is still
        # working - never based on when a run happened to finish.
        if now < self._report_cutoff(now) or self._scripts_running():
            return

        title, body = self._compose_daily(day, entries)
        errors = self.notifier.send(title, body)
        if errors:
            # Do not mark it sent - retry on the next tick rather than lose the day.
            log.error("日报推送失败，稍后重试: %s", "；".join(errors))
            return
        self.state.mark_report_sent(day)
        log.info("📋 %s 日报已推送（%d 条记录）", day, len(entries))

    # ---------- power off, once everything has actually been delivered ----------

    def _maybe_shutdown(self, now: datetime | None = None) -> bool:
        """Power the machine off after a run, but only when nothing is pending.

        Every guard here exists so a bug cannot cost a day's run:
          - the feature is off unless explicitly enabled
          - nothing ran this session -> never
          - a script is still working -> never
          - a failure alert is still queued -> never
          - it is late enough for the daily report -> wait until it is sent
          - too soon after start -> never (no boot/shutdown loop)
        """
        if not self.cfg.shutdown_after_run or not self._handled_any:
            return False
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        if (now - self._started_at).total_seconds() < self.cfg.shutdown_min_uptime:
            return False
        if self._scripts_running() or self._pending or self._recovered:
            return False
        cutoff = self._report_cutoff(now)   # same source as the report itself
        day = now.strftime("%Y-%m-%d")
        if now >= cutoff and not self.state.report_sent(day):
            log.info("到点该关机了，但日报还没发出去，继续等")
            return False
        log.info("本轮已处理完毕，60 秒后关机")
        try:
            subprocess.run(["shutdown", "/s", "/t", "60",
                            "/c", "ark-relay: run complete"], timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            log.exception("关机命令执行失败")
            return False
        return True

    def _compose_daily(self, day: str, entries: list[dict]) -> tuple[str, str]:
        """Model writes the report from the raw records; code only decides the
        headline (green / how many failed), which must never be a guess."""
        tomorrow = plan.next_plan(self.cfg.automas_dir)
        failed = [e for e in entries if not e["ok"]]
        head = "全绿 ✅" if not failed else f"{len(failed)} 项出错 ⚠️"
        title = f"📋 {day[5:]} · {head}"
        written = summary.daily_report(self.cfg, entries, tomorrow)
        if written:
            log.info("📋 日报由模型撰写（%d 条记录）", len(entries))
            return title, written
        log.warning("模型不可用，日报回退到结构化排版")
        return core.format_daily(day, entries, "", tomorrow)

    def send_daily_now(self) -> bool:
        """Force today's report out (used by the `report` command and tests)."""
        now = datetime.now(tz=SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        entries = self.state.read_ledger(day)
        title, body = self._compose_daily(day, entries)
        errors = self.notifier.send(title, body)
        if errors:
            log.error("日报推送失败: %s", "；".join(errors))
            return False
        self.state.mark_report_sent(day)
        return True
