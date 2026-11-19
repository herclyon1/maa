"""The phone mailbox's wire format: ntfy constants, the PIN envelope and the receipt stamp.

pack / pack_chunks / unpack build and open the envelope every phone message travels
in; stamp attaches where a command came from. Split out of phone.py (which still
re-exports every name here); the design notes are in phone.py's module docstring.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
import threading
import re
import http.client
import socket
import contextlib
import functools
import os
import boot_stages
try:
    import win32event
except ImportError:
    win32event = None  # type: ignore[assignment]
from datetime import datetime, date, timedelta
from ark_relay.core import notify as netretry, texts, config
from pathlib import Path
from ark_relay.features import errwatch, queues, sanity_plan
from ark_relay.core.config import SERVER_TZ, atomic_write_bytes, atomic_write_text, both_clocks
from ark_relay.features.commands import apply_command

log = logging.getLogger("ark.phone")   # same logger as phone.py: log lines keep their name

NTFY = "https://ntfy.sh"
# How long ntfy keeps a message: "cache-duration: defines the duration for which
# messages are stored in the cache (default is 12h)." (https://docs.ntfy.sh/config/;
# ntfy.sh runs the default). A boot read (poll=1&since=...) gets nothing older,
# whatever `since` asks for, so this - not MAX_AGE - is how long a press made
# while the machine is off can wait for the next boot.
NTFY_CACHE_SEC = 12 * 3600
# The oldest envelope ts the relay still acts on (unpack), and the age past
# which an order queued behind a run is dropped (cmd_expired). An execution-age
# cap, not the mailbox's reach: the mailbox itself holds NTFY_CACHE_SEC.
MAX_AGE = 24 * 3600
# The newest ntfy time the mailbox has read is kept on disk (queues/phone_mark)
# so the next boot can tell whether it was off longer than NTFY_CACHE_SEC. The
# held stream moves it every keepalive (45 s); it is written at most this often
# from there, and always after the boot read and when the channel is closed. A
# power cut leaves it at most this stale, which only widens a reported gap.
MARK_SAVE_SEC = 600
# How many windows the mailbox could not read are kept (queues/phone_blind,
# relay.信箱空窗 in the state): at two boots a day, five days of them.
BLIND_KEEP = 10
# How many handled command ids to remember. Only commands count - the relay's
# own state pushes and heartbeats share the topic but never need remembering.
# The page renews its watch every 8 minutes, so 2000 ids is a couple of weeks of
# watch renewals; an id that rolls out lets its command run again after a
# restart. Commands older than MAX_AGE are refused anyway.
SEEN_KEEP = 2000
_UA = "ark-relay"


def pack(pin: str, body: dict, kind: str = "cmd", *, gz: bool = False) -> str:
    """The envelope. With `gz=True` the body becomes a gzip+base64 string under
    the field name `gz`.

The sending side compresses only when **the plaintext would exceed the
    limit**, so ordinarily it stays plaintext; the receiving side accepts both.
    That way an old page still running on the phone cannot suddenly fail to read
    it.
    """
    env = {"v": 1, "kind": kind, "pin": pin, "ts": int(time.time())}
    if gz:
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        env["gz"] = base64.b64encode(gzip.compress(raw.encode("utf-8"))).decode("ascii")
    else:
        env["body"] = body
    return json.dumps(env, ensure_ascii=False, separators=(",", ":"))


def pack_chunks(pin: str, body: dict, kind: str, room: int) -> "list[str]":
    """One state too big to travel inline, split into ordinary messages.

    Not attachments: ntfy expires those after three hours, and the state pushed
    before the machine shuts down for the night is exactly the one read the next
    morning. Ordinary messages are kept for twelve hours, the same as every other
    message the phone relies on.

    Every piece carries the same `sid` and its own `i` of `n`, so the phone can tell
    a complete set from a half-arrived one and never renders half a state.
    """
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    blob = base64.b64encode(gzip.compress(raw.encode("utf-8"))).decode("ascii")
    sid = hashlib.sha1(f"{time.time()}{len(blob)}".encode()).hexdigest()[:10]
    slices = [blob[i:i + room] for i in range(0, len(blob), room)] or [""]
    now = int(time.time())
    return [json.dumps({"v": 1, "kind": kind, "pin": pin, "ts": now,
                        "sid": sid, "i": i, "n": len(slices), "gzp": s},
                       ensure_ascii=False, separators=(",", ":"))
            for i, s in enumerate(slices)]


def unpack(pin: str, raw: str, *, now: "float | None" = None) -> "dict | None":
    """A wrong PIN, or a message that is too old, is treated as never seen."""
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(msg, dict):
        return None
    if str(msg.get("pin") or "") != pin:
        return None
    ts = msg.get("ts")
    if not isinstance(ts, int):
        return None
    age = (now if now is not None else time.time()) - ts
    if abs(age) > MAX_AGE:
        log.info("信箱里那条指令太老了（%s 发出，%.1f 小时前），丢弃", _bj(ts), age / 3600)
        return None
    if "gz" in msg and "body" not in msg:
        try:
            msg["body"] = json.loads(
                gzip.decompress(base64.b64decode(msg["gz"])).decode("utf-8"))
        except Exception:
            log.warning("信箱里那条消息解压失败，丢弃", exc_info=True)
            return None
    return msg


def stale_cmd(pin: str, raw: str, *, now: "float | None" = None) -> bool:
    """A command for this PIN that unpack drops for its age. The mailbox marks
    its id handled: the drop is final, and without the mark the same message is
    re-read and re-logged at every boot and reconnect while ntfy keeps it
    (relay.log 2026-10-05: two messages logged 11 times)."""
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(msg, dict) or str(msg.get("pin") or "") != pin or msg.get("kind") != "cmd":
        return False
    ts = msg.get("ts")
    if not isinstance(ts, int):
        return False
    return abs((now if now is not None else time.time()) - ts) > MAX_AGE


def _bj(ts, fmt: str = "%m-%d %H:%M:%S") -> str:
    """A unix time as the server clock (Beijing) reads it; "?" when there is none."""
    from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
    try:
        return datetime.fromtimestamp(int(ts), tz=SERVER_TZ).strftime(fmt)
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


# Page traffic, not orders: sent on every page open / every few minutes while the
# page is up. Logging them would bury the orders this line exists for.
_QUIET_ACTIONS = ("refresh", "watch")


def stamp(msg: dict, env: dict, via: str) -> dict:
    """The command body with where it came from attached under "_meta", logged once.

    ntfy keeps a message 12 hours, so once the topic has expired relay.log is the
    only record of when an order was sent. The envelope's ts is the phone's
    clock at the press, ntfy's time is when the server took it, the id is
    ntfy's own; all three go into relay.log, and "sent" into the receipt. `via` is "backlog" for the boot-time
    mailbox read (acted on later than sent), "live" for the held connection.
    run_phone_cmd strips "_meta" before apply_command, so no command sees it.
    """
    body = dict(msg.get("body") or {})
    ts, ntime, mid = msg.get("ts"), env.get("time"), str(env.get("id") or "")
    body["_meta"] = {"sent": ts, "ntfy_time": ntime, "ntfy_id": mid, "via": via}
    action = str(body.get("action") or "")
    if action not in _QUIET_ACTIONS:
        log.info("📱 收到手机指令 %s：%s 发出（北京），ntfy %s 收到，id %s，%s",
                 action or "?", _bj(ts), _bj(ntime), mid or "?",
                 "开机读信箱积压" if via == "backlog" else "在线收到")
    return body


STATE_PREFIX = "state"


def state_key(topic: str) -> str:
    """The object name for this topic; the App derives the same (Relay.stateKey)."""
    t = (topic or "").strip().lower()
    return f"{STATE_PREFIX}/{hashlib.sha256(t.encode('utf-8')).hexdigest()[:32]}.json"


def hb_key(topic: str) -> str:
    """The heartbeat object next to the state: `state/<same hash>.hb.json`
    (the App derives the same, Relay.hbURL). Built from state_key so the two
    names cannot drift apart."""
    return state_key(topic)[:-len(".json")] + ".hb.json"


def cos_put(cos, key: str, data: bytes, timeout: float, *, public: bool = True,
            content_type: str = "application/json; charset=utf-8", retry: bool = True) -> "str | None":
    """PUT `data` to `key`: public-read by default (the App has no COS keys), never
    cached (or the App reads a stale copy). `public=False` leaves the bucket's
    private ACL (alertlog.py: only key holders read the alarm copy). None when
    stored, else why not - the caller says what that means for its own object
    in its own log line. A reset or a gateway 5xx is tried again within `timeout`
    (netretry.call): the caller's limit is not stretched. `retry=False` makes one try
    (heartbeat.cos_beat between beats: its next beat is the retry)."""
    headers = {"Authorization": cos.authorization("PUT", key),
               "Cache-Control": "no-store",
               "Content-Type": content_type,
               "User-Agent": _UA}
    if public:
        headers["x-cos-acl"] = "public-read"
    req = urllib.request.Request(f"https://{cos.host}/{key}", data=data, method="PUT", headers=headers)

    def once(left):
        with urllib.request.urlopen(req, timeout=left) as r:
            return r.status
    try:
        status = netretry.call(once, "写腾讯云", timeout, detail=key) if retry else once(timeout)
    except urllib.error.HTTPError as exc:
        return f"回 {exc.code}"
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never raised
        return str(exc) or type(exc).__name__
    return None if 200 <= status < 300 else f"回 {status}"


def cos_get(cos, key: str, timeout: float) -> "tuple[bytes | None, str]":
    """GET `key` with the same signing as cos_put: (body, '') when it is there,
    (None, '') when the object does not exist (404), (None, why) for anything
    else. Never raises. Tried again within `timeout` like cos_put."""
    req = urllib.request.Request(f"https://{cos.host}/{key}",
                                 headers={"Authorization": cos.authorization("GET", key),
                                          "User-Agent": _UA})

    def once(left):
        with urllib.request.urlopen(req, timeout=left) as r:
            return r.read()
    try:
        return netretry.call(once, "读腾讯云", timeout, detail=key), ""
    except urllib.error.HTTPError as exc:
        return None, ("" if exc.code == 404 else f"回 {exc.code}")
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never raised
        return None, str(exc) or type(exc).__name__


def state_cos(cfg):
    """The bucket client from the machine's COS_* (config.Config.cos_*), or
    None when this machine has no COS - then states go to ntfy in pieces."""
    keys = [getattr(cfg, f"cos_{k}", "") or "" for k in ("secret_id", "secret_key", "bucket", "region")]
    if not all(keys):
        return None
    from ark_relay.features.evidence import Cos  # noqa: PLC0415
    return Cos(*keys)


# same logger as phone.py: log lines keep their name


HEARTBEAT_SEC = 30       # interval while someone is watching
WATCH_LEASE_SEC = 600    # one "I am watching" lasts 10 min; a foreground page renews it
HB_SLOW_SEC = 300        # interval once the day's total passes HB_FAST_UNTIL
HB_CRAWL_SEC = 1800      # interval once it passes HB_SLOW_UNTIL
HB_FAST_UNTIL = 100
HB_SLOW_UNTIL = 180
# A "watch" asks for a beat at once, so a page that has just opened learns the
# machine is up. The page reads the last 90 s of beats on open (probeHb,
# since=90s), so a beat younger than this one already answers it; the App
# renews its watch every 8 minutes and on every return to the foreground, so
# HB_KICK_GAP keeps those from each costing a message.
HB_KICK_GAP = 60
NTFY_DAILY_LIMIT = 250
# Hard stops, so the relay alone can never spend the 250. From HB_STOP_AT on
# the day's total the beat
# goes to COS only (the App reads it there); from NOTICE_STOP_AT the one-line
# 「state <ts> <bytes>」 notice is not sent either, since COS already holds the
# state it announces. The last 20 stay for bye and for the phone's own presses
# when it shares this machine's IP (ntfy counts per IP, not per sender).
HB_STOP_AT = 200
NOTICE_STOP_AT = 230
# ntfy's own count for this IP (GET /v1/account, which an anonymous visitor may
# read: {"limits": {"messages": 250, ...}, "stats": {"messages": N,
# "messages_remaining": M, ...}}). Read at heartbeat start and every
# QUOTA_SYNC_SEC while watched; a read is one request, not one message.
NTFY_ACCOUNT = f"{NTFY}/v1/account"
QUOTA_SYNC_SEC = 1800


class Quota:
    """Every message this machine posts to ntfy today, all kinds in one ledger.

    ntfy counts per IP, all topics together (the state topic and <topic>-hb
    share it), and resets "every day at midnight (UTC)" (docs.ntfy.sh/config,
    visitor-message-daily-limit) - 08:00 on the machine's Beijing clock. So the
    ledger is keyed by the UTC date, not the local one. It is a file so the
    heartbeat thread and the mailbox thread (and a restart) see the same count.

    `full` is set when ntfy itself answers 42908 「daily message quota
    reached」: from then until UTC midnight a beat would only be refused again.

    The ledger alone undercounts: a refused post is never counted, and anything
    else posting from the same IP (the phone on the home network, the Mac's
    order-now.sh) is invisible to it. So `sync` takes ntfy's own count
    (NTFY_ACCOUNT) and total() is that count plus what the relay posted since.
    """

    # Reads take the lock too: the heartbeat thread and the mailbox thread share
    # one file, and a read landing mid-write would see {} - total 0, not full -
    # and beat into a 429. Re-entrant because add() reads under it. Every write
    # is under the lock as well, so the two threads never share the fixed
    # `.tmp` name of atomic_write_text, and no reader of ours holds the file
    # open when it is replaced (on Windows os.replace fails if one did). The
    # replace itself is for a power cut mid-write: a half file reads as {} and
    # the day's count would start over at zero.
    _lock = threading.RLock()
    # The day ntfy refused, per state folder, in memory: when the day's file cannot
    # be written (_write swallows OSError) the flag never reached the disk, and
    # every later 42908 sent the day's WARNING again (status-channel audit A4).
    # Class-wide: the mailbox and the heartbeat each hold their own Quota.
    _full_day: dict = {}

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)

    @staticmethod
    def day(now: "float | None" = None) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(time.time() if now is None else now))

    def _file(self) -> Path:
        return self.state_dir / f"ntfy-{self.day()}.json"

    def read(self) -> dict:
        try:
            with self._lock:
                text = self._file().read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
            atomic_write_text(self._file(), json.dumps(data, ensure_ascii=False))
        except OSError:
            pass

    def add(self, kind: str, n: int = 1) -> None:
        with self._lock:
            data = self.read()
            try:
                data[kind] = int(data.get(kind) or 0) + n
            except (TypeError, ValueError):
                data[kind] = n
            self._write(data)

    def count(self, kind: str) -> int:
        try:
            return int(self.read().get(kind) or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _own(data: dict) -> int:
        """What the relay itself posted: every integer entry ("full" is a bool,
        "ntfy" the synced dict)."""
        return sum(v for k, v in data.items()
                   if k != "full" and isinstance(v, int) and not isinstance(v, bool))

    def own(self) -> int:
        """Messages the relay itself posted today (its ledger alone)."""
        return self._own(self.read())

    def total(self) -> int:
        """Today's messages on ntfy for this IP: ntfy's own count at the last
        sync plus what the relay posted since, or the ledger alone before any
        sync - whichever is larger."""
        data = self.read()
        own = self._own(data)
        seen = data.get("ntfy")
        if isinstance(seen, dict):
            try:
                return max(own, int(seen["n"]) + own - int(seen["own"]))
            except (KeyError, TypeError, ValueError):
                pass
        return own

    def sync(self, account) -> "int | None":
        """Take ntfy's own count from a /v1/account answer (a dict); the count,
        or None when the answer has no stats (then the ledger stands). A count
        with nothing left marks the day full."""
        stats = account.get("stats") if isinstance(account, dict) else None
        try:
            n = int(stats["messages"])
            left = int(stats["messages_remaining"])
        except (TypeError, KeyError, ValueError):
            return None
        with self._lock:
            data = self.read()
            data["ntfy"] = {"n": n, "own": self._own(data), "at": int(time.time())}
            self._write(data)
        if left <= 0:
            self.mark_full(f"ntfy 自己的计数：今天已用 {n} 条，剩 0 条")
        return n

    def mark_full(self, why: str = "") -> bool:
        """Note that ntfy refuses the rest of the day. True when this call is the
        one that noted it: that call logs the day's one WARNING (the flag is in
        the day's file, so neither the other thread nor a restart repeats it)."""
        with self._lock:
            data = self.read()
            if data.get("full") is True or self._full_day.get(str(self.state_dir)) == self.day():
                return False
            data["full"] = True
            self._full_day[str(self.state_dir)] = self.day()
            self._write(data)
            own = self._own(data)
        log.warning("ntfy 今天 %d 条的额度用完了（%s；中继这一天自己发了 %d 条）："
                    "北京时间 8 点 ntfy 清零之前，中继不再往 ntfy 发心跳和状态通知，"
                    "手机经 ntfy 发来的指令也可能被拒；腾讯云 COS 上的状态和心跳照常写，App 打开或刷新时读得到",
                    NTFY_DAILY_LIMIT, why or "ntfy 回 42908", own)
        return True

    def full(self) -> bool:
        return (self.read().get("full") is True
                or self._full_day.get(str(self.state_dir)) == self.day())

    def stops_beats(self) -> bool:
        """No beat on ntfy now: ntfy refused the day, or the day's total reached
        HB_STOP_AT (the COS beat goes on either way)."""
        return self.full() or self.total() >= HB_STOP_AT


