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

from ark_relay.core import texts
from ark_relay.features.alarm import handle, missed
from ark_relay.features.modes import modes
from ark_relay.core import plan
from ark_relay.features.report import report
from ark_relay.features.shutdown import shutdown
from ark_relay.core.config import SERVER_TZ, Config, RunRecord
from ark_relay.core.ledger import State
from ark_relay.features.alarm.missed import MISSED_GRACE_MIN
from ark_relay.core.notify import Notifier
from ark_relay.core.transport import Source

log = logging.getLogger("ark.engine")
# Short-lived cache for `_scripts_running`; see the comment on that method.
_SCRIPTS_CACHE: dict = {"at": -1e9, "val": False}
_SCRIPTS_TTL = 3.0


def forget_scripts_cache() -> None:
    """Drop the cached `_scripts_running` answer, so the next ask goes to AUTO-MAS.

    For whoever has just started something (a queued phone order applied, a
    make-up dispatched): within the same tick the shutdown decision or the
    make-up step would otherwise reuse the 「nothing runs」 read before it, and
    power off or dispatch on top of the run that has just been started.
    """
    _SCRIPTS_CACHE["at"], _SCRIPTS_CACHE["val"] = -1e9, False

_RUNTIME_PATH = "/api/dispatch/runtime-snapshot"   # the only confirmed GET endpoint
# Terminal states AUTO-MAS marks on a script/user. Anything not listed here
# (running, waiting, and anything we have never seen) counts as still running.
_SNAPSHOT_DONE = {"完成", "异常", "失败", "跳过", "中止", "取消"}


def _task_unfinished(task) -> bool:
    """Is this one runtime-snapshot task still unfinished?

    The one criterion shared by `_judge_snapshot` and the red button
    (commands._estop_live_tasks), so the two can never disagree about what
    "still running" means.
    """
    info = (task or {}).get("task_info") or []
    if not info:
        return True              # just dispatched, no status of any kind yet
    return any(str(item.get("status") or "") not in _SNAPSHOT_DONE for item in info)


def _judge_snapshot(snap) -> bool:
    """Does runtime-snapshot still hold an unfinished task?

    The real 2026-09-07 10:18 sample this was written against is in the tests.
    """
    return any(_task_unfinished(task) for task in (snap or {}).get("tasks") or [])


def _script_unfinished(snap, name: str) -> bool:
    """Is the script `name` (MAA / OK-WW / MaaEnd) still unfinished in this snapshot?

    Narrower than `_judge_snapshot` on purpose: a held failure of one script only
    has to wait for that script's own retries, not for the rest of the queue.
    2026-10-01: OK-WW's three timed-out rounds landed at 15:23 with OK-WW already
    「异常」, but MaaEnd ran on until past 16:10 and the alarm waited behind it.
    """
    for task in (snap or {}).get("tasks") or []:
        info = (task or {}).get("task_info") or []
        if not info:
            return True          # just dispatched, cannot tell which script yet
        if any(str(item.get("name") or "") == name
               and str(item.get("status") or "") not in _SNAPSHOT_DONE for item in info):
            return True
    return False


