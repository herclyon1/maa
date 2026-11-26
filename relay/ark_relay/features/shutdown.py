"""Shutdown decision: should this round power the machine off, and why.

`decide` judges and writes nothing; `_maybe_shutdown` does what follows a "go" (the
command itself is Engine._power_off); `abort_countdown` cancels the relay's own
countdown when a phone order asks for it.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from ark_relay.features import modes
from ark_relay.core import texts, plan
from ark_relay.features import stagegate
from ark_relay.features import selfcheck as tape
from ark_relay.core.config import SERVER_TZ

log = logging.getLogger("ark.shutdown")

# How far a round's FIRST record may sit from a scheduled time and still count
# as that scheduled round. Only the first record is tested: a queue's later
# scripts legitimately land 40+ minutes in (MAA then MaaEnd), so testing every
# record against this window would call every healthy morning "manual".
MANUAL_WINDOW_MIN = 30


def _entry_time(e: dict, key: str = "started") -> datetime:
    """A ledger entry's `key` timestamp on the relay's clock."""
    return datetime.fromisoformat(e[key]).astimezone(SERVER_TZ)


def _boot_time(eng, now: datetime | None = None) -> datetime | None:
    """When this machine last booted, or None when it cannot be told.

    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:_boot_time」。
    """
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    try:
        import ctypes  # noqa: PLC0415 - Windows only, imported where used
        # The return value is 64-bit; without a declared restype ctypes truncates it
        # to a 32-bit int, and any uptime past 24.8 days turns negative.
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        ms = ctypes.windll.kernel32.GetTickCount64()
    except (AttributeError, OSError):
        return None
    if not ms or ms < 0:
        return None
    return now - timedelta(milliseconds=int(ms))


def _recent_entries(eng, now: datetime) -> list[dict]:
    """Today's ledger plus yesterday's, for queue-completion checks.

    The ledger is keyed by each run's *start* date, so an evening queue
    checked just after midnight has its records in yesterday's file; a
    today-only read makes a finished queue look like it never ran.
    """
    return (eng.state.read_ledger(now.strftime("%Y-%m-%d"))
            + eng.state.read_ledger((now - timedelta(days=1)).strftime("%Y-%m-%d")))


def _missing_kinds(eng, q: dict, entries: list[dict]) -> list[str]:
    """The scripts of queue `q` not recorded since its own time."""
    from ark_relay.features import handle as missed  # noqa: PLC0415
    if missed._sat_out(eng, q["due"].astimezone(SERVER_TZ).strftime("%Y-%m-%d"), q["name"]):
        return []
    # Only runs started at or after this queue's own time count -
    # otherwise the morning's MaaEnd would satisfy the evening queue.
    ran = {e["script"] for e in entries if _entry_time(e) >= q["due"] - timedelta(minutes=5)}
    # MAA the stage gate pulled from this run is not waited for (stagegate.py).
    return [k for k in q["kinds"] if k not in ran
            and not (k == "MAA" and stagegate.excused(eng.cfg.state_dir, q["name"], q["due"]))]


def _missing_scripts(eng, queues: list[dict], entries: list[dict]) -> list[str]:
    """For each queue, the scripts it has not recorded since its own time (one line per queue)."""
    return [f"队列「{q['name']}」还差 {'、'.join(missing)}"
            for q in queues if (missing := _missing_kinds(eng, q, entries))]


def _unfinished_queues(eng, now: datetime, entries: list[dict]) -> list[str]:
    """Queues that came due recently and are still missing one of their scripts.

    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:_unfinished_queues」。
    """
    return _missing_scripts(eng, plan.recent_due_queues(eng.cfg.automas_dir, now), entries)


# How far ahead a scheduled queue still counts as the one this boot was woken for
# (the machine wakes 15 minutes before the morning shift, 10 before the evening one).
SHIFT_AHEAD_MIN = 60


def _shift_queues(eng, now: datetime, booted: datetime) -> list[dict]:
    """The AUTO-MAS queues (morning / evening shift) that came due while this boot was up.

    No two-hour cut-off as in recent_due_queues' default: an OK-WW shift can run for two
    hours, and its end would fall out of the window it began in. A shift the stage gate
    emptied (stagegate.recent_pulled) is a shift too.
    """
    window = int((now - booted).total_seconds() // 60) + 1
    found = (plan.recent_due_queues(eng.cfg.automas_dir, now, window_minutes=window)
             + stagegate.recent_pulled(eng.cfg.state_dir, now, window_min=window))
    return [q for q in found if q["due"] >= booted]


BOOT_UNKNOWN = "看不出这次是什么时候开的机"
LANDING_UNSEEN = "这趟跑完以后中继重启过，重启前后都没看到这趟跑完"
# Stay-on reasons that are the relay losing track, not a state: _maybe_shutdown logs them as WARNING.
RELAY_LOST_TRACK = (BOOT_UNKNOWN, LANDING_UNSEEN)


def _current_shift(shift: list[dict]) -> list[dict]:
    """The newest shift among the queues due on this boot: the latest-due queue and those due
    within RETRY_LINK_H before the one after them. A boot the power-off skipped (debug mode,
    「下次跑完不关机」) can hold the morning shift and the evening one; until 11-08 a script
    the morning shift never recorded (one the evening queue does not run, so no later record
    stands in for it) kept every decision of the evening at 「还差」 and the machine on for
    good (audit 11-08 A-16). The morning's own alarms are not this function's: it is used
    for the power-off and the after-shift check only (_shift_overdue still sees every queue).
    """
    out = sorted(shift, key=lambda q: q["due"], reverse=True)
    for i in range(1, len(out)):
        if out[i - 1]["due"] - out[i]["due"] > timedelta(hours=RETRY_LINK_H):
            return out[:i]
    return out


def _not_shift(eng, now: datetime, entries: list[dict], booted, shift: list[dict]) -> "tuple[str, str] | None":
    """Why this decision is not the one right after a morning / evening shift finished:
    (code, why), or None when it is (or the shift is still running). Code 「shift-held」:
    the shift finished but a hold took its moment (_forfeited); decide reads it as not-shift.

    The user's rule (quoted in USER-SWITCHES.txt at shutdown.py:_say_if_moment_passed):
    only a shift from the AUTO-MAS schedule, run on this boot, whose records this
    relay saw land, may end in a power-off. Everything else - a boot by hand, a make-up or a
    run started by hand, a relay restarted after the shift - leaves the machine on. So does
    a shift whose power-off a make-up or client update held past its end (_forfeited): the
    opportunity is the moment the shift finished, not the rest of the boot.
    """
    if booted is None:
        return "not-shift", BOOT_UNKNOWN
    shift = _current_shift(shift)
    if not shift:
        ahead = plan.recent_due_queues(eng.cfg.automas_dir, now + timedelta(minutes=SHIFT_AHEAD_MIN),
                                       window_minutes=SHIFT_AHEAD_MIN)
        if soon := [q for q in ahead if q["due"] > now]:
            return "shift-ahead", f"排期 {min(q['due'] for q in soon):%H:%M} 那趟还没开始"
        return "not-shift", f"这次是 {booted.astimezone(SERVER_TZ):%m-%d %H:%M} 开的机，之后没有到点的排期"
    if missing := _missing_scripts(eng, shift, entries):
        # Still running, or failed: nothing to judge before every script of the shift
        # has recorded.
        return "shift-running", "；".join(missing)
    if held := _forfeited(eng, shift):
        # The shift did finish (shiftcheck still counts it); only its power-off is gone.
        return "shift-held", held
    if not _seen_landing(eng, booted, shift):
        return "not-shift", LANDING_UNSEEN
    if eng._last_round_manual(now, entries):
        return "not-shift", "最近一轮是手动触发的"
    return None


BOOT_SLACK_S = 120   # the boot time is now - uptime, so two reads of one boot differ by seconds


HELD_PAST_SHIFT = ("makeup", "updating")
# Verdicts reached only after _not_shift passed (the shift finished) that can sit in front
# of 「updating」 in decide's chain: the update thread running behind one of them still
# holds the power-off past the shift.
AFTER_SHIFT = ("uptime", "running", "farming", "pending", "report")
UPDATE_HOLD = "游戏客户端正在更新或重跑"


# A failed run nobody here can fix: the game's servers down (maintenance / maaend_unreachable /
# okww_unreachable), MAA short on sanity (maa_sanity_short, ledger.episode_kinds "nosanity"),
# a MaaEnd update restart after the round was already done, or the user's own stop (manual_stop).
UNFIXABLE = ("maintenance", "maaend_unreachable", "okww_unreachable", "maa_sanity_short",
             "maaend_update_after_done", "manual_stop")


def _incomplete_unfixed(e: dict) -> str:
    """Remaining undone summary of an ok=True record after dropping gathering-only items
    (which collect_retry re-runs at the power-off moment); '' when nothing else is undone."""
    why = str(e.get("incomplete") or "").strip()
    if not why:
        return ""
    if e.get("script") == "MaaEnd":
        from ark_relay.core.ledger import strip_incomplete_items  # noqa: PLC0415
        from ark_relay.features.collect_retry import GATHERING_UNDONE  # noqa: PLC0415
        why = strip_incomplete_items(why, GATHERING_UNDONE).strip()
    return why


def _shift_unfixed(shift: list[dict], entries: list[dict], off: "set[int] | frozenset" = frozenset()) -> list[str]:
    """「明日方舟（开始唤醒）」 for each (script, user, mode) of the current shift (_current_shift)
    whose latest record since the shift's time failed or ended incomplete, unless that failure is
    UNFIXABLE or gathering only. A later clean record (an AUTO-MAS retry, the make-up, a run by
    hand) fixes it. manual_stop records neither fix nor fail (ledger.manual_stop) and are skipped
    so they never mask an earlier real failure. Off-shift (`off`: test or hand-started) runs that
    failed or ended incomplete do not count against the shift; a clean off-shift run fixes it.
    Transitional records are superseded by any non-transitional record of the same key, while a
    shift whose only record for a key is a failed transitional one (e.g. a MaaEnd update restart
    with RunTimesLimit=1) still holds."""
    from ark_relay.core import ledger as core  # noqa: PLC0415
    from ark_relay.features.handle import GAME  # noqa: PLC0415 - handle imports this module
    from ark_relay.features.collector_maaend import _strip_emoji  # noqa: PLC0415
    from ark_relay.features.makeup import GATHERING  # noqa: PLC0415
    cur = _current_shift(shift)
    if not cur:
        return []
    since = min(q["due"] for q in cur) - timedelta(minutes=5)
    kinds = {k for q in cur for k in q.get("kinds", [])}
    latest_final: dict = {}
    latest_trans: dict = {}
    for e in entries:
        try:
            if e.get("script") not in kinds or _entry_time(e) < since or core.manual_stop(e):
                continue
            clean_ok = bool(e.get("ok")) and not _incomplete_unfixed(e)
            if id(e) in off and not clean_ok:
                continue
            key = (e["script"], str(e.get("user") or ""), core.maa_mode(e))
            bucket = latest_trans if e.get("transitional") else latest_final
            if key not in bucket or _entry_time(e) >= _entry_time(bucket[key]):
                bucket[key] = e
        except (KeyError, TypeError, ValueError):
            continue
    latest = {**latest_trans, **latest_final}
    out = []
    for (script, _user, mode), e in sorted(latest.items()):
        raw = e.get("raw") or {}
        label = ({"OK-WW": "鸣潮", **GAME}).get(script, script) + ("剿灭" if mode == "剿灭" else "")
        if e.get("ok"):
            if undone := _incomplete_unfixed(e):
                out.append(f"{label}（{core._incomplete_note(undone)}）")
            continue
        if any(raw.get(k) for k in UNFIXABLE):
            continue
        if raw.get("automas_config_skip") and any(
                s2 == script and m2 == mode and _entry_time(e2) >= _entry_time(e)
                and bool(e2.get("ok")) and not _incomplete_unfixed(e2)
                for (s2, _u2, m2), e2 in latest_final.items()):
            continue
        failed = [str(t) for t in e.get("failed_tasks") or []]
        if failed and all(_strip_emoji(t) == GATHERING for t in failed):
            continue
        what = "、".join(failed[:3]) + ("…" if len(failed) > 3 else "")
        out.append(f"{label}（{what or '没说是哪一项'}）")
    return out


def _newest_shift(shift: list[dict]) -> "dict | None":
    return max(shift, key=lambda q: q["due"]) if shift else None


def _shift_tag(q: dict) -> str:
    """One shift run: its queue and due time (a later shift on the same boot is another)."""
    return f"{q.get('name')}|{q['due'].astimezone(SERVER_TZ).isoformat()}"


def _forfeited(eng, shift: list[dict]) -> str:
    """Why the newest shift of this boot lost its power-off (_note_forfeit), or ''."""
    q = _newest_shift(shift)
    try:
        got = eng.state.store.get("marks", "shutdown_forfeit")
    except Exception:  # noqa: BLE001 - an unreadable mark reads as none
        return ""
    if q is None or not isinstance(got, dict) or got.get("shift") != _shift_tag(q):
        return ""
    return str(got.get("why") or "")


def _held_past_shift(eng, v: "Verdict") -> str:
    """What holds the power-off past the moment the shift finished, '' when nothing does."""
    if v.code in HELD_PAST_SHIFT:
        return v.reason
    if v.code in AFTER_SHIFT:
        try:
            if eng._deferred_update_busy():
                return UPDATE_HOLD
        except Exception:  # noqa: BLE001 - the verdict's own gate decides then
            return ""
    return ""


def _note_forfeit(eng, now: datetime, hold: str) -> None:
    """The newest shift of this boot is past its moment: keep that in state.json marks, so
    a later decision - in this process or a relay restarted on the same boot - refuses
    instead of powering off once the hold lets go."""
    booted = eng._boot_time(now)
    q = _newest_shift(_shift_queues(eng, now, booted)) if booted is not None else None
    if q is None:
        return
    tag = _shift_tag(q)
    try:
        got = eng.state.store.get("marks", "shutdown_forfeit")
        if isinstance(got, dict) and got.get("shift") == tag:
            return
        done = _shift_finished(eng, now, q)
        why = (f"{q.get('name')} {q['due'].astimezone(SERVER_TZ):%H:%M} 那趟"
               + (f" {done:%H:%M} 跑完" if done else "跑完")
               + f"后，{now:%H:%M} 起关机被拖住（{hold}），已经不是刚跑完；下一趟早班/晚班跑完照常关机")
        eng.state.store.set("marks", "shutdown_forfeit", {"shift": tag, "why": why, "at": now.isoformat()})
    except Exception:  # the process keeps judging; a restart would forget it
        log.warning("「这一班的关机机会已过」没记到磁盘，等住的事放手后可能照样关机", exc_info=True)
        return
    log.info("这一班的关机机会已过：%s", why)


def _shift_finished(eng, now: datetime, q: dict) -> "datetime | None":
    """When shift run `q` finished: the latest end among its scripts' records since its time."""
    since = q["due"] - timedelta(minutes=5)
    ends = []
    for e in eng._recent_entries(now):
        try:
            if e.get("script") in q.get("kinds", []) and _entry_time(e) >= since:
                ends.append(_entry_time(e, "finished") if e.get("finished") else _entry_time(e))
        except (KeyError, TypeError, ValueError):
            continue
    return max(ends) if ends else None


