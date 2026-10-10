"""MAA's own config: what the infrastructure drones are used on, and the Award (领取奖励) switches.

AUTO-MAS has no setting for either; they live only in MAA's gui.new.json under
Configurations/<Current>/TaskQueue/<task>. There are two copies: the master at
AUTO-MAS's data/<MAA script id>/Default/ConfigFile/gui.new.json, and MAA's own
config/gui.new.json, which AUTO-MAS overwrites from the master before every
launch. The writers change both copies and read each one back.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ark_relay.core.config import atomic_write_text

log = logging.getLogger("ark.mastercfg")

# Drone targets: keys and Chinese names from MAA's
# InfrastSettingsUserControlModel.UsesOfDronesList and docs/protocol/integration.md
# (checked 2026-09-07, v6.17).
MAA_DRONES: tuple[tuple[str, str], ...] = (
    ("_NotUse", "不使用"),
    ("Money", "贸易站 · 龙门币"),
    ("SyntheticJade", "贸易站 · 合成玉"),
    ("CombatRecord", "制造站 · 作战记录"),
    ("PureGold", "制造站 · 赤金"),
    ("OriginStone", "制造站 · 源石碎片"),
    ("Chip", "制造站 · 芯片"),
)


MAA_DRONES_PATH = "Infrast/UsesOfDrones"


# The 领取奖励 (Award) task's switches. Keys and Chinese labels from MAA's
# AwardTask.cs / zh-cn.xaml (checked 2026-09-14, v6.17). FreeGacha is left out
# on purpose: MAA itself pops a warning before enabling it.
MAA_AWARD: tuple[tuple[str, str], ...] = (
    ("Mail", "领取所有邮件奖励"),
    ("Orundum", "领取幸运墙的每日合成玉奖励"),
    ("Mining", "领取限时开采许可的每日合成玉奖励"),
    ("SpecialAccess", "领取周年赠送月卡奖励"),
)


MAA_AWARD_PATHS = {f"Award/{k}": zh for k, zh in MAA_AWARD}


def maa_master(automas_dir) -> Path | None:
    root = Path(automas_dir) / "data" if automas_dir else None
    return next((f for f in (root.glob("*/Default/ConfigFile/gui.new.json") if root else [])), None)


def _maa_task(doc: dict, match) -> dict | None:
    """The first task in the current configuration's TaskQueue that `match` accepts."""
    cfgs = doc.get("Configurations") or {}
    c = cfgs.get(doc.get("Current") or "Default") or cfgs.get("Default") or {}
    for t in c.get("TaskQueue") or []:
        if isinstance(t, dict) and match(t):
            return t
    return None


def _maa_infrast(doc: dict) -> dict | None:
    return _maa_task(doc, lambda t: "UsesOfDrones" in t)


def _maa_award(doc: dict) -> dict | None:
    return _maa_task(doc, lambda t: t.get("Type") == "Award" or ("Mail" in t and "FreeGacha" in t))


def read_maa(automas_dir) -> dict:
    out: dict = {"values": {}, "options": {}, "labels": {}}
    f = maa_master(automas_dir)
    if not f or not f.is_file():
        # Said, so the phone page's missing section has a cause in the log.
        log.warning("母本配置文件不在：%s（手机页那一段会标成读不到）", f or "没找到路径")
        return out
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("母本 gui.new.json 读不出来", exc_info=True)
        return out
    task = _maa_infrast(doc)
    if task is not None:
        out["values"][MAA_DRONES_PATH] = str(task.get("UsesOfDrones") or "")
        out["options"][MAA_DRONES_PATH] = [[label, key] for key, label in MAA_DRONES]
        out["labels"][MAA_DRONES_PATH] = "基建无人机用在哪"
    award = _maa_award(doc)
    if award is not None:
        for key, zh in MAA_AWARD:
            out["values"][f"Award/{key}"] = bool(award.get(key, False))
            out["labels"][f"Award/{key}"] = zh
    return out


def write_maa(automas_dir, maa_dir, path: str, value) -> tuple[bool, str]:
    """Change what the infrastructure drones are used on. Both the master copy
    and the copy in the MAA directory are written; only the seven values MAA
    itself declares are accepted.
    """
    if str(path) in MAA_AWARD_PATHS:
        return _write_maa_award(automas_dir, maa_dir, str(path), value)
    if str(path) != MAA_DRONES_PATH:
        return False, f"MAA 只开放 {MAA_DRONES_PATH} 和 {sorted(MAA_AWARD_PATHS)} 这几项，已拒绝 {path!r}"
    keys = {k for k, _ in MAA_DRONES}
    if str(value) not in keys:
        return False, f"无人机用途不认识取值 {value!r}，它只接受 {sorted(keys)}"
    err, before, written = _write_maa_copies(
        automas_dir, maa_dir, _maa_infrast, "UsesOfDrones", str(value),
        "里找不到带 UsesOfDrones 的基建任务，已拒绝", lambda t: t.get("UsesOfDrones"))
    if err:
        return False, err
    zh = dict(MAA_DRONES)
    if before == str(value):
        return True, f"基建无人机本来就用在{zh[str(value)]}"
    return True, f"基建无人机用在哪：{zh.get(str(before), before)} → {zh[str(value)]}（写了 {len(written)} 份）"


def _write_maa_award(automas_dir, maa_dir, path: str, value) -> tuple[bool, str]:
    """Flip one switch of the 领取奖励 task in both copies of gui.new.json."""
    if not isinstance(value, bool):
        return False, f"{path} 只接受开/关，已拒绝 {value!r}"
    key = path.split("/", 1)[1]
    zh = MAA_AWARD_PATHS[path]
    err, before, written = _write_maa_copies(
        automas_dir, maa_dir, _maa_award, key, value,
        "里找不到领取奖励任务，已拒绝", lambda t: bool(t.get(key, False)))
    if err:
        return False, err
    state = "开" if value else "关"
    if before is value:
        return True, f"「{zh}」本来就是{state}的"
    return True, f"「{zh}」：{'开' if before else '关'} → {state}（写了 {len(written)} 份）"


def _write_maa_copies(automas_dir, maa_dir, find, key: str, value, no_task: str,
                      read_before) -> "tuple[str, object, list[str]]":
    """Set find(doc)[key] = value in the master gui.new.json and in MAA's own copy.

    Each file is written atomically and read back. `read_before(task)` gives the
    old value; it is taken from the first file where it is not None. Returns
    (error, old value, names of the files written); error is "" on success.
    """
    targets = [maa_master(automas_dir)]
    if maa_dir:
        targets.append(Path(maa_dir) / "config" / "gui.new.json")
    before = None
    written: list[str] = []
    for f in targets:
        if not f or not f.is_file():
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        task = find(doc)
        if task is None:
            return f"{f.name} {no_task}", before, written
        if before is None:
            before = read_before(task)
        task[key] = value
        atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=4))
        back = find(json.loads(f.read_text(encoding="utf-8")))
        if not back or back.get(key) != value:
            return f"{f} 写进去之后读出来和写的不一样", before, written
        written.append(f.name)
    if not written:
        return "找不到 MAA 的母本配置", before, written
    return "", before, written
