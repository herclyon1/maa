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

from . import handle, missed, modes, plan, report, shutdown
from .config import SERVER_TZ, Config, RunRecord
from .core import State
from .missed import MISSED_GRACE_MIN
from .shutdown import CHECK_OPEN_MIN
from .notify import Notifier
from .transport import Source

log = logging.getLogger("ark.engine")
# `_scripts_running` 的短缓存，见那个方法的注释。
_SCRIPTS_CACHE: dict = {"at": -1e9, "val": False}
_SCRIPTS_TTL = 3.0


class Engine:
    def __init__(self, cfg: Config, source: Source, state: State, notifier: Notifier):
        self.cfg = cfg
        self.source = source
        self.state = state
        self.notifier = notifier
        # 关机前最后拉一次待办用的钩子，由 service 接上（见 _maybe_shutdown）。
        # 单机跑测试时是 None，那就不拉。
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
        # 周常乐园和剿灭是同一个形状的问题：一周只需要做一次的事，
        # 别每天都跑去看一眼。区别只在剿灭关的是 MAA 的开关、
        # 这个关的是 OK-WW 的「Check Weekly Garden」附加任务。
        from .garden import GardenGate     # noqa: PLC0415 - optional feature
        # 2026-08-28 起直接写母本，不再走 MAS 的接口——那条路要求快速配置
        # 开着，而快速配置已经废掉了。
        self._garden = GardenGate(state.dir, cfg.automas_dir)
        from .weeklyboss import WeeklyBossGate  # noqa: PLC0415 - 避免导入环
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
                # 用户 2026-09-02 定的：调试模式是「跳过这一次跑完后的关机」
                # 的一次性开关，关掉它**不会**有人再去执行那条关机——机器就
                # 开到下一趟队列跑完为止。这是默认设计，别在这里补关。
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
        try:
            records = self.source.fetch(self.state.seen)
        except Exception:  # noqa: BLE001 - 读不到记录，时钟类的事照做
            log.exception("读取运行记录失败，本轮按没有新记录处理")
            records = []
        for rec in records:
            try:
                self._handle(rec)
            except Exception:  # noqa: BLE001 - one bad record must not stop the loop
                log.exception("处理运行记录失败: %s", rec.run_id)
                continue
            self.state.mark_seen(rec.run_id)
            self._handled_any = True
        # 每一段各自兜住，一段坏了不许连累后面的。2026-09-04 「明日安排」那段
        # 一个 ImportError 把它后面的补更新、日报、自动关机全带走，机器白开
        # 一上午没人发现——关机和日报是最后两段，恰恰最不该被前面的段拖死。
        for what, step in (
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
            except Exception:  # noqa: BLE001 - 这一段坏了，下一段照跑
                log.exception("本轮「%s」这一段出错，跳过它继续", what)
        return len(records)

    def _weekly_gates(self) -> None:
        try:
            self._garden.enforce()
            self._weeklyboss.enforce()
        except Exception:  # noqa: BLE001 - 一道省时间的门，不许拖垮主流程
            log.warning("周常乐园开关没能落盘，下轮再试", exc_info=True)

    # ---------- 队列跑完之后再更新游戏客户端 ----------

    def _deferred_update_busy(self) -> bool:
        t = getattr(self, "_gu_thread", None)
        return bool(t is not None and t.is_alive())

    def _maybe_deferred_update(self) -> None:
        """有登记、队列都跑完了、没脚本在跑 → 起后台线程去更新再重跑。

        用户 2026-09-02 定的顺序：先让别的游戏跑完，再单独更新、单独重跑。
        线程活着期间 _maybe_shutdown 不关机；重跑本身是 AUTO-MAS 派发的
        脚本，跑起来之后照常由 _scripts_running 挡住关机。一天最多起一次。
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
            # 只在原因变化时写一行，免得每 30 秒刷屏
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
                    self.notifier.send("🆕 游戏更新", n)
                if reran:
                    self.notifier.send("🔁 更新后重跑", "、".join(reran) + " 已单独开跑")
                if problems:
                    self.notifier.send(f"⚠️ 游戏更新没能确认（{len(problems)} 项）",
                                       "\n".join(f"· {x}" for x in problems))
            except Exception:  # noqa: BLE001
                log.exception("游戏更新（队列后）出错")

        self._gu_thread = threading.Thread(target=work, name="game-update", daemon=True)
        self._gu_thread.start()
        log.info("游戏更新：队列已跑完，后台开始更新 %s", "、".join(gameupdate.pending(self.state.dir)))

    # MaaEnd 里这几项失败是上游/游戏本身的问题，不是要人半夜处理的故障：
    #   应急理智加强剂：beta.5 在「选择加强剂」那步坏了（09-03 实录，已关掉等上游）
    #   自动采集：15 条路线里总有两三条「采集失败」，任务整体就报失败，其余都采了
    # 用户 2026-09-03：「今天下午或者明天再报错你就滚」——这类只进日报，不推 ⚠️。
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
        """True while any managed script is still working.

        A failure is only worth reporting once nothing is still trying. This is
        deliberately a process check rather than a timer: a retry run can take
        20+ minutes, so any fixed grace period would either fire early or delay
        real alerts past usefulness.
        """
        if os.name != "nt":
            return False
        # 一轮 tick 里这个判断要问十来次（跳过模式、积压告警、漏跑、临时查看、
        # 日报、关机……各问一遍），每问一次起一个 tasklist，慢的时候一次一两秒。
        # 三秒内的答案直接复用：进程列表三秒内不会变出一个新游戏来。
        now = time.monotonic()
        if now - _SCRIPTS_CACHE["at"] < _SCRIPTS_TTL:
            return _SCRIPTS_CACHE["val"]
        try:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                                 capture_output=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            val = True  # cannot tell -> wait rather than cry wolf
        else:
            # Endfield.exe is on this list because MaaEnd has NO process of its
            # own - AUTO-MAS's python drives it in-process (verified 2026-08-20:
            # during a MaaEnd run tasklist shows only the game). Watching for
            # "MaaEnd.exe" alone made this check blind through the entire 终末地
            # phase; the game binary is the only visible sign that phase is live.
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
        except Exception:  # noqa: BLE001 - a failed fix must not break the tick
            log.exception("剿灭开关校正出错")

    # ---------- 记账与告警（handle.py） ----------
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

    # ---------- 漏跑与缺项（missed.py） ----------
    def _check_missed_runs(self, now: datetime | None = None,
                           grace_min: int = MISSED_GRACE_MIN) -> None:
        return missed._check_missed_runs(self, now, grace_min)

    def _check_partial_queues(self, now: datetime, day: str,
                              entries: list[dict]) -> None:
        return missed._check_partial_queues(self, now, day, entries)

    # ---------- 日报与临时查看（report.py） ----------
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

    # ---------- 关机判定（shutdown.py） ----------
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
        """真正下关机命令。留在这里是为了测试能替换掉 subprocess。"""
        log.info("本轮已处理完毕，60 秒后关机")
        try:
            subprocess.run(["shutdown", "/s", "/t", "60",
                            "/c", "ark-relay: run complete"], timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            log.exception("关机命令执行失败")
            return False
        return True
