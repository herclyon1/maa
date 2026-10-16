"""Machine checks judged from a run record right after the relay booked it (event 「run」).

handle._handle calls machinecheck.judge(state_dir, "run", ctx) once the record is
handled to the end. The context (handle._run_ctx) carries:

    rec, raw, log_text   the record, its raw dict, AUTO-MAS's run log for it
    outcome              what handle._verify_outcome found: {checks, msg, expect_nest,
                         only_nest} (None when it did not check this record)
    held_before, held    run ids held for a later push before and after the handling
    unsent               run ids of alarms that did not go out (retried next tick)
    alerts               the alarm copies (alertlog.py, state/alerts/<Beijing day>.jsonl)
                         written while the record was handled: what went to the group
    relay_errors         the relay's own WARNING / ERROR lines of the handling, each with
                         whether it was already delivered (errwatch.group_pushed) or
                         recovered - the others errwatch pushes to the group
    ledger               the record's day in the ledger
    test_run             inside a test window run-one.sh marked
    update_restarts      MaaEnd: {run_id: {version, started, done, held}} for the update
                         restarts of the record's day and the day before (handle._update_restarts)
    overlay              OK-WW: the overrides' report as on disk (okww_overlay.report_snapshot)
    maaend_dir           where MaaEnd's own logs are

A run inside a test window, one a person started at AUTO-MAS and one the red
button cut short is not an unattended run, so the checks of 「works unattended」
items say nothing about it (the user's rule of 2026-09-14, in CLAUDE.md: clicking
through once by hand is no verification; only the patch running unattended counts).

Evidence is the line the verdict rests on, quoted from the log or the state file;
when the line a check needs is not there, that is a FAIL quoting what is there.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.features.verify import collector_maaend as cm
from ark_relay.features.selfcheck import machinecheck as mc
from ark_relay.features.verify import outcome
from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ

PASS, FAIL = mc.PASS, mc.FAIL
LINE_CHARS = 160


def _r(status: str, evidence: str) -> mc.Result:
    return mc.Result(status, evidence)


def _script(ctx, name: str) -> bool:
    rec = ctx.get("rec")
    return getattr(rec, "script", None) == name


def _unattended(ctx) -> bool:
    raw = ctx.get("raw") or {}
    return not (ctx.get("test_run") or raw.get("hand_started") or raw.get("manual_stop"))


def _lines(text: str, pattern) -> list[str]:
    """Every line of `text` matching `pattern` (a regex or a plain substring)."""
    rx = pattern if isinstance(pattern, re.Pattern) else re.compile(re.escape(pattern))
    return [ln for ln in (text or "").splitlines() if rx.search(ln)]


def _cut(line: str) -> str:
    line = line.strip()
    return line if len(line) <= LINE_CHARS else line[:LINE_CHARS] + "…"


def _around(line: str, needle: str, width: int = 60) -> str:
    """The line's leading time stamp and the stretch around `needle` (framework lines run to kilobytes)."""
    i = line.find(needle)
    if i < 0 or len(line) <= LINE_CHARS:
        return _cut(line)
    stamp = m.group(0) if (m := re.match(r"^\[[^\]]+\]", line)) else ""
    return f"{stamp} …{line[max(0, i - width):i + len(needle) + width].strip()}…"


def _first(text: str, pattern) -> str:
    got = _lines(text, pattern)
    return _cut(got[0]) if got else ""


def _last(text: str, pattern) -> str:
    got = _lines(text, pattern)
    return _cut(got[-1]) if got else ""


def _after(text: str, marker: str) -> str:
    """The part of `text` from the last line holding `marker` on ('' when none)."""
    i = text.rfind(marker)
    return text[text.rfind("\n", 0, i) + 1:] if i >= 0 else ""


# ------------------------------------------------------------------ OK-WW

WEEKLY = "Teleport to Boss Weekly Challenge"
_WEEKLY_ANY = re.compile(r"周本|FarmEchoTask")
_WEEKLY_SHORT = ("结晶波片不足", "波片不足挡住开启挑战")
_WEEKLY_CAPPED = re.compile(r"本周周本次数已领满|收取物资次数已达到上限|本周剩余可收取次数[：:]\s*0\s*/")


@mc.check("#4", "鸣潮周本打完自己领到奖励（领完回读本周剩余次数少了一次）", "A", "run")
def _c4(ctx):
    if not _script(ctx, "OK-WW") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    if WEEKLY not in text:
        return None
    c = outcome.weekly_claims(text)
    if c["verified"]:
        return _r(PASS, _first(text, outcome.WEEKLY_CLAIM_OK))
    if not c["attempted"] and (_WEEKLY_CAPPED.search(text) or any(k in text for k in _WEEKLY_SHORT)):
        # Already capped this week, or the game refused for want of waveplates: no
        # claim to make, so nothing here says whether claiming works (the run's
        # own result check says the waveplate case).
        return None
    return _r(FAIL, f"{_weekly_why(text, c)}；日志最后一行周本：{_last(text, _WEEKLY_ANY) or '（没有）'}")


def _weekly_why(text: str, c: dict) -> str:
    """Why a weekly run has no confirmed claim, in the result check's words (outcome.okww_checks)."""
    if stopped := outcome._WEEKLY_FAILED.search(text):
        return "这一趟按失败结束：" + stopped.group(1).strip()
    if c["attempted"]:
        return outcome.weekly_unverified(c)
    if "teleport_to_boss prepared as" not in text and not _PAGE_KNOWN.search(text):
        return "没进本，一次没打"
    if not outcome._WEEKLY_FOUGHT.search(text):
        return "进了本，但日志里没有开打的记录：一次没打"
    return "周本打了，但没有领奖那一步：奖励没拿到"


DIALOG = "限时提前开放的剧情提示框，点确认前往"
_PAGE_KNOWN = re.compile(r"限时提前开放：确认后是(这个 Boss 的选等级页|队伍界面)")
_PAGE_UNKNOWN = re.compile(r"进本：.*这一屏认不出|限时提前开放确认后是传送地图")
_FOUGHT = re.compile(r"FarmEchoTask:enter combat|周本领奖：认出弹窗|周本领奖：回读确认领到")
_LEGIT_STOP = re.compile(r"本周周本次数已领满|结晶波片不足|波片不足挡住开启挑战")


