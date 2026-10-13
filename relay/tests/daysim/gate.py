#!/usr/bin/env python3
"""daysim day gate: deploy-relay.sh step 0.8 (design.md section 5), runnable alone.

    ~/.local/bin/python3.14 -I relay/tests/daysim/gate.py [--jobs 3] [--code relay/]

1. `run.py --all` replays every recorded day through the relay code under test and
   judges it; any new red (a failure line known-red.json does not list) or a stale /
   expired known-red entry fails the gate.
2. Self-check: each badfix/*.patch puts a fixed bug back into a throwaway copy of the
   code; its `Day:` must then fail with new red lines matching every `Expect:` regex.
   A gate that stays green with a known bug put back is broken (deploy-relay.sh's rule
   for every gate: feed it a known bad sample).

Exit 0 only when both hold. Outputs go to a temp folder that is removed on a pass and
kept (path printed) on a failure; the sim trees inside are removed either way (run.py).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))         # -I leaves the script's folder off the path
RELAY = HERE.parents[1]
BADFIX = HERE / "badfix"
PY = sys.executable
# Free space a full gate needs: one run of the three days took the Mac's free space from
# 2.1 to 1.6 GiB at its peak (measured 2026-10-13 19:27, df during run.py --all --jobs 3);
# the R36 day after it adds less. A run that hits ENOSPC dies with misleading failures
# (the 2026-10-13 18:5x gate run did), so refuse up front instead.
MIN_FREE_GIB = 1.0


def run(argv: list[str], log: Path) -> tuple[int, str]:
    """A run.py process; its output is echoed and returned."""
    t = time.perf_counter()
    p = subprocess.run([PY, "-I", "-X", "utf8", str(HERE / "run.py"), *argv], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", check=False)
    out = p.stdout + p.stderr
    log.write_text(out, encoding="utf-8")
    print(f"  ({time.perf_counter() - t:.0f} s wall)")
    return p.returncode, out


def patch_spec(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    days = re.findall(r"^Day: (\S+)$", text, re.M)
    expects = re.findall(r"^Expect: (.+)$", text, re.M)
    if len(days) != 1 or not expects:
        raise SystemExit(f"{path.name}: needs exactly one 'Day:' line and at least one 'Expect:' line")
    return days[0], expects


def code_copy(code: Path, dst: Path) -> Path:
    """The relay code as run.py's install_code takes it (tests, state and caches left out)."""
    shutil.copytree(code, dst / "relay", ignore=shutil.ignore_patterns(
        "tests", "state", ".env", "__pycache__", "*.pyc", "relay.log"))
    return dst / "relay"


def self_check(patch: Path, code: Path, work: Path, jobs: int) -> list[str]:
    """Problems (empty = the gate caught the bug the patch puts back)."""
    day, expects = patch_spec(patch)
    tmp = work / f"badfix-{patch.stem}"
    tmp.mkdir(parents=True)
    bad = code_copy(code, tmp)
    ap = subprocess.run(["git", "apply", str(patch)], cwd=tmp, capture_output=True, text=True,
                        check=False)
    if ap.returncode != 0:
        return [f"{patch.name} no longer applies to this code (refresh it against the fix): "
                f"{(ap.stderr or ap.stdout).strip()[:300]}"]
    print(f"▶ self-check {patch.name}: {day} with the bug put back must go red")
    rc, out = run(["--day", day, "--code", str(bad), "--out", str(tmp / "out"), "--jobs", str(jobs)],
                  work / f"badfix-{patch.stem}.log")
    new = [ln.split("NEW RED: ", 1)[1] for ln in out.splitlines() if "NEW RED: " in ln]
    for ln in new:
        print(f"    caught: {ln}")
    problems = []
    if rc != 1:
        problems.append(f"{patch.name}: run.py exit {rc}, wanted 1 (red); output tail:\n{out[-1500:]}")
    for x in expects:
        if not any(re.search(x, ln) for ln in new):
            problems.append(f"{patch.name}: no new red line matches {x!r} - the gate no longer sees this bug")
    shutil.rmtree(bad, ignore_errors=True)
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--code", default=str(RELAY), help="the relay code under test (default: this repo's relay/)")
    ap.add_argument("--skip-self-check", action="store_true", help="bring-up only; the deploy never passes it")
    ap.add_argument("--available", action="store_true",
                    help="only the days whose corpus is there (CI: the light packs, pack.py unpack); "
                         "the deploy runs every day")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)   # deploy-relay.sh pipes it through sed
    free = shutil.disk_usage(tempfile.gettempdir()).free / 2**30
    if free < MIN_FREE_GIB:
        print(f"✋ day gate: only {free:.1f} GiB free on the disk (needs {MIN_FREE_GIB}); free space first")
        return 3
    t0 = time.perf_counter()
    work = Path(tempfile.mkdtemp(prefix="daysim-gate-"))
    which = ["--all"]
    if a.available:
        import install  # noqa: PLC0415
        have = sorted(p.parent.name for p in (HERE / "days").glob("*/events.jsonl")
                      if (install.CORPUS_ROOT / p.parent.name).is_dir())
        print(f"▶ days with a corpus under {install.CORPUS_ROOT}: {', '.join(have) or 'none'}")
        if not have:
            print("✋ day gate: no day to replay")
            return 2
        which = [x for d in have for x in ("--day", d)]
    print(f"▶ day replay: run.py {' '.join(which)}")
    rc, out = run([*which, "--jobs", str(a.jobs), "--code", str(a.code), "--out", str(work / "days")],
                  work / "days.log")
    problems = []
    for ln in out.splitlines():
        if not ln.startswith("  ok   "):         # each passing entry, one line apiece
            print(ln)
    if rc != 0:
        problems.append(f"run.py --all exit {rc} (new red, stale known-red, or a refused list; see above)")
    if not a.skip_self_check:
        patches = sorted(BADFIX.glob("*.patch"))
        if not patches:
            problems.append("no badfix/*.patch: the gate has no self-check")
        for p in patches:
            problems += self_check(p, Path(a.code), work, a.jobs)
    took = time.perf_counter() - t0
    if problems:
        print(f"✋ day gate FAILED after {took:.0f} s:")
        for x in problems:
            print(f"  - {x}")
        print(f"  outputs kept in {work}")
        return 1
    shutil.rmtree(work, ignore_errors=True)
    print(f"✅ day gate passed in {took:.0f} s: no new red, every known-red entry still matches, "
          "and each bad patch turned its day red")
    return 0


if __name__ == "__main__":
    sys.exit(main())
