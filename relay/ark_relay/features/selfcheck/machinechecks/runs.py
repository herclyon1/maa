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
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.features.verify import collector_maaend as cm
from ark_relay.features.verify import maaend_fwlog
from ark_relay.features.selfcheck import machinecheck as mc
from ark_relay.features.verify import outcome
from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ, USER_TZ

log = logging.getLogger("ark.runs")

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


# The four tasks and how each is judged from MaaFW's own steps live in maaend_fwlog
# (TRAIL_TASKS, TRAIL_RULES, task_verdict, trail_table), shared with the ledger's
# 「没证据」 rule, which reads the same verdicts booked in raw['tasks_trail'].
SHOT_TASKS = maaend_fwlog.TRAIL_TASKS
# Runs in a row with none of the four in MaaFW's log before that is a FAIL of its own
# (as #7: MaaEnd clears its debug folder when it restarts). The ledger waits as long.
SHOT_MISS_FAIL = maaend_fwlog.TRAIL_MISS_FAIL


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
    """Judged from MaaFW's own steps of each task (maaend_fwlog.task_verdict), not from the desktop
    picture. Until 2026-10-16 this passed when the picture file existed, and the
    pictures of 10-08 showed the next task: 093302-赠送干员礼物.png the 装备制造 page,
    093322-装备制造.png 拜访好友, 103416-装备制造.png the bare desktop after MaaEnd
    stopped itself (maaend_fwlog.ABORT_STEP; verify ledger #28). The picture is still
    named, with how late it was.

    The verdicts are the ones booked with the record (raw['tasks_trail'],
    alarm.records._mark_task_trails), so MaaFW's log is read once a run; a record
    without them is read here the same way.

    A task another MaaEnd run of the same day did (or found nothing to do in) does not
    need a person: it is no FAIL, its line says which run did it, and the run's own
    ledger row keeps the cause for the daily report (core.maaend_unverified). On
    2026-10-08 MaaEnd stopped itself in 装备制造 at 10:34:16 (MaaEnd-06-31-06) after
    the 09:33 run (MaaEnd-05-29-15) had crafted. Only runs booked before this one are
    seen: a later run that does the task comes after this verdict. Such a verdict is a
    PASS marked healed, which the daily section says as failed and made up for.

    A task MaaFW's log does not cover (maaend_fwlog.trail_unread: a rotated or cleared
    log beginning inside the run, or none of the four in it) is not judged until that
    has happened SHOT_MISS_FAIL runs in a row, as the ledger waits; the rest of the run
    is judged as usual.

    A FAIL whose tasks are all on the 「没证据」 alarm sent (or queued) while this record
    was booked (ctx['unverified_alarm'], pushes._push_unverified) is not pushed again:
    that alarm carries MaaEnd's own verdict and reason for each of them
    (maaend_unbacked_why), so one cause goes to the group as one message; the FAIL
    stays on record. An alarm for the same items sent earlier that day does not count:
    that one was about another run. A FAIL about a run held for its retry - how the
    machine books MaaEnd stopping itself: ok=False, every later task failed
    (MaaEnd-06-31-06) - waits for the hold to end (_fail_28, settle_28)."""
    if not _script(ctx, "MaaEnd") or not _unattended(ctx):
        return None
    text = ctx.get("log_text") or ""
    raw = ctx.get("raw") or {}
    state_dir = ctx.get("state_dir")
    if "tasks_trail" in raw:
        table = raw.get("tasks_trail") or {}
        misses = int(raw.get("tasks_trail_miss") or 0)
    else:
        times = cm.task_times(text)
        skipped = raw.get("maaend_tasks_skipped") or {}
        table, why = maaend_fwlog.trail_table(ctx.get("maaend_dir"),
                                              {t: v for t, v in times.items() if t not in skipped}, text)
        misses = int(_state_get(state_dir, "#28-miss") or 0) + 1 if why else 0
        if table:
            _state_set(state_dir, "#28-miss", misses)
    done = [t for t in SHOT_TASKS if isinstance(table.get(t), dict)]
    if not done:
        return None
    unread = [t for t in done if misses and maaend_fwlog.trail_unread(table[t])]
    if unread and misses < SHOT_MISS_FAIL:
        # Not judged this run; said on the verdict's line when the rest is judged.
        done = [t for t in done if t not in unread]
        if not done:
            return None
        waits = f"{'、'.join(unread)} 这一趟终末地自己的记录没盖到，先不判"
    else:
        waits = ""
    if unread and len(unread) == len(done) and not waits:
        return _fail_28(ctx, done, f"连续 {misses} 趟，{'、'.join(done)} 在终末地自己的记录里都找不到，做成没有看不出来")
    files = raw.get("tasks_shot_files") or {}
    state = Path(state_dir or ".")
    good, bad, healed = [], [], False
    for t in done:
        e = table[t]
        t0, t1 = datetime.fromisoformat(e["t0"]), datetime.fromisoformat(e["t1"])
        line = f"{t}（{t0:%H:%M:%S}→{t1:%H:%M:%S}）"
        if not e.get("found"):
            line += (f"连续 {misses} 趟在终末地自己的记录里读不到" if t in unread
                     else "在终末地自己的记录里找不到")
        else:
            line += str(e.get("said") or "")
            ended = datetime.fromisoformat(e["ended"]) if e.get("ended") else None
            if note := (_shot_note(state, files[t], ended) if files.get(t) else ""):
                line += f"；{note}"
        if e.get("ok"):
            good.append(line)
        elif by := _done_elsewhere(ctx, t):
            # The work got done that day: no FAIL, but a session looks at why this run
            # did not do it (one 「自愈待查」 red item, techlog.self_heal).
            good.append(f"{line}；{by}，不用人管")
            healed = True
            rid = getattr(ctx.get("rec"), "run_id", "")
            log.info("上机核对 #28：%s 的%s没做成，%s，不进群，只进日报", rid, t, by)
            try:
                from ark_relay.core import techlog  # noqa: PLC0415
                techlog.self_heal(f"上机核对 #28 {rid} {t}", f"{line}；{by}", state_dir=state_dir)
            except Exception:  # the verdict stands; the group hears the failure to write
                log.warning("自愈待查的红项没写进技术日志：#28 %s %s", rid, t, exc_info=True)
        else:
            bad.append((t, line))
    tail = f"；{waits}" if waits else ""
    if bad:
        return _fail_28(ctx, [t for t, _ in bad], "；".join(x for _, x in bad)
                        + (f"。做成的：{'；'.join(good)}" if good else "") + tail)
    return mc.Result(PASS, "；".join(good) + tail, healed=healed)


