"""三个游戏的卡池解析。

夹具都是 2026-08-31 从线上抓的真实响应：
* `wuwa_home.json`      —— 库街区 wiki 首页 getPage，裁到「唤取」两个模块
* `wuwa_notice.html`    —— 官方 3.6 版本内容说明，裁到「全新角色/武器」两节
* `prts_limited.wikitext` —— PRTS「卡池一览/限时寻访」全文
* `ak_schedule.js`      —— 一图流手工维护的方舟未来排期（08-31）
* `ef_pool_info_table_2026-10-01.json` —— Yituliu's Endfield pool table
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
   两版都开完时，下一版角色要用 wiki 的「预告」角标报出来，没有就明说官方未公告。
8. (2026-09-30) No guesses: every predicted or worked-out line is gone; all three
   games get a block every day (see _no_guess).
"""
import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ark_relay.banners as _b
from ark_relay.banners import (
    _AK_PAGES, _PRTS, debut_only, parse_ak_schedule, parse_arknights,
    group_notice, newest_version, opening_tomorrow, parse_endfield,
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
    """Arknights: the PRTS banner table."""
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
                 {"鸣潮": (datetime(2026, 9, 10, 10, 0, 0), "景燃「身赴三途」")})
    check("段首写明北京时间", out.startswith("🎴 卡池（时间为北京时间）\n"), True)
    check("三个游戏都有一块，顺序固定",
          [ln for ln in out.split("\n")[1:] if not ln.startswith("·")], ["明日方舟", "鸣潮", "终末地"])
    check("当期结束与下期开始是同一时刻，只写一次「换池」",
          "· 当期：仙风玉影水天清 · 清宵 · 北京 09-10 09:59 换池 · 剩 10 天 9 小时" in out, True)
    check("下期写池名 · 角色，时刻不重复", "· 下期：身赴三途 · 景燃 · 换池时开" in out, True)
    check("复刻不进报告", "达妮娅" in out, False)
    check("没有新角色池的游戏明说", "明日方舟\n· 当期无新角色卡池\n· 下期：官方未公告" in out, True)

    notime = render([], now, {"鸣潮": (None, "锁暝「余心所向九死未悔」")})
    check("公告点了名没给时间：只写名字和「开始时间官方未公布」",
          "· 下期：余心所向九死未悔 · 锁暝 · 开始时间官方未公布" in notime, True)
    check("没给时间就不出日期", bool(re.search(r"鸣潮\n.*\n· 下期：[^\n]*\d\d-\d\d", notime)), False)

    blind = render([], now, {"终末地": (datetime(2026, 9, 2, 6, 0, 0), "")})
    check("没有角色名的不算下一个新角色池", ("终末地\n· 当期无新角色卡池\n· 下期：官方未公告" in blind, "09-02" in blind), (True, False))

    dateonly = render([], now, {"明日方舟": (datetime(2026, 9, 4, 0, 0, 0), "结城理「石白深蓝之夜」")})
    check("只给到日期的源不许凑出 00:00", "00:00" in dateonly, False)
    check("只给到日期时写到日", "· 下期：石白深蓝之夜 · 结城理 · 北京 09-04 开" in dateonly, True)


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

    check("没公布时间的下期不发群", opening_tomorrow(evening, {"鸣潮": (None, "锁暝「余心所向九死未悔」")}), [])
    check("什么都没有也出三块，各写「无」和「官方未公告」",
          render([], datetime(2026, 8, 31, 0, 0, 0), {}),
          "🎴 卡池（时间为北京时间）\n" + "\n".join(
              f"{g}\n· 当期无新角色卡池\n· 下期：官方未公告" for g in ("明日方舟", "鸣潮", "终末地")))


