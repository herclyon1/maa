"""Read MaaEnd's two side logs: the MaaFW framework log and MXU's own app log.

* Framework log: `<maaend>/debug/maafw*.log` and `<maaend>/debug/cpp-algo/debug/maafw*.log`
  (current and rotated). Every line starts with `[YYYY-MM-DD HH:MM:SS.mmm][LVL]`;
  a second process repeats each event line.
* MXU app log: `<maaend>/debug/YYYY-MM-DD-N.log`, one per MaaEnd launch, lines
  starting with `YYYY-MM-DD HH:MM:SS `.

collector_maaend re-exports the readers it used to hold, under their old names.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import threading
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter
from ark_relay.core.config import SERVER_TZ

log = logging.getLogger("ark.collector_maaend")

# The game's storage-full notice as MaaEnd's OCR logs it.
_END_STORAGE_FULL = "仓储空间已满"

# Strips the process / thread / source-file brackets between a framework line's
# stamp+level and its message.
_FW_META = re.compile(r"^(\[[^\]]+\]\[[A-Z]{3}\])(?:\[Px\d+\]\[Tx\d+\](?:\[[^\]]*\])?(?:\[L\d+\])?(?:\[[^\]]*\])?)?\s*")
# Framework event lines and ERR / WRN lines.
_FW_PICK = re.compile(r"\[msg=|^\[[^\]]+\]\[(?:ERR|WRN)\]")

_MXU_STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ")
_MXU_PENDING = re.compile(r"检测到待安装更新: (\S+)")
_MXU_INSTALLED = "更新安装完成"
# The pending line must fall within UPDATE_AT_START_S of the attempt's start, and
# the installed line within UPDATE_INSTALL_S after the pending line.
UPDATE_AT_START_S = (-2, 30)
UPDATE_INSTALL_S = 30


# MaaFW rotates maafw.log to maafw.bak.<YYYY.MM.DD-HH.MM.SS.mmm>.log and gzips it (….log.gz; one
# still being written ends in .tmp and is left alone). The stamp is the moment of the rotation, so
# a file holds what was logged before it. 2026-11-20 the 09:34-10:46 part of the 早班 was in three
# such files (09.40.02.867, 10.13.19.711, 10.46.38.827) and maafw.log began at 10:46:38: read
# without them, the 「协议更新」 dialog of 09:34:28 was not there for _dialog_seen.
_BAK_END = re.compile(r"maafw\.bak\.(\d{4})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2})(?:\.(\d{1,6}))?")


def _naive(t: datetime) -> datetime:
    """`t` on the machine's clock (MaaFW stamps its lines in it) without a zone."""
    return t.astimezone(SERVER_TZ).replace(tzinfo=None) if t.tzinfo else t


def _bak_time(name: str) -> "datetime | None":
    """Rotation stamp parsed from a maafw.bak.<stamp>.log[.gz] name; None if invalid."""
    m = _BAK_END.search(name)
    if not m:
        return None
    try:
        base = datetime(*map(int, m.groups()[:6]))
    except ValueError:
        return None
    frac = m.group(7) or ""
    if not frac:
        return base
    # Unpadded milliseconds, matching shot_time (17/160 maafw.bak names have 2 digits, e.g. .93 = 93 ms).
    return base + (timedelta(milliseconds=int(frac)) if len(frac) <= 3
                   else timedelta(microseconds=int(frac[:6].ljust(6, "0"))))


def _bak_stem(f: Path) -> str:
    return f.name[:-3] if f.suffix == ".gz" else f.name


def _fw_files(maaend_dir, t0: "datetime | None" = None, t1: "datetime | None" = None,
              *, include_gz: bool = False) -> list[Path]:
    """MaaFW's logs (main debug/ and cpp-algo/debug/, each rotated independently).
    Without a window: the plain ones (or plain + gzipped when `include_gz`), preferring plain
    when both exist for one rotation. With one: maafw.log plus, per directory, the rotated
    ones (plain or gzipped) covering [t0, t1] - each ending at or after t0, up to the first
    ending after t1."""
    debug = Path(maaend_dir) / "debug"
    dirs = (debug, debug / "cpp-algo" / "debug")
    if t0 is None or t1 is None:
        if not include_gz:
            return sorted(f for d in dirs for f in d.glob("maafw*.log"))
        files: list[Path] = []
        for d in dirs:
            plain = list(d.glob("maafw*.log"))
            files.extend(f for f in plain if not _BAK_END.search(f.name))
            rot = []
            for f in [*plain, *d.glob("maafw.bak.*.log.gz")]:
                if (end := _bak_time(f.name)) is not None:
                    rot.append((end, f.suffix == ".gz", _bak_stem(f), f))
            rot.sort()
            seen: set[str] = set()
            for _end, _is_gz, stem, f in rot:
                if stem not in seen:
                    seen.add(stem)
                    files.append(f)
        return sorted(files)
    lo, hi = _naive(t0).replace(microsecond=0), _naive(t1)
    files = []
    for d in dirs:
        plain = list(d.glob("maafw*.log"))
        files.extend(f for f in plain if not _BAK_END.search(f.name))
        rotated = []
        for f in [*plain, *d.glob("maafw.bak.*.log.gz")]:
            if (end := _bak_time(f.name)) is not None:
                rotated.append((end, f.suffix == ".gz", _bak_stem(f), f))
        rotated.sort()
        seen = set()     # 11-15 left both maafw.bak.<stamp>.log and its .log.gz: the same lines once
        for end, _is_gz, stem, f in rotated:
            if stem in seen or end < lo:
                continue
            seen.add(stem)
            files.append(f)
            if end.replace(microsecond=0) > hi:
                break
    return sorted(files)


def _fw_lines(files: list[Path], t0: datetime, t1: datetime, want=None) -> list[str]:
    """Lines of `files` stamped from t0 to t1 (whole seconds) for which `want(line)`
    holds (every line when `want` is None), trailing newline removed. A .gz is read
    through gzip. Unreadable or corrupt files are skipped."""
    lo, hi = f"[{_naive(t0):%Y-%m-%d %H:%M:%S}", f"[{_naive(t1):%Y-%m-%d %H:%M:%S}~"
    out: list[str] = []
    for f in files:
        try:
            opener = gzip.open(f, "rt", encoding="utf-8", errors="replace") if f.suffix == ".gz" \
                else f.open(encoding="utf-8", errors="replace")
            with opener as fh:
                out.extend(line.rstrip("\n") for line in fh
                           if lo <= line[:24] <= hi and (want is None or want(line)))
        except (OSError, EOFError, zlib.error):
            continue
    return out


def _short(line: str) -> "tuple[str, str]":
    """(the line without the bracket metadata, its message body)."""
    short = _FW_META.sub(r"\1 ", line)
    return short, short.split("]", 2)[-1]


def maafw_text(maaend_dir, t0: "datetime | None" = None, t1: "datetime | None" = None) -> str:
    """The storage-full lines of MaaEnd's framework logs (including rotated .log.gz),
    or "" when there is no directory or nothing to read."""
    if not maaend_dir:
        return ""
    files = _fw_files(maaend_dir, t0, t1) if (t0 is not None and t1 is not None) else _fw_files(maaend_dir, include_gz=True)
    out: list[str] = []
    for f in files:
        try:
            opener = gzip.open(f, "rt", encoding="utf-8", errors="replace") if f.suffix == ".gz" \
                else f.open(encoding="utf-8", errors="replace")
            with opener as fh:
                out.extend(line for line in fh if _END_STORAGE_FULL in line)
        except (OSError, EOFError, zlib.error):
            continue
    return "".join(out)


def maafw_window(maaend_dir, t0: datetime, t1: datetime) -> tuple[list[str], str]:
    """MaaEnd's framework-log lines stamped from t0 to t1 (whole seconds): the
    event lines ([msg=...]) and ERR / WRN lines when there are any, every line of
    the stretch otherwise. Each line keeps its stamp and level without the bracket
    metadata; a line whose body equals the previous one is dropped. Returns
    (lines, why there are none - '' when there are)."""
    if not maaend_dir:
        return [], "没配终末地的目录"
    files = _fw_files(maaend_dir, t0, t1)
    if not files:
        return [], "框架日志的文件夹里没有日志（终末地每次重启会清掉它）"
    stretch = _fw_lines(files, t0, t1)
    if not stretch:
        return [], "框架日志里这段时间没有记录"
    picked = [x for x in stretch if _FW_PICK.search(x)] or stretch
    out: list[str] = []
    seen_last = ""
    for line in sorted(picked):
        short, body = _short(line)
        if body == seen_last:
            continue
        seen_last = body
        out.append(short)
    return out, ""


def maafw_grep(maaend_dir, t0: datetime, t1: datetime, needles: "tuple[str, ...]") -> list[str]:
    """MaaEnd's framework-log lines stamped from t0 to t1 (whole seconds) that hold
    any of `needles`, as written or JSON-escaped (\\uXXXX); each body kept once,
    in time order. [] when there is no directory or nothing matched."""
    if not maaend_dir or not needles:
        return []
    forms = list(dict.fromkeys(f for n in needles
                               for f in (n, json.dumps(n).strip('"'))))
    found = _fw_lines(_fw_files(maaend_dir, t0, t1), t0, t1, lambda line: any(x in line for x in forms))
    out: list[str] = []
    seen: set[str] = set()
    for line in sorted(found):
        short, body = _short(line)
        if body in seen:
            continue
        seen.add(body)
        out.append(short)
    return out


