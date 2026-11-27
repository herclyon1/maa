"""Mac operational tools: disk-tidy, order inbox CLI, and deploy smoke gates."""
from __future__ import annotations

# ruff: noqa: PLC0415
import os as _os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, stage_mac_script, tmpdir

# Prefer the active latest Python (4x faster startup than macOS /usr/bin/python3 stub) for bash sub-scripts.
_PY_BIN = Path(sys.executable).parent
if (_PY_BIN / "python3").exists():
    _os.environ["PATH"] = f"{_PY_BIN}:{_os.environ.get('PATH', '')}"

_SHARED = (check, fails, require, tmpdir)


def _part_disk_tidy():  # noqa: C901
    import importlib.util
    import json
    import os
    import re
    import shutil
    import subprocess
    import time

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay" / "tests"))

    TOOL = ROOT / "scripts" / "mac" / "disk-tidy.py"
    spec = importlib.util.spec_from_file_location("disk_tidy", TOOL)
    dt = importlib.util.module_from_spec(spec)
    sys.modules["disk_tidy"] = dt          # dataclasses look the module up while it loads
    spec.loader.exec_module(dt)


    BASE = tmpdir("disktidy-").resolve()
    HOME = BASE / "home"
    TMP_ROOT = BASE / "claude-501"
    TDIR = BASE / "T"
    CLONES = BASE / "X/com.google.Chrome.code_sign_clone"
    BREW = BASE / "brew"
    STUBS = BASE / "bin"
    CALLS = BASE / "calls.log"
    OPEN = BASE / "open-paths.txt"
    PROCS = BASE / "procs.txt"
    GIT_ENV = dict(os.environ, HOME=str(HOME), GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_NOSYSTEM="1",
                   GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="core.logAllRefUpdates", GIT_CONFIG_VALUE_0="false",
                   GIT_CONFIG_KEY_1="gc.auto", GIT_CONFIG_VALUE_1="0")
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


    def add_wt(path, extra_commit=False, template_wt=None, head_sha=None):
        path = Path(path)
        if template_wt is not None and not extra_commit and head_sha:
            name = path.name
            path.mkdir(parents=True, exist_ok=True)
            (REPO / ".git" / "refs" / "heads" / name).write_text(head_sha + "\n", encoding="utf-8")
            wt_meta = REPO / ".git" / "worktrees" / name
            wt_meta.mkdir(parents=True, exist_ok=True)
            (wt_meta / "HEAD").write_text(f"ref: refs/heads/{name}\n", encoding="utf-8")
            (wt_meta / "commondir").write_text("../..\n", encoding="utf-8")
            (wt_meta / "gitdir").write_text(f"{path}/.git\n", encoding="utf-8")
            shutil.copy2(REPO / ".git" / "worktrees" / template_wt / "index", wt_meta / "index")
            (path / ".git").write_text(f"gitdir: {wt_meta}\n", encoding="utf-8")
            shutil.copy2(REPO / "a.txt", path / "a.txt")
            shutil.copy2(REPO / ".gitignore", path / ".gitignore")
            return path
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

        head_sha = sh("git", "-C", REPO, "rev-parse", "origin/main").strip()
        add_wt(WT / "wt-old")
        for name in ("wt-new", "wt-dirty", "wt-cwd", "wt-journal", "wt-named", "wt-locked",
                     "wt-5h", "wt-gone"):
            add_wt(WT / name, template_wt="wt-old", head_sha=head_sha)
        add_wt(WT / "wt-unmerged", extra_commit=True)
        for p in (HOME / "Claude/maa-automation-sib", HOME / "Claude/maa-automation-data",
                  HOME / "Claude/other-fix", HOME / "Money/styl-work/ds-relay-tree", HOME / "Money/other-tree"):
            add_wt(p, template_wt="wt-old", head_sha=head_sha)
        for name in ("wt-old", "wt-dirty", "wt-unmerged"):
            write(WT / name / ".build/out.o", "obj")
        write(WT / "wt-unmerged/.swiftpm/state", "s")
        write(WT / "wt-dirty/notes.txt", "uncommitted")
        sh("git", "-C", REPO, "worktree", "lock", WT / "wt-locked")
        shutil.rmtree(WT / "wt-gone")

        # Claude sessions: tmp dirs, the session registry, transcripts, a live workflow journal.
        proj = TMP_ROOT / "-Users-x"
        for sid in U.values():
            write(proj / sid / "scratchpad/f.txt")
        write(TMP_ROOT / "disk-tidy/inventory.md")
        write(HOME / ".claude/sessions/1.json", json.dumps({"pid": os.getpid(), "sessionId": U["live"]}))
        write(HOME / f".claude/projects/-Users-x/{U['live']}.jsonl",
              f'{{"m": "read the full transcript at: {HOME}/.claude/projects/-Users-x/{U["pred"]}.jsonl\\nContinue"}}\n')
        write(HOME / f".claude/projects/-Users-x/{U['transcript']}.jsonl", "{}\n")
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
        # Chrome's code-signing clones: X beside the T dir (DISK_TIDY_TMPDIR = BASE/T).
        for n in ("code_sign_clone.Old1", "code_sign_clone.Open1", "other"):
            write(CLONES / n / "Google Chrome.app.bundle/Contents/MacOS/Google Chrome")
            age(CLONES / n, 72)
        write(CLONES / "code_sign_clone.New1/Google Chrome.app.bundle/Contents/MacOS/Google Chrome")

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
        add_wt(sp / "sp-wt", template_wt="wt-old", head_sha=head_sha)
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
        write(OPEN, f"{WT / 'wt-cwd' / 'sub'}\n{proj / U['live'] / 'scratchpad/sp-open/deep/f.txt'}\n"
                    f"{CLONES / 'code_sign_clone.Open1/Google Chrome.app.bundle/Contents/MacOS/Google Chrome'}\n")
        write(PROCS, "launchd\nzsh\n")


    def tool(*args, free=10 ** 15, cli=False):
        env_patch = dict(HOME=str(HOME), PATH=f"{STUBS}:{os.environ['PATH']}",
                         DISK_TIDY_TMP_ROOT=str(TMP_ROOT), DISK_TIDY_TMPDIR=str(TDIR),
                         DISK_TIDY_BREW_PREFIX=str(BREW), DISK_TIDY_OPEN_PATHS=str(OPEN),
                         DISK_TIDY_PROCS=str(PROCS), DISK_TIDY_FREE_BYTES=str(free),
                         DISK_TIDY_NOW=str(NOW), GIT_CONFIG_NOSYSTEM="1")
        if cli:
            env = dict(GIT_ENV, **env_patch)
            r = subprocess.run([sys.executable, str(TOOL), *args], env=env, capture_output=True, text=True,
                               timeout=300)
            if r.returncode not in (0, 1):
                print(r.stdout, r.stderr)
            return r
        import contextlib
        import io
        import types
        saved_env = {k: os.environ.get(k) for k in env_patch}
        saved_run = dt.run
        stub_names = {"uv", "brew", "go", "swiftly", "xcrun"}

        def fast_run(cmd_args, cwd=None, timeout=dt.GIT_TIMEOUT_S, env=None):
            if cmd_args:
                base_cmd = os.path.basename(str(cmd_args[0]))
                if base_cmd == "du" and len(cmd_args) == 3 and cmd_args[1] == "-sk":
                    p = Path(cmd_args[2])
                    if not p.exists():
                        return subprocess.CompletedProcess(cmd_args, 1, "", "")
                    blocks = 0
                    try:
                        blocks += p.lstat().st_blocks
                        if p.is_dir() and not p.is_symlink():
                            for dp, dns, fns in os.walk(p):
                                for n in dns + fns:
                                    try:
                                        blocks += os.lstat(os.path.join(dp, n)).st_blocks
                                    except OSError:
                                        pass
                    except OSError:
                        return subprocess.CompletedProcess(cmd_args, 1, "", "")
                    kb = max(1, (blocks + 1) // 2) if blocks else 0
                    return subprocess.CompletedProcess(cmd_args, 0, f"{kb}\t{cmd_args[2]}\n", "")
                if base_cmd in stub_names:
                    with open(CALLS, "a", encoding="utf-8") as fh:
                        fh.write(" ".join([base_cmd, *[str(x) for x in cmd_args[1:]]]) + "\n")
                    out_s = ""
                    if base_cmd == "swiftly" and len(cmd_args) >= 3 and cmd_args[1] == "uninstall":
                        shutil.rmtree(HOME / f"Library/Developer/Toolchains/swift-{cmd_args[2]}-RELEASE.xctoolchain",
                                      ignore_errors=True)
                    elif base_cmd == "xcrun" and len(cmd_args) >= 4 and cmd_args[3] == "-j":
                        out_s = '{"devices": {"rt": [{"name": "old", "udid": "U1"}]}}\n'
                    return subprocess.CompletedProcess(cmd_args, 0, out_s, "")
            return saved_run(cmd_args, cwd=cwd, timeout=timeout, env=env)

        os.environ.update(env_patch)
        dt.run = fast_run
        out_buf, err_buf = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                rc = dt.main(list(args))
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
        finally:
            dt.run = saved_run
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return types.SimpleNamespace(returncode=rc, stdout=out_buf.getvalue(), stderr=err_buf.getvalue())


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
            HOME / "Money/styl-work/evidence/x/dd", HOME / "Money/styl-work/evidence/deep/a/b/dd",
            CLONES / "code_sign_clone.Old1"]
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
        CLONES / "code_sign_clone.Open1": "running process",
        CLONES / "code_sign_clone.New1": "changed within 24",
    }
    UNTOUCHED = [HOME / "Money/styl-work/BOARD/OPEN.md", HOME / "Documents/mine.txt", TMP_ROOT / "disk-tidy",
                 HOME / ".gradle/caches/modules-2", dd / "ModuleCache.noindex", SP, SP / "small.log",
                 proj / U["live"] / "tasks", HOME / "Money/styl-work/evidence/y/dd",
                 HOME / "Money/styl-work/evidence/x/a.png", HOME / "Money/styl-work/evidence/x",
                 CLONES, CLONES / "other"]

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
          all(re.match(r"^\d{4}-\d\d-\d\dT[\d:]+[+-]\d{4}\t[a-z0-9-]+\t\S.*\t(?:<=)?\d*K$", ln) for ln in log), True)
    check("a removed clone logs its size as an upper bound (blocks shared with the app)",
          [ln.split("\t")[3][:2] for ln in log if ln.split("\t")[1] == "chrome-sign-clone"], ["<="])
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
                    (TMP_ROOT, "not in a place"),
                    (CLONES, "not in a place"),
                    (CLONES / "other", "not in a place")):
        got = dt.guard(env, ctx, str(p)) or ""
        check(f"guard refuses {p.relative_to(BASE)}", want in got, True)
    check("guard allows a dead session dir", dt.guard(env, ctx, str(proj / U["cwd"])), None)

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
        os.environ["DISK_TIDY_OPEN_PATHS"] = str(OPEN)
    ctx.in_use = saved

    print("[chrome clones: while Chrome runs, the clone it runs from must show open]")
    old2 = CLONES / "code_sign_clone.Old2"
    write(old2 / "Google Chrome.app.bundle/Contents/MacOS/Google Chrome")
    age(old2, 72, NOW)

    def clone_keep(procs, in_use):
        ctx.procs, ctx.in_use = procs, sorted(in_use)
        return {i.path: i.keep for i in dt.rule_chrome_sign_clones(env, ctx)}.get(str(old2), "-")

    no_clone_open = [x for x in saved if "code_sign_clone" not in x]
    check("Chrome running, no clone shows open: an idle clone stays",
          "unknown" in (clone_keep({"launchd", "Google Chrome"}, no_clone_open) or ""), True)
    check("Chrome not running, nothing open: the idle clone goes", clone_keep({"launchd"}, no_clone_open), None)
    check("Chrome running from this clone: it stays",
          "running process" in (clone_keep({"Google Chrome"}, no_clone_open + [str(
              old2 / "Google Chrome.app.bundle/Contents/MacOS/Google Chrome")]) or ""), True)
    check("Chrome running from another clone: this idle one goes",
          clone_keep({"Google Chrome"}, saved), None)
    check("Chrome running straight from the app (no clone): the idle clone goes",
          clone_keep({"Google Chrome"}, no_clone_open + [dt.CHROME_APP_BIN]), None)
    check("ps gave nothing and no clone shows open: the idle clone stays",
          "unknown" in (clone_keep(set(), no_clone_open) or ""), True)
    ctx.procs, ctx.in_use = dt.proc_names(), saved
    nobrew = dt.Env(HOME, TMP_ROOT, TDIR, BASE / "no-brew", NOW)
    write(HOME / ".gradle/caches/9.7.0/f")
    age(HOME / ".gradle/caches/9.7.0", 72, NOW)
    items = dt.rule_old_gradle(nobrew, ctx)
    check("unknown Gradle version in use: nothing goes",
          sorted({i.keep for i in items}), ["cannot tell which Gradle version is in use"])

    write(HOME / ".swiftly/config.json", json.dumps({"inUse": "6.4.1", "installedToolchains": ["6.4.1", "6.4.0"]}))
    write(HOME / "Library/Developer/Toolchains/swift-6.4.0-RELEASE.xctoolchain/usr/bin/swift")
    write(HOME / "Library/org.swift.swiftpm/swift-sdks/swift-6.4.0-RELEASE_android.artifactbundle/info.json")
    items = {i.path.rsplit("/", 1)[-1]: i for i in dt.rule_old_swift_toolchains(env, ctx)}
    check("a toolchain an installed Swift SDK needs is kept",
          (items["swift-6.4.0-RELEASE.xctoolchain"].action, items["swift-6.4.0-RELEASE.xctoolchain"].keep),
          ("rm", "needed by the Swift SDK swift-6.4.0-RELEASE_android.artifactbundle"))

    for label, ref in (("the session dir", f"/private/tmp/claude-501/-Users-x/{U['live']}/"),
                       ("scratchpad/ itself", f"/private/tmp/claude-501/-Users-x/{U['live']}/scratchpad"),
                       ("an f-string entry", f"/private/tmp/claude-501/-Users-x/{U['live']}/scratchpad/sp-{{name}}")):
        write(HOME / ".claude/hooks/h2.py", f"P = f'{ref}'\n")
        ctx.ref_ids, ctx.ref_whole, ctx.ref_entries, ctx.ref_dd_names, ctx.ref_paths, ctx.ref_gemini_ids = dt.references(
            env, ctx.repos, repo_files=ctx.repo_files)
        got = {i.path: i.keep or "" for i in dt.rule_live_session_scratch(env, ctx)}
        check(f"a tool naming {label} keeps the whole scratchpad",
              (list(got), "names this session" in got.get(str(SP), "")), ([str(SP)], True))
    write(HOME / ".claude/hooks/h2.py", "\n")

    tf = HOME / ".gradle/caches/9.8.1/transforms"
    write(tf / "t/f")
    age(tf, 72, NOW)
    rule_tf = getattr(dt, "rule_gradle_transforms", lambda e, c: [])
    write(PROCS, "launchd\n/usr/bin/java -Xmx2g -cp gradle-daemon-main-9.8.1.jar "
             "org.gradle.launcher.daemon.bootstrap.GradleDaemon 9.8.1\n")
    ctx.gradle_running = dt.gradle_running()
    got = {i.path: i.keep for i in rule_tf(env, ctx)}.get(str(tf), "-")
    check("gradle transforms kept while a Gradle daemon runs", "Gradle" in (got or ""), True)
    write(PROCS, "launchd\n")
    ctx.gradle_running = dt.gradle_running()
    got = {i.path: i.keep for i in rule_tf(env, ctx)}.get(str(tf), "-")
    check("gradle transforms go when no Gradle runs", got, None)
    write(tf / "t/g")
    age(tf / "t/g", 1, NOW)
    got = {i.path: i.keep for i in rule_tf(env, ctx)}.get(str(tf), "-")
    check("gradle transforms changed 1 h ago are kept", "changed" in (got or ""), True)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


