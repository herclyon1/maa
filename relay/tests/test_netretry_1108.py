"""Another try, inside the caller's own limit, for a request the network cut short
(dispatch relay-opt-round3-1108 O-03; core/netretry.py).

Pinned here:
* transient(): timeouts, short bodies, resets, DNS failures and the gateway statuses
  502 / 503 / 504 are tried again; any other HTTP status (404, 403, 500) is not;
* call(): at most notify._RETRIES attempts, the first with the whole limit and each later one
  with what is left; no retry once the pause would use the rest (an 8 s COS write that timed
  out is not tried again, so the 30 s service stop still fits); INFO per failed attempt, one
  WARNING marked recovered when a later one went through, the last failure raised;
* cos_put / cos_get: a reset is tried again, a 404 / 403 is not, and they still never raise;
* efstatus.update_hint: a gateway 503 is tried again within its 8 s;
* needtable build._retry: a 404 is raised at once, a 503 or a reset is asked again.
"""
import http.client
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ark_relay.core import netretry, notify
from ark_relay.features.alarm import errwatch
from ark_relay.features.maintenance import efstatus
from ark_relay.features.needtable import build
from ark_relay.features.phone import cos_store

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


class Rows(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.rows = []

    def emit(self, record):
        self.rows.append((record.levelname, bool(getattr(record, errwatch.RECOVERED, False)), record.getMessage()))


rows = Rows()
netretry.log.addHandler(rows)
netretry.log.setLevel(logging.DEBUG)
netretry.log.propagate = False
notify._rng.seed(7)


def http_error(code):
    return urllib.error.HTTPError("https://x.invalid/k", code, "test", {}, None)


print("[什么算网络掐断、值得再试]")
for exc, want in ((TimeoutError("timed out"), True), (http.client.IncompleteRead(b"half"), True),
                  (http.client.RemoteDisconnected("closed"), True), (ConnectionResetError(54, "reset"), True),
                  (urllib.error.URLError("no dns"), True), (http_error(502), True), (http_error(503), True),
                  (http_error(504), True), (http_error(404), False), (http_error(403), False),
                  (http_error(500), False), (ValueError("odd"), False)):
    check(f"{type(exc).__name__} {getattr(exc, 'code', '')}".strip(), netretry.transient(exc), want)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run(answers, limit=8.0, cost=0.3):
    """call() over a scripted fn: each answer is raised or returned, costing `cost` seconds."""
    clock, seen = Clock(), []

    def fn(left):
        seen.append(round(left, 2))
        clock.t += cost
        got = answers.pop(0)
        if isinstance(got, BaseException):
            raise got
        return got
    rows.rows.clear()
    try:
        out = netretry.call(fn, "读测试页", limit, detail="https://x.invalid/k", clock=clock, sleep=clock.sleep)
    except Exception as exc:  # noqa: BLE001
        out = exc
    return out, seen, list(rows.rows)


print("\n[call：在原来的时限里再试]")
out, seen, logged = run([ConnectionResetError(54, "reset"), "ok"])
check("断了一次、第二次成了", out, "ok")
check("第一次用整个时限，第二次用剩下的", (seen[0], 0 < seen[1] < 8.0 - 0.3), (8.0, True))
check("一条 INFO、一条标自己好了的 WARNING", [(lv, r) for lv, r, _ in logged], [("INFO", False), ("WARNING", True)])
out, seen, logged = run([http_error(503), http_error(502), http_error(504)])
check("三次都是网关错：报最后一次", (getattr(out, "code", None), len(seen)), (504, notify._RETRIES))
check("……没有 WARNING（由调用方报）", [lv for lv, _, _ in logged], ["INFO", "INFO"])
out, seen, _ = run([http_error(404)])
check("404：不再试，原样报出", (getattr(out, "code", None), len(seen)), (404, 1))
out, seen, _ = run([TimeoutError("timed out"), "ok"], limit=8.0, cost=8.0)
check("超时把时限用完：不再试（服务停止的 30 秒里放得下）", (type(out).__name__, len(seen)), ("TimeoutError", 1))
out, seen, _ = run([ValueError("odd"), "ok"])
check("别的错：不再试", (type(out).__name__, len(seen)), ("ValueError", 1))


class Resp:
    def __init__(self, body=b"", status=200):
        self.body, self.status = body, status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def scripted(answers):
    calls = []

    def urlopen(req, timeout=None):
        calls.append(timeout)
        got = answers.pop(0)
        if isinstance(got, BaseException):
            raise got
        return got
    return urlopen, calls


REAL = urllib.request.urlopen
cos = SimpleNamespace(host="b.cos.example.invalid", authorization=lambda method, key: "sig")
real_sleep = netretry._sleep
netretry._sleep = lambda s: None
try:
    print("\n[腾讯云 COS：断一下再写一次；404 / 403 照旧]")
    urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
    check("写入：断了一次又写进去了", (cos_store.cos_put(cos, "state/k.json", b"{}", 8), len(calls)), (None, 2))
    urllib.request.urlopen, calls = scripted([http_error(403)])
    check("写入：403 不再试，说回 403", (cos_store.cos_put(cos, "state/k.json", b"{}", 8), len(calls)), ("回 403", 1))
    urllib.request.urlopen, calls = scripted([http_error(503), Resp(b"body")])
    check("读取：网关 503 后读到", (cos_store.cos_get(cos, "k", 8), len(calls)), ((b"body", ""), 2))
    urllib.request.urlopen, calls = scripted([http_error(404)])
    check("读取：404 就是没有这个对象，不再试", (cos_store.cos_get(cos, "k", 8), len(calls)), ((None, ""), 1))
    urllib.request.urlopen, calls = scripted([OSError("odd")])
    check("读取：别的错照旧不抛、说原因", (cos_store.cos_get(cos, "k", 8)[1], len(calls)), ("odd", 1))

    urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
    check("写入 retry=False：只写一次，说原因", (bool(cos_store.cos_put(cos, "state/k.json", b"{}", 8, retry=False)),
                                          len(calls)), (True, 1))

    print("\n[心跳：平时一跳只写一次（下一跳就是重试），关机那一跳在 8 秒里再写一次]")
    # dispatch relay-opt-round3b-1108: a 30 s beat retried in the call wrote one 自愈待查 red
    # item per healed beat on a flaky link; the bye has no next beat.
    from ark_relay.features.phone import phone
    from _tmp import tmpdir
    hb = phone.Heartbeat("ark-test-topic", tmpdir(), post=lambda p, t: None, cos=cos)
    urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
    check("平时那一跳：断了就算这一跳没写上，只写一次", (hb.cos_beat(), len(calls)), (False, 1))
    urllib.request.urlopen, calls = scripted([ConnectionResetError(54, "reset"), Resp(status=200)])
    check("关机那一跳：断了再写一次，写上了", (hb.cos_beat(bye=True), len(calls)), (True, 2))

    print("\n[终末地官方公告：网关 503 后在 8 秒里再读一次]")
    body = b'{"data": {"list": []}}'
    urllib.request.urlopen, calls = scripted([http_error(503), Resp(body)])
    check("读到了（今天没有版本更新）", (efstatus.update_hint(strict=True), len(calls)), ("", 2))
    check("第一次用 8 秒", calls[0], 8)
finally:
    urllib.request.urlopen = REAL
    netretry._sleep = real_sleep

print("\n[需求表建表：404 当场报，503 和断线照旧再问]")
real_bsleep = build.time.sleep
build.time.sleep = lambda s: None
try:
    n = []

    def nf():
        n.append(1)
        raise http_error(404)
    try:
        build._retry(nf)
        out = None
    except urllib.error.HTTPError as exc:
        out = exc.code
    check("404：问一次就报", (out, len(n)), (404, 1))
    seq = [http_error(503), ConnectionResetError(54, "reset"), "ok"]

    def flaky():
        got = seq.pop(0)
        if isinstance(got, BaseException):
            raise got
        return got
    check("503、断线之后第三次成了", build._retry(flaky), "ok")
finally:
    build.time.sleep = real_bsleep

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
