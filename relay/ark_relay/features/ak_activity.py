"""R-14: Detect newly opened or rerun Arknights activities and notify once.

Combines two authoritative sources:
1. Official Arknights news API (`https://ak.hypergryph.com/api/news?category=ACTIVITY`,
   plus bulletin detail `https://web-news.hypergryph.com/api/bulletin/{cid}`), keeping
   reruns (复刻) and recognizing SideStory / 故事集 / 主题活动 / 限时活动 while
   filtering out gacha-only notices and non-gameplay community contests.
2. Local MAA stage activity file (`<maa_dir>/cache/gui/StageActivityV2.json`,
   `Official.sideStoryStage`), checking `UtcStartTime` and `UtcExpireTime` against
   the server clock.

Deduplication is persisted in `state.json` (`marks["ak_activity:<id>"]`), storing
every alias (MAA stage key, official `cid=<id>`, and normalized name + start date)
so both sources merge cleanly without duplicate pushes while never suppressing a
future rerun that reuses a generic slot key like `SSReopen`.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ark_relay.core import config, plan, texts
from ark_relay.core.config import SERVER_TZ

log = logging.getLogger("ark.ak_activity")

AK_NEWS_API = "https://ak.hypergryph.com/api/news?category=ACTIVITY&page={page}"
AK_POST_API = "https://web-news.hypergryph.com/api/bulletin/{cid}?lang=zh-cn&code=arknights"
_UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

NEWS_CHECK_INTERVAL_S = 1800.0
NEWS_MAX_PAGES = 2
DEFAULT_ACTIVITY_SPAN_DAYS = 14

_REUSABLE_STAGE_KEYS = frozenset({"ssreopen", "reopen", "rerun", "sidestoryreopen"})
_EXCLUDE_TITLE_HINTS = (
    "创作征集", "征集活动", "周边", "音乐会", "音律联觉",
    "漫展", "线下", "前瞻特别节目", "特别节目", "直播", "问卷", "壁纸", "表情包",
)
_ACTIVITY_TITLE_HINTS = (
    "[活动预告]", "sidestory", "故事集", "限时活动", "主题活动", "主题曲",
    "危机合约", "生息演算", "集成战略", "保全派驻", "矢量突破",
    "引航者试炼", "联锁竞赛", "多维合作", "感谢庆典", "嘉年华", "特别活动",
)

_QUOTE_NAME = re.compile(r"「([^」]+)」")
_SECTION_ONE = re.compile(r"(?:^|\n)一、([^\n]*)")
_SECTION_TWO = re.compile(r"\n二、")
_STAGE_TIME_ANCHOR = re.compile(r"活动关卡[^\n]{0,24}(?:开启|开放)时间")
_TIME_SPAN = re.compile(
    r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*(?:(上午|下午)?(\d{1,2}):(\d{2})|(版本更新后))\s*[-~～]\s*"
    r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*(上午|下午)?(\d{1,2}):(\d{2})"
)
_STAGE_CODE = re.compile(r"^[A-Z]{2,4}-\d{1,2}$")
_NORM_STRIP = re.compile(r"[\s·•\-_—:：!！?？,，.。'\"「」【】\[\]()（）]")

_last_news_poll: dict[str, float] = {}
_last_cache_err: dict[str, str] = {}


@dataclass(frozen=True)
class AkActivity:
    """One Arknights in-game activity detected from local MAA data or official news."""

    activity_id: str
    name: str
    kind: str
    rerun: bool
    start: datetime
    end: datetime | None
    source: str
    aliases: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()

    def all_ids(self) -> tuple[str, ...]:
        items: list[str] = [self.activity_id, *self.aliases, canonical_alias(self.name, self.start)]
        return tuple(dict.fromkeys(x for x in items if x))


def _norm_name(name: str) -> str:
    cleaned = str(name or "").replace("复刻", "").strip()
    return _NORM_STRIP.sub("", cleaned).lower()


def canonical_alias(name: str, start: datetime) -> str:
    """Stable cross-source dedupe alias built from normalized event name and Beijing opening date."""
    norm = _norm_name(name)
    day = start.astimezone(SERVER_TZ).strftime("%Y-%m-%d")
    return f"name:{norm}@{day}" if norm else f"day:{day}"


def _try_strptime(text: str, fmt: str, tz: timezone) -> datetime | None:
    try:
        return datetime.strptime(text, fmt).replace(tzinfo=tz).astimezone(SERVER_TZ)
    except ValueError:
        return None


def _parse_tz_hours(raw: Any, default: int = 8) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_maa_time(raw: str, tz_hours: int) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    tz = timezone(timedelta(hours=tz_hours))
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"):
        if dt := _try_strptime(text, fmt, tz):
            return dt
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(SERVER_TZ)


def _extract_stages(node: dict[str, Any]) -> tuple[str, ...]:
    raw = node.get("Stages")
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        val = str(item.get("Value") or item.get("Display") or "").strip()
        if _STAGE_CODE.match(val) and val not in out:
            out.append(val)
    return tuple(out)


def parse_stage_activity_v2(data: dict[str, Any]) -> list[AkActivity]:
    """Parse MAA `StageActivityV2.json` `Official.sideStoryStage` entries."""
    official = data.get("Official") if isinstance(data, dict) else None
    side_story = official.get("sideStoryStage") if isinstance(official, dict) else None
    if not isinstance(side_story, dict):
        return []
    out: list[AkActivity] = []
    for raw_key, node in side_story.items():
        if not isinstance(node, dict):
            continue
        act = node.get("Activity")
        if not isinstance(act, dict):
            continue
        tz_hours = _parse_tz_hours(act.get("TimeZone", 8))
        start = _parse_maa_time(str(act.get("UtcStartTime") or ""), tz_hours)
        end = _parse_maa_time(str(act.get("UtcExpireTime") or ""), tz_hours)
        if start is None:
            continue
        key = str(raw_key or "").strip()
        tip = str(act.get("Tip") or "").strip()
        name = str(act.get("StageName") or "").strip()
        if not name and (m := _QUOTE_NAME.search(tip)):
            name = m.group(1).strip()
        name = name or key or "当期活动"
        rerun = ("复刻" in tip) or ("复刻" in name) or (key.lower() in _REUSABLE_STAGE_KEYS)
        if "故事集" in tip:
            kind = "故事集"
        elif "主题" in tip:
            kind = "主题活动"
        else:
            kind = "支线活动"
        if not key or key.lower() in _REUSABLE_STAGE_KEYS:
            act_id = f"{key or 'stage'}:{start:%Y%m%d}"
            aliases = (act_id, canonical_alias(name, start))
        else:
            act_id = key
            aliases = (key, canonical_alias(name, start))
        out.append(AkActivity(
            activity_id=act_id,
            name=name,
            kind=kind,
            rerun=rerun,
            start=start,
            end=end,
            source="MAA活动表",
            aliases=aliases,
            stages=_extract_stages(node),
        ))
    return out


def read_local_activities(automas_dir: Path | None, *, maa_dir: Path | None = None,
                          cache_path: Path | None = None) -> list[AkActivity]:
    """Read activities from local `StageActivityV2.json`. Returns [] when absent/unreadable."""
    path = cache_path
    if path is None:
        base = maa_dir or plan.script_dir(automas_dir, "MAA")
        if not base:
            return []
        path = Path(base) / "cache" / "gui" / "StageActivityV2.json"
    key = str(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _last_cache_err.pop(key, None)
        return []
    except (OSError, ValueError) as exc:
        err_key = f"{type(exc).__name__}: {exc}"
        if _last_cache_err.get(key) != err_key:
            log.warning("MAA 活动表读不了（%s）：%s", path, exc)
            _last_cache_err[key] = err_key
        return []
    _last_cache_err.pop(key, None)
    return parse_stage_activity_v2(raw)


def _strip_html(raw: str) -> str:
    txt = re.sub(r"<(?:br|/p|/div|/li|/h\d)[^>]*>", "\n", str(raw or ""), flags=re.I)
    txt = html.unescape(re.sub(r"<[^>]+>", "", txt))
    return "\n".join(line.strip() for line in txt.splitlines() if line.strip())


def is_activity_news_title(title: str) -> bool:
    """True for in-game Arknights activity opening/rerun announcements (not gacha-only/fanart)."""
    t = str(title or "").strip()
    if not t:
        return False
    if "开启" not in t and "开放" not in t:
        return False
    if any(bad in t for bad in _EXCLUDE_TITLE_HINTS):
        return False
    low = t.lower()
    has_hint = any(h in low for h in _ACTIVITY_TITLE_HINTS)
    # Standalone gacha notices (e.g. 「限时寻访即将开启」) belong to banners.py, not R-14.
    if "寻访" in t and not has_hint:
        return False
    if has_hint:
        return True
    return "复刻" in t and ("活动" in t or "关卡" in t)


def _infer_year(month: int, posted: datetime) -> int:
    return posted.year + (1 if month < posted.month - 6 else 0)


def _parse_span_match(m: re.Match[str], posted: datetime) -> tuple[datetime, datetime]:
    y1, mo, d, ap1, hh, mm, note, y2, mo2, d2, ap2, hh2, mm2 = m.groups()
    mo_i, d_i, mo2_i, d2_i = int(mo), int(d), int(mo2), int(d2)
    year = int(y1) if y1 else _infer_year(mo_i, posted)
    if note:
        start = datetime(year, mo_i, d_i, 0, 0, tzinfo=SERVER_TZ)
    else:
        h1 = int(hh) + (12 if ap1 == "下午" and int(hh) < 12 else 0)
        start = datetime(year, mo_i, d_i, h1, int(mm), tzinfo=SERVER_TZ)
    year2 = int(y2) if y2 else year + (1 if mo2_i < mo_i else 0)
    h2 = int(hh2) + (12 if ap2 == "下午" and int(hh2) < 12 else 0)
    end = datetime(year2, mo2_i, d2_i, h2, int(mm2), tzinfo=SERVER_TZ)
    return start, end


def _section_one(body: str) -> str:
    m1 = _SECTION_ONE.search(body)
    sub = body[m1.start():] if m1 else body
    m2 = _SECTION_TWO.search(sub)
    return sub[:m2.start()] if m2 else sub


def _classify_kind(title: str, sec1: str) -> str:
    combined = f"{title}\n{sec1}"
    if "sidestory" in combined.lower():
        return "支线活动"
    if "故事集" in combined:
        return "故事集"
    if any(k in combined for k in ("主题活动", "主题曲", "感谢庆典", "嘉年华", "危机合约", "矢量突破", "引航者试炼")):
        return "主题活动"
    return "限时活动"


def _extract_news_name(title: str, sec1: str) -> str:
    # Prefer SideStory/故事集 quoted name in title first, then in section 1.
    if m := _QUOTE_NAME.search(title):
        return m.group(1).strip()
    if m := re.search(r"(?:SideStory|故事集)「([^」]+)」", sec1, flags=re.I):
        return m.group(1).strip()
    if m := _QUOTE_NAME.search(sec1.splitlines()[0] if sec1 else ""):
        return m.group(1).strip()
    cleaned = re.sub(r"^\[[^\]]+\]", "", title).strip()
    cleaned = re.sub(r"(?:限时)?(?:复刻)?(?:即将)?(?:开启|开放)$", "", cleaned).strip()
    return cleaned or title.strip()


def parse_activity_bulletin(cid: str, title: str, body_html_or_text: str,
                            posted: datetime) -> AkActivity | None:
    """Parse one official Arknights activity bulletin into an AkActivity, or None."""
    if not is_activity_news_title(title):
        return None
    posted_bj = posted.astimezone(SERVER_TZ) if posted.tzinfo else posted.replace(tzinfo=SERVER_TZ)
    text = _strip_html(body_html_or_text)
    sec1 = _section_one(text)
    # Prefer the activity stage window (e.g. 11-22 04:00 ~ 12-02 03:59) when published.
    span_match = None
    if anchor := _STAGE_TIME_ANCHOR.search(sec1):
        span_match = _TIME_SPAN.search(sec1[anchor.start():])
    if span_match is None:
        span_match = _TIME_SPAN.search(sec1) or _TIME_SPAN.search(text)
    if span_match is None:
        return None
    start, end = _parse_span_match(span_match, posted_bj)
    name = _extract_news_name(title, sec1)
    first_line = sec1.splitlines()[0] if sec1 else ""
    rerun = ("复刻" in title) or ("复刻" in first_line)
    kind = _classify_kind(title, sec1)
    cid_s = str(cid or "").strip()
    act_id = f"cid={cid_s}" if cid_s else f"news:{start:%Y%m%d}"
    aliases = tuple(dict.fromkeys(x for x in (
        act_id,
        f"cid:{cid_s}" if cid_s else "",
        canonical_alias(name, start),
    ) if x))
    return AkActivity(
        activity_id=act_id,
        name=name,
        kind=kind,
        rerun=rerun,
        start=start,
        end=end,
        source="方舟官网公告",
        aliases=aliases,
    )


def _http_text(url: str, timeout: float = 12.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA_BROWSER})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_post_body(get, cid: str, post_text=None) -> str:
    if post_text is not None:
        return str(post_text(cid) or "")
    raw = json.loads(get(AK_POST_API.format(cid=cid)))
    if raw.get("code") != 0:
        raise ValueError(f"方舟官网详情 {cid} 返回异常 code={raw.get('code')!r}")
    return str((raw.get("data") or {}).get("data") or "")


def _parse_news_item(get, post_text, cid: str, title: str, posted: datetime) -> AkActivity | None:
    try:
        body = _fetch_post_body(get, cid, post_text=post_text)
        return parse_activity_bulletin(cid, title, body, posted)
    except Exception as exc:  # noqa: BLE001 - one bad bulletin must not hide others
        log.info("读取方舟活动公告详情 %s 失败（%s），跳过该条", cid, exc)
        return None


def fetch_official_activities(*, get=None, post_text=None, max_pages: int = NEWS_MAX_PAGES) -> list[AkActivity]:
    """Fetch recent Arknights activity announcements from `ak.hypergryph.com/api/news`."""
    getter = get or _http_text
    out: list[AkActivity] = []
    seen_cids: set[str] = set()
    for page in range(1, max_pages + 1):
        d = json.loads(getter(AK_NEWS_API.format(page=page)))
        if d.get("code") != 0:
            raise ValueError(f"方舟官网活动列表第 {page} 页返回异常 code={d.get('code')!r}")
        data = d.get("data") or {}
        items = data.get("list") or []
        for it in items:
            cid = str(it.get("cid") or "").strip()
            title = str(it.get("title") or "").strip()
            if not cid or cid in seen_cids or not is_activity_news_title(title):
                continue
            seen_cids.add(cid)
            ts = int(it.get("displayTime") or 0)
            posted = datetime.fromtimestamp(ts, tz=SERVER_TZ)
            if act := _parse_news_item(getter, post_text, cid, title, posted):
                out.append(act)
        if data.get("end") or not items:
            break
    return out


def _same_activity(a: AkActivity, b: AkActivity) -> bool:
    if set(a.all_ids()) & set(b.all_ids()):
        return True
    na, nb = _norm_name(a.name), _norm_name(b.name)
    if not na or not nb or (na != nb and na not in nb and nb not in na):
        return False
    return abs((a.start.astimezone(SERVER_TZ).date() - b.start.astimezone(SERVER_TZ).date()).days) <= 1


def _merge_pair(base: AkActivity, extra: AkActivity) -> AkActivity:
    # Prefer specific non-cid MAA id when available, keeping every alias from both sources.
    primary = base.activity_id
    if primary.startswith("cid=") and not extra.activity_id.startswith("cid="):
        primary = extra.activity_id
    aliases = tuple(dict.fromkeys((*base.all_ids(), *extra.all_ids())))
    stages = base.stages or extra.stages
    end = base.end or extra.end
    # Prefer MAA's stage end over a later shop-only end when MAA cache is one of the sources.
    if extra.source == "MAA活动表" and extra.end is not None:
        end = extra.end
    sources = " + ".join(dict.fromkeys(s for s in (base.source, extra.source) if s))
    return AkActivity(
        activity_id=primary,
        name=base.name if len(base.name) >= len(extra.name) else extra.name,
        kind=base.kind if base.kind != "限时活动" else extra.kind,
        rerun=base.rerun or extra.rerun,
        start=min(base.start, extra.start),
        end=end,
        source=sources,
        aliases=aliases,
        stages=stages,
    )


def merge_activities(cache_acts: list[AkActivity], news_acts: list[AkActivity]) -> list[AkActivity]:
    """Merge local MAA cache entries and official news entries into deduplicated events."""
    merged: list[AkActivity] = []
    for act in [*cache_acts, *news_acts]:
        idx = next((i for i, cur in enumerate(merged) if _same_activity(cur, act)), None)
        if idx is None:
            merged.append(act)
        else:
            merged[idx] = _merge_pair(merged[idx], act)
    merged.sort(key=lambda a: a.start)
    return merged


def _as_bj(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(tz=SERVER_TZ)
    return dt.replace(tzinfo=SERVER_TZ) if dt.tzinfo is None else dt.astimezone(SERVER_TZ)


def is_open_or_opening_today(act: AkActivity, now: datetime) -> bool:
    """True if `act` opens today or is currently running at `now` (Beijing clock)."""
    now_bj = _as_bj(now)
    start_bj = _as_bj(act.start)
    end_bj = (
        _as_bj(act.end)
        if act.end is not None
        else start_bj + timedelta(days=DEFAULT_ACTIVITY_SPAN_DAYS)
    )
    return start_bj.date() <= now_bj.date() and now_bj < end_bj


def _recorded_ids(store) -> set[str]:
    out: set[str] = set()
    marks = store.section("marks")
    for k, val in marks.items():
        if not k.startswith("ak_activity:"):
            continue
        out.add(k.removeprefix("ak_activity:"))
        if isinstance(val, dict):
            for alias in val.get("ids") or ():
                if isinstance(alias, str) and alias:
                    out.add(alias)
            name = str(val.get("name") or "")
            start_s = str(val.get("start") or "")
            if name and len(start_s) >= 10:
                norm = _norm_name(name)
                if norm:
                    out.add(f"name:{norm}@{start_s[:10]}")
    return out


def already_notified(store, act: AkActivity) -> bool:
    """True if any alias of `act` is already recorded in state.json marks."""
    seen = _recorded_ids(store)
    return bool(set(act.all_ids()) & seen)


def mark_notified(store, act: AkActivity, now: datetime) -> None:
    """Persist `act` and all its aliases in state.json `marks["ak_activity:<id>"]`."""
    now_bj = now.astimezone(SERVER_TZ)
    store.set("marks", f"ak_activity:{act.activity_id}", {
        "name": act.name,
        "kind": act.kind,
        "rerun": act.rerun,
        "start": act.start.astimezone(SERVER_TZ).isoformat(timespec="seconds"),
        "end": act.end.astimezone(SERVER_TZ).isoformat(timespec="seconds") if act.end else "",
        "ids": list(act.all_ids()),
        "source": act.source,
        "notified_at": now_bj.isoformat(timespec="seconds"),
    })


def format_notice(act: AkActivity, now: datetime) -> tuple[str, str]:
    """Plain-Chinese (title, body) for group and friend-event notification."""
    now_bj = _as_bj(now)
    start_bj = _as_bj(act.start)
    start_txt = config.both_clocks(start_bj)
    end_txt = config.both_clocks(_as_bj(act.end)) if act.end else ""
    opening_today = start_bj > now_bj
    body = texts.ak_activity_open_body(
        act.name,
        act.kind,
        start_txt,
        end_txt=end_txt,
        rerun=act.rerun,
        opening_today=opening_today,
    )
    return texts.AK_ACTIVITY_OPEN, body


def _should_poll_news(state_key: str, *, get, force_news: bool) -> bool:
    if get is not None:
        return True
    if os.environ.get("ARK_AK_ACTIVITY_NO_NET") == "1":
        return False
    now_m = time.monotonic()
    last = _last_news_poll.get(state_key, -1e9)
    if not force_news and now_m - last < NEWS_CHECK_INTERVAL_S:
        return False
    _last_news_poll[state_key] = now_m
    return True


def _emit_friend_activity(eng, act: AkActivity, title: str, body: str, now_bj: datetime,
                          friend_post=None, friend_sync: bool = False) -> None:
    try:
        from ark_relay.features import friend_events  # noqa: PLC0415
        friend_events.emit_arknights_activity_open(
            eng.cfg,
            activity_id=act.activity_id,
            title=title,
            text=body,
            now=now_bj,
            post=friend_post,
            sync=friend_sync,
        )
    except Exception:
        log.warning("明日方舟活动好友提醒入队失败（%s）", act.activity_id, exc_info=True)


def step(eng, now: datetime | None = None, *, cache_path: Path | None = None,
         get=None, post_text=None, force_news: bool = False,
         friend_post=None, friend_sync: bool = False) -> list[AkActivity]:
    """Check for newly opened Arknights activities, notify group + friend queue once each."""
    from ark_relay.features import hardlock  # noqa: PLC0415
    if hardlock.active(getattr(eng.cfg, "state_dir", None)):
        return []
    now_bj = _as_bj(now)
    cache_acts = read_local_activities(
        getattr(eng.cfg, "automas_dir", None),
        maa_dir=getattr(eng.cfg, "maa_dir", None),
        cache_path=cache_path,
    )
    news_acts: list[AkActivity] = []
    state_key = str(getattr(eng.cfg, "state_dir", ""))
    if _should_poll_news(state_key, get=get, force_news=force_news):
        try:
            news_acts = fetch_official_activities(get=get, post_text=post_text)
        except Exception as exc:  # noqa: BLE001 - local MAA source still works when news API fails
            log.info("拉取明日方舟官网活动列表失败（%s），本轮仅用本地活动表", exc)
    all_acts = merge_activities(cache_acts, news_acts)
    notified: list[AkActivity] = []
    for act in all_acts:
        if not is_open_or_opening_today(act, now_bj):
            continue
        if already_notified(eng.state.store, act):
            continue
        title, body = format_notice(act, now_bj)
        errs = eng.notifier.send_group(title, body)
        if errs:
            log.info("明日方舟活动开启提醒暂未送到群（%s），下轮重试：%s", "；".join(errs), act.name)
            continue
        mark_notified(eng.state.store, act, now_bj)
        _emit_friend_activity(eng, act, title, body, now_bj,
                              friend_post=friend_post, friend_sync=friend_sync)
        log.info("🎉 已推送明日方舟活动开启提醒：%s（%s，来源：%s）",
                 act.name, act.activity_id, act.source)
        notified.append(act)
    return notified