def _part_order_now_confirmed():
    """scripts/mac/order-now.sh refuses a changing order without "confirmed": true."""
    import json
    import os
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = stage_mac_script(ROOT, "order-now.sh")
    sys.path.insert(0, str(ROOT / "relay"))
    from ark_relay.features.commands import MUTATING


    py_dir = str(Path(sys.executable).parent)

    def run(body: dict, home: str) -> tuple[int, str, bool]:
        """(exit code, output, whether the fake curl was called)."""
        sent = Path(home) / "curl-called"
        sent.unlink(missing_ok=True)
        env = {**os.environ, "HOME": home, "PATH": f"{home}/bin:{py_dir}:{os.environ['PATH']}"}
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
    """scripts/mac/order.sh writes the inbox to main only."""
    import json
    import os
    import shutil
    import subprocess
    import tempfile

    SCRIPT = stage_mac_script(Path(__file__).resolve().parents[2], "order.sh")


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


    py_dir = str(Path(sys.executable).parent)

    def run(work, tmp, *args):
        env = dict(os.environ, HOME=str(tmp / "home"), PATH=f"{py_dir}:{os.environ['PATH']}")
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
    """deploy-pkg.sh under macOS /bin/bash 3.2, a UTF-8 locale and set -u."""
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
    """deploy-relay.sh: the smoke runs before COS, and a failed smoke takes the way back."""
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


