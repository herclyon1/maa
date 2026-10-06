"""Countdowns for the three games' new-character banners, and when the next one
starts.

**Only banners that debut a brand-new character are reported** -- reruns, standard
and rotating banners are never reported. The user, 2026-08-30: 「我有且只要全新角色的
卡池信息，其他的不要，因为我都有老角色了。」

## Data sources (each measured 2026-08-30; all official)

| Game | Source | What it gives |
|------|------|---------|
| Wuthering Waves | Kuro BBS `api.kurobbs.com/wiki/core/homepage/getPage` (no token) | banner name, start/end; character names need a further `getEntryDetail` |
| Wuthering Waves preview | official in-game bulletin `aki-gm-resources-back.aki-game.com` | the **brand-new 5-stars** and banner names for both halves of the version |
| Endfield | Skland `zonai.skland.com/web/v1/wiki/char-pool` | banner name, start/end timestamps; character names need a further `item/info` |
| Endfield preview | official bulletin `game-hub.hypergryph.com/bulletin/v2/aggregate` | the **brand-new operators** and banner names for both halves of the version |
| Arknights | PRTS `卡池一览/限时寻访` | banner name, UP operators, exact start/end |
| Arknights preview | the official site's 「…寻访即将开启」 posts | the next banner, its six-stars and opening time |

**Why this must use official sources and not Fandom**: measured 2026-08-30, at the
same moment Fandom (global servers) said 「False Promise for Tomorrow / Denia」 while
Kuro BBS (CN servers) said 「予明日以谎言 / 达妮娅」. Neither the names nor the
characters line up, and the servers are not on the same schedule. Using Fandom would
report the wrong thing.

## Only what is published

The user, 2026-09-30 23:56: 「尤其是推测内容，我不希望见到有推测，信息全部都是能查到的。」
Every line says only what an official source states. Nothing is worked out:
no "the next one opens when this one ends", no stream date from a rule, no
community schedule, no "announced N days ahead". A version bulletin that names
the second-half banner but gives no time yields the name and "time not
published"; nothing announced yields "not announced". All three games always
get a block.

If nothing can be fetched this returns empty: one line missing from the report beats
having no report.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .config import SERVER_TZ

log = logging.getLogger("ark.banners")

# PRTS checks the User-Agent: curl's default UA gets through, a browser UA gets a
# 403 instead. Do not "optimise" this into a Chrome UA; everything 403s (measured
# twice, 2026-08-30).
_UA_PLAIN = "curl/8.7.1"
_UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


@dataclass(frozen=True)
class Banner:
    """One banner. `chars` are the new characters debuting on it; there can be
    more than one.
    """

    game: str
    name: str
    chars: tuple[str, ...]
    start: "datetime | None"    # None only on a notice that opens 「X版本更新后」
    end: datetime
    start_note: str = ""        # that wording, when start is None


@dataclass
class Trace:
    """Where every line of the section came from, and what was checked.

    Asked for by the user on 2026-09-12, after two invented previews in one day:
    is there nothing that guards this section against invention or bad data?
    Three things stand between the fetchers and the notification now:

    * provenance - every fetched value is recorded with its URL/field
      (`sources`), and the trace is written next to the state so a line can be
      traced back after the fact;
    * cross-checks - each running banner is read from **two** official sources and
      the section says whether they agree (`checks`);
    * the date gate in `render` - a next-banner line may only carry a date that an
      official source assigned to a *start* (`starts`: an opening time, or a
      maintenance window), or an end when the line says it ends. A line
      that fails is withheld and logged instead of sent. There is no class for
      a worked-out or predicted date any more (2026-09-30, the user: no
      guesses at all), so such a date can never pass.
    """

    sources: list[str]
    starts: set
    ends: set
    checks: list[str]
    withheld: list[str]
    # game -> the next banner's published end, printed after its start
    until: dict = field(default_factory=dict)
    # game -> how a start that no source printed was worked out, said on the line
    how: dict = field(default_factory=dict)
    # a source that answered but could not be read (risk control, changed shape),
    # with the raw shape: kept apart from "the source has no such post"
    problems: list = field(default_factory=list)
    # game -> (start, who) of the next banner as render() was given it: the
    # group's 「明天开新卡池」 is built from the same dict (report._announce_banners)
    nexts: dict = field(default_factory=dict)
    # when the section started being built: the machine check (#58) reads the
    # relay's own log lines from here on
    born: float = field(default_factory=time.time)

    @classmethod
    def new(cls) -> "Trace":
        return cls([], set(), set(), [], [])

    def src(self, game: str, what: str, where: str, value: str) -> None:
        self.sources.append(f"{game}｜{what}｜{where}｜{value}")


def _stamps(when: datetime) -> set[str]:
    return {f"{when:%m-%d}", f"{when:%m-%d %H:%M}"}


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
_AK_HTML_TIME = re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d)\s*~\s*<br\s*/?>\s*(\d{4}-\d\d-\d\d \d\d:\d\d)")
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


# ── Endfield: official Skland API ──────────────────────────────
# chars[].name in char-pool is empty, so item/info has to be queried as well; the gid
# comes from what follows `gameEntryId=` in chars[].pcLink.
# This endpoint belongs to Endfield alone: passing ?gameId=1 still returns Endfield,
# and every /api/v1/game/arknights/* path 404s.
_SK_UP = "label_type_up"


def parse_endfield(pools: list, name_of) -> list[Banner]:
    """`pools` is char-pool's data.list; `name_of(gid)` returns a character name."""
    out: list[Banner] = []
    for p in pools:
        try:
            # Server clock, not the host's: run from Tokyo the same timestamp read
            # 12:59 while the bulletin said 11:59, and the cross-check flagged it.
            a = datetime.fromtimestamp(int(p["poolStartAtTs"]), tz=SERVER_TZ).replace(tzinfo=None)
            b = datetime.fromtimestamp(int(p["poolEndAtTs"]), tz=SERVER_TZ).replace(tzinfo=None)
        except (KeyError, TypeError, ValueError):
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
_EF_POOL = re.compile(r"「([^」]+)」特许寻访")
_EF_UP = re.compile(r"6星干员【([^】]+)】获取概率提升")


