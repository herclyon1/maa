#!/usr/bin/env python3
"""三个脚本**实际会跑什么**——按 IfQuickConfig 分别取真正生效的那一份。

    winrun.sh --py scripts/mac/lib/effective_config.py

**为什么不能只看 MAS**（2026-08-28）：

MaaEnd 和 OK-WW 的 `Info.IfQuickConfig` 关掉之后，MAS 用户配置里那些
`If<任务名>` / 理智任务 / 基质地点 / OK-WW 的六个键**全部不再生效**，
真正说了算的是各自的母本配置。`config-check.py` 只读 MAS 侧，
关掉快速配置之后它报的东西会误导人。

MAA 没有快速配置机制（`Info.IfQuickConfig` 恒为 None），永远由 MAS 驱动；
但它的日常理智药**不在**用户配置里，而在计划表 `PlanConfig.json` 的
`MedicineNumb`——见 memory `maa-stage-and-medicine-fields`（826 事故的正解）。
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

MAS = "http://127.0.0.1:36163"
DATA = Path(r"D:\ark\automas\data")


def post(p: str, b: dict | None = None):
    r = urllib.request.Request(MAS + p, data=json.dumps(b or {}).encode(),
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=20).read().decode())


def head(t: str) -> None:
    print(f"\n{'='*66}\n{t}\n{'='*66}")


def main() -> int:
    scripts = post("/api/scripts/get")["data"]
    by_name = {(s.get("Info") or {}).get("Name"): (uid, s) for uid, s in scripts.items()}

    for name in ("MAA", "MaaEnd", "OK-WW"):
        if name not in by_name:
            print(f"⚠️ 没有名为 {name} 的脚本"); continue
        sid, sc = by_name[name]
        users = post("/api/scripts/user/get", {"scriptId": sid})["data"]
        uid, u = next(iter(users.items()))
        info, task = u["Info"], u.get("Task") or {}
        qc = info.get("IfQuickConfig")
        head(f"{name}　用户「{info.get('Name')}」　IfQuickConfig={qc!r}")

        if name == "MAA":
            print("  MAA 没有快速配置机制，以下 MAS 字段全部生效：")
            print(f"    作战开关 IfFight      = {task.get('IfFight')}")
            print(f"    关卡 Info.Stage       = {info.get('Stage')}")
            print(f"    关卡模式 StageMode    = {info.get('StageMode')}")
            print(f"    连战 SeriesNumb       = {info.get('SeriesNumb')}")
            print(f"    剿灭 Annihilation     = {info.get('Annihilation')}")
            print(f"    活动关优先            = {task.get('IfActivityFirst')}"
                  f"（序号 {task.get('ActivityStageIndex')}，1 起算；"
                  f"药 {task.get('ActivityMedicineNumb')}）")
            if task.get("IfActivityFirst"):
                print("    ⚠️ 开着活动关优先 → 「理智作战」的理智药会被清零")
            # 日常那条的药量取哪儿，**看 StageMode**（AutoProxy.py:727-739）：
            #   StageMode == "Fixed"  → plan_data 全部取 Info.*，用 Info.MedicineNumb
            #   否则                   → StageMode 是计划表的 UUID，读 PlanConfig
            # 2026-08-28 更正：memory maa-stage-and-medicine-fields 只写了后一个
            # 分支，说「日常那条的药在计划表」——在 Fixed 模式下是错的。
            mode = info.get("StageMode")
            if mode == "Fixed":
                print("    ▶ Fixed 模式 → 关卡和药量都取 Info.*")
                print(f"      Stage={info.get('Stage')!r} "
                      f"Stage_1/2/3={[info.get(f'Stage_{n}') for n in (1,2,3)]}")
                print(f"      **MedicineNumb = {info.get('MedicineNumb')}**"
                      f"（>0 就会 UseMedicine=True，即吃药）")
                print(f"      SeriesNumb={info.get('SeriesNumb')!r}")
            else:
                plan = Path(r"D:\ark\automas\config\PlanConfig.json")
                print(f"    ▶ 计划表模式（StageMode={mode}）→ 读 {plan}")
                if plan.is_file():
                    d = json.loads(plan.read_text(encoding="utf-8"))
                    cfg = d.get(str(mode)) or {}
                    for day, c in cfg.items():
                        if isinstance(c, dict) and "MedicineNumb" in c:
                            print(f"      {day:<10} Stage={c.get('Stage')!r:<8} "
                                  f"MedicineNumb={c.get('MedicineNumb')} "
                                  f"SeriesNumb={c.get('SeriesNumb')!r}")

        elif name == "MaaEnd":
            f = Path(DATA, sid, "Default", "ConfigFile", "mxu-MaaEnd.json")
            d = json.loads(f.read_text(encoding="utf-8"))
            ins = next(i for i in d["instances"]
                       if i.get("id") == "automas" or i.get("name") == "AUTO-MAS")
            on = [t for t in ins["tasks"]
                  if t.get("enabled") and not t["taskName"].startswith("__")]
            print(f"  快速配置{'开' if qc else '关'} → "
                  f"{'MAS 的 If* 开关生效' if qc else '**以 MaaEnd 母本为准**'}")
            print(f"  母本启用 {len(on)} 个任务：")
            print("    " + "、".join(t["taskName"] for t in on))
            for t in on:
                if t["taskName"] in ("ProtocolSpace", "AutoEssence"):
                    ov = t.get("optionValues") or {}
                    print(f"  理智任务 = {t['taskName']}")
                    for k in ("ProtocolSpaceTab", "OperatorProgression", "ProtocolSpaceLevel",
                              "ProtocolSpaceUsePermit", "AutoEssenceChooseLocation",
                              "AutoEssenceObtainMode", "AutoEssenceDoOverride",
                              "AutoEssenceRepeatCount"):
                        if k in ov:
                            print(f"      {k:<28} {json.dumps(ov[k], ensure_ascii=False)}")
            if not qc:
                dead = [k for k in task if k.startswith("If")] + \
                       ["SanityTaskType", "AutoEssenceSpecifiedLocation"]
                print(f"  ⚠️ MAS 侧这些字段已不生效：{'、'.join(sorted(set(dead)))}")

        else:  # OK-WW
            cfg = Path(DATA, sid, "Default", "ConfigFile")
            print(f"  快速配置{'开' if qc else '关'} → "
                  f"{'MAS 的 Task.* 会覆盖 6 个键' if qc else '**以母本为准，无覆盖**'}")
            for fn in ("DailyTask", "NightmareNestTask", "Basic Options"):
                p = cfg / f"{fn}.json"
                if not p.is_file():
                    print(f"  {fn}: 文件不在"); continue
                d = json.loads(p.read_text(encoding="utf-8"))
                print(f"  {fn}:")
                for k, v in d.items():
                    print(f"      {k:<44} {json.dumps(v, ensure_ascii=False)[:60]}")
            print(f"  MAS 侧 TaskIndex = {task.get('TaskIndex')}"
                  f"（启动参数 -t，这个**始终生效**）")

    head("队列")
    for qid, q in post("/api/queue/get")["data"].items():
        i = q["Info"]
        times = post("/api/queue/time/get", {"queueId": qid})["data"]
        items = post("/api/queue/item/get", {"queueId": qid})["data"]
        names = []
        for it in items.values():
            s = scripts.get(it["Info"]["ScriptId"])
            names.append((s.get("Info") or {}).get("Name", "?") if s else "?")
        for t in times.values():
            ti = t["Info"]
            print(f"  {i['Name']:<14} {ti['Time']}  Enabled={ti['Enabled']}  "
                  f"→ {'、'.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