@mc.check("#27", "鸣潮周本「确认前往」后读屏认出选等级页并进本（日常早班自动那趟）", "A", "run")
def _c27(ctx):
    if not _script(ctx, "OK-WW") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    if WEEKLY not in text or DIALOG not in text:
        return None
    tail = _after(text, DIALOG)
    page = _first(tail, _PAGE_KNOWN)
    if not page:
        rest = tail.splitlines()[1:]
        seen = _first(tail, _PAGE_UNKNOWN) or (_cut(rest[0]) if rest else "确认前往之后日志没有下一行")
        return _r(FAIL, f"点了确认前往，之后没认出选等级页：{seen}")
    if _FOUGHT.search(tail) or _LEGIT_STOP.search(tail):
        then = _first(tail, _FOUGHT) or _first(tail, _LEGIT_STOP)
        return _r(PASS, f"{page[:90]}…；之后：{then}")
    return _r(FAIL, f"认出了选等级页，但之后没开打：{_last(tail, _WEEKLY_ANY) or page}")


def _nest_settings(ctx) -> "tuple[bool | None, str]":
    o = ctx.get("outcome") or {}
    return o.get("expect_nest"), str(o.get("only_nest") or "").strip()


@mc.check("#5", "鸣潮残象聚落「只刷指定点位」的改动在真跑里贴上了", "A", "run")
def _c5(ctx):
    if not _script(ctx, "OK-WW") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    expect, only = _nest_settings(ctx)
    if not expect or not only or "NightmareNestTask" not in text:
        return None
    if outcome._NEST_FILTER_MISSING in text:
        return _r(FAIL, _first(text, outcome._NEST_FILTER_MISSING))
    if line := _first(text, outcome._NEST_FILTER_LINE):
        return _r(PASS, line)
    if opened := _first(text, "NightmareNestTask:opened gray_book_boss"):
        return _r(FAIL, f"打开了残象聚落页，日志里却没有「nightmare nest: 只刷 […]」（设置是只刷{only}）：{opened}")
    return None


_NEST_COMBAT = outcome._NEST_ENGAGED  # the verdict's own fight lines
_NEST_FARMED_LABEL = "残象聚落"


def _nest_verdict(ctx):
    for c in (ctx.get("outcome") or {}).get("checks") or []:
        if c.label.startswith("残象聚落") and not c.label.startswith(("残象聚落只刷", "残象聚落没进")):
            return c
    return None


def _nest_step(ctx) -> str:
    for s in (ctx.get("raw") or {}).get("okww_steps") or []:
        if s.startswith(("残象聚落", "梦魇巢穴")):
            return s
    return ""


@mc.check("#25", "鸣潮残象聚落只有真进了战斗才算刷了", "A", "run")
def _c25(ctx):
    if not _script(ctx, "OK-WW") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    verdict, step = _nest_verdict(ctx), _nest_step(ctx)
    if verdict is None and not step:
        return None
    combat = _first(text, _NEST_COMBAT)
    # Booked as farmed: the result check's plain 「残象聚落」 that is ok, or the daily
    # step that is the bare name (any note in brackets says it was not farmed),
    # the adapted-filter note excepted.
    plain = re.sub(r"（只刷指定点位的过滤按 OK-WW 新版适配，请核对）$", "", step)
    booked = (verdict is not None and verdict.ok and verdict.label == _NEST_FARMED_LABEL) \
        or plain in ("残象聚落", "梦魇巢穴")
    if booked and not combat:
        seen = _last(text, re.compile(r"nightmare nest|NightmareNestTask")) or "（巢穴任务一行都没有）"
        return _r(FAIL, f"一次没进战斗，却记成刷了（结果核对：{verdict.label if verdict else '—'}，"
                        f"日报：{step or '—'}）；巢穴最后一行：{seen}")
    if combat:
        return _r(PASS, combat)
    why = verdict.detail if verdict is not None else step
    line = _first(text, outcome._NEST_UNREACHABLE) or _first(text, outcome._NEST_ALL_FULL) \
        or _first(text, outcome._NEST_FILTER_MISSING) or _last(text, "NightmareNestTask")
    return _r(PASS, f"没进战斗，也没记成刷了（{why}）：{line or '—'}")


FIND_NEST = "NightmareNestTask.find_nest"
# A report written this long before the run's first line still belongs to its start
# (AUTO-MAS starts OK-WW first, the overrides run as ok-script loads).
_REPORT_EARLY = timedelta(minutes=5)


def _log_says(text: str) -> str:
    if outcome._NEST_FILTER_MISSING in text:
        return "没装上"
    if outcome._NEST_ADAPTED in text:
        return "按新版适配装上"
    if outcome._NEST_FILTER_LINE.search(text):
        return "装上"
    return ""


def _report_says(rep: dict) -> str:
    if rep.get("error"):
        return "出错（一条都没生效）"
    whats = lambda key: {str((x or {}).get("what")) for x in rep.get(key) or [] if isinstance(x, dict)}  # noqa: E731
    if FIND_NEST in whats("adapted"):
        return "按新版适配装上"
    if FIND_NEST in whats("skipped"):
        return "没装上"
    return "装上" if FIND_NEST in (rep.get("applied") or []) else "没装上"


@mc.check("#26", "鸣潮 find_nest 装没装上：这一趟日志和覆盖层报告说的一样", "A", "run")
def _c26(ctx):
    if not _script(ctx, "OK-WW") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    log_says = _log_says(text)
    if not log_says:
        return None
    rec = ctx["rec"]
    rep = ctx.get("overlay") or {}
    if not rep:
        return _r(FAIL, f"日志说 find_nest {log_says}，覆盖层报告（ark-okww-overlay.json）读不到")
    try:
        written = datetime.fromisoformat(str(rep.get("written")))
    except (TypeError, ValueError):
        return _r(FAIL, f"覆盖层报告没有写入时间：{str(rep)[:120]}")
    if written > rec.finished + timedelta(minutes=1):
        return None          # a later OK-WW start rewrote it; that start's own run is judged
    if written < rec.started - _REPORT_EARLY:
        return _r(FAIL, f"这一趟 OK-WW 启动没写覆盖层报告（盘上那份是 {written:%m-%d %H:%M:%S} 写的）；"
                        f"日志说 find_nest {log_says}")
    rep_says = _report_says(rep)
    line = (_first(text, outcome._NEST_FILTER_MISSING) or _first(text, outcome._NEST_ADAPTED)
            or _first(text, outcome._NEST_FILTER_LINE))
    ev = f"日志：{line}；覆盖层报告（{written:%H:%M:%S} 写）：find_nest {rep_says}"
    same = rep_says == log_says or (log_says == "装上" and rep_says == "按新版适配装上")
    return _r(PASS if same else FAIL, ev if same else "对不上——" + ev)


