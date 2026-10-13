"""daysim: every HTTP call and socket the relay makes, answered in process.

The relay reaches the network only through `urllib.request.urlopen` and, for the
Mac push, `urllib.request.build_opener(...).open` (macpush.MacPush._http_post);
no module imports `urlopen` by name (design.md section 1, seam table). FakeNet
replaces both and guards the socket layer underneath, so nothing leaves the
process:

* push channels are captured as outputs (`out("push", ...)`): WeCom group robot
  (`group`), WeCom app (`wecom_app`), Server酱 (`serverchan`), ntfy publishes
  (`ntfy`) and the Mac push (`mac`);
* ntfy is a small server model: a message store with ntfy's 12 h cache, the
  backlog poll, the held stream (keepalives every 45 s, phone orders at their
  recorded times) and the daily quota of 250 publishes per UTC day, refused
  with ntfy's own 429 / 42908 answer (R08: the relay once counted per local day);
* COS is an in-memory bucket (state, heartbeat, evidence, self-update, inbox);
* the AUTO-MAS backend (fake_mas.FakeMas) and MaaEnd's MXU web API on 12701
  are routed to in-process models;
* information sources (maintenance notices, banners, pinned upstream files,
  the LLM, evidence stores) get "nothing new" answers in the shapes their
  parsers read, overridable per day with `set_web`;
* anything else - an unknown host, a raw `socket.connect` - is a sim error
  (`out("sim_error", ...)`) and fails the call the way an unreachable host
  does, so the day goes on and the oracle fails it (design.md section 3,
  invariant 5).

Scheduler contract (design.md section 2, W1): `sched.now()`, `sched.park(timeout,
ready)` for a helper thread's blocking read, `sched.out(kind, **fields)`. A
plain delay (an injected timeout) uses `time.sleep`, which the sim clock owns.
"""
from __future__ import annotations

import base64
import email.message
import gzip
import io
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC8 = timezone(timedelta(hours=8))
RELAY = Path(__file__).resolve().parents[2]          # relay/
FIXTURES = RELAY / "tests" / "fixtures"
SOURCE_PINS = FIXTURES / "source-pins"           # evidence/sources.py PINS, by file name
# Other upstream files the relay reads through the GitHub doors, by file name: the
# repo's recorded copies (banners: Arknights-yituliu's gacha schedule).
UPSTREAM_COPIES = {"gachaScheduleOptions.js": FIXTURES / "ak_schedule.js"}

# ntfy.sh's limits, as the relay itself cites them (features/phone/quota.py:
# NTFY_DAILY_LIMIT 250 per IP per day, reset "every day at midnight (UTC)";
# wire.py: NTFY_CACHE_SEC 12 h; mailbox.py: a keepalive every 45 s).
NTFY_LIMIT = 250
NTFY_CACHE_S = 12 * 3600
NTFY_KEEPALIVE_S = 45
NTFY_QUOTA_BODY = {"code": 42908, "http": 429,
                   "error": "limit reached: daily message quota reached"}

GAMES = ("明日方舟", "终末地", "鸣潮")

_REAL: dict = {}          # the originals install() replaced, put back by uninstall()


class SimNetError(urllib.error.URLError):
    """An unrouted call: a URLError (what the relay handles everywhere) that says why."""


class Resp(io.BytesIO):
    """An http.client response as far as the relay reads one."""

    def __init__(self, body: "bytes | str | dict | list" = b"", status: int = 200,
                 url: str = "", headers: "dict | None" = None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        super().__init__(body)
        self.status = self.code = status
        self.url = url
        self.reason = "OK"
        self.headers = email.message.Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v
        self.fp = None        # Mailbox.close walks r.fp.raw._sock; None ends the walk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self.url

    def info(self):
        return self.headers


def http_error(url: str, code: int, body: "bytes | str | dict" = b"",
               headers: "dict | None" = None) -> urllib.error.HTTPError:
    if isinstance(body, dict):
        body = json.dumps(body, ensure_ascii=False)
    if isinstance(body, str):
        body = body.encode("utf-8")
    hdrs = email.message.Message()
    for k, v in (headers or {}).items():
        hdrs[k] = v
    return urllib.error.HTTPError(url, code, f"HTTP {code}", hdrs, io.BytesIO(body))


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC8).isoformat(timespec="seconds")


def game_of(*texts: str) -> str:
    for text in texts:
        for g in GAMES:
            if g in (text or ""):
                return g
    return ""