def _automas_snapshot():
    """AUTO-MAS's runtime-snapshot, parsed; None when it cannot be asked."""
    import json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    from ark_relay.core.config import mas_base  # noqa: PLC0415
    try:
        with urllib.request.urlopen(mas_base() + _RUNTIME_PATH, timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - no endpoint -> fall back to the process check
        return None


def _automas_busy():
    """Ask AUTO-MAS whether a task is running. True/False; None when it cannot be asked."""
    snap = _automas_snapshot()
    if snap is None:
        return None
    busy = _judge_snapshot(snap)
    _note_other_modes(snap, busy)
    return busy


# Where _note_other_modes keeps what it saw and finds AUTO-MAS's app.log; set by
# Engine.__init__ (a process that built no engine notes nothing).
_BUSY_SEEN: dict = {"state_dir": None, "automas_dir": None}
BUSY_FILE = "machinecheck-busy.json"      # read by machinechecks/system.py (#18)
# An app.log task with no end line counts as open for this long after its start.
OTHER_MODE_OPEN_MIN = 30
_APPLOG_TAIL = 512 * 1024


def _note_other_modes(snap, busy: bool, now: "datetime | None" = None) -> None:
    """Keep, for the machine check #18, what AUTO-MAS's runtime-snapshot said while a
    task of a mode other than AutoProxy (a 设置脚本 session, say) was open: whether it
    was counted as running. A master edit made during such a session is copied over
    when it ends (docs/BACKLOG.md, 2026-09-30 audit), so it has to count.

    Listed in the snapshot and unfinished: counted. Not listed at all while app.log
    has its 「创建任务」 line (OTHER_MODE_OPEN_MIN old at most) and no end line, with
    the snapshot saying nothing runs: not counted. One entry per task and answer.
    Never raises."""
    state_dir = _BUSY_SEEN["state_dir"]
    if not state_dir:
        return
    try:
        _note_other_modes_in(Path(state_dir), _BUSY_SEEN["automas_dir"], snap, busy,
                             (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ))
    except Exception:  # evidence for a check; never in the way of the answer
        log.debug("没记下调度程序非代理任务的忙闲", exc_info=True)


def _note_other_modes_in(state_dir: Path, automas_dir, snap, busy: bool, now: datetime) -> None:
    import json  # noqa: PLC0415
    from ark_relay.features.guard import trigger  # noqa: PLC0415
    from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
    at = now.strftime("%m-%d %H:%M:%S")
    found: list[dict] = []
    listed = set()
    for task in (snap or {}).get("tasks") or []:
        tid = str((task or {}).get("taskId") or "")
        listed.add(tid)
        mode = str((task or {}).get("mode") or "")
        if mode and mode != "AutoProxy" and _task_unfinished(task):
            states = "、".join(f"{i.get('name')} {i.get('status')}" for i in task.get("task_info") or [])
            found.append({"at": at, "task": tid, "mode": mode, "busy": True,
                          "line": f"快照里列着、没完成：{states or '还没有状态'}"})
    if not busy and automas_dir:
        f = Path(automas_dir) / "debug" / "app.log"
        try:
            with f.open("rb") as fh:
                fh.seek(max(0, f.stat().st_size - _APPLOG_TAIL))
                lines = fh.read().decode("utf-8", "replace").splitlines()
        except OSError:
            lines = []
        for t in trigger.parse(lines):
            if (t.mode != "AutoProxy" and t.ended is None
                    and timedelta(0) <= now - t.created <= timedelta(minutes=OTHER_MODE_OPEN_MIN)
                    and not any(tid and (t.id == tid or t.id.startswith(tid)) for tid in listed)):
                found.append({"at": at, "task": t.id, "mode": t.mode, "busy": False,
                              "line": f"调度程序日志 {t.created:%H:%M:%S} 创建任务 {t.id[:8]}，"
                                      f"模式 {t.mode}，触发来源 {t.source}，还没有结束那一行；快照里没有它"})
    if not found:
        return
    path = state_dir / BUSY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    seen = data.get("seen") if isinstance(data, dict) and isinstance(data.get("seen"), list) else []
    known = {(o.get("task"), o.get("busy")) for o in seen if isinstance(o, dict)}
    new = [o for o in found if (o["task"], o["busy"]) not in known]
    if new:
        state_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps({"seen": (seen + new)[-50:]}, ensure_ascii=False, indent=1))


# A skip of a queue (跳过模式, skip_today) that did not take effect, or whose restore
# failed: a failure that did not recover, so it goes to the group every time it is
# said (the user, 2026-10-06: 「不论多少次什么错误都要发」). texts.SKIP_MODE, which
# notify routes to the log only, stays for the acknowledgements.
SKIP_FAILED = texts.SKIP_FAILED


def skip_failed(state_dir, msg: str) -> bool:
    """Whether a message of modes.process_skip is a failure: modes writes every failed
    engage or restore as a red receipt (ok false) with the same words, for the phone
    page; an acknowledgement is a green receipt or none."""
    text = str(msg)[:200]
    return any(r.get("ok") is False and r.get("text") == text for r in modes.receipts(state_dir))


