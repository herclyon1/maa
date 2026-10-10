"""Shared parts of the two OK-WW weekly switches (garden.py, weeklyboss.py).

Both switches add or remove one entry in `Additional Tasks to Run After Daily
Task` of OK-WW's master `DailyTask.json`, book the game week in which the task is
done, and clear that booking once the week rolls over. The week boundary is
`annihilation.week_key`.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from ark_relay.features.weekly.annihilation import week_key
from ark_relay.core.statestore import StateStore
from ark_relay.core.config import SERVER_TZ, master_config_dir

KEY = "Additional Tasks to Run After Daily Task"
DAILY = "DailyTask.json"


def master_file(automas_dir, name: str) -> "Path | None":
    """`name` in OK-WW's master config folder (the folder that holds DailyTask.json),
    or None when that folder cannot be found."""
    d = master_config_dir(automas_dir, DAILY)
    return (d / name) if d else None


class WeekGate:
    """Bookkeeping shared by GardenGate and WeeklyBossGate.

    State lives in state.json under `weekly.<STATE_KEY>` as {"done_week": <week_key>, ...}.
    Subclasses set NAME (shown to the user), STATE_KEY, REOPENED (the log line
    written when the booking is cleared, with %s for last week) and `_log` (their
    module's logger), and provide week_line().
    """

    NAME = ""
    STATE_KEY = ""
    REOPENED = ""
    _log = logging.getLogger("ark.weekgate")

    def __init__(self, state_dir: Path, automas_dir=None):
        self._store = StateStore(state_dir)
        self.automas_dir = automas_dir

    def _load(self) -> dict:
        return dict(self._store.get("weekly", self.STATE_KEY) or {})

    def _save(self, data: dict) -> None:
        self._store.set("weekly", self.STATE_KEY, dict(data))

    def week_line(self, now: "datetime | None" = None) -> str:
        raise NotImplementedError

    def maybe_reopen(self, now: "datetime | None" = None) -> str:
        """Called at boot. Once the week has rolled over, clears last week's
        booking and returns week_line(); returns "" when it has not."""
        state = self._load()
        done = state.get("done_week")
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        if not done or done == week:
            return ""
        state.pop("done_week", None)
        self._save(state)
        self._log.info(self.REOPENED, done)
        return self.week_line(now)
