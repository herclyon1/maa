"""deploy-relay.sh step 0.9: no deploy without a green game-layer Windows run (gamesim U15).

The game-layer harness (.github/workflows/gamesim-windows.yml, relay/tests/gamesim/) runs the
OK-WW overlay inside the real OK-WW on windows-latest; until 10-13 nothing tied a deploy to
it, and it ran only on gamesim-ci-* pushes. Checked here, with gh and the clock faked (no
network):
  - the workflow runs on pushes to main and relay-* (design section 4), and deploy-relay.sh
    runs scripts/mac/lib/ci_green.py after the dry-run exit and before step 1, stopping on
    its failure;
  - a green run on the exact commit passes (also a rollback to an old green commit);
  - finished runs with none green stop, naming each URL and the rerun command;
  - a running run is waited for, and passes when it turns green; still running after
    WAIT_S stops;
  - no run and the commit on no remote branch stops at once with the push command;
  - a green commit with the same game-layer files passes (the deploy's manifest commit, a
    docs-only commit); one that differs in relay/ or packaging/ does not;
  - gh failing stops with exit 2, never passes.
"""
import contextlib
import importlib.util
import io
import os
import re
import stat
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


print("[wiring: triggers and the deploy step]")
wf = (ROOT / ".github/workflows/gamesim-windows.yml").read_text(encoding="utf-8")
on = re.search(r"\non:\n(.*?)\n(?:\S)", wf, re.S)
branches = re.findall(r"- '([^']+)'", on.group(1)) if on else []
check("gamesim-windows runs on pushes to main and relay-*", ("main" in branches, "relay-*" in branches), (True, True))
deploy = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
dry, gate_at, step1 = (deploy.find('if [ "$DRY_RUN" = 1 ]; then\n  echo "✅ dry run'),
                       deploy.find("scripts/mac/lib/ci_green.py\""), deploy.find('echo "▶ 1/5'))
check("deploy-relay.sh runs ci_green.py after the dry-run exit, before step 1", 0 < dry < gate_at < step1, True)
block = deploy[gate_at:step1]
check("and stops the deploy when it fails", ("if ! python3" in deploy[gate_at - 200:gate_at], "exit 16" in block),
      (True, True))

path = ROOT / "scripts/mac/lib/ci_green.py"
if not path.is_file():
    check("scripts/mac/lib/ci_green.py exists", False, True)
    print("\nFAILED: " + "; ".join(fails))
    sys.exit(1)
spec = importlib.util.spec_from_file_location("ci_green", path)
cg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cg)

SHA = "a" * 40
GREEN = {"databaseId": 1, "status": "completed", "conclusion": "success", "url": "u/1", "headBranch": "main"}
RED = {"databaseId": 2, "status": "completed", "conclusion": "failure", "url": "u/2", "headBranch": "main"}
RUNNING = {"databaseId": 3, "status": "in_progress", "conclusion": "", "url": "u/3", "headBranch": "relay-x"}


