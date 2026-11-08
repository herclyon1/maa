"""The repository's own gates and tools: build notes at the deploy tip, CI green, dead helpers gone, a silent diag pull, the gamesim fetch retry, lint's test pick, number sources, release notes, the replay gate, the tests-for selector, tools importing the installed relay, unmerged fixes.

One part per former file, each run on its own (tests/_parts.py): test_build_notes_at_deploy_tip.py, test_ci_green.py, test_dead_helpers_gone.py, test_diag_pull_silent.py, test_gamesim_fetch_retry.py, test_lint_pick_tests.py, test_num_source.py, test_release_notes.py, test_replay_gate.py, test_tests_for_selector.py, test_tools_import_installed_relay.py, test_unmerged_fixes.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_build_notes_at_deploy_tip():
    """packaging/build.py builds at a deploy commit, whose RELEASE-NOTES.md is emptied.

2026-10-13 (audit of the install / switch-over block, item 3): deploy-relay.sh builds the
manifest with the notes filled in, then empties relay/RELEASE-NOTES.md and commits both
in the commit it tags with the manifest's `ref`. build.py compared every listed file with
the tree, so at each deploy tip (7ce92679, d6fb8004, 45584225) it stopped with "hash
differs: RELEASE-NOTES.md". Now the notes come from the first of the tree, `<ref>^` and
`<ref>` whose hashes match the manifest. Run on a throwaway git repo shaped like that.

    Formerly test_build_notes_at_deploy_tip.py.
    """
    import hashlib
    import json
    import subprocess
    import tempfile

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY.parent / "packaging"))

    import build


    def git(repo: Path, *args: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        "-c", "tag.gpgsign=false", *args], cwd=repo, check=True, capture_output=True)


    FILLED = "- 这次改了什么\n".encode("utf-8")


    def make_repo(root: Path) -> Path:
        """A repo whose tip is a deploy commit: manifest of the filled notes, notes emptied,
    tag relay-1 on that commit; the filled notes in its parent."""
        repo = root / "repo"
        relay = repo / "relay"
        (relay / "ark_relay").mkdir(parents=True)
        (relay / "ark_relay" / "core.py").write_text("X = 1\n", encoding="utf-8")
        (relay / "app_main.py").write_text("print('main')\n", encoding="utf-8")
        (relay / "RELEASE-NOTES.md").write_bytes(FILLED)
        names = ["ark_relay/core.py", "app_main.py", "RELEASE-NOTES.md"]
        data = {n: (relay / n).read_bytes() for n in names}
        manifest = {"version": 1, "ref": "relay-1",
                    "files": {n: hashlib.sha1(b).hexdigest() for n, b in data.items()},
                    "sha256": {n: hashlib.sha256(b).hexdigest() for n, b in data.items()}}
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "notes written")
        (relay / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (relay / "RELEASE-NOTES.md").write_bytes(b"")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "deploy: manifest 1")
        git(repo, "tag", "relay-1", "HEAD")
        return repo


    def stage_in(repo: Path, stage: Path):
        saved = build.REPO, build.RELAY
        build.REPO, build.RELAY = repo, repo / "relay"
        try:
            return build.stage_code(stage)
        except SystemExit as exc:
            return f"stopped: {str(exc).splitlines()[-1].strip()}"
        finally:
            build.REPO, build.RELAY = saved


    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        repo = make_repo(t)
        print("[a deploy tip: notes empty in the tree and at the tag, filled at the tag's parent]")
        got = stage_in(repo, t / "stage")
        check("stage_code passes", got, "1")
        staged = t / "stage" / "versions" / "1" / "RELEASE-NOTES.md"
        check("the staged notes are the deployed ones",
              staged.read_bytes() if staged.exists() else None, FILLED)
        main = t / "stage" / "versions" / "1" / "app_main.py"
        check("the other files staged as in the tree",
              main.read_text(encoding="utf-8") if main.exists() else None, "print('main')\n")

        print("[notes for the next deploy written in the tree: still the deployed ones staged]")
        (repo / "relay" / "RELEASE-NOTES.md").write_text("- 下一次的说明\n", encoding="utf-8")
        got = stage_in(repo, t / "stage2")
        check("stage_code passes", got, "1")
        staged = t / "stage2" / "versions" / "1" / "RELEASE-NOTES.md"
        check("the staged notes are the deployed ones",
              staged.read_bytes() if staged.exists() else None, FILLED)

        print("[no copy matches the manifest: stops as before]")
        m = json.loads((repo / "relay" / "manifest.json").read_text(encoding="utf-8"))
        m["sha256"]["RELEASE-NOTES.md"] = "0" * 64
        (repo / "relay" / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        got = stage_in(repo, t / "stage3")
        check("stopped on the notes", str(got).startswith("stopped: hash differs: RELEASE-NOTES.md"), True)

        print("[a code file that differs still stops it]")
        repo2 = make_repo(t / "b")
        (repo2 / "relay" / "app_main.py").write_text("print('changed')\n", encoding="utf-8")
        check("stopped on app_main.py", stage_in(repo2, t / "stage4"), "stopped: hash differs: app_main.py")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_ci_green():
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

    Formerly test_ci_green.py.
    """
    import contextlib
    import importlib.util
    import io
    import os
    import re
    import stat
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]


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


