"""Reading and writing each script's own config (the master copy).

**Why this exists** (established on the night of 2026-09-03): once AUTO-MAS's
"quick config" is switched off, the fields in the MAS user config are **no
longer pushed down** to the scripts --

* `app/task/Okww/AutoProxy.py:320` `if not ...get("Info","IfQuickConfig"): return`,
  so `Which to Farm` / `Material Selection` and that whole batch never reach
  OK-WW at all;
* after `app/task/MaaEnd/AutoProxy.py:537`, the sanity tasks are only read from
  MAS while it is on.

Both scripts now run with `IfQuickConfig=False`. Those are exactly the fields
the phone page had been editing until that day: the button gave a receipt and
the value really did land in MAS, but the script reads the master copy when it
runs, so it **changed nothing**. The only place that takes effect for good is
the master copy -- see the notes on `config.master_config_dir`.

(Arknights is different: AUTO-MAS has no quick-config concept for MAA at all,
`IfQuickConfig` is defined only on the MaaEnd and OK-WW config classes. MAA's
`Info.Mode` simple/detailed only decides which baseline gets copied as the
starting point; stage, sanity potions, series count and annihilation are
overwritten into gui.new.json on every dispatch --
`app/task/Maa/AutoProxy.py:796-845`. So routing those MAA items through MAS is
correct, and they are not this module's business.)

**Never invent the Chinese names**: every MaaEnd option and every one of its
values carries a language-pack key of the form `"$xxx.yyy"` in its own task
definition, and resolving that gives the official translation. Same for OK-WW,
via its `ok.po`. When upstream renames something, this follows.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from .config import atomic_write_text, master_config_dir

log = logging.getLogger("ark.mastercfg")

# The items that show up on the phone for tasks that list them by hand. The old
# reason for a short list (one ntfy message truncating, 2026-08-31) is gone: a
# big state is split into ordinary messages since 2026-09-09 (phone.py publish).
MAAEND_SHOWN: dict[str, tuple[str, ...]] = {
    "AutoCollect": (
        "@enabled",
        # With only a switch, the phone gives no way to see which routes it
        # will gather or on which days.
        # The user, 2026-09-04: 「自动采集任务，你应该显示采集路线。」
        # ("For the auto-gather task you should show the gathering routes.")
        # That day it "finished" in 0.16 seconds, precisely because the
        # schedule only had Monday and Thursday ticked -- and the page said
        # nothing about it at all.
        "AutoCollectSchedule",          # Which days to gather (哪几天采)
        # v2.28.0-beta.5 split the one route list per region: a switch for the
        # region, then its rare and common lists. The old AutoCollectRoutes key
        # is gone from the definitions, so a page still asking for it showed
        # nothing (the user, 2026-09-10: 「手机遥控器页面你也没修啊」).
        "AutoCollectValleyIV",
        "AutoCollectValleyIVRareRoutes",
        "AutoCollectValleyIVCommonRoutes",
        "AutoCollectWuling",
        "AutoCollectWulingRareRoutes",
        "AutoCollectWulingCommonRoutes",
        "AutoCollectMode",              # Tick-list or target-inventory gathering
    ),
}

# Sanity tasks: the phone gets each one's whole option tree, straight from the
# MaaEnd definitions, so no choice MaaEnd offers is missing. MaaEnd itself puts
# exactly these two in the group "sanity_sink" (v2.30.0-rc.1 task declarations;
# read on the machine 2026-09-25). Any other task MaaEnd adds to that group is
# picked up too. The user, 2026-09-25 15:10 (relayed): the phone page must
# carry every sanity-farming option, not only T-Creds.
# ProtocolSpace sits before AutoEssence in the task list, so with both on it
# spends the sanity first.
MAAEND_TREE_TASKS: tuple[str, ...] = ("ProtocolSpace", "AutoEssence")
MAAEND_TREE_GROUP = "sanity_sink"

OKWW_SHOWN: dict[str, tuple[str, ...]] = {
    "DailyTask.json": (
        "Which to Farm",
        "Material Selection",
        "Which Forgery Challenge to Farm",
        "Which Tacet Suppression to Farm",
    ),
}

# Shown read-only, not editable: the Nightmare Nest locations carry a standing
# order -- 「只刷落渊南丘」("farm Nanqiu only") -- and I have reverted it to
# "farm all" twice myself. Visible, but not clickable.
OKWW_READONLY: dict[str, tuple[str, ...]] = {
    "NightmareNestTask.json": ("Only Farm These Nests",),
}

_COMMENT = re.compile(r"^\s*//.*$", re.M)
_HAN = re.compile(r"[一-鿿]")


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas, leaving strings alone.

    Regex stripping is not enough: MaaEnd writes `"enabled": false //不购买任意物品`
    - a comment after a value on the same line - and CreditShopping.json and
    PuzzleSolver.json failed to parse on that, so the tasks they declare
    (CreditShoppingN2) were reported as orphans. A regex that removes `//.*`
    anywhere would eat "https://" inside strings, so this walks the text.
    """
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        out.append(c); i += 1
    cleaned = "".join(out)
    return re.sub(r",(\s*[}\]])", r"\1", cleaned)


