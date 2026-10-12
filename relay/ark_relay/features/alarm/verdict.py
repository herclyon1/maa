"""What one run actually got done, checked against its evidence (outcome.py
holds the criteria); handle.py asks this once AUTO-MAS says a run exited
normally. Also books 「all tasks done, MaaEnd did not exit」.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from ark_relay.features.verify import outcome
from ark_relay.core.config import RunRecord
from ark_relay.features.alarm.gamelogs import (
    MAAEND_NOTHING_TO_RUN, _maa_app_log, _maaend_app_log, _maaend_new_shots, _okww_master_config,
    _okww_nest_expected)
from ark_relay.features.alarm.records import run_day
from ark_relay.features.alarm.runchecks import _judged

# Same logger as handle.py: relay.log names these lines "ark.handle".
log = logging.getLogger("ark.handle")


def _verify_outcome(eng, rec: RunRecord) -> str | None:
    """Check against the evidence what this round actually accomplished; returns None when everything was done.

    The criteria live in `outcome.py`, with samples taken from real logs. This
    function only assembles the log text and what was supposed to happen -
    **a failed check must never block bookkeeping**, so the whole body is wrapped
    in try: an error in the check itself only writes a log line and does not
    change existing behaviour.
    """
    try:
        text = ""
        if rec.log_path and rec.log_path.exists():
            text = rec.log_path.read_text(encoding="utf-8", errors="replace")
        if not text:
            return None                     # no log means nothing to check against; do not report blindly
        if rec.script == "OK-WW":
            expect_nest = _okww_nest_expected(eng.cfg.automas_dir)
            if expect_nest is None:
                # If the config cannot be read, say so; never quietly drop the
                # tacet-nest check.
                checks = outcome.okww_checks(text, expect_nest=False)
                checks.append(outcome.Check(
                    "能读到 OK-WW 生效中的配置", False,
                    f"{eng.cfg.automas_dir}/data/*/Default/ConfigFile/ "
                    "下没读到 NightmareNestTask.json 和 DailyTask.json，"
                    "所以这一轮该不该打残象聚落无从判断"))
            else:
                only = (_okww_master_config(eng.cfg.automas_dir, "NightmareNestTask")
                        .get("Only Farm These Nests") or "").strip()
                checks = outcome.okww_checks(text, expect_nest=expect_nest, only_nest=only)
                return _judged(rec, checks, "OK-WW", expect_nest=expect_nest, only_nest=only)
            return _judged(rec, checks, "OK-WW", expect_nest=None, only_nest="")
        if rec.script == "MAA":
            # Only MAA's own log is read: AUTO-MAS's history carries no per-
            # subtask success or failure.
            # The finish time is used as the upper bound only when it is
            # trustworthy (see RunRecord.duration_known).
            # Leave 5 minutes of slack: MAA's wrap-up lines can land after
            # AUTO-MAS has already recorded the run.
            until = (rec.finished + timedelta(minutes=5)
                     if rec.duration_known else None)
            maa_log = _maa_app_log(eng.cfg.maa_dir, rec.started, until)
            if maa_log is None:
                # Feeding empty text to maa_checks passes every check = another
                # false green.
                return _judged(rec, [outcome.Check(
                    "能读到 MAA 自己的日志", False,
                    f"maa_dir={eng.cfg.maa_dir}，"
                    "MAA 自己的日志里没有这一轮的记录，基建做没做成核对不了")],
                    "MAA")
            return _judged(rec, outcome.maa_checks(maa_log), "MAA")
        if rec.script == "MaaEnd":
            # AUTO-MAS closes a retry round with one more record whose whole log
            # is MAAEND_NOTHING_TO_RUN_LOG - bookkeeping, not a run: no MaaEnd
            # process, no app log. Judged as a run it would fail the
            # completion-marker check: the record starts after the real run's log
            # was last written, so the mtime cut in _maaend_app_log excludes it.
            if MAAEND_NOTHING_TO_RUN in text:
                log.info("%s 是 AUTO-MAS 的收尾记录（没有可执行任务），不是一趟运行，不核对", rec.run_id)
                return None
            shots = _maaend_new_shots(eng.cfg.maaend_dir, rec.started)
            # Read AUTO-MAS's history log together with MaaEnd's own app log:
            # the wrap-up marker only exists in the latter and task start/finish
            # only in the former, so missing either one misjudges the round.
            app = _maaend_app_log(eng.cfg.maaend_dir, rec.started)
            both = text + "\n" + app
            # Only with MaaEnd's own log in hand: the wrap-up line lives there, and
            # without it every run would look like one that did not exit.
            own = bool(app.strip())
            if outcome.maaend_no_self_exit(both, own_log=own):
                _mark_no_self_exit(eng, rec)
            return _judged(rec, outcome.maaend_checks(both, shots, own_log=own), "MaaEnd")
    except Exception as exc:
        log.exception("结果核对本身出错")
        # None would mean "everything was done"; a check that crashed has
        # verified nothing, so it says so. Bookkeeping is unaffected either way
        # (this function only decides whether to say one extra thing).
        return (f"{rec.script} 这一轮的结果核对没跑成（{type(exc).__name__}: "
                f"{exc}），所以「干成了没有」这次没人验过。")
    return None


def _mark_no_self_exit(eng, rec: RunRecord) -> None:
    """Book 「all tasks done, MaaEnd did not exit」 with how long it then sat idle.

    The idle span runs from the log's last line to AUTO-MAS's own result line in
    app.log, in minutes; 0 when that line is not there to read.

    The hang is upstream MistEO/MXU#371. AUTO-MAS v5.7.0-beta.2 ends such a MaaEnd
    itself right after recording the result (collector._automas_ended_maaend reads
    its line): the run is done and AUTO-MAS handles it by design, so that case is an
    INFO line only. No such AUTO-MAS line and the WARNING is pushed (errwatch).
    """
    from ark_relay.core.collector import _automas_ended_maaend, _automas_result_time  # noqa: PLC0415
    # Read from handle at call time: tests rebind handle._ship_evidence.
    from ark_relay.features.alarm.handle import _ship_evidence  # noqa: PLC0415
    idle, ended_by_mas = 0, None
    if eng.cfg.history_dir and (ended := _automas_result_time(eng.cfg.history_dir, rec.script, rec.started)):
        idle = max(0, int((ended - rec.finished).total_seconds() // 60))
        ended_by_mas = _automas_ended_maaend(eng.cfg.history_dir, ended)
    rec.raw["maaend_no_self_exit"] = idle
    day = run_day(rec)
    eng.state.mark_raw(day, rec.run_id, "maaend_no_self_exit", idle)
    if ended_by_mas is not None:
        # Handled: AUTO-MAS ends it on its own path every time, the run's work is
        # done and the cause is known (MXU#371), so there is nothing to look into.
        # Kept in the relay log and the technical section of the daily report.
        log.info("MaaEnd %s 任务全部完成，跑完没自己退出（空等 %d 分钟）；AUTO-MAS %s 记下结果后按设计结束了它"
                 "（上游 MXU#371）", rec.run_id, idle, ended_by_mas.strftime("%H:%M:%S"))
    else:
        # Every task was done; only the exit was missing, and AUTO-MAS did not end
        # it on its own path: pushed (errwatch).
        log.warning("🟠 MaaEnd %s 任务全部完成，但跑完没自己退出（空等 %d 分钟）", rec.run_id, idle)
    # The run is ok, so the failure path never ships its bundle, and MXU's own log
    # of the hang (why the quit-after-run exit never fired) would stay on the
    # machine. Ship it here, once per record: a replay of the record finds the
    # link already on it.
    if not rec.raw.get("evidence_page"):
        _ship_evidence(eng, rec)
