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
「留一个 pin 就行了，那那么多事」). The mailbox name itself is a 28-character
random string that exists only in the user's phone and the machine's .env.
State carries game config only, never credentials.

The command window is 24 hours: the machine powers on twice a day, and a command
pressed on the phone has to survive in the mailbox until the next boot. Commands
already handled are remembered by ntfy's own message id, so nothing runs twice.
"""
from __future__ import annotations

import base64
import hashlib
import gzip
import json
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
# How many handled message ids to remember. At a few commands a day, 200 lasts
# several months.
SEEN_KEEP = 200
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
        log.info("信箱里那条指令太老了（%.1f 小时前），丢弃", age / 3600)
        return None
    if "gz" in msg and "body" not in msg:
        try:
            msg["body"] = json.loads(
                gzip.decompress(base64.b64decode(msg["gz"])).decode("utf-8"))
        except Exception:
            log.warning("信箱里那条消息解压失败，丢弃", exc_info=True)
            return None
    return msg


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
# replies alike. Hence: beat only while someone is watching, at most
# HB_DAILY_CAP times a day, dropping to a 5-minute interval past that.

HEARTBEAT_SEC = 30       # interval while someone is watching
WATCH_LEASE_SEC = 600    # one "I am watching" lasts 10 min; a foreground page renews it
HB_DAILY_CAP = 150       # daily beat cap, leaving quota for state/commands
HB_SLOW_SEC = 300        # interval once the cap is passed


class Heartbeat:
    """Beats only while someone is watching. `post` is injectable so the tests
    never touch the network."""

    def __init__(self, topic: str, state_dir: Path, post=None):
        self.topic = (topic or "").strip()
        self.url = f"{NTFY}/{self.topic}-hb"
        self.state_dir = Path(state_dir)
        self._lease = 0.0
        self._kick = threading.Event()
        self._post = post or self._http_post

    def _http_post(self, payload: bytes, title: str) -> None:
        req = urllib.request.Request(self.url, data=payload, method="POST",
                                     headers={"User-Agent": _UA, "Title": title})
        urllib.request.urlopen(req, timeout=10).read()

    # -- lease --
    def watch(self) -> None:
        """The page says "I am watching": renew for 10 minutes and beat at once so
        it knows immediately that the machine is up."""
        self._lease = time.time() + WATCH_LEASE_SEC
        self._kick.set()

    def watched(self) -> bool:
        return time.time() < self._lease

    # -- today's count (keeps the ntfy quota from being eaten) --
    def _count_file(self) -> Path:
        return self.state_dir / f"hb-{time.strftime('%Y-%m-%d')}.txt"

    def sent_today(self) -> int:
        try:
            return int(self._count_file().read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return 0

    def _bump(self) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self._count_file().write_text(str(self.sent_today() + 1), encoding="utf-8")
        except OSError:
            pass

    def interval(self) -> int:
        return HEARTBEAT_SEC if self.sent_today() < HB_DAILY_CAP else HB_SLOW_SEC

    def beat(self) -> bool:
        try:
            # The current cadence rides along in the message. The page decides
            # "no heartbeat for a while = powered off" from a fixed 90 seconds,
            # and once the daily cap drops this to one beat every 5 minutes that
            # verdict is wrong for three and a half minutes out of every five -
            # a red 「关机中」 while the queue is running. It cannot know the
            # cadence unless it is told, and widening its window instead would
            # slow down the one thing it exists for: seeing a real power-off.
            self._post(f"hb {self.interval()}".encode(), "hb")
        except Exception:
            log.debug("心跳没发出去", exc_info=True)
            return False
        self._bump()
        return True

    def bye(self) -> None:
        try:
            self._post(b"bye", "bye")
            log.info("📱 已发下线心跳（bye）")
        except Exception:  # noqa: BLE001
            pass

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
            wait = 5
            if self.watched():
                self.beat()
                wait = self.interval()
            # Wait in slices rather than one long sleep: stopping the service must
            # exit at once, and an incoming watch() must be able to beat at once.
            # `slice_s` is only ever shortened by the test — 2026-09-08 that test
            # spent 4 s of real wall-clock asleep, and the deploy runs the whole
            # suite every time, so a sleeping test is deploy time.
            for _ in range(wait):
                if stop() or self._kick.is_set():
                    break
                time.sleep(self._slice_s)
            self._kick.clear()
        self.bye()


class Mailbox:
    """One mailbox: fetches commands, publishes state, holds the long-lived
    connection."""

    def __init__(self, topic: str, pin: str, state_dir: Path):
        self.topic = (topic or "").strip()
        self.pin = (pin or "").strip()
        self.state_dir = Path(state_dir)
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
        if len(data) <= self.INLINE_MAX:
            return self._post(data, kind)
        parts = pack_chunks(self.pin, body, kind,
                            self.INLINE_MAX - self.CHUNK_ROOM)
        log.info("状态 %d 字节，切成 %d 条普通消息发（附件只活 3 小时，消息活 12 小时）",
                 len(data), len(parts))
        ok = True
        for piece in parts:
            ok = self._post(piece.encode("utf-8"), kind) and ok
        return ok

    def _post(self, data: bytes, kind: str) -> bool:
        req = urllib.request.Request(f"{NTFY}/{self.topic}", data=data,
                                     method="POST",
                                     headers={"User-Agent": _UA,
                                              "Title": kind})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return 200 <= r.status < 300
        except Exception:
            log.warning("状态没能发到信箱", exc_info=True)
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
                out.append(msg["body"])
            if mid:
                fresh.append(mid)
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
                            on_cmd(msg["body"])
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
    from . import modes, plan, snapshot  # noqa: PLC0415 - avoids an import cycle
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
            "调试模式": modes.debug_until(state_dir) or "",
            "刷声骸": (lambda r: {"名字": r.get("name"), "到": r.get("until"),
                                  "从": r.get("started")} if r else {})(
                __import__("ark_relay.echofarm", fromlist=["x"]).current(state_dir)),
            "下次别关机": modes.skip_armed(state_dir),
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
    return out