def _part_wingui_guards():
    """scripts/mac/wingui.sh (2026-11-19): no input while the echo farm runs, a launch budget
    that covers the machine's own wait, ERR is a non-zero exit, every call logged."""
    import json
    import os
    import re
    import subprocess

    ROOT = Path(__file__).resolve().parents[2]
    MAC = ROOT / "scripts" / "mac"
    WINGUI = stage_mac_script(ROOT, "wingui.sh")
    FAKE = tmpdir("wingui-")
    (FAKE / "bin").mkdir()
    (FAKE / "tmp").mkdir()
    # ssh: the state read answers from state.json (none = unreachable), the result read
    # from gui.txt (none = not written yet), anything else is the scheduled task.
    (FAKE / "bin" / "ssh").write_text(
        "#!/bin/sh\n"
        f"F='{FAKE}'\n"
        'case "$*" in\n'
        '  *"type C:"*ark-gui.txt*) [ -f "$F/gui.txt" ] && cat "$F/gui.txt"; exit 0 ;;\n'
        '  *state.json*) printf "%s\\n" "ssh $*" >>"$F/calls"; [ -f "$F/state.json" ] || exit 255; cat "$F/state.json" ;;\n'
        '  *) printf "%s\\n" "ssh $*" >>"$F/calls"; echo STARTED ;;\n'
        'esac\n', encoding="utf-8")
    # scp: an upload is kept as pushed-<name>, a download writes a stand-in picture.
    (FAKE / "bin" / "scp").write_text(
        "#!/bin/sh\n"
        f"F='{FAKE}'\n"
        'printf "%s\\n" "scp $*" >>"$F/calls"\n'
        'src=""; dst=""; for a in "$@"; do src="$dst"; dst="$a"; done\n'
        'case "$dst" in *:*) cp "$src" "$F/pushed-${dst##*/}" ;; *) printf PNG >"$dst" ;; esac\n',
        encoding="utf-8")
    os.symlink("/usr/bin/true", FAKE / "bin" / "sleep")   # the wait loop, instantly
    for f in (FAKE / "bin" / "ssh", FAKE / "bin" / "scp"):
        f.chmod(0o755)
    LOG = FAKE / "actions.log"
    FARM = {"queues": {"echo_farm": {"boss": 2, "name": "千傀重楼", "weekly": True,
                                     "until": "2099-11-19 21:15", "started": "2099-11-19 16:13"}}}
    PY_DIR = str(Path(sys.executable).parent)

    def run(*args: str, state: "dict | None", gui: "str | None", **extra: str):
        for name in ("calls", "state.json", "gui.txt"):
            (FAKE / name).unlink(missing_ok=True)
        for old in FAKE.glob("pushed-*"):
            old.unlink()
        for old in (FAKE / "tmp").glob("*"):
            old.unlink()
        if state is not None:
            (FAKE / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        if gui is not None:
            (FAKE / "gui.txt").write_text(gui, encoding="utf-8")
        # The action log only where a check reads it (log=True): writing it starts python3 for the redaction, and
        # thirty-odd calls of that kept this file over the deploy's 10 s a file (2026-11-20).
        env = {**os.environ, "PATH": f"{FAKE / 'bin'}:{PY_DIR}:{os.environ['PATH']}", "ARK_HOST": "test-host",
               "ARK_ACTION_LOG": str(LOG) if extra.pop("log", None) else os.devnull, "TMPDIR": str(FAKE / "tmp"), **extra}
        env.pop("ARK_GUI_WAIT", None)
        if "ARK_GUI_POLL" not in extra:
            env.pop("ARK_GUI_POLL", None)
        if "ARK_GUI_DURING_FARM" not in extra:
            env.pop("ARK_GUI_DURING_FARM", None)
        r = subprocess.run(["bash", str(WINGUI), *args], capture_output=True, env=env, timeout=60)
        calls = (FAKE / "calls").read_text(encoding="utf-8") if (FAKE / "calls").exists() else ""
        return r.returncode, (r.stderr + r.stdout).decode("utf-8", "replace"), calls

    def pushed_ps1() -> str:
        p = FAKE / "pushed-ark-gui.ps1"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    print("[echo farm running: input refused before anything reaches the machine]")
    code, out, calls = run("key", "esc", state=FARM, gui="cmd=esc\nsent esc")
    check("key refused, exit 7", code, 7)
    check("says how to stop first", "echo_farm_stop" in out, True)
    check("gives the resume order with its boss and end", '"boss": 2' in out and '"until": "21:15"' in out, True)
    check("nothing pushed, no task started", ("ark-gui.ps1" in calls, "schtasks" in calls), (False, False))
    for action in (("click", "960", "540"), ("launch",), ("focus",), ("scroll", "-3"), ("seq", "focus; wait 100")):
        check(f"{action[0]} refused too", run(*action, state=FARM, gui="x")[0], 7)

    print("\n[shot is read-only: never stopped, never reads the state]")
    code, out, calls = run("shot", state=FARM, gui="cmd=shot\nshot 1920x1080 22:00:00")
    check("shot goes through", code, 0)
    check("shot does not read the relay state", "state.json" in calls, False)

    print("\n[ARK_GUI_DURING_FARM=1 is the one way through while it farms]")
    code, out, calls = run("key", "esc", state=FARM, gui="cmd=esc\nsent esc", ARK_GUI_DURING_FARM="1")
    check("with the switch: sent", code, 0)
    check("with the switch: the state is not read", "state.json" in calls, False)

    print("\n[state unreadable: refused, not guessed]")
    code, out, calls = run("click", "1", "2", state=None, gui="cmd=click 1 2\nclicked 1,2")
    check("unreadable state: exit 7", code, 7)
    check("says it could not read it", "读不到" in out, True)

    print("\n[no farm: input goes through as before]")
    code, out, calls = run("key", "esc", state={"queues": {}}, gui="cmd=esc\nsent esc")
    check("no farm: exit 0", code, 0)
    check("no farm: the task ran", "schtasks" in calls, True)

    print("\n[a farm whose end has passed: no resume order offered]")
    old = {"queues": {"echo_farm": {**FARM["queues"]["echo_farm"], "until": "2020-01-01 08:30"}}}
    code, out, calls = run("key", "esc", state=old, gui="x")
    check("still refused while the record is there", code, 7)
    check("no resume order for a past end", '"action": "echo_farm"' in out, False)

    print("\n[launch: the wait covers the machine's own wait for the game window]")
    code, out, calls = run("launch", state={"queues": {}}, gui=None, ARK_GUI_POLL="999")
    waited = re.search(r"等了 (\d+) 秒", out)
    ps1 = pushed_ps1()
    check("no result: exit 3", code, 3)
    m = re.search(r"\.TotalSeconds -lt (\d+)\)", ps1)   # the launch wuwa wait loop
    check("the machine waits a stated number of seconds", m is not None, True)
    check("the budget is longer than that wait plus start-up",
          bool(waited and m and int(waited.group(1)) >= int(m.group(1)) + 30), True)
    check("no placeholder left in what was pushed", re.search(r"__[A-Z_]+__", ps1), None)
    check("launch wuwa passes a quality pack", "$extra = @(\"-krqlv=$pkg\") + $extra" in ps1, True)
    check("Client-Win64-Shipping.exe is refused", "别直接起 Client-Win64-Shipping.exe" in ps1, True)
    code, out, _ = run("key", "esc", state={"queues": {}}, gui=None, ARK_GUI_POLL="999")
    check("other actions keep their budget (35 s for one key)", re.search(r"等了 (\d+) 秒", out).group(1), "35")

    print("\n[ERR from the machine is a failure, the screenshot still comes back]")
    code, out, _ = run("key", "esc", state={"queues": {}},
                       gui="cmd=esc\nproc=Client-Win64-Shipping\nERR 进程 Client-Win64-Shipping 不在，按键跳过\nshot 1920x1080")
    check("ERR: exit 6", code, 6)
    check("ERR: the picture was fetched", len(list((FAKE / "tmp").glob("wingui-*.png"))), 1)

    print("\n[every call leaves one line in the action log]")
    LOG.unlink(missing_ok=True)
    run("key", "esc", state={"queues": {}}, gui="cmd=esc\nsent esc", log="1")
    run("seq", "focus\nwait 100", state={"queues": {}}, gui="cmd=focus\nfocus only", log="1")
    run("shot", state=FARM, gui="cmd=shot\nshot", log="1")
    lines = LOG.read_text(encoding="utf-8").splitlines()
    check("one line per call, a newline in the argument included", len(lines), 3)
    check("script and arguments in it", [ln.split("\t")[1:3] for ln in lines],
          [["wingui.sh", "key esc"], ["wingui.sh", "seq focus wait 100"], ["wingui.sh", "shot"]])

    print("\n[wingui with no action is a shot: let through while it farms]")
    code, out, calls = run(state=FARM, gui="cmd=shot\nshot 1920x1080")
    check("bare wingui.sh: exit 0", code, 0)
    check("bare wingui.sh: no state read", "state.json" in calls, False)

    print("\n[state shapes: no farm record, an empty one, a broken file]")
    for label, st in (("echo_farm null", {"queues": {"echo_farm": None}}), ("echo_farm {}", {"queues": {"echo_farm": {}}}),
                      ("no queues", {})):
        check(f"{label}: input goes through", run("key", "esc", state=st, gui="cmd=esc\nsent esc")[0], 0)
    (FAKE / "state.json").unlink(missing_ok=True)
    code, out, calls = run("key", "esc", state=None, gui="cmd=esc\nsent esc")
    check("no state file: refused", code, 7)
    for name in ("calls", "gui.txt"):
        (FAKE / name).unlink(missing_ok=True)
    (FAKE / "state.json").write_text("{not json", encoding="utf-8")
    env = {**os.environ, "PATH": f"{FAKE / 'bin'}:{PY_DIR}:{os.environ['PATH']}", "ARK_HOST": "test-host",
           "ARK_ACTION_LOG": os.devnull, "TMPDIR": str(FAKE / "tmp")}
    env.pop("ARK_GUI_DURING_FARM", None)
    r = subprocess.run(["bash", str(WINGUI), "key", "esc"], capture_output=True, env=env, timeout=60)
    check("broken state.json: refused", r.returncode, 7)

    print("\n[launch keeps every argument after the action, quoted or not]")
    run("launch", "wuwa", "--", "-krqlv=sd", state={"queues": {}}, gui="cmd=launch\nERR x")
    check("unquoted arguments all reach the machine", (FAKE / "pushed-ark-gui-cmd.txt").read_text(encoding="utf-8"),
          "launch wuwa -- -krqlv=sd")
    run("launch", state={"queues": {}}, gui="cmd=launch\nERR x")
    check("no argument is wuwa", (FAKE / "pushed-ark-gui-cmd.txt").read_text(encoding="utf-8"), "launch wuwa")
    ps1 = pushed_ps1()
    check("a crash box that will not close stops the launch", "ERR 残留的崩溃弹窗关不掉" in ps1, True)
    after_close = ps1[ps1.index("Start-Sleep -Seconds 3"):ps1.index("$left = @(Find-CrashBoxes)")]
    check("after WM_CLOSE the game is ended by the list taken before (its box is gone by then)",
          ("foreach ($b in $boxes)" in after_close, "Find-CrashBoxes" in after_close,
           "Get-Process -Id $b.Id" in after_close), (True, False, True))
    check("a throw in the launch branch becomes an ERR line", "ERR 起鸣潮这段出错了" in ps1, True)
    check("the game window needs a title", "$p.MainWindowTitle -and $p.MainWindowTitle -notmatch $crash" in ps1, True)
    code, out, _ = run("key", "esc", state={"queues": {}}, gui="cmd=esc\nERRATIC is not an error line\nsent esc")
    check("only a line starting with 'ERR ' counts", code, 0)

    print("\n[the log never breaks or talks to its caller]")
    DRV = FAKE / "drv"
    DRV.mkdir()
    driver = DRV / "adbdo.sh"     # named so: adbdo.sh text is masked whole
    driver.write_text("#!/bin/bash\nset -euo pipefail\n"
                      f". '{MAC / 'lib' / 'mac-action-log.sh'}'\n"
                      'ark_action_log "$@"\necho survived\n', encoding="utf-8")
    ALOG = FAKE / "drv.log"
    ALOG.write_text("", encoding="utf-8")
    ALOG.chmod(0o644)

    def drive(*args, env_extra=None, drop=()):
        e = {**os.environ, "PATH": f"{PY_DIR}:{os.environ['PATH']}", "ARK_ACTION_LOG": str(ALOG),
             "LC_CTYPE": "UTF-8", **(env_extra or {})}
        for k in drop:
            e.pop(k, None)
        r = subprocess.run(["/bin/bash", str(driver), *args], capture_output=True, env=e, timeout=30)
        return r.returncode, r.stdout, r.stderr

    rc, so, se = drive(b"ab\xff\xfecd")
    check("a non-UTF-8 argument: caller goes on", (rc, so), (0, b"survived\n"))
    check("...and says nothing on stderr", se, b"")
    # A log whose parent is a regular file: mkdir -p fails (ENOTDIR), nothing can be written.
    rc, so, se = drive("x", env_extra={"ARK_ACTION_LOG": str(ALOG / "x.log")})
    check("an unwritable log: caller goes on", (rc, so, se), (0, b"survived\n", b""))
    check("an unwritable log: nothing created", (ALOG / "x.log").exists() or not ALOG.is_file(), False)
    rc, so, _ = drive("x", drop=("HOME", "ARK_ACTION_LOG"))
    check("no HOME and no ARK_ACTION_LOG: caller goes on", (rc, so), (0, b"survived\n"))
    rc, so, _ = drive("WECOM_SECRET=abcdef123456", "password=hunter2xyz", "token=tok_9876543",
                      'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig')
    check("stdout is the caller's own only", so, b"survived\n")
    rc, so, _ = drive("text", "834221")
    text = ALOG.read_text(encoding="utf-8")
    for secret in ("abcdef123456", "hunter2xyz", "tok_9876543", "eyJhbGciOiJIUzI1NiJ9", "834221"):
        check(f"{secret[:6]}... not in the log", secret in text, False)
    check("masked, not dropped", text.count("<已隐藏>") >= 5, True)
    check("the log is 0600 (it was 0644)", oct(ALOG.stat().st_mode & 0o777), "0o600")
    check("one line per call so far", len(text.splitlines()), 3)

    print("\n[fail closed: no redact.py, or no python3, and the arguments are not written]")
    BARE = FAKE / "bare-lib"
    BARE.mkdir()
    (BARE / "mac-action-log.sh").write_text((MAC / "lib" / "mac-action-log.sh").read_text(encoding="utf-8"),
                                            encoding="utf-8")      # no ../redact.py next to it
    bare_drv = DRV / "bare.sh"
    bare_drv.write_text("#!/bin/bash\nset -euo pipefail\n"
                        f". '{BARE / 'mac-action-log.sh'}'\n"
                        'ark_action_log "$@"\necho survived\n', encoding="utf-8")
    BLOG = FAKE / "bare.log"
    r = subprocess.run(["/bin/bash", str(bare_drv), "password=hunter2xyz"], capture_output=True,
                       env={**os.environ, "ARK_ACTION_LOG": str(BLOG)}, timeout=30)
    check("no redact.py: caller goes on", (r.returncode, r.stdout), (0, b"survived\n"))
    check("no redact.py: no argument written", ("hunter2xyz" in BLOG.read_text(encoding="utf-8"),
                                                "找不到 redact.py" in BLOG.read_text(encoding="utf-8")), (False, True))
    NOPY = FAKE / "nopy-bin"
    NOPY.mkdir()
    for tool in ("basename", "dirname", "ps", "tr", "date", "mkdir", "chmod"):
        for d in ("/bin", "/usr/bin"):
            if Path(d, tool).exists():
                (NOPY / tool).symlink_to(Path(d, tool))
                break
    PLOG = FAKE / "nopy.log"
    r = subprocess.run(["/bin/bash", str(driver), "password=hunter2xyz"], capture_output=True,
                       env={"PATH": str(NOPY), "HOME": str(FAKE), "ARK_ACTION_LOG": str(PLOG)}, timeout=30)
    check("no python3: caller goes on", (r.returncode, r.stdout), (0, b"survived\n"))
    check("no python3: no argument written", ("hunter2xyz" in PLOG.read_text(encoding="utf-8"),
                                              "脱敏没跑成" in PLOG.read_text(encoding="utf-8")), (False, True))

    print("\n[a copy of wingui.sh without the lib still runs]")
    ALONE = FAKE / "alone"
    ALONE.mkdir()
    (ALONE / "wingui.sh").write_text(WINGUI.read_text(encoding="utf-8"), encoding="utf-8")
    for name in ("calls", "gui.txt"):
        (FAKE / name).unlink(missing_ok=True)
    (FAKE / "gui.txt").write_text("cmd=shot\nshot", encoding="utf-8")
    r = subprocess.run(["bash", str(ALONE / "wingui.sh"), "shot"], capture_output=True, env=env, timeout=60)
    check("no lib next to it: shot still works", r.returncode, 0)

    print("\n[the entry scripts that drive the machine all log]")
    check("the shared log file exists", (MAC / "lib" / "mac-action-log.sh").is_file(), True)
    for name in ("wingui.sh", "winps.sh", "winrun.sh", "order-now.sh", "order.sh", "run-one.sh",
                 "estop.sh", "okww-task.sh", "adbdo.sh", "deploy-relay.sh"):
        text = (MAC / name).read_text(encoding="utf-8")
        check(f"{name} logs its calls", "lib/mac-action-log.sh" in text and "ark_action_log" in text, True)


if __name__ == "__main__":
    sys.exit(run_parts([_part_disk_tidy, _part_order_now_confirmed, _part_order_push_main, _part_deploy_pkg_bash32, _part_deploy_smoke_gate,
                       _part_wingui_guards]))
