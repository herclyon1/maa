"""scripts/windows/retire_legacy.py retires the old relay and nothing of the new one, and
packaging/switch.py + legacy.py cope with an old relay that is gone.

2026-10-11 (user 17:23: could all of the old relay be taken off, replaced by the new one,
without harm): the old relay's code left on the machine made seven tools read the old
version without saying so. retire_legacy.py moves it into ark-relay-retired-1011; these
checks pin that it
  * never moves a kept path (the new relay's data, echo-farm files, Mac-side tool files),
    and stops the whole run when a planned move would touch one, or when something kept
    (a kept script, a scheduled task, a desktop shortcut) names a planned move;
  * does nothing at all when the new relay is not running;
  * changes nothing in a dry run;
  * saves the service, its event-log key and the task before deleting them;
and that once the old relay is gone, `switch.py revert` changes nothing (before, it handed
AUTO-MAS's jobs back and stopped the new relay, then found no old relay to start), a
failed upgrade switches the new relay on again, and the uninstall skips what is gone.
Run on a temporary folder with a fake machine; no Windows needed.
"""
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(ROOT / "scripts" / "windows"))
sys.path.insert(0, str(ROOT / "packaging"))

import legacy  # noqa: E402
import retire_legacy as rl  # noqa: E402
import switch  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


TASK_XML = '<?xml version="1.0" encoding="UTF-16"?><Task></Task>'.encode("utf-16")


class FakeMachine:
    def __init__(self, task_running=True, watchdog=4, old_service=1, old_task=True,
                 eventlog=True, admin=True, refs=()):
        self.task_running, self.watchdog, self.old_service = task_running, watchdog, old_service
        self.old_task, self.eventlog, self.admin = old_task, eventlog, admin
        self.calls = []          # every command, captured or run, in order
        self.refs = list(refs)   # (where, text): task actions, desktop scripts

    def service_state(self, name):
        return self.watchdog if name == rl.NEW_WATCHDOG else self.old_service

    def new_task_running(self):
        return self.task_running

    def task_exists(self, name):
        return self.old_task and name == rl.OLD_TASK

    def reg_key_exists(self, key):
        return self.eventlog and key == rl.EVENTLOG_KEY

    def is_admin(self):
        return self.admin

    def references(self):
        return self.refs

    def capture(self, cmd):
        self.calls.append(" ".join(cmd))
        if cmd[:2] == ["reg", "export"]:
            Path(cmd[3]).write_text("Windows Registry Editor Version 5.00\n", encoding="utf-8")
        return 0, (TASK_XML if "/xml" in cmd else b"SERVICE_NAME: ark-relay\n")

    def run(self, cmd):
        self.calls.append(" ".join(cmd))
        if cmd[:2] == ["sc", "delete"]:
            self.old_service = None
        if cmd[:2] == ["schtasks", "/delete"]:
            self.old_task = False
        if cmd[:2] == ["reg", "delete"]:
            self.eventlog = False
        return 0


KEPT = [  # (path under ProgramData, content): must stay where and as they are
    ("ark-relay/.env", "ARK_X=1\n"),
    ("ark-relay/state/state.json", "{}"),
    ("ark-relay/state/legacy-takeover.json", "{}"),
    ("ark-relay/relay.log", "log"),
    ("ark-relay/relay.log.1", "old log"),
    ("ark-relay/watchdog.log", "w"),
    ("ark-relay/switch.log", "s"),
    ("ark-okww-overlay.json", "{}"),
    ("ark-okww-master.txt", "m"),
    ("ark-okww-farm.bat", "@echo off"),
    ("ark-okww-stop.bat", "@echo off"),
    ("ark-gui.ps1", "#"),
    ("ark-shot.png", "png"),
    ("ark-queue-watch.json", "{}"),
    ("arklog.py", "#"),
    ("winrun.out", "x"),
]
RETIRED = [  # what moves
    "ark-relay/ark_relay/__init__.py", "ark-relay/run.py", "ark-relay/service.py",
    "ark-relay/boot_stages.py", "ark-relay/RELEASE-NOTES.md", "ark-relay/__pycache__/a.pyc",
    "ark-relay/ark-relay.ps1", "ark-relay/ark-relay.cmd", "ark-relay/morning-report.cmd",
    "ark-relay/skip-shutdown.bat", "ark-relay/ark-state/state.json",
    "ark-relay/ocrcrop-test/out.json", "ark-relay/last-run.txt", "ark-relay/plan-check.txt",
    "ark-relay/.env.bak-tuning", "ark-relay-deploy-prev/snapshot.json", "ark-hist/INDEX.txt",
    "ark-shot.jpg", "ark-tmp/q.json", "okww-shot-0.png", "focus-watch.bat",
]
LEFT = ["ark-cmd.txt", "ark-relay/.env.env.bak", "ark-mystery.txt"]
# The entries actually moved: the top folder or file of each, inside the data folder its child.
TOP_MOVES = {"/".join(r.split("/")[:2]) if r.startswith("ark-relay/") else r.split("/")[0]
             for r in RETIRED}


