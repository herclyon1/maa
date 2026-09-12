"""Where MaaEnd's sanity actually goes -- read and write the copy that **really
takes effect**.

**Changed 2026-08-28: read and write the MaaEnd master copy directly, no longer via
AUTO-MAS's ScriptConfig.**

It used to write `Task.SanityTaskType` in the MAS user config, but that path only
gets pushed down to MaaEnd when `Info.IfQuickConfig` is on. Quick config was
abolished that day (it can only toggle tasks that **already exist**, and it creates
silent failures: with no `AutoEssence` in the master copy, selecting 「基质刷取」 is
skipped entirely while the UI label still shows it as in effect), so this whole
module stopped working.

It now edits the master copy directly:
`<automas>/data/<script id>/Default/ConfigFile/mxu-MaaEnd.json`. The sanity tasks are
the `ProtocolSpace` and `AutoEssence` tasks in the AUTO-MAS instance; whichever one
is `enabled` is the current plan. This path does not depend on quick config -- the
master directory is the one AUTO-MAS copies over to MaaEnd **unconditionally** every
run.

What follows is background on the old implementation, kept as a lesson. With quick
config on, AUTO-MAS rewrites it like this:

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
import shutil
from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ, atomic_write_text, master_config_dir

log = logging.getLogger("ark.sanity_plan")

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
    """The current plan: {tab, line, rewards_set, item, label}. {} if unreadable."""
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


def _validate_plan(tab: str, line: str, rewards_set: str) -> str | None:
    """Check the three arguments first; return an error text, or None if all legal.

    This is a separate step because it does not touch the master copy at all -- it is
    purely "are these three values legal in themselves", and it must run to completion
    before anything reads or writes the master copy: these three values decide where
    tomorrow's sanity goes, and letting an illegal value reach the write is already
    too late.
    """
    if tab not in TAB_LABELS:
        return f"理智任务类型不合法: {tab!r}（可选 {'、'.join(TAB_LABELS)}）"
    if tab != "Essence" and line:
        legal = LINE_OPTIONS.get(tab, ())
        if legal and line not in legal:
            return f"{TAB_LABELS[tab]} 不接受 {line!r}（可选 {'、'.join(legal)}）"
    if rewards_set and rewards_set not in ("RewardsSetA", "RewardsSetB"):
        return f"奖励组不合法: {rewards_set!r}（只能 RewardsSetA / RewardsSetB）"
    return None


def _toggle_sanity_tasks(have: dict, want_task: str, changes: list[str]) -> None:
    """Enable want_task, disable the other sanity task; record edits in changes.

    This is a separate step because "whichever one is enabled is the current plan" is
    this module's fundamental criterion. It touches only the enabled field and shares
    no intermediate state with the code below that writes the dropdowns.
    A task that does not exist in the master copy is skipped here -- **only toggle
    tasks that already exist, never create them**.
    """
    for name in SANITY_TASKS:
        t = have.get(name)
        if t is None:
            continue
        want_on = name == want_task
        if bool(t.get("enabled")) != want_on:
            changes.append(f"{name}: {'开' if want_on else '关'}")
            t["enabled"] = want_on


def _write_options(ov: dict, want_task: str, tab: str, line: str,
                   rewards_set: str, location: str,
                   changes: list[str]) -> str | None:
    """Write the locations/dropdowns into the chosen task's optionValues.

    Edits are recorded in changes.

    This is a separate step because essence farming and protocol space part ways
    completely here: one writes location checkboxes, the other writes three linked
    dropdowns, and every one of the latter must first confirm the key already exists
    in the master copy.
    Returns an error text, or None when there is no error.
    """
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
                # A key invented out of thin air is not recognised by MaaEnd, so
                # writing it would achieve nothing.
                return f"母本的 {want_task} 里没有 {key!r} 这一项，中继不会自己新建，拒绝"
            if _case(ov, key) != want:
                changes.append(f"{key}: {_case(ov, key)} → {want}")
                ov[key] = {"type": "select", "caseName": want}
    return None


def set_plan(automas_dir: "Path | None", tab: str, line: str = "",
             rewards_set: str = "", location: str = "") -> tuple[bool, str]:
    """Write the plan into the master copy.

    That is the copy AUTO-MAS hands to MaaEnd every run.

    `tab == "Essence"` -> enable `AutoEssence`, disable `ProtocolSpace`;
    anything else -> enable `ProtocolSpace` and write its dropdowns, disable
    `AutoEssence`.
    **Only toggle tasks that already exist, never create them**: selecting essence
    farming when the master copy has no `AutoEssence` is exactly the silent failure of
    2026-08-28 where the UI showed it as in effect while the whole thing was skipped.
    """
    if err := _validate_plan(tab, line, rewards_set):
        return False, err

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
        return False, "母本里找不到 AUTO-MAS 登记的那个终末地配置"

    want_task = "AutoEssence" if tab == "Essence" else "ProtocolSpace"
    have = {t.get("taskName"): t for t in ins.get("tasks") or []}
    if want_task not in have:
        return False, (f"母本里没有 {want_task} 任务，拒绝新建——"
                       f"先在 MaaEnd 界面加上并同步进母本")

    changes: list[str] = []
    _toggle_sanity_tasks(have, want_task, changes)

    ov = have[want_task].setdefault("optionValues", {})
    if err := _write_options(ov, want_task, tab, line, rewards_set, location,
                             changes):
        return False, err

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
