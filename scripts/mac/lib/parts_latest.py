"""Are the parts the relay ships with still the newest of their line? Prints, never blocks.

The installed relay carries its own Python (packaging/build.py PY_VERSION, the embeddable
zip from python.org/ftp) and two wheels (relay/requirements.txt: Pillow, pywin32). The four
programs it drives update themselves; these parts only change when we change them, and on
10-11 two of the three were a release behind with nobody aware (BOARD/DECISIONS.md D-1011, tools current:
Python 3.14.7 vs 3.14.8, pywin32 311 vs 312).

"Newest of its line" - a new line is a decision, not a lag:
  Python   same 3.N (3.14.x); the release must have the embed-amd64 zip build.py downloads
           (security-only releases ship source only, so a bare directory does not count)
  Pillow   same major (12.x.y)
  pywin32  any higher build (it has one number)
Final releases only (no a/b/rc/dev), not yanked, with a wheel for the bundled Python
(cpXY, win_amd64) - one without it could not be installed anyway.

deploy-relay.sh runs this first and ignores the exit code; it needs the network, so it is
not part of lint-repo.sh (a commit must work offline). Output is for us: not the group, not
the daily report.

    python3 scripts/mac/lib/parts_latest.py
Exit 0 = all current, 1 = something is behind, 2 = could not ask (and nothing seen behind).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FTP = "https://www.python.org/ftp/python/"
PYPI = "https://pypi.org/pypi/{}/json"
TIMEOUT = 5
# How many leading version numbers must match for a release to be "the same line".
SERIES = {"Pillow": 1, "pywin32": 0}
FINAL = re.compile(r"^\d+(?:\.\d+)*$")


def vkey(v: str) -> "tuple[int, ...]":
    return tuple(int(x) for x in v.split("."))


def pinned(root: Path = ROOT) -> "dict[str, str]":
    """{'Python': ..., 'Pillow': ..., 'pywin32': ...} as the repo pins them."""
    out = {}
    m = re.search(r'^PY_VERSION\s*=\s*"([\d.]+)"', (root / "packaging/build.py").read_text(
        encoding="utf-8"), re.MULTILINE)
    if m:
        out["Python"] = m.group(1)
    for line in (root / "relay/requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*==\s*([\w.]+)", line)
        if m and m.group(1) in SERIES:
            out[m.group(1)] = m.group(2)
    return out


def python_candidates(listing: str, current: str) -> "list[str]":
    """Same-line versions newer than `current` in the python.org/ftp listing, newest first."""
    line = current.split(".")[:2]
    found = {m.group(1) for m in re.finditer(r'href="(\d+\.\d+\.\d+)/"', listing)}
    newer = [v for v in found if v.split(".")[:2] == line and vkey(v) > vkey(current)]
    return sorted(newer, key=vkey, reverse=True)


def newest_pypi(data: dict, current: str, series: int, cp: str) -> str:
    """The newest final, unyanked release in `current`'s line with a cpXY win_amd64 wheel."""
    head = current.split(".")[:series]
    best = current
    for v, files in data.get("releases", {}).items():
        if not FINAL.match(v) or v.split(".")[:series] != head or vkey(v) <= vkey(best):
            continue
        if any(not f.get("yanked") and f.get("filename", "").endswith(".whl")
               and f"-{cp}-" in f["filename"] and "win_amd64" in f["filename"] for f in files):
            best = v
    return best


def _get(url: str, method: str = "GET") -> bytes:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "ark-parts-check"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read() if method == "GET" else b""


def _exists(url: str) -> bool:
    try:
        _get(url, "HEAD")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def latest_python(current: str) -> str:
    listing = _get(FTP).decode("utf-8", "replace")
    for v in python_candidates(listing, current):
        if _exists(f"{FTP}{v}/python-{v}-embed-amd64.zip"):
            return v
    return current


def latest_wheel(name: str, current: str, cp: str) -> str:
    return newest_pypi(json.loads(_get(PYPI.format(name))), current, SERIES[name], cp)


def report(pins: "dict[str, str]", latest: "dict[str, str | Exception]") -> int:
    behind = unreachable = False
    where = {"Python": "PY_VERSION in packaging/build.py",
             "Pillow": "relay/requirements.txt", "pywin32": "relay/requirements.txt"}
    for name, have in pins.items():
        got = latest.get(name)
        if isinstance(got, Exception) or got is None:
            unreachable = True
            print(f"  ? {name} {have}: could not ask ({got})")
        elif got != have:
            behind = True
            print(f"  ✗ {name} {have}: {got} is out - bump {where[name]}")
        else:
            print(f"  ✓ {name} {have}: newest of its line")
    return 1 if behind else 2 if unreachable else 0


def main() -> int:
    print("▶ relay parts against python.org / PyPI (newest patch of the same line)")
    pins = pinned()
    py = pins.get("Python", "3.14")
    cp = "cp" + "".join(py.split(".")[:2])
    jobs = {"Python": lambda: latest_python(py)}
    for name in SERIES:
        if name in pins:
            jobs[name] = (lambda n=name: latest_wheel(n, pins[n], cp))
    latest: dict = {}
    with ThreadPoolExecutor(len(jobs)) as ex:
        futures = {name: ex.submit(fn) for name, fn in jobs.items()}
        for name, fut in futures.items():
            try:
                latest[name] = fut.result()
            except (OSError, ValueError) as e:      # URLError and timeouts are OSError
                latest[name] = e
    return report(pins, latest)


if __name__ == "__main__":
    sys.exit(main())
