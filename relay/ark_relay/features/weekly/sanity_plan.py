"""Where MaaEnd's sanity goes: read and write MaaEnd's master copy.

The file is `<automas>/data/<script id>/Default/ConfigFile/mxu-MaaEnd.json`. The
sanity tasks are `ProtocolSpace` and `AutoEssence` in the AUTO-MAS instance; the one
that is `enabled` is the current plan. AUTO-MAS copies this master folder over
MaaEnd's config before every run whether or not quick config is on, so a write here
is what MaaEnd runs with. An edit made in MaaEnd's own UI is overwritten by that copy
at the next run. The MAS user config's `Task.SanityTaskType` reaches MaaEnd only when
`Info.IfQuickConfig` is on, so it is not used.

Three of ProtocolSpace's options decide what the sanity buys:

    ProtocolSpaceTab               which tab    OperatorProgression /
                                                WeaponProgression / CrisisDrills
    <that tab>                     which line   e.g. OperatorProgression -> OperatorEXP
    <line>RewardsSetOption         which item   one case per line, MaaEnd's own names

    OperatorEXP  CognitiveCarriers -> 高级认知载体、初级认知载体
                 AdvancedCombatRecord -> 高级作战记录
    Promotions   Protoset -> 协议圆盘组        Protodisk -> 协议圆盘
    SkillUp      Protohedron -> 协议棱柱组     Protoprism -> 协议棱柱
    WeaponTune   HeavyCastDie -> 重型强固模具  CastDie -> 强固模具

The case names and labels are MaaEnd's (tasks/ProtocolSpace.json and
locales/interface/zh_cn.json; fixtures/maaend-protocolspace-v2.30.0-rc.1).
AUTO-MAS's "RewardsSetA / RewardsSetB" belong to its quick-config field and are
not values MaaEnd's master copy holds.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from ark_relay.core.config import SERVER_TZ, atomic_write_text, master_config_dir

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

# (line, MaaEnd's case of f"{line}RewardsSetOption") -> the item that drops, in
# MaaEnd's own Chinese without its "A." / "B." prefix
# (tests/test_sanity_plan_reward_names.py checks it against the v2.30.0-rc.1 files).
REWARD = {
    ("OperatorEXP", "CognitiveCarriers"): "高级认知载体、初级认知载体",
    ("OperatorEXP", "AdvancedCombatRecord"): "高级作战记录",
    ("Promotions", "Protoset"): "协议圆盘组",
    ("Promotions", "Protodisk"): "协议圆盘",
    ("SkillUp", "Protohedron"): "协议棱柱组",
    ("SkillUp", "Protoprism"): "协议棱柱",
    ("WeaponTune", "HeavyCastDie"): "重型强固模具",
    ("WeaponTune", "CastDie"): "强固模具",
}


MARKER = "mxu-MaaEnd.json"
SANITY_TASKS = ("ProtocolSpace", "AutoEssence")


def _maaend_dir(automas_dir) -> "Path | None":
    """MaaEnd's install, where AUTO-MAS says it is (as config.py finds it)."""
    from ark_relay.core import plan  # noqa: PLC0415 - plan imports this module
    return plan.script_dir(automas_dir, "MaaEnd")


def _reward_cases(maaend_dir, line: str) -> "tuple[str, ...] | None":
    """The cases MaaEnd defines for f"{line}RewardsSetOption"; () when the line has
    no reward set, None when MaaEnd's definitions cannot be read."""
    from ark_relay.core import mastercfg  # noqa: PLC0415 - imported where used, as plan.py does
    opts = mastercfg._maaend_defs(maaend_dir)[0] if maaend_dir else {}
    if not opts:
        return None
    opt = opts.get(f"{line}RewardsSetOption") or {}
    return tuple(str(c.get("name")) for c in opt.get("cases") or [] if c.get("name"))


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


