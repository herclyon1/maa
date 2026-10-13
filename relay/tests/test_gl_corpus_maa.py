"""T10: the relay's MAA verdicts on real MAA runs (offline game-layer harness, unit U13c).

Every expected value in tests/gamesim/corpus/maa comes from evidence outside the relay's
code - MAA's own lines, AUTO-MAS's own result JSON, or a later run of the same week - and
carries that evidence next to it (cases.json, history/<date>/expected.json, SOURCE.txt).
What is asserted is what collector_maa.parse_maa_log and outcome.maa_checks / summarize /
maa_sanity_short make of those runs.

  cases.json   the T10 incidents; each case names the commit that fixed it and must
               fail an assertion at red_at (<fix>~1) and at every also_red commit, and pass
               at green_at (--prove re-runs that from git history). A fix committed with
               its case cannot name its own hash and says "self": the commit that added
               the case's id to cases.json (resolve).
  history/     all 167 MAA records AUTO-MAS kept 2026-08-14..10-13, labelled from MAA's
               printed totals / annihilation line / refusal line.
  live_bugs    verdicts the evidence says are wrong on today's code. They are expected to
               fail; one that passes fails the test, so a fix has to move it into cases.

  python3 tests/test_gl_corpus_maa.py                          the gate
  python3 tests/test_gl_corpus_maa.py --relay DIR --case ID    one case on another relay tree
  python3 tests/test_gl_corpus_maa.py --prove                  red_at / green_at for every case
"""
from __future__ import annotations

import argparse
import gzip
import importlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
REPO = RELAY.parent
CORPUS = RELAY / "tests" / "gamesim" / "corpus" / "maa"
HISTORY_FLOOR = 167
T10_IDS = {"T10-1-config-refusal", "T10-2-annihilation-cap", "T10-3-drop-running-totals",
           "T10-4-infrast-recovery-is-not-failure", "T10-5-window-reaches-next-run",
           "T10-6-sanity-short", "T10-7-annihilation-no-progress",
           "T10-8-stop-receipt-after-completion", "T10-9-rounded-drop-totals"}

# The repo is public: what the redaction in SOURCE.txt removed must stay removed.
PRIVATE = (
    re.compile(r"PenguinID [1-9]"),
    re.compile(r'"(?:penguin|yituliu)_id":"[1-9]'),
    re.compile(r'\\?"uuid\\?":\\?"[0-9a-f]*[1-9a-f]'),
    re.compile(r'Idempotency-Key":"(?!<redacted>")'),
    re.compile(r"auth_key=(?!<redacted>)"),
    re.compile(r"q-signature=(?!<redacted>)"),
    re.compile(r"AKID(?!REDACTED)"),
    re.compile(r"cgi-bin/webhook|sctapi\.|sc\.ftqq\.com"),
)

FAILS: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


def require(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok or not detail else f": {detail}"))
    if not ok:
        FAILS.append(name)


# ---------------------------------------------------------------- the code under test

