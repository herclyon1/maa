"""Turning a whole queue on and off, and skipping scripts inside it for today.

Two levers, both through AUTO-MAS: a queue's own `Info.TimeEnabled`, and each
queue item's `Schedule.Days` (the weekdays that item runs; AUTO-MAS skips an
item whose days leave out the day the queue task starts). "Run only these
scripts" leaves every item in the queue: an unlisted one loses today's weekday
(commands.skip_script_in_queue) and gets it back the next day, when
gameupdate.restore_skips(before_day=...) runs at boot. Since the 2026-10-11
hand-over (item 16) no item is deleted and nothing needs backing up for it.

The switch goes through the backend whenever it answers; the file is edited
only when the backend refused the connection (it re-reads the file at start).
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


def _scripts_via_backend(state_dir: Path | None, name: str, scripts: list[str]) -> tuple[bool, str]:
    """Run only `scripts` in queue `name` today: skip the rest, put back listed ones we skipped.

    Backend only: a Schedule.Days edit in the file is overwritten from AUTO-MAS's
    memory while it runs, and on a powered-off machine there is no "today" to
    skip. A listed script the relay did not skip keeps whatever days the user
    gave it. Each skip is recorded in updates.queue_skips with source "queue",
    so the boot-time restore puts it back on the next day and the game-update
    re-run (restore_skips(manual_too=False)) leaves it alone.
    """
    if state_dir is None:
        return False, f"队列「{name}」没改：找不到中继的状态目录，记不下明天要改回的跳过"
    from ark_relay.features.phone import commands  # noqa: PLC0415 - avoids an import cycle
    from ark_relay.features.gameupdate import gameupdate  # noqa: PLC0415 - avoids an import cycle
    try:
        qid = commands._queue_id(name)
        known = {str((sc.get("Info") or {}).get("Name") or ""): sid
                 for sid, sc in commands._mas("/api/scripts/get")["data"].items()}
        items = commands._mas("/api/queue/item/get", {"queueId": qid})
    except KeyError as exc:
        return False, str(exc.args[0] if exc.args else exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"队列「{name}」没改：调度程序没应答（{type(exc).__name__}: {exc}）"
    by_lower = {k.lower(): k for k in known}
    if unknown := [s for s in scripts if s.lower() not in by_lower]:
        return False, f"认不出脚本 {'、'.join(unknown)}（可用：{'、'.join(k for k in known if k)}）"
    want = {known[by_lower[s.lower()]] for s in scripts}
    back = {sid: n for n, sid in known.items()}
    in_queue = [((((items.get("data") or {}).get(i["uid"])) or {}).get("Info") or {}).get("ScriptId")
                for i in items.get("index") or []]
    changes: list[str] = []
    for rec in [r for r in gameupdate.skips(state_dir) if r.get("queueId") == qid and r.get("scriptId") in want]:
        if not commands.restore_script_in_queue(rec):
            return False, f"队列「{name}」：{rec.get('script')} 今天的跳过没撤掉（调度程序读回来没变）"
        gameupdate._drop_skip(state_dir, rec)
        changes.append(f"恢复 {rec.get('script')}")
    for sid in dict.fromkeys(s for s in in_queue if s and s not in want):
        try:
            rec = commands.skip_script_in_queue(name, back.get(sid, sid))
        except Exception as exc:  # noqa: BLE001
            return False, f"队列「{name}」：今天跳过 {back.get(sid, sid)} 失败（{exc}）"
        if rec:
            rec["source"] = "queue"
            gameupdate._add_skip(state_dir, rec)
            changes.append(f"今天跳过 {rec['script']}")
    if not changes:
        return True, "已经是这个状态，无需改动"
    return True, f"队列「{name}」：{'；'.join(changes)}（调度程序已确认，跳过的明天开机改回）"


def _enabled_via_backend(name: str, enabled: bool) -> tuple[bool, str] | None:
    """Flip the switch through the running AUTO-MAS backend and read it back.

    None means the backend refused the connection (annihilation._backend_unreachable),
    so the file is safe to edit: it is read when AUTO-MAS starts. A timeout or an
    error from a backend that is there is a failure, never None. While the backend
    runs, it does not re-read the file and writes its in-memory copy back over a
    file edit. Success is reported only after /api/queue/get returns the new value.
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
        # is overwritten from AUTO-MAS's memory (see the docstring).
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
          scripts: list[str] | None = None, state_dir: Path | None = None) -> tuple[bool, str]:
    """Enable/disable a queue and/or set which scripts it runs today."""
    name = names.canonical(name)
    if enabled is not None and not isinstance(enabled, bool):
        return False, f"enabled 必须是 true/false，收到 {enabled!r}"
    if scripts is not None:
        out = []
        if enabled is not None:
            ok, detail = apply(automas_dir, name, enabled)
            if not ok:
                return ok, detail
            out.append(detail)
        ok, detail = _scripts_via_backend(state_dir, name, list(scripts))
        return ok, "；".join(out + [detail])
    if enabled is not None:
        if (via := _enabled_via_backend(name, enabled)) is not None:
            return via
    path = _path(automas_dir)
    try:
        original = path.read_text(encoding="utf-8")
        data = json.loads(original)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"读不了 QueueConfig: {exc}"

    target = None
    # Not called `names`: that is the module used by names.canonical() above, and a
    # local of the same name would make that call raise UnboundLocalError.
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
    if enabled is not None:
        if err := _apply_enabled(target, enabled, changes):
            return False, err

    if not changes:
        return True, "已经是这个状态，无需改动"

    stamp = datetime.now(tz=SERVER_TZ)
    backup = path.with_suffix(f".bak-{stamp:%Y%m%d-%H%M%S}.json")
    shutil.copy2(path, backup)
    try:
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as exc:
        shutil.copy2(backup, path)
        return False, f"写入失败，已回滚: {exc}"
    return True, f"队列「{name}」：{'；'.join(changes)}（备份 {backup.name}）"
