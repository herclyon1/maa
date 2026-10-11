"""The relay starts its watchdog again (watchdog_guard.py), except when it was stopped on purpose.

2026-10-11 (收尾1011): the watchdog starts the relay again, but nothing started the
watchdog again - Windows starts it once at boot (cloud run 38095391114: one start
ended during START_PENDING and stayed stopped). Now each guards the other. Checked:
the decisions (Guard.tick), the stop marker being scoped to this boot, every stopper
(switch.py stop_watchdog, estop.sh) writing the marker before `sc stop` and every
starter deleting it, and app_main starting the thread in the packaged install only.
"""
import os
import re
import sys
import tempfile
import time
import types
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(RELAY))
sys.path.insert(0, str(ROOT / "packaging"))

import watchdog_guard as G  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Logs:
    def __init__(self):
        self.lines = []

    def __enter__(self):
        self.real = G.log.info, G.log.error
        G.log.info = lambda msg, *a, **k: self.lines.append(("INFO", msg % a))
        G.log.error = lambda msg, *a, **k: self.lines.append(("ERROR", msg % a))
        return self

    def __exit__(self, *exc):
        G.log.info, G.log.error = self.real


def guard(states, start_results=(), marker=False):
    states, results, started = list(states), list(start_results), []

    def start():
        started.append(1)
        return results.pop(0) if results else ""
    g = G.Guard(lambda: states.pop(0) if len(states) > 1 else states[0], start, lambda: marker)
    return g, started


print("[what it does on each look]")
for label, state, marker, want in [
        ("running: nothing", ("RUNNING", "AUTO"), False, "running"),
        ("starting up: wait", ("PENDING", "AUTO"), False, "pending"),
        ("not installed (old relay, dev run): nothing", ("MISSING", "OTHER"), False, "missing"),
        ("stopped, disabled (revert): leave it", ("STOPPED", "DISABLED"), False, "disabled"),
        ("stopped, manual start type: leave it", ("STOPPED", "OTHER"), False, "disabled"),
        ("stopped, marker from this boot: leave it", ("STOPPED", "AUTO"), True, "stopped on purpose"),
        ("stopped, automatic, no marker: start it", ("STOPPED", "AUTO"), False, "started")]:
    g, started = guard([state], marker=marker)
    with Logs():
        got = g.tick()
    check(label, (got, len(started)), (want, 1 if want == "started" else 0))

print("[a start that fails: INFO each time, one ERROR at the third, quiet until it runs]")
g, started = guard([("STOPPED", "AUTO")] * 6 + [("RUNNING", "AUTO")] + [("STOPPED", "AUTO")] * 3,
                   ["1053 timeout"] * 9)
with Logs() as logs:
    for _ in range(10):
        g.tick()
errors = [m for lvl, m in logs.lines if lvl == "ERROR"]
check("two ERRORs in two outages of 3+ failures (errwatch pushes each)", len(errors), 2)
check("ERROR says what failed", "1053 timeout" in errors[0], True)
check("ERROR says a person has to look", "要人到游戏机上看一眼" in errors[0], True)
check("recovery is INFO only", [lvl for lvl, m in logs.lines if "又在跑了" in m], ["INFO"])
check("the ERROR comes with the third failure, not before",
      [lvl for lvl, _ in logs.lines][:5], ["INFO", "INFO", "INFO", "ERROR", "INFO"])

print("[a look that raises counts as a failure]")
g = G.Guard(lambda: ("STOPPED", "AUTO"), lambda: "", lambda: False)
with Logs() as logs:
    for _ in range(3):
        g.failed("OSError()", looked=False)
check("third raise -> one ERROR", [lvl for lvl, _ in logs.lines].count("ERROR"), 1)
check("it says the relay could not look, not that the watchdog is down",
      "查不了" in logs.lines[-1][1] and "看门服务停了" not in logs.lines[-1][1], True)

