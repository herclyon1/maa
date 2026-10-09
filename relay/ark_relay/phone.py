"""The pipe between the phone and the machine. Zero polling.

The shape the user settled on, 2026-08-31:

* every boot fetches commands once and reports state once
* state is reported once more before shutdown
* pressing "refresh" on the phone gets live state - **only while the machine is
  powered on**
* an online/offline indicator, with no polling

**Why this is not polling**: the machine holds one long-lived connection to ntfy
and then sits still; the server pushes only when there is a message (measured
latency 0.90 s). It is the same shape as the two mechanisms the relay already
uses: the WMI subscription on process start, and directory-change notifications.
A dropped connection is reconnected, and reconnecting is not polling.

**How online is decided**: the phone sends a ping and the machine answers with
state. An answer within a few seconds means it is up; no answer means it is down.
No heartbeat is needed, so no polling is needed.

**The only credential is a PIN** (the user, 2026-08-31:
「留一个 pin 就行了，那那么多事」). The mailbox name itself is a random string
(32 characters in the Mac copy, measured 2026-09-23) kept in the user's phone, the machine's .env and the Mac's
~/.config/ark/push.env (ARK_PHONE_TOPIC / ARK_PHONE_PIN; docs/CONFIG.md
"Relay environment" names the index of every key's location).
State carries game config only, never credentials.

A command pressed on the phone has to survive in the mailbox until the next boot
(the machine powers on twice a day), and ntfy.sh keeps a message 12 hours
(NTFY_CACHE_SEC). A machine off for longer cannot read what was pressed in
between: the window it could not read is recorded at boot (Mailbox.blind) and
carried in the state as relay.信箱空窗, so the phone can tell an order that
never arrived from one still waiting. Commands already handled are remembered
by ntfy's own message id, so nothing runs twice.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import gzip
import json
from datetime import datetime
import logging
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import errwatch

log = logging.getLogger("ark.phone")

# state_payload runs on every phone-state publish and a WARNING is a group
# message: a block it cannot build is said once per condition (block -> the
# error last said, as WeeklyBossGate._last_error), forgotten once it builds again.
_last_error: dict[str, str] = {}

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
# 2026-09-15: the page renews its watch every 8 minutes and every state push is
# two messages, so the old 200 (sized for "a few commands a day", and counting
# every message) rolled over within a morning; at the 09:01 restart six
# commands from the previous evening came back out of the mailbox and were only
# stopped by the "scripts are running" gate. 2000 ids is a couple of weeks of
# watch renewals, and commands older than MAX_AGE are refused anyway.
SEEN_KEEP = 2000
_UA = "ark-relay"


def pack(pin: str, body: dict, kind: str = "cmd", *, gz: bool = False) -> str:
    """The envelope. With `gz=True` the body becomes a gzip+base64 string under
    the field name `gz`.

    Why compress: `options` in the state payload (the pile of dropdown choices)
    accounted for 57% of it, and on 2026-08-31 the whole packet measured 3783
    bytes - 117 short of the limit. One more field would have triggered the
    degradation path: first tomorrow's plan gets dropped, then the options table,
    and the options table is exactly what fills those dropdowns on the phone.
    Dropping it means the feature is gone, and gone **silently**.
    Compressed, it is 2464 bytes, putting the headroom back over a thousand.

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


def _bj(ts, fmt: str = "%m-%d %H:%M:%S") -> str:
    """A unix time as the server clock (Beijing) reads it; "?" when there is none."""
    from .config import SERVER_TZ  # noqa: PLC0415
    try:
        return datetime.fromtimestamp(int(ts), tz=SERVER_TZ).strftime(fmt)
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


# Page traffic, not orders: sent on every page open / every few minutes while the
# page is up. Logging them would bury the orders this line exists for.
_QUIET_ACTIONS = ("refresh", "watch")


