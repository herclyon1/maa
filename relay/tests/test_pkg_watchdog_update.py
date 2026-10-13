"""A relay deploy updates the watchdog service's file when it changed (no setup.exe).

2026-10-11: {app}\\watchdog\\ark_watchdog.py sits outside the version folders and only
the installer wrote it, so the preshutdown push (d0c0e12b) could ship only by running
setup.exe again.
The user's words, 10-11 16:37, kept verbatim: 「为啥要重新安装？你们现在搞一次更新这么麻烦了吗？」
Now deploy-pkg.sh step 5.3, after the relay is live and watched, sends the file when
its sha1 differs from the installed one and scripts/windows/pkg_deploy.py `watchdog`
does copy -> install -> restart -> verify. Checked here:
  - pkg_deploy.update_watchdog: unchanged = no service call at all; changed = exactly
    that order; disabled / not installed / a bad transfer = nothing changed; a failed
    step = the previous file back, the service started on it, exit 1;
  - WinService.stop / start against stand-in pywin32 modules: the stop marker is
    written before the stop and deleted before the start, and relay/watchdog_guard.py
    reads the stopped watchdog as stopped on purpose meanwhile (no race);
  - the Mac half (the `# >>> watchdog step` block of deploy-pkg.sh, run in bash with
    scp / pkg_py stood in): unchanged = no scp, no machine command, one line;
  - where the step sits: after the watch and the rollback exits, and deploy-relay.sh
    reports a failure only after COS and the smoke, exiting 14 at the very end.
"""
import contextlib
import hashlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(RELAY))

import watchdog_guard as G  # noqa: E402

spec = importlib.util.spec_from_file_location("pkg_deploy", ROOT / "scripts/windows/pkg_deploy.py")
pd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pd)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


class FakeService:
    """Records each call; `fail` names the step that returns a reason."""

    def __init__(self, app: Path, kind="AUTO", fail="", running=True):
        self.dst = app / "watchdog" / "ark_watchdog.py"
        self.kind, self.fail, self.is_running = kind, fail, running
        self.calls = []

    def start_type(self):
        self.calls.append("start_type")
        return self.kind

    def install(self, script):
        # What the file holds when install runs proves the copy came first.
        self.calls.append(("install", Path(script).read_text(encoding="utf-8")))
        return "exit 1" if self.fail == "install" else ""

    def stop(self):
        self.calls.append("stop")
        return "stuck" if self.fail == "stop" else ""

    def start(self):
        self.calls.append(("start", self.dst.read_text(encoding="utf-8")))
        if self.fail == "start":
            self.fail = ""          # the second start (on the previous file) works
            return "stopped again during its start"
        return ""

    def running(self):
        self.calls.append("running")
        return self.is_running


def setup(td: str, installed="OLD", sent="NEW"):
    app = Path(td) / "ArkRelay"
    (app / "watchdog").mkdir(parents=True)
    (app / "watchdog" / "ark_watchdog.py").write_text(installed, encoding="utf-8")
    staged = Path(td) / "ark-watchdog-new.py"
    staged.write_text(sent, encoding="utf-8")
    return app, staged


def run(app, want, staged, svc):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = pd.update_watchdog(app, want, staged, svc)
    return rc, buf.getvalue().splitlines()


print("[update_watchdog: the same file = nothing at all]")
with tempfile.TemporaryDirectory() as td:
    app, staged = setup(td, "SAME", "SAME")
    svc = FakeService(app)
    rc, out = run(app, sha("SAME"), staged, svc)
    check("exit 0", rc, 0)
    check("no service call", svc.calls, [])
    check("says unchanged", out, ["WATCHDOG=unchanged"])

print("[update_watchdog: changed = copy, install, restart (stop, start), verify]")
with tempfile.TemporaryDirectory() as td:
    app, staged = setup(td)
    svc = FakeService(app)
    rc, out = run(app, sha("NEW"), staged, svc)
    check("exit 0", rc, 0)
    check("calls in order, install and start already on the new file", svc.calls,
          ["start_type", ("install", "NEW"), "stop", ("start", "NEW"), "running"])
    check("steps printed in order", [x for x in out if x.startswith("WATCHDOG")],
          ["WATCHDOG_STEP copy", "WATCHDOG_STEP install", "WATCHDOG_STEP stop",
           "WATCHDOG_STEP start", "WATCHDOG_STEP verify", "WATCHDOG=updated"])
    check("installed file is the new one", (app / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), "NEW")
    check("no .new left behind", (app / "watchdog" / "ark_watchdog.py.new").exists(), False)

