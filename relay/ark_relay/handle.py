"""Bookkeeping and alerting: once a run record lands, judge it, record it, keep the evidence, decide whether to push.

Split out of engine.py (2026-09-06, moved verbatim, no changes). The first
argument of every function here is the Engine instance, whose cfg / state /
notifier / _pending they read.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import texts
from . import collector, core, efstatus, outcome, summary
from .config import SERVER_TZ, RunRecord, atomic_write_text

log = logging.getLogger("ark.handle")



def _okww_master_config(automas_dir: str | Path | None, name: str) -> dict:
    """Read the OK-WW config that is **actually in effect**.

    The copy in OK-WW's own directory is replaced wholesale by AUTO-MAS before a
    run and restored afterwards, so reading it after the fact reads a fake. The
    one actually in effect is under
    `<automas>/data/<script id>/Default/ConfigFile/`.
    The script id is not fixed, so just scan - on this machine only OK-WW has
    this directory structure.
    """
    if not automas_dir:
        return {}
    root = Path(automas_dir) / "data"
    if not root.is_dir():
        return {}
    for sid in root.iterdir():
        f = sid / "Default" / "ConfigFile" / f"{name}.json"
        if f.is_file():
            try:
                d = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and d:
                return d
    return {}



def _okww_nest_expected(automas_dir: str | Path | None) -> bool | None:
    """Whether this round was supposed to farm tacet nests. **Returns None, not False, when the config cannot be read.**

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_okww_nest_expected」。
    """
    nest = _okww_master_config(automas_dir, "NightmareNestTask")
    daily = _okww_master_config(automas_dir, "DailyTask")
    if not nest and not daily:
        return None
    if (nest.get("Only Farm These Nests") or "").strip():
        return True
    if daily.get("Farm Nightmare Nest for Daily Echo"):
        return True
    adds = daily.get("Additional Tasks to Run After Daily Task") or []
    return "Auto Farm all Nightmare Nest" in adds



# MAA's line-leading timestamp: [2026-08-30 09:09:41.495][INF]...
_MAA_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")

# How much of the tail to take. One round is roughly 30,000 lines / 6-7 MB, so
# 16 MB is plenty to cover a whole round.
_MAA_LOG_TAIL = 16 * 1024 * 1024



# What AUTO-MAS writes as the entire history log of a record it created only to
# close a retry round (real text, 2026-09-17 history/2026-09-17/endfield/MaaEnd-06-32-49.log,
# the whole file):
MAAEND_NOTHING_TO_RUN_LOG = "MaaEnd 没有可执行任务，请检查任务配置, 无日志记录"
MAAEND_NOTHING_TO_RUN = "没有可执行任务"


def _maaend_app_log(maaend_dir: "str | Path | None",
                    started: datetime) -> str:
    """The app log MaaEnd wrote **itself** for this round.

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_maaend_app_log」。
    """
    if not maaend_dir:
        return ""
    d = Path(maaend_dir) / "debug"
    if not d.is_dir():
        return ""
    cut = started.timestamp()
    out: list[str] = []
    # Filenames look like 2026-08-29-7.log; maafw* / go-service are framework
    # logs and are not read.
    for f in sorted(d.glob("20??-??-??-*.log")):
        try:
            if f.stat().st_mtime < cut:
                continue
            out.append(f.read_text(encoding="utf-8", errors="replace")[-200_000:])
        except OSError:
            continue
    return "\n".join(out)



def _maa_app_log(maa_dir: "str | Path | None", started: datetime,
                 until: "datetime | None" = None) -> "str | None":
    """The asst.log MAA wrote **itself** for this round, keeping only the lines inside this round's time window.

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_maa_app_log」。
    """
    if not maa_dir:
        return None
    f = Path(maa_dir) / "debug" / "asst.log"
    if not f.is_file():
        return None
    try:
        # One round alone is over 30,000 lines, so reading the whole file is
        # unnecessary; take the tail and then cut by time.
        size = f.stat().st_size
        with f.open("rb") as fh:
            if size > _MAA_LOG_TAIL:
                fh.seek(size - _MAA_LOG_TAIL)
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    # An upper bound is mandatory: a start with no end sweeps in lines from the
    # **later rounds** as well, which is charging this morning's error to last
    # night. The exception is `until` being None, where no upper bound is set -
    # the times on such a record are untrustworthy to begin with, and taking too
    # much beats cutting the whole round away.
    # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_maa_app_log」
    cut = started.strftime("%Y-%m-%d %H:%M:%S")
    top = until.strftime("%Y-%m-%d %H:%M:%S") if until else None
    out: list[str] = []
    keep = False
    for line in raw.splitlines():
        m = _MAA_TS.match(line)
        if m:
            # The timestamp is fixed-width, so lexical order is chronological
            # order and it can be compared directly here.
            ts = m.group(1)
            keep = ts >= cut and (top is None or ts <= top)
        # A line with no timestamp is a continuation of the previous one and
        # follows it - do not judge it on its own, or traceback lines get pulled
        # in unconditionally (this trap is recorded in arklog.py).
        if keep:
            out.append(line)
    # Not a single line inside the window = this round's log was not found,
    # which is just as uncheckable as "cannot read the file". Returning "" would
    # be read by the checks as "no errors at all", which is another false green.
    return "\n".join(out) if out else None



def _maaend_new_shots(maaend_dir: str | Path | None,
                      started: datetime) -> list[str]:
    """The on_error screenshot filenames that appeared during this round.

    MaaEnd does not report an error when it gets stuck, but a failed
    universal-navigation step saves an image - that image is the only evidence.
    """
    if not maaend_dir:
        return []
    d = Path(maaend_dir) / "debug" / "on_error"
    if not d.is_dir():
        return []
    cut = started.timestamp()
    return sorted(p.name for p in d.glob("*.png")
                  if p.stat().st_mtime >= cut)


# ---------- per record ----------

def _warn_if_evidence_stale(eng, rec: RunRecord, dst: Path) -> None:
    """The archived debug log is not necessarily from the failing run - say so plainly when it does not line up, rather than misleading the reader.

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_warn_if_evidence_stale」。
    """
    try:
        stamp = rec.run_id.rsplit("-", 3)[-3:]
        if len(stamp) != 3 or not all(x.isdigit() for x in stamp):
            return
        hh, mm, ss = (int(x) for x in stamp)
        started = hh * 3600 + mm * 60 + ss
        for f in dst.glob("*.log"):
            if f.name.startswith("automas-"):
                continue          # this one was taken by run_id, so it always lines up
            mt = datetime.fromtimestamp(f.stat().st_mtime, tz=SERVER_TZ)
            ended = mt.hour * 3600 + mt.minute * 60 + mt.second
            if ended < started:
                log.warning("⚠️ 证据里的 %s 最后写于 %s，早于这一轮开始的 %s，"
                            "多半是**别的轮次**的日志，别拿它当这次失败的依据",
                            f.name, mt.strftime("%H:%M:%S"),
                            f"{hh:02d}:{mm:02d}:{ss:02d}")
    except Exception:
        log.debug("证据时间范围检查失败", exc_info=True)


def _okww_log_file(okww_dir: "str | Path | None") -> "Path | None":
    """OK-WW's newest log. Say something when it is not found; never return None silently."""
    if not okww_dir:
        log.warning("okww_dir 没解析出来，OK-WW 的日志切片存不了")
        return None
    logs = Path(okww_dir) / "data" / "apps" / "ok-ww" / "working" / "logs"
    try:
        return max(logs.glob("*.log*"), key=lambda q: q.stat().st_mtime)
    except (OSError, ValueError):
        log.warning("OK-WW 的日志目录 %s 里没有日志", logs)
        return None


