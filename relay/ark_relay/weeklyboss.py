"""Wuthering Waves weekly boss (战歌重奏): switched off once done for the week,
switched back on automatically at 04:00 on Monday.

Same shape as `garden.py` and `annihilation.py` - "something that only needs
doing once a week must not be done every day". What the user asked for on
2026-08-31 was exactly 「和剿灭逻辑一致」 (same logic as annihilation).

## What it actually changes

Two files, both in OK-WW's **master** config directory (the one AUTO-MAS copies
to OK-WW unconditionally every round, unaffected by the "quick config" switch;
reasoning is in garden.py):

* adds/removes `Teleport and Farm 4C Echo` (「传送并刷取4C声骸」 in the game's
  translation) in `DailyTask.json`'s
  `Additional Tasks to Run After Daily Task`
* sets `FarmEchoTask.json`'s `Teleport to Boss` to `Weekly Challenge`
  (「战歌重奏」, i.e. the weekly boss), and writes
  `Which Weekly Boss to Teleport` and `Repeat Farm Count` from the settings

## Why it is off by default

`Repeat Farm Count` ships as **10000**. Turned on as-is, it would keep fighting
forever. How many times a week the weekly boss pays out is a game rule I have no
reliable source for, so it is not decided on the user's behalf - **off by
default, the count comes from the user on the phone**. Inventing game rules and
writing them into production config is precisely what caused incident 826.
"""
from __future__ import annotations

import json
import re
import logging
import os
from datetime import datetime
from pathlib import Path

from .annihilation import week_key          # week boundary identical to annihilation
from .statestore import StateStore
from .config import SERVER_TZ, master_config_dir, atomic_write_text

log = logging.getLogger("ark.weeklyboss")

TASK_NAME = "Teleport and Farm 4C Echo"     # 「传送并刷取4C声骸」
TASK_ZH = "传送并刷取4C声骸"
KEY = "Additional Tasks to Run After Daily Task"
# Upstream describes Boss Level as "Choose the Lowest that Drop a Echo" - that is
# the **echo-farming** mindset: the lowest level that still drops echoes is the
# easiest fight. The weekly boss is the opposite: **the level decides the reward
# tier, so it must be the highest**. Both uses share one config key, but our
# FarmEchoTask is used by the weekly boss only (day-to-day echo farming goes
# through the tacet nests), so pinning it to the maximum level creates no
# conflict. On 2026-08-31 the user pointed out the machine was set to 80, which
# was wrong.
LEVELS = ("50", "60", "70", "80", "90")
MAX_LEVEL = LEVELS[-1]
COUNT = 3                                   # game rule: only 3 reward claims per week

DAILY = "DailyTask.json"
FARM = "FarmEchoTask.json"
WEEKLY = "Weekly Challenge"                 # 「战歌重奏」


def _file(automas_dir, name: str) -> "Path | None":
    d = master_config_dir(automas_dir, DAILY)
    return (d / name) if d else None


def _read(f: "Path | None") -> "dict | None":
    if f is None or not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(f: Path, cfg: dict) -> bool:
    # Atomic replace: AUTO-MAS may be copying this directory right now, and torn
    # JSON stops OK-WW from starting at all.
    try:
        atomic_write_text(f, json.dumps(cfg, ensure_ascii=False, indent=2))
    except OSError:
        return False
    return True


