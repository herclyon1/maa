"""手机页那一份状态包：形状、大小、去重、额度。全程注入假网络。

这个文件防的是**一类损失：用户唯一的日常操作界面变成一张白纸**，
而机器这头一片绿——它以为自己发出去了。

具体的坏法都出过：
* `state_payload` 少一个键，页面那一段就整块不渲染（2026-09-02 晚 AUTO-MAS 没开着，
  页面把空配置当成真配置显示，用户的评价是「一坨屎」）；
* 单条消息超过 ntfy 上限会被**截断**，手机上 JSON.parse 直接失败，
  表现成「状态永远不更新」，于是被判成关机中（2026-08-31 真发生过）；
* 已经执行过的指令再执行一遍——同一条「现在跑一趟」跑两趟，烧掉一趟的理智；
* PIN 不对的消息被当成指令执行；
* 心跳盲发：匿名 ntfy 每 IP 每天 250 条，闷头跳就把状态推送和指令应答一起挤掉。

`phone.py` 25 个函数里 16 个从来没被执行过，上面这些没有一条被钉住过。
已有的 test_phone.py（PIN/时效）、test_phone_gzip.py（pack/unpack 压缩往返）、
test_heartbeat.py（有人看才跳）覆盖的部分这里不重复。
"""
import io
import json
import sys
import time
import types
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay import phone

PIN = "8964"
fails: list[str] = []


def bare(bodies):
    """The command bodies without phone.stamp's "_meta" (when / how it arrived)."""
    return [{k: v for k, v in b.items() if k != "_meta"} for b in bodies]


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
    if not ok:
        fails.append(label)


# ---------------------------------------------------------------- 假网络
#
# phone.py 里所有网络都走 `urllib.request.*`。整块换掉，测试进程绝不出网。

class FakeResp:
    def __init__(self, body: bytes = b"", status: int = 200):
        self.status = status
        self._body = body
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(io.BytesIO(self._body))

    def read(self):
        return self._body

    def close(self):
        self.closed = True


class FakeNet:
    """Records every request; hands back canned responses."""

    def __init__(self):
        self.sent: list[tuple[str, bytes, dict]] = []
        self.queue: list = []

    def urlopen(self, req, timeout=None):
        self.sent.append((req.full_url, req.data or b"", dict(req.headers)))
        if not self.queue:
            return FakeResp(b"")
        nxt = self.queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def with_net(net, fn):
    saved = phone.urllib
    phone.urllib = types.SimpleNamespace(
        request=types.SimpleNamespace(Request=saved.request.Request,
                                      urlopen=net.urlopen),
        error=urllib.error)
    try:
        return fn()
    finally:
        phone.urllib = saved


# ---------------------------------------------------------------- state_payload

print("[state_payload 的形状：手机页靠这几个键渲染，少一个就是一块空白]")

FULL = {
    "MAA": {"关卡": "AT-4", "理智药": 0, "剿灭": "Close", "作战开关": True,
            "Stage": "AT-4", "MedicineNumb": 0, "StageMode": "Fixed",
            "RunTimesLimit": 3, "这个手机上不显示": "别发过去"},
    "MaaEnd": {"Stage": "藏剑谷", "MedicineNumb": 2},
    "OK-WW": {"WhichToFarm": "残象聚落"},
    "ark-relay": "跑着",
    "程序": {"MAA.exe": True, "Endfield.exe": False, "MaaEnd.exe": True},
    "队列": {"早班": {"定时": True, "脚本": ["MAA", "MaaEnd", "OK-WW"]},
             "晚班": {"定时": True, "脚本": ["MAA"]}},
    "OK-WW配置": {"一大坨": "不该出现在手机包里"},
}

STATE = tmpdir()
AUTOMAS = tmpdir()

