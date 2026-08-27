#!/usr/bin/env python3
"""单独调用 MaaEnd 的「基质筛选锁定」，不跑整条队列。

在游戏机上跑（winrun 会把它送过去）：

    winrun.sh --py scripts/mac/lib/maaend_essence.py            # 只体检，不动手
    winrun.sh --py scripts/mac/lib/maaend_essence.py --go       # 真跑
    winrun.sh --py scripts/mac/lib/maaend_essence.py --go --also-5star

## 它到底会做什么（源码读出来的，不是猜的）

上游 `assets/tasks/EssenceFilter.json`：任务名 `EssenceFilter`，
入口节点 **`EssenceFilterMain`**，controller 支持 `Win32-Front`。

流程（`assets/resource/pipeline/EssenceFilter.json` + `EntryAndInit.json`）：

1. `EssenceFilterMain` 自己导航——`next` 里挂了 `[JumpBack]SceneEnterMenuValuables`，
   不在基质页就先跳贵重品库，再切「武器库 → 武器基质」页签。
   **所以不要求游戏停在某个界面，但游戏必须在跑、且能开菜单。**
2. C++ `EssenceGridScan` 扫背包网格，按品质和缩略图挑出待处理的格子。
3. Pipeline 对每个格子 OCR 三条技能和等级。
4. Go `matchapi` 拿 OCR 结果去比 `weapons_output.json` 里**该稀有度的全部武器**
   （注意：是全部武器，不是我拥有的），命中 → `ShouldLock` → 点锁。
5. `discard_unmatched` 打开时，没命中的**会被废弃**——本脚本默认关闭，
   而且不提供打开的开关。要废弃自己去 MaaEnd 界面点，别让脚本替你毁东西。

Go 那层只做判断，点击全在 Pipeline（见 `agent/go-service/essencefilter/README.md`）。

## 为什么必须 /tasks/start

`/tasks/run` 不会拉起 `agent/go-service` 和 `agent/cpp-algo` 两个子进程，
而基质筛选的识别、匹配、扫格子全在那两个里面。用 run 会一路
`Action is null`。详见 docs/HEADLESS.md。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

MXU = "http://127.0.0.1:12701/api"
MAS = "http://127.0.0.1:36163"        # AUTO-MAS 的 REST，用来问出游戏真实路径
MAAEND = r"D:\ark\maaend"
ENTRY = "EssenceFilterMain"
AGENTS = [{"child_exec": "agent/go-service"},
          {"child_exec": "agent/cpp-algo", "child_args": []}]
PLAN_HTML = MAAEND + r"\EssencePlan.html"


def api(path: str, body: dict | None = None, timeout: int = 30):
    url = MXU + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def game_exe() -> str | None:
    """从 AUTO-MAS 问出终末地的 exe 路径。**不写死**——2026-08-28 我凭印象
    在 wingui.sh 里填过两条 exe 路径，事后发现那两条只存在于我自己刚写的
    文件里，是纯猜。路径要从真实配置来。"""
    try:
        req = urllib.request.Request(
            MAS + "/api/scripts/get", data=b"{}",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            for sc in json.loads(r.read().decode()).get("data", []):
                if "maaend" in str(sc).lower():
                    for u in (sc.get("user_infos") or {}).values():
                        p = (u.get("Game") or {}).get("Path")
                        if p:
                            return p
    except Exception:  # noqa: BLE001
        pass
    return None


def running_procs() -> set[str]:
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"],
                         capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    return {l.split('","')[0].lstrip('"').lower() for l in out.splitlines() if l}


def preflight() -> tuple[dict, list[str]]:
    """返回 (实例表, 问题清单)。问题清单非空就别跑。"""
    bad = []
    procs = running_procs()
    for name, why in (("maaend.exe", "MaaEnd 的界面/服务（MXU），12701 接口由它提供"),
                      ("endfield.exe", "游戏本体")):
        if name not in procs:
            bad.append(f"{name} 没在跑（{why}）")

    state = {}
    try:
        state = api("/maa/state")
    except Exception as e:  # noqa: BLE001
        bad.append(f"MXU 的 12701 接口连不上：{type(e).__name__}: {e}")

    # 字段名抄自 MXU 的 web_server.rs handle_get_maa_state：
    #   {"instances": {"<id>": {connected, resource_loaded, tasker_inited,
    #                           is_running, task_run_state}}, ...}
    inst = (state or {}).get("instances") or {}
    if not inst:
        bad.append("MXU 里一个实例都没有——先在 MaaEnd 界面里连一次游戏窗口，"
                   "本脚本不新建实例（新实例没连控制器、也没加载资源）")
    elif not any(usable(v) for v in inst.values()):
        bad.append("有实例但都不可用（connected / resource_loaded / tasker_inited "
                   "没齐）——去 MaaEnd 界面点一次连接")
    return inst, bad


def usable(v: dict) -> bool:
    """三个都要真：连了控制器、加载了资源、tasker 初始化过。

    本脚本**不新建实例**——新建的这三样都是假的，跑起来会一路失败。
    """
    return bool(v.get("connected") and v.get("resource_loaded")
                and v.get("tasker_inited"))


def pick_instance(inst: dict) -> str:
    """挑一个可用且当前空闲的实例。"""
    ok = {k: v for k, v in inst.items() if usable(v)}
    if not ok:
        raise SystemExit(
            "没有可用实例（要同时满足 connected / resource_loaded / tasker_inited）。"
            "先在 MaaEnd 界面里连一次游戏窗口。")
    free = [k for k, v in ok.items() if not v.get("is_running")]
    if not free:
        raise SystemExit(f"实例都在忙（{list(ok)}）。等它跑完，或去 MaaEnd 界面停掉，"
                         f"别抢——抢了会把正在跑的队列搅乱。")
    return free[0]


def override(six_only: bool, flawless_only: bool, export_plan: bool) -> str:
    """构造 pipeline_override。键名抄自 assets/tasks/EssenceFilter.json 的
    每个 case 的 pipeline_override.attach，不是我起的名字。"""
    return json.dumps({
        "EssenceFilterInit": {"attach": {
            "input_language": "CN",              # 必须和游戏内界面语言一致
            "rarity6_weapon": True,
            "rarity5_weapon": not six_only,
            "rarity4_weapon": False,
            "flawless_essence": True,            # 无瑕（金色五星）
            "pure_essence": not flawless_only,   # 高纯（紫色）
            "keep_future_promising": False,
            "keep_slot3_level3_practical": False,
            "discard_unmatched": False,          # ← 故意写死。不给开关。
            "export_calculator_script": export_plan,
        }},
        "EssenceGridAdvance": {"attach": {
            "skip_thumb_lock": True,             # 已锁的跳过，省时间
            "skip_thumb_discard": True,          # 已废弃的跳过
        }},
    }, ensure_ascii=False)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="真跑；不加只体检")
    ap.add_argument("--also-5star", action="store_true",
                    help="连 5★ 武器的组合一起算命中")
    ap.add_argument("--also-pure", action="store_true",
                    help="连高纯（紫）基质一起筛，默认只筛无瑕（金）")
    ap.add_argument("--timeout", type=int, default=900,
                    help="最长等待秒数，默认 900")
    ns = ap.parse_args(argv[1:])

    inst, bad = preflight()
    print(f"[机器时间] {time.strftime('%m-%d %H:%M:%S')}")
    print(f"MXU 实例 {len(inst)} 个：")
    for k, v in inst.items():
        print(f"  {k}  连接={v.get('connected')} 资源={v.get('resource_loaded')} "
              f"tasker={v.get('tasker_inited')} 在跑={v.get('is_running')}")
    if bad:
        print("\n❌ 还不能跑：")
        for b in bad:
            print("  · " + b)
        exe = game_exe()
        print("\n补救（图形程序必须从 session 1 起，见 memory relay-runs-in-session-0）：")
        print(f"  游戏：wingui.sh launch '{exe}'" if exe else
              "  游戏：AUTO-MAS 问不出 Game.Path，先确认 AUTO-MAS 在跑（36163）")
        print("  MaaEnd：exe 路径同样别猜，先 winps.sh 列一下 D:\\ark\\maaend 下的 *.exe")
        return 1
    print("\n✅ 前置条件都满足")

    if not ns.go:
        print("\n（只是体检。要真跑加 --go）")
        return 0

    iid = pick_instance(inst)
    ov = override(not ns.also_5star, not ns.also_pure, export_plan=True)
    print(f"\n用实例 {iid} 跑 {ENTRY}")
    print("override:", ov)

    res = api(f"/maa/instances/{iid}/tasks/start", {
        "tasks": [{"entry": ENTRY, "pipeline_override": ov}],
        "agent_configs": AGENTS,
        "cwd": MAAEND,
        "tcp_compat_mode": False,
        "pi_envs": None,
        "reset_state": True,
        "controller_info": None,
    }, timeout=120)
    print("已提交：", res)

    t0 = time.time()
    try:
        while time.time() - t0 < ns.timeout:
            time.sleep(5)
            st = api("/maa/state")
            cur = (st.get("instances") or {}).get(iid, {})
            if not cur.get("is_running"):
                print(f"\n跑完了，用时 {time.time()-t0:.0f} 秒")
                break
            print(f"  …运行中 {time.time()-t0:.0f}s", flush=True)
        else:
            print(f"\n⚠️ 等了 {ns.timeout} 秒还没结束，去停任务")
            api(f"/maa/instances/{iid}/tasks/stop", {})
    finally:
        try:
            api(f"/maa/instances/{iid}/agent/stop", {})
            print("agent 已停（不停会一直挂着两个子进程）")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ 停 agent 失败：{e}")

    # 运行日志（focus 文案都在这儿：匹配摘要、锁了几个、预刻写建议）
    try:
        logs = api("/logs")
        lines = logs.get(iid) if isinstance(logs, dict) else None
        if lines is None and isinstance(logs, dict):
            lines = sum((v for v in logs.values() if isinstance(v, list)), [])
        lines = lines or []
        keep = [str(l) for l in lines
                if any(k in str(l) for k in
                       ("基质", "锁", "废弃", "匹配", "刻写", "初始化完成", "完成"))]
        print(f"\n运行日志里相关的 {len(keep)} 行（共 {len(lines)} 行）：")
        for l in keep[-40:]:
            print("  " + l[:200])
    except Exception as e:  # noqa: BLE001
        print(f"\n⚠️ 取运行日志失败：{type(e).__name__}: {e}")

    from pathlib import Path
    p = Path(PLAN_HTML)
    if p.is_file():
        print(f"\nEssencePlan.html 已生成，{p.stat().st_size} 字节 → {PLAN_HTML}")
        print("  取回：winrun.sh --get '" + PLAN_HTML + "'")
    else:
        print(f"\nEssencePlan.html 没生成（{PLAN_HTML}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