def _part_dead_helpers_gone():
    """Helpers nothing called are gone and stay gone (review 2026-10-13, s5 #10).

* Notifier.send_image / WeCom.send_image / WeCom._upload: the self-built app is in
  no automatic order (push.py --private sends text only); group images go through
  Notifier.send_group_image.
* notify._hint: advice for the self-built app's errcode 60020 inside the outage
  notice; that app is never in an automatic order, so it could never fire.
* techlog.red_items: numbered from 1 on every call (duplicate ids); add_red is the
  one writer.
* Desktop.click(x, y) was here too; it came back on 2026-10-15 with a caller: the
  launcher's 「确认」 button that no OCR pass reads (gameupdate_games._confirm_space).

Checked two ways: the names are not defined, and no relay or scripts source calls them.

    Formerly test_dead_helpers_gone.py.
    """
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.core import desktop, notify, techlog


    print("[没人调用的辅助已删掉]")
    check("Notifier.send_image", hasattr(notify.Notifier, "send_image"), False)
    check("WeCom.send_image", hasattr(notify.WeCom, "send_image"), False)
    check("WeCom._upload", hasattr(notify.WeCom, "_upload"), False)
    check("notify._hint", hasattr(notify, "_hint"), False)
    check("techlog.red_items", hasattr(techlog, "red_items"), False)
    check("群机器人发图还在", hasattr(notify.Notifier, "send_group_image"), True)
    check("按字点击还在", hasattr(desktop.Desktop, "click_text"), True)

    print("\n[也没有哪里再调用它们]")
    srcs = [p for p in (ROOT / "ark_relay").rglob("*.py") if "okww_files" not in p.parts]
    srcs += [ROOT / "service.py", ROOT / "boot_stages.py"] + list((ROOT.parent / "scripts").rglob("*.py"))
    # WeComBot.send_image (the group image) stays; scripts/mac/techlog.py has its own red_items.
    pat = re.compile(r"(?<!wecom_bot)\.send_image\(|\._upload\(|\b_hint\(|\bcore\.techlog\b.*red_items|"
                     r"\btechlog\.red_items\(")
    hits = [f"{p.name}:{i}" for p in srcs for i, ln in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
            if pat.search(ln)]
    check("没有调用处", hits, [])


def _part_diag_pull_silent():
    """diag-pull.py must not exit 0 when a record could not be fetched.

Silent-failure audit row scripts/mac/diag-pull.py:54: a per-object GET that
failed was printed to stderr, then the summary said 「新取回 N 条」 and the tool
exited 0, so a session that checks only the exit code believed every record
was on disk. The bucket deletes records after 7 days, so a missed one is lost.

    Formerly test_diag_pull_silent.py.
    """
    import contextlib
    import importlib.util
    import io

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay" / "tests"))

    spec = importlib.util.spec_from_file_location("diag_pull", ROOT / "scripts" / "mac" / "diag-pull.py")
    dp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dp)


    def run(get):
        d = tmpdir()
        dp.DEST = d / "ark-diag"
        dp.env = lambda _p: {"COS_SECRET_ID": "i", "COS_SECRET_KEY": "k", "COS_DIAG_BUCKET": "b-1"}
        dp.listing = lambda _cos: [("diag/a.json", 3, "2026-10-10T01:00:00"),
                                   ("diag/b.json", 3, "2026-10-10T02:00:00")]
        dp.get = get
        old = sys.argv
        sys.argv = ["diag-pull.py"]
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = dp.main()
        finally:
            sys.argv = old
        return rc, out.getvalue(), err.getvalue(), d


    print("[one of two records fails to fetch]")
    rc, out, err, d = run(lambda _cos, key, params="": (500, b"boom") if key == "diag/b.json" else (200, b"{}"))
    check("exit code is non-zero", rc, 1)
    check("the good record is on disk", (d / "ark-diag" / "a.json").exists(), True)
    check("the summary names the failure count", "失败 1 条" in out, True)
    check("the per-record error is still on stderr", "取回失败 500" in err, True)

    print("[every record fetched]")
    rc, out, err, d = run(lambda _cos, key, params="": (200, b"{}"))
    check("exit code is 0", rc, 0)
    check("no failure count in the summary", "失败" in out, False)


def _part_gamesim_fetch_retry():
    """gamesim ci_prepare: a failed fetch of the pinned OK-WW commit is retried, a commit that
never comes still fails.

Run 38434766518 (2026-10-14) lost lane u7-green-034a555d to one `git fetch --depth 1` of the
pinned v3.7.3 commit; the same fetch from the Mac worked at once. The lane now tries
FETCH_TRIES times before it gives up.

    Formerly test_gamesim_fetch_retry.py.
    """
    import importlib.util
    import subprocess

    HERE = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("ci_prepare", HERE / "gamesim" / "okww" / "ci_prepare.py")
    cp = importlib.util.module_from_spec(spec)
    sys.modules["ci_prepare"] = cp
    spec.loader.exec_module(cp)


    def runner(fail_first):
        calls = []

        def run(*cmd):
            calls.append(cmd)
            if len(calls) <= fail_first:
                raise subprocess.CalledProcessError(128, list(cmd), stderr="fatal: unable to access")
            return ""
        return run, calls


    waits = []
    run, calls = runner(2)
    cp.fetch_pinned(Path("w"), "https://example.invalid/r", "abc", run=run, sleep=waits.append)
    check("two failures then a fetch: three tries", len(calls), 3)
    check("waits between tries", waits, [10, 30])
    check("it fetches the pinned commit, depth 1", calls[-1][-4:], ("--depth", "1", "https://example.invalid/r", "abc"))

    waits.clear()
    run, calls = runner(99)
    try:
        cp.fetch_pinned(Path("w"), "https://example.invalid/r", "abc", run=run, sleep=waits.append)
        raised = None
    except subprocess.CalledProcessError as exc:
        raised = exc.returncode
    check("never comes: the last failure is raised", raised, 128)
    check("after FETCH_TRIES tries", len(calls), cp.FETCH_TRIES)

    run, calls = runner(0)
    cp.fetch_pinned(Path("w"), "r", "c", run=run, sleep=waits.append)
    check("a good fetch is one try", len(calls), 1)