def _yituliu() -> None:
    """2026-10-01 00:03 the user asked whether we looked at the two Yituliu sites
    at all. Both tables are read and recorded; only an Arknights entry marked
    announced may print."""
    sched = parse_ak_schedule((FX / "ak_schedule.js").read_text(encoding="utf-8"))
    check("一图流排期按时间正序，带官宣标记",
          [(n, f"{d:%Y-%m-%d}", ok) for n, d, ok in sched],
          [("P3R联动", "2026-09-04", False), ("感谢庆典", "2026-11-01", False)])
    check("排期是空文本时返回空", parse_ak_schedule(""), [])
    ef_rows = json.loads((FX / "ef_pool_info_table_2026-10-01.json").read_text(encoding="utf-8"))
    ef = _b.parse_ef_yituliu(ef_rows)
    check("终末地一图流最后一条：提弗洛斯 09-02 12:00 ~ 09-30 12:00",
          ef[-1], ("提弗洛斯", "提弗洛斯", datetime(2026, 9, 2, 12, 0), datetime(2026, 9, 30, 12, 0)))

    page = (FX / "prts_limited_page.html").read_text(encoding="utf-8")
    ak_js = (FX / "ak_schedule.js").read_text(encoding="utf-8")
    real_json, real_text = _b._json, _b._text

    def no_api(url, *a, **k):
        raise OSError("offline")

    def run_ak(js):
        def text(url, *a, **k):
            if url.startswith(_b._PRTS_PAGE):
                return page
            if url in _b._AK_SCHEDULE:
                return js
            raise OSError("offline")
        _b._json, _b._text = no_api, text
        try:
            tr = _b.Trace.new()
            _, nxt = _b._arknights(datetime(2026, 9, 20, 12, 0), trace=tr)
        finally:
            _b._json, _b._text = real_json, real_text
        return nxt, tr
    nxt, tr = run_ak(ak_js)
    check("一图流的预测不当下期", nxt, None)
    check("一图流读过、记进来源",
          any("一图流" in x and "感谢庆典 2026-11-01（一图流预测，不写）" in x for x in tr.sources), True)
    out = render([], datetime(2026, 9, 20, 12, 0), {}, trace=tr)
    check("预测不进正文", ("感谢庆典" in out, "11-01" in out), (False, False))
    # without accuracyFlag: false the parser takes the entry as announced
    flagged = re.sub(r'(id: "thanksgiving"[^}]*?)accuracyFlag:\s*false', r"\1", ak_js)
    nxt, tr = run_ak(flagged)
    check("一图流标了已官宣、官网和 PRTS 都没有时才用", nxt, (datetime(2026, 11, 1), "「感谢庆典」"))
    check("只给到日期写到日", "· 下期：感谢庆典 · 北京 11-01 开" in render([], datetime(2026, 9, 20), {"明日方舟": nxt}, trace=tr), True)

    future = [dict(ef_rows[-1], poolName="某池", character="某人",
                   poolStart="2026/10/14 12:00:00", poolEnd="2026/11/04 12:00:00")]

    def ef_text(url, *a, **k):
        if url in _b._EF_YITULIU:
            return json.dumps(ef_rows + future, ensure_ascii=False)
        raise OSError("offline")
    _b._json, _b._text = no_api, ef_text
    try:
        tr = _b.Trace.new()
        got, nxt = _b._endfield(None, lambda path: {"data": {"list": []}}, datetime(2026, 10, 1, 0, 20), trace=tr)
    finally:
        _b._json, _b._text = real_json, real_text
    check("终末地一图流没有官宣标记：有未来条目也不当下期", (got, nxt), ([], None))
    check("终末地一图流记进来源",
          any("终末地｜一图流" in x and "某人「某池」 2026-10-14（一图流预测，不写）" in x for x in tr.sources), True)


