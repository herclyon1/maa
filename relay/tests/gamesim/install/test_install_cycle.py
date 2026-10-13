#!/usr/bin/env python3
"""T6: the overlay's install / update / re-apply / drift / uninstall cycle on real OK-WW trees.

The cycle replays what the game PC went through 2026-10-03 .. 10-06, in order, with the
relay's own installer (okww_overlay.install, drift, drift_line, report_line, last_report)
and OK-WW's own code. Every expected value cites the machine record it comes from.

  10-03  OK-WW v3.7.2 (relay.log 10-03 08:46:50 "OK-WW 已更新：v3.6.9-beta.1 → v3.7.2") with
         the overlay the relay installed 10-01 17:44:59 (relay.log: 3059111a's file, the
         last overlay commit before that deploy). Install, install again, drift, OK-WW start.
  10-04  OK-WW updates itself v3.7.2 -> v3.7.3 (relay.log 10-04 08:47:36). The overlay stays
         in ok_tasks/; before the next run nothing needs re-applying; the relay's pre-run
         drift check names find_nest with the hashes the machine reported; OK-WW's start
         skips it and the relay says exactly what relay.log said 10-04 21:20:19.
  10-05  The fix f6b5f432 is deployed (relay.log 10-05 21:20:27 install line); OK-WW's start
         applies everything.
  10-06  This checkout's overlay installed, OK-WW updates v3.7.3 -> v3.7.4 (relay.log 10-06
         06:11:04); drift check and OK-WW start clean.
  end    Uninstall: the one file install() wrote is removed; every upstream file is as the
         tag has it, and OK-WW starts without our code.

The update is the effect the machine recorded, applied with git: on the PC only the files
the new tag changed were rewritten (U0's read of the PC, okww-working-source-hashes.tsv:
mtime 2026-10-04T08:47:33 and 2026-10-06T06:11:03, the sets UPDATE_1004 / UPDATE_1006
below), and ok_tasks/ was left alone (relay/handover/legacy-items.json, the
ark_overrides.py entry: "on 2026-10-06 the v3.7.3 -> v3.7.4 update's first start ...
found ok_tasks\\ark_overrides.py"). A `git checkout` of the next tag's commit does exactly
that to a tree checked out at the previous one, and the test asserts the footprint matches
the PC's. pyappify itself (a Rust binary started by ok-ww.exe) does not run here.

Two modes:
  full    (Windows; --okww-python): trees are git checkouts of the pinned commits, checked
          byte-equal to relay/tests/gamesim/upstream/okww-<tag>/, and each "OK-WW start"
          runs okww_start_probe.py through OK-WW's own run_test.py with OK-WW's Python, so
          ok-script's task manager executes the installed file. Run by the Windows job
          through gamesim/okww/test_install_lane.py (the `installed` lane).
  static  (any OS; the default without --okww-python): trees are the pinned upstream
          copies written out (fetch_upstream.materialize) and the OK-WW starts are left
          out; install, update, drift and uninstall still run for real.

Red before green: --relay-rev REV runs the cycle with the relay's code as it was at REV
(git archive of relay/), e.g. e8e90be2~1 fails at "drift line again at the next boot".

    test_install_cycle.py [--static] [--relay-rev REV]
    test_install_cycle.py --okww-python PY --root DIR [--relay-rev REV]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE.parent / "tools"))
import fetch_upstream as fu  # noqa: E402

OVERLAY_NAME = "okww_files/ark_overrides.tasks.py"
PROBE = HERE / "okww_start_probe.py"
PROBE_IN_TREE = "tests/ark_install_probe.py"
# The same start in test_overlay_loads.py took 1.0 s and test_harness_self.py's 4.5 s on
# windows-latest (gamesim-windows run 38389995838, installed lane); 100 s is a hang guard,
# and five of them fit the 570 s test_install_lane.py gives the whole cycle.
START_TIMEOUT_S = 100

# ── what the machine recorded (the expected values) ─────────────────────────────
# relay.log on the game PC (scratchpad machine-relay/relay.log): 10-01 17:44:59 (line
# 24679) and 10-05 21:20:27 (line 27723), each right after a deploy that changed the overlay.
INSTALL_LINE = "中继给 OK-WW 的改动文件已装到 {dest}"
# relay.log 10-04 21:20:19 (line 27223): the report of OK-WW v3.7.3's first starts with the
# 10-01 overlay. Same text as ci_prepare.MACHINE_2026_10_04 (the P1 red lane).
MACHINE_2026_10_04 = ("OK-WW 有改动没贴上（上游源码和登记的不一致）：NightmareNestTask.find_nest"
                      "（上游正文变了（现在 12d040afa102，我们照着 3b0271924cac 抄的））")
DRIFT_1004 = [("NightmareNestTask.find_nest", "3b0271924cac", "12d040afa102", False)]
# U0's read of the PC (scratchpad gamesim/u0/okww-working-source-hashes.tsv, 2026-10-13):
# the .py files under working/ (root and src/) whose mtime is each update's minute. Files
# rewritten again later carry the later mtime (FarmEchoTask.py changed in both updates).
UPDATE_1004 = {"src/task/BaseCombatTask.py", "src/task/DomainTask.py", "src/task/EnhanceEchoTask.py",
               "src/task/NightmareNestTask.py", "src/task/TacetTask.py"}
UPDATE_1006 = {"config.py", "src/char/Rover.py", "src/task/FarmEchoTask.py"}

PROBLEMS: list[str] = []


def check(label: str, got, want, evidence: str) -> bool:
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f"  (want {want!r})")
          + f"\n      evidence: {evidence}", flush=True)
    if not ok:
        PROBLEMS.append(label)
    return ok


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args, cwd=None) -> str:
    return subprocess.run(["git", *[str(a) for a in args]], cwd=cwd, check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


# ── the relay and the overlay, at a revision ────────────────────────────────────
def load_relay(rev: "str | None", scratch: Path):
    """okww_overlay as the relay had it at `rev` (None = this checkout)."""
    relay = REPO / "relay"
    if rev is not None:
        data = subprocess.run(["git", "-C", str(REPO), "archive", rev, "relay"],
                              check=True, capture_output=True).stdout
        out = scratch / f"relay@{rev.replace('~', '_')}"
        tarfile.open(fileobj=io.BytesIO(data)).extractall(out, filter="data")
        relay = out / "relay"
    sys.path.insert(0, str(relay))
    # The module moved with 2c3290c8 (ark_relay/okww_overlay.py -> features/okww_patch/).
    name = ("ark_relay.features.okww_patch.okww_overlay"
            if (relay / "ark_relay/features/okww_patch/okww_overlay.py").is_file()
            else "ark_relay.okww_overlay")
    return importlib.import_module(name), f"{rev or 'this checkout'} ({name})"


def overlay_at(rev: "str | None", scratch: Path) -> Path:
    """The overlay file at `rev` (None = this checkout's), looked up in the revision's own tree."""
    if rev is None:
        return REPO / "relay/ark_relay/features/okww_patch" / OVERLAY_NAME
    names = git("-C", REPO, "ls-tree", "-r", "--name-only", rev, "--", "relay").splitlines()
    hits = [n for n in names if n.endswith(OVERLAY_NAME)]
    if len(hits) != 1:
        raise SystemExit(f"{rev}: expected one {OVERLAY_NAME} in relay/, found {hits}")
    out = scratch / f"ark_overrides@{rev.replace('~', '_')}.py"
    out.write_bytes(subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{hits[0]}"],
                                   check=True, capture_output=True).stdout)
    return out


# ── OK-WW trees ─────────────────────────────────────────────────────────────────
class Tree:
    """<root>/data/apps/ok-ww/working, the layout okww_overlay.target() expects."""

    def __init__(self, root: Path, full: bool):
        self.root, self.full = root, full
        self.work = root.joinpath("data", "apps", "ok-ww", "working")
        self.tag = ""

    def _pin(self, tag: str) -> dict:
        return fu.read_manifest(fu.copy_dir("okww", tag))

    def _check_pinned(self, tag: str) -> None:
        pin = self._pin(tag)
        bad = [p for p, want in pin["files"].items()
               if not (self.work / p).is_file() or sha256((self.work / p).read_bytes()) != want]
        if bad:
            raise SystemExit(f"OK-WW {tag} tree differs from upstream/okww-{tag}: {bad}")

    def _fetch(self, tag: str) -> None:
        pin = self._pin(tag)
        git("-C", self.work, "-c", "core.autocrlf=false", "fetch", "-q", "--depth", "1", pin["repo"], pin["commit"])
        git("-C", self.work, "-c", "core.autocrlf=false", "checkout", "-q", "FETCH_HEAD")
        head = git("-C", self.work, "rev-parse", "HEAD").strip()
        if head != pin["commit"]:
            raise SystemExit(f"fetched {head}, upstream/okww-{tag}/SOURCE.txt pins {pin['commit']}")

    def lay_out(self, tag: str) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.work.mkdir(parents=True)
        if self.full:
            git("init", "-q", self.work)
            self._fetch(tag)
        else:
            fu.materialize(fu.copy_dir("okww", tag), self.work)
        self._check_pinned(tag)
        self.tag = tag
        print(f"  OK-WW {tag} laid out at {self.work} ({'git checkout' if self.full else 'pinned copy'})")

    def files(self) -> dict:
        """{relative path: (sha256, mtime_ns)} of every file outside .git."""
        out = {}
        for p in sorted(self.work.rglob("*")):
            rel = p.relative_to(self.work).as_posix()
            if p.is_file() and not rel.startswith(".git/"):
                out[rel] = (sha256(p.read_bytes()), p.stat().st_mtime_ns)
        return out

    def update(self, tag: str) -> "list[str]":
        """OK-WW updating itself to `tag`; the files it rewrote."""
        before = self.files()
        time.sleep(0.05)         # a rewrite must get a later mtime than the layout's
        if self.full:
            self._fetch(tag)
        else:
            fu.materialize(fu.copy_dir("okww", tag), self.work)
        self._check_pinned(tag)
        self.tag = tag
        after = self.files()
        return sorted(p for p in after if p not in before or after[p] != before[p])

    def pristine(self) -> "list[str]":
        """Upstream files that are not as the tag has them ([] when all are)."""
        bad = [p for p, want in self._pin(self.tag)["files"].items()
               if sha256((self.work / p).read_bytes()) != want]
        if self.full:
            # Tracked files modified, and anything left under ok_tasks/.
            bad += [ln for ln in git("-C", self.work, "status", "--porcelain", "--untracked-files=all").splitlines()
                    if not ln.startswith("??") or ln[3:].startswith("ok_tasks/")]
        elif (self.work / "ok_tasks").exists():
            bad.append("ok_tasks/")
        return bad


def py_set(paths) -> set:
    """The .py files the PC's record covers: the root of working/ and src/."""
    return {p for p in paths if p.endswith(".py") and ("/" not in p or p.startswith("src/"))}


# ── one OK-WW start ─────────────────────────────────────────────────────────────
def okww_start(ov, tree: Tree, python: str, out_dir: Path) -> "tuple[dict, dict, bool]":
    """(probe answer, the overlay's report as the relay reads it, report written by this start)."""
    if ov.REPORT.exists():
        ov.REPORT.unlink()           # a report from before must not pass for this start's
    shutil.copyfile(PROBE, tree.work / PROBE_IN_TREE)
    answer = out_dir / f"probe-{tree.tag}-{time.time_ns()}.json"
    started = time.time()
    p = subprocess.run([python, "-u", "run_test.py", PROBE_IN_TREE], cwd=tree.work,
                       env={**os.environ, "ARK_INSTALL_PROBE_OUT": str(answer)},
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=START_TIMEOUT_S)
    (tree.work / PROBE_IN_TREE).unlink()
    text = p.stdout + p.stderr
    print(f"  OK-WW start on {tree.tag}: exit {p.returncode}, {round(time.time() - started, 1)} s")
    if p.returncode != 0 or not answer.is_file():
        print(text[-4000:])
        raise SystemExit(f"OK-WW did not start on {tree.tag} (exit {p.returncode})")
    probe = json.loads(answer.read_text(encoding="utf-8"))
    fresh = ov.REPORT.is_file() and ov.REPORT.stat().st_mtime >= started - 1
    report = ov.last_report()
    print(f"  probe: {json.dumps(probe, ensure_ascii=False)}\n  report: {json.dumps(report, ensure_ascii=False)}")
    return probe, report, fresh


def install_checks(ov, tree: Tree, overlay: Path, evidence: str) -> None:
    ov._SOURCE = overlay           # install() copies source_text(); point it at this overlay
    dest = ov.target(tree.root)
    replaces = dest.is_file()
    before = tree.files()
    line = ov.install(tree.root)
    after = tree.files()
    check("install says it put the overlay in place", line, INSTALL_LINE.format(dest=dest), evidence)
    check("the installed file is the overlay's bytes", sha256(dest.read_bytes()), sha256(overlay.read_bytes()),
          "U0: the PC's ok_tasks/ark_overrides.py hashes equal to the relay's overlay file (7f07188afede, 2026-10-13)")
    changed = sorted(p for p in after if p in before and after[p] != before[p])
    added = sorted(p for p in after if p not in before)
    removed = sorted(p for p in before if p not in after)
    mine = ["ok_tasks/ark_overrides.py"]
    check("install writes that one file and touches nothing of OK-WW's", (added, changed, removed),
          ([], mine, []) if replaces else (mine, [], []),
          "U0: every ok/ and src/ file on the PC hashes equal to the OK-WW tag and the ok-script wheel")


def run_cycle(ov, tree: Tree, python: "str | None", scratch: Path) -> None:
    state = scratch / "state"
    state.mkdir()
    o_1001 = overlay_at("3059111a", scratch)
    o_fix = overlay_at("f6b5f432", scratch)
    o_now = overlay_at(None, scratch)
    dest = ov.target(tree.root)

    print("\n== 10-03: OK-WW v3.7.2, the overlay installed 10-01 17:44:59 (3059111a)")
    tree.lay_out("v3.7.2")
    install_checks(ov, tree, o_1001, "relay.log 10-01 17:44:59 (line 24679)")
    mtime = dest.stat().st_mtime_ns
    check("installing the same overlay again writes nothing", ov.install(tree.root), "",
          "relay.log: the boots 10-02 08:45:19 .. 10-04 21:20:19 log no install line")
    check("... and leaves the file's mtime alone", dest.stat().st_mtime_ns, mtime, "same boots")
    check("the pre-run drift check finds nothing on v3.7.2", ov.drift(tree.root), [],
          "relay.log: no skipped-override line at the boots 10-03 12:54:28 and 21:20:21, after OK-WW "
          "ran on v3.7.2 at 09:18 and 09:20 (ledger-2026-10-03 lines 6-7)")
    if python:
        probe, report, fresh = okww_start(ov, tree, python, scratch)
        check("OK-WW's start executed the overlay and wrote its report", (probe["overlay_executed"], fresh), (True, True),
              "relay.log 10-04 21:20:19: the relay read a report written by OK-WW's start")
        check("nothing skipped, no error", (report.get("skipped"), report.get("error")), ([], ""), "same boots as above")
        check("the relay says nothing at boot", ov.report_line(), "", "same boots as above")

    print("\n== 10-04 08:47:36: OK-WW updates itself v3.7.2 -> v3.7.3")
    written = dest.read_bytes()
    mtime = dest.stat().st_mtime_ns
    rewritten = tree.update("v3.7.3")
    check("the update leaves ok_tasks/ark_overrides.py alone", ("ok_tasks/ark_overrides.py" in rewritten,
          dest.read_bytes() == written, dest.stat().st_mtime_ns == mtime), (False, True, True),
          "relay.log: no install line from 10-01 17:44:59 to 10-04 21:20:19, yet the 10-04 report is the "
          "10-01 overlay's; legacy-items.json (ark_overrides.py entry)")
    if python:
        py = py_set(rewritten)
        check("the update rewrote the files the PC's update rewrote", (UPDATE_1004 <= py, sorted(py - UPDATE_1004 - UPDATE_1006)),
              (True, []), "U0 okww-working-source-hashes.tsv, mtime 2026-10-04T08:47:33")
    check("before the next run the relay has nothing to re-apply", ov.install(tree.root), "",
          "relay.log: no install line on 10-04")
    check("the pre-run drift check names find_nest with the machine's hashes",
          [(d["what"], d["want"], d["got"], d["adapt"]) for d in ov.drift(tree.root)], DRIFT_1004,
          "relay.log 10-04 21:20:19 (line 27223)")
    first, again = ov.drift_line(tree.root, state), ov.drift_line(tree.root, state)
    check("the drift line names it at the first boot", "NightmareNestTask.find_nest" in first, True,
          "relay.log 10-04 21:20:19")
    check("the drift line names it again at the next boot", "NightmareNestTask.find_nest" in again, True,
          "the owner 2026-10-06: 「不论多少次什么错误都要发」 (e8e90be2); relay.log said the skip at all six boots "
          "10-04 21:20:19 .. 10-05 22:00:55")
    if python:
        probe, report, fresh = okww_start(ov, tree, python, scratch)
        check("OK-WW's start wrote the report", (probe["overlay_executed"], fresh), (True, True), "relay.log 10-04 21:20:19")
        check("the relay says what it said on the machine", ov.report_line(), MACHINE_2026_10_04,
              "relay.log 10-04 21:20:19 (line 27223)")
        check("what drift predicted before the run is what OK-WW's start skipped",
              sorted(s.get("what") for s in report.get("skipped") or []), [w for w, *_ in DRIFT_1004],
              "relay.log 10-04 21:20:19")

    print("\n== 10-05 21:20:27: the fix f6b5f432 is deployed")
    install_checks(ov, tree, o_fix, "relay.log 10-05 21:20:27 (line 27723)")
    check("the pre-run drift check finds nothing", ov.drift(tree.root), [],
          "relay.log: no skipped-override line from the boot 10-05 22:10:57 on")
    if python:
        probe, report, fresh = okww_start(ov, tree, python, scratch)
        check("OK-WW's start applied everything", (fresh, report.get("skipped"), report.get("adapted") or [],
              report.get("error")), (True, [], [], ""), "relay.log: no skipped-override line from 10-05 22:10:57 on")
        check("the relay says nothing at boot", ov.report_line(), "", "same boots")

    print("\n== this checkout's overlay; 10-06 06:11:04: OK-WW updates itself v3.7.3 -> v3.7.4")
    if sha256(o_now.read_bytes()) != sha256(dest.read_bytes()):
        install_checks(ov, tree, o_now, "relay.log 10-06 06:10:04 (line 28209), the boot before the update")
    ov._SOURCE = o_now
    written = dest.read_bytes()
    rewritten = tree.update("v3.7.4")
    check("the update leaves ok_tasks/ark_overrides.py alone",
          ("ok_tasks/ark_overrides.py" in rewritten, dest.read_bytes() == written), (False, True),
          "legacy-items.json (ark_overrides.py entry): the 10-06 update's first start found the file")
    if python:
        check("the update rewrote exactly the files the PC's update rewrote", sorted(py_set(rewritten)),
              sorted(UPDATE_1006), "U0 okww-working-source-hashes.tsv, mtime 2026-10-06T06:11:03")
    check("before the next run the relay has nothing to re-apply", ov.install(tree.root), "",
          "relay.log: no install line between 10-06 06:10:04 and the next deploy")
    check("the pre-run drift check finds nothing on v3.7.4", ov.drift(tree.root), [],
          "relay.log: no skipped-override line after 10-06 06:11:04")
    if python:
        probe, report, fresh = okww_start(ov, tree, python, scratch)
        applied = report.get("applied") or []
        check("OK-WW's start applied everything, each override once",
              (fresh, report.get("skipped"), report.get("adapted") or [], report.get("error"),
               len(applied) == len(set(applied)), applied == probe["applied_in_process"]),
              (True, [], [], "", True, True),
              "relay.log: no skipped-override line since 10-05 22:10:57; 09-01 b0bb8607 (two layers stacked)")
        check("the relay says nothing at boot", ov.report_line(), "", "same boots")

    print("\n== uninstall: the one file install() wrote is removed")
    dest.unlink()
    if dest.parent.is_dir() and not any(dest.parent.iterdir()):
        dest.parent.rmdir()          # install() made the folder; OK-WW does not ship one
    check("every upstream file is as the tag has it, nothing of ours is left", tree.pristine(), [],
          f"upstream/okww-{tree.tag}/SOURCE.txt; legacy-items.json: the uninstaller deletes ark_overrides.py")
    if python:
        probe, report, fresh = okww_start(ov, tree, python, scratch)
        check("OK-WW starts without our code and no report is written", (probe["overlay_executed"], fresh, report),
              (False, False, {}), "upstream OK-WW has no ok_tasks/ (git status above)")
        check("the relay says nothing", ov.report_line(), "", "no report on disk")
        check("still nothing of ours left after the start", [p for p in tree.pristine() if "ok_tasks" in p], [],
              "as above")


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--okww-python", help="OK-WW's interpreter: full mode with OK-WW starts (Windows)")
    ap.add_argument("--root", type=Path, help="folder for the OK-WW tree (full mode; emptied first)")
    ap.add_argument("--static", action="store_true", help="no OK-WW starts (the default without --okww-python)")
    ap.add_argument("--relay-rev", help="run the relay's code as it was at this revision (red-before-green)")
    a = ap.parse_args(argv)
    full = bool(a.okww_python) and not a.static
    if full and os.name != "nt":
        raise SystemExit("full mode is Windows only: ok-script imports pywin32 at module top (ok/util/window.py)")
    if full and not a.root:
        ap.error("full mode needs --root")
    with tempfile.TemporaryDirectory(prefix="ark-install-cycle-") as tmp:
        scratch = Path(tmp)
        ov, label = load_relay(a.relay_rev, scratch)
        root = a.root.resolve() if full else scratch / "okww"
        print(f"install cycle: relay {label}, {'full (OK-WW starts with ' + a.okww_python + ')' if full else 'static'}")
        try:
            run_cycle(ov, Tree(root, full), a.okww_python if full else None, scratch)
        finally:
            if full and ov.REPORT.exists():
                ov.REPORT.unlink()   # shared path: the lane's own tests read it after this one
    print("\n" + ("all checks passed" if not PROBLEMS else f"{len(PROBLEMS)} problem(s): " + "; ".join(PROBLEMS)))
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