def _jsonc(path: Path) -> dict:
    """MaaEnd task definitions are JSON with comments and trailing commas."""
    return json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))


class _Locale:
    """`$key` -> Chinese. On a miss, strip the `$` and return it as is. Never invent one."""

    def __init__(self, maaend_dir: Path | None) -> None:
        self.table: dict[str, str] = {}
        if not maaend_dir:
            return
        f = Path(maaend_dir) / "locales" / "interface" / "zh_cn.json"
        try:
            self.table = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("读不到 MaaEnd 的中文语言包，手机上只能显示英文键名")

    def __call__(self, ref: object) -> str:
        s = str(ref or "")
        return self.table.get(s[1:], s[1:]) if s.startswith("$") else s


def maaend_master(automas_dir) -> Path | None:
    d = master_config_dir(automas_dir, "mxu-MaaEnd.json")
    return (d / "mxu-MaaEnd.json") if d else None


def _maaend_task(doc: dict, name: str) -> dict | None:
    for t in (doc.get("instances") or [{}])[0].get("tasks", []):
        if t.get("taskName") == name:
            return t
    return None


def _maaend_defs(maaend_dir) -> tuple[dict, dict]:
    """(option definitions, task declarations) for the whole MaaEnd install.

    Read from the files `interface.json` imports, which is MaaEnd's own list of
    where its definitions live. Reading `tasks/<task>.json` by name stopped
    working in v2.28.0-beta.4: AutoEssence moved to tasks/AutoEssence/AutoEssence.json,
    the page lost every label and choice for it and showed raw keys instead
    (2026-09-09, on the user's phone). Option names are unique across the install,
    so one flat index is enough. A file that fails to parse is skipped and logged;
    CreditShopping.json and PuzzleSolver.json fail today and are not ours.
    """
    opts: dict = {}
    tasks: dict = {}
    if not maaend_dir:
        return opts, tasks
    root = Path(maaend_dir)
    files: list[Path] = []
    try:
        iface = _jsonc(root / "interface.json")
        files = [root / rel for rel in (iface.get("import") or []) if isinstance(rel, str)]
    except (OSError, ValueError, TypeError):
        log.warning("读不到 MaaEnd 的 interface.json，退回按文件名找定义")
    if not files:
        files = sorted((root / "tasks").glob("**/*.json"))
    for f in files:
        try:
            d = _jsonc(f)
        except (OSError, ValueError, TypeError) as exc:
            log.debug("MaaEnd 定义文件读不了 %s: %s", f.name, exc)
            continue
        for name, spec in (d.get("option") or {}).items():
            opts.setdefault(name, spec or {})
        for t in d.get("task") or []:
            if isinstance(t, dict) and t.get("name"):
                tasks.setdefault(t["name"], t)
    return opts, tasks


def _maaend_option_def(maaend_dir, task_name: str, opt: str, opts: dict | None = None) -> dict:
    """The definition of one option, from the install-wide index."""
    if opts is None:
        opts, _ = _maaend_defs(maaend_dir)
    return opts.get(opt) or {}


def _switch_on(case_name) -> bool:
    """MaaFramework ProjectInterface V2: a switch case named Yes/yes/Y/y is the
    on case (docs/en_us/3.3-ProjectInterfaceV2.md, "switch" under cases)."""
    return str(case_name) in ("Yes", "yes", "Y", "y")


_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)\s*")


def _plain(label: str) -> str:
    """Drop the Markdown item icons some MaaEnd labels start with, e.g.
    SupplyPlanLimits: "![](resource/image/UI/Item/item_gold.png) <name>"."""
    return _MD_IMAGE.sub("", str(label or "")).strip()


def _maaend_tree(opts: dict, roots: list[str]) -> tuple[str, ...]:
    """Every option reachable from `roots` through the cases' sub-options,
    parents before children, each once."""
    seen: list[str] = []

    def walk(o: str) -> None:
        if o in seen:
            return
        seen.append(o)
        for c in (opts.get(o) or {}).get("cases") or []:
            for sub in c.get("option") or []:
                walk(str(sub))

    for r in roots:
        walk(r)
    return tuple(seen)


