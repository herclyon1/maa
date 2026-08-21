"""Run 剿灭 once a week instead of once a day.

AUTO-MAS runs it as a separate pass before every queue, so every run produces
two records - one of them a one-minute launch that farms nothing because MAA
recognises the weekly cap and leaves. That minute is not wasted on the check
itself; it is the cost of starting the game to ask.

Nothing anywhere remembers the answer. In AutoProxy.py:

    self.run_book = {"Annihilation": ... == "Close", "Routine": False}

`run_book` is rebuilt in memory on every run, and the only persistent control
is the static `Info.Annihilation` switch. So the weekly memory has to live
here: flip that switch to "Close" once a pass succeeds, and back to its old
value after the game's weekly reset.

Reset is Monday 04:00 on the official server's clock - the same UTC+4 day
boundary AUTO-MAS uses for its own daily bookkeeping, one day-shift out. The
previous value is remembered rather than assumed: someone who picked
`Chernobog@Annihilation` wants that map back, not the generic default.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.annihilation")

CLOSED = "Close"
DEFAULT_WHEN_UNKNOWN = "Annihilation"


def _script_config(automas_dir: Path) -> Path:
    return Path(automas_dir) / "config" / "ScriptConfig.json"


def _maa_users(data: dict):
    """Every MAA user-config node, found by install path rather than by name."""
    for inst in data.get("instances", []):
        node = data.get(inst.get("uid")) or {}
        path = ((node.get("Info") or {}).get("Path") or "").lower()
        if "maaend" in path or "maa" not in path:
            continue
        for uid, user in ((node.get("SubConfigsInfo") or {}).get("UserData") or {}).items():
            if uid == "instances" or not isinstance(user, dict):
                continue
            yield user


def week_key(now: datetime) -> str:
    """Which game-week a moment belongs to. Weekly reset is Monday 04:00.

    Anything before 04:00 on Monday still belongs to the week that is ending,
    so a run at 03:00 must not be credited to the new week and skip it.
    """
    srv = now.astimezone(SERVER_TZ)
    shifted = srv - timedelta(hours=4)
    monday = shifted - timedelta(days=shifted.weekday())
    return monday.strftime("%G-W%V") if hasattr(monday, "strftime") else str(monday.date())


def read_setting(automas_dir: Path | None) -> str:
    if not automas_dir:
        return ""
    try:
        data = json.loads(_script_config(automas_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    for user in _maa_users(data):
        return str((user.get("Info") or {}).get("Annihilation") or "")
    return ""


def _write_setting(automas_dir: Path, value: str) -> tuple[bool, str]:
    path = _script_config(automas_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"读不了 ScriptConfig: {exc}"
    touched = 0
    for user in _maa_users(data):
        info = user.setdefault("Info", {})
        if info.get("Annihilation") != value:
            info["Annihilation"] = value
            touched += 1
    if not touched:
        return True, ""
    stamp = datetime.now(tz=SERVER_TZ)
    backup = path.with_suffix(f".bak-{stamp:%Y%m%d-%H%M%S}.json")
    shutil.copy2(path, backup)
    try:
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as exc:
        shutil.copy2(backup, path)
        return False, f"写入失败，已回滚: {exc}"
    return True, f"已改 {touched} 个账号"


class WeeklyGate:
    """Remembers which game-week's 剿灭 is already done."""

    def __init__(self, state_dir: Path, automas_dir: Path | None):
        self.path = Path(state_dir) / "annihilation.json"
        self.automas_dir = automas_dir

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path,
                          json.dumps(data, ensure_ascii=False, indent=1))

    def on_success(self, now: datetime | None = None) -> str:
        """Called when an annihilation pass completed. Closes it for the week."""
        if not self.automas_dir:
            return ""
        now = now or datetime.now(tz=SERVER_TZ)
        week = week_key(now)
        state = self._load()
        if state.get("done_week") == week:
            return ""
        current = read_setting(self.automas_dir)
        if current == CLOSED:
            return ""
        # 这里只记账，不写配置。
        #
        # 这一刻是「剿灭那趟刚出记录」，队列多半还在跑下一个脚本，而 AUTO-MAS
        # 运行期间会用自己内存里的那份覆写 ScriptConfig——此时写下去的 Close
        # 会被静静冲掉（2026-08-20 实测，正是它导致本周每轮又空跑一次剿灭）。
        # 真正的关闭交给 enforce()：它挑没有脚本在跑的时刻做，而且做多少遍
        # 结果都一样，被冲回去也能再关上。
        self._save({"done_week": week, "restore_to": current or DEFAULT_WHEN_UNKNOWN})
        log.info("本周剿灭已完成，待脚本停下后关闭（周一 04:00 后恢复为 %s）", current)
        return f"本周剿灭已完成，稍后暂停到下周一（届时恢复为 {current}）"

    def enforce(self, now: datetime | None = None) -> bool:
        """本周已打完，就把开关摁回 Close。返回是否真的改了。

        必须可以反复执行，因为一次性关闭关不住：AUTO-MAS 在运行时会用自己
        内存里的配置覆写 ScriptConfig.json，把闸门刚写下的 Close 冲回去。
        2026-08-20 实测的现场就是这个样子——闸门状态文件记着「本周已完成」，
        开关却还开着，于是早晚两班各自又空跑了一次剿灭（每次约 1 分钟，
        外加一次完整的游戏启动）。on_success 因为 done_week 已匹配而直接
        返回，永远不会再关第二次，这个洞要一直漏到下周一。

        调用方负责挑没有脚本在跑的时刻调用，否则照样会被冲掉。
        """
        if not self.automas_dir:
            return False
        now = now or datetime.now(tz=SERVER_TZ)
        if self._load().get("done_week") != week_key(now):
            return False        # 本周还没打完，本来就该开着
        current = read_setting(self.automas_dir)
        if current in (CLOSED, ""):
            return False        # 已经关着，或读不到配置
        ok, detail = _write_setting(self.automas_dir, CLOSED)
        if not ok:
            log.warning("剿灭开关重新关闭失败: %s", detail)
            return False
        log.info("剿灭开关被冲回「%s」，已重新关闭（%s）", current, detail)
        return True

    def maybe_reopen(self, now: datetime | None = None) -> str:
        """Called at startup. Restores the switch once the week has rolled."""
        if not self.automas_dir:
            return ""
        now = now or datetime.now(tz=SERVER_TZ)
        state = self._load()
        done = state.get("done_week")
        if not done or done == week_key(now):
            return ""
        restore = state.get("restore_to") or DEFAULT_WHEN_UNKNOWN
        ok, detail = _write_setting(self.automas_dir, restore)
        if not ok:
            log.warning("剿灭恢复失败: %s", detail)
            return ""
        # Read it back before forgetting the week. AUTO-MAS rewrites this file
        # from its own memory while a queue runs, so a write that "succeeded"
        # can be gone seconds later - and clearing the state first meant
        # enforce() had nothing left to retry with, leaving 剿灭 off for the
        # whole new week while the operator was told it had been restored.
        if read_setting(self.automas_dir) != restore:
            log.warning("剿灭恢复写入后又被改回，保留状态待下次重试")
            return ""
        self._save({})
        log.info("新的一周，剿灭已恢复为 %s", restore)
        return f"新的一周，剿灭已重新开启（{restore}）"
