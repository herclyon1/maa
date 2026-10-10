"""Reading and writing each script's own config (the master copy), and MaaEnd's.

With AUTO-MAS's "quick config" off (`IfQuickConfig=False`, how both MaaEnd and
OK-WW run), the fields in the MAS user config are not pushed down to the scripts:

* `app/task/Okww/AutoProxy.py:320` `if not ...get("Info","IfQuickConfig"): return`,
  so `Which to Farm` / `Material Selection` and the rest never reach OK-WW;
* after `app/task/MaaEnd/AutoProxy.py:537`, the sanity tasks are read from MAS
  only while it is on.

So a change takes effect only in the master copy, which AUTO-MAS copies over the
script's own config before each run (see `config.master_config_dir`).

MAA is different: AUTO-MAS has no quick-config concept for MAA (`IfQuickConfig`
exists only on the MaaEnd and OK-WW config classes), and stage, sanity potions,
series count and annihilation are written into gui.new.json on every dispatch
(`app/task/Maa/AutoProxy.py:796-845`), so those go through MAS and not through
this module. MAA's drones and Award switches are in mastercfg_maa.py; OK-WW is in
mastercfg_okww.py.

**Chinese names are never invented**: every MaaEnd option and value carries a
language-pack key `"$xxx.yyy"` in its own task definition, resolved to the
official translation (_Locale). Same for OK-WW, via its `ok.po`.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from ark_relay.features.alarm import errwatch
from ark_relay.core import texts
from ark_relay.core.config import atomic_write_text, master_config_dir

# MAA and OK-WW config live in mastercfg_maa / mastercfg_okww; callers and tests
# say mastercfg.<name>, so those names are importable from here too.
from ark_relay.core.mastercfg_maa import (  # noqa: F401
    MAA_AWARD, MAA_AWARD_PATHS, MAA_DRONES, MAA_DRONES_PATH, _maa_award, _maa_infrast, _maa_task,
    _write_maa_award, _write_maa_copies, maa_master, read_maa, write_maa,
)
from ark_relay.core.mastercfg_okww import (  # noqa: F401
    OKWW_READONLY, OKWW_SHOWN, OKWW_SUBS, _LIST, _last_error, _okww_cases, _okww_doc, okww_file,
    read_okww, write_okww,
)

log = logging.getLogger("ark.mastercfg")


# The items that show up on the phone for tasks that list them by hand.
MAAEND_SHOWN: dict[str, tuple[str, ...]] = {
    "AutoCollect": (
        "@enabled",
        # Besides the switch: which days and which routes it gathers.
        "AutoCollectSchedule",          # Which days to gather (哪几天采)
        # From v2.28.0-beta.5 routes are per region: a switch for the region,
        # then its rare and common lists (the old AutoCollectRoutes is gone).
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
# exactly these two in the group "sanity_sink" (v2.30.0-rc.1 task declarations);
# any other task MaaEnd adds to that group is picked up too.
# ProtocolSpace sits before AutoEssence in the task list, so with both on it
# spends the sanity first.
MAAEND_TREE_TASKS: tuple[str, ...] = ("ProtocolSpace", "AutoEssence")
MAAEND_TREE_GROUP = "sanity_sink"


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
    where its definitions live (a task's file is not always tasks/<task>.json:
    AutoEssence is tasks/AutoEssence/AutoEssence.json). Option names are unique
    across the install, so one flat index is enough. A file that fails to parse
    is skipped and logged.
    """
    opts, tasks, _unread, _listed = _read_maaend_defs(maaend_dir)
    return opts, tasks


