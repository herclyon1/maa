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
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import texts
from . import handle, missed, modes, plan, report, shutdown
from .config import SERVER_TZ, Config, RunRecord
from .core import State
from .missed import MISSED_GRACE_MIN
from .shutdown import CHECK_OPEN_MIN
from .notify import Notifier
from .transport import Source

log = logging.getLogger("ark.engine")
# Short-lived cache for `_scripts_running`; see the comment on that method.
_SCRIPTS_CACHE: dict = {"at": -1e9, "val": False}
_SCRIPTS_TTL = 3.0

_RUNTIME_PATH = "/api/dispatch/runtime-snapshot"   # the only confirmed GET endpoint
# Terminal states AUTO-MAS marks on a script/user. Anything not listed here
# (running, waiting, and anything we have never seen) counts as still running.
_SNAPSHOT_DONE = {"完成", "异常", "失败", "跳过", "中止", "取消"}


def _judge_snapshot(snap) -> bool:
    """Does runtime-snapshot still hold an unfinished task?

    The real 2026-09-07 10:18 sample this was written against is in the tests.
    """
    for task in (snap or {}).get("tasks") or []:
        info = task.get("task_info") or []
        if not info:
            return True          # just dispatched, no status of any kind yet
        for item in info:
            if str(item.get("status") or "") not in _SNAPSHOT_DONE:
                return True
    return False


def _automas_busy():
    """Ask AUTO-MAS whether a task is running. True/False; None when it cannot be asked."""
    import json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    from .config import mas_base  # noqa: PLC0415
    try:
        with urllib.request.urlopen(mas_base() + _RUNTIME_PATH, timeout=3) as r:
            return _judge_snapshot(json.loads(r.read().decode("utf-8")))
    except Exception:  # noqa: BLE001 - no endpoint -> fall back to the process check
        return None


