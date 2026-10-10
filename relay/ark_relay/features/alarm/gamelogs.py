"""Reading what the games' own programs wrote for one run: MAA's asst.log,
MaaEnd's app logs and on_error pictures, OK-WW's log and the OK-WW config
AUTO-MAS had in effect. handle.py judges a run with these.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

# Same logger as handle.py: relay.log names these lines "ark.handle".
log = logging.getLogger("ark.handle")


def _okww_master_config(automas_dir: str | Path | None, name: str) -> dict:
    """Read the OK-WW config that is **actually in effect**.

    The copy in OK-WW's own directory is replaced wholesale by AUTO-MAS before a
    run and restored afterwards, so reading it after the fact reads a fake. The
    one actually in effect is under
    `<automas>/data/<script id>/Default/ConfigFile/`.
    The script id is not fixed, so just scan - on this machine only OK-WW has
    this directory structure.
    """
    if not automas_dir:
        return {}
    root = Path(automas_dir) / "data"
    if not root.is_dir():
        return {}
    for sid in root.iterdir():
        f = sid / "Default" / "ConfigFile" / f"{name}.json"
        if f.is_file():
            try:
                d = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and d:
                return d
    return {}


def _okww_nest_expected(automas_dir: str | Path | None) -> bool | None:
    """Whether this round was supposed to farm tacet nests. **Returns None, not False, when the config cannot be read.**

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_okww_nest_expected」。
    """
    nest = _okww_master_config(automas_dir, "NightmareNestTask")
    daily = _okww_master_config(automas_dir, "DailyTask")
    if not nest and not daily:
        return None
    if (nest.get("Only Farm These Nests") or "").strip():
        return True
    if daily.get("Farm Nightmare Nest for Daily Echo"):
        return True
    adds = daily.get("Additional Tasks to Run After Daily Task") or []
    return "Auto Farm all Nightmare Nest" in adds


# MAA's line-leading timestamp: [2026-08-30 09:09:41.495][INF]...
_MAA_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


# How much of the tail to take. One round is roughly 30,000 lines / 6-7 MB, so
# 16 MB is plenty to cover a whole round.
_MAA_LOG_TAIL = 16 * 1024 * 1024


# What AUTO-MAS writes as the entire history log of a record it created only to
# close a retry round (real text, 2026-09-17 history/2026-09-17/endfield/MaaEnd-06-32-49.log,
# the whole file):
MAAEND_NOTHING_TO_RUN_LOG = "MaaEnd 没有可执行任务，请检查任务配置, 无日志记录"


MAAEND_NOTHING_TO_RUN = "没有可执行任务"


def _maaend_app_log(maaend_dir: "str | Path | None",
                    started: datetime) -> str:
    """The app log MaaEnd wrote **itself** for this round.

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_maaend_app_log」。
    """
    if not maaend_dir:
        return ""
    d = Path(maaend_dir) / "debug"
    if not d.is_dir():
        return ""
    cut = started.timestamp()
    out: list[str] = []
    # Filenames look like 2026-08-29-7.log; maafw* / go-service are framework
    # logs and are not read.
    for f in sorted(d.glob("20??-??-??-*.log")):
        try:
            if f.stat().st_mtime < cut:
                continue
            out.append(f.read_text(encoding="utf-8", errors="replace")[-200_000:])
        except OSError:
            continue
    return "\n".join(out)


def _maa_app_log(maa_dir: "str | Path | None", started: datetime,
                 until: "datetime | None" = None) -> "str | None":
    """The asst.log MAA wrote **itself** for this round, keeping only the lines inside this round's time window.

    来龙去脉见 docs/CODE-HISTORY.md「handle.py:_maa_app_log」。
    """
    if not maa_dir:
        return None
    f = Path(maa_dir) / "debug" / "asst.log"
    if not f.is_file():
        return None
    try:
        # One round alone is over 30,000 lines, so reading the whole file is
        # unnecessary; take the tail and then cut by time.
        size = f.stat().st_size
        with f.open("rb") as fh:
            if size > _MAA_LOG_TAIL:
                fh.seek(size - _MAA_LOG_TAIL)
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    # An upper bound is mandatory: a start with no end sweeps in lines from the
    # **later rounds** as well, which is charging this morning's error to last
    # night. The exception is `until` being None, where no upper bound is set -
    # the times on such a record are untrustworthy to begin with, and taking too
    # much beats cutting the whole round away.
    # 来龙去脉见 docs/CODE-HISTORY.md「handle.py:_maa_app_log」
    cut = started.strftime("%Y-%m-%d %H:%M:%S")
    top = until.strftime("%Y-%m-%d %H:%M:%S") if until else None
    out: list[str] = []
    keep = False
    for line in raw.splitlines():
        m = _MAA_TS.match(line)
        if m:
            # The timestamp is fixed-width, so lexical order is chronological
            # order and it can be compared directly here.
            ts = m.group(1)
            keep = ts >= cut and (top is None or ts <= top)
        # A line with no timestamp is a continuation of the previous one and
        # follows it - do not judge it on its own, or traceback lines get pulled
        # in unconditionally (this trap is recorded in arklog.py).
        if keep:
            out.append(line)
    # Not a single line inside the window = this round's log was not found,
    # which is just as uncheckable as "cannot read the file". Returning "" would
    # be read by the checks as "no errors at all", which is another false green.
    return "\n".join(out) if out else None


def _maaend_new_shots(maaend_dir: str | Path | None,
                      started: datetime) -> list[str]:
    """The on_error screenshot filenames that appeared during this round.

    MaaEnd does not report an error when it gets stuck, but a failed
    universal-navigation step saves an image - that image is the only evidence.
    """
    if not maaend_dir:
        return []
    d = Path(maaend_dir) / "debug" / "on_error"
    if not d.is_dir():
        return []
    cut = started.timestamp()
    return sorted(p.name for p in d.glob("*.png")
                  if p.stat().st_mtime >= cut)


def _okww_log_file(okww_dir: "str | Path | None") -> "Path | None":
    """OK-WW's newest log. Say something when it is not found; never return None silently."""
    if not okww_dir:
        log.warning("okww_dir 没解析出来，OK-WW 的日志切片存不了")
        return None
    logs = Path(okww_dir) / "data" / "apps" / "ok-ww" / "working" / "logs"
    try:
        return max(logs.glob("*.log*"), key=lambda q: q.stat().st_mtime)
    except (OSError, ValueError):
        log.warning("OK-WW 的日志目录 %s 里没有日志", logs)
        return None