# ------------------------------------------------------------------ MaaEnd

SEEN_FILE = "machinecheck-runs.json"


def _state_get(state_dir, key: str):
    """One key of state/machinecheck-runs.json; None when missing or unreadable."""
    try:
        return json.loads((Path(state_dir) / SEEN_FILE).read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _state_set(state_dir, key: str, value) -> None:
    """Set one key of state/machinecheck-runs.json; a failed write is dropped."""
    from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
    f = Path(state_dir) / SEEN_FILE
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data[key] = value
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(f, json.dumps(data, ensure_ascii=False))
    except OSError:
        pass


def _seen(state_dir, cid: str) -> set:
    """Run ids check `cid` has given its verdict on already."""
    got = _state_get(state_dir, cid)
    return set(got) if isinstance(got, list) else set()


def _mark_seen(state_dir, cid: str, run_ids: list) -> None:
    """Add `run_ids` to check `cid`'s seen list, keeping the last 50."""
    _state_set(state_dir, cid, (list(_state_get(state_dir, cid) or []) + list(run_ids))[-50:])


def _about_restart(row: dict, run_id: str, version: str) -> bool:
    """Whether a group alarm copy is about the MaaEnd update restart `run_id`: it names
    the record, or the build it restarted into (every failure text of such a record
    says 「MaaEnd 装新版 <build> 后自己重启」, handle._mark_update_restart)."""
    title, text = str(row.get("title") or ""), str(row.get("text") or "")
    stem = run_id.rsplit("/", 1)[-1]
    return (row.get("evidence_run") == run_id or stem in title or stem in text
            or bool(version) and f"装新版 {version}" in title + text)


def _update_restart_check(ctx, cid: str):
    """#6 / #24a: a MaaEnd attempt spent restarting into its new build, in a shift whose
    round already got everything done, ends without any alarm about it: none in
    the copies of what went to the group (state/alerts, errwatch's pushes included)
    since it started, and no relay WARNING / ERROR naming it in this handling.

    Judged once per restart, once it is settled - no longer held for a later push
    (a held one is let go at the push step, handle._update_restart_done). Every
    restart of the batch is judged before the verdict: they are all marked seen
    here, so one returned early on the first FAIL (until 2026-10-13) left the
    others never judged."""
    if not _script(ctx, "MaaEnd"):
        return None
    state_dir = ctx.get("state_dir")
    seen = _seen(state_dir, cid)
    todo = {rid: x for rid, x in (ctx.get("update_restarts") or {}).items()
            if x.get("done") and not x.get("held") and rid not in seen}
    if not todo:
        return None
    _mark_seen(state_dir, cid, list(todo))
    passed, failed = [], []
    for rid, x in todo.items():
        stem, version = rid.rsplit("/", 1)[-1], str(x.get("version") or "")
        head = f"{stem} 装新版 {version} 后自己重启，同班 {str(x['done']).rsplit('/', 1)[-1]} 已经做完"
        try:
            since = datetime.fromisoformat(str(x.get("started")))
        except ValueError:
            since = ctx["rec"].started
        if rows := [a for a in _day_alerts(state_dir, since) if _about_restart(a, rid, version)]:
            failed.append(f"{head}，却进了群：{rows[0].get('ts')} 「{rows[0].get('title')}」")
            continue
        noisy = [e for e in ctx.get("relay_errors") or []
                 if stem in e.get("msg", "") and not (e.get("pushed") or e.get("recovered"))]
        if noisy:
            failed.append(f"{head}，中继却记了一条会进群的报错：{_cut(noisy[0]['msg'])}")
            continue
        passed.append(head)
    if failed:
        return _r(FAIL, "；".join(failed))
    return _r(PASS, "；".join(passed) + "：放下了，报警抄送里没有它，也没记报错")


@mc.check("#6", "终末地做完以后装新版自己重启，不再报「最终失败」也不进群", "A", "run")
def _c6(ctx):
    return _update_restart_check(ctx, "#6")


@mc.check("#24a", "三处误报修复之一：终末地做完后装新版重启不进群", "A", "run")
def _c24a(ctx):
    return _update_restart_check(ctx, "#24a")


def _task_window(text: str, task: str) -> "tuple[datetime, datetime] | None":
    return cm.task_times(text).get(task)


ENV = "环境监测"
# Where the framework-log stretch of each 环境监测 run is kept, newest ENV_KEEP files.
ENV_DIR = "machinecheck-env"
ENV_KEEP = 10
ENV_LINES = 4000          # head and tail kept of a longer stretch
# 环境监测 runs in a row with no framework-log lines in their window before that
# missing evidence is a FAIL of its own (MaaFW writes maafw.log on every run).
ENV_MISS_FAIL = 2
_FW_NODE = re.compile(r'"name":"([^"]+)"')
_FW_ENTRY = re.compile(r'"entry":"([^"]+)"')


def _keep_env_lines(state_dir, rec, t0: datetime, t1: datetime, lines: list[str]) -> str:
    """Write the stretch to state/machinecheck-env/<run>.log; returns that path under the state folder."""
    from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
    d = Path(state_dir) / ENV_DIR
    name = rec.run_id.replace("/", "_") + ".log"
    body = lines
    if len(lines) > ENV_LINES:
        half = ENV_LINES // 2
        body = lines[:half] + [f"…（中间 {len(lines) - ENV_LINES} 行没留）…"] + lines[-half:]
    head = f"# {rec.run_id} 环境监测 {t0:%Y-%m-%d %H:%M:%S} → {t1:%H:%M:%S}，框架日志 {len(lines)} 行"
    try:
        d.mkdir(parents=True, exist_ok=True)
        atomic_write_text(d / name, "\n".join([head, *body]) + "\n")
        for old in sorted(d.glob("*.log"), key=lambda f: f.stat().st_mtime)[:-ENV_KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        return ""
    return f"{ENV_DIR}/{name}"


@mc.check("#7", "终末地环境监测那一段的框架日志每趟都收下来（拿到真实样本、定下判据之前只收不判）", "B", "run")
def _c7(ctx):
    """Capture only. Whether 环境监测 did its job cannot be told yet: it writes no line
    of its own in the AUTO-MAS log even on a run that took 110 s (2026-09-04), and the
    repo holds no framework-log sample and no pipeline of it (only its locale strings:
    per-route 「…任务失败」 and 「当前任务尚未适配，仅接取并追踪」). So each run's
    framework-log stretch from its 「任务开始」 to its 「任务完成」 is kept in
    state/machinecheck-env/ and named in the daily section (PASS = captured, never
    pushed), until a real sample states what failing looks like. No lines in the
    window: not judged; ENV_MISS_FAIL runs in a row without them is a FAIL."""
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    raw = ctx.get("raw") or {}
    span = _task_window(text, ENV)
    if span is None or ENV in (raw.get("maaend_tasks_skipped") or {}):
        return None
    t0, t1 = span
    state_dir = ctx.get("state_dir")
    lines, why = cm.maafw_window(ctx.get("maaend_dir"), t0, t1)
    if not lines:
        misses = int(_state_get(state_dir, "#7-miss") or 0) + 1
        _state_set(state_dir, "#7-miss", misses)
        if misses >= ENV_MISS_FAIL:
            return _r(FAIL, f"连续 {misses} 趟环境监测（这一趟 {t0:%m-%d %H:%M:%S}→{t1:%H:%M:%S}）"
                            f"那一段的框架日志都没有：{why}")
        return None
    _state_set(state_dir, "#7-miss", 0)
    kept = _keep_env_lines(state_dir, ctx["rec"], t0, t1, lines)
    nodes = list(dict.fromkeys(n for ln in lines for n in _FW_NODE.findall(ln)))
    entries = list(dict.fromkeys(n for ln in lines for n in _FW_ENTRY.findall(ln)))
    secs = int((t1 - t0).total_seconds())
    shot = (raw.get("tasks_shot_files") or {}).get(ENV)
    return _r(PASS, f"只收不判：环境监测 {secs} 秒（{t0:%H:%M:%S}→{t1:%H:%M:%S}），框架日志 {len(lines)} 行"
                    + (f"，任务 {'、'.join(entries[:3])}" if entries else "")
                    + f"，节点 {len(nodes)} 个" + (f"：{'、'.join(nodes[:6])}" + ("…" if len(nodes) > 6 else "") if nodes else "")
                    + (f"；全文 {kept}" if kept else "；全文没存下")
                    + (f"；结束截图 {shot}" if shot else ""))


SHOT_TASKS = ("赠送干员礼物", "装备制造", "转交委托", "环境监测")
# What each task's own run in MaaFW's log has to show. MaaEnd's AUTO-MAS log has only
# 「任务开始」 / 「任务完成」 for these four; the framework log names every step that
# succeeded (maaend_fwlog.task_trail). Steps from MaaEnd's pipeline
# (github.com/MaaEnd/MaaEnd, branch v2, assets/resource/pipeline/), checked against
# the runs of 2026-10-07..10-13 and 10-16:
#   entry  - the task MXU posts (Tasker.Task.Starting "entry");
#   did    - (step, what it means): the task did its job when one of these succeeded;
#   none   - (step, what it means): the task found nothing to do, a normal end
#            (资源不足 / 已领满 are normal states, not failures);
#   needs  - for a `none` that is told by steps that did run, every one of these.
# Gift: GiftOperatorGiftFlow.json - GiftOperatorConfirmGift 「点击赠送按钮」 (once on
#   every 10-08..10-16 run), GiftOperatorGiftFull 「赠送已满」.
# Gear: GearAssembly/GearAssembly.json - GearAssemblyClickProduceBtn 「点击制作按钮」
#   (once a run, followed by SceneNoticeRewardsConfirm), GearAssemblyCheckMaterialEnough
#   「检测背包是否已满，背包已满直接结束」, GearAssemblyCheckFailedAndFinish 「检查制作失败，退出任务」.
#   10-08 10:34:11-10:34:16 ran only the scene check, which failed and stopped MaaEnd (ABORT_STEP).
# Delivery: DeliveryJobs/TransferJob.json - DeliveryJobsConfirmTaskTransfer (5 a run in the
#   mornings); a region loop (Region/ValleyIV.json, Wuling.json) tries every depot's
#   job and cargo and falls back to DeliveryJobsLoop when none is there: the re-runs
#   of 10-08 10:37 and 10-12 11:03 ran both region loops and transferred nothing.
# Environment: EnvironmentMonitoring/TakePhoto.json - EnvironmentMonitoringTakePhoto
#   (10-08 09:42, 10-10, 10-12 10:1x took one job each; the step succeeds twice a job,
#   so no count is said); Terminals.json - each
#   terminal's loop tries all its jobs; on 10-08 10:38, 10-11, 10-12 11:04, 10-13 and
#   10-16 both terminal loops ran, no job was taken and the task ended in 6-8 s.
SHOT_RULES = {
    "赠送干员礼物": {"entry": "GiftOperatorMain",
                 "did": (("GiftOperatorConfirmGift", "点了「赠送」{n} 次"),),
                 "none": (("GiftOperatorGiftFull", "干员的礼物已经送满"),)},
    "装备制造": {"entry": "GearAssemblyStart",
              "did": (("GearAssemblyClickProduceBtn", "点了「制作」{n} 次"),),
              "none": (("GearAssemblyCheckMaterialEnough", "背包已满，没法再做"),
                       ("GearAssemblyCheckFailedAndFinish", "材料不够，做不了"))},
    "转交委托": {"entry": "DeliveryJobsMain",
              "did": (("DeliveryJobsConfirmTaskTransfer", "确认转交了 {n} 单"),),
              "none": (("", "两个地区都走了一遍，没有可转交的委托"),),
              "needs": ("DeliveryJobsValleyIVLoop", "DeliveryJobsWulingLoop")},
    "环境监测": {"entry": "EnvironmentMonitoringMain",
              "did": (("EnvironmentMonitoringTakePhoto", "接了委托、拍了监测照片"),),
              "none": (("", "两个监测终端都看过了，没有可接的委托"),),
              "needs": ("OutskirtsMonitoringTerminalLoop", "MarkerStoneMonitoringTerminalLoop")},
}
# Runs in a row with none of the four in MaaFW's log before that is a FAIL of its own
# (as #7: MaaEnd clears its debug folder when it restarts).
SHOT_MISS_FAIL = 2
# MaaEnd's own abort: a failed scene check (SceneImageCheck.json, e.g.
# __SceneImageCheckModFailedFinish) goes next to this node, which stops the whole task
# chain through MaaFW's PostStop (SceneLoading.json 「运用 poststop 接口停止整个任务链」).
# 2026-10-08 10:34:16 (MaaEnd-06-31-06): 装备制造's check found the UID line cut short,
# MaaEnd said so in its own log (「UID显示不完整，…影响识别」, the line _ABORT_WORDS
# words plainly), MaaFW logged
# __SceneImageCheckModFailedFinish -> __SceneCheckAbortPipeline, GearAssemblyStart
# Succeeded, MaaTaskerPostStop; MXU logged 「自动执行任务完成，关闭自身」 and the
# 「停止任务」 lines are that stop. AUTO-MAS sent no stop (its MaaEnd update had ended at
# 10:30:43). MaaFW books the task Succeeded, so the abort is read from this step. It is
# no known normal state and no other check reports it: #28 fails on it.
ABORT_STEP = "__SceneCheckAbortPipeline"


def _shot_verdict(rule: dict, trail: dict) -> "tuple[bool, str]":
    """(did its job or found nothing to do, what the framework log shows)."""
    nodes = trail["nodes"]
    if nodes.get(ABORT_STEP):
        return False, "终末地自己检查画面没过，把后面的任务全停了，这一项没做成"
    if trail["result"] == "Failed":
        return False, "终末地自己记的结果是失败"
    did = [w.format(n=nodes[s]) for s, w in rule["did"] if nodes.get(s)]
    if did:
        return True, "、".join(did)
    for step, word in rule["none"]:
        if step and nodes.get(step):
            return True, word
        if not step and all(nodes.get(x) for x in rule.get("needs", ())):
            return True, word
    return False, f"终末地自己的记录里只走了 {sum(nodes.values())} 步，没有做成的一步，也没有「没东西可做」的结果"


_LOG_LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[.\d]*\] (.+)$", re.M)
# MaaEnd's own lines in a task's window that are not its reason: the task's start and
# end, and the scene check's standing note (2026-10-08 10:34:14.623).
_NOT_REASON = re.compile(r"^任务(开始|完成)[:：]|^正在检查画面")


def _abort_said(text: str, t0: datetime, t1: datetime) -> "tuple[str, datetime | None]":
    """MaaEnd's last own line inside the task's window t0..t1 (whole seconds, as
    task_times gives them) that is not a task start / end, and its time: why it
    stopped itself (2026-10-08 10:34:16.230 「UID显示不完整，…影响识别」);
    ("", None) when there is none."""
    said, when = "", None
    for m in _LOG_LINE.finditer(text):
        at = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        line = m.group(2).strip()
        if t0 <= at <= t1 and line and not _NOT_REASON.search(line):
            said, when = line, at
    return said, when


# MaaEnd's reasons said in plain words, where its own line carries English
# (texts.plain): (part of its line, what it means).
_ABORT_WORDS = (
    ("UID显示不完整", "左上角的账号编号显示不全，它说开着隐藏账号编号的模组会挡住左上方的字，认不出画面"),
)


def _abort_why(text: str, t0: datetime, t1: datetime) -> str:
    """", 原因…" for the evidence line: MaaEnd's own line, verbatim when it is plain
    Chinese, else its _ABORT_WORDS meaning, else where to read it."""
    from ark_relay.core import texts  # noqa: PLC0415
    line, at = _abort_said(text, t0, t1)
    if not line:
        return ""
    for part, meant in _ABORT_WORDS:
        if part in line:
            return f"，它记的原因：{meant}"
    if not texts.plain(line):
        return f"，它记的原因：「{line}」"
    return f"，原因写在终末地自己记的 {at:%H:%M:%S} 那一行"


def _shot_note(state: Path, rel: str, ended) -> str:
    """The desktop picture of this task, said for what it is: task_shots takes it after
    the task's end event through the desktop agent, 5-8 s late (2026-10-08, -11, -16:
    file times against file names), while MaaEnd posts the next task within 2 ms and
    its first input lands 0.1-1.5 s later (maafw.log 2026-10-16). So it shows the
    next task, never this one's result screen."""
    p = state / rel
    try:
        taken = datetime.fromtimestamp(p.stat().st_mtime)
    except (OSError, ValueError):
        return ""
    where = f"{Path(rel).parent.as_posix()} 里 {p.stem[:6]} 那张"
    if ended is None:
        return f"桌面截图 {where} 只作参考"
    late = (taken - ended).total_seconds()
    if late <= 0:
        return f"桌面截图 {where} 是它结束前拍的"
    return f"桌面截图 {where} 是它结束后 {late:.0f} 秒才拍到的，那时下一个任务已经开始，只作参考"


@mc.check("#28", "终末地送礼/装备制造/转交委托/环境监测每趟在终末地自己的记录里看得到做成了（或没东西可做）", "A", "run")
def _c28(ctx):
    """Judged from MaaFW's own steps of each task (SHOT_RULES), not from the desktop
    picture. Until 2026-10-16 this passed when the picture file existed, and the
    pictures of 10-08 showed the next task: 093302-赠送干员礼物.png the 装备制造 page,
    093322-装备制造.png 拜访好友, 103416-装备制造.png the bare desktop after MaaEnd
    stopped itself (ABORT_STEP; verify ledger #28). The picture is still named, with how
    late it was."""
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    raw = ctx.get("raw") or {}
    skipped = raw.get("maaend_tasks_skipped") or {}
    times = cm.task_times(text)
    done = [t for t in SHOT_TASKS if t in times and t not in skipped]
    if not done:
        return None
    from ark_relay.features.verify import maaend_fwlog  # noqa: PLC0415
    events = maaend_fwlog.task_events(ctx.get("maaend_dir"), min(times[t][0] for t in done),
                                      max(times[t][1] for t in done))
    trails = {t: maaend_fwlog.task_trail(events, SHOT_RULES[t]["entry"], *times[t]) for t in done}
    state_dir = ctx.get("state_dir")
    if not any(trails.values()):
        misses = int(_state_get(state_dir, "#28-miss") or 0) + 1
        _state_set(state_dir, "#28-miss", misses)
        if misses >= SHOT_MISS_FAIL:
            return _r(FAIL, f"连续 {misses} 趟，{'、'.join(done)} 在终末地自己的记录里都找不到，做成没有看不出来")
        return None
    _state_set(state_dir, "#28-miss", 0)
    files = raw.get("tasks_shot_files") or {}
    state = Path(state_dir or ".")
    good, bad = [], []
    for t in done:
        t0, t1 = times[t]
        trail = trails[t]
        span = f"{t0:%H:%M:%S}→{t1:%H:%M:%S}"
        if trail is None:
            bad.append(f"{t}（{span}）在终末地自己的记录里找不到")
            continue
        ok, said = _shot_verdict(SHOT_RULES[t], trail)
        if trail["nodes"].get(ABORT_STEP):
            said += _abort_why(text, t0, t1)
        line = f"{t}（{span}）{said}"
        note = _shot_note(state, files[t], trail["ended"]) if files.get(t) else ""
        (good if ok else bad).append(line + (f"；{note}" if note else ""))
    if bad:
        return _r(FAIL, "；".join(bad) + (f"。做成的：{'；'.join(good)}" if good else ""))
    if not good:
        return None
    return _r(PASS, "；".join(good))


_CLAIM = "确认领取奖励"
_HEAD = re.compile(r"^获得以下物品[:：]\s*$")
_ITEM = re.compile(r"^([^\[\s].*?)\s*[×x]\s*(\d+)\s*$")
_READING = re.compile(r"当前理智\s*(\d+)\s*/\s*(\d+)")
_STOP = re.compile(r"理智不足")
_MSG = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d[.\d]*\] (.*)$")
# What one Protocol Space claim cost, told by its own payout: the double reward pays
# 折金票 ×68000 and costs 160 (MaaEnd-05-29-05, 2026-10-07: 277 -> 117 across one such
# claim, no potion between); the single reward pays 折金票 ×34000 and costs 80 (same log:
# 117 -> single claim -> 37, which 10-08's first reading 237 = 37 + 200 overnight
# regeneration confirms). The MaaEnd logs kept in the day-replay corpus (pulls of
# 2026-10-06..10-13, history back to 09-24) hold no third amount within four lines of a
# 「确认领取奖励」: 108 such lines of 68000, 49 of 34000 (copies across pulls counted);
# on the 16 distinct list-era farming runs among them (09-29..10-13) this check and the
# collector agree. Another amount leaves the remaining sanity unjudged rather than guessed.
_PAY_ITEM = "折金票"
_CLAIM_COST = {68000: 160, 34000: 80}
_CLAIM_KIND = {68000: "双倍，扣 160", 34000: "单倍，扣 80"}


