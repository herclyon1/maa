"""Fault kinds recorded as fixed, for errwatch to tag when they come back.

Key: errwatch.signature() of the record (logger | message with the variable
parts blanked | exception type). Value: `fixed_in`, the first deployed relay
version (deploy tag relay-<N>) carrying the fix, and `what`, the fault in plain
words for the alarm and the daily report.

Add an entry only for a fix that is in a deploy tag (`git tag --contains
<fix commit>`), never on a guess - a recurrence alarm names the version.

A Python module rather than a JSON file next to it: make-manifest picks up
every ark_relay/*.py, so the registry cannot be left off the machine.
"""
from __future__ import annotations

import sys as _sys
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from ark_relay.core import texts

KNOWN: dict[str, dict] = {
    "ark.banners|官方图转 PNG 失败，原样交给系统 OCR|ModuleNotFoundError": {
        "fixed_in": "20261005151027",
        "what": "游戏机缺读图组件，官方长图读不了",
    },
}


_log_alertlog = logging.getLogger("ark.alertlog")

BEIJING = timezone(timedelta(hours=8))
PREFIX = "alerts"
FIELDS = ("ts", "game", "title", "text", "version", "evidence_run", "channel")
TIMEOUT = 15
KEEP_DAYS = 7          # local day files kept once they are on COS
_DAY = re.compile(r"^\d{8}$")

# The three games by the names the notification texts use (texts.py) and the
# script names AUTO-MAS runs them under. Case-sensitive: 「MAA」 is MAA's own
# name, while 「MaaEnd」 is Endfield's.
_GAMES = (("明日方舟", re.compile(r"明日方舟|(?<![A-Za-z])MAA(?![A-Za-z])")),
          ("终末地", re.compile(r"终末地|MaaEnd")),
          ("鸣潮", re.compile(r"鸣潮|OK-WW")))
# collector.py: run_id = f"{date}/{user}/{stem}"; evidence keys spell it with "_"
# (evidence.uploaders: prefix=run_id.replace("/", "_")).
_RUN = re.compile(r"(?<!\d)(\d{4}-\d\d-\d\d)[/_]([A-Za-z]+)[/_]([A-Za-z][\w-]*?-\d\d-\d\d-\d\d)(?![\w-])")


