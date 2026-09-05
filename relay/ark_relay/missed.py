"""漏跑与缺项告警：该跑的队列没跑、跑了却少一个脚本。

从 engine.py 拆出来（2026-09-06，只搬不改）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from . import core, modes, plan
from .config import SERVER_TZ

log = logging.getLogger("ark.missed")

# How long past a queue's time before "it produced nothing" becomes a fault.
MISSED_GRACE_MIN = 25


# ---------- a run that should have happened and did not ----------

def _check_missed_runs(eng, now: datetime | None = None,
                       grace_min: int = MISSED_GRACE_MIN) -> None:
    """Alert when a scheduled queue produced nothing.

    "Did not run" is as much a fault as "ran and failed", and it is the
    one the operator is least likely to notice on their own - silence
    looks exactly like everything being fine.

    Only covers windows while the relay itself is up. A machine that never
    powered on cannot be caught from inside it; that is the GitHub Actions
    watchdog's job (scripts/watchdog.py, reading Tailscale lastSeen).
    """
    # Debug mode: the operator is deliberately making the machine do
    # nothing; "it produced nothing" is the plan, not a fault.
    if modes.debug_active(eng.state.dir):
        return
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    day = now.strftime("%Y-%m-%d")
    entries = eng._recent_entries(now)
    for q in plan.schedule(eng.cfg.automas_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if now < due + timedelta(minutes=grace_min):
                continue  # not late yet
            key = f"{day}/{q['name']}/{hhmm}"
            if key in eng._missed_alerted:
                continue
            # Anything recorded after the scheduled time counts as "it ran".
            ran = any(datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
                      >= due - timedelta(minutes=5) for e in entries)
            if ran:
                eng._missed_alerted.add(key)   # settled, stop checking
                continue
            # Was this machine even awake when the queue was due? If it
            # was off, "nothing ran" is not something this relay can
            # observe from the inside, and claiming it would be a false
            # alarm every single morning - that is the GitHub Actions
            # watchdog's job instead.
            #
            # Uptime, not the relay's own start time. Those differ every
            # time the relay restarts itself for a selfupdate, and an
            # update that runs long enough to cross the queue's time used
            # to make the new process disqualify itself - swallowing a
            # genuine missed run on precisely the boot where something had
            # already gone slowly enough to be worth knowing about.
            watching_since = eng._boot_time(now) or eng._started_at
            if watching_since > due:
                eng._missed_alerted.add(key)
                continue
            if eng._scripts_running():
                # 09-03 11:15：MaaEnd 正被 AUTO-MAS 重试第三次、进程好好的，
                # 这里却因为「75 分钟没有记录」喊了「MaaEnd 没有运行」。
                log.info("🔌 %s 还没有记录，但脚本进程在跑，先不喊", q["name"])
                continue
            late = int((now - due).total_seconds() // 60)
            title, body = core.format_missing(
                f"{q['name']} 没有运行", due,
                f"已经晚了 {late} 分钟，今天没有任何该时段的运行记录。\n"
                "可能原因：AUTO-MAS 没启动、定时没触发、模拟器或游戏起不来。")
            if not eng.notifier.send(title, body, alert=True):
                eng._missed_alerted.add(key)
                log.warning("🔌 %s 该跑没跑，已告警", q["name"])
    eng._check_partial_queues(now, day, entries)


def _check_partial_queues(eng, now: datetime, day: str,
                          entries: list[dict]) -> None:
    if eng._scripts_running():
        return          # 还有脚本在跑，缺的那项可能正是它
    """Alert when a queue ran but one of its scripts never did.

    The check above only asks "did this queue produce anything", and on
    2026-08-16 that was not enough: MAA ran, so the queue counted as having
    run, while 终末地 never started at all and nobody was told. A queue that
    delivers half of what it promised is a fault, and it is invisible from
    the outside - the day looks green.

    Two things make this safe to alert on:

    Grace is generous. The morning queue runs MAA (~20 min) and only then
    MaaEnd (~25 min), so MaaEnd's record can legitimately be 45+ minutes
    late. Alerting at the same 25-minute mark as "nothing ran" would fire
    on every single healthy morning.

    Records are matched to their own queue by start time, so the morning's
    MaaEnd can never be mistaken for the evening's.
    """
    for q in plan.recent_due_queues(eng.cfg.automas_dir, now,
                                    window_minutes=eng.cfg.partial_window):
        due = q["due"]
        if now < due + timedelta(minutes=eng.cfg.partial_grace):
            continue  # still legitimately in progress
        ran = {e["script"] for e in entries
               if datetime.fromisoformat(e["started"]).astimezone(SERVER_TZ)
               >= due - timedelta(minutes=5)}
        if not ran:
            continue  # nothing at all - already covered by the check above
        for kind in q["kinds"]:
            if kind in ran:
                continue
            key = f"{day}/{q['name']}/{due:%H:%M}/{kind}"
            if key in eng._missed_alerted:
                continue
            # Was the machine awake when this queue was due? Same test,
            # and the same reason, as in _check_missed_runs: uptime rather
            # than the relay's start time, so a selfupdate restart cannot
            # make the relay disqualify itself from reporting a script that
            # never started.
            watching_since = eng._boot_time(now) or eng._started_at
            if watching_since > due:
                eng._missed_alerted.add(key)
                continue
            late = int((now - due).total_seconds() // 60)
            title, body = core.format_missing(
                f"{kind} 没有运行（{q['name']}）", due,
                f"这一轮跑了 {'、'.join(sorted(ran))}，但 {kind} 一次记录都没有，"
                f"已经晚了 {late} 分钟。\n"
                "队列本身是跑了的，所以不是没开机——是这一项自己没起来。")
            if not eng.notifier.send(title, body, alert=True):
                eng._missed_alerted.add(key)
                log.warning("🔌 %s 缺项：%s 没跑，已告警", q["name"], kind)
