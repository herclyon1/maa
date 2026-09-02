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
| 终末地预告 | 官方公告 `game-hub.hypergryph.com/bulletin/v2/aggregate` | 整版上下半的**全新干员**和池名 |
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


# 官方「版本更新说明」公告里，整版上下半的新干员和池名一起给，
# 和鸣潮的版本公告是一个路数：
#     ■ 全新干员
#     6星干员【诀】【梨诺】
#     ■ 全新寻访及申领
#     1.「临渊望北」特许寻访 · ... 6星干员【诀】获取概率提升 ...
#     3.「晨星于此闪耀」特许寻访 · ... 6星干员【梨诺】获取概率提升 ...
# 「全新干员」那一节天然不含复刻，正好是判首发的依据。
_EF_DEBUT_SEG = re.compile(r"全新干员(.{0,300}?)■", re.S)
# 只要 6 星。2026-09-02 的公告「6星干员【提弗洛斯】、5星干员【噗切娜】」——
# 噗切娜是赠送的 5 星，根本不进卡池，却被当成下一期报出去了。
# 用户定的：终末地、明日方舟只报 6 星限定新 UP；鸣潮只报 5 星（它的最高稀有度）。
_EF_SIX = re.compile(r"6星干员((?:【[^】]+】)+)")
_EF_BRACKET = re.compile(r"【([^】]+)】")
_EF_POOL = re.compile(r"「([^」]+)」特许寻访")
_EF_UP = re.compile(r"6星干员【([^】]+)】获取概率提升")


_VER = re.compile(r"(\d+)\.(\d+)")


def newest_version(entries: "list[tuple[str, str]]") -> str:
    """从 [(标题, 正文)] 里挑版本号最大的那条正文。

    3.6 快结束时 3.7 的版本说明会先发出来，两条并存。原来是把所有
    「版本内容说明」拼在一起，一旦 3.7 排在 3.6 前面，「在开的那位之后」
    这条判据就会指到错的人身上。只认版本号最大的那条，3.7 一发布
    不用改代码就能自动报出来。
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
    """公告按时间顺序列全版的池子，在开的那位之后的才是还没开的。

    不能只用「不在 live 里」——本版上半已经开完了，那位也不在 live 里，
    照那个判据会把**上一期**当成下一期报出去。
    """
    idx = max((i for i, (w, _) in enumerate(debut) if w in live), default=None)
    return debut[idx + 1:] if idx is not None else []


_EF_ANY_POOL = re.compile(r"「([^」]+)」(特许寻访|重构寻访#?\d*)")
_EF_OPEN = re.compile(r"开放时间[：:]\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})")


def parse_endfield_notice(html: str) -> "list[tuple[str, str]]":
    """从版本更新说明取 (干员, 池名)，按公告里的先后顺序。只要 6 星首发。"""
    return [(n, pool) for n, pool, _, debut in endfield_pools_from_notice(html) if debut]


def endfield_pools_from_notice(html: str) -> "list[tuple[str, str, datetime | None, bool]]":
    """公告里每一期 6 星 UP 池：(干员, 池名, 开放时刻或 None, 是否首发)。

    用户 2026-09-03：「不要光顾着删卡池，你要补充预期卡池的角色」。
    2026-09-02 的公告：「冬猎」提弗洛斯（首发，版本更新后开）；
    「绚丽异彩」重构寻访#1 伊冯（复刻，2026/09/24 12:00 开）。
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


# 日报里的顺序：和上面三块运行记录一致（MAA → 鸣潮 → 终末地）
_GAME_ORDER = ("明日方舟", "鸣潮", "终末地")


def _stamp(when: datetime) -> str:
    # 有些源只给到日期；硬凑一个 00:00 出来是假精确。
    return f"{when:%m-%d}" if (when.hour, when.minute) == (0, 0) else f"{when:%m-%d %H:%M}"


def render(banners: list[Banner], now: datetime,
           next_starts: "dict[str, tuple[datetime, str]] | None" = None) -> str:
    """日报末尾那一段，按游戏分块，每块最多两行：

        明日方舟
        · 当期　「池名」角色　剩 3 天 4 小时（09-05 03:59 结束）
        · 预告　09-04 开（还有 1 天）　是谁

    用户 2026-09-02：「要有当期新 UP 角色的卡池倒计时（如果没有 UP 就不显示），
    而且得要有卡池预告」，并且三家视觉上要一样。所以：
    · 没有在开的 UP → 不写「当期」那行；没有预告 → 不写「预告」那行；
      两样都没有 → 这个游戏整块不出现。
    · `next_starts[游戏] = (开始时刻, 是谁)`。是谁为空表示官方只换了时间、
      没公布人——那种情况措辞必须是「约」，不能写成官宣。
    """
    live: dict[str, list[Banner]] = {}
    for b in sorted((x for x in banners if x.start <= now <= x.end), key=lambda x: x.end):
        live.setdefault(b.game, []).append(b)
    nxt = {g: v for g, v in (next_starts or {}).items() if v[0] > now}
    games = [g for g in _GAME_ORDER if g in live or g in nxt]
    games += sorted(g for g in set(live) | set(nxt) if g not in _GAME_ORDER)
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
        blocks.append("\n".join(lines))
    return "🎴 卡池\n" + "\n".join(blocks) if blocks else ""


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

