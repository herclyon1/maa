#!/usr/bin/env python3
"""Remove what Claude sessions left on this Mac's disk - and nothing else.

The disk filled to 100 % twice on 10-13. The owner, 10-13 22:3x: we never clean what we
create, and he cannot watch us all the time. His rules (memory files clean-own-garbage.md and
leftover-is-not-garbage.md): we clean our own leftovers without asking him, but anything shared
or reused is checked first - 「你们不会全删了吧，还要留下了复用的啊」 (09-24 01:57) - and his own
files are never touched.

Every rule below is one row of the "safe" column of the 10-13 22:45 disk inventory
(/private/tmp/claude-501/disk-tidy/inventory.md), turned from a list of paths into a predicate
that is re-checked on every run: is it merged, is it clean, is a process using it, did anything
in it change lately, does a running session or workflow still name it, does a tool reuse it.

    ~/.local/bin/python3.14 scripts/mac/disk-tidy.py            # dry run: what would go, how big
    ~/.local/bin/python3.14 scripts/mac/disk-tidy.py --apply    # remove; one log line per removal

Removals are appended to ~/Library/Logs/disk-tidy.log (time, rule, path, size). Below the
free-space floor (--floor-gb, default 30) the "floor" rules run too: the same checks with a
2 h idle window instead of 24 h, plus git-ignored build outputs inside idle unmerged or dirty
worktrees and the shared Xcode caches.

A running session's own tmp dir stays whole, but inside its scratchpad/ each subdirectory (and
each top-level file of BIG_FILE_BYTES or more) goes once idle 24 h (2 h below the floor; idle by
mtime and ctime, so a tree unpacked with old timestamps is fresh), unused, not a git worktree and
not named by a running workflow's journal, script or agent prompt, nor a running subagent's
prompt (10-16: the acceptance session ran for days and its finished subagents' copies grew to
8.8 GB there). A tool that names an entry of that scratchpad keeps that entry only; one that names
the session dir or scratchpad/ itself keeps all of it. Hard refusals, whatever a rule says: anything
under ~/Money or ~/Claude that is not a session worktree, a listed build output or an idle Xcode
DerivedData folder (Build/ beside an Index / CompilationCache / ModuleCache .noindex) inside
~/Money/styl-work that no tool names (the files beside it stay), a worktree with
uncommitted changes, anything a running process has open or as its cwd, ~/.claude, CoreDevice
(a mount of his phone), simulators (only `xcrun simctl delete unavailable`), and anything no
rule matches. Worktrees go only through `git worktree remove` (never --force); branches stay.

Test hooks (relay/tests/test_disk_tidy.py): HOME, DISK_TIDY_TMP_ROOT, DISK_TIDY_TMPDIR,
DISK_TIDY_BREW_PREFIX, DISK_TIDY_OPEN_PATHS (file of in-use paths instead of lsof),
DISK_TIDY_PROCS (file of process names and command lines instead of ps), DISK_TIDY_FREE_BYTES,
DISK_TIDY_NOW (the clock, epoch seconds: fixtures cannot set ctime back, so the test runs the
tool in the future).
"""
from __future__ import annotations

import argparse
import bisect
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

# Measured in the 10-13 22:45 inventory (raw/wt-table.txt, scanned 22:25): every worktree a
# process was working in had a file changed minutes earlier (app-r1 22:23, gamesim-u8 22:22).
# 2 h is the activity window that inventory used; it is also the floor tier's idle window.
ACTIVE_HOURS = 2
# Measured in the same inventory: the resumed session c0d9dfdd wrote into its predecessor's tmp
# dir (983aaaa0/tasks, 09:22) 13 h before the scan, and every safe-to-remove item was idle since
# 10-12 or earlier. 24 h covers that gap; it is the normal tier's idle window.
STALE_HOURS = 24
# The 10-13 brief proposed 30 GB. Measured that evening: 8.1 GiB free at 22:44 with swap at
# 5 GB, one app-r1 Xcode test build is 9.5 GB, the daysim corpus rewrite 4.6 GB - 30 GB holds
# all three at once with room left.
FLOOR_GB = 30
# Measured 10-13 22:45 (inventory method line): du -sk over 234 worktrees and every scratch dir
# with a 60 s cap per item, none timed out; git status / cherry in the same scan used 60 s too.
DU_TIMEOUT_S = 60
GIT_TIMEOUT_S = 60
# Measured 10-13 22:5x: a full `lsof -w -n -P -F n` (525 processes, 41619 lines) took 0.19 s.
LSOF_TIMEOUT_S = 60
# Measured 10-13 22:5x: `brew cleanup --prune=all -n` 0.78 s, `go clean -cache -n` 0.02 s; the
# largest single item, the swift 6.4.0 toolchain, is 4.9 GB in 4158 files.
TOOL_TIMEOUT_S = 600
# Files bigger than this are data or logs, not tools; the reuse scan reads only code.
REF_FILE_BYTES = 2_000_000
# Top-level files of a running session's scratchpad from this size on are judged one by one.
# Measured 10-16 21:3x in the acceptance session's scratchpad (832 entries): the largest top-level
# file was 0.5 MB (gradle.log) and the 8.8 GB sat in subdirectories; 100 MB is a download or a
# build product, and smaller files would only add hundreds of lines to every hourly run.
BIG_FILE_BYTES = 100 << 20
# Measured 10-16 22:0x over the 1509 subagent transcripts on this Mac: the leading user lines (the
# prompt) were 3.7 KB median and 324 KB at most; 1 MB reads every prompt whole.
PROMPT_BYTES = 1 << 20

UUID_RX = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID_NAME = re.compile(rf"^{UUID_RX}$")
# A session's tmp dir as code names it. Hooks and tests also quote session ids of transcripts
# (~/.claude/projects/...), which says nothing about the tmp dir, so only this form counts.
# Group 2 is the scratchpad entry it names, if any (10-18: two map scripts named
# scratchpad/urwalk2 and scratchpad/ro-apple/M4/oue.json, and the whole 11 GB scratchpad stayed).
# An entry the pattern cannot read whole (an f-string placeholder or a glob, as in run-{n} or *.json)
# must not count as a shorter name, so the entry has to end at a path or string boundary;
# otherwise the group stays empty and the whole scratchpad stays.
TMP_REF = re.compile(rf"claude-501/[^/\s'\"]+/({UUID_RX})"
                     rf"(?:/scratchpad/([^/\s'\"`<>()\[\]{{}},;|*?\\$]+)(?=[/\s'\"`<>(),;|\\]|$))?")
# A session that was continued after compaction names its predecessor's transcript like this;
# the running successor keeps using the predecessor's tmp dir (c0d9dfdd -> 983aaaa0, 10-13).
CONTINUED = re.compile(rf"read the full transcript at: \S*?/({UUID_RX})\.jsonl")
PATH_TAIL = r"/(?:Claude|Money)/[^\s'\"`<>()\[\]{},;|*?\\]+"
VERSION = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
WRAPPER_URL = re.compile(r"gradle-(\d+\.\d+(?:\.\d+)?)-(?:bin|all)\.zip")
# Code only: remote-ref/tools also holds 141k JSON data files (measured 10-13 23:1x: reading them
# made the scan take 242 s), and data does not reuse a path, a program does.
CODE_SUFFIXES = {".py", ".sh", ".zsh", ".command", ".js", ".mjs", ".ts", ".swift"}
REF_SKIP_DIRS = {".git", "node_modules", ".build", "DerivedData", "out", "xcr-dd", "__pycache__"}
# Git-ignored build outputs the floor tier may take out of idle unmerged / dirty worktrees
# (inventory row 4 and the skiphint-1011 row: .build, .swiftpm, .ruff_cache).
BUILD_DIRS = {".build", ".swiftpm", ".ruff_cache"}
# Xcode's shared caches next to the per-project folders (inventory, deferred list): only while
# no build runs.
SHARED_DD = {"ModuleCache.noindex", "SDKExplicitPrecompiledModules", "SymbolCache.noindex",
             "SDKStatCaches.noindex", "CompilationCache.noindex"}
