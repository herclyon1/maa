"""Endfield banners: Skland's char-pool API, the official bulletin and news
posts, the version briefing page, and the banner history."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime

from ark_relay.features.banners import banners as hub
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.banners.banners import (
    _ak_article_text, _AK_NEWS_ITEM, Banner, crosscheck, _ef_cms_text, log,
    newest_version, record_history, _stamps, Trace, _UA_BROWSER, upcoming,
    _yituliu_future,
)


# ── Endfield: official Skland API ──────────────────────────────
# chars[].name in char-pool is empty, so item/info has to be queried as well; the gid
# comes from what follows `gameEntryId=` in chars[].pcLink.
# This endpoint belongs to Endfield alone: passing ?gameId=1 still returns Endfield,
# and every /api/v1/game/arknights/* path 404s.
_SK_UP = "label_type_up"


def parse_endfield(pools: list, name_of) -> list[Banner]:
    """`pools` is char-pool's data.list; `name_of(gid)` returns a character name.

    Raises ValueError when there are pools but none has readable times: a renamed
    field would otherwise empty the list, and the report would say no banner is
    running (see _endfield). Some pools unreadable is one WARNING.
    """
    out: list[Banner] = []
    bad: list[str] = []
    for p in pools:
        try:
            # Server clock, not the host's: run from Tokyo the same timestamp read
            # 12:59 while the bulletin said 11:59, and the cross-check flagged it.
            a = datetime.fromtimestamp(int(p["poolStartAtTs"]), tz=SERVER_TZ).replace(tzinfo=None)
            b = datetime.fromtimestamp(int(p["poolEndAtTs"]), tz=SERVER_TZ).replace(tzinfo=None)
        except (KeyError, TypeError, ValueError, OverflowError, OSError) as e:
            bad.append(f"「{p.get('name') if isinstance(p, dict) else p}」"
                       f"（{type(e).__name__}: {e}）")
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
    if bad and len(bad) == len(pools):
        raise ValueError(f"森空岛 {len(pools)} 个卡池都读不出开放时间（poolStartAtTs / poolEndAtTs）："
                         + "；".join(bad))
    if bad:
        log.warning("终末地：森空岛 %d 个卡池里有 %d 个读不出开放时间，这几个池子这次没报\n%s",
                    len(pools), len(bad), "；".join(bad))
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
_EF_UP = re.compile(r"6星干员【([^】]+)】获取概率提升")


_EF_ANY_POOL = re.compile(r"「([^」]+)」(特许寻访|重构寻访#?\d*)")
_EF_OPEN = re.compile(r"开放时间[：:]\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})")


_EF_CLOSE = re.compile(r"[-~～]\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})")


def _ef_segments(html: str) -> "list[tuple[str, str]]":
    """[(banner name, the bulletin text about it)]. A banner is named twice in its
    own paragraph (the heading names it, and the 寻访说明 line names it again), so
    consecutive mentions of the same name are one segment.
    """
    txt = re.sub(r"<[^>]+>", " ", html or "").replace("&nbsp;", " ")
    txt = re.sub(r"\s+", " ", txt)
    hits = list(_EF_ANY_POOL.finditer(txt))
    out: list[tuple[str, str]] = []
    for k, m in enumerate(hits):
        tail = txt[m.end():hits[k + 1].start() if k + 1 < len(hits) else len(txt)]
        if out and out[-1][0] == m.group(1):
            out[-1] = (m.group(1), out[-1][1] + tail)
        else:
            out.append((m.group(1), tail))
    return out


def endfield_pool_ends(html: str) -> "dict[tuple[str, str], datetime]":
    """{(operator, banner): closing time} for every UP banner in the bulletin whose
    开放时间 line ends with a clock (「…版本更新后 - 2026/09/30 11:59」); banners that
    close 「版本更新维护前」 have no clock and are absent. Only the first 开放时间 of
    the banner's own paragraph counts - later ones belong to other activities.
    """
    out: dict[tuple[str, str], datetime] = {}
    for pool, seg in _ef_segments(html):
        up = _EF_UP.search(seg)
        i = seg.find("开放时间")
        if not up or i < 0 or (up.group(1), pool) in out:
            continue
        cl = _EF_CLOSE.search(seg[i:i + 70])
        if cl:
            y, mo, d, hh, mm = (int(x) for x in cl.groups())
            out[(up.group(1), pool)] = datetime(y, mo, d, hh, mm)
    return out


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
    out: list[tuple[str, str, "datetime | None", bool]] = []
    seen: set[tuple[str, str]] = set()
    for pool, body in _ef_segments(html):
        up = _EF_UP.search(body)
        if not up:
            continue
        name = up.group(1)
        if (name, pool) in seen:
            continue
        seen.add((name, pool))
        when = None
        # Only the banner's own 开放时间 (the first in its paragraph): a later one
        # belongs to the 申领 or event that follows.
        i = body.find("开放时间")
        if i >= 0 and (t := _EF_OPEN.match(body, i)):
            y, mo, d, hh, mm = (int(x) for x in t.groups())
            when = datetime(y, mo, d, hh, mm)
        out.append((name, pool, when, name in debut))
    return out
# Endfield's official bulletin aggregate endpoint, no token needed. code is a
# channel constant.
_EF_BULLETIN = ("https://game-hub.hypergryph.com/bulletin/v2/aggregate"
                "?lang=zh-cn&platform=Windows&channel=1&type=0"
                "&code=endfield_5SD9TN&hideDetail=0")


def _endfield(cred, sk_get, now: datetime, trace: "Trace | None" = None,
              notes: "dict[str, str] | None" = None
              ) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Running banners come from Skland (authoritative on timing); debuts and
    previews come from the official version bulletin.
    """
    tr = trace if trace is not None else Trace.new()
    # Unreadable must raise: `collect` then reports the game as not read, where
    # an empty return would print "no new banner running", which is false.
    pools = (sk_get("/web/v1/wiki/char-pool")["data"] or {}).get("list") or []

    unnamed: list[str] = []
    why: list[str] = []

    def name_of(gid: str) -> str:
        try:
            item = ((sk_get(f"/web/v1/wiki/item/info?id={gid}")["data"] or {})
                    .get("item") or {})
            return str(item.get("name") or "").strip()
        except Exception as e:  # said once below, not per operator
            log.info("森空岛条目 %s 查不到名字", gid, exc_info=True)
            unnamed.append(gid)
            why.append(f"{type(e).__name__}: {e}")
            return ""

    live = parse_endfield(pools, name_of)
    if unnamed:
        # A banner without its operator's name is dropped (never shown nameless),
        # so the report would read 「当期无新角色卡池」 for it.
        log.warning("终末地：森空岛条目 %s 查不到名字，这几个卡池这次没报\n%s",
                    "、".join(unnamed), why[-1][:200])

    # Official bulletin: which new operators this version has, and on which banner
    html = ""
    debut: "list[tuple[str, str]]" = []
    notice_ok = True
    try:
        d = hub._json(_EF_BULLETIN, _UA_BROWSER, timeout=25)
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
    try:
        pools_n = endfield_pools_from_notice(html) if notice_ok else []
        ends_n = hub.endfield_pool_ends(html) if notice_ok else {}
    except Exception:
        pools_n, ends_n = [], {}
        # The bulletin's opening and closing times are the official next-banner
        # time; without them the line falls to a weaker source or 「官方未公告」.
        log.warning("终末地版本更新说明里的卡池时间读不出，下一期开放时间这次不按公告报", exc_info=True)
    for b in got:
        if b.start <= now <= b.end:
            tr.ends |= _stamps(b.end)
            tr.src("终末地", "当期", "森空岛 /web/v1/wiki/char-pool", f"{b.name} {'、'.join(b.chars)} {b.start:%Y-%m-%d %H:%M}~{b.end:%Y-%m-%d %H:%M}")
            other = None
            for n, pname, w, _dbt in pools_n:
                if pname == b.name or n in b.chars:
                    en = ends_n.get((n, pname), b.end)
                    other = Banner("终末地", pname, (n,), w or b.start, en)
                    tr.src("终末地", "公告", _EF_BULLETIN, f"{pname} {n} 开 {w:%Y-%m-%d %H:%M} 止 {en:%Y-%m-%d %H:%M}" if w else f"{pname} {n} 版本更新后开 止 {en:%Y-%m-%d %H:%M}")
                    break
            tr.checks.append(crosscheck("终末地", "森空岛", b, "公告", other) if notice_ok
                             else "终末地：公告取不到，只有森空岛一个来源 ✗")
    # 2026-09-30 the whole Endfield block vanished: the banner had ended,
    # nothing was running, and an early return here skipped the official site's notice.
    # Prefer the official bulletin for the next banner: the one whose opening time is
    # in the future. Debuts only - a rerun is never "the next banner" (the user's
    # rule in the module docstring: new characters only; on 2026-09-12 the report
    # had put a rerun there, labelled as one, and that was wrong).
    on = {c for b in live for c in b.chars}
    future = [(n, p, w, d) for n, p, w, d in pools_n if w and w > now and n not in on and d]
    if future:
        n, p, w, d = min(future, key=lambda x: x[2])
        tr.starts |= _stamps(w)
        tr.src("终末地", "预告", _EF_BULLETIN, f"{p} {n} 开 {w:%Y-%m-%d %H:%M} 首发")
        return got, (w, f"{n}「{p}」")
    rest = upcoming(debut, on)
    if rest:
        # The bulletin names the second half but gives it no time: say only that.
        tr.src("终末地", "预告", _EF_BULLETIN, "本版下半：" + "、".join(f"{w}「{p}」" for w, p in rest) + "，开放时间公告未写")
        return got, (None, "、".join(f"{w}「{p}」" if p else w for w, p in rest))

    # Both halves of this version have finished. The official site posts the next
    # version's banner notice about a day before the update; until then nobody has
    # announced the operator, and the line must say exactly that.
    try:
        if official := hub.endfield_next_from_news(now):
            if official[0] is None:
                # The notice names the banner; its version's maintenance window is not out yet.
                tr.src("终末地", "预告", _EF_NEWS, f"{official[1]} 版本开启后开，维护时间公告未写")
                return got, official
            tr.starts |= _stamps(official[0])
            tr.src("终末地", "预告", _EF_NEWS, f"{official[1]} 开 {official[0]:%Y-%m-%d %H:%M}")
            return got, official
    except Exception:
        log.warning("终末地官网寻访公告取不到", exc_info=True)
    # No banner notice yet: the version briefing names the next version's operators
    # from its preview broadcast on (see _EF_BRIEFING).
    try:
        if brief := endfield_next_from_briefing(now, on):
            when, who, ver, day = brief
            if when is not None:
                tr.starts |= _stamps(when)
                tr.src("终末地", "预告", _EF_BRIEFING, f"{who} 开 {when:%Y-%m-%d %H:%M}")
                return got, (when, who)
            note = f"「{ver}」版本更新后开" if ver else "版本更新后开"
            if day is not None:
                tr.starts |= {f"{day:%m-%d}"}
                note += f"（版本 {day:%m-%d} 开启）"
            if notes is not None:
                notes["终末地"] = note
            tr.src("终末地", "预告", _EF_BRIEFING, f"{who} {note}")
            return got, (None, who)
    except Exception:
        log.warning("终末地新版本导览取不到", exc_info=True)
    # Yituliu's table has no announced/predicted mark, so it is recorded only.
    _yituliu_future("终末地", now, tr)
    return got, None


