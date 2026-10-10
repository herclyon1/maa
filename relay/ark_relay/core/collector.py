"""Read AUTO-MAS run records off disk.

AUTO-MAS writes, per run:
    history/<YYYY-MM-DD>/<username>/<HH-MM-SS>.json   result
    history/<YYYY-MM-DD>/<username>/<HH-MM-SS>.log    full log

The JSON says which script ran and whether it succeeded:
    MAA     -> {"maa_result": "Success!", "drop_statistics": {...}, "sanity": 1, ...}
    MaaEnd  -> {"maaend_result": "MaaEnd 部分任务执行失败: ⚔️协议空间"}

The filename is the start time (UTC+4, see AUTOMAS_NAME_TZ); the times inside
the log are preferred when there are any (_log_span).

This module walks the history directory, works out which program a record
belongs to, judges success or failure, and hands the log to that game's parser
(features/verify: collector_maa / collector_maaend / collector_okww). The
parsers' public names are re-exported, so callers write collector.<name>.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ark_relay.features.verify.collector_maa import parse_maa_log
from ark_relay.features.verify.collector_maaend import CLAIM_UNCONFIRMED, maaend_unreachable, parse_maaend_log, _maaend_all_done, _split_failed
from ark_relay.features.verify.collector_okww import okww_info, parse_okww_log
from ark_relay.core.config import SERVER_TZ, RunRecord

log = logging.getLogger("ark.collector")

# The result keys _judge_result recognises: a JSON carrying one is a run record.
_RESULT_KEYS = ("maa_result", "maaend_result", "general_result")
# Records whose name does not parse. Every scan re-reads them and a WARNING is a
# group message, so scan() says the new ones together, once (_say_unparsed):
# after a boot with N of them that is one message, not N.
_unparsed_warned: set[str] = set()     # already said in this process
_unparsed_new: list[str] = []          # found, not said yet

# Only public names are re-exported. `_maaend_all_done` and `_split_failed` are
# imported because `_judge_result` calls them; other private names are imported
# from the module that defines them.
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

# AUTO-MAS names history folders and files on a UTC+4 clock (`self.curdate =
# datetime.now(tz=UTC4)` in its AutoProxy); the machine runs on UTC+8. The
# filename time is used only when the run left no timestamped log.
AUTOMAS_NAME_TZ = timezone(timedelta(hours=4))


# MAA/MaaEnd write "[2026-08-25 09:37:25.186]"; OK-WW writes
# "2026-08-25 12:31:32,941 INFO ..." (no brackets). This matches both.
_LOG_TS = re.compile(r"^\[?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_MAA_SUCCESS = "Success!"
# AUTO-MAS (app/task/Okww/AutoProxy.py) records OK-WW as 「在完成任务前退出」
# ("exited before finishing") when the process is gone before it saw success in
# the log. _OKWW_DONE is the line OK-WW writes when its daily task is complete.
_OKWW_EXITED = "在完成任务前退出"
_OKWW_DONE = "Daily Task Completed"

# Results AUTO-MAS writes for an attempt it restarts right away. A real result
# always follows, so such a record is neither a success nor a failure. The first
# two are AUTO-MAS's own strings (task/Okww/AutoProxy.py:52, in
# _OKWW_BUILTIN_FATAL).
_TRANSITIONAL = (
    "游戏更新成功，即将重启任务",
    "游戏更新成功, 游戏即将重启",
    # AUTO-MAS failed to start the emulator: the attempt's log is the single line
    # 「模拟器启动失败, 无日志记录」 and the next attempt starts a second later.
    "模拟器启动失败",
    # AUTO-MAS launched MaaEnd while MaaEnd was installing its own update and
    # restarting: the record is a 30-byte stub with this result. It is not a run:
    # no retry is judged on it and it is not counted in 「尝试 N 次」.
    "未捕获到日志",
)


def _is_transitional(result: str) -> bool:
    r = result.strip()
    return any(t in r for t in _TRANSITIONAL)


def _log_span(log_path: Path) -> tuple[datetime, datetime] | None:
    """First and last timestamp inside a run log: the run's real span.

    The record's filename is hours off on this install and its mtime is when the
    whole queue finished, so neither is used for the duration when the log has
    timestamps.
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
    """"Full at" in the words of MAA's own result sentence, so ledger_rows._sanity_full
    reads MaaEnd and OK-WW the same way it reads MAA (one wording, one time
    conversion for all three games).
    """
    if current >= cap:
        return ""
    when = ref + timedelta(seconds=(cap - current) * sec_per_point)
    return f"理智将在 {when.astimezone(SERVER_TZ):%Y-%m-%d %H:%M} 回满。"