def ntfy_account(timeout: float = 10) -> dict:
    """GET NTFY_ACCOUNT: this IP's limits and today's count, as ntfy keeps them.
    Raises on any failure (the caller keeps its ledger)."""
    req = urllib.request.Request(NTFY_ACCOUNT, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


def _ntfy_code(exc) -> "tuple[int, str]":
    """(ntfy error code, its text) from an HTTPError, (0, "") when there is none.
    ntfy answers every refusal with {"code":42908,"http":429,"error":"..."}
    (server/errors.go); a 429 alone does not say whether it was the request
    burst (42901, back in seconds) or the day's messages (42908, back at UTC
    midnight)."""
    try:
        data = json.loads(exc.read().decode("utf-8", "replace") or "{}")
        return int(data.get("code") or 0), str(data.get("error") or "")
    except Exception:  # noqa: BLE001
        return 0, ""


def _why(exc: BaseException) -> str:
    """One short reason for a failed request, for a log line a person reads."""
    if isinstance(exc, urllib.error.HTTPError):
        code, text = _ntfy_code(exc)
        return f"ntfy 回 {exc.code}" + (f" {code}" if code else "") + (f" {text}" if text else "")
    if isinstance(exc, urllib.error.URLError):
        return f"连不上：{exc.reason}"
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


def _idle_timeout(exc: BaseException) -> bool:
    """A read that timed out (no line, not even ntfy's keepalive, within the read
    timeout). Only on a stream that was already open is this the normal idle
    drop; a connection that could not be made is not."""
    return isinstance(exc, TimeoutError) or (
        isinstance(exc, urllib.error.URLError) and isinstance(getattr(exc, "reason", None), TimeoutError))


def _retry_after(exc) -> float:
    """Seconds from a Retry-After header in its delta form; 0 when there is none."""
    try:
        return max(0.0, float((getattr(exc, "headers", None) or {}).get("Retry-After") or 0))
    except (TypeError, ValueError, AttributeError):
        return 0.0


# same logger as phone.py: log lines keep their module name


_ITEM_HEAD = re.compile(r"##\s*(?P<label>[^\n]+)\n\s*(?:self|config)\.\w+\s*=\s*ConfigItem\(")
_SEC_KEY = re.compile(r'\s*"(?P<sec>\w+)"\s*,\s*"(?P<key>\w+)"\s*(?:,|$)')
_DEF = re.compile(r"^def\s+(\w+)\s*\(", re.M)
# A line at column 0 that is not a comment or the close of a wrapped signature.
_TOP_LEVEL = re.compile(r"^(?=[^\s#)\]])", re.M)
_OPTS = re.compile(r"OptionsValidator\(\s*\[(.*?)\]", re.S)
_QUOTED = re.compile(r"""["']([^"']+)["']""")


# One class per script: MaaUserConfig / MaaEndUserConfig / OkwwUserConfig.
# Matching "section.key" globally would cross labels between identically named
# fields, so the classes are kept apart.
_CLASS = re.compile(r"^class\s+(\w+)", re.M)
_CLASS_OF = {"MaaUserConfig": "MAA", "MaaEndUserConfig": "MaaEnd",
             "OkwwUserConfig": "OK-WW"}


def _mas_labels(automas_dir) -> dict:
    """Chinese labels and legal values per script. `{"MAA": {"Info.Stage": {...}}}`"""
    out: dict = {"MAA": {}, "MaaEnd": {}, "OK-WW": {}}
    if not automas_dir:
        return out
    models = Path(automas_dir) / "app" / "models"
    if not models.is_dir():
        log.warning("找不到 AUTO-MAS 的 models 目录，手机上只能显示英文字段名")
        return out
    for f in sorted(models.glob("*.py")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        marks = list(_CLASS.finditer(text))
        helpers = _helpers(text)
        for i, cm in enumerate(marks):
            game = _CLASS_OF.get(cm.group(1))
            if not game:
                continue
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            body = text[cm.end():end]
            found = _items(body)
            # Module-level helpers the class calls with itself declare fields too.
            for name in dict.fromkeys(re.findall(r"\b(\w+)\(self\)", body)):
                for path, info in _items(helpers.get(name, "")).items():
                    found.setdefault(path, info)
            out[game].update(found)
    return out


def _helpers(text: str) -> dict[str, str]:
    """Module-level functions: name -> source, up to the next top-level line."""
    out = {}
    for m in _DEF.finditer(text):
        line_end = text.find("\n", m.end())
        nxt = _TOP_LEVEL.search(text, line_end + 1) if line_end >= 0 else None
        out[m.group(1)] = text[m.start():nxt.start() if nxt else len(text)]
    return out


def _call_args(text: str, start: int) -> "str | None":
    """The arguments of the call whose `(` ends just before `start`, up to its
    matching `)`; quotes and comments are skipped. None when it never closes."""
    depth, i, quote = 1, start, ""
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "#":
            j = text.find("\n", i)
            i = len(text) if j < 0 else j
            continue
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


def _items(text: str) -> dict:
    """Every labelled ConfigItem("Section", "Key", ...) in `text`: {"Section.Key": {label, options}}."""
    out: dict = {}
    for m in _ITEM_HEAD.finditer(text):
        args = _call_args(text, m.end())
        sk = _SEC_KEY.match(args) if args is not None else None
        if not sk:
            continue
        o = _OPTS.search(args)
        out[f'{sk.group("sec")}.{sk.group("key")}'] = {
            "label": m.group("label").strip(),
            "options": _QUOTED.findall(o.group(1)) if o else None,
        }
    return out


# The items the phone displays. Only these are sent: all ~154 labels together push
# one message past ntfy's size limit, the message is truncated, the page's
# JSON.parse fails and the phone shows the machine as 「关机中」.
SHOWN = (
    "Info.Stage", "Info.StageMode", "Info.MedicineNumb", "Info.SeriesNumb",
    "Info.Annihilation",
    # AUTO-MAS v5.7.0-beta.3 moved those five here (ark_relay/core/masuser.py).
    "Stage.Stage", "Stage.StageMode", "Stage.MedicineNumb", "Stage.SeriesNumb",
    "Task.Annihilation", "Task.IfFight", "Task.IfActivityFirst",
    "Task.ActivityStageIndex", "Task.ActivityMedicineNumb",
    "Task.IfSanity", "Task.IfAutoUseSpMedication", "Task.SanityTaskType",
    "Task.AutoEssenceSpecifiedLocation",
    "Task.WhichToFarm", "Task.WhichTacetSuppressionToFarm",
    "Task.WhichForgeryChallengeToFarm", "Task.MaterialSelection",
    "Task.FarmNightmareNestForDailyEcho", "Task.TaskIndex",
)


def _options(cfg) -> dict:
    """Per-game options. When they cannot be read, none are sent and the page
    falls back to a text box for that item."""
    out: dict = {"MAA": {}, "MaaEnd": {}, "OK-WW": {}}
    try:
        names: dict = {}
        for game, items in _mas_labels(getattr(cfg, "automas_dir", None)).items():
            for path, info in items.items():
                if path not in SHOWN:
                    continue
                names[f"{game}|{path}"] = info["label"]
                # Only the Chinese field names are sent, not the candidate lists:
                # the stage list alone is over a thousand bytes and would push the
                # packet towards ntfy's size limit.
        out["_labels"] = names
    except Exception:
        log.warning("AUTO-MAS 的中文标注读不到", exc_info=True)
    return out


# same logger as phone.py: log lines keep their name


HB_COS_SEC = HEARTBEAT_SEC


class Heartbeat:
    """Beats only while someone is watching. `post` is injectable so the tests
    never touch the network; `cos` (state_cos) adds the beat on COS.
    `account` reads ntfy's own count (ntfy_account); it defaults to the real
    one only when `post` is the real one too, so a test that fakes the beats
    never reaches ntfy for the count either."""

    def __init__(self, topic: str, state_dir: Path, post=None, cos=None, account=None):
        self.topic = (topic or "").strip()
        self.url = f"{NTFY}/{self.topic}-hb"
        self.state_dir = Path(state_dir)
        self.quota = Quota(self.state_dir)
        self.cos = cos
        self._lease = 0.0
        self._last = 0.0          # when the last ntfy beat went out
        self._cos_last = 0.0      # when the last COS beat was tried
        self._cos_ok = True       # so a COS outage is logged once, not every 30 s
        self._cos_down = None     # when the current COS outage began (first failed beat)
        self._cos_why = ""        # its first reason
        self._cos_told = False    # it reached COS_OUTAGE_SEC and was pushed
        # COS beats written / failed by this process, and when the last one was
        # written: the machine check #56 reads them (cos_report)
        self.cos_ok_n = 0
        self.cos_fail_n = 0
        self.cos_last_ok = 0.0
        self._synced = 0.0        # when ntfy's own count was last asked for
        self._stop_told = ""      # the UTC day the HB_STOP_AT switch was logged
        self._kick = threading.Event()
        self._post = post or self._http_post
        self._account = account if account is not None else (None if post else ntfy_account)

    def _http_post(self, payload: bytes, title: str) -> None:
        req = urllib.request.Request(self.url, data=payload, method="POST",
                                     headers={"User-Agent": _UA, "Title": title})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except urllib.error.HTTPError as exc:
            code, text = _ntfy_code(exc)
            if code == 42908:
                self.quota.mark_full(f"心跳被 ntfy 拒：{text or '42908'}")   # the day's one WARNING
            raise

    def sync_quota(self) -> None:
        """Ask ntfy for its own count of today's messages from this IP
        (Quota.sync). A failed read changes nothing and is not a fault: the
        ledger stands (DEBUG)."""
        if self._account is None:
            return
        self._synced = time.time()
        try:
            n = self.quota.sync(self._account())
        except Exception:  # optional; the ledger is the fallback
            log.debug("ntfy 的计数没读到，按中继自己的账本算", exc_info=True)
            return
        if n is not None:
            log.info("📱 ntfy 今天这个 IP 已用 %d 条（中继自己发的 %d 条）", n, self.quota.own())

    # -- lease --
    def watch(self) -> None:
        """The page says "I am watching": renew for 10 minutes and beat at once
        (unless a beat went out within HB_KICK_GAP) so it knows the machine is up."""
        self._lease = time.time() + WATCH_LEASE_SEC
        self._kick.set()

    def watched(self) -> bool:
        return time.time() < self._lease

    # -- today's count (keeps the ntfy quota from being eaten) --
    def sent_today(self) -> int:
        """Beats sent today (ntfy's UTC day)."""
        return self.quota.count("hb")

    def interval(self) -> int:
        total = self.quota.total()
        if total < HB_FAST_UNTIL:
            return HEARTBEAT_SEC
        if total < HB_SLOW_UNTIL:
            return HB_SLOW_SEC
        return HB_CRAWL_SEC

    def pace(self) -> int:
        """`every` in the COS beat (see HB_COS_SEC)."""
        every = self.interval()
        return max(every, HB_SLOW_SEC) if self.quota.stops_beats() else every

    # A COS beat outage this long is pushed (the phone channel's own bound,
    # Mailbox.OUTAGE_SEC): the App's read on open finds an old beat all that time.
    COS_OUTAGE_SEC = 600

    def cos_beat(self, bye: bool = False) -> bool:
        """PUT the beat to hb_key(topic). Never raises; a failure is one log
        line (until it works again) and does not touch the ntfy beat.

        A failed beat is INFO and decided by the next ones: one that works
        again -> one WARNING marked errwatch.recovered(), the daily report only
        (why: USER-SWITCHES.txt at heartbeat.py:Heartbeat.cos_beat);
        still failing COS_OUTAGE_SEC after the first -> one WARNING, pushed."""
        if self.cos is None or not self.topic:
            return False
        self._cos_last = time.time()
        body = {"at": int(self._cos_last), "every": self.pace(), "cos_every": HB_COS_SEC}
        if bye:
            body["bye"] = True
            # Who stopped the machine and why (the relay's own power-off names the shift
            # and when it finished); an extra field, so an App that does not read it is unchanged.
            try:
                from ark_relay.features import shutdown  # noqa: PLC0415
                body["off"] = shutdown.poweroff_note(self.state_dir)
            except Exception:  # the bye goes out without it
                log.debug("下线心跳的关机原因没整理出来", exc_info=True)
        try:
            why = cos_put(self.cos, hb_key(self.topic), json.dumps(body).encode("utf-8"),
                          Mailbox.COS_TIMEOUT, retry=bye)
        except Exception as exc:  # noqa: BLE001 - e.g. signing; never reaches the ntfy beat
            why = str(exc) or type(exc).__name__
        if why:
            self.cos_fail_n += 1
            # INFO at first, not WARNING: the next COS beat is 30 s away and the
            # ntfy beat still carries this one.
            if self._cos_down is None:
                self._cos_down, self._cos_why = self._cos_last, why
            if self._cos_ok or bye:
                log.info("心跳没能写到腾讯云 COS（%s）%s", why,
                         "，App 要等下次打开才知道已下线" if bye else "，ntfy 心跳照旧")
            elif not self._cos_told and self._cos_last - self._cos_down >= self.COS_OUTAGE_SEC:
                # Not back after COS_OUTAGE_SEC: not recovered, pushed (once per outage).
                self._cos_told = True
                log.warning("心跳从 %s 起一直写不进腾讯云，已经 %.0f 分钟（最近一次：%s）：这段时间 App 打开时读到的是"
                            "写不进之前的那一跳；手机信箱的心跳照旧", _bj(self._cos_down, "%H:%M:%S"),
                            (self._cos_last - self._cos_down) / 60, why)
            self._cos_ok = False
            return False
        if self._cos_down is not None:
            # Written again: the relay got over it by itself, the daily report only.
            log.warning("心跳又写得进腾讯云了（断了 %.0f 秒%s）\n没写上的原因：%s",
                        self._cos_last - self._cos_down, "，期间报过群" if self._cos_told else "",
                        self._cos_why, extra=errwatch.recovered())
        self._cos_ok, self._cos_down, self._cos_why, self._cos_told = True, None, "", False
        self.cos_ok_n += 1
        self.cos_last_ok = self._cos_last
        return True

    def cos_report(self) -> dict:
        """The COS beats of this process, for the machine check #56: how many were
        written and failed, the last one written, and the outage going on now
        (since when, its first reason, whether it was pushed)."""
        return {"ok": self.cos_ok_n, "failed": self.cos_fail_n, "last_ok": self.cos_last_ok,
                "down_since": self._cos_down, "why": self._cos_why, "told": self._cos_told,
                "cos": self.cos is not None}

    def beat(self) -> bool:
        """One beat: on COS always, on ntfy unless the quota stopped it.
        Returns whether the ntfy beat went out."""
        self.cos_beat()
        if self.quota.full():
            return False          # ntfy said 42908; a beat would only be refused again
        if self.quota.stops_beats():
            # The relay's own budget: the rest of the day is for states, bye
            # and the phone's presses. Said once a day, as what it is - a
            # rule doing its job, not a fault.
            if self._stop_told != Quota.day():
                self._stop_told = Quota.day()
                log.info("📱 ntfy 今天已用 %d 条（到 %d 条就停），心跳只写腾讯云 COS，"
                         "留额度给状态通知和手机的指令", self.quota.total(), HB_STOP_AT)
            return False
        try:
            # The current cadence rides along in the message. The page decides
            # "no heartbeat for a while = powered off" from a fixed 90 seconds,
            # and once the cadence drops to one beat every 5 minutes that
            # verdict is wrong for three and a half minutes out of every five -
            # a red 「关机中」 while the queue is running. It cannot know the
            # cadence unless it is told, and widening its window instead would
            # slow down the one thing it exists for: seeing a real power-off.
            self._post(f"hb {self.interval()}".encode(), "hb")
        except Exception:
            log.debug("心跳没发出去", exc_info=True)
            return False
        self._last = time.time()
        self.quota.add("hb")
        return True

    def bye(self) -> None:
        # Not into a day ntfy has refused: the bye would only get a 429.
        if not self.quota.full():
            try:
                self._post(b"bye", "bye")
                self.quota.add("bye")
                log.info("📱 已发下线心跳（bye）")
            except Exception:
                log.debug("下线心跳没发出去", exc_info=True)
        # After the ntfy bye, so the live signal is not held up; cos_beat never
        # raises and COS_TIMEOUT (8 s) plus the bye's 10 s fit the 30 s a
        # Windows service stop allows.
        self.cos_beat(bye=True)

    _slice_s = 1        # 见 loop() 里的说明

    def loop(self, stop) -> None:
        """Body of the background thread. Exits when stop() returns true, sending
        bye on the way out."""
        # One beat on the way in, whoever is watching. Stopping the service sends a
        # bye, and beats only go out while someone holds a watch, so without this
        # the last thing the phone heard after a restart would be the bye
        # (「关机中」) while the machine runs.
        self.sync_quota()           # ntfy's own count first: the cadence follows it
        self.beat()
        while not stop():
            kicked = self._kick.is_set()
            self._kick.clear()
            wait = 5
            if self.watched():
                if time.time() - self._synced >= QUOTA_SYNC_SEC:
                    self.sync_quota()
                every = self.interval()
                need = min(every, HB_KICK_GAP) if kicked else every
                since = time.time() - self._last
                stopped = self.quota.stops_beats()
                beat = not stopped and since >= need
                if beat:
                    self.beat()             # ntfy and COS; a failed one waits `every` too
                    left = every
                elif stopped:
                    left = every            # nothing to send on ntfy until the day turns
                else:
                    left = every - since
                if self.cos is not None:
                    if not beat and (kicked or time.time() - self._cos_last >= HB_COS_SEC):
                        # A watch is answered on COS at once even when the ntfy
                        # beat is not due (or the quota stopped it): the App
                        # reads the object a few seconds after it sends the watch.
                        self.cos_beat()
                    left = min(left, HB_COS_SEC - (time.time() - self._cos_last))
                wait = max(1, int(left + 0.999))
            # Wait in slices rather than one long sleep: stopping the service must
            # exit at once, and an incoming watch() must be able to beat at once.
            # `slice_s` is only ever shortened by the test, so the test does not
            # sleep in real time.
            for _ in range(wait):
                if stop() or self._kick.is_set():
                    break
                time.sleep(self._slice_s)
        self.bye()


_log_monthcard = logging.getLogger("ark.monthcard")

# Days added by one purchase, per game.
DAYS = {
    # PRTS wiki, item page for the monthly card voucher: 「增加30天月卡有效期」
    "明日方舟": 30,
    # PlayStation Store UB0018-PPSA18538_00-ZMDPS5GL0MONTHLY: 「同时获得30天的月卡权益」
    "终末地": 30,
    # 月相观测卡, 30 days per purchase: shop text as quoted by gamekee / 17173; the
    # official page was not found (spec, 「未核对官方原文」).
    "鸣潮": 30,
}

WARN_DAYS = 5          # start warning five days ahead, his words: 「临近到期前五天开始通知」
MAX_ADD = 12
MAX_LEFT = 400
FILE = "monthcard.json"
# A phone-computed `last` further out than this is refused: the most the page can reach is
# left 400, or a card with up to 400 days left topped up 12 times.
MAX_AHEAD = MAX_LEFT + 30 * MAX_ADD


def _today() -> date:
    return datetime.now(tz=SERVER_TZ).date()


def _load(state_dir) -> dict:
    try:
        return json.loads((Path(state_dir) / FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        # Keep the unreadable file beside it: the next registration rewrites FILE, and his
        # earlier entries would otherwise be gone without a trace.
        bad = Path(state_dir) / (FILE + ".bad")
        try:
            atomic_write_bytes(bad, (Path(state_dir) / FILE).read_bytes())
        except OSError:
            pass
        _log_monthcard.error("monthcard.json unreadable, treated as empty; copy kept as %s", bad, exc_info=True)
        return {}


def _save(state_dir, data: dict) -> None:
    atomic_write_text(Path(state_dir) / FILE, json.dumps(data, ensure_ascii=False, indent=1))


def _md(d: date) -> str:
    return f"{d.month} 月 {d.day} 日"


def _line(game: str, last: date, today: date) -> str:
    left = (last - today).days
    if left < 0:
        return f"{game}月卡：已过期（最后一次领取是 {_md(last)}）"
    return f"{game}月卡：最后一次领取 {_md(last)}（还剩 {left} 天）"


def _int(v, lo: int, hi: int) -> "int | None":
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi and str(n) == str(v).strip() else None


def _when(v) -> "datetime | None":
    """An ISO timestamp from the phone (`toISOString`, trailing Z) or from this file."""
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        t = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)


def apply(state_dir, cmd: dict, today: "date | None" = None) -> tuple[bool, str]:
    """The phone's `monthcard` order: `{"game", "add": N}` or `{"game", "left": X}`."""
    today = today or _today()
    game = str(cmd.get("game") or "").strip()
    if game not in DAYS:
        return False, f"月卡：不认识的游戏 {game!r}，只认 明日方舟 / 终末地 / 鸣潮"
    has_add, has_left = cmd.get("add") is not None, cmd.get("left") is not None
    if has_add == has_left:
        return False, "月卡：add（充值次数）和 left（还剩几天）要填且只填一个"
    data = _load(state_dir)
    rec = dict(data.get(game) or {})
    at = _when(cmd.get("at"))
    if cmd.get("at") is not None and at is None:
        return False, f"月卡：登记时间看不懂，收到 {cmd.get('at')!r}"
    stored = _when(rec.get("set"))
    phone_last = None
    if cmd.get("last") is not None:
        try:
            phone_last = date.fromisoformat(str(cmd.get("last")).strip())
        except ValueError:
            return False, f"月卡：最后领取日要是 YYYY-MM-DD，收到 {cmd.get('last')!r}"
        if (phone_last - today).days > MAX_AHEAD:
            return False, f"月卡：最后领取日 {phone_last.isoformat()} 离今天超过 {MAX_AHEAD} 天，没记"
    if has_left:
        left = _int(cmd.get("left"), 0, MAX_LEFT)
        if left is None:
            return False, f"月卡：还剩天数要是 0 到 {MAX_LEFT} 的整数，收到 {cmd.get('left')!r}"
        last = today + timedelta(days=left)
    else:
        n = _int(cmd.get("add"), 1, MAX_ADD)
        if n is None:
            return False, f"月卡：充值次数要是 1 到 {MAX_ADD} 的整数，收到 {cmd.get('add')!r}"
    if at is not None and stored is not None and at < stored:
        return True, _line(game, date.fromisoformat(rec["last"]), today) + "（已有更晚的登记，这条没改）"
    if phone_last is not None:
        last = phone_last
    elif not has_left:
        base_day = at.astimezone(SERVER_TZ).date() if at is not None else today
        prev = date.fromisoformat(rec["last"]) if rec.get("last") else None
        if prev is not None and prev >= base_day:
            last = prev + timedelta(days=DAYS[game] * n)
        else:
            # Never registered, or lapsed: the purchase day is day 1.
            last = base_day + timedelta(days=DAYS[game] * n - 1)
    rec.update(last=last.isoformat(),
               set=(at or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ).isoformat(timespec="milliseconds"))
    # milliseconds: the page compares 登记于 with its own registration time, which has them
    data[game] = rec
    _save(state_dir, data)
    return True, _line(game, last, today)


def status(state_dir, today: "date | None" = None) -> dict:
    """`relay.月卡` for the phone page: registered games only."""
    today = today or _today()
    out = {}
    for game, rec in _load(state_dir).items():
        if game not in DAYS or not isinstance(rec, dict) or not rec.get("last"):
            continue
        try:
            last = date.fromisoformat(rec["last"])
        except ValueError:
            continue
        left = (last - today).days
        out[game] = {"最后领取": last.isoformat(), "还剩": left, "已过期": left < 0}
        if rec.get("set"):
            out[game]["登记于"] = rec["set"]   # the phone keeps whichever registration is newer
    return out


def due_notice(state_dir, today: "date | None" = None) -> "tuple[str, str] | None":
    """Today's reminder: (title, body), or None when nothing is due or it already went out today.

    The caller sends it and then calls `mark_sent`, so a push that reached nobody
    is tried again on the next tick instead of being lost for the day.
    """
    today = today or _today()
    due = [(g, v) for g, v in status(state_dir, today).items() if 0 <= v["还剩"] <= WARN_DAYS]
    if not due:
        return None
    data = _load(state_dir)
    if data.get("_notified") == today.isoformat():
        return None
    due.sort(key=lambda gv: gv[1]["还剩"])
    lines = [f"{g}月卡还剩 {v['还剩']} 天，最后一次领取是 {_md(date.fromisoformat(v['最后领取']))}"
             for g, v in due]
    return "💳 月卡快到期", "\n".join(lines)


def mark_sent(state_dir, today: "date | None" = None) -> None:
    data = _load(state_dir)
    data["_notified"] = (today or _today()).isoformat()
    _save(state_dir, data)


# same logger as phone.py: log lines keep their name


# ---------- orders that wait for the run to end ----------
#
# A config write while a script runs is clobbered by AUTO-MAS's in-memory copy,
# so such an order cannot be applied on the spot. It waits here, on disk (a relay
# restart or a reboot
# between the press and the end of the run must not lose it), and
# boot_stages drains it in arrival order once nothing is running, before the
# shutdown decision of that same tick.
CMD_QUEUE_FILE = "phone-queue.json"
# Orders that start a run rather than change a setting. Pressed while a run is
# going they are answered at once and never queued: applied after the run they
# would start one more on top of it (commands.run_script). Every
# other order only writes settings and waits in the queue.
DISPATCHING_ACTIONS = frozenset({"run_now", "echo_farm"})
# Ids of drained orders, remembered so the same order is never queued twice
# (the mailbox's own `_seen` already stops a re-delivery; this is the second lock).
CMD_QUEUE_DONE_KEEP = 200
_CMD_QUEUE_LOCK = threading.Lock()


def cmd_key(body: dict) -> str:
    """What makes an order the same order: ntfy's id, else its send time and content."""
    meta = (body or {}).get("_meta") or {}
    if meta.get("ntfy_id"):
        return str(meta["ntfy_id"])
    rest = {k: v for k, v in (body or {}).items() if k != "_meta"}
    raw = json.dumps([meta.get("sent"), rest], ensure_ascii=False, sort_keys=True, default=str)
    return "h:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# What CmdQueue.add did with an order.
QUEUED, RESENT, SAME = "queued", "resent", "same"


def _content(body: dict) -> str:
    """An order without its envelope: what it asks for, not when or how it came."""
    return json.dumps({k: v for k, v in (body or {}).items() if k != "_meta"},
                      ensure_ascii=False, sort_keys=True, default=str)


def _item_keys(item: dict) -> list[str]:
    """The order's own key plus those of the presses folded into it (RESENT)."""
    return [cmd_key(item["body"])] + [str(k) for k in item.get("also") or []]


def item_sent(item: dict) -> "int | None":
    """The latest send time of a queued order: its own, or a later press of the same
    order folded into it. The final receipt carries it, so the App can match it to
    every press it answers (D207: a receipt answers presses sent no later than it)."""
    meta = (item.get("body") or {}).get("_meta") or {}
    times = [t for t in (meta.get("sent"), item.get("resent")) if isinstance(t, int)]
    return max(times) if times else None


class CmdQueue:
    """Phone orders that arrived while a script was running, oldest first.

    Every item is the order exactly as it arrived (with its "_meta": the receipt
    needs "sent", the de-dup needs "ntfy_id") plus "queued" (unix seconds), and,
    once the same order was pressed again while it waited, "also" (those presses'
    keys) and "resent" (the latest of their send times).
    Written atomically under one lock: the mailbox thread adds, the engine
    thread takes. `pop` removes the item before it is acted on, so a crash
    mid-order loses that one order rather than running it twice.
    """

    def __init__(self, state_dir):
        self.path = Path(state_dir) / CMD_QUEUE_FILE

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"items": [], "done": []}
        except (OSError, ValueError):
            log.warning("手机指令排队文件读不出来，按空的处理：%s", self.path, exc_info=True)
            return {"items": [], "done": []}
        if not isinstance(data, dict):
            return {"items": [], "done": []}
        items = [i for i in data.get("items") or [] if isinstance(i, dict) and isinstance(i.get("body"), dict)]
        done = [str(d) for d in data.get("done") or []]
        return {"items": items, "done": done}

    def _write(self, data: dict) -> None:
        from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data["done"] = data["done"][-CMD_QUEUE_DONE_KEEP:]
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False))

    def add(self, body: dict, now: "float | None" = None) -> str:
        """Queue one order. QUEUED when it went in. SAME when this very message is
        already queued or done (a re-delivery). RESENT when it is a new press of
        what the latest waiting order of the same action already asks for, word for
        word (D207): it is not queued a second time, its key and send time are
        kept on the waiting one. Only the latest of that action is compared:
        「开 → 关 → 开」 still ends on 开."""
        key = cmd_key(body)
        with _CMD_QUEUE_LOCK:
            data = self._read()
            if key in data["done"] or any(key in _item_keys(i) for i in data["items"]):
                return SAME
            action = (body or {}).get("action")
            last = next((i for i in reversed(data["items"]) if i["body"].get("action") == action), None)
            if last is not None and _content(last["body"]) == _content(body):
                last["also"] = [str(k) for k in last.get("also") or []] + [key]
                sent = ((body or {}).get("_meta") or {}).get("sent")
                if isinstance(sent, int):
                    last["resent"] = max(sent, last["resent"]) if isinstance(last.get("resent"), int) else sent
                self._write(data)
                return RESENT
            data["items"].append({"body": body, "queued": int(now if now is not None else time.time())})
            self._write(data)
            return QUEUED

    def __len__(self) -> int:
        if not self.path.is_file():
            return 0
        with _CMD_QUEUE_LOCK:
            return len(self._read()["items"])

    def holds(self, body: dict) -> bool:
        """Whether this order is on the queue file: waiting, folded into a waiting
        one, or already taken off to run (the machine check #23)."""
        key = cmd_key(body)
        with _CMD_QUEUE_LOCK:
            data = self._read()
        return key in data["done"] or any(key in _item_keys(i) for i in data["items"])

    def pop(self) -> "dict | None":
        """Take the oldest order off the queue (and remember its key); None when empty."""
        with _CMD_QUEUE_LOCK:
            data = self._read()
            if not data["items"]:
                return None
            item = data["items"].pop(0)
            data["done"].extend(_item_keys(item))
            self._write(data)
            return item


