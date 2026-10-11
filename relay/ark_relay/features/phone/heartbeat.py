"""The online heartbeat (Heartbeat): beats to ntfy and COS only while someone is watching.

Split out of phone.py (which still re-exports Heartbeat); the cadence and the
budget it follows are in quota.py.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from ark_relay.features.alarm import errwatch
from ark_relay.features.phone.cos_store import cos_put, hb_key
from ark_relay.features.phone.mailbox import Mailbox
from ark_relay.features.phone.quota import (
    HB_CRAWL_SEC, HB_FAST_UNTIL, HB_KICK_GAP, HB_SLOW_SEC, HB_SLOW_UNTIL, HB_STOP_AT, HEARTBEAT_SEC,
    QUOTA_SYNC_SEC, WATCH_LEASE_SEC, Quota, _ntfy_code, ntfy_account,
)
from ark_relay.features.phone.wire import NTFY, _UA, _bj

log = logging.getLogger("ark.phone")   # same logger as phone.py: log lines keep their name


# The heartbeat on COS as well (the user, 10-03 00:12: the online verdict must
# not rest on the mailbox's heartbeat alone): once ntfy refuses the day, no ntfy
# beat reaches the App. So every beat also PUTs `state/<hash>.hb.json` = {"at", "every",
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
