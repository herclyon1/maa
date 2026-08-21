"""Read AUTO-MAS run records off disk.

AUTO-MAS writes, per run:
    history/<YYYY-MM-DD>/<用户名>/<HH-MM-SS>.json   结果
    history/<YYYY-MM-DD>/<用户名>/<HH-MM-SS>.log    完整日志

The JSON tells us which script ran and whether it succeeded:
    MAA     -> {"maa_result": "Success!", "drop_statistics": {...}, "sanity": 1, ...}
    MaaEnd  -> {"maaend_result": "MaaEnd 部分任务执行失败: ⚔️协议空间"}

Filename = start time. File mtime = finish time.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
_LOG_TS = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_MAA_SUCCESS = "Success!"


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
    drops: dict[str, int] = {}
    stages: list[str] = []
    spent = 0
    medicine = 0

    times = 0
    in_block = False
    for line in text.splitlines():
        if m := _STAGE_DROPS.search(line):
            stages.append(m.group(1))
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
                name, total = m.group(1), int(m.group(2))
                drops[name] = total
                continue
            elif not line.strip():
                continue
            else:
                in_block = False
        if m := _SANITY_SPENT.search(line):
            spent += int(m.group(1))
        if m := _MEDICINE.search(line):
            medicine = max(medicine, int(m.group(1)))

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
    return out


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
# 终末地的理智数值。MaaEnd 以前不打印，是本项目 2026-08-15 提的建议
# (MaaEnd#5053) 被采纳后加上的，形如「当前理智 920/360」——注意会超上限。
# 取最后一次出现＝任务结束时的状态。
_END_SANITY = re.compile(r"当前理智\s*(\d+)\s*/\s*(\d+)")
# MaaEnd 还会说它是不是因为理智耗尽才收工，这条比数字更直接决定要不要管。
_END_SANITY_OUT = re.compile(r"理智不足[，,]\s*结束任务")
_END_PS_ENTER = re.compile(r"进入协议空间成功")
_END_TASK_DONE = re.compile(r"任务完成[:：]\s*(\S.+?)\s*$")


def parse_maaend_log(log_path: Path) -> dict:
    """Recover items gained and tasks finished from a MaaEnd log. {} if unreadable."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

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
    if runs := len(_END_PS_ENTER.findall(text)):
        out["protocol_runs"] = runs
    if hits := _END_SANITY.findall(text):
        got, cap = (int(x) for x in hits[-1])
        # AUTO-MAS 给 MaaEnd 记的 sanity 恒为 0，所以这里填进去就会被采用
        # （parse_record 只补 raw 里空着的字段）。
        out["sanity"] = got
        out["sanity_cap"] = cap
    if _END_SANITY_OUT.search(text):
        out["sanity_exhausted"] = True
    return out


def parse_record(json_path: Path, history_root: Path) -> RunRecord | None:
    """Parse one result JSON. Returns None if it is not a run record."""
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

    try:
        started = datetime.strptime(f"{date_str} {stem}", "%Y-%m-%d %H-%M-%S")
    except ValueError:
        return None
    started = started.replace(tzinfo=AUTOMAS_NAME_TZ).astimezone(SERVER_TZ)
    finished = datetime.fromtimestamp(json_path.stat().st_mtime, tz=SERVER_TZ)
    if finished < started:  # clock skew or a copied file; don't produce negatives
        finished = started

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
        if not ok and not failed:
            failed = [result or "未知错误"]
    else:
        return None

    log_path = json_path.with_suffix(".log")
    # Prefer the log's own timestamps; fall back to filename/mtime only when
    # the log is missing or has none (e.g. "未捕获到日志" runs).
    duration_known = False
    if log_path.exists() and (span := _log_span(log_path)):
        started, finished = span
        duration_known = True

    # AUTO-MAS always hands us empty drop/recruit stats, so recover them from
    # the log. Only fill what is genuinely missing - if a future AUTO-MAS
    # version starts populating these, its numbers win over our parsing.
    if log_path.exists():
        parsed = (parse_maa_log(log_path) if script == "MAA"
                  else parse_maaend_log(log_path))
        for key, value in parsed.items():
            if not raw.get(key):
                raw[key] = value

    return RunRecord(
        run_id=f"{date_str}/{user}/{stem}",
        script=script,
        user=user,
        started=started,
        finished=finished,
        ok=ok,
        failed_tasks=failed,
        raw=raw,
        log_path=log_path if log_path.exists() else None,
        duration_known=duration_known,
    )


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
