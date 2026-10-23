"""Daily activity short of 100 because the waveplates ran out: the evening shift tops it up.

The user, 2026-10-23 (Tokyo 11:0x-11:2x), after that morning's alarm for the daily activity
at 80 points, wanted the relay to handle it rather than ring: 「以后再遇到这种情况，最好让中继自己
知道该怎么做而不是报错」 (next time the relay should know what to do, not raise an error), as
「今天这个不是错误报警而是功能缺失问题」 (this was a missing feature, not a fault). Then the rule:
「中继不报警但是要在群里说一声今天早班没满活跃，晚班补。」 (no alarm, but tell the group that
the morning fell short and the evening shift tops it up) and 「如果连晚班都没满就报警。」 (alarm
if the evening fails too).
The waveplates are spent in full, the backup ones included: 「我有时候自己刷不代表你默认把体力
留给我刷」 (his own farming is no reason to keep any for him), 「如果正常体力不够的话，你们可以用
备用体力补」 (use the backup when the normal ones run short).

That morning OK-WW started with 98/240 and no backup (he had spent them himself the day
before), spent 80 and stopped (「current stamina: 19 not enough to continue」, 「used all
stamina」): 「累计消耗 180 点结晶波片」 stayed at 80/180 and the points at 80. Upstream's
DailyTask spends what that task still needs (farm_forgery / farm_tacet: must_use = 180 -
used), counting the backup in (BaseWWTask.use_stamina: total = current + back_up), so a
second DailyTask run once the waveplates have come back finishes it.

* morning(): an OK-WW round whose 「每日活跃满 100」 failed after its waveplates ran out, on
  a day with no top-up booked yet and a queue still to come today: the check passes as
  「晚班补」, the top-up is booked for that queue's time and the group hears it once
  (send_group: a notice, not an alarm).
* maybe_run(): from the first idle moment at or after that time OK-WW is dispatched once
  through AUTO-MAS (commands.run_script), tried again RETRY_GAP_S apart up to MAX_TRIES.
* That round is judged like any other, and a booked day is not booked again: short of
  100 once more is the usual 「⚠️ 这一轮没干完」 alarm.
* holding(): from the booked time until the top-up's record lands (or STALE after its
  dispatch) the daily report and the shutdown decision wait for it.
* A top-up that never got to run - not dispatched after MAX_TRIES, no record STALE after
  its dispatch, or the evening never came (still booked the next day) - leaves the day
  short of 100 as well: one 「⚠️ 这一轮没干完」 alarm says so (_alarm).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.activity")

SCRIPT = "OK-WW"
LABEL = "每日活跃满 100"          # outcome.daily_reward_checks
# OK-WW's own lines when the waveplates (backup included) cannot pay for another run:
# BaseWWTask.use_stamina 「current stamina: 19 not enough to continue」, ForgeryTask /
# TacetTask 「used all stamina」 (ok-script.log 2026-10-23 09:28:40 / 09:28:44).
_STAMINA_OUT = re.compile(r"not enough to continue|used all stamina")
_POINTS = re.compile(r"今天活跃 (\d+) 分")
MAX_TRIES = 3
RETRY_GAP_S = 300
# A dispatched top-up that has produced no record by then is let go, so the report and
# the power-off do not wait for ever. Measured: that morning's OK-WW daily took 12 minutes
# (ok-script.log 2026-10-23 09:18:16-09:29:52); AUTO-MAS's retries of one round stay
# within an hour.
STALE = timedelta(hours=2)
# A record starting up to this long before the dispatch can still be the top-up's: the
# log's first line and the dispatch time come from two clocks (makeup.SLACK).
SLACK = timedelta(minutes=2)


def _file(state_dir, day: str) -> Path:
    return Path(state_dir) / "activity-topup" / f"{day}.json"


def read(state_dir, day: str) -> dict:
    try:
        rec = json.loads(_file(state_dir, day).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return rec if isinstance(rec, dict) else {}


def _write(state_dir, day: str, rec: dict) -> None:
    f = _file(state_dir, day)
    f.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(f, json.dumps(rec, ensure_ascii=False, indent=1))


def _at(s) -> "datetime | None":
    try:
        return datetime.fromisoformat(str(s)).astimezone(SERVER_TZ)
    except (TypeError, ValueError):
        return None


def next_queue_time(automas_dir, after: datetime) -> "datetime | None":
    """The first queue time today later than `after`, on a weekday it fires (plan.schedule)."""
    from ark_relay.core import plan  # noqa: PLC0415
    after = after.astimezone(SERVER_TZ)
    weekday = after.strftime("%A")
    best = None
    for q in plan.schedule(automas_dir):
        for hhmm in q.get("times") or []:
            if weekday not in ((q.get("days") or {}).get(hhmm) or [weekday]):
                continue
            hh, mm = (int(x) for x in hhmm.split(":"))
            at = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if at > after and (best is None or at < best):
                best = at
    return best


def morning(eng, rec, text: str, checks: list) -> None:
    """Turn a waveplate-short 「每日活跃满 100」 into 「晚班补」 and book the top-up (see above)."""
    i = next((k for k, c in enumerate(checks) if c.label == LABEL and not c.ok), None)
    if i is None or not _STAMINA_OUT.search(text):
        return
    from ark_relay.features.alarm.records import run_day  # noqa: PLC0415
    day = run_day(rec)
    state_dir = eng.cfg.state_dir
    if read(state_dir, day):
        return                          # booked already: this is the top-up or a later round
    due = next_queue_time(eng.cfg.automas_dir, rec.finished or rec.started)
    if due is None:
        log.info("鸣潮活跃没满（%s），今天后面没有排期，补不了，照常报", checks[i].detail)
        return
    m = _POINTS.search(checks[i].detail)
    points = int(m.group(1)) if m else None
    _write(state_dir, day, {"booked": datetime.now(tz=SERVER_TZ).isoformat(), "run_id": rec.run_id,
                            "points": points, "due": due.isoformat(), "tries": 0, "result": "booked"})
    checks[i] = type(checks[i])(LABEL, True, texts.activity_topup_detail(points, due))
    send = getattr(eng.notifier, "send_group", None)
    errs = send(texts.ACTIVITY_TOPUP, texts.activity_topup_body(points, due)) if send else ["没有群机器人通道"]
    if errs:
        log.warning("鸣潮活跃晚班补：群里那一声没发出去（%s）", "；".join(errs))
    log.info("鸣潮活跃 %s 分没满（波片用完），记下 %s 补", points, f"{due:%H:%M}")


def holding(eng, now: "datetime | None" = None) -> str:
    """Why the report and the power-off wait for today's top-up; '' when they need not."""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    rec = read(eng.cfg.state_dir, now.strftime("%Y-%m-%d"))
    due = _at(rec.get("due"))
    if not rec or due is None or now < due or rec.get("result") in ("landed", "gave_up"):
        return ""
    sent = _at(rec.get("dispatched_at"))
    if sent is not None and now - sent > STALE:
        return ""
    return texts.ACTIVITY_TOPUP_WAIT


