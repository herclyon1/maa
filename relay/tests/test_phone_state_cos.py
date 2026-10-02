"""The whole state on Tencent COS, one notice on ntfy (the user, 2026-10-02 22:22).

The loss this guards against: states eating ntfy's 250 a day (10-02: a state
was 4 pieces; 13 states + 196 beats = 248, and from 19:19 the phone could not
see the machine). Now the envelope is PUT to COS whole and the topic only gets
one line, `state <ts> <bytes>`.

Pinned here:
* what is stored is the envelope that would have gone to ntfy (PIN inside, the
  App decodes it as before);
* the object is public-read, never cached, named from the topic the same way
  the App names it (lower-case, first 32 hex of sha256);
* stored -> one short notice on ntfy, one message on the ledger;
* not stored (refused / no network) -> the old pieces, nothing lost;
* a machine without COS -> exactly the old path.
Fake network throughout.
"""
import hashlib
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
from ark_relay.evidence import Cos

PIN = "8964"
TOPIC = "topic-abc"
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
    if not ok:
        fails.append(label)


class FakeResp:
    def __init__(self, body: bytes = b"", status: int = 200):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


class FakeNet:
    """Records every request (url, method, body, headers); canned answers in order."""

    def __init__(self, *answers):
        self.sent: list[tuple[str, str, bytes, dict]] = []
        self.queue = list(answers)

    def urlopen(self, req, timeout=None):
        self.sent.append((req.full_url, req.get_method(), req.data or b"",
                          {k.lower(): v for k, v in req.header_items()}))
        if not self.queue:
            return FakeResp()
        nxt = self.queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def with_net(net, fn):
    saved = phone.urllib
    phone.urllib = types.SimpleNamespace(
        request=types.SimpleNamespace(Request=saved.request.Request, urlopen=net.urlopen),
        error=urllib.error)
    try:
        return fn()
    finally:
        phone.urllib = saved


COS = Cos("AKIDtest", "secret", "ark-evidence-1", "ap-shanghai")
# A state the size of 10-02's (43 KB raw): random text so gzip cannot fold it
# under the 4096-byte inline limit.
import random  # noqa: E402

random.seed(7)
BIG = {"at": 1790000000, "options": {f"k{i}": "".join(random.choice("abcdefghijk甲乙丙丁")
                                                      for _ in range(40)) for i in range(400)}}

print("[对象名：由 topic 推出，App 算的是同一个]")
key = phone.state_key(TOPIC)
check("state/ 下、sha256(topic) 前 32 位、.json",
      key, "state/" + hashlib.sha256(TOPIC.encode()).hexdigest()[:32] + ".json")
check("大小写、首尾空格不影响（App 存 topic 时转小写、去空格）",
      phone.state_key("  TOPIC-ABC \n"), key)
check("名字里看不出 topic", TOPIC in key, False)

print("\n[state_cos：机器没配 COS 就是老路子]")
cfg_none = types.SimpleNamespace(cos_secret_id="", cos_secret_key="", cos_bucket="", cos_region="")
check("缺 COS_* 时返回 None", phone.state_cos(cfg_none), None)
cfg_all = types.SimpleNamespace(cos_secret_id="a", cos_secret_key="b",
                                cos_bucket="ark-evidence-1", cos_region="ap-shanghai")
c = phone.state_cos(cfg_all)
check("配齐了给出这个桶的客户端", (c.host, c.prefix), ("ark-evidence-1.cos.ap-shanghai.myqcloud.com", ""))

print("\n[大状态：整份进 COS，ntfy 只发一条通知]")
mb = phone.Mailbox(TOPIC, PIN, tmpdir(), cos=COS)
net = FakeNet()
t0 = int(time.time())
check("发出去了", with_net(net, lambda: mb.publish(BIG)), True)
check("一共两次请求：一次 PUT 到 COS，一次 POST 到 ntfy",
      [(m, u.split("/")[2]) for u, m, _, _ in net.sent],
      [("PUT", COS.host), ("POST", "ntfy.sh")])
