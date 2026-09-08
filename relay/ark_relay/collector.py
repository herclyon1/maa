"""Read AUTO-MAS run records off disk.

AUTO-MAS writes, per run:
    history/<YYYY-MM-DD>/<username>/<HH-MM-SS>.json   result
    history/<YYYY-MM-DD>/<username>/<HH-MM-SS>.log    full log

The JSON tells us which script ran and whether it succeeded:
    MAA     -> {"maa_result": "Success!", "drop_statistics": {...}, "sanity": 1, ...}
    MaaEnd  -> {"maaend_result": "MaaEnd 部分任务执行失败: ⚔️协议空间"}

Filename = start time. File mtime = finish time.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import wuwa_forgery, wuwa_tacet
from .config import SERVER_TZ, RunRecord

# AUTO-MAS names history folders and files on the game's day-boundary clock,
# not the machine's: `self.curdate = datetime.now(tz=UTC4)` in its AutoProxy.
# The machine runs on UTC+8, so every filename reads four hours early. It only
# shows when a run produced no timestamped log to prefer - a login failure, for
# instance - and then the report claimed 05:17 for something that happened at
# 09:17, at an hour the machine is not even powered on.
AUTOMAS_NAME_TZ = timezone(timedelta(hours=4))

# "MaaEnd 部分任务执行失败: 🚚转交委托、⚔️协议空间"
_FAILED_LIST = re.compile(r"失败[:：]\s*(.+)$")

# "[2026-08-14 06:45:11.432] 任务开始: ..."
# MAA/MaaEnd write "[2026-08-25 09:37:25.186]", OK-WW writes
# "2026-08-25 12:31:32,941 INFO ..." -- no brackets, comma before the
# milliseconds. Matching only the first form makes every OK-WW record show
# "duration unknown".
_LOG_TS = re.compile(r"^\[?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_MAA_SUCCESS = "Success!"
# AUTO-MAS's two verdicts on OK-WW (app/task/Okww/AutoProxy.py): if the log
# contains _OKWW_SUCCESS_LOG it records success; otherwise, the moment the
# process is gone, it records 「在完成任务前退出」("exited before finishing").
_OKWW_EXITED = "在完成任务前退出"
_OKWW_DONE = "Daily Task Completed"

# AUTO-MAS also writes "this round was interrupted and is restarting right
# away" as a non-success result, and the relay used to report that as a
# failure at face value. The strings are copied from AUTO-MAS's source, not
# invented here:
#   task/Okww/AutoProxy.py:52
#       ("游戏更新成功, 游戏即将重启", "游戏更新成功，即将重启任务")
#   -- they sit in _OKWW_BUILTIN_FATAL alongside 「未连接游戏客户端」and
#   「流程产生错误」.
# A record like this is always followed by a real result, so it counts as
# neither a success nor a failure.
_TRANSITIONAL = (
    "游戏更新成功，即将重启任务",
    "游戏更新成功, 游戏即将重启",
)


def _is_transitional(result: str) -> bool:
    r = result.strip()
    return any(t in r for t in _TRANSITIONAL)


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


def _log_span(log_path: Path) -> tuple[datetime, datetime] | None:
    """First and last timestamp inside a run log.

    This is the only trustworthy source for how long a script actually ran.
    The record's filename and mtime are not: the filename disagrees with the
    log by hours on this install, and the mtime is when the whole *queue*
    finished, not this one script - together they reported a 42-minute run as
    4h45m.
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    stamps = [m.group(1) for ln in text.splitlines() if (m := _LOG_TS.match(ln))]
    if not stamps:
        return None
    try:
        first = datetime.strptime(stamps[0], "%Y-%m-%d %H:%M:%S")
        last = datetime.strptime(stamps[-1], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return first.replace(tzinfo=SERVER_TZ), last.replace(tzinfo=SERVER_TZ)


# MAA writes what it actually farmed into its own log, but AUTO-MAS does not
# copy any of it into the result JSON - `drop_statistics` and
# `recruit_statistics` arrive as empty dicts on every single run. The numbers
# the operator most wants ("what did tonight's sanity actually buy") are
# therefore only in the log, and only the relay can put them back.
#
#   [.. 09:04:12 ..] <2> 开始行动 1~6 次, -72理智
#   [.. 09:04:03 ..] <2> 已使用理智药 1(+1)
#   [.. 09:06:29 ..] <2> TO-5 掉落统计:
#   龙门币 : 864 (+864)
#
_STAGE_DROPS = re.compile(r"(\S+)\s*掉落统计[:：]")
# Real drops always carry the "(+N)" delta; the block's trailing
# "当前次数 : 6" (how many times the stage was run) does not. That suffix is
# the only thing separating an item from the run counter, so it is required.
_DROP_ITEM = re.compile(r"^\s*(\S[^:：]*?)\s*[:：]\s*(\d+)\s*\(\+\d+\)\s*$")
_RUN_TIMES = re.compile(r"^\s*当前次数\s*[:：]\s*(\d+)\s*$")
_SANITY_SPENT = re.compile(r"开始行动.*?-\s*(\d+)\s*理智")
# AUTO-MAS runs 剿灭 as a separate pass before the day's farming, so every queue
# produces two records. The short one farms nothing and ends on 0 sanity, which
# unlabelled reads as a run that inexplicably did nothing.
_ANNIHILATION = re.compile(r'GetFightStage: from \["Annihilation"\]')
# "剿灭模式 : 1480 / 1800" - the weekly cap and how far into it this run got.
# Whether the pass *finished* is this comparison, not whether MAA exited
# cleanly: a run that stops early for want of sanity still reports Success!,
# and treating that as done would skip the rest of the week's 剿灭 entirely.
_ANNI_PROGRESS = re.compile(r"剿灭模式\s*[:：]\s*(\d+)\s*/\s*(\d+)")
_MEDICINE = re.compile(r"已使用理智药\s*(\d+)")
# Lines inside a drop block are bare "name : count"; anything with a log
# timestamp has left the block.
_HAS_TS = re.compile(r"^\[\d{4}-\d{2}-\d{2}")


def _maa_scan_lines(text: str) -> "tuple[dict[str, dict[str, int]], list[str], int, int, int]":
    """Scan the MAA log line by line, collecting stage, drops, run count,
    sanity spent and potions used in a single pass.

    It is its own step because this is the only stateful part of the whole
    parse: in_block / current have to carry across lines, so it has to be read
    as one piece; everything that assembles the result afterwards is stateless.
    Returns (drops per stage, stages in order of appearance, sanity spent,
    potions used, total run count).
    """
    # Per stage, because the running total below is per stage. One round can
    # farm more than one - annihilation then the daily stage, or an event
    # stage alongside a permanent one - and each keeps its own running total.
    per_stage: dict[str, dict[str, int]] = {}
    stages: list[str] = []
    spent = 0
    medicine = 0

    times = 0
    current = ""
    in_block = False
    for line in text.splitlines():
        if m := _STAGE_DROPS.search(line):
            current = m.group(1)
            stages.append(current)
            per_stage.setdefault(current, {})
            in_block = True
            continue
        if in_block:
            # The block ends at the next timestamped line.
            if _HAS_TS.match(line):
                in_block = False
            elif m := _RUN_TIMES.match(line):
                times += int(m.group(1))
                continue
            elif m := _DROP_ITEM.match(line):
                # MAA prints a RUNNING TOTAL in every drop block, not the
                # gain since the last one: farming TO-5 twice logs
                # "龙门币 : 1440 (+1440)" and then "龙门币 : 2448 (+1008)".
                # Adding those gave 3888 for a run that dropped 2448 - the
                # last block already is the answer, so overwrite, never sum.
                # (Verified against 2026-08-20's real log, where AUTO-MAS's
                # own figure agrees with the last block.)
                #
                # But the total only runs within one stage. Overwriting across
                # stages made a second stage's total erase the first one's
                # instead of adding to it - annihilation's 龙门币 vanished the
                # moment the daily stage logged its own. Hence per stage here,
                # summed across stages below.
                name, total = m.group(1), int(m.group(2))
                per_stage.setdefault(current, {})[name] = total
                continue
            elif not line.strip():
                continue
            else:
                in_block = False
        if m := _SANITY_SPENT.search(line):
            spent += int(m.group(1))
        if m := _MEDICINE.search(line):
            medicine = max(medicine, int(m.group(1)))

    return per_stage, stages, spent, medicine, times


def _maa_annihilation(text: str, spent: int, out: dict) -> None:
    """Decide whether annihilation in this log hit the weekly cap; the verdict
    goes into `out`.

    It is its own step because the evidence differs from the line-by-line scan
    above: this runs regexes over the whole text, and the criterion is whether
    progress reached the cap -- not whether MAA exited cleanly.
    """
    if _ANNIHILATION.search(text):
        out["annihilation"] = True
        if hits := _ANNI_PROGRESS.findall(text):
            got, cap = (int(x) for x in hits[-1])   # last line = final state
            out["annihilation_progress"] = [got, cap]
            out["annihilation_done"] = got >= cap
        else:
            # No progress line at all means MAA saw the cap was already met and
            # left without fighting - which is also "done for this week".
            out["annihilation_done"] = not spent


def parse_maa_log(log_path: Path) -> dict:
    """Recover stage / drops / sanity spend from a MAA log. {} when unreadable.

    Deliberately forgiving: a log line that does not match is skipped rather
    than aborting the parse. A daily report missing one item is a small loss;
    a report that fails to render because of one odd line is a large one.
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    out: dict = {}
    per_stage, stages, spent, medicine, times = _maa_scan_lines(text)

    drops: dict[str, int] = {}
    for stage_drops in per_stage.values():
        for name, total in stage_drops.items():
            drops[name] = drops.get(name, 0) + total
    if drops:
        out["drop_statistics"] = drops
    if stages:
        # Keep order, drop repeats: one stage farmed ten times is still one stage.
        out["stages"] = list(dict.fromkeys(stages))
    if spent:
        out["sanity_spent"] = spent
    if medicine:
        out["medicine_used"] = medicine
    if times:
        out["run_times"] = times
    _maa_annihilation(text, spent, out)
    return out



def _full_at_sentence(current: int, cap: int, sec_per_point: int,
                      ref: datetime) -> str:
    """Format it in the shape of MAA's own sentence, so core._sanity_full can
    take it as is.

    Reusing that avoids writing the "today/tomorrow" wording and the Tokyo-time
    conversion a second time -- the moment those two drift apart, the report
    starts stating the time two different ways.
    """
    if current >= cap:
        return ""
    when = ref + timedelta(seconds=(cap - current) * sec_per_point)
    return f"理智将在 {when.astimezone(SERVER_TZ):%Y-%m-%d %H:%M} 回满。"


def flatten_drops(raw: dict) -> dict:
    """Flatten stage-nested drops into {item: count}.

    AUTO-MAS used to leave `drop_statistics` empty, so this code has always
    parsed the MAA log itself and filled it in. This project's own PR to
    AUTO-MAS made it really populate that field from v5.4.0-beta.8 on -- in the
    stage-nested shape `{"AT-4": {"龙门币": 1296, ...}}`, one level deeper than
    what is parsed here. And the merge rule is "fill in only what raw lacks",
    so the nested version went into the report untouched and rendered as
    `产出 AT-4×{'龙门币': 1296, ...}`. Observed 2026-08-25.

    In other words, our own upstream change came back to hit us: when adding
    the field, only the AUTO-MAS side was considered, without going back to
    check what shape the consuming code here assumed.
    """
    src = raw.get("drop_statistics")
    if not isinstance(src, dict) or not src:
        return {}
    if all(isinstance(v, dict) for v in src.values()):
        flat: dict[str, int] = {}
        for per_stage in src.values():
            for name, count in per_stage.items():
                try:
                    flat[name] = flat.get(name, 0) + int(count)
                except (TypeError, ValueError):
                    continue
        return flat
    return {}


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
# Recovery rates for sanity / waveplates, used to work out "full at what time".
# MAA writes that sentence into its result JSON itself; the other two do not,
# so it is computed here.
#   Endfield: 1 point every 7m12s, 200 points per 24 hours (official figure).
#             Matches measurement: 2026-08-24 ended at 41 -> 08-25 started at
#             241, exactly +200 over 24 hours.
#   Wuthering Waves: 1 point every 6 minutes, cap 240, empty to full in exactly
#             24 hours.
_END_SANITY_SEC_PER_POINT = 432
_OKWW_STAMINA_CAP = 240
_OKWW_SEC_PER_POINT = 360
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
_END_COLLECT_ROUTES = re.compile(r"(\d+)\s*条路线")


def _strip_emoji(name: str) -> str:
    return re.sub(r"^[^\w一-鿿]+", "", name).strip()


def _maaend_farm(text: str) -> dict:
    """The farming section: what was farmed, where, how many runs, what
    dropped. Returns {} when there is no farming task.
    """
    out: dict = {}
    lines = text.splitlines()
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
    if start is None:
        return out
    seg = lines[start:(end + 1) if end is not None else None]
    body = "\n".join(seg)
    out["maaend_farm"] = farm
    if m := _END_PLACE.search(body):
        out["maaend_farm_place"] = m.group(1)
    runs = len(_END_ESSENCE_DONE.findall(body)) or len(_END_PS_ENTER.findall(body))
    if runs:
        out["maaend_farm_runs"] = runs
    drops: dict[str, int] = {}
    for line in seg:
        if m := _END_ESSENCE_DROP.search(line.split("] ", 1)[-1]):
            drops[m.group(1)] = drops.get(m.group(1), 0) + 1
        elif m := _END_GAIN.search(line):
            drops[m.group(1).strip()] = drops.get(m.group(1).strip(), 0) + int(m.group(2))
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
    if steps and runs:
        out["maaend_sanity_spent"] = runs * sorted(steps)[len(steps) // 2]
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
    failed = [_strip_emoji(m.group(1)) for m in _END_TASK_FAIL.finditer(text)]
    failed = [f for f in failed if "结束进程" not in f]
    if failed:
        out["tasks_failed"] = list(dict.fromkeys(failed))
    if runs := len(_END_PS_ENTER.findall(text)):
        out["protocol_runs"] = runs
    out.update(_maaend_farm(text))
    if n := len(_END_MEDICINE.findall(text)):
        out["maaend_medicine"] = n
    if m := _END_COLLECT_ROUTES.findall(text):
        out["maaend_collect_routes"] = int(m[-1])
    # How many times 「路线N：xxx」appears = how many routes were walked;
    # how many 「…采集失败」lines = the ones that gathered nothing
    started = set(re.findall(r"路线(\d+)[：:]", text))
    failed_r = set(re.findall(r"(?:路线|线路)(\d+)[：:][^\n]*采集失败", text))
    if started:
        out["maaend_collect_done"] = len(started - failed_r)
        out["maaend_collect_total"] = len(started)
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


# OK-WW is the third shape. It never reads the reward screen, so there is no
# drop list to recover - it is a pure image-recognition combat script and the
# only numbers it ever knows are its own. What it *does* publish, through
# ok-script's `info_set` (which logs every call), is enough for a useful line:
# how much stamina went in, how many domain entries that bought, and where the
# daily quest ended up. Asked for on 2026-08-25 with "虽然它没有掉落物的显示，
# 但只能说够用了".
_OKWW_STAMINA = re.compile(r"info_set current_stamina (\d+)")
# The green reserve value. get_stamina() has always stored two separate
# fields; we only used one of them.
_OKWW_BACKUP = re.compile(r"info_set back_up_stamina (\d+)")
# The real remainder at the end: OK-WW prints this line itself when it stops.
# `info_set current_stamina` is recorded **before each round**, so taking the
# last one as "remaining" always overcounts by one round -- on 2026-08-28 it
# actually farmed down to 0 while the report said 「剩余波片 80/240」, and the
# user pointed out the misreport on the spot. The per-run cost also switches
# between 40 and 80 on its own, so deriving it from outside is unreliable too;
# only the number OK-WW reports itself is accepted.
# 2026-09-04: this regex used to hardcode the second half
# `not enough to continue` as well, but OK-WW has a second wrap-up wording --
# recorded that day as
# `current stamina: 37 must_use completed, no need to use back_up`.
# Failing to match cost that day's report the entire last run: the truth was
# 236 -> 37 (199 spent, 37 left) and it was reported as 「消耗 159、剩余 77」.
# So only the first half is matched, and whatever follows is fine.
_OKWW_STAMINA_END = re.compile(r"current stamina:\s*(\d+)")
_OKWW_DAILY = re.compile(r"info_set current daily progress (\d+)")
_OKWW_POINTS = re.compile(r"info_set total daily points (\d+)")
# One of these is logged per domain entry, so counting them counts the runs.
_OKWW_ENTRY = re.compile(r"使用单倍体力|当前体力大于等于双倍|使用双倍")
# Real Nightmare Nest progress. The user, 2026-08-29: 「能不能给一下残像聚落的
# 真实刷取结果，xx/41 这种」("can you give the real farming result for the
# Nightmare Nests, something like xx/41"). The log prints a line
# `已击败残象：N/M` every time the compendium is opened; take the last one.
# WARNING: this number comes from OCR and a leading digit can be swallowed
# (10/41 read as 0/41), so it is for reference only -- never draw the "did it
# actually farm anything" conclusion from it; that is what nest_cleared is for.
_OKWW_NEST = re.compile(r"已击败残象[：:]\s*(\d+)\s*/\s*(\d+)")
_OKWW_NEST_FULL = re.compile(r"指定点位都已打满")
_OKWW_DAILY_TARGET = 180
# The full value of the in-game daily activity meter. It can go above this
# (the weekly garden and others keep adding), so the cap must be reported
# alongside it, or 「活跃度 110」looks like an error.
_OKWW_POINTS_TARGET = 100

_OKWW_FORGERY_INDEX = re.compile(r"info_set Teleport to Forgery Challenge (\d+)")
# The Simulation Challenge target: one of three in OK-WW's SimulationTask
# source; the translations come from its own ok.po
_OKWW_SIM_TARGET = re.compile(r"info_set Target Simulation Challenge (.+?)\s*$", re.M)
_SIM_ZH = {"Shell Credit": "贝币", "Resonator EXP": "共鸣者经验", "Weapon EXP": "武器经验"}
# At full difficulty (Union Level >= 70 / SOL3 tier 8) the Shell Credit
# Simulation Challenge gives 84,000 Shell Credits per run for 40 waveplates
# (game8 / fandom data, 2026-09; the user's Union Level has long been maxed and
# he fights the level 90 weekly boss). Double = 80 waveplates for two lots.
# The user, 2026-09-02: 「产出必须显示出来，不许标游戏未显示数量」("the yield
# must be shown; do not label it as a quantity the game did not display").
_SIM_REWARD_PER_RUN = {"贝币": 84000}
_OKWW_DOUBLE = re.compile(r"当前体力大于等于双倍|使用双倍")
_OKWW_SINGLE = re.compile(r"使用单倍体力")
_OKWW_TACET_INDEX = re.compile(r"info_set Teleport to Tacet Suppression (\d+)")


def _okww_farm(text: str, info: dict | None = None) -> "tuple[str, str]":
    """(the domain farmed, the yield category). OK-WW never reads the reward
    screen, so the yield can only be stated as a category.
    """
    info = info if info is not None else okww_info(text)
    if "SimulationTask:" in text:
        hits = _OKWW_SIM_TARGET.findall(text)
        tgt = _SIM_ZH.get(hits[-1].strip(), hits[-1].strip()) if hits else ""
        return (f"模拟领域·{tgt}" if tgt else "模拟领域", tgt or "模拟领域奖励")
    if "ForgeryTask:" in text:
        hits = _OKWW_FORGERY_INDEX.findall(text)
        idx = int(hits[-1]) + 1 if hits else 0
        return (_forgery_label(text), wuwa_forgery.reward(idx))
    if "TacetTask:" in text:
        # Wording like 「无音区 #2 / 声骸与角色突破材料」means nothing to a
        # reader (user, 2026-09-06). Look the index up in wuwa_tacet's table
        # and write the name plus the two sets it always drops; when it is not
        # registered, say so outright.
        # For the index, prefer what upstream reports itself -- "which one it
        # actually teleported to" (info_set, counting from 0) -- and only fall
        # back to scraping it out of the prompt text. The config says "which one
        # do we want to farm"; what is needed here is "which one was actually
        # farmed" -- and the two possibly differing is exactly what the user was
        # uneasy about on 2026-09-07.
        got = (info.get("fields") or {}).get("Teleport to Tacet Suppression")
        hits = _OKWW_TACET_INDEX.findall(text)
        if got is None and not hits:
            return ("无音区（日志里没有序号）", "声骸（无音区序号没读到，套装不明）")
        idx = (int(got) if got is not None else int(hits[-1])) + 1
        return (wuwa_tacet.label(idx), wuwa_tacet.reward(idx))
    return ("", "")


def _forgery_label(text: str) -> str:
    """Which instance follows 「凝素领域」. When it cannot be identified, only
    the index is stated.

    The index in the log counts from 0 (`Teleport to Forgery Challenge 0`);
    the lookup table counts from 1 (matching the game's F2 list). **The
    conversion happens only here**, and callers always get plain language.
    """
    hits = _OKWW_FORGERY_INDEX.findall(text)
    if not hits:
        return "凝素领域"          # The step list reads 「做了 凝素领域 ×5」; do not stuff brackets in
    return wuwa_forgery.label(int(hits[-1]) + 1)


_OKWW_GAME_ERR = "waiting for game to start error"
_OKWW_ACTIVITY = re.compile(r" INFO TaskExecutor \w+:")
_OKWW_TB_HEAD = re.compile(r" ERROR TaskExecutor (\w+):(.*?) Traceback \(most recent call last\):")
_OKWW_EXC_LINE = re.compile(r"^\s*([\w.]*(?:Exception|Error)\w*)\b(.*)$", re.M)


def _okww_got_in(text: str) -> bool:
    """Whether any task executor was still working after the last
    "cannot get the game window". If so, it got in later on.
    """
    i = text.rfind(_OKWW_GAME_ERR)
    return bool(_OKWW_ACTIVITY.search(text, i if i >= 0 else 0))


# Notifications may contain plain language only (user, 2026-09-07:
# 「你写进通知的任何东西都要是人话」-- "anything you put in a notification has
# to be plain language"). Task class names, exception names and raw log text
# stay in the log; here they are translated into Chinese. (The original note
# added "and when it cannot be translated it just says 「这一步出错」"; see
# _okww_say -- that catch-all was later removed on purpose.)
_OKWW_TASK_ZH = {
    "DailyTask": "日常清单", "FarmEchoTask": "周本", "TacetTask": "无音区",
    "NightmareNestTask": "残象聚落", "GardenTask": "周常乐园", "DomainTask": "模拟领域",
    "FarmWorldBossTask": "世界 Boss", "CombatCheck": "战斗", "BaseCombatTask": "战斗",
    "TaskExecutor": "任务执行", "AutoCombatTask": "战斗",
}
_OKWW_EXC_ZH = {
    "WaitFailedException": "等一个画面没等到", "CannotFindException": "画面上找不到要点的东西",
    "NotInCombatException": "没有进入战斗", "CharDeadException": "角色倒下了",
    "TimeoutError": "超时", "TaskDisabledException": "任务被关掉了",
}
_OKWW_MSG_ZH = (
    ("farm 4c error", "打完 Boss 领完奖之后没能退出副本"),
    ("can't find gray_book_boss", "按 F2 打不开图鉴，多半是键位改过了"),
    ("NightmareNestTask Failed", "打了但没打成"),
    ("Logger.error() got an unexpected keyword", "旧版补丁自己的日志调用写错（已撤回）"),
    ("can not battle pass", "打不过，可能已经结束"),
    ("Game window is not connected", "连不上游戏窗口"),
    ("not in combat", "没有进入战斗"),
    ("can't find boss_proceed", "图鉴里找不到「前往」按钮"),
)
_OKWW_WAIT_SEC = re.compile(r"wait_until timeout .*? (\d+(?:\.\d+)?) seconds")
_ASCII_LETTER = re.compile(r"[A-Za-z]")
_OKWW_ANY_ERR = re.compile(r" ERROR TaskExecutor (\w+):(.*)")
_OKWW_UNTRANSLATED: set = set()


_OKWW_INFO = re.compile(r" INFO TaskExecutor (\w+):info_set (.+)$", re.M)
_OKWW_INFO_NUM = ("current_stamina", "back_up_stamina", "current daily progress",
                  "total daily points", "Teleport to Tacet Suppression",
                  "Teleport to Boss Weekly Challenge")
# Keys whose value contains spaces: the rest of the line is the value, so it
# must not be split on the last space
_OKWW_INFO_REST = ("Chars", "Revive", "Target Simulation Challenge")


def okww_info(text: str, until: int | None = None) -> dict:
    """The structured state OK-WW writes itself (`info_set key value`), taking
    the last occurrence of each key.

    This is **the state upstream reports itself**, not something guessed out of
    prose: `current task` is the step it believes it is on, `错误` is the
    failure reason it decided on, and `Teleport to Tacet Suppression` is which
    Tacet Suppression it **actually** teleported to (counting from 0).
    Before 2026-09-08 all of this was scraped out of the prompt text with
    regexes, which broke the moment upstream reworded anything.

    Returns {"fields": {key: value}, "tasks": [current task in order of
    appearance], "error": the reason, or empty}.
    """
    fields: dict = {}
    tasks: list[str] = []
    error = ""
    for m in _OKWW_INFO.finditer(text):
        if until is not None and m.start() >= until:
            break           # Only the state before this point
        body = m.group(2).strip()
        if body.startswith("current task"):
            what = body[len("current task"):].strip()
            if what and not what.startswith(("wait main", "in main")):
                tasks.append(what)
            continue
        if body == "错误" or body.startswith("错误 "):
            error = body[len("错误"):].strip()
            continue
        key, _, value = body.rpartition(" ")
        for whole in _OKWW_INFO_REST:
            if body.startswith(whole + " "):
                key, value = whole, body[len(whole) + 1:]
                break
        if not key:
            continue
        if key in _OKWW_INFO_NUM:
            try:
                fields[key] = int(value)
            except ValueError:
                continue
        else:
            fields[key] = value
    return {"fields": fields, "tasks": tasks, "error": error}


def _okww_error(text: str) -> str:
    """The real reason for the failure, in plain language. Taken from the
    innermost task's section of the last traceback cluster.

    When OK-WW raises, it prints three tracebacks in a row (the task itself,
    DailyTask.run_task_by_class, and TaskExecutor's
    「Daily Task exception stopped」); all three describe the same event, and the
    innermost one carries the explanation (such as
    「farm 4c error, try handle monthly card」). Before 2026-09-07 the daily
    report only carried AUTO-MAS's 「流程产生错误，请检查游戏状态」, which does
    not say which step it was.
    """
    info = okww_info(text)
    heads = list(_OKWW_TB_HEAD.finditer(text))
    if not heads:
        # No traceback, but upstream said 「错误 …」itself: write what it said
        if info["error"] and info["tasks"]:
            step = info["tasks"][-1].split()[0]
            return _okww_say(_OKWW_TASK_BY_STEP.get(step, step), info["error"], "")
        return ""
    last = heads[-1]
    cluster = [m for m in heads if last.start() - m.start() < 6000]
    inner = [m for m in cluster if m.group(1) not in ("DailyTask", "TaskExecutor")]
    head = (inner or cluster)[0]
    task, msg = head.group(1), head.group(2).strip()
    nxt = heads[heads.index(head) + 1].start() if heads.index(head) + 1 < len(heads) else len(text)
    excs = _OKWW_EXC_LINE.findall(text[head.end():nxt])
    exc = excs[-1][0].rsplit(".", 1)[-1] if excs else ""
    # The current task upstream recorded itself is more reliable than the
    # wrapper layer's class name: `run_task_by_class <class …>` only says who
    # called it, while `current task` says which step is being done.
    if task in ("DailyTask", "TaskExecutor"):
        before_tasks = okww_info(text, until=head.start())["tasks"]
        if before_tasks:
            task = _OKWW_TASK_BY_STEP.get(before_tasks[-1].split()[0], task)
    if task in ("DailyTask", "TaskExecutor"):
        # Raised by the wrapper layer itself (such as
        # 「NightmareNestTask Failed」or 「run_task_by_class <class …>」): the real
        # task name is in that sentence, and the real reason is in the ERROR
        # line before it
        if m := re.search(r"<class '[\w.]*\.(\w+)'>", msg):
            task = m.group(1)
        elif m := re.match(r"(\w+Task) Failed", msg):
            task = m.group(1)
        before = text[max(0, head.start() - 1500):head.start()]
        prior = [m for m in _OKWW_ANY_ERR.finditer(before)
                 if m.group(1) not in ("DailyTask", "TaskExecutor", "CombatCheck", "BaseCombatTask")]
        if prior:
            task, msg = prior[-1].group(1), prior[-1].group(2).strip()
    # A vague description is banned even harder than English (user,
    # 2026-09-07: 「描述模糊是第一大禁止」-- "vague descriptions are the number
    # one prohibition"). So there is no 「这一步出错」catch-all here: if it can
    # be translated, say something specific; if it cannot, say outright that
    # 「中继还不认识这条错」and put the raw text in the log, pending a
    # translation -- saying clearly that we do not know is not fobbing him off.
    return _okww_say(task, msg, exc, text, head.start())


_OKWW_TASK_BY_STEP = {
    "garden_start_game": "GardenTask", "garden": "GardenTask",
    "check": "GardenTask", "claim": "DailyTask", "farm": "FarmEchoTask",
    "tacet": "TacetTask", "nest": "NightmareNestTask",
}


def _okww_say(task: str, msg: str, exc: str, text: str = "", at: int = 0) -> str:
    """Turn (task, raw message, exception name) into one plain-language
    sentence. When it cannot be translated, say so outright -- never be vague.
    """
    task_zh = _OKWW_TASK_ZH.get(task)
    msg_zh = next((zh for en, zh in _OKWW_MSG_ZH if en in msg), "")
    exc_zh = _OKWW_EXC_ZH.get(exc)
    if task_zh is None or not (msg_zh or exc_zh):
        sig = (task, exc, msg[:80])
        if sig not in _OKWW_UNTRANSLATED:      # Warn once per process for the same raw message
            _OKWW_UNTRANSLATED.add(sig)
            logging.getLogger("ark.collector").warning(
                "OK-WW 报错中继还没有翻译，通知里只能说不认识：任务 %s，异常 %s，原文「%s」",
                task, exc or "（没抓到异常名）", msg)
        who = task_zh or "某个任务"
        # **Copy the raw text into the notification**; do not only say
        # 「已记进日志」("recorded in the log"). Hit on 2026-09-08: OK-WW failed
        # three times in a row on the morning shift, the notification said the
        # raw text was in the log -- and the machine powers off as soon as the
        # morning shift ends, so the log is out of reach until the 21:20 boot.
        # The moment someone reads the alert and wants to know what happened is
        # exactly the moment the log is least reachable. The raw text is
        # English, but one line of English he can read beats not knowing what
        # happened; banning English exists so he can understand, not so that he
        # has nothing to look at.
        raw = " ".join((msg or "").split())[:110] or exc or "（连原文都没抓到）"
        return f"{who}：中继还不认识这条错，原文照抄——「{raw}」"
    what = msg_zh or exc_zh
    # The 「wait_until timeout … N seconds」line right before the traceback says
    # how long it waited
    before = text[max(0, at - 600):at] if text else ""
    if (w := _OKWW_WAIT_SEC.findall(before)) and "等" in what:
        sec = w[-1][:-2] if w[-1].endswith(".0") else w[-1]
        what += f"（等了 {sec} 秒）"
    return f"{task_zh}：{what}"


def parse_okww_log(log_path: Path) -> dict:
    """Recover stamina spend / entry count / daily progress from an OK-WW log.

    Stamina is summed from the *drops* between consecutive readings rather than
    from first-minus-last: the reserve tops the bar back up mid-run, and a
    naive subtraction reads that refill as if it had never been spent.
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    out: dict = {}
    readings, entries = _okww_stamina_fields(text, out)
    _okww_health(text, out, entries)
    _okww_farm_fields(text, out)
    _okww_stamina_left(text, out, readings)
    _okww_progress(text, out)
    if steps := _okww_steps(text, entries):
        out["okww_steps"] = steps
    return out


def _okww_stamina_fields(text: str, out: dict) -> "tuple[list[int], int]":
    """Waveplates spent, domain entries, reserve stamina. Returns
    (the series of readings, the entry count) for the checks that follow.
    """
    readings = [int(m.group(1)) for m in _OKWW_STAMINA.finditer(text)]
    # The wrap-up line 「current stamina: 8 not enough to continue」is the last
    # reading; leaving it out loses the final run's cost (recorded 2026-09-02:
    # 168 -> 88 -> 8 came out as only 80).
    tail = [int(x) for x in _OKWW_STAMINA_END.findall(text)]
    series = readings + tail[-1:]
    spent = sum(a - b for a, b in zip(series, series[1:]) if a > b)
    if spent:
        out["okww_stamina_spent"] = spent
    entries = len(_OKWW_ENTRY.findall(text))
    if entries:
        out["okww_runs"] = entries
    if back := _OKWW_BACKUP.findall(text):
        out["okww_backup_stamina"] = int(back[-1])
        backs = [int(x) for x in back]
        if used := sum(a - b for a, b in zip(backs, backs[1:]) if a > b):
            out["okww_backup_spent"] = used
    return readings, entries


def _okww_health(text: str, out: dict, entries: int) -> None:
    """Whether it got into the game, and the real reason for a failure."""
    # Never got into the game: the window wait errored, not a single run
    # started, **and nothing else was done afterwards**. On a major version
    # update day the Kuro launcher sits on the 「更新」button and OK-WW just
    # waits for the game window (recorded 2026-09-02 09:18).
    # The "nothing else was done afterwards" clause was added 2026-09-07: that
    # day all three rounds opened with
    # 「waiting for game to start error … is not connected」(a transient window
    # connection error that cleared a few seconds later), then ran for 41
    # minutes, fell over on the weekly boss settlement screen and never started
    # a Tacet Suppression run -- so all of them were judged "cannot get into
    # the game (server maintenance / client waiting to update)". The user: the
    # classification mechanism is broken.
    if "waiting for game to start error" in text and not entries and not _okww_got_in(text):
        out["okww_unreachable"] = True
    if err := _okww_error(text):
        out["okww_error"] = err


def _okww_farm_fields(text: str, out: dict) -> None:
    """Which domain was farmed, how many single and double runs, and the yield
    estimated at full difficulty.
    """
    info = okww_info(text)
    if info["fields"] or info["tasks"]:
        out["okww_info"] = info["fields"]
    farm, reward = _okww_farm(text, info)
    if farm:
        out["okww_farm"] = farm
        out["okww_farm_reward"] = reward
        double = len(_OKWW_DOUBLE.findall(text))
        single = len(_OKWW_SINGLE.findall(text))
        if double:
            out["okww_runs_double"] = double
        if single:
            out["okww_runs_single"] = single
        if (per := _SIM_REWARD_PER_RUN.get(reward)) and (double or single):
            out["okww_farm_drops"] = {reward: per * (2 * double + single)}


def _okww_stamina_left(text: str, out: dict, readings: list) -> None:
    if end := _OKWW_STAMINA_END.findall(text):
        out["okww_stamina_left"] = int(end[-1])
        out["okww_stamina_left_exact"] = True
    elif readings:
        # Only when the wrap-up line was not caught does it fall back to the
        # pre-run reading, flagged as not being the final remainder.
        out["okww_stamina_left"] = readings[-1]
        out["okww_stamina_left_exact"] = False


def _okww_progress(text: str, out: dict) -> None:
    """Nightmare Nests, daily progress, daily points, and why it stopped."""
    if nest := _OKWW_NEST.findall(text):
        out["okww_nest"] = f"{nest[-1][0]}/{nest[-1][1]}"
    if _OKWW_NEST_FULL.search(text):
        out["okww_nest_full"] = True
    if daily := _OKWW_DAILY.findall(text):
        out["okww_daily"] = f"{max(int(x) for x in daily)}/{_OKWW_DAILY_TARGET}"
    if points := _OKWW_POINTS.findall(text):
        top = max(int(x) for x in points)
        out["okww_points"] = f"{top}/{_OKWW_POINTS_TARGET}"
        if top >= _OKWW_POINTS_TARGET:
            out["okww_points"] += "（已满）"
        # The very first activity reading already >= the target means the
        # dailies were finished before this round started (the second run of
        # the day). Farming nothing this round is **correct behaviour**; both
        # the rendering and the result check downstream need this flag, so that
        # "nothing to do" is not judged as "failed to do it".
        if int(points[0]) >= _OKWW_POINTS_TARGET:
            out["okww_daily_done_at_start"] = True
    # Why it stopped, in its own words. "used all stamina" is the good ending.
    if "used all stamina" in text:
        # "Used up" is wrong: OK-WW's `used all stamina` means **what is left
        # is not enough for another run** (a Forgery Challenge run costs 40, so
        # 37 left cannot get in), not that 0 is left. The user called this out
        # on 2026-08-29: 「用尽不是零吗？还剩 20 多」("doesn't used up mean
        # zero? there are still 20-odd left").
        out["okww_stopped"] = "体力不够再开一局"
    elif "not enough stamina" in text:
        out["okww_stopped"] = "体力不够，一局都没开成"


def _okww_steps(text: str, entries: int) -> list[str]:
    """The step list in the daily report's 「备注」, each item marked with its
    own success or failure.
    """
    # Only report what carries information: collecting mail, the radio and the
    # daily reward happen every round and are pure noise in a report.
    # The operator, 2026-08-25: 「除了周常乐园、刷取的关卡、残像聚落之外也别写
    # 上去了」("apart from the weekly garden, the stage farmed and the
    # Nightmare Nests, do not list anything else either").
    # Appearing in the log != having succeeded. A Forgery Challenge may never
    # have been entered for want of stamina, and a Nightmare task may have
    # raised an exception that DailyTask swallowed -- writing either of those
    # up as "done" would be a lie. So each item is marked with its own outcome.
    steps = []
    for needle, name in (
        ("ForgeryTask:", _forgery_label(text)),
        ("TacetTask:", "无音区"),
        ("SimulationTask:", "模拟领域"),
    ):
        if needle not in text:
            continue
        if entries:
            steps.append(f"{name} ×{entries}")
        else:
            steps.append(f"{name}（未进本）")
    if "NightmareNestTask:" in text:
        nest = "残象聚落" if "canxiang" in text else "梦魇巢穴"
        # Appearing in the log != having fought. On 2026-08-27 three rounds in
        # a row reached `open_boss_book canxiang` without a single fight, while
        # this still wrote 「残象聚落」-- so the daily report came out all green.
        # The criterion is now "did it actually enter", and "skipped because
        # full" is stated separately from "location not found".
        if "NightmareNestTask Failed" in text:
            steps.append(f"{nest}（失败）")
        elif "列表里没找到指定的点位" in text:
            steps.append(f"{nest}（点位名对不上，一次没打）")
        elif "指定点位都已打满" in text:
            # 「跳过」("skipped") is find_nest's internal wording and must not
            # leak into a report a person reads: hitting the cap means it is
            # **done**, not that it did nothing.
            steps.append(f"{nest}（已刷满）")
        elif re.search(r"is not complete|click_team_challenge|echo captured", text):
            steps.append(nest)
        else:
            steps.append(f"{nest}（开了界面就退出，一次没打）")
    # The weekly boss (Sonata Reverb): it was not in this list at all, so the
    # "record it when done, reset on Monday" bookkeeping was never triggered by
    # a record (on 2026-09-07 all three rewards were claimed and the books
    # still said 「本周还没领满」).
    if "Teleport to Boss Weekly Challenge" in text:
        claims = text.count("周本领奖：已点确认")
        left = [int(m) for m in re.findall(r"本周剩余可收取次数[：:]\s*(\d+)\s*/", text)]
        if "farm 4c error" in text:
            steps.append(f"周本（领了 {claims} 次，然后没能退出副本）" if claims
                         else "周本（没做完，原因见失败于）")
        elif "收取物资次数已达到上限" in text or (left and left[-1] == 0 and not claims):
            steps.append("周本（已完成，本周已领满）")
        elif claims:
            remain = max((left[-1] if left else claims) - claims, 0)
            steps.append(f"周本（已完成，领了 {claims} 次，本周还剩 {remain} 次）")
        else:
            steps.append("周本（打了，没领到奖励）")
    if "weekly garden already completed" in text:
        steps.append("周常乐园（本周已完成）")
    elif "GardenTask:" in text:
        steps.append("周常乐园")
    if "check discarded echo" in text:
        steps.append("声骸五合一")
    return steps




def refresh_raw(entry: dict, history_root: Path | None) -> dict:
    """`raw` in the ledger is whatever the parser produced at bookkeeping
    time, so older entries lack fields added by later parser versions.
    Before reporting, find the history log by run_id and recompute; new keys
    overwrite old ones. If the log cannot be found, the entry is left as is.
    Evening of 2026-09-02: the Wuthering Waves line in the report,
    「刷 模拟领域 ×2 / 波片 80」, was bookkeeping done by the morning's older
    parser.
    """
    if not history_root:
        return entry
    raw = dict(entry.get("raw") or {})
    script = entry.get("script")
    try:
        log_path = Path(history_root) / (str(entry.get("run_id") or "") + ".log")
        if not log_path.is_file():
            return entry
        if script == "MAA":
            parsed = parse_maa_log(log_path)
        elif script == "MaaEnd":
            parsed = parse_maaend_log(log_path)
        elif script == "OK-WW":
            parsed = parse_okww_log(log_path)
        else:
            return entry
    except Exception:  # noqa: BLE001 - if the recompute fails, keep the original
        return entry
    raw.update(parsed)
    out = dict(entry)
    out["raw"] = raw
    if parsed.get("sanity") is not None and out.get("sanity") is None:
        out["sanity"] = parsed["sanity"]
    # Re-judge success or failure by today's criteria too: the books were
    # judged at bookkeeping time, so after a criteria upgrade (for instance the
    # two from 09-06: "AUTO-MAS does not recognise a renamed task" and "OK-WW
    # omits a line when exiting") an old entry is still marked failed, and the
    # evening report keeps writing a finished run up as a failure. Changes only
    # ever go towards "it was done": overwrite only when parse_record says ok,
    # and leave the old entry alone when it says not ok (a failure in the books
    # had its own evidence at the time).
    try:
        rec = parse_record(log_path.with_suffix(".json"), Path(history_root))
    except Exception:  # noqa: BLE001
        rec = None
    if rec is not None and rec.ok and not out.get("ok"):
        out["ok"], out["failed_tasks"] = True, []
        for k in ("maaend_name_mismatch", "okww_exit_race"):
            if k in rec.raw:
                raw[k] = rec.raw[k]
    return out


def parse_record(json_path: Path, history_root: Path) -> RunRecord | None:
    """Parse one result JSON. Returns None if it is not a run record."""
    got = _record_identity(json_path, history_root)
    if got is None:
        return None
    raw, date_str, user, stem, started, finished = got
    judged = _judge_result(raw, json_path, stem)
    if judged is None:
        return None
    script, result, ok, failed = judged

    transitional = _is_transitional(result)
    if transitional:
        # Not a fault -- superseded by the next round. Keep it out of the
        # failure list.
        failed = []

    log_path = json_path.with_suffix(".log")
    # Prefer the log's own timestamps; fall back to filename/mtime only when
    # the log is missing or has none (e.g. "未捕获到日志" runs).
    duration_known = False
    if log_path.exists() and (span := _log_span(log_path)):
        started, finished = span
        duration_known = True

    # AUTO-MAS always hands us empty drop/recruit stats, so recover them from
    # the log. Only fill what is genuinely missing - if a future AUTO-MAS
    failed = _enrich_record(raw, script, log_path, ok, failed, finished)

    return RunRecord(
        run_id=f"{date_str}/{user}/{stem}",
        script=script,
        user=user,
        started=started,
        finished=finished,
        ok=ok,
        failed_tasks=failed,
        transitional=transitional,
        raw=raw,
        log_path=log_path if log_path.exists() else None,
        duration_known=duration_known,
    )


def _record_identity(json_path: Path, history_root: Path):
    """Read the JSON and work out date / account / start time from the path
    and file name. Returns None when it is not a run record.
    """
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None

    try:
        rel = json_path.relative_to(history_root)
        date_str, user, stem = rel.parts[0], rel.parts[1], json_path.stem
    except (ValueError, IndexError):
        return None

    # AUTO-MAS names these files by the run's start time on a UTC+4 clock.
    # v5.4.0-beta.7 started prefixing them with the script name, so the same
    # record is "05-00-01.json" on 2026-08-22 and "MAA-05-00-00.json" on
    # 2026-08-23. Parsing only the bare form silently dropped every record the
    # morning after that update: an empty ledger, no report, no power-off, and
    # a "该跑没跑" alarm for a queue that had in fact succeeded.
    stem_time = stem.rsplit("-", 3)[-3:]
    stem_time = "-".join(stem_time) if len(stem_time) == 3 else stem
    try:
        started = datetime.strptime(f"{date_str} {stem_time}", "%Y-%m-%d %H-%M-%S")
    except ValueError:
        return None
    started = started.replace(tzinfo=AUTOMAS_NAME_TZ).astimezone(SERVER_TZ)
    finished = datetime.fromtimestamp(json_path.stat().st_mtime, tz=SERVER_TZ)
    if finished < started:  # clock skew or a copied file; don't produce negatives
        finished = started
    return raw, date_str, user, stem, started, finished


def _judge_result(raw: dict, json_path: Path, stem: str):
    """The success criteria of each of the three programs. Returns
    (script, raw result, ok, failure list); None when it is not recognised.
    """

    # Which script produced this record, and did it succeed?
    if "maa_result" in raw:
        script = "MAA"
        result = str(raw.get("maa_result") or "")
        ok = result.strip() == _MAA_SUCCESS
        failed = [] if ok else ([result] if result else ["未知错误"])
    elif "maaend_result" in raw:
        script = "MaaEnd"
        result = str(raw.get("maaend_result") or "")
        # "未捕获到日志" means AUTO-MAS could not tell - treat as failure, not success.
        ok = "失败" not in result and "未捕获" not in result and bool(result)
        failed = _split_failed(result) if not ok else []
        # AUTO-MAS matches the log against **its own table of task names**: the
        # moment upstream renames a task's display name, it cannot find that
        # 「任务完成」and records 「部分任务执行失败: X」.
        # Morning shift 2026-09-06: MaaEnd v2.28.0-beta.1 changed SellProduct's
        # display name to 「据点交易」; the log had all 17 tasks at 「任务完成」
        # and not one 「任务失败」, and AUTO-MAS still recorded a failure and
        # wasted two retry rounds. MaaEnd's own log is authoritative: if every
        # 「任务开始」has a matching 「任务完成」and there is no 「任务失败」,
        # the round was finished.
        if not ok and failed and "未捕获" not in result:
            try:
                text = json_path.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if text and _maaend_all_done(text):
                ok, failed = True, []
                raw["maaend_name_mismatch"] = _split_failed(result)
        if not ok and not failed:
            failed = [result or "未知错误"]
    elif "general_result" in raw:
        # AUTO-MAS files OK-WW under the generic key it uses for 通用脚本, so the
        # key alone cannot name the script - the filename prefix can. Records
        # are "<script>-HH-MM-SS.json" since v5.4.0-beta.7.
        prefix = stem.rsplit("-", 3)[0] if len(stem.rsplit("-", 3)) == 4 else ""
        script = prefix or "通用脚本"
        result = str(raw.get("general_result") or "")
        ok = result.strip() == _MAA_SUCCESS
        # AUTO-MAS reads the log first and then looks at the process: OK-WW
        # exits on its own within seconds of writing 「Daily Task Completed」,
        # and if AUTO-MAS only sees the process gone during those seconds it
        # records 「在完成任务前退出」.
        # That is exactly the 2026-09-06 morning shift: Completed at 09:36:18,
        # exit at 09:36:24, recorded as a failure -- and the retry round, with
        # nothing left to do, was recorded green. OK-WW's own log is
        # authoritative: if it wrote Completed, the round was finished.
        if not ok and _OKWW_EXITED in result:
            try:
                if _OKWW_DONE in json_path.with_suffix(".log").read_text(
                        encoding="utf-8", errors="replace"):
                    ok = True
                    raw["okww_exit_race"] = True
            except OSError:
                pass
        failed = [] if ok else ([result] if result else ["未知错误"])
    else:
        return None
    return script, result, ok, failed


def _enrich_record(raw: dict, script: str, log_path: Path, ok: bool, failed: list, finished) -> list:
    """Merge the fields computed from the log into raw and work out the
    full-again time; the failure list may be replaced by the real reason from
    the log.
    """
    # version starts populating these, its numbers win over our parsing.
    if log_path.exists():
        if script == "MAA":
            parsed = parse_maa_log(log_path)
        elif script == "MaaEnd":
            parsed = parse_maaend_log(log_path)
        else:
            parsed = parse_okww_log(log_path)
        for key, value in parsed.items():
            if not raw.get(key):
                raw[key] = value
        # OK-WW's failure list holds only AUTO-MAS's vague sentence; when the
        # log has the real reason, use that instead
        if script not in ("MAA", "MaaEnd") and not ok and raw.get("okww_error"):
            failed = [raw["okww_error"]]
    if flat := flatten_drops(raw):
        raw["drop_statistics"] = flat
    # Full-again time: MAA writes it into its result JSON itself, the other two
    # have to be computed. Use this record's finish time as the starting point
    # -- that is exactly when the last reading was taken.
    if not raw.get("sanity_full_at"):
        if script == "MaaEnd" and raw.get("sanity") is not None:
            raw["sanity_full_at"] = _full_at_sentence(
                int(raw["sanity"]), int(raw.get("sanity_cap") or 360),
                _END_SANITY_SEC_PER_POINT, finished)
        elif raw.get("okww_stamina_left") is not None:
            raw["sanity_full_at"] = _full_at_sentence(
                int(raw["okww_stamina_left"]), _OKWW_STAMINA_CAP,
                _OKWW_SEC_PER_POINT, finished)
    return failed


def scan(history_root: Path, seen: set[str]) -> list[RunRecord]:
    """Return records not in `seen`, oldest first.

    Only files that have stopped changing are returned: a run still being
    written would otherwise be reported as finished.
    """
    out: list[RunRecord] = []
    now = datetime.now(tz=SERVER_TZ).timestamp()
    for path in sorted(history_root.rglob("*.json")):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        # Wait only for an incomplete pair: AUTO-MAS writes the .json first and
        # its .log moments later, and a log-less parse is frozen wrong forever
        # once the engine marks it seen (filename/mtime times, no drops, no
        # annihilation flags). The .log's own write fires the next directory
        # event, so the record is processed seconds later with full data. A
        # flat "younger than 20s" gate here used to skip every record on the
        # very event its own write triggered, deferring "失败立刻推" to the
        # next unrelated wake - up to an hour at night. Past 120s assume the
        # run genuinely produced no log and take the record as it is. Negative
        # age means clock skew (mtime in the future); never skip those forever.
        if 0 <= age < 120 and not path.with_suffix(".log").exists():
            continue
        # Compute run_id from the path first and skip anything already
        # processed. This used to re-parse all several hundred records in the
        # whole history directory every cycle and filter afterwards -- measured
        # 2026-09-07, a single startup took over ten seconds, which made
        # stopping the service hit the hard 15-second cutoff, and old failed
        # records from August raised their alerts again every single time.
        try:
            rel = path.relative_to(history_root)
            if f"{rel.parts[0]}/{rel.parts[1]}/{path.stem}" in seen:
                continue
        except (ValueError, IndexError):
            pass
        rec = parse_record(path, history_root)
        if rec and rec.run_id not in seen:
            out.append(rec)
    out.sort(key=lambda r: r.started)
    return out


def log_tail(rec: RunRecord, lines: int = 60) -> str:
    """Last N meaningful log lines, for failure diagnosis.

    MaaFramework spams template-matcher errors that are noise, not causes.
    """
    if not rec.log_path:
        return ""
    try:
        text = rec.log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    keep = [
        ln for ln in text.splitlines()
        if ln.strip() and "TemplateMatcher.cpp" not in ln
    ]
    return "\n".join(keep[-lines:])
