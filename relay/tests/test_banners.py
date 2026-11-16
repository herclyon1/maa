"""Arknights, Endfield, and WuWa banner/calendar parsers, Skland client, and need-table builder."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


def _part_banners():  # noqa: C901
    import json
    import logging
    import re
    import sys
    import urllib.parse
    from contextlib import contextmanager
    from datetime import datetime, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import fx_dir

    import ark_relay.features.banners as _b
    from ark_relay.features.banners import _AK_PAGES, _PRTS, debut_only, parse_ak_schedule, parse_arknights, group_notice, newest_version, opening_tomorrow, parse_endfield, parse_endfield_notice, parse_wuwa, parse_wuwa_preview, render, upcoming

    FX = fx_dir(Path(__file__), "fixtures")
    FAILED: list[str] = []


    def check(what, got, want):
        if got != want:
            FAILED.append(f"{what}: 得到 {got!r}，应为 {want!r}")


    @contextmanager
    def _logs():
        """The banners module's log records while the block runs."""
        recs: list = []
        grab = logging.Handler(logging.DEBUG)
        grab.emit = recs.append
        old = _b.log.level
        _b.log.addHandler(grab)
        _b.log.setLevel(logging.DEBUG)
        try:
            yield recs
        finally:
            _b.log.removeHandler(grab)
            _b.log.setLevel(old)


    def _warned(recs: list, part: str) -> int:
        """How many WARNINGs (each one a group message) carry `part`."""
        return sum(1 for r in recs if r.levelno == logging.WARNING and part in r.getMessage())


    # The Arknights official site as the relay reads it since 2026-10-07: the list
    # endpoint (one tab, 6 a page, newest first) and the bulletin backend's posts.
    # The /news pages recorded earlier give the lists: their items carry the tab
    # (tab 0 = 公告 announcements, 1 = 活动 events, 2 = 新闻 news).
    _AK_ITEM_TAB = re.compile(r'\\"cid\\":\\"(\d+)\\",\\"tab\\":\\"(\w+)\\",\\"sticky\\":(?:true|false),'
                          r'\\"title\\":\\"([^"\\]+)\\",\\"author\\":\\"[^"\\]*\\",\\"displayTime\\":(\d+)')
    _AK_TAB = {"0": "ANNOUNCEMENT", "1": "ACTIVITY", "2": "NEWS"}


    def ak_lists(page: str) -> dict:
        """{category: [(cid, title, displayTime)]} newest first, off a recorded /news page."""
        out: dict = {}
        seen = set()
        for cid, tab, title, ts in _AK_ITEM_TAB.findall(page):
            if cid not in seen:
                seen.add(cid)
                out.setdefault(_AK_TAB.get(tab, tab), []).append((cid, title, int(ts)))
        return {k: sorted(v, key=lambda it: -it[2]) for k, v in out.items()}


    def ak_cms(html_body: str) -> str:
        """A bulletin-backend reply carrying `html_body` as the post."""
        return json.dumps({"code": 0, "data": {"data": html_body}}, ensure_ascii=False)


    def ak_post_fx(cid: str) -> str:
        """The bulletin-backend reply for `cid`, recorded 2026-10-07."""
        return (FX / f"ak-post-{cid}.json").read_text(encoding="utf-8")


    def ak_site(lists: dict, posts: dict, calls: "list | None" = None):
        """A fake `get`: lists {category: [(cid, title, ts)]}, posts {cid: backend reply};
    a post not given is an empty one. Anything else raises."""
        def get(u):
            if calls is not None:
                calls.append(u)
            if u.startswith("https://ak.hypergryph.com/api/news?"):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
                items, n = lists.get(q["category"][0], []), int(q["page"][0])
                chunk = items[(n - 1) * 6:n * 6]
                return json.dumps({"code": 0, "data": {
                    "list": [{"cid": c, "title": t, "displayTime": ts} for c, t, ts in chunk],
                    "end": n * 6 >= len(items)}}, ensure_ascii=False)
            m = re.match(r"https://web-news\.hypergryph\.com/api/bulletin/(\w+)\?.*code=arknights$", u)
            if m:
                return posts.get(m.group(1)) or ak_cms("")
            raise OSError(f"offline: {u}")
        return get


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
        # 164 since 2026-10-06: the row 「雪融之诺 复刻」 writes 「2022-12-1 16:00」 and was dropped before
        check("限时寻访解析条数", len(ak), 164)
        check("一位数的日子也读（2022-12-1 16:00）",
              [(b.start, b.end) for b in ak if b.name == "雪融之诺 复刻"],
              [(datetime(2022, 12, 1, 16, 0), datetime(2022, 12, 15, 3, 59))])
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
        """Rendered as the lines of the notification."""
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
        """Only a banner opening tomorrow (「明天开」) goes to the group."""
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
        import logging
        levels: list[int] = []
        grab = logging.Handler()
        grab.emit = lambda r: levels.append(r.levelno) if "没通过来源核对" in r.getMessage() else None
        _b.log.addHandler(grab)
        try:
            out = render([], now, {"明日方舟": (datetime(2026, 10, 9, 16, 0), "某人「某池」")}, trace=tr)
        finally:
            _b.log.removeHandler(grab)
        check("下期时刻没有来源就扣下", ("⚠️ 这一行没通过来源核对" in out, len(tr.withheld)), (True, 1))
        # 09-26 21:46:53: as an ERROR this rang the group (errwatch) for one line of the report.
        check("held back as a WARNING, not an ERROR", levels, [logging.WARNING])


    def _top_rarity_only() -> None:
        """只报最高稀有度（用户 2026-09-03）。"""
        from ark_relay.features import banners as _b
        notice_html = "<p>■ 全新干员 6星干员【提弗洛斯】、5星干员【噗切娜】 ■ 全新武器 …</p><p>1.「冬猎」特许寻访 · 寻访说明：6星干员【提弗洛斯】获取概率提升</p>"
        check("终末地公告：5 星赠送角色不进首发名单", parse_endfield_notice(notice_html), [("提弗洛斯", "冬猎")])
        import json as _json
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
        ak_get = ak_site(ak_lists(ak_list), {"1457": ak_post_fx("1457")})
        nxt = _ak_next(datetime(2026, 9, 3, 0, 0), get=ak_get)
        check("方舟下一期：09-04 12:00 结城理「石白深蓝之夜」", (nxt[0].strftime("%m-%d %H:%M"), nxt[1]) if nxt else None, ("09-04 12:00", "结城理「石白深蓝之夜」"))
        check("已经开了就不当下一期", _ak_next(datetime(2026, 9, 5, 0, 0), get=ak_get), None)
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
        calls: list[str] = []
        ak_get2 = ak_site(ak_lists(ak_list2), {"1457": ak_post_fx("1457"), "6247": ak_post_fx("6247")}, calls)
        posts = _b.arknights_banner_posts(now, get=ak_get2)
        check("近两条首发寻访公告：09-04 和 08-01，各自的发布日和结束",
              [(st.strftime("%m-%d"), po.strftime("%m-%d"), en.strftime("%m-%d %H:%M")) for st, _, po, en, _c in posts],
              [("09-04", "08-29", "09-18 03:59"), ("08-01", "07-25", "08-15 03:59")])
        check("复刻寻访（砺火成锋 8588）不算", any("/bulletin/8588?" in u for u in calls), False)
        check("只读活动页的列表（接口），两页为限", sorted({u for u in calls if "/api/news" in u}),
              [_b._AK_NEWS_API.format(cat="ACTIVITY", page=1), _b._AK_NEWS_API.format(cat="ACTIVITY", page=2)])
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
        # 3.7's first half opens with the version: 「活动时间✦ 3.7版本更新后 ~ 2026年10月22日09:59」
        nb37 = _b.parse_wuwa_notice_banners(json.loads((FX / "wuwa_notice_recommend_2026-10-01.json").read_text(encoding="utf-8")))
        check("开始写「3.7版本更新后」的公告也读得出（开始留空，结束 10-22 09:59）",
              [(x.name, x.chars, x.start, x.start_note, x.end.strftime("%m-%d %H:%M")) for x in nb37],
              [("但愿长圆如此夜", ("心",), None, "3.7版本更新后", "10-22 09:59")])
        xin = _b.Banner("鸣潮", "但愿长圆如此夜", ("心",), datetime(2026, 9, 30, 11, 0), datetime(2026, 10, 22, 9, 59, 59))
        check("这种公告只核结束，并说明", _b.crosscheck("鸣潮", "库街区", xin, "游戏公告", nb37[0]),
              "鸣潮：库街区=游戏公告 ✓（游戏公告开始写「3.7版本更新后」，只核了结束）")
        late = _b.Banner("鸣潮", "但愿长圆如此夜", ("心",), datetime(2026, 9, 30, 11, 0), datetime(2026, 10, 23, 9, 59, 59))
        check("结束对不上照样 ✗", _b.crosscheck("鸣潮", "库街区", late, "游戏公告", nb37[0]).endswith("）") and
              "✗" in _b.crosscheck("鸣潮", "库街区", late, "游戏公告", nb37[0]), True)
        # 4. the second 终末地 source: the bulletin's closing times
        ends = _b.endfield_pool_ends(_ef_bulletin_html())
        check("公告里冬猎 09-30 11:59 结束；绚丽异彩「版本更新维护前」没有钟点所以不在", 
              {k: v.strftime("%m-%d %H:%M") for k, v in ends.items()}, {("提弗洛斯", "冬猎"): "09-30 11:59"})
        # 5. the footer
        tr2 = _b.Trace.new(); tr2.checks.append("鸣潮：库街区=游戏公告 ✓")
        out2 = render([c], now, {}, trace=tr2)
        check("页脚不再印核对结果（用户 09-14）", "核对　" in out2, False)
        # 6. the trace file: one per day next to the state, sources and checks inside
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _tmp import tmpdir
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


    def _ak_history() -> None:
        """Asked for by the user on 2026-10-06 at 18:5x, for the running banner and
    every past one alike, in his words: 「本期及之前的都必须适配」.

    Every sample below is a real official post (cut to the page's own article
    HTML) or a real page of the site's list endpoint. Each one pins a wording
    the reader met when replayed over all 239 ACTIVITY posts (2019-05 to
    2026-10): a banner as a section of an event post (5101 - the reader read
    titles only and missed every regular banner), 「[限定] \\」 between names
    (6247), two banners in one post (2019084798), a rerun section (2021079658),
    the year written in the span (2021120792), 「版本更新后」 with no clock (6262),
    and the 2019 「限时卡池【…】开启」 / 「上午10:00」 / no colon (201905517).
    """
        fx = lambda n: (FX / n).read_text(encoding="utf-8")  # noqa: E731
        page_items = {n: json.loads(fx(f"ak-history-news-p{n}.json"))["data"]["list"] for n in (1, 7, 28, 29, 39, 40)}
        meta = {it["cid"]: it for items in page_items.values() for it in items}
        arts = {c: fx(f"ak-history-{c}.html") for c in
                ("5101", "1455", "9681", "9605", "6262", "2830", "2021079658", "2021120792", "2019084798", "201905517")}
        arts["1457"] = (FX / "ak_banner_1457.html").read_text(encoding="utf-8", errors="replace")
        arts["6247"] = (FX / "ak_banner_6247.html").read_text(encoding="utf-8", errors="replace")
        # The same posts from the bulletin backend (what the relay reads since 2026-10-07)
        cms = {c: ak_post_fx(c) for c in arts}

        def read(cid, text):
            it = meta[cid]
            return [(s.name, s.chars, s.start, s.end, s.rerun, s.start_note) for s in _b.parse_ak_post(
                it["title"], text, _b._ak_posted(it["displayTime"]))]

        def sections(cid):
            return read(cid, _b.ak_post_text(lambda u: cms[cid], cid))
        D = datetime
        want = {
            "5101": [("海渊巡游", ("克莱门莎",), D(2026, 10, 9, 12, 0), D(2026, 10, 23, 3, 59), False, "")],
            "1455": [],      # 定向甄选: six-stars to pick from, no UP one
            "9681": [("石白深蓝之夜", ("结城理",), D(2026, 9, 4, 12, 0), D(2026, 9, 18, 3, 59), False, "")],
            "9605": [("现实之上六百米", ("娜斯提",), D(2025, 12, 5, 12, 0), D(2025, 12, 19, 3, 59), False, "")],
            "6262": [("以风雪为誓", ("凛御银灰", "圣聆初雪"), D(2025, 11, 1), D(2025, 11, 15, 3, 59), False, "版本更新后")],
            "2830": [("以风雪为誓", ("凛御银灰", "圣聆初雪"), D(2025, 11, 1), D(2025, 11, 15, 3, 59), False, "版本更新后")],
            "2021079658": [("盛夏新星", ("假日威龙陈", "水月"), D(2021, 8, 3, 16, 0), D(2021, 8, 17, 3, 59), False, ""),
                           ("不羁逆流", ("棘刺",), D(2021, 8, 26, 16, 0), D(2021, 9, 9, 3, 59), True, "")],
            "2021120792": [("雪融之诺", ("灵知",), D(2021, 12, 21, 16, 0), D(2022, 1, 4, 3, 59), False, "")],
            "2019084798": [("深夏的守夜人", ("黑",), D(2019, 8, 27, 16, 0), D(2019, 9, 10, 3, 59), False, ""),
                           ("久铸尘铁", ("赫拉格",), D(2019, 9, 10, 16, 0), D(2019, 9, 24, 3, 59), False, "")],
            "201905517": [("银灰色的荣耀", ("银灰",), D(2019, 5, 23, 10, 0), D(2019, 5, 30, 4, 0), False, "")],
        }
        for cid, w in want.items():
            check(f"官网公告 {cid} 按节读出的卡池", sections(cid), w)
            # Texts cached off the page before 2026-10-07 stay in use (update_arknights_history)
            check(f"官网公告 {cid}：网页正文与接口正文读出的一样", read(cid, _b._ak_article_text(arts[cid])), w)
        # The gate: these samples must keep coming from different banners and years,
        # so a later change to the reader is checked against more than one period.
        got = [x for cid in want for x in sections(cid)]
        check("样本至少来自 3 个不同期（不同卡池、不同年份）",
              (len({(x[0], x[2]) for x in got}) >= 3, len({x[2].year for x in got}) >= 3), (True, True))

        # 6247 (a limited banner): 「予愿安洁莉娜[限定] \\ 珊比」 used to come out as one name
        lst = ak_lists(fx("ak_news_list_2026-09-12.txt"))
        posts = _b.arknights_banner_posts(datetime(2026, 9, 12), get=ak_site(lst, cms))
        check("限定池六星分开、去掉 [限定]", [w for _, w, _, _, _ in posts],
              ["结城理「石白深蓝之夜」", "予愿安洁莉娜、珊比「车辙与风的归所」"])

        # The next banner on 2026-10-06: announced only inside the 「昨日海」 event post
        get = ak_site(ak_lists(fx("ak-history-news-2026-10-06.txt")), cms)
        check("10-06 的下期：克莱门莎「海渊巡游」10-09 12:00（只在活动预告里）",
              _ak_next(datetime(2026, 10, 6, 12, 0), get=get),
              (datetime(2026, 10, 9, 12, 0), "克莱门莎「海渊巡游」"))
        # Two banners in one post: after the first opens, the second is still next
        get19 = ak_site({"ACTIVITY": sorted(((it["cid"], it["title"], it["displayTime"]) for it in page_items[39]),
                                            key=lambda it: -it[2])}, cms)
        check("一帖两池：08-21 发帖后下期是深夏的守夜人",
              _ak_next(datetime(2019, 8, 22), get=get19), (datetime(2019, 8, 27, 16, 0), "黑「深夏的守夜人」"))
        check("一帖两池：第一池开了以后下期是久铸尘铁",
              _ak_next(datetime(2019, 9, 1), get=get19), (datetime(2019, 9, 10, 16, 0), "赫拉格「久铸尘铁」"))

        # The same through _arknights (PRTS of 08-31 has no row for it yet)
        wt = fx("prts_limited.wikitext")
        real_json, real_text = _b._json, _b._text

        def api(url, *a, **k):
            if url.startswith(_b._PRTS) and url.endswith(urllib.parse.quote(_AK_PAGES[0])):
                return {"parse": {"wikitext": {"*": wt}}}
            raise OSError("offline")

        def text(url, *a, **k):
            return get(url)
        _b._json, _b._text = api, text
        saved = dict(_b._rarity_cache)
        _b._rarity_cache.clear()
        try:
            tr = _b.Trace.new()
            _, nxt = _b._arknights(datetime(2026, 10, 6, 12, 0), trace=tr)
        finally:
            _b._json, _b._text = real_json, real_text
            _b._rarity_cache.clear()
            _b._rarity_cache.update(saved)
        check("_arknights 10-06 的下期来自官网活动预告", nxt, (datetime(2026, 10, 9, 12, 0), "克莱门莎「海渊巡游」"))
        check("开始时刻进了来源闸", "10-09 12:00" in tr.starts, True)

        # arknights_history: the site's list endpoint page by page, merged with PRTS
        order = [1, 7, 28, 29, 39, 40]

        post_get = ak_site({}, cms)

        def hget(u):
            if "/api/news" in u:
                n = int(u.rsplit("=", 1)[-1])
                return fx(f"ak-history-news-p{order[n - 1]}.json")
            return post_get(u)
        hist = _b.arknights_history(get=hget, prts_rows=parse_arknights(wt), max_pages=len(order))
        off = [h for h in hist if h.source != "PRTS"]
        check("往期（官网）按时间排好",
              [(h.name, h.start.strftime("%Y-%m-%d %H:%M")) for h in off],
              [("银灰色的荣耀", "2019-05-23 10:00"), ("深夏的守夜人", "2019-08-27 16:00"), ("久铸尘铁", "2019-09-10 16:00"),
               ("盛夏新星", "2021-08-03 16:00"), ("不羁逆流", "2021-08-26 16:00"), ("雪融之诺", "2021-12-21 16:00"),
               ("以风雪为誓", "2025-11-01 00:00"), ("现实之上六百米", "2025-12-05 12:00"),
               ("石白深蓝之夜", "2026-09-04 12:00"), ("海渊巡游", "2026-10-09 12:00")])
        by = {h.name: h for h in off}
        check("两帖同一池并成一行、两个来源都记", by["以风雪为誓"].source.count("/news/"), 2)
        # the PRTS sample is of 08-31: its last row is 联合行动23 (08-18)
        check("官网与 PRTS 对上的记 + PRTS", [n for n, h in by.items() if "+ PRTS" not in h.source], ["石白深蓝之夜", "海渊巡游"])
        check("PRTS 写 07:00、官网写 12:00 的差异记下",
              by["现实之上六百米"].check, "开始 官网 2025-12-05 12:00 / PRTS 2025-12-05 07:00")
        check("2019 官网写 04:00、PRTS 写 03:59", by["银灰色的荣耀"].check, "结束 官网 2019-05-30 04:00 / PRTS 2019-05-30 03:59")
        check("复刻节标出来", [n for n, h in by.items() if h.rerun], ["不羁逆流"])
        check("PRTS 的其余行照样在（来源只写 PRTS）", len(hist) - len(off), 164 - (len(off) - 2))
        import tempfile
        sd = Path(tempfile.mkdtemp())
        asked: list = []

        def counted(u):
            asked.append(u)
            return hget(u)
        rows1, chg = _b.update_arknights_history(sd, counted, parse_arknights(wt), budget=1000, max_pages=len(order))
        check("方舟往期记账：缓存过的正文读出来和直接读一样", [(h.name, h.start, h.end) for h in rows1],
              [(h.name, h.start, h.end) for h in hist])
        check("方舟往期记账：第一次没有变化", chg, [])
        n1 = len([u for u in asked if "/api/news" not in u])
        _b.update_arknights_history(sd, counted, parse_arknights(wt), budget=1000, max_pages=len(order))
        check("方舟往期记账：第二次不再取帖子正文", len([u for u in asked if "/api/news" not in u]) - n1, 0)
        # A cache written before 2026-10-07 holds the page texts under the page address:
        # read as they are, nothing fetched again.
        sd2 = Path(tempfile.mkdtemp())
        (sd2 / "banners").mkdir(parents=True)
        old_cache = {f"{_b._AK_NEWS}/{c}": _b._ak_article_text(h) for c, h in arts.items()}
        (sd2 / "banners" / "ak-posts.json").write_text(json.dumps(old_cache, ensure_ascii=False), encoding="utf-8")
        asked.clear()
        rows2, _chg = _b.update_arknights_history(sd2, counted, parse_arknights(wt), budget=1000, max_pages=len(order))
        check("方舟往期记账：旧缓存（网页正文）读出来一样",
              [(h.name, h.start, h.end) for h in rows2 if h.source != "PRTS"],
              [(h.name, h.start, h.end) for h in hist if h.source != "PRTS"])
        check("方舟往期记账：旧缓存里有的帖子不再取",
              sorted({u.split("/bulletin/")[1].split("?")[0] for u in asked if "/bulletin/" in u} & set(arts)), [])

        # displayTime is read on the server clock (+8), whatever the machine's zone
        import os
        import time
        if hasattr(time, "tzset"):
            saved_tz = os.environ.get("TZ")
            os.environ["TZ"] = "Asia/Tokyo"
            time.tzset()
            try:
                got = _b._ak_posted(1790996400)
            finally:
                if saved_tz is None:
                    os.environ.pop("TZ", None)
                else:
                    os.environ["TZ"] = saved_tz
                time.tzset()
            check("发帖时间按服务器时钟 +8，不随本机时区（东京）", got, datetime(2026, 10, 3, 11, 0))


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


    def _comm_lead() -> None:
        """Acceptance 2026-10-01 00:31: newsletter #69 (cid 7366, 09-25) says new
    operators (「新干员」) come with SideStory「昨日海」 in early October."""
        lst = {"NEWS": [("7366", "《明日方舟》制作组通讯#69期", 1790326800)]}     # 09-25 16:00 +8
        body = ("<p>●SideStory「昨日海」限时活动将于10月上旬开启，该活动除包含全新活动关卡与剧情外，"
            "新干员和新时装以及相关主题家具也将伴随本次活动登场及上架。</p>"
            "<p>●【明日方舟×国家图书馆】「恒远津梁」限时活动将于10月中旬开启，活动期间玩家登录签到"
            "可获得活动家具，联动系列时装、头像将同步上架贩售。</p>")
        get = ak_site(lst, {"7366": ak_cms(body)})
        now = datetime(2026, 10, 1, 0, 30)
        lead = _b.arknights_comm_lead(now, get=get)
        check("通讯#69：昨日海 10 月上旬，出处 7366", lead[:3] if lead else None, ("昨日海", "10 月上旬", "7366"))
        check("原句进来源记录", "新干员" in lead[3] and "恒远津梁" not in lead[3], True)
        only_outfits = body.replace("新干员和", "")
        check("同篇「恒远津梁」（只有时装）不算",
              _b.arknights_comm_lead(now, get=ak_site(lst, {"7366": ak_cms(only_outfits)})), None)
        check("上旬过了就不出", _b.arknights_comm_lead(datetime(2026, 10, 11), get=get), None)
        post = (datetime(2026, 10, 8, 16, 0), "某人「某池」", datetime(2026, 10, 3, 12, 0), datetime(2026, 10, 22, 3, 59), "1")
        check("通讯之后出了寻访公告就不出", _b.arknights_comm_lead(now, [post], get=get), None)
        check("通讯之后开的首发池在跑就不出", _b.arknights_comm_lead(now, opened=[datetime(2026, 9, 30, 16, 0)], get=get), None)
        check("通讯之前开的池不挡", _b.arknights_comm_lead(now, opened=[datetime(2026, 9, 18, 16, 0)], get=get)[0], "昨日海")
        out = render([], now, {}, leads={"明日方舟": "昨日海 · 10 月上旬 · 官方通讯：有新干员，寻访未公告"},
                     trace=_b.Trace.new())
        check("下期行原样、过来源闸", "· 下期：昨日海 · 10 月上旬 · 官方通讯：有新干员，寻访未公告" in out, True)


    def _ww_calendar() -> None:
        """The user, 2026-10-01 01:03: 「下期锁暝，开始时间官方公布了。你们没有找到，说明你们根本在偷懒。」
    The date is only on the notice's activity[] image 「3.7版本活动日历」 (id 50868).
    The fixture is that image read by macOS Vision; the machine uses
    Windows.Media.Ocr, whose text may differ character by character."""
        from ark_relay.core.desktop import Line
        url = "https://aki-gm-resources-back.aki-game.com/notice/image/fYrvOmEkgCfEKFTy.png"
        notice = {"activity": [
            {"id": "50868", "tabTitle": "3.7版本活动日历", "startTimeMs": "1790712000000",
             "content": f'<p><img src="{url}" alt="" width="1080" height="2159"></p>'},
            {"id": "1", "tabTitle": "鸣潮丨蜃云灯影·凡尘剑心系列周边 预售现已开启！", "content": '<img src="x.png">'}]}
        check("找到版本活动日历图", _b.wuwa_calendar_image(notice), ("3.7", "50868", url))
        check("没有日历帖就是 None", _b.wuwa_calendar_image({"activity": []}), None)

        # ww-3.7-calendar.webp is the image as served; the .json next to it is its OCR
        import hashlib
        check("真图在固定件里", hashlib.sha1((FX / "ww-3.7-calendar.webp").read_bytes()).hexdigest()[:12], "67c0af2ff520")
        lines = [Line(**o) for o in json.loads((FX / "ww-3.7-calendar-ocr.json").read_text(encoding="utf-8"))]
        now = datetime(2026, 10, 1, 1, 30)
        check("锁暝的池 10-22 开（图上 10.22~11.11/1 带 OCR 杂字）",
              _b.parse_wuwa_calendar(lines, "余心所向九死未悔", now), datetime(2026, 10, 22))
        typo = [Line("余心所问九死未悔", o.x, o.y, o.w, o.h) if o.text == "余心所向九死未悔" else o for o in lines]
        check("池名认错一个字也配得上", _b.parse_wuwa_calendar(typo, "余心所向九死未悔", now), datetime(2026, 10, 22))
        # 2026-10-06 06:20:17 incident: Windows OCR dropped two characters off the name
        # and garbled the date row into 「10．22一]I.11」 and 「]0．22」 (]→1, 一→~,
        # full-width dots). The old _fuzzy_in only saw same-length substitution, never
        # dropped characters, so every case above read red.
        dropped = [Line("余心所向九悔", o.x, o.y, o.w, o.h) if o.text == "余心所向九死未悔" else o for o in lines]
        check("名字掉两字也配得上（事故原文「余心所向九悔」）",
              _b.parse_wuwa_calendar(dropped, "余心所向九死未悔", now), datetime(2026, 10, 22))
        garbled = [Line("余心所向九悔", 621, 200, 219, 34), Line("10．22一]I.11", 609, 172, 91, 22)]
        check("日期行 ]→1、一→~、全角点（事故原文「10．22一]I.11」）",
              _b.parse_wuwa_calendar(garbled, "余心所向九死未悔", now), datetime(2026, 10, 22))
        bare = [Line("余心所向九悔", 621, 200, 219, 34), Line("]0．22", 609, 172, 91, 22)]
        check("裸日期「]0．22」没带 ~，不取（分不清是起还是止）",
              _b.parse_wuwa_calendar(bare, "余心所向九死未悔", now), None)
        # A single date is as likely the END of the previous banner's range as the start
        # of this one: 11.11 alone above the name must not be taken for the start date.
        end_alone = [Line("余心所向九悔", 621, 200, 219, 34), Line("11.11", 609, 172, 91, 22)]
        check("单独一行 11.11（区间结束日期）不当开始日期",
              _b.parse_wuwa_calendar(end_alone, "余心所向九死未悔", now), None)
        joined = [Line("9.30~10.22 10.22~11.11", 131, 172, 569, 22) if o.text.startswith("10.22~11.11") else o
                  for o in lines if not (o.y < 190 and o.text.startswith("9.30"))]
        check("两个标签被并成一行也取对的那个",
              _b.parse_wuwa_calendar(joined, "余心所向九死未悔", now), datetime(2026, 10, 22))
        check("图上没有的池不给日期", _b.parse_wuwa_calendar(lines, "身赴三途", now), None)
        check("跨年：12 月读到 1 月的日期算下一年",
              _b.parse_wuwa_calendar([Line("1.05~1.26", 10, 100, 90, 22), Line("某池", 20, 128, 100, 34)], "某池",
                                     datetime(2026, 12, 20)), datetime(2027, 1, 5))

        end = datetime(2026, 10, 22, 9, 59, 59)
        xin = _b.Banner("鸣潮", "但愿长圆如此夜", ("心",), datetime(2026, 9, 30, 11, 0), end)
        tr, notes = _b.Trace.new(), {}
        day = _b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, lambda u: lines if u == url else None, notes, tr)
        check("读图得到日期", day, datetime(2026, 10, 22))
        check("来源记下公告 id 和图", any("鸣潮｜版本日历" in x and "id=50868" in x and url in x for x in tr.sources), True)
        check("与当期结束同一天，互核 ✓", any("版本日历" in c and c.endswith("✓") for c in tr.checks), True)
        out = _b.render([xin], now, {"鸣潮": (day, "锁暝「余心所向九死未悔」")}, notes, tr)
        check("下期写日期和出处、不凑时刻",
              ("· 下期：余心所向九死未悔 · 锁暝 · 10-22 开始（官方 3.7 版本活动日历）" in out, "00:00" in out, tr.withheld),
              (True, False, []))
        check("当天（10-22 凌晨）这行还在",
              "10-22 开始（官方 3.7 版本活动日历）" in _b.render([xin], datetime(2026, 10, 22, 5, 0),
                                                            {"鸣潮": (day, "锁暝「余心所向九死未悔」")}, notes), True)

        tr, notes = _b.Trace.new(), {}
        day = _b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, None, notes, tr)
        out = _b.render([xin], now, {"鸣潮": (day, "锁暝「余心所向九死未悔」")}, notes, tr)
        check("读不出图：说公告是图片没读出，不说官方未公布",
              ("· 下期：余心所向九死未悔 · 锁暝 · 官方公告为图片，未能读取" in out, "官方未公布" in out),
              (True, False))

        # Another source already gave the time (notes=None): the calendar image has dates only, no
        # hour or minute, so it is not read at all; the trace says 「另一来源已给出」 (machine check #2).
        def _must_not_read(u):
            raise AssertionError("the calendar image must not be read when another source gave the time")
        tr = _b.Trace.new()
        day = _b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, _must_not_read, None, tr)
        check("另一来源已给出：图不读，日期 None", day, None)
        check("……trace 写「另一来源已给出」，不写「官方公告为图片」",
              (any("另一来源已给出" in s for s in tr.sources),
               any("官方公告为图片" in s for s in tr.sources)),
              (True, False))


    def _ww_news_poster() -> None:
        """The user, 2026-10-01 02:00: 「我已经在b站的这个贴文的第三张图片看到了时间。确实有点难找。」
    The second-half banner's time of day is only on the version-news post's third
    long image (Kuro BBS post 1551271800597471232, 733x10000; the same on Bilibili). Read
    whole it gives three garbled lines; in strips it gives the sentence. The OCR
    fixture is that image (sha1 a21cd2de102d, not kept: 1.3 MB) read in strips by
    macOS Vision through ocr_strips; ww-3.7-news-3-banner.webp is the block that
    matters, cut from it (y 5230-5800)."""
        from io import BytesIO

        from PIL import Image

        from ark_relay.core.desktop import Line
        now = datetime(2026, 10, 1, 2, 30)
        events = json.loads((FX / "ww-news-events.json").read_text(encoding="utf-8"))["data"]["list"]
        check("找到 3.7 版本资讯帖（标题里是不换行空格）",
              _b.wuwa_news_post(events, "3.7", now)[:2],
              ("1551271800597471232", "《鸣潮》版本资讯 | 3.7版本「镜锁妄世，心照红尘」"))
        check("别的版本号不认", _b.wuwa_news_post(events, "3.8", now), None)
        check("发帖之前不认", _b.wuwa_news_post(events, "3.7", datetime(2026, 9, 28, 17, 0)), None)

        import hashlib
        check("唤取时间那一段裁图在固定件里",
              hashlib.sha1((FX / "ww-3.7-news-3-banner.webp").read_bytes()).hexdigest()[:12], "4a054eb3ab8c")
        lines = [Line(**o) for o in json.loads((FX / "ww-3.7-news-3-ocr.json").read_text(encoding="utf-8"))]
        span = (datetime(2026, 10, 22, 10, 0), datetime(2026, 11, 11, 11, 59))
        check("锁暝池：2026年10月22日10:00～2026年11月11日11:59",
              _b.parse_wuwa_poster(lines, "余心所向九死未悔", "锁暝"), span)
        check("同一时间块下的洛瑟菈池同样取到", _b.parse_wuwa_poster(lines, "显影于明日", "洛瑟菈"), span)
        check("第一期池（3.7版本更新后～…09:59）没有起始日期，不给",
              _b.parse_wuwa_poster(lines, "但愿长圆如此夜", "心"), None)
        garbled = [Line("余心所向九死未啊角色活动典取", o.x, o.y, o.w, o.h) if o.text == "余心所向九死未悔" else o
                   for o in lines]
        check("池名 OCR 错两个字（B 站图的 Vision 读法）也配得上",
              _b.parse_wuwa_poster(garbled, "余心所向九死未悔"), span)
        split = [x for o in lines for x in ([Line("2026年10月22日10:00", o.x, o.y, 250, o.h),
                                             Line("～ 2026年11月11日11:59（服务器时间）", o.x + 260, o.y + 2, 290, o.h)]
                                            if o.text.startswith("2026年10月22日10:00") else [o])]
        check("时间行被拆成两段也拼得回", _b.parse_wuwa_poster(split, "余心所向九死未悔"), span)
        check("图上没有的池不给", _b.parse_wuwa_poster(lines, "身赴三途"), None)
        alone = [x for o in lines for x in ([Line("2026年10月22日10:00～2026年11月11日11:59", o.x, o.y, 450, o.h),
                                             Line("（服务器时间）", o.x + 20, o.y + 30, 150, o.h)]
                                            if o.text.startswith("2026年10月22日10:00") else [o])]
        check("「（服务器时间）」单独成行也取上一行的时间", _b.parse_wuwa_poster(alone, "余心所向九死未悔"), span)
        win = [Line(**o) for o in json.loads((FX / "ww-3.7-news-4-winocr.json").read_text(encoding="utf-8"))]
        check("游戏机上 Windows 识字的真读数（「～」读成「、」，池名读花，「锁暝UP!」读成「锁暝U」）也取到",
              _b.parse_wuwa_poster(win, "余心所向九死未悔", "锁暝"), span)
        check("同一份真读数：第一期池没有起始日期，不给", _b.parse_wuwa_poster(win, "但愿长圆如此夜", "心"), None)

        # Every "each version has one" reader is checked against real samples of at least
        # two different versions (the user, 2026-10-06 17:10 / 17:14: a fix that only fits
        # the current sample fails at the next version). 3.6 is the Windows OCR of the 3.6
        # post's poster: the second-half span is two lines with no 「～」 between them, and
        # the names are garbled (「雪色所千般来」, 「纟史星光于兄穷还」).
        win36 = [Line(**o) for o in json.loads((FX / "ww-3.6-news-4-winocr.json").read_text(encoding="utf-8"))]
        span36 = (datetime(2026, 9, 10, 10, 0), datetime(2026, 9, 29, 11, 59))
        samples = [("3.7", win, [("余心所向九死未悔", "锁暝", span)]),
                   ("3.6", win36, [("身赴三途", "景燃", span36), ("雪色所映千般未来", "绯雪", span36),
                                   ("纵使星光于无穷远", "莫宁", span36),
                                   ("仙风玉影水天清", "清宵", None), ("予明日以谎言", "达妮娅", None)])]
        check("海报读法至少用两个不同版本的真样本验过", len({v for v, _l, _c in samples}) >= 2, True)
        for ver, sample_lines, cases in samples:
            for pool, char, want in cases:
                check(f"{ver} 版本资讯海报：{pool}（{char}）", _b.parse_wuwa_poster(sample_lines, pool, char), want)

        post = json.loads((FX / "ww-3.7-news-post.json").read_text(encoding="utf-8"))
        img3 = "https://prod-alicdn-community.kurobbs.com/forum/539302b44e6e4c118735142822df9fe120260921.jpg"
        asked: list = []

        def get(path, payload):
            return {"data": {"list": events}} if "findEventList" in path else post

        def read(url):
            asked.append(url)
            return lines if url == img3 else []
        feed = json.loads((FX / "ww-bili-feed.json").read_text(encoding="utf-8"))
        bili3 = "https://i0.hdslb.com/bfs/new_dyn/e1826ff7fe229d2f29d8a715a4ee4eee1955897084.jpg"
        bili_asked: list = []

        def bili(url, cookie):
            bili_asked.append(url)
            if "finger/spi" in url:
                return {"data": {"b_3": "B3", "b_4": "B4=="}}
            if "/nav" in url:
                return {"data": {"wbi_img": {"img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                                             "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png"}}}
            return feed

        def no_bili(url, cookie):
            raise AssertionError("B 站不该被问到")
        tr = _b.Trace.new()
        got = _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now, read, tr, get, no_bili)
        check("帖子 → 长图 → 取到时间（库街区读到就不去 B 站）", got, span)
        check("只读长图（封面和小卡片不读），读到它为止", len(asked), 3)
        check("来源记下帖子与第几张图（库街区第 1 张是封面，这张是第 4 张）",
              any("鸣潮｜版本资讯｜库街区" in x and "1551271800597471232" in x and "第 4 张图" in x and img3 in x
                  for x in tr.sources), True)
        check("开始与结束都记为官方时刻", ({"10-22 10:00", "11-11 11:59"} <= tr.starts | tr.ends), True)

        check("WBI 签名：公开写法里的算例", _b.bili_sign({"foo": "114", "bar": "514", "zab": 1919810},
                                                    "7cd084941338484aae1ad9425b84077c",
                                                    "4932caff0ff746eab6f01bf08b70ac45", 1702204169),
              "bar=514&foo=114&wts=1702204169&zab=1919810&w_rid=8f6f2b5b3d485fe1886cec6a0be8c5d4")
        hit = _b.wuwa_bili_post(feed["data"]["items"], "3.7", now)
        check("B 站动态里找到 3.7 版本资讯（图址换成 https）",
              (hit[0], hit[2][2], "版本资讯" in hit[1]), ("1253061864718336024", (bili3, 1080, 14717), True))
        check("B 站：别的版本号不认", _b.wuwa_bili_post(feed["data"]["items"], "3.8", now), None)
        asked.clear()
        tr = _b.Trace.new()
        got = _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now,
                                   lambda u: lines if u == bili3 else [], tr, lambda p, d: {}, bili)
        check("库街区取不到时读 B 站同一帖", got, span)
        check("B 站那条来源记下动态网址与第 3 张图",
              any("鸣潮｜版本资讯｜B 站 https://www.bilibili.com/opus/1253061864718336024" in x and "第 3 张图" in x
                  and bili3 in x for x in tr.sources), True)
        check("B 站请求带了签名", any("w_rid=" in u and "host_mid=1955897084" in u for u in bili_asked), True)
        check("两边都取不到就是 None", _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now, read,
                                                        _b.Trace.new(), lambda p, d: {}, lambda u, c: {}), None)
        asked.clear()
        check("读图助手失败就不再读后面的图，也不去 B 站",
              (_b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now, lambda u: asked.append(u), _b.Trace.new(),
                                    get, no_bili), len(asked)), (None, 1))
        asked.clear()

        def flaky(u):
            asked.append(u)
            if len(asked) == 1:
                raise OSError("timed out")
            return lines if u == img3 else []
        check("一张图下载超时不算读图助手坏了，接着读后面的图",
              _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now, flaky, _b.Trace.new(), get, no_bili), span)
        check("没有读图能力就不去取",
              _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now, None, _b.Trace.new(), get, no_bili), None)

        end = datetime(2026, 10, 22, 9, 59, 59)
        xin = _b.Banner("鸣潮", "但愿长圆如此夜", ("心",), datetime(2026, 9, 30, 11, 0), end)
        tr.until["鸣潮"] = span[1]
        out = _b.render([xin], now, {"鸣潮": (span[0], "锁暝「余心所向九死未悔」")}, {}, tr)
        check("下期写官方钟点和结束，不折成「换池时开」",
              ("· 下期：余心所向九死未悔 · 锁暝 · 北京 10-22 10:00 开 · 11-11 11:59 结束" in out, "换池时开" in out,
               tr.withheld), (True, False, []))
        out = _b.render([xin], now, {"鸣潮": (datetime(2026, 10, 22, 10, 0), "锁暝「余心所向九死未悔」")}, {},
                        _b.Trace.new())
        check("没有官方结束时刻的相接时刻照旧折成换池", "换池时开" in out, True)
        check("群里明天开新池照样报（有名字、有钟点）",
              _b.opening_tomorrow(datetime(2026, 10, 21, 21, 30), {"鸣潮": (span[0], "锁暝「余心所向九死未悔」")}),
              [("鸣潮", span[0], "锁暝「余心所向九死未悔」")])

        # strips: a 733x10000 poster is enlarged to 1000 wide and cut every 1200 px;
        # each strip is read on its own and the lines come back in image coordinates
        scale, plan = _b.strip_plan(733, 10000)
        check("窄长图放大到约 1000 宽、每块不超过 2000 像素",
              (round(733 * scale), all(round(h * scale) <= 2000 for _, h in plan), plan[0], plan[-1][0] + plan[-1][1]),
              (1000, True, (0, 1400), 10000))
        check("日历图（1080x2159）整张读，放大两倍（原样读时 Windows OCR 读乱了日期）", _b.strip_plan(1080, 2159),
              (2.0, [(0, 2159)]))
        check("放大后超过 8000 像素的不放大", _b.strip_plan(2400, 4400), (1.0, [(0, 4400)]))
        # The machine's real Windows OCR of the 3.7 calendar (notice 50868), 2026-10-06 16:07: read at its
        # own size the second-half label is garbled, read at two times the date comes out.
        _fx = fx_dir(Path(__file__), "fixtures")
        _l1 = [Line(**o) for o in json.loads((_fx / "ww-3.7-calendar-ocr-win-1x.json").read_text(encoding="utf-8"))]
        _l2 = [Line(**o) for o in json.loads((_fx / "ww-3.7-calendar-ocr-win-2x.json").read_text(encoding="utf-8"))]
        _now = datetime(2026, 10, 6)
        check("机器上原样读的那份：读不出（这就是 10-06 的误报）",
              _b.parse_wuwa_calendar(_l1, "余心所向九死未悔", _now), None)
        check("机器上放大两倍读的那份：读出 10-22",
              _b.parse_wuwa_calendar(_l2, "余心所向九死未悔", _now), datetime(2026, 10, 22))
        check("B 站那张（1080x14717）不放大、切块", (_b.strip_plan(1080, 14717)[0], len(_b.strip_plan(1080, 14717)[1]) > 5),
              (1.0, True))
        buf = BytesIO()
        Image.new("RGB", (733, 3000), "white").save(buf, format="PNG")
        seen = []

        def fake(png, i):
            w, h = Image.open(BytesIO(png)).size
            seen.append((w, h))
            # a line 200 px into each strip, and one inside the overlap at its bottom
            return [Line(f"s{i}", 10, 200, 100, 20), Line(f"e{i}", 10, h - 60, 100, 20)]
        got = _b.ocr_strips(buf.getvalue(), fake)
        check("每块按放大后的尺寸送去读", seen[0], (1000, round(1400 * 1000 / 733)))
        check("坐标换回原图；重叠区的行只留一份",
              [(x.text, x.y) for x in got],
              [("s0", 147), ("s1", 1347), ("s2", 2547), ("e2", 2956)])
        check("有一块读不出就整张不算", _b.ocr_strips(buf.getvalue(), lambda png, i: None if i == 1 else []), None)


    def _ww_gacha_notice() -> None:
        """鸣潮 second half to the minute (user 2026-10-05 23:31 「必须要精确到几点几分」).
    The 库街区 banner notices print the span as text; before the second half's own
    notice (about 12:00 the day before) the first half's printed end + 1 min is
    used and said to be worked out (notices go up about 11:00 Beijing the day before). Real lists and posts of 2026-10-05."""
        events = json.loads((FX / "ww-kuro-events3-2026-10-05.json").read_text(encoding="utf-8"))["data"]["list"]
        posts = json.loads((FX / "ww-kuro-gacha-posts.json").read_text(encoding="utf-8"))
        asked: list = []

        def detail_of(pid):
            asked.append(pid)
            return posts[pid]
        # 3.6 second half, real: the notices went up 09-09 11:00-11:15 Beijing for 09-10 10:00
        got = _b.wuwa_gacha_notice(events, detail_of, "3.6", "身赴三途", datetime(2026, 9, 9, 13, 0))
        check("3.6 第二期公告出了：取公告原文 09-10 10:00～09-29 11:59",
              got[:3], ("公告原文", datetime(2026, 9, 10, 10, 0), datetime(2026, 9, 29, 11, 59)))
        check("来源写帖子地址和标题", "1546" in got[3] and "唤取" in got[3], True)
        got = _b.wuwa_gacha_notice(events, detail_of, "3.6", "身赴三途", datetime(2026, 9, 9, 10, 30))
        check("3.6 第二期公告没出：第一期 09-10 09:59 结束 +1 分钟，和后来的公告一样",
              got[:3], ("推导", datetime(2026, 9, 10, 10, 0), None))
        got = _b.wuwa_gacha_notice(events, detail_of, "3.7", "余心所向九死未悔", datetime(2026, 10, 5, 23, 0))
        check("3.7 第二期公告没出：推导 10-22 10:00（第一期帖原文「3.7版本更新后 ~ 2026年10月22日09:59」）",
              got[:3], ("推导", datetime(2026, 10, 22, 10, 0), None))
        check("推导来源写第一期帖和它的结束时刻", "1554096755014008832" in got[3] and "10-22 09:59 结束" in got[3], True)
        check("没有版本号也没有本池公告就不推", _b.wuwa_gacha_notice(events, detail_of, None, "余心所向九死未悔",
                                                             datetime(2026, 10, 5, 23, 0)), None)

        # The next version's first half, end only (its start is the maintenance end): the Kuro
        # first-half notice and the poster row, each on real samples of two versions.
        from ark_relay.core.desktop import Line as _L
        for ver, at, want in (("3.7", datetime(2026, 9, 30, 0, 0), datetime(2026, 10, 22, 9, 59)),
                              ("3.6", datetime(2026, 9, 9, 13, 0), datetime(2026, 9, 10, 9, 59))):
            got = _b.wuwa_first_half_notice_end(events, detail_of, ver, at)
            check(f"{ver} 第一期公告原文：结束 {want:%m-%d %H:%M}", got[0] if got else None, want)
        check("下一版（3.8）第一期公告没出：不给", _b.wuwa_first_half_notice_end(events, detail_of, "3.8", datetime(2026, 10, 5, 23, 0)), None)
        check("公告发出之前不给", _b.wuwa_first_half_notice_end(events, detail_of, "3.7", datetime(2026, 9, 1, 0, 0)), None)
        for ver, name, want in (("3.7", "ww-3.7-news-4-winocr.json", datetime(2026, 10, 22, 9, 59)),
                                ("3.6", "ww-3.6-news-4-winocr.json", datetime(2026, 9, 10, 9, 59))):
            pl = [_L(**o) for o in json.loads((FX / name).read_text(encoding="utf-8"))]
            check(f"{ver} 海报：第一期结束 {want:%m-%d %H:%M}（真读数）", _b.parse_wuwa_poster_first_end(pl), want)
        act = [_L("先约电台", 400, 900, 200, 40), _L("活动时间", 112, 1673, 83, 24),
               _L("3．6版本更新后、2026年9月29日03：59（服务器时间）", 238, 1700, 630, 26)]
        check("普通活动的「版本更新后～…03:59」不当作第一期结束（上面没有「唤取」标题）",
              _b.parse_wuwa_poster_first_end(act), None)

        # the door order: no notice yet -> the Kuro poster copy is read, its first-half row gives the end
        news_events = json.loads((FX / "ww-news-events.json").read_text(encoding="utf-8"))["data"]["list"]
        post37 = json.loads((FX / "ww-3.7-news-post.json").read_text(encoding="utf-8"))
        pl37 = [_L(**o) for o in json.loads((FX / "ww-3.7-news-4-winocr.json").read_text(encoding="utf-8"))]

        def kget(path, payload):
            if "findEventList" in path:
                return {"data": {"list": [] if payload.get("eventType") == 3 else news_events}}
            return post37
        img4 = "https://prod-alicdn-community.kurobbs.com/forum/539302b44e6e4c118735142822df9fe120260921.jpg"
        def no_net(url, cookie):
            raise OSError("offline")
        tr0 = _b.Trace.new()
        end1 = _b._wuwa_first_half_end("3.7", datetime(2026, 9, 29, 12, 0), lambda u: pl37 if u == img4 else [],
                                       tr0, kget, no_net)
        check("公告没出：从版本资讯长图读到第一期结束 10-22 09:59", end1, datetime(2026, 10, 22, 9, 59))
        check("来源写进追溯", any("第一期 2026-10-22 09:59 结束" in x for x in tr0.sources), True)
        check("两处都没出（长图读不到）就不给，也不报错",
              _b._wuwa_first_half_end("3.7", datetime(2026, 9, 29, 12, 0), lambda u: [], _b.Trace.new(), kget, no_net), None)
        check("下期行：开 = 维护结束，结束 = 第一期结束",
              _b._next_line(datetime(2026, 11, 12, 11, 0), "3.8版本第一期", False, "", datetime(2026, 11, 26, 9, 59),
                            "版本更新维护 11-12 04:00～11:00 结束后开"),
              "· 下期：3.8版本第一期 · 北京 11-12 11:00 开（版本更新维护 11-12 04:00～11:00 结束后开） · 11-26 09:59 结束")

        # Past periods, read like the next one (real: every banner notice the Kuro list still holds, 2024-06 ..
        # 2026-09, 147 notices, plus the site's maintenance notices 1.1 .. 3.7).
        hx = json.loads((FX / "ww-history-2026-10-06.json").read_text(encoding="utf-8"))
        hist = _b.wuwa_history(hx["events"], lambda pid: hx["details"][pid], hx["articles"],
                               lambda aid: json.dumps({"articleContent": hx["article_text"][str(aid)]}), datetime(2026, 10, 6, 12, 0))
        check("往期：1.0 第二期到 3.6 第二期共 42 段", len(hist), 42)
        by = {(h["ver"], h["part"], h["pools"][0] if h["pools"] else ""): h for h in hist}
        h36 = by[("3.6", "第二期", "身赴三途")]
        check("3.6 第二期：09-10 10:00～09-29 11:59，千般渡",
              (h36["start"], h36["end"], h36["weapons"]),
              (datetime(2026, 9, 10, 10, 0), datetime(2026, 9, 29, 11, 59), ["千般渡"]))
        # 2026-10-13: `ups` mixed weapon names into the featured characters
        # (1.1 gave ["今汐", "时和岁稔"]) and nothing read it; it is gone.
        check("往期记录里没有 ups 这一项", any("ups" in h for h in hist), False)
        h36a = by[("3.6", "第一期", "仙风玉影水天清")]
        check("3.6 第一期：开 = 维护结束 08-20 11:00，09-10 09:59 结束",
              (h36a["start"], h36a["end"], h36a["start_how"].startswith("3.6版本更新维护 08-20 04:00～11:00")),
              (datetime(2026, 8, 20, 11, 0), datetime(2026, 9, 10, 9, 59), True))
        h11 = by[("1.1", "第一期", "寒尽觉春生")]
        check("1.1（2024 年，标题写法 <名>…——「角色」概率UP）：06-28 13:00～07-22 09:59",
              (h11["start"], h11["end"]), (datetime(2024, 6, 28, 13, 0), datetime(2024, 7, 22, 9, 59)))
        check("2.x 的写法也读到：2.3 第二期 诗与乐的交响 05-22 10:00～06-11 11:59",
              (by[("2.3", "第二期", "诗与乐的交响")]["start"], by[("2.3", "第二期", "诗与乐的交响")]["end"]),
              (datetime(2025, 5, 22, 10, 0), datetime(2025, 6, 11, 11, 59)))
        check("3.5 的忆旅唤取（联动之外的另一种写法）也在", ("3.5", "第一期", "忆旅回响") in by, True)
        # structure that must hold for any version: a half is a real span, and a second half opens one
        # minute after its first half closes (2.6 - 3.6 nine of nine; 3.4 is the one overlap)
        from datetime import timedelta
        firsts = {h["ver"]: h for h in hist if h["part"] == "第一期" and (h["end"].hour, h["end"].minute) == (9, 59)}
        chain_bad = [h["ver"] for h in hist if h["part"] == "第二期" and h["ver"] in firsts
                     and h["start"] != firsts[h["ver"]]["end"] + timedelta(minutes=1) and h["ver"] != "3.4"]
        check("每一版第二期都在第一期结束后一分钟开（3.4 除外，两期并行）", chain_bad, [])
        check("每段都有起止、开始早于结束", [h["ver"] for h in hist if not (h["start"] and h["start"] < h["end"])], [])
        check("版本依次排好，没有哪一版缺第一期（1.0 只有第二期留着）",
              sorted({h["ver"] for h in hist if h["part"] == "第二期"} - {h["ver"] for h in hist if h["part"] == "第一期"}), ["1.0"])
        import tempfile
        hd = Path(tempfile.mkdtemp())
        check("记账：第一次记下，没有变化", _b.record_history(hd, "鸣潮", hist), [])
        check("记账：同一份再记，没有变化", _b.record_history(hd, "鸣潮", hist), [])
        bad = [dict(h, end=h["end"] + timedelta(hours=1)) if (h["ver"], h["part"]) == ("3.6", "第二期") else h for h in hist]
        ch = _b.record_history(hd, "鸣潮", bad)
        check("记账：往期的结束时刻变了就说出来（只说一次）", (len(ch), "3.6 第二期" in ch[0] and "09-29 11:59" in ch[0]), (1, True))
        check("记账：说过之后不再重复", _b.record_history(hd, "鸣潮", bad), [])
        # the daily step: fetch once, cache, never raise
        fetched: list = []

        def hist_get(path, payload):
            fetched.append(path)
            if "findEventList" in path:
                return {"data": {"list": hx["events"]}}
            return {"data": {"postDetail": {"postContent": [{"contentType": 1, "content": hx["details"][str(payload["postId"])]["postContent"][0]["content"]}]}}}

        def aget(url):
            if url == _b._WW_SITE_ARTICLES:
                return json.dumps(hx["articles"])
            aid = url.rsplit("/", 1)[1].split(".")[0]
            return json.dumps({"articleContent": hx["article_text"][aid]})
        sd = Path(tempfile.mkdtemp())
        got, chg = _b.update_wuwa_history(sd, datetime(2026, 10, 6, 12, 0), hist_get, aget, budget=1000)
        check("每日这一步：一次取全、记下 42 段", (len(got), chg), (42, []))
        n1 = len(fetched)
        _b.update_wuwa_history(sd, datetime(2026, 10, 6, 12, 0), hist_get, aget, budget=1000)
        check("第二次不再取帖子正文（只问一次列表）", len(fetched) - n1, 1)
        real_ww, real_ef, real_ak = _b.update_wuwa_history, _b.update_endfield_history, _b.update_arknights_history

        def ef_down(state_dir, get=None):
            raise OSError("offline")
        _b.update_wuwa_history = lambda state_dir, now: ([], ["鸣潮往期「3.6 第二期」的起止变了"])
        _b.update_endfield_history = ef_down
        _b.update_arknights_history = lambda state_dir: ([], [])
        try:
            check("每日往期这一步：一个游戏取不到不挡另一个，也不抛", _b.update_history(sd, datetime(2026, 10, 6, 12, 0)),
                  ["鸣潮往期「3.6 第二期」的起止变了"])
        finally:
            _b.update_wuwa_history, _b.update_endfield_history, _b.update_arknights_history = real_ww, real_ef, real_ak

        # the whole of _wuwa on the 10-05 game notice: four cases
        notice = json.loads((FX / "ww-notice-2026-10-05.json").read_text(encoding="utf-8"))
        news = json.loads((FX / "ww-news-events.json").read_text(encoding="utf-8"))["data"]["list"]
        news_post = json.loads((FX / "ww-3.7-news-post.json").read_text(encoding="utf-8"))
        img3 = "https://prod-alicdn-community.kurobbs.com/forum/539302b44e6e4c118735142822df9fe120260921.jpg"
        from ark_relay.core.desktop import Line
        lines = [Line(**o) for o in json.loads((FX / "ww-3.7-news-3-ocr.json").read_text(encoding="utf-8"))]
        xin = _b.Banner("鸣潮", "但愿长圆如此夜", ("心",), datetime(2026, 9, 30, 11, 0), datetime(2026, 10, 22, 9, 59, 59))
        # a second-half notice as 3.6's (real wording), with 3.7's names and times
        p36 = posts["1546583036413710336"]
        p37 = json.loads(json.dumps(p36, ensure_ascii=False).replace("身赴三途", "余心所向九死未悔")
                         .replace("2026年9月10日10:00", "2026年10月22日10:00").replace("2026年9月29日11:59", "2026年11月11日11:59"))
        p37["postTitle"] = "【3.7版本】[角色/武器活动唤取・第二期]"
        out37 = {"postId": "9990000000000000001", "postTitle": p37["postTitle"], "publishTime": 1792555200000, "eventType": 3}
        art = (FX / "wuwa_site_article_5282.json").read_text(encoding="utf-8")
        art38 = art.replace("2026年8月20日", "2026年11月12日").replace("3.6版本", "3.8版本")
        menu38 = json.dumps([{"articleId": 5500, "articleTitle": "《鸣潮》3.8版本更新维护预告",
                              "articleType": 52, "startTime": "2026-10-21 12:00:00"}], ensure_ascii=False)

        def run(now, read_image, *, out=False, maint=False):
            evs = events + ([out37] if out else [])

            def kuro(path, payload):
                if "findEventList" in path:
                    return {"data": {"list": evs if payload.get("eventType") == 3 else news}}
                pid = str(payload.get("postId"))
                if pid == out37["postId"]:
                    return {"data": {"postDetail": p37}}
                if pid in posts:
                    return {"data": {"postDetail": posts[pid]}}
                return news_post

            def js(url, *a, **k):
                if url == _b._WW_NOTICE:
                    return notice
                if url.endswith("/wiki/core/homepage/getPage"):
                    return {}
                raise OSError("offline")

            def text(url, *a, **k):
                if url == _b._WW_SITE_ARTICLES:
                    return menu38 if maint else "[]"
                if url.endswith("/5500.json"):
                    return art38
                raise OSError("offline")
            real = _b._json, _b._text, _b.parse_wuwa
            _b._json, _b._text, _b.parse_wuwa = js, text, (lambda home, name_of: [xin])
            tr, notes = _b.Trace.new(), {}
            try:
                _got, nxt = _b._wuwa(now, notes, tr, read_image, kuro, lambda u, c: {})
            finally:
                _b._json, _b._text, _b.parse_wuwa = real
            return nxt, tr, _b.render([xin], now, {"鸣潮": nxt}, notes, tr)

        def no_read(url):
            raise AssertionError("公告原文有了就不该读图")
        eve = datetime(2026, 10, 5, 23, 0)
        print("\n[一、公告没出、长图识别失败：推导出几点几分，行里说明是推的]")
        nxt, tr, out = run(eve, lambda u: None)
        check("开始 10-22 10:00", nxt[0], datetime(2026, 10, 22, 10, 0))
        check("下期行带几点几分并说明是推导",
              "· 下期：余心所向九死未悔 · 锁暝 · 北京 10-22 10:00 开（第一期 09:59 结束后接着开，公告未出）" in out, True)
        check("没被来源核对扣下", tr.withheld, [])
        check("来源写推导和历史命中", any("唤取公告" in x and "推导 2026-10-22 10:00" in x and "9 期全中" in x
                                    for x in tr.sources), True)
        print("\n[二、公告出了：用公告原文，不读图]")
        nxt, tr, out = run(datetime(2026, 10, 21, 13, 0), no_read, out=True)
        check("开始 10-22 10:00", nxt[0], datetime(2026, 10, 22, 10, 0))
        check("下期行写原文的开始和结束", "· 下期：余心所向九死未悔 · 锁暝 · 北京 10-22 10:00 开 · 11-11 11:59 结束" in out, True)
        check("来源写公告原文", any("唤取公告" in x and "公告原文" in x and "9990000000000000001" in x for x in tr.sources), True)
        check("没被扣下", tr.withheld, [])
        print("\n[三、长图识别成功：用长图，和推导对得上]")
        nxt, tr, out = run(eve, lambda u: lines if u == img3 else [])
        check("开始与结束取自长图", (nxt[0], tr.until.get("鸣潮")), (datetime(2026, 10, 22, 10, 0), datetime(2026, 11, 11, 11, 59)))
        check("长图与推导核对 ✓", any("长图识别" in c and "推导 10-22 10:00 ✓" in c for c in tr.checks), True)
        check("行里是长图的开始和结束", "北京 10-22 10:00 开 · 11-11 11:59 结束" in out, True)
        print("\n[四、下一版维护预告出了：维护时刻进来源，下期行照旧有几点几分]")
        nxt, tr, out = run(datetime(2026, 10, 21, 13, 0), lambda u: None, maint=True)
        check("维护时刻进来源", any("3.8 维护 2026-11-12" in x for x in tr.sources), True)
        check("下期行照旧 10-22 10:00", "北京 10-22 10:00 开（第一期 09:59 结束后接着开，公告未出）" in out, True)
        check("没被扣下", tr.withheld, [])


    def _ww_bili_feed() -> None:
        """The Bilibili door against real answers recorded 2026-10-05 (fixture
    ww-bili-feed-2026-10-05.json: nav, three signed feed pages, the empty
    risk-control answer, the unsigned -352). On the game machine every try came
    back code 0 with no items and the relay took that as "no post"."""
        fx = json.loads((FX / "ww-bili-feed-2026-10-05.json").read_text(encoding="utf-8"))
        pages = [p["response"] for p in fx["pages"]]
        empty, unsigned, nav = fx["empty"]["response"], fx["unsigned"]["response"], fx["nav"]["response"]
        now = datetime(2026, 10, 5, 12, 0)
        post = "https://www.bilibili.com/opus/1253061864718336024"
        img3 = ("https://i0.hdslb.com/bfs/new_dyn/e1826ff7fe229d2f29d8a715a4ee4eee1955897084.jpg", 1080, 14717)

        def fake(feed):
            """A get() serving spi / nav, and `feed(n, offset)` for the n-th feed request."""
            asked = {"spi": 0, "feed": []}

            def get(url, cookie):
                if "finger/spi" in url:
                    asked["spi"] += 1
                    return {"code": 0, "data": {"b_3": f"B3-{asked['spi']}", "b_4": "B4=="}}
                if "/nav" in url:
                    return nav
                q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1], keep_blank_values=True))
                asked["feed"].append((q, cookie))
                return feed(len(asked["feed"]), q["offset"])
            return get, asked

        by_offset = {"": pages[0], pages[0]["data"]["offset"]: pages[1], pages[1]["data"]["offset"]: pages[2]}
        ticks = iter(range(1759600000, 1759700000, 7))
        slept: list = []
        get, asked = fake(lambda n, off: by_offset[off])
        got = _b._bili_poster("3.7", now, get, slept.append, lambda: next(ticks))
        check("B 站（真实三页）：第 3 页找到 3.7 版本资讯，第 3 张是 1080x14717 长图",
              (got[0], got[2][2], "3.7版本" in got[1]) if got else None, (post, img3, True))
        check("B 站：按 offset 翻页，每页都签名", [(q["offset"], "w_rid" in q and "wts" in q) for q, _c in asked["feed"]],
              [("", True), (pages[0]["data"]["offset"], True), (pages[1]["data"]["offset"], True)])
        check("B 站：nav 的 WBI 键", _b.bili_wbi_keys(nav),
              ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"))

        # risk control: the empty answer twice, then the list - each retry with a new buvid and a new wts
        get, asked = fake(lambda n, off: empty if n <= 2 else by_offset[off])
        got = _b._bili_poster("3.7", now, get, slept.append, lambda: next(ticks))
        check("B 站：空列表（风控）换新 buvid 重试后照样找到", got[0] if got else None, post)
        check("B 站：每次重试都换 buvid、重新签 wts",
              (asked["spi"], len({c for _q, c in asked["feed"][:3]}), len({q["wts"] for q, _c in asked["feed"][:3]})),
              (3, 3, 3))

        # every try empty: a source problem with the raw shape, not "no post"
        get, asked = fake(lambda n, off: empty)
        try:
            _b._bili_poster("3.7", now, get, slept.append, lambda: next(ticks))
            err = None
        except _b.BiliFeedProblem as e:
            err = str(e)
        check("B 站：一直空就报源出问题（不当没帖子）", err is not None and "page 1" in err, True)
        check("B 站：报错里带原始形状", err is not None and '"has_more": false' in err and "<0 items>" in err, True)
        check("B 站：试满次数才放弃", len(asked["feed"]), _b._BILI_TRIES)
        get, asked = fake(lambda n, off: unsigned)
        try:
            _b._bili_poster("3.7", now, get, slept.append, lambda: next(ticks))
            err = None
        except _b.BiliFeedProblem as e:
            err = str(e)
        check("B 站：-352 也是源出问题", err is not None and '"code": -352' in err, True)

        # the items stop carrying a publish time: a changed shape, said so
        shapeless = dict(pages[0], data=dict(pages[0]["data"], items=[{k: v for k, v in it.items() if k != "modules"}
                                                                       for it in pages[0]["data"]["items"]]))
        get, asked = fake(lambda n, off: shapeless)
        try:
            _b._bili_poster("3.7", now, get, slept.append, lambda: next(ticks))
            err = None
        except _b.BiliFeedProblem as e:
            err = str(e)
        check("B 站：条目读不出发布时间就报格式变了", err is not None and "shape changed" in err, True)

        # two weeks later the post sits deeper than four pages: still found
        deeper = [pages[0], pages[0], pages[0], pages[1], pages[2]]
        get, asked = fake(lambda n, off: deeper[n - 1])
        got = _b._bili_poster("3.7", now, get, slept.append, lambda: next(ticks))
        check("B 站：帖子在第 5 页也翻得到", (got[0] if got else None, len(asked["feed"])), (post, 5))
        # nothing for the version and the feed already older than a version: stop, no problem
        get, asked = fake(lambda n, off: by_offset[off])
        check("B 站：翻到比一个版本还早就停，不算源坏",
              (_b._bili_poster("3.8", datetime(2026, 12, 1, 12, 0), get, slept.append, lambda: next(ticks)),
               len(asked["feed"])), (None, 1))
        last = dict(pages[0], data=dict(pages[0]["data"], has_more=False))
        get, asked = fake(lambda n, off: last)
        check("B 站：列表到底了就停", (_b._bili_poster("3.8", now, get, slept.append, lambda: next(ticks)),
                                    len(asked["feed"])), (None, 1))
        # 2026-11-07 21:48: 3.8 maintenance notice out, 3.8版本前瞻 posted on page 1, 3.8版本资讯 not out
        # yet; once page 1's unpinned items pass the preview timestamp, stop instead of paging into 3.7 (page 4 empty)
        p1_38 = json.loads(json.dumps(pages[0], ensure_ascii=False).replace("3.7版本前瞻", "3.8版本前瞻"))
        p1_38["data"]["items"][0]["modules"]["module_author"]["pub_ts"] = p1_38["data"]["items"][8]["modules"]["module_author"]["pub_ts"]
        get, asked = fake(lambda n, off: p1_38 if off == "" else empty)
        check("B 站：已翻过本版前瞻仍无版本资讯就停在当页，不继续翻旧版撞风控",
              (_b._bili_poster("3.8", now, get, slept.append, lambda: next(ticks)),
               len(asked["feed"])), (None, 1))
        try:
            _b.bili_wbi_keys({"code": -101, "data": {"isLogin": False}})
            err = None
        except _b.BiliFeedProblem as e:
            err = str(e)
        check("B 站：nav 没给 WBI 键就报源出问题", err is not None and "isLogin" in err, True)

        # through the poster lookup: 库街区 has no post, Bilibili stays empty -> None, the
        # problem with its shape in the trace (and saved with it); a working 库街区
        # copy is still read first and Bilibili is not asked
        pause = _b._pause
        _b._pause = slept.append
        try:
            get, asked = fake(lambda n, off: empty)
            tr = _b.Trace.new()
            check("库街区没帖、B 站被风控：没有时间（不编）",
                  _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now, lambda u: [], tr,
                                       lambda p, d: {"data": {"list": []}}, get), None)
            check("B 站的问题记进来源记录，带原始形状", tr.problems,
                  ['鸣潮｜版本资讯｜B 站｜BiliFeedProblem: space feed page 1 listed nothing in 5 tries (risk control, '
               'not "no post"): {"code": 0, "message": "0", "data": {"update_num": "0", "update_baseline": "", '
               '"offset": "", "has_more": false, "total": "0", "items": "<0 items>"}, "ttl": 1}'])
            import tempfile
            with tempfile.TemporaryDirectory() as sd:
                _b.save_trace(Path(sd), now, "x", tr)
                saved = json.loads((Path(sd) / "banners" / "2026-10-05.json").read_text(encoding="utf-8"))
            check("来源问题落盘", saved.get("problems"), tr.problems)
        finally:
            _b._pause = pause

        # WBI signature: the browser's own encoding (encodeURIComponent, keys sorted,
        # !'()* dropped), computed with Node's crypto as an independent reference -
        # the same Node code reproduces the community worked example above
        check("WBI 签名：和浏览器写法（Node 算的）一致",
              _b.bili_sign({"host_mid": 1955897084, "offset": "",
                            "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
                            "features": "itemOpusStyle,listOnlyfans", "kw": "五一四", "odd": "(19)*!'x"},
                           "7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45", 1759682552),
              "dm_img_inter=%7B%22ds%22%3A%5B%5D%2C%22wh%22%3A%5B0%2C0%2C0%5D%2C%22of%22%3A%5B0%2C0%2C0%5D%7D"
          "&features=itemOpusStyle%2ClistOnlyfans&host_mid=1955897084&kw=%E4%BA%94%E4%B8%80%E5%9B%9B"
          "&odd=19x&offset=&wts=1759682552&w_rid=a3e791815ebb470da018ad03be1e556f")


    def _ef_history() -> None:
        """Endfield past banners (2026-10-06): every 特许寻访 the official site still
    lists, read by the same reader as the next-banner line, replayed at the time
    each notice went up. Fixtures: ef-history-cms/ (the site's own CMS API, raw).
    """
        d = FX / "ef-history-cms"

        def get(url):
            if m := re.search(r"[?&]page=(\d+)", url):
                return (d / f"list-p{m.group(1)}.json").read_text(encoding="utf-8")
            cid = re.search(r"/bulletin/(\w+)\?", url).group(1)
            return (d / f"post-{cid}.json").read_text(encoding="utf-8")

        rows = _b.endfield_history(get)
        f = "%m-%d %H:%M"
        nxt = _b.endfield_next_from_news(datetime(2026, 9, 1, 20, 0), get=get)
        check("终末地下期和往期同一个接口：冬猎 提弗洛斯 09-02 12:00 开",
              (nxt[0].strftime(f), nxt[1]) if nxt else None, ("09-02 12:00", "提弗洛斯「冬猎」"))
        check("终末地下期：冬猎开了以后没有下期", _b.endfield_next_from_news(datetime(2026, 9, 3), get=get), None)
        check("终末地往期：官网 11 期特许寻访，开始结束全按公告原文",
              [(v, w, a.strftime(f) if a else None, b.strftime(f) if b else None) for v, w, a, b, _ in rows],
              [("公测", "莱万汀「熔火灼痕」", "01-22 11:00", "02-07 11:59"),
               ("公测", "洁尔佩塔「轻飘飘的信使」", "02-07 12:00", "02-24 11:59"),
               ("公测", "伊冯「热烈色彩」", "02-24 12:00", "03-12 06:00"),
               ("新潮起，故渊离", "汤汤「河流的女儿」", "03-12 12:00", "03-29 11:59"),
               ("新潮起，故渊离", "洛茜「狼珀」", "03-29 12:00", "04-17 06:00"),
               ("春晓时", "庄方宜「春雷动，万物生」", "04-17 12:00", "05-22 11:59"),
               ("寻遗散记", "弭弗「拳出无悔」", "06-05 12:00", "06-26 11:59"),
               ("寻遗散记", "卡缪「逐罪者」", "06-26 12:00", "07-16 06:00"),
               ("向渊行", "诀「临渊望北」", "07-16 12:00", "08-09 11:59"),
               ("向渊行", "梨诺「晨星于此闪耀」", "08-09 12:00", "09-02 06:00"),
               ("雪凇幽梦", "提弗洛斯「冬猎」", "09-02 12:00", "09-30 11:59")])
        check("往期每行都带官网出处", all(src.startswith(_b._EF_NEWS + "/") for *_, src in rows), True)
        import tempfile
        sd = Path(tempfile.mkdtemp())
        got_rows, chg = _b.update_endfield_history(sd, get)
        check("终末地往期记账：第一次记下 11 期，没有变化", (len(got_rows), chg), (11, []))
        check("终末地往期记账：同一份再记，没有变化", _b.update_endfield_history(sd, get)[1], [])
        hist_file = json.loads((sd / "banners" / "history.json").read_text(encoding="utf-8"))
        hist_file["终末地"]["雪凇幽梦|提弗洛斯「冬猎」"] = [["2026-09-02 12:00", "2026-09-30 10:00"]]
        (sd / "banners" / "history.json").write_text(json.dumps(hist_file, ensure_ascii=False), encoding="utf-8")
        chg = _b.update_endfield_history(sd, get)[1]
        check("终末地往期记账：记下的结束时刻和这次读到的不一样就说出来",
              (len(chg), "提弗洛斯" in chg[0] and "09-30 10:00" in chg[0]), (1, True))
        # Gate for any later change to the reader: the fixtures must keep covering several
        # periods and several 开放时间 wordings, counted from the fixtures themselves.
        posts = _b.ef_cms_posts(get)
        kinds = set()
        for _cid, title, _ts, text in posts:
            if "特许寻访说明" in title and (m := _b._EF_SPAN.search(text)):
                g = m.groups()
                kinds.add(("钟点" if g[0] else "版本开启后" if g[5] else "公测开启后",
                           "钟点" if g[7] else "版本更新维护前"))
        check("闸：样本至少来自 3 个不同期", len({v for v, *_ in rows}) >= 3, True)
        check("闸：样本至少有 3 种开放时间写法", len(kinds) >= 3, True)
        # Skland's own end for 晨星于此闪耀 (endfield_pools.json) is the window start too
        sk = parse_endfield(json.loads((FX / "endfield_pools.json").read_text(encoding="utf-8")), lambda g: "梨诺")
        check("「版本更新维护前」= 下一次维护开始，和森空岛 poolEndAtTs 一致",
              [b for _, w, _, b, _ in rows if w == "梨诺「晨星于此闪耀」"], [sk[0].end])
        # Replay the next-banner line as it would have run one hour after each notice
        # went up (only the posts already published then), and mid-banner.
        tz = _b.SERVER_TZ

        def upto(when):
            return [p for p in posts if p[2] <= when.replace(tzinfo=tz).timestamp()]

        for r in _b.ef_banner_posts(posts):
            t = datetime.fromtimestamp(r["posted"], tz=tz).replace(tzinfo=None) + timedelta(hours=1)
            seen = upto(t)
            want = (None, r["who"]) if r["who"] == "弭弗「拳出无悔」" else (r["start"], r["who"])
            check(f"回放：{r['who']} 公告后一小时报下期", _b.ef_next_banner(seen, t), want)
            mid = r["start"] + (r["end"] - r["start"]) / 2
            check(f"回放：{r['who']} 开池期间不再报成下期",
                  _b.ef_next_banner(upto(mid), mid), None)


    def _ef_briefing() -> None:
        """2026-10-08 13:12 the user reported the Endfield next banner missing although it
    was announced: the version briefing named it from 10-06 20:00 (UTC+8) on, while
    the banner notice the report waited for was not out yet."""
        fx = FX / "ef-briefing-v1d6"
        page = (fx / "latest.html").read_text(encoding="utf-8")
        bundle = (fx / "bundle.js").read_text(encoding="utf-8")

        def get(url):
            if url == _b._EF_BRIEFING:
                return page
            if url.endswith("/_version_briefing/v1d6/version-v1d6.0dca1e.js"):
                return bundle
            raise OSError(url)
        ver, rows = _b.ef_briefing_banners(bundle)
        check("briefing: version name", ver, "丹青渡")
        check("briefing: both operators with their banners", [r["who"] for r in rows],
              ["祀「万物更新」", "明河「烟火邀星河」"])
        check("briefing: startsAfterUpdate -> no opening clock", (rows[0]["open"], rows[0]["close"]),
              (None, datetime(2026, 11, 5, 11, 59)))
        check("briefing: a printed opening is kept", (rows[1]["open"], rows[1]["close"]),
              (datetime(2026, 11, 5, 12, 0), datetime(2026, 11, 26, 6, 0)))
        check("briefing: 10-08 -> 祀, after the update, version day 10-15",
              _b.endfield_next_from_briefing(datetime(2026, 10, 8, 12, 27), set(), get=get),
              (None, "祀「万物更新」", "丹青渡", datetime(2026, 10, 15, 7, 0)))
        check("briefing: once 祀 is out -> 明河 at its printed time",
              _b.endfield_next_from_briefing(datetime(2026, 10, 16), {"祀"}, get=get),
              (datetime(2026, 11, 5, 12, 0), "明河「烟火邀星河」", "丹青渡", None))
        check("briefing: a running operator is not the next one",
              _b.endfield_next_from_briefing(datetime(2026, 10, 8), {"祀", "明河"}, get=get), None)
        check("briefing: all opened -> none", _b.endfield_next_from_briefing(datetime(2026, 11, 6), set(), get=get), None)
        free = bundle.replace('"gachaPoolName":{"zh-cn":"万物更新"', '"gachaPoolName":{"zh-cn":""', 1)
        check("briefing: an operator without a banner is skipped, the rest kept",
              [r["who"] for r in _b.ef_briefing_banners(free)[1]] if free != bundle else "fixture text not found",
              ["明河「烟火邀星河」"])
        check("briefing: no operator on a banner -> empty, not an error",
              _b.ef_briefing_banners("var a=JSON.parse('{\"characters\":[{\"id\":\"x\"}]}');"), ("", []))
        for bad in ("!function(){}();", "var a=JSON.parse('{\"weapons\":[]}');"):
            try:
                _b.ef_briefing_banners(bad)
                check("briefing: a changed shape raises", "no error", "ValueError")
            except ValueError:
                pass

        # Through _endfield: no banner notice yet, so the briefing gives the line, and
        # its date passes the source gate. The official bulletin (_json, game-hub.hypergryph.com)
        # is offline: no relay test reaches the internet, and the line does not come from it.
        real_text, real_news, real_json = _b._text, _b.endfield_next_from_news, _b._json

        def no_api(url, *a, **k):
            raise OSError("offline")

        _b._text, _b.endfield_next_from_news, _b._json = (lambda url, *a, **k: get(url)), (lambda now: None), no_api
        try:
            tr, notes = _b.Trace.new(), {}
            got, nxt = _b._endfield(None, lambda path: {"data": {"list": []}}, datetime(2026, 10, 8, 12, 27),
                                    trace=tr, notes=notes)
        finally:
            _b._text, _b.endfield_next_from_news, _b._json = real_text, real_news, real_json
        out = render(got, datetime(2026, 10, 8, 12, 27), {"终末地": nxt}, notes=notes, trace=tr)
        check("briefing: 10-08 report line",
              "· 下期：万物更新 · 祀 · 「丹青渡」版本更新后开（版本 10-15 开启）" in out, True)
        check("briefing: nothing withheld", tr.withheld, [])


    def _sf_pool_times() -> None:
        """Silent-failure audit rows banners.py:244 and :424: a Skland pool or a Kuro
    wiki tab whose times could not be read was dropped without a word, and a
    renamed field emptied the section into 「当期无新角色卡池」."""
        name = lambda gid: "梨诺"  # noqa: E731
        ef = json.loads((FX / "endfield_pools.json").read_text(encoding="utf-8"))
        renamed = json.loads(json.dumps(ef))
        for p in renamed:
            p["poolStartAt"] = p.pop("poolStartAtTs")
        with _logs():
            try:
                parse_endfield(renamed, name)
                got = "no error"
            except ValueError:
                got = "ValueError"
        check("silent 244: every Skland pool without readable times raises", got, "ValueError")
        bad = json.loads(json.dumps(ef))
        bad[0]["name"], bad[0]["poolEndAtTs"] = "坏池", "2026-09-02"
        with _logs() as recs:
            got = parse_endfield(ef + bad, name)
        check("silent 244: the readable pool is kept", [b.name for b in got], ["晨星于此闪耀"])
        check("silent 244: one unreadable pool is one WARNING", _warned(recs, "坏池"), 1)
        with _logs() as recs:
            # The parser's own answer only: whether a banner is running is _endfield's,
            # with the official sources (_audit_1108_endfield: Skland empty while 明河
            # was open from 11-05 to 11-08).
            check("silent 244: an empty char-pool parses to no Skland rows", parse_endfield([], name), [])
        check("silent 244: ...and the parser says nothing about it", _warned(recs, ""), 0)

        home = json.loads((FX / "wuwa_home.json").read_text(encoding="utf-8"))
        names = {"1536353668409655296": "清宵", "1488852222116831232": "达妮娅"}
        who = lambda e: names.get(e, "")  # noqa: E731

        def tabs(h):
            return [t for m in h["data"]["contentJson"]["sideModules"] if "角色" in str(m.get("title"))
                    for t in m["content"]["tabs"]]
        reshaped = json.loads(json.dumps(home))
        for t in tabs(reshaped):
            t["countDown"]["dateRange"] = ["2026/08/20 11:00", "2026/09/10 09:59"]
        with _logs():
            try:
                parse_wuwa(reshaped, who)
                got = "no error"
            except ValueError:
                got = "ValueError"
        check("silent 424: every Kuro tab with an unreadable dateRange raises", got, "ValueError")
        moved = json.loads(json.dumps(home))
        for t in tabs(moved):
            t["countDown"] = {"range": t["countDown"]["dateRange"]}
        try:
            parse_wuwa(moved, who)
            got = "no error"
        except ValueError:
            got = "ValueError"
        check("silent 424: a moved dateRange raises too", got, "ValueError")
        one = json.loads(json.dumps(home))
        tabs(one)[1]["countDown"]["dateRange"] = ["8月20日", "9月10日"]
        with _logs() as recs:
            got = parse_wuwa(one, who)
        check("silent 424: the readable tab is kept", [b.name for b in got], ["仙风玉影水天清"])
        check("silent 424: one unreadable tab is one WARNING", _warned(recs, "予明日以谎言"), 1)


    def _sf_rarity() -> None:
        """Silent-failure audit row banners.py:798: one PRTS timeout cached -1 for the
    life of the process, so a running six-star banner vanished from every report
    until the relay restarted, with no log line."""
        saved = dict(_b._rarity_cache)
        _b._rarity_cache.clear()
        calls: list = []

        def flaky(n):
            calls.append(n)
            if len(calls) == 1:
                raise OSError("timed out")
            return "|稀有度=5"
        real = (_b._ak_prts_rows, _b._json, _b._text)

        def offline(url, *a, **k):
            raise OSError(f"offline: {url}")
        now = datetime(2026, 9, 10, 12, 0)
        row = _b.Banner("明日方舟", "某池", ("甲", "乙"), datetime(2026, 9, 1), datetime(2026, 9, 20))
        try:
            first = _b.ak_rarity("某六星", flaky)
            second = _b.ak_rarity("某六星", flaky)
        finally:
            _b._rarity_cache.clear()
            _b._rarity_cache.update(saved)
        check("silent 798: a failed lookup is -1 this time", first, -1)
        check("silent 798: a failed lookup is not cached, the next one asks again", (second, len(calls)), (5, 2))
        # s20 #2: a running banner whose rarity is unknown is never faked and never
        # dropped in silence - the game reads as not read (collect puts it in `failed`).
        out, _tr, _recs = _ak_offline(now, [row])
        check("silent 798: unknown rarity is a failed read, not an empty one",
              (type(out).__name__, "甲、乙" in str(out)), ("RuntimeError", True))
        rows, _nxt, failed, text, recs = _collect_offline(now, [row])
        check("silent 798: collect lists 明日方舟 as not read", [f for f in failed if f.startswith("明日方舟")], ["明日方舟"])
        block = _block(text, "明日方舟")
        check("silent 798: the report says not read, never 「当期无新角色卡池」",
              ("这次没读到" in block, "当期无新角色卡池" in block), (True, False))
        check("silent 798: one WARNING names both operators, with the cause", _warned_exc(recs, "甲、乙"), 1)
        check("silent 798: and only one about rarity", _warned_exc(recs, "稀有度"), 1)
        # Review of 7fa60c96: the partial failure raised out of _arknights, so the
        # next banner was never worked out and the group's 「明天开」 notice was lost.
        soon = _b.Banner("明日方舟", "下一池", ("丙",), datetime(2026, 9, 11, 16, 0), datetime(2026, 9, 25, 3, 59))
        rows, nxt, failed, text, _recs = _collect_offline(now, [row, soon], rarity={"丙": 5})
        check("review 7fa60c96: one rarity lookup failing still lists 明日方舟 as not read",
              [f for f in failed if f.startswith("明日方舟")], ["明日方舟"])
        check("review 7fa60c96: and the next banner is still worked out",
              nxt.get("明日方舟"), (datetime(2026, 9, 11, 16, 0), "丙「下一池」"))
        check("review 7fa60c96: so the group still hears it opens tomorrow",
              [(g, who) for g, _w, who in _b.opening_tomorrow(now, nxt)], [("明日方舟", "丙「下一池」")])

        # The announced next banner (PRTS has registered it, not open yet): a failed
        # lookup dropped it and the line fell to 「官方未公告」 in silence.
        ahead = _b.Banner("明日方舟", "下一池", ("丙", "丁"), datetime(2026, 9, 20), datetime(2026, 10, 4))
        _b._rarity_cache.clear()
        try:
            _b._ak_prts_rows, _b._json, _b._text = (lambda tr: [ahead]), offline, offline
            with _logs() as recs:
                _debut, nxt = _b._arknights(now, trace=_b.Trace.new())
        finally:
            _b._ak_prts_rows, _b._json, _b._text = real
            _b._rarity_cache.clear()
            _b._rarity_cache.update(saved)
        check("silent 798 next: unknown rarity is still not the next banner", nxt, None)
        check("silent 798 next: one WARNING names both operators", _warned(recs, "丙、丁"), 1)
        check("silent 798 next: and only one about rarity", _warned(recs, "稀有度"), 1)


    def _ak_offline(now, prts_rows, get=None, rarity=None):
        """_arknights with every web source stubbed: PRTS rows are `prts_rows`, the
    official site is `get` (an ak_site; None = offline), `rarity` seeds the PRTS
    rarity cache, the rest is offline. Returns ((debut, next) or the exception,
    the trace, log records)."""
        real = (_b._ak_prts_rows, _b._json, _b._text)
        saved = dict(_b._rarity_cache)

        def offline(url, *a, **k):
            raise OSError(f"offline: {url}")

        def text(url, *a, **k):
            if get is None:
                raise OSError(f"offline: {url}")
            return get(url)
        _b._ak_prts_rows, _b._json, _b._text = (lambda tr: list(prts_rows)), offline, text
        _b._rarity_cache.clear()
        _b._rarity_cache.update(rarity or {})
        tr = _b.Trace.new()
        try:
            with _logs() as recs:
                try:
                    out = _b._arknights(now, trace=tr)
                except Exception as e:  # noqa: BLE001
                    out = e
        finally:
            _b._ak_prts_rows, _b._json, _b._text = real
            _b._rarity_cache.clear()
            _b._rarity_cache.update(saved)
        return out, tr, recs


    def _warned_exc(recs: list, part: str) -> int:
        """Like _warned, counting the exception text too: errwatch puts
    「ExcType: message」 after the line in the group message."""
        return sum(1 for r in recs if r.levelno == logging.WARNING
                   and (part in r.getMessage() or (r.exc_info and part in str(r.exc_info[1]))))


    def _block(text: str, game: str) -> str:
        """One game's lines of the rendered section, its name line first."""
        out: list[str] = []
        for line in text.split("\n"):
            if line in ("明日方舟", "鸣潮", "终末地"):
                if out:
                    break
                if line == game:
                    out.append(line)
            elif out:
                out.append(line)
        return "\n".join(out)


    def _collect_offline(now, prts_rows, rarity=None, sk_get=None, ef_bulletin=None):
        """collect + render with every web source stubbed: Arknights as _ak_offline
    (official site offline), Endfield through `sk_get` (None: no Skland token),
    its version bulletin list is `ef_bulletin` (None = unreachable), Wuthering
    Waves reads nothing. Returns (rows, next, failed, rendered text, log records)."""
        real = (_b._ak_prts_rows, _b._json, _b._text, _b._wuwa, _b.endfield_next_from_news)
        saved = dict(_b._rarity_cache)

        def offline(url, *a, **k):
            raise OSError(f"offline: {url}")

        def js(url, *a, **k):
            if url == _b._EF_BULLETIN and ef_bulletin is not None:
                return ef_bulletin
            raise OSError(f"offline: {url}")
        _b._ak_prts_rows, _b._json, _b._text = (lambda tr: list(prts_rows)), js, offline
        _b._wuwa, _b.endfield_next_from_news = (lambda *a, **k: ([], None)), (lambda now: None)
        _b._rarity_cache.clear()
        _b._rarity_cache.update(rarity or {})
        failed: list[str] = []
        tr = _b.Trace.new()
        try:
            with _logs() as recs:
                rows, nxt = _b.collect(now, sk_get=sk_get, failed=failed, trace=tr)
                text = render(rows, now, nxt, {}, tr, failed, {})
        finally:
            _b._ak_prts_rows, _b._json, _b._text, _b._wuwa, _b.endfield_next_from_news = real
            _b._rarity_cache.clear()
            _b._rarity_cache.update(saved)
        return rows, nxt, failed, text, recs


    def _ak_site_1006():
        """The official site as of 2026-10-06: post 5101 announces 海渊巡游 for 10-09 12:00."""
        fx = lambda n: (FX / n).read_text(encoding="utf-8")  # noqa: E731
        return ak_site(ak_lists(fx("ak-history-news-2026-10-06.txt")), {"5101": ak_post_fx("5101")})


    def _ak_prts_clock() -> None:
        """s20 #1: since 2025-12 PRTS writes 07:00 for banners the official posts open
    at 12:00 (cid 9605). A PRTS row for the same banner counted as "ran before",
    so the official post was dropped as a rerun and the next-banner line and the
    group notice carried PRTS's 07:00."""
        row = _b.Banner("明日方舟", "海渊巡游", ("克莱门莎",), datetime(2026, 10, 9, 7, 0), datetime(2026, 10, 23, 3, 59))
        out, tr, _recs = _ak_offline(datetime(2026, 10, 8, 21, 45), [row], _ak_site_1006(), {"克莱门莎": 5})
        nxt = out[1] if isinstance(out, tuple) else out
        check("PRTS 07:00 那行不顶掉官网 12:00", nxt, (datetime(2026, 10, 9, 12, 0), "克莱门莎「海渊巡游」"))
        check("官网的 12:00 进了来源闸", "10-09 12:00" in tr.starts, True)
        due = opening_tomorrow(datetime(2026, 10, 8, 21, 45), {"明日方舟": nxt} if isinstance(nxt, tuple) else {})
        check("群通知写官网的 12:00", group_notice(due)[1], "· 明日方舟　10-09 12:00 开　克莱门莎「海渊巡游」")
        # A real rerun: an earlier row with the same six-star that has ended still marks it.
        old = _b.Banner("明日方舟", "旧池", ("克莱门莎",), datetime(2026, 1, 1, 16, 0), datetime(2026, 1, 15, 3, 59))
        out, _tr, _recs = _ak_offline(datetime(2026, 10, 8, 21, 45), [old], _ak_site_1006(), {"克莱门莎": 5})
        check("真复刻（早先一行已经结束）照旧不当下一期", out[1] if isinstance(out, tuple) else out, None)


    def _ef_no_token() -> None:
        """s20 #3: with no Skland token Endfield was skipped and not listed as not
    read, so the report said 当期无新角色卡池 and 下期：官方未公告."""
        _rows, _nxt, failed, text, _recs = _collect_offline(datetime(2026, 8, 20), [])
        check("没有森空岛令牌：终末地记为没读到", [f for f in failed if f.startswith("终末地")], ["终末地（没有森空岛令牌）"])
        check("没有森空岛令牌：日报写没读到", _block(text, "终末地"), "终末地\n· 这次没读到（没有森空岛令牌），不是没有卡池")


    def _ef_offline(sk_get, now, *, pool_ends=None, bulletin_html=None, pages=None,
                    bulletin_title="「x」版本更新说明", trace=None):
        """_endfield with every web source stubbed: Skland is `sk_get`, the version
    bulletin is `bulletin_html` (None = unreachable) under `bulletin_title`, `pages`
    maps URLs read as text, the rest is offline. Returns ((got, next) or the
    exception, log records)."""
        real = (_b._json, _b._text, _b.endfield_next_from_news, _b.endfield_pool_ends)

        def js(url, *a, **k):
            if url == _b._EF_BULLETIN and bulletin_html is not None:
                return {"data": {"list": [{"title": bulletin_title, "data": {"html": bulletin_html}}]}}
            raise OSError(f"offline: {url}")

        def offline(url, *a, **k):
            if pages and url in pages:
                return pages[url]
            raise OSError(f"offline: {url}")
        _b._json, _b._text, _b.endfield_next_from_news = js, offline, (lambda now: None)
        if pool_ends is not None:
            _b.endfield_pool_ends = pool_ends
        try:
            with _logs() as recs:
                try:
                    out = _b._endfield(None, sk_get, now, trace=trace if trace is not None else _b.Trace.new())
                except Exception as e:  # noqa: BLE001
                    out = e
        finally:
            _b._json, _b._text, _b.endfield_next_from_news, _b.endfield_pool_ends = real
        return out, recs


    def _sf_ef_names() -> None:
        """Silent-failure audit row banners.py:1349: Skland item/info failing gave the
    UP operator no name, parse_endfield dropped the banner, and nothing was said
    (the Wuthering Waves twin warns)."""
        ef = json.loads((FX / "endfield_pools.json").read_text(encoding="utf-8"))
        two = json.loads(json.dumps(ef + ef))
        two[1]["name"] = "另一池"
        two[1]["chars"][0]["pcLink"] = two[1]["chars"][0]["pcLink"].replace("=1683", "=1700")

        def sk(path):
            if path == "/web/v1/wiki/char-pool":
                return {"data": {"list": two}}
            raise OSError("Skland 502")
        out, recs = _ef_offline(sk, datetime(2026, 8, 20))
        # s20 #2: no name faked, and no banner dropped in silence either: the game
        # reads as not read (collect puts it in `failed`).
        check("silent 1349: a lookup that failed is a failed read, not an empty one",
              (type(out).__name__, "1683、1700" in str(out)), ("RuntimeError", True))
        _rows, _nxt, failed, text, recs = _collect_offline(datetime(2026, 8, 20), [], sk_get=sk)
        check("silent 1349: collect lists 终末地 as not read", [f for f in failed if f.startswith("终末地")], ["终末地"])
        block = _block(text, "终末地")
        check("silent 1349: the report says not read, never 「当期无新角色卡池」",
              ("这次没读到" in block, "当期无新角色卡池" in block), (True, False))
        check("silent 1349: one WARNING names both lookups, with the cause", _warned_exc(recs, "1683、1700"), 1)
        check("silent 1349: only one about the names", _warned_exc(recs, "名字"), 1)


    def _sf_ef_pool_ends() -> None:
        """Silent-failure audit row banners.py:1375: endfield_pool_ends raising on the
    bulletin emptied the bulletin's pools and closing times without a word, and
    the official next-banner time was replaced by a weaker source."""
        ef = json.loads((FX / "endfield_pools.json").read_text(encoding="utf-8"))
        html = (FX / "endfield_notice.html").read_text(encoding="utf-8")

        def sk(path):
            if path == "/web/v1/wiki/char-pool":
                return {"data": {"list": ef}}
            return {"data": {"item": {"name": "梨诺"}}}

        def broken(html):
            raise ValueError("day is out of range for month")
        out, recs = _ef_offline(sk, datetime(2026, 8, 20), pool_ends=broken, bulletin_html=html)
        check("silent 1375: the running banner still comes from Skland",
              [b.chars for b in out[0]] if isinstance(out, tuple) else out, [("梨诺",)])
        check("silent 1375: the unreadable bulletin times are one WARNING", _warned(recs, "版本更新说明"), 1)
        check("silent 1375: with the traceback",
              [bool(r.exc_info) for r in recs if r.levelno == logging.WARNING and "版本更新说明" in r.getMessage()],
              [True])
        out, recs = _ef_offline(sk, datetime(2026, 8, 20), bulletin_html=html)
        check("silent 1375: a readable bulletin says nothing about it", _warned(recs, "版本更新说明"), 0)


    def _ef_no_version_notes() -> None:
        """s20 #4: a bulletin list with no 版本更新说明 entry gave no debuts and no
    warning, so every running banner vanished and the report said
    当期无新角色卡池. Read 2026-10-13 off the live list: the entry posted 09-02 09:00
    is still there beside 10-13's 预下载与更新预告, so this has not happened yet."""
        ef = json.loads((FX / "endfield_pools.json").read_text(encoding="utf-8"))

        def sk(path):
            if path == "/web/v1/wiki/char-pool":
                return {"data": {"list": ef}}
            return {"data": {"item": {"name": "梨诺"}}}
        out, recs = _ef_offline(sk, datetime(2026, 8, 20), bulletin_html="<p>预下载</p>",
                                bulletin_title="预下载与\n更新预告")
        check("没有版本更新说明：在开的池子照旧来自森空岛",
              [b.chars for b in out[0]] if isinstance(out, tuple) else out, [("梨诺",)])
        check("没有版本更新说明：当作公告没读到，说一次", _warned(recs, "公告取不到"), 1)


    def _ak_next(now, get):
        """The next Arknights banner as _arknights picks it from the official posts:
    the earliest one not yet open, whichever post announces it."""
        fut = [(st, who) for st, who, _p, _en, _c in _b.arknights_banner_posts(now, get) if st > now]
        return min(fut) if fut else None


    def _no_test_only_api() -> None:
        """s20 #7: arknights_next_from_news and section() had callers only in tests
    (the relay calls collect and render, and section() skipped save_trace)."""
        check("只有测试在用的入口已删", [n for n in ("arknights_next_from_news", "section") if hasattr(_b, n)], [])


    def _crosscheck_honest() -> None:
        """s20 #6: the trace's cross-checks. Endfield filled a clock the bulletin does
    not print with Skland's own value and then compared Skland with itself (✓ with
    nothing checked); Arknights missed its post when PRTS prefixes the name and
    writes 07:00 for the post's 12:00."""
        ef = json.loads((FX / "endfield_pools.json").read_text(encoding="utf-8"))
        html = (FX / "endfield_notice.html").read_text(encoding="utf-8")

        def sk(path):
            if path == "/web/v1/wiki/char-pool":
                return {"data": {"list": ef}}
            return {"data": {"item": {"name": "梨诺"}}}
        # 晨星于此闪耀: the bulletin gives 08-09 12:00 to open and no closing clock.
        tr = _b.Trace.new()
        _ef_offline(sk, datetime(2026, 8, 20), bulletin_html=html, trace=tr)
        check("终末地：公告没写结束就不拿森空岛自己比", tr.checks, ["终末地：森空岛=公告 ✓（公告没写结束时刻，只核了开始）"])
        # 临渊望北 (诀): the bulletin opens it 「版本更新后」 and closes it 08-09 11:59.
        jue = json.loads(json.dumps(ef))
        jue[0].update(name="临渊望北", poolStartAtTs="1784700000", poolEndAtTs="1786247999")

        def sk2(path):
            if path == "/web/v1/wiki/char-pool":
                return {"data": {"list": jue}}
            return {"data": {"item": {"name": "诀"}}}
        tr = _b.Trace.new()
        _ef_offline(sk2, datetime(2026, 8, 1), bulletin_html=html, trace=tr)
        check("终末地：公告开始写版本更新后，只核结束",
              tr.checks, ["终末地：森空岛=公告 ✓（公告开始写「版本更新后」，只核了结束）"])
        # Arknights: PRTS 【限定寻访·夏季】 prefix and 07:00, the post 12:00 the same day.
        row = _b.Banner("明日方舟", "【限定寻访·夏季】海渊巡游", ("克莱门莎",),
                        datetime(2026, 10, 9, 7, 0), datetime(2026, 10, 23, 3, 59))
        out, tr, _recs = _ak_offline(datetime(2026, 10, 10, 12, 0), [row], _ak_site_1006(), {"克莱门莎": 5})
        got = " ".join(tr.checks)
        # Since 11-09 (alarm #157, Gemini): the 07:00 PRTS lists is its own bookkeeping, the
        # post's 12:00 is first-hand, so the opening is corrected and the line is a ✓.
        check("方舟：PRTS 名字带前缀、07:00 也对得上官网那帖，开始按官网补正",
              ("找不到" in got, "池名" in got, "✗" in got,
               "开始不同（PRTS 10-09 07:00 / 官网公告 10-09 12:00），已按官网公告补正 ✓" in got),
              (False, False, False, True))
        check("方舟：返回的那一行开始也是官网的 12:00",
              [(b.name, b.start) for b in out[0] if b.chars == ("克莱门莎",)],
              [("【限定寻访·夏季】海渊巡游", datetime(2026, 10, 9, 12, 0))])


    def _sf_ef_brief_time() -> None:
        """Silent-failure audit row banners.py:1631: a briefing openTime in neither
    known format read as "not set", so the announced next operator silently
    became 「官方未公告」."""
        check("silent 1631: empty is not set", _b._ef_brief_time(""), None)
        check("silent 1631: both known shapes",
              (_b._ef_brief_time("2026/10/15 7:00:00"), _b._ef_brief_time("2026-11-05T11:59")),
              (datetime(2026, 10, 15, 7, 0), datetime(2026, 11, 5, 11, 59)))
        try:
            _b._ef_brief_time("2026年10月15日 07:00")
            got = "None"
        except ValueError:
            got = "ValueError"
        check("silent 1631: an unknown shape raises", got, "ValueError")
        fx = FX / "ef-briefing-v1d6"
        page = (fx / "latest.html").read_text(encoding="utf-8")
        bundle = re.sub(r'openTime":"(\d{4})/(\d{1,2})/(\d{1,2}) ', r'openTime":"\1年\2月\3日 ',
                        (fx / "bundle.js").read_text(encoding="utf-8"))
        js = _b._EF_BRIEFING_JS.search(page).group(1)
        out, recs = _ef_offline(lambda path: {"data": {"list": []}}, datetime(2026, 10, 8, 12, 27),
                                pages={_b._EF_BRIEFING: page, js: bundle})
        check("silent 1631: the reshaped briefing is not 「官方未公告」 in silence",
              _warned(recs, "新版本导览取不到"), 1)
        out, recs = _ef_offline(lambda path: {"data": {"list": []}}, datetime(2026, 10, 8, 12, 27),
                                pages={_b._EF_BRIEFING: page, js: (fx / "bundle.js").read_text(encoding="utf-8")})
        check("silent 1631: the real briefing still gives 祀",
              out[1] if isinstance(out, tuple) else out, (None, "祀「万物更新」"))
        check("silent 1631: and says nothing", _warned(recs, "新版本导览"), 0)


    def _sf_ww_first_half_end() -> None:
        """Silent-failure audit rows banners.py:2655 / 2666 / 2678: when the Kuro
    notice and the poster doors FAILED (an exception, not "not published"),
    _wuwa_first_half_end returned None in silence and the report printed the
    "next banner: not announced" line (「下期：官方未公告」) as fact."""
        now = datetime(2026, 10, 10, 12, 0)

        def down(*a, **k):
            raise OSError("timed out")

        def empty(path, payload):
            return {"data": {"list": []}}
        post = ("https://www.kurobbs.com/mc/post/1", "3.8版本资讯", [("https://img/1.png", 733, 10000)])
        real = (_b._kuro_poster, _b._bili_poster, _b.parse_wuwa_poster_first_end)

        def run(kuro_get, kuro_door, bili_door, read_image, first_end=None):
            _b._kuro_poster = lambda ver, now, get=None: kuro_door()
            _b._bili_poster = lambda ver, now, get=None: bili_door()
            if first_end is not None:
                _b.parse_wuwa_poster_first_end = lambda lines: first_end
            try:
                with _logs() as recs:
                    got = _b._wuwa_first_half_end("3.8", now, read_image, _b.Trace.new(), kuro_get, None)
            finally:
                _b._kuro_poster, _b._bili_poster, _b.parse_wuwa_poster_first_end = real
            warns = [r.getMessage() for r in recs if r.levelno == logging.WARNING]
            return got, warns

        got, warns = run(down, down, down, lambda url: [])
        check("silent 2655: notice and both doors failing is one WARNING", (got, len(warns)), (None, 1))
        check("silent 2655: it lists every failure",
              [all(x in w for x in ("唤取公告", "库街区", "哔哩哔哩")) for w in warns], [True])
        check("silent 2655: no Latin letters in the quoted first line",
              [bool(re.search(r"[A-Za-z]", w.split("\n")[0])) for w in warns], [False])
        got, warns = run(down, lambda: None, lambda: None, None)
        check("silent 2655: notice failing with no OCR is one WARNING too", (got, len(warns)), (None, 1))

        def bad_image(url):
            raise OSError("image timed out")
        got, warns = run(empty, lambda: post, lambda: None, bad_image)
        check("silent 2678: a poster image that failed is said", (got, len(warns)), (None, 1))
        check("silent 2678: naming the image", ["第 1 张图" in w for w in warns], [True])
        got, warns = run(empty, lambda: None, lambda: None, lambda url: [])
        check("silent 2655: not published yet says nothing (the docstring's promise)", (got, warns), (None, []))
        got, warns = run(empty, lambda: None, lambda: None, None)
        check("silent 2655: not published, no OCR, says nothing", (got, warns), (None, []))
        end = datetime(2026, 11, 11, 9, 59)
        got, warns = run(down, lambda: post, down, lambda url: [], first_end=end)
        check("silent 2666: the poster giving the end is no group message", (got, warns), (end, []))


    # ------------------------------------------------------------------ 2026-11-08 audit
    # The user, 2026-11-08 00:12 / 00:15: 明河「烟火邀星河」 had been open since 11-05
    # 12:00 while the report said 「当期无新角色卡池」; the group had been told on 11-04
    # that it opens 11-05 12:00; and he wants the hidden mines of the whole section
    # cleared, not only the one that rang (BOARD/中继卡池与关联模块清雷清单-1108.md).

    EF1107 = FX / "ef-1107"
    EF_NOW = datetime(2026, 11, 7, 23, 28)


    def _ef_pages(briefing=True, bundle=None):
        """The official site as read 2026-11-07 23:28: the banner-notice backend's first
    page (trimmed to the three notices _endfield reads) and the version briefing
    (the 10-08 recording, whose GachaCharPool rows are the same version's)."""
        pages = {_b._EF_CMS_LIST.format(page=1): (EF1107 / "cms_list_p1.json").read_text(encoding="utf-8")}
        for cid in ("7204", "8548", "2650"):
            pages[_b._EF_CMS_POST.format(cid=cid)] = (EF1107 / f"cms_{cid}.json").read_text(encoding="utf-8")
        if briefing:
            fx = FX / "ef-briefing-v1d6"
            page = (fx / "latest.html").read_text(encoding="utf-8")
            pages[_b._EF_BRIEFING] = page
            pages[_b._EF_BRIEFING_JS.search(page).group(1)] = bundle or (fx / "bundle.js").read_text(encoding="utf-8")
        return pages


    def _ef_1107(now=EF_NOW, *, pages=None, bulletin=True, failed=None, sk=None):
        """_endfield on 11-07's real answers: Skland's char-pool empty (as it was from
    11-05 to 11-08), the version bulletin, the banner notices and the briefing."""
        html = json.loads((EF1107 / "bulletin.json").read_text(encoding="utf-8"))["data"]["list"][0]["data"]["html"]
        real = (_b._json, _b._text, _b.endfield_next_from_news)
        pg = _ef_pages() if pages is None else pages

        def js(url, *a, **k):
            if url == _b._EF_BULLETIN and bulletin:
                return {"data": {"list": [{"title": "版本更新说明", "data": {"html": html}}]}}
            raise OSError(f"offline: {url}")

        def text(url, *a, **k):
            if url in pg:
                return pg[url]
            raise OSError(f"offline: {url}")
        _b._json, _b._text, _b.endfield_next_from_news = js, text, (lambda now: None)
        tr = _b.Trace.new()
        try:
            with _logs() as recs:
                got, nxt = _b._endfield(None, sk or (lambda path: {"data": {"list": []}}), now, trace=tr, failed=failed)
        finally:
            _b._json, _b._text, _b.endfield_next_from_news = real
        return got, nxt, tr, recs


    EF1109 = FX / "ef-1109"


    def _ef_1109(end_ts: "str | None" = None):
        """_endfield on 11-09 21:46 with Skland's char-pool as the game PC read it at 22:05
    (EF1109/char_pool.json: 明河「烟火邀星河」 entered that day, poolStartAtTs 11-09
    00:00, poolEndAtTs 11-25 06:00) and the official sources of _ef_1107 (the bulletin
    opens it 11-05 12:00 and prints no end, the briefing closes it 11-26 06:00).
    `end_ts` replaces Skland's poolEndAtTs."""
        pool = json.loads((EF1109 / "char_pool.json").read_text(encoding="utf-8"))
        if end_ts is not None:
            pool["list"][0]["poolEndAtTs"] = end_ts

        def sk(path):
            if path == "/web/v1/wiki/char-pool":
                return {"data": pool}
            return {"data": {"item": {"name": "明河"}}}
        return _ef_1107(datetime(2026, 11, 9, 21, 46), sk=sk)


    def _audit_1109_skland_backfill() -> None:
        """Alarm #157 (Gemini, 2026-11-09): #66 failed on 「终末地：森空岛 和 公告 对不上 ✗
    （开始 森空岛 11-09 00:00 / 公告 11-05 12:00）」. Both of Skland's times are its
    bookkeeping: the opening differs from the bulletin, the end (11-25 06:00) from the
    version briefing (11-26 06:00), which nothing compared. Her ruling: the first-hand
    time wins, start and end, as ✓ corrections; the report counts down to 11-26 06:00
    as it did on 11-08."""
        from ark_relay.features import machinecheck as mc
        from ark_relay.features import machinechecks as pb
        now = datetime(2026, 11, 9, 21, 46)
        got, nxt, tr, _recs = _ef_1109()
        check("1109 ef: Skland's opening and end take the official ones",
              [(b.name, b.chars, b.start, b.end) for b in got],
              [("烟火邀星河", ("明河",), datetime(2026, 11, 5, 12, 0), datetime(2026, 11, 26, 6, 0))])
        check("1109 ef: two ✓ corrections naming both values, nothing else",
              [c for c in tr.checks if c.startswith("终末地")],
              ["终末地：森空岛 和 公告 开始不同（森空岛 11-09 00:00 / 公告 11-05 12:00），已按公告补正 ✓"
           "（公告没写结束时刻，只核了开始）",
               "终末地：森空岛 和 新版本导览 结束不同（森空岛 11-25 06:00 / 新版本导览 11-26 06:00），已按新版本导览补正 ✓"])
        out = render(got, now, {"终末地": nxt} if nxt else {}, {}, tr)
        check("1109 ef: the report counts down to the briefing's end, as on 11-08",
              ("· 当期：烟火邀星河 · 明河 · 北京 11-26 06:00 结束 · 剩 16 天 8 小时" in out, "11-26 06:00" in tr.ends),
              (True, True))
        v = pb._no_open_mismatch({"trace": tr})
        check("1109 #66: passes, both corrections counted as filled",
              (v.status, "其中 2 条是官方来源补上的" in v.evidence), (mc.PASS, True))
        # Had Skland closed it at the briefing's 11-26 06:00, only the opening is corrected.
        got, _nxt, tr, _recs = _ef_1109(end_ts="1795644000")
        check("1109 ef: the same end -> the end line is a plain ✓",
              ([b.end for b in got], "终末地：森空岛和新版本导览的结束时刻对得上 ✓（11-26 06:00）" in tr.checks,
               ["✗" in c for c in tr.checks if c.startswith("终末地")]),
              ([datetime(2026, 11, 26, 6, 0)], True, [False, False]))
        from ark_relay.features import endfield as _ef
        sk = _b.Banner("终末地", "烟火邀星河", ("明河",), datetime(2026, 11, 5, 12, 0), datetime(2026, 11, 25, 6, 0))
        row = {"op": "明河", "pool": "烟火邀星河", "end": datetime(2026, 11, 26, 6, 0),
               "ends": {"新版本导览": datetime(2026, 11, 26, 6, 0), "特许寻访说明": datetime(2026, 11, 27, 6, 0)}}
        tr = _b.Trace.new()
        check("1109 ef: official ends that disagree among themselves -> not corrected here (_ef_fill's ✗)",
              (_ef._ef_end_check(sk, [row], now, tr), tr.checks), (sk, []))
        tr = _b.Trace.new()
        late = datetime(2026, 11, 26, 8, 0)
        old = {**row, "ends": {"新版本导览": row["end"]}}
        sk2 = _b.Banner("终末地", "烟火邀星河", ("明河",), datetime(2026, 11, 5, 12, 0), datetime(2026, 11, 27, 6, 0))
        check("1109 ef: the official close already past while Skland has it open -> ✗, not corrected",
              (_ef._ef_end_check(sk2, [old], late, tr), ["✗" in c and "官方已经结束" in c for c in tr.checks]),
              (sk2, [True]))


    def _crosscheck_fix_cases() -> None:
        """crosscheck_fix corrects the opening and the end to the first-hand times, and
    only to an opening already past and a close still to come."""
        now = datetime(2026, 11, 9, 21, 46)
        wiki = _b.Banner("终末地", "烟火邀星河", ("明河",), datetime(2026, 11, 9, 0, 0), datetime(2026, 11, 25, 6, 0))

        def off(**kw):
            base = dict(game="终末地", name="烟火邀星河", chars=("明河",),
                        start=datetime(2026, 11, 9, 0, 0), end=datetime(2026, 11, 25, 6, 0))
            return _b.Banner(**{**base, **kw})
        tr = _b.Trace.new()
        b, line = _b.crosscheck_fix("终末地", "森空岛", wiki, "公告", off(start=datetime(2026, 11, 5, 12, 0)), now, tr)
        check("fix: only the opening differs -> corrected ✓",
              (b.start, b.end, line, tr.ends),
              (datetime(2026, 11, 5, 12, 0), wiki.end,
               "终末地：森空岛 和 公告 开始不同（森空岛 11-09 00:00 / 公告 11-05 12:00），已按公告补正 ✓", set()))
        tr = _b.Trace.new()
        b, line = _b.crosscheck_fix("终末地", "森空岛", wiki, "公告", off(end=datetime(2026, 11, 26, 6, 0)), now, tr)
        check("fix: only the end differs -> corrected ✓, the new end a source stamp",
              (b.start, b.end, line, "11-26 06:00" in tr.ends),
              (wiki.start, datetime(2026, 11, 26, 6, 0),
               "终末地：森空岛 和 公告 结束不同（森空岛 11-25 06:00 / 公告 11-26 06:00），已按公告补正 ✓", True))
        b, line = _b.crosscheck_fix("终末地", "森空岛", wiki, "公告",
                                    off(start=datetime(2026, 11, 5, 12, 0), end=datetime(2026, 11, 26, 6, 0)), now)
        check("fix: both differ -> both corrected, one ✓ line",
              ((b.start, b.end), line),
              ((datetime(2026, 11, 5, 12, 0), datetime(2026, 11, 26, 6, 0)),
               "终末地：森空岛 和 公告 开始、结束都不同（开始 森空岛 11-09 00:00 / 公告 11-05 12:00；"
           "结束 森空岛 11-25 06:00 / 公告 11-26 06:00），已按公告补正 ✓"))
        b, line = _b.crosscheck_fix("终末地", "森空岛", wiki, "公告",
                                    off(start=None, start_note="版本更新后", end=datetime(2026, 11, 26, 6, 0)), now)
        check("fix: the official side prints no opening -> the end alone is corrected, the line says so",
              (b.start, b.end, line),
              (wiki.start, datetime(2026, 11, 26, 6, 0),
               "终末地：森空岛 和 公告 结束不同（森空岛 11-25 06:00 / 公告 11-26 06:00），已按公告补正 ✓"
           "（公告开始写「版本更新后」，只核了结束）"))
        # 2026-11-12, alarms #168/#169: Kuro BBS printed only the beginning of the name.
        from dataclasses import replace
        ww_now = datetime(2026, 11, 12, 11, 38)
        kuro = _b.Banner("鸣潮", "盛放于昨日梦土的", ("莉莉",), datetime(2026, 11, 12, 11, 0), datetime(2026, 12, 3, 9, 59, 59))
        game = _b.Banner("鸣潮", "盛放于昨日梦土的花朵", ("莉莉",), None, datetime(2026, 12, 3, 9, 59), start_note="版本更新后")
        b, line = _b.crosscheck_fix("鸣潮", "库街区", kuro, "游戏公告", game, ww_now)
        check("fix: the wiki cut the name short -> the official name, ✓",
              (b.name, b.chars, b.start, b.end, line),
              ("盛放于昨日梦土的花朵", ("莉莉",), kuro.start, kuro.end,
               "鸣潮：库街区 和 游戏公告 池名不同（库街区「盛放于昨日梦土的」/ 游戏公告「盛放于昨日梦土的花朵」），已按游戏公告补正 ✓"
           "（游戏公告开始写「版本更新后」，只核了结束）"))
        b, line = _b.crosscheck_fix("鸣潮", "库街区", kuro, "游戏公告", replace(game, end=datetime(2026, 12, 4, 9, 59)), ww_now)
        check("fix: cut short and another end -> both corrected in one ✓ line",
              (b.name, b.end, line.endswith("，已按游戏公告补正 ✓（游戏公告开始写「版本更新后」，只核了结束）"), "池名、结束都不同" in line),
              ("盛放于昨日梦土的花朵", datetime(2026, 12, 4, 9, 59), True, True))
        for label, w, o in (("the official name is the shorter one", "盛放于昨日梦土的花朵", "盛放于昨日梦土的"),
                            ("only three characters in common", "盛放于", "盛放于昨日梦土的花朵"),
                            ("the names merely begin alike", "盛放于昨日的雪", "盛放于昨日梦土的花朵")):
            x, y = replace(kuro, name=w), replace(game, name=o)
            b, line = _b.crosscheck_fix("鸣潮", "库街区", x, "游戏公告", y, ww_now)
            check(f"fix: {label} -> still a ✗, nothing corrected",
                  (b is x, line), (True, _b.crosscheck("鸣潮", "库街区", x, "游戏公告", y)))
        b, line = _b.crosscheck_fix("鸣潮", "库街区", kuro, "游戏公告", replace(game, chars=("别人",)), ww_now)
        check("fix: cut short but another character -> still a ✗", (b is kuro, "✗" in line), (True, True))
        check("name_cut_short: a kind prefix in 【】 is not part of the name",
              (_b.name_cut_short("【限定寻访】盛放于昨日", "盛放于昨日梦土"), _b.name_cut_short("盛放于昨日", "盛放于昨日")), (True, False))
        for label, other in (("the official opening still to come", off(start=datetime(2026, 11, 10, 12, 0))),
                             ("the official close already past", off(end=datetime(2026, 11, 9, 12, 0))),
                             ("the name differs too", off(name="另一个池", start=datetime(2026, 11, 5, 12, 0))),
                             ("a character the wiki lacks", off(chars=("祀",), end=datetime(2026, 11, 26, 6, 0))),
                             ("no such banner", None),
                             ("nothing differs", off())):
            b, line = _b.crosscheck_fix("终末地", "森空岛", wiki, "公告", other, now)
            check(f"fix: {label} -> crosscheck's line, nothing corrected",
                  (b is wiki, line), (True, _b.crosscheck("终末地", "森空岛", wiki, "公告", other)))


    def _recovered(recs: list, part: str) -> "list[bool]":
        """For each WARNING carrying `part`: is it marked recovered (daily report only)?"""
        from ark_relay.features import errwatch
        return [bool(getattr(r, errwatch.RECOVERED, False)) for r in recs
                if r.levelno == logging.WARNING and part in r.getMessage()]


    def _audit_1108_endfield() -> None:
        from ark_relay.features import endfield as _ef
        got, nxt, tr, recs = _ef_1107()
        out = render(got, EF_NOW, {"终末地": nxt} if nxt else {}, {}, tr)
        check("1108 ef: 明河 is running from the official sources while Skland is empty",
              [(b.name, b.chars, b.start, b.end) for b in got],
              [("烟火邀星河", ("明河",), datetime(2026, 11, 5, 12, 0), datetime(2026, 11, 26, 6, 0))])
        check("1108 ef: the report line", "· 当期：烟火邀星河 · 明河 · 北京 11-26 06:00 结束 · 剩 18 天 6 小时" in out, True)
        check("1108 ef: never 「当期无新角色卡池」", "当期无新角色卡池" in _block(out, "终末地"), False)
        check("1108 ef: the fill is a ✓ cross-check naming all three official sources",
              [c for c in tr.checks if "补进当期 ✓" in c],
              ["终末地：森空岛里没有在开的「烟火邀星河」，版本更新说明、特许寻访说明、新版本导览写着 11-05 12:00 开、"
           "11-26 06:00 结束，已按官方补进当期 ✓"])
        check("1108 ef: one WARNING, marked recovered", _recovered(recs, "烟火邀星河"), [True])
        check("1108 ef: no Latin letters in its first line",
              [bool(re.search(r"[A-Za-z]", r.getMessage().split("\n")[0])) for r in recs
               if r.levelno == logging.WARNING and "烟火邀星河" in r.getMessage()], [False])
        check("1108 ef: the open banner is recorded for check #67",
              tr.opens, [["终末地", "烟火邀星河", "明河", "2026-11-05 12:00", "2026-11-26 06:00",
                          "版本更新说明、特许寻访说明、新版本导览"]])
        check("1108 ef: 明河 running means no next banner yet", nxt, None)
        check("1108 ef: the end is a source date", "11-26 06:00" in tr.ends, True)

        # 11-01: 祀 running (Skland empty, filled from the notices), 明河 announced for
        # 11-05 12:00: its end is recorded like the other games' (the 下期 line and the
        # trace file's "until", which the cross-day gate puts it back with).
        nov1 = datetime(2026, 11, 1, 12, 0)
        got, nxt, tr, recs = _ef_1107(nov1)
        out = render(got, nov1, {"终末地": nxt}, {}, tr)
        check("1108 ef: the next banner's end is recorded",
              (nxt, tr.until.get("终末地"), "11-26 06:00" in tr.ends),
              ((datetime(2026, 11, 5, 12, 0), "明河「烟火邀星河」"), datetime(2026, 11, 26, 6, 0), True))
        check("1108 ef: and printed on the 下期 line, which passes the source gate",
              ("· 下期：烟火邀星河 · 明河 · 北京 11-05 12:00 开 · 11-26 06:00 结束" in out, tr.withheld), (True, []))
        check("1108 ef: 祀 running from the notices, ending at the changeover",
              "· 当期：万物更新 · 祀 · 北京 11-05 11:59 换池" in out, True)
        check("1108 ef: no end known for a next banner -> none recorded",
              (_ef._ef_until(None, [], _b.Trace.new()), _ef._ef_until((None, "x「y」"), [], _b.Trace.new())),
              (None, None))

        # 11-27: everything in the bulletin, the notices and the briefing has closed.
        got, nxt, tr, recs = _ef_1107(datetime(2026, 11, 27, 12, 0))
        out = render(got, datetime(2026, 11, 27, 12, 0), {}, {}, tr)
        check("silent 244: Skland empty and no official banner open -> no banner, said plainly",
              (got, "· 当期无新角色卡池" in out, tr.opens), ([], True, []))

        # The briefing unreadable: the notices say 「版本更新维护前」 and nothing gives the end.
        failed: list = []
        got, nxt, tr, recs = _ef_1107(pages=_ef_pages(briefing=False), failed=failed)
        out = render(got, EF_NOW, {}, {}, tr, failed)
        check("1108 ef: with no end published the banner is still running",
              [(b.name, b.end) for b in got], [("烟火邀星河", None)])
        check("1108 ef: its line says the end is not published",
              "· 当期：烟火邀星河 · 明河 · 版本更新维护前结束（几点官方还没公布）" in out, True)
        check("1108 ef: and that is a ✗ (#66 pushes it once), no WARNING of its own",
              (any("✗" in c and "烟火邀星河" in c for c in tr.checks), _recovered(recs, "烟火邀星河"),
               [r.levelno for r in recs if "结束时刻哪个官方来源都没给" in r.getMessage()]), (True, [], [logging.INFO]))
        check("1108 ef: the briefing is said once, where the next banner needed it", _warned(recs, "新版本导览取不到"), 1)
        check("1108 ef: not read is not the game failing", failed, [])

        # Two official sources disagree on the opening time.
        bundle = (FX / "ef-briefing-v1d6" / "bundle.js").read_text(encoding="utf-8").replace(
            '"cn":{"openTime":"2026/11/5 12:00:00","closeTime":"2026/11/26 6:00:00","endTimeDisplay"',
            '"cn":{"openTime":"2026/11/5 13:00:00","closeTime":"2026/11/26 6:00:00","endTimeDisplay"')
        got, nxt, tr, recs = _ef_1107(pages=_ef_pages(bundle=bundle))
        check("1108 ef: official sources disagreeing is a ✗ naming each",
              [c for c in tr.checks if "对不上" in c],
              ["终末地：「烟火邀星河」各官方来源的开始时刻对不上 ✗（版本更新说明 11-05 12:00；特许寻访说明 11-05 12:00；新版本导览 11-05 13:00）"])

        # Skland empty and every official source unreadable: not read, never "none".
        failed = []
        got, nxt, tr, recs = _ef_1107(pages={}, bulletin=False, failed=failed)
        check("1108 ef: Skland empty and nothing official read is listed as not read",
              failed, ["终末地（森空岛的当期卡池表是空的，官方公告也没读到）"])
        check("1108 ef: ...said once", _warned(recs, "三个官方来源也都没读到"), 1)

        # Skland lists 明河: nothing is filled, the cross-check is Skland's against the bulletin.
        pool = {"name": "烟火邀星河", "poolStartAtTs": "1794024000", "poolEndAtTs": "1795644000",
                "chars": [{"dotType": "label_type_up", "pcLink": "x?gameEntryId=2001"}]}

        def sk(path):
            if path == "/web/v1/wiki/char-pool":
                return {"data": {"list": [pool]}}
            return {"data": {"item": {"name": "明河"}}}
        got, nxt, tr, recs = _ef_1107(sk=sk)
        check("1108 ef: Skland listing it -> no fill, no fill warning",
              ([b.chars for b in got], [c for c in tr.checks if "补进当期 ✓" in c], _warned(recs, "补进当期")), ([("明河",)], [], 0))

        # A notice whose title names no banner never makes a nameless 当期 line.
        got, tr = [], _b.Trace.new()
        _ef._ef_fill(got, [], [{"op": "明河", "pool": "", "debut": True, "starts": {}, "ends": {}, "by": ["特许寻访说明"],
                                "start": datetime(2026, 11, 5, 12), "end": None}], EF_NOW, tr)
        check("1108 ef: an open notice with no banner name is not filled", (got, tr.opens), ([], []))

        # The next banner from the notices already read (no second fetch of the backend).
        before = _b.ef_banner_posts([(c, t, ts, x) for c, t, ts, x in _b.ef_cms_posts(lambda u: _ef_pages()[u], 1)])
        check("1108 ef: the notices read once give the next banner the same way",
              (_b.ef_next_from_rows(before, datetime(2026, 11, 1)), _b.ef_next_from_rows([], EF_NOW)),
              ((datetime(2026, 11, 5, 12, 0), "明河「烟火邀星河」"), None))
        check("1108 ef: a notice with no start and a past end is not next",
              _b.ef_next_from_rows([{"who": "x「y」", "start": None, "end": datetime(2026, 1, 1)}], EF_NOW), None)
        check("1108 ef: a notice with no start yet is next with no time",
              _b.ef_next_from_rows([{"who": "x「y」", "start": None, "end": None}], EF_NOW), (None, "x「y」"))


    def _audit_1108_read_retry() -> None:
        import http.client
        import urllib.error
        import urllib.request

        class R:
            status = 200

            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.body
        calls: list = []
        pauses: list = []

        def run(*answers):
            seq = list(answers)

            def fake(req, timeout=None):
                calls.append(req.full_url)
                a = seq.pop(0)
                if isinstance(a, BaseException):
                    raise a
                return R(a)
            real, real_pause = urllib.request.urlopen, _b._pause
            urllib.request.urlopen, _b._pause = fake, pauses.append
            calls.clear()
            pauses.clear()
            try:
                with _logs() as recs:
                    try:
                        out = _b._text("https://example.invalid/x", "ua")
                    except Exception as e:  # noqa: BLE001
                        out = e
            finally:
                urllib.request.urlopen, _b._pause = real, real_pause
            return out, len(calls), list(pauses), recs
        out, n, pz, recs = run(http.client.IncompleteRead(b"half"), b"whole")
        check("1108 read: a body cut short is read again", (out, n, pz), ("whole", 2, [_b._RETRY_PAUSE]))
        check("1108 read: the retry is INFO, not a group message",
              [r.levelno for r in recs if "再读一次" in r.getMessage()], [logging.INFO])
        out, n, _pz, _r = run(TimeoutError("timed out"), urllib.error.URLError("reset"))
        check("1108 read: two cut-short reads raise the second", (type(out).__name__, n), ("URLError", 2))
        out, n, _pz, _r = run(urllib.error.HTTPError("https://example.invalid/x", 404, "nf", {}, None))
        check("1108 read: an HTTP status is the site's answer, not retried", (type(out).__name__, n), ("HTTPError", 1))
        # relay-opt-round3-1108 O-03: a gateway's 502 / 503 / 504 is the network, not the site.
        out, n, _pz, _r = run(urllib.error.HTTPError("https://example.invalid/x", 503, "busy", {}, None), b"whole")
        check("1108 read: a gateway 503 is read again", (out, n), ("whole", 2))
        out, n, _pz, _r = run(ValueError("odd"))
        check("1108 read: anything else is not retried", (type(out).__name__, n), ("ValueError", 1))


    def _audit_1108_arknights() -> None:
        # PRTS has not listed 海渊巡游 on its first day; the official post has it open.
        now = datetime(2026, 10, 10, 12, 0)
        out, tr, recs = _ak_offline(now, [], _ak_site_1006())
        got = out[0] if isinstance(out, tuple) else out
        text = render(got, now, {}, {}, tr)
        check("1108 ak: the official post fills the running banner PRTS lacks",
              "· 当期：海渊巡游 · 克莱门莎 · 北京 10-23 03:59 结束" in text, True)
        check("1108 ak: as a ✓ fill, one recovered WARNING",
              ([c for c in tr.checks if "补进当期 ✓" in c and "资料站" in c] != [], _recovered(recs, "海渊巡游")), (True, [True]))
        check("1108 ak: recorded for check #67", [o[:3] for o in tr.opens], [["明日方舟", "海渊巡游", "克莱门莎"]])
        # PRTS has it (prefixed, 07:00): no fill.
        row = _b.Banner("明日方舟", "【限定寻访·夏季】海渊巡游", ("克莱门莎",),
                        datetime(2026, 10, 9, 7, 0), datetime(2026, 10, 23, 3, 59))
        out, tr, recs = _ak_offline(now, [row], _ak_site_1006(), {"克莱门莎": 5})
        check("1108 ak: PRTS listing it -> no fill", ([c for c in tr.checks if "补进当期 ✓" in c], _warned(recs, "补进当期")), ([], 0))
        # Before it opens and after it closes: nothing.
        for when in (datetime(2026, 10, 9, 11, 0), datetime(2026, 10, 23, 4, 0)):
            out, tr, recs = _ak_offline(when, [], _ak_site_1006())
            check(f"1108 ak: not open at {when:%m-%d %H:%M} -> nothing filled", tr.opens, [])


    def _audit_1108_wuwa() -> None:
        notice = json.loads((FX / "ww-notice-2026-10-05.json").read_text(encoding="utf-8"))
        now = datetime(2026, 10, 10, 12, 0)

        def run(home, entry):
            def js(url, *a, **k):
                if url == _b._WW_NOTICE:
                    return notice
                if url.endswith("/wiki/core/homepage/getPage"):
                    return home
                if url.endswith("/getEntryDetail"):
                    return entry()
                raise OSError("offline")

            def text(url, *a, **k):
                if url == _b._WW_SITE_ARTICLES:
                    return "[]"
                raise OSError("offline")
            real = _b._json, _b._text
            _b._json, _b._text = js, text
            tr = _b.Trace.new()
            try:
                with _logs() as recs:
                    got, nxt = _b._wuwa(now, {}, tr, None, lambda p, q: {"data": {"list": []}}, lambda u, c: {})
            finally:
                _b._json, _b._text = real
            return got, nxt, tr, recs, render(got, now, {"鸣潮": nxt} if nxt else {}, {}, tr)

        def tab(name, eid):
            return {"name": name, "countDown": {"dateRange": ["2026-09-30 11:00", "2026-10-22 09:59"]},
                    "imgs": [{"linkConfig": {"entryId": eid}}]}

        def home(*tabs):
            return {"code": 200, "data": {"contentJson": {"sideModules": [
                {"title": "角色活动唤取", "content": {"tabs": list(tabs)}}]}}}

        def cut():
            raise http_incomplete
        import http.client
        http_incomplete = http.client.IncompleteRead(b"")

        # The wiki lists no running banner; the in-game post has 但愿长圆如此夜 open.
        got, nxt, tr, recs, out = run(home(), cut)
        check("1108 ww: the in-game post fills the running banner the wiki lacks",
              "· 当期：但愿长圆如此夜 · 心 · 北京 10-22 09:59 结束" in out, True)
        check("1108 ww: as a ✓ fill, one recovered WARNING",
              ([c for c in tr.checks if "补进当期 ✓" in c and "库街区" in c] != [], _recovered(recs, "但愿长圆如此夜")), (True, [True]))
        check("1108 ww: the second half is still next, not the running one",
              nxt[1] if nxt else None, "锁暝「余心所向九死未悔」")
        # The wiki lists it but its character's name lookup is cut short.
        got, nxt, tr, recs, out = run(home(tab("但愿长圆如此夜", 101)), cut)
        check("1108 ww: a nameless wiki banner is named from the bulletin",
              [(b.name, b.chars) for b in got if b.name == "但愿长圆如此夜"], [("但愿长圆如此夜", ("心",))])
        check("1108 ww: said once, marked recovered", _recovered(recs, "查不到名字"), [True])
        check("1108 ww: named, it is the wiki's and cross-checked, not filled again",
              ([c for c in tr.checks if "补进当期 ✓" in c], any("库街区=游戏公告" in c for c in tr.checks)), ([], True))
        # A nameless tab no notice names stays out, with the plain WARNING.
        got, nxt, tr, recs, out = run(home(tab("但愿长圆如此夜", 101), tab("别的卡池", 102)), cut)
        check("1108 ww: a name found nowhere is the plain WARNING", _recovered(recs, "102 查不到名字"), [False])


    def _audit_1108_gate() -> None:
        import tempfile
        sd = Path(tempfile.mkdtemp())
        (sd / "banners").mkdir()

        def snap(day, nxt, until=None, raw=None):
            f = sd / "banners" / f"{day}.json"
            f.write_text(raw if raw is not None else json.dumps({"next": nxt, "until": until or {}}, ensure_ascii=False),
                         encoding="utf-8")
        # 11-04's report: 「明天开」 明河 at 11-05 12:00 (what the group was told).
        snap("2026-11-04", {"终末地": ["2026-11-05 12:00", "明河「烟火邀星河」"], "鸣潮": [None, "锁暝"]})
        snap("2026-11-05", {}, raw="{broken")

        def gate(rows, failed=None, now=EF_NOW):
            tr = _b.Trace.new()
            failed = [] if failed is None else failed
            with _logs() as recs:
                _b.check_continuity(sd, now, rows, failed, tr)
            return rows, failed, tr, recs
        rows, failed, tr, recs = gate([])
        out = render(rows, EF_NOW, {}, {}, tr, failed)
        check("1108 gate: announced, opened, lost everywhere, no end -> not read",
              (failed, _block(out, "终末地")),
              (["终末地（11-05 12:00 已预告开的明河「烟火邀星河」）"],
               "终末地\n· 这次没读到（11-05 12:00 已预告开的明河「烟火邀星河」），不是没有卡池"))
        check("1108 gate: the verdict for #68 (which pushes it once), no WARNING of its own",
              (_recovered(recs, "之前预告"), [r.levelno for r in recs if "之前预告" in r.getMessage()],
               [r[1] for r in tr.continuity]), ([], [logging.INFO], ["lost"]))
        ming = _b.Banner("终末地", "烟火邀星河", ("明河",), datetime(2026, 11, 5, 12), datetime(2026, 11, 26, 6))
        rows, failed, tr, recs = gate([ming])
        check("1108 gate: in today's 当期 -> ok", ([r[1] for r in tr.continuity], failed), (["ok"], []))
        rows, failed, tr, recs = gate([], ["终末地（没有森空岛令牌）"])
        check("1108 gate: a game already not read is left alone", tr.continuity, [])
        # The end published with the announcement: put back.
        snap("2026-11-04", {"终末地": ["2026-11-05 12:00", "明河「烟火邀星河」"]}, {"终末地": "2026-11-26 06:00"})
        rows, failed, tr, recs = gate([])
        check("1108 gate: with its end -> put back, recovered",
              ([(b.name, b.end) for b in rows], failed, _recovered(recs, "之前预告"), [r[1] for r in tr.continuity]),
              ([("烟火邀星河", datetime(2026, 11, 26, 6))], [], [True], ["recovered"]))
        # The end from the history ledger instead.
        snap("2026-11-04", {"终末地": ["2026-11-05 12:00", "明河「烟火邀星河」"]})
        (sd / "banners" / "history.json").write_text(json.dumps({"终末地": {
            "丹青渡|明河「烟火邀星河」": [["2026-11-05 12:00", "2026-11-26 06:00"]],
            "丹青渡|祀「万物更新」": [["2026-10-15 12:00", "2026-11-05 11:59"]]}}, ensure_ascii=False), encoding="utf-8")
        rows, failed, tr, recs = gate([])
        check("1108 gate: end from banners/history.json", [(b.name, b.end) for b in rows],
              [("烟火邀星河", datetime(2026, 11, 26, 6))])
        (sd / "banners" / "history.json").write_text("{broken", encoding="utf-8")
        # Not yet due / over / too old / a bare announcement.
        snap("2026-11-04", {"终末地": ["2026-11-08 12:00", "明河「烟火邀星河」"],
                            "明日方舟": ["2026-11-07 00:00", "「新年限定」"],
                            "鸣潮": ["2026-10-20 10:00", "3.8版本第一期"]}, {"明日方舟": "2026-11-21 03:59"})
        rows, failed, tr, recs = gate([])
        check("1108 gate: not opened yet, a date-only start today, a week-old one -> nothing",
              (tr.continuity, failed), ([], []))
        snap("2026-11-04", {"鸣潮": ["2026-11-06 10:00", "3.8版本第一期"], "终末地": ["2026-11-01 12:00", "x「y」"]},
             {"终末地": "2026-11-03 12:00"})
        xin = _b.Banner("鸣潮", "某池", ("某人",), datetime(2026, 11, 6, 10), datetime(2026, 11, 27, 9, 59))
        rows, failed, tr, recs = gate([xin])
        check("1108 gate: an announcement naming no banner is met by any running one; an ended one is skipped",
              [r[:2] for r in tr.continuity], [["鸣潮", "ok"]])
        snap("2026-11-04", {"鸣潮": ["bad", "x"]})
        check("1108 gate: an unreadable time is skipped", gate([])[2].continuity, [])

        # Through collect and save_trace: the verdicts and the next banner's end are kept.
        real = (_b._ak_prts_rows, _b._json, _b._text, _b._wuwa, _b.endfield_next_from_news)
        _b._ak_prts_rows, _b._wuwa = (lambda tr: []), (lambda *a, **k: ([], None))
        _b._json = _b._text = lambda url, *a, **k: (_ for _ in ()).throw(OSError("offline"))
        snap("2026-11-04", {"终末地": ["2026-11-05 12:00", "明河「烟火邀星河」"], "明日方舟": ["2026-11-06 16:00", "某人「某池」"]})
        failed, tr = [], _b.Trace.new()
        try:
            with _logs():
                rows, nxt = _b.collect(EF_NOW, sk_get=lambda path: {"data": {"list": []}}, failed=failed, trace=tr,
                                       state_dir=sd)
        finally:
            _b._ak_prts_rows, _b._json, _b._text, _b._wuwa, _b.endfield_next_from_news = real
        check("1108 gate: collect runs it when given the state dir (终末地 is already not read there)",
              [r[:2] for r in tr.continuity], [["明日方舟", "lost"]])
        tr.until["明日方舟"] = datetime(2026, 11, 21, 3, 59)
        sd2 = Path(tempfile.mkdtemp())
        with _logs():
            _b.save_trace(sd2, EF_NOW, "🎴", tr)
        saved = json.loads((sd2 / "banners" / f"{EF_NOW:%Y-%m-%d}.json").read_text(encoding="utf-8"))
        check("1108 gate: the trace file keeps until, opens and the verdicts",
              (saved["until"], [r[1] for r in saved["continuity"]]), ({"明日方舟": "2026-11-21 03:59"}, ["lost"]))


    def _audit_1108_first_end_doors() -> None:
        """_wuwa_first_half_end's poster doors are traced like _wuwa_poster_span's, so
    machine check #3 sees both halves of a version (until 11-08 the first-half
    poster wrote no door at all)."""
        now = datetime(2026, 11, 8, 12, 0)
        post = ("https://www.kurobbs.com/mc/post/1", "3.8版本资讯", [("https://img/1.png", 733, 10000)])
        real = (_b._kuro_poster, _b._bili_poster, _b.parse_wuwa_poster_first_end)

        def run(kuro_door, bili_door, read_image, first_end=None):
            _b._kuro_poster = lambda ver, now, get=None: kuro_door()
            _b._bili_poster = lambda ver, now, get=None: bili_door()
            _b.parse_wuwa_poster_first_end = lambda lines: first_end
            tr = _b.Trace.new()
            try:
                with _logs():
                    got = _b._wuwa_first_half_end("3.8", now, read_image, tr, lambda p, q: {"data": {"list": []}}, None)
            finally:
                _b._kuro_poster, _b._bili_poster, _b.parse_wuwa_poster_first_end = real
            return got, {w: v for w, v in (x.split("｜")[2:] for x in tr.sources if "｜版本资讯门｜" in x)}

        def down():
            raise OSError("timed out")
        got, d = run(lambda: None, lambda: None, lambda u: [])
        check("1108 doors: no post on either side", d, {"库街区": "没有这一帖", "B 站": "没有这一帖"})
        end = datetime(2026, 12, 3, 9, 59)
        got, d = run(down, lambda: post, lambda u: [], end)
        check("1108 doors: one failed, the other gave the end",
              (got, d["库街区"].startswith("取不到"), d["B 站"]), (end, True, "给出了 3.8 第一期的结束时刻 12-03 09:59"))
        got, d = run(lambda: post, lambda: None, lambda u: None)
        check("1108 doors: the poster read with no result", (got, d["库街区"].startswith("长图没读出来")), (None, True))
        got, d = run(lambda: post, lambda: None, lambda u: [])
        check("1108 doors: the poster read, no end on it", d["库街区"], "长图里没读到 3.8 第一期的结束时刻")


    def _audit_1108_render() -> None:
        now = datetime(2026, 10, 10, 12, 0)
        b = _b.Banner("鸣潮", "某池", ("某人",), None, datetime(2026, 10, 22, 9, 59, 59), "3.7版本更新后")
        check("1108 render: a running banner whose start is 「版本更新后」 is running",
              (_b.running(b, now), "· 当期：某池 · 某人 · 北京 10-22 09:59 结束" in render([b], now, {}, {})), (True, True))
        check("1108 render: who split", (_b.split_who("明河「烟火邀星河」"), _b.split_who("3.8版本第一期"), _b.split_who("")),
              (("明河", "烟火邀星河"), ("3.8版本第一期", ""), ("", "")))


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
        _comm_lead()
        _ww_calendar()
        _ww_news_poster()
        _ww_bili_feed()
        _ww_gacha_notice()
        _ef_history()
        _ef_briefing()
        _ak_history()
        _sf_pool_times()
        _sf_rarity()
        _ak_prts_clock()
        _sf_ef_names()
        _ef_no_token()
        _ef_no_version_notes()
        _crosscheck_honest()
        _no_test_only_api()
        _sf_ef_pool_ends()
        _sf_ef_brief_time()
        _sf_ww_first_half_end()
        _audit_1108_endfield()
        _audit_1108_read_retry()
        _audit_1108_arknights()
        _audit_1108_wuwa()
        _audit_1108_gate()
        _audit_1108_first_end_doors()
        _audit_1108_render()
        _audit_1109_skland_backfill()
        _crosscheck_fix_cases()
        print("all checks passed" if not FAILED else "FAILED: " + "; ".join(FAILED))
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_banner_post_miss():
    """The Wuthering Waves version-news post: a door's miss is INFO, no door is one WARNING.

10-05 21:47:23 (#58) 「库街区官方资讯里没找到 3.7 版本资讯帖」 was a WARNING on its
own, before the Bilibili copy was even asked. Every WARNING is pushed to the
group now (2026-10-06; the user: 「你正常情况应该一条都不发的」), so the rule is:
库街区 missing the post while Bilibili has it is INFO; neither giving the
second half's time is one WARNING naming what each door said. A 库街区 answer
without a list is a source problem (KuroListProblem, kept in the trace), not
"no post". Fixtures are the real 3.7 post (库街区 list 10-01, Bilibili feed,
the poster's OCR) as test_banners.py uses them; no network.

Since the user's rule of 2026-10-06 05:07 (「报错后自己好了的，只进日报、不进群」),
a source that FAILED (an exception, not "no such post") while another gave
the time is one WARNING marked errwatch.recovered(): not pushed, in the daily
report. Here for the 库街区 door (KuroListProblem) with Bilibili giving the
span, the PRTS API with its page giving the table, and the 库街区 gacha notice
with the poster giving the second half's start; when nothing else gives it,
the failure is a plain WARNING, pushed. A real errwatch handler shows both.

    Formerly test_banner_post_miss.py.
    """
    import json
    import logging
    import tempfile
    import time
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import banners as _b
    from ark_relay.features import errwatch
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.desktop import Line

    FX = fx_dir(Path(__file__), "fixtures")


    class Logs(logging.Handler):
        def __init__(self):
            super().__init__()
            self.recs: list[tuple[int, str]] = []

        def emit(self, record):
            self.recs.append((record.levelno, record.getMessage()))
            self.marks = getattr(self, "marks", [])
            if record.levelno >= logging.WARNING:
                self.marks.append((record.getMessage(), bool(getattr(record, errwatch.RECOVERED, False))))

        def warnings(self):
            return [m for lv, m in self.recs if lv >= logging.WARNING]

        def loud(self):
            """WARNINGs errwatch pushes (not marked recovered)."""
            return [m for m, rec in getattr(self, "marks", []) if not rec]

        def recovered(self):
            return [m for m, rec in getattr(self, "marks", []) if rec]

        def clear(self):
            self.recs.clear()
            self.marks = []


    class Pushes:
        def __init__(self):
            self.sent = []

        def send(self, title, body, **k):
            self.sent.append((title, body))
            return []


    STATE = Path(tempfile.mkdtemp(prefix="banner-post-miss-"))
    PUSHES = Pushes()
    WATCH = errwatch.ErrorKindAlert(PUSHES, state_dir=STATE, known={}, pace=0, retry=(0.05,))


    def pushed(want=0, secs=3.0):
        end = time.time() + secs
        while time.time() < end and (WATCH.pending() or len(PUSHES.sent) < want):
            time.sleep(0.02)
        time.sleep(0.1)
        return [b for _, b in PUSHES.sent]


    def daily():
        return errwatch.daily_section(STATE, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))


    logs = Logs()
    _b.log.addHandler(logs)
    _b.log.addHandler(WATCH)
    _b.log.setLevel(logging.DEBUG)
    _b.log.propagate = False
    _b._pause = lambda s: None

    now = datetime(2026, 10, 1, 2, 30)
    events = json.loads((FX / "ww-news-events.json").read_text(encoding="utf-8"))["data"]["list"]
    lines = [Line(**o) for o in json.loads((FX / "ww-3.7-news-3-ocr.json").read_text(encoding="utf-8"))]
    feed = json.loads((FX / "ww-bili-feed.json").read_text(encoding="utf-8"))
    bili3 = "https://i0.hdslb.com/bfs/new_dyn/e1826ff7fe229d2f29d8a715a4ee4eee1955897084.jpg"
    span = (datetime(2026, 10, 22, 10, 0), datetime(2026, 11, 11, 11, 59))
    without_post = [e for e in events if "版本资讯" not in str(e.get("postTitle") or "")]


    def bili(feed_answer):
        def get(url, cookie):
            if "finger/spi" in url:
                return {"data": {"b_3": "B3", "b_4": "B4=="}}
            if "/nav" in url:
                return {"data": {"wbi_img": {"img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                                             "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png"}}}
            return feed_answer
        return get


    def read(url):
        return lines if url == bili3 else []


    print("[库街区列表里没有这一帖、B 站有：拿到时间，不报 WARNING]")
    logs.recs.clear()
    tr = _b.Trace.new()
    got = _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now, read, tr,
                               lambda p, d: {"code": 200, "data": {"list": without_post}}, bili(feed))
    check("B 站那一份给出第二期的时间", got, span)
    check("库街区没找到只是 INFO（10-05 21:47 那条 WARNING）", logs.warnings(), [])
    check("……INFO 里还说了是哪边没找到",
          any(lv == logging.INFO and "库街区官方资讯里没找到 3.7 版本资讯帖" in m for lv, m in logs.recs), True)

    print("\n[库街区回的不是列表：记成来源问题，B 站给了时间 -> 只进日报，不报群]")
    logs.clear()
    tr = _b.Trace.new()
    got = _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now, read, tr,
                               lambda p, d: {"code": 220, "msg": "系统繁忙", "data": None}, bili(feed))
    check("还是拿到时间", got, span)
    check("nothing for the group", logs.loud(), [])
    rec = logs.recovered()
    check("one WARNING marked recovered: a door failed, the other gave the time",
          [("哔哩哔哩那一帖给出了" in m, "KuroListProblem" in m) for m in rec], [(True, True)])
    check("its first line is plain (the daily report quotes it)",
          [texts.plain(m.splitlines()[0]) for m in rec], [[]])
    check("not pushed", pushed(), [])
    check("in the daily report, tagged 「自己好了，只进日报」",
          ("给出了「余心所向九死未悔」的唤取时间" in daily(), "自己好了，只进日报" in daily()), (True, True))
    check("来源问题记进 trace，不当成「没有这一帖」",
          [p.split("｜")[3].split(":")[0] for p in tr.problems], ["KuroListProblem"])

    print("\n[两边都没有：一条 WARNING，说清两边各是什么情况]")
    logs.recs.clear()
    ended = {"code": 0, "data": dict(feed["data"], items=[i for i in feed["data"]["items"]
                                                           if not _b.wuwa_bili_post([i], "3.7", now)],
                                     has_more=False, offset="")}
    got = _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now, read, _b.Trace.new(),
                               lambda p, d: {"code": 200, "data": {"list": without_post}}, bili(ended))
    check("没有时间（不编）", got, None)
    warns = logs.warnings()
    check("只有一条 WARNING", len(warns), 1)
    check("……点名两边", ("库街区没有这一帖" in (warns or [""])[0], "B 站没有这一帖" in (warns or [""])[0]),
          (True, True))

    print("\n[PRTS 接口不通、页面读到了：只进日报；页面也不通：报群]")
    page = (FX / "prts_limited_page.html").read_text(encoding="utf-8")
    real_json, real_text = _b._json, _b._text
    saved_rarity = dict(_b._rarity_cache)


    def no_api(url, *a, **k):
        raise OSError("503 Backend fetch failed")


    def run_ak(page_text):
        def text(url, *a, **k):
            if url.startswith(_b._PRTS_PAGE) and page_text is not None:
                return page_text
            raise OSError("offline")
        _b._json, _b._text = no_api, text
        _b._rarity_cache.clear()
        try:
            return _b._arknights(datetime(2026, 9, 10, 12, 0), trace=_b.Trace.new())
        except RuntimeError:
            return None
        finally:
            _b._json, _b._text = real_json, real_text
            _b._rarity_cache.clear()
            _b._rarity_cache.update(saved_rarity)


    logs.clear()
    got = run_ak(page)
    check("the page gave the table", bool(got and got[0]), True)
    prts = [m for m in logs.recovered() if "资料站的数据入口" in m]
    check("one recovered WARNING per page the API missed and the page gave",
          len(prts) == len(_b._AK_PAGES) and all("改读它的页面读到了" in m for m in prts), True)
    check("no PRTS line for the group", [m for m in logs.loud() if "PRTS" in m or "资料站" in m], [])
    check("first lines plain (the daily report quotes them)", [texts.plain(m.splitlines()[0]) for m in prts],
          [[]] * len(prts))
    logs.clear()
    got = run_ak(None)
    check("API and page both down: no table", got, None)
    check("a plain WARNING per page, naming both (pushed)",
          [("接口和页面都取不到" in m) for m in logs.loud() if "PRTS" in m], [True] * len(_b._AK_PAGES))
    check("nothing marked recovered", [m for m in logs.recovered() if "资料站" in m], [])

    print("\n[库街区唤取公告取不到、版本资讯帖的长图给了开始时间：只进日报；长图也没有：报群]")
    saved_cal = (_b.wuwa_calendar_image, _b._wuwa_calendar_start)
    _b.wuwa_calendar_image = lambda notice: ("3.7", "1", "https://example.invalid/cal.png")
    _b._wuwa_calendar_start = lambda *a, **k: None


    def kuro(path, payload):
        if payload.get("eventType") == 3:          # the gacha notices
            raise OSError("库街区 502")
        return {"code": 200, "data": {"list": without_post}}


    try:
        logs.clear()
        at = _b._wuwa_second_half({}, "余心所向九死未悔", "锁暝", now, None, read, None, _b.Trace.new(),
                                  kuro, bili(feed))
        check("the poster gave the start", at, span[0])
        check("one recovered WARNING about the gacha notice, first line plain",
              [("唤取公告没取到" in m and "长图给出了" in m, texts.plain(m.splitlines()[0]))
               for m in logs.recovered() if "唤取公告" in m], [(True, [])])
        check("nothing for the group", logs.loud(), [])
        logs.clear()
        at = _b._wuwa_second_half({}, "余心所向九死未悔", "锁暝", now, None, read, None, _b.Trace.new(),
                                  kuro, bili(ended))
        check("nothing gave the start", at, None)
        check("the gacha notice's failure is a plain WARNING (pushed)",
              any("唤取公告取不到" in m for m in logs.loud()), True)
        check("nothing marked recovered", logs.recovered(), [])
    finally:
        _b.wuwa_calendar_image, _b._wuwa_calendar_start = saved_cal

    print("\n[版本日历图读不出、另一来源已给时间：只进日报；没别的来源：报群]")
    cal_notice = {"activity": [
        {"id": "50868", "tabTitle": "3.7版本活动日历", "startTimeMs": "1790712000000",
         "content": '<p><img src="https://example.invalid/cal.png" alt="" width="1080" height="2159"></p>'}]}
    logs.clear()
    tr = _b.Trace.new()
    day = _b._wuwa_calendar_start(cal_notice, "余心所向九死未悔", now, span[1], None, None, tr)
    check("另一来源已给出：图不读，日期 None", day, None)
    check("另一来源已给出：没有任何 WARNING（不读图就没有读不出）",
          (logs.recovered(), logs.loud()), ([], []))
    check("……trace 写「另一来源已给出」", any("另一来源已给出" in s for s in tr.sources), True)
    logs.clear()
    tr = _b.Trace.new()
    day = _b._wuwa_calendar_start(cal_notice, "余心所向九死未悔", now, span[1], None, {}, tr)
    check("没有别的来源：日期 None", day, None)
    check("……是 plain WARNING，报群",
          ([m for m in logs.loud() if "这条公告只有图，没读到字" in m][:1] != [], logs.recovered()),
          (True, []))

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_bili_pinned_post():
    """A pinned old post on page 1 does not stop the Bilibili feed paging.

Page 1 of the real feed (ww-bili-feed-2026-10-05.json) starts with a pinned post
from 09-19 above the 10-04/10-05 items. Paging stopped on the page's OLDEST item
being past the cutoff, so once the pinned post aged past it the feed stopped at
page 1 every day and the Bilibili door was closed without a word. It now stops
on the page's NEWEST item.

    Formerly test_bili_pinned_post.py.
    """
    import json
    import urllib.parse
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ark_relay.features.banners as _b
    from ark_relay.features import wuwa as P


    fx = json.loads((fx_dir(Path(__file__), "fixtures") / "ww-bili-feed-2026-10-05.json").read_text(encoding="utf-8"))
    pages = [p["response"] for p in fx["pages"]]
    nav = fx["nav"]["response"]
    by_offset = {"": pages[0], pages[0]["data"]["offset"]: pages[1], pages[1]["data"]["offset"]: pages[2]}
    asked = []


    def get(url, cookie):
        if "finger/spi" in url:
            return {"code": 0, "data": {"b_3": "B3", "b_4": "B4=="}}
        if "/nav" in url:
            return nav
        off = dict(urllib.parse.parse_qsl(url.split("?", 1)[1], keep_blank_values=True))["offset"]
        asked.append(off)
        return by_offset[off]


    first = [P._bili_at(i) for i in pages[0]["data"]["items"]]
    check("fixture: page 1 starts with the old pinned post", (f"{first[0]:%m-%d}", f"{max(first):%m-%d}"), ("09-19", "10-05"))

    # Cutoff = now - 50 days = 09-21: past the pinned 09-19 post, before every other
    # item on pages 1-3 (the 3.7 version-news post is on page 3, 09-28).
    now = datetime(2026, 11, 10, 12, 0)
    check("the cutoff falls between the pinned post and the rest",
          first[0] < now - P._BILI_OLDEST < sorted(first)[1], True)
    ticks = iter(range(1759600000, 1759700000, 7))
    got = _b._bili_poster("3.7", now, get, lambda s: None, lambda: next(ticks))
    check("paging goes past page 1 and finds the 3.7 post on page 3",
          got[0] if got else None, "https://www.bilibili.com/opus/1253061864718336024")
    check("three pages were read", len(asked), 3)


