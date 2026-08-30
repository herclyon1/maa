"""三个游戏的「新角色卡池」倒计时与下一期时间。

**只报全新角色首发的池子**——复刻、常驻、中坚轮换一律不报。
用户 2026-08-30 原话：「我有且只要全新角色的卡池信息，其他的不要，
因为我都有老角色了。」

## 数据源（2026-08-30 逐个实测，全部走官方）

| 游戏 | 来源 | 拿到什么 |
|------|------|---------|
| 鸣潮 | 库街区 `api.kurobbs.com/wiki/core/homepage/getPage`（免 token） | 池子名、起止时间；角色名要再查 `getEntryDetail` |
| 鸣潮预告 | 官方游戏内公告 `aki-gm-resources-back.aki-game.com` | 整个版本上下半的**全新五星**和池名 |
| 终末地 | 森空岛 `zonai.skland.com/web/v1/wiki/char-pool` | 池子名、起止时间戳；角色名要再查 `item/info` |
| 明日方舟 | PRTS `卡池一览/限时寻访` | 池子名、UP 干员、精确起止 |
| 方舟预告 | 一图流前端仓库 `gachaScheduleOptions.js`（人工维护） | 下一期池名和大致开始日 |

**为什么必须走官方而不是 Fandom**：2026-08-30 实测，同一时刻
Fandom（国际服）给的是「False Promise for Tomorrow / Denia」，
而库街区（国服）给的是「予明日以谎言 / 达妮娅」。
名字和角色都对不上，服务器进度也不同步。用 Fandom 会报错东西。

## 下一期时间

**鸣潮是唯一能拿到「下一期是谁」的**：官方在版本更新当天发的
「N.N版本内容说明」公告里，把整个版本上下半的全新五星和对应池名
一次性列全，等于提前三周官宣。这一节天然不含复刻，正好对上口径。

方舟和终末地拿不到人，只拿得到**什么时候换**：

* 终末地：本期结束即下期开始（连轴换）
* 明日方舟：`gacha_table.json` 随客户端更新推送，里面**已经有未来的池子**

所以除鸣潮外，「下一期」是推出来的，不是官宣的——渲染时必须说清楚，
不许写成好像官方已经公布了。

取不到就返回空——报告少一行，好过没有报告。
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

# PRTS 认 User-Agent：curl 的默认 UA 能过，浏览器 UA 反而 403。
# 别"优化"成 Chrome UA，会全线 403（2026-08-30 实测两次）。
_UA_PLAIN = "curl/8.7.1"
_UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


@dataclass(frozen=True)
class Banner:
    """一个卡池。`chars` 是这一池首发的新角色，可能不止一个。"""

    game: str
    name: str
    chars: tuple[str, ...]
    start: datetime
    end: datetime


# ── 明日方舟：PRTS ──────────────────────────────────────────────
# 一行长这样（实测）：
#   |[[文件:X.jpg|400px|link=Y]]<br/>[[Y|【限定寻访·夏季】车辙与风的归所]]
#   |2026-08-01 12:00~<br/>2026-08-15 03:59
#   |{{干员头像|予愿安洁莉娜|limited=1}}{{干员头像|珊比}}
_AK_TIME = re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d)\s*~\s*<br\s*/?>\s*"
                      r"(\d{4}-\d\d-\d\d \d\d:\d\d)")
# 两种写法都要认：[[页面|显示名]] 和 [[页面]]；图片链接跳过。
_AK_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_AK_FILE = re.compile(r"^(?:文件|File):", re.I)
_AK_CHAR = re.compile(r"\{\{干员头像\|([^|}]+)")


def parse_arknights(wt: str) -> list[Banner]:
    """解析 PRTS 的寻访表。表是新在前的，这里按时间正序返回。"""
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


# ── 终末地：森空岛官方 ──────────────────────────────────────────
# char-pool 里 chars[].name 是空的，必须再查 item/info；
# gid 从 chars[].pcLink 的 `gameEntryId=` 后面取。
# 这个接口只属于终末地：带 ?gameId=1 返回的还是终末地，
# 而 /api/v1/game/arknights/* 全部 404。
_SK_UP = "label_type_up"


def parse_endfield(pools: list, name_of) -> list[Banner]:
    """`pools` 是 char-pool 的 data.list；`name_of(gid)` 返回角色名。"""
    out: list[Banner] = []
    for p in pools:
        try:
            a = datetime.fromtimestamp(int(p["poolStartAtTs"]))
            b = datetime.fromtimestamp(int(p["poolEndAtTs"]))
        except (KeyError, TypeError, ValueError):
            continue
        names = []
        for c in p.get("chars") or []:
            if c.get("dotType") != _SK_UP:          # 只要 UP，不要陪跑的
                continue
            gid = str(c.get("pcLink", "")).split("gameEntryId=")[-1]
            if gid.isdigit() and (nm := name_of(gid)):
                names.append(nm)
        if names:
            out.append(Banner("终末地", str(p.get("name") or ""),
                              tuple(names), a, b))
    out.sort(key=lambda x: x.start)
    return out


# ── 鸣潮：库街区 wiki 首页（免 token）──────────────────────────
# POST /wiki/core/homepage/getPage，只要三个固定 header。
# data.contentJson.sideModules[] 里 title 含「角色…唤取」的模块，
# content.tabs[] 是同时开着的几个池子：
#   tab.name                        池名
#   tab.countDown.dateRange         ["2026-08-20 11:00", "2026-09-10 09:59"]
#   tab.imgs[0].linkConfig.entryId  角色条目 id
# **imgs 后几项在所有 tab 里是同一组通用条目，只有第一项是角色。**
# 武器池不报。
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


# 官方公告正文里「全新角色」那一节，格式是固定的：
#     5星共鸣者「景燃」（热熔 | 长刃）
#     ...
#     ※可通过[身赴三途]角色活动唤取获得。
_WW_ROLE = re.compile(r"5星共鸣者[「\[]([^」\]]+)[」\]]")
_WW_POOL = re.compile(r"可通过[\[「]([^\]」]+)[\]」]角色活动唤取")


def parse_wuwa_preview(content: str) -> "list[tuple[str, str]]":
    """从版本公告正文取 (角色, 池名)。只截「全新角色」一节，复刻不在其中。"""
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


# ── 首发判定 ────────────────────────────────────────────────────
_RERUN = ("复刻", "Rerun", "rerun")
# 按定义就不可能有首发角色的池子，直接按名字排掉。
# 2026-08-30 第一版没排，「联合行动23」被判成首发（诺威尔、杏仁都是老干员）。
_NOT_DEBUT = ("联合行动", "中坚寻访", "中坚甄选", "概率提升")


def debut_only(banners: list[Banner]) -> list[Banner]:
    """只留首发。传进来的必须是**按开始时间正序的完整历史**。"""
    seen: set[str] = set()
    out: list[Banner] = []
    for b in banners:
        skip = any(k in b.name for k in _RERUN + _NOT_DEBUT)
        fresh = tuple(c for c in b.chars if c not in seen)
        seen.update(b.chars)          # 轮换池里的角色也要记，它们不是新人
        if skip or not fresh:
            continue
        out.append(Banner(b.game, b.name, fresh, b.start, b.end))
    return out


def render(banners: list[Banner], now: datetime,
           next_starts: "dict[str, tuple[datetime, str]] | None" = None) -> str:
    """渲染成日报末尾的几行。

    `next_starts[游戏] = (开始时刻, 是谁)`。是谁为空表示官方只换了时间、
    没公布人——那种情况措辞必须是「约」，不能写成官宣。
    """
    lines: list[str] = []
    for b in sorted((x for x in banners if x.start <= now <= x.end),
                    key=lambda x: x.end):
        d = b.end - now
        lines.append(f"· {b.game}「{b.name}」{' · '.join(b.chars)}"
                     f"　剩 {d.days} 天 {d.seconds // 3600} 小时")
    for game, (when, who) in sorted((next_starts or {}).items(),
                                    key=lambda kv: kv[1][0]):
        if when <= now:
            continue
        d = when - now
        head = f"· {game} 下一期" + ("" if who else "约")
        tail = f"　{who}" if who else "（UP 是谁官方未公布）"
        # 有些源只给到日期；硬凑一个 00:00 出来是假精确。
        stamp = f"{when:%m-%d}" if (when.hour, when.minute) == (0, 0) \
            else f"{when:%m-%d %H:%M}"
        lines.append(f"{head} {stamp} 换（还有 {d.days} 天）{tail}")
    return "🎴 新角色卡池\n" + "\n".join(lines) if lines else ""


# ── 汇总：三个源拉一遍，渲染成日报末尾那一段 ──────────────────
# urlencode 出来的结尾就是 "&page="，正好给后面拼页面标题。
# 2026-08-31 之前这里多切了 [:-6]，把 "&page=" 整个削掉，请求变成
# ...&format=json卡池一览/限时寻访 —— PRTS 回一页 HTML，解析必炸，
# 每次日报都在日志里留两条 WARNING，方舟那几行从来没出来过。
_PRTS = "https://prts.wiki/api.php?" + urllib.parse.urlencode(
    {"action": "parse", "prop": "wikitext", "format": "json", "page": ""})
# 只读这一页就够。2026-08-31 核对过：「卡池一览/常驻标准寻访」那页是
# **干员轮换池**，表格结构也不同（序号/寻访页面/开启时间，没有池名），
# 解析出来恒为 0 条；而且里面每一个干员——提丰、引星棘刺、逻各斯、鸿雪、
# 衡沙——都能在限时寻访里追到更早的首发，轮换池永远不会有新人。
# 哪天方舟真在别的页首发干员了，把那页加回这里即可。
_AK_PAGES = ("卡池一览/限时寻访",)

# 下一期排期：官方不公布，PRTS 也只记已经开过的。一图流前端仓库里
# 有人手工维护着未来排期，`accuracyFlag: false` 表示这条是预测不是官宣。
_AK_SCHEDULE = ("https://raw.githubusercontent.com/Arknights-yituliu/"
                "frontend-v2-plus/main/src/utils/gachaScheduleOptions.js")
_KURO = "https://api.kurobbs.com"
_ZONAI = "https://zonai.skland.com"


def _json(url: str, ua: str, data: "bytes | None" = None,
          headers: "dict | None" = None, timeout: int = 20) -> dict:
    h = {"User-Agent": ua}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310
        return json.loads(r.read())


def _text(url: str, ua: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310
        return r.read().decode("utf-8", "replace")


def parse_ak_schedule(js: str) -> "list[tuple[str, datetime, bool]]":
    """一图流的排期数组 → [(池名, 开始日, 是否官宣)]，按时间正序。"""
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


def _arknights(now: datetime) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """PRTS 两页合起来判首发。下一期时间 PRTS 不给，返回 None 由调用方补。"""
    rows: list[Banner] = []
    for page in _AK_PAGES:
        url = _PRTS + urllib.parse.quote(page)
        try:
            rows += parse_arknights(
                _json(url, _UA_PLAIN)["parse"]["wikitext"]["*"])
        except Exception:  # noqa: BLE001
            log.warning("PRTS 取不到 %s", page, exc_info=True)
    rows.sort(key=lambda b: b.start)
    debut = debut_only(rows)
    if when := min((b.start for b in rows if b.start > now), default=None):
        return debut, (when, "")      # PRTS 已经收录了，时间准，人未知
    try:
        sched = parse_ak_schedule(_text(_AK_SCHEDULE, _UA_BROWSER))
    except Exception:  # noqa: BLE001
        log.warning("一图流方舟排期取不到", exc_info=True)
        return debut, None
    nxt = next(((n, d, ok) for n, d, ok in sched if d > now), None)
    if not nxt:
        return debut, None
    name, day, official = nxt
    return debut, (day, name if official else f"{name}（排期是预测，未官宣）")


def _endfield(cred, sk_get) -> "tuple[list[Banner], datetime | None]":
    try:
        pools = (sk_get("/web/v1/wiki/char-pool")["data"] or {}).get("list") or []
    except Exception:  # noqa: BLE001
        log.warning("森空岛卡池取不到", exc_info=True)
        return [], None

    def name_of(gid: str) -> str:
        try:
            item = ((sk_get(f"/web/v1/wiki/item/info?id={gid}")["data"] or {})
                    .get("item") or {})
            return item.get("name") or ""
        except Exception:  # noqa: BLE001
            return ""

    got = parse_endfield(pools, name_of)
    return got, (min((b.end for b in got), default=None))


# 这个 hash 是渠道常量、不随版本变；真失效了就去
# 555me/game-CDN-List 的 data/ww/game/notice.json 里读 metadata.source_url。
_WW_NOTICE = ("https://aki-gm-resources-back.aki-game.com/gamenotice/G152/"
              "76402e5b20be2c39f095a152090afddc/zh-Hans.json")
_WW_HDR = {"wiki_type": "9", "source": "h5",
           "referer": "https://wiki.kurobbs.com/"}


def _wuwa(now: datetime) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """当前池走 wiki 首页，下一期走官方公告。两个都不要 token。"""
    def post(path, payload=None):
        # data 必须非 None，否则 urllib 发成 GET —— 这两个接口只认 POST。
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
            except Exception:  # noqa: BLE001
                log.warning("库街区条目 %s 查不到名字", eid, exc_info=True)
                cache[eid] = ""
        return cache[eid]

    # 先取公告：它的「全新角色」一节是判断首发/复刻的唯一权威依据。
    # getPage 只给池子，不说谁是新人；3.6 上半两个池里达妮娅是复刻。
    debut: "list[tuple[str, str]]" = []
    notice_ok = True
    try:
        notice = _json(_WW_NOTICE, _UA_BROWSER, timeout=25)
        body = "".join(str(n.get("content") or "")
                       for n in (notice.get("game") or [])
                       if "版本内容说明" in str(n.get("tabTitle") or ""))
        debut = parse_wuwa_preview(body)
    except Exception:  # noqa: BLE001
        notice_ok = False
        log.warning("鸣潮官方公告取不到，这一版分不出首发和复刻", exc_info=True)

    try:
        home = post("/wiki/core/homepage/getPage")
    except Exception:  # noqa: BLE001
        log.warning("库街区首页取不到", exc_info=True)
        return [], None
    pools = parse_wuwa(home, name_of)
    end = min((b.end for b in pools), default=None)

    # 公告拿不到就宁可多报一条复刻，也不把倒计时整个丢掉——反正
    # 同版本几个池子结束时间一样，这一行的价值主要在那个时刻。
    names = {w for w, _ in debut}
    got = [b for b in pools if set(b.chars) & names] if notice_ok else pools

    if not end or end <= now:
        return got, None
    live = {c for b in pools for c in b.chars}
    rest = [(w, pl) for w, pl in debut if w not in live]
    if not rest:
        return got, (end, "")
    who = "、".join(f"{w}「{p}」" if p else w for w, p in rest)
    return got, (end, who)


def section(now: datetime, *, skland_token: str = "",
            cred=None, sk_get=None) -> str:
    """日报末尾那一段。任何一个游戏取不到就少一行，不影响其余。

    只有终末地需要 `skland_token`（或调用方直接给 `cred`/`sk_get`，
    测试就是这么注入的）。方舟走 PRTS、鸣潮走库街区，都不要 token。
    签名链路在 skland.py，这里不重造。
    """
    if sk_get is None and skland_token:
        try:
            from . import skland  # noqa: PLC0415 - 只有这一处用得上
            cred = skland.login(skland_token)
            def sk_get(path):  # noqa: E306
                return skland.get(cred, path)
        except Exception:  # noqa: BLE001
            log.warning("森空岛登录失败，终末地卡池这一行不出", exc_info=True)
            sk_get = None
    banners: list[Banner] = []
    nxt: "dict[str, tuple[datetime, str]]" = {}
    try:
        ak, ak_next = _arknights(now)
        banners += ak
        if ak_next:
            nxt["明日方舟"] = (ak_next, "")
    except Exception:  # noqa: BLE001
        log.warning("方舟卡池整段失败", exc_info=True)
    if sk_get is not None:
        ef, ef_next = _endfield(cred, sk_get)
        banners += ef
        if ef_next and ef_next > now:
            nxt["终末地"] = (ef_next, "")
    try:
        ww, ww_next = _wuwa(now)
        banners += ww
        if ww_next and ww_next[0] > now:
            nxt["鸣潮"] = ww_next
    except Exception:  # noqa: BLE001
        log.warning("鸣潮卡池整段失败", exc_info=True)
    return render(banners, now, nxt)
