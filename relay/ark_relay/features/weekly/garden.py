"""Weekly garden (OK-WW "Check Weekly Garden"): off once done for the game week,
back on from Monday 04:00.

The switch is the `Check Weekly Garden` entry in `Additional Tasks to Run After Daily
Task` of OK-WW's master `DailyTask.json`
(`<automas>/data/<script id>/Default/ConfigFile/DailyTask.json`). AUTO-MAS copies that
master folder over OK-WW's own config before every run whether or not quick config is
on, and AUTO-MAS only reads it, so a write there is what OK-WW runs with. OK-WW's
auto-update replaces its `src` folder but not its config, so this is done in config
rather than by patching OK-WW source. Writes are atomic replaces so a copy in progress
never reads a torn file.

Without the switch, upstream's `check_weekly_garden()` opens the garden page and checks
it on every run.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ark_relay.features.weekly.annihilation import week_key
from ark_relay.features.weekly.weekgate import KEY, WeekGate, master_file
from ark_relay.core.config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.garden")

TASK_NAME = "Check Weekly Garden"
MARKER = "DailyTask.json"


class GardenGate(WeekGate):
    """Which game week the weekly garden was done in.

    Same interface as annihilation and the weekly boss: settings() for the phone page,
    week_line() for the "new week" notification, on_success() books the week,
    enforce() sets the switch, maybe_reopen() clears the booking on Monday. State:
    weekly.garden = {"done_week": <week_key>}. There is no on/off setting: it stops
    once done and resumes Monday (the user, 2026-09-07: 「三个周常都应该只显示状态」).
    """

    NAME = "鸣潮 · 周常乐园"
    STATE_KEY = "garden"
    REOPENED = "新的一周，周常乐园记账已清（上周 %s）"
    _log = log

    def __init__(self, state_dir: Path, automas_dir=None):
        super().__init__(state_dir, automas_dir)
        self._last_write_error = ""     # the last failure logged by enforce(), so it is logged once

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

        f = master_file(self.automas_dir, MARKER)
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
                state.pop("done_week", None); self._save(state)   # booking from an earlier week
            return False
        if want_on:
            tasks.append(TASK_NAME)
        else:
            tasks.remove(TASK_NAME)

        cfg[KEY] = tasks
        # Atomic replace: AUTO-MAS may be copying this folder now; a torn JSON file stops OK-WW.
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