def _maaend_default(d: dict) -> dict | None:
    """The config entry MaaEnd would run for an option absent from the config,
    in the same shape the config uses. None when the definition gives no
    default (a select without default_case)."""
    kind = str(d.get("type") or "")
    if kind == "select":
        return {"type": "select", "caseName": d["default_case"]} if d.get("default_case") is not None else None
    if kind == "switch":
        return {"type": "switch", "value": _switch_on(d.get("default_case"))}
    if kind == "checkbox":
        return {"type": "checkbox", "caseNames": [str(x) for x in d.get("default_case") or []]}
    if kind == "input":
        boxes = [i for i in d.get("inputs") or [] if i.get("name")]
        if not boxes:
            return None
        return {"type": "input", "values": {str(i["name"]): str(i.get("default", "")) for i in boxes}}
    return None


def _maaend_value(kind: str, cur: dict, d: dict, zh) -> tuple:
    """(value for the page, input boxes or None). Several input boxes give
    {input name: text} and [[Chinese label, input name]]; one box gives its text."""
    if kind == "switch":
        return bool(cur.get("value")), None
    if kind == "select":
        return cur.get("caseName"), None
    if kind == "checkbox":
        return list(cur.get("caseNames") or []), None
    vals = cur.get("values") or {}
    boxes = [i for i in d.get("inputs") or [] if i.get("name")]
    if len(boxes) > 1:
        return ({str(i["name"]): str(vals.get(i["name"], i.get("default", ""))) for i in boxes},
                [[_plain(zh(i.get("label"))) or str(i["name"]), str(i["name"])] for i in boxes])
    return next(iter(vals.values()), ""), None


def _maaend_children(task_name: str, kind: str, d: dict) -> dict:
    """{case name: [task/option it opens]}; a switch is keyed "true"/"false"."""
    kids = {}
    for c in d.get("cases") or []:
        sub = [f"{task_name}/{o}" for o in c.get("option") or []]
        if sub and c.get("name") is not None:
            name = str(c["name"])
            if kind == "switch":
                name = "true" if _switch_on(name) else "false"
            kids[name] = sub
    return kids


def read_maaend(automas_dir, maaend_dir) -> dict:
    """Returns `{"values": {"task/option": value},
    "options": {"task/option": [[Chinese label, value]]},
    "labels": {"task/option": Chinese name}}`. Empty when it cannot be read,
    and the page then hides that section.
    """
    out: dict = {"values": {}, "options": {}, "labels": {}}
    f = maaend_master(automas_dir)
    if not f or not f.is_file():
        # Silence here meant the phone page dropped whole sections with no trace
        # on either end. The file has been renamed and damaged on this machine.
        log.warning("母本配置文件不在：%s（手机页那一段会标成读不到）", f or "没找到路径")
        return out
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("母本 mxu-MaaEnd.json 读不出来", exc_info=True)
        return out
    zh = _Locale(Path(maaend_dir) if maaend_dir else None)
    all_opts, all_tasks = _maaend_defs(maaend_dir)
    # A task the config still carries but no definition file declares any more.
    # v2.28 removed the standalone AutoUseSpMedication task (the booster moved into
    # AutoEssence); the config kept the entry, and nothing said it was dead.
    if all_tasks:
        # MXU's own entries (__MXU_WEBHOOK__ and the like) are not MaaEnd tasks and
        # never appear in its definitions; they are not orphans.
        out["orphans"] = sorted({t.get("taskName") for inst in doc.get("instances") or []
                                 for t in inst.get("tasks") or []
                                 if t.get("taskName") and not str(t.get("taskName")).startswith("__")
                                 and t.get("taskName") not in all_tasks})
    # The page must never show a raw key. Anything that fails to translate is
    # listed here, logged, and shown on the page as untranslated - instead of
    # quietly appearing as English (the user, 2026-09-09: 「不是说强制要求了人话界面吗」).
    out["untranslated"] = []
    shown: dict[str, tuple[str, ...]] = dict(MAAEND_SHOWN)
    tree_tasks = list(MAAEND_TREE_TASKS) + sorted(
        n for n, t in all_tasks.items()
        if MAAEND_TREE_GROUP in (t.get("group") or []) and n not in MAAEND_TREE_TASKS)
    # For the tree tasks the page also gets the shape of the tree: the task's
    # top-level options ("roots") and which choice opens which options
    # ("children", keyed by case name; a switch is keyed "true"/"false").
    # An option whose parent does not currently open it is still listed, with
    # the value MaaEnd would run if it were opened.
    out["roots"] = {}
    out["children"] = {}
    # Options with several input boxes: [[Chinese label, input name]] per box;
    # their value is then {input name: text} instead of one string.
    out["inputs"] = {}
    for n in tree_tasks:
        roots = [str(o) for o in (all_tasks.get(n) or {}).get("option") or []]
        shown[n] = ("@enabled",) + _maaend_tree(all_opts, roots)
        out["roots"][n] = [f"{n}/{o}" for o in roots]
    for task_name, wanted in shown.items():
        task = _maaend_task(doc, task_name)
        if task is None:
            continue
        defs = all_opts
        decl = all_tasks.get(task_name) or {}
        out["labels"][f"{task_name}/@enabled"] = zh(
            decl.get("label") or f"$task.{task_name}.label")
        for opt in wanted:
            key = f"{task_name}/{opt}"
            if opt == "@enabled":
                out["values"][key] = bool(task.get("enabled"))
                continue
            d = defs.get(opt) or _maaend_option_def(maaend_dir, task_name, opt, defs)
            cur = (task.get("optionValues") or {}).get(opt)
            if cur is None:
                # Not in the config yet: MaaEnd then runs its default. Show the
                # default so the page can offer the choice (and write_maaend may
                # create the key, since the definition declares it).
                cur = _maaend_default(d) if d else None
                if cur is None and d.get("type") == "select":
                    # No declared default (ProtocolSpaceTab, the lines, the A/B
                    # sets): the value is unknown (None), the choices still go out.
                    cur = {"type": "select", "caseName": None}
                if cur is None:
                    continue
            label = zh(d.get("label"))
            if not label or label == d.get("label", "").lstrip("$") or not _HAN.search(label):
                out["untranslated"].append(key)
                log.warning("MaaEnd 选项 %s 没有中文名（定义%s），手机页会标成没翻译",
                            key, "找到了" if d else "找不到")
            out["labels"][key] = _plain(label) or opt
            kind = str(cur.get("type") or d.get("type") or "")
            if kind in ("switch", "select", "checkbox", "input"):
                out["values"][key], boxes = _maaend_value(kind, cur, d, zh)
                if boxes:
                    out["inputs"][key] = boxes
            if task_name in tree_tasks and _maaend_children(task_name, kind, d):
                out["children"][key] = _maaend_children(task_name, kind, d)
            if kind in ("select", "checkbox"):
                cases = [[_plain(zh(c.get("label"))) or str(c.get("name")), str(c.get("name"))]
                         for c in (d.get("cases") or []) if c.get("name")]
                if cases:
                    out["options"][key] = cases
                else:
                    if key not in out["untranslated"]:
                        out["untranslated"].append(key)
                    log.warning("MaaEnd 选项 %s 是选择项但没有可选值，手机页只能给个文本框", key)
    return out


