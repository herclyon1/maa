"""The heartbeat cadence and the day's ntfy budget (Quota), plus ntfy error helpers.

Split out of phone.py (which still re-exports every name here). Mailbox and
Heartbeat both spend from the one Quota ledger.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from ark_relay.features.phone.wire import NTFY, _UA

log = logging.getLogger("ark.phone")   # same logger as phone.py: log lines keep their name


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
# the day's messages run low. One ledger (Quota) counts every message the relay
# posts - beats, states, notices, bye - and the cadence follows that total.

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
