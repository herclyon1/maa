"""A deploy with nothing to change leaves the recorded code version on the folder in use.

Audit s19 #4/#5 (10-13): when the manifest is newer but every file already matches,
selfupdate.check stages nothing yet still records the manifest's version
(selfupdate.py, `_remember_version(root, remote_ver)` after an empty `updated`).
The staging copy's `state` is the shared state folder, so versions.code then named a
version pkg_layout.update never switched to (it drops the staging copy when nothing
changed). pending_announcement could say 「中继已更新 → vN」 for code that is not
running. update now puts the record back on the running folder in that case.
"""
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
here = app / "versions" / "5"
here.mkdir(parents=True)
(here / "app_main.py").write_text("# v5\n", encoding="utf-8")
(app / "current.txt").write_text("5\n", encoding="ascii")
pkg_layout.link_state(here, pkg_layout.state_dir(DATA))
pkg_layout.record_running_version(here)
check("record starts on the running folder", selfupdate._applied_version(here), 5)


def check_nothing_to_change(root: Path) -> list[str]:
    # What selfupdate.check does for a newer manifest whose files all match:
    # nothing staged, the manifest's version recorded, [] returned.
    selfupdate._remember_version(root, 7)
    return []


got = pkg_layout.update(here, check_nothing_to_change)
check("update returns nothing", got, [])
check("still running folder 5", pkg_layout.current(app), "5")
check("staging copy dropped", (app / "versions" / pkg_layout.STAGING).exists(), False)
check("record names the folder in use, not v7", selfupdate._applied_version(here), 5)

if fails:
    print("FAIL:", fails)
    sys.exit(1)
print("all ok")
