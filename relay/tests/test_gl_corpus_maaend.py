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
           log), compared field: says - the summary's first line, null for nothing.
  episodes the records booked in a fresh ledger, then the ledger's episode_kinds
           (a failure that is not a fault: "update", "maintenance"); compared
           fields: kind:<record path>.

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
# The corpus must not quietly vanish (the .gitignore *.log precedent, test_replay.FLOOR).
FLOOR = 20


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
    return {"says": says.splitlines()[0] if says else None}


def probe_episodes(root: Path, check: dict) -> dict:
    """Book `records` in a fresh ledger the way the relay does (State.append_ledger)
    and read the day's episode kinds back (episode_kinds: "update", "maintenance",
    ...). A tree with no episode_kinds excused nothing: every kind is None."""
    ledger = _module("ark_relay.core.ledger", "ark_relay.core")
    with tempfile.TemporaryDirectory() as state_dir:
        state = ledger.State(Path(state_dir))
        days = set()
        ids = {}
        for rel in check["records"]:
            rec = book(root, rel, Path(state_dir))
            state.append_ledger(rec)
            days.add(rec.started.strftime("%Y-%m-%d"))
            ids[rel] = rec.run_id
        entries = [e for day in sorted(days) for e in state.read_ledger(day)]
    kinds = ledger.episode_kinds(entries) if hasattr(ledger, "episode_kinds") else {}
    return {f"kind:{rel}": kinds.get(run_id) for rel, run_id in ids.items()}


PROBES = {"record": probe_record, "outcome": probe_outcome, "episodes": probe_episodes}


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


def run_case(case_dir: Path, fails: list[str]) -> int:
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
            missing = [k for k in (want if isinstance(want, dict) else {"": 0})
                       if not str((check.get("evidence") or {}).get(k or "none", "")).strip()]
            if missing:
                fails.append(label)
                print(f"  ✗ {label}: no evidence for {missing} (rule 1: every expected value cites one)")
                continue
            got = PROBES[check["probe"]](root, check)
            n += 1
            if want is None or got is None:
                if got != want:
                    fails.append(label)
                    print(f"  ✗ {label}: want {want!r}, got {got!r}")
                else:
                    print(f"  ✓ {label}: {got!r}")
                continue
            bad = {k: got.get(k, ABSENT) for k, v in want.items() if got.get(k, ABSENT) != v}
            if bad:
                fails.append(label)
                print(f"  ✗ {label} ({spec['failure']})")
                for k, v in bad.items():
                    print(f"      {k}: want {want[k]!r}, got {v!r}")
            else:
                print(f"  ✓ {label}: " + ", ".join(f"{k}={v!r}" for k, v in want.items()))
    return n


def main(argv: list[str]) -> int:
    tree, only = _args(argv)
    sys.path.insert(0, str(tree))
    cases = sorted(p.parent for p in CORPUS.glob("*/case.json"))
    if only:
        cases = [c for c in cases if c.name in only]
        if len(cases) != len(only):
            raise SystemExit(f"no such case among {only}")
    fails: list[str] = []
    n = 0
    for case_dir in cases:
        n += run_case(case_dir, fails)
    if not only:
        untracked = _git_tracked([p for p in CORPUS.rglob("*") if p.is_file()])
        for p in untracked:
            fails.append(str(p))
            print(f"  ✗ not tracked by git (add it with -f): {p.relative_to(HERE)}")
        if len(cases) < FLOOR:
            fails.append("floor")
            print(f"  ✗ only {len(cases)} cases found, want at least {FLOOR}")
    print(f"\n{len(cases)} cases, {n} checks, " + (f"FAILED: {len(fails)}" if fails else "all checks passed"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