def _read_maaend_defs(maaend_dir) -> "tuple[dict, dict, list[tuple[Path, str | None]], bool]":
    """_maaend_defs plus what it could not see: (opts, tasks, unread, listed).

    `unread` is every existing definition file that did not parse, with its raw
    text (None when it could not even be opened; a listed file that does not
    exist defines nothing and is not in it); `listed` is False when the file list is
    the fallback glob because interface.json - MaaEnd's own list - was unreadable.
    """
    opts: dict = {}
    tasks: dict = {}
    unread: list = []
    if not maaend_dir:
        return opts, tasks, unread, False
    root = Path(maaend_dir)
    files: list[Path] = []
    try:
        iface = _jsonc(root / "interface.json")
        files = [root / rel for rel in (iface.get("import") or []) if isinstance(rel, str)]
    except (OSError, ValueError, TypeError):
        log.warning("读不到 MaaEnd 的 interface.json，退回按文件名找定义")
    listed = bool(files)
    if not files:
        files = sorted((root / "tasks").glob("**/*.json"))
    for f in files:
        try:
            d = _jsonc(f)
        except (OSError, ValueError, TypeError) as exc:
            log.debug("MaaEnd 定义文件读不了 %s: %s", f.name, exc)
            if not f.exists():
                continue            # nothing on disk: it defines nothing
            try:
                unread.append((f, f.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                unread.append((f, None))
            continue
        for name, spec in (d.get("option") or {}).items():
            opts.setdefault(name, spec or {})
        for t in d.get("task") or []:
            if isinstance(t, dict) and t.get("name"):
                tasks.setdefault(t["name"], t)
    return opts, tasks, unread, listed


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
        # Said, so the phone page's missing section has a cause in the log.
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
    if all_tasks:
        # MXU's own entries (__MXU_WEBHOOK__ and the like) are not MaaEnd tasks and
        # never appear in its definitions; they are not orphans.
        out["orphans"] = sorted({t.get("taskName") for inst in doc.get("instances") or []
                                 for t in inst.get("tasks") or []
                                 if t.get("taskName") and not str(t.get("taskName")).startswith("__")
                                 and t.get("taskName") not in all_tasks})
    # The page must never show a raw key. Anything that fails to translate is
    # listed here, logged, and shown on the page as untranslated, not as English.
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
            # created, in the shape the definition gives it; nothing else is
            # invented.
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


def prune_maaend_orphans(automas_dir, maaend_dir) -> tuple[list[str], str]:
    """Remove config entries for tasks this MaaEnd no longer has. Returns (removed, note).

    A dead entry (MaaEnd v2.28 dropped AutoUseSpMedication, for one) would be
    warned about on the phone page every day; it is removed instead.

    It never removes an entry MaaEnd still defines. Two independent signals are
    required, because the definition index alone is not proof: a definition file
    that fails to parse makes every task it declares look absent. A task
    that is missing from the definitions **and** has no `task.<name>.label` in
    MaaEnd's own language pack is one MaaEnd does not know. On top of that it
    refuses outright - ([], reason) - when it cannot see every definition:
    interface.json (MaaEnd's list of definition files) unreadable, a listed file
    that cannot be opened, or a candidate named in a file that does not parse.
    MXU's internal entries (`__*`) are never touched. The file is backed up first.

    Every deletion and every refusal is a WARNING logged here, so it reaches the
    group (errwatch) each time: a deletion names each entry and whether it was
    switched on. The caller need not log the note again.
    """
    f = maaend_master(automas_dir)
    if not f or not f.is_file():
        return _prune_refused("找不到 MaaEnd 的母本")
    _, tasks, unread, listed = _read_maaend_defs(maaend_dir)
    if not tasks:
        return _prune_refused("读不到 MaaEnd 的任务定义，不动配置")
    if not listed:
        return _prune_refused("读不到 MaaEnd 的任务定义清单（interface.json），不知道定义全不全，不动配置")
    if blind := [x.name for x, text in unread if text is None]:
        return _prune_refused(f"MaaEnd 的任务定义文件打不开（{'、'.join(blind)}），不知道里面有哪些任务，不动配置")
    zh = _Locale(Path(maaend_dir) if maaend_dir else None)
    if not zh.table:
        return _prune_refused("读不到 MaaEnd 的语言包，不动配置")
    doc = json.loads(f.read_text(encoding="utf-8"))
    removed: list[str] = []
    named: list[str] = []          # 「name（开着/关着）」 for the warning
    for inst in doc.get("instances") or []:
        keep = []
        for t in inst.get("tasks") or []:
            name = str(t.get("taskName") or "")
            dead = (name and not name.startswith("__") and name not in tasks
                    and f"task.{name}.label" not in zh.table)
            if dead and (seen := [x.name for x, text in unread if f'"{name}"' in (text or "")]):
                return _prune_refused(f"MaaEnd 的「{name}」不在读得出的任务定义里，但读不了的定义文件"
                                      f"（{'、'.join(seen)}）里提到它；定义看不全，就不动配置")
            if dead:
                removed.append(name)
                named.append(f"{name}（{'开着' if t.get('enabled') else '关着'}）")
            else:
                keep.append(t)
        inst["tasks"] = keep
    if not removed:
        return [], ""
    bak = f.with_name(f.name + f".bak-orphans-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    bak.write_bytes(f.read_bytes())
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    back = json.loads(f.read_text(encoding="utf-8"))
    left = [t.get("taskName") for inst in back.get("instances") or [] for t in inst.get("tasks") or []]
    if any(n in left for n in removed):
        return _prune_refused(f"删 MaaEnd 的死条目时写进去之后读出来和写的不一样，{bak.name} 是原样")
    msg = f"MaaEnd 这一版已经没有这些任务了，已从配置里删掉：{'、'.join(named)}（原文件备份为 {bak.name}）"
    # Every removal reaches the group under its own title (errwatch pushes WARNINGs).
    log.warning("%s", msg, extra=errwatch.alarm(texts.MAAEND_PRUNED, msg))
    return removed, (f"MaaEnd 这一版已经没有这些任务，配置里的死条目已清掉：{'、'.join(removed)}"
                     f"（原文件备份为 {bak.name}）")


def _prune_refused(note: str) -> tuple[list[str], str]:
    msg = f"MaaEnd 配置里失效的任务没有删：{note}"
    log.warning("%s", msg, extra=errwatch.alarm(texts.MAAEND_PRUNED_REFUSED, msg))
    return [], note


# ── Option format changes between MaaEnd versions ───────────────────────────
# v2.28.0-beta.5 split 自动采集's one route list into a per-region switch plus
# rare/common checkboxes, and made 基质刷取's location a sub-option of a new
# AutoEssenceMenu. MaaEnd discards a saved value whose option no longer exists and
# runs on defaults, and AUTO-MAS copies the master over before every run, so old
# keys in the master are rewritten here. Each entry: old key -> how to rewrite it.
# Only observed changes are translated; any other dead key is removed and named
# in the note.
_COLLECT_SPLIT = {
    "AutoCollectRoutes": ("AutoCollectValleyIVRareRoutes", "AutoCollectWulingRareRoutes"),
    "AutoCollectCommonRoutes": ("AutoCollectValleyIVCommonRoutes", "AutoCollectWulingCommonRoutes"),
}


def _cases(opts: dict, name: str) -> list[str]:
    return [c.get("name") for c in (opts.get(name) or {}).get("cases") or [] if c.get("name")]


def _checkbox_to_switch(task: str, key: str, ov: dict, opts: dict, zh) -> "str | None":
    """Carry a checkbox of items over to the switch + `<key>Items` that replaced it.

    MaaEnd v2.31/v2.32 turned each 自动囤货 buy list (e.g.
    AutoStockBuyDailyGoodsValleyIV) from a checkbox of items into a switch whose
    on case opens `<key>Items`, a checkbox of the same item names. MaaEnd resets
    a saved value whose type changed to the default (「选项 "…" 的类型已从
    "checkbox" 变更为 "switch"，已重置为默认值」). The picks go to `<key>Items` unchanged; the switch is on when
    anything was picked and off when nothing was (an empty list bought nothing).
    Only that exact shape is translated, and only when every picked item is a
    choice of the new list - otherwise the value is left for the check to report.
    Returns the change line (named by MaaEnd's own Chinese labels: the option
    that opens it, then its own), or None when nothing was done.
    """
    cur = ov.get(key) or {}
    spec = opts.get(key) or {}
    if cur.get("type") != "checkbox" or spec.get("type") != "switch":
        return None
    items = key + "Items"
    on = next((c for c in spec.get("cases") or [] if _switch_on(c.get("name"))), None)
    if (not on or items not in (on.get("option") or [])
            or (opts.get(items) or {}).get("type") != "checkbox"):
        return None
    picked = [str(x) for x in cur.get("caseNames") or []]
    if any(x not in _cases(opts, items) for x in picked):
        return None
    ov[key] = {"type": "switch", "value": bool(picked)}
    ov[items] = {"type": "checkbox", "caseNames": picked}
    parent = next((o for o in opts.values()
                   if any(key in (c.get("option") or []) for c in o.get("cases") or [])), {})
    what = " · ".join(x for x in (zh(parent.get("label")), zh(spec.get("label"))) if x)
    return (f"{what or key}：改成了开关，设为{'开' if picked else '关'}"
            + (f"，原来勾的 {len(picked)} 样照旧勾上" if picked else "（原来一样都没勾）"))


def _stale_entry(entry: dict, opts: dict, tasks: dict) -> bool:
    """A closed-tab record whose task (definition read) carries a key MaaEnd no longer has."""
    return any(str(t.get("taskName") or "") in tasks
               and any(k not in opts for k in (t.get("optionValues") or {}))
               for t in entry.get("tasks") or [])


def _prune_recently_closed(doc: dict, opts: dict, tasks: dict) -> int:
    """Drop stale records from MXU's recentlyClosed list; returns how many went.

    MXU keeps the tabs the user closed under recentlyClosed, option values and
    all, and re-validates them on every load, logging 「已不存在」 for each dead
    key in them.
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
    zh = _Locale(Path(maaend_dir))
    doc = json.loads(f.read_text(encoding="utf-8"))
    changes: list[str] = []
    switched: list[str] = []
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
            for k in list(ov):
                if line := _checkbox_to_switch(name, k, ov, opts, zh):
                    changes.append(line)
                    switched.append(k)
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
            if any((ov.get(k) or {}).get("type") == "checkbox" for k in switched):
                return [], f"写进去之后再读，改成开关的项还是多选，{bak.name} 是原样"
    if any(_stale_entry(e, opts, tasks) for e in back.get("recentlyClosed") or []):
        return [], f"写进去之后再读，「最近关闭」里旧写法的项还在，{bak.name} 是原样"
    return changes, ("MaaEnd 换了版本后旧设置的写法它不认了，母本已按原意改写：\n"
                     + "\n".join(f"· {c}" for c in changes)
                     + f"\n（原文件备份为 {bak.name}）")
