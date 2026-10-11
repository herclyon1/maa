"""lint-repo.sh item 23: a new timing / retry / threshold number has to name its source.

On 10-11 the post-deploy wait was a flat 120 s nobody had measured (22c925b8); c76d94a5
replaced it with the measured 22 s and wrote the measurement above it. Checked here on a
temporary git repo whose origin/main is the baseline commit:
  - an added WATCH_S="${WATCH_S:-120}" with no source fails, by file:line;
  - the same with a "Measured: ..." comment above it passes, as do a doc URL and his words
    with the time on the next line; the 22c925b8 comment (an incident time and a quoted log
    line four lines apart) does not count;
  - unchanged old lines (sleep 1, sleep 5) are never judged, nor relay/tests/, comment
    lines, numbers <= 1, or a variable in place of a literal;
  - a line committed on the branch and an untracked new file are judged too;
  - with no origin/main the item skips instead of failing;
  - lint-repo.sh runs it outside the LINT_SKIP_TESTS block.
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


ns = load("num_source", ROOT / "scripts/mac/lib/num_source.py")
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


G = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def git(*a, cwd):
    return subprocess.run([*G, *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


def write(base: Path, rel: str, text: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def run(base: Path) -> "tuple[int, str]":
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ns.main(["--root", str(base)])
    return rc, buf.getvalue()


OLD = 'echo start\nsleep 1\nsleep 5\necho done\n'


def deploy(*middle: str) -> str:
    """The baseline script with lines inserted after `sleep 5` (new lines 4.. )."""
    return 'echo start\nsleep 1\nsleep 5\n' + "".join(m + "\n" for m in middle) + 'echo done\n'


# The patterns, one line at a time.
for line, want in [
    ('WATCH_S="${WATCH_S:-120}"', "WATCH_S = 120"),
    ("CRASH_GAP_S = 22", "CRASH_GAP_S = 22"),
    ("RETRY_LIMIT = 5", "RETRY_LIMIT = 5"),
    ("MAX_TRIES: int = 4", "MAX_TRIES = 4"),
    ("sleep 30", "sleep N, N = 30"),
    ("    time.sleep(2.5)", "sleep(N), N = 2.5"),
    ("r = subprocess.run(cmd, timeout=60)", "timeout=N, N = 60"),
    ("ssh -o ConnectTimeout=10 host", "timeout=N, N = 10"),
    ("winrun.sh --timeout 600 x.py", "--timeout N, N = 600"),
    ("curl --max-time 15 url", "--timeout N, N = 15"),
    ('sleep "${POLL_S:-3}"', "POLL_S = 3"),
    ("sleep 1", None),
    ("time.sleep(0.5)", None),
    ("RETRIES = 1", None),
    ("timeout=WAIT_S", None),
    ("QUIET_S = CRASH_GAP_S + POLL_S", None),
    ("COUNT = 40", None),
    ('print(f"  {ln[:120]}")', None),
    ("x = f(a)  # sleep 30 before retrying, see 10-11", None),
]:
    check(f"rule for {line.strip()!r}", ns.offence(line), want)

with tempfile.TemporaryDirectory() as td:
    base = Path(td) / "repo"
    base.mkdir()
    git("init", "-q", "-b", "main", cwd=base)
    write(base, "scripts/mac/deploy.sh", OLD)
    write(base, "relay/tests/test_x.py", "x = 1\n")
    git("add", "-A", cwd=base)
    git("commit", "-qm", "baseline", cwd=base)

    rc, out = run(base)
    check("no origin/main: skipped, not failed", (rc, "skipped" in out), (0, True))

    git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=base)
    check("nothing added: passes", run(base)[0], 0)

    write(base, "scripts/mac/deploy.sh", deploy('WATCH_S="${WATCH_S:-120}"'))
    rc, out = run(base)
    check("added WATCH_S 120 with no source: fails by file:line",
          (rc, "scripts/mac/deploy.sh:4: WATCH_S=" in out), (1, True))
    check("old sleep 1 / sleep 5 are not judged",
          (":2:" in out, ":3:" in out, "sleep" in out), (False, False, False))

    write(base, "scripts/mac/deploy.sh", deploy(
        "# How long to watch. Measured: crash loops restart 17-22 s apart (relay.log, 10-11).",
        'WATCH_S="${WATCH_S:-120}"'))
    check("same line under a Measured: comment passes", run(base)[0], 0)

    write(base, "scripts/mac/deploy.sh", deploy(
        "# Docs: https://learn.microsoft.com/windows/win32/services/service-control-manager",
        "# say the SCM waits 30 s for a service to start.",
        "",
        "WAIT_S=30"))
    check("a doc URL within the 6 lines above passes", run(base)[0], 0)

    write(base, "scripts/mac/deploy.sh", deploy(
        "# The user, 10-11 19:14:",
        "# 「下次是一百二十秒」 - so this is his number, not ours.",
        "WAIT_S=120"))
    check("his words with the time on the next line pass", run(base)[0], 0)

    write(base, "scripts/mac/deploy.sh", deploy(
        "# 2026-10-10 16:27 a deploy left a relay that crashed a few seconds after every",
        "# start, and this script printed green. So before COS gets this version:",
        "# two minutes of watching. A restart, a self-check that is not all green, or",
        "# no 「已挂上 AUTO-MAS 进程句柄」 puts the previous version back by itself.",
        "# 验收 decided this.",
        'WATCH_S="${WATCH_S:-120}"'))
    rc, out = run(base)
    check("the 22c925b8 comment (time and quoted log line apart) does not count",
          (rc, "deploy.sh:9:" in out), (1, True))

    write(base, "scripts/mac/deploy.sh", deploy(
        "# Measured too long ago to matter:",
        "a", "b", "c", "d", "e", "f",
        "WAIT_S=120"))
    check("a source 7 lines up is out of reach", run(base)[0], 1)

    write(base, "scripts/mac/deploy.sh", deploy("# sleep 30", "sleep 1", "sleep $WAIT_S"))
    write(base, "relay/tests/test_x.py", "x = 1\ntime.sleep(30)\n")
    check("comment lines, numbers <= 1, variables, relay/tests/: not judged", run(base)[0], 0)

    git("add", "-A", cwd=base)
    git("commit", "-qm", "branch work", cwd=base)
    write(base, "scripts/mac/deploy.sh", deploy("sleep 5"))
    git("commit", "-qam", "branch work 2", cwd=base)
    rc, out = run(base)
    check("a line committed on the branch is judged against the merge-base",
          (rc, "scripts/mac/deploy.sh:4: sleep 5" in out), (1, True))

    write(base, "scripts/mac/deploy.sh", OLD)
    write(base, "relay/ark_relay/new.py", '"""New."""\nRETRY_LIMIT = 5\n')
    rc, out = run(base)
    check("an untracked new file is judged whole",
          (rc, "relay/ark_relay/new.py:2: RETRY_LIMIT = 5" in out), (1, True))

lint = (ROOT / "scripts/mac/lint-repo.sh").read_text(encoding="utf-8")
skip_end = lint.index("\nfi\n", lint.index('if [ -n "${LINT_SKIP_TESTS:-}" ]'))
check("lint-repo.sh runs num_source.py, after the LINT_SKIP_TESTS block",
      lint.find("lib/num_source.py") > skip_end, True)

if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