def stamp(msg: dict, env: dict, via: str) -> dict:
    """The command body with where it came from attached under "_meta", logged once.

    ntfy keeps a message 12 hours and the relay kept only the moment it acted, so
    three skip orders found at 08:46 on 2026-09-30 could not be traced to when
    they were sent once the topic had expired (the user asked 「谁干的？」 and there
    was no answer). The envelope's ts is the phone's clock at the press, ntfy's
    time is when the server took it, the id is ntfy's own; all three go into
    relay.log, and "sent" into the receipt. `via` is "backlog" for the boot-time
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


# ---------- heartbeat (ToDesk-style online status) ----------
#
# The user, 2026-09-02: 「像 ToDesk 一样，打开就是在线或离线，不用手动刷新，
# 能不能不用轮询实现？手动刷新作为兜底选项而不是经常行为。」
# (Like ToDesk: open it and it is online or offline, no manual refresh - can that
# be done without polling? Manual refresh as a fallback, not a routine.)
#
# How: opening the page sends a "I am watching" (watch) message, and for the next
# 10-minute lease the machine beats to <topic>-hb every 30 seconds; with nobody
# watching it beats not at all. The page receives them live over SSE: a heartbeat
# flips it to "powered on", a bye (graceful service stop) flips it to "powered
# off" instantly, and a hard power cut is caught by the 90-second timeout.
# The page itself never polls - one long-lived connection and a local timer.
#
# Why it must not beat blindly: the anonymous ntfy.sh tier allows **250 messages
# per IP per day** (confirmed 2026-09-02 against /v1/account). Beating blindly
# every 60 seconds is 270 a day, which would shut out state pushes and command
# replies alike. Hence: beat only while someone is watching, and slow down as
# the day's messages run low (see Quota).
#
# 2026-10-02 19:19:08 the quota ran out anyway: 196 beats (hb-2026-10-02.txt)
# plus 13 states of 4 pieces each = 248 messages, and every state after that
# (52 pieces up to 20:54) came back 429 - the phone could not see the machine
# for the rest of the evening. The old cap (150 fast beats, "the rest is left
# for states") was sized on 09-02 when a state was one message; by October a
# state was 43 KB, 13 KB gzipped, four messages. The beat counter could not
# see the states and nothing counted them, so the "rest" was gone before
# anyone noticed. Now one ledger counts every message the relay posts, and the
# cadence follows that total.

HEARTBEAT_SEC = 30       # interval while someone is watching
WATCH_LEASE_SEC = 600    # one "I am watching" lasts 10 min; a foreground page renews it
HB_SLOW_SEC = 300        # interval once the day's total passes HB_FAST_UNTIL
HB_CRAWL_SEC = 1800      # interval once it passes HB_SLOW_UNTIL
# Thresholds on the day's total (all kinds), not on beats alone. Up to 100 the
# page gets its live 30 s beat; up to 180 one every 5 minutes; past that one
# every 30 minutes, so the last 70 of the 250 stay for what the user asked for:
# states (4 messages each), the shutdown state and bye. The page reads the
# cadence from the beat itself ("hb 1800") and widens its window to match
# (web/live.js hbWindowMs, ark-remote Live.swift hbWindowMs), so a slow beat
# still reads 「开机中 · 每 30 分钟报一次」, not a false 「关机」.
HB_FAST_UNTIL = 100
HB_SLOW_UNTIL = 180
# A "watch" asks for a beat at once, so a page that has just opened learns the
# machine is up. The page reads the last 90 s of beats on open (probeHb,
# since=90s), so a beat younger than this one already answers it; the App
# renews its watch every 8 minutes and on every return to the foreground, and
# each of those used to cost a message.
HB_KICK_GAP = 60
NTFY_DAILY_LIMIT = 250
# Hard stops, so the relay alone can never spend the 250 (10-02 it did: 196
# beats + 13 four-piece states). From HB_STOP_AT on the day's total the beat
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

    The ledger alone undercounts: 10-02 22:56 it said 「今天 ntfy 已发 0 条」
    while ntfy refused with 42908 - the ledger had been deployed at 21:16 with
    the day's 248 already spent, and a refused post is never counted. Anything
    else posting from the same IP (the phone on the home network, the Mac's
    order-now.sh) is invisible to it too. So `sync` takes ntfy's own count
    (NTFY_ACCOUNT) and total() is that count plus what the relay posted since.
    """

    # Reads take the lock too: the heartbeat thread and the mailbox thread share
    # one file, and a read landing mid-write would see {} - total 0, not full -
    # and beat into a 429. Re-entrant because add() reads under it. (A lock, not
    # temp-file-and-replace: on Windows os.replace fails while a reader has the
    # file open, and a failed write here is a message nobody counted.)
    _lock = threading.RLock()

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
            self._file().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
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
        the day's file, so neither the other thread nor a restart repeats it -
        10-02 it was logged again by every beat, every state and every bye)."""
        with self._lock:
            data = self.read()
            if data.get("full") is True:
                return False
            data["full"] = True
            self._write(data)
            own = self._own(data)
        log.warning("ntfy 今天 %d 条的额度用完了（%s；中继这一天自己发了 %d 条）："
                    "北京时间 8 点 ntfy 清零之前，中继不再往 ntfy 发心跳和状态通知，"
                    "手机经 ntfy 发来的指令也可能被拒；腾讯云 COS 上的状态和心跳照常写，App 打开或刷新时读得到",
                    NTFY_DAILY_LIMIT, why or "ntfy 回 42908", own)
        return True

    def full(self) -> bool:
        return self.read().get("full") is True

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


# The heartbeat on COS as well (the user, 10-03 00:12: the online verdict must
# not rest on the mailbox's heartbeat alone). 2026-10-02 19:19 the 250 ran out;
# from then on every beat was refused, and at 23:58 the App still read
# 「关机 · 最后心跳 22:34」 while the machine was running and writing its state to
# COS. So every beat also PUTs `state/<hash>.hb.json` = {"at", "every",
# "cos_every"} (+ "bye": true on a service stop), whether or not the ntfy
# beat went out and whether or not the quota has stopped it. The App reads it
# on open, on refresh and on return to the foreground - no timer.
#   at        - when it was written (seconds);
#   every     - the window the App should keep a beat alive for: the ntfy
#               cadence (interval()); once ntfy has refused the day nothing
#               live reaches the App, so at least HB_SLOW_SEC - its next read
#               (the 8-minute watch renewal) comes before 2 x 300 + 30 s;
#   cos_every - how often this object is rewritten while someone watches
#               (HEARTBEAT_SEC), so a reader can tell a stale object (power
#               cut, nobody watching) from a live one at once.
# A PUT costs 0.01 yuan per 10,000; 30 s for a 10-minute lease is 20 of them.
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
        (the user on 2026-10-06 05:07 about faults the relay got over: 「报错后自己好了的，只进日报、不进群」);
        still failing COS_OUTAGE_SEC after the first -> one WARNING, pushed."""
        if self.cos is None or not self.topic:
            return False
        self._cos_last = time.time()
        body = {"at": int(self._cos_last), "every": self.pace(), "cos_every": HB_COS_SEC}
        if bye:
            body["bye"] = True
        try:
            why = cos_put(self.cos, hb_key(self.topic), json.dumps(body).encode("utf-8"),
                          Mailbox.COS_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - e.g. signing; never reaches the ntfy beat
            why = str(exc) or type(exc).__name__
        if why:
            self.cos_fail_n += 1
            # INFO at first, not WARNING (10-03 00:16:44, one timeout): the next
            # COS beat is 30 s away and the ntfy beat still carries this one.
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
        # Not into a day ntfy has refused: 10-02 23:29:36 every restart's bye
        # ran into the 429 and logged the quota WARNING once more.
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
        # bye, and beats only go out while someone holds a watch, so after a deploy
        # the last thing the phone had heard was 「关机中」 - on 2026-09-09 the user
        # was looking at a red 「关机中」 while the page itself was showing the game
        # running on that machine. The last message must match reality.
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
            # `slice_s` is only ever shortened by the test — 2026-09-08 that test
            # spent 4 s of real wall-clock asleep, and the deploy runs the whole
            # suite every time, so a sleeping test is deploy time.
            for _ in range(wait):
                if stop() or self._kick.is_set():
                    break
                time.sleep(self._slice_s)
        self.bye()


# ---------- the whole state on Tencent COS ----------
#
# 2026-10-02 the user moved the state off ntfy's 250 a day (22:22): a state is
# ~13 KB gzipped, four ntfy messages, and 13 of them plus the day's beats ran
# the quota out at 19:19. Now every state push PUTs the same envelope pack()
# makes (plain or gz, exactly what would have gone to ntfy, PIN inside) to the
# evidence bucket, and only a one-line notice `state <ts> <bytes>` goes to the
# topic. The App GETs the object on that notice, on open and on refresh.
#
# The object is readable by anyone who has its URL (public-read ACL), and its
# name comes from the topic: whoever can read the topic on ntfy.sh today can
# read the state, nobody else - the same exposure as before. sha256 so the
# name does not give the topic back (and with it the command channel).
#
# The bucket's lifecycle rule (expire-30d-not-relay, docs/OPERATIONS.md)
# covers state/: COS counts Days from the object's last modification, and
# every push rewrites it, so only a machine silent for 30 days loses it.
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
            content_type: str = "application/json; charset=utf-8") -> "str | None":
    """PUT `data` to `key`: public-read by default (the App has no COS keys), never
    cached (or the App reads a stale copy). `public=False` leaves the bucket's
    private ACL (alertlog.py: only key holders read the alarm copy). None when
    stored, else why not - the caller says what that means for its own object
    in its own log line."""
    headers = {"Authorization": cos.authorization("PUT", key),
               "Cache-Control": "no-store",
               "Content-Type": content_type,
               "User-Agent": _UA}
    if public:
        headers["x-cos-acl"] = "public-read"
    req = urllib.request.Request(f"https://{cos.host}/{key}", data=data, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
    except urllib.error.HTTPError as exc:
        return f"回 {exc.code}"
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never raised
        return str(exc) or type(exc).__name__
    return None if 200 <= status < 300 else f"回 {status}"


def cos_get(cos, key: str, timeout: float) -> "tuple[bytes | None, str]":
    """GET `key` with the same signing as cos_put: (body, '') when it is there,
    (None, '') when the object does not exist (404), (None, why) for anything
    else. Never raises."""
    req = urllib.request.Request(f"https://{cos.host}/{key}",
                                 headers={"Authorization": cos.authorization("GET", key),
                                          "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), ""
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
    from .evidence import Cos  # noqa: PLC0415
    return Cos(*keys)


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
        # grace - which is why it hung in STOP_PENDING several times in a row on
        # 2026-08-31, wasting ten minutes each time.
        self._resp = None
        # Why the last publish() returned False, in words for the log line the
        # caller writes (boot_stages.publish_state): one WARNING per state the
        # phone cannot see, with its reason, instead of one per piece / try.
        self.last_error = ""
        # The boot read of the mailbox failed (fetch): listen() reads it again
        # once ntfy answers, so presses made while the machine was off are not
        # lost to a timeout (#41: 11 boots between 08-31 and 10-02).
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
    # and (now - NTFY_CACHE_SEC) are gone before this boot can read them, and
    # nothing on either side said so: the phone showed 「已寄出，等机器开机」 for
    # an order the machine would never see. The window is recorded here, kept
    # on disk and carried in every state (mailbox_status -> relay.信箱空窗), so
    # the phone can tell those presses from ones still waiting. Whether anything
    # was pressed in it the relay cannot know, so it is an INFO line, not an
    # alarm.

    def _load_mark(self) -> "int | None":
        try:
            v = self._store().get("queues", "phone_mark")
        except Exception:  # an unreadable mark only means no gap is reported
            log.info("上次读手机信箱读到哪儿没读出来，这次开机不判断有没有读不到的时段", exc_info=True)
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
            log.info("手机信箱读到哪儿没存下来，下次开机算读不到的时段会偏长", exc_info=True)
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
            log.info("读不到的时段没存下来，手机上这次看不到", exc_info=True)
        log.info("📱 上次读到手机信箱是 %s，这次 %s 读，隔了 %.1f 小时，超过 ntfy 只留 %d 小时："
                 "%s 到 %s 之间手机发的指令已被 ntfy 清掉，机器读不到（状态里 relay.信箱空窗 带着这一段）",
                 _bj(prev), _bj(read_at), (int(read_at) - prev) / 3600, NTFY_CACHE_SEC // 3600,
                 _bj(prev), _bj(edge))

    # ---------- remembering which messages were handled ----------
    # Each boot fetches the last 24 hours of messages in one go, and most of them
    # were already executed on the previous boot. Recording ntfy's own message id
    # keeps the same command from running twice.

    def _store(self):
        from .statestore import StateStore  # noqa: PLC0415
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

    # A single ntfy message has a size limit and anything past it is **truncated**
    # - truncated JSON fails to parse on the phone, which shows up as "state never
    # updates, so it is judged powered off", while the sending side looks
    # perfectly fine. So measure before sending, and when it is over, drop the
    # expendable parts and say so out loud.
    # ntfy's real limit is 4096 bytes. A 200-byte margin is plenty - 3600 was too
    # conservative, and after the queues and the weekly boss were added on
    # 2026-08-31 it went over and dropped tomorrow's plan.
    # ntfy turns anything over 4096 bytes into an attachment and hands back a URL,
    # so this is not a ceiling on what can be sent - it is the point where the
    # message stops travelling inline. Measured on 2026-09-09: a 9046-byte body
    # posted fine and came back byte-for-byte from its attachment URL.
    # It used to be treated as a hard limit, and the state was trimmed section by
    # section to fit. That threw away features to solve a problem that did not
    # exist, and when trimming was not enough the message went out unparseable and
    # the phone silently showed values 54 minutes old.
    # ntfy keeps messages for 12 hours and attachments for only 3. A state pushed
    # before the machine shuts down at night has to still be readable the next
    # morning, so it must never travel as an attachment - which is what anything
    # over 4096 bytes turns into. Over that, it is split into ordinary messages
    # instead: they last as long as any other message, and nothing is dropped.
    INLINE_MAX = 4096
    MAX_BODY = INLINE_MAX      # old name, kept for callers and tests
    # Room for the envelope around each slice.
    CHUNK_ROOM = 400

    def publish(self, body: dict, kind: str = "state") -> bool:
        """Send one state where the phone reads it. True when the phone can read
        it: stored on COS (the App reads the object on open, on refresh and on
        the notice), or carried whole by ntfy (inline, or every piece). False
        sets `last_error` to why, in words, for the caller's one log line.

        Until 2026-10-06 a state stored on COS still came back False when the
        one-line notice after it was refused: 10-02 22:56-10-03 01:36 states
        reached COS and were logged 「状态没能上报到手机」 all the same."""
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
                # walks back to it), so the rest of a broken set is dead weight:
                # 2026-10-02 19:19-20:54 every piece of every state was sent
                # (and retried) into a 429, 52 refusals for nothing.
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
        route got over, so the daily report only (the user, 2026-10-06 05:07:
        「报错后自己好了的，只进日报、不进群」). Nothing when COS took it."""
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
        # One short notice instead of the pieces: 2026-10-02 a state was 4
        # pieces and 13 states plus 196 beats used 248 of the 250.
        if not self._post(f"state {int(time.time())} {len(data)}".encode("ascii"), "state"):
            self._carried_by_cos("notice")
            self.last_error = ""

    # 8 s: the machine reached COS in 0.3 s (09-18, 4/4); on a miss the pieces still
    # have to fit in the 30 s a Windows service stop allows.
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
    # (2026-09-18 19:27 the second of two boot pieces hit a 20 s read timeout
    # once, and the phone kept a thirteen-minute-old state), ntfy's
    # request-rate refusal 42901 (back in seconds) and a 5xx from ntfy's front
    # (502 on 09-23 and 10-05). The pause is RETRY_AFTER, longer when the
    # answer carries Retry-After (at most RETRY_AFTER_MAX). Never retried:
    # 42908, the day's quota (back at 08:00 Beijing - until 10-02 urllib's
    # HTTPError fell into the bare `except Exception` and every 429 that
    # evening was sent twice), and any other 4xx: the same body gets the
    # same answer.
    RETRY_AFTER = 3.0
    RETRY_AFTER_MAX = 30.0
    ATTEMPTS = 2

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
                with urllib.request.urlopen(req, timeout=20) as r:
                    status = r.status
                if 200 <= status < 300:
                    self.quota.add(kind)
                    if i:
                        # The retry got it through: a fault the relay got over by
                        # itself, the daily report only (the user, 2026-10-06 05:07).
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

        When ntfy does not answer (#41: a 25 s read timeout at 11 boots from
        08-31 to 10-02, and until 10-06 those presses were simply gone - the
        stream only replayed 10 minutes) it returns [] and sets backlog_missed;
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
            msg = unpack(self.pin, str(env.get("message") or ""))
            if msg and msg.get("kind") == "cmd":
                out.append(stamp(msg, env, "backlog"))
                if mid:
                    fresh.append(mid)      # commands only - see SEEN_KEEP
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

        The socket is shut down first. r.close() alone waits for the read the
        listener thread is blocked in (the response's buffered reader is locked
        by it) and returned only with the next line ntfy sent - a keepalive, 45 s
        apart on ntfy.sh - so SvcStop sat in it before arming its 15 s backstop
        (measured 2026-10-07 against a real ntfy server, CPython 3.9.6 and
        3.14.7: close() took 4.5 s with a 5 s keepalive, 11.5 s with 12 s; after
        shutdown(), 0.00 s, and the listener came out at once).
        "If you want to close the connection in a timely fashion, call
        shutdown() before close()." (https://docs.python.org/3/library/socket.html#socket.socket.close)
        The socket is reached through http.client's response file (fp.raw._sock,
        no public accessor); when that is not there, close() is all there is.

        Windows: shutdown() does not wake a read another thread is blocked in
        (measured 2026-10-07 on the GitHub Windows runner, run 37519943859,
        CPython 3.14.7: close() took 5.3 s against a server that sends a line
        every 5 s and does not answer the FIN - a real ntfy closes its end on
        the FIN, which is why test_phone_mailbox_e2e.py passed there). The
        socket is closed there as well: "Any pending blocking, asynchronous
        calls issued by any thread in this process are canceled"
        (https://learn.microsoft.com/en-us/windows/win32/api/winsock/nf-winsock-closesocket).
        It is detached first: sock.close() only drops a reference while the
        response file holds the socket (makefile), and a detached socket object
        answers the listener's next call with an error instead of reading a
        handle that may already belong to something else. socket.close(fd) is
        the call for that: "On some platforms (most noticeable Windows)
        os.close() does not work for socket file descriptors."
        (https://docs.python.org/3/library/socket.html#socket.close)"""
        r, self._resp = self._resp, None
        self._save_mark(force=True)
        if r is not None:
            sock = getattr(getattr(getattr(r, "fp", None), "raw", None), "_sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    log.debug("手机通道的连接已经断了，不用再断", exc_info=True)
                if sys.platform == "win32":
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
    # (08-31..10-05: seven drops - read timeouts, 502 Bad Gateway, a reset by
    # the peer - each reconnected within a minute). Until 10-06 the reconnect
    # asked for the last 10 minutes only, so a longer gap did lose presses.
    # A channel that stays down OUTAGE_SEC is a fault: the phone's presses wait
    # in ntfy and the page gets no answer. One WARNING when an outage reaches
    # it (the same outage going on is not a new fault).
    # The reconnect decides the rest (the user, 2026-10-06 05:07: 「报错后自己
    # 好了的，只进日报、不进群」): an outage with a fault in it (a 5xx, a reset, a
    # connection that could not be made) ends in ONE WARNING marked
    # errwatch.recovered() - the daily report only; a stream that only timed
    # out reading while it was open (idle) and came straight back is normal
    # and stays INFO.
    OUTAGE_SEC = 600

    def _late_backlog(self, on_cmd, on_backlog) -> None:
        """Read the boot backlog fetch() missed (raises while ntfy still does not
        answer) and hand it on. Read now: a fault the relay got over by itself,
        the daily report only (the user, 2026-10-06 05:07)."""
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
                # Measured 2026-08-31: the machine received no refresh at all
                # after 03:34:31, and pressing the button on the phone did
                # nothing. With `since`, a reconnect picks up what was missed;
                # anything already handled is deduplicated by message id, so
                # nothing runs twice.
                url = f"{NTFY}/{self.topic}/json?since={self._since()}"
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                # **timeout=None is forbidden**: the read would block
                # indefinitely, this thread would hang on service stop, and the
                # service would be stuck in STOP_PENDING. That happened once on
                # 2026-08-31 and the process had to be killed. ntfy sends a
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
                        msg = unpack(self.pin, str(env.get("message") or ""))
                        if not msg or msg.get("kind") != "cmd":
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
      post, so nearly every press cost two states (8 messages): 2026-10-02
      17:02:23 / 17:02:31, 18:30:05 / 18:30:12, 20:20:27 / 20:20:48. And the
      refreshes pressed while the machine was off all come back out of the
      mailbox at boot, right after the boot state already answered them:
      09-30 08:46:03-08:47:44, eleven of them, 44 messages in 100 seconds.
    * While held (the boot backlog), every push is put off and sent once at the
      end: each config order in the backlog used to send its own state.

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

    def __call__(self, why: str) -> bool:
        with self._lock:
            if self._held:
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


# ---------- orders that wait for the run to end ----------
#
# A config write while a script runs is clobbered by AUTO-MAS's in-memory copy,
# so such an order cannot be applied on the spot. Until 2026-10-05 it was thrown
# away instead: a 「等这一趟跑完再按一次」 push, no receipt, and its message id
# already in `_seen`, so nothing ever ran it - while the App told him the change
# was 「推迟到跑完再生效」. Now it waits here, on disk (a relay restart or a reboot
# between the press and the end of the run must not lose it), and
# boot_stages drains it in arrival order once nothing is running, before the
# shutdown decision of that same tick.
CMD_QUEUE_FILE = "phone-queue.json"
# Orders that start a run rather than change a setting. Pressed while a run is
# going they are answered at once and never queued: applied after the run they
# would start one more on top of it (commands.run_script, 2026-09-01). Every
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
        from .config import atomic_write_text  # noqa: PLC0415
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


# AUTO-MAS's own UI is entirely in Chinese, and the labels live in its models:
# one line of `## 中文名` above each ConfigItem, with the legal values inside
# OptionsValidator([...]).
# The user, 2026-08-31: 「一定是有中文解释的因为 ui 界面就是全中文，
# 只不过你没找到在哪里标注的而已。」 (there must be Chinese labels, since the UI
# is all Chinese; you just did not find where they are annotated) - he was right,
# my earlier search missed them.
# Read them from there rather than translating them here: when upstream renames
# something this follows along, whereas a hardcoded table eventually disagrees.
_CFG_ITEM = re.compile(
    r'##\s*(?P<label>[^\n]+)\n\s*self\.\w+\s*=\s*ConfigItem\(\s*'
    r'"(?P<sec>\w+)"\s*,\s*"(?P<key>\w+)"\s*,(?P<rest>.*?)\n\s*\)',
    re.S)
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
        for i, cm in enumerate(marks):
            game = _CLASS_OF.get(cm.group(1))
            if not game:
                continue
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            for m in _CFG_ITEM.finditer(text[cm.end():end]):
                o = _OPTS.search(m.group("rest"))
                out[game][f'{m.group("sec")}.{m.group("key")}'] = {
                    "label": m.group("label").strip(),
                    "options": _QUOTED.findall(o.group(1)) if o else None,
                }
    return out


# The items the phone actually displays. **Send only these**: cramming in all 154
# labels pushes the single message past ntfy's size limit, it gets truncated, the
# page's JSON.parse fails outright, and state then never updates and is judged
# 「关机中」 - which is exactly how it broke on 2026-08-31.
SHOWN = (
    "Info.Stage", "Info.StageMode", "Info.MedicineNumb", "Info.SeriesNumb",
    "Info.Annihilation", "Task.IfFight", "Task.IfActivityFirst",
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
                # Since 2026-09-04 only the Chinese field names are sent, without
                # the candidate lists: of the six remaining items only 「剿灭」 is
                # a multiple choice, and it has since become read-only display
                # (it switches itself weekly and should not be tapped on the
                # phone). The stage table alone runs to over a thousand bytes and
                # would push the whole packet up against ntfy's limit.
        out["_labels"] = names
    except Exception:
        log.warning("AUTO-MAS 的中文标注读不到", exc_info=True)
    return out


def mailbox_status(state_dir) -> list[dict]:
    """relay.信箱空窗 in the state: the windows the mailbox could not read
    (Mailbox._note_blind), oldest first, each {"从", "到", "开机"} in unix
    seconds. A press sent inside one never reached the machine: ntfy had
    dropped it before the boot read. The App compares an order's send time
    with them (its sent time is on ntfy's clock, Net.send; "从" is ntfy's time
    of the last line read, "到" the machine's boot read minus NTFY_CACHE_SEC)."""
    from .statestore import StateStore  # noqa: PLC0415
    kept = StateStore(Path(state_dir)).get("queues", "phone_blind")
    out = []
    for g in kept if isinstance(kept, list) else []:
        if isinstance(g, dict) and all(isinstance(g.get(k), int) for k in ("from", "to", "boot")):
            out.append({"从": g["from"], "到": g["to"], "开机": g["boot"]})
    return out


def state_payload(cfg, state_dir: Path) -> dict:
    """The payload the phone displays. Same code config-check reads (snapshot.py)."""
    from . import modes, monthcard, plan, snapshot  # noqa: PLC0415 - avoids an import cycle
    out: dict = {"at": int(time.time())}
    # Send only the three sections the phone displays. The full snapshot also
    # carries OK-WW's four config files, the queue table and the process list,
    # which together push the single message past ntfy's size limit; once
    # truncated, the phone side fails to parse it - showing up as "permanently
    # powered off".
    # Only the keys the phone displays. The full snapshot does not fit in one
    # message (see Mailbox.MAX_BODY).
    keep = {k.split(".", 1)[1] for k in SHOWN} | {"关卡", "理智药", "剿灭",
            "作战开关", "活动关优先", "活动关序号"}
    try:
        full = snapshot.read()
        # The orchestrator is always up while the machine is; listing it made
        # 「现在没有脚本在跑」 impossible to ever show, and 「在跑：AUTO-MAS」 tells him
        # nothing. Only scripts and games count as running.
        from .config import ORCHESTRATOR_PROC  # noqa: PLC0415
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
    except Exception:
        log.warning("班次名单读不到", exc_info=True)
        out["queues"] = []
    try:
        from . import annihilation, garden, weeklyboss  # noqa: PLC0415
        automas = getattr(cfg, "automas_dir", None)
        wb = weeklyboss.WeeklyBossGate(state_dir, automas).settings()
        out["relay"] = {
            # only while it holds: an expired end time read as "on" on the phone (10-02 App walk-through, still
            # showing the 09-30 21:10 end two days later); shutdown already goes by debug_active (shutdown.py:315)
            "调试模式": modes.debug_until(state_dir) if modes.debug_active(state_dir) else "",
            "刷声骸": (lambda r: {"名字": r.get("name"), "到": r.get("until"),
                                  "从": r.get("started")} if r else {})(
                __import__("ark_relay.echofarm", fromlist=["x"]).current(state_dir)),
            "下次别关机": modes.skip_armed(state_dir),
            # Which queues sit out today: the page shows each as its queue
            # row's switch (2026-09-15). "今天跳过" is the first one ("" = none)
            # for pages that read a single name; "今天跳过队列" lists them all
            # (2026-09-30, two queues can sit out the same day).
            "今天跳过": modes.skipped_today(state_dir) or "",
            "今天跳过队列": modes.skipped_today_all(state_dir),
            "无音区截图": modes.tacet_shots_on(state_dir),
            # Monthly cards the user registered (monthcard.py, spec 月卡到期提示-规格.md).
            "月卡": monthcard.status(state_dir),
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
    except Exception as exc:  # noqa: BLE001
        # {} reads on the phone as switches off, weekly not done, no month
        # cards - as if real.
        if _last_error.get("relay") != (key := f"{type(exc).__name__}: {exc}"):
            log.warning("手机状态里中继那一段读不到，App 上的开关、周常和月卡这次是空的", exc_info=True)
            _last_error["relay"] = key
        out["relay"] = {}
    try:
        out["options"] = _options(cfg)
    except Exception:  # noqa: BLE001
        out["options"] = {}
    # Endfield and Wuthering Waves are configured through the scripts' own config,
    # not through MAS - changing it on the MAS side has no effect.
    try:
        from . import mastercfg  # noqa: PLC0415
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
    except Exception as exc:  # noqa: BLE001
        if _last_error.get("plan") != (key := f"{type(exc).__name__}: {exc}"):
            log.warning("明日安排算不出来，App 上那一段这次是空的", exc_info=True)
            _last_error["plan"] = key
        out["plan"] = ""
    # The number tiles on the 状态 tab: the page reads the games' stamina itself
    # (web/stamina.js); it only needs the Skland session from here, plus today's
    # run count from the ledger.
    try:
        from . import resources  # noqa: PLC0415
        from .config import SERVER_TZ  # noqa: PLC0415
        from .core import State  # noqa: PLC0415
        out["密钥"] = {"sk": resources.skland_session(cfg)}
        out["今天"] = resources.today(State(Path(state_dir)), datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
    except Exception:
        log.warning("森空岛会话和今天的统计读不到", exc_info=True)
    return out
