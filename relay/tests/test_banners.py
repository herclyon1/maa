"""三个游戏的卡池解析。

夹具都是 2026-08-31 从线上抓的真实响应：
* `wuwa_home.json`      —— 库街区 wiki 首页 getPage，裁到「唤取」两个模块
* `wuwa_notice.html`    —— 官方 3.6 版本内容说明，裁到「全新角色/武器」两节
* `prts_limited.wikitext` —— PRTS「卡池一览/限时寻访」全文
* `ak_schedule.js`      —— 一图流手工维护的方舟未来排期
* `endfield_pools.json`  —— 森空岛 char-pool 的 data.list
* `endfield_notice.html` —— 官方「版本更新说明」，裁到「全新干员」和寻访两节

钉住的都是已经踩过的坑：

1. PRTS 的 URL 少了 `page=`（`[:-6]` 多切了六个字符），请求变成
   `...&format=json卡池一览/限时寻访`，回一页 HTML，方舟那几行从来没出来过。
2. getPage 的 `imgs[1:]` 在所有 tab 里是同一组通用条目，当成角色会每池多三个名字。
3. getPage 分不出首发和复刻——3.6 上半两个池子里清宵是首发、达妮娅是复刻，
   只有官方公告的「全新角色」一节能分。
4. 「联合行动」这类池子里全是老干员，不能算首发。
5. 下一期官方公布了人的时候不许再写「约」和「官方未公布」；
   只给到日期的源不许硬凑出 00:00 冒充精确时刻。
6. 「已公布但不在开」不等于「下一期」——本版上半开完了也满足这个条件，
   照那个判据会把**上一期**当成下一期报出去。公告是按时间顺序列的，
   要取在开的那位**之后**的。
7. (2026-09-12) 库街区词条名带空格（「 景燃」），不 strip 就和公告的「景燃」对不上，
   在开的首发池整行消失；复刻永远不许当「预告」（伊冯的重构寻访曾被报成下一期）；
   一图流的表只有限定池，它的下一条不是「下一池」；两版都开完时，下一版角色要用
   wiki 的「预告」角标报出来，没有就明说还没公告。
"""
import json
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ark_relay.banners as _b
from ark_relay.banners import (
    _AK_PAGES, _PRTS, debut_only, parse_ak_schedule, parse_arknights,
    gh_raw, group_notice, newest_version, opening_tomorrow, parse_endfield,
    parse_endfield_notice, parse_wuwa, parse_wuwa_preview, render, upcoming,
)

FX = Path(__file__).parent / "fixtures"
FAILED: list[str] = []


def check(what, got, want):
    if got != want:
        FAILED.append(f"{what}: 得到 {got!r}，应为 {want!r}")


def _wuwa() -> None:
    """鸣潮：库街区首页 + 官方公告。"""
    home = json.loads((FX / "wuwa_home.json").read_text(encoding="utf-8"))
    notice = (FX / "wuwa_notice.html").read_text(encoding="utf-8")
    names = {"1536353668409655296": "清宵", "1488852222116831232": "达妮娅"}
    pools = parse_wuwa(home, lambda e: names.get(e, ""))

    check("只认角色池，武器池排掉",
          [b.name for b in pools], ["仙风玉影水天清", "予明日以谎言"])
    check("每池只有一个角色（imgs 后几项是共用条目）",
          [b.chars for b in pools], [("清宵",), ("达妮娅",)])
    check("起始时刻按服务器时间原样解析",
          pools[0].start, datetime(2026, 8, 20, 11, 0, 0))
    check("结束时刻补到 59 秒",
          pools[0].end, datetime(2026, 9, 10, 9, 59, 59))

    debut = parse_wuwa_preview(notice)
    check("公告只给全新角色，整版上下半一次给全",
          debut, [("清宵", "仙风玉影水天清"), ("景燃", "身赴三途")])
    check("复刻不在「全新角色」那一节里",
          "达妮娅" in {w for w, _ in debut}, False)
    check("正文取不到时返回空而不是炸", parse_wuwa_preview(""), [])
    check("没有那一节时返回空", parse_wuwa_preview("<p>啥也没有</p>"), [])
    return pools, debut


