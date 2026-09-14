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

log = logging.getLogger("ark.resources")

_session: dict = {"sk": None}     # Skland creates creds sparingly; one per process


def skland_session(cfg) -> dict:
    """{cred, token, dId, uid, efRole, efServer} for the page, or {"错误": ...}."""
    from . import skland  # noqa: PLC0415
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
            except Exception as exc:  # noqa: BLE001 - no Endfield binding: the tile says so
                log.info("终末地角色没找到：%s", exc)
            _session["sk"] = sk
        return dict(_session["sk"])
    except Exception as exc:  # noqa: BLE001 - the page shows the reason in the tile
        _session["sk"] = None
        msg = f"{type(exc).__name__}: {exc}"[:120]
        log.info("森空岛会话给不了手机页：%s", msg)
        return {"错误": msg}


def today(state, day: str) -> dict:
    """Today's run count and failure count, from the day's ledger (core.State.read_ledger)."""
    try:
        entries = state.read_ledger(day)
    except Exception:  # noqa: BLE001
        return {}
    return {"跑了": len(entries), "失败": sum(1 for e in entries if not e.get("ok")),
            "最近": (entries[-1].get("script") if entries else "")}
