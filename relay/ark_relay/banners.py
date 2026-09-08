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
            a = datetime.fromtimestamp(int(p["poolStartAtTs"]))
            b = datetime.fromtimestamp(int(p["poolEndAtTs"]))
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
    hits = list(_EF_ANY_POOL.finditer(txt))
    out: list[tuple[str, str, "datetime | None", bool]] = []
    seen: set[tuple[str, str]] = set()
    for k, m in enumerate(hits):
        tail = txt[m.end():hits[k + 1].start() if k + 1 < len(hits) else len(txt)]
        up = _EF_UP.search(tail)
        if not up:
            continue
        name, pool = up.group(1), m.group(1)
        if (name, pool) in seen:
            continue
        seen.add((name, pool))
        when = None
        if t := _EF_OPEN.search(tail):
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
            who = name_of(str(eid)) if eid else ""
            if not who:
                continue
            out.append(Banner("鸣潮", str(tab.get("name") or ""), (who,), a, b))
    out.sort(key=lambda x: x.end)
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
             official: "dict[str, tuple[datetime, str]] | None" = None) -> "dict[str, str]":
    """{game: the body of the preview line}.

    When official[game] = (preview time, title) is present it is used instead.
    """
    out: dict[str, str] = {}
    for game, (days, hh, mm) in _PREVIEW_RULE.items():
        if official and game in official:
            when, title = official[game]
            out[game] = f"{when:%m-%d %H:%M} {title}"
            continue
        end = version_end.get(game)
        if not end:
            continue
        when = (end - timedelta(days=days)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if when <= now:
            out[game] = f"{when:%m-%d %H:%M} 已播（版本 {end:%m-%d} 更新）"
        else:
            out[game] = f"{when:%m-%d %H:%M}（版本 {end:%m-%d} 更新前 {days} 天，按规律）"
    return out


def render(banners: list[Banner], now: datetime,
           next_starts: "dict[str, tuple[datetime, str]] | None" = None,
           preview: "dict[str, str] | None" = None) -> str:
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
    games = [g for g in _GAME_ORDER if g in live or g in nxt or g in pv]
    games += sorted(g for g in set(live) | set(nxt) | set(pv) if g not in _GAME_ORDER)
    blocks: list[str] = []
    for game in games:
        lines = [game]
        for b in live.get(game, []):
            d = b.end - now
            lines.append(f"· 当期　「{b.name}」{' · '.join(b.chars)}"
                         f"　剩 {d.days} 天 {d.seconds // 3600} 小时（{_stamp(b.end)} 结束）")
        if game in nxt:
            when, who = nxt[game]
            d = when - now
            head = ("约 " if not who else "") + f"{_stamp(when)} 开（还有 {d.days} 天）"
            lines.append(f"· 预告　{head}　{who or 'UP 是谁官方未公布'}")
        if game in pv:
            lines.append(f"· 前瞻　{pv[game]}")
        blocks.append("\n".join(lines))
    return "🎴 卡池\n" + "\n".join(blocks) if blocks else ""


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
# The next banner across a version boundary exists only in this hand-maintained file.
# Its times are not trusted (see docs/BANNER-SOURCES.md); it is used only to get who
# the next character is.
_EF_SCHEDULE = gh_raw("Arknights-yituliu", "ef-frontend-v1", "main",
                      "custom/core/gacha/data/pool_info_table.json")


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
    get = get or (lambda u: _text(u, _UA_BROWSER))
    page = get(_AK_NEWS)
    seen = set()
    for cid, title, _ts in _AK_NEWS_ITEM.findall(page):
        if cid in seen or "寻访" not in title or "开启" not in title:
            continue
        seen.add(cid)
        body = _ak_article_text(get(f"{_AK_NEWS}/{cid}"))
        m6 = _AK_SIX_LINE.search(body)
        six = [x.strip() for x in re.split(r"[/、]", m6.group(1))] if m6 else []
        sp = _AK_SPAN.search(body)
        if not six or not sp:
            continue
        mo, d, hh, mm = (int(x) for x in sp.groups()[:4])
        year = now.year + (1 if mo < now.month - 6 else 0)
        start = datetime(year, mo, d, hh, mm)
        pool = re.search(r"【([^】]+)】", title)
        who = "、".join(x for x in six if x) + (f"「{pool.group(1)}」" if pool else "")
        return (start, who) if start > now else None
    return None


def _arknights(now: datetime) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Both PRTS pages combined to decide debuts.

    PRTS does not give the next banner's time, so None is returned and the caller
    fills it in.
    """
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
    # The official site's 「寻访即将开启」 post is the most accurate: it has both the
    # names and the time. Use it whenever it exists.
    try:
        if official := arknights_next_from_news(now):
            return debut, official
    except Exception:
        log.warning("方舟官网寻访公告取不到", exc_info=True)
    if when := min((b.start for b in rows if b.start > now), default=None):
        return debut, (when, "")      # PRTS already lists it: the time is accurate, the character unknown
    try:
        sched = parse_ak_schedule(_first(_AK_SCHEDULE, _UA_BROWSER))
    except Exception:
        log.warning("一图流方舟排期取不到", exc_info=True)
        return debut, None
    nxt = next(((n, d, ok) for n, d, ok in sched if d > now), None)
    if not nxt:
        return debut, None
    name, day, official = nxt
    return debut, (day, name if official else f"{name}（排期是预测，未官宣）")


def _endfield(cred, sk_get, now: datetime
              ) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Running banners come from Skland (authoritative on timing); debuts and
    previews come from the official version bulletin.
    """
    try:
        pools = (sk_get("/web/v1/wiki/char-pool")["data"] or {}).get("list") or []
    except Exception:
        log.warning("森空岛卡池取不到", exc_info=True)
        return [], None

    def name_of(gid: str) -> str:
        try:
            item = ((sk_get(f"/web/v1/wiki/item/info?id={gid}")["data"] or {})
                    .get("item") or {})
            return item.get("name") or ""
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
    if not end or end <= now:
        return got, None

    # Prefer the official bulletin for the next banner: the one whose opening time is
    # in the future (reruns are reported too, labelled as such)
    on = {c for b in live for c in b.chars}
    try:
        pools = endfield_pools_from_notice(html) if notice_ok else []
    except Exception:  # noqa: BLE001
        pools = []
    future = [(n, p, w, d) for n, p, w, d in pools if w and w > now and n not in on]
    if future:
        n, p, w, d = min(future, key=lambda x: x[2])
        return got, (w, f"{n}「{p}」" + ("" if d else "（复刻）"))
    rest = upcoming(debut, on)
    if rest:
        return got, (end, "、".join(f"{w}「{p}」" if p else w for w, p in rest))

    # Both halves of this version have finished; only Yituliu's hand-maintained table
    # covers the next version
    try:
        table = json.loads(_first(_EF_SCHEDULE, _UA_BROWSER))
    except Exception:
        log.warning("一图流终末地排期取不到（几条镜像都不通）", exc_info=True)
        return got, (end, "")
    seen = {b.name for b in live} | {p for _, p in debut}
    nxt = next((r for r in (table if isinstance(table, list) else [])
                if str(r.get("poolName") or "") not in seen
                and _ef_after(r, now)), None)
    if not nxt:
        return got, (end, "")
    who = str(nxt.get("character") or "") or str(nxt.get("poolName") or "")
    pool = str(nxt.get("poolName") or "")
    label = f"{who}「{pool}」" if pool and pool != who else who
    return got, (end, f"{label}（排期是别人手工维护的，未官宣）")


def _ef_after(row: dict, now: datetime) -> bool:
    try:
        return datetime.strptime(str(row.get("poolStart") or ""),
                                 "%Y/%m/%d %H:%M:%S") > now
    except (ValueError, TypeError):
        return False


# This hash is a channel constant and does not change with the version; if it ever
# does stop working, read metadata.source_url from data/ww/game/notice.json in
# 555me/game-CDN-List.
_WW_NOTICE = ("https://aki-gm-resources-back.aki-game.com/gamenotice/G152/"
              "76402e5b20be2c39f095a152090afddc/zh-Hans.json")
_WW_HDR = {"wiki_type": "9", "source": "h5",
           "referer": "https://wiki.kurobbs.com/"}


def _wuwa(now: datetime) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """Current banners come from the wiki homepage, the next one from the official
    bulletin. Neither needs a token.
    """
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
                cache[eid] = str(d.get("name") or "")
            except Exception:
                log.warning("库街区条目 %s 查不到名字", eid, exc_info=True)
                cache[eid] = ""
        return cache[eid]

    # Fetch the bulletin first: its 「全新角色」 section is the only authoritative basis
    # for telling a debut from a rerun. getPage gives only the banners and says nothing
    # about who is new; of the two banners in the first half of 3.6, 达妮娅 was a rerun.
    debut: "list[tuple[str, str]]" = []
    notice_ok = True
    try:
        notice = _json(_WW_NOTICE, _UA_BROWSER, timeout=25)
        body = newest_version([(str(n.get("tabTitle") or ""),
                                str(n.get("content") or ""))
                               for n in (notice.get("game") or [])
                               if "版本内容说明" in str(n.get("tabTitle") or "")])
        debut = parse_wuwa_preview(body)
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

    if not end or end <= now:
        return got, None
    live = {c for b in pools for c in b.chars}
    rest = upcoming(debut, live)
    if not rest:
        return got, (end, "")
    who = "、".join(f"{w}「{p}」" if p else w for w, p in rest)
    return got, (end, who)


def collect(now: datetime, *, skland_token: str = "",
            cred=None, sk_get=None
            ) -> "tuple[list[Banner], dict[str, tuple[datetime, str]]]":
    """Pull all three games. If one cannot be fetched, that line is missing and the
    others are unaffected.

    Only Endfield needs `skland_token` (or the caller supplies `cred`/`sk_get`
    directly, which is how the tests inject it). Arknights uses PRTS and Wuthering
    Waves uses Kuro BBS; neither needs a token.
    The request-signing chain lives in skland.py and is not rebuilt here.
    """
    if sk_get is None and skland_token:
        try:
            from . import skland  # noqa: PLC0415 - needed only here
            cred = skland.login(skland_token)
            def sk_get(path):
                return skland.get(cred, path)
        except Exception:
            log.warning("森空岛登录失败，终末地卡池这一行不出", exc_info=True)
            sk_get = None
    rows: list[Banner] = []
    nxt: "dict[str, tuple[datetime, str]]" = {}
    try:
        ak, ak_next = _arknights(now)
        rows += ak
        if ak_next:
            nxt["明日方舟"] = ak_next      # _arknights already returns (time, who)
    except Exception:
        log.warning("方舟卡池整段失败", exc_info=True)
    if sk_get is not None:
        try:
            ef, ef_next = _endfield(cred, sk_get, now)
            rows += ef
            if ef_next and ef_next[0] > now:
                nxt["终末地"] = ef_next
        except Exception:
            log.warning("终末地卡池整段失败", exc_info=True)
    try:
        ww, ww_next = _wuwa(now)
        rows += ww
        if ww_next and ww_next[0] > now:
            nxt["鸣潮"] = ww_next
    except Exception:
        log.warning("鸣潮卡池整段失败", exc_info=True)
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
    try:
        from . import maintenance  # noqa: PLC0415
        w = maintenance.wuwa_window(now)
        if w:
            out["鸣潮"] = w[0].replace(tzinfo=None) + timedelta(days=42)
    except Exception:  # noqa: BLE001
        pass
    return out


def section(now: datetime, **kw) -> str:
    """The section at the end of the daily report."""
    rows, nxt = collect(now, **kw)
    return render(rows, now, nxt, previews(now, rows, version_ends(now, rows)))


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
