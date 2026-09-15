#!/usr/bin/env python3
"""Acceptance run of the phone page on the iOS simulator (docs/HIG-CHECKLIST.md).

Opens https://herclyon1.github.io/maa/?accept=1&quiet=1 in the simulator's Safari
(web/accept.js measures the DOM against the checklist numbers and stores the
result in localStorage), then reads that result straight out of Safari's
localStorage database in the device's data directory - no server, nothing
leaves the Mac. Runs light and dark (`simctl ui … appearance`). Exit 1 when any
item is off. Method after ~/Money/transit/pipeline/ui/accept.py (the other
session, 2026-09-15); the transport differs because this page is on GitHub
Pages and cannot POST to localhost.

  scripts/mac/phone-accept.py [--udid UDID] [--url URL] [--light-only]
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

SIMCTL = "/Applications/Xcode.app/Contents/Developer/usr/bin/simctl"
UDID = "8E793B8A-922B-46BC-86E2-E0F2BE845CA5"   # iPhone 18 Pro Max, iOS 27.0, Simplified Chinese
PAGE = "https://herclyon1.github.io/maa/"
ORIGIN = "herclyon1.github.io"


def sim(*args: str, check: bool = True) -> str:
    r = subprocess.run([SIMCTL, *args], capture_output=True, text=True, timeout=180)
    if check and r.returncode:
        raise SystemExit(f"simctl {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def safari_localstorage(udid: str) -> Path:
    """Safari's LocalStorage db for the page's origin (WebKit salts the directory name per device)."""
    base = Path.home() / "Library/Developer/CoreSimulator/Devices" / udid / "data/Containers/Data/Application"
    for origin in base.glob("*/Library/WebKit/com.apple.mobilesafari/WebsiteData/Default/*/*/origin"):
        if ORIGIN in origin.read_bytes().decode("utf-8", "ignore"):
            db = origin.parent / "LocalStorage/localstorage.sqlite3"
            if db.exists():
                return db
    raise SystemExit("Safari has no localStorage for the page yet - open it once in the simulator's Safari")


def read_result(db: Path) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    row = con.execute("select value from ItemTable where key='ark-accept'").fetchone()
    con.close()
    if not row:
        raise SystemExit("no ark-accept in localStorage - did accept.js load? (index.html loads it only with ?accept)")
    v = row[0]
    return json.loads(v.decode("utf-16-le") if isinstance(v, bytes) else v)


def run_once(udid: str, url: str, label: str, wait: float) -> int:
    stamp = int(time.time())
    sim("openurl", udid, f"{url}?accept=1&quiet=1&r={stamp}")
    time.sleep(wait)
    db = safari_localstorage(udid)
    out = None
    for _ in range(10):
        out = read_result(db)
        if abs(time.time() - time.mktime(time.strptime(out["at"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone) < 600 and f"r={stamp}" in out.get("href", ""):
            break
        time.sleep(1)
    if not out or f"r={stamp}" not in out.get("href", ""):
        raise SystemExit(f"{label}: the stored result is from an older run ({(out or {}).get('href')})")
    print(f"[{label}] {out['viewport']} {'standalone' if out['standalone'] else 'Safari'}{' dark' if out['dark'] else ''}: "
          f"{out['total'] - out['fails']}/{out['total']} pass")
    for r in out["rows"]:
        print(f"  {'✓' if r['ok'] else '✗'} {r['item']}: {r['got']}" + ("" if r["ok"] else f"  (expected {r['expect']})"))
    return out["fails"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--udid", default=UDID)
    ap.add_argument("--url", default=PAGE)
    ap.add_argument("--light-only", action="store_true")
    ap.add_argument("--wait", type=float, default=12, help="seconds for the page to load and measure")
    a = ap.parse_args()
    booted = sim("list", "devices", "booted", check=False)
    if a.udid not in booted:
        sim("boot", a.udid); sim("bootstatus", a.udid, "-b"); time.sleep(3)
    fails = 0
    sim("ui", a.udid, "appearance", "light")
    fails += run_once(a.udid, a.url, "light", a.wait)
    if not a.light_only:
        sim("ui", a.udid, "appearance", "dark")
        try:
            fails += run_once(a.udid, a.url, "dark", a.wait)
        finally:
            sim("ui", a.udid, "appearance", "light")
    print("ALL PASS" if not fails else f"{fails} item(s) off - docs/HIG-CHECKLIST.md is the reference; fix the CSS or, with a new measurement, the table first")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
