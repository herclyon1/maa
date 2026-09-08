"""Wuthering Waves banners: the Kuro BBS wiki homepage, and the in-game bulletin.

Split out of banners.py on 2026-09-08, moved verbatim. Its own module because both
of its sources are shaped unlike the other two games': the wiki homepage is a POST
that needs three fixed headers and hands back a nested contentJson whose character
ids each need a second POST, and the bulletin is a single JSON file on the game CDN
addressed by a channel hash. It is also the only game where the publisher announces
**who** comes next, which is why the bulletin is fetched first here -- its 「全新角色」
section is the only thing that tells a debut from a rerun.

The 「唤取」/「角色」 module titles and the 「5星共鸣者」/「角色活动唤取」 patterns below are
**runtime data**: they are what the pages actually say, measured 2026-08-30/31.

Everything public here is re-exported from banners.py, so callers and tests still
write banners.xxx.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import datetime

from .banners_common import (
    Banner,
    _UA_BROWSER,
    _json,
    newest_version,
    upcoming,
)


# Same logger name as banners.py -- one feature, one name to grep. It is
# re-declared here instead of imported from banners_common because ruff's
# BLE001 only exempts a blind `except` that logs with exc_info=True when it
# can see the logger being created in the same file.
log = logging.getLogger("ark.banners")


# ── Wuthering Waves: the Kuro BBS wiki homepage (no token) ─────
# POST /wiki/core/homepage/getPage with just three fixed headers.
# In data.contentJson.sideModules[], the modules whose title contains 「角色…唤取」;
# their content.tabs[] are the banners running concurrently:
#   tab.name                        banner name
#   tab.countDown.dateRange         ["2026-08-20 11:00", "2026-09-10 09:59"]
#   tab.imgs[0].linkConfig.entryId  character entry id
# **The imgs after the first are the same generic entries in every tab; only the
# first one is the character.**
# Weapon banners are not reported.
def parse_wuwa(home: dict, name_of) -> list[Banner]:
    out: list[Banner] = []
    content = ((home or {}).get("data") or {}).get("contentJson") or {}
    for m in content.get("sideModules") or []:
        title = str(m.get("title") or "")
        if "唤取" not in title or "角色" not in title:
            continue
        for tab in (m.get("content") or {}).get("tabs") or []:
            dr = (tab.get("countDown") or {}).get("dateRange") or []
            if len(dr) != 2:
                continue
            try:
                a = datetime.strptime(f"{dr[0]}:00", "%Y-%m-%d %H:%M:%S")
                b = datetime.strptime(f"{dr[1]}:59", "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            imgs = tab.get("imgs") or []
            eid = (imgs[0].get("linkConfig") or {}).get("entryId") if imgs else None
            who = name_of(str(eid)) if eid else ""
            if not who:
                continue
            out.append(Banner("鸣潮", str(tab.get("name") or ""), (who,), a, b))
    out.sort(key=lambda x: x.end)
    return out


# The 「全新角色」 section in the body of the official bulletin has a fixed format:
#     5星共鸣者「景燃」（热熔 | 长刃）
#     ...
#     ※可通过[身赴三途]角色活动唤取获得。
_WW_ROLE = re.compile(r"5星共鸣者[「\[]([^」\]]+)[」\]]")
_WW_POOL = re.compile(r"可通过[\[「]([^\]」]+)[\]」]角色活动唤取")


def parse_wuwa_preview(content: str) -> "list[tuple[str, str]]":
    """Extract (character, banner name) from the version bulletin body.

    Only the 「全新角色」 section is sliced out, and reruns are not in it.
    """
    text = re.sub(r"<[^>]+>", "", content or "").replace("&nbsp;", "")
    i = text.find("全新角色")
    if i < 0:
        return []
    j = text.find("全新武器", i)
    seg = text[i:j if j > 0 else len(text)]
    hits = list(_WW_ROLE.finditer(seg))
    out: "list[tuple[str, str]]" = []
    for k, m in enumerate(hits):
        tail = seg[m.end():hits[k + 1].start() if k + 1 < len(hits) else len(seg)]
        pool = _WW_POOL.search(tail)
        out.append((m.group(1), pool.group(1) if pool else ""))
    return out


_KURO = "https://api.kurobbs.com"

# This hash is a channel constant and does not change with the version; if it ever
# does stop working, read metadata.source_url from data/ww/game/notice.json in
# 555me/game-CDN-List.
_WW_NOTICE = ("https://aki-gm-resources-back.aki-game.com/gamenotice/G152/"
              "76402e5b20be2c39f095a152090afddc/zh-Hans.json")
_WW_HDR = {"wiki_type": "9", "source": "h5",
           "referer": "https://wiki.kurobbs.com/"}


def _wuwa(now: datetime) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Current banners come from the wiki homepage, the next one from the official
    bulletin. Neither needs a token.
    """
    def post(path, payload=None):
        # data must not be None, or urllib sends a GET -- these two endpoints only
        # accept POST.
        h = dict(_WW_HDR)
        body = b""
        if payload is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
            body = urllib.parse.urlencode(payload).encode()
        return _json(_KURO + path, _UA_BROWSER, body, h)

    cache: dict[str, str] = {}

    def name_of(eid: str) -> str:
        if eid not in cache:
            try:
                d = post("/wiki/core/catalogue/item/getEntryDetail",
                         {"id": eid})["data"] or {}
                cache[eid] = str(d.get("name") or "")
            except Exception:
                log.warning("库街区条目 %s 查不到名字", eid, exc_info=True)
                cache[eid] = ""
        return cache[eid]

    # Fetch the bulletin first: its 「全新角色」 section is the only authoritative basis
    # for telling a debut from a rerun. getPage gives only the banners and says nothing
    # about who is new; of the two banners in the first half of 3.6, 达妮娅 was a rerun.
    debut: "list[tuple[str, str]]" = []
    notice_ok = True
    try:
        notice = _json(_WW_NOTICE, _UA_BROWSER, timeout=25)
        body = newest_version([(str(n.get("tabTitle") or ""),
                                str(n.get("content") or ""))
                               for n in (notice.get("game") or [])
                               if "版本内容说明" in str(n.get("tabTitle") or "")])
        debut = parse_wuwa_preview(body)
    except Exception:
        notice_ok = False
        log.warning("鸣潮官方公告取不到，这一版分不出首发和复刻", exc_info=True)

    try:
        home = post("/wiki/core/homepage/getPage")
    except Exception:
        log.warning("库街区首页取不到", exc_info=True)
        return [], None
    pools = parse_wuwa(home, name_of)
    end = min((b.end for b in pools), default=None)

    # If the bulletin cannot be fetched, better to report one extra rerun than to lose
    # the countdown entirely -- the banners within a version all end at the same time
    # anyway, and the value of this line is mostly in that moment.
    names = {w for w, _ in debut}
    got = [b for b in pools if set(b.chars) & names] if notice_ok else pools

    if not end or end <= now:
        return got, None
    live = {c for b in pools for c in b.chars}
    rest = upcoming(debut, live)
    if not rest:
        return got, (end, "")
    who = "、".join(f"{w}「{p}」" if p else w for w, p in rest)
    return got, (end, who)
