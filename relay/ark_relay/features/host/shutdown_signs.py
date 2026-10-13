"""Is the machine going down? The relay's own power-off (errwatch) and the System log's 1074 / 1075, so an exit or a dropped listener that a shutdown explains is not pushed as a fault.

Split out of relay/service.py (2026-10-11); behaviour unchanged.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from ark_relay.core.config import SERVER_TZ


# How long a failure that a shutdown would also explain - the process-start
# listener dropping, the AUTO-MAS backend exiting - waits for a sign that the
# machine is going down before it is logged as a fault. On a shutdown Windows
# closes the logged-on session and tells services to stop in no fixed order with
# each other or with WMI going down (2026-10-10 04:28 the AUTO-MAS exit came ~16 s
# before the stop notice; in the ten Windows-shutdown stops from 10-10 23:31 to
# 10-13 11:14 the stop notice came first), so either can reach us before any flag
# (errwatch.going_down) is set. The first sign ends the wait at once; no sign at
# all means it was not a shutdown, and it is logged as the fault it is.
GOING_DOWN_SETTLE_SECONDS = 15.0


# A System-log 1074 ("shutdown requested") this recent, with no 1075 ("aborted") after it,
# means an AUTO-MAS exit is the shutdown's doing. 2026-10-10: `shutdown /s /t 60` by hand
# wrote its 1074 at 04:27:24 (machine clock), AUTO-MAS exited ~04:28:29, the stop notice
# came 04:28:45; the relay's own power-offs of 10-09 21:41:51 / 21:49:11 wrote one too
# (docs/OPERATIONS.md, the 6005 / 6006 / 1074 check).
SHUTDOWN_EVENT_WINDOW_SECONDS = 120


_EVT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"


_SETTLE_STEP = 0.5


def _going_down_soon(seconds: "float | None" = None) -> bool:
    """True when the relay ITSELF has issued the machine power-off, now or within `seconds`.

    The only case where a dropped WMI link or AUTO-MAS exiting is logged at INFO
    instead of being pushed (the user, 2026-10-06: only the planned power-off the
    relay started may stay out of the group). A shutdown by hand, `sc stop` or
    Windows' own shutdown is NOT that: errwatch.relay_shutdown_issued() is false
    for them, so the event is a WARNING/ERROR and reaches the group.
    """
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    if seconds is None:
        seconds = GOING_DOWN_SETTLE_SECONDS
    deadline = time.monotonic() + seconds
    while not errwatch.relay_shutdown_issued():
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        time.sleep(min(_SETTLE_STEP, left))
    return True


def _down_reason() -> str:
    """The words the log line uses for the relay's own power-off."""
    return "中继自己发出了关机命令"


def _shutdown_event_xml(window_s: int = SHUTDOWN_EVENT_WINDOW_SECONDS) -> "list[str] | None":
    """The System log's 1074 / 1075 events of the last `window_s` seconds, newest first, as
    event XML; None when it cannot be read (ark_relay.features.shutdown.shutdown.shutdown_event_xml)."""
    from ark_relay.features.shutdown import shutdown  # noqa: PLC0415
    return shutdown.shutdown_event_xml(window_s)


def shutdown_requested(xmls: "list[str]") -> "dict | None":
    """From 1074 / 1075 event XML, newest first: the shutdown request still standing, or None.

    1074 (User32): "The process <param1> has initiated the power off of computer ... on
    behalf of user <param7>"; 1075: that shutdown was aborted. The newest of the two
    decides. Returns {"clock": HH:MM:SS on the relay's clock, "process": ..., "user": ...}."""
    import xml.etree.ElementTree as ET  # noqa: PLC0415
    for x in xmls:
        try:
            ev = ET.fromstring(x)
        except ET.ParseError:
            continue
        eid = (ev.findtext(f"{_EVT_NS}System/{_EVT_NS}EventID") or "").strip()
        if eid == "1075":
            return None
        if eid != "1074":
            continue
        data = [d.text or "" for d in ev.iter(f"{_EVT_NS}Data")]
        stamp = ev.find(f"{_EVT_NS}System/{_EVT_NS}TimeCreated")
        clock, when = "", None
        if stamp is not None and stamp.get("SystemTime"):
            raw = stamp.get("SystemTime").rstrip("Z")
            head = raw.split(".")[0]
            try:
                when = datetime.fromisoformat(head).replace(tzinfo=timezone.utc)
                clock = when.astimezone(SERVER_TZ).strftime("%H:%M:%S")
            except ValueError:
                clock, when = "", None
        return {"clock": clock, "at": when, "process": data[0] if data else "",
                "user": data[6] if len(data) > 6 else ""}
    return None


# A power-off request logged up to this long after the drop began still counts as
# before it: the 1074 stamp and the monotonic drop time are read on different clocks.
SHUTDOWN_BEFORE_SLACK_SECONDS = 2


# How far back the 1074 is looked for: `shutdown -s -t N` is logged when given, N earlier.
SHUTDOWN_BEFORE_WINDOW_SECONDS = 3600


def _shutdown_before(since_mono: float) -> "dict | None":
    """The standing Windows power-off request (shutdown_requested) when Windows is shutting
    down (SvcShutdown ran) and the request was logged before the moment `since_mono`
    (time.monotonic()); else None. Unreadable System log -> None, so the caller pushes."""
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    if not errwatch.os_shutdown():
        return None
    xmls = _shutdown_event_xml(SHUTDOWN_BEFORE_WINDOW_SECONDS)
    asked = shutdown_requested(xmls) if xmls else None
    if asked is None or asked.get("at") is None:
        return None
    began = datetime.now(tz=timezone.utc) - timedelta(seconds=time.monotonic() - since_mono)
    return asked if asked["at"] <= began + timedelta(seconds=SHUTDOWN_BEFORE_SLACK_SECONDS) else None