BUILD_PROCS = {"xcodebuild", "swift-frontend", "swift-build", "swift-test", "XCBBuildService",
               "SWBBuildService"}
# A Gradle build in progress, as its java command line shows it (`ps -o comm` says only `java`):
# the daemon, the in-process client (--no-daemon) and the wrapper.
GRADLE_CMD = re.compile(r"GradleDaemon|GradleMain|GradleWrapperMain")
# An Xcode DerivedData folder (-derivedDataPath): Build/ plus at least one of these.
DD_SIGNATURE = {"Index.noindex", "CompilationCache.noindex", "ModuleCache.noindex"}
# A build folder a tool reuses, as its xcodebuild call names it. Absolute paths are caught by the
# path scan; this catches relative ones (axdump.sh: -derivedDataPath "$HERE/../axdump-dd").
DD_PATH_ARG = re.compile(r"""-derivedDataPath["',\s]+["']?([^"'\s,\]\)]+)""")
# Measured 10-18 22:5x: `find` over ~/Money/styl-work (no .git / node_modules / *.noindex) took
# 4.4 s; the deepest DerivedData folder in the 10-18 inventory sat 5 levels below it.
MONEY_DD_DEPTH = 8



# The os module has PRIO_DARWIN_PROCESS from Python 3.12 on; deploy-relay.sh runs some of these scripts with
# the system python3 (3.9), where reading it raised AttributeError. 4 is its value in <sys/resource.h>.
PRIO_DARWIN_PROCESS = getattr(os, "PRIO_DARWIN_PROCESS", 4)


def _wait_not_background() -> None:
    """Block while macOS runs this process at background priority, which it does to every other
    app's processes while a game is in front (Game Mode). Starting programs from that priority can
    lock this Mac's macOS 27.2 beta kernel (froze 09-23, 10-10 twice, 10-14 19:52). The kernel
    reports it as getpriority(PRIO_DARWIN_PROCESS) == 1 (checked live 10-14), 0 otherwise."""
    while sys.platform == "darwin" and os.getpriority(PRIO_DARWIN_PROCESS, 0):
        # Measured: 10-14 background spells lasted 56 s to 2 min 56 s; 30 s resumes soon after.
        time.sleep(30)

def norm(p: str) -> str:
    """lsof and git print /tmp and /var; on macOS both are symlinks into /private."""
    for short in ("/tmp", "/var"):
        if p == short or p.startswith(short + "/"):
            return "/private" + p
    return p


def within(p: str, root: str | Path) -> bool:
    """p is root or below it (plain string paths, no resolution)."""
    r = str(root).rstrip("/")
    return p == r or p.startswith(r + "/")


def run(args: list[str], cwd: str | None = None, timeout: float = GIT_TIMEOUT_S,
        env: dict | None = None) -> subprocess.CompletedProcess | None:
    """subprocess.run that returns None instead of raising when the tool is missing or hangs."""
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, errors="replace",
                              timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def git(repo: str, *args: str) -> subprocess.CompletedProcess | None:
    """git without optional locks: a plain `git status` rewrites the index, which would make
    every tree look freshly used to the next run (https://git-scm.com/docs/git#Documentation/git.txt---no-optional-locks)."""
    return run(["git", "--no-optional-locks", "-C", repo, *args])


def du_k(path: str) -> int | None:
    r = run(["du", "-sk", path], timeout=DU_TIMEOUT_S)
    if r is None or not r.stdout.strip():
        return None
    try:
        return int(r.stdout.split()[0])
    except ValueError:
        return None


def changed_since(path: str, cutoff: float, skip: frozenset = frozenset(),
                  ctime: bool = False) -> str | None:
    """The first file or directory under path modified after cutoff, else None.

    Directory mtimes count: creating or deleting an entry is activity too. Symlinks are
    not followed; directories named in skip are not entered. With ctime, an inode change counts
    too: tar -x, unzip, ditto, cp -p and rsync -a keep the source's old mtime, but nothing can set
    ctime back (10-16 review: a tarball dated 09-01 unpacked into a running session's scratchpad
    looked 6 weeks idle the moment it landed).
    """
    def t(st: os.stat_result) -> float:
        return max(st.st_mtime, st.st_ctime) if ctime else st.st_mtime

    try:
        if t(os.lstat(path)) > cutoff:
            return path
    except OSError:
        return None
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if t(st) > cutoff:
                    return e.path
                if stat.S_ISDIR(st.st_mode) and e.name not in skip:
                    stack.append(e.path)
    return None


def ago(path: str) -> str:
    try:
        h = (time.time() - os.lstat(path).st_mtime) / 3600
    except OSError:
        return "?"
    return f"{h:.1f} h ago"


@dataclass
class Env:
    """Where things live. Everything derives from HOME plus three overridable roots."""
    home: Path
    tmp_root: Path
    tmpdir: Path
    brew: Path
    now: float

    def __post_init__(self) -> None:
        h = self.home
        self.claude, self.money = h / "Claude", h / "Money"
        self.dd = h / "Library/Developer/Xcode/DerivedData"
        self.toolchains = h / "Library/Developer/Toolchains"
        self.gradle, self.swiftly_cfg = h / ".gradle", h / ".swiftly/config.json"
        # Swift SDK bundles (`swift sdk install`), e.g. swift-6.4.0-RELEASE_android.artifactbundle.
        self.swift_sdks = (h / "Library/org.swift.swiftpm/swift-sdks", h / ".swiftpm/swift-sdks")
        self.sessions, self.projects = h / ".claude/sessions", h / ".claude/projects"
        self.hooks, self.ref_tools = h / ".claude/hooks", h / "Money/styl-work/remote-ref/tools"
        self.log, self.lock = h / "Library/Logs/disk-tidy.log", h / "Library/Logs/disk-tidy.lock"

    @classmethod
    def from_environ(cls) -> "Env":
        e = os.environ
        return cls(home=Path.home(),
                   tmp_root=Path(norm(e.get("DISK_TIDY_TMP_ROOT", "/private/tmp/claude-501"))),
                   tmpdir=Path(os.path.realpath(e.get("DISK_TIDY_TMPDIR") or tempfile.gettempdir())),
                   brew=Path(e.get("DISK_TIDY_BREW_PREFIX", "/opt/homebrew")),
                   now=float(e.get("DISK_TIDY_NOW") or time.time()))

    def cutoff(self, hours: float) -> float:
        return self.now - hours * 3600

    def never(self) -> list[tuple[str, Path]]:
        """Roots no rule may reach into, whatever it matched."""
        h = self.home
        return [("~/.claude: transcripts, memory, hooks", h / ".claude"),
                ("CoreDevice: a mount of his phone, not disk use", h / "Library/Developer/CoreDevice"),
                ("simulators: only `simctl delete unavailable`", h / "Library/Developer/CoreSimulator"),
                ("app containers (his games and apps)", h / "Library/Containers"),
                ("app data", h / "Library/Application Support"),
                ("iCloud", h / "Library/Mobile Documents"),
                ("external volumes", Path("/Volumes"))]

    def standing(self) -> set[str]:
        """Long-lived trees that are reused, never removed (inventory, keep list)."""
        c, m = self.claude, self.money
        return {str(c / n) for n in ("maa-automation-data", "maa-automation-ui", "maa-automation-ui2",
                                     "transit-data", "transit-ui")} | {str(m / "styl-work/ds-relay-tree")}

    def known_outputs(self) -> list[Path]:
        """One-off build outputs the inventory checked by hand (row 11): rebuildable, no references."""
        out = [self.claude / "transit-app/build", self.ref_tools / "bugexam/xcr-dd"]
        try:
            out += sorted(p for p in self.tmpdir.glob("precheck-*") if p.is_dir())
        except OSError:
            pass
        return out


