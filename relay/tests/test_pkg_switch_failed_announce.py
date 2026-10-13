"""A switch to the new version folder that fails says 「更新没生效」, not 「中继已更新」.

Audit s24 F1 (10-13): pkg_layout.update runs selfupdate.check on a staging copy whose
`state` is the shared state folder. A round that lands records the new version, clears
update-failed.json and writes update-announce.json there. When the rename of the copy
or the current.txt write then raised, update's except put only the version record back:
the same boot's _stage_announce_update pushed 「🔄 中继已更新」 while the old folder
ran, and no 「更新没生效」 went out (repro: scratchpad core-audit/s24/repro.py).

Also checked here:
- a power cut between check and the switch leaves the same note behind; the next start
  (record_running_version) drops a note for code newer than the folder in use, while a
  note for the folder in use (the first boot after a real switch) stays;
- app_main._packaged_selfupdate exits (True) when update() already switched current.txt
  and only restart_soon raised: the watchdog starts the new folder, instead of the old
  process running on and announcing the new version.
"""
import logging
import os
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))

from _tmp import tmpdir  # noqa: E402

TMP = tmpdir()
DATA = TMP / "data"
DATA.mkdir()
os.environ["ARK_HOME"] = str(DATA)
for k in ("ARK_STATE_DIR", "ARK_LOG_FILE"):
    os.environ.pop(k, None)

import pkg_layout  # noqa: E402
from ark_relay.features.selfupdate import selfupdate  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


app = TMP / "app"
here = app / "versions" / "100"
here.mkdir(parents=True)
(here / "app_main.py").write_text("# v100\n", encoding="utf-8")
(app / "current.txt").write_text("100\n", encoding="ascii")
pkg_layout.link_state(here, pkg_layout.state_dir(DATA))
pkg_layout.record_running_version(here)
selfupdate._remember_announced(here, 100)     # v100 was announced when it landed


def landed_round(root: Path) -> list[str]:
    # What selfupdate.check does on a round that lands (selfupdate.py, end of check).
    selfupdate._remember_version(root, 200)
    selfupdate._clear_failure(root)
    selfupdate._record_announcement(root, {"version": 200, "previous": 100, "files": ["x.py"]})
    return ["x.py"]


print("switch raises after check landed")
real_replace = os.replace


def folder_in_use(a, b):
    if str(a).endswith(pkg_layout.STAGING):
        raise PermissionError(5, "Access is denied (folder in use)")
    return real_replace(a, b)


os.replace = folder_in_use
try:
    pkg_layout.update(here, landed_round)
    raised = None
except PermissionError as exc:
    raised = exc
finally:
    os.replace = real_replace
check("update raised", type(raised).__name__, "PermissionError")
check("still running folder 100", pkg_layout.current(app), "100")
check("staging copy dropped", (app / "versions" / pkg_layout.STAGING).exists(), False)
check("record names the folder in use", selfupdate._applied_version(here), 100)
check("no 「中继已更新」 for code that is not running", selfupdate.pending_announcement(here), None)
fail = selfupdate.take_failure(here) or {}
check("「更新没生效」 recorded: remote", fail.get("remote"), 200)
check("「更新没生效」 recorded: local", fail.get("local"), 100)
check("「更新没生效」 recorded: files", fail.get("files"), ["x.py"])
check("「更新没生效」 has a reason", bool(fail.get("reason")), True)

print("power cut between check and the switch")
# The interrupted round's note survives in the shared state; the next start runs
# record_running_version on the old folder before anything announces.
landed_round(here)
pkg_layout.record_running_version(here)
check("record back on the folder in use", selfupdate._applied_version(here), 100)
check("note for v200 dropped at the next start", selfupdate.pending_announcement(here), None)

print("a note for the folder in use stays (first boot after a real switch)")
new = app / "versions" / "200"
new.mkdir()
(new / "app_main.py").write_text("# v200\n", encoding="utf-8")
pkg_layout.link_state(new, pkg_layout.state_dir(DATA))
(app / "current.txt").write_text("200\n", encoding="ascii")
landed_round(new)
pkg_layout.record_running_version(new)
note = selfupdate.pending_announcement(new) or {}
check("note for v200 announced by v200", (note.get("version"), note.get("files")), (200, ["x.py"]))

print("restart_soon raises after current.txt was switched")
import app_main  # noqa: E402

real = pkg_layout.update, pkg_layout.restart_soon, pkg_layout.app_root


def no_restart(_app):
    raise OSError(2, "pythonw.exe not found")


pkg_layout.update = lambda _here, _check: ["x.py"]
pkg_layout.restart_soon = no_restart
pkg_layout.app_root = lambda _here: app
try:
    got = app_main._packaged_selfupdate(logging.getLogger("ark.test"))
finally:
    pkg_layout.update, pkg_layout.restart_soon, pkg_layout.app_root = real
check("process exits so the watchdog starts the switched folder", got, True)

print("an update that changes nothing still continues the boot")
pkg_layout.update = lambda _here, _check: []
try:
    got = app_main._packaged_selfupdate(logging.getLogger("ark.test"))
finally:
    pkg_layout.update = real[0]
check("nothing changed: boot continues", got, False)

if fails:
    print("FAIL:", fails)
    sys.exit(1)
print("all checks passed")