def _game_numbers(lines: list[str]) -> dict:
    """What the game showed in one farming task: claims that paid out (each
    「确认领取奖励」 followed by a 「获得以下物品：」 list before the next claim,
    reading or 「理智不足」), the items in those lists, and the 「当前理智」 readings."""
    msgs = [(m.group(1).strip() if (m := _MSG.match(x)) else x.strip()) for x in lines]
    landed, items, readings, last_landed = 0, {}, [], None
    claim_open, in_list = False, False
    for msg in msgs:
        if in_list and (m := _ITEM.match(msg)):
            items[m.group(1).strip()] = items.get(m.group(1).strip(), 0) + int(m.group(2))
            continue
        in_list = False
        if r := _READING.search(msg):
            readings.append((int(r.group(1)), int(r.group(2))))
            claim_open = False
        elif _CLAIM in msg:
            claim_open, last_landed = True, False
        elif _HEAD.match(msg):
            in_list = True
            if claim_open:
                landed, last_landed, claim_open = landed + 1, True, False
        elif _STOP.search(msg):
            claim_open = False
    return {"landed": landed, "items": items, "readings": readings, "last_landed": last_landed}


@mc.check("#20", "终末地产出和剩余理智按游戏自己的结算和读数记", "A", "run")
def _c20(ctx):
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    raw = ctx.get("raw") or {}
    lines = text.splitlines()
    segs = [s for s in cm._named_farm_segments(lines) if s[0] not in (raw.get("maaend_tasks_skipped") or {})]
    games = [(name, _game_numbers(lines[a:(b + 1) if b is not None else None])) for name, a, b in segs]
    games = [(n, g) for n, g in games if g["items"]]
    if not games:
        return None          # no farming task listed what it paid out (essence farming, or nothing claimed)
    runs = sum(g["landed"] for _, g in games)
    items: dict = {}
    for _, g in games:
        for k, n in g["items"].items():
            items[k] = items.get(k, 0) + n
    # Remaining sanity: the game's last reading in the whole log, plus the potions used
    # after it, less what the claim after it cost - read from that claim's own payout
    # (_claim_cost), not from the collector's rule, so the two are checked against each other.
    readings = [(int(m.group(1)), int(m.group(2))) for ln in lines if (m := _READING.search(ln))]
    want_sanity, landed_last, last_pay = None, False, None
    if readings:
        last_at = max(i for i, ln in enumerate(lines) if _READING.search(ln))
        end = next((b for _, a, b in cm._named_farm_segments(lines) if a <= last_at and (b is None or last_at <= b)),
                   None)
        tail = lines[last_at:(end + 1) if end is not None else None]
        after = _game_numbers(tail)
        landed_last = after["landed"] > 0
        have = readings[-1][0] + sum(1 for x in tail if cm._END_POTION.search(x)) * cm._END_POTION_SANITY
        if not landed_last:
            want_sanity = have
        else:
            last_pay = after["items"].get(_PAY_ITEM)
            if (cost := _CLAIM_COST.get(last_pay)) is not None:
                want_sanity = max(0, have - cost)
    got_drops = raw.get("maaend_farm_drops") or {}
    bad = []
    if raw.get("maaend_farm_runs") != runs:
        bad.append(f"趟数 {raw.get('maaend_farm_runs')}≠{runs}")
    if any(got_drops.get(k) != n for k, n in items.items()):
        bad.append("产出 " + " ".join(f"{k}×{got_drops.get(k, 0)}≠{n}" for k, n in items.items()
                                     if got_drops.get(k) != n))
    if want_sanity is not None and raw.get("sanity") != want_sanity:
        bad.append(f"剩余理智 {raw.get('sanity')}≠{want_sanity}")
    shown = " ".join(f"{k}×{n}" for k, n in items.items())
    paid = (f"，到账 {_PAY_ITEM}×{last_pay}（{_CLAIM_KIND[last_pay]}）" if last_pay in _CLAIM_KIND
            else f"，到账 {_PAY_ITEM}×{last_pay}（认不出单双倍）" if last_pay is not None else "")
    reading = (f"最后一次读数 当前理智 {readings[-1][0]}/{readings[-1][1]}（{'那次到账了' if landed_last else '那次没到账'}{paid}）"
               if readings else "没有理智读数")
    game = f"游戏结算 {runs} 次到账（{shown}），{reading}"
    if bad:
        return _r(FAIL, f"{game}；中继记的对不上：{'；'.join(bad)}")
    return _r(PASS, f"{game} → 中继记 {runs} 趟、{shown}"
                    + (f"、剩 {want_sanity}" if want_sanity is not None else "，剩余理智这趟算不出来不比"))


