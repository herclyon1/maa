"""T9 corpus: the relay's verdicts on real AUTO-MAS + MaaEnd records that it once got wrong.

Each case under tests/gamesim/corpus/maaend/<case>/ is one failure from the game-layer
failure table (branches V3 / V4 / V5 / C6): the machine's own files, copied as they
were (AUTO-MAS history record + log, and where the verdict needs them AUTO-MAS's
app.log and MaaEnd's debug/ logs), laid out as on the machine:

    <case>/automas/history/<date>/<account>/<stem>.json|.log
    <case>/automas/debug/app.log           (optional)
    <case>/maaend/debug/...                (optional)

and a case.json:

    {"failure": "<date> <branch>: what went wrong on the machine",
     "fix": "<commit that fixed it>",
     "mtimes": {"<path in the case>": <the file's mtime on the machine, epoch s>},
     "checks": [{"probe": "record" | "outcome" | ..., ...probe args...,
                 "want": {<field>: <value>},
                 "evidence": {<field>: "<where the right value comes from>"}}]}

Rule 1 of the game-layer harness design: no `want` value comes from the code under
test. Every field in `want` carries an `evidence` entry outside our code - a line of
the record's own log, AUTO-MAS's or MaaEnd's source, the owner's words - and this
test refuses a check whose `want` has a field without one. Each case was shown red
on the code just before its fix and green at the fix (gamesim/corpus/maaend/prove.py
runs this file against those trees with --tree).

Probes:
  record   the record as the relay books it: collector.parse_record(<record>,
           <history root>[, <maaend dir>]), then the steps handle._book runs before
           the ledger line (book()); the only network read, the official Endfield
           bulletin, is served from the case's official/ copy. Compared
           fields: none (the whole result, for "not a run record"), script, ok,
           failed_tasks, transitional, started, finished, duration_known, and
           raw.<key> for each key of the record's raw dict.
  outcome  the outcome check of a MaaEnd run (outcome.maaend_checks over the record's
           log, outcome.summarize); compared fields: fault - whether it reports
           anything wrong, says - the summary's first line (null for nothing),
           check:<subject> - the ok of the checks about one subject (a task name). The relay also reads MaaEnd's own app
           log (MXU's debug/YYYY-MM-DD-N.log) into the same text; MaaEnd deletes
           it on restart and none survives from before 10-07, so a case without
           it asserts the one check the failure was about, not `fault`.
  ledger   the records booked, in order, in a fresh ledger and read back as the
           daily report reads them (probe_ledger); compared fields
           <record>|kind (episode_kinds: a failure that is not a fault),
           <record>|sanity, <record>|raw.<key>.

Failures of this group (T9) with no case, and why:
  09-13 C6 991a4be0  route narrowing from the live maafw.log: the relay stopped narrowing
                     routes on 10-05 (f8293cac), so there is no verdict left to assert.
  10-06 V4 5510ccf7  weekday-skipped 协议空间 listed as done, and
  10-06 V4 709fdb92  a round's second farming task lost: both were found by audit; no
                     machine record 08-14..10-13 has either shape (only 自动采集 is ever
                     weekday-skipped, no round ran both farming tasks), and the fixes'
                     own tests compose real lines.
  08-27 V5 bc3b709d  MaaEnd stuck on a popup closed itself, booked green: the verdict
                     rested on its on_error screenshots and MXU's app log, which MaaEnd
                     deleted at its next start; the record's own log shows all three
                     retried tasks 「任务完成」.

Usage: test_gl_corpus_maaend.py [--tree <relay dir>] [--case <name> ...]
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "gamesim" / "corpus" / "maaend"
ABSENT = "<absent>"
# The corpus must not quietly vanish (the .gitignore *.log precedent, test_replay.FLOOR):
# the 17 cases it was built with (2026-10-13).
FLOOR = 17


def _args(argv: list[str]) -> tuple[Path, list[str]]:
    tree, only = HERE.parent, []
    it = iter(argv)
    for a in it:
        if a == "--tree":
            tree = Path(next(it)).resolve()
        elif a == "--case":
            only.append(next(it))
        else:
            raise SystemExit(f"unknown argument {a!r}")
    return tree, only


def _module(*names: str):
    """The first of `names` that imports: the relay moved its modules over time
    (ark_relay/collector.py -> ark_relay/core/collector.py), and prove.py runs this
    file against trees from before the move."""
    last = None
    for name in names:
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as e:
            last = e
    raise last


def _collector():
    return _module("ark_relay.core.collector", "ark_relay.collector")


def _outcome():
    return _module("ark_relay.features.verify.outcome", "ark_relay.outcome")


def snapshot(rec) -> "dict | None":
    if rec is None:
        return None
    out = {"script": rec.script, "ok": rec.ok, "failed_tasks": list(rec.failed_tasks),
           "transitional": getattr(rec, "transitional", ABSENT),
           "started": rec.started.isoformat(), "finished": rec.finished.isoformat(),
           "duration_known": getattr(rec, "duration_known", ABSENT)}
    for k, v in (rec.raw or {}).items():
        out[f"raw.{k}"] = v
    return out


# The steps the relay runs on a parsed record before it writes the ledger line
# (handle._book at a44a536f: _mark_update_restart, then _confirm_unreachable), by
# name, in the modules they lived in over time. A tree without one did not have
# that step.
_BOOK_STEPS = ("_mark_update_restart", "_confirm_unreachable")
_BOOK_MODULES = ("ark_relay.features.alarm.records", "ark_relay.features.alarm.handle", "ark_relay.handle")


class _Offline:
    """urllib.request.urlopen for the booking steps: the case's copy of an official
    page (official/<file>, fetched from the real endpoint) for the one URL that
    reads it, and no network for anything else."""

    def __init__(self, root: Path):
        self.pages = sorted((root / "official").glob("*.json"))

    def __call__(self, req, *a, **k):
        url = getattr(req, "full_url", req)
        if "bulletin" in str(url) and self.pages:
            import io  # noqa: PLC0415
            return _Resp(io.BytesIO(self.pages[0].read_bytes()))
        raise OSError(f"no network in the corpus test: {url}")


class _Resp:
    def __init__(self, fh):
        self.fh = fh

    def read(self, *a):
        return self.fh.read(*a)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def book(root: Path, rel: str, state_dir: Path):
    """The record as the relay books it: parse_record, then the tree's pre-ledger steps."""
    collector = _collector()
    kwargs = {}
    if (root / "maaend").is_dir() and "maaend_dir" in inspect.signature(collector.parse_record).parameters:
        kwargs["maaend_dir"] = root / "maaend"
    rec = collector.parse_record(root / rel, root / "automas" / "history", **kwargs)
    if rec is None:
        return None
    cfg = type("Cfg", (), {"maaend_dir": str(root / "maaend") if (root / "maaend").is_dir() else None,
                           "state_dir": str(state_dir), "history_dir": str(root / "automas" / "history"),
                           "automas_dir": str(root / "automas"), "maa_dir": None})()
    eng = type("Eng", (), {"cfg": cfg})()
    import urllib.request  # noqa: PLC0415
    real = urllib.request.urlopen
    urllib.request.urlopen = _Offline(root)
    try:
        for step in _BOOK_STEPS:
            for name in _BOOK_MODULES:
                try:
                    fn = getattr(importlib.import_module(name), step, None)
                except ModuleNotFoundError:
                    continue
                if fn is not None:
                    fn(eng, rec)
                    break
    finally:
        urllib.request.urlopen = real
    return rec


