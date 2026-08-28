#!/usr/bin/env python3
"""单跑 MaaEnd 的任意入口节点，可带 pipeline_override。

在游戏机上跑（winrun 送过去）：

    winrun.sh --py scripts/mac/lib/maaend_task.py --entry AutoEssenceMain \
        --override '{"节点名": {"enabled": true}}' --go

不加 `--go` 只体检，不提交任何任务。

## 为什么要能指定 entry

MaaEnd 的任务是一张节点图，`assets/tasks/*.json` 里的 `entry` 只是官方入口。
真正想做的事常常是「跑到中间某一步就停」——比如走到淤积点的开始挑战界面
（那里才有预刻写选项），但**不要**点开始挑战、不要打、不要花体力。
这时就要自定义 entry 加 override 把后续节点掐掉。

复用 `maaend_essence.py` 的前置检查与资源加载，不重复实现。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maaend_essence import (AGENTS, MAAEND, api, ensure_resource,  # noqa: E402
                            pick_instance, preflight)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", required=True, help="要跑的入口节点名")
    # 只收 base64。裸 JSON 要穿过 bash → ssh → cmd → PowerShell 四层引号，
    # 2026-08-28 实测被啃成 `{GotoTrigger...`，引号全没了。
    ap.add_argument("--override-b64", default="", help="pipeline_override，base64(JSON)")
    ap.add_argument("--go", action="store_true", help="真跑；不加只体检")
    ap.add_argument("--timeout", type=int, default=600)
    ns = ap.parse_args(argv[1:])

    ov = (base64.b64decode(ns.override_b64).decode("utf-8")
          if ns.override_b64 else "{}")
    json.loads(ov)                     # 先验语法，别把坏 JSON 发过去

    inst, bad = preflight()
    print(f"[机器时间] {time.strftime('%m-%d %H:%M:%S')}")
    for k, v in inst.items():
        print(f"  {k}  连接={v.get('connected')} 资源={v.get('resource_loaded')} "
              f"在跑={v.get('is_running')}")
    if bad:
        print("\n❌ 还不能跑：")
        for b in bad:
            print("  · " + b)
        return 1
    if not ns.go:
        print(f"\n✅ 前置满足。要跑 {ns.entry} 请加 --go")
        return 0

    for k, v in inst.items():
        if v.get("connected") and not v.get("resource_loaded"):
            ensure_resource(k)
    inst = api("/maa/state").get("instances") or {}
    iid = pick_instance(inst)

    print(f"\n实例 {iid} 跑 {ns.entry}")
    print("override:", ov)
    print("已提交:", api(f"/maa/instances/{iid}/tasks/start", {
        "tasks": [{"entry": ns.entry, "pipeline_override": ov}],
        "agent_configs": AGENTS, "cwd": MAAEND, "tcp_compat_mode": False,
        "pi_envs": None, "reset_state": True, "controller_info": None,
    }, timeout=120))

    t0 = time.time()
    try:
        while time.time() - t0 < ns.timeout:
            time.sleep(5)
            cur = (api("/maa/state").get("instances") or {}).get(iid, {})
            if not cur.get("is_running"):
                print(f"\n跑完了，用时 {time.time()-t0:.0f} 秒")
                break
            print(f"  …运行中 {time.time()-t0:.0f}s", flush=True)
        else:
            print(f"\n⚠️ 超时 {ns.timeout}s，停任务")
            api(f"/maa/instances/{iid}/tasks/stop", {})
    finally:
        try:
            api(f"/maa/instances/{iid}/agent/stop", {})
            print("agent 已停")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ 停 agent 失败：{e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
