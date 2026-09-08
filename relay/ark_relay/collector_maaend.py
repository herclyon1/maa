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
from datetime import datetime
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