def flatten_drops(raw: dict) -> dict:
    """Flatten stage-nested drops into {item: count}.

    AUTO-MAS (from v5.4.0-beta.8) writes `drop_statistics` nested by stage:
    `{"AT-4": {"龙门币": 1296, ...}}`. Returns {} when the field is missing,
    empty or not nested.
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


# Recovery rates, used to work out "full at what time" for the two games whose
# result JSON does not carry it (MAA writes it itself):
#   Endfield: 1 point every 7m12s, 200 points per 24 hours (official figure).
#   Wuthering Waves: 1 point every 6 minutes, cap 240, empty to full in 24 hours.
_END_SANITY_SEC_PER_POINT = 432
_OKWW_STAMINA_CAP = 240
_OKWW_SEC_PER_POINT = 360


def refresh_raw(entry: dict, history_root: Path | None, maaend_dir: Path | None = None) -> dict:
    """Recompute an old ledger entry's `raw` from its history log before reporting.

    `raw` is what the parser produced at bookkeeping time, so older entries lack
    fields added later. The log is found by run_id; new keys overwrite old ones.
    If the log cannot be found or the recompute fails, the entry is returned as is.

    `maaend_dir` is handed to parse_maaend_log so a full bag can still be
    proven from MaaEnd's framework log (collector_maaend._maaend_fail_causes).
    A cause proven at bookkeeping time is kept: MaaEnd wipes its debug folder on
    every restart, so a later recompute can usually only say CLAIM_UNCONFIRMED.
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
            parsed = parse_maaend_log(log_path, maaend_dir)
            if proven := {k: v for k, v in (raw.get("maaend_fail_causes") or {}).items()
                          if v != CLAIM_UNCONFIRMED}:
                parsed["maaend_fail_causes"] = {**(parsed.get("maaend_fail_causes") or {}), **proven}
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
    # Re-judge with today's rules, in one direction only: an entry marked failed
    # is overwritten when parse_record now says ok; an entry parse_record says
    # is not ok is left as it was booked.
    try:
        rec = parse_record(log_path.with_suffix(".json"), Path(history_root), maaend_dir)
    except Exception:  # noqa: BLE001
        rec = None
    if rec is not None and rec.ok and not out.get("ok"):
        out["ok"], out["failed_tasks"] = True, []
        for k in ("maaend_name_mismatch", "okww_exit_race"):
            if k in rec.raw:
                raw[k] = rec.raw[k]
    return out


def parse_record(json_path: Path, history_root: Path,
                 maaend_dir: Path | None = None) -> RunRecord | None:
    """Parse one result JSON. Returns None if it is not a run record.

    `maaend_dir` (Config.maaend_dir) reaches parse_maaend_log, which reads
    MaaEnd's framework log there to prove a full bag.
    """
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
        # Superseded by the next attempt: keep it out of the failure list.
        failed = []

    log_path = json_path.with_suffix(".log")
    # Prefer the log's own timestamps; fall back to filename/mtime only when
    # the log is missing or has none (e.g. 「未捕获到日志」 runs).
    duration_known = False
    if log_path.exists() and (span := _log_span(log_path)):
        started, finished = span
        duration_known = True
    # A timed-out attempt's log stops where the script hung, not where AUTO-MAS
    # killed it; AUTO-MAS's own result line in app.log has the kill time. Not for
    # a MaaEnd that finished its work and then hung (ok above): its work ended
    # where its log ends.
    if not ok and "超时" in result and (killed := _automas_result_time(history_root, script, started)):
        finished = max(finished, killed)

    # AUTO-MAS hands over empty drop/recruit stats; _enrich_record fills them
    # from the log.
    failed = _enrich_record(raw, script, log_path, ok, failed, finished, maaend_dir)

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


