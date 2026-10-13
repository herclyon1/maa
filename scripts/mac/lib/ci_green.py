#!/usr/bin/env python3
"""Deploy gate: the game-layer Windows job is green for the code being deployed.

`.github/workflows/gamesim-windows.yml` runs the relay's OK-WW overlay inside the real
OK-WW / ok-script on windows-latest (frame truth, scenarios, install cycle, the relay's
verdicts on the overlay's own log lines; gamesim design section 4). The Mac cannot run
it (ok-script imports pywin32 at module top), so the deploy asks GitHub instead:

  1. a run of that workflow on the exact commit being deployed concluded success -> pass.
     A rollback to an earlier, already-green commit passes the same way;
  2. a run on that commit is finished and none succeeded (red, cancelled, or a lane that
     crashed with 0xC000001D on some runners, U6/U7) -> stop, with each run's URL and the
     `gh run rerun --failed` command; never skipped;
  3. otherwise, a green run on another commit whose game-layer files (GAME_LAYER) are
     byte-identical to this one's counts (design section 4: "reuse an earlier green only if
     git diff --quiet <green>..HEAD shows no change in the game-layer paths"); this is what
     lets the deploy's own manifest commit, or a docs-only commit, through;
  4. otherwise, if the commit is on no remote branch, nothing can ever run on it -> stop
     and print the push command (the workflow runs on pushes to main and relay-*);
  5. otherwise wait for its run, polling every POLL_S, at most WAIT_S; then stop.

GitHub or Actions unreachable is a stop too (design: "If Actions is down or the run is
red, stop and print the run URL; never skip").

    python3 scripts/mac/lib/ci_green.py              # HEAD
    python3 scripts/mac/lib/ci_green.py --sha REV [--wait-s N]

Exit 0 = green; 1 = red, not pushed or still not done after WAIT_S; 2 = GitHub not answering.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKFLOW = "gamesim-windows.yml"
# What the Windows job reads: the relay (its overlay, okww_overlay, the verdict code the
# chain step runs, the fixtures and the gamesim tests), packaging/ (the install cycle runs
# legacy.py's uninstall) and the workflow itself. Not the files the deploy itself commits
# (manifest.json, RELEASE-NOTES.md, state/last-deployed-notes.sha1), which the job never reads.
GAME_LAYER = ("relay", "packaging", f".github/workflows/{WORKFLOW}",
              ":(exclude)relay/manifest.json", ":(exclude)relay/RELEASE-NOTES.md", ":(exclude)relay/state")
# The branches whose pushes run the workflow (gamesim-windows.yml `on.push.branches`).
RUN_BRANCHES = ("main", "relay-", "gamesim-ci-")
# measured: the 58-job runs on 10-13 took 7.3 min (38406795391) and 9.6 min (38404775023)
# from creation to the last update (gh run list createdAt..updatedAt); 15 min is the
# design's bound (section 4, "Wait up to about 15 min (expected 6-10)") and 1.5x the slowest.
WAIT_S = 900
# One gh call per poll; 30 polls at most in WAIT_S. The jobs' own steps take minutes
# (measured: installed lane 1 min 40 s to 2 min 19 s, run 38380531733), so 30 s adds little.
POLL_S = 30
GREEN_SCAN = 100            # how many recent green runs to try for an identical game layer


class Unreachable(Exception):
    """gh or git did not answer; the gate stops."""


def sh(*cmd: str) -> "tuple[int, str]":
    p = subprocess.run(list(cmd), cwd=ROOT, capture_output=True, text=True, check=False)
    return p.returncode, p.stdout + (p.stderr if p.returncode else "")


def gh_json(*args: str):
    rc, out = sh("gh", *args)
    if rc != 0:
        raise Unreachable(f"gh {' '.join(args[:3])}: {out.strip()[:300]}")
    try:
        return json.loads(out)
    except ValueError as exc:
        raise Unreachable(f"gh {' '.join(args[:3])}: not JSON ({exc})") from exc


def runs_for(sha: str) -> list:
    return gh_json("run", "list", "--workflow", WORKFLOW, "--commit", sha, "--limit", "20",
                   "--json", "databaseId,status,conclusion,url,headBranch,headSha,event")


def recent_greens() -> list:
    return gh_json("run", "list", "--workflow", WORKFLOW, "--status", "success", "--limit", str(GREEN_SCAN),
                   "--json", "databaseId,url,headSha,headBranch")


def same_game_layer(a: str, b: str) -> bool:
    """True when commit a is here and its game-layer files equal b's."""
    if sh("git", "cat-file", "-e", f"{a}^{{commit}}")[0] != 0:
        return False
    return sh("git", "diff", "--quiet", a, b, "--", *GAME_LAYER)[0] == 0


