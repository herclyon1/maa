"""Red before green, per case: run tests/test_gl_corpus_okww.py against the relay of each
commit a case names in cases.json (`proof.red_at`, `proof.green_at`).

A case is accepted only if its own run is judged wrong at every `red_at` commit - the test
fails on that case at an assertion, not at an import or a harness error - and right at
`green_at`. The relay of each commit is taken with `git archive <commit> relay` into a
temporary directory; the corpus and the test file are always this checkout's. One process
per commit, since one Python process can hold only one era's ark_relay.

Not part of the deploy gate (it reads git history and takes a few seconds per commit);
run it after adding or changing a case and copy its table into README.md.

    python3.14 relay/tests/gamesim/corpus/okww/prove.py [--case ID]
"""
from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEST = HERE.parents[2] / "test_gl_corpus_okww.py"


def _repo() -> Path:
    out = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def _tree(commit: str, into: Path, repo: Path) -> Path:
    """relay/ of `commit`, unpacked under `into`; reused across cases."""
    d = into / commit.replace("~", "_").replace("^", "_")
    if not d.exists():
        blob = subprocess.run(["git", "-C", str(repo), "archive", commit, "relay"],
                              capture_output=True, check=True).stdout
        with tarfile.open(fileobj=BytesIO(blob)) as tf:
            tf.extractall(d, filter="data")
    return d / "relay"


def _run(case_id: str, root: Path) -> "tuple[str, str]":
    """('red' | 'green' | 'broken', the lines that say why) for one case on one tree."""
    p = subprocess.run([sys.executable, str(TEST), "--relay-root", str(root), "--case", case_id],
                       capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    lines = out.splitlines()
    # A crash starts a line with 「Traceback」; an assertion may quote a log line that has the
    # word inside it (10-15: OK-WW's 「refresh error Traceback (most recent call last):」).
    if any(ln.startswith("Traceback") for ln in lines) or "HARNESS" in out:
        return "broken", out[-600:]
    if p.returncode == 0 and f"  ✓ {case_id} " in out:
        return "green", ""
    if p.returncode == 1 and any(ln.startswith(f"  ✗ {case_id} ") for ln in lines):
        return "red", "; ".join(ln.strip() for ln in lines if ln.startswith("      "))[:300]
    return "broken", out[-600:]


def main(argv: list[str]) -> int:
    only = argv[argv.index("--case") + 1] if "--case" in argv else None
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    repo, bad = _repo(), []
    print("| case | red at | green at | first red assertion |")
    print("|---|---|---|---|")
    with tempfile.TemporaryDirectory(prefix="gl-okww-prove-") as tmp:
        for c in cases:
            if only and c["id"] != only:
                continue
            proof = c["proof"]
            reds, why = [], ""
            for commit in proof["red_at"]:
                got, detail = _run(c["id"], _tree(commit, Path(tmp), repo))
                reds.append(f"{commit} {got}")
                why = why or detail
                if got != "red":
                    bad.append(f"{c['id']}: {commit} is {got}, not red: {detail}")
            got, detail = _run(c["id"], _tree(proof["green_at"], Path(tmp), repo))
            if got != "green":
                bad.append(f"{c['id']}: {proof['green_at']} is {got}, not green: {detail}")
            print(f"| {c['id']} | {', '.join(reds)} | {proof['green_at']} {got} | {why.replace('|', '/')} |")
    for b in bad:
        print(f"  ✗ {b}")
    print("all red before green" if not bad else f"FAILED: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
