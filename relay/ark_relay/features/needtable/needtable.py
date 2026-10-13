"""The App's need table, rebuilt by the relay once a server day and put on COS.

The 库存 page of the App (ark-remote Inventory.swift) shows the stock against what the
newest six-star's full build needs. That table was built by hand on the Mac
(scripts/mac/build-need-tables.py) and published with the phone page; the last run was
2026-09-23, so 祀 and 明河 (in the wiki since October) never reached it. The cause was
the process: a person had to notice a new six-star and rerun it, and again once the
calculator listed her. Here the relay does it on the first tick of each server day
(engine.Engine._need_table), with its own Skland token, and PUTs the result next to the
phone state: `state/<the state's hash>.need.json`, public-read like the state (the App has
no COS keys), the App derives the same name (Relay.needURL) and falls back to the old
GitHub Pages copy when it is not there. The bucket's 30-day rule (expire-30d-not-relay)
covers state/; a daily PUT keeps it, and only a machine silent for 30 days loses it.

One build is about 115 Skland requests, 55 s from the Mac (measured 2026-10-14), so it
runs on a thread of its own and the tick never waits for it. A day's build that fails
is one WARNING (pushed, like every other failed Skland read: banners.collect); the next
try is the next server day. The App's 库存 footer says on which day the table was built,
so a table that stopped being rebuilt shows there too.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from ark_relay.core.config import SERVER_TZ, atomic_write_text
from ark_relay.features.phone.cos_store import cos_put, state_cos, state_key
from ark_relay.features.phone.mailbox import Mailbox

log = logging.getLogger("ark.needtable")

MARK = "needtable.json"
_lock = threading.Lock()
# The build thread of this process, if one was started (step); a dict, not a rebound global.
_running: "dict[str, threading.Thread]" = {}


def need_key(topic: str) -> str:
    """`state/<same hash as the state>.need.json`; built from state_key so the names cannot drift apart."""
    return state_key(topic)[:-len(".json")] + ".need.json"


def _read_mark(state_dir) -> dict:
    try:
        return json.loads((state_dir / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def due(state_dir, today: str) -> bool:
    """True until today's build has finished (worked or not)."""
    return _read_mark(state_dir).get("day") != today


def _mark(state_dir, today: str, ok: bool, what: str) -> None:
    try:
        atomic_write_text(state_dir / MARK, json.dumps(
            {"day": today, "ok": ok, "at": datetime.now(SERVER_TZ).isoformat(timespec="seconds"), "what": what},
            ensure_ascii=False))
    except OSError:
        log.info("需求表的当天记号写不进去，下一轮会再建一次", exc_info=True)


def _live_table(cfg) -> dict:
    from ark_relay.features.needtable import build  # noqa: PLC0415 - only this thread needs it
    return build.make(build.RulesSource(None, None, getattr(cfg, "skland_token", "") or ""))


def refresh(cfg, now: "datetime | None" = None, *, make=None, cos=None, put=cos_put) -> bool:
    """Build today's table and put it on COS. True when it is there. Never raises.
    `make` / `cos` / `put` are the tests' doors (no network)."""
    from ark_relay.features.needtable import build  # noqa: PLC0415
    today = (now or datetime.now(SERVER_TZ)).strftime("%Y-%m-%d")
    topic = (getattr(cfg, "phone_topic", "") or "").strip()
    cos = cos if cos is not None else state_cos(cfg)
    if not topic or cos is None:
        # Same as the state itself (Mailbox): without a topic or COS there is no App to read it.
        log.info("这台机器没配手机信箱或腾讯云 COS，需求表不重建")
        _mark(cfg.state_dir, today, False, "no topic / COS")
        return False
    try:
        table = (make or (lambda: _live_table(cfg)))()
        data = json.dumps(table, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except Exception as exc:  # whatever broke, today's table is not there
        log.warning("终末地「最新六星满练要多少」表今天没重算成：%s。App 库存页还用上次的表，明天再试",
                    str(exc) or type(exc).__name__, exc_info=True)
        _mark(cfg.state_dir, today, False, str(exc) or type(exc).__name__)
        return False
    why = put(cos, need_key(topic), data, Mailbox.COS_TIMEOUT)
    if why:
        log.warning("终末地「最新六星满练要多少」表算好了，但放不上腾讯云（%s）。App 库存页还用上次的表，明天再试", why)
        _mark(cfg.state_dir, today, False, why)
        return False
    what = build.summary(table)
    log.info("需求表已重算并放上 COS：%s", what)
    _mark(cfg.state_dir, today, True, what)
    return True


def step(cfg, now: "datetime | None" = None, *, start=None) -> bool:
    """The engine's tick step: start today's build on its own thread when it is due and
    none is running. True when one was started. `start` replaces the thread in tests."""
    today = (now or datetime.now(SERVER_TZ)).strftime("%Y-%m-%d")
    if not due(cfg.state_dir, today):
        return False
    with _lock:
        t = _running.get("thread")
        if t is not None and t.is_alive():
            return False
        if start is not None:
            start(lambda: refresh(cfg, now))
            return True
        t = _running["thread"] = threading.Thread(target=refresh, args=(cfg, now), name="need-table", daemon=True)
        t.start()
    return True