# 2026-08-31 在游戏机上实测：raw.githubusercontent.com 通是通，但要 **33 秒**，
# 超过超时就直接失败，方舟和终末地的预告因此时有时无。同一份文件走
# jsDelivr 只要 2.8~4.6 秒。所以按实测速度排镜像，raw 放最后兜底。
# gitmirror 和 ghfast.top 当时完全不通，别加回来。
def gh_raw(owner: str, repo: str, branch: str, path: str) -> list[str]:
    """同一个 GitHub 文件的几条路，按在游戏机上实测的速度排。"""
    return [
        f"https://fastly.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}",
        f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}",
        f"https://gh-proxy.com/https://raw.githubusercontent.com/"
        f"{owner}/{repo}/{branch}/{path}",
        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}",
    ]


# 下一期排期：官方不公布，PRTS 也只记已经开过的。一图流前端仓库里
# 有人手工维护着未来排期，`accuracyFlag: false` 表示这条是预测不是官宣。
_AK_SCHEDULE = gh_raw("Arknights-yituliu", "frontend-v2-plus", "main",
                      "src/utils/gachaScheduleOptions.js")
_KURO = "https://api.kurobbs.com"
_ZONAI = "https://zonai.skland.com"
# 终末地官方公告聚合口，免 token。code 是渠道常量。
_EF_BULLETIN = ("https://game-hub.hypergryph.com/bulletin/v2/aggregate"
                "?lang=zh-cn&platform=Windows&channel=1&type=0"
                "&code=endfield_5SD9TN&hideDetail=0")
# 跨版本的下一期只有手工维护的这份有。时刻不采信它（见 docs/BANNER-SOURCES.md），
# 只用来取「下一个是谁」。
_EF_SCHEDULE = gh_raw("Arknights-yituliu", "ef-frontend-v1", "main",
                      "custom/core/gacha/data/pool_info_table.json")


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


def _first(urls: list[str], ua: str, timeout: int = 12) -> str:
    """挨个试，第一条通的就返回。全挂了才抛最后一个异常。"""
    err: Exception = RuntimeError("没有可用地址")
    for u in urls:
        try:
            return _text(u, ua, timeout)
        except Exception as e:  # noqa: BLE001, PERF203
            log.debug("镜像取不到 %s：%s", u, e)
            err = e
    raise err


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


_AK_RARITY = re.compile(r"稀有度\s*=\s*(\d)")
_rarity_cache: dict[str, int] = {}


def ak_rarity(name: str, fetch=None) -> int:
    """PRTS 干员页的稀有度字段，**0 起算**（5 = 六星，2026-09-03 用予愿安洁莉娜核对）。
    取不到返回 -1。只查在开的那几个名字，每个名字缓存到进程结束。"""
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
    """方舟池子只留六星（用户定的）。稀有度查不到的名字**去掉**，不冒充。"""
    keep = tuple(c for c in b.chars if ak_rarity(c, fetch) == 5)
    return Banner(b.game, b.name, keep, b.start, b.end)


