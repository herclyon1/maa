"""MAA's own config: what the infrastructure drones are used on, and the Award (领取奖励) switches.

AUTO-MAS has no setting for either; they live only in MAA's gui.new.json under
Configurations/<Current>/TaskQueue/<task>. There are two copies: the master at
AUTO-MAS's data/<MAA script id>/Default/ConfigFile/gui.new.json, and MAA's own
config/gui.new.json, which AUTO-MAS overwrites from the master before every
launch. The writers change both copies and read each one back.

A queue can hold two entries of one task type: MAA's own nameless one
("Name": "") and a named one ("领取奖励") that AUTO-MAS appended when it wrote a
run back (task/MAA/AutoProxy.py _merge_task_queue: an identity its baseline knew
and the archive lacked is appended). AUTO-MAS hands MAA the named one
(_find_task_source matches (TaskType, Name) first), so the readers here put the
named entry first, the writers write every entry of the type, and
heal_maa_master folds the copies back into one at boot.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from ark_relay.core.config import atomic_write_text

log = logging.getLogger("ark.mastercfg")

# read_maa runs on every phone publish and a WARNING is a group message
# (errwatch): each condition is said once and forgotten once it clears.
_said: dict[str, str] = {}


def _warn_once(site: str, why: str, msg: str, *args, exc_info: bool = False) -> None:
    if _said.get(site) != why:
        log.warning(msg, *args, exc_info=exc_info)
        _said[site] = why

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


# The 领取奖励 (Award) task's switches: every bool property of MAA's
# Configuration/Single/MaaTask/AwardTask.cs, labels from AsstAwardTask.cs
# (checked 2026-11-08, v6.19.0). All seven are open since 2026-11-08 (the
# user's order, relayed by Gemini in 中继-App-MAA领奖励治本-1108); until then
# Award, FreeGacha and SignInEvent were not offered, and FreeGacha was held back
# because MAA asks for confirmation before turning it on.
MAA_AWARD: tuple[tuple[str, str], ...] = (
    ("Award", "领取每日/每周任务奖励"),
    ("Mail", "领取所有邮件奖励"),
    ("FreeGacha", "每日免费单抽"),
    ("Orundum", "领取幸运墙的每日合成玉奖励"),
    ("Mining", "领取限时开采许可的每日合成玉奖励"),
    ("SpecialAccess", "领取周年赠送月卡奖励"),
    ("SignInEvent", "限时签到活动领取"),
)

# MAA's one-of-a-kind tasks and the names AUTO-MAS gives them (MAA_TASKS /
# MAA_TASKS_ZH in app/utils/constants.py, pinned by test_gl's guinew case).
MAA_SINGLETON_TASKS: dict[str, str] = {
    "StartUp": "开始唤醒",
    "Infrast": "基建换班",
    "Recruit": "自动公招",
    "Mall": "信用收支",
    "Award": "领取奖励",
}


MAA_AWARD_PATHS = {f"Award/{k}": zh for k, zh in MAA_AWARD}


def maa_master(automas_dir) -> Path | None:
    root = Path(automas_dir) / "data" if automas_dir else None
    return next((f for f in (root.glob("*/Default/ConfigFile/gui.new.json") if root else [])), None)


def _maa_tasks(doc: dict, match, canonical_name: str = "") -> list[dict]:
    """Every task in the current configuration's TaskQueue that `match` accepts,
    the one named `canonical_name` first: the entry AUTO-MAS hands MAA
    (_find_task_source returns an exact (TaskType, Name) match before anything else).
    """
    cfgs = doc.get("Configurations") or {}
    c = cfgs.get(doc.get("Current") or "Default") or cfgs.get("Default") or {}
    found = [t for t in c.get("TaskQueue") or [] if isinstance(t, dict) and match(t)]
    if canonical_name:
        found.sort(key=lambda t: t.get("Name") != canonical_name)   # stable: queue order otherwise
    return found


def _maa_task(doc: dict, match, canonical_name: str = "") -> dict | None:
    """The task AUTO-MAS would hand MAA: see _maa_tasks."""
    return next(iter(_maa_tasks(doc, match, canonical_name)), None)


def _is_type(t: dict, task_type: str) -> bool:
    return t.get("TaskType") == task_type or t.get("Type") == task_type


def _infrast_match(t: dict) -> bool:
    return _is_type(t, "Infrast") or "UsesOfDrones" in t


def _award_match(t: dict) -> bool:
    return _is_type(t, "Award") or ("Mail" in t and "FreeGacha" in t)


def _maa_infrast(doc: dict) -> dict | None:
    return _maa_task(doc, _infrast_match, MAA_SINGLETON_TASKS["Infrast"])


def _maa_award(doc: dict) -> dict | None:
    return _maa_task(doc, _award_match, MAA_SINGLETON_TASKS["Award"])


def _maa_infrasts(doc: dict) -> list[dict]:
    return _maa_tasks(doc, _infrast_match, MAA_SINGLETON_TASKS["Infrast"])


def _maa_awards(doc: dict) -> list[dict]:
    return _maa_tasks(doc, _award_match, MAA_SINGLETON_TASKS["Award"])


def read_maa(automas_dir) -> dict:
    out: dict = {"values": {}, "options": {}, "labels": {}}
    f = maa_master(automas_dir)
    if not f or not f.is_file():
        # Said, so the phone page's missing section has a cause in the log.
        _warn_once("master", f"missing: {f}", "母本配置文件不在：%s（手机页那一段会标成读不到）", f or "没找到路径")
        return out
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _warn_once("master", f"unreadable: {type(exc).__name__}: {exc}", "母本 gui.new.json 读不出来",
                   exc_info=True)
        return out
    _said.pop("master", None)
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
        automas_dir, maa_dir, _maa_infrasts, "UsesOfDrones", str(value),
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
        automas_dir, maa_dir, _maa_awards, key, value,
        "里找不到领取奖励任务，已拒绝", lambda t: bool(t.get(key, False)))
    if err:
        return False, err
    state = "开" if value else "关"
    if before is value:
        return True, f"「{zh}」本来就是{state}的"
    return True, f"「{zh}」：{'开' if before else '关'} → {state}（写了 {len(written)} 份）"


def _write_maa_copies(automas_dir, maa_dir, find_all, key: str, value, no_task: str,
                      read_before) -> "tuple[str, object, list[str]]":
    """Set t[key] = value for every t in find_all(doc), in the master gui.new.json
    and in MAA's own copy. find_all puts the entry AUTO-MAS uses first; every
    copy of the task is written, so whichever one is used carries the value.

    The master copy is the one that counts: AUTO-MAS copies
    data/<script>/<user>/ConfigFile over MAA's config dir before each run
    (task/MAA/AutoProxy.py _copy_source_config), so without it nothing is
    written. Both files are parsed and checked before either is written, so a
    refusal leaves both untouched. Each file is written atomically and read
    back. `read_before(task)` gives the old value, from the master's first entry.
    Returns (error, old value, names of the files written); error is "" on
    success and, when it is not, names the files already written.
    """
    master = maa_master(automas_dir)
    if not master or not master.is_file():
        return ("找不到 AUTO-MAS 里 MAA 的母本配置，没改（只改 MAA 自己那份，"
                "下次开跑前会被母本盖掉）"), None, []
    targets = [master]
    if maa_dir and (own := Path(maa_dir) / "config" / "gui.new.json").is_file():
        targets.append(own)
    docs = []
    for f in targets:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return f"{f} 读不出来（{type(exc).__name__}），两份都没改", None, []
        if not find_all(doc):
            return f"{f.name} {no_task}（两份都没改）", None, []
        docs.append(doc)
    before = read_before(find_all(docs[0])[0])
    written: list[str] = []
    for f, doc in zip(targets, docs, strict=True):
        for t in find_all(doc):
            t[key] = value
        try:
            atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=4))
            back = find_all(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            back, problem = [], f"写的时候出错（{type(exc).__name__}）"
        else:
            problem = "写进去之后读出来和写的不一样"
        if not back or any(t.get(key) != value for t in back):
            # Only the master can come before: it is already changed, and
            # AUTO-MAS copies it over MAA's own file before the next run.
            done = "；母本已经改好，下次开跑会照它覆盖 MAA 自己那份" if written else ""
            return f"{f} {problem}{done}", before, written
        written.append(f)
    return "", before, [w.name for w in written]


def _placeholder(v) -> bool:
    """MAA's unfilled default, e.g. "{{ HighPriorityDefault }}" (see AutoProxy.py's
    comment where it fills a missing source from the preset)."""
    return isinstance(v, str) and "{{" in v


def dedup_maa_task_queue(doc: dict) -> list[str]:
    """Fold each one-of-a-kind task's copies into one entry, in every configuration.

    The first entry of the type is kept in its place; a later copy only fills a
    key the first lacks or holds as a placeholder ("Name" and "IsEnable" are not
    taken, placeholders never are). The Award switches are on when any copy has
    them on. The kept entry is named as AUTO-MAS names it, so its exact match
    finds it and its write-back no longer appends a copy, and "$type" stays the
    first key (MAA's System.Text.Json reads it from there; AutoProxy.py
    _with_type_first). Returns what was folded, e.g. ["领取奖励（2 条合成 1 条）"].
    """
    folded: list[str] = []
    award_keys = [k for k, _ in MAA_AWARD]
    for scheme, c in (doc.get("Configurations") or {}).items():
        queue = c.get("TaskQueue") if isinstance(c, dict) else None
        if not isinstance(queue, list):
            continue
        for task_type, zh in MAA_SINGLETON_TASKS.items():
            idxs = [i for i, t in enumerate(queue) if isinstance(t, dict) and _is_type(t, task_type)]
            if len(idxs) < 2:
                continue
            merged = dict(queue[idxs[0]])
            for i in idxs[1:]:
                for k, v in queue[i].items():
                    if k in ("Name", "IsEnable") or _placeholder(v):
                        continue
                    if k not in merged or _placeholder(merged[k]):
                        merged[k] = v
            if task_type == "Award":
                for k in award_keys:
                    merged[k] = any(bool(queue[i].get(k, False)) for i in idxs)
            merged["Name"] = zh
            merged["TaskType"] = task_type
            queue[idxs[0]] = {"$type": merged.get("$type") or f"{task_type}Task", **merged}
            for i in reversed(idxs[1:]):
                del queue[i]
            where = "" if scheme == "Default" else f"「{scheme}」方案的"
            folded.append(f"{where}{zh}（{len(idxs)} 条合成 1 条）")
    return folded


def heal_maa_master(automas_dir, maa_dir=None) -> tuple[list[str], str]:
    """Run dedup_maa_task_queue on the master gui.new.json and on MAA's own copy.

    Returns (what was folded, note); ([], "") when there was nothing to fold or
    no master (read_maa already says that one). The master is backed up first,
    one level above ConfigFile: AUTO-MAS copies that whole folder into MAA's
    config dir before every run. Each file is read back after writing.
    """
    master = maa_master(automas_dir)
    if not master or not master.is_file():
        return [], ""
    targets = [master]
    if maa_dir and (own := Path(maa_dir) / "config" / "gui.new.json").is_file():
        targets.append(own)
    folded: list[str] = []
    notes: list[str] = []
    for f in targets:
        try:
            raw = f.read_bytes()
            doc = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError) as exc:
            notes.append(f"{f} 读不出来（{type(exc).__name__}），没去重")
            continue
        merged = dedup_maa_task_queue(doc)
        if not merged:
            continue
        bak = None
        if f == master:
            bak = f.parent.parent / f"{f.name}.bak-dedup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            bak.write_bytes(raw)
        try:
            atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=4))
            left = dedup_maa_task_queue(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            notes.append(f"{f} 写的时候出错（{type(exc).__name__}）" + (f"，{bak.name} 是原样" if bak else ""))
            continue
        if left:
            notes.append(f"{f} 写进去之后再读还有重复：{'、'.join(left)}" + (f"，{bak.name} 是原样" if bak else ""))
            continue
        which = "母本" if f == master else "MAA 自己那份"
        folded += [m for m in merged if m not in folded]
        notes.append(f"MAA {which}里重复的任务合并了：{'、'.join(merged)}" + (f"（原文件备份为 {bak.name}）" if bak else ""))
    return folded, "；".join(notes)