print("[update_watchdog: nothing changed when it must not]")
with tempfile.TemporaryDirectory() as td:
    app, staged = setup(td)
    svc = FakeService(app, kind="DISABLED")
    rc, out = run(app, sha("NEW"), staged, svc)
    check("disabled (a revert): exit 0, said so", (rc, out), (0, ["WATCHDOG=disabled"]))
    check("disabled: not installed (that would switch it back to automatic), not started",
          svc.calls, ["start_type"])
    check("disabled: file untouched", (app / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), "OLD")
with tempfile.TemporaryDirectory() as td:
    app, staged = setup(td)
    svc = FakeService(app, kind="MISSING")
    rc, out = run(app, sha("NEW"), staged, svc)
    check("not installed: exit 1, loud", (rc, out[-1].startswith("WATCHDOG_FAIL")), (1, True))
    check("not installed: file untouched", (app / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), "OLD")
with tempfile.TemporaryDirectory() as td:
    app, staged = setup(td, sent="NEW, cut sho")
    svc = FakeService(app)
    rc, out = run(app, sha("NEW, cut short"), staged, svc)
    check("file sent does not match its sha1: exit 1, no service call", (rc, svc.calls), (1, []))
    check("bad transfer: file untouched", (app / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), "OLD")

print("[update_watchdog: a failed step puts the previous file back and starts it]")
for step, want_calls in (
        ("install", ["start_type", ("install", "NEW"), "stop", ("start", "OLD")]),
        ("stop", ["start_type", ("install", "NEW"), "stop", "stop", ("start", "OLD")]),
        ("start", ["start_type", ("install", "NEW"), "stop", ("start", "NEW"), "stop", ("start", "OLD")])):
    with tempfile.TemporaryDirectory() as td:
        app, staged = setup(td)
        svc = FakeService(app, fail=step)
        rc, out = run(app, sha("NEW"), staged, svc)
        check(f"{step} fails: exit 1", rc, 1)
        check(f"{step} fails: says which step", any(x.startswith(f"WATCHDOG_FAIL {step}:") for x in out), True)
        check(f"{step} fails: calls", svc.calls, want_calls)
        check(f"{step} fails: previous file back", (app / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), "OLD")
        check(f"{step} fails: says it runs on the previous file", out[-1], "WATCHDOG_RESTORED running on the previous file")
        check(f"{step} fails: never says updated", "WATCHDOG=updated" in out, False)
with tempfile.TemporaryDirectory() as td:
    app, staged = setup(td)
    svc = FakeService(app, running=False)
    rc, out = run(app, sha("NEW"), staged, svc)
    check("not RUNNING at the verify: exit 1, verify named", (rc, any(x.startswith("WATCHDOG_FAIL verify:") for x in out)), (1, True))

print("[WinService.stop / start: the stop marker, and the relay's guard meanwhile]")


class PyWinError(Exception):
    def __init__(self, winerror, strerror=""):
        super().__init__(winerror, strerror)
        self.winerror, self.strerror = winerror, strerror


RUNNING, STOPPED = 4, 1
service = {"state": RUNNING}
events = []


def _status(name):
    return (0x10, service["state"], 0, 0, 0, 0, 0)


def _stop(name):
    events.append(("StopService", pd.WATCHDOG_MARKER.exists()))
    service["state"] = STOPPED


def _start(name):
    events.append(("StartService", pd.WATCHDOG_MARKER.exists()))
    service["state"] = RUNNING