def _arknights() -> None:
    """明日方舟：PRTS 卡池一览 + 一图流排期。"""
    page = urllib.parse.quote(_AK_PAGES[0])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(_PRTS + page).query)
    check("PRTS 的 URL 必须带 page 参数",
          q.get("page"), ["卡池一览/限时寻访"])
    check("只读限时寻访一页（轮换池那页恒为 0 条且没有首发）",
          len(_AK_PAGES), 1)

    ak = parse_arknights((FX / "prts_limited.wikitext").read_text(encoding="utf-8"))
    check("限时寻访解析条数", len(ak), 163)
    check("最后一条是联合行动23", ak[-1].name, "联合行动23")
    check("联合行动23 在开时收录的是十个老干员", len(ak[-1].chars), 10)

    fresh = debut_only(ak)
    check("联合行动不算首发",
          [b for b in fresh if b.name == "联合行动23"], [])
    check("首发池里没有复刻",
          [b.name for b in fresh if "复刻" in b.name], [])
    check("2026 夏限是首发，且只留新干员",
          next((b.chars for b in fresh
                if b.name == "【限定寻访·夏季】车辙与风的归所"), None),
          ("予愿安洁莉娜", "珊比", "嘉辛塔"))

    sched = parse_ak_schedule((FX / "ak_schedule.js").read_text(encoding="utf-8"))
    check("一图流排期按时间正序",
          [(n, f"{d:%Y-%m-%d}", ok) for n, d, ok in sched],
          [("P3R联动", "2026-09-04", False), ("感谢庆典", "2026-11-01", False)])
    check("排期是空文本时返回空", parse_ak_schedule(""), [])


def _endfield() -> None:
    """终末地：森空岛 char-pool + 官方版本说明。"""
    ef_pools = json.loads((FX / "endfield_pools.json").read_text(encoding="utf-8"))
    ef = parse_endfield(ef_pools, lambda gid: {"1683": "梨诺"}.get(gid, ""))
    check("终末地池名", [b.name for b in ef], ["晨星于此闪耀"])
    check("角色名要按 pcLink 里的 gameEntryId 去查", ef[0].chars, ("梨诺",))
    # Wall clock in the server's zone regardless of where the test runs (from Tokyo the
    # old local conversion read 12:59 for the bulletin's 11:59, 2026-09-12).
    check("起止按北京时间还原（1786248000 = 08-09 12:00，1788300000 = 09-02 06:00）",
          (ef[0].start.strftime("%m-%d %H:%M"), ef[0].end.strftime("%m-%d %H:%M")),
          ("08-09 12:00", "09-02 06:00"))

    not_up = json.loads(json.dumps(ef_pools))
    for c in not_up[0]["chars"]:
        c["dotType"] = "label_type_normal"
    check("不是 UP 的角色不进报告", parse_endfield(not_up, lambda g: "梨诺"), [])

    ef_notice = (FX / "endfield_notice.html").read_text(encoding="utf-8")
    ef_debut = parse_endfield_notice(ef_notice)
    check("官方公告一次给全整版上下半的新干员和池名",
          ef_debut, [("诀", "临渊望北"), ("梨诺", "晨星于此闪耀")])
    check("公告取不到时返回空", parse_endfield_notice(""), [])
    check("没有「全新干员」那一节时返回空",
          parse_endfield_notice("<p>只有更新维护时间</p>"), [])
    return ef_debut


def _next_after_current(debut, ef_debut) -> None:
    """「下一期」只能取在开的那位之后的。"""
    check("本版最后一个在开时，本版没有下一期了",
          upcoming(ef_debut, {"梨诺"}), [])
    check("本版第一个在开时，下一期是第二个",
          upcoming(ef_debut, {"诀"}), [("梨诺", "晨星于此闪耀")])
    check("上半开完了也不许被当成下一期",
          [w for w, _ in upcoming(ef_debut, {"梨诺"})], [])
    check("鸣潮同理：清宵在开，下一期是景燃",
          upcoming(debut, {"清宵", "达妮娅"}), [("景燃", "身赴三途")])
    check("一个都没在开时不猜",
          upcoming(debut, set()), [])


