"""Wuthering Waves version-news posters and banner notices: Kuro BBS and
Bilibili posts, the OCR of their long images, and the Kuro gacha notices."""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from ark_relay.features.banners import banners as hub
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.banners.banners import (
    log, _stamps, _UA_BROWSER,
)


_KURO = "https://api.kurobbs.com"


# The version-news post (「《鸣潮》版本资讯 | 3.7版本…」, 库街区 1551271800597471232,
# 2026-09-28 18:00; the same images on Bilibili an hour later) is the one official
# place the second-half banner's time of day appears before it opens: its third
# long image has the heading 「角色/武器活动唤取」, the label 「活动时间」, then the span
# 2026年10月22日10:00～2026年11月11日11:59 (server time) with the banner names under
# it. It is a 新闻 (eventType 2) in the
# official-news list. getPostDetail answers 102 「服务器外部错误」 without a devCode
# and a browser User-Agent; any devCode value does (2026-10-01).
_KURO_NEWS = "/forum/companyEvent/findEventList"
_KURO_POST = "/forum/getPostDetail"
_KURO_BBS_HDR = {"source": "h5", "version": "2.5.0", "devCode": "ark-relay"}
_KURO_POST_URL = "https://www.kurobbs.com/mc/post/{id}"
_WW_POSTER_SPAN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})[:：](\d{2})[~～\-—一至、]*"
                             r"(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})[:：](\d{2})")


def wuwa_news_post(events: list, ver: "str | None", now: datetime) -> "tuple[str, str, datetime] | None":
    """(post id, title, published) of the newest 「版本资讯」 post up to `now`,
    for version `ver` when known."""
    best = None
    for e in events or []:
        title = str(e.get("postTitle") or "").replace("\xa0", " ")
        if "版本资讯" not in title or (ver and f"{ver}版本" not in title):
            continue
        try:
            at = datetime.fromtimestamp(int(e.get("publishTime")) / 1000, tz=SERVER_TZ).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        if at <= now and (best is None or at > best[2]):
            best = (str(e.get("postId") or ""), title, at)
    return best


def _rows(lines: list) -> "list[tuple[int, str]]":
    """OCR lines joined into rows (same baseline, left to right), top to bottom:
    an engine may split 「2026年10月22日10:00 ~ 2026年…」 at the spaces."""
    rows: "list[list]" = []
    for ln in sorted(lines, key=lambda x: (x.y, x.x)):
        if rows and abs(ln.y - rows[-1][0].y) <= max(rows[-1][0].h, 1) // 2:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    return [(r[0].y, "".join(x.text for x in sorted(r, key=lambda x: x.x)).replace(" ", "")) for r in rows]


def parse_wuwa_poster(lines: list, pool: str, char: str = "") -> "tuple[datetime, datetime] | None":
    """(start, end) of `pool` from a version-news poster: the 「(服务器时间)」 row
    nearest above the banner's name, when that row is a full date span. The
    first-half block 「3.7版本更新后～2026年10月22日09:59」 has no start date, so a
    banner under it gets nothing. The name tolerates OCR errors
    (「余心所向九死未啊角色活动典取」); 「<char>UP」 under the name also counts."""
    from ark_relay.core.desktop import _name_in  # noqa: PLC0415
    want = pool.replace(" ", "")
    miss = 2 if len(want) >= 6 else 1 if len(want) >= 4 else 0
    rows = _rows(lines)
    for i, (_y, txt) in enumerate(rows):
        # Windows.Media.Ocr reads 「～」 as 「、」 and 「锁暝UP!」 as 「锁暝U」 (2026-10-05
        # on the PC, fixture ww-3.7-news-4-winocr.json)
        if not (_name_in(want, txt, miss) or (char and f"{char}U" in txt.upper())):
            continue
        k = next((j for j in range(i - 1, -1, -1) if "服务器时间" in rows[j][1]), None)
        if k is None:
            continue
        # an engine that puts 「（服务器时间）」 on a row of its own leaves the span
        # on the row above it
        m = _WW_POSTER_SPAN.search(rows[k][1]) or (_WW_POSTER_SPAN.search(rows[k - 1][1]) if k else None)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        try:
            return datetime(g[0], g[1], g[2], g[3], g[4]), datetime(g[5], g[6], g[7], g[8], g[9])
        except ValueError:
            return None
    return None


