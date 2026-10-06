"""Mailbox.close() cuts the held stream at once, on macOS and on Windows.

The service stop (SvcStop) calls Mailbox.close() while the listener thread is
blocked reading the ntfy stream. Until 2026-10-07 close() returned only with
the next line the server sent - a keepalive, 45 s apart on ntfy.sh - because
r.close() waits for the read the listener holds; the fix shuts the socket down
first (see Mailbox.close). test_phone_mailbox_e2e.py checks this against a
real ntfy; this file checks the same thing with nothing but the standard
library, so it runs wherever Python runs (the Windows CI job included, the
machine the relay really lives on being Windows).

The server below holds a GET open and writes one ntfy-shaped keepalive line
every KEEPALIVE seconds. KEEPALIVE is well over the 1 s limit, so a close()
that waits for the next line cannot pass by luck.

Basis: "If you want to close the connection in a timely fashion, call
shutdown() before close()." (https://docs.python.org/3/library/socket.html#socket.socket.close)
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay import phone  # noqa: E402

KEEPALIVE = 5.0          # seconds between keepalive lines (ntfy.sh: 45 s)
LIMIT = 1.0              # close() and the listener's exit must each take less
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


stopping = threading.Event()
held = threading.Event()           # the server has sent the headers and the open line


class Stream(BaseHTTPRequestHandler):
    """GET /<topic>/json?...: what ntfy sends a subscriber - an open line, then a
    keepalive every KEEPALIVE seconds - until the client goes away."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.end_headers()
        try:
            self._line("open")
            held.set()
            while not stopping.wait(KEEPALIVE):
                self._line("keepalive")
        except OSError:          # the client shut the socket down: done
            return

    def _line(self, event):
        body = {"id": f"k{time.time_ns()}", "time": int(time.time()), "event": event,
                "topic": self.path.split("/")[1]}
        self.wfile.write((json.dumps(body) + "\n").encode("utf-8"))
        self.wfile.flush()

    def log_message(self, *a):   # no per-request lines on stderr
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), Stream)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
phone.NTFY = f"http://127.0.0.1:{srv.server_address[1]}"

t0 = time.time()
try:
    print(f"[a local stream server on {phone.NTFY}, keepalive every {KEEPALIVE:.0f} s]")
    box = phone.Mailbox("close-test", "8964", tmpdir())
    stop = threading.Event()
    listener = threading.Thread(target=box.listen, args=(lambda body: None, stop.is_set),
                                daemon=True)
    listener.start()
    check("the server holds the stream", held.wait(5), True)
    until = time.time() + 5
    while not box.connected and time.time() < until:
        time.sleep(0.01)
    check("the mailbox says it is connected", box.connected, True)
    time.sleep(0.3)              # the listener is now blocked reading the next line

    # SvcStop: the stop flag first, then close().
    stop.set()
    t = time.time()
    box.close()
    took = time.time() - t
    check(f"Mailbox.close() returned in under {LIMIT:.0f} s (keepalive every {KEEPALIVE:.0f} s)",
          took < LIMIT or round(took, 2), True)
    listener.join(LIMIT)
    check(f"the listener thread ended within {LIMIT:.0f} s after it", listener.is_alive(), False)
except Exception as exc:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    fails.append(type(exc).__name__)
finally:
    stopping.set()
    srv.shutdown()
    srv.server_close()
    print(f"  ({time.time() - t0:.1f} s)")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