_EF_NEWS = "https://endfield.hypergryph.com/news"
# The backend the news page itself pages through (page 2 onwards is fetched in the
# browser): host and appCode are module 56006 of the site's Next.js bundle, the call
# is `GET /api/bulletin?lang&code&page&pageSize&tabs` in chunk 226 (read
# 2026-10-06). pageSize is capped at 20 server-side; total was 99, back to 2024.
_EF_CMS = "https://web-news.hypergryph.com/api/bulletin"
_EF_CMS_LIST = _EF_CMS + "?lang=zh-cn&code=endfield_web&page={page}&pageSize=20"
_EF_CMS_POST = _EF_CMS + "/{cid}?lang=zh-cn&code=endfield_web"
_EF_SIX_UP = re.compile(r"概率提升的6星干员为【([^】]+)】")
_EF_CLOCK = r"(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})"
# Every 开放时间 wording the 11 特许寻访 notices use (all read 2026-10-06):
#   start: a clock (5 of 11); 「<version>」版本开启后, i.e. once that version is
#     out (5 of 11, e.g. cid 5992); 公测开启后, i.e. at launch (cid 1188 only).
#   end: a clock (7 of 11); 版本更新维护前, i.e. before the next update's
#     maintenance (4 of 11, e.g. cid 7226).
# Either side may be followed by the 服务器时间 marker in full-width brackets.
# Groups: 1-5 start clock, 6 the version it opens with, 7 the launch marker,
# 8-12 end clock, 13 the before-maintenance marker.
_EF_SPAN = re.compile(r"开放时间[：:]?\s*(?:" + _EF_CLOCK + r"|「([^」]+)」版本(?:开启|更新)后|(公测)开启后)"
                      r"[^-~～/\d]{0,12}[-~～]\s*(?:" + _EF_CLOCK + r"|(版本更新维护前))")