def _part_event_expiry():
    """活动结束后的提醒：三天窗口，文案讲的是活动商店。

2026-08-24 运营看到"活动「直到大地变成一颗酸橙」已结束——主关卡若还是活动关，
下一轮必失败，记得换关"，说它过时。查了真机数据：活动是 08-22 03:59 结束的，
距今 2.77 天，**三天窗口本身是生效的**，第二天就会自己消失。过时的是内容——
主关卡早就是 AT-4 这种常驻关，"换关"永远不可能适用。

改成两件事：说活动商店该搬空了（结束后真正还来得及做的事），并写出这条提醒
还会出现多久，免得同一句话连出三天看起来像卡死。

    Formerly test_event_expiry.py.
    """
    import json, os, sys
    from datetime import datetime, timedelta, timezone

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.plan import activity_countdown

    CN = timezone(timedelta(hours=8))


    def cache(name, end):
        """写一份 MAA 形状的活动缓存。"""
        p = TMP / f"{name}.json"
        p.write_text(json.dumps({"Official": {"sideStoryStage": {"a": {"Activity": {
            "StageName": name, "TimeZone": 8,
            "UtcExpireTime": end.strftime("%Y/%m/%d %H:%M:%S")}}}}}),
            encoding="utf-8")
        return p

    NOW = datetime(2026, 8, 24, 22, 27, tzinfo=CN)

    print("[结束 2.77 天：还在窗口内]")
    out = activity_countdown(None, now=NOW,
                             cache_path=cache("酸橙", NOW - timedelta(days=2, hours=18, minutes=28)))
    check("有提醒", "已于" in out, True)
    check("讲的是活动商店", "活动商店" in out, True)
    check("不再叫人换关", "换关" in out, False)
    check("写了还剩多久", "此提醒还会出现" in out, True)
    check("剩不到一天", "还会出现 5 时" in out, True)

    print("\n[结束 3 天多：不该再出现]")
    out = activity_countdown(None, now=NOW,
                             cache_path=cache("红丝绒", NOW - timedelta(days=3, minutes=1)))
    check("彻底安静", out.strip(), "")

    print("\n[刚结束几分钟：窗口最满]")
    out = activity_countdown(None, now=NOW,
                             cache_path=cache("刚结束", NOW - timedelta(minutes=5)))
    check("还剩 2 天多", "还会出现 2 天 23 时" in out, True)

    print("\n[还没结束：走倒计时，不是结束提醒]")
    out = activity_countdown(None, now=NOW,
                             cache_path=cache("墟", NOW + timedelta(days=7, hours=5)))
    check("没有结束提醒", "已于" in out, False)
    check("有倒计时", "剩" in out and "结束" in out, True)

    print("\n[缓存在但读不了：说一次，不再默默没有倒计时（2026-11-08）]")
    import logging
    from ark_relay.core import plan as _plan


    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines = []

        def emit(self, r):
            self.lines.append((r.levelno, r.getMessage()))


    _g = _Grab()
    _plan.log.addHandler(_g)
    _lvl = _plan.log.level
    _plan.log.setLevel(logging.DEBUG)
    _plan._last_error.pop("activity", None)
    broken = TMP / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    check("读不了还是空", activity_countdown(None, now=NOW, cache_path=broken), "")
    check("读不了的说一次", [m for lv, m in _g.lines if lv == logging.WARNING and "活动表读不了" in m] != [], True)
    n = len(_g.lines)
    activity_countdown(None, now=NOW, cache_path=broken)
    check("同一个毛病不重复说", len(_g.lines), n)
    activity_countdown(None, now=NOW, cache_path=cache("又好了", NOW + timedelta(days=1)))
    check("好了以后忘掉，下次坏了再说", "activity" in _plan._last_error, False)
    check("还没有缓存（新装的 MAA）：只记一行，不推群",
          (activity_countdown(None, now=NOW, cache_path=TMP / "none.json"),
           [lv for lv, m in _g.lines if "活动表还没有" in m]), ("", [logging.INFO]))
    _plan.log.removeHandler(_g)
    _plan.log.setLevel(_lvl)


