"""Each group alarm is also POSTed to the Mac (macpush.py); what the Mac cannot take waits.

The user, 2026-10-11 18:25, on the Mac pulling COS every two minutes:
「又在那轮询你们他妈只会做轮询是吗」. The relay now POSTs the very row it copies to
COS alerts/ (alertlog.FIELDS) to the Mac, 3-second limit; what does not get there
is kept on disk and sent with the next alarm or at the next boot, dropped only
once the Mac took it. None of it may touch the group alarm or the COS copy.

A real HTTP server on 127.0.0.1 stands in for the Mac; a closed port stands in
for 「积极拒绝」 (the 18:26 observation: the network reaches the Mac, nothing listens).
"""
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                  COS_SECRET_ID="", COS_SECRET_KEY="", COS_BUCKET="", COS_REGION="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.alarm import alertlog, macpush  # noqa: E402
from ark_relay.core import texts  # noqa: E402
from ark_relay.core.config import Config  # noqa: E402
from ark_relay.core.notify import Notifier  # noqa: E402
from ark_relay.core.statestore import StateStore  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Mac:
    """A stand-in for the Mac's listener: keeps every body it was POSTed."""

    def __init__(self):
        self.got, self.paths, self.types = [], [], []
        self.status = 200
        self.delay = 0.0
        mac = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                if mac.delay:
                    time.sleep(mac.delay)
                if mac.status == 200:
                    mac.got.append(json.loads(body.decode("utf-8")))
                    mac.paths.append(self.path)
                    mac.types.append(self.headers.get("Content-Type"))
                self.send_response(mac.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/alert"

    def titles(self):
        return [x.get("title") for x in self.got]


def closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/alert"


def join(t):
    if t is not None:
        t.join(10)


class FakeCos:
    def __init__(self):
        self.puts = []

    def put(self, key, data):
        self.puts.append((key, data))
        return None

    def get(self, key):
        return None, ""


def notifier(name, url):
    cfg = Config()
    cfg.state_dir = TMP / name
    cfg.alert_push_url = url
    StateStore(cfg.state_dir).set("versions", "code", "20261011190000")
    n = Notifier(cfg)
    n._fan_out = lambda title, body, **kw: (["企业微信机器人"], {})
    cos = FakeCos()
    n._alerts = alertlog.AlertLog(cfg.state_dir, put=cos.put, get=cos.get)
    return n, cos


def last_threads(n):
    """Wait for the Mac push and the COS copy threads this notifier started."""
    for t in threading.enumerate():
        if t.name in ("alarm-mac", "alarm-copy"):
            t.join(10)


print("\n[默认地址：Mac 的 Tailscale 地址、验收端口 8931；.env 可改；测试里一律关着]")
saved = os.environ.pop("ARK_ALERT_PUSH_URL", None)
check("默认地址", Config().alert_push_url, "http://100.110.87.36:8931/alert")
os.environ["ARK_ALERT_PUSH_URL"] = "http://10.0.0.9:1/x"
check(".env 覆盖", Config().alert_push_url, "http://10.0.0.9:1/x")
os.environ["ARK_ALERT_PUSH_URL"] = saved if saved is not None else ""
check("测试环境里默认关着（_tmp.py），测试报警不会发到真的 Mac", Config().alert_push_url, "")
check("关着时不排队、不发", macpush.MacPush(TMP / "off", "").push({"title": "x"}), None)
check("关着时没有队列文件", (TMP / "off" / macpush.QUEUE_FILE).exists(), False)

print("\n[POST 成功：送的就是 COS 那一行，一字不差；送到就从队列里删]")
mac = Mac()
n, cos = notifier("ok", mac.url)
check("群报警照常送达", n.send(texts.ROUND_INCOMPLETE, "鸣潮 OK-WW 这一轮没干完", alert=True), [])
last_threads(n)
check("Mac 收到一条", mac.titles(), [texts.ROUND_INCOMPLETE])
check("路径 /alert", mac.paths, ["/alert"])
check("Content-Type 是 JSON", mac.types, ["application/json; charset=utf-8"])
cos_row = json.loads(cos.puts[-1][1].decode("utf-8").splitlines()[-1]) if cos.puts else {}
check("字段正好是 COS 那几个", mac.got and tuple(mac.got[0]), alertlog.FIELDS)
check("和 COS 那一行完全一样（同一个 ts）", mac.got and mac.got[0], cos_row)
check("版本是本机代码版本", mac.got and mac.got[0]["version"], "20261011190000")
check("送到后队列空了", n.mac_push().pending(), [])
check("队列文件删掉了", (TMP / "ok" / macpush.QUEUE_FILE).exists(), False)
n.send("📋 10-11 · 全绿 ✅", "正文", daily=True)
n.send("🆕 游戏更新", "正文")
n.send("🔄 中继已更新", "正文", alert=True)
n.send_group("📣 明天开卡池", "正文")
last_threads(n)
check("日报、普通信息、只记日志的不送；send_group 送", mac.titles(),
      [texts.ROUND_INCOMPLETE, "📣 明天开卡池"])

print("\n[POST 超时（3 秒上限，测试里缩短）：进队列，推送不等它]")
slow = Mac()
slow.delay = 1.0
mp = macpush.MacPush(TMP / "slow", slow.url, timeout=0.3)
t0 = time.monotonic()
th = mp.push(alertlog.row("⚠️ 慢的", "a"))
check("push 立刻返回（POST 在自己的线程里）", time.monotonic() - t0 < 0.5)
join(th)
check("超时的留在队列里", [x["title"] for x in mp.pending()], ["⚠️ 慢的"])
check("落了盘", json.loads((TMP / "slow" / macpush.QUEUE_FILE).read_text("utf-8"))[0]["title"], "⚠️ 慢的")
check("超时上限默认 3 秒", macpush.TIMEOUT, 3.0)

print("\n[Mac 没人听（积极拒绝）：进队列；下一条报警时先补旧的再发新的，按先后]")
down = closed_port_url()
mp = macpush.MacPush(TMP / "later", down)
join(mp.push(alertlog.row("⚠️ 一", "a")))
join(mp.push(alertlog.row("⚠️ 二", "b")))
check("两条都留着", [x["title"] for x in mp.pending()], ["⚠️ 一", "⚠️ 二"])
mac2 = Mac()
mp.url = mac2.url                      # the Mac's listener is up again
join(mp.push(alertlog.row("⚠️ 三", "c")))
check("下一条报警时三条按先后送到", mac2.titles(), ["⚠️ 一", "⚠️ 二", "⚠️ 三"])
check("全送到后队列空了", mp.pending(), [])

print("\n[开机补发：新进程读回盘上的队列，开机那一下全送出去；送到才删]")
mp = macpush.MacPush(TMP / "boot", down)
join(mp.push(alertlog.row("⚠️ 关机前没送到", "x")))
check("关机前没送到的在盘上", (TMP / "boot" / macpush.QUEUE_FILE).exists())
mac3 = Mac()
cfg = Config()
cfg.state_dir = TMP / "boot"
cfg.alert_push_url = mac3.url
fresh = Notifier(cfg)                  # the process after the reboot
check("新进程读回了队列", [x["title"] for x in fresh.mac_push().pending()], ["⚠️ 关机前没送到"])
join(fresh.mac_push().flush_async())   # what boot_stages.py does at start
check("开机补发送到了", mac3.titles(), ["⚠️ 关机前没送到"])
check("送到后才删", (TMP / "boot" / macpush.QUEUE_FILE).exists(), False)
src = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
check("boot_stages.py 开机时调了补发", "notifier.mac_push().flush_async()" in src)

print("\n[Mac 拒收（4xx）：丢掉，不卡住后面的；5xx 留着]")
picky = Mac()
picky.status = 400
mp = macpush.MacPush(TMP / "picky", picky.url)
join(mp.push(alertlog.row("⚠️ 拒收的", "x")))
check("4xx 丢掉", mp.pending(), [])
picky.status = 503
join(mp.push(alertlog.row("⚠️ 忙", "x")))
check("5xx 留着", [x["title"] for x in mp.pending()], ["⚠️ 忙"])
picky.status = 429
join(mp.flush_async())
check("429 也留着", len(mp.pending()), 1)

print("\n[POST 失败不影响群报警，也不影响 COS 那份；不出 WARNING（WARNING 会进群）]")
import logging  # noqa: E402
seen = []


class Grab(logging.Handler):
    def emit(self, record):
        seen.append(record)


grab = Grab(level=logging.DEBUG)
logging.getLogger("ark").addHandler(grab)
logging.getLogger("ark").setLevel(logging.DEBUG)
n, cos = notifier("down", down)
check("Mac 连不上，群报警照常送达", n.send(texts.RELAY_ERROR, "x", alert=True), [])
last_threads(n)
check("COS 那份照常写了", len(cos.puts), 1)
check("没送到的留着", [x["title"] for x in n.mac_push().pending()], [texts.RELAY_ERROR])
check("第二条报警时也照常送达", n.send(texts.RELAY_ERROR, "x2", alert=True), [])
last_threads(n)
check("两条都留着", len(n.mac_push().pending()), 2)
mine = [r for r in seen if r.name == "ark.macpush"]
check("Mac 没开是正常状态：只记 INFO，没有 WARNING", sorted({r.levelname for r in mine}), ["INFO"])
check("连续两次不通只说一次", len(mine), 1)


class Boom:
    def push(self, row):
        raise RuntimeError("boom")


n._mac = Boom()
seen.clear()
check("直送 Mac 这段抛异常，群报警照常送达", n.send(texts.RELAY_ERROR, "y", alert=True), [])
last_threads(n)
check("COS 那份照常写了（抛异常时）", len(cos.puts), 3)
check("真出错（代码坏了）才是 WARNING", [r.getMessage() for r in seen if r.levelno >= logging.WARNING],
      ["报警没能直送 Mac"])
logging.getLogger("ark").removeHandler(grab)

print("\n[同时来几条：只有一个在发，后来的不丢]")
mac4 = Mac()
mac4.delay = 0.2
mp = macpush.MacPush(TMP / "burst", mac4.url)
ts = [mp.push(alertlog.row(f"⚠️ {i}", "")) for i in range(5)]
for t in ts:
    join(t)
check("五条都送到，按先后", mac4.titles(), [f"⚠️ {i}" for i in range(5)])
check("队列空了", mp.pending(), [])

print("\n[队列最多留 MAX_QUEUE 条（留新的）；坏掉的队列文件按空处理]")
mp = macpush.MacPush(TMP / "cap", down)
for i in range(macpush.MAX_QUEUE + 3):
    mp.add({"title": str(i)})
check("留最新的 MAX_QUEUE 条", (len(mp.pending()), mp.pending()[0]["title"]),
      (macpush.MAX_QUEUE, "3"))
(TMP / "bad").mkdir()
(TMP / "bad" / macpush.QUEUE_FILE).write_text("{not json", encoding="utf-8")
check("坏文件按空队列", macpush.MacPush(TMP / "bad", down).pending(), [])

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