def _module(name: str):
    """The module, or None when that module path does not exist in this relay tree."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name and name.startswith(e.name):
            return None
        raise


def load_relay(relay: Path) -> dict:
    """The verdict functions of one relay tree, wherever that tree keeps them.

    The modules moved (ark_relay.collector -> ark_relay.collector_maa ->
    features.verify.collector_maa; ark_relay.outcome -> features.verify.outcome) and some
    functions are younger than the fixes they are checked against. A function the tree
    does not have is None: that tree gave no such verdict (before ea143346 the relay did
    not check MAA at all, before a0c23e1d it had no 「sanity short」).
    """
    sys.path.insert(0, str(relay))
    out: dict = {"parse_maa_log": None, "maa_checks": None, "summarize": None, "maa_sanity_short": None}
    for name in ("ark_relay.features.verify.collector_maa", "ark_relay.collector_maa", "ark_relay.collector"):
        if (m := _module(name)) is not None and hasattr(m, "parse_maa_log"):
            out["parse_maa_log"] = m.parse_maa_log
            break
    for name in ("ark_relay.features.verify.outcome", "ark_relay.outcome"):
        if (m := _module(name)) is not None:
            for fn in ("maa_checks", "summarize", "maa_sanity_short"):
                out[fn] = getattr(m, fn, None)
            break
    if out["parse_maa_log"] is None:
        raise SystemExit(f"no parse_maa_log under {relay}")
    return out


# ---------------------------------------------------------------- reading the corpus

def corpus_text(rel: str) -> str:
    return gzip.decompress((CORPUS / rel).read_bytes()).decode("utf-8")


class Judge:
    """What one relay tree says about each corpus input; parsed once per input."""

    def __init__(self, fns: dict, tmp: Path):
        self.fns = fns
        self.tmp = tmp
        self.seen: dict = {}

    def history(self, ref: str) -> dict:
        """parse_maa_log on history/<date>/<stem> (written out byte for byte, as the relay reads it)."""
        if ref not in self.seen:
            day, stem = ref.split("/")[1:]
            path = self.tmp / day / f"{stem}.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.decompress((CORPUS / "history" / day / f"{stem}.log.gz").read_bytes()))
            self.seen[ref] = self.fns["parse_maa_log"](path)
        return self.seen[ref]

    def verdict(self, ref: str, kind: str):
        text = corpus_text(ref + ".gz")
        if kind == "alarm":
            if self.fns["maa_checks"] is None:
                return False            # no MAA check in this tree: the run was never alarmed on
            return self.fns["summarize"](self.fns["maa_checks"](text), "MAA") is not None
        if kind == "sanity_short":
            fn = self.fns["maa_sanity_short"]
            return fn(text) if fn else None
        raise ValueError(kind)


def bulk_want(ref: str, field: str):
    day, stem = ref.split("/")[1:]
    return json.loads((CORPUS / "history" / day / "expected.json").read_text(encoding="utf-8"))[stem].get(field)


def run_check(judge: Judge, c: dict) -> "tuple[bool, object, object]":
    """(passed, got, want) for one check of cases.json."""
    if "field" in c:
        got = judge.history(c["input"]).get(c["field"])
        if "contains" in c:
            return isinstance(got, str) and all(s in got for s in c["contains"]), got, {"contains": c["contains"]}
        want = bulk_want(c["input"], c["field"]) if c["want"] == "bulk" else c["want"]
        return got == want, got, want
    got = judge.verdict(c["input"], c["verdict"])
    if "subset" in c:
        sub = c["subset"]
        return isinstance(got, dict) and all(got.get(k) == v for k, v in sub.items()), got, {"subset": sub}
    return got == c["want"], got, c["want"]


def run_case(judge: Judge, case: dict) -> None:
    print(f"\n[{case['id']}] {case['incident']}")
    for c in case["checks"]:
        ok, got, want = run_check(judge, c)
        name = f"{c['input']} {c.get('field') or c.get('verdict')}"
        check(name, got if not ok else want, want)


def run_live_bugs(judge: Judge, bugs: list) -> "set[tuple[str, str]]":
    """Each live bug must still fail; returns the (input, field) pairs the bulk pass leaves to it."""
    owned = set()
    for bug in bugs:
        print(f"\n[{bug['id']}] known wrong on today's code (must fail until fixed)")
        for c in bug["checks"]:
            ok, got, want = run_check(judge, c)
            name = f"{c['input']} {c.get('field') or c.get('verdict')}"
            require(f"{name} still wrong (got {got!r}, evidence says {want!r})", not ok,
                    "now right: move this check into cases.json with the commit that fixed it")
            if "field" in c:
                owned.add((c["input"], c["field"]))
    return owned


def run_bulk(judge: Judge, owned: "set[tuple[str, str]]") -> int:
    """Every history record against its labels; returns how many records were checked."""
    n = 0
    print("\n[history] every AUTO-MAS MAA record 08-14..10-13")
    for ef in sorted((CORPUS / "history").glob("*/expected.json")):
        for stem, want in json.loads(ef.read_text(encoding="utf-8")).items():
            n += 1
            ref = f"history/{ef.parent.name}/{stem}"
            got = judge.history(ref)
            bad = []
            for field in ("drop_statistics", "annihilation", "annihilation_progress", "annihilation_done"):
                if (ref, field) in owned:
                    continue
                if field == "annihilation_done" and field not in want:
                    continue            # not proven either way by this record alone (SOURCE.txt)
                if got.get(field) != want.get(field):
                    bad.append(f"{field}: got {got.get(field)!r}, want {want.get(field)!r}")
            rej, got_rej = want.get("maa_config_rejected"), got.get("maa_config_rejected")
            if rej is None and got_rej is not None:
                bad.append(f"maa_config_rejected: got {got_rej!r}, MAA refused nothing")
            if rej is not None and not (isinstance(got_rej, str) and all(s in got_rej for s in rej["contains"])):
                bad.append(f"maa_config_rejected: got {got_rej!r}, want {rej}")
            if bad:
                require(ref, False, "; ".join(bad) + f" [evidence: {want['evidence']}]")
    require(f"{n} history records match their labels", n >= HISTORY_FLOOR,
            f"only {n} records found, the corpus has {HISTORY_FLOOR}")
    return n


def run_privacy() -> None:
    print("\n[privacy] the public repo carries no ids, keys or signed links from these logs")
    files = sorted(p for p in CORPUS.rglob("*") if p.is_file())
    hits = []
    for p in files:
        text = gzip.decompress(p.read_bytes()).decode("utf-8") if p.suffix == ".gz" else p.read_text(encoding="utf-8")
        hits += [f"{p.relative_to(CORPUS)}: {rx.pattern}" for rx in PRIVATE if rx.search(text)]
    require(f"{len(files)} corpus files redacted", not hits, "; ".join(hits[:5]))


# ---------------------------------------------------------------- red / green proof

def resolve(rev: str, case_id: str) -> str:
    """`rev` with a leading "self" replaced by the commit that added `case_id` to cases.json."""
    if not rev.startswith("self"):
        return rev
    shas = subprocess.run(["git", "-C", str(REPO), "log", "--reverse", "--format=%H", f'-S"id": "{case_id}"',
                           "--", str((CORPUS / "cases.json").relative_to(REPO))],
                          capture_output=True, text=True, check=True).stdout.split()
    if not shas:
        raise SystemExit(f"{case_id}: 'self' case not committed yet")
    return shas[0][:8] + rev[len("self"):]


def prove(cases: list) -> None:
    """Each case on its red_at tree (must fail) and its green_at tree (must pass)."""
    for case in cases:
        revs = [(case["red_at"], False), (case["green_at"], True)] + [(r, False) for r in case.get("also_red", [])]
        revs = [(resolve(r, case["id"]), want) for r, want in revs]
        for rev, want_pass in revs:
            with tempfile.TemporaryDirectory() as td:
                arch = subprocess.run(["git", "-C", str(REPO), "archive", rev, "relay/ark_relay"],
                                      capture_output=True, check=True).stdout
                subprocess.run(["tar", "-x", "-C", td], input=arch, check=True)
                r = subprocess.run([sys.executable, __file__, "--relay", str(Path(td) / "relay"),
                                    "--case", case["id"]], capture_output=True, text=True)
            fails = [ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith("FAIL")]
            # Red means a verdict assertion failed, not that the old tree crashed.
            check(f"{case['id']} at {rev} {'passes' if want_pass else 'fails at an assertion'}"
                  + (f" ({fails[0][:150]})" if fails and not want_pass else ""),
                  r.returncode == 0 if want_pass else bool(fails) and r.returncode == 1, True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--relay", type=Path, default=RELAY)
    ap.add_argument("--case")
    ap.add_argument("--prove", action="store_true")
    args = ap.parse_args()
    spec = json.loads((CORPUS / "cases.json").read_text(encoding="utf-8"))
    cases = spec["cases"]
    if args.prove:
        prove(cases)
    else:
        with tempfile.TemporaryDirectory() as td:
            judge = Judge(load_relay(args.relay), Path(td))
            if args.case:
                run_case(judge, next(c for c in cases if c["id"] == args.case))
            else:
                check("the T10 cases are all here", {c["id"] for c in cases}, T10_IDS)
                for case in cases:
                    require(f"{case['id']} names its fix and red/green commits",
                            bool(case["fix"] and case["red_at"] and case["green_at"]))
                    run_case(judge, case)
                owned = run_live_bugs(judge, spec["live_bugs"])
                run_bulk(judge, owned)
                run_privacy()
    print(f"\nFAILED: {len(FAILS)}" if FAILS else "\nall checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
