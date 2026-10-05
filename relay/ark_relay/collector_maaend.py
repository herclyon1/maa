"""Read a MaaEnd (Endfield) run log: items gained, tasks, sanity, farming.

Split out of collector.py on 2026-09-08 (moved verbatim). MaaEnd reports in a
shape of its own -- no stage and no drop table, just a running list of
「获得 x ×n」plus one line per task -- so its regexes and its
「did every 任务开始 get a 任务完成」reasoning share nothing with the other two
games. `_split_failed` and `_maaend_all_done` live here too: they read MaaEnd's
own wording, and collector.py's `_judge_result` imports them to overrule
AUTO-MAS when its task-name table has gone stale.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path


# "MaaEnd 部分任务执行失败: 🚚转交委托、⚔️协议空间"
_FAILED_LIST = re.compile(r"失败[:：]\s*(.+)$")


def _maaend_all_done(text: str) -> bool:
    """Every 「任务开始」has a 「任务完成」with the same name, there is no
    「任务失败」at all, and at least one task ran.
    """
    started = [_strip_emoji(m.group(1)) for m in _END_TASK_START.finditer(text)]
    done = {_strip_emoji(m.group(1)) for m in _END_TASK_DONE.finditer(text)}
    if not started or _END_TASK_FAIL.search(text):
        return False
    return all(s in done for s in started)


def _split_failed(text: str) -> list[str]:
    """Pull the per-task names out of MaaEnd's failure sentence."""
    m = _FAILED_LIST.search(text)
    if not m:
        return []
    # Names are separated by the Chinese enumeration comma; strip leading emoji.
    parts = [p.strip() for p in m.group(1).split("、") if p.strip()]
    return [re.sub(r"^[^\w一-鿿]+", "", p) for p in parts]


# MaaEnd writes what it collected in a different shape from MAA - no stage, no
# drop table, just a running list of "获得 <item> ×<n>" as it works through the
# day's chores, plus one line per finished task. AUTO-MAS records none of it
# either (its result JSON is a bare "Success!"), so the same recovery applies.
#
#   任务完成: 🎁赠送干员礼物
#   获得 高级认知载体 ×3
#   获得 嵌晶玉 ×25
#
_END_GAIN = re.compile(r"获得\s+(\S.*?)\s*[×x]\s*(\d+)")
# Endfield's sanity figure. MaaEnd did not print it before; it was added after
# this project's 2026-08-15 suggestion (MaaEnd#5053) was accepted, in the form
# 「当前理智 920/360」 - note that it can go above the cap.
# Take the last occurrence = the state when the tasks ended.
_END_SANITY = re.compile(r"当前理智\s*(\d+)\s*/\s*(\d+)")
# MaaEnd also says whether it knocked off because sanity ran out, and that
# decides whether anything needs attention more directly than the number does.
_END_SANITY_OUT = re.compile(r"理智不足[，,]\s*结束任务")
# How much sanity one Protocol Space settlement costs. Prefer calibrating it
# from the drop between readings in the log; this constant is only used when
# the whole log shows no drop at all (e.g. 2026-08-24: both readings were 201
# because the charge happened at the last settlement, after which there were no
# more readings). 160 was measured on 2026-08-25: 241 -> 81.
# The number changes with the stage level, but as long as that day's log shows
# a single drop, the measured value overrides this.
_END_PS_COST = 160
_END_SANITY_SPENT = re.compile(r"尝试使用理智消耗许可")
_END_SANITY_REFUSED = re.compile(r"理智不足[，,]\s*尝试不使用理智消耗许可")
_END_PS_ENTER = re.compile(r"进入协议空间成功")
# re.M: these three are used both with search on a single line and with
# finditer over the whole text. Without re.M, `$` only matches the very end of
# the text and finditer catches nothing -- which is why parse_maaend_log's
# tasks_failed was always empty (caught by a test on 09-06).
_END_TASK_DONE = re.compile(r"任务完成[:：]\s*(\S.+?)\s*$", re.M)
# The user, 2026-09-02: one semantic template across all three games in the
# daily report; MaaEnd does not produce these numbers, so 「只能我们自己来」
# ("we have to do it ourselves").
# Shape of the farming section (recorded 2026-09-01):
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
_END_COLLECT_ROUTES = re.compile(r"(\d+)\s*条路线")


