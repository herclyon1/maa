"""scripts/mac/disk-tidy.py removes exactly what its rules allow and refuses everything else.

A whole fake HOME is built in a temp dir: a repo with a bare origin and every kind of worktree
(merged / fresh / dirty / unmerged / in use / named by a live workflow / named by a tool /
locked / standing / outside the session zone / gone), Claude session tmp dirs (dead, running,
continued by a running one, fresh, reused by a hook, owning a live workflow journal; inside a
running session's scratchpad: idle / fresh / 5 h idle / open / worktree subdirs, subdirs named by a
running workflow's script or an agent's prompt, subdirs a tool names, and a big idle file), Xcode
DerivedData (also folders of it inside ~/Money/styl-work evidence), Gradle versions and transform
caches, swiftly versions, the one-off build outputs and the caches. The tool
runs as a subprocess against it, with stub `swiftly` / `uv` / `brew` / `go` / `xcrun` on PATH
that only record their arguments. Then: the dry run removes nothing and logs nothing, --apply
removes exactly the rule matches and logs one line each, the floor tier adds its rules, and
guard() refuses his files, CoreDevice, simulators, symlinks and - with the real lsof - a
directory a live process sits in.

Clock: the scratchpad rule counts ctime too (tar / cp -p / rsync -a keep old mtimes, never
ctime), and os.utime cannot set ctime back. So once built, every fixture's mtime is moved SHIFT
into the future and the tool runs with DISK_TIDY_NOW = real now + SHIFT: relative ages stay as
built, and every ctime reads SHIFT old. The "unpacked just now" case runs at the real clock.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay" / "tests"))
from _tmp import tmpdir  # noqa: E402

TOOL = ROOT / "scripts" / "mac" / "disk-tidy.py"
spec = importlib.util.spec_from_file_location("disk_tidy", TOOL)
dt = importlib.util.module_from_spec(spec)
sys.modules["disk_tidy"] = dt          # dataclasses look the module up while it loads
spec.loader.exec_module(dt)
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


BASE = tmpdir("disktidy-").resolve()
HOME = BASE / "home"
TMP_ROOT = BASE / "claude-501"
TDIR = BASE / "T"
BREW = BASE / "brew"
STUBS = BASE / "bin"
CALLS = BASE / "calls.log"
OPEN = BASE / "open-paths.txt"
PROCS = BASE / "procs.txt"
GIT_ENV = dict(os.environ, HOME=str(HOME), GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_NOSYSTEM="1")
SHIFT = 48 * 3600
U = {k: f"{n}0000000-0000-4000-8000-00000000000{n}" for n, k in enumerate(
    ["dead", "live", "pred", "fresh", "reused", "journal", "transcript", "cwd"], start=1)}


def sh(*args, cwd=None):
    r = subprocess.run([str(a) for a in args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{args}: {r.stderr}")
    return r.stdout


def write(p, text="x"):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def age(path, hours, now=None):
    """Set the mtime of path and everything below it to `hours` before now (default: the real
    clock, which shift_all() later moves with everything else)."""
    t = (now or time.time()) - hours * 3600
    for dirpath, dirnames, filenames in os.walk(path, topdown=False):
        for n in filenames + dirnames:
            os.utime(os.path.join(dirpath, n), (t, t), follow_symlinks=False)
    os.utime(path, (t, t), follow_symlinks=False)


def shift_all():
    """Move every mtime under BASE SHIFT into the future; returns the simulated clock."""
    now = time.time()
    for dirpath, dirnames, filenames in os.walk(BASE, topdown=False):
        for n in filenames + dirnames:
            p = os.path.join(dirpath, n)
            st = os.lstat(p)
            os.utime(p, (st.st_atime, st.st_mtime + SHIFT), follow_symlinks=False)
    return now + SHIFT


REPO = HOME / "Claude" / "maa-automation"
WT = REPO / ".claude" / "worktrees"


def add_wt(path, extra_commit=False):
    path = Path(path)
    sh("git", "-C", REPO, "worktree", "add", "-q", path, "-b", path.name, "origin/main")
    if extra_commit:
        write(path / "new.txt", "work")
        sh("git", "-C", path, "add", "new.txt")
        sh("git", "-C", path, "commit", "-qm", "unmerged work")
    return path


def age_wt(path, hours):
    age(path, hours)
    age(REPO / ".git" / "worktrees" / Path(path).name, hours)


def build():
    remote = BASE / "remote.git"
    sh("git", "init", "-q", "--bare", "-b", "main", remote)
    REPO.mkdir(parents=True)
    sh("git", "init", "-q", "-b", "main", REPO)
    write(REPO / ".gitignore", ".build/\n.swiftpm/\n.ruff_cache/\n")
    write(REPO / "a.txt", "a")
    sh("git", "-C", REPO, "add", ".")
    sh("git", "-C", REPO, "commit", "-qm", "init")
    sh("git", "-C", REPO, "remote", "add", "origin", remote)
    sh("git", "-C", REPO, "push", "-q", "origin", "main")
    sh("git", "-C", REPO, "fetch", "-q", "origin")

    for name in ("wt-old", "wt-new", "wt-dirty", "wt-cwd", "wt-journal", "wt-named", "wt-locked",
                 "wt-5h", "wt-gone"):
        add_wt(WT / name)
    add_wt(WT / "wt-unmerged", extra_commit=True)
    for p in (HOME / "Claude/maa-automation-sib", HOME / "Claude/maa-automation-data",
              HOME / "Claude/other-fix", HOME / "Money/styl-work/ds-relay-tree", HOME / "Money/other-tree"):
        add_wt(p)
    for name in ("wt-old", "wt-dirty", "wt-unmerged"):
        write(WT / name / ".build/out.o", "obj")
    write(WT / "wt-unmerged/.swiftpm/state", "s")
    write(WT / "wt-dirty/notes.txt", "uncommitted")
    sh("git", "-C", REPO, "worktree", "lock", WT / "wt-locked")
    sh("rm", "-rf", WT / "wt-gone")

    # Claude sessions: tmp dirs, the session registry, transcripts, a live workflow journal.
    proj = TMP_ROOT / "-Users-x"
    for sid in U.values():
        write(proj / sid / "scratchpad/f.txt")
    write(TMP_ROOT / "disk-tidy/inventory.md")
    write(HOME / ".claude/sessions/1.json", json.dumps({"pid": os.getpid(), "sessionId": U["live"]}))
    write(HOME / f".claude/projects/-Users-x/{U['live']}.jsonl",
          f'{{"m": "read the full transcript at: {HOME}/.claude/projects/-Users-x/{U["pred"]}.jsonl\\nContinue"}}\n')
    write(HOME / f".claude/projects/-Users-x/{U['transcript']}.jsonl", "{}\n")
    # Workflows, in the real layout (10-16 review: 81 journals on this Mac hold only type / key /
    # agentId / label / phase / result, never a prompt). A run's script lives under whichever
    # project dir the session started the workflow from; its agents' prompts open their
    # agent-*.jsonl. wf_1 is running, wf_2 is in a 5 h phase (journal idle, agents writing),
    # wf_0 finished 3 days ago and its script names sp-old.
    runs = HOME / f".claude/projects/-Users-x/{U['journal']}/subagents/workflows"
    scripts = HOME / f".claude/projects/-Users-y/{U['journal']}/workflows/scripts"
    spx = f"/tmp/claude-501/-Users-x/{U['live']}/scratchpad"
    for run in ("wf_0", "wf_1", "wf_2"):
        write(runs / run / "journal.jsonl",
              '{"type": "started", "key": "fix", "agentId": "a1", "label": "fix", "phase": "Fix"}\n'
              '{"type": "result", "key": "fix", "agentId": "a1", "result": "done"}\n')
    write(scripts / "fix-wf_1.js", f'const TREE = ".claude/worktrees/wt-journal";\n'
                                   f'const IN = "{spx}/sp-journal/";\n')
    write(runs / "wf_1/agent-a1.jsonl",
          '{"parentUuid": null, "type": "user", "message": {"content": "[harness] request"}}\n'
          f'{{"parentUuid": "p", "type": "user", "message": {{"content": "read {spx}/sp-prompt/in.txt"}}}}\n'
          '{"parentUuid": "q", "type": "attachment", "attachment": {}}\n'
          f'{{"parentUuid": "r", "type": "assistant", "message": {{"content": "ls {spx}/sp-old"}}}}\n')
    write(scripts / "long-wf_2.js", f'const IN = "{spx}/sp-longrun";\n')
    write(runs / "wf_2/agent-b1.jsonl", '{"parentUuid": null, "type": "user", "message": {}}\n')
    write(scripts / "done-wf_0.js", f'const IN = "{spx}/sp-old";\n')
    write(runs / "wf_0/agent-c1.jsonl", f'{{"parentUuid": null, "type": "user", "message": "{spx}/sp-old"}}\n')
    # A plain subagent (no workflow) that is still writing its transcript.
    write(HOME / f".claude/projects/-Users-x/{U['live']}/subagents/agent-d1.jsonl",
          f'{{"parentUuid": null, "type": "user", "message": {{"content": "use {spx}/sp-plain"}}}}\n')
    # 10-18: two map scripts named one folder (and one file) inside the acceptance session's
    # scratchpad, and the whole 11 GB scratchpad stayed. A reference keeps only the entry it names.
    write(HOME / ".claude/hooks/h.py",
          f'SRC = "/private/tmp/claude-501/-Users-x/{U["reused"]}/scratchpad/r-1.txt"\n'
          f'TREE = "{WT / "wt-named"}"\n'
          f"SCR = '/private/tmp/claude-501/-Users-x/{U['live']}/scratchpad/sp-named'\n"
          f"OUT = '/private/tmp/claude-501/-Users-x/{U['live']}/scratchpad/sp-ro/M4/oue.json'\n"
          f'DD = "{HOME}/Money/styl-work/evidence/named/dd"\n'
          'CMD = ["xcodebuild", "-derivedDataPath", dd]\n')    # a variable: names no folder "dd"

    dd = HOME / "Library/Developer/Xcode/DerivedData"
    write(dd / "Proj-old/Build/x")
    write(dd / "Proj-new/Build/x")
    write(dd / "ModuleCache.noindex/m")
    write(BREW / "Cellar/gradle/9.8.1_1/bin/gradle")      # a Homebrew revision suffix
    (BREW / "opt").mkdir(parents=True)
    os.symlink("../Cellar/gradle/9.8.1_1", BREW / "opt/gradle")
    for d in ("caches/9.8.0", "caches/9.8.1", "caches/9.8.1/transforms", "caches/modules-2", "daemon/9.8.0"):
        write(HOME / ".gradle" / d / "f")
    write(HOME / ".swiftly/config.json", json.dumps({"inUse": "6.4.1", "installedToolchains": ["6.4.1", "6.4.0"]}))
    for v in ("6.4.0", "6.4.1"):
        write(HOME / f"Library/Developer/Toolchains/swift-{v}-RELEASE.xctoolchain/usr/bin/swift")
    write(TDIR / "precheck-abc/f")
    app = HOME / "Claude/transit-app"
    write(app / ".gitignore", "build/\n")
    sh("git", "init", "-q", "-b", "main", app)
    sh("git", "-C", app, "add", ".gitignore")
    sh("git", "-C", app, "commit", "-qm", "init")
    write(app / "build/Release/x")
    write(HOME / "Money/styl-work/remote-ref/tools/bugexam/xcr-dd/Build/x")
    write(HOME / "Money/styl-work/BOARD/OPEN.md", "his board")
    # Xcode DerivedData folders left inside ~/Money/styl-work evidence (10-18 inventory, A5): the
    # folder goes, the screenshots beside it stay.
    ev = HOME / "Money/styl-work/evidence"
    for x in ("x", "named", "fresh", "deep/a/b"):
        write(ev / x / "dd/Build/Products/app")
        write(ev / x / "dd/Index.noindex/i")
        write(ev / x / "a.png", "png")
    write(ev / "y/dd/a.png", "png")                                      # no DerivedData signature
    write(ev / "y/dd/Build/b.png", "png")
    # A tool that builds into its own DerivedData by a relative path and reuses it (axdump.sh).
    tools = HOME / "Money/styl-work/remote-ref/tools"
    write(tools / "axd/axd.sh", 'xcodebuild test -derivedDataPath "$HERE/../axd-dd" -quiet\n')
    write(tools / "axd-dd/Build/Products/app")
    write(tools / "axd-dd/ModuleCache.noindex/m")
    write(HOME / "Documents/mine.txt", "his file")
    for c in (".cache/pyright-python/n", ".cache/uv/u", "Library/Caches/Homebrew/b", "Library/Caches/go-build/g"):
        write(HOME / c)

    # Everything old, except what must look fresh.
    for p in (HOME / ".gradle", HOME / "Library", HOME / ".cache", HOME / "Money/styl-work/remote-ref",
              HOME / "Money/styl-work/BOARD", HOME / "Money/styl-work/evidence", TDIR, app / "build",
              TMP_ROOT / "disk-tidy"):
        age(p, 72)
    age(HOME / "Money/styl-work/evidence/fresh/dd", 1)
    for sid in U.values():
        if sid != U["fresh"]:
            age(proj / sid, 72)
    age(runs / "wf_0", 72)
    age(runs / "wf_2/journal.jsonl", 5)
    for p in (WT / n for n in ("wt-old", "wt-dirty", "wt-cwd", "wt-journal", "wt-named", "wt-locked",
                               "wt-unmerged")):
        age_wt(p, 72)
    age_wt(WT / "wt-5h", 5)
    for p in ("Claude/maa-automation-sib", "Claude/maa-automation-data", "Claude/other-fix",
              "Money/styl-work/ds-relay-tree", "Money/other-tree"):
        age_wt(HOME / p, 72)
    write(dd / "Proj-new/Build/x", "fresh")

    # Inside a running session's scratchpad (10-16: the acceptance session ran for days and its
    # finished subagents' copies grew to 8.8 GB): created after the 72 h aging above.
    sp = proj / U["live"] / "scratchpad"
    for name in ("sp-old", "sp-open", "sp-journal", "sp-prompt", "sp-longrun", "sp-plain", "sp-gitlink",
                 "sp-named", "sp-ro/M4"):
        write(sp / name / "deep/f.txt")
        age(sp / name.split("/")[0], 72)
    write(sp / "sp-5h/f.txt")
    age(sp / "sp-5h", 5)
    write(sp / "sp-new/f.txt")
    write(sp / "sp-gitlink/.git", "gitdir: /elsewhere/.git/worktrees/x\n")    # a worktree of a repo
    age(sp / "sp-gitlink", 72)                                               # outside ~/Claude
    add_wt(sp / "sp-wt")
    age_wt(sp / "sp-wt", 72)
    with open(sp / "big.bin", "wb") as fh:
        fh.truncate(getattr(dt, "BIG_FILE_BYTES", 100 << 20) + 1)            # sparse
    age(sp / "big.bin", 72)
    write(sp / "small.log", "s")
    age(sp / "small.log", 72)
    write(proj / U["live"] / "tasks/a1.output", "o")                   # outside scratchpad/
    age(proj / U["live"] / "tasks", 72)

    STUBS.mkdir()
    for tool in ("uv", "brew", "go", "swiftly", "xcrun"):
        write(STUBS / tool, f"""#!/bin/sh