class _Call:
    """One request, decoded."""

    def __init__(self, req, data, timeout, via: str):
        if isinstance(req, str):
            self.url, self.body, self.headers, self.method = req, data, {}, None
        else:
            self.url = req.full_url
            self.body = req.data if req.data is not None else data
            self.headers = {k.lower(): v for k, v in req.header_items()}
            self.method = req.get_method()
        if self.method is None:
            self.method = "POST" if self.body is not None else "GET"
        self.timeout = timeout
        self.via = via
        p = urllib.parse.urlsplit(self.url)
        self.host = (p.hostname or "").lower()
        self.port = p.port
        self.path = p.path or "/"
        self.query = dict(urllib.parse.parse_qsl(p.query, keep_blank_values=True))
        self.bare = f"{p.scheme}://{p.netloc}{p.path}"      # no query: no key= / access_token= kept

    def text(self) -> str:
        b = self.body or b""
        return b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b)

    def json(self):
        try:
            return json.loads(self.text() or "null")
        except ValueError:
            return None


class _Fault:
    def __init__(self, match: str, kind: str, start: float, n: int, body, method: "str | None" = None,
                 title: "str | None" = None):
        self.match, self.kind, self.start, self.left, self.body = match, kind, start, n, body
        self.method, self.title = method, title