class Engine:
    def __init__(self, cfg: Config, source: Source, state: State, notifier: Notifier):
        self.cfg = cfg
        self.source = source
        self.state = state
        self.notifier = notifier
        # Hook for the last pull of pending orders before powering off, wired up by
        # service (see _maybe_shutdown). None when running tests standalone, and then
        # nothing is pulled.
        self._before_shutdown = None
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
        # The weekly garden and annihilation are the same shape of problem: something
        # that only needs doing once a week should not be visited every day. The only
        # difference is which switch gets turned off - annihilation's is MAA's, this
        # one's is OK-WW's "Check Weekly Garden" additional task.
        from .garden import GardenGate     # noqa: PLC0415 - optional feature
        # Since 2026-08-28 this writes the master copy directly instead of going
        # through the MAS API - that path requires quick-config to be on, and
        # quick-config has been abandoned.
        self._garden = GardenGate(state.dir, cfg.automas_dir)
        from .weeklyboss import WeeklyBossGate  # noqa: PLC0415 - avoid import cycle
        self._weeklyboss = WeeklyBossGate(state.dir, cfg.automas_dir)

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
                    self.notifier.send(texts.SKIP_MODE, msg)
        except Exception:
            log.exception("跳过模式处理出错")
        active = modes.debug_active(self.state.dir)
        if active != self._debug_last:
            if active:
                log.info("🔧 调试模式生效（至 %s）：不关机、不报漏跑",
                         modes.debug_until(self.state.dir))
            elif self._debug_last is not None:
                log.info("🔧 调试模式已结束，恢复正常判定")
                # Settled by the user on 2026-09-02: debug mode is a one-shot
                # switch that skips the shutdown after this one round, and turning it
                # off does **not** make anyone go back and run that shutdown - the
                # machine simply stays up until the next queue finishes. That is the
                # intended design; do not add a catch-up shutdown here.
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
        # Guarded like every other step below, and for the same reason. This one
        # sits before the loop, so an exception here kills the *whole* tick -
        # including the daily report and the shutdown decision at the end of it,
        # every single round. That is the exact shape of the 2026-09-04 incident
        # described below, and service.py's outer try only converts it into
        # "the relay quietly does nothing", which is worse than a crash.
        # `modes.process_skip` guards itself; `debug_active` / `debug_until` did not.
        try:
            self._observe_modes()
        except Exception:
            log.exception("读模式开关出错，本轮按「没开任何模式」继续")
        try:
            records = self.source.fetch(self.state.seen)
        except Exception:
            log.exception("读取运行记录失败，本轮按没有新记录处理")
            records = []
        for rec in records:
            try:
                self._handle(rec)
            except Exception:
                log.exception("处理运行记录失败: %s", rec.run_id)
                continue
            self.state.mark_seen(rec.run_id)
            self._handled_any = True
        # Every step is caught on its own; a broken one must not take the rest with
        # it. On 2026-09-04 a single ImportError in the "tomorrow's schedule" step
        # carried off the deferred update, the daily report and the auto shutdown
        # behind it, and the machine stayed powered up all morning with nobody
        # noticing - shutdown and the daily report are the last two steps, exactly the
        # ones that must not be killed off by an earlier one.
        for what, step in (
            ("刷声骸到点收工", self._echo_farm_deadline),
            ("OK-WW 补丁", self._patch_okww_if_updated),
            ("推送积压告警", self._flush_pending),
            ("剿灭开关", self._enforce_annihilation),
            ("周常门", self._weekly_gates),
            ("漏跑检查", self._check_missed_runs),
            ("临时查看", self._maybe_interim_report),
            ("队列后更新", self._maybe_deferred_update),
            ("日报", self._maybe_daily_report),
            ("关机", self._maybe_shutdown),
        ):
            try:
                step()
            except Exception:
                log.exception("本轮「%s」这一段出错，跳过它继续", what)
        return len(records)

    def _echo_farm_deadline(self) -> None:
        """End a 「farm until HH:MM」 run when its moment arrives.

        OK-WW counts runs, not minutes, so the clock has to live here. Checked on
        every tick, which is event-driven already - no timer of its own.
        """
        from . import echofarm  # noqa: PLC0415
        note = echofarm.tick(self.cfg)
        if note:
            log.info("刷声骸：%s", note)
            self.notifier.send(texts.ECHO_FARM_DONE, note)

    def _patch_okww_if_updated(self) -> None:
        """Re-apply the patches if OK-WW updated itself; leave it alone while a script runs."""
        if self._scripts_running():
            return
        from . import okww_patch  # noqa: PLC0415
        okww = self.cfg.okww_dir or (
            Path(self.cfg.automas_dir).parent / "okww" if self.cfg.automas_dir else None)
        notes = okww_patch.ensure_if_updated(self.state.dir, okww)
        for n in notes:
            log.info("补丁：%s", n)
        if notes:
            self.notifier.send(texts.patches(len(notes), notes),
                               "\n".join(f"· {n}" for n in notes))

    def _weekly_gates(self) -> None:
        try:
            self._garden.enforce()
            self._weeklyboss.enforce()
        except Exception:
            log.warning("周常乐园开关没能落盘，下轮再试", exc_info=True)

    # ---------- update the game clients only after the queue is done ----------

    def _deferred_update_busy(self) -> bool:
        t = getattr(self, "_gu_thread", None)
        return bool(t is not None and t.is_alive())

    def _maybe_deferred_update(self) -> None:
        """Registered + queues finished + nothing running -> update in a background
        thread, then re-run.

        The order the user settled on 2026-09-02: let the other games finish first,
        then update on its own and re-run on its own. _maybe_shutdown will not power
        off while the thread is alive; the re-run itself is a script dispatched by
        AUTO-MAS, so once it starts _scripts_running blocks shutdown as usual. At most
        once a day.
        """
        from . import gameupdate  # noqa: PLC0415
        if self._deferred_update_busy() or not gameupdate.pending(self.state.dir):
            return
        now = datetime.now(tz=SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        why = ""
        if getattr(self, "_gu_day", "") == day:
            why = "今天已经起过一次"
        elif self._scripts_running():
            why = "有脚本在跑"
        elif not self.state.read_ledger(day):
            why = "今天还没有任何运行记录"
        elif unfinished := self._unfinished_queues(now, self._recent_entries(now)):
            why = "队列没跑完：" + "；".join(unfinished)
        if why:
            # One line only when the reason changes, so it does not spam every 30s
            if why != getattr(self, "_gu_wait_note", ""):
                self._gu_wait_note = why
                log.info("游戏更新：有登记但先不动（%s）", why)
            return
        self._gu_wait_note = ""
        import threading  # noqa: PLC0415
        self._gu_day = day

        def work() -> None:
            from . import commands  # noqa: PLC0415
            try:
                def _dispatch(name: str):
                    self._gu_rerun_at = datetime.now(tz=SERVER_TZ)
                    return commands.run_script(name)
                notes, problems, reran = gameupdate.run_deferred(
                    self.cfg, now=now, dispatch=_dispatch)
                for n in notes:
                    self.notifier.send(texts.GAME_UPDATE, n)
                if reran:
                    self.notifier.send(texts.RERUN_AFTER_UPDATE, texts.rerun_body(reran))
                if problems:
                    self.notifier.send(texts.unconfirmed("游戏更新", len(problems)),
                                       "\n".join(f"· {x}" for x in problems))
            except Exception:
                log.exception("游戏更新（队列后）出错")

        self._gu_thread = threading.Thread(target=work, name="game-update", daemon=True)
        self._gu_thread.start()
        log.info("游戏更新：队列已跑完，后台开始更新 %s", "、".join(gameupdate.pending(self.state.dir)))

    # These MaaEnd items fail because of upstream or the game itself; they are not
    # faults anybody has to get up in the middle of the night for:
    # 来龙去脉见 docs/CODE-HISTORY.md「engine.py:Engine」
    SOFT_FAILS = {"应急理智加强剂", "自动采集"}

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
        """True while AUTO-MAS says a task is in progress, or a game process is alive.

        Ask AUTO-MAS first (/api/dispatch/runtime-snapshot: the state of every script
        in the queue) and fall back to the process list only when it cannot be reached.
        Going by processes alone has burned us: on 2026-09-07 10:15 OK-WW was on its
        third round, it was not in the process list, the relay took that to mean nothing
        was running, and it raised two false alarms, 「OK-WW 没有运行」 and
        「MaaEnd 没有运行」 - AUTO-MAS only writes a record once the whole script ends.
        A failure is only worth reporting once nothing is still trying.
        """
        if os.name != "nt":
            return False
        # One tick asks this a dozen times over (skip mode, held-back alerts, missed
        # runs, interim report, daily report, shutdown ... each asks separately). An
        # answer less than three seconds old is reused as is.
        now = time.monotonic()
        if now - _SCRIPTS_CACHE["at"] < _SCRIPTS_TTL:
            return _SCRIPTS_CACHE["val"]
        busy = _automas_busy()
        if busy:
            val = True
        else:
            try:
                out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                                     capture_output=True, timeout=20).stdout
            except (OSError, subprocess.SubprocessError):
                val = True  # cannot tell -> wait rather than cry wolf
            else:
                # Endfield.exe has to be counted too: MaaEnd **has no process of
                # its own**, AUTO-MAS's python drives it in-process, so watching only
                # MaaEnd.exe goes blind for the entire Endfield stretch.
                # 来龙去脉见 docs/CODE-HISTORY.md「engine.py:_scripts_running」
                val = any(n in out for n in (b"MAA.exe", b"MaaEnd.exe", b"Endfield.exe"))
        _SCRIPTS_CACHE["at"], _SCRIPTS_CACHE["val"] = now, val
        return val

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

        # A farm has two clock needs and neither was registered here, so the loop
        # slept until whatever the next queue alarm happened to be. On 2026-09-09 the
        # gaps ran to 21 minutes: OK-WW stopped at 06:45 and nothing looked at it
        # until 07:06. Its deadline is a moment like any other, and while it runs the
        # loop has to come back often enough to notice the task has died.
        from . import echofarm  # noqa: PLC0415
        if rec := echofarm.current(self.cfg.state_dir):
            if until := echofarm.deadline_of(rec):
                cands.append((until, "刷声骸到点收工"))
            cands.append((now + timedelta(minutes=echofarm.RESTART_QUIET_MINUTES),
                          "看一眼刷声骸还活着没"))

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
        except Exception:
            log.exception("剿灭开关校正出错")

    # ---------- bookkeeping and alerts (handle.py) ----------
    def _handle(self, rec: RunRecord) -> None:
        return handle._handle(self, rec)

    def _verify_outcome(self, rec: RunRecord) -> str | None:
        return handle._verify_outcome(self, rec)

    def _archive_maaend_evidence(self, rec: RunRecord) -> None:
        return handle._archive_maaend_evidence(self, rec)

    def _warn_if_evidence_stale(self, rec: RunRecord, dst: Path) -> None:
        return handle._warn_if_evidence_stale(self, rec, dst)

    def _maintenance_today(self, game: str) -> bool:
        return handle._maintenance_today(self, game)

    def _alert_key(self, rec) -> str:
        return handle._alert_key(self, rec)

    def _alerted_file(self, day: str) -> Path:
        return handle._alerted_file(self, day)

    def _already_alerted(self, day: str, key: str) -> bool:
        return handle._already_alerted(self, day, key)

    def _mark_alerted(self, day: str, key: str) -> None:
        return handle._mark_alerted(self, day, key)

    def _flush_pending(self) -> None:
        return handle._flush_pending(self)

    # ---------- missed runs and missing items (missed.py) ----------
    def _check_missed_runs(self, now: datetime | None = None,
                           grace_min: int = MISSED_GRACE_MIN) -> None:
        return missed._check_missed_runs(self, now, grace_min)

    def _check_partial_queues(self, now: datetime, day: str,
                              entries: list[dict]) -> None:
        return missed._check_partial_queues(self, now, day, entries)

    # ---------- daily report and interim view (report.py) ----------
    def _report_cutoff(self, now: datetime) -> datetime:
        return report._report_cutoff(self, now)

    def _maybe_interim_report(self, now: datetime | None = None) -> None:
        return report._maybe_interim_report(self, now)

    def _maybe_daily_report(self, now: datetime | None = None) -> None:
        return report._maybe_daily_report(self, now)

    def _compose_daily(self, day: str, entries: list[dict]) -> tuple[str, str]:
        return report._compose_daily(self, day, entries)

    def _announce_banners(self, now: datetime, nxt) -> None:
        return report._announce_banners(self, now, nxt)

    def send_daily_now(self, mark: bool = True, label: str = "临时查看") -> bool:
        return report.send_daily_now(self, mark, label)

    # ---------- shutdown decision (shutdown.py) ----------
    def _idle_checkpoint(self, now: datetime | None = None) -> bool:
        return shutdown._idle_checkpoint(self, now)

    def _boot_time(self, now: datetime | None = None) -> datetime | None:
        return shutdown._boot_time(self, now)

    def _recent_entries(self, now: datetime) -> list[dict]:
        return shutdown._recent_entries(self, now)

    def _unfinished_queues(self, now: datetime, entries: list[dict]) -> list[str]:
        return shutdown._unfinished_queues(self, now, entries)

    def _work_is_done(self, now: datetime, entries: list[dict]) -> bool:
        return shutdown._work_is_done(self, now, entries)

    def _round_is_manual(self, new_entries: list[dict]) -> bool:
        return shutdown._round_is_manual(self, new_entries)

    def _last_round_manual(self, now: datetime, entries: list[dict]) -> bool:
        return shutdown._last_round_manual(self, now, entries)

    def _shutdown_key(self, now: datetime) -> str:
        return shutdown._shutdown_key(self, now)

    def _maybe_shutdown(self, now: datetime | None = None) -> bool:
        return shutdown._maybe_shutdown(self, now)

    def _power_off(self) -> bool:
        """Issue the actual shutdown command. It lives here so tests can swap out subprocess."""
        log.info("本轮已处理完毕，60 秒后关机")
        try:
            subprocess.run(["shutdown", "/s", "/t", "60",
                            "/c", "ark-relay: run complete"], timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            log.exception("关机命令执行失败")
            return False
        return True
