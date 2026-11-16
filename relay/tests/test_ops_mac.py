"""Mac operational tools: disk-tidy, order inbox CLI, and deploy smoke gates."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir

_SHARED = (check, fails, require, tmpdir)


def _part_disk_tidy():  # noqa: C901
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
    from _tmp import tmpdir

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
          'CMD = ["xcodebuild", "-derivedDataPath", dd]\n'     # a variable: names no folder "dd"
          f'OLD = "xcodebuild -derivedDataPath ~/Money/styl-work/evidence/gone/dd"\n')  # that one only

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


def _part_order_now_confirmed():
    """scripts/mac/order-now.sh refuses a changing order without "confirmed": true.

2026-10-10 04:16:12 a set_master sent with order-now.sh carried no "confirmed";
the relay refused it (commands.py gate 2) and pushed 「📱 配置没改成」 to the
group. The script now stops before
sending such an order. The list of changing actions is read from the relay
(commands.MUTATING).

Nothing here reaches ntfy: HOME holds a made-up push.env and PATH starts with a
fake curl that only records that it was called and answers 200.

    Formerly test_order_now_confirmed.py.
    """
    import json
    import os
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts" / "mac" / "order-now.sh"
    sys.path.insert(0, str(ROOT / "relay"))
    from ark_relay.features.commands import MUTATING


    def run(body: dict, home: str) -> tuple[int, str, bool]:
        """(exit code, output, whether the fake curl was called)."""
        sent = Path(home) / "curl-called"
        sent.unlink(missing_ok=True)
        env = {**os.environ, "HOME": home, "PATH": f"{home}/bin:{os.environ['PATH']}"}
        r = subprocess.run(["bash", str(SCRIPT), json.dumps(body, ensure_ascii=False)],
                           capture_output=True, env=env, timeout=30)
        return r.returncode, (r.stderr + r.stdout).decode("utf-8", "replace"), sent.exists()


    def fake_home(home: str) -> None:
        cfg = Path(home) / ".config" / "ark"
        cfg.mkdir(parents=True)
        (cfg / "push.env").write_text("ARK_PHONE_TOPIC=test-topic-not-real\nARK_PHONE_PIN=0000\n", encoding="utf-8")
        curl = Path(home) / "bin" / "curl"
        curl.parent.mkdir()
        curl.write_text(f"#!/bin/sh\ntouch '{home}/curl-called'\nprintf 200\n", encoding="utf-8")
        curl.chmod(0o755)


    with tempfile.TemporaryDirectory() as home:
        fake_home(home)
        print("[a changing order without confirmed: stopped here, not sent]")
        code, out, sent = run({"action": "set_master", "game": "鸣潮", "path": "x", "value": 2}, home)
        check("exit code non-zero", code != 0, True)
        check("says confirmed is needed", '"confirmed": true' in out, True)
        check("not sent", sent, False)

        code, out, sent = run({"action": "set_stage", "value": "1-7", "confirmed": False}, home)
        check("confirmed false is stopped too", (code != 0, sent), (True, False))

        print("\n[confirmed, or not a changing order: sent as before]")
        code, out, sent = run({"action": "set_master", "confirmed": True, "game": "鸣潮", "path": "x", "value": 2}, home)
        check("confirmed set_master is sent", (code, sent), (0, True))
        code, out, sent = run({"action": "tacet_shots", "on": False}, home)
        check("a non-changing order needs no confirmed", (code, sent), (0, True))

        print("\n[the list is the relay's own]")
        check("set_master, set_config and run_now are changing orders", {"set_master", "set_config", "run_now"} <= MUTATING, True)


def _part_order_push_main():
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

    Formerly test_order_push_main.py.
    """
    import json
    import os
    import shutil
    import subprocess
    import tempfile

    SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mac" / "order.sh"


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
        # scripts/mac/order.sh imports ark_relay.features.phone.commands
        features = work / "relay" / "ark_relay" / "features"
        features.mkdir(parents=True)
        for pkg in (features.parent, features):
            (pkg / "__init__.py").write_text("")
        (features / "commands.py").write_text("ALLOWED = {'skip_shutdown': None}\n")
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


