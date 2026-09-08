"""Weekly garden: once done for the week, turn the check off; it comes back
automatically Monday 04:00.

Same shape as `annihilation.py` -- "something that only needs doing once a week
should not be looked at every day". Annihilation turns off MAA's
`Info.Annihilation`; this turns off the `Check Weekly Garden` entry in OK-WW's
`Task.AdditionalTasks`.

Why it is worth doing: upstream's `check_weekly_garden()` navigates to the garden
page, takes a screenshot and decides whether it is done, every single run. Six days
out of seven that is a wasted trip, pure lost time.

**Why this goes through the config layer instead of patching OK-WW source**: OK-WW's
auto-update overwrites all of `src` (measured 2026-08-26: after v3.6.5 ->
v3.6.6-beta.1 the local patches disappeared along with their backups). Config is not
in the overwritten set, so the same effect done at the config layer is immune by
construction. Things that cannot avoid touching source live in `okww_patch.py`;
anything that can be done in config must never be done by patching source.

**Changed 2026-08-28 to write the master copy directly instead of going through the
AUTO-MAS API.** It used to write `Task.AdditionalTasks` in the MAS user config, but
that path only gets pushed down when `Info.IfQuickConfig` is on. The user asked that
day to abolish quick config (it can only toggle tasks that already exist, and it
creates silent failures), so this feature stopped working entirely.

It now edits `Additional Tasks to Run After Daily Task` in the master copy at
`<automas>/data/<script id>/Default/ConfigFile/DailyTask.json`. That path does not
depend on quick config: the master directory is the one AUTO-MAS copies over to
OK-WW **unconditionally** every run.

The reason `annihilation.py` had its file writes wiped back then is that it wrote
**MAS's own config** (which MAS overwrites from its in-memory copy while running).
MAS only reads, never writes, the master `ConfigFile/` directory
(`Okww/AutoProxy.py:82,264` only read; the write-back lives in `OkNte`, not OK-WW),
so the same problem does not arise. Writes use atomic replacement so they cannot
collide with copytree and leave a torn file.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .annihilation import week_key          # the week boundary must match annihilation exactly
from .statestore import StateStore
from .config import SERVER_TZ, master_config_dir, atomic_write_text

log = logging.getLogger("ark.garden")

TASK_NAME = "Check Weekly Garden"
KEY = "Additional Tasks to Run After Daily Task"
MARKER = "DailyTask.json"


def _daily_file(automas_dir) -> "Path | None":
    d = master_config_dir(automas_dir, MARKER)
    return (d / MARKER) if d else None


class GardenGate:
    """Remember which game week's weekly garden has already been done.

    Same interface as annihilation and the weekly boss (the user, 2026-09-07:
    「逻辑上一致的东西就应该强统一」): settings() feeds the phone page, week_line()
    feeds the "new week" notification, on_success() books it, enforce() pushes the
    switch, maybe_reopen() clears the books on Monday. State file:
    {"done_week": this week}. There is no master on/off switch: like annihilation it
    stops once done and resumes Monday (the user, 2026-09-07:
    「三个周常都应该只显示状态」).
    """

    NAME = "鸣潮 · 周常乐园"

    def __init__(self, state_dir: Path, automas_dir=None):
        self._store = StateStore(state_dir)   # single state funnel: this lands in the weekly section of state.json
        self.automas_dir = automas_dir
        self._last_write_error = ""     # say the same write failure only once, see enforce()

    def _load(self) -> dict:
        return dict(self._store.get("weekly", "garden") or {})

    def _save(self, data: dict) -> None:
        self._store.set("weekly", "garden", dict(data))

    # ---------- for the phone page and the notifications ----------

    def settings(self, now: datetime | None = None) -> dict:
        s = self._load()
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        return {"本周已完成": s.get("done_week") == week}

    def week_line(self, now: datetime | None = None) -> str:
        v = self.settings(now)
        if v["本周已完成"]:
            return f"{self.NAME}：本周已完成，暂停检查到下周一"
        return f"{self.NAME}：本周还没做，每趟都会去检查"

    # ---------- done for this week ----------

    def on_success(self, now: datetime | None = None) -> str:
        """Called when the report shows the weekly garden as done for the week.

        Only books it; does not write the config. Writing is left to `enforce()`:
        at this moment the queue is most likely still running the next script, and
        the config is locked while a task runs, so writing now would certainly fail.
        """
        now = now or datetime.now(tz=SERVER_TZ)
        week = week_key(now)
        state = self._load()
        if state.get("done_week") == week:
            return ""
        state["done_week"] = week
        self._save(state)
        log.info("本周周常乐园已完成，待脚本停下后关闭检查（周一 04:00 后恢复）")
        return f"{self.NAME}：本周已完成，暂停检查到下周一"

    def maybe_reopen(self, now: datetime | None = None) -> str:
        """Called at boot.

        Clears last week's booking once the week has rolled over and returns
        week_line; returns an empty string if the week has not rolled over.
        """
        state = self._load()
        done = state.get("done_week")
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        if not done or done == week:
            return ""
        state.pop("done_week", None)
        self._save(state)
        log.info("新的一周，周常乐园记账已清（上周 %s）", done)
        return self.week_line(now)

    # ---------- push the switch to where it should be ----------

    def enforce(self, now: datetime | None = None) -> bool:
        """Push the switch to where it should be. Returns whether anything changed.

        Must be safe to run repeatedly: turning it off once does not mean it stays
        off, and it has to come back on when Monday arrives.
        """
        now = now or datetime.now(tz=SERVER_TZ)
        week = week_key(now)
        state = self._load()
        want_on = state.get("done_week") != week      # like annihilation: no master switch, stop once done

        f = _daily_file(self.automas_dir)
        if f is None:
            if self._last_write_error != "no-master":
                log.warning("找不到 OK-WW 母本 %s，周常乐园开关没法改", MARKER)
                self._last_write_error = "no-master"
            return False
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            if str(exc) != self._last_write_error:
                log.warning("读不了 %s：%s", f.name, exc)
                self._last_write_error = str(exc)
            return False
        tasks = list(cfg.get(KEY) or [])
        has = TASK_NAME in tasks
        if want_on == has:
            if state.get("done_week") and state["done_week"] != week:
                state.pop("done_week", None); self._save(state)   # stale booking, clear it while we are here
            return False
        if want_on:
            tasks.append(TASK_NAME)
        else:
            tasks.remove(TASK_NAME)

        cfg[KEY] = tasks
        # Atomic replace: copytree may be reading this directory right now, and a torn
        # JSON file would stop OK-WW from starting.
        try:
            atomic_write_text(f, json.dumps(cfg, ensure_ascii=False, indent=2))
        except OSError as exc:
            if str(exc) != self._last_write_error:
                log.warning("周常乐园开关写不进去：%s", exc)
                self._last_write_error = str(exc)
            return False
        self._last_write_error = ""
        if want_on:
            if state.get("done_week") and state["done_week"] != week:
                state.pop("done_week", None); self._save(state)
            log.info("周常乐园检查已恢复")
        else:
            log.info("已关闭周常乐园检查（周一 04:00 后自动恢复）")
        return True
