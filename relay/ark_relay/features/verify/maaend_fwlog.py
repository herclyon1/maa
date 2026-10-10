"""Read MaaEnd's two side logs: the MaaFW framework log and MXU's own app log.

* Framework log: `<maaend>/debug/maafw*.log` and `<maaend>/debug/cpp-algo/debug/maafw*.log`
  (current and rotated). Every line starts with `[YYYY-MM-DD HH:MM:SS.mmm][LVL]`;
  a second process repeats each event line.
* MXU app log: `<maaend>/debug/YYYY-MM-DD-N.log`, one per MaaEnd launch, lines
  starting with `YYYY-MM-DD HH:MM:SS `.

collector_maaend re-exports every public name here.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

# The game's storage-full notice as MaaEnd's OCR logs it.
_END_STORAGE_FULL = "仓储空间已满"

# Strips the process / thread / source-file brackets between a framework line's
# stamp+level and its message.
_FW_META = re.compile(r"^(\[[^\]]+\]\[[A-Z]{3}\])(?:\[Px\d+\]\[Tx\d+\](?:\[[^\]]*\])?(?:\[L\d+\])?(?:\[[^\]]*\])?)?\s*")
# Framework event lines and ERR / WRN lines.
_FW_PICK = re.compile(r"\[msg=|^\[[^\]]+\]\[(?:ERR|WRN)\]")

# MXU app log lines, e.g. 2026-10-01-4.log:
#   2026-10-01 16:11:06 INFO  [App] 检测到待安装更新: v2.31.0-beta.6
#   2026-10-01 16:11:07 INFO  [App] 更新安装完成
_MXU_STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ")
_MXU_PENDING = re.compile(r"检测到待安装更新: (\S+)")
_MXU_INSTALLED = "更新安装完成"
# The pending line must fall within UPDATE_AT_START_S of the attempt's start, and
# the installed line within UPDATE_INSTALL_S after the pending line.
UPDATE_AT_START_S = (-2, 30)
UPDATE_INSTALL_S = 30


def _fw_files(maaend_dir) -> list[Path]:
    debug = Path(maaend_dir) / "debug"
    return sorted([*debug.glob("maafw*.log"), *(debug / "cpp-algo" / "debug").glob("maafw*.log")])


def _fw_lines(files: list[Path], t0: datetime, t1: datetime, want=None) -> list[str]:
    """Lines of `files` stamped from t0 to t1 (whole seconds) for which `want(line)`
    holds (every line when `want` is None), trailing newline removed. Unreadable
    files are skipped."""
    lo, hi = f"[{t0:%Y-%m-%d %H:%M:%S}", f"[{t1:%Y-%m-%d %H:%M:%S}~"
    out: list[str] = []
    for f in files:
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                out.extend(line.rstrip("\n") for line in fh
                           if lo <= line[:24] <= hi and (want is None or want(line)))
        except OSError:
            continue
    return out


def _short(line: str) -> "tuple[str, str]":
    """(the line without the bracket metadata, its message body)."""
    short = _FW_META.sub(r"\1 ", line)
    return short, short.split("]", 2)[-1]


def maafw_text(maaend_dir) -> str:
    """The storage-full lines of MaaEnd's framework logs, or "" when there is no
    directory or nothing to read."""
    if not maaend_dir:
        return ""
    out: list[str] = []
    for f in _fw_files(maaend_dir):
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                out.extend(line for line in fh if _END_STORAGE_FULL in line)
        except OSError:
            continue
    return "".join(out)


def maafw_window(maaend_dir, t0: datetime, t1: datetime) -> tuple[list[str], str]:
    """MaaEnd's framework-log lines stamped from t0 to t1 (whole seconds): the
    event lines ([msg=...]) and ERR / WRN lines when there are any, every line of
    the stretch otherwise. Each line keeps its stamp and level without the bracket
    metadata; a line whose body equals the previous one is dropped. Returns
    (lines, why there are none - '' when there are)."""
    if not maaend_dir:
        return [], "没配终末地的目录"
    files = _fw_files(maaend_dir)
    if not files:
        return [], "框架日志的文件夹里没有日志（终末地每次重启会清掉它）"
    stretch = _fw_lines(files, t0, t1)
    if not stretch:
        return [], "框架日志里这段时间没有记录"
    picked = [x for x in stretch if _FW_PICK.search(x)] or stretch
    out: list[str] = []
    seen_last = ""
    for line in sorted(picked):
        short, body = _short(line)
        if body == seen_last:
            continue
        seen_last = body
        out.append(short)
    return out, ""


def maafw_grep(maaend_dir, t0: datetime, t1: datetime, needles: "tuple[str, ...]") -> list[str]:
    """MaaEnd's framework-log lines stamped from t0 to t1 (whole seconds) that hold
    any of `needles`, as written or JSON-escaped (\\uXXXX); each body kept once,
    in time order. [] when there is no directory or nothing matched."""
    if not maaend_dir or not needles:
        return []
    forms = list(dict.fromkeys(f for n in needles
                               for f in (n, json.dumps(n).strip('"'))))
    found = _fw_lines(_fw_files(maaend_dir), t0, t1, lambda line: any(x in line for x in forms))
    out: list[str] = []
    seen: set[str] = set()
    for line in sorted(found):
        short, body = _short(line)
        if body in seen:
            continue
        seen.add(body)
        out.append(short)
    return out


def update_restart_version(maaend_dir, started) -> str:
    """The version MaaEnd installed at the start of the attempt that began at
    `started`, or "".

    MXU installs a pending update when it launches and restarts MaaEnd; the
    process AUTO-MAS watches exits and that attempt's tasks are booked failed.
    Only MXU's app log has these lines. The window is anchored on this attempt's
    start, not on the previous attempt's end.
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
