"""Red-before-green proof for the T9 corpus (rule 1 of the game-layer harness design).

For each case, extract the relay tree at <fix>~1 and at <fix> (git archive, into a
temporary directory) and run tests/test_gl_corpus_maaend.py --tree <that tree>
--case <case>. A case is accepted when it is RED at <fix>~1 and GREEN at <fix>.
The test file and the corpus always come from this checkout; only the code under
test changes.

    prove.py [<case> ...]        (all cases when none is named)
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[2]
REPO = TESTS.parents[1]
TEST = TESTS / "test_gl_corpus_maaend.py"


def tree_at(rev: str, into: Path) -> Path:
    """The relay/ directory of `rev`, extracted under `into`."""
    into.mkdir(parents=True, exist_ok=True)
    arch = subprocess.run(["git", "-C", str(REPO), "archive", rev, "relay"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(into)], input=arch, check=True)
    return into / "relay"


def run(tree: Path, case: str) -> tuple[str, str]:
    """(GREEN | RED | ERROR, the test's output) for one case on one tree."""
    p = subprocess.run([sys.executable, str(TEST), "--tree", str(tree), "--case", case],
                       capture_output=True, text=True, timeout=300, cwd=str(tree))
    out = p.stdout + p.stderr
    if p.returncode == 0 and out.rstrip().endswith("all checks passed"):
        return "GREEN", out
    # A red must be an assertion (✗ line), never an import error or a crash.
    if "Traceback" in out or "✗" not in out:
        return "ERROR", out
    return "RED", out


def main(argv: list[str]) -> int:
    names = argv or sorted(p.parent.name for p in HERE.glob("*/case.json"))
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            fix = json.loads((HERE / name / "case.json").read_text(encoding="utf-8"))["fix"]
            before, out_before = run(tree_at(f"{fix}~1", Path(tmp) / f"{fix}-before"), name)
            after, out_after = run(tree_at(fix, Path(tmp) / f"{fix}-at"), name)
            ok = before == "RED" and after == "GREEN"
            bad += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {name}: {fix}~1 {before}, {fix} {after}")
            for label, verdict, out in (("~1", before, out_before), ("fix", after, out_after)):
                if verdict != "GREEN" or not ok:
                    for line in out.splitlines():
                        if line.lstrip().startswith(("✗", "want", "Traceback")) or ": want" in line \
                                or line.startswith(("  File", "    ")) and verdict == "ERROR":
                            print(f"    [{label}] {line.strip()}")
    print(f"\n{len(names)} cases, " + (f"FAILED: {bad}" if bad else "all red before, green at fix"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
