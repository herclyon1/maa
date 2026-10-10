"""Wuthering Waves banners: the Kuro BBS wiki homepage, the in-game version
bulletin, the version calendar image, and the two halves of a version."""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from datetime import datetime

from ark_relay.features.banners import banners as hub
from ark_relay.features.banners.banners import (
    Banner, crosscheck, log, newest_version, _stamps, _SWAP, Trace, _UA_BROWSER,
    upcoming,
)
from ark_relay.features.banners.wuwa_posters import (
    _KURO, _kuro_default, _kuro_gacha, _KURO_NEWS, _KURO_POST,
    wuwa_first_half_notice_end, _wuwa_poster_span, _WW_GACHA_CHECKED,
)
from ark_relay.features.banners.wuwa_history import (
    wuwa_maintenance, _WW_SITE_ARTICLES,
)


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
    """Raises ValueError when there are character tabs but none has a readable
    dateRange (an empty return would read as "none", see _wuwa); some tabs
    unreadable is one WARNING."""
    out: list[Banner] = []
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
            # The wiki entry name can carry whitespace (a leading space on 2026-09-12);
            # a raw compare against the bulletin's spelling dropped the running banner.
            who = (name_of(str(eid)) if eid else "").strip()
            if not who:
                continue
            out.append(Banner("鸣潮", str(tab.get("name") or "").strip(), (who,), a, b))
    if bad and len(bad) == n_tabs:
        raise ValueError(f"库街区 {n_tabs} 个角色唤取都读不出起止时间（countDown.dateRange）："
                         + "；".join(bad))
    if bad:
        log.warning("鸣潮：库街区 %d 个角色唤取里有 %d 个读不出起止时间，这几个池子这次没报\n%s",
                    n_tabs, len(bad), "；".join(bad))
    out.sort(key=lambda x: x.end)
    return out


def wuwa_teased(records: list, now: datetime) -> list[str]:
    """Characters the Kuro wiki marks as previewed (announced, not yet released).

    The character catalogue (id 1105) carries a corner badge per entry:
    `content.showTeaserIcon` with `showTeaserIconNum` 1 = new, 2 = previewed,
    3 = rerun, valid inside `teaserDateRange`. Read off the wiki on 2026-09-12:
    景燃 1, 绯雪 3, 莫宁 3, 心 2, 锁暝 2 - matching the badges the page draws. Stale
    flags stay on old entries (a rerun badge whose range ended 2026-04-29), so the
    range is required.
    """
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
        name = str(r.get("name") or "").strip()
        if name and a <= now <= b:
            out.append(name)
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


# This hash is a channel constant and does not change with the version; if it ever
# does stop working, read metadata.source_url from data/ww/game/notice.json in
# 555me/game-CDN-List.
_WW_NOTICE = ("https://aki-gm-resources-back.aki-game.com/gamenotice/G152/"
              "76402e5b20be2c39f095a152090afddc/zh-Hans.json")
# The character catalogue on the wiki (its id, read off the homepage's index tab).
_WW_CHAR_CATALOGUE = 1105
_WW_HDR = {"wiki_type": "9", "source": "h5",
           "referer": "https://wiki.kurobbs.com/"}


_WW_NOTICE_UP = re.compile(r"5星角色「([^」]+)」")
# The start is a date, or 「3.7版本更新后」 for a banner that opens with the version
# (its maintenance end, which the notice does not print): 2026-10-01, every
# first-half 3.7 banner post reads 「活动时间✦ 3.7版本更新后 ~ 2026年10月22日09:59」.
_WW_NOTICE_SPAN = re.compile(r"活动时间[✦\s]*(?:(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})|(\d+\.\d+版本更新后))"
                             r"\s*[~～-]\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")
_WW_NOTICE_TITLE = re.compile(r"[\[「]([^\]」]+)[\]」]\s*角色活动唤取")


