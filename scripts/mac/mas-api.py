#!/usr/bin/env python3
"""Talk to AUTO-MAS's backend directly, from here, over Tailscale.

The Electron window is a shell over a FastAPI backend. Driving that API instead
of the UI removes three problems at once: no screenshots to read, no
coordinates to guess, and no stop-edit-restart dance - the API writes through
the running backend, so there is no in-memory copy left to clobber the file.

Verified 2026-08-23: reachable at http://<host>:36163 over Tailscale, no
authentication, port unchanged across a reboot. It binds 0.0.0.0, so it is an
unauthenticated control plane for anything that can route to the machine;
that is acceptable on Tailscale and would not be on an untrusted network.

    scripts/mac/mas-api.py paths                 # every endpoint
    scripts/mac/mas-api.py get /api/info/get/overview
    scripts/mac/mas-api.py get /api/scripts/get

Three things that cost real time on 2026-08-26, written down so they do not
again:

* **Every endpoint is POST.** A GET returns `Method Not Allowed`, including on
  things that read (`/api/scripts/get`, `/api/queue/get`).
* **`ValueError: 配置已锁定, 无法修改`** means a task is running - the config is
  read-only for its duration. The fix is to `POST /api/dispatch/stop` and wait
  for AUTO-MAS to go idle, **not** to retry: that day it was retried eighteen
  times and failed every one. Verified afterwards that a write succeeds
  immediately once nothing is running.
* **`Config.json`'s `Data.Stage` is JSON inside a JSON string** - `json.loads`
  it twice or you get `TypeError: string indices must be integers`.
"""
import json
import os
import sys
import urllib.error
import urllib.request

HOST = os.environ.get("ARK_HOST", "100.65.39.119")
PORT = os.environ.get("ARK_MAS_PORT", "36163")
BASE = f"http://{HOST}:{PORT}"


def call(path, body=None, method="POST"):
    data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # FastAPI puts the reason a request was rejected in the body - which
        # field, what it expected. Raising instead of showing that turns a
        # one-line fix into guesswork; 422 is the normal way this API says
        # "your shape is wrong".
        body = e.read().decode("utf-8", "replace")
        try:
            return {"__status": e.code, "__detail": json.loads(body)}
        except json.JSONDecodeError:
            return {"__status": e.code, "__body": body[:1000]}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"__raw": raw[:2000]}


def spec():
    with urllib.request.urlopen(BASE + "/openapi.json", timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


SECRET_HINT = ("key", "cdk", "secret", "token", "password", "passwd", "sendkey",
               "webhook", "cookie", "authorization")


def redact(o):
    """Blank anything whose key looks like a credential.

    Printing a whole settings blob leaked a WeCom secret and a MirrorChyan CDK
    into a transcript on 2026-08-24. A dump helper that cannot be trusted with
    a config file is not a helper.
    """
    if isinstance(o, dict):
        return {k: ("<已隐去>" if any(h in k.lower() for h in SECRET_HINT) and o[k]
                    else redact(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [redact(v) for v in o]
    return o


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "paths":
        d = spec()
        comps = (d.get("components") or {}).get("schemas") or {}
        for p in sorted(d.get("paths") or {}):
            for m, op in d["paths"][p].items():
                if m not in ("get", "post"):
                    continue
                rb = ((op.get("requestBody") or {}).get("content", {})
                      .get("application/json", {}).get("schema", {}))
                need = ""
                if "$ref" in rb:
                    sch = comps.get(rb["$ref"].split("/")[-1], {})
                    if sch.get("required"):
                        need = "  需要: " + ",".join(sch["required"])
                print(f"{m.upper():5} {p:52} {op.get('summary','')}{need}")
        return 0
    if cmd in ("get", "post"):
        path = argv[1]
        body = json.loads(argv[2]) if len(argv) > 2 else {}
        raw = call(path, body, "POST")
        show = raw if "--raw" in argv else redact(raw)
        print(json.dumps(show, ensure_ascii=False, indent=1))
        return 0
    print(f"未知命令: {cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