def cmd_expired(item: dict, now: "float | None" = None) -> bool:
    """The mailbox's own window (MAX_AGE, 24 h) applied once more when the order
    finally runs: counted from the phone's send time (its latest press, see
    item_sent), else from when it was queued."""
    sent = item_sent(item)
    if sent is None:
        sent = item.get("queued")
    if not isinstance(sent, (int, float)):
        return False
    return (now if now is not None else time.time()) - sent > MAX_AGE


_log_inbox = logging.getLogger("ark.inbox")


def receipt_failed(lines: "list[str]") -> bool:
    """True when a command line of a batch's receipt (Inbox._apply, or the mid-batch
    error line) failed: each failed command's line starts with 「✗」."""
    return any(str(m).startswith("✗") for m in lines)


def label_version(version: int) -> str:
    """2026081702 -> '08-17 v2'. Falls back to the raw number.

    The version has to be an integer so "strictly newer" can be decided without
    ambiguity - raw.githubusercontent is a CDN and can hand back a stale copy,
    and comparing dates as text invites the wrong answer at a month boundary.
    Encoding the date into the integer as YYYYMMDDNN keeps that property while
    letting the push say when the change was made instead of "v1", which tells
    the reader nothing.
    """
    text = str(version)
    if len(text) != 10:
        return f"v{version}"
    try:
        return f"{text[4:6]}-{text[6:8]} v{int(text[8:10])}"
    except ValueError:
        return f"v{version}"

