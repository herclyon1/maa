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

The command window is 24 hours: the machine powers on twice a day, and a command
pressed on the phone has to survive in the mailbox until the next boot. Commands
already handled are remembered by ntfy's own message id, so nothing runs twice.
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
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


log = logging.getLogger("ark.phone")

NTFY = "https://ntfy.sh"
# How long a command may wait in the mailbox. The machine boots twice a day, with
# a maximum gap of about 11.5 hours.
MAX_AGE = 24 * 3600
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


class Quota:
    """Every message this machine posts to ntfy today, all kinds in one ledger.

    ntfy counts per IP, all topics together (the state topic and <topic>-hb
    share it), and resets "every day at midnight (UTC)" (docs.ntfy.sh/config,
    visitor-message-daily-limit) - 08:00 on the machine's Beijing clock. So the
    ledger is keyed by the UTC date, not the local one. It is a file so the
    heartbeat thread and the mailbox thread (and a restart) see the same count.

    `full` is set when ntfy itself answers 42908 「daily message quota
    reached」: from then until UTC midnight a beat would only be refused again.
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

    def total(self) -> int:
        n = 0
        for k, v in self.read().items():
            if k != "full" and isinstance(v, int) and not isinstance(v, bool):
                n += v
        return n

    def mark_full(self) -> None:
        with self._lock:
            data = self.read()
            data["full"] = True
            self._write(data)

    def full(self) -> bool:
        return self.read().get("full") is True


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
    never touch the network; `cos` (state_cos) adds the beat on COS."""

    def __init__(self, topic: str, state_dir: Path, post=None, cos=None):
        self.topic = (topic or "").strip()
        self.url = f"{NTFY}/{self.topic}-hb"
        self.state_dir = Path(state_dir)
        self.quota = Quota(self.state_dir)
        self.cos = cos
        self._lease = 0.0
        self._last = 0.0          # when the last ntfy beat went out
        self._cos_last = 0.0      # when the last COS beat was tried
        self._cos_ok = True       # so a COS outage is logged once, not every 30 s
        self._kick = threading.Event()
        self._post = post or self._http_post

    def _http_post(self, payload: bytes, title: str) -> None:
        req = urllib.request.Request(self.url, data=payload, method="POST",
                                     headers={"User-Agent": _UA, "Title": title})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except urllib.error.HTTPError as exc:
            code, text = _ntfy_code(exc)
            if code == 42908:
                self.quota.mark_full()
                log.warning("ntfy 今天的 %d 条额度用完了（%s；本机今天记了 %d 条），"
                            "心跳停到北京时间 8 点额度恢复（腾讯云 COS 上的心跳照常）",
                            NTFY_DAILY_LIMIT, text, self.quota.total())
            raise

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
        return max(every, HB_SLOW_SEC) if self.quota.full() else every

    def cos_beat(self, bye: bool = False) -> bool:
        """PUT the beat to hb_key(topic). Never raises; a failure is one log
        line (until it works again) and does not touch the ntfy beat."""
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
            if self._cos_ok or bye:
                log.warning("心跳没能写到腾讯云 COS（%s）%s", why,
                            "，App 要等下次打开才知道已下线" if bye else "，ntfy 心跳照旧")
            self._cos_ok = False
            return False
        if not self._cos_ok:
            log.info("心跳又写得进腾讯云 COS 了")
        self._cos_ok = True
        return True

    def beat(self) -> bool:
        """One beat: on COS always, on ntfy unless the quota stopped it.
        Returns whether the ntfy beat went out."""
        self.cos_beat()
        if self.quota.full():
            return False          # ntfy said 42908; a beat would only be refused again
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
        try:
            self._post(b"bye", "bye")
            self.quota.add("bye")
            log.info("📱 已发下线心跳（bye）")
        except Exception:  # noqa: BLE001
            pass
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
        self.beat()
        while not stop():
            kicked = self._kick.is_set()
            self._kick.clear()
            wait = 5
            if self.watched():
                every = self.interval()
                need = min(every, HB_KICK_GAP) if kicked else every
                since = time.time() - self._last
                beat = not self.quota.full() and since >= need
                if beat:
                    self.beat()             # ntfy and COS; a failed one waits `every` too
                    left = every
                elif self.quota.full():
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


