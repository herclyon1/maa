"""Read a MAA run log: stage, drops, sanity spent, annihilation progress.

Split out of collector.py on 2026-09-08 (moved verbatim). It is its own file
because MAA is the only one of the three programs that prints a drop table:
the parsing here is a stateful line-by-line scan of blocks that belong to a
stage, and none of it says anything about Endfield or Wuthering Waves. The
shell in collector.py only ever calls `parse_maa_log`.
"""
from __future__ import annotations

import re
from pathlib import Path


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