DEFAULT_URL = ("https://raw.githubusercontent.com/herclyon1/maa/main/"
               "queue/config.json")

# Where scripts/mac/order.sh puts the same file on COS, below selfupdate's
# COS_PREFIX ("relay"): the full object key is relay/queue/config.json. Under
# relay/ because the bucket's lifecycle rule deletes everything else after 30
# days (PrefixNotEquals relay/, docs/OPERATIONS.md). order.sh imports this
# name, so both ends use one key.
COS_INBOX_KEY = "queue/config.json"
COS_DOOR = "cos"   # how the COS door appears in _last_good and the error list


def _alternates(url: str) -> list[str]:
    """The same file through a second door.

    raw.githubusercontent is poorly reachable from the machine's network
    (timeouts and 429s; measurements below). jsDelivr serves the identical
    GitHub content over a CDN with far better reachability from there. The repo, its history and
    the write path stay on GitHub untouched; only the download exit changes.
    A stale CDN copy is harmless by construction: versions apply only when
    strictly newer, and selfupdate verifies every file against its SHA-1.

    (Deliberately duplicated in selfupdate.py rather than shared: selfupdate
    refuses to create new files on the machine, so a new shared module would
    never arrive there.)
    """
    prefix = "https://raw.githubusercontent.com/"
    if not url.startswith(prefix):
        return [url]
    parts = url[len(prefix):].split("/", 3)
    if len(parts) < 4:
        return [url]
    owner, repo, branch, path = parts
    ref = f"gh/{owner}/{repo}@{branch}/{path}"
    return [
        f"https://fastly.jsdelivr.net/{ref}",
        f"https://cdn.jsdelivr.net/{ref}",
        f"https://gcore.jsdelivr.net/{ref}",
        url,
    ]


# Netloc of the door that answered most recently, tried first from then on.
# (Same stickiness as selfupdate.py, duplicated for the same reason the
# _alternates helper is: selfupdate cannot deliver new shared modules.)
_last_good = ""


def _netloc(url: str) -> str:
    """Host part of an http(s) URL; the URL itself when it has no host.

    Never raises: a misconfigured ARK_INBOX_URL must degrade into a failed
    fetch (which keeps last_fetch_ok False and the 5-minute retry alive), not
    an IndexError that skips the fetch and leaves last_fetch_ok stuck True.
    """
    parts = url.split("/")
    return parts[2] if len(parts) > 2 else url


def _fetch(url: str, timeout: int = 20, attempts: int = 3) -> dict | None:
    """Fetch the queue file from every door and keep the highest version.

    "Use whichever door answers first" will not do: a CDN still caching an
    older config.json shows a version that has not gone up, which reads as "no
    new instructions" and skips a queued order without a word.

    Self-update can see through a stale copy using the SHA-1s in the manifest;
    the queue file has no such check, because it is the authority itself. So it
    uses the same approach - ask every door and take the highest version.
    Version numbers only ever go up, so a lagging door drops out by itself and
    no single door has to be trusted.

    When only one door answers (or none of them carries a version), fall back
    to "use whatever was fetched", which keeps backward compatibility.

    A round in which no door answered is the fault (one door failing is not).
    When a later round gets the file, the relay got over it by itself: one
    WARNING marked errwatch.recovered(), the daily report only (why:
    USER-SWITCHES.txt at inbox.py:_got_on_retry).
    Every round failing stays the WARNING below, pushed.

    COS goes first in every round (see the module docstring) but is one door
    among the others: its copy wins only by carrying the highest version, so
    a COS that was not written (order.sh failed its PUT, or the file was
    edited on GitHub by hand) costs nothing but the round-trip.
    """
    global _last_good  # noqa: PLW0603 - process-lifetime stickiness by design
    urls = _alternates(url)
    urls.sort(key=lambda u: _netloc(u) != _last_good)  # stable: keeps order
    cos = _cos_client()
    doors = ([COS_DOOR] if cos is not None else []) + urls
    errors: list[str] = []
    for i in range(attempts):
        before = errors[:]              # what the rounds before this one met
        best: dict | None = None
        best_ver = -1
        fallback: dict | None = None
        for u in doors:
            data = (_fetch_cos_once(cos, timeout, errors) if u == COS_DOOR
                    else _fetch_once(u, timeout, errors))
            if data is None:
                continue
            if fallback is None:
                fallback = data
                _last_good = _netloc(u)
            try:
                ver = int(data.get("version") or 0)
            except (TypeError, ValueError):
                ver = 0
            if ver > best_ver:
                best, best_ver = data, ver
                if ver > 0:
                    _last_good = _netloc(u)
        if best is not None and best_ver > 0:
            _log_inbox.debug("待办文件取自各门中最新的一份 v%s", best_ver)
            _got_on_retry(i, before)
            return best
        if fallback is not None:
            _got_on_retry(i, before)
            return fallback
        if i + 1 < attempts:
            time.sleep(3 * (i + 1))
    # Only **every door failing to answer** counts as a fault, and when that happens
    # write out what each door did, instead of a single "could not fetch" that leaves
    # the reader guessing which route is down.
    _log_inbox.warning("待办文件一扇门都没取到（试了 %d 扇 × %d 轮）：%s",
                len(doors), attempts, "；".join(errors[-len(doors):]) or "无详情")
    return None


def _got_on_retry(round_: int, errors: "list[str]") -> None:
    """Round `round_` (0-based) got the file: when it is not the first, no door
    gave it in the rounds before (`errors`: what they met) - a fault the relay
    got over by retrying, the daily report only."""
    if round_:
        from ark_relay.features import errwatch  # noqa: PLC0415
        _log_inbox.warning("待办文件前 %d 轮一扇门都没取到，第 %d 轮取到了\n前几轮：%s", round_, round_ + 1,
                    "；".join(errors) or "无详情", extra=errwatch.recovered())


def _cos_client():
    """The bucket client self-update uses, or None when COS is not configured
    on this machine (then the GitHub doors are all there is, as before)."""
    from ark_relay.features import selfupdate  # noqa: PLC0415 - selfupdate never imports inbox
    try:
        return selfupdate._cos()  # one place builds the client
    except Exception:  # noqa: BLE001 - a broken COS setup must not stop the GitHub doors
        _log_inbox.debug("待办：COS 客户端建不起来", exc_info=True)
        return None


