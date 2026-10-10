"""Read a MaaEnd (Endfield) run log: items gained, tasks, sanity, farming.

MaaEnd's run log has no stage and no drop table: it lists 「获得 x ×n」 lines,
「获得以下物品：」 blocks and one 「任务开始 / 任务完成 / 任务失败」 line per task.
`_split_failed` and `_maaend_all_done` are imported by core.collector to judge a
MaaEnd record from MaaEnd's own wording.

The framework-log and MXU-log readers live in maaend_fwlog and are re-exported
here under their old names.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.features.verify.maaend_fwlog import (  # noqa: F401 - re-exported names
    _END_STORAGE_FULL, _FW_META, _FW_PICK, _MXU_INSTALLED, _MXU_PENDING, _MXU_STAMP,
    UPDATE_AT_START_S, UPDATE_INSTALL_S, _fw_files, maafw_grep, maafw_text, maafw_window,
    update_restart_version)


# "MaaEnd 部分任务执行失败: 🚚转交委托、⚔️协议空间"
_FAILED_LIST = re.compile(r"失败[:：]\s*(.+)$")


def _maaend_all_done(text: str) -> bool:
    """MaaEnd's own log shows the whole round finished: every 「任务开始」has a
    「任务完成」with the same name, there is no 「任务失败」at all, at least one
    task ran, and the round reached its closing task (`_maaend_round_closed`).

    The last condition is what tells "finished" from "stopped between tasks":
    a MaaEnd that died or was killed right after one task's 「任务完成」 leaves a
    log in which every started task also completed, while the tasks AUTO-MAS
    lists as failed never started at all.
    """
    started = [_strip_emoji(m.group(1)) for m in _END_TASK_START.finditer(text)]
    done = {_strip_emoji(m.group(1)) for m in _END_TASK_DONE.finditer(text)}
    if not started or _END_TASK_FAIL.search(text):
        return False
    return all(s in done for s in started) and _maaend_round_closed(text)


# The tasks that end a round: AUTO-MAS appends MaaEnd's CloseGamePC
# 「❌关闭游戏（PC）」 (tests/fixtures/maaend-farm-drops/2026-09-28a.log lines
# 811-812); older logs end with the MXU task 「⛔ 结束进程」
# (tests/fixtures/maaend_full_2026-09-01.log lines 49-50).
_END_CLOSING_TASKS = ("关闭游戏", "结束进程")


def _maaend_round_closed(text: str) -> bool:
    """The last task MaaEnd started is a closing task, and it completed.

    No closing task means the log cannot show the round reached its end, so
    this says no. CloseGamePC is only appended when no later stage follows
    (docs/PITFALLS.md), so a stage followed by another one never qualifies.
    """
    starts = list(_END_TASK_START.finditer(text))
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
# MaaEnd's line when it stops a task because sanity ran out.
_END_SANITY_OUT = re.compile(r"理智不足[，,]\s*结束任务")
# Sanity one Protocol Space settlement costs, used only when the log shows no
# drop between two readings (measured 241 -> 81 in a 2026-08-25 log). A drop
# seen in the log is used instead.
_END_PS_COST = 160
_END_SANITY_SPENT = re.compile(r"尝试使用理智消耗许可")
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
_END_ESSENCE_DROP = re.compile(r"^是(\S+?基质)\s*$")
_END_MEDICINE = re.compile(r"使用(?:了)?应急理智加强剂")
_END_COLLECT_SKIP = re.compile(r"任务开始[:：]\s*\S*自动采集\s*\n[^\n]*?现在游戏时间是(周[一二三四五六日天])，根据执行周期跳过任务")
# The weekday-schedule skip of any task (MaaEnd's 「执行周期」 option exists for
# AutoCollect, ProtocolSpace and AutoEssence: tests/fixtures/maaend228/tasks/*.json).
_END_SCHEDULE_SKIP = re.compile(
    r"任务开始[:：]\s*(\S.+?)\s*\n[^\n]*?现在游戏时间是(周[一二三四五六日天])，根据执行周期跳过任务")
_END_COLLECT_ROUTES = re.compile(r"(\d+)\s*条路线")


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
# Not produced any more; kept because ledger lines written before 2026-10-06 carry it.
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


# A claim's items are printed as a block: the header line (_END_ITEMS_HEAD), then
# one 「<item> ×<n>」 line per item, without 「获得」, so _END_GAIN does not see them
# (tests/fixtures/maaend-farm-drops/2026-09-27.log lines 320-323). The block ends
# at the first line that is not an item. Framework lines ("[ts][ERR]...", no space
# after the stamp) are not MaaEnd messages and end a block too.
# A stamped MaaEnd message line: (stamp, message).
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
    2026-08-24/25 samples in test_maaend_sanity.py) have none and are read by the
    older wording."""
    return any(_END_ITEMS_HEAD.match(_msg(x).strip()) for x in text.splitlines())


