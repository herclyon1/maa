"""deploy-relay.sh step 0.6: a finished relay fix may not sit on a branch, unreviewed.

On 10-11 23 local branches held relay changes that never reached main (one was the
10-10 Endfield-hang fix a4be51cb). Checked here on a temporary git repo whose
origin/main is the baseline commit:
  - a branch commit touching relay/ that is not in main and not listed blocks (exit 1),
    and the output names its branch, hash and subject;
  - the same commit listed in the review file passes;
  - a docs-only commit on a branch is ignored;
  - a commit whose patch is already in main (cherry-picked: `git cherry` says "-") is
    ignored, and so is a commit on HEAD (the deploy pushes HEAD to main);
  - a malformed review line (unknown verdict) fails closed;
  - all of it under diff.noprefix / diff.mnemonicPrefix / diff.renames=false;
  - deploy-relay.sh runs the gate before the pre-deploy replay.
"""
import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


uf = load("unmerged_fixes", ROOT / "scripts/mac/lib/unmerged_fixes.py")
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


G = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def git(*a, cwd):
    return subprocess.run([*G, *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


def commit(base, path, text, msg):
    p = base / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    git("add", "-A", cwd=base)
    git("commit", "-qm", msg, cwd=base)
    return git("rev-parse", "HEAD", cwd=base).strip()


def run(base, reviewed):
    (base / "docs").mkdir(exist_ok=True)
    (base / "docs/UNMERGED-REVIEWED.txt").write_text(reviewed, encoding="utf-8")
    out = io.StringIO()
    argv = sys.argv
    sys.argv = ["unmerged_fixes.py", "--root", str(base)]
    try:
        with contextlib.redirect_stdout(out):
            rc = uf.main()
    finally:
        sys.argv = argv
    return rc, out.getvalue()


with tempfile.TemporaryDirectory() as d:
    base = Path(d)
    git("init", "-q", "-b", "main", cwd=base)
    for k, v in (("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"),
                 ("diff.renames", "false")):
        git("config", k, v, cwd=base)
    commit(base, "relay/ark_relay/x.py", "A = 1\n", "base")
    git("update-ref", "refs/remotes/origin/main", "main", cwd=base)

    git("checkout", "-qb", "fix-branch", cwd=base)
    fix = commit(base, "relay/ark_relay/x.py", "A = 2\n", "relay: the fix nobody merged")
    git("checkout", "-qb", "docs-branch", "main", cwd=base)
    commit(base, "docs/NOTE.md", "note\n", "docs only")
    git("checkout", "-qb", "picked-branch", "main", cwd=base)
    picked = commit(base, "scripts/windows/w.py", "B = 1\n", "windows: picked into main")
    git("checkout", "-q", "main", cwd=base)
    # main moves first, so the pick gets a new parent and a new hash (same second,
    # same parent would reproduce the very same commit).
    commit(base, "relay/ark_relay/y.py", "C = 1\n", "main moves on")
    git("cherry-pick", picked, cwd=base)
    git("update-ref", "refs/remotes/origin/main", "main", cwd=base)
    check("git cherry marks the picked commit '-'",
          git("cherry", "origin/main", "picked-branch", cwd=base).split()[0], "-")

    rc, out = run(base, "# nothing reviewed yet\n")
    check("an unlisted relay commit blocks", rc, 1)
    check("the output names branch, hash and subject",
          f"fix-branch  {fix[:8]}  relay: the fix nobody merged" in out, True)
    check("the docs-only commit is not listed", "docs only" in out, False)
    check("the cherry-equivalent commit is not listed", picked[:8] in out, False)
    check("exactly one commit blocks", "1 relay commit(s)" in out, True)

    rc, out = run(base, f"# reviewed\n{fix[:8]} declined DECISIONS D-1011 test\n")
    check("the same commit, listed, passes", rc, 0)

    rc, out = run(base, f"{fix[:8]} maybe not sure\n")
    check("an unknown verdict fails closed", (rc, "unreadable lines" in out), (1, True))
    rc, out = run(base, f"{fix[:8]} a\n")
    check("a verdict without a reason fails closed", rc, 1)

    git("checkout", "-q", "fix-branch", cwd=base)
    rc, out = run(base, "")
    check("a commit on HEAD (pushed to main by this deploy) does not block", rc, 0)

deploy = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
gate = deploy.find("lib/unmerged_fixes.py")
check("deploy-relay.sh runs the gate before the pre-deploy replay",
      0 < gate < deploy.find("ark_relay.features.selfcheck.replay"), True)
check("a failed gate exits the deploy", "exit 1" in deploy[gate:gate + 600], True)

if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