def _fetch_cos_once(cos, timeout: int = 20,
                    errors: "list[str] | None" = None) -> dict | None:
    """The COS door: one signed GET of COS_INBOX_KEY. Like _fetch_once, a
    failure is logged at debug only - one door failing is not a fault - and
    noted in `errors` for the warning _fetch writes when every door failed.
    (Not selfupdate._cos_get: that one logs a WARNING per failure.)"""
    import urllib.parse  # noqa: PLC0415
    full = f"{cos.prefix}/{COS_INBOX_KEY}"
    url = f"https://{cos.host}/" + urllib.parse.quote(full, safe="/")
    try:
        req = urllib.request.Request(url, headers={"Authorization": cos.authorization("GET", full),
                                                   "User-Agent": "ark-relay"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, OSError, ValueError,
            http.client.HTTPException) as exc:
        _log_inbox.debug("待办：COS 没答应（%s）", exc)
        if errors is not None:
            errors.append(f"{COS_DOOR}: {exc}")
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log_inbox.warning("COS 上的待办文件不是合法 JSON: %s", exc)
        return None
    return data if isinstance(data, dict) else None


def _fetch_once(url: str, timeout: int = 20,
                errors: "list[str] | None" = None) -> dict | None:
    """Try one door. **A failure is logged at debug only**; the caller decides
    whether it warrants an alarm.

    raw.githubusercontent is **deliberately last and the least reachable**, so a
    WARNING per door would log "could not fetch the queue file" on runs where the
    doors ahead of it succeeded. **One door failing is not a fault; all of them
    failing is.**
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ark-relay"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, OSError, ValueError,
            http.client.HTTPException) as exc:
        # IncompleteRead is not a subclass of OSError; leaving it out lets the
        # exception escape.
        _log_inbox.debug("待办：%s 没答应（%s）", _netloc(url), exc)
        if errors is not None:
            errors.append(f"{_netloc(url)}: {exc}")
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log_inbox.warning("待办文件不是合法 JSON: %s", exc)
        return None
    return data if isinstance(data, dict) else None


class Inbox:
    """Remembers which version has been applied; applies newer ones once."""

    def __init__(self, state_dir: Path, url: str = "", automas_dir: Path | None = None):
        self.url = url or DEFAULT_URL
        self.state_dir = Path(state_dir)
        self.automas_dir = automas_dir
        # Whether the last poll actually reached the queue file. "Could not
        # fetch" and "fetched, nothing new" both return quietly from poll();
        # the caller needs to tell them apart to keep retrying the former -
        # a pause order that fails to download is not a pause order.
        self.last_fetch_ok = True

    def _store(self):
        from ark_relay.core.statestore import StateStore  # noqa: PLC0415
        return StateStore(self.state_dir)

    @property
    def applied_version(self) -> int:
        try:
            return int(str(self._store().get("queues", "inbox_version") or 0).strip() or 0)
        except (TypeError, ValueError):
            return 0

    def _remember(self, version: int) -> None:
        # Atomic write: this can run inside the shutdown countdown (service.py does
        # the deferred inbox pass after tick(), and tick may already have issued
        # `shutdown /s /t 60`). A corrupted record reads back as version 0, which
        # would replay the whole previous batch of commands on the next boot. Writes
        # to state.json are atomic.
        self._store().set("queues", "inbox_version", str(version))

    def poll(self) -> tuple[int, list[str]]:
        """Fetch, and apply if it is newer. Returns (version_now, messages).

        Messages are empty when nothing changed - the overwhelmingly common
        case. This runs on a machine that boots twice a day and is expected to
        do nothing at all on almost every one of those boots.
        """
        have = self.applied_version
        data = self._fetch_or_none()
        self.last_fetch_ok = data is not None
        if data is None:
            return have, []

        try:
            version = int(data.get("version") or 0)
        except (TypeError, ValueError):
            _log_inbox.warning("待办文件的 version 不是整数，忽略")
            return have, []

        # Strictly greater, never merely different. raw.githubusercontent is a
        # CDN and can serve a stale copy for a few minutes; on "different" that
        # would re-apply an older plan and flip the machine back and forth.
        if version <= have:
            return have, []

        note = str(data.get("note") or "").strip()
        commands = data.get("commands")
        if not isinstance(commands, list):
            _log_inbox.warning("待办文件 v%s 没有 commands 数组，忽略", version)
            return have, []

        name = str(data.get("name") or "").strip()
        _log_inbox.info("收到待办 v%s（当前 v%s）：%s", version, have, note or "(无说明)")
        try:
            messages = self._apply(commands)
        except Exception as exc:  # noqa: BLE001
            # An exception mid-batch (copy2 on a locked file, disk full) is
            # caught here so a half-applied batch still records its version and
            # says what happened; otherwise the next boot would re-apply the
            # whole batch (skip_today landing on a day nobody named, edits
            # repeated).
            _log_inbox.exception("待办 v%s 应用中途出错", version)
            messages = [f"✗ 应用中途出错：{exc}。出错前的指令已生效，出错后的没有；"
                        "这批指令不会再执行一遍——请核对设置，没生效的指令用新版本重发"]
        # Recorded even when a command failed. Retrying the same broken batch
        # on every boot would push the same failure every morning and never
        # get better; the failure is reported instead, and the fix is a new
        # version - which is also how the operator learns it did not land.
        self._remember(version)
        # Item 0 of the return value is the push title, the rest is the body;
        # the operator's note goes in the body so it is shown. A batch that went
        # through is our own order.sh order and stays out of his sight (CLAUDE.md
        # 「测试不进他眼」): its title is on notify's log-only list. Any ✗ line is a
        # failure and takes the phone's failure title, which boot_stages' collect
        # sends to the group (docs/NOTIFICATIONS.md, the 「📱 配置没改成」 row).
        head = texts.CONFIG_FAILED if receipt_failed(messages) else texts.INBOX_APPLIED
        title = f"{head}：{name}" if name else head
        body = [f"{both_clocks(datetime.now(tz=SERVER_TZ))} · {label_version(version)}"]
        if note:
            body += ["", note]
        return version, [title, "", *body, "", *messages]

    def _fetch_or_none(self) -> dict | None:
        data = _fetch(self.url)
        if data is None and self.url != DEFAULT_URL:
            # A configured address that no door can serve is almost always a
            # stale one (a file removed from the repo while .env still points at
            # it). Fall back to the built-in address and say so loudly - a dead
            # command channel must not stay quiet.
            _log_inbox.warning("配置的待办地址 %s 一扇门都取不到，改试内置地址 %s", self.url, DEFAULT_URL)
            data = _fetch(DEFAULT_URL)
            if data is not None:
                self.url = DEFAULT_URL
                _log_inbox.warning("内置地址取到了：.env 里的 ARK_INBOX_URL 指着一个已经不存在的文件，请删掉那一行")
        return data

    def _apply(self, commands: list) -> list[str]:
        out: list[str] = []
        others = [c for c in commands if isinstance(c, dict)]

        for cmd in others:
            act = cmd.get("action")
            if act == "queue":
                if not self.automas_dir:
                    out.append("✗ 队列：找不到 AUTO-MAS 目录，跳过")
                    continue
                ok, detail = queues.apply(
                    self.automas_dir, str(cmd.get("name") or ""),
                    cmd.get("enabled"), cmd.get("scripts"), state_dir=self.state_dir)
                out.append(("✅ " if ok else "✗ ") + detail)
            elif act == "sanity_plan":
                # Decides where MaaEnd spends its sanity. This writes the AUTO-MAS
                # **master copy** -- MaaEnd's own copy is overwritten wholesale from the
                # master on every startup.
                if not self.automas_dir:
                    out.append("✗ 理智方案：找不到 AUTO-MAS 目录，跳过")
                    continue
                ok, detail = sanity_plan.set_plan(
                    self.automas_dir, str(cmd.get("tab") or ""),
                    str(cmd.get("line") or ""), str(cmd.get("rewards_set") or ""),
                    str(cmd.get("location") or ""))
                out.append(("✅ 理智方案：" if ok else "✗ 理智方案：") + detail)
            else:
                # The file can only be written by whoever can push to the repo, so
                # authorship is the confirmation that gate ② asks for.
                ok, detail = apply_command({**cmd, "confirmed": True})
                # On success report only the human-readable part; the internal action
                # name is added only on failure, where it is a diagnostic clue.
                out.append(f"✅ {detail}" if ok else f"✗ {act}: {detail}")
        return out


# same logger as phone.py: log lines keep their name


class Mailbox:
    """One mailbox: fetches commands, publishes state, holds the long-lived
    connection."""

    def __init__(self, topic: str, pin: str, state_dir: Path, cos=None):
        self.topic = (topic or "").strip()
        self.pin = (pin or "").strip()
        self.state_dir = Path(state_dir)
        self.quota = Quota(self.state_dir)
        # The bucket the whole state goes to (state_cos); None keeps the old
        # pieces-on-ntfy path.
        self.cos = cos
        self._seen = self._load_seen()
        # Stopping the service must be able to sever this connection immediately.
        # A read timeout alone is not enough: worst case it waits out a whole
        # timeout period, while a Windows service stop only grants 30 seconds of
        # grace, after which the service hangs in STOP_PENDING.
        self._resp = None
        # Why the last publish() returned False, in words for the log line the
        # caller writes (boot_stages.publish_state): one WARNING per state the
        # phone cannot see, with its reason, instead of one per piece / try.
        self.last_error = ""
        # The boot read of the mailbox failed (fetch): listen() reads it again
        # once ntfy answers, so presses made while the machine was off are not
        # lost to a timeout.
        self.backlog_missed = False
        self.backlog_why = ""      # why that boot read failed, for the line at the late read
        # The late read that made up for it: {"at", "n", "why"} (machine check #41).
        self.backlog_late: "dict | None" = None
        # The held stream as the machine check #45 sees it: up or not, since
        # when it has been down, and every drop of this process (newest last).
        self.connected = False
        self.down_since: "float | None" = None
        self.drops: "list[dict]" = []
        # How the last state that got out reached the phone (publish): 「腾讯云」
        # (the App reads the object) or 「手机信箱」 (ntfy carried it whole).
        self.last_route = ""
        # ntfy's time of the newest line the mailbox has read (fetch or the
        # stream); a reconnect asks for everything after it (_since).
        self._mark: "int | None" = None
        self._sleep = time.sleep
        # What the previous process had read up to (queues/phone_mark), and the
        # last mark this one wrote there (MARK_SAVE_SEC).
        self._prev_mark = self._load_mark()
        self._mark_saved: "int | None" = None
        # This boot's window the mailbox could not read ({"from", "to", "boot"},
        # see _note_blind), None when there is none.
        self.blind: "dict | None" = None
        self._booted = int(time.time())
        if self.enabled:
            self._note_blind(self._booted)

    @property
    def enabled(self) -> bool:
        return bool(self.topic and self.pin)

    # ---------- what the mailbox could not read ----------
    # ntfy keeps a message NTFY_CACHE_SEC. When the previous process last read
    # the mailbox longer ago than that, the presses made between its last read
    # and (now - NTFY_CACHE_SEC) are gone before this boot can read them, while
    # the phone still shows 「已寄出，等机器开机」. The window is recorded here, kept
    # on disk and carried in every state (mailbox_status -> relay.信箱空窗), so
    # the phone can tell those presses from ones still waiting. Whether anything
    # was pressed in it the relay cannot know, so it is an INFO line, not an
    # alarm.

    def _load_mark(self) -> "int | None":
        try:
            v = self._store().get("queues", "phone_mark")
        except Exception:  # an unreadable mark only means no gap is reported
            log.warning("上次读手机信箱读到哪儿没读出来，这次开机不判断有没有读不到的时段", exc_info=True)
            return None
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _save_mark(self, *, force: bool = False, upto: "int | None" = None) -> None:
        """Keep how far the mailbox has been read (`upto`, else the mark) on disk:
        at most every MARK_SAVE_SEC unless `force`."""
        m = upto if upto is not None else self._mark
        if m is None:
            return
        m = int(m)
        if self._mark_saved is not None and (m <= self._mark_saved or
                                             (not force and m - self._mark_saved < MARK_SAVE_SEC)):
            return
        try:
            self._store().set("queues", "phone_mark", m)
        except OSError:
            log.warning("手机信箱读到哪儿没存下来，下次开机算读不到的时段会偏长", exc_info=True)
            return
        self._mark_saved = m

    def _note_blind(self, read_at: int) -> None:
        """Record the window this boot cannot read: from the previous process's
        last read to `read_at` - NTFY_CACHE_SEC. Nothing when there is no previous
        read on disk or it is recent enough."""
        prev = self._prev_mark
        if prev is None:
            return
        edge = int(read_at) - NTFY_CACHE_SEC
        if prev >= edge:
            return
        gap = {"from": int(prev), "to": edge, "boot": self._booted}
        if gap == self.blind:
            return
        self.blind = gap
        try:
            store = self._store()
            kept = store.get("queues", "phone_blind")
            kept = [g for g in kept if isinstance(g, dict) and g.get("boot") != gap["boot"]] \
                if isinstance(kept, list) else []
            store.set("queues", "phone_blind", [*kept, gap][-BLIND_KEEP:])
        except OSError:
            log.warning("读不到的时段没存下来，手机上这次看不到", exc_info=True)
        log.info("📱 上次读到手机信箱是 %s，这次 %s 读，隔了 %.1f 小时，超过 ntfy 只留 %d 小时："
                 "%s 到 %s 之间手机发的指令已被 ntfy 清掉，机器读不到（状态里 relay.信箱空窗 带着这一段）",
                 _bj(prev), _bj(read_at), (int(read_at) - prev) / 3600, NTFY_CACHE_SEC // 3600,
                 _bj(prev), _bj(edge))

    # ---------- remembering which messages were handled ----------
    # Each boot fetches the last 24 hours of messages in one go, and most of them
    # were already executed on the previous boot. Recording ntfy's own message id
    # keeps the same command from running twice.

    def _store(self):
        from ark_relay.core.statestore import StateStore  # noqa: PLC0415
        return StateStore(self.state_dir)

    def _load_seen(self) -> "list[str]":
        data = self._store().get("queues", "phone_seen")
        return [str(x) for x in data] if isinstance(data, list) else []

    def _save_seen(self) -> None:
        try:
            self._store().set("queues", "phone_seen", list(self._seen[-SEEN_KEEP:]))
        except OSError:
            log.warning("处理过的消息 id 存不下来，同一条指令可能被执行两次",
                        exc_info=True)

    # ---------- publishing ----------

    INLINE_MAX = 4096
    MAX_BODY = INLINE_MAX      # old name, kept for callers and tests
    # Room for the envelope around each slice.
    CHUNK_ROOM = 400

    def publish(self, body: dict, kind: str = "state") -> bool:
        """Send one state where the phone reads it. True when the phone can read
        it: stored on COS (the App reads the object on open, on refresh and on
        the notice), or carried whole by ntfy (inline, or every piece). False
        sets `last_error` to why, in words, for the caller's one log line. A
        state stored on COS is True even when the one-line notice after it is
        refused."""
        self.last_error = ""
        self.last_route = ""
        if not self.enabled:
            self.last_error = "没配手机信箱"
            return False
        data = pack(self.pin, body, kind).encode("utf-8")
        if len(data) > self.INLINE_MAX:
            packed = pack(self.pin, body, kind, gz=True).encode("utf-8")
            if len(packed) < len(data):
                log.info("状态 %d 字节，压缩到 %d 字节", len(data), len(packed))
                data = packed
        # The whole envelope goes to COS on every push, so the App's read on
        # open / refresh always finds the newest state (state_cos).
        cos_why = ""
        if kind == "state" and self.cos is not None:
            cos_why = self._cos_put(data)
        stored = kind == "state" and self.cos is not None and not cos_why
        if len(data) <= self.INLINE_MAX:
            if self._post(data, kind):
                self._carried_by_ntfy(cos_why)
                self.last_route = "腾讯云" if stored else "手机信箱"
                return True
            if stored:
                self._carried_by_cos("state")
                self.last_error = ""
                self.last_route = "腾讯云"
                return True
            self.last_error = self._both(cos_why, self.last_error)
            return False
        if stored:
            self._notice(data)
            self.last_route = "腾讯云"
            return True
        parts = pack_chunks(self.pin, body, kind,
                            self.INLINE_MAX - self.CHUNK_ROOM)
        log.info("状态 %d 字节，切成 %d 条普通消息发（附件只活 3 小时，消息活 12 小时）",
                 len(data), len(parts))
        for n, piece in enumerate(parts):
            if not self._post(piece.encode("utf-8"), kind):
                # The piece has had its own retry (_post). The phone joins a set
                # only when all n pieces are there (pack_chunks) and keeps the
                # last complete one on screen meanwhile (web/net.js latestState
                # walks back to it), so the rest of a broken set is dead weight
                # and is not sent.
                if n + 1 < len(parts):
                    log.info("第 %d/%d 片没发出去（%s），这一份状态剩下的 %d 片不发了"
                             "（缺一片手机也拼不起来，手机上留着上一份完整的）",
                             n + 1, len(parts), self.last_error, len(parts) - n - 1)
                self.last_error = self._both(
                    cos_why, f"切成 {len(parts)} 片发 ntfy，第 {n + 1} 片没发出去：{self.last_error}")
                return False
        self._carried_by_ntfy(cos_why)
        self.last_route = "手机信箱"
        return True

    @staticmethod
    def _carried_by_ntfy(cos_why: str) -> None:
        """COS refused this state (cos_why) and ntfy carried it: a fault another
        route got over, so the daily report only (why: USER-SWITCHES.txt at
        mailbox.py:Mailbox._carried_by_ntfy). Nothing when COS took it."""
        if cos_why:
            log.warning("状态没存上腾讯云，这一份改走手机信箱发到了\n腾讯云：%s", cos_why,
                        extra=errwatch.recovered())

    def _carried_by_cos(self, what: str) -> None:
        """ntfy did not take `what` ("state": the state itself, "notice": the
        one-line notice of it; why in last_error) and the state is on COS, where
        the App reads it on open and on refresh: a fault COS got over, the daily
        report only. ntfy's day quota used up is not a new fault (Quota.mark_full
        says it once a day, as its own WARNING): INFO."""
        if self.quota.full():
            log.info("状态已存到腾讯云 COS；ntfy 上%s没发出去（%s），App 打开或刷新时照样读得到",
                     "那一条" if what == "state" else "的通知", self.last_error)
            return
        log.warning("状态%s没发到手机信箱，状态已存到腾讯云，手机打开或刷新时照样读得到\n手机信箱：%s",
                    "" if what == "state" else "的通知", self.last_error, extra=errwatch.recovered())

    @staticmethod
    def _both(cos_why: str, ntfy_why: str) -> str:
        """The reason a state reached neither place."""
        if cos_why:
            return f"腾讯云 COS 没存上（{cos_why}），ntfy 也没发出去（{ntfy_why}）"
        return ntfy_why

    def _notice(self, data: bytes) -> None:
        """The one-line 「state <ts> <bytes>」 notice that a new state is on COS.
        Optional: the App also reads the object on open and on refresh, so a
        notice that does not go out is an INFO line, never a failed state."""
        total = self.quota.total()
        if total >= NOTICE_STOP_AT:
            log.info("状态已存到腾讯云 COS；ntfy 今天已用 %d 条（到 %d 条就不发通知），"
                     "App 打开或刷新时读得到", total, NOTICE_STOP_AT)
            return
        # One short notice instead of the pieces: a state is about 4 pieces, and
        # the day's 250 messages are shared with the beats.
        if not self._post(f"state {int(time.time())} {len(data)}".encode("ascii"), "state"):
            self._carried_by_cos("notice")
            self.last_error = ""

    COS_TIMEOUT = 8

    def _cos_put(self, data: bytes) -> str:
        """PUT the packed envelope to state_key(topic). '' when stored, else why
        not - the caller then sends the state over ntfy, and only when that
        fails too is it a fault (one WARNING, by the caller)."""
        why = cos_put(self.cos, state_key(self.topic), data, self.COS_TIMEOUT)
        if why:
            log.info("状态没能存到腾讯云 COS（%s），这一份改走 ntfy", why)
        return why or ""

    # Transient failures get one more try after a pause: a network exception
    # (a read timeout, for example), ntfy's request-rate refusal 42901 (back in
    # seconds) and a 5xx from ntfy's front (502). The pause is RETRY_AFTER,
    # longer when the answer carries Retry-After (at most RETRY_AFTER_MAX).
    # Never retried: 42908, the day's quota (back at 08:00 Beijing), and any
    # other 4xx: the same body gets the same answer.
    RETRY_AFTER = 3.0
    RETRY_AFTER_MAX = 30.0
    ATTEMPTS = 2
    POST_TIMEOUT = 20

    def _post(self, data: bytes, kind: str) -> bool:
        """POST one message to the topic. Never raises; False sets last_error."""
        self.last_error = ""
        if self.quota.full():
            # ntfy said 42908 today (Quota.mark_full logged it once): a post
            # would only be refused again.
            self.last_error = "ntfy 今天的额度已经用完（北京时间 8 点清零）"
            return False
        req = urllib.request.Request(f"{NTFY}/{self.topic}", data=data,
                                     method="POST",
                                     headers={"User-Agent": _UA,
                                              "Title": kind})
        why, waited = "", 0.0
        for i in range(self.ATTEMPTS):
            hint = 0.0
            try:
                with urllib.request.urlopen(req, timeout=self.POST_TIMEOUT) as r:
                    status = r.status
                if 200 <= status < 300:
                    self.quota.add(kind)
                    if i:
                        # The retry got it through: a fault the relay got over by
                        # itself, the daily report only (USER-SWITCHES.txt, Mailbox._post).
                        log.warning("发到手机信箱第一次没成，%.0f 秒后再发一次，发出去了\n第一次：%s",
                                    waited, why, extra=errwatch.recovered())
                    return True
                self.last_error = f"ntfy 回 {status}"
                return False
            except urllib.error.HTTPError as exc:
                code, text = _ntfy_code(exc)
                why = f"ntfy 回 {exc.code}" + (f" {code}" if code else "") + (f" {text}" if text else "")
                if code == 42908:
                    self.quota.mark_full(why)          # the day's one WARNING
                    self.last_error = f"{why}（今天的额度用完了，北京时间 8 点清零）"
                    return False
                if exc.code != 429 and exc.code < 500:
                    self.last_error = why
                    return False
                hint = _retry_after(exc)
            except Exception as exc:  # noqa: BLE001 - timeout, reset, DNS
                why = _why(exc)
            if i + 1 < self.ATTEMPTS:
                wait = max(self.RETRY_AFTER, min(hint, self.RETRY_AFTER_MAX))
                log.info("发到信箱没成（%s），%.0f 秒后再试一次", why, wait)
                self._sleep(wait)
                waited += wait
        self.last_error = f"{why}（试了 {self.ATTEMPTS} 次）"
        return False

    # ---------- fetching (once per boot) ----------

    def fetch(self, since: str = "24h") -> "list[dict]":
        """Fetch every command waiting in the mailbox in one go. Not polling -
        called once, at boot. ntfy hands back at most NTFY_CACHE_SEC of it
        whatever `since` says; what is older is the window _note_blind records.

        When ntfy does not answer (a read timeout at boot) it returns [] and
        sets backlog_missed;
        listen() reads the mailbox again as soon as ntfy answers. So a miss
        here loses nothing and is an INFO line; ntfy staying unreachable is
        the outage listen() reports."""
        if not self.enabled:
            return []
        try:
            out = self._read_backlog(since)
        except Exception as exc:  # noqa: BLE001 - any failure: read again from listen()
            self.backlog_missed = True
            self.backlog_why = _why(exc)
            log.info("开机读手机信箱没成（%s），手机通道连上后再补读；补读到了写进日报", self.backlog_why)
            return []
        self.backlog_missed = False
        return out

    def _read_backlog(self, since: str = "24h") -> "list[dict]":
        """The commands waiting in the mailbox not yet handled; raises when ntfy
        cannot be read."""
        url = f"{NTFY}/{self.topic}/json?poll=1&since={since}"
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        started = int(time.time())
        if self.backlog_missed:
            # The boot read failed and this is the late one: ntfy has dropped
            # more since boot, so the window it cannot reach is wider now.
            self._note_blind(started)
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode("utf-8", "replace")
        out: list[dict] = []
        seen = set(self._seen)
        fresh: list[str] = []
        newest = None
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                env = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(env, dict):
                continue
            if isinstance(env.get("time"), int):
                newest = env["time"] if newest is None else max(newest, env["time"])
            if env.get("event") != "message":
                continue
            mid = str(env.get("id") or "")
            if mid and mid in seen:
                continue          # already executed on a previous boot
            raw_msg = str(env.get("message") or "")
            msg = unpack(self.pin, raw_msg)
            if msg and msg.get("kind") == "cmd":
                out.append(stamp(msg, env, "backlog"))
                if mid:
                    fresh.append(mid)      # commands only - see SEEN_KEEP
            elif mid and stale_cmd(self.pin, raw_msg):
                fresh.append(mid)          # dropped for its age: handled for good
        if fresh:
            self._seen = [*self._seen, *fresh]
            self._save_seen()
        # Read up to here: the stream asks for what came after. ntfy's own
        # clock when a message gave it; else ours, five minutes back for skew.
        self._mark = newest if newest is not None else started - 300
        # The poll covered everything up to the moment it was asked, also when
        # the newest message in it is older (the same five minutes for skew).
        self._save_mark(force=True, upto=max(self._mark, started - 300))
        return out

    # ---------- listening (long-lived connection, zero polling) ----------

    def close(self) -> None:
        """Sever the held connection so listen() comes out of its blocking read
        immediately.
        """
        r, self._resp = self._resp, None
        self._save_mark(force=True)
        if r is not None:
            sock = getattr(getattr(getattr(r, "fp", None), "raw", None), "_sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    log.debug("手机通道的连接已经断了，不用再断", exc_info=True)
                if config.IS_WINDOWS:
                    try:
                        socket.close(sock.detach())
                    except OSError:
                        log.debug("手机通道的连接关不掉，忽略", exc_info=True)
            try:
                r.close()
            except Exception:
                log.debug("手机通道关不掉，忽略", exc_info=True)

    def _since(self) -> str:
        """`since` for the next subscription: everything after the newest line
        already read (30 s of overlap; message ids de-duplicate), at most 12
        hours back (ntfy keeps no more); 10m before anything was read."""
        if self._mark is None:
            return "10m"
        return str(max(int(self._mark) - 30, int(time.time()) - 12 * 3600))

    # A dropped stream is picked up again and asks for everything after the
    # newest line it read (_since), so a drop loses nothing and is an INFO line
    # (drops seen: read timeouts, 502 Bad Gateway, a reset by the peer).
    # A channel that stays down OUTAGE_SEC is a fault: the phone's presses wait
    # in ntfy and the page gets no answer. One WARNING when an outage reaches
    # it (the same outage going on is not a new fault).
    # The reconnect decides the rest (why: USER-SWITCHES.txt at
    # mailbox.py:Mailbox._connected): an outage with a fault in it (a 5xx, a reset, a
    # connection that could not be made) ends in ONE WARNING marked
    # errwatch.recovered() - the daily report only; a stream that only timed
    # out reading while it was open (idle) and came straight back is normal
    # and stays INFO.
    OUTAGE_SEC = 600

    def _late_backlog(self, on_cmd, on_backlog) -> None:
        """Read the boot backlog fetch() missed (raises while ntfy still does not
        answer) and hand it on. Read now: a fault the relay got over by itself,
        the daily report only (USER-SWITCHES.txt, Mailbox._late_backlog)."""
        cmds = self._read_backlog()
        self.backlog_missed = False
        self.backlog_late = {"at": time.time(), "n": len(cmds), "why": self.backlog_why}
        log.warning("开机时没读到手机信箱，手机通道连上后补读到了 %d 条指令\n开机那次：%s",
                    len(cmds), self.backlog_why or "原因没记下", extra=errwatch.recovered())
        try:
            if on_backlog is not None:
                on_backlog(cmds)
            else:
                for body in cmds:
                    on_cmd(body)
        except Exception:
            log.exception("补读到的手机指令处理出错，连接继续")

    DROPS_KEEP = 50

    def report(self) -> dict:
        """The channel as the machine checks #41 / #45 read it at the end of a shift."""
        return {"connected": self.connected, "down_since": self.down_since,
                "drops": [dict(d) for d in self.drops[-self.DROPS_KEEP:]],
                "backlog_missed": self.backlog_missed, "backlog_why": self.backlog_why,
                "backlog_late": dict(self.backlog_late) if self.backlog_late else None,
                "blind": dict(self.blind) if self.blind else None}

    @staticmethod
    def _connected(down_since: "float | None", fault: str, warned: bool) -> None:
        """Say the stream is (back) up. An outage with a fault in it, or one pushed
        at OUTAGE_SEC, ends in one WARNING marked errwatch.recovered() - the daily
        report only; one that was only an idle read timeout is INFO."""
        if down_since is None:
            log.info("📱 手机通道已连上（长连接，不轮询）")
        elif fault or warned:
            log.warning("手机通道断过 %.0f 秒，已经自己连上，断开期间的指令照样补收%s\n断开原因：%s",
                        time.time() - down_since, "（期间报过群）" if warned else "",
                        fault or "读的时候超时", extra=errwatch.recovered())
        else:
            log.info("📱 手机通道又连上了（断了 %.0f 秒，断开期间的指令照样补收）",
                     time.time() - down_since)

    def listen(self, on_cmd, stop, on_backlog=None) -> None:
        """Connect and hold; the server pushes only when there is a message.
        Exits when `stop()` returns true.

        `on_backlog(cmds)` takes the boot backlog when fetch() could not read
        it and this loop later could (each command to on_cmd when not given).

        The reconnect backoff follows the same reasoning as the WMI subscription
        in service.py: a dropped connection has to be picked back up, but a drop
        must not turn into a burst of retries.
        """
        if not self.enabled:
            return
        delay = 5
        down_since: "float | None" = None    # first failure since the stream last worked
        warned = False
        fault = ""                           # the first drop of this outage that was a fault
        while not stop():
            streaming = False                # the stream was open when it dropped
            try:
                if self.backlog_missed:
                    self._late_backlog(on_cmd, on_backlog)   # raises while ntfy still does not answer
                # **`since` is mandatory**: a streaming subscription delivers only
                # messages that arrive while connected, so a refresh sent from the
                # phone during the few seconds of a reconnect is lost forever.
                # With `since`, a reconnect picks up what was missed;
                # anything already handled is deduplicated by message id, so
                # nothing runs twice.
                url = f"{NTFY}/{self.topic}/json?since={self._since()}"
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                # **timeout=None is forbidden**: the read would block
                # indefinitely, this thread would hang on service stop, and the
                # service would be stuck in STOP_PENDING. ntfy sends a
                # keepalive every 45 seconds, so a 90-second read timeout fires
                # only on a stalled connection; the outer loop reconnects.
                with urllib.request.urlopen(req, timeout=90) as r:
                    self._resp = r
                    self._connected(down_since, fault, warned)
                    down_since, warned, delay, fault = None, False, 5, ""
                    self.connected, self.down_since = True, None
                    streaming = True
                    for line in r:
                        if stop():
                            return
                        line = line.decode("utf-8", "replace").strip()
                        if not line:
                            continue
                        try:
                            env = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(env, dict):
                            continue
                        if isinstance(env.get("time"), int):
                            self._mark = env["time"]      # keepalives too: read up to here
                            self._save_mark()             # on disk every MARK_SAVE_SEC
                        if env.get("event") != "message":
                            continue
                        mid = str(env.get("id") or "")
                        if mid and mid in set(self._seen):
                            continue
                        raw_msg = str(env.get("message") or "")
                        msg = unpack(self.pin, raw_msg)
                        if not msg or msg.get("kind") != "cmd":
                            if mid and stale_cmd(self.pin, raw_msg):
                                # Dropped for its age: handled for good.
                                self._seen = [*self._seen, mid]
                                self._save_seen()
                            continue
                        if mid:
                            self._seen = [*self._seen, mid]
                            self._save_seen()
                        try:
                            on_cmd(stamp(msg, env, "live"))
                        except Exception:
                            log.exception("手机指令处理出错，连接继续")
            except Exception as exc:  # noqa: BLE001 - any drop: reconnect
                if stop():
                    return
                now = time.time()
                if down_since is None:
                    down_since = now
                idle = streaming and _idle_timeout(exc)
                self.connected, self.down_since = False, down_since
                self.drops = [*self.drops[-(self.DROPS_KEEP - 1):],
                              {"at": now, "why": _why(exc), "idle": bool(idle)}]
                if not fault and not idle:
                    fault = _why(exc)
                if not warned and now - down_since >= self.OUTAGE_SEC:
                    warned = True
                    log.warning("手机通道连不上 ntfy 已经 %.0f 分钟（%s）：这段时间手机发的指令到不了机器，"
                                "页面也等不到应答%s；连上后自动补收这段时间的指令",
                                (now - down_since) / 60, _why(exc),
                                "，开机前手机上按的指令也还没读到" if self.backlog_missed else "")
                else:
                    log.info("手机通道断了（%s），%d 秒后重连", _why(exc), delay)
            # The wait before reconnecting. sleep here is not polling - it waits
            # to get the connection back, it does not go asking whether there are
            # new messages.
            for _ in range(delay):
                if stop():
                    return
                self._sleep(1)
            delay = min(delay * 2, 60)