def _poweroff_why(eng, now: datetime) -> dict:
    """Why the relay powers off now, for state.json and the last heartbeat: which shift,
    when it finished. {"why", "shift", "due", "finished"}."""
    booted = eng._boot_time(now)
    q = _newest_shift(_shift_queues(eng, now, booted)) if booted is not None else None
    if q is None:
        return {"why": f"中继 {now:%H:%M} 判定本轮已处理完毕，发出关机"}
    due = q["due"].astimezone(SERVER_TZ)
    done = _shift_finished(eng, now, q)
    return {"why": f"{q.get('name')}（排期 {due:%H:%M}）"
                   + (f"{done:%H:%M} 跑完，" if done else "跑完，") + f"中继 {now:%H:%M} 发出关机",
            "shift": q.get("name"), "due": due.isoformat(),
            "finished": done.isoformat() if done else None}


def note_handled(eng, now: datetime) -> None:
    """Records landed on this boot: keep {boot, at} in state.json marks, so a relay restarted
    on the same boot still counts the shift as seen landing (_seen_landing)."""
    booted = eng._boot_time(now)
    if booted is None:
        return
    try:
        eng.state.store.set("marks", "handled_boot", {"boot": booted.isoformat(), "at": now.isoformat()})
    except Exception:  # the in-memory flag still holds for this process
        log.warning("「这次开机看到过记录落账」没记到磁盘，中继重启后会当作没看到", exc_info=True)


def _seen_landing(eng, booted: datetime, shift: list[dict]) -> bool:
    """This process saw records land, or one before it did on this same boot after the shift came due."""
    if eng._handled_any:
        return True
    got = eng.state.store.get("marks", "handled_boot")
    if not isinstance(got, dict) or not shift:
        return False
    try:
        boot, at = datetime.fromisoformat(got["boot"]), datetime.fromisoformat(got["at"])
    except (KeyError, TypeError, ValueError):
        return False
    return abs((boot - booted).total_seconds()) <= BOOT_SLACK_S and at >= max(q["due"] for q in shift)


def _schedule_times(eng) -> list[tuple[dict, str]]:
    """(queue, "HH:MM") for every scheduled queue time in AUTO-MAS's own queue config;
    _near_due asks plan.runs_at whether that time runs anything on the day."""
    return [(q, t) for q in plan.schedule(eng.cfg.automas_dir) for t in q.get("times", [])]