def _claim_landed(tail: list[str]) -> bool:
    """In a block-era log: did the claim after the last sanity reading land?

    It landed when an item block follows the claim before any 「理智不足」
    line or the end of the task. The stop line (_END_SANITY_OUT) also ends a task
    after a claim that landed, so it is not read as refused on its own
    (fixtures/maaend-farm-drops 2026-09-28a.log lines 341-354: landed;
    2026-09-27.log lines 352-353: refused).
    """
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


def _farm_segment(lines: list[str]) -> tuple[str, int, "int | None"]:
    """(task name, first line, last line or None) of the farming task, or
    ("", -1, None) when there is none.

    First by name (_END_FARM_TASKS). When no task carries either name, the
    first task whose own lines hold a 「当前理智 N/M」 reading is taken instead.
    Name first because a failed 基质刷取 run can end before any reading
    (tests/fixtures/maaend-2026-09-18, tests/replay/2026-09-07). In the logs under
    tests/replay and tests/fixtures the reading appears only inside 基质刷取 and
    协议空间.
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
    parts = [x for x in parts if x]
    out: dict = {"maaend_farm": "、".join(x["maaend_farm"] for x in parts)}
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
    steps = [a - b for a, b in zip(readings, readings[1:]) if a > b]
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


# The shape of a round that never got into the game (seen during Endfield server
# maintenance on 2026-09-02): every task fails within seconds, none completes.
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
        if cur and not first and msg:
            first = msg[:80]
    return out


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
    # is there to be explained.
    fw = maafw_text(maaend_dir) if _END_CLAIM_CLICK.search(text) else ""
    causes = _maaend_fail_causes(text, fw)
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
    # first routes 线路); routes that gathered nothing: those with 「采集失败」.
    started = set(re.findall(r"(?:路线|线路)(\d+)[：:]", text))
    failed_r = set(re.findall(r"(?:路线|线路)(\d+)[：:][^\n]*采集失败", text))
    if started:
        out["maaend_collect_done"] = len(started - failed_r)
        out["maaend_collect_total"] = len(started)
    # The failed routes by name and id: 「路线15：红矛叶采集失败」 gives
    # 「路线15：红矛叶」 and Route15.
    if failed_lines := re.findall(r"((?:路线|线路)(\d+)[：:][^\n]*?)采集失败", text):
        out["maaend_collect_failed"] = list(dict.fromkeys(lbl.strip() for lbl, _ in failed_lines))
        out["maaend_collect_failed_ids"] = list(dict.fromkeys(f"Route{n}" for _, n in failed_lines))
    if hits := _END_SANITY.findall(text):
        got, cap = (int(x) for x in hits[-1])
        # 「当前理智」 is read on the settlement screen, before the claim that
        # charges sanity. When the last claim was charged, one run's cost (the
        # largest drop between readings, else _END_PS_COST) is taken off.
        readings = [int(a) for a, _ in hits]
        drops = [a - b for a, b in zip(readings, readings[1:]) if a > b]
        # Only the last settlement decides, read from the text after the last
        # reading.
        tail = text[text.rfind("当前理智"):]
        if _prints_item_blocks(text):
            last_claim_spent = _claim_landed(tail.splitlines())
        else:
            last_claim_spent = (_END_SANITY_SPENT.search(tail)
                                and not _END_SANITY_REFUSED.search(tail))
        if last_claim_spent:
            got = max(0, got - (max(drops) if drops else _END_PS_COST))
        # AUTO-MAS records sanity as 0 for MaaEnd; parse_record fills empty raw
        # fields from here.
        out["sanity"] = got
        out["sanity_cap"] = cap
    if _END_SANITY_OUT.search(text):
        out["sanity_exhausted"] = True
    out.update(out_flags)
    return out