LIVE_ONLY_ACTIONS = ("estop",)


def receipt_target(body: "dict | None") -> str:
    """Which setting or queue an order is about, for its receipt's "target" (modes.add_receipt):
    set_master game:path, set_config script:path, skip_today / unskip_today the queue; ''
    for any other order. The fields are the ones commands.apply_command reads."""
    body = body or {}
    action = str(body.get("action") or "")
    if action == "set_master":
        return f"{body.get('game') or ''}:{body.get('path') or ''}"
    if action == "set_config":
        return f"{body.get('script') or ''}:{body.get('path') or ''}"
    if action in ("skip_today", "unskip_today"):
        return str(body.get("queue") or "")
    return ""


def _before(body, started) -> bool:
    """True unless ntfy received `body` at or after `started` (unix seconds).

    The same filter also reads the late backlog (mailbox._late_backlog, after a
    boot read that timed out), which can carry a press made while this process
    was already up - that one is live and must run (status-channel audit A2).
    No start time or no ntfy time: treated as before, as it always was."""
    if started is None:
        return True
    try:
        return float(((body or {}).get("_meta") or {}).get("ntfy_time")) < float(started)
    except (TypeError, ValueError):
        return True


def boot_backlog(cmds: list[dict], log, started: float | None = None) -> list[dict]:
    """The mailbox backlog with the live-only presses made before `started` (this
    process's start, unix seconds) dropped, each one logged."""
    out: list[dict] = []
    for body in cmds:
        action = str((body or {}).get("action") or "")
        if action in LIVE_ONLY_ACTIONS and _before(body, started):
            log.warning("信箱里有一条关机期间按的「%s」，开机不执行（当时和现在都没有在跑的东西）", action)
            continue
        out.append(body)
    return out


def _phone_answer(receipt, log, push_state, action: str, sent, ok: bool, msg: str, target: str = "") -> None:
    """Write an order's receipt and push the state: the answer is on the page where he pressed."""
    try:
        receipt(action, sent, ok, msg, target=target)
    except Exception:
        log.exception("手机指令回执没记下")
    push_state("改完配置")


def _phone_stamp_sent(body: dict, sent, meta: dict | None) -> None:
    """echo_farm's deadline is read against when it was sent. ntfy's own clock first:
    a phone whose clock runs a few minutes fast would turn 「刷到 21:00」 pressed at
    20:58 into tomorrow's 21:00."""
    ntime = (meta or {}).get("ntfy_time")
    when = ntime if isinstance(ntime, int) else sent
    if when is not None:
        body["sent"] = when


def _monthcard_stamp_at(body: dict, sent, meta: dict | None) -> None:
    """A monthly-card order without `at` (an older App, or a bare add made offline)
    is dated by when it was sent, not when the relay got to it: dated at the drain,
    it beat a later correction made in between and counted the purchase day from the
    drain date (11-08 [D-07])."""
    from datetime import timezone  # noqa: PLC0415
    ntime = (meta or {}).get("ntfy_time")
    when = ntime if isinstance(ntime, int) else sent
    if isinstance(when, int):
        when = datetime.fromtimestamp(when, tz=timezone.utc)
    if isinstance(when, datetime):
        body["at"] = when.isoformat()


def _machine_check(state_dir, event: str, ctx: dict, notifier, log) -> None:
    """Judge the machine checks listening to `event` (machinecheck.py; the phone ones
    are in ark_relay/features/selfcheck/machinechecks/phone_banners.py). Never breaks the phone path."""
    try:
        from ark_relay.features import machinechecks as phone_banners  # noqa: PLC0415
        phone_banners.fire(state_dir, event, ctx, notifier)
    except Exception:
        log.exception("上机核对（%s）没能做", event)


def _push_farm_trouble(notifier, log) -> None:
    """An echo farm stopped by hand (the phone's stop-farm order, the red button) whose
    wrap-up went wrong: the same group alarm as at the deadline (echofarm.push_manual_trouble)."""
    from ark_relay.features import echofarm  # noqa: PLC0415
    try:
        echofarm.push_manual_trouble(notifier)
    except Exception:
        log.exception("刷声骸收工出问题没推出去")


