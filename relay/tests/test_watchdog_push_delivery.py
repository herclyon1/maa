"""The watchdog's own group alarm counts as sent only when the group bot took it.

s26 audit, finding 1 (2026-10-13): packaging/watchdog/ark_watchdog.py `push` sent once,
caught only OSError and logged 「进群」 on any HTTP 200, and every caller marked its
alarm as sent whatever happened. So:
  a. a WeCom refusal inside HTTP 200 (errcode != 0, the way relay/ark_relay/core/notify.py
     reads it) or a transport error right after boot (relay.log 10-12 08:45:26
     WinError 10051, the network not up yet) lost the one 「中继停了」 alarm for good;
  b. http.client.HTTPException is not an OSError: it escaped push(), the tick logged
     「检查出错」, the flag stayed False and the alarm was re-sent every 30 s with no end.
Now push() returns whether the bot answered errcode 0, an undelivered alarm is tried
again on the next looks, and after PUSH_TRIES failed pushes in one stretch the
watchdog gives up and says so in watchdog.log.

Runs on any OS: pywin32 is faked, urlopen is replaced at the HTTP layer.
"""
import http.client
import io
import json
import os
import sys
import types
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "packaging" / "watchdog"))
from _tmp import tmpdir  # noqa: E402

DATA = tmpdir()
os.environ["ARK_HOME"] = str(DATA)
(DATA / ".env").write_text("WECOM_BOT_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test\n",
                           encoding="utf-8")

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


def _module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class _PyError(Exception):
    pass


_module("pywintypes", error=_PyError)
_module("servicemanager", LogMsg=lambda *a: None, EVENTLOG_INFORMATION_TYPE=4, PYS_SERVICE_STARTED=1)
_module("win32api", GetSystemMetrics=lambda i: 0, CloseHandle=lambda h: None)
_module("win32event", CreateEvent=lambda *a: None, SetEvent=lambda e: None, WaitForSingleObject=lambda *a: 0,
        WAIT_TIMEOUT=258)
_module("win32service", SERVICE_ACCEPT_PRESHUTDOWN=0x100, SERVICE_CONTROL_PRESHUTDOWN=0xF,
        SERVICE_STOP_PENDING=3, SERVICE_AUTO_START=2)
_module("win32serviceutil", ServiceFramework=object)
_module("win32ts")

import ark_watchdog as W  # noqa: E402


class _Resp:
    def __init__(self, status, obj):
        self.status = status
        self._raw = io.BytesIO(json.dumps(obj).encode("utf-8"))

    def read(self):
        return self._raw.read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


answers = []      # what each urlopen call does, in order: a reply or an exception
posts = []


def fake_urlopen(req, timeout=None):
    posts.append(json.loads(req.data.decode("utf-8"))["text"]["content"])
    a = answers.pop(0) if answers else _Resp(200, {"errcode": 0, "errmsg": "ok"})
    if isinstance(a, BaseException):
        raise a
    return a


def refused():
    return _Resp(200, {"errcode": 45009, "errmsg": "api freq out of limit"})


def dropped():
    # BadStatusLine is an HTTPException and not an OSError (RemoteDisconnected is both).
    return http.client.BadStatusLine("")


W.urllib.request.urlopen = fake_urlopen
logged = []
W._log = logged.append
running = {"on": False}
logon = {"on": True}
W.main_running = lambda: running["on"]
W.someone_logged_on = lambda: logon["on"]
W.start_main = lambda: True
# No start record in these stretches: the alarm says so (REASON_NONE).
W.START_ERROR = DATA / "no-start-error.txt"
CAP = getattr(W, "PUSH_TRIES", 3)


def new_watch():
    try:
        return W.Watch()
    except TypeError:               # the old signature, Watch(now)
        return W.Watch(0.0)


def deliver(text):
    """push() as a bool; the old one returned None and let HTTPException out."""
    try:
        return W.push(text)
    except http.client.HTTPException as exc:
        return f"raised {type(exc).__name__}"


print("[push(): delivered only on HTTP 200 with errcode 0]")
answers[:] = [_Resp(200, {"errcode": 0, "errmsg": "ok"})]
check("errcode 0: delivered", deliver("x"), True)
answers[:] = [refused()]
check("HTTP 200 with errcode 45009: not delivered", deliver("x"), False)
check("... and the log says it did not get through", logged[-1].startswith("进群失败"), True)
answers[:] = [dropped()]
check("http.client.HTTPException is caught: not delivered", deliver("x"), False)
answers[:] = [OSError(10051, "A socket operation was attempted to an unreachable network")]
check("network not up (WinError 10051): not delivered", deliver("x"), False)
answers[:] = [_Resp(200, "not a dict")]
check("an answer that is not WeCom's: not delivered", deliver("x"), False)

print("\n[「中继停了」 refused once: tried again at the next look, flag set only once it got through]")
posts.clear()
w = new_watch()
answers[:] = [refused()]
for t in (0, 30, 60):
    w.tick(t, wall=1_000_000.0 + t)
check("3rd start: one push, refused", len(posts), 1)
check("the alarm is not marked sent", w.alerted, False)
w.tick(90, wall=1_000_090.0)
check("next look: pushed again", len(posts), 2)
check("delivered this time: marked sent", w.alerted, True)
w.tick(120, wall=1_000_120.0)
check("no third push once delivered", len(posts), 2)

print(f"\n[「中继停了」 never gets through: {CAP} pushes, then give up and say so]")
posts.clear()
logged.clear()
w = new_watch()
answers[:] = [refused() for _ in range(10)]
for k in range(10):
    w.tick(30 * k, wall=1_000_000.0 + 30 * k)
check(f"pushed exactly {CAP} times", len(posts), CAP)
check("given up: no more pushes this stretch", w.alerted, True)
check("the give-up is in watchdog.log", any("不再重试" in x for x in logged), True)
running["on"] = True
w.tick(2900, wall=1_002_900.0)     # up again, past LOOP_WINDOW_S: no crash-loop alarm mixed in
running["on"] = False
answers[:] = [refused()]
for k in range(100, 103):
    w.tick(30 * k, wall=1_000_000.0 + 30 * k)
check("a new stretch after the relay ran again: tried again", len(posts), CAP + 1)

print("\n[HTTPException from the bot: no endless re-send every 30 s]")
posts.clear()
w = new_watch()
answers[:] = [dropped() for _ in range(20)]
for k in range(20):
    try:
        w.tick(30 * k, wall=1_000_000.0 + 30 * k)
    except http.client.HTTPException:
        pass                        # what SvcDoRun's 「检查出错」 caught on the old code
check(f"bounded by {CAP}", len(posts), CAP)

print("\n[「没人登录」: same rule]")
posts.clear()
logon["on"] = False
w = new_watch()
answers[:] = [dropped(), refused()]
for t in range(0, W.NOBODY_LIMIT_S + 30 * 5, 30):
    try:
        w.tick(float(t), wall=1_000_000.0 + t)
    except http.client.HTTPException:
        pass
check("two failed, the third delivered", len(posts), 3)
check("marked sent", w.nobody_alerted, True)
logon["on"] = True

print("\n[crash loop: refused, tried again at the next start]")
posts.clear()
w = new_watch()
answers[:] = [refused()]
for k in range(6):
    running["on"] = True
    w.tick(300.0 * k, wall=1_000_000.0 + 300 * k)
    running["on"] = False
    w.tick(300.0 * k + 30, wall=1_000_030.0 + 300 * k)
check("5th start refused, 6th start delivered", (len(posts), w.loop_alerted_at), (2, 300.0 * 5 + 30))

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
