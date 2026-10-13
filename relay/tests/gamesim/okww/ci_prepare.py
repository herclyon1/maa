#!/usr/bin/env python3
"""Lay out a real OK-WW the way the game PC has it, install our overlay with the relay's own
installer, and run the gamesim OK-WW tests through upstream's own test runner (Windows job).

The game PC runs D:/ark/okww/data/apps/ok-ww/working/main.py on Python 3.12.10 with
ok-script 2.0.8 (scratchpad gamesim/u0/versions.json; every one of the 256 ok/ files and
92 src/ files the PC has hashes equal to the ok-script 2.0.8 wheel and the OK-WW v3.7.4
tag, okww-working-source-hashes.tsv, compared 2026-10-13). ok-script executes every .py in
<working>/ok_tasks/ while it starts (ok/core/task_manager.py load_user_tasks), and that is
where okww_overlay.install() puts ark_overrides.py. Nothing here imitates either side:

  prepare  fetches OK-WW at the commit relay/tests/gamesim/upstream/okww-<tag>/SOURCE.txt
           pins, checks every file that copy holds is byte-equal, lays it out as
           <root>/data/apps/ok-ww/working, and calls okww_overlay.install(<root>) - the
           relay's installer, on the relay's Python - with the overlay of the lane.
  run      runs each lane test with OK-WW's Python through OK-WW's own run_test.py
           (what its run_tests.ps1 and test.yml do), then reads the report back with
           okww_overlay.report_line(), the code that wrote the machine's relay.log lines.

A lane is an OK-WW tag plus an overlay revision plus the outcome it must have. `installed`
is the gate: the tag the PC runs and the overlay in this checkout. The p1-* lanes are the
red-before-green proof of test_overlay_loads.py on the one load failure the machine
recorded (relay.log 2026-10-04 21:20:19, below).

    ci_prepare.py lanes
    ci_prepare.py prepare --lane installed --root DIR
    ci_prepare.py run --lane installed --root DIR --python OKWW_PYTHON --out RESULTS [--summary FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
RELAY = REPO / "relay"
TESTS = RELAY / "tests"
sys.path.insert(0, str(RELAY))
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS / "gamesim" / "tools"))
import fetch_upstream as fu  # noqa: E402
from ark_relay.features.okww_patch import okww_overlay  # noqa: E402

_argv, sys.argv = sys.argv, sys.argv[:1]     # the contract test reads sys.argv[1] at import
try:
    import test_gl_okww_contract as contract
finally:
    sys.argv = _argv

OVERLAY_NAME = "okww_files/ark_overrides.tasks.py"
CONTEXT = "ark_gamesim.json"      # read by the tests, next to OK-WW's main.py
TEST_PREFIX = "gamesim_"          # the copies in OK-WW's tests/ folder
# OK-WW's own CI gives its whole test step 20 minutes (ok-wuthering-waves v3.7.4
# .github/workflows/test.yml, "Run tests" timeout-minutes: 20); one file gets half that.
TEST_TIMEOUT_S = 600

# The relay's report line for the one load failure the machine recorded. relay.log on the
# game PC, 2026-10-04 21:20:19 (scratchpad machine-relay/relay.log line 27223), the boot
# after OK-WW v3.7.3 started at 09:20:26 that day (OK-WW app log app.2026-10-04,
# "ok-script init v3.7.3") with the overlay as it was before f6b5f432:
MACHINE_2026_10_04 = ("OK-WW 有改动没贴上（上游源码和登记的不一致）：NightmareNestTask.find_nest"
                      "（上游正文变了（现在 12d040afa102，我们照着 3b0271924cac 抄的））")

LANES = {
    # The gate: the OK-WW the PC runs (contract.INSTALLED) and this checkout's overlay.
    # Every test under relay/tests/gamesim/okww/ runs; all must pass.
    "installed": {"tag": contract.INSTALLED, "overlay": None, "tests": "test_*.py",
                  "expect": "green"},
    # P1 red: the overlay before f6b5f432 on v3.7.3, the pair the machine ran on 10-04/05.
    # It must fail at an assertion, and the relay must say exactly what it said then.
    "p1-red-f6b5f432": {"tag": "v3.7.3", "overlay": "f6b5f432~1", "tests": "test_overlay_loads.py",
                        "expect": "red", "relay_line": MACHINE_2026_10_04},
    # P1 green: the fix (find_nest pinned to v3.7.3's body 12d040afa102) on the same OK-WW.
    "p1-green-f6b5f432": {"tag": "v3.7.3", "overlay": "f6b5f432", "tests": "test_overlay_loads.py",
                          "expect": "green"},
    # P2 red: the same pair, on the 2026-10-07 nest list with the 落渊南丘 order. find_nest is
    # skipped (the report the relay read on 10-04), so upstream's picks the first 0 (0/48) and
    # the click misses the 落渊南丘 row: the case must fail at an assertion.
    "p2-red-f6b5f432": {"tag": "v3.7.3", "overlay": "f6b5f432~1", "tests": "test_p2_find_nest.py",
                        "expect": "red", "relay_line": MACHINE_2026_10_04},
    # P2 green: f6b5f432's find_nest on the same OK-WW chooses and clicks 落渊南丘 0/41.
    "p2-green-f6b5f432": {"tag": "v3.7.3", "overlay": "f6b5f432", "tests": "test_p2_find_nest.py",
                          "expect": "green"},
}

# U5, the weekly boss (test_weekly.py): each case with a fix commit, red at <fix>~1 and green at the
# fix, on the OK-WW the machine ran when it broke (U4 frames.json: 10-04/05 v3.7.3, from 10-06
# v3.7.4). `select` runs only that fix's cases. The relay line is not checked (None): these
# overlays never ran on these OK-WW builds together, so there is no machine line to match;
# summary.json records what it was.
_WEEKLY_PAIRS = {
    # T3: a claim made on upstream's own pickup is read back and the way back in taken.
    "82a238ae": ("v3.7.4", ["test_main_path_1012"]),
    # T2: waveplates + backup under 60 -> 取消 before 确认 (10-12 11:44 17+24; 15:29 18+0 paid with solute).
    "b07f1086": ("v3.7.4", ["test_claim_short_17_24", "test_claim_short_18_0"]),
    # T2: 「240/240+」 reads as 240; an unread bar is never confirmed.
    "afd0ffa6": ("v3.7.4", ["test_claim_bar_240_plus", "test_claim_bar_unread"]),
    # T2: a top-up dialog after an enough read (it defaults to 结晶溶剂) is closed, not paid.
    "efc7fb6b": ("v3.7.4", ["test_claim_topup_after_enough_read"]),
    # T2: no 挑战成功 after 确认 stops with a picture instead of handing the screen back.
    "022adf68": ("v3.7.4", ["test_claim_no_settlement"]),
    # T2: no crystal after the fight (10-12 09:52:20) stops with a picture.
    "9ca36da5": ("v3.7.4", ["test_no_crystal_0952"]),
    # T4: 确认前往 opens the level page (10-05 22:05) -> upstream's team path.
    "f087e2b6": ("v3.7.3", ["test_entry_spoiler_level_page"]),
    # T4: 确认前往 and then the open world -> picture and stop, no walk.
    "f786bec1": ("v3.7.3", ["test_entry_open_world_stops"]),
    # T4 (P3): the 「无法获取奖励」 reminder with too few waveplates -> 取消, never upstream's 确认 + tick.
    "a0db4b38": ("v3.7.4", ["test_solo_reminder_short"]),
    # T4: the reminder with a bar that reads enough -> 取消 and a picture, never 确认.
    "892f9973": ("v3.7.4", ["test_solo_reminder_contradicts"]),
    # T4: 单人挑战 not taken (09-21, frame no_start_btn) -> clicked again. The machine had v3.6.7,
    # whose ok-script 2.0.4 the harness does not run; v3.7.4 has the same click_team_challenge
    # body (the overlay pins daeaf5a0f809 at both commits).
    "a549c57e": ("v3.7.4", ["test_solo_click_not_taken_0921"]),
    # T4: the Boss Challenge team page (10-13 11:55:58): the level cannot be picked there, said once.
    "35d6166b": ("v3.7.4", ["test_boss_challenge_team_page"]),
}
for _fix, (_tag, _cases) in _WEEKLY_PAIRS.items():
    for _expect, _rev in (("red", f"{_fix}~1"), ("green", _fix)):
        LANES[f"weekly-{_expect}-{_fix}"] = {"tag": _tag, "overlay": _rev, "tests": "test_weekly.py",
                                             "select": _cases, "expect": _expect, "relay_line": None}


_NO_LINE = object()


def sh(*cmd, cwd=None) -> str:
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], cwd=cwd, check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def working(root: Path) -> Path:
    """Where okww_overlay.target() expects OK-WW's working directory under `root`."""
    return okww_overlay.target(root).parent.parent