# A stand-in for AUTO-MAS's own models file: this is where the Chinese labels on
# the phone come from (the user, 2026-08-31: the UI is all Chinese, the labels
# must be read from upstream, never invented here).
models = AUTOMAS / "app" / "models"
models.mkdir(parents=True)
(models / "user_config.py").write_text('''
class MaaUserConfig(ConfigBase):
    def __init__(self):
        ## 刷取关卡
        self.Stage = ConfigItem(
            "Info", "Stage", "AT-4"
        )
        ## 选关模式
        self.StageMode = ConfigItem(
            "Info", "StageMode", "Fixed", OptionsValidator(["Fixed", "Auto"])
        )
        ## 失败重试上限
        self.RunTimesLimit = ConfigItem(
            "Info", "RunTimesLimit", 3
        )


class OkwwUserConfig(ConfigBase):
    def __init__(self):
        ## 刷什么
        self.WhichToFarm = ConfigItem(
            "Task", "WhichToFarm", "", OptionsValidator(["残象聚落", "无音区"])
        )
''', encoding="utf-8")

cfg = types.SimpleNamespace(automas_dir=str(AUTOMAS),
                            maaend_dir=str(tmpdir()),
                            okww_dir=str(tmpdir()))

from ark_relay import plan, snapshot  # noqa: E402

saved_read, saved_plan = snapshot.read, plan.next_plan
snapshot.read = lambda: dict(FULL)
plan.next_plan = lambda automas_dir: "明天：早班 MAA/MaaEnd/OK-WW"
try:
    out = phone.state_payload(cfg, STATE)
finally:
    snapshot.read, plan.next_plan = saved_read, saved_plan

for key in ("at", "config", "run", "queues", "relay", "options", "master", "plan"):
    check(f"有 {key} 这个键", key in out, True)
check("at 是秒级时间戳（页面靠它算「多久以前」和挑最新的一份）",
      isinstance(out["at"], int) and abs(out["at"] - time.time()) < 5, True)

check("只发明日方舟那一段（另两个游戏走母本，发 MAS 的值会误导人）",
      sorted(out["config"]), ["MAA"])
check("手机上要显示的字段留下",
      {k: out["config"]["MAA"][k] for k in ("关卡", "理智药", "Stage")},
      {"关卡": "AT-4", "理智药": 0, "Stage": "AT-4"})
check("手机上不显示的字段不发（整包塞不下）",
      "这个手机上不显示" in out["config"]["MAA"], False)
check("快照里的大块头没混进来（OK-WW配置/进程原文）",
      [k for k in out if k in ("OK-WW配置", "程序")], [])

check("run 里给出服务状态", out["run"]["服务"], "跑着")
check("run 里只列真在跑的进程", sorted(out["run"]["在跑的"]), ["MAA.exe", "MaaEnd.exe"])

check("queues 是列表，每项带「名」（页面用它做班次下拉）",
      [q["名"] for q in out["queues"]], ["早班", "晚班"])
check("queues 每项保留原有字段", out["queues"][0]["脚本"],
      ["MAA", "MaaEnd", "OK-WW"])

from ark_relay import modes as _modes  # noqa: E402
_modes._store(STATE).set("modes", "debug_until", "2000-01-01 00:00")
snapshot.read, plan.next_plan = (lambda: dict(FULL)), (lambda automas_dir: "")
try:
    check("调试模式过了结束时间就发空串（手机上不再显示「开着」）",
          phone.state_payload(cfg, STATE)["relay"]["调试模式"], "")
    _modes._store(STATE).set("modes", "debug_until", "2999-01-01 00:00")
    check("调试模式还在期内照发结束时间",
          phone.state_payload(cfg, STATE)["relay"]["调试模式"], "2999-01-01 00:00")
finally:
    snapshot.read, plan.next_plan = saved_read, saved_plan
    _modes._store(STATE).pop("modes", "debug_until")

for key in ("调试模式", "下次别关机", "周本", "周常"):
    check(f"relay 里有「{key}」", key in out["relay"], True)
check("relay.周常 三件套齐全（页面读的是这三个）",
      sorted(out["relay"]["周常"]), sorted(["剿灭", "周常乐园", "周本"]))
