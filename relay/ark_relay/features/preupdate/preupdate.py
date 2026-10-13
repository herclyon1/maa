"""Run each program's own self-update in the boot window, before the first queue.

AUTO-MAS and OK-WW each have their own module: preupdate_automas
(`run_automas`), preupdate_okww (`run_okww`); preupdate_common holds the shared
process launching. Every `run_*` returns a note when an update landed, and
appends to `problems` whenever it could not confirm that a check happened. A
failure here leaves the round as it would be without the pre-update.

MaaEnd's and MAA's own updates are AUTO-MAS's job since the 2026-10-11
switch-over: AUTO-MAS updates MaaEnd in the first stage of a MaaEnd run, and
has MAA download its update during a run and installs it after each account
(MAA/AutoProxy.py 1164, 1853-1860; board file
打包-交接AUTO-MAS-删代码清单-1011.md, items 9a and 9b).

This module holds the once-a-day bookkeeping (should_run / mark_run /
wanted_today) and re-exports the public names of the per-program modules, so
callers write preupdate.xxx.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ark_relay.core.config import SERVER_TZ

from ark_relay.features.preupdate.preupdate_common import log
from ark_relay.features.preupdate.preupdate_automas import MAS_BUDGET_SECONDS, MAS_WAIT_SECONDS, run_automas
from ark_relay.features.preupdate.preupdate_okww import OKWW_BUDGET_SECONDS, OKWW_MIN_WAIT_SECONDS, run_okww

# Only public names are re-exported. Callers that need a private name import it
# from the module that defines it.
__all__ = [
    "MAS_BUDGET_SECONDS",
    "MAS_WAIT_SECONDS",
    "OKWW_BUDGET_SECONDS",
    "OKWW_MIN_WAIT_SECONDS",
    "RETRY_MIN",
    "log",
    "mark_run",
    "run_automas",
    "run_okww",
    "should_run",
    "wanted_today",
]


# Runs at most once per day: a service restart after a clean run does not run it
# again, and a run that left something unconfirmed may be retried after RETRY_MIN.
RETRY_MIN = 20          # minutes before a run that left something unconfirmed may be retried


def should_run(state_dir: "Path | None", now: datetime,
               *, had_problems: bool = False) -> bool:
    """Whether the pre-update should run today.

    * Finished cleanly today -> False.
    * Ran today but left something unconfirmed -> True once RETRY_MIN minutes
      have passed since that run.
    * Not run today, or no state directory -> True.
    """
    if not state_dir:
        return True
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    st = StateStore(state_dir).get("updates", "preupdate")
    if not isinstance(st, dict):
        return True
    if st.get("day") != now.strftime("%Y-%m-%d"):
        return True
    if st.get("clean"):
        return False
    try:
        last = datetime.fromisoformat(str(st.get("at")))
    except (TypeError, ValueError):
        return True
    return (now - last).total_seconds() >= RETRY_MIN * 60


def mark_run(state_dir: "Path | None", now: datetime, *, clean: bool) -> None:
    if not state_dir:
        return
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    try:
        StateStore(state_dir).set("updates", "preupdate",
                                  {"day": now.strftime("%Y-%m-%d"), "at": now.isoformat(),
                                   "clean": bool(clean)})
    except OSError:
        log.warning("预更新的记账写不下来，下次重启可能会重跑一遍", exc_info=True)


def wanted_today(automas_dir: Path | None, now: datetime | None = None,
                 kind: str = "OK-WW") -> bool:
    """True when a queue still to come today runs `kind`.

    OK-WW by default: it is the one program the pre-update still launches (its
    update overwrites the local patches, which are re-applied right after), so
    the pre-update is wanted only before a queue that runs it. Read from
    AUTO-MAS's own schedule (plan.schedule); queue times already past are ignored.
    """
    from ark_relay.core import plan  # noqa: PLC0415 - avoids an import cycle

    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    cfg_dir = Path(automas_dir) / "config" if automas_dir else None
    if not cfg_dir or not cfg_dir.is_dir():
        return False
    scripts = plan._scripts(cfg_dir)
    for q in plan.schedule(automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due < now:
                continue
            # Only the items that run at that time on that day (plan.runs_at: the
            # weekday rules and the relay's own one-day skip).
            if any((scripts.get(uid) or {}).get("kind") == kind
                   for uid in plan.runs_at(q, hhmm, due)):
                return True
    return False
