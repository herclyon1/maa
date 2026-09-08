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
from pathlib import Path

from .config import atomic_write_text, master_config_dir

log = logging.getLogger("ark.mastercfg")

# The items that actually show up on the phone. **Not everything editable**:
# stuffing the full option set into one ntfy message exceeds the size limit and
# gets truncated, and the page's JSON.parse then fails outright (that bit us on
# 2026-08-31). Only what really gets changed day to day is kept here.
MAAEND_SHOWN: dict[str, tuple[str, ...]] = {
    "AutoEssence": (
        "@enabled",
        "AutoEssenceDoOverride",        # Use override vouchers (使用刻写券)
        "AutoEssenceObtainMode",        # Claim mode: none / single / double (领取方式)
        "AutoEssenceRepeatCount",       # Max loop count (最大循环次数)
        "AutoEssenceChooseLocation",    # Region choice (地区选择)
        "EssenceFilterAfterBattle",     # Post-battle essence filtering (战后基质筛选)
        # MaaEnd v2.28 folded the sanity booster into essence farming: these two
        # replace the standalone AutoUseSpMedication task (still present in the
        # config as an orphan, see read_maaend). The user asked for the booster
        # settings on the page on 2026-09-09: 「你把终末地吃理智的设置做进手机控制页里面」.
        "AutoUseSpMedication",                    # When sanity runs out: stop / use booster
        "AutoEssenceSpMedicationExpireWithinDays",  # Use boosters expiring within N days
    ),
    "AutoCollect": (
        "@enabled",
        # With only a switch, the phone gives no way to see which routes it
        # will gather or on which days.
        # The user, 2026-09-04: 「自动采集任务，你应该显示采集路线。」
        # ("For the auto-gather task you should show the gathering routes.")
        # That day it "finished" in 0.16 seconds, precisely because the
        # schedule only had Monday and Thursday ticked -- and the page said
        # nothing about it at all.
        "AutoCollectRoutes",            # Which routes to gather (采哪几条路线)
        "AutoCollectSchedule",          # Which days to gather (哪几天采)
    ),
}

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


def _jsonc(path: Path) -> dict:
    """MaaEnd task definitions are JSON with // comments."""
    return json.loads(_COMMENT.sub("", path.read_text(encoding="utf-8")))


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
        out["orphans"] = [t.get("taskName") for inst in doc.get("instances") or []
                          for t in inst.get("tasks") or []
                          if t.get("taskName") and t.get("taskName") not in all_tasks]
    # The page must never show a raw key. Anything that fails to translate is
    # listed here, logged, and shown on the page as untranslated - instead of
    # quietly appearing as English (the user, 2026-09-09: 「不是说强制要求了人话界面吗」).
    out["untranslated"] = []
    for task_name, wanted in MAAEND_SHOWN.items():
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
                if not d:
                    continue
                kind0 = str(d.get("type") or "")
                if kind0 == "select":
                    cur = {"type": "select", "caseName": d.get("default_case")}
                elif kind0 == "switch":
                    cur = {"type": "switch", "value": bool(d.get("default"))}
                else:
                    continue
            label = zh(d.get("label"))
            if not label or label == d.get("label", "").lstrip("$") or not _HAN.search(label):
                out["untranslated"].append(key)
                log.warning("MaaEnd 选项 %s 没有中文名（定义%s），手机页会标成没翻译",
                            key, "找到了" if d else "找不到")
            out["labels"][key] = label or opt
            kind = str(cur.get("type") or d.get("type") or "")
            if kind == "switch":
                out["values"][key] = bool(cur.get("value"))
            elif kind == "select":
                out["values"][key] = cur.get("caseName")
            elif kind == "checkbox":
                out["values"][key] = list(cur.get("caseNames") or [])
            elif kind == "input":
                vals = cur.get("values") or {}
                out["values"][key] = next(iter(vals.values()), "")
            if kind in ("select", "checkbox"):
                cases = [[zh(c.get("label")) or str(c.get("name")), str(c.get("name"))]
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
            if d.get("type") == "select" and d.get("default_case") is not None:
                task.setdefault("optionValues", {})[opt] = {"type": "select",
                                                            "caseName": d["default_case"]}
                cur = task["optionValues"][opt]
                log.info("母本里 %s 还没有 %s，按 MaaEnd 定义的默认值 %r 建了这一项", task_name, opt, d["default_case"])
            else:
                return False, (f"{task_name} 里没有 {opt} 这一项，已拒绝"
                               "（不许凭空造字段——826 就是这么出的事）")
        kind = str(cur.get("type") or "")
        # The value must be one this item itself declares; no filling in whatever
        allowed = {str(c.get("name")) for c in (d.get("cases") or [])}
        if kind == "switch":
            before = bool(cur.get("value"))
            cur["value"] = bool(value)
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
            vals = cur.get("values") or {}
            name = next(iter(vals), "")
            if not name:
                return False, f"{opt} 没有可填的输入框"
            before = vals[name]
            cur["values"][name] = str(value)
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


def read_maa(automas_dir) -> dict:
    out: dict = {"values": {}, "options": {}, "labels": {}}
    f = maa_master(automas_dir)
    if not f or not f.is_file():
        # Silence here meant the phone page dropped whole sections with no trace
        # on either end. The file has been renamed and damaged on this machine.
        log.warning("母本配置文件不在：%s（手机页那一段会标成读不到）", f or "没找到路径")
        return out
    try:
        task = _maa_infrast(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        log.warning("母本 gui.new.json 读不出来", exc_info=True)
        return out
    if task is None:
        return out
    out["values"][MAA_DRONES_PATH] = str(task.get("UsesOfDrones") or "")
    out["options"][MAA_DRONES_PATH] = [[label, key] for key, label in MAA_DRONES]
    out["labels"][MAA_DRONES_PATH] = "基建无人机用在哪"
    return out


def write_maa(automas_dir, maa_dir, path: str, value) -> tuple[bool, str]:
    """Change what the infrastructure drones are used on. Both the master copy
    and the copy in the MAA directory are written; only the seven values MAA
    itself declares are accepted.
    """
    if str(path) != MAA_DRONES_PATH:
        return False, f"MAA 只开放 {MAA_DRONES_PATH} 这一项，已拒绝 {path!r}"
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
            return False, f"{f} 写完回读不对"
        written.append(f.name)
    if not written:
        return False, "找不到 MAA 的母本配置"
    zh = dict(MAA_DRONES)
    if before == str(value):
        return True, f"基建无人机本来就用在{zh[str(value)]}"
    return True, f"基建无人机用在哪：{zh.get(str(before), before)} → {zh[str(value)]}（写了 {len(written)} 份）"


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
                       "（不许凭空造字段——826 就是这么出的事）")
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
