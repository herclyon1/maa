"""The last 「停止前」 state at a Windows shutdown: the watchdog service sends it when the relay could not.

2026-10-11 14:25 (machine time): `shutdown /r /t 5` (/t above 0 implies /f, forced).
relay.log had 「14:25:10 ark.service 收到停止通知（Windows 关机）」 and nothing after it
until the next boot; the boot's machine check #11 failed and pushed to the group. The
packaged relay is a program in the user's session, and those end before any service
hears of a shutdown; the watchdog service (packaging/watchdog/ark_watchdog.py) is told
afterwards through SERVICE_CONTROL_PRESHUTDOWN and runs `launch.py stop-push`
(relay/app_main.py stop_push), which sends the state through phone.send_state - the
same function and the same log line as the relay's own push.

Checked here, on any OS (pywin32 is faked):
  a. #11 on a relay.log like 14:25's: with the watchdog's line it passes, without it it
     still fails; the watchdog's line alone (no stop notice) passes too; the line comes
     from running the real app_main.stop_push into that relay.log;
  b. stop_push skips when the relay's own push left its marker, sends exactly once
     otherwise, gives up after its time; the watchdog runs it once per shutdown, after a
     relay still running had a few seconds to finish; the marker is written by
     send_state and cleared when the phone channel comes up;
  c. the watchdog accepts PRESHUTDOWN, its handler only flags and returns, and it does
     not start the relay again once Windows is going down.
"""
import os
import re
import sys
import threading
import types
from datetime import datetime
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(RELAY))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "packaging" / "watchdog"))
from _tmp import tmpdir  # noqa: E402

DATA = tmpdir()
(DATA / "state").mkdir()
os.environ["ARK_HOME"] = str(DATA)
for _k in ("ARK_LOG_FILE", "ARK_STATE_DIR", "ARK_PHONE_TOPIC", "ARK_PHONE_PIN"):
    os.environ.pop(_k, None)
LOG = DATA / "relay.log"

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


# ---------------------------------------------------------------- pywin32, faked

def _module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class _Event:
    def __init__(self):
        self.set = False


def _wait(evt, ms):
    return 0 if evt.set else 258


win32service = _module(
    "win32service", SERVICE_ACCEPT_STOP=0x1, SERVICE_ACCEPT_PAUSE_CONTINUE=0x2, SERVICE_ACCEPT_SHUTDOWN=0x4,
    SERVICE_ACCEPT_PRESHUTDOWN=0x100, SERVICE_CONTROL_SHUTDOWN=0x5, SERVICE_CONTROL_PRESHUTDOWN=0xF,
    SERVICE_STOP_PENDING=3, SERVICE_AUTO_START=2)


class ServiceFramework:
    """pywin32 311's win32serviceutil.ServiceFramework, the parts the watchdog relies on."""

    def __init__(self, args):
        self.statuses = []

    def GetAcceptedControls(self):  # noqa: N802
        accepted = 0
        if hasattr(self, "SvcStop"):
            accepted |= win32service.SERVICE_ACCEPT_STOP
        if hasattr(self, "SvcPause") and hasattr(self, "SvcContinue"):
            accepted |= win32service.SERVICE_ACCEPT_PAUSE_CONTINUE
        if hasattr(self, "SvcShutdown"):
            accepted |= win32service.SERVICE_ACCEPT_SHUTDOWN
        return accepted

    def SvcOther(self, control):  # noqa: N802
        return None

    def SvcOtherEx(self, control, event_type, data):  # noqa: N802
        return self.SvcOther(control)

    def ReportServiceStatus(self, status, waitHint=5000, win32ExitCode=0, svcExitCode=0):  # noqa: N802
        self.statuses.append((status, waitHint))


class _PyError(Exception):
    pass


_module("pywintypes", error=_PyError)
_module("servicemanager", LogMsg=lambda *a: None, EVENTLOG_INFORMATION_TYPE=4, PYS_SERVICE_STARTED=1)
_module("win32api", GetSystemMetrics=lambda i: 0, CloseHandle=lambda h: None)
_module("win32event", CreateEvent=lambda *a: _Event(), SetEvent=lambda e: setattr(e, "set", True),
        WaitForSingleObject=_wait, WAIT_TIMEOUT=258)
_module("win32serviceutil", ServiceFramework=ServiceFramework)
_module("win32ts")

import ark_watchdog as W  # noqa: E402
import app_main  # noqa: E402
from ark_relay.features.selfcheck import machinecheck as mc  # noqa: E402
from ark_relay.features.phone import phone  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.selfcheck.machinechecks import system as sysmc  # noqa: E402

# ---------------------------------------------------------------- relay.log and #11

NOW = datetime(2026, 10, 11, 14, 27, tzinfo=SERVER_TZ)


def logline(stamp, msg, level="INFO", name="ark.service"):
    return f"{stamp} {level:<7} {name}  {msg}"


