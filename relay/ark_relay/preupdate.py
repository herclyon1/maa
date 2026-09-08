"""Get MaaEnd's self-update out of the way before a queue needs it.

The problem this exists for, measured on 2026-08-22:

MaaEnd checks for updates only at startup, and AUTO-MAS kills and relaunches it
before every round - so every round lands on that check. When there is a new
build, MaaEnd downloads it and **restarts its own process**. AUTO-MAS's log
monitor is attached to the pid it launched, that pid is gone, and every task in
the round is reported failed about four seconds later:

    11:47:57  AUTO-MAS starts MaaEnd
    11:47:58  MaaEnd.exe pid=15772 takes focus
    11:48:14  MaaEnd.exe pid=20416 takes focus     <- restarted after updating
    11:48:18  all 14 tasks fail

The retry then succeeds, because by then the update is done - which is exactly
the "fails once or twice then heals itself" pattern that has been written off as
a window race for days. MaaEnd's own log says it plainly on the second attempt:
"检测到刚更新完成: v2.26.0-beta.1".

The update channel is `beta`, which ships most days, so most days start with a
wasted attempt and a failure alert.

Turning auto-update off is not an option - staying current is the point of it.
So the update is moved instead of removed: run MaaEnd once in the gap between
boot and the first queue, let it update and restart there where nothing is
watching, and close it. By the time the queue starts, the check returns
"有更新=false" and the process it launches is the one that stays.

Upstream declined to fix the underlying window-focus behaviour (MaaEnd#4820),
so this is handled from our side or not at all.

Measured side effects of launching MaaEnd on its own, 2026-08-22 12:37:

    12:37:12 WARN  [App] 自动执行：目标实例不存在，跳过自动执行
    12:37:12 INFO  [App] 检查更新: MaaEnd, 当前版本: v2.26.0-beta.1, 频道: beta
    12:37:13 INFO  [App] 更新检查完成: 最新版本=v2.26.0-beta.1, 有更新=false

It does not launch the game (verified over 64 seconds - only MaaEnd.exe ran),
it does not start its configured tasks, and the check itself takes one second.
So on the ordinary day, when there is nothing to update, this costs a few
seconds and touches nothing.

Why not check for the update from here and skip the launch entirely: doing that
means reimplementing MaaEnd's own version lookup - its MirrorChyan resource id,
its channel, its version format - and keeping that in step with a program that
ships most days. The launch already answers the question authoritatively in one
second, with no side effects worth avoiding. Downloading and applying the update
from here would be worse still: that is MaaEnd's updater, including whatever
file replacement and migration it does, and reimplementing it earns nothing but
a second thing to keep correct.

Failure here is deliberately cheap: if the pre-update cannot run, does not
finish, or the network is slow, the round proceeds exactly as it does today -
one wasted attempt, then the retry succeeds.


The pre-update is split per program into five modules (2026-09-08, moved
verbatim): preupdate_common / _maaend / _maa / _automas / _okww. This module
keeps the shared bookkeeping functions and re-exports every name unchanged, so
callers and tests still write preupdate.xxx.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ

from .preupdate_common import (
    log,
    BUDGET_SECONDS,
)
from .preupdate_maaend import (
    run,
)
from .preupdate_maa import (
    maa_update_pending,
    run_maa,
)
from .preupdate_automas import (
    MAS_BUDGET_SECONDS,
    MAS_WAIT_SECONDS,
    run_automas,
)
from .preupdate_okww import (
    OKWW_BUDGET_SECONDS,
    OKWW_MIN_WAIT_SECONDS,
    run_okww,
)

# Only public names are forwarded here. Before 2026-09-08 this facade also
# re-exported all 53 private names from the five modules and listed them in
# __all__ -- which announced "_close, _read and friends are yours to use",
# stopped __all__ from describing the public interface at all, and meant that
# changing any module's private implementation forced an edit to this list.
# The places that need a private name (gameupdate, desktop, commands, a few
# tests) now import it from the module it lives in.
__all__ = [
    "BUDGET_SECONDS",
    "MAS_BUDGET_SECONDS",
    "MAS_WAIT_SECONDS",
    "OKWW_BUDGET_SECONDS",
    "OKWW_MIN_WAIT_SECONDS",
    "RETRY_MIN",
    "log",
    "maa_update_pending",
    "mark_run",
    "run",
    "run_automas",
    "run_maa",
    "run_okww",
    "should_run",
    "wanted_today",
]



# Once a day is enough. This used to only ask "is there still a queue today
# that runs MaaEnd?" without recording "already ran today" -- so **every
# service restart re-ran the whole round**, launching MAA, MaaEnd and OK-WW
# one by one to check for updates. On 2026-08-31 I deployed three times in one
# morning and it ran three times; on the third, MAA did not reach a conclusion
# within 180 seconds and raised a "could not confirm" alert.
# That alert was not wrong -- there simply should never have been a third run.
RETRY_MIN = 20          # How long before a retry is allowed when the last round left something unconfirmed


def should_run(state_dir: "Path | None", now: datetime,
               *, had_problems: bool = False) -> bool:
    """Whether the pre-update should run today.

    * Already finished **cleanly** today -> do not run (a service restart must
      not redo it)
    * Ran today but left something unconfirmed -> a retry is allowed, but only
      after at least RETRY_MIN minutes, so back-to-back deploys cannot turn it
      into a chain of retries
    """
    if not state_dir:
        return True
    from .statestore import StateStore  # noqa: PLC0415
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
    from .statestore import StateStore  # noqa: PLC0415
    try:
        StateStore(state_dir).set("updates", "preupdate",
                                  {"day": now.strftime("%Y-%m-%d"), "at": now.isoformat(),
                                   "clean": bool(clean)})
    except OSError:
        log.warning("预更新的记账写不下来，下次重启可能会重跑一遍", exc_info=True)


def wanted_today(automas_dir: Path | None, now: datetime | None = None) -> bool:
    """True when a queue still to come today runs MaaEnd.

    The evening queue is MAA only, so warming up before it would start a
    program nothing is going to use. Read from AUTO-MAS's own schedule, so a
    queue changed there changes this too.
    """
    from . import plan  # noqa: PLC0415 - avoids an import cycle

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
                continue        # already past; warming up helps nothing
            if any((scripts.get(uid) or {}).get("kind") == "MaaEnd"
                   for uid in q.get("items", [])):
                return True
    return False