_RESULT_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \|[^|]*\| (\S+) 自动代理 \| \S+ 任务结果: ")


def _automas_result_time(history_root: Path, script: str, started) -> "datetime | None":
    """When AUTO-MAS wrote the first result line for `script` at or after `started`.

    Read from <automas>/debug/app.log (history_root's sibling). None when the
    file is unreadable or holds no such line - AUTO-MAS rotates app.log at each
    start, so older days are simply not there and keep their log-based end.
    """
    app_log = Path(history_root).parent / "debug" / "app.log"
    try:
        text = app_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if "任务结果" not in line:
            continue
        m = _RESULT_LINE.match(line)
        if not m or m.group(2) != script:
            continue
        try:
            at = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=SERVER_TZ)
        except ValueError:
            continue
        if at >= started:
            return at
    return None


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
    # From v5.4.0-beta.7 the name carries the script as a prefix: "05-00-01.json"
    # before, "MAA-05-00-00.json" after. Both forms parse here.
    stem_time = stem.rsplit("-", 3)[-3:]
    stem_time = "-".join(stem_time) if len(stem_time) == 3 else stem
    try:
        started = datetime.strptime(f"{date_str} {stem_time}", "%Y-%m-%d %H-%M-%S")
    except ValueError:
        # A run record (by its contents) whose name does not parse would be
        # skipped on every scan; it is collected for one WARNING (_say_unparsed).
        if any(k in raw for k in _RESULT_KEYS) and str(json_path) not in _unparsed_warned:
            _unparsed_warned.add(str(json_path))
            _unparsed_new.append(rel.as_posix())
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
        # Only 「Success!」 is a success; a timeout (「MaaEnd 进程超时」) is not.
        ok = result.strip() == _MAA_SUCCESS
        failed = _split_failed(result) if not ok else []
        # AUTO-MAS matches the log against its own table of task display names,
        # so when MaaEnd renames a task AUTO-MAS records 「部分任务执行失败: X」
        # although X completed. MaaEnd's own log decides instead: every
        # 「任务开始」 has a matching 「任务完成」, there is no 「任务失败」, and
        # the round's closing task (关闭游戏 / 结束进程) ran last and completed.
        # The closing-task condition stops a MaaEnd that stopped between tasks
        # from reading as done.
        if not ok and failed and "未捕获" not in result:
            try:
                text = json_path.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if text and _maaend_all_done(text):
                ok, failed = True, []
                raw["maaend_name_mismatch"] = _split_failed(result)
        # Timed out after the work was done: MaaEnd logged every task complete
        # and then did not exit, so AUTO-MAS's silence limit ran out. Counted as
        # done only when the log reaches the closing task (_maaend_all_done): a
        # MaaEnd killed between two tasks also has every started task complete.
        if not ok and "超时" in result:
            try:
                text = json_path.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if text and _maaend_all_done(text):
                ok, failed = True, []
                raw["maaend_done_then_hung"] = True
        if not ok and not failed:
            failed = [result or "未知错误"]
    elif "general_result" in raw:
        # AUTO-MAS files OK-WW under the generic key it uses for 通用脚本; the
        # filename prefix ("<script>-HH-MM-SS.json", from v5.4.0-beta.7) names
        # the script.
        prefix = stem.rsplit("-", 3)[0] if len(stem.rsplit("-", 3)) == 4 else ""
        script = prefix or "通用脚本"
        result = str(raw.get("general_result") or "")
        ok = result.strip() == _MAA_SUCCESS
        # OK-WW exits within seconds of writing 「Daily Task Completed」; when
        # AUTO-MAS sees the process gone in those seconds it records
        # 「在完成任务前退出」. OK-WW's own log decides: if it wrote Completed,
        # the round is done.
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