def _near_due(first: datetime, times: list[tuple[dict, str]]) -> bool:
    """`first` is within MANUAL_WINDOW_MIN of a scheduled time that runs something that
    day. A time off that weekday, or whose items all sit the day out (the relay's own
    one-day skip), is no shift: a hand start next to it stays a hand start (audit,
    10-13: raw queue times read without the weekday rule)."""
    for q, hhmm in times:
        try:
            hh, mm = (int(x) for x in hhmm.split(":"))
        except ValueError:
            continue
        due = first.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if abs((first - due).total_seconds()) <= MANUAL_WINDOW_MIN * 60 and plan.runs_at(q, hhmm, due):
            return True
    return False


def _round_is_manual(eng, new_entries: list[dict]) -> bool:
    """Whether this round was triggered by hand rather than by the schedule.

    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:_round_is_manual」。
    """
    times = _schedule_times(eng)
    if not times or not new_entries:
        return False
    try:
        first = min(_entry_time(e) for e in new_entries)
    except (KeyError, ValueError):
        return False
    return not _near_due(first, times)


# How far apart two consecutive records may be and still belong to one round:
# a full queue is MAA then MaaEnd then OK-WW back to back, a hand-started run
# comes hours after the morning one.
ROUND_GAP_H = 2
# AUTO-MAS retries a failed script inside the same queue run, but only after
# its own timeout has expired on the failed attempt, which can be hours later.
# Such a retry belongs to the round of the attempt it repeats; the bound only
# keeps a hand-run repeat the next afternoon from being chained back.
RETRY_LINK_H = 4
TIMEOUT_LIMIT_MIN = {"OK-WW": 120, "MaaEnd": 40, "MAA": 45}
TIMEOUT_SLACK_MIN = 10
# A single script the relay itself dispatched (commands.run_script: the make-up,
# the re-run after a client update) notes 「脚本 <name>」 in relay-dispatches.json.
# Its first record's start is the script's first log line, which comes after the
# game or emulator is up: allowed this long after the note (and makeup.SLACK
# before it, two clocks on one machine).
RELAY_RUN_START_MIN = 15
RELAY_RUN_EARLY = timedelta(minutes=2)
# The power-off is `shutdown /s /t 60` (Engine._power_off); Windows stops the relay
# within a minute or two after the countdown. A relay still deciding this long after
# issuing it is on a machine that did not go down.
ISSUED_STUCK_MIN = 10

# 1074: "The process <param1> has initiated the power off of computer ... on behalf of
# user <param7>"; 1075: that power-off was aborted (User32, the System log).
_EVT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"


def shutdown_event_xml(window_s: int, ids: "tuple[int, ...]" = (1074, 1075)) -> "list[str] | None":
    """The System log's events `ids` (1074 / 1075 unless asked) of the last `window_s`
    seconds, newest first, as event XML (Windows Event Log API, EvtQuery + EvtRender);
    None when it cannot be read."""
    try:
        import win32evtlog  # noqa: PLC0415
        which = " or ".join(f"EventID={int(i)}" for i in ids)
        q = win32evtlog.EvtQuery(
            "System", win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection,
            f"*[System[({which}) and TimeCreated[timediff(@SystemTime) <= {int(window_s * 1000)}]]]")
        out = []
        while True:
            got = win32evtlog.EvtNext(q, 10)
            if not got:
                break
            out += [win32evtlog.EvtRender(e, win32evtlog.EvtRenderEventXml) for e in got]
    except Exception as exc:  # noqa: BLE001 - unknown, not "no event"; the caller says so
        tape.syslog(ids, window_s, None, error=exc)
        return None
    tape.syslog(ids, window_s, out)
    return out