check("「下次别关机」是布尔，页面拿它决定按钮文案",
      isinstance(out["relay"]["下次别关机"], bool), True)

check("中文标注按「脚本|路径」发过去，正是页面查表用的键",
      out["options"]["_labels"].get("MAA|Info.Stage"), "刷取关卡")
check("另一个脚本的标注也读得到",
      out["options"]["_labels"].get("OK-WW|Task.WhichToFarm"), "刷什么")
check("不在 SHOWN 里的标注不发（154 条全发会撑爆单条消息）",
      "MAA|Info.RunTimesLimit" in out["options"]["_labels"], False)

check("plan 发出去了", out["plan"].startswith("明天："), True)
for game in ("MAA", "MaaEnd", "OK-WW"):
    check(f"master 里有 {game} 这一段", game in out["master"], True)

print("\n[快照读不到时：明说读不到，其余照发——页面才能标「这是上次的」]")
snapshot.read = lambda: (_ for _ in ()).throw(ConnectionError("AUTO-MAS 没开"))
plan.next_plan = lambda automas_dir: (_ for _ in ()).throw(OSError("读不了"))
try:
    broken = phone.state_payload(cfg, STATE)
finally:
    snapshot.read, plan.next_plan = saved_read, saved_plan

check("config 里留一条 _错误，页面据此弹警告",
      list(broken["config"]), ["_错误"])
check("_错误 里带上异常类型，不是干巴巴一句「出错」",
      broken["config"]["_错误"].startswith("ConnectionError:"), True)
check("plan 读不到时给空串，不是缺键", broken["plan"], "")
# 快照那一段全靠 AUTO-MAS，它没开着就什么都读不到；页面对 run/queues 缺失是
# 容错的（`(snap && snap.queues) || []`），但下面这几个键页面直接取值，必须还在。
for key in ("at", "config", "relay", "options", "master", "plan"):
    check(f"快照炸了，{key} 还在", key in broken, True)
check("relay 那一段和快照无关，照样有内容",
      "下次别关机" in broken["relay"], True)

# ---------------------------------------------------------------- publish

print("\n[publish：什么都不砍。通道不是 4096，那只是「转成附件」的分界]")
# Measured 2026-09-09: a 9046-byte body posts fine, ntfy stores it as an attachment
# and hands back a URL that returns it byte-for-byte. 4096 was treated as a hard
# ceiling here and the state was trimmed section by section to fit - features thrown
# away for a problem that did not exist, and when trimming was not enough the message
# went out unparseable and the page kept showing values almost an hour old.

mb = phone.Mailbox("topic-abc", PIN, tmpdir())
check("有 topic 有 pin 才算启用", mb.enabled, True)
check("没配 topic 就是没启用", phone.Mailbox("", PIN, tmpdir()).enabled, False)
check("没配 pin 就是没启用", phone.Mailbox("t", "", tmpdir()).enabled, False)

net = FakeNet()
off = phone.Mailbox("", "", tmpdir())
check("没启用时 publish 直接返回 False", with_net(net, lambda: off.publish({"at": 1})), False)
check("没启用时一个网络请求都没发", net.sent, [])

net = FakeNet()
net.queue.append(FakeResp(b"ok"))
check("小状态包发得出去", with_net(net, lambda: mb.publish({"at": 1, "x": "y"})), True)
url, body, headers = net.sent[0]
check("发到自己的 topic", url, f"{phone.NTFY}/topic-abc")
check("标题标明是 state（页面靠 kind 区分状态和指令）",
      headers.get("Title"), "state")
check("小包保持明文", "body" in json.loads(body.decode()), True)
check("收回来解得开且内容一致",
      phone.unpack(PIN, body.decode())["body"], {"at": 1, "x": "y"})

big = {"at": 1,
       "options": {"_labels": {f"MAA|Info.键{i}": f"中文标注{i}" for i in range(150)}},
       "plan": "明天早班要跑的东西" * 40}