def maybe_run(eng, now: "datetime | None" = None) -> bool:
    """Dispatch today's booked top-up once the queue is idle at or after its time."""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    day = now.strftime("%Y-%m-%d")
    state_dir = eng.cfg.state_dir
    rec = read(state_dir, day)
    due = _at(rec.get("due"))
    _missed(eng, now)
    if not rec or due is None or now < due or rec.get("result") not in ("booked", "couldnt_run"):
        return False
    if (last := _at(rec.get("dispatched_at"))) is not None and (now - last).total_seconds() < RETRY_GAP_S:
        return False
    from ark_relay.features.makeup import makeup  # noqa: PLC0415
    if why := makeup._blocked(eng, now):
        if why != getattr(eng, "_activity_wait_note", ""):
            eng._activity_wait_note = why
            log.info("鸣潮活跃晚班补：等着（%s）", why)
        return False
    eng._activity_wait_note = ""
    tries = int(rec.get("tries") or 0) + 1
    rec.update(dispatched_at=now.isoformat(), tries=tries, result="dispatched")
    _write(state_dir, day, rec)          # before the dispatch: a crash after it must not dispatch twice
    try:
        ok, msg = makeup._dispatch(SCRIPT)
    except Exception as exc:  # noqa: BLE001 - a top-up must never take the service down
        ok, msg = False, f"{type(exc).__name__}: {exc}"
    if not ok:
        rec.update(result="couldnt_run" if tries < MAX_TRIES else "gave_up", note=msg)
        _write(state_dir, day, rec)
        log.info("鸣潮活跃晚班补：没派下去（第 %d 次，%s）", tries, msg)
        if rec["result"] == "gave_up":
            _alarm(eng, day, rec, texts.activity_topup_not_dispatched(tries, msg))
        return False
    from ark_relay.core import engine  # noqa: PLC0415
    engine.forget_scripts_cache()
    log.info("🔁 鸣潮活跃晚班补：再跑一次每日任务 → %s", msg)
    return True