def _part_skland_api():
    """The Skland calls: device id, login, refresh, bindings, Endfield card, role.

No network: urllib.request.urlopen is replaced by a recorder that answers
each URL with a canned JSON body (gzip-compressed where the real server does
it, see skland._read). What is tested is the relay's own judgement: a wrong
return code raises with its reason and is never taken as a success, the
device id is cached and sent where it must be, and with several Endfield
roles and none named the role lookup refuses with the list instead of
silently taking the first (audit 2026-10-05).

The response shapes follow docs/SKLAND-API.md (roleId / serverId in
bindingList[].roles[]); no real binding response is on file.

    Formerly test_skland_api.py.
    """
    #!/usr/bin/env python3

    import gzip
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import skland


    def raises(fn) -> str:
        """The SklandError message, or "" when nothing was raised."""
        try:
            fn()
        except skland.SklandError as exc:
            return str(exc) or "(empty)"
        return ""


    class Resp:
        def __init__(self, body: dict, gz: bool):
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self._raw = gzip.compress(raw) if gz else raw
            self.headers = {"Content-Encoding": "gzip"} if gz else {}

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


    sent: list[dict] = []
    answers: dict = {}


    def fake_urlopen(req, timeout=None):
        url = req.full_url
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        sent.append({"url": url, "body": body, "headers": {k.lower(): v for k, v in req.header_items()}})
        a = answers[url.split("?")[0]]
        a = a(url) if callable(a) else a
        return Resp(a, gz=len(sent) % 2 == 0)      # every other answer gzip'd


    skland.urllib.request.urlopen = fake_urlopen
    CRED = skland.Cred(cred="c", token="t", userId="u", dId="Bdev")


    def main() -> int:
        print("[get_did: device fingerprint]")
        skland._did_cache = ""
        answers[skland.V4_URL] = {"code": 1101, "msg": "参数错误"}
        check("return code not 1100 -> raises with the reason", "参数错误" in raises(skland.get_did))
        answers[skland.V4_URL] = {"code": 1100, "detail": {}}
        check("no deviceId -> raises", "deviceId" in raises(skland.get_did))
        answers[skland.V4_URL] = {"code": 1100, "detail": {"deviceId": "XYZ"}}
        check("ok: prefixed with B", skland.get_did(), "BXYZ")
        n = len(sent)
        check("second call is cached, no request", (skland.get_did(), len(sent)), ("BXYZ", n))
        skland._did_cache = ""

        print("[login: token -> code -> cred]")
        answers[skland.GRANT_URL] = {"status": 1, "msg": "token 过期"}
        check("token refused -> raises with the reason", "token 过期" in raises(lambda: skland.login("tok", "Bdev")))
        answers[skland.GRANT_URL] = {"status": 0, "data": {"code": "CODE"}}
        answers[skland.CRED_URL] = {"code": 10002, "message": "设备信息无效"}
        check("cred exchange refused -> raises with the reason",
              "设备信息无效" in raises(lambda: skland.login("tok", "Bdev")))
        answers[skland.CRED_URL] = {"code": 0, "data": {"cred": "CR", "token": "TK", "userId": 42}}
        c = skland.login("tok", "Bdev")
        check("ok: cred / token / userId / dId", (c.cred, c.token, c.userId, c.dId), ("CR", "TK", "42", "Bdev"))
        check("the code is exchanged with the grant's code", sent[-1]["body"], {"code": "CODE", "kind": 1})
        check("the cred exchange carries the device id", sent[-1]["headers"].get("did"), "Bdev")
        check("the credential is not in repr", "TK" in repr(c) or "CR" in repr(c), False)

        print("[refresh: new token, clock offset]")
        answers[skland.REFRESH_URL] = {"code": 10001, "message": "操作失败"}
        check("refresh refused -> raises", "刷新失败" in raises(lambda: skland.refresh(CRED)))
        skland._synced, skland._clock_skew = False, 0
        now = int(skland.time.time())
        answers[skland.REFRESH_URL] = {"code": 0, "timestamp": str(now + 30), "data": {"token": "NEW"}}
        r = skland.refresh(CRED)
        check("new token", r.token, "NEW")
        check("offset recorded, marked synced", (abs(skland._clock_skew - 30) <= 1, skland._synced), (True, True))

        print("[bindings]")
        answers[skland.BINDING_URL] = {"code": 10000, "message": "未登录"}
        check("wrong return code -> raises", "未登录" in raises(lambda: skland.bindings(CRED)))

        def bind(*roles):
            return {"code": 0, "data": {"list": [
                {"appCode": "arknights", "bindingList": [{"uid": "1923", "channelMasterId": "1"}]},
                {"appCode": "endfield", "bindingList": [{"uid": "2474", "channelMasterId": "1",
                                                         "roles": [{"roleId": r, "serverId": s} for r, s in roles]}]},
            ]}}

        answers[skland.BINDING_URL] = bind(("111", "1"))
        check("ok: the list as given", [a["appCode"] for a in skland.bindings(CRED)], ["arknights", "endfield"])
        check("the request is signed", bool(sent[-1]["headers"].get("sign")) and sent[-1]["headers"].get("cred") == "c")

        print("[endfield_role]")
        check("one role -> that one", skland.endfield_role(CRED), ("111", "1"))
        answers[skland.BINDING_URL] = bind(("111", "1"), ("222", "2"))
        msg = raises(lambda: skland.endfield_role(CRED))
        check("two roles, none named -> refused with both listed, not the first",
              "2 个终末地角色" in msg and "111" in msg and "222" in msg, True)
        check("named -> that one", skland.endfield_role(CRED, role_id="222"), ("222", "2"))
        check("named but not bound -> refused", "333" in raises(lambda: skland.endfield_role(CRED, role_id="333")))
        answers[skland.BINDING_URL] = {"code": 0, "data": {"list": [{"appCode": "arknights", "bindingList": []}]}}
        check("no Endfield binding -> refused", "没找到" in raises(lambda: skland.endfield_role(CRED)))

        print("[endfield_card]")
        answers[skland.BINDING_URL] = bind(("111", "1"))
        skland._synced = False
        before = sum(1 for s in sent if s["url"] == skland.REFRESH_URL)
        answers[skland.ENDFIELD_CARD_URL] = lambda url: {"code": 0, "data": {"detail": {"url": url}}}
        d = skland.endfield_card(CRED)
        check("not synced -> refreshes first", sum(1 for s in sent if s["url"] == skland.REFRESH_URL), before + 1)
        check("no role given -> the only role", "roleId=111&serverId=1" in d["detail"]["url"])
        answers[skland.BINDING_URL] = bind(("111", "1"), ("222", "2"))
        check("two roles, none given -> refused, not the first",
              "2 个终末地角色" in raises(lambda: skland.endfield_card(CRED)))
        check("role given without server -> that role's server",
              "roleId=222&serverId=2" in skland.endfield_card(CRED, "222")["detail"]["url"])
        check("role and server given -> used as given",
              "roleId=222&serverId=2" in skland.endfield_card(CRED, "222", "2")["detail"]["url"])
        answers[skland.ENDFIELD_CARD_URL] = {"code": 10003, "message": "时间戳过期"}
        check("wrong return code -> raises with the reason",
              "时间戳过期" in raises(lambda: skland.endfield_card(CRED, "111", "1")))

        print()
        if fails:
            print(f"FAILED {len(fails)}: {fails}")
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_skland_http_error_body():
    """A Skland 4xx must keep the {"code", "message"} body it came with.

Audit s6 #5 (2026-10-13): _get / _post let urllib raise a bare HTTPError, so
Skland's own reason (10001 「操作失败，请稍后重试」 on a 403, measured 2026-08-27,
docs/SKLAND-API.md) never reached the log or the phone tile, which showed only
「HTTP Error 403」. Network is faked; no request leaves.

    Formerly test_skland_http_error_body.py.
    """
    import email.message
    import io
    import urllib.error

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import skland


    def refusing(code: int, body: bytes):
        def urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, code, "Forbidden", email.message.Message(), io.BytesIO(body))
        return urlopen


    real = skland.urllib.request.urlopen
    url = "https://zonai.skland.com/web/v1/game/endfield/card/detail?roleId=1&serverId=1"

    print("[403 with Skland's body: the code and message are in the error]")
    skland.urllib.request.urlopen = refusing(403, '{"code":10001,"message":"操作失败，请稍后重试"}'.encode())
    try:
        skland._get(url, {})
        said = ""
    except Exception as e:  # noqa: BLE001
        said = str(e)
    check("Skland's code is kept", "10001" in said, True)
    check("Skland's message is kept", "操作失败，请稍后重试" in said, True)
    check("the HTTP status is kept", "403" in said, True)

    print("\n[403 with no readable body: the plain HTTP error, as before]")
    skland.urllib.request.urlopen = refusing(403, b"<html>nope</html>")
    try:
        skland._get(url, {})
        got = None
    except Exception as e:  # noqa: BLE001
        got = type(e).__name__
    check("bare HTTPError", got, "HTTPError")
    skland.urllib.request.urlopen = real

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")