def _phone_execute(apply_command, notifier, log, push_state, receipt,
                   body: dict, action: str, sent, notify: bool, meta: dict | None = None,
                   *, state_dir=None, via: str = "live", queued_at=None) -> None:
    """Apply one order, write its receipt, push the state - live or drained alike.

    `notify` False (an order drained after the run) keeps a success off the
    channels - the receipt is the answer; a failure goes to the group either way.
    `via` / `queued_at` tell the machine check #23 how it got here."""
    from ark_relay.core import engine as _engine_mod  # noqa: PLC0415
    if action == "echo_farm":
        _phone_stamp_sent(body, sent, meta)
    if action == "monthcard" and body.get("at") is None:
        _monthcard_stamp_at(body, sent, meta)
    ok, msg = apply_command(body)
    log.info("📱 手机指令 %s：%s", action, msg)
    _push_farm_trouble(notifier, log)
    # Whatever the order changed or started, the next 「is anything running」
    # asks AUTO-MAS afresh: the drain loop's own next check, and the shutdown
    # decision of the same tick, which would otherwise reuse a 「nothing runs」
    # read from up to three seconds before.
    _engine_mod.forget_scripts_cache()
    try:
        receipt(action, sent, ok, msg, target=receipt_target(body))
    except Exception:
        log.exception("手机指令回执没记下")
    if notify or not ok:
        notifier.send(texts.CONFIG_CHANGED if ok else texts.CONFIG_FAILED, msg, alert=not ok)
    _machine_check(state_dir, "phone_cmd", {"action": action, "ok": ok, "msg": msg, "receipt": (ok, msg),
                                            "via": via, "queued_at": queued_at, "sent": sent}, notifier, log)
    push_state("改完配置")


def _phone_enqueue(queue, log, queued_receipt, raw: dict, action: str, mid: str, sent) -> None:
    """Put one order on the queue (phone.CmdQueue). While a script runs (`queued_receipt`
    given), a new order - or a new press of the same waiting one - is answered at
    once with a 「排队中」 receipt and a state push (D207)."""
    got = queue.add(raw)
    if got == QUEUED:
        log.info("📱 手机指令 %s 排队，等脚本跑完再执行（id %s）", action, mid)
    elif got == RESENT:
        # Pressed again while the same order waits: not queued twice, but this
        # press gets its own receipt (the App matches a receipt to a press by
        # send time).
        log.info("📱 手机指令 %s 又按了一次，和排着的那条一样，不重复排（id %s）", action, mid)
    else:
        log.info("📱 手机指令 %s 已经排过队或执行过，不再重复（id %s）", action, mid)
    if queued_receipt is not None and got in (QUEUED, RESENT):
        queued_receipt(action, sent, receipt_target(raw))


def _make_phone_cmd(engine, notifier, log, hb, push_state, cfg_state_dir=None):
    """Build the callback for what happens after a button is pressed on the phone.

    A separate step because it has two entry points: at boot the commands that
    piled up are worked through one by one, and after that the long-lived
    connection calls it again for every command it hears - both have to be the
    same logic.
    """
    from ark_relay.features.commands import apply_command  # noqa: PLC0415

    # Orders that came in while a script was running wait here for the end of
    # the run (phone.CmdQueue). Same state dir the commands themselves use.
    state_dir = cfg_state_dir if cfg_state_dir is not None else os.environ.get("ARK_STATE_DIR", "./ark-state")
    queue = CmdQueue(state_dir)
    drain_lock = threading.Lock()

    def _receipt(action, sent, ok, msg, queued=False, target=""):
        # "sent" beside "at": the page shows both (「HH:MM 发出 · HH:MM 执行」,
        # web data 5238f367), so the text itself stays the plain answer.
        from ark_relay.features import modes as _modes  # noqa: PLC0415
        _modes.add_receipt(cfg_state_dir, action, ok, msg, sent=sent, queued=queued, target=target)

    def _queued_receipt(action: str, sent, target: str = "") -> None:
        """D207: the moment an order is queued behind a running script, a receipt says
        so and a state goes out, so the App shows 「排队中」 instead of 「没生效」."""
        try:
            _receipt(action, sent, True, texts.PHONE_QUEUED, queued=True, target=target)
        except Exception:
            log.exception("手机指令排队回执没记下")
        push_state("指令排队")

    _execute = functools.partial(_phone_execute, apply_command, notifier, log, push_state, _receipt,
                                 state_dir=state_dir)

    def _refuse_dispatch(action: str, sent) -> None:
        """An order that starts a run, pressed while one is running: answered on the
        page, not queued. Run after the run it would start one more - the whole
        queue again for 「现在跑」, which is how MAA got an extra run and burned
        sanity potions on 2026-09-01 (commands.run_script). No push."""
        msg = f"「{texts.action_name(action)}」没执行：{texts.phone_busy_reason(action)}"
        log.info("📱 手机指令 %s 在跑的时候到，不排队：%s", action, msg)
        _phone_answer(_receipt, log, push_state, action, sent, False, msg)

    def drain() -> int:
        """Run the queued orders, oldest first, once nothing is running. Returns how many ran.

        Called at the top of every engine tick (before the shutdown decision of
        that tick, so a queued 「现在跑」 or skip is seen by it) and right after an
        order is queued while idle. An order that went through is not pushed: the
        receipt and the state are the answer, on the page where he pressed. One
        that failed goes to the group like a live one (_phone_execute); one that
        expired is a WARNING (errwatch pushes it).
        """
        if not len(queue):
            return 0
        n = 0
        held = getattr(push_state, "held", None)
        with drain_lock, (held() if held is not None else contextlib.nullcontext()):
            while True:
                if engine.scripts_running():
                    break           # a run started again; the rest waits for its end
                item = queue.pop()
                if item is None:
                    break
                body = dict(item["body"])
                meta = body.pop("_meta", None) or {}
                # The latest press of it: the final receipt answers every press (D207).
                sent = item_sent(item)
                action = str(body.get("action") or "")
                if action in DISPATCHING_ACTIONS:
                    # Queued before this rule (or behind older orders when a run
                    # started): it would start a run the user did not see coming.
                    _refuse_dispatch(action, sent)
                    n += 1
                    continue
                if cmd_expired(item):
                    msg = (f"「{texts.action_name(action)}」等这一趟跑完时已过了 24 小时，"
                           "过期没执行；需要就重新发一次")
                    log.warning("📱 排队的手机指令 %s 过期没执行（id %s）",
                                action, meta.get("ntfy_id") or "?")
                    _phone_answer(_receipt, log, push_state, action, sent, False, msg, target=receipt_target(body))
                    _machine_check(state_dir, "phone_cmd", {"action": action, "ok": False, "msg": msg,
                                                            "via": "expired", "queued_at": item.get("queued"),
                                                            "sent": sent}, notifier, log)
                    n += 1
                    continue
                log.info("📱 脚本已停，执行排队的手机指令 %s（id %s，%s 排进来）",
                         action, meta.get("ntfy_id") or "?",
                         datetime.fromtimestamp(int(item.get("queued") or 0), tz=SERVER_TZ)
                         .strftime("%H:%M:%S"))
                _execute(body, action, sent, notify=False, meta=meta, via="drained",
                         queued_at=item.get("queued"))
                n += 1
        return n

    def run_phone_cmd(body: dict) -> None:
        """One press from the phone. Refresh only answers with state; everything else really changes config, and notifies the moment it is done."""
        # phone.stamp's "_meta" (when it was sent, how it arrived) is for the log
        # and the receipt only; the command itself goes on without it.
        raw = dict(body or {})
        meta = (body or {}).get("_meta") or {}
        body = {k: v for k, v in (body or {}).items() if k != "_meta"}
        sent = meta.get("sent") if isinstance(meta.get("sent"), int) else None

        def receipt(ok, msg):
            _receipt(action, sent, ok, msg, target=receipt_target(body))

        action = str((body or {}).get("action") or "")
        if action == "refresh":
            # A state that already reached the mailbox answers it (phone.StatePusher):
            # the App's 4-second re-ask and the refreshes read back at boot.
            answered = getattr(push_state, "answered", None)
            if answered is not None and answered(meta.get("ntfy_time")):
                return
            boot_stages.ensure_automas()          # make sure it is alive before reading config
            push_state("手机请求")
            return
        if action == "watch":
            hb.watch()          # the page is open: beat every 30s for the next 10 minutes
            return
        if action == "estop":
            # Red button: it gets pressed precisely while scripts are running,
            # so it must not be blocked by the gate below.
            from ark_relay.features import commands as _cmd  # noqa: PLC0415
            ok, msg = _cmd.estop(state_dir=cfg_state_dir)
            (log.info if ok else log.warning)("🛑 红按钮：%s", msg)
            _push_farm_trouble(notifier, log)
            try:
                receipt(ok, msg)
            except Exception:
                log.exception("红按钮回执没记下")
            # The title has to follow the answer. It used to be 「已停一切」 whatever
            # came back, so the one case that needs the operator - the relay could
            # not get the machine quiet - was pushed to his phone as a success.
            notifier.send(texts.ESTOP if ok else texts.ESTOP_FAILED, msg, alert=not ok)
            _machine_check(state_dir, "estop", {"result": (ok, msg), "reads": dict(_cmd.ESTOP_LAST)},
                           notifier, log)
            push_state("红按钮")
            return
        if action not in ("skip_shutdown", "debug_mode", "echo_farm_stop", "echo_farm_until",
                          "monthcard", "tacet_shots"):
            # Config changed while a script is running gets clobbered by
            # AUTO-MAS's in-memory copy, so the order waits for the end of the
            # run (it used to be dropped with a 「再按一次」 push). An order that
            # comes in while older ones still wait queues behind them, so they
            # run in the order they were pressed.
            running = engine.scripts_running()
            if action in DISPATCHING_ACTIONS:
                # Never queued (see _refuse_dispatch). Older orders still waiting
                # go first, so a setting pressed before it is in place for its run.
                if not running and len(queue):
                    drain()
                    running = engine.scripts_running()
                if running:
                    _refuse_dispatch(action, sent)
                    return
            elif running or len(queue):
                _phone_enqueue(queue, log, _queued_receipt if running else None,
                               raw, action, meta.get("ntfy_id") or "?", sent)
                _machine_check(state_dir, "phone_cmd", {"action": action, "via": "queued", "raw": raw,
                                                        "sent": sent}, notifier, log)
                if not running:
                    drain()
                return
        _execute(body, action, sent, notify=True, meta=meta)

    run_phone_cmd.drain = drain
    return run_phone_cmd


def _start_phone_channel(svc, cfg, engine, notifier, log):
    """Bring up the whole phone channel: mailbox, heartbeat, two background threads.

    A separate step because this section does exactly one thing - let the phone
    both see the state and change the config - and it exposes only one thing to
    the outside: push_state, which reports state and is needed once more before
    shutdown.
    """
    # Fetching once at boot is enough: the machine restarts for every queue run,
    # and the config is almost always changed while it is off, so the next boot
    # is bound to pick it up. Online/offline must not be done by polling; how it
    # is done instead is in phone.py's module docstring.
    # 来龙去脉见 docs/CODE-HISTORY.md「service.py:_stage_inbox_and_phone」
    pass

    # The whole state goes to COS and ntfy only carries a notice (phone.state_cos)
    box = Mailbox(cfg.phone_topic, cfg.phone_pin, cfg.state_dir, cos=state_cos(cfg))
    svc._mailbox = box          # SvcStop uses this to cut the long-lived connection
    # A new process whose 「停止前」 state has not gone out yet: the watchdog's push at a
    # Windows shutdown sends it unless this process's own push did (phone.STOP_PUSHED_FILE).
    pass
    clear_stop_pushed(cfg.state_dir)
    # Every state of this process and whether it reached the phone, plus the
    # heartbeat once it exists: what the machine checks of the phone channel
    # read at the end of a shift (machinechecks/phone_banners.py, #39-#56).
    tally: dict = {"since": time.time(), "n": 0, "ok": 0, "routes": {}, "failed": []}
    beat: list = []

    def _judge_state(why: str, payload, ok: bool) -> None:
        try:
            from ark_relay.features import maintenance as _maint  # noqa: PLC0415
            quota = box.quota
            hb_now = beat[0] if beat else None
            ctx = {"state": payload, "why": why, "ok": ok, "error": box.last_error, "tally": tally,
                   "mailbox": box.report() if hasattr(box, "report") else {},
                   "heartbeat": hb_now.cos_report() if hasattr(hb_now, "cos_report") else {},
                   "quota": {"day": quota.day(), "total": quota.total(), "own": quota.own(),
                             "full": quota.full(), "raw": quota.read()},
                   "maintenance": _maint.stats()}
        except Exception:
            log.exception("上机核对（phone_state）没能做")
            return
        # A service stop has 30 s: no network push from here then - a check that did
        # not hold goes through errwatch's queue (on disk, its own push thread).
        _machine_check(cfg.state_dir, "phone_state", ctx, None if why == "停止前" else notifier, log)
        if why == "关机前":
            # The shift is judged; a machine that stays on starts the next one afresh
            # (the heartbeat's and the bulletins' own counts run on: their base moves).
            tally.update(since=time.time(), n=0, ok=0, routes={}, failed=[],
                         base={"heartbeat": ctx["heartbeat"], "maintenance": ctx["maintenance"]})

    def publish_state(why: str) -> bool:
        if not box.enabled:
            return False
        tally["n"] += 1
        stamp = datetime.now(tz=SERVER_TZ).strftime("%H:%M:%S")
        # The state, the send and its log line are phone.send_state, shared with the
        # watchdog's push at a Windows shutdown (app_main.py stop-push).
        pass
        ok, payload, why_not = send_state(box, cfg, why, log)
        if ok:
            tally["ok"] += 1
            route = getattr(box, "last_route", "") or "没说走哪条"
            tally["routes"][route] = tally["routes"].get(route, 0) + 1
        else:
            tally["failed"].append((stamp, why, why_not))
        _judge_state(why, payload, ok)
        return ok

    pass
    # Callable like the old push_state(why); also skips refreshes a state
    # already answered and folds the boot backlog's pushes into one.
    push_state = StatePusher(publish_state)

    svc._push_state = push_state
    # A skip that engages, fails or is restored writes a receipt on the engine
    # thread; this sends the page the snapshot that carries it.
    engine._push_state = push_state

    pass
    hb = Heartbeat(box.topic, cfg.state_dir, cos=box.cos)   # its beat on COS too
    beat.append(hb)
    run_phone_cmd = _make_phone_cmd(engine, notifier, log, hb, push_state, cfg.state_dir)
    # Orders queued while a script ran are applied at the top of the first tick
    # that finds nothing running - before that tick's shutdown decision.
    engine._phone_drain = run_phone_cmd.drain

    boot_stages.ensure_automas(notifier=notifier)
    started = getattr(getattr(engine, "_started_at", None), "timestamp", lambda: None)()

    def run_backlog(cmds) -> None:
        with push_state.held():
            for body in boot_backlog(cmds, log, started):
                run_phone_cmd(body)

    push_state("开机")
    if box.enabled:
        run_backlog(box.fetch())
        threading.Thread(
            target=lambda: box.listen(
                run_phone_cmd,
                lambda: win32event.WaitForSingleObject(svc.stop_event, 0)
                == win32event.WAIT_OBJECT_0,
                # a boot read that timed out is read again once ntfy answers
                on_backlog=run_backlog),
            name="phone-mailbox", daemon=True).start()
        threading.Thread(
            target=lambda: hb.loop(
                lambda: win32event.WaitForSingleObject(svc.stop_event, 0)
                == win32event.WAIT_OBJECT_0),
            name="phone-heartbeat", daemon=True).start()

    return push_state


