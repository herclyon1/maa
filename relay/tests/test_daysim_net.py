"""daysim W3: the network, AUTO-MAS and desktop fakes answer the real relay code.

Each check drives the relay's own caller through the fake (notify, macpush,
mailbox, quota, cos_store, selfupdate, inbox, queues, engine, annihilation,
preupdate_automas, collect_retry, desktop, maintenance, efstatus, banners,
evidence.sources), so the shapes are the ones the relay reads, not the ones
the fake's author assumed. design.md section 6, W3: an unrouted URL fails; the
251st ntfy publish of a UTC day gets 429; AUTO-MAS does not re-read a config
file edited while it runs (R11).

The scheduler is a stand-in with the fixed W1 names (now, park, out); a helper's
park waits on a condition the test moves the clock under.
"""
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "relay"), str(ROOT / "relay" / "tests"), str(ROOT / "relay" / "tests" / "daysim")]
from _tmp import tmpdir  # noqa: E402

os.environ["ARK_STATE_DIR"] = str(tmpdir())
os.environ["ARK_MAS_PORT"] = "36163"

import fake_desktop  # noqa: E402
import fake_mas  # noqa: E402
import fake_net  # noqa: E402
from fake_mas import fake_automas  # noqa: E402 - scripts/ci, put on sys.path by fake_mas

UTC8 = timezone(timedelta(hours=8))
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Sched:
    """The W1 interface, minimal: a settable clock and an output list."""

    def __init__(self, t: float):
        self.t = t
        self.cond = threading.Condition()
        self.outs = []

    def now(self):
        return self.t

    def set(self, t):
        with self.cond:
            self.t = t
            self.cond.notify_all()

    def wake(self):
        with self.cond:
            self.cond.notify_all()

    def park(self, timeout, ready):
        deadline = self.t + timeout
        with self.cond:
            while not ready() and self.t < deadline:
                self.cond.wait(0.01)
        return ready()

    def out(self, kind, **f):
        self.outs.append((kind, f))

    def kinds(self, kind):
        return [f for k, f in self.outs if k == kind]


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


grab = Grab()
logging.getLogger().addHandler(grab)


def bj(y, mo, d, h, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC8).timestamp()


