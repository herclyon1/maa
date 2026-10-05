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

What gets edited is AUTO-MAS's **master copy** of that file
(`<automas>/data/<script id>/Default/ConfigFile/mxu-MaaEnd.json`, found by
`mastercfg.maaend_master`), not MaaEnd's own `config/mxu-MaaEnd.json`: AUTO-MAS
copies the master directory over MaaEnd's config before every run
(`config.master_config_dir`), so an edit to MaaEnd's copy was reported as
「改动 N 处」 and then silently undone. The option definitions still come from
the MaaEnd install. Layout being edited (the same in both copies):

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

from . import mastercfg
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
    """One MaaEnd installation's option definitions, plus a task lookup in a parsed config.

    There is deliberately no reader for a config file here. MaaEnd's own
    config/mxu-MaaEnd.json is overwritten from AUTO-MAS's master before every
    run, so reporting a value from it (the describe()/load() pair removed on
    2026-10-06, which nothing in production called) states what the next run
    will *not* use. The master is read by mastercfg (maaend_master).
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    # ---------- definitions: what MaaEnd itself considers legal ----------

    def option_spec(self, task: str, option: str) -> dict | None:
        """The definition of one option, or None if MaaEnd does not define it."""
        path = self.root / "tasks" / f"{task}.json"
        if not path.exists():
            return None
        try:
            spec = _load_jsonc(path)
        # ValueError, not just JSONDecodeError: a file that is not UTF-8 raises
        # UnicodeDecodeError, which used to escape apply_changes as a crash.
        except (OSError, ValueError) as exc:
            log.warning("读不懂 %s: %s", path.name, exc)
            return None
        opts = spec.get("option") if isinstance(spec, dict) else None
        found = opts.get(option) if isinstance(opts, dict) else None
        return found if isinstance(found, dict) else None

    def legal_cases(self, task: str, option: str) -> list[str]:
        spec = self.option_spec(task, option)
        cases = (spec or {}).get("cases")
        return [c["name"] for c in (cases if isinstance(cases, list) else [])
                if isinstance(c, dict) and c.get("name")]

    # ---------- a parsed config (the master, read by apply_changes) ----------

    @staticmethod
    def find_task(cfg: dict, task: str) -> dict | None:
        for inst in cfg.get("instances", []):
            for t in inst.get("tasks", []):
                if t.get("taskName") == task:
                    return t
        return None


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
        return (f"{task}.{option} 是 {kind} 型，要给的是 {expected!r}，"
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
        # Same rule as select: with no definition to check against, every value
        # would pass and land on disk unchecked (AutoEssenceSchedule did, its
        # definition being in tasks/AutoEssence/AutoEssence.json).
        if not legal:
            return f"读不到 {task}.{option} 的合法取值，拒绝盲改"
        if bad := [c for c in cases if c not in legal]:
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
        return len(changed), (f"改动的地方和预期不符，已放弃：{len(stray)} 处改到了"
                              f"没打算动的地方，例如 {stray[0]}")
    return len(changed), ""


def _backup_and_write(target: Path, backup_dir: Path, updated: str) -> tuple[str, str]:
    """Back up the current config, write atomically, then read the file back.

    Returns (backup file name, failure explanation). The backup goes to
    `backup_dir`, never next to `target`: the master's directory is copied
    wholesale into MaaEnd's config before every run, so a .bak left there
    would travel along each time.
    """
    stamp = datetime.now(tz=SERVER_TZ)
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    backup = Path(backup_dir) / f"{target.stem}.bak-{stamp:%Y%m%d-%H%M%S}.json"
    shutil.copy2(target, backup)
    try:
        atomic_write_text(target, updated)
    except OSError as exc:
        shutil.copy2(backup, target)
        return backup.name, f"写入失败，已回滚: {exc}"
    # The master is the file of record (nothing holds it in memory), so reading
    # the disk back is a real check that the edit is what the next run gets.
    if target.read_text(encoding="utf-8") != updated:
        shutil.copy2(backup, target)
        return backup.name, "写进去之后读出来和写的不一样，已换回原样"
    return backup.name, ""


def apply_changes(root: Path, changes: list[dict], automas_dir: "Path | None",
                  backup_dir: Path) -> tuple[bool, str]:
    """Apply a whole batch of option changes. Returns (success, human-readable explanation).

    `root` is the MaaEnd install (option definitions); the config written is
    the AUTO-MAS master under `automas_dir`. There is deliberately no fallback
    to MaaEnd's own config/mxu-MaaEnd.json - it is overwritten from the master
    before every run, so writing it would report a change that never happens.

    A batch rather than one at a time, because MaaEnd's options are related to
    each other: switching to operator progression and then picking its reward
    set is **one** intent, and landing half of it makes the machine farm things
    nobody wants. Either every change validates and gets written, or the file
    is not touched at all.
    """
    mc = MaaEndConfig(root)
    target = mastercfg.maaend_master(automas_dir)
    if not target or not target.is_file():
        return False, "找不到 AUTO-MAS 里的终末地母本配置（mxu-MaaEnd.json），没有改"

    original = target.read_text(encoding="utf-8")
    try:
        cfg = json.loads(original)
    except json.JSONDecodeError as exc:
        return False, f"终末地母本配置本身不是合法 JSON，拒绝改动: {exc}"

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

    name, failed = _backup_and_write(target, backup_dir,
                                     json.dumps(cfg, ensure_ascii=False, indent=2))
    if failed:
        return False, failed
    return True, f"改动 {n_changed} 处（备份 {name}）：" + "；".join(applied)
