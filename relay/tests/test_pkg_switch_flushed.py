"""The new version folder is on disk before current.txt names it.

Audit s24 F2 (10-13): pkg_layout.update copied the folder in use (copytree), let
selfupdate.check write the changed files into the copy, renamed it and wrote
current.txt with fsync - but nothing flushed the copy's files. A power cut right after
the switch could leave current.txt naming a folder whose files were never written out,
and launch.py (which only checks that app_main.py exists) would pick it at every start.
Now every file of the copy, and each of its folders where the OS allows (not Windows),
is fsynced before the switch.
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
here = app / "versions" / "100"
(here / "ark_relay" / "core").mkdir(parents=True)
(here / "app_main.py").write_text("# v100\n", encoding="utf-8")
(here / "ark_relay" / "core" / "x.py").write_text("X = 1\n", encoding="utf-8")
(app / "current.txt").write_text("100\n", encoding="ascii")
pkg_layout.link_state(here, pkg_layout.state_dir(DATA))
pkg_layout.record_running_version(here)
(DATA / "state" / "shared.txt").write_text("data folder, not the code\n", encoding="utf-8")


def landed_round(root: Path) -> list[str]:
    (root / "ark_relay" / "core" / "x.py").write_text("X = 2\n", encoding="utf-8")
    (root / "ark_relay" / "core" / "new.py").write_text("N = 1\n", encoding="utf-8")
    selfupdate._remember_version(root, 200)
    return ["ark_relay/core/x.py", "ark_relay/core/new.py"]


synced: set[int] = set()
at_switch: set[int] = set()
real_fsync, real_set_current = os.fsync, pkg_layout._set_current


def recording_fsync(fd):
    synced.add(os.fstat(fd).st_ino)
    return real_fsync(fd)


def snapshot_set_current(a, name):
    at_switch.update(synced)
    return real_set_current(a, name)


os.fsync = recording_fsync
pkg_layout._set_current = snapshot_set_current
try:
    got = pkg_layout.update(here, landed_round)
finally:
    os.fsync, pkg_layout._set_current = real_fsync, real_set_current

new = app / "versions" / "200"
check("switched to the new folder", (pkg_layout.current(app), len(got)), ("200", 2))
code_files = sorted(p for p in new.rglob("*") if p.is_file() and "state" not in p.relative_to(new).parts)
check("the new folder has its code files", [p.relative_to(new).as_posix() for p in code_files],
      ["app_main.py", "ark_relay/core/new.py", "ark_relay/core/x.py"])
check("every code file fsynced before current.txt was written",
      [p.relative_to(new).as_posix() for p in code_files if p.stat().st_ino not in at_switch], [])
if os.name != "nt":
    dirs = [new, new / "ark_relay", new / "ark_relay" / "core"]
    check("its folders fsynced before current.txt was written",
          [str(d.relative_to(app)) for d in dirs if d.stat().st_ino not in at_switch], [])
check("the shared state behind the junction is not walked",
      (DATA / "state" / "shared.txt").stat().st_ino in at_switch, False)

print("[a file that cannot be opened for the flush is skipped, the rest still flushed]")
held = tmpdir() / "v"
(held / "sub").mkdir(parents=True)
(held / "a.py").write_text("a", encoding="utf-8")
(held / "sub" / "b.py").write_text("b", encoding="utf-8")
opened: list = []


def picky_open(path, mode="r", *a, **k):
    if Path(path).name == "a.py":
        raise PermissionError(13, "held by a scanner")
    opened.append(Path(path).name)
    return open(path, mode, *a, **k)


pkg_layout.open = picky_open
try:
    pkg_layout._flush_tree(held)
    raised = False
except OSError:
    raised = True
finally:
    del pkg_layout.open
check("one held file does not stop the flush (no error)", raised, False)
check("the other file is still flushed", opened, ["b.py"])

if fails:
    print("FAIL:", fails)
    sys.exit(1)
print("all checks passed")