def _render(pools) -> None:
    """渲染成通知里的那几行。"""
    now = datetime(2026, 8, 31, 0, 0, 0)
    live = [b for b in pools if b.chars == ("清宵",)]
    out = render(live, now,
                 {"鸣潮": (datetime(2026, 9, 10, 9, 59, 59), "景燃「身赴三途」")})
    check("在开的首发池要报", "清宵" in out, True)
    check("复刻不进报告", "达妮娅" in out, False)
    check("下一期报出人名", "景燃「身赴三途」" in out, True)
    check("官方公布了人就不写「还没公告」", "还没公告" in out, False)

    blind = render([], now, {"终末地": (datetime(2026, 9, 2, 6, 0, 0), "")})
    check("没公布人时说清是登记了池子、干员名还没公告", "这一池已登记，干员名官方还没公告" in blind, True)
    check("不写「约」「未公布」这种含糊话", "约" in blind or "未公布" in blind, False)
    check("有确切时刻就把时刻写出来", "09-02 06:00" in blind, True)

    dateonly = render([], now, {"明日方舟": (datetime(2026, 9, 4, 0, 0, 0),
                                            "P3R联动（排期是预测，未官宣）")})
    check("只给到日期的源不许凑出 00:00", "00:00" in dateonly, False)
    check("只给到日期时写到日", "09-04 开" in dateonly, True)


def _newest_version() -> None:
    """3.7 发布后 3.6 还挂着，只认版本号大的那条。"""
    check("两版并存时取版本号大的",
          newest_version([("「甲」3.6版本内容说明", "旧"),
                          ("「乙」3.7版本内容说明", "新")]), "新")
    check("顺序反过来结果不变",
          newest_version([("「乙」3.7版本内容说明", "新"),
                          ("「甲」3.6版本内容说明", "旧")]), "新")
    check("跨大版本也要比对(9.9 < 10.0)",
          newest_version([("9.9版本内容说明", "旧"),
                          ("10.0版本内容说明", "新")]), "新")
    check("一条都没有时返回空", newest_version([]), "")

    # Measured 2026-08-31 on the game machine: raw.githubusercontent takes 33 s (times
    # out), jsDelivr 2.8 s. The mirror order follows measured speed; do not revert it.
    mirrors = gh_raw("o", "r", "main", "a/b.js")
    check("jsDelivr 排在最前", "jsdelivr" in mirrors[0], True)
    check("raw.githubusercontent 只做最后兜底",
          mirrors[-1], "https://raw.githubusercontent.com/o/r/main/a/b.js")
    check("每条镜像都指向同一个文件",
          all(m.endswith("a/b.js") for m in mirrors), True)


def _opening_tomorrow() -> None:
    """只有「明天开」的才发群。"""
    # The daily report goes out in the evening. "Within 24 hours" at 21:30 would sweep
    # in a banner opening at six the morning after tomorrow - not tomorrow. So compare dates.
    evening = datetime(2026, 8, 31, 21, 30)
    pool_nxt = {
        "终末地": (datetime(2026, 9, 2, 6, 0), "提弗洛斯"),      # the day after tomorrow: no
        "明日方舟": (datetime(2026, 9, 1, 0, 0), "P3R联动"),      # tomorrow: yes
        "鸣潮": (datetime(2026, 8, 31, 23, 0), "景燃"),          # today: no
    }
    due = opening_tomorrow(evening, pool_nxt)
    check("只留明天开的", [g for g, _, _ in due], ["明日方舟"])
    check("后天开的不算明天",
          "终末地" in {g for g, _, _ in due}, False)
    check("今天开的也不算明天（24 小时内会算错）",
          "鸣潮" in {g for g, _, _ in due}, False)
    check("一个都没有时返回空", opening_tomorrow(evening, {}), [])

    two = opening_tomorrow(evening, {
        "明日方舟": (datetime(2026, 9, 1, 0, 0), "P3R联动"),
        "鸣潮": (datetime(2026, 9, 1, 11, 0), "景燃「身赴三途」")})
    check("同一天两个游戏换池都要留下，按时刻排",
          [g for g, _, _ in two], ["明日方舟", "鸣潮"])

    title, body = group_notice(two)
    check("群通知标题点名是哪几个游戏",
          title, "🎴 明天开新卡池：明日方舟、鸣潮")
    check("只给到日期的不凑 00:00", "00:00" in body, False)
    check("有时刻的写出时刻", "09-01 11:00" in body, True)
    check("人名带上", "景燃「身赴三途」" in body, True)
    check("没有要播的就不发", group_notice([]), ("", ""))

    check("一条都没有时整段为空",
          render([], datetime(2026, 8, 31, 0, 0, 0), {}), "")