# The rest of the phone channel lives in sibling modules (wire, quota, cos_store,
# mailbox, heartbeat, cmdqueue); callers and tests say phone.<name>, so every
# name stays importable from here. A test that rebinds a module global such as
# urllib, time, NTFY or cos_put has to rebind it in the module whose code reads it.


# state_payload runs on every phone-state publish and a WARNING is a group
# message: a block it cannot build is said once per condition (block -> the
# error last said, as WeeklyBossGate._last_error), forgotten once it builds again.
_last_error: dict[str, str] = {}


# ---------- one push_state for the whole relay ----------
#
# A refresh is answered by any state that reaches the mailbox shortly before or
# after it was asked: the page and the App open their stream with since=30s
# before sending "refresh" (web/live.js _ping, ark-remote Live.swift
# pingInner), so a state posted up to 30 s before the press is replayed to
# them. 20 s leaves room for the few seconds a four-piece post takes.
REFRESH_ANSWERED_SEC = 20


class StatePusher:
    """push_state for the whole relay, with two savings on ntfy's 250 a day.

    * A refresh that a state already answers is not answered again. The App
      sends a second refresh 4 s after the first if no state is back yet
      (Live.swift pingInner `resent`), and a state takes ~5-20 s to read and
      post, so without this nearly every press would cost two states. And the
      refreshes pressed while the machine was off all come back out of the
      mailbox at boot, right after the boot state already answered them.
    * While held (the boot backlog), every push is put off and sent once at the
      end, rather than one state per config order in the backlog.

    `publish(why)` builds and sends one state and returns whether it got out.
    Pushes that are not refreshes (改完配置, 红按钮, 关机前, 跳过队列) are never
    skipped - they carry a change the page has to see.
    """

    def __init__(self, publish):
        self._publish = publish
        self._lock = threading.Lock()
        self._done = 0.0               # when the last state that got out finished
        self._held = 0
        self._pending: list[str] = []

    def answered(self, asked_at=None) -> bool:
        """True when a state that got out answers a refresh asked at `asked_at`
        (ntfy's receive time, unix seconds; now when unknown) - logged once."""
        try:
            asked = float(asked_at)
        except (TypeError, ValueError):
            asked = time.time()
        with self._lock:
            done = self._done
        if done and asked <= done + REFRESH_ANSWERED_SEC:
            log.info("📱 手机要刷新（%s 收到）：%s 已发完一份状态，它收得到，不再重发（省 ntfy 额度）",
                     _bj(asked, "%H:%M:%S"), _bj(done, "%H:%M:%S"))
            return True
        return False

    NEVER_HELD = ("停止前", "关机前")

    def __call__(self, why: str) -> bool:
        with self._lock:
            if self._held and why not in self.NEVER_HELD:
                self._pending.append(why)
                return False
        ok = bool(self._publish(why))
        if ok:
            with self._lock:
                self._done = time.time()
        return ok

    @contextlib.contextmanager
    def held(self):
        """`with pusher.held():` - pushes inside are put off and sent once at the end."""
        with self._lock:
            self._held += 1
        try:
            yield self
        finally:
            with self._lock:
                self._held -= 1
                whys = self._pending if self._held == 0 else []
                if self._held == 0:
                    self._pending = []
            if whys:
                names = list(dict.fromkeys(whys))
                self("、".join(names) + (f"（{len(whys)} 次合成一次）" if len(whys) > 1 else ""))


def mailbox_status(state_dir) -> list[dict]:
    """relay.信箱空窗 in the state: the windows the mailbox could not read
    (Mailbox._note_blind), oldest first, each {"从", "到", "开机"} in unix
    seconds. A press sent inside one never reached the machine: ntfy had
    dropped it before the boot read. The App compares an order's send time
    with them (its sent time is on ntfy's clock, Net.send; "从" is ntfy's time
    of the last line read, "到" the machine's boot read minus NTFY_CACHE_SEC)."""
    from ark_relay.core.statestore import StateStore  # noqa: PLC0415
    kept = StateStore(Path(state_dir)).get("queues", "phone_blind")
    out = []
    for g in kept if isinstance(kept, list) else []:
        if isinstance(g, dict) and all(isinstance(g.get(k), int) for k in ("from", "to", "boot")):
            out.append({"从": g["from"], "到": g["to"], "开机": g["boot"]})
    return out


def state_payload(cfg, state_dir: Path) -> dict:
    """The payload the phone displays. Same code config-check reads (snapshot.py)."""
    from ark_relay.features import modes  # noqa: PLC0415
    from ark_relay.features import snapshot  # noqa: PLC0415
    from ark_relay.core import plan  # noqa: PLC0415 - avoids an import cycle
    out: dict = {"at": int(time.time())}
    # Only the keys the phone displays. The full snapshot is not sent: of it the
    # phone gets only the service state and the running scripts ("run"); the
    # queues come from plan.queue_rows and the config from maa_from_files below.
    keep = {k.split(".", 1)[1] for k in SHOWN} | {"关卡", "理智药", "剿灭",
            "作战开关", "活动关优先", "活动关序号"}
    try:
        full = snapshot.read_runtime()
        # The orchestrator is always up while the machine is; listing it made
        # 「现在没有脚本在跑」 impossible to ever show, and 「在跑：AUTO-MAS」 tells him
        # nothing. Only scripts and games count as running.
        from ark_relay.core.config import ORCHESTRATOR_PROC  # noqa: PLC0415
        orch = ORCHESTRATOR_PROC[:-4]
        out["run"] = {"服务": full.get("ark-relay"),
                      "在跑的": [n for n, on in (full.get("程序") or {}).items() if on and n != orch]}
    except Exception:
        log.warning("快照读不到，服务和在跑的程序这次不报", exc_info=True)
    # Arknights only: the MAS fields for the other two games are not sent, see
    # mastercfg. From ScriptConfig.json, like the queues and the plan below
    # (snapshot.maa_from_files): the backend is gone at the service-stop push.
    try:
        maa = snapshot.maa_from_files(getattr(cfg, "automas_dir", None))
        out["config"] = {"MAA": {k: v for k, v in maa.items() if k in keep}}
    except Exception as exc:  # noqa: BLE001
        out["config"] = {"_错误": f"{type(exc).__name__}: {exc}"}
    # The queues from AUTO-MAS's config files, the source "plan" below reads too
    # (plan.queue_rows), not from the snapshot: its queue section needs the
    # backend, which is gone at the service-stop push.
    try:
        out["queues"] = plan.queue_rows(getattr(cfg, "automas_dir", None))
    except Exception as exc:
        log.warning("班次名单读不到", exc_info=True)
        # [] read on the App as "no shift", i.e. every game in the shift - as if
        # real. A row with only `_错误`, like config's marker (audit A3).
        out["queues"] = [{"_错误": f"{type(exc).__name__}: {exc}"}]
    try:
        from ark_relay.features import annihilation, annihilation as garden, weeklyboss  # noqa: PLC0415
        automas = getattr(cfg, "automas_dir", None)
        wb = weeklyboss.WeeklyBossGate(state_dir, automas).settings()
        out["relay"] = {
            # only while it holds: an expired end time would read as "on" on the phone; shutdown also goes by
            # debug_active
            "调试模式": modes.debug_until(state_dir) if modes.debug_active(state_dir) else "",
            # By main stat (target_count set): the counts tick_result last read off the drop
            # lines; "到" is then the backstop, not the end. Counts are this farm's only.
            "刷声骸": (lambda r: {"名字": r.get("name"), "到": r.get("until"), "从": r.get("started"),
                                  **({"目标词条": r.get("target_stat"), "目标数": r.get("target_count"),
                                      "已出": r.get("已出", 0), "总捡": r.get("总捡", 0),
                                      "未读出": r.get("未读出", 0)} if r.get("target_count") else {})}
                       if r else {})(
                __import__("ark_relay.features.echofarm", fromlist=["x"]).current(state_dir)),
            "下次别关机": modes.skip_armed(state_dir),
            # Which queues sit out today: the page shows each as its queue
            # row's switch. "今天跳过" is the first one ("" = none) for pages
            # that read a single name; "今天跳过队列" lists them all (two
            # queues can sit out the same day).
            "今天跳过": modes.skipped_today(state_dir) or "",
            "今天跳过队列": modes.skipped_today_all(state_dir),
            "无音区截图": modes.tacet_shots_on(state_dir),
            # Monthly cards the user registered (monthcard.py, spec 月卡到期提示-规格.md).
            "月卡": status(state_dir),
            "最近指令": modes.receipts(state_dir),
            # Windows the mailbox could not read: presses sent in one never
            # arrived (mailbox_status).
            "信箱空窗": mailbox_status(state_dir),
            "周本": wb,
            # The three "once a week" things share one shape: done this week /
            # the switch / their own settings
            "周常": {
                "剿灭": annihilation.WeeklyGate(state_dir, automas).settings(),
                "周常乐园": garden.GardenGate(state_dir, automas).settings(),
                "周本": wb,
            },
        }
        _last_error.pop("relay", None)
    except Exception as exc:
        # {} read on the phone as switches off, weekly not done, no month
        # cards - as if real. `_错误` marks it, like config (audit A3).
        if _last_error.get("relay") != (key := f"{type(exc).__name__}: {exc}"):
            log.warning("手机状态里中继那一段读不到，App 上的开关、周常和月卡这次是空的", exc_info=True)
            _last_error["relay"] = key
        out["relay"] = {"_错误": key}
    try:
        out["options"] = _options(cfg)
    except Exception:  # noqa: BLE001
        out["options"] = {}
    # Endfield and Wuthering Waves are configured through the scripts' own config,
    # not through MAS - changing it on the MAS side has no effect.
    try:
        from ark_relay.core import mastercfg  # noqa: PLC0415
        out["master"] = {
            "MAA": mastercfg.read_maa(getattr(cfg, "automas_dir", None)),
            "MaaEnd": mastercfg.read_maaend(getattr(cfg, "automas_dir", None),
                                            getattr(cfg, "maaend_dir", None)),
            "OK-WW": mastercfg.read_okww(getattr(cfg, "automas_dir", None),
                                         getattr(cfg, "okww_dir", None)),
        }
    except Exception:
        log.warning("母本配置读不到", exc_info=True)
        out["master"] = {}
    try:
        out["plan"] = plan.next_plan(cfg.automas_dir)
        _last_error.pop("plan", None)
    except Exception as exc:
        if _last_error.get("plan") != (key := f"{type(exc).__name__}: {exc}"):
            log.warning("明日安排算不出来，App 上那一段这次是空的", exc_info=True)
            _last_error["plan"] = key
        out["plan"] = ""
    # The number tiles on the 状态 tab: the page reads the games' stamina itself
    # (web/stamina.js); it only needs the Skland session from here, plus today's
    # run count from the ledger.
    try:
        from ark_relay.features import resources  # noqa: PLC0415
        from ark_relay.core.config import SERVER_TZ  # noqa: PLC0415
        from ark_relay.core.ledger import State  # noqa: PLC0415
        out["密钥"] = {"sk": resources.skland_session(cfg)}
        out["今天"] = resources.today(State(Path(state_dir)), datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
    except Exception:
        log.warning("森空岛会话和今天的统计读不到", exc_info=True)
    return out


# ---------- one state to the phone, and the last one before a stop ----------

STOP_WHY = "停止前"
# Written into the state folder when a 「停止前」 state reached the phone, deleted when
# the phone channel comes up (boot_stages._start_phone_channel). The watchdog service's
# shutdown push (app_main.py stop-push) reads it: present = the relay's own last push
# already got out, so it does not send a second one.
STOP_PUSHED_FILE = "stop-pushed.txt"


def stop_pushed(state_dir) -> bool:
    """True when this relay process's 「停止前」 state reached the phone (STOP_PUSHED_FILE)."""
    return (Path(state_dir) / STOP_PUSHED_FILE).is_file()


def clear_stop_pushed(state_dir) -> None:
    try:
        (Path(state_dir) / STOP_PUSHED_FILE).unlink(missing_ok=True)
    except OSError:
        # INFO: in the relay every WARNING goes to the group, and this needs no person.
        log.info("上次停止前那份的记号删不掉，这次关机时看门服务可能不补发", exc_info=True)


def send_state(box, cfg, why: str, log=log) -> "tuple[bool, dict | None, str]":
    """Build the state and send it through `box`: (reached the phone, payload, why not)."""
    payload = None
    from ark_relay.features import snapshot  # noqa: PLC0415
    # The last state before a stop / power-off must not wait on the process list.
    quiet = snapshot.no_process_query() if why in StatePusher.NEVER_HELD else contextlib.nullcontext()
    try:
        with quiet:
            payload = state_payload(cfg, cfg.state_dir)
        ok = box.publish(payload)
    except Exception as exc:
        log.warning("状态没能上报到手机（%s）", why, exc_info=True)
        return False, payload, f"{type(exc).__name__}: {exc}"[:160]
    if ok:
        log.info("📱 已上报状态到手机（%s；今天 ntfy 已用 %d 条）", why, box.quota.total())
        try:
            from ark_relay.features import macpush  # noqa: PLC0415
            macpush.flush_after_network_ok(cfg)
        except Exception:   # the phone push must not break on the Mac hand-off
            log.info("报警直送 Mac 的补交没起来", exc_info=True)
        if why == STOP_WHY:
            try:
                atomic_write_text(
                    Path(cfg.state_dir) / STOP_PUSHED_FILE, time.strftime("%Y-%m-%d %H:%M:%S\n"))
            except OSError:
                log.warning("停止前那份送到了，记号没写下，关机时看门服务会再发一次", exc_info=True)
        return True, payload, ""
    log.warning("状态没能上报到手机（%s）：%s；手机上留着上一份状态", why, box.last_error or "原因没说")
    return False, payload, box.last_error or "原因没说"

__all__ = ['log', '_last_error', 'REFRESH_ANSWERED_SEC', 'StatePusher', 'mailbox_status', 'state_payload', 'BLIND_KEEP', 'MARK_SAVE_SEC', 'MAX_AGE', 'NTFY', 'NTFY_CACHE_SEC', 'SEEN_KEEP', '_QUIET_ACTIONS', '_UA', '_bj', 'pack', 'pack_chunks', 'stamp', 'unpack', 'HB_CRAWL_SEC', 'HB_FAST_UNTIL', 'HB_KICK_GAP', 'HB_SLOW_SEC', 'HB_SLOW_UNTIL', 'HB_STOP_AT', 'HEARTBEAT_SEC', 'NOTICE_STOP_AT', 'NTFY_ACCOUNT', 'NTFY_DAILY_LIMIT', 'QUOTA_SYNC_SEC', 'WATCH_LEASE_SEC', 'Quota', '_idle_timeout', '_ntfy_code', '_retry_after', '_why', 'ntfy_account', 'STATE_PREFIX', 'cos_get', 'cos_put', 'hb_key', 'state_cos', 'state_key', 'Mailbox', 'HB_COS_SEC', 'Heartbeat', 'CMD_QUEUE_DONE_KEEP', 'CMD_QUEUE_FILE', 'DISPATCHING_ACTIONS', 'QUEUED', 'RESENT', 'SAME', '_CMD_QUEUE_LOCK', '_content', '_item_keys', 'CmdQueue', 'cmd_expired', 'cmd_key', 'item_sent']