fake = {
    "pywintypes": types.SimpleNamespace(error=PyWinError),
    "win32service": types.SimpleNamespace(SERVICE_RUNNING=RUNNING, SERVICE_STOPPED=STOPPED),
    "win32serviceutil": types.SimpleNamespace(QueryServiceStatus=_status, StopService=_stop,
                                              StartService=_start),
}
saved = {k: sys.modules.get(k) for k in fake}
real_sleep, real_marker, real_steady = pd.time.sleep, pd.WATCHDOG_MARKER, pd.WATCHDOG_STEADY_S
clock = [1000.0]
real_mono = pd.time.monotonic
with tempfile.TemporaryDirectory() as td:
    try:
        sys.modules.update(fake)
        pd.WATCHDOG_MARKER = Path(td) / "watchdog-stopped.txt"

        def fake_sleep(s):
            clock[0] += s

        pd.time.sleep = fake_sleep
        pd.time.monotonic = lambda: clock[0]
        ws = pd.WinService(Path(td))
        check("stop returns ''", ws.stop(), "")
        check("marker written before StopService", events, [("StopService", True)])
        # The relay's guard looking now: stopped, automatic, marker from this boot.
        guard = G.Guard(lambda: ("STOPPED", "AUTO"), lambda: events.append("GUARD_START") or "",
                        lambda: G.marker_this_boot(pd.WATCHDOG_MARKER, time.time() - 3600))
        check("the guard reads it as stopped on purpose", guard.tick(), "stopped on purpose")
        check("the guard did not start it", "GUARD_START" in events, False)
        check("start returns '' once RUNNING steady", ws.start(), "")
        check("marker deleted before StartService", events[-1], ("StartService", False))
        check("no marker left (the guard covers any later stop)", pd.WATCHDOG_MARKER.exists(), False)
        check("verify", ws.running(), True)
    finally:
        pd.time.sleep, pd.time.monotonic = real_sleep, real_mono
        pd.WATCHDOG_MARKER = real_marker
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

print("[deploy-pkg.sh step 5.3, run in bash with scp and pkg_py stood in]")
# deploy-pkg.sh runs on the Mac only. Its block run in bash on the Windows CI job
# recorded no call at all (run 38360295330: IndexError on calls[0]) and would say
# nothing about the Mac anyway: this part runs on the Mac (the deploy gate), the
# Windows job runs the rest of this file (pkg_deploy.py, which runs on the machine).
ON_MAC_LIKE = sys.platform != "win32"
pkg_sh = (ROOT / "scripts/mac/lib/deploy-pkg.sh").read_text(encoding="utf-8")
block = pkg_sh[pkg_sh.index("# >>> watchdog step"):pkg_sh.index("# <<< watchdog step")]
sha_fn = next(x for x in pkg_sh.splitlines() if x.startswith("pkg_sha1() "))
src = ROOT / "packaging/watchdog/ark_watchdog.py"
src_sha = hashlib.sha1(src.read_bytes()).hexdigest()


def bash_step(installed_sha: str, machine_out: str, scp_rc: int = 0):
    with tempfile.TemporaryDirectory() as td:
        calls = Path(td) / "calls"
        script = f"""
set -euo pipefail
HERE={str(RELAY)!r}
SSH_OPTS=(-o ConnectTimeout=15)
USER_AT=Administrator@host
APP_WIN='C:\\Program Files\\ArkRelay'
PKG_DEPLOY='C:\\Users\\Administrator\\ark-pkg-deploy.py'
WD_SRC="$HERE/../packaging/watchdog/ark_watchdog.py"
WD_STAGED='C:\\Users\\Administrator\\ark-watchdog-new.py'
{sha_fn}
scp() {{ echo "scp $*" >>{str(calls)!r}; return {scp_rc}; }}
pkg_py() {{ echo "pkg_py $*" >>{str(calls)!r}; printf '%s\\n' "$MACHINE_OUT"; }}
{block}
pkg_watchdog_step "$1"
echo "FAIL_WHY=$WATCHDOG_FAIL_WHY"
"""
        r = subprocess.run(["bash", "-c", script, "step", installed_sha], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           env={**os.environ, "MACHINE_OUT": machine_out, "LC_ALL": "en_US.UTF-8"})
        if r.stderr.strip():
            print("    bash stderr:", r.stderr.strip()[-300:])
        got = calls.read_text().splitlines() if calls.exists() else []
        return r.returncode, r.stdout.splitlines(), got