_VER = re.compile(r"(\d+)\.(\d+)")


def newest_version(entries: "list[tuple[str, str]]") -> str:
    """From [(title, body)], pick the body with the highest version number.

    As 3.6 nears its end the 3.7 version notes are posted first and both exist at
    once. This used to concatenate every 「版本内容说明」, so as soon as 3.7 came before
    3.6 the "whoever comes after the one currently running" criterion pointed at the
    wrong character. Only the highest version number is accepted, so 3.7 gets reported
    automatically the moment it is published, with no code change.
    """
    best, best_key = "", (-1, -1)
    for title, body in entries:
        m = _VER.search(title or "")
        key = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        if key >= best_key:
            best, best_key = body, key
    return best


def upcoming(debut: "list[tuple[str, str]]", live: "set[str]"
             ) -> "list[tuple[str, str]]":
    """The bulletin lists the version's banners in order; only the ones after the
    banner currently running have yet to open.

    "Not in live" alone will not do -- the first half of this version has already
    finished, so that character is not in live either, and by that criterion the
    **previous** banner would get reported as the next one.
    """
    idx = max((i for i, (w, _) in enumerate(debut) if w in live), default=None)
    return debut[idx + 1:] if idx is not None else []


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
    out: list[Banner] = []
    content = ((home or {}).get("data") or {}).get("contentJson") or {}
    for m in content.get("sideModules") or []:
        title = str(m.get("title") or "")
        if "唤取" not in title or "角色" not in title:
            continue
        for tab in (m.get("content") or {}).get("tabs") or []:
            dr = (tab.get("countDown") or {}).get("dateRange") or []
            if len(dr) != 2:
                continue
            try:
                a = datetime.strptime(f"{dr[0]}:00", "%Y-%m-%d %H:%M:%S")
                b = datetime.strptime(f"{dr[1]}:59", "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            imgs = tab.get("imgs") or []
            eid = (imgs[0].get("linkConfig") or {}).get("entryId") if imgs else None
            # The wiki entry name can carry whitespace (a leading space on 2026-09-12);
            # a raw compare against the bulletin's spelling dropped the running banner.
            who = (name_of(str(eid)) if eid else "").strip()
            if not who:
                continue
            out.append(Banner("鸣潮", str(tab.get("name") or "").strip(), (who,), a, b))
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


# ── Deciding what counts as a debut ────────────────────────────
_RERUN = ("复刻", "Rerun", "rerun")
# Banners that by definition cannot debut a character, excluded by name.
# The first version on 2026-08-30 did not exclude them and judged 「联合行动23」 a debut
# (诺威尔 and 杏仁 are both old operators).
_NOT_DEBUT = ("联合行动", "中坚寻访", "中坚甄选", "概率提升")


def debut_only(banners: list[Banner]) -> list[Banner]:
    """Keep debuts only.

    What is passed in must be the **complete history, sorted by start time**.
    """
    seen: set[str] = set()
    out: list[Banner] = []
    for b in banners:
        skip = any(k in b.name for k in _RERUN + _NOT_DEBUT)
        fresh = tuple(c for c in b.chars if c not in seen)
        seen.update(b.chars)          # record rotating-banner characters too; they are not new
        if skip or not fresh:
            continue
        out.append(Banner(b.game, b.name, fresh, b.start, b.end))
    return out


# Order within the daily report: same as the three run-record blocks above
# (MAA -> Wuthering Waves -> Endfield)
_GAME_ORDER = ("明日方舟", "鸣潮", "终末地")


def _stamp(when: datetime) -> str:
    # Some sources only give a date; inventing a 00:00 would be false precision.
    return f"{when:%m-%d}" if (when.hour, when.minute) == (0, 0) else f"{when:%m-%d %H:%M}"


_DATE_TOKEN = re.compile(r"\d\d-\d\d(?: \d\d:\d\d)?")


def gate_preview(line: str, trace: "Trace") -> str:
    """Why a next-banner line must not go out, or '' when it may.

    Every date in the line has to be one an official source assigned to a
    *start* (an opening time, a maintenance window), or an end when the line
    says 结束 / 换池. 「09-18 03:59 之后开」 - an end dressed up as a start - fails
    here, and so does any date that was worked out rather than read.
    """
    for tok in _DATE_TOKEN.findall(line):
        # a bare MM-DD is also satisfied by an MM-DD HH:MM stamp of the same day
        ok = (tok in trace.starts
              or (("结束" in line or "换池" in line) and tok in trace.ends))
        if not ok:
            return f"日期 {tok} 没有来源把它当作开始时刻"
    return ""


_WHO = re.compile(r"(.*)「([^」]+)」$")
# Kuro closes a banner at 09:59:59 and opens the next at 10:00: one moment.
_SWAP = timedelta(minutes=1)


def _next_line(when: "datetime | None", who: str, swap: bool, note: str = "",
               until: "datetime | None" = None, how: str = "") -> str:
    m = _WHO.match(who)
    chars, pool = (m.group(1), m.group(2)) if m else (who, "")
    if when is not None and how:
        # worked out from a published end (first half closes 09:59, the second
        # opens 10:00): the clock time, and that it was worked out
        at = f"北京 {_stamp(when)} 开（{how}）" + (f" · {_stamp(until)} 结束" if until else "")
    elif swap and until is None:
        # A start taken as "when the running one ends" says so. A start the
        # publisher printed with its own end (the Wuthering Waves version-news poster: 10:00
        # after a 09:59 close) is printed as published instead.
        at = "换池时开"
    elif when is not None and note and (when.hour, when.minute) == (0, 0):
        # a date-only source that names itself (the 鸣潮 version calendar): the date
        # and where it is from, never a clock time
        at = f"{_stamp(when)} 开始（{note}）"
    elif when is not None:
        at = f"北京 {_stamp(when)} 开" + (f" · {_stamp(until)} 结束" if until else "")
    else:
        at = note or "开始时间官方未公布"
    return "· 下期：" + " · ".join(x for x in (pool, chars, at) if x)


def render(banners: list[Banner], now: datetime,
           next_starts: "dict[str, tuple[datetime | None, str]] | None" = None,
           notes: "dict[str, str] | None" = None,
           trace: "Trace | None" = None,
           failed: "list[str] | None" = None,
           leads: "dict[str, str] | None" = None) -> str:
    """The section at the end of the daily report: a heading that names the time
    zone, then all three games, two lines each, e.g. for Wuthering Waves:

        · 当期：但愿长圆如此夜 · 心 · 北京 10-22 09:59 结束 · 剩 21 天 10 小时
        · 下期：余心所向九死未悔 · 锁暝 · 北京 10-22 10:00 开 · 11-11 11:59 结束

    The user, 2026-09-02: 「要有当期新 UP 角色的卡池倒计时（如果没有 UP 就不显示），
    而且得要有卡池预告」, and the three games must look the same. 2026-09-30 23:56:
    no guesses - only what can be looked up. So:
    · no new-character banner running -> 「当期无新角色卡池」 (reruns stay out);
    · `next_starts[game] = (start, who)` is an announced debut banner; `start` is
      None when the publisher named it but gave no time. Nothing announced ->
      「下期：官方未公告」, plus `notes[game]` (other official facts) if any, or
      「下期：<leads[game]>」 when the publisher has hinted at it;
    · the running banner's end and the next one's start being the same moment
      prints once, as a changeover;
    · a game in `failed` says it was not read - never "none".
    """
    if trace is not None:
        trace.nexts = dict(next_starts or {})
    live: dict[str, list[Banner]] = {}
    for b in sorted((x for x in banners if x.start <= now <= x.end), key=lambda x: x.end):
        live.setdefault(b.game, []).append(b)
    nxt = {g: v for g, v in (next_starts or {}).items()
           if v[1] and (v[0] is None or v[0] > now
                        # a date-only start stays until that day is over
                        or ((v[0].hour, v[0].minute) == (0, 0) and v[0].date() == now.date()))}
    nt = notes or {}
    lost = {g: f[len(g):] for f in failed or () for g in _GAME_ORDER if f.startswith(g)}
    blocks: list[str] = []
    for game in _GAME_ORDER:
        lines = [game]
        if game in lost:
            lines.append(f"· 这次没读到{lost[game]}，不是没有卡池")
            blocks.append("\n".join(lines))
            continue
        when, who = nxt.get(game, (None, ""))
        swapped = False
        for b in live.get(game, []):
            swap = when is not None and abs(when - b.end) <= _SWAP
            swapped |= swap
            lines.append(f"· 当期：{b.name} · {'、'.join(b.chars)} · 北京 {_stamp(b.end)} "
                         f"{'换池' if swap else '结束'} · 剩 {(b.end - now).days} 天 "
                         f"{(b.end - now).seconds // 3600} 小时")
        if game not in live:
            lines.append("· 当期无新角色卡池")
        if who:
            ln = _next_line(when, who, swapped, nt.get(game, ""),
                            trace.until.get(game) if trace is not None else None,
                            trace.how.get(game, "") if trace is not None else "")
        elif game in (leads or {}):
            ln = f"· 下期：{leads[game]}"
        else:
            ln = "· 下期：官方未公告" + (f" · {nt[game]}" if game in nt else "")
        if trace is not None and (why := gate_preview(ln, trace)):
            # WARNING: holding a line back is the check working, and the report
            # already says 「已扣下」. As an ERROR it rang the group (errwatch;
            # 09-26 21:46:53) for one line of the daily report.
            log.warning("卡池下期没通过来源核对，扣下：%s ← %s", ln, why)
            trace.withheld.append(f"{ln} ← {why}")
            ln = "· 下期：⚠️ 这一行没通过来源核对，已扣下（原文在日志）"
        lines.append(ln)
        blocks.append("\n".join(lines))
    # The cross-check results stay in the trace file (state/banners/<day>.json) and
    # withheld lines still say so; the footer listing them was dropped on
    # 2026-09-14 at the user's request (it carried nothing he acts on).
    return "🎴 卡池（时间为北京时间）\n" + "\n".join(blocks)


# ── Aggregation: pull all three sources and render the report section ──
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

# Measured on the game machine 2026-08-31: raw.githubusercontent.com takes 33 s
# (past the timeout), jsDelivr 2.8-4.6 s. Mirrors in measured order, raw last.
def gh_raw(owner: str, repo: str, branch: str, path: str) -> list[str]:
    """Several routes to the same GitHub file, ordered by speed measured on the
    game machine.
    """
    return [
        f"https://fastly.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}",
        f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}",
        f"https://gh-proxy.com/https://raw.githubusercontent.com/"
        f"{owner}/{repo}/{branch}/{path}",
        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}",
    ]