@dataclass
class Worktree:
    repo: str
    path: str
    head: str = ""
    branch: str = ""
    locked: bool = False
    prunable: bool = False


@dataclass
class Ctx:
    """One snapshot of what is in use, taken at the start of a run."""
    in_use: list[str] | None          # sorted; None = lsof failed, refuse everything
    procs: set[str]
    live_ids: set[str]                # running sessions and the ones they continue
    journal_ids: set[str]             # sessions owning a workflow active lately (active_journals)
    journal_text: str                 # those runs' journals, scripts and agent prompts, plus
                                      # running plain subagents' prompts
    ref_ids: set[str]                 # session ids named by tools / hooks / repo code
    ref_whole: set[str]               # of those, named without a scratchpad entry (all of it stays)
    dd_names: set[str]                # last component of every -derivedDataPath a tool passes
    ref_entries: dict[str, set[str]]  # sid -> scratchpad entries named (only those stay)
    ref_paths: list[str]              # sorted absolute paths named there
    repos: list[str]
    worktrees: list[Worktree]
    allowed_wt: list[str] = field(default_factory=list)
    money_dd: list[str] = field(default_factory=list)   # DerivedData folders in ~/Money/styl-work
    gradle_running: bool = True       # unknown counts as running


def open_paths() -> list[str] | None:
    """Every cwd and open file of every process we can see (lsof), or None if lsof failed."""
    f = os.environ.get("DISK_TIDY_OPEN_PATHS")
    if f:
        lines = Path(f).read_text(encoding="utf-8").splitlines()
        return sorted({norm(os.path.realpath(x.strip())) for x in lines if x.strip()})
    r = run(["lsof", "-w", "-n", "-P", "-F", "n"], timeout=LSOF_TIMEOUT_S)
    if r is None:
        return None
    names = {norm(x[1:].split(" (")[0]) for x in r.stdout.splitlines() if x.startswith("n/")}
    return sorted(names) or None


def proc_names() -> set[str]:
    f = os.environ.get("DISK_TIDY_PROCS")
    if f:
        return {x.strip() for x in Path(f).read_text(encoding="utf-8").splitlines() if x.strip()}
    r = run(["ps", "-axo", "comm="])
    return set() if r is None else {os.path.basename(x.strip()) for x in r.stdout.splitlines()}


def gradle_running() -> bool:
    """Is a Gradle build or daemon running? True when ps fails (unknown = running)."""
    f = os.environ.get("DISK_TIDY_PROCS")
    if f:
        lines = Path(f).read_text(encoding="utf-8").splitlines()
    else:
        r = run(["ps", "-axww", "-o", "args="])
        if r is None or r.returncode != 0:
            return True
        lines = r.stdout.splitlines()
    return any(GRADLE_CMD.search(x) for x in lines)


def sorted_hit(paths: list[str], p: str) -> bool:
    """Is p, or anything below p, in the sorted list?"""
    i = bisect.bisect_left(paths, p)
    if i < len(paths) and paths[i] == p:
        return True
    j = bisect.bisect_left(paths, p + "/")
    return j < len(paths) and paths[j].startswith(p + "/")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_text(p: Path) -> str:
    try:
        return p.read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