def make_tree(base: Path) -> "tuple[Path, Path]":
    pd, pkg = base / "ProgramData", base / "ArkRelay"
    for rel, text in KEPT:
        (pd / rel).parent.mkdir(parents=True, exist_ok=True)
        (pd / rel).write_text(text, encoding="utf-8")
    for rel in RETIRED + LEFT:
        (pd / rel).parent.mkdir(parents=True, exist_ok=True)
        (pd / rel).write_text("old " + rel, encoding="utf-8")
    pkg.mkdir()
    (pkg / "current.txt").write_text("v1", encoding="utf-8")
    return pd, pkg


def snapshot(base: Path) -> dict:
    out = {}
    for root, dirs, files in os.walk(base):
        for name in dirs + files:
            p = Path(root) / name
            st = p.stat()
            out[str(p.relative_to(base))] = (p.read_bytes() if p.is_file() else None, st.st_mtime_ns)
    return out


def run_main(argv, machine, pd, pkg, outside=None):
    """retire_legacy.main with its listing kept out of this test's output."""
    with contextlib.redirect_stdout(io.StringIO()):
        return rl.main(argv, machine=machine, pd=pd, package=pkg,
                       keep_outside={} if outside is None else outside)


print("[the move list and the keep list never overlap]")
moves = {m.lower() for m in rl.MOVE}
check("no MOVE entry is in KEEP", sorted(moves & {k.lower() for k in rl.KEEP}), [])
import fnmatch  # noqa: E402
check("no MOVE entry matches a KEEP glob",
      sorted(m for m in rl.MOVE for g in rl.KEEP_GLOBS if fnmatch.fnmatch(m.lower(), g.lower())), [])
check("the data folder itself never moves", rl.DATA_NAME.lower() in moves, False)
check("every old-code name packaging/legacy.py knows is retired too",
      sorted(set(legacy.OLD_CODE) - set(rl.OLD_CODE)), [])

print("\n[dry run: plan as expected, nothing changed]")
with tempfile.TemporaryDirectory() as t:
    pd, pkg = make_tree(Path(t))
    before = snapshot(Path(t))
    m = FakeMachine()
    rc = run_main([], m, pd, pkg)
    check("exit 0", rc, 0)
    check("tree byte-for-byte unchanged", snapshot(Path(t)) == before, True)
    check("no command run", m.calls, [])
    check("retired folder not created", (pd / rl.RETIRED_NAME).exists(), False)
    plan = rl.make_plan(m, pd, pkg, {})
    planned = {str(s.relative_to(pd)).replace(os.sep, "/") for s, _ in plan.moves}
    check("plan moves exactly the old relay's leftovers", sorted(planned), sorted(TOP_MOVES))
    kept_planned = [k for k, _ in KEPT if any(rl._inside(rl._norm(pd / k), rl._norm(s))
                                              for s, _ in plan.moves)]
    check("no kept path in the plan", kept_planned, [])
    left = sorted(str(p.relative_to(pd)).replace(os.sep, "/") for p, _ in plan.left)
    check("referenced / unlisted / unknown ones listed as left", left, sorted(LEFT))
    check("service, event log, task found", (plan.service, plan.eventlog, plan.task),
          (True, True, True))

print("\n[new relay not running: nothing done]")
for label, kw, drop_current in [("task not running", {"task_running": False}, False),
                                ("watchdog stopped", {"watchdog": 1}, False),
                                ("no watchdog service", {"watchdog": None}, False),
                                ("no current.txt", {}, True)]:
    with tempfile.TemporaryDirectory() as t:
        pd, pkg = make_tree(Path(t))
        if drop_current:
            (pkg / "current.txt").unlink()
        before = snapshot(Path(t))
        m = FakeMachine(**kw)
        rc = run_main(["--go"], m, pd, pkg)
        check(f"{label}: exit 2", rc, 2)
        check(f"{label}: tree unchanged", snapshot(Path(t)) == before, True)
        check(f"{label}: no command run", m.calls, [])

