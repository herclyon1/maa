"""What one run actually got done, checked against its evidence (outcome.py
holds the criteria); handle.py asks this once AUTO-MAS says a run exited
normally. Also books 「all tasks done, MaaEnd did not exit」.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ark_relay.features.verify import outcome
from ark_relay.core.config import SERVER_TZ, RunRecord
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
    """
    from ark_relay.core.collector import _automas_result_time  # noqa: PLC0415
    # Read from handle at call time: tests rebind handle._ship_evidence.
    from ark_relay.features.alarm.handle import _ship_evidence  # noqa: PLC0415
    idle = 0
    if eng.cfg.history_dir and (ended := _automas_result_time(eng.cfg.history_dir, rec.script, rec.started)):
        idle = max(0, int((ended - rec.finished).total_seconds() // 60))
    rec.raw["maaend_no_self_exit"] = idle
    day = run_day(rec)
    eng.state.mark_raw(day, rec.run_id, "maaend_no_self_exit", idle)
    nudge = _nudged_exit(eng, rec)
    if nudge is not None:
        # The watchdog asked MXU to stop (upstream MXU#371) and MaaEnd then left with
        # no kill: the same event its own exit books as recovered
        # (maaend_watchdog.Watchdog._verify_nudge), so this line goes the same way -
        # daily report, plus errwatch's one 「自愈待查」 red item in the technical log.
        # A request that failed or did not make it exit is killed and booked
        # 「failed」, and this line is pushed as below.
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        log.warning("🟠 MaaEnd %s 任务全部完成，但跑完没自己退出（空等 %d 分钟）；看门狗在第 %s 秒请它停一次，"
                    "它自己退出了，没有强行结束（上游 MXU#371）", rec.run_id, idle, nudge.get("after", "?"),
                    extra=errwatch.recovered())
    else:
        # Every task was done; only the exit was missing, and no stop request made it
        # exit: pushed (errwatch).
        log.warning("🟠 MaaEnd %s 任务全部完成，但跑完没自己退出（空等 %d 分钟）", rec.run_id, idle)
    # The run is ok, so the failure path never ships its bundle, and MXU's own log
    # of the hang (why the quit-after-run exit never fired) would stay on the
    # machine. Ship it here, once per record: a replay of the record finds the
    # link already on it.
    if not rec.raw.get("evidence_page"):
        _ship_evidence(eng, rec)


def _nudged_exit(eng, rec: RunRecord) -> "dict | None":
    """The watchdog's stop request this run exited on (upstream MXU#371), or None.

    The watchdog books each request in StateStore marks (maaend_watchdog.NUDGE_MARK)
    keyed by MXU's tasks-completed time, which falls inside the run: after its start
    and before AUTO-MAS recorded its end, give or take NUDGE_FORGET_SECONDS. The run
    must also have ended within NUDGE_FORGET_SECONDS of the request: a later exit is
    not claimed for the request by the watchdog either. An entry
    still 「asked」 counts as exited: AUTO-MAS has recorded the run, so MaaEnd has
    left, and a kill would have booked 「failed」 first. One entry, one run: the
    matching run's id is written on it, so a later run cannot claim it again.
    """
    from ark_relay.features.run.maaend_watchdog import (  # noqa: PLC0415
        NUDGE_FORGET_SECONDS, NUDGE_MARK)
    store = eng.state.store
    rows = store.get("marks", NUDGE_MARK) or []
    hi = rec.finished + timedelta(seconds=NUDGE_FORGET_SECONDS)
    for row in rows:
        if not isinstance(row, dict) or row.get("run_id") not in (None, rec.run_id):
            continue
        try:
            at = datetime.strptime(str(row.get("done_at")), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if rec.started.tzinfo is not None:
            at = at.replace(tzinfo=SERVER_TZ)   # MXU stamps the machine's clock, as AUTO-MAS does
        if not rec.started <= at <= hi:
            continue
        if row.get("state") not in ("asked", "exited"):
            return None
        # The watchdog's own bound, mirrored: an exit more than NUDGE_FORGET_SECONDS
        # after the request is not its doing (a row left 「asked」 by a relay restart,
        # then AUTO-MAS's own timeout ending MaaEnd much later, would read as one).
        after = row.get("after") if isinstance(row.get("after"), int) else 0
        if rec.finished > at + timedelta(seconds=after + NUDGE_FORGET_SECONDS):
            return None
        if row.get("run_id") != rec.run_id:
            row["run_id"] = rec.run_id
            store.set("marks", NUDGE_MARK, rows)
        return row
    return None
