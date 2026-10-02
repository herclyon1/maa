"""心跳：有人看才跳、看了立刻跳（刚跳过就不重跳）、停服务发 bye、今天发得多了就放慢。不碰网络。"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import phone
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

sent = []
STATE = tmpdir()
hb = phone.Heartbeat("t", STATE, post=lambda payload, title: sent.append(title))
# 把等待切片缩到 20 毫秒：这个测试验的是「有人看才跳」的逻辑，不是真的计时。
# 2026-09-08 之前它真等 4 秒，而部署每次都跑整套测试。
hb._slice_s = 0.02
stop = {"v": False}
th = threading.Thread(target=hb.loop, args=(lambda: stop["v"],), daemon=True)
th.start()

time.sleep(0.2)
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
time.sleep(0.2)
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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
