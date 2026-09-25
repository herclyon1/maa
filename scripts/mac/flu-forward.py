#!/usr/bin/env python3
"""Stand-in for the diag bucket's browser side, for the simulator proof of web/fluency-rec.js.

    scripts/mac/flu-forward.py <port> <save-dir> [--no-cos]

The bucket's CORS rule only admits https://herclyon1.github.io (seg-frames-logger.js header, 件 C), so a page served from
localhost cannot PUT to it. Point the page at this server instead (?flubucket=http://localhost:<port>, or the served copy's
default bucket rewritten): it answers the CORS preflight, keeps every PUT body in <save-dir>/<key>, and forwards the same
PUT anonymously to the real bucket (same key, x-cos-forbid-overwrite), answering with the bucket's status — so the record
also goes the whole way and flu-report.py (without --no-pull) finds it. --no-cos keeps it local only.
"""
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT, SAVE = int(sys.argv[1]), Path(sys.argv[2])
COS = None if "--no-cos" in sys.argv else "https://ark-diag-1315873325.cos.ap-shanghai.myqcloud.com"


class H(BaseHTTPRequestHandler):
    def cors(self):
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Access-Control-Allow-Methods", "PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Expose-Headers", "ETag")

    def do_OPTIONS(self):
        self.send_response(200)
        self.cors()
        self.end_headers()

    def do_PUT(self):
        key = self.path.lstrip("/").split("?")[0]
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if not key.startswith("diag/") or ".." in key:
            self.send_response(403); self.cors(); self.end_headers(); return
        dest = SAVE / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        code = 200
        if COS:
            req = urllib.request.Request(f"{COS}/{key}", data=body, method="PUT",
                                         headers={"Content-Type": "application/json", "x-cos-forbid-overwrite": "true"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            except OSError:
                code = 502
        print(f"PUT {key} {len(body)} B -> {code}", flush=True)
        self.send_response(code)
        self.cors()
        self.end_headers()


ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
