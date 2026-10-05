"""Each new kind of relay ERROR goes to the group once; the self-recovered ones go to the daily report.

2026-09-17 21:21:28 relay.log: `AUTO-MAS 拉起后 45 秒内接口仍不通` - one ERROR line,
read by nobody, and the 21:30 queue never ran. Every `log.error` /
`log.exception` in this code base marks a fault the relay could not handle on
its own; a fault nobody is told about is the one that costs a whole shift.
WARNING is the level the code uses for a fault it did handle - it retried,
fell back, or carried on without one part (boot_stages._stage_preupdate:
「WARNING, not ERROR: an ERROR line is a group alarm of its own」; banners.py
09-26). Those are the self-recovered ones: listed in the daily report, never
pushed.

Until 2026-10-06 only the first ERROR of a boot reached the group, so a second,
different fault in the same boot was read by nobody, and warnings were read by
nobody at all (the official-poster PNG conversion failing with a Pillow
traceback, 10-05 21:47). The user, 2026-10-06 00:01, asked for new errors to go
straight to the group robot (「如果有新的错误，还是直接发到群机器人里面」),
and at 00:04 for old errors not to come back unseen (「我不希望之前遇到的老错误还要再犯」).

Every fault record is reduced to a kind (`signature`): the logger name plus the
first message line with times, numbers, paths, URLs and hex ids blanked, plus
the exception type. Then:

* ERROR of a kind never alarmed before (state/errsigs.json, kept across
  restarts): pushed once as 「🩺 中继自己报错了」. The same kind again - this boot or
  any later one - is not pushed; it is counted and listed in the daily report.
* A kind in known_fixed.py (recorded as fixed in an earlier relay version) is
  tagged as a recurrence of a known-fixed fault wherever it shows up. An ERROR
  one is pushed once per (kind, version it was fixed in) under a title of its
  own, even when the kind had been alarmed before the fix.
* WARNING that is a fault (a traceback, a failure word, or a known-fixed kind):
  daily report only.
* Never more than MAX_PER_HOUR pushes from here in any hour (the 2026-09-08
  flood rang the group for half an hour). A kind held back by that cap is not
  marked alarmed, so it is pushed the next time it occurs with room; the daily
  report says it was held.

Suppressed while the machine is going down - the process-watch thread logs an
ERROR when Windows tears its WMI subscription down at shutdown (2026-09-17
10:48:40), which is the machine going away, not a fault. "Going down" is any
of: the relay issued the power-off itself (`engine._shutdown_issued`), the
service was told to stop (`mark_stopping()` from SvcStop, which pywin32 also
calls for SERVICE_CONTROL_SHUTDOWN), or Windows says the session is shutting
down (`GetSystemMetrics(SM_SHUTTINGDOWN)`). The last two were missing on
2026-09-18 02:20: a hand-issued `shutdown /s` set no relay flag, the same WMI
line came, and the group got a 「🩺 中继自己报错了」 for a machine that was
simply being switched off.

The push runs on its own thread: a logging call must never block on the
network, and a record logged from inside that push never comes back in here.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from . import texts

log = logging.getLogger("ark.errwatch")
# The parent of every module logger. Derived, not spelled, so the logger-name
# lint (one name per module) has nothing to object to.
ARK = log.name.rsplit(".", 1)[0]

# Pushes from this handler in any rolling hour.
MAX_PER_HOUR = 3
_HOUR = 3600.0
# A repeat of a known kind rewrites the state files at most this often.
SAVE_EVERY = 30.0
# A WARNING whose message says a step did not get done. Checked against the
# 10-05 relay3.log lines: the PNG conversion of an official poster failing,
# the desktop agent's picture read failing, a news image that was not read.
FAILED_WORDS = ("没做成", "失败", "取不到", "没读出来")
# 🟡 lines are run outcomes the code files for the daily report itself
# (handle.py: MAA short of sanity "is not a failure", an upstream-only miss is
# "daily report, no alarm"); the report already carries them from the ledger.
_RUN_OUTCOME = "🟡"
# Records logged from inside a push never come back in here (no recursion).
_PUSH_THREAD = "errwatch-push"
FILE = "errsigs.json"
DAY_DIR = "errkinds"

_URL = re.compile(r"https?://\S+")
_WINPATH = re.compile(r"[A-Za-z]:\\[^\s，。；：「」]*")
_POSIX = re.compile(r"(?<![\w.])/(?:[\w.-]+/)+[\w.-]*")
_HEX = re.compile(r"\b(?=[0-9a-fA-F]*[a-fA-F])(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{8,}\b")
_NUM = re.compile(r"\d+(?:[.:,]\d+)*")


# GetSystemMetrics index: nonzero while the current session is shutting down.
SM_SHUTTINGDOWN = 0x2000
_stopping = threading.Event()


def mark_stopping() -> None:
    """The service has been told to stop (a stop, or Windows shutting down): from here on an ERROR is not a fault."""
    _stopping.set()


def system_shutting_down() -> bool:
    """True while Windows reports the session is going down; False where that cannot be asked (a Mac, a test)."""
    try:
        import win32api  # noqa: PLC0415
        return bool(win32api.GetSystemMetrics(SM_SHUTTINGDOWN))
    except Exception:  # noqa: BLE001 - not on Windows, or the call itself failed
        return False


def going_down(extra=lambda: False) -> bool:
    """Any of the three signs that the machine is on its way down."""
    if _stopping.is_set() or system_shutting_down():
        return True
    try:
        return bool(extra())
    except Exception:  # noqa: BLE001 - a broken probe must not stop the alarm
        return False


# ---------- what kind of fault a record is ----------

def first_line(record: logging.LogRecord) -> str:
    try:
        text = record.getMessage()
    except (TypeError, ValueError, KeyError, IndexError):   # a bad format string
        text = str(record.msg)
    return (text.splitlines() or [""])[0].strip()


def strip_variable(text: str) -> str:
    """The message with what differs every time (times, numbers, paths, URLs, hex ids) blanked."""
    s = _URL.sub("<url>", text)
    s = _WINPATH.sub("<path>", s)
    s = _POSIX.sub("<path>", s)
    s = _HEX.sub("<id>", s)
    s = _NUM.sub("#", s)
    return " ".join(s.split())[:200]


def signature(name: str, message: str, exc_type: str = "") -> str:
    sig = f"{name}|{strip_variable(message)}"
    return f"{sig}|{exc_type}" if exc_type else sig


def record_signature(record: logging.LogRecord) -> str:
    exc = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else ""
    return signature(record.name, first_line(record), exc)


def is_fault(record: logging.LogRecord) -> bool:
    """ERROR and above always; a WARNING with a traceback or a failure word."""
    if record.levelno >= logging.ERROR:
        return True
    if record.levelno < logging.WARNING:
        return False
    line = first_line(record)
    if line.startswith(_RUN_OUTCOME):
        return False
    return bool(record.exc_info and record.exc_info[0]) or any(w in line for w in FAILED_WORDS)


def _version_int(v) -> int:
    try:
        return int(str(v or "").strip().lstrip("v") or 0)
    except ValueError:
        return 0


def fixed_entry(sig: str, known: dict, running: str = "") -> dict:
    """The known-fixed record for `sig` when it applies to the running code, else {}.

    It applies unless the running version is known and older than the fix (the
    registry ships with the code, so an unknown running version has the fix)."""
    ent = known.get(sig)
    if not isinstance(ent, dict):
        return {}
    run, fixed = _version_int(running), _version_int(ent.get("fixed_in"))
    if run and fixed and run < fixed:
        return {}
    return ent


# ---------- the handler ----------

class ErrorKindAlert(logging.Handler):
    """Attach to the "ark" logger: new ERROR kinds to the group, self-recovered faults to the daily report."""

    def __init__(self, notifier, shutting_down=lambda: False, state_dir=None, known=None,
                 version=None, clock=time.time):
        super().__init__(level=logging.WARNING)
        self._notifier = notifier
        self._shutting_down = shutting_down
        if state_dir is None:
            state_dir = getattr(notifier, "_state_dir", None)
        self._dir = Path(state_dir) if state_dir else None
        if known is None:
            from .known_fixed import KNOWN  # noqa: PLC0415
            known = KNOWN
        self._known = known
        self._version = version        # callable -> running code version, or None
        self._clock = clock
        self._seen = self._read(self._dir / FILE) if self._dir else {}
        self._days: dict[str, dict] = {}
        self._saved_at = 0.0
        self._pushed: list[float] = []  # times of this handler's pushes (the hourly cap)
        self._lock = threading.Lock()

    # -- state --
    @staticmethod
    def _read(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _write(path: Path, data) -> None:
        try:
            from .config import atomic_write_text  # noqa: PLC0415
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))
        except OSError:
            pass   # worst case a kind is pushed once more after a restart

    def _day(self, day: str) -> dict:
        if day not in self._days:
            self._days = {day: self._read(self._dir / DAY_DIR / f"{day}.json") if self._dir else {}}
        return self._days[day]

    def _running(self) -> str:
        try:
            return str(self._version() or "") if self._version else ""
        except Exception:  # noqa: BLE001 - an unreadable version only loses the version check
            return ""

    def _room(self, now: float) -> bool:
        self._pushed = [t for t in self._pushed if now - t < _HOUR]
        return len(self._pushed) < MAX_PER_HOUR

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == log.name or record.threadName.startswith(_PUSH_THREAD):
            return
        sig = record_signature(record)
        fixed = fixed_entry(sig, self._known, self._running())
        if not fixed and not is_fault(record):
            return
        if going_down(self._shutting_down):
            return
        try:
            self._handle(record, sig, fixed)
        except Exception:  # noqa: BLE001 - a logging handler must never raise into the caller
            super().handleError(record)

    def _handle(self, record: logging.LogRecord, sig: str, fixed: dict) -> None:
        from .config import SERVER_TZ  # noqa: PLC0415
        now = self._clock()
        when = datetime.fromtimestamp(record.created, tz=SERVER_TZ)
        stamp = when.strftime("%Y-%m-%d %H:%M:%S")
        line = first_line(record)
        if record.exc_info and record.exc_info[0]:
            line += f" ｜ {record.exc_info[0].__name__}: {record.exc_info[1]}"
        fixed_key = f"fixed:{fixed.get('fixed_in', '')}" if fixed else ""
        push = ""
        with self._lock:
            ent = self._seen.get(sig)
            fresh = not isinstance(ent, dict)
            if fresh:
                ent = self._seen[sig] = {"first": stamp, "count": 0}
            ent["count"] = int(ent.get("count", 0)) + 1
            ent["last"] = stamp
            if record.levelno >= logging.ERROR:
                due = (ent.get("recurred") != fixed_key) if fixed_key else not ent.get("alarmed")
                if due and self._room(now):
                    self._pushed.append(now)
                    push = "recur" if fixed_key else "new"
                    ent["alarmed"] = True
                    if fixed_key:
                        ent["recurred"] = fixed_key
                elif due:
                    push = "held"
            day = self._day(when.strftime("%Y-%m-%d"))
            row = day.get(sig)
            if not isinstance(row, dict):
                fresh = True
                row = day[sig] = {"first": stamp, "count": 0}
            row["count"] = int(row.get("count", 0)) + 1
            row.update(last=stamp, level=record.levelname, where=record.name, line=line[:200])
            if push in ("new", "recur"):
                row["pushed"] = True
                row.pop("held", None)
            elif push == "held" and not row.get("pushed"):
                row["held"] = True
            if fixed:
                row["fixed_in"] = str(fixed.get("fixed_in", ""))
            if self._dir and (fresh or push or now - self._saved_at >= SAVE_EVERY):
                self._write(self._dir / FILE, self._seen)
                self._write(self._dir / DAY_DIR / f"{when.strftime('%Y-%m-%d')}.json", day)
                self._saved_at = now
        if push not in ("new", "recur"):
            return
        at = stamp[11:16]
        if push == "recur":
            title = texts.relay_error_recurred(str(fixed.get("fixed_in", "")))
            body = texts.relay_error_recurred_body(record.name, line[:300], at, str(fixed.get("what", "")))
        else:
            title = texts.RELAY_ERROR
            body = texts.relay_error_body(record.name, line[:160], at)
        threading.Thread(target=self._push, args=(title, body), name=f"{_PUSH_THREAD}-{int(now)}",
                         daemon=True).start()

    def _push(self, title: str, body: str) -> None:
        try:
            self._notifier.send(title, body, alert=True)
        except Exception:
            log.warning("中继报错的报警没发出去", exc_info=True)


FirstErrorAlert = ErrorKindAlert   # the old name


def install(notifier, shutting_down=lambda: False, state_dir=None, known=None, version=None) -> ErrorKindAlert:
    """Hook the handler onto the "ark" logger (every module logs as ark.<name>)."""
    h = ErrorKindAlert(notifier, shutting_down, state_dir, known, version)
    logging.getLogger(ARK).addHandler(h)
    return h


def day_faults(state_dir, day: str) -> list[dict]:
    """The day's fault kinds, oldest first: [{where, line, count, level, pushed, held, fixed_in, ...}]."""
    if not state_dir:
        return []
    data = ErrorKindAlert._read(Path(state_dir) / DAY_DIR / f"{day}.json")
    return sorted((r for r in data.values() if isinstance(r, dict)), key=lambda r: str(r.get("first", "")))


def daily_section(state_dir, day: str) -> str:
    """The daily report's lines on the relay's own faults that day, '' when none."""
    return texts.relay_faults_section(day_faults(state_dir, day))