def _part_skland_role():
    """endfield_role never guesses between several bound Endfield roles.

No binding response has been recorded (fixtures/skland-endfield holds wiki and
catalog pages only), so the shape below follows docs/SKLAND-API.md line 24:
roleId and serverId sit in bindingList[].roles[]. Before 2026-10-06 the first
role was returned whatever else was bound.

    Formerly test_skland_role.py.
    """
    #!/usr/bin/env python3


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import skland

    FAILED: list[str] = []


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
        if not ok:
            FAILED.append(name)


    def _apps(*roles):
        return [{"appCode": "arknights", "bindingList": [{"uid": "1"}]},
                {"appCode": "endfield", "bindingList": [{"uid": "9", "roles": list(roles)}]}]


    def _role(apps):
        skland.bindings = lambda cred: apps
        try:
            return skland.endfield_role(None)
        except skland.SklandError as exc:
            return str(exc)


    def main() -> int:
        a = {"roleId": "1001", "serverId": "1"}
        b = {"roleId": "2002", "serverId": "2"}
        require("one role is returned", _role(_apps(a)) == ("1001", "1"), repr(_role(_apps(a))))
        require("the same role listed twice is still one role", _role(_apps(a, dict(a))) == ("1001", "1"))
        two = _role(_apps(a, b))
        require("two roles: refused, not the first one", isinstance(two, str) and "2 个终末地角色" in two, repr(two))
        skland.bindings = lambda cred: _apps(a, b)
        try:
            skland.endfield_role(None)
            kind, roles = "returned", []
        except skland.SklandError as exc:
            kind, roles = type(exc).__name__, getattr(exc, "roles", None)
        require("the refusal is its own type, carrying the roles (callers tell it by type, not text)",
                (kind, roles) == ("SklandMultiRole", [("1001", "1"), ("2002", "2")]), repr((kind, roles)))
        none = _role(_apps())
        require("no role: refused", isinstance(none, str) and "没找到" in none, repr(none))
        print()
        if FAILED:
            print(f"FAILED {len(FAILED)}: {FAILED}")
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_skland_sign():
    """The Skland request signature, recomputed independently.

Every Skland call carries a `sign`. Get any part of it wrong and the server
answers HTTP 403 `{"code":10001,"message":"操作失败，请稍后重试"}` - **it never
says which part**. On 2026-08-27 three things were wrong at once (platform,
vName, serverId) and the whole day went into the wrong line of investigation.

So this test does not trust the implementation to check itself. It rebuilds the
signature from the algorithm written in the module docstring, with its own
constants and its own key order, and demands the two agree:

    secret = path + query + timestamp + json({platform,timestamp,dId,vName})
    sign   = MD5(HMAC-SHA256(cred.token, secret))

That pins two things a refactor cannot see it has broken: the exact key order
inside the signed JSON (a dict rebuilt in a different order signs a different
string), and `platform` / `vName` staying at "3" / "1.0.0".

    Formerly test_skland_sign.py.
    """
    import hashlib
    import hmac
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import skland


    FIXED = 1757000000
    skland.time = type("t", (), {"time": staticmethod(lambda: float(FIXED))})()

    CRED = skland.Cred(cred="CRED-abc", token="TOKEN-xyz", userId="u1", dId="DID-1")


    def expect(path, query, ts, did):
        """The signature, spelled out from the docstring rather than reused."""
        header_ca = {"platform": "3", "timestamp": str(ts), "dId": did, "vName": "1.0.0"}
        secret = f"{path}{query}{ts}{json.dumps(header_ca, separators=(',', ':'))}"
        hexed = hmac.new(CRED.token.encode(), secret.encode(), hashlib.sha256).hexdigest()
        return hashlib.md5(hexed.encode()).hexdigest()


    print("[时钟：没校准过时就是本机时间]")
    skland._clock_skew = 0
    check("本机时间", skland.server_now(), FIXED)

    print("\n[校准过之后每次请求都带「服务器时间＋本机走过的时间」]")
    skland._clock_skew = 37
    check("带上偏移", skland.server_now(), FIXED + 37)
    skland._clock_skew = -12
    check("偏移是负的也算得对", skland.server_now(), FIXED - 12)
    skland._clock_skew = 0

    print("\n[GET：签名和照着文档算出来的一模一样]")
    url = "https://zonai.skland.com/api/v1/game/player/binding?uid=1"
    h = skland.sign_headers(CRED, url)
    check("sign", h["sign"], expect("/api/v1/game/player/binding", "uid=1", FIXED, "DID-1"))
    check("cred 带上了", h["cred"], "CRED-abc")
    check("platform 是 3", h["platform"], "3")
    check("vName 是 1.0.0", h["vName"], "1.0.0")
    check("timestamp 是字符串", h["timestamp"], str(FIXED))
    check("dId 带上了", h["dId"], "DID-1")
    check("User-Agent 还在", "Skland" in h["User-Agent"], True)

    print("\n[时钟偏移会进签名——签的时刻和头里写的时刻必须是同一个]")
    skland._clock_skew = 60
    h4 = skland.sign_headers(CRED, url)
    check("头里是校准后的时刻", h4["timestamp"], str(FIXED + 60))
    check("签的也是同一个时刻", h4["sign"],
          expect("/api/v1/game/player/binding", "uid=1", FIXED + 60, "DID-1"))
    skland._clock_skew = 0

    print("\n[只有 GET 一种签法：没人用的 POST 请求体、现取 dId 两个参数删掉了（audit s6 #4）]")
    import inspect
    check("参数只剩凭据和网址", list(inspect.signature(skland.sign_headers).parameters), ["cred", "url"])

    print("\n[凭据没有 dId 时不去现取一个：签进去的就是凭据自己的]")
    calls = []
    orig_get_did = skland.get_did
    skland.get_did = lambda: (calls.append(1), "DID-NEW")[1]
    bare = skland.Cred(cred="CRED-abc", token="TOKEN-xyz")
    h7 = skland.sign_headers(bare, url)
    check("没去要新的", calls, [])
    check("头里是空的", h7["dId"], "")
    check("签名里也是空的", h7["sign"],
          expect("/api/v1/game/player/binding", "uid=1", FIXED, ""))
    skland.get_did = orig_get_did

    print("\n[token 不同签名必须不同，否则等于没签]")
    other = skland.Cred(cred="CRED-abc", token="TOKEN-OTHER", dId="DID-1")
    check("换了 token 签名就变", skland.sign_headers(other, url)["sign"] != h["sign"], True)