def overlay_source(rev: "str | None", scratch: Path) -> "tuple[Path, str]":
    """(file holding the overlay of `rev`, label). None = this checkout's file.

    The file moved with 2c3290c8 (relay/ark_relay/okww_files -> features/okww_patch), so the
    path is looked up in the revision's own tree."""
    if rev is None:
        return okww_overlay._SOURCE, "this checkout"
    names = sh("git", "-C", REPO, "ls-tree", "-r", "--name-only", rev).splitlines()
    hits = [n for n in names if n.startswith("relay/") and n.endswith(OVERLAY_NAME)]
    if len(hits) != 1:
        raise SystemExit(f"{rev}: expected one {OVERLAY_NAME} in relay/, found {hits}")
    data = subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{hits[0]}"],
                          check=True, capture_output=True).stdout
    out = scratch / f"ark_overrides@{rev.replace('~', '_')}.py"
    out.write_bytes(data)
    return out, f"{rev}:{hits[0]}"


def prepare(lane: str, root: Path) -> None:
    spec = LANES[lane]
    copy = fu.copy_dir("okww", spec["tag"])
    pin = fu.read_manifest(copy)
    work = working(root)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    # The PC gets OK-WW's LF bytes; the hashes in SOURCE.txt are of those (same as relay-windows.yml).
    sh("git", "init", "-q", work)
    sh("git", "-C", work, "-c", "core.autocrlf=false", "fetch", "-q", "--depth", "1",
       pin["repo"], pin["commit"])
    sh("git", "-C", work, "-c", "core.autocrlf=false", "checkout", "-q", "FETCH_HEAD")
    head = sh("git", "-C", work, "rev-parse", "HEAD").strip()
    if head != pin["commit"]:
        raise SystemExit(f"fetched {head}, {copy.name}/SOURCE.txt pins {pin['commit']}")
    bad = [p for p, want in pin["files"].items()
           if not (work / p).is_file() or sha256((work / p).read_bytes()) != want]
    if bad:
        raise SystemExit(f"OK-WW {spec['tag']} at {head[:12]} differs from {copy.name}: {bad}")
    print(f"OK-WW {spec['tag']} at {head[:12]}: the {len(pin['files'])} files of {copy.name} are byte-equal")

    src, label = overlay_source(spec["overlay"], root)
    text = src.read_text(encoding="utf-8")
    okww_overlay._SOURCE = src            # install() copies source_text(); point it at the lane's
    line = okww_overlay.install(root)
    dest = okww_overlay.target(root)
    if not dest.is_file() or dest.read_bytes() != src.read_bytes():
        raise SystemExit(f"okww_overlay.install({root}) did not leave the overlay in place: {line!r}")
    print(f"overlay {label} ({sha256(src.read_bytes())[:12]}) installed: {line}")

    # Both sides must mean the same file: the overlay writes its REPORT, the relay reads its own.
    if f'REPORT = r"{okww_overlay.REPORT}"' not in text:
        raise SystemExit(f"the overlay does not write {okww_overlay.REPORT}, which the relay reads")
    expected = [f"{c}.{n}" for c, n, _ in contract.rebinds(text)]
    if contract.stray_overrides(text):
        raise SystemExit(f"override(...) calls the static reader cannot place: {contract.stray_overrides(text)}")

    tests = sorted(HERE.glob(spec["tests"]))
    if not tests:
        raise SystemExit(f"no {spec['tests']} in {HERE}")
    for t in tests:
        shutil.copyfile(t, work / "tests" / f"{TEST_PREFIX}{t.name}")
    ctx = {"lane": lane, "okww_tag": spec["tag"], "okww_commit": head, "overlay": label,
           "overlay_sha256": sha256(src.read_bytes()), "report": str(okww_overlay.REPORT),
           "expected_applied": expected, "tests": [t.name for t in tests],
           # The harness (harness.py, scenario.py, scenarios/) and the frame library stay in
           # this checkout; the copied tests import them from here.
           "gamesim_okww": str(HERE)}
    (work / CONTEXT).write_text(json.dumps(ctx, ensure_ascii=False, indent=1), encoding="utf-8")
    # pip input: OK-WW's pinned requirements from the fetched copy, plus the one range it
    # leaves open, at what the PC has (versions.json: onnxocr-ppocrv5 ">=0.0.20 (installed 0.0.20)").
    shutil.copyfile(copy / ("requirements.txt" + fu.SUFFIX), root / "pip-requirements.txt")
    (root / "pip-constraints.txt").write_text("onnxocr-ppocrv5==0.0.20\n", encoding="utf-8")
    print(f"{len(tests)} test file(s) copied; static read of the overlay: {len(expected)} rebinds")


