"""An upgrade that is cancelled after it stopped the relay starts the previous version again.

2026-10-11 (review round 10 #28): the installer's PrepareToInstall runs `switch.py stop`
(watchdog, restart helper, relay; stop marker written). When Setup then ended before
ssPostInstall - Cancel, or a file that could not be replaced (Abort) - nothing started
the relay again until the next logon. Now DeinitializeSetup runs `switch.py resume
--current=<the name current.txt held before>`: current.txt goes back to that folder when
the rollback left it on another one (Inno Setup keeps files it already replaced), then
the watchdog and the task start as uninstall's way back does (switch.start). A watchdog
a revert disabled stays off: the old relay is the one on then.
"""
import re
import sys
import tempfile
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(ROOT / "packaging"))

import switch  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def resume_in(app: Path, current: str, *, disabled=False, watchdog_rc=0):
    """switch.resume(current) with APP = app and nothing run; the steps taken and its code."""
    steps = []
    saved = switch.APP, switch.run, switch.start_watchdog, switch._watchdog_disabled
    switch.APP = app
    switch.run = lambda *cmd: steps.append(" ".join(map(str, cmd))) or 0
    switch.start_watchdog = lambda: steps.append("start_watchdog") or watchdog_rc
    switch._watchdog_disabled = lambda: disabled
    try:
        rc = switch.resume(current)
    finally:
        switch.APP, switch.run, switch.start_watchdog, switch._watchdog_disabled = saved
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

    print("[after a revert (watchdog disabled): nothing started]")
    app = make_app(tmp / "g", "1300", ["1300"])
    steps, rc = resume_in(app, "1300", disabled=True)
    check("nothing run", steps, [])
    check("exit 0 (the old relay is the one on)", rc, 0)

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
sys.exit(1 if fails else 0)
