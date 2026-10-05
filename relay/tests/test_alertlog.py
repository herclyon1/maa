"""Every group alarm is also kept in COS alerts/<Beijing YYYYMMDD>.jsonl, one JSON line each.

The user, 2026-10-06 00:23, asked for a copy to his Mac of every alarm the relay sends to
the group, at the moment it sends it (「中继每往群里发一条报警，就同时抄一份给 Mac」).
Fields exactly ts (Beijing, from UTC, whatever the machine's zone), game, title,
text, version, evidence_run; "" when unknown. The uploader is a fake here -
nothing in this file talks to COS.
"""
import io
import json
import logging
import os
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                  COS_SECRET_ID="", COS_SECRET_KEY="", COS_BUCKET="", COS_REGION="")
# The Mac is in Tokyo; the copy must not care.
os.environ.update(TZ="Asia/Tokyo")
time.tzset()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import alertlog, phone, texts  # noqa: E402
from ark_relay.config import Config  # noqa: E402
from ark_relay.notify import Notifier  # noqa: E402
from ark_relay.statestore import StateStore  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class FakeCos:
    """put/get the way alertlog.for_config wires phone.cos_put / cos_get."""

    def __init__(self):
        self.objects = {}
        self.puts = []
        self.put_fail = ""
        self.get_fail = ""
        self.delay = 0.0

    def put(self, key, data):
        time.sleep(self.delay)
        self.puts.append(key)
        if self.put_fail:
            return self.put_fail
        self.objects[key] = data
        return None

    def get(self, key):
        if self.get_fail:
            return None, self.get_fail
        return self.objects.get(key), ""


def lines(cos, key):
    return [json.loads(x) for x in cos.objects.get(key, b"").decode("utf-8").splitlines()]


def wait_puts(cos, n, secs=3.0):
    t0 = time.monotonic()
    while len(cos.puts) < n and time.monotonic() - t0 < secs:
        time.sleep(0.02)
    time.sleep(0.05)


# relay3.log:27539-27545, the 10-05 10:39 鸣潮 round that did not finish.
WW_BODY = ("OK-WW 2026-10-05/wuwa/OK-WW-05-39-25 有项目没干成：\n"
           "· 周本领到了奖励：周本打了，但没有领奖那一步：奖励没拿到\n"
           "干成的：每日任务跑完、刷体力")
END_BODY = texts.unresolved_head("终末地", "早班", "补跑也没成", "基质刷取",
                                 "https://ark-1250000000.cos.ap-shanghai.myqcloud.com/"
                                 "2026-10-05_endfield_MaaEnd-07-30-14/MaaEnd.zip")

