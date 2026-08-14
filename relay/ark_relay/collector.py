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
from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ, RunRecord

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
    started = started.replace(tzinfo=SERVER_TZ)
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
        # Skip only files touched in the last few seconds. A negative age means
        # the mtime is in the future (clock skew); those must not be skipped
        # forever, so let them through.
        if 0 <= age < 20:
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