print("\n[a planned move that touches a kept path stops the whole run]")
cases = [
    ("live state folder is ark-state (.env)", lambda pd: (pd / "ark-relay/.env").write_text(
        "ARK_STATE_DIR=./ark-state\n", encoding="utf-8"), None),
    ("a kept path is planned for moving", None, ("ark-hist", "planted")),
    ("a kept path lies inside a planned move", None, ("ark-relay-deploy-prev/snapshot.json", "x")),
]
for label, prepare, plant in cases:
    with tempfile.TemporaryDirectory() as t:
        pd, pkg = make_tree(Path(t))
        if prepare:
            prepare(pd)
        saved = dict(rl.KEEP)
        if plant:
            rl.KEEP[plant[0]] = plant[1]
        try:
            before = snapshot(Path(t))
            m = FakeMachine()
            rc = run_main(["--go"], m, pd, pkg)
        finally:
            rl.KEEP.clear()
            rl.KEEP.update(saved)
        check(f"{label}: exit 3", rc, 3)
        check(f"{label}: tree unchanged", snapshot(Path(t)) == before, True)
        check(f"{label}: no command run", m.calls, [])
print("\n[something kept that names a planned move stops the whole run]")
for label, prepare, refs in [
    ("a kept .bat starts a moved script",
     lambda pd: (pd / "ark-okww-stop.bat").write_text(
         f'@echo off\r\ncall "{pd}\\ark-relay\\skip-shutdown.bat"\r\n', encoding="utf-8"), ()),
    ("a task runs a file in a moved folder",
     None, lambda pd: [("task \\1232", f"cmd /c {pd}/ark-tmp/q.json")]),
    ("a desktop shortcut points at moved code",
     None, lambda pd: [("Desktop\\x.lnk", "%ProgramData%/ark-relay/run.py ")]),
]:
    with tempfile.TemporaryDirectory() as t:
        pd, pkg = make_tree(Path(t))
        if prepare:
            prepare(pd)
        before = snapshot(Path(t))
        m = FakeMachine(refs=refs(pd) if refs else ())
        rc = run_main(["--go"], m, pd, pkg)
        check(f"{label}: exit 3", rc, 3)
        check(f"{label}: tree unchanged", snapshot(Path(t)) == before, True)
        check(f"{label}: no command run", m.calls, [])
with tempfile.TemporaryDirectory() as t:
    pd, pkg = make_tree(Path(t))
    m = FakeMachine(refs=[("task \\x", f"{pd}/ark-tmp2/a.bat {pd}/ark-relay/run.pyc")])
    check("a longer name that only starts like a moved one: not a hit",
          rl.make_plan(m, pd, pkg, {}).aborted, [])
    (pd / "winrun.ps1").write_text(f'cmd /c "if exist {pd}\\ark-relay\\run.py echo x"', encoding="utf-8")
    (pd / "winrun-run-1-2.py").write_text(f'"{pd}\\ark-relay-deploy-prev"', encoding="utf-8")
    check("winrun's per-call files (last command, this script itself): not searched",
          rl.make_plan(FakeMachine(), pd, pkg, {}).aborted, [])
    check("a task list that cannot be read stops the run",
          len(rl.make_plan(FakeMachine(refs=[("task list", "<unreadable: x>")]), pd, pkg, {}).aborted), 1)

with tempfile.TemporaryDirectory() as t:
    pd, pkg = make_tree(Path(t))
    before = snapshot(Path(t))
    m = FakeMachine()
    rc = run_main(["--go"], m, pd, pkg, outside={str(pd / "ark-tmp"): "planted outside"})
    check("an outside keep path hit: exit 3", rc, 3)
    check("an outside keep path hit: tree unchanged", snapshot(Path(t)) == before, True)

print("\n[old service running, or not elevated: nothing done]")
for label, kw, want in [("old service running", {"old_service": 4}, 3),
                        ("old service state unreadable", {"old_service": -1}, 3),
                        ("not elevated", {"admin": False}, 4)]:
    with tempfile.TemporaryDirectory() as t:
        pd, pkg = make_tree(Path(t))
        before = snapshot(Path(t))
        m = FakeMachine(**kw)
        rc = run_main(["--go"], m, pd, pkg)
        check(f"{label}: exit {want}", rc, want)
        check(f"{label}: tree unchanged", snapshot(Path(t)) == before, True)
        check(f"{label}: no command run", m.calls, [])

