"""The relay loop, shared by local mode and server mode.

Given a Source of run records, this decides what to say and when to say it:

    failure       push immediately
    success       book it silently, no push
    end of day    push one daily report (日报)

Judgment happens here in plain Python. The model is asked for wording only,
after the verdict is already fixed.
"""
from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from . import collector, core, modes, plan, summary
from .config import SERVER_TZ, Config, RunRecord
from .core import State
from .notify import Notifier
from .transport import Source

log = logging.getLogger("ark.engine")

# How long past a queue's time before "it produced nothing" becomes a fault.
MISSED_GRACE_MIN = 25
# A wake-up checkpoint is judged once, in this window past the hour: open two
# minutes late (a queue may start a moment behind), closed five minutes later.
CHECK_OPEN_MIN, CHECK_CLOSE_MIN = 2, 7
# How long after the last remote GUI action the machine is held awake.
# Long enough to keep working between two screenshots, short enough that
# forgetting about it costs one delayed shutdown, not a night of uptime.
MAINTENANCE_HOLD_SEC = 20 * 60
# How far a round's FIRST record may sit from a scheduled time and still count
# as that scheduled round. Only the first record is tested: a queue's later
# scripts legitimately land 40+ minutes in (MAA then MaaEnd), so testing every
# record against this window would call every healthy morning "manual".
MANUAL_WINDOW_MIN = 30


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
        self._shutdown_issued = False  # a countdown is already running; never twice
        self._last_wait_note = ""  # so the guard does not repeat itself every poll
        self._mode_notified: set[str] = set()  # skip-mode messages already pushed
        self._debug_last: bool | None = None  # log mode transitions, not every tick
        from .annihilation import WeeklyGate  # noqa: PLC0415 - optional feature
        self._annihilation = WeeklyGate(state.dir, cfg.automas_dir)

    # ---------- operator modes ----------

    def _observe_modes(self) -> None:
        """Advance skip-mode and make debug-mode transitions visible.

        Runs at the top of every tick: the skip flag must engage before the
        queue it targets comes due, and a mode change should announce itself
        once in the log rather than being discovered from what did not happen.
        """
        # Skip mode (跳过模式) edits AUTO-MAS's queue config, so like every
        # other config write it has to stay clear of a running script -
        # otherwise AUTO-MAS's in-memory copy wipes it, and "skip today"
        # quietly fails while the queue runs anyway.
        # Deferring costs nothing: a script is already running, so this round
        # was never going to be stopped; engage on the next tick.
        if self._scripts_running():
            return
        try:
            for msg in modes.process_skip(self.state.dir, self.cfg.automas_dir):
                log.info("⏭️ %s", msg)
                # A *persistent* failure (queue renamed while a restore marker
                # is pending) returns the identical message on every tick, and
                # ticks fire on every directory event - dedup per process, or
                # the operator gets the same push dozens of times a boot.
                if msg not in self._mode_notified:
                    self._mode_notified.add(msg)
                    self.notifier.send("⏭️ 跳过模式", msg)
        except Exception:  # noqa: BLE001 - modes must never stop the loop
            log.exception("跳过模式处理出错")
        active = modes.debug_active(self.state.dir)
        if active != self._debug_last:
            if active:
                log.info("🔧 调试模式生效（至 %s）：不关机、不报漏跑",
                         modes.debug_until(self.state.dir))
            elif self._debug_last is not None:
                log.info("🔧 调试模式已结束，恢复正常判定")
            self._debug_last = active

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
        self._observe_modes()
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
        self._enforce_annihilation()
        self._check_missed_runs()
        self._maybe_interim_report()
        self._maybe_daily_report()
        self._maybe_shutdown()
        return len(records)

    # ---------- per record ----------

    def _handle(self, rec: RunRecord) -> None:
        # mark_seen only happens after _handle returns, so a crash later in
        # this method (disk full during save_pending, annihilation copy2)
        # replays the record on every retry tick - and each replay used to
        # append the same run to the ledger again, inflating the daily report
        # and the "重试 N 次" counts. The ledger append itself must be
        # idempotent.
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        if any(e.get("run_id") == rec.run_id for e in self.state.read_ledger(day)):
            log.info("记录 %s 已在账上（上次处理中途出错的重试），跳过重记", rec.run_id)
        else:
            self.state.append_ledger(rec)
        key = (rec.script, rec.user)

        if rec.ok:
            # A later success means AUTO-MAS got past it on its own. Report it
            # anyway - once for the whole event, not once per failed attempt.
            if (bad := self._pending.pop(key, None)) is not None:
                self._recovered[key] = bad
                self._persist_pending()
                log.info("↩️ %s 重试后成功，改为自愈通知", rec.script)
            # Only a pass that actually reached the weekly cap counts. MAA
            # reports Success! even when it stops early for want of sanity, and
            # closing 剿灭 on that would skip the rest of the week with the cap
            # unmet - the run on 2026-08-17 needed five sorties and 125 sanity
            # to get from 0 to 1800.
            if (rec.raw.get("annihilation") and rec.raw.get("annihilation_done")
                    and self._annihilation):
                if msg := self._annihilation.on_success(rec.finished):
                    self.notifier.send("🗓️ 剿灭", msg)
            log.info("✅ %s %s（%d 分钟）静默记账",
                     rec.script, rec.run_id, rec.duration_min)
            return

        # Hold it. Only alert once the script has stopped retrying entirely.
        self._pending[key] = rec
        self._persist_pending()   # queued to disk before anything else can go wrong
        log.info("⏳ %s 失败，暂不推送，等重试结果", rec.script)

    # ---------- a run that should have happened and did not ----------

    def _check_missed_runs(self, now: datetime | None = None,
                           grace_min: int = MISSED_GRACE_MIN) -> None:
        """Alert when a scheduled queue produced nothing.

        "Did not run" is as much a fault as "ran and failed", and it is the
        one the operator is least likely to notice on their own - silence
        looks exactly like everything being fine.

        Only covers windows while the relay itself is up. A machine that never
        powered on cannot be caught from inside it; that is the GitHub Actions
        watchdog's job (scripts/watchdog.py, reading Tailscale lastSeen).
        """
        # Debug mode: the operator is deliberately making the machine do
        # nothing; "it produced nothing" is the plan, not a fault.
        if modes.debug_active(self.state.dir):
            return
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        entries = self._recent_entries(now)
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
                # Was this machine even awake when the queue was due? If it
                # was off, "nothing ran" is not something this relay can
                # observe from the inside, and claiming it would be a false
                # alarm every single morning - that is the GitHub Actions
                # watchdog's job instead.
                #
                # Uptime, not the relay's own start time. Those differ every
                # time the relay restarts itself for a selfupdate, and an
                # update that runs long enough to cross the queue's time used
                # to make the new process disqualify itself - swallowing a
                # genuine missed run on precisely the boot where something had
                # already gone slowly enough to be worth knowing about.
                watching_since = self._boot_time(now) or self._started_at
                if watching_since > due:
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
        self._check_partial_queues(now, day, entries)

    def _check_partial_queues(self, now: datetime, day: str,
                              entries: list[dict]) -> None:
        """Alert when a queue ran but one of its scripts never did.

        The check above only asks "did this queue produce anything", and on
        2026-08-16 that was not enough: MAA ran, so the queue counted as having
        run, while 终末地 never started at all and nobody was told. A queue that
        delivers half of what it promised is a fault, and it is invisible from
        the outside - the day looks green.

        Two things make this safe to alert on:

        Grace is generous. The morning queue runs MAA (~20 min) and only then
        MaaEnd (~25 min), so MaaEnd's record can legitimately be 45+ minutes
        late. Alerting at the same 25-minute mark as "nothing ran" would fire
        on every single healthy morning.

        Records are matched to their own queue by start time, so the morning's
        MaaEnd can never be mistaken for the evening's.
        """
        for q in plan.recent_due_queues(self.cfg.automas_dir, now,
                                        window_minutes=self.cfg.partial_window):
            due = q["due"]
            if now < due + timedelta(minutes=self.cfg.partial_grace):
                continue  # still legitimately in progress
            ran = {e["script"] for e in entries
                   if datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                   >= due - timedelta(minutes=5)}
            if not ran:
                continue  # nothing at all - already covered by the check above
            for kind in q["kinds"]:
                if kind in ran:
                    continue
                key = f"{day}/{q['name']}/{due:%H:%M}/{kind}"
                if key in self._missed_alerted:
                    continue
                # Was the machine awake when this queue was due? Same test,
                # and the same reason, as in _check_missed_runs: uptime rather
                # than the relay's start time, so a selfupdate restart cannot
                # make the relay disqualify itself from reporting a script that
                # never started.
                watching_since = self._boot_time(now) or self._started_at
                if watching_since > due:
                    self._missed_alerted.add(key)
                    continue
                late = int((now - due).total_seconds() // 60)
                title, body = core.format_missing(
                    f"{kind} 没有运行（{q['name']}）", due,
                    f"这一轮跑了 {'、'.join(sorted(ran))}，但 {kind} 一次记录都没有，"
                    f"已经晚了 {late} 分钟。\n"
                    "队列本身是跑了的，所以不是没开机——是这一项自己没起来。")
                if not self.notifier.send(title, body):
                    self._missed_alerted.add(key)
                    log.warning("🔌 %s 缺项：%s 没跑，已告警", q["name"], kind)

    # ---------- decide held-back failures ----------

    def scripts_running(self) -> bool:
        """Public view of the same check the shutdown path uses.

        The service needs it to decide when a config edit is safe: AUTO-MAS
        reads its config as it launches each script, so writing during a run
        would land somewhere between two scripts and take effect for only half
        the queue.
        """
        return self._scripts_running()

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
        # Endfield.exe is on this list because MaaEnd has NO process of its
        # own - AUTO-MAS's python drives it in-process (verified 2026-08-20:
        # during a MaaEnd run tasklist shows only the game). Watching for
        # "MaaEnd.exe" alone made this check blind through the entire 终末地
        # phase; the game binary is the only visible sign that phase is live.
        return any(n in out for n in (b"MAA.exe", b"MaaEnd.exe", b"Endfield.exe"))

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

    def next_deadline(self, now: datetime | None = None) -> tuple[datetime, str] | None:
        """The next moment any purely time-based decision can change.

        Everything event-driven already wakes the loop by itself - a record
        landing on disk, the backend dying, the service being stopped. What
        remains is clock work, and each piece of it has an exact next moment:

          - a queue that produced nothing becomes reportable at due+grace
          - the daily report becomes due at the cutoff
          - a wake-up checkpoint is asked once, shortly past its time

        So the loop can sleep until the earliest of these instead of waking
        every few minutes to ask the clock whether anything is due yet. The
        opposite of polling is not "wait longer" - it is knowing exactly which
        moment you are waiting for.
        """
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        if self._shutdown_issued:
            return None
        cands: list[tuple[datetime, str]] = []

        def today_and_tomorrow(hh: int, mm: int):
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            return due, due + timedelta(days=1)

        for q in plan.schedule(self.cfg.automas_dir):
            for hhmm in q.get("times", []):
                try:
                    hh, mm = (int(x) for x in hhmm.split(":"))
                except ValueError:
                    continue
                for due in today_and_tomorrow(hh, mm):
                    key = f"{due:%Y-%m-%d}/{q['name']}/{hhmm}"
                    moment = due + timedelta(minutes=MISSED_GRACE_MIN)
                    if moment > now and key not in self._missed_alerted:
                        cands.append((moment, f"核对队列「{q['name']}」{hhmm} 是否漏跑"))

        if not self.state.report_sent(now.strftime("%Y-%m-%d")):
            cutoff = self._report_cutoff(now)
            if cutoff > now:
                cands.append((cutoff, "日报截止"))

        for raw in self.cfg.check_times.split(","):
            raw = raw.strip()
            try:
                hh, mm = (int(x) for x in raw.split(":"))
            except ValueError:
                continue
            for due in today_and_tomorrow(hh, mm):
                moment = due + timedelta(minutes=CHECK_OPEN_MIN)
                if moment > now:
                    cands.append((moment, f"检查点 {raw}"))

        return min(cands) if cands else None

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

    def _idle_checkpoint(self, now: datetime | None = None) -> bool:
        """True when a wake-up time has passed with nothing scheduled for it.

        The machine is woken at fixed times - 09:00 and 21:30 here - and each
        wake exists to serve the queues at that time. So the morning check asks
        only about 09:00 and the evening check only about 21:30. With 明日方舟
        paused there is no 21:30 queue any more, but the wake still fires; that
        boot has no purpose and should end.

        Two earlier attempts got this wrong and are worth remembering. Keying
        off "up for 25 minutes with every queue time past" would also have
        powered off a machine booted at three in the afternoon to work on. And
        vetoing on an open SSH or ToDesk session was worse than useless: both
        start automatically at boot, so the veto always held and the feature
        never fired at all.
        """
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        if self._handled_any:
            return False
        scheduled: set[str] = {t for q in plan.schedule(self.cfg.automas_dir)
                               for t in q.get("times", [])}
        for raw in self.cfg.check_times.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                hh, mm = (int(x) for x in raw.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            # A checkpoint is a moment, not a state. The window opens two
            # minutes after the time - long enough for a queue that starts a
            # little late - and closes five minutes later. Without the closing
            # edge the condition stayed true all evening, so 21:33 and 22:00
            # were still "checking 21:30", and a machine someone had been
            # working on since the afternoon would be powered off the moment
            # the loop next ran.
            if not (due + timedelta(minutes=CHECK_OPEN_MIN)
                    <= now <= due + timedelta(minutes=CHECK_CLOSE_MIN)):
                continue
            if due < self._started_at:
                continue        # this boot was not up for that checkpoint
            if raw in scheduled:
                return False        # this wake has work; the normal path decides
            log.info("%s 这个时间点没有任何排期，本次开机无事可做", raw)
            return True
        return False

    def _recent_entries(self, now: datetime) -> list[dict]:
        """Today's ledger plus yesterday's, for queue-completion checks.

        The ledger is keyed by each run's *start* date, so an evening queue
        checked just after midnight has its records in yesterday's file; a
        today-only read makes a finished queue look like it never ran.
        """
        return (self.state.read_ledger(now.strftime("%Y-%m-%d"))
                + self.state.read_ledger((now - timedelta(days=1)).strftime("%Y-%m-%d")))

    def _unfinished_queues(self, now: datetime, entries: list[dict]) -> list[str]:
        """Queues that came due recently and are still missing one of their scripts.

        "No game process" is not the same as "the queue is finished". Between
        two scripts in one queue there is a window - MAA has exited, MaaEnd's
        game is still launching - where neither process exists, and the same
        window exists at the very start before the first game comes up. Acting
        in it costs a run: it cost 终末地 the morning of 2026-08-16.
        """
        out: list[str] = []
        for q in plan.recent_due_queues(self.cfg.automas_dir, now):
            # Only runs started at or after this queue's own time count -
            # otherwise the morning's MaaEnd would satisfy the evening queue.
            ran = {e["script"] for e in entries
                   if datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                   >= q["due"] - timedelta(minutes=5)}
            if missing := [k for k in q["kinds"] if k not in ran]:
                out.append(f"队列「{q['name']}」还差 {'、'.join(missing)}")
        return out

    def _hands_on_machine(self, now: datetime) -> int:
        """Seconds since someone last drove the desktop through `ark-do`, or -1.

        The 21:30 checkpoint cannot tell "nobody is here" from "somebody is
        working on this machine right now", so it used to power off under
        whoever was mid-maintenance. Vetoing on an open SSH or ToDesk session
        was tried and was worse than useless - both come up automatically at
        boot, so the veto never lifted.

        A GUI action is different: `ark-do` only ever runs because a person
        asked for a click, a keystroke or a screenshot. It stamps this file on
        every batch, so the hold is bounded by the last action rather than by
        anything that merely stays connected.
        """
        mark = Path(self.state.dir) / "ark-do-last.txt"
        try:
            stamp = int(mark.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return -1
        # A clock the other way round means a stale or corrupt stamp; ignore it
        # rather than hold the machine open forever on a bad number.
        age = int(now.timestamp()) - stamp
        return age if 0 <= age <= 86400 else -1

    def _boot_time(self, now: datetime) -> datetime | None:
        """When this machine last booted, or None if it cannot be determined.

        Uptime, not the relay's own start time: the relay restarts itself for
        every selfupdate, so its start time says nothing about why the machine
        is awake. `GetTickCount64` is a kernel counter read, cheap enough to
        call on every tick.
        """
        try:
            import ctypes  # noqa: PLC0415 - Windows only, imported where used

            ms = ctypes.windll.kernel32.GetTickCount64()  # type: ignore[attr-defined]
        except (AttributeError, OSError, ImportError):
            return None
        if not ms or ms < 0:
            return None
        return now - timedelta(milliseconds=ms)

    def _work_is_done(self, now: datetime, entries: list[dict]) -> bool:
        """True when this boot's queue has come due and produced all its records.

        The durable version of `_handled_any`, which only knows what *this
        process* watched land. A relay restart after the last run - a
        selfupdate is exactly that - cleared the flag, so nothing was left to
        trigger the shutdown and the machine stayed awake all night. It cost
        2026-08-20 a manual power-off.

        Two requirements, and dropping either one costs a run:

        A queue must actually have come due. "Nothing is unfinished" is
        vacuously true at 08:50 with the 09:00 queue still ahead, and acting on
        it would power the machine off minutes before its own run.

        And the machine must have booted *before* that queue was due - this
        boot has to be the one the queue was scheduled for. Without that test
        the rule reaches a machine somebody powered on at 10:35 to work on: the
        09:00 queue is still inside its two-hour window and its records are
        already in the ledger from the morning, so "everything is finished"
        reads true and the machine switches off under them ten minutes later.
        Uptime is what distinguishes the two, not the relay's start time, which
        every selfupdate resets.

        Residual, deliberately not widened: `recent_due_queues` forgets a queue
        two hours after it was due, so a restart later than that still leaves
        no one to shut down. Widening the window here would also widen the
        "wait for a script that never ran" hold that shares it.
        """
        due = plan.recent_due_queues(self.cfg.automas_dir, now)
        if not due:
            return False
        booted = self._boot_time(now)
        if booted is None:
            return False        # cannot prove this boot belongs to the queue
        if booted > min(q["due"] for q in due):
            return False        # somebody powered this on after the queue ran
        return not self._unfinished_queues(now, entries)

    def _enforce_annihilation(self) -> None:
        """Once this week's annihilation (剿灭) is done, make sure the switch
        is off - but only write while no script is running.

        AUTO-MAS overwrites ScriptConfig while it runs, so a write made then
        is a write thrown away (see the note on annihilation.enforce).
        """
        if self._scripts_running():
            return
        try:
            self._annihilation.enforce()
        except Exception:  # noqa: BLE001 - a failed fix must not break the tick
            log.exception("剿灭开关校正出错")

    def _round_is_manual(self, new_entries: list[dict]) -> bool:
        """Whether this round was triggered by hand rather than by the schedule.

        Manual rounds have to be labelled separately (operator order,
        2026-08-20): a scheduled round and a hand-triggered make-up run must
        be distinguishable at a glance, or the operator cannot judge whether
        a given message was supposed to appear at all.

        The test looks only at how far this round's earliest record sits from
        a scheduled time - and the scheduled times are read straight from
        AUTO-MAS's queue config, so changing the schedule needs no matching
        change here. If no schedule can be read it returns False: better to
        leave a round unlabelled than to mislabel a scheduled one as manual.
        """
        times = [t for q in plan.schedule(self.cfg.automas_dir)
                 for t in q.get("times", [])]
        if not times or not new_entries:
            return False
        try:
            first = min(datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                        for e in new_entries)
        except (KeyError, ValueError):
            return False
        for hhmm in times:
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = first.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if abs((first - due).total_seconds()) <= MANUAL_WINDOW_MIN * 60:
                return False
        return True

    def _last_round_manual(self, now: datetime, entries: list[dict]) -> bool:
        """True when the day's most recent round was triggered by hand.

        A manual round must not count as "the day's work is done". On
        2026-08-21 a hand-triggered MaaEnd test finished at 12:29 and the
        relay promptly powered the machine off - while the operator was in
        the middle of working on it, and hours before the evening queue.

        The round is the group of records that finished close together; two
        hours is comfortably wider than a full queue (MAA then MaaEnd) and
        far narrower than the gap between the morning and evening queues.
        """
        if not entries:
            return False
        try:
            starts = [datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                      for e in entries]
        except (KeyError, ValueError):
            return False
        newest = max(starts)
        group = [e for e, t in zip(entries, starts)
                 if newest - t <= timedelta(hours=2)]
        return self._round_is_manual(group)

    def _maybe_interim_report(self, now: datetime | None = None) -> None:
        """Report once the day's earlier queues are done, hours before the
        daily summary is due.

        This used to live inside the shutdown path, which coupled two unrelated
        things: turning shutdown off for an afternoon of maintenance also
        silently turned off the morning report, and the operator was left with
        a machine that had run and said nothing. What decides this is "the
        morning queue finished", not "I am about to power off".
        """
        if not self.cfg.interim_report:
            return
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        if self.state.report_sent(day):
            return
        if now >= self._report_cutoff(now):
            return          # the real daily report is due; let it do the talking
        entries = self.state.read_ledger(day)
        if not entries or self._scripts_running():
            return
        if self._unfinished_queues(now, entries):
            return
        # Once per finished daytime ROUND, not once per day: a make-up run
        # adds entries past the covered mark and deserves its own interim
        # (operator order 2026-08-20 - the silent afternoon rerun taught us).
        covered = self.state.interim_covered(day)
        if len(entries) <= covered:
            return
        # Judge manual-vs-scheduled from this round's new entries only; the
        # earlier rounds have each already been reported on their own.
        label = "手动执行" if self._round_is_manual(entries[covered:]) else "临时查看"
        if self.send_daily_now(mark=False, label=label):
            self.state.mark_interim_sent(day, len(entries))
            log.info("🔎 %s 已推送「%s」（覆盖 %d 条记录）", day, label, len(entries))

    def _maybe_daily_report(self, now: datetime | None = None) -> None:
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        # Yesterday first. Everything below keys off "today", so a report that
        # could not be delivered before midnight (channel outage - it has
        # happened: 60020 all day on 2026-08-20) used to be abandoned the
        # moment the date rolled: today's ledger is a different file, and no
        # code path ever looked back. The runs are still in yesterday's
        # ledger; send their report late rather than never.
        yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        if not self.state.report_sent(yday) and (
                y_entries := self.state.read_ledger(yday)):
            title, body = self._compose_daily(yday, y_entries)
            if errors := self.notifier.send(title + "（补发）", body):
                log.error("昨日日报补发失败，稍后重试: %s", "；".join(errors))
            else:
                self.state.mark_report_sent(yday)
                log.info("📋 %s 日报已补发（%d 条记录）", yday, len(y_entries))
        if self.state.report_sent(day):
            return
        entries = self.state.read_ledger(day)
        if not entries:
            return
        # Due once the clock is past the day's last queue and nothing is still
        # working - never based on when a run happened to finish.
        if now < self._report_cutoff(now) or self._scripts_running():
            return
        # The cutoff *is* the last queue's start time, so this check first comes
        # true in the seconds after that queue fires - while its game is still
        # launching and no process exists yet. With earlier runs already in the
        # ledger the report looked complete, so it went out describing only the
        # morning and marked the day done; the evening run would then never be
        # reported at all. Same guard the shutdown path already uses.
        if unfinished := self._unfinished_queues(now, self.state.read_ledger(day)):
            log.info("日报再等等：%s", "；".join(unfinished))
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
        # Debug mode outranks everything below, the idle checkpoint included:
        # a boot with nothing scheduled is exactly what debugging looks like,
        # and powering it off is exactly what the operator asked not to happen.
        if modes.debug_active(self.state.dir):
            return False
        if not self.cfg.shutdown_after_run:
            return False
        # `shutdown /s /t 60` only starts a countdown; the loop keeps ticking
        # through it. Without this flag the whole block ran again every poll -
        # on 2026-08-16 that sent the pre-shutdown report three times in 60
        # seconds and re-issued the shutdown twice.
        if self._shutdown_issued:
            return False
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        idle = self._idle_checkpoint(now)
        entries = self._recent_entries(now)
        # `_handled_any` is the fast path for the ordinary case; `_work_is_done`
        # is what survives a restart between the last run and the shutdown.
        if not (self._handled_any or self._work_is_done(now, entries)) and not idle:
            return False
        # The uptime floor guards against a boot -> immediate-shutdown loop.
        # The idle checkpoint is exempt: it *is* a deliberate quick power-off
        # of a purposeless boot, its window is only five minutes wide, and it
        # cannot loop (the next wake is the machine's own timer, hours away).
        # Held to the floor, it was unreachable whenever the service came up
        # less than shutdown_min_uptime before the checkpoint - the 2026-08-19
        # all-night wake.
        if (not idle and (now - self._started_at).total_seconds()
                < self.cfg.shutdown_min_uptime):
            return False
        if self._scripts_running() or self._pending or self._recovered:
            return False
        # Somebody is working on this desktop. Hold, but only for a bounded
        # time after their last action - an open-ended hold would turn one
        # forgotten screenshot into a machine that never sleeps again.
        hands = self._hands_on_machine(now)
        if 0 <= hands < MAINTENANCE_HOLD_SEC:
            note = (f"{hands // 60} 分钟前有人在这台机器上操作过，"
                    f"暂不关机（{MAINTENANCE_HOLD_SEC // 60} 分钟无操作后放行）")
            if note != self._last_wait_note:
                self._last_wait_note = note
                log.info(note)
            return False
        # "No game process" is not the same as "the queue is finished". Between
        # two scripts in one queue there is a window - MAA has exited, MaaEnd's
        # game is still launching - where neither process exists. Powering off
        # in that window costs a whole run, so also require that every script
        # today's due queues contain has actually produced a record.
        day = now.strftime("%Y-%m-%d")
        if self._last_round_manual(now, entries):
            note = "最近一轮是手动触发的，不当作当天收工，不关机"
            if note != self._last_wait_note:
                self._last_wait_note = note
                log.info(note)
            return False
        if unfinished := self._unfinished_queues(now, entries):
            # Log only when the answer changes. Repeating the same line every
            # poll buries the lines that matter under forty identical ones.
            note = "；".join(unfinished)
            if note != self._last_wait_note:
                self._last_wait_note = note
                log.info("不关机：%s", note)
            return False
        self._last_wait_note = ""
        cutoff = self._report_cutoff(now)   # same source as the report itself
        # An empty ledger means the day had nothing scheduled at all - queues
        # disabled, or a boot with no work. There is no report to wait for and
        # _maybe_daily_report returns early without ever marking one sent, so
        # waiting here waits forever: on 2026-08-19 the evening boot sat awake
        # all night on exactly this. Only hold the machine open when the day
        # actually produced runs that still owe a report.
        if (now >= cutoff and not self.state.report_sent(day)
                and self.state.read_ledger(day)):
            log.info("到点该关机了，但日报还没发出去，继续等")
            return False
        # Never power off in silence. If the day's real report has not gone out
        # yet - which is the case after the morning queue - send an interim one
        # first, so the machine is never dark without the operator knowing what
        # it did. A timed task cannot do this job: it would have to fire in the
        # gap between "run finished" and "machine off", and that gap moves.
        # Normally already sent by _maybe_interim_report; this is the backstop
        # for the case where that failed to deliver.
        if (self.cfg.report_before_shutdown and not self.state.report_sent(day)
                and not self.state.interim_sent(day)):
            log.info("关机前补发一份当前进度")
            if self.send_daily_now(mark=False):
                self.state.mark_interim_sent(
                    day, len(self.state.read_ledger(day)))

        log.info("本轮已处理完毕，60 秒后关机")
        try:
            subprocess.run(["shutdown", "/s", "/t", "60",
                            "/c", "ark-relay: run complete"], timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            log.exception("关机命令执行失败")
            return False
        self._shutdown_issued = True
        return True

    def _compose_daily(self, day: str, entries: list[dict]) -> tuple[str, str]:
        """Model writes the report from the raw records; code only decides the
        headline (green / how many failed), which must never be a guess."""
        tomorrow = plan.next_plan(self.cfg.automas_dir)
        failed = [e for e in entries if not e["ok"]]
        head = "全绿 ✅" if not failed else f"{len(failed)} 项出错 ⚠️"
        title = f"📋 {day[5:]} · {head}"
        # Event countdown rides on every report (operator order, 2026-08-20):
        # a fixed-stage config plus an event ending overnight is a silent
        # next-morning failure. Appended outside the model's text so a model
        # outage can never drop it.
        act = plan.activity_countdown(self.cfg.automas_dir)
        written = summary.daily_report(self.cfg, entries, tomorrow)
        if written:
            log.info("📋 日报由模型撰写（%d 条记录）", len(entries))
            return title, written + (f"\n\n{act}" if act else "")
        log.warning("模型不可用，日报回退到结构化排版")
        title2, body = core.format_daily(day, entries, "", tomorrow)
        return title2, body + (f"\n\n{act}" if act else "")

    def send_daily_now(self, mark: bool = True, label: str = "临时查看") -> bool:
        """Force today's report out (used by the `report` command and tests).

        `mark=False` sends an interim look at the day so far without consuming
        the day's report - the evening summary still goes out on schedule.
        Marking it would silently cancel that summary, which is the opposite of
        what someone asking for a mid-day check wants.

        `label` distinguishes the two non-consuming kinds: 「临时查看」for a
        scheduled daytime round, 「手动执行」for a round someone triggered by
        hand. See docs/NOTIFICATIONS.md - that distinction is required, not
        cosmetic: the operator has to be able to tell why a summary appeared.
        """
        now = datetime.now(tz=SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        entries = self.state.read_ledger(day)
        title, body = self._compose_daily(day, entries)
        if not mark:
            title = title.replace("📋", "🔎", 1) + f"（{label}）"
        errors = self.notifier.send(title, body)
        if errors:
            log.error("日报推送失败: %s", "；".join(errors))
            return False
        if mark:
            self.state.mark_report_sent(day)
        return True
