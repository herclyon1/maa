"""The phone channel says WARNING only when something is wrong (2026-10-06).

Every WARNING the relay logs is now pushed to the group. The user, 10-06:
「你正常情况应该一条都不发的」. The 10-06 sweep of relay.log found the phone
channel behind most of them; each check below is one of those lines:

* #40 #52 #54 ntfy's 42908 (the day's 250 used up) was logged by every beat,
  every state, every piece and every restart's bye: now once per UTC day, and
  nothing is posted into a refused day;
* #42 #47 #48 a state stored on COS was logged 「状态没能上报到手机」 because the
  one-line notice after it was refused: stored on COS is delivered;
* #44 a timed-out post was a WARNING per try: one reason in last_error, the
  caller writes the one line, and only when the phone cannot see the state;
* #39 #49 a 429 (42901) or a 5xx was not retried, or retried without a pause:
  one more try after a pause, Retry-After honoured; 42908 / other 4xx never;
* #51 a lost piece dropped the rest with a WARNING: the piece is retried
  first, a set that still breaks is the caller's one line;
* #41 a boot mailbox read that timed out lost the presses made while the
  machine was off: read again by listen() once ntfy answers;
* #45 #49 #57 every dropped stream was a WARNING and the reconnect only
  replayed 10 minutes: drops are INFO and replay from the last line read; ten
  minutes down is one WARNING;
* #56 one COS heartbeat timeout was a WARNING: INFO (ntfy still beats);
* the ledger said 「今天 ntfy 已发 0 条」 beside ntfy's 42908: ntfy's own count
  (GET /v1/account) is taken in, and the relay stops itself short of 250.
Fake network throughout; nothing waits for real.
"""
import io
import json
import logging
import os
import sys
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay import phone
from ark_relay.evidence import Cos

PIN = "8964"
TOPIC = "topic-abc"
COS = Cos("AKIDtest", "secret", "ark-evidence-1", "ap-shanghai")
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
    if not ok:
        fails.append(label)


def section(title, fn):
    """Run one block; an exception (old code without the new names) is a failure, not an abort."""
    print(f"\n[{title}]")
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ {title}: {type(exc).__name__}: {exc}")
        fails.append(title)


class FakeResp:
    def __init__(self, body: bytes = b"", status: int = 200):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(io.BytesIO(self._body))

    def read(self):
        return self._body

    def close(self):
        pass


class FakeNet:
    """Records every request (url, method, body); canned answers in order, then 200."""

    def __init__(self, *answers):
        self.sent: list[tuple[str, str, bytes]] = []
        self.queue = list(answers)

    def urlopen(self, req, timeout=None):
        self.sent.append((req.full_url, req.get_method(), req.data or b""))
        if not self.queue:
            return FakeResp()
        nxt = self.queue.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt

    def posts(self):
        return [(u, b) for u, m, b in self.sent if m == "POST"]


def use(net):
    phone.urllib = types.SimpleNamespace(
        request=types.SimpleNamespace(Request=urllib.request.Request, urlopen=net.urlopen),
        error=urllib.error)


class Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.recs: list[tuple[int, str]] = []

    def emit(self, record):
        self.recs.append((record.levelno, record.getMessage()))

    def warnings(self):
        return [m for lv, m in self.recs if lv >= logging.WARNING]

    def infos(self, word):
        return [m for lv, m in self.recs if lv == logging.INFO and word in m]


logs = Logs()
phone.log.addHandler(logs)
phone.log.setLevel(logging.DEBUG)
phone.log.propagate = False


def ntfy_error(http: int, code: int = 0, text: str = "", headers=None):
    body = json.dumps({"code": code, "http": http, "error": text}).encode() if code else b""
    return urllib.error.HTTPError("https://ntfy.sh/x", http, "err", headers or {}, io.BytesIO(body))


def quota_full():
    return ntfy_error(429, 42908, "limit reached: daily message quota reached")


def mailbox(cos=None, state_dir=None):
    mb = phone.Mailbox(TOPIC, PIN, state_dir or tmpdir(), cos=cos)
    mb.RETRY_AFTER = 1
    mb.slept = []
    mb._sleep = mb.slept.append
    return mb


# 43 KB raw, ~13 KB gzipped on 10-02: incompressible, so it is pieces or COS.
BIG = {"at": 1, "options": {"x": __import__("base64").b64encode(os.urandom(9600)).decode()}}


