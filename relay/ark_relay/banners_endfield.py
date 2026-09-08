"""Endfield banners: Skland's char-pool, and Hypergryph's 版本更新说明 bulletin.

Split out of banners.py on 2026-09-08, moved verbatim. Its own module because
Endfield needs two sources to say anything at all: Skland is authoritative on
**when** a banner runs but leaves the character names empty (each one is a second
request), while the official bulletin is the only place that says **who is new** --
its 「全新干员」 section contains no reruns by construction, which is what makes it
usable as the debut criterion. Joining those two, and reading the next banner's
opening time out of the bulletin, is all specific to this game.

The 「全新干员」/「特许寻访」/「重构寻访」/「开放时间」 patterns below are **runtime data**:
they are what the bulletin literally says. Rewording one of them silently loses the
difference between a debut and a rerun.

Everything public here is re-exported from banners.py, so callers and tests still
write banners.xxx.
"""
from __future__ import annotations

import logging
import json
import re
from datetime import datetime

from .banners_common import (
    Banner,
    _UA_BROWSER,
    _first,
    _json,
    gh_raw,
    newest_version,
    upcoming,
)


# Same logger name as banners.py -- one feature, one name to grep. It is
# re-declared here instead of imported from banners_common because ruff's
# BLE001 only exempts a blind `except` that logs with exc_info=True when it
# can see the logger being created in the same file.
log = logging.getLogger("ark.banners")


# ── Endfield: official Skland API ──────────────────────────────
# chars[].name in char-pool is empty, so item/info has to be queried as well; the gid
# comes from what follows `gameEntryId=` in chars[].pcLink.
# This endpoint belongs to Endfield alone: passing ?gameId=1 still returns Endfield,
# and every /api/v1/game/arknights/* path 404s.
_SK_UP = "label_type_up"


def parse_endfield(pools: list, name_of) -> list[Banner]:
    """`pools` is char-pool's data.list; `name_of(gid)` returns a character name."""
    out: list[Banner] = []
    for p in pools:
        try:
            a = datetime.fromtimestamp(int(p["poolStartAtTs"]))
            b = datetime.fromtimestamp(int(p["poolEndAtTs"]))
        except (KeyError, TypeError, ValueError):
            continue
        names = []
        for c in p.get("chars") or []:
            if c.get("dotType") != _SK_UP:          # only the UP characters, not the filler
                continue
            gid = str(c.get("pcLink", "")).split("gameEntryId=")[-1]
            if gid.isdigit() and (nm := name_of(gid)):
                names.append(nm)
        if names:
            out.append(Banner("终末地", str(p.get("name") or ""),
                              tuple(names), a, b))
    out.sort(key=lambda x: x.start)
    return out


# The official 「版本更新说明」 bulletin gives the new operators and banner names for
# both halves of the version together, the same way the Wuthering Waves version
# bulletin does:
#     ■ 全新干员
#     6星干员【诀】【梨诺】
#     ■ 全新寻访及申领
#     1.「临渊望北」特许寻访 · ... 6星干员【诀】获取概率提升 ...
#     3.「晨星于此闪耀」特许寻访 · ... 6星干员【梨诺】获取概率提升 ...
# The 「全新干员」 section contains no reruns by construction, which is exactly what
# makes it usable as the debut criterion.
_EF_DEBUT_SEG = re.compile(r"全新干员(.{0,300}?)■", re.S)
# 6-stars only. The 2026-09-02 bulletin read 「6星干员【提弗洛斯】、5星干员【噗切娜】」
# -- 噗切娜 is a gifted 5-star that never appears on a banner at all, yet it got
# reported as the next banner.
# Set by the user: for Endfield and Arknights report only new limited 6-star UPs; for
# Wuthering Waves only 5-stars (its highest rarity).
_EF_SIX = re.compile(r"6星干员((?:【[^】]+】)+)")
_EF_BRACKET = re.compile(r"【([^】]+)】")
_EF_POOL = re.compile(r"「([^」]+)」特许寻访")
_EF_UP = re.compile(r"6星干员【([^】]+)】获取概率提升")


_EF_ANY_POOL = re.compile(r"「([^」]+)」(特许寻访|重构寻访#?\d*)")
_EF_OPEN = re.compile(r"开放时间[：:]\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})")


def parse_endfield_notice(html: str) -> "list[tuple[str, str]]":
    """Extract (operator, banner name) from the version update notes, in the order
    they appear in the bulletin. 6-star debuts only.
    """
    return [(n, pool) for n, pool, _, debut in endfield_pools_from_notice(html) if debut]


