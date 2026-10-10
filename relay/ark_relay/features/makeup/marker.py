"""The make-up's day marker (state/makeup/<day>.json) and what is read from it:
which held failures a make-up is still due for, which make-ups are running, and
when the next clock-only change of that is due.

Re-exported by makeup.py; callers use the makeup module.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core.config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.makeup")

SCRIPTS = ("MAA", "MaaEnd")
# A dispatch that did not take is retried no sooner than this.
RETRY_GAP_S = 120
# A dispatched make-up with no record and not seen running for this long is
# closed as NO_RECORD (AUTO-MAS took the order and ran nothing).
STALE_MIN = 10

# Results kept in the marker. `couldnt_run` is the only one that does not count
# as today's attempt.
DISPATCHED, COULDNT_RUN, GAVE_UP, OK, FAILED, NO_RECORD = (
    "dispatched", "couldnt_run", "gave_up", "ok", "failed", "no_record")


# ------------------------------------------------------------------ marker

def _dir(state_dir) -> Path:
    return Path(state_dir) / "makeup"


def _marker_file(state_dir, day: str) -> Path:
    return _dir(state_dir) / f"{day}.json"


# (state_dir, day) of marker files that exist but cannot be read. read_marker
# runs every tick, so each is logged once; a key is dropped once its file reads
# again. attempted() treats a day in this set as spent.
_unreadable: set = set()


def read_marker(state_dir, day: str) -> dict:
    """{script: {...}} for the day, {} when there is none or it cannot be read.

    A marker that is there but unreadable also reads as {}, and its day is
    remembered in `_unreadable` so attempted() treats every script as spent: a
    second whole make-up the same day would spend the stamina again. Nothing
    writes over that file then (no candidate, no entry to settle)."""
    if not state_dir:
        return {}
    f = _marker_file(state_dir, day)
    key = (str(state_dir), day)
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _unreadable.discard(key)
        return {}                       # no make-up yet that day: the normal case
    except (OSError, ValueError) as exc:
        if key not in _unreadable:
            log.warning("补跑记录 %s 读不出来（%s），当天按已补过处理，不再补跑", f.name, type(exc).__name__)
            _unreadable.add(key)
        return {}
    if not isinstance(d, dict):
        if key not in _unreadable:
            log.warning("补跑记录 %s 不是字典，当天按已补过处理，不再补跑", f.name)
            _unreadable.add(key)
        return {}
    _unreadable.discard(key)
    return d


def _write_marker(state_dir, day: str, data: dict) -> None:
    f = _marker_file(state_dir, day)
    f.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(f, json.dumps(data, ensure_ascii=False, indent=1))


def _day(t: datetime) -> str:
    return t.astimezone(SERVER_TZ).strftime("%Y-%m-%d")


def _at(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)


def attempted(state_dir, day: str, script: str) -> bool:
    """True once the day's make-up for `script` is spent: dispatched (whatever came of
    it) or given up. A dispatch that did not take (`couldnt_run`) is not an attempt."""
    ent = read_marker(state_dir, day).get(script)
    if (str(state_dir), day) in _unreadable:
        return True                     # the day's marker is there but unreadable: see read_marker
    return bool(ent) and ent.get("result") != COULDNT_RUN


# ------------------------------------------------------------- candidates

def eligible(rec, now: datetime | None = None) -> bool:
    """Whether a held failure is one a make-up is for: MAA / MaaEnd, started today,
    not a maintenance day, not a game it could not even enter, not stopped by hand."""
    if getattr(rec, "script", None) not in SCRIPTS:
        return False
    if _day(rec.started) != _day(_now(now)):
        return False
    raw = rec.raw or {}
    return not (raw.get("maintenance") or raw.get("maaend_unreachable") or raw.get("manual_stop"))


def candidates(eng, now: datetime | None = None) -> list:
    """Held failures a make-up is still to be dispatched for (today's marker not spent)."""
    today = _day(_now(now))
    return [r for r in eng._pending.values()
            if eligible(r, now) and not attempted(eng.cfg.state_dir, today, r.script)]


def holding(eng, rec, now: datetime | None = None) -> bool:
    """_flush_pending keeps `rec` held (no push, no drop): its make-up is still to come."""
    return eligible(rec, now) and not attempted(eng.cfg.state_dir, _day(_now(now)), rec.script)


def _recent(state_dir, now: datetime) -> list[tuple[str, dict]]:
    """(day, marker) for today and yesterday. A make-up dispatched at 23:55 is still
    running after midnight, and its entry sits in the day it was dispatched on."""
    return [(d, read_marker(state_dir, d)) for d in (_day(now - timedelta(days=1)), _day(now))]


def _last_stamp(ent: dict) -> datetime | None:
    stamps = [t for t in (_at(ent.get("dispatched_at")), _at(ent.get("seen_running_at"))) if t]
    return max(stamps) if stamps else None


def _fresh(ent, now: datetime) -> bool:
    """A dispatched make-up that has not gone stale."""
    if not isinstance(ent, dict) or ent.get("result") != DISPATCHED:
        return False
    last = _last_stamp(ent)
    return last is not None and now - last <= timedelta(minutes=STALE_MIN)


def in_flight(state_dir, now: datetime | None = None) -> list[str]:
    """Scripts whose dispatched make-up has not produced a record yet and is not stale,
    whichever day it was dispatched on."""
    now = _now(now)
    return sorted({script for _, marker in _recent(state_dir, now)
                   for script, ent in marker.items() if _fresh(ent, now)})


def maaend_still_running(state_dir, now: datetime | None = None) -> bool:
    """A MaaEnd make-up is in flight and AUTO-MAS says MaaEnd has not finished.

    For the boot-time restore: a relay restart in the middle of the make-up
    must not put the full master back under it. AUTO-MAS not answering counts as
    not running (a real boot: nothing can be running yet)."""
    if "MaaEnd" not in in_flight(state_dir, now):
        return False
    from ark_relay.core import engine  # noqa: PLC0415
    snap = engine._automas_snapshot()
    return snap is not None and engine._script_unfinished(snap, "MaaEnd")


def next_moment(state_dir, now: datetime | None = None) -> tuple[datetime, str] | None:
    """The next moment a make-up decision changes by the clock alone, for engine.next_deadline."""
    now = _now(now)
    out: list[tuple[datetime, str]] = []
    for script, ent in (kv for _, marker in _recent(state_dir, now) for kv in marker.items()):
        if not isinstance(ent, dict):
            continue
        last = _last_stamp(ent)
        if last is None:
            continue
        if ent.get("result") == COULDNT_RUN:
            out.append((last + timedelta(seconds=RETRY_GAP_S), f"补跑 {script} 再派一次"))
        elif ent.get("result") == DISPATCHED:
            out.append((last + timedelta(minutes=STALE_MIN, seconds=1), f"补跑 {script} 有没有跑起来"))
    out = [m for m in out if m[0] > now]
    return min(out) if out else None


def waiting(eng, now: datetime | None = None) -> list[str]:
    """What the shutdown decision and the reports wait for: make-ups still to dispatch or running."""
    names = {r.script for r in candidates(eng, now)} | set(in_flight(eng.cfg.state_dir, now))
    return sorted(names)
