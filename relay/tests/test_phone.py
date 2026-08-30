"""手机通道：PIN 对不上、太老的指令、状态和指令别混。

凭证就一个 PIN（用户 2026-08-31：「留一个 pin 就行了，那那么多事」）。
这里钉住的是「不该被执行的消息有没有被挡住」，以及机器一天只开两趟
带来的那个时效窗——指令要能在信箱里等到下次开机。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.phone import MAX_AGE, pack, unpack  # noqa: E402

PIN = "8964"
FAILED: list[str] = []


def check(what, got, want):
    if got != want:
        FAILED.append(f"{what}: 得到 {got!r}，应为 {want!r}")


def main() -> int:
    raw = pack(PIN, {"action": "skip_shutdown"})
    msg = unpack(PIN, raw)
    check("自己发自己收", msg and msg["body"], {"action": "skip_shutdown"})
    check("带上类型", msg and msg["kind"], "cmd")

    check("PIN 不对，丢弃", unpack("1234", raw), None)
    check("没有 PIN 字段，丢弃", unpack(PIN, '{"kind":"cmd","body":{}}'), None)
    check("根本不是 JSON，丢弃", unpack(PIN, "hello"), None)
    check("是 JSON 但不是对象，丢弃", unpack(PIN, "[1,2,3]"), None)

    def stamped(age_s):
        d = json.loads(raw)
        d["ts"] = int(time.time()) - age_s
        return json.dumps(d, ensure_ascii=False)

    check("超过 24 小时的指令，丢弃", unpack(PIN, stamped(MAX_AGE + 60)), None)
    check("等了 11 小时还算数（机器一天只开两趟）",
          bool(unpack(PIN, stamped(11 * 3600))), True)
    check("时间戳不是整数，丢弃",
          unpack(PIN, json.dumps({**json.loads(raw), "ts": "刚刚"})), None)

    st = unpack(PIN, pack(PIN, {"stage": "1-7"}, kind="state"))
    check("状态消息的类型是 state，取指令时不会被当指令执行",
          st and st["kind"], "state")

    print("all checks passed" if not FAILED else "FAILED: " + "; ".join(FAILED))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
