"""What the phone page needs to read the games' stamina **itself** (web/stamina.js
asks 森空岛 and 库街区 straight from the browser - both APIs answer cross-origin;
measured 2026-09-15). The user, 2026-09-15: 「你直接在网页上调取理智数」.

The one thing a browser cannot do is Skland's token -> code -> cred exchange
(as.hypergryph.com sends no CORS headers), so the relay does that once per
process with the SKLAND_TOKEN it already holds and puts the resulting session
(cred, signing token, device id, the account ids) into the phone snapshot -
the same PIN-sealed channel that carries the config. The page stores it and
signs its own requests from then on. Today's run count comes from the ledger.
Nothing here runs on a timer.
"""
from __future__ import annotations

import logging
import time

from ark_relay.core.ledger import manual_stop

log = logging.getLogger("ark.resources")

# today() runs on every phone-state publish and a WARNING is a group message:
# an unreadable ledger is said once per condition (as WeeklyBossGate._last_error),
# forgotten once it reads again.
_last_error: dict[str, str] = {}

_session: dict = {"sk": None}     # Skland creates creds sparingly; one per process
# What the machine check #10 reads (machinechecks/phone_banners.py): when this
# process made the session, and Endfield's stamina block as Skland gave it to the
# same session - the keys web/stamina.js endfieldFromDungeon reads first
# (curStamina / maxStamina / maxTs). Never credentials.
_probe: dict = {"p": {}}    # one slot, replaced whole (see _probe_stamina)


def probe() -> dict:
    """{"at": unix time the session was made, "dungeon": {...}} or {"at", "错误": why};
    {} before any session (or after one failed)."""
    return dict(_probe["p"])


def _probe_stamina(skland, cred, sk: dict) -> None:
    """One read of card/detail with the session just made, kept for the check #10.

    Built aside and published by one assignment, so a reader never sees 「at」 without
    its outcome.
    The boot push and the 停止前 push can both make a session at the same moment (a stop
    7 s after boot, 2026-10-10 16:32:53); when this cleared the probe and then waited on
    Skland, #10 read the half-made one and pushed 「终末地体力没读到：没读」. Not a lock
    around the session: the 停止前 push has its own short Skland time-outs
    (app_main.stop_push) and must not wait on the boot push's."""
    p: dict = {"at": time.time()}
    if not sk.get("efRole"):
        p["错误"] = "会话里没有终末地的角色"
    else:
        try:
            card = skland.endfield_card(cred, sk["efRole"], sk.get("efServer") or "")
            dg = (card.get("detail") or {}).get("dungeon") if isinstance(card, dict) else None
            if isinstance(dg, dict):
                p["dungeon"] = {str(k): v for k, v in dg.items()}
            else:
                p["错误"] = f"森空岛的终末地详情里没有 detail.dungeon（有：{sorted(card)[:8] if isinstance(card, dict) else card}）"
        except Exception as exc:  # noqa: BLE001 - the check says it; the tile reads on its own
            p["错误"] = f"{type(exc).__name__}: {exc}"[:160]
            log.info("终末地体力没读到：%s", p["错误"])
    _probe["p"] = p     # one store: probe() sees the old result or the new one, never a mix


def skland_session(cfg) -> dict:
    """{cred, token, dId, uid, efRole, efServer} for the page, or {"错误": ...}."""
    from ark_relay.core import skland  # noqa: PLC0415
    if not getattr(cfg, "skland_token", ""):
        return {"错误": "没配森空岛 token"}
    try:
        if _session["sk"] is None:
            did = skland.get_did()
            cred = skland.login(cfg.skland_token, did)
            cred = skland.refresh(cred)
            sk = {"cred": cred.cred, "token": cred.token, "dId": did}
            for app in skland.bindings(cred):
                if app.get("appCode") == "arknights":
                    for b in app.get("bindingList", []):
                        if b.get("uid") and "uid" not in sk:
                            sk["uid"] = str(b["uid"])
            # Endfield wants roles[].roleId / serverId - uid + channelMasterId only earn a 403
            try:
                sk["efRole"], sk["efServer"] = skland.endfield_role(cred)
            except skland.SklandMultiRole as exc:
                # Refused rather than guessed (skland.endfield_role): a refusal the
                # group hears of (errwatch, extra=alarm), once per session made.
                from ark_relay.features.alarm import errwatch  # noqa: PLC0415
                from ark_relay.core import texts  # noqa: PLC0415
                log.warning("终末地角色不止一个，没有读：%s", exc,
                            extra=errwatch.alarm(texts.SKLAND_MULTI_ROLE,
                                                 texts.skland_multi_role_body([r for r, _ in exc.roles])))
            except Exception as exc:  # noqa: BLE001 - the tile says so, and the group hears it
                # Once per session made (a session is kept until it fails): the account
                # has an Endfield role, so not finding it is a fault, not a state.
                log.warning("终末地角色没找到：%s", exc)
            _probe_stamina(skland, cred, sk)
            _session["sk"] = sk
            _session.pop("failed", None)
        return dict(_session["sk"])
    except Exception as exc:  # noqa: BLE001 - the page shows the reason in the tile
        _session["sk"] = None
        _probe["p"] = {}
        msg = f"{type(exc).__name__}: {exc}"[:120]
        # A WARNING (the group) for each new reason; the same reason again on the next
        # state publish is the same outage, not a new fault. Reset once a session is made.
        if _session.get("failed") != msg:
            log.warning("森空岛会话给不了手机页：%s", msg)
        _session["failed"] = msg
        return {"错误": msg}


def today(state, day: str) -> dict:
    """Today's run count and failure count, from the day's ledger (core.State.read_ledger)."""
    try:
        entries = state.read_ledger(day)
    except Exception as exc:  # noqa: BLE001
        # No counts: the App would show 0 failures today as a fact.
        why = f"{type(exc).__name__}: {exc}"
        if _last_error.get("ledger") != why:
            log.warning("今天的账本读不到（%s），手机上今天跑了几趟、失败几趟这次不报", why)
            _last_error["ledger"] = why
        return {"错误": f"账本读不到：{why}"[:120]}
    _last_error.pop("ledger", None)
    # A run the red button (停一切) cut short is neither a success nor a failure
    # (ledger.manual_stop), so it is counted as neither.
    return {"跑了": len(entries),
            "失败": sum(1 for e in entries
                      if not e.get("ok") and not manual_stop(e)),
            "最近": (entries[-1].get("script") if entries else "")}