check("这份状态明文确实超过内联分界",
      len(phone.pack(PIN, big, "state").encode()) > phone.Mailbox.INLINE_MAX, True)

net = FakeNet()
net.queue.append(FakeResp(b"ok"))
check("超线的状态照样发得出去", with_net(net, lambda: mb.publish(big)), True)
wire = net.sent[0][1]
check("能压进内联就压，省手机一次取附件", "gz" in json.loads(wire.decode()), True)
check("压缩没丢东西：options 和 plan 都还在",
      phone.unpack(PIN, wire.decode())["body"], big)

# Random text does not compress. This used to be the path where fields got dropped;
# now it simply goes out whole and ntfy turns it into an attachment.
import random  # noqa: E402

random.seed(826)
noise = "".join(random.choice("0123456789abcdef") for _ in range(20000))



payload = {"at": 1, "plan": noise[:5000], "options": {"x": noise[5000:15000]},
           "config": {"MAA": {"关卡": "AT-4"}}}
net = FakeNet()
for _ in range(10):
    net.queue.append(FakeResp(b"ok"))
with_net(net, lambda: mb.publish(payload))
wires = [s[1] for s in net.sent]
check("压不下去就切成多条，而不是走附件", len(wires) > 1, True)
# Attachments expire after three hours; the state pushed before the machine shuts
# down at night is exactly the one read the next morning. Ordinary messages last
# twelve hours, so oversized states are split into those.
check("每一条都在内联分界之内（不会被转成附件）",
      max(len(w) for w in wires) <= phone.Mailbox.INLINE_MAX, True)
parts = [json.loads(w.decode()) for w in wires]
check("每条都带同一个 sid", len({p["sid"] for p in parts}), 1)
check("序号从 0 连到 n-1", [p["i"] for p in parts], list(range(len(parts))))
check("每条都写明总共几条", {p["n"] for p in parts}, {len(parts)})
check("每条的 pin 都在（半路截获也认不出内容）", {p["pin"] for p in parts}, {PIN})

import base64 as _b64, gzip as _gz  # noqa: E402

blob = "".join(p["gzp"] for p in sorted(parts, key=lambda x: x["i"]))
back = json.loads(_gz.decompress(_b64.b64decode(blob)).decode("utf-8"))
check("拼起来一个字段都不少", back, payload)
check("明日安排还在", "plan" in back, True)
check("选项表还在", "options" in back, True)

print("\n[少一片就当没有：绝不把半份状态当完整的显示]")
short = parts[:-1]
blob2 = "".join(p["gzp"] for p in sorted(short, key=lambda x: x["i"]))
broke = False
try:
    _gz.decompress(_b64.b64decode(blob2 + "=" * (-len(blob2) % 4)))
except Exception:  # noqa: BLE001 - any failure to decode is the point
    broke = True
check("缺一片就解不开，不会解出半份", broke, True)
check("总数写在每一片上，凑没凑齐一看便知", short[0]["n"] > len(short), True)

# One retry after a network exception (2026-09-18 19:27: the second of two boot
# pieces hit a read timeout once, and the phone showed a 13-minute-old state until
# shutdown). No wait in tests.
mb.RETRY_AFTER = 0
net = FakeNet()
net.queue.append(urllib.error.URLError("网断了"))
check("断一次、第二次通了：算发出去了",
      with_net(net, lambda: mb.publish({"at": 1})), True)
check("确实发了两次", len(net.sent), 2)
net = FakeNet()
net.queue += [TimeoutError("读超时"), urllib.error.URLError("网断了")]
check("连断两次返回 False，不抛（调用方才能去别的渠道)",
      with_net(net, lambda: mb.publish({"at": 1})), False)
check("只试两次，不无限重试", len(net.sent), 2)
net = FakeNet()
net.queue.append(FakeResp(b"", status=500))
check("服务器 500 也算没发出去",
      with_net(net, lambda: mb.publish({"at": 1})), False)
