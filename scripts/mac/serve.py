#!/usr/bin/env python3
"""Static server for the acceptance runs: `python3 scripts/mac/serve.py <dir> <port>`.
`python3 -m http.server` keeps socketserver's default listen backlog of 5; headless Chrome opens far more parallel connections for the
page (≈40 lens PNGs + a dozen scripts), so under load some connections are refused/reset and a script silently never runs (night 00:2x–00:5x:
"Motion is not defined", window.Sheet / NavEdge missing, accept-sheet.js never requested). This server listens with a backlog of 256 and
answers each request in its own thread."""
import sys, functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
class Server(ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True
    allow_reuse_address = True
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args): sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))
d, port = sys.argv[1], int(sys.argv[2])
Server(("127.0.0.1", port), functools.partial(Quiet, directory=d)).serve_forever()