def update_restart_version(maaend_dir, started) -> str:
    """The version MaaEnd installed at the start of the attempt that began at
    `started`, or "".

    MXU installs a pending update when it launches and restarts MaaEnd; the
    process AUTO-MAS watches exits and that attempt's tasks are booked failed.
    Only MXU's app log has these lines. The window is anchored on this attempt's
    start, not on the previous attempt's end.
    """
    if not maaend_dir:
        return ""
    lo = started + timedelta(seconds=UPDATE_AT_START_S[0])
    hi = started + timedelta(seconds=UPDATE_AT_START_S[1])
    debug = Path(maaend_dir) / "debug"
    for day in {lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d")}:
        for log_file in sorted(debug.glob(f"{day}-*.log")):
            try:
                text = log_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            version, pending_at = "", None
            for line in text.splitlines():
                m = _MXU_STAMP.match(line)
                if not m:
                    continue
                try:
                    at = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=started.tzinfo)
                except ValueError:
                    continue
                if pm := _MXU_PENDING.search(line):
                    if lo <= at <= hi:
                        version, pending_at = pm.group(1), at
                elif (_MXU_INSTALLED in line and pending_at is not None
                      and pending_at <= at <= pending_at + timedelta(seconds=UPDATE_INSTALL_S)):
                    return version
    return ""


_FW_EVENT = re.compile(r"\[msg=(Tasker\.Task\.\w+|Node\.PipelineNode\.Succeeded)\]\s*\[details=(\{.*\})\]\s*$")
_FW_AT = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)\]")
TRAIL_SLACK_S = 5


def task_events(maaend_dir, t0: datetime, t1: datetime) -> list:
    """MaaFW's task and node events from t0 - TRAIL_SLACK_S to t1 + TRAIL_SLACK_S,
    as (time, "Tasker.Task.Starting" | ... | "Node.PipelineNode.Succeeded", details),
    oldest first; [] when there is no directory or nothing there. Read once and
    handed to task_trail for each task of a run: the rotated files are tens of MB each."""
    if not maaend_dir:
        return []
    lo = t0 - timedelta(seconds=TRAIL_SLACK_S)
    hi = t1 + timedelta(seconds=TRAIL_SLACK_S)
    lines = _fw_lines(_fw_files(maaend_dir, lo, hi), lo, hi,
                      lambda line: "[msg=Tasker.Task." in line or "[msg=Node.PipelineNode.Succeeded]" in line)
    events = []
    for line in lines:
        m, at = _FW_EVENT.search(line), _FW_AT.match(line)
        if not m or not at:
            continue
        try:
            details = json.loads(m.group(2))
            when = datetime.fromisoformat(at.group(1))
        except ValueError:
            continue
        if isinstance(details, dict):
            events.append((when, m.group(1), details))
    events.sort(key=lambda e: e[0])
    return events


def task_trail(events: list, entry: str, t0: datetime, t1: datetime) -> "dict | None":
    """What MaaFW logged for one task (`events` from task_events): the run of `entry`
    whose start is nearest t0 (AUTO-MAS's 「任务开始」) within TRAIL_SLACK_S of the
    window t0..t1 (its 「任务完成」).

Returns {"started", "ended" (datetimes, ended None when no end event),
    "result" ("Succeeded" / "Failed" / ""), "nodes" ({node name: times it
    succeeded})} or None when there is no start of `entry` in the window.
    """
    lo = t0 - timedelta(seconds=TRAIL_SLACK_S)
    hi = t1 + timedelta(seconds=TRAIL_SLACK_S)
    starts = [(abs((w - t0).total_seconds()), w, d.get("task_id")) for w, msg, d in events
              if msg == "Tasker.Task.Starting" and d.get("entry") == entry and lo <= w <= hi]
    if not starts:
        return None
    _, started, task_id = min(starts, key=lambda s: (s[0], s[1]))
    ended, result = None, ""
    for w, msg, d in events:
        if (w >= started and d.get("task_id") == task_id and d.get("entry") == entry
                and msg in ("Tasker.Task.Succeeded", "Tasker.Task.Failed")):
            ended, result = w, msg.rsplit(".", 1)[-1]
            break
    # Without an end event the stretch stops at the window's edge, not at the end of
    # `events`, which holds the later tasks of the run too.
    last = ended if ended is not None else hi
    nxt = None
    if ended is None:
        nxt = min((w for w, msg, d in events if msg == "Tasker.Task.Starting" and w > started
                   and d.get("task_id") != task_id and w <= hi), default=None)
    nodes: dict = {}
    seen: set = set()
    for w, msg, d in events:
        if msg != "Node.PipelineNode.Succeeded" or w < started or w > last or (nxt is not None and w >= nxt):
            continue
        key = (d.get("task_id"), d.get("node_id"))
        if key in seen:
            continue
        seen.add(key)
        hit = d.get("node_details") or d.get("action_details") or {}
        name = str((hit.get("name") if isinstance(hit, dict) else "") or d.get("name") or "")
        nodes[name] = nodes.get(name, 0) + 1
    return {"started": started, "ended": ended, "result": result, "nodes": nodes}


# The four MaaEnd tasks whose AUTO-MAS log has only 「任务开始」 / 「任务完成」: whether
# they did their job is read from MaaFW's own steps (task_trail), by machine check #28
# (machinechecks/runs.py) and by the ledger's 「没证据」 rule (core.maaend_unverified,
# through raw['tasks_trail'] booked by alarm.records._mark_task_trails).
TRAIL_TASKS = ("赠送干员礼物", "装备制造", "转交委托", "环境监测")
TRAIL_RULES = {
    "赠送干员礼物": {"entry": "GiftOperatorMain",
                 "did": (("GiftOperatorConfirmGift", "点了「赠送」{n} 次"),),
                 "end": (("GiftOperatorGiftFullFail", "连换 5 次干员，礼物都已送满，算没东西可做"),)},
    "装备制造": {"entry": "GearAssemblyStart",
              "did": (("GearAssemblyClickProduceBtn", "点了「制作」{n} 次"),),
              "end": (("GearAssemblyCheckMaterialEnough", "背包已满，做不出来，算没东西可做"),
                      ("GearAssemblyCheckFailedAndFinish", "装备列表翻到底，没有能做的（材料不够或没解锁），算没东西可做"))},
    "转交委托": {"entry": "DeliveryJobsMain",
              "did": (("DeliveryJobsConfirmTaskTransfer", "确认转交了 {n} 单"),),
              "none": "两个地区都走了一遍，没有可转交的委托",
              "needs": ("DeliveryJobsValleyIVLoop", "DeliveryJobsWulingLoop")},
    "环境监测": {"entry": "EnvironmentMonitoringMain",
              "did": (("EnvironmentMonitoringTakePhoto", "接了委托、拍了监测照片"),),
              "none": "两个监测终端都看过了，没有可接的委托",
              "needs": ("OutskirtsMonitoringTerminalLoop", "MarkerStoneMonitoringTerminalLoop")},
}
ABORT_STEP = "__SceneCheckAbortPipeline"


def task_verdict(task: str, trail: dict) -> "tuple[bool, str]":
    """(did its job or found nothing to do, what MaaFW's log shows) for one of
    TRAIL_TASKS, from its task_trail.

    Order: MaaEnd's abort; a nothing-to-do end step (before MaaFW's result, which for
    a StopTask end is Succeeded - TRAIL_RULES - but the pipeline calls the step a
    normal end whatever is booked); MaaFW's Failed; the step that did the job; a
    nothing-to-do told by the steps that ran."""
    rule, nodes = TRAIL_RULES[task], trail["nodes"]
    if nodes.get(ABORT_STEP):
        return False, "终末地自己检查画面没过，把后面的任务全停了，这一项没做成"
    for step, word in rule.get("end", ()):
        if nodes.get(step):
            return True, word
    if trail["result"] == "Failed":
        return False, "终末地自己记的结果是失败"
    did = [w.format(n=nodes[s]) for s, w in rule["did"] if nodes.get(s)]
    if did:
        return True, "、".join(did)
    if rule.get("needs") and all(nodes.get(x) for x in rule["needs"]):
        return True, rule["none"]
    return False, f"终末地自己的记录里只走了 {sum(nodes.values())} 步，没有做成的一步，也没有「没东西可做」的结果"


def _trails_read(maaend_dir, times: dict) -> "tuple[dict, dict]":
    """({task: task_trail or None}, {task: log_reaches its start}) for each of
    TRAIL_TASKS in `times` ({task: (start, finish)}, naive machine-local, as
    collector_maaend.task_times gives them); MaaFW's log is read once for all of them.
    ({}, {}) when none of the four is in `times`."""
    tasks = [t for t in TRAIL_TASKS if t in times]
    if not tasks:
        return {}, {}
    events = task_events(maaend_dir, min(times[t][0] for t in tasks), max(times[t][1] for t in tasks))
    return ({t: task_trail(events, TRAIL_RULES[t]["entry"], *times[t]) for t in tasks},
            {t: log_reaches(events, times[t][0]) for t in tasks})


def log_reaches(events: list, t0: datetime) -> bool:
    """MaaFW's log (`events` from task_events) holds an event in the TRAIL_SLACK_S before
    t0, AUTO-MAS's 「任务开始」 of a task: the log reaches back to the moment MaaEnd
    posted that task (its Tasker.Task.Starting comes up to a second before t0), so a
    task with no start of its own there was not posted as MaaFW knows it. False when the
    log begins later: MaaFW rotates its log into maafw.bak.<time>.log files (2026-10-16:
    three in seven minutes) and MaaEnd clears its debug folder when it restarts, so the
    files can begin inside a long run - also inside the task itself, which is why the
    stretch before the start is read and not the task's whole window. The previous
    task's end event sits 2 ms before the next start (2026-10-16); the first task of a
    launch has nothing before it and reads as not reached."""
    lo = t0 - timedelta(seconds=TRAIL_SLACK_S)
    return any(lo <= w < t0 for w, _, _ in events)


# Runs in a row with a task left unread before that counts: machine check #28 FAILs and
# the ledger calls those tasks unbacked (core.maaend_unverified). A task is unread when
# MaaFW's log holds none of the four, or when it holds no run of this task and does not
# reach back to its start (log_reaches). One such run is left unjudged: MaaEnd clears
# its debug folder when it restarts, MaaFW rotates its log, and a folder that is not
# configured or not readable says nothing about the game.
TRAIL_MISS_FAIL = 2