def a_quota_once():
    logs.recs.clear()
    d = tmpdir()
    mb = mailbox(state_dir=d)
    net = FakeNet(quota_full())
    use(net)
    check("ntfy 回 42908：这份状态没发出去", mb.publish({"at": 1}), False)
    check("……记一条 WARNING，说额度用完了",
          [("额度用完" in m) for m in logs.warnings()], [True])
    mb.publish({"at": 2})
    mb.publish({"at": 3})
    check("之后的状态不再去撞 ntfy（一个请求都不多发）", len(net.sent), 1)
    check("……也不再多记 WARNING（10-02 晚 ×47 + ×14）", len(logs.warnings()), 1)
    beats = []
    hb = phone.Heartbeat(TOPIC, d, post=lambda p, t: beats.append(t))
    hb.beat()
    hb.bye()
    check("同一天：心跳和 bye 都不发（10-02 23:29:36 重启时的 bye 又报了一次）", beats, [])
    check("……还是只有那一条 WARNING", len(logs.warnings()), 1)
    logs.recs.clear()
    d2 = tmpdir()
    raw = phone.Heartbeat(TOPIC, d2, account=lambda: {})
    raw.url = "https://ntfy.sh/x-hb"
    use(FakeNet(quota_full()))
    raw.beat()
    use(FakeNet())
    mailbox(state_dir=d2).publish({"at": 1})
    check("心跳先撞到 42908、状态后到：一天一共一条 WARNING", len(logs.warnings()), 1)


def b_cos_is_delivered():
    logs.recs.clear()
    mb = mailbox(cos=COS)
    net = FakeNet(FakeResp(), TimeoutError("The read operation timed out"),
                  TimeoutError("The read operation timed out"))
    use(net)
    check("COS 存上了、ntfy 通知超时两次：手机读得到，算送到了", mb.publish(BIG), True)
    check("……不记 WARNING", logs.warnings(), [])
    check("……INFO 里说了状态在 COS 上", bool(logs.infos("腾讯云 COS")), True)
    logs.recs.clear()
    d = tmpdir()
    mb = mailbox(cos=COS, state_dir=d)
    mb.quota.mark_full("测试")
    logs.recs.clear()
    net = FakeNet()
    use(net)
    check("额度已满时 COS 照存：算送到了（10-02 22:56 起这里被记成没上报）", mb.publish(BIG), True)
    check("……只有 COS 的 PUT，ntfy 一个请求都没有", [m for _, m, _ in net.sent], ["PUT"])
    check("……不记 WARNING", logs.warnings(), [])


def c_timeout_one_reason():
    logs.recs.clear()
    mb = mailbox()
    net = FakeNet(TimeoutError("The read operation timed out"), TimeoutError("The read operation timed out"))
    use(net)
    check("没配 COS、ntfy 连超时两次：没送到", mb.publish({"at": 1}), False)
    check("……phone 自己不记 WARNING（调用方记那一条）", logs.warnings(), [])
    why = getattr(mb, "last_error", "")
    check("……原因写进 last_error：超时、试了 2 次",
          ("timed out" in why, "试了 2 次" in why), (True, True))
    check("……两次之间停了一下", mb.slept, [1])
    logs.recs.clear()
    mb = mailbox(cos=COS)
    use(FakeNet(urllib.error.URLError("timed out"), TimeoutError("t1"), TimeoutError("t2")))
    check("COS 和 ntfy 都不通：没送到", mb.publish({"at": 1}), False)
    check("……原因两边都说", ("腾讯云 COS" in mb.last_error, "ntfy" in mb.last_error), (True, True))


def d_retry_rules():
    mb = mailbox()
    net = FakeNet(ntfy_error(429, 42901, "limit reached: too many requests", {"Retry-After": "7"}), FakeResp())
    use(net)
    check("42901（请求太密）：等一会儿再试一次就送到", mb.publish({"at": 1}), True)
    check("……一共两次请求", len(net.sent), 2)
    check("……按 Retry-After 等了 7 秒", mb.slept, [7])
    mb = mailbox()
    net = FakeNet(ntfy_error(502), FakeResp())
    use(net)
    check("502（ntfy 前面的网关，09-23 / 10-05 见过）：再试一次", (mb.publish({"at": 1}), len(net.sent)), (True, 2))
    check("……先停 RETRY_AFTER 秒", mb.slept, [1])
    mb = mailbox()
    net = FakeNet(ntfy_error(400, 40001, "bad"))
    use(net)
    check("400：同样的内容再发也是 400，不重试", (mb.publish({"at": 1}), len(net.sent)), (False, 1))
    mb = mailbox()
    net = FakeNet(quota_full())
    use(net)
    check("42908：不重试", (mb.publish({"at": 1}), len(net.sent)), (False, 1))