url, _, put_body, put_h = net.sent[0]
check("PUT 到 state_key", url, f"https://{COS.host}/{key}")
check("对象公开读（App 没有 COS 密钥）", put_h.get("x-cos-acl"), "public-read")
check("不许缓存（不然 App 读到旧状态）", put_h.get("cache-control"), "no-store")
check("带签名", put_h.get("authorization", "").startswith("q-sign-algorithm=sha1&q-ak=AKIDtest"), True)
back = phone.unpack(PIN, put_body.decode("utf-8"))
check("存上去的就是 ntfy 那份信封：PIN 对得上、kind=state、解出来一字不差",
      (back or {}).get("kind"), "state")
check("……body 原样", (back or {}).get("body"), BIG)
def no_ts(raw):
    d = json.loads(raw)
    d.pop("ts", None)
    return d


check("……就是 pack(gz=True) 那一份（除了时间戳，一字节不差）",
      no_ts(put_body), no_ts(phone.pack(PIN, BIG, "state", gz=True)))
check("确实压了（gz 字段）", "gz" in json.loads(put_body), True)
_, _, note, note_h = net.sent[1]
parts = note.decode("ascii").split(" ")
check("通知格式 `state <ts> <字节数>`", (parts[0], len(parts)), ("state", 3))
check("通知里的时间是这次发的", abs(int(parts[1]) - t0) <= 2, True)
check("通知里的字节数就是对象的大小", int(parts[2]), len(put_body))
check("通知很短（远在 4096 之内）", len(note) < 64, True)
check("通知的 Title 还是 state", note_h.get("title"), "state")
check("通知不是 JSON：老页面、老中继 unpack 都当没看见", phone.unpack(PIN, note.decode()), None)
check("ntfy 额度只记了一条", mb.quota.count("state"), 1)

print("\n[小状态：也存 COS（开 App 时读得到最新的），ntfy 照旧发整条，老 App 不受影响]")
mb_s = phone.Mailbox(TOPIC, PIN, tmpdir(), cos=COS)
net = FakeNet()
check("发出去了", with_net(net, lambda: mb_s.publish({"at": 1})), True)
check("PUT 一次 + 整条状态一次", [m for _, m, _, _ in net.sent], ["PUT", "POST"])
check("ntfy 上那条就是对象本身", net.sent[1][2], net.sent[0][2])

print("\n[COS 存不上：照旧切片发，什么都不丢]")
for label, err in (("COS 拒绝（403）", urllib.error.HTTPError(
        f"https://{COS.host}/{key}", 403, "Forbidden", {}, io.BytesIO(b""))),
        ("连不上 COS", urllib.error.URLError("网断了")),
        ("COS 回的不是 2xx（302）", FakeResp(status=302))):
    mb_f = phone.Mailbox(TOPIC, PIN, tmpdir(), cos=COS)
    net = FakeNet(err)
    ok = with_net(net, lambda: mb_f.publish(BIG))
    posts = [b for u, m, b, _ in net.sent if m == "POST"]
    check(f"{label}：还是发出去了", ok, True)
    check(f"{label}：PUT 只试一次，不重试", sum(1 for _, m, _, _ in net.sent if m == "PUT"), 1)
    check(f"{label}：退回切片（多条，每条带 gzp）",
          len(posts) > 1 and all("gzp" in json.loads(p) for p in posts), True)

print("\n[没配 COS 的机器：完全是老路子，不碰 COS]")
mb_n = phone.Mailbox(TOPIC, PIN, tmpdir())
net = FakeNet()
with_net(net, lambda: mb_n.publish(BIG))
check("一次 PUT 都没有", [m for _, m, _, _ in net.sent if m == "PUT"], [])
check("照旧切片", len(net.sent) > 1, True)

print("\n[只有状态进 COS：指令、bye 之类不碰]")
net = FakeNet()
with_net(net, lambda: mb.publish({"action": "x"}, kind="cmd"))
check("kind=cmd 不 PUT", [m for _, m, _, _ in net.sent], ["POST"])

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