print("[一行正好六个字段；ts 是北京时间，从 UTC 算，机器在东京也一样]")
at = datetime(2026, 10, 5, 14, 39, 0, tzinfo=timezone.utc)          # Beijing 22:39, Tokyo 23:39
r = alertlog.row(texts.ROUND_INCOMPLETE, WW_BODY, "20261005153900", now=at)
check("字段", list(r), ["ts", "game", "title", "text", "version", "evidence_run"])
check("北京时间", r["ts"], "2026-10-05 22:39:00")
check("鸣潮认得出", r["game"], "鸣潮")
check("运行编号", r["evidence_run"], "2026-10-05/wuwa/OK-WW-05-39-25")
check("正文原样（含换行）", r["text"], WW_BODY)
check("版本", r["version"], "20261005153900")
now_bj = datetime.now(timezone.utc).timestamp() + 8 * 3600
got = datetime.strptime(alertlog.row("x", "y")["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
check("不传时间：用当前 UTC + 8 小时（不是东京钟）", abs(got - now_bj) < 3)


def _raises(f):
    try:
        f()
    except ValueError:
        return True
    return False


check("裸时间（不知道时区）不收", _raises(lambda: alertlog.beijing(datetime(2026, 10, 5, 12, 0))))
r2 = alertlog.row(texts.RELAY_ERROR, texts.relay_error_body("ark.report", "日报没发出去", "21:21"), "", now=at)
check("中继自己的报错：游戏、运行编号、版本都空", (r2["game"], r2["evidence_run"], r2["version"]), ("", "", ""))
r3 = alertlog.row(texts.unresolved("终末地", "早班"), END_BODY, "v", now=at)
check("终末地认得出", r3["game"], "终末地")
check("证据链接里的运行编号也认得出", r3["evidence_run"], "2026-10-05/endfield/MaaEnd-07-30-14")
check("MAA 失败认成明日方舟", alertlog.row(texts.failed("MAA"), "", now=at)["game"], "明日方舟")
check("MaaEnd 不会被认成明日方舟", alertlog.row(texts.failed("MaaEnd"), "", now=at)["game"], "终末地")
check("标题没说、正文提到两个游戏：空", alertlog.row("早班 没有运行", "明日方舟 和 鸣潮 都没跑", now=at)["game"], "")
check("东京 00:30 = 北京前一天 23:30：放前一天的对象",
      alertlog.row("x", "", now=datetime(2026, 10, 5, 15, 30, tzinfo=timezone.utc))["ts"][:10], "2026-10-05")
check("对象名", alertlog.key_for("20261005"), "alerts/20261005.jsonl")

print("\n[本地先记一行，再把整天的文件 PUT 上去；第二条追加在后面]")
cos = FakeCos()
al = alertlog.AlertLog(TMP / "s1", put=cos.put, get=cos.get)
al.copy(texts.ROUND_INCOMPLETE, WW_BODY, "1", now=at).join(3)
al.copy(texts.unresolved("终末地", "早班"), END_BODY, "1", now=at).join(3)
got = lines(cos, "alerts/20261005.jsonl")
check("两行都在、顺序对", [x["title"] for x in got], [texts.ROUND_INCOMPLETE, texts.unresolved("终末地", "早班")])
check("每行都是这六个字段", all(list(x) == list(alertlog.FIELDS) for x in got))
check("本地也有这一天", (TMP / "s1" / "alerts" / "20261005.jsonl").exists())

print("\n[COS 写不进：行留在本地、只记一条 WARNING；下一条报警把前面的一起补上]")
records = []


class _Grab(logging.Handler):
    def emit(self, record):
        records.append(record)


grab = _Grab()
alertlog.log.addHandler(grab)
alertlog.log.setLevel(logging.INFO)
cos = FakeCos()
cos.put_fail = "回 503"
al = alertlog.AlertLog(TMP / "s2", put=cos.put, get=cos.get)
al.copy("⚠️ 一", "a", now=at).join(3)
al.copy("⚠️ 二", "b", now=at).join(3)
check("COS 上还没有", cos.objects, {})
check("只记了一条 WARNING（不是每条报警一条）", [x.levelname for x in records], ["WARNING"])
cos.put_fail = ""
al.copy("⚠️ 三", "c", now=at).join(3)
check("三条一起上去了", [x["title"] for x in lines(cos, "alerts/20261005.jsonl")], ["⚠️ 一", "⚠️ 二", "⚠️ 三"])
check("恢复时记一条 INFO", records[-1].levelname, "INFO")
al2 = alertlog.AlertLog(TMP / "s2", put=cos.put, get=cos.get)
n_puts = len(cos.puts)
al2.sync()
check("都上去了以后，开机补传什么都不做", len(cos.puts), n_puts)
alertlog.log.removeHandler(grab)

print("\n[本地没有这一天（状态目录被清过）：先读回 COS 上的，读不回来就不写，免得盖掉]")
cos = FakeCos()
cos.objects["alerts/20261005.jsonl"] = (json.dumps(alertlog.row("⚠️ 早上的", "", now=at), ensure_ascii=False)
                                        + "\n").encode("utf-8")
cos.get_fail = "timed out"
al = alertlog.AlertLog(TMP / "s3", put=cos.put, get=cos.get)
al.copy("⚠️ 晚上的", "", now=at).join(3)
check("读不回来：没有 PUT", cos.puts, [])
cos.get_fail = ""
al.sync()
check("读回来以后：早上的在前，晚上的在后", [x["title"] for x in lines(cos, "alerts/20261005.jsonl")],
      ["⚠️ 早上的", "⚠️ 晚上的"])

print("\n[Notifier：送到群的报警才抄；日报、普通信息、只记日志的、没送到的都不抄；COS 慢不拖推送]")
cfg = Config()
cfg.state_dir = TMP / "n1"
StateStore(cfg.state_dir).set("versions", "code", "20261005153900")
n = Notifier(cfg)
n._fan_out = lambda title, body, **kw: (["企业微信机器人"], {})
fake = FakeCos()
fake.delay = 0.8
n._alerts = alertlog.AlertLog(cfg.state_dir, put=fake.put, get=fake.get)
t0 = time.monotonic()
check("报警送达", n.send(texts.ROUND_INCOMPLETE, WW_BODY, alert=True), [])
check("COS 慢 0.8 秒，推送不等它", time.monotonic() - t0 < 0.5)
n.send("📋 10-05 · 全绿 ✅", "正文", daily=True)
n.send("🆕 游戏更新", "正文")
n.send("🔄 中继已更新", "正文", alert=True)
n.send_group("📣 明天开卡池", "正文")
fake.delay = 0.0
wait_puts(fake, 2)
time.sleep(0.3)
key = alertlog.key_for(alertlog.beijing().strftime("%Y%m%d"))
got = lines(fake, key)
check("群报警和 send_group 抄了，日报、普通信息、只记日志的没抄", [x["title"] for x in got],
      [texts.ROUND_INCOMPLETE, "📣 明天开卡池"])
check("版本是这台机器正在跑的代码版本", got and got[0]["version"], "20261005153900")
n._fan_out = lambda title, body, **kw: ([], {"企业微信机器人": "60020"})
n.send("❌ OK-WW 失败", "没送到", alert=True)
time.sleep(0.3)
check("没送到的报警不抄（调用方每轮重发，抄了就是一串重复）",
      [x["title"] for x in lines(fake, key)][-1], "📣 明天开卡池")

print("\n[这台机器没配 COS：照常送达，只在本地记]")
cfg2 = Config()
cfg2.state_dir = TMP / "n2"
n2 = Notifier(cfg2)
n2._fan_out = lambda title, body, **kw: (["企业微信机器人"], {})
check("照常送达", n2.send(texts.RELAY_ERROR, "x", alert=True), [])
check("没有上传器", n2.alert_log()._put, None)
check("本地有一行", len(list((TMP / "n2" / "alerts").glob("*.jsonl"))), 1)

print("\n[真的 PUT：私有（不带 public-read），404 当成还没有]")


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


seen = []


def fake_urlopen(req, timeout=None):
    seen.append((req.get_method(), req.full_url, {k.lower(): v for k, v in req.header_items()}))
    if req.get_method() == "GET":
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
    return _Resp(b"")


class _Cos:
    host = "bucket.cos.ap-shanghai.myqcloud.com"

    def authorization(self, method, key, now=None, ttl=3600):
        return f"sig-{method}-{key}"


real = phone.urllib.request.urlopen
phone.urllib.request.urlopen = fake_urlopen
try:
    check("404：没有这个对象，不算出错", phone.cos_get(_Cos(), "alerts/20261006.jsonl", 5), (None, ""))
    check("私有 PUT 成功", phone.cos_put(_Cos(), "alerts/20261006.jsonl", b"{}\n", 5, public=False,
                                    content_type="application/x-ndjson; charset=utf-8"), None)
    check("不带 x-cos-acl", "x-cos-acl" in seen[-1][2], False)
    check("带签名", seen[-1][2].get("authorization"), "sig-PUT-alerts/20261006.jsonl")
    phone.cos_put(_Cos(), "state/x.json", b"{}", 5)
    check("手机状态照旧 public-read", seen[-1][2].get("x-cos-acl"), "public-read")
finally:
    phone.urllib.request.urlopen = real

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
