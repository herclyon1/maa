"""What MaaEnd will actually spend sanity on - read and written where it counts.

MaaEnd's own config is not the authority. With AUTO-MAS's "quick config" on -
which it is here - AutoProxy.py rewrites MaaEnd's optionValues from AUTO-MAS's
ScriptConfig every time it launches the script:

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

from .config import SERVER_TZ

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


def _script_config(automas_dir: Path) -> Path:
    return Path(automas_dir) / "config" / "ScriptConfig.json"


def _maaend_node(data: dict) -> tuple[str, dict] | None:
    """The MaaEnd script's user-data node, found by install path."""
    for inst in data.get("instances", []):
        uid = inst.get("uid")
        node = data.get(uid) or {}
        path = ((node.get("Info") or {}).get("Path") or "").lower()
        if "maaend" not in path:
            continue
        for sub_uid, user in ((node.get("SubConfigsInfo") or {}).get("UserData") or {}).items():
            if sub_uid == "instances" or not isinstance(user, dict):
                continue
            return uid, user
    return None


def read(automas_dir: Path | None) -> dict:
    """Current plan: {tab, line, rewards_set, item, quick, label}. {} if unreadable."""
    if not automas_dir:
        return {}
    path = _script_config(automas_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    found = _maaend_node(data)
    if not found:
        return {}
    _, user = found
    task = user.get("Task") or {}
    tab = task.get("SanityTaskType") or ""
    line = task.get(tab) or ""
    rset = task.get("RewardsSetOption") or ""
    item = REWARD.get((line, rset), "")
    parts = [TAB_LABELS.get(tab, tab)]
    if line:
        parts.append(LINE_LABELS.get(line, line))
    if item:
        parts.append(item)
    return {
        "tab": tab, "line": line, "rewards_set": rset, "item": item,
        "quick": bool((user.get("Info") or {}).get("IfQuickConfig")),
        "enabled": bool(task.get("IfSanity")),
        # The whole chain, because the tab alone reads as the answer and is not:
        # "干员养成" does not tell you whether that means 经验 or 进阶, and the
        # reward set decides which item actually drops.
        "label": " → ".join(p for p in parts if p),
    }


def set_plan(automas_dir: Path, tab: str, line: str = "",
             rewards_set: str = "") -> tuple[bool, str]:
    """Write the plan into AUTO-MAS - the copy that survives the next launch."""
    if tab not in TAB_LABELS:
        return False, f"理智任务类型不合法: {tab!r}（可选 {'、'.join(TAB_LABELS)}）"
    if line:
        legal = LINE_OPTIONS.get(tab, ())
        if legal and line not in legal:
            return False, f"{TAB_LABELS[tab]} 不接受 {line!r}（可选 {'、'.join(legal)}）"
    if rewards_set and rewards_set not in ("RewardsSetA", "RewardsSetB"):
        return False, f"奖励组不合法: {rewards_set!r}（只能 RewardsSetA / RewardsSetB）"

    before_label = read(automas_dir).get("label", "")
    path = _script_config(automas_dir)
    try:
        original = path.read_text(encoding="utf-8")
        data = json.loads(original)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"读不了 ScriptConfig: {exc}"
    found = _maaend_node(data)
    if not found:
        return False, "ScriptConfig 里找不到 MaaEnd 脚本"
    _, user = found
    task = user.setdefault("Task", {})

    changes: list[str] = []
    for key, want in (("SanityTaskType", tab), (tab, line),
                      ("RewardsSetOption", rewards_set)):
        if not want:
            continue
        if key not in task:
            # AUTO-MAS writes every field it understands, so a missing key means
            # this build does not have it - inventing it would be ignored.
            return False, f"AUTO-MAS 配置里没有字段 {key!r}，拒绝新建"
        if task[key] != want:
            changes.append(f"{key}: {task[key]} → {want}")
            task[key] = want

    if not changes:
        return True, "已经是这个方案，无需改动"

    stamp = datetime.now(tz=SERVER_TZ)
    backup = path.with_suffix(f".bak-{stamp:%Y%m%d-%H%M%S}.json")
    shutil.copy2(path, backup)
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except OSError as exc:
        shutil.copy2(backup, path)
        return False, f"写入失败，已回滚: {exc}"
    after = read(automas_dir)
    # Internal names are what the file holds and what a bug report needs, but
    # they are not what the operator reads on their phone at midnight. The push
    # gets the human chain; the log keeps the raw field names.
    log.info("理智方案改动: %s", "；".join(changes))
    return True, (f"{before_label or '(未知)'}\n改成 {after.get('label', '?')}"
                  f"\n（备份 {backup.name}）")
