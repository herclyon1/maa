"""Countdowns for the three games' new-character banners, and when the next one
starts.

**Only banners that debut a brand-new character are reported** -- reruns, standard
and rotating banners are never reported. The user, 2026-08-30: 「我有且只要全新角色的
卡池信息，其他的不要，因为我都有老角色了。」

## Data sources (each measured 2026-08-30)

| Game | Source | What it gives |
|------|------|---------|
| Wuthering Waves | Kuro BBS `api.kurobbs.com/wiki/core/homepage/getPage` (no token) | banner name, start/end; character names need a further `getEntryDetail` |
| Wuthering Waves preview | official in-game bulletin `aki-gm-resources-back.aki-game.com` | the **brand-new 5-stars** and banner names for both halves of the version |
| Endfield | Skland `zonai.skland.com/web/v1/wiki/char-pool` | banner name, start/end timestamps; character names need a further `item/info` |
| Endfield preview | official bulletin `game-hub.hypergryph.com/bulletin/v2/aggregate` | the **brand-new operators** and banner names for both halves of the version |
| Arknights | PRTS `卡池一览/限时寻访` | banner name, UP operators, exact start/end |
| Arknights preview | the official site's 「…寻访即将开启」 posts | the next banner, its six-stars and opening time |

Fandom is not used: it follows the global servers, whose banner names, characters
and schedule differ from the CN servers'.

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

## Files

This module holds what the three games share (Banner, Trace, render, the fetch
helpers, the Yituliu tables, the history ledger, collect / section /
opening_tomorrow) and re-exports the game modules' names, so `ark_relay.banners.X`
works for all of them: arknights.py, endfield.py, wuwa.py (banners and the two halves
of a version), wuwa_posters.py (version-news posters, OCR, gacha notices) and
wuwa_history.py (past banners, maintenance windows).
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


log = logging.getLogger("ark.banners")

# The User-Agent for PRTS (a MediaWiki site): the project and where to reach it,
# as the MediaWiki API etiquette asks - "Set an informative User-Agent string with
# contact information" (https://www.mediawiki.org/wiki/API:Etiquette), in the
# 「client/version (contact) library/version」 shape of the Wikimedia User-Agent
# policy (https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy).
# PRTS answers this one 200 (API and rendered page, measured 2026-10-07); a browser
# UA gets a 403 (measured 2026-08-30 and again 2026-10-07), so never a Chrome UA here.
_UA_PLAIN = "ark-relay/1.0 (https://github.com/herclyon1/maa) Python-urllib/3"
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


_VER = re.compile(r"(\d+)\.(\d+)")


def newest_version(entries: "list[tuple[str, str]]") -> str:
    """From [(title, body)], pick the body with the highest version number.

    Near the end of a version the next version's notes are already posted, so
    both exist at once. Only the highest version number is taken, so the next
    version is reported as soon as its notes are published.
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


# ── Deciding what counts as a debut ────────────────────────────
_RERUN = ("复刻", "Rerun", "rerun")
# Banners that by definition cannot debut a character, excluded by name
# (e.g. 「联合行动23」 features only old operators).
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
_AK_NEWS_ITEM = re.compile(r'\\"cid\\":\\"(\d+)\\",\\"tab\\":\\"\w+\\",\\"sticky\\":(?:true|false),\\"title\\":\\"([^"\\]+)\\",\\"author\\":\\"[^"\\]*\\",\\"displayTime\\":(\d+)')


def _ak_article_text(raw: str) -> str:
    """Official-site articles are Next.js rendered: the body sits inside a JSON
    string and the HTML is escaped twice.
    """
    body = raw.encode("utf-8").decode("unicode_escape", errors="ignore").encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


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


def _ef_cms_text(html_body: str) -> str:
    """The CMS API returns the article HTML once-escaped as a JSON string, so a plain
    tag strip is enough (the SSR page needs _ak_article_text instead).
    """
    txt = re.sub(r"<[^>]+>", " ", html_body or "").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", html.unescape(txt))


def _pause(seconds: float) -> None:
    import time  # noqa: PLC0415
    time.sleep(seconds)


def record_history(state_dir, game: str, periods: "list[dict]") -> "list[str]":
    """Keep the ended periods in `banners/history.json` and say which ones changed.

    An ended period is a fixed fact, so a (version, part) whose recorded (start, end)
    is not in what is read now means one of the two reads is wrong: it is returned as a
    sentence (the caller warns) and the record is replaced, so it is said once."""
    from ark_relay.core.config import atomic_write_text  # noqa: PLC0415
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


def update_history(state_dir, now: datetime) -> "list[str]":
    """The history step of the daily banner run: one game failing does not stop the
    others, nothing raises, and what changed is returned."""
    out: "list[str]" = []
    for game, step in (("鸣潮", lambda: update_wuwa_history(state_dir, now)),
                       ("终末地", lambda: update_endfield_history(state_dir)),
                       ("明日方舟", lambda: update_arknights_history(state_dir))):
        try:
            out += step()[1]
        except Exception:
            log.info("%s往期卡池这一步没做成", game, exc_info=True)
    return out


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
            from ark_relay.core import skland  # noqa: PLC0415 - needed only here
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
            ef, ef_next = _endfield(cred, sk_get, now, trace, notes)
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
        from ark_relay.features.selfcheck.machinechecks import phone_banners  # noqa: PLC0415 - imports this module
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


