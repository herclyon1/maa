"""Turning a whole queue, or one script inside it, on and off.

AUTO-MAS's QueueConfig has no per-item switch - a QueueItem is just a ScriptId,
so "stop running MAA" cannot be expressed by flipping a flag. There are only two
levers: a queue's own `Info.TimeEnabled`, and which items the queue contains.

Both are handled here rather than by hand-editing JSON over SSH, because the
machine is powered off whenever the decision gets made. Removed items are
written to the backup alongside the file, so putting a script back is reading
one file rather than remembering a UUID.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.queues")


def _path(automas_dir: Path) -> Path:
    return Path(automas_dir) / "config" / "QueueConfig.json"


def _script_ids(automas_dir: Path) -> dict[str, str]:
    """{"MAA": uid, "MaaEnd": uid} - classified by install path, as elsewhere."""
    from . import plan  # noqa: PLC0415 - avoids an import cycle
    out: dict[str, str] = {}
    cfg_dir = Path(automas_dir) / "config"
    if not cfg_dir.is_dir():
        return out
    for uid, s in plan._scripts(cfg_dir).items():  # noqa: SLF001
        if s.get("kind"):
            out[s["kind"]] = uid
    return out


def describe(automas_dir: Path | None) -> list[str]:
    """One line per queue, for the report."""
    from . import plan  # noqa: PLC0415
    if not automas_dir:
        return []
    ids = {v: k for k, v in _script_ids(Path(automas_dir)).items()}
    out = []
    for q in plan.schedule(automas_dir):
        kinds = [ids.get(u, "?") for u in q.get("items", [])]
        out.append(f"{q['name']} {'/'.join(q.get('times') or [])}：{'、'.join(kinds) or '(空)'}")
    return out


def apply(automas_dir: Path, name: str, enabled: bool | None = None,
          scripts: list[str] | None = None) -> tuple[bool, str]:
    """Enable/disable a queue and/or set which scripts it runs."""
    path = _path(automas_dir)
    try:
        original = path.read_text(encoding="utf-8")
        data = json.loads(original)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"读不了 QueueConfig: {exc}"

    target = None
    names = []
    for inst in data.get("instances", []):
        node = data.get(inst.get("uid")) or {}
        qn = (node.get("Info") or {}).get("Name")
        names.append(qn)
        if qn == name:
            target = node
    if target is None:
        return False, f"没有叫「{name}」的队列（现有：{'、'.join(n for n in names if n)}）"

    changes: list[str] = []
    removed: list[dict] = []

    if enabled is not None:
        # The value arrives from a JSON file a person hand-edits. A string
        # "false" is truthy, so it would switch the queue ON while the push
        # reported it OFF; this writer has no structural diff to catch that.
        if not isinstance(enabled, bool):
            return False, f"enabled 必须是 true/false，收到 {enabled!r}"
        info = target.setdefault("Info", {})
        if bool(info.get("TimeEnabled")) != enabled:
            info["TimeEnabled"] = enabled
            changes.append(f"定时{'开启' if enabled else '关闭'}")

    if scripts is not None:
        ids = _script_ids(Path(automas_dir))
        unknown = [s for s in scripts if s not in ids]
        if unknown:
            return False, (f"认不出脚本 {'、'.join(unknown)}"
                           f"（可用：{'、'.join(ids)}）")
        want = {ids[s] for s in scripts}
        sub = (target.get("SubConfigsInfo") or {}).get("QueueItem") or {}
        # This code can only REMOVE items - there is no insertion path (a
        # QueueItem needs a fresh uid and AUTO-MAS-shaped structure). Asking to
        # restore a script that is not in the queue used to fall through to
        # "已经是这个状态" - a ✅ for a machine that keeps farming without it.
        have = {(item.get("Info") or {}).get("ScriptId")
                for uid, item in sub.items()
                if uid != "instances" and isinstance(item, dict)}
        if missing := [s for s in scripts if ids[s] not in have]:
            return False, (f"加回脚本尚未实现：{'、'.join(missing)} 不在队列里，"
                           "只能移出不能加回。removed-*.json 里有原条目，需人工加回")
        keep_uids, dropped = [], []
        for uid, item in sub.items():
            if uid == "instances" or not isinstance(item, dict):
                continue
            sid = (item.get("Info") or {}).get("ScriptId")
            (keep_uids if sid in want else dropped).append(uid)
            if sid not in want:
                removed.append({"uid": uid, "item": item})
        if dropped:
            for uid in dropped:
                sub.pop(uid, None)
            sub["instances"] = [i for i in (sub.get("instances") or [])
                                if i.get("uid") not in dropped]
            back = {v: k for k, v in ids.items()}
            gone = [back.get((r["item"].get("Info") or {}).get("ScriptId"), "?")
                    for r in removed]
            changes.append(f"移出 {'、'.join(gone)}")

    if not changes:
        return True, "已经是这个状态，无需改动"

    stamp = datetime.now(tz=SERVER_TZ)
    backup = path.with_suffix(f".bak-{stamp:%Y%m%d-%H%M%S}.json")
    shutil.copy2(path, backup)
    if removed:
        # Put the removed entries where restoring them is reading a file, not
        # remembering a UUID.
        (path.parent / f"removed-{stamp:%Y%m%d-%H%M%S}.json").write_text(
            json.dumps({"queue": name, "items": removed}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    try:
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as exc:
        shutil.copy2(backup, path)
        return False, f"写入失败，已回滚: {exc}"
    return True, f"队列「{name}」：{'；'.join(changes)}（备份 {backup.name}）"
