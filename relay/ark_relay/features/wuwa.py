"""Wuthering Waves past banners and maintenance windows, read from Kuro BBS
news and the official site's article index."""
from __future__ import annotations

import json
import re
import html
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from ark_relay.features import banners as hub
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.banners import record_history, _UA_BROWSER, log, _stamps, Trace, Banner, crosscheck_fix, newest_version, _SWAP, upcoming

_WW_HIST_TITLE = re.compile(r"^[\[「<《]([^\]」>》]+)[\]」>》](角色|武器)(?:活动|联动|忆旅)?唤取(?:——「([^」]+)」概率UP)?")


def wuwa_maint_window(articles: list, article_text, ver: str) -> "tuple[datetime, datetime] | None":
    """Version `ver`'s update maintenance window off the site's notice, any date
    (`wuwa_maintenance` only looks forward). `article_text(id)` is the article JSON text."""
    for a in articles or []:
        if re.search(rf"(?<![\d.]){re.escape(ver)}版本更新维护预告", str(a.get("articleTitle") or "")):
            body = json.loads(article_text(a.get("articleId"))).get("articleContent") or ""
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body).replace("&nbsp;", " "))
            w = _WW_MAINT.search(txt)
            if w:
                g = [int(x) for x in w.groups()]
                return datetime(g[0], g[1], g[2], g[3], g[4]), datetime(g[5], g[6], g[7], g[8], g[9])
    return None


def wuwa_history(events: list, detail_of, articles: list, article_text, now: datetime) -> "list[dict]":
    """Every ended period still readable, oldest first: {ver, part, pools, weapons,
    start, start_how, end, where}. `part` is 第一期 for a half that opens with the version,
    第二期 for one with its own start date. A half's pools are the notices that share
    one span; its version is the one whose maintenance window ended last before its
    start (the notice's own 「X版本更新后」 when it has one), 1.0 before the first."""
    rows = []
    for e in events or []:
        title = str(e.get("postTitle") or "").replace("\xa0", " ")
        try:
            at = datetime.fromtimestamp(int(e.get("publishTime")) / 1000, tz=SERVER_TZ).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        if "唤取" in title and "【" not in title:
            rows.append((at, str(e.get("postId") or ""), title))
    rows.sort()
    wins: "dict[str, tuple[datetime, datetime]]" = {}
    for a in articles or []:
        mv = re.search(r"(\d+\.\d+)版本更新维护预告", str(a.get("articleTitle") or ""))
        if mv and (w := wuwa_maint_window(articles, article_text, mv.group(1))):
            wins[mv.group(1)] = w
    halves: "dict[tuple, dict]" = {}
    for _at, pid, title in rows:
        text = _kuro_text(detail_of(pid))
        m = _WW_GACHA_SPAN.search(text)
        if not m:
            continue
        g = m.groups()
        end = datetime(*[int(x) for x in g[6:]])
        start = datetime(*[int(x) for x in g[:5]]) if g[0] else None
        key = (g[5] or start, end)
        h = halves.setdefault(key, {"ver": g[5], "part": "第一期" if g[5] else "第二期", "pools": [], "weapons": [],
                                    "start": start, "start_how": "公告原文" if start else "",
                                    "end": end, "where": []})
        h["where"].append(_KURO_POST_URL.format(id=pid))
        tm = _WW_HIST_TITLE.match(title)
        if tm:
            h["pools" if tm.group(2) == "角色" else "weapons"].append(tm.group(1))
    out = []
    for h in halves.values():
        if h["end"] >= now:
            continue
        if h["start"] is None and h["ver"] in wins:
            win = wins[h["ver"]]
            h["start"], h["start_how"] = win[1], f"{h['ver']}版本更新维护 {win[0]:%m-%d %H:%M}～{win[1]:%H:%M} 结束后开"
        if not h["ver"]:
            before = [v for v, w in wins.items() if h["start"] and w[1] <= h["start"]]
            h["ver"] = max(before, key=lambda v: wins[v][1]) if before else "1.0"
        out.append(h)
    return sorted(out, key=lambda h: (h["end"], h["start"] or h["end"]))


def update_wuwa_history(state_dir, now: datetime, get=None, article_get=None, budget: int = 80
                        ) -> "tuple[list[dict], list[str]]":
    """Read the ended Wuthering Waves periods the way the next one is read and record them.
    Post texts never change, so each is fetched once into `banners/ww-notices.json`
    (at most `budget` fetches a run, the site's maintenance notices first, then the newest
    notices, so the whole history fills in over a few days)."""
    from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
    get = get or _kuro_default
    article_get = article_get or (lambda u: hub._text(u, _UA_BROWSER))
    cache_f = Path(state_dir) / "banners" / "ww-notices.json"
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    texts, art_texts = cache.setdefault("text", {}), cache.setdefault("articles", {})
    events = (kuro_checked(get(_KURO_NEWS, {"gameId": 3, "eventType": 3, "pageSize": 1000}), "唤取公告列表")
              .get("data") or {}).get("list") or []
    gacha = sorted((e for e in events if "唤取" in str(e.get("postTitle") or "")),
                   key=lambda e: -int(e.get("publishTime") or 0))
    articles = [a for a in json.loads(article_get(_WW_SITE_ARTICLES))
                if "版本更新维护预告" in str(a.get("articleTitle") or "")]
    # A fetch that fails raises out of here (update_history reports it); what was
    # fetched before it is kept, and the failed post is fetched again next run
    # instead of being cached as an empty text for ever.
    try:
        for a in articles:
            if str(a.get("articleId")) not in art_texts and budget > 0:
                budget -= 1
                body = json.loads(article_get(_WW_SITE_ARTICLE.format(id=a.get("articleId")))).get("articleContent") or ""
                art_texts[str(a.get("articleId"))] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body).replace("&nbsp;", " "))
        for e in gacha:
            pid = str(e.get("postId"))
            if pid not in texts and budget > 0:
                budget -= 1
                d = ((kuro_checked(get(_KURO_POST, {"isOnlyPublisher": 0, "postId": pid, "showOrderType": 2}),
                                   f"帖子 {pid}").get("data") or {})
                     .get("postDetail") or {})
                texts[pid] = _kuro_text(d)
    finally:
        cache_f.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(cache_f, json.dumps(cache, ensure_ascii=False))
    hist = wuwa_history([e for e in gacha if str(e.get("postId")) in texts],
                        lambda pid: {"postContent": [{"contentType": 1, "content": texts[pid]}]},
                        [a for a in articles if str(a.get("articleId")) in art_texts],
                        lambda aid: json.dumps({"articleContent": art_texts[str(aid)]}), now)
    return hist, record_history(state_dir, "鸣潮", hist)