# The same post on Bilibili (the official space, uid 1955897084: dynamic
# 1253061864718336024, 2026-09-28 19:00, image 3 is the 1080x14717 original of
# the 库街区 poster) is the second door. Its space feed needs a visitor buvid
# (finger/spi) and a WBI-signed query: unsigned it answers -352. Signed, it is
# still risk-controlled without saying so: the answer is code 0 with no items,
# has_more false and an empty offset (fixture ww-bili-feed-2026-10-05.json,
# "empty") - the same shape a space with no dynamics would give, so read alone
# it looks like "no post". Measured 2026-10-05 from a cloud container, the same
# signed page-1 request listed 13 items in 4 of 6 tries with a fresh buvid per
# try, and in 1 of 6 with one buvid reused for ~30 requests; one buvid per run
# with a single retry (what the relay did until then) gave up on the first empty
# page; a live run of this code the same evening needed 4 tries for page 2. So
# each empty page is retried with a new buvid and a new wts, and a page
# that stays empty is a source problem (BiliFeedProblem, raw shape in the
# message and the trace), never "no banner". The signature follows the
# community write-up (bilibili-API-collect docs/misc/sign/wbi.md - that
# repository was emptied in 2026-01 after a lawyer's letter from Bilibili; its
# worked example is pinned in the tests); Bilibili publishes no documentation.
_BILI_UID = 1955897084
_BILI_SPI = "https://api.bilibili.com/x/frontend/finger/spi"
_BILI_NAV = "https://api.bilibili.com/x/web-interface/nav"
_BILI_FEED = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
_BILI_POST_URL = "https://www.bilibili.com/opus/{id}"
_BILI_MIX = (46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
             33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
             61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
             36, 20, 34, 44, 52)
# The account posts about five dynamics a day, 12-13 per page: on 2026-10-05 the
# 3.7 post (09-28) was on page 3, so four pages lost it about two weeks before
# the second half it times (10-22). Paging stops at the first page whose oldest
# item is older than _BILI_OLDEST (a version runs about 40 days and its post
# comes out two days before it), or at _BILI_PAGES, whichever is first.
_BILI_PAGES = 12
_BILI_OLDEST = timedelta(days=50)
_BILI_TRIES = 5


class BiliFeedProblem(RuntimeError):
    """The Bilibili space feed answered but listed nothing readable: a source
    problem (risk control, or a changed response shape), not "no post"."""


def bili_sign(params: dict, img_key: str, sub_key: str, wts: int) -> str:
    """The query string with `wts` and `w_rid` (WBI signature)."""
    import hashlib  # noqa: PLC0415
    k = img_key + sub_key
    mixin = "".join(k[i] for i in _BILI_MIX)[:32]
    q = urllib.parse.urlencode(sorted((a, "".join(c for c in str(b) if c not in "!'()*"))
                                      for a, b in dict(params, wts=wts).items()))
    return q + "&w_rid=" + hashlib.md5((q + mixin).encode()).hexdigest()


def bili_wbi_keys(nav: dict) -> "tuple[str, str]":
    """(img_key, sub_key) from an x/web-interface/nav answer: the file stems of
    wbi_img.img_url / sub_url. The answer is code -101 for a visitor and still
    carries them (2026-10-05)."""
    wbi = ((nav or {}).get("data") or {}).get("wbi_img") or {}
    keys = tuple(str(wbi.get(k) or "").rsplit("/", 1)[-1].split(".")[0] for k in ("img_url", "sub_url"))
    if not all(re.fullmatch(r"[0-9a-f]{32}", x) for x in keys):
        raise BiliFeedProblem(f"nav gave no WBI keys: {bili_shape(nav)}")
    return keys


def bili_shape(d) -> str:
    """The raw shape of a Bilibili answer for the log: the envelope and `data`
    verbatim except that the item list is counted, not printed."""
    if not isinstance(d, dict):
        return repr(d)[:300]
    out = dict(d)
    if isinstance(out.get("data"), dict):
        out["data"] = {k: (f"<{len(v)} items>" if k == "items" and isinstance(v, list) else v)
                       for k, v in out["data"].items()}
    return json.dumps(out, ensure_ascii=False)[:400]


