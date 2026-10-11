"""Runs a 停一切 (emergency stop) press cut short, booked at boot when the
press was recorded after the run (backfill_manual_stops), and the held alarms
such a run settles: the failure it cut off from its retries is pushed now.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from ark_relay.core.config import SERVER_TZ, RunRecord, atomic_write_text
from ark_relay.features.alarm.pushes import _push_now
from ark_relay.features.alarm.records import run_day

# Same logger as handle.py: relay.log names these lines "ark.handle".
log = logging.getLogger("ark.handle")


def backfill_manual_stops(eng, now: datetime | None = None) -> int:
    """Book as manual stops the runs of today and yesterday that a recorded press
    overlaps but whose ledger line lacks raw.manual_stop. Returns how many.

    Run once per boot, after the self-update, so the new code does it. Covers a
    press recorded after its run was booked, or one that predates the window file
    (commands.ESTOP_SEED, merged here first). Each ledger file is rewritten once,
    atomically, with every other line - torn ones included - kept byte for byte.
    Idempotent: a patched line is skipped the next time.

    Also drops the alarms _handle would have dropped at record time: a held
    failure of the same script and user that started no later than the stopped
    run (its final alarm), and a self-heal notice the stopped run produced by
    reading as a success. The engine has already loaded both from disk in its
    constructor, so they are removed in memory and persisted.
    """
    from ark_relay.features.phone import commands  # noqa: PLC0415
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    state_dir = eng.cfg.state_dir
    commands.merge_estop_seed(state_dir, now)
    windows = commands.estop_windows(state_dir)
    if not windows:
        return 0
    patched: list[dict] = []
    entries: list[dict] = []
    for day in sorted({(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in (1, 0)}):
        path = eng.state.ledger_path(day)
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        hit = False
        for i, ln in enumerate(lines):
            try:
                e = json.loads(ln)
                started = datetime.fromisoformat(str(e["started"]))
                finished = datetime.fromisoformat(str(e["finished"]))
            except (ValueError, TypeError, KeyError):
                continue          # a torn or foreign line stays exactly as it is
            entries.append(e)
            raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
            if raw.get("manual_stop"):
                continue
            if not (label := commands.estop_label(windows, started, finished)):
                continue
            raw["manual_stop"] = label
            e["raw"] = raw
            lines[i] = json.dumps(e, ensure_ascii=False)
            patched.append(e)
            hit = True
            log.info("⏹ 补记：%s %s（%s）这趟是停一切停掉的，记手动停止",
                     e.get("script"), e.get("run_id"), label)
        if hit:
            atomic_write_text(path, "\n".join(lines) + "\n")
    if patched:
        _drop_alarms_for_manual(eng, patched, entries)
    return len(patched)


def _push_before_stop(eng, failed: RunRecord, stop: str) -> list:
    """A failure that a 停一切 cut off from its retries / make-up: pushed now, saying so."""
    # Imported at call time: handle imports this module, and _failure_alarm stays in
    # handle with the evidence helpers tests rebind there.
    from ark_relay.features.alarm.handle import _failure_alarm  # noqa: PLC0415
    day = run_day(failed)
    title, body = _failure_alarm(eng, failed, f"后面那趟是停一切停掉的（{stop}），这次失败没再重试、也没补跑，照报。")
    return _push_now(eng, day, "停一切前", failed.run_id, title, body)


def _drop_alarms_for_manual(eng, patched: list[dict], entries: list[dict]) -> None:
    """Settle held alarms tied to runs just booked as manual stops (see backfill_manual_stops):
    the failure is pushed now instead of waiting for retries a 停一切 ended."""
    def _at(v) -> datetime:
        t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
        return t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)

    changed = False
    for e in patched:
        key = (e.get("script"), e.get("user"))
        stop_at = _at(e["started"])
        held = eng._pending.get(key)
        stop = (e.get("raw") or {}).get("manual_stop") or "停一切"
        if held is not None and _at(held.started) <= stop_at:
            eng._pending.pop(key, None)
            changed = True
            _push_before_stop(eng, held, stop)
            log.info("⏹ 补记：%s %s 的失败已报群（后面那趟是停一切停掉的）", key[0], held.run_id)
        healed = eng._recovered.get(key)
        if healed is None or _at(healed.started) > stop_at:
            continue
        # A genuine success between the held failure and the stopped run is what
        # healed it; that notice stands.
        cured = any(x is not e and x.get("ok") and not (x.get("raw") or {}).get("manual_stop")
                    and (x.get("script"), x.get("user")) == key
                    and _at(healed.started) < _at(x["started"]) < stop_at
                    for x in entries)
        if not cured:
            # The 「success」 that healed it was the stopped run: it was not healed.
            eng._recovered.pop(key, None)
            changed = True
            _push_before_stop(eng, healed, stop)
            log.info("⏹ 补记：%s %s 不算重试后成功（那次成功是停一切停掉的），失败已报群",
                     key[0], healed.run_id)
    if changed:
        eng._persist_pending()
