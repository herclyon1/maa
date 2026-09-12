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
| Arknights preview | the Yituliu frontend repo `gachaScheduleOptions.js` (hand-maintained) | the next banner's name and rough start date |

**Why this must use official sources and not Fandom**: measured 2026-08-30, at the
same moment Fandom (global servers) said 「False Promise for Tomorrow / Denia」 while
Kuro BBS (CN servers) said 「予明日以谎言 / 达妮娅」. Neither the names nor the
characters line up, and the servers are not on the same schedule. Using Fandom would
report the wrong thing.

## When the next banner starts

**Wuthering Waves is the only one where "who is next" can be obtained**: the
「N.N版本内容说明」 bulletin the publisher posts on version-update day lists every
brand-new 5-star for both halves of the version together with its banner name -- an
official announcement three weeks ahead. That section contains no reruns by
construction, which is exactly the criterion we want.

For Arknights and Endfield the characters are not available, only **when the
changeover happens**:

* Endfield: the next banner starts the moment the current one ends (back to back)
* Arknights: `gacha_table.json` ships with the client update and **already contains
  future banners**

So outside Wuthering Waves, "the next banner" is inferred, not announced -- the
rendering must say so, and must never read as though the publisher had announced it.

If nothing can be fetched this returns empty: one line missing from the report beats
having no report.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
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
    start: datetime
    end: datetime


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
    * the date gate in `render` - a preview line may only carry a date that a
      source assigned to a *start* (`starts`), or an end when the line says 结束,
      or a rule/prediction when it is labelled as such. A line that fails is
      withheld and logged instead of sent.
    """

    sources: list[str]
    starts: set
    ends: set
    rule: set
    predicted: set
    checks: list[str]
    withheld: list[str]

    @classmethod
    def new(cls) -> "Trace":
        return cls([], set(), set(), set(), set(), [], [])

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


# ── Version preview streams ──
# The user, 2026-09-03: the preview stream time for each Wuthering Waves and Endfield
# version follows a **fixed rule**, it is not an approximation. As recorded:
#   Wuthering Waves 3.6: version updates 08-20 (Thu), preview stream 08-07 (Fri)
#     19:00 -> 13 days before the version
#   Endfield 「雪凇幽梦」: version updates 09-02 (Wed), preview stream 08-21 (Fri)
#     19:00 -> 12 days before the version
# Once the publisher posts a preview announcement, use the time from it; until then
# compute from this rule and label it as derived from the rule.
# Arknights version timing is not fixed; its next banner comes from Yituliu (already
# carried in next_starts).
_PREVIEW_RULE = {"鸣潮": (13, 19, 0), "终末地": (12, 19, 0)}   # (days before the version, hour, minute)


def previews(now: datetime, rows: list[Banner], version_end: "dict[str, datetime]",
             official: "dict[str, tuple[datetime, str]] | None" = None,
             trace: "Trace | None" = None) -> "dict[str, str]":
    """{game: the body of the preview line}.

    When official[game] = (preview time, title) is present it is used instead.
    """
    out: dict[str, str] = {}
    for game, (days, hh, mm) in _PREVIEW_RULE.items():
        if official and game in official:
            when, title = official[game]
            if trace is not None:
                trace.starts |= _stamps(when)
            out[game] = f"{when:%m-%d %H:%M} {title}"
            continue
        end = version_end.get(game)
        if not end:
            continue
        when = (end - timedelta(days=days)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if trace is not None:
            trace.rule |= _stamps(when) | _stamps(end)
        if when <= now:
            out[game] = f"{when:%m-%d %H:%M} 已播（版本 {end:%m-%d} 更新）"
        else:
            out[game] = f"{when:%m-%d %H:%M}（版本 {end:%m-%d} 更新前 {days} 天，按规律）"
    return out


_DATE_TOKEN = re.compile(r"\d\d-\d\d(?: \d\d:\d\d)?")


def gate_preview(line: str, trace: "Trace") -> str:
    """Why a preview line must not go out, or '' when it may.

    Every date in the line has to be one a source assigned to a *start* (an
    official opening time or a maintenance end), or an end when the line says
    结束, or a rule-derived / predicted date when the line is labelled 按规律 /
    预测. 「09-18 03:59 之后开」 - an end dressed up as a start - fails here.
    """
    for tok in _DATE_TOKEN.findall(line):
        # a bare MM-DD is also satisfied by an MM-DD HH:MM stamp of the same day
        ok = (tok in trace.starts
              or ("结束" in line and tok in trace.ends)
              or ("按规律" in line and tok in trace.rule)
              or ("预测" in line and tok in trace.predicted))
        if not ok:
            return f"日期 {tok} 没有来源把它当作开始时刻"
    return ""


def render(banners: list[Banner], now: datetime,
           next_starts: "dict[str, tuple[datetime, str]] | None" = None,
           preview: "dict[str, str] | None" = None,
           notes: "dict[str, str] | None" = None,
           trace: "Trace | None" = None) -> str:
    """The section at the end of the daily report, one block per game, at most two
    lines each:

        明日方舟
        · 当期　「池名」角色　剩 3 天 4 小时（09-05 03:59 结束）
        · 预告　09-04 开（还有 1 天）　是谁

    The user, 2026-09-02: 「要有当期新 UP 角色的卡池倒计时（如果没有 UP 就不显示），
    而且得要有卡池预告」, and the three games must look the same. So:
    · no UP banner running -> omit the "current" line; no preview -> omit the
      "preview" line; neither -> the game's whole block is absent.
    · `next_starts[game] = (start time, who)`. An empty `who` means the publisher
      only moved the date without announcing the character -- in that case the wording
      must be hedged, never phrased as an official announcement.
    """
    live: dict[str, list[Banner]] = {}
    for b in sorted((x for x in banners if x.start <= now <= x.end), key=lambda x: x.end):
        live.setdefault(b.game, []).append(b)
    nxt = {g: v for g, v in (next_starts or {}).items() if v[0] > now}
    pv = preview or {}
    nt = notes or {}
    games = [g for g in _GAME_ORDER if g in live or g in nxt or g in pv or g in nt]
    games += sorted(g for g in set(live) | set(nxt) | set(pv) | set(nt) if g not in _GAME_ORDER)
    blocks: list[str] = []
    for game in games:
        lines = [game]
        for b in live.get(game, []):
            d = b.end - now
            lines.append(f"· 当期　「{b.name}」{' · '.join(b.chars)}"
                         f"　剩 {d.days} 天 {d.seconds // 3600} 小时（{_stamp(b.end)} 结束）")
        pre = ""
        if game in nt:
            # Nothing announced: the producer wrote what *is* known (dates only
            # where a date exists - a version boundary; never for Arknights).
            pre = f"· 预告　{nt[game]}"
        elif game in nxt:
            when, who = nxt[game]
            d = when - now
            head = ("约 " if not who else "") + f"{_stamp(when)} 开（还有 {d.days} 天）"
            pre = f"· 预告　{head}　{who or 'UP 是谁官方未公布'}"
        if pre and trace is not None:
            if why := gate_preview(pre, trace):
                log.error("卡池预告没通过来源核对，扣下：%s ← %s", pre, why)
                trace.withheld.append(f"{pre} ← {why}")
                pre = "· 预告　⚠️ 这一行没通过来源核对，已扣下（原文在日志）"
        if pre:
            lines.append(pre)
        if game in pv:
            lines.append(f"· 前瞻　{pv[game]}")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    out = "🎴 卡池\n" + "\n".join(blocks)
    if trace is not None and trace.checks:
        out += "\n核对　" + "；".join(trace.checks)
    return out


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

# Measured on the game machine 2026-08-31: raw.githubusercontent.com is reachable,
# but takes **33 seconds** -- past the timeout it simply fails, which is why the
# Arknights and Endfield previews came and went. The same file over jsDelivr takes
# only 2.8-4.6 seconds. So the mirrors are ordered by measured speed, with raw last as
# a fallback. gitmirror and ghfast.top were completely unreachable at the time; do not
# add them back.
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


# The next banner's schedule: the publisher does not announce it, and PRTS only
# records banners that have already run. Someone hand-maintains a future schedule in
# the Yituliu frontend repo; `accuracyFlag: false` marks an entry as a prediction
# rather than an official announcement.
_AK_SCHEDULE = gh_raw("Arknights-yituliu", "frontend-v2-plus", "main",
                      "src/utils/gachaScheduleOptions.js")
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
    """Try each in turn and return the first that works.

    Only when all of them fail is the last exception raised.
    """
    err: Exception = RuntimeError("没有可用地址")
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
        if (x.hour, x.minute) == (0, 0) or (y.hour, y.minute) == (0, 0):
            same = x.date() == y.date()
        else:
            # to the minute: Skland ends at 11:59:59, the bulletin writes 11:59
            same = x.replace(second=0, microsecond=0) == y.replace(second=0, microsecond=0)
        if not same:
            diffs.append(f"{label} {a_name} {x:%m-%d %H:%M} / {b_name} {y:%m-%d %H:%M}")
    if diffs:
        return f"{game}：{a_name} 和 {b_name} 对不上 ✗（" + "；".join(diffs) + "）"
    return f"{game}：{a_name}={b_name} ✓"


def announce_lead(posts: "list[tuple[datetime, str, datetime]]") -> str:
    """"Announced about a week ahead", backed by the actual lead of the recent
    posts (how many days before opening each was published); '' without data.
    Measured 2026-09-12: 车辙与风的归所 posted 07-25 for 08-01 (7 days), 石白深蓝之夜
    posted 08-29 for 09-04 (6 days).
    """
    leads = [(start.date() - posted.date()).days for start, _, posted, _e, _c in posts]
    if not leads:
        return ""
    return "官方惯例开池前约一周公告（上" + ("两" if len(leads) == 2 else str(len(leads))) + "池分别提前 " \
        + "、".join(f"{d} 天" for d in leads) + "）"


def _arknights(now: datetime, notes: "dict[str, str] | None" = None,
               trace: "Trace | None" = None
               ) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Both PRTS pages combined to decide debuts.

    PRTS does not give the next banner's time, so None is returned and the caller
    fills it in.
    """
    tr = trace if trace is not None else Trace.new()
    rows: list[Banner] = []
    for page in _AK_PAGES:
        url = _PRTS + urllib.parse.quote(page)
        try:
            rows += parse_arknights(
                _json(url, _UA_PLAIN)["parse"]["wikitext"]["*"])
        except Exception:
            log.warning("PRTS 取不到 %s", page, exc_info=True)
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
    if when := min((b.start for b in rows if b.start > now), default=None):
        tr.starts |= _stamps(when)
        return debut, (when, "")      # PRTS already lists it: the time is accurate, the character unknown
    # Nothing announced. Yituliu's table only lists *limited* banners (it feeds a
    # pull-saving calculator), so its next entry is not "the next banner" - on
    # 2026-09-12 it put the 11-01 anniversary banner as the preview while the banner
    # after 09-18 was simply not announced yet. Say so, and carry the limited-banner
    # projection as a far-off note, labelled as the prediction it is.
    # A new Arknights banner does not open when the current one ends (the gaps
    # between debut banners in the PRTS table run 22-39 days), so no date at all
    # is given here - not even the current banner's end (2026-09-12 the line said
    # "opens after 09-18 03:59, 5 days to go", and that was invented).
    far = ""
    try:
        sched = parse_ak_schedule(_first(_AK_SCHEDULE, _UA_BROWSER))
        if nxt := next(((n, d, ok) for n, d, ok in sched if d > now), None):
            name, day, official = nxt
            far = f"；远期 {day:%m-%d} {name}" + ("" if official else "（一图流预测，未官宣）")
            tr.predicted |= _stamps(day)
            tr.src("明日方舟", "远期", _AK_SCHEDULE[0], f"{name} {day:%Y-%m-%d} accuracyFlag={official}")
    except Exception:
        log.warning("一图流方舟排期取不到", exc_info=True)
    lead = announce_lead(posts)
    if notes is not None:
        notes["明日方舟"] = "下一池官方还没公告" + (f"，{lead}" if lead else "") + far
    return debut, None