def _bili_at(it: dict) -> "datetime | None":
    try:
        return datetime.fromtimestamp(int(((it.get("modules") or {}).get("module_author") or {}).get("pub_ts")),
                                      tz=SERVER_TZ).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def wuwa_bili_post(items: list, ver: "str | None", now: datetime
                   ) -> "tuple[str, str, list[tuple[str, int, int]]] | None":
    """(dynamic id, first line, [(image URL, width, height)]) of the newest
    「版本资讯」 dynamic up to `now`, for version `ver` when known."""
    best = None
    for it in items or []:
        m = it.get("modules") or {}
        op = ((m.get("module_dynamic") or {}).get("major") or {}).get("opus") or {}
        text = str((op.get("summary") or {}).get("text") or "")
        head = next((x for x in text.splitlines() if "版本资讯" in x), "")
        if not head or (ver and f"{ver}版本" not in head):
            continue
        at = _bili_at(it)
        if at is None:
            continue
        pics = [(str(p.get("url") or "").replace("http://", "https://", 1), int(p.get("width") or 0),
                 int(p.get("height") or 0)) for p in op.get("pics") or [] if p.get("url")]
        if at <= now and (best is None or at > best[0]):
            best = (at, str(it.get("id_str") or ""), head.strip(), pics)
    return best[1:] if best else None


