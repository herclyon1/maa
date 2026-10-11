"""Config paths and fields: flatten / dig into / build nested config, and say a field change in plain words.

Pure helpers shared by the command gates in commands.py; no I/O, no AUTO-MAS calls.
"""
from __future__ import annotations

from typing import Any


# Config field -> plain words. The push is read by a person on a phone, and
# something like `/59da8762-8fa7-.../Game/WaitTime` means nothing at all to
# the person reading it.
_FIELD_LABELS = {
    "Stage": "刷取关卡",
    "MedicineNumb": "理智药上限",
    "WaitTime": "终末地启动后等待",
    "Annihilation": "剿灭",
    "TimeEnabled": "队列定时",
    "Enabled": "启用",
    "RunTimesLimit": "失败重试上限",
    "StageMode": "选关模式",
}
_FIELD_UNITS = {"WaitTime": " 秒", "MedicineNumb": " 个"}


def _humanize(path: str, before: Any, after: Any) -> str:
    """'/x/Game/WaitTime', 60, 120 -> '终末地启动后等待：60 秒 → 120 秒'"""
    field = path.rsplit("/", 1)[-1]
    label = _FIELD_LABELS.get(field, field)
    unit = _FIELD_UNITS.get(field, "")
    fmt = lambda v: f"{v}{unit}" if not isinstance(v, bool) else ("开" if v else "关")  # noqa: E731
    return f"{label}：{fmt(before)} → {fmt(after)}"


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


def _dig(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def _nest(path: str, value) -> dict:
    out: dict = {}
    cur = out
    parts = path.split(".")
    for part in parts[:-1]:
        cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value
    return out
