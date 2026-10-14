"""Nothing we run on the Mac starts programs in bulk while macOS runs it at background priority.

The Mac runs a macOS 27.2 beta whose kernel locks itself when a background-priority process
execs while it updates its own importance (09-23 04:19 panic, symbolicated in
the board write-up of the 09-23 04:19 panic: the locking grep was started by lint-repo.sh's `xargs -P 8`).
The Mac froze the same way 10-10 01:06 and 03:09, and 10-14 19:52 while a lint-repo.sh run
(started 19:50:33) was still going. macOS puts every other app's processes, Claude's included, at
background priority while a game is in front (runningboardd: "Set darwin role to: Background" each
time Game Mode turned on, 10-14). So the runners keep starting tests in parallel, but each start
first waits while the run is at background priority.

Checks:
  * every `xargs -P` above 1 under scripts/mac/ starts a function whose first step is
    wait_not_background (deploy-relay.sh defines it inside the block CI sources);
  * every Python file that starts programs from a thread or process pool waits on
    getpriority(PRIO_DARWIN_PROCESS) first, except FORK_ONLY (forked workers that never exec);
  * the wait itself, with a fake ps; the priority read, live, without starting a program;
  * launchd jobs we install are not Background jobs.
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

# 1. shell: every xargs -P <n> above 1 under scripts/mac/ runs a function that waits first
FUNC = re.compile(r"^(\w+)\(\) \{\n(.*?)^\}", re.S | re.M)
bad_sh = []
for p in sorted((ROOT / "scripts/mac").rglob("*.sh")):
    text = p.read_text(errors="replace").replace("\r\n", "\n")
    funcs = {m.group(1): m.group(2) for m in FUNC.finditer(text)}
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for m in re.finditer(r"xargs\b[^|;&]*?-P\s*(\d+)[^|;&]*?bash -c '(\w+)", line):
            body = funcs.get(m.group(2), "")
            first = next((ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith(("local ", "#"))), "")
            if int(m.group(1)) > 1 and first != "wait_not_background":
                bad_sh.append(f"{p.relative_to(ROOT)}:{i} ({m.group(2)})")
        if re.search(r"xargs\b[^|;&]*?-P\s*([2-9]|\d\d)", line) and "bash -c '" not in line:
            bad_sh.append(f"{p.relative_to(ROOT)}:{i} (not a waiting function)")
check("every `xargs -P <n>` above 1 in scripts/mac starts a function that waits first", bad_sh, [])

# 2. deploy-relay.sh: the wait is inside the test timing block CI sources, and is exported
dep = (ROOT / "scripts/mac/deploy-relay.sh").read_text().replace("
", "
")
block = re.search(r"^# >>> test timing$(.*?)^# <<< test timing$", dep, re.S | re.M).group(1)
check("wait_not_background is defined in the block CI sources",
      bool(re.search(r"^wait_not_background\(\) \{", block, re.M)) and "export -f wait_not_background" in block, True)

# 3. python: pools in files that start programs wait before each start
POOL = re.compile(r"(ThreadPoolExecutor|ProcessPoolExecutor)\(")
STARTS = re.compile(r"subprocess\.|os\.system\(|Popen\(")
bad_py = []
files = [*sorted((ROOT / "scripts/mac").rglob("*.py")), *sorted((ROOT / "relay/tests").glob("test_*.py"))]
for p in files:
    rel = p.relative_to(ROOT).as_posix()
    if p.name == Path(__file__).name:
        continue
    text = p.read_text(errors="replace").replace("\r\n", "\n")
    if not POOL.search(text):
        continue
    if rel in FORK_ONLY:
        check(f"{rel} still forks without exec", FORK_ONLY[rel] in text, True)
        continue
    # test_replay.py's judges are spawned Python processes: a spawn is an exec.
    starts = STARTS.search(text) or "ProcessPoolExecutor(" in text
    if starts and not ("os.getpriority(os.PRIO_DARWIN_PROCESS, 0)" in text and text.count("_wait_not_background()") >= 1):
        bad_py.append(rel)
check("pools that start programs wait while at background priority", bad_py, [])

# 3b. live, without starting any program: what the Python waits key on. This process puts itself at
#     background priority, reads it back, and puts itself back.
if sys.platform == "darwin":
    before = os.getpriority(os.PRIO_DARWIN_PROCESS, 0)
    os.setpriority(os.PRIO_DARWIN_PROCESS, 0, os.PRIO_DARWIN_BG)
    during = os.getpriority(os.PRIO_DARWIN_PROCESS, 0)
    os.setpriority(os.PRIO_DARWIN_PROCESS, 0, 0)
    after = os.getpriority(os.PRIO_DARWIN_PROCESS, 0)
    check("getpriority(PRIO_DARWIN_PROCESS) reads 0 / 1 / 0 around background priority", (before, during, after), (0, 1, 0))

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


# The wait only matters on the Mac, and the fake ps / uname need a POSIX shell; on a CI runner
# (Windows / Linux) the text checks above still run, this section does not.
lib = (ROOT / "scripts/mac/lib/wait-not-background.sh").read_text().replace("
", "
")
fn = re.search(r"^wait_not_background\(\) \{.*?^\}", dep, re.S | re.M).group(0)
for label, src in ((("lib", lib), ("deploy block", fn)) if sys.platform == "darwin" else ()):
    check(f"{label}: background (4, 4, 31) waits, says so once, then returns", run_wait(src, [4, 4, 31]), ("done", True, 3))
    check(f"{label}: foreground (31) returns at once, silent", run_wait(src, [31]), ("done", False, 1))
    check(f"{label}: not macOS returns without asking ps", run_wait(src, [4], uname="Linux"), ("done", False, 0))
lint = (ROOT / "scripts/mac/lint-repo.sh").read_text().replace("
", "
")
check("lint-repo.sh lint_one_test waits first",
      bool(re.search(r"lint_one_test\(\) \{\n\s+local name out\n\s+wait_not_background\n", lint)), True)
check("deploy-relay.sh run_one_test waits first",
      bool(re.search(r"run_one_test\(\) \{\n[^\n]*\n\s+wait_not_background\n", dep)), True)

# 5. launchd jobs we install run at Standard, not Background (darwin background priority).
for p in sorted((ROOT / "scripts/mac/launchd").glob("*.plist")):
    t = p.read_text().replace("
", "
")
    m = re.search(r"<key>ProcessType</key>\s*<string>(\w+)</string>", t)
    check(f"{p.name} is not a Background job", (m.group(1) if m else "unset") != "Background", True)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