def _alarm(eng, day: str, rec: dict, why: str) -> None:
    """The day stays short of 100 with no top-up round to judge: one alarm, then marked."""
    if rec.get("alarmed"):
        return
    rec["alarmed"] = datetime.now(tz=SERVER_TZ).isoformat()
    _write(eng.cfg.state_dir, day, rec)
    eng.notifier.send(texts.ROUND_INCOMPLETE, texts.activity_topup_failed(rec.get("points"), why), alert=True)
    log.info("鸣潮活跃晚班补没补成，已报：%s", why)


def _missed(eng, now: datetime) -> None:
    """Alarm a top-up that will not run: no record STALE after its dispatch today, or one
    still waiting from yesterday (the evening never came)."""
    today = now.strftime("%Y-%m-%d")
    rec = read(eng.cfg.state_dir, today)
    sent = _at(rec.get("dispatched_at"))
    if rec.get("result") == "dispatched" and sent is not None and now - sent > STALE:
        _alarm(eng, today, rec, texts.activity_topup_no_record(sent))
    yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    old = read(eng.cfg.state_dir, yday)
    if old.get("result") in ("booked", "couldnt_run", "dispatched"):
        _alarm(eng, yday, old, texts.ACTIVITY_TOPUP_NEVER_RAN)


def on_record(eng, rec) -> None:
    """An OK-WW record that started after today's dispatch is the top-up's: booked as landed."""
    if rec.script != SCRIPT:
        return
    day = rec.started.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
    top = read(eng.cfg.state_dir, day)
    sent = _at(top.get("dispatched_at"))
    if top.get("result") != "dispatched" or sent is None or rec.started < sent - SLACK:
        return
    top.update(result="landed", record=rec.run_id)
    _write(eng.cfg.state_dir, day, top)
    log.info("鸣潮活跃晚班补：这一趟的记录到了（%s）", rec.run_id)


def next_moment(state_dir, now: datetime) -> "tuple[datetime, str] | None":
    """When the loop must wake for the top-up: its time, or a retry after a dispatch that did not take."""
    rec = read(state_dir, now.strftime("%Y-%m-%d"))
    due = _at(rec.get("due"))
    if due is None:
        return None
    if rec.get("result") == "booked" and due > now:
        return due, "到点给鸣潮补活跃"
    if rec.get("result") == "couldnt_run" and (last := _at(rec.get("dispatched_at"))) is not None:
        return last + timedelta(seconds=RETRY_GAP_S), "鸣潮活跃晚班补再派一次"
    return None