def _part_lint_pick_tests():
    """lint-repo.sh runs only the relay tests a change reaches (scripts/mac/lib/lint_pick_tests.py).

Until 10-14 it ran every relay test (about 450 files) on each call, even for a one-line script
edit, and a session waited on that after every small fix; ~/Claude/CLAUDE.md asks to run only the
tests a change reaches. These checks pin the selection: the deploy selector's picks, plus tests
that name a changed script; everything when the selector cannot decide; nothing for a docs-only
change.

    Formerly test_lint_pick_tests.py.
    """

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "scripts/mac/lib"))
    import lint_pick_tests as lp

    # Built from parts so this file itself does not name it.
    UNNAMED_DOC = "docs/NOT-NAMED-" + "BY-ANY-TEST.md"


    check("a changed script reaches the test that names it",
          "test_disk_tidy.py" in lp.named_by_tests(["scripts/mac/disk-tidy.py"]), True)
    check("a doc no test reads names no test", lp.named_by_tests([UNNAMED_DOC]), set())

    real_tests_for, real_changed = lp.changed_covered.tests_for, lp.changed_files
    try:
        lp.changed_files = lambda base: ["scripts/mac/disk-tidy.py"]
        lp.changed_covered.tests_for = lambda base: ([], lp.NO_BEHAVIOUR + "，全量跑（便宜的保险）")
        got, _ = lp.pick("x")
        check("no relay module changed: only the tests naming the changed script", "test_disk_tidy.py" in got and len(got) < 20, True)
        lp.changed_covered.tests_for = lambda base: (["test_heartbeat.py"], "picked")
        got, _ = lp.pick("x")
        check("selector picks plus naming tests", set(got) >= {"test_heartbeat.py", "test_disk_tidy.py"}, True)
        lp.changed_covered.tests_for = lambda base: ([], "没有测试映射表，全量跑")
        check("selector cannot decide: everything", lp.pick("x")[0], None)
        lp.changed_files = lambda base: [UNNAMED_DOC]
        lp.changed_covered.tests_for = lambda base: ([], lp.NO_BEHAVIOUR)
        check("a doc no test reads: no relay test", lp.pick("x")[0], [])
    finally:
        lp.changed_covered.tests_for, lp.changed_files = real_tests_for, real_changed

    lint = (ROOT / "scripts/mac/lint-repo.sh").read_text()
    check("lint-repo.sh runs the picked list, all only on ALL or LINT_ALL_TESTS",
          "scripts/mac/lib/lint_pick_tests.py" in lint and '[ "$picked" = ALL ]' in lint and "LINT_ALL_TESTS" in lint, True)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_num_source():
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
  - all of it under diff.noprefix / diff.mnemonicPrefix / diff.renames=false;
  - lint-repo.sh runs it outside the LINT_SKIP_TESTS block.

    Formerly test_num_source.py.
    """
    import contextlib
    import importlib.util
    import io
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]


    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


    ns = load("num_source", ROOT / "scripts/mac/lib/num_source.py")


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
        # Settings that change the diff headers must not blind the parser (every case below
        # would then pass with nothing judged).
        for key, value in (("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"), ("diff.renames", "false")):
            git("config", key, value, cwd=base)
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


def _part_release_notes():
    """更新播报要说「修好了什么毛病」，不是列一串文件名。

2026-08-26 用户看到的播报是「改动文件：service.py、preupdate.py……」，
对着不看代码的人等于什么都没说。原话：「**更新内容用人话写**」。

所以 `relay/RELEASE-NOTES.md` 跟代码一起部署，播报优先念它；
没有这个文件时才退回列文件名（老行为，不能退化）。

这里测的是「说明文件在不在决定播报内容」，以及那份说明本身够不够人话——
后者用一条粗但有效的判据：**不许出现代码符号**。

    Formerly test_release_notes.py.
    """
    import re
    import tempfile

    HERE = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(HERE))

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    def render(notes_dir: Path, files: list[str]) -> str:
        """service.py 里组装播报正文的那几行，原样复刻。

    复刻而不是 import：那段逻辑埋在服务主循环里，拆出来单测要动生产代码，
    而这里真正要钉住的是「有说明文件就念说明、没有就列文件名」这个取舍。
    """
        lines = ["刚刚生效", "版本 v1 → v2"]
        notes = ""
        nf = notes_dir / "RELEASE-NOTES.md"
        if nf.exists():
            notes = nf.read_text(encoding="utf-8").strip()
        if notes:
            lines += ["", notes]
        else:
            lines.append("改动文件：" + "、".join(files) if files
                         else "（改动清单由上一版代码写入，本次没有）")
        lines += ["", "更新在开机后、队列开跑前落地，本轮直接使用新代码。"]
        return "\n".join(lines)


    def test_switch(tmp: Path) -> None:
        print("[有说明文件时念说明，没有时列文件名]")

        empty = tmp / "no-notes"
        empty.mkdir()
        body = render(empty, ["service.py", "preupdate.py"])
        check("没有说明文件 → 退回列文件名（老行为不退化）",
              "改动文件：service.py、preupdate.py" in body, True)

        withn = tmp / "with-notes"
        withn.mkdir()
        (withn / "RELEASE-NOTES.md").write_text(
            "开机预更新的两处误报修好了\n\n· MAA 明明已经下载好了，中继却说没确认到\n",
            encoding="utf-8")
        body = render(withn, ["service.py", "preupdate.py"])
        check("有说明文件 → 正文里有说明", "开机预更新的两处误报修好了" in body, True)
        check("有说明文件 → 不再列文件名", "改动文件：" in body, False)

        blank = tmp / "blank-notes"
        blank.mkdir()
        (blank / "RELEASE-NOTES.md").write_text("   \n\n  \n", encoding="utf-8")
        body = render(blank, ["service.py"])
        check("说明文件是空白 → 当作没有，退回列文件名",
              "改动文件：service.py" in body, True)


    def test_is_plain_language() -> None:
        """随仓库的那份说明本身要是人话。

    判据故意粗：**不许出现代码符号**（下划线函数名、括号调用、驼峰、路径后缀）。
    这拦不住所有术语，但拦得住「修复 `maa_update_pending()` 未识别 MirrorChyan
    zip 制品」这种——而那正是当天被点名的写法。
    """
        print("[RELEASE-NOTES.md 是不是人话]")
        nf = HERE / "RELEASE-NOTES.md"
        check("说明文件存在", nf.exists(), True)
        if not nf.exists():
            return
        text = nf.read_text(encoding="utf-8")
        if not text.strip():
            # 空是**合法状态**：部署成功后脚本会把它清零，逼下一次写新的。
            # 拦「空着就部署」是部署脚本的闸（`[ ! -s "$NOTES" ]`），不是这里的事；
            # 这里只负责「有内容的时候，内容得是人话」。
            print("  ok   文件是空的——刚部署完的正常状态，人话检查跳过")
            return

        jargon = {
            "下划线函数名": r"\b[a-z]+_[a-z_]+\(",
            "函数调用括号": r"\w+\(\)",
            "代码文件名":   r"\b\w+\.(py|json|sh|md)\b",
            "驼峰标识符":   r"\b[a-z]+[A-Z]\w+\b",
        }
        for label, rx in jargon.items():
            hit = re.search(rx, text)
            check(f"不含{label}", hit.group(0) if hit else None, None)


    def main(tmp: Path) -> int:
        test_switch(tmp)
        test_is_plain_language()
        print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        with tempfile.TemporaryDirectory() as t:
            raise SystemExit(main(Path(t)))


def _part_replay_gate():
    """Deploy gate E1: the offline replay of outcome / errwatch over the real 2026-10-06 logs.