def _okww_log() -> "Path | None":
    """OK-WW's newest log. Returns None when there is none, and **says so out
    loud** - failing silently here is not allowed.

    Found in review on 2026-09-08: with `ARK_OKWW_DIR` unset this used to just
    return, so the remaining-claims count could not be read, the weekly-boss
    bookkeeping never advanced and the boss name was never read either - the
    phone kept showing 「本周还没领满」 and the machine went and fought it again
    every day, with not one word about it in the log. An environment variable can
    go missing (a new machine, an edited deploy script, one wrong line in .env),
    and when it does it must be audible.
    """
    if path := os.environ.get("ARK_OKWW_LOG"):
        return Path(path)
    root = os.environ.get("ARK_OKWW_DIR")
    if not root:
        log.warning("ARK_OKWW_DIR 没设，读不到 OK-WW 的日志——"
                    "周本记账、剩余次数、周本名字全都会失效")
        return None
    logs = Path(root) / "data" / "apps" / "ok-ww" / "working" / "logs"
    try:
        return max(logs.glob("*.log*"), key=lambda q: q.stat().st_mtime)
    except (OSError, ValueError):
        log.warning("OK-WW 的日志目录 %s 里没有日志，周本记账这一轮跳过", logs)
        return None


def remaining_from_log() -> "int | None":
    """The most recent 「本周剩余可收取次数」 (claims left this week) read from the
    OK-WW log. None when it cannot be read.

    The local patch that "takes a screenshot before entering to read the claims
    left" OCRs that line into the log, shaped like
    `周本本周剩余次数原文: [... '本周剩余可收取次数：2/3' ...]`.
    Only the number before the slash is taken.

    Why read it at all: `on_success` used to mark the week done as soon as the
    task finished, but **one round does not necessarily claim all three times** -
    the reward costs 60 waveplates on entry, and short on waveplates you claim
    fewer. Measured 2026-08-31: shell-credit farming had burned waveplates down
    to 1, and by the next morning they had only recovered to ~147, enough for two
    claims. Bookkeeping that treats "the round finished" as "the week is done"
    loses the third claim for good.
    """
    f = _okww_log()
    if f is None:
        return None
    path = str(f)
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    hits = re.findall(r"本周剩余可收取次数[：:]\s*(\d+)\s*/\s*(\d+)", text)
    if not hits:
        return None
    return int(hits[-1][0])


_NAME_RE = re.compile(r"周本名称原文:\s*\[(.*?)\]")


def name_from_log() -> str:
    """The most recent weekly-boss name OCR'd into the OK-WW log (by the
    「周本名称原文」 patch). "" when it cannot be read."""
    f = _okww_log()
    if f is None:
        return ""
    path = str(f)
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    hits = _NAME_RE.findall(text)
    if not hits:
        return ""
    # OCR output looks like "千傀重楼_0.99": take the first token, drop the score
    first = hits[-1].split(",")[0].strip().strip("'\"")
    return re.sub(r"_[\d.]+$", "", first).strip()


