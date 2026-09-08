"""Run annihilation (剿灭) once a week instead of once a day.

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

from .statestore import StateStore
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
    """The current annihilation setting. **Ask the backend first** - the file
    may not have been refreshed yet.

    Reading the file has the same trap as writing it: while AUTO-MAS is running,
    what is in the file is neither what it holds in memory nor what will
    eventually be persisted. A read-back check that picks up the stale value
    concludes either "the write failed" or "the write succeeded", and neither
    conclusion can be trusted.
    """
    try:
        from .commands import _find_user  # noqa: PLC0415 - avoids an import cycle
        return str((_find_user("MAA")[2].get("Info") or {}).get("Annihilation") or "")
    except Exception:  # noqa: BLE001 - backend down: fall back to reading the file
        pass
    if not automas_dir:
        return ""
    try:
        data = json.loads(_script_config(automas_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    for user in _maa_users(data):
        return str((user.get("Info") or {}).get("Annihilation") or "")
    return ""


def _write_via_api(value: str) -> tuple[bool, str]:
    """Change it through the AUTO-MAS backend. **This is the preferred path.**

    The problem with editing the config file directly: while AUTO-MAS runs it
    overwrites the file from its own in-memory copy, so a value written there is
    wiped seconds later. That is what happened at 04:01 on 2026-08-31 - the
    restore write succeeded and the immediate read-back agreed, then it was wiped
    back to Close; `maybe_reopen`, having passed its read-back, cleared the
    bookkeeping, so nothing ever retried and annihilation went unfought for the
    entire week.

    Writing through the backend API changes **the copy that is running**. There
    is no unpersisted in-memory copy left, so there is nothing that can wipe it.
    """
    from .commands import _find_user, _mas  # noqa: PLC0415 - avoids an import cycle
    sid, uid, user = _find_user("MAA")
    if (user.get("Info") or {}).get("Annihilation") == value:
        return True, ""
    _mas("/api/scripts/user/update",
         {"scriptId": sid, "userId": uid,
          "data": {"Info": {"Annihilation": value}}})
    users = _mas("/api/scripts/user/get", {"scriptId": sid})["data"]
    now = (users[uid].get("Info") or {}).get("Annihilation")
    if now != value:
        return False, f"写了但没生效：现在是 {now!r}"
    return True, "已通过 AUTO-MAS 后端改写"


def _write_setting(automas_dir: Path, value: str) -> tuple[bool, str]:
    # Use the backend when it is running; fall back to editing the file only when
    # it cannot be reached (AUTO-MAS is not up) - in that case there is no
    # in-memory copy, so editing the file is safe.
    try:
        return _write_via_api(value)
    except Exception as exc:  # noqa: BLE001
        log.info("AUTO-MAS 后端不可用（%s），退回直接改配置文件", exc)
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
    """Remembers which game-week's annihilation is already done.

    Same interface as the weekly garden and the weekly boss:
    settings / week_line / on_success / enforce / maybe_reopen.
    """

    NAME = "明日方舟 · 剿灭"

    def __init__(self, state_dir: Path, automas_dir: Path | None):
        # single state entry point: persisted in state.json's `weekly` section
        self._store = StateStore(state_dir)
        self.automas_dir = automas_dir

    def settings(self, now: datetime | None = None) -> dict:
        s = self._load()
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        return {"本周已完成": s.get("done_week") == week,
                "当前": read_setting(self.automas_dir) if self.automas_dir else ""}

    def week_line(self, now: datetime | None = None) -> str:
        v = self.settings(now)
        if v["本周已完成"]:
            return f"{self.NAME}：本周已打满，暂停到下周一"
        return f"{self.NAME}：本周还没打满，开关开着（{v['当前'] or '读不到'}）"

    def _load(self) -> dict:
        return dict(self._store.get("weekly", "annihilation") or {})

    def _save(self, data: dict) -> None:
        self._store.set("weekly", "annihilation", dict(data))

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
        # Bookkeeping only here; nothing is written to the config.
        #
        # This moment is "the annihilation pass has just produced its
        # record", so the queue is most likely still running the next script,
        # and while AUTO-MAS runs it overwrites ScriptConfig from its own
        # in-memory copy - a Close written now is silently wiped (measured
        # 2026-08-20; that is exactly what made every round this week burn
        # another empty annihilation pass). The actual close is left to
        # enforce(): it picks a moment when no script is running, and running
        # it any number of times gives the same result, so it can close the
        # switch again after it has been wiped back open.
        self._save({"done_week": week, "restore_to": current or DEFAULT_WHEN_UNKNOWN})
        log.info("本周剿灭已完成，待脚本停下后关闭（周一 04:00 后恢复为 %s）", current)
        return f"{self.NAME}：本周已打满，暂停到下周一（届时恢复为 {current}）"

    def enforce(self, now: datetime | None = None) -> bool:
        """Once this week's pass is done, push the switch back to Close.

        Returns whether anything was actually changed.

        This must be safe to run over and over, because closing the switch
        once does not keep it closed: while AUTO-MAS runs it overwrites
        ScriptConfig.json from its own in-memory config, wiping out the Close
        the gate just wrote. That is exactly what was measured on 2026-08-20 -
        the gate's state file said "done for this week" while the switch was
        still open, so the morning and evening rounds each burned another
        empty annihilation pass (about 1 minute apiece, plus a full
        game launch each time). on_success returns immediately because
        done_week already matches, so it never closes the switch a second
        time, and the hole would stay open until the following Monday.

        The caller is responsible for calling this at a moment when no script
        is running; otherwise the write gets wiped just the same.
        """
        if not self.automas_dir:
            return False
        now = now or datetime.now(tz=SERVER_TZ)
        if self._load().get("done_week") != week_key(now):
            return False        # not done this week yet - it should be open
        current = read_setting(self.automas_dir)
        if current in (CLOSED, ""):
            return False        # already closed, or the config cannot be read
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
        # enforce() had nothing left to retry with, leaving annihilation off for
        # the whole new week while the operator was told it had been restored.
        if read_setting(self.automas_dir) != restore:
            log.warning("剿灭恢复写入后又被改回，保留状态待下次重试")
            return ""
        self._save({})
        log.info("新的一周，剿灭已恢复为 %s", restore)
        return f"{self.NAME}：新的一周，已重新开启（{restore}）"
