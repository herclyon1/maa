"""What is scheduled to run next.

The daily report has to end with tomorrow's plan. Knowing last night went fine
is only half the answer - the operator also needs to know what will be farmed
tomorrow, while there is still time to change it.

Everything here is read straight from AUTO-MAS's own config, so the report can
never disagree with what the machine will actually do.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import SERVER_TZ, USER_TZ

log = logging.getLogger("ark.plan")

# AUTO-MAS stores per-user settings under an opaque uid; walk to them by shape
# rather than by hard-coded id, so a new user or a reinstall does not break it.
_SANITY_USE = {
    "OperatorProgression": "干员经验",
    "WeaponProgression": "武器经验",
    "CrisisDrills": "危机演习",
    "Essence": "精华",
}


def _tokyo(hhmm: str) -> str:
    """'09:00' on the server clock -> '10:00' in Tokyo."""
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return ""
    shift = int((USER_TZ.utcoffset(None) - SERVER_TZ.utcoffset(None)).total_seconds() // 3600)
    return f"{(hh + shift) % 24:02d}:{mm:02d}"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("读取 %s 失败: %s", path.name, exc)
        return {}


def _scripts(cfg_dir: Path) -> dict[str, dict]:
    """{script_uid: {name, stage, medicine, sanity_use}}"""
    data = _load(cfg_dir / "ScriptConfig.json")
    out: dict[str, dict] = {}
    for inst in data.get("instances", []):
        uid = inst.get("uid")
        node = data.get(uid) or {}
        entry = {"name": (node.get("Info") or {}).get("Name") or "?"}
        for user in ((node.get("SubConfigsInfo") or {}).get("UserData") or {}).values():
            if not isinstance(user, dict):
                continue
            info, task = user.get("Info") or {}, user.get("Task") or {}
            if info.get("Stage"):
                entry["stage"] = info["Stage"]
                entry["stage_mode"] = info.get("StageMode", "")
                entry["medicine"] = info.get("MedicineNumb")
            if task.get("SanityTaskType"):
                entry["sanity_use"] = _SANITY_USE.get(
                    task["SanityTaskType"], task["SanityTaskType"]
                )
        out[uid] = entry
    return out


def _queues(cfg_dir: Path) -> list[dict]:
    data = _load(cfg_dir / "QueueConfig.json")
    out = []
    for inst in data.get("instances", []):
        node = data.get(inst.get("uid")) or {}
        info = node.get("Info") or {}
        sub = node.get("SubConfigsInfo") or {}
        times = []
        for tid, t in (sub.get("TimeSet") or {}).items():
            if tid == "instances" or not isinstance(t, dict):
                continue
            ti = t.get("Info") or {}
            if ti.get("Enabled") and ti.get("Time"):
                times.append(ti["Time"])
        items = []
        for qid, q in (sub.get("QueueItem") or {}).items():
            if qid == "instances" or not isinstance(q, dict):
                continue
            sid = (q.get("Info") or {}).get("ScriptId")
            if sid:
                items.append(sid)
        if info.get("TimeEnabled") and times:
            out.append({
                "name": info.get("Name") or "?",
                "times": sorted(times),
                "after": info.get("AfterAccomplish"),
                "items": items,
            })
    out.sort(key=lambda q: q["times"][0])
    return out


def next_plan(automas_dir: Path | None) -> str:
    """Human-readable summary of what will run next. '' if it cannot be read."""
    if not automas_dir:
        return ""
    cfg_dir = Path(automas_dir) / "config"
    if not cfg_dir.is_dir():
        log.warning("找不到 AUTO-MAS 配置目录: %s", cfg_dir)
        return ""

    scripts, queues = _scripts(cfg_dir), _queues(cfg_dir)
    if not queues:
        return ""

    lines = ["📅 明日安排"]
    for q in queues:
        for t in q["times"]:
            lines.append(f"{t}（东京 {_tokyo(t)}）")
        for uid in q["items"]:
            s = scripts.get(uid) or {}
            bits = []
            if s.get("stage"):
                mode = "固定" if s.get("stage_mode") == "Fixed" else s.get("stage_mode", "")
                bits.append(f"理智 {s['stage']}" + (f"（{mode}）" if mode else ""))
            if (med := s.get("medicine")) is not None:
                # AUTO-MAS stores "use as many as you have" as a sentinel, not
                # as a real count. Printing 999 makes a reader stop and wonder.
                bits.append("理智药不限" if int(med) >= 999 else f"理智药 {med} 个")
            if s.get("sanity_use"):
                bits.append(f"理智用于 {s['sanity_use']}")
            label = s.get("name", "?")
            lines.append(f"· {label}" + ("　" + " · ".join(bits) if bits else ""))
        if q["after"] == "Shutdown":
            lines.append("· 跑完自动关机")
        lines.append("")
    return "\n".join(lines)