def _bili_poster(ver: "str | None", now: datetime, get=None, sleep=None, clock=None):
    """(page URL, title, images) of the Bilibili copy of the version-news post;
    None when the feed lists fine but the post is not in it. Raises
    BiliFeedProblem when a page stays empty or unreadable after _BILI_TRIES."""
    import time  # noqa: PLC0415

    def fetch(url: str, cookie: str) -> dict:
        return hub._json(url, _UA_BROWSER, None, {"Cookie": cookie, "Origin": "https://space.bilibili.com",
                                              "Referer": f"https://space.bilibili.com/{_BILI_UID}/dynamic"})
    get = get or fetch
    sleep = sleep or hub._pause
    clock = clock or time.time

    def visitor() -> str:
        spi = get(_BILI_SPI, "")["data"]
        return f"buvid3={spi['b_3']}; buvid4={urllib.parse.quote(spi['b_4'])}"
    cookie = visitor()
    img_key, sub_key = bili_wbi_keys(get(_BILI_NAV, cookie))   # once per run
    offset = ""
    for page in range(_BILI_PAGES):
        if page:
            sleep(2)   # a second page fetched within a second came back empty
        shapes = []
        for attempt in range(_BILI_TRIES):
            if attempt:
                sleep(3 * attempt)
                cookie = visitor()
            q = bili_sign({"host_mid": _BILI_UID, "offset": offset, "timezone_offset": -480, "platform": "web",
                           "features": "itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote",
                           "web_location": "333.1387", "dm_img_list": "[]",
                           "dm_img_str": "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ",
                           "dm_cover_img_str": "QU5HTEUgKEFwcGxlLCBBTkdMRSBNZXRhbCBSZW5kZXJlcjogQXBwbGUgTTEgUHJvLCBV"
                                               "bnNwZWNpZmllZCBWZXJzaW9uKUdvb2dsZSBJbmMuIChBcHBsZS",
                           "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}'},
                          img_key, sub_key, int(clock()))
            d = get(f"{_BILI_FEED}?{q}", cookie)
            data = d.get("data") if isinstance(d, dict) and isinstance(d.get("data"), dict) else {}
            items = data.get("items") or []
            if isinstance(d, dict) and d.get("code") == 0 and items:
                break
            shapes.append(bili_shape(d))
        else:
            raise BiliFeedProblem(f"space feed page {page + 1} listed nothing in {_BILI_TRIES} tries "
                                  f"(risk control, not \"no post\"): {shapes[-1]}")
        dated = [t for t in map(_bili_at, items) if t]
        if not dated:
            raise BiliFeedProblem(f"space feed page {page + 1}: none of {len(items)} items has "
                                  f"modules.module_author.pub_ts (shape changed?): "
                                  f"{json.dumps(items[0], ensure_ascii=False)[:400]}")
        hit = wuwa_bili_post(items, ver, now)
        if hit:
            return _BILI_POST_URL.format(id=hit[0]), hit[1], hit[2]
        offset = str(data.get("offset") or "")
        if min(dated) < now - _BILI_OLDEST:
            # a door's miss, INFO: _wuwa_poster_span warns once when no door has it
            log.info("Bilibili feed: no %s version-news post back to %s (page %d)",
                        ver or "current", f"{min(dated):%Y-%m-%d}", page + 1)
            return None
        if not data.get("has_more") or not offset:
            log.info("Bilibili feed: no %s version-news post, the feed ends at page %d",
                        ver or "current", page + 1)
            return None
    log.info("Bilibili feed: no %s version-news post in %d pages", ver or "current", _BILI_PAGES)
    return None


class KuroListProblem(RuntimeError):
    """The 库街区 official-news list answered without a list: a source problem,
    not "no post" (the same distinction as BiliFeedProblem)."""


def _kuro_poster(ver: "str | None", now: datetime, get=None):
    """(page URL, title, images) of the 库街区 version-news post; None when the
    list reads fine but the post is not in it. Raises KuroListProblem when the
    answer carries no list."""
    def post(path: str, payload: dict) -> dict:
        h = dict(_KURO_BBS_HDR, **{"Content-Type": "application/x-www-form-urlencoded"})
        return hub._json(_KURO + path, _UA_BROWSER, urllib.parse.urlencode(payload).encode(), h)
    get = get or post
    answer = get(_KURO_NEWS, {"gameId": 3, "eventType": 2, "pageSize": 200})
    events = ((answer if isinstance(answer, dict) else {}).get("data") or {}).get("list")
    if not isinstance(events, list):
        raise KuroListProblem(f"official-news list came back without a list: "
                              f"{json.dumps(answer, ensure_ascii=False)[:300]}")
    hit = wuwa_news_post(events, ver, now)
    if not hit:
        # Not a fault by itself: the Bilibili copy is the next door
        # (_wuwa_poster_span), and only both missing is one (10-05 21:47).
        log.info("库街区官方资讯里没找到 %s 版本资讯帖（列表 %d 条）", ver or "当期", len(events))
        return None
    pid, title, _at = hit
    detail = ((get(_KURO_POST, {"isOnlyPublisher": 0, "postId": pid, "showOrderType": 2}).get("data") or {})
              .get("postDetail") or {})
    imgs = [(str(c["url"]), int(c.get("imgWidth") or 0), int(c.get("imgHeight") or 0))
            for c in detail.get("postContent") or [] if c.get("contentType") == 2 and c.get("url")]
    return _KURO_POST_URL.format(id=pid), title, imgs


# The banner notices (Kuro BBS official eventType 3, posted about 11:00 Beijing the
# day before a half opens) print the span as text, to the minute: the second half
# of 3.6 gives its start and end dates, the first half of 3.7 gives "after the 3.7
# update" and its end (fixtures ww-kuro-gacha-posts.json). Until the second half's notice is out, its start is the first half's printed
# end plus one minute. Checked against every pair the list still holds
# (2025-08-13..2026-09-29): 2.6 09-17, 2.7 10-30, 2.8 12-11, 3.0 01-15, 3.1 02-26,
# 3.2 04-09, 3.3 05-21, 3.5 07-30, 3.6 09-10 - first half ends 09:59, second
# opens 10:00 the same day, 9 of 9 (3.4's first-half notice is not in the list).
_WW_GACHA_SPAN = re.compile(r"活动时间[✦\s：:]*(?:(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})[:：](\d{2})|(\d+\.\d+)版本更新后)"
                            r"\s*[~～\-—至]+\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})[:：](\d{2})")
_WW_GACHA_CHECKED = "2.6–3.6 九期第一期结束 09:59、第二期同日 10:00 开，9 期全中"


def _kuro_text(detail: dict) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", " ".join(
        str(c.get("content") or "") for c in detail.get("postContent") or [] if c.get("contentType") != 2))))