def _endfield(cred, sk_get, now: datetime, notes: "dict[str, str] | None" = None,
              trace: "Trace | None" = None
              ) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Running banners come from Skland (authoritative on timing); debuts and
    previews come from the official version bulletin.
    """
    tr = trace if trace is not None else Trace.new()
    try:
        pools = (sk_get("/web/v1/wiki/char-pool")["data"] or {}).get("list") or []
    except Exception:
        log.warning("森空岛卡池取不到", exc_info=True)
        return [], None

    def name_of(gid: str) -> str:
        try:
            item = ((sk_get(f"/web/v1/wiki/item/info?id={gid}")["data"] or {})
                    .get("item") or {})
            return str(item.get("name") or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    live = parse_endfield(pools, name_of)
    end = min((b.end for b in live), default=None)

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
    if not end or end <= now:
        return got, None

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
        tr.starts |= _stamps(end)
        tr.src("终末地", "预告", _EF_BULLETIN, "本版下半：" + "、".join(f"{w}「{p}」" for w, p in rest) + f"，当期 {end:%Y-%m-%d %H:%M} 结束即开")
        return got, (end, "、".join(f"{w}「{p}」" if p else w for w, p in rest))

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
    if notes is not None:
        notes["终末地"] = f"当期 {end:%m-%d %H:%M} 结束（还有 {(end - now).days} 天）　下一版新干员官方还没公告"
    return got, (end, "")


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
_WW_NOTICE_SPAN = re.compile(r"活动时间[✦\s]*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})\s*[~～-]\s*(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})")
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
        g = [int(x) for x in sp.groups()]
        out.append(Banner("鸣潮", tm.group(1).strip(), (up.group(1).strip(),),
                          datetime(g[0], g[1], g[2], g[3], g[4]),
                          datetime(g[5], g[6], g[7], g[8], g[9], 59)))
    return out


def _wuwa(now: datetime, notes: "dict[str, str] | None" = None,
          trace: "Trace | None" = None
          ) -> "tuple[list[Banner], tuple[datetime, str] | None]":
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

    try:
        home = post("/wiki/core/homepage/getPage")
    except Exception:
        log.warning("库街区首页取不到", exc_info=True)
        return [], None
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
                tr.src("鸣潮", "游戏公告", _WW_NOTICE, f"{other.name} {'、'.join(other.chars)} {other.start:%Y-%m-%d %H:%M}~{other.end:%Y-%m-%d %H:%M}")
            tr.checks.append(crosscheck("鸣潮", "库街区", b, "游戏公告", other) if notice_ok
                             else "鸣潮：游戏公告取不到，只有库街区一个来源 ✗")

    if not end or end <= now:
        return got, None
    live = {c for b in pools for c in b.chars}
    rest = upcoming(debut, live)
    if rest:
        who = "、".join(f"{w}「{p}」" if p else w for w, p in rest)
        tr.starts |= _stamps(end)
        tr.src("鸣潮", "预告", _WW_NOTICE, f"本版下半：{who}，当期 {end:%Y-%m-%d %H:%M} 结束即开")
        return got, (end, who)
    # Both halves are done: the next banner belongs to the next version, whose
    # bulletin is not out yet. The wiki does mark the characters the publisher has
    # previewed (the teaser badge), so name them; the order and banner names are
    # only in the version bulletin.
    teased: list[str] = []
    try:
        page = post("/wiki/core/catalogue/item/getPage",
                    {"catalogueId": _WW_CHAR_CATALOGUE, "page": 1, "limit": 100})
        teased = wuwa_teased((((page.get("data") or {}).get("results") or {}).get("records")) or [], now)
        tr.src("鸣潮", "预告角色", _KURO + f"/wiki/core/catalogue/item/getPage catalogueId={_WW_CHAR_CATALOGUE}", "预告角标：" + ("、".join(teased) or "无"))
    except Exception:
        log.warning("库街区角色图鉴取不到，预告角色这一项不出", exc_info=True)
    shown = ""
    maint = None
    try:
        articles = json.loads(_text(_WW_SITE_ARTICLES, _UA_BROWSER))
        maint = wuwa_maintenance(articles, now)
        if maint:
            tr.starts |= _stamps(maint[2])
            tr.src("鸣潮", "版本维护", _WW_SITE_ARTICLES, f"{maint[0]} 维护 {maint[1]:%Y-%m-%d %H:%M}~{maint[2]:%Y-%m-%d %H:%M}")
        if teased:
            shown = wuwa_demo_note(articles, teased, now)
            if shown:
                tr.src("鸣潮", "战斗演示", _WW_SITE_ARTICLES, shown)
    except Exception:
        log.warning("鸣潮官网文章列表取不到", exc_info=True)
    if notes is not None:
        if maint:
            head = f"{maint[0]} 版本 {maint[2]:%m-%d %H:%M} 维护结束后开（还有 {(maint[2] - now).days} 天）　"
        else:
            head = f"当期 {end:%m-%d %H:%M} 结束（还有 {(end - now).days} 天）　"
        if teased:
            notes["鸣潮"] = head + "下一版新角色官方已预告：" + "、".join(teased) + (f"；{shown}" if shown else "")
        else:
            notes["鸣潮"] = head + "下一版新角色官方还没公告"
    return got, (end, "")


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


def wuwa_demo_note(articles: list, teased: list[str], now: datetime) -> str:
    """Which previewed character the official site has already shown a combat demo
    or PV for, and when - the first sign of who opens first.

    Facts from the article index, 2026-09-12: 秧秧·玄翎 demo 07-06 -> banner 07-10
    (3.5 first half), 穗穗 demo 07-26 -> 08-13 (second half); 清宵 demo 08-17 ->
    08-20 (3.6 first half), 景燃 demo 09-06 -> 09-10 (second half). The demo order
    matched the banner order both times; the lead ranged from 3 to 18 days, so no
    "opens within N days" is derived from it - only the fact is reported.
    """
    seen: dict[str, datetime] = {}
    for a in articles or []:
        title = str(a.get("articleTitle") or "")
        m = _WW_DEMO.search(title) or _WW_PV.search(title)
        if not m:
            continue
        name = m.group(1).strip()
        try:
            at = datetime.strptime(str(a.get("startTime") or a.get("createTime"))[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        if at <= now and name in teased and (name not in seen or at < seen[name]):
            seen[name] = at
    if not seen:
        return ""
    first = sorted(seen.items(), key=lambda kv: kv[1])
    return "官网已发" + "、".join(f"「{n}」的战斗演示（{t:%m-%d}）" for n, t in first)


def collect(now: datetime, *, skland_token: str = "",
            cred=None, sk_get=None, failed: "list[str] | None" = None,
            notes: "dict[str, str] | None" = None, trace: "Trace | None" = None
            ) -> "tuple[list[Banner], dict[str, tuple[datetime, str]]]":
    """Pull all three games. If one cannot be fetched, that line is missing and the
    others are unaffected.

    Only Endfield needs `skland_token` (or the caller supplies `cred`/`sk_get`
    directly, which is how the tests inject it). Arknights uses PRTS and Wuthering
    Waves uses Kuro BBS; neither needs a token.
    The request-signing chain lives in skland.py and is not rebuilt here.

    `notes`, when given, is filled with the preview line for a game whose next
    banner is not announced (what is known instead of an invented date).
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
    nxt: "dict[str, tuple[datetime, str]]" = {}
    try:
        ak, ak_next = _arknights(now, notes, trace)
        rows += ak
        if ak_next:
            nxt["明日方舟"] = ak_next      # _arknights already returns (time, who)
    except Exception:
        log.warning("方舟卡池整段失败", exc_info=True)
        failed.append("明日方舟")
    if sk_get is not None:
        try:
            ef, ef_next = _endfield(cred, sk_get, now, notes, trace)
            rows += ef
            if ef_next and ef_next[0] > now:
                nxt["终末地"] = ef_next
        except Exception:
            log.warning("终末地卡池整段失败", exc_info=True)
            failed.append("终末地")
    try:
        ww, ww_next = _wuwa(now, notes, trace)
        rows += ww
        if ww_next and ww_next[0] > now:
            nxt["鸣潮"] = ww_next
    except Exception:
        log.warning("鸣潮卡池整段失败", exc_info=True)
        failed.append("鸣潮")
    return rows, nxt


