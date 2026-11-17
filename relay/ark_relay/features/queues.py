"""Keep Endfield's failure retry limit in AUTO-MAS at 1.

The limit is AUTO-MAS's own setting, written through its API. An AUTO-MAS update, or one click
in its window, puts it back to 3 with nobody noticing. So every engine tick reads it, and a
value other than 1 is written back and read back (commands._script_item_via_api). AUTO-MAS
refuses the write while that script runs (「正在运行，无法更新配置项」, 11-05 13:1x); the next tick
tries again, and a tick comes when the run's record lands. A write that worked is one Server-chan
line a day; ALARM_AFTER failures in a row for another reason are one group alarm.
"""
from __future__ import annotations

import logging
import json
import shutil
from datetime import datetime
from ark_relay.core import texts, config as names
from ark_relay.core.config import SERVER_TZ, atomic_write_text
from pathlib import Path

_log_run_limit = logging.getLogger(__name__)

WANT = {"MaaEnd": 1}
GAME = {"MaaEnd": "终末地"}
PATH = "Run.RunTimesLimit"
SINCE = "2026-11-05"
BUSY = "正在运行"
ALARM_AFTER = 3


def _read(script: str) -> "tuple[dict | None, object]":
    """(the /api/scripts/get reply, the current limit), or (None, None) when the
    backend is down or the script / item is not there (nothing to guard then)."""
    from ark_relay.features import commands  # noqa: PLC0415
    reply, _why = commands._backend_scripts()
    scripts = reply.get("data") if isinstance(reply, dict) else None
    if not isinstance(scripts, dict):
        return None, None
    for sc in scripts.values():
        if isinstance(sc, dict) and str((sc.get("Info") or {}).get("Name") or "").lower() == script.lower():
            try:
                return reply, commands._dig(sc, PATH)
            except KeyError:
                return None, None
    return None, None


def _fails(eng) -> dict:
    """{script: {"n": write-backs failed in a row, "alarmed": the group has it}}, on the engine."""
    got = getattr(eng, "_run_limit_fails", None)
    if not isinstance(got, dict):
        got = {}
        eng._run_limit_fails = got
    return got


def step(eng, now: "datetime | None" = None) -> None:
    """One look per engine tick; a limit other than WANT is written back."""
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    day = now.strftime("%Y-%m-%d")
    if day < SINCE:
        return
    from ark_relay.features import commands  # noqa: PLC0415
    for script, want in WANT.items():
        reply, cur = _read(script)
        if reply is None:
            continue
        fails = _fails(eng)
        if cur == want:
            fails.pop(script, None)
            continue
        ok, msg = commands._script_item_via_api(reply, script, PATH, want)
        game = GAME.get(script, script)
        if ok:
            _log_run_limit.info("%s 的失败重试上限被改成了 %s，已改回 %s：%s", script, cur, want, msg)
            fails.pop(script, None)
            if getattr(eng, "_run_limit_noted", "") != day and \
                    not eng.notifier.send(texts.RUN_LIMIT_RESET, texts.run_limit_reset_body(game, cur, want)):
                eng._run_limit_noted = day
            continue
        if BUSY in msg:
            _log_run_limit.info("%s 正在跑，失败重试上限 %s 先不改回 %s，下一轮再改", script, cur, want)
            continue
        st = fails.setdefault(script, {"n": 0, "alarmed": False})
        st["n"] += 1
        n = st["n"]
        _log_run_limit.info("%s 的失败重试上限是 %s，改回 %s 没成（第 %d 次）：%s", script, cur, want, n, msg)
        if n >= ALARM_AFTER and not st["alarmed"]:
            errs = eng.notifier.send(texts.RUN_LIMIT_STUCK, texts.run_limit_stuck_body(game, cur, want, msg), alert=True)
            st["alarmed"] = not errs


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
    """_apply_scripts, with a failure's receipt also naming what it had already changed.

    A restore or skip that landed before a later step failed is real (AUTO-MAS was
    changed, updates.queue_skips holds it); a receipt with only the failing step
    would read as "nothing changed"."""
    done: list[str] = []
    ok, text = _apply_scripts(state_dir, name, scripts, done)
    if not ok and done:
        text += f"；这之前已经改了：{'；'.join(dict.fromkeys(done))}"
    return ok, text