class NtfyStream:
    """The held subscription (GET /<topic>/json?since=...): one JSON line per
    message or keepalive, blocking in `sched.park` between them, never on a
    real socket."""

    def __init__(self, net: "FakeNet", topic: str, since: float, read_timeout):
        self.net, self.topic = net, topic
        self.status = self.code = 200
        self.fp = None
        self.closed_flag = False
        self.read_timeout = float(read_timeout or 90)
        self.queue = [{"event": "open"}]
        self.sent: set = set()
        now = net.now()
        self.last_line = now
        for m in net.ntfy_messages(topic, since):
            self.queue.append(m)
            self.sent.add(m["id"])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self) -> None:
        self.closed_flag = True
        self.net.wake()

    def __iter__(self):
        return self

    def _fresh(self) -> "list[dict]":
        return [m for m in self.net.ntfy_messages(self.topic, 0) if m["id"] not in self.sent]

    def __next__(self) -> bytes:
        while True:
            if self.closed_flag:
                raise StopIteration
            if self.queue:
                m = self.queue.pop(0)
                return self._line(m)
            fresh = self._fresh()
            if fresh:
                for m in fresh:
                    self.sent.add(m["id"])
                self.queue.extend(fresh)
                continue
            stall = self.net.stream_fault(self.topic)
            if stall == "drop":
                raise ConnectionResetError(104, "sim: ntfy stream dropped")
            now = self.net.now()
            gap = self.read_timeout if stall == "stall" else NTFY_KEEPALIVE_S
            due = self.last_line + gap
            if now >= due:
                if stall == "stall":
                    raise TimeoutError("timed out")
                self.queue.append({"event": "keepalive"})
                continue
            self.net.sched.park(due - now, lambda: self.closed_flag or bool(self._fresh()))

    def _line(self, m: dict) -> bytes:
        now = self.net.now()
        self.last_line = now
        row = dict(m)
        row.setdefault("id", self.net.next_id())
        row.setdefault("time", int(now))
        row.setdefault("topic", self.topic)
        return (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")


class _Opener:
    """What `urllib.request.build_opener(...)` returns; macpush calls `.open`."""

    def __init__(self, net: "FakeNet"):
        self.net = net

    def open(self, req, data=None, timeout=None):
        return self.net.dispatch(req, data, timeout, via="opener")


class FakeNet:
    def __init__(self, sched, *, code_version: "int | None" = None, inbox: "dict | None" = None,
                 mas=None, mxu=None, ntfy_limit: int = NTFY_LIMIT, mac_url: "str | None" = None):
        self.sched = sched
        self.code_version = code_version if code_version is not None else _manifest_version()
        self.mas = mas                     # fake_mas.FakeMas, or None: AUTO-MAS calls are refused
        self.mxu = mxu                     # MxuModel, or None: 12701 is refused (MaaEnd not running)
        self.ntfy_limit = ntfy_limit
        self.mac_url = mac_url
        self.calls: "list[dict]" = []      # every request: t, method, url without its query, via
        self.cos: "dict[str, bytes]" = {}
        self.ntfy_count: "dict[str, int]" = {}       # UTC date -> publishes accepted
        self._ntfy: "list[dict]" = []                # every message ntfy holds or will hold
        self._ids = 0
        self._faults: "list[_Fault]" = []
        self._web: "list[tuple[str, object]]" = []   # (url prefix, answer), newest first
        self._lock = threading.RLock()
        self.set_inbox(inbox if inbox is not None else {"version": 0})
        self.cos["relay/latest.json"] = json.dumps({"version": self.code_version}).encode()

    # ---------- plumbing ----------

    def now(self) -> float:
        return float(self.sched.now())

    def wake(self) -> None:
        wake = getattr(self.sched, "wake", None)
        if wake:
            wake()

    def next_id(self) -> str:
        with self._lock:
            self._ids += 1
            return f"sim{self._ids:09d}"

    def sim_error(self, what: str, **f) -> None:
        self.sched.out("sim_error", t=iso(self.now()), what=what, **f)

    def note(self, what: str, **f) -> None:
        self.sched.out("sim_note", t=iso(self.now()), what=what, **f)

    def push(self, ch: str, title: str, text: str, game: str = "") -> None:
        self.sched.out("push", t=iso(self.now()), ch=ch, title=title, text=text,
                       game=game or game_of(title, text))

    # ---------- install ----------

    def install(self) -> "FakeNet":
        if _REAL:
            raise RuntimeError("FakeNet already installed")
        _REAL.update(urlopen=urllib.request.urlopen, build_opener=urllib.request.build_opener,
                     connect=socket.socket.connect, connect_ex=socket.socket.connect_ex,
                     create_connection=socket.create_connection, getaddrinfo=socket.getaddrinfo)
        urllib.request.urlopen = self.urlopen
        urllib.request.build_opener = self.build_opener
        socket.socket.connect = self._raw_connect
        socket.socket.connect_ex = self._raw_connect
        socket.create_connection = self._raw_connect
        # service._wait_for_network resolves raw.githubusercontent.com before the boot
        # goes on (up to 90 s of retries): resolving always works, connecting never does.
        socket.getaddrinfo = lambda host, port, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", port or 443))]
        return self

    @staticmethod
    def uninstall() -> None:
        if not _REAL:
            return
        urllib.request.urlopen = _REAL["urlopen"]
        urllib.request.build_opener = _REAL["build_opener"]
        socket.socket.connect = _REAL["connect"]
        socket.socket.connect_ex = _REAL["connect_ex"]
        socket.create_connection = _REAL["create_connection"]
        socket.getaddrinfo = _REAL["getaddrinfo"]
        _REAL.clear()

    def _raw_connect(self, *a, **k):
        target = a[1] if len(a) > 1 and not isinstance(a[0], tuple) else (a[0] if a else k.get("address"))
        self.sim_error("raw socket connect", target=repr(target))
        raise ConnectionRefusedError(111, "daysim: no real network")

    def urlopen(self, req, data=None, timeout=None, **kw):
        return self.dispatch(req, data, timeout, via="urlopen")

    def build_opener(self, *handlers):
        return _Opener(self)

    # ---------- inputs W5 feeds from events.jsonl ----------

    def set_inbox(self, doc: dict) -> None:
        """The queue file every inbox door serves (inbox.py: COS relay/queue/config.json,
        then the GitHub doors). Default {"version": 0}: nothing newer than applied."""
        raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        with self._lock:
            self.inbox = raw
            self.cos["relay/queue/config.json"] = raw

    def phone_order(self, t: float, body: dict, pin: str, topic: str, *, ts: "int | None" = None,
                    raw: "str | None" = None) -> str:
        """A press on the phone: an ntfy message on `topic` that exists from `t` on.
        The envelope is wire.pack's (v, kind=cmd, pin, ts, body) unless `raw` is given."""
        msg = raw if raw is not None else json.dumps(
            {"v": 1, "kind": "cmd", "pin": pin, "ts": int(ts if ts is not None else t), "body": body},
            ensure_ascii=False, separators=(",", ":"))
        mid = self.next_id()
        with self._lock:
            self._ntfy.append({"id": mid, "time": int(t), "event": "message", "topic": topic,
                               "message": msg, "_from": "phone"})
            self._ntfy.sort(key=lambda m: m["time"])
        self.wake()
        return mid

    def fault(self, match: str, kind: str, *, start: "float | None" = None, n: int = 1,
              body=None, method: "str | None" = None, title: "str | None" = None) -> None:
        """The next `n` calls whose URL contains `match`, from `start` on, fail:
        kind "timeout" (waits the call's timeout, then TimeoutError), "refused",
        "reset", "http:<code>" (with `body`, e.g. ntfy's 42908), or on an ntfy
        stream "drop" / "stall" (no line until the read timeout). `method` limits
        it to calls with that HTTP method (an ntfy publish POSTs to the URL the
        stream GETs below); `title` to calls with that Title header (an ntfy publish's
        kind: state, hb, bye)."""
        with self._lock:
            self._faults.append(_Fault(match, kind, self.now() if start is None else start, n, body,
                                       method.upper() if method else None, title))

    def set_web(self, prefix: str, answer) -> None:
        """Override an information source: every URL starting with `prefix` gets
        `answer` - bytes / str / dict, or a callable(call) returning one or a Resp."""
        with self._lock:
            self._web.insert(0, (prefix, answer))

    # ---------- dispatch ----------

    def dispatch(self, req, data, timeout, via: str):
        c = _Call(req, data, timeout, via)
        now = self.now()
        with self._lock:
            self.calls.append({"t": iso(now), "method": c.method, "url": c.bare, "via": via})
        self._apply_fault(c)
        if via == "opener":
            return self._mac(c)
        route = self._route(c)
        if route is None:
            self.sim_error("unrouted URL", url=c.bare, method=c.method)
            raise SimNetError(f"daysim: no route for {c.bare}")
        return route(c)

    def _apply_fault(self, c: _Call) -> None:
        with self._lock:
            f = next((f for f in self._faults
                      if f.left > 0 and f.match in c.url and self.now() >= f.start
                      and f.kind not in ("drop", "stall") and f.method in (None, c.method)
                      and f.title in (None, c.headers.get("title"))), None)
            if f is None:
                return
            f.left -= 1
        if f.kind == "timeout":
            time.sleep(float(c.timeout or 30))
            raise TimeoutError("timed out")
        if f.kind == "refused":
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        if f.kind == "reset":
            raise ConnectionResetError(104, "Connection reset by peer")
        if f.kind.startswith("http:"):
            raise http_error(c.bare, int(f.kind[5:]), f.body or b"")
        raise ValueError(f"unknown fault kind {f.kind!r}")

    def stream_fault(self, topic: str) -> str:
        with self._lock:
            f = next((f for f in self._faults if f.left > 0 and f.kind in ("drop", "stall")
                      and f.match in topic and self.now() >= f.start), None)
            if f is None:
                return ""
            f.left -= 1
            return f.kind

    def _route(self, c: _Call):
        h = c.host
        if h in ("127.0.0.1", "localhost"):
            if c.port == int(os.environ.get("ARK_MAS_PORT", "36163")):
                return self._automas
            if c.port == 12701 or (self.mxu is not None and c.port == self.mxu.port):
                return self._mxu
            return None
        for prefix, answer in self._web:
            if c.url.startswith(prefix):
                return lambda call, a=answer: self._answer(call, a)
        if h == "ntfy.sh":
            return self._ntfy_route
        if h == "qyapi.weixin.qq.com":
            return self._wecom
        if h == "sctapi.ftqq.com" or h.endswith(".push.ft07.com"):
            return self._serverchan
        if re.fullmatch(r"[a-z0-9-]+\.cos\.[a-z0-9-]+\.myqcloud\.com", h):
            return self._cos
        if h in ("raw.githubusercontent.com", "fastly.jsdelivr.net", "cdn.jsdelivr.net",
                 "gcore.jsdelivr.net", "gh-proxy.com"):
            return self._github
        if h == "api.gofile.io" or h.endswith(".gofile.io"):
            return self._gofile
        if h == "api.deepseek.com" or h == "api.anthropic.com" or "llm" in h:
            return self._llm
        if h in WEB_DEFAULTS:
            return lambda call: self._answer(call, WEB_DEFAULTS[h])
        return None

    def _answer(self, c: _Call, answer):
        if callable(answer):
            answer = answer(c)
        if isinstance(answer, Resp):
            return answer
        if isinstance(answer, BaseException):
            raise answer
        return Resp(answer, url=c.url)

    # ---------- push channels ----------

    def _wecom(self, c: _Call):
        p = c.path
        if p.endswith("/gettoken"):
            return Resp({"errcode": 0, "errmsg": "ok", "access_token": "sim-token", "expires_in": 7200})
        if p.endswith("/media/upload") or p.endswith("/webhook/upload_media"):
            return Resp({"errcode": 0, "errmsg": "ok", "type": "file", "media_id": "sim-media"})
        body = c.json() or {}
        ch = "group" if p.endswith("/webhook/send") else "wecom_app" if p.endswith("/message/send") else ""
        if not ch:
            self.sim_error("unrouted WeCom endpoint", url=c.bare)
            raise http_error(c.bare, 404)
        kind = body.get("msgtype")
        if kind == "text":
            text = str((body.get("text") or {}).get("content") or "")
            self.push(ch, text.split("\n", 1)[0], text)
        elif kind in ("image", "file"):
            self.push(ch, f"[{kind}]", json.dumps({k: v for k, v in (body.get(kind) or {}).items()
                                                   if k != "base64"}, ensure_ascii=False))
        else:
            self.push(ch, f"[{kind}]", c.text()[:2000])
        return Resp({"errcode": 0, "errmsg": "ok"})

    def _serverchan(self, c: _Call):
        f = dict(urllib.parse.parse_qsl(c.text(), keep_blank_values=True))
        title, desp = f.get("title", ""), f.get("desp", "")
        # ServerChan.send_text doubles every line break for Markdown; undo it.
        self.push("serverchan", title, desp.replace("\n\n", "\n"))
        return Resp({"code": 0, "message": "", "data": {"pushid": "sim", "readkey": "sim", "error": "SUCCESS",
                                                       "errno": 0}})

    def _mac(self, c: _Call):
        want = self.mac_url or os.environ.get("ARK_ALERT_PUSH_URL") or ""
        if want and not c.url.startswith(want) and not c.path.endswith("/alert"):
            self.sim_error("unrouted opener URL", url=c.bare)
            raise SimNetError(f"daysim: no route for {c.bare}")
        row = c.json() or {}
        self.push("mac", str(row.get("title") or ""), str(row.get("text") or ""), str(row.get("game") or ""))
        return Resp(b'{"ok":true}')

    # ---------- ntfy ----------

    @staticmethod
    def utc_day(t: float) -> str:
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")

    def ntfy_messages(self, topic: str, since: float) -> "list[dict]":
        """Messages on `topic` that exist now, newer than `since`, inside the cache."""
        now = self.now()
        lo = max(since, now - NTFY_CACHE_S)
        with self._lock:
            return [{k: v for k, v in m.items() if not k.startswith("_")} for m in self._ntfy
                    if m["topic"] == topic and lo < m["time"] <= now]

    def _since(self, raw: str) -> float:
        now = self.now()
        raw = (raw or "").strip()
        if raw in ("", "all"):
            return 0.0
        if raw.isdigit():
            return float(raw)
        m = re.fullmatch(r"(\d+)([smhd])", raw)
        if m:
            return now - int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
        with self._lock:
            hit = next((x["time"] for x in self._ntfy if x["id"] == raw), None)
        if hit is not None:
            return float(hit)
        self.sim_error("ntfy since not understood", since=raw)
        return 0.0

    def _ntfy_route(self, c: _Call):
        parts = [p for p in c.path.split("/") if p]
        if parts == ["v1", "account"]:
            n = self.ntfy_count.get(self.utc_day(self.now()), 0)
            return Resp({"limits": {"messages": self.ntfy_limit},
                         "stats": {"messages": n, "messages_remaining": max(0, self.ntfy_limit - n)}})
        if len(parts) == 1 and c.method in ("POST", "PUT"):
            return self._ntfy_publish(c, parts[0])
        if len(parts) == 2 and parts[1] == "json" and c.method == "GET":
            since = self._since(c.query.get("since", ""))
            if c.query.get("poll") == "1":
                lines = [json.dumps(m, ensure_ascii=False) for m in self.ntfy_messages(parts[0], since)]
                return Resp("\n".join(lines) + ("\n" if lines else ""), url=c.url)
            return NtfyStream(self, parts[0], since, c.timeout)
        self.sim_error("unrouted ntfy call", url=c.bare, method=c.method)
        raise http_error(c.bare, 404)

    def _ntfy_publish(self, c: _Call, topic: str):
        now = self.now()
        day = self.utc_day(now)
        with self._lock:
            if self.ntfy_count.get(day, 0) >= self.ntfy_limit:
                refused = True
            else:
                refused = False
                self.ntfy_count[day] = self.ntfy_count.get(day, 0) + 1
                mid = self.next_id()
                msg = {"id": mid, "time": int(now), "event": "message", "topic": topic,
                       "message": c.text(), "_from": "relay"}
                title = c.headers.get("title") or c.headers.get("x-title") or ""
                if title:
                    msg["title"] = title
                self._ntfy.append(msg)
        if refused:
            raise http_error(c.bare, 429, NTFY_QUOTA_BODY)
        self.push("ntfy", title or topic, c.text())
        self.wake()
        return Resp({"id": mid, "time": int(now), "event": "message", "topic": topic}, url=c.url)

    # ---------- COS ----------

    def _state_out(self, key: str, data: bytes) -> None:
        """The phone's state as the App reads it from COS (cos_store.state_key; the
        envelope of wire.pack, the body gzip+base64 under `gz` when large), an output:
        what the phone holds after a stop is the last one (R05: 10-07's stop push
        carried empty queues and an empty Arknights config, 7c7c165b)."""
        try:
            env = json.loads(data.decode("utf-8"))
            body = env.get("body")
            if body is None and "gz" in env:
                body = json.loads(gzip.decompress(base64.b64decode(env["gz"])).decode("utf-8"))
        except (ValueError, OSError, AttributeError) as exc:
            self.sim_error("phone state on COS not readable", key=key, why=f"{type(exc).__name__}: {exc}")
            return
        self.sched.out("phone_state", t=iso(self.now()), key=key, env_kind=env.get("kind"), body=body)

    def _cos(self, c: _Call):
        key = urllib.parse.unquote(c.path.lstrip("/"))
        if c.method == "HEAD":
            return Resp(b"", url=c.url)
        if c.method == "PUT":
            data = c.body if isinstance(c.body, bytes) else str(c.body or "").encode()
            with self._lock:
                self.cos[key] = data
            if key.startswith("state/") and not key.endswith(".hb.json"):     # cos_store.state_key, not hb_key
                self._state_out(key, data)
            return Resp(b"", url=c.url)
        if c.method == "GET":
            with self._lock:
                data = self.cos.get(key)
            if data is None:
                raise http_error(c.bare, 404, b"<Error><Code>NoSuchKey</Code></Error>")
            return Resp(data, url=c.url)
        self.sim_error("unrouted COS call", url=c.bare, method=c.method)
        raise http_error(c.bare, 405)

    # ---------- GitHub doors (self-update, inbox, pinned upstream files) ----------

    def _github(self, c: _Call):
        path = c.path
        if c.host == "gh-proxy.com":
            path = urllib.parse.urlsplit(c.path.lstrip("/")).path
        m = (re.fullmatch(r"/gh/([^/]+)/([^@/]+)@([^/]+)/(.+)", path)
             or re.fullmatch(r"/([^/]+)/([^/]+)/([^/]+)/(.+)", path))
        if not m:
            self.sim_error("unrouted GitHub door", url=c.bare)
            raise http_error(c.bare, 404)
        owner, repo, _branch, rel = m.groups()
        if (owner, repo) == ("herclyon1", "maa"):
            if rel == "queue/config.json":
                with self._lock:
                    return Resp(self.inbox, url=c.url)
            if rel.startswith("relay/") and (RELAY / rel[len("relay/"):]).is_file():
                return Resp((RELAY / rel[len("relay/"):]).read_bytes(), url=c.url)
        pin = UPSTREAM_COPIES.get(Path(rel).name) or SOURCE_PINS / Path(rel).name
        if pin.is_file():
            return Resp(pin.read_bytes(), url=c.url)
        self.sim_error("GitHub file not modelled", url=c.bare)
        raise http_error(c.bare, 404)

    # ---------- evidence stores, LLM ----------

    def _gofile(self, c: _Call):
        if c.path == "/servers":
            return Resp({"status": "ok", "data": {"servers": [{"name": "store1", "zone": "eu"}]}})
        if c.path.endswith("/contents/uploadfile"):
            return Resp({"status": "ok", "data": {"id": "sim", "name": "sim", "md5": "",
                                                  "downloadPage": "https://gofile.io/d/sim",
                                                  "guestToken": "sim-guest", "parentFolder": "sim-folder"}})
        self.sim_error("unrouted gofile call", url=c.bare)
        raise http_error(c.bare, 404)

    def _llm(self, c: _Call):
        self.note("LLM asked; answered with no wording", url=c.bare)
        return Resp({"choices": [{"message": {"role": "assistant", "content": ""}}],
                     "content": [{"type": "text", "text": ""}]})

    # ---------- local services ----------

    def _automas(self, c: _Call):
        if self.mas is None:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "AUTO-MAS backend not modelled"))
        return Resp(self.mas.handle(c.method, c.path, c.json()), url=c.url)

    def _mxu(self, c: _Call):
        if self.mxu is None:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "MaaEnd MXU not running"))
        return Resp(self.mxu.handle(c.method, c.path, c.query, c.json()), url=c.url)


