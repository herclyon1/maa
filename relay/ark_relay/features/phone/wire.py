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
from datetime import datetime
import logging
import time

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

    Why compress: a packet over the size limit goes down the degradation path
    (first tomorrow's plan is dropped, then the options table that fills the
    phone's dropdowns), and that loss is silent. Measured 2026-08-31: 3783 bytes
    plain, 2464 compressed.

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