def _apply_scripts(state_dir: Path | None, name: str, scripts: list[str],
                   changes: list[str]) -> tuple[bool, str]:
    """Run only `scripts` in queue `name` today: skip the rest, put back listed ones we skipped.
    Each change that landed is appended to `changes` as it happens.

    Backend only: a Schedule.Days edit in the file is overwritten from AUTO-MAS's
    memory while it runs, and on a powered-off machine there is no "today" to
    skip. A listed script the relay did not skip keeps whatever days the user
    gave it. Each skip is recorded in updates.queue_skips with source "queue",
    so the boot-time restore puts it back on the next day and the game-update
    re-run (restore_skips(manual_too=False)) leaves it alone.

    A skip the game update made (maintenance) is never undone here: listing that
    script only takes the queue command's hold off it, and the item stays out
    until the update's re-run puts it back. Skipping a script the update already
    took out adds the queue command as a second holder of that record, so the
    update's put-back does not bring it back today either (gameupdate._add_skip).
    """
    if state_dir is None:
        return False, f"队列「{name}」没改：找不到中继的状态目录，记不下明天要改回的跳过"
    from ark_relay.features import commands  # noqa: PLC0415 - avoids an import cycle
    from ark_relay.features import gameupdate  # noqa: PLC0415 - avoids an import cycle
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
    today = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    for rec in [r for r in gameupdate.skips(state_dir) if r.get("queueId") == qid and r.get("scriptId") in want]:
        if gameupdate._sources(rec) != {"queue"}:
            # The game update holds it: the item stays out (only our hold, if any,
            # is dropped), and the receipt says why the listed script will not run.
            if "queue" in gameupdate._sources(rec):
                gameupdate._release(state_dir, rec, "queue")
            changes.append(f"{rec.get('script')} 今天为游戏更新先跳过，更新完由中继补跑")
            continue
        if not commands.restore_script_in_queue(rec):
            return False, f"队列「{name}」：{rec.get('script')} 今天的跳过没撤掉（调度程序读回来没变）"
        gameupdate._drop_skip(state_dir, rec)
        changes.append(f"恢复 {rec.get('script')}")
    for sid in dict.fromkeys(s for s in in_queue if s and s not in want):
        script = back.get(sid, sid)
        try:
            recs = commands.skip_script_all_items(name, script)
        except Exception as exc:  # noqa: BLE001
            # Items whose run days may already be trimmed: keep their undo
            # records, or the weekday stays removed for good.
            for rec in getattr(exc, "recs", []):
                rec["source"] = "queue"
                gameupdate._add_skip(state_dir, rec)
            return False, f"队列「{name}」：今天跳过 {script} 失败（{exc}）"
        for rec in recs:
            rec["source"] = "queue"
            gameupdate._add_skip(state_dir, rec)
        # Items the game update already took out today: hold them as well.
        held = [r for r in gameupdate.skips(state_dir) if r.get("queueId") == qid and r.get("scriptId") == sid
                and str(r.get("day") or "") == today and "queue" not in gameupdate._sources(r)]
        for rec in held:
            gameupdate._add_skip(state_dir, dict(rec, source="queue", sources=["queue"]))
        if recs or held:
            changes.append(f"今天跳过 {script}")
    if not changes:
        return True, "已经是这个状态，无需改动"
    changes = list(dict.fromkeys(changes))     # one line per script, not per item
    return True, f"队列「{name}」：{'；'.join(changes)}（调度程序已确认，跳过的明天开机改回）"


def _enabled_via_backend(name: str, enabled: bool) -> tuple[bool, str] | None:
    """Flip the switch through the running AUTO-MAS backend and read it back.

    None means the backend refused the connection (annihilation._backend_unreachable),
    so the file is safe to edit: it is read when AUTO-MAS starts. A timeout or an
    error from a backend that is there is a failure, never None. While the backend
    runs, it does not re-read the file and writes its in-memory copy back over a
    file edit. Success is reported only after /api/queue/get returns the new value.
    """
    from ark_relay.features.annihilation import _backend_unreachable  # noqa: PLC0415 - avoids an import cycle
    from ark_relay.features.commands import _mas  # noqa: PLC0415 - avoids an import cycle
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
    from ark_relay.core import mastercfg as masconfig  # noqa: PLC0415
    import re  # noqa: PLC0415
    path = masconfig.source(_path(automas_dir))
    try:
        original = path.read_text(encoding="utf-8")
        data = masconfig.parse_text(path, original)
    except (OSError, ValueError) as exc:
        return False, f"读不了 QueueConfig: {exc}"

    target = None
    target_uid = ""
    # Not called `names`: that is the module used by names.canonical() above, and a
    # local of the same name would make that call raise UnboundLocalError.
    have = []
    for inst in data.get("instances", []):
        uid = str(inst.get("uid") or "")
        node = data.get(uid) or {}
        qn = (node.get("Info") or {}).get("Name")
        have.append(qn)
        if qn == name:
            target = node
            target_uid = uid
    if target is None:
        return False, f"没有叫「{name}」的队列（现有：{'、'.join(n for n in have if n)}）"

    changes: list[str] = []
    if enabled is not None:
        if err := _apply_enabled(target, enabled, changes):
            return False, err

    if not changes:
        return True, "已经是这个状态，无需改动"

    if path.suffix == ".yaml":
        pat = re.compile(rf"(?ms)(^  {re.escape(target_uid)}:\n.*?^\s*TimeEnabled:\s*)(?:true|false)(\s*$)")
        updated, count = pat.subn(rf"\g<1>{'true' if enabled else 'false'}\2", original, count=1)
        try:
            if count != 1 or masconfig.parse_text(path, updated) != data:
                return False, f"改动 {path.name} 后核对不符，已放弃"
        except ValueError as exc:
            return False, f"改动 {path.name} 后语法非法，已放弃: {exc}"
    else:
        updated = json.dumps(data, ensure_ascii=False, indent=2)

    stamp = datetime.now(tz=SERVER_TZ)
    backup = path.with_suffix(f".bak-{stamp:%Y%m%d-%H%M%S}{path.suffix}")
    shutil.copy2(path, backup)
    try:
        atomic_write_text(path, updated)
    except OSError as exc:
        shutil.copy2(backup, path)
        return False, f"写入失败，已回滚: {exc}"
    return True, f"队列「{name}」：{'；'.join(changes)}（备份 {backup.name}）"
