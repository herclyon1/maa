"""The relay's first ERROR of a boot goes to the group, once.

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

import logging
import threading
import time

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


class FirstErrorAlert(logging.Handler):
    """Attach to the "ark" logger; the first record at ERROR or above is pushed as an alarm."""

    def __init__(self, notifier, shutting_down=lambda: False):
        super().__init__(level=logging.ERROR)
        self._notifier = notifier
        self._shutting_down = shutting_down
        self._sent = False
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR or record.name == log.name:
            return
        with self._lock:
            if self._sent:
                return
            if going_down(self._shutting_down):
                return
            self._sent = True
        try:
            what = record.getMessage().splitlines()[0][:160]
        except (TypeError, ValueError, KeyError, IndexError):   # a bad format string or an empty message
            what = str(record.msg)[:160]
        at = time.strftime("%H:%M", time.localtime(record.created))
        body = texts.relay_error_body(record.name, what, at)
        threading.Thread(target=self._push, args=(body,), name="first-error-alert",
                         daemon=True).start()

    def _push(self, body: str) -> None:
        try:
            self._notifier.send(texts.RELAY_ERROR, body, alert=True)
        except Exception:
            log.warning("中继报错的报警没发出去", exc_info=True)


def install(notifier, shutting_down=lambda: False) -> FirstErrorAlert:
    """Hook the handler onto the "ark" logger (every module logs as ark.<name>)."""
    h = FirstErrorAlert(notifier, shutting_down)
    logging.getLogger(ARK).addHandler(h)
    return h