def _part_skland_sync_guard():
    """skland.get / bindings must align clocks first when this process has not yet.

Audit s6 #3 (2026-10-13): only endfield_card had the `if not _synced: refresh()`
guard. banners.py calls login() then get(), so in a process where no phone
session had refreshed first, the request was signed with the local clock
(Skland answers 10003 when it is off). Network is faked; no request leaves.

    Formerly test_skland_sync_guard.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import skland


    calls: list = []


    def fake_get(url, headers):
        calls.append(url.split("?")[0])
        if url.startswith(skland.REFRESH_URL):
            return {"code": 0, "timestamp": 2_000_000_000, "data": {"token": "TOKEN-NEW"}}
        return {"code": 0, "data": {"list": []}}


    skland._get = fake_get
    cred = skland.Cred(cred="CRED", token="TOKEN-OLD", dId="DID")

    for name, call, target in (("get", lambda: skland.get(cred, "/api/v1/game/x"), skland.ZONAI + "/api/v1/game/x"),
                               ("bindings", lambda: skland.bindings(cred), skland.BINDING_URL)):
        print(f"\n[{name}: first call in a fresh process refreshes first]")
        skland._synced = False
        skland._clock_skew = 0
        calls.clear()
        call()
        check("refresh, then the request", calls, [skland.REFRESH_URL, target])
        print(f"[{name}: once aligned, no second refresh]")
        calls.clear()
        call()
        check("only the request", calls, [target])

    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} failed")


def _part_skland_arknights_annihilation():
    """arknights_uid picks the default Arknights role; arknights_annihilation reads campaign.reward.

