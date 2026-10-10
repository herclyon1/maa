"""Arknights banners: PRTS banner tables, the official site's banner posts,
Yituliu's schedule, and the banner history kept for the phone page."""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from ark_relay.features.banners import banners as hub
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.banners.banners import (
    Banner, crosscheck, debut_only, _ef_cms_text, log, _NOT_DEBUT, record_history,
    _RERUN, _stamps, Trace, _UA_BROWSER, _UA_PLAIN, _yituliu_future,
)


# ── Arknights: PRTS ────────────────────────────────────────────
# One row looks like this (as observed):
#   |[[文件:X.jpg|400px|link=Y]]<br/>[[Y|【限定寻访·夏季】车辙与风的归所]]
#   |2026-08-01 12:00~<br/>2026-08-15 03:59
#   |{{干员头像|予愿安洁莉娜|limited=1}}{{干员头像|珊比}}
# PRTS also writes a one-digit day or month: 「2022-12-1 16:00~<br/>2022-12-15 03:59」
# (雪融之诺 复刻); strptime takes both.
_AK_TIME = re.compile(r"(\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d\d)\s*~\s*<br\s*/?>\s*"
                      r"(\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d\d)")
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


# The same table as the rendered page, for when PRTS's API is down. 2026-09-26 21:53-23:05
# the API, index.php?action=raw and the front page all answered 503 "Backend fetch
# failed" from the machine and from the Mac alike, while /w/卡池一览/限时寻访 came back
# 200 from PRTS's CDN cache. A row of that page, as observed:
#   <td>...<a href="/w/BANNER" title="BANNER">BANNER</a></td>     (BANNER = 石白深蓝之夜)
#   <td>2026-09-04 12:00~<br />2026-09-18 03:59</td>
#   <td>...<a href="/w/结城理" title="结城理"><span ...><img id="charicon" .../>
#       <img id="levlicon" ... src=".../稀有度_黄_5.png..." />...
# The levlicon number is the same 0-based rarity as the operator page's 稀有度 field:
# on that page 1017 icons, every name always the same number, 5 for the six-stars
# 予愿安洁莉娜 / 结城理 and 4 for the five-stars 埃癸斯 / 嘉辛塔.
_PRTS_PAGE = "https://prts.wiki/w/"
_AK_HTML_TIME = _AK_TIME
_AK_HTML_NAME = re.compile(r'<a href="/w/[^"]*" title="[^"]*">([^<]+)</a>')
_AK_HTML_CHAR = re.compile(r'<a href="/w/[^"]*" title="([^"]+)"><span[^>]*><img id="charicon"[^>]*/>'
                           r'<img id="levlicon"[^>]*?src="[^"]*?(?:稀有度|%E7%A8%80%E6%9C%89%E5%BA%A6)_'
                           r'(?:黄|%E9%BB%84)_(\d)\.png')