# 「维护时间」, 「更新维护时间」 and 「版本维护时间」 all occur; both ends are kept: the
# end is when a 「版本开启后」 banner opens, the start is when a 「版本更新维护前」
# banner closes (Skland's char-pool agrees: 晨星于此闪耀 poolEndAtTs 1788300000 =
# 2026-09-02 06:00, the start of the 雪凇幽梦 window).
_EF_WINDOW = re.compile(r"维护时间\s*" + _EF_CLOCK + r"\s*[-~～]\s*" + _EF_CLOCK)
# Launch time: cid 7231, the 2026-01-20 pre-download post, says the launch is at
# 2026-01-22 11:00 (UTC+8) in the form matched below.
_EF_LAUNCH = re.compile(r"公测将于\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")
_EF_LAUNCH_NAME = "公测"


def _ef_dt(parts) -> datetime:
    y, mo, d, hh, mm = (int(x) for x in parts)
    return datetime(y, mo, d, hh, mm)


def _ef_wanted(title: str) -> bool:
    """The posts whose bodies the banner times come from: banner notices, and the
    posts that carry a maintenance window or the launch time.
    """
    return (any(k in title for k in ("特许寻访说明", "预下载", "版本更新说明"))
            or ("版本" in title and "预告" in title))


def ef_banner_posts(posts: "list[tuple[str, str, int, str]]") -> "list[dict]":
    """Read every 特许寻访 notice in `posts` [(cid, title, displayTime, text)].

    One dict per banner, newest notice first: who (operator「banner」), start, end,
    version (the period it ran in), how (which wording each end came from), cid,
    posted. A start or end that no post in `posts` publishes stays None; nothing is
    worked out beyond reading the named window or launch time.
    """
    windows: "dict[str, tuple[datetime, datetime]]" = {}
    launch = None
    for _cid, title, _ts, text in posts:
        v = re.search(r"「([^」]+)」", title)
        if v and ("预告" in title or "版本更新说明" in title) and (w := _EF_WINDOW.search(text)):
            windows.setdefault(v.group(1), (_ef_dt(w.groups()[:5]), _ef_dt(w.groups()[5:])))
        if launch is None and (m := _EF_LAUNCH.search(text)):
            launch = _ef_dt(m.groups())
    out: list[dict] = []
    for cid, title, ts, text in sorted(posts, key=lambda p: -int(p[2] or 0)):
        if "特许寻访说明" not in title:
            continue
        six, span = _EF_SIX_UP.search(text), _EF_SPAN.search(text)
        if not six or not span:
            log.warning("终末地寻访公告 %s「%s」读不出概率提升干员或开放时间", cid, title)
            continue
        g = span.groups()
        start, end, how = None, None, []
        if g[0]:
            start = _ef_dt(g[:5])
            how.append("开放时间写明")
        elif g[5]:
            win = windows.get(g[5])
            start = win[1] if win else None
            how.append(f"「{g[5]}」版本开启后 = 维护结束" if win else f"「{g[5]}」版本开启后，维护时间未公布")
        else:
            start = launch
            how.append("公测开启后 = 公测开启时刻" if launch else "公测开启后，开启时刻未读到")
        if g[7]:
            end = _ef_dt(g[7:12])
        else:
            later = sorted(w[0] for w in windows.values() if start and w[0] > start)
            end = later[0] if later else None
            how.append("版本更新维护前 = 下一次维护开始" if later else "版本更新维护前，下一次维护未公布")
        if g[5]:
            version = g[5]
        else:
            before = [(w[1], n) for n, w in windows.items() if start and w[1] <= start]
            version = max(before)[1] if before else _EF_LAUNCH_NAME
        pool = re.search(r"「([^」]+)」特许寻访说明", title)
        out.append({"who": six.group(1).strip() + (f"「{pool.group(1)}」" if pool else ""),
                    "start": start, "end": end, "version": version, "how": "；".join(how),
                    "cid": cid, "posted": int(ts or 0)})
    return out