The response shape is the one measured 2026-11-16 09:20:38 from the Mac (code 0,
data.campaign.reward {"current": 1800, "total": 1800}, data.status.storeTs), with
made-up uids. Network is faked; no request leaves.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import skland

    asked: list = []

    def apps(*roles):
        return [{"appCode": "endfield", "bindingList": [{"uid": "e1", "roles": []}]},
                {"appCode": "arknights", "bindingList": list(roles)}]

    def uid(listing):
        skland.bindings = lambda cred: listing
        try:
            return skland.arknights_uid(None)
        except skland.SklandError as exc:
            return type(exc).__name__

    print("[which role]")
    check("the default role of two", uid(apps({"uid": "11", "isDefault": False}, {"uid": "22", "isDefault": True})), "22")
    check("the only role, not marked default", uid(apps({"uid": "11"})), "11")
    check("two roles, none default: refused", uid(apps({"uid": "11"}, {"uid": "22"})), "SklandError")
    check("no Arknights role: refused", uid(apps()), "SklandError")

    def read(answer):
        skland.bindings = lambda cred: apps({"uid": "22", "isDefault": True})

        def fake_get(cred, path):
            asked.append(path)
            return answer
        skland.get = fake_get
        try:
            return skland.arknights_annihilation(None)
        except skland.SklandError as exc:
            return type(exc).__name__

    print("\n[the reading]")
    ok = {"code": 0, "message": "OK", "data": {"campaign": {"reward": {"current": 1800, "total": 1800}},
                                               "status": {"storeTs": 1794791397}}}
    check("full week, with when it was stored", read(ok), {"current": 1800, "total": 1800, "store_ts": 1794791397})
    check("asked for the default role", asked[-1], "/api/v1/game/player/info?uid=22")
    check("an error code: refused", read({"code": 10001, "message": "x"}), "SklandError")
    check("no reward in the answer: refused", read({"code": 0, "data": {"campaign": {}}}), "SklandError")
    no_ts = {"code": 0, "data": {"campaign": {"reward": {"current": 400, "total": 1800}}}}
    check("no storeTs reads as 0 (the caller then refuses it)", read(no_ts), {"current": 400, "total": 1800, "store_ts": 0})


