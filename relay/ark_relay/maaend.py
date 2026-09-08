"""Editing MaaEnd's config safely, without a hand-maintained whitelist.

MaaEnd's options are a tree, not a value. ProtocolSpace alone has 18 options,
several of which only mean anything under a particular parent - pick
`WeaponProgression` and the operator-side reward choices stop applying. A
command vocabulary that named individual settings ("set_stage") could never
cover that, and would need editing every time MaaEnd shipped a new task.

So nothing here is hard-coded. A command names a task, an option and a value,
and every part is checked against **MaaEnd's own definition files** -
`tasks/<Task>.json` next to its interface.json. If MaaEnd accepts it, so do we;
if MaaEnd has never heard of it, it is refused before anything touches disk.
That is what makes an arbitrary future change expressible without new code.

Layout being edited (config/mxu-MaaEnd.json):

    instances[0].tasks[] = [
      {"id": "c4kzbdr", "taskName": "ProtocolSpace", "enabled": true,
       "optionValues": {
          "ProtocolSpaceTab":  {"type": "select",   "caseName": "WeaponProgression"},
          "AutoFightDodge":    {"type": "switch",   "value": true},
          "ProtocolSpaceSchedule": {"type": "checkbox", "caseNames": [...]},
          "SupplyPlanLimits":  {"type": "input",    "values": {...}}
       }},
      ...
    ]
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.maaend")


def _load_jsonc(path: Path) -> dict:
    """Parse MaaEnd's JSON, which carries comments and trailing commas.

    Its task definitions are hand-written and use both; json.loads refuses
    them outright, and the whole validation story depends on being able to
    read these files.
    """
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)


class MaaEndConfig:
    """One MaaEnd installation: its live config and its option definitions."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.config_path = self.root / "config" / "mxu-MaaEnd.json"

    # ---------- definitions: what MaaEnd itself considers legal ----------

    def option_spec(self, task: str, option: str) -> dict | None:
        """The definition of one option, or None if MaaEnd does not define it."""
        path = self.root / "tasks" / f"{task}.json"
        if not path.exists():
            return None
        try:
            spec = _load_jsonc(path)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("读不懂 %s: %s", path.name, exc)
            return None
        return (spec.get("option") or {}).get(option)

    def legal_cases(self, task: str, option: str) -> list[str]:
        spec = self.option_spec(task, option)
        return [c.get("name") for c in (spec or {}).get("cases", []) if c.get("name")]

    # ---------- the live config ----------

    def load(self) -> dict:
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    @staticmethod
    def find_task(cfg: dict, task: str) -> dict | None:
        for inst in cfg.get("instances", []):
            for t in inst.get("tasks", []):
                if t.get("taskName") == task:
                    return t
        return None

    def describe(self, task: str, option: str) -> str:
        """Current value of one option, for reporting. '' when absent."""
        try:
            t = self.find_task(self.load(), task)
        except (OSError, json.JSONDecodeError):
            return ""
        v = ((t or {}).get("optionValues") or {}).get(option)
        # An absent option has to come back as '' - the docstring promises it and
        # every caller tests the result for truth. Falling through to the json
        # dump below turned "MaaEnd has never heard of this" into the string
        # "{}", which is truthy, so a report line would state the current value
        # of a setting that does not exist.
        if not isinstance(v, dict):
            return ""
        if v.get("type") == "select":
            return str(v.get("caseName") or "")
        if v.get("type") == "switch":
            return "on" if v.get("value") else "off"
        if v.get("type") == "checkbox":
            return ",".join(v.get("caseNames") or [])
        return json.dumps(v.get("values") or v, ensure_ascii=False)


