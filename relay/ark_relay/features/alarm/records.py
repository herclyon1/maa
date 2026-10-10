"""Facts handle.py reads about one run record, and marks it writes on the
record and its ledger line before deciding what to push.
"""
from __future__ import annotations

import logging
from datetime import datetime
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
    if rec.script != "MaaEnd" or rec.ok or rec.transitional:
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
    (task_shots.py) - game evidence for core.maaend_unverified. A key of its own,
    so collector.refresh_raw (which re-parses only the log) never drops it.
    raw['tasks_shot_files']: {task: that picture, relative to the state folder},
    the evidence a machine check names (machinechecks/runs.py)."""
    try:
        from ark_relay.features.verify import collector_maaend
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
    try:
        from ark_relay.features.gameupdate import gameupdate  # noqa: PLC0415
        why = gameupdate.in_maintenance(eng.cfg.state_dir, rec.script, rec.started)
    except Exception:  # unknown is not evidence; logged with the traceback
        log.warning("查不了维护窗口，%s 按普通失败处理", rec.run_id, exc_info=True)
    why = why or efstatus.update_hint(rec.started)
    if why:
        raw["maaend_unreachable"] = True
        raw["maaend_unreachable_why"] = why
        log.info("⏸ MaaEnd %s 每个任务秒败、零完成，且有官方依据（%s）：按进不了游戏处理", rec.run_id, why)
    else:
        log.warning("❌ MaaEnd %s 每个任务秒败、零完成，像没进游戏，但没有官方维护或更新公告："
                    "按普通失败处理（报警、补跑）", rec.run_id)


def _mark_raw_on_ledger(eng, rec: RunRecord, key: str, value) -> None:
    """A raw field learned after the run's ledger line was written goes onto that line."""
    day = run_day(rec)
    if not eng.state.mark_raw(day, rec.run_id, key, value):
        log.warning("没能把 %s 写回 %s 的账本", key, rec.run_id)


def _attempts(eng, rec: RunRecord, day: str) -> int:
    """How many times this script really ran today: stubs AUTO-MAS wrote for an
    attempt that never ran (transitional, e.g. 「未捕获到日志」) are not attempts."""
    # An attempt MaaEnd spent installing its own update did run and did use up
    # one of AUTO-MAS's tries, so it counts.
    return sum(1 for e in eng.state.read_ledger(day)
               if e["script"] == rec.script and e["user"] == rec.user
               and (not e.get("transitional") or (e.get("raw") or {}).get("maaend_update_restart")))


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
