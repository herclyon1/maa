"""scripts/mac/order.sh writes the inbox to main only.

2026-10-10 03:0x a ``--clear`` run from a worktree on branch acc-yw-manual-1009
ended in ``git push -q origin HEAD``: the inbox commit (d47c1998) went to that
branch, and main - the one the relay reads - never got it. The script now stops
before writing anything unless the checkout sits exactly on origin/main, commits
only queue/config.json, and pushes ``HEAD:main``.

Each case runs the real script in a throwaway clone of a throwaway bare repo.
The stub ``ark_relay`` there has no ``evidence`` module and there is no
purge-cdn.py, so nothing after the push can reach COS or the CDN; the script
ends non-zero there, after the part under test.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mac" / "order.sh"

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def setup(tmp):
    origin, work = tmp / "origin.git", tmp / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "t")
    (work / "scripts" / "mac").mkdir(parents=True)
    shutil.copy(SCRIPT, work / "scripts" / "mac" / "order.sh")
    (work / "relay" / "ark_relay").mkdir(parents=True)
    (work / "relay" / "ark_relay" / "__init__.py").write_text("")
    (work / "relay" / "ark_relay" / "features" / "phone" / "commands.py").write_text("ALLOWED = {'skip_shutdown': None}\n")
    (work / "queue").mkdir()
    (work / "queue" / "config.json").write_text(json.dumps(
        {"version": 1, "name": "空（安全状态）", "note": "", "commands": []}, ensure_ascii=False) + "\n")
    git(work, "symbolic-ref", "HEAD", "refs/heads/main")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "init")
    git(work, "push", "-q", "origin", "main")
    return origin, work


def run(work, tmp, *args):
    env = dict(os.environ, HOME=str(tmp / "home"))
    (tmp / "home").mkdir(exist_ok=True)
    return subprocess.run(["bash", str(work / "scripts" / "mac" / "order.sh"), *args],
                          capture_output=True, text=True, env=env, timeout=60)


def origin_branches(origin):
    return sorted(git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())


print("[a branch with commits of its own: the 10-10 03:0x case]")
with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    origin, work = setup(tmp)
    main_before = git(origin, "rev-parse", "main")
    git(work, "checkout", "-q", "-b", "acc-yw-manual-1009")
    (work / "notes.txt").write_text("side work\n")
    git(work, "add", "notes.txt")
    git(work, "commit", "-q", "-m", "side work")
    box_before = (work / "queue" / "config.json").read_text()
    r = run(work, tmp, "--clear")
    check("exits non-zero", r.returncode != 0, True)
    check("says why", "not at origin/main" in r.stderr, True)
    check("inbox file untouched", (work / "queue" / "config.json").read_text() == box_before, True)
    check("origin main unchanged", git(origin, "rev-parse", "main"), main_before)
    check("no branch pushed to origin", origin_branches(origin), ["main"])

print("[a branch sitting on origin/main, with another file staged]")
with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    origin, work = setup(tmp)
    git(work, "checkout", "-q", "-b", "acc-other")
    (work / "staged-by-someone.txt").write_text("not mine\n")
    git(work, "add", "staged-by-someone.txt")
    r = run(work, tmp, "--clear")
    check("got past the guard", "not at origin/main" in r.stderr, False)
    check("pushed", "已推上 GitHub" in r.stdout, True)
    check("only main on origin", origin_branches(origin), ["main"])
    files = git(origin, "show", "--name-only", "--format=", "main").split()
    check("the commit holds the inbox only", files, ["queue/config.json"])
    check("origin main has the new version", json.loads(git(origin, "show", "main:queue/config.json"))["version"] > 1, True)
    check("the staged file stays staged, not committed", git(work, "diff", "--cached", "--name-only"), "staged-by-someone.txt")

print("[--show reads without a fetch or a check]")
with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    origin, work = setup(tmp)
    git(work, "checkout", "-q", "-b", "elsewhere")
    (work / "x.txt").write_text("x\n")
    git(work, "add", "x.txt")
    git(work, "commit", "-q", "-m", "x")
    r = run(work, tmp, "--show")
    check("--show still works off main", r.returncode, 0)

if fails:
    print(f"✗ {len(fails)} failed: {fails}")
    sys.exit(1)
print("✓ all passed")