class WeeklyBossGate:
    """Remembers which game week the weekly boss has already been cleared in.
    Off by default; someone has to turn it on explicitly.

    Same interface as annihilation and the weekly garden:
    settings / week_line / on_success / enforce / maybe_reopen.
    """

    NAME = "鸣潮 · 周本"

    def __init__(self, state_dir: Path, automas_dir=None):
        # single state entry point: persisted in state.json's `weekly` section
        self._store = StateStore(state_dir)
        self.automas_dir = automas_dir
        self._last_error = ""

    def _load(self) -> dict:
        return dict(self._store.get("weekly", "boss") or {})

    def _save(self, data: dict) -> None:
        self._store.set("weekly", "boss", dict(data))

    # ---------- turned on and off by a person ----------

    def settings(self, now: "datetime | None" = None) -> dict:
        """What the phone page shows. 3 times a week and level 90 are game rules:
        fixed, not editable (user, 2026-09-07). There is no master switch either -
        like annihilation, it stops itself once the quota is full and comes back
        on by itself on Monday."""
        s = self._load()
        # 「本周已打」 must compare done_week against **the current week**, not
        # merely check that it has a value.
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        return {"名字": str(s.get("name") or ""),
                "第几个周本": int(s.get("index") or 1),
                "打几次": COUNT,
                "难度等级": MAX_LEVEL,
                "本周已打": s.get("done_week") == week}

    def configure(self, *, index: "int | None" = None) -> tuple[bool, str]:
        s = self._load()
        if index is not None:
            if not 1 <= int(index) <= 20:
                return False, f"周本序号 {index} 不像话（应在 1~20）"
            s["index"] = int(index)
        self._save(s)
        return True, f"周本：打第 {self.settings()['第几个周本']} 个"

    def week_line(self, now: "datetime | None" = None) -> str:
        """The weekly-boss line in the "new week" notification: where this week
        stands. It always has something to say."""
        v = self.settings(now)
        what = v["名字"] or f"第 {v['第几个周本']} 个"
        if v["本周已打"]:
            return f"{self.NAME}：{what} 本周三次已领满，暂停到下周一"
        return f"{self.NAME}：{what}，本周还没领满"

    def maybe_reopen(self, now: "datetime | None" = None) -> str:
        """Called at boot. Once the week has rolled over, clears last week's
        "quota full" mark and returns week_line; returns "" if it has not."""
        s = self._load()
        done = s.get("done_week")
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        if not done or done == week:
            return ""
        s.pop("done_week", None)
        self._save(s)
        log.info("新的一周，周本记账已清（上周 %s）", done)
        return self.week_line(now)

    # ---------- done for the week ----------

    def on_success(self, now: "datetime | None" = None) -> str:
        s = self._load()
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        if s.get("done_week") == week:
            return ""
        if nm := name_from_log():
            if s.get("name") != nm:
                s["name"] = nm
                self._save(s)
        left = remaining_from_log()
        if left is None:
            log.info("周本：读不到本周剩余次数，这趟先不记账，下一趟再看")
            return ""
        if left > 0:
            log.info("周本：本周还剩 %d 次没领，开关继续挂着", left)
            return f"{self.NAME}：这趟领了，本周还剩 {left} 次没领，下一趟接着打"
        s["done_week"] = week
        self._save(s)
        log.info("本周周本三次已领满，待脚本停下后摘掉（周一 04:00 后恢复）")
        return f"{self.NAME}：本周三次已领满，暂停到下周一"

    # ---------- push the switch to where it should be ----------

    def enforce(self, now: "datetime | None" = None) -> bool:
        """Safe to run repeatedly: switching it off once does not keep it off -
        it has to go back on when Monday arrives."""
        s = self._load()
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        want_on = s.get("done_week") != week

        daily_f = _file(self.automas_dir, DAILY)
        daily = _read(daily_f)
        if daily is None:
            if self._last_error != "no-master":
                log.warning("找不到 OK-WW 母本 %s，周本开关没法改", DAILY)
                self._last_error = "no-master"
            return False

        tasks = list(daily.get(KEY) or [])
        has = TASK_NAME in tasks
        changed = False

        if want_on and not has:
            tasks.append(TASK_NAME)
            changed = True
        elif not want_on and has:
            tasks.remove(TASK_NAME)
            changed = True
        if changed:
            daily[KEY] = tasks
            if not _write(daily_f, daily):
                log.warning("周本开关写不进 %s", DAILY)
                return False

        # While turning it on, also write the teleport target - otherwise the task
        # is armed with nowhere to go
        if want_on:
            farm_f = _file(self.automas_dir, FARM)
            farm = _read(farm_f)
            if farm is not None:
                want = {"Teleport to Boss": WEEKLY,
                        "Which Weekly Boss to Teleport": int(s.get("index") or 1),
                        "Repeat Farm Count": COUNT,
                        "Boss Level": MAX_LEVEL}
                if any(farm.get(k) != v for k, v in want.items()):
                    farm.update(want)
                    if _write(farm_f, farm):
                        changed = True
                    else:
                        log.warning("周本的传送设置写不进 %s", FARM)

        if changed:
            log.info("周本已%s（第 %s 个，打 %s 次）",
                     "挂上" if want_on else "摘掉", s.get("index") or 1, COUNT)
        self._last_error = ""
        return changed