Before a deploy, ``scripts/mac/deploy-relay.sh`` runs ``ark_relay.features.selfcheck.replay`` over
the two checked-in fixtures - the OK-WW weekly-boss run whose update note once
matched 「结晶波片不足」, and the relay.log fragment holding the banner calendar
#2 and shutdown snapshot false alarms. This test pins what the replay must see:
the current code pushes nothing, the code with one of the fixes undone pushes that
false alarm again (the producers run under the real errwatch handler), and a
genuine ERROR still pushes.

    Formerly test_replay_gate.py.
    """
    import importlib.util

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.features.verify import outcome
    from ark_relay.features.selfcheck import replay

    FIX = Path(__file__).resolve().parent / "fixtures"
    OKWW = (FIX / "okww-1006-run.log").read_text(encoding="utf-8")
    RELAY = (FIX / "relay-1006-false-alarms.log").read_text(encoding="utf-8")


    print("[OK-WW: the update note once matched 「结晶波片不足」]")
    check("this code pushes nothing", replay.okww_pushes(OKWW), [])

    orig = outcome.okww_checks


    def pre_fix_checks(text, **kw):
        """The weekly judgement before 12edfb0b, reproduced: a substring match of
    「结晶波片不足」 over every line of the log, update note included, read as an
    unclaimed week. Since 2026-10-07 a real shortage is green and is read only from
    the overlay's own skip line (outcome.WEEKLY_SHORT), so no data patch of the
    current code brings the old alarm back; the old rule is stubbed in instead."""
        out = orig(text, **kw)
        if "Teleport to Boss Weekly Challenge" in text and "结晶波片不足" in text:
            out = [c for c in out if not c.label.startswith("周本")]
            out.append(outcome.Check("周本领到了奖励", False, "结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」）"))
        return out


    outcome.okww_checks = pre_fix_checks
    try:
        old = replay.okww_pushes(OKWW)
        check("pre-fix code pushes exactly one", len(old), 1)
        check("it is the waveplate-shortage false alarm", "结晶波片不足" in (old[0] if old else ""), True)
    finally:
        outcome.okww_checks = orig

    print("[relay.log: the banner calendar #2 and shutdown snapshot false alarms]")
    check("this code pushes nothing", replay.errwatch_pushes(RELAY), [])

    # The producers run again under the real errwatch handler, so breaking one of the
    # fixes brings its false alarm back into the replay (until 2026-10-13 the quiet lines
    # were a hand list of wordings and every one of these still passed).
    from ark_relay.features.banners import banners as _hub
    from ark_relay.features.weekly import annihilation as _ann

    _cal = _hub._wuwa_calendar_start
    _hub._wuwa_calendar_start = lambda n, p, now, end, ri, notes, tr: _cal(n, p, now, end, ri, {} if notes is None else notes, tr)
    try:
        got = replay.errwatch_pushes(RELAY)
        check("the calendar read even though another source gave the time: the 10-06 pushes are back",
              sorted({p["where"] for p in got}), ["ark.banners", "ark.machinecheck"])
        check("……among them 「没找到…的日期」 and 「只有图，没读到字」",
              (any("没找到「余心所向九死未悔」的日期" in p["line"] for p in got),
               any(p["line"].startswith("这条公告只有图，没读到字") for p in got)), (True, True))
        check("……and the #2 machine check FAIL", any("#2" in p["line"] for p in got), True)
    finally:
        _hub._wuwa_calendar_start = _cal

    _down = _ann._going_down
    _ann._going_down = lambda: False
    try:
        got = replay.errwatch_pushes(RELAY)
        check("the snapshot read during the relay's own power-off: both AUTO-MAS sections push",
              [p["line"] for p in got], ["快照的 _MAS错误 这一段读不到", "快照的 _队列错误 这一段读不到"])
    finally:
        _ann._going_down = _down
    check("……and with the fixes in place it is quiet again", replay.errwatch_pushes(RELAY), [])
    check("main() stops a deploy whose snapshot fix is gone", (
        setattr(_ann, "_going_down", lambda: False),
        replay.main([str(FIX / "relay-1006-false-alarms.log")]),
        setattr(_ann, "_going_down", _down))[1], 1)
    check("the replay leaves no handler on the ark logger",
          [type(h).__name__ for h in __import__("logging").getLogger(__import__("ark_relay.features.alarm.errwatch", fromlist=["ARK"]).ARK).handlers], [])

    print("[a genuine ERROR still pushes; INFO / diag / traceback lines do not]")
    check("a real ERROR line pushes",
          replay.errwatch_pushes("10-06 06:20:17 ERROR   ark.engine  采集超时：残象聚落"),
          [{"where": "ark.engine", "line": "采集超时：残象聚落", "lineno": 1}])
    check("INFO and bare diag / traceback lines are skipped",
          replay.errwatch_pushes('10-06 06:20:17 INFO    ark.machinecheck  ok\ndiag: x\n  File "x"\nTraceback (most recent call last):\n'),
          [])

    print("[the deploy script's entry point over both fixtures]")
    check("main exits 0, deploy may proceed",
          replay.main([str(FIX / "okww-1006-run.log"), str(FIX / "relay-1006-false-alarms.log")]), 0)

    print("[the deploy script passes file paths: the OK-WW fixture must be replayed as an OK-WW run log]")
    check("the fixture path is read as an OK-WW run log", replay._is_okww(str(FIX / "okww-1006-run.log")), True)
    check("an evidence-package log name is too", replay._is_okww("OK-WW-05-19-08.log"), True)
    check("the relay.log fixture is not", replay._is_okww(str(FIX / "relay-1006-false-alarms.log")), False)
    outcome.okww_checks = pre_fix_checks
    try:
        check("main() over the fixtures stops the pre-fix code (the gate really blocks)",
              replay.main([str(FIX / "okww-1006-run.log")]), 1)
    finally:
        outcome.okww_checks = orig

    print("[the deploy script's `python3 -m` target can be run by runpy]")
    # 2026-10-11: deploy-relay.sh still ran `-m ark_relay.replay`, an old name served by
    # _aliases; runpy needs the loader's get_code, which the alias loader lacks, so the
    # gate died with a traceback and the deploy was refused.
    import re as _re
    _deploy = (Path(__file__).resolve().parents[2] / "scripts" / "mac" / "deploy-relay.sh").read_text(encoding="utf-8")
    for _mod in _re.findall(r"python3 -m (ark_relay[\w.]*)", _deploy):
        _spec = importlib.util.find_spec(_mod)
        check(f"{_mod} has a loader runpy can use", bool(_spec and hasattr(_spec.loader, "get_code")), True)


def _part_tests_for_selector():
    """The deploy's "only the relevant tests" selector never skips a test that could