def beijing(now: "datetime | None" = None) -> datetime:
    """`now` (default: the current UTC instant) in Beijing time."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("a naive time cannot be placed in Beijing time")
    return now.astimezone(BEIJING)


def key_for(day: str) -> str:
    """The COS object for a Beijing day 'YYYYMMDD'."""
    return f"{PREFIX}/{day}.jsonl"


def _games_in(text: str) -> list[str]:
    return [g for g, rx in _GAMES if rx.search(text or "")]


def game_of(title: str, text: str) -> str:
    """The one game the title names, else the one game the body names, else ''."""
    for part in (title, text):
        found = _games_in(part)
        if len(found) == 1:
            return found[0]
        if found:
            return ""        # more than one: not one game's alarm
    return ""


def run_of(title: str, text: str) -> str:
    """The first run id the alarm names, as date/user/stem; '' when none."""
    m = _RUN.search(f"{title}\n{text}")
    return "/".join(m.groups()) if m else ""


def row(title: str, text: str, version: str = "", now: "datetime | None" = None,
        channel: str = "") -> dict:
    return {"ts": beijing(now).strftime("%Y-%m-%d %H:%M:%S"),
            "game": game_of(title, text),
            "title": str(title or ""),
            "text": str(text or ""),
            "version": str(version or ""),
            "evidence_run": run_of(title, text),
            "channel": str(channel or "")}


class AlertLog:
    """The local day files and their sync to COS.

    `put(key, data) -> None | why` and `get(key) -> (bytes | None, why)` are the
    uploader; None for `put` means this machine has no COS (lines are still kept
    locally). Tests pass fakes; production builds them from phone.cos_put/cos_get.
    """

    def __init__(self, state_dir, put=None, get=None):
        self.dir = Path(state_dir) / "alerts"
        self._put, self._get = put, get
        self._lock = threading.Lock()
        self._sync_lock = threading.Lock()
        # Whether the last sync worked, kept apart for the push path: errwatch drops
        # a WARNING logged on its own push threads, so a failure first met there
        # was never said, yet it silenced every later one (keyed by in_push_path()).
        self._ok = {False: True, True: True}

    # ---------- local ----------

    def _file(self, day: str) -> Path:
        return self.dir / f"{day}.jsonl"

    def _mark_path(self, day: str) -> Path:
        return self.dir / f"{day}.cos.json"

    def _mark(self, day: str) -> dict:
        try:
            data = json.loads(self._mark_path(day).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"seeded": False, "synced": -1}
        return data if isinstance(data, dict) else {"seeded": False, "synced": -1}

    def _set_mark(self, day: str, mark: dict) -> None:
        from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
        atomic_write_text(self._mark_path(day), json.dumps(mark))

    def record(self, title: str, text: str, version: str = "", now: "datetime | None" = None,
               channel: str = "") -> str:
        """Append one line to the day file; returns the Beijing day 'YYYYMMDD'."""
        entry = row(title, text, version, now, channel)
        day = entry["ts"][:10].replace("-", "")
        line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            f = self._file(day)
            if not f.exists():
                # A day file the COS object has not been read into yet.
                self._set_mark(day, {"seeded": False, "synced": -1})
            with f.open("ab") as fh:
                fh.write(line)
        return day

    # ---------- COS ----------

    def _days(self) -> list[str]:
        try:
            names = sorted(p.stem for p in self.dir.glob("*.jsonl"))
        except OSError:
            return []
        return [d for d in names if _DAY.match(d)]

    def sync(self) -> list[str]:
        """PUT every day file COS does not have in full yet. -> problems ([] = all there)."""
        if self._put is None:
            return []
        problems: list[str] = []
        with self._sync_lock:
            for day in self._days()[-KEEP_DAYS:]:
                if why := self._sync_day(day):
                    problems.append(why)
            with self._lock:
                self._prune()
        errwatch = _sys.modules[__name__]
        push = errwatch.in_push_path()
        if problems and self._ok[push]:
            _log_alertlog.warning("报警抄到腾讯云 COS 没成，下一条报警或下次开机再补：%s", "；".join(problems))
        elif not problems and not self._ok[push]:
            _log_alertlog.info("报警抄到腾讯云 COS 又成了")
        self._ok[push] = not problems
        return problems

    def _sync_day(self, day: str) -> str:
        """Bring one day's COS object up to the local file. -> the problem, '' when done.
        The GET and the PUT run without _lock; lines record() appends meanwhile
        are kept (the merge re-reads the file) and go up on the next sync."""
        f = self._file(day)
        with self._lock:
            mark = self._mark(day)
            try:
                data = f.read_bytes()
            except OSError as exc:
                return f"{day}: {exc}"
        if mark.get("seeded") and mark.get("synced") == len(data):
            return ""
        if not mark.get("seeded"):
            old, why = self._get(key_for(day)) if self._get else (None, "")
            if why:
                return f"{key_for(day)} 读不回来（{why}），先不写，免得盖掉"
            with self._lock:
                try:
                    data = f.read_bytes()      # with whatever was recorded during the GET
                except OSError as exc:
                    return f"{day}: {exc}"
                if old:
                    data = old + (b"" if old.endswith(b"\n") else b"\n") + data
                    from ark_relay.core.config import atomic_write_bytes  # noqa: PLC0415
                    atomic_write_bytes(f, data)
                self._set_mark(day, {"seeded": True, "synced": -1})
        why = self._put(key_for(day), data)
        if why:
            return f"{key_for(day)}：{why}"
        with self._lock:
            self._set_mark(day, {"seeded": True, "synced": len(data)})
        return ""

    def _prune(self) -> None:
        cutoff = (beijing() - timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
        for day in self._days():
            if day >= cutoff:
                continue
            f = self._file(day)
            try:
                if self._mark(day).get("synced") == f.stat().st_size:
                    f.unlink()
                    self._mark_path(day).unlink(missing_ok=True)
            except OSError:
                pass

    def flush_async(self) -> "threading.Thread | None":
        """Sync on a thread of its own (never raises into the caller)."""
        if self._put is None:
            return None

        def run() -> None:
            try:
                self.sync()
            except Exception:  # noqa: BLE001 - the copy never breaks anything else
                _log_alertlog.warning("报警抄到腾讯云 COS 出错", exc_info=True)

        errwatch = _sys.modules[__name__]
        name = f"{errwatch.PUSH_THREAD}-copy" if errwatch.in_push_path() else "alarm-copy"
        t = threading.Thread(target=run, name=name, daemon=True)
        t.start()
        return t

    def copy(self, title: str, text: str, version: str = "", now: "datetime | None" = None,
             channel: str = ""):
        """Keep the line, then send the day to COS on a thread. -> that thread or None."""
        self.record(title, text, version, now, channel)
        return self.flush_async()


def for_config(cfg) -> AlertLog:
    """The AlertLog of this machine: COS from COS_* when configured, local-only otherwise."""
    from ark_relay.features import phone  # noqa: PLC0415
    cos = phone.state_cos(cfg)
    if cos is None:
        return AlertLog(cfg.state_dir)
    return AlertLog(
        cfg.state_dir,
        put=lambda key, data: phone.cos_put(cos, key, data, TIMEOUT, public=False,
                                            content_type="application/x-ndjson; charset=utf-8"),
        get=lambda key: phone.cos_get(cos, key, TIMEOUT))


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


_os_shutdown = threading.Event()


def mark_os_shutdown() -> None:
    """The stop that is arriving is Windows shutting down (SvcShutdown), not `sc stop`."""
    _os_shutdown.set()


def os_shutdown() -> bool:
    """True once SvcShutdown has run: Windows is shutting down, whoever started it."""
    return _os_shutdown.is_set()


def clear_stopping() -> None:
    """The power-off the relay issued was cancelled (shutdown.abort_countdown): the machine stays up."""
    _stopping.clear()


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

    The one case a fault-shaped event may stay out of the group: the planned
    power-off teardown of a shutdown the relay started.
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

    What fixed itself goes to the daily report only (the user's words are in
    relay/USER-SWITCHES.txt). Only for what already recovered: a fault that is
    still there is a plain WARNING / ERROR and is pushed every time.
    Every caller is listed in relay/USER-SWITCHES.txt (tests/test_user_switches.py)."""
    return {RECOVERED: True}


