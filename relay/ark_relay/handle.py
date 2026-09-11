"""Bookkeeping and alerting: once a run record lands, judge it, record it, keep the evidence, decide whether to push.

Split out of engine.py (2026-09-06, moved verbatim, no changes). The first
argument of every function here is the Engine instance, whose cfg / state /
notifier / _pending they read.
"""
from __future__ import annotations

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
from .config import SERVER_TZ, RunRecord

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
                checks = outcome.okww_checks(text, expect_nest=expect_nest)
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
                    "asst.log 里没有这一轮时间窗内的行，基建成败无从核对")],
                    "MAA")
            return outcome.summarize(outcome.maa_checks(maa_log), "MAA")
        if rec.script == "MaaEnd":
            shots = _maaend_new_shots(eng.cfg.maaend_dir, rec.started)
            # Read AUTO-MAS's history log together with MaaEnd's own app log:
            # the wrap-up marker only exists in the latter and task start/finish
            # only in the former, so missing either one misjudges the round.
            both = text + "\n" + _maaend_app_log(eng.cfg.maaend_dir, rec.started)
            return outcome.summarize(
                outcome.maaend_checks(both, shots), "MaaEnd")
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
    # A later success means AUTO-MAS got past it on its own. Report it
    # anyway - once for the whole event, not once per failed attempt.
    if (bad := eng._pending.pop(key, None)) is not None:
        eng._recovered[key] = bad
        eng._persist_pending()
        log.info("↩️ %s 重试后成功，改为自愈通知", rec.script)
    _weekly_gates(eng, rec)
    # AUTO-MAS saying 「这个脚本正常退出了」 does not mean it got the work done.
    # So check against the evidence before returning, and anything not done has
    # to be said out loud.
    # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_handle」
    if msg := eng._verify_outcome(rec):
        log.warning("⚠️ %s %s 有项目没干成：\n%s",
                    rec.script, rec.run_id, msg)
        # Onto the ledger too, or the evening report opens with 全绿 while this
        # very message said otherwise (2026-09-10, 自动采集 walked zero routes).
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        if not eng.state.mark_incomplete(day, rec.run_id, msg):
            log.warning("没能把「没干完」写回 %s 的账本，日报会少这一条", rec.run_id)
        eng.notifier.send(texts.ROUND_INCOMPLETE, msg, alert=True)
        _ship_evidence(eng, rec)
        return
    log.info("✅ %s %s（%d 分钟）静默记账",
             rec.script, rec.run_id, rec.duration_min)
    return


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
    _ship_evidence(eng, rec)
    log.info("⏳ %s 失败，暂不推送，等重试结果", rec.script)


def _ship_evidence(eng, rec: RunRecord) -> None:
    """Build the upstream-format bundle and push it off the machine; log the link.

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
        res = evidence.save_and_upload(eng.cfg, rec.script, rec.run_id, extra)
        if res.get("page"):
            log.info("🗂️ %s 证据包已上传（%d 个文件）→ %s", rec.run_id, len(res["uploaded"]), res["page"])
            eng.notifier.send(texts.EVIDENCE_SAVED,
                              texts.evidence_saved_body(rec.script, rec.started.astimezone(SERVER_TZ).strftime("%m-%d %H:%M"),
                                                        len(res["uploaded"]), res["page"]))
        else:
            log.warning("🗂️ %s 证据包没传上去：%s", rec.run_id, "；".join(res.get("errors") or ["没有文件"]))
    except Exception:
        log.exception("证据外送出错（不影响记账）")


def _handle(eng, rec: RunRecord) -> None:
    _append_ledger_once(eng, rec)
    key = (rec.script, rec.user)

    if rec.ok:
        _handle_success(eng, rec, key)
        return

    # "Superseded by the next round" is not a failure and does not enter the
    # pending queue. AUTO-MAS puts 「游戏更新成功，即将重启任务」 into
    # _OKWW_BUILTIN_FATAL alongside real faults, so every Wuthering Waves client
    # update produced one fake failure (the one the user named on 2026-08-28 as
    # needing a fix).
    if rec.transitional:
        log.info("↪️ %s %s 是中途重启（%s），不算失败",
                 rec.script, rec.run_id,
                 str(rec.raw.get("general_result")
                     or rec.raw.get("maa_result")
                     or rec.raw.get("maaend_result") or "").strip())
        return

    if rec.script == "MAA" and not rec.ok and eng._maintenance_today("明日方舟"):
        # Major version update day: failing because the package or assets are not
        # ready yet is not something a person has to act on; the evening shift
        # tries again
        log.warning("🟡 更新日 MAA 没跑成，晚班再试，不拉警报")
        rec.raw["maintenance_day"] = True
        return
    if rec.script == "MaaEnd" and rec.failed_tasks and set(rec.failed_tasks) <= eng.SOFT_FAILS:
        log.warning("🟡 %s 只是 %s 没做成（上游问题），记日报不拉警报",
                    rec.script, "、".join(rec.failed_tasks))
        return
    _hold_for_retry(eng, rec, key)


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


def _flush_pending(eng) -> None:
    if not (eng._pending or eng._recovered) or eng._scripts_running():
        return

    for rec in list(eng._recovered.values()):
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        attempts = sum(1 for e in eng.state.read_ledger(day)
                       if e["script"] == rec.script and e["user"] == rec.user)
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
        if eng.notifier.send(texts.self_healed(rec.script), body, alert=True):
            return  # keep it on disk; retry next tick
        eng._recovered.pop((rec.script, rec.user), None)
        eng._persist_pending()   # only now is it safe to forget
        eng._mark_alerted(day, key)
        log.info("⚠️ %s 自愈通知已推送", rec.script)

    for rec in list(eng._pending.values()):
        day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
        attempts = sum(1 for e in eng.state.read_ledger(day)
                       if e["script"] == rec.script and e["user"] == rec.user)
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
        key = eng._alert_key(rec)
        if eng._already_alerted(day, key):
            eng._pending.pop((rec.script, rec.user), None)
            eng._persist_pending()
            log.info("❌ %s 又在同一步失败（今天已告警过），只记日志不再推", rec.script)
            continue
        tail = eng.log_tails.pop(rec.run_id, "") or collector.log_tail(rec)
        diagnosis = summary.diagnose(eng.cfg, rec.script, rec.failed_tasks, tail)
        title, body = core.format_failure(rec, diagnosis)
        body = texts.failed_body_head(attempts) + body
        errors = eng.notifier.send(title, body, alert=True)
        if errors:
            log.error("告警推送出错，保留待重发: %s", "；".join(errors))
            return  # still on disk, retry next tick
        eng._pending.pop((rec.script, rec.user), None)
        eng._persist_pending()   # only now is it safe to forget
        eng._mark_alerted(day, key)
        log.info("❌ %s 最终失败，告警已推送（尝试 %d 次）", rec.script, attempts)
