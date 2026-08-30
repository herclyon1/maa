"""手机通道的验签、时效、防重放。

这条管道是**公开的**——ntfy 上一个谁都能读写的主题。所以真正的判据不是
「消息能不能到」，而是「不该被执行的消息有没有被挡住」。下面每一条都是
一种「有人知道信箱名但不知道 PIN」时会发生的事。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.phone import MAX_AGE, pack, sign, unpack  # noqa: E402

PIN = "8964"
FAILED: list[str] = []


def check(what, got, want):
    if got != want:
        FAILED.append(f"{what}: 得到 {got!r}，应为 {want!r}")


def main() -> int:
    raw = pack(PIN, {"action": "skip_shutdown"})
    msg = unpack(PIN, raw)
    check("自己发自己收，能过", msg and msg["body"], {"action": "skip_shutdown"})
    check("带上类型", msg and msg["kind"], "cmd")

    check("PIN 不对，丢弃", unpack("1234", raw), None)

    # 改内容不改签名——最直接的伪造
    d = json.loads(raw)
    d["body"] = {"action": "set_stage", "value": "CE-6"}
    check("内容被改过，签名对不上，丢弃",
          unpack(PIN, json.dumps(d, ensure_ascii=False)), None)

    # 连签名一起改也没用：他算不出正确的签名
    d["sig"] = "0" * 64
    check("签名被替换，丢弃", unpack(PIN, json.dumps(d, ensure_ascii=False)), None)

    check("根本不是 JSON，丢弃", unpack(PIN, "hello"), None)
    check("没有签名字段，丢弃", unpack(PIN, '{"body":{"action":"x"}}'), None)

    # 时效：指令要能在信箱里等到下次开机，但不能无限久
    old = json.loads(raw)
    payload = {k: v for k, v in old.items() if k != "sig"}
    payload["ts"] = int(time.time()) - MAX_AGE - 60
    payload["sig"] = sign(PIN, {k: v for k, v in payload.items() if k != "sig"})
    check("超过 24 小时的指令，丢弃",
          unpack(PIN, json.dumps(payload, ensure_ascii=False)), None)

    payload["ts"] = int(time.time()) - 11 * 3600      # 机器两趟之间最长的间隔
    payload["sig"] = sign(PIN, {k: v for k, v in payload.items() if k != "sig"})
    ok = unpack(PIN, json.dumps(payload, ensure_ascii=False))
    check("等了 11 小时的指令还算数（机器一天只开两趟）", bool(ok), True)

    # 防重放：同一条抓下来重发
    seen: set[str] = set()
    check("第一次收，过", bool(unpack(PIN, raw, seen=seen)), True)
    check("同一条再来一次，按重放丢弃", unpack(PIN, raw, seen=seen), None)

    # 两条不同的指令不能互相误伤
    seen2: set[str] = set()
    a = pack(PIN, {"action": "skip_shutdown"})
    b = pack(PIN, {"action": "skip_shutdown"})
    check("内容相同但随机串不同的两条，都要过",
          [bool(unpack(PIN, x, seen=seen2)) for x in (a, b)], [True, True])

    # 状态消息不是指令，取指令时不该被当成指令执行
    st = unpack(PIN, pack(PIN, {"stage": "1-7"}, kind="state"))
    check("状态消息的类型是 state", st and st["kind"], "state")

    print("all checks passed" if not FAILED else "FAILED: " + "; ".join(FAILED))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