def _stamp(ev) -> "datetime | None":
    from datetime import timezone  # noqa: PLC0415
    t = ev.find(f"{_EVT_NS}System/{_EVT_NS}TimeCreated")
    raw = (t.get("SystemTime") or "") if t is not None else ""
    try:
        return datetime.fromisoformat(raw.rstrip("Z").split(".")[0]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _events(xmls: "list[str]") -> list:
    import xml.etree.ElementTree as ET  # noqa: PLC0415
    out = []
    for x in xmls:
        try:
            ev = ET.fromstring(x)
        except ET.ParseError:
            continue
        eid = (ev.findtext(f"{_EVT_NS}System/{_EVT_NS}EventID") or "").strip()
        data = {d.get("Name") or str(k): (d.text or "").strip()
                for k, d in enumerate(ev.iter(f"{_EVT_NS}Data"))}
        out.append((eid, _stamp(ev), data))
    return out


def cancel_event(xmls: "list[str]") -> "tuple[datetime | None, str] | None":
    """From System log XML, newest first: (UTC time, account) of a 1075 newer than every
    1074 - the power-off was aborted and nothing asked again - else None. Time None when
    its stamp does not parse; account "" when absent.

    A 1075 holds param1 = computer, param2 = account (read on the machine: `INS` /
    `INS\\Administrator`). A remote `shutdown /a` run as that account is logged the
    same way as a person at the machine."""
    for eid, when, data in _events(xmls):
        if eid == "1074":
            return None
        if eid == "1075":
            return when, data.get("param2") or data.get("1") or ""
    return None


def cancelled_at(xmls: "list[str]") -> "str | None":
    """cancel_event's time as relay-clock HH:MM:SS ("时刻读不出" on a bad stamp), else None."""
    got = cancel_event(xmls)
    if got is None:
        return None
    return got[0].astimezone(SERVER_TZ).strftime("%H:%M:%S") if got[0] else "时刻读不出"


def _round_of_newest(entries: list[dict]) -> list[dict]:
    """The records that make up the round the newest record belongs to.

    Walk back from the newest record: the previous one is part of the same
    round when this one starts within ROUND_GAP_H of its end, or when this one
    is a retry of it (same script and user, the previous one failed, within
    RETRY_LINK_H), or when the previous one timed out and this one starts
    before AUTO-MAS's limit for it could have run out.
    """
    ordered = sorted(entries, key=_entry_time)
    group = [ordered[-1]]
    for prev in reversed(ordered[:-1]):
        if _linked(prev, group[0]):
            group.insert(0, prev)
        else:
            break
    return group


def _linked(prev: dict, cur: dict) -> bool:
    """`cur` continues the round `prev` is part of (the rules of _round_of_newest)."""
    cur_start = _entry_time(cur)
    prev_end = _entry_time(prev, "finished") if prev.get("finished") else _entry_time(prev)
    gap = cur_start - prev_end
    same_script = (prev.get("script") == cur.get("script")
                   and prev.get("user") == cur.get("user"))
    retry = same_script and not prev.get("ok") and gap <= timedelta(hours=RETRY_LINK_H)
    # A timed-out record's "finished" can be its log's last line, not the
    # moment AUTO-MAS killed it, so the gap after it can look longer than
    # ROUND_GAP_H. What starts before AUTO-MAS's own limit for that script
    # could have run out (+ TIMEOUT_SLACK_MIN) is the same round; anything
    # later (a hand-started re-run) is not.
    timed_out = not prev.get("ok") and any(
        "超时" in str(w) for w in list(prev.get("failed_tasks") or [])
        + [str((prev.get("raw") or {}).get("general_result") or "")])
    moved_on = False
    if timed_out and (limit := TIMEOUT_LIMIT_MIN.get(str(prev.get("script")))):
        # OK-WW's and MAA's limits run from the start; MaaEnd's from its last
        # log line.
        anchor = prev_end if prev.get("script") == "MaaEnd" else _entry_time(prev)
        moved_on = cur_start <= anchor + timedelta(minutes=limit + TIMEOUT_SLACK_MIN)
    return gap <= timedelta(hours=ROUND_GAP_H) or retry or moved_on


OPEN_WINDOW_MAX_H = 3     # ledger_report.OPEN_TEST_WINDOW_MAX_H reads open windows the same way


def _test_spans(eng) -> list[tuple[datetime, datetime]]:
    """The test windows run-one.sh marked (report.test_windows) as (since, until);
    an open one ends OPEN_WINDOW_MAX_H after it opened. [] when none or no state dir."""
    from ark_relay.features import report  # noqa: PLC0415 - avoids an import cycle
    spans = []
    for w in report.test_windows(getattr(getattr(eng, "cfg", None), "state_dir", None)):
        try:
            since = datetime.fromisoformat(w["since"]).astimezone(SERVER_TZ)
            until = (datetime.fromisoformat(w["until"]).astimezone(SERVER_TZ) if w.get("until")
                     else since + timedelta(hours=OPEN_WINDOW_MAX_H))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        spans.append((since, until))
    return spans


def _off_shift(eng, entries: list[dict]) -> set[int]:
    """id() of every record in `entries` that is no part of a 早班/晚班.

Off-shift is a run a person started at AUTO-MAS (raw.hand_started, written by
    handle._book), or one inside a marked test window that is not a scheduled run.
    A window can never swallow a shift: an in-window record still belongs to a
    shift when it starts within MANUAL_WINDOW_MIN of a scheduled time, or continues
    (_linked) the shift record before it with no window opened in between -
    run-one.sh's busy gate dispatches a test only on an idle queue, so a window
    opened after the previous record ended marks the next start as the test's.
    """
    spans = _test_spans(eng)
    times = _schedule_times(eng) if spans else []
    try:
        ordered = sorted(entries, key=_entry_time)
    except (KeyError, ValueError, TypeError):
        return {id(e) for e in entries if (e.get("raw") or {}).get("hand_started")}
    off: set[int] = set()
    prev = None
    for e in ordered:
        if (e.get("raw") or {}).get("hand_started"):
            off.add(id(e))
            continue
        start = _entry_time(e)
        if any(since <= start <= until for since, until in spans):
            shift = _near_due(start, times)
            if not shift and prev is not None and _linked(prev, e):
                prev_end = _entry_time(prev, "finished") if prev.get("finished") else _entry_time(prev)
                shift = not any(prev_end <= since <= start for since, _ in spans)
            if not shift:
                off.add(id(e))
                continue
        prev = e
    return off


def _last_round_manual(eng, now: datetime, entries: list[dict]) -> bool:
    """True when the day's most recent round was triggered by hand.

    The newest record being hand-started or a test run (_off_shift) makes it manual;
    otherwise the round is built from the scheduled records only.
    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:_last_round_manual」。
    """
    if not entries:
        return False
    try:
        newest_entry = max(entries, key=_entry_time)
    except (KeyError, ValueError):
        return False
    newest = _entry_time(newest_entry)
    off = _off_shift(eng, entries)
    if id(newest_entry) in off:
        return True
    # A catch-up run the relay itself dispatched after a client update is not a
    # hand-started run. It does not end in a power-off either: the update held the
    # shift past its end, and _forfeited refuses that shift before this is asked.
    since = getattr(eng, "_gu_rerun_at", None)
    if since is not None and newest >= since:
        return False
    try:
        group = _round_of_newest([e for e in entries if id(e) not in off])
    except (KeyError, ValueError, TypeError):
        return False
    if _relay_dispatched(eng, group):
        return False
    return eng._round_is_manual(group)


def _relay_dispatched(eng, group: list[dict]) -> bool:
    """The round opens with a script the relay dispatched itself (run_script's note).

    The make-up (makeup.py) waits for an idle queue and can start hours after
    it, beyond what _round_of_newest chains to the scheduled round; read by the
    schedule alone it would be a hand-started round. A queue started from the
    phone (「队列 …」) is not matched here. Not a hand start does not mean a power-off:
    the make-up held its shift past the end, and _forfeited refuses that shift."""
    from ark_relay.features import trigger  # noqa: PLC0415
    try:
        first = min(group, key=lambda e: datetime.fromisoformat(e["started"]))
        start = datetime.fromisoformat(first["started"]).astimezone(SERVER_TZ)
    except (KeyError, ValueError, TypeError):
        return False
    want = f"脚本 {first.get('script')}"
    for d in trigger._read_dispatches(getattr(getattr(eng, "cfg", None), "state_dir", None)):
        if str(d.get("what") or "") != want:
            continue
        try:
            at = datetime.fromisoformat(str(d.get("at")))
        except ValueError:
            continue
        at = (at if at.tzinfo else at.replace(tzinfo=SERVER_TZ)).astimezone(SERVER_TZ)
        if at - RELAY_RUN_EARLY <= start <= at + timedelta(minutes=RELAY_RUN_START_MIN):
            return True
    return False


# ---------- power off, once everything has actually been delivered ----------

def _shutdown_key(eng, now: datetime) -> str:
    """Identifier for this one "time to power off" opportunity.

    It is the day and count of the ledger entries that belong to the latest 早班/晚班
    (not _off_shift): the count grows every time a scheduled queue's script records, so
    "the one after the evening shift" and "the one after the morning shift" are two
    different opportunities, while a hand-started or test run in between leaves the
    key - and a skip recorded on it - as it was. When today has no shift records yet
    (e.g. at the 00:00 midnight wake after yesterday's evening shift), the key stays on
    yesterday's shift count so a skipped evening shift does not power off at midnight.
    """
    day = now.strftime("%Y-%m-%d")
    yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    today = eng.state.read_ledger(day)
    yesterday = eng.state.read_ledger(yday)
    off = _off_shift(eng, today + yesterday)
    today_n = sum(1 for e in today if id(e) not in off)
    if today_n or not yesterday:
        return f"{day}:{today_n}"
    yday_n = sum(1 for e in yesterday if id(e) not in off)
    return f"{yday}:{yday_n}" if yday_n else f"{day}:0"


@dataclass(frozen=True)
class Verdict:
    """Power off or not, why, and which gate. `code` drives the caller's side effects
    and de-duplication; `reason` is what a human reads.
    """

    go: bool
    code: str
    reason: str
    say: str = ""      # the one line pushed to the group (「cancelled」 / 「not-down」 only)


def _cancel_verdict(at: datetime, when) -> Verdict:
    """An aborted power-off (a 1075 after the command): 「cancelled」, whoever aborted it.

    The relay does not look at console input and does not name who aborted it."""
    clock = when.astimezone(SERVER_TZ).strftime("%H:%M:%S") if when else "时刻读不出"
    say = f"关机被取消（{when.astimezone(SERVER_TZ):%H:%M}）" if when else f"关机被取消（关机命令 {at:%H:%M} 发出后）"
    return Verdict(False, "cancelled", f"关机命令 {at:%H:%M} 发出后，{clock} 被取消了（系统事件 1075），中继不会再自己关机", say)


def _boot_imminent(eng, now: datetime) -> str:
    """Return a wait reason when `now` is inside [boot-2m, due) for an imminent scheduled shift."""
    cur = now.astimezone(SERVER_TZ)
    cands: list[datetime] = []
    for day in (-1, 0, 1):
        for hhmm in modes.BOOT_TIMES:
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            cands.append((cur + timedelta(days=day)).replace(
                hour=hh, minute=mm, second=0, microsecond=0))
    if not cands:
        return ""
    for q in plan.recent_due_queues(eng.cfg.automas_dir, cur + timedelta(minutes=62), window_minutes=62):
        due = q["due"].astimezone(SERVER_TZ)
        if due <= cur:
            continue
        for boot in cands:
            if boot - timedelta(minutes=2) <= cur < due and boot <= due <= boot + timedelta(minutes=60):
                return f"距下次定时开机（{boot:%H:%M}）与排期（{due:%H:%M}）太近，先不关机"
    return ""


def _locked_verdict(eng, now: datetime) -> Verdict:
    """decide() while hard-locked (hardlock.py): no shift runs, so a scheduled boot has
    nothing to wait for and powers off once nothing runs and debug mode / the alarm hold
    (both over ten minutes before the next scheduled power-on) are not holding. A boot
    by hand stays on, as it does unlocked."""
    from ark_relay.features import hardlock  # noqa: PLC0415
    booted = eng._boot_time(now)
    if booted is None:
        return Verdict(False, "hardlock-hold", "硬锁中；" + BOOT_UNKNOWN)
    if not hardlock.scheduled_boot(booted):
        return Verdict(False, "hardlock-hold",
                       f"硬锁中；这次是 {booted.astimezone(SERVER_TZ):%m-%d %H:%M} 手动开的机，不关")
    if (now - eng._started_at).total_seconds() < eng.cfg.shutdown_min_uptime:
        return Verdict(False, "uptime", "开机不够久")
    if eng._scripts_running():
        return Verdict(False, "running", "还有脚本或游戏在跑")
    if hardlock.before_power_cut(now):
        return Verdict(True, hardlock.GO_CUT,
                       f"硬锁中：离 {hardlock.POWER_CUT} 插座断电不到 {hardlock.CUT_LEAD_MIN} 分钟，"
                       "调试模式和故障留机锁都不再留机，按设计关机")
    if modes.debug_active(eng.state.dir, now):
        return Verdict(False, "hardlock-hold",
                       f"硬锁中；调试模式开着（到 {modes.debug_until(eng.state.dir)}），到点就按设计关机")
    if hold := modes.alarm_hold_info(eng.state.dir, now):
        return Verdict(False, "hardlock-hold",
                       f"硬锁中；故障留机锁开着（留机至 {hold.get('until') or '?'}），到点就按设计关机")
    return Verdict(True, "go", "硬锁中：定时开机这一轮不跑班，没东西在跑，按设计关机")


def decide(eng, now: datetime) -> Verdict:
    """Pure decision: reads state, writes nothing.

    来龙去脉见 docs/CODE-HISTORY.md「shutdown.py:decide」。
    """
    if not eng.cfg.shutdown_after_run:
        return Verdict(False, "off", "关机功能没开")
    if eng._shutdown_issued:
        # A power-off that did not take: the command went out ISSUED_STUCK_MIN or
        # more ago and this process is still deciding, so the machine is still up.
        at = getattr(eng, "_shutdown_issued_at", None)
        if at is not None and now - at >= timedelta(minutes=ISSUED_STUCK_MIN):
            # Why is it still up? A 1075 after the command means the power-off was aborted
            # (see cancel_event) - not a power-off that failed: 「cancelled」. Both push
            # 「关机被取消」 once (_say_if_moment_passed). Unreadable log: 「not-down」.
            seen = getattr(eng, "_cancel_verdict", None)
            if seen and seen[0] == at:
                return seen[1]            # one reading per power-off: the text stays the same tick to tick
            xmls = shutdown_event_xml(int((now - at).total_seconds()) + 120, (1074, 1075, 566))
            got = cancel_event(xmls) if xmls is not None else None
            if got is not None:
                v = _cancel_verdict(at, got[0])
                eng._cancel_verdict = (at, v)
                return v
            return Verdict(False, "not-down", f"关机命令 {at:%H:%M} 就发出去了，过了 {ISSUED_STUCK_MIN} 分钟机器还开着，"
                                              "没有关下去",
                           f"关机没成功（关机命令 {at:%H:%M} 发出，过了 {ISSUED_STUCK_MIN} 分钟机器还开着）")
        # The relay's own power-off is under way.
        return Verdict(False, "issued", "关机命令已经发出去了，机器正在关")
    from ark_relay.features import hardlock  # noqa: PLC0415
    if hardlock.active(eng.state.dir):
        return _locked_verdict(eng, now)
    entries = eng._recent_entries(now)
    booted = eng._boot_time(now)
    shift = _shift_queues(eng, now, booted) if booted is not None else []
    # _not_shift comes before every other gate: a machine that is not right after a
    # scheduled shift is not powered off, whatever else holds it.
    if no := _not_shift(eng, now, entries, booted, shift):
        code, why = no
        if code in ("shift-ahead", "shift-running"):
            return Verdict(False, code, f"等排期的那趟跑完再判关机（{why}）")
        # 「shift-held」 (_forfeited) is a not-shift to everything downstream.
        return Verdict(False, "not-shift", f"不是早班/晚班跑完，不关机（{why}）")
    if imminent := _boot_imminent(eng, now):
        return Verdict(False, "boot-imminent", imminent)
    # The minimum-uptime floor guards against a "boot, power off at once" loop.
    if (now - eng._started_at).total_seconds() < eng.cfg.shutdown_min_uptime:
        return Verdict(False, "uptime", "开机不够久")
    # A make-up run the relay dispatched itself (makeup.py) gets its own code,
    # not "running".
    from ark_relay.features import makeup  # noqa: PLC0415
    if going := makeup.in_flight(eng.cfg.state_dir, now):
        return Verdict(False, "makeup", f"{'、'.join(going)} 正在补跑")
    if eng._scripts_running():
        return Verdict(False, "running", "还有脚本或游戏在跑")
    # A farm is a promise to keep going until a stated time. 「还有脚本在跑」 covers
    # it only while OK-WW is actually up; when the character dies OK-WW stops and the
    # relay takes up to three minutes to put it back, and a shutdown landing in that
    # window would end the night's farming without a word.
    from ark_relay.features import echofarm  # noqa: PLC0415 - avoids an import cycle
    if rec := echofarm.current(eng.cfg.state_dir):
        return Verdict(False, "farming",
                       f"正在刷{rec.get('name') or '声骸'}，刷到 {rec.get('until')} 才收工")
    # A held MAA / MaaEnd failure whose make-up is still to come is not an alarm
    # waiting to go out (makeup.holding); the make-up gate further down holds it.
    held = [r for r in eng._pending.values() if not makeup.holding(eng, r, now)]
    # A config-check skip whose push failed (runwatch.check_config_skips) is booked on the
    # ledger as the shift's failed run but its alarm is still to go out, like a held failure.
    if held or eng._recovered or getattr(eng, "_unsent_skips", None):
        return Verdict(False, "pending", "还有告警没推出去")
    if eng._deferred_update_busy():
        return Verdict(False, "updating", "游戏客户端正在更新或重跑")
    # After every gate that means "the queue is not idle": by now the make-up step
    # (engine.tick, before this one) can dispatch, and does. Not a stuck code: it
    # clears itself once the make-up's record lands or it goes stale.
    if waiting := makeup.waiting(eng, now):
        return Verdict(False, "makeup", f"{'、'.join(waiting)} 补跑还没完")
    from ark_relay.features import activity  # noqa: PLC0415
    if why := activity.holding(eng, now):
        return Verdict(False, "makeup", why)
    # The user, 2026-11-20 (B 10477): 「早班的游戏任务没跑完，没修好，就不能关机，你们要修好。」
    # That morning the 终末地 shift failed and the machine stayed on only because debug mode
    # happened to be on. Not in HELD_PAST_SHIFT: once a later run of the script goes through,
    # the machine powers off as usual.
    if unfixed := _shift_unfixed(shift, entries, _off_shift(eng, entries)):
        return Verdict(False, "shift-failed", "这一班有游戏任务没跑完、还没修好：" + "；".join(unfixed))
    day = now.strftime("%Y-%m-%d")
    cutoff = eng._report_cutoff(now)   # same source as the report itself
    # An empty ledger means nothing ran today, so there is no daily report to wait
    # for; wait only when something actually ran.
    if (now >= cutoff and not eng.state.report_sent(day)
            and eng.state.read_ledger(day)):
        return Verdict(False, "report", "到点该关机了，但日报还没发出去，继续等")
    # Debug mode holds this shutdown opportunity while active. Once it expires or is
    # turned off, any |debug skip it recorded is released so decide() re-evaluates.
    if modes.debug_active(eng.state.dir):
        return Verdict(False, "debug", "调试模式开着，这一次关机跳过")
    key = eng._shutdown_key(now)
    raw_skip = modes.shutdown_skipped_raw(eng.state.dir)
    if raw_skip == key:
        return Verdict(False, "skipped",
                       "这一次关机已经跳过了（手机上点了「下次跑完不关机」）")
    if hold := modes.alarm_hold_info(eng.state.dir, now):
        why = str(hold.get("reason") or "有未修完的故障报警")
        until = str(hold.get("until") or "")
        tail = f"（留机至 {until}）" if until else ""
        return Verdict(False, "alarm-hold", f"故障留机锁开着，先不关机：{why}{tail}")
    if raw_skip == key + modes.ALARM_SKIP_TAG:
        return Verdict(False, "skipped",
                       "这一次关机已经跳过了（故障留机锁到期时临近下次开机，等下一趟再判）")
    return Verdict(True, "go", "本轮已处理完毕")


# The relay's own power-off, under way: nothing to say.
RELAY_POWER_OFF = "issued"


def _say_if_moment_passed(eng, now: datetime, v) -> None:
    """Push 「关机被取消」 once per power-off when the relay's command went out and the machine
    is still up: aborted (「cancelled」, a 1075) or never went down (「not-down」).

    Every other reason the machine stays on is a state with its own push path, so it
    goes to relay.log only (why each is not a fault: USER-SWITCHES.txt at
    shutdown.py:_say_if_moment_passed); the two that are the relay losing track
    (RELAY_LOST_TRACK) are a WARNING in _maybe_shutdown.
    """
    if not v.say:
        return        # _maybe_shutdown has logged the reason
    at = getattr(eng, "_shutdown_issued_at", None)
    # one fault, one push: one per power-off command
    if getattr(eng, "_cancel_noted", None) == at:
        return
    eng._cancel_noted = at
    log.info("关机被取消，进群：%s（%s）", v.say, v.reason)
    try:
        eng.notifier.send(texts.SHUTDOWN_CANCELLED, v.say, alert=True)
    except Exception:
        log.warning("「关机被取消」这条没推出去", exc_info=True)


def _shift_overdue(eng, now: datetime):
    """(queue, due, missing scripts, limit, deadline, days, turn) for each shift queue of this boot
    that still lacks a record, and whose run check_overrun has not alarmed on. The limit is
    check_overrun's: runwatch.planned_minutes + OVERRUN_SLACK_MIN from the queue's time; the
    deadline waits, as check_overrun does, until the script whose turn it is has spent its
    own planned minutes (runwatch.turn_deadline; `turn` is its answer when it waited, else None)."""
    from ark_relay.features import handle, handle as missed  # noqa: PLC0415
    from ark_relay.features import runwatch  # noqa: PLC0415
    booted = eng._boot_time(now)
    if booted is None:
        return
    entries = eng._recent_entries(now)
    for q in _shift_queues(eng, now, booted):
        due = q["due"].astimezone(SERVER_TZ)
        day, hhmm = due.strftime("%Y-%m-%d"), due.strftime("%H:%M")
        # A script already in the group as missing from this run (missed's key, also settled by
        # runwatch.check_config_skips) is that fault's one push; only the others are overdue.
        # Per script, not per shift: a second script hanging in the same run is still said.
        if not (missing := [k for k in _missing_kinds(eng, q, entries)
                            if not missed._settled(eng, day, f"{day}/{q['name']}/{hhmm}/{k}")]):
            continue
        # one fault, one push: one shift run (queue + its due time) without a record past its end, re-checked every tick
        if (handle._already_alerted(eng, day, f"{OVERDUE_KEY}|{q['name']}|{hhmm}")
                or handle._already_alerted(eng, day, f"队列超时|{q['name']}|{hhmm}")):
            continue
        limit, days = runwatch.planned_minutes(eng, due.hour, due.minute, due)
        start = _overdue_from(eng, due, missing, limit)
        deadline, turn = runwatch.turn_deadline(eng, due, start, start + timedelta(minutes=limit + runwatch.OVERRUN_SLACK_MIN),
                                                list(q.get("kinds") or []), entries)
        yield q, due, missing, limit, deadline, days, turn


def _overdue_from(eng, due: datetime, missing: list[str], limit: int | None = None) -> datetime:
    """When the shift's clock starts for the scripts still missing: the queue's time, or - when the
    client update held all of them out of the queue and the relay re-ran them itself afterwards
    (engine._gu_reran) - the re-run's start. 2026-11-01: 明日方舟 updated, MAA was skipped in the
    09:00 早班 and re-run at 12:02; at 12:04 「⏰ 早班有脚本一直没出结果」 counted 142 + 30 minutes
    from 09:00. Timed from the re-run it still alarms if the re-run itself hangs.
    With `limit` (the shift's planned minutes) a script of the run that timed out and was
    retried by AUTO-MAS restarts the clock too (runwatch.retry_clock, 2026-11-05 ledger #138);
    the later of the two starts wins."""
    from ark_relay.features import runwatch  # noqa: PLC0415
    start = due
    since = getattr(eng, "_gu_rerun_at", None)
    if since is not None and since >= due and set(missing) <= set(getattr(eng, "_gu_reran", ())):
        start = since.astimezone(SERVER_TZ)
    if limit is not None and (retried := runwatch.retry_clock(eng, due, limit)) is not None:
        start = max(start, retried.astimezone(SERVER_TZ))
    return start


OVERDUE_KEY = "班次无结果"


def overdue_moments(eng, now: datetime) -> list[tuple[datetime, str]]:
    """Engine.next_deadline: wake when a shift still lacking a record becomes overdue. Nothing
    else may wake the loop then (no script running, AUTO-MAS not answering), and the backstop
    is an hour."""
    if eng._shutdown_issued:
        return []
    return [(deadline, f"核对「{q['name']}」{due:%H:%M} 那趟有没有跑完")
            for q, due, _, _, deadline, _, _ in _shift_overdue(eng, now) if deadline > now]


def _alarm_shift_overdue(eng, now: datetime) -> None:
    """A shift script still without a record past the shift's planned end: one group alarm
    per shift run (key: the queue and its due time; re-checked every tick).
    """
    from ark_relay.features import errwatch, handle  # noqa: PLC0415
    from ark_relay.features import runwatch  # noqa: PLC0415
    for q, due, missing, limit, deadline, days, turn in list(_shift_overdue(eng, now)):
        if now < deadline:
            continue
        title = texts.shift_no_result(q["name"])
        start = _overdue_from(eng, due, missing, limit)
        body = texts.shift_no_result_body(q["name"], due, now, "、".join(missing),
                                          limit, runwatch.OVERRUN_SLACK_MIN, days,
                                          restarted=start if start != due else None)
        if turn is not None:
            body += "\n" + texts.own_turn_note(turn[0], turn[1], now, turn[2], runwatch.OVERRUN_SLACK_MIN)
        if errs := eng.notifier.send(title, body, alert=True):
            log.error("班次没出结果的告警没推出去，下一轮再试：%s", q["name"])
            continue
        handle._mark_alerted(eng, due.strftime("%Y-%m-%d"), f"{OVERDUE_KEY}|{q['name']}|{due:%H:%M}")
        log.warning("⏰ %s %s 开跑，%s 还没有 %s 的记录（计划 %d 分钟 + %d），已告警",
                    q["name"], f"{due:%H:%M}", now.strftime("%H:%M"), "、".join(missing), limit,
                    runwatch.OVERRUN_SLACK_MIN, extra=errwatch.group_pushed(title, errs, eng.notifier))


def _handle_alarm_hold_side_effects(eng, now: datetime) -> bool:
    """Record |alarm skip without overwriting user/debug skips, retry collect once per key, and send interim."""
    key = eng._shutdown_key(now)
    if modes.shutdown_skipped(eng.state.dir) != key:
        modes.mark_shutdown_skipped(eng.state.dir, key, by_alarm=True)
    if getattr(eng, "_alarm_retry_key", None) != key:
        eng._alarm_retry_key = key
        from ark_relay.features import collect_retry  # noqa: PLC0415
        if collect_retry.maybe_run(eng, now):
            log.info("补跑刚做完，这一轮关机判断从头再来")
            return True
    day = now.strftime("%Y-%m-%d")
    if (eng.cfg.report_before_shutdown and not eng.state.report_sent(day)
            and not eng.state.interim_sent(day) and eng.state.read_ledger(day)):
        log.info("故障留机期间补发一份当前进度")
        if eng.send_daily_now(mark=False):
            eng.state.mark_interim_sent(day, len(eng.state.read_ledger(day)))
    return False


def _issue_poweroff(eng, now: datetime, live_clock: bool, gen0: int, why: dict) -> bool:
    """Issue eng._power_off() with Condition + try/finally anti-deadlock & instant mid-issue abort."""
    with _SHUTDOWN_COND:
        if _ISSUE_STATE["gen"] != gen0:
            log.info("🚨 关机准备期间出现新故障留机：取消本次关机")
            return False
        _ISSUE_STATE.update(
            issuing=True, tid=threading.get_ident(), abort=False, mark_skipped=False, outcome=None,
        )
        _ISSUED[0] = eng
    from ark_relay.features import errwatch  # noqa: PLC0415
    try:
        issue_t0 = datetime.now(tz=SERVER_TZ)
        issued_at = issue_t0 if live_clock else now
        _record_poweroff(eng, issued_at, why)
        ok = eng._power_off()
        issue_t1 = datetime.now(tz=SERVER_TZ)
        if not ok:
            with _SHUTDOWN_COND:
                _ISSUE_STATE.update(outcome=("none", ""), issuing=False, tid=None)
                _ISSUED[0] = None
                _SHUTDOWN_COND.notify_all()
            _record_poweroff(eng, None)
            return False
        with _SHUTDOWN_COND:
            need_abort = _ISSUE_STATE["abort"] or (_ISSUE_STATE["gen"] != gen0)
            want_skip = _ISSUE_STATE["mark_skipped"]
            if not need_abort:
                eng._shutdown_issued = True
                eng._shutdown_issued_at = issued_at
                eng._poweroff_window = (issue_t0, issue_t1)
                _ISSUE_STATE.update(issuing=False, tid=None)
                errwatch.mark_stopping()
                _SHUTDOWN_COND.notify_all()
                issued_done = True
            else:
                issued_done = False
        if issued_done:
            log.info("关机原因：%s", why["why"])
            return True
        rc = eng._abort_power_off()
        if rc in (0, NO_SHUTDOWN_IN_PROGRESS):
            with _SHUTDOWN_COND:
                _record_self_abort((issue_t0, issue_t1))
                _ISSUE_STATE.update(
                    outcome=("aborted", "已取消正在倒计时的关机，这一次不关；下一趟早班/晚班跑完照常关机"),
                    issuing=False, tid=None,
                )
                _ISSUED[0] = None
                errwatch.clear_stopping()
                _SHUTDOWN_COND.notify_all()
            _record_poweroff(eng, None)
            if want_skip:
                modes.mark_shutdown_skipped(eng.state.dir, eng._shutdown_key(issued_at))
            log.info("🚨 关机发出瞬间命中取消或故障留机，已撤回关机倒计时")
            return False
        with _SHUTDOWN_COND:
            _ISSUE_STATE.update(
                outcome=("failed", f"取消关机失败（退出码 {rc}），机器还会关"),
                issuing=False, tid=None,
            )
            eng._shutdown_issued = True
            eng._shutdown_issued_at = issued_at
            eng._poweroff_window = (issue_t0, issue_t1)
            errwatch.mark_stopping()
            _SHUTDOWN_COND.notify_all()
        _ABORT_ERR_TLS.busy = True
        try:
            log.error("关机发出瞬间命中取消或故障留机，但取消关机倒计时失败（退出码 %s），机器还会关", rc)
        finally:
            _ABORT_ERR_TLS.busy = False
        return True
    finally:
        cleanup_needed = False
        with _SHUTDOWN_COND:
            if _ISSUE_STATE["issuing"]:
                _ISSUE_STATE.update(issuing=False, tid=None, outcome=("none", ""))
                _ISSUED[0] = None
                _SHUTDOWN_COND.notify_all()
                cleanup_needed = True
        if cleanup_needed:
            _record_poweroff(eng, None)


# The locked power-off right before the 08:40 mains cut (hardlock.GO_CUT): nothing holds it then.
_CUT = "go-cut"


def _expire_debug_for_shutdown(eng) -> None:
    if expired_until := modes.expire_debug_if_due(eng.state.dir):
        log.info("🔧 调试模式（至 %s）已到期，释放被吞的关机机会并重新判关机", expired_until)


def _maybe_shutdown(eng, now: datetime | None = None) -> bool:
    """Decision plus side effects. decide() judges; this does what follows a "go"."""
    live_clock = now is None
    now = (datetime.now(tz=SERVER_TZ) if live_clock else now).astimezone(SERVER_TZ)
    _expire_debug_for_shutdown(eng)
    v = decide(eng, now)
    if v.code == "debug":
        # Debug mode holds this opportunity while active; tag with |debug so expiry
        # or manual off releases only debug's own skip (never a human mark or |alarm).
        key = eng._shutdown_key(now)
        raw_skip = modes.shutdown_skipped_raw(eng.state.dir)
        if raw_skip not in (key, key + modes.DEBUG_SKIP_TAG):
            modes.mark_shutdown_skipped(eng.state.dir, key, by_debug=True)
            log.info("🔧 调试模式：这一次关机暂缓（%s）；"
                     "到期或关闭后会释放机会重新判关机", key)
    if v.code == "alarm-hold" and _handle_alarm_hold_side_effects(eng, now):
        return False
    if not v.go:
        # "off": a shift that never records is a fault whether or not the relay powers off.
        if v.code in ("shift-running", "off"):
            _alarm_shift_overdue(eng, now)
        # A make-up or client update holding the machine past the shift's end spends
        # that shift's opportunity (HELD_PAST_SHIFT); the next decision says not-shift.
        if hold := _held_past_shift(eng, v):
            _note_forfeit(eng, now, hold)
        # One log line whenever the reason changes, for every reason. Two reasons are
        # the relay failing its own job rather than a state, so they are a WARNING
        # (pushed, once per change): the boot time unreadable (GetTickCount64 failed,
        # _boot_time) and a shift whose records landed while no relay process saw them
        # (_seen_landing) - either way the machine stays on all night after a shift.
        if v.reason != eng._last_wait_note:
            eng._last_wait_note = v.reason
            (log.warning if any(r in v.reason for r in RELAY_LOST_TRACK) else log.info)("不关机：%s", v.reason)
        _say_if_moment_passed(eng, now, v)
        if v.code in ("cancelled", "not-down"):
            _give_up_poweroff(eng, now, v)
        return False
    eng._last_wait_note = ""
    from ark_relay.features import collect_retry  # noqa: PLC0415
    if collect_retry.maybe_run(eng, now):
        log.info("补跑刚做完，这一轮关机判断从头再来")
        return False
    day = now.strftime("%Y-%m-%d")
    if (eng.cfg.report_before_shutdown and not eng.state.report_sent(day)
            and not eng.state.interim_sent(day) and eng.state.read_ledger(day)):
        log.info("关机前补发一份当前进度")
        if eng.send_daily_now(mark=False):
            eng.state.mark_interim_sent(day, len(eng.state.read_ledger(day)))
    if eng._before_shutdown is not None:
        try:
            eng._before_shutdown()
        except Exception:
            log.warning("关机前的待办检查失败", exc_info=True)
        if v.code != _CUT and modes.debug_active(eng.state.dir):
            key = eng._shutdown_key(now)
            raw_skip = modes.shutdown_skipped_raw(eng.state.dir)
            if raw_skip not in (key, key + modes.DEBUG_SKIP_TAG):
                modes.mark_shutdown_skipped(eng.state.dir, key, by_debug=True)
            log.info("🔧 关机前刚收到调试模式：这一次关机跳过（%s）", key)
            return False
        if v.code != _CUT and modes.alarm_hold_info(eng.state.dir, now):
            key = eng._shutdown_key(now)
            if modes.shutdown_skipped(eng.state.dir) != key:
                modes.mark_shutdown_skipped(eng.state.dir, key, by_alarm=True)
            log.info("🚨 关机前刚挂上故障留机锁：先不关机（%s）", key)
            return False
        if eng._scripts_running():
            log.info("关机前刚派了脚本：先不关机，等它跑完再判")
            return False
    with _SHUTDOWN_COND:
        gen0 = _ISSUE_STATE["gen"]
    if v.code != _CUT and modes.alarm_hold_info(eng.state.dir, now):
        log.info("🚨 故障留机锁刚挂上：先不关机")
        return False
    if v.code != _CUT and modes.take_skip(eng.state.dir):
        key = eng._shutdown_key(now)
        modes.mark_shutdown_skipped(eng.state.dir, key)
        log.info("⏸ 「下次跑完不关机」用掉了：这一次关机跳过（%s），"
                 "机器开着，等下一趟早班/晚班跑完照常关机", key)
        return False
    try:
        from ark_relay.features import evidence as error_evidence  # noqa: PLC0415
        _up = error_evidence.upload_daily_logs(eng.cfg, force=True)
    except Exception as _exc:  # noqa: BLE001 - an evidence problem never delays the power-off
        _up = {"errors": [f"upload raised {type(_exc).__name__}: {_exc}"]}
    for _e in (_up or {}).get("errors") or []:
        log.warning("关机前证据上传失败：%s", _e)
    try:
        why = _poweroff_why(eng, now)
    except Exception:  # the reason is for the user to read; the power-off goes on
        log.warning("关机原因没整理出来", exc_info=True)
        why = {"why": f"中继 {now:%H:%M} 判定本轮已处理完毕，发出关机"}
    if v.code != _CUT and modes.alarm_hold_info(eng.state.dir, now):
        log.info("🚨 关机前发现故障留机锁：取消本次关机")
        return False
    return _issue_poweroff(eng, now, live_clock, gen0, why)


def _give_up_poweroff(eng, now: datetime, v: "Verdict") -> None:
    """The power-off was aborted or never took: this shift has lost its power-off.
    Clear the "issued" state so engine.next_deadline, the alarms and the next
    shift's power-off work again (before 11-08 they stayed dead until a restart)."""
    try:
        _note_forfeit(eng, now, v.reason)
    except Exception:  # the reset below matters more than the mark
        log.warning("「这一班不再关机」没记下来", exc_info=True)
    from ark_relay.features import errwatch  # noqa: PLC0415
    with _SHUTDOWN_COND:
        eng._shutdown_issued = False
        eng._shutdown_issued_at = None
        eng._poweroff_window = None
        eng._cancel_verdict = None
        _ISSUED[0] = None
        errwatch.clear_stopping()
    _record_poweroff(eng, None)
    log.info("关机没成：这一班不再关机，定时报警和下一班关机恢复正常")


def _record_poweroff(eng, at: datetime | None, why: "dict | None" = None) -> None:
    """Keep the moment the relay issued its own power-off in state.json (None: the
    countdown was cancelled), and why (`relay_poweroff_why`, _poweroff_why: which
    shift, when it finished) for the last heartbeat (poweroff_note).
    eng._shutdown_issued_at lives in this process only;
    `app_main.py stop-push` runs in the watchdog's process at the same power-off and
    reads this (relay_poweroff_recorded). Never raises: the power-off goes on."""
    try:
        if at is None:
            eng.state.store.pop("marks", "relay_poweroff")
            eng.state.store.pop("marks", "relay_poweroff_why")
        else:
            eng.state.store.set("marks", "relay_poweroff", at.isoformat())
            eng.state.store.set("marks", "relay_poweroff_why", dict(why or {}, at=at.isoformat()))
    except Exception:  # the relay's own probe (boot_stages._relay_poweroff_live) still answers
        log.warning("没能把中继自己发出的关机记进 state.json，看门服务代发时认不出是中继关的机", exc_info=True)


def poweroff_note(state_dir, now: datetime | None = None) -> dict:
    """Who stopped the machine, for the last COS heartbeat (heartbeat.Heartbeat.bye):
    {"by": "relay" | "windows" | "service", "why", "at" (unix seconds)}.

    "relay": the relay issued its own power-off less than ISSUED_STUCK_MIN ago
    (relay_poweroff_recorded), with the reason _record_poweroff kept. "windows":
    Windows is shutting down (SvcShutdown ran, or the session says so) without that
    command - a person, Windows Update or anything else. "service": the relay service
    stopped and the machine is not going down (a deploy, `sc stop`). Never raises."""
    from ark_relay.features import errwatch  # noqa: PLC0415
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    try:
        if relay_poweroff_recorded(state_dir, now):
            from ark_relay.core.statestore import StateStore  # noqa: PLC0415
            store = StateStore(state_dir)
            issued = datetime.fromisoformat(str(store.get("marks", "relay_poweroff")))
            got = store.get("marks", "relay_poweroff_why")
            why = (str(got.get("why") or "") if isinstance(got, dict)
                   and got.get("at") == issued.isoformat() else "")
            return {"by": "relay", "why": why or "中继发出了关机命令（原因没记下）",
                    "at": int(issued.timestamp())}
    except Exception:  # fall through to what Windows says
        log.debug("中继自己的关机记录读不出", exc_info=True)
    if errwatch.os_shutdown() or errwatch.system_shutting_down():
        return {"by": "windows", "why": "Windows 在关机，不是中继发的关机命令（有人关机或系统自己关）",
                "at": int(now.timestamp())}
    return {"by": "service", "why": "中继服务停了，机器没有关", "at": int(now.timestamp())}


def relay_poweroff_recorded(state_dir, now: datetime | None = None) -> bool:
    """boot_stages._relay_poweroff_live for a process without the engine: the relay
    issued its own power-off less than ISSUED_STUCK_MIN ago (state.json, _record_poweroff).
    False when nothing is recorded or the record cannot be read."""
    try:
        from ark_relay.core.statestore import StateStore  # noqa: PLC0415
        at = StateStore(state_dir).get("marks", "relay_poweroff")
        if not at:
            return False
        at = datetime.fromisoformat(str(at))
    except Exception:  # noqa: BLE001 - unreadable answers "not ours", as errwatch.relay_shutdown_issued does
        return False
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    return timedelta(0) <= now - at < timedelta(minutes=ISSUED_STUCK_MIN)


# ---------- 「下次跑完不关机」 pressed while the 60-second countdown is already running ----------
# The engine whose _power_off was accepted, so a phone order (commands.apply_command,
# which has no engine) can cancel a countdown that is already running.
_ISSUED: list = [None]
NO_SHUTDOWN_IN_PROGRESS = 1116     # shutdown /a: ERROR_NO_SHUTDOWN_IN_PROGRESS

_SHUTDOWN_COND = threading.Condition(threading.Lock())
_ISSUE_STATE: dict = {
    "gen": 0,
    "issuing": False,
    "tid": None,
    "abort": False,
    "mark_skipped": False,
    "outcome": None,
}
_RECENT_SELF_ABORTS: list[tuple[datetime, datetime, float]] = []
_ABORT_ERR_TLS = threading.local()
_GUARD_QUEUE: list = [None]


def register_guard_queue(q) -> None:
    with _SHUTDOWN_COND:
        _GUARD_QUEUE[0] = q


def in_abort_error() -> bool:
    return bool(getattr(_ABORT_ERR_TLS, "busy", False))


def _record_self_abort(win: tuple[datetime, datetime] | None) -> None:
    now_m = time.monotonic()
    _RECENT_SELF_ABORTS[:] = [x for x in _RECENT_SELF_ABORTS if x[2] > now_m]
    if win is not None:
        _RECENT_SELF_ABORTS.append((win[0] - timedelta(seconds=2), win[1] + timedelta(seconds=2), now_m + 30.0))


def poweroff_in_progress(event_at: datetime | None = None) -> bool:
    """True when the relay is issuing/holding a power-off, or just self-aborted one covering `event_at`."""
    now_m = time.monotonic()
    with _SHUTDOWN_COND:
        _RECENT_SELF_ABORTS[:] = [x for x in _RECENT_SELF_ABORTS if x[2] > now_m]
        if _ISSUE_STATE["issuing"]:
            return True
        eng = _ISSUED[0]
        if eng is not None and getattr(eng, "_shutdown_issued", False):
            return True
        if _RECENT_SELF_ABORTS:
            if event_at is None:
                return True
            ev = event_at.astimezone(SERVER_TZ)
            for lo, hi, _ in _RECENT_SELF_ABORTS:
                if lo <= ev <= hi:
                    return True
    return False


def on_alarm_hold() -> None:
    """Bump alarm generation and cancel any relay or pending external shutdown countdown."""
    with _SHUTDOWN_COND:
        _ISSUE_STATE["gen"] += 1
        if _ISSUE_STATE["issuing"]:
            _ISSUE_STATE["abort"] = True
            return
        eng = _ISSUED[0]
        issued = eng is not None and getattr(eng, "_shutdown_issued", False)
        guard_q = _GUARD_QUEUE[0]
    if issued and not in_abort_error():
        abort_countdown(mark_skipped=False)
        return
    if guard_q is not None:
        try:
            guard_q.put(("alarm_hold", None))
        except Exception:  # noqa: BLE001 - guard queue put must never raise
            pass


def abort_countdown(now: datetime | None = None, *, mark_skipped: bool = True) -> tuple[str, str]:
    """Cancel the relay's own power-off if its countdown is still running.

    Returns (outcome, text): "aborted" - cancelled; "none" - no countdown of ours is
    running; "failed" - `shutdown /a` was refused, the machine is still going down.
    """
    with _SHUTDOWN_COND:
        if _ISSUE_STATE["issuing"]:
            _ISSUE_STATE["abort"] = True
            _ISSUE_STATE["mark_skipped"] = _ISSUE_STATE["mark_skipped"] or bool(mark_skipped)
            if threading.get_ident() == _ISSUE_STATE["tid"]:
                return "aborted", ""
            while _ISSUE_STATE["issuing"]:
                _SHUTDOWN_COND.wait()
            return _ISSUE_STATE["outcome"] or ("none", "")
        eng = _ISSUED[0]
        if eng is None or not getattr(eng, "_shutdown_issued", False):
            return "none", ""
        issued_at = getattr(eng, "_shutdown_issued_at", None)
        win = getattr(eng, "_poweroff_window", None)
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    rc = eng._abort_power_off()
    # Error branch MUST precede any errwatch.system_shutting_down() check (test_texts MUTE-guard).
    if rc not in (0, NO_SHUTDOWN_IN_PROGRESS):
        _ABORT_ERR_TLS.busy = True
        try:
            if mark_skipped:
                log.error("收到「下次跑完不关机」，取消关机倒计时失败（退出码 %s），机器还会关", rc)
            else:
                log.error("故障留机触发取消关机倒计时失败（退出码 %s），机器还会关", rc)
        finally:
            _ABORT_ERR_TLS.busy = False
        return "failed", f"取消关机失败（退出码 {rc}），机器还会关"
    from ark_relay.features import errwatch  # noqa: PLC0415
    if rc == NO_SHUTDOWN_IN_PROGRESS:
        if not (errwatch.os_shutdown() or errwatch.system_shutting_down()):
            anchor = (win[0] if win else (issued_at or now)).astimezone(SERVER_TZ).replace(microsecond=0)
            real_now = datetime.now(tz=SERVER_TZ)
            window_s = max(120, min(3600, int((real_now - anchor).total_seconds()) + 120))
            xmls = shutdown_event_xml(window_s, (1074, 1075, 566))
            got = cancel_event(xmls) if xmls is not None else None
            if got is not None and got[0] is not None and got[0].astimezone(SERVER_TZ) >= anchor:
                cleared = False
                with _SHUTDOWN_COND:
                    if _ISSUED[0] is eng and getattr(eng, "_shutdown_issued_at", None) == issued_at:
                        eng._shutdown_issued = False
                        eng._shutdown_issued_at = None
                        eng._poweroff_window = None
                        eng._cancel_verdict = None
                        _ISSUED[0] = None
                        errwatch.clear_stopping()
                        cleared = True
                if cleared:
                    _record_poweroff(eng, None)
        if mark_skipped:
            log.info("收到「下次跑完不关机」：系统里已经没有关机倒计时（退出码 1116），照常记下这个标记")
        else:
            log.info("故障留机取消关机：系统里已经没有关机倒计时（退出码 1116）")
        return "none", ""
    cleared = False
    with _SHUTDOWN_COND:
        if _ISSUED[0] is eng and getattr(eng, "_shutdown_issued_at", None) == issued_at:
            _record_self_abort(win)
            eng._shutdown_issued = False
            eng._shutdown_issued_at = None
            eng._poweroff_window = None
            eng._cancel_verdict = None
            _ISSUED[0] = None
            errwatch.clear_stopping()
            cleared = True
    if cleared:
        _record_poweroff(eng, None)
        if mark_skipped:
            key = eng._shutdown_key(issued_at or now)
            modes.mark_shutdown_skipped(eng.state.dir, key)
    if mark_skipped:
        log.info("⏸ 收到「下次跑完不关机」：已取消正在倒计时的关机，这一次不关；下一趟早班/晚班跑完照常关机")
        return "aborted", "已取消正在倒计时的关机，这一次不关；下一趟早班/晚班跑完照常关机"
    log.info("🚨 故障留机触发：已取消正在倒计时的关机")
    return "aborted", "已取消正在倒计时的关机"
