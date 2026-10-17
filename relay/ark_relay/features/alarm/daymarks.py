"""Per-day facts the engine asks handle.py for: whether a game has an update
window registered today, and which alarm keys were already marked sent today
(state.json marks.alerted:<day>).
"""
from __future__ import annotations

from pathlib import Path


def _maintenance_today(eng, game: str) -> bool:
    try:
        from ark_relay.features.gameupdate import gameupdate  # noqa: PLC0415
        return game in gameupdate.windows(eng.state.dir)
    except Exception:  # noqa: BLE001
        return False


# Script + user + which steps failed. No push is held back on this key; only
# tests/test_alert_dedup.py reads it (through Engine._alert_key).
# 来龙去脉见 docs/CODE-HISTORY.md「handle.py:(模块级)」
def _alert_key(eng, rec) -> str:
    return f"{rec.script}|{rec.user}|{','.join(sorted(rec.failed_tasks or ['?']))}"


def _alerted_file(eng, day: str) -> Path:
    """The path of the old per-day alerted file. Nothing calls it (Engine._alerted_file
    wraps it and is itself never called); the marks live in state.json under
    marks.alerted:<day>."""
    return Path(eng.state.dir) / f"alerted-{day}.json"


def _already_alerted(eng, day: str, key: str) -> bool:
    got = eng.state.store.get("marks", f"alerted:{day}")
    return key in got if isinstance(got, list) else False


def _mark_alerted(eng, day: str, key: str) -> None:
    """Add `key` to the day's marks in one read-modify-write of state.json (update):
    built from a get() outside the write lock, two marks racing wrote back the list
    each had read and one of them was lost."""
    def _add(got):
        cur = list(got) if isinstance(got, list) else []
        if key not in cur:
            cur.append(key)
        return cur
    eng.state.store.update("marks", f"alerted:{day}", _add)
