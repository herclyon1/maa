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

print("[the real start counts only a watchdog that comes up and stays (review round 10 #30)]")
# Only the two Windows calls are stubbed: StartService and QueryServiceStatus.
# 2 = START_PENDING, 1 = STOPPED, 4 = RUNNING (winsvc.h).


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def wait(self, seconds):
        self.t += seconds
        return False


def fake_service(states, start_error=None):
    """StartService records the call (raising start_error if given); each status query
    returns the next state, the last one from then on."""
    calls = {"start": 0}
    states = list(states)

    def start_service(name):
        calls["start"] += 1
        if start_error is not None:
            exc = pywintypes.error()
            exc.winerror, exc.strerror = start_error, {1056: "already running"}.get(start_error, "disabled")
            raise exc
    win32serviceutil.StartService = start_service
    win32serviceutil.QueryServiceStatus = lambda name: (0, states.pop(0) if len(states) > 1 else states[0])
    return calls


def real_start(states, start_error=None):
    clock = Clock()
    calls = fake_service(states, start_error)
    return G._start(clock.wait, clock.now), calls["start"], clock.t


got, starts, waited = real_start([2, 2, 1])
check("START_PENDING then STOPPED (cloud run 38095391114) is a failure, not a start",
      (got, starts), ("开到一半自己停了", 1))
got, starts, waited = real_start([2, 4])
check("RUNNING and still RUNNING STEADY_S later: started", got, "")
check("... after waiting the steady time, not at the first RUNNING", waited >= G.STEADY_S, True)
check("RUNNING, then STOPPED within the steady time: a failure",
      real_start([2, 4, 4, 1])[0], "刚跑起来就又停了")
check("never leaves START_PENDING: a failure at START_WAIT_S",
      real_start([2])[:1] + (real_start([2])[2] >= G.START_WAIT_S,),
      (f"开了 {G.START_WAIT_S} 秒还没跑起来", True))
check("1056 (already starting) is watched too, and ends stopped: a failure",
      real_start([2, 1], start_error=1056)[0], "开到一半自己停了")
check("another start error is the failure itself",
      real_start([1], start_error=1058)[0], "1058 disabled")
fake_service([2])
check("relay stopping while it waits: neither success nor failure",
      G._start(lambda s: True, Clock().now), None)

print("[the guard over the real start: a watchdog that starts then stops reaches the ERROR]")


def guard_over_real_start(looks, service_each_start):
    """looks: what each look finds; service_each_start: the states a start then goes through."""
    looks, clock = list(looks), Clock()

    def start():
        fake_service(service_each_start)
        return G._start(clock.wait, clock.now)
    return G.Guard(lambda: looks.pop(0) if len(looks) > 1 else looks[0], start, lambda: False)


g = guard_over_real_start([("STOPPED", "AUTO")], [2, 2, 1])
with Logs() as logs:
    got = [g.tick() for _ in range(3)]
check("every start stops during START_PENDING: three failures", got, ["start failed"] * 3)
errors = [m for lvl, m in logs.lines if lvl == "ERROR"]
check("one ERROR at the third, with the reason", len(errors) == 1 and "开到一半自己停了" in errors[0], True)

g = guard_over_real_start([("STOPPED", "AUTO")], [2, 4])
with Logs() as logs:
    got = [g.tick() for _ in range(4)]
check("comes up and stays, but is stopped again at every look: counted from the second",
      got, ["started", "started again", "started again", "started again"])
check("... one ERROR, at the fourth look", [lvl for lvl, _ in logs.lines].count("ERROR"), 1)

g = guard_over_real_start([("STOPPED", "AUTO"), ("RUNNING", "AUTO"), ("STOPPED", "AUTO")], [2, 4])
with Logs() as logs:
    got = [g.tick() for _ in range(3)]
check("a start that is still running at the next look: no failure, a later stop starts afresh",
      (got, g.fails), (["started", "running", "started"], 0))

looks = [("STOPPED", "AUTO"), ("STOPPED", "AUTO"), ("STOPPED", "AUTO")]
marks = [False, True, False]
g = guard_over_real_start(looks, [2, 4])
g.marker_this_boot = lambda: marks.pop(0)
with Logs() as logs:
    got = [g.tick() for _ in range(3)]
check("a look in between (stopped on purpose) means the next start is not 'stopped again'",
      (got, g.fails), (["started", "stopped on purpose", "started"], 0))
check("the group ERROR does not claim it is down after a start that worked: it says found stopped",
      "留不住" in G.ALERT_GAVE_UP and "发现它停了" in G.ALERT_GAVE_UP, True)

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