def _part_needtable_publish():
    """The relay keeps the App's need table current by itself (needtable.py).

Until 2026-10-14 the table was rebuilt only when someone ran scripts/mac/build-need-tables.py
and deploy-web.sh by hand; the last run was 09-23, and the two six-stars announced since
(祀, 明河) never reached the App. Pinned here:

* the object's name is the phone state's hash + `.need.json` (the App derives the same:
  ark-remote Relay.needURL; the hex for "ark-test-topic" is pinned on both sides);
* a due day builds once, on a thread of its own, and PUTs the table public-read (cos_put's
  default) with the state's timeout; a day that has its table does not build again; the next does;
* a build or a PUT that fails is an INFO line and a red item in the technical log, never
  raises, and is tried once more the same day at least 30 min later - at most two builds a
  server day, even when the mark file cannot be written;
* a day's second failed try, or two failed builds in a row that no group message covered
  yet (a day's lone try and the next day's first), is one plain WARNING (the group) at
  once, every time - no three-day wait (Gemini's dispatch relay-audit-round2-1108 N-01, 2026-11-08);
* a build that works after a failure (the same day's second try, or a later day) is one
  WARNING marked errwatch.recovered() (daily report only) naming the failure and the days
  missed;
* a machine without a topic, COS or Skland token builds nothing and says so at INFO;
* the engine's tick runs the step.

No network: the table is built offline from fixtures/skland-endfield-1015 (祀 current, 明河 next;
skland-endfield-1014 until the 2026-10-15 two-standard caliber), the PUT is a recorder.

    Formerly test_needtable_publish.py.
    """
    import inspect
    import json
    import logging
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    sys.path.insert(0, str(HERE))


    def done():
        print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
        sys.exit(1 if fails else 0)


    try:
        from ark_relay.features import needtable as build, needtable
    except ImportError as exc:
        check("the relay has a need-table step (ark_relay.features.needtable)", str(exc), "")
        done()
    from ark_relay.core import engine, statestore as techlog
    from ark_relay.features import errwatch
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.phone import state_key
    from ark_relay.features.phone import Mailbox

    FIX15 = fx_dir(HERE, "fixtures") / "skland-endfield-1015"
    D1 = datetime(2026, 10, 14, 9, 0, tzinfo=SERVER_TZ)
    D2, D3, D4, D5, D6, D7, D8, D9 = (datetime(2026, 10, d, 9, 0, tzinfo=SERVER_TZ) for d in range(15, 23))


    class Records(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.rows = []

        def emit(self, record):
            self.rows.append((record.levelname, record.getMessage(), bool(getattr(record, errwatch.RECOVERED, False))))


    rec = Records()
    needtable.log.addHandler(rec)
    needtable.log.setLevel(logging.DEBUG)
    needtable.log.propagate = False


    def cfg_with(topic="ark-test-topic", token="test-token"):
        # state/ inside its own temp dir: the technical log goes next to it (techlog.tech_dir)
        d = tmpdir() / "state"
        d.mkdir()
        return SimpleNamespace(state_dir=d, phone_topic=topic, skland_token=token)


    def reds(c):
        """The red items the need table wrote to the day's technical log."""
        try:
            text = techlog.path_for("2026-10-14", c.state_dir).read_text(encoding="utf-8")
        except OSError:
            return []
        return [t for _, t in techlog.unhandled(text)]


    def offline():
        return build.make(build.RulesSource(FIX15, None))


    puts = []


    def put_ok(cos, key, data, timeout):
        puts.append((cos, key, data, timeout))
        return None


    print("[名字：和手机状态同一个哈希，后缀 .need.json；App 那边算出同一个]")
    check("need_key", needtable.need_key("ark-test-topic"), "state/d980719e5e0b17d6d61cc31f7b36a714.need.json")
    check("与 state_key 同一个哈希", needtable.need_key(" Ark-Test-Topic "), state_key("ark-test-topic")[:-5] + ".need.json")

    print("\n[到期的一天：建一次、放上 COS（公开读，状态的超时）]")
    c = cfg_with()
    check("没建过就到期", needtable.due(c.state_dir, "2026-10-14"), True)
    ok = needtable.refresh(c, D1, make=offline, cos="COS", put=put_ok)
    check("建好并放上", ok, True)
    check("放了一次", len(puts), 1)
    cos, key, data, timeout = puts[0]
    check("放的位置", (cos, key), ("COS", needtable.need_key("ark-test-topic")))
    check("超时同手机状态", timeout, Mailbox.COS_TIMEOUT)
    table = json.loads(data.decode("utf-8"))
    check("内容就是祀（当前）+ 明河（下一位）那张表", ([x["name"] for x in table["games"][0]["standards"]], table["built"]),
          (["祀", "明河"], "2026-10-15 16:05 UTC+8"))
    check("cos_put 默认公开读（App 没有 COS 钥匙）",
          inspect.signature(needtable.cos_put).parameters["public"].default, True)
    check("当天不再到期", needtable.due(c.state_dir, "2026-10-14"), False)
    check("第二天又到期", needtable.due(c.state_dir, "2026-10-15"), True)
    check("成功是一行 INFO", [r for r in rec.rows if r[0] != "INFO"], [])

    print("\n[引擎的那一步：到期才起线程，同一天不起第二次]")
    needtable._running.clear()
    c2 = cfg_with()
    started = []


    def fake_start(fn):
        started.append(fn)


    check("到期：起一个", needtable.step(c2, D1, start=fake_start), True)
    started[0]()   # the thread's work, run here: this config has no COS, so it ends at INFO without the network
    check("到期那次跑完记了当天", needtable.due(c2.state_dir, "2026-10-14"), False)
    check("同一天：不起", needtable.step(c2, D1, start=fake_start), False)
    check("第二天：再起", needtable.step(c2, D2, start=fake_start), True)
    src = inspect.getsource(engine.Engine.tick)
    check("tick 里有这一步", '("需求表", self._need_table)' in src, True)
    check("这一步调 needtable.step", "needtable.step(self.cfg)" in inspect.getsource(engine.Engine._need_table), True)

    print("\n[第一次建不成：INFO + 技术日志红项，不推送；表还是上次的]")
    rec.rows.clear()
    puts.clear()
    c3 = cfg_with()
    T = "2026-10-14"


    def broken():
        raise RuntimeError("明河: cannot pick hers")


    def mins(m, base=D1):
        return base + timedelta(minutes=m)


    check("建不成返回 False", needtable.refresh(c3, D1, make=broken, cos="COS", put=put_ok), False)
    check("没放（COS 上留着上次那份）", puts, [])
    check("一条 INFO，带原因，没有 WARNING", [(lv, "cannot pick hers" in m) for lv, m, _ in rec.rows], [("INFO", True)])
    check("技术日志一条红项，带原因", [("cannot pick hers" in t) for t in reds(c3)], [True])
    check("30 分钟内不再试", needtable.due(c3.state_dir, T, mins(10)), False)
    check("30 分钟后再试一次", needtable.due(c3.state_dir, T, mins(31)), True)

    print("\n[当天第二次也没建成：当场一条进群的 WARNING]")
    rec.rows.clear()
    check("第二次也建不成", needtable.refresh(c3, mins(31), make=broken, cos="COS", put=put_ok), False)
    check("一条 INFO 带原因，一条进群的 WARNING（没标自己好了）",
          [(lv, r) for lv, _, r in rec.rows], [("INFO", False), ("WARNING", False)])
    check("WARNING 说连着 2 次、带原因、不带报错堆栈",
          [("2 次" in m and "cannot pick hers" in m, "Traceback" not in m) for lv, m, _ in rec.rows if lv == "WARNING"],
          [(True, True)])
    check("第二条红项", len(reds(c3)), 2)
    check("当天不再到期", needtable.due(c3.state_dir, T, mins(240)), False)
    check("第二天又到期", needtable.due(c3.state_dir, "2026-10-15", D2), True)
    rec.rows.clear()
    c3b = cfg_with()
    check("放不上返回 False", needtable.refresh(c3b, D1, make=offline, cos="COS", put=lambda *a: "回 403"), False)
    check("放不上也是 INFO，带原因", [(lv, "回 403" in m) for lv, m, _ in rec.rows], [("INFO", True)])
    check("放不上也记红项", [("回 403" in t) for t in reds(c3b)], [True])


    def fail_day(c, day, tries=2):
        for i in range(tries):
            needtable.refresh(c, mins(31 * i, day), make=broken, cos="COS", put=put_ok)


    def warnings():
        return [(m, recovered) for lv, m, recovered in rec.rows if lv == "WARNING"]


    print("\n[每天两次都没建成：每天都当场进群一条，不等三天、不只报一次]")
    rec.rows.clear()
    c5 = cfg_with()
    fail_day(c5, D1, tries=1)
    check("第一次没成：还没有 WARNING", warnings(), [])
    needtable.refresh(c5, mins(31, D1), make=broken, cos="COS", put=put_ok)
    check("当天第二次也没成：一条进群的 WARNING", [r for _, r in warnings()], [False])
    fail_day(c5, D2)
    fail_day(c5, D3)
    check("第二天、第三天各一条，都进群", [r for _, r in warnings()], [False, False, False])

    print("\n[失败几天后建成：一条标「自己好了」的 WARNING（只进日报），说漏了几天]")
    rec.rows.clear()
    check("第四天建成", needtable.refresh(c5, D4, make=offline, cos="COS", put=put_ok), True)
    w = warnings()
    check("一条 WARNING，标自己好了", [r for _, r in w], [True])
    check("说漏了 3 天", ["3 天" in m for m, _ in w], [True])
    rec.rows.clear()
    needtable.refresh(c5, D5, make=offline, cos="COS", put=put_ok)
    check("再下一天建成：没有 WARNING", warnings(), [])

    print("\n[当天第一次没成、半小时后重试成了：一条标「自己好了」的 WARNING（只进日报）]")
    rec.rows.clear()
    c6 = cfg_with()
    needtable.refresh(c6, D1, make=broken, cos="COS", put=put_ok)
    check("当天重试建成", needtable.refresh(c6, mins(31), make=offline, cos="COS", put=put_ok), True)
    check("一条标自己好了的 WARNING，说第一次为什么没成、没说漏了几天",
          [(r, "cannot pick hers" in m, "天没算成" in m) for m, r in warnings()], [(True, True, False)])

    print("\n[一天只试了一次（第二次没轮到），第二天第一次又没成：当场进群，不再往后拖]")
    rec.rows.clear()
    c7 = cfg_with()
    fail_day(c7, D1, tries=1)
    fail_day(c7, D2, tries=1)
    check("两次连着没成：一条进群的 WARNING", [(r, "2 次" in m) for m, r in warnings()], [(False, True)])
    rec.rows.clear()
    needtable.refresh(c7, mins(31, D2), make=broken, cos="COS", put=put_ok)
    check("当天第二次也没成：照样进群一条，说连着 3 次", [(r, "3 次" in m) for m, r in warnings()], [(False, True)])
    c7b = cfg_with()
    fail_day(c7b, D1)
    rec.rows.clear()
    needtable.refresh(c7b, D2, make=offline, cos="COS", put=put_ok)
    check("漏了一天后建成：一条自己好了的 WARNING，说 1 天", [(r, "1 天" in m) for m, r in warnings()], [(True, True)])

    print("\n[没有森空岛令牌：INFO 一句，不建，当天不再试]")
    rec.rows.clear()
    puts.clear()
    c8 = cfg_with(token="")
    called = []
    check("没令牌返回 False",
          needtable.refresh(c8, D1, make=lambda: called.append(1) or offline(), cos="COS", put=put_ok), False)
    check("没建、没放", (len(called), len(puts)), (0, 0))
    check("只是 INFO", {lv for lv, _, _ in rec.rows}, {"INFO"})
    check("当天不再到期", needtable.due(c8.state_dir, T, mins(240)), False)

    print("\n[记号写不进去：一天照样最多建两次]")
    needtable._running.clear()
    c9 = cfg_with()    # no COS: each build ends at INFO, no network
    real_write = needtable.atomic_write_text


    def no_disk(*a, **k):
        raise OSError("disk full")


    needtable.atomic_write_text = no_disk
    starts = []
    try:
        for m in (0, 5, 31, 40, 62, 180, 360, 840):   # 09:00 to 23:00 of one server day
            needtable.step(c9, mins(m), start=lambda fn: (starts.append(1), fn()))
        check("同一天起了 2 次", len(starts), 2)
        needtable.step(c9, D2, start=lambda fn: (starts.append(1), fn()))
        check("第二天又能起", len(starts), 3)
    finally:
        needtable.atomic_write_text = real_write

    print("\n[机器上建表：把装着的 MaaEnd 交给建表（基质建议读它自己的数据）]")
    seen = {}
    real_rs, real_make = build.RulesSource, build.make
    build.RulesSource = lambda offline, save, token="", maaend_dir=None: seen.update(token=token, maaend_dir=maaend_dir) or "SRC"
    build.make = lambda src, **k: {"src": src}
    try:
        got = needtable._live_table(SimpleNamespace(skland_token="tok", maaend_dir=Path("D:/ark/maaend")))
    finally:
        build.RulesSource, build.make = real_rs, real_make
    check("令牌和 MaaEnd 目录都交过去", (got, seen), ({"src": "SRC"}, {"token": "tok", "maaend_dir": Path("D:/ark/maaend")}))

    print("\n[没配信箱或 COS 的机器：不建，INFO 说一句]")
    rec.rows.clear()
    puts.clear()
    c10 = cfg_with(topic="")
    check("没 topic", needtable.refresh(c10, D1, make=offline, cos="COS", put=put_ok), False)
    c11 = cfg_with()
    c11.cos_secret_id = ""
    check("没 COS", needtable.refresh(c11, D1, make=offline, put=put_ok), False)
    check("都只是 INFO", {lv for lv, _, _ in rec.rows}, {"INFO"})
    check("没放", puts, [])

    done()


def _part_needtable_trims():
    """The need table's trims: what each keeps of a live Skland / GitHub answer.

The relay runs these on every live answer of the daily build (needtable/build.py,
RulesSource.get / get_url); the offline tests read fixtures that were trimmed already, so
until 2026-10-14 no test ran them (the deploy's coverage gate: 9 new functions never
touched). Each case feeds an answer shaped like the live one, with the extra fields the
trim must drop, and checks exactly what is kept.

    Formerly test_needtable_trims.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import needtable as build


    cat = {"catalog": [{"typeSub": [
        {"name": "干员", "filterTagTree": [{"id": build.WEAPON_TAG_GROUP, "children": [{"id": "1", "name": "长柄"}]},
                                            {"id": "x", "children": [{"id": "9", "name": "无关"}]}],
         "items": [{"itemId": "100", "name": "明河", "publishedAtTs": 5, "cover": "url",
                    "brief": {"dotType": 2, "subTypeList": [{"id": "1"}], "desc": "长"}}]},
        {"name": "物品", "items": [{"itemId": "7", "name": "折金票", "cover": "url", "brief": {}}]}]}]}
    got = build.trim_catalog(cat)["catalog"][0]["typeSub"]
    check("干员 keeps weapon tags, id/name/published/brief bits", got[0],
          {"name": "干员", "weaponTags": {"1": "长柄"}, "items": [
              {"itemId": "100", "name": "明河", "publishedAtTs": 5, "brief": {"dotType": 2, "subTypeList": [{"id": "1"}]}}]})
    check("other subtypes only id -> name", got[1], {"name": "物品", "items": [{"itemId": "7", "name": "折金票"}]})

    item = {"item": {"itemId": "2", "name": "X", "publishedAtTs": 3, "cover": "u", "document": {"a": [
        {"label": "上线时间", "value": "2026-11-05"}, {"label": "类型", "value": "材料"},
        {"label": "主要获取方式", "value": "采集"}, {"label": "别的", "value": "丢掉"}]}}}
    check("wiki item keeps three attrs", build.trim_wiki_item(item),
          {"item": {"itemId": "2", "name": "X", "publishedAtTs": 3,
                    "attrs": {"上线时间": "2026-11-05", "类型": "材料", "主要获取方式": "采集"}}})

    doc = {"item": {"itemId": "5", "name": "D", "document": {
        "chapterGroup": [{"title": "武器信息", "widgets": [{"id": "w1", "title": "突破", "extra": 1}]}],
        "widgetCommonMap": {"w1": {"tabDataMap": {"t": {"content": "d1"}, "e": {"content": ""}}}, "w2": {"tabDataMap": {}}},
        "documentMap": {"d1": {"blockMap": {"b": {"text": {"inlineElements": [
            {"kind": "entry", "entry": {"id": 42, "count": "3", "showType": "card-big"}},
            {"kind": "entry", "entry": {"id": 43, "count": "1", "showType": "inline"}},
            {"kind": "text", "text": "说明"}]}}}},
            "d2": {"blockMap": {"b": {"text": {"inlineElements": []}}}}}}}}
    check("wiki doc keeps chapters, widget tabs and big cards only", build.trim_wiki_doc(doc),
          {"item": {"itemId": "5", "name": "D", "document": {
              "chapterGroup": [{"title": "武器信息", "widgets": [{"id": "w1", "title": "突破"}]}],
              "widgetCommonMap": {"w1": {"tabDataMap": {"t": {"content": "d1"}}}},
              "documentMap": {"d1": {"cards": [{"id": "42", "count": 3}]}}}}})

    check("search chars", build.trim_search_chars({"chars": [{"id": "a", "name": "N", "rarity": 6, "weaponType": 2, "x": 1}]}),
          {"chars": [{"id": "a", "name": "N", "rarity": 6, "weaponType": 2}]})
    check("search weapons", build.trim_search_weapons({"weapons": [{"id": "w", "name": "唤月", "x": 1}]}),
          {"weapons": [{"id": "w", "name": "唤月"}]})
    check("rules drop talents only", build.trim_rules({"chars": [{"id": "a", "talents": [1], "levels": [2]}], "weaponLevelRules": [3]}),
          {"chars": [{"id": "a", "levels": [2]}], "weaponLevelRules": [3]})
    check("foresight keeps the top stage and weapon ids", build.trim_foresight(
        {"c1": {"rarity": 6, "weaponIds": ["w"], "stageMaterials": {"1": ["a"], "4": ["d"], "3": ["c"]}, "x": 1},
         "c2": {"stageMaterials": {}}}),
          {"c1": {"charId": "c1", "rarity": 6, "weaponIds": ["w"], "stageMaterials": {"4": ["d"]}},
           "c2": {"charId": "c2", "rarity": None, "weaponIds": [], "stageMaterials": {}}})
    check("item names: only iconRecognition.name.item_*", build.trim_item_names(
        {"iconRecognition.name.item_gold": "折金票", "iconRecognition.name.other": "x", "ui.ok": "好"}),
          {"item_gold": "折金票"})
    origin = {"item": {"itemId": "9", "name": "O", "document": {
        "chapterGroup": [{"title": build.ORIGIN_CHAPTER, "widgets": [{"id": "w"}]}, {"title": "别的", "widgets": [{"id": "v"}]}],
        "widgetCommonMap": {"w": {"tabDataMap": {"t": {"content": "c"}}}, "v": {"tabDataMap": {"t": {"content": "z"}}}},
        "documentMap": {"c": {"blockIds": ["b2", "b1"], "blockMap": {
            "b1": {"text": "采集：", "children": [{"text": "四号谷地"}]}, "b2": {"text": "  "}}},
            "z": {"blockMap": {"b": {"text": "不要"}}}}}}}
    check("origin keeps the 物品来源 chapter's blocks in order", build.trim_wiki_origin(origin),
          {"itemId": "9", "name": "O", "lines": ["采集：四号谷地"]})

    # The client-data mirrors: from the game PC raw.githubusercontent.com reset the TLS
    # handshake (2026-10-14 10:30:06); the jsDelivr doors come first.
    raw = "https://raw.githubusercontent.com/MaaEnd/MaaEnd/v2/assets/locales/interface/zh_cn.json"
    check("doors: three jsDelivr mirrors, then raw", build.github_doors(raw), [
        "https://fastly.jsdelivr.net/gh/MaaEnd/MaaEnd@v2/assets/locales/interface/zh_cn.json",
        "https://cdn.jsdelivr.net/gh/MaaEnd/MaaEnd@v2/assets/locales/interface/zh_cn.json",
        "https://gcore.jsdelivr.net/gh/MaaEnd/MaaEnd@v2/assets/locales/interface/zh_cn.json", raw])
    check("another URL is its own door", build.github_doors("https://example.invalid/x"), ["https://example.invalid/x"])
    tried = []


    class _Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body


    def _urlopen(req, timeout=None):
        tried.append(req.full_url)
        if "gcore" not in req.full_url:
            raise ConnectionResetError(10054, "reset")
        return _Resp('{"iconRecognition.name.item_gold": "折金票"}'.encode("utf-8"))


    real = build.urllib.request.urlopen
    build.urllib.request.urlopen = _urlopen
    try:
        src = build.RulesSource.__new__(build.RulesSource)
        src.offline, src._store, src._memo = None, (lambda name, data: None), {}
        got = src.get_url("client-item-names", raw, build.trim_item_names)
    finally:
        build.urllib.request.urlopen = real
    check("a reset door is skipped, the next answers", (got, [u.split("/")[2] for u in tried]),
          ({"item_gold": "折金票"}, ["fastly.jsdelivr.net", "cdn.jsdelivr.net", "gcore.jsdelivr.net"]))
    check("an answer is kept for the rest of the build (no second request)",
          (src.get_url("client-item-names", raw, build.trim_item_names), len(tried)), ({"item_gold": "折金票"}, 3))

    # MaaEnd's essence files (build.essence_advice), shaped like assets/data/EssenceFilter/* and
    # tasks/AutoEssence/Target/Target.json of MaaEnd v2 on 2026-10-15.
    check("essence weapons: code -> CN name, CN skills, type, rarity", build.trim_essence_weapons(
        {"wpn_claym_0018": {"internal_id": "wpn_claym_0018", "weapon_type": "Claymores", "rarity": 6, "icon_path": "x.png",
                            "skill_ids": ["a"], "names": {"CN": "玉中身", "EN": "Jade Vessel"},
                            "skills": {"CN": ["智识提升·大", "寒冷伤害提升·大", "效益·落墨添彩"], "EN": ["Intellect [L]"]},
                            "foresight": True}}),
          {"wpn_claym_0018": {"name": "玉中身", "skills": ["智识提升·大", "寒冷伤害提升·大", "效益·落墨添彩"],
                              "type": "Claymores", "rarity": 6}})
    check("essence pools: id + cn per slot", build.trim_essence_pools(
        {"slot1": [{"cn": "智识", "tc": "智識", "en": "Intellect", "id": 5}], "slot2": [{"cn": "寒冷", "id": 1}],
         "slot3": [{"cn": "效益", "jp": "効率", "id": 7}]}),
          {"slot1": [{"id": 5, "cn": "智识"}], "slot2": [{"id": 1, "cn": "寒冷"}], "slot3": [{"id": 7, "cn": "效益"}]})
    check("essence locations: name and the slot 2 / 3 ids", build.trim_essence_locations(
        [{"name": "重度能量淤积点·枢纽区", "slot2_ids": [2, 1], "slot3_ids": [7], "slot2": [{"cn": "攻击"}]}]),
          [{"name": "重度能量淤积点·枢纽区", "slot2_ids": [2, 1], "slot3_ids": [7]}])
    check("essence matcher: only the data version", build.trim_essence_matcher(
        {"data_version": "2026-10-08 08:40:17 UTC", "similarWordMap": {"进": "迸"}}), {"data_version": "2026-10-08 08:40:17 UTC"})
    check("target: checkbox options -> case names; switches dropped", build.trim_essence_target({"option": {
        "AutoEssenceWeaponTypeClaymore": {"type": "switch", "cases": [{"name": "Yes"}]},
        "AutoEssenceWeaponsClaymore": {"type": "checkbox", "cases": [{"name": "wpn_claym_0018", "label": "$weapon.x", "icon": "i"}]}}}),
          {"AutoEssenceWeaponsClaymore": ["wpn_claym_0018"]})
    check("essence names: only option.AutoEssenceSkill.*", build.trim_essence_names(
        {"option.AutoEssenceSkill.s2_6": "源石技艺提升", "option.AutoEssenceMenu.label": "模式", "global.region.TheHub": "枢纽区"}),
          {"s2_6": "源石技艺提升"})


def _part_need_table():
    import json
    import sys
    from collections import Counter
    from pathlib import Path

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import fx_dir

    from ark_relay.features import needtable as bnt

    fails = []


    def check(label, got, want):
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
        if not ok:
            fails.append(label)


    def require(name, ok, detail=""):
        print(f"  {'✓' if ok else '✗'} {name}{(' - ' + detail) if detail and not ok else ''}")
        if not ok:
            fails.append(name)


    # 提弗洛斯 1→90, every breakthrough, four skills to 12 (rules?charIds=9de117d5…).
    TYPHOEUS = {
        "协议棱柱组": 472, "协议棱柱": 328, "协议圆盘组": 60, "协议圆盘": 33, "存续的痕迹": 24,
        "纯晶多齿叶": 16, "至晶多齿叶": 16, "晶化多齿叶": 12, "重红柱状菌": 5, "中红柱状菌": 5, "轻红柱状菌": 3,
        "D96钢样品四": 116, "快子遴捡晶格": 20, "红矛叶": 84, "塔罗斯菌": 8,
        "干员经验": 1_792_290,
    }
    # 寒夜幽影 1→90, every breakthrough (rules?weaponIds=4e7f3757…).
    WEAPON = {"重型强固模具": 50, "强固模具": 23, "中黯石": 5, "重黯石": 5, "轻黯石": 3, "协议纹石": 8, "武器经验": 2_524_080}
    SHARED = {"象限拟合液": (132, "干员 116 + 专武 16"), "折金票": (841_000 + 385_420 + 125_700 + 341_390, "干员 1,226,420 + 专武 467,090")}
    # The use section each of them lands in (rules: charBreak* nodes / skill levels 2-9 and 10-12 / weapon breakthroughs).
    USE_OF = {"协议圆盘组": "干员精英化", "协议圆盘": "干员精英化", "重红柱状菌": "干员精英化", "中红柱状菌": "干员精英化",
              "轻红柱状菌": "干员精英化", "快子遴捡晶格": "干员精英化", "塔罗斯菌": "干员精英化",
              "协议棱柱": "干员技能升级", "纯晶多齿叶": "干员技能升级", "至晶多齿叶": "干员技能升级", "晶化多齿叶": "干员技能升级",
              "存续的痕迹": "干员技能专精", "D96钢样品四": "干员技能专精", "红矛叶": "干员技能专精",
              "干员经验": "干员等级提升", "武器经验": "武器等级提升",
              "协议棱柱组": "多处共用", "象限拟合液": "多处共用", "折金票": "多处共用",
              **{k: "武器突破" for k in ("重型强固模具", "强固模具", "中黯石", "重黯石", "轻黯石", "协议纹石")}}
    UNUSED = ["三相纳米片", "超距辉映管", "受蚀玉化叶", "岩天使叶", "星门菌", "血菌", "武陵石", "燎石"]
    # 噗切娜 from the client preview table: her choices, and the two rows that carry talents.
    PURRCHENA = {"超距辉映管": 116, "三相纳米片": 116, "D96钢样品四": 20, "岩天使叶": 84, "塔罗斯菌": 8,
                 "协议圆盘组": 60, "协议圆盘": 33, "存续的痕迹": 24, "纯晶多齿叶": 16, "至晶多齿叶": 16, "晶化多齿叶": 12,
                 "协议棱柱组": 562, "协议棱柱": 461}
    FIX = fx_dir(HERE, "fixtures") / "skland-endfield"
    TODAY = "2026-09-18"


    def rows_by_name(table):
        g = table["games"][0]
        return g, {r["name"]: r for r in g["rows"]}


    print("[谁是最新六星：官方百科的上线时间，未来的也算]")
    src = bnt.RulesSource(FIX, None)
    ops = bnt.wiki_entries(src, "干员", "6")
    top, ranked = bnt.newest(ops)
    check("最新六星", (top["name"], top["onlineDate"], top["wikiItemId"], top["obtain"], top["dotType"]),
          ("提弗洛斯", "2026-09-02", "2116", "干员寻访·特许寻访", "label_type_up"))
    check("其次是梨诺", (ranked[1]["name"], ranked[1]["onlineDate"]), ("梨诺", "2026-08-09"))
    fives = bnt.wiki_entries(src, "干员", "5")
    ftop, _ = bnt.newest(fives)
    check("五星那边：未实装的噗切娜排第一", (ftop["name"], ftop["onlineDate"], ftop["dotType"]), ("噗切娜", "2026-09-24", "label_type_preview"))
    check("日期解析", (bnt.parse_online_date("2026年9月2日"), bnt.parse_online_date("")), ("2026-09-02", ""))

    print("\n[专武：同日上线、同类型、限时特卖，唯一一把]")
    weapons = bnt.wiki_entries(src, "武器", "6")
    sig = bnt.signature_weapon(weapons, top, "施术单元")
    check("提弗洛斯的专武", (sig["name"], sig["onlineDate"], sig["kind"], sig["obtain"], sig["wikiItemId"]),
          ("寒夜幽影", "2026-09-02", "施术单元", "武库交易所·限时特卖", "2118"))
    same_day = sorted(w["name"] + "/" + w["obtain"] for w in weapons if w["onlineDate"] == "2026-09-02")
    check("同日的另一把是通行证武器，不算专武", same_day, ["寒夜幽影/武库交易所·限时特卖", "苦难的尽头/协议通行证·武器补给"])
    lai = next(o for o in ops if o["name"] == "莱万汀")
    check("同一规则给莱万汀找到熔铸火焰", bnt.signature_weapon(weapons, lai, "单手剑")["name"], "熔铸火焰")
    check("类型对不上就是没有，不猜", bnt.signature_weapon(weapons, top, "手铳"), None)

    print("\n[上线前的来源：百科词条的材料卡片 == 计算器 rules]")
    names = bnt.wiki_item_names(src)
    doc = src.get("wiki-doc-2116", "", "")
    cards = bnt.material_cards(doc, bnt.OP_CHAPTER, bnt.OP_WIDGETS, names)
    rule = src.get("rules-char-9de117d5969945ecfdbd70dac3a632e6", "", "")
    mat = bnt.material_table(src.get("material-list", "", ""))
    need, gold = bnt.char_need(rule)
    from_rules = Counter({mat[mid]["name"]: c for mid, c in need.items()})
    from_cards = Counter({k: v for k, v in cards.items() if k != "折金票"})
    check("提弗洛斯：卡片材料 == rules 材料（17 种）", from_cards, from_rules)
    check("卡片的折金票 = rules 里精英化+技能的金币减去装备位解锁", (cards["折金票"], gold - cards["折金票"]), (814_900, 26_100))
    wdoc = src.get("wiki-doc-2118", "", "")
    wcards = bnt.material_cards(wdoc, bnt.WP_CHAPTER, bnt.WP_WIDGETS, names)
    wrule = src.get("rules-weapon-4e7f3757fd7c98a1262bf4bca8fd9d83", "", "")
    wneed, wgold = bnt.weapon_need(wrule)
    check("寒夜幽影：卡片 == rules（材料和金币）", (Counter({k: v for k, v in wcards.items() if k != "折金票"}), wcards["折金票"]),
          (Counter({mat[mid]["name"]: c for mid, c in wneed.items()}), wgold))
    check("噗切娜的词条还没有材料卡片", dict(bnt.material_cards(src.get("wiki-doc-2117", "", ""), bnt.OP_CHAPTER, bnt.OP_WIDGETS, names)), {})

    print("\n[默认：提弗洛斯 + 寒夜幽影，用量来自计算器]")
    table = bnt.build(src, "fixture", TODAY)
    g, rows = rows_by_name(table)
    check("game 字段", (g["game"], g["gameId"]), ("终末地", "endfield"))
    check("caliber", g["caliber"], "最新六星 提弗洛斯（2026-09-02 上线）：1→90 全突破、四技能 12、专武 寒夜幽影 1→90；不含天赋")
    check("footnote", g["footnote"], "人份 = 库存 ÷ 提弗洛斯满练所需（1→90 全突破、四技能 12、专武 寒夜幽影 1→90，不含天赋；2026-09-02 上线的最新六星）")
    st = g["standards"][0]
    check("standards 只有一个，就是她", [(s["charId"], s["name"], s["rarity"], s["releasedAt"], s["status"]) for s in g["standards"]],
          [("9de117d5969945ecfdbd70dac3a632e6", "提弗洛斯", 6, "2026-09-02", "已实装")])
    check("默认标准 = 她", g["standard"], "9de117d5969945ecfdbd70dac3a632e6")
    check("没有已公布的下一位：只有当前这一个", (st["role"], st["label"], g["coverage"]["next"], g["coverage"]["nextError"]),
          ("current", "最新六星", None, ""))
    check("标准自带的节顺序 = 游戏层那份", st["groups"], g["groups"])
    check("专武写实名", (st["weapon"]["name"], st["weapon"]["id"], st["weapon"]["releasedAt"], st["weapon"]["kind"], st["weapon"]["status"]),
          ("寒夜幽影", "4e7f3757fd7c98a1262bf4bca8fd9d83", "2026-09-02", "施术单元", "已收录"))
    check("来源", st["sources"], {"need": bnt.SRC_CALC, "weapon": bnt.SRC_CALC, "levels": bnt.SRC_CALC})
    check("rows 镜像默认标准", g["rows"], st["rows"])
    cov = g["coverage"]
    check("coverage", (cov["operator"], cov["status"], cov["weapon"], cov["weaponStatus"], cov["asOf"]), ("提弗洛斯", "已实装", "寒夜幽影", "已收录", TODAY))
    require("coverage 里没有别人的数据", "universalCheckedOn" not in cov and "upcoming" not in cov)
    for name, want in TYPHOEUS.items():
        check(f"提弗洛斯 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["owner"]), (want, USE_OF[name], "干员"))
    for name, want in WEAPON.items():
        check(f"专武 寒夜幽影 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["owner"]), (want, USE_OF[name], "专武"))
    for name, (want, note) in SHARED.items():
        check(f"两边都要的 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["note"]), (want, "多处共用", note))
    check("用在两步的写出每步用量", {n: rows[n]["uses"] for n in ("协议棱柱组", "象限拟合液")},
          {"协议棱柱组": [{"use": "干员技能升级", "need": 116}, {"use": "干员技能专精", "need": 356}],
           "象限拟合液": [{"use": "干员技能专精", "need": 116}, {"use": "武器突破", "need": 16}]})
    check("节的顺序", g["groups"], ["干员精英化", "干员技能升级", "干员技能专精", "干员等级提升", "武器突破", "武器等级提升", "多处共用"])
    require("用途有出处", "三相纳米片" in g["useSource"] and "至晶多齿叶" in g["useSource"])
    print("\n[怎么来：百科「物品来源」原文，采集 / 理智关卡 / 其它]")
    check("怎么来：每种材料都查到了", g["originMissing"], [])
    check("怎么来：采集物", sorted(r["name"] for r in g["rows"] if (r.get("origin") or {}).get("kind") == "采集物"),
          sorted(["协议纹石", "红矛叶", "塔罗斯菌", "至晶多齿叶", "血菌", "中红柱状菌", "重黯石", "纯晶多齿叶", "重红柱状菌",
                  "中黯石", "受蚀玉化叶", "岩天使叶", "星门菌", "武陵石", "燎石", "轻黯石", "晶化多齿叶", "轻红柱状菌"]))
    check("怎么来：自选箱不是理智关卡", (rows["高阶培养自选箱Ⅰ"]["origin"]["kind"], rows["高阶培养自选箱Ⅰ"]["origin"]["其它"]),
          ("其它来源", ["协议通行证及各类活动奖励。", "四号谷地-物资调度终端购买。"]))
    check("怎么来：高阶素材的理智关卡原文", rows["三相纳米片"]["origin"]["理智关卡"],
          [l for l in rows["三相纳米片"]["origin"]["理智关卡"] if "协议空间" in l])
    require("怎么来：每条原文恰好落在一类", all(sorted(r["origin"]["采集"] + r["origin"]["理智关卡"] + r["origin"]["其它"]) ==
            sorted(set(r["origin"]["采集"] + r["origin"]["理智关卡"] + r["origin"]["其它"])) for r in g["rows"] if r.get("origin")))
    for name in UNUSED:
        check(f"不用 {name}", (rows[name]["need"], rows[name]["group"], rows[name]["note"]), (0, None, "提弗洛斯 的满练不用它"))
    require("没有一行写「因人而异」", not any("因人而异" in json.dumps(r, ensure_ascii=False) for r in g["rows"]))
    check("经验行是虚拟行", (rows["干员经验"].get("virtual"), rows["干员经验"]["id"], rows["武器经验"]["id"]), (True, "exp:char", "exp:weapon"))
    check("经验材料折算进虚拟行", {r["name"]: (r["exp"], r["sumInto"]) for r in g["rows"] if r.get("sumInto")},
          {"高级认知载体": (10000, "exp:char"), "初级认知载体": (1000, "exp:char"),
           "高级作战记录": (10000, "exp:char"), "中级作战记录": (1000, "exp:char"), "初级作战记录": (200, "exp:char"),
           "武器检查套组": (10000, "exp:weapon"), "武器检查装置": (1000, "exp:weapon"), "武器检查单元": (200, "exp:weapon")})
    for exp_row, sid in (("干员经验", "exp:char"), ("武器经验", "exp:weapon")):
        cards = sorted((r for r in g["rows"] if r.get("sumInto") == sid), key=lambda r: (-r["rarity"], r["name"]))
        o = rows[exp_row]["origin"]
        check(f"{exp_row}：怎么来 = 折进来那几种的并集", (o["kind"], o["from"], {k: set(o[k]) for k in ("采集", "理智关卡", "其它")}),
              (cards[0]["origin"]["kind"], [r["name"] for r in cards],
               {k: {l for r in cards for l in r["origin"][k]} for k in ("采集", "理智关卡", "其它")}))
        check(f"{exp_row}：图标借最高稀有度那件", (rows[exp_row]["icon"], rows[exp_row]["note"].endswith(f"图标借{cards[0]['name']}")),
              (cards[0]["icon"], True))
    check("自选箱不计人份",(rows["高阶培养自选箱Ⅰ"]["need"], rows["高阶培养自选箱Ⅰ"]["group"]), (None, None))
    check("sections", g["sections"], ["通用", "高阶素材", "采集", "经验与货币"])
    check("延迟那句是官方计算器页面说的", (g["lagMinutes"], "官方" in g["lagNote"]), (30, True))
    check("每行都在某一节里，经验材料不在", {r["section"] for r in g["rows"] if not r.get("sumInto")}, {"通用", "高阶素材", "采集", "经验与货币"})
    check("经验材料无节（折进两条经验行）", {r["section"] for r in g["rows"] if r.get("sumInto")}, {None})
    check("高阶素材一节", [r["name"] for r in g["rows"] if r["section"] == "高阶素材"],
          ["快子遴捡晶格", "D96钢样品四", "象限拟合液", "三相纳米片", "超距辉映管", "高阶培养自选箱Ⅰ"])
    check("经验与货币一节", [r["name"] for r in g["rows"] if r["section"] == "经验与货币"], ["干员经验", "武器经验", "折金票"])
    require("每种材料都有一行（40 种 + 2 个经验虚拟行）", len(g["rows"]) == 42, str(len(g["rows"])))
    require("每行都有 id / name / rarity / icon / need / group / section / stage / note",
            all({"id", "name", "rarity", "icon", "need", "group", "section", "stage", "note"} <= set(r) for r in g["rows"]))
    require("名字没有首尾空白", all(r["name"] == r["name"].strip() for r in g["rows"]))
    order = [r["name"] for r in g["rows"]]
    require("排序：按用途节，节内需求大的在前、不用的在后、无需求的最后",
            order.index("协议圆盘组") < order.index("协议棱柱") < order.index("D96钢样品四") < order.index("干员经验") < order.index("重型强固模具")
            < order.index("武器经验") < order.index("协议棱柱组") < order.index("三相纳米片") < order.index("高级认知载体"),
            str(order[:8]))

    print("\n[未来的干员：--rarity 5 时未实装的噗切娜是「下一位」；她的用量来自客户端预览表]")
    # 2026-10-15: the first standard is the newest released one, the announced one the second
    # (build.pick_standards). This fixture holds no numbers for the released five-star, so her
    # build is pinned by name (--char), which takes the same path as the second standard.
    _, ranked5 = bnt.newest(fives)
    check("五星：已上线最新的那位在前，未实装的噗切娜是下一位", [(w, r) for w, r, _l, _c in bnt.pick_standards(ranked5, TODAY, "5")],
          [(next(e["name"] for e in ranked5 if e["onlineDate"] <= TODAY), "current"), ("噗切娜", "next")])
    t5 = bnt.build(src, "fixture", TODAY, char_name="噗切娜", rarity="5")
    g5, rows5 = rows_by_name(t5)
    s5 = g5["standards"][0]
    check("选中未实装的她", (s5["name"], s5["releasedAt"], s5["status"], s5["dotType"], s5["charId"], s5["wikiItemId"]),
          ("噗切娜", "2026-09-24", "未实装", "label_type_preview", "", "2117"))
    check("指定的只建这一个标准", ([s["role"] for s in g5["standards"]], s5["chosenBy"], g5["coverage"]["next"]), (["named"], "--char", None))
    check("用量来源 = 预览表，并记下内部代号", (s5["sources"]["need"], s5["sources"]["foresightCharId"]), (bnt.SRC_FORESIGHT, "chr_0038_purrche"))
    check("等级表来自专武应答（她自己还没有）", s5["sources"]["levels"], f"{bnt.SRC_CALC}（等级表取自 寒夜幽影 的应答，各角色相同）")
    check("专武待定，理由说清", (s5["weapon"]["status"], s5["weapon"]["name"]), ("待定", ""))
    require("待定理由提到计算器未收录", "计算器还没收录" in s5["weapon"]["reason"], s5["weapon"]["reason"])
    for name, want in PURRCHENA.items():
        check(f"噗切娜 {name}", (rows5[name]["need"], rows5[name]["group"]), (want, "干员养成"))  # no rules yet: per-owner section, named by use
    check("含天赋的两行有说明", (rows5["协议棱柱"]["note"], rows5["协议棱柱组"]["note"]), ("预览表的数含天赋树", "预览表的数含天赋树"))
    check("caliber 写专武待定", g5["caliber"], "指定干员 噗切娜（2026-09-24 上线）：1→90 全突破、四技能 12、专武待定 1→90；不含天赋")
    require("footnote 提醒预览表含天赋", g5["footnote"].endswith("（上线前按客户端预览表，棱柱和折金票含天赋树）"), g5["footnote"])
    check("她不用的写明", (rows5["快子遴捡晶格"]["need"], rows5["快子遴捡晶格"]["note"]), (0, "噗切娜 的满练不用它"))
    check("coverage 标出她未实装", (g5["coverage"]["status"], g5["coverage"]["weaponStatus"], g5["coverage"]["candidates"][0]),
          ("未实装", "待定", "噗切娜 2026-09-24（未实装）"))

    print("\n[10-14：两个未实装六星、预览表里四个六星条目，照样认出明河]")
    FIX14 = fx_dir(HERE, "fixtures") / "skland-endfield-1014"
    src14 = bnt.RulesSource(FIX14, None)
    ops14 = bnt.wiki_entries(src14, "干员", "6")
    top14, ranked14 = bnt.newest(ops14)
    check("最新六星是未实装的明河，武器类型取自百科标签", (top14["name"], top14["onlineDate"], top14.get("weaponType")),
          ("明河", "2026-11-05", "单手剑"))
    check("其次是祀", (ranked14[1]["name"], ranked14[1]["onlineDate"], ranked14[1].get("weaponType")), ("祀", "2026-10-15", "双手剑"))
    try:
        t14 = bnt.make(src14, char_name="明河")   # the fixture has no numbers for the then-current 提弗洛斯
        why14 = ""
    except Exception as exc:  # noqa: BLE001
        t14, why14 = None, f"{type(exc).__name__}: {exc}"
    check("建得出来（旧代码在这里放弃：cannot pick hers）", why14, "")
    if t14 is not None:
        g14, rows14 = rows_by_name(t14)
        s14 = g14["standards"][0]
        check("她、未实装、预览表里的条目", (s14["name"], s14["status"], s14["sources"]["need"], s14["sources"]["foresightCharId"]),
              ("明河", "未实装", bnt.SRC_FORESIGHT, "chr_0037_minghe"))
        check("专武按百科标签的单手剑找到唤月（数还没有，待定）", (s14["weapon"]["name"], s14["weapon"]["kind"], s14["weapon"]["status"]),
              ("唤月", "单手剑", "待定"))
        check("built 是拉取时刻，固定写法", t14["built"], "2026-10-14 03:36 UTC+8")
        check("预览表的数", {n: rows14[n]["need"] for n in ("协议棱柱组", "协议棱柱", "象限拟合液", "三相纳米片", "红矛叶")},
              {"协议棱柱组": 562, "协议棱柱": 461, "象限拟合液": 116, "三相纳米片": 20, "红矛叶": 84})
    fs14 = src14.get_url("client-foresight", "", None)
    mat14 = bnt.material_table(src14.get("material-list", "", ""))
    calc14 = {c["id"] for c in src14.get("search-chars", "", "")["chars"]}
    check("计算器已收录的条目（md5 代号）排除掉，剩两个", sorted(e["charId"] for e in fs14.values() if str(e["rarity"]) == "6"
          and __import__("hashlib").md5(e["charId"].encode()).hexdigest() not in calc14), ["chr_0036_jsspsi", "chr_0037_minghe"])
    pick = getattr(bnt, "foresight_entry", None)
    check("有按淘汰和武器类型挑预览表条目的函数", pick is not None, True)
    if pick is not None:
        check("剩下的按武器类型分开", (pick(fs14, "6", calc14, "单手剑", "明河")["charId"],
              pick(fs14, "6", calc14, "双手剑", "祀")["charId"]), ("chr_0037_minghe", "chr_0036_jsspsi"))
        try:
            pick(fs14, "6", calc14, "", "某人")
            gave_up = False
        except RuntimeError:
            gave_up = True
        check("不知道武器类型时两个都像：不猜", gave_up, True)
    naming = getattr(bnt, "foresight_names", None)
    names14 = naming(fs14["chr_0037_minghe"], src14.get_url("client-item-names", "", None), mat14) if naming else {}
    check("预览表的新材料按计算器 id（md5）取名，MaaEnd 还没有它", names14.get("item_char_skill_specialize_6"), "跃迁浆体涂片")

    print("\n[10-15：祀上线当天 —— 当前 = 已上线最新的祀，下一位 = 已公布的明河；专武附基质建议]")
    FIX15 = fx_dir(HERE, "fixtures") / "skland-endfield-1015"
    src15 = bnt.RulesSource(FIX15, None)
    t15 = bnt.make(src15)
    g15, rows15 = rows_by_name(t15)
    cur, nxt = (g15["standards"] + [None, None])[:2]
    check("两个标准：祀（当前）、明河（下一位）",
          [(x["name"], x["role"], x["label"], x["status"], x["releasedAt"]) for x in g15["standards"]],
          [("祀", "current", "最新六星", "已实装", "2026-10-15"), ("明河", "next", "下一位六星", "未实装", "2026-11-05")])
    check("祀的专武是玉中身，祀和玉中身都已进计算器", (cur["weapon"]["name"], cur["sources"]["need"], cur["sources"]["weapon"]),
          ("玉中身", bnt.SRC_CALC, bnt.SRC_CALC))
    check("明河：预览表的条目、专武唤月待定", (nxt["sources"]["need"], nxt["sources"]["foresightCharId"], nxt["weapon"]["name"], nxt["weapon"]["status"]),
          (bnt.SRC_FORESIGHT, "chr_0037_minghe", "唤月", "待定"))
    check("默认标准 = 祀（旧 App 落到她）", g15["standard"], cur["charId"])
    require("游戏层的 rows / caliber / footnote / groups / useSource 都镜像祀",
            g15["rows"] is cur["rows"] and (g15["caliber"], g15["footnote"], g15["groups"], g15["useSource"])
            == (cur["caliber"], cur["footnote"], cur["groups"], cur["useSource"]))
    check("caliber 说的是祀", g15["caliber"], "最新六星 祀（2026-10-15 上线）：1→90 全突破、四技能 12、专武 玉中身 1→90；不含天赋")
    check("明河的 caliber 叫下一位", nxt["caliber"], "下一位六星 明河（2026-11-05 上线）：1→90 全突破、四技能 12、专武 唤月 1→90；不含天赋")
    check("每个标准带自己的节顺序：明河没有计算器分步，按人分节、节名按用途",
          (cur["groups"][:2], nxt["groups"], bool(cur["useSource"]), nxt["useSource"]),
          (["干员精英化", "干员技能升级"], ["干员养成", "武器养成", "多处共用"], True, ""))
    check("coverage 指当前、并写出下一位", (g15["coverage"]["operator"], g15["coverage"]["weapon"], g15["coverage"]["next"], g15["coverage"]["nextError"]),
          ("祀", "玉中身", {"name": "明河", "releasedAt": "2026-11-05", "status": "未实装", "weapon": "唤月"}, ""))


    def app_default(game):
        """ark-remote Inventory.swift standardFor() with nothing picked on the phone: the file's
    `standard`, matched by charId else wikiItemId, else the first standard."""
        key = lambda x: x.get("charId") or x.get("wikiItemId") or None  # noqa: E731
        return next((x for x in game["standards"] if key(x) == game["standard"]), game["standards"][0])


    check("App 不选时用的就是祀", app_default(g15)["name"], "祀")

    ess = cur["weapon"]["essence"]
    check("玉中身：三个词条（基础 / 附加 / 技能），用 MaaEnd 的 id 和名字",
          [(x["slot"], x["id"], x["name"]) for x in ess["terms"]],
          [("基础属性", "s1_5", "智识提升"), ("附加属性", "s2_1", "寒冷伤害提升"), ("技能属性", "s3_7", "效益")])
    check("玉中身：MaaEnd 武器代号", ess["code"], "wpn_claym_0018")
    # CEP, read 2026-10-15: weapons.ts 玉中身 = gat_passive_attr_wisd / gat_passive_attr_icedam / gst_passive_keyword;
    # dungeons.ts points whose s2Pool and s3Pool hold the last two (names after the 「·」).
    CEP_POINTS = {"玉中身": ["枢纽区", "源石研究园", "矿脉源区", "藏剑谷", "应龙关"],
                  "唤月": ["源石研究园", "供能高地", "首墩", "应龙关"]}
    check("玉中身：能同时出三条的地方 = CEP 算出来的五处", [x["name"] for x in ess["points"]], CEP_POINTS["玉中身"])
    check("全名是游戏里的能量淤积点名", ess["points"][0]["full"], "重度能量淤积点·枢纽区")
    check("MaaEnd 的目标选择能勾玉中身", ess["inMaaEndTarget"], True)
    require("MaaEnd 那句：目标选择、只勾它、自己挑地方和预刻写",
            all(w in ess["maaend"] for w in ("「目标选择」", "只勾玉中身", "自己挑地方", "预刻写")), ess["maaend"])
    check("预刻写那句", ess["engrave"], "预刻写：基础属性选 3 项（含智识提升），附加 / 技能属性固定寒冷伤害提升或效益")
    check("数据版本和来源", (ess["dataVersion"], ess["reason"], "保存的应答" in ess["source"]), ("2026-10-08 08:40:17 UTC", "", True))
    ess2 = nxt["weapon"]["essence"]
    check("唤月：意志提升 / 攻击提升 / 附术，四处 = CEP", ([x["name"] for x in ess2["terms"]], [x["name"] for x in ess2["points"]]),
          (["意志提升", "攻击提升", "附术"], CEP_POINTS["唤月"]))

    print("\n[基质词条：按 MaaEnd 自己的匹配法，名字用基质上的叫法]")
    pools15 = src15.get_maaend(bnt.ESSENCE_POOLS)
    names15 = src15.get_maaend(bnt.ESSENCE_NAMES)
    check("武器栏写「源石技艺强度提升」，基质上叫「源石技艺提升」（古渠）",
          [x["name"] for x in bnt.essence_terms(["力量提升·中", "源石技艺强度提升·中", "残暴·千秋旧土"], pools15, names15)],
          ["力量提升", "源石技艺提升", "残暴"])
    check("武器栏写「法术提升」，基质上叫「法术伤害提升」（全自动骇新星）",
          [x["id"] + x["name"] for x in bnt.essence_terms(["智识提升·小", "法术提升·小", "昂扬·远途起始"], pools15, names15)],
          ["s1_5智识提升", "s2_5法术伤害提升", "s3_8昂扬"])
    check("终结技充能效率：取最长的那个池名", bnt.essence_terms(["敏捷提升·大", "终结技充能效率提升·大", "迸发·x"], pools15, names15)[1]["id"], "s2_11")
    check("对不上就是 None，不猜", bnt.essence_terms(["智识提升·大", "不存在的词条·大", "效益·x"], pools15, names15), None)

    print("\n[基质建议缺了不拖垮整张表]")
    ess_old = rows_by_name(bnt.make(bnt.RulesSource(FIX, None)))[0]["standards"][0]["weapon"]["essence"]
    check("旧夹具没有 MaaEnd 的基质文件：表照样建，建议写明缺什么", (ess_old["terms"], ess_old["points"], ess_old["weapon"]),
          (None, None, "寒夜幽影"))
    require("缺的原因写出来", ess_old["reason"].startswith("读不到 MaaEnd 的基质数据"), ess_old["reason"])
    check("MaaEnd 里没有的武器：写明没有，不猜", bnt.essence_advice(src15, "不存在的武器")["reason"],
          "MaaEnd 的基质数据（数据版本 2026-10-08 08:40:17 UTC）里还没有不存在的武器")


    class NoForesight(bnt.RulesSource):
        """The 1015 fixture with the client preview table gone: 明河's numbers cannot be read."""

        def get_url(self, name, url, trim=None, loads=json.loads):
            if name == "client-foresight":
                raise RuntimeError("preview table unreachable")
            return super().get_url(name, url, trim, loads)


    t15b = bnt.make(NoForesight(FIX15, None))
    g15b = t15b["games"][0]
    check("下一位建不成：表照样出，只有祀，原因写进 coverage.nextError",
          ([x["name"] for x in g15b["standards"]], g15b["coverage"]["next"], g15b["coverage"]["nextError"]),
          (["祀"], None, "明河：RuntimeError: preview table unreachable"))
    require("summary 提到下一位没建成", "下一位没建成" in bnt.summary(t15b), bnt.summary(t15b))
    require("summary 两个都说到", all(w in bnt.summary(t15) for w in ("祀", "玉中身", "下一位 明河", "智识提升/寒冷伤害提升/效益")), bnt.summary(t15))

    print("\n[MaaEnd 的文件：游戏机上装着的那份优先（不联网），带注释也读得懂]")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        inst = Path(tmp) / "maaend"
        (inst / "data" / "EssenceFilter").mkdir(parents=True)
        (inst / "data" / "EssenceFilter" / "matcher_config.json").write_text(
            '{\n  // installed copy\n  "data_version": "installed-1",\n}\n', encoding="utf-8")
        live = bnt.RulesSource.__new__(bnt.RulesSource)   # no Skland login: this read must not touch the network
        live.offline, live.save, live.maaend_dir, live._memo, live.maaend_from = None, None, inst, {}, {}

        def no_net(*_a, **_k):
            raise AssertionError("went to the network although the installed file is there")
        live.get_url = no_net
        check("装着的 matcher_config 读到了", live.get_maaend(bnt.ESSENCE_MATCHER, bnt.trim_essence_matcher), {"data_version": "installed-1"})
        check("来源记作游戏机上装着的 MaaEnd", live.maaend_from, {"maaend-essence-matcher": "游戏机上装着的 MaaEnd"})

    print("\n[三个坑]")
    lv = src.get("rules-char-9de117d5969945ecfdbd70dac3a632e6", "", "")
    check("90 级那行是 -1 哨兵，不能当成本", lv["charLevelRules"][-1], {"level": 90, "gold": "-1", "exp": "-1"})
    check("哨兵被跳过", bnt.level_totals(lv["charLevelRules"]), (385_420, 1_792_290))
    check("武器表尾是 0", bnt.level_totals(lv["weaponLevelRules"]), (341_390, 2_524_080))
    mt = bnt.material_table({"charExpMaterials": {}, "weaponExpMaterials": {},
                             "materials": {"x": {"name": "D96钢样品四\n", "rarity": {"value": "5"}, "icon": "", "exp": "0"}}})
    check("名字尾巴的换行被去掉", mt["x"]["name"], "D96钢样品四")

    print("\n[自选箱：只补不够一人份的高阶素材，最缺的先补（用户 2026-09-23 09:05）]")
    # Until 2026-11-17 this part also read the committed web/data/need.json (the published copy had
    # to equal the offline rebuild) and ran web/inventory.js applyBox in JavaScriptCore; the phone
    # page (web/) was removed that day, so the box is checked on the offline rebuild alone.
    box = g["box"]
    check("箱子 = material-list 的 SELFSELECT 项", (box["id"], box["name"], box["per"]), ("e55ebf79deddbe781f2a33fb65fd7c61", "高阶培养自选箱Ⅰ", 2))
    check("可选 = priorities RARE 五种", box["pickNames"], ["超距辉映管", "D96钢样品四", "快子遴捡晶格", "象限拟合液", "三相纳米片"])
    check("箱子那行仍不算人份", rows["高阶培养自选箱Ⅰ"]["need"], None)

    print()
    if fails:
        print(f"✗ {len(fails)} failed: {fails}")
        sys.exit(1)
    print(f"all checks passed ({len(TYPHOEUS)} of 提弗洛斯's numbers, {len(WEAPON)} of 寒夜幽影's, {len(PURRCHENA)} of 噗切娜's from the preview table)")


if __name__ == "__main__":
    sys.exit(run_parts([_part_banners, _part_banner_post_miss, _part_bili_pinned_post, _part_event_expiry, _part_skland_api, _part_skland_http_error_body, _part_skland_role, _part_skland_sign, _part_skland_sync_guard, _part_skland_arknights_annihilation, _part_needtable_publish, _part_needtable_trims, _part_need_table]))