def group_pushed(title: str, errs, notifier=None) -> dict:
    """`extra=` for a log call that repeats an alarm the caller has just sent with
    `notifier.send(title, ..., alert=True)` on this thread: {PUSHED: True} only when
    that send returned no errors, the title takes the group route and - when the
    notifier can tell (notify.Notifier.went_to_group) - the group robot took it
    rather than Server酱; {} otherwise, so the record is pushed from here like any
    other."""
    from ark_relay.core.notify import route_of  # noqa: PLC0415
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


# How much of a long line's end survives the cut in _kept: an exception's own words
# (「... getaddrinfo failed>」, 「[WinError 32] ...」) sit at the end of the line.
CAUSE_TAIL = 60


def _kept(line: str, n: int) -> str:
    """`line` cut to `n` characters for the queued item. When the cut would lose the
    cause the push says in plain words (texts.fault_cause reads it from the exception
    appended at the end), the head is cut shorter and the line's end is kept."""
    cut = line[:n]
    if len(line) <= n or texts.fault_cause(cut) or not texts.fault_cause(line):
        return cut
    return line[:n - CAUSE_TAIL - 1] + "…" + line[-CAUSE_TAIL:]


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
    from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
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
            known = KNOWN
        self._known = known
        self._version = version        # callable -> running code version, or None
        self._clock = clock
        self._pace = float(pace)
        self._retry = tuple(retry) or RETRY_S
        self._fallback_after = float(fallback_after)
        self._cv = threading.Condition()
        # The push thread's pause between pushes. Its own event, not the condition:
        # every new record notifies the condition and would cut a retry backoff short.
        # close() sets it so a stop does not wait out a RETRY_S backoff.
        self._wake = threading.Event()
        self._days: dict[str, dict] = {}   # before _read_queue: a lost queue is counted
        self._saved_at = 0.0
        self._queue: list[dict] = self._read_queue()
        self._inflight = 0             # items at the head of the queue being sent now
        self._refused = bool(self._queue)   # left over from before a restart: merge them
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
            from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))
        except OSError:
            pass   # still in memory; only a restart right now would lose it

    def _read_queue(self) -> list[dict]:
        if not self._dir:
            return []
        try:
            data = json.loads((self._dir / QUEUE_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []                  # nothing was waiting: the normal case
        except (OSError, ValueError) as exc:
            # The alarms the robot refused before the restart are lost. Logging it would not
            # reach the group (this handler's own records never come back in), so the
            # lost queue becomes the first item of the new one: it goes to the group.
            return [self._lost_queue_item(f"{QUEUE_FILE} 读不出来（{type(exc).__name__}），"
                                          "重启前没送出去的群报警丢了")]
        return [x for x in data if isinstance(x, dict) and x.get("title")] if isinstance(data, list) else []

    def _lost_queue_item(self, line: str) -> dict:
        """A queue item of this handler's own (no LogRecord): pushed like any other record."""
        from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
        t = self._clock()
        stamp = datetime.fromtimestamp(t, tz=SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
        item = {"title": texts.RELAY_ERROR, "body": texts.LOST_ALARM_QUEUE, "where": log.name, "line": line[:160]}
        item["key"] = json.dumps([item.get(k) for k in ("title", "body", "where", "line")], ensure_ascii=False)
        item.update(sig=signature(log.name, line), first=stamp, last=stamp, n=1, t=t)
        row = self._day(stamp[:10]).setdefault(item["sig"], {"first": stamp, "count": 0, "pushed": 0})
        row["count"] = int(row.get("count") or 0) + 1
        row.update(last=stamp, level="WARNING", where=log.name, line=line[:200])
        self._save_day(stamp[:10])
        return item

    def _save_queue(self) -> None:
        if self._dir:
            self._write(self._dir / QUEUE_FILE, self._queue)

    def _day(self, day: str) -> dict:
        if day not in self._days:
            if self._dir:
                for old, rows in self._days.items():
                    self._write(self._dir / DAY_DIR / f"{old}.json", rows)
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
        if record.name == log.name or getattr(record, PUSHED, False):
            return
        try:
            # Before the push-thread filter: a fault that recovered on the push path
            # (notify.py:_post's transport retry that went through) still writes its
            # red item. It only counts and writes the technical log, so it cannot loop
            # back into a push; _run holds no lock while it delivers.
            if getattr(record, RECOVERED, False):
                self._note_recovered(record)
                return
            if record.threadName.startswith(PUSH_THREAD):
                self._count_only(record)
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
                    "where": record.name, "line": _kept(line, 300),
                    "fixed_in": str(fixed.get("fixed_in", "")), "fixed_what": str(fixed.get("what", ""))}
        else:
            item = {"title": texts.RELAY_ERROR, "where": record.name, "line": _kept(line, 160)}
        # Merged in a backlog by the whole first line, not its first 160 characters: two faults
        # alike that far were one queued item and the second one's tail was lost (audit C-05).
        item["key"] = json.dumps([item.get("title"), item.get("body"), item.get("where"), line], ensure_ascii=False)
        item.update(sig=sig, first=stamp, last=stamp, n=1, t=record.created)
        return item

    def _backlog(self) -> bool:
        return self._refused or len(self._queue) - self._inflight >= BACKLOG

    def _take(self, record: logging.LogRecord) -> None:
        from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
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

    def _count_only(self, record: logging.LogRecord) -> None:
        """Count a record taken on the push thread, without queueing it."""
        from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
        when = datetime.fromtimestamp(record.created, tz=SERVER_TZ)
        stamp = when.strftime("%Y-%m-%d %H:%M:%S")
        sig = record_signature(record)
        item = self._item(record, sig, stamp)
        with self._cv:
            self._count(when.strftime("%Y-%m-%d"), sig, record, item, stamp)

    def _note_recovered(self, record: logging.LogRecord) -> None:
        """A fault the relay recovered from by itself: counted, never pushed, and one
        red item in the technical log (techlog.self_heal) so a session looks at why it
        happened - the user, 2026-10-11 17:44, in techlog.self_heal's docstring."""
        from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
        when = datetime.fromtimestamp(record.created, tz=SERVER_TZ)
        stamp = when.strftime("%Y-%m-%d %H:%M:%S")
        sig = record_signature(record)
        with self._cv:
            day = when.strftime("%Y-%m-%d")
            self._count(day, sig, record, {}, stamp)
            self._day(day)[sig]["recovered"] = True
            self._save_day(day)
        if self._dir:
            from ark_relay.core import statestore as techlog  # noqa: PLC0415
            techlog.self_heal(record.name, first_line(record)[:300], state_dir=self._dir, now=when)

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
            self._wake.wait(wait)

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
        before the push; when it failed, the push says so in the same message
        (texts.EVIDENCE_UPLOAD_FAILED) and the reasons go to relay.log. A failed upload
        never holds a push back. Until 2026-10-11 the failure went to the daily report
        only; the user forbade that at 17:43 (his words are in relay/USER-SWITCHES.txt's header)."""
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
            from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
            when = datetime.fromtimestamp(min(float(x.get("t") or 0) for x in batch),
                                          tz=SERVER_TZ).strftime("%H:%M")
            return body + "\n" + texts.evidence_link(got["url"], when, bool(got.get("truncated")))
        if errors := got.get("errors") or []:
            # On the push thread: this line is never pushed itself; the push carries the fact.
            log.info("证据上传失败：%s", "；".join(str(e) for e in errors))
            return body + "\n" + texts.EVIDENCE_UPLOAD_FAILED
        return body

    def pending(self) -> list[dict]:
        """What is waiting to go out (copies)."""
        with self._cv:
            return [dict(x) for x in self._queue]

    def drain(self, timeout: float = 3.0) -> None:
        """Wait for the push thread to deliver everything queued or in flight, then
        persist the queue once more.

        The hard exit (service.py SvcDoRun's os._exit) kills the push thread without
        waiting; a batch it had just delivered to the group could still be on disk
        and would be re-sent at the next boot. Called on the main thread before the
        exit."""
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
        self._wake.set()
        super().close()


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