def wuwa_gacha_notice(events: list, detail_of, ver: "str | None", pool: str, now: datetime
                      ) -> "tuple[str, datetime, datetime | None, str] | None":
    """`pool`'s start from the 库街区 banner notices: ("公告原文", start, end, where)
    once its own notice is out, else ("推导", first half's end + 1 min, None, where)
    from the version's first-half notice, else None. `detail_of(post id)` is the
    getPostDetail postDetail."""
    rows = []
    for e in events or []:
        title = str(e.get("postTitle") or "").replace("\xa0", " ")
        try:
            at = datetime.fromtimestamp(int(e.get("publishTime")) / 1000, tz=SERVER_TZ).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        if at <= now and "唤取" in title:
            rows.append((at, str(e.get("postId") or ""), title))
    rows.sort(reverse=True)
    tag = f"【{ver}版本】" if ver else ""
    own = [r for r in rows if f"[{pool}]" in r[2] or (tag and tag in r[2] and "第二期" in r[2])]
    first = [r for r in rows if tag and tag in r[2] and "第一期" in r[2]]
    for at, pid, title in own[:3]:
        text = _kuro_text(detail_of(pid))
        if f"「{pool}」" not in text and f"[{pool}]" not in title:
            continue
        m = _WW_GACHA_SPAN.search(text)
        if m and m.group(1):
            g = [int(x) for x in m.groups()[:5]] + [int(x) for x in m.groups()[6:]]
            start, end = datetime(*g[:5]), datetime(*g[5:])
            return "公告原文", start, end, f"{_KURO_POST_URL.format(id=pid)}「{title}」{at:%m-%d %H:%M} 发"
    for at, pid, title in first[:1]:
        m = _WW_GACHA_SPAN.search(_kuro_text(detail_of(pid)))
        if m:
            g = [int(x) for x in m.groups()[6:]]
            end1 = datetime(*g)
            return ("推导", end1 + timedelta(minutes=1), None,
                    f"{_KURO_POST_URL.format(id=pid)}「{title}」{at:%m-%d %H:%M} 发，第一期 {end1:%m-%d %H:%M} 结束")
    return None


def _kuro_gacha(ver: "str | None", pool: str, now: datetime, get=None):
    def post(path: str, payload: dict) -> dict:
        h = dict(_KURO_BBS_HDR, **{"Content-Type": "application/x-www-form-urlencoded"})
        return hub._json(_KURO + path, _UA_BROWSER, urllib.parse.urlencode(payload).encode(), h)
    get = get or post
    events = (get(_KURO_NEWS, {"gameId": 3, "eventType": 3, "pageSize": 100}).get("data") or {}).get("list")

    def detail_of(pid: str) -> dict:
        return ((get(_KURO_POST, {"isOnlyPublisher": 0, "postId": pid, "showOrderType": 2}).get("data") or {})
                .get("postDetail") or {})
    return wuwa_gacha_notice(events or [], detail_of, ver, pool, now)


_AGENT_DOWN = object()


def _poster_read(what: str, page: str, title: str, imgs: list, pool: str, char: str, now: datetime,
                 read_image, tr: "Trace", failed: "list[str] | None" = None):
    """Read the long images of one copy of the post; the span, None, or
    _AGENT_DOWN when the OCR agent failed (each strip may wait up to 90 s, so
    nothing else is tried this run). An image that could not be read is
    appended to `failed`, in words."""
    for n, (url, w, h) in enumerate(imgs, 1):
        # only the long posters; the cover and the small cards carry no schedule
        if h <= 2.5 * max(w, 1):
            continue
        try:
            lines = read_image(url)
        except Exception as e:
            # a download that timed out (the posters are several MB; 2026-10-01
            # 02:5x the Mac's fetch of one timed out) says nothing about the OCR
            # agent: go on to the next image (INFO: the next image or door may
            # still give the span; none giving it is _wuwa_poster_span's WARNING)
            log.info("%s版本资讯第 %d 张图读图失败", what, n, exc_info=True)
            if failed is not None:
                failed.append(f"{what}那一帖第 {n} 张图没读下来（{type(e).__name__}）")
            continue
        if lines is None:
            log.warning("%s版本资讯第 %d 张图没读出来，这次不再读后面的图", what, n)
            if failed is not None:
                failed.append(f"{what}那一帖第 {n} 张图没读出来（读图没有结果）")
            return _AGENT_DOWN
        span = parse_wuwa_poster(lines, pool, char)
        if span and span[1] > now:
            tr.starts |= _stamps(span[0])
            tr.ends |= _stamps(span[1])
            tr.src("鸣潮", "版本资讯", f"{what} {page}「{title}」第 {n} 张图 {url}",
                   f"{pool} {span[0]:%Y-%m-%d %H:%M}~{span[1]:%Y-%m-%d %H:%M}（服务器时间）")
            return span
    log.info("%s %s 的长图里没读到「%s」的唤取时间", what, page, pool)
    return None


