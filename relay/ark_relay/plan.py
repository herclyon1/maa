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
from datetime import timedelta
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


def _script_kind(path: str) -> str:
    """Classify a script by its install path: "MAA" | "MaaEnd" | "".

    The display name is whatever the operator typed ("maa明日方舟", "新 MaaEnd
    脚本"), so it cannot be matched on. The install path is set by AUTO-MAS
    itself and matches the names the collector puts in the ledger, which is
    what lets the two be compared.
    """
    p = (path or "").lower()
    if "maaend" in p:
        return "MaaEnd"
    if "maa" in p:
        return "MAA"
    return ""


def _scripts(cfg_dir: Path) -> dict[str, dict]:
    """{script_uid: {name, kind, stage, medicine, sanity_use}}"""
    data = _load(cfg_dir / "ScriptConfig.json")
    out: dict[str, dict] = {}
    for inst in data.get("instances", []):
        uid = inst.get("uid")
        node = data.get(uid) or {}
        info_node = node.get("Info") or {}
        entry = {
            "name": info_node.get("Name") or "?",
            "kind": _script_kind(info_node.get("Path") or ""),
            "path": info_node.get("Path") or "",
        }
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


def schedule(automas_dir: Path | None) -> list[dict]:
    """[{name, times, items}] straight from AUTO-MAS's own queue config.

    Read rather than hard-coded, so changing a queue time in AUTO-MAS cannot
    leave the relay watching for a run that no longer exists.
    """
    if not automas_dir:
        return []
    cfg_dir = Path(automas_dir) / "config"
    return _queues(cfg_dir) if cfg_dir.is_dir() else []


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
            if s.get("kind") == "MaaEnd":
                # AUTO-MAS's SanityTaskType is only the tab; on its own it reads
                # as the answer and is not one - "干员养成" does not say whether
                # that means 经验 or 进阶, and the reward set decides which item
                # actually drops. Report the resolved chain instead.
                from . import sanity_plan  # noqa: PLC0415 - avoids a cycle
                if label := sanity_plan.read(automas_dir).get("label"):
                    bits.append(f"理智用于 {label}")
            elif s.get("sanity_use"):
                bits.append(f"理智用于 {s['sanity_use']}")
            label = s.get("name", "?")
            lines.append(f"· {label}" + ("　" + " · ".join(bits) if bits else ""))
        if q["after"] == "Shutdown":
            lines.append("· 跑完自动关机")
        lines.append("")
    return "\n".join(lines)


def recent_due_queues(automas_dir: Path | None, now, window_minutes: int = 120) -> list[dict]:
    """Queues whose time came up in the last `window_minutes`, with their scripts.

    [{"name": ..., "due": datetime, "kinds": ["MAA", "MaaEnd"]}]

    Two bounds matter, and getting either wrong breaks the machine's day:

    A queue that just became due may still be working through its items, and
    between two of them no game process exists at all - MAA has exited, the
    next game is still launching. Powering off in that window costs a run; it
    cost the 终月地 half of 2026-08-16.

    But the wait cannot be open-ended either. If a script simply never runs -
    it crashed, the game would not start - waiting for it forever would keep
    the machine powered on all day and every day after. Past the window the
    queue is written off and the machine may sleep.
    """
    if not automas_dir:
        return []
    cfg_dir = Path(automas_dir) / "config"
    if not cfg_dir.is_dir():
        return []
    scripts = _scripts(cfg_dir)
    out: list[dict] = []
    for q in _queues(cfg_dir):
        for hhmm in q.get("times", []):
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            # Yesterday's occurrence too: a 21:30 queue still inside its
            # window at 00:10 used to vanish from this list the moment the
            # date rolled, dropping the "don't power off mid-queue" guard in
            # exactly the inter-script gap it exists for.
            due = None
            for day_shift in (0, -1):
                cand = (now + timedelta(days=day_shift)).replace(
                    hour=hh, minute=mm, second=0, microsecond=0)
                if cand <= now < cand + timedelta(minutes=window_minutes):
                    due = cand
                    break
            if due is None:
                continue
            kinds = []
            for uid in q.get("items", []):
                kind = (scripts.get(uid) or {}).get("kind")
                if kind and kind not in kinds:
                    kinds.append(kind)
            if kinds:
                out.append({"name": q.get("name", "?"), "due": due, "kinds": kinds})
    return out


def activity_countdown(automas_dir: Path | None, now=None,
                       cache_path: Path | None = None) -> str:
    """One line per current event: name, remaining time, end on both clocks.

    Read from MAA's own activity cache (cache/gui/StageActivityV2.json,
    maintained by the MAA resource repo and OTA-updated), so the relay never
    holds its own copy of event dates. Empty string when anything is missing -
    a report without a countdown beats no report.

    Requested 2026-08-20: the operator farms event stages on a fixed-stage
    config; an event ending overnight silently turns the next morning's run
    into guaranteed failures. The countdown makes that visible in every
    report, and an expired event is flagged instead of dropped.
    """
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    try:
        if cache_path is None:
            maa = script_dir(automas_dir, "MAA")
            if not maa:
                return ""
            cache_path = Path(maa) / "cache" / "gui" / "StageActivityV2.json"
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return ""
    now = now or datetime.now(tz=SERVER_TZ)
    lines: list[str] = []
    for node in ((data.get("Official") or {}).get("sideStoryStage") or {}).values():
        act = node.get("Activity") if isinstance(node, dict) else None
        if not isinstance(act, dict):
            continue
        name = str(act.get("StageName") or "").strip() or "当期活动"
        raw = str(act.get("UtcExpireTime") or "")
        try:
            tz_hours = int(act.get("TimeZone", 8))
            end = datetime.strptime(raw, "%Y/%m/%d %H:%M:%S").replace(
                tzinfo=timezone(timedelta(hours=tz_hours)))
        except (ValueError, TypeError):
            continue
        left = end - now
        end_txt = (f"{end.astimezone(SERVER_TZ):%m-%d %H:%M} 结束"
                   f"（东京 {end.astimezone(USER_TZ):%H:%M}）")
        if left.total_seconds() <= 0:
            # Only a *recently* ended event deserves the warning - the cache
            # keeps whole past events around ("红丝绒" months gone), and a
            # permanent stale alarm teaches the reader to ignore alarms.
            if left >= -timedelta(days=3):
                lines.append(f"⚠️ 活动「{name}」已结束——主关卡若还是活动关，"
                             "下一轮必失败，记得换关")
            continue
        days, rem = divmod(int(left.total_seconds()), 86400)
        hours, rem = divmod(rem, 3600)
        mins = rem // 60
        span = (f"{days} 天 {hours} 时" if days else
                (f"{hours} 时 {mins} 分" if hours else f"{mins} 分"))
        head = "⚠️ " if left <= timedelta(hours=36) else ""
        lines.append(f"{head}🗓️ 活动「{name}」剩 {span}，{end_txt}")
    return "\n".join(lines)


def script_dir(automas_dir: Path | None, kind: str) -> Path | None:
    """Where AUTO-MAS says a given script is installed. None if unknown.

    Saves having to configure the MaaEnd path a second time: AUTO-MAS already
    knows it, and a path configured twice is a path that will disagree with
    itself the day one of them moves.
    """
    if not automas_dir:
        return None
    cfg_dir = Path(automas_dir) / "config"
    if not cfg_dir.is_dir():
        return None
    for s in _scripts(cfg_dir).values():
        if s.get("kind") == kind and s.get("path"):
            return Path(s["path"])
    return None
