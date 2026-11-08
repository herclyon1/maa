"""A maintenance bulletin read has a deadline of its own, not only a per-socket-op time-out.

maintenance._get passed GET_TIMEOUT to urlopen, which bounds each socket operation:
a server that keeps sending a byte now and then is never "timed out". Measured from
the Mac on 2026-10-13 (140 timed reads of the seven bulletin URLs, median 0.57 s):
one read of the 26 KB media-cdn-mingchao.kurogame.com/.../article/5477.json took
164.8 s and succeeded. Every phone state push builds tomorrow's plan
(phone.state_payload -> plan.next_plan -> maintenance_lines -> today), so it sat
there too.

Pinned here, against a real HTTP server on 127.0.0.1 that dribbles its body:
  1. one try ends at GET_TIMEOUT whatever the server does; the try is then a
     failure exactly like a socket time-out today: one retry after GET_PAUSE, the
     same WARNING from today(), the same FAIL_TTL cache (the next today() asks
     nobody and logs the INFO);
  2. the worker thread of a cut-off try does not outlive it by more than a moment;
  3. a server that dribbles its headers is cut off at the same time;
  4. today()'s real reads together stop at TODAY_BUDGET: the games after that fail
     at once, each with the same WARNING;
  5. a normal answer is still read whole: a 200 KB body (the Wuthering Waves
     in-game notice is 155 KB) and a chunked one.
"""
import http.server
import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.maintenance import maintenance as M

fails: list[str] = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


class Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.recs: list[tuple[int, str]] = []

    def emit(self, record):
        self.recs.append((record.levelno, record.getMessage()))

    def at(self, level):
        return [m for lv, m in self.recs if lv == level]


logs = Logs()
M.log.addHandler(logs)
M.log.setLevel(logging.INFO)

BIG = "公告".encode() * 34134 + b"ab"      # 204806 bytes of UTF-8
hits: list[str] = []


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        hits.append(self.path)
        try:
            if self.path.startswith("/dribble"):
                # A byte every 0.2 s: each socket read gets data, the whole takes 6 s.
                self.send_response(200)
                self.send_header("Content-Length", "30")
                self.end_headers()
                for _ in range(30):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.2)
            elif self.path.startswith("/headers"):
                self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                for i in range(30):
                    self.wfile.write(f"X-Slow-{i}: 1\r\n".encode())
                    self.wfile.flush()
                    time.sleep(0.2)
                self.wfile.write(b"Content-Length: 2\r\n\r\nok")
            elif self.path.startswith("/big"):
                self.send_response(200)
                self.send_header("Content-Length", str(len(BIG)))
                self.end_headers()
                self.wfile.write(BIG)
            elif self.path.startswith("/chunked"):
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for part in ("维护", "公告", "x" * 70000):
                    data = part.encode()
                    self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
        except OSError:        # the client gave up: that is the point
            pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

slept: list[float] = []
M._sleep = slept.append
M.GET_TIMEOUT = 1
NOW = datetime(2026, 10, 14, 8, 46, tzinfo=SERVER_TZ)


def only(game, fn):
    """SOURCES with `fn` for `game` and no maintenance for the other two."""
    return {g: (fn if g == game else (lambda now: None)) for g in M.SOURCES}


def reset():
    M._CACHE.clear()
    logs.recs.clear()
    hits.clear()
    slept.clear()


def warned():
    return sorted(m.split("（")[0] for m in logs.at(logging.WARNING))


real_sources = M.SOURCES
try:
    print("[1. a dribbling body: each try ends at GET_TIMEOUT; then it is a time-out like any other]")
    reset()
    M.SOURCES = only("明日方舟", lambda now: (M._get(BASE + "/dribble"), None)[1])
    failed: list[str] = []
    t0 = time.monotonic()
    got = M.today(NOW, failed=failed)
    took = time.monotonic() - t0
    check(f"two tries of 1 s: took {took:.1f} s (< 4 s; the server takes 6 s a try)", took < 4)
    check("not read: no window, listed as failed", (got, failed), ({}, ["明日方舟"]))
    check("asked twice, a pause between", (len(hits), slept), (2, [M.GET_PAUSE]))
    check("the retry's INFO, as for a socket time-out",
          any(m.startswith("维护公告：" + BASE + "/dribble 没响应") for m in logs.at(logging.INFO)))
    check("today()'s WARNING, the site named", warned(), ["维护公告：明日方舟 官方公告取不到"])

    print("[2. its worker does not hang on]")
    left = ["?"]
    for _ in range(40):       # its body loop ends at the deadline; the server's next byte is 0.2 s away
        left = [t.name for t in threading.enumerate() if t.name.startswith("maintenance-get")]
        if not left:
            break
        time.sleep(0.05)
    check("no read thread left within 2 s", left, [])

    print("[1b. within FAIL_TTL the next today() asks nobody (the cache rules are unchanged)]")
    logs.recs.clear()
    n = len(hits)
    failed = []
    M.today(NOW, failed=failed)
    check("no new request", len(hits), n)
    check("failed again, said at INFO",
          (failed, any("刚才取不到" in m for m in logs.at(logging.INFO)), logs.at(logging.WARNING)),
          (["明日方舟"], True, []))

    print("[3. dribbled headers: cut off at the same time]")
    reset()
    M.GET_ATTEMPTS = 1
    M.SOURCES = only("终末地", lambda now: (M._get(BASE + "/headers"), None)[1])
    failed = []
    t0 = time.monotonic()
    M.today(NOW, failed=failed)
    took = time.monotonic() - t0
    check(f"one try of 1 s: took {took:.1f} s (< 3 s; the server takes 6 s)", took < 3)
    check("listed as failed with the WARNING", (failed, warned()), (["终末地"], ["维护公告：终末地 官方公告取不到"]))

    print("[4. today()'s real reads together stop at TODAY_BUDGET]")
    reset()
    M.TODAY_BUDGET = 2.5
    M.SOURCES = {g: (lambda now: (M._get(BASE + "/dribble"), M._get(BASE + "/dribble"), None)[2])
                 for g in M.SOURCES}
    failed = []
    t0 = time.monotonic()
    M.today(NOW, failed=failed)
    took = time.monotonic() - t0
    check(f"took {took:.1f} s (< 4.5 s; six 1 s reads without the budget)", took < 4.5)
    check("every game failed, each with today()'s WARNING", (sorted(failed), warned()),
          (sorted(M.SOURCES), sorted(f"维护公告：{g} 官方公告取不到" for g in M.SOURCES)))
    check(f"at most three requests made ({len(hits)})", len(hits) <= 3)

    print("[4b. the budget is per today() call: the next one starts afresh]")
    reset()
    M.SOURCES = only("鸣潮", lambda now: (M._get(BASE + "/big"), None)[1])
    failed = []
    M.today(NOW, failed=failed)
    check("read, nothing failed", (failed, len(hits)), ([], 1))

    print("[5. normal answers read whole]")
    M.GET_TIMEOUT = 20
    check("a 200 KB body, byte for byte", M._get(BASE + "/big") == BIG.decode("utf-8"))
    check("a chunked body", M._get(BASE + "/chunked"), "维护公告" + "x" * 70000)
finally:
    M.SOURCES = real_sources
    srv.shutdown()

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