check("服务器答了话就不重复发", len(net.sent), 1)

# ---------------------------------------------------------------- fetch

print("\n[fetch：PIN 不对的不执行、状态回音不当指令、执行过的不再执行一遍]")


def ntfy_lines(*items) -> bytes:
    out = []
    for mid, msg in items:
        out.append(json.dumps({"id": mid, "event": "message", "message": msg},
                              ensure_ascii=False))
    return ("\n".join(out) + "\n").encode()


MB_STATE = tmpdir()
mb2 = phone.Mailbox("topic-abc", PIN, MB_STATE)
lines = ntfy_lines(
    ("m1", phone.pack(PIN, {"action": "run_now", "queue": "早班"})),
    ("m2", phone.pack("0000", {"action": "run_now", "queue": "晚班"})),
    ("m3", phone.pack(PIN, {"at": 1}, "state")),
    ("m4", "这不是 JSON"),
    ("m5", phone.pack(PIN, {"action": "skip_shutdown"})),
)
lines += json.dumps({"event": "keepalive"}).encode() + b"\n"
net = FakeNet()
net.queue.append(FakeResp(lines))
got = with_net(net, lambda: mb2.fetch())
check("只把 PIN 对的、kind=cmd 的当指令",
      bare(got), [{"action": "run_now", "queue": "早班"}, {"action": "skip_shutdown"}])
check("每条带上从哪来（_meta：信封 ts、ntfy id、开机积压）",
      [(b["_meta"]["ntfy_id"], b["_meta"]["via"], isinstance(b["_meta"]["sent"], int)) for b in got],
      [("m1", "backlog", True), ("m5", "backlog", True)])
check("请求里带上 poll=1（一次取完，不是轮询）",
      "poll=1" in net.sent[0][0], True)

net = FakeNet()
net.queue.append(FakeResp(lines))
check("同一批消息第二次取：一条都不再执行（否则同一条指令跑两趟）",
      with_net(net, lambda: mb2.fetch()), [])
check("记住的只有指令的 id，状态和坏消息不占名额（2026-09-15 名额被 watch 和状态挤满，旧指令重放）",
      sorted(mb2._seen), ["m1", "m5"])
check("名额够一个早上的 watch 续租（8 分钟一条）用两周", phone.SEEN_KEEP >= 2000, True)

net = FakeNet()
net.queue.append(FakeResp(lines))
check("换个新实例（下次开机）照样记得已经执行过",
      with_net(net, lambda: phone.Mailbox("topic-abc", PIN, MB_STATE).fetch()), [])

net = FakeNet()
net.queue.append(FakeResp(lines + ntfy_lines(
    ("m9", phone.pack(PIN, {"action": "debug_mode"})))))
check("同一批里新来的那条要执行",
      bare(with_net(net, lambda: mb2.fetch())), [{"action": "debug_mode"}])

net = FakeNet()
net.queue.append(urllib.error.URLError("取不到"))
check("取不到就返回空表，不抛", with_net(net, lambda: mb2.fetch()), [])

net = FakeNet()
check("没启用的信箱不取也不联网",
      (with_net(net, lambda: off.fetch()), net.sent), ([], []))

# ---------------------------------------------------------------- listen

print("\n[listen：长连接上收到的指令，同样要过 PIN 和去重]")

got: list[dict] = []
mb3 = phone.Mailbox("topic-abc", PIN, tmpdir())
stream = ntfy_lines(
    ("s1", phone.pack("9999", {"action": "run_now"})),
    ("s2", phone.pack(PIN, {"at": 1}, "state")),
    ("s3", phone.pack(PIN, {"action": "run_now", "queue": "早班"})),
    ("s3", phone.pack(PIN, {"action": "run_now", "queue": "早班"})),
)
net = FakeNet()
net.queue.append(FakeResp(stream))
rounds = {"n": 0}


