"""The three games' live stamina for the phone page: sanity (Arknights, Skland),
sanity (Endfield, Skland card detail `dungeon`), waveplate / backup stamina /
weekly-boss claims (Wuthering Waves, Kuro BBS `baseData`). Read-only, the
operator's own accounts.

Why this exists: the status tab's number tiles (docs/PHONE-NATIVE-REFERENCES.md,
Reminders' 2×2 tiles). The user, 2026-09-15: 「当前理智/波片走token，三个游戏你都有接口」.

Every source is fetched at most once per TTL; the phone snapshot is built often
(boot, every phone order, every refresh) and none of these numbers move faster
than a few minutes. A source that fails answers with an error field and never sinks
the snapshot. Field names are Chinese because the phone shows them verbatim.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

log = logging.getLogger("ark.resources")

TTL_SECONDS = 600
_TIMEOUT = 12

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": {}}
_session: dict = {"cred": None}   # Skland creds are rate-limited at creation; keep one

KURO_MAIN = "https://api.kurobbs.com"
KURO_UA = ("Mozilla/5.0 (Linux; Android 16; 25098PN5AC Build/BP2A.250605.031.A3; wv) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/143.0.7499.34 "
           "Mobile Safari/537.36 Kuro/3.0.0 KuroGameBox/3.0.0")
KURO_GAME_ID = 3


def _stamp(ts: int | float | None) -> str:
    """Epoch seconds -> 'MM-DD HH:MM' on the machine's clock, '' when absent."""
    if not ts:
        return ""
    try:
        from .config import SERVER_TZ  # noqa: PLC0415
        return datetime.fromtimestamp(int(ts), tz=SERVER_TZ).strftime("%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


# ---------------------------------------------------------------- Skland

def _skland(cfg) -> tuple[dict, dict]:
    """(Arknights, Endfield) from one Skland session."""
    from . import skland  # noqa: PLC0415
    if not getattr(cfg, "skland_token", ""):
        return {"错误": "没配森空岛 token"}, {"错误": "没配森空岛 token"}
    if _session["cred"] is None:
        _session["cred"] = skland.login(cfg.skland_token, skland.get_did())
    try:
        binds = skland.bindings(_session["cred"])
    except Exception:  # noqa: BLE001 - a cred is only good for a while; one fresh cred, one retry
        _session["cred"] = skland.login(cfg.skland_token, skland.get_did())
        binds = skland.bindings(_session["cred"])
    cred = _session["cred"]
    ak: dict = {}
    ef: dict = {}
    uid = next((r.get("uid") for app in binds if app.get("appCode") == "arknights"
                for r in app.get("bindingList", [])), None)
    if uid:
        try:
            r = skland.get(cred, f"/api/v1/game/player/info?uid={uid}")
            ap = ((r.get("data") or {}).get("status") or {}).get("ap") or {}
            ak = {"理智": ap.get("current"), "上限": ap.get("max"),
                  "回满": _stamp(ap.get("completeRecoveryTime"))}
        except Exception as exc:  # noqa: BLE001
            ak = {"错误": f"{type(exc).__name__}: {exc}"[:120]}
    else:
        ak = {"错误": "森空岛账号下没绑明日方舟"}
    try:
        card = skland.endfield_card(cred)
        dg = ((card.get("data") or {}).get("detail") or {}).get("dungeon") or {}
        ef = endfield_from_dungeon(dg)
    except Exception as exc:  # noqa: BLE001
        ef = {"错误": f"{type(exc).__name__}: {exc}"[:120]}
    return ak, ef


def endfield_from_dungeon(dg: dict) -> dict:
    """`detail.dungeon` = current stamina, cap, full-recovery time (otae-bot's API notes); the
    exact key names are not documented, so match on meaning: the two integer
    fields whose names carry ap/sanity, smaller = current, larger = max, and any
    field that looks like a recovery time."""
    if not dg:
        return {"错误": "森空岛没给终末地的理智"}
    nums = {k: v for k, v in dg.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
            and any(t in k.lower() for t in ("ap", "sanity", "stamina", "energy", "power"))}
    when = next((v for k, v in dg.items() if any(t in k.lower() for t in ("recover", "full", "complete"))), None)
    if not nums:
        return {"错误": "终末地的理智没认出来，森空岛给的是：" + "、".join(list(dg)[:6])}
    small = [v for k, v in nums.items() if "max" not in k.lower() and "limit" not in k.lower()]
    big = [v for k, v in nums.items() if "max" in k.lower() or "limit" in k.lower()]
    cur = min(small) if small else None
    top = max(big) if big else (max(nums.values()) if len(nums) > 1 else None)
    out = {"理智": cur, "上限": top}
    if isinstance(when, (int, float)) and when > 1e9:
        out["回满"] = _stamp(when)
    return out


# ---------------------------------------------------------------- Kuro BBS

def _kuro_post(path: str, headers: dict, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    head = {"source": "android", "version": "3.1.3", "User-Agent": KURO_UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
    head.update(headers)
    req = urllib.request.Request(KURO_MAIN + path, data=body, headers=head, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _kuro_need(resp: dict, what: str):
    if not resp.get("success") or resp.get("code") != 200:
        raise RuntimeError(f"{what}：{resp.get('msg') or resp.get('message') or resp.get('code')}")
    data = resp.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            pass
    return data


def _wuwa(cfg) -> dict:
    token, did = getattr(cfg, "kurobbs_token", ""), getattr(cfg, "kurobbs_did", "")
    if not token or not did:
        return {"错误": "没配库街区 token/did"}
    roles = _kuro_need(_kuro_post("/gamer/role/list", {"token": token, "devCode": did},
                                  {"gameId": KURO_GAME_ID}), "取角色")
    w = next((r for r in roles if int(r.get("gameId", 0)) == KURO_GAME_ID), None)
    if not w:
        return {"错误": "库街区账号下没有鸣潮角色"}
    role_id, server_id = str(w["roleId"]), w.get("serverId") or ""
    bat = _kuro_need(_kuro_post("/aki/roleBox/requestToken", {"token": token, "did": did, "b-at": ""},
                                {"serverId": server_id, "roleId": role_id}), "换数据令牌")["accessToken"]
    d = _kuro_need(_kuro_post("/aki/roleBox/akiBox/baseData", {"did": did, "b-at": bat},
                              {"gameId": KURO_GAME_ID, "serverId": server_id, "roleId": role_id}), "取基础数据")
    return wuwa_from_base(d)


def wuwa_from_base(d: dict) -> dict:
    """Kuro `baseData` (real sample 2026-09-15 01:15): energy 232 / maxEnergy 240,
    storeEnergy 44 / storeEnergyLimit 480 (backup stamina), weeklyInstCount 0 / 3
    (weekly boss claims), liveness 0 / 100."""
    return {"波片": d.get("energy"), "上限": d.get("maxEnergy"),
            "备用": d.get("storeEnergy"), "备用上限": d.get("storeEnergyLimit"),
            "周本": d.get("weeklyInstCount"), "周本上限": d.get("weeklyInstCountLimit"),
            "活跃": d.get("liveness"), "活跃上限": d.get("livenessMaxCount")}


# ---------------------------------------------------------------- entry

def fetch(cfg, *, force: bool = False) -> dict:
    """The phone's resources block. Cached TTL_SECONDS; never raises."""
    with _lock:
        if not force and _cache["data"] and time.time() - _cache["at"] < TTL_SECONDS:
            return _cache["data"]
        out: dict = {}
        try:
            out["明日方舟"], out["终末地"] = _skland(cfg)
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}"[:120]
            out["明日方舟"] = {"错误": msg}
            out["终末地"] = {"错误": msg}
        try:
            out["鸣潮"] = _wuwa(cfg)
        except Exception as exc:  # noqa: BLE001
            out["鸣潮"] = {"错误": f"{type(exc).__name__}: {exc}"[:120]}
        from .config import SERVER_TZ  # noqa: PLC0415
        out["取自"] = datetime.now(tz=SERVER_TZ).strftime("%H:%M")
        for g, v in out.items():
            if isinstance(v, dict) and v.get("错误"):
                log.info("资源：%s 读不到：%s", g, v["错误"])
        _cache["at"], _cache["data"] = time.time(), out
        return out


def today(state, day: str) -> dict:
    """Today's run count and failure count, from the day's ledger (core.State.read_ledger)."""
    try:
        entries = state.read_ledger(day)
    except Exception:  # noqa: BLE001
        return {}
    return {"跑了": len(entries), "失败": sum(1 for e in entries if not e.get("ok")),
            "最近": (entries[-1].get("script") if entries else "")}