class MxuModel:
    """MaaEnd's MXU web API (collect_retry.api, http://127.0.0.1:12701/api) while
    the World has MaaEnd.exe up. `alive()` comes from the World's process table;
    a started task runs `task_s` sim seconds (the recorded run's length). Not
    recorded anywhere yet: a synthesized input (design.md section 4)."""

    def __init__(self, sched, alive, *, port: int = 12701, task_s: float = 0.0, hwnd: int = 0x1234):
        self.sched, self.alive, self.port, self.task_s, self.hwnd = sched, alive, port, task_s, hwnd
        self.connected = self.loaded = False
        self.ends = 0.0

    def handle(self, method: str, path: str, query: dict, body):
        if not self.alive():
            raise urllib.error.URLError(ConnectionRefusedError(10061, "MaaEnd MXU not running"))
        now = float(self.sched.now())
        rel = path[len("/api"):] if path.startswith("/api") else path
        if rel == "/maa/state":
            return {"instances": {"automas": {"connected": self.connected, "resource_loaded": self.loaded,
                                              "is_running": now < self.ends}}}
        if rel == "/maa/windows":
            return {"windows": [{"handle": self.hwnd, "class_name": "UnityWndClass", "window_name": "Endfield"}]}
        if rel.endswith("/connect"):
            self.connected = True
        elif rel.endswith("/resource/load"):
            self.loaded = True
        elif rel.endswith("/tasks/start"):
            self.ends = now + self.task_s
            self.sched.out("sim_note", t=iso(now), what="MXU task started", task_s=self.task_s)
        elif rel.endswith("/tasks/stop") or rel.endswith("/agent/stop"):
            self.ends = min(self.ends, now)
        else:
            raise http_error(f"http://127.0.0.1:{self.port}{path}", 404)
        return {"success": True}


