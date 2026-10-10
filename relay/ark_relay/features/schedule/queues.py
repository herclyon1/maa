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

from ark_relay.core import names
import logging
import shutil
from datetime import datetime
from pathlib import Path

from ark_relay.core.config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.queues")


def _path(automas_dir: Path) -> Path:
    return Path(automas_dir) / "config" / "QueueConfig.json"


def _script_ids(automas_dir: Path) -> dict[str, str]:
    """{"MAA": uid, "MaaEnd": uid} - classified by install path, as elsewhere."""
    from ark_relay.core import plan  # noqa: PLC0415 - avoids an import cycle
    out: dict[str, str] = {}
    cfg_dir = Path(automas_dir) / "config"
    if not cfg_dir.is_dir():
        return out
    for uid, s in plan._scripts(cfg_dir).items():
        if s.get("kind"):
            out[s["kind"]] = uid
    return out


def _apply_enabled(target: dict, enabled: bool, changes: list[str]) -> str | None:
    """Flip the queue's own schedule switch, recording edits into changes.

    Returns an error string, or None when there was no error. It is a separate
    step because it has to reject non-boolean values before touching the config:
    this step decides whether the queue runs at all tomorrow, and getting it
    wrong leaves the whole queue in the wrong state overnight - the write that
    follows has no structural diff that could catch it.
    """
    # The value arrives from a JSON file a person hand-edits. A string
    # "false" is truthy, so it would switch the queue ON while the push
    # reported it OFF; this writer has no structural diff to catch that.
    if not isinstance(enabled, bool):
        return f"enabled 必须是 true/false，收到 {enabled!r}"
    info = target.setdefault("Info", {})
    if bool(info.get("TimeEnabled")) != enabled:
        info["TimeEnabled"] = enabled
        changes.append(f"定时{'开启' if enabled else '关闭'}")
    return None


def _apply_scripts(automas_dir: Path, target: dict, scripts: list[str],
                   changes: list[str], removed: list[dict]) -> str | None:
    """Trim the queue down to only the scripts listed, collecting cut entries into removed.

    It is a separate step because this is the only place in this module that
    **deletes config**: the three checks (is the script name recognised, is the
    script in the queue at all, which of the rest should stay) have to be read
    together to explain why items can only be moved out and not added back.
    Returns an error string, or None when there was no error.
    """
    ids = _script_ids(Path(automas_dir))
    unknown = [s for s in scripts if s not in ids]
    if unknown:
        return (f"认不出脚本 {'、'.join(unknown)}"
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
        return (f"加回脚本尚未实现：{'、'.join(missing)} 不在队列里，"
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
    return None


def _enabled_via_backend(name: str, enabled: bool) -> tuple[bool, str] | None:
    """Flip the switch through the running AUTO-MAS backend and read it back.

    None means the backend refused the connection (annihilation._backend_unreachable),
    so the file is safe to edit: it is read when AUTO-MAS starts. A timeout or an
    error from a backend that is there is a failure, never None. While the backend runs, a file edit is silently
    lost: on 2026-09-30 a skip wrote TimeEnabled=false at 08:51:34, AUTO-MAS
    (timer armed since 08:48:59, no script running, so the
    scripts_running() guard let the write through) never re-read the file,
    started the morning queue at 09:00:00 and wrote its in-memory copy back
    over the edit, while the log said the queue was disabled. Success is
    reported only after /api/queue/get returns the new value.
    """
    from ark_relay.features.weekly.annihilation import _backend_unreachable  # noqa: PLC0415 - avoids an import cycle
    from ark_relay.features.phone.commands import _mas  # noqa: PLC0415 - avoids an import cycle
    word = "开启" if enabled else "关闭"
    try:
        have = _mas("/api/queue/get", timeout=5)["data"]
        if not isinstance(have, dict):
            raise TypeError(f"队列列表不是字典：{type(have).__name__}")
    except Exception as exc:  # noqa: BLE001
        if _backend_unreachable(exc):
            return None
        # Something answered, or accepted the connection and hung: a file edit now
        # is overwritten from AUTO-MAS's memory (the 2026-09-30 failure above).
        return False, (f"队列「{name}」定时{word}没改：调度程序没应答"
                       f"（{type(exc).__name__}: {exc}）；它开着时改文件，会被它用自己记着的那份盖回去")
    qid = next((k for k, q in have.items()
                if (q.get("Info") or {}).get("Name") == name), None)
    if qid is None:
        listed = "、".join(str((q.get("Info") or {}).get("Name") or "") for q in have.values())
        return False, f"没有叫「{name}」的队列（现有：{listed}）"
    if bool((have[qid].get("Info") or {}).get("TimeEnabled")) == enabled:
        return True, "已经是这个状态，无需改动"
    try:
        _mas("/api/queue/update", {"queueId": qid, "data": {"Info": {"TimeEnabled": enabled}}})
        back = (_mas("/api/queue/get")["data"].get(qid) or {}).get("Info") or {}
    except Exception as exc:  # noqa: BLE001
        return False, f"队列「{name}」定时{word}失败：调度程序报错（{exc}）"
    if back.get("TimeEnabled") is not enabled:
        return False, (f"队列「{name}」定时{word}没生效：调度程序里它仍是"
                       f"{'开启' if back.get('TimeEnabled') else '关闭'}")
    log.info("queue %s TimeEnabled=%s via backend, read back", name, enabled)
    return True, f"队列「{name}」：定时{word}（调度程序已确认）"


def apply(automas_dir: Path, name: str, enabled: bool | None = None,
          scripts: list[str] | None = None) -> tuple[bool, str]:
    """Enable/disable a queue and/or set which scripts it runs."""
    name = names.canonical(name)
    if enabled is not None and scripts is None:
        if not isinstance(enabled, bool):
            return False, f"enabled 必须是 true/false，收到 {enabled!r}"
        if (via := _enabled_via_backend(name, enabled)) is not None:
            return via
    path = _path(automas_dir)
    try:
        original = path.read_text(encoding="utf-8")
        data = json.loads(original)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"读不了 QueueConfig: {exc}"

    target = None
    # This must not be called `names`: that is the module name, and
    # names.canonical() at the top of this function still needs it.
    # From 2026-09-02 to 09-06 it was called `names` here, so Python treated it
    # as a local of this function and the very first line, names.canonical(),
    # raised UnboundLocalError - skip-queue and the queue switch in the todo
    # list crashed on every single call for four days. pyflakes reports this in
    # one line (F823), and that check is now part of lint.
    have = []
    for inst in data.get("instances", []):
        node = data.get(inst.get("uid")) or {}
        qn = (node.get("Info") or {}).get("Name")
        have.append(qn)
        if qn == name:
            target = node
    if target is None:
        return False, f"没有叫「{name}」的队列（现有：{'、'.join(n for n in have if n)}）"

    changes: list[str] = []
    removed: list[dict] = []

    if enabled is not None:
        if err := _apply_enabled(target, enabled, changes):
            return False, err

    if scripts is not None:
        if err := _apply_scripts(automas_dir, target, scripts, changes, removed):
            return False, err

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
