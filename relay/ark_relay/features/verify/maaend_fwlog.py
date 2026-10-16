"""Read MaaEnd's two side logs: the MaaFW framework log and MXU's own app log.

* Framework log: `<maaend>/debug/maafw*.log` and `<maaend>/debug/cpp-algo/debug/maafw*.log`
  (current and rotated). Every line starts with `[YYYY-MM-DD HH:MM:SS.mmm][LVL]`;
  a second process repeats each event line.
* MXU app log: `<maaend>/debug/YYYY-MM-DD-N.log`, one per MaaEnd launch, lines
  starting with `YYYY-MM-DD HH:MM:SS `.

collector_maaend re-exports every public name here.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

# The game's storage-full notice as MaaEnd's OCR logs it.
_END_STORAGE_FULL = "仓储空间已满"

# Strips the process / thread / source-file brackets between a framework line's
# stamp+level and its message.
_FW_META = re.compile(r"^(\[[^\]]+\]\[[A-Z]{3}\])(?:\[Px\d+\]\[Tx\d+\](?:\[[^\]]*\])?(?:\[L\d+\])?(?:\[[^\]]*\])?)?\s*")
# Framework event lines and ERR / WRN lines.
_FW_PICK = re.compile(r"\[msg=|^\[[^\]]+\]\[(?:ERR|WRN)\]")

# MXU app log lines, e.g. 2026-10-01-4.log:
#   2026-10-01 16:11:06 INFO  [App] 检测到待安装更新: v2.31.0-beta.6
#   2026-10-01 16:11:07 INFO  [App] 更新安装完成
_MXU_STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ")
_MXU_PENDING = re.compile(r"检测到待安装更新: (\S+)")
_MXU_INSTALLED = "更新安装完成"
# The pending line must fall within UPDATE_AT_START_S of the attempt's start, and
# the installed line within UPDATE_INSTALL_S after the pending line.
UPDATE_AT_START_S = (-2, 30)
UPDATE_INSTALL_S = 30


def _fw_files(maaend_dir) -> list[Path]:
    debug = Path(maaend_dir) / "debug"
    return sorted([*debug.glob("maafw*.log"), *(debug / "cpp-algo" / "debug").glob("maafw*.log")])


def _fw_lines(files: list[Path], t0: datetime, t1: datetime, want=None) -> list[str]:
    """Lines of `files` stamped from t0 to t1 (whole seconds) for which `want(line)`
    holds (every line when `want` is None), trailing newline removed. Unreadable
    files are skipped."""
    lo, hi = f"[{t0:%Y-%m-%d %H:%M:%S}", f"[{t1:%Y-%m-%d %H:%M:%S}~"
    out: list[str] = []
    for f in files:
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                out.extend(line.rstrip("\n") for line in fh
                           if lo <= line[:24] <= hi and (want is None or want(line)))
        except OSError:
            continue
    return out


def _short(line: str) -> "tuple[str, str]":
    """(the line without the bracket metadata, its message body)."""
    short = _FW_META.sub(r"\1 ", line)
    return short, short.split("]", 2)[-1]


def maafw_text(maaend_dir) -> str:
    """The storage-full lines of MaaEnd's framework logs, or "" when there is no
    directory or nothing to read."""
    if not maaend_dir:
        return ""
    out: list[str] = []
    for f in _fw_files(maaend_dir):
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                out.extend(line for line in fh if _END_STORAGE_FULL in line)
        except OSError:
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
    files = _fw_files(maaend_dir)
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
    found = _fw_lines(_fw_files(maaend_dir), t0, t1, lambda line: any(x in line for x in forms))
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



# One MaaFW event line: [msg=Tasker.Task.Starting] [details={...}] (maafw.log, 2026-10-16:
# 「[msg=Tasker.Task.Succeeded] [details={"entry":"GiftOperatorMain",...,"task_id":200000001,...}]」).
_FW_EVENT = re.compile(r"\[msg=(Tasker\.Task\.\w+|Node\.PipelineNode\.Succeeded)\]\s*\[details=(\{.*\})\]\s*$")
_FW_AT = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)\]")
# AUTO-MAS prints 「任务开始」 up to a second after MaaFW's Tasker.Task.Starting
# (2026-10-16: 13:54:59.034 against 13:54:58.249), so windows are read this much wider.
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
    lines = _fw_lines(_fw_files(maaend_dir), lo, hi,
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

    The nodes are every Node.PipelineNode.Succeeded between that start and end,
    whatever task_id they carry: a custom action runs its work as a sub-task of its
    own (environment monitoring, 2026-10-08 09:41: task 200000008 was posted, the
    photo job ran as 200000559 - EternalSunsetExecute, AcceptEternalSunset,
    EnvironmentMonitoringTakePhoto). MaaEnd runs one task at a time, so the stretch
    holds only this task's work. The second process repeats every event line;
    (task_id, node_id) counts it once."""
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
    nodes: dict = {}
    seen: set = set()
    for w, msg, d in events:
        if msg != "Node.PipelineNode.Succeeded" or w < started or (ended is not None and w > ended):
            continue
        key = (d.get("task_id"), d.get("node_id"))
        if key in seen:
            continue
        seen.add(key)
        name = str(d.get("name") or "")
        nodes[name] = nodes.get(name, 0) + 1
    return {"started": started, "ended": ended, "result": result, "nodes": nodes}