def ef_next_banner(posts: "list[tuple[str, str, int, str]]", now: datetime
                   ) -> "tuple[datetime | None, str] | None":
    """The newest banner notice in `posts`, if it has not opened: (start, who).
    (None, who) when it opens with a version whose maintenance window is not
    published yet - that version has not been released, so neither has the banner.
    """
    rows = ef_banner_posts(posts)
    if not rows:
        return None
    r = rows[0]
    if r["start"] is None:
        return None if (r["end"] and r["end"] <= now) else (None, r["who"])
    return (r["start"], r["who"]) if r["start"] > now else None


def endfield_next_from_news(now: datetime, get=None) -> "tuple[datetime | None, str] | None":
    """The newest banner notice on the official site whose banner has not opened:
    (opening time, operator「banner」). None when there is none.

    Same page shape as the Arknights site (a Next.js list of cid/title/displayTime).
    Recorded 2026-09-12: cid 6097 「冬猎」特许寻访说明, posted 09-01; its body gives
    the opening as "after the version update - 2026/09/30 11:59" and names the
    rate-up six-star 【提弗洛斯】. A banner that opens "after the version update"
    opens when that version's maintenance window in the pre-download notice ends
    (2026/09/02 06:00 - 12:00 there). Read by ef_banner_posts, the same reader
    endfield_history uses for every past banner.

    The posts come from the same CMS API endfield_history pages through (its first
    page, the newest 20 posts); the SSR news page, which shows only 10, is the
    fallback when the API does not answer.
    """
    get = get or (lambda u: hub._text(u, _UA_BROWSER))
    try:
        return ef_next_banner(ef_cms_posts(get, max_pages=1), now)
    except Exception:  # any API failure falls back to the page
        log.info("终末地官网接口取不到，改读新闻页", exc_info=True)
    page = get(_EF_NEWS)
    posts, seen = [], set()
    for cid, title, ts in _AK_NEWS_ITEM.findall(page):
        if cid in seen or not _ef_wanted(title):
            continue
        seen.add(cid)
        posts.append((cid, title, int(ts), _ak_article_text(get(f"{_EF_NEWS}/{cid}"))))
    return ef_next_banner(posts, now)


