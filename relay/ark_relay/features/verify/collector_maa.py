"""Read a MAA run log: stage, drops, sanity spent, fights, annihilation progress,
and a task MAA refused to take.

MAA is the only one of the three programs that prints a drop table; the parse
is a line-by-line scan of the drop blocks of each stage. core.collector calls
`parse_maa_log` and `never_started`; makeup calls `keep_run_lines` and the
never-started rule's parts.
"""
from __future__ import annotations

import re
from pathlib import Path

from ark_relay.core import texts


# AUTO-MAS's result JSON has empty `drop_statistics`; the drops are only in MAA's
# own log:
#
#   [.. 09:04:12 ..] <2> 开始行动 1~6 次, -72理智
#   [.. 09:04:03 ..] <2> 已使用理智药 1(+1)
#   [.. 09:06:29 ..] <2> TO-5 掉落统计:
#   龙门币 : 864 (+864)
#
_STAGE_DROPS = re.compile(r"(\S+)\s*掉落统计[:：]")
# _STAGE_DROPS is searched only in lines that contain this word: `(\S+)`
# backtracks quadratically over a long run of non-blanks (MAA writes lines of
# ~9000 characters).
_STAGE_DROPS_WORD = "掉落统计"
# Real drops always carry the "(+N)" delta; the block's trailing
# "当前次数 : 6" (how many times the stage was run) does not. That suffix is
# the only thing separating an item from the run counter, so it is required.
#
# MAA prints both numbers through FormatNumber(false) (MaaWpfGui AsstProxy.cs
# "StageDrops", v6.19.0 :2285-2288; the same at v6.16.8 and v6.17.0-beta.6, the
# versions of 08-14 and 08-26): from 10000 up a number is rounded to one decimal
# with a unit, `{n / 1000.0:#.#}k` (Extensions/NumberExtensions.cs :25; M and B
# above). Both files are pinned in relay/tests/gamesim/upstream/maa-v6.19.0, and
# test_gl_maa_config.py `pin` fails if a new pin prints otherwise. Real LMD lines,
# 2026-08-26 15:19:37 and 2026-08-14 07:08:04 (gamesim/corpus/maa/history):
#   <LMD> : 10.1k (+1440)
#   <LMD> : 13k (+1440)
_MAA_NUMBER = r"\d+(?:\.\d+)?[kMB]?"
_DROP_ITEM = re.compile(rf"^\s*(\S[^:：]*?)\s*[:：]\s*({_MAA_NUMBER})\s*\(\+({_MAA_NUMBER})\)\s*$")
_RUN_TIMES = re.compile(r"^\s*当前次数\s*[:：]\s*(\d+)\s*$")
# An item whose running total did not move in this block: "酯原料 : 2" with no
# "(+N)". It is still inside the block.
_DROP_ITEM_UNCHANGED = re.compile(rf"^\s*(\S[^:：]*?)\s*[:：]\s*({_MAA_NUMBER})\s*$")
_MAA_UNIT = {"k": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def _maa_count(text: str) -> "tuple[int, bool]":
    """(value, exact) for a number as MAA prints it; a rounded "10.1k" gives (10100, False)."""
    if text[-1] in _MAA_UNIT:
        return round(float(text[:-1]) * _MAA_UNIT[text[-1]]), False
    return int(text), True


def _maa_total(previous: "int | None", total: str, delta: "str | None") -> int:
    """An item's exact running total from one drop line.

    MAA's total is the sum of its "(+N)" deltas (08-26 AT-4: 1440 x 8 + 576 = 12096,
    printed 「12.1k (+576)」), so a rounded total is the previous total plus an exact
    delta. A rounded delta, or no earlier total to add to, leaves only the rounded value.
    """
    value, exact = _maa_count(total)
    if exact:
        return value
    if delta is None:
        return previous if previous is not None else value
    add, add_exact = _maa_count(delta)
    if add_exact:
        return (previous or 0) + add
    return value
# MAA's own statement of which runs a batch covers: "开始行动 11~19 次" /
# "开始行动 21 次". Runs are numbered across the whole stage, so the highest
# number seen is how many times the stage was started - the drop blocks'
# "当前次数" are per batch and a batch can end without one.
_RUN_SPAN = re.compile(r"开始行动\s*(\d+)(?:\s*~\s*(\d+))?\s*次")
_SANITY_SPENT = re.compile(r"开始行动.*?-\s*(\d+)\s*理智")
# AUTO-MAS runs 剿灭 as a separate pass before the day's farming, so a queue
# produces two records; this marks the annihilation one.
_ANNIHILATION = re.compile(r'GetFightStage: from \["Annihilation"\]')
# "剿灭模式 : 1480 / 1800" - progress and the weekly cap. The pass is done when
# progress reaches the cap; MAA reports Success! even when it stopped early.
_ANNI_PROGRESS = re.compile(r"剿灭模式\s*[:：]\s*(\d+)\s*/\s*(\d+)")
_MEDICINE = re.compile(r"已使用理智药\s*(\d+)")
# Lines inside a drop block are bare "name : count"; anything with a log
# timestamp has left the block.
_HAS_TS = re.compile(r"^\[\d{4}-\d{2}-\d{2}")

# MAA refusing a task of its own queue, which stops the whole queue
# (tests/fixtures/maa-2026-10-10/MAA-05-02-18.log):
#   [..][ERR][TaskQueueViewModel]     <2> 理智作战: 理智作战 序列化失败
#   [..][INF][TaskQueueViewModel]     <2> 已停止
# The words searched for are the keys of texts.MAA_REJECT_WHY, each as a plain
# substring first (one MAA line can be ~9000 characters).
_REJECT_LINE = re.compile(r"<\d+>\s*(?:[^:：\s]+[:：]\s*)?(\S*?)\s*(?:序列化失败|添加任务失败)")
_REJECT_STAGE = re.compile(r"Cannot set stage\W*([A-Za-z0-9\-]+)")
# The queue as MAA lists it before starting: 「Index 1, Type "Fight", Name 理智作战, IsEnable true」.
_TASK_ROW = re.compile(r'Type "(\w+)", Name (\S+?),')
# The stage the Fight task was given: 「GetFightStage: from ["YW-4"], selected YW-4」.
_FIGHT_STAGE = re.compile(r"GetFightStage: from \[[^\]]*\], selected (\S+)")
# MAA lists its queue (above) once it has connected; only then does the log say
# whether a fight happened. Without that line the log does not cover the queue
# and the number of fights is unknown, not 0.
_QUEUE_LISTED = re.compile(r'Index \d+, Type "\w+"')


def _maa_scan_lines(text: str) -> "tuple[dict[str, dict[str, int]], list[str], int, int, int]":
    """Scan the MAA log line by line, collecting stage, drops, run count,
    sanity spent and potions used in a single pass.

    Returns (drops per stage, stages in order of appearance, sanity spent,
    potions used, total run count).
    """
    # Per stage: each stage keeps its own running total, and one round can farm
    # more than one stage.
    per_stage: dict[str, dict[str, int]] = {}
    stages: list[str] = []
    spent = 0
    medicine = 0

    times = 0
    last_run = 0
    current = ""
    in_block = False
    for line in text.splitlines():
        if _STAGE_DROPS_WORD in line and (m := _STAGE_DROPS.search(line)):
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
                # Each drop block holds the running total for its stage
                # ("龙门币 : 1440 (+1440)", then "龙门币 : 2448 (+1008)"), so the
                # last block per stage is kept; stages are summed in parse_maa_log.
                items = per_stage.setdefault(current, {})
                items[m.group(1)] = _maa_total(items.get(m.group(1)), m.group(2), m.group(3))
                continue
            elif m := _DROP_ITEM_UNCHANGED.match(line):
                items = per_stage.setdefault(current, {})
                items[m.group(1)] = _maa_total(items.get(m.group(1)), m.group(2), None)
                continue
            elif not line.strip():
                continue
            else:
                in_block = False
        if m := _RUN_SPAN.search(line):
            last_run = max(last_run, int(m.group(2) or m.group(1)))
        if m := _SANITY_SPENT.search(line):
            spent += int(m.group(1))
        if m := _MEDICINE.search(line):
            medicine = max(medicine, int(m.group(1)))

    # "当前次数" only says this is a counted farming stage (annihilation prints
    # none); the count itself comes from the run numbers.
    if times:
        times = max(times, last_run)
    return per_stage, stages, spent, medicine, times


def _maa_annihilation(text: str, out: dict) -> None:
    """Decide whether annihilation in this log hit the weekly cap; the verdict
    goes into `out`.

    The criterion is whether progress reached the cap, not whether MAA exited
    cleanly.
    """
    if _ANNIHILATION.search(text):
        out["annihilation"] = True
        if hits := _ANNI_PROGRESS.findall(text):
            got, cap = (int(x) for x in hits[-1])   # last line = final state
            out["annihilation_progress"] = [got, cap]
            out["annihilation_done"] = got >= cap
        else:
            # No progress line: MAA prints it after any fight, even with the week
            # already full, so no line means no fight. Not done.
            out["annihilation_done"] = False


def _maa_fights(text: str) -> "int | None":
    """How many times this log started a fight, from MAA's 「开始行动 1~10 次」 lines;
    None when the log never reached MAA's queue listing (_QUEUE_LISTED).

    Not `run_times`: that needs a drop block's 「当前次数」, which annihilation never
    prints, and it is left out when 0; here 0 means no fight. Run numbers count up
    within one stage and start again at 1 for the next: a span that does not
    continue the count opens a new stage.
    """
    if not _QUEUE_LISTED.search(text):
        return None
    total = current = 0
    for line in text.splitlines():
        if "开始行动" in line and (m := _RUN_SPAN.search(line)):
            first, last = int(m.group(1)), int(m.group(2) or m.group(1))
            if first <= current:
                total, current = total + current, last
            else:
                current = max(current, last)
    return total + current


def _maa_rejected(text: str) -> str:
    """「理智作战 序列化失败，关卡 YW-4」 when MAA refused a task of its queue, else ''.

    The first refusal in the log is the one that stopped the queue. The stage is
    named only for the Fight task: it is the one MAA last chose (GetFightStage)
    before the refusal.
    """
    types: dict[str, str] = {}
    stage = ""
    for line in text.splitlines():
        if 'Type "' in line and (m := _TASK_ROW.search(line)):
            types[m.group(2)] = m.group(1)
        if "GetFightStage" in line and (m := _FIGHT_STAGE.search(line)):
            stage = m.group(1)
        for word, why in texts.MAA_REJECT_WHY.items():
            if word not in line:
                continue
            if word.isascii():
                # MAA's English words are generic; only its error lines count.
                if "[ERR]" not in line:
                    continue
                task = next((n for n, t in types.items() if t == "Fight"), "") if "stage" in word else ""
                m = _REJECT_STAGE.search(line)
                return texts.maa_config_rejected(task, why, m.group(1) if m else (stage if task else ""))
            m = _REJECT_LINE.search(line)
            task = m.group(1) if m else ""
            return texts.maa_config_rejected(task, why, stage if types.get(task) == "Fight" else "")
    return ""


def parse_maa_log(log_path: Path) -> dict:
    """Recover stage / drops / sanity spend from a MAA log. {} when unreadable.

    A line that does not match is skipped; the parse never aborts on one line.
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
    if (fights := _maa_fights(text)) is not None:
        out["fight_count"] = fights
    if rejected := _maa_rejected(text):
        out["maa_config_rejected"] = rejected
    _maa_annihilation(text, out)
    return out


# ---------------------------------------------------------------- never got going

# A MAA round that never got into the game. Every failure has to read as one of
# these (AUTO-MAS's 「MAA 未能正确登录 PRTS」 is the StartUp task, 开始唤醒,
# failing), and the record must carry none of parse_maa_log's evidence of work.
# One rule for two readers: core.collector writes raw['maa_unreachable'] by it
# when it books the record, and makeup.maa_work_done re-runs a round only when
# every attempt of the round passes it.
MAA_NOT_STARTED = ("开始唤醒", "StartUp", "未能正确登录", "模拟器", "连接", "ADB", "adb")
MAA_WORK_KEYS = {"drop_statistics": "有掉落", "sanity_spent": "花过理智", "medicine_used": "吃过理智药",
                 "run_times": "打过关", "stages": "进过关卡", "annihilation_progress": "打过剿灭",
                 "fight_count": "打过仗"}


def failures_not_started(failed) -> bool:
    """Every failure on the record reads as MAA not getting into the game (and there is one)."""
    failed = [str(x) for x in failed or []]
    return bool(failed) and all(any(s in x for s in MAA_NOT_STARTED) for x in failed)


def work_evidence(raw: dict) -> list[str]:
    """What the record shows MAA did in the game (MAA_WORK_KEYS labels); [] for nothing."""
    return [v for k, v in MAA_WORK_KEYS.items() if (raw or {}).get(k)]


def never_started(failed, raw: dict) -> bool:
    """One MAA record's failure is 「never got into the game」: every failure reads as
    not started, nothing on it shows work, and MAA did not refuse its config (a
    refused config is refused again, so it is not a run to repeat)."""
    raw = raw or {}
    return failures_not_started(failed) and not work_evidence(raw) and not raw.get("maa_config_rejected")


# ---------------------------------------------------------------- one run's raw lines

# MAA's own debug logs open each line with 「[YYYY-MM-DD HH:MM:SS」 (asst.log, read the
# same way by handle._maa_app_log); a line without one continues the line before it.
_RUN_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
_RUN_LOGS = ("gui.log", "asst.log")
_RUN_TAIL = 16 * 1024 * 1024
_RUN_FALLBACK_LINES = 100


def run_lines(maa_dir, started, finished) -> dict[str, "list[str] | None"]:
    """{file name: the lines MAA itself wrote into debug/<file> between `started` and
    `finished`} for gui.log and asst.log; None for a file that cannot be read.

    Only the window: a start with no end would sweep in later runs (the trap
    handle._maa_app_log documents). `finished` None means no upper bound."""
    out: dict[str, "list[str] | None"] = {}
    lo = started.strftime("%Y-%m-%d %H:%M:%S")
    hi = finished.strftime("%Y-%m-%d %H:%M:%S") if finished else None
    for name in _RUN_LOGS:
        text = _tail(Path(maa_dir) / "debug" / name) if maa_dir else None
        if text is None:
            out[name] = None
            continue
        keep, lines = False, []
        for line in text.splitlines():
            if m := _RUN_TS.match(line):
                keep = m.group(1) >= lo and (hi is None or m.group(1) <= hi)
            if keep:
                lines.append(line)
        out[name] = lines
    return out


def _tail(path: Path) -> "str | None":
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > _RUN_TAIL:
                fh.seek(size - _RUN_TAIL)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None


def keep_run_lines(maa_dir, started, finished, dest_dir, run_id: str) -> dict:
    """Save one run's gui.log / asst.log lines (run_lines) to <dest_dir>/<run stem>.log,
    each under its own header; a file with no line inside the window gets its last
    _RUN_FALLBACK_LINES lines instead, said so in its header, so the sample is never
    empty by accident. Returns {"gui", "asst": lines in the window, "path", "last": the
    last line in the window (asst.log first)} for the evidence line."""
    got = run_lines(maa_dir, started, finished)
    parts = []
    for name in _RUN_LOGS:
        lines = got.get(name)
        if lines is None:
            parts.append(f"== {name}: unreadable ==")
        elif lines:
            parts.append(f"== {name}: {len(lines)} lines in {started:%Y-%m-%d %H:%M:%S} .. "
                         f"{finished:%H:%M:%S} ==" if finished else f"== {name}: {len(lines)} lines ==")
            parts.extend(lines)
        else:
            text = _tail(Path(maa_dir) / "debug" / name) if maa_dir else None
            last = (text or "").splitlines()[-_RUN_FALLBACK_LINES:]
            parts.append(f"== {name}: no line inside the run's window; its last {len(last)} lines ==")
            parts.extend(last)
    dest = Path(dest_dir) / (str(run_id).replace("/", "_") + ".log")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(parts) + "\n", encoding="utf-8")
    window = (got.get("asst.log") or []) or (got.get("gui.log") or [])
    return {"gui": len(got.get("gui.log") or []), "asst": len(got.get("asst.log") or []),
            "path": str(dest), "last": (window[-1].strip()[:160] if window else "")}