def trail_unread(e: dict) -> bool:
    """A booked trail_entry left unread. A row booked before the 「unread」 key read a
    missing task as unread only when none of the four was found, and then its
    raw['tasks_trail_miss'] is above 0 - which the callers ask first."""
    return bool(e.get("unread", not e.get("found", True)))

_RUN_LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[.\d]*\] (.+)$", re.M)
_NOT_REASON = re.compile(r"^任务(开始|完成)[:：]|^正在检查画面")
# MaaEnd's reasons said in plain words, where its own line carries English
# (texts.plain): (part of its line, what it means).
_ABORT_WORDS = (
    ("UID显示不完整", "左上角的账号编号显示不全，它说开着隐藏账号编号的模组会挡住左上方的字，认不出画面"),
)


def abort_said(text: str, t0: datetime, t1: datetime) -> "tuple[str, datetime | None]":
    """MaaEnd's last own line in AUTO-MAS's run log `text` inside the task's window
    t0..t1 (whole seconds, as collector_maaend.task_times gives them) that is not a
    task start / end, and its time: why it stopped itself (2026-10-08 10:34:16.230
    「UID显示不完整，…影响识别」); ("", None) when there is none."""
    said, when = "", None
    for m in _RUN_LINE.finditer(text or ""):
        at = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        line = m.group(2).strip()
        if t0 <= at <= t1 and line and not _NOT_REASON.search(line):
            said, when = line, at
    return said, when


def abort_why(text: str, t0: datetime, t1: datetime) -> str:
    """\"，它记的原因：…\" for MaaEnd's abort of one task: its own line, verbatim when it
    is plain Chinese, else its _ABORT_WORDS meaning, else where to read it."""
    from ark_relay.core import texts  # noqa: PLC0415
    line, at = abort_said(text, t0, t1)
    if not line:
        return ""
    for part, meant in _ABORT_WORDS:
        if part in line:
            return f"，它记的原因：{meant}"
    if not texts.plain(line):
        return f"，它记的原因：「{line}」"
    return f"，原因写在终末地自己记的 {at:%H:%M:%S} 那一行"


def trail_entry(task: str, trail: "dict | None", t0: datetime, t1: datetime, text: str = "",
                unread: bool = False) -> dict:
    """One task's verdict as booked in raw['tasks_trail'] (alarm.records._mark_task_trails)
    and read back by machine check #28 and core.maaend_unverified, so MaaFW's log is
    read once per run:

        t0, t1   AUTO-MAS's 「任务开始」 / 「任务完成」 (ISO, machine-local)
        found    MaaFW's log holds this task's run (task_trail is not None)
        unread   not found because the log does not cover it (`unread`, set by
                 trail_table: none of the four found, or the log does not reach
                 back to its start); a task found, or missing from a log that
                 covers it, is not unread
        ok       task_verdict: did its job or found nothing to do
        said     what MaaFW's log shows (task_verdict), with MaaEnd's own reason
                 (abort_why, from the run log `text`) when it stopped itself
        abort    MaaEnd stopped itself inside this task (ABORT_STEP)
        ended    MaaFW's end event (ISO), None when there is none"""
    e = {"t0": t0.isoformat(), "t1": t1.isoformat(), "found": trail is not None,
         "unread": trail is None and unread, "ok": False, "said": "", "abort": False, "ended": None}
    if trail is None:
        return e
    ok, said = task_verdict(task, trail)
    abort = bool(trail["nodes"].get(ABORT_STEP))
    if abort:
        said += abort_why(text, t0, t1)
    e.update(ok=ok, said=said, abort=abort,
             ended=trail["ended"].isoformat() if trail["ended"] is not None else None)
    return e


def trail_table(maaend_dir, times: dict, text: str = "") -> "tuple[dict, str]":
    """({task: trail_entry} for each of TRAIL_TASKS in `times`, why some of them are
    unread - '' when none is, or when none was asked). Unread: every one of them when
    MaaFW's log holds none of the four; else each one with no run in the log that the
    log does not reach back to (log_reaches: a rotated or cleared log beginning inside
    the run). A task missing from a log that does reach its start is not unread: it
    was not posted as MaaFW knows it, and is judged unbacked at once. An unreadable
    file is skipped like a missing one (_fw_lines)."""
    asked = {t: times[t] for t in TRAIL_TASKS if t in times}
    if not asked:
        return {}, ""
    found, reach = _trails_read(maaend_dir, asked) if maaend_dir else ({}, {})
    none = not any(found.get(t) for t in asked)
    table = {t: trail_entry(t, found.get(t), t0, t1, text, unread=none or not reach.get(t))
             for t, (t0, t1) in asked.items()}
    unread = [t for t, e in table.items() if e["unread"]]
    if not unread:
        return table, ""
    if not maaend_dir:
        why = "没配终末地的文件夹"
    elif not _fw_files(maaend_dir):
        why = "终末地的日志文件夹里没有框架日志（它每次重启会清掉）"
    elif not all(reach.get(t) for t in unread):
        why = (f"框架日志没盖到{'、'.join(t for t in unread if not reach.get(t))}开始的那一刻："
               f"开始前 {TRAIL_SLACK_S} 秒里一条记录也没有，日志换了新文件、终末地重启清掉了前面的、"
               "或者文件读不了，都会这样")
    else:
        why = "框架日志盖到了这段时间，但里面没有这几个任务"
    return table, why


# This module's public names plus every name re-exported from the modules above
# (callers and tests say collector_maaend.<name>); pyflakes and ruff count a listed name as used.


# "MaaEnd 部分任务执行失败: 🚚转交委托、⚔️协议空间"
_FAILED_LIST = re.compile(r"失败[:：]\s*(.+)$")


def _maaend_all_done(text: str, failed: "list[str] | None" = None) -> bool:
    """MaaEnd's own log shows the whole round finished: every 「任务开始」has a
    「任务完成」with the same name, there is no 「任务失败」at all, at least one
    task ran, and either the round reached its closing task (`_maaend_round_closed`)
    or every task AUTO-MAS lists as failed (`failed`) is one it could not name.
    """
    started = [_strip_emoji(m.group(1)) for m in _END_TASK_START.finditer(text)]
    done = Counter(_strip_emoji(m.group(1)) for m in _END_TASK_DONE.finditer(text))
    if not started or _END_TASK_FAIL.search(text):
        return False
    if Counter(started) - done:
        return False
    if failed and any(not _AUTOMAS_KEY.fullmatch(n) and n not in started for n in failed):
        return False
    if _maaend_round_closed(text):
        return True
    return bool(failed) and all(_AUTOMAS_KEY.fullmatch(n) for n in failed)


_AUTOMAS_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


_END_CLOSING_TASKS = ("关闭游戏", "结束进程")
_END_STOP_MARK = "停止任务"


def _maaend_round_closed(text: str) -> bool:
    """The last task MaaEnd started is a closing task, and it completed.

    No closing task means the log cannot show the round reached its end, so
    this says no. CloseGamePC is only appended when no later stage follows
    (docs/PITFALLS.md), so a stage followed by another one never qualifies.
    """
    starts = [m for m in _END_TASK_START.finditer(text) if _strip_emoji(m.group(1)) != _END_STOP_MARK]
    if not starts:
        return False
    last = _strip_emoji(starts[-1].group(1))
    if not any(c in last for c in _END_CLOSING_TASKS):
        return False
    # Its 「任务完成」 must come after its own 「任务开始」, not from an earlier run
    # of the same name.
    return any(_strip_emoji(m.group(1)) == last
               for m in _END_TASK_DONE.finditer(text, starts[-1].end()))


def _split_failed(text: str) -> list[str]:
    """Pull the per-task names out of MaaEnd's failure sentence."""
    m = _FAILED_LIST.search(text)
    if not m:
        return []
    # Names are separated by the Chinese enumeration comma; strip leading emoji.
    parts = [p.strip() for p in m.group(1).split("、") if p.strip()]
    return [_strip_emoji(p) for p in parts]


# Items gained, one line each:
#   任务完成: 🎁赠送干员礼物
#   获得 高级认知载体 ×3
_END_GAIN = re.compile(r"获得\s+(\S.*?)\s*[×x]\s*(\d+)")
# Endfield's sanity reading, e.g. 「当前理智 920/360」 (it can exceed the cap).
_END_SANITY = re.compile(r"当前理智\s*(\d+)\s*/\s*(\d+)")
_END_SANITY_OUT = re.compile(r"理智不足[，,]\s*结束任务|体力不足[，,]\s*任务结束")
_END_PS_COST = 160
# Endfield regenerates 1 sanity every 7m12s, 200 points per 24 hours (official
# figure); also used for the full-again time (core/collector.py).
_END_SANITY_SEC_PER_POINT = 432
_END_SANITY_SPENT = re.compile(r"尝试使用理智消耗许可")
_END_POTION = re.compile(r"补充理智")
_END_POTION_SANITY = 40
_END_SANITY_REFUSED = re.compile(r"理智不足[，,]\s*尝试不使用理智消耗许可")
_END_PS_ENTER = re.compile(r"进入协议空间成功")
# re.M on the three task-status patterns: they are used with search on one line
# and with finditer over the whole text, where `$` must match at every line end.
_END_TASK_DONE = re.compile(r"任务完成[:：]\s*(\S.+?)\s*$", re.M)
# A farming section looks like:
#   任务开始: 🎱基质刷取 / 📌目标地点：枢纽区 / 当前理智 234/360 / 是无暇基质 ×N
#   ✅已完成一次基质刷取 / 当前理智 154/360 / … / 任务完成: 🎱基质刷取
_END_TASK_START = re.compile(r"任务开始[:：]\s*(\S.+?)\s*$", re.M)
_END_TASK_FAIL = re.compile(r"任务失败[:：]\s*(\S.+?)\s*$", re.M)
_END_FARM_TASKS = ("基质刷取", "协议空间")
_END_PLACE = re.compile(r"目标地点[:：]\s*(\S+)")
_END_ESSENCE_DONE = re.compile(r"已完成一次基质刷取")
# Target mode with the ticked weapons' essences already owned (outcome._MAAEND_ESSENCE_MET).
_END_ESSENCE_MET = re.compile(r"勾选武器的基质均已满足")
_END_ESSENCE_DROP = re.compile(r"^是(\S+?基质)\s*$")
_END_MEDICINE = re.compile(r"使用(?:了)?应急理智加强剂|补充理智")
_END_COLLECT_SKIP = re.compile(r"任务开始[:：]\s*\S*自动采集\s*\n[^\n]*?现在游戏时间是(周[一二三四五六日天])，根据执行周期跳过任务")
# The weekday-schedule skip of any task (MaaEnd's 「执行周期」 option exists for
# AutoCollect, ProtocolSpace and AutoEssence: tests/fixtures/maaend228/tasks/*.json).
_END_SCHEDULE_SKIP = re.compile(
    r"任务开始[:：]\s*(\S.+?)\s*\n[^\n]*?现在游戏时间是(周[一二三四五六日天])，根据执行周期跳过任务")