def stop_after_first():
    # False while the stream is being consumed, True once it is exhausted.
    return rounds["n"] > 0 and not net.queue


def on_cmd(body):
    got.append(body)
    rounds["n"] += 1


with_net(net, lambda: mb3.listen(on_cmd, stop_after_first))
check("PIN 不对的没被执行，状态回音没被执行，重复 id 只执行一次",
      bare(got), [{"action": "run_now", "queue": "早班"}])
check("长连接收到的标 live", [b["_meta"]["via"] for b in got], ["live"])
check("订阅带 since，重连时补得回漏掉的（不带就永远丢）",
      "since=" in net.sent[0][0], True)

print("\n[close：停服务时要能立刻掐断连接，不然 STOP_PENDING 卡满 30 秒]")
r = FakeResp(b"")
mb3._resp = r
mb3.close()
check("连接被关掉", r.closed, True)
check("关完把引用清掉", mb3._resp, None)
mb3.close()
check("重复关不抛", True, True)

# ---------------------------------------------------------------- 心跳额度

print("\n[心跳额度：ntfy 每 IP 每天 250 条，超了要放慢而不是继续闷头跳]")

HB_STATE = tmpdir()
posts: list[bytes] = []
hb = phone.Heartbeat("topic-abc", HB_STATE, post=lambda p, t: posts.append(p))

check("没人看的时候不算在线（租约没开）", hb.watched(), False)
hb.watch()
check("说了「我在看」就在租约内", hb.watched(), True)
hb._lease = time.time() - 1
check("租约过期就不再跳（没人看时一条都不发）", hb.watched(), False)

check("没跳过时今天是 0", hb.sent_today(), 0)
for _ in range(3):
    hb.beat()
check("跳一次记一次", hb.sent_today(), 3)
check("没到快档线用 30 秒间隔", hb.interval(), phone.HEARTBEAT_SEC)

# The tiers follow everything sent today, not beats alone: on 10-02 the beat
# counter said 196, nobody counted the 4-piece states, and 248 hit the 250.
hb.quota.add("state", phone.HB_FAST_UNTIL - 3 - 1)
check("差一条到快档线，还是快的", hb.interval(), phone.HEARTBEAT_SEC)
hb.quota.add("state")
check("状态片也算进去：到快档线就放慢到 5 分钟", hb.interval(), phone.HB_SLOW_SEC)
hb.quota.add("state", phone.HB_SLOW_UNTIL - phone.HB_FAST_UNTIL)
check("到慢档线再放慢到 30 分钟", hb.interval(), phone.HB_CRAWL_SEC)
check("三档线都在 250 之内、从快到慢", 0 < phone.HB_FAST_UNTIL < phone.HB_SLOW_UNTIL < phone.NTFY_DAILY_LIMIT, True)
check("慢档之后至少给状态留 60 条（15 份 4 片的状态）",
      phone.NTFY_DAILY_LIMIT - phone.HB_SLOW_UNTIL >= 60, True)
check("放慢档确实慢一个量级",
      phone.HB_SLOW_SEC >= 10 * phone.HEARTBEAT_SEC, True)

qf = hb.quota._file()
qf.write_text("这不是 JSON", encoding="utf-8")
check("账本坏了当 0，不抛（抛了整个心跳线程就死了）", (hb.sent_today(), hb.quota.total()), (0, 0))
qf.unlink()
check("账本没了当 0", hb.quota.total(), 0)
# ntfy's day resets at midnight UTC (docs.ntfy.sh/config,
# visitor-message-daily-limit) = 08:00 Beijing; keyed by the local date, 00-08
# would land on the wrong day.
from datetime import datetime as _dt, timezone as _tz  # noqa: E402
_bj8 = _dt(2026, 10, 2, tzinfo=_tz.utc).timestamp()   # 2026-10-02 08:00 Beijing = 00:00 UTC
check("北京 07:59 还算前一个 ntfy 日", phone.Quota.day(_bj8 - 60), "2026-10-01")
check("北京 08:00 起算新的一天", phone.Quota.day(_bj8), "2026-10-02")
check("账本按 UTC 日期分文件", phone.Quota.day() in qf.name, True)
hb.quota.add("hb", 2)
hb.quota.mark_full()
check("full 标记不算进条数", hb.quota.total(), 2)