def e_pieces():
    logs.recs.clear()
    mb = mailbox()
    net = FakeNet(FakeResp(), ntfy_error(502), FakeResp(), FakeResp(), FakeResp())
    use(net)
    check("第 2 片碰上一次 502：这一片重试，整份送到", mb.publish(BIG), True)
    pieces = [json.loads(b) for _, b in net.posts()]
    check("……四片都到了 ntfy（同一个 sid，序号 0-3 各一次）",
          (len({p["sid"] for p in pieces}), sorted({p["i"] for p in pieces})), (1, [0, 1, 2, 3]))
    logs.recs.clear()
    mb = mailbox()
    net = FakeNet(FakeResp(), TimeoutError("t1"), TimeoutError("t2"))
    use(net)
    check("第 2 片两次都超时：这份没送到", mb.publish(BIG), False)
    check("……剩下的片不发（拼不起来）", len(net.sent), 3)
    check("……不记 WARNING（调用方记那一条）", logs.warnings(), [])
    check("……last_error 说是第 2 片", "第 2 片" in getattr(mb, "last_error", ""), True)


def ntfy_lines(*events):
    return ("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n").encode("utf-8")


def f_backlog_read_again():
    logs.recs.clear()
    mb = mailbox()
    use(FakeNet(TimeoutError("The read operation timed out")))
    check("开机读信箱超时：先给空的", mb.fetch(), [])
    check("……不记 WARNING（#41，08-31 到 10-02 共 11 次）", logs.warnings(), [])
    check("……记下要补读", getattr(mb, "backlog_missed", False), True)
    now = int(time.time())
    skip = phone.pack(PIN, {"action": "skip_today", "queue": "早班"})
    later = phone.pack(PIN, {"action": "debug_mode", "days": 1})
    net = FakeNet(FakeResp(ntfy_lines({"id": "b1", "time": now - 3600, "event": "message", "message": skip})),
                  FakeResp(ntfy_lines({"id": "o", "time": now, "event": "open"},
                                      {"id": "s1", "time": now, "event": "message", "message": later})))
    use(net)
    backlog, live = [], []
    mb.listen(live.append, lambda: not net.queue and len(live) >= 1, on_backlog=backlog.extend)
    check("手机通道连上后补读到关机期间按的那条",
          [(b.get("action"), b["_meta"]["via"]) for b in backlog], [("skip_today", "backlog")])
    check("……补读的那条走开机积压那条路（on_backlog），不当成在线按的", [b.get("action") for b in live], ["debug_mode"])
    check("……先补读、再订阅", ("poll=1" in net.sent[0][0], "poll=1" in net.sent[1][0]), (True, False))
    check("……补读完就不再补", mb.backlog_missed, False)