# The two Yituliu tables the user pointed us at (Arknights, Endfield). Both are
# hand-maintained. They are read and recorded next to the official sources, but
# they are not official: the Arknights one marks predictions with
# `accuracyFlag: false` (and on 08-31 still marked 「P3R联动」 09-04 false two days
# after the official post), the Endfield one has no such mark at all.
_AK_SCHEDULE = gh_raw("Arknights-yituliu", "frontend-v2-plus", "main",
                      "src/utils/gachaScheduleOptions.js")
_EF_YITULIU = gh_raw("Arknights-yituliu", "ef-frontend-v1", "main",
                     "custom/core/gacha/data/pool_info_table.json")
_KURO = "https://api.kurobbs.com"
_ZONAI = "https://zonai.skland.com"
# Endfield's official bulletin aggregate endpoint, no token needed. code is a
# channel constant.
_EF_BULLETIN = ("https://game-hub.hypergryph.com/bulletin/v2/aggregate"
                "?lang=zh-cn&platform=Windows&channel=1&type=0"
                "&code=endfield_5SD9TN&hideDetail=0")

def _json(url: str, ua: str, data: "bytes | None" = None,
          headers: "dict | None" = None, timeout: int = 20) -> dict:
    h = {"User-Agent": ua}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _text(url: str, ua: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _first(urls: list[str], ua: str, timeout: int = 12) -> str:
    """Try each in turn and return the first that works; the last error otherwise."""
    err: Exception = RuntimeError("no mirror answered")
    for u in urls:
        try:
            return _text(u, ua, timeout)
        except Exception as e:  # noqa: BLE001
            log.debug("镜像取不到 %s：%s", u, e)
            err = e
    raise err


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


def parse_ef_yituliu(rows: list) -> "list[tuple[str, str, datetime, datetime]]":
    """Yituliu's Endfield pool table -> [(character, banner name, start, end)]."""
    out = []
    for r in rows or []:
        try:
            out.append((str(r["character"]), str(r["poolName"]),
                        datetime.strptime(r["poolStart"], "%Y/%m/%d %H:%M:%S"),
                        datetime.strptime(r["poolEnd"], "%Y/%m/%d %H:%M:%S")))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out, key=lambda x: x[2])