def _part_deploy_pkg_bash32():
    """deploy-pkg.sh under macOS /bin/bash 3.2, a UTF-8 locale and set -u.

bash 3.2 reads the bytes of a full-width character right after `$NAME` (for example
`$PREV（`) as part of the variable name, so under set -u the line dies with
"PREVï: unbound variable" (exit 127). Until 2026-10-13 seven lines of
scripts/mac/lib/deploy-pkg.sh were written that way, one of them on the way back
after a failed deploy. Every variable touching a non-ASCII character is ${NAME} now.

No deploy runs here: the way-back block is run in /bin/bash with ssh, scp and the
script's helpers (pkg_py, pkg_py_at, pkg_restart) stood in, and every other echo line
that names a variable next to a non-ASCII character is run on its own.

    Formerly test_deploy_pkg_bash32.py.
    """
    import os
    import re
    import subprocess

    ROOT = Path(__file__).resolve().parents[2]
    SH = (ROOT / "scripts" / "mac" / "lib" / "deploy-pkg.sh").read_text(encoding="utf-8")
    BASH = "/bin/bash"
    ENV = {**os.environ, "LC_ALL": "en_US.UTF-8"}


    def bash(script: str):
        r = subprocess.run([BASH, "-c", script], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=ENV)
        return r.returncode, r.stdout + r.stderr


    if not Path(BASH).exists():
        print("  - no /bin/bash here, nothing to check")
        sys.exit(0)

    print("[this bash is the one that trips]")
    rc, out = bash('set -u; PREV=41; echo "a $PREV（b"')
    print(f"    {Path(BASH)} on $PREV（: exit {rc}")

    print("[no $NAME right before a non-ASCII character]")
    bare = [ln.strip() for ln in SH.splitlines() if re.search(r"\$[A-Za-z_][A-Za-z_0-9]*[^\x00-\x7F]", ln)]
    check("lines with a bare $NAME before a non-ASCII character", bare, [])

    STUBS = r"""
set -euo pipefail
SSH_OPTS=(-o ConnectTimeout=15); USER_AT=Administrator@host
APP_WIN='C:\Program Files\ArkRelay'; PKG_DEPLOY='C:\x\ark-pkg-deploy.py'; WATCH_PY='C:\x\w.py'
PREV=41; NEW=42; VER=20261013000000; T0='2026-10-13 11:00:00'; INC='C:\x\.incoming'
APPFILES_WHY=boom; RUNTIME_WHY=boom; MC_STATE='C:\Program Data\ark'; RUNTIME_PY_EXE='C:\x\python.exe'
FAILED_WHY="上线后没稳住：test"; RUNTIME_TOUCHED=0; APPFILES_SWAPPED=0
STATE=Stopped; CURRENT=42; WATCH_OUT=$(mktemp)
ssh() { :; }
scp() { :; }
pkg_py() { case "$*" in *" watch "*) echo "WATCH_OK" ;; *" back "*) echo "BACK to 41" ;; esac; }
pkg_py_at() { :; }
pkg_restart() { STATE=Running; CURRENT=$PREV; }
"""

    print("[the way back runs to its end]")
    start = SH.find('if [ -n "$FAILED_WHY" ]; then\n  echo "❌❌ $FAILED_WHY"')
    end = SH.find("  exit 13\nfi\n", start)
    check("way-back block found", start >= 0 and end > start, True)
    block = SH[start:end + len("  exit 13\nfi\n")]
    rc, out = bash(STUBS + block)
    check("way back exits 12 (previous version holds)", rc, 12)
    check("way back names the previous version", "自动退回上一版 41（" in out, True)
    check("way back reports it held", "已自动退回上一版 41，" in out, True)

    print("[every other echo naming a variable next to a non-ASCII character]")
    lines = [ln.strip() for ln in SH.splitlines()
             if ln.strip().startswith("echo ") and re.search(r"\$\{?[A-Za-z_][A-Za-z_0-9]*\}?[^\x00-\x7F]", ln)]
    check("found the echo lines", len(lines) >= 7, True)
    for ln in lines:
        rc, out = bash(STUBS + ln + "\n")
        check(f"exit 0: {ln[:60]}", rc, 0)

    print("FAIL" if fails else "all checks passed")