def _door(tr: "Trace", what: str, outcome: str) -> None:
    """One door's outcome in the trace, 「鸣潮｜版本资讯门｜<door>｜…」: the machine
    checks #3 (the Bilibili door) and #58 (the 库街区 door) read it."""
    tr.src("鸣潮", "版本资讯门", what, outcome[:300])


def _wuwa_poster_span(ver: "str | None", pool: str, char: str, now: datetime,
                      read_image, tr: "Trace", get=None, bili=None) -> "tuple[datetime, datetime] | None":
    """`pool`'s (start, end) off the version-news post's long images: the 库街区
    copy first (plain JSON, a 733-wide poster), the Bilibili copy only when that
    gave nothing, so an evening costs one poster's OCR. None when neither did."""
    if not read_image:
        return None
    # A door that misses is only a fault when the other one misses too: until
    # 2026-10-06 each door's miss was its own WARNING (10-05 21:47 「库街区官方资讯
    # 里没找到 3.7 版本资讯帖」) whether or not Bilibili then had the post. Now
    # each miss is INFO and the WARNING is one line, when no door gave the span.
    # A door or an image that FAILED (an exception, not "no such post") while
    # another one gave the span is a fault the relay got over: one WARNING
    # marked errwatch.recovered(), the daily report only (the user on 2026-10-06
    # 05:07 about faults the relay got over: 「报错后自己好了的，只进日报、不进群」).
    misses: list[str] = []
    failed: list[str] = []
    for what, find in (("库街区", lambda: hub._kuro_poster(ver, now, get)),
                       ("B 站", lambda: hub._bili_poster(ver, now, bili))):
        try:
            found = find()
        except Exception as e:
            # the raw shape is in the message (BiliFeedProblem); the next door
            # is still tried and the problem stays in the trace
            log.info("%s版本资讯帖取不到", what, exc_info=True)
            tr.problems.append(f"鸣潮｜版本资讯｜{what}｜{type(e).__name__}: {e}")
            misses.append(f"{what}取不到（{type(e).__name__}）")
            failed.append(misses[-1])
            _door(tr, what, f"取不到：{type(e).__name__}: {e}")
            continue
        if not found:
            misses.append(f"{what}没有这一帖")
            _door(tr, what, "没有这一帖")
            continue
        had = len(failed)
        span = _poster_read(what, *found, pool, char, now, read_image, tr, failed)
        mine = "；".join(failed[had:])
        if span is _AGENT_DOWN:
            _door(tr, what, f"长图没读出来：{mine}")
            return None       # _poster_read warned: the OCR agent itself is down
        if span:
            _door(tr, what, f"给出了「{pool}」的唤取时间 {span[0]:%m-%d %H:%M}～{span[1]:%m-%d %H:%M}"
                  + (f"（{mine}）" if mine else ""))
            if failed:
                from ark_relay.features.alarm import errwatch  # noqa: PLC0415
                # the first line is quoted in the daily report: no Latin letters ("B 站")
                log.warning("鸣潮 %s 版本资讯帖有 %d 处没取到，%s那一帖给出了「%s」的唤取时间\n%s",
                            ver or "当期", len(failed), "哔哩哔哩" if what == "B 站" else what, pool,
                            "；".join(failed), extra=errwatch.recovered())
            return span
        misses.append(f"{what}那一帖的长图里没读到「{pool}」")
        _door(tr, what, f"长图里没读到「{pool}」" + (f"（{mine}）" if mine else ""))
    log.warning("鸣潮 %s 版本资讯帖里没拿到「%s」的唤取时间（%s）：第二期卡池几点开，这次读不到长图上的官方时刻",
                ver or "当期", pool, "；".join(misses))
    return None


