"""MaaEnd tasks the relay switched off in the past, and the sanity-booster step check.

maaend_reenable_records runs at boot: every task a leftover switch-off record
names is switched back on in AUTO-MAS's master mxu-MaaEnd.json, whatever the
MaaEnd version, and the record is dropped. spmed_check reports when the
sanity-booster step in MaaEnd's nodes.json has a shape this module does not
recognise; it changes nothing.

Re-exported from gameupdate, so callers write gameupdate.xxx.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ark_relay.core.config import atomic_write_text
from ark_relay.features.gameupdate.gameupdate_games import _store

log = logging.getLogger("ark.gameupdate")


# state.json records (section "updates") that name MaaEnd tasks switched off in
# the past. The task names sit under "disabled" (the hand-written 1.5.3 record)
# or "tasks" (the shape statestore.py documents).
_OFF_RECORDS = ("maaend_disabled_1_5_3", "maaend_reenable_next_boot", "maaend_disabled_spmed")
_TASK_ZH = {"GiftOperator": "赠送干员礼物", "GearAssembly": "装备制造", "DeliveryJobs": "转交委托",
            "EnvironmentMonitoring": "环境监测", "AutoCollect": "自动采集",
            "AutoUseSpMedication": "应急理智加强剂"}


def maaend_enable(cfg, names: set) -> tuple[list[str], list[str], str]:
    """Switch the named tasks on in AUTO-MAS's master mxu-MaaEnd.json: `enabled` and
    every per-controller copy of it. This function only switches tasks on.

    Returns (switched on now, named but not in the master at all, why it could not
    be done - '' when it was). "Already on" is in neither list."""
    root = Path(cfg.automas_dir) / "data" if cfg.automas_dir else None
    target = next((f for f in (root.glob("*/Default/ConfigFile/mxu-MaaEnd.json") if root else [])), None)
    if not target:
        return [], [], "找不到终末地的母本"
    try:
        j = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], [], f"终末地的母本读不出来（{type(exc).__name__}）"
    changed: list[str] = []
    seen: set[str] = set()
    for inst in j.get("instances") or []:
        for t in inst.get("tasks") or []:
            name = t.get("taskName")
            if name not in names:
                continue
            seen.add(name)
            ctl = t.get("enabledByController")
            ctl_off = (isinstance(ctl, dict) and not all(ctl.values())) or ctl is False
            if not t.get("enabled") or ctl_off:
                t["enabled"] = True
                if isinstance(ctl, dict):
                    for k in ctl:
                        ctl[k] = True
                elif isinstance(ctl, bool):
                    t["enabledByController"] = True
                if name not in changed:
                    changed.append(name)
    gone = sorted(set(names) - seen)
    if not changed:
        return [], gone, ""
    try:
        atomic_write_text(target, json.dumps(j, ensure_ascii=False, indent=2))
        back = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], gone, f"终末地的母本写不进去（{type(exc).__name__}）"
    off = sorted({str(t.get("taskName")) for inst in back.get("instances") or []
                  for t in inst.get("tasks") or [] if t.get("taskName") in changed and not t.get("enabled")})
    if off:
        return [], gone, "写进终末地的母本之后再读，这几项还是关着：" + "、".join(off)
    return changed, gone, ""


def maaend_reenable_records(cfg) -> list[str]:
    """Boot: switch every task a leftover switch-off record names back on, once, and
    drop the record. Returns the log lines (already logged).

    Switched on (or already on): INFO, record dropped. The master cannot be found or
    read: WARNING (a relay WARNING reaches the group), record kept for the next boot.
    A record naming no task, or tasks the master no longer has: WARNING with the
    record, record dropped (nothing is left to switch on)."""
    store = _store(cfg.state_dir)
    said: list[str] = []
    for key in _OFF_RECORDS:
        rec = store.get("updates", key)
        if rec is None:
            continue
        rec_d = rec if isinstance(rec, dict) else {}
        names = {str(n) for n in (rec_d.get("disabled") or rec_d.get("tasks") or []) if n}
        if not names:
            line = f"开机：中继以前关掉终末地任务的记录 {key} 里没有任务名（{rec!r}），没法开回，记录已删"
            log.warning(line)
            store.pop("updates", key)
            said.append(line)
            continue
        zh = "、".join(_TASK_ZH.get(n, n) for n in sorted(names))
        on, gone, err = maaend_enable(cfg, names)
        if err:
            line = f"开机：中继以前关掉的终末地任务 {zh} 没能开回（{err}），记录留着，下次开机再试"
            log.warning(line)
            said.append(line)
            continue
        store.pop("updates", key)
        if gone:
            line = (f"开机：中继以前关掉的终末地任务里，{'、'.join(_TASK_ZH.get(n, n) for n in gone)}"
                    f" 母本里已经没有了，没法开回（记录 {key} 已删）")
            log.warning(line)
            said.append(line)
        if on:
            line = (f"开机：中继以前关掉的终末地任务已开回：{'、'.join(_TASK_ZH.get(n, n) for n in on)}"
                    f"（记录 {key} 已删）")
        elif len(gone) < len(names):
            line = (f"开机：中继以前关掉的终末地任务 {'、'.join(_TASK_ZH.get(n, n) for n in sorted(names - set(gone)))}"
                    f" 已经开着（记录 {key} 已删）")
        else:
            continue
        log.info(line)
        said.append(line)
    return said


# The sanity-booster (应急理智加强剂) step in MaaEnd's resource/pipeline/nodes.json
# is only inspected here; no task is switched off because of it.
# SPMED_NODE is the confirm node's name before v2.32. Its recognition.param.all_of
# lists nodes; an inline recognition must sit inside its own "recognition" block
# (the shape after upstream PR #5453, "fixed"); an inline element with type/param
# directly on it is not understood by the framework ("broken").
# Fixtures: tests/fixtures/maaend-v2.30.0-beta.4-spmed (node absent),
# tests/fixtures/maaend-v2.32-spmed (SPMED_NODE_V232).
SPMED_NODE = "AutoUseSpMedicationQuickUse"
# The node from v2.32 on: the click on the detail page's use button; its all_of
# holds only node names.
SPMED_NODE_V232 = "__AutoUseSpMedicationUseEmergencySpBooster"
SPMED_NODES = (SPMED_NODE, SPMED_NODE_V232)


def spmed_shape(maaend_dir) -> str:
    """How the booster's confirm node reads in this MaaEnd install:
    "fixed" (the shape upstream PR #5453 produced), "broken" (inline element
    without its own recognition block),
    "unknown" (the node is there in a shape this file does not know), "missing"
    (no node of that name: renamed or removed upstream), "unreadable" (nodes.json
    cannot be read), "" (no MaaEnd directory configured)."""
    if not maaend_dir:
        return ""
    f = Path(maaend_dir) / "resource" / "pipeline" / "nodes.json"
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"
    if not isinstance(doc, dict):
        return "unreadable"
    name = next((n for n in SPMED_NODES if n in doc), None)
    if name is None:
        return "missing"
    node = doc[name]
    if not isinstance(node, dict) or not isinstance(node.get("recognition"), dict):
        return "unknown"
    all_of = (node["recognition"].get("param") or {}).get("all_of")
    if not isinstance(all_of, list) or not all_of:
        return "unknown"
    # Fixed: every element is a node name, or an inline recognition inside its own
    # recognition block. Broken: an inline element without that block.
    if any(not isinstance(x, (str, dict)) for x in all_of):
        return "unknown"
    return "fixed" if all(isinstance(x, str) or "recognition" in x for x in all_of) else "broken"


def spmed_check(cfg) -> str:
    """The booster step's shape when it calls for the boot alarm (texts.SPMED_UNRECOGNISED,
    body texts.spmed_unrecognised_body), '' when it is the fixed shape or there is no
    MaaEnd directory.

    Called at every boot; the task itself is never changed here."""
    shape = spmed_shape(getattr(cfg, "maaend_dir", None))
    if not shape:
        return ""
    if shape == "fixed":
        log.info("开机：应急理智加强剂那段是认得的修好写法")
        return ""
    # INFO, not WARNING: the caller sends the alarm, and errwatch forwards every
    # relay WARNING to the group as well.
    log.info("开机：应急理智加强剂那段认不出（%s），报群", shape)
    return shape