# The official site's article index (what mc.kurogames.com/main/news renders): a
# plain JSON list, articleType 51 = 新闻 (PVs, combat demos), 52 = 公告.
_WW_SITE_ARTICLES = "https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/json/G152/zh/ArticleMenu.json"


_WW_SITE_ARTICLE = "https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/json/G152/zh/article/{id}.json"
_WW_MAINT = re.compile(r"更新维护时间[：:\s]*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})\s*[~～-]\s*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})")


def wuwa_maintenance(articles: list, now: datetime, get=None) -> "tuple[str, datetime, datetime] | None":
    """The next version's maintenance window from the official site's
    「X版本更新维护预告」 post (published about a week ahead: 3.6's on 08-13 for
    08-20): (version label, maintenance start, maintenance end). None until it is
    posted or once the window has passed.
    """
    got = wuwa_maint_notice(articles, now, get)
    return got if got and got[2] > now else None


def wuwa_maint_notice(articles: list, now: datetime, get=None) -> "tuple[str, datetime, datetime] | None":
    """The newest 「X版本更新维护预告」 posted by `now` (naive, server clock) and
    the window it gives, passed or not: (version label, start, end). None when
    there is no such post or its body has no window. Also read by
    maintenance.wuwa_window.
    """
    get = get or (lambda u: hub._text(u, _UA_BROWSER))
    cands = []
    for a in articles or []:
        title = str(a.get("articleTitle") or "")
        m = re.search(r"(\d+\.\d+)版本更新维护预告", title)
        if m:
            try:
                at = datetime.strptime(str(a.get("startTime") or a.get("createTime"))[:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            if at <= now:
                cands.append((at, m.group(1), a.get("articleId")))
    if not cands:
        return None
    _at, ver, aid = max(cands)
    body = json.loads(get(_WW_SITE_ARTICLE.format(id=aid))).get("articleContent") or ""
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body).replace("&nbsp;", " "))
    w = _WW_MAINT.search(txt)
    if not w:
        return None
    g = [int(x) for x in w.groups()]
    return ver, datetime(g[0], g[1], g[2], g[3], g[4]), datetime(g[5], g[6], g[7], g[8], g[9])


_KURO = "https://api.kurobbs.com"


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


_BILI_UID = 1955897084
_BILI_SPI = "https://api.bilibili.com/x/frontend/finger/spi"
_BILI_NAV = "https://api.bilibili.com/x/web-interface/nav"
_BILI_FEED = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
_BILI_POST_URL = "https://www.bilibili.com/opus/{id}"
_BILI_MIX = (46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
             33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
             61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
             36, 20, 34, 44, 52)
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


def _bili_opus(it: dict) -> dict:
    return (((it.get("modules") or {}).get("module_dynamic") or {}).get("major") or {}).get("opus") or {}


def _live_dict_text(d: dict) -> list[str]:
    info = d.get("live_play_info")
    return [str(d.get("title") or ""),
            str(info.get("title") or "") if isinstance(info, dict) else ""]


def _bili_live_text(live) -> str:
    if isinstance(live, str):
        try:
            live = json.loads(live)
        except ValueError:
            return live
    if not isinstance(live, dict):
        return ""
    parts = _live_dict_text(live)
    content = live.get("content")
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except ValueError:
            parts.append(content)
        else:
            parts.extend(_live_dict_text(parsed) if isinstance(parsed, dict)
                         else [parsed] if isinstance(parsed, str) else [])
    elif isinstance(content, dict):
        parts.extend(_live_dict_text(content))
    return "\n".join(p for p in parts if p)


def _bili_text(it: dict) -> str:
    """All user-visible text of a Bilibili dynamic item (opus, archive, live_rcmd, desc)."""
    md = (it.get("modules") or {}).get("module_dynamic")
    if not isinstance(md, dict):
        return ""
    major = md.get("major")
    major = major if isinstance(major, dict) else {}
    opus = major.get("opus")
    opus = opus if isinstance(opus, dict) else {}
    summary = opus.get("summary")
    archive = major.get("archive")
    archive = archive if isinstance(archive, dict) else {}
    desc = md.get("desc")
    desc = desc if isinstance(desc, dict) else {}
    parts = [
        str(opus.get("title") or ""),
        str((summary if isinstance(summary, dict) else {}).get("text") or ""),
        str(archive.get("title") or ""),
        str(archive.get("desc") or ""),
        _bili_live_text(major.get("live_rcmd")),
        str(desc.get("text") or ""),
    ]
    return "\n".join(p for p in parts if p)