def image_reader(state_dir):
    """OCR for an official image: Windows.Media.Ocr through the desktop agent
    (desktop.py), cached per URL so the daily report does not spawn it again.
    None off Windows, where there is no agent."""
    import hashlib  # noqa: PLC0415
    import os  # noqa: PLC0415

    from ark_relay.core import desktop  # noqa: PLC0415
    from ark_relay.core.config import atomic_write_bytes, atomic_write_text  # noqa: PLC0415
    if os.name != "nt":
        return None
    d = Path(state_dir) / "desktop"
    cache_f = d / "image-ocr.json"

    def read(url: str) -> "list | None":
        try:
            cache = json.loads(cache_f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        # The key carries the read recipe: a result cached before the not-tall images
        # were enlarged (the garbled 10-06 calendar) must not be served again.
        key = f"{url}#2x"
        if key not in cache:
            req = urllib.request.Request(url, headers={"User-Agent": _UA_BROWSER})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            stem = f"img-{hashlib.sha1(url.encode()).hexdigest()[:10]}"
            d.mkdir(parents=True, exist_ok=True)

            def ocr_png(png: bytes, i: int) -> "list | None":
                p = d / f"{stem}-{i}.png"
                atomic_write_bytes(p, png)
                return desktop.Desktop(state_dir).read_file(p)
            try:
                # The CDN serves WebP whatever the extension says; the Windows
                # decoder only reads WebP with the Store codec installed.
                got = ocr_strips(raw, ocr_png)
            except Exception:
                log.warning("官方图转 PNG 失败，原样交给系统 OCR", exc_info=True)
                path = d / f"{stem}.webp"
                atomic_write_bytes(path, raw)
                got = desktop.Desktop(state_dir).read_file(path)
            # [] is a read that found no text: cached too, so a poster of ten strips
            # is not read again every evening
            if got is None:
                return None
            cache[key] = [vars(x) for x in got]
            atomic_write_text(cache_f, json.dumps(cache, ensure_ascii=False))
        return [desktop.Line(**o) for o in cache[key]]
    return read


# Long posters (the 「版本资讯」 images are 733x10000 on 库街区, 1080x14717 on
# Bilibili) come back as three garbled lines when OCR'd whole: the engine shrinks
# them until the text is unreadable (2026-10-01, Vision on the Mac and the 01:37
# read). So every image is cut into strips that overlap, a line cut by one
# boundary being whole in the next, and narrow ones are enlarged first. Each strip
# stays within _STRIP_MAX px a side: OcrEngine.MaxImageDimension exists but its
# documentation gives no number.
_STRIP = 1400
_STRIP_OVERLAP = 200
_STRIP_MAX = 2000
_STRIP_MIN_WIDTH = 1000
# A not-tall image is enlarged only while its enlarged side stays below this.
_ONE_STRIP_MAX = 8000


def strip_plan(w: int, h: int) -> "tuple[float, list[tuple[int, int]]]":
    """(scale, [(top, height)] in source pixels). Anything not much taller than
    wide is one strip, enlarged two times while it stays under _ONE_STRIP_MAX px
    a side: the calendar (1080x2159) read at its own size came out as 「]0．22」 /
    「9.30司1]]」 on the machine's Windows OCR (2026-10-06, mc #2), and the same
    image at two times read the second-half banner's date right."""
    if h <= 2.5 * w:
        return (2.0 if max(w, h) * 2 <= _ONE_STRIP_MAX else 1.0), [(0, h)]
    scale = min(2.0, _STRIP_MIN_WIDTH / w) if w < _STRIP_MIN_WIDTH else min(1.0, _STRIP_MAX / w)
    size = min(_STRIP, int(_STRIP_MAX / scale))
    tops, top = [], 0
    while True:
        tops.append((top, min(size, h - top)))
        if top + size >= h:
            return scale, tops
        top += size - _STRIP_OVERLAP


def ocr_strips(raw: bytes, ocr_png) -> "list | None":
    """OCR `raw` (any format PIL reads) strip by strip; `ocr_png(png_bytes, i)` reads
    one strip. Lines come back in source-image coordinates; a line near an inner
    edge is taken from the strip where it sits away from the edge, so the overlap
    does not double it. None when any strip could not be read (nothing half-read
    gets cached)."""
    from io import BytesIO  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    from ark_relay.core.desktop import Line  # noqa: PLC0415
    im = Image.open(BytesIO(raw)).convert("RGB")
    scale, plan = strip_plan(*im.size)
    out = []
    for i, (top, h) in enumerate(plan):
        part = im.crop((0, top, im.size[0], top + h))
        if scale != 1.0:
            part = part.resize((round(part.size[0] * scale), round(h * scale)), Image.LANCZOS)
        buf = BytesIO()
        part.save(buf, format="PNG")
        got = ocr_png(buf.getvalue(), i)
        if got is None:
            return None
        lo = _STRIP_OVERLAP // 2 if i > 0 else 0
        hi = h - _STRIP_OVERLAP // 2 if i < len(plan) - 1 else h
        for ln in got:
            y = round(ln.y / scale)
            if lo <= y < hi:
                out.append(Line(ln.text, round(ln.x / scale), top + y, round(ln.w / scale), round(ln.h / scale)))
    return out


# While the second half of a version runs, the next version's first half has no banner
# list yet, but two things are published early: the maintenance window (the site's
# 「X版本更新维护预告」, about a week ahead; the first half opens when it ends - 3.6:
# 08-20 04:00~11:00, banner start 11:00) and the first half's end, printed on the
# version-news poster as 「X.Y版本更新后～2026年…09:59」 and, the day before, in the Kuro
# BBS first-half notice. The user, 2026-10-06 18:03: the period after the next one must
# have its time complete, start and end.
_WW_FIRST_END = re.compile(r"版本更新后[~～\-—一至、]*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})[:：](\d{2})")


def parse_wuwa_poster_first_end(lines: list) -> "datetime | None":
    """The first half's end off a version-news poster: the 「…版本更新后～<date>」 row
    under a 「…活动唤取」 heading. The poster prints the same shape for plain
    activities (「3.6版本更新后、2026年9月29日03:59」), which is why the heading is required."""
    rows = _rows(lines)
    for i, (_y, txt) in enumerate(rows):
        m = _WW_FIRST_END.search(txt)
        if m and any("唤取" in r[1] for r in rows[max(0, i - 3):i]):
            try:
                return datetime(*[int(x) for x in m.groups()])
            except ValueError:
                return None
    return None


def wuwa_first_half_notice_end(events: list, detail_of, ver: str, now: datetime
                               ) -> "tuple[datetime, str] | None":
    """(end, where) of version `ver`'s first half from its Kuro BBS banner notice
    (「【3.7版本】[角色/武器活动唤取・第一期]」, out the day before the version opens)."""
    rows = []
    for e in events or []:
        title = str(e.get("postTitle") or "").replace("\xa0", " ")
        try:
            at = datetime.fromtimestamp(int(e.get("publishTime")) / 1000, tz=SERVER_TZ).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        if at <= now and f"【{ver}版本】" in title and "第一期" in title and "唤取" in title:
            rows.append((at, str(e.get("postId") or ""), title))
    for at, pid, title in sorted(rows, reverse=True)[:1]:
        m = _WW_GACHA_SPAN.search(_kuro_text(detail_of(pid)))
        if m:
            end = datetime(*[int(x) for x in m.groups()[6:]])
            return end, f"{_KURO_POST_URL.format(id=pid)}「{title}」{at:%m-%d %H:%M} 发"
    return None


def _kuro_default(path: str, payload: dict) -> dict:
    h = dict(_KURO_BBS_HDR, **{"Content-Type": "application/x-www-form-urlencoded"})
    return hub._json(_KURO + path, _UA_BROWSER, urllib.parse.urlencode(payload).encode(), h)