def _yituliu_future(game: str, now: datetime, tr: "Trace") -> "list[tuple[str, datetime, bool]]":
    """Read the game's Yituliu table and record what it has from now on, in the
    trace only. [(name, start, officially announced)]; [] when unreadable (it is
    not an official source, so its absence never makes a game 「没读到」).
    """
    try:
        if game == "明日方舟":
            url = _AK_SCHEDULE
            fut = [x for x in parse_ak_schedule(_first(url, _UA_BROWSER)) if x[1] > now]
        else:
            url = _EF_YITULIU
            fut = [(f"{c}「{p}」", st, False)
                   for c, p, st, _en in parse_ef_yituliu(json.loads(_first(url, _UA_BROWSER))) if st > now]
    except Exception:
        log.warning("%s一图流取不到", game, exc_info=True)
        return []
    tr.src(game, "一图流", url[0], "今后条目：" + ("、".join(
        f"{n} {st:%Y-%m-%d}（{'已官宣' if ok else '一图流预测，不写'}）" for n, st, ok in fut) or "无"))
    return fut


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
    for start, who, _posted, _end, _cid in arknights_banner_posts(now, get):
        return (start, who) if start > now else None
    return None


def arknights_banner_posts(now: datetime, get=None, limit: int = 2
                           ) -> "list[tuple[datetime, str, datetime, datetime, str]]":
    """The newest debut-banner posts on the official site, newest first:
    (opening time, six-star「banner」, posting time, closing time, cid). Reruns
    (「…即将复刻开启」, e.g. cid 8588 【砺火成锋】 of 06-12) are skipped - they are
    not new banners.
    """
    get = get or (lambda u: _text(u, _UA_BROWSER))
    page = get(_AK_NEWS)
    out: list[tuple[datetime, str, datetime, datetime, str]] = []
    seen = set()
    for cid, title, ts in _AK_NEWS_ITEM.findall(page):
        if cid in seen or "寻访" not in title or "开启" not in title or "复刻" in title:
            continue
        seen.add(cid)
        body = _ak_article_text(get(f"{_AK_NEWS}/{cid}"))
        m6 = _AK_SIX_LINE.search(body)
        six = [x.strip() for x in re.split(r"[/、]", m6.group(1))] if m6 else []
        sp = _AK_SPAN.search(body)
        if not six or not sp:
            continue
        mo, d, hh, mm, mo2, d2, hh2, mm2 = (int(x) for x in sp.groups())
        year = now.year + (1 if mo < now.month - 6 else 0)
        start = datetime(year, mo, d, hh, mm)
        end = datetime(year + (1 if mo2 < mo else 0), mo2, d2, hh2, mm2)
        pool = re.search(r"【([^】]+)】", title)
        who = "、".join(x for x in six if x) + (f"「{pool.group(1)}」" if pool else "")
        out.append((start, who, datetime.fromtimestamp(int(ts)), end, cid))
        if len(out) >= limit:
            break
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
    get = get or (lambda u: _text(u, _UA_BROWSER))
    page = get(_AK_NEWS)
    comm = next(((cid, t, int(ts)) for cid, t, ts in _AK_NEWS_ITEM.findall(page)
                 if "制作组通讯" in t), None)
    if comm is None:
        why.append("无：官网新闻里没有制作组通讯")
        return None
    cid, title, ts = comm
    posted = datetime.fromtimestamp(ts)
    later = [p for p in posts or () if p[2] > posted]
    if later:
        why.append(f"过期：通讯（{posted:%m-%d} 发）之后官网出了寻访公告「{later[0][1]}」（{later[0][2]:%m-%d} 发）")
        return None
    if ran := [t for t in opened or () if t > posted]:
        why.append(f"过期：通讯（{posted:%m-%d} 发）之后开的首发卡池在跑（{min(ran):%m-%d %H:%M} 开）")
        return None
    body = _ak_article_text(get(f"{_AK_NEWS}/{cid}"))
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