COMBAT_BLOCK = "战斗中无法使用"
_ROUTE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[.\d]*\] ((?:路线|线路)(\d+)[：:]\S*)")
_FW_STAMP = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
COLLECT = "自动采集"


def _collect_window(text: str) -> "tuple[datetime, datetime] | None":
    start = end = None
    for line in text.splitlines():
        m = _FW_STAMP.match(line)
        if not m:
            continue
        if re.search(r"任务开始[:：]\s*\S*" + COLLECT, line):
            start = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        elif start and re.search(r"任务(完成|失败)[:：]\s*\S*" + COLLECT, line):
            end = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    return (start, end) if start and end else None


@mc.check("#29", "终末地采集撞上「战斗中无法使用」的那条路线采没采到", "A", "run")
def _c29(ctx):
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    span = _collect_window(text)
    if span is None:
        return None
    t0, t1 = span
    own = [ln for ln in text.splitlines() if COMBAT_BLOCK in ln]
    fw = cm.maafw_grep(ctx.get("maaend_dir"), t0, t1, (COMBAT_BLOCK,))
    hits = own + fw
    if not hits:
        return None
    hit = hits[0]
    m = _FW_STAMP.match(hit)
    if not m:
        return _r(FAIL, f"撞了「{COMBAT_BLOCK}」，但这一行没有时间，认不出是哪条路线：{_cut(hit)}")
    at = m.group(1)
    routes = [(r.group(1), r.group(2), r.group(3)) for ln in text.splitlines() if (r := _ROUTE.match(ln))]
    before = [x for x in routes if x[0] <= at and not x[1].endswith("采集失败")]
    if not before:
        return _r(FAIL, f"{at[11:]} 撞了「{COMBAT_BLOCK}」，这之前日志里没有路线行，认不出是哪条：{_cut(hit)}")
    _, label, n = before[-1]
    if failed := [x for x in routes if x[2] == n and x[1].endswith("采集失败")]:
        return _r(FAIL, f"{label} 在 {at[11:]} 撞了「{COMBAT_BLOCK}」，没采到：{failed[-1][1]}")
    ends = cm.maafw_grep(ctx.get("maaend_dir"), datetime.strptime(at, "%Y-%m-%d %H:%M:%S"), t1,
                         (f'"name":"AutoCollectRoute{n}End"', f'"name":"AutoCollectRoute{n}Failed"'))
    if any(f"AutoCollectRoute{n}Failed" in x for x in ends):
        return _r(FAIL, f"{label} 在 {at[11:]} 撞了「{COMBAT_BLOCK}」，框架日志记这条路线失败：{_cut(ends[0])}")
    if done := [x for x in ends if f"AutoCollectRoute{n}End" in x]:
        return _r(PASS, f"{label} 在 {at[11:]} 撞了「{COMBAT_BLOCK}」，后来走完了：{_cut(done[0])}")
    return _r(FAIL, f"{label} 在 {at[11:]} 撞了「{COMBAT_BLOCK}」，没有采集失败那一行，"
                    f"框架日志里也没有这条路线走完（AutoCollectRoute{n}End）的记录：{_cut(hit)}")