catch the change (the user's condition, 2026-09-18: allowed only if not a
single bug slips through).

* a test that executes a changed module is picked;
* a test that maps to no module (source scan / subprocess) is always picked;
* a test file that itself changed is always picked;
* a change outside the relay modules, a missing or stale map, or a test the map
  does not know -> empty pick, meaning the deploy runs everything.

    Formerly test_tests_for_selector.py.
    """
    import json
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "mac" / "lib"))
    import changed_covered as cc


    orig = (cc._sh, cc.changed_modules, cc.TEST_MAP, cc.REPO)
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "relay" / "tests").mkdir(parents=True)
        for n in ("test_a.py", "test_b.py", "test_scan.py", "test_new.py"):
            (t / "relay" / "tests" / n).write_text("", encoding="utf-8")
        cc.REPO = t
        cc.TEST_MAP = t / "relay" / "tests" / "test-map.json"
        cc.TEST_MAP.write_text(json.dumps({"test_a.py": ["phone", "config"], "test_b.py": ["engine"],
                                           "test_scan.py": [], "test_new.py": ["phone"]}), encoding="utf-8")
        state = {"diff": ["relay/ark_relay/features/phone/phone.py"], "status": []}
        cc._sh = lambda *a: "\n".join(state["status"] if a[1] == "status" else state["diff"])
        cc.changed_modules = lambda base: ({"phone"}, set())

        print("[改了 phone.py：跑碰到 phone 的测试 + 不走 import 的测试]")
        picked, why = cc.tests_for("HEAD")
        check("选中 a、new（碰 phone）和 scan（不映射）", picked, ["test_a.py", "test_new.py", "test_scan.py"])
        check("b 不跑（只碰 engine）", "test_b.py" not in picked)

        print("\n[测试文件自己改了：一定跑]")
        state["status"] = [" M relay/tests/test_b.py"]
        picked, _ = cc.tests_for("HEAD")
        check("b 也进来了", "test_b.py" in picked)
        state["status"] = []

        print("\n[改动不在中继模块范围：全量]")
        state["diff"] = ["relay/ark_relay/features/phone/phone.py", "web/app.js"]
        picked, why = cc.tests_for("HEAD")
        check("空选择 = 全量", picked, [])
        check("说了原因", "全量" in why)
        state["diff"] = ["relay/ark_relay/features/phone/phone.py"]

        print("\n[信箱文件和部署记账跟着改：不算代码改动，照常只跑相关的]")
        state["diff"] = ["relay/ark_relay/features/phone/phone.py", "queue/config.json", "relay/state/last-deployed-notes.sha1"]
        picked, why = cc.tests_for("HEAD")
        check("仍只选 a、new、scan", picked, ["test_a.py", "test_new.py", "test_scan.py"])
        state["diff"] = ["relay/ark_relay/features/phone/phone.py"]

        print("\n[静音登记表 USER-SWITCHES.txt 跟着改：不全量，加跑读它的测试]")
        (t / "relay" / "tests" / "test_reads_switches.py").write_text('REG = "relay/USER-SWITCHES.txt"\n', encoding="utf-8")
        table = json.loads(cc.TEST_MAP.read_text(encoding="utf-8"))
        cc.TEST_MAP.write_text(json.dumps({**table, "test_reads_switches.py": ["engine"]}), encoding="utf-8")
        state["diff"] = ["relay/ark_relay/features/phone/phone.py", "relay/USER-SWITCHES.txt"]
        picked, why = cc.tests_for("HEAD")
        check("选 a、new、scan，加上读登记表的那个", picked, ["test_a.py", "test_new.py", "test_reads_switches.py", "test_scan.py"])
        check("没退回全量", "全量" not in why)
        (t / "relay" / "tests" / "test_reads_switches.py").unlink()
        cc.TEST_MAP.write_text(json.dumps(table), encoding="utf-8")
        state["diff"] = ["relay/ark_relay/features/phone/phone.py"]

        print("\n[映射表不认识某个测试：全量]")
        (t / "relay" / "tests" / "test_unknown.py").write_text("", encoding="utf-8")
        picked, why = cc.tests_for("HEAD")
        check("空选择", picked, [])
        check("点名不认识的测试", "test_unknown" in why)
        (t / "relay" / "tests" / "test_unknown.py").unlink()

        print("\n[没有映射表：全量]")
        cc.TEST_MAP.unlink()
        picked, why = cc.tests_for("HEAD")
        check("空选择", picked, [])

    cc._sh, cc.changed_modules, cc.TEST_MAP, cc.REPO = orig
    print()
    if fails:
        print("FAILED:", fails); sys.exit(1)
    print("all checks passed")


def _part_tools_import_installed_relay():
    """Tools that import ark_relay on the gaming machine import the installed relay's code.