def cos_put(cos, key: str, data: bytes, timeout: float) -> "str | None":
    """PUT `data` to `key`: public-read (the App has no COS keys), never cached
    (or the App reads a stale copy). None when stored, else why not - the
    caller says what that means for its own object in its own log line."""
    req = urllib.request.Request(
        f"https://{cos.host}/{key}", data=data, method="PUT",
        headers={"Authorization": cos.authorization("PUT", key),
                 "x-cos-acl": "public-read",
                 "Cache-Control": "no-store",
                 "Content-Type": "application/json; charset=utf-8",
                 "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
    except urllib.error.HTTPError as exc:
        return f"回 {exc.code}"
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never raised
        return str(exc) or type(exc).__name__
    return None if 200 <= status < 300 else f"回 {status}"


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

    @property
    def enabled(self) -> bool:
        return bool(self.topic and self.pin)

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
        if not self.enabled:
            return False
        data = pack(self.pin, body, kind).encode("utf-8")
        if len(data) > self.INLINE_MAX:
            packed = pack(self.pin, body, kind, gz=True).encode("utf-8")
            if len(packed) < len(data):
                log.info("状态 %d 字节，压缩到 %d 字节", len(data), len(packed))
                data = packed
        # The whole envelope goes to COS on every push, so the App's read on
        # open / refresh always finds the newest state (state_cos).
        stored = kind == "state" and self.cos is not None and self._cos_put(data)
        if len(data) <= self.INLINE_MAX:
            return self._post(data, kind)
        if stored:
            # One short notice instead of the pieces: 2026-10-02 a state was 4
            # pieces and 13 states plus 196 beats used 248 of the 250.
            return self._post(f"state {int(time.time())} {len(data)}".encode("ascii"), kind)
        parts = pack_chunks(self.pin, body, kind,
                            self.INLINE_MAX - self.CHUNK_ROOM)
        log.info("状态 %d 字节，切成 %d 条普通消息发（附件只活 3 小时，消息活 12 小时）",
                 len(data), len(parts))
        for n, piece in enumerate(parts):
            if not self._post(piece.encode("utf-8"), kind):
                # The phone joins a set only when all n pieces are there
                # (pack_chunks), so the rest of a broken set is dead weight:
                # 2026-10-02 19:19-20:54 every piece of every state was sent
                # (and retried) into a 429, 52 refusals for nothing.
                if n + 1 < len(parts):
                    log.warning("第 %d/%d 片没发出去，这一份状态剩下的 %d 片不发了（缺一片手机也拼不起来）",
                                n + 1, len(parts), len(parts) - n - 1)
                return False
        return True

    # 8 s: the machine reached COS in 0.3 s (09-18, 4/4); on a miss the pieces still
    # have to fit in the 30 s a Windows service stop allows.
    COS_TIMEOUT = 8

    def _cos_put(self, data: bytes) -> bool:
        """PUT the packed envelope to state_key(topic). False on any failure -
        the caller then sends the pieces."""
        why = cos_put(self.cos, state_key(self.topic), data, self.COS_TIMEOUT)
        if why:
            log.warning("状态没能存到腾讯云 COS（%s），这一份照旧切片发 ntfy", why)
        return why is None

    # One retry after a network exception. 2026-09-18 19:27 the boot state was
    # two pieces and the second one hit a 20 s read timeout - a single miss -
    # so the phone kept showing the state from thirteen minutes earlier until
    # the next push (which is the shutdown). A piece that is missing cannot be
    # reassembled on the phone, so one retry for the piece is worth far more
    # than it costs (one extra message, only on failure). A 4xx/5xx answer is
    # not retried: the server did answer, and repeating the same body will
    # not change its mind. (Until 2026-10-02 it was: urllib raises HTTPError
    # for those, and the bare `except Exception` caught it as a network error -
    # every 429 that evening was sent twice.)
    RETRY_AFTER = 2.0

    def _post(self, data: bytes, kind: str, attempts: int = 2) -> bool:
        req = urllib.request.Request(f"{NTFY}/{self.topic}", data=data,
                                     method="POST",
                                     headers={"User-Agent": _UA,
                                              "Title": kind})
        for i in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    ok = 200 <= r.status < 300
                if ok:
                    self.quota.add(kind)
                return ok
            except urllib.error.HTTPError as exc:
                code, text = _ntfy_code(exc)
                if code == 42908:
                    self.quota.mark_full()
                log.warning("状态没能发到信箱：ntfy 回 %s %s%s（本机今天记了 %d 条，ntfy 每天 %d 条，北京时间 8 点清零）",
                            exc.code, code or "", f" {text}" if text else "",
                            self.quota.total(), NTFY_DAILY_LIMIT)
                return False
            except Exception:
                if i + 1 < attempts:
                    log.info("状态这一片没发到信箱，%.0f 秒后再试一次", self.RETRY_AFTER)
                    time.sleep(self.RETRY_AFTER)
                    continue
                log.warning("状态没能发到信箱（试了 %d 次）", attempts, exc_info=True)
        return False

    # ---------- fetching (once per boot) ----------

    def fetch(self, since: str = "24h") -> "list[dict]":
        """Fetch every command waiting in the mailbox in one go. Not polling -
        called once, at boot."""
        if not self.enabled:
            return []
        url = f"{NTFY}/{self.topic}/json?poll=1&since={since}"
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read().decode("utf-8", "replace")
        except Exception:
            log.warning("取不到信箱里的指令", exc_info=True)
            return []
        out: list[dict] = []
        seen = set(self._seen)
        fresh: list[str] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                env = json.loads(line)
            except json.JSONDecodeError:
                continue
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
        return out

    # ---------- listening (long-lived connection, zero polling) ----------

    def close(self) -> None:
        """Sever the held connection so listen() comes out of its blocking read
        immediately."""
        r, self._resp = self._resp, None
        if r is not None:
            try:
                r.close()
            except Exception:
                log.debug("手机通道关不掉，忽略", exc_info=True)

    def listen(self, on_cmd, stop) -> None:
        """Connect and hold; the server pushes only when there is a message.
        Exits when `stop()` returns true.

        The reconnect backoff follows the same reasoning as the WMI subscription
        in service.py: a dropped connection has to be picked back up, but a drop
        must not turn into a burst of retries.
        """
        if not self.enabled:
            return
        delay = 5
        while not stop():
            try:
                # **`since` is mandatory**: a streaming subscription delivers only
                # messages that arrive while connected, so a refresh sent from the
                # phone during the few seconds of a reconnect is lost forever.
                # Measured 2026-08-31: the machine received no refresh at all
                # after 03:34:31, and pressing the button on the phone did
                # nothing. With `since`, a reconnect picks up what was missed;
                # anything already handled is deduplicated by message id, so
                # nothing runs twice.
                url = f"{NTFY}/{self.topic}/json?since=10m"
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                # **timeout=None is forbidden**: the read would block
                # indefinitely, this thread would hang on service stop, and the
                # service would be stuck in STOP_PENDING. That happened once on
                # 2026-08-31 and the process had to be killed. ntfy sends a
                # keepalive every 45 seconds, so a 90-second read timeout can
                # never fire spuriously; when it does fire, the outer loop
                # reconnects.
                with urllib.request.urlopen(req, timeout=90) as r:
                    self._resp = r
                    log.info("📱 手机通道已连上（长连接，不轮询）")
                    delay = 5
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
            except Exception:
                if stop():
                    return
                log.warning("手机通道断了，%d 秒后重连", delay, exc_info=True)
            # The wait before reconnecting. sleep here is not polling - it waits
            # to get the connection back, it does not go asking whether there are
            # new messages.
            for _ in range(delay):
                if stop():
                    return
                time.sleep(1)
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
        # Arknights only: the MAS fields for the other two games are not sent,
        # see mastercfg
        out["config"] = {
            sec: {k: v for k, v in (vals or {}).items() if k in keep}
            for sec, vals in full.items() if sec == "MAA"}
        # The orchestrator is always up while the machine is; listing it made
        # 「现在没有脚本在跑」 impossible to ever show, and 「在跑：AUTO-MAS」 tells him
        # nothing. Only scripts and games count as running.
        from .config import ORCHESTRATOR_PROC  # noqa: PLC0415
        orch = ORCHESTRATOR_PROC[:-4]
        out["run"] = {"服务": full.get("ark-relay"),
                      "在跑的": [n for n, on in (full.get("程序") or {}).items() if on and n != orch]}
        out["queues"] = [{"名": n, **v} for n, v in (full.get("队列") or {}).items()]
    except Exception as exc:  # noqa: BLE001
        out["config"] = {"_错误": f"{type(exc).__name__}: {exc}"}
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
            "周本": wb,
            # The three "once a week" things share one shape: done this week /
            # the switch / their own settings
            "周常": {
                "剿灭": annihilation.WeeklyGate(state_dir, automas).settings(),
                "周常乐园": garden.GardenGate(state_dir, automas).settings(),
                "周本": wb,
            },
        }
    except Exception:  # noqa: BLE001
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
    except Exception:  # noqa: BLE001
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
