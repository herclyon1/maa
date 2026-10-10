"""The packaged relay reads and writes its code version in one state folder.

2026-10-11: selfupdate keeps versions.code under <version folder>/state, a junction
to <data>/state, while app_main defaulted ARK_STATE_DIR to <data>/ark-state; the boot
read the other state.json and logged "code version v?" at every start (cloud package
smoke, 2026-10-10 22:37:41 and 22:38:00). Both now name the same folder, and
pkg_deploy's idea of the relay's state folder (STATEDIR=) agrees.
"""
import os
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(RELAY))
sys.path.insert(0, str(ROOT / "scripts" / "windows"))

from _tmp import tmpdir  # noqa: E402

TMP = tmpdir()
DATA = TMP / "data"
DATA.mkdir()
os.environ["ARK_HOME"] = str(DATA)
for k in ("ARK_STATE_DIR", "ARK_LOG_FILE"):
    os.environ.pop(k, None)

import app_main  # noqa: E402
import pkg_deploy  # noqa: E402
from ark_relay import selfupdate  # noqa: E402
from ark_relay.core.config import Config  # noqa: E402
from ark_relay.core.statestore import StateStore  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


print("[app_main: ARK_STATE_DIR defaults to the folder selfupdate writes to]")
check("app_main.DATA is ARK_HOME", app_main.DATA, DATA)
app_main._prepare_env()
check("ARK_STATE_DIR", os.environ.get("ARK_STATE_DIR"), str(DATA / "state"))
check("Config().state_dir", Path(Config().state_dir), DATA / "state")

print("[a version folder's state junction and the boot see the same versions.code]")
code = TMP / "app" / "versions" / "20261011"
code.mkdir(parents=True)
(DATA / "state").mkdir(exist_ok=True)
if os.name == "nt":
    import pkg_layout  # noqa: E402
    pkg_layout.link_state(code, DATA)
else:
    # What pkg_layout.link_state makes on Windows (a junction), as a symlink here.
    os.symlink(DATA / "state", code / "state", target_is_directory=True)
selfupdate._remember_version(code, 20261011)
check("versions.code read at boot", StateStore(Path(Config().state_dir)).get("versions", "code"),
      "20261011")
check("selfupdate reads it back", selfupdate._applied_version(code), 20261011)

print("[pkg_deploy STATEDIR with no ARK_STATE_DIR in .env]")
check("pkg_deploy._state_dir()", pkg_deploy._state_dir(), app_main.state_default(pkg_deploy.DATA))

print("[.env naming a folder still wins]")
os.environ.pop("ARK_STATE_DIR")
(DATA / ".env").write_text(f"ARK_STATE_DIR={TMP / 'elsewhere'}\n", encoding="utf-8")
app_main._prepare_env()
check("ARK_STATE_DIR from .env", os.environ.get("ARK_STATE_DIR"), str(TMP / "elsewhere"))

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