dead = phone.Heartbeat("topic-abc", tmpdir(),
                       post=lambda *_: (_ for _ in ()).throw(OSError("网断了")))
check("发失败返回 False", dead.beat(), False)
check("发失败不许记数（否则网一断就自己把额度耗光）", dead.sent_today(), 0)

full_posts = []
fullhb = phone.Heartbeat("t", tmpdir(), post=lambda p, t: full_posts.append(p))
fullhb.quota.mark_full()
check("ntfy 说过今天额度用完（42908）：心跳不再去撞", (fullhb.beat(), full_posts), (False, []))

# ---- The beat has to carry the cadence it is beating at ----
# The page decides "no heartbeat for a while = powered off" from a fixed window.
# Once the relay drops to one beat every 5 minutes, that verdict is wrong for
# three and a half minutes out of every five - a red 「关机中」 while the queue
# is running. The page cannot guess the cadence; this message is the only
# place it can learn it.
_sent = []
_hb = phone.Heartbeat("t", tmpdir(), post=lambda payload, title: _sent.append(payload))
check("正常节奏报 30", (_hb.beat(), _sent[-1]), (True, b"hb 30"))
_hb.quota.add("state", phone.HB_FAST_UNTIL)
check("过了快档线报 300", (_hb.beat(), _sent[-1]), (True, b"hb 300"))
_hb.quota.add("state", phone.HB_SLOW_UNTIL)
check("过了慢档线报 1800", (_hb.beat(), _sent[-1]), (True, b"hb 1800"))
check("报的就是 interval() 说的那个",
      _sent[-1].decode(), f"hb {_hb.interval()}")

# ---------------------------------------------------------------- state pieces in the ledger, no retry on 429

print("\n[状态每一片都记进今天的账；429 不重试，一片失败剩下的不发]")


def http_error(code: int, ntfy_code: int, text: str):
    body = json.dumps({"code": ntfy_code, "http": code, "error": text}).encode()
    return urllib.error.HTTPError("https://ntfy.sh/x", code, "Too Many Requests", {}, io.BytesIO(body))


QSTATE = tmpdir()
qmb = phone.Mailbox("topic-abc", PIN, QSTATE)
qmb.RETRY_AFTER = 0
net = FakeNet()
with_net(net, lambda: qmb.publish(payload))      # the incompressible multi-piece state from above
n_pieces = len(net.sent)
check("每一片都记进今天的账", qmb.quota.count("state"), n_pieces)
check("心跳和状态共用一本账（同一个 state 目录）",
      phone.Heartbeat("topic-abc", QSTATE).quota.total(), n_pieces)

net = FakeNet()
net.queue.append(http_error(429, 42908, "limit reached: daily message quota reached"))
check("今天额度满：这份状态算没发出去", with_net(net, lambda: qmb.publish(payload)), False)
check("第一片被拒，剩下的片不再发（缺一片手机也拼不起来）", len(net.sent), 1)
check("429 不重试（10-02 晚上 52 片每片都白试了两次）", len(net.sent), 1)
check("42908 记成「今天满了」，心跳就不去撞", qmb.quota.full(), True)
check("被拒的不记账", qmb.quota.count("state"), n_pieces)

RSTATE = tmpdir()
rmb = phone.Mailbox("topic-abc", PIN, RSTATE)
net = FakeNet()
net.queue.append(http_error(429, 42901, "limit reached: too many requests"))
with_net(net, lambda: rmb.publish({"at": 1}))
check("请求太密（42901，几秒就回来）不当成今天满了", rmb.quota.full(), False)

# ---------------------------------------------------------------- refreshes already answered