def version_ends(now: datetime, rows: list[Banner]) -> "dict[str, datetime]":
    """When each game's current version ends (= when the next one updates).

    Endfield takes the end of the current banner; Wuthering Waves takes the start of
    the maintenance window in the bulletin + 42 days (every 3.x version runs six
    weeks). Games that cannot be determined are simply absent.
    """
    out: dict[str, datetime] = {}
    ef = [b.end for b in rows if b.game == "终末地" and b.start <= now]
    if ef:
        out["终末地"] = max(ef)
    # The banners of a version all end on update day, so the running banner's end is
    # the version end. "+42 days" was a guess: 3.6 ran 08-20 to 09-29 (40 days) and
    # the guess put the update on 10-01 (2026-09-12).
    ww = [b.end for b in rows if b.game == "鸣潮" and b.start <= now <= b.end]
    if ww:
        out["鸣潮"] = max(ww)
    else:
        try:
            from . import maintenance  # noqa: PLC0415
            w = maintenance.wuwa_window(now)
            if w:
                out["鸣潮"] = w[0].replace(tzinfo=None) + timedelta(days=42)
        except Exception:  # noqa: BLE001
            pass
    return out


def save_trace(state_dir, now: datetime, text: str, tr: "Trace") -> None:
    """Keep the section with its provenance next to the state, one file per day
    (`banners/YYYY-MM-DD.json`), so any line in a report can be traced to the
    URL and field it came from without re-fetching anything.
    """
    try:
        d = Path(state_dir) / "banners"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{now:%Y-%m-%d}.json").write_text(json.dumps({
            "when": now.strftime("%Y-%m-%d %H:%M:%S"), "text": text, "sources": tr.sources,
            "checks": tr.checks, "withheld": tr.withheld,
            "starts": sorted(tr.starts), "ends": sorted(tr.ends),
            "rule": sorted(tr.rule), "predicted": sorted(tr.predicted),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        log.warning("卡池来源记录写不进去", exc_info=True)


def section(now: datetime, **kw) -> str:
    """The section at the end of the daily report."""
    notes: dict[str, str] = {}
    tr = Trace.new()
    rows, nxt = collect(now, notes=notes, trace=tr, **kw)
    return render(rows, now, nxt, previews(now, rows, version_ends(now, rows), trace=tr), notes, tr)


def opening_tomorrow(now: datetime,
                     nxt: "dict[str, tuple[datetime, str]]"
                     ) -> "list[tuple[str, datetime, str]]":
    """New banners opening tomorrow. Set by the user 2026-08-31: only these get sent
    to the WeChat group.

    The comparison is on the **date**, not "within 24 hours" -- the daily report goes
    out in the evening, and at 21:30 "within 24 hours" would sweep in a banner opening
    at six the morning after tomorrow, which is not tomorrow.
    """
    day = (now + timedelta(days=1)).date()
    return sorted(((g, w, who) for g, (w, who) in nxt.items()
                   if w.date() == day), key=lambda x: x[1])


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