_END_COLLECT_ROUTES = re.compile(r"(\d+)\s*条路线")

OBSTACLE_SHOT = "MapNavigatorObstacleDevice_InteractPost"
_SHOT_NAME = re.compile(r"^(\d{4}\.\d\d\.\d\d-\d\d\.\d\d\.\d\d)\.(\d+)_+(.+)\.png$")
_LINE_TIME = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:\.(\d{1,6}))?")
_ROUTE_LINE = re.compile(r"^\[[^\]]+\]\s*((?:路线|线路)\d+[：:].*?|(?:采集(?!失败$)[^\s：:]+|\S+(?:采集失败| 库存已达目标，本次跳过)))\s*$")
_ROUTE_NOT_START = re.compile(r"采集失败$|本次跳过$")
_COLLECTOR_FAILED = re.compile(r"FailureCollector subtask failed task=(AutoCollect[A-Za-z]+?\d+)[A-Z][A-Za-z]*\b")
_COLLECT_END = re.compile(r"任务(?:完成|失败)[:：]\s*\S*自动采集")


def collector_failed_routes(text: str) -> list[str]:
    """Route ids the failure collector failed in a run's AUTO-MAS log, in order (_COLLECTOR_FAILED)."""
    found: list[str] = []
    for m in _COLLECTOR_FAILED.finditer(text):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


# v2.36+ item-named route lines, 「[time] 采集纯晶多齿叶」 (also read by collect_retry.walked_routes).
_V236_ROUTE_START = re.compile(r"(?m)^\[[^\]]+\]\s*采集(?!失败\s*$)([^\s：:]+)\s*$")


def _collector_failed_items(text: str, items: dict[str, str]) -> list[str]:
    """The items (as in 「采集<item>」) of the routes the failure collector failed, in order."""
    out: list[str] = []
    last = None
    for line in text.splitlines():
        if m := _V236_ROUTE_START.match(line.strip()):
            last = m.group(1)
        elif m := _COLLECTOR_FAILED.search(line):
            it = items.get(m.group(1)) or last
            if it and it not in out:
                out.append(it)
    return out


def _add_collector_failed(text: str, maaend_dir, failed_items: list[str], out: dict) -> None:
    """Routes the failure collector named (no 「采集失败」 line of their own) join `failed_items`:
    by item through the locale, else the route whose 「采集…」 line came last before the failure line."""
    if cf_ids := collector_failed_routes(text):
        out["maaend_collect_failed_ids"] = cf_ids
        for it in _collector_failed_items(text, route_items(maaend_dir) if maaend_dir else {}):
            if it not in failed_items:
                failed_items.append(it)


def route_items(maaend_dir) -> dict[str, str]:
    """{route id: what the history log writes after 「采集」} from MaaEnd's own zh_cn locale, through
    collect_retry's label table: task.AutoCollect.route.WulingProtocolith2.label 「采集协议纹石（路线2）」
    -> 「协议纹石（路线2）」, the words of the run's own 「采集协议纹石（路线2）」 line. {} without a locale."""
    from ark_relay.features import collect_retry  # noqa: PLC0415 - collect_retry reads this module
    zh = collect_retry._locale(Path(maaend_dir))
    return {rid: lbl.removeprefix("采集") for lbl, rid in collect_retry.route_ids_by_label(zh).items()}


def shot_time(name: str) -> "datetime | None":
    """The time in an on_error picture's own name, to the millisecond (the game PC's
    clock, as the logs'). The node name follows ___ (on_error) or a single _
    (2026.10.08-10.01.43.463_AutoCollectRoute1Start.png). MaaFW writes the
    milliseconds unpadded - 「…10.44.55.895___」 but 「…16.39.29.93」 is 93 ms: 17 of
    the 160 maafw.bak names in the day corpus have two digits, the one in ten that
    random milliseconds below 100 give."""
    m = _SHOT_NAME.match(name)
    try:
        base = datetime.strptime(m.group(1), "%Y.%m.%d-%H.%M.%S") if m else None
    except ValueError:
        return None
    if base is None:
        return None
    frac = m.group(2)
    # Unpadded milliseconds; more than three digits can only be a decimal fraction.
    return base + (timedelta(milliseconds=int(frac)) if len(frac) <= 3
                   else timedelta(microseconds=int(frac[:6].ljust(6, "0"))))


def is_obstacle_shot(name: str) -> bool:
    """Whether an on_error picture is a relay-device one (OBSTACLE_SHOT), by the node
    name after its time - ___ or a single _, as shot_time reads it. The one test for
    every part that looks for these pictures (obstacle_shots for the daily row and the
    retry list, blocked_routes, collect_retry.retry_blocked, machine check #29), so a
    picture the outcome check books is one the daily row and the retry book too."""
    m = _SHOT_NAME.match(name)
    return bool(m) and m.group(3) == OBSTACLE_SHOT


def line_time(line: str) -> "datetime | None":
    """A history-log or maafw.log line's stamp, to the millisecond; None when it has none."""
    m = _LINE_TIME.match(line)
    try:
        base = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None
    except ValueError:
        return None
    return base.replace(microsecond=int((m.group(2) or "0").ljust(6, "0"))) if base else None


def in_window(t: datetime, start: datetime, end: "datetime | None") -> bool:
    """Whether a picture stamped `t` belongs to the window [start, end); end None = open.

    The one rule for every part that hands a relay-device picture to a route or a run
    (blocked_routes, collect_retry.retry_blocked, machine check #29, round_shots). All
    stamps carry their milliseconds (shot_time, line_time): cut to the second, a
    picture at 10:45:39.400 - before AutoCollectRoute10End (.489) and the 路线11 line
    (.533) - went to route 11, which was then re-run for nothing while route 10 was
    booked as walked."""
    return start <= t and (end is None or t < end)


def spans(events, last: "datetime | None") -> list[tuple[str, datetime, "datetime | None"]]:
    """(route, start, end) windows from `events`, (time, kind, route) in log order.

    The one window rule for the history log (route_windows) and maafw.log
    (collect_retry.retry_blocked), so the two cannot credit a picture differently:
    'open' starts `route`'s window and closes the open one; 'close' closes it (a
    failed route, or the gathering task's end - where the history log ends its last
    route, and maafw.log's Tasker.Task event for the same moment);
    'tail' (a route's End node, which the history log has no line for) is where the
    open window ends only when nothing follows - otherwise it runs on to the next
    route's start or the task's end, as the history log's does. The same route opened again while its
    window is open is the same start (MaaFW logs every event twice, and the
    recognition and then the action of one Start node). A window still open at the
    end closes at its tail, else at `last`, the log's last stamp: nothing later is
    this run's."""
    out: list[list] = []
    tail = None
    for t, kind, key in events:
        cur = out[-1] if out and out[-1][2] is None else None
        if kind == "tail":
            if cur is not None:
                tail = t
            continue
        if kind == "open" and cur is not None and cur[0] == key:
            continue
        if cur is not None:
            cur[2] = t
        tail = None
        if kind == "open":
            out.append([key, t, None])
    if out and out[-1][2] is None:
        out[-1][2] = tail or last
    return [(a, b, c) for a, b, c in out]


def _naive_beijing(t: datetime) -> datetime:
    return t.astimezone(SERVER_TZ).replace(tzinfo=None) if t.tzinfo else t


def round_until(rec) -> "datetime | None":
    """The upper bound of a MaaEnd round's evidence: its finish + 5 min when its times
    are known (a round judged late must not take the later rounds' pictures and lines,
    audit 2026-10-13 s8 #2), else open."""
    return rec.finished + timedelta(minutes=5) if getattr(rec, "duration_known", False) else None


def round_shots(maaend_dir, started: datetime, until: "datetime | None" = None) -> list[str]:
    """The on_error picture names of the round from `started` to `until` (round_until),
    by the time in each name (shot_time; Beijing, the game PC's clock); a name with no
    time goes by its file time. The one picture set of a round: the outcome check
    (verdict -> outcome.maaend_checks) and machine check #29 both take it, so #29
    cannot fail a run on a picture the outcome check never saw - by file time, a
    picture copied or touched later was the check's by name and not by file."""
    if not maaend_dir:
        return []
    d = Path(maaend_dir) / "debug" / "on_error"
    if not d.is_dir():
        return []
    lo, hi = _naive_beijing(started), (_naive_beijing(until) if until is not None else None)
    out: list[str] = []
    for p in d.glob("*.png"):
        t = shot_time(p.name)
        if t is None:
            try:
                t = _naive_beijing(datetime.fromtimestamp(p.stat().st_mtime, SERVER_TZ))
            except OSError:
                continue
        if in_window(t, lo, hi):
            out.append(p.name)
    return sorted(out)


