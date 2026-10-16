"""Facts handle.py reads about one run record, and marks it writes on the
record and its ledger line before deciding what to push.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core import texts
from ark_relay.core import collector, ledger as core, summary
from ark_relay.features.maintenance import efstatus
from ark_relay.core.config import SERVER_TZ, RunRecord

# Same logger as handle.py: relay.log names these lines "ark.handle".
log = logging.getLogger("ark.handle")


def run_day(rec: RunRecord) -> str:
    """The server-time day (YYYY-MM-DD) the run started on: its ledger file."""
    return rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")


def _append_ledger_once(eng, rec: RunRecord) -> None:
    """Append this run to the day's ledger, without double-counting a replayed record.

    Its own step because bookkeeping has to be idempotent, while the judging and
    pushing below it can fail midway and send the whole record through from the
    start again - fenced off as one step, a replay simply skips it.
    """
    # mark_seen only happens after _handle returns, so a crash later in
    # handling replays the record on every retry tick; appending it again
    # would inflate the daily report and the "重试 N 次" counts.
    day = run_day(rec)
    if any(e.get("run_id") == rec.run_id for e in eng.state.read_ledger(day)):
        log.info("记录 %s 已在账上（上次处理中途出错的重试），跳过重记", rec.run_id)
    else:
        eng.state.append_ledger(rec)


def _same_shift(eng, a: RunRecord, b: RunRecord) -> bool:
    from ark_relay.features.alarm import unresolved  # noqa: PLC0415
    try:
        return unresolved.where(eng, a) == unresolved.where(eng, b)
    except Exception:  # not knowing keeps the held record on its usual path
        log.warning("分不清 %s 和 %s 是不是同一班，按原样处理", a.run_id, b.run_id, exc_info=True)
        return False


def _estop_overlap(eng, rec: RunRecord) -> str:
    """「HH:MM 停一切」 when this run overlaps a press of the red button, else ''.

    AUTO-MAS can record a run the button stopped as Success!; without this mark
    it would read as the retry that healed an earlier failure.
    """
    try:
        from ark_relay.features.phone import commands  # noqa: PLC0415
        return commands.estop_label(commands.estop_windows(eng.cfg.state_dir),
                                    rec.started, rec.finished)
    except Exception:
        log.exception("红按钮时间对不上（按正常记录处理）")
    return ""


def _mark_update_restart(eng, rec: RunRecord) -> None:
    """A MaaEnd attempt spent on installing its own update is not a game failure.

    Marked before the ledger line is written, so the daily report reads it as an
    update episode. It is still held like a failure: if no later attempt gets
    through, the final alarm says the last retry went on the update.
    """
    # Only a run attempt: AUTO-MAS's own failed update step (collector,
    # raw['automas_update_step']) sits in the same MXU install window but is no run.
    if rec.script != "MaaEnd" or rec.ok or rec.transitional or (rec.raw or {}).get("automas_update_step"):
        return
    try:
        from ark_relay.features.verify.collector_maaend import update_restart_version  # noqa: PLC0415
        version = update_restart_version(eng.cfg.maaend_dir, rec.started)
    except Exception:
        log.exception("核对 MaaEnd 是否在装更新时出错，按原样处理")
        return
    if not version:
        return
    rec.raw["maaend_update_restart"] = version
    rec.raw["automas_failed_tasks"] = list(rec.failed_tasks)
    rec.failed_tasks = [f"MaaEnd 装新版 {version} 后自己重启，这一次重试被用掉"]
    rec.transitional = True


# A task-end picture belongs to a task when it was taken this close after the
# task's 「任务完成」 (the picture lands a few seconds after the maafw event,
# task_shots.py); the launch's first-start picture of a longer task is earlier.
SHOT_BEFORE_S, SHOT_AFTER_S = 5, 120


def _mark_task_shots(eng, rec: RunRecord) -> None:
    """raw['tasks_shot']: the MaaEnd tasks of this run with a task-end picture
    (task_shots.py). Game evidence for core.maaend_unverified only on records booked
    before raw['tasks_trail'] (_mark_task_trails): the picture shows the next task. A
    key of its own, so collector.refresh_raw (which re-parses only the log) never drops it.
    raw['tasks_shot_files']: {task: that picture, relative to the state folder},
    the evidence a machine check names (machinechecks/runs.py)."""
    try:
        from ark_relay.features.verify import collector_maaend  # noqa: PLC0415
        from ark_relay.features.evidence import task_shots  # noqa: PLC0415
        log_path = rec.log_path
        if not log_path or not Path(log_path).is_file():
            return
        times = collector_maaend.task_times(Path(log_path).read_text(encoding="utf-8", errors="replace"))
        shots: list[tuple[str, datetime, Path]] = []
        end = rec.finished if rec.finished else datetime.now().astimezone()
        for p in task_shots.in_window(eng.cfg.state_dir, (rec.started.timestamp(),
                                                          end.timestamp() + SHOT_AFTER_S)):
            stamp, _, label = p.stem.partition("-")
            try:
                at = datetime.strptime(f"{p.parent.parent.name} {stamp}", "%Y-%m-%d %H%M%S")
            except ValueError:
                continue
            shots.append((label, at, p))
        files: dict[str, str] = {}
        for t, (_, fin) in times.items():
            for label, at, p in shots:
                if (label == task_shots.plain_name(t)
                        and -SHOT_BEFORE_S <= (at - fin).total_seconds() <= SHOT_AFTER_S):
                    files[t] = _state_relative(eng.cfg.state_dir, p)
                    break
        if files:
            rec.raw["tasks_shot"] = list(files)
            rec.raw["tasks_shot_files"] = files
    except Exception:
        log.warning("核对任务截图出错（这一趟的任务按日志里的证据算）", exc_info=True)


def _mark_task_trails(eng, rec: RunRecord) -> None:
    """raw['tasks_trail']: {task: maaend_fwlog.trail_entry} for each of
    maaend_fwlog.TRAIL_TASKS this run finished (its 「任务完成」, not a weekday skip):
    whether MaaFW's log holds its run, and whether its steps show the job done or
    nothing to do (maaend_fwlog.task_verdict). It is the game evidence of those tasks
    for core.maaend_unverified, and machine check #28 reads its verdict from here
    (machinechecks/runs.py) instead of reading MaaFW's log again; the desktop picture
    (_mark_task_shots) is no evidence, since it is taken 5-8 s after the task ended and
    shows the next one (task_shots.py).

    raw['tasks_trail_miss']: when none of those tasks is in MaaFW's log (the folder is
    not configured, MaaEnd cleared it at a restart, a file could not be read), how many
    MaaEnd runs in a row that is, this one included (_trail_miss_streak); 0 otherwise.
    Below maaend_fwlog.TRAIL_MISS_FAIL those tasks are left unjudged - said at INFO
    and in the daily report (core.maaend_unjudged), not pushed - as #28 does.

    Booked here, while MaaFW's log still holds the run: MaaEnd clears its debug folder
    when it restarts. Keys of their own, so collector.refresh_raw keeps them. Always
    set on a MaaEnd record ({} when the run did none of the four), which tells
    maaend_unverified the record was booked under this rule."""
    trails: dict = {}
    rec.raw["tasks_trail"] = trails
    rec.raw["tasks_trail_miss"] = 0
    try:
        from ark_relay.features.verify import collector_maaend, maaend_fwlog  # noqa: PLC0415
        log_path = rec.log_path
        if not log_path or not Path(log_path).is_file():
            return
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        times = collector_maaend.task_times(text)
        done = set(rec.raw.get("tasks_done") or [])
        skipped = rec.raw.get("maaend_tasks_skipped") or {}
        times = {t: v for t, v in times.items() if t in done and t not in skipped}
        table, why = maaend_fwlog.trail_table(getattr(eng.cfg, "maaend_dir", None), times, text)
        trails.update(table)
        if not why:
            return
        miss = _trail_miss_streak(eng, rec)
        rec.raw["tasks_trail_miss"] = miss
        log.info("%s：%s 在终末地自己的记录里都找不到（%s），连续第 %d 趟；%s", rec.run_id, "、".join(table), why,
                 miss, "到了次数，按没证据算" if miss >= maaend_fwlog.TRAIL_MISS_FAIL else "这一趟先不判，写进日报")
    except Exception:
        log.warning("没读成终末地自己的任务记录（这一趟的四个任务只按日志里的行算）", exc_info=True)


def _trail_miss_streak(eng, rec: RunRecord) -> int:
    """1 + the tasks_trail_miss of the MaaEnd run booked last before this one (today's
    and yesterday's ledger) among those that asked MaaFW's log about any of the four
    tasks; 1 when that run found them or there is none. Read from the ledger, so a
    record handled again (handle._append_ledger_once) does not count twice."""
    try:
        day = datetime.strptime(run_day(rec), "%Y-%m-%d")
        rows = [*eng.state.read_ledger((day - timedelta(days=1)).strftime("%Y-%m-%d")),
                *eng.state.read_ledger(run_day(rec))]
        before = sorted((e for e in rows if e.get("script") == "MaaEnd" and e.get("run_id") != rec.run_id
                         and (e.get("started") or "") < rec.started.isoformat()
                         and (e.get("raw") or {}).get("tasks_trail")),
                        key=lambda e: e.get("started") or "")
    except Exception:  # no history: this run counts as the first in a row
        log.info("读不到前几趟的账，这一趟按连续第 1 趟算", exc_info=True)
        return 1
    if not before:
        return 1
    return int((before[-1].get("raw") or {}).get("tasks_trail_miss") or 0) + 1


def _state_relative(state_dir, p: Path) -> str:
    """`p` as written under the state folder (shots/<day>/...), or the whole path when it is elsewhere."""
    try:
        return Path(p).relative_to(Path(state_dir)).as_posix()
    except ValueError:
        return str(p)


def _restore_after_maaend(eng) -> None:
    """A MaaEnd record has landed: put back what a retry or a make-up narrowed."""
    # A MaaEnd record ending means AUTO-MAS's retry round (if any) is over:
    # whatever narrowing was done for it must go back before anything else.
    try:
        from ark_relay.features.makeup import collect_retry  # noqa: PLC0415
        if back := collect_retry.restore_master(eng.cfg):
            log.info("🔁 %s", back)
    except Exception:
        log.exception("母本路线改回出错")
    # Same for the make-up's narrowing (makeup.py): AUTO-MAS writes a
    # script's records once all its attempts are over, so the make-up run
    # and its own retries are done by now.
    try:
        from ark_relay.features.makeup import makeup  # noqa: PLC0415
        back, err = makeup.try_restore(eng.cfg, eng.notifier)
        if back:
            log.info("🔁 %s", back)
        elif err:
            # A failure, so it reaches the group (errwatch pushes every
            # WARNING). makeup's own alarm (both files unreadable) may say
            # the same; try_restore does not tell whether it sent one, so this
            # line is not held back on a guess.
            log.warning("补跑的母本没能改回（%s）", err)
    except Exception:
        log.exception("补跑的母本改回出错")


def _check_d3d11_after_maaend() -> None:
    """A MaaEnd record has landed: did AUTO-MAS's launcher start run the game on Direct3D 11?
    AUTO-MAS never ticks 「DirectX 11 启动」 (efstart_setup.check_d3d11 reads Player.log)."""
    try:
        from ark_relay.features.gameupdate import efstart_setup  # noqa: PLC0415
        efstart_setup.check_d3d11()
    except Exception:
        log.exception("核对终末地是不是用 DirectX 11 开的出错")


def _confirm_unreachable(eng, rec: RunRecord) -> None:
    """A MaaEnd failure shaped like "never got into the game" is that only when
    there is evidence the game itself was unavailable.

    `maaend_unreachable` skips the alarm (_flush_pending), the make-up
    (makeup.eligible), and registers a client update plus a re-run after the
    queue (gameupdate.mark_pending -> run_deferred kills the game, opens the
    launcher and re-dispatches MaaEnd via needs_rerun). The log's shape alone
    (collector_maaend.maaend_unreachable) is also what a lost game window or a
    crash at the title screen looks like, so it is set only on an official
    maintenance window (gameupdate.in_maintenance) or an official update notice
    for today (efstatus.update_hint). Without either the run is an ordinary
    failure: held, made up, and alarmed on like any other; the shape stays in
    `maaend_unreachable_shape` for the alarm text. Runs before the ledger line
    is written so the daily report reads the same verdict.
    """
    raw = rec.raw   # RunRecord.raw defaults to a dict
    shape = raw.pop("maaend_unreachable", None) or raw.get("maaend_unreachable_shape")
    if rec.script != "MaaEnd" or rec.ok or not shape:
        return
    if raw.get("maaend_update_restart"):
        # Every task failing at once is what MaaEnd restarting into its new build
        # looks like (MXU's own log proves the install, _mark_update_restart). Not a
        # fault to warn about - the WARNING below reaches the group (errwatch) and
        # said 「报警、补跑」 about an attempt that is let go when its shift is done -
        # and not the alarm note 「看着像没进游戏」 either.
        raw.pop("maaend_unreachable_shape", None)
        log.info("MaaEnd %s 每个任务秒败，是装新版 %s 后自己重启造成的，不按没进游戏算",
                 rec.run_id, raw["maaend_update_restart"])
        return
    raw["maaend_unreachable_shape"] = True
    why = ""
    # Unknown is not evidence, but it is not "no notice" either (audit 2026-10-13
    # s1 #3): `maaend_unreachable_unread` lets the alarm say the notices could not
    # be read (texts.UNREACHABLE_UNREAD_NOTE) instead of 「今天没有官方…公告」.
    unread = False
    try:
        from ark_relay.features.gameupdate import gameupdate  # noqa: PLC0415
        why = gameupdate.in_maintenance(eng.cfg.state_dir, rec.script, rec.started)
    except Exception:  # logged with the traceback
        log.warning("查不了维护窗口，%s 按普通失败处理", rec.run_id, exc_info=True)
        unread = True
    if not why:
        try:
            why = efstatus.update_hint(rec.started, strict=True)
        except Exception:  # the alarm says the notice was not read
            log.info("终末地更新公告没读到，%s 按普通失败处理", rec.run_id, exc_info=True)
            unread = True
    if unread and not why:
        raw["maaend_unreachable_unread"] = True
    if why:
        raw["maaend_unreachable"] = True
        raw["maaend_unreachable_why"] = why
        log.info("⏸ MaaEnd %s 每个任务秒败、零完成，且有官方依据（%s）：按进不了游戏处理", rec.run_id, why)
    else:
        # INFO, not WARNING (audit 2026-10-13 s7 #5): errwatch pushed the WARNING at
        # once as 「中继自己报错了」 while the failure was still held for its retry - a
        # game failure under the relay-error title, before a retry that may heal it.
        # The held final alarm says it (pushes._push_unresolved: UNREACHABLE_SHAPE_NOTE).
        log.info("❌ MaaEnd %s 每个任务秒败、零完成，像没进游戏，但没有官方维护或更新公告："
                 "按普通失败处理（报警、补跑）", rec.run_id)


def _mark_raw_on_ledger(eng, rec: RunRecord, key: str, value) -> None:
    """A raw field learned after the run's ledger line was written goes onto that line."""
    day = run_day(rec)
    if not eng.state.mark_raw(day, rec.run_id, key, value):
        log.warning("没能把 %s 写回 %s 的账本", key, rec.run_id)


def _attempts(eng, rec: RunRecord, day: str) -> int:
    """How many tries the failed streak `rec` belongs to took: the failed rows of the
    same script and user in `rec`'s shift since the last row that exited normally,
    plus the success that healed it when there is one (「跑了 N 次」).

    Not the whole day (audit 2026-10-13 s7 #4 / s1 #1): the morning's successes,
    the other shift and a person's own runs inflated 「重试 N 次全部失败」 (10-10's
    rows gave 5 for an evening failure). Rows a person started (hand_started) or
    the red button cut short (manual_stop) are not this streak's tries; stubs
    AUTO-MAS wrote for an attempt that never ran (transitional, e.g. 「未捕获到日志」)
    are not tries either, while an attempt MaaEnd spent installing its own update
    did use up one of AUTO-MAS's tries, so it counts. Without a readable shift the
    streak alone bounds it."""
    from ark_relay.features.alarm import unresolved  # noqa: PLC0415
    try:
        shift = unresolved.where(eng, rec)
    except Exception:  # noqa: BLE001 - no shift known: the streak alone bounds the count
        shift = None
    rows = []
    for d in dict.fromkeys((day, shift[0] if shift else day)):
        rows += [e for e in eng.state.read_ledger(d)
                 if e.get("script") == rec.script and e.get("user") == rec.user
                 and _row_started(e) is not None]
    rows.sort(key=_row_started)
    n = 0
    for e in rows:
        raw = e.get("raw") or {}
        if raw.get("hand_started") or core.manual_stop(e):
            continue
        if shift is not None and e.get("run_id") != rec.run_id:
            try:
                if unresolved.where(eng, unresolved._row_rec(e)) != shift:
                    continue
            except Exception:  # noqa: BLE001 - unknown shift: judged by the streak alone
                pass
        if e.get("ok"):
            if _row_started(e) >= rec.started:
                return n + 1   # the success that healed it is the streak's last try
            n = 0              # a success before it ends the streak before it
        elif not e.get("transitional") or raw.get("maaend_update_restart"):
            n += 1
    return n


def _row_started(e: dict) -> datetime | None:
    """A ledger row's start as an aware time; None when unreadable or naive."""
    try:
        t = datetime.fromisoformat(str(e.get("started")))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else None


def _diagnosis(eng, rec: RunRecord) -> str:
    """What is known about why `rec` failed: a known cause as it is, the model asked
    only about the rest."""
    tail = eng.log_tails.pop(rec.run_id, "") or collector.log_tail(rec)
    causes = (rec.raw or {}).get("maaend_fail_causes") or {}
    # An unconfirmed cause states what was seen, not why: still ask about it.
    from ark_relay.features.verify.collector_maaend import CLAIM_UNCONFIRMED  # noqa: PLC0415
    known = {k: v for k, v in causes.items() if v != CLAIM_UNCONFIRMED}
    rest = [t for t in rec.failed_tasks if t not in known]
    return "\n".join(x for x in (
        texts.known_cause(causes),
        summary.diagnose(eng.cfg, rec.script, rest, tail) if rest or not known else "",
    ) if x)


def _later_success(eng, rec: RunRecord) -> str:
    """run_id of a ledger row of the same script and user, started after `rec`, that
    exited normally with nothing left undone and was not cut short by the red
    button; '' when there is none."""
    day = run_day(rec)
    for e in eng.state.read_ledger(day):
        if ((e.get("script"), e.get("user")) != (rec.script, rec.user) or not e.get("ok")
                or e.get("incomplete") or core.manual_stop(e)):
            continue
        try:
            after = datetime.fromisoformat(str(e.get("started"))) > rec.started
        except (TypeError, ValueError):   # unreadable, or naive against aware: not known to be later
            continue
        if after:
            return str(e.get("run_id") or "")
    return ""


def _restart_result(rec: RunRecord) -> str:
    """What AUTO-MAS recorded as the result of an attempt ('' when it wrote none)."""
    raw = rec.raw or {}
    return str(raw.get("general_result") or raw.get("maa_result") or raw.get("maaend_result") or "").strip()


def _restart_note(rec: RunRecord) -> str:
    """The line a final alarm carries when its held record is an attempt AUTO-MAS
    recorded as a restart (collector._TRANSITIONAL; held by _handle) and no record
    of the script came after it; '' for any other record."""
    if not rec.transitional or (rec.raw or {}).get("maaend_update_restart"):
        return ""
    return texts.restart_was_last(_restart_result(rec), rec.started.astimezone(SERVER_TZ).strftime("%H:%M"))


def _healed_title(eng, rec: RunRecord, day: str) -> str:
    """What a held failure that recovered is called in relay.log (_flush_pending):
    its make-up went through (MAA / MaaEnd), it sat in an update's streak
    (core.episode_kinds 「update」), or AUTO-MAS's own retry got past it."""
    if rec.script in ("MAA", "MaaEnd"):
        from ark_relay.features.alarm import unresolved  # noqa: PLC0415
        if unresolved.after_makeup(eng, rec)[0] == unresolved.PASSED:
            return texts.makeup_passed(unresolved.GAME[rec.script], unresolved.where(eng, rec)[1])
    if core.episode_kinds(eng.state.read_ledger(day)).get(rec.run_id) == "update":
        return texts.healed_after_update(rec.script)
    return texts.self_healed(rec.script)
