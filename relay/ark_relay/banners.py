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

## How this is split up

The three games were split out per game on 2026-09-08 (moved verbatim):
banners_wuwa / banners_endfield / banners_arknights, with banners_common holding
what more than one of them needs. What stays here is the part that is the same
whatever the game -- deciding which block to print, the countdown wording, the
preview-stream rule, and pulling the three games together. This module re-exports
every public name unchanged, so callers and tests still write banners.xxx.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .banners_common import (
    Banner,
    debut_only,
    gh_raw,
    newest_version,
    upcoming,
)
from .banners_arknights import (
    _arknights,
    ak_rarity,
    arknights_next_from_news,
    parse_ak_schedule,
    parse_arknights,
    six_star_only,
)
from .banners_endfield import (
    _endfield,
    endfield_pools_from_notice,
    parse_endfield,
    parse_endfield_notice,
)
from .banners_wuwa import (
    _wuwa,
    parse_wuwa,
    parse_wuwa_preview,
)

# Only public names are forwarded. `_arknights`, `_endfield` and `_wuwa` are
# imported above because `collect` below actually calls them, not to hand them
# on: anything that wants another private name imports it from the module it
# lives in (tests/test_banners.py takes `_PRTS` and `_AK_PAGES` from
# banners_arknights), so changing a game module's internals does not force an
# edit here.
__all__ = [
    "Banner",
    "ak_rarity",
    "arknights_next_from_news",
    "collect",
    "debut_only",
    "endfield_pools_from_notice",
    "gh_raw",
    "group_notice",
    "log",
    "newest_version",
    "opening_tomorrow",
    "parse_ak_schedule",
    "parse_arknights",
    "parse_endfield",
    "parse_endfield_notice",
    "parse_wuwa",
    "parse_wuwa_preview",
    "previews",
    "render",
    "section",
    "six_star_only",
    "upcoming",
    "version_ends",
]

# Same logger name as banners.py -- one feature, one name to grep. It is
# re-declared here instead of imported from banners_common because ruff's
# BLE001 only exempts a blind `except` that logs with exc_info=True when it
# can see the logger being created in the same file.
log = logging.getLogger("ark.banners")


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
