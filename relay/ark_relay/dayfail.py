"""One alarm when a game got nothing done all day (D206), the exception to 「只进日报」.

Since 2026-10-05 a MAA / MaaEnd failure goes to the daily report only: it is held,
gets one make-up run (makeup.py), and is dropped without a push whatever comes of
it - the user, 13:07: 「中继我就要求一个，他不要再报错了」. That rule leaves one case
nobody would want silent: a whole day on which a game never once got its work
done. D206 (主持定): the same game on the same Beijing day, once every shift that
was due has run and the make-up is over, still without a single good run -> one
push to the group, and no more about that game that day.

A day is judged only once nothing about it can still change:

* every scheduled time of a queue that runs the script has come (AUTO-MAS's own
  QueueConfig, read through plan; a queue skipped that day does not count), and
  the last of them has produced a record of the script - or is so long past
  (WRITE_OFF, plan.recent_due_queues' window) that it never will;
* the script is not running, no failure of it from that day is held
  (handle._flush_pending), and makeup.waiting no longer names it.

Then: a good run is one that is `ok` and not marked 「没干完」 (`incomplete`), or
the day's make-up booked as passed (its record can sit in the next day's ledger).
A run a person started at AUTO-MAS itself (raw.hand_started) or one cut short by
the red button (raw.manual_stop) is neither due nor good. Failures the relay
already declares not to be faults - maintenance / could not enter the game
(their own notice), the update-day MAA, MAA short of sanity, MaaEnd failing only
on SOFT_FAILS - do not make a day of failures on their own.

Yesterday is judged too, until NEXT_DAY_UNTIL: an evening make-up dispatched just
before midnight finishes after it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ

log = logging.getLogger("ark.dayfail")

SCRIPTS = ("MAA", "MaaEnd")
GAME = {"MAA": "明日方舟", "MaaEnd": "终末地"}
# A run started this long before its queue's time still belongs to it (the same
# allowance shutdown._unfinished_queues gives).
QUEUE_SLACK = timedelta(minutes=5)
# A due queue that has produced nothing for this long is written off
# (plan.recent_due_queues' default window): the missed-run check reports it.
WRITE_OFF = timedelta(minutes=120)
# Yesterday is still judged before this hour (server clock).
NEXT_DAY_UNTIL = 6


def alert_key(script: str) -> str:
    return f"全天|{script}"


def _day(t: datetime) -> str:
    return t.astimezone(SERVER_TZ).strftime("%Y-%m-%d")


def _at(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)


def shifts(automas_dir, state_dir, script: str, day: str) -> list[tuple[datetime, str]]:
    """(due, queue name) of every scheduled time on `day` whose queue runs `script`,
    earliest first; queues skipped that day are left out. [] when the queue config
    cannot be read."""
    from . import modes, names, plan  # noqa: PLC0415
    if not automas_dir:
        return []
    cfg_dir = Path(automas_dir) / "config"
    if not cfg_dir.is_dir():
        return []
    base = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=SERVER_TZ)
    try:
        skipped = {names.canonical(q) for q in modes.skipped_today_all(Path(state_dir), base + timedelta(hours=12))}
    except Exception:  # noqa: BLE001 - an unreadable skip flag counts as no skip
        skipped = set()
    kinds = {uid: s.get("kind") for uid, s in plan._scripts(cfg_dir).items()}
    out: list[tuple[datetime, str]] = []
    for q in plan._queues(cfg_dir):
        name = names.canonical(q.get("name") or "")
        if name in skipped or script not in {kinds.get(uid) for uid in q.get("items") or []}:
            continue
        for hhmm in q.get("times") or []:
            try:
                hh, mm = (int(x) for x in str(hhmm).split(":"))
            except ValueError:
                continue
            out.append((base.replace(hour=hh, minute=mm), name))
    return sorted(out)


def _counted(e: dict, script: str) -> bool:
    raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
    return (e.get("script") == script and not e.get("transitional")
            and not raw.get("hand_started") and not raw.get("manual_stop"))


def _good(e: dict) -> bool:
    return bool(e.get("ok")) and not e.get("incomplete")


def _excused(eng, e: dict) -> bool:
    """A failure the relay already says is not a fault (see the module docstring)."""
    raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
    if raw.get("maintenance") or raw.get("maaend_unreachable") or raw.get("maintenance_day") \
            or raw.get("maa_sanity_short"):
        return True
    failed = set(e.get("failed_tasks") or [])
    return (e.get("script") == "MaaEnd" and not e.get("ok") and bool(failed)
            and failed <= set(getattr(eng, "SOFT_FAILS", ())))


def _settled(eng, script: str, day: str, now: datetime, rows: list[dict], due: list) -> str:
    """'' when the day of `script` can be judged; otherwise what it still waits for."""
    from . import makeup  # noqa: PLC0415
    if not due:
        return "读不到这一天该跑的班次"
    if any(t > now for t, _ in due):
        return "后面还有班次"
    last = due[-1][0]
    ran = any((s := _at(e.get("started"))) is not None and s >= last - QUEUE_SLACK
              for e in rows if e.get("script") == script)
    if not ran and now < last + WRITE_OFF:
        return "最后一班还没出记录"
    if eng._script_running(script):
        return "还在跑"
    if any(r.script == script and _day(r.started) == day for r in eng._pending.values()):
        return "还有失败压着等重试或补跑"
    if script in makeup.waiting(eng, now):
        return "补跑还没结束"
    # A failed run (not 「没干完」, which gets no make-up) is held and gets today's
    # make-up; should it not be held any more for whatever reason, its make-up is
    # still owed, and the day is not over before it. Yesterday's never gets one
    # (makeup.eligible: started today).
    if day == _day(now) and not makeup.attempted(eng.cfg.state_dir, day, script) \
            and any(not e.get("ok") and not _excused(eng, e) for e in rows):
        return "补跑还没结束"
    return ""


def _makeup_phrase(ent) -> tuple[bool, str]:
    """(the make-up ran and failed, what to add about it)."""
    from . import makeup  # noqa: PLC0415
    if not isinstance(ent, dict):
        return False, ""
    res, note = ent.get("result"), str(ent.get("note") or "").strip()
    if res in (makeup.FAILED, makeup.NO_RECORD):
        return True, ""
    if res == makeup.GAVE_UP and note.startswith("不补跑"):
        return False, note
    if res in (makeup.GAVE_UP, makeup.COULDNT_RUN):
        return False, "补跑没能开跑" + (f"（{note}）" if note else "")
    return False, ""


def _reason(e: dict) -> str:
    from .core import _fmt_failed  # noqa: PLC0415
    if e.get("ok") and e.get("incomplete"):
        first = str(e["incomplete"]).strip().splitlines()
        return "跑完了但没干完：" + (first[0] if first else "")
    raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
    return _fmt_failed(list(e.get("failed_tasks") or []), causes=raw.get("maaend_fail_causes"))


def body_for(script: str, day: str, now: datetime, ran: list[str], failures: list[dict], ent) -> str:
    from . import texts  # noqa: PLC0415
    made_up, extra = _makeup_phrase(ent)
    what = list(dict.fromkeys(ran)) + (["补跑"] if made_up else [])
    last = max(failures, key=lambda e: _at(e.get("started")) or now)
    page = next((p for e in sorted(failures, key=lambda e: _at(e.get("started")) or now, reverse=True)
                 if (p := (e.get("raw") or {}).get("evidence_page"))), "")
    when = "今天" if day == _day(now) else datetime.strptime(day, "%Y-%m-%d").strftime("%m-%d")
    return texts.day_failed_body(GAME.get(script, script), when, what, extra, _reason(last), page)


def judge(eng, script: str, day: str, now: datetime) -> tuple[str, str]:
    """(body, '') when `script` got nothing done on `day` and that is final; ('', why not) otherwise."""
    from . import makeup  # noqa: PLC0415
    rows = [e for e in eng.state.read_ledger(day) if _counted(e, script)]
    ent = makeup.read_marker(eng.cfg.state_dir, day).get(script)
    if any(_good(e) for e in rows) or (isinstance(ent, dict) and ent.get("result") == makeup.OK):
        return "", "有一趟跑成了"
    failures = [e for e in rows if not _excused(eng, e)]
    if not failures:
        return "", "没有算数的失败"
    due = shifts(eng.cfg.automas_dir, eng.cfg.state_dir, script, day)
    if why := _settled(eng, script, day, now, rows, due):
        return "", why
    ran = [name for t, name in due
           if any((s := _at(e.get("started"))) is not None and s >= t - QUEUE_SLACK for e in rows)]
    return body_for(script, day, now, ran, failures, ent), ""


def maybe_alert(eng, now: datetime | None = None) -> int:
    """The tick step: push the day's alarm for every game that has earned one. Returns how many went out."""
    from . import texts  # noqa: PLC0415
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    days = [_day(now)]
    if now.hour < NEXT_DAY_UNTIL:
        days.insert(0, _day(now - timedelta(days=1)))
    sent = 0
    for day in days:
        for script in SCRIPTS:
            key = alert_key(script)
            if eng._already_alerted(day, key):
                continue
            body, why = judge(eng, script, day, now)
            if not body:
                log.debug("全天没成：%s %s 不报（%s）", day, script, why)
                continue
            if errs := eng.notifier.send(texts.day_failed(GAME.get(script, script)), body, alert=True):
                # WARNING, not ERROR: an ERROR line is itself a group alarm (errwatch).
                log.warning("全天没成的报警没推出去，下一轮再试：%s", "；".join(errs))
                continue
            eng._mark_alerted(day, key)
            sent += 1
            log.warning("🚨 %s %s 一趟都没跑成，已进群一次：%s", day, script, body.replace("\n", " "))
    return sent
