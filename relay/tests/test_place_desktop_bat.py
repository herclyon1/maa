"""scripts/mac/lib/place_desktop_bat.py replaces his desktop switch safely.

The acceptance session decided (BOARD/DECISIONS.md D-1011-工具最新) that the 08-31
中继关机开关.bat on his desktop, which writes state\\skip-next-shutdown.flag, is replaced in
place by scripts/windows/skip-shutdown.bat; scripts/mac/place-skip-shutdown.py runs
place() on the machine. Checked against a temporary folder: no new file when the target
is missing, the original kept once as the backup, nothing done while the switch's window
is open or when that cannot be told, the new bytes read back, a second run a no-op.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
from place_desktop_bat import place  # noqa: E402

fails = []


def require(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok or not detail else f": {detail}"))
    if not ok:
        fails.append(name)


def run(*a, **k):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = place(*a, **k)
    return rc, out.getvalue()


NEW = (ROOT / "scripts" / "windows" / "skip-shutdown.bat").read_bytes()
OLD = "@echo off\nset FLAG=C:\\ProgramData\\ark-relay\\state\\skip-next-shutdown.flag\n".encode()
SUF = ".bak-1011"
closed = lambda _t: False  # noqa: E731

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    target = d / "中继关机开关.bat"

    rc, out = run(NEW, target, SUF, is_open=closed)
    require("missing target: refused, nothing created", rc == 2 and not list(d.iterdir()), out)

    target.write_bytes(OLD)
    rc, out = run(NEW, target, SUF, check_only=True, is_open=closed)
    require("--check: says WOULD_REPLACE, changes nothing",
          rc == 0 and "WOULD_REPLACE" in out and target.read_bytes() == OLD
          and sorted(p.name for p in d.iterdir()) == [target.name], out)

    for opened, word in ((True, "WINDOW_OPEN"), (None, "UNKNOWN_WINDOW")):
        rc, out = run(NEW, target, SUF, is_open=lambda _t, o=opened: o)
        require(f"window {word}: refused, file untouched",
              rc == 3 and word in out and target.read_bytes() == OLD
              and sorted(p.name for p in d.iterdir()) == [target.name], out)

    rc, out = run(NEW, target, SUF, is_open=closed)
    backup = d / (target.name + SUF)
    require("placed: target holds the repo's bytes", rc == 0 and "PLACED" in out
          and target.read_bytes() == NEW, out)
    require("... the original kept as <name>.bak-1011", backup.read_bytes() == OLD)
    require("... and nothing else left in the folder",
          sorted(p.name for p in d.iterdir()) == sorted([target.name, backup.name]))

    rc, out = run(NEW, target, SUF, is_open=closed)
    require("second run: ALREADY_CURRENT", rc == 0 and "ALREADY_CURRENT" in out, out)

    target.write_bytes(b"something else\r\n")
    rc, out = run(NEW, target, SUF, is_open=closed)
    require("a later run keeps the first backup (the original)",
          rc == 0 and backup.read_bytes() == OLD and "BACKUP=kept" in out, out)

# What the new switch writes reaches a relay that is running, at once, and survives the
# relay's own next write: modes.set_skip_shutdown writes state.json through StateStore
# (read again whenever state.json's mtime changed, then os.replace); the relay builds a
# fresh StateStore per modes call and re-reads by mtime before each set.
sys.path.insert(0, str(ROOT / "relay"))
from ark_relay.core.statestore import StateStore  # noqa: E402
from ark_relay.features.modes import modes  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    st = Path(tmp)
    relay_store = StateStore(st)                 # the running relay's long-lived instance
    relay_store.set("versions", "code", "1")
    ok, msg = modes.set_skip_shutdown(st, True)  # the desktop switch, another process
    require("switch receipt is the relay's own wording",
          ok and msg.startswith("已记下「下次跑完不关机」"), msg)
    require("a running relay sees the mark at once (skip_armed, fresh store)", modes.skip_armed(st))
    require("... and through its long-lived store", relay_store.get("modes", "skip_next_shutdown") is True)
    relay_store.set("versions", "code", "2")     # the relay's next write of another key
    require("the relay's next write keeps the mark", modes.skip_armed(st)
          and StateStore(st).get("versions", "code") == "2")
    modes.set_skip_shutdown(st, False)
    require("pulling it back is seen at once too", not modes.skip_armed(st)
          and relay_store.get("modes", "skip_next_shutdown") is None)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