def obstacle_shots(maaend_dir) -> list[str]:
    """The relay-device pictures (is_obstacle_shot) in MaaEnd's on_error folder, by name."""
    if not maaend_dir:
        return []
    d = Path(maaend_dir) / "debug" / "on_error"
    try:
        return sorted(p.name for p in d.glob("*.png") if is_obstacle_shot(p.name))
    except OSError:
        return []


def route_windows(text: str) -> list[tuple[str, datetime, datetime]]:
    """(route label, start, end) for every route a history log shows MaaEnd starting."""
    events: list[tuple] = []
    last = None
    for line in text.splitlines():
        line = line.strip()
        if (t := line_time(line)) is None:
            continue
        last = t
        if m := _ROUTE_LINE.match(line):
            events.append((t, "close" if _ROUTE_NOT_START.search(m.group(1)) else "open", m.group(1)))
        elif _COLLECT_END.search(line):
            events.append((t, "close", None))
    return spans(events, last)


# Arknights: Endfield's top-center toast when pressing [F] on a relay device during combat:
# 「战斗中无法使用，请脱离战斗后尝试」.
# Upstream MaaEnd's MapNavigatorObstacleDevice clicks any nearby [F] prompt when navigation
# stalls, including ground loot pickups (协议纹石 / 灼壳虫 on 2026-11-23), which open no
# device dialog and still leave an InteractPost on_error picture. On 2026-11-23 Windows OCR
# read two real combat-block shots as 「战斗中无法使用请脱离战斗尝试」 and
# 「戲斗中无法使用，请离战斗后尝沣」; the three ground-loot shots had none of these words.
_OCR_STRIP = re.compile(r"[\s，,。\.、|!！?？:：;；'\"「」『』（）()]+")
_COMBAT_SHOT_CACHE: dict[tuple[str, int, int], bool] = {}
_COMBAT_SHOT_CACHE_LOCK = threading.Lock()


def has_combat_block_text(text: str) -> bool:
    """Whether OCR text from an InteractPost screenshot shows 「战斗中无法使用」."""
    from ark_relay.core import desktop  # noqa: PLC0415
    clean = _OCR_STRIP.sub("", text or "")
    if not clean:
        return False
    if "无法使用" in clean or "脱离战斗" in clean:
        return True
    return (desktop._name_in("战斗中无法使用", clean, max_miss=2)
            or desktop._name_in("请脱离战斗后尝试", clean, max_miss=2))


def is_combat_block_shot(maaend_dir, name: str, *, ocr_fn=None) -> bool:
    """Whether `name` (an InteractPost screenshot) actually shows 「战斗中无法使用」.

    Fail-safe: returns True when `maaend_dir` is omitted, the file is not on disk, or OCR
    is unavailable (None), so filename-only tests and OCR outages never drop a real block.
    """
    if not maaend_dir:
        return True
    path = Path(maaend_dir) / "debug" / "on_error" / name
    try:
        st = path.stat()
    except OSError:
        return True
    key = (str(path), st.st_mtime_ns, st.st_size)
    if ocr_fn is None:
        with _COMBAT_SHOT_CACHE_LOCK:
            cached = _COMBAT_SHOT_CACHE.get(key)
        if cached is not None:
            return cached
        from ark_relay.core import desktop  # noqa: PLC0415
        text = desktop.ocr_image_file(path)
    else:
        text = ocr_fn(path)
    if text is None:
        return True
    hit = has_combat_block_text(text)
    if ocr_fn is None:
        with _COMBAT_SHOT_CACHE_LOCK:
            if len(_COMBAT_SHOT_CACHE) >= 256 and key not in _COMBAT_SHOT_CACHE:
                _COMBAT_SHOT_CACHE.clear()
            _COMBAT_SHOT_CACHE[key] = hit
    if not hit:
        preview = " ".join(text.split())[:80] or "（无文字）"
        log.info("自动采集：%s 截图里没有「战斗中无法使用」（读到：%s），不算被挡", name, preview)
    return hit


def blocked_routes(text: str, shot_names: list[str], maaend_dir=None, *, ocr_fn=None) -> dict[str, list[str]]:
    """{route label: its relay-device pictures} for the routes of `text` that hit
    「战斗中无法使用」, in route order. A picture outside every route window is left out;
    when `maaend_dir` holds the PNG on disk and OCR reads it, pictures without the
    combat-block toast (e.g. ground loot pickups) are left out too."""
    shots = [(t, n) for n in shot_names if is_obstacle_shot(n) and (t := shot_time(n)) is not None]
    out: dict[str, list[str]] = {}
    if not shots:
        return out
    for label, start, end in route_windows(text):
        for t, n in shots:
            if in_window(t, start, end) and is_combat_block_shot(maaend_dir, n, ocr_fn=ocr_fn):
                out.setdefault(label, []).append(n)
    return out


# An essence (基质刷取) failure whose previous MaaEnd message is the claim click
# 「点击确认领取按钮」. It is named a full bag (BAG_FULL) only when the game's
# storage-full notice is logged, here or in the framework log, between the click
# and _STORAGE_FULL_AFTER_S after the failure. Otherwise it stays an ordinary task
# failure and the raw lines from the click to the failure go with it
# (claim_lines -> raw["maaend_claim_lines"]). A proven cause goes in
# raw["maaend_fail_causes"]; the failure name itself is unchanged.
_END_CLAIM_CLICK = re.compile(r"点击确认领取按钮")
_END_FW_LINE = re.compile(r"^\[[^\]]+\]\[(?:ERR|WRN|DBG|INF|TRC)\]")
_END_STAMP = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
_STORAGE_FULL_AFTER_S = 120
BAG_FULL = "背包满了"
CLAIM_UNCONFIRMED = "点了确认领取后失败，没看到仓储已满的提示"
# How many raw lines go with a claim failure, per log: the first and last lines
# of the stretch, each cut to CLAIM_LINE_CHARS.
CLAIM_HEAD_LINES = 4
CLAIM_TAIL_LINES = 10
CLAIM_LINE_CHARS = 200


def _stamp(line: str) -> "datetime | None":
    m = _END_STAMP.match(line)
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None
    except ValueError:
        return None


def _storage_full_times(text: str) -> list[datetime]:
    """When the game's storage-full notice was on screen, from any log lines."""
    return [t for line in text.splitlines()
            if _END_STORAGE_FULL in line and (t := _stamp(line)) is not None]


def _claim_failures(lines: list[str]) -> list[tuple[str, int, int]]:
    """(task, claim-click line, failure line) for every 基质刷取 failure whose
    previous MaaEnd message (framework lines skipped) is the claim click."""
    out: list[tuple[str, int, int]] = []
    last, last_i = "", -1
    for i, line in enumerate(lines):
        if m := _END_TASK_FAIL.search(line):
            name = _strip_emoji(m.group(1))
            if "基质刷取" in name and _END_CLAIM_CLICK.search(last):
                out.append((name, last_i, i))
            last, last_i = "", -1
        elif line.strip() and not _END_FW_LINE.match(line):
            last, last_i = line, i
    return out


def _maaend_fail_causes(text: str, fw_text: str = "") -> dict:
    """{failed task name: BAG_FULL} for essence failures proven to be a full bag.

    An essence failure right after the claim click is a full bag only when the
    storage-full notice shows up (in this log or in `fw_text`, MaaEnd's
    framework log) between the click and _STORAGE_FULL_AFTER_S after the
    failure. Without the notice no cause is named (claim_lines carries the raw
    lines instead)."""
    causes: dict = {}
    notices = _storage_full_times(text + "\n" + fw_text)
    lines = text.splitlines()
    for name, ci, fi in _claim_failures(lines):
        click, failed = _stamp(lines[ci]), _stamp(lines[fi])
        if click and failed and any(
                click <= t <= failed + timedelta(seconds=_STORAGE_FULL_AFTER_S) for t in notices):
            causes[name] = BAG_FULL
    return causes


LOGGED_OUT_TEXT = "登录认证已失效"
LOGGED_OUT = "这个号在别的设备上登录了，游戏弹「登录认证已失效」，之后进不了游戏"


# 2026-11-20 09:32 (#187): the game opened on a one-time 「协议更新」 dialog (游戏个人信息保护政策,
# [取消]/[同意]); MaaEnd has no node for it, so each of 15 tasks waited 5 min 33 s and failed,
# and the alarm said 「卡在 赠送干员礼物、装备制造、拜访好友…」 with nothing about the dialog. MaaEnd's
# OCR reads the dialog's line into its framework log. Nothing here clicks 同意: that is
# accepting an agreement, which is the account owner's to do.
AGREEMENT_TEXT = "请您仔细阅读并同意以下协议"
AGREEMENT = "游戏停在「协议更新」窗口，要人点同意"


# A dialog read this long before the task's own 「任务开始」 line still counts as read during it:
# MaaFW's start event and AUTO-MAS's line differ by up to a second (11-20: 09:34:27.414 / .524).
TASK_START_SLACK_S = 5


def _line_or_stamp(line: str) -> "datetime | None":
    return line_time(line) or _stamp(line)