# The alarm a #28 FAIL rides along with (pushes._push_unverified, its kind 「没证据」).
UNVERIFIED_ALARM = "没证据"
RODE_ALONG = "。已写在「没证据」那条报警里一起进群"
# #28 FAILs of runs held for their retry, until settle_28 settles them (machinecheck-runs.json):
# {run_id: {script, user, day, tasks, evidence, covered}}.
HELD_28 = "#28-held"
HELD_NOTE = "。这一趟中途停了，等这一班的重试跑完再定要不要报"


def _fail_28(ctx, tasks: list, evidence: str) -> mc.Result:
    """#28's FAIL about `tasks`: not pushed on its own when the 「没证据」 alarm sent while
    this record was booked names every one of them (ctx['unverified_alarm']) - that
    alarm carries the same verdicts - so the group gets one message for one cause.

    A run held for its retry (ctx['held']: booked ok=False, as AUTO-MAS books MaaEnd
    stopping itself, every later task failed) is not pushed yet either: its 「没证据」
    alarm, if any, comes with the retry's booking (handle._handle_success), and the
    retry may do the task. _hold_28 keeps it until settle_28 settles it."""
    sent = set(ctx.get("unverified_alarm") or [])
    if tasks and all(t in sent for t in tasks):
        return mc.Result(FAIL, evidence + RODE_ALONG, pushed_with=UNVERIFIED_ALARM)
    rec = ctx.get("rec")
    if tasks and getattr(rec, "run_id", None) in (ctx.get("held") or []):
        return _hold_28(ctx, tasks, evidence)
    return _r(FAIL, evidence)


def _hold_28(ctx, tasks: list, evidence: str) -> mc.Result:
    """Keep the FAIL about the held record (machinecheck-runs.json HELD_28) for
    settle_28; pushed at once when it cannot be kept, so it is never lost."""
    rec, state_dir = ctx.get("rec"), ctx.get("state_dir")
    held = _state_get(state_dir, HELD_28)
    held = dict(held) if isinstance(held, dict) else {}
    held[rec.run_id] = {"script": rec.script, "user": rec.user, "day": ctx.get("day") or "",
                        "tasks": list(tasks), "evidence": evidence, "covered": []}
    _state_set(state_dir, HELD_28, held)
    if rec.run_id not in (_state_get(state_dir, HELD_28) or {}):
        log.warning("上机核对 #28：%s 在等重试，但没记下来，现在就报", rec.run_id)
        return _r(FAIL, evidence)
    return mc.Result(FAIL, evidence + HELD_NOTE, deferred=True)