print("[the marker counts only when written since the boot]")
with tempfile.TemporaryDirectory() as d:
    m = Path(d) / G.MARKER
    check("no marker", G.marker_this_boot(m, time.time() - 100), False)
    m.write_text("x")
    check("written after the boot", G.marker_this_boot(m, time.time() - 100), True)
    old = time.time() - 3600
    os.utime(m, (old, old))
    check("left from before the boot (crashed installer, earlier estop): ignored",
          G.marker_this_boot(m, time.time() - 100), False)

print("[one marker, the same on every side]")
fake = {}
for name in ("pywintypes", "win32service", "win32serviceutil"):
    fake[name] = sys.modules.get(name)
pywintypes = types.ModuleType("pywintypes")
pywintypes.error = type("error", (Exception,), {})
win32service = types.ModuleType("win32service")
win32service.SERVICE_STOPPED, win32service.SERVICE_RUNNING = 1, 4
win32serviceutil = types.ModuleType("win32serviceutil")
sys.modules.update(pywintypes=pywintypes, win32service=win32service, win32serviceutil=win32serviceutil)
import switch  # noqa: E402

check("switch.py's marker is the guard's (data folder, same name)",
      (switch.WATCHDOG_MARKER.name, str(switch.WATCHDOG_MARKER.parent)),
      (G.MARKER, r"C:\ProgramData\ark-relay"))
estop = (ROOT / "scripts" / "mac" / "estop.sh").read_text(encoding="utf-8")
stop_ps = estop[estop.index('PS_PKG_STOP="'):estop.index('PS_PKG_START="')]
start_ps = estop[estop.index('PS_PKG_START="'):]
marker_ps = r"'C:\\ProgramData\\ark-relay\\" + G.MARKER + "'"
check("estop writes it", f"Set-Content -Path {marker_ps}" in stop_ps, True)
check("estop writes it before sc stop",
      stop_ps.find("Set-Content -Path") < stop_ps.find("sc.exe stop ArkRelayWatchdog"), True)
check("estop --restore deletes it before sc start",
      0 <= start_ps.find(f"Remove-Item -Path {marker_ps}") < start_ps.find("sc.exe start ArkRelayWatchdog"),
      True)

print("[switch.py: marker before sc stop, deleted before sc start]")
with tempfile.TemporaryDirectory() as d:
    switch.WATCHDOG_MARKER = Path(d) / G.MARKER
    steps = []
    states = [4, 1]          # RUNNING once (the relay raced it), then STOPPED

    def run(*cmd):
        steps.append(("marker" if switch.WATCHDOG_MARKER.exists() else "no marker",) + tuple(map(str, cmd)))
        return 0
    real_run, real_sleep = switch.run, switch.time.sleep
    switch.run, switch.time.sleep = run, lambda s: None
    win32serviceutil.QueryServiceStatus = lambda name: (0, states.pop(0) if len(states) > 1 else states[0])
    try:
        switch.stop_watchdog()
        check("every sc stop with the marker already there",
              [s[0] for s in steps], ["marker", "marker"])
        check("stopped again after it came back", [s[1:3] for s in steps], [("sc.exe", "stop")] * 2)
        steps.clear()
        win32serviceutil.QueryServiceStatus = lambda name: (0, 4)
        check("start_watchdog -> 0", switch.start_watchdog(), 0)
        check("marker gone before sc start", steps[0][:3], ("no marker", "sc.exe", "start"))
    finally:
        switch.run, switch.time.sleep = real_run, real_sleep
for name, mod in fake.items():
    if mod is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = mod

src = (ROOT / "packaging" / "switch.py").read_text(encoding="utf-8")
check("no other starter in switch.py (each goes through start_watchdog)",
      re.findall(r'run\("sc\.exe", "start", WATCHDOG\)', src), ['run("sc.exe", "start", WATCHDOG)'])

print("[app_main starts the guard, packaged install only, stopping with the relay]")
app = (RELAY / "app_main.py").read_text(encoding="utf-8")
gate = app.index("if pkg_layout.app_root(HERE) is not None:")
body = app[gate:app.index("threading.Thread(target=_end_session_window")]
check("thread inside the packaged-install gate",
      "target=watchdog_guard.run, args=(host.stop_event, DATA)" in body, True)
check("logger under ark. (errwatch hooks ark)", G.log.name.startswith("ark."), True)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
