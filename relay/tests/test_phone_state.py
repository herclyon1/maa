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
    "进程": {"MAA.exe": True, "Endfield.exe": False, "MaaEnd.exe": True},
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
      [k for k in out if k in ("OK-WW配置", "进程")], [])

check("run 里给出服务状态", out["run"]["服务"], "跑着")
check("run 里只列真在跑的进程", sorted(out["run"]["在跑的"]), ["MAA.exe", "MaaEnd.exe"])

check("queues 是列表，每项带「名」（页面用它做班次下拉）",
      [q["名"] for q in out["queues"]], ["早班", "晚班"])
check("queues 每项保留原有字段", out["queues"][0]["脚本"],
      ["MAA", "MaaEnd", "OK-WW"])

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

print("\n[publish：宁可压缩，也不静默砍掉功能；砍了要说出来]")

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
check("这份状态明文确实超线",
      len(phone.pack(PIN, big, "state").encode()) > phone.Mailbox.MAX_BODY, True)

net = FakeNet()
net.queue.append(FakeResp(b"ok"))
check("超线的状态照样发得出去", with_net(net, lambda: mb.publish(big)), True)
wire = net.sent[0][1]
check("超线时改走压缩", "gz" in json.loads(wire.decode()), True)
check("压完在上限之内（超了就会被截断，手机上解析失败）",
      len(wire) <= phone.Mailbox.MAX_BODY, True)
check("压缩没丢东西：options 和 plan 都还在",
      phone.unpack(PIN, wire.decode())["body"], big)

# Random text does not compress; this is the path where fields really do get
# dropped - and the point is that what goes out is still parseable JSON.
import random  # noqa: E402

random.seed(826)
noise = "".join(random.choice("0123456789abcdef") for _ in range(20000))


def publish_and_read(body):
    net = FakeNet()
    net.queue.append(FakeResp(b"ok"))
    with_net(net, lambda: mb.publish(body))
    wire = net.sent[0][1]
    return wire, phone.unpack(PIN, wire.decode())


wire, sent = publish_and_read(
    {"at": 1, "plan": noise[:5000], "options": {"x": "小"},
     "config": {"MAA": {"关卡": "AT-4"}}})
check("压不下去时砍字段，但发出去的仍是完整 JSON（手机上解析得开）",
      sent is not None, True)
check("砍完在上限之内", len(wire) <= phone.Mailbox.MAX_BODY, True)
check("先砍 plan；砍到装得下就停手，选项表能留就留",
      ("plan" in sent["body"], "options" in sent["body"]), (False, True))
check("配置这种要紧的一个字段都不砍",
      sent["body"].get("config"), {"MAA": {"关卡": "AT-4"}})

wire, sent = publish_and_read(
    {"at": 1, "plan": noise[:5000], "options": {"x": noise[5000:15000]},
     "config": {"MAA": {"关卡": "AT-4"}}})
check("砍了 plan 还装不下，才轮到选项表",
      ("plan" in sent["body"], "options" in sent["body"]), (False, False))
check("砍到最后配置还在", sent["body"].get("config"), {"MAA": {"关卡": "AT-4"}})
check("最终发出去的一定在上限之内", len(wire) <= phone.Mailbox.MAX_BODY, True)

net = FakeNet()
net.queue.append(urllib.error.URLError("网断了"))
check("网断了返回 False，不抛（调用方才能去别的渠道)",
      with_net(net, lambda: mb.publish({"at": 1})), False)
net = FakeNet()
net.queue.append(FakeResp(b"", status=500))
check("服务器 500 也算没发出去",
      with_net(net, lambda: mb.publish({"at": 1})), False)

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
      got, [{"action": "run_now", "queue": "早班"}, {"action": "skip_shutdown"}])
check("请求里带上 poll=1（一次取完，不是轮询）",
      "poll=1" in net.sent[0][0], True)

net = FakeNet()
net.queue.append(FakeResp(lines))
check("同一批消息第二次取：一条都不再执行（否则同一条指令跑两趟）",
      with_net(net, lambda: mb2.fetch()), [])

net = FakeNet()
net.queue.append(FakeResp(lines))
check("换个新实例（下次开机）照样记得已经执行过",
      with_net(net, lambda: phone.Mailbox("topic-abc", PIN, MB_STATE).fetch()), [])

net = FakeNet()
net.queue.append(FakeResp(lines + ntfy_lines(
    ("m9", phone.pack(PIN, {"action": "debug_mode"})))))
check("同一批里新来的那条要执行",
      with_net(net, lambda: mb2.fetch()), [{"action": "debug_mode"}])

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
      got, [{"action": "run_now", "queue": "早班"}])
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
check("没到上限用 30 秒间隔", hb.interval(), phone.HEARTBEAT_SEC)

hb._count_file().write_text(str(phone.HB_DAILY_CAP - 1), encoding="utf-8")
check("差一条到上限，还是快的", hb.interval(), phone.HEARTBEAT_SEC)
hb.beat()
check("正好到上限就放慢到 5 分钟", hb.interval(), phone.HB_SLOW_SEC)
# ntfy 匿名档每 IP 每天 250 条。上限之下的快跳最多吃掉 HB_DAILY_CAP 条，
# 必须给状态推送和指令应答留出足够的余量。
check("快跳的日上限低于 ntfy 的 250 条", phone.HB_DAILY_CAP < 250, True)
check("给状态和指令留了至少 100 条余量", 250 - phone.HB_DAILY_CAP >= 100, True)
check("放慢档确实慢一个量级",
      phone.HB_SLOW_SEC >= 10 * phone.HEARTBEAT_SEC, True)

hb._count_file().write_text("这不是数字", encoding="utf-8")
check("计数文件坏了当 0，不抛（抛了整个心跳线程就死了）", hb.sent_today(), 0)
hb._count_file().unlink()
check("计数文件没了当 0", hb.sent_today(), 0)
check("计数按天分文件，隔天自动归零",
      time.strftime("%Y-%m-%d") in hb._count_file().name, True)

dead = phone.Heartbeat("topic-abc", HB_STATE,
                       post=lambda *_: (_ for _ in ()).throw(OSError("网断了")))
before = dead.sent_today()
check("发失败返回 False", dead.beat(), False)
check("发失败不许记数（否则网一断就自己把额度耗光）", dead.sent_today(), before)

# ---- The beat has to carry the cadence it is beating at ----
# The page decides "no heartbeat for a while = powered off" from a fixed window.
# Once the daily cap drops the relay to one beat every 5 minutes, that verdict is
# wrong for three and a half minutes out of every five - a red 「关机中」 while the
# queue is running. The page cannot guess the cadence; this message is the only
# place it can learn it.
_sent = []
_hb = phone.Heartbeat("t", tmpdir(), post=lambda payload, title: _sent.append(payload))
check("正常节奏报 30", (_hb.beat(), _sent[-1]), (True, b"hb 30"))
for _ in range(phone.HB_DAILY_CAP):
    _hb._bump()
check("过了日上限报 300", (_hb.beat(), _sent[-1]), (True, b"hb 300"))
check("报的就是 interval() 说的那个",
      _sent[-1].decode(), f"hb {_hb.interval()}")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
