#!/usr/bin/env python3
"""Read back, in one go, what is really configured on the gaming machine.

**Only the MAA section is what is really in effect.** Endfield and Wuthering Waves
have quick config switched off, so AUTO-MAS never pushes those fields down and each
game runs from its own master config instead. Both sections now open with a line
saying whether their fields are live; do not draw a conclusion from a section that
says they are not. For what those two really run:
`winrun.sh --py scripts/mac/lib/effective_config.py`.

    scripts/mac/config-check.py              # 打印当前全部关键配置
    scripts/mac/config-check.py --save       # 存快照
    scripts/mac/config-check.py --diff       # 和上次快照比，只显示变了的

存在的唯一理由：**防止我说「已经设好了」而其实没设。**

2026-08-26 至少两次栽在这上面：
  * 说 OK-WW 的梦魇净化「三令五申检查通过」——配置文件从 08-24 起就没被写过；
  * 说改了 MAA 的关卡序号并「回读确认」——回读的是「值存进去了」，
    而不是「这个值是不是我以为的那个关卡」。

用户的原话是：「你不是不会干活，你是有幻觉，以为自己干了但没有。」

**规矩：任何关于配置的断言，先跑这个，把它的输出贴出来，再说结论。**
不许凭印象、不许凭「我刚才改过」。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import os

# 和其余脚本一个口径：ARK_HOST 优先，没设才回落到这台机器的地址。
# 写死常量的话，换一台机器要改源码；而别的脚本全都认 ARK_HOST，只有它不认。
HOST = os.environ.get("ARK_HOST") or "100.65.39.119"
HERE = Path(__file__).resolve().parent
SNAP = HERE.parent.parent / "relay" / "state" / "config-snapshot.json"
SNAP_AT = "_snapshot_at"          # 快照自己的时间戳，flatten 之前 pop 掉
RUNTIME_SEGMENTS = ("进程", "ark-relay")   # 运行时状态，不是配置

# 远端读取脚本。只输出 JSON，中文走 winrun 的字节通道，不经过 936 控制台。
PROBE = r'''
# 读取逻辑在中继里（ark_relay/snapshot.py），这里只是把它调起来。
# 两处各写一遍早晚会各说各话，而「显示的和机器上真实的不一样」正是
# 826 那类事故的温床——用户 2026-08-31 明确要求手机端和机器保持一致，
# 这里跟着一起收敛到同一份代码。
import json, sys
sys.path.insert(0, r"C:\ProgramData\ark-relay")
from ark_relay import snapshot
print(json.dumps(snapshot.read(), ensure_ascii=False, indent=1, sort_keys=True))
'''


def fetch() -> dict:
    tmp = Path("/tmp/ark-config-probe.py")
    tmp.write_text(PROBE, encoding="utf-8")
    r = subprocess.run([str(HERE / "winrun.sh"), "--py", str(tmp)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"✗ 读不回配置（winrun 退出码 {r.returncode}）\n{r.stderr.strip()}")
    # winrun 会在正文前面加一行「[机器时间] MM-DD HH:MM:SS」——那是它的
    # 设计（远端时钟必须露出来，见 winrun.sh 的注释），不是脏数据。
    # 2026-08-31 之前这里直接 json.loads 整个 stdout，于是**读回来了却报
    # 「不是 JSON」**：一个能正常工作的工具，每次都自称失败。
    # 这正是这个脚本存在的理由那一类错——「以为干了但没干」的镜像。
    body = r.stdout
    i = body.find("{")
    if i > 0:
        body = body[i:]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        sys.exit(f"✗ 远端返回的不是 JSON：\n{r.stdout[:600]}")


def _now_both() -> str:
    """「09-08 07:30（东京 08:30）」——两地时差一小时，不标是哪边的钟等于没标。"""
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    tokyo = datetime.now(timezone(timedelta(hours=9)))
    server = tokyo - timedelta(hours=1)
    return f"{server:%Y-%m-%d %H:%M}（东京 {tokyo:%H:%M}）"


def flatten(d, pre=""):
    for k, v in sorted(d.items()):
        key = f"{pre}.{k}" if pre else k
        if isinstance(v, dict):
            yield from flatten(v, key)
        else:
            yield key, v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", action="store_true", help="存为快照")
    ap.add_argument("--diff", action="store_true", help="与快照比对，只列变化")
    a = ap.parse_args()

    cur = fetch()
    if a.diff:
        if not SNAP.exists():
            sys.exit("✗ 还没有快照，先跑一次 --save")
        old = json.loads(SNAP.read_text(encoding="utf-8"))
        # 快照自报年龄。不标时间的「你的实际配置」是谎话——2026-09-08 审出来时
        # 那份基线是 13 天前的，里面写着 09-05 已经改掉的错地区，而它被当成现状读。
        at = old.pop(SNAP_AT, "")
        if at:
            print(f"快照存于 {at}")
        else:
            print("⚠️  这份快照没有时间戳（老格式），不知道多旧——比完建议重新 --save")
        # 运行时状态不是配置，比对它只会天天冒出无意义的差异
        for seg in RUNTIME_SEGMENTS:
            old.pop(seg, None)
            cur.pop(seg, None)
        o, c = dict(flatten(old)), dict(flatten(cur))
        # 两边都要兜底：快照的键会随 snapshot.py 改版增减，只在一侧存在是常态。
        # 2026-09-08 之前这里写的是 c[k]，遇到「只在旧快照里」的键当场 KeyError——
        # 而这个工具正是「改完配置必须跑一次」的那个验证步骤，最需要它的时候罢工。
        changed = [(k, o.get(k, "（原本没有）"), c.get(k, "（现在没有）"))
                   for k in sorted(set(o) | set(c)) if o.get(k) != c.get(k)]
        if not changed:
            print("✅ 和快照完全一致，没有任何变化")
            return 0
        print(f"⚠️  有 {len(changed)} 项和快照不同：")
        for k, ov, nv in changed:
            print(f"  {k}\n      快照: {ov!r}\n      现在: {nv!r}")
        return 0

    print(json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=True))
    if a.save:
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        stamped = dict(cur)
        stamped[SNAP_AT] = _now_both()
        SNAP.write_text(json.dumps(stamped, ensure_ascii=False, indent=1,
                                   sort_keys=True), encoding="utf-8")
        print(f"\n快照已存: {SNAP}（{stamped[SNAP_AT]}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