def write_maaend(automas_dir, maaend_dir, path: str, value) -> tuple[bool, str]:
    """Change one item in the master copy. Write only what already exists, then
    read it back -- the same rule as `commands._set_config`.
    """
    task_name, _, opt = str(path).partition("/")
    f = maaend_master(automas_dir)
    if not f or not f.is_file():
        return False, "找不到 MaaEnd 的母本配置"
    doc = json.loads(f.read_text(encoding="utf-8"))
    task = _maaend_task(doc, task_name)
    if task is None:
        return False, f"母本里没有任务 {task_name}，已拒绝"
    label = task_name
    if opt == "@enabled":
        before = bool(task.get("enabled"))
        if before == bool(value):
            return True, f"{task_name} 本来就是{'开' if before else '关'}着的"
        task["enabled"] = bool(value)
    else:
        d = _maaend_option_def(maaend_dir, task_name, opt)
        cur = (task.get("optionValues") or {}).get(opt)
        if cur is None:
            # Only a key MaaEnd's own definition declares for this task may be
            # created, in the shape the definition gives it. Anything else is
            # inventing a field, which is how 826 happened.
            declared = {str(c.get("name")) for c in (d.get("cases") or [])}
            made = _maaend_default(d) if d else None
            if made is None and d.get("type") == "select" and str(value) in declared:
                # A select with no default_case (ProtocolSpaceTab, the three
                # lines, the four A/B sets): created with the value being written.
                made = {"type": "select", "caseName": None}
            if made is None:
                return False, (f"{task_name} 里没有 {opt} 这一项，已拒绝"
                               "（设置里本来没有它，中继不会自己新建）")
            task.setdefault("optionValues", {})[opt] = made
            cur = made
            log.info("母本里 %s 还没有 %s，按 MaaEnd 定义建了这一项：%r", task_name, opt, made)
        kind = str(cur.get("type") or "")
        # The value must be one this item itself declares; no filling in whatever
        allowed = {str(c.get("name")) for c in (d.get("cases") or [])}
        if kind == "switch":
            before = bool(cur.get("value"))
            if isinstance(value, bool):
                cur["value"] = value
            elif str(value).lower() in ("true", "false"):
                cur["value"] = str(value).lower() == "true"
            else:
                return False, f"{opt} 是开关，只接受真或假，收到的是 {value!r}"
        elif kind == "select":
            before = cur.get("caseName")
            if allowed and str(value) not in allowed:
                return False, f"{opt} 不认识取值 {value!r}，它只接受 {sorted(allowed)}"
            cur["caseName"] = str(value)
        elif kind == "checkbox":
            before = list(cur.get("caseNames") or [])
            picked = [str(v) for v in (value if isinstance(value, list) else [value])]
            if allowed and not set(picked) <= allowed:
                return False, f"{opt} 里有不认识的取值：{sorted(set(picked) - allowed)}"
            if not picked:
                return False, f"{opt} 不能一个都不选"
            cur["caseNames"] = picked
        elif kind == "input":
            vals = cur.setdefault("values", {})
            boxes = {str(i["name"]): i for i in d.get("inputs") or [] if i.get("name")}
            if isinstance(value, dict):
                # Several boxes: change only the ones named.
                want = {str(k): str(v) for k, v in value.items()}
            else:
                name = next(iter(vals), "") or next(iter(boxes), "")
                if not name:
                    return False, f"{opt} 没有可填的输入框"
                want = {name: str(value)}
            unknown = sorted(set(want) - set(boxes or vals))
            if unknown:
                return False, f"{opt} 没有这些输入框：{unknown}"
            for name, text in want.items():
                rule = (boxes.get(name) or {}).get("verify")
                if rule and not re.fullmatch(rule, text):
                    return False, f"{opt} 的 {name} 填的 {text!r} 不合格式（{rule}）"
            before = dict(vals) if len(want) > 1 or isinstance(value, dict) else vals.get(next(iter(want)))
            vals.update(want)
        else:
            return False, f"{opt} 是没见过的类型 {kind!r}，不敢动"
        label = f"{task_name} 的 {opt}"
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    back = json.loads(f.read_text(encoding="utf-8"))
    now = read_maaend(automas_dir, maaend_dir)["values"].get(path)
    if opt == "@enabled":
        now = bool((_maaend_task(back, task_name) or {}).get("enabled"))
    return True, f"{label}：{before!r} → {now!r}"


