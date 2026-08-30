"""三个游戏的「新角色卡池」倒计时与下一期时间。

**只报全新角色首发的池子**——复刻、常驻、中坚轮换一律不报。
用户 2026-08-30 原话：「我有且只要全新角色的卡池信息，其他的不要，
因为我都有老角色了。」

## 数据源（2026-08-30 逐个实测，全部走官方）

| 游戏 | 来源 | 拿到什么 |
|------|------|---------|
| 鸣潮 | 库街区 `api.kurobbs.com/aki/eventCalendar/summon` | 池子名、五星 UP（中文名）、剩余毫秒 |
| 终末地 | 森空岛 `zonai.skland.com/web/v1/wiki/char-pool` | 池子名、起止时间戳；角色名要再查 `item/info` |
| 明日方舟 | PRTS `卡池一览/限时寻访` + `常驻标准寻访` | 池子名、UP 干员、精确起止 |

**为什么必须走官方而不是 Fandom**：2026-08-30 实测，同一时刻
Fandom（国际服）给的是「False Promise for Tomorrow / Denia」，
而库街区（国服）给的是「予明日以谎言 / 达妮娅」。
名字和角色都对不上，服务器进度也不同步。用 Fandom 会报错东西。

## 下一期时间

官方接口都不给「下一期是谁」，但给得出**什么时候开**：

* 鸣潮 / 终末地：本期结束即下期开始（这两家是连轴换的）
* 明日方舟：`gacha_table.json` 随客户端更新推送，里面**已经有未来的池子**

所以「下一期开始时间」是推出来的，不是官宣的——渲染时要说清楚这一点，
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


# ── 鸣潮：库街区官方 ────────────────────────────────────────────
# summon 返回 {"summonRoleEvents":[{title, state, leftTimestamp,
#   roleList:[{name, starLevel}]}], "summonWeaponEvents":[...]}。
# 只要角色池、只要五星 UP；武器池不报。
# state=2 是进行中；没有结束时间字段，用 leftTimestamp 从 now 推。
def parse_wuwa(data: dict, now: datetime) -> list[Banner]:
    out: list[Banner] = []
    for e in (data or {}).get("summonRoleEvents") or []:
        left = e.get("leftTimestamp")
        if not isinstance(left, int):
            continue
        five = tuple(r["name"] for r in (e.get("roleList") or [])
                     if r.get("starLevel") == 5 and r.get("name"))
        if not five:
            continue
        end = now + timedelta(milliseconds=left)
        out.append(Banner("鸣潮", str(e.get("title") or ""), five, now, end))
    out.sort(key=lambda x: x.end)
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
           next_starts: "dict[str, datetime] | None" = None) -> str:
    """渲染成日报末尾的几行。

    `next_starts` 是各游戏下一期的**推算**开始时刻——官方没公布是谁，
    只知道什么时候换，所以措辞必须是「约」，不能写成官宣。
    """
    lines: list[str] = []
    for b in sorted((x for x in banners if x.start <= now <= x.end),
                    key=lambda x: x.end):
        d = b.end - now
        lines.append(f"· {b.game}「{b.name}」{' · '.join(b.chars)}"
                     f"　剩 {d.days} 天 {d.seconds // 3600} 小时")
    for game, when in sorted((next_starts or {}).items(), key=lambda kv: kv[1]):
        if when <= now:
            continue
        d = when - now
        lines.append(f"· {game} 下一期约 {when:%m-%d %H:%M} 换"
                     f"（还有 {d.days} 天，UP 是谁官方未公布）")
    return "🎴 新角色卡池\n" + "\n".join(lines) if lines else ""


# ── 汇总：三个源拉一遍，渲染成日报末尾那一段 ──────────────────
_PRTS = "https://prts.wiki/api.php?" + urllib.parse.urlencode(
    {"action": "parse", "prop": "wikitext", "format": "json", "page": ""})[:-6]
_AK_PAGES = ("卡池一览/限时寻访", "卡池一览/常驻标准寻访/2026")
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


def _arknights(now: datetime) -> "tuple[list[Banner], datetime | None]":
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
    nxt = min((b.start for b in rows if b.start > now), default=None)
    return debut, nxt


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


def _wuwa(token: str, now: datetime) -> "tuple[list[Banner], datetime | None]":
    h = {"token": token, "source": "h5", "devcode": "",
         "Content-Type": "application/x-www-form-urlencoded"}
    def post(path, payload):
        return _json(_KURO + path, _UA_BROWSER,
                     urllib.parse.urlencode(payload).encode(), h)
    try:
        role = post("/user/role/findRoleList", {"gameId": 3})["data"][0]
        d = post("/aki/eventCalendar/summon",
                 {"gameId": 3, "roleId": role["roleId"],
                  "serverId": role["serverId"]})["data"]
    except Exception:  # noqa: BLE001
        log.warning("库街区卡池取不到", exc_info=True)
        return [], None
    got = parse_wuwa(d, now)
    return got, (min((b.end for b in got), default=None))


def section(now: datetime, *, cred=None, sk_get=None,
            kuro_token: str = "") -> str:
    """日报末尾那一段。任何一个游戏取不到就少一行，不影响其余。

    `cred`/`sk_get` 由 engine 注入（森空岛签名链路在 skland.py，
    不在这里重造）；`kuro_token` 来自 .env 的 KUROBBS_TOKEN。
    """
    banners: list[Banner] = []
    nxt: dict[str, datetime] = {}
    try:
        ak, ak_next = _arknights(now)
        banners += ak
        if ak_next:
            nxt["明日方舟"] = ak_next
    except Exception:  # noqa: BLE001
        log.warning("方舟卡池整段失败", exc_info=True)
    if sk_get is not None:
        ef, ef_next = _endfield(cred, sk_get)
        banners += ef
        if ef_next and ef_next > now:
            nxt["终末地"] = ef_next
    if kuro_token:
        ww, ww_next = _wuwa(kuro_token, now)
        banners += ww
        if ww_next and ww_next > now:
            nxt["鸣潮"] = ww_next
    return render(banners, now, nxt)
