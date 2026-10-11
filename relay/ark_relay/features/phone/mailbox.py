"""The phone mailbox (Mailbox): the boot read, state publishing and the held ntfy stream.

Split out of phone.py (which still re-exports Mailbox); the design notes are in
phone.py's module docstring.
"""
from __future__ import annotations

import json
import logging
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ark_relay.features.alarm import errwatch
from ark_relay.features.phone.cos_store import cos_put, state_key
from ark_relay.features.phone.quota import NOTICE_STOP_AT, Quota, _idle_timeout, _ntfy_code, _retry_after, _why
from ark_relay.features.phone.wire import (
    BLIND_KEEP, MARK_SAVE_SEC, NTFY, NTFY_CACHE_SEC, SEEN_KEEP, _UA, _bj, pack, pack_chunks, stamp, unpack,
)

log = logging.getLogger("ark.phone")   # same logger as phone.py: log lines keep their name


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

    # A single ntfy message has a size limit and anything past it is **truncated**
    # - truncated JSON fails to parse on the phone, which shows up as "state never
    # updates, so it is judged powered off", while the sending side looks
    # perfectly fine. So measure before sending, and when it is over, drop the
    # expendable parts and say so out loud.
    # ntfy's real limit is 4096 bytes; the margin below it is 200 bytes.
    # ntfy turns anything over 4096 bytes into an attachment and hands back a URL,
    # so this is not a ceiling on what can be sent - it is the point where the
    # message stops travelling inline. Measured on 2026-09-09: a 9046-byte body
    # posted fine and came back byte-for-byte from its attachment URL.
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
    # (a read timeout, for example), ntfy's request-rate refusal 42901 (back in
    # seconds) and a 5xx from ntfy's front (502). The pause is RETRY_AFTER,
    # longer when the answer carries Retry-After (at most RETRY_AFTER_MAX).
    # Never retried: 42908, the day's quota (back at 08:00 Beijing), and any
    # other 4xx: the same body gets the same answer.
    RETRY_AFTER = 3.0
    RETRY_AFTER_MAX = 30.0
    ATTEMPTS = 2
    # Per socket operation of one POST. app_main.stop_push (the watchdog's push at a
    # Windows shutdown) lowers it and ATTEMPTS on its own Mailbox: 2026-10-11 15:42:09
    # its notice reached ntfy but the answer did not come back, and waiting out these
    # 20 s ran its whole time limit out with the state already on COS.
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