# ─────────────────────────────── MAA ───────────────────────────────
# What the infrastructure drones are used on. AUTO-MAS does not handle this
# item (it is not in its user config); it lives only in MAA's own gui.new.json:
# Configurations/<Current>/TaskQueue/<the infrastructure task>/UsesOfDrones.
# The values and their Chinese names are taken from MAA's source,
# InfrastSettingsUserControlModel.UsesOfDronesList, and from
# docs/protocol/integration.md (checked 2026-09-07, v6.17).
# The master copy is at AUTO-MAS's
# data/<MAA script id>/Default/ConfigFile/gui.new.json; the copy in the MAA
# directory is overwritten by the master before every launch, but both are
# written and both are verified (background: memory maa-config-master-copy).
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
# on purpose: MAA itself pops a warning before enabling it. Found 2026-09-14:
# Mail had been off all along - three days of mail sat unclaimed while the
# report read 全绿, because Award only checks its own chain finished.
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


def _maa_infrast(doc: dict) -> dict | None:
    cfgs = doc.get("Configurations") or {}
    c = cfgs.get(doc.get("Current") or "Default") or cfgs.get("Default") or {}
    for t in c.get("TaskQueue") or []:
        if isinstance(t, dict) and "UsesOfDrones" in t:
            return t
    return None


def _maa_award(doc: dict) -> dict | None:
    cfgs = doc.get("Configurations") or {}
    c = cfgs.get(doc.get("Current") or "Default") or cfgs.get("Default") or {}
    for t in c.get("TaskQueue") or []:
        if isinstance(t, dict) and (t.get("Type") == "Award" or ("Mail" in t and "FreeGacha" in t)):
            return t
    return None