START = "服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）"
MARK = "中继代码版本 v20261011042937"
BEFORE = [
    logline("10-11 13:40:02", START), logline("10-11 13:40:02", MARK),
    logline("10-11 13:40:31", "📱 已上报状态到手机（开机；今天 ntfy 已用 30 条）"),
    logline("10-11 14:25:10", "收到停止通知（Windows 关机）"),
]
BOOT_NOW = [logline("10-11 14:26:04", START), logline("10-11 14:26:04", MARK)]
DOG = [logline("10-11 14:25:31", app_main.STOP_PUSH_START, name="ark.app.stop_push"),
       logline("10-11 14:25:33", "📱 已上报状态到手机（停止前；今天 ntfy 已用 31 条）", name="ark.app.stop_push")]


class N:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body, alert))
        return []

    def alert_log(self):
        return None


def judge11(lines):
    d = tmpdir()
    f = d / "relay.log"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sysmc._SESSION.clear()
    got = dict(mc.judge(d, "boot", {"log_file": str(f)}, notifier=N(), now=NOW))
    return got.get("#11")


print("[a. 14:25: stop notice, the relay's push cut off, the watchdog's push after it -> #11 passes]")
r = judge11(BEFORE + DOG + BOOT_NOW)
check("#11 passed", r and r.status, mc.PASS)
check("the evidence names the watchdog's line", "看门服务代发" in (r.evidence if r else ""), True)

print("[a. the same log without the watchdog's line -> #11 still fails]")
r = judge11(BEFORE + BOOT_NOW)
check("#11 failed", r and r.status, mc.FAIL)
check("as before: the relay stopped first", "中继先停下了" in (r.evidence if r else ""), True)

print("[a. the watchdog tried and did not get it out -> fails with its reason]")
r = judge11(BEFORE + [DOG[0], logline("10-11 14:25:41", "状态没能上报到手机（停止前）：COS 403；手机上留着上一份状态",
                                     level="WARNING", name="ark.app.stop_push")] + BOOT_NOW)
check("#11 failed", r and r.status, mc.FAIL)
check("with the reason", "COS 403" in (r.evidence if r else ""), True)

print("[a. no stop notice (the relay ended before logging it), the watchdog's push there -> passes]")
r = judge11(BEFORE[:3] + DOG + BOOT_NOW)
check("#11 passed", r and r.status, mc.PASS)
r = judge11(BEFORE[:3] + BOOT_NOW)
check("without it: still the old failure", r and r.status, mc.FAIL)

print("[a+b. the real stop_push writes the line #11 reads into relay.log]")
LOG.write_text("\n".join(BEFORE) + "\n", encoding="utf-8")
published = []


class FakeBox:
    """phone.Mailbox as stop_push builds it; publish succeeds unless told otherwise."""
    ok = True

    def __init__(self, topic, pin, state_dir, cos=None):
        self.enabled, self.last_error, self.last_route = True, "", "腾讯云"
        self.quota = phone.Quota(state_dir)

    def publish(self, body):
        published.append(body)
        if not FakeBox.ok:
            self.last_error = "COS 403"
        return FakeBox.ok


phone.Mailbox = FakeBox
phone.state_payload = lambda cfg, state_dir: {"at": 1}
code = app_main.stop_push()
check("sent: exit code 0", code, 0)
check("one publish", len(published), 1)
text = LOG.read_text(encoding="utf-8")
check("the start line is in relay.log", app_main.STOP_PUSH_START in text, True)
check("the push line under ark.stop_push",
      bool(re.search(r"INFO\s+ark\.app\.stop_push\s+📱 已上报状态到手机（停止前；", text)), True)
check("send_state left the marker", phone.stop_pushed(DATA / "state"), True)
r = judge11(text.splitlines() + BOOT_NOW)
check("#11 on that relay.log passes", r and r.status, mc.PASS)

print("[b. the relay's own push got out (marker) -> stop_push sends nothing]")
n0 = len(published)
check("skipped: exit code 2", app_main.stop_push(), 2)
check("no publish", len(published), n0)
check("says so in relay.log", app_main.STOP_PUSH_SKIP in LOG.read_text(encoding="utf-8"), True)

print("[b. the phone channel coming up clears the marker; a failed push leaves none]")
phone.clear_stop_pushed(DATA / "state")
check("cleared", phone.stop_pushed(DATA / "state"), False)
FakeBox.ok = False
check("not sent: exit code 1", app_main.stop_push(), 1)
check("no marker after a failed push", phone.stop_pushed(DATA / "state"), False)
check("the failure line #11 reads",
      "状态没能上报到手机（停止前）：COS 403" in LOG.read_text(encoding="utf-8"), True)
FakeBox.ok = True

print("[b. a send that hangs: stop_push gives up after its time and says so]")
gate = threading.Event()
real_send = phone.send_state
phone.send_state = lambda *a, **k: (gate.wait(5), (True, None, ""))[1]
check("not sent: exit code 1", app_main.stop_push(wait_s=0.2), 1)
gate.set()
phone.send_state = real_send
check("the failure line names the wait",
      "状态没能上报到手机（停止前）：看门服务等了 0 秒还没发完" in LOG.read_text(encoding="utf-8"), True)

