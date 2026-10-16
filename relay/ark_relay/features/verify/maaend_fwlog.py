"""Read MaaEnd's two side logs: the MaaFW framework log and MXU's own app log.

* Framework log: `<maaend>/debug/maafw*.log` and `<maaend>/debug/cpp-algo/debug/maafw*.log`
  (current and rotated). Every line starts with `[YYYY-MM-DD HH:MM:SS.mmm][LVL]`;
  a second process repeats each event line.
* MXU app log: `<maaend>/debug/YYYY-MM-DD-N.log`, one per MaaEnd launch, lines
  starting with `YYYY-MM-DD HH:MM:SS `.

collector_maaend re-exports the readers it used to hold, under their old names.
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
    (task_id, node_id) counts it once.

    A step is named by node_details.name, the node that was hit and acted. The
    top-level "name" is the node whose next list was being tried: on 2026-10-13
    09:41:34-36 GiftOperatorConfirmGift clicked once (node_details) and was the
    top-level name three times, for the two [JumpBack]GiftOperatorGiftDialog skips
    and GiftOperatorLeave after it (its next list, GiftOperatorGiftFlow.json)."""
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
    nodes: dict = {}
    seen: set = set()
    for w, msg, d in events:
        if msg != "Node.PipelineNode.Succeeded" or w < started or w > last:
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
# What each task's own run in MaaFW's log has to show. Steps from MaaEnd's pipeline
# (github.com/MaaEnd/MaaEnd, tag v2.33.0-beta.3 - the version on the machine -
# assets/resource/pipeline/):
#   entry  - the task MXU posts (Tasker.Task.Starting "entry");
#   did    - (step, what it means): the task did its job when one of these succeeded;
#   end    - (step, what it means): a step with no way on but the task's end, reached
#            when there is nothing to do - a normal end (资源不足 / 已领满 are normal
#            states, not failures). Read before `did`: the gear task's bag-full end
#            comes right after its produce click;
#   none   - for tasks whose nothing-to-do is told by the steps that ran: what it
#            means, when every step of `needs` succeeded and no `did` step did.
# Gift: GiftOperatorGiftFlow.json - GiftOperatorConfirmGift 「点击赠送按钮」 (once on
#   every 10-08..10-16 run). GiftOperatorGiftFull 「赠送已满」 is one operator, not the
#   end: its next is GiftFullLeave -> GiftFullBackInWorld -> GiftFullRetry (max_hit 5,
#   back to GiftOperatorEntry for another operator) and only then GiftOperatorGiftFullFail
#   (StopTask; the pipeline's own desc: 「重试五次也只能找到送满的干员，正常失败」).
# Gear: GearAssembly/GearAssembly.json - GearAssemblyClickProduceBtn 「点击制作按钮」
#   (once a run, followed by SceneNoticeRewardsConfirm on 10-07..10-16). Its next is
#   [GearAssemblyCheckMaterialEnough 「检测背包是否已满，背包已满直接结束」,
#   SceneNoticeRewardsConfirm]; GearAssemblyCheckFailedAndFinish 「检查制作失败，退出任务」
#   (recognises NotEnough or NotUnlocked) is reached from GearAssemblyGearListScrollEnd.
#   10-08 10:34:11-10:34:16 ran only the scene check, which failed and stopped MaaEnd (ABORT_STEP).
#   GiftFullFail, CheckMaterialEnough and CheckFailedAndFinish appear in no run we
#   hold (corpus pull 2026-10-13, 10-16 bundle): read from the pipeline only
#   (tests/test_mc28_task_trail.py builds those trails from it).
# Delivery: DeliveryJobs/TransferJob.json - DeliveryJobsConfirmTaskTransfer (5 a run in the
#   mornings); a region loop (Region/ValleyIV.json, Wuling.json) tries every depot's
#   job and cargo and falls back to DeliveryJobsLoop when none is there: the re-runs
#   of 10-08 10:37 and 10-12 11:03 ran both region loops and transferred nothing.
# Environment: EnvironmentMonitoring/TakePhoto.json - EnvironmentMonitoringTakePhoto
#   (10-08 09:42, 10-10, 10-12 10:1x took one job each; the step succeeds twice a job,
#   so no count is said); Terminals.json - each
#   terminal's loop tries all its jobs; on 10-08 10:38, 10-11, 10-12 11:04, 10-13 and
#   10-16 both terminal loops ran, no job was taken and the task ended in 6-8 s.
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
# MaaEnd's own abort: a failed scene check (SceneImageCheck.json, e.g.
# __SceneImageCheckModFailedFinish) goes next to this node, which stops the whole task
# chain through MaaFW's PostStop (SceneLoading.json 「运用 poststop 接口停止整个任务链」).
# 2026-10-08 10:34:16 (MaaEnd-06-31-06): 装备制造's check found the UID line cut short,
# MaaEnd said so in its own log (「UID显示不完整，…影响识别」), MaaFW logged
# __SceneImageCheckModFailedFinish -> __SceneCheckAbortPipeline, GearAssemblyStart
# Succeeded, MaaTaskerPostStop; MXU logged 「自动执行任务完成，关闭自身」 and the
# 「停止任务」 lines are that stop. AUTO-MAS sent no stop (its MaaEnd update had ended at
# 10:30:43). MaaFW books the task Succeeded, so the abort is read from this step.
ABORT_STEP = "__SceneCheckAbortPipeline"


def task_verdict(task: str, trail: dict) -> "tuple[bool, str]":
    """(did its job or found nothing to do, what MaaFW's log shows) for one of
    TRAIL_TASKS, from its task_trail.

    Order: MaaEnd's abort; a nothing-to-do end step (before MaaFW's result: whether
    GiftOperatorGiftFullFail's StopTask books the task Succeeded or Failed is in no
    log we hold, and the pipeline calls it a normal end); MaaFW's Failed; the step
    that did the job; a nothing-to-do told by the steps that ran."""
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


def task_trails(maaend_dir, times: dict) -> dict:
    """{task: task_trail or None} for each of TRAIL_TASKS in `times` ({task: (start,
    finish)}, naive machine-local, as collector_maaend.task_times gives them); MaaFW's
    log is read once for all of them. {} when none of the four is in `times`."""
    tasks = [t for t in TRAIL_TASKS if t in times]
    if not tasks:
        return {}
    events = task_events(maaend_dir, min(times[t][0] for t in tasks), max(times[t][1] for t in tasks))
    return {t: task_trail(events, TRAIL_RULES[t]["entry"], *times[t]) for t in tasks}