def _causes_from_reads(text: str, reads: list[datetime], cause: str, *, during: bool = False) -> "tuple[str, dict]":
    """Match framework-log dialog timestamps `reads` against failed tasks in `text`."""
    if not reads:
        return "", {}
    at = reads[0]
    causes: dict = {}
    started: "tuple[str, datetime] | None" = None
    prev_end: "datetime | None" = None
    matched_reads: list[datetime] = []
    for line in text.splitlines():
        if (m := _END_TASK_START.search(line)) and (t := _line_or_stamp(line)):
            started = (_strip_emoji(m.group(1)), t)
        elif _END_TASK_DONE.search(line) and (t := _line_or_stamp(line)):
            prev_end = t
            started = None
        elif (m := _END_TASK_FAIL.search(line)) and (t := _line_or_stamp(line)):
            name = _strip_emoji(m.group(1))
            if during:
                if started is not None and started[0] == name:
                    lo_t = started[1] - timedelta(seconds=TASK_START_SLACK_S)
                    if prev_end is not None:
                        lo_t = max(lo_t, prev_end)
                    hits = [r for r in reads if lo_t <= r <= t and (prev_end is None or r > prev_end)]
                    if hits:
                        causes[name] = cause
                        matched_reads.append(hits[0])
            elif t >= at:
                causes[name] = cause
            prev_end = t
            started = None
    if not causes:
        return "", {}
    if during:
        return min(matched_reads).strftime("%H:%M:%S"), causes
    return at.strftime("%H:%M:%S"), causes


def _add_logged_out(text: str, maaend_dir, failed: list[str], causes: dict, out: dict) -> dict:
    """`causes` with LOGGED_OUT for the tasks that failed at or after that dialog and
    AGREEMENT for those with a read during the task, out["maaend_logged_out_at"] /
    out["maaend_agreement_at"] set; unchanged when nothing failed or neither was seen.
    A cause already proven (a full bag) stays; for a task after both, the logout is named.
    Scans the framework logs once for both dialogs (~90 MB a file)."""
    if not failed or not maaend_dir:
        return causes
    stamps = [t for line in text.splitlines() if (t := _line_or_stamp(line))]
    if not stamps:
        return causes
    t0, t1 = min(stamps), max(stamps)
    q0 = t0 - timedelta(seconds=TASK_START_SLACK_S)
    out_forms = (LOGGED_OUT_TEXT, json.dumps(LOGGED_OUT_TEXT).strip('"'))
    agr_forms = (AGREEMENT_TEXT, json.dumps(AGREEMENT_TEXT).strip('"'))
    all_forms = out_forms + agr_forms
    hits = _fw_lines(_fw_files(maaend_dir, q0, t1), q0, t1, lambda line: any(x in line for x in all_forms))
    out_reads = sorted(t for h in hits if any(x in h for x in out_forms) and (t := _line_or_stamp(h)) and t >= t0)
    agr_reads = sorted(t for h in hits if any(x in h for x in agr_forms) and (t := _line_or_stamp(h)) and t >= q0)
    at, lost = _causes_from_reads(text, out_reads, LOGGED_OUT, during=False)
    if at:
        out["maaend_logged_out_at"] = at
    agreed_at, held = _causes_from_reads(text, agr_reads, AGREEMENT, during=True)
    if agreed_at:
        out["maaend_agreement_at"] = agreed_at
    if not (at or agreed_at):
        return causes
    return {**held, **lost, **causes}


def _cap(lines: list[str]) -> list[str]:
    """The first CLAIM_HEAD_LINES and last CLAIM_TAIL_LINES of `lines`, each cut to
    CLAIM_LINE_CHARS, with one line saying how many were left out between."""
    from ark_relay.core import texts  # noqa: PLC0415
    cut = [x if len(x) <= CLAIM_LINE_CHARS else x[:CLAIM_LINE_CHARS] + "…" for x in lines]
    if len(cut) <= CLAIM_HEAD_LINES + CLAIM_TAIL_LINES:
        return cut
    skipped = len(cut) - CLAIM_HEAD_LINES - CLAIM_TAIL_LINES
    return cut[:CLAIM_HEAD_LINES] + [texts.claim_lines_skipped(skipped)] + cut[-CLAIM_TAIL_LINES:]


def claim_failures(text: str) -> list[tuple[str, str, str]]:
    """(task, claim-click line, failure line) for every 基质刷取 failure right after
    the claim click, the case _maaend_fail_causes and claim_lines are about."""
    lines = text.splitlines()
    return [(name, lines[ci], lines[fi]) for name, ci, fi in _claim_failures(lines)]


def claim_lines(text: str, maaend_dir=None, causes: dict | None = None) -> dict:
    """{task: {"run": [...], "fw": [...], "fw_why": "..."}} for every essence failure
    right after the claim click that is not a proven full bag: the raw lines of
    this log from the click to the failure, and MaaEnd's framework-log lines of
    the same seconds (maafw_window), each capped (_cap). A task failing so more
    than once in the log keeps its last stretch."""
    out: dict = {}
    lines = text.splitlines()
    for name, ci, fi in _claim_failures(lines):
        if (causes or {}).get(name) == BAG_FULL:
            continue
        click, failed = _stamp(lines[ci]), _stamp(lines[fi])
        fw, why = (maafw_window(maaend_dir, click, failed) if click and failed
                   else ([], "这两行日志没有时间"))
        out[name] = {"run": _cap(lines[ci:fi + 1]), "fw": _cap(fw), "fw_why": why}
    return out


def _strip_emoji(name: str) -> str:
    return re.sub(r"^[^\w一-鿿]+", "", name).strip()


_LINE_STAMP = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[.\d]*\] (.*)$")
_END_ITEMS_HEAD = re.compile(r"^获得以下物品[:：]\s*$")
_END_ITEM = re.compile(r"^([^\[\s].*?)\s*[×x]\s*(\d+)\s*$")


def _msg(line: str) -> str:
    """The message part of a MaaEnd log line (the line itself if unstamped)."""
    m = _LINE_STAMP.match(line)
    return m.group(2) if m else line


def _item_blocks(lines: list[str]) -> dict[str, int]:
    """Sum every 「获得以下物品：」 block in `lines` into {item: count}."""
    got: dict[str, int] = {}
    in_block = False
    for line in lines:
        msg = _msg(line).strip()
        if _END_ITEMS_HEAD.match(msg):
            in_block = True
            continue
        if in_block and (m := _END_ITEM.match(msg)):
            name = m.group(1).strip()
            got[name] = got.get(name, 0) + int(m.group(2))
            continue
        in_block = False
    return got


def _prints_item_blocks(text: str) -> bool:
    """Does this log contain 「获得以下物品：」 blocks? Older MaaEnd logs (the
    2026-08-24/25 samples in test_maaend_watchdog.py) have none and are read by the
    older wording."""
    return any(_END_ITEMS_HEAD.match(_msg(x).strip()) for x in text.splitlines())


def _claim_landed(tail: list[str]) -> bool:
    """In a block-era log: did the claim after the last sanity reading land?"""
    tried = False
    for line in tail:
        msg = _msg(line).strip()
        if _END_SANITY_SPENT.search(msg):
            tried = True
        elif tried and _END_ITEMS_HEAD.match(msg):
            return True
        elif tried and (_END_SANITY_REFUSED.search(msg) or _END_SANITY_OUT.search(msg)
                        or _END_TASK_DONE.search(msg) or _END_TASK_FAIL.search(msg)):
            return False
    return False