if ON_MAC_LIKE:
    rc, out, calls = bash_step(src_sha, "WATCHDOG=updated")
    check("unchanged: bash exit 0", rc, 0)
    check("unchanged: no scp, no machine command", calls, [])
    check("unchanged: one line, then no failure", (len(out), out[-1]), (2, "FAIL_WHY="))
    rc, out, calls = bash_step("0" * 40, "WATCHDOG_STEP copy\nWATCHDOG_STEP install\nWATCHDOG_STEP stop\n"
                                         "WATCHDOG_STEP start\nWATCHDOG_STEP verify\nWATCHDOG=updated")
    check("changed: scp the file, then pkg_deploy.py watchdog with its sha1 and the staged path",
          [c.split()[0] for c in calls], ["scp", "pkg_py"])
    check("changed: the scp sends packaging/watchdog/ark_watchdog.py",
          "packaging/watchdog/ark_watchdog.py Administrator@host:C:/Users/Administrator/ark-watchdog-new.py" in calls[0], True)
    check("changed: machine command", calls[1],
          f"pkg_py C:\\Users\\Administrator\\ark-pkg-deploy.py watchdog C:\\Program Files\\ArkRelay {src_sha} "
          "C:\\Users\\Administrator\\ark-watchdog-new.py")
    check("changed: no failure", out[-1], "FAIL_WHY=")
    check("changed: steps shown", sum(x.strip().startswith("WATCHDOG_STEP") for x in out), 5)
    rc, out, calls = bash_step("0" * 40, "WATCHDOG_STEP copy\nWATCHDOG_FAIL start: stopped again during its start\n"
                                         "WATCHDOG_RESTORED running on the previous file")
    check("machine failure: bash still exit 0 (the relay is live; deploy-relay.sh reports it)", rc, 0)
    check("machine failure: WATCHDOG_FAIL_WHY names it and the restore",
          ("stopped again during its start" in out[-1], "running on the previous file" in out[-1]), (True, True))
    rc, out, calls = bash_step("0" * 40, "")
    check("no answer from the machine: a failure too", out[-1].startswith("FAIL_WHY=") and len(out[-1]) > len("FAIL_WHY="), True)
    rc, out, calls = bash_step("0" * 40, "WATCHDOG=updated", scp_rc=1)
    check("scp failed: no machine command, a failure", ([c.split()[0] for c in calls], len(out[-1]) > len("FAIL_WHY=")),
          (["scp"], True))
    rc, out, calls = bash_step("", "WATCHDOG=updated")
    check("no WATCHDOG_SHA from info (old machine script): treated as changed", [c.split()[0] for c in calls],
          ["scp", "pkg_py"])
else:
    print('  (skipped on Windows: see above)')

print("[where the step sits]")
p = {k: pkg_sh.find(k) for k in ("WD_SHA=$(sed -n 's/^WATCHDOG_SHA=//p' <<<\"$INFO\")", "grep -q '^WATCH_OK' \"$WATCH_OUT\"",
                                 "\n  exit 13\nfi", "\npkg_watchdog_step \"$WD_SHA\"\n", "\nCHANGED=\"\"\n")}
check("deploy-pkg.sh: every anchor there", [k for k, v in p.items() if v < 0], [])
order = list(p.values())
check("deploy-pkg.sh: sha read from info, after the watch and the rollback exits, before the hand-over",
      order == sorted(order), True)
check("deploy-pkg.sh: the staged file is deleted on exit", "del $WD_STAGED" in pkg_sh, True)
sh = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
# The smoke runs before COS since 2026-10-13 (a failed smoke takes the way back, so it
# must come before the version is published).
q = {k: sh.find(k) for k in ('\nWATCHDOG_FAIL_WHY=""\n', 'lib/deploy-pkg.sh"', "grep -q '^SMOKE_OK$'", 'publish-cos.py"',
                             'if [ -n "$WATCHDOG_FAIL_WHY" ]; then\n  echo "❌❌ 中继已上线', 'echo "✅ 部署完成',
                             "push -q origin HEAD:refs/heads/main", "ledger-gap.py",
                             'if [ -n "$WATCHDOG_FAIL_WHY" ]; then\n  echo "❌❌ 再说一遍', "\n  exit 14\nfi")}
check("deploy-relay.sh: every anchor there", [k for k, v in q.items() if v < 0], [])
order = list(q.values())
check("deploy-relay.sh: set for both layouts first; reported after the smoke and COS; exit 14 last",
      order == sorted(order), True)
check("deploy-relay.sh: exit 14 is the last command", sh.rstrip().endswith("exit 14\nfi"), True)

if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
