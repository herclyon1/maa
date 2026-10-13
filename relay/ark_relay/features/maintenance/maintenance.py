"""Official downtime-maintenance bulletins for the three games.

today() returns the games under maintenance today and their windows; boot_check
saves them, and the relay does not run a game during its window (gameupdate).

| Game | Source | Format (as observed) |
|---|---|---|
| Arknights | the ANNOUNCEMENT tab of ak.hypergryph.com/api/news (banners.ak_news_pages), title 「[明日方舟]09月04日06:00版本更新停机维护公告」; the post from web-news.hypergryph.com/api/bulletin (banners.ak_post_text), body 「2026年09月04日06:00 - 12:00」 | see _AK_* |
| Endfield | the list and post endpoints of web-news.hypergryph.com/api/bulletin (code=endfield_web, the backend the endfield.hypergryph.com/news page pages through), title 「…版本预下载与更新预告」, body 「版本维护时间 2026/09/02 06:00 - 2026/09/02 12:00（UTC+8）」 | see _EF_* |
| Wuthering Waves | the official site's article index ArticleMenu.json, 「《鸣潮》X.Y版本更新维护预告」 posted about a week ahead (3.7: 09-23 for 09-30), body 「更新维护时间：2026年9月30日04:00 ~ 2026年9月30日11:00（UTC+8）」; the in-game bulletin JSON 「X.Y版本内容说明」 when no 预告 covers today | see _WW_* |

The in-game 「版本内容说明」 bulletins go up only once the update is out, inside
the window; Wuthering Waves falls back to one only when no 预告 covers today.

Each `*_window()` returns (start, end, evidence line), or None when no bulletin
with a window was found. today() treats an exception from one as "could not read".
"""
from __future__ import annotations

import contextvars
import html as _html
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from ark_relay.core.config import SERVER_TZ

log = logging.getLogger("ark.maintenance")
_UA = "Mozilla/5.0"

Window = tuple[datetime, datetime, str]


# A request that got no answer (timeout, reset, DNS) is tried once more after
# GET_PAUSE seconds; an HTTP error answer is not retried. A retry that succeeds
# logs one WARNING marked errwatch.recovered() (daily report only). Both tries
# failing raises, and today() logs the WARNING.
GET_ATTEMPTS = 2
GET_PAUSE = 3.0
# One try, whole: connect, headers and body (it was per socket operation, so a server
# sending a byte now and then held a read for as long as it liked). A try cut off here
# is a time-out like any other: retried once, then today()'s WARNING and FAIL_TTL.
# Measured 2026-10-13 from the Mac, 140 timed reads of the seven bulletin URLs:
# median 0.57 s, 90th percentile 1.88 s, slowest good reads 14.0 / 17.9 s; one read of
# the 26 KB kurogame article/5477.json took 164.8 s. relay.log 10-02 23:05:34 / 23:05:54:
# the machine's two failures, 20 s apart (silence until the per-op time-out).
# app_main.stop_push (a fresh process at a Windows shutdown, no cache) lowers it and
# GET_ATTEMPTS so tomorrow's plan cannot eat its time limit.
GET_TIMEOUT = 20
# All of one today() call's real reads together (up to seven URLs, a try each and a
# retry): what is left after it fails at once, as a time-out. Measured with the same
# reads: a whole today() took 3.2-22.2 s in 18 of 20 runs; the other two 47.4 s (a
# 24.9 s read) and 169.7 s (the 164.8 s read). relay.log 10-11 16:57 / 18:31 / 21:47:
# the whole stop-push state, all reads included, built in 11.3-11.6 s on the machine.
TODAY_BUDGET = 60
_sleep = time.sleep
# When the running today() call's budget ends (time.monotonic()); None outside one.
_UNTIL: "contextvars.ContextVar[float | None]" = contextvars.ContextVar("maintenance_until", default=None)


def _limit(timeout: float) -> float:
    """The time one try may take: `timeout`, or less when today()'s budget ends sooner."""
    until = _UNTIL.get()
    if until is None:
        return timeout
    left = until - time.monotonic()
    if left <= 0:
        raise TimeoutError("timed out")
    return min(timeout, left)


def _read_whole(req, end: float, limit: float) -> str:
    """One request, read to the end unless time.monotonic() passes `end` first."""
    with urllib.request.urlopen(req, timeout=limit) as r:
        read1 = getattr(r, "read1", None)
        if read1 is None:                      # a plain file-like answer
            return r.read().decode("utf-8", "replace")
        # Each socket read waits at most the time left (CPython's SocketIO keeps the
        # socket in ._sock; without it a read still ends at `limit`).
        sock = getattr(getattr(r.fp, "raw", None), "_sock", None)
        parts: list[bytes] = []
        while True:
            left = end - time.monotonic()
            if left <= 0:
                raise TimeoutError("timed out")
            if sock is not None and not r.isclosed():     # closed: read1 says b"" next
                sock.settimeout(left)
            chunk = read1(65536)
            if not chunk:
                return b"".join(parts).decode("utf-8", "replace")
            parts.append(chunk)