def _claim_costs(text: str) -> list[int]:
    """Sanity each 「当前理智」 reading's settlement cost, one entry per reading
    (0 when no claim landed after it, e.g. the reading on the level screen).

    A landed claim (_claim_landed) costs _END_PS_COST when the reading plus the
    potions used before the next reading pay for it, else half: the game then
    pays out the single reward (10-07, 10-08, 10-11 and 10-12 logs: 34000 折金票
    instead of 68000 whenever that sum was below 160).
    """
    lines = text.splitlines()
    at = [i for i, x in enumerate(lines) if _END_SANITY.search(x)]
    costs = []
    for k, i in enumerate(at):
        seg = lines[i:at[k + 1] if k + 1 < len(at) else None]
        if not _claim_landed(seg):
            costs.append(0)
            continue
        have = int(_END_SANITY.search(lines[i]).group(1))
        have += sum(1 for x in seg if _END_POTION.search(x)) * _END_POTION_SANITY
        costs.append(_END_PS_COST if have >= _END_PS_COST else _END_PS_COST // 2)
    return costs


def _claims_fit(text: str) -> bool:
    """Does every 「当前理智」 reading in a block-era log equal the previous
    reading plus its potions (_END_POTION_SANITY each) minus its claim
    (_claim_costs), give or take what regenerated in between (one point per
    _END_SANITY_SEC_PER_POINT, plus one for a partly regenerated point)?

False means the per-claim rule does not describe this run, so the spent and
    left it gives are not reported as figures.
    """
    lines = text.splitlines()
    at = [i for i, x in enumerate(lines) if _END_SANITY.search(x)]
    costs = _claim_costs(text)
    for k in range(len(at) - 1):
        i, j = at[k], at[k + 1]
        if not any(_END_SANITY_SPENT.search(x) for x in lines[i:j]):
            continue
        have = int(_END_SANITY.search(lines[i]).group(1))
        nxt = int(_END_SANITY.search(lines[j]).group(1))
        want = have + sum(1 for x in lines[i:j] if _END_POTION.search(x)) * _END_POTION_SANITY - costs[k]
        regen = 0
        a, b = _LINE_STAMP.match(lines[i]), _LINE_STAMP.match(lines[j])
        if a and b:
            sec = (datetime.strptime(b.group(1), "%Y-%m-%d %H:%M:%S")
                   - datetime.strptime(a.group(1), "%Y-%m-%d %H:%M:%S")).total_seconds()
            regen = max(0, int(sec)) // _END_SANITY_SEC_PER_POINT
        if not want <= nxt <= want + regen + 1:
            return False
    return True


def _farm_segment(lines: list[str]) -> tuple[str, int, "int | None"]:
    """(task name, first line, last line or None) of the farming task, or
    ("", -1, None) when there is none.
    """
    start = end = None
    farm = ""
    for i, line in enumerate(lines):
        if m := _END_TASK_START.search(line):
            name = _strip_emoji(m.group(1))
            if any(k in name for k in _END_FARM_TASKS):
                start, farm = i, name
        elif start is not None and (m := _END_TASK_DONE.search(line) or _END_TASK_FAIL.search(line)):
            if _strip_emoji(m.group(1)) == farm:
                end = i
                break
    if start is not None:
        return farm, start, end
    # Fallback: a task's lines run to its own 「任务完成/失败」, or to the next
    # 「任务开始」 when it never reports one.
    cur = ""
    begin = -1
    for i, line in enumerate(lines + ["任务开始: <eof>"]):
        if m := _END_TASK_START.search(line):
            if cur and any(_END_SANITY.search(x) for x in lines[begin:i]):
                return cur, begin, None if i >= len(lines) else i - 1
            cur, begin = _strip_emoji(m.group(1)), i
        elif cur and (m := _END_TASK_DONE.search(line) or _END_TASK_FAIL.search(line)):
            if _strip_emoji(m.group(1)) == cur:
                if any(_END_SANITY.search(x) for x in lines[begin:i + 1]):
                    return cur, begin, i
                cur = ""
    return "", -1, None


def _schedule_skipped(text: str) -> dict[str, str]:
    """{task name: weekday} for every task MaaEnd skipped by its 执行周期."""
    return {_strip_emoji(m.group(1)): m.group(2) for m in _END_SCHEDULE_SKIP.finditer(text)}


def _named_farm_segments(lines: list[str]) -> list[tuple[str, int, "int | None"]]:
    """Every farming task found by name, each to its own 「任务完成/失败」 (or to
    the next 「任务开始」). One round can run both ProtocolSpace and AutoEssence."""
    segs: list[tuple[str, int, "int | None"]] = []
    cur, begin = "", -1
    for i, line in enumerate(lines):
        if m := _END_TASK_START.search(line):
            if cur:
                segs.append((cur, begin, i - 1))
                cur = ""
            name = _strip_emoji(m.group(1))
            if any(k in name for k in _END_FARM_TASKS):
                cur, begin = name, i
        elif cur and (m := _END_TASK_DONE.search(line) or _END_TASK_FAIL.search(line)):
            if _strip_emoji(m.group(1)) == cur:
                segs.append((cur, begin, i))
                cur = ""
    if cur:
        segs.append((cur, begin, None))
    return segs


def _maaend_farm(text: str) -> dict:
    """The farming section: what was farmed, where, how many runs, what
    dropped. Returns {} when there is no farming task. Several farming tasks in
    one round are each read and added up.
    """
    lines = text.splitlines()
    skipped = _schedule_skipped(text)
    segs = [x for x in _named_farm_segments(lines) if x[0] not in skipped]
    if len(segs) <= 1:
        return _farm_one(text, lines, *(segs[0] if segs else _farm_segment(lines)), skipped)
    parts = [_farm_one(text, lines, *x, skipped) for x in segs]
    met = any(x.get("maaend_essence_met") for x in parts)
    parts = [x for x in parts if x.get("maaend_farm")]
    out: dict = {"maaend_essence_met": True} if met else {}
    if not parts:
        return out
    out["maaend_farm"] = "、".join(x["maaend_farm"] for x in parts)
    if places := [x["maaend_farm_place"] for x in parts if x.get("maaend_farm_place")]:
        out["maaend_farm_place"] = places[0]
    if runs := sum(x.get("maaend_farm_runs", 0) for x in parts):
        out["maaend_farm_runs"] = runs
    drops: dict[str, int] = {}
    for x in parts:
        for k, n in (x.get("maaend_farm_drops") or {}).items():
            drops[k] = drops.get(k, 0) + n
    if drops:
        out["maaend_farm_drops"] = drops
    ran = [x for x in parts if x.get("maaend_farm_runs")]
    if ran and all(x.get("maaend_sanity_spent") for x in ran):
        out["maaend_sanity_spent"] = sum(x["maaend_sanity_spent"] for x in ran)
    elif runs:
        # A part without its own figure: let the report work it out from the
        # day's readings rather than print a partial sum as the total.
        out["maaend_sanity_runs_only"] = runs
    return out


def _farm_one(text: str, lines: list[str], farm: str, start: int, end, skipped: dict) -> dict:
    """_maaend_farm for one farming task's lines."""
    out: dict = {}
    if not farm or farm in skipped:
        return out          # a weekday-skipped farming task farmed nothing
    seg = lines[start:(end + 1) if end is not None else None]
    body = "\n".join(seg)
    if _END_ESSENCE_MET.search(body) and not _END_ESSENCE_DONE.search(body):
        return {"maaend_essence_met": True}
    out["maaend_farm"] = farm
    if m := _END_PLACE.search(body):
        out["maaend_farm_place"] = m.group(1)
    # Runs: one 「已完成一次基质刷取」 each. Otherwise, in a log with item blocks,
    # one block inside the task (an entry whose claim was refused prints none);
    # in older logs, one 「进入协议空间成功」 each.
    runs = len(_END_ESSENCE_DONE.findall(body))
    if not runs:
        if _prints_item_blocks(text):
            runs = sum(1 for x in seg if _END_ITEMS_HEAD.match(_msg(x).strip()))
        else:
            runs = len(_END_PS_ENTER.findall(body))
    if runs:
        out["maaend_farm_runs"] = runs
    # Drops from three sources, added together: one 「是X基质」 line per essence,
    # the older single-line 「获得 X ×n」, and item blocks. In the fixture logs
    # blocks occur only in 协议空间 and 「是X基质」 only in 基质刷取, so they do
    # not overlap.
    drops: dict[str, int] = {}
    for line in seg:
        if m := _END_ESSENCE_DROP.search(line.split("] ", 1)[-1]):
            drops[m.group(1)] = drops.get(m.group(1), 0) + 1
        elif m := _END_GAIN.search(line):
            drops[m.group(1).strip()] = drops.get(m.group(1).strip(), 0) + int(m.group(2))
    for name, n in _item_blocks(seg).items():
        drops[name] = drops.get(name, 0) + n
    if drops:
        out["maaend_farm_drops"] = drops
    readings = [int(a) for a, _ in _END_SANITY.findall(body)]
    steps = [a - b for a, b in zip(readings, readings[1:], strict=False) if a > b]
    # 「当前理智」 is logged before each claim and not after the last one, so n
    # claims give n-1 steps. Spent = runs x the cost of one run, where the cost is
    # the largest step not above 1.5x the median step (a step is the cost minus
    # what regenerated meanwhile; a step above 1.5x the median spans a missed
    # reading).
    if steps and runs:
        med = sorted(steps)[len(steps) // 2]
        out["maaend_sanity_spent"] = runs * max(x for x in steps if x <= med * 1.5)
    elif runs and len(readings) >= 2:
        out["maaend_sanity_spent"] = readings[0] - readings[-1]
    # One run with one reading has no step: the caller fills the figure in from
    # the day's previous record.
    elif runs:
        out["maaend_sanity_runs_only"] = runs
    return out


_TASK_START = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[.\d]*\]\s*任务开始:\s*(.+)")
_TASK_END = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[.\d]*\]\s*任务(完成|失败):\s*(.+)")
_UNREACHABLE_QUICK_SEC = 30
_UNREACHABLE_MIN_FAILS = 3


def maaend_unreachable(text: str) -> bool:
    """Every task failed within half a minute and none completed: the run
    looks like it never got into the game.

    This is the shape of the log only: a local fault (lost game window, crash
    at the title screen) has it too. The parser records it as
    `maaend_unreachable_shape`; handle._confirm_unreachable turns it into
    `maaend_unreachable` (no alarm, no make-up) only when an official maintenance
    window or update notice says the game was unavailable.
    """
    starts: dict[str, datetime] = {}
    fails = done = quick = 0
    for line in text.splitlines():
        if m := _TASK_START.search(line):
            starts[m.group(2).strip()] = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            continue
        if not (m := _TASK_END.search(line)):
            continue
        name = m.group(3).strip()
        if "结束进程" in name:
            continue          # A wrap-up task, not an in-game one
        if m.group(2) == "完成":
            done += 1
            continue
        fails += 1
        t0 = starts.get(name)
        t1 = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        if t0 is not None and (t1 - t0).total_seconds() <= _UNREACHABLE_QUICK_SEC:
            quick += 1
    return done == 0 and fails >= _UNREACHABLE_MIN_FAILS and quick == fails


# A task's own status lines; anything else MaaEnd logged between a task's start
# and its finish is something it read or did in the game.
_TASK_STATUS = re.compile(r"^任务(开始|完成|失败)[:：]\s*(\S.+?)\s*$")


def task_evidence(text: str) -> dict[str, str]:
    """{task: evidence} for every task with a 「任务完成」 line; evidence '' = none.

    Evidence is the first timestamped line MaaEnd wrote between that task's
    start and finish lines other than the status lines themselves: an item
    gained, a sanity reading, "no emergency sanity potion in stock" (see
    tests/fixtures/maaend_full_2026-09-01.log). A task run twice in one log keeps
    the attempt that had evidence."""
    out: dict[str, str] = {}
    cur, first = "", ""
    for line in text.splitlines():
        m = _LINE_STAMP.match(line)
        if not m:
            continue
        msg = m.group(2).strip()
        if st := _TASK_STATUS.match(msg):
            name = _strip_emoji(st.group(2))
            if st.group(1) == "开始":
                cur, first = name, ""
                continue
            if st.group(1) == "完成" and name == cur and (name not in out or first):
                out[name] = first
            cur, first = "", ""
            continue
        if cur and not first and msg and not _NOT_EVIDENCE.search(msg):
            first = msg[:80]
    return out


_NOT_EVIDENCE = re.compile(r"^正在检查画面|^UID显示不完整|\[(?:ERR|WRN)\]|FailureCollector")


