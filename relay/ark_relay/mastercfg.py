"""脚本自己那份配置（母本）的读与写。

**为什么存在**（2026-09-03 夜查证）：AUTO-MAS 的「快速配置」关掉之后，
MAS 用户配置里那些字段就**不再下发**给脚本——

* `app/task/Okww/AutoProxy.py:320` `if not ...get("Info","IfQuickConfig"): return`，
  于是 `Which to Farm` / `Material Selection` 那一批根本没写进 OK-WW；
* `app/task/MaaEnd/AutoProxy.py:537` 之后，理智任务那套只在开着时才从 MAS 读。

两个脚本现在都是 `IfQuickConfig=False`。手机页面在这天之前改的正是那些字段：
按下去有回执、值也真写进了 MAS，可脚本跑的时候看的是母本，**等于没改**。
真正长期生效的地方只有母本，见 `config.master_config_dir` 的说明。

（明日方舟不一样：AUTO-MAS 里根本没有 MAA 的快速配置这回事，
`IfQuickConfig` 只定义在 MaaEnd 和 OK-WW 两个配置类上。MAA 的
`Info.Mode` 简洁/详细只决定拷哪份底子当基础，关卡、理智药、连战、剿灭
每次派发都会被覆盖写进 gui.new.json——`app/task/Maa/AutoProxy.py:796-845`。
所以 MAA 那几项走 MAS 是对的，不归这个模块管。）

**中文名不自己编**：MaaEnd 每个选项和每个取值都在自己的任务定义里带一个
`"$xxx.yyy"` 形式的语言包键，照着解析就是官方译名。OK-WW 同理，用它的
`ok.po`。上游改了名字这边跟着变。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .config import atomic_write_text, master_config_dir

log = logging.getLogger("ark.mastercfg")

# 手机上真正会出现的那些项。**不是能改的全给**：整份选项塞进一条 ntfy
# 消息会超上限被截断，页面 JSON.parse 直接失败（2026-08-31 栽过）。
# 这里只留每天真会动的。
MAAEND_SHOWN: dict[str, tuple[str, ...]] = {
    "AutoEssence": (
        "@enabled",
        "AutoEssenceDoOverride",        # 使用刻写券
        "AutoEssenceObtainMode",        # 领取方式：不领取／单倍／双倍
        "AutoEssenceRepeatCount",       # 最大循环次数
        "AutoEssenceChooseLocation",    # 地区选择
        "EssenceFilterAfterBattle",     # 战后基质筛选
    ),
    "AutoUseSpMedication": ("@enabled",),
    "AutoCollect": (
        "@enabled",
        # 只给一个开关，手机上看不出它到底会去采哪几条、哪天采。
        # 2026-09-04 用户：「自动采集任务，你应该显示采集路线。」
        # 那天它 0.16 秒就「完成」，正是因为计划表只勾了周一和周四，
        # 页面上却一个字都看不出来。
        "AutoCollectRoutes",            # 采哪几条路线
        "AutoCollectSchedule",          # 哪几天采
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

# 只读展示，不给改：残象聚落点位有死命令「只刷落渊南丘」，
# 我自己已经改回「刷全部」两次。放出来看得见，但按不动。
OKWW_READONLY: dict[str, tuple[str, ...]] = {
    "NightmareNestTask.json": ("Only Farm These Nests",),
}

_COMMENT = re.compile(r"^\s*//.*$", re.M)


def _jsonc(path: Path) -> dict:
    """MaaEnd 的任务定义是带 // 注释的 JSON。"""
    return json.loads(_COMMENT.sub("", path.read_text(encoding="utf-8")))


class _Locale:
    """`$key` → 中文。查不到就把 `$` 去掉原样返回，绝不编。"""

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


def read_maaend(automas_dir, maaend_dir) -> dict:
    """`{"values": {"任务/选项": 值}, "options": {"任务/选项": [[中文, 取值]]},
    "labels": {"任务/选项": 中文名}}`。读不到就返回空，页面那段不显示。"""
    out: dict = {"values": {}, "options": {}, "labels": {}}
    f = maaend_master(automas_dir)
    if not f or not f.is_file():
        return out
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("母本 mxu-MaaEnd.json 读不出来", exc_info=True)
        return out
    zh = _Locale(Path(maaend_dir) if maaend_dir else None)
    for task_name, wanted in MAAEND_SHOWN.items():
        task = _maaend_task(doc, task_name)
        if task is None:
            continue
        try:
            spec = _jsonc(Path(maaend_dir) / "tasks" / f"{task_name}.json")
        except (OSError, ValueError, TypeError):
            spec = {}
        defs = spec.get("option") or {}
        # `task` 在真文件里是**数组**（一个文件可以声明多个任务），
        # 里面按 name 找。2026-09-04 我照着自造的样例写成 dict，上机就炸。
        decl = next((t for t in (spec.get("task") or [])
                     if isinstance(t, dict) and t.get("name") == task_name), {})
        out["labels"][f"{task_name}/@enabled"] = zh(
            decl.get("label") or f"$task.{task_name}.label")
        for opt in wanted:
            key = f"{task_name}/{opt}"
            if opt == "@enabled":
                out["values"][key] = bool(task.get("enabled"))
                continue
            cur = (task.get("optionValues") or {}).get(opt)
            if cur is None:
                continue
            d = defs.get(opt) or {}
            out["labels"][key] = zh(d.get("label")) or opt
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
    return out


def write_maaend(automas_dir, maaend_dir, path: str, value) -> tuple[bool, str]:
    """改母本里的一项。存在才写、写完回读，和 `commands._set_config` 一个规矩。"""
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
        cur = (task.get("optionValues") or {}).get(opt)
        if cur is None:
            return False, (f"{task_name} 里没有 {opt} 这一项，已拒绝"
                           "（不许凭空造字段——826 就是这么出的事）")
        kind = str(cur.get("type") or "")
        # 取值必须是这一项自己声明过的，不许乱填
        try:
            defs = _jsonc(Path(maaend_dir) / "tasks" / f"{task_name}.json").get("option") or {}
            allowed = {str(c.get("name")) for c in (defs.get(opt) or {}).get("cases") or []}
        except (OSError, ValueError, TypeError):
            allowed = set()
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


# ─────────────────────────────── OK-WW ───────────────────────────────

def okww_file(automas_dir, name: str) -> Path | None:
    d = master_config_dir(automas_dir, "DailyTask.json")
    return (d / name) if d else None


# 选了「刷什么」里的哪一项，下面才出现哪一项子设置。抄自 OK-WW 的 sub_configs。
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
    """下拉候选从 OK-WW **自己的源码**里读，不自己编。"""
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
    """值、候选、中文名。中文名全部来自 OK-WW 自带的 ok.po。

    2026-09-03 才发现原来页面上那两个序号的标签是我自己编的，而且编反了：
    `Forgery Challenge` 官方译作「凝素领域」，`Tacet Suppression` 是「无音区」。
    """
    out: dict = {"values": {}, "options": {}, "labels": {}, "readonly": {},
                 "subs": OKWW_SUBS}
    try:
        from . import plan  # noqa: PLC0415
        zh = plan._okww_zh(Path(okww_dir) if okww_dir else None)  # noqa: SLF001
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