def _try(req, limit: float) -> str:
    """_read_whole within `limit` seconds. In a thread of its own: a stalled DNS
    lookup or a server that dribbles its headers is out of the body loop's reach; it
    is left to end at its socket time-out."""
    end = time.monotonic() + limit
    box: dict = {}

    def run():
        try:
            box["page"] = _read_whole(req, end, limit)
        except BaseException as exc:  # noqa: BLE001 - handed to the caller as is
            box["exc"] = exc

    worker = threading.Thread(target=run, daemon=True, name="maintenance-get")
    worker.start()
    worker.join(limit)
    if worker.is_alive():
        raise TimeoutError("timed out")
    if "exc" in box:
        raise box["exc"]
    return box["page"]


def _get(url: str, timeout: "float | None" = None) -> str:
    timeout = timeout or GET_TIMEOUT
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    first = ""
    for i in range(GET_ATTEMPTS):
        try:
            page = _try(req, _limit(timeout))
        except urllib.error.HTTPError:
            raise
        except Exception as exc:  # timeout, reset, DNS (the last try re-raises)
            until = _UNTIL.get()
            if i + 1 >= GET_ATTEMPTS or (until is not None and until - time.monotonic() <= GET_PAUSE):
                raise
            first = first or f"{type(exc).__name__}: {exc}"
            log.info("维护公告：%s 没响应（%s），%.0f 秒后再试一次", url, exc, GET_PAUSE)
            _sleep(GET_PAUSE)
            continue
        if i:
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415
            log.warning("停服维护公告的官网第一次没响应，%.0f 秒后再取一次，取到了\n%s 第一次：%s",
                        GET_PAUSE * i, url, first, extra=errwatch.recovered())
        return page
    raise RuntimeError("unreachable")


def _text(page: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html.unescape(page)))


def _dt(y: int, mo: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, mo, d, hh, mm, tzinfo=SERVER_TZ)


# ── Arknights ──
# Pages of the ANNOUNCEMENT tab to search (6 posts a page).
_AK_PAGES = 2
_AK_TITLE = re.compile(r"(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2}).*?(停机维护|停机更新|维护公告)")
_AK_BODY = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})\s*[-~～至]\s*(?:(\d{4})年(\d{1,2})月(\d{1,2})日\s*)?(\d{1,2}):(\d{2})")


def arknights_window(now: datetime | None = None, get=_get) -> Window | None:
    from ark_relay.features.banners.banners import ak_news_pages, ak_post_text  # noqa: PLC0415
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
# One page of the backend list: the newest 20 posts.
_EF_BODY = re.compile(r"维护时间\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})\s*[-~～]\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})")


def endfield_window(now: datetime | None = None, get=_get) -> Window | None:
    from ark_relay.features.banners.banners import _EF_CMS_LIST, _EF_CMS_POST, _ef_cms_text  # noqa: PLC0415
    d = json.loads(get(_EF_CMS_LIST.format(page=1)))
    if d.get("code") != 0:
        raise ValueError(f"终末地官网列表返回 code={d.get('code')!r}")
    # Sorted newest first by displayTime; the backend's own order is not by date.
    items = (d.get("data") or {}).get("list") or []
    for it in sorted(items, key=lambda it: -int(it.get("displayTime") or 0)):
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
    from ark_relay.features.banners.banners import _WW_SITE_ARTICLES, newest_version, wuwa_maint_notice  # noqa: PLC0415
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


# The bulletins are read through a cache: every phone state push builds tomorrow's
# plan (phone.state_payload -> plan.next_plan -> maintenance_lines -> today). A
# successful read is reused for OK_TTL seconds; a failed one is not retried for
# FAIL_TTL seconds, and that repeat is logged at INFO, not as a new fault.
OK_TTL = 3600
FAIL_TTL = 300
_CACHE: "dict[tuple[str, object], tuple[float, object]]" = {}  # (game, day asked) -> (when, window or None or exception)
_CACHE_LOCK = threading.Lock()
_SITE = {"明日方舟": "ak.hypergryph.com / web-news.hypergryph.com", "终末地": "web-news.hypergryph.com",
         "鸣潮": "鸣潮官网 kurogame.com / aki-game.com 的游戏内公告"}


# Per game, the real reads this process made (not cache hits): count, failures,
# last time. Read by the machine check #50 (machinechecks/phone_banners.py).
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
    failure is younger than FAIL_TTL. Keyed by the server day `now` falls on: the
    plan asks about tomorrow and the boot check about today, and 鸣潮's answer
    depends on the day (s16 #3)."""
    t = time.time()
    key = (game, now.astimezone(SERVER_TZ).date())
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
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
            _CACHE[key] = (t, exc)
        _count(game, t, f"{type(exc).__name__}: {exc}"[:200])
        raise
    with _CACHE_LOCK:
        _CACHE[key] = (t, got)
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
    budget = _UNTIL.set(time.monotonic() + TODAY_BUDGET)
    try:
        _today(now, sources, failed, out)
    finally:
        _UNTIL.reset(budget)
    return out


def _today(now: datetime, sources, failed: "list[str] | None", out: "dict[str, Window]") -> None:
    """today()'s loop, inside its TODAY_BUDGET."""
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
