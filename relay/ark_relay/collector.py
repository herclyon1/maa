"""Read AUTO-MAS run records off disk.

AUTO-MAS writes, per run:
    history/<YYYY-MM-DD>/<username>/<HH-MM-SS>.json   result
    history/<YYYY-MM-DD>/<username>/<HH-MM-SS>.log    full log

The JSON tells us which script ran and whether it succeeded:
    MAA     -> {"maa_result": "Success!", "drop_statistics": {...}, "sanity": 1, ...}
    MaaEnd  -> {"maaend_result": "MaaEnd 部分任务执行失败: ⚔️协议空间"}

Filename = start time. File mtime = finish time.

The three log parsers were split out per game on 2026-09-08 (moved verbatim):
collector_maa / collector_maaend / collector_okww. What stays here is the part
that is the same whatever ran -- walk the history directory, work out which
program a record belongs to, judge success or failure, and hand the log to that
game's parser. This module re-exports every public name unchanged, so callers
and tests still write collector.xxx.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .collector_maa import parse_maa_log
from .collector_maaend import (
    maaend_unreachable,
    parse_maaend_log,
    _maaend_all_done,
    _split_failed,
)
from .collector_okww import okww_info, parse_okww_log
from .config import SERVER_TZ, RunRecord

# Only public names are forwarded. `_maaend_all_done` and `_split_failed` are
# imported above because `_judge_result` below actually calls them, not to hand
# them on: anything else that wants a private name imports it from the module
# it lives in (plan.py takes `_SIM_ZH` from collector_okww, and the tests do
# the same), so changing a parser's internals does not force an edit here.
__all__ = [
    "AUTOMAS_NAME_TZ",
    "flatten_drops",
    "log_tail",
    "maaend_unreachable",
    "okww_info",
    "parse_maa_log",
    "parse_maaend_log",
    "parse_okww_log",
    "parse_record",
    "refresh_raw",
    "scan",
]

# AUTO-MAS names history folders and files on the game's day-boundary clock,
# not the machine's: `self.curdate = datetime.now(tz=UTC4)` in its AutoProxy.
# The machine runs on UTC+8, so every filename reads four hours early. It only
# shows when a run produced no timestamped log to prefer - a login failure, for
# instance - and then the report claimed 05:17 for something that happened at
# 09:17, at an hour the machine is not even powered on.
AUTOMAS_NAME_TZ = timezone(timedelta(hours=4))


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
