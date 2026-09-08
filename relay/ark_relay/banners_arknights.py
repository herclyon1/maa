"""Arknights banners: PRTS 卡池一览, the official site's 寻访 posts, Yituliu's schedule.

Split out of banners.py on 2026-09-08, moved verbatim. Its own module because
Arknights is the one game whose banners are read out of a wiki table rather than an
API: the parsing is wikitext, the rarity of every operator has to be looked up one
page at a time, and the next banner comes from three different places in order of
trustworthiness (the official 「寻访即将开启」 post, then PRTS's own future rows, then
a hand-maintained schedule in the Yituliu frontend repo). None of that has a
counterpart in the other two games.

The wikitext patterns, 「干员头像」/「稀有度」 field names and 「寻访」/「开启」 title words
below are **runtime data**: they are what the pages actually say. Rewording one of
them makes the Arknights lines quietly disappear from the report.

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
    _UA_PLAIN,
    _first,
    _json,
    _text,
    debut_only,
    gh_raw,
)


# Same logger name as banners.py -- one feature, one name to grep. It is
# re-declared here instead of imported from banners_common because ruff's
# BLE001 only exempts a blind `except` that logs with exc_info=True when it
# can see the logger being created in the same file.
log = logging.getLogger("ark.banners")


# ── Arknights: PRTS ────────────────────────────────────────────
# One row looks like this (as observed):
#   |[[文件:X.jpg|400px|link=Y]]<br/>[[Y|【限定寻访·夏季】车辙与风的归所]]
#   |2026-08-01 12:00~<br/>2026-08-15 03:59
#   |{{干员头像|予愿安洁莉娜|limited=1}}{{干员头像|珊比}}
_AK_TIME = re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d)\s*~\s*<br\s*/?>\s*"
                      r"(\d{4}-\d\d-\d\d \d\d:\d\d)")
# Both spellings must be recognised: [[page|shown]] and [[page]]; image links are
# skipped.
_AK_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_AK_FILE = re.compile(r"^(?:文件|File):", re.I)
_AK_CHAR = re.compile(r"\{\{干员头像\|([^|}]+)")


def parse_arknights(wt: str) -> list[Banner]:
    """Parse the PRTS banner table.

    The table is newest-first; this returns entries in chronological order.
    """
    out: list[Banner] = []
    for row in wt.split("\n|-"):
        m = _AK_TIME.search(row)
        if not m:
            continue
        name = ""
        for target, shown in _AK_LINK.findall(row):
            if _AK_FILE.match(target.strip()):
                continue
            name = (shown or target).strip()
        if not name:
            continue
        chars = tuple(dict.fromkeys(c.strip() for c in _AK_CHAR.findall(row)))
        try:
            a = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
            b = datetime.strptime(m.group(2), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        out.append(Banner("明日方舟", name, chars, a, b))
    out.sort(key=lambda x: x.start)
    return out


# urlencode leaves the string ending in "&page=", exactly right for appending the page
# title. Before 2026-08-31 there was a stray [:-6] here that chopped "&page=" off
# entirely, turning the request into ...&format=json卡池一览/限时寻访 -- PRTS returned
# a page of HTML, parsing blew up every time, two WARNINGs landed in the log with
# every daily report, and the Arknights lines never appeared at all.
_PRTS = "https://prts.wiki/api.php?" + urllib.parse.urlencode(
    {"action": "parse", "prop": "wikitext", "format": "json", "page": ""})

# This one page is enough. Verified 2026-08-31: the 「卡池一览/常驻标准寻访」 page is
# the **operator rotation pool**, its table has a different structure (index / banner
# page / opening time, with no banner name) and always parses to zero rows; and every
# operator on it -- 提丰, 引星棘刺, 逻各斯, 鸿雪, 衡沙 -- can be traced to an earlier
# debut in the limited banners, so the rotation pool never contains a newcomer.
# If Arknights ever really debuts an operator on another page, add that page back
# here.
_AK_PAGES = ("卡池一览/限时寻访",)

# The next banner's schedule: the publisher does not announce it, and PRTS only
# records banners that have already run. Someone hand-maintains a future schedule in
# the Yituliu frontend repo; `accuracyFlag: false` marks an entry as a prediction
# rather than an official announcement.
_AK_SCHEDULE = gh_raw("Arknights-yituliu", "frontend-v2-plus", "main",
                      "src/utils/gachaScheduleOptions.js")


def parse_ak_schedule(js: str) -> "list[tuple[str, datetime, bool]]":
    """Yituliu's schedule array -> [(banner name, start date, officially announced)],
    in chronological order.
    """
    out: "list[tuple[str, datetime, bool]]" = []
    for m in re.finditer(r"\{([^{}]*)\}", js or ""):
        blk = m.group(1)
        name = re.search(r'name:\s*"([^"]+)"', blk)
        start = re.search(r'startDate:\s*"(\d{4}-\d\d-\d\d)"', blk)
        if not name or not start or re.search(r"disabled:\s*true", blk):
            continue
        out.append((name.group(1),
                    datetime.strptime(start.group(1), "%Y-%m-%d"),
                    not re.search(r"accuracyFlag:\s*false", blk)))
    out.sort(key=lambda x: x[1])
    return out


_AK_RARITY = re.compile(r"稀有度\s*=\s*(\d)")
_rarity_cache: dict[str, int] = {}


def ak_rarity(name: str, fetch=None) -> int:
    """The rarity field on a PRTS operator page, **counted from 0** (5 = six-star,
    verified 2026-09-03 against 予愿安洁莉娜).

    Returns -1 when it cannot be fetched. Only the names currently running are looked
    up, and each name is cached for the life of the process.
    """
    if name in _rarity_cache:
        return _rarity_cache[name]
    try:
        wt = (fetch or (lambda n: _json(_PRTS + urllib.parse.quote(n), _UA_PLAIN)["parse"]["wikitext"]["*"]))(name)
        m = _AK_RARITY.search(wt or "")
        r = int(m.group(1)) if m else -1
    except Exception:  # noqa: BLE001
        r = -1
    _rarity_cache[name] = r
    return r


def six_star_only(b: Banner, fetch=None) -> Banner:
    """Keep only six-stars on Arknights banners (set by the user).

    A name whose rarity cannot be looked up is **dropped**, never faked.
    """
    keep = tuple(c for c in b.chars if ak_rarity(c, fetch) == 5)
    return Banner(b.game, b.name, keep, b.start, b.end)


_AK_NEWS = "https://ak.hypergryph.com/news"
_AK_NEWS_ITEM = re.compile(r'\\"cid\\":\\"(\d+)\\",\\"tab\\":\\"\w+\\",\\"sticky\\":(?:true|false),\\"title\\":\\"([^"\\]+)\\",\\"author\\":\\"[^"\\]*\\",\\"displayTime\\":(\d+)')
_AK_SIX_LINE = re.compile(r"★{6}[：:]\s*([^（(★]+)")
_AK_SPAN = re.compile(r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})\s*[-~～]\s*(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")


def _ak_article_text(raw: str) -> str:
    """Official-site articles are Next.js rendered: the body sits inside a JSON
    string and the HTML is escaped twice.
    """
    body = raw.encode("utf-8").decode("unicode_escape", errors="ignore").encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def arknights_next_from_news(now: datetime, get=None) -> "tuple[datetime, str] | None":
    """The newest 「…寻访即将开启」 post on the official site: (opening time,
    six-star「banner name」). None when there is none, or it has already opened.

    The user, 2026-09-03: 「明日方舟官方早都公布角色了，中继完全没跟进」.
    As recorded, bulletin 1457 of 08-29: 【石白深蓝之夜】限时寻访 09月04日 12:00 -
    09月18日 03:59, ★★★★★★：结城理（占6★出率的50%）. The year is absent from the
    bulletin and is filled in as the one nearest to now.
    """
    get = get or (lambda u: _text(u, _UA_BROWSER))
    page = get(_AK_NEWS)
    seen = set()
    for cid, title, _ts in _AK_NEWS_ITEM.findall(page):
        if cid in seen or "寻访" not in title or "开启" not in title:
            continue
        seen.add(cid)
        body = _ak_article_text(get(f"{_AK_NEWS}/{cid}"))
        m6 = _AK_SIX_LINE.search(body)
        six = [x.strip() for x in re.split(r"[/、]", m6.group(1))] if m6 else []
        sp = _AK_SPAN.search(body)
        if not six or not sp:
            continue
        mo, d, hh, mm = (int(x) for x in sp.groups()[:4])
        year = now.year + (1 if mo < now.month - 6 else 0)
        start = datetime(year, mo, d, hh, mm)
        pool = re.search(r"【([^】]+)】", title)
        who = "、".join(x for x in six if x) + (f"「{pool.group(1)}」" if pool else "")
        return (start, who) if start > now else None
    return None


def _arknights(now: datetime) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Both PRTS pages combined to decide debuts.

    PRTS does not give the next banner's time, so None is returned and the caller
    fills it in.
    """
    rows: list[Banner] = []
    for page in _AK_PAGES:
        url = _PRTS + urllib.parse.quote(page)
        try:
            rows += parse_arknights(
                _json(url, _UA_PLAIN)["parse"]["wikitext"]["*"])
        except Exception:
            log.warning("PRTS 取不到 %s", page, exc_info=True)
    rows.sort(key=lambda b: b.start)
    debut = debut_only(rows)
    # Look up rarity only for the ones currently running (not the dozens of historical
    # entries); report six-stars only
    debut = [six_star_only(b) if b.start <= now <= b.end else b for b in debut]
    debut = [b for b in debut if b.chars]
    # The official site's 「寻访即将开启」 post is the most accurate: it has both the
    # names and the time. Use it whenever it exists.
    try:
        if official := arknights_next_from_news(now):
            return debut, official
    except Exception:
        log.warning("方舟官网寻访公告取不到", exc_info=True)
    if when := min((b.start for b in rows if b.start > now), default=None):
        return debut, (when, "")      # PRTS already lists it: the time is accurate, the character unknown
    try:
        sched = parse_ak_schedule(_first(_AK_SCHEDULE, _UA_BROWSER))
    except Exception:
        log.warning("一图流方舟排期取不到", exc_info=True)
        return debut, None
    nxt = next(((n, d, ok) for n, d, ok in sched if d > now), None)
    if not nxt:
        return debut, None
    name, day, official = nxt
    return debut, (day, name if official else f"{name}（排期是预测，未官宣）")