def _at(line: str) -> "datetime | None":
    m = _FW_STAMP.match(line or "")
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None


@mc.check("#30", "终末地基质刷取领奖后失败：背包满了就写背包满了，不是就带原始日志", "A", "run")
def _c30(ctx):
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    from ark_relay.core import ledger as core  # noqa: PLC0415
    text = ctx.get("log_text") or ""
    fails = cm.claim_failures(text)
    if not fails:
        return None
    raw = ctx.get("raw") or {}
    rec = ctx["rec"]
    causes = raw.get("maaend_fail_causes") or {}
    claim = raw.get("maaend_claim_lines") or {}
    notices = [x for x in (text + "\n" + cm.maafw_text(ctx.get("maaend_dir"))).splitlines()
               if cm._END_STORAGE_FULL in x]
    _, body = core.format_failure(rec, texts.known_cause(causes))
    out = []
    for name, click, failed in fails:
        c0, c1 = _at(click), _at(failed)
        seen = [x for x in notices if c0 and c1 and (t := _at(x)) and c0 <= t <= c1 + timedelta(seconds=cm._STORAGE_FULL_AFTER_S)]
        full = causes.get(name) == cm.BAG_FULL
        if seen and not full:
            return _r(FAIL, f"{name} 点确认领取后失败，看到了「{cm._END_STORAGE_FULL}」却没写背包满了："
                            f"{_around(seen[0], cm._END_STORAGE_FULL)}")
        if full and not seen:
            return _r(FAIL, f"{name} 写成了背包满了，日志里却找不到「{cm._END_STORAGE_FULL}」：{_cut(failed)}")
        if full:
            if f"{name}（{cm.BAG_FULL}）" not in body:
                return _r(FAIL, f"{name} 认出背包满了，报警正文里却没有「{name}（{cm.BAG_FULL}）」")
            out.append(f"{name}（{cm.BAG_FULL}）：{_around(seen[0], cm._END_STORAGE_FULL)}")
            continue
        part = claim.get(name) if isinstance(claim.get(name), dict) else {}
        run = part.get("run") or []
        if not run or texts.CLAIM_LINES_RUN not in body:
            return _r(FAIL, f"{name} 点确认领取后失败，没看到仓储已满，报警却没带原始日志：{_cut(failed)}")
        out.append(f"{name} 没看到仓储已满，报警带了原始日志 {len(run)} 行（{_cut(run[0])[:60]}…）")
    return _r(PASS, "；".join(out))