# The essence claim that never lands: 「点击确认领取按钮」, twenty seconds of
# nothing, then the task fails (2026-09-25 09:46, 09:53 and 09:58, machine
# clock). The user, 2026-09-26 16:30, ruled it a full bag, not an upstream bug.
# MaaEnd's own OCR agrees: each time, the mail it opened seconds later carried
# the game's storage-full notice (maafw.log 09:46:57.931, 09:53:43.390 and
# 09:58:51.525, node DailyEmailConfirmTSA, OCR score 0.9995). The failure name
# stays as it is (retries and alert keys match on it); the cause travels next to
# it in raw["maaend_fail_causes"].
_END_CLAIM_CLICK = re.compile(r"点击确认领取按钮")
_END_FW_LINE = re.compile(r"^\[[^\]]+\]\[(?:ERR|WRN|DBG|INF|TRC)\]")
BAG_FULL = "背包满了"


def _maaend_fail_causes(text: str) -> dict:
    """{failed task name: known cause} for failures whose cause is certain."""
    causes: dict = {}
    last = ""
    for line in text.splitlines():
        if m := _END_TASK_FAIL.search(line):
            name = _strip_emoji(m.group(1))
            if "基质刷取" in name and _END_CLAIM_CLICK.search(last):
                causes[name] = BAG_FULL
            last = ""
        elif line.strip() and not _END_FW_LINE.match(line):
            last = line
    return causes


def _strip_emoji(name: str) -> str:
    return re.sub(r"^[^\w一-鿿]+", "", name).strip()


# MaaEnd prints what a claim handed out as a block: a header line
# (_END_ITEMS_HEAD), then one 「<item> ×<n>」 line per item, all carrying the
# header's timestamp, then the next step's message. None of the item lines
# carries 「获得」, so _END_GAIN never sees them. Real example:
# tests/fixtures/maaend-farm-drops/2026-09-27.log lines 320-323 (header, the
# two items of one Protocol Space claim, then the continue-action line). The
# block ends at the first line that is not an item; the shared timestamp is not
# used as the boundary. Framework lines ("[ts][ERR]...", no space after the
# stamp) are not MaaEnd messages and end a block too.
_END_MSG = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d[.\d]*\] (.*)$")
_END_ITEMS_HEAD = re.compile(r"^获得以下物品[:：]\s*$")
_END_ITEM = re.compile(r"^([^\[\s].*?)\s*[×x]\s*(\d+)\s*$")


def _msg(line: str) -> str:
    """The message part of a MaaEnd log line (the line itself if unstamped)."""
    m = _END_MSG.match(line)
    return m.group(1) if m else line


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
    """Does this log come from a MaaEnd that prints 「获得以下物品：」 blocks?

    Older logs (the 2026-08-24/25 samples in test_maaend_sanity.py) have none,
    and there a refused claim can only be told by the older wording, so they
    keep the older reading.
    """
    return any(_END_ITEMS_HEAD.match(_msg(x).strip()) for x in text.splitlines())


