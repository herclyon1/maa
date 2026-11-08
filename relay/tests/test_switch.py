"""The packaged install's switch: resume, run encoding, stop and uninstall.

One part per former file, each run on its own (tests/_parts.py): test_switch_resume.py, test_switch_run_encoding.py, test_switch_stop.py, test_switch_uninstall.py.
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


def _part_switch_resume():
    """An upgrade that is cancelled after it stopped the relay starts the previous version again.

2026-10-11 (review round 10 #28): the installer's PrepareToInstall runs `switch.py stop`
(watchdog, restart helper, relay; stop marker written). When Setup then ended before
ssPostInstall - Cancel, or a file that could not be replaced (Abort) - nothing started
the relay again until the next logon. Now DeinitializeSetup runs `switch.py resume
--current=<the name current.txt held before>`: current.txt goes back to that folder when
the rollback left it on another one (Inno Setup keeps files it already replaced), then
the watchdog and the task start as uninstall's way back does (switch.start).

    Formerly test_switch_resume.py.
    """
    import re
    import tempfile

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(ROOT / "packaging"))

    import switch


    def resume_in(app: Path, current: str, *, watchdog_rc=0):
        """switch.resume(current) with APP = app and nothing run; the steps taken and its code."""
        steps = []
        saved = switch.APP, switch.run, switch.start_watchdog
        switch.APP = app
        switch.run = lambda *cmd: steps.append(" ".join(map(str, cmd))) or 0
        switch.start_watchdog = lambda: steps.append("start_watchdog") or watchdog_rc
        try:
            rc = switch.resume(current)
        finally:
            switch.APP, switch.run, switch.start_watchdog = saved
        return steps, rc


    def make_app(root: Path, current: "str | None", folders: list[str]) -> Path:
        app = root / "ArkRelay"
        for name in folders:
            (app / "versions" / name).mkdir(parents=True)
            (app / "versions" / name / "app_main.py").write_text("", encoding="ascii")
        app.mkdir(exist_ok=True)
        if current is not None:
            (app / "current.txt").write_text(current + "\r\n", encoding="ascii")
        return app


    def current_of(app: Path) -> str:
        p = app / "current.txt"
        return p.read_text(encoding="ascii").strip() if p.exists() else "(none)"


    TASK_RUN = f"schtasks.exe /run /tn {switch.TASK_PATH}{switch.TASK_NAME}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        print("[cancelled before current.txt was copied: start what is there]")
        app = make_app(tmp / "a", "1300", ["1300"])
        steps, rc = resume_in(app, "1300")
        check("current.txt unchanged", current_of(app), "1300")
        check("watchdog started, then the task run", steps, ["start_watchdog", TASK_RUN])
        check("exit 0", rc, 0)

        print("[cancelled after current.txt was copied, new folder rolled back]")
        app = make_app(tmp / "b", "1310", ["1300"])
        steps, rc = resume_in(app, "1300")
        check("current.txt back on the version that ran", current_of(app), "1300")
        check("no temp file left", (app / "current.txt.tmp").exists(), False)
        check("then watchdog and task", steps, ["start_watchdog", TASK_RUN])

        print("[cancelled after current.txt was copied, new folder still there]")
        app = make_app(tmp / "c", "1310", ["1300", "1310"])
        resume_in(app, "1300")
        check("current.txt back on the version that ran", current_of(app), "1300")

        print("[the previous folder is not complete: current.txt left alone]")
        app = make_app(tmp / "d", "1310", ["1310"])
        (app / "versions" / "1300").mkdir()
        steps, rc = resume_in(app, "1300")
        check("current.txt unchanged", current_of(app), "1310")
        check("still started", steps, ["start_watchdog", TASK_RUN])

        print("[no name from the installer (no current.txt before): left alone]")
        app = make_app(tmp / "e", "1310", ["1310"])
        resume_in(app, "")
        check("current.txt unchanged", current_of(app), "1310")

        print("[watchdog did not come up: the task still runs, exit says so]")
        app = make_app(tmp / "f", "1300", ["1300"])
        steps, rc = resume_in(app, "1300", watchdog_rc=1)
        check("task run anyway", steps, ["start_watchdog", TASK_RUN])
        check("exit 1", rc, 1)

    print("[uninstall's way back is the same start()]")
    src = (ROOT / "packaging" / "switch.py").read_text(encoding="utf-8")
    body = src.split("def uninstall()", 1)[1].split("\ndef ", 1)[0]
    check("uninstall calls start() when AUTO-MAS is not put back", "start()" in body, True)
    check("switch.py dispatches resume with --current=",
          'args[:1] == ["resume"]' in src and '"--current="' in src, True)

    print("[the installer: DeinitializeSetup resumes only between stop and the switch-over]")
    iss = (ROOT / "packaging" / "ark-relay.iss").read_text(encoding="utf-8-sig")
    code = iss.split("[Code]", 1)[1]


    def proc(name: str) -> str:
        m = re.search(rf"\n(?:procedure|function) {name}\b.*?\nend;", code, re.S)
        return m.group(0) if m else ""


    prep, step, deinit = proc("PrepareToInstall"), proc("CurStepChanged"), proc("DeinitializeSetup")
    check("PrepareToInstall sets the flag before switch.py stop",
          0 <= prep.find("StoppedForUpgrade := True") < prep.find("stop',"), True)
    check("ssPostInstall clears it before switch.py install",
          0 <= step.find("StoppedForUpgrade := False") < step.find("RunSwitch(Args)"), True)
    check("DeinitializeSetup exists and is guarded by the flag",
          "if not StoppedForUpgrade then" in deinit, True)
    check("DeinitializeSetup runs switch.py resume with the old current.txt",
          "RunSwitch('resume \"--current=' + OldCurrent + '\"')" in deinit, True)
    files = iss.split("[Files]", 1)[1].split("\n[", 1)[0]
    sources = re.findall(r'^Source: "([^"]+)"', files, re.M)
    check("switch.py and legacy.py are copied before everything else",
          sources[:2], ["legacy.py", "switch.py"])

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_switch_run_encoding():
    """switch.run decodes Windows tools' output in the console code page, not UTF-8.

2026-10-13 (audit of the install / switch-over block, item 4): the machine's switch.log
(the install of 2026-10-11 10:04) has `[SC] ChangeServiceConfig �ɹ�` where sc.exe wrote
成功 in code page 936; switch.run decoded every tool's output as UTF-8. Now "oem".
The codec exists only on Windows, so this checks what run() passes to subprocess.run
and that 936 bytes decode cleanly under the code page "oem" maps to on his machine.

    Formerly test_switch_run_encoding.py.
    """

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY.parent / "packaging"))

    import switch


    class Done:
        returncode, stdout, stderr = 0, "", ""


    seen = {}


    def fake_run(cmd, **kw):
        seen.update(kw)
        return Done()


    had_flag = hasattr(switch.subprocess, "CREATE_NO_WINDOW")
    saved = switch.subprocess.run
    switch.subprocess.run = fake_run
    if not had_flag:
        switch.subprocess.CREATE_NO_WINDOW = 0
    try:
        switch.run("sc.exe", "config", "ArkRelayWatchdog", "start=", "auto")
    finally:
        switch.subprocess.run = saved
        if not had_flag:
            del switch.subprocess.CREATE_NO_WINDOW

    print("[switch.run]")
    check("decodes in the console code page", seen.get("encoding"), "oem")
    check("never raises on a byte it cannot map", seen.get("errors"), "replace")
    sc_ok = "[SC] ChangeServiceConfig 成功".encode("cp936")
    check("the machine's bytes read back under cp936 (what oem is there)",
          sc_ok.decode("cp936"), "[SC] ChangeServiceConfig 成功")
    check("and were mojibake under UTF-8", "成功" in sc_ok.decode("utf-8", "replace"), False)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_switch_stop():
    """switch.py stop() - before an upgrade, at uninstall and at revert - ends the update's
restart helper before it stops the relay.

2026-10-11 (review round 8 #23): stop() stopped the watchdog and the relay but not
`launch.py relaunch` (pkg_layout.restart_soon). Within two minutes of a self-update or
rollback the helper started the relay again under the installer, or left one running
after an uninstall. a8c22829's launch.py gives up once a running watchdog stops, but not
a helper that started while the watchdog was down, nor one from an older package; stop()
now ends it as scripts/mac/estop.sh does.

    Formerly test_switch_stop.py.
    """
    import fnmatch
    import subprocess

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(RELAY))
    sys.path.insert(0, str(ROOT / "packaging"))

    import pkg_layout
    import switch


    def like(text: str, pattern: str) -> bool:
        """PowerShell -like: wildcards * ? [], case-insensitive."""
        return fnmatch.fnmatchcase(text.lower(), pattern.lower())


    print("[stop(): watchdog, then the helper, then the relay]")
    steps = []
    real_run, real_wd = switch.run, switch.stop_watchdog
    switch.run = lambda *cmd: steps.append(("run", tuple(map(str, cmd)))) or 0
    switch.stop_watchdog = lambda: steps.append(("watchdog",))
    try:
        switch.stop()
    finally:
        switch.run, switch.stop_watchdog = real_run, real_wd


    def kind(step):
        if step[0] == "watchdog":
            return "watchdog"
        cmd = step[1]
        if cmd[0] == "powershell.exe" and switch.HELPER_LIKE in cmd[-1]:
            return "helper"
        if cmd[-2:] == (str(switch.APP / "launch.py"), "stop"):
            return "relay"
        return "other: " + " ".join(cmd)


    check("order", [kind(s) for s in steps], ["watchdog", "helper", "relay"])
    ps = next((s[1][-1] for s in steps if kind(s) == "helper"), "")
    check("looks only at pythonw.exe (restart_soon starts the helper with it)",
          "Name='pythonw.exe'" in ps, True)
    check("ends what it finds", "Stop-Process" in ps, True)

    print("[the match: the helper restart_soon starts, and nothing else]")
    calls = []
    pkg_layout.restart_soon(Path("C:/Program Files/ArkRelay"), popen=lambda cmd, creationflags=0: calls.append(cmd))
    helper_line = subprocess.list2cmdline(calls[0])
    check("restart_soon's helper matches", like(helper_line, switch.HELPER_LIKE), True)
    check("same match as estop.sh",
          f"-like '{switch.HELPER_LIKE}'" in (ROOT / "scripts" / "mac" / "estop.sh").read_text(encoding="utf-8"),
          True)
    relay_line = subprocess.list2cmdline([r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe",
                                          r"C:\Program Files\ArkRelay\launch.py"])
    check("the relay itself (task \\ArkRelay\\main) does not match", like(relay_line, switch.HELPER_LIKE), False)
    stop_line = subprocess.list2cmdline([str(switch.PY), str(switch.APP / "launch.py"), "stop"])
    check("launch.py stop does not match", like(stop_line, switch.HELPER_LIKE), False)

    print("[uninstall(): the task, then its \\ArkRelay\\ folder in Task Scheduler]")
    # schtasks /delete removes the task and leaves its folder (found comparing the install with the old service, 2026-10-11).


    class FakeScheduler:
        """Schedule.Service as delete_task_folder uses it; `fail` makes DeleteFolder raise."""

        def __init__(self, fail=False):
            self.fail, self.calls = fail, []

        def GetFolder(self, path):  # noqa: N802 - COM name
            self.calls.append(("GetFolder", path))
            return self

        def DeleteFolder(self, name, flags):  # noqa: N802 - COM name
            self.calls.append(("DeleteFolder", name, flags))
            if self.fail:
                raise OSError("the folder still holds a task")


    steps = []
    saved = (switch.stop, switch._handover_rollback, switch.run, switch._mark_watchdog_stopped,
             switch.legacy.remove, switch.delete_task_folder)
    sched = FakeScheduler()
    real_delete = switch.delete_task_folder
    switch.stop = lambda: steps.append("stop")
    switch._handover_rollback = lambda: 0
    switch.run = lambda *cmd: steps.append(" ".join(map(str, cmd[:2]))) or 0
    switch._mark_watchdog_stopped = lambda on: None
    switch.legacy.remove = lambda: steps.append("legacy")
    switch.delete_task_folder = lambda: steps.append("folder") or real_delete(connect=lambda: sched)
    try:
        rc = switch.uninstall()
    finally:
        (switch.stop, switch._handover_rollback, switch.run, switch._mark_watchdog_stopped,
         switch.legacy.remove, switch.delete_task_folder) = saved
    check("uninstall exit", rc, 0)
    check("folder deleted after the task", steps.index("folder") > steps.index("schtasks.exe /delete"), True)
    check("the root folder deletes ArkRelay with flags 0", sched.calls, [("GetFolder", "\\"), ("DeleteFolder", "ArkRelay", 0)])
    check("a folder that cannot go does not fail the uninstall",
          switch.delete_task_folder(connect=lambda: FakeScheduler(fail=True)), False)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_switch_uninstall():
    """An uninstall that fails part way still does every other step and says what is left.

2026-10-13 (audit of the install / switch-over block, item 2): after `switch.py
uninstall` had stopped the relay and put AUTO-MAS back, any exception (a state link that
would not go, a locked leftover file, an unreadable legacy-items.json) ended Python with
exit 1, skipping the rest; the uninstaller treated every non-zero exit as "AUTO-MAS not
put back" and said 「中继已经重新开起来，什么都没删」 - with no relay, no watchdog and
nothing restarted. Now each step after the rollback runs on its own, legacy.remove()
tries each item on its own, a partial uninstall exits 7 with the failed steps in
uninstall-left.txt, and the installer script shows that message only for exit 3.
Fakes for every Windows call; no Windows needed.

    Formerly test_switch_uninstall.py.
    """
    import contextlib
    import io
    import re
    import tempfile

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(ROOT / "packaging"))

    import legacy
    import switch


    def quiet(fn, *args):
        """fn's result with its prints swallowed; an exception becomes its name (a failed
    check, not a crash)."""
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return fn(*args)
        except Exception as exc:  # noqa: BLE001
            return f"raised {type(exc).__name__}"


    NAMES = ("APP", "stop", "start", "_handover_rollback", "run", "delete_task_folder",
             "_mark_watchdog_stopped")


    def uninstall_in(tmp: Path, *, rollback_rc=0, raise_in=""):
        """switch.uninstall() with every Windows call faked; the steps taken, its code and
    the uninstall-left.txt text ('' = none)."""
        steps = []
        app = tmp / "ArkRelay"
        (app / "versions" / "1300").mkdir(parents=True, exist_ok=True)
        left_file = tmp / "uninstall-left.txt"

        def maybe_raise(name):
            steps.append(name)
            if name == raise_in:
                raise OSError(f"{name} is locked")

        def fake_run(*cmd):
            name = "watchdog remove" if "ark_watchdog.py" in " ".join(map(str, cmd)) else "task delete"
            maybe_raise(name)
            return 0

        saved = [getattr(switch, n) for n in NAMES] + [legacy.remove, getattr(switch, "UNINSTALL_LEFT", None)]
        switch.APP = app
        switch.stop = lambda: steps.append("stop") or 0
        switch.start = lambda: steps.append("start") or 0
        switch._handover_rollback = lambda: steps.append("rollback") or rollback_rc
        switch.run = fake_run
        switch.delete_task_folder = lambda: maybe_raise("task folder") or True
        switch._mark_watchdog_stopped = lambda on: maybe_raise("marker")
        legacy.remove = lambda: maybe_raise("legacy remove") or []
        switch.UNINSTALL_LEFT = left_file
        try:
            rc = quiet(switch.uninstall)
        finally:
            for n, v in zip(NAMES, saved[:len(NAMES)], strict=True):
                setattr(switch, n, v)
            legacy.remove = saved[len(NAMES)]
            if saved[-1] is None:
                del switch.UNINSTALL_LEFT
            else:
                switch.UNINSTALL_LEFT = saved[-1]
        left = left_file.read_text(encoding="utf-8") if left_file.exists() else ""
        return steps, rc, left


    ALL = ["stop", "rollback", "watchdog remove", "marker", "task delete", "task folder",
           "legacy remove"]

    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        print("[everything works: exit 0, nothing listed]")
        steps, rc, left = uninstall_in(t / "a")
        check("every step", steps, ALL)
        check("exit 0", rc, 0)
        check("no uninstall-left.txt", left, "")

        print("[AUTO-MAS not put back: nothing removed, relay started, exit 3]")
        steps, rc, left = uninstall_in(t / "b", rollback_rc=1)
        check("steps", steps, ["stop", "rollback", "start"])
        check("exit 3", rc, 3)

        for broken in ("watchdog remove", "marker", "task delete", "task folder", "legacy remove"):
            print(f"[{broken} raises: every other step still runs, exit 7, listed]")
            steps, rc, left = uninstall_in(t / broken.replace(" ", "-"), raise_in=broken)
            check(f"{broken}: every step tried", steps, ALL)
            check(f"{broken}: exit 7 (not 0, not 3)", rc, 7)
            check(f"{broken}: listed in uninstall-left.txt", f"{broken} is locked" in left, True)

    print("[legacy.remove: one item that fails does not stop the rest]")
    deleted, runs = [], []
    saved = (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
             legacy.service_exists, legacy.TAKEOVER_RECORD)


    def fake_delete(p):
        if "locked" in str(p):
            raise PermissionError(f"{p} in use")
        deleted.append(str(p))
        return []


    legacy.items = lambda: [
        {"kind": "file", "path": "C:\\locked.bat", "action": "remove"},
        {"kind": "file", "path": "C:\\free.bat", "action": "remove"},
        {"kind": "task", "name": "ark-old", "action": "remove"},
        {"kind": "service", "name": "ark-svc", "action": "takeover"},
        {"kind": "file", "path": "C:\\kept.txt", "action": "keep"},
    ]
    legacy._delete_path = fake_delete
    legacy._run = lambda *cmd: runs.append(" ".join(cmd)) or (5 if cmd[:2] == ("sc", "delete") else 0)
    legacy._task_names = lambda: ["ark-old"]
    legacy.service_exists = lambda name: True
    with tempfile.TemporaryDirectory() as t:
        legacy.TAKEOVER_RECORD = Path(t) / "legacy-takeover.json"
        try:
            out = quiet(legacy.remove)
        finally:
            (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
             legacy.service_exists, legacy.TAKEOVER_RECORD) = saved
    check("the items after the locked one still removed",
          (deleted, "schtasks /delete /tn ark-old /f" in runs), (["C:\\free.bat"], True))
    check("returns what was not removed (the locked file, the failed sc delete)",
          isinstance(out, list) and len(out) == 2 and "locked.bat" in out[0] and "ark-svc" in out[1], True)
    legacy.items = lambda: (_ for _ in ()).throw(ValueError("bad json"))
    try:
        out = quiet(legacy.remove)
    finally:
        legacy.items = saved[0]
    check("an unreadable list is one failure, not an exception",
          isinstance(out, list) and len(out) == 1 and "bad json" in out[0], True)

    print("[uninstall removes the OK-WW overlay file, and nothing else in OK-WW]")
    # gamesim U9 reported that no code removes ok_tasks/ark_overrides.py (its install cycle
    # deleted the file itself). It is removed: legacy-items.json lists it as a `file` item with
    # action `takeover`, and legacy.remove() deletes every remove/takeover item. Pinned here with
    # the real list, the real remove() and the real _delete_path.
    sys.path.insert(0, str(RELAY))
    from pathlib import PureWindowsPath
    from ark_relay.features.okww_patch import okww_overlay

    OKWW_ROOT = PureWindowsPath(r"D:\ark\okww")     # the machine's OK-WW folder (legacy-items.json)
    want = PureWindowsPath(*okww_overlay._WORKING, okww_overlay.TASKS_DIR, okww_overlay.FILE_NAME)
    saved_items_file = legacy.ITEMS
    legacy.ITEMS = RELAY / "handover" / "legacy-items.json"     # handover\ next to legacy.py when packaged
    real_items = legacy.items()
    ours = [it for it in real_items if it.get("kind") == "file"
            and PureWindowsPath(it["path"]).name == okww_overlay.FILE_NAME]
    check("legacy-items.json lists the overlay file once, as removed at uninstall",
          [(it["action"] in ("remove", "takeover"), PureWindowsPath(it["path"]) == OKWW_ROOT / want) for it in ours],
          [(True, True)])
    asked = []
    saved = (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
             legacy.service_exists, legacy.TAKEOVER_RECORD)
    legacy._delete_path = lambda p: asked.append(PureWindowsPath(str(p))) or []
    legacy._run = lambda *cmd: 0
    legacy._task_names = lambda: []
    legacy.service_exists = lambda name: False
    with tempfile.TemporaryDirectory() as t:
        legacy.TAKEOVER_RECORD = Path(t) / "legacy-takeover.json"
        try:
            quiet(legacy.remove)
        finally:
            (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
             legacy.service_exists, legacy.TAKEOVER_RECORD) = saved
            legacy.ITEMS = saved_items_file
    check("remove() with the real list deletes the overlay file", OKWW_ROOT / want in asked, True)
    check("and nothing else under OK-WW's folder",
          [str(p) for p in asked if str(p).lower().startswith(str(OKWW_ROOT).lower() + "\\")
           and not (p.match("*.py.bak-*") and p.parent.name == "task")], [str(OKWW_ROOT / want)])
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / "okww"
        dest = okww_overlay.target(root)
        dest.parent.mkdir(parents=True)
        dest.write_text("# ours\n", encoding="utf-8")
        theirs = dest.parent / "user_task.py"           # a task the owner put there himself
        theirs.write_text("# his\n", encoding="utf-8")
        upstream = root.joinpath(*okww_overlay._WORKING, "src", "task", "DailyTask.py")
        upstream.parent.mkdir(parents=True)
        upstream.write_text("# upstream\n", encoding="utf-8")
        local = {**ours[0], "path": str(root.joinpath(*PureWindowsPath(ours[0]["path"]).relative_to(OKWW_ROOT).parts))} \
            if ours else {}
        failed, _ = quiet(legacy._remove_one, local, None) if ours else ([], None)
        check("the real removal of that item: our file gone, his task and upstream's file kept",
              (failed, dest.exists(), theirs.exists(), upstream.exists()), ([], False, True, True))

    print("[the uninstaller: 「中继已经重新开起来，什么都没删」 only for exit 3]")
    iss = (ROOT / "packaging" / "ark-relay.iss").read_text(encoding="utf-8-sig")
    m = re.search(r"\nprocedure CurUninstallStepChanged\b.*?\nend;", iss, re.S)
    body = m.group(0) if m else ""
    branches = re.split(r"\n    (?:else )?if Rc ", body)
    restarted = [b.split("\n", 1)[0] for b in branches if "中继已经重新开起来，什么都没删" in b]
    check("that message sits only in the Rc = 3 branch", restarted, ["= 3 then"])
    seven = next((b for b in branches if b.startswith("= 7 then")), "")
    check("exit 7 shows what is left (uninstall-left.txt) and does not abort",
          ("UninstallLeft()" in seven, "RaiseException" in seven), (True, False))
    check("the left list is read from the file switch.py writes",
          "uninstall-left.txt" in iss and switch.UNINSTALL_LEFT.name == "uninstall-left.txt"
          if hasattr(switch, "UNINSTALL_LEFT") else False, True)
    other = next((b for b in branches if b.startswith("<> 0 then")), "")
    check("any other code starts the relay again before aborting",
          0 <= other.find("RunSwitch('start')") < other.find("RaiseException"), True)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


if __name__ == "__main__":
    sys.exit(run_parts([_part_switch_resume, _part_switch_run_encoding, _part_switch_stop, _part_switch_uninstall]))