# The 新版本导览 (version briefing) page. Bulletin cid 2183 「「丹青渡」新版本导览专题网页
# 上线说明」 (startAt 1791288000 = 2026-10-06 20:00 UTC+8) links to it; it is up from
# a version's preview broadcast until the next one's, about a week before the
# banner notice (「…」特许寻访说明) goes out - on 2026-10-08 the notice for the
# 10-15 version was not posted yet and the report said 「官方未公告」 for a week.
# The HTML only loads a bundle under web.hycdn.cn/endfield/webview/_version_briefing/
# whose name changes per version (v1d6/version-v1d6.0dca1e.js on 2026-10-08), so
# it is found through the page each time. The bundle carries the page content as
# JSON.parse('...') literals; the one with characters[] lists each new operator
# with gachaPoolName and gachaTimeByServer.cn (meta.sourceTables names
# GachaCharPool, i.e. the game's own tables).
_EF_BRIEFING = "https://endfield.hypergryph.com/version_briefing/latest"
_EF_BRIEFING_JS = re.compile(r'src="(https://[^"]+/_version_briefing/[^"]+\.js)"')
_JS_PARSE = re.compile(r"JSON\.parse\('((?:[^'\\]|\\.)*)'\)")
_JS_ESC = re.compile(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)", re.S)