# ------------------------------------------------------- alarms that must go out

def _undone_alarm(ctx, script: str):
    """#43 / #46: a round that exited normally with work left undone gets no make-up
    and no other way to recover (handle._handle_success pushes it at once), so its
    alarm must be among the copies of what went to the group (alertlog.py)."""
    if not _script(ctx, script) or ctx.get("test_run"):
        return None
    rec = ctx["rec"]
    msg = str((ctx.get("outcome") or {}).get("msg") or "")
    if not rec.ok or not msg or (ctx.get("raw") or {}).get("manual_stop"):
        return None
    bullet = next((ln for ln in msg.splitlines() if ln.startswith("· ")), msg.splitlines()[0])
    rows = [a for a in ctx.get("alerts") or [] if bullet in str(a.get("text") or "")]
    if not rows:
        rows = [a for a in _day_alerts(ctx.get("state_dir"), rec.finished)
                if msg in str(a.get("text") or "")]
    if rows:
        return _r(PASS, f"已进群：{rows[0].get('ts')} 「{rows[0].get('title')}」（报警抄送里有，{bullet[2:60]}）")
    why = "推送没成，排在下一轮重推" if rec.run_id in (ctx.get("unsent") or []) else "这一趟处理完，报警抄送里没有它"
    return _r(FAIL, f"「{bullet[2:80]}」没进群：{why}")


