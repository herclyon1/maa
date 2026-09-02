"""心跳：有人看才跳、看了立刻跳、停服务发 bye、超过日上限放慢。不碰网络。"""
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import phone  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

sent = []
STATE = Path(tempfile.mkdtemp())
hb = phone.Heartbeat("t", STATE, post=lambda payload, title: sent.append(title))
stop = {"v": False}
th = threading.Thread(target=hb.loop, args=(lambda: stop["v"],), daemon=True)
th.start()

time.sleep(2.5)
check("没人看：一跳不跳", sent, [])
hb.watch()
time.sleep(1.5)
check("说「我在看」：立刻跳", sent, ["hb"])
check("计数落盘", hb.sent_today(), 1)
check("有人看时的间隔", hb.interval(), phone.HEARTBEAT_SEC)

(STATE / hb._count_file().name).write_text(str(phone.HB_DAILY_CAP), encoding="utf-8")
check("到日上限就放慢", hb.interval(), phone.HB_SLOW_SEC)

stop["v"] = True
th.join(5)
check("线程 5 秒内退出", th.is_alive(), False)
check("退出发 bye", sent[-1], "bye")

# 发不出去不炸
bad = phone.Heartbeat("t", STATE, post=lambda *_: (_ for _ in ()).throw(OSError("net")))
check("post 失败返回 False 不抛", bad.beat(), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