def _flatten(obj: Any, path: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{path}/{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{path}[{i}]"))
    else:
        out[path] = obj
    return out


def _apply_one(mc: "MaaEndConfig", cfg: dict, ch: dict,
               applied: list[str], touched_opts: set[str]) -> str:
    """Write one change into the in-memory cfg. Empty string means success, otherwise it is the reason for refusing.

    Split out so that apply_changes is left with just four steps: read the
    config, apply the changes one by one, run the structural diff, back up and
    write. The validation for each of the four option types lives here.
    """
    task = str(ch.get("task") or "")
    option = str(ch.get("option") or "")
    node = mc.find_task(cfg, task)
    if node is None:
        return f"配置里没有任务 {task!r}"
    values = node.setdefault("optionValues", {})
    current = values.get(option)
    if current is None:
        # Refusing to invent keys is deliberate: one typo in an option name
        # would write a setting MaaEnd never reads, while the person believes
        # the change took effect.
        return f"任务 {task} 没有选项 {option!r}（拼错了？）"

    kind = current.get("type")
    # The shape of the command has to match the option type. Without this check,
    # a `case` aimed at a switch fell through to bool(ch.get("value")) and was
    # written as False - a silently wrong answer, which is far worse than an
    # outright refusal.
    expected = {"select": "case", "switch": "value",
                "checkbox": "cases", "input": "values"}.get(kind)
    if expected and expected not in ch:
        return (f"{task}.{option} 是 {kind} 型，需要字段 {expected!r}，"
                f"收到的是 {sorted(set(ch) - {'task', 'option', 'action', 'enabled'})}")

    touched_opts.add(option)
    if kind == "select":
        case = str(ch.get("case") or "")
        legal = mc.legal_cases(task, option)
        if not legal:
            return f"读不到 {task}.{option} 的合法取值，拒绝盲改"
        if case not in legal:
            return (f"{task}.{option} 不接受 {case!r}；"
                    f"MaaEnd 定义的取值是 {'、'.join(legal)}")
        before = current.get("caseName")
        current["caseName"] = case
        applied.append(f"{task}.{option}: {before} → {case}")
    elif kind == "switch":
        want = bool(ch.get("value"))
        before = bool(current.get("value"))
        current["value"] = want
        applied.append(f"{task}.{option}: {before} → {want}")
    elif kind == "checkbox":
        cases = ch.get("cases")
        if not isinstance(cases, list):
            return f"{task}.{option} 是多选项，需要 cases 数组"
        legal = mc.legal_cases(task, option)
        if bad := [c for c in cases if legal and c not in legal]:
            return f"{task}.{option} 不接受 {'、'.join(bad)}"
        before = current.get("caseNames") or []
        current["caseNames"] = list(cases)
        applied.append(f"{task}.{option}: {len(before)} 项 → {len(cases)} 项")
    elif kind == "input":
        vals = ch.get("values")
        if not isinstance(vals, dict):
            return f"{task}.{option} 是输入项，需要 values 对象"
        slot = current.setdefault("values", {})
        for k, v in vals.items():
            if k not in slot:
                return f"{task}.{option} 没有输入框 {k!r}"
            applied.append(f"{task}.{option}.{k}: {slot[k]} → {v}")
            slot[k] = v
    else:
        return f"{task}.{option} 是未知类型 {kind!r}，不敢改"

    # "And while you are at it, enable/disable the task itself" rides along on
    # the same command.
    if "enabled" in ch:
        want = bool(ch["enabled"])
        if bool(node.get("enabled")) != want:
            applied.append(f"{task}: {'启用' if want else '停用'}")
            node["enabled"] = want
            for k in (node.get("enabledByController") or {}):
                node["enabledByController"][k] = want
    return ""


def _stray_changes(original: str, cfg: dict, touched_opts: set[str]) -> tuple[int, str]:
    """Structural diff run before writing to disk.

    Returns (number of changed leaves, out-of-scope explanation); writing is
    only allowed when that explanation is empty. This is the same gate the
    AUTO-MAS path uses: a regex that only meant to change three settings once
    wrecked a whole unrelated section of config, and only the diff caught it.
    """
    before_flat, after_flat = _flatten(json.loads(original)), _flatten(cfg)
    added, removed = set(after_flat) - set(before_flat), set(before_flat) - set(after_flat)
    changed = {k for k in before_flat.keys() & after_flat.keys()
               if before_flat[k] != after_flat[k]}
    # Additions and removals are legal **inside the option we actually touched**
    # - a checkbox going from seven days to two is supposed to lose five leaves
    # - but nowhere else. Scoping it this way keeps the gate that caught the
    # regex back then, without misreading a real change as out of scope.
    stray = [p for p in (added | removed)
             if not any(f"/optionValues/{opt}/" in p for opt in touched_opts)]
    if stray:
        return len(changed), (f"结构化 diff 不符预期，已放弃：{len(stray)} 处改到了"
                              f"没打算动的地方，例如 {stray[0]}")
    return len(changed), ""


def _backup_and_write(mc: "MaaEndConfig", updated: str) -> tuple[str, str]:
    """Back up the current config, then write atomically. Returns (backup file name, failure explanation)."""
    stamp = datetime.now(tz=SERVER_TZ)
    backup = mc.config_path.with_name(
        f"{mc.config_path.stem}.bak-{stamp:%Y%m%d-%H%M%S}.json")
    shutil.copy2(mc.config_path, backup)
    try:
        atomic_write_text(mc.config_path, updated)
    except OSError as exc:
        shutil.copy2(backup, mc.config_path)
        return backup.name, f"写入失败，已回滚: {exc}"
    return backup.name, ""


def apply_changes(root: Path, changes: list[dict]) -> tuple[bool, str]:
    """Apply a whole batch of option changes. Returns (success, human-readable explanation).

    A batch rather than one at a time, because MaaEnd's options are related to
    each other: switching to operator progression and then picking its reward
    set is **one** intent, and landing half of it makes the machine farm things
    nobody wants. Either every change validates and gets written, or the file
    is not touched at all.
    """
    mc = MaaEndConfig(root)
    if not mc.config_path.exists():
        return False, f"找不到 MaaEnd 配置: {mc.config_path}"

    original = mc.config_path.read_text(encoding="utf-8")
    try:
        cfg = json.loads(original)
    except json.JSONDecodeError as exc:
        return False, f"MaaEnd 配置本身不是合法 JSON，拒绝改动: {exc}"

    applied: list[str] = []
    touched_opts: set[str] = set()
    for ch in changes:
        if refused := _apply_one(mc, cfg, ch, applied, touched_opts):
            return False, refused

    if not applied:
        return True, "没有需要改动的地方"

    n_changed, stray = _stray_changes(original, cfg, touched_opts)
    if stray:
        return False, stray

    name, failed = _backup_and_write(mc, json.dumps(cfg, ensure_ascii=False, indent=2))
    if failed:
        return False, failed
    return True, f"改动 {n_changed} 处（备份 {name}）：" + "；".join(applied)
