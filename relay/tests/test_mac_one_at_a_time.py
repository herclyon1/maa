"""Nothing we run on the Mac starts programs many at a time.

The Mac runs a macOS 27.2 beta whose kernel locks itself when a background-priority process
execs while it updates its own importance (09-23 04:19 panic, symbolicated in
the board write-up of the 09-23 04:19 panic: the locking grep was started by lint-repo.sh's `xargs -P 8`).
The Mac froze the same way 10-10 01:06 and 03:09, and 10-14 19:52 while a lint-repo.sh run
(started 19:50:33) was still going. Running the tests and checks one at a time on the Mac is
slower (437 relay tests: 144 s on 10-14) but keeps the machine up. CI runners are not this Mac
and keep their parallelism.

Checks:
  * no shell script under scripts/mac/ hands xargs a literal parallelism above 1;
  * deploy-relay.sh runs its tests TEST_JOBS at a time with TEST_JOBS=1 on Darwin (CI sources
    the same block);
  * every Python file the Mac runs that starts programs from a thread or process pool caps the
    pool at 1 on Darwin (or is Mac-only and uses 1), except those listed in FORK_ONLY, whose
    workers fork and never exec.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
fails = []


def check(name, got, want):
    ok = got == want
    print(("  ok  " if ok else "  FAIL") + f" {name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(name)


# Pools whose workers are forked copies that never exec (no new program is started), and pools whose
# tasks start no program at all (the file starts programs elsewhere, one at a time). Each entry is
# the text that shows it; the check fails if that text goes away.
FORK_ONLY = {
    "scripts/mac/relay-judge-diff.py": 'mp_context=multiprocessing.get_context("fork")',
    "relay/tests/test_daysim_clock.py": "fut = pool.submit(lambda: (time.sleep(3), simclock.now() - base)[1])",
}

# 1. shell: xargs -P <n> with n > 1 under scripts/mac/
bad_sh = []
for p in sorted((ROOT / "scripts/mac").rglob("*.sh")):
    for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for m in re.finditer(r"xargs\b[^|;&]*?-P\s*(\d+)", line):
            if int(m.group(1)) > 1:
                bad_sh.append(f"{p.relative_to(ROOT)}:{i}")
check("no `xargs -P <n>` above 1 in scripts/mac", bad_sh, [])

# 2. deploy-relay.sh: TEST_JOBS=1 on Darwin, and xargs uses it
dep = (ROOT / "scripts/mac/deploy-relay.sh").read_text()
check("deploy-relay.sh sets TEST_JOBS=1 on Darwin",
      bool(re.search(r'if \[ "\$\(uname -s\)" = Darwin \]; then TEST_JOBS=1;', dep)), True)
check("deploy-relay.sh runs xargs with -P \"$TEST_JOBS\"",
      'xargs -P "$TEST_JOBS"' in dep and not re.search(r"xargs -P [2-9]", dep), True)
block = re.search(r"^# >>> test timing$(.*?)^# <<< test timing$", dep, re.S | re.M).group(1)
check("TEST_JOBS is inside the test timing block CI sources", "TEST_JOBS=1" in block, True)

# 3. python: pools in files that start programs
POOL = re.compile(r"(ThreadPoolExecutor|ProcessPoolExecutor)\(")
STARTS = re.compile(r"subprocess\.|os\.system\(|Popen\(")
DARWIN_CAP = re.compile(r'sys\.platform\s*==\s*"darwin"|PoolExecutor\(1\)|max_workers=1\b')
bad_py = []
files = [*sorted((ROOT / "scripts/mac").rglob("*.py")), *sorted((ROOT / "relay/tests").glob("test_*.py"))]
for p in files:
    rel = str(p.relative_to(ROOT))
    if p.name == Path(__file__).name:
        continue
    text = p.read_text(errors="replace")
    if not POOL.search(text):
        continue
    if rel in FORK_ONLY:
        check(f"{rel} still forks without exec", FORK_ONLY[rel] in text, True)
        continue
    # test_replay.py's judges are spawned Python processes: a spawn is an exec.
    starts = STARTS.search(text) or "ProcessPoolExecutor(" in text
    if starts and not DARWIN_CAP.search(text):
        bad_py.append(rel)
check("pools that start programs are capped at 1 on Darwin", bad_py, [])

# 4. wait_not_background: waits while ps shows priority 4 (background), returns when it rises,
#    returns at once when not background or not macOS. Driven with a fake ps / uname on PATH.

def run_wait(src, pri_seq, uname="Darwin"):
    with tempfile.TemporaryDirectory() as d:
        state = os.path.join(d, "n")
        open(state, "w").write("0")
        seq = " ".join(str(x) for x in pri_seq)
        with open(os.path.join(d, "ps"), "w") as fh:
            fh.write(f"""#!/bin/bash
n=$(cat {state}); set -- {seq}; shift $n 2>/dev/null; echo "${{1:-31}}"; echo $((n+1)) > {state}
""")
        with open(os.path.join(d, "uname"), "w") as fh:
            fh.write(f"#!/bin/bash\necho {uname}\n")
        for x in ("ps", "uname"):
            os.chmod(os.path.join(d, x), 0o755)
        env = {**os.environ, "PATH": d + ":" + os.environ["PATH"], "WAIT_BG_POLL_S": "0"}
        r = subprocess.run(["bash", "-c", src + "\nwait_not_background; echo done"], capture_output=True,
                           text=True, env=env, timeout=20)
        calls = int(open(state).read())
        return r.stdout.strip(), ("waiting" in r.stderr), calls


lib = (ROOT / "scripts/mac/lib/wait-not-background.sh").read_text()
fn = re.search(r"^wait_not_background\(\) \{.*?^\}", dep, re.S | re.M).group(0)
for label, src in (("lib", lib), ("deploy block", fn)):
    check(f"{label}: background (4, 4, 31) waits, says so once, then returns", run_wait(src, [4, 4, 31]), ("done", True, 3))
    check(f"{label}: foreground (31) returns at once, silent", run_wait(src, [31]), ("done", False, 1))
    check(f"{label}: not macOS returns without asking ps", run_wait(src, [4], uname="Linux"), ("done", False, 0))
lint = (ROOT / "scripts/mac/lint-repo.sh").read_text()
check("lint-repo.sh waits before every relay test",
      bool(re.search(r"for f in relay/tests/test_\*\.py; do\n\s+wait_not_background\n", lint)), True)
check("deploy-relay.sh run_one_test waits first",
      bool(re.search(r"run_one_test\(\) \{\n[^\n]*\n\s+wait_not_background\n", dep)), True)

# 5. launchd jobs we install run at Standard, not Background (darwin background priority).
for p in sorted((ROOT / "scripts/mac/launchd").glob("*.plist")):
    t = p.read_text()
    m = re.search(r"<key>ProcessType</key>\s*<string>(\w+)</string>", t)
    check(f"{p.name} is not a Background job", (m.group(1) if m else "unset") != "Background", True)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