def _no_guess() -> None:
    """2026-09-30 用户：「鸣潮当期结尾的「心」，这角色名字就这一个字。除了这一条，其他全部修干净。
    尤其是推测内容，我不希望见到有推测，信息全部都是能查到的。」"""
    now = datetime(2026, 9, 30, 23, 1, 41)
    xin = _b.Banner("鸣潮", "但愿长圆如此夜", ("心",), datetime(2026, 9, 30, 11, 0), datetime(2026, 10, 22, 9, 59, 59))
    out = render([xin], now, {"鸣潮": (None, "锁暝「余心所向九死未悔」")})
    check("单字角色名「心」原样", "· 当期：但愿长圆如此夜 · 心 · 北京 10-22 09:59 结束 · 剩 21 天 10 小时" in out, True)
    check("09-30 那天的整段", out, "\n".join((
        "🎴 卡池（时间为北京时间）",
        "明日方舟", "· 当期无新角色卡池", "· 下期：官方未公告",
        "鸣潮", "· 当期：但愿长圆如此夜 · 心 · 北京 10-22 09:59 结束 · 剩 21 天 10 小时",
        "· 下期：余心所向九死未悔 · 锁暝 · 开始时间官方未公布",
        "终末地", "· 当期无新角色卡池", "· 下期：官方未公告")))
    teased = render([], now, {}, notes={"鸣潮": "官方已预告下一版新角色：心、锁暝 · 3.7 版本更新维护 北京 09-30 04:00～11:00"})
    texts = out + teased + render([], now, {}, failed=["终末地（森空岛登录失败）"])
    for word in ("按规律", "推算", "一图流", "实测", "预测", "结束即开", "维护结束后开", "前瞻", "约"):
        check(f"无公告时不出推测：没有「{word}」", word in texts, False)
    check("官方已公布的预告角色与维护时间照写",
          "· 下期：官方未公告 · 官方已预告下一版新角色：心、锁暝 · 3.7 版本更新维护 北京 09-30 04:00～11:00" in teased, True)

    lost = render([], now, {}, failed=["终末地（森空岛登录失败）"])
    check("没读到的游戏说没读到，不写「无」",
          ("终末地\n· 这次没读到（森空岛登录失败），不是没有卡池" in lost, "终末地\n· 当期无新角色卡池" in lost), (True, False))

    tr = _b.Trace.new()
    out = render([], now, {"明日方舟": (datetime(2026, 10, 9, 16, 0), "某人「某池」")}, trace=tr)
    check("下期时刻没有来源就扣下", ("⚠️ 这一行没通过来源核对" in out, len(tr.withheld)), (True, 1))


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
    both = render(live, now, {"鸣潮": (datetime(2026, 9, 12, 10, 0), "景燃「身赴三途」"),
                              "明日方舟": (datetime(2026, 9, 4, 12, 0, 0), "结城理「石白深蓝之夜」")})
    lines = both.splitlines()
    check("标题", lines[0], "🎴 卡池（时间为北京时间）")
    check("游戏顺序按日报顺序：方舟在前", lines.index("明日方舟") < lines.index("鸣潮"), True)
    check("方舟没有在开的新角色池：写「当期无新角色卡池」",
          lines[lines.index("明日方舟") + 1:lines.index("鸣潮")], ["· 当期无新角色卡池", "· 下期：石白深蓝之夜 · 结城理 · 北京 09-04 12:00 开"])
    check("鸣潮有当期也有下期",
          [ln.split("：")[0] for ln in lines[lines.index("鸣潮") + 1:lines.index("终末地")]], ["· 当期", "· 下期"])
    check("时刻不是同一刻就分开写结束和开", ("北京 09-10 09:59 结束" in both, "北京 09-12 10:00 开" in both), (True, True))


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
    # c. an unannounced next banner: the published facts, never an invented date
    note = {"鸣潮": "官方已预告下一版新角色：心、锁暝"}
    out = render([], now, {"鸣潮": (datetime(2026, 9, 29, 11, 59, 59), "")}, notes=note)
    check("说明行原样、不带日期", ("· 下期：官方未公告 · 官方已预告下一版新角色：心、锁暝" in out, "09-29" in out), (True, False))
    # c2. the official posts, and reruns skipped
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
    # c3. the official site's maintenance notice
    site = json.loads((FX / "wuwa_site_articles_2026-09-12.json").read_text(encoding="utf-8"))
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
    check("有来源当作开始的时刻放行", _b.gate_preview("· 下期：绚丽异彩 · 伊冯 · 北京 09-24 12:00 开", tr), "")
    check("推出来的日期（按规律 / 推算）没有来源类别，一律扣下",
          bool(_b.gate_preview("· 下期：09-16 19:00（版本 09-29 更新前 13 天，按规律）", tr)), True)
    check("没有日期的行放行", _b.gate_preview("· 下期：官方未公告", tr), "")
    out = render([], now, {}, notes={"明日方舟": "09-18 03:59 之后开"}, trace=tr)
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
    check("页脚不再印核对结果（用户 09-14）", "核对　" in out2, False)
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