def wuwa_bili_post(items: list, ver: "str | None", now: datetime
                   ) -> "tuple[str, str, list[tuple[str, int, int]]] | None":
    """(dynamic id, first line, [(image URL, width, height)]) of the newest
    「版本资讯」 dynamic up to `now`, for version `ver` when known."""
    best = None
    for it in items or []:
        op = _bili_opus(it)
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
    preview_at: datetime | None = None
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
        if ver:
            for it in items:
                at = _bili_at(it)
                txt = _bili_text(it)
                if at and at <= now and f"{ver}版本前瞻" in txt and (preview_at is None or at > preview_at):
                    preview_at = at
            unpinned = dated[1:] if len(dated) > 1 and dated[0] < dated[1] else dated
            if preview_at is not None and min(unpinned) <= preview_at:
                log.info("Bilibili feed: no %s version-news post; page %d reached %s, past %s版本前瞻 (%s)",
                         ver, page + 1, f"{min(unpinned):%Y-%m-%d}", ver, f"{preview_at:%Y-%m-%d}")
                return None
        offset = str(data.get("offset") or "")
        if max(dated) < now - _BILI_OLDEST:
            # a door's miss, INFO: _wuwa_poster_span warns once when no door has it
            log.info("Bilibili feed: no %s version-news post; page %d's newest item is %s, past the cutoff",
                     ver or "current", page + 1, f"{max(dated):%Y-%m-%d}")
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


class KuroAnswerProblem(RuntimeError):
    """库街区 answered HTTP 200 with an error code in the body: a failed fetch, not
    "nothing found"."""


_KURO_OK = 200


def kuro_checked(answer, what: str):
    """`answer` unchanged, or KuroAnswerProblem when its body carries a code other
    than 200. Without the check an error body (data null) read as an empty list or
    an empty post, i.e. "nothing found". A body with no `code` at all is left to
    the caller's shape checks, as before."""
    if isinstance(answer, dict) and "code" in answer and answer.get("code") != _KURO_OK:
        raise KuroAnswerProblem(f"库街区 {what} 返回 code={answer.get('code')!r}："
                                f"{json.dumps(answer, ensure_ascii=False)[:300]}")
    return answer


