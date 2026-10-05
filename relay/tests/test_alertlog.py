"""Every group alarm is also appended to COS alerts/<Beijing YYYYMMDD>.jsonl, after the push, on a thread.

The user, 2026-10-06 00:23: 「中继每往群里发一条报警，就同时抄一份给 Mac…就是他发给群里的时候再发给我的电脑不就完了。」
A COS failure is one WARNING on ark.alertlog and never delays the group push.
"""
import io
import json
import logging
import sys
import time
import urllib.error
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import alertlog, errwatch, texts  # noqa: E402
from ark_relay.config import Config              # noqa: E402
from ark_relay.notify import Notifier           # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class FakeCos:
    host = "bucket.cos.ap-shanghai.myqcloud.com"

    def __init__(self):
        self.objects = {}
        self.puts = []
        self.fail = None
        self.delay = 0.0

    def authorization(self, method, key, now=None, ttl=3600):
        return f"sig-{method}-{key}"

    def get(self, cos, key):
        if self.fail:
            raise urllib.error.URLError(self.fail)
        return self.objects.get(key, b"")

    def put(self, cos, key, data):
        time.sleep(self.delay)
        self.puts.append(key)
        self.objects[key] = data


def lines(cos, key):
    return [json.loads(x) for x in cos.objects.get(key, b"").decode("utf-8").splitlines()]


# Real push texts.
ERR_BODY = texts.relay_error_body("ark.service", "AUTO-MAS 拉起后 45 秒内接口仍不通", "21:21")
# relay3.log:27539-27545, the 10-05 10:39 鸣潮 round that did not finish.
WW_BODY = ("OK-WW 2026-10-05/wuwa/OK-WW-05-39-25 有项目没干成：\n"
           "OK-WW 这一轮有 2 项没干成，但它自己没报错：\n"
           "· 残象聚落只刷指定点位（过滤生效）：日志里没有「nightmare nest: 只刷 […]」这一行：过滤没拿到点位名，按上游行为刷了全部\n"
           "· 周本领到了奖励：周本打了，但没有领奖那一步：奖励没拿到\n"
           "干成的：残象聚落没进别的点位、每日任务跑完、残象聚落、刷体力")

print("[一行的字段：ts（北京时间）、game、title、text、version、evidence_run]")
at = datetime.fromisoformat("2026-10-05T23:39:00+09:00")       # Tokyo 23:39 = Beijing 22:39, same day
row = alertlog.entry(texts.ROUND_INCOMPLETE, WW_BODY, "v20261005151027", now=at)
check("字段正好六个", sorted(row), sorted(["ts", "game", "title", "text", "version", "evidence_run"]))
check("北京时间", row["ts"], "2026-10-05 22:39:00")
check("鸣潮认得出", row["game"], "鸣潮")
check("运行编号取得出", row["evidence_run"], "2026-10-05/wuwa/OK-WW-05-39-25")
row2 = alertlog.entry(texts.RELAY_ERROR, ERR_BODY, "v1", now=at)
check("中继自己的报错：游戏=中继，运行编号空", (row2["game"], row2["evidence_run"]), ("中继", ""))
check("北京日期定对象名（东京 00:30 = 北京前一天 23:30）",
      alertlog.key_for(datetime.fromisoformat("2026-10-06T00:30:00+09:00")), "alerts/20261005.jsonl")

print("\n[读旧的、追加一行、写回；没有对象（404）就新建]")
cos = FakeCos()
alertlog.append(cos, row, cos.get, cos.put)
alertlog.append(cos, row2, cos.get, cos.put)
got = lines(cos, "alerts/20261005.jsonl")
check("两行都在、顺序对", [r["title"] for r in got], [texts.ROUND_INCOMPLETE, texts.RELAY_ERROR])
check("正文原样（含换行）", got[0]["text"], WW_BODY)


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


real_urlopen = alertlog.urllib.request.urlopen
seen = []


def fake_urlopen(req, timeout=None):
    seen.append((req.get_method(), req.full_url, dict(req.header_items())))
    if req.get_method() == "GET":
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
    return _Resp(b"")


alertlog.urllib.request.urlopen = fake_urlopen
try:
    check("404 当作空对象", alertlog.cos_get(cos, "alerts/20261006.jsonl"), b"")
    alertlog.cos_put(cos, "alerts/20261006.jsonl", b"{}\n")
finally:
    alertlog.urllib.request.urlopen = real_urlopen
check("PUT 带签名、不带 public-read（私有）",
      ("Authorization" in seen[-1][2], any(k.lower() == "x-cos-acl" for k in seen[-1][2])), (True, False))

print("\n[Notifier：走群的才抄送；抄送在推送之后、另起线程，COS 慢也不拖推送]")
cfg = Config()
n = Notifier(cfg)
pushed = []
n._fan_out = lambda title, body, **kw: (pushed.append(title) or (["企业微信机器人"], {}))
fake = FakeCos()
fake.delay = 0.8
n._cos = fake
real_get, real_put = alertlog.cos_get, alertlog.cos_put
alertlog.cos_get, alertlog.cos_put = fake.get, fake.put
try:
    t0 = time.monotonic()
    check("报警送达", n.send(texts.ROUND_INCOMPLETE, WW_BODY, alert=True), [])
    check("COS 慢 0.8 秒，推送不等它", time.monotonic() - t0 < 0.3)
    n.send("📋 日报", "正文", daily=True)
    n.send("ℹ️ 普通信息", "正文")
    n.send_group("📣 明天开卡池", "正文")
    time.sleep(2.0)
    today = alertlog.key_for(datetime.now(alertlog.BEIJING))
    titles = [r["title"] for r in lines(fake, today)]
    check("群报警和 send_group 抄了，日报和普通信息没抄", titles, [texts.ROUND_INCOMPLETE, "📣 明天开卡池"])

    print("\n[COS 坏了：只记一条 WARNING，报警照发，不回到 errwatch]")
    fake.delay, fake.fail = 0.0, "timed out"
    records = []

    class _Grab(logging.Handler):
        def emit(self, record):
            records.append(record)

    grab = _Grab()
    logging.getLogger("ark.alertlog").addHandler(grab)

    class _N:
        sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append(title)
            return []

    watcher_n = _N()
    import tempfile
    h = errwatch.install(watcher_n, lambda: False, state_dir=Path(tempfile.mkdtemp()), known={})
    check("报警照发", n.send(texts.RELAY_ERROR, ERR_BODY, alert=True), [])
    time.sleep(0.5)
    check("记了一条 WARNING", [r.levelname for r in records], ["WARNING"])
    check("errwatch 没把它当新报错", watcher_n.sent, [])
    logging.getLogger(errwatch.ARK).removeHandler(h)
    logging.getLogger("ark.alertlog").removeHandler(grab)
finally:
    alertlog.cos_get, alertlog.cos_put = real_get, real_put

print("\n[这台机器没配 COS：什么都不做]")
n2 = Notifier(cfg)
n2._fan_out = lambda title, body, **kw: (["企业微信机器人"], {})
n2._cos = False
check("照常送达", n2.send(texts.RELAY_ERROR, ERR_BODY, alert=True), [])

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
