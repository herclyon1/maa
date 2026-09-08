"""Official downtime-maintenance bulletins for the three games -- machine-readable
sources, each verified 2026-09-02/03.

The user, 2026-09-02: 「游戏官方都会提前好几天发更新公告，写什么时候停服维护。
拿到这个就简单了：服务器更新的时候就不跑他，等跑完队列之后检测时间是否已经
过了停服时间，还在停服就等，一直等到开服，更新，补跑，跑完再关机。」

| Game | Source | Format (as observed) |
|---|---|---|
| Arknights | the Next.js data `initialData.LATEST.list[]` embedded in the ak.hypergryph.com/news page, title 「[明日方舟]09月04日06:00版本更新停机维护公告」, body 「2026年09月04日06:00 - 12:00」 | see _AK_* |
| Endfield | the `bulletins[]` embedded in the endfield.hypergryph.com/news page, title 「…版本预下载与更新预告」, body 「版本维护时间 2026/09/02 06:00 - 2026/09/02 12:00（UTC+8）」 | see _EF_* |
| Wuthering Waves | the in-game bulletin JSON, 「X.Y版本内容说明」, body 「更新维护时间：2026年8月20日04:00 ~ 2026年8月20日11:00（UTC+8）」 | see _WW_* |

Each `*_window()` returns (start, end, evidence line) or None. If nothing can be
fetched it returns None; it never guesses.
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
import urllib.request
from datetime import datetime

from .config import SERVER_TZ

log = logging.getLogger("ark.maintenance")
_UA = "Mozilla/5.0"

Window = tuple[datetime, datetime, str]


def _get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _text(page: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html.unescape(page)))


def _dt(y: int, mo: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, mo, d, hh, mm, tzinfo=SERVER_TZ)


# ── Arknights ──
_AK_NEWS = "https://ak.hypergryph.com/news"
_AK_ITEM = re.compile(r'\\"cid\\":\\"(\d+)\\",\\"tab\\":\\"\w+\\",\\"sticky\\":(?:true|false),\\"title\\":\\"([^"\\]+)')
_AK_TITLE = re.compile(r"(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2}).*?(停机维护|停机更新|维护公告)")
_AK_BODY = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})\s*[-~～至]\s*(?:(\d{4})年(\d{1,2})月(\d{1,2})日\s*)?(\d{1,2}):(\d{2})")


def arknights_window(now: datetime | None = None, get=_get) -> Window | None:
    now = now or datetime.now(tz=SERVER_TZ)
    page = get(_AK_NEWS)
    for cid, title in _AK_ITEM.findall(page):
        if not _AK_TITLE.search(title):
            continue
        body = _text(get(f"{_AK_NEWS}/{cid}"))
        m = _AK_BODY.search(body)
        if not m:
            continue
        y, mo, d, h1, m1, y2, mo2, d2, h2, m2 = m.groups()
        start = _dt(int(y), int(mo), int(d), int(h1), int(m1))
        end = _dt(int(y2 or y), int(mo2 or mo), int(d2 or d), int(h2), int(m2))
        return start, end, f"官方公告：{title}（{start:%m-%d %H:%M}–{end:%H:%M}）"
    return None


# ── Endfield ──
_EF_NEWS = "https://endfield.hypergryph.com/news"
_EF_ITEM = re.compile(r'\\"cid\\":\\"(\d+)\\",\\"tab\\":\\"\w+\\",\\"sticky\\":(?:true|false),\\"title\\":\\"([^"\\]+)')
_EF_BODY = re.compile(r"维护时间\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})\s*[-~～]\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})")


def endfield_window(now: datetime | None = None, get=_get) -> Window | None:
    page = get(_EF_NEWS)
    for cid, title in _EF_ITEM.findall(page):
        if "预告" not in title and "维护" not in title:
            continue
        body = _text(get(f"{_EF_NEWS}/{cid}"))
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
    from .banners import newest_version  # noqa: PLC0415
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


def today(now: datetime | None = None, sources=None) -> dict[str, Window]:
    """Games with downtime maintenance today -> their window.

    One network request per game; a failure is treated as "no maintenance".
    """
    now = now or datetime.now(tz=SERVER_TZ)
    out: dict[str, Window] = {}
    for game, fn in (sources if sources is not None else SOURCES).items():
        try:
            w = fn(now)
        except Exception:
            log.warning("维护公告：%s 取不到", game, exc_info=True)
            continue
        if w and w[0].date() <= now.date() <= w[1].date():
            out[game] = w
    return out
