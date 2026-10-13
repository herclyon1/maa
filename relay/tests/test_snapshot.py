"""snapshot.read() skips the AUTO-MAS sections once the relay issued its own shutdown.

2026-10-06 06:21:34/36: after the relay issued the shutdown order the AUTO-MAS backend
was already gone, so `_MAS错误`/`_队列错误` failed with ConnectionRefused and two
WARNINGs went to the group. The read never asked errwatch.relay_shutdown_issued(),
which was True then. The fix: skip exactly those two sections while stopping; the
other two (`_OKWW错误` reads files, `_运行时错误` reads Windows services) still run.

2026-10-10 04:28:47: the same WARNING again, from a shutdown by hand (relay.log 04:28:45
「收到停止通知（Windows 关机）」, i.e. errwatch.mark_stopping()). relay_shutdown_issued()
was False, so the read went ahead and pushed. A machine shutdown - the relay's own, or
Windows' (SvcShutdown ran: errwatch.os_shutdown(), or SM_SHUTTINGDOWN) - now skips those
two sections, and a section failing once it has begun is INFO.

2026-10-12 (mute audit item 10): until then any service stop (errwatch.going_down(): also a
plain `sc stop` or the self-update restart, with the machine and AUTO-MAS staying up) counted,
so an AUTO-MAS that failed to answer then was INFO and reached nobody. Only the machine
really going down may keep it from the group.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.alarm import errwatch
from ark_relay.features.phone import snapshot

fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
    if not ok:
        fails.append(label)


class Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.warned: list[str] = []

    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.warned.append(record.getMessage())


grab = Grab()
snapshot.log.addHandler(grab)
snapshot.log.propagate = False

calls: list[str] = []


def fake(label):
    def f(out):
        calls.append(label)
        out[label] = "ok"
    return f


saved = (snapshot._mas, snapshot._queues, snapshot._okww, snapshot._runtime,
         errwatch.relay_shutdown_issued, errwatch.os_shutdown)
errwatch.os_shutdown = lambda: False

snapshot._mas, snapshot._queues = fake("_mas"), fake("_queues")
snapshot._okww, snapshot._runtime = fake("_okww"), fake("_runtime")

errwatch.relay_shutdown_issued = lambda: False
calls.clear()
out = snapshot.read()
check("没关机：四个都读", calls, ["_mas", "_queues", "_okww", "_runtime"])
check("没关机：无 WARNING", grab.warned, [])

errwatch.relay_shutdown_issued = lambda: True
calls.clear()
grab.warned.clear()
out = snapshot.read()
check("关机令已发：只读 _okww/_runtime，不碰 _mas/_queues", calls, ["_okww", "_runtime"])
check("关机令已发：无 WARNING", grab.warned, [])
check("_mas/_queues 不再写进结果", all(k not in out for k in ("_mas", "_queues")), True)
check("_okww/_runtime 还在", ("_okww" in out, "_runtime" in out), (True, True))

print("[10-10 04:28:47: Windows shutdown by hand, not the relay's own (SvcShutdown ran)]")
errwatch.relay_shutdown_issued = lambda: False
errwatch.os_shutdown = lambda: True
calls.clear()
grab.warned.clear()
out = snapshot.read()
check("手动关机：不碰 _mas/_queues", calls, ["_okww", "_runtime"])
check("手动关机：无 WARNING", grab.warned, [])

print("[a plain service stop (sc stop, the self-update restart): the machine stays up, so it is read]")
errwatch.os_shutdown = lambda: False
errwatch.mark_stopping()
try:
    calls.clear()
    grab.warned.clear()
    out = snapshot.read()
    check("service stop only: all four read", calls, ["_mas", "_queues", "_okww", "_runtime"])
    snapshot._mas = lambda out: (_ for _ in ()).throw(ConnectionRefusedError("x"))
    grab.warned.clear()
    snapshot.read()
    check("service stop only: a section that fails still warns (pushed)", len(grab.warned), 1)
    snapshot._mas = fake("_mas")
finally:
    errwatch.clear_stopping()

print("[the shutdown begins while a section is being read]")
state = {"down": False}
errwatch.os_shutdown = lambda: state["down"]


def gone(out):
    state["down"] = True
    raise ConnectionRefusedError("AUTO-MAS backend gone")


snapshot._mas = gone
grab.warned.clear()
out = snapshot.read()
check("读到一半开始关机：无 WARNING", grab.warned, [])
check("读到一半开始关机：错误仍记进结果", "_MAS错误" in out, True)

print("[not shutting down: a failing section still warns]")
state["down"] = False


def refused(out):
    raise ConnectionRefusedError("x")


snapshot._mas = refused
grab.warned.clear()
out = snapshot.read()
check("没关机时读不到：照样 WARNING", len(grab.warned), 1)

print("[a phone publish reads only the runtime section (audit 11 #2)]")
# relay.log 10-06 / 10-10: every phone publish ran _mas / _queues / _okww, kept only
# 「ark-relay」 and 「程序」 (from _runtime), and an AUTO-MAS hiccup reached the group.
import types  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402
from ark_relay.features.phone import phone  # noqa: E402


def runtime(out):
    calls.append("_runtime")
    out["ark-relay"], out["程序"] = "RUNNING", {"MAA": True}


snapshot._runtime = runtime
calls.clear()
grab.warned.clear()
pcfg = types.SimpleNamespace(automas_dir=str(tmpdir()), maaend_dir=str(tmpdir()), okww_dir=str(tmpdir()))
st = phone.state_payload(pcfg, tmpdir())
check("the publish calls only _runtime", calls, ["_runtime"])
check("an AUTO-MAS that does not answer is not a WARNING from the publish", grab.warned, [])
check("the phone still gets the runtime", st.get("run"), {"服务": "RUNNING", "在跑的": ["MAA"]})
calls.clear()
snapshot.read()
check("config-check's full read still reads every section", calls, ["_queues", "_okww", "_runtime"])

(snapshot._mas, snapshot._queues, snapshot._okww, snapshot._runtime,
 errwatch.relay_shutdown_issued, errwatch.os_shutdown) = saved
snapshot.log.removeHandler(grab)

print("[_queues: one queue's item list unreadable]")
import urllib.error  # noqa: E402
from unittest import mock  # noqa: E402

item_err = {"exc": None}


def fake_post(path, body=None, timeout=15):
    if path == "/api/scripts/get":
        return {"data": {"s1": {"Info": {"Name": "MAA"}}}}
    if path == "/api/queue/get":
        return {"data": {"q1": {"Info": {"Name": "早班", "TimeEnabled": True, "StartUpEnabled": False}}}}
    if item_err["exc"] is not None:
        raise item_err["exc"]
    return {"data": {"i1": {"Info": {"ScriptId": "s1"}}}}


class Grab2(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.warned = []

    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.warned.append(record)


g2 = Grab2()
snapshot.log.addHandler(g2)
getattr(snapshot, "_last_error", {}).clear()
with mock.patch.object(snapshot, "_post", fake_post), \
        mock.patch.object(errwatch, "relay_shutdown_issued", lambda: False), \
        mock.patch.object(errwatch, "os_shutdown", lambda: False):
    item_err["exc"] = urllib.error.HTTPError("u", 500, "boom", {}, None)
    out = {}
    snapshot._queues(out)
    q = out["队列"]["早班"]
    check("unreadable -> 脚本 stays [] (shape) and is marked", (q["脚本"], "脚本读不到" in q), ([], True))
    check("unreadable -> one WARNING", len(g2.warned), 1)
    snapshot._queues({})
    check("same condition again -> no second WARNING", len(g2.warned), 1)
    item_err["exc"] = None
    out = {}
    snapshot._queues(out)
    check("readable -> the list, no mark", (out["队列"]["早班"]["脚本"], "脚本读不到" in out["队列"]["早班"]),
          (["MAA"], False))
    item_err["exc"] = urllib.error.HTTPError("u", 500, "boom", {}, None)
    snapshot._queues({})
    check("broken again after a good read -> WARNING again", len(g2.warned), 2)
    item_err["exc"] = urllib.error.URLError(ConnectionRefusedError(61, "refused"))
    raised = False
    try:
        snapshot._queues({})
    except Exception:  # noqa: BLE001
        raised = True
    check("backend gone (connection refused) -> the section fails as before", raised, True)
snapshot.log.removeHandler(g2)

print("\n[_mas: one script's user unreadable is marked, not dropped (audit 11 #5)]")


def users_post(path, body=None, timeout=15):
    if path == "/api/scripts/get":
        return {"data": {"s1": {"Info": {"Name": "MAA"}}, "s2": {"Info": {"Name": "MaaEnd"}},
                         "s3": {"Info": {"Name": "OK-WW"}}}}
    if path == "/api/scripts/user/get" and body["scriptId"] == "s2":
        raise TimeoutError("timed out")
    if path == "/api/scripts/user/get" and body["scriptId"] == "s3":
        raise urllib.error.URLError("refused")
    return {"data": {"u1": {"Info": {"Stage": "1-7"}, "Task": {}}}}


o = {}
with mock.patch.object(snapshot, "_post", users_post):
    snapshot._mas(o)
check("the readable script is there", (o.get("MAA") or {}).get("关卡"), "1-7")
check("MaaEnd's section says its user could not be read", o.get("MaaEnd"), {"用户读不到": "TimeoutError: timed out"})
check("OK-WW's too, under its usual key", sorted(o.get("OK-WW(MAS侧)") or {}), ["用户读不到"])

print("\n[the phone page's relay state looks for the mutex the packaged main program holds]")
import re  # noqa: E402
_relay = Path(__file__).resolve().parents[1]
_held = re.search(r'^MUTEX = "([^"]+)"', (_relay / "app_main.py").read_text(encoding="utf-8"), re.M)
_watched = re.search(r'^MUTEX = "([^"]+)"',
                     (_relay.parent / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), re.M)
check("snapshot, app_main and the watchdog name the same mutex",
      (snapshot._MAIN_LOCK_NAME, _held and _held.group(1).replace("\\\\", "\\"),
       _watched and _watched.group(1).replace("\\\\", "\\")),
      (snapshot._MAIN_LOCK_NAME,) * 3)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