def live_sessions(env: Env) -> set[str]:
    """Ids of running Claude sessions (~/.claude/sessions/<pid>.json with a live pid), plus every
    session they continue, transitively (their transcripts name the predecessor's transcript)."""
    ids: set[str] = set()
    for f in env.sessions.glob("*.json") if env.sessions.is_dir() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if pid_alive(int(d["pid"])):
                ids.add(str(d["sessionId"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    todo = list(ids)
    while todo:
        sid = todo.pop()
        for t in env.projects.glob(f"*/{sid}.jsonl") if env.projects.is_dir() else []:
            for m in CONTINUED.finditer(read_text(t)):
                if m.group(1) not in ids:
                    ids.add(m.group(1))
                    todo.append(m.group(1))
    return ids


def prompt_head(p: Path) -> str:
    """The prompt of a subagent transcript: its leading "type": "user" lines (at most
    PROMPT_BYTES). What the agent did later (an `ls scratchpad/` lists every subdir) is left
    out, or every name it ever printed would stay protected."""
    out, n = [], 0
    try:
        with p.open("rb") as fh:
            for raw in fh:
                n += len(raw)
                try:
                    if json.loads(raw).get("type") != "user":
                        break
                except (ValueError, AttributeError):
                    break
                out.append(raw.decode("utf-8", "replace"))
                if n > PROMPT_BYTES:
                    break
    except OSError:
        return ""
    return "".join(out)


def newest_mtime(paths: list[Path]) -> float:
    best = 0.0
    for p in paths:
        try:
            best = max(best, p.stat().st_mtime)
        except OSError:
            continue
    return best


def active_journals(env: Env) -> tuple[set[str], str]:
    """Workflows active within ACTIVE_HOURS: (owning session ids, what they name).

    The inventory's deferred list: 28 merged worktrees idle for 2 h were still named by
    journals being written 22:0x-22:2x, so a worktree a live journal names is in use. A run is
    active while its journal or any of its agents' transcripts was written lately (one agent
    can run for hours). A journal holds only type / key / agentId / label / phase / result
    (10-16 review, all 81 on this Mac), so the run's script (~/.claude/projects/*/<sid>/
    workflows/scripts/*-<runId>.js, under whichever project the session started it from) and
    its agents' prompts are read too: relay-ledger-triage named scratchpad/ledger-triage only
    there. Plain subagents still writing their transcript count by their prompt."""
    ids, texts = set(), []
    if not env.projects.is_dir():
        return ids, ""
    cut = env.cutoff(ACTIVE_HOURS)
    for run in env.projects.glob("*/*/subagents/workflows/*/"):
        journal, agents = run / "journal.jsonl", sorted(run.glob("agent-*.jsonl"))
        if newest_mtime([journal, *agents]) <= cut:
            continue
        sid = run.parts[-4]
        ids.add(sid)
        texts.append(read_text(journal))
        texts += [read_text(s) for s in env.projects.glob(f"*/{sid}/workflows/scripts/*-{run.name}.js")]
        texts += [prompt_head(a) for a in agents]
    for a in env.projects.glob("*/*/subagents/agent-*.jsonl"):
        if newest_mtime([a]) > cut:
            texts.append(prompt_head(a))
    return ids, "\n".join(texts)


def ref_files(env: Env, repos: list[str]) -> list[Path]:
    """Code that may reuse a path: hooks, the remote-ref tools, and every repo's tracked files."""
    out: list[Path] = []
    for root in (env.hooks, env.ref_tools):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in REF_SKIP_DIRS]
            out += [Path(dirpath, f) for f in filenames if Path(f).suffix in CODE_SUFFIXES]
    for repo in repos:
        r = git(repo, "ls-files", "-z")
        if r is not None and r.returncode == 0:
            out += [Path(repo, f) for f in r.stdout.split("\0") if Path(f).suffix in CODE_SUFFIXES]
    return out


def references(env: Env, repos: list[str]) -> tuple[set[str], set[str], dict[str, set[str]], set[str], list[str]]:
    """What some tool's code names (it reuses it): session ids; of those, the ones named without a
    scratchpad entry; per session the scratchpad entries named; the folder names tools pass to
    -derivedDataPath; ~/Claude and ~/Money paths."""
    ids: set[str] = set()
    whole: set[str] = set()
    entries: dict[str, set[str]] = {}
    dd_names: set[str] = set()
    paths: set[str] = set()
    home = str(env.home)
    path_ref = re.compile("(?:~|" + re.escape(home) + ")" + PATH_TAIL)
    for f in ref_files(env, repos):
        try:
            if f.stat().st_size > REF_FILE_BYTES:
                continue
        except OSError:
            continue
        text = read_text(f)
        for sid, entry in TMP_REF.findall(text):
            ids.add(sid)
            entry = entry.rstrip(".:")
            if entry:
                entries.setdefault(sid, set()).add(entry)
            else:
                whole.add(sid)
        # A path, not a variable: ark-remote's scripts pass `"-derivedDataPath", dd` and counting
        # that would keep every folder named dd.
        dd_names.update(os.path.basename(v.rstrip("/")) for v in DD_PATH_ARG.findall(text) if "/" in v)
        for m in path_ref.findall(text):
            p = home + m[1:] if m.startswith("~") else m
            paths.add(p.rstrip("/.:"))
    return ids, whole, entries, dd_names, sorted(paths)


def repo_list(env: Env) -> list[str]:
    """Main checkouts directly under ~/Claude (a real .git directory, not a worktree's file)."""
    try:
        return sorted(str(d) for d in env.claude.iterdir() if (d / ".git").is_dir())
    except OSError:
        return []


def worktrees(repo: str) -> list[Worktree]:
    """Linked worktrees of repo (the main checkout itself is left out)."""
    r = git(repo, "worktree", "list", "--porcelain")
    if r is None or r.returncode != 0:
        return []
    out: list[Worktree] = []
    for block in r.stdout.strip().split("\n\n"):
        wt = Worktree(repo=repo, path="")
        for line in block.splitlines():
            key, _, val = line.partition(" ")
            if key == "worktree":
                wt.path = norm(val)
            elif key == "HEAD":
                wt.head = val
            elif key == "branch":
                wt.branch = val.removeprefix("refs/heads/")
            elif key == "locked":
                wt.locked = True
            elif key == "prunable":
                wt.prunable = True
        if wt.path and os.path.realpath(wt.path) != os.path.realpath(repo):
            out.append(wt)
    return out


def allowed_worktree(env: Env, wt: Worktree) -> bool:
    """Session worktrees: <repo>/.claude/worktrees/<name>, or a registered ~/Claude/<repo>-<x>
    sibling (the ark-remote-044-* / -w044-* / -replay rows) that is not itself a repo."""
    p, repo = wt.path, wt.repo
    if os.path.dirname(p) == os.path.join(repo, ".claude", "worktrees"):
        return True
    return (os.path.dirname(p) == str(env.claude)
            and os.path.basename(p).startswith(os.path.basename(repo) + "-")
            and not os.path.isdir(os.path.join(p, ".git")))


def money_derived_data(env: Env) -> list[str]:
    """Xcode DerivedData folders (Build/ plus a DD_SIGNATURE .noindex) under ~/Money/styl-work,
    sorted. Not entered: .git, node_modules, a match's own insides, deeper than MONEY_DD_DEPTH."""
    root = str(env.money / "styl-work")
    out: list[str] = []
    for dirpath, dirnames, _ in os.walk(root):
        names = set(dirnames)
        if "Build" in names and names & DD_SIGNATURE and dirpath != root:
            out.append(norm(dirpath))
            dirnames[:] = []
            continue
        depth = dirpath[len(root):].count("/")
        dirnames[:] = [] if depth >= MONEY_DD_DEPTH else [
            d for d in dirnames if d not in {".git", "node_modules", "Build"} and not d.endswith(".noindex")]
    return sorted(out)


def snapshot(env: Env) -> Ctx:
    repos = repo_list(env)
    wts = [w for r in repos for w in worktrees(r)]
    ids, text = active_journals(env)
    ref_ids, ref_whole, ref_entries, dd_names, ref_paths = references(env, repos)
    standing = env.standing()
    allowed = sorted(w.path for w in wts if allowed_worktree(env, w) and w.path not in standing)
    return Ctx(in_use=open_paths(), procs=proc_names(), live_ids=live_sessions(env),
               journal_ids=ids, journal_text=text, ref_ids=ref_ids, ref_whole=ref_whole,
               ref_entries=ref_entries, dd_names=dd_names, ref_paths=ref_paths, repos=repos, worktrees=wts,
               allowed_wt=allowed, money_dd=money_derived_data(env), gradle_running=gradle_running())


def zone_ok(env: Env, ctx: Ctx, p: str) -> bool:
    """Is p inside a place some rule is allowed to remove from (and not the place itself)?"""
    h = env.home
    child_of = [env.tmp_root, env.dd, env.gradle / "caches", env.gradle / "daemon", env.toolchains]
    for root in child_of:
        if within(p, root) and p != str(root):
            return True
    if within(p, env.tmpdir) and os.path.basename(p).startswith("precheck-"):
        return True
    if within(p, env.tmpdir) and any(within(p, o) for o in env.known_outputs()):
        return True
    for exact in (h / ".cache/pyright-python", h / ".cache/uv", h / "Library/Caches/Homebrew",
                  h / "Library/Caches/go-build"):
        if p == str(exact):
            return True
    if within(p, env.claude) or within(p, env.money):
        if any(within(p, o) for o in env.known_outputs()):
            return True
        if p in ctx.money_dd:
            return True
        return within(p, env.claude) and any(within(p, w) for w in ctx.allowed_wt)
    return False


def guard(env: Env, ctx: Ctx, path: str) -> str | None:
    """Hard refusals, checked for every path before anything is removed. None = allowed."""
    p = norm(os.path.abspath(path))
    if os.path.islink(p):
        return "is a symlink"
    if norm(os.path.realpath(p)) != p:
        return "resolves somewhere else through a symlink"
    for label, root in env.never():
        if within(p, root):
            return f"never touched ({label})"
    if not zone_ok(env, ctx, p):
        return "not in a place any rule may remove from (his files or project sources)"
    if ctx.in_use is None:
        return "lsof failed, so what is in use is unknown"
    if sorted_hit(ctx.in_use, p):
        return "a running process has it open or as its cwd"
    return None


@dataclass
class Item:
    rule: str
    path: str
    action: str = "rm"                 # rm | worktree | cmd
    keep: str | None = None            # why it stays
    cmd: list[str] | None = None
    repo: str | None = None
    size_k: int | None = None
    upper_bound: bool = False          # size is the cache's whole size, the tool frees less


def keep(rule: str, path: str, why: str) -> Item:
    return Item(rule, path, keep=why)


# ---- worktrees ---------------------------------------------------------------------------

def merged(repo: str, head: str) -> bool:
    """HEAD is in origin/main (ancestor), or every commit has an equivalent there (git cherry)."""
    refs = [r for r in ("origin/main", "main")
            if (x := git(repo, "rev-parse", "--verify", "-q", r)) is not None and x.returncode == 0]
    for ref in refs:
        x = git(repo, "merge-base", "--is-ancestor", head, ref)
        if x is not None and x.returncode == 0:
            return True
    if refs:
        x = git(repo, "cherry", refs[0], head)
        if x is not None and x.returncode == 0 and not any(
                ln.startswith("+") for ln in x.stdout.splitlines()):
            return True
    return False


def dirty(path: str) -> bool:
    """Uncommitted changes or untracked (not ignored) files; a failed git status counts as dirty."""
    r = git(path, "status", "--porcelain", "--untracked-files=normal")
    return r is None or r.returncode != 0 or bool(r.stdout.strip())


def wt_recent(env: Env, wt: Worktree, hours: float) -> str | None:
    """Why the worktree counts as active within `hours`, or None."""
    cut = env.cutoff(hours)
    hit = changed_since(wt.path, cut, frozenset({".git"}))
    if hit:
        return f"changed within {hours} h ({hit})"
    try:
        gitdir = Path(wt.path, ".git").read_text(encoding="utf-8").split("gitdir:", 1)[1].strip()
        for f in ("HEAD", "logs/HEAD"):           # not index: status refreshes it
            if os.path.getmtime(os.path.join(gitdir, f)) > cut:
                return f"git activity within {hours} h ({f})"
    except (OSError, IndexError):
        pass
    enc = re.sub(r"[^A-Za-z0-9]", "-", wt.path)
    proj = env.projects / enc
    if proj.is_dir() and changed_since(str(proj), cut):
        return f"a Claude session started in it wrote its transcript within {hours} h"
    return None


def wt_named(ctx: Ctx, wt: Worktree) -> str | None:
    """Why something still names the worktree, or None."""
    name = os.path.basename(wt.path)
    rx = re.compile(r"(?:worktrees/" + re.escape(name) + "|" + re.escape(wt.path) + r")(?![A-Za-z0-9._-])")
    if rx.search(ctx.journal_text):
        return f"a running workflow (journal, script or agent prompt) active within {ACTIVE_HOURS} h names it"
    if sorted_hit(ctx.ref_paths, wt.path):
        return "a tool, hook or repo file names its path (reused)"
    return None


def wt_facts(env: Env, ctx: Ctx, wts: list[Worktree]) -> dict[str, tuple[bool, bool]]:
    """(merged, dirty) per worktree path, computed in parallel (git status is the slow part)."""
    def one(w: Worktree) -> tuple[str, tuple[bool, bool]]:
        _wait_not_background()
        return w.path, (merged(w.repo, w.head), dirty(w.path))
    with ThreadPoolExecutor(8) as ex:
        return dict(ex.map(one, wts))


def removable_worktrees(env: Env, ctx: Ctx, rule: str, hours: float) -> list[Item]:
    standing = env.standing()
    todo, items = [], []
    for w in ctx.worktrees:
        if w.prunable or not os.path.isdir(w.path):
            continue
        if w.path in standing:
            items.append(keep(rule, w.path, "standing tree, reused"))
        elif not allowed_worktree(env, w):
            items.append(keep(rule, w.path, "not a session worktree (outside .claude/worktrees "
                                            "and not a ~/Claude/<repo>-* sibling)"))
        elif w.locked:
            items.append(keep(rule, w.path, "locked"))
        else:
            todo.append(w)
    facts = wt_facts(env, ctx, todo)
    for w in todo:
        is_merged, is_dirty = facts[w.path]
        why = (None if is_merged else "not merged into origin/main") \
            or ("uncommitted changes" if is_dirty else None) \
            or wt_named(ctx, w) or wt_recent(env, w, hours) or guard(env, ctx, w.path)
        items.append(keep(rule, w.path, why) if why else
                     Item(rule, w.path, action="worktree", repo=w.repo))
    return items


def rule_merged_worktrees(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory rows 1-3: worktrees merged into origin/main (or cherry-equivalent), clean, not
    used by any process, not named by a live workflow, idle 24 h. `git worktree remove` without
    --force refuses anything uncommitted on its own; the branch stays."""
    return removable_worktrees(env, ctx, "merged-worktree", STALE_HOURS)


def rule_merged_worktrees_floor(env: Env, ctx: Ctx) -> list[Item]:
    """Below the floor: the same worktrees after 2 h idle (deferred row 1: merged, clean, and
    removable once no journal names them)."""
    return removable_worktrees(env, ctx, "merged-worktree-2h", ACTIVE_HOURS)


def rule_idle_build_outputs(env: Env, ctx: Ctx) -> list[Item]:
    """Below the floor - inventory rows 4-5: git-ignored .build/.swiftpm/.ruff_cache inside idle
    worktrees that must stay (unmerged or dirty). Only the build output goes; the checkout and
    its changes stay. The output dir itself must be unused (skiphint-1011: adb's cwd elsewhere in
    the tree is fine), hold no tracked file, and the tree must be idle 2 h."""
    rule, items = "idle-build-output", []
    standing = env.standing()
    for w in ctx.worktrees:
        if w.prunable or not os.path.isdir(w.path) or w.path in standing or not allowed_worktree(env, w):
            continue
        r = git(w.path, "ls-files", "-o", "-i", "--exclude-standard", "--directory")
        if r is None or r.returncode != 0:
            continue
        outs = [os.path.join(w.path, x.rstrip("/")) for x in r.stdout.splitlines()
                if os.path.basename(x.rstrip("/")) in BUILD_DIRS]
        if not outs:
            continue
        busy = wt_named(ctx, w) or wt_recent(env, w, ACTIVE_HOURS)
        for o in outs:
            tracked = git(w.path, "ls-files", "--", os.path.relpath(o, w.path))
            why = busy or ("holds tracked files" if tracked is None or tracked.stdout.strip() else None) \
                or guard(env, ctx, o)
            items.append(keep(rule, o, why) if why else Item(rule, o))
    return items


def rule_stale_registrations(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory, branches line: registrations of worktrees whose folder is already gone
    (`git worktree prune` frees 0 MB, removes only metadata git itself calls prunable)."""
    items = []
    for repo in ctx.repos:
        r = git(repo, "worktree", "prune", "-n", "-v")
        if r is not None and r.returncode == 0 and (r.stdout + r.stderr).strip():
            items.append(Item("stale-registration", repo, action="cmd",
                              cmd=["git", "-C", repo, "worktree", "prune"], size_k=0))
    return items


# ---- Xcode, Gradle, Swift ----------------------------------------------------------------

def derived_data(env: Env, ctx: Ctx, rule: str, hours: float) -> list[Item]:
    items = []
    try:
        dirs = sorted(d for d in env.dd.iterdir() if d.is_dir() and d.name not in SHARED_DD)
    except OSError:
        return []
    for d in dirs:
        why = (f"changed {ago(str(d))}" if changed_since(str(d), env.cutoff(hours)) else None) \
            or guard(env, ctx, str(d))
        items.append(keep(rule, str(d), why) if why else Item(rule, str(d)))
    return items


def rule_derived_data(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory row 6: per-project DerivedData folders idle 24 h with nothing open in them -
    xcodebuild output, rebuilt on the next build."""
    return derived_data(env, ctx, "derived-data", STALE_HOURS)


def rule_derived_data_floor(env: Env, ctx: Ctx) -> list[Item]:
    """Below the floor - deferred row 2: today's DerivedData folders once no build is running."""
    if ctx.procs & BUILD_PROCS:
        return []
    return derived_data(env, ctx, "derived-data-2h", ACTIVE_HOURS)


def rule_shared_derived_caches(env: Env, ctx: Ctx) -> list[Item]:
    """Below the floor - deferred row 2: Xcode's shared ModuleCache / SDK / Symbol caches, only
    while no xcodebuild / swift-frontend / build service runs, idle 2 h."""
    rule, items = "shared-xcode-cache", []
    running = ctx.procs & BUILD_PROCS
    for name in sorted(SHARED_DD):
        d = env.dd / name
        if not d.is_dir():
            continue
        why = (f"build running ({', '.join(sorted(running))})" if running else None) \
            or (f"changed {ago(str(d))}" if changed_since(str(d), env.cutoff(ACTIVE_HOURS)) else None) \
            or guard(env, ctx, str(d))
        items.append(keep(rule, str(d), why) if why else Item(rule, str(d)))
    return items


def gradle_in_use(env: Env, ctx: Ctx) -> set[str]:
    """The Homebrew gradle version plus every version a repo's gradle-wrapper.properties pins."""
    out = set()
    link = env.brew / "opt/gradle"
    if link.exists():
        # A Homebrew revision names the keg 9.8.1_1; Gradle's own dirs say 9.8.1.
        m = re.match(r"\d+\.\d+(?:\.\d+)?", os.path.basename(os.path.realpath(link)))
        if m:
            out.add(m.group(0))
    for repo in ctx.repos:
        r = git(repo, "ls-files", "-z", "--", "*gradle-wrapper.properties")
        for f in (r.stdout.split("\0") if r is not None and r.returncode == 0 else []):
            if f:
                out.update(WRAPPER_URL.findall(read_text(Path(repo, f))))
    return out


def rule_old_gradle(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory row 7: ~/.gradle/caches/<v> and daemon/<v> for a Gradle version nothing uses any
    more (Homebrew moved 9.8.0 -> 9.8.1 on 10-12, no wrapper pins 9.8.0), idle 24 h, unopened.
    If the version in use cannot be read, nothing goes."""
    rule, items = "old-gradle", []
    current = gradle_in_use(env, ctx)
    for kind in ("caches", "daemon"):
        base = env.gradle / kind
        try:
            dirs = sorted(d for d in base.iterdir() if d.is_dir() and VERSION.match(d.name))
        except OSError:
            continue
        for d in dirs:
            why = ("cannot tell which Gradle version is in use" if not current else None) \
                or (f"version in use ({', '.join(sorted(current))})" if d.name in current else None) \
                or (f"changed {ago(str(d))}" if changed_since(str(d), env.cutoff(STALE_HOURS)) else None) \
                or guard(env, ctx, str(d))
            items.append(keep(rule, str(d), why) if why else Item(rule, str(d)))
    return items


def gradle_transforms(env: Env, ctx: Ctx, rule: str, hours: float) -> list[Item]:
    items = []
    try:
        dirs = sorted(d / "transforms" for d in (env.gradle / "caches").iterdir()
                      if VERSION.match(d.name) and (d / "transforms").is_dir())
    except OSError:
        return []
    for d in dirs:
        why = ("a Gradle build or daemon is running" if ctx.gradle_running else None) \
            or (f"changed {ago(str(d))}" if changed_since(str(d), env.cutoff(hours)) else None) \
            or guard(env, ctx, str(d))
        items.append(keep(rule, str(d), why) if why else Item(rule, str(d)))
    return items


def rule_gradle_transforms(env: Env, ctx: Ctx) -> list[Item]:
    """10-18 inventory A2 (9.8 GB): ~/.gradle/caches/<v>/transforms holds the outputs of artifact
    transforms, a cache Gradle recreates on first use (https://docs.gradle.org/current/userguide/
    directory_layout.html#dir:caches:version_specific). It goes while no Gradle daemon, client or
    wrapper runs and nothing in it changed within 24 h; the downloaded jars (modules-2) stay."""
    return gradle_transforms(env, ctx, "gradle-transforms", STALE_HOURS)


def rule_gradle_transforms_floor(env: Env, ctx: Ctx) -> list[Item]:
    """Below the floor: the same after 2 h idle."""
    return gradle_transforms(env, ctx, "gradle-transforms-2h", ACTIVE_HOURS)


def sdk_toolchain_versions(env: Env) -> dict[str, str]:
    """Toolchain version -> the installed Swift SDK bundle that builds only with it. A bundle
    named swift-6.4.0-RELEASE_android needs the 6.4.0 toolchain: 10-13 23:30 this tool removed
    6.4.0 as unused and Skip's Android build stopped with "No Swift Toolchain matching version
    6.4.0 for SDK version 6.4.0"."""
    found = {}
    for root in env.swift_sdks:
        try:
            names = sorted(p.name for p in root.iterdir())
        except OSError:
            continue
        for name in names:
            if m := re.match(r"swift-(\d+\.\d+(?:\.\d+)?)-RELEASE_.*\.artifactbundle$", name):
                found.setdefault(m.group(1), name)
    return found


def rule_old_swift_toolchains(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory row 8: swiftly toolchains other than the one swiftly has in use, not pinned by
    any repo's .swift-version and not needed by an installed Swift SDK bundle, with nothing open
    inside; removed by `swiftly uninstall`."""
    rule, items = "old-swift-toolchain", []
    sdks = sdk_toolchain_versions(env)
    try:
        cfg = json.loads(env.swiftly_cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    in_use = str(cfg.get("inUse") or "")
    pins = set()
    for repo in ctx.repos:
        r = git(repo, "ls-files", "-z", "--", "*.swift-version")
        for f in (r.stdout.split("\0") if r is not None and r.returncode == 0 else []):
            if f:
                pins.add(read_text(Path(repo, f)).strip())
    for v in cfg.get("installedToolchains") or []:
        tc = env.toolchains / f"swift-{v}-RELEASE.xctoolchain"
        why = ("swiftly has no toolchain in use" if not in_use else None) \
            or ("in use" if v == in_use else None) \
            or ("pinned by a .swift-version" if v in pins else None) \
            or (f"needed by the Swift SDK {sdks[v]}" if v in sdks else None) \
            or (None if tc.is_dir() else "toolchain folder not found") \
            or guard(env, ctx, str(tc))
        items.append(keep(rule, str(tc), why) if why else
                     Item(rule, str(tc), action="cmd", cmd=["swiftly", "uninstall", v, "--assume-yes"]))
    return items


# ---- session leftovers ---------------------------------------------------------------------

def rule_dead_session_dirs(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory rows 9-10: /private/tmp/claude-501/<project>/<session-id>/ of sessions that are
    over - no live process, not continued by a live one, no workflow journal within 2 h, no
    transcript or file change within 24 h - and that no tool or hook names (5f3e1301's files are
    read by the precheck tests, so it stays)."""
    rule, items = "dead-session-dir", []
    cut = env.cutoff(STALE_HOURS)
    try:
        projects = sorted(p for p in env.tmp_root.iterdir() if p.is_dir() and not p.is_symlink())
    except OSError:
        return []
    for proj in projects:
        try:
            dirs = sorted(d for d in proj.iterdir() if UUID_NAME.match(d.name) and d.is_dir())
        except OSError:
            continue
        for d in dirs:
            sid = d.name
            why = ("session running (or continued by a running one)" if sid in ctx.live_ids else None) \
                or (f"its workflow journal was written within {ACTIVE_HOURS} h" if sid in ctx.journal_ids else None) \
                or ("a tool, hook or repo file names this session (reused)" if sid in ctx.ref_ids else None)
            if not why:
                for t in env.projects.glob(f"*/{sid}.jsonl"):
                    if os.path.getmtime(t) > cut:
                        why = f"transcript written {ago(str(t))}"
                for sub in env.projects.glob(f"*/{sid}"):
                    if not why and changed_since(str(sub), cut):
                        why = f"subagent transcripts written within {STALE_HOURS} h"
            if not why and changed_since(str(d), cut):
                why = f"a file in it changed within {STALE_HOURS} h"
            why = why or guard(env, ctx, str(d))
            items.append(keep(rule, str(d), why) if why else Item(rule, str(d)))
    return items


def git_link_inside(path: str) -> str | None:
    """A `.git` file (a linked worktree of some repo, maybe outside ~/Claude) or a clone whose
    .git/worktrees is not empty (it has linked trees elsewhere) under path, else None."""
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.name == ".git" and e.is_file(follow_symlinks=False):
                        return f"holds a linked git worktree ({d})"
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    if e.name == ".git":
                        if any(os.scandir(os.path.join(e.path, "worktrees"))):
                            return f"holds a repo with linked worktrees ({d})"
                        continue
                except OSError:
                    continue
                stack.append(e.path)
    return None


def live_scratch(env: Env, ctx: Ctx, rule: str, hours: float) -> list[Item]:
    """Subdirectories and big top-level files of a running session's scratchpad/. Only entries of
    scratchpad/ are judged: the session dir, scratchpad/ itself and tasks/ (symlinks into
    ~/.claude) never are."""
    items = []
    try:
        projects = sorted(p for p in env.tmp_root.iterdir() if p.is_dir() and not p.is_symlink())
    except OSError:
        return []
    for proj in projects:
        for sid in sorted(ctx.live_ids):
            sp = proj / sid / "scratchpad"
            if sp.is_symlink() or not sp.is_dir():
                continue
            if sid in ctx.ref_whole:
                items.append(keep(rule, str(sp), "a tool, hook or repo file names this session (reused)"))
                continue
            named = ctx.ref_entries.get(sid, set())
            try:
                entries = sorted(os.scandir(sp), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                try:
                    if e.is_symlink():
                        continue
                    is_dir = e.is_dir(follow_symlinks=False)
                    if not is_dir and (not e.is_file(follow_symlinks=False)
                                       or e.stat(follow_symlinks=False).st_size < BIG_FILE_BYTES):
                        continue
                except OSError:
                    continue
                p = norm(e.path)
                hit = changed_since(p, env.cutoff(hours), ctime=True)
                why = f"changed within {hours} h ({hit})" if hit else None
                if not why:
                    why = next((f"holds the registered git worktree {w.path}" for w in ctx.worktrees
                                if within(w.path, p) or within(p, w.path)), None)
                if not why and e.name in named:
                    why = f"a tool, hook or repo file names scratchpad/{e.name} (reused)"
                if not why and is_dir:
                    why = git_link_inside(p)
                if not why and re.search(r"scratchpad/" + re.escape(e.name) + r"(?![A-Za-z0-9._-])",
                                         ctx.journal_text):
                    why = (f"a running workflow (journal, script or agent prompt) or subagent "
                           f"active within {ACTIVE_HOURS} h names it")
                why = why or guard(env, ctx, p)
                items.append(keep(rule, p, why) if why else Item(rule, p))
    return items


def rule_live_session_scratch(env: Env, ctx: Ctx) -> list[Item]:
    """10-16 Low disk space at 9 GB free: the acceptance session had run for days, so the
    dead-session rule kept its whole tmp dir while its scratchpad/ held 8.8 GB of finished
    subagents' leftovers (review copies of origin/main, a DerivedData copy, unpacked sources),
    none touched for hours. Each subdirectory of a running session's scratchpad/ (and each
    top-level file of BIG_FILE_BYTES or more) goes once nothing in it changed within 24 h (mtime
    or ctime: unpacked trees keep old mtimes), no process has a file in it open or as cwd, it
    neither is nor holds a git worktree, and no workflow or subagent active within 2 h names it
    (journal, script or agent prompt). An entry a tool names stays; if a tool names the session
    dir or scratchpad/ itself, all of it stays."""
    return live_scratch(env, ctx, "live-session-scratch", STALE_HOURS)


def rule_live_session_scratch_floor(env: Env, ctx: Ctx) -> list[Item]:
    """Below the floor: the same scratchpad entries after 2 h idle."""
    return live_scratch(env, ctx, "live-session-scratch-2h", ACTIVE_HOURS)


def rule_known_build_outputs(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory row 11: $TMPDIR/precheck-* (hook-test copies), ~/Claude/transit-app/build (an
    old Xcode build, git-ignored) and remote-ref/tools/bugexam/xcr-dd (old DerivedData, no
    reference in BOARD or task evidence). Idle 24 h, unopened; inside a repo it must be ignored."""
    rule, items = "known-build-output", []
    for p in env.known_outputs():
        if not p.exists():
            continue
        why = f"changed {ago(str(p))}" if changed_since(str(p), env.cutoff(STALE_HOURS)) else None
        top = run(["git", "-C", str(p.parent), "rev-parse", "--show-toplevel"])
        if not why and top is not None and top.returncode == 0:
            ign = git(top.stdout.strip(), "check-ignore", "-q", str(p))
            if ign is None or ign.returncode != 0:
                why = "inside a repo and not git-ignored"
        why = why or guard(env, ctx, str(p))
        items.append(keep(rule, str(p), why) if why else Item(rule, str(p)))
    return items


def money_dd(env: Env, ctx: Ctx, rule: str, hours: float) -> list[Item]:
    items = []
    for p in ctx.money_dd:
        why = (f"changed {ago(p)}" if changed_since(p, env.cutoff(hours)) else None) \
            or ("a tool, hook or repo file names its path (reused)" if sorted_hit(ctx.ref_paths, p) else None) \
            or (f"a tool builds into a folder of this name (-derivedDataPath .../{os.path.basename(p)})"
                if os.path.basename(p) in ctx.dd_names else None) \
            or (f"a running workflow or subagent active within {ACTIVE_HOURS} h names it"
                if re.search(re.escape(p) + r"(?![A-Za-z0-9._-])", ctx.journal_text) else None) \
            or guard(env, ctx, p)
        items.append(keep(rule, p, why) if why else Item(rule, p))
    return items


def rule_money_derived_data(env: Env, ctx: Ctx) -> list[Item]:
    """10-18 inventory A5 (5.75 GB): app sessions built with -derivedDataPath into evidence and
    BOARD folders under ~/Money/styl-work. A folder holding Build/ plus an Index /
    CompilationCache / ModuleCache .noindex is xcodebuild output, rebuilt from the commit; it
    goes once nothing in it changed within 24 h, nothing has it open and no tool or running
    workflow names its path, nor passes a folder of its name to -derivedDataPath (axdump.sh builds
    into "$HERE/../axdump-dd" and reuses it). Only that folder goes: the screenshots and reference sets beside it,
    which app-page-references.txt and the hooks name, stay."""
    return money_dd(env, ctx, "money-derived-data", STALE_HOURS)


def rule_money_derived_data_floor(env: Env, ctx: Ctx) -> list[Item]:
    """Below the floor: the same after 2 h idle."""
    return money_dd(env, ctx, "money-derived-data-2h", ACTIVE_HOURS)


# ---- rebuildable caches --------------------------------------------------------------------

def cache_item(env: Env, ctx: Ctx, rule: str, path: Path, tool: str, cmd: list[str],
               idle_hours: float) -> list[Item]:
    if not path.is_dir():
        return []
    if shutil.which(tool) is None:
        return [keep(rule, str(path), f"{tool} not found")]
    why = (f"changed {ago(str(path))}" if changed_since(str(path), env.cutoff(idle_hours)) else None) \
        or guard(env, ctx, str(path))
    if why:
        return [keep(rule, str(path), why)]
    return [Item(rule, str(path), action="cmd", cmd=[shutil.which(tool) or tool, *cmd[1:]],
                 upper_bound=True)]


def rule_uv_cache(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory row 12: `uv cache prune` drops only entries no environment uses (uv docs:
    https://docs.astral.sh/uv/concepts/cache/#clearing-the-cache); uv locks the cache itself."""
    return cache_item(env, ctx, "uv-cache", env.home / ".cache/uv", "uv", ["uv", "cache", "prune"], 0)


def rule_brew_cache(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory row 12: `brew cleanup --prune=all` - downloads and old kegs, all re-fetchable
    (https://docs.brew.sh/Manpage#cleanup-options-formulacask-)."""
    return cache_item(env, ctx, "brew-cache", env.home / "Library/Caches/Homebrew", "brew",
                      ["brew", "cleanup", "--prune=all"], ACTIVE_HOURS)


def rule_go_cache(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory row 12: `go clean -cache` empties the build cache, rebuilt on the next build
    (https://pkg.go.dev/cmd/go#hdr-Build_and_test_caching)."""
    return cache_item(env, ctx, "go-build-cache", env.home / "Library/Caches/go-build", "go",
                      ["go", "clean", "-cache"], STALE_HOURS)


def rule_pyright_cache(env: Env, ctx: Ctx) -> list[Item]:
    """Inventory row 12: ~/.cache/pyright-python is the npm copy of pyright the pip wrapper
    downloads on first use; idle 24 h and unopened it goes and comes back on the next run."""
    p = env.home / ".cache/pyright-python"
    if not p.is_dir():
        return []
    why = (f"changed {ago(str(p))}" if changed_since(str(p), env.cutoff(STALE_HOURS)) else None) \
        or guard(env, ctx, str(p))
    return [keep("pyright-cache", str(p), why) if why else Item("pyright-cache", str(p))]


def rule_unavailable_simulators(env: Env, ctx: Ctx) -> list[Item]:
    """The one simulator removal allowed: `xcrun simctl delete unavailable` (devices whose runtime
    is gone and that cannot boot). Simulators themselves and what is installed on them are reused
    and never touched."""
    if shutil.which("xcrun") is None:
        return []
    r = run(["xcrun", "simctl", "list", "-j", "devices", "unavailable"])
    try:
        devs = [d for lst in json.loads(r.stdout)["devices"].values() for d in lst] if r else []
    except (ValueError, KeyError, AttributeError):
        return []
    if not devs:
        return []
    return [Item("unavailable-simulator", f"{len(devs)} unavailable simulator(s)", action="cmd",
                 cmd=["xcrun", "simctl", "delete", "unavailable"])]


NORMAL_RULES = [rule_merged_worktrees, rule_stale_registrations, rule_derived_data, rule_old_gradle,
                rule_gradle_transforms, rule_old_swift_toolchains, rule_dead_session_dirs,
                rule_live_session_scratch, rule_known_build_outputs, rule_money_derived_data,
                rule_uv_cache, rule_brew_cache, rule_go_cache, rule_pyright_cache,
                rule_unavailable_simulators]
FLOOR_RULES = [rule_merged_worktrees_floor, rule_derived_data_floor, rule_shared_derived_caches,
               rule_idle_build_outputs, rule_live_session_scratch_floor, rule_gradle_transforms_floor,
               rule_money_derived_data_floor]
# Floor rules that only repeat a normal rule with a shorter window: their KEEP lines would
# repeat what the normal pass already printed.
QUIET_KEEPS = {"merged-worktree-2h", "derived-data-2h", "live-session-scratch-2h", "gradle-transforms-2h",
               "money-derived-data-2h"}


# ---- running -------------------------------------------------------------------------------

def free_bytes(env: Env) -> int:
    f = os.environ.get("DISK_TIDY_FREE_BYTES")
    return int(f) if f else shutil.disk_usage(env.home).free


def human(k: int | None) -> str:
    if k is None:
        return "?"
    for unit, div in (("G", 1 << 20), ("M", 1 << 10)):
        if k >= div:
            return f"{k / div:.1f}{unit}"
    return f"{k}K"


def _chmod_retry(func, path, _exc) -> None:
    """rmtree hit a read-only directory (Xcode and SwiftPM leave some): make it writable, retry."""
    os.chmod(os.path.dirname(path), stat.S_IRWXU)
    if os.path.isdir(path) and not os.path.islink(path):
        os.chmod(path, stat.S_IRWXU)
    func(path)


def apply_one(env: Env, ctx: Ctx, it: Item) -> str | None:
    """Do it. Returns an error text, or None on success. The guard runs again right before."""
    if it.action in ("rm", "worktree") or (it.action == "cmd" and it.path.startswith("/")):
        ctx.in_use = open_paths()                      # fresh: minutes may have passed
        why = guard(env, ctx, it.path) if it.rule != "stale-registration" else None
        if why:
            return f"refused at removal time: {why}"
    if it.action == "rm":
        try:
            if os.path.isdir(it.path) and not os.path.islink(it.path):
                shutil.rmtree(it.path, onexc=_chmod_retry)
            else:
                os.remove(it.path)
        except OSError as e:
            return f"rm failed: {e}"
        return None
    if it.action == "worktree":
        if dirty(it.path):
            return "refused at removal time: uncommitted changes"
        r = run(["git", "-C", it.repo or "", "worktree", "remove", it.path], timeout=TOOL_TIMEOUT_S)
        if r is None or r.returncode != 0:
            return "git worktree remove failed: " + ((r.stderr or r.stdout).strip() if r else "no answer")
        return None
    envx = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_ENV_HINTS="1")
    r = run(it.cmd or [], timeout=TOOL_TIMEOUT_S, env=envx)
    if r is None or r.returncode != 0:
        return f"{' '.join(it.cmd or [])} failed: " + ((r.stderr or r.stdout).strip()[-300:] if r else "no answer")
    return None


def log_line(env: Env, it: Item, size_k: int | None) -> None:
    env.log.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with env.log.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp}\t{it.rule}\t{it.path}\t{'' if size_k is None else size_k}K\n")


def measure(items: list[Item]) -> None:
    todo = [i for i in items if i.keep is None and i.size_k is None and i.path.startswith("/")]
    with ThreadPoolExecutor(8) as ex:
        for it, k in zip(todo, ex.map(lambda i: (_wait_not_background(), du_k(i.path))[1], todo), strict=True):
            it.size_k = k


def run_pass(env: Env, ctx: Ctx, rules: list, apply: bool, seen: set[str],
             totals: dict[str, list[int]]) -> int:
    """Run the rules, print each decision, apply when asked. Returns how many removals failed."""
    def covered(i: Item) -> bool:
        return i.keep is None and i.action != "cmd" and any(within(i.path, s) for s in seen)

    items: list[Item] = []
    for rule in rules:
        items += [i for i in rule(env, ctx) if not covered(i)]
    measure(items)
    failed = 0
    for it in items:
        if it.keep is not None:
            if it.rule not in QUIET_KEEPS:
                print(f"keep          {it.rule:<22} {it.path}  -- {it.keep}")
            continue
        if covered(it):                              # inside something removed in this run
            continue
        if it.action != "cmd":
            seen.add(it.path)
        size = ("<=" if it.upper_bound else "") + human(it.size_k)
        what = it.path if it.action != "cmd" else f"{it.path}  ({' '.join(it.cmd or [])})"
        if not apply:
            print(f"would-remove  {it.rule:<22} {size:>9}  {what}")
        else:
            before = du_k(it.path) if it.upper_bound else it.size_k
            err = apply_one(env, ctx, it)
            if err:
                failed += 1
                print(f"FAILED        {it.rule:<22} {size:>9}  {what}  -- {err}")
                continue
            freed = (before or 0) - (du_k(it.path) or 0) if it.upper_bound else it.size_k
            it.size_k, it.upper_bound = freed, False
            log_line(env, it, freed)
            print(f"removed       {it.rule:<22} {human(freed):>9}  {what}")
        t = totals.setdefault(it.rule, [0, 0, 0])
        t[0] += 1
        t[1] += it.size_k or 0
        t[2] |= it.upper_bound
    return failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="remove (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="only print (the default)")
    ap.add_argument("--floor-gb", type=float, default=FLOOR_GB,
                    help="below this much free space the floor rules run too")
    ap.add_argument("--aggressive", action="store_true", help="run the floor rules regardless")
    args = ap.parse_args(argv)
    apply = args.apply and not args.dry_run
    env = Env.from_environ()
    env.lock.parent.mkdir(parents=True, exist_ok=True)
    lock = env.lock.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another disk-tidy run holds the lock; nothing done")
        return 0
    ctx = snapshot(env)
    free = free_bytes(env)
    print(f"disk-tidy {time.strftime('%Y-%m-%d %H:%M')}  {'APPLY' if apply else 'dry run'}  "
          f"free {free / 2**30:.1f} GiB  floor {args.floor_gb:g} GB")
    if ctx.in_use is None:
        print("lsof failed: every removal is refused this run")
    totals: dict[str, list[int]] = {}
    seen: set[str] = set()
    failed = run_pass(env, ctx, NORMAL_RULES, apply, seen, totals)
    after = free_bytes(env) if apply else free + sum(t[1] for t in totals.values()) * 1024
    if args.aggressive or after < args.floor_gb * 1e9:
        print(f"-- floor rules: free {'is' if apply else 'would be'} {after / 2**30:.1f} GiB "
              f"(floor {args.floor_gb:g} GB){' / --aggressive' if args.aggressive else ''}")
        failed += run_pass(env, ctx, FLOOR_RULES, apply, seen, totals)
    print("-- summary (rule, count, size)")
    total = 0
    for rule, (n, k, ub) in sorted(totals.items(), key=lambda kv: -kv[1][1]):
        total += k
        print(f"  {rule:<22} {n:>4}  {('<=' if ub else '') + human(k):>9}")
    print(f"  {'total':<22} {sum(t[0] for t in totals.values()):>4}  {human(total):>9}"
          f"  {'removed' if apply else 'would be removed'}"
          f"{' (cache sizes are upper bounds)' if any(t[2] for t in totals.values()) else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
