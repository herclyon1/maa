"""MaaEnd 的理智到底花在哪——读写**真正生效**的那一份。

**2026-08-28 改：直接读写 MaaEnd 母本，不再走 AUTO-MAS 的 ScriptConfig。**

原先写的是 MAS 用户配置的 `Task.SanityTaskType`，那条路要求
`Info.IfQuickConfig` 开着才会被下发到 MaaEnd。快速配置当天被废掉
（它只能开关**已存在**的任务、还制造静默故障：母本里没有 `AutoEssence`
时选「基质刷取」会被整段跳过，而界面标签照样显示已生效），
于是这个模块整个失效了。

现在直接改母本
`<automas>/data/<脚本id>/Default/ConfigFile/mxu-MaaEnd.json`：
理智任务就是 AUTO-MAS 实例里 `ProtocolSpace` 和 `AutoEssence` 这两个任务，
谁 `enabled` 谁就是当前方案。这条路不依赖快速配置——母本目录是
AUTO-MAS 每轮**无条件**拷给 MaaEnd 的那一份。

以下是旧实现的背景，留着当教训：AUTO-MAS 开着快速配置时会这样重写：

    task["optionValues"]["ProtocolSpaceTab"] = {"caseName": sanity_task_type}
    for option in ("OperatorProgression", "WeaponProgression", "CrisisDrills"):
        task["optionValues"][option] = {"caseName": sanity_task_config[option]}
    ...then derives the reward-set option from RewardsSetOption

So an edit made in MaaEnd's UI survives exactly until the next run. That is not
a theory: it is what happened to the change made on this machine at 12:34 on
2026-08-16, and it is what would have happened to the queued change applied at
22:42 the same day. Both wrote to the copy that gets overwritten.

Three fields decide everything, and the reward is derived rather than chosen:

    SanityTaskType   which tab      OperatorProgression / WeaponProgression /
                                    CrisisDrills / Essence
    <that tab>       which line     e.g. OperatorProgression -> OperatorEXP
    RewardsSetOption A or B         A and B mean different items per line

    OperatorEXP  + A -> 高级认知载体、初级认知载体   + B -> 高级作战记录
    Promotions   + A -> 协议圆盘组                 + B -> 协议圆盘
    SkillUp      + A -> 协议棱柱组                 + B -> 协议棱柱
    WeaponTune   + A -> 重型强固模具               + B -> 强固模具
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ, atomic_write_text, master_config_dir

log = logging.getLogger("ark.sanity")

TAB_LABELS = {
    "OperatorProgression": "干员养成",
    "WeaponProgression": "武器养成",
    "CrisisDrills": "危境预演",
    "Essence": "基质刷取",
}

LINE_OPTIONS = {
    "OperatorProgression": ("OperatorEXP", "Promotions", "T-Creds", "SkillUp"),
    "WeaponProgression": ("WeaponEXP", "WeaponTune"),
    "CrisisDrills": ("AdvancedProgression1", "AdvancedProgression2",
                     "AdvancedProgression3", "AdvancedProgression4",
                     "AdvancedProgression5"),
}

LOCATION_LABELS = {
    "VFTheHub": "枢纽区", "VFOriginiumSciencePark": "源石研究园",
    "VFOriginLodespring": "矿脉源区", "VFPowerPlateau": "供能高地",
    "WLWulingCity": "武陵城区", "WLQingboStockade": "清波寨",
    "WLMarkerStone": "首墩", "WLTestArea": "试验园区",
    "WLSwordVaultDale": "藏剑谷", "WLYinglungPass": "应龙关",
    "WLNorthWulingExclusionZone": "北部禁区",
}

LINE_LABELS = {
    "OperatorEXP": "干员经验", "Promotions": "干员进阶",
    "T-Creds": "钱币收集", "SkillUp": "技能提升",
    "WeaponEXP": "武器经验", "WeaponTune": "武器进阶",
    "AdvancedProgression1": "高阶培养Ⅰ（D96钢样品四）",
    "AdvancedProgression2": "高阶培养Ⅱ（超距辉映管）",
    "AdvancedProgression3": "高阶培养Ⅲ（快子遴捡晶格）",
    "AdvancedProgression4": "高阶培养Ⅳ（象限拟合液）",
    "AdvancedProgression5": "高阶培养Ⅴ（三相纳米片）",
}

# Mirrors AutoProxy.py's own branching, so the report says what will really
# drop rather than which radio button is selected.
REWARD = {
    ("OperatorEXP", "RewardsSetA"): "高级认知载体、初级认知载体",
    ("OperatorEXP", "RewardsSetB"): "高级作战记录",
    ("Promotions", "RewardsSetA"): "协议圆盘组",
    ("Promotions", "RewardsSetB"): "协议圆盘",
    ("SkillUp", "RewardsSetA"): "协议棱柱组",
    ("SkillUp", "RewardsSetB"): "协议棱柱",
    ("WeaponTune", "RewardsSetA"): "重型强固模具",
    ("WeaponTune", "RewardsSetB"): "强固模具",
}


MARKER = "mxu-MaaEnd.json"
SANITY_TASKS = ("ProtocolSpace", "AutoEssence")


def _master(automas_dir) -> "Path | None":
    d = master_config_dir(automas_dir, MARKER)
    return (d / MARKER) if d else None


def _automas_instance(data: dict) -> dict | None:
    for ins in data.get("instances") or []:
        if ins.get("id") == "automas" or ins.get("name") == "AUTO-MAS":
            return ins
    return None


def _case(ov: dict, key: str) -> str:
    v = ov.get(key)
    return str(v.get("caseName") or "") if isinstance(v, dict) else ""


def read(automas_dir: "Path | None") -> dict:
    """当前方案：{tab, line, rewards_set, item, label}。读不了返回 {}。"""
    f = _master(automas_dir)
    if f is None:
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    ins = _automas_instance(data)
    if not ins:
        return {}
    on = [t for t in ins.get("tasks") or []
          if t.get("taskName") in SANITY_TASKS and t.get("enabled")]
    if not on:
        return {"tab": "", "line": "", "rewards_set": "", "item": "",
                "enabled": False, "label": "理智任务全部关闭"}
    t = on[0]
    ov = t.get("optionValues") or {}
    if t["taskName"] == "AutoEssence":
        loc = (ov.get("AutoEssenceChooseLocation") or {}).get("caseNames") or []
        parts = ["基质刷取"] + [LOCATION_LABELS.get(x, x) for x in loc]
        return {"tab": "Essence", "line": "", "rewards_set": "", "item": "",
                "enabled": True, "locations": list(loc),
                "label": " → ".join(parts)}
    tab = _case(ov, "ProtocolSpaceTab")
    line = _case(ov, tab) if tab else ""
    rset = _case(ov, f"{line}RewardsSetOption") or _case(ov, "RewardsSetOption")
    item = REWARD.get((line, rset), "")
    parts = [TAB_LABELS.get(tab, tab)]
    if line:
        parts.append(LINE_LABELS.get(line, line))
    if item:
        parts.append(item)
    return {"tab": tab, "line": line, "rewards_set": rset, "item": item,
            "enabled": True, "label": " → ".join(p for p in parts if p)}


def set_plan(automas_dir: "Path | None", tab: str, line: str = "",
             rewards_set: str = "", location: str = "") -> tuple[bool, str]:
    """把方案写进母本——AUTO-MAS 每轮拷给 MaaEnd 的那一份。

    `tab == "Essence"` → 开 `AutoEssence`、关 `ProtocolSpace`；
    其余 → 开 `ProtocolSpace` 并写它的下拉项、关 `AutoEssence`。
    **只切换已存在的任务，不新建**：母本里没有 `AutoEssence` 却选基质刷取，
    正是 2026-08-28 那个「界面显示已生效、实际整段跳过」的静默故障。
    """
    if tab not in TAB_LABELS:
        return False, f"理智任务类型不合法: {tab!r}（可选 {'、'.join(TAB_LABELS)}）"
    if tab != "Essence" and line:
        legal = LINE_OPTIONS.get(tab, ())
        if legal and line not in legal:
            return False, f"{TAB_LABELS[tab]} 不接受 {line!r}（可选 {'、'.join(legal)}）"
    if rewards_set and rewards_set not in ("RewardsSetA", "RewardsSetB"):
        return False, f"奖励组不合法: {rewards_set!r}（只能 RewardsSetA / RewardsSetB）"

    f = _master(automas_dir)
    if f is None:
        return False, f"找不到 MaaEnd 母本 {MARKER}"
    before_label = read(automas_dir).get("label", "")
    try:
        original = f.read_text(encoding="utf-8")
        data = json.loads(original)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"读不了母本: {exc}"
    ins = _automas_instance(data)
    if not ins:
        return False, "母本里找不到 AUTO-MAS 实例"

    want_task = "AutoEssence" if tab == "Essence" else "ProtocolSpace"
    have = {t.get("taskName"): t for t in ins.get("tasks") or []}
    if want_task not in have:
        return False, (f"母本里没有 {want_task} 任务，拒绝新建——"
                       f"先在 MaaEnd 界面加上并同步进母本")

    changes: list[str] = []
    for name in SANITY_TASKS:
        t = have.get(name)
        if t is None:
            continue
        want_on = name == want_task
        if bool(t.get("enabled")) != want_on:
            changes.append(f"{name}: {'开' if want_on else '关'}")
            t["enabled"] = want_on

    ov = have[want_task].setdefault("optionValues", {})
    if tab == "Essence":
        if location:
            cur = (ov.get("AutoEssenceChooseLocation") or {}).get("caseNames") or []
            if cur != [location]:
                changes.append(f"地点: {cur} → [{location}]")
                ov["AutoEssenceChooseLocation"] = {"type": "checkbox",
                                                   "caseNames": [location]}
    else:
        for key, want in (("ProtocolSpaceTab", tab), (tab, line),
                          (f"{line}RewardsSetOption" if line else "", rewards_set)):
            if not key or not want:
                continue
            if key not in ov:
                # 母本里没有的键凭空造出来，MaaEnd 那边不认，等于白写。
                return False, f"母本的 {want_task} 里没有字段 {key!r}，拒绝新建"
            if _case(ov, key) != want:
                changes.append(f"{key}: {_case(ov, key)} → {want}")
                ov[key] = {"type": "select", "caseName": want}

    if not changes:
        return True, "已经是这个方案，无需改动"

    stamp = datetime.now(tz=SERVER_TZ)
    backup = f.with_suffix(f".json.bak-{stamp:%Y%m%d-%H%M%S}")
    shutil.copy2(f, backup)
    try:
        atomic_write_text(f, json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as exc:
        shutil.copy2(backup, f)
        return False, f"写入失败，已回滚: {exc}"
    log.info("理智方案改动: %s", "；".join(changes))
    return True, (f"{before_label or '(未知)'}\n改成 {read(automas_dir).get('label', '?')}"
                  f"\n（备份 {backup.name}）")