def _day_alerts(state_dir, since: datetime) -> list[dict]:
    """Alarm copies of the Beijing days from `since` to now that are no older than it."""
    if not state_dir:
        return []
    from ark_relay.features.alarm import alertlog  # noqa: PLC0415
    start = alertlog.beijing(since)
    days = sorted({start.strftime("%Y%m%d"), alertlog.beijing().strftime("%Y%m%d")})
    cut = start.strftime("%Y-%m-%d %H:%M:%S")
    return [row for day in days for row in mc.alert_rows(state_dir, day) if str(row.get("ts") or "") >= cut]


@mc.check("#43", "终末地「有项目没干成」的每一趟都进了群", "A", "run")
def _c43(ctx):
    return _undone_alarm(ctx, "MaaEnd")


@mc.check("#46", "鸣潮「有项目没干成」的每一趟都进了群", "A", "run")
def _c46(ctx):
    return _undone_alarm(ctx, "OK-WW")


# ------------------------------------------------------- #24: the three false-alarm fixes of 10-05

_PRE_RETRY = re.compile(r"预更新：(\S+) 没给出结论（.*），再试一次")
_PRE_NO_ROOM = re.compile(r"预更新：(\S+) 没给出结论，离下一个队列只有 \d+ 秒，不再试")
_PRE_LEFT = re.compile(r"预更新有 (\d+) 项没能确认")
# boot_stages._once_more: the second try gave a verdict. A retry line followed by neither
# this nor _PRE_LEFT is a pre-update that did not finish (a stop during the retry, which
# says nothing by design), so it is not judged rather than passed.
_PRE_FIXED = re.compile(r"预更新：(\S+) 第一次没给出结论，再试一次给出了结论")
RELAY_TAIL = 4 * 1024 * 1024


def _relay_today(now: datetime) -> list[str]:
    """relay.log (ARK_LOG_FILE) lines stamped today on the machine's clock; [] when there is none."""
    path = os.environ.get("ARK_LOG_FILE", "")
    if not path:
        return []
    from ark_relay.core.logfile import tail_bytes  # noqa: PLC0415
    try:
        # Reaches into relay.log.1 after a rotation (logfile.py).
        raw = tail_bytes(path, RELAY_TAIL)[0].decode("utf-8", errors="replace")
    except OSError:
        return []
    day = now.strftime("%m-%d")
    return [ln for ln in raw.splitlines() if ln.startswith(day + " ")]


@mc.check("#24b", "三处误报修复之二：预更新某项没给出结论就再试一次，还没结论就进群", "B", "run")
def _c24b(ctx):
    now = datetime.now(tz=SERVER_TZ)
    lines = _relay_today(now)
    first = [ln for ln in lines if _PRE_RETRY.search(ln) or _PRE_NO_ROOM.search(ln)]
    left = [ln for ln in lines if _PRE_LEFT.search(ln)]
    if not first and not left:
        return None
    stamp = (first or left)[0][:14]
    seen = (mc.read(ctx.get("state_dir")).get("#24b") or {}).get("evidence", "")
    if seen.startswith(stamp):
        return None          # this pre-update was judged already
    msg = lambda ln: _cut(ln.split("  ", 1)[-1])  # noqa: E731 - the message part of a relay.log line
    if left and not first:
        return _r(FAIL, f"{stamp} {msg(left[0])}，之前没有「再试一次」也没有「不再试」那一行")
    head = f"{stamp} {msg(first[0])}"
    if not left:
        if any(_PRE_NO_ROOM.search(ln) for ln in first):
            return _r(FAIL, f"{head}；说了不再试，后面却没有「预更新有 N 项没能确认」")
        if not any(_PRE_FIXED.search(ln) for ln in lines):
            return None      # the retry never finished: nothing was judged yet
        return _r(PASS, f"{head}；第二次给出了结论")
    n = int(_PRE_LEFT.search(left[-1]).group(1))
    title = texts.unconfirmed("预更新", n)
    rows = [a for a in _day_alerts(ctx.get("state_dir"), now.replace(hour=0, minute=0, second=0))
            if a.get("title") == title]
    if not rows:
        return _r(FAIL, f"{head}；还有 {n} 项没确认，报警抄送里没有「{title}」")
    return _r(PASS, f"{head}；还有 {n} 项没确认，{rows[0].get('ts')} 已进群")


mc.cannot("#24c", "三处误报修复之三：卡池下期扣下只记提醒、不进群",
          "这条修复要的「不进群」，10-06 已按「不论多少次什么错误都要发」改回进群，没有要核的了")
mc.cannot("#24d", "部署前闸门那次红的原因",
          "闸门在 Mac 上部署时跑，不在游戏机上，机器看不到")