def _version_day() -> None:
    """Wuthering Waves between versions. The preview-stream line (a stream time from a rule,
    a version day from a banner end) went on 2026-09-30 with every other guess;
    what stays is what the official site posts: the maintenance window."""
    site = _b._WW_SITE_ARTICLES
    art = (FX / "wuwa_site_article_5282.json").read_text(encoding="utf-8")
    art37 = art.replace("2026年8月20日", "2026年9月30日").replace("3.6版本", "3.7版本")
    menu = json.dumps([{"articleId": 5400, "articleTitle": "《鸣潮》3.7版本更新维护预告",
                        "articleType": 52, "startTime": "2026-09-23 11:00:00"}], ensure_ascii=False)
    real_json, real_text = _b._json, _b._text

    def text(url, *a, **k):
        if url == site:
            return menu
        if url.endswith("/5400.json"):
            return art37
        raise OSError("offline")

    def no_json(url, *a, **k):
        raise OSError("offline")
    # a. the wiki homepage unreadable: raise, so the report says "not read", not "none"
    _b._json, _b._text = no_json, text
    try:
        _b._wuwa(datetime(2026, 9, 30, 0, 0), notes={}, trace=_b.Trace.new())
        raised = False
    except OSError:
        raised = True
    finally:
        _b._json, _b._text = real_json, real_text
    check("库街区首页取不到就报错（交给 collect 记「没读到」）", raised, True)
    # b. version eve, both halves done: no banner and no time is claimed; the
    # teased names and the official maintenance window are said as they are
    eve = datetime(2026, 9, 29, 21, 49)
    cat = json.loads((FX / "wuwa_catalogue_2026-09-12.json").read_text(encoding="utf-8"))
    running = [_b.Banner("鸣潮", "当期", ("某人",), datetime(2026, 9, 10, 12, 0), datetime(2026, 9, 30, 4, 0))]
    real_parse = _b.parse_wuwa

    def kuro(url, *a, **k):
        if url.endswith("/wiki/core/catalogue/item/getPage"):
            return cat
        if url.endswith("/wiki/core/homepage/getPage"):
            return {}
        raise OSError("offline")
    _b._json, _b._text, _b.parse_wuwa = kuro, text, (lambda home, name_of: running)
    notes: dict = {}
    tr = _b.Trace.new()
    try:
        _got, nxt = _b._wuwa(eve, notes=notes, trace=tr)
    finally:
        _b._json, _b._text, _b.parse_wuwa = real_json, real_text, real_parse
    check("版本前夜：不编开池时刻", nxt, None)
    check("前夜的说明只有官方公布的事",
          notes.get("鸣潮"), "官方已预告下一版新角色：心、锁暝 · 3.7 版本更新维护 北京 09-30 04:00～11:00")
    check("维护窗口进来源", any("3.7 维护 2026-09-30 04:00~2026-09-30 11:00" in x for x in tr.sources), True)
    out = render([], eve, {}, notes, tr)
    check("说明行过得了来源核对", (tr.withheld, "· 下期：官方未公告 · 官方已预告下一版新角色：心、锁暝" in out), ([], True))