def probe_record(root: Path, check: dict) -> "dict | None":
    with tempfile.TemporaryDirectory() as state_dir:
        return snapshot(book(root, check["record"], Path(state_dir)))


def probe_outcome(root: Path, check: dict) -> dict:
    outcome = _outcome()
    text = (root / check["log"]).read_text(encoding="utf-8", errors="replace")
    params = inspect.signature(outcome.maaend_checks).parameters
    args = [text]
    if "on_error_names" in params:
        args.append(list(check.get("on_error_names") or []))
    checks = outcome.maaend_checks(*args)
    says = outcome.summarize(checks, "终末地")
    out = {"fault": bool(says), "says": says.splitlines()[0] if says else None}
    # A check is keyed by what it is about - the first word of its label, the task
    # name for the per-task checks (「自动采集 真的走了路线」 until a later commit
    # shortened it to 「自动采集」) - not by its wording.
    for c in checks:
        key = f"check:{c.label.split(' ')[0]}"
        out[key] = out.get(key, True) and c.ok
    return out


# The daily report's pass over the day's ledger lines before it reads them: an
# Endfield record with one farming run gets its sanity spent from the previous
# record's remaining sanity (90d845cb). Looked up by name where it lived.
_FILL_STEPS = (("ark_relay.features.report.report", "_fill_single_run_sanity"),
               ("ark_relay.report", "_fill_single_run_sanity"),
               ("ark_relay.engine", "_fill_single_run_sanity"))


def probe_ledger(root: Path, check: dict) -> dict:
    """Book `records`, in order, in a fresh ledger the way the relay does
    (book(), State.append_ledger), read the day back as the daily report does
    (its sanity fill), and give per record: <record>|kind (episode_kinds:
    "update", "maintenance", ... - None when the tree has no episode_kinds, which
    excused nothing), <record>|sanity, <record>|raw.<key>."""
    ledger = _module("ark_relay.core.ledger", "ark_relay.core")
    with tempfile.TemporaryDirectory() as state_dir:
        state = ledger.State(Path(state_dir))
        days = set()
        ids = {}
        for rel in check["records"]:
            rec = book(root, rel, Path(state_dir))
            state.append_ledger(rec)
            days.add(rec.started.strftime("%Y-%m-%d"))
            ids[rec.run_id] = rel
        entries = [e for day in sorted(days) for e in state.read_ledger(day)]
    for name, fn in _FILL_STEPS:
        try:
            fill = getattr(importlib.import_module(name), fn, None)
        except ModuleNotFoundError:
            continue
        if fill is not None:
            fill(entries)
            break
    kinds = ledger.episode_kinds(entries) if hasattr(ledger, "episode_kinds") else {}
    out = {}
    for e in entries:
        rel = ids[e["run_id"]]
        out[f"{rel}|kind"] = kinds.get(e["run_id"])
        out[f"{rel}|sanity"] = e.get("sanity", ABSENT)
        for k, v in (e.get("raw") or {}).items():
            out[f"{rel}|raw.{k}"] = v
    return out


