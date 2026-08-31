"""状态包超限时压缩，而不是砍字段。

2026-08-31 量到整包 3783 字节，上限 3900，**只剩 117 字节余量**。
超线时原来的处理是先砍「明日安排」、再砍「选项表」——而选项表正是手机上
那一堆中文下拉候选，占了整包 57%。砍掉等于功能没了，而且不出声地没了。
压缩后 2464 字节，余量回到一千多。

发的那头只在明文会超限时才压，收的那头两种都认，
所以手机上就算跑的是旧页面也不会突然读不懂。
"""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import phone

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
    if not ok:
        fails.append(label)

PIN = "8964"
BODY = {"options": {f"键{i}": ["候选甲", "候选乙", "候选丙"] for i in range(60)},
        "plan": "明日安排" * 30, "at": 1}

print("\n[往返]")
# 断言只印真假——BODY 有六十个键，整份印出来把日志淹了
check("明文解得回来",
      phone.unpack(PIN, phone.pack(PIN, BODY, "state"))["body"] == BODY, True)
check("压缩解得回来",
      phone.unpack(PIN, phone.pack(PIN, BODY, "state", gz=True))["body"] == BODY, True)

print("\n[压缩确实更小]")
plain = len(phone.pack(PIN, BODY, "state").encode())
gz = len(phone.pack(PIN, BODY, "state", gz=True).encode())
check("压完不到明文一半", gz * 2 < plain, True)
print(f"       明文 {plain} 字节 → 压缩 {gz} 字节")

print("\n[坏包不许当好包]")
bad = json.dumps({"v": 1, "kind": "state", "pin": PIN,
                  "ts": int(time.time()), "gz": "这不是 base64"})
check("解不开就丢弃", phone.unpack(PIN, bad), None)
check("PIN 不对照旧拒", phone.unpack("0000", phone.pack(PIN, BODY, "state", gz=True)), None)

print("\n[发的那头：不超限就别压]")
small = phone.pack(PIN, {"at": 1}, "state").encode()
check("小包保持明文（body 在、gz 不在）",
      ("body" in json.loads(small)) and ("gz" not in json.loads(small)), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
