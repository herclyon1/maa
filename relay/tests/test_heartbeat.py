"""The heartbeat; and its COS copy.

One part per former file, each run on its own (tests/_parts.py): test_heartbeat.py, test_heartbeat_cos.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_main():
    """心跳：有人看才跳、看了立刻跳（刚跳过就不重跳）、停服务发 bye、今天发得多了就放慢。不碰网络。

    Formerly test_heartbeat.py.
    """
    import threading
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.phone import phone


    def wait_for(pred, limit=10.0):
        """Poll until pred() holds or `limit` seconds pass. A fixed 0.2 s sleep went red on a
    loaded Windows runner (relay-windows runs 38391031443 and 38409766185, 2026-10-13: the
    beat thread had not woken yet); a beat that is due still lands at once here."""
        end = time.monotonic() + limit
        while not pred() and time.monotonic() < end:
            time.sleep(0.01)


    sent = []
    STATE = tmpdir()
    hb = phone.Heartbeat("t", STATE, post=lambda payload, title: sent.append(title))
    # 把等待切片缩到 20 毫秒：这个测试验的是「有人看才跳」的逻辑，不是真的计时。
    # 2026-09-08 之前它真等 4 秒，而部署每次都跑整套测试。
    hb._slice_s = 0.02
    stop = {"v": False}
    th = threading.Thread(target=hb.loop, args=(lambda: stop["v"],), daemon=True)
    th.start()

    wait_for(lambda: sent)
    check("刚起来先报一次在线", sent, ["hb"])
    sent.clear()
    check("之后没人看就不跳了", sent, [])
    hb.watch()
    time.sleep(0.2)
    # On open the page reads the last 90 s of beats itself (probeHb since=90s), so a
    # beat that just went out already answers a watch; no extra message for it
    # (10-02 the quota ran out and 196 of the messages were beats).
    check("刚跳过（不到 HB_KICK_GAP）：说「我在看」不再多跳", sent, [])
    hb._last = time.time() - phone.HB_KICK_GAP - 1
    hb.watch()
    wait_for(lambda: sent)
    check("上一跳已经旧了：说「我在看」立刻跳", sent, ["hb"])
    check("计数落盘", hb.sent_today(), 2)
    check("有人看时的间隔", hb.interval(), phone.HEARTBEAT_SEC)

    hb.quota.add("state", phone.HB_FAST_UNTIL)
    check("今天发的总数过了快档线就放慢", hb.interval(), phone.HB_SLOW_SEC)

    stop["v"] = True
    th.join(5)
    check("线程 5 秒内退出", th.is_alive(), False)
    check("退出发 bye", sent[-1], "bye")

    # 发不出去不炸
    bad = phone.Heartbeat("t", STATE, post=lambda *_: (_ for _ in ()).throw(OSError("net")))
    check("post 失败返回 False 不抛", bad.beat(), False)

    # loop() run on this thread as well: the coverage gate (changed_covered.py) does
    # not trace the thread above, so without this it counts loop() as never run.
    direct_sent = []
    direct = phone.Heartbeat("t", tmpdir(), post=lambda payload, title: direct_sent.append(title))
    direct.loop(lambda: True)
    check("loop() on the caller's thread: one beat in, bye out", direct_sent, ["hb", "bye"])


def _part_heartbeat_cos():
    """The heartbeat on COS too (the user, 10-03 00:12: the online verdict must not
rest on the mailbox's heartbeat alone).

The loss this guards against: 2026-10-02 19:19 ntfy's 250 a day ran out, every
beat after that was refused, and at 23:58 the App showed
「关机 · 最后心跳 22:34」 while the machine was running and writing its state to
COS. Now every beat also PUTs `state/<hash>.hb.json`.

Pinned here:
* the object sits next to the state (same hash, `.hb.json`), public-read,
  never cached, {"at", "every", "cos_every"};
* written whether or not the ntfy beat went out, and while the quota has
  stopped the ntfy beats (then `every` is at least HB_SLOW_SEC);
* a COS failure is one log line and the ntfy beat still goes out;
* a service stop writes it once more with "bye": true, after the ntfy bye;
* while watched, the loop rewrites it every HB_COS_SEC and at once on a watch,
  even when the ntfy beat is not due or the quota stopped it;
* no COS -> exactly the old ntfy beat, no request.
Fake network throughout.

    Formerly test_heartbeat_cos.py.
    """
    import json
    import logging
    import threading
    import time
    import types
    import urllib.error

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.phone import phone
    from ark_relay.features.phone import cos_store as phone_cos_store, heartbeat as phone_heartbeat, mailbox as phone_mailbox, quota as phone_quota
    from ark_relay.features.evidence.evidence import Cos

    TOPIC = "topic-abc"
    COS = Cos("AKIDtest", "secret", "ark-evidence-1", "ap-shanghai")


    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""


    class FakeNet:
        """Records every COS request (url, method, body, headers); `fail` makes them raise."""

        def __init__(self):
            self.sent: list[tuple[str, str, bytes, dict]] = []
            self.fail: "Exception | None" = None

        def urlopen(self, req, timeout=None):
            self.sent.append((req.full_url, req.get_method(), req.data or b"",
                              {k.lower(): v for k, v in req.header_items()}))
            if self.fail is not None:
                raise self.fail
            return FakeResp()

        def bodies(self):
            return [json.loads(b) for _, _, b, _ in self.sent]


    net = FakeNet()
    fake_urllib = types.SimpleNamespace(
        request=types.SimpleNamespace(Request=urllib.request.Request, urlopen=net.urlopen),
        error=urllib.error)
    # phone.py's network code lives in these sibling modules; each reads its own urllib.
    for _m in (phone_quota, phone_cos_store, phone_mailbox, phone_heartbeat):
        _m.urllib = fake_urllib


    class Logs(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines: list[str] = []
            self.recovered: list[bool] = []

        def emit(self, record):
            if record.levelno >= logging.INFO:
                self.lines.append(record.getMessage())
            if record.levelno >= logging.WARNING:
                self.recovered.append(bool(getattr(record, "ark_recovered", False)))


    logs = Logs()
    phone.log.addHandler(logs)
    phone.log.setLevel(logging.DEBUG)

    print("[对象名：和状态对象同一个哈希，后缀 .hb.json]")
    key = phone.hb_key(TOPIC)
    check("state_key 去掉 .json 换成 .hb.json", key, phone.state_key(TOPIC)[:-5] + ".hb.json")
    check("大小写、首尾空格不影响（和 state_key 一样）", phone.hb_key("  TOPIC-ABC \n"), key)

    print("\n[一跳：COS 和 ntfy 各一次]")
    posted: list[str] = []
    hb = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: posted.append(title), cos=COS)
    t0 = int(time.time())
    check("ntfy 心跳照旧发出", hb.beat(), True)
    check("ntfy 收到一条 hb", posted, ["hb"])
    check("COS 一次 PUT", [m for _, m, _, _ in net.sent], ["PUT"])
    url, _, body, h = net.sent[0]
    check("PUT 到 hb_key", url, f"https://{COS.host}/{key}")
    check("公开读（App 没有 COS 密钥）", h.get("x-cos-acl"), "public-read")
    check("不许缓存（不然 App 读到旧心跳）", h.get("cache-control"), "no-store")
    check("带签名", h.get("authorization", "").startswith("q-sign-algorithm=sha1&q-ak=AKIDtest"), True)
    b = json.loads(body)
    check("at 是现在（秒）", t0 <= b["at"] <= int(time.time()), True)
    check("every = 当前 ntfy 心跳间隔", b["every"], phone.HEARTBEAT_SEC)
    check("cos_every = COS 心跳间隔 30 秒", b["cos_every"], phone.HB_COS_SEC)
    check("平时不带 bye", "bye" in b, False)

    print("\n[ntfy 发不出去：COS 照写]")
    net.sent.clear()
    bad = phone.Heartbeat(TOPIC, tmpdir(), post=lambda *_: (_ for _ in ()).throw(OSError("net")), cos=COS)
    check("ntfy 失败返回 False 不抛", bad.beat(), False)
    check("COS 还是写了一次", len(net.sent), 1)

    print("\n[ntfy 额度用完（42908）：ntfy 不再发，COS 照写，every 至少 5 分钟]")
    net.sent.clear()
    posted.clear()
    full = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: posted.append(title), cos=COS)
    full.quota.mark_full()
    check("ntfy 不发（发了也是 429）", full.beat(), False)
    check("ntfy 一条没发", posted, [])
    check("COS 写了", len(net.sent), 1)
    check("every 至少 HB_SLOW_SEC（App 下次读在 8 分钟的续看）", net.bodies()[0]["every"], phone.HB_SLOW_SEC)
    full.quota.add("hb", phone.HB_SLOW_UNTIL)
    net.sent.clear()
    full.beat()
    check("额度用完且总数过了慢档线：every = HB_CRAWL_SEC", net.bodies()[0]["every"], phone.HB_CRAWL_SEC)

    print("\n[COS 失败：一行日志，ntfy 照发，不抛]")
    net.sent.clear()
    posted.clear()
    logs.lines.clear()
    net.fail = urllib.error.URLError("网断了")
    flaky = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: posted.append(title), cos=COS)
    check("ntfy 心跳照旧发出", flaky.beat(), True)
    check("ntfy 收到 hb", posted, ["hb"])
    flaky.beat()
    flaky.beat()
    cos_lines = [l for l in logs.lines if "腾讯云 COS" in l]
    check("连失败三次只记一行", len(cos_lines), 1)
    check("那一行说了原因", "网断了" in (cos_lines or [""])[0], True)
    net.fail = urllib.error.HTTPError(f"https://{COS.host}/{key}", 403, "Forbidden", None, None)
    check("COS 回 403 也不抛", flaky.cos_beat(), False)
    net.fail = None
    logs.lines.clear()
    logs.recovered.clear()
    check("恢复后写得进", flaky.cos_beat(), True)
    # Since 2026-10-06 the recovery is one WARNING marked errwatch.recovered()
    # (daily report only), saying how long it was down and the first reason.
    check("恢复记一行", [l.splitlines()[0].split("（")[0] for l in logs.lines if "腾讯云" in l],
          ["心跳又写得进腾讯云了"])
    check("……marked recovered (not pushed)", logs.recovered, [True])
    check("……the first reason on its second line", "网断了" in (logs.lines or [""])[-1], True)

    print("\n[停服务：ntfy 发 bye 之后，COS 写一次带 bye 的]")
    order: list[str] = []
    net.sent.clear()
    stopper = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: order.append("ntfy:" + title), cos=COS)
    orig = net.urlopen
    net.urlopen = lambda req, timeout=None: (order.append("cos"), orig(req, timeout))[1]
    fake_urllib.request.urlopen = net.urlopen
    stopper.bye()
    check("先 ntfy bye，再 COS", order, ["ntfy:bye", "cos"])
    check("COS 的心跳带 bye", net.bodies()[-1].get("bye"), True)
    net.urlopen = orig
    fake_urllib.request.urlopen = orig
    net.sent.clear()
    broke = phone.Heartbeat(TOPIC, tmpdir(), post=lambda *_: (_ for _ in ()).throw(OSError("net")), cos=COS)
    broke.bye()
    check("ntfy bye 失败也照写 COS bye", net.bodies()[-1].get("bye"), True)

    print("\n[循环：有人看时每 30 秒写一次 COS；说「我在看」立刻写，哪怕 ntfy 不到点或额度停了]")
    net.sent.clear()
    posted.clear()
    lp = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: posted.append(title), cos=COS)
    lp._slice_s = 0.01
    stop = {"v": False}
    th = threading.Thread(target=lp.loop, args=(lambda: stop["v"],), daemon=True)
    th.start()
    time.sleep(0.15)
    check("起来先跳一次：ntfy 一条、COS 一次", (posted, len(net.sent)), (["hb"], 1))
    lp.watch()
    time.sleep(0.15)
    check("刚跳过：ntfy 不重跳", posted, ["hb"])
    check("但 COS 立刻再写一次（App 几秒后来读）", len(net.sent), 2)
    # The loop sleeps up to HB_COS_SEC slices (0.3 s here) before it looks again.
    lp._cos_last = time.time() - phone.HB_COS_SEC - 1
    # Wait for the write rather than a fixed 0.5 s: 30 slices of time.sleep(0.01) ran
    # past 0.5 s on a loaded Mac (load 10-29, 2026-10-10 00:45) and the check failed.
    _until = time.time() + 5
    while len(net.sent) < 3 and time.time() < _until:
        time.sleep(0.05)
    check("COS 到 30 秒就再写，ntfy 不到点不发", (posted, len(net.sent) >= 3), (["hb"], True))
    lp.quota.mark_full()
    n = len(net.sent)
    lp.watch()
    time.sleep(0.15)
    check("额度停了：说「我在看」COS 照写，ntfy 不发", (posted, len(net.sent) > n), (["hb"], True))
    stop["v"] = True
    th.join(5)
    check("线程 5 秒内退出", th.is_alive(), False)
    check("退出时 COS 写 bye", net.bodies()[-1].get("bye"), True)

    print("\n[没配 COS：老样子，一个 COS 请求都没有]")
    net.sent.clear()
    posted.clear()
    plain = phone.Heartbeat(TOPIC, tmpdir(), post=lambda payload, title: posted.append(title))
    plain.beat()
    plain.bye()
    check("ntfy 照旧 hb、bye", posted, ["hb", "bye"])
    check("不碰 COS", net.sent, [])
    check("cos_beat 直接 False", plain.cos_beat(), False)


if __name__ == "__main__":
    sys.exit(run_parts([_part_main, _part_heartbeat_cos]))