def endfield_pools_from_notice(html: str) -> "list[tuple[str, str, datetime | None, bool]]":
    """Every 6-star UP banner in the bulletin: (operator, banner name, opening time
    or None, is it a debut).

    The user, 2026-09-03: 「不要光顾着删卡池，你要补充预期卡池的角色」.
    From the 2026-09-02 bulletin: 「冬猎」 提弗洛斯 (debut, opens after the version
    update); 「绚丽异彩」 重构寻访#1 伊冯 (rerun, opens 2026/09/24 12:00).
    """
    txt = re.sub(r"<[^>]+>", " ", html or "").replace("&nbsp;", " ")
    txt = re.sub(r"\s+", " ", txt)
    seg = _EF_DEBUT_SEG.search(txt)
    debut = set(n for grp in _EF_SIX.findall(seg.group(1)) for n in _EF_BRACKET.findall(grp)) if seg else set()
    hits = list(_EF_ANY_POOL.finditer(txt))
    out: list[tuple[str, str, "datetime | None", bool]] = []
    seen: set[tuple[str, str]] = set()
    for k, m in enumerate(hits):
        tail = txt[m.end():hits[k + 1].start() if k + 1 < len(hits) else len(txt)]
        up = _EF_UP.search(tail)
        if not up:
            continue
        name, pool = up.group(1), m.group(1)
        if (name, pool) in seen:
            continue
        seen.add((name, pool))
        when = None
        if t := _EF_OPEN.search(tail):
            y, mo, d, hh, mm = (int(x) for x in t.groups())
            when = datetime(y, mo, d, hh, mm)
        out.append((name, pool, when, name in debut))
    return out


_ZONAI = "https://zonai.skland.com"
# Endfield's official bulletin aggregate endpoint, no token needed. code is a
# channel constant.
_EF_BULLETIN = ("https://game-hub.hypergryph.com/bulletin/v2/aggregate"
                "?lang=zh-cn&platform=Windows&channel=1&type=0"
                "&code=endfield_5SD9TN&hideDetail=0")
# The next banner across a version boundary exists only in this hand-maintained file.
# Its times are not trusted (see docs/BANNER-SOURCES.md); it is used only to get who
# the next character is.
_EF_SCHEDULE = gh_raw("Arknights-yituliu", "ef-frontend-v1", "main",
                      "custom/core/gacha/data/pool_info_table.json")


def _endfield(cred, sk_get, now: datetime
              ) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Running banners come from Skland (authoritative on timing); debuts and
    previews come from the official version bulletin.
    """
    try:
        pools = (sk_get("/web/v1/wiki/char-pool")["data"] or {}).get("list") or []
    except Exception:
        log.warning("森空岛卡池取不到", exc_info=True)
        return [], None

    def name_of(gid: str) -> str:
        try:
            item = ((sk_get(f"/web/v1/wiki/item/info?id={gid}")["data"] or {})
                    .get("item") or {})
            return item.get("name") or ""
        except Exception:  # noqa: BLE001
            return ""

    live = parse_endfield(pools, name_of)
    end = min((b.end for b in live), default=None)

    # Official bulletin: which new operators this version has, and on which banner
    html = ""
    debut: "list[tuple[str, str]]" = []
    notice_ok = True
    try:
        d = _json(_EF_BULLETIN, _UA_BROWSER, timeout=25)
        html = newest_version([
            (str(n.get("title") or ""),
             str(((n.get("data") or {}).get("html")) or ""))
            for n in ((d.get("data") or {}).get("list") or [])
            if "版本更新说明" in str(n.get("title") or "")])
        debut = parse_endfield_notice(html)
    except Exception:
        notice_ok = False
        log.warning("终末地官方公告取不到，这一版分不出首发和复刻", exc_info=True)

    names = {w for w, _ in debut}
    got = [b for b in live if set(b.chars) & names] if notice_ok else live
    if not end or end <= now:
        return got, None

    # Prefer the official bulletin for the next banner: the one whose opening time is
    # in the future (reruns are reported too, labelled as such)
    on = {c for b in live for c in b.chars}
    try:
        pools = endfield_pools_from_notice(html) if notice_ok else []
    except Exception:  # noqa: BLE001
        pools = []
    future = [(n, p, w, d) for n, p, w, d in pools if w and w > now and n not in on]
    if future:
        n, p, w, d = min(future, key=lambda x: x[2])
        return got, (w, f"{n}「{p}」" + ("" if d else "（复刻）"))
    rest = upcoming(debut, on)
    if rest:
        return got, (end, "、".join(f"{w}「{p}」" if p else w for w, p in rest))

    # Both halves of this version have finished; only Yituliu's hand-maintained table
    # covers the next version
    try:
        table = json.loads(_first(_EF_SCHEDULE, _UA_BROWSER))
    except Exception:
        log.warning("一图流终末地排期取不到（几条镜像都不通）", exc_info=True)
        return got, (end, "")
    seen = {b.name for b in live} | {p for _, p in debut}
    nxt = next((r for r in (table if isinstance(table, list) else [])
                if str(r.get("poolName") or "") not in seen
                and _ef_after(r, now)), None)
    if not nxt:
        return got, (end, "")
    who = str(nxt.get("character") or "") or str(nxt.get("poolName") or "")
    pool = str(nxt.get("poolName") or "")
    label = f"{who}「{pool}」" if pool and pool != who else who
    return got, (end, f"{label}（排期是别人手工维护的，未官宣）")


def _ef_after(row: dict, now: datetime) -> bool:
    try:
        return datetime.strptime(str(row.get("poolStart") or ""),
                                 "%Y/%m/%d %H:%M:%S") > now
    except (ValueError, TypeError):
        return False