def read_maa(automas_dir) -> dict:
    out: dict = {"values": {}, "options": {}, "labels": {}}
    f = maa_master(automas_dir)
    if not f or not f.is_file():
        # Silence here meant the phone page dropped whole sections with no trace
        # on either end. The file has been renamed and damaged on this machine.
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
    targets = [maa_master(automas_dir)]
    if maa_dir:
        targets.append(Path(maa_dir) / "config" / "gui.new.json")
    before = None
    written = []
    for f in targets:
        if not f or not f.is_file():
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        task = _maa_infrast(doc)
        if task is None:
            return False, f"{f.name} 里找不到带 UsesOfDrones 的基建任务，已拒绝"
        if before is None:
            before = task.get("UsesOfDrones")
        task["UsesOfDrones"] = str(value)
        atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=4))
        back = _maa_infrast(json.loads(f.read_text(encoding="utf-8")))
        if not back or back.get("UsesOfDrones") != str(value):
            return False, f"{f} 写进去之后读出来和写的不一样"
        written.append(f.name)
    if not written:
        return False, "找不到 MAA 的母本配置"
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
    targets = [maa_master(automas_dir)]
    if maa_dir:
        targets.append(Path(maa_dir) / "config" / "gui.new.json")
    before = None
    written = []
    for f in targets:
        if not f or not f.is_file():
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        task = _maa_award(doc)
        if task is None:
            return False, f"{f.name} 里找不到领取奖励任务，已拒绝"
        if before is None:
            before = bool(task.get(key, False))
        task[key] = value
        atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=4))
        back = _maa_award(json.loads(f.read_text(encoding="utf-8")))
        if not back or back.get(key) is not value:
            return False, f"{f} 写进去之后读出来和写的不一样"
        written.append(f.name)
    if not written:
        return False, "找不到 MAA 的母本配置"
    state = "开" if value else "关"
    if before is value:
        return True, f"「{zh}」本来就是{state}的"
    return True, f"「{zh}」：{'开' if before else '关'} → {state}（写了 {len(written)} 份）"


# ─────────────────────────────── OK-WW ───────────────────────────────

def okww_file(automas_dir, name: str) -> Path | None:
    d = master_config_dir(automas_dir, "DailyTask.json")
    return (d / name) if d else None


# Which sub-setting appears below depends on which entry of "what to farm" is
# selected. Taken from OK-WW's own sub_configs.
OKWW_SUBS = {
    "Tacet Suppression": ["DailyTask.json/Which Tacet Suppression to Farm"],
    "Forgery Challenge": ["DailyTask.json/Which Forgery Challenge to Farm"],
    "Simulation Challenge": ["DailyTask.json/Material Selection"],
}

_LIST = {
    "Which to Farm": r"support_tasks\s*=\s*\[([^\]]*)\]",
    "Material Selection": r"material_option_list\s*=\s*\[([^\]]*)\]",
}


def _okww_cases(okww_dir) -> dict[str, list[str]]:
    """The dropdown candidates are read from OK-WW's **own source**, never invented here."""
    out: dict[str, list[str]] = {}
    if not okww_dir:
        return out
    f = (Path(okww_dir) / "data" / "apps" / "ok-ww" / "working" / "src"
         / "task" / "DailyTask.py")
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for key, pat in _LIST.items():
        m = re.search(pat, text, re.S)
        if m:
            vals = re.findall(r"""['"]([^'"]+)['"]""", m.group(1))
            if vals:
                out[key] = vals
    return out


def read_okww(automas_dir, okww_dir) -> dict:
    """Values, candidates and Chinese names. Every Chinese name comes from the
    ok.po that ships with OK-WW.

    Only on 2026-09-03 did it turn out that the labels for those two indices on
    the page were ones I had made up myself -- and had swapped: the official
    translation of `Forgery Challenge` is 「凝素领域」, and `Tacet Suppression`
    is 「无音区」.
    """
    out: dict = {"values": {}, "options": {}, "labels": {}, "readonly": {},
                 "subs": OKWW_SUBS}
    try:
        from . import plan  # noqa: PLC0415
        zh = plan._okww_zh(Path(okww_dir) if okww_dir else None)
    except Exception:  # noqa: BLE001
        zh = {}
    cases = _okww_cases(okww_dir)
    for name, wanted in OKWW_SHOWN.items():
        f = okww_file(automas_dir, name)
        if not f or not f.is_file():
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key in wanted:
            if key not in doc:
                continue
            path = f"{name}/{key}"
            out["values"][path] = doc[key]
            if zh.get(key):
                out["labels"][path] = zh[key]
            if key in cases:
                out["options"][path] = [[zh.get(v, v), v] for v in cases[key]]
    for name, wanted in OKWW_READONLY.items():
        f = okww_file(automas_dir, name)
        if not f or not f.is_file():
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key in wanted:
            if key in doc:
                out["readonly"][f"{name}/{key}"] = doc[key]
                if zh.get(key):
                    out["labels"][f"{name}/{key}"] = zh[key]
    return out