print("\n[刷新：已经有一份状态答过它，就不再发一份（一份 4 条）]")

pushed: list[str] = []
pusher = phone.StatePusher(lambda why: pushed.append(why) or True)
check("还没发过状态：刷新照常答", pusher.answered(time.time()), False)
pusher("开机")
t_done = pusher._done
check("开机那份发出去了", pushed, ["开机"])
check("关机期间按的刷新（开机读积压时才到）：开机那份已经答了",
      pusher.answered(t_done - 3 * 3600), True)
check("App 4 秒后补的那次刷新：刚发完的那份答了",
      pusher.answered(t_done + 4), True)
check("窗口之内不重发", pusher.answered(t_done + phone.REFRESH_ANSWERED_SEC), True)
check("窗口之外照常答", pusher.answered(t_done + phone.REFRESH_ANSWERED_SEC + 1), False)
check("不知道什么时候问的：按现在算", pusher.answered(None), True)
check("窗口比页面和 App 订阅时回看的 30 秒短（since=30s），发过的那份一定回放得到",
      phone.REFRESH_ANSWERED_SEC < 30, True)
pusher("改完配置")
check("改完配置从不省：它带着页面要看的改动", pushed, ["开机", "改完配置"])

failed = phone.StatePusher(lambda why: False)
failed("开机")
check("没发出去的那份不算答过", failed.answered(time.time()), False)

print("\n[开机读积压：每条指令不再各发一份状态，读完合成一份]")
pushed.clear()
with pusher.held():
    pusher("改完配置")
    pusher("改完配置")
    pusher("红按钮")
    check("积压读着的时候一份都不发", pushed, [])
check("读完合成一份", len(pushed), 1)
check("合成的那份写清是哪几种、几次", pushed[0], "改完配置、红按钮（3 次合成一次）")
pushed.clear()
with pusher.held():
    pass
check("积压里没有要发的：一份都不多发", pushed, [])

# ---------------------------------------------------------------- a whole day's count

print("\n[一天的账：照 10-02 那样开着 App 测一晚上，也落在 250 以内]")
# The real state size: 43 KB on 10-02, 13003 bytes gzipped, 4 pieces
# (relay.log 10-02 17:02:18, 「状态 43465 字节，压缩到 13003 字节」 / 「切成 4 条」).
import os as _os  # noqa: E402
_big = {"at": 1, "options": {"x": _b64.b64encode(_os.urandom(9600)).decode()}}   # incompressible; ~13 KB as gzip+base64
_net = FakeNet()
with_net(_net, lambda: phone.Mailbox("t", PIN, tmpdir()).publish(_big))
PIECES = len(_net.sent)
check("一份 13 KB 的状态是 4 片（和线上一样）", PIECES, 4)

day = phone.Heartbeat("t", tmpdir(), post=lambda p, t: None)
states = [0]


def push_state_sim():
    states[0] += 1
    day.quota.add("state", PIECES)


# 10-02's day: two boots and one shutdown state; from 17:00 the App stays open
# for 4 hours (a watch every 8 minutes); 21 refresh presses, each re-asked by
# the App 4 s later (answered once); 5 config changes.
for _ in range(3):
    push_state_sim()
OPEN_S = 4 * 3600
refresh_at = {int(i * OPEN_S / 21) for i in range(21)}
config_at = {int((i + 0.5) * OPEN_S / 5) for i in range(5)}
last_beat = -10 ** 9
for t in range(OPEN_S):
    if t in refresh_at or t in config_at:
        push_state_sim()
    if t - last_beat >= day.interval():
        day.quota.add("hb")
        last_beat = t
push_state_sim()          # before shutdown
total = day.quota.total()
print(f"    （模拟：{states[0]} 份状态 × {PIECES} 片 + {day.quota.count('hb')} 跳 = {total} 条）")
check("整天落在 250 以内，还留着至少 20 条余量", total <= phone.NTFY_DAILY_LIMIT - 20, True)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