print("\n[--go: kept stays, the rest moves under its relative path, saved before deleted]")
with tempfile.TemporaryDirectory() as t:
    pd, pkg = make_tree(Path(t))
    m = FakeMachine()
    rc = run_main(["--go"], m, pd, pkg)
    check("exit 0", rc, 0)
    retired = pd / rl.RETIRED_NAME
    check("every kept file still there, same content",
          [k for k, text in KEPT if not (pd / k).is_file()
           or (pd / k).read_text(encoding="utf-8") != text], [])
    check("every retired file gone from its place", [r for r in RETIRED if (pd / r).exists()], [])
    check("every retired file under the same relative path",
          [r for r in RETIRED if (retired / r).read_text(encoding="utf-8") != "old " + r], [])
    check("left ones untouched", [r for r in LEFT if not (pd / r).is_file()], [])
    manifest = (retired / "manifest.txt").read_text(encoding="utf-8")
    check("manifest has a moved line per move", manifest.count("\tmoved\t"), len(TOP_MOVES))
    check("manifest names the 30-day clear-out", "clear this folder after 30 days" in manifest, True)

    def at(prefix):
        return next(i for i, c in enumerate(m.calls) if c.startswith(prefix))
    check("sc qc saved before sc delete", at("sc qc") < at("sc delete"), True)
    check("service key exported before sc delete", at("reg export " + rl.SERVICE_KEY) < at("sc delete"),
          True)
    check("event-log key exported before it is deleted",
          at("reg export " + rl.EVENTLOG_KEY) < at("reg delete " + rl.EVENTLOG_KEY), True)
    check("task xml saved before the task is deleted",
          at("schtasks /query /tn \\ark-relay /xml") < at("schtasks /delete"), True)
    xml = (retired / "ark-relay.task.xml").read_bytes()
    check("task xml kept as UTF-16 with BOM", (xml[:2], "<Task" in xml.decode("utf-16")),
          (b"\xff\xfe", True))
    check("saved files present", sorted(p.name for p in retired.iterdir() if p.is_file()
                                        and p.name.startswith("ark-relay.")),
          ["ark-relay.eventlog.reg", "ark-relay.eventlog.reg.log", "ark-relay.sc-qc.txt",
           "ark-relay.sc-qfailure.txt", "ark-relay.service.reg", "ark-relay.service.reg.log",
           "ark-relay.task.xml"])
    print("  (a second run: nothing left to do)")
    m2 = FakeMachine(old_service=m.old_service, old_task=m.old_task, eventlog=m.eventlog)
    check("second --go exit 0", run_main(["--go"], m2, pd, pkg), 0)
    check("second --go deletes nothing", [c for c in m2.calls if "delete" in c], [])

print("\n[switch.py revert with the old relay retired: nothing changes, exit 6]")
steps = []
saved = (legacy.old_relay_present, switch._handover_rollback, switch._switch_off_new,
         switch._switch_on_new, legacy.undo_takeover, switch.run)
legacy.old_relay_present = lambda: False
switch._handover_rollback = lambda: steps.append("handover rollback") or 0
switch._switch_off_new = lambda: steps.append("switch off new")
switch._switch_on_new = lambda: steps.append("switch on new")
legacy.undo_takeover = lambda: steps.append("undo takeover") or 0
switch.run = lambda *cmd: steps.append("run " + " ".join(map(str, cmd))) or 0
try:
    check("revert exit", switch.revert(), 6)
    check("revert touched nothing", steps, [])
    switch._back_to_old_after_failed_install()
    check("a failed upgrade switches the new relay on again, nothing else", steps,
          ["switch on new"])
    steps.clear()
    legacy.old_relay_present = lambda: True
    switch._back_to_old_after_failed_install()
    check("with the old relay present: back to it as before", steps,
          ["switch off new", "handover rollback", "undo takeover"])
finally:
    (legacy.old_relay_present, switch._handover_rollback, switch._switch_off_new,
     switch._switch_on_new, legacy.undo_takeover, switch.run) = saved

print("\n[legacy.py with the old service gone]")
runs = []
saved = (legacy.service_exists, legacy._run, legacy._task_names, legacy.TAKEOVER_RECORD,
         legacy.ITEMS)
legacy.ITEMS = RELAY / "handover" / "legacy-items.json"     # handover\ next to it when packaged
legacy.service_exists = lambda name: False
legacy._run = lambda *cmd: runs.append(" ".join(cmd)) or 0
legacy._task_names = lambda: []
with tempfile.TemporaryDirectory() as t:
    legacy.TAKEOVER_RECORD = Path(t) / "legacy-takeover.json"
    try:
        legacy.takeover()
        check("takeover runs nothing", runs, [])
        check("takeover writes no record", legacy.TAKEOVER_RECORD.exists(), False)
        check("undo_takeover says 1060", legacy.undo_takeover(), 1060)
        check("undo_takeover runs nothing", runs, [])
        legacy.remove()
        check("remove skips the gone service (no sc stop / delete)",
              [r for r in runs if r.startswith("sc ")], [])
    finally:
        (legacy.service_exists, legacy._run, legacy._task_names, legacy.TAKEOVER_RECORD,
         legacy.ITEMS) = saved

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
