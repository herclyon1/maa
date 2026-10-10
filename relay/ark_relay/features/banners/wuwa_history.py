"""Wuthering Waves past banners and maintenance windows, read from Kuro BBS
news and the official site's article index."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from ark_relay.features.banners import banners as hub
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.banners.banners import (
    record_history, _UA_BROWSER,
)
from ark_relay.features.banners.wuwa_posters import (
    _kuro_default, _KURO_NEWS, _KURO_POST, _KURO_POST_URL, _kuro_text, _WW_GACHA_SPAN,
)


# Past Wuthering Waves banner periods, read the way the next one is: the Kuro BBS
# banner notices (every half of a version since 3.1 is still in the list: 43 notices,
# 2026-02-25 .. 09-29) give the pools and the span; a half that opens 「X版本更新后」
# starts when that version's maintenance window (the site's 「X版本更新维护预告」, kept
# back to 1.1) ends. The facts of an ended period do not change, so the same read must
# give the same record for ever (the user, 2026-10-06 18:56: the banner feature must be
# perfect, these facts are fixed).
# Titles over the years: 「x」 / <x> / [x] around the pool name, 「角色|武器」, 活动 / 联动 /
# 忆旅 唤取, and from 1.x to 2.x a trailing 「——「<up>」概率UP」 naming the featured one.
_WW_HIST_TITLE = re.compile(r"^[\[「<《]([^\]」>》]+)[\]」>》](角色|武器)(?:活动|联动|忆旅)?唤取(?:——「([^」]+)」概率UP)?")
_WW_HIST_UP = re.compile(r"5星(?:角色|武器)「([^」]+)」")


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
    """Every ended period still readable, oldest first: {ver, part, pools, weapons, ups,
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
    for at, pid, title in rows:
        text = _kuro_text(detail_of(pid))
        m = _WW_GACHA_SPAN.search(text)
        if not m:
            continue
        g = m.groups()
        end = datetime(*[int(x) for x in g[6:]])
        start = datetime(*[int(x) for x in g[:5]]) if g[0] else None
        key = (g[5] or start, end)
        h = halves.setdefault(key, {"ver": g[5], "part": "第一期" if g[5] else "第二期", "pools": [], "weapons": [],
                                    "ups": [], "start": start, "start_how": "公告原文" if start else "",
                                    "end": end, "where": []})
        h["where"].append(_KURO_POST_URL.format(id=pid))
        tm = _WW_HIST_TITLE.match(title)
        if tm:
            h["pools" if tm.group(2) == "角色" else "weapons"].append(tm.group(1))
            if tm.group(3):
                h["ups"].append(tm.group(3))
        um = _WW_HIST_UP.search(text)
        if um and um.group(1) not in h["ups"] and tm and tm.group(2) == "角色":
            h["ups"].append(um.group(1))
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
    events = (get(_KURO_NEWS, {"gameId": 3, "eventType": 3, "pageSize": 1000}).get("data") or {}).get("list") or []
    gacha = sorted((e for e in events if "唤取" in str(e.get("postTitle") or "")),
                   key=lambda e: -int(e.get("publishTime") or 0))
    articles = [a for a in json.loads(article_get(_WW_SITE_ARTICLES))
                if "版本更新维护预告" in str(a.get("articleTitle") or "")]
    for a in articles:
        if str(a.get("articleId")) not in art_texts and budget > 0:
            budget -= 1
            body = json.loads(article_get(_WW_SITE_ARTICLE.format(id=a.get("articleId")))).get("articleContent") or ""
            art_texts[str(a.get("articleId"))] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body).replace("&nbsp;", " "))
    for e in gacha:
        pid = str(e.get("postId"))
        if pid not in texts and budget > 0:
            budget -= 1
            d = ((get(_KURO_POST, {"isOnlyPublisher": 0, "postId": pid, "showOrderType": 2}).get("data") or {})
                 .get("postDetail") or {})
            texts[pid] = _kuro_text(d)
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