def parse_wuwa_notice_banners(notice: dict) -> list[Banner]:
    """The in-game notice's own banner posts (`recommend[]`, 「[X]角色活动唤取」):
    the second official source for the running 鸣潮 banners.

    Read 2026-09-12: tabTitle 「[身赴三途]角色活动唤取」, the content names the
    five-star 「景燃」 and gives the activity span 2026-09-10 10:00 to 2026-09-29 11:59.
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
        out.append(Banner("鸣潮", tm.group(1).strip(), (up.group(1).strip(),), start,
                          datetime(*map(int, g[6:]), 59), g[5] or ""))
    return out


# The version's activity calendar (the notice's activity[] post 「3.7版本活动日历」)
# is the only official place the second-half banner's date appears before it opens:
# the version bulletin says only 「※可通过[余心所向九死未悔]角色活动唤取获得」 and
# the in-game banner post goes up when the banner opens. The calendar is a single
# image; each banner card carries a 「10.22~11.11」 label right above its name.
# Read 2026-10-01 from notice id 50868, notice/image/fYrvOmEkgCfEKFTy.png: dates
# only, no time of day.
_WW_CAL_TITLE = re.compile(r"(\d+\.\d+)版本活动日历")
_WW_CAL_IMG = re.compile(r"""src=["']([^"']+)["']""")
# The date label 「10.22~11.11」 above a banner card. Windows OCR reads its digits
# and separators its own way: on the machine 2026-10-06 「10.22~11.11」 came out
# 「]0．22」+「]1月」 split across lines, 「10.22」 as 「]0」. `_WW_CAL_FIX` normalises
# those confusions before the label is looked for; the name is matched unnormalised.
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

    `notes is None` means another source already gave the time (the caller passes
    None exactly then), so this read is only a cross-check: failing it is a fault
    the relay got over, kept to the daily report, not the group (the user,
    2026-10-06 05:07, 「报错后自己好了的，只进日报」 -- self-recovered errors go
    to the daily report only)."""
    from ark_relay.features.alarm import errwatch  # noqa: PLC0415
    cal = hub.wuwa_calendar_image(notice)
    if not cal:
        return None
    ver, nid, url = cal
    where = f"{_WW_NOTICE} activity id={nid}「{ver}版本活动日历」{url}"
    cross = notes is None
    if cross:
        # Another source already gave the start with its time of day (the Kuro BBS
        # version-news post, or the first banner's end + 1 minute). The calendar image
        # carries dates only, no hour or minute, so it cannot add anything: it is not
        # read at all (user, 2026-10-06 17:41: the image has no hour or minute and the
        # relay already has a source that does). Reading it only made OCR noise and alarms.
        tr.src("鸣潮", "版本日历", where, f"{pool} 没读图：另一来源已给出开启时刻（图上只有日期，没有几点）")
        return None
    day = None
    # Why the date was not read, kept in the trace for the machine check #2 (the
    # 10-02 「只有图没读到字」 lines never said whether the image was read at all).
    got = "这台机器不读图" if not read_image else ""
    try:
        lines = read_image(url) if read_image else None
        day = parse_wuwa_calendar(lines or [], pool, now) if lines else None
        if lines and not day:
            if cross:
                log.warning("鸣潮 %s 版本活动日历读了 %d 行，没找到「%s」的日期：%s", ver, len(lines), pool,
                            " / ".join(x.text for x in lines[:60]), extra=errwatch.recovered())
            else:
                log.warning("鸣潮 %s 版本活动日历读了 %d 行，没找到「%s」的日期：%s", ver, len(lines), pool,
                            " / ".join(x.text for x in lines[:60]))
            got = f"读出 {len(lines)} 行，没找到它上方的日期：" + " / ".join(x.text for x in lines[:12])
        elif read_image and lines is None:
            got = "读图没有结果：桌面读屏没返回"
        elif read_image and not lines:
            got = "图上一行字都没读出"
    except Exception as e:
        if cross:
            log.warning("鸣潮版本活动日历读图失败", exc_info=True, extra=errwatch.recovered())
        else:
            log.warning("鸣潮版本活动日历读图失败", exc_info=True)
        got = f"读图出错：{type(e).__name__}: {e}"
    if day is not None and day.date() < now.date():
        got = f"读出的日期 {day:%m-%d} 已经过了"
    if day is None or day.date() < now.date():
        if cross:
            log.warning("这条公告只有图，没读到字：%s", where, extra=errwatch.recovered())
            tr.src("鸣潮", "版本日历", where, f"{pool} 的日期没读出，另一来源已给出（{got[:240]}）")
        else:
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
        # the relay got over (the daily report only - the user on 2026-10-06
        # 05:07 about faults the relay got over: 「报错后自己好了的，只进日报、不进群」);
        # without it, it is pushed.
        if span:
            from ark_relay.features.alarm import errwatch  # noqa: PLC0415
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
        events = (get(_KURO_NEWS, {"gameId": 3, "eventType": 3, "pageSize": 100}).get("data") or {}).get("list")

        def detail_of(pid: str) -> dict:
            return ((get(_KURO_POST, {"isOnlyPublisher": 0, "postId": pid, "showOrderType": 2}).get("data") or {})
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
            continue
        if not found:
            continue
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
                return None
            end = hub.parse_wuwa_poster_first_end(lines)
            if end and end > now:
                tr.src("鸣潮", "版本资讯", f"{what} {page}「{title}」第 {n} 张图 {url}",
                       f"{ver} 第一期 {end:%Y-%m-%d %H:%M} 结束（服务器时间）")
                return end
    return None


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
        return hub._json(_KURO + path, _UA_BROWSER, body, h)

    cache: dict[str, str] = {}

    def name_of(eid: str) -> str:
        if eid not in cache:
            try:
                d = post("/wiki/core/catalogue/item/getEntryDetail",
                         {"id": eid})["data"] or {}
                cache[eid] = str(d.get("name") or "").strip()
            except Exception:
                log.warning("库街区条目 %s 查不到名字", eid, exc_info=True)
                cache[eid] = ""
        return cache[eid]

    # Fetch the bulletin first: its 「全新角色」 section is the only authoritative basis
    # for telling a debut from a rerun. getPage gives only the banners and says nothing
    # about who is new; of the two banners in the first half of 3.6, 达妮娅 was a rerun.
    debut: "list[tuple[str, str]]" = []
    notice_ok = True
    notice_banners: list[Banner] = []
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
    end = min((b.end for b in pools), default=None)

    # If the bulletin cannot be fetched, better to report one extra rerun than to lose
    # the countdown entirely -- the banners within a version all end at the same time
    # anyway, and the value of this line is mostly in that moment.
    names = {w for w, _ in debut}
    got = [b for b in pools if set(b.chars) & names] if notice_ok else pools
    for b in got:
        if b.start <= now <= b.end:
            tr.ends |= _stamps(b.end)
            tr.src("鸣潮", "当期", _KURO + "/wiki/core/homepage/getPage", f"{b.name} {'、'.join(b.chars)} {b.start:%Y-%m-%d %H:%M}~{b.end:%Y-%m-%d %H:%M}")
            other = next((x for x in notice_banners if x.name == b.name or set(x.chars) & set(b.chars)), None)
            if other:
                tr.src("鸣潮", "游戏公告", _WW_NOTICE, f"{other.name} {'、'.join(other.chars)} "
                       + (f"{other.start:%Y-%m-%d %H:%M}" if other.start else other.start_note)
                       + f"~{other.end:%Y-%m-%d %H:%M}")
            tr.checks.append(crosscheck("鸣潮", "库街区", b, "游戏公告", other) if notice_ok
                             else "鸣潮：游戏公告取不到，只有库街区一个来源 ✗")

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
        teased = wuwa_teased((((page.get("data") or {}).get("results") or {}).get("records")) or [], now)
        tr.src("鸣潮", "预告角色", _KURO + f"/wiki/core/catalogue/item/getPage catalogueId={_WW_CHAR_CATALOGUE}", "预告角标：" + ("、".join(teased) or "无"))
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