def write_okww(automas_dir, path: str, value) -> tuple[bool, str]:
    name, _, key = str(path).partition("/")
    if name in OKWW_READONLY and key in OKWW_READONLY[name]:
        return False, f"{key} 在手机上是只读的（死命令：残象聚落只刷落渊南丘）"
    if key not in OKWW_SHOWN.get(name, ()):
        return False, f"{path} 不在手机可改的清单里，已拒绝"
    f = okww_file(automas_dir, name)
    if not f or not f.is_file():
        return False, f"找不到 OK-WW 的母本 {name}"
    doc = json.loads(f.read_text(encoding="utf-8"))
    if key not in doc:
        return False, (f"{name} 里没有「{key}」这一项，已拒绝"
                       "（设置里本来没有它，中继不会自己新建）")
    before = doc[key]
    if isinstance(before, bool):
        new: object = bool(value)
    elif isinstance(before, int) and not isinstance(before, bool):
        try:
            new = int(value)
        except (TypeError, ValueError):
            return False, f"「{key}」要一个整数，收到 {value!r}"
    else:
        new = str(value)
    if before == new:
        return True, f"「{key}」本来就是 {before!r}，没有改动"
    doc[key] = new
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    now = json.loads(f.read_text(encoding="utf-8")).get(key)
    if now != new:
        return False, f"写了但没生效：「{key}」现在是 {now!r}"
    return True, f"「{key}」：{before!r} → {now!r}"


