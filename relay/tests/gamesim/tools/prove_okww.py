#!/usr/bin/env python3
"""Red before green for the OK-WW game-layer tests: each case's check fails at <fix>~1 and passes at <fix>.

gamesim design, rule 1: a case is accepted only when it fails on the input that broke on
the machine and passes at the fix. For each case this builds the tree of a revision with
`git archive <rev> relay` in a temporary directory, copies in today's test file and
relay/tests/gamesim/ (the fetched upstream copies, the schema reader), runs the test there
and reads the one check line the case is about ("✓ <label>" or "✗ <label>"). An overlay
case keeps today's tree and puts in the overrides file as it was at the revision (its path
moved on 10-10; the module that reads it did not keep the same functions across the move).

    relay-python relay/tests/gamesim/tools/prove_okww.py          # every case
    relay-python relay/tests/gamesim/tools/prove_okww.py 35d6166b # some, by fix commit

A fix committed together with its case cannot name its own hash, so its row says "self":
the fix is then the first commit that added the row's check label to this file.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
TESTS = REPO / "relay" / "tests"
OVERLAY = "relay/ark_relay/features/okww_patch/okww_files/ark_overrides.tasks.py"

# (fix commit, test file, test arguments, the check label, overlay path at the fix or None)
CASES = [
    ("b24c48fc", "test_gl_okww_contract.py", [],
     "FarmEchoTask.run: target exists, takes upstream's calls", None),
    ("f6b5f432", "test_gl_okww_contract.py", ["v3.7.3"],
     "every pinned body found upstream and equal", "relay/ark_relay/okww_files/ark_overrides.tasks.py"),
    ("f6b5f432", "test_gl_okww_contract.py", ["v3.7.3"],
     "okww_overlay.drift() is empty", "relay/ark_relay/okww_files/ark_overrides.tasks.py"),
    ("0a69e862", "test_gl_okww_config.py", ["mastercfg"],
     "every drop-down value write_okww accepts is one upstream keeps, lists and reads", None),
    ("a3bf4e82", "test_gl_okww_config.py", ["mastercfg"],
     "every serial write_okww accepts is within upstream's list", None),
    ("08b71251", "test_gl_okww_config.py", ["weekly"],
     "FarmEchoTask.json unreadable: the daily is not left to raise before login", None),
    ("21dac430", "test_gl_okww_config.py", ["echofarm"],
     "start farms boss 1 in a machine-shaped tree", None),
    ("35d6166b", "test_gl_okww_config.py", ["echofarm"],
     "every setting start writes for its teleport target is read on that target's path", None),
    ("85ca8649", "test_gl_okww_config.py", ["overlay"],
     "no overlay read depends on a key ok-script drops at load", None),
    ("self", "test_gl_okww_config.py", ["echofarm"],
     "start takes exactly upstream's Boss Challenge list (1..total_boss_number)", None),
]


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=True).stdout


def resolve(fix: str, label: str) -> str:
    """A fix commit; "self" is the first commit that added `label` to this file."""
    if fix != "self":
        return fix
    rel = str(Path(__file__).resolve().relative_to(REPO))
    shas = git("log", "--reverse", "--format=%H", f"-S{label}", "--", rel).decode().split()
    if not shas:
        raise SystemExit(f"'self' row not committed yet: {label}")
    return shas[0][:8]


def tree(rev: str, test: str, overlay_from: "str | None") -> Path:
    """relay/ at `rev` (or today's, with the overlay of `rev`), plus today's test and gamesim/."""
    root = Path(tempfile.mkdtemp(prefix="gamesim-prove-"))
    base = "HEAD" if overlay_from else rev
    with tarfile.open(fileobj=io.BytesIO(git("archive", base, "relay"))) as tar:
        tar.extractall(root, filter="data")
    if overlay_from:
        (root / OVERLAY).write_bytes(git("show", f"{rev}:{overlay_from}"))
    shutil.copy2(TESTS / test, root / "relay" / "tests" / test)
    shutil.copytree(TESTS / "gamesim", root / "relay" / "tests" / "gamesim", dirs_exist_ok=True)
    return root


def verdict(rev: str, test: str, args: list, label: str, overlay_from: "str | None") -> "tuple[str, str]":
    """('red' | 'green' | 'not run', the line that says so)."""
    root = tree(rev, test, overlay_from)
    try:
        out = subprocess.run([sys.executable, f"tests/{test}", *args], cwd=root / "relay",
                             capture_output=True, text=True).stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)
    for line in out.splitlines():
        if line.startswith(f"  ✓ {label}"):
            return "green", line.strip()
        if line.startswith(f"  ✗ {label}"):
            return "red", line.strip()
    return "not run", (out.strip().splitlines() or ["no output"])[-1]


def main(argv: list[str]) -> int:
    bad = 0
    for fix, test, args, label, overlay_from in CASES:
        fix = resolve(fix, label)
        if argv and fix not in argv:
            continue
        (before, why), (after, why_after) = (verdict(f"{fix}~1", test, args, label, overlay_from),
                                             verdict(fix, test, args, label, overlay_from))
        ok = before == "red" and after == "green"
        bad += not ok
        print(f"{'✓' if ok else '✗'} {fix}  {test} {' '.join(args)}  {fix}~1 {before}, {fix} {after}\n"
              f"    {fix}~1: {why[:300]}" + ("" if after == "green" else f"\n    {fix}: {why_after[:300]}"))
    print("all cases red before green" if not bad else f"{bad} cases not red before green")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