def _claim_landed(tail: list[str]) -> bool:
    """In a block-era log: did the claim after the last sanity reading land?

    It landed when an item block follows the claim before any 「理智不足」
    line or the end of the task. The stop line (_END_SANITY_OUT) on its own
    does not mean refused - it is also how the task ends after a claim that
    landed. In fixtures/maaend-farm-drops: 2026-09-28a.log has the claim at
    line 341, the block at 342 and the stop line only at 354, and the claim
    was charged (166 -> 6); 2026-09-27.log has the claim at line 352 and the
    stop line right at 353 with no block, and 117 stayed.
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
    first task whose own lines hold MaaEnd's 「当前理智 N/M」 is taken instead,
    so a sanity task under a new name is still read. That reading cannot
    replace the names: six failed 基质刷取 runs never got to it
    (evidence 2026-09-24 06-18-45, 2026-09-25 05-54-06, both
    tests/fixtures/maaend-2026-09-18 logs of 05-26-03 and 05-54-44, both
    tests/replay/2026-09-07 logs), and the daily report still names those.
    Across 34 real MaaEnd logs (ark-evidence 09-12..09-25, the M6 history of
    09-20..09-22, the 09-27/09-28 logs in fixtures/maaend-farm-drops, and every
    MaaEnd log under tests/replay and tests/fixtures) the reading appears only
    inside 基质刷取 (51 lines) and 协议空间 (7). It never appears in the
    other tasks that do print item blocks: the base task (基建任务), the
    credit shop (信用点购物), the sword trial and the daily rewards - so the
    fallback does not pick those up.
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


def _maaend_farm(text: str) -> dict:
    """The farming section: what was farmed, where, how many runs, what
    dropped. Returns {} when there is no farming task.
    """
    out: dict = {}
    lines = text.splitlines()
    farm, start, end = _farm_segment(lines)
    if not farm:
        return out
    seg = lines[start:(end + 1) if end is not None else None]
    body = "\n".join(seg)
    out["maaend_farm"] = farm
    if m := _END_PLACE.search(body):
        out["maaend_farm_place"] = m.group(1)
    # Essence runs are counted as before. Other runs: in a log that prints item
    # blocks, a run is a claim that landed, i.e. one block inside the task;
    # an entry whose claim was refused is not a run (2026-09-27: two
    # 「进入协议空间成功」, one block). Older logs without blocks count entries.
    # The alternative count - 「确认领取奖励」 not directly followed by
    # 「理智不足」 - gives the same numbers on both block-era logs (1 and 2);
    # the block is used because it is the item list itself.
    runs = len(_END_ESSENCE_DONE.findall(body))
    if not runs:
        if _prints_item_blocks(text):
            runs = sum(1 for x in seg if _END_ITEMS_HEAD.match(_msg(x).strip()))
        else:
            runs = len(_END_PS_ENTER.findall(body))
    if runs:
        out["maaend_farm_runs"] = runs
    # Three sources, added together. They do not overlap: across the same 34
    # logs, 「获得以下物品：」 blocks inside a farming task occur only in
    # 协议空间 (3 blocks), never inside a 基质刷取 task, and 协议空间 prints no
    # 「是X基质」 lines - essences are counted one 「是X基质」 line each
    # (tests/fixtures/maaend-farm-drops/2026-09-24_MaaEnd-06-07-50.log, lines
    # 93-166: 10 such lines and no block). So no de-duplication rule is needed.
    # The single-line 「获得 X ×n」 is the older wording, kept for logs that
    # still have it.
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
    # 「当前理智」is announced **before each claim**, and there is no reading
    # after the last one. So n claims show only n readings and n-1 steps, and
    # summing them always undercounts the final run: recorded 09-03 as
    # 979/899/819/739/659 -- five claims give only 320 by adjacent differences,
    # when 400 was actually spent.
    # The correct form is "runs x step per run", not the sum of the differences.
    # Each step is the run's cost minus what regenerated while it ran, so the
    # median undercounts: 2026-09-22 read 237/158/78/38/38/39 over five runs,
    # steps 79/80/40, median 79 -> "395" for 5 x 80 = 400 spent
    # (history/2026-09-22/endfield/MaaEnd-05-25-40.log). The largest step is
    # the closest to the cost; steps above 1.5x the median would span a
    # missed reading and are not a single run.
    if steps and runs:
        med = sorted(steps)[len(steps) // 2]
        out["maaend_sanity_spent"] = runs * max(x for x in steps if x <= med * 1.5)
    elif runs and len(readings) >= 2:
        out["maaend_sanity_spent"] = readings[0] - readings[-1]
    # With only one run there is no step to see within it (a single reading),
    # so leave it empty and let the caller fill it in from that day's previous
    # record -- the 09-04 run had exactly this shape, and the daily report
    # printed a dash for "spent".
    elif runs:
        out["maaend_sanity_runs_only"] = runs
    return out



# 2026-09-02, Endfield server maintenance (the 「雪凇幽梦」version update,
# servers up at 10:00): across three MaaEnd rounds every task failed at exactly
# 20 seconds with none completed, and the screenshots sat on the title screen.
# AUTO-MAS wrote it up as 「任务执行情况解析失败」and the relay reported three
# failures at face value. This "never got into the game" shape is easy to
# recognise: every task fails instantly, zero completed. The user asked for it
# to be recognised, skipped for the day, and not alerted on.
_TASK_START = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[.\d]*\]\s*任务开始:\s*(.+)")
_TASK_END = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[.\d]*\]\s*任务(完成|失败):\s*(.+)")
_UNREACHABLE_QUICK_SEC = 30
_UNREACHABLE_MIN_FAILS = 3


def maaend_unreachable(text: str) -> bool:
    """Every task failed within half a minute and none completed = it never
    got into the game.

    Server maintenance, a client waiting to update, and being stuck on the
    title screen all have this shape. An ordinary failure is one step hanging
    for minutes while other tasks still complete, which never meets this
    condition.
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
_LINE_STAMP = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[.\d]*\] (.*)$")