def _preview_line() -> None:
    """前瞻行。"""
    from ark_relay import banners as _b  # noqa: PLC0415
    pv = _b.previews(datetime(2026, 9, 3), [], {"终末地": datetime(2026, 9, 30, 11, 59), "鸣潮": datetime(2026, 10, 1, 4, 0)})
    check("终末地前瞻：版本前 12 天 19:00", pv["终末地"].startswith("09-18 19:00"), True)
    check("鸣潮前瞻：版本前 13 天 19:00", pv["鸣潮"].startswith("09-18 19:00"), True)
    pv2 = _b.previews(datetime(2026, 9, 3), [], {"终末地": datetime(2026, 9, 30)}, official={"终末地": (datetime(2026, 9, 19, 19, 0), "「XX」版本前瞻直播")})
    check("官方公布了就用官方的", pv2["终末地"], "09-19 19:00 「XX」版本前瞻直播")
    out3 = render([], datetime(2026, 9, 3), {}, {"鸣潮": "09-18 19:00（…）"})
    check("只有前瞻也出这个游戏的块", "鸣潮\n· 前瞻　09-18 19:00（…）" in out3, True)


def _top_rarity_only() -> None:
    """只报最高稀有度（用户 2026-09-03）。"""
    from ark_relay import banners as _b  # noqa: PLC0415
    notice_html = "<p>■ 全新干员 6星干员【提弗洛斯】、5星干员【噗切娜】 ■ 全新武器 …</p><p>1.「冬猎」特许寻访 · 寻访说明：6星干员【提弗洛斯】获取概率提升</p>"
    check("终末地公告：5 星赠送角色不进首发名单", parse_endfield_notice(notice_html), [("提弗洛斯", "冬猎")])
    import json as _json  # noqa: PLC0415
    full = _json.loads((FX / "ef_bulletin_full_2026-09-03.json").read_text(encoding="utf-8"))
    def _walk(o, acc):
        if isinstance(o, dict):
            if "版本更新说明" in str(o.get("header") or o.get("title") or ""): acc.append(o)
            for v in o.values(): _walk(v, acc)
        elif isinstance(o, list):
            for v in o: _walk(v, acc)
    acc = []; _walk(full, acc)
    ef_html = str(((acc[0].get("data") or {}).get("html")) or acc[0].get("html") or "")
    pools = _b.endfield_pools_from_notice(ef_html)
    check("终末地各期：冬猎提弗洛斯首发、绚丽异彩伊冯复刻 09-24 12:00",
          [(n, p, w.strftime("%m-%d %H:%M") if w else None, d) for n, p, w, d in pools],
          [("提弗洛斯", "冬猎", None, True), ("伊冯", "绚丽异彩", "09-24 12:00", False)])
    ak_list = (FX / "maint" / "ak_news.html").read_text(encoding="utf-8", errors="replace")
    ak_art = (FX / "ak_banner_1457.html").read_text(encoding="utf-8", errors="replace")
    ak_get = lambda u: ak_art if u.endswith("/1457") else ak_list  # noqa: E731
    nxt = _b.arknights_next_from_news(datetime(2026, 9, 3, 0, 0), get=ak_get)
    check("方舟下一期：09-04 12:00 结城理「石白深蓝之夜」", (nxt[0].strftime("%m-%d %H:%M"), nxt[1]) if nxt else None, ("09-04 12:00", "结城理「石白深蓝之夜」"))
    check("已经开了就不当下一期", _b.arknights_next_from_news(datetime(2026, 9, 5, 0, 0), get=ak_get), None)
    fake_prts = lambda n: {"予愿安洁莉娜": "|稀有度=5", "珊比": "|稀有度=5", "嘉辛塔": "|稀有度=4"}.get(n, "")  # noqa: E731
    b6 = _b.Banner("明日方舟", "车辙与风的归所", ("予愿安洁莉娜", "珊比", "嘉辛塔"), datetime(2026, 8, 1), datetime(2026, 8, 15))
    check("方舟池只留六星（PRTS 稀有度 5=六星）", _b.six_star_only(b6, fake_prts).chars, ("予愿安洁莉娜", "珊比"))
    check("稀有度查不到的名字去掉，不冒充", _b.six_star_only(_b.Banner("明日方舟", "x", ("无名",), datetime(2026, 8, 1), datetime(2026, 8, 15)), fake_prts).chars, ())