def wait_real(pred, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


# ---------------------------------------------------------------- push channels
print("push channels through the relay's own senders")
from ark_relay.core import notify  # noqa: E402
from ark_relay.features.alarm import macpush  # noqa: E402

s = Sched(bj(2026, 10, 12, 11, 45))
net = fake_net.FakeNet(s).install()
cfg = SimpleNamespace(wecom_corpid="simcorp", wecom_secret="simsecret", wecom_agentid="1000002",
                      wecom_touser="@all", serverchan_key="SCTsim",
                      wecom_bot_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=sim-webhook")
notify.WeComBot(cfg).send_text("鸣潮 早班没干完\n周本没打")
notify.WeCom(cfg).send_text("明日方舟 私聊一条")
notify.ServerChan(cfg).send_text("日报 10-12", "第一行\n第二行")
mp = macpush.MacPush(tmpdir(), "http://100.110.87.36:8931/alert")
check("macpush posts through build_opener and hears ok",
      mp._http_post({"game": "终末地", "title": "终末地 报警", "text": "正文"}), ("ok", ""))
pushes = s.kinds("push")
check("four pushes, one per channel", [p["ch"] for p in pushes], ["group", "wecom_app", "serverchan", "mac"])
check("group push: title is the first line, game read from it",
      (pushes[0]["title"], pushes[0]["game"], pushes[0]["text"]), ("鸣潮 早班没干完", "鸣潮", "鸣潮 早班没干完\n周本没打"))
check("Server酱: title and body as sent (Markdown line doubling undone)",
      (pushes[2]["title"], pushes[2]["text"]), ("日报 10-12", "第一行\n第二行"))
check("mac push keeps the row's game", (pushes[3]["game"], pushes[3]["title"]), ("终末地", "终末地 报警"))
check("push time is the sim time, Beijing", pushes[0]["t"], "2026-10-12T11:45:00+08:00")
check("no request kept with its query (webhook key, access token, corpsecret)",
      [c["url"] for c in net.calls if "?" in c["url"] or "key=" in c["url"]], [])

# ---------------------------------------------------------------- the guard
print("anything unrouted is a sim error and fails like an unreachable host")
before = len(s.kinds("sim_error"))
try:
    urllib.request.urlopen("https://example.invalid/x?token=1", timeout=5)
    got = "answered"
except urllib.error.URLError as exc:
    got = type(exc).__name__
check("an unknown host raises URLError", got, "SimNetError")
for name, call in (("create_connection", lambda: socket.create_connection(("192.0.2.7", 80), 1)),
                   ("socket.connect", lambda: socket.socket().connect(("192.0.2.7", 80)))):
    try:
        call()
        got = "connected"
    except ConnectionRefusedError:
        got = "refused"
    check(f"raw {name} is refused", got, "refused")
errs = s.kinds("sim_error")[before:]
check("three sim errors, the URL without its query",
      [e["what"] for e in errs], ["unrouted URL", "raw socket connect", "raw socket connect"])
check("the unrouted URL is logged bare", errs[0]["url"], "https://example.invalid/x")
check("name resolution still answers (service._wait_for_network)",
      bool(socket.getaddrinfo("raw.githubusercontent.com", 443)), True)

# ---------------------------------------------------------------- ntfy quota (R08)
print("ntfy: 250 publishes per UTC day, refused as ntfy refuses them")
from ark_relay.features.phone import quota as quota_mod  # noqa: E402


def publish(topic="simtopic"):
    """The status ntfy answers one publish with (a refusal is its code, not a raise)."""
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=b"x", method="POST", headers={"Title": "state"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


s.set(bj(2026, 10, 12, 7, 0))                  # UTC 10-11 23:00
check("250 publishes from 07:00 Beijing all accepted", {publish() for _ in range(250)}, {200})
s.set(bj(2026, 10, 12, 7, 59))
try:
    urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/simtopic-hb", data=b"beat", method="POST"))
    got = None
except urllib.error.HTTPError as exc:
    got = (exc.code, quota_mod._ntfy_code(exc)[0])
check("the 251st, 07:59 Beijing (same UTC day), is 429 / 42908 for any topic", got, (429, 42908))
check("ntfy's account says 0 left", quota_mod.ntfy_account()["stats"]["messages_remaining"], 0)
s.set(bj(2026, 10, 12, 8, 1))                  # UTC midnight passed
check("08:01 Beijing is a new UTC day: accepted", publish(), 200)
s.set(bj(2026, 10, 13, 6, 0))
n6 = sum(publish() == 200 for _ in range(200))
s.set(bj(2026, 10, 13, 8, 30))
n8 = sum(publish() == 200 for _ in range(51))
check("200 at 06:00 + 51 at 08:30 Beijing span two UTC days: none refused", (n6, n8), (200, 51))
check("account count follows the UTC day", quota_mod.ntfy_account()["stats"]["messages"], 51)
check("publishes are captured as ntfy pushes", s.kinds("push")[-1]["ch"], "ntfy")

# ---------------------------------------------------------------- ntfy mailbox + stream
print("ntfy: the boot backlog and the held stream, through mailbox.Mailbox")
from ark_relay.features.phone import mailbox as mailbox_mod  # noqa: E402

t0 = float(int(time.time()))          # wire.unpack ages envelopes by the real clock
s.set(t0)
pin, topic = "simpin", "simphone"
net.phone_order(t0 - 60, {"action": "refresh"}, pin, topic)
net.phone_order(t0 - 3600, {"action": "x"}, "otherpin", topic)
mb = mailbox_mod.Mailbox(topic, pin, tmpdir())
backlog = mb.fetch("24h")
check("the order pressed before boot is in the backlog read", [c["action"] for c in backlog], ["refresh"])
check("the backlog read says where it came from", backlog[0]["_meta"]["via"], "backlog")
got, stopped = [], threading.Event()
th = threading.Thread(target=mb.listen, args=(got.append, stopped.is_set), daemon=True, name="phone-mailbox")
th.start()
check("the stream connects", wait_real(lambda: mb.connected), True)
net.phone_order(t0 + 10, {"action": "skip_today", "queue": "早班"}, pin, topic)
time.sleep(0.05)
check("an order stamped t+10 is not delivered before t+10", got, [])
s.set(t0 + 10)
check("at t+10 the held stream delivers it", wait_real(lambda: len(got) == 1), True)
check("the live order is the one pressed, via live",
      got and (got[0]["action"], got[0]["_meta"]["via"]), ("skip_today", "live"))
s.set(t0 + 10 + fake_net.NTFY_KEEPALIVE_S)
check("a keepalive 45 s after the last line moves the mailbox mark",
      wait_real(lambda: mb._mark == int(t0 + 10 + fake_net.NTFY_KEEPALIVE_S)), True)
stopped.set()
mb.close()
th.join(3)
check("close() ends the held read at once", th.is_alive(), False)
check("the backlog order was not run twice", [c["action"] for c in got], ["skip_today"])
net.fault("simdrop", "drop")
st = urllib.request.urlopen(f"https://ntfy.sh/simdrop/json?since={int(t0)}", timeout=90)
first = json.loads(next(st))
try:
    next(st)
    got_drop = "line"
except ConnectionResetError:
    got_drop = "reset"
check("a stream fault: open line, then the connection drops", (first["event"], got_drop), ("open", "reset"))
before = len(s.kinds("sim_error"))
urllib.request.urlopen("https://ntfy.sh/simphone/json?poll=1&since=yesterday", timeout=25).read()
check("a since= ntfy would not understand is a sim error", len(s.kinds("sim_error")) - before, 1)

# ---------------------------------------------------------------- faults on one call
print("recorded network faults fail exactly the call they name")
net.fault("sctapi.ftqq.com", "http:502")
try:
    urllib.request.urlopen(urllib.request.Request("https://sctapi.ftqq.com/SCTsim.send", data=b"title=a"))
    got = "sent"
except urllib.error.HTTPError as exc:
    got = exc.code
check("the faulted call fails with its status", got, 502)
check("the next one goes through", urllib.request.urlopen(
    urllib.request.Request("https://sctapi.ftqq.com/SCTsim.send", data=b"title=a")).status, 200)
net.fault("ntfy.sh/v1/account", "timeout")
try:
    quota_mod.ntfy_account(timeout=0.01)
    got = "answered"
except TimeoutError:
    got = "timed out"
check("a timeout fault waits the call's timeout, then times out", got, "timed out")
for kind, want in (("refused", "URLError"), ("reset", "ConnectionResetError")):
    net.fault("api.gofile.io", kind)
    try:
        urllib.request.urlopen("https://api.gofile.io/servers", timeout=5)
        got = "answered"
    except (urllib.error.URLError, ConnectionResetError) as exc:
        got = type(exc).__name__
    check(f"fault {kind}", got, want)
try:
    net.fault("ntfy.sh/simpub", "refused", method="POST")
except TypeError as exc:
    check("a fault can be limited to one HTTP method", str(exc), "")
urllib.request.urlopen(f"https://ntfy.sh/simpub/json?poll=1&since={int(t0)}", timeout=5).read()
try:
    urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/simpub", data=b"x", method="POST"), timeout=5)
    got = "published"
except urllib.error.URLError:
    got = "refused"
check("a POST-only fault passes the GET on the same URL and fails the publish (10-08 21:49)", got, "refused")

# ---------------------------------------------------------------- COS, self-update, inbox, evidence
print("COS bucket, self-update 'current', the inbox doors, evidence stores")
from ark_relay.features.evidence import stores  # noqa: E402
from ark_relay.features.phone import cos_store, inbox  # noqa: E402
from ark_relay.features.selfupdate import selfupdate  # noqa: E402

cos = stores.Cos("AKIDSIMSIMSIM", "simsecret", "simbucket-1250000000", "ap-shanghai")
check("COS probe: the bucket takes the key", cos.probe(), "")
check("cos_put stores", cos_store.cos_put(cos, "state/abc.json", b'{"a":1}', 10), None)
check("cos_get reads it back", cos_store.cos_get(cos, "state/abc.json", 10), (b'{"a":1}', ""))
check("cos_get of a missing object is (None, '')", cos_store.cos_get(cos, "state/none.json", 10), (None, ""))
rel = stores.Cos("AKIDSIMSIMSIM", "simsecret", "simbucket-1250000000", "ap-shanghai", prefix=selfupdate.COS_PREFIX)
check("self-update: COS says the running version, nothing newer",
      selfupdate._cos_manifest(rel, net.code_version), (None, net.code_version))
check("the code version is the manifest's", net.code_version > 20260000000000, True)
check("inbox COS door: the default file is version 0", inbox._fetch_cos_once(rel), {"version": 0})
net.set_inbox({"version": 2026101302, "note": "sim"})
check("inbox after set_inbox: COS door", inbox._fetch_cos_once(rel)["version"], 2026101302)
check("inbox after set_inbox: every GitHub door",
      {inbox._fetch_once(u)["version"] for u in selfupdate._alternates(inbox.DEFAULT_URL)}, {2026101302})
check("gofile upload answers a page", stores.Gofile(tmpdir()).upload(Path(__file__))["page"], "https://gofile.io/d/sim")
check("LLM asked: an empty wording, noted", (json.loads(urllib.request.urlopen(urllib.request.Request(
    "https://api.deepseek.com/chat/completions", data=b"{}")).read())["choices"][0]["message"]["content"],
    s.kinds("sim_note")[-1]["what"]), ("", "LLM asked; answered with no wording"))

# ---------------------------------------------------------------- information sources
print("information sources: 'nothing new', read by the relay's parsers without a WARNING")
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.banners import banners  # noqa: E402
from ark_relay.features.evidence import sources  # noqa: E402
from ark_relay.features.maintenance import efstatus, maintenance  # noqa: E402

s.set(bj(2026, 10, 12, 8, 46))
grab.lines.clear()
before = len(s.kinds("sim_error"))
now = datetime.fromtimestamp(s.now(), SERVER_TZ)
check("maintenance.today: no window", maintenance.today(now), {})
check("efstatus.update_hint(strict): no update today", efstatus.update_hint(now, strict=True), "")
check("pinned upstream files: none changed, none unreachable", sources.check_sources(), ([], []))
b_failed = []
rows, _nxt = banners.collect(now.replace(tzinfo=None), skland_token="", failed=b_failed, notes={},
                             trace=banners.Trace.new(), leads={}, read_image=lambda *a, **k: None)
check("banners: only the source that needs a token is missing", b_failed, ["终末地（没有森空岛令牌）"])
check("banners: the Arknights table parses", bool(rows), True)
check("no WARNING from any information source", grab.lines, [])
check("no sim error from any information source", s.kinds("sim_error")[before:], [])
net.set_web("https://game-hub.hypergryph.com/", {"code": 0, "data": {"list": [
    {"title": "x", "header": "「雪凇幽梦」版本更新说明", "startAt": int(bj(2026, 10, 12, 10, 0))}]}})
check("a per-day web answer replaces the default", efstatus.update_hint(now, strict=True),
      "官方公告：今天 10:00 「雪凇幽梦」版本更新")

# ---------------------------------------------------------------- AUTO-MAS
print("AUTO-MAS: memory, write-through, running guard, snapshot, shutdown")
from ark_relay.core import engine  # noqa: E402
from ark_relay.features.makeup import collect_retry  # noqa: E402
from ark_relay.features.phone import commands, mas_client  # noqa: E402
from ark_relay.features.preupdate import preupdate_automas  # noqa: E402
from ark_relay.features.schedule import queues  # noqa: E402
from ark_relay.features.weekly.annihilation import _backend_unreachable  # noqa: E402

AM, QM, QE, ITEM = tmpdir(), "q-morning", "q-evening", "i-maa"
fake_automas.seed(AM, {})
queue_cfg = {
    "instances": [{"uid": QM, "type": "QueueConfig"}, {"uid": QE, "type": "QueueConfig"}],
    QM: {"Info": {"Name": "早班", "TimeEnabled": True}, "Data": {},
         "SubConfigsInfo": {"QueueItem": {"instances": [{"uid": ITEM, "type": "QueueItem"}],
                                          ITEM: {"Info": {"ScriptId": fake_automas.MAA},
                                                 "Schedule": {"Days": ["Monday", "Tuesday"]}}}}},
    QE: {"Info": {"Name": "晚班", "TimeEnabled": True}, "Data": {}, "SubConfigsInfo": {}},
}
qfile = AM / "config" / "QueueConfig.json"
qfile.write_text(json.dumps(queue_cfg, ensure_ascii=False), encoding="utf-8")
dispatched = []
mas = fake_mas.FakeMas(s, AM, tmpdir(), version="v5.6.0", on_dispatch=lambda tid, mode: dispatched.append((tid, mode)))
net.mas = mas


def file_enabled(name):
    q = json.loads(qfile.read_text(encoding="utf-8"))
    return next(q[i["uid"]]["Info"]["TimeEnabled"] for i in q["instances"] if q[i["uid"]]["Info"]["Name"] == name)


def api_enabled(name):
    data = mas_client.mas_post("/api/queue/get")["data"]
    return next(v["Info"]["TimeEnabled"] for v in data.values() if v["Info"]["Name"] == name)


ok, msg = queues._enabled_via_backend("早班", False)
check("queues: switched through the backend and read back", ok, True)
check("AUTO-MAS saved memory to its file", file_enabled("早班"), False)
check("the switch is an output", s.kinds("mas_write")[-1]["path"], "/api/queue/update")
q = json.loads(qfile.read_text(encoding="utf-8"))
q[QE]["Info"]["TimeEnabled"] = False
qfile.write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")       # the R11 mistake
check("R11: a file edit while the backend runs is not seen by the API", api_enabled("晚班"), True)
check("R11: the edit is an output marked unseen",
      [(w["how"], w["file"], w["seen_by_backend"]) for w in s.kinds("mas_write") if w.get("how") == "file"],
      [("file", "QueueConfig.json", False)])
mas.run_started()
check("R11: the next save puts memory back over the edit", file_enabled("晚班"), True)
check("memory() is what a timed queue runs with", mas.memory()[QE]["Info"]["TimeEnabled"], True)
mas.stop()
q[QE]["Info"]["TimeEnabled"] = False
qfile.write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")
mas.start()
check("a file edited while the backend is down is read at its next start", api_enabled("晚班"), False)
check("queue/item/get answers index + data",
      [i["uid"] for i in mas_client.mas_post("/api/queue/item/get", {"queueId": QM})["index"]], [ITEM])

mas.set_tasks([{"taskId": QM, "mode": "AutoProxy", "task_info": [{"name": "MAA", "status": "运行"}]}])
r = mas_client.mas_post("/api/queue/update", {"queueId": QM, "data": {"Info": {"TimeEnabled": True}}})
check("running guard: an Info change of the running queue is refused", commands._refused(r), fake_mas.REFUSED_RUNNING)
r = mas_client.mas_post("/api/queue/item/update", {"queueId": QM, "queueItemId": ITEM,
                                                   "data": {"Schedule": {"Days": ["Monday"]}}})
check("running guard: a Schedule-only item write passes", r["status"], "success")
mas.set_tasks([{"taskId": "run-7", "mode": "早班", "task_info": [{"name": "MAA", "status": "运行"}]}])
r = mas_client.mas_post("/api/queue/update", {"queueId": QM, "data": {"Info": {"TimeEnabled": True}}})
check("running guard: a queue task named by its mode counts too", commands._refused(r), fake_mas.REFUSED_RUNNING)
mas.set_tasks([{"taskId": QM, "mode": "AutoProxy", "task_info": [{"name": "MAA", "status": "运行"}]}])
r = mas_client.mas_post("/api/scripts/user/update", {"scriptId": fake_automas.MAA, "userId": fake_automas.UID,
                                                     "data": {"Info": {"Stage": "1-7"}}})
check("running guard: a script setting is refused while a task runs", commands._refused(r), fake_mas.REFUSED_RUNNING)
check("runtime-snapshot (a GET) says busy", engine._judge_snapshot(engine._automas_snapshot()), True)
check("the busy script is MAA", engine._script_unfinished(engine._automas_snapshot(), "MAA"), True)
mas_client.mas_post("/api/dispatch/stop", {"taskId": QM})
check("dispatch/stop of the live task ends it", engine._judge_snapshot(engine._automas_snapshot()), False)
mas.set_tasks([])
r = mas_client.mas_post("/api/scripts/user/update", {"scriptId": fake_automas.MAA, "userId": fake_automas.UID,
                                                     "data": {"Info": {"Stage": "1-7"}}})
check("idle: the script setting is accepted", commands._refused(r), "")
r = mas_client.mas_post("/api/dispatch/start", {"taskId": fake_automas.MAA, "mode": "AutoProxy"})
check("dispatch/start reaches the World's hook", (r["status"], dispatched), ("success", [(fake_automas.MAA, "AutoProxy")]))
check("health answers the version", preupdate_automas._live_version(), "v5.6.0")
try:
    mas_client.mas_post("/api/plan/get")
    got = "answered"
except urllib.error.HTTPError as exc:
    got = exc.code
check("an endpoint the model lacks: 404 and a sim error", (got, s.kinds("sim_error")[-1]["what"]),
      (404, "AUTO-MAS endpoint not modelled"))

mas.apply_event({"kind": "mas_config", "file": "QueueConfig.json", "data": q})
check("a recorded config change reaches memory and file", (api_enabled("晚班"), file_enabled("晚班")), (False, False))
mas.apply_event({"kind": "mas_backend", "state": "down"})
mas.apply_event({"kind": "mas_backend", "state": "up"})
check("a recorded backend restart keeps answering", api_enabled("早班"), False)

s.set(bj(2026, 10, 12, 21, 46))
mas.shutdown_started(reset_s=5)
seen = []
for dt in (0, 6):
    s.set(bj(2026, 10, 12, 21, 46) + dt)
    try:
        mas_client.mas_post("/api/queue/get")
        seen.append("answered")
    except Exception as exc:  # noqa: BLE001 - the relay's own test decides
        seen.append((type(exc).__name__, _backend_unreachable(exc)))
check("R04/R05: shutdown kills the backend: a reset first, then refused",
      seen, [("ConnectionResetError", False), ("URLError", True)])
check("runtime-snapshot after shutdown: cannot ask", engine._automas_snapshot(), None)

print("MaaEnd MXU on 12701")
mxu_up = []
net.mxu = fake_net.MxuModel(s, lambda: bool(mxu_up), task_s=600)
try:
    collect_retry.api("/maa/state", timeout=5)
    got = "answered"
except urllib.error.URLError:
    got = "refused"
check("MXU refused while MaaEnd is not running", got, "refused")
mxu_up.append(1)
for p in ("/maa/instances/automas/connect", "/maa/instances/automas/resource/load",
          "/maa/instances/automas/tasks/start"):
    collect_retry.api(p, {})
st = collect_retry.api("/maa/state")["instances"]["automas"]
check("MXU: connected, loaded, running after tasks/start",
      (st["connected"], st["resource_loaded"], st["is_running"]), (True, True, True))
check("MXU windows lists the game window", collect_retry.api("/maa/windows?class_regex=UnityWndClass")["windows"][0]["handle"],
      0x1234)
s.set(s.now() + 600)
check("MXU: the task ends after its recorded length", collect_retry.api("/maa/state")["instances"]["automas"]["is_running"],
      False)

# ---------------------------------------------------------------- desktop
print("desktop agent answered from recorded req/res pairs")
from ark_relay.core import desktop  # noqa: E402

rec = tmpdir()
pairs = (("0001", {"focus": "title:鸣潮", "actions": [{"act": "ocr"}], "shot": r"C:\x\shot-0001.png"},
          {"ok": True, "ocr": [{"text": "开始游戏", "x": 1, "y": 2, "w": 3, "h": 4}]}, -300),
         ("0002", {"focus": None, "actions": [{"act": "ocrfile", "path": r"C:\x\img-ab12-4.png"}],
                   "shot": r"C:\x\shot-0002.png"},
          {"ok": True, "ocr": [{"text": "3.7版本", "x": 0, "y": 0, "w": 9, "h": 9}]}, -200))
for rid, rq, rs, age in pairs:
    for kind, body in (("req", rq), ("res", rs)):
        f = rec / f"{kind}-{rid}.json"
        f.write_text("\ufeff" + json.dumps(body, ensure_ascii=False), encoding="utf-8")
        os.utime(f, (s.now() + age, s.now() + age))
(rec / "req-0003.json").write_text("{}", encoding="utf-8")          # no result: skipped
fd = fake_desktop.FakeDesktop(s, rec).install()
check("two recorded pairs loaded", sum(len(v) for v in fd.recorded.values()), 2)
grab.lines.clear()
dk = desktop.Desktop(tmpdir(), timeout=5)
t_real = time.monotonic()
scr = dk.read(focus="title:鸣潮")
check("a recorded screen read returns the recorded lines", [ln.text for ln in scr.lines], ["开始游戏"])
check("answered without the agent's poll wait", time.monotonic() - t_real < 1, True)
lines = dk.read_file(Path("/sim/state/desktop/img-ab12-4.png"))
check("OCR of a file matches by file name", [ln.text for ln in lines or []], ["3.7版本"])
scr = dk.read(focus="title:明日方舟")
check("an unrecorded read is an empty screen, not an agent failure",
      (scr.lines, scr.error, scr.focus_missing), ([], "", False))
check("... with a sim note", s.kinds("sim_note")[-1]["what"], "desktop request not recorded")
check("no WARNING from the desktop path", grab.lines, [])
check("screenshots are not recorded: None", dk.screenshot(timeout=5), None)
scr = dk.read(focus="title:鸣潮")
check("a recording asked for again is reused, noted",
      ([ln.text for ln in scr.lines], s.kinds("sim_note")[-1]["what"]), (["开始游戏"], "desktop answer reused"))
check("every request is listed", [a["answered"] for a in fd.asked], [True, True, False, False, True])
fd.add(s.now(), {"focus": None, "actions": [{"act": "click_text", "text": "更新"}]},
       {"ok": True, "clicked": ["更新"]})
check("a click answered from an added pair", dk.click_text("更新"), True)
check("the request key ignores the folder of an OCR'd file",
      fake_desktop.request_key({"actions": [{"act": "ocrfile", "path": "/a/b/x.png"}]}),
      fake_desktop.request_key({"actions": [{"act": "ocrfile", "path": r"D:\c\x.png"}]}))
fd.spawn(None, None, ("-File", str(rec / "req-0001.json"), str(rec / "res-new.json")))
check("spawn writes the result file the agent would", "开始游戏" in (rec / "res-new.json").read_text(encoding="utf-8"),
      True)
fake_desktop.FakeDesktop.uninstall()
check("uninstall puts the agent start back", desktop.Desktop._spawn_default is not fd.spawn, True)

fake_net.FakeNet.uninstall()
check("uninstall puts urlopen back", urllib.request.urlopen is not net.urlopen, True)
check("game_of finds the game in a text", fake_net.game_of("", "终末地 报警"), "终末地")
check("utc_day buckets Beijing 07:59 into the previous UTC date", fake_net.FakeNet.utc_day(bj(2026, 10, 12, 7, 59)),
      "2026-10-11")

if fails:
    print(f"FAILED: {len(fails)}")
    for f in fails:
        print("  ✗", f)
    sys.exit(1)
print("all checks passed")