def g_stream_drops():
    logs.recs.clear()
    mb = mailbox()
    t = int(time.time()) - 100
    net = FakeNet(FakeResp(ntfy_lines({"id": "o", "time": t, "event": "open"},
                                      {"id": "k", "time": t + 45, "event": "keepalive"})),
                  TimeoutError("The read operation timed out"),
                  ntfy_error(502),
                  urllib.error.URLError(ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。")),
                  FakeResp(ntfy_lines({"id": "o2", "time": t + 90, "event": "open"})),
                  TimeoutError("again"))
    use(net)
    mb.listen(lambda b: None, lambda: len(net.sent) >= 6)
    check("读超时、502、对方重置，几秒内又连上：一条 WARNING 都没有（#45 #49 #57）", logs.warnings(), [])
    check("……每次断开记一行 INFO", len(logs.infos("手机通道断了")), 3)
    check("……重连从读到的最后一行接着要（不是固定的 10 分钟）",
          [u.split("since=")[1] for u, _, _ in net.sent[1:4]], [str(t + 45 - 30)] * 3)
    check("……再连上记一行 INFO", bool(logs.infos("又连上了")), True)
    logs.recs.clear()
    mb = mailbox()
    mb.OUTAGE_SEC = 0                  # "ten minutes" without waiting ten minutes
    net = FakeNet(TimeoutError("t1"), ntfy_error(502), TimeoutError("t3"), FakeResp(b""), TimeoutError("t5"))
    use(net)
    mb.listen(lambda b: None, lambda: len(net.sent) >= 4)
    check("一直连不上到时限：一次断线只记一条 WARNING", len(logs.warnings()), 1)
    check("……说清连不上多久、手机发的指令到不了", "手机通道连不上 ntfy" in (logs.warnings() or [""])[0], True)


def h_cos_beat_info():
    logs.recs.clear()
    use(FakeNet(urllib.error.URLError("timed out")))
    hb = phone.Heartbeat(TOPIC, tmpdir(), post=lambda p, t: None, cos=COS)
    check("COS 心跳超时一次、ntfy 心跳照发", hb.beat(), True)
    check("……不记 WARNING（10-03 00:16:44 那条）", logs.warnings(), [])
    check("……记一行 INFO", bool(logs.infos("腾讯云 COS")), True)


def i_ntfy_count():
    logs.recs.clear()
    q = phone.Quota(tmpdir())
    q.add("hb", 5)
    check("ntfy 自己的计数读进来", q.sync({"stats": {"messages": 240, "messages_remaining": 10}}), 240)
    check("……今天用了多少按 ntfy 的算（不是本机账本的 5）", q.total(), 240)
    q.add("state")
    check("……之后中继再发的照加", (q.total(), q.own()), (241, 6))
    check("……过了停跳线，心跳只走 COS", q.stops_beats(), True)
    check("没有 stats 的回答不算数，账本照旧", phone.Quota(tmpdir()).sync({"error": "x"}), None)
    q2 = phone.Quota(tmpdir())
    q2.sync({"stats": {"messages": 250, "messages_remaining": 0}})
    check("ntfy 说剩 0 条：记成今天满了，一条 WARNING", (q2.full(), len(logs.warnings())), (True, 1))
    hb = phone.Heartbeat(TOPIC, tmpdir(), post=lambda p, t: None,
                         account=lambda: {"stats": {"messages": 150, "messages_remaining": 100}})
    hb.sync_quota()
    check("心跳的节奏跟着 ntfy 的计数走（150 条 → 5 分钟一跳）", hb.interval(), phone.HB_SLOW_SEC)
    net = FakeNet(FakeResp(json.dumps({"limits": {"messages": 250},
                                       "stats": {"messages": 12, "messages_remaining": 238}}).encode()))
    use(net)
    check("ntfy_account：GET /v1/account，解出 stats", phone.ntfy_account()["stats"]["messages"], 12)
    check("……问的是 ntfy.sh/v1/account", net.sent[0][:2], ("https://ntfy.sh/v1/account", "GET"))
    plain = phone.Heartbeat(TOPIC, tmpdir(), post=lambda p, t: None)
    check("测试里给了假心跳就不去问 ntfy 的计数", plain._account, None)
    check("线上（不给 post）才问", phone.Heartbeat(TOPIC, tmpdir())._account, phone.ntfy_account)


def j_budget():
    d = tmpdir()
    mb = mailbox(cos=COS, state_dir=d)
    mb.quota.add("hb", phone.NOTICE_STOP_AT)
    net = FakeNet()
    use(net)
    check("今天已用到 230：状态照存 COS、算送到", mb.publish(BIG), True)
    check("……ntfy 的通知不发了（留给 bye 和手机的指令）", [m for _, m, _ in net.sent], ["PUT"])
    beats = []
    hb = phone.Heartbeat(TOPIC, tmpdir(), post=lambda p, t: beats.append(t), cos=COS)
    hb.quota.add("state", phone.HB_STOP_AT)
    net = FakeNet()
    use(net)
    check("今天已用到 200：ntfy 不再跳", (hb.beat(), beats), (False, []))
    check("……COS 心跳照写，App 照样看得到开机", [m for _, m, _ in net.sent], ["PUT"])
    check("……COS 上告诉 App 节奏放宽了", json.loads(net.sent[0][2])["every"] >= phone.HB_SLOW_SEC, True)


for title, fn in (("#40 #52 #54：额度用完一天只说一次，之后不再去撞", a_quota_once),
                  ("#42 #47 #48：存进 COS 就算送到", b_cos_is_delivered),
                  ("#44：超时只给一个原因，不在每次尝试时报", c_timeout_one_reason),
                  ("#39 #49：429/5xx 停一下再试，42908 和其他 4xx 不试", d_retry_rules),
                  ("#51：切片先重试那一片，断了也只由调用方报一次", e_pieces),
                  ("#41：开机读信箱超时，等通道连上补读", f_backlog_read_again),
                  ("#45 #49 #57：断线重连是 INFO，连不上十分钟才 WARNING", g_stream_drops),
                  ("#56：COS 心跳一次超时是 INFO", h_cos_beat_info),
                  ("「今天 ntfy 已发 0 条」：用 ntfy 自己的计数", i_ntfy_count),
                  ("中继自己停在 250 之前", j_budget)):
    section(title, fn)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