def _per_game_blocks(pools) -> None:
    """按游戏分块，每家一个样（用户 2026-09-02）。"""
    now = datetime(2026, 8, 31, 0, 0, 0)
    live = [b for b in pools if b.chars == ("清宵",)]
    both = render(live, now, {"鸣潮": (datetime(2026, 9, 10, 9, 59, 59), "景燃「身赴三途」"),
                              "明日方舟": (datetime(2026, 9, 4, 0, 0, 0), "P3R联动（排期是预测，未官宣）")})
    lines = both.splitlines()
    check("标题", lines[0], "🎴 卡池")
    check("游戏顺序按日报顺序：方舟在前", lines.index("明日方舟") < lines.index("鸣潮"), True)
    check("方舟没有在开的 UP 就没有「当期」行",
          any(l.startswith("· 当期") for l in lines[lines.index("明日方舟") + 1:lines.index("鸣潮")]), False)
    check("鸣潮有当期也有预告",
          [l.split("　")[0] for l in lines[lines.index("鸣潮") + 1:]], ["· 当期", "· 预告"])
    check("当期带结束时刻", "（09-10 09:59 结束）" in both, True)


def _ef_bulletin_html() -> str:
    """The 版本更新说明 body inside the full 2026-09-03 bulletin fixture."""
    full = json.loads((FX / "ef_bulletin_full_2026-09-03.json").read_text(encoding="utf-8"))
    acc: list = []
    def walk(o):
        if isinstance(o, dict):
            if "版本更新说明" in str(o.get("header") or o.get("title") or ""):
                acc.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(full)
    return str(((acc[0].get("data") or {}).get("html")) or acc[0].get("html") or "") if acc else ""