def prune_maaend_orphans(automas_dir, maaend_dir) -> tuple[list[str], str]:
    """Remove config entries for tasks this MaaEnd no longer has. Returns (removed, note).

    v2.28 dropped the standalone AutoUseSpMedication task (the booster moved into
    AutoEssence). The config kept the entry, the page warned about it, and the
    user's answer was the right one: 「你光报警不去修吗？」 A dead entry costs a
    warning every day and nothing else, so it goes.

    Two independent signals are required before anything is deleted, because the
    definition index alone is not proof: a definition file that fails to parse
    makes every task it declares look absent (that happened with CreditShopping.json
    the same night). A task that is missing from the definitions **and** has no
    `task.<name>.label` in MaaEnd's own language pack is one MaaEnd does not know.
    MXU's internal entries (`__*`) are never touched. The file is backed up first.
    """
    f = maaend_master(automas_dir)
    if not f or not f.is_file():
        return [], "找不到 MaaEnd 的母本"
    _, tasks = _maaend_defs(maaend_dir)
    if not tasks:
        return [], "读不到 MaaEnd 的任务定义，不动配置"
    zh = _Locale(Path(maaend_dir) if maaend_dir else None)
    if not zh.table:
        return [], "读不到 MaaEnd 的语言包，不动配置"
    doc = json.loads(f.read_text(encoding="utf-8"))
    removed: list[str] = []
    for inst in doc.get("instances") or []:
        keep = []
        for t in inst.get("tasks") or []:
            name = str(t.get("taskName") or "")
            dead = (name and not name.startswith("__") and name not in tasks
                    and f"task.{name}.label" not in zh.table)
            (removed if dead else keep).append(name if dead else t)
        inst["tasks"] = keep
    if not removed:
        return [], ""
    bak = f.with_name(f.name + f".bak-orphans-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    bak.write_bytes(f.read_bytes())
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    back = json.loads(f.read_text(encoding="utf-8"))
    left = [t.get("taskName") for inst in back.get("instances") or [] for t in inst.get("tasks") or []]
    if any(n in left for n in removed):
        return [], f"写进去之后读出来和写的不一样，{bak.name} 是原样"
    return removed, (f"MaaEnd 这一版已经没有这些任务，配置里的死条目已清掉：{'、'.join(removed)}"
                     f"（原文件备份为 {bak.name}）")


# ── Option format changes between MaaEnd versions ───────────────────────────
# v2.28.0-beta.5 (2026-09-10) split 自动采集's one route list into a per-region
# switch plus rare/common checkboxes, and made 基质刷取's location a sub-option of
# a new AutoEssenceMenu. MaaEnd itself discards a saved value whose option no
# longer exists and runs on defaults - so the master AUTO-MAS copies over before
# every run kept feeding it the old keys, and every run silently lost the routes.
# Each entry: old key -> how to rewrite it. Only what has actually been observed
# is translated; anything else that is dead is removed and named in the note.
_COLLECT_SPLIT = {
    "AutoCollectRoutes": ("AutoCollectValleyIVRareRoutes", "AutoCollectWulingRareRoutes"),
    "AutoCollectCommonRoutes": ("AutoCollectValleyIVCommonRoutes", "AutoCollectWulingCommonRoutes"),
}


def _cases(opts: dict, name: str) -> list[str]:
    return [c.get("name") for c in (opts.get(name) or {}).get("cases") or [] if c.get("name")]


def _stale_entry(entry: dict, opts: dict, tasks: dict) -> bool:
    """A closed-tab record whose task (definition read) carries a key MaaEnd no longer has."""
    return any(str(t.get("taskName") or "") in tasks
               and any(k not in opts for k in (t.get("optionValues") or {}))
               for t in entry.get("tasks") or [])


def _prune_recently_closed(doc: dict, opts: dict, tasks: dict) -> int:
    """Drop stale records from MXU's recentlyClosed list; returns how many went.

    MXU keeps the tabs the user closed under recentlyClosed, option values and
    all, and re-validates them on every load. The instance was clean after the
    16:13 migration on 2026-09-10 and MaaEnd still logged 33 「已不存在」 lines
    at 16:42 - every one of them from that history.
    """
    before = doc.get("recentlyClosed") or []
    kept = [e for e in before if not _stale_entry(e, opts, tasks)]
    if len(kept) != len(before):
        doc["recentlyClosed"] = kept
    return len(before) - len(kept)


def migrate_maaend_options(automas_dir, maaend_dir) -> tuple[list[str], str]:
    """Rewrite option values in the master that this MaaEnd no longer understands.

    Returns (changes, note). A key is dead only when its task's definition file
    was read successfully **and** the key is absent from the whole install's
    option index - a definition file that fails to parse (CreditShopping.json
    does) must not make its options look dead. MXU's own `__*` tasks are never
    touched. The file is backed up first and read back after.
    """
    f = maaend_master(automas_dir)
    if not f or not f.is_file():
        return [], "找不到 MaaEnd 的母本"
    opts, tasks = _maaend_defs(maaend_dir)
    if not opts or not tasks:
        return [], "读不到 MaaEnd 的选项定义，不动配置"
    doc = json.loads(f.read_text(encoding="utf-8"))
    changes: list[str] = []
    for inst in doc.get("instances") or []:
        for task in inst.get("tasks") or []:
            name = str(task.get("taskName") or "")
            if not name or name.startswith("__") or name not in tasks:
                continue
            ov = task.get("optionValues")
            if not isinstance(ov, dict):
                continue
            # 自动采集: one route list -> per-region switch + rare/common lists.
            for old, (valley, wuling) in _COLLECT_SPLIT.items():
                if old not in ov or valley in ov or wuling in ov:
                    continue
                picked = set((ov[old] or {}).get("caseNames") or [])
                for new in (valley, wuling):
                    mine = [c for c in _cases(opts, new) if c in picked]
                    ov[new] = {"type": "checkbox", "caseNames": mine}
                    region = "AutoCollectValleyIV" if "ValleyIV" in new else "AutoCollectWuling"
                    ov.setdefault(region, {"type": "switch", "value": True})
                changes.append(f"{name}/{old} → 按区域拆成 {valley}、{wuling}"
                               f"（保留原来勾的 {len(picked)} 条）")
            if name == "AutoCollect" and "AutoCollectMode" in opts and "AutoCollectMode" not in ov:
                ov["AutoCollectMode"] = {"type": "select", "caseName": "Always"}
                changes.append(f"{name}/AutoCollectMode 补上默认值 Always")
            # 基质刷取: the location list now hangs under AutoEssenceMenu=Random;
            # without the menu key MaaEnd falls back to its default location.
            if name == "AutoEssence":
                if "AutoEssenceMenu" in opts and "AutoEssenceMenu" not in ov:
                    ov["AutoEssenceMenu"] = {"type": "select", "caseName": "Random"}
                    changes.append(f"{name}/AutoEssenceMenu 补上 Random（原来的按地点随机刷）")
                if ("AutoUseSpMedication" in opts and "AutoUseSpMedication" not in ov
                        and "AutoEssenceSpMedicationExpireWithinDays" in ov):
                    ov["AutoUseSpMedication"] = {"type": "select", "caseName": "UseMedication"}
                    changes.append(f"{name}/AutoUseSpMedication 补上 UseMedication（原来就在吃药）")
            dead = [k for k in list(ov) if k not in opts]
            for k in dead:
                del ov[k]
            if dead:
                changes.append(f"{name} 去掉新版本没有的 {len(dead)} 项：{'、'.join(dead)}")
    if dropped := _prune_recently_closed(doc, opts, tasks):
        changes.append(f"清掉界面里 {dropped} 条「最近关闭」的旧记录（全是旧格式的设置）")
    if not changes:
        return [], ""
    bak = f.with_name(f.name + f".bak-migrate-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    bak.write_bytes(f.read_bytes())
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    back = json.loads(f.read_text(encoding="utf-8"))
    for inst in back.get("instances") or []:
        for task in inst.get("tasks") or []:
            ov = task.get("optionValues") or {}
            if str(task.get("taskName") or "") in tasks and any(k not in opts for k in ov):
                return [], f"写进去之后再读，旧写法的项还在，{bak.name} 是原样"
    if any(_stale_entry(e, opts, tasks) for e in back.get("recentlyClosed") or []):
        return [], f"写进去之后再读，「最近关闭」里旧写法的项还在，{bak.name} 是原样"
    return changes, ("MaaEnd 换了版本后旧设置的写法它不认了，母本已按原意改写：\n"
                     + "\n".join(f"· {c}" for c in changes)
                     + f"\n（原文件备份为 {bak.name}）")