def covered_28(state_dir, script: str, day: str, items: list) -> None:
    """A 「没证据」 alarm naming `items` of `script` on `day` was just sent (or queued
    until it goes out): the held #28 FAILs of that day about those tasks are in it."""
    held = _state_get(state_dir, HELD_28)
    if not isinstance(held, dict) or not held:
        return
    changed = False
    for e in held.values():
        if e.get("script") != script or e.get("day") != day:
            continue
        add = [t for t in e.get("tasks") or [] if t in items and t not in (e.get("covered") or [])]
        if add:
            e["covered"] = list(e.get("covered") or []) + add
            changed = True
    if changed:
        _state_set(state_dir, HELD_28, held)


def settle_28(state_dir, hold_over, ledger, notifier) -> None:
    """Settle each held #28 FAIL whose hold is over (`hold_over(script, user)`: no record
    of that script and user held any more, the script not running): the tasks a
    「没证据」 alarm sent for them carries (covered_28) are in the group already; a task
    another run of the day did (`ledger(day)`, _done_elsewhere) was made up for, which
    the daily report says, as for a FAIL healed at once; any other task is pushed now
    as the check's own FAIL, with the evidence of the held run. A push that did not go
    out is kept and tried again at the next settle."""
    held = _state_get(state_dir, HELD_28)
    if not isinstance(held, dict) or not held:
        return
    mc.load()
    what = mc.CHECKS["#28"].what
    left = dict(held)
    for rid, e in held.items():
        if not hold_over(e.get("script"), e.get("user")):
            continue
        tasks = list(e.get("tasks") or [])
        covered = set(e.get("covered") or [])
        evidence = str(e.get("evidence") or "")
        was = evidence + HELD_NOTE
        ctx = {"rec": type("Held", (), {"run_id": rid})(), "ledger": ledger(e.get("day") or "")}
        healed = {t: by for t in tasks if t not in covered and (by := _done_elsewhere(ctx, t))}
        if rest := [t for t in tasks if t not in covered and t not in healed]:
            errs = notifier.send(texts.machinecheck_failed("#28", what),
                                 texts.machinecheck_failed_body(what, evidence), alert=True)
            if errs:
                log.error("上机核对 #28 没过（%s 等重试的那一趟），推送也没推出去，下一轮再推：%s", rid, "；".join(errs))
                continue
            log.info("上机核对 #28 没过，%s 的重试完了，%s 没有别的报警带上，已报群：%s", rid, "、".join(rest), evidence[:120])
            mc.restate(state_dir, "#28", was, evidence)
        elif covered:
            log.info("上机核对 #28 没过，%s 已写在「没证据」那条报警里进群，不另发：%s", rid, evidence[:120])
            mc.restate(state_dir, "#28", was, evidence + RODE_ALONG)
        else:
            by = "；".join(f"{t}：{b}" for t, b in healed.items())
            log.info("上机核对 #28：%s 的%s没做成，%s，不进群，只进日报", rid, "、".join(healed), by)
            mc.restate(state_dir, "#28", was, f"{evidence}；{by}，不用人管", healed=True)
            try:
                from ark_relay.core import techlog  # noqa: PLC0415
                techlog.self_heal(f"上机核对 #28 {rid} {'、'.join(healed)}", f"{evidence}；{by}", state_dir=state_dir)
            except Exception:  # the verdict stands; the group hears the failure to write
                log.warning("自愈待查的红项没写进技术日志：#28 %s", rid, exc_info=True)
        left.pop(rid, None)
    if left != held:
        _state_set(state_dir, HELD_28, left)


def _done_elsewhere(ctx, task: str) -> str:
    """「同一天 HH:MM（东京 HH:MM）开始的那趟已经做成了」 - on both clocks, as the daily
    report names a run (core.retried_notes) - when another MaaEnd run of the day booked before
    this one did `task` or found nothing to do in it (its raw['tasks_trail'] verdict,
    ctx['ledger']), else ''. A row booked before raw['tasks_trail'] backs nothing here."""
    rec = ctx.get("rec")
    me = getattr(rec, "run_id", None)
    for row in ctx.get("ledger") or []:
        if row.get("script") != "MaaEnd" or row.get("run_id") == me:
            continue
        e = ((row.get("raw") or {}).get("tasks_trail") or {}).get(task)
        if isinstance(e, dict) and e.get("ok"):
            try:
                at = datetime.fromisoformat(row.get("started") or "").astimezone(SERVER_TZ)
            except ValueError:
                return "同一天另一趟已经做成了"
            return f"同一天 {at:%H:%M}（东京 {at.astimezone(USER_TZ):%H:%M}）开始的那趟已经做成了"
    return ""


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
