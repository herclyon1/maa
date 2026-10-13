"""`app_main.py rollback` says so and exits 1 when the relay does not stop.

Audit s24 F4 (10-13): rollback() switched current.txt, printed `current -> <prev>`,
ignored stop()'s result and returned 0. When the relay did not stop within stop()'s
40 s, `launch.py relaunch` waited its 120 s and gave up, and the version rolled away
from ran on until the next restart while current.txt and the pin named the earlier one.
Now a failed stop prints what is true (current.txt changed, the relay still running,
the earlier version starts at the next restart), skips the restart helper, exits 1.
"""
import contextlib
import io
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))

import app_main  # noqa: E402
import pkg_layout  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def rollback_with(stop_result):
    restarts = []
    real = pkg_layout.app_root, pkg_layout.rollback, pkg_layout.restart_soon, app_main.stop
    pkg_layout.app_root = lambda _here: Path("/app")
    pkg_layout.rollback = lambda _app: "100"
    pkg_layout.restart_soon = lambda app: restarts.append(app)
    app_main.stop = lambda: stop_result
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = app_main.rollback()
    finally:
        pkg_layout.app_root, pkg_layout.rollback, pkg_layout.restart_soon, app_main.stop = real
    return code, out.getvalue(), restarts


print("[the relay stops]")
code, out, restarts = rollback_with(0)
check("exit 0", code, 0)
check("says current -> 100", "current -> 100" in out, True)
check("restart helper started", len(restarts), 1)

print("[the relay does not stop]")
code, out, restarts = rollback_with(1)
check("exit 1", code, 1)
check("does not claim the switch took effect", "current -> 100" in out, False)
check("says the relay did not stop", "did not stop" in out, True)
check("says when 100 starts", "next restart" in out, True)
check("no restart helper (it would wait 120 s and give up)", restarts, [])

if fails:
    print("FAIL:", fails)
    sys.exit(1)
print("all checks passed")
