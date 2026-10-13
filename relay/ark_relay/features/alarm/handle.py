"""Bookkeeping and alerting: once a run record lands, judge it, record it, keep the evidence, decide whether to push.

The first argument of every function here is the Engine instance, whose cfg /
state / notifier / _pending they read. Helpers live next to this file:
gamelogs.py (the games' own logs), records.py (facts and marks on one record),
runchecks.py (what the machine checks get), verdict.py (what a run got done),
pushes.py (alarms pushed at once), manualstops.py (runs a 停一切 cut short),
daymarks.py (per-day marks); their names are imported here so `handle.<name>`
keeps working.

Tests rebind names on this module (_ship_evidence, _weekly_gates,
_archive_okww_evidence, _screenshot_to, _hand_started, _run_ctx,
backfill_manual_stops, handle.time). The ones defined here stay here together
with every function that calls them by bare name; _run_ctx is called only by
_judge_run here, and backfill_manual_stops only through `handle.` from outside.
A moved function that needs one of them imports it from this module inside its
body, so it reads the binding a test may have replaced.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core import texts
from ark_relay.core import ledger as core
from ark_relay.features.maintenance import efstatus
from ark_relay.features.verify import outcome
from ark_relay.core.config import SERVER_TZ, RunRecord
from ark_relay.features.alarm.gamelogs import (
    MAAEND_NOTHING_TO_RUN, MAAEND_NOTHING_TO_RUN_LOG, _MAA_LOG_TAIL, _MAA_TS, _maa_app_log,
    _maaend_app_log, _maaend_new_shots, _okww_log_file, _okww_master_config, _okww_nest_expected)
from ark_relay.features.alarm.records import (
    SHOT_AFTER_S, SHOT_BEFORE_S, _append_ledger_once, _attempts, _confirm_unreachable, _diagnosis,
    _estop_overlap, _healed_title, _later_success, _mark_raw_on_ledger, _mark_task_shots,
    _mark_update_restart, _restart_note, _restart_result, _restore_after_maaend, _same_shift,
    _state_relative, run_day)
from ark_relay.features.alarm.runchecks import (
    _OUTCOME, _RunWatch, _alert_days, _alert_file, _alert_sizes, _alerts_since, _judged,
    _run_ctx, _test_run, _update_restarts)
from ark_relay.features.alarm.verdict import _mark_no_self_exit, _verify_outcome
from ark_relay.features.alarm.pushes import (
    UNVERIFIED_KIND, _UNVERIFIED_WHY, _errwatch, _evidence_note, _push_now, _push_undone,
    _push_unresolved, _push_unverified)
from ark_relay.features.alarm.manualstops import (
    _drop_alarms_for_manual, _push_before_stop, backfill_manual_stops)
from ark_relay.features.alarm.daymarks import (
    _alert_key, _alerted_file, _already_alerted, _maintenance_today, _mark_alerted)

# This module's public names plus every name re-exported from the modules above
# (callers and tests say handle.<name>); pyflakes and ruff count a listed name as used.
__all__ = [
    "MAAEND_NOTHING_TO_RUN",
    "MAAEND_NOTHING_TO_RUN_LOG",
    "SAME_ROUND",
    "SHOT_AFTER_S",
    "SHOT_BEFORE_S",
    "UNVERIFIED_KIND",
    "_MAA_LOG_TAIL",
    "_MAA_TS",
    "_UNVERIFIED_WHY",
    "_alert_days",
    "_alert_file",
    "_alert_key",
    "_alert_sizes",
    "_alerted_file",
    "_alerts_since",
    "_already_alerted",
    "_drop_alarms_for_manual",
    "_judged",
    "_maaend_app_log",
    "_maaend_new_shots",
    "_maintenance_today",
    "_mark_alerted",
    "_mark_no_self_exit",
    "_okww_master_config",
    "_okww_nest_expected",
    "_state_relative",
    "_test_run",
    "_update_restarts",
    "_verify_outcome",
    "backfill_manual_stops",
    "log",
]

log = logging.getLogger("ark.handle")


def _self_heal_red(eng, where: str, why: str) -> None:
    """A held failure that healed itself stays out of the group; one red item in the
    technical log says a session has to look at why it failed (techlog.self_heal)."""
    from ark_relay.core import techlog  # noqa: PLC0415
    try:
        techlog.self_heal(where, why, state_dir=getattr(eng.cfg, "state_dir", None))
    except Exception:  # the booking goes on; the group hears the failure to write
        log.warning("自愈待查的红项没写进技术日志：%s", where, exc_info=True)


# ---------- per record ----------

def _warn_if_evidence_stale(eng, rec: RunRecord, dst: Path) -> None:
    """The archived debug log is not necessarily from the failing run - say so plainly when it does not line up, rather than misleading the reader.

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_warn_if_evidence_stale」。
    """
    try:
        # Compare instants, not clock readings: the run_id stem is AUTO-MAS's
        # clock (UTC+4, collector.AUTOMAS_NAME_TZ) and carries no date, so the
        # stem against a Beijing mtime missed exactly the previous round's log
        # (audit 2026-10-13 s7 #3).
        cut = rec.started.timestamp()
        began = rec.started.astimezone(SERVER_TZ)
        for f in dst.glob("*.log"):
            if f.name.startswith("automas-"):
                continue          # this one was taken by run_id, so it always lines up
            mtime = f.stat().st_mtime
            if mtime < cut:
                mt = datetime.fromtimestamp(mtime, tz=SERVER_TZ)
                log.warning("⚠️ 证据里的 %s 最后写于 %s，早于这一轮开始的 %s，"
                            "多半是**别的轮次**的日志，别拿它当这次失败的依据",
                            f.name, mt.strftime("%m-%d %H:%M:%S"), began.strftime("%m-%d %H:%M:%S"))
    except Exception:  # the booking goes on; the group hears the check broke
        log.warning("证据时间范围检查失败（这一份证据没核是不是这一轮的）", exc_info=True)


# Take a full-screen shot. **Must run in an interactive session** - the relay is
# a service running in session 0, which has no desktop at all, so shooting from
# here only ever yields a black image.
_SHOT_PS1 = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object Drawing.Bitmap $b.Width, $b.Height
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save('%OUT%', [Drawing.Imaging.ImageFormat]::Png)
"""


