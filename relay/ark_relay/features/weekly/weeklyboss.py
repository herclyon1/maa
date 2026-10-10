"""Wuthering Waves weekly boss (战歌重奏): off once this week's three reward claims
are used, back on from Monday 04:00. Same shape as garden.py and annihilation.py
(the user, 2026-08-31: 「和剿灭逻辑一致」).

## What it changes

Two files in OK-WW's master config folder (see garden.py for why the master copy):

* `DailyTask.json`: adds/removes `Teleport and Farm 4C Echo` (「传送并刷取4C声骸」)
  in `Additional Tasks to Run After Daily Task`
* `FarmEchoTask.json`: while the switch is on, sets `Teleport to Boss` to
  `Weekly Challenge` (「战歌重奏」), `Which Weekly Boss to Teleport` from the
  settings, `Repeat Farm Count` to COUNT and `Boss Level` to MAX_LEVEL

The week counts as done only when the claims-left counter that OK-WW logs reads 0
(`remaining_from_log`).
"""
from __future__ import annotations

import json
import re
import logging
import os
from datetime import datetime
from pathlib import Path

from ark_relay.features.verify import outcome
from ark_relay.features.weekly.annihilation import week_key
from ark_relay.features.weekly.weekgate import DAILY, KEY, WeekGate, master_file
from ark_relay.core.config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.weeklyboss")

TASK_NAME = "Teleport and Farm 4C Echo"     # 「传送并刷取4C声骸」
# Boss Level: the weekly boss's level sets the reward tier, so it is pinned to the
# highest. Our FarmEchoTask.json is used only by the weekly boss (echo farming goes
# through the tacet nests), so this does not affect anything else.
LEVELS = ("50", "60", "70", "80", "90")
MAX_LEVEL = LEVELS[-1]
COUNT = 3                                   # game rule: only 3 reward claims per week

FARM = "FarmEchoTask.json"
WEEKLY = "Weekly Challenge"                 # 「战歌重奏」


_file = master_file


def _read(f: "Path | None") -> "dict | None":
    if f is None or not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(f: Path, cfg: dict) -> bool:
    # Atomic replace: AUTO-MAS may be copying this folder now; a torn JSON file stops OK-WW.
    try:
        atomic_write_text(f, json.dumps(cfg, ensure_ascii=False, indent=2))
    except OSError:
        return False
    return True


def _okww_log() -> "Path | None":
    """OK-WW's newest log (`ARK_OKWW_LOG`, else the newest file in OK-WW's log
    folder under `ARK_OKWW_DIR`). None, with a WARNING, when there is none: without
    the log the claims-left count and the boss name cannot be read."""
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

    One run does not always use all three claims: each claim costs 60 waveplates,
    so with fewer waveplates fewer are claimed. Booking the week as done when the
    run finishes would lose the claims left over.
    """
    text = _okww_log_text()
    return None if text is None else left_after_claims(text)


def _okww_log_text() -> "str | None":
    """Text of `_okww_log()`; None when there is no log or it cannot be read."""
    f = _okww_log()
    if f is None:
        return None
    try:
        return Path(str(f)).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def left_after_claims(text: str) -> "int | None":
    """Claims left after this log: the newest reading of the game's own counter.

    One run re-enters and claims up to three times, reading the counter on each way
    in; the overlay also re-reads it after each claim (outcome.WEEKLY_CLAIM_OK /
    WEEKLY_CLAIM_SAME). 「周本领奖：已点确认」 is not subtracted: it is logged right
    after the click, before anything shows the claim landed. A click-only log keeps its pre-entry number, which errs towards
    leaving the switch on - the next entry reads the counter and the 0/3 gate
    stops it.
    """
    return outcome.weekly_left(text)


_NAME_RE = re.compile(r"周本名称原文:\s*\[(.*?)\]")


def name_from_log() -> str:
    """The most recent weekly-boss name OCR'd into the OK-WW log (by the
    「周本名称原文」 patch). "" when it cannot be read."""
    text = _okww_log_text()
    if text is None:
        return ""
    hits = _NAME_RE.findall(text)
    if not hits:
        return ""
    # OCR output looks like "千傀重楼_0.99": take the first token, drop the score
    first = hits[-1].split(",")[0].strip().strip("'\"")
    return re.sub(r"_[\d.]+$", "", first).strip()


class WeeklyBossGate(WeekGate):
    """Which game week the weekly boss's claims were used up in. State:
    weekly.boss = {"done_week", "name", "index"}.

    Same interface as annihilation and the weekly garden:
    settings / week_line / on_success / enforce / maybe_reopen.
    """

    NAME = "鸣潮 · 周本"
    STATE_KEY = "boss"
    REOPENED = "新的一周，周本记账已清（上周 %s）"
    _log = log

    def __init__(self, state_dir: Path, automas_dir=None):
        super().__init__(state_dir, automas_dir)
        self._last_error = ""

    # ---------- turned on and off by a person ----------

    def settings(self, now: "datetime | None" = None) -> dict:
        """What the phone page shows. COUNT and MAX_LEVEL are fixed (user,
        2026-09-07). There is no on/off setting: it stops once the claims are used
        and comes back on Monday."""
        s = self._load()
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
            # WARNING: if the count stays unreadable the week is never booked.
            log.warning("周本：这趟打完了，但读不到本周剩余次数，没记成打完；下一趟再看，一直读不到就一直不记")
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

        # While the switch is on, also write the teleport target the task needs.
        farm_error = ""
        if want_on:
            farm_f = _file(self.automas_dir, FARM)
            farm = _read(farm_f)
            if farm is None:
                # Logged once per condition: enforce runs every round.
                farm_error = "no-farm"
                if self._last_error != farm_error:
                    log.warning("周本要挂上，但读不了 OK-WW 母本 %s，传送目标没写，周本会不知道去哪打", FARM)
            else:
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
        self._last_error = farm_error
        return changed
