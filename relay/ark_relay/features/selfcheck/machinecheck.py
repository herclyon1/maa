"""Machine checks: changes not yet confirmed on the game machine, judged by the machine itself.

Asked for by the user on 2026-10-06 04:59. Each open ledger item is a check here:

* kind "A": exercised by the normal runs - judged from the relay's own logs,
  screenshots and game readings right after the run that exercises it;
* kind "B": needs one natural trigger (a phone command, a game update day, the
  red button, ...) - judged the next time that trigger happens on its own. A check
  never starts a game task, spends stamina or presses anything to get judged.

A check is a function of the event that just happened. It returns None when that
event did not exercise it (nothing to say yet), else PASS or FAIL with the one
evidence line it rests on (a log line, a screenshot path, a game reading). Every
FAIL is pushed to the group, every time it is judged (the user's order of 2026-10-06:
「只要是报错…不论多少次什么错误都要发」); PASS and still-waiting go to the daily
report's 「上机核对」 section only. Results live in state/machinecheck.json, per
item: the last verdict, its evidence, when, event, version, and pass / fail counts.

Items that cannot be automated are listed in CANNOT with the reason, shown in the
daily section.

The helpers at the end read the state files several check modules judge from.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ark_relay.core.config import SERVER_TZ, atomic_write_text

log = logging.getLogger("ark.machinecheck")

PASS, FAIL = "PASS", "FAIL"
STATE_FILE = "machinecheck.json"


@dataclass
class Result:
    status: str          # PASS | FAIL
    evidence: str        # the one line the verdict rests on


@dataclass
class Check:
    id: str              # the ledger item, e.g. "#4"
    what: str            # plain Chinese: what is being confirmed
    kind: str            # "A" (normal runs) | "B" (one natural trigger)
    triggers: tuple      # event names that can exercise it (see EVENTS)
    fn: Callable


# Event names. A caller passes the event and its context; only checks that listen
# to that event are asked.
EVENTS = {
    "boot": "the relay started (after any self-update)",
    "run": "a run record was booked (ctx: rec, raw, log_text)",
    "banners": "the banners section was built (ctx: trace)",
    "phone_state": "a state was published to the phone (ctx: state)",
    "phone_cmd": "a phone order was applied (ctx: action, ok, msg, receipt)",
    "estop": "the red button finished (ctx: result)",
    "preupdate": "a pre-update ran (ctx: script, steps)",
    "gameupdate": "a game client update ran (ctx: game, screens)",
    "makeup": "a make-up result was booked (ctx: script, result)",
    "unresolved": "an unresolved alarm was decided (ctx: rec, sent)",
    "watchdog": "the MaaEnd watchdog acted (ctx: action, result)",
    "service_stop": "the service was told to stop (ctx: pushed)",
}

CHECKS: dict[str, Check] = {}
# Items that cannot be automated: id -> (what, why).
CANNOT: dict[str, tuple[str, str]] = {}
_LOADED = [False]


def load() -> None:
    """Import every module in ark_relay/features/selfcheck/machinechecks/ once (each registers its checks)."""
    if _LOADED[0]:
        return
    _LOADED[0] = True
    import importlib  # noqa: PLC0415
    import pkgutil  # noqa: PLC0415
    from ark_relay.features.selfcheck import machinechecks  # noqa: PLC0415
    for mod in sorted(pkgutil.iter_modules(machinechecks.__path__), key=lambda m: m.name):
        importlib.import_module(f"{machinechecks.__name__}.{mod.name}")


def check(id: str, what: str, kind: str, *triggers: str):
    """Register a machine check (decorator)."""
    if kind not in ("A", "B"):
        raise ValueError(f"{id}: kind must be A or B")
    bad = [t for t in triggers if t not in EVENTS]
    if bad or not triggers:
        raise ValueError(f"{id}: unknown or no triggers {bad}")

    def wrap(fn):
        if id in CHECKS:
            raise ValueError(f"{id} registered twice")
        CHECKS[id] = Check(id, what, kind, tuple(triggers), fn)
        return fn
    return wrap


def cannot(id: str, what: str, why: str) -> None:
    """Record an item that cannot be automated, with the exact reason."""
    CANNOT[id] = (what, why)


# ------------------------------------------------------------------ state

def _file(state_dir) -> Path:
    return Path(state_dir) / STATE_FILE


# judge runs on every phone-state publish and a WARNING reaches the group, so an
# unreadable state file is logged once per condition and forgotten once it reads again.
_last_error: dict[str, str] = {}


def _read_state(state_dir) -> "dict | None":
    """The state file's rows; {} when there is none yet, None when it exists but
    cannot be read - then judge must not write, or this event's verdicts would
    replace every other check's history."""
    f = _file(state_dir)
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        why = "" if isinstance(d, dict) else f"不是一张表（{type(d).__name__}）"
    except FileNotFoundError:
        d, why = {}, ""
    except (OSError, ValueError) as exc:
        why = f"{type(exc).__name__}: {exc}"
    if why:
        if _last_error.get("state") != why:
            log.warning("上机核对的记录 %s 读不到（%s），这期间的结论不写进去，日报那一段可能是旧的", f, why)
            _last_error["state"] = why
        return None
    _last_error.pop("state", None)
    return d