echo "{tool} $*" >> "{CALLS}"
if [ "{tool}" = swiftly ] && [ "$1" = uninstall ]; then
  rm -rf "$HOME/Library/Developer/Toolchains/swift-$2-RELEASE.xctoolchain"
fi
if [ "{tool}" = xcrun ] && [ "$3" = "-j" ]; then
  echo '{{"devices": {{"rt": [{{"name": "old", "udid": "U1"}}]}}}}'
fi
""")
        os.chmod(STUBS / tool, 0o755)
    write(OPEN, f"{WT / 'wt-cwd' / 'sub'}\n{proj / U['live'] / 'scratchpad/sp-open/deep/f.txt'}\n")
    write(PROCS, "launchd\nzsh\n")


def tool(*args, free=10 ** 15):
    env = dict(GIT_ENV, PATH=f"{STUBS}:{os.environ['PATH']}", DISK_TIDY_TMP_ROOT=str(TMP_ROOT),
               DISK_TIDY_TMPDIR=str(TDIR), DISK_TIDY_BREW_PREFIX=str(BREW),
               DISK_TIDY_OPEN_PATHS=str(OPEN), DISK_TIDY_PROCS=str(PROCS), DISK_TIDY_FREE_BYTES=str(free),
               DISK_TIDY_NOW=str(NOW))
    r = subprocess.run([sys.executable, str(TOOL), *args], env=env, capture_output=True, text=True,
                       timeout=300)
    if r.returncode not in (0, 1):
        print(r.stdout, r.stderr)
    return r


LINE = re.compile(r"^(keep|would-remove|removed|FAILED)\s+(\S+)\s+(?:\S+\s+)?(/\S*|\d+ unavailable \S+)"
                  r"(?:  \((.*?)\))?(?:  -- (.*))?$")


def parse(out):
    """{path: (verb, rule, reason)} for every decision line."""
    res = {}
    for line in out.splitlines():
        m = LINE.match(line)
        if m:
            res[m.group(3)] = (m.group(1), m.group(2), m.group(5) or "")
    return res


def verb(res, p):
    return res.get(str(p), ("-", "", ""))[0]


def reason(res, p):
    return res.get(str(p), ("-", "", ""))[2]


build()
NOW = shift_all()                       # the clock every tool run below is given
proj = TMP_ROOT / "-Users-x"
dd = HOME / "Library/Developer/Xcode/DerivedData"
SP = proj / U["live"] / "scratchpad"
LOG = HOME / "Library/Logs/disk-tidy.log"
GONE = [WT / "wt-old", HOME / "Claude/maa-automation-sib", dd / "Proj-old", HOME / ".gradle/caches/9.8.0",
        HOME / ".gradle/daemon/9.8.0", HOME / "Library/Developer/Toolchains/swift-6.4.0-RELEASE.xctoolchain",
        proj / U["dead"], TDIR / "precheck-abc", HOME / "Claude/transit-app/build",
        HOME / "Money/styl-work/remote-ref/tools/bugexam/xcr-dd", HOME / ".cache/pyright-python",
        SP / "sp-old", SP / "big.bin", HOME / ".gradle/caches/9.8.1/transforms",
        HOME / "Money/styl-work/evidence/x/dd", HOME / "Money/styl-work/evidence/deep/a/b/dd"]
KEPT = {
    WT / "wt-new": "changed within 24",
    WT / "wt-dirty": "uncommitted changes",
    WT / "wt-unmerged": "not merged",
    WT / "wt-cwd": "running process",
    WT / "wt-journal": "running workflow",
    WT / "wt-named": "names its path",
    WT / "wt-locked": "locked",
    WT / "wt-5h": "changed within 24",
    HOME / "Claude/maa-automation-data": "standing",
    HOME / "Money/styl-work/ds-relay-tree": "standing",
    HOME / "Money/other-tree": "not a session worktree",
    HOME / "Claude/other-fix": "not a session worktree",
    proj / U["live"]: "session running",
    proj / U["pred"]: "session running",
    proj / U["fresh"]: "changed within 24",
    proj / U["reused"]: "names this session",
    proj / U["journal"]: "workflow journal",
    proj / U["transcript"]: "transcript written",
    dd / "Proj-new": "changed",
    SP / "sp-new": "changed within 24",
    SP / "sp-5h": "changed within 24",
    SP / "sp-open": "running process",
    SP / "sp-journal": "running workflow",
    SP / "sp-prompt": "running workflow",
    SP / "sp-longrun": "running workflow",
    SP / "sp-plain": "running workflow",
    SP / "sp-wt": "registered git worktree",
    SP / "sp-gitlink": "linked git worktree",
    SP / "sp-named": "names scratchpad/sp-named",
    SP / "sp-ro": "names scratchpad/sp-ro",
    HOME / "Money/styl-work/evidence/named/dd": "names its path",
    HOME / "Money/styl-work/evidence/fresh/dd": "changed",
    HOME / "Money/styl-work/remote-ref/tools/axd-dd": "-derivedDataPath .../axd-dd",
    HOME / ".gradle/caches/9.8.1": "version in use",
    HOME / "Library/Developer/Toolchains/swift-6.4.1-RELEASE.xctoolchain": "in use",
}
UNTOUCHED = [HOME / "Money/styl-work/BOARD/OPEN.md", HOME / "Documents/mine.txt", TMP_ROOT / "disk-tidy",
             HOME / ".gradle/caches/modules-2", dd / "ModuleCache.noindex", SP, SP / "small.log",
             proj / U["live"] / "tasks", HOME / "Money/styl-work/evidence/y/dd",
             HOME / "Money/styl-work/evidence/x/a.png", HOME / "Money/styl-work/evidence/x"]

print("[dry run: decides everything, removes nothing, logs nothing]")
r = tool()
res = parse(r.stdout)
check("dry run exit code", r.returncode, 0)
for p in GONE:
    check(f"dry run would remove {p.relative_to(BASE)}", verb(res, p), "would-remove")
for p, why in KEPT.items():
    check(f"dry run keeps {p.relative_to(BASE)} ({why})", (verb(res, p), why in reason(res, p)), ("keep", True))
for p in UNTOUCHED:
    check(f"no rule matches {p.relative_to(BASE)}", verb(res, p), "-")
check("dry run: every path still there", [str(p) for p in GONE if not p.exists()], [])
check("dry run: no log written", LOG.exists(), False)
check("dry run: no tool ran except listing simulators",
      CALLS.read_text().split("\n")[:-1] if CALLS.exists() else [], ["xcrun simctl list -j devices unavailable"])
check("dry run: floor rules not run while free space is above the floor", "-- floor rules" in r.stdout, False)

print("[apply: exactly the rule matches go, each one logged]")
CALLS.unlink()
r = tool("--apply")
res = parse(r.stdout)
check("apply exit code", r.returncode, 0)
for p in GONE:
    check(f"removed {p.relative_to(BASE)}", (verb(res, p), p.exists()), ("removed", False))
for p in list(KEPT) + UNTOUCHED:
    check(f"still there: {p.relative_to(BASE)}", p.exists(), True)
check("dirty tree keeps its uncommitted file", (WT / "wt-dirty/notes.txt").exists(), True)
wtlist = sh("git", "-C", REPO, "worktree", "list", "--porcelain")
check("removed worktree unregistered", f"worktree {WT / 'wt-old'}\n" in wtlist, False)
check("branch of the removed worktree kept", "wt-old" in sh("git", "-C", REPO, "branch", "--list", "wt-old"), True)
check("stale registration pruned", "wt-gone" in wtlist, False)
calls = CALLS.read_text().splitlines()
for c in ("swiftly uninstall 6.4.0 --assume-yes", "uv cache prune", "brew cleanup --prune=all",
          "go clean -cache", "xcrun simctl delete unavailable"):
    check(f"ran `{c}`", c in calls, True)
check("no other toolchain uninstalled", [c for c in calls if c.startswith("swiftly")],
      ["swiftly uninstall 6.4.0 --assume-yes"])
log = LOG.read_text(encoding="utf-8").splitlines()
logged = {ln.split("\t")[2] for ln in log}
check("one log line per removed path", sorted(str(p) for p in GONE if str(p) not in logged), [])
check("log line shape: time, rule, path, size",
      all(re.match(r"^\d{4}-\d\d-\d\dT[\d:]+[+-]\d{4}\t[a-z0-9-]+\t\S.*\t\d*K$", ln) for ln in log), True)
check("log lines == removals", len(log), sum(1 for v in res.values() if v[0] == "removed"))

print("[below the floor: build outputs in kept trees, today's DerivedData, shared caches]")
write(PROCS, "launchd\nxcodebuild\n")
r = tool("--dry-run", free=0)
res = parse(r.stdout)
check("floor rules announced", "-- floor rules" in r.stdout, True)
check("shared cache kept while xcodebuild runs", "build running" in reason(res, dd / "ModuleCache.noindex"), True)
write(PROCS, "launchd\n")
r = tool("--apply", free=0)
res = parse(r.stdout)
check("floor apply exit code", r.returncode, 0)
for p in (WT / "wt-dirty/.build", WT / "wt-unmerged/.build", WT / "wt-unmerged/.swiftpm"):
    check(f"floor removed {p.relative_to(BASE)}", (verb(res, p), p.exists()), ("removed", False))
check("unmerged tree itself and its commit stay", ((WT / "wt-unmerged/new.txt").exists(),
                                                   (WT / "wt-unmerged/a.txt").exists()), (True, True))
check("dirty tree's change stays", (WT / "wt-dirty/notes.txt").exists(), True)
check("floor removed shared ModuleCache", (dd / "ModuleCache.noindex").exists(), False)
check("floor removed the 5 h idle merged tree", (verb(res, WT / "wt-5h"), (WT / "wt-5h").exists()),
      ("removed", False))
check("floor still keeps the fresh tree", (WT / "wt-new").exists(), True)
check("floor still keeps the tree in use", (WT / "wt-cwd").exists(), True)
check("floor removed the 5 h idle scratchpad subdir (2 h window)",
      (verb(res, SP / "sp-5h"), (SP / "sp-5h").exists()), ("removed", False))
for p in (SP / "sp-new", SP / "sp-open", SP / "sp-journal", SP / "sp-prompt", SP / "sp-longrun",
          SP / "sp-plain", SP / "sp-wt", SP / "sp-gitlink", SP / "small.log", SP / "sp-named",
          SP / "sp-ro/M4/deep/f.txt", HOME / "Money/styl-work/evidence/named/dd",
          HOME / "Money/styl-work/evidence/fresh/dd", HOME / "Money/styl-work/evidence/x/a.png"):
    check(f"floor still keeps {p.relative_to(BASE)}", p.exists(), True)
check("running session's dir and scratchpad stay", (proj / U["live"]).is_dir() and SP.is_dir(), True)
for p in UNTOUCHED[:3]:
    check(f"floor leaves {p.relative_to(BASE)}", p.exists(), True)

print("[guard: hard refusals, whatever a rule matched]")
os.environ.update(HOME=str(HOME), DISK_TIDY_TMP_ROOT=str(TMP_ROOT), DISK_TIDY_TMPDIR=str(TDIR),
                  DISK_TIDY_BREW_PREFIX=str(BREW), DISK_TIDY_OPEN_PATHS=str(OPEN), DISK_TIDY_PROCS=str(PROCS),
                  DISK_TIDY_NOW=str(NOW))
env = dt.Env.from_environ()
ctx = dt.snapshot(env)
os.symlink(HOME / "Money", proj / "link-to-money")
write(proj / U["cwd"] / "scratchpad/f.txt")             # the apply above removed it
for p, want in ((HOME / "Money/styl-work/BOARD", "not in a place"),
                (HOME / "Money/styl-work/evidence", "not in a place"),
                (HOME / "Claude/maa-automation/relay", "not in a place"),
                (HOME / "Documents", "not in a place"),
                (HOME / "Library/Developer/CoreDevice/x", "CoreDevice"),
                (HOME / "Library/Developer/CoreSimulator/Devices/A", "simulators"),
                (HOME / ".claude/projects/-Users-x", "~/.claude"),
                (HOME / "Library/Containers/com.kurogame.mingchao", "containers"),
                (proj / "link-to-money", "symlink"),
                (env.dd, "not in a place"),
                (TMP_ROOT, "not in a place")):
    got = dt.guard(env, ctx, str(p)) or ""
    check(f"guard refuses {p.relative_to(BASE)}", want in got, True)
check("guard allows a dead session dir", dt.guard(env, ctx, str(proj / U["cwd"])), None)

# 10-16 review: a tree unpacked into a running session's scratchpad keeps its old mtimes
# (tar -x, unzip, ditto, cp -Rp, rsync -a), so on mtime alone it looked idle the moment it landed
# and the next hourly run could delete it under a subagent still reading it. ctime cannot be set
# back: the real clock here, not the simulated one.
pkg = BASE / "pkg"
write(pkg / "src/a.txt", "a")
old = time.mktime((2026, 9, 1, 0, 0, 0, 0, 0, -1))
for f in (pkg / "src/a.txt", pkg / "src", pkg):
    os.utime(f, (old, old))
sh("tar", "-cf", BASE / "pkg.tar", "-C", pkg, "src")
(SP / "sp-unpacked").mkdir()
sh("tar", "-xf", BASE / "pkg.tar", "-C", SP / "sp-unpacked")
os.utime(SP / "sp-unpacked", (old, old))
real = dt.Env(HOME, TMP_ROOT, TDIR, BREW, time.time())
check("unpacked tree: every mtime is old (mtime alone calls it idle)",
      dt.changed_since(str(SP / "sp-unpacked"), real.cutoff(dt.ACTIVE_HOURS)), None)
for fn in (dt.rule_live_session_scratch, dt.rule_live_session_scratch_floor):
    got = {i.path: i.keep or "" for i in fn(real, ctx)}.get(str(SP / "sp-unpacked"), "-")
    check(f"{fn.__name__}: a tree unpacked just now with old mtimes is kept", "changed within" in got, True)
got = {i.path: i.keep for i in dt.rule_live_session_scratch(env, ctx)}.get(str(SP / "sp-unpacked"), "-")
check("the same tree 48 h later goes", got, None)
saved = ctx.in_use
ctx.in_use = None
check("guard refuses everything when lsof failed", "lsof failed" in (dt.guard(env, ctx, str(proj / U["cwd"])) or ""), True)
os.environ.pop("DISK_TIDY_OPEN_PATHS")
sleeper = subprocess.Popen(["/bin/sleep", "60"], cwd=proj / U["cwd"])
try:
    ctx.in_use = dt.open_paths()
    check("real lsof sees the live cwd", "running process" in (dt.guard(env, ctx, str(proj / U["cwd"])) or ""), True)
finally:
    sleeper.kill()
    sleeper.wait()
ctx.in_use = saved
nobrew = dt.Env(HOME, TMP_ROOT, TDIR, BASE / "no-brew", NOW)
write(HOME / ".gradle/caches/9.7.0/f")
age(HOME / ".gradle/caches/9.7.0", 72, NOW)
items = dt.rule_old_gradle(nobrew, ctx)
check("unknown Gradle version in use: nothing goes",
      sorted({i.keep for i in items}), ["cannot tell which Gradle version is in use"])

# 10-13 23:30 the tool uninstalled swift 6.4.0 while the Android SDK bundle built for it was
# installed, and the App's Android build stopped. A toolchain an SDK bundle needs stays.
write(HOME / ".swiftly/config.json", json.dumps({"inUse": "6.4.1", "installedToolchains": ["6.4.1", "6.4.0"]}))
write(HOME / "Library/Developer/Toolchains/swift-6.4.0-RELEASE.xctoolchain/usr/bin/swift")
write(HOME / "Library/org.swift.swiftpm/swift-sdks/swift-6.4.0-RELEASE_android.artifactbundle/info.json")
items = {i.path.rsplit("/", 1)[-1]: i for i in dt.rule_old_swift_toolchains(env, ctx)}
check("a toolchain an installed Swift SDK needs is kept",
      (items["swift-6.4.0-RELEASE.xctoolchain"].action, items["swift-6.4.0-RELEASE.xctoolchain"].keep),
      ("rm", "needed by the Swift SDK swift-6.4.0-RELEASE_android.artifactbundle"))

# 10-18: a reference that names the session dir or scratchpad/ itself - or an entry the scan
# cannot read, like an f-string placeholder - still keeps the whole scratchpad.
for label, ref in (("the session dir", f"/private/tmp/claude-501/-Users-x/{U['live']}/"),
                   ("scratchpad/ itself", f"/private/tmp/claude-501/-Users-x/{U['live']}/scratchpad"),
                   ("an f-string entry", f"/private/tmp/claude-501/-Users-x/{U['live']}/scratchpad/sp-{{name}}")):
    write(HOME / ".claude/hooks/h2.py", f"P = f'{ref}'\n")
    got = {i.path: i.keep or "" for i in dt.rule_live_session_scratch(env, dt.snapshot(env))}
    check(f"a tool naming {label} keeps the whole scratchpad",
          (list(got), "names this session" in got.get(str(SP), "")), ([str(SP)], True))
write(HOME / ".claude/hooks/h2.py", "\n")

# 10-18: Gradle's transform cache goes only while no Gradle process runs and once idle. `ps -o
# comm` shows a daemon as `java`, so the check reads the command line.
tf = HOME / ".gradle/caches/9.8.1/transforms"
write(tf / "t/f")
age(tf, 72, NOW)
rule_tf = getattr(dt, "rule_gradle_transforms", lambda e, c: [])
write(PROCS, "launchd\n/usr/bin/java -Xmx2g -cp gradle-daemon-main-9.8.1.jar "
             "org.gradle.launcher.daemon.bootstrap.GradleDaemon 9.8.1\n")
got = {i.path: i.keep for i in rule_tf(env, dt.snapshot(env))}.get(str(tf), "-")
check("gradle transforms kept while a Gradle daemon runs", "Gradle" in (got or ""), True)
write(PROCS, "launchd\n")
got = {i.path: i.keep for i in rule_tf(env, dt.snapshot(env))}.get(str(tf), "-")
check("gradle transforms go when no Gradle runs", got, None)
write(tf / "t/g")
age(tf / "t/g", 1, NOW)
got = {i.path: i.keep for i in rule_tf(env, dt.snapshot(env))}.get(str(tf), "-")
check("gradle transforms changed 1 h ago are kept", "changed" in (got or ""), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