def _kuro_poster(ver: "str | None", now: datetime, get=None):
    """(page URL, title, images) of the 库街区 version-news post; None when the
    list reads fine but the post is not in it. Raises KuroListProblem when the
    answer carries no list."""
    def post(path: str, payload: dict) -> dict:
        h = dict(_KURO_BBS_HDR, **{"Content-Type": "application/x-www-form-urlencoded"})
        return hub._json(_KURO + path, _UA_BROWSER, urllib.parse.urlencode(payload).encode(), h)
    get = get or post
    # An error body has no list either: KuroListProblem below covers it.
    answer = get(_KURO_NEWS, {"gameId": 3, "eventType": 2, "pageSize": 200})
    events = ((answer if isinstance(answer, dict) else {}).get("data") or {}).get("list")
    if not isinstance(events, list):
        raise KuroListProblem(f"official-news list came back without a list: "
                              f"{json.dumps(answer, ensure_ascii=False)[:300]}")
    hit = wuwa_news_post(events, ver, now)
    if not hit:
        log.info("库街区官方资讯里没找到 %s 版本资讯帖（列表 %d 条）", ver or "当期", len(events))
        return None
    pid, title, _at = hit
    detail = ((kuro_checked(get(_KURO_POST, {"isOnlyPublisher": 0, "postId": pid, "showOrderType": 2}),
                            f"帖子 {pid}").get("data") or {})
              .get("postDetail") or {})
    imgs = [(str(c["url"]), int(c.get("imgWidth") or 0), int(c.get("imgHeight") or 0))
            for c in detail.get("postContent") or [] if c.get("contentType") == 2 and c.get("url")]
    return _KURO_POST_URL.format(id=pid), title, imgs


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
    events = (kuro_checked(get(_KURO_NEWS, {"gameId": 3, "eventType": 3, "pageSize": 100}), "唤取公告列表")
              .get("data") or {}).get("list")

    def detail_of(pid: str) -> dict:
        return ((kuro_checked(get(_KURO_POST, {"isOnlyPublisher": 0, "postId": pid, "showOrderType": 2}),
                              f"帖子 {pid}").get("data") or {})
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
                from ark_relay.features import errwatch  # noqa: PLC0415
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

    from ark_relay.core import config, desktop  # noqa: PLC0415
    from ark_relay.core.config import atomic_write_bytes, atomic_write_text  # noqa: PLC0415
    if not config.IS_WINDOWS:
        return None
    d = Path(state_dir) / "desktop"
    cache_f = d / "image-ocr.json"

    def read(url: str) -> "list | None":
        try:
            cache = json.loads(cache_f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
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


_DOTS = str.maketrans({"\u30fb": "\u00b7", "\uff65": "\u00b7", "\u2022": "\u00b7", "\u2027": "\u00b7"})


def _one_dot(name: str) -> str:
    return name.translate(_DOTS)


def wuwa_tabs(home: dict) -> "tuple[list[tuple[str, str, datetime, datetime]], list[str], int]":
    """The homepage's character-banner tabs: ([(banner name, the character's entry
    id or "", start, end)], the tabs whose dateRange cannot be read, how many tabs)."""
    out: "list[tuple[str, str, datetime, datetime]]" = []
    bad: list[str] = []
    n_tabs = 0
    content = ((home or {}).get("data") or {}).get("contentJson") or {}
    for m in content.get("sideModules") or []:
        title = str(m.get("title") or "")
        if "唤取" not in title or "角色" not in title:
            continue
        for tab in (m.get("content") or {}).get("tabs") or []:
            n_tabs += 1
            dr = (tab.get("countDown") or {}).get("dateRange") or []
            try:
                if len(dr) != 2:
                    raise ValueError(f"dateRange 是 {dr!r}")
                a = datetime.strptime(f"{dr[0]}:00", "%Y-%m-%d %H:%M:%S")
                b = datetime.strptime(f"{dr[1]}:59", "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError) as e:
                bad.append(f"「{str(tab.get('name') or '').strip()}」（{type(e).__name__}: {e}）")
                continue
            imgs = tab.get("imgs") or []
            eid = (imgs[0].get("linkConfig") or {}).get("entryId") if imgs else None
            out.append((str(tab.get("name") or "").strip(), str(eid) if eid else "", a, b))
    return out, bad, n_tabs


def parse_wuwa(home: dict, name_of) -> list[Banner]:
    """Raises ValueError when there are character tabs but none has a readable
    dateRange (an empty return would read as "none", see _wuwa); some tabs
    unreadable is one WARNING. A tab whose character has no name is left out
    (_wuwa names it from the official notices when it can)."""
    out: list[Banner] = []
    tabs, bad, n_tabs = wuwa_tabs(home)
    for name, eid, a, b in tabs:
        who = _one_dot((name_of(eid) if eid else "").strip())
        if who:
            out.append(Banner("鸣潮", name, (who,), a, b))
    if bad and len(bad) == n_tabs:
        raise ValueError(f"库街区 {n_tabs} 个角色唤取都读不出起止时间（countDown.dateRange）："
                         + "；".join(bad))
    if bad:
        log.warning("鸣潮：库街区 %d 个角色唤取里有 %d 个读不出起止时间，这几个池子这次没报\n%s",
                    n_tabs, len(bad), "；".join(bad))
    out.sort(key=lambda x: x.end)
    return out


def wuwa_teased(records: list, now: datetime) -> list[str]:
    """Characters the Kuro wiki marks as previewed (announced, not yet released)."""
    out: list[str] = []
    for r in records or []:
        c = r.get("content") or {}
        if not c.get("showTeaserIcon") or str(c.get("showTeaserIconNum")) != "2":
            continue
        rng = c.get("teaserDateRange") or []
        try:
            a = datetime.strptime(str(rng[0])[:19], "%Y-%m-%d %H:%M:%S")
            b = datetime.strptime(str(rng[1])[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, IndexError):
            continue
        name = _one_dot(str(r.get("name") or "").strip())
        if name and a <= now <= b:
            out.append(name)
    return out


# The 「全新角色」 section in the body of the official bulletin has a fixed format:
#     5星共鸣者「景燃」（热熔 | 长刃）
#     ...
#     ※可通过[身赴三途]角色活动唤取获得。
_WW_ROLE = re.compile(r"5星共鸣者[「\[]([^」\]]+)[」\]]")
# 活动 is the usual word; collaboration and memory banners say 联动 / 忆旅 instead
# (the 库街区 notice titles of the 怒 烬中重燃 and 忆旅回响 banners), the same three
# words wuwa_history._WW_HIST_TITLE accepts.
_WW_POOL = re.compile(r"可通过[\[「]([^\]」]+)[\]」]角色(?:活动|联动|忆旅)唤取")


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
        out.append((_one_dot(m.group(1)), pool.group(1) if pool else ""))
    return out


_WW_NOTICE = ("https://aki-gm-resources-back.aki-game.com/gamenotice/G152/"
              "76402e5b20be2c39f095a152090afddc/zh-Hans.json")
# The character catalogue on the wiki (its id, read off the homepage's index tab).
_WW_CHAR_CATALOGUE = 1105
_WW_HDR = {"wiki_type": "9", "source": "h5",
           "referer": "https://wiki.kurobbs.com/"}


_WW_NOTICE_UP = re.compile(r"5星角色「([^」]+)」")
_WW_NOTICE_SPAN = re.compile(r"活动时间[✦\s]*(?:(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})|(\d+\.\d+版本更新后))"
                             r"\s*[~～-]\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")
_WW_NOTICE_TITLE = re.compile(r"[\[「]([^\]」]+)[\]」]\s*角色(?:活动|联动|忆旅)唤取")


def parse_wuwa_notice_banners(notice: dict) -> list[Banner]:
    """The in-game notice's own banner posts (`recommend[]`, 「[X]角色活动唤取」):
    the second official source for the running 鸣潮 banners.
    """
    out: list[Banner] = []
    for n in (notice or {}).get("recommend") or []:
        title = str(n.get("tabTitle") or n.get("title") or "").replace("\n", " ")
        tm = _WW_NOTICE_TITLE.search(title)
        if not tm:
            continue
        txt = re.sub(r"<[^>]+>", " ", str(n.get("content") or "")).replace("&nbsp;", " ")
        txt = re.sub(r"\s+", " ", txt)
        up = _WW_NOTICE_UP.search(txt)
        sp = _WW_NOTICE_SPAN.search(txt)
        if not up or not sp:
            continue
        g = sp.groups()
        start = datetime(*map(int, g[:5])) if g[0] else None
        out.append(Banner("鸣潮", tm.group(1).strip(), (_one_dot(up.group(1).strip()),), start,
                          datetime(*map(int, g[6:]), 59), g[5] or ""))
    return out


_WW_CAL_TITLE = re.compile(r"(\d+\.\d+)版本活动日历")
_WW_CAL_IMG = re.compile(r"""src=["']([^"']+)["']""")
_WW_CAL_FIX = str.maketrans({
    "．": ".", "。": ".", "·": ".", "˙": ".",
    "]": "1", "］": "1", "I": "1", "l": "1", "|": "1", "丨": "1",
    "O": "0", "o": "0", "Ｏ": "0", "０": "0", "〇": "0",
    "一": "~", "—": "~", "–": "~", "～": "~", "〜": "~", "、": "~", "至": "~",
})
# A label start: 「DD.DD」 followed by a range separator (the text is normalised first).
# A single date with no separator is never a start on its own: it is as likely the
# END of the previous banner's range (「9.30~10.22」 vs 「10.22~11.11」 both leave a
# bare 10.22) as the start of this one, so only the range form is trusted.
_WW_CAL_SPAN = re.compile(r"(\d{1,2})[.](\d{1,2})[~\-]")


def wuwa_calendar_image(notice: dict) -> "tuple[str, str, str] | None":
    """(version, notice id, image URL) of the newest 「X版本活动日历」 post."""
    best = None
    for n in (notice or {}).get("activity") or []:
        m = _WW_CAL_TITLE.search(str(n.get("tabTitle") or ""))
        img = _WW_CAL_IMG.search(str(n.get("content") or ""))
        if m and img:
            key = int(n.get("startTimeMs") or 0)
            if best is None or key > best[0]:
                best = (key, m.group(1), str(n.get("id") or ""), html.unescape(img.group(1)))
    return best[1:] if best else None


def parse_wuwa_calendar(lines: list, pool: str, now: datetime) -> "datetime | None":
    """The start date on the calendar label just above `pool`'s card (a date, the
    time left at 00:00, which _stamp prints as a bare date).

    `lines` are OCR lines (desktop.Line: text, x, y, w, h). The label sits a
    little above the name and starts at about the same x; OCR junk after the
    end date (「10.22~11.11/1」) and a slightly wrong name character are tolerated.
    """
    from ark_relay.core.desktop import _name_in  # noqa: PLC0415 - desktop is Windows-side machinery
    want = pool.replace(" ", "")
    miss = 2 if len(want) >= 6 else 1 if len(want) >= 4 else 0
    for nm in lines:
        txt = nm.text.replace(" ", "")
        if not _name_in(want, txt, miss):
            continue
        h = max(nm.h, 1)
        best = None
        for ln in lines:
            t = ln.text.replace(" ", "").translate(_WW_CAL_FIX)
            dy = nm.y - ln.y
            if not 0 < dy <= 3 * h:
                continue
            # An OCR engine may join two labels on the same row (「9.30~10.22」 and
            # 「10.22~11.11」, 480 px apart) into one line. The gap has no characters,
            # so place the first label at the line's left edge and the last one back
            # from its right edge (digits are about half as wide as the label is tall).
            spans = list(_WW_CAL_SPAN.finditer(t))
            for i, m in enumerate(spans):
                x = (ln.x if i == 0 else
                     ln.x + ln.w - int((len(t) - m.start()) * ln.h * 0.45) if i == len(spans) - 1 else
                     ln.x + ln.w * m.start() // max(len(t), 1))
                if abs(x - nm.x) <= 3 * h and (best is None or dy < best[0]):
                    best = (dy, int(m.group(1)), int(m.group(2)))
        if best:
            try:
                day = datetime(now.year, best[1], best[2])
            except ValueError:
                return None
            # a calendar read in December can show January
            return day.replace(year=now.year + 1) if (now - day).days > 180 else day
    return None


def _wuwa_calendar_start(notice: dict, pool: str, now: datetime, end: datetime,
                         read_image, notes: "dict[str, str] | None", tr: "Trace"
                         ) -> "datetime | None":
    """`pool`'s start date from the version calendar image, or None (and a note
    saying where the date is, so the line does not claim it was never published).
    """
    cal = hub.wuwa_calendar_image(notice)
    if not cal:
        return None
    ver, nid, url = cal
    where = f"{_WW_NOTICE} activity id={nid}「{ver}版本活动日历」{url}"
    cross = notes is None
    if cross:
        tr.src("鸣潮", "版本日历", where, f"{pool} 没读图：另一来源已给出开启时刻（图上只有日期，没有几点）")
        return None
    day = None
    got = "这台机器不读图" if not read_image else ""
    try:
        lines = read_image(url) if read_image else None
        day = parse_wuwa_calendar(lines or [], pool, now) if lines else None
        if lines and not day:
            log.warning("鸣潮 %s 版本活动日历读了 %d 行，没找到「%s」的日期：%s", ver, len(lines), pool,
                        " / ".join(x.text for x in lines[:60]))
            got = f"读出 {len(lines)} 行，没找到它上方的日期：" + " / ".join(x.text for x in lines[:12])
        elif read_image and lines is None:
            got = "读图没有结果：桌面读屏没返回"
        elif read_image and not lines:
            got = "图上一行字都没读出"
    except Exception as e:
        log.warning("鸣潮版本活动日历读图失败", exc_info=True)
        got = f"读图出错：{type(e).__name__}: {e}"
    if day is not None and day.date() < now.date():
        got = f"读出的日期 {day:%m-%d} 已经过了"
    if day is None or day.date() < now.date():
        log.warning("这条公告只有图，没读到字：%s", where)
        tr.src("鸣潮", "版本日历", where, f"{pool} 的日期没读出（{got[:240]}）")
        if notes is not None:
            notes["鸣潮"] = "官方公告为图片，未能读取"
        return None
    tr.starts |= _stamps(day)
    if notes is not None:
        notes["鸣潮"] = f"官方 {ver} 版本活动日历"
    tr.src("鸣潮", "版本日历", where, f"{pool} {day:%Y-%m-%d} 开（图上只有日期，没有几点）")
    tr.checks.append(f"鸣潮：版本日历 {pool} {day:%m-%d} 开 ↔ 当期 {end:%m-%d %H:%M} 结束 "
                     + ("✓" if day.date() == end.date() else "✗"))
    return day


def _wuwa_second_half(notice: dict, p: str, w: str, now: datetime, end: "datetime | None",
                      read_image, notes: "dict[str, str] | None", tr: "Trace", kuro_get, bili_get
                      ) -> "datetime | None":
    """The second half's start (banner `p`, character `w`) when the game notice gives none."""
    at = None
    # In order: the banner's own Kuro BBS notice (text, to the minute); the
    # version-news poster (OCR, to the minute); the first half's printed
    # end + 1 min (worked out, said so on the line); the version calendar
    # (date only). Each clock time names where it came from in the trace.
    cal = hub.wuwa_calendar_image(notice)
    ver = cal[0] if cal else None
    gacha = None
    gacha_why = ""
    try:
        gacha = _kuro_gacha(ver, p, now, kuro_get)
    except Exception as e:  # decided below, once the poster is read
        gacha_why = f"{type(e).__name__}: {e}"
        log.info("库街区唤取公告取不到", exc_info=True)
    if gacha and gacha[0] == "公告原文":
        _how, at, until, where = gacha
        tr.starts |= _stamps(at)
        tr.ends |= _stamps(until)
        tr.until["鸣潮"] = until
        tr.src("鸣潮", "唤取公告", where, f"{p} {at:%Y-%m-%d %H:%M}~{until:%Y-%m-%d %H:%M}（公告原文，服务器时间）")
        return at
    span = _wuwa_poster_span(ver, p, w, now, read_image, tr, kuro_get, bili_get)
    if gacha_why:
        # The notice failed: the poster giving the time to the minute is a fault
        # the relay got over (the daily report only; why: USER-SWITCHES.txt at
        # wuwa.py:_wuwa_second_half); without it, it is pushed.
        if span:
            from ark_relay.features import errwatch  # noqa: PLC0415
            log.warning("库街区唤取公告没取到，版本资讯帖的长图给出了「%s」的开始时间\n唤取公告：%s",
                        p, gacha_why, extra=errwatch.recovered())
        else:
            log.warning("库街区唤取公告取不到（%s），版本资讯帖的长图也没给出「%s」的开始时间", gacha_why, p)
    if gacha:
        _how, derived, _none, where = gacha
        tr.src("鸣潮", "唤取公告", where,
               f"{p} 推导 {derived:%Y-%m-%d %H:%M} 开（第一期结束 +1 分钟；{_WW_GACHA_CHECKED}）")
    if span:
        at = span[0]
        tr.until["鸣潮"] = span[1]
        if gacha:
            tr.checks.append(f"鸣潮：长图识别 {p} {at:%m-%d %H:%M} 开 ↔ 推导 {derived:%m-%d %H:%M} "
                             + ("✓" if derived == at else "✗"))
    elif gacha:
        at = derived
        tr.starts |= _stamps(at)
        tr.how["鸣潮"] = f"第一期 {at - _SWAP:%H:%M} 结束后接着开，公告未出"
    day = hub._wuwa_calendar_start(notice, p, now, end, read_image, None if at else notes, tr)
    if at is not None:
        agree = ("没读出 —" if day is None
                 else f"{day:%m-%d} " + ("✓" if day.date() == at.date() else "✗"))
        tr.checks.append(f"鸣潮：{'长图识别' if span else '推导'} {p} {at:%m-%d %H:%M} 开 ↔ 版本日历 {agree}")
    else:
        at = day
    return at


def _wuwa_first_half_end(ver: str, now: datetime, read_image, tr: "Trace", kuro_get, bili_get
                         ) -> "datetime | None":
    """The next version's first-half end: the Kuro notice when it is out, else the
    version-news poster (Kuro copy, then Bilibili). None while neither is published;
    that is the publisher's schedule, not a fault, so that says nothing. A step
    that FAILED (an exception or an OCR without a result, not "not published")
    when no end was found is one WARNING listing the failures, as in
    _wuwa_poster_span: otherwise the report printed 「官方未公告」 as fact."""
    get = kuro_get or _kuro_default
    failed: list[str] = []
    try:
        events = (kuro_checked(get(_KURO_NEWS, {"gameId": 3, "eventType": 3, "pageSize": 100}), "唤取公告列表")
                  .get("data") or {}).get("list")

        def detail_of(pid: str) -> dict:
            return ((kuro_checked(get(_KURO_POST, {"isOnlyPublisher": 0, "postId": pid, "showOrderType": 2}),
                                  f"帖子 {pid}").get("data") or {})
                    .get("postDetail") or {})
        hit = wuwa_first_half_notice_end(events or [], detail_of, ver, now)
    except Exception as e:
        log.info("库街区唤取公告取不到，下一版第一期的结束时刻改看长图", exc_info=True)
        failed.append(f"库街区唤取公告取不到（{type(e).__name__}）")
        hit = None
    if hit:
        tr.src("鸣潮", "唤取公告", hit[1], f"{ver} 第一期 {hit[0]:%Y-%m-%d %H:%M} 结束（公告原文）")
        return hit[0]
    end = _wuwa_first_end_poster(ver, now, read_image, tr, get, bili_get, failed) if read_image else None
    if end is None and failed:
        # the first line is quoted in the daily report: no Latin letters
        log.warning("鸣潮 %s 版本第一期的结束时刻这次没读到，下期一行只能写官方未公告\n%s",
                    ver, "；".join(failed))
    return end


def _wuwa_first_end_poster(ver: str, now: datetime, read_image, tr: "Trace", get, bili_get,
                           failed: "list[str]") -> "datetime | None":
    """_wuwa_first_half_end's poster doors; a door or an image that failed is
    appended to `failed`, in words."""
    for what, find in (("库街区", lambda: hub._kuro_poster(ver, now, get)), ("B 站", lambda: hub._bili_poster(ver, now, bili_get))):
        who = "哔哩哔哩" if what == "B 站" else what
        try:
            found = find()
        except Exception as e:
            log.info("%s版本资讯帖取不到", what, exc_info=True)
            tr.problems.append(f"鸣潮｜版本资讯｜{what}｜{type(e).__name__}: {e}")
            failed.append(f"{who}版本资讯帖取不到（{type(e).__name__}）")
            _door(tr, what, f"取不到：{type(e).__name__}: {e}")
            continue
        if not found:
            _door(tr, what, "没有这一帖")
            continue
        had = len(failed)
        page, title, imgs = found
        for n, (url, w, h) in enumerate(imgs, 1):
            if h <= 2.5 * max(w, 1):
                continue
            try:
                lines = read_image(url)
            except Exception as e:
                log.info("%s版本资讯第 %d 张图读图失败", what, n, exc_info=True)
                failed.append(f"{who}那一帖第 {n} 张图没读下来（{type(e).__name__}）")
                continue
            if lines is None:
                failed.append(f"{who}那一帖第 {n} 张图没读出来（读图没有结果）")
                _door(tr, what, f"长图没读出来：{failed[-1]}")
                return None
            end = hub.parse_wuwa_poster_first_end(lines)
            if end and end > now:
                tr.src("鸣潮", "版本资讯", f"{what} {page}「{title}」第 {n} 张图 {url}",
                       f"{ver} 第一期 {end:%Y-%m-%d %H:%M} 结束（服务器时间）")
                _door(tr, what, f"给出了 {ver} 第一期的结束时刻 {end:%m-%d %H:%M}")
                return end
        mine = "；".join(failed[had:])
        _door(tr, what, f"长图里没读到 {ver} 第一期的结束时刻" + (f"（{mine}）" if mine else ""))
    return None


def _wuwa_name_from_notice(home: dict, nameless: "dict[str, Exception]",
                           debut: "list[tuple[str, str]]", notice_banners: "list[Banner]"
                           ) -> "list[Banner]":
    """The banners parse_wuwa left out because the wiki gave their character no name,
    named from the official notices where they name the same banner: the version
    bulletin's debuts, then the in-game banner posts. A name found that way is a
    fault the relay got over (WARNING marked recovered, the daily report only; why:
    USER-SWITCHES.txt at wuwa.py:_wuwa_name_from_notice); one found nowhere is the
    plain WARNING it always was, and the banner stays out.
    """
    from ark_relay.features import errwatch  # noqa: PLC0415
    by_pool = {p: w for w, p in debut if p}
    for x in notice_banners:
        by_pool.setdefault(x.name, x.chars[0])
    out: list[Banner] = []
    named: "dict[str, str]" = {}
    for name, eid, a, b in wuwa_tabs(home)[0]:
        if eid in nameless and (who := by_pool.get(name)):
            out.append(Banner("鸣潮", name, (_one_dot(who),), a, b))
            named[eid] = f"「{name}」{who}"
    for eid, e in nameless.items():
        if eid in named:
            log.warning("鸣潮：库街区条目 %s 查不到名字，按官方公告补上%s\n%s: %s", eid, named[eid],
                        type(e).__name__, e, extra=errwatch.recovered())
        else:
            log.warning("库街区条目 %s 查不到名字", eid, exc_info=e)
    return out


def _wuwa_fill_from_notice(now: datetime, pools: "list[Banner]", notice_banners: "list[Banner]",
                           debut: "list[tuple[str, str]]", tr: "Trace") -> "list[Banner]":
    """The other direction: the in-game notice's banners that are open now and that
    the wiki does not list, to go in the report from the notice. The notice posts a
    banner when it opens, so one still before its end is running, also when its
    start reads 「X版本更新后」. With the version's debuts known (`debut`), a rerun is
    left out, as everywhere in the report."""
    out: list[Banner] = []
    debut_names = {w for w, _ in debut}
    for x in notice_banners:
        if not (now <= x.end and (x.start is None or x.start <= now)):
            continue
        if debut_names and not set(x.chars) & debut_names:
            continue
        tr.opened("鸣潮", x.name, "、".join(x.chars), x.start, x.end, _WW_NOTICE)
        if any(b.name == x.name or set(b.chars) & set(x.chars) for b in pools if hub.running(b, now)):
            continue
        out.append(x)
        tr.src("鸣潮", "当期", _WW_NOTICE, f"{x.name} {'、'.join(x.chars)} "
               + (f"{x.start:%Y-%m-%d %H:%M}" if x.start else x.start_note) + f"~{x.end:%Y-%m-%d %H:%M}")
        hub.official_fill("鸣潮", "库街区", x, "游戏公告", tr)
    return out


def _wuwa(now: datetime, notes: "dict[str, str] | None" = None,
          trace: "Trace | None" = None, read_image=None, kuro_get=None, bili_get=None
          ) -> "tuple[list[Banner], tuple[datetime | None, str] | None]":
    """Current banners come from the wiki homepage, the next one from the official
    bulletin. Neither needs a token.
    """
    tr = trace if trace is not None else Trace.new()

    def post(path, payload=None):
        # data must not be None, or urllib sends a GET -- these two endpoints only
        # accept POST.
        h = dict(_WW_HDR)
        body = b""
        if payload is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
            body = urllib.parse.urlencode(payload).encode()
        return kuro_checked(hub._json(_KURO + path, _UA_BROWSER, body, h), path)

    cache: dict[str, str] = {}
    nameless: "dict[str, Exception]" = {}

    def name_of(eid: str) -> str:
        if eid not in cache:
            try:
                d = post("/wiki/core/catalogue/item/getEntryDetail",
                         {"id": eid})["data"] or {}
                cache[eid] = str(d.get("name") or "").strip()
            except Exception as e:   # said once the official notices are read (below)
                log.info("库街区条目 %s 查不到名字", eid, exc_info=True)
                nameless[eid] = e
                cache[eid] = ""
        return cache[eid]

    # Fetch the bulletin first: its 「全新角色」 section is the only authoritative basis
    # for telling a debut from a rerun. getPage gives only the banners and says nothing
    # about who is new; of the two banners in the first half of 3.6, 达妮娅 was a rerun.
    debut: "list[tuple[str, str]]" = []
    notice_ok = True
    notice_banners: list[Banner] = []
    body = ""
    try:
        notice = hub._json(_WW_NOTICE, _UA_BROWSER, timeout=25)
        body = newest_version([(str(n.get("tabTitle") or ""),
                                str(n.get("content") or ""))
                               for n in (notice.get("game") or [])
                               if "版本内容说明" in str(n.get("tabTitle") or "")])
        debut = parse_wuwa_preview(body)
        notice_banners = parse_wuwa_notice_banners(notice)
    except Exception:
        notice_ok = False
        log.warning("鸣潮官方公告取不到，这一版分不出首发和复刻", exc_info=True)

    articles = None
    maint = None
    try:
        articles = json.loads(hub._text(_WW_SITE_ARTICLES, _UA_BROWSER))
        maint = wuwa_maintenance(articles, now)
        if maint:
            tr.starts |= _stamps(maint[1]) | _stamps(maint[2])
            tr.src("鸣潮", "版本维护", _WW_SITE_ARTICLES, f"{maint[0]} 维护 {maint[1]:%Y-%m-%d %H:%M}~{maint[2]:%Y-%m-%d %H:%M}")
    except Exception:
        log.warning("鸣潮官网文章列表取不到", exc_info=True)

    # Unreadable raises (see _endfield): an empty return would read as "none".
    home = post("/wiki/core/homepage/getPage")
    pools = hub.parse_wuwa(home, name_of)
    if nameless:
        pools += _wuwa_name_from_notice(home, nameless, debut, notice_banners)
    synth = _wuwa_fill_from_notice(now, pools, notice_banners, debut if notice_ok else [], tr)
    pools += synth
    end = min((b.end for b in pools), default=None)

    # If the bulletin cannot be fetched, better to report one extra rerun than to lose
    # the countdown entirely -- the banners within a version all end at the same time
    # anyway, and the value of this line is mostly in that moment.
    # The same holds when the bulletin was fetched but no debut came out of it: its
    # title no longer says 版本内容说明, or the 「全新角色」 section changed shape
    # (_WW_ROLE). An empty debut list used to drop every running pool and the block
    # read 「当期无新角色卡池」 with no log line.
    names = {w for w, _ in debut}
    split = notice_ok
    if notice_ok and pools and not debut:
        split = False
        why = ("没有标题含「版本内容说明」的公告" if not body
               else "版本说明里没有「全新角色」一节" if "全新角色" not in body
               else "「全新角色」一节里一个角色都没读出来（写法变了）")
        # the first line is quoted in the daily report: no Latin letters
        log.warning("鸣潮官方公告里读不出这一版的新角色（%s），分不出首发和复刻，在开的卡池全部照报", why)
    got = [b for b in pools if set(b.chars) & names] if split else pools
    for i, b in enumerate(got):
        if b not in synth and b.start <= now <= b.end:
            tr.ends |= _stamps(b.end)
            tr.src("鸣潮", "当期", _KURO + "/wiki/core/homepage/getPage", f"{b.name} {'、'.join(b.chars)} {b.start:%Y-%m-%d %H:%M}~{b.end:%Y-%m-%d %H:%M}")
            other = next((x for x in notice_banners if x.name == b.name or set(x.chars) & set(b.chars)), None)
            if other:
                tr.src("鸣潮", "游戏公告", _WW_NOTICE, f"{other.name} {'、'.join(other.chars)} "
                       + (f"{other.start:%Y-%m-%d %H:%M}" if other.start else other.start_note)
                       + f"~{other.end:%Y-%m-%d %H:%M}")
            got[i], line = (crosscheck_fix("鸣潮", "库街区", b, "游戏公告", other, now, tr) if notice_ok
                            else (b, "鸣潮：游戏公告取不到，只有库街区一个来源 ✗"))
            tr.checks.append(line)

    live = {c for b in pools for c in b.chars}
    rest = upcoming(debut, live) if end and end > now else []
    if rest:
        # The version bulletin names the second half and its banner but no time
        # (3.7 gives the banner name for the second character, nothing more). The
        # time is printed only once the in-game banner notice gives one.
        w, p = rest[0]
        at = next((x.start for x in notice_banners
                   if x.start is not None and x.start > now and (x.name == p or w in x.chars)), None)
        who = "、".join(f"{w}「{p}」" if p else w for w, p in rest)
        if at:
            tr.starts |= _stamps(at)
        tr.src("鸣潮", "预告", _WW_NOTICE, f"本版下半：{who}，" + (f"开 {at:%Y-%m-%d %H:%M}" if at else "开放时间公告未写"))
        if at is None and p and notice_ok:
            at = _wuwa_second_half(notice, p, w, now, end, read_image, notes, tr, kuro_get, bili_get)
        return got, (at, who)
    # Both halves are done: the next banner belongs to the next version, whose
    # bulletin is not out yet. The wiki marks the characters the publisher has
    # previewed (the teaser badge), and the site posts the maintenance window a
    # week ahead: both are published, so both are said - but no banner, no order
    # and no opening time, which neither gives.
    teased: list[str] = []
    try:
        page = post("/wiki/core/catalogue/item/getPage",
                    {"catalogueId": _WW_CHAR_CATALOGUE, "page": 1, "limit": 100})
        current = live | {w for w, _ in debut}
        text = _one_dot(body)
        badged = wuwa_teased((((page.get("data") or {}).get("results") or {}).get("records")) or [], now)
        if debut or text or (end and maint and end >= maint[1]):
            teased = [t for t in badged if t not in current and f"「{t}」" not in text]
            tr.src("鸣潮", "预告角色", _KURO + f"/wiki/core/catalogue/item/getPage catalogueId={_WW_CHAR_CATALOGUE}", "预告角标：" + ("、".join(teased) or "无"))
        elif badged:
            tr.src("鸣潮", "预告角色", _KURO + f"/wiki/core/catalogue/item/getPage catalogueId={_WW_CHAR_CATALOGUE}",
                   "预告角标：" + "、".join(badged) + "（没有版本说明，也不是这一版最后半段，分不出是这一版还是下一版的，不报）")
    except Exception:
        log.warning("库街区角色图鉴取不到，预告角色这一项不出", exc_info=True)
    facts = []
    if teased:
        facts.append("官方已预告下一版新角色：" + "、".join(teased))
    if maint:
        facts.append(f"{maint[0]} 版本更新维护 北京 {maint[1]:%m-%d %H:%M}～{maint[2]:%H:%M}")
    if notes is not None and facts:
        notes["鸣潮"] = " · ".join(facts)
    if maint:
        end1 = _wuwa_first_half_end(maint[0], now, read_image, tr, kuro_get, bili_get)
        if end1:
            tr.ends |= _stamps(end1)
            tr.until["鸣潮"] = end1
            tr.how["鸣潮"] = f"版本更新维护 {maint[1]:%m-%d %H:%M}～{maint[2]:%H:%M} 结束后开"
            return got, (maint[2], f"{maint[0]}版本第一期")
    return got, None
