"""OK-WW's own config files in AUTO-MAS's master copy: read for the phone page, write one item.

Files are the JSON files next to DailyTask.json in the directory
config.master_config_dir finds. OKWW_SHOWN lists the items the phone page
shows and may change; OKWW_READONLY the items it shows but may not change.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ark_relay.core.config import atomic_write_text, master_config_dir

log = logging.getLogger("ark.mastercfg")

# read_okww runs on every phone-state publish and a WARNING is a group message:
# a config file that exists but cannot be read is said once per condition (file
# -> the error last said), forgotten once it reads again.
_last_error: dict[str, str] = {}


OKWW_SHOWN: dict[str, tuple[str, ...]] = {
    "DailyTask.json": (
        "Which to Farm",
        "Material Selection",
        "Which Forgery Challenge to Farm",
        "Which Tacet Suppression to Farm",
    ),
}


# Shown on the phone page but not editable: the Nightmare Nest locations are a
# standing order from the user ("farm 落渊南丘 only").
OKWW_READONLY: dict[str, tuple[str, ...]] = {
    "NightmareNestTask.json": ("Only Farm These Nests",),
}


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


def _okww_doc(f: Path) -> "dict | None":
    """One existing OK-WW config file, or None (said once) when it cannot be read:
    its rows would otherwise just vanish from the phone page."""
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        why = f"{type(exc).__name__}: {exc}"
        if _last_error.get(str(f)) != why:
            log.warning("鸣潮母本 %s 读不到（%s），手机页上它那几项这次不显示", f.name, why)
            _last_error[str(f)] = why
        return None
    _last_error.pop(str(f), None)
    return doc


def read_okww(automas_dir, okww_dir) -> dict:
    """Values, candidates and Chinese names. Every Chinese name comes from the
    ok.po that ships with OK-WW (`Forgery Challenge` is officially 「凝素领域」,
    `Tacet Suppression` 「无音区」).
    """
    out: dict = {"values": {}, "options": {}, "labels": {}, "readonly": {},
                 "subs": OKWW_SUBS}
    try:
        from ark_relay.core import plan  # noqa: PLC0415
        zh = plan._okww_zh(Path(okww_dir) if okww_dir else None)
    except Exception:  # noqa: BLE001
        zh = {}
    cases = _okww_cases(okww_dir)
    for name, wanted in OKWW_SHOWN.items():
        f = okww_file(automas_dir, name)
        if not f or not f.is_file():
            continue
        if (doc := _okww_doc(f)) is None:
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
        if (doc := _okww_doc(f)) is None:
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