print("[b. boot_stages clears the marker when the phone channel comes up]")
src = (RELAY / "boot_stages.py").read_text(encoding="utf-8")
body = src[src.index("def _start_phone_channel"):src.index("def publish_state")]
check("clear_stop_pushed(cfg.state_dir) in _start_phone_channel", "clear_stop_pushed(cfg.state_dir)" in body, True)
check("publish_state goes through phone.send_state", "send_state(box, cfg, why, log)" in src, True)

print("[b. the watchdog runs stop-push once per shutdown, after a running relay had its seconds]")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


for label, alive, want_waited in [("relay gone already", [False], 0.0),
                                  ("relay exits after 1 s", [True, True, False], 1.0),
                                  ("relay never exits: waits ALIVE_WAIT_S, then still once", [True], W.ALIVE_WAIT_S)]:
    clock, pushes = Clock(), []
    states = list(alive)
    got = W.last_push(relay_running=lambda: states.pop(0) if len(states) > 1 else states[0],
                      push=lambda timeout: pushes.append(timeout) or "送到了", sleep=clock.sleep, clock=clock)
    check(f"{label}: one push", len(pushes), 1)
    check(f"{label}: with PUSH_TIMEOUT_S", pushes[0], W.PUSH_TIMEOUT_S)
    check(f"{label}: waited", clock.t, want_waited)
    check(f"{label}: its result logged", got, "送到了")

print("[b. the command the watchdog runs is one app_main knows, through launch.py]")
dog_src = (ROOT / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8")
check("launch.py stop-push", '"launch.py"), "stop-push"]' in dog_src, True)
check("app_main dispatches stop-push", '"stop-push": _stop_push_exit' in (RELAY / "app_main.py").read_text(encoding="utf-8"),
      True)
check("the same session-ending file name", W.SESSION_ENDING.name, app_main.SESSION_ENDING)
check("the send fits in the command's time", app_main.STOP_PUSH_WAIT_S < W.PUSH_TIMEOUT_S, True)
check("wait + command fit in the preshutdown time", W.ALIVE_WAIT_S + W.PUSH_TIMEOUT_S < W.PRESHUTDOWN_MS / 1000, True)

print("[c. the watchdog accepts PRESHUTDOWN (and still STOP and SHUTDOWN)]")
svc = W.WatchdogService(["ArkRelayWatchdog"])
acc = svc.GetAcceptedControls()
check("SERVICE_ACCEPT_PRESHUTDOWN", bool(acc & win32service.SERVICE_ACCEPT_PRESHUTDOWN), True)
check("SERVICE_ACCEPT_STOP", bool(acc & win32service.SERVICE_ACCEPT_STOP), True)
check("SERVICE_ACCEPT_SHUTDOWN", bool(acc & win32service.SERVICE_ACCEPT_SHUTDOWN), True)

print("[c. the PRESHUTDOWN handler flags, reports STOP_PENDING, sets the stop event and returns]")
calls = []
W.last_push = lambda **k: calls.append(1) or "送到了"
W._log = lambda line: calls.append(line)
check("handler returns NO_ERROR (None)", svc.SvcOtherEx(win32service.SERVICE_CONTROL_PRESHUTDOWN, 0, None), None)
check("flag set", svc.watch.shutting_down, True)
check("stop event set", svc.stop_event.set, True)
check("STOP_PENDING with the preshutdown time as wait hint",
      svc.statuses[-1], (win32service.SERVICE_STOP_PENDING, W.PRESHUTDOWN_MS))
check("no push inside the handler", calls.count(1), 0)
svc.SvcDoRun()
check("SvcDoRun pushed once after the loop", calls.count(1), 1)
check("and logged it", any(isinstance(c, str) and c.startswith("Windows 关机，停止前那份状态：送到了") for c in calls), True)

print("[c. a plain stop (sc stop, the installer) pushes nothing]")
svc2 = W.WatchdogService(["ArkRelayWatchdog"])
calls.clear()
svc2.SvcStop()
svc2.SvcDoRun()
check("no push", calls.count(1), 0)
check("other controls still go to pywin32's SvcOtherEx", svc2.SvcOtherEx(0x80, 0, None), None)

print("[c. once Windows is going down the watchdog does not start the relay again]")
started = []
W.main_running = lambda: False
W.someone_logged_on = lambda: True
W.start_main = lambda: started.append(1) or True
w = W.Watch(0.0)
w.tick(30.0)
check("relay gone, nothing going down: started", len(started), 1)
w = W.Watch(0.0)
w.shutting_down = True
w.tick(30.0)
check("after PRESHUTDOWN: not started", len(started), 1)
W.SESSION_ENDING.write_text("x", encoding="utf-8")
w = W.Watch(0.0)
w.tick(30.0)
check("the relay's session is ending (its marker): not started", len(started), 1)
os.utime(W.SESSION_ENDING, (0, 0))
w.tick(60.0)
check("a marker older than ENDING_HOLD_S no longer holds it", len(started), 2)
check("app_main deletes the marker at start and writes it on WM_ENDSESSION",
      ("(DATA / SESSION_ENDING).unlink" in (RELAY / "app_main.py").read_text(encoding="utf-8"),
       "_mark_session_ending()" in (RELAY / "app_main.py").read_text(encoding="utf-8")), (True, True))

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