def parse_arknights_html(page: str) -> "tuple[list[Banner], dict[str, int]]":
    """The rendered banner table: the rows `parse_arknights` gives, plus each
    operator's rarity from its icon (so no per-operator API call is needed)."""
    out: list[Banner] = []
    rarity: dict[str, int] = {}
    for row in page.split("<tr")[1:]:
        row = row.split("</tr>", 1)[0]
        m = _AK_HTML_TIME.search(row)
        cells = row.split("<td")
        if not m or len(cells) < 4:
            continue
        names = _AK_HTML_NAME.findall(cells[1])
        if not names:
            continue
        chars = []
        for who, r in _AK_HTML_CHAR.findall(row):
            who = html.unescape(who).strip()
            rarity.setdefault(who, int(r))
            if who not in chars:
                chars.append(who)
        try:
            a = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
            b = datetime.strptime(m.group(2), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        out.append(Banner("明日方舟", html.unescape(names[-1]).strip(), tuple(chars), a, b))
    out.sort(key=lambda x: x.start)
    return out, rarity


# ── Arknights: PRTS API ────────────────────────────────────────
# urlencode leaves the string ending in "&page=", so the page title is appended as is.
_PRTS = "https://prts.wiki/api.php?" + urllib.parse.urlencode(
    {"action": "parse", "prop": "wikitext", "format": "json", "page": ""})
# Only the limited-banner page. 「卡池一览/常驻标准寻访」 is the operator rotation pool:
# its table has no banner name (it parses to zero rows here), and every operator on it
# debuted earlier in a limited banner (checked 2026-08-31). A debut on another page
# would need that page added here.
_AK_PAGES = ("卡池一览/限时寻访",)


_AK_RARITY = re.compile(r"稀有度\s*=\s*(\d)")
_rarity_cache: dict[str, int] = {}


def ak_rarity(name: str, fetch=None) -> int:
    """The rarity field on a PRTS operator page, **counted from 0** (5 = six-star,
    verified 2026-09-03 against 予愿安洁莉娜).

    Returns -1 when it cannot be fetched or the page has no rarity field. Only the
    names currently running are looked up, and each answer is cached for the life
    of the process - a failure is not cached, so a timeout does not hide a running
    six-star banner until the relay restarts.
    """
    if name in _rarity_cache:
        return _rarity_cache[name]
    try:
        wt = (fetch or (lambda n: hub._json(_PRTS + urllib.parse.quote(n), _UA_PLAIN)["parse"]["wikitext"]["*"]))(name)
        m = _AK_RARITY.search(wt or "")
    except Exception:  # the caller says it (six_star_only's `failed`)
        log.info("PRTS 查不到 %s 的稀有度", name, exc_info=True)
        return -1
    if not m:
        return -1
    _rarity_cache[name] = r = int(m.group(1))
    return r


def six_star_only(b: Banner, fetch=None, failed: "list[str] | None" = None) -> Banner:
    """Keep only six-stars on Arknights banners (set by the user).

    A name whose rarity cannot be looked up is **dropped**, never faked, and
    appended to `failed`.
    """
    keep = []
    for c in b.chars:
        r = ak_rarity(c, fetch)
        if r == 5:
            keep.append(c)
        elif r < 0 and failed is not None:
            failed.append(c)
    return Banner(b.game, b.name, tuple(keep), b.start, b.end)


# The official site. Its news page is Next.js-rendered; the relay reads the two
# JSON endpoints behind it instead (both measured 2026-10-07):
#  * the list, one tab at a time, newest first, 6 a page:
#    /api/news?category=ACTIVITY|ANNOUNCEMENT|NEWS&page=N ->
#    {"code":0,"data":{"list":[{cid,title,displayTime,brief…}],"end":bool}}
#    (ACTIVITY = 活动 tab with the banner posts, ANNOUNCEMENT = 公告 tab with the
#    maintenance notices, NEWS = 新闻 tab with the 制作组通讯);
#  * one post, from the bulletin backend Endfield's site uses too (code=arknights):
#    web-news.hypergryph.com/api/bulletin/<cid> -> {"code":0,"data":{…,"data":"<p>…"}},
#    the article HTML escaped once (read by _ef_cms_text). On all 12 sample posts
#    (2019-05 to 2026-10) parse_ak_post reads the same banners from it as from
#    the page (test_banners._ak_history).
# _AK_NEWS stays the address people open (sources, traces); the page reader below
# (_AK_NEWS_ITEM, _ak_article_text) is left for the Endfield page fallback and for
# post texts cached from the page before 2026-10-07 (update_arknights_history).
_AK_NEWS = "https://ak.hypergryph.com/news"
_AK_NEWS_API = "https://ak.hypergryph.com/api/news?category={cat}&page={page}"
_AK_POST = "https://web-news.hypergryph.com/api/bulletin/{cid}?lang=zh-cn&code=arknights"


def _ak_posted(ts) -> datetime:
    """A post's displayTime (Unix seconds) on the server clock, naive like every
    other time in this module. Not datetime.fromtimestamp(ts) alone: "If optional
    argument tz is None or not specified, the timestamp is converted to the
    platform's local date and time" (https://docs.python.org/3/library/datetime.html#datetime.datetime.fromtimestamp),
    i.e. the clock of whichever machine runs this.
    """
    return datetime.fromtimestamp(int(ts or 0), tz=SERVER_TZ).replace(tzinfo=None)


def ak_news_pages(get, category: str, max_pages: int):
    """The official site's list for one tab, a page at a time: yields
    [(cid, title, posting time)] per page, newest first, until the site says
    `end` or `max_pages` pages are read. A reply that is not code 0 raises.
    """
    for page in range(1, max_pages + 1):
        d = json.loads(get(_AK_NEWS_API.format(cat=category, page=page)))
        if d.get("code") != 0:
            raise ValueError(f"方舟官网列表 {category} 第 {page} 页返回 code={d.get('code')!r}")
        data = d.get("data") or {}
        items = data.get("list") or []
        yield [(str(it.get("cid") or ""), str(it.get("title") or ""), _ak_posted(it.get("displayTime")))
               for it in items]
        if data.get("end") or not items:
            return


def ak_post_text(get, cid: str) -> str:
    """One official post's text, tags stripped, from the bulletin backend."""
    d = json.loads(get(_AK_POST.format(cid=cid)))
    if d.get("code") != 0:
        raise ValueError(f"方舟官网帖子 {cid} 返回 code={d.get('code')!r}")
    return _ef_cms_text(str((d.get("data") or {}).get("data") or ""))


def arknights_next_from_news(now: datetime, get=None) -> "tuple[datetime, str] | None":
    """The earliest debut banner the newest official posts announce that has
    not opened yet: (opening time, six-star「banner name」). None when there is
    none. One post can announce two (cid 2019084798: 深夏的守夜人 08-27, then
    久铸尘铁 09-10), so the first one having opened does not end the search.

    The user, 2026-09-03: 「明日方舟官方早都公布角色了，中继完全没跟进」.
    As recorded, bulletin 1457 of 08-29: 【石白深蓝之夜】限时寻访 09月04日 12:00 -
    09月18日 03:59, ★★★★★★：结城理（占6★出率的50%）. The year is absent from the
    bulletin and is taken from the post's own date (`_ak_year`).
    """
    fut = [(start, who) for start, who, _posted, _end, _cid in arknights_banner_posts(now, get)
           if start > now]
    return min(fut) if fut else None


# A banner is announced in one of two places, both in the site's ACTIVITY tab:
#  * a post of its own (cid 6247, title ending 【车辙与风的归所】限时寻访即将开启);
#    only limited and collab banners get one;
#  * a numbered section of the event's preview post. Every regular debut banner
#    is announced only this way: cid 5101 (10-03) has section 「二、【海渊巡游】限时寻访开启」
#    with its span and six-star line. Reading post titles alone misses these.
# The heading wordings met in all 239 ACTIVITY posts (2019-05 to 2026-10) are
# pinned one by one in test_banners._ak_history: a section heading names the
# banner in 【】 right before 寻访…开启, 限时复刻开启 or, in 2019, after 限时卡池.
# 「复刻」 and 「返场」 (2020) in the heading mark a rerun.
_AK_BANNER_HEAD = re.compile(r"【([^】]+)】(?:[^【】\s]{0,10}?寻访(?:即将|限时)*(?:复刻)?|限时复刻)开启"
                             r"|限时卡池【([^】]+)】开启")
_AK_RERUN_HEAD = ("复刻", "返场")
# Sections are numbered 「一、」「二、」; posts of 2019 put 「活动」 before the number.
_AK_SECTION = re.compile(r"(?:^|\s|活动)[一二三四五六七八九十]{1,3}、")
# The UP six-stars follow six stars and a colon (a space before the colon in 2020,
# no colon at all in 2019). Names are split on 「/」 「、」 「\」 and lose the
# 「[限定]」 tag. A pool to pick from (定向甄选, 前路回响) writes 「★★★★★★（6★出率：2%）：」:
# no UP six-star, and the bracket right after the stars keeps it out.
_AK_SIX_LINE = re.compile(r"★{6}\s*[：:]?\s*([^（(★\s\"][^（(★\"]*)")
_AK_NAME_SPLIT = re.compile(r"[/、\\]")
_AK_TAG = re.compile(r"\[[^\]]*\]")
# The span is month/day hh:mm - month/day hh:mm, and was also written with the
# year (cid 2021120792, across the new year), with 版本更新后 for the opening clock
# (cid 6262, 2025-10-25) and with 上午 before the clock (2019).
_AK_SPAN = re.compile(
    r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*(?:(上午|下午)?(\d{1,2}):(\d{2})|(版本更新后))\s*[-~～]\s*"
    r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*(上午|下午)?(\d{1,2}):(\d{2})")


@dataclass(frozen=True)
class AkSection:
    """One banner as an official post announces it."""

    name: str
    chars: tuple[str, ...]      # the UP six-stars
    start: datetime             # 00:00 when the post gives the day only
    end: datetime
    rerun: bool                 # 「复刻」 or 「返场」 in its heading
    start_note: str = ""        # 「版本更新后」 when that is all the post says of the clock


def _ak_year(mo: int, posted: datetime) -> int:
    # A post gives no year (most of them); a banner opens within weeks of its
    # post, so a month far behind the posting month is the next year's
    # (posted 12-22, opens 01-01).
    return posted.year + (1 if mo < posted.month - 6 else 0)


def _ak_span(m: "re.Match", posted: datetime) -> "tuple[datetime, datetime, str]":
    y1, mo, d, ap1, hh, mm, note, y2, mo2, d2, ap2, hh2, mm2 = m.groups()
    mo, d, mo2, d2 = int(mo), int(d), int(mo2), int(d2)
    year = int(y1) if y1 else _ak_year(mo, posted)
    if note:
        start = datetime(year, mo, d)
    else:
        start = datetime(year, mo, d, int(hh) + (12 if ap1 == "下午" and int(hh) < 12 else 0), int(mm))
    year2 = int(y2) if y2 else year + (1 if mo2 < mo else 0)
    end = datetime(year2, mo2, d2, int(hh2) + (12 if ap2 == "下午" and int(hh2) < 12 else 0), int(mm2))
    return start, end, note or ""


def parse_ak_post(title: str, text: str, posted: datetime) -> "list[AkSection]":
    """Every banner with an UP six-star that one official post announces, in
    the order written.

    `text` is the article as `_ak_article_text` gives it. A post titled as a
    banner is one banner; any other post is cut at its 「一、」「二、」 headings and
    each section whose heading names a banner is read. The article body is in
    the page twice (server HTML and the Next.js payload), so a banner is kept once.
    """
    if _AK_BANNER_HEAD.search(title):
        parts = [(title, text)]
    else:
        cuts = [m.end() for m in _AK_SECTION.finditer(text)]
        parts = []
        for a, b in zip(cuts, cuts[1:] + [len(text)]):
            sec = text[a:b]
            stop = min((i for i in (sec.find("活动时间"), sec.find("开放时间"), sec.find("返场时间")) if i >= 0),
                       default=80)
            parts.append((sec[:min(stop, 80)], sec))
    out: list[AkSection] = []
    seen = set()
    for head, sec in parts:
        heads = list(_AK_BANNER_HEAD.finditer(head))
        m6 = _AK_SIX_LINE.search(sec)
        sp = _AK_SPAN.search(sec)
        if not heads or not m6 or not sp:
            continue
        name = (heads[-1].group(1) or heads[-1].group(2)).strip()
        chars = tuple(dict.fromkeys(
            x for x in (_AK_TAG.sub("", y).strip() for y in _AK_NAME_SPLIT.split(m6.group(1))) if x))
        start, end, note = _ak_span(sp, posted)
        if (name, start) in seen or not chars:
            continue
        seen.add((name, start))
        out.append(AkSection(name, chars, start, end,
                             any(k in heads[-1].group(0) for k in _AK_RERUN_HEAD), note))
    return out


def arknights_banner_posts(now: datetime, get=None, limit: int = 3, max_pages: int = 2
                           ) -> "list[tuple[datetime, str, datetime, datetime, str]]":
    """The newest debut banners the official site has announced, newest post
    first: (opening time, six-star「banner」, posting time, closing time, cid).
    Reruns (「…即将复刻开启」, e.g. cid 8588 【砺火成锋】 of 06-12, or a 「复刻开启」
    section) are skipped - they are not new banners. `now` is unused and kept for
    the callers.

    The posts are the ACTIVITY tab's newest `max_pages` pages (6 a page; two
    pages are the dozen the /news page used to show), read until `limit`
    banners are found.
    """
    get = get or (lambda u: hub._text(u, _UA_BROWSER))
    out: list[tuple[datetime, str, datetime, datetime, str]] = []
    seen, done = set(), set()
    for items in ak_news_pages(get, "ACTIVITY", max_pages):
        for cid, title, posted in sorted(items, key=lambda it: it[2], reverse=True):
            if cid in done or "开启" not in title or ("复刻" in title and "寻访" in title):
                continue
            done.add(cid)
            for sec in parse_ak_post(title, ak_post_text(get, cid), posted):
                if sec.rerun or any(k in sec.name for k in _RERUN + _NOT_DEBUT) or (sec.name, sec.start) in seen:
                    continue
                seen.add((sec.name, sec.start))
                out.append((sec.start, f"{'、'.join(sec.chars)}「{sec.name}」", posted, sec.end, cid))
            if len(out) >= limit:
                return out[:limit]
    return out[:limit]


class AkPast(NamedTuple):
    """One past banner, as `arknights_history` returns it."""

    name: str
    chars: "tuple[str, ...]"    # the UP six-stars (a PRTS-only row: every operator PRTS lists)
    start: datetime             # 00:00 when the post gives the day only (「版本更新后」)
    end: datetime
    source: str                 # the post URLs, 「+ PRTS」 when PRTS has it too
    rerun: bool
    check: str                  # where the post and PRTS differ; empty when they agree


def _ak_key(name: str) -> str:
    return re.sub(r"[\W_]", "", name)


def _ak_same_banner(sec: AkSection, row: Banner) -> bool:
    """The same banner on a post and in PRTS: the same opening day, and one name
    within the other once punctuation is gone (PRTS adds a 【限定寻访·夏季】 prefix
    or a 复刻 suffix, writes a space or a full-width 「！」 where a post has a colon
    or 「 !」). The clock is compared afterwards, not here: since 2025-12 PRTS
    writes 07:00 for banners the posts open at 12:00 (cid 9605), and that is a
    difference between the two sources, not two banners.
    """
    a, b = _ak_key(sec.name), _ak_key(row.name)
    return row.start.date() == sec.start.date() and bool(a) and (a in b or b in a)


def arknights_history(get=None, prts_rows: "list[Banner] | None" = None,
                      trace: "Trace | None" = None, max_pages: int = 80,
                      post_text=None) -> "list[AkPast]":
    """Every banner the official site and PRTS still hold, oldest first.

    The same sources and the same readers as the next-banner line
    (`_arknights`): the official site's posts read by `parse_ak_post` - every
    page of the ACTIVITY tab, through the site's own list endpoint
    (`ak_news_pages`, 6 a page), each post's text from `post_text(cid)`
    (default `ak_post_text`) - and the PRTS table read by `parse_arknights`.

    A post's banner is matched to a PRTS row by start and name; `source` names
    both, and `check` says where they differ (empty when they agree, or when
    only one has the banner). A PRTS row no post matches comes last in its
    place with the operators PRTS lists (PRTS does not mark six-stars): pools
    without an UP six-star (定向甄选, 联合行动, 跨年欢庆) and banners whose post is gone.
    Asked for by the user on 2026-10-06 at 18:55, who said past banners should be
    read the way the next one is: 「你们怎么查到下期数据应当能查到往期的数据」.
    """
    tr = trace if trace is not None else Trace.new()
    get = get or (lambda u: hub._text(u, _UA_BROWSER))
    post_text = post_text or (lambda cid: ak_post_text(get, cid))
    found: dict = {}
    for items in ak_news_pages(get, "ACTIVITY", max_pages):
        for cid, title, posted in items:
            if "开启" not in title and "寻访" not in title:
                continue
            for sec in parse_ak_post(title, post_text(cid), posted):
                found.setdefault((sec.name, sec.start), [sec, []])[1].append(cid)
    if prts_rows is None:
        try:
            prts_rows = hub._ak_prts_rows(tr)
        except Exception as e:
            log.warning("方舟往期卡池：PRTS 取不到，只有官网一个来源", exc_info=True)
            tr.src("明日方舟", "往期卡池", _PRTS_PAGE + _AK_PAGES[0], f"取不到：{type(e).__name__}: {e}"[:300])
            prts_rows = []
    used: set[int] = set()
    out: list[AkPast] = []
    for sec, cids in found.values():
        hit = next((i for i, r in enumerate(prts_rows) if i not in used and _ak_same_banner(sec, r)), None)
        src = "官网 " + "、".join(f"{_AK_NEWS}/{c}" for c in dict.fromkeys(cids))
        diffs = []
        if hit is not None:
            used.add(hit)
            row = prts_rows[hit]
            src += " + PRTS"
            if row.end != sec.end:
                diffs.append(f"结束 官网 {sec.end:%Y-%m-%d %H:%M} / PRTS {row.end:%Y-%m-%d %H:%M}")
            if sec.start_note == "" and row.start != sec.start:
                diffs.append(f"开始 官网 {sec.start:%Y-%m-%d %H:%M} / PRTS {row.start:%Y-%m-%d %H:%M}")
            if miss := [c for c in sec.chars if c not in row.chars]:
                diffs.append("PRTS 没有六星 " + "、".join(miss))
        out.append(AkPast(sec.name, sec.chars, sec.start, sec.end, src, sec.rerun, "；".join(diffs)))
    for i, r in enumerate(prts_rows):
        if i not in used:
            out.append(AkPast(r.name, r.chars, r.start, r.end, "PRTS",
                              any(k in r.name for k in _RERUN), ""))
    out.sort(key=lambda x: (x.start, x.name))
    return out


_AK_COMM_EVENT = re.compile(
    r"「([^」]+)」限时活动将于(\d{1,2})月(上|中|下)旬开启[^。●]*新干员")
_XUN_END = {"上": 11, "中": 21}


def arknights_comm_lead(now: datetime, posts: "list | None" = None,
                        opened: "list[datetime] | None" = None, get=None,
                        why: "list[str] | None" = None
                        ) -> "tuple[str, str, str, str] | None":
    """The newest 「制作组通讯」 on the official site, when it says an event opens
    in some part of a month *with new operators*: (event, 「10 月上旬」, cid,
    title + posting day + the sentence). None otherwise.

    As read, newsletter #69 (cid 7366, 09-25): SideStory「昨日海」 opens in early
    October (「10月上旬」), and new operators come with it (「新干员」). The same
    post's 「恒远津梁」 (10月中旬, outfits only) does not count - the operator has to
    be in the same sentence.

    Stale once the banner itself is out: None when a debut-banner post (`posts`,
    from arknights_banner_posts) came after the newsletter, when a debut banner
    that opened after it is running (`opened`: the running ones' starts), or when
    that part of the month is over (上旬 = 1-10, 中旬 = 11-20, 下旬 = to the end).

    `why`, when given, gets the reason for a None: 「过期：…」 when the newsletter's
    line has run its course (a banner post or a debut banner after it, or its
    part of the month over), 「无：…」 when there was nothing to say. The machine
    check #8 reads it from the trace (machinechecks/phone_banners.py).
    """
    why = why if why is not None else []
    get = get or (lambda u: hub._text(u, _UA_BROWSER))
    # The NEWS tab, newest first; two pages are the dozen the /news page showed.
    comm = next((it for items in ak_news_pages(get, "NEWS", 2) for it in items
                 if "制作组通讯" in it[1]), None)
    if comm is None:
        why.append("无：官网新闻里没有制作组通讯")
        return None
    cid, title, posted = comm
    later = [p for p in posts or () if p[2] > posted]
    if later:
        why.append(f"过期：通讯（{posted:%m-%d} 发）之后官网出了寻访公告「{later[0][1]}」（{later[0][2]:%m-%d} 发）")
        return None
    if ran := [t for t in opened or () if t > posted]:
        why.append(f"过期：通讯（{posted:%m-%d} 发）之后开的首发卡池在跑（{min(ran):%m-%d %H:%M} 开）")
        return None
    body = ak_post_text(get, cid)
    over_said = ""
    for m in _AK_COMM_EVENT.finditer(body):
        name, mo, part = m.group(1), int(m.group(2)), m.group(3)
        year = now.year + (1 if mo < now.month - 6 else 0)
        if part in _XUN_END:
            over = datetime(year, mo, _XUN_END[part])
        else:
            over = datetime(year + mo // 12, mo % 12 + 1, 1)
        if now >= over:
            over_said = over_said or f"过期：通讯里的「{name}」{mo} 月{part}旬已过"
            continue
        start = body.rfind("●", 0, m.start()) + 1
        stop = body.find("。", m.end())
        said = body[start:stop + 1 if stop >= 0 else None].strip()
        return name, f"{mo} 月{part}旬", cid, f"{title}（{posted:%m-%d} 发）：{said}"
    why.append(over_said or f"无：通讯（{title}，{posted:%m-%d} 发）里没有带新干员的限时活动")
    return None


def _ak_prts_rows(tr: "Trace") -> "list[Banner]":
    """The PRTS limited-banner table: its API, or its rendered page when the API
    fails. Raises when neither gives a row."""
    rows: list[Banner] = []
    for page in _AK_PAGES:
        url = _PRTS + urllib.parse.quote(page)
        try:
            rows += parse_arknights(
                hub._json(url, _UA_PLAIN)["parse"]["wikitext"]["*"])
            continue
        except Exception as e:  # the page is the second source
            api_why = f"{type(e).__name__}: {e}"
            log.info("PRTS 接口取不到 %s，改读页面", page, exc_info=True)
        try:
            got, rarity = parse_arknights_html(hub._text(_PRTS_PAGE + urllib.parse.quote(page), _UA_PLAIN, timeout=40))
        except Exception:
            log.warning("PRTS 接口和页面都取不到 %s（接口：%s）", page, api_why, exc_info=True)
            continue
        if not got:
            log.warning("PRTS 接口取不到 %s，页面解析出 0 行（接口：%s）", page, api_why)
            continue
        rows += got
        # The API failed and the page gave the table: a fault the relay got over,
        # the daily report only (the user on 2026-10-06 05:07 about faults the relay got over: 「报错后自己好了的，只进日报、不进群」).
        from ark_relay.features.alarm import errwatch  # noqa: PLC0415
        log.warning("方舟卡池表：资料站的数据入口没取到「%s」，改读它的页面读到了 %d 行\n数据入口：%s",
                    page, len(got), api_why, extra=errwatch.recovered())
        for who, r in rarity.items():
            if _rarity_cache.get(who, -1) < 0:   # the API is down, so ak_rarity would drop them all
                _rarity_cache[who] = r
        tr.src("明日方舟", "卡池表", _PRTS_PAGE + page, f"资料站数据入口出错，改读页面：{len(got)} 行")
    if not rows:
        raise RuntimeError("PRTS 两条路都没读到卡池表")
    rows.sort(key=lambda b: b.start)
    return rows


def _arknights(now: datetime, trace: "Trace | None" = None,
               leads: "dict[str, str] | None" = None
               ) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Both PRTS pages combined to decide debuts; the next debut banner from the
    official site's post, or from a PRTS row once PRTS has registered it. None
    when neither has one.
    """
    tr = trace if trace is not None else Trace.new()
    rows = hub._ak_prts_rows(tr)
    debut = debut_only(rows)
    # Look up rarity only for the ones currently running (not the dozens of historical
    # entries); report six-stars only
    lost: list[str] = []
    debut = [six_star_only(b, failed=lost) if b.start <= now <= b.end else b for b in debut]
    if lost:
        log.warning("方舟：在开的卡池里 %s 在 PRTS 查不到稀有度，分不出是不是六星，这次没报",
                    "、".join(lost))
    debut = [b for b in debut if b.chars]
    for b in debut:
        if b.start <= now <= b.end:
            tr.ends |= _stamps(b.end)
            tr.src("明日方舟", "当期", f"PRTS {_AK_PAGES[0]}", f"{b.name} {'、'.join(b.chars)} {b.start:%Y-%m-%d %H:%M}~{b.end:%Y-%m-%d %H:%M}")
    # The official site's 「寻访即将开启」 posts: the next banner when one is announced,
    # and the second source for the running one.
    posts: list = []
    try:
        posts = arknights_banner_posts(now)
    except Exception:
        log.warning("方舟官网寻访公告取不到", exc_info=True)
    # A heading without 「复刻」 is not proof of a debut on its own: a post whose
    # six-stars all ran on an earlier PRTS row is a rerun.
    def _seen_before(st: datetime, who: str) -> bool:
        names = [x for x in who.split("「", 1)[0].split("、") if x]
        old = {c for r in rows if r.start < st for c in r.chars}
        return bool(names) and all(n in old for n in names)
    posts = [p for p in posts if not _seen_before(p[0], p[1])]
    for st, who, posted, en, cid in posts:
        tr.src("明日方舟", "官网寻访公告", f"{_AK_NEWS}/{cid}", f"{who} {st:%Y-%m-%d %H:%M}~{en:%Y-%m-%d %H:%M}（{posted:%m-%d} 发）")
    live = [b for b in debut if b.start <= now <= b.end]
    for b in live:
        other = None
        for st, who, _p, en, _c in posts:
            m = re.match(r"(.*)「([^」]+)」$", who)
            if m and (m.group(2) == b.name or st == b.start):
                other = Banner("明日方舟", m.group(2), tuple(x for x in m.group(1).split("、") if x), st, en)
                break
        tr.checks.append(crosscheck("明日方舟", "PRTS", b, "官网公告", other))
    # The earliest announced one not yet open, whichever post it is in (the
    # same rule as arknights_next_from_news).
    if fut := [(st, who, en) for st, who, _p, en, _c in posts if st > now]:
        st, who, en = min(fut)
        tr.starts |= _stamps(st)
        # the post prints the end too (cid 5101: 10-09 12:00 - 10-23 03:59), so the line says it
        tr.ends |= _stamps(en)
        tr.until["明日方舟"] = en
        return debut, (st, who)
    # PRTS registers a banner once it is announced, so its time is published. Only
    # a debut counts (a rerun is never "the next banner").
    # A name whose rarity could not be looked up drops that banner: said once, or
    # the line falls to 「官方未公告」 for an announced banner in silence.
    unknown: list[str] = []
    nxt = next((b for b in (six_star_only(x, failed=unknown) for x in debut if x.start > now)
                if b.chars), None)
    if unknown:
        log.warning("方舟：已公布的下一期卡池里 %s 在 PRTS 查不到稀有度，分不出是不是六星，这次没当下一期报",
                    "、".join(unknown))
    if nxt:
        tr.starts |= _stamps(nxt.start)
        tr.ends |= _stamps(nxt.end)
        tr.until["明日方舟"] = nxt.end
        return debut, (nxt.start, f"{'、'.join(nxt.chars)}「{nxt.name}」")
    # Last, the Yituliu table - only an entry it marks as announced. Its
    # predictions are recorded in the trace and never printed (2026-09-30).
    fut = _yituliu_future("明日方舟", now, tr)
    if ok := next(((n, st) for n, st, flag in fut if flag), None):
        tr.starts |= _stamps(ok[1])
        return debut, (ok[1], f"「{ok[0]}」")
    # No banner yet, but the newsletter may say an event with new operators is
    # coming. A miss and a failed fetch are traced too (machine check #8).
    why: list[str] = []
    try:
        lead = arknights_comm_lead(now, posts, [b.start for b in live], why=why)
    except Exception as e:
        lead = None
        log.warning("方舟官网制作组通讯取不到", exc_info=True)
        tr.src("明日方舟", "官方通讯", _AK_NEWS, f"取不到：{type(e).__name__}: {e}"[:300])
    if lead:
        event, when, cid, said = lead
        tr.src("明日方舟", "官方通讯", f"{_AK_NEWS}/{cid}", said)
        if leads is not None:
            leads["明日方舟"] = f"{event} · {when} · 官方通讯：有新干员，寻访未公告"
    elif why:
        tr.src("明日方舟", "官方通讯", _AK_NEWS, f"没用上（{why[-1]}）")
    return debut, None


def update_arknights_history(state_dir, get=None, prts_rows=None, budget: int = 60, max_pages: int = 80
                             ) -> "tuple[list, list[str]]":
    """Record the Arknights banners the official site and PRTS still hold. A post's
    text never changes, so each is fetched once into `banners/ak-posts.json` (at most
    `budget` new ones a run; the rest come in on the following days)."""
    from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
    raw = get or (lambda u: hub._text(u, _UA_BROWSER))
    cache_f = Path(state_dir) / "banners" / "ak-posts.json"
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    left = [budget]

    def post_text(cid: str) -> str:
        # Keyed by the post's page address, as since the cache began: the texts
        # cached before 2026-10-07 were read off that page (_ak_article_text) and
        # parse to the same banners as the backend's (test_banners._ak_history).
        key = f"{_AK_NEWS}/{cid}"
        if key not in cache:
            if left[0] <= 0:
                return ""
            left[0] -= 1
            cache[key] = ak_post_text(raw, cid)
        return cache[key]
    try:
        rows = arknights_history(get=raw, prts_rows=prts_rows, max_pages=max_pages, post_text=post_text)
    finally:
        cache_f.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(cache_f, json.dumps(cache, ensure_ascii=False))
    periods = [{"ver": r.name, "part": "复刻" if r.rerun else "首发", "start": r.start, "end": r.end} for r in rows]
    return rows, record_history(state_dir, "明日方舟", periods)