def crosscheck(game: str, a_name: str, a: Banner, b_name: str, b: "Banner | None") -> str:
    """One line for the section's 核对 footer: the two sources agree, or how they differ.

    `b` is what the second source says about the banner `a` (None: it has no such
    banner). Compared: banner name, the characters (b's must be within a's), start
    and end. A one-hour skew is tolerated only when one side gives a date without a
    clock (00:00).
    """
    if b is None:
        return f"{game}：{a_name} 有「{a.name}」，{b_name} 里找不到 ✗"
    diffs = []
    if a.name and b.name and a.name != b.name:
        diffs.append(f"池名 {a_name}「{a.name}」/ {b_name}「{b.name}」")
    if b.chars and not set(b.chars) <= set(a.chars):
        diffs.append(f"角色 {a_name} {'、'.join(a.chars)} / {b_name} {'、'.join(b.chars)}")
    for label, x, y in (("开始", a.start, b.start), ("结束", a.end, b.end)):
        if y is None:
            # 「3.7版本更新后」: no clock to compare, the end is still checked
            continue
        if (x.hour, x.minute) == (0, 0) or (y.hour, y.minute) == (0, 0):
            same = x.date() == y.date()
        else:
            # to the minute: Skland ends at 11:59:59, the bulletin writes 11:59
            same = x.replace(second=0, microsecond=0) == y.replace(second=0, microsecond=0)
        if not same:
            diffs.append(f"{label} {a_name} {x:%m-%d %H:%M} / {b_name} {y:%m-%d %H:%M}")
    if diffs:
        return f"{game}：{a_name} 和 {b_name} 对不上 ✗（" + "；".join(diffs) + "）"
    if b.start is None:
        return f"{game}：{a_name}={b_name} ✓（{b_name}开始写「{b.start_note}」，只核了结束）"
    return f"{game}：{a_name}={b_name} ✓"


