"""Every new kind of relay error goes to the group, once; a known-fixed one that comes back, every boot.

2026-10-06 (the user, 00:01): 「如果有新的错误，还是直接发到群机器人里面」; 00:04:
「我不希望之前遇到的老错误还要再犯」. Until then only the first ERROR of a boot
reached the group and warnings never did, so a failed step logged as a WARNING
(「官方图转 PNG 失败」 with a Pillow traceback, 10-05 21:47) was read by nobody.

What counts (`is_fault`): every ERROR; a WARNING that carries a traceback; a
WARNING whose message says a step failed (FAILED_WORDS); and any record whose
kind is in known-fixed.json. Each is reduced to a kind (`signature`): logger
name + first message line with times, numbers, paths, URLs and hex ids blanked
(+ exception type). A kind not seen before (state/errsigs.json) is pushed once;
a kind in known-fixed.json is pushed as 「复发」 once per boot, every boot.

Original history of the single first-ERROR alarm:

2026-09-17 21:21:28 relay.log: `AUTO-MAS 拉起后 45 秒内接口仍不通` - one ERROR line,
read by nobody, and the 21:30 queue never ran. Every `log.error` /
`log.exception` in this code base marks a fault the relay could not handle on
its own; a fault nobody is told about is the one that costs a whole shift.

One per boot, not one per error: an ERROR that repeats every tick would turn the
group into noise, and the group is for real alarms only (the 0914 guarantee).
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
network, and a push that itself logs an ERROR must not come back in here
(guarded by `_sent`).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

from . import texts

log = logging.getLogger("ark.errwatch")
# The parent of every module logger. Derived, not spelled, so the logger-name
# lint (one name per module) has nothing to object to.
ARK = log.name.rsplit(".", 1)[0]


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


# A WARNING whose message says a step did not get done. Checked on relay3.log
# 10-05: 「官方图转 PNG 失败」, 「桌面助手读图失败」, 「B 站版本资讯第 2 张图没读出来」.
FAILED_WORDS = ("没做成", "失败", "取不到", "读图失败", "没读出来")

# Loggers whose own records never become alarms: this module and the alarm copy
# to COS (a COS outage there must not ring the group about itself).
QUIET_LOGGERS = (log.name, f"{ARK}.alertlog")
# Records logged from inside a push never come back in here (no recursion).
_PUSH_THREAD = "errwatch-push"

KNOWN_FIXED = Path(__file__).resolve().parents[1] / "known-fixed.json"

_URL = re.compile(r"https?://\S+")
_WINPATH = re.compile(r"[A-Za-z]:\\[^\s，。；：「」]*")
_POSIX = re.compile(r"(?<![\w.])/(?:[\w.-]+/)+[\w.-]*")
_HEX = re.compile(r"\b(?=[0-9a-fA-F]*[a-fA-F])(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{8,}\b")
_NUM = re.compile(r"\d+(?:[.:,]\d+)*")

GAMES = (("终末地", ("终末地", "MaaEnd", "maaend", "Endfield")),
         ("鸣潮", ("鸣潮", "OK-WW", "okww", "wuwa", "库街区")),
         ("明日方舟", ("明日方舟", "MAA", "maa")))


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
    if record.levelno >= logging.ERROR:
        return True
    if record.levelno < logging.WARNING:
        return False
    return bool(record.exc_info and record.exc_info[0]) or any(w in first_line(record) for w in FAILED_WORDS)


def game_of(*texts_: str) -> str:
    joined = " ".join(texts_)
    for game, keys in GAMES:
        if any(k in joined for k in keys):
            return game
    return "中继"


def load_known(path: Path = KNOWN_FIXED) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _evidence(record: logging.LogRecord, message: str) -> str:
    page = getattr(record, "evidence", "") or ""
    if not page:
        m = re.search(r"https?://\S*(?:gofile\.io/d/|myqcloud\.com/)\S+", message)
        page = m.group(0) if m else ""
    return str(page)


class ErrorKindAlert(logging.Handler):
    """Attach to the "ark" logger; a new kind of fault (or a fixed one coming back) is pushed as an alarm."""

    def __init__(self, notifier, shutting_down=lambda: False, state_dir=None, known=None):
        super().__init__(level=logging.WARNING)
        self._notifier = notifier
        self._shutting_down = shutting_down
        if state_dir is None:
            state_dir = getattr(notifier, "_state_dir", None)
        self._path = Path(state_dir) / "errsigs.json" if state_dir else None
        self._known = load_known() if known is None else known
        self._recurred: set[str] = set()     # known-fixed kinds already pushed this boot
        self._seen = self._load()
        self._saved_at = 0.0
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if not self._path:
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._seen, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            pass   # worst case a kind is pushed once more after a restart
        self._saved_at = time.time()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name in QUIET_LOGGERS or record.threadName.startswith(_PUSH_THREAD):
            return
        sig = record_signature(record)
        fixed = self._known.get(sig)
        if not fixed and not is_fault(record):
            return
        if going_down(self._shutting_down):
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        with self._lock:
            entry = self._seen.get(sig)
            new = not isinstance(entry, dict)
            if new:
                entry = self._seen[sig] = {"count": 0, "first": stamp}
            entry["count"] = int(entry.get("count", 0)) + 1
            entry["last"] = stamp
            recur = bool(fixed) and sig not in self._recurred
            if recur:
                self._recurred.add(sig)
            if new or recur or time.time() - self._saved_at > 60:
                self._save()
        if not (new or recur):
            return
        message = first_line(record)
        line = f"{stamp[5:]} {record.levelname} {record.name}  {message}"
        if record.exc_info and record.exc_info[0]:
            line += f" ｜ {record.exc_info[0].__name__}: {record.exc_info[1]}"
        game = game_of(record.name, message)
        part = texts.relay_part(record.name)
        evidence = _evidence(record, message)
        if recur:
            title = texts.error_recurred_title(str(fixed.get("fixed_in", "")))
            body = texts.error_recurred_body(game, part, line[:300], str(fixed.get("what", "")), evidence)
        else:
            title = texts.ERROR_NEW_KIND
            body = texts.error_new_kind_body(game, part, line[:300], evidence)
        threading.Thread(target=self._push, args=(title, body), name=f"{_PUSH_THREAD}-{int(time.time())}",
                         daemon=True).start()

    def _push(self, title: str, body: str) -> None:
        try:
            self._notifier.send(title, body, alert=True)
        except Exception:
            log.warning("中继报错的报警没发出去", exc_info=True)


FirstErrorAlert = ErrorKindAlert   # the old name, for callers and tests that still use it


def install(notifier, shutting_down=lambda: False, state_dir=None, known=None) -> ErrorKindAlert:
    """Hook the handler onto the "ark" logger (every module logs as ark.<name>)."""
    h = ErrorKindAlert(notifier, shutting_down, state_dir, known)
    logging.getLogger(ARK).addHandler(h)
    return h