def _sept12() -> None:
    """The four things wrong in the 2026-09-12 report, one check each."""
    now = datetime(2026, 9, 12, 12, 0)
    # a. leading space in the wiki entry name
    home = json.loads((FX / "wuwa_home.json").read_text(encoding="utf-8"))
    entry = json.loads((FX / "wuwa_entry_jingran.json").read_text(encoding="utf-8"))
    got = parse_wuwa(home, lambda e: entry["data"]["name"])
    check("词条名带空格也要对上", all(b.chars == ("景燃",) for b in got) and bool(got), True)
    # b. the teaser badge on the wiki catalogue
    cat = json.loads((FX / "wuwa_catalogue_2026-09-12.json").read_text(encoding="utf-8"))
    recs = cat["data"]["results"]["records"]
    check("wiki 预告角标 = 心、锁暝", _b.wuwa_teased(recs, now), ["心", "锁暝"])
    check("角标过期的不算（赞妮 2026-04-29 到期）", "赞妮" in _b.wuwa_teased(recs, datetime(2026, 5, 1)), False)
    check("在开的「新」和「复刻」都不是预告", any(n in _b.wuwa_teased(recs, now) for n in ("景燃", "绯雪", "莫宁")), False)
    # c. an unannounced next banner is a note, never an invented date
    note = {"鸣潮": "09-29 版本更新后开（还有 16 天）　下一版新角色官方已预告：心、锁暝"}
    out = render([], now, {"鸣潮": (datetime(2026, 9, 29, 11, 59, 59), "")}, notes=note)
    check("有说明时用说明行，不用「约…开 UP 是谁官方未公布」", "官方未公布" in out or "约 " in out, False)
    check("说明行原样", "· 预告　09-29 版本更新后开（还有 16 天）　下一版新角色官方已预告：心、锁暝" in out, True)
    ak_note = {"明日方舟": "下一池官方还没公告，官方开池前 6～7 天公告（上 2 池实测：提前 6 天、提前 7 天）；远期 11-01 感谢庆典（一图流预测，未官宣）"}
    out = render([], now, {}, notes=ak_note)
    check("方舟没公告时不给任何日期（09-18 那种「之后开」是编的）", "09-18" in out or "之后开" in out, False)
    check("方舟没公告的说明行出现", "· 预告　下一池官方还没公告，官方开池前 6～7 天公告" in out, True)
    # c2. the lead of the official posts, and reruns skipped
    ak_list2 = (FX / "ak_news_list_2026-09-12.txt").read_text(encoding="utf-8")
    arts = {"1457": (FX / "ak_banner_1457.html").read_text(encoding="utf-8", errors="replace"),
            "6247": (FX / "ak_banner_6247.html").read_text(encoding="utf-8", errors="replace")}
    calls: list[str] = []
    def ak_get2(url):
        calls.append(url)
        cid = url.rsplit("/", 1)[-1]
        return arts.get(cid, "") if cid != "news?page=2" and cid != "news" else ak_list2
    posts = _b.arknights_banner_posts(now, get=ak_get2)
    check("近两条首发寻访公告：09-04 和 08-01，各自的发布日和结束",
          [(st.strftime("%m-%d"), po.strftime("%m-%d"), en.strftime("%m-%d %H:%M")) for st, _, po, en, _c in posts],
          [("09-04", "08-29", "09-18 03:59"), ("08-01", "07-25", "08-15 03:59")])
    check("复刻寻访（砺火成锋 8588）不算", any(u.endswith("/8588") for u in calls), False)
    check("公告提前量文案（实测数字，不写「约一周」）", _b.announce_lead(posts), "官方开池前 6～7 天公告（上 2 池实测：提前 6 天、提前 7 天）")
    # c3. the official site's combat demos say who of the teased pair comes first
    site = json.loads((FX / "wuwa_site_articles_2026-09-12.json").read_text(encoding="utf-8"))
    check("09-12 还没有心/锁暝的演示", _b.wuwa_demo_note(site, ["心", "锁暝"], now), "")
    check("3.6 的两人：清宵 08-17 先、景燃 09-06 后（顺序 = 池子顺序）",
          _b.wuwa_demo_note(site, ["清宵", "景燃"], datetime(2026, 9, 7)), "官网已发「清宵」的战斗演示（08-17）、「景燃」的战斗演示（09-06）")
    check("还没到发布时间的不算", _b.wuwa_demo_note(site, ["景燃"], datetime(2026, 9, 1)), "")
    art5282 = (FX / "wuwa_site_article_5282.json").read_text(encoding="utf-8")
    mt = _b.wuwa_maintenance(site, datetime(2026, 8, 15), get=lambda u: art5282 if u.endswith("/5282.json") else "{}")
    check("官网维护预告：3.6 维护 08-20 04:00~11:00", (mt[0], mt[1].strftime("%m-%d %H:%M"), mt[2].strftime("%m-%d %H:%M")) if mt else None, ("3.6", "08-20 04:00", "08-20 11:00"))
    check("维护已经过去就不算下一版", _b.wuwa_maintenance(site, now, get=lambda u: art5282), None)