def _describe(t: dict) -> dict:
    """One enabled sanity task as {tab, line, rewards_set, item, enabled, label}.

    A ProtocolSpace tab this module does not know is not passed through as if
    it were a plan: the label says it could not be read (model: _write_options
    refusing an unknown key) and `understood` is False.
    """
    ov = t.get("optionValues") or {}
    if t["taskName"] == "AutoEssence":
        loc = (ov.get("AutoEssenceChooseLocation") or {}).get("caseNames") or []
        parts = ["基质刷取"] + [LOCATION_LABELS.get(x, x) for x in loc]
        return {"tab": "Essence", "line": "", "rewards_set": "", "item": "",
                "enabled": True, "locations": list(loc), "understood": True,
                "label": " → ".join(parts)}
    tab = _case(ov, "ProtocolSpaceTab")
    # ProtocolSpaceTab's cases are OperatorProgression / WeaponProgression /
    # CrisisDrills (fixtures/maaend-protocolspace-v2.30.0-rc.1); "Essence" is
    # AutoEssence's job, never a ProtocolSpace tab.
    if tab not in TAB_LABELS or tab == "Essence":
        what = f"页签是 {tab!r}" if tab else "没有选页签"
        return {"tab": tab, "line": "", "rewards_set": "", "item": "",
                "enabled": True, "understood": False,
                "label": f"读不懂：ProtocolSpace {what}，不知道理智会用在哪"}
    line = _case(ov, tab)
    rset = _case(ov, f"{line}RewardsSetOption")
    item = REWARD.get((line, rset), "")
    parts = [TAB_LABELS[tab]]
    if line:
        parts.append(LINE_LABELS.get(line, line))
    if item:
        parts.append(item)
    return {"tab": tab, "line": line, "rewards_set": rset, "item": item,
            "enabled": True, "understood": True,
            "label": " → ".join(p for p in parts if p)}


_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_DAYS_ZH = "一二三四五六日"


def _ticked_days(t: dict, maaend_dir) -> "list[int] | None":
    """The weekdays (0 = Monday) the task is ticked for in f"{task}Schedule".

    With no schedule saved MaaEnd uses the option's default_case from its
    definition, as plan._maaend_extra_bits reads AutoCollect's. None when that
    definition cannot be read either: the caller then keeps the task, because
    every MaaEnd version on record defaults to all seven days
    (fixtures/maaend-2026-09-10, maaend228, maaend-protocolspace-v2.30.0-rc.1).
    """
    key = f"{t.get('taskName')}Schedule"
    v = (t.get("optionValues") or {}).get(key)
    if isinstance(v, dict):
        names = v.get("caseNames") or []
    else:
        from ark_relay.core import mastercfg  # noqa: PLC0415 - imported where used, as plan.py does
        opt = (mastercfg._maaend_defs(maaend_dir)[0] if maaend_dir else {}).get(key)
        if not isinstance(opt, dict):
            return None
        names = opt.get("default_case") or []
    return sorted({_DAYS.index(n[len(key):]) for n in names
                   if isinstance(n, str) and n[len(key):] in _DAYS})


