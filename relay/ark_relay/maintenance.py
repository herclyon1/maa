"""Official downtime-maintenance bulletins for the three games -- machine-readable
sources, first verified 2026-09-02/03, moved to the sites' JSON endpoints 2026-10-07.

The user, 2026-09-02: 「游戏官方都会提前好几天发更新公告，写什么时候停服维护。
拿到这个就简单了：服务器更新的时候就不跑他，等跑完队列之后检测时间是否已经
过了停服时间，还在停服就等，一直等到开服，更新，补跑，跑完再关机。」

| Game | Source | Format (as observed) |
|---|---|---|
| Arknights | the ANNOUNCEMENT tab of ak.hypergryph.com/api/news (banners.ak_news_pages), title 「[明日方舟]09月04日06:00版本更新停机维护公告」; the post from web-news.hypergryph.com/api/bulletin (banners.ak_post_text), body 「2026年09月04日06:00 - 12:00」 | see _AK_* |
| Endfield | the list and post endpoints of web-news.hypergryph.com/api/bulletin (code=endfield_web, the backend the endfield.hypergryph.com/news page pages through), title 「…版本预下载与更新预告」, body 「版本维护时间 2026/09/02 06:00 - 2026/09/02 12:00（UTC+8）」 | see _EF_* |
| Wuthering Waves | the official site's article index ArticleMenu.json, 「《鸣潮》X.Y版本更新维护预告」 posted about a week ahead (3.7: 09-23 for 09-30), body 「更新维护时间：2026年9月30日04:00 ~ 2026年9月30日11:00（UTC+8）」; the in-game bulletin JSON 「X.Y版本内容说明」 when no 预告 covers today | see _WW_* |

The in-game bulletins are no source for the planning: they go up once the
update is out (Endfield's 「雪凇幽梦」版本更新说明 at 09-02 09:00 for the 06:00-12:00
window; Wuthering Waves' 3.7版本内容说明 shown from 09-30 09:20, inside 04:00-11:00).

Each `*_window()` returns (start, end, evidence line) or None. If nothing can be
fetched it returns None; it never guesses.
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from .config import SERVER_TZ

log = logging.getLogger("ark.maintenance")
_UA = "Mozilla/5.0"

Window = tuple[datetime, datetime, str]


# One more try after a pause when the site did not answer at all (10-02
# 23:05:34 / 23:05:54: ak.hypergryph.com and endfield.hypergryph.com each
# timed out once, 20 s apart, inside one state push). An HTTP answer is not
# retried: the site did answer, and the same request gets the same page.
# A retry that gets the page is a fault the relay got over by itself: one
# WARNING marked errwatch.recovered(), the daily report only (the user on
# 2026-10-06 05:07 about faults the relay got over: 「报错后自己好了的，只进日报、不进群」).
# Both tries failing raises, and today() pushes that WARNING.
GET_ATTEMPTS = 2
GET_PAUSE = 3.0
_sleep = time.sleep


def _get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    first = ""
    for i in range(GET_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                page = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError:
            raise
        except Exception as exc:  # timeout, reset, DNS (the last try re-raises)
            if i + 1 >= GET_ATTEMPTS:
                raise
            first = first or f"{type(exc).__name__}: {exc}"
            log.info("维护公告：%s 没响应（%s），%.0f 秒后再试一次", url, exc, GET_PAUSE)
            _sleep(GET_PAUSE)
            continue
        if i:
            from . import errwatch  # noqa: PLC0415
            log.warning("停服维护公告的官网第一次没响应，%.0f 秒后再取一次，取到了\n%s 第一次：%s",
                        GET_PAUSE * i, url, first, extra=errwatch.recovered())
        return page
    raise RuntimeError("unreachable")


def _text(page: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html.unescape(page)))


def _dt(y: int, mo: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, mo, d, hh, mm, tzinfo=SERVER_TZ)


# ── Arknights ──
# Two pages of the ANNOUNCEMENT tab (6 a page) are the dozen the /news page
# showed; a week of 闪断更新 notices can push the 停机维护 one off the first page.
_AK_PAGES = 2
_AK_TITLE = re.compile(r"(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2}).*?(停机维护|停机更新|维护公告)")
_AK_BODY = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})\s*[-~～至]\s*(?:(\d{4})年(\d{1,2})月(\d{1,2})日\s*)?(\d{1,2}):(\d{2})")


def arknights_window(now: datetime | None = None, get=_get) -> Window | None:
    from .banners import ak_news_pages, ak_post_text  # noqa: PLC0415
    for items in ak_news_pages(get, "ANNOUNCEMENT", _AK_PAGES):
        for cid, title, _posted in items:
            if not _AK_TITLE.search(title):
                continue
            m = _AK_BODY.search(ak_post_text(get, cid))
            if not m:
                continue
            y, mo, d, h1, m1, y2, mo2, d2, h2, m2 = m.groups()
            start = _dt(int(y), int(mo), int(d), int(h1), int(m1))
            end = _dt(int(y2 or y), int(mo2 or mo), int(d2 or d), int(h2), int(m2))
            return start, end, f"官方公告：{title}（{start:%m-%d %H:%M}–{end:%H:%M}）"
    return None


# ── Endfield ──
# One page of the backend list is the newest 20 posts (the /news page showed 10).
_EF_BODY = re.compile(r"维护时间\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})\s*[-~～]\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})")


def endfield_window(now: datetime | None = None, get=_get) -> Window | None:
    from .banners import _EF_CMS_LIST, _EF_CMS_POST, _ef_cms_text  # noqa: PLC0415
    d = json.loads(get(_EF_CMS_LIST.format(page=1)))
    if d.get("code") != 0:
        raise ValueError(f"终末地官网列表返回 code={d.get('code')!r}")
    for it in (d.get("data") or {}).get("list") or []:
        cid, title = str(it.get("cid") or ""), str(it.get("title") or "")
        if "预告" not in title and "维护" not in title:
            continue
        post = json.loads(get(_EF_CMS_POST.format(cid=cid)))
        body = _ef_cms_text(str((post.get("data") or {}).get("data") or ""))
        m = _EF_BODY.search(body)
        if not m:
            continue
        y, mo, d, h1, m1, y2, mo2, d2, h2, m2 = (int(x) for x in m.groups())
        start, end = _dt(y, mo, d, h1, m1), _dt(y2, mo2, d2, h2, m2)
        return start, end, f"官方公告：{title}（{start:%m-%d %H:%M}–{end:%H:%M}）"
    return None


# ── Wuthering Waves ──
_WW_NOTICE = ("https://aki-gm-resources-back.aki-game.com/gamenotice/G152/"
              "76402e5b20be2c39f095a152090afddc/zh-Hans.json")
_WW_BODY = re.compile(r"更新维护时间[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})\s*[~～-]\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")


def wuwa_window(now: datetime | None = None, get=_get) -> Window | None:
    """The official site's 「X.Y版本更新维护预告」 (a week ahead) when its window
    ends today or later; otherwise the in-game bulletin's newest 「版本内容说明」 -
    the path for a version the site posted no 预告 for, and after the window.
    """
    from .banners import _WW_SITE_ARTICLES, newest_version, wuwa_maint_notice  # noqa: PLC0415
    now = now or datetime.now(tz=SERVER_TZ)
    local = now.astimezone(SERVER_TZ).replace(tzinfo=None)
    site = wuwa_maint_notice(json.loads(get(_WW_SITE_ARTICLES)), local, get=get)
    if site and site[2].date() >= local.date():
        ver, a, b = site
        start, end = a.replace(tzinfo=SERVER_TZ), b.replace(tzinfo=SERVER_TZ)
        return start, end, f"官方公告：《鸣潮》{ver}版本更新维护预告（{start:%m-%d %H:%M}–{end:%H:%M}）"
    data = json.loads(get(_WW_NOTICE))
    items = [(str(n.get("tabTitle") or ""), str(n.get("content") or ""))
             for n in (data.get("game") or []) if "版本内容说明" in str(n.get("tabTitle") or "")]
    body = _text(newest_version(items))
    m = _WW_BODY.search(body)
    if not m:
        return None
    y, mo, d, h1, m1, y2, mo2, d2, h2, m2 = (int(x) for x in m.groups())
    start, end = _dt(y, mo, d, h1, m1), _dt(y2, mo2, d2, h2, m2)
    title = next((t for t, _ in items if _text(dict(items)[t]) == body), "版本更新")
    return start, end, f"官方公告：{title.strip().splitlines()[-1]}（{start:%m-%d %H:%M}–{end:%H:%M}）"


SCRIPT_OF = {"明日方舟": "MAA", "终末地": "MaaEnd", "鸣潮": "OK-WW"}
SOURCES = {"明日方舟": arknights_window, "终末地": endfield_window, "鸣潮": wuwa_window}


# The bulletins are read through a cache. Every phone state push builds
# tomorrow's plan (phone.state_payload -> plan.next_plan -> maintenance_lines
# -> today), so until 2026-10-06 each push fetched all three official sites -
# 10-02 evening dozens of times, a 20 s wait per site that did not answer, and
# a WARNING each time one timed out (#50, #53). A bulletin is posted days
# ahead, so an hour-old read is as good as a fresh one; a site that just failed
# is not asked again for FAIL_TTL, and that repeat is not a new fault.
OK_TTL = 3600
FAIL_TTL = 300
_CACHE: "dict[str, tuple[float, object]]" = {}     # game -> (when, window or None or exception)
_CACHE_LOCK = threading.Lock()
_SITE = {"明日方舟": "ak.hypergryph.com / web-news.hypergryph.com", "终末地": "web-news.hypergryph.com",
         "鸣潮": "鸣潮官网 kurogame.com / aki-game.com 的游戏内公告"}


# Per game, what this process really asked the site (not the cache): reads,
# failures, and the last one - for the machine check #50 (machinechecks/
# phone_banners.py), which compares them with the state pushes of the shift.
_STATS: "dict[str, dict]" = {}


def stats() -> "dict[str, dict]":
    """{game: {"fetch": n, "fail": n, "last": unix time, "last_ok": bool, "why": str}}
    of the real reads this process made (served from the cache not counted)."""
    with _CACHE_LOCK:
        return {g: dict(v) for g, v in _STATS.items()}


def _count(game: str, t: float, why: "str | None") -> None:
    with _CACHE_LOCK:
        row = _STATS.setdefault(game, {"fetch": 0, "fail": 0, "last": 0.0, "last_ok": True, "why": ""})
        row["fetch"] += 1
        row["last"] = t
        row["last_ok"] = why is None
        if why is not None:
            row["fail"] += 1
            row["why"] = why


class _Cached(Exception):
    """A failure served from the cache: the real read failed less than
    FAIL_TTL ago and was reported then."""


def _read(game: str, fn, now: datetime):
    """fn(now) through the cache. Raises what fn raised, or _Cached while that
    failure is younger than FAIL_TTL."""
    t = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(game)
    if hit is not None:
        at, got = hit
        if isinstance(got, Exception):
            if t - at < FAIL_TTL:
                raise _Cached(str(got)) from got
        elif t - at < OK_TTL:
            return got
    try:
        got = fn(now)
    except Exception as exc:
        with _CACHE_LOCK:
            _CACHE[game] = (t, exc)
        _count(game, t, f"{type(exc).__name__}: {exc}"[:200])
        raise
    with _CACHE_LOCK:
        _CACHE[game] = (t, got)
    _count(game, t, None)
    return got


def today(now: datetime | None = None, sources=None,
          failed: list[str] | None = None) -> dict[str, Window]:
    """Games with downtime maintenance today -> their window.

    A list and a post per game (the three official sources through the cache
    above; `sources` given = read as given, uncached). A game whose bulletin
    could not be fetched is left out of the result and, when `failed` is given,
    appended to it - so the caller can tell "read it, no maintenance" from
    "could not read it" (an empty dict alone says both).

    A read that fails is a WARNING (the site or the network is down, not this
    code - and the caller may not know today's window); the same failure
    served from the cache within FAIL_TTL is INFO.
    """
    now = now or datetime.now(tz=SERVER_TZ)
    out: dict[str, Window] = {}
    for game, fn in (sources if sources is not None else SOURCES).items():
        try:
            w = fn(now) if sources is not None else _read(game, fn, now)
        except _Cached:
            log.info("维护公告：%s 官方公告刚才取不到，%d 分钟内不再去取", game, FAIL_TTL // 60)
            if failed is not None:
                failed.append(game)
            continue
        except Exception as exc:
            log.warning("维护公告：%s 官方公告取不到（%s%s），这次不知道它有没有停服维护",
                        game, _SITE.get(game, "官网"), f"：{exc}" if str(exc) else "",
                        exc_info=True)
            if failed is not None:
                failed.append(game)
            continue
        if w and w[0].date() <= now.date() <= w[1].date():
            out[game] = w
    return out
