"""The App's need table, rebuilt by the relay once a server day and put on COS.

The 库存 page of the App (ark-remote Inventory.swift) shows the stock against what the
newest six-star's full build needs. That table was built by hand on the Mac
(scripts/mac/build-need-tables.py) and published with the phone page; the last run was
2026-09-23, so 祀 and 明河 (in the wiki since October) never reached it. The cause was
the process: a person had to notice a new six-star and rerun it, and again once the
calculator listed her. Here the relay does it on the first tick of each server day
(engine.Engine._need_table), with its own Skland token, and PUTs the result next to the
phone state: `state/<the state's hash>.need.json`, public-read like the state (the App has
no COS keys). The App reads this object only from its next update on (Relay.needURL, with
the old GitHub Pages copy as its fallback); the App installed on 2026-10-14 still reads the
GitHub Pages copy. The bucket's 30-day rule (expire-30d-not-relay) covers state/; a daily
PUT keeps it, and only a machine silent for 30 days loses it.

One build is about 115 Skland requests, 55 s from the Mac (measured 2026-10-14), so it
runs on a thread of its own and the tick never waits for it.

Where a failure goes (relay/USER-SWITCHES.txt, needtable.py:_settle). Every WARNING is
pushed to the owner's group (errwatch), and the group is for what a person must act on
now; a table one day old is not that - the App keeps the previous COS object, and its
库存 footer says on which day that table was built. So:
  * a failed build (or a PUT that did not land) is an INFO line and a red item in the
    technical log (techlog.add_red), and the same server day tries once more, at least
    SECOND_TRY_AFTER after the failure: at most BUILDS_A_DAY builds a day;
  * the mark file counts the server days that ended without a table since the last one
    that had one; a build that works after one or more of them is one WARNING marked
    errwatch.recovered() (daily report only, and errwatch writes its 自愈待查 red item)
    saying how many days were missed;
  * GROUP_AFTER_DAYS such days in a row is one plain WARNING (the group), and not again
    until a build works.
A machine without a topic, COS or Skland token builds nothing: one INFO line a day.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta

from ark_relay.core import techlog
from ark_relay.core.config import SERVER_TZ, atomic_write_text
from ark_relay.features.alarm import errwatch
from ark_relay.features.phone.cos_store import cos_put, state_cos, state_key
from ark_relay.features.phone.mailbox import Mailbox

log = logging.getLogger("ark.needtable")

MARK = "needtable.json"
# The routing numbers are the review's ceiling for this step (2026-10-14, needtable branch),
# not measurements: one more try the same day for a passing Skland or COS fault, spaced so a
# short outage can end first; a table older than three server days is worth a person's look.
BUILDS_A_DAY = 2
SECOND_TRY_AFTER = timedelta(minutes=30)
GROUP_AFTER_DAYS = 3
_lock = threading.Lock()
# This process's builds: the thread, and the server day, count and end of the builds
# started on it - so the cap holds even when the mark file cannot be written.
_running: dict = {}


def need_key(topic: str) -> str:
    """`state/<same hash as the state>.need.json`; built from state_key so the names cannot drift apart."""
    return state_key(topic)[:-len(".json")] + ".need.json"


def _read_mark(state_dir) -> dict:
    try:
        m = json.loads((state_dir / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


def _num(m: dict, key: str) -> int:
    try:
        return int(m.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def due(state_dir, today: str, now: "datetime | None" = None) -> bool:
    """True when a build should start: none yet today, or one failed build that is at
    least SECOND_TRY_AFTER old. Not after a table, a skip (no topic / COS / token), or
    BUILDS_A_DAY builds."""
    m = _read_mark(state_dir)
    if m.get("day") != today:
        return True
    if m.get("ok") or m.get("skip") or _num(m, "tries") >= BUILDS_A_DAY:
        return False
    try:
        return (now or datetime.now(SERVER_TZ)) - datetime.fromisoformat(m.get("last_at") or "") >= SECOND_TRY_AFTER
    except (TypeError, ValueError):   # unreadable, or a time without its zone: the cap still holds
        return True


def _mark(state_dir, mark: dict) -> None:
    try:
        atomic_write_text(state_dir / MARK, json.dumps(mark, ensure_ascii=False))
    except OSError:
        log.info("需求表的当天记号写不进去；这台机器今天照样最多建 %d 次", BUILDS_A_DAY, exc_info=True)


def _settle(cfg, today: str, at: datetime, ok: bool, what: str, *, skip=False, exc=None) -> None:
    """Record how today's build ended and route it (the module docstring's list)."""
    prev = _read_mark(cfg.state_dir)
    same = prev.get("day") == today
    tries = (_num(prev, "tries") if same else 0) + (0 if skip else 1)
    # Server days before today that ended without a table, since the last one with it.
    missed = _num(prev, "missed_days")
    if not same and prev.get("day") and not prev.get("ok") and not prev.get("skip") and _num(prev, "tries"):
        missed += 1
    warned = bool(prev.get("warned"))
    last_ok = f"{prev['last_ok_day']} 那天" if prev.get("last_ok_day") else "上次"
    mark = {"day": today, "ok": ok, "skip": skip, "tries": tries, "last_at": at.isoformat(timespec="seconds"),
            "what": what, "missed_days": missed, "warned": warned, "last_ok_day": prev.get("last_ok_day", "")}
    if skip:
        log.info("%s，需求表不重建", what)
    elif ok:
        log.info("需求表已重算并放上 COS：%s", what)
        if missed:
            log.warning("终末地「最新六星满练要多少」表今天重算成了；之前连着 %d 天没算成，App 库存页那几天用的是%s的表",
                        missed, last_ok, extra=errwatch.recovered())
        mark.update(missed_days=0, warned=False, last_ok_day=today)
    else:
        later = "过半小时再试一次" if tries < BUILDS_A_DAY else "明天再试"
        log.info("终末地「最新六星满练要多少」表今天第 %d 次没重算成：%s。App 库存页还用%s的表，%s",
                 tries, what, last_ok, later, exc_info=exc)
        techlog.add_red(today, "需求表没重算成", [f"终末地需求表今天第 {tries} 次没重算成：{what}"],
                        state_dir=cfg.state_dir, now=at)
        failed_days = missed + (1 if tries >= BUILDS_A_DAY else 0)
        if failed_days >= GROUP_AFTER_DAYS and not warned:
            log.warning("终末地「最新六星满练要多少」表已经连着 %d 个服务器日没重算成（这次：%s）。App 库存页一直用%s的表",
                        failed_days, what, last_ok)
            mark["warned"] = True
    _mark(cfg.state_dir, mark)


def _live_table(cfg) -> dict:
    from ark_relay.features.needtable import build  # noqa: PLC0415 - only this thread needs it
    return build.make(build.RulesSource(None, None, getattr(cfg, "skland_token", "") or ""))


def refresh(cfg, now: "datetime | None" = None, *, make=None, cos=None, put=cos_put) -> bool:
    """Build today's table and put it on COS. True when it is there. Never raises.
    `make` / `cos` / `put` are the tests' doors (no network)."""
    from ark_relay.features.needtable import build  # noqa: PLC0415
    at = now or datetime.now(SERVER_TZ)
    today = at.strftime("%Y-%m-%d")
    ended = (lambda: now or datetime.now(SERVER_TZ))   # noqa: E731 - when the attempt ended
    topic = (getattr(cfg, "phone_topic", "") or "").strip()
    cos = cos if cos is not None else state_cos(cfg)
    if not topic or cos is None:
        # Same as the state itself (Mailbox): without a topic or COS there is no App to read it.
        _settle(cfg, today, ended(), False, "这台机器没配手机信箱或腾讯云 COS", skip=True)
        return False
    if not (getattr(cfg, "skland_token", "") or "").strip():
        # The build reads the calculator with the machine's Skland token (build.RulesSource).
        _settle(cfg, today, ended(), False, "这台机器没配森空岛令牌（SKLAND_TOKEN）", skip=True)
        return False
    try:
        table = (make or (lambda: _live_table(cfg)))()
        data = json.dumps(table, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        summary = build.summary(table)    # read before the upload: a table it cannot read is a failed build
    except Exception as exc:  # noqa: BLE001 - whatever broke, today's table is not there; _settle logs the traceback
        _settle(cfg, today, ended(), False, str(exc) or type(exc).__name__, exc=exc)
        return False
    why = put(cos, need_key(topic), data, Mailbox.COS_TIMEOUT)
    if why:
        _settle(cfg, today, ended(), False, f"算好了，但放不上腾讯云（{why}）")
        return False
    _settle(cfg, today, ended(), True, summary)
    return True


def _run(cfg, now) -> None:
    try:
        refresh(cfg, now)
    finally:
        _running["ended"] = now or datetime.now(SERVER_TZ)


def step(cfg, now: "datetime | None" = None, *, start=None) -> bool:
    """The engine's tick step: start a build on its own thread when one is due and none
    is running, at most BUILDS_A_DAY a server day and SECOND_TRY_AFTER apart whatever
    the mark file says. True when one was started. `start` replaces the thread in tests."""
    at = now or datetime.now(SERVER_TZ)
    today = at.strftime("%Y-%m-%d")
    if not due(cfg.state_dir, today, at):
        return False
    with _lock:
        t = _running.get("thread")
        if t is not None and t.is_alive():
            return False
        if _running.get("day") != today:
            _running.update(day=today, count=0, ended=None)
        ended = _running.get("ended")
        if _running["count"] >= BUILDS_A_DAY or (ended is not None and at - ended < SECOND_TRY_AFTER):
            return False
        _running["count"] += 1
        _running["ended"] = None
        if start is not None:
            start(lambda: _run(cfg, now))
            return True
        t = _running["thread"] = threading.Thread(target=_run, args=(cfg, now), name="need-table", daemon=True)
        t.start()
    return True
