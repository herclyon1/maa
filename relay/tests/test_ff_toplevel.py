"""scripts/mac/lib/ff-toplevel.sh: after a deploy pushes main, the shared top-level checkout follows.

On 10-11 the top-level checkout sat 359 commits behind origin/main and its estop.sh did not
know the installed relay, because no step ever moved it. deploy-relay.sh runs ff-toplevel.sh
after the push. Checked here, on temporary repositories (no network, nothing on the gaming
machine):
  - a top-level checkout with uncommitted changes is left alone (exit 0, says so);
  - one on another branch is left alone;
  - a clean one on main is fast-forwarded to origin/main;
  - deploy-relay.sh runs it after the push and cannot be stopped by it.

Until 2026-11-17 these checks were part of test_tool_refs.py, removed that day with the lint
tools it tested (scripts/mac/lib/tool_refs.py, parts_latest.py, tools_latest.py).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


with tempfile.TemporaryDirectory() as t:
    base = Path(t)
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]

    def git(*a, cwd):
        return subprocess.run([*g, *a], cwd=cwd, capture_output=True, text=True, check=True).stdout

    origin, top, wt = base / "origin.git", base / "top", base / "wt"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(top)], check=True, capture_output=True)
    git("checkout", "-q", "-b", "main", cwd=top)
    (top / "a.txt").write_text("1\n")
    git("add", "a.txt", cwd=top)
    git("commit", "-qm", "one", cwd=top)
    git("push", "-q", "origin", "main", cwd=top)
    git("worktree", "add", "-q", "-b", "work", str(wt), cwd=top)
    (wt / "a.txt").write_text("2\n")
    git("commit", "-qam", "two", cwd=wt)
    git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=wt)
    ff = str(ROOT / "scripts/mac/lib/ff-toplevel.sh")
    (top / "a.txt").write_text("dirty\n")
    r = subprocess.run([ff, str(wt)], capture_output=True, text=True)
    check("dirty top-level left alone, exit 0",
          (r.returncode, "uncommitted changes" in r.stdout, (top / "a.txt").read_text()),
          (0, True, "dirty\n"))
    git("checkout", "-q", "--", "a.txt", cwd=top)
    git("checkout", "-q", "-b", "side", cwd=top)
    r = subprocess.run([ff, str(wt)], capture_output=True, text=True)
    check("top-level on another branch left alone",
          (r.returncode, "not main" in r.stdout, git("rev-parse", "--abbrev-ref", "HEAD", cwd=top).strip()),
          (0, True, "side"))
    git("checkout", "-q", "main", cwd=top)
    r = subprocess.run([ff, str(wt)], capture_output=True, text=True)
    check("clean top-level on main fast-forwarded",
          (r.returncode, "fast-forwarded 1 commits" in r.stdout, (top / "a.txt").read_text()),
          (0, True, "2\n"))

dr = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
check("deploy fast-forwards the top-level checkout after the push, and ignores its exit",
      ('lib/ff-toplevel.sh" "$HERE/.." || true' in dr,
       dr.find("push -q origin HEAD:refs/heads/main") < dr.find("ff-toplevel.sh")),
      (True, True))

if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
