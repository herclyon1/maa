"""Reading what the games' own programs wrote for one run: MAA's asst.log,
MaaEnd's app logs and on_error pictures, OK-WW's log and the OK-WW config
AUTO-MAS had in effect. handle.py judges a run with these.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core.config import SERVER_TZ

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
    # Upstream's own condition (OK-WW v3.7.4 DailyTask.py:84-93, defaults at :32-38),
    # which the overrides leave as it is: nests run when 「Auto Farm all Nightmare
    # Nest」 is an additional task, or when 「Farm Nightmare Nest for Daily Echo」
    # (default on) is set, the farm target is not Tacet Suppression (the default),
    # and the daily reward is not ready yet. That last part is the log's to tell
    # (outcome.okww_checks: dailies done at start -> the nest is judged only if its
    # task ran). The nest filter 「Only Farm These Nests」 only narrows a run that
    # happens; until 2026-10-13 a leftover filter, or the echo flag on its own,
    # made every daily expect nests (audit 2026-10-13 item 9).
    daily = _okww_master_config(automas_dir, "DailyTask")
    if not daily:
        return None
    adds = daily.get("Additional Tasks to Run After Daily Task") or []
    if "Auto Farm all Nightmare Nest" in adds:
        return True
    return bool(daily.get("Farm Nightmare Nest for Daily Echo", True)
                and daily.get("Which to Farm", "Tacet Suppression") != "Tacet Suppression")


# MAA's line-leading timestamp: [2026-08-30 09:09:41.495][INF]...
_MAA_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


# How much of the tail to take. One round is roughly 30,000 lines / 6-7 MB, so
# 16 MB is plenty to cover a whole round.
_MAA_LOG_TAIL = 16 * 1024 * 1024


# What AUTO-MAS writes as the entire history log of a record it created only to
# close a retry round (sample: history/2026-09-17/endfield/MaaEnd-06-32-49.log,
# the whole file):
MAAEND_NOTHING_TO_RUN_LOG = "MaaEnd 没有可执行任务，请检查任务配置, 无日志记录"


MAAEND_NOTHING_TO_RUN = "没有可执行任务"


# MaaEnd's app-log line stamp: 「2026-10-10 09:14:22 INFO  [App] ...」 (MXU) or
# 「[2026-09-01 11:06:21.834] ...」.
_MAAEND_TS = re.compile(r"^\[?(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


def _in_window(text: str, started: datetime, until: datetime) -> str:
    """The lines of `text` stamped inside [started - WINDOW_SLACK, until] (Beijing,
    the machine's clock), unstamped lines following the line before them; `text` as
    it is when no line carries a stamp (a format this does not know is not cut away).

    The slack before the start (evidence.WINDOW_SLACK): MaaEnd loads its config,
    and says a dropped option, before AUTO-MAS's record starts (10-10: 09:14:22
    against 09:14:25, tests/replay/2026-10-10)."""
    from ark_relay.features.evidence.evidence import WINDOW_SLACK  # noqa: PLC0415
    cut = (started - timedelta(seconds=WINDOW_SLACK)).astimezone(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
    top = until.astimezone(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
    out: list[str] = []
    keep, stamped = False, False
    for line in text.splitlines():
        if m := _MAAEND_TS.match(line):
            stamped = True
            keep = cut <= m.group(1) <= top     # fixed width: lexical order is time order
        if keep:
            out.append(line)
    return "\n".join(out) if stamped else text


def _maaend_app_log(maaend_dir: "str | Path | None",
                    started: datetime, until: "datetime | None" = None) -> str:
    """The app log MaaEnd wrote **itself** for this round.

    `until` (the run's finish + 5 min when its times are known, as for
    _maa_app_log) bounds it from above, and the lines are then cut by their own
    stamps (_in_window): one dated file holds several rounds, and a round judged late (after
    a restart, a backlog at boot) read the later rounds' lines as its own (audit
    2026-10-13 s8 #2). Without `until` the files are taken whole, as before.

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
            text = f.read_text(encoding="utf-8", errors="replace")[-200_000:]
        except OSError:
            continue
        if until is not None:
            text = _in_window(text, started, until)
        if text:
            out.append(text)
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
                      started: datetime, until: "datetime | None" = None) -> list[str]:
    """The on_error screenshot filenames that appeared during this round.

    MaaEnd does not report an error when it gets stuck, but a failed
    universal-navigation step saves an image - that image is the only evidence.
    `until` (finish + 5 min, as for _maaend_app_log) leaves out the later
    rounds' pictures: 10-01's 15:24 round was judged at 17:27 and blamed for a
    16:44 picture of the 16:12 round (relay.log 24567; audit 2026-10-13 s8 #2).
    Each picture goes by the time in its name (collector_maaend.round_shots), as
    machine check #29 reads the same set.
    """
    from ark_relay.features.verify import collector_maaend  # noqa: PLC0415
    return collector_maaend.round_shots(maaend_dir, started, until)


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