def task_evidence(text: str) -> dict[str, str]:
    """{task: evidence} for every task with a 「任务完成」 line; evidence '' = none.

    Evidence is the first timestamped line MaaEnd wrote between that task's
    start and finish lines other than the status lines themselves: an item
    gained, a sanity reading, "no emergency sanity potion in stock" (see
    tests/fixtures/maaend_full_2026-09-01.log). The 「任务完成」 line alone is
    MaaEnd's own word that the task finished, not something read from the game:
    on 2026-10-05 four tasks had nothing else between start and finish. A task
    run twice in one log keeps the attempt that had evidence."""
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


def parse_maaend_log(log_path: Path) -> dict:
    """Recover items gained and tasks finished from a MaaEnd log. {} if unreadable."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out_flags: dict = {}
    if maaend_unreachable(text):
        out_flags["maaend_unreachable"] = True

    gains: dict[str, int] = {}
    tasks: list[str] = []
    for line in text.splitlines():
        if m := _END_GAIN.search(line):
            name = m.group(1).strip()
            gains[name] = gains.get(name, 0) + int(m.group(2))
        elif m := _END_TASK_DONE.search(line):
            # Strip the leading emoji AUTO-MAS puts on every task name; it adds
            # nothing once the names are already in a list.
            name = re.sub(r"^[^\w一-鿿]+", "", m.group(1)).strip()
            if name and name not in tasks:
                tasks.append(name)

    out: dict = {}
    if gains:
        out["drop_statistics"] = gains
    if tasks:
        out["tasks_done"] = tasks
        # What each finished task left in the log besides 「任务完成」 (core.task_unverified).
        out["tasks_evidence"] = task_evidence(text)
    failed = [_strip_emoji(m.group(1)) for m in _END_TASK_FAIL.finditer(text)]
    failed = [f for f in failed if "结束进程" not in f]
    if failed:
        out["tasks_failed"] = list(dict.fromkeys(failed))
    if causes := _maaend_fail_causes(text):
        out["maaend_fail_causes"] = causes
    if runs := len(_END_PS_ENTER.findall(text)):
        out["protocol_runs"] = runs
    out.update(_maaend_farm(text))
    if n := len(_END_MEDICINE.findall(text)):
        out["maaend_medicine"] = n
    if m := _END_COLLECT_ROUTES.findall(text):
        out["maaend_collect_routes"] = int(m[-1])
    # The gathering task can open and close within a second because today is
    # not a gathering weekday (real lines: replay 2026-09-05 09:54, task start,
    # the weekday-skip line, task done). Recorded so the report states that
    # instead of listing the task as done, which read as a fake green (user, 2026-09-13).
    if m := _END_COLLECT_SKIP.search(text):
        out["maaend_collect_skipped"] = m.group(1)
    # How many times 「路线N：xxx」appears = how many routes were walked;
    # how many 「…采集失败」lines = the ones that gathered nothing
    # MaaEnd's locale spells the first routes 「线路N：」 and the rest 「路线N：」
    # (2026-09-12: 线路2、线路3 … 路线4 … 路线17); counting only 路线 read 14/17.
    started = set(re.findall(r"(?:路线|线路)(\d+)[：:]", text))
    failed_r = set(re.findall(r"(?:路线|线路)(\d+)[：:][^\n]*采集失败", text))
    if started:
        out["maaend_collect_done"] = len(started - failed_r)
        out["maaend_collect_total"] = len(started)
    # Which ones, by name, for the report and for the narrowed retry: the line
    # reads 「路线15：红矛叶采集失败」 - keep 「路线15：红矛叶」 and the id Route15.
    if failed_lines := re.findall(r"((?:路线|线路)(\d+)[：:][^\n]*?)采集失败", text):
        out["maaend_collect_failed"] = list(dict.fromkeys(lbl.strip() for lbl, _ in failed_lines))
        out["maaend_collect_failed_ids"] = list(dict.fromkeys(f"Route{n}" for _, n in failed_lines))
    if hits := _END_SANITY.findall(text):
        got, cap = (int(x) for x in hits[-1])
        # 「当前理智」is read off Protocol Space's **reward settlement screen**,
        # while the charge happens on the 「确认领取奖励」that immediately
        # follows. So the last reading is the number **before** the charge: if
        # the last claim really went through, reporting it directly overstates
        # the remainder by one full run.
        #
        # The per-run cost is calibrated from the difference between readings
        # -- measured 2026-08-25: 241 -> 81, i.e. 160 per run. A hardcoded
        # number goes wrong when the stage level changes, whereas this
        # difference is itself that run's real cost.
        readings = [int(a) for a, _ in hits]
        drops = [a - b for a, b in zip(readings, readings[1:]) if a > b]
        # Look only at whether the **last** settlement charged: how many times
        # it charged over the whole log does not matter. Measured 2026-08-25,
        # the last one was "理智不足，尝试不使用理智消耗许可" -- no charge, so
        # 81 is the final value. Judging by "charges > refusals" would subtract
        # another 160 from 81 and give 0.
        tail = text[text.rfind("当前理智"):]
        if _prints_item_blocks(text):
            last_claim_spent = _claim_landed(tail.splitlines())
        else:
            last_claim_spent = (_END_SANITY_SPENT.search(tail)
                                and not _END_SANITY_REFUSED.search(tail))
        if last_claim_spent:
            got = max(0, got - (max(drops) if drops else _END_PS_COST))
        # AUTO-MAS always records sanity as 0 for MaaEnd, so whatever is filled
        # in here gets used (parse_record only fills in fields that are empty
        # in raw).
        out["sanity"] = got
        out["sanity_cap"] = cap
    if _END_SANITY_OUT.search(text):
        out["sanity_exhausted"] = True
    out.update(out_flags)
    return out


# MXU's own log (<maaend>/debug/YYYY-MM-DD-N.log), 2026-10-01-4.log:
#   2026-10-01 16:11:06 INFO  [App] 检测到待安装更新: v2.31.0-beta.6
#   2026-10-01 16:11:07 INFO  [App] 更新安装完成
_MXU_STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ")
_MXU_PENDING = re.compile(r"检测到待安装更新: (\S+)")
_MXU_INSTALLED = "更新安装完成"
# The install happens as this attempt's MaaEnd starts: its 「检测到待安装更新」 line
# must fall within this window of the attempt's first line, and 「更新安装完成」
# within the second window after it (10-01: 16:11:06 attempt, 16:11:06 pending,
# 16:11:07 installed).
UPDATE_AT_START_S = (-2, 30)
UPDATE_INSTALL_S = 30


def update_restart_version(maaend_dir, started) -> str:
    """The version MaaEnd installed at the start of this very attempt, or "".

    A build found mid-queue is only downloaded (「已保存待安装更新信息」); the next
    launch installs it and restarts MaaEnd, the process AUTO-MAS watches exits,
    and every task of that attempt is booked failed (2026-10-01 16:11:06,
    beta.5 -> beta.6). Only MXU's own log says so - AUTO-MAS's copy of the run
    log has none of these lines. Anchored on this attempt's own start, never on
    the previous attempt's end: an attempt killed a minute before the next one
    installs must stay the failure it was.
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