def read(automas_dir: "Path | None", when: "datetime | None" = None,
         maaend_dir: "Path | None" = None) -> dict:
    """The current plan: {tab, line, rewards_set, item, label}. {} if unreadable.

    Both sanity tasks can be on at once (mastercfg.MAAEND_TREE_TASKS: MaaEnd runs
    them in list order, so the first spends the sanity first). The label names
    both in run order; the top-level keys describe the first, and `tasks`
    carries each one.

    when: the day the plan is for (tomorrow's plan). A task not ticked for that
    weekday in its f"{task}Schedule" does not run that day and is left out; with
    none left, `enabled` is False and the label says so. Without `when` (the
    before/after echo of set_plan) every enabled task is described.
    maaend_dir: MaaEnd's install, for a schedule's default_case; by default where
    AUTO-MAS says it is.
    """
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
    if when is not None:
        resolved = False
        kept, off = [], []
        for t in on:
            days = _ticked_days(t, maaend_dir)
            if days is None and not resolved and maaend_dir is None:
                maaend_dir, resolved = _maaend_dir(automas_dir), True
                days = _ticked_days(t, maaend_dir)
            (kept if days is None or when.weekday() in days else off).append((t, days))
        on = [t for t, _ in kept]
        if not on:
            why = "；".join(
                f"{'基质刷取' if t['taskName'] == 'AutoEssence' else '协议空间'}"
                + (f"仅周{'、'.join(_DAYS_ZH[i] for i in days)} 跑" if days else "一天都没勾")
                for t, days in off)
            return {"tab": "", "line": "", "rewards_set": "", "item": "",
                    "enabled": False,
                    "label": f"理智任务明天（周{_DAYS_ZH[when.weekday()]}）不跑（{why}）"}
    each = [_describe(t) for t in on]
    out = dict(each[0])
    out["tasks"] = each
    out["understood"] = all(d["understood"] for d in each)
    if len(each) > 1:
        out["label"] = ("，用完再 ".join(d["label"] for d in each)
                        + f"（{len(each)} 项都开着，按母本顺序先打前面的）")
    return out


def _validate_plan(tab: str, line: str, rewards_set: str,
                   maaend_dir=None) -> str | None:
    """Check the three arguments first; return an error text, or None if all legal.

    This is a separate step because it does not touch the master copy at all -- it is
    purely "are these three values legal in themselves", and it must run to completion
    before anything reads or writes the master copy: these three values decide where
    tomorrow's sanity goes, and letting an illegal value reach the write is already
    too late.
    A reward set is legal only as a case MaaEnd defines for f"{line}RewardsSetOption"
    (read from MaaEnd's install, as plan._maaend_extra_bits reads its defaults); when
    those definitions cannot be read it is refused, not guessed.
    """
    if tab not in TAB_LABELS:
        return f"理智任务类型不合法: {tab!r}（可选 {'、'.join(TAB_LABELS)}）"
    if tab != "Essence" and line:
        legal = LINE_OPTIONS.get(tab, ())
        if legal and line not in legal:
            return f"{TAB_LABELS[tab]} 不接受 {line!r}（可选 {'、'.join(legal)}）"
    if rewards_set:
        if tab == "Essence" or not line:
            return f"奖励组 {rewards_set!r} 要和协议空间的线路一起给"
        cases = _reward_cases(maaend_dir, line)
        if cases is None:
            return f"读不到 MaaEnd 的选项定义，确认不了奖励组 {rewards_set!r} 合不合法，没写"
        if not cases:
            return f"{LINE_LABELS.get(line, line)} 没有奖励组可选，不接受 {rewards_set!r}"
        if rewards_set not in cases:
            return (f"{LINE_LABELS.get(line, line)} 的奖励组不接受 {rewards_set!r}"
                    f"（可选 {'、'.join(f'{c}（{REWARD.get((line, c), c)}）' for c in cases)}）")
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
             rewards_set: str = "", location: str = "",
             maaend_dir: "Path | None" = None) -> tuple[bool, str]:
    """Write the plan into the master copy.

    That is the copy AUTO-MAS hands to MaaEnd every run.

    `tab == "Essence"` -> enable `AutoEssence`, disable `ProtocolSpace`;
    anything else -> enable `ProtocolSpace` and write its dropdowns, disable
    `AutoEssence`.
    **Only toggles tasks that already exist, never creates them**: with no
    `AutoEssence` in the master copy, essence farming is refused instead of being
    reported as set.
    maaend_dir: MaaEnd's install, for its reward-set cases; by default where
    AUTO-MAS says it is.
    """
    if rewards_set and maaend_dir is None:
        maaend_dir = _maaend_dir(automas_dir)
    if err := _validate_plan(tab, line, rewards_set, maaend_dir):
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