def on_run_branch(sha: str) -> list:
    """Remote branches holding sha whose pushes run the workflow."""
    rc, out = sh("git", "branch", "-r", "--contains", sha, "--format=%(refname:short)")
    if rc != 0:
        raise Unreachable(f"git branch -r --contains {sha[:12]}: {out.strip()[:200]}")
    names = [ln.strip().split("/", 1)[-1] for ln in out.splitlines() if ln.strip()]
    return [n for n in names if n == "main" or n.startswith(RUN_BRANCHES[1:])]


def decide(sha: str, runs: list, greens: list, pushed: "list | None", same=None) -> "tuple[str, str]":
    """('pass' | 'stop' | 'wait', what to print). `pushed` None = not asked yet."""
    same = same or same_game_layer
    ok = [r for r in runs if r.get("conclusion") == "success"]
    if ok:
        return "pass", f"gamesim-windows green on {sha[:12]}: {ok[0]['url']}"
    pending = [r for r in runs if r.get("status") != "completed"]
    if runs and not pending:
        lines = [f"gamesim-windows is not green on {sha[:12]}; deploy stopped:"]
        lines += [f"  {r.get('conclusion')}: {r['url']} (branch {r.get('headBranch')})" for r in runs]
        lines.append("  A lane that crashed with 0xC000001D (illegal instruction, some runners) is a "
                     f"runner fault: gh run rerun {runs[0]['databaseId']} --failed, then deploy again. "
                     "Anything else: fix it first.")
        return "stop", "\n".join(lines)
    for g in greens:
        if g.get("headSha") and g["headSha"] != sha and same(g["headSha"], sha):
            return "pass", (f"gamesim-windows green on {g['headSha'][:12]} ({g['url']}), whose game-layer "
                            f"files equal {sha[:12]}'s ({' '.join(GAME_LAYER[:3])}, without the deploy's own files)")
    if pending:
        return "wait", f"gamesim-windows running on {sha[:12]}: {pending[0]['url']}"
    if pushed is not None and not pushed:
        return "stop", (f"{sha[:12]} is on no remote branch the workflow runs on (main, relay-*), so no "
                        f"gamesim-windows run can exist for it; deploy stopped. Push it first, e.g.\n"
                        f"  git push origin {sha}:refs/heads/main     (or :refs/heads/relay-<name>)\n"
                        f"then deploy again (the run takes 6-10 min).")
    return "wait", f"no gamesim-windows run on {sha[:12]} yet (pushed to {', '.join(pushed or [])})"


def gate(sha: str, wait_s: int, poll_s: int, clock=time.monotonic, sleep=time.sleep) -> int:
    deadline = clock() + wait_s
    pushed = None
    last = ""
    while True:
        try:
            runs = runs_for(sha)
            greens = [] if any(r.get("conclusion") == "success" for r in runs) else recent_greens()
            if not runs and pushed is None:
                pushed = on_run_branch(sha)
        except Unreachable as exc:
            print(f"GitHub did not answer, so gamesim-windows cannot be checked; deploy stopped: {exc}")
            return 2
        verdict, msg = decide(sha, runs, greens, pushed)
        if verdict != "wait":
            print(msg)
            return 0 if verdict == "pass" else 1
        if msg != last:
            print(msg, flush=True)
            last = msg
        if clock() >= deadline:
            print(f"gamesim-windows still not done on {sha[:12]} after {wait_s // 60} min; deploy stopped. "
                  f"Deploy again once it is green.")
            return 1
        sleep(poll_s)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", default="HEAD")
    ap.add_argument("--wait-s", type=int, default=WAIT_S)
    a = ap.parse_args(argv)
    rc, out = sh("git", "rev-parse", "--verify", f"{a.sha}^{{commit}}")
    if rc != 0:
        print(f"not a commit: {a.sha}")
        return 1
    return gate(out.strip(), a.wait_s, POLL_S)


if __name__ == "__main__":
    sys.exit(main())