def _js_unescape(lit: str) -> str:
    """The body of a single-quoted JS string literal, unescaped."""
    def one(m: "re.Match[str]") -> str:
        e = m.group(1)
        if len(e) > 1:  # \xNN or \uNNNN
            return chr(int(e[1:], 16))
        return {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}.get(e, e)
    return _JS_ESC.sub(one, lit)


def _ef_brief_time(s: str) -> "datetime | None":
    # Two shapes occur: 「2026/10/15 7:00:00」 and 「2026-11-05T11:59」; "" = not set.
    # Any other text raises: read as "not set", a new shape turned the announced
    # operator into 「官方未公告」 without a word (_endfield warns on the raise).
    if not s.strip():
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    raise ValueError(f"新版本导览的时间写法认不出：{s!r}")


def ef_briefing_banners(bundle: str) -> "tuple[str, list[dict]]":
    """(version, banners) from the briefing page's bundle. One dict per new
    operator: who (operator「banner」), open, close, after_update.

    after_update: the page itself drops openTime and shows 「版本更新后」 when
    startsAfterUpdate is set (`o.startsAfterUpdate ? {...o, openTime: ""}` in the
    bundle), so `open` is then None - the clock time beside it is not when the
    banner opens. Operators listed without a banner are skipped. Raises ValueError
    when no literal has the expected shape, so a redesign shows up in the log
    instead of reading as 「nothing announced」.
    """
    version, chars = "", None
    for m in _JS_PARSE.finditer(bundle):
        lit = m.group(1)
        if "page.title" not in lit and "characters" not in lit:
            continue
        d = json.loads(_js_unescape(lit))
        title = ((d.get("page.title") or {}).get("zh-cn") or "") if isinstance(d, dict) else ""
        if v := re.search(r"「([^」]+)」新版本导览", title):
            version = v.group(1)
        if isinstance(d, dict) and isinstance(d.get("characters"), list):
            chars = d["characters"]
    if chars is None:
        raise ValueError("新版本导览里没有 characters 列表")
    out = []
    for c in chars:
        t = (c.get("gachaTimeByServer") or {}).get("cn") or {}
        name = ((c.get("name") or {}).get("zh-cn") or "").strip()
        pool = ((c.get("gachaPoolName") or {}).get("zh-cn") or "").strip()
        if not pool or not t.get("openTime"):
            continue  # not on a banner (e.g. a free operator): not a next banner
        if not name:
            log.warning("新版本导览卡池「%s」的干员没有名字：%s", pool, c.get("id"))
            continue
        after = bool(t.get("startsAfterUpdate"))
        out.append({"who": name + (f"「{pool}」" if pool else ""),
                    "open": None if after else _ef_brief_time(t["openTime"]),
                    "listed": _ef_brief_time(t["openTime"]),
                    "close": _ef_brief_time(t.get("closeTime") or ""),
                    "after_update": after})
    return version, out