def _manifest_version() -> int:
    try:
        return int(json.loads((RELAY / "manifest.json").read_text(encoding="utf-8")).get("version") or 0)
    except (OSError, ValueError):
        return 0


# "Nothing new" for every information source the relay reads on a normal day,
# in the shape its parser reads (an error or a non-JSON page would log the
# 「不知道它有没有停服维护」 WARNING the probe produced). Keyed by host.
def _hg_news(c: _Call):
    # ak.hypergryph.com/api/news (banners.ak_news_pages) and web-news.hypergryph.com
    # /api/bulletin lists: no posts; a single post (bulletin/<cid>) never asked for.
    return {"code": 0, "msg": "", "data": {"list": [], "total": 0, "end": True}}


def _prts(c: _Call):
    # The limited-banner table (arknights._ak_prts_rows): the API's wikitext, or the
    # rendered page; both from the repo's recorded copies (tests/fixtures/prts_limited.*).
    # An empty table is not "nothing new" there: it logs a WARNING and drops the section.
    if c.path.endswith("/api.php"):
        return {"parse": {"title": c.query.get("page", ""),
                          "wikitext": {"*": (FIXTURES / "prts_limited.wikitext").read_text(encoding="utf-8")}}}
    return (FIXTURES / "prts_limited_page.html").read_bytes()


WEB_DEFAULTS: "dict[str, object]" = {
    "ak.hypergryph.com": _hg_news,
    "web-news.hypergryph.com": _hg_news,
    "game-hub.hypergryph.com": {"code": 0, "msg": "", "data": {}},
    "endfield.hypergryph.com": "<html><body></body></html>",
    "aki-gm-resources-back.aki-game.com": {"game": [], "activity": []},
    "media-cdn-mingchao.kurogame.com": [],
    "prts.wiki": _prts,
    "api.kurobbs.com": {"code": 200, "msg": "", "success": True, "data": {}},
    "api.bilibili.com": {"code": 0, "message": "0", "data": {}},
}