# The game modules import from this module, so they are loaded after everything above.
# Names that tests and scripts replace on this module (banners.X = fake) are called
# from the game modules as hub.X, so one replacement reaches every caller:
# _ak_prts_rows, _bili_poster, _json, _kuro_poster, _pause, _text,
# _wuwa_calendar_start, collect, endfield_next_from_news, endfield_pool_ends,
# opening_tomorrow, parse_wuwa, parse_wuwa_poster_first_end, save_trace,
# update_arknights_history, update_endfield_history, update_wuwa_history,
# wuwa_calendar_image
from ark_relay.features.banners.arknights import (  # noqa: E402
    _AK_NEWS, _AK_NEWS_API, ak_news_pages, _AK_PAGES, _AK_POST, ak_post_text,
    _ak_posted, _ak_prts_rows, ak_rarity, AkPast, AkSection, _arknights,
    arknights_banner_posts, arknights_comm_lead, arknights_history,
    arknights_next_from_news, parse_ak_post, parse_arknights, parse_arknights_html,
    _PRTS, _PRTS_PAGE, _rarity_cache, six_star_only, update_arknights_history,
)
from ark_relay.features.banners.endfield import (  # noqa: E402
    ef_banner_posts, _ef_brief_time, _EF_BRIEFING, ef_briefing_banners,
    _EF_BRIEFING_JS, _EF_BULLETIN, _EF_CMS_LIST, _EF_CMS_POST, ef_cms_posts, _EF_NEWS,
    ef_next_banner, _EF_SPAN, _endfield, endfield_history, endfield_next_from_briefing,
    endfield_next_from_news, endfield_pool_ends, endfield_pools_from_notice,
    parse_endfield, parse_endfield_notice, update_endfield_history,
)
from ark_relay.features.banners.wuwa import (  # noqa: E402
    parse_wuwa, parse_wuwa_calendar, parse_wuwa_notice_banners, parse_wuwa_preview,
    _wuwa, wuwa_calendar_image, _wuwa_calendar_start, _wuwa_first_half_end,
    _wuwa_second_half, wuwa_teased, _WW_NOTICE,
)
from ark_relay.features.banners.wuwa_posters import (  # noqa: E402
    _bili_poster, bili_shape, bili_sign, _BILI_TRIES, bili_wbi_keys, BiliFeedProblem,
    image_reader, _kuro_poster, KuroListProblem, ocr_strips, parse_wuwa_poster,
    parse_wuwa_poster_first_end, strip_plan, wuwa_bili_post,
    wuwa_first_half_notice_end, wuwa_gacha_notice, wuwa_news_post, _wuwa_poster_span,
)
from ark_relay.features.banners.wuwa_history import (  # noqa: E402
    update_wuwa_history, wuwa_history, wuwa_maint_notice, wuwa_maint_window,
    wuwa_maintenance, _WW_SITE_ARTICLE, _WW_SITE_ARTICLES,
)

__all__ = [
    "AkPast", "AkSection", "Banner", "BiliFeedProblem", "KuroListProblem", "Trace",
    "ak_news_pages", "ak_post_text", "ak_rarity", "arknights_banner_posts",
    "arknights_comm_lead", "arknights_history", "arknights_next_from_news",
    "bili_shape", "bili_sign", "bili_wbi_keys", "collect", "crosscheck", "debut_only",
    "ef_banner_posts", "ef_briefing_banners", "ef_cms_posts", "ef_next_banner",
    "endfield_history", "endfield_next_from_briefing", "endfield_next_from_news",
    "endfield_pool_ends", "endfield_pools_from_notice", "gate_preview", "gh_raw",
    "group_notice", "image_reader", "log", "newest_version", "ocr_strips",
    "opening_tomorrow", "parse_ak_post", "parse_ak_schedule", "parse_arknights",
    "parse_arknights_html", "parse_ef_yituliu", "parse_endfield",
    "parse_endfield_notice", "parse_wuwa", "parse_wuwa_calendar",
    "parse_wuwa_notice_banners", "parse_wuwa_poster", "parse_wuwa_poster_first_end",
    "parse_wuwa_preview", "record_history", "render", "save_trace", "section",
    "six_star_only", "strip_plan", "upcoming", "update_arknights_history",
    "update_endfield_history", "update_history", "update_wuwa_history",
    "wuwa_bili_post", "wuwa_calendar_image", "wuwa_first_half_notice_end",
    "wuwa_gacha_notice", "wuwa_history", "wuwa_maint_notice", "wuwa_maint_window",
    "wuwa_maintenance", "wuwa_news_post", "wuwa_teased",
    # Private names listed because tests and scripts read or replace them as banners.X.
    "_AK_NEWS", "_AK_NEWS_API", "_AK_PAGES", "_AK_POST", "_BILI_TRIES", "_EF_BRIEFING",
    "_EF_BRIEFING_JS", "_EF_BULLETIN", "_EF_CMS_LIST", "_EF_CMS_POST", "_EF_NEWS",
    "_EF_SPAN", "_PRTS", "_PRTS_PAGE", "_WW_NOTICE", "_WW_SITE_ARTICLE",
    "_WW_SITE_ARTICLES", "_ak_posted", "_ak_prts_rows", "_arknights", "_bili_poster",
    "_ef_brief_time", "_endfield", "_kuro_poster", "_rarity_cache", "_wuwa",
    "_wuwa_calendar_start", "_wuwa_first_half_end", "_wuwa_poster_span",
    "_wuwa_second_half",
]