def endfield_next_from_briefing(now: datetime, on: "set[str]", get=None
                                ) -> "tuple[datetime | None, str, str, datetime | None] | None":
    """The earliest briefing banner that has not opened and whose operator is not
    running: (open, who, version, version day). `open` is None for a banner that
    opens 「版本更新后」; the version day is then the date its listed time falls on.
    """
    get = get or (lambda u: hub._text(u, _UA_BROWSER))
    page = get(_EF_BRIEFING)
    js = _EF_BRIEFING_JS.search(page)
    if not js:
        raise ValueError("新版本导览页里找不到内容脚本")
    version, rows = ef_briefing_banners(get(js.group(1)))
    ahead = [r for r in rows if r["listed"] and r["listed"] > now
             and re.sub(r"「.*", "", r["who"]) not in on]
    if not ahead:
        return None
    r = min(ahead, key=lambda r: r["listed"])
    return r["open"], r["who"], version, (r["listed"] if r["after_update"] else None)


def ef_cms_posts(get=None, max_pages: int = 20) -> "list[tuple[str, str, int, str]]":
    """Every post the official site still lists, with the bodies _ef_wanted needs:
    [(cid, title, displayTime, text)]. Maintenance windows come from the 预告 posts;
    a 版本更新说明 body is fetched only for a version no 预告 covers (寻遗散记 had
    none in the list on 2026-10-06; its 版本更新说明 carries the window).
    """
    get = get or (lambda u: hub._text(u, _UA_BROWSER))
    items: list[dict] = []
    for page in range(1, max_pages + 1):
        data = (json.loads(get(_EF_CMS_LIST.format(page=page))).get("data") or {})
        got = data.get("list") or []
        items += got
        if not got or len(items) >= int(data.get("total") or 0):
            break

    def body(cid: str) -> str:
        d = json.loads(get(_EF_CMS_POST.format(cid=cid))).get("data") or {}
        return _ef_cms_text(str(d.get("data") or ""))

    posts: list[tuple[str, str, int, str]] = []
    seen: set[str] = set()
    covered: set[str] = set()
    first = [i for i in items if "版本更新说明" not in str(i.get("title") or "")]
    notes = [i for i in items if "版本更新说明" in str(i.get("title") or "")]
    for it in first + notes:
        cid, title = str(it.get("cid") or ""), str(it.get("title") or "")
        if not cid or cid in seen or not _ef_wanted(title):
            continue
        v = re.search(r"「([^」]+)」", title)
        if "版本更新说明" in title and v and v.group(1) in covered:
            continue
        seen.add(cid)
        text = body(cid)
        if v and ("预告" in title or "版本更新说明" in title) and _EF_WINDOW.search(text):
            covered.add(v.group(1))
        posts.append((cid, title, int(it.get("displayTime") or 0), text))
    return posts


def endfield_history(get=None) -> "list[tuple[str, str, datetime | None, datetime | None, str]]":
    """Every new-operator banner the official site still has a notice for:
    [(period, operator「banner」, start, end, source)], oldest first.

    The user, 2026-10-06 18:55, asked for past banners to be fetched the way the
    next one is (his words are in BOARD/replay-终末地-1006.txt). Same site, same
    reader (ef_banner_posts) as
    endfield_next_from_news; only the listing goes past the page's first ten posts.
    Only 「特许寻访」 notices: reruns are 「重构寻访」 and 「辉光庆典」 is a
    「特殊寻访」 with no rate-up operator. Skland's char-pool lists only running
    banners (0 rows on 2026-10-06, code 0), so it cannot be a history source.
    """
    rows = ef_banner_posts(ef_cms_posts(get))
    far = datetime.max
    rows.sort(key=lambda r: (r["start"] or r["end"] or far, r["cid"]))
    return [(r["version"], r["who"], r["start"], r["end"],
             f"{_EF_NEWS}/{r['cid']}（{r['how']}）") for r in rows]


def update_endfield_history(state_dir, get=None) -> "tuple[list, list[str]]":
    """Record the Endfield banners the official site still has a notice for (a period is
    recorded once both its start and its end are published)."""
    rows = endfield_history(get)
    periods = [{"ver": v, "part": who, "start": a, "end": b} for v, who, a, b, _src in rows if a and b]
    return rows, record_history(state_dir, "终末地", periods)