Since the switch-over (packaging/switch.py install) the relay runs
C:\\Program Files\\ArkRelay\\versions\\<current.txt>\\ (relay/pkg_layout.py), and
C:\\ProgramData\\ark-relay holds only its data. The ark_relay folder still lying there is
the old relay's, frozen at the switch-over. Until 2026-10-11 healthcheck.py,
okww_effective.py, config-check.py, okww-landed.py, maaend_only_task.py,
waittime_roundtrip.py, boot_check_remote.py, the desktop switch skip-shutdown.bat and the
commands in docs/OPERATIONS.md all put that folder on sys.path: every check judged the
machine by the old code, and healthcheck.py's ensure_patches wrote the old OK-WW patches
over newer fixes. They now take the folder from scripts/mac/lib/relay_code.py (the .bat,
which sits alone on his desktop, reads current.txt itself).

Checked here:
  1. nothing under scripts/ or docs/ puts C:\\ProgramData\\ark-relay itself (literally, or
     through a name or %VAR% bound to it in the same file) on sys.path, or reads a file
     under C:\\ProgramData\\ark-relay\\ark_relay - except the listed files that are about
     the old relay on purpose;
  2. each of those tools imports relay_code on a line winrun.sh's module shipping sees;
  3. relay_code.code_root() picks versions\\<current.txt>, and the old folder (saying so)
     only when there is no installed relay;
  4. skip-shutdown.bat reads current.txt, has CRLF line endings, and does not start a
     for /f command with a quote (cmd /c then drops the first and last quote and the
     Python path no longer parses: its menu read 「读不出来」 every time, seen on the machine
     2026-10-11; with LF line endings cmd.exe ran fragments of its lines as commands).

    Formerly test_tools_import_installed_relay.py.
    """
    import contextlib
    import io
    import re
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
    import relay_code


    # Files that address the old relay's folder on purpose.
    ALLOW = {
        "scripts/mac/lib/relay_code.py": "the fallback for a machine without the installed relay",
        "scripts/windows/skip-shutdown.bat": "the same fallback, inline (checked in section 4)",
        "scripts/mac/deploy-relay.sh": "its old-layout branch deploys the old relay into that folder",
        "scripts/windows/smoke.py": "deploy smoke; deploy-pkg.sh passes --pkg-version, the default is the old layout",
    }

    # The old folder itself: backslashes as written in .py / .md / .bat / .sh (one, or doubled
    # inside a string literal), optionally a trailing one, then the end of the literal.
    OLD = r"ProgramData(?:\\{1,2}|/)ark-relay(?:\\{1,2}|/)?"
    OLD_END = OLD + r"""\\?["')%]"""
    SYSPATH = re.compile(r"sys\.path\.(?:insert|append)\(([^)\n]*)\)")
    BIND_PY = re.compile(r"""(?:^|[;\s])([A-Za-z_]\w*)\s*=\s*[^;\n]*?""" + OLD_END, re.M)
    BIND_BAT = re.compile(r"""^\s*set\s+"?([A-Za-z_]\w*)=[^\n"]*""" + OLD + r"""\s*"?\s*$""", re.M | re.I)
    OLD_CODE_FILE = re.compile(OLD + r"(?:\\{1,2}|/)ark_relay\b")


    def offences(text: str) -> list:
        out = []
        names = set(BIND_PY.findall(text)) | set(BIND_BAT.findall(text))
        for m in SYSPATH.finditer(text):
            arg = m.group(1) + ")"
            if re.search(OLD_END, arg) or re.search(OLD + r"\\?\\?\"", arg):
                out.append(m.group(0)[:120])
                continue
            for n in names:
                if re.search(rf"\b{n}\b|%{n}%", m.group(1)):
                    out.append(f"{m.group(0)[:100]} ({n} = the old folder)")
        out += [f"reads old code: {m.group(0)}" for m in OLD_CODE_FILE.finditer(text)]
        return out


    def scan(paths) -> dict:
        found = {}
        for p in paths:
            rel = p.relative_to(ROOT).as_posix()
            if rel in ALLOW:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "ark-relay" not in text:
                continue
            hits = offences(text)
            if hits:
                found[rel] = hits
        return found


    print("[1. nothing puts the old folder on sys.path]")
    files = [p for d in ("scripts", "docs") for p in (ROOT / d).rglob("*")
             if p.is_file() and p.suffix in (".py", ".sh", ".md", ".bat", ".ps1", ".txt")]
    found = scan(files)
    require(f"{len(files)} files under scripts/ and docs/", not found,
          "; ".join(f"{k}: {v[0]}" for k, v in sorted(found.items())))

    # The scan has to recognise each shape the tools used before 2026-10-11.
    SHAPES = {
        "literal": 'import sys\nsys.path.insert(0, r"C:\\ProgramData\\ark-relay")\n',
        "named": 'R = Path(r"C:\\ProgramData\\ark-relay")\nsys.path.insert(0, str(R))\n',
        "one line": 'root = pathlib.Path(r"C:\\ProgramData\\ark-relay"); sys.path.insert(0, str(root))\n',
        "bat": "set RELAY=C:\\ProgramData\\ark-relay\n\"%PY%\" -c \"import sys; sys.path.insert(0, r'%RELAY%')\"\n",
        "doc": 'winps.sh \'& py -c "import sys; sys.path.insert(0, r\\"C:\\ProgramData\\ark-relay\\"); x"\'\n',
        "old code file": 'ref = Path(r"C:\\ProgramData\\ark-relay\\ark_relay\\okww_files")\n',
    }
    for name, text in SHAPES.items():
        require(f"scan catches the {name} shape", bool(offences(text)), text)
    DATA_ONLY = ('_load_dotenv(Path(r"C:\\ProgramData\\ark-relay\\.env"))\n'
                 'st = Path(r"C:\\ProgramData\\ark-relay\\state")\n'
                 'set DATA=C:\\ProgramData\\ark-relay\nPath(r\'%DATA%\\state\')\n')
    require("scan leaves data paths alone", not offences(DATA_ONLY), str(offences(DATA_ONLY)))

    print("\n[2. the tools import relay_code where winrun ships it]")
    winrun = (ROOT / "scripts" / "mac" / "winrun.sh").read_text(encoding="utf-8")
    m = re.search(r"grep -oE '(\^\(from\|import\) \+\[a-z_\]\[a-z0-9_\]\*)'", winrun)
    require("winrun.sh still ships same-folder modules by their import line", bool(m))
    SHIP = re.compile(m.group(1) if m else r"^(from|import) +[a-z_][a-z0-9_]*", re.M)
    TOOLS = {
        "scripts/mac/lib/healthcheck.py": "use_relay_code()",
        "scripts/mac/lib/okww_effective.py": "use_relay_code()",
        "scripts/mac/lib/maaend_only_task.py": "use_relay_code()",
        "scripts/mac/lib/waittime_roundtrip.py": "use_relay_code()",
        "scripts/mac/lib/boot_check_remote.py": "code_root()",
        "scripts/windows/okww-landed.py": "use_relay_code()",
        "scripts/mac/config-check.py": "use_relay_code()",   # inside PROBE, shipped as its own file
    }
    for rel, call in TOOLS.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        shipped = any(s.split()[-1] == "relay_code" for s in SHIP.findall(text)) or \
            any(line.split()[1] == "relay_code" for line in text.splitlines()
                if SHIP.match(line) and len(line.split()) > 1)
        require(f"{rel}: imports relay_code at column 0 and calls {call}", shipped and call in text)

    print("\n[3. relay_code.code_root]")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        app, legacy = t / "ArkRelay", t / "ark-relay"
        (app / "versions" / "20261011073720" / "ark_relay").mkdir(parents=True)
        (app / "versions" / "20261011073720" / "ark_relay" / "__init__.py").write_text("")
        (app / "current.txt").write_text("20261011073720\n", encoding="ascii")
        got = relay_code.code_root(app, legacy)
        require("installed: versions\\<current.txt>", got == (app / "versions" / "20261011073720", True), str(got))
        (app / "current.txt").write_text("20261011999999\n", encoding="ascii")
        require("current.txt naming a folder without ark_relay: the old folder",
              relay_code.code_root(app, legacy) == (legacy, False))
        err = io.StringIO()
        saved = list(sys.path)
        with contextlib.redirect_stderr(err):
            got = relay_code.use_relay_code(t / "nothing", legacy)
        first = sys.path[0]
        sys.path[:] = saved
        require("no installed relay: the old folder, first on sys.path", got == legacy and first == str(legacy))
        require("... and one line on stderr saying so", "no installed relay" in err.getvalue()
              and "{" not in err.getvalue(), err.getvalue())

    print("\n[4. skip-shutdown.bat]")
    raw = (ROOT / "scripts" / "windows" / "skip-shutdown.bat").read_bytes()
    lines = raw.split(b"\n")[:-1] if raw.endswith(b"\n") else raw.split(b"\n")
    lf_only = sum(not l.endswith(b"\r") for l in lines)
    require("CRLF on every line", lf_only == 0, f"{lf_only} LF-only lines")
    bat = raw.decode("utf-8")
    require("reads current.txt for the code folder",
          '"%APP%\\current.txt"' in bat and "%APP%\\versions\\%%v" in bat)
    require("puts the code folder (not the data folder) on sys.path",
          bat.count("sys.path.insert(0, r'%CODE%')") == 3 and "sys.path.insert(0, r'%DATA%')" not in bat)
    quoted = re.findall(r"""for /f [^\n]*?in \('"[^\n]*""", bat)
    require("no for /f command starts with a quote", not quoted, quoted[0][:80] if quoted else "")
    require("says when it falls back to the old code", "if defined OLDCODE echo" in bat)
    require("runs the installed relay's own Python, never AUTO-MAS's",
            'set "PY=%APP%\\runtime\\python\\python.exe"' in bat and "automas" not in bat.lower())

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_unmerged_fixes():
    """deploy-relay.sh step 0.6: a finished relay fix may not sit on a branch, unreviewed.

On 10-11 23 local branches held relay changes that never reached main (one was the
10-10 Endfield-hang fix a4be51cb). Checked here on a temporary git repo whose
origin/main is the baseline commit:
  - a branch commit touching relay/ that is not in main and not listed blocks (exit 1),
    and the output names its branch, hash and subject;
  - the same commit listed in the review file passes;
  - a docs-only commit on a branch is ignored, and so is one that touches only files
    that never reach the machine: relay/tests/ and relay/make-manifest.py (make-manifest.py
    ships relay/ark_relay/**/*.py|*.txt, relay/*.py and RELEASE-NOTES.md); a top-level
    relay/*.py commit still blocks (2026-10-13: the daysim test commits were counted);
  - a commit whose patch is already in main (cherry-picked: `git cherry` says "-") is
    ignored, and so is a commit on HEAD (the deploy pushes HEAD to main);
  - a malformed review line (unknown verdict) fails closed;
  - all of it under diff.noprefix / diff.mnemonicPrefix / diff.renames=false;
  - deploy-relay.sh runs the gate before the pre-deploy replay.

    Formerly test_unmerged_fixes.py.
    """
    import contextlib
    import importlib.util
    import io
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]


    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


    uf = load("unmerged_fixes", ROOT / "scripts/mac/lib/unmerged_fixes.py")


    G = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


    def git(*a, cwd):
        return subprocess.run([*G, *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


    def commit(base, path, text, msg):
        p = base / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        git("add", "-A", cwd=base)
        git("commit", "-qm", msg, cwd=base)
        return git("rev-parse", "HEAD", cwd=base).strip()


    def run(base, reviewed):
        (base / "docs").mkdir(exist_ok=True)
        (base / "docs/UNMERGED-REVIEWED.txt").write_text(reviewed, encoding="utf-8")
        out = io.StringIO()
        argv = sys.argv
        sys.argv = ["unmerged_fixes.py", "--root", str(base)]
        try:
            with contextlib.redirect_stdout(out):
                rc = uf.main()
        finally:
            sys.argv = argv
        return rc, out.getvalue()


    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        git("init", "-q", "-b", "main", cwd=base)
        for k, v in (("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"),
                     ("diff.renames", "false")):
            git("config", k, v, cwd=base)
        commit(base, "relay/ark_relay/x.py", "A = 1\n", "base")
        git("update-ref", "refs/remotes/origin/main", "main", cwd=base)

        git("checkout", "-qb", "fix-branch", cwd=base)
        fix = commit(base, "relay/ark_relay/x.py", "A = 2\n", "relay: the fix nobody merged")
        git("checkout", "-qb", "docs-branch", "main", cwd=base)
        commit(base, "docs/NOTE.md", "note\n", "docs only")
        git("checkout", "-qb", "tests-branch", "main", cwd=base)
        commit(base, "relay/tests/daysim/test_day.py", "T = 1\n", "tests only")
        commit(base, "relay/make-manifest.py", "M = 1\n", "manifest tool only")
        git("checkout", "-qb", "top-branch", "main", cwd=base)
        top = commit(base, "relay/boot_x.py", "D = 1\n", "relay: a top-level module fix")
        git("checkout", "-qb", "picked-branch", "main", cwd=base)
        picked = commit(base, "scripts/windows/w.py", "B = 1\n", "windows: picked into main")
        git("checkout", "-q", "main", cwd=base)
        # main moves first, so the pick gets a new parent and a new hash (same second,
        # same parent would reproduce the very same commit).
        commit(base, "relay/ark_relay/y.py", "C = 1\n", "main moves on")
        git("cherry-pick", picked, cwd=base)
        git("update-ref", "refs/remotes/origin/main", "main", cwd=base)
        check("git cherry marks the picked commit '-'",
              git("cherry", "origin/main", "picked-branch", cwd=base).split()[0], "-")

        rc, out = run(base, "# nothing reviewed yet\n")
        check("an unlisted relay commit blocks", rc, 1)
        check("the output names branch, hash and subject",
              f"fix-branch  {fix[:8]}  relay: the fix nobody merged" in out, True)
        check("the docs-only commit is not listed", "docs only" in out, False)
        check("commits touching only relay/tests/ or make-manifest.py are not listed",
              ("tests only" in out, "manifest tool only" in out), (False, False))
        check("a top-level relay/*.py commit is listed", f"top-branch  {top[:8]}" in out, True)
        check("the cherry-equivalent commit is not listed", picked[:8] in out, False)
        check("exactly two commits block", "2 relay commit(s)" in out, True)

        rc, out = run(base, f"# reviewed\n{fix[:8]} declined DECISIONS D-1011 test\n"
                            f"{top[:8]} declined DECISIONS D-1011 test\n")
        check("the same commit, listed, passes", rc, 0)

        rc, out = run(base, f"{fix[:8]} maybe not sure\n")
        check("an unknown verdict fails closed", (rc, "unreadable lines" in out), (1, True))
        rc, out = run(base, f"{fix[:8]} a\n")
        check("a verdict without a reason fails closed", rc, 1)

        git("checkout", "-q", "fix-branch", cwd=base)
        rc, out = run(base, f"{top[:8]} declined DECISIONS D-1011 test\n")
        check("a commit on HEAD (pushed to main by this deploy) does not block", rc, 0)

    deploy = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
    gate = deploy.find("lib/unmerged_fixes.py")
    check("deploy-relay.sh runs the gate before the pre-deploy replay",
          0 < gate < deploy.find("ark_relay.features.selfcheck.replay"), True)
    check("a failed gate exits the deploy", "exit 1" in deploy[gate:gate + 600], True)

    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    sys.exit(run_parts([_part_build_notes_at_deploy_tip, _part_ci_green, _part_dead_helpers_gone, _part_diag_pull_silent, _part_gamesim_fetch_retry, _part_lint_pick_tests, _part_num_source, _part_release_notes, _part_replay_gate, _part_tests_for_selector, _part_tools_import_installed_relay, _part_unmerged_fixes]))
