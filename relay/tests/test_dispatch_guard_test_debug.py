"""A test dispatch turns debug mode on first, and test-off turns off only what it turned on.

2026-10-13 11:05 (Beijing) `run-one.sh OK-WW --test` ran after the morning shift
had spent the one-shot 「下次跑完不关机」 mark; when the run ended the relay logged
11:13:55 「本轮已处理完毕，60 秒后关机」 and powered the machine off, which cannot be
undone remotely. The rule 「临时跑不改排班；维护先开调试模式」 was a habit with
nothing enforcing it. dispatch_guard.start(test=True) now writes the relay's debug
mode (modes.set_debug, the state the debug_mode command writes) before dispatching,
records in the test window that it did, refuses the dispatch when it cannot, and
test_off turns it off again only if this window turned it on.
"""
import contextlib
import inspect
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay"))
sys.path.insert(0, str(ROOT / "relay" / "tests"))
sys.path.insert(0, str(ROOT / "scripts" / "windows"))
import dispatch_guard as g  # noqa: E402
from _tmp import tmpdir  # noqa: E402
from ark_relay.features.modes import modes  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def setup():
    state = tmpdir()
    g.STATE_DIR = str(state)
    g.TEST_WINDOWS = str(state / "test-windows.json")
    return state


dispatched = []
g.status = lambda: []
g.ids = lambda: {"OK-WW": "sid-okww"}
g.post = lambda path, body=None: dispatched.append(body["taskId"]) or {"status": "success"}
g._modes = lambda: modes


def run(fn, *a, **k):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fn(*a, **k)
    return rc, out.getvalue()


def windows():
    return json.loads(Path(g.TEST_WINDOWS).read_text(encoding="utf-8"))


print("[debug off -> the test start turns it on before dispatching, and records it]")
state = setup()
dispatched.clear()
rc, out = run(g.start, "OK-WW", test=True)
check("dispatched", (rc, dispatched), (0, ["sid-okww"]))
check("debug mode on", modes.debug_active(state), True)
check("the window records the debug_until it wrote", windows()[-1].get("debug_set"), modes.debug_until(state))
rc, out = run(g.test_status)
check("test-status says this window turned it on", "调试模式是这个窗口开的" in out, True)
rc, out = run(g.test_off)
check("test-off: window closed", windows()[-1]["until"] is not None, True)
check("test-off: debug mode off again", (rc, modes.debug_active(state)), (0, False))

print("\n[10-13: the morning shift spent 「下次跑完不关机」 (key :3), then a test -> test-off keeps that skip]")
state = setup()
modes.mark_shutdown_skipped(state, "2026-10-13:3")       # what take_skip's caller writes
run(g.start, "OK-WW", test=True)
rc, out = run(g.test_off)
check("test-off: debug mode off", (rc, modes.debug_active(state)), (0, False))
check("test-off: the spent mark's skipped occasion is still there (no power-off after the test)",
      modes.shutdown_skipped(state), "2026-10-13:3")

print("\n[a skip debug mode itself recorded during the window -> test-off releases it]")
state = setup()
run(g.start, "OK-WW", test=True)
can_tag = "by_debug" in inspect.signature(modes.mark_shutdown_skipped).parameters
check("debug mode's own skip is told apart from the mark's", can_tag, True)
if can_tag:
    modes.mark_shutdown_skipped(state, "2026-10-13:4", by_debug=True)   # shutdown._maybe_shutdown, verdict "debug"
    run(g.test_off)
    check("test-off: debug mode's own skip is cleared", modes.shutdown_skipped(state), "")

print("\n[debug already on -> left on, and not turned off at test-off]")
state = setup()
modes.set_debug(state, 2)
before = modes.debug_until(state)
dispatched.clear()
rc, out = run(g.start, "OK-WW", test=True)
check("dispatched", (rc, dispatched), (0, ["sid-okww"]))
check("debug untouched", modes.debug_until(state), before)
check("the window does not claim it", "debug_set" in windows()[-1], False)
rc, out = run(g.test_off)
check("test-off leaves it on", (rc, modes.debug_until(state)), (0, before))

print("\n[changed during the window (e.g. extended from the phone) -> test-off leaves it]")
state = setup()
run(g.start, "OK-WW", test=True)
modes.set_debug(state, 3)
extended = modes.debug_until(state)
run(g.test_off)
check("left as extended", modes.debug_until(state), extended)

print("\n[debug mode cannot be written -> the test dispatch is refused]")
state = setup()


class Broken:
    debug_active = staticmethod(lambda sd: False)
    debug_until = staticmethod(lambda sd: "")

    @staticmethod
    def set_debug(sd, cycles=1, off=False):
        raise OSError(13, "Access is denied")


g._modes = lambda: Broken
dispatched.clear()
rc, out = run(g.start, "OK-WW", test=True)
check("refused, non-zero", rc, 6)
check("nothing dispatched", dispatched, [])
check("says why", "调试模式开不了" in out and "Access is denied" in out, True)
check("no test window opened", Path(g.TEST_WINDOWS).exists(), False)

print("\n[a normal (non-test) dispatch does not touch debug mode]")
state = setup()
g._modes = lambda: modes
dispatched.clear()
rc, out = run(g.start, "OK-WW")
check("dispatched, debug still off", (rc, modes.debug_active(state)), (0, False))

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
