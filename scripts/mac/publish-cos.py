#!/usr/bin/env python3
"""Publish the relay's current manifest, its files as one bundle, and latest.json to the COS bucket.

    scripts/mac/publish-cos.py            # after make-manifest.py: PUT relay/<version>/{manifest.json,bundle.zip} and relay/latest.json
    scripts/mac/publish-cos.py --check    # GET latest.json and say which version the machine would see

The machine's self-update (relay/ark_relay/selfupdate.py) asks this bucket first:
latest.json (a hundred bytes), then relay/<version>/manifest.json, then the bundle -
every file in it verified against the manifest's SHA-1, so a wrong or half-written
object can only mean "COS has nothing", never wrong code. The four GitHub doors stay
as the fallback. Written 2026-09-18 after a manifest pushed at 02:31 was still the old
one on the machine's jsDelivr node at 08:45.

Credentials: COS_* in ~/.config/ark/push.env (the same bucket the evidence goes to).
The bucket's lifecycle rule deletes objects after 90 days; until that rule is limited
to the evidence prefix, a deleted relay/<version>/ simply makes the machine fall back
to GitHub - latest.json carries `uploaded` so the age is visible.
"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay"))
from ark_relay.evidence import Cos  # noqa: E402
from ark_relay.selfupdate import COS_BUNDLE, COS_LATEST, COS_PREFIX  # noqa: E402

RELAY = ROOT / "relay"


def _env() -> dict:
    p = Path.home() / ".config" / "ark" / "push.env"
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def _client() -> Cos:
    e = _env()
    missing = [k for k in ("COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET", "COS_REGION") if not e.get(k)]
    if missing:
        raise SystemExit(f"~/.config/ark/push.env 缺 {', '.join(missing)}")
    return Cos(e["COS_SECRET_ID"], e["COS_SECRET_KEY"], e["COS_BUCKET"], e["COS_REGION"], prefix=COS_PREFIX)


def _put(cos: Cos, key: str, data: bytes, ctype: str) -> None:
    full = f"{cos.prefix}/{key}"
    url = f"https://{cos.host}/" + urllib.parse.quote(full, safe="/")
    req = urllib.request.Request(url, data=data, method="PUT",
                                 headers={"Authorization": cos.authorization("PUT", full),
                                          "Content-Type": ctype, "Content-Length": str(len(data))})
    with urllib.request.urlopen(req, timeout=120) as r:
        r.read()


def _get(cos: Cos, key: str) -> bytes | None:
    full = f"{cos.prefix}/{key}"
    url = f"https://{cos.host}/" + urllib.parse.quote(full, safe="/")
    req = urllib.request.Request(url, headers={"Authorization": cos.authorization("GET", full)})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def main(argv: list[str]) -> int:
    cos = _client()
    if reason := cos.probe():
        print(f"✗ {reason}")
        return 1
    if "--check" in argv:
        data = _get(cos, COS_LATEST)
        print("COS latest.json:", data.decode() if data else "（没有）")
        return 0
    manifest = json.loads((RELAY / "manifest.json").read_text(encoding="utf-8"))
    ver = int(manifest["version"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(manifest["files"]):
            z.write(RELAY / rel, rel)
    bundle = buf.getvalue()
    t0 = time.time()
    # Order matters: the version directory first, latest.json last - a machine
    # that reads latest.json must find everything it points at already there.
    _put(cos, f"{ver}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"), "application/json")
    _put(cos, f"{ver}/{COS_BUNDLE}", bundle, "application/zip")
    latest = {"version": ver, "uploaded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "files": len(manifest["files"]), "bundle_bytes": len(bundle)}
    _put(cos, COS_LATEST, json.dumps(latest).encode("utf-8"), "application/json")
    back = _get(cos, COS_LATEST)
    ok = back is not None and json.loads(back).get("version") == ver
    print(f"{'✓' if ok else '✗'} COS：v{ver}，{len(manifest['files'])} 个文件，bundle {len(bundle) / 1024:.0f} KB，"
          f"{time.time() - t0:.1f} 秒{'，回读一致' if ok else '，回读不一致！'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