def _part_deploy_smoke_gate():
    """deploy-relay.sh: the smoke runs before COS, and a failed smoke takes the way back.

Until 2026-10-13 the order was watch, publish-cos.py, smoke: on SMOKE_FAIL the relay
kept running code that failed the import check and COS already carried it as the
newest version; only a watch failure put the previous version back. Now the smoke
sits right after the watch, before the notes stamp and COS, and SMOKE_FAIL runs the
same way back as a watch failure (exit 7 when the previous version holds, 13 when not).

No deploy runs here. The `# >>> smoke gate` block is run in bash with ssh, scp and the
installed relay's helpers (pkg_py, pkg_restart) and the old service's restart_service
stood in; what the machine would answer is given per case. The position of the block
in the script is checked on the text.

    Formerly test_deploy_smoke_gate.py.
    """
    import os
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]
    SH = (ROOT / "scripts" / "mac" / "deploy-relay.sh").read_text(encoding="utf-8")


    print("[where the smoke sits]")
    pos = {k: SH.find(k) for k in ("# <<< deploy watch: watch\nfi\n", "# >>> smoke gate", "grep -q '^SMOKE_OK$'",
                                   "# <<< smoke gate", 'printf \'%s\' "$NOTES_SHA" > "$NOTES_STAMP"',
                                   'publish-cos.py"', 'echo "✅ 部署完成')}
    check("every anchor is there", [k for k, v in pos.items() if v < 0], [])
    order = list(pos.values())
    check("watch, then the smoke, then the notes stamp, then COS, then 部署完成", order == sorted(order), True)
    check("one smoke only", SH.count("ark-smoke.py $SMOKE_ARGS"), 1)

    start, end = SH.find("# >>> smoke gate"), SH.find("# <<< smoke gate")
    block = SH[start:end] if 0 <= start < end else "exit 99\n"


    def run(layout: str, smoke_out: str, *, back_holds: bool = True, appfiles: int = 0):
        """(exit code, stdout, calls) of the smoke gate block for one case."""
        with tempfile.TemporaryDirectory() as td:
            calls = Path(td) / "calls"
            script = f"""
set -euo pipefail
LOG={str(calls)!r}
HERE={str(ROOT / "relay")!r}
SSH_OPTS=(-o ConnectTimeout=15)
USER_AT=Administrator@host
LAYOUT={layout}
CHANGED="ark_relay/core/texts.py"
SMOKE_PY='"C:\\py\\python.exe"'; SMOKE_ARGS=""
PY='D:\\ark\\automas\\environment\\python\\python.exe'
REMOTE_DIR='C:/ProgramData/ark-relay'
BACKUP_DIR='C:\\ProgramData\\ark-relay-deploy-prev'
WATCH_PY='C:\\Users\\Administrator\\ark-deploy-watch.py'
PKG_DEPLOY='C:\\Users\\Administrator\\ark-pkg-deploy.py'
APP_WIN='C:\\Program Files\\ArkRelay'
PREV=41; PREV_VER=20261012000000; T0='2026-10-13 11:00:00'
APPFILES_SWAPPED={appfiles}; RUNTIME_TOUCHED=0
STATE=Running; CURRENT=42
WATCH_OUT=$(mktemp)
ssh() {{
  echo "ssh $*" >>"$LOG"
  case "$*" in
    *ark-smoke.py*) printf '%s\\n' "$SMOKE_OUT" ;;
    *" restore "*) echo "RESTORED 2 files" ;;
    *" watch "*) echo "WATCH_OK" ;;
  esac
}}
scp() {{ echo "scp $*" >>"$LOG"; }}
pkg_py() {{
  echo "pkg_py $*" >>"$LOG"
  case "$*" in *" watch "*) echo "WATCH_OK" ;; *" back "*) echo "BACK to 41" ;; esac
}}
pkg_restart() {{ echo "pkg_restart" >>"$LOG"; STATE=$BACK_STATE; CURRENT=$PREV; }}
restart_service() {{ echo "restart_service" >>"$LOG"; STATE=$BACK_STATE; }}
{block}
echo "GATE_PASSED"
"""
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env={**os.environ, "SMOKE_OUT": smoke_out, "LC_ALL": "en_US.UTF-8",
                                    "BACK_STATE": "Running" if back_holds else "Stopped"})
            if r.stderr.strip():
                print("    bash stderr:", r.stderr.strip()[-300:])
            got = calls.read_text().splitlines() if calls.exists() else []
            return r.returncode, r.stdout, got


    def kinds(calls):
        out = []
        for c in calls:
            w = c.split()
            if w[0] == "pkg_py":
                out.append("pkg_py " + w[2] if len(w) > 2 else c)
            elif w[0] == "ssh":
                out.append("ssh " + next((k for k in ("ark-smoke.py", "del", "restore", "watch") if k in c), "?"))
            else:
                out.append(w[0])
        return out


    OK = "SMOKE 导入 3 个模块（共 90 个），失败 0 个\nSMOKE_OK"
    BAD = "SMOKE 导入 3 个模块（共 90 个），失败 1 个\nSMOKE_FAIL\n  import ark_relay.core.texts 失败：SyntaxError"

    print("\n[installed relay, smoke passes: on to COS, nothing put back]")
    rc, out, calls = run("pkg", OK)
    check("the block falls through", (rc, "GATE_PASSED" in out), (0, True))
    check("no way back", [k for k in kinds(calls) if k not in ("scp", "ssh ark-smoke.py", "ssh del")], [])

    print("\n[installed relay, smoke fails: the previous version back, restarted, watched]")
    rc, out, calls = run("pkg", BAD, appfiles=1)
    check("exit 7, never reaches COS", (rc, "GATE_PASSED" in out), (7, False))
    check("back to the previous folder, the swapped files back, restart, 60 s rollback watch",
          [k for k in kinds(calls) if k not in ("scp", "ssh ark-smoke.py", "ssh del")],
          ["pkg_py back", "pkg_py appfiles-back", "pkg_restart", "pkg_py watch"])
    check("back names the previous folder", any(c.endswith("back C:\\Program Files\\ArkRelay 41") for c in calls), True)
    check("the rollback watch expects the previous folder",
          any(" watch " in c and "60 rollback 41 --pkg" in c for c in calls), True)
    check("the reason and the way back are printed", ("SyntaxError" in out, "已自动退回上一版" in out), (True, True))

    print("\n[installed relay, smoke fails and the previous version does not come back up]")
    rc, out, calls = run("pkg", BAD, back_holds=False)
    check("exit 13", (rc, "必须立刻有人处理" in out), (13, True))
    check("no appfiles-back when this deploy swapped none", "pkg_py appfiles-back" in kinds(calls), False)

    print("\n[old service layout, smoke fails: the snapshot restored, restart, watched]")
    rc, out, calls = run("legacy", BAD)
    check("exit 7", rc, 7)
    check("restore, restart_service, rollback watch",
          [k for k in kinds(calls) if k not in ("scp", "ssh ark-smoke.py", "ssh del")],
          ["ssh restore", "restart_service", "ssh watch"])

    print("\n[a smoke that answers nothing is a failure too]")
    rc, out, calls = run("pkg", "")
    check("exit 7 and the way back ran", (rc, "pkg_py back" in kinds(calls)), (7, True))


if __name__ == "__main__":
    sys.exit(run_parts([_part_disk_tidy, _part_order_now_confirmed, _part_order_push_main, _part_deploy_pkg_bash32, _part_deploy_smoke_gate]))
