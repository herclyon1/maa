#!/usr/bin/env python3
"""Deploy gate: no finished relay fix may sit on a branch, outside main, unreviewed.

On 10-11 23 local branches turned out to hold relay changes that never reached main.
One of them, relay2-mxuquit-1010 (a4be51cb), fixed the Endfield hang on 10-10; it was
never merged, so the machine kept the old code and the group kept getting the alarm.
No deploy gate looked for this.

What it checks. For every local branch and every origin/* ref (main and HEAD excluded),
take the commits that `git cherry origin/main <ref>` would mark "+" - not merged, and no
commit with the same patch in main - whose diff touches relay/ or scripts/windows/ (the
code that ships to the machine). Each one must be listed in docs/UNMERGED-REVIEWED.txt:

    <hash8> <a|b|declined> <one-line reason>

    a        the same fix is in main as <hash> (moved files, so git cannot match it)
    b        superseded by <hash> in main
    declined decided not to ship; the reason cites a DECISIONS id or a file

`#` starts a comment line. Anything unlisted is printed (branch, hash, subject) and the
exit code is 1; a malformed line in the list is also exit 1, so a typo never un-gates.

Why a hand-checked list and not git alone: `git cherry` compares patch ids, and a fix
that was carried over with its files moved has a different patch id. Only a person
reading both diffs can say it is the same fix.

Two deliberate details:
  - The base is origin/main *and* HEAD. The deploy ends with `push HEAD:refs/heads/main`,
    so commits on HEAD are the ones being shipped right now; they are not "left behind".
  - Patch ids are computed in two `git log -p` runs (the candidates, and every main
    commit touching those paths) instead of one `git cherry` per ref: 600-odd refs one
    by one would take far longer than the whole rest of the gate stage.
    Measured 10-11 on this repo (607 refs): about 1 s for the whole check.

    python3 scripts/mac/lib/unmerged_fixes.py
    python3 scripts/mac/lib/unmerged_fixes.py --root DIR --reviewed FILE
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
PATHS = ("relay", "scripts/windows")
BASE_REFS = ("origin/main", "HEAD")
SKIP_REFS = {"refs/heads/main", "refs/remotes/origin/main", "refs/remotes/origin/HEAD"}
LINE = re.compile(r"^([0-9a-f]{8})\s+(a|b|declined)\s+(\S.*)$")
# The two sides of the patch-id comparison must be diffed the same way whatever the
# user's git config says (noprefix, renames, external diff tools).
GIT = ["git", "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false",
       "-c", "diff.renames=true", "-c", "core.quotePath=false"]
DIFF = ["-p", "--full-diff", "--no-ext-diff", "--no-textconv", "--no-color"]


def git(root: pathlib.Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run([*GIT, *args], cwd=root, input=stdin, capture_output=True,
                          text=True, check=True).stdout


def patch_ids(root: pathlib.Path, log_out: str) -> "dict[str, str]":
    """commit -> stable patch id, from `git log -p --format='commit %H'` output."""
    out = subprocess.run(["git", "patch-id", "--stable"], cwd=root, input=log_out,
                         capture_output=True, text=True, check=True).stdout
    ids = {}
    for line in out.splitlines():
        pid, commit = line.split()
        ids[commit] = pid
    return ids


def base_refs(root: pathlib.Path) -> "list[str]":
    """The base refs that exist here (a fresh clone may have no origin/main)."""
    return [b for b in BASE_REFS
            if subprocess.run(["git", "rev-parse", "--verify", "--quiet", b + "^{commit}"],
                              cwd=root, capture_output=True).returncode == 0]


def read_reviewed(path: pathlib.Path) -> "tuple[dict[str, str], list[str]]":
    listed, bad = {}, []
    if not path.exists():
        return listed, [f"{path}: missing"]
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE.match(line)
        if not m:
            bad.append(f"{path.name}:{n}: {raw}")
            continue
        listed[m.group(1)] = m.group(2)
    return listed, bad


def candidates(root: pathlib.Path) -> "list[tuple[str, str, str]]":
    """(commit, ref, subject) for each commit not in the base that touches PATHS."""
    refs = [r for r in git(root, "for-each-ref", "--format=%(refname)",
                           "refs/heads", "refs/remotes/origin").split()
            if r not in SKIP_REFS]
    if not refs:
        return []
    have = base_refs(root)
    out = git(root, "log", "--no-merges", "--source", "--format=%H%x00%S%x00%s", "--stdin",
              *("^" + b for b in have), "--", *PATHS, stdin="\n".join(refs) + "\n")
    rows = []
    for line in out.splitlines():
        commit, ref, subject = line.split("\x00", 2)
        for prefix in ("refs/heads/", "refs/remotes/"):
            if ref.startswith(prefix):
                ref = ref[len(prefix):]
        rows.append((commit, ref, subject))
    return rows


def unmerged(root: pathlib.Path) -> "list[tuple[str, str, str]]":
    """The "+" commits: candidates with no same-patch commit in the base."""
    rows = candidates(root)
    if not rows:
        return []
    mine = patch_ids(root, git(root, "log", "--no-walk=unsorted", "--stdin", *DIFF,
                               "--format=commit %H",
                               stdin="\n".join(c for c, _, _ in rows) + "\n"))
    have = base_refs(root)
    in_main = set(patch_ids(root, git(root, "log", "--no-merges", *DIFF, "--format=commit %H",
                                      *have, "--", *PATHS)).values())
    return [r for r in rows if mine.get(r[0]) not in in_main]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=pathlib.Path, default=ROOT)
    ap.add_argument("--reviewed", type=pathlib.Path, default=None)
    a = ap.parse_args()
    reviewed = a.reviewed or a.root / "docs" / "UNMERGED-REVIEWED.txt"
    listed, bad = read_reviewed(reviewed)
    rows = unmerged(a.root)
    blocking = [r for r in rows if r[0][:8] not in listed]
    if bad:
        print("unreadable lines in the review list (want '<hash8> <a|b|declined> <reason>'):")
        for b in bad:
            print("  " + b)
    if blocking:
        print(f"{len(blocking)} relay commit(s) on a branch, not in main, not reviewed:")
        for commit, ref, subject in blocking:
            print(f"  {ref}  {commit[:8]}  {subject}")
        print(f"Merge each into main, or list it in {reviewed.name} after reading both diffs.")
        print("A stale local origin/main makes merged commits look unmerged: git fetch origin.")
    if bad or blocking:
        return 1
    print(f"no unreviewed relay fixes left on branches "
          f"({len(rows)} not in main, all listed in {reviewed.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