class Engine:
    def __init__(self, cfg: Config, source: Source, state: State, notifier: Notifier):
        self.cfg = cfg
        self.source = source
        self.state = state
        self.notifier = notifier
        _BUSY_SEEN.update(state_dir=cfg.state_dir, automas_dir=cfg.automas_dir)
        # Hook for the last pull of pending orders before powering off, wired up by
        # service (see _maybe_shutdown). None when running tests standalone, and then
        # nothing is pulled.
        self._before_shutdown = None
        # Hook for sending the phone page a fresh state snapshot, wired up by
        # boot_stages._start_phone_channel. Called after a skip step says
        # something, so its receipt shows without waiting for the next refresh.
        self._push_state = None
        # Hook that applies the phone orders queued while a script ran
        # (boot_stages._make_phone_cmd drain). None in standalone tests.
        self._phone_drain = None
        # runwatch: AUTO-MAS's app.log, read incrementally, and the first-timeout
        # alarms that could not be sent yet (the log line is read only once).
        self._applog = None
        self._unsent_timeouts: list = []
        # 「没干完」 alarms (unresolved.py) whose push failed: (day, key, title, body),
        # tried again at the top of every _flush_pending.
        self._unsent_unresolved: list = []
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
        from ark_relay.features.weekly.annihilation import WeeklyGate  # noqa: PLC0415 - optional feature
        self._annihilation = WeeklyGate(state.dir, cfg.automas_dir)
        # The weekly garden and annihilation are the same shape of problem: something
        # that only needs doing once a week should not be visited every day. The only
        # difference is which switch gets turned off - annihilation's is MAA's, this
        # one's is OK-WW's "Check Weekly Garden" additional task.
        from ark_relay.features.weekly.garden import GardenGate  # noqa: PLC0415 - optional feature
        # Since 2026-08-28 this writes the master copy directly instead of going
        # through the MAS API - that path requires quick-config to be on, and
        # quick-config has been abandoned.
        self._garden = GardenGate(state.dir, cfg.automas_dir)
        from ark_relay.features.weekly.weeklyboss import WeeklyBossGate  # noqa: PLC0415 - avoid import cycle
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
        # This guard alone is not enough: with no script running AUTO-MAS can
        # still be up and ignore a file edit (2026-09-30 09:00), which is why
        # queues.apply goes through the backend API whenever it answers.
        if self._scripts_running():
            return
        fresh = False
        try:
            for msg in modes.process_skip(self.state.dir, self.cfg.automas_dir):
                log.info("⏭️ %s", msg)
                # A *persistent* failure (queue renamed while a restore marker
                # is pending) returns the identical message on every tick, and
                # ticks fire on every directory event - dedup per process, or
                # the operator gets the same push dozens of times a boot.
                # one fault, one push: one skip / restore that did not take, the identical words returned again every tick
                if msg not in self._mode_notified:
                    self._mode_notified.add(msg)
                    fresh = True
                    if not skip_failed(self.state.dir, msg):
                        self.notifier.send(texts.SKIP_MODE, msg)     # an acknowledgement: log route
                    elif errs := self.notifier.send(SKIP_FAILED, msg, alert=True):
                        # Not out: errwatch pushes this line (kept on disk until the
                        # group takes it), and a failure said again next tick is pushed again.
                        self._mode_notified.discard(msg)
                        log.warning("%s：%s（报警没推出去：%s）", SKIP_FAILED, msg, "；".join(errs))
        except Exception:
            log.exception("跳过模式处理出错")
        if fresh and self._push_state is not None:
            try:
                self._push_state("跳过队列")
            except Exception:
                log.exception("跳过队列后状态没能上报到手机")
        active = modes.debug_active(self.state.dir)
        if active != self._debug_last:
            if active:
                log.info("🔧 调试模式生效（至 %s）：这一轮跑完不关机",
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
        from ark_relay.core.transport import payload_to_record  # noqa: PLC0415 - avoid cycle
        data = self.state.load_pending()
        dropped = []
        for bucket, target in (("pending", self._pending), ("recovered", self._recovered)):
            for item in data.get(bucket, []):
                try:
                    rec = payload_to_record(item)
                except (KeyError, ValueError, TypeError):
                    # Boot-only path: say it directly, or an alarm held across the
                    # restart vanishes with no trace.
                    got = item if isinstance(item, dict) else {}
                    dropped.append(" ".join(str(got.get(k) or "") for k in ("script", "run_id")).strip()
                                   or "（认不出是哪条）")
                    continue
                target[(rec.script, rec.user)] = rec
        if dropped:
            log.warning("磁盘上有 %d 条未送达的告警恢复不出来，已丢弃：%s",
                        len(dropped), "；".join(dropped))
        if self._pending or self._recovered:
            log.info("从磁盘恢复了 %d 条未送达的告警",
                     len(self._pending) + len(self._recovered))

    def _persist_pending(self) -> None:
        from ark_relay.core.transport import record_to_payload  # noqa: PLC0415 - avoid cycle
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
        # Phone orders that waited for the run to end go first: a queued skip is
        # then engaged by _observe_modes below, and a queued 「现在跑」 or setting
        # is in place before this tick's shutdown decision.
        if self._phone_drain is not None:
            try:
                self._phone_drain()
            except Exception:
                log.exception("排队的手机指令没执行完，下一轮再试")
        try:
            self._observe_modes()
        except Exception:
            log.exception("读模式开关出错，本轮按「没开任何模式」继续")
        try:
            records = self.source.fetch(self.state.seen)
        except Exception:
            log.exception("读取运行记录失败，本轮按没有新记录处理")
            records = []
        landed = False
        for rec in records:
            try:
                self._handle(rec)
            except Exception:
                log.exception("处理运行记录失败: %s", rec.run_id)
                continue
            self.state.mark_seen(rec.run_id)
            self._handled_any = landed = True
        if landed:
            # On disk too: a restart on the same boot (a deploy) still knows it saw them land.
            shutdown.note_handled(self, datetime.now(tz=SERVER_TZ))
        # Every step is caught on its own; a broken one must not take the rest with
        # it. On 2026-09-04 a single ImportError in the "tomorrow's schedule" step
        # carried off the deferred update, the daily report and the auto shutdown
        # behind it, and the machine stayed powered up all morning with nobody
        # noticing - shutdown and the daily report are the last two steps, exactly the
        # ones that must not be killed off by an earlier one.
        for what, step in (
            ("刷声骸到点收工", self._echo_farm_deadline),
            ("OK-WW 补丁", self._patch_okww_if_updated),
            ("在跑巡查", self._run_watch),
            ("推送积压告警", self._flush_pending),
            ("剿灭开关", self._enforce_annihilation),
            ("周常门", self._weekly_gates),
            ("月卡提醒", self._monthcard_notice),
            # Before the missed-run check and the shutdown decision: both read what
            # the stage gate pulled (stagegate.excused / recent_pulled).
            ("关卡门", self._stage_gate),
            ("漏跑检查", self._check_missed_runs),
            # Before both reports and the shutdown decision: a held MAA / MaaEnd
            # failure gets its one make-up run first (makeup.py), and the reports
            # wait for it instead of describing the day without it.
            ("补跑", self._maybe_makeup),
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
        from ark_relay.features.echofarm import echofarm  # noqa: PLC0415
        note = echofarm.tick(self.cfg)
        if note:
            log.info("刷声骸：%s", note)
            self.notifier.send(texts.ECHO_FARM_DONE, note)

    def _patch_okww_if_updated(self) -> None:
        """Re-apply the patches if OK-WW updated itself; leave it alone while a script runs."""
        if self._scripts_running():
            return
        from ark_relay.features.okww_patch import okww_patch  # noqa: PLC0415
        okww = self.cfg.okww_dir or (
            Path(self.cfg.automas_dir).parent / "okww" if self.cfg.automas_dir else None)
        notes = okww_patch.ensure_if_updated(self.state.dir, okww)
        for n in notes:
            log.info("补丁：%s", n)
        if notes:
            # alert=True: 「⚠️ OK-WW 补丁有 N 条没贴上」 goes to the group, each time (until
            # 2026-10-06 Server酱 only); the healthy 「🩹 OK-WW 补丁」 stays log-only (notify.route_of).
            self.notifier.send(texts.patches(len(notes), notes),
                               "\n".join(f"· {n}" for n in notes), alert=True)

    def _monthcard_notice(self) -> None:
        """From five days before a monthly card's last claim day, one Server酱 line a day."""
        from ark_relay.features.phone import monthcard  # noqa: PLC0415
        due = monthcard.due_notice(self.state.dir)
        if due and not self.notifier.send(*due):
            monthcard.mark_sent(self.state.dir)

    def _stage_gate(self, now: datetime | None = None, lead_min: int | None = None) -> None:
        """Before each MAA due: pull MAA from that queue run when its stage cannot be
        navigated to; put it back afterwards (stagegate.py). Local files only.
        lead_min: the boot pass looks further ahead (stagegate.BOOT_LEAD_MIN)."""
        from ark_relay.features.schedule import stagegate  # noqa: PLC0415
        stagegate.step(self.cfg, self.notifier, now, busy=self._scripts_running,
                       lead_min=lead_min or stagegate.LEAD_MIN)

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
        from ark_relay.features.gameupdate import gameupdate  # noqa: PLC0415
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

        games = "、".join(gameupdate.pending(self.state.dir))

        def work() -> None:
            from ark_relay.features.phone import commands  # noqa: PLC0415
            try:
                def _dispatch(name: str):
                    self._gu_rerun_at = datetime.now(tz=SERVER_TZ)
                    return commands.run_script(name)
                try:
                    notes, problems, reran = gameupdate.run_deferred(
                        self.cfg, now=now, dispatch=_dispatch)
                finally:
                    # Every screen the update read (gameupdate.last_trace): the
                    # machine checks #60-#62 judge from it.
                    self._machinecheck("gameupdate", {"game": games, "screens": gameupdate.last_trace()})
                for n in notes:
                    self.notifier.send(texts.GAME_UPDATE, n)
                if reran:
                    self.notifier.send(texts.RERUN_AFTER_UPDATE, texts.rerun_body(reran))
                if problems:
                    # A group alarm, each time (until 2026-10-06 demoted to Server酱 by notify.route_of).
                    self.notifier.send(texts.unconfirmed("游戏更新", len(problems)),
                                       "\n".join(f"· {x}" for x in problems), alert=True)
            except Exception:
                log.exception("游戏更新（队列后）出错")

        self._gu_thread = threading.Thread(target=work, name="game-update", daemon=True)
        self._gu_thread.start()
        log.info("游戏更新：队列已跑完，后台开始更新 %s", "、".join(gameupdate.pending(self.state.dir)))

    def _machinecheck(self, event: str, ctx: dict) -> None:
        """Hand one event to the machine checks (machinecheck.py). Never raises: a
        broken check must not break the relay's own path (judge logs it as ERROR)."""
        if not getattr(self.cfg, "state_dir", None):
            return
        try:
            from ark_relay.features.selfcheck import machinecheck  # noqa: PLC0415
            from ark_relay.core.statestore import StateStore  # noqa: PLC0415
            machinecheck.judge(self.cfg.state_dir, event, ctx, notifier=self.notifier,
                               version=str(StateStore(self.cfg.state_dir).get("versions", "code") or ""))
        except Exception:
            log.exception("上机核对（%s）自己出错，这一步照常", event)

    # ---------- decide held-back failures ----------

    def scripts_running(self) -> bool:
        """Public view of the same check the shutdown path uses.

        The service needs it to decide when a config edit is safe: AUTO-MAS
        reads its config as it launches each script, so writing during a run
        would land somewhere between two scripts and take effect for only half
        the queue.
        """
        return self._scripts_running()

    def _script_running(self, name: str) -> bool:
        """Is this one script still running or waiting its turn in AUTO-MAS?

        Asks runtime-snapshot for that script alone. When AUTO-MAS cannot be
        asked, falls back to the queue-wide `_scripts_running` - waiting too long
        beats alarming on a script that is still retrying.
        """
        if os.name != "nt":
            return False
        snap = _automas_snapshot()
        if snap is None:
            return self._scripts_running()
        return _script_unfinished(snap, name)

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
        from ark_relay.features.echofarm import echofarm  # noqa: PLC0415
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

        # A queue that runs is only visible through AUTO-MAS's own log and snapshot,
        # neither of which wakes the loop; see runwatch for 2026-10-01.
        try:
            from ark_relay.features.run import runwatch  # noqa: PLC0415
            cands.extend(runwatch.next_moments(self, now, self._scripts_running()))
        except Exception:
            log.exception("算在跑巡查的时刻出错，跳过")

        # The shutdown floor (shutdown.py: 「开机不够久」 until _started_at +
        # shutdown_min_uptime) is a moment too. Unregistered, a relay restarted at
        # 2026-10-01 18:03:57 judged 「开机不够久」 once and then slept until the
        # 21:30 alarm: nothing looked again when the floor passed at 18:13:57.
        if self.cfg.shutdown_after_run:
            floor = self._started_at + timedelta(seconds=self.cfg.shutdown_min_uptime)
            if floor > now:
                cands.append((floor, "开机满下限，重新判一次关机"))

        # A make-up dispatch that did not take is tried again after a gap, and one
        # that never produced a record is closed out after a while; both are
        # moments nothing else wakes the loop for.
        try:
            from ark_relay.features.makeup import makeup  # noqa: PLC0415
            if moment := makeup.next_moment(self.cfg.state_dir, now):
                cands.append(moment)
        except Exception:
            log.exception("算补跑的时刻出错，跳过")

        if not self.state.report_sent(now.strftime("%Y-%m-%d")):
            cutoff = self._report_cutoff(now)
            if cutoff > now:
                cands.append((cutoff, "日报截止"))

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

    def _maybe_makeup(self, now: datetime | None = None) -> bool:
        from ark_relay.features.makeup import makeup  # noqa: PLC0415
        return makeup.maybe_run(self, now)

    def _run_watch(self, now: datetime | None = None) -> None:
        """First timeout of each script, and a shift running past its planned end (runwatch)."""
        from ark_relay.features.run import runwatch  # noqa: PLC0415
        now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
        if self._applog is None:
            self._applog = runwatch.AppLog(runwatch.applog_path(self.cfg.automas_dir))
        events = self._unsent_timeouts + self._applog.poll()
        self._unsent_timeouts = runwatch.check_timeouts(self, events, now)
        if os.name == "nt":
            runwatch.check_overrun(self, now, _automas_snapshot())

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
    def _boot_time(self, now: datetime | None = None) -> datetime | None:
        return shutdown._boot_time(self, now)

    def _recent_entries(self, now: datetime) -> list[dict]:
        return shutdown._recent_entries(self, now)

    def _unfinished_queues(self, now: datetime, entries: list[dict]) -> list[str]:
        return shutdown._unfinished_queues(self, now, entries)

    def _round_is_manual(self, new_entries: list[dict]) -> bool:
        return shutdown._round_is_manual(self, new_entries)

    def _last_round_manual(self, now: datetime, entries: list[dict]) -> bool:
        return shutdown._last_round_manual(self, now, entries)

    def _shutdown_key(self, now: datetime) -> str:
        return shutdown._shutdown_key(self, now)

    def _maybe_shutdown(self, now: datetime | None = None) -> bool:
        return shutdown._maybe_shutdown(self, now)

    def _power_off(self) -> bool:
        """Issue the actual shutdown command. It lives here so tests can swap out subprocess.

        True only when Windows accepted the command (exit code 0). A refusal -
        1190 "a shutdown is already scheduled", no privilege - used to return
        True as well, and the caller then marked the machine as going down while
        it stayed on. False sends the caller (shutdown._maybe_shutdown) back to
        deciding on the next tick, and the ERROR line is the alarm (errwatch).
        The 「60 秒后关机」 line is written only after the command was accepted:
        machine checks #37/#38 (machinechecks/system.py POWER_OFF) read it as
        proof the relay powered the machine off.
        """
        # /d p:4:1 records the power-off as planned ("Application: Maintenance
        # (Planned)" in the reason table of the shutdown docs). Without /d, the
        # same page says, "If p or u aren't specified, the restart or shutdown
        # is unplanned." - and every routine power-off was logged as unplanned,
        # indistinguishable from a real power cut.
        # https://learn.microsoft.com/windows-server/administration/windows-commands/shutdown
        try:
            r = subprocess.run(["shutdown", "/s", "/t", "60", "/d", "p:4:1",
                                "/c", "ark-relay: run complete"],
                               capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            log.exception("关机命令执行失败")
            return False
        if r.returncode != 0:
            # shutdown.exe prints in the console codepage (GBK on the machine).
            said = b" ".join(x for x in (r.stderr or b"", r.stdout or b"") if x.strip())
            log.error("关机命令被 Windows 拒绝（退出码 %s）：%s，这次没关机，下一轮再判",
                      r.returncode, said.decode("gbk", errors="replace").strip() or "没有输出")
            return False
        log.info("本轮已处理完毕，60 秒后关机")
        return True

    def _abort_power_off(self) -> int:
        """Run `shutdown /a` and return its exit code (-1 when it could not run).

        0 = the countdown _power_off started was cancelled; 1116
        (ERROR_NO_SHUTDOWN_IN_PROGRESS) = there was no countdown to cancel.
        """
        try:
            r = subprocess.run(["shutdown", "/a"], capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            log.exception("取消关机命令执行失败")
            return -1
        return r.returncode