def task_times(text: str) -> dict[str, tuple[datetime, datetime]]:
    """{task: (start, finish)} from 「任务开始」 / 「任务完成」, naive machine-local times; last attempt wins."""
    out: dict[str, tuple[datetime, datetime]] = {}
    starts: dict[str, datetime] = {}
    for line in text.splitlines():
        m = _LINE_STAMP.match(line)
        st = _TASK_STATUS.match(m.group(2).strip()) if m else None
        if not st:
            continue
        name = _strip_emoji(st.group(2))
        at = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        if st.group(1) == "开始":
            starts[name] = at
        elif st.group(1) == "完成" and name in starts:
            out[name] = (starts[name], at)
    return out


def _sanity_fields(text: str, hits: list, out: dict) -> None:
    """parse_maaend_log's sanity part: sanity, sanity_cap, sanity_read_at and the
    Protocol Space spend, from the 「当前理智」 readings (`hits`, _END_SANITY.findall)."""
    got, cap = (int(x) for x in hits[-1])
    # 「当前理智」 is read on the settlement screen, before the claim that
    # charges sanity; a claim after the last reading is taken off.
    readings = [int(a) for a, _ in hits]
    drops = [a - b for a, b in zip(readings, readings[1:], strict=False) if a > b]
    blocks = _prints_item_blocks(text)
    if blocks:
        # Each claim is charged by one rule (_claim_cost): what is left is the
        # last reading plus later potions minus the last claim, and spent is
        # the sum of all claims, so the two always agree.
        costs = _claim_costs(text)
        fits = _claims_fit(text)
        got += len(_END_POTION.findall(text[text.rfind("当前理智"):])) * _END_POTION_SANITY
        got -= costs[-1]
    else:
        # Only the last settlement decides, read from the text after the last
        # reading.
        tail = text[text.rfind("当前理智"):]
        if _END_SANITY_SPENT.search(tail) and not _END_SANITY_REFUSED.search(tail):
            got -= max(drops) if drops else _END_PS_COST
    # A negative result is floored to 0: a lower bound, not a reading
    # (collector._enrich_record gives no full-again time for it). An exact 0
    # is the rule's own figure, e.g. 160 read, one double claim.
    out["sanity_floored"] = got < 0
    got = max(0, got)
    # AUTO-MAS records sanity as 0 for MaaEnd; parse_record fills empty raw
    # fields from here.
    out["sanity"] = got
    out["sanity_cap"] = cap
    # When the last reading was taken (machine clock): the full-again time
    # counts from here, not from the record's finish (collector._enrich_record).
    if at := next((m.group(1) for x in reversed(text.splitlines())
                   if _END_SANITY.search(x) and (m := _LINE_STAMP.match(x))), ""):
        out["sanity_read_at"] = at
    # Protocol Space alone: _farm_one's step estimate gives 0 for one run (its
    # two readings are equal) and charges a half last claim in full.
    farm = out.get("maaend_farm") or ""
    if blocks and "协议空间" in farm and "、" not in farm and out.get("maaend_farm_runs") and sum(costs):
        out["maaend_sanity_spent"] = sum(costs)
        out.pop("maaend_sanity_runs_only", None)
    if blocks and not fits:
        # The readings do not follow the rule: no figure, and none filled in
        # from the day's other records either (report._fill_single_run_sanity).
        out.pop("maaend_sanity_spent", None)
        out.pop("maaend_sanity_runs_only", None)
        out["maaend_sanity_unfit"] = True


def parse_maaend_log(log_path: Path, maaend_dir=None) -> dict:
    """Recover items gained and tasks finished from a MaaEnd log. {} if unreadable.

    `maaend_dir` lets a failure's cause be proven from MaaEnd's own framework
    log (_maaend_fail_causes); without it a full bag cannot be proven and the
    essence failure is an ordinary one, with its raw lines (claim_lines).
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out_flags: dict = {}
    if maaend_unreachable(text):
        # The shape only; see maaend_unreachable for why it silences nothing.
        out_flags["maaend_unreachable_shape"] = True

    gains: dict[str, int] = {}
    tasks: list[str] = []
    for line in text.splitlines():
        if m := _END_GAIN.search(line):
            name = m.group(1).strip()
            gains[name] = gains.get(name, 0) + int(m.group(2))
        elif m := _END_TASK_DONE.search(line):
            name = _strip_emoji(m.group(1))
            if name and name not in tasks:
                tasks.append(name)

    out: dict = {}
    if gains:
        out["drop_statistics"] = gains
    # A task skipped by its weekday schedule still prints 「任务完成」; it is
    # reported as skipped, not as done.
    skipped = _schedule_skipped(text)
    tasks = [t for t in tasks if t not in skipped]
    if skipped:
        out["maaend_tasks_skipped"] = skipped
    if tasks:
        out["tasks_done"] = tasks
        # What each finished task left in the log besides 「任务完成」 (core.task_unverified).
        out["tasks_evidence"] = task_evidence(text)
    failed = [_strip_emoji(m.group(1)) for m in _END_TASK_FAIL.finditer(text)]
    failed = [f for f in failed if "结束进程" not in f]
    if failed:
        out["tasks_failed"] = list(dict.fromkeys(failed))
    # The framework logs run to ~90 MB each; read them only when a claim click
    # is there to be explained, bounded to this run's window (+ storage-full slack).
    fw = ""
    if _END_CLAIM_CLICK.search(text):
        stamps = [t for ln in text.splitlines() if (t := _line_or_stamp(ln))]
        fw = (maafw_text(maaend_dir, min(stamps), max(stamps) + timedelta(seconds=_STORAGE_FULL_AFTER_S))
              if stamps else maafw_text(maaend_dir))
    causes = _add_logged_out(text, maaend_dir, failed, _maaend_fail_causes(text, fw), out)
    if causes:
        out["maaend_fail_causes"] = causes
    if _END_CLAIM_CLICK.search(text) and (claim := claim_lines(text, maaend_dir, causes)):
        out["maaend_claim_lines"] = claim
    if runs := len(_END_PS_ENTER.findall(text)):
        out["protocol_runs"] = runs
    out.update(_maaend_farm(text))
    if n := len(_END_MEDICINE.findall(text)):
        out["maaend_medicine"] = n
    if m := _END_COLLECT_ROUTES.findall(text):
        out["maaend_collect_routes"] = int(m[-1])
    # 自动采集 skipped because today is not one of its weekdays.
    if m := _END_COLLECT_SKIP.search(text):
        out["maaend_collect_skipped"] = m.group(1)
    # Routes walked: distinct 「路线N：」 / 「线路N：」 numbers (MaaEnd spells the
    # first routes 线路) or v2.36+ item routes 「采集<Item>」 (ledger #122/#134);
    # routes that gathered nothing: those with 「采集失败」.
    started = set(re.findall(r"(?:路线|线路)(\d+)[：:]", text))
    if started:
        failed_r = set(re.findall(r"(?:路线|线路)(\d+)[：:][^\n]*采集失败", text))
        blocked = blocked_routes(text, obstacle_shots(maaend_dir), maaend_dir=maaend_dir) if maaend_dir else {}
        blocked_r = {m.group(1) for lbl in blocked if (m := re.search(r"(\d+)[：:]", lbl))}
        if failed_lines := re.findall(r"((?:路线|线路)(\d+)[：:][^\n]*?)采集失败", text):
            out["maaend_collect_failed"] = list(dict.fromkeys(lbl.strip() for lbl, _ in failed_lines))
            out["maaend_collect_failed_ids"] = list(dict.fromkeys(f"Route{n}" for _, n in failed_lines))
    else:
        v236_started = list(dict.fromkeys(_V236_ROUTE_START.findall(text)))
        started = set(v236_started)
        v236_failed = list(dict.fromkeys(re.findall(r"(?m)^\[[^\]]+\]\s*(?!(?:路线|线路)\d+[：:])([^\s：:]+?)采集失败\s*$", text)))
        _add_collector_failed(text, maaend_dir, v236_failed, out)
        failed_r = set(v236_failed) & started
        blocked = blocked_routes(text, obstacle_shots(maaend_dir), maaend_dir=maaend_dir) if started and maaend_dir else {}
        blocked_r = {lbl.removeprefix("采集") for lbl in blocked} & started
        if v236_failed:
            out["maaend_collect_failed"] = [f"采集{it}" for it in v236_failed if it in started] or v236_failed
    # Routes that walked through but hit 「战斗中无法使用」 gathered nothing either
    # (blocked_routes); they are booked apart, with the reason, for the daily row.
    if blocked:
        out["maaend_collect_blocked"] = list(blocked)
    if started:
        out["maaend_collect_done"] = len(started - failed_r - blocked_r)
        out["maaend_collect_total"] = len(started)
    if hits := _END_SANITY.findall(text):
        _sanity_fields(text, hits, out)
    if _END_SANITY_OUT.search(text):
        out["sanity_exhausted"] = True
    out.update(out_flags)
    return out

__all__ = ['BAG_FULL', 'CLAIM_HEAD_LINES', 'CLAIM_LINE_CHARS', 'CLAIM_TAIL_LINES', 'CLAIM_UNCONFIRMED', 'AGREEMENT', 'AGREEMENT_TEXT', 'LOGGED_OUT', 'LOGGED_OUT_TEXT', 'OBSTACLE_SHOT', 'UPDATE_AT_START_S', 'UPDATE_INSTALL_S', '_FW_META', '_FW_PICK', '_MXU_INSTALLED', '_MXU_PENDING', '_MXU_STAMP', '_fw_files', 'blocked_routes', 'claim_failures', 'claim_lines', 'has_combat_block_text', 'in_window', 'is_combat_block_shot', 'is_obstacle_shot', 'maaend_unreachable', 'maafw_grep', 'obstacle_shots', 'parse_maaend_log', 'line_time', 'round_shots', 'round_until', 'route_windows', 'shot_time', 'spans', 'task_evidence', 'task_times', 'update_restart_version']