def _screenshot_to(out: Path) -> bool:
    """Take a screenshot in an interactive session and save it to `out`. True on success."""
    from ark_relay.features.preupdate.preupdate_common import _PWSH7, _spawn_hidden_via_task  # noqa: PLC0415 - avoids an import cycle
    ps1 = Path(tempfile.gettempdir()) / f"ark-shot-{os.getpid()}.ps1"
    try:
        ps1.write_text(_SHOT_PS1.replace("%OUT%", str(out)), encoding="utf-8")
        # No console window: an OK-WW record lands while the next script
        # (MaaEnd, foreground controller) may already be driving its game, and a
        # window flashing up takes the foreground from it (2026-10-11 09:39).
        _spawn_hidden_via_task(_PWSH7, ps1.parent,
                               ("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)))
        # The scheduled task starts asynchronously, so wait for the image to
        # land. Nothing after 10 seconds means the shot did not happen.
        for _ in range(20):
            if out.is_file() and out.stat().st_size > 10_000:
                return True
            time.sleep(0.5)
        return False
    except Exception:   # a failed screenshot must never take bookkeeping down
        log.warning("截图失败", exc_info=True)
        return False
    finally:
        ps1.unlink(missing_ok=True)


def _archive_okww_evidence(eng, rec: RunRecord) -> None:
    """When OK-WW fails, rescue a log slice and **a screenshot taken right then**.

    When upstream `ensure_main` cannot reach 「大世界 + 队伍」 (`Please start in game
    world and in team!`), the log cannot say what was in the way; only the screen
    at that moment can (a dialog, for one: docs/OKWW-STUCK-DIALOG.md), and OK-WW's
    own debug screenshots are switched off.

    The whole body is wrapped in try: rescuing evidence must never block
    bookkeeping.
    """
    dst = Path(eng.cfg.state_dir) / "evidence" / rec.run_id.replace("/", "_")
    try:
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        if log_path := _okww_log_file(eng.cfg.okww_dir):
            try:
                tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-800:]
                (dst / "ok-script.tail.log").write_text("\n".join(tail), encoding="utf-8")
                n += 1
            except OSError:
                log.warning("OK-WW 日志读不出来：%s", log_path, exc_info=True)
        if eng.cfg.history_dir:
            for suffix in (".log", ".json"):
                src_f = Path(eng.cfg.history_dir) / (rec.run_id + suffix)
                if src_f.is_file():
                    shutil.copy2(src_f, dst / ("automas-" + src_f.name))
                    n += 1
        # The screen. This is the reason this function exists.
        if _screenshot_to(dst / "screen.png"):
            n += 1
        else:
            log.error("❌ OK-WW 失败截图没拍成——下次还是只能猜屏幕上是什么")
        log.info("📦 OK-WW 失败证据已存档 %d 个文件 → %s", n, dst)
    except Exception:
        log.warning("存 OK-WW 失败证据时出错，跳过", exc_info=True)


def _archive_maaend_evidence(eng, rec: RunRecord) -> None:
    """Rescue this round's on_error screenshots and debug logs into the relay's own directory.

    Saved to state/evidence/<run_id>/. It must never block bookkeeping, so the
    whole body is wrapped in try.
    """
    try:
        if not eng.cfg.maaend_dir:
            log.error("❌ 存不了 MaaEnd 失败证据：maaend_dir 没解析出来"
                      "（ARK_MAAEND_DIR 未设，且 AUTO-MAS 里也没查到）。"
                      "MaaEnd 下次启动就会清空 debug 目录，证据即将丢失")
            return
        src = Path(eng.cfg.maaend_dir) / "debug"
        if not src.is_dir():
            log.error("❌ 存不了 MaaEnd 失败证据：%s 不是目录", src)
            return
        dst = Path(eng.cfg.state_dir) / "evidence" / rec.run_id.replace("/", "_")
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        oe = src / "on_error"
        if oe.is_dir():
            for png in sorted(oe.glob("*.png"))[:20]:
                shutil.copy2(png, dst / png.name)
                n += 1
        logs = sorted(src.glob("*.log"), key=lambda f: f.stat().st_mtime)
        for f in logs[-2:]:
            shutil.copy2(f, dst / f.name)
            n += 1
        # AUTO-MAS's own .log/.json for that round **always lines up with this
        # failure**, whereas MaaEnd's debug log may not - see the time-range check
        # below. The .json names the failing task.
        if eng.cfg.history_dir:
            for suffix in (".log", ".json"):
                src_f = Path(eng.cfg.history_dir) / (rec.run_id + suffix)
                if src_f.is_file():
                    shutil.copy2(src_f, dst / ("automas-" + src_f.name))
                    n += 1
        log.info("📦 MaaEnd 失败证据已存档 %d 个文件 → %s", n, dst)
        eng._warn_if_evidence_stale(rec, dst)
    except Exception:
        log.exception("MaaEnd 证据存档失败（不影响记账）")


def _mark_downtime(eng, rec: RunRecord) -> None:
    """A failure that could not get into the game: register the game for the update
    and re-run after the queue (gameupdate.mark_pending -> run_deferred), and mark a
    failure inside an official maintenance window on the record and its ledger line.

    For every script (audit 2026-10-13 s7 #1 / s1 #2): this sat in
    _archive_maaend_evidence, so MAA and OK-WW never got the mark, and even
    MaaEnd's stayed off the ledger - the daily report booked a plain failure and
    gameupdate.needs_rerun (it reads the ledger) never re-ran what the alarm
    promised to re-run. Only for a scheduled run being held (_hold_for_retry, the
    MaaEnd update-restart hold): a run pushed at once is not re-run by the relay.
    Never raises: the booking goes on."""
    try:
        from ark_relay.features.gameupdate import gameupdate  # noqa: PLC0415
        from ark_relay.features.maintenance import maintenance  # noqa: PLC0415
        raw = rec.raw
        # Never entering the game at all is the signal that the client needs an update.
        if rec.script == "MaaEnd" and raw.get("maaend_unreachable"):
            gameupdate.mark_pending(eng.cfg.state_dir, "终末地", "今天 MaaEnd 进不了游戏（客户端待更新）")
        if rec.script == "OK-WW" and raw.get("okww_unreachable"):
            gameupdate.mark_pending(eng.cfg.state_dir, "鸣潮", "今天 OK-WW 等不到游戏窗口（客户端待更新）")
        # A failure that ran into official downtime: ⏸ in the daily report, the
        # 「进不了游戏」 alarm instead of a failure, no make-up, and a re-run once
        # the servers are back.
        if why := gameupdate.in_maintenance(eng.cfg.state_dir, rec.script, rec.started):
            raw["maintenance"] = why
            _mark_raw_on_ledger(eng, rec, "maintenance", why)
            game = next((g for g, s in maintenance.SCRIPT_OF.items() if s == rec.script), "")
            if game:
                gameupdate.mark_pending(eng.cfg.state_dir, game, f"今天 {rec.script} 撞上官方维护（{why}）")
    except Exception:  # not knowing leaves it an ordinary failure
        log.warning("没查成 %s 是不是撞上维护 / 进不了游戏，按普通失败处理", rec.run_id, exc_info=True)


def _weekly_gates(eng, rec: RunRecord) -> None:
    """The weekly gates (weekly boss, weekly garden): which one this run finished, and one line about it when it did.

    Its own step because the blocks have exactly the same shape - look at
    the evidence, ask the weekly gate, say something only if there is something
    to say; they have nothing to do with the self-heal notice or the outcome
    check around them, and mixed together the lines are easy to read across.
    Annihilation is AUTO-MAS's own bookkeeping since the 2026-10-11 hand-over.
    """
    # Only a run that genuinely fills the weekly quota counts.
    # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_handle」
    steps = rec.raw.get("okww_steps") or []
    # Weekly boss: the task name is translated as 「传送并刷取4C声骸」 while the task
    # itself displays 「刷4C(大世界/副本)」; both are accepted. The criterion matches
    # the weekly garden - only actually finishing that step counts.
    if any(s.startswith("周本") and "已完成" in s for s in steps):
        if msg := eng._weeklyboss.on_success(rec.finished):
            eng.notifier.send(texts.WEEKLY, msg)
    if any("周常乐园" in s and "已完成" in s for s in steps) and eng._garden:
        if msg := eng._garden.on_success(rec.finished):
            # The weekly gates have the same shape.
            # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_handle」
            eng.notifier.send(texts.WEEKLY, msg)
    # Annihilation is not booked here: AUTO-MAS records the week itself
    # (Data.AnnihilationCompletedWeek) since the 2026-10-11 hand-over, item 13.


def _handle_success(eng, rec: RunRecord, key: tuple) -> None:
    """Everything to do after AUTO-MAS reports that this round exited normally.

    Its own step because the success and failure paths share not one line: this
    one handles the self-heal notice, the weekly gates and the outcome check,
    while the failure one handles mid-round restarts, update days and holding.
    """
    # A held MaaEnd update restart that started after this round of the same
    # shift (records can land in either order). If this round turns out to have got the
    # work done (the outcome check below), the restart is let go; until then it
    # stays held, and an undone round sends it down the usual path.
    held = eng._pending.get(key)
    after_done = (held is not None and bool((held.raw or {}).get("maaend_update_restart"))
                  and rec.started < held.started and _same_shift(eng, held, rec))
    if not after_done:
        _retry_healed(eng, rec, key)
    _weekly_gates(eng, rec)
    # AUTO-MAS saying 「这个脚本正常退出了」 does not mean it got the work done.
    # So check against the evidence before returning, and anything not done has
    # to be said out loud.
    # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_handle」
    _push_unverified(eng, rec)
    if msg := eng._verify_outcome(rec):
        if after_done:
            _retry_healed(eng, rec, key)
        # Onto the ledger too, or the daily report would open with 全绿 while this
        # very message says otherwise.
        day = run_day(rec)
        if not eng.state.mark_incomplete(day, rec.run_id, msg):
            log.warning("没能把「没干完」写回 %s 的账本，日报会少这一条", rec.run_id)
        # Bundle first, so the alarm carries the link (the round is over: this
        # alarm is the final word on it, and the daily row gets the link too).
        page = _ship_evidence(eng, rec)
        full = msg + (f"\n\n证据包：{page}" if page else "")
        if rec.script in ("MAA", "MaaEnd"):
            title, errs = _push_undone(eng, rec, msg, page)
        else:
            title = texts.ROUND_INCOMPLETE
            errs = eng.notifier.send(title, full, alert=True)
        # Logged after the push: errwatch pushes this line unless the alarm above
        # really went to the group (no second copy of the same thing). When the send
        # failed, errwatch pushes the whole message under the alarm's own title:
        # its default is the first line only, which ends at 「有项目没干成：」 and loses
        # every undone item (audit 2026-10-13 s7 #6; relay.log 10-11 09:30:45).
        ew = _errwatch()
        log.warning("⚠️ %s %s 有项目没干成：\n%s", rec.script, rec.run_id, msg,
                    extra=ew.alarm(title, full) if errs else ew.group_pushed(title, errs, eng.notifier))
        return
    if after_done:
        eng._pending.pop(key, None)
        eng._persist_pending()
        _drop_update_after_done(eng, held, rec.run_id)
    # Booked a success and every outcome check passed: an ERROR line in the game's own
    # log that nobody has looked at still goes to the group (gamelog_errors.py).
    from ark_relay.features.verify import gamelog_errors  # noqa: PLC0415
    try:
        gamelog_errors.check_round(eng, rec)
    except Exception:  # the booking goes on; the group hears the check broke
        log.warning("%s %s 日志里的报错没查成", rec.script, rec.run_id, exc_info=True)
    log.info("✅ %s %s（%d 分钟）静默记账",
             rec.script, rec.run_id, rec.duration_min)
    return


def _retry_healed(eng, rec: RunRecord, key: tuple) -> None:
    """A later success means AUTO-MAS got past the held failure on its own. Report
    it anyway - once for the whole event, not once per failed attempt."""
    if (bad := eng._pending.pop(key, None)) is not None:
        eng._recovered[key] = bad
        eng._persist_pending()
        log.info("↩️ %s 重试后成功，改为自愈通知", rec.script)


def _drop_update_after_done(eng, rec: RunRecord, done: str) -> None:
    """An update restart whose shift's round (`done`) was already done: no make-up
    and no push - that round got its work done, so nothing is left broken. The
    daily report carries it.

    The ledger line stays; the mark on it is what makes the daily report book it
    as the update (core.episode_kinds: a ↪️ row naming the new build) instead of a
    failure, since no success follows it there. Not pushed: the user's words for
    this are in relay/USER-SWITCHES.txt (this function's entry).
    """
    _mark_raw_on_ledger(eng, rec, "maaend_update_after_done", done)
    log.info("↪️ MaaEnd %s 前面那趟已经做完（%s），这趟是装新版 %s 重启，只进日报（%s）",
             rec.run_id, done, rec.raw.get("maaend_update_restart"), texts.MAAEND_UPDATE_AFTER_DONE)


def _update_restart_done(eng, rec: RunRecord) -> bool:
    """At the push: a held MaaEnd update restart whose shift's round is done by now
    is let go (_drop_update_after_done) instead of alarmed on. True when let go.

    _handle lets it go when that round is already booked, and _handle_success when
    the round lands after it; this is the last door before any alarm, so a done
    shift can never end in an alarm about the restart, whichever order and tick the
    two records came in."""
    if rec.script != "MaaEnd" or not (rec.raw or {}).get("maaend_update_restart"):
        return False
    from ark_relay.features.alarm import unresolved  # noqa: PLC0415
    try:
        done = unresolved.done_in_shift(eng, rec)
    except Exception:  # not knowing keeps it on its usual path
        log.warning("查不了这一班有没有做完的那趟，%s 照旧处理", rec.run_id, exc_info=True)
        return False
    if not done:
        return False
    eng._pending.pop((rec.script, rec.user), None)
    eng._persist_pending()
    eng.log_tails.pop(rec.run_id, None)
    _drop_update_after_done(eng, rec, done)
    return True


# Attempts of one AUTO-MAS round start minutes apart at most (its retries follow at
# once); a held record further away than this belongs to another round.
SAME_ROUND = timedelta(minutes=30)


def _keeps_rejected(held, rec: RunRecord) -> bool:
    """Whether the held record of the same key stays held instead of `rec`: it says
    MAA refused the config (collector_maa) and `rec`, an attempt of the same round,
    does not. AUTO-MAS lands a round's records together in no fixed order, and one
    without its log (json only) carries no reason; held last, the alarm would lose the refusal and wait for a make-up tick."""
    return (held is not None and held is not rec
            and bool((held.raw or {}).get("maa_config_rejected"))
            and not (rec.raw or {}).get("maa_config_rejected")
            and abs(rec.started - held.started) <= SAME_ROUND)


def _hold_for_retry(eng, rec: RunRecord, key: tuple) -> None:
    """Wrapping up a genuine failure: queue it for pushing, persist it, rescue the evidence.

    Its own step because it is the only section of the failure path that stops
    judging and just cleans up, and because every step of it has to be finished
    before the next thing can go wrong - the order must not be changed.
    """
    _mark_downtime(eng, rec)   # before the hold is persisted: the mark survives a restart
    # Hold it. Only alert once the script has stopped retrying entirely.
    if not _keeps_rejected(eng._pending.get(key), rec):
        eng._pending[key] = rec   # else the held refusal stays: the alarm is about it
    eng._persist_pending()   # queued to disk before anything else can go wrong
    # Move the evidence away the moment a failure is recorded: the instant
    # MaaEnd next starts it clears the previous round's screenshots and logs
    # itself, and by the time a person looks there is nothing left.
    # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_handle」
    if rec.script == "MaaEnd":
        eng._archive_maaend_evidence(rec)
    elif rec.script == "OK-WW":
        _archive_okww_evidence(eng, rec)
    if _ship_evidence(eng, rec):
        eng._persist_pending()   # again, now with the link the final alarm carries
    if rejected := (eng._pending[key].raw or {}).get("maa_config_rejected"):
        # Collapsed with the round's other attempts under one key and pushed by this
        # tick's _flush_pending (makeup.refuse_rejected): nothing to wait for.
        log.info("🚫 MAA 不接受这份配置（%s），不等重试、不补跑，这一轮就进群", rejected)
        return
    log.info("⏳ %s 失败，暂不推送，等重试结果", rec.script)


def _ship_evidence(eng, rec: RunRecord) -> str:
    """Build the upstream-format bundle and push it off the machine; log the link.

    Returns the link ("" when nothing went up) and leaves it on rec.raw and on
    the day's ledger line: the final alarm and the daily report carry it.

    The bundle is the same files the project's own export button would produce
    (evidence.py), plus this round's AUTO-MAS log and record, readable with the
    machine off. Wrapped in try: shipping
    evidence must never block bookkeeping.
    """
    try:
        from ark_relay.features.evidence import evidence  # noqa: PLC0415
        extra = []
        if eng.cfg.history_dir:
            for suffix in (".log", ".json"):
                f = Path(eng.cfg.history_dir) / (rec.run_id + suffix)
                if f.is_file():
                    extra.append(f)
        # One run's window, widened a little on both ends (evidence.WINDOW_SLACK):
        # a bundle is always cut by time, never the whole debug folder.
        window = evidence.run_window(rec.started, rec.finished if rec.duration_known else None)
        if rec.script == "MaaEnd":
            # The desktop at each task's end (task_shots.py), next to MaaEnd's own
            # on_error / vision pictures that bundle_maaend takes.
            from ark_relay.features.evidence import task_shots  # noqa: PLC0415
            extra += task_shots.in_window(eng.cfg.state_dir, window)
        # relay.log up to now: what the relay did about the run comes after it.
        res = evidence.save_and_upload(eng.cfg, rec.script, rec.run_id, extra, window=window,
                                       relay_until=time.time())
        if res.get("page"):
            # One archive goes up (evidence.pack_one), so "uploaded" holds one link;
            # the count that means something is the files inside it.
            n = len(res.get("files") or [])
            log.info("🗂️ %s 证据包已上传（%d 个文件）→ %s", rec.run_id, n, res["page"])
            rec.raw["evidence_page"] = res["page"]     # the failure alarm and the daily row carry it
            day = run_day(rec)
            if not eng.state.mark_evidence(day, rec.run_id, res["page"]):
                log.warning("没能把证据链接写回 %s 的账本，日报那一行会没有链接", rec.run_id)
            eng.notifier.send(texts.EVIDENCE_SAVED,
                              texts.evidence_saved_body(rec.script, rec.started.astimezone(SERVER_TZ).strftime("%m-%d %H:%M"),
                                                        n, res["page"]))
        else:
            log.warning("🗂️ %s 证据包没传上去：%s", rec.run_id, "；".join(res.get("errors") or ["没有文件"]))
        return res.get("page") or ""
    except Exception:
        log.exception("证据外送出错（不影响记账）")
        return ""


def _hand_started(eng, rec: RunRecord) -> str:
    """The AUTO-MAS task id when a person started this run at AUTO-MAS itself, else ''.

    Never raises: not knowing keeps the run on the normal path (trigger.py).
    """
    try:
        from ark_relay.features.guard import trigger  # noqa: PLC0415
        task = trigger.hand_started(eng.cfg.automas_dir, eng.cfg.state_dir, rec.started)
    except Exception:
        log.exception("判断是不是有人手动开的出错，按定时的处理")
        return ""
    return task.id if task else ""


def _hand_started_alarm(eng, rec: RunRecord, key: tuple) -> "tuple[str, str, str, str] | None":
    """(day, alarm kind, title, body) of the alarm about a run a person started from
    AUTO-MAS's own screen (trigger.py), or None when it got its work done. _handle
    pushes it at once: alarmed like any other failure, with a line saying whose run
    it was; no make-up is run for it.

    It stays in the ledger as a normal row - the daily report shows it
    (core.split_test). Its failure is pushed at once: AUTO-MAS writes a script's records only once all its attempts
    are over, and holding it would hand it to the shift's make-up (makeup.py), which
    is not for a person's own run.
    """
    day = run_day(rec)
    kind = "手动"          # unresolved.send keys it with rec.run_id
    if rec.ok:
        # The held failure is done with, but not as 「重试后成功」: nobody's retry healed
        # it, a person did. A person fixing it is not "fixed itself", so it is pushed
        # now with a line saying so, as the manual_stop branch pushes its held failure
        # (audit 2026-10-13 s7 #2: it was dropped with one INFO line).
        # Only a failure from before this run: one held from a later round was not
        # got past by it and stays held.
        held = eng._pending.get(key)
        if held is not None and held.started < rec.started:
            eng._pending.pop(key, None)
            eng._persist_pending()
            hhmm = rec.started.astimezone(SERVER_TZ).strftime("%H:%M")
            title, body = _failure_alarm(eng, held, texts.hand_fixed_note(hhmm), held=True)
            errs = _push_now(eng, run_day(held), "手动跑成前", held.run_id, title, body)
            log.info("🖐 %s 之前压着的失败 %s，后来有人手动跑成了，%s", rec.script, held.run_id,
                     "没推出去，下一轮再推" if errs else "照报进群")
        _weekly_gates(eng, rec)
        _push_unverified(eng, rec)
        if msg := eng._verify_outcome(rec):
            eng.state.mark_incomplete(day, rec.run_id, msg)
            page = _ship_evidence(eng, rec)
            return day, kind, texts.ROUND_INCOMPLETE, (texts.HAND_STARTED_NOTE + "\n" + msg
                                                       + (f"\n\n证据包：{page}" if page else ""))
        log.info("🖐 %s %s 是有人在 AUTO-MAS 上手动开的，跑完了，静默记账", rec.script, rec.run_id)
        return None
    title, body = _failure_alarm(eng, rec, texts.HAND_STARTED_NOTE)
    return day, kind, title, body


def _failure_alarm(eng, rec: RunRecord, note: str, held: bool = False) -> tuple[str, str]:
    """(title, body) of the final-failure alarm about `rec` when it is pushed now
    rather than held (no make-up is run for it): the usual failure text with `note`
    on top and the evidence link. Rescues and ships the evidence first.

    `held`: `rec` was held, and _hold_for_retry captured its evidence when it was
    recorded. Nothing is captured again: by now the screen, the log tail and
    MaaEnd's debug folder belong to a later run (a person's, or the one 停一切
    cut), and copying them would overwrite the held run's own evidence (audit
    2026-10-13 review of s7 #2).

    No _mark_downtime here: the mark (⏸, mark_pending, the relay's re-run) is for
    a scheduled run being held. A hand-started failure is a person's run, and an
    update-day MAA failure is pushed saying the evening shift runs it again; a held
    `rec` got its mark when it was held."""
    if not held and rec.script == "MaaEnd":
        eng._archive_maaend_evidence(rec)
    elif not held and rec.script == "OK-WW":
        _archive_okww_evidence(eng, rec)
    ev = _evidence_note(eng, rec)      # ships the bundle first when the record has none
    title, body = core.format_failure(rec, _diagnosis(eng, rec))
    body = note + "\n" + body + (f"\n{ev}" if ev else "")
    # The 「像没进游戏」 shape with no official notice behind it: said here as
    # pushes._push_unresolved says it on the held final alarm, since
    # _confirm_unreachable logs it at INFO only (review of s7 #5).
    raw = rec.raw or {}
    if raw.get("maaend_unreachable_shape") and not raw.get("maaend_unreachable"):
        body += "\n" + (texts.UNREACHABLE_UNREAD_NOTE if raw.get("maaend_unreachable_unread")
                        else texts.UNREACHABLE_SHAPE_NOTE)
    return title, body


def _handle(eng, rec: RunRecord) -> None:
    """Book one run record, then let the machine checks read what happened
    (machinecheck.py, event 「run」).

    The checks run only after the record was handled to the end: one whose
    handling broke off is replayed on the next tick and judged then."""
    watch = _RunWatch(eng)
    with watch:
        _book(eng, rec)
    _judge_run(eng, rec, watch)


def _book(eng, rec: RunRecord) -> None:
    day = run_day(rec)
    if stop := _estop_overlap(eng, rec):
        rec.raw["manual_stop"] = stop
    elif hand := _hand_started(eng, rec):
        rec.raw["hand_started"] = hand
    _mark_update_restart(eng, rec)
    _confirm_unreachable(eng, rec)
    if rec.script == "MaaEnd":
        _mark_task_shots(eng, rec)
    _append_ledger_once(eng, rec)
    key = (rec.script, rec.user)
    if rec.script == "MaaEnd":
        _restore_after_maaend(eng)
    if rec.script in ("MAA", "MaaEnd"):
        # Is this the day's make-up run? Book its outcome before anything below
        # can return early (a red-button stop returns right away).
        try:
            from ark_relay.features.makeup import makeup  # noqa: PLC0415
            makeup.on_record(eng, rec)
        except Exception:
            log.exception("补跑结果记账出错")

    if rec.raw.get("manual_stop"):
        # Cut short by the red button: not a self-heal, not a success (no weekly
        # gates, no outcome check), not a new failure to hold. A failure held from
        # before the stop, and a failure AUTO-MAS wrote for the stopped run itself,
        # both go to the group, saying the run was stopped by 停一切.
        stop = rec.raw["manual_stop"]
        if (held := eng._pending.pop(key, None)) is not None:
            eng._persist_pending()
            _push_before_stop(eng, held, stop)
        if not rec.ok:
            title, body = _failure_alarm(eng, rec, f"这一趟是停一切停掉的（{stop}），AUTO-MAS 把它记成了失败，照报。")
            _push_now(eng, day, "停一切", rec.run_id, title, body)
        log.info("⏹ %s %s 这趟是停一切停掉的（%s），记手动停止，不算自愈也不算成功；之前的失败已报群",
                 rec.script, rec.run_id, stop)
        return
    if rec.raw.get("hand_started"):
        # A run a person started at AUTO-MAS itself (trigger.py): its failure or its
        # undone round is pushed right here, at once - no make-up for a person's own run.
        if alarm := _hand_started_alarm(eng, rec, key):
            _, kind, title, body = alarm
            errs = _push_now(eng, day, kind, rec.run_id, title, body)
            log.info("🖐 %s %s 是有人在 AUTO-MAS 上手动开的（任务 %s）：%s，%s", rec.script, rec.run_id,
                     rec.raw.get("hand_started"), title, "没推出去，下一轮再推" if errs else "已报群")
        return

    if rec.ok:
        _handle_success(eng, rec, key)
        return

    # AUTO-MAS records a restart (「游戏更新成功，即将重启任务」 sits in
    # _OKWW_BUILTIN_FATAL alongside real faults) as a failed attempt; the next two
    # branches handle MaaEnd's update restarts and every other restart.
    if rec.raw.get("maaend_update_restart"):
        # The shift's round already got everything done: this attempt is MaaEnd
        # restarting into its new build - not held, no make-up, not pushed; its
        # ledger line stays and the daily report says it (_drop_update_after_done).
        from ark_relay.features.alarm import unresolved  # noqa: PLC0415
        try:
            done = unresolved.done_in_shift(eng, rec)
        except Exception:  # not knowing keeps it held, as before
            log.warning("查不了这一班有没有做完的那趟，%s 照旧压着", rec.run_id, exc_info=True)
            done = ""
        if done:
            _drop_update_after_done(eng, rec, done)
            return
        if later := _later_success(eng, rec):
            # Its retry's record landed first: healed already, as _hold_restart does.
            # The daily report books the pair as the update (core.episode_kinds).
            log.info("↪️ MaaEnd %s 是装新版 %s 后的自重启，后面那次 %s 已经成功：自己好了", rec.run_id,
                     rec.raw["maaend_update_restart"], later)
            _self_heal_red(eng, f"{rec.script} {rec.run_id} 装新版 {rec.raw['maaend_update_restart']} 后自重启",
                           f"后面 {later} 成功")
            return
        # Held, not dropped: a later success turns it into an update episode
        # (no alarm); no later success and the final alarm names the update. A
        # failure held already stays held instead (as _hold_restart keeps it): it is
        # what a later success heals or the final alarm names - replaced, its failed
        # tasks were lost (relay.log 10-12: 06-04-00's 协议空间 under 06-58-11).
        _mark_downtime(eng, rec)   # held like _hold_for_retry: marked before it is persisted
        if key not in eng._pending or (eng._pending[key].raw or {}).get("maaend_update_restart"):
            eng._pending[key] = rec
        eng._persist_pending()
        # Rescue and ship the evidence now, as _hold_for_retry does: MaaEnd clears
        # its own debug folder on its next start, and this record can still end
        # in the final alarm.
        eng._archive_maaend_evidence(rec)
        if _ship_evidence(eng, rec):
            eng._persist_pending()
        log.info("↪️ MaaEnd %s 是装新版 %s 后的自重启，先压着看后面的重试",
                 rec.run_id, rec.raw["maaend_update_restart"])
        return
    if rec.transitional:
        # An attempt AUTO-MAS recorded as a restart (collector._TRANSITIONAL: a game
        # update, an emulator that did not start, a stub with no log) and retried at
        # once. Nothing is pushed at this moment: the attempts after it decide. It is
        # held like a failure - unless an earlier failure of the same script is held
        # already, which stays (it is the one a later success heals or the final
        # alarm names). A later success moves the held record to the self-heal path
        # (_retry_healed): daily report only (what recovered by itself). A later
        # failure replaces it and is alarmed on as usual; no later attempt at all,
        # and the final alarm names this one (_flush_pending).
        _hold_restart(eng, rec, key)
        return

    if rec.script == "MAA" and not rec.ok:
        # MAA stopping at once for lack of sanity (「理智 17，需要 25」) fought
        # nothing and spent nothing; say that and stop there.
        until = rec.finished + timedelta(minutes=5) if rec.duration_known else None
        short = outcome.maa_sanity_short(_maa_app_log(eng.cfg.maa_dir, rec.started, until) or "")
        if short:
            rec.raw["maa_sanity_short"] = short
            # The ledger line was written above, before this was known: put it
            # there too, or the daily report (core.episode_kinds 「nosanity」) reads
            # the run as a plain failure.
            _mark_raw_on_ledger(eng, rec, "maa_sanity_short", short)
            # AUTO-MAS booked it as failed: the group hears of it, every such run, with
            # the two numbers. Not held and no make-up: a second run would meet the
            # same sanity.
            errs = _push_now(eng, day, "理智", rec.run_id, texts.MAA_SANITY_SHORT,
                             texts.maa_sanity_short_body(short["have"], short["cost"],
                                                         rec.started.astimezone(SERVER_TZ).strftime("%H:%M")))
            log.info("🟡 MAA 理智不够（%s/%s），没打，%s", short["have"], short["cost"],
                     "没推出去，下一轮再推" if errs else "已报群")
            return
    if rec.script == "MAA" and not rec.ok and eng._maintenance_today("明日方舟"):
        # A MAA failure on a day with a registered version update is still a
        # failure: pushed now, saying it is the update day, and not held for a
        # make-up (the evening shift runs it again anyway).
        rec.raw["maintenance_day"] = True
        _mark_raw_on_ledger(eng, rec, "maintenance_day", True)
        title, body = _failure_alarm(eng, rec, texts.UPDATE_DAY_NOTE)
        errs = _push_now(eng, day, "更新日", rec.run_id, title, body)
        log.info("❌ 更新日 MAA %s 没跑成，%s", rec.run_id, "没推出去，下一轮再推" if errs else "已报群")
        return
    # Every other failure - a MaaEnd round that failed on 自动采集 / 应急理智加强剂
    # alone included - is held, made up and alarmed on.
    _hold_for_retry(eng, rec, key)


def _hold_restart(eng, rec: RunRecord, key: tuple) -> None:
    """Hold an attempt AUTO-MAS recorded as a restart (see _handle) unless a failure
    of the same script is held already; nothing is pushed for it now.

    Its record can land after the record of the attempt that followed it (records
    become readable once their file stops changing): when the ledger already holds
    a success of the same script and user that started after it, it is healed
    already - not held, or the next flush would push a final alarm about a script
    that got through."""
    if later := _later_success(eng, rec):
        log.info("↪️ %s %s 是中途重启（%s），后面那次 %s 已经成功：自己好了，只进日报", rec.script, rec.run_id,
                 _restart_result(rec), later)
        _self_heal_red(eng, f"{rec.script} {rec.run_id} 中途重启", f"{_restart_result(rec)}；后面 {later} 成功")
        return
    if key not in eng._pending:
        eng._pending[key] = rec
        eng._persist_pending()
    log.info("↪️ %s %s 是中途重启（%s），AUTO-MAS 接着重试；先压着，看后面那次", rec.script, rec.run_id,
             _restart_result(rec))


def _flush_pending(eng) -> None:
    if getattr(eng, "_unsent_unresolved", None):
        from ark_relay.features.alarm import unresolved  # noqa: PLC0415
        unresolved.retry_unsent(eng)
    if not (eng._pending or eng._recovered):
        return

    # Wait only on the failed script's own retries, never on the rest of the queue.
    # AUTO-MAS writes a script's records once all its attempts are over, so by the
    # time one is held here its retries are normally spent; waiting for the whole
    # queue would hold an alarm behind every script after it.
    for rec in list(eng._recovered.values()):
        if eng._script_running(rec.script):
            continue
        day = run_day(rec)
        # Recovered by itself: AUTO-MAS's own retry, the rerun after an update
        # restart, or the relay's make-up (makeup.py: its success moved the held
        # failure here) got past it. Not pushed; the daily report says it - the
        # failed run's row (↻ 「后来在 HH:MM 那趟重试/补跑里做成了」 with its evidence
        # link, or ↪️ for an update's streak, core.episode_kinds), the run that got
        # through, and the make-up line (report.makeup_line). The user's words for
        # this are in relay/USER-SWITCHES.txt (this function's entry). The title
        # (texts.self_healed / healed_after_update / makeup_passed) only names the
        # log line.
        title = _healed_title(eng, rec, day)
        eng._recovered.pop((rec.script, rec.user), None)
        eng._persist_pending()   # only now is it safe to forget
        why = "、".join(rec.failed_tasks or []) or "没写失败项"
        log.info("%s（%s，跑了 %d 次）：自己好了，只进日报", title, why, _attempts(eng, rec, day))
        _self_heal_red(eng, f"{rec.script} {rec.run_id} {title}", why)

    for rec in list(eng._pending.values()):
        if eng._script_running(rec.script):
            continue
        if _update_restart_done(eng, rec):
            continue
        day = run_day(rec)
        attempts = _attempts(eng, rec, day)
        # Could not get into the game, with an official maintenance window or update
        # notice behind it (handle._mark_downtime, _confirm_unreachable):
        # every such record goes to the group, with that notice in the text; no
        # make-up (gameupdate re-runs it after the queue).
        raw = rec.raw or {}
        maint = raw.get("maintenance")
        if maint or (rec.script == "MaaEnd" and raw.get("maaend_unreachable")):
            hint = maint or raw.get("maaend_unreachable_why") or efstatus.update_hint()
            note = _evidence_note(eng, rec)      # ships the bundle first when the record has none
            page = raw.get("evidence_page") or ""
            from ark_relay.features.verify.collector_maaend import _UNREACHABLE_QUICK_SEC  # noqa: PLC0415
            body = (texts.cant_enter_body(rec.script, attempts, bool(maint), str(hint or ""),
                                          _UNREACHABLE_QUICK_SEC)
                    + (f"\n证据包：{page}" if page else f"\n{note}" if note else ""))
            if eng.notifier.send(texts.cant_enter(rec.script), body, alert=True):
                return  # if it cannot be sent, come back next tick
            eng._pending.pop((rec.script, rec.user), None)
            eng._persist_pending()
            eng.log_tails.pop(rec.run_id, None)
            log.info("⏸ %s 进不了游戏（尝试 %d 次），已报群", rec.script, attempts)
            continue
        if rec.script in ("MAA", "MaaEnd"):
            # A person would restart the game and run just the failed part once
            # more before calling it a fault (makeup.py). Held until the make-up is
            # over. Still failed, or no make-up for it -> the group hears of it now,
            # every time (unresolved.py). Went through -> recovered: the daily report
            # only, its make-up line and the failed run's row say it.
            from ark_relay.features.makeup import makeup  # noqa: PLC0415
            from ark_relay.features.alarm import unresolved  # noqa: PLC0415
            # MAA refused the config itself: no make-up can help, so it is refused
            # here and the alarm goes out on this tick, not after maybe_run's.
            makeup.refuse_rejected(eng, rec)
            verdict, phrase = unresolved.after_makeup(eng, rec)
            if verdict == unresolved.WAIT:
                continue
            if verdict == unresolved.PASSED:
                eng._pending.pop((rec.script, rec.user), None)
                eng._persist_pending()
                eng.log_tails.pop(rec.run_id, None)
                passed = texts.makeup_passed(unresolved.GAME[rec.script], unresolved.where(eng, rec)[1])
                log.info("%s（尝试 %d 次）：补跑走通了，只进日报", passed, attempts)
                _self_heal_red(eng, f"{rec.script} {rec.run_id} {passed}",
                               "、".join(rec.failed_tasks or []) or "没写失败项")
                continue
            if not _push_unresolved(eng, rec, phrase, attempts):
                return  # still on disk, retry next tick
            eng._pending.pop((rec.script, rec.user), None)
            eng._persist_pending()
            eng.log_tails.pop(rec.run_id, None)
            log.info("❌ %s 没处理好，已进群（%s；尝试 %d 次）", rec.script, phrase, attempts)
            continue
        # Every final failure is pushed, the same step failing again the same day
        # included.
        note = _evidence_note(eng, rec)
        title, body = core.format_failure(rec, _diagnosis(eng, rec))
        body = texts.failed_body_head(attempts) + _restart_note(rec) + body + (f"\n{note}" if note else "")
        errors = eng.notifier.send(title, body, alert=True)
        if errors:
            log.error("告警推送出错，保留待重发: %s", "；".join(errors))
            return  # still on disk, retry next tick
        eng._pending.pop((rec.script, rec.user), None)
        eng._persist_pending()   # only now is it safe to forget
        log.info("❌ %s 最终失败，告警已推送（尝试 %d 次）", rec.script, attempts)


# ---------- machine checks (machinecheck.py, event 「run」) ----------


def _judge_run(eng, rec: RunRecord, watch: _RunWatch) -> None:
    """machinecheck.judge(event 「run」) for a record just handled. A broken check or
    context is an ERROR of its own (it reaches the group), never a broken booking."""
    try:
        from ark_relay.features.selfcheck import machinecheck  # noqa: PLC0415
        try:
            version = str(eng.state.store.get("versions", "code") or "")
        except Exception:  # noqa: BLE001 - a version missing from the verdict is no reason to skip it
            version = ""
        machinecheck.judge(eng.cfg.state_dir, "run", _run_ctx(eng, rec, watch),
                           version=version, notifier=eng.notifier)
    except Exception:
        log.exception("上机核对没跑成（%s；记账照常）", rec.run_id)
    finally:
        _OUTCOME.pop(rec.run_id, None)