# Take a full-screen shot. **Must run in an interactive session** - the relay is
# a service running in session 0, which has no desktop at all, so shooting from
# here only ever yields a black image (memory relay-runs-in-session-0).
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
    from .preupdate_common import _PWSH7, _spawn_via_task  # noqa: PLC0415 - avoids an import cycle
    ps1 = Path(tempfile.gettempdir()) / f"ark-shot-{os.getpid()}.ps1"
    try:
        ps1.write_text(_SHOT_PS1.replace("%OUT%", str(out)), encoding="utf-8")
        _spawn_via_task(_PWSH7, ps1.parent,
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

    Hit on the morning shift of 2026-09-08: OK-WW failed three times in a row,
    every one of them upstream `ensure_main` failing to reach 「大世界 + 队伍」 and
    throwing `Please start in game world and in team!`.
    The only way to tell which screen the game was stuck on is to see what was on
    the screen at that moment - and OK-WW's debug screenshots are switched off,
    while the relay only archived evidence for MaaEnd at the time. The result was
    that **the log said 「等不到大世界」 and nothing whatsoever could say what was
    in the way**. On 08-26, with the same symptom, the real cause was a
    「选择复苏物品」 dialog blocking things for twenty minutes
    (docs/OKWW-STUCK-DIALOG.md), and that was only found because a person went and
    looked at the screen - we cannot depend on someone happening to be there.

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
        # below. On 2026-09-05 it was the .json in history that revealed the
        # failing task was 「基质刷取」.
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
    # Never entering the game at all is the signal that the client needs an
    # update: register it, and after the queue finishes update and re-run
    if (rec.raw or {}).get("maaend_unreachable"):
        from . import gameupdate  # noqa: PLC0415
        gameupdate.mark_pending(eng.cfg.state_dir, "终末地", "今天 MaaEnd 进不了游戏（客户端待更新）")
    if rec.script == "OK-WW" and not rec.ok and (rec.raw or {}).get("okww_unreachable"):
        from . import gameupdate  # noqa: PLC0415
        gameupdate.mark_pending(eng.cfg.state_dir, "鸣潮", "今天 OK-WW 等不到游戏窗口（客户端待更新）")
    if not rec.ok:
        # A failure that ran into official downtime: mark it, draw ⏸ in the daily
        # report, raise no alert, and after the queue wait for the servers to come
        # back and make the run up
        from . import gameupdate  # noqa: PLC0415
        if why := gameupdate.in_maintenance(eng.cfg.state_dir, rec.script, rec.started):
            rec.raw["maintenance"] = why


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
            return outcome.summarize(checks, "OK-WW")
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
                return outcome.summarize([outcome.Check(
                    "能读到 MAA 自己的日志", False,
                    f"maa_dir={eng.cfg.maa_dir}，"
                    "MAA 自己的日志里没有这一轮的记录，基建做没做成核对不了")],
                    "MAA")
            return outcome.summarize(outcome.maa_checks(maa_log), "MAA")
        if rec.script == "MaaEnd":
            # AUTO-MAS closes a retry round with one more record whose whole log
            # is MAAEND_NOTHING_TO_RUN_LOG - bookkeeping, not a run: no MaaEnd
            # process, no app log. Judging it as a run is how 2026-09-17 10:43
            # got a false ROUND_INCOMPLETE (the completion-marker check) pushed
            # to the group two seconds after the real run's log had that very
            # line: the record starts 2 s after the log's last write, so the
            # mtime cut in _maaend_app_log excluded that log.
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
            return outcome.summarize(
                outcome.maaend_checks(both, shots, own_log=own), "MaaEnd")
    except Exception as exc:
        log.exception("结果核对本身出错")
        # This used to just return None, i.e. "everything was done". Reporting
        # all green when the check itself crashed is the worst kind of bug in
        # this class: the moment something is wrong is exactly the moment not to
        # say nothing is. Bookkeeping is unaffected either way (this function
        # only decides whether to say one extra thing).
        return (f"{rec.script} 这一轮的结果核对没跑成（{type(exc).__name__}: "
                f"{exc}），所以「干成了没有」这次没人验过。")
    return None


def _mark_no_self_exit(eng, rec: RunRecord) -> None:
    """Book 「all tasks done, MaaEnd did not exit」 with how long it then sat idle.

    The idle span runs from the log's last line to AUTO-MAS's own result line in
    app.log (2026-10-01: 16:58:22 -> 17:27:43, 29 minutes); 0 when that line is
    not there to read.
    """
    from .collector import _automas_result_time  # noqa: PLC0415
    idle = 0
    if eng.cfg.history_dir and (ended := _automas_result_time(eng.cfg.history_dir, rec.script, rec.started)):
        idle = max(0, int((ended - rec.finished).total_seconds() // 60))
    rec.raw["maaend_no_self_exit"] = idle
    day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
    eng.state.mark_raw(day, rec.run_id, "maaend_no_self_exit", idle)
    log.warning("🟠 MaaEnd %s 任务全部完成，但跑完没自己退出（空等 %d 分钟）", rec.run_id, idle)


def _append_ledger_once(eng, rec: RunRecord) -> None:
    """Append this run to the day's ledger, without double-counting a replayed record.

    Its own step because bookkeeping has to be idempotent, while the judging and
    pushing below it can fail midway and send the whole record through from the
    start again - fenced off as one step, a replay simply skips it.
    """
    # mark_seen only happens after _handle returns, so a crash later in
    # this method (disk full during save_pending, annihilation copy2)
    # replays the record on every retry tick - and each replay used to
    # append the same run to the ledger again, inflating the daily report
    # and the "重试 N 次" counts. The ledger append itself must be
    # idempotent.
    day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
    if any(e.get("run_id") == rec.run_id for e in eng.state.read_ledger(day)):
        log.info("记录 %s 已在账上（上次处理中途出错的重试），跳过重记", rec.run_id)
    else:
        eng.state.append_ledger(rec)


def _weekly_gates(eng, rec: RunRecord) -> None:
    """The three weekly gates (weekly boss, weekly garden, annihilation): which one this run finished, and one line about it when it did.

    Its own step because the three blocks have exactly the same shape - look at
    the evidence, ask the weekly gate, say something only if there is something
    to say; they have nothing to do with the self-heal notice or the outcome
    check around them, and mixed together the lines are easy to read across.
    """
    # Only a run that genuinely fills the weekly quota counts: MAA still reports
    # Success! when it stops early for lack of sanity, and removing annihilation
    # on the strength of that means it is not run for the rest of the week and
    # the quota is never filled.
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
            # Written the same way as the annihilation branch: the two weekly
            # gates were always meant to have the same shape.
            # (On 2026-08-26 this was written as notes.append, and there is no
            # `notes` in this scope.)
            # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_handle」
            eng.notifier.send(texts.WEEKLY, msg)
    if (rec.raw.get("annihilation") and rec.raw.get("annihilation_done")
            and eng._annihilation):
        if msg := eng._annihilation.on_success(rec.finished):
            eng.notifier.send(texts.WEEKLY, msg)


def _handle_success(eng, rec: RunRecord, key: tuple) -> None:
    """Everything to do after AUTO-MAS reports that this round exited normally.

    Its own step because the success and failure paths share not one line: this
    one handles the self-heal notice, the weekly gates and the outcome check,
    while the failure one handles mid-round restarts, update days, soft failures
    and holding.
    """
    # The same 10-04 / 10-05 pair arriving the other way round: the held update
    # restart came after this round. If this round turns out to have got the
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
    if msg := eng._verify_outcome(rec):
        if after_done:
            _retry_healed(eng, rec, key)
        log.warning("⚠️ %s %s 有项目没干成：\n%s",
                    rec.script, rec.run_id, msg)
        # Onto the ledger too, or the evening report opens with 全绿 while this
        # very message said otherwise (2026-09-10, 自动采集 walked zero routes).
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        if not eng.state.mark_incomplete(day, rec.run_id, msg):
            log.warning("没能把「没干完」写回 %s 的账本，日报会少这一条", rec.run_id)
        # Bundle first, so the alarm carries the link (the round is over: this
        # alarm is the final word on it, and the daily row gets the link too).
        page = _ship_evidence(eng, rec)
        if rec.script in ("MAA", "MaaEnd"):
            _push_undone(eng, rec, msg, page)
            return
        if page:
            msg += f"\n\n证据包：{page}"
        eng.notifier.send(texts.ROUND_INCOMPLETE, msg, alert=True)
        return
    if after_done:
        eng._pending.pop(key, None)
        eng._persist_pending()
        _drop_update_after_done(eng, held, rec.run_id)
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


def _same_shift(eng, a: RunRecord, b: RunRecord) -> bool:
    from . import unresolved  # noqa: PLC0415
    try:
        return unresolved.where(eng, a) == unresolved.where(eng, b)
    except Exception:  # not knowing keeps the held record on its usual path
        log.warning("分不清 %s 和 %s 是不是同一班，按原样处理", a.run_id, b.run_id, exc_info=True)
        return False


def _drop_update_after_done(eng, rec: RunRecord, done: str) -> None:
    """Let go of an update restart whose shift's round (`done`) was already done.

    The ledger line stays; the mark on it is what makes the daily report book it
    as the update instead of a failure (core.episode_kinds), since no success
    follows it there.
    """
    _mark_raw_on_ledger(eng, rec, "maaend_update_after_done", done)
    log.info("↪️ MaaEnd %s 前面那趟已经做完（%s），这趟只是装新版 %s 重启，不算失败",
             rec.run_id, done, rec.raw.get("maaend_update_restart"))


def _push_undone(eng, rec: RunRecord, msg: str, page: str) -> None:
    """A MAA / MaaEnd round that exited normally with work left undone: no make-up
    is run for it, so the group hears of it now, once per shift (unresolved.py).
    MaaEnd's SOFT_FAILS alone stay in the daily report, like the failure path."""
    from . import unresolved  # noqa: PLC0415
    if rec.script == "MaaEnd" and unresolved.soft_only(msg, eng.SOFT_FAILS):
        log.info("⚠️ %s 只是 %s 没干完，只进日报", rec.script, unresolved.undone_label(msg))
        return
    day, shift = unresolved.where(eng, rec)
    game = unresolved.GAME[rec.script]
    body = texts.unresolved_undone_head(game, shift, unresolved.undone_label(msg), page) + "\n" + msg
    key = unresolved.alert_key(rec.script, shift)
    if not unresolved.send(eng, day, key, texts.unresolved_undone(game, shift), body):
        eng._unsent_unresolved.append((day, key, texts.unresolved_undone(game, shift), body))


def _hold_for_retry(eng, rec: RunRecord, key: tuple) -> None:
    """Wrapping up a genuine failure: queue it for pushing, persist it, rescue the evidence.

    Its own step because it is the only section of the failure path that stops
    judging and just cleans up, and because every step of it has to be finished
    before the next thing can go wrong - the order must not be changed.
    """
    # Hold it. Only alert once the script has stopped retrying entirely.
    eng._pending[key] = rec
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
    log.info("⏳ %s 失败，暂不推送，等重试结果", rec.script)


def _ship_evidence(eng, rec: RunRecord) -> str:
    """Build the upstream-format bundle and push it off the machine; log the link.

    Returns the link ("" when nothing went up) and leaves it on rec.raw and on
    the day's ledger line: the final alarm and the daily report carry it.

    The user, 2026-09-11: 「证据全都在电脑上面，都要我开机」. The bundle is the
    same files the project's own export button would produce (evidence.py),
    plus this round's AUTO-MAS log and record. Wrapped in try: shipping
    evidence must never block bookkeeping.
    """
    try:
        from . import evidence  # noqa: PLC0415
        extra = []
        if eng.cfg.history_dir:
            for suffix in (".log", ".json"):
                f = Path(eng.cfg.history_dir) / (rec.run_id + suffix)
                if f.is_file():
                    extra.append(f)
        # One run's window, widened a little on both ends (evidence.WINDOW_SLACK):
        # a bundle is always cut by time, never the whole debug folder.
        window = evidence.run_window(rec.started, rec.finished if rec.duration_known else None)
        # relay.log up to now: what the relay did about the run comes after it.
        res = evidence.save_and_upload(eng.cfg, rec.script, rec.run_id, extra, window=window,
                                       relay_until=time.time())
        if res.get("page"):
            log.info("🗂️ %s 证据包已上传（%d 个文件）→ %s", rec.run_id, len(res["uploaded"]), res["page"])
            rec.raw["evidence_page"] = res["page"]     # the failure alarm and the daily row carry it
            day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
            if not eng.state.mark_evidence(day, rec.run_id, res["page"]):
                log.warning("没能把证据链接写回 %s 的账本，日报那一行会没有链接", rec.run_id)
            eng.notifier.send(texts.EVIDENCE_SAVED,
                              texts.evidence_saved_body(rec.script, rec.started.astimezone(SERVER_TZ).strftime("%m-%d %H:%M"),
                                                        len(res["uploaded"]), res["page"]))
        else:
            log.warning("🗂️ %s 证据包没传上去：%s", rec.run_id, "；".join(res.get("errors") or ["没有文件"]))
        return res.get("page") or ""
    except Exception:
        log.exception("证据外送出错（不影响记账）")
        return ""


def _estop_overlap(eng, rec: RunRecord) -> str:
    """「HH:MM 停一切」 when this run overlaps a press of the red button, else ''.

    2026-09-30: the button stopped an OK-WW run at 09:47; AUTO-MAS recorded it
    as Success!, and the relay took that as the retry that fixed the 09:19 and
    09:30 failures - a 「重试后成功」 self-heal for a run nobody let finish.
    """
    try:
        from . import commands  # noqa: PLC0415
        return commands.estop_label(commands.estop_windows(eng.cfg.state_dir),
                                    rec.started, rec.finished)
    except Exception:
        log.exception("红按钮时间对不上（按正常记录处理）")
    return ""


def backfill_manual_stops(eng, now: datetime | None = None) -> int:
    """Book as manual stops the runs of today and yesterday that a recorded press
    overlaps but whose ledger line lacks raw.manual_stop. Returns how many.

    Run once per boot, after the self-update, so the new code does it. Covers a
    press recorded after its run was booked, or one that predates the window file
    (commands.ESTOP_SEED, merged here first). Each ledger file is rewritten once,
    atomically, with every other line - torn ones included - kept byte for byte.
    Idempotent: a patched line is skipped the next time.

    Also drops the alarms _handle would have dropped at record time: a held
    failure of the same script and user that started no later than the stopped
    run (its final alarm), and a self-heal notice the stopped run produced by
    reading as a success. The engine has already loaded both from disk in its
    constructor, so they are removed in memory and persisted.
    """
    from . import commands  # noqa: PLC0415
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    state_dir = eng.cfg.state_dir
    commands.merge_estop_seed(state_dir, now)
    windows = commands.estop_windows(state_dir)
    if not windows:
        return 0
    patched: list[dict] = []
    entries: list[dict] = []
    for day in sorted({(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in (1, 0)}):
        path = eng.state.ledger_path(day)
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        hit = False
        for i, ln in enumerate(lines):
            try:
                e = json.loads(ln)
                started = datetime.fromisoformat(str(e["started"]))
                finished = datetime.fromisoformat(str(e["finished"]))
            except (ValueError, TypeError, KeyError):
                continue          # a torn or foreign line stays exactly as it is
            entries.append(e)
            raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
            if raw.get("manual_stop"):
                continue
            if not (label := commands.estop_label(windows, started, finished)):
                continue
            raw["manual_stop"] = label
            e["raw"] = raw
            lines[i] = json.dumps(e, ensure_ascii=False)
            patched.append(e)
            hit = True
            log.info("⏹ 补记：%s %s（%s）这趟是停一切停掉的，记手动停止",
                     e.get("script"), e.get("run_id"), label)
        if hit:
            atomic_write_text(path, "\n".join(lines) + "\n")
    if patched:
        _drop_alarms_for_manual(eng, patched, entries)
    return len(patched)


def _drop_alarms_for_manual(eng, patched: list[dict], entries: list[dict]) -> None:
    """Drop held alarms tied to runs just booked as manual stops (see backfill_manual_stops)."""
    def _at(v) -> datetime:
        t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
        return t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)

    changed = False
    for e in patched:
        key = (e.get("script"), e.get("user"))
        stop_at = _at(e["started"])
        held = eng._pending.get(key)
        if held is not None and _at(held.started) <= stop_at:
            eng._pending.pop(key, None)
            changed = True
            log.info("⏹ 补记：%s %s 的最终告警不再推（后面那趟是停一切停掉的）", key[0], held.run_id)
        healed = eng._recovered.get(key)
        if healed is None or _at(healed.started) > stop_at:
            continue
        # A genuine success between the held failure and the stopped run is what
        # healed it; that notice stands.
        cured = any(x is not e and x.get("ok") and not (x.get("raw") or {}).get("manual_stop")
                    and (x.get("script"), x.get("user")) == key
                    and _at(healed.started) < _at(x["started"]) < stop_at
                    for x in entries)
        if not cured:
            eng._recovered.pop(key, None)
            changed = True
            log.info("⏹ 补记：%s %s 的重试后成功通知不发了（那次成功是停一切停掉的）",
                     key[0], healed.run_id)
    if changed:
        eng._persist_pending()


def _mark_update_restart(eng, rec: RunRecord) -> None:
    """A MaaEnd attempt spent on installing its own update is not a game failure.

    Marked before the ledger line is written, so the daily report reads it as an
    update episode. It is still held like a failure: if no later attempt gets
    through, the final alarm says the last retry went on the update.
    """
    if rec.script != "MaaEnd" or rec.ok or rec.transitional:
        return
    try:
        from .collector_maaend import update_restart_version  # noqa: PLC0415
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


def _hand_started(eng, rec: RunRecord) -> str:
    """The AUTO-MAS task id when a person started this run at AUTO-MAS itself, else ''.

    Never raises: not knowing keeps the run on the normal path (trigger.py).
    """
    try:
        from . import trigger  # noqa: PLC0415
        task = trigger.hand_started(eng.cfg.automas_dir, eng.cfg.state_dir, rec.started)
    except Exception:
        log.exception("判断是不是有人手动开的出错，按定时的处理")
        return ""
    return task.id if task else ""


def _handle_hand_started(eng, rec: RunRecord, key: tuple) -> None:
    """A run a person started from AUTO-MAS's own screen (trigger.py): report, never alarm.

    It stays in the ledger as a normal row - the daily report shows it, the user's
    rule of 2026-09-14 (core.split_test). What it does not do is what a scheduled run
    does on failure: no held failure, no final alarm, no 「这一轮没干完」. 10-03 00:40 -
    02:35 (JST) ten such runs of 自动肉鸽 were booked as the evening shift's failures.
    """
    if rec.ok:
        # The held failure is done with, but not as 「重试后成功」: nobody's retry healed
        # it, a person did (same as the manual_stop branch).
        if eng._pending.pop(key, None) is not None:
            eng._persist_pending()
            log.info("🖐 %s 之前压着的失败，有人手动跑成了，不再推最终报警", rec.script)
        _weekly_gates(eng, rec)
        if msg := eng._verify_outcome(rec):
            day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
            eng.state.mark_incomplete(day, rec.run_id, msg)
            log.info("🖐 %s %s 是有人在 AUTO-MAS 上手动开的，有项目没干成，记日报不报警：\n%s",
                     rec.script, rec.run_id, msg)
            return
        log.info("🖐 %s %s 是有人在 AUTO-MAS 上手动开的，跑完了，静默记账", rec.script, rec.run_id)
        return
    log.info("🖐 %s %s 是有人在 AUTO-MAS 上手动开的，没跑成，记日报不报警（任务 %s）",
             rec.script, rec.run_id, rec.raw.get("hand_started"))


def _handle(eng, rec: RunRecord) -> None:
    if stop := _estop_overlap(eng, rec):
        rec.raw["manual_stop"] = stop
    elif hand := _hand_started(eng, rec):
        rec.raw["hand_started"] = hand
    _mark_update_restart(eng, rec)
    _confirm_unreachable(eng, rec)
    _append_ledger_once(eng, rec)
    key = (rec.script, rec.user)
    if rec.script == "MaaEnd":
        # A MaaEnd record ending means AUTO-MAS's retry round (if any) is over:
        # whatever narrowing was done for it must go back before anything else.
        try:
            from . import collect_retry  # noqa: PLC0415
            if back := collect_retry.restore_master(eng.cfg):
                log.info("🔁 %s", back)
        except Exception:
            log.exception("母本路线改回出错")
        # Same for the make-up's narrowing (makeup.py): AUTO-MAS writes a
        # script's records once all its attempts are over, so the make-up run
        # and its own retries are done by now.
        try:
            from . import makeup  # noqa: PLC0415
            back, err = makeup.try_restore(eng.cfg, eng.notifier)
            if back:
                log.info("🔁 %s", back)
            elif err:
                # WARNING: the one alarm a person needs is makeup's own (both files
                # unreadable); an ERROR line here would be a second one (errwatch).
                log.warning("补跑的母本没能改回（%s）", err)
        except Exception:
            log.exception("补跑的母本改回出错")
    if rec.script in ("MAA", "MaaEnd"):
        # Is this the day's make-up run? Book its outcome before anything below
        # can return early (a red-button stop returns right away).
        try:
            from . import makeup  # noqa: PLC0415
            makeup.on_record(eng, rec)
        except Exception:
            log.exception("补跑结果记账出错")

    if rec.raw.get("manual_stop"):
        # Cut short by the red button: whatever AUTO-MAS wrote (Success! or a
        # failure) says nothing about the script. Not a self-heal, not a success
        # (no weekly gates, no outcome check), not a new failure to hold. The
        # failures before it stay in the ledger but no longer push a final alarm:
        # the operator stopped this on purpose.
        if eng._pending.pop(key, None) is not None:
            eng._persist_pending()
        log.info("⏹ %s %s 这趟是停一切停掉的（%s），记手动停止，不算自愈也不算成功",
                 rec.script, rec.run_id, rec.raw["manual_stop"])
        return
    if rec.raw.get("hand_started"):
        _handle_hand_started(eng, rec, key)
        return

    if rec.ok:
        _handle_success(eng, rec, key)
        return

    # "Superseded by the next round" is not a failure and does not enter the
    # pending queue. AUTO-MAS puts 「游戏更新成功，即将重启任务」 into
    # _OKWW_BUILTIN_FATAL alongside real faults, so every Wuthering Waves client
    # update produced one fake failure (the one the user named on 2026-08-28 as
    # needing a fix).
    if rec.raw.get("maaend_update_restart"):
        # The shift's round already got everything done: this attempt is MaaEnd
        # restarting into its new build, nothing more - not held, no make-up, no
        # alarm; its ledger line stays (10-04 09:51:26, 10-05 11:30:44 pushed it
        # as the final failure; the user, 10-05 13:07: 「他不要再报错了」).
        from . import unresolved  # noqa: PLC0415
        try:
            done = unresolved.done_in_shift(eng, rec)
        except Exception:  # not knowing keeps it held, as before
            log.warning("查不了这一班有没有做完的那趟，%s 照旧压着", rec.run_id, exc_info=True)
            done = ""
        if done:
            _drop_update_after_done(eng, rec, done)
            return
        # Held, not dropped: a later success turns it into an update episode
        # (no alarm); no later success and the final alarm names the update.
        eng._pending[key] = rec
        eng._persist_pending()
        log.info("↪️ MaaEnd %s 是装新版 %s 后的自重启，先压着看后面的重试",
                 rec.run_id, rec.raw["maaend_update_restart"])
        return
    if rec.transitional:
        log.info("↪️ %s %s 是中途重启（%s），不算失败",
                 rec.script, rec.run_id,
                 str(rec.raw.get("general_result")
                     or rec.raw.get("maa_result")
                     or rec.raw.get("maaend_result") or "").strip())
        return

    if rec.script == "MAA" and not rec.ok:
        # 2026-09-14: the Monday annihilation re-arm ran three times into
        # 「理智 17，需要 25」, each 20-second attempt was booked as a failure and
        # each shipped an evidence bundle. Nothing was fought, nothing was spent;
        # say that and stop there.
        until = rec.finished + timedelta(minutes=5) if rec.duration_known else None
        short = outcome.maa_sanity_short(_maa_app_log(eng.cfg.maa_dir, rec.started, until) or "")
        if short:
            log.warning("🟡 MAA 理智不够（%s/%s），没打，不算失败", short["have"], short["cost"])
            rec.raw["maa_sanity_short"] = short
            # The ledger line was written above, before this was known: put it
            # there too, or the daily report (core.episode_kinds 「nosanity」) reads
            # the run as a plain failure.
            _mark_raw_on_ledger(eng, rec, "maa_sanity_short", short)
            return
    if rec.script == "MAA" and not rec.ok and eng._maintenance_today("明日方舟"):
        # Major version update day: failing because the package or assets are not
        # ready yet is not something a person has to act on; the evening shift
        # tries again
        log.warning("🟡 更新日 MAA 没跑成，晚班再试，不拉警报")
        rec.raw["maintenance_day"] = True
        _mark_raw_on_ledger(eng, rec, "maintenance_day", True)
        return
    if rec.script == "MaaEnd" and rec.failed_tasks and set(rec.failed_tasks) <= eng.SOFT_FAILS:
        # Narrowing the master here (2026-09-12..14) never reached a retry: AUTO-MAS
        # writes all attempts' records at the end of the task, so the retry is
        # over before this runs. collect_watch.py does it from the live log.
        log.warning("🟡 %s 只是 %s 没做成（上游问题），记日报不拉警报",
                    rec.script, "、".join(rec.failed_tasks))
        return
    _hold_for_retry(eng, rec, key)


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
    raw["maaend_unreachable_shape"] = True
    why = ""
    try:
        from . import gameupdate  # noqa: PLC0415
        why = gameupdate.in_maintenance(eng.cfg.state_dir, rec.script, rec.started)
    except Exception:  # noqa: BLE001 - unknown is not evidence
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
    day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
    if not eng.state.mark_raw(day, rec.run_id, key, value):
        log.warning("没能把 %s 写回 %s 的账本", key, rec.run_id)


def _maintenance_today(eng, game: str) -> bool:
    try:
        from . import gameupdate  # noqa: PLC0415
        return game in gameupdate.windows(eng.state.dir)
    except Exception:  # noqa: BLE001
        return False


# One report per thing per day. The key = script + which step failed: failing
# repeatedly on the same step is the same thing, and only failing on a different
# step is a new thing worth another push.
# 来龙去脉见 docs/CODE-HISTORY.md「handle.py:(模块级)」
def _alert_key(eng, rec) -> str:
    return f"{rec.script}|{rec.user}|{','.join(sorted(rec.failed_tasks or ['?']))}"


def _alerted_file(eng, day: str) -> Path:
    """Old name, kept for the places that still reference it by name. The bookkeeping
    actually lives in state.json under marks.alerted:<day>."""
    return Path(eng.state.dir) / f"alerted-{day}.json"


def _already_alerted(eng, day: str, key: str) -> bool:
    got = eng.state.store.get("marks", f"alerted:{day}")
    return key in got if isinstance(got, list) else False


def _mark_alerted(eng, day: str, key: str) -> None:
    got = eng.state.store.get("marks", f"alerted:{day}")
    cur = list(got) if isinstance(got, list) else []
    if key not in cur:
        cur.append(key)
    eng.state.store.set("marks", f"alerted:{day}", cur)


def _attempts(eng, rec: RunRecord, day: str) -> int:
    """How many times this script really ran today: stubs AUTO-MAS wrote for an
    attempt that never ran (transitional, e.g. 「未捕获到日志」) are not attempts."""
    # An attempt MaaEnd spent installing its own update did run and did use up
    # one of AUTO-MAS's tries, so it counts (the final alarm said 「尝试 2 次」 for
    # 2026-10-01's three MaaEnd attempts otherwise).
    return sum(1 for e in eng.state.read_ledger(day)
               if e["script"] == rec.script and e["user"] == rec.user
               and (not e.get("transitional") or (e.get("raw") or {}).get("maaend_update_restart")))


def _diagnosis(eng, rec: RunRecord) -> str:
    """What is known about why `rec` failed: a known cause as it is, the model asked
    only about the rest."""
    tail = eng.log_tails.pop(rec.run_id, "") or collector.log_tail(rec)
    causes = (rec.raw or {}).get("maaend_fail_causes") or {}
    # An unconfirmed cause states what was seen, not why: still ask about it.
    from .collector_maaend import CLAIM_UNCONFIRMED  # noqa: PLC0415
    known = {k: v for k, v in causes.items() if v != CLAIM_UNCONFIRMED}
    rest = [t for t in rec.failed_tasks if t not in known]
    return "\n".join(x for x in (
        texts.known_cause(causes),
        summary.diagnose(eng.cfg, rec.script, rest, tail) if rest or not known else "",
    ) if x)


def _push_unresolved(eng, rec: RunRecord, makeup_phrase: str, attempts: int) -> bool:
    """A MAA / MaaEnd failure its make-up did not fix (or that got none): one alarm
    per game per shift (unresolved.py). False when the push failed (keep it held)."""
    from . import unresolved  # noqa: PLC0415
    day, shift = unresolved.where(eng, rec)
    key = unresolved.alert_key(rec.script, shift)
    if eng._already_alerted(day, key):
        log.info("❌ %s %s 这一班已经进过群，这次只记日志", rec.script, shift)
        return True
    game = unresolved.GAME[rec.script]
    raw = rec.raw or {}
    names = core._with_causes(list(rec.failed_tasks or []), raw.get("maaend_fail_causes"))
    stuck = "、".join(names[:3]) + ("…" if len(names) > 3 else "")
    page = raw.get("evidence_page") or ""
    # The link goes in the head; the rest of the body is the usual failure text without it.
    _, rest = core.format_failure(dataclasses.replace(rec, raw={k: v for k, v in raw.items() if k != "evidence_page"}),
                                  _diagnosis(eng, rec))
    body = (texts.unresolved_head(game, shift, makeup_phrase, stuck, page) + "\n"
            + texts.failed_body_head(attempts) + rest)
    if raw.get("maaend_unreachable_shape") and not raw.get("maaend_unreachable"):
        body += ("\n每个任务都在 30 秒内失败、一个没完成，看着像没进游戏；"
                 "但今天没有官方维护或更新公告，所以按故障报（游戏窗口、分辨率、游戏是否闪退要看）。")
    return unresolved.send(eng, day, key, texts.unresolved(game, shift), body)


def _flush_pending(eng) -> None:
    if getattr(eng, "_unsent_unresolved", None):
        from . import unresolved  # noqa: PLC0415
        unresolved.retry_unsent(eng)
    if not (eng._pending or eng._recovered):
        return

    # Wait only on the failed script's own retries, never on the rest of the queue.
    # AUTO-MAS writes a script's records once all its attempts are over, so by the
    # time one is held here its retries are normally spent; waiting for the whole
    # queue held 2026-10-01's OK-WW alarm (records landed 15:23) behind the whole of
    # MaaEnd's run, after six silent hours.
    for rec in list(eng._recovered.values()):
        if eng._script_running(rec.script):
            continue
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        attempts = _attempts(eng, rec, day)
        # Wuthering Waves client update -> restart -> successful re-run: an
        # episode, not a fault. On the morning shift of 2026-09-02 this pushed a
        # ⚠️「本次自愈，问题未解决」 that the user named as a false alarm.
        if core.episode_kinds(eng.state.read_ledger(day)).get(rec.run_id) == "update":
            eng._recovered.pop((rec.script, rec.user), None)
            eng._persist_pending()
            log.info("↪️ %s 游戏更新后重跑成功，不算故障，不报警", rec.script)
            continue
        key = "自愈|" + eng._alert_key(rec)
        if eng._already_alerted(day, key):
            eng._recovered.pop((rec.script, rec.user), None)
            eng._persist_pending()
            log.info("⚠️ %s 同一步的自愈今天已报过，只记日志", rec.script)
            continue
        _, body = core.format_failure(rec)
        # Self-healed is not the same as fine: the fault happened and will
        # happen again. Report it as an unresolved problem that this run
        # got past, never as "nothing to do".
        body = texts.self_healed_body(attempts) + body
        # Information, not an alarm: the run got through and the daily report
        # carries the retry (the user, 2026-09-14: the group is for the report
        # and real alarms only).
        if eng.notifier.send(texts.self_healed(rec.script), body):
            return  # keep it on disk; retry next tick
        eng._recovered.pop((rec.script, rec.user), None)
        eng._persist_pending()   # only now is it safe to forget
        eng._mark_alerted(day, key)
        # The title routes to the log only (notify._LOG_ONLY_CONTAINS): the
        # 2026-09-24 log said 「已推送」 for three notices nobody received.
        from .notify import route_of  # noqa: PLC0415
        log.info("⚠️ %s 自愈通知%s", rec.script,
                 "只记日志（日报里有）" if route_of(texts.self_healed(rec.script)) == "log" else "已推送")

    for rec in list(eng._pending.values()):
        if eng._script_running(rec.script):
            continue
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        attempts = _attempts(eng, rec, day)
        # Endfield never entered the game at all (server maintenance / client
        # update pending): not a fault anyone has to act on. Send one explanation
        # that day and raise no alert. The user, 2026-09-02: 「检测到
        # 服务器在维护时候就跳过，不报警」.
        maint = (rec.raw or {}).get("maintenance")
        if maint or (rec.script == "MaaEnd" and (rec.raw or {}).get("maaend_unreachable")):
            mkey = f"维护|{rec.script}"
            if not eng._already_alerted(day, mkey):
                hint = maint or efstatus.update_hint()
                body = texts.cant_enter_body(rec.script, attempts, bool(maint), hint or "")
                if eng.notifier.send(texts.cant_enter(rec.script), body):
                    return  # if it cannot be sent, come back next tick
                eng._mark_alerted(day, mkey)
            eng._pending.pop((rec.script, rec.user), None)
            eng._persist_pending()
            eng.log_tails.pop(rec.run_id, None)
            log.info("⏸ %s 进不了游戏（尝试 %d 次），按维护处理，不报警", rec.script, attempts)
            continue
        if rec.script in ("MAA", "MaaEnd"):
            # A person would restart the game and run just the failed part once
            # more before calling it a fault (makeup.py; the user, 2026-10-05 13:07:
            # 「他不要再报错了」). Held until the make-up is over; went through ->
            # dropped, the daily report says so. Still failed, or no make-up for it
            # -> the group hears of it now, once per shift (unresolved.py; the user,
            # 15:38, on why it stayed silent: 「你们不是没处理好吗？」).
            from . import unresolved  # noqa: PLC0415
            verdict, phrase = unresolved.after_makeup(eng, rec)
            if verdict == unresolved.WAIT:
                continue
            if verdict == unresolved.UNRESOLVED and not _push_unresolved(eng, rec, phrase, attempts):
                return  # still on disk, retry next tick
            eng._pending.pop((rec.script, rec.user), None)
            eng._persist_pending()
            eng.log_tails.pop(rec.run_id, None)
            log.info("❌ %s %s（尝试 %d 次）", rec.script,
                     "补跑走通了，只进日报" if verdict == unresolved.PASSED else f"没处理好，已进群（{phrase}）",
                     attempts)
            continue
        key = eng._alert_key(rec)
        if eng._already_alerted(day, key):
            eng._pending.pop((rec.script, rec.user), None)
            eng._persist_pending()
            log.info("❌ %s 又在同一步失败（今天已告警过），只记日志不再推", rec.script)
            continue
        title, body = core.format_failure(rec, _diagnosis(eng, rec))
        body = texts.failed_body_head(attempts) + body
        errors = eng.notifier.send(title, body, alert=True)
        if errors:
            log.error("告警推送出错，保留待重发: %s", "；".join(errors))
            return  # still on disk, retry next tick
        eng._pending.pop((rec.script, rec.user), None)
        eng._persist_pending()   # only now is it safe to forget
        eng._mark_alerted(day, key)
        log.info("❌ %s 最终失败，告警已推送（尝试 %d 次）", rec.script, attempts)