def _arknights(now: datetime, trace: "Trace | None" = None,
               leads: "dict[str, str] | None" = None
               ) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Both PRTS pages combined to decide debuts; the next debut banner from the
    official site's post, or from a PRTS row once PRTS has registered it. None
    when neither has one.
    """
    tr = trace if trace is not None else Trace.new()
    rows: list[Banner] = []
    for page in _AK_PAGES:
        url = _PRTS + urllib.parse.quote(page)
        try:
            rows += parse_arknights(
                _json(url, _UA_PLAIN)["parse"]["wikitext"]["*"])
            continue
        except Exception as e:  # the page is the second source
            api_why = f"{type(e).__name__}: {e}"
            log.info("PRTS 接口取不到 %s，改读页面", page, exc_info=True)
        try:
            got, rarity = parse_arknights_html(_text(_PRTS_PAGE + urllib.parse.quote(page), _UA_PLAIN, timeout=40))
        except Exception:
            log.warning("PRTS 接口和页面都取不到 %s（接口：%s）", page, api_why, exc_info=True)
            continue
        if not got:
            log.warning("PRTS 接口取不到 %s，页面解析出 0 行（接口：%s）", page, api_why)
            continue
        rows += got
        # The API failed and the page gave the table: a fault the relay got over,
        # the daily report only (the user on 2026-10-06 05:07 about faults the relay got over: 「报错后自己好了的，只进日报、不进群」).
        from . import errwatch  # noqa: PLC0415
        log.warning("方舟卡池表：资料站的数据入口没取到「%s」，改读它的页面读到了 %d 行\n数据入口：%s",
                    page, len(got), api_why, extra=errwatch.recovered())
        for who, r in rarity.items():
            if _rarity_cache.get(who, -1) < 0:   # the API is down, so ak_rarity would drop them all
                _rarity_cache[who] = r
        tr.src("明日方舟", "卡池表", _PRTS_PAGE + page, f"资料站数据入口出错，改读页面：{len(got)} 行")
    if not rows:
        raise RuntimeError("PRTS 两条路都没读到卡池表")
    rows.sort(key=lambda b: b.start)
    debut = debut_only(rows)
    # Look up rarity only for the ones currently running (not the dozens of historical
    # entries); report six-stars only
    debut = [six_star_only(b) if b.start <= now <= b.end else b for b in debut]
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
    for st, who, _p, _e, _c in posts:
        if st > now:
            tr.starts |= _stamps(st)
            return debut, (st, who)
    # PRTS registers a banner once it is announced, so its time is published. Only
    # a debut counts (a rerun is never "the next banner").
    for b in (six_star_only(x) for x in debut if x.start > now):
        if b.chars:
            tr.starts |= _stamps(b.start)
            return debut, (b.start, f"{'、'.join(b.chars)}「{b.name}」")
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


def _endfield(cred, sk_get, now: datetime, trace: "Trace | None" = None
              ) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Running banners come from Skland (authoritative on timing); debuts and
    previews come from the official version bulletin.
    """
    tr = trace if trace is not None else Trace.new()
    # Unreadable must raise: `collect` then reports the game as not read, where
    # an empty return would print "no new banner running", which is false.
    pools = (sk_get("/web/v1/wiki/char-pool")["data"] or {}).get("list") or []

    def name_of(gid: str) -> str:
        try:
            item = ((sk_get(f"/web/v1/wiki/item/info?id={gid}")["data"] or {})
                    .get("item") or {})
            return str(item.get("name") or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    live = parse_endfield(pools, name_of)

    # Official bulletin: which new operators this version has, and on which banner
    html = ""
    debut: "list[tuple[str, str]]" = []
    notice_ok = True
    try:
        d = _json(_EF_BULLETIN, _UA_BROWSER, timeout=25)
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
        ends_n = endfield_pool_ends(html) if notice_ok else {}
    except Exception:  # noqa: BLE001
        pools_n, ends_n = [], {}
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
        if official := endfield_next_from_news(now):
            tr.starts |= _stamps(official[0])
            tr.src("终末地", "预告", _EF_NEWS, f"{official[1]} 开 {official[0]:%Y-%m-%d %H:%M}")
            return got, official
    except Exception:
        log.warning("终末地官网寻访公告取不到", exc_info=True)
    # Yituliu's table has no announced/predicted mark, so it is recorded only.
    _yituliu_future("终末地", now, tr)
    return got, None


_EF_NEWS = "https://endfield.hypergryph.com/news"
_EF_SIX_UP = re.compile(r"概率提升的6星干员为【([^】]+)】")
_EF_OPEN_AT = re.compile(r"开放时间[：:]\s*(?:(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})|「[^」]+」版本(?:开启|更新)后)")
_EF_MAINT = re.compile(r"(?:更新)?维护时间\s*\d{4}/\d{1,2}/\d{1,2}\s*\d{1,2}:\d{2}\s*[-~～]\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})")


def endfield_next_from_news(now: datetime, get=None) -> "tuple[datetime, str] | None":
    """The newest banner notice on the official site whose banner has not opened:
    (opening time, operator「banner」). None when there is none.

    Same page shape as the Arknights site (a Next.js list of cid/title/displayTime).
    Recorded 2026-09-12: cid 6097 「冬猎」特许寻访说明, posted 09-01; its body gives
    the opening as "after the version update - 2026/09/30 11:59" and names the
    rate-up six-star 【提弗洛斯】. A banner that opens "after the version update"
    opens when the maintenance window in the pre-download notice ends
    (2026/09/02 06:00 - 12:00 there).
    """
    get = get or (lambda u: _text(u, _UA_BROWSER))
    page = get(_EF_NEWS)
    items = _AK_NEWS_ITEM.findall(page)
    maint = None
    for cid, title, _ts in items:
        if "更新预告" in title or "版本更新说明" in title:
            if m := _EF_MAINT.search(_ak_article_text(get(f"{_EF_NEWS}/{cid}"))):
                y, mo, d, hh, mm = (int(x) for x in m.groups())
                maint = datetime(y, mo, d, hh, mm)
                break
    seen = set()
    for cid, title, _ts in items:
        if cid in seen or "特许寻访说明" not in title:
            continue
        seen.add(cid)
        body = _ak_article_text(get(f"{_EF_NEWS}/{cid}"))
        six = _EF_SIX_UP.search(body)
        at = _EF_OPEN_AT.search(body)
        if not six or not at:
            continue
        if at.group(1):
            y, mo, d, hh, mm = (int(x) for x in at.groups())
            start = datetime(y, mo, d, hh, mm)
        elif maint:
            start = maint
        else:
            continue
        pool = re.search(r"「([^」]+)」特许寻访说明", title)
        who = six.group(1).strip() + (f"「{pool.group(1)}」" if pool else "")
        return (start, who) if start > now else None
    return None


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
    from .desktop import _name_in  # noqa: PLC0415 - desktop is Windows-side machinery
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
    from . import errwatch  # noqa: PLC0415
    cal = wuwa_calendar_image(notice)
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
    from .desktop import _name_in  # noqa: PLC0415
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


def _pause(seconds: float) -> None:
    import time  # noqa: PLC0415
    time.sleep(seconds)


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
        return _json(url, _UA_BROWSER, None, {"Cookie": cookie, "Origin": "https://space.bilibili.com",
                                              "Referer": f"https://space.bilibili.com/{_BILI_UID}/dynamic"})
    get = get or fetch
    sleep = sleep or _pause
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
        return _json(_KURO + path, _UA_BROWSER, urllib.parse.urlencode(payload).encode(), h)
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
        return _json(_KURO + path, _UA_BROWSER, urllib.parse.urlencode(payload).encode(), h)
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
    for what, find in (("库街区", lambda: _kuro_poster(ver, now, get)),
                       ("B 站", lambda: _bili_poster(ver, now, bili))):
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
                from . import errwatch  # noqa: PLC0415
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

    from . import desktop  # noqa: PLC0415
    from .config import atomic_write_bytes, atomic_write_text  # noqa: PLC0415
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

    from .desktop import Line  # noqa: PLC0415
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


def _wuwa_second_half(notice: dict, p: str, w: str, now: datetime, end: "datetime | None",
                      read_image, notes: "dict[str, str] | None", tr: "Trace", kuro_get, bili_get
                      ) -> "datetime | None":
    """The second half's start (banner `p`, character `w`) when the game notice gives none."""
    at = None
    # In order: the banner's own Kuro BBS notice (text, to the minute); the
    # version-news poster (OCR, to the minute); the first half's printed
    # end + 1 min (worked out, said so on the line); the version calendar
    # (date only). Each clock time names where it came from in the trace.
    cal = wuwa_calendar_image(notice)
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
            from . import errwatch  # noqa: PLC0415
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
    day = _wuwa_calendar_start(notice, p, now, end, read_image, None if at else notes, tr)
    if at is not None:
        agree = ("没读出 —" if day is None
                 else f"{day:%m-%d} " + ("✓" if day.date() == at.date() else "✗"))
        tr.checks.append(f"鸣潮：{'长图识别' if span else '推导'} {p} {at:%m-%d %H:%M} 开 ↔ 版本日历 {agree}")
    else:
        at = day
    return at


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
    return _json(_KURO + path, _UA_BROWSER, urllib.parse.urlencode(payload).encode(), h)


def _wuwa_first_half_end(ver: str, now: datetime, read_image, tr: "Trace", kuro_get, bili_get
                         ) -> "datetime | None":
    """The next version's first-half end: the Kuro notice when it is out, else the
    version-news poster (Kuro copy, then Bilibili). None while neither is published;
    that is the publisher's schedule, not a fault, so nothing here warns."""
    get = kuro_get or _kuro_default
    try:
        events = (get(_KURO_NEWS, {"gameId": 3, "eventType": 3, "pageSize": 100}).get("data") or {}).get("list")

        def detail_of(pid: str) -> dict:
            return ((get(_KURO_POST, {"isOnlyPublisher": 0, "postId": pid, "showOrderType": 2}).get("data") or {})
                    .get("postDetail") or {})
        hit = wuwa_first_half_notice_end(events or [], detail_of, ver, now)
    except Exception:
        log.info("库街区唤取公告取不到，下一版第一期的结束时刻改看长图", exc_info=True)
        hit = None
    if hit:
        tr.src("鸣潮", "唤取公告", hit[1], f"{ver} 第一期 {hit[0]:%Y-%m-%d %H:%M} 结束（公告原文）")
        return hit[0]
    if not read_image:
        return None
    for what, find in (("库街区", lambda: _kuro_poster(ver, now, get)), ("B 站", lambda: _bili_poster(ver, now, bili_get))):
        try:
            found = find()
        except Exception as e:
            log.info("%s版本资讯帖取不到", what, exc_info=True)
            tr.problems.append(f"鸣潮｜版本资讯｜{what}｜{type(e).__name__}: {e}")
            continue
        if not found:
            continue
        page, title, imgs = found
        for n, (url, w, h) in enumerate(imgs, 1):
            if h <= 2.5 * max(w, 1):
                continue
            try:
                lines = read_image(url)
            except Exception:
                log.info("%s版本资讯第 %d 张图读图失败", what, n, exc_info=True)
                continue
            if lines is None:
                return None
            end = parse_wuwa_poster_first_end(lines)
            if end and end > now:
                tr.src("鸣潮", "版本资讯", f"{what} {page}「{title}」第 {n} 张图 {url}",
                       f"{ver} 第一期 {end:%Y-%m-%d %H:%M} 结束（服务器时间）")
                return end
    return None


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


def record_history(state_dir, game: str, periods: "list[dict]") -> "list[str]":
    """Keep the ended periods in `banners/history.json` and say which ones changed.

    An ended period is a fixed fact, so a (version, part) whose recorded (start, end)
    is not in what is read now means one of the two reads is wrong: it is returned as a
    sentence (the caller warns) and the record is replaced, so it is said once."""
    from .config import atomic_write_text  # noqa: PLC0415
    path = Path(state_dir) / "banners" / "history.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    old = data.get(game, {})
    new: "dict[str, list]" = {}
    for p in periods:
        new.setdefault(f"{p['ver']}|{p['part']}", []).append(
            [f"{p['start']:%Y-%m-%d %H:%M}", f"{p['end']:%Y-%m-%d %H:%M}"])
    changes = []
    for k, spans in old.items():
        gone = [x for x in spans if k in new and x not in new[k]]
        if gone:
            changes.append(f"{game}往期「{k.replace('|', ' ')}」的起止变了：以前记的 {gone}，这次读到 {new[k]}")
    old.update(new)
    data[game] = old
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
    return changes


def update_wuwa_history(state_dir, now: datetime, get=None, article_get=None, budget: int = 80
                        ) -> "tuple[list[dict], list[str]]":
    """Read the ended Wuthering Waves periods the way the next one is read and record them.
    Post texts never change, so each is fetched once into `banners/ww-notices.json`
    (at most `budget` fetches a run, the site's maintenance notices first, then the newest
    notices, so the whole history fills in over a few days)."""
    from .config import atomic_write_text  # noqa: PLC0415
    get = get or _kuro_default
    article_get = article_get or (lambda u: _text(u, _UA_BROWSER))
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


def update_history(state_dir, now: datetime) -> "list[str]":
    """The history step of the daily banner run: never raises, returns what changed."""
    try:
        return update_wuwa_history(state_dir, now)[1]
    except Exception:
        log.info("往期卡池这一步没做成", exc_info=True)
        return []


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
        return _json(_KURO + path, _UA_BROWSER, body, h)

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
        notice = _json(_WW_NOTICE, _UA_BROWSER, timeout=25)
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
        articles = json.loads(_text(_WW_SITE_ARTICLES, _UA_BROWSER))
        maint = wuwa_maintenance(articles, now)
        if maint:
            tr.starts |= _stamps(maint[1]) | _stamps(maint[2])
            tr.src("鸣潮", "版本维护", _WW_SITE_ARTICLES, f"{maint[0]} 维护 {maint[1]:%Y-%m-%d %H:%M}~{maint[2]:%Y-%m-%d %H:%M}")
    except Exception:
        log.warning("鸣潮官网文章列表取不到", exc_info=True)

    # Unreadable raises (see _endfield): an empty return would read as "none".
    home = post("/wiki/core/homepage/getPage")
    pools = parse_wuwa(home, name_of)
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


# The official site's article index (what mc.kurogames.com/main/news renders): a
# plain JSON list, articleType 51 = 新闻 (PVs, combat demos), 52 = 公告.
_WW_SITE_ARTICLES = "https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/json/G152/zh/ArticleMenu.json"
_WW_DEMO = re.compile(r"共鸣者战斗演示\s*[|｜]\s*(.+?)\s*$")
_WW_PV = re.compile(r"共鸣者「([^」]+)」PV")


_WW_SITE_ARTICLE = "https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/json/G152/zh/article/{id}.json"
_WW_MAINT = re.compile(r"更新维护时间[：:\s]*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})\s*[~～-]\s*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})")


def wuwa_maintenance(articles: list, now: datetime, get=None) -> "tuple[str, datetime, datetime] | None":
    """The next version's maintenance window from the official site's
    「X版本更新维护预告」 post (published about a week ahead: 3.6's on 08-13 for
    08-20): (version label, maintenance start, maintenance end). None until it is
    posted or once the window has passed.
    """
    get = get or (lambda u: _text(u, _UA_BROWSER))
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
    a, b = datetime(g[0], g[1], g[2], g[3], g[4]), datetime(g[5], g[6], g[7], g[8], g[9])
    return (ver, a, b) if b > now else None


def collect(now: datetime, *, skland_token: str = "",
            cred=None, sk_get=None, failed: "list[str] | None" = None,
            notes: "dict[str, str] | None" = None, trace: "Trace | None" = None,
            leads: "dict[str, str] | None" = None, read_image=None
            ) -> "tuple[list[Banner], dict[str, tuple[datetime | None, str]]]":
    """Pull all three games. If one cannot be fetched, that line is missing and the
    others are unaffected.

    Only Endfield needs `skland_token` (or the caller supplies `cred`/`sk_get`
    directly, which is how the tests inject it). Arknights uses PRTS and Wuthering
    Waves uses Kuro BBS; neither needs a token.
    The request-signing chain lives in skland.py and is not rebuilt here.

    `notes`, when given, is filled with other published facts for a game whose
    next banner is not announced (Wuthering Waves' teased characters and
    maintenance window) - never a date that was worked out.
    `leads`, when given, is filled with an official hint that stands in for the
    unannounced next banner (Arknights: the newsletter's event with new operators).
    `failed`, when given, is filled with the games whose source could not be read.
    Without it a missing section of the report looked exactly like "no banner
    running" - and he reads this section every day to decide when to save stones.
    """
    failed = failed if failed is not None else []
    if sk_get is None and skland_token:
        try:
            from . import skland  # noqa: PLC0415 - needed only here
            cred = skland.login(skland_token)
            def sk_get(path):
                return skland.get(cred, path)
        except Exception:
            log.warning("森空岛登录失败，终末地卡池这一行不出", exc_info=True)
            sk_get = None
            failed.append("终末地（森空岛登录失败）")
    rows: list[Banner] = []
    nxt: "dict[str, tuple[datetime | None, str]]" = {}
    try:
        ak, ak_next = _arknights(now, trace, leads)
        rows += ak
        if ak_next:
            nxt["明日方舟"] = ak_next      # _arknights already returns (time, who)
    except Exception:
        log.warning("方舟卡池整段失败", exc_info=True)
        failed.append("明日方舟")
    if sk_get is not None:
        try:
            ef, ef_next = _endfield(cred, sk_get, now, trace)
            rows += ef
            if ef_next:
                nxt["终末地"] = ef_next
        except Exception:
            log.warning("终末地卡池整段失败", exc_info=True)
            failed.append("终末地")
    try:
        ww, ww_next = _wuwa(now, notes, trace, read_image)
        rows += ww
        if ww_next:
            nxt["鸣潮"] = ww_next
    except Exception:
        log.warning("鸣潮卡池整段失败", exc_info=True)
        failed.append("鸣潮")
    return rows, nxt


def save_trace(state_dir, now: datetime, text: str, tr: "Trace", notifier=None) -> None:
    """Keep the section with its provenance next to the state, one file per day
    (`banners/YYYY-MM-DD.json`), so any line in a report can be traced to the
    URL and field it came from without re-fetching anything.

    Then the machine checks of the banner section are judged on what was just
    built (machinecheck event "banners": #2 #3 #8 #9 #58). `notifier` is the
    relay's when the caller has it; without it a check that did not hold goes
    to the group through errwatch with its own title and evidence.
    """
    try:
        d = Path(state_dir) / "banners"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{now:%Y-%m-%d}.json").write_text(json.dumps({
            "when": now.strftime("%Y-%m-%d %H:%M:%S"), "text": text, "sources": tr.sources,
            "checks": tr.checks, "withheld": tr.withheld, "problems": tr.problems,
            "starts": sorted(tr.starts), "ends": sorted(tr.ends),
            "next": {g: [w.strftime("%Y-%m-%d %H:%M") if w else None, who]
                     for g, (w, who) in tr.nexts.items()},
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        log.warning("卡池来源记录写不进去", exc_info=True)
    try:
        from .machinechecks import phone_banners  # noqa: PLC0415 - imports this module
        phone_banners.fire(state_dir, "banners", {"trace": tr, "text": text, "now": now}, notifier)
    except Exception:
        log.exception("卡池那一段的上机核对没能做")


def section(now: datetime, **kw) -> str:
    """The section at the end of the daily report."""
    notes: dict[str, str] = {}
    tr = Trace.new()
    failed: list[str] = []
    leads: dict[str, str] = {}
    rows, nxt = collect(now, notes=notes, trace=tr, failed=failed, leads=leads, **kw)
    return render(rows, now, nxt, notes, tr, failed, leads)


def opening_tomorrow(now: datetime,
                     nxt: "dict[str, tuple[datetime | None, str]]"
                     ) -> "list[tuple[str, datetime, str]]":
    """New banners opening tomorrow. Set by the user 2026-08-31: only these get sent
    to the WeChat group.

    The comparison is on the **date**, not "within 24 hours" -- the daily report goes
    out in the evening, and at 21:30 "within 24 hours" would sweep in a banner opening
    at six the morning after tomorrow, which is not tomorrow.

    An entry with no character name is not a new banner: it is the running banner's
    end with the next debut not announced yet (Endfield once both halves of a version
    are done), or a PRTS row that is not a debut. The daily report still says so;
    the group does not get it. 2026-09-29 the group was told a new Endfield banner
    opens 09-30 11:59, with no name: that was the running banner ending. The user
    (10:53) asked why the name was missing and called it a rerun reported as new.
    """
    day = (now + timedelta(days=1)).date()
    # No published time (None) means nothing to announce.
    return sorted(((g, w, who) for g, (w, who) in nxt.items()
                   if w is not None and w.date() == day and who), key=lambda x: x[1])


def group_notice(due: "list[tuple[str, datetime, str]]") -> "tuple[str, str]":
    """The message sent to the group. Two empty strings when there is nothing."""
    if not due:
        return "", ""
    lines = []
    for game, when, who in due:
        stamp = f"{when:%m-%d}" if (when.hour, when.minute) == (0, 0) \
            else f"{when:%m-%d %H:%M}"
        lines.append(f"· {game}　{stamp} 开" + (f"　{who}" if who else ""))
    what = "、".join(g for g, _, _ in due)
    return f"🎴 明天开新卡池：{what}", "\n".join(lines)