def _supervision() -> None:
    """The user, 2026-09-12: 「你对卡池信息这一块没有监管工具防止你瞎编或者数据出错吗？」"""
    now = datetime(2026, 9, 12, 12, 0)
    # 1. the date gate: an end dressed up as a start is withheld
    tr = _b.Trace.new()
    tr.ends |= {"09-18", "09-18 03:59"}
    check("「09-18 03:59 之后开」被扣下", bool(_b.gate_preview("· 预告　09-18 03:59 之后开（还有 5 天）　下一池官方还没公告", tr)), True)
    check("说了「结束」的当期结束时刻放行", _b.gate_preview("· 预告　当期 09-18 03:59 结束（还有 5 天）　下一池官方还没公告", tr), "")
    tr.starts |= {"09-24", "09-24 12:00"}
    check("有来源当作开始的时刻放行", _b.gate_preview("· 预告　09-24 12:00 开（还有 12 天）　伊冯「绚丽异彩」", tr), "")
    check("按规律的前瞻日期要在规律集合里", bool(_b.gate_preview("· 预告　09-16 19:00（版本 09-29 更新前 13 天，按规律）", tr)), True)
    tr.rule |= {"09-16 19:00", "09-16", "09-29", "09-29 11:59"}
    check("登记后放行", _b.gate_preview("· 预告　09-16 19:00（版本 09-29 更新前 13 天，按规律）", tr), "")
    check("没有日期的说明行放行", _b.gate_preview("· 预告　下一池官方还没公告，官方惯例开池前约一周公告", tr), "")
    out = render([], now, {}, notes={"明日方舟": "09-18 03:59 之后开（还有 5 天）　下一池官方还没公告"}, trace=tr)
    check("render 扣下并标注", "已扣下" in out and "09-18" not in out, True)
    check("扣下的原文进 trace", len(tr.withheld), 1)
    # 2. cross-checks between two official sources
    a = _b.Banner("明日方舟", "石白深蓝之夜", ("结城理",), datetime(2026, 9, 4, 12, 0), datetime(2026, 9, 18, 3, 59))
    check("两源一致 ✓", _b.crosscheck("明日方舟", "PRTS", a, "官网公告", a), "明日方舟：PRTS=官网公告 ✓")
    b = _b.Banner("明日方舟", "石白深蓝之夜", ("结城理",), datetime(2026, 9, 4, 12, 0), datetime(2026, 9, 19, 3, 59))
    check("结束对不上要点名", "结束 PRTS 09-18 03:59 / 官网公告 09-19 03:59" in _b.crosscheck("明日方舟", "PRTS", a, "官网公告", b), True)
    check("第二源没有这个池 ✗", _b.crosscheck("明日方舟", "PRTS", a, "官网公告", None).endswith("找不到 ✗"), True)
    c = _b.Banner("鸣潮", "身赴三途", ("景燃",), datetime(2026, 9, 10, 10, 0), datetime(2026, 9, 29, 11, 59, 59))
    d = _b.Banner("鸣潮", "身赴三途", ("景燃",), datetime(2026, 9, 10), datetime(2026, 9, 29, 11, 59, 59))
    check("一边只有日期时按日比", _b.crosscheck("鸣潮", "库街区", c, "游戏公告", d), "鸣潮：库街区=游戏公告 ✓")
    e1 = _b.Banner("终末地", "冬猎", ("提弗洛斯",), datetime(2026, 9, 2, 11, 30), datetime(2026, 9, 30, 11, 59, 59))
    e2 = _b.Banner("终末地", "冬猎", ("提弗洛斯",), datetime(2026, 9, 2, 11, 30), datetime(2026, 9, 30, 11, 59))
    check("秒不算差异（森空岛 11:59:59 / 公告 11:59）", _b.crosscheck("终末地", "森空岛", e1, "公告", e2), "终末地：森空岛=公告 ✓")
    # 3. the second 鸣潮 source: the in-game notice's own banner posts
    notice = json.loads((FX / "wuwa_notice_recommend_2026-09-12.json").read_text(encoding="utf-8"))
    nb = _b.parse_wuwa_notice_banners(notice)
    check("游戏公告里的当期池：身赴三途 景燃 09-10 10:00 ~ 09-29 11:59",
          [(x.name, x.chars, x.start.strftime("%m-%d %H:%M"), x.end.strftime("%m-%d %H:%M")) for x in nb if x.name == "身赴三途"],
          [("身赴三途", ("景燃",), "09-10 10:00", "09-29 11:59")])
    check("库街区和游戏公告对得上", _b.crosscheck("鸣潮", "库街区", c, "游戏公告", next(x for x in nb if x.name == "身赴三途")), "鸣潮：库街区=游戏公告 ✓")
    # 4. the second 终末地 source: the bulletin's closing times
    ends = _b.endfield_pool_ends(_ef_bulletin_html())
    check("公告里冬猎 09-30 11:59 结束；绚丽异彩「版本更新维护前」没有钟点所以不在", 
          {k: v.strftime("%m-%d %H:%M") for k, v in ends.items()}, {("提弗洛斯", "冬猎"): "09-30 11:59"})
    # 5. the footer
    tr2 = _b.Trace.new(); tr2.checks.append("鸣潮：库街区=游戏公告 ✓")
    out2 = render([c], now, {}, trace=tr2)
    check("页脚列出核对结果", out2.splitlines()[-1], "核对　鸣潮：库街区=游戏公告 ✓")
    # 6. the trace file: one per day next to the state, sources and checks inside
    import sys as _sys  # noqa: PLC0415
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import tmpdir  # noqa: PLC0415
    sd = tmpdir()
    tr2.src("鸣潮", "当期", "库街区", "身赴三途 景燃")
    _b.save_trace(sd, now, out2, tr2)
    saved = json.loads((sd / "banners" / "2026-09-12.json").read_text(encoding="utf-8"))
    check("来源落盘", saved["sources"], ["鸣潮｜当期｜库街区｜身赴三途 景燃"])
    check("核对和正文一起落盘", (saved["checks"], saved["text"] == out2), (["鸣潮：库街区=游戏公告 ✓"], True))
    _b.save_trace(Path("/nonexistent/x"), now, out2, tr2)   # unwritable: logs, never raises
    # d. Endfield: the official site's banner notice; "after the version update" resolved by the maintenance window
    news = (FX / "ef_news_2026-09-12.txt").read_text(encoding="utf-8")
    arts = {"6097": (FX / "ef_news_6097.txt").read_text(encoding="utf-8"),
            "1164": (FX / "ef_news_1164.txt").read_text(encoding="utf-8")}
    def ef_get(url):
        cid = url.rsplit("/", 1)[-1]
        return arts.get(cid, news) if cid != "news" else news
    nxt = _b.endfield_next_from_news(datetime(2026, 9, 1, 20, 0), get=ef_get)
    check("终末地官网：冬猎 提弗洛斯，版本开启后 = 维护结束 09-02 12:00",
          (nxt[0].strftime("%m-%d %H:%M"), nxt[1]) if nxt else None, ("09-02 12:00", "提弗洛斯「冬猎」"))
    check("已经开了的不再是下一期", _b.endfield_next_from_news(now, get=ef_get), None)
    # e. Endfield reruns never become the preview
    pools = _b.endfield_pools_from_notice(_ef_bulletin_html())
    reruns = [(n, p) for n, p, w, d in pools if not d]
    check("公告里确实有复刻池（伊冯）作为反例", ("伊冯", "绚丽异彩") in reruns, True)
    future = [(n, p, w, d) for n, p, w, d in pools if w and w > now and d]
    check("复刻不许成为下一期：09-12 之后只剩伊冯，首发筛选后为空", future, [])
    # f. WuWa version end comes from the running banner, not +42 days
    live = [_b.Banner("鸣潮", "身赴三途", ("景燃",), datetime(2026, 9, 10, 10, 0), datetime(2026, 9, 29, 11, 59, 59))]
    check("鸣潮版本结束 = 在开池子的结束", _b.version_ends(now, live).get("鸣潮"), datetime(2026, 9, 29, 11, 59, 59))
    pv = _b.previews(now, live, _b.version_ends(now, live))
    check("前瞻按规律从真实版本结束倒推", pv.get("鸣潮"), "09-16 19:00（版本 09-29 更新前 13 天，按规律）")


def main() -> int:
    # One function per section. This used to be a 215-line main: when a check went
    # red you had to count line numbers to tell which game's section it was in.
    pools, debut = _wuwa()
    _arknights()
    ef_debut = _endfield()
    _next_after_current(debut, ef_debut)
    _render(pools)
    _newest_version()
    _opening_tomorrow()
    _preview_line()
    _top_rarity_only()
    _per_game_blocks(pools)
    _sept12()
    _supervision()
    print("all checks passed" if not FAILED else "FAILED: " + "; ".join(FAILED))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
