"""This game-week's annihilation (剿灭) status, as AUTO-MAS keeps it.

Running annihilation once a week is AUTO-MAS's job since the 2026-10-11
switch-over (board list 打包-交接AUTO-MAS-删代码清单-1011.md, item 13): with the
MAA account's Info.IfQuickConfig on, AUTO-MAS records a completed week in
Data.AnnihilationCompletedWeek and skips annihilation until the Monday 04:00
reset (AutoProxy._should_run_annihilation). The relay no longer flips
Info.Annihilation to "Close" and back; that fought AUTO-MAS over the setting.

What stays here is reading: the week marker and the switch, for the one status
line (week_line), the phone's settings, and the boot alarm when the switch is
off with this week not done (switch_off_line) - nothing turns it back on.
"""
from __future__ import annotations

import json
import logging
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ

log = logging.getLogger("ark.annihilation")

# Info.Annihilation's "off" value (AUTO-MAS MAA user config; any other value is
# the stage to fight, e.g. "Annihilation").
SWITCH_OFF = "Close"


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
    so a run at 03:00 must not be credited to the new week and skip it. The
    same marker AUTO-MAS writes to Data.AnnihilationCompletedWeek
    (f"{iso_year:04d}-W{iso_week:02d}" on the UTC+4 game day, AutoProxy
    _current_week_marker): Beijing time minus 4 hours is that day.
    """
    srv = now.astimezone(SERVER_TZ)
    shifted = srv - timedelta(hours=4)
    monday = shifted - timedelta(days=shifted.weekday())
    return monday.strftime("%G-W%V")


# _maa_user's failure currently said (at most one), so a lasting one is said once,
# not per call. Mutated in place, like statestore's _CORRUPT_SAID.
_READ_SAID: set[str] = set()


def _maa_user(automas_dir: Path | None) -> dict:
    """The MAA account's config, {} when unreadable. **Ask the backend first** -
    the file may not have been refreshed yet.

    While AUTO-MAS is running, what is in the file is neither what it holds in
    memory nor what will eventually be persisted, so the file is read only when
    nothing answers on the backend's port (_backend_unreachable).

    Once the machine is going down the backend is not asked either: the last state
    push (service.py:SvcStop with phone.STOP_WHY, app_main.py stop-push) runs while
    Windows tears AUTO-MAS down, so the call fails for no reason but the stop -
    10-11 21:46:43, ConnectionResetError 10054 one second after service.STOP_NOTICE,
    pushed to the group as a relay error under this logger. That push reads everything
    else of AUTO-MAS from the files too (phone.state_payload, snapshot.read skips the
    AUTO-MAS sections), and this is a read only, so no in-memory copy can be written
    over. This includes the relay's own 60-second power-off countdown
    (errwatch.relay_shutdown_issued), as snapshot.read's down() does; a plain service
    stop is not the machine going down (_going_down).
    """
    if not _going_down():
        try:
            from ark_relay.features.phone.commands import _find_user  # noqa: PLC0415 - avoids an import cycle
            user = _find_user("MAA")[2]
        except Exception as exc:  # noqa: BLE001 - only "backend down" may fall back to the file
            if not _backend_unreachable(exc):
                # Something is listening (HTTP error, timeout, no "MAA", odd answer), so
                # the file is the stale copy the docstring warns about.
                # Said once per condition: the phone's state publish calls this constantly.
                if "backend-error" not in _READ_SAID:
                    log.warning("AUTO-MAS 后端有回应但读不出方舟账号的设置（%s: %s），不拿配置文件里的旧值顶替",
                                type(exc).__name__, exc)
                    _READ_SAID.add("backend-error")
                return {}
        else:
            _READ_SAID.clear()
            return user if isinstance(user, dict) else {}
    _READ_SAID.clear()
    if not automas_dir:
        return {}
    try:
        data = json.loads(_script_config(automas_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    for user in _maa_users(data):
        return user
    return {}


def _going_down() -> bool:
    """The machine itself is on its way down (snapshot.read's down() too): the relay's own
    power-off (errwatch.relay_shutdown_issued), or Windows shutting down - SvcShutdown ran
    (errwatch.os_shutdown) or the session reports SM_SHUTTINGDOWN. Not a plain service stop
    (`sc stop`, the self-update restart): the machine and AUTO-MAS stay up then, so a read
    that fails is a fault and is said (until 2026-10-12 errwatch.going_down(), which counts
    any service stop, kept it from the group)."""
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415 - imported where used, as snapshot.read does
    return errwatch.relay_shutdown_issued() or errwatch.os_shutdown() or errwatch.system_shutting_down()


def _field(user: dict, section: str, key: str) -> str:
    return str((user.get(section) or {}).get(key) or "")


def _backend_unreachable(exc: BaseException) -> bool:
    """Whether nothing answered: the connection to the backend was refused.

    That is the one state in which editing ScriptConfig.json is safe - no
    AUTO-MAS process holds an in-memory copy to write back over it. An HTTP
    error, a timeout on an accepted connection, a missing "MAA" script or a
    malformed answer all mean something is listening, and a file edit then is
    silently undone while the caller reports success.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, urllib.error.URLError):
        exc = exc.reason if isinstance(exc.reason, BaseException) else exc
    return isinstance(exc, ConnectionRefusedError)


class WeeklyGate:
    """This game-week's annihilation status, read from AUTO-MAS.

    The same NAME / settings / week_line as the weekly garden and the weekly boss,
    for the shared new-week notice and the phone; the bookkeeping and the switch
    are AUTO-MAS's (module docstring).
    """

    NAME = "明日方舟 · 剿灭"

    def __init__(self, state_dir: Path, automas_dir: Path | None):
        # state_dir is unused now; kept so every weekly gate is built the same way.
        self.automas_dir = automas_dir

    def _status(self, now: datetime | None) -> "tuple[bool | None, str]":
        """(done this week, the switch); done is None when AUTO-MAS could not be read."""
        week = week_key(now or datetime.now(tz=SERVER_TZ))
        user = _maa_user(self.automas_dir) if self.automas_dir else {}
        if not user:
            return None, ""
        return (_field(user, "Data", "AnnihilationCompletedWeek") == week,
                _field(user, "Info", "Annihilation"))

    def settings(self, now: datetime | None = None) -> dict:
        """{"本周已完成": True / False, or None when AUTO-MAS could not be read, "当前": the switch}.

        None is not "not done": callers say 读不到 for it (week_line, plan.py)."""
        done, current = self._status(now)
        return {"本周已完成": done, "当前": current}

    def week_line(self, now: datetime | None = None) -> str:
        done, current = self._status(now)
        if done is None:
            return f"{self.NAME}：读不到调度程序记的本周进度"
        if done:
            return f"{self.NAME}：本周已打满，暂停到下周一"
        if current == SWITCH_OFF:
            return f"{self.NAME}：本周还没打满，开关关着，这周不会打"
        return f"{self.NAME}：本周还没打满，开关开着（{current or '读不到'}）"

    def switch_off_line(self, now: datetime | None = None) -> str:
        """The alarm text when the switch is "Close" with no completed week on record; "" otherwise.

        AUTO-MAS never turns Info.Annihilation back on and the relay no longer
        writes it (module docstring), so a switch left off means no annihilation
        this week or any later one. Unreadable (done None) is not this alarm.
        """
        done, current = self._status(now)
        if done is False and current == SWITCH_OFF:
            return texts.annihilation_off_body(self.NAME)
        return ""