_AK_NEWS = "https://ak.hypergryph.com/news"
_AK_NEWS_ITEM = re.compile(r'\\"cid\\":\\"(\d+)\\",\\"tab\\":\\"\w+\\",\\"sticky\\":(?:true|false),\\"title\\":\\"([^"\\]+)\\",\\"author\\":\\"[^"\\]*\\",\\"displayTime\\":(\d+)')
_AK_SIX_LINE = re.compile(r"★{6}[：:]\s*([^（(★]+)")
_AK_SPAN = re.compile(r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})\s*[-~～]\s*(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")


def _ak_article_text(raw: str) -> str:
    """官网文章是 Next.js 渲染，正文在 JSON 字符串里、HTML 被转义两层。"""
    body = raw.encode("utf-8").decode("unicode_escape", errors="ignore").encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def arknights_next_from_news(now: datetime, get=None) -> "tuple[datetime, str] | None":
    """官网最新一条「…寻访即将开启」：(开启时刻, 六星「池名」)。没有/已开就 None。

    用户 2026-09-03：「明日方舟官方早都公布角色了，中继完全没跟进」。
    实录 08-29 公告 1457：【石白深蓝之夜】限时寻访 09月04日 12:00 - 09月18日 03:59，
    ★★★★★★：结城理（占6★出率的50%）。年份公告里没有，按「离现在最近」补。
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
    # 只对在开的那几个查稀有度（历史几十条不查），六星才报
    debut = [six_star_only(b) if b.start <= now <= b.end else b for b in debut]
    debut = [b for b in debut if b.chars]
    # 官网「寻访即将开启」公告最准：有名有时刻。有就用它。
    try:
        if official := arknights_next_from_news(now):
            return debut, official
    except Exception:  # noqa: BLE001
        log.warning("方舟官网寻访公告取不到", exc_info=True)
    if when := min((b.start for b in rows if b.start > now), default=None):
        return debut, (when, "")      # PRTS 已经收录了，时间准，人未知
    try:
        sched = parse_ak_schedule(_first(_AK_SCHEDULE, _UA_BROWSER))
    except Exception:  # noqa: BLE001
        log.warning("一图流方舟排期取不到", exc_info=True)
        return debut, None
    nxt = next(((n, d, ok) for n, d, ok in sched if d > now), None)
    if not nxt:
        return debut, None
    name, day, official = nxt
    return debut, (day, name if official else f"{name}（排期是预测，未官宣）")


def _endfield(cred, sk_get, now: datetime
              ) -> "tuple[list[Banner], tuple[datetime, str] | None]":
    """在开的池子走森空岛（时刻权威），首发/预告走官方版本公告。"""
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

    live = parse_endfield(pools, name_of)
    end = min((b.end for b in live), default=None)

    # 官方公告：这一版有哪些新干员、各在哪个池
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
    except Exception:  # noqa: BLE001
        notice_ok = False
        log.warning("终末地官方公告取不到，这一版分不出首发和复刻", exc_info=True)

    names = {w for w, _ in debut}
    got = [b for b in live if set(b.chars) & names] if notice_ok else live
    if not end or end <= now:
        return got, None

    # 下一期优先用官方公告：开放时刻在未来的那一期（复刻也报，标「复刻」）
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

    # 本版两半都开完了，跨版本的只有一图流那份手工表有
    try:
        table = json.loads(_first(_EF_SCHEDULE, _UA_BROWSER))
    except Exception:  # noqa: BLE001
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
        body = newest_version([(str(n.get("tabTitle") or ""),
                                str(n.get("content") or ""))
                               for n in (notice.get("game") or [])
                               if "版本内容说明" in str(n.get("tabTitle") or "")])
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
    rest = upcoming(debut, live)
    if not rest:
        return got, (end, "")
    who = "、".join(f"{w}「{p}」" if p else w for w, p in rest)
    return got, (end, who)


def collect(now: datetime, *, skland_token: str = "",
            cred=None, sk_get=None
            ) -> "tuple[list[Banner], dict[str, tuple[datetime, str]]]":
    """把三个游戏拉一遍。任何一个取不到就少一条，不影响其余。

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
    rows: list[Banner] = []
    nxt: "dict[str, tuple[datetime, str]]" = {}
    try:
        ak, ak_next = _arknights(now)
        rows += ak
        if ak_next:
            nxt["明日方舟"] = ak_next      # _arknights 已经给的是 (时刻, 是谁)
    except Exception:  # noqa: BLE001
        log.warning("方舟卡池整段失败", exc_info=True)
    if sk_get is not None:
        try:
            ef, ef_next = _endfield(cred, sk_get, now)
            rows += ef
            if ef_next and ef_next[0] > now:
                nxt["终末地"] = ef_next
        except Exception:  # noqa: BLE001
            log.warning("终末地卡池整段失败", exc_info=True)
    try:
        ww, ww_next = _wuwa(now)
        rows += ww
        if ww_next and ww_next[0] > now:
            nxt["鸣潮"] = ww_next
    except Exception:  # noqa: BLE001
        log.warning("鸣潮卡池整段失败", exc_info=True)
    return rows, nxt


def section(now: datetime, **kw) -> str:
    """日报末尾那一段。"""
    rows, nxt = collect(now, **kw)
    return render(rows, now, nxt)


def opening_tomorrow(now: datetime,
                     nxt: "dict[str, tuple[datetime, str]]"
                     ) -> "list[tuple[str, datetime, str]]":
    """明天开的新池子。用户 2026-08-31 定的：只有这种才发到微信群。

    比的是**日期**不是「24 小时内」——日报是晚上发的，21:30 看
    「24 小时内」会把后天早上六点开的池子算进来，那不是明天。
    """
    day = (now + timedelta(days=1)).date()
    return sorted(((g, w, who) for g, (w, who) in nxt.items()
                   if w.date() == day), key=lambda x: x[1])


def group_notice(due: "list[tuple[str, datetime, str]]") -> "tuple[str, str]":
    """发到群里的那条。没有就返回两个空串。"""
    if not due:
        return "", ""
    lines = []
    for game, when, who in due:
        stamp = f"{when:%m-%d}" if (when.hour, when.minute) == (0, 0) \
            else f"{when:%m-%d %H:%M}"
        lines.append(f"· {game}　{stamp} 开" + (f"　{who}" if who else ""))
    what = "、".join(g for g, _, _ in due)
    return f"🎴 明天开新卡池：{what}", "\n".join(lines)