def _enrich_record(raw: dict, script: str, log_path: Path, ok: bool, failed: list, finished,
                   maaend_dir: Path | None = None) -> list:
    """Merge the fields parsed from the log into raw (only keys raw lacks or has
    empty) and work out the full-again time. Returns the failure list, which for
    OK-WW is replaced by the real reason from the log when there is one.
    """
    if log_path.exists():
        if script == "MAA":
            parsed = parse_maa_log(log_path)
        elif script == "MaaEnd":
            parsed = parse_maaend_log(log_path, maaend_dir)
        else:
            parsed = parse_okww_log(log_path)
        for key, value in parsed.items():
            if not raw.get(key):
                raw[key] = value
        # OK-WW's failure list holds only AUTO-MAS's vague sentence; use the
        # log's reason when there is one.
        if script not in ("MAA", "MaaEnd") and not ok and raw.get("okww_error"):
            failed = [raw["okww_error"]]
    if flat := flatten_drops(raw):
        raw["drop_statistics"] = flat
    # MAA writes `"sanity": 0` and an empty `sanity_full_at` when it never read
    # sanity that round (fixtures: tests/fixtures/maa-2026-10-10/MAA-05-02-18.json,
    # tests/replay/2026-09-04/arknights/MAA-08-40-31.json). A round that really
    # ends on 0 carries MAA's refill sentence. Unread is stored as None plus
    # `sanity_unread`, not 0.
    if script == "MAA" and type(raw.get("sanity")) is int and raw["sanity"] == 0 and not raw.get("sanity_full_at"):
        raw["sanity"] = None
        raw["sanity_unread"] = True
    # Full-again time: MAA writes it itself; for the other two it is computed
    # from this record's finish time, when the last reading was taken.
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


def scan(history_root: Path, seen: set[str], maaend_dir: Path | None = None) -> list[RunRecord]:
    """Return records not in `seen`, oldest first. `maaend_dir` goes to parse_record.

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
        # Skip a .json younger than 120s whose .log is not there yet: AUTO-MAS
        # writes the .json first and the .log moments later, and the .log's
        # write fires the next directory event. A record parsed without its log
        # would be booked with filename/mtime times and no drops, and never
        # re-parsed once seen. Past 120s the run is taken to have no log.
        # Negative age (mtime in the future, clock skew) is never skipped.
        if 0 <= age < 120 and not path.with_suffix(".log").exists():
            continue
        # Skip records already processed by run_id from the path, before parsing.
        try:
            rel = path.relative_to(history_root)
            if f"{rel.parts[0]}/{rel.parts[1]}/{path.stem}" in seen:
                continue
        except (ValueError, IndexError):
            pass
        rec = parse_record(path, history_root, maaend_dir)
        if rec and rec.run_id not in seen:
            out.append(rec)
    _say_unparsed()
    out.sort(key=lambda r: r.started)
    return out


def _say_unparsed() -> None:
    """One WARNING for the run records found since the last one whose file name no
    longer parses: the count and the first few names."""
    if not _unparsed_new:
        return
    names = sorted(_unparsed_new)
    _unparsed_new.clear()
    shown = "、".join(names[:3]) + (f" 等 {len(names)} 个" if len(names) > 3 else "")
    log.warning("%d 个运行记录的文件名认不出开始时间（AUTO-MAS 又改了命名？），没记进账本：%s",
                len(names), shown)


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