def _prts_page_fallback() -> None:
    """2026-09-26 21:53-23:05: PRTS's API answered 503 while the rendered page came from its CDN."""
    page = (FX / "prts_limited_page.html").read_text(encoding="utf-8")
    rows, rarity = _b.parse_arknights_html(page)
    check("页面解析出 6 行", len(rows), 6)
    check("最新一行和接口原文同形", rows[-1], _b.Banner("明日方舟", "石白深蓝之夜", ("结城理", "埃癸斯", "岳羽由加莉"),
                                                  datetime(2026, 9, 4, 12, 0), datetime(2026, 9, 18, 3, 59)))
    check("星级从头像角标读（0 起算，5 = 六星）", (rarity["结城理"], rarity["埃癸斯"]), (5, 4))
    wt = parse_arknights((FX / "prts_limited.wikitext").read_text(encoding="utf-8"))
    both = {(b.name, b.start) for b in rows} & {(b.name, b.start) for b in wt}
    check("两份都有的池，名字、时间、角色完全一致",
          [b for b in rows if (b.name, b.start) in both], [b for b in wt if (b.name, b.start) in both])
    check("不是卡池表的页面解析出 0 行", _b.parse_arknights_html("<html><tr><td>x</td></tr></html>"), ([], {}))
    real_json, real_text = _b._json, _b._text
    seen = []

    def no_api(url, *a, **k):
        raise OSError("503 Backend fetch failed")

    def text(url, *a, **k):
        seen.append(url)
        if url.startswith(_b._PRTS_PAGE):
            return page
        raise OSError("offline")
    _b._json, _b._text = no_api, text
    saved = dict(_b._rarity_cache)
    _b._rarity_cache.clear()
    try:
        tr = _b.Trace.new()
        debut, _ = _b._arknights(datetime(2026, 9, 10, 12, 0), trace=tr)
    finally:
        _b._json, _b._text = real_json, real_text
        _b._rarity_cache.clear()
        _b._rarity_cache.update(saved)
    cur = [b for b in debut if b.start <= datetime(2026, 9, 10, 12, 0) <= b.end]
    check("接口 503 时改读页面，当期照出、只留六星", [(b.name, b.chars) for b in cur], [("石白深蓝之夜", ("结城理",))])
    check("读了页面", any(u.startswith(_b._PRTS_PAGE) for u in seen), True)
    check("来源记下是读页面", any("改读页面" in x for x in tr.sources), True)


def _sept29() -> None:
    """2026-09-29: the group got 「🎴 明天开新卡池：终末地 · 终末地　09-30 11:59 开」 with no
    name. Both halves of Endfield 1.x had opened, the next debut was not announced,
    and _endfield returned (the running banner's end, "") - measured 10:59 against
    the live Skland pool and the official bulletin: 冬猎 提弗洛斯 ends 09-30 11:59:59.
    """
    evening = datetime(2026, 9, 29, 21, 30)
    live = {"终末地": (datetime(2026, 9, 30, 11, 59, 59), "")}
    check("当期结束、下一版没公告：不进群", opening_tomorrow(evening, live), [])
    check("群里什么都不发", group_notice(opening_tomorrow(evening, live)), ("", ""))
    both = dict(live, 鸣潮=(datetime(2026, 9, 30, 11, 0), "景燃「身赴三途」"))
    due = opening_tomorrow(evening, both)
    check("有首发角色的那条照样发", [g for g, _, _ in due], ["鸣潮"])
    title, body = group_notice(due)
    check("标题只点有名字的游戏", title, "🎴 明天开新卡池：鸣潮")
    check("名字带上", "景燃「身赴三途」" in body, True)

    # Arknights: PRTS lists the next banner before the official post. Its time is
    # accurate; the new six-star must come with it, or the filter above drops it.
    page = (FX / "prts_limited_page.html").read_text(encoding="utf-8")
    real_json, real_text = _b._json, _b._text

    def no_api(url, *a, **k):
        raise OSError("503 Backend fetch failed")

    def text(url, *a, **k):
        if url.startswith(_b._PRTS_PAGE):
            return page
        raise OSError("offline")
    _b._json, _b._text = no_api, text
    saved = dict(_b._rarity_cache)
    _b._rarity_cache.clear()
    try:
        now = datetime(2026, 9, 3, 21, 30)
        _, nxt = _b._arknights(now, trace=_b.Trace.new())
    finally:
        _b._json, _b._text = real_json, real_text
        _b._rarity_cache.clear()
        _b._rarity_cache.update(saved)
    check("PRTS 已列出的下一首发池带六星名", nxt, (datetime(2026, 9, 4, 12, 0), "结城理「石白深蓝之夜」"))
    check("带名的照样进群", [g for g, _, _ in opening_tomorrow(now, {"明日方舟": nxt})], ["明日方舟"])


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
    _no_guess()
    _yituliu()
    _version_day()
    _top_rarity_only()
    _per_game_blocks(pools)
    _sept12()
    _supervision()
    _prts_page_fallback()
    _sept29()
    print("all checks passed" if not FAILED else "FAILED: " + "; ".join(FAILED))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
