"""Every WARNING and ERROR the relay logs goes to the group, every time, at once.

2026-09-17 21:21:28 relay.log: `AUTO-MAS 拉起后 45 秒内接口仍不通` - one ERROR line,
read by nobody, and the 21:30 queue never ran. A fault nobody is told about is
the one that costs a whole shift.

Until 2026-10-06 each kind of ERROR reached the group once (kinds kept in
state/errsigs.json), a repeat was only counted, WARNINGs ("self-recovered") went
to the daily report only, at most 3 pushes an hour left here, and nothing was
said while the machine was going down. The user replaced all of that on
2026-10-06 (his full words are in docs/NOTIFICATIONS.md, the 🩺 row), ending with
the rule itself, 「不论多少次什么错误都要发」 - any error, however often. So now:

* every WARNING / ERROR record of an ark.* logger is pushed to the group, each
  occurrence, as soon as it is logged;
* a kind known_fixed.py records as fixed is pushed under its own title, as a
  recurrence (「复发」), each time;
* a record may carry its own title and body (`extra=alarm(title, body)`): the
  annihilation switch and the Skland role refusal use it;
* a record that only repeats an alarm its caller already delivered to the group
  carries `extra=group_pushed(title, errs, notifier)` and is not pushed again - set
  only when that push really went out, never inferred from the text;
* each push goes to the group robot alone (`notifier.send_group`) when one is
  configured. Nothing is dropped: what the robot refuses (rate limit, network)
  stays queued on disk (state/errwatch-queue.json, so a restart does not lose
  it) and is sent again later. Only a record the robot has refused for
  FALLBACK_AFTER_S goes the way of every other group alarm, robot first and
  Server酱 when the robot still refuses (notify.py: an alarm must arrive), and
  stays queued if that fails too. Once the queue has backed up (a refusal, or
  BACKLOG records waiting) the waiting records go out merged, as many as fit in
  one group message, and identical waiting ones become one line with their
  count and first / last time. Otherwise each record is a push of its own;
* records logged from inside the push path (the push thread, and the alarm-copy
  thread it starts) never come back in here, or a failing channel would feed
  itself;
* the machine going down is no reason to keep quiet: the user does not want the
  WMI teardown at shutdown hidden from the group (the service logs that line at
  INFO itself when it knows the machine is going down). `mark_stopping()` and
  `going_down()` stay: service.py, shutdown.py and boot_stages.py use them.

The day's records are also counted per kind in state/errkinds/<day>.json for the
daily report's section 「中继自己记下的报错」.

Each push runs on the push thread: a logging call never blocks on the network.
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

# LogRecord attributes (set through `extra=`).
PUSHED = "ark_group_pushed"     # the caller already delivered this to the group
RECOVERED = "ark_recovered"     # the relay recovered from this by itself: daily report only
ALARM = "ark_alarm"             # (title, body) to push instead of the generic text
# Threads of the push path; a record logged on one of them is never pushed.
PUSH_THREAD = "errwatch-push"
QUEUE_FILE = "errwatch-queue.json"
DAY_DIR = "errkinds"
# Between two pushes from here: the group robot takes at most 20 messages a
# minute, and this handler must not use them all up on its own.
PACE_S = 3.0
# Waits after the group refused, one after another; the last one repeats.
RETRY_S = (30.0, 60.0, 120.0, 300.0, 600.0)
# A record the robot has refused this long goes out the usual alarm way (robot,
# then Server酱) rather than wait for the robot alone.
FALLBACK_AFTER_S = 600.0
ROBOT = "企业微信机器人"           # notify.Notifier.channels name of the group robot
# This many records waiting at once and they go out merged.
BACKLOG = 10
# A merged push stays one group robot message (notify.WeComBot._LIMIT is 1800).
BATCH_BYTES = 1700
# The day file of counts is rewritten at most this often for a repeat.
SAVE_EVERY = 30.0

_URL = re.compile(r"https?://\S+")
_WINPATH = re.compile(r"[A-Za-z]:\\[^\s，。；：「」]*")
_POSIX = re.compile(r"(?<![\w.])/(?:[\w.-]+/)+[\w.-]*")
_HEX = re.compile(r"\b(?=[0-9a-fA-F]*[a-fA-F])(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{8,}\b")
_NUM = re.compile(r"\d+(?:[.:,]\d+)*")


# GetSystemMetrics index: nonzero while the current session is shutting down.
SM_SHUTTINGDOWN = 0x2000
_stopping = threading.Event()


def mark_stopping() -> None:
    """The service has been told to stop (a stop, or Windows shutting down)."""
    _stopping.set()


def system_shutting_down() -> bool:
    """True while Windows reports the session is going down; False where that cannot be asked (a Mac, a test)."""
    try:
        import win32api  # noqa: PLC0415
        return bool(win32api.GetSystemMetrics(SM_SHUTTINGDOWN))
    except Exception:  # noqa: BLE001 - not on Windows, or the call itself failed
        return False


# Set by install(): answers whether the relay itself has issued the machine
# power-off and it is still under way (boot_stages._relay_poweroff_live).
_relay_poweroff = [lambda: False]
# Set by install(): the installed handler, so service.py can drain its push
# thread before the hard exit (see drain()).
_handler = [None]
# Set by boot_stages (set_evidence_uploader): uploads today's relay.log to COS so
# a relay-error push can end with 「日志：<链接>，出事时刻 HH:MM」 (error_evidence.py).
# Returns a dict like error_evidence.upload_daily_logs does.
_evidence_uploader = [None]


def set_evidence_uploader(fn) -> None:
    """The callable errwatch runs once per push (throttled inside) to get today's
    log URL; boot_stages wires it to error_evidence.upload_daily_logs(cfg)."""
    _evidence_uploader[0] = fn


def relay_shutdown_issued() -> bool:
    """True only while the power-off the relay itself issued is under way.

    The one case a fault-shaped event may stay out of the group (the user,
    2026-10-06): the planned power-off teardown of a shutdown the relay started.
    A shutdown issued by hand, `sc stop`, or Windows' own shutdown does not count
    - those still push (going_down() covers all of them and is NOT that test)."""
    try:
        return bool(_relay_poweroff[0]())
    except Exception:  # noqa: BLE001 - a broken probe answers "not ours", so it pushes
        return False


def going_down(extra=lambda: False) -> bool:
    """Any of the three signs that the machine is on its way down."""
    if _stopping.is_set() or system_shutting_down():
        return True
    try:
        return bool(extra())
    except Exception:  # noqa: BLE001 - a broken probe answers "not going down"
        return False


# ---------- what callers put on a record ----------

def alarm(title: str, body: str) -> dict:
    """`extra=` for a log call whose push needs its own title and body."""
    return {ALARM: (str(title), str(body))}


def recovered() -> dict:
    """`extra=` for a WARNING about a fault the relay has already recovered from by
    itself (a retry, a make-up or a reconnect that then worked): it goes to the daily
    report's 「中继自己记下的报错」 tagged 自己好了, and is NOT pushed to the group.

    The user's rule of 2026-10-06 05:07 (quoted in full in relay/USER-SWITCHES.txt):
    what fixed itself goes to the daily report only (「只进日报、不进群」). Only for what already recovered: a
    fault that is still there is a plain WARNING / ERROR and is pushed every time.
    Every caller is listed in relay/USER-SWITCHES.txt (tests/test_user_switches.py)."""
    return {RECOVERED: True}


def group_pushed(title: str, errs, notifier=None) -> dict:
    """`extra=` for a log call that repeats an alarm the caller has just sent with
    `notifier.send(title, ..., alert=True)` on this thread: {PUSHED: True} only when
    that send returned no errors, the title takes the group route and - when the
    notifier can tell (notify.Notifier.went_to_group) - the group robot took it
    rather than Server酱; {} otherwise, so the record is pushed from here like any
    other."""
    from .notify import route_of  # noqa: PLC0415
    if errs or route_of(title, alert=True) != "group":
        return {}
    asked = getattr(notifier, "went_to_group", None)
    if callable(asked) and not asked():
        return {}
    return {PUSHED: True}


def in_push_path() -> bool:
    """True on a thread of the push path (alertlog names its copy thread from this)."""
    return threading.current_thread().name.startswith(PUSH_THREAD)


# ---------- what kind of record it is ----------

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


# ---------- what a queued item says ----------

def _clock_part(stamp: str) -> str:
    """「21:21:05」 for today (server clock), 「10-05 21:21:05」 for an earlier day."""
    from .config import SERVER_TZ  # noqa: PLC0415
    stamp = str(stamp or "")
    if stamp[:10] == datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"):
        return stamp[11:19]
    return f"{stamp[5:10]} {stamp[11:19]}".strip()


def span(item: dict) -> str:
    """When: 「21:21:05」, or 「21:21:05 起共 3 次，最后一次 21:25:10」 for merged ones."""
    n = int(item.get("n") or 1)
    first = _clock_part(item.get("first", ""))
    return f"{first} 起共 {n} 次，最后一次 {_clock_part(item.get('last', ''))}" if n > 1 else first


def render(item: dict) -> tuple[str, str]:
    """(title, body) of one queued item pushed on its own."""
    at = span(item)
    if item.get("body") is not None:
        return item["title"], f"{item['body']}\n（{at}）"
    if item.get("fixed_in") is not None:
        return item["title"], texts.relay_error_recurred_body(item.get("where", ""), item.get("line", ""), at,
                                                              item.get("fixed_what", ""))
    return item["title"], texts.relay_error_body(item.get("where", ""), item.get("line", ""), at)


def merge(items: list[dict]) -> tuple[str, str]:
    """One push for one or several queued items."""
    if len(items) == 1:
        return render(items[0])
    titles = [x["title"] for x in items]
    title = texts.relay_errors_merged(titles[0] if len(set(titles)) == 1 else texts.RELAY_ERROR, len(items))
    parts, generic = [], False
    for x in items:
        if x.get("body") is not None:
            t, b = render(x)
            parts.append(f"【{t}】\n{b}")
        else:
            generic = True
            parts.append(texts.relay_error_line(x.get("where", ""), x.get("line", ""), span(x),
                                                x.get("fixed_in") or "", x.get("fixed_what") or ""))
    body = "\n".join(parts)
    return title, body + ("\n" + texts.RELAY_ERROR_TAIL if generic else "")


# ---------- the handler ----------

class ErrorKindAlert(logging.Handler):
    """Attach to the "ark" logger: every WARNING / ERROR record to the group, nothing dropped.

    `shutting_down` is accepted for the callers that still pass it and is not
    used: going down no longer keeps a record from the group."""

    def __init__(self, notifier, shutting_down=lambda: False, state_dir=None, known=None,
                 version=None, clock=time.time, pace=PACE_S, retry=RETRY_S, fallback_after=FALLBACK_AFTER_S):
        super().__init__(level=logging.WARNING)
        self._notifier = notifier
        if state_dir is None:
            state_dir = getattr(notifier, "_state_dir", None)
        self._dir = Path(state_dir) if state_dir else None
        if known is None:
            from .known_fixed import KNOWN  # noqa: PLC0415
            known = KNOWN
        self._known = known
        self._version = version        # callable -> running code version, or None
        self._clock = clock
        self._pace = float(pace)
        self._retry = tuple(retry) or RETRY_S
        self._fallback_after = float(fallback_after)
        self._cv = threading.Condition()
        self._queue: list[dict] = self._read_queue()
        self._inflight = 0             # items at the head of the queue being sent now
        self._refused = bool(self._queue)   # left over from before a restart: merge them
        self._days: dict[str, dict] = {}
        self._saved_at = 0.0
        self._closed = False
        self._sender: threading.Thread | None = None
        if self._queue:
            with self._cv:
                self._start()

    # -- files --
    @staticmethod
    def _read(path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _write(path: Path, data) -> None:
        try:
            from .config import atomic_write_text  # noqa: PLC0415
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))
        except OSError:
            pass   # still in memory; only a restart right now would lose it

    def _read_queue(self) -> list[dict]:
        data = self._read(self._dir / QUEUE_FILE) if self._dir else None
        return [x for x in data if isinstance(x, dict) and x.get("title")] if isinstance(data, list) else []

    def _save_queue(self) -> None:
        if self._dir:
            self._write(self._dir / QUEUE_FILE, self._queue)

    def _day(self, day: str) -> dict:
        if day not in self._days:
            got = self._read(self._dir / DAY_DIR / f"{day}.json") if self._dir else None
            self._days = {day: got if isinstance(got, dict) else {}}
        return self._days[day]

    def _save_day(self, day: str) -> None:
        if self._dir:
            self._write(self._dir / DAY_DIR / f"{day}.json", self._day(day))
            self._saved_at = self._clock()

    def _running(self) -> str:
        try:
            return str(self._version() or "") if self._version else ""
        except Exception:  # noqa: BLE001 - an unreadable version only loses the version check
            return ""

    # -- taking records in --
    def emit(self, record: logging.LogRecord) -> None:
        if (record.name == log.name or record.threadName.startswith(PUSH_THREAD)
                or getattr(record, PUSHED, False)):
            return
        try:
            if getattr(record, RECOVERED, False):
                self._note_recovered(record)
                return
            self._take(record)
        except Exception:  # noqa: BLE001 - a logging handler must never raise into the caller
            super().handleError(record)

    def _item(self, record: logging.LogRecord, sig: str, stamp: str) -> dict:
        line = first_line(record)
        if record.exc_info and record.exc_info[0]:
            line += f" ｜ {record.exc_info[0].__name__}: {record.exc_info[1]}"
        given = getattr(record, ALARM, None)
        if isinstance(given, (tuple, list)) and len(given) == 2:
            item = {"title": str(given[0]), "body": str(given[1])}
        elif fixed := fixed_entry(sig, self._known, self._running()):
            item = {"title": texts.relay_error_recurred(str(fixed.get("fixed_in", ""))),
                    "where": record.name, "line": line[:300],
                    "fixed_in": str(fixed.get("fixed_in", "")), "fixed_what": str(fixed.get("what", ""))}
        else:
            item = {"title": texts.RELAY_ERROR, "where": record.name, "line": line[:160]}
        item["key"] = json.dumps([item.get(k) for k in ("title", "body", "where", "line")], ensure_ascii=False)
        item.update(sig=sig, first=stamp, last=stamp, n=1, t=record.created)
        return item

    def _backlog(self) -> bool:
        return self._refused or len(self._queue) - self._inflight >= BACKLOG

    def _take(self, record: logging.LogRecord) -> None:
        from .config import SERVER_TZ  # noqa: PLC0415
        when = datetime.fromtimestamp(record.created, tz=SERVER_TZ)
        stamp = when.strftime("%Y-%m-%d %H:%M:%S")
        sig = record_signature(record)
        item = self._item(record, sig, stamp)
        with self._cv:
            same = None
            if self._backlog():
                same = next((x for x in self._queue[self._inflight:] if x.get("key") == item["key"]), None)
            if same is not None:
                same["n"] = int(same.get("n") or 1) + 1
                same["last"] = stamp
            else:
                self._queue.append(item)
            self._save_queue()
            self._count(when.strftime("%Y-%m-%d"), sig, record, item, stamp)
            self._cv.notify_all()
            self._start()

    def _note_recovered(self, record: logging.LogRecord) -> None:
        """A fault the relay recovered from by itself: counted for the daily report, never pushed."""
        from .config import SERVER_TZ  # noqa: PLC0415
        when = datetime.fromtimestamp(record.created, tz=SERVER_TZ)
        stamp = when.strftime("%Y-%m-%d %H:%M:%S")
        sig = record_signature(record)
        with self._cv:
            day = when.strftime("%Y-%m-%d")
            self._count(day, sig, record, {}, stamp)
            self._day(day)[sig]["recovered"] = True
            self._save_day(day)

    def _count(self, day: str, sig: str, record: logging.LogRecord, item: dict, stamp: str) -> None:
        rows = self._day(day)
        row = rows.get(sig)
        fresh = not isinstance(row, dict)
        if fresh:
            row = rows[sig] = {"first": stamp, "count": 0, "pushed": 0}
        row["count"] = int(row.get("count") or 0) + 1
        row.update(last=stamp, level=record.levelname, where=record.name, line=first_line(record)[:200])
        if item.get("fixed_in") is not None:
            row["fixed_in"] = item["fixed_in"]
        if fresh or self._clock() - self._saved_at >= SAVE_EVERY:
            self._save_day(day)

    # -- sending --
    def _start(self) -> None:
        """Start the push thread unless it is running (called with the lock held)."""
        if self._closed or (self._sender is not None and self._sender.is_alive()):
            return
        self._sender = threading.Thread(target=self._run, name=PUSH_THREAD, daemon=True)
        self._sender.start()

    def _batch(self) -> list[dict]:
        """The next push: the head item alone, or once backed up, as many as fit in one message."""
        if not self._backlog():
            return self._queue[:1]
        out, size = [], 0
        for item in self._queue:
            t, b = render(item)
            n = len(f"【{t}】\n{b}\n".encode("utf-8"))
            if out and size + n > BATCH_BYTES:
                break
            out.append(item)
            size += n
        return out

    def _run(self) -> None:
        tries = 0
        while True:
            with self._cv:
                while not self._queue and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
                batch = self._batch()
                self._inflight = len(batch)
            title, body = merge(batch)
            waited = self._clock() - min(float(x.get("t") or 0) for x in batch)
            body = self._attach_evidence(body, batch)
            try:
                errs = self._deliver(title, body, waited)
            except Exception as exc:  # noqa: BLE001 - kept queued, tried again
                errs = [f"{type(exc).__name__}: {exc}"]
            with self._cv:
                self._inflight = 0
                if errs:
                    self._refused = True
                    wait = self._retry[min(tries, len(self._retry) - 1)]
                    tries += 1
                else:
                    del self._queue[:len(batch)]
                    self._delivered(batch)
                    self._refused = False
                    tries, wait = 0, self._pace
                self._save_queue()
            if errs:
                log.warning("报错没推到群里，%d 条留着，%.0f 秒后再推：%s", len(batch), wait, "；".join(errs))
            time.sleep(wait)

    def _deliver(self, title: str, body: str, waited: float) -> list:
        """The group robot alone while it is configured and the batch has not waited
        FALLBACK_AFTER_S; otherwise the usual alarm route. -> errors ([] = delivered)."""
        group = getattr(self._notifier, "send_group", None)
        if group is not None and ROBOT in (getattr(self._notifier, "channels", None) or ()) \
                and waited < self._fallback_after:
            return group(title, body)
        return self._notifier.send(title, body, alert=True)

    def _delivered(self, batch: list[dict]) -> None:
        days: set[str] = set()
        for item in batch:
            day = str(item.get("first", ""))[:10]
            row = self._day(day).get(item.get("sig"))
            if isinstance(row, dict):
                row["pushed"] = int(row.get("pushed") or 0) + int(item.get("n") or 1)
                days.add(day)
        for day in days:
            self._save_day(day)

    def _attach_evidence(self, body: str, batch: list[dict]) -> str:
        """Append 「日志：<链接>，出事时刻 HH:MM」 when today's relay.log upload landed
        before the push; a failed upload is noted for the daily report and the push
        goes out as-is (the user, 2026-10-06: 上传失败不挡推送)."""
        up = _evidence_uploader[0]
        if up is None:
            return body
        try:
            got = up()
        except Exception as exc:  # noqa: BLE001 - an upload must never hold the push
            got = {"errors": [f"{type(exc).__name__}: {exc}"], "url": ""}
        if not isinstance(got, dict):
            got = {}
        if got.get("url"):
            from .config import SERVER_TZ  # noqa: PLC0415
            when = datetime.fromtimestamp(min(float(x.get("t") or 0) for x in batch),
                                          tz=SERVER_TZ).strftime("%H:%M")
            return body + "\n" + texts.evidence_link(got["url"], when, bool(got.get("truncated")))
        for e in got.get("errors") or []:
            self.note_daily("ark.evidence", f"证据上传失败：{e}")
        return body

    def note_daily(self, where: str, line: str) -> None:
        """A line for the daily report's 「中继自己记下的报错」 that must not be pushed
        (an evidence upload that failed while the push itself went ahead). Logging
        it as a WARNING would not reach here - the push thread's records never come
        back in - so the day file is written directly, tagged daily-only."""
        from .config import SERVER_TZ  # noqa: PLC0415
        now = datetime.fromtimestamp(self._clock(), tz=SERVER_TZ)
        day = now.strftime("%Y-%m-%d")
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        sig = signature(where, line)
        with self._cv:
            row = self._day(day).get(sig)
            if not isinstance(row, dict):
                row = self._day(day)[sig] = {"first": stamp, "count": 0, "pushed": 0}
            row["count"] = int(row.get("count") or 0) + 1
            row.update(last=stamp, level="WARNING", where=where, line=line[:200], daily_only=True)
            self._save_day(day)

    def pending(self) -> list[dict]:
        """What is waiting to go out (copies)."""
        with self._cv:
            return [dict(x) for x in self._queue]

    def drain(self, timeout: float = 3.0) -> None:
        """Wait for the push thread to deliver everything queued or in flight, then
        persist the queue once more.

        The hard exit (service.py SvcDoRun's os._exit) kills the push thread without
        waiting; a batch it had just delivered to the group could still be on disk
        and would be re-sent at the next boot. 2026-10-06 06:21:36 did exactly that
        and came back at 08:45. Called on the main thread before the exit."""
        deadline = self._clock() + timeout
        with self._cv:
            while (self._queue or self._inflight) and not self._closed \
                    and self._clock() < deadline:
                self._cv.wait(timeout=max(0.0, min(0.1, deadline - self._clock())))
            self._save_queue()

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()
        super().close()


FirstErrorAlert = ErrorKindAlert   # the old name


def install(notifier, shutting_down=lambda: False, state_dir=None, known=None, version=None) -> ErrorKindAlert:
    """Hook the handler onto the "ark" logger (every module logs as ark.<name>)."""
    h = ErrorKindAlert(notifier, shutting_down, state_dir, known, version)
    _relay_poweroff[0] = shutting_down
    _handler[0] = h
    logging.getLogger(ARK).addHandler(h)
    return h


def drain(timeout: float = 3.0) -> None:
    """service.py calls this right before the hard exit: let the push thread deliver
    and persist, so nothing the group already got is re-sent at boot."""
    h = _handler[0]
    if h is not None:
        h.drain(timeout)


def day_faults(state_dir, day: str) -> list[dict]:
    """The day's record kinds, oldest first: [{where, line, count, pushed, level, fixed_in, ...}]."""
    if not state_dir:
        return []
    data = ErrorKindAlert._read(Path(state_dir) / DAY_DIR / f"{day}.json")
    if not isinstance(data, dict):
        return []
    return sorted((r for r in data.values() if isinstance(r, dict)), key=lambda r: str(r.get("first", "")))


def daily_section(state_dir, day: str) -> str:
    """The daily report's lines on the relay's own faults that day, '' when none."""
    return texts.relay_faults_section(day_faults(state_dir, day))