def run_gate(script, pushed=("main",), greens=(), same=lambda a, b: False, wait_s=90, poll_s=30):
    """gate() over a script of runs_for answers (one list per poll); returns (rc, output, polls)."""
    t = [0.0]
    calls = []

    def runs_for(sha):
        calls.append(sha)
        return script[min(len(calls), len(script)) - 1]
    saved = (cg.runs_for, cg.recent_greens, cg.on_run_branch, cg.same_game_layer)
    cg.runs_for, cg.recent_greens, cg.on_run_branch = runs_for, lambda: list(greens), lambda sha: list(pushed)
    cg.same_game_layer = same
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = cg.gate(SHA, wait_s, poll_s, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    finally:
        cg.runs_for, cg.recent_greens, cg.on_run_branch, cg.same_game_layer = saved
    return rc, out.getvalue(), len(calls)


print("[the exact commit]")
rc, out, _ = run_gate([[GREEN]])
check("green on this commit: pass, URL printed", (rc, "u/1" in out), (0, True))
rc, out, _ = run_gate([[RED, GREEN]])
check("one green among reruns on other branches: pass", rc, 0)
rc, out, _ = run_gate([[RED]])
check("red: stop with the URL and the rerun command", (rc, "u/2" in out, "gh run rerun 2 --failed" in out), (1, True, True))
rc, out, _ = run_gate([[{**RED, "conclusion": "cancelled"}]])
check("cancelled: stop", rc, 1)
rc, out, polls = run_gate([[RUNNING], [RUNNING], [GREEN]])
check("running, then green: waited, then pass", (rc, polls), (0, 3))
rc, out, polls = run_gate([[RUNNING]], wait_s=90, poll_s=30)
check("still running after WAIT_S: stop, never pass", (rc, "still not done" in out, polls), (1, True, 4))

print("[no run on the commit]")
rc, out, polls = run_gate([[]], pushed=())
check("on no remote branch: stop at once with the push command",
      (rc, polls, "git push origin" in out), (1, 1, True))
rc, out, polls = run_gate([[], [RUNNING], [GREEN]], pushed=("main",))
check("pushed, run not created yet: waited, then pass", (rc, polls), (0, 3))
other = {"databaseId": 9, "url": "u/9", "headSha": "b" * 40, "headBranch": "gamesim-ci-x"}
rc, out, _ = run_gate([[]], pushed=(), greens=[other], same=lambda a, b: a == "b" * 40 and b == SHA)
check("a green commit with the same game-layer files: pass, naming it", (rc, "u/9" in out), (0, True))
rc, out, _ = run_gate([[RED]], greens=[other], same=lambda a, b: True)
check("but a red run on this very commit still stops", rc, 1)

print("[same game layer, on a real git history]")
G = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def git(*a, cwd):
    return subprocess.run([*G, *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def commit(base, rel, text):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    git("add", "-A", cwd=base)
    git("commit", "-qm", rel, cwd=base)
    return git("rev-parse", "HEAD", cwd=base)


with tempfile.TemporaryDirectory() as d:
    base = Path(d)
    git("init", "-q", "-b", "main", cwd=base)
    green = commit(base, "relay/ark_relay/a.py", "x = 1\n")
    docs = commit(base, "docs/X.md", "doc\n")
    commit(base, "relay/RELEASE-NOTES.md", "notes\n")
    manifest = commit(base, "relay/manifest.json", "{}\n")
    relay = commit(base, "relay/ark_relay/a.py", "x = 2\n")
    pkg = commit(base, "packaging/legacy.py", "y = 1\n")
    wfc = commit(base, ".github/workflows/gamesim-windows.yml", "on: {}\n")
    saved_root = cg.ROOT
    cg.ROOT = base
    try:
        check("a docs-only and the deploy's own commits keep the game layer",
              (cg.same_game_layer(green, docs), cg.same_game_layer(green, manifest)), (True, True))
        check("a relay/ change does not", cg.same_game_layer(green, relay), False)
        check("packaging/ and the workflow file count too",
              (cg.same_game_layer(relay, pkg), cg.same_game_layer(pkg, wfc)), (False, False))
        check("a commit that is not here is never the same", cg.same_game_layer("c" * 40, green), False)
    finally:
        cg.ROOT = saved_root

print("[gh not answering]")
with tempfile.TemporaryDirectory() as d:
    fake = Path(d) / "gh"
    fake.write_text("#!/bin/sh\necho 'error connecting to api.github.com' >&2\nexit 1\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    old_path = os.environ["PATH"]
    os.environ["PATH"] = f"{d}{os.pathsep}{old_path}"
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = cg.gate(SHA, 60, 30, clock=lambda: 0.0, sleep=lambda s: None)
    finally:
        os.environ["PATH"] = old_path
    check("exit 2, said, never a pass", (rc, "GitHub did not answer" in out.getvalue()), (2, True))

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