def read(state_dir) -> dict:
    """{id: {status, evidence, at, version, passes, fails}}; {} when none or unreadable."""
    if not state_dir:
        return {}
    return _read_state(state_dir) or {}


def _write(state_dir, data: dict) -> None:
    f = _file(state_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(f, json.dumps(data, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ judging

def judge(state_dir, event: str, ctx: dict, *, version: str = "", now: datetime | None = None,
          notifier=None) -> list[tuple[str, Result]]:
    """Ask every check that listens to `event`. Records each verdict; pushes each FAIL
    to the group (every time). Returns [(id, Result)] for the checks that judged."""
    from ark_relay.core import texts  # noqa: PLC0415
    if event not in EVENTS:
        raise ValueError(f"unknown event {event!r}")
    load()
    now = (now or datetime.now(tz=SERVER_TZ)).astimezone(SERVER_TZ)
    out: list[tuple[str, Result]] = []
    for c in CHECKS.values():
        if event not in c.triggers:
            continue
        try:
            r = c.fn(dict(ctx, event=event, state_dir=state_dir))
        except Exception:
            # A broken check is a relay fault of its own: ERROR, so it reaches the group.
            log.exception("上机核对 %s 自己出错了（%s）", c.id, c.what)
            continue
        if r is None:
            continue
        if r.status not in (PASS, FAIL):
            log.error("上机核对 %s 给了认不出的结论 %r", c.id, r.status)
            continue
        out.append((c.id, r))
    if not out:
        return out
    data = _read_state(state_dir) if state_dir else {}
    if data is not None:
        for cid, r in out:
            row = dict(data.get(cid) or {})
            row.update(status=r.status, evidence=r.evidence[:300], at=now.strftime("%Y-%m-%d %H:%M:%S"),
                       version=version, event=event)
            key = "passes" if r.status == PASS else "fails"
            row[key] = int(row.get(key) or 0) + 1
            data[cid] = row
        _write(state_dir, data)
    for cid, r in out:
        c = CHECKS[cid]
        if r.status == FAIL:
            title, body = texts.machinecheck_failed(cid, c.what), texts.machinecheck_failed_body(c.what, r.evidence)
            if notifier is None:
                log.error("%s\n%s", title, body)      # no notifier: errwatch pushes the ERROR
                continue
            errs = notifier.send(title, body, alert=True)
            if errs:
                log.error("上机核对 %s 没过，推送也没推出去：%s", cid, "；".join(errs))
            else:
                log.info("上机核对 %s 没过，已报群：%s", cid, r.evidence[:120])
        else:
            log.info("上机核对 %s 过了：%s", cid, r.evidence[:120])
    return out


def daily_section(state_dir) -> str:
    """The daily report's 「上机核对」 lines: every check's latest verdict, or that it still waits."""
    from ark_relay.core import texts  # noqa: PLC0415
    load()
    if not CHECKS and not CANNOT:
        return ""
    data = read(state_dir)
    rows = []
    for cid, c in sorted(CHECKS.items(), key=lambda kv: _num(kv[0])):
        r = data.get(cid) or {}
        rows.append((cid, c.what, c.kind, str(r.get("status") or ""), str(r.get("evidence") or ""),
                     str(r.get("at") or "")))
    return texts.machinecheck_section(rows, sorted(CANNOT.items(), key=lambda kv: _num(kv[0])))


def _num(cid: str) -> int:
    digits = "".join(ch for ch in cid if ch.isdigit())
    return int(digits) if digits else 0


# ------------------------------------------------------------------ shared readers

def judged_before(state_dir, cid: str, evidence: str) -> bool:
    """The verdict on record for `cid` already rests on this very evidence (the same
    session read again, the same receipt): judging it again would count it twice."""
    row = read(state_dir).get(cid) or {}
    return str(row.get("evidence") or "") == evidence[:300]


def alert_rows(state_dir, day8: str) -> list[dict]:
    """The group-alarm copies of one Beijing day (alertlog: state/alerts/<YYYYMMDD>.jsonl),
    oldest first; [] when there is none. Lines that are not JSON objects are skipped."""
    try:
        text = (Path(state_dir) / "alerts" / f"{day8}.jsonl").read_text(encoding="utf-8")
    except (OSError, TypeError):
        return []
    rows = []
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return [r for r in rows if isinstance(r, dict)]


def errkind_rows(state_dir, day: str) -> list[tuple[str, dict]]:
    """(signature, row) of one day's error kinds (errwatch: state/errkinds/<YYYY-MM-DD>.json);
    [] when there is none or it cannot be read."""
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    try:
        data = json.loads((Path(state_dir) / errwatch.DAY_DIR / f"{day}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    return [(str(k), v) for k, v in data.items() if isinstance(v, dict)] if isinstance(data, dict) else []
