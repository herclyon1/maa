"""One make-up run, the way a person would do it, before a MAA / MaaEnd failure is called final.

The user, 2026-10-05 13:07: 「中继我就要求一个，他不要再报错了……几乎就是遇到
一点小毛病就停下来报错」. Until then a MAA or MaaEnd failure that outlived
AUTO-MAS's own three attempts went straight to the group as 「最终失败」
(handle._flush_pending). 2026-09-25: MaaEnd's 送礼 / 基质刷取 / 日常奖励 failed
3/3 and the group got an alarm, although a fresh game and one more go at just
those three tasks is all anyone would have done about it.

So, once the queue is idle:

* MaaEnd: the AUTO-MAS master (mxu-MaaEnd.json) is narrowed so that only the
  failed tasks are enabled - plus 存放背包 when a claim failed on a full bag and
  the master already has that task - the game is closed, and the MaaEnd script
  is dispatched through AUTO-MAS once. AUTO-MAS copies the master into MaaEnd
  before every attempt, so its own retries of the make-up run stay narrowed.
  The saved flags go back when the make-up's record lands (handle._handle), at
  the top of every `maybe_run`, and at boot.
* MAA: there is no single-task path, so the whole MAA script runs again (its
  tasks are idempotent; handle's sanity-short guard covers "nothing left to
  spend").

At most one make-up per script per day (state/makeup/<day>.json). A dispatch
that never got going (AUTO-MAS unreachable, API refused) is `couldnt_run` and
is tried again, up to MAX_TRIES. Whatever the make-up's outcome, nothing goes to
the group: the held failure is dropped with a log line and the daily report
carries one line on the make-up (report.makeup_line).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.makeup")

SCRIPTS = ("MAA", "MaaEnd")
MAX_TRIES = 3
# A dispatch that did not take is retried no sooner than this.
RETRY_GAP_S = 120
# A dispatched make-up that has neither produced a record nor been seen running
# for this long never ran (AUTO-MAS took the order and did nothing with it).
STALE_MIN = 10
# A record this much older than the dispatch can still be the make-up's: the log's
# first line and the dispatch moment come from two clocks on the same machine.
SLACK = timedelta(minutes=2)
# Failures already handled elsewhere: 自动采集's routes by collect_retry, the
# booster by upstream (engine.SOFT_FAILS). Re-running them here would walk the
# gathering routes twice.
SKIP_TASKS = frozenset({"应急理智加强剂", "自动采集"})
STASH = "StashBackpack"
# Destroys items; never switched on by the relay, whatever the master says.
NEVER_ENABLE = frozenset({"DecomposeWeaponEssence"})
GAME_EXE = "Endfield.exe"

# Results kept in the marker. `couldnt_run` is the only one that does not count
# as today's attempt.
DISPATCHED, COULDNT_RUN, GAVE_UP, OK, FAILED, NO_RECORD = (
    "dispatched", "couldnt_run", "gave_up", "ok", "failed", "no_record")


# ------------------------------------------------------------------ marker

def _dir(state_dir) -> Path:
    return Path(state_dir) / "makeup"


def _marker_file(state_dir, day: str) -> Path:
    return _dir(state_dir) / f"{day}.json"


def read_marker(state_dir, day: str) -> dict:
    """{script: {...}} for the day, {} when there is none or it cannot be read."""
    if not state_dir:
        return {}
    try:
        d = json.loads(_marker_file(state_dir, day).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write_marker(state_dir, day: str, data: dict) -> None:
    f = _marker_file(state_dir, day)
    f.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(f, json.dumps(data, ensure_ascii=False, indent=1))


def _day(t: datetime) -> str:
    return t.astimezone(SERVER_TZ).strftime("%Y-%m-%d")


def _at(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=SERVER_TZ)


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)


def attempted(state_dir, day: str, script: str) -> bool:
    """True once the day's make-up for `script` is spent: dispatched (whatever came of
    it) or given up. A dispatch that did not take (`couldnt_run`) is not an attempt."""
    ent = read_marker(state_dir, day).get(script)
    return bool(ent) and ent.get("result") != COULDNT_RUN


# ------------------------------------------------------------- candidates

def eligible(rec, now: datetime | None = None) -> bool:
    """Whether a held failure is one a make-up is for: MAA / MaaEnd, started today,
    not a maintenance day, not a game it could not even enter, not stopped by hand."""
    if getattr(rec, "script", None) not in SCRIPTS:
        return False
    if _day(rec.started) != _day(_now(now)):
        return False
    raw = rec.raw or {}
    return not (raw.get("maintenance") or raw.get("maaend_unreachable") or raw.get("manual_stop"))


def candidates(eng, now: datetime | None = None) -> list:
    """Held failures a make-up is still to be dispatched for (today's marker not spent)."""
    today = _day(_now(now))
    return [r for r in eng._pending.values()
            if eligible(r, now) and not attempted(eng.cfg.state_dir, today, r.script)]


def holding(eng, rec, now: datetime | None = None) -> bool:
    """_flush_pending keeps `rec` held (no push, no drop): its make-up is still to come."""
    return eligible(rec, now) and not attempted(eng.cfg.state_dir, _day(_now(now)), rec.script)


def in_flight(state_dir, now: datetime | None = None) -> list[str]:
    """Scripts whose dispatched make-up has not produced a record yet and is not stale."""
    now = _now(now)
    out = []
    for script, ent in read_marker(state_dir, _day(now)).items():
        if not isinstance(ent, dict) or ent.get("result") != DISPATCHED:
            continue
        stamps = [t for t in (_at(ent.get("dispatched_at")), _at(ent.get("seen_running_at"))) if t]
        if stamps and now - max(stamps) <= timedelta(minutes=STALE_MIN):
            out.append(script)
    return out


def next_moment(state_dir, now: datetime | None = None) -> tuple[datetime, str] | None:
    """The next moment a make-up decision changes by the clock alone, for engine.next_deadline."""
    now = _now(now)
    out: list[tuple[datetime, str]] = []
    for script, ent in read_marker(state_dir, _day(now)).items():
        if not isinstance(ent, dict):
            continue
        stamps = [t for t in (_at(ent.get("dispatched_at")), _at(ent.get("seen_running_at"))) if t]
        if not stamps:
            continue
        if ent.get("result") == COULDNT_RUN:
            out.append((max(stamps) + timedelta(seconds=RETRY_GAP_S), f"补跑 {script} 再派一次"))
        elif ent.get("result") == DISPATCHED:
            out.append((max(stamps) + timedelta(minutes=STALE_MIN, seconds=1), f"补跑 {script} 有没有跑起来"))
    out = [m for m in out if m[0] > now]
    return min(out) if out else None


def waiting(eng, now: datetime | None = None) -> list[str]:
    """What the shutdown decision and the reports wait for: make-ups still to dispatch or running."""
    names = {r.script for r in candidates(eng, now)} | set(in_flight(eng.cfg.state_dir, now))
    return sorted(names)


# ------------------------------------------------- MaaEnd master narrowing

def _narrow_file(state_dir) -> Path:
    return _dir(state_dir) / "narrow.json"


def _strip(name: str) -> str:
    from .collector_maaend import _strip_emoji  # noqa: PLC0415
    return _strip_emoji(str(name or ""))


def _labels(maaend_dir) -> dict[str, str]:
    """{taskName: label as MaaEnd prints it in 「任务失败: …」, emoji stripped}."""
    from . import mastercfg  # noqa: PLC0415
    zh = mastercfg._Locale(Path(maaend_dir) if maaend_dir else None)
    _, decls = mastercfg._maaend_defs(maaend_dir)
    out: dict[str, str] = {}
    for name, decl in decls.items():
        if ref := (decl or {}).get("label"):
            out[name] = _strip(zh(ref))
    for key, val in zh.table.items():
        if key.startswith("task.") and key.endswith(".label") and key.count(".") == 2:
            out.setdefault(key[5:-6], _strip(val))
    return out


def _set_flag(task: dict, on: bool) -> None:
    """`enabled` and every per-controller copy of it (maaend.py does the same)."""
    task["enabled"] = on
    ctl = task.get("enabledByController")
    if isinstance(ctl, dict):
        for k in ctl:
            ctl[k] = on
    elif isinstance(ctl, bool):
        task["enabledByController"] = on


def plan_maaend(doc: dict, failed: list[str], causes: dict, labels: dict[str, str]) -> tuple[list[str], list[str]]:
    """(taskNames to enable, failed names that map to nothing in the master)."""
    from .collector_maaend import BAG_FULL  # noqa: PLC0415
    tasks = [t for inst in doc.get("instances") or [] for t in inst.get("tasks") or []]
    names = [str(t.get("taskName") or "") for t in tasks]
    by_label: dict[str, str] = {}
    for t in tasks:
        n = str(t.get("taskName") or "")
        if not n or n.startswith("__") or n in NEVER_ENABLE:
            continue
        for lab in (labels.get(n), _strip(t.get("customName") or "")):
            if lab:
                by_label.setdefault(lab, n)
    want: list[str] = []
    unmapped: list[str] = []
    for f in failed:
        f = _strip(f)
        if f in SKIP_TASKS:
            continue
        n = by_label.get(f)
        if n is None:
            unmapped.append(f)
        elif n not in want:
            want.append(n)
    bag = any(c == BAG_FULL for c in (causes or {}).values())
    if want and bag and STASH in names and STASH not in want:
        want.insert(0, STASH)
    return want, unmapped


def narrow_master(cfg, want: list[str], run_id: str, now: datetime) -> str:
    """Leave only `want` enabled in the MaaEnd master, StashBackpack moved in front of
    the first of them. The original flags and order go to state/makeup/narrow.json
    first; an existing save is kept, never overwritten. Returns a log line, '' when
    nothing was changed."""
    from . import mastercfg  # noqa: PLC0415
    f = mastercfg.maaend_master(cfg.automas_dir) if cfg.automas_dir else None
    if not f or not f.is_file() or not want:
        return ""
    doc = json.loads(f.read_text(encoding="utf-8"))
    insts = doc.get("instances") or []
    saved = {"run_id": run_id, "at": now.isoformat(),
             "order": [[t.get("id") for t in inst.get("tasks") or []] for inst in insts],
             "flags": {str(t.get("id")): {"enabled": t.get("enabled"),
                                         "enabledByController": t.get("enabledByController")}
                       for inst in insts for t in inst.get("tasks") or [] if t.get("id")}}
    nf = _narrow_file(cfg.state_dir)
    nf.parent.mkdir(parents=True, exist_ok=True)
    if not nf.exists():
        nf.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    for inst in insts:
        tasks = inst.get("tasks") or []
        for t in tasks:
            n = str(t.get("taskName") or "")
            if not n or n.startswith("__"):
                continue                  # MXU's own entries (kill-process, webhook) stay as they are
            _set_flag(t, n in want and n not in NEVER_ENABLE)
        if STASH in want:
            stash = [t for t in tasks if t.get("taskName") == STASH]
            first = next((i for i, t in enumerate(tasks)
                          if t.get("taskName") in want and t.get("taskName") != STASH), None)
            if stash and first is not None and tasks.index(stash[0]) > first:
                tasks.remove(stash[0])
                tasks.insert(first, stash[0])
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    back = json.loads(f.read_text(encoding="utf-8"))
    on = sorted({str(t.get("taskName")) for inst in back.get("instances") or [] for t in inst.get("tasks") or []
                 if t.get("enabled") and not str(t.get("taskName") or "").startswith("__")})
    if on != sorted(set(want) - NEVER_ENABLE):
        log.warning("母本收窄后回读不对：开着的是 %s，改回原样、这次不补", on)
        restore(cfg)
        return ""
    return f"母本里的终末地任务暂时只开 {'、'.join(want)}"


def restore(cfg) -> str:
    """Put the saved enabled flags and task order back. '' when there is nothing to restore."""
    from . import mastercfg  # noqa: PLC0415
    nf = _narrow_file(cfg.state_dir)
    if not nf.exists():
        return ""
    try:
        saved = json.loads(nf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.exception("补跑的收窄记录读不出来，母本没法自动改回")
        return ""
    f = mastercfg.maaend_master(cfg.automas_dir) if cfg.automas_dir else None
    if not f or not f.is_file():
        return ""
    doc = json.loads(f.read_text(encoding="utf-8"))
    flags = saved.get("flags") or {}
    for i, inst in enumerate(doc.get("instances") or []):
        tasks = inst.get("tasks") or []
        order = (saved.get("order") or [])[i] if i < len(saved.get("order") or []) else []
        rank = {tid: k for k, tid in enumerate(order)}
        tasks.sort(key=lambda t: rank.get(t.get("id"), len(rank)))   # stable: unknown ones keep their place at the end
        for t in tasks:
            if (old := flags.get(str(t.get("id")))) is None:
                continue
            t["enabled"] = old.get("enabled")
            if old.get("enabledByController") is None:
                t.pop("enabledByController", None)
            else:
                t["enabledByController"] = old.get("enabledByController")
    atomic_write_text(f, json.dumps(doc, ensure_ascii=False, indent=2))
    back = json.loads(f.read_text(encoding="utf-8"))
    got = {str(t.get("id")): {"enabled": t.get("enabled"), "enabledByController": t.get("enabledByController")}
           for inst in back.get("instances") or [] for t in inst.get("tasks") or [] if t.get("id")}
    if any(got.get(k) != v for k, v in flags.items() if k in got):
        log.error("母本改回后回读不对")
        return ""
    nf.unlink()
    return f"母本里的终末地任务已改回原样（{saved.get('run_id', '')} 补跑时临时改过）"


# ---------------------------------------------------------------- dispatch

def _kill_game() -> None:
    from .desktop import kill  # noqa: PLC0415
    kill(GAME_EXE)


def _dispatch(script: str) -> tuple[bool, str]:
    from . import commands  # noqa: PLC0415
    return commands.run_script(script)


def _blocked(eng, now: datetime) -> str:
    """Why the queue is not idle enough for a make-up; '' when it is."""
    from . import echofarm, modes  # noqa: PLC0415
    if modes.debug_active(eng.state.dir):
        return "调试模式开着"
    if eng._scripts_running():
        return "脚本或游戏还在跑"
    if echofarm.current(eng.cfg.state_dir):
        return "正在刷声骸"
    if eng._deferred_update_busy():
        return "游戏客户端正在更新或重跑"
    if unfinished := eng._unfinished_queues(now, eng._recent_entries(now)):
        return "；".join(unfinished)
    return ""


def _settle_stale(eng, now: datetime, marker: dict, day: str) -> bool:
    """Note a running make-up, and close out one that never ran. True if the marker changed."""
    changed = False
    for script, ent in marker.items():
        if not isinstance(ent, dict) or ent.get("result") != DISPATCHED:
            continue
        if eng._script_running(script):
            last = _at(ent.get("seen_running_at"))
            if last is None or now - last >= timedelta(seconds=60):
                ent["seen_running_at"] = now.isoformat()
                changed = True
        elif script not in in_flight(eng.cfg.state_dir, now):
            ent["result"] = NO_RECORD
            changed = True
            log.warning("补跑：%s 派下去了，但 AUTO-MAS 没跑出记录", script)
    if changed:
        _write_marker(eng.cfg.state_dir, day, marker)
    return changed


def maybe_run(eng, now: datetime | None = None) -> bool:
    """Dispatch one make-up when the queue is idle. True when something was dispatched
    (or a dispatch that did not take is to be tried again), False otherwise.

    A tick step of its own (engine.tick, before the interim and daily reports and
    the shutdown decision): the shutdown decision cannot host it, because a held
    failure keeps that decision at 「还有告警没推出去」 and it would never reach the
    point of running anything.
    """
    now = _now(now)
    day = _day(now)
    state_dir = eng.cfg.state_dir
    marker = read_marker(state_dir, day)
    _settle_stale(eng, now, marker, day)
    if "MaaEnd" not in in_flight(state_dir, now):
        if back := restore(eng.cfg):
            log.info("补跑：%s", back)
    todo = candidates(eng, now)
    if not todo:
        return False
    if why := _blocked(eng, now):
        if why != getattr(eng, "_makeup_wait_note", ""):
            eng._makeup_wait_note = why
            log.info("补跑：%s 等着（%s）", "、".join(sorted({r.script for r in todo})), why)
        return False
    eng._makeup_wait_note = ""
    rec = sorted(todo, key=lambda r: r.started)[0]   # one at a time: two games at once is not what a person does
    ent = dict(marker.get(rec.script) or {})
    if (last := _at(ent.get("dispatched_at"))) is not None and (now - last).total_seconds() < RETRY_GAP_S:
        return True
    tries = int(ent.get("tries") or 0) + 1
    ent.update({"dispatched_at": now.isoformat(), "tries": tries, "run_id": rec.run_id,
                "failed": list(rec.failed_tasks or []), "result": DISPATCHED, "note": ""})
    if rec.script == "MaaEnd":
        try:
            ok, ent = _prepare_maaend(eng, rec, ent, now)
        except Exception as exc:  # noqa: BLE001 - a bad master must not raise every tick
            # WARNING, not ERROR: an ERROR line is itself a group alarm (errwatch),
            # and the outcome is already in the marker and the daily report.
            log.warning("补跑：准备终末地母本出错", exc_info=True)
            restore(eng.cfg)
            ok = False
            ent.update(result=GAVE_UP, note=f"母本读写出错（{type(exc).__name__}: {exc}）")
        if not ok:
            marker[rec.script] = ent
            _write_marker(state_dir, day, marker)
            log.warning("补跑：终末地这次不补（%s）", ent.get("note"))
            return False
    else:
        ent["tasks"] = ["整个 MAA"]
    marker[rec.script] = ent
    _write_marker(state_dir, day, marker)        # before the dispatch: a crash after it must not dispatch twice
    if rec.script == "MaaEnd":
        _kill_game()
    try:
        ok, msg = _dispatch(rec.script)
    except Exception as exc:  # noqa: BLE001 - a make-up must never take the service down
        ok, msg = False, f"{type(exc).__name__}: {exc}"
    if not ok:
        if rec.script == "MaaEnd":
            restore(eng.cfg)
        ent["result"] = COULDNT_RUN if tries < MAX_TRIES else GAVE_UP
        ent["note"] = msg
        marker[rec.script] = ent
        _write_marker(state_dir, day, marker)
        log.warning("补跑：%s 没派下去（第 %d 次，%s）", rec.script, tries, msg)
        return ent["result"] == COULDNT_RUN
    # A run the relay dispatched itself is not a round someone started by hand
    # (shutdown._last_round_manual reads this, as it does for the update re-run).
    eng._gu_rerun_at = now
    log.info("🔁 补跑：%s 只补一次（%s）→ %s", rec.script, "、".join(ent.get("tasks") or []), msg)
    return True


def _prepare_maaend(eng, rec, ent: dict, now: datetime) -> tuple[bool, dict]:
    """Narrow the master to the failed tasks. (False, ent marked gave_up) when there is nothing to run."""
    from . import mastercfg  # noqa: PLC0415
    cfg = eng.cfg
    f = mastercfg.maaend_master(cfg.automas_dir) if cfg.automas_dir else None
    if not f or not f.is_file():
        ent.update(result=GAVE_UP, note="找不到终末地的母本")
        return False, ent
    doc = json.loads(f.read_text(encoding="utf-8"))
    want, unmapped = plan_maaend(doc, list(rec.failed_tasks or []),
                                 (rec.raw or {}).get("maaend_fail_causes") or {}, _labels(cfg.maaend_dir))
    notes = []
    if unmapped:
        notes.append("母本里对不上的：" + "、".join(unmapped))
    if not want:
        ent.update(result=GAVE_UP, tasks=[], note="；".join(notes) or "没有能补的任务")
        return False, ent
    restore(cfg)                    # a leftover narrowing is not the original to save
    if not (line := narrow_master(cfg, want, rec.run_id, now)):
        ent.update(result=GAVE_UP, tasks=want, note="母本没改成")
        return False, ent
    log.info("补跑：%s", line)
    labels = _labels(cfg.maaend_dir)
    ent["tasks"] = [labels.get(n, n) for n in want]
    ent["note"] = "；".join(notes)
    return True, ent


# ------------------------------------------------------- the make-up's record

def on_record(eng, rec) -> None:
    """Book the make-up's own record into the marker; on success, tie the earlier
    failures to it on the ledger (raw.makeup_ok), so the report reads them as retried."""
    if rec.script not in SCRIPTS or rec.transitional:
        return
    day = _day(rec.started)
    marker = read_marker(eng.cfg.state_dir, day)
    ent = marker.get(rec.script)
    if not isinstance(ent, dict) or ent.get("result") not in (DISPATCHED, OK, FAILED, NO_RECORD):
        return
    since = _at(ent.get("dispatched_at"))
    if since is None or rec.started < since - SLACK:
        return
    stopped = bool((rec.raw or {}).get("manual_stop"))
    ent["result"] = OK if rec.ok and not stopped else FAILED
    ent["record"] = rec.run_id
    if stopped:
        ent["note"] = "被停一切停掉"
    elif not rec.ok:
        ent["note"] = "、".join(rec.failed_tasks or []) or ent.get("note", "")
    marker[rec.script] = ent
    _write_marker(eng.cfg.state_dir, day, marker)
    if ent["result"] != OK:
        log.info("补跑：%s %s 没成（%s）", rec.script, rec.run_id, ent.get("note"))
        return
    when = rec.finished.astimezone(SERVER_TZ).strftime("%H:%M")
    for e in eng.state.read_ledger(day):
        if e.get("script") != rec.script or e.get("user") != rec.user:
            continue
        started = _at(e.get("started"))
        if started is None or started >= since - SLACK:
            continue
        if not e.get("ok"):
            eng.state.mark_raw(day, e["run_id"], "makeup_ok", when)
        elif e.get("incomplete") and rec.script == "MAA":
            # The whole of MAA ran again and went through; a narrowed MaaEnd only
            # re-ran the failed tasks and says nothing about an unfinished one.
            eng.state.mark_incomplete(day, e["run_id"], "")
    log.info("✅ 补跑：%s %s 走通", rec.script, rec.run_id)