def _unittest_verdict(out: str, code: int) -> "tuple[str, list[str]]":
    """('pass' | 'fail' | 'error', the FAIL:/ERROR: lines) from unittest's verbose output."""
    lines = [ln for ln in out.splitlines() if ln.startswith(("FAIL: ", "ERROR: "))]
    if any(ln.startswith("ERROR: ") for ln in lines) or (code != 0 and not lines):
        return "error", lines
    return ("fail" if code != 0 else "pass"), lines


def run(lane: str, root: Path, python: str, out_dir: Path, step_summary: "str | None" = None) -> int:
    spec = LANES[lane]
    work = working(root)
    ctx = json.loads((work / CONTEXT).read_text(encoding="utf-8"))
    out_dir = out_dir / lane
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for name in ctx["tests"]:
        if okww_overlay.REPORT.exists():
            okww_overlay.REPORT.unlink()     # a report left from before must not pass for this one
        t0 = time.monotonic()
        # `select`: unittest's own -k patterns, so a red lane runs only the cases its fix is about.
        picks = [arg for k in spec.get("select", []) for arg in ("-k", k)]
        p = subprocess.run([python, "-u", "run_test.py", *picks, f"tests/{TEST_PREFIX}{name}"], cwd=work,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=TEST_TIMEOUT_S)
        took = round(time.monotonic() - t0, 1)
        text = p.stdout + p.stderr
        (out_dir / f"{name}.log").write_text(text, encoding="utf-8")
        print(f"\n===== {name} (exit {p.returncode}, {took} s) =====\n{text}", flush=True)
        verdict, lines = _unittest_verdict(text, p.returncode)
        report = okww_overlay.last_report()
        if okww_overlay.REPORT.exists():
            shutil.copyfile(okww_overlay.REPORT, out_dir / f"{name}.report.json")
        relay_line = okww_overlay.report_line()
        results.append({"test": name, "exit": p.returncode, "seconds": took, "verdict": verdict,
                        "unittest": lines, "report": report, "relay_line": relay_line})
    if (work / "logs").is_dir():
        shutil.copytree(work / "logs", out_dir / "okww-logs", dirs_exist_ok=True)

    problems = []
    # relay_line: the line the relay must print for this overlay on this OK-WW. Green lanes
    # default to none; a lane that sets it to None leaves it unchecked (an old overlay on an
    # OK-WW the machine never ran it with has no recorded line to match) - it is reported.
    want_line = spec.get("relay_line", "" if spec["expect"] == "green" else _NO_LINE)
    for r in results:
        if spec["expect"] == "green":
            if r["verdict"] != "pass":
                problems.append(f"{r['test']}: {r['verdict']} {r['unittest']}")
        else:
            if r["verdict"] != "fail":
                problems.append(f"{r['test']}: must fail at an assertion, got {r['verdict']} {r['unittest']}")
        if want_line is _NO_LINE:
            problems.append(f"{lane}: a red lane needs `relay_line` (the machine's, or None)")
        elif want_line is not None and (r["relay_line"] or "") != want_line:
            problems.append(f"{r['test']}: relay line {r['relay_line']!r} != {want_line!r}")
        # Every selected case must have run and come out the lane's way, not just one of them.
        for k in spec.get("select", []):
            log = (out_dir / f"{r['test']}.log").read_text(encoding="utf-8")
            # unittest -v starts each case's line with its name; with no FAIL/ERROR it passed.
            if spec["expect"] == "green" and not re.search(rf"^{re.escape(k)} \(", log, re.M):
                problems.append(f"{r['test']}: selected case {k} did not run")
            if spec["expect"] == "red" and not any(k in ln for ln in r["unittest"] if ln.startswith("FAIL: ")):
                problems.append(f"{r['test']}: selected case {k} did not fail at an assertion")
    summary = {"lane": lane, "expect": spec["expect"], "okww_tag": ctx["okww_tag"],
               "okww_commit": ctx["okww_commit"], "overlay": ctx["overlay"],
               "results": results, "problems": problems}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    head = (f"lane {lane} (OK-WW {ctx['okww_tag']}, overlay {ctx['overlay']}, expect {spec['expect']}): "
            + ", ".join(f"{r['test']} {r['verdict']} in {r['seconds']} s" for r in results))
    tail = "all checks passed" if not problems else f"{len(problems)} problem(s)"
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(f"- {head}: **{tail}**\n" + "".join(f"  - {p}\n" for p in problems))
    print("\n" + head)
    for r in results:
        print(f"  relay line after {r['test']}: {r['relay_line'] or '(none)'}")
    for pr in problems:
        print(f"  ✗ {pr}")
    print(tail)
    return 1 if problems else 0


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=("lanes", "prepare", "run"))
    ap.add_argument("--lane", choices=sorted(LANES))
    ap.add_argument("--root", type=Path)
    ap.add_argument("--python", help="OK-WW's interpreter (run)")
    ap.add_argument("--out", type=Path, help="results folder (run)")
    ap.add_argument("--summary", help="file to append a Markdown line per lane to (run; the job's step summary)")
    a = ap.parse_args(argv)
    if a.action == "lanes":
        print(json.dumps(sorted(LANES)))
        return 0
    if not (a.lane and a.root):
        ap.error("prepare and run need --lane and --root")
    if os.name != "nt":
        raise SystemExit("Windows only: ok-script imports pywin32 at module top (ok/util/window.py)")
    if a.action == "prepare":
        prepare(a.lane, a.root.resolve())
        return 0
    if not (a.python and a.out):
        ap.error("run needs --python and --out")
    return run(a.lane, a.root.resolve(), a.python, a.out.resolve(), a.summary)


if __name__ == "__main__":
    sys.exit(main())