PROBES = {"record": probe_record, "outcome": probe_outcome, "ledger": probe_ledger}


def _git_tracked(paths: list[Path]) -> list[Path]:
    """Corpus files git does not track. *.log is ignored repo-wide outside
    tests/fixtures and tests/replay, so a log added without -f would vanish from
    every other clone and the case would fail as if the code were wrong."""
    try:
        out = subprocess.run(["git", "-C", str(CORPUS), "ls-files", "-z", "--", "."],
                             capture_output=True, check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []          # not a git checkout: nothing to compare against
    tracked = {(CORPUS / p).resolve() for p in out.decode("utf-8").split("\0") if p}
    return [p for p in paths if p.resolve() not in tracked]


def _diff(want, got) -> dict:
    """{field: what was got} for each field of `want` that `got` does not match."""
    if want is None or got is None:
        return {} if got == want else {"none": got}
    return {k: got.get(k, ABSENT) for k, v in want.items() if got.get(k, ABSENT) != v}


def run_case(case_dir: Path, fails: list[str], pinned: list[str], on_head: bool) -> int:
    """Run one case's checks; returns how many ran.

    A check may carry "head_wrong": {"since": <commit>, "got": {...}} - this tree's
    code gives a known wrong verdict on this real input, introduced by <commit>.
    On this checkout (no --tree) the check then passes only while the code gives
    exactly that wrong verdict, and says so on a ⚠ line and in the last line;
    once the code gives `want` the check fails until the marker is removed. With
    --tree (prove.py, old trees) `want` alone decides.
    """
    spec = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / case_dir.name
        shutil.copytree(case_dir, root)
        # The relay takes a record's end from its .json mtime: give every copied
        # file the mtime it had on the machine.
        for rel, mtime in (spec.get("mtimes") or {}).items():
            os.utime(root / rel, (mtime, mtime))
        for i, check in enumerate(spec["checks"]):
            label = f"{case_dir.name}#{i} {check['probe']}"
            want = check["want"]
            missing = [k for k in (want if isinstance(want, dict) else {"none": 0})
                       if not str((check.get("evidence") or {}).get(k, "")).strip()]
            if missing:
                fails.append(label)
                print(f"  ✗ {label}: no evidence for {missing} (rule 1: every expected value cites one)")
                continue
            got = PROBES[check["probe"]](root, check)
            n += 1
            bad = _diff(want, got)
            wrong = check.get("head_wrong") if on_head else None
            if wrong and not bad:
                fails.append(label)
                print(f"  ✗ {label}: gives the right verdict now - remove its head_wrong marker")
            elif wrong and not _diff(wrong["got"], got):
                pinned.append(f"{label} (since {wrong['since']})")
                print(f"  ⚠ {label}: still the known wrong verdict since {wrong['since']}: "
                      + ", ".join(f"{k}={v!r}" for k, v in wrong["got"].items())
                      + "; right is " + ", ".join(f"{k}={v!r}" for k, v in want.items()))
            elif bad:
                fails.append(label)
                print(f"  ✗ {label} ({spec['failure']})")
                for k, v in bad.items():
                    print(f"      {k}: want {(want or {}).get(k)!r}, got {v!r}")
            else:
                print(f"  ✓ {label}: " + (", ".join(f"{k}={v!r}" for k, v in want.items()) if want else "None"))
    return n


def main(argv: list[str]) -> int:
    tree, only = _args(argv)
    on_head = "--tree" not in argv
    sys.path.insert(0, str(tree))
    cases = sorted(p.parent for p in CORPUS.glob("*/case.json"))
    if only:
        cases = [c for c in cases if c.name in only]
        if len(cases) != len(only):
            raise SystemExit(f"no such case among {only}")
    fails: list[str] = []
    pinned: list[str] = []
    n = 0
    for case_dir in cases:
        n += run_case(case_dir, fails, pinned, on_head)
    if not only:
        files = [p for p in CORPUS.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        for p in _git_tracked(files):
            fails.append(str(p))
            print(f"  ✗ not tracked by git (add it with -f): {p.relative_to(HERE)}")
        if len(cases) < FLOOR:
            fails.append("floor")
            print(f"  ✗ only {len(cases)} cases found, want at least {FLOOR}")
    tail = f"; {len(pinned)} pinned wrong at this tree: {', '.join(pinned)}" if pinned else ""
    print(f"\n{len(cases)} cases, {n} checks" + tail + ", " + (f"FAILED: {len(fails)}" if fails else "all checks passed"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
