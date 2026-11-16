"""Boot self-check, machinecheck probes, and offline collector replay."""
from __future__ import annotations

# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


def _part_mc_phone_banners():  # noqa: C901
    """Machine checks of the phone channel, the phone orders and the banner section.

The user, 2026-10-06 04:59: the machine has to confirm by itself, after a deploy,
what nobody had confirmed on it (ark_relay/features/machinechecks.py).
Each check here gets a realistic input - recorded fixtures, the real code path
that produces the evidence (the trace, the receipts, the queue file, the
relay's own WARNING lines through errwatch) - that PASSes, and a broken one that
FAILs and is pushed to the group. The wiring is driven through the real call
sites: banners.save_trace, boot_stages publish_state / run_phone_cmd / drain.
No network, no thread left running.

    Formerly test_mc_phone_banners.py.
    """
    import functools
    import json
    import logging
    import os
    import time
    import types
    import urllib.error
    import urllib.parse
    import urllib.request
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
                  "win32com", "win32com.client"):
        sys.modules.setdefault(_name, _Stub(_name))


    os.environ.update(ARK_STATE_DIR=str(tmpdir()), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

    import boot_stages
    from ark_relay.features import phone as phone_channel
    import ark_relay.features.banners as _b
    import ark_relay.features.commands as C
    from ark_relay.features import redbutton  # estop() reads its stop steps here
    import ark_relay.core.desktop as _desktop_mod
    from ark_relay.features import errwatch as alertlog, errwatch
    from ark_relay.features import machinecheck as mc
    from ark_relay.features import maintenance
    from ark_relay.features import modes
    from ark_relay.features import phone, resources
    from ark_relay.core import plan, skland, texts
    from ark_relay.features import queues
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.desktop import Line
    from ark_relay.features import phone as phone_heartbeat

    FX = fx_dir(Path(__file__), "fixtures")
    PASS, FAIL = mc.PASS, mc.FAIL


    class N:
        """The relay's notifier as judge sees it."""

        def __init__(self):
            self.sent = []

        def send(self, title, body="", alert=False, **kw):
            self.sent.append((title, body, alert))
            return []

        def failed(self, cid):
            return [(t, b, a) for t, b, a in self.sent if t.startswith(f"{texts.MACHINECHECK_FAIL}：{cid} ")]


    class Group:
        """errwatch's side of the notifier: the group robot, with the copy of every
    delivered group alarm (notify.Notifier._copy_alarm -> alertlog)."""
        channels = ["企业微信机器人"]

        def __init__(self, d):
            self.d, self.sent = d, []

        def send_group(self, title, body):
            self.sent.append((title, body))
            alertlog.AlertLog(self.d).copy(title, body)
            return []

        def send(self, title, body="", alert=False, **kw):
            return self.send_group(title, body)


    class Watch:
        """errwatch on the "ark" logger for one state dir: the day's error kinds, its
    queue and the alarm copy come out exactly as on the machine."""

        def __init__(self, d):
            self.group = Group(d)
            self.h = errwatch.ErrorKindAlert(self.group, lambda: False, d, known={}, pace=0, retry=(0.05,))
            logging.getLogger(errwatch.ARK).addHandler(self.h)

        def settle(self):
            t0 = time.monotonic()
            while self.h.pending() and time.monotonic() - t0 < 5:
                time.sleep(0.02)
            time.sleep(0.05)

        def close(self):
            self.settle()
            logging.getLogger(errwatch.ARK).removeHandler(self.h)
            self.h.close()


    def judged(d, event, ctx, n=None):
        """{id: Result} of the checks that judged."""
        return dict(mc.judge(d, event, ctx, notifier=n if n is not None else N()))


    def status(v, cid):
        r = v.get(cid)
        return r.status if r else None


    def ev(v, cid):
        r = v.get(cid)
        return r.evidence if r else ""


    mc.load()
    MINE = ("#2", "#3", "#8", "#9", "#10", "#15", "#16", "#23", "#39", "#40", "#41", "#45", "#50", "#56", "#58")

    print("[登记：十五项，写的是人话]")
    check("十五项都登记了", [c for c in MINE if c in mc.CHECKS], list(MINE))
    check("每项写的是人话", {c: texts.plain(mc.CHECKS[c].what) for c in MINE if c in mc.CHECKS},
          {c: [] for c in MINE if c in mc.CHECKS})
    check("卡池五项听卡池那一段", {c: mc.CHECKS[c].triggers for c in ("#2", "#3", "#8", "#9", "#58") if c in mc.CHECKS},
          {c: ("banners",) for c in ("#2", "#3", "#8", "#9", "#58") if c in mc.CHECKS})

    saved_pause = _b._pause
    _b._pause = lambda s: None

    # ------------------------------------------------------------------ #2
    print("\n[#2 鸣潮版本活动日历图：读出日期过，读图没结果不过（10-02 那次是「RecognizeAsync 参数错误」）]")
    CAL = "https://aki-gm-resources-back.aki-game.com/notice/image/fYrvOmEkgCfEKFTy.png"
    notice = {"activity": [{"id": "50868", "tabTitle": "3.7版本活动日历", "startTimeMs": "1790712000000",
                            "content": f'<p><img src="{CAL}" alt="" width="1080" height="2159"></p>'}]}
    cal_lines = [Line(**o) for o in json.loads((FX / "ww-3.7-calendar-ocr.json").read_text(encoding="utf-8"))]
    now = datetime(2026, 10, 6, 21, 40)
    end = datetime(2026, 10, 22, 9, 59, 59)
    d = tmpdir()
    tr = _b.Trace.new()
    _b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, lambda u: cal_lines if u == CAL else None, {}, tr)
    n = N()
    _b.save_trace(d, now, "🎴 卡池", tr, n)          # the real call site
    row = mc.read(d).get("#2") or {}
    check("经 save_trace 判了：过", row.get("status"), PASS)
    check("依据是图上读出的日期和图址", ("2026-10-22 开" in str(row.get("evidence")), CAL in str(row.get("evidence"))),
          (True, True))
    check("过了不推", n.sent, [])

    d = tmpdir()
    w = Watch(d)
    _desktop_mod.log.warning(
        "桌面助手读图失败：ERR 使用“1”个参数调用“RecognizeAsync”时发生异常:“参数错误。”")
    w.settle()
    tr = _b.Trace.new()
    _b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, lambda u: None, {}, tr)
    n = N()
    v = judged(d, "banners", {"trace": tr, "text": "", "now": now}, n)
    w.close()
    check("读图没结果：没过", status(v, "#2"), FAIL)
    check("依据说读图没结果，带桌面读屏自己的原话", ("读图没有结果" in ev(v, "#2"), "参数错误" in ev(v, "#2")), (True, True))
    check("没过推群", [a for _t, _b2, a in n.failed("#2")], [True])

    # Another source gave the time (cross-check, notes=None): failing to read is not a
    # fault; the trace writes 「另一来源已给出」 and check #2 keys on that.
    d = tmpdir()
    tr = _b.Trace.new()
    _b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, lambda u: None, None, tr)
    n = N()
    v = judged(d, "banners", {"trace": tr, "text": "", "now": now}, n)
    check("跨检读不出（另一来源已给）：#2 判过", status(v, "#2"), PASS)
    check("……不推群", [a for _t, _b2, a in n.failed("#2")], [])
    check("依据是「另一来源已给出」", "另一来源已给出" in str(ev(v, "#2")), True)

    # ------------------------------------------------------------------ #3 and #58
    print("\n[#3 哔哩哔哩那份：库街区没有这一帖时读出时间过，被风控挡住不过；#58 库街区没有那一帖不单独报错]")
    fx = json.loads((FX / "ww-bili-feed-2026-10-05.json").read_text(encoding="utf-8"))
    pages = [p["response"] for p in fx["pages"]]
    empty, nav = fx["empty"]["response"], fx["nav"]["response"]
    by_offset = {"": pages[0], pages[0]["data"]["offset"]: pages[1], pages[1]["data"]["offset"]: pages[2]}
    IMG3 = "https://i0.hdslb.com/bfs/new_dyn/e1826ff7fe229d2f29d8a715a4ee4eee1955897084.jpg"
    win = [Line(**o) for o in json.loads((FX / "ww-3.7-news-4-winocr.json").read_text(encoding="utf-8"))]


    def bili(feed):
        def get(url, cookie):
            if "finger/spi" in url:
                return {"code": 0, "data": {"b_3": "B3", "b_4": "B4=="}}
            if "/nav" in url:
                return nav
            import urllib.parse
            return feed(dict(urllib.parse.parse_qsl(url.split("?", 1)[1], keep_blank_values=True))["offset"])
        return get


    def no_kuro_post(path, payload):
        return {"data": {"list": []}}          # the list reads fine, the post is not in it


    feb = datetime(2026, 10, 5, 12, 0)
    d = tmpdir()
    tr = _b.Trace.new()
    got = _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", feb, lambda u: win if u == IMG3 else [], tr,
                               no_kuro_post, bili(lambda off: by_offset[off]))
    check("真实三页里找到那一帖、读出时间", got, (datetime(2026, 10, 22, 10, 0), datetime(2026, 11, 11, 11, 59)))
    n = N()
    v = judged(d, "banners", {"trace": tr, "text": "", "now": feb}, n)
    check("#3 过", status(v, "#3"), PASS)
    check("#3 依据：两扇门各自的结果", ("库街区：没有这一帖" in ev(v, "#3"), "哔哩哔哩：给出了「余心所向九死未悔」" in ev(v, "#3")),
          (True, True))
    check("#58 过：库街区没有这一帖只记日志", (status(v, "#58"), "只记了日志" in ev(v, "#58")), (PASS, True))
    check("过了不推", n.sent, [])

    d = tmpdir()
    tr = _b.Trace.new()
    _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", feb, lambda u: [], tr, no_kuro_post, bili(lambda off: empty))
    n = N()
    v = judged(d, "banners", {"trace": tr, "text": "", "now": feb}, n)
    check("#3 一直空（风控）：没过", status(v, "#3"), FAIL)
    check("#3 依据带原始形状", ("BiliFeedProblem" in ev(v, "#3"), "<0 items>" in ev(v, "#3")), (True, True))
    check("#3 没过推群", len(n.failed("#3")), 1)

    events = json.loads((FX / "ww-news-events.json").read_text(encoding="utf-8"))["data"]["list"]
    post = json.loads((FX / "ww-3.7-news-post.json").read_text(encoding="utf-8"))
    lines3 = [Line(**o) for o in json.loads((FX / "ww-3.7-news-3-ocr.json").read_text(encoding="utf-8"))]
    KURO3 = "https://prod-alicdn-community.kurobbs.com/forum/539302b44e6e4c118735142822df9fe120260921.jpg"
    d = tmpdir()
    tr = _b.Trace.new()
    _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", datetime(2026, 10, 1, 2, 30),
                         lambda u: lines3 if u == KURO3 else [], tr,
                         lambda p, payload: {"data": {"list": events}} if "findEventList" in p else post,
                         bili(lambda off: by_offset[off]))
    v = judged(d, "banners", {"trace": tr, "text": "", "now": feb})
    check("库街区给出了：#3 不用判，#58 过（库街区找到了这一帖）",
          (status(v, "#3"), status(v, "#58"), "找到了这一帖" in ev(v, "#58")), (None, PASS, True))

    d = tmpdir()
    w = Watch(d)
    tr = _b.Trace.new()
    _b.log.warning("库街区官方资讯里没找到 3.7 版本资讯帖")     # the 10-05 21:47 line
    _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", feb, lambda u: win if u == IMG3 else [], tr,
                         no_kuro_post, bili(lambda off: by_offset[off]))
    w.settle()
    n = N()
    v = judged(d, "banners", {"trace": tr, "text": "", "now": feb}, n)
    w.close()
    check("#58 那句又成了报错（旧代码）：没过", (status(v, "#58"), "旧报错又出现了" in ev(v, "#58")), (FAIL, True))
    check("#58 没过推群", len(n.failed("#58")), 1)

    # ------------------------------------------------------------------ #3 before the post, #66 #67 #68
    print("\n[#3 两边都还没发这一帖不算没过；#66 核对有对不上的不过；#67 官方在开的新池日报当期得写上；#68 预告过的池开了不许变成没有]")
    NEW3 = ("#66", "#67", "#68")
    check("新三项听卡池那一段", {c: mc.CHECKS[c].triggers for c in NEW3 if c in mc.CHECKS}, {c: ("banners",) for c in NEW3})
    check("新三项写的是人话", {c: texts.plain(mc.CHECKS[c].what) for c in NEW3 if c in mc.CHECKS}, {c: [] for c in NEW3})


    def doors(kuro, bili):
        tr = _b.Trace.new()
        tr.src("鸣潮", "版本资讯门", "库街区", kuro)
        tr.src("鸣潮", "版本资讯门", "B 站", bili)
        return tr


    v = judged(tmpdir(), "banners", {"trace": doors("没有这一帖", "没有这一帖"), "text": "", "now": feb})
    check("#3 库街区和哔哩哔哩都还没这一帖：过（11-08 前每晚误报）", (status(v, "#3"), "官方还没发这一帖" in ev(v, "#3")), (PASS, True))
    v = judged(tmpdir(), "banners", {"trace": doors("取不到：OSError: x", "没有这一帖"), "text": "", "now": feb})
    check("#3 库街区那边取不到、哔哩哔哩读了没有：过", status(v, "#3"), PASS)
    v = judged(tmpdir(), "banners", {"trace": doors("长图里没读到「余心所向九死未悔」", "没有这一帖"), "text": "", "now": feb})
    check("#3 库街区有帖、哔哩哔哩没有：照旧不过", status(v, "#3"), FAIL)

    ok_checks = ["鸣潮：库街区=游戏公告 ✓",
                 "终末地：森空岛里没有在开的「烟火邀星河」，新版本导览写着 11-05 12:00 开、11-26 06:00 结束，已按官方补进当期 ✓"]
    tr = _b.Trace.new()
    tr.checks += ok_checks
    v = judged(tmpdir(), "banners", {"trace": tr, "text": "", "now": feb})
    check("#66 都对得上（含官方补上的）：过，依据说补了哪条", (status(v, "#66"), "官方来源补上的" in ev(v, "#66")), (PASS, True))
    tr.checks.append("终末地：公告取不到，只有森空岛一个来源 ✗")
    n = N()
    v = judged(tmpdir(), "banners", {"trace": tr, "text": "", "now": feb}, n)
    check("#66 有对不上的：不过，推群，依据是那一条", (status(v, "#66"), "只有森空岛一个来源" in ev(v, "#66"), len(n.failed("#66"))),
          (FAIL, True, 1))
    check("#66 没有核对：不判", status(judged(tmpdir(), "banners", {"trace": _b.Trace.new(), "text": "", "now": feb}), "#66"), None)

    SECTION = ("🎴 卡池（时间为北京时间）\n明日方舟\n· 当期无新角色卡池\n· 下期：官方未公告\n鸣潮\n· 当期无新角色卡池\n"
               "· 下期：官方未公告\n终末地\n{ef}\n· 下期：官方未公告")
    tr = _b.Trace.new()
    tr.opened("终末地", "烟火邀星河", "明河", datetime(2026, 11, 5, 12), datetime(2026, 11, 26, 6), "新版本导览")
    shown = SECTION.format(ef="· 当期：烟火邀星河 · 明河 · 北京 11-26 06:00 结束 · 剩 18 天 6 小时")
    v = judged(tmpdir(), "banners", {"trace": tr, "text": shown, "now": feb})
    check("#67 官方在开的写上了：过", (status(v, "#67"), "终末地「烟火邀星河」" in ev(v, "#67")), (PASS, True))
    d = tmpdir()
    n = N()
    _b.save_trace(d, datetime(2026, 11, 7, 23, 28), SECTION.format(ef="· 当期无新角色卡池"), tr, n)     # the real call site
    row = mc.read(d).get("#67") or {}
    check("#67 11-05 到 11-08 那样（官方在开、日报写没有）：不过，推群",
          (row.get("status"), "烟火邀星河" in str(row.get("evidence")), "当期无新角色卡池" in str(row.get("evidence")),
           len(n.failed("#67"))), (FAIL, True, True, 1))
    v = judged(tmpdir(), "banners", {"trace": tr, "text": SECTION.format(ef="· 这次没读到（没有森空岛令牌），不是没有卡池"), "now": feb})
    check("#67 那一游戏按没读到报：不算漏（没读到自己会报）", (status(v, "#67"), "按没读到报" in ev(v, "#67")), (PASS, True))
    check("#67 官方没有在开的：不判", status(judged(tmpdir(), "banners", {"trace": _b.Trace.new(), "text": shown, "now": feb}), "#67"), None)

    tr = _b.Trace.new()
    tr.continuity = [["终末地", "lost", "2026-11-04.json 预告 11-05 12:00 开 明河「烟火邀星河」，今天各来源都没有，按没读到报"]]
    n = N()
    v = judged(tmpdir(), "banners", {"trace": tr, "text": "", "now": feb}, n)
    check("#68 预告过的池开了却哪儿都没有：不过，推群", (status(v, "#68"), "明河" in ev(v, "#68"), len(n.failed("#68"))), (FAIL, True, 1))
    tr.continuity = [["终末地", "recovered", "按预告补回"], ["鸣潮", "ok", "今天当期里有"]]
    v = judged(tmpdir(), "banners", {"trace": tr, "text": "", "now": feb})
    check("#68 补回的、本来就有的：过", (status(v, "#68"), "按预告补回" in ev(v, "#68")), (PASS, True))
    tr.continuity = None
    check("#68 没跑跨天核对：不判", status(judged(tmpdir(), "banners", {"trace": tr, "text": "", "now": feb}), "#68"), None)

    # ------------------------------------------------------------------ #8
    print("\n[#8 明日方舟下期「官方通讯」一行：该出就出，过期就撤，取不到不过]")
    page = (FX / "prts_limited_page.html").read_text(encoding="utf-8")


    # The official site's two endpoints (banners.ak_news_pages / ak_post_text): the
    # NEWS tab holds newsletter #69 (09-25 16:00 +8), the ACTIVITY tab nothing.
    NEWS = {"NEWS": [{"cid": "7366", "title": "《明日方舟》制作组通讯#69期", "displayTime": 1790326800}]}
    COMM = ("<p>●SideStory「昨日海」限时活动将于10月上旬开启，该活动除包含全新活动关卡与剧情外，"
            "新干员和新时装以及相关主题家具也将伴随本次活动登场及上架。</p>")


    def ak_site(url):
        if url.startswith("https://ak.hypergryph.com/api/news?"):
            cat = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["category"][0]
            return json.dumps({"code": 0, "data": {"list": NEWS.get(cat, []), "end": True}}, ensure_ascii=False)
        if url == _b._AK_POST.format(cid="7366"):
            return json.dumps({"code": 0, "data": {"data": COMM}}, ensure_ascii=False)
        return None


    def ak_section(now, *, news_ok=True, with_leads=True):
        """The Arknights block as report._compose_daily builds it, against recorded pages."""
        real_json, real_text = _b._json, _b._text

        def no_api(url, *a, **k):
            raise OSError("503 Backend fetch failed")

        def text(url, *a, **k):
            if url.startswith(_b._PRTS_PAGE):
                return page
            got = ak_site(url) if news_ok else None
            if got is not None:
                return got
            raise OSError("offline")
        _b._json, _b._text = no_api, text
        cache = dict(_b._rarity_cache)
        try:
            tr, leads = _b.Trace.new(), {}
            rows, nxt = _b._arknights(now, trace=tr, leads=leads)
            out = _b.render(rows, now, {"明日方舟": nxt} if nxt else {}, {}, tr, [], leads if with_leads else {})
        finally:
            _b._json, _b._text = real_json, real_text
            _b._rarity_cache.clear()
            _b._rarity_cache.update(cache)
        return tr, out


    oct6 = datetime(2026, 10, 6, 21, 40)
    d = tmpdir()
    tr, out = ak_section(oct6)
    n = N()
    _b.save_trace(d, oct6, out, tr, n)
    row = mc.read(d).get("#8") or {}
    check("通讯说 10 月上旬有新干员、日报写了：过", row.get("status"), PASS)
    check("依据是日报那一行", "昨日海 · 10 月上旬 · 官方通讯" in str(row.get("evidence")), True)
    d = tmpdir()
    tr, out = ak_section(oct6, with_leads=False)
    n = N()
    v = judged(d, "banners", {"trace": tr, "text": out, "now": oct6}, n)
    check("通讯给了、日报没写：没过", (status(v, "#8"), "官方未公告" in ev(v, "#8")), (FAIL, True))
    check("没过推群", len(n.failed("#8")), 1)
    d = tmpdir()
    tr, out = ak_section(datetime(2026, 10, 11, 21, 40))
    v = judged(d, "banners", {"trace": tr, "text": out, "now": datetime(2026, 10, 11, 21, 40)})
    check("上旬过了、日报撤了这一行：过", (status(v, "#8"), "上旬已过" in ev(v, "#8"), "官方通讯" in out), (PASS, True, False))
    d = tmpdir()
    tr, out = ak_section(oct6, news_ok=False)
    v = judged(d, "banners", {"trace": tr, "text": out, "now": oct6})
    check("官网取不到：没过，带原因", (status(v, "#8"), "OSError: offline" in ev(v, "#8")), (FAIL, True))

    # ------------------------------------------------------------------ #9
    print("\n[#9 「明天开新卡池」不带没有名字的（09-29 那条：终末地 09-30 11:59，没有名字）]")
    evening = datetime(2026, 9, 29, 21, 30)
    nxt = {"终末地": (datetime(2026, 9, 30, 11, 59, 59), ""), "鸣潮": (datetime(2026, 9, 30, 11, 0), "景燃「身赴三途」")}
    d = tmpdir()
    tr = _b.Trace.new()
    out = _b.render([], evening, nxt, {}, tr)
    v = judged(d, "banners", {"trace": tr, "text": out, "now": evening})
    check("没名字的没进群播报：过", status(v, "#9"), PASS)
    check("依据：哪一条没名字、群里播的是什么", ("终末地 09-30 11:59" in ev(v, "#9"), "🎴 明天开新卡池：鸣潮" in ev(v, "#9")),
          (True, True))
    real_opening = _b.opening_tomorrow


    def opening_before_0929(now, nxt):          # 30eb8b41's parent: dates only, no name filter
        day = (now + timedelta(days=1)).date()
        return sorted(((g, w, who) for g, (w, who) in nxt.items() if w is not None and w.date() == day),
                      key=lambda x: x[1])


    _b.opening_tomorrow = opening_before_0929
    try:
        n = N()
        v = judged(tmpdir(), "banners", {"trace": tr, "text": out, "now": evening}, n)
    finally:
        _b.opening_tomorrow = real_opening
    check("退回 09-29 前的写法：没过", (status(v, "#9"), "进了群播报" in ev(v, "#9")), (FAIL, True))
    check("没过推群", len(n.failed("#9")), 1)
    v = judged(tmpdir(), "banners", {"trace": _b.Trace.new(), "text": "", "now": evening})
    check("没有没名字的：不判", status(v, "#9"), None)

    # ------------------------------------------------------------------ #10
    print("\n[#10 森空岛会话交到手机，终末地体力那几项的名字认得出]")
    saved_sk = (skland.get_did, skland.login, skland.refresh, skland.bindings, skland.endfield_card)


    class Cred:
        cred, token = "c-secret", "t-secret"


    _REAL_SKLAND = (skland.get_did, skland.login, skland.refresh, skland.bindings)   # put back at the end (shared process in the coverage pass)
    skland.get_did, skland.login, skland.refresh = (lambda: "Bdev"), (lambda tok, did="": Cred()), (lambda c: c)
    skland.bindings = lambda c: [
        {"appCode": "endfield", "bindingList": [{"uid": "247481631", "roles": [{"roleId": "1234567890", "serverId": "1"}]}]},
        {"appCode": "arknights", "bindingList": [{"uid": "19237299"}]}]
    # The 09-15 03:45 card/detail sample quoted in web/stamina.js.
    DUNGEON = {"curStamina": "179", "maxTs": "1789490362", "maxStamina": "360"}
    asked = []
    skland.endfield_card = lambda cred, role="", server="": (asked.append((role, server)),
                                                             {"detail": {"dungeon": dict(DUNGEON)}})[1]
    try:
        resources._session["sk"] = None
        sk = resources.skland_session(types.SimpleNamespace(skland_token="tok"))
        check("体力是拿同一个会话、同一个角色读的", asked, [("1234567890", "1")])
        d = tmpdir()
        n = N()
        v = judged(d, "phone_state", {"state": {"密钥": {"sk": sk}}, "why": "开机"}, n)
        check("会话齐、体力三项在：过", status(v, "#10"), PASS)
        check("依据有体力读数", "curStamina=179 maxStamina=360 maxTs=1789490362" in ev(v, "#10"), True)
        check("依据里没有凭据", ("c-secret" in ev(v, "#10"), "t-secret" in ev(v, "#10")), (False, False))
        check("关机前那份不再判", status(judged(d, "phone_state", {"state": {"密钥": {"sk": sk}}, "why": "关机前"}), "#10"), None)
        skland.endfield_card = lambda cred, role="", server="": {"detail": {"dungeon": {"stamina": 179, "staminaMax": 360}}}
        resources._session["sk"] = None
        sk = resources.skland_session(types.SimpleNamespace(skland_token="tok"))
        n = N()
        v = judged(tmpdir(), "phone_state", {"state": {"密钥": {"sk": sk}}, "why": "开机"}, n)
        check("森空岛改了名字：没过，列出给的是什么", (status(v, "#10"), "staminaMax" in ev(v, "#10")), (FAIL, True))
        check("没过推群", len(n.failed("#10")), 1)
        v = judged(tmpdir(), "phone_state", {"state": {"密钥": {"sk": {"错误": "没配森空岛 token"}}}, "why": "开机"})
        check("会话没给出去：没过", (status(v, "#10"), "没配森空岛 token" in ev(v, "#10")), (FAIL, True))
    finally:
        skland.get_did, skland.login, skland.refresh, skland.bindings, skland.endfield_card = saved_sk
        resources._session["sk"] = None

    # ------------------------------------------------------------------ #15
    print("\n[#15 跳过队列的回执：成功写「调度程序已确认」，失败撤掉并给红回执]")
    saved_q = (plan.schedule, queues.apply)
    plan.schedule = lambda automas_dir: [{"name": "晚班", "times": ["21:30"]}]


    def engage(answer):
        d = tmpdir()
        queues.apply = lambda automas_dir, name, enabled=None, scripts=None: answer(name)
        today = datetime.now(tz=SERVER_TZ)
        modes.add_day_queue(d, today.strftime("%Y-%m-%d"), "晚班")
        modes.process_skip(d, tmpdir(), today)
        return d, {"relay": {"最近指令": modes.receipts(d), "今天跳过队列": modes.skipped_today_all(d)}}


    try:
        d, state = engage(lambda name: (True, f"队列「{name}」：定时关闭（调度程序已确认）"))
        n = N()
        v = judged(d, "phone_state", {"state": state, "why": "跳过队列"}, n)
        check("跳过生效，回执带「调度程序已确认」：过", status(v, "#15"), PASS)
        check("同一张回执下一份状态不再判", status(judged(d, "phone_state", {"state": state, "why": "手机请求"}), "#15"), None)
        d, state = engage(lambda name: (False, f"队列「{name}」定时关闭失败：调度程序报错（timed out）"))
        v = judged(d, "phone_state", {"state": state, "why": "跳过队列"})
        check("跳过没成：红回执、手机上不再显示跳过：过", (status(v, "#15"), "今天跳过的队列：无" in ev(v, "#15")), (PASS, True))
        broken = dict(state["relay"], 今天跳过队列=["晚班"])          # the pre-09-30 shape: the flag stayed
        n = N()
        v = judged(tmpdir(), "phone_state", {"state": {"relay": broken}, "why": "跳过队列"}, n)
        check("红回执但还挂着跳过：没过", status(v, "#15"), FAIL)
        check("没过推群", len(n.failed("#15")), 1)
        d, state = engage(lambda name: (True, f"队列「{name}」：定时关闭（备份 QueueConfig.bak-20261006-212000.json）"))
        v = judged(d, "phone_state", {"state": state, "why": "跳过队列"})
        check("成功却没有调度程序确认（改文件那条路）：没过", status(v, "#15"), FAIL)
    finally:
        plan.schedule, queues.apply = saved_q

    # ------------------------------------------------------------------ the phone orders (#16, #23)


    class Eng:
        def __init__(self, busy):
            self.busy = busy

        def scripts_running(self):
            return self.busy


    class Log:
        def __init__(self):
            self.lines = []

        def _rec(self, fmt, *a, **k):
            self.lines.append(fmt % a if a else fmt)

        info = warning = debug = _rec

        def exception(self, fmt, *a, **k):
            self.lines.append("EXC " + (fmt % a if a else fmt))


    class HB:
        def watch(self):
            pass


    def order(action, mid, sent=None, **kw):
        body = {"action": action, "confirmed": True, **kw}
        body["_meta"] = {"sent": int(time.time()) if sent is None else sent,
                         "ntfy_time": int(time.time()), "ntfy_id": mid, "via": "live"}
        return body


    def make(engine, d, n):
        return phone_channel._make_phone_cmd(engine, n, Log(), HB(), phone.StatePusher(lambda why: True), d)


    print("\n[#16 红按钮：游戏、脚本和调度程序里的任务都没了才回「已停一切」（经 run_phone_cmd）]")
    real_estop = C.estop
    saved_e = (redbutton._estop_stop_via_mas, redbutton._estop_kill, redbutton._estop_alive, redbutton._estop_live_tasks)


    def rig(alive_rounds, task_rounds):
        alive_rounds, task_rounds = list(alive_rounds), list(task_rounds)
        redbutton._estop_stop_via_mas = lambda: ["晚班"]
        redbutton._estop_kill = lambda: None
        redbutton._estop_alive = lambda: alive_rounds.pop(0) if alive_rounds else []
        redbutton._estop_live_tasks = lambda: task_rounds.pop(0) if task_rounds else []
        C.estop = functools.partial(real_estop, sleep=lambda s: None)


    try:
        rig([[]], [[]])
        d, n = tmpdir(), N()
        make(Eng(True), d, n)(order("estop", "e1"))
        row = mc.read(d).get("#16") or {}
        check("都没了才回已停一切：过", row.get("status"), PASS)
        check("依据是最后一轮看到的", "游戏和脚本 一个都没有" in str(row.get("evidence")), True)
        rig([["MaaEnd.exe"], ["MaaEnd.exe"]], [[], []])
        d, n = tmpdir(), N()
        make(Eng(True), d, n)(order("estop", "e2"))
        row = mc.read(d).get("#16") or {}
        check("没停干净就没说已停一切：过", (row.get("status"), "MaaEnd.exe" in str(row.get("evidence"))), (PASS, True))

        def estop_before_0930(sleep=None, state_dir=None):    # processes only, AUTO-MAS's task list not read
            C.ESTOP_LAST.clear()
            C.ESTOP_LAST.update(alive=[], live=[("7f3c", "终末地 · 日常")], rounds=1)
            return True, "已停一切：晚班；脚本和游戏都确认没了"
        C.estop = estop_before_0930
        d, n = tmpdir(), N()
        make(Eng(True), d, n)(order("estop", "e3"))
        check("调度程序里还有任务却回了已停一切：没过", (mc.read(d).get("#16") or {}).get("status"), FAIL)
        check("没过推群", len(n.failed("#16")), 1)
        rig([[]], [None, None])
        d, n = tmpdir(), N()
        make(Eng(True), d, n)(order("estop", "e4"))
        check("问不到调度程序：没过", "问不到" in str((mc.read(d).get("#16") or {}).get("evidence")), True)
    finally:
        C.estop = real_estop
        redbutton._estop_stop_via_mas, redbutton._estop_kill, redbutton._estop_alive, redbutton._estop_live_tasks = saved_e

    print("\n[#23 跑着时按的手机指令先进 phone-queue.json，跑完照样执行]")
    real_apply = C.apply_command
    C.apply_command = lambda body: (True, f"刷取关卡：{body.get('value')}")
    try:
        eng, d, n = Eng(True), tmpdir(), N()
        fn = make(eng, d, n)
        fn(order("set_config", "q1", value="1-7"))
        check("排上了，还没判", ("#23" in mc.read(d), len(phone.CmdQueue(d))), (False, 1))
        eng.busy = False
        fn.drain()
        row = mc.read(d).get("#23") or {}
        check("跑完执行了：过", row.get("status"), PASS)
        check("依据：排进文件、跑完执行、结果", ("phone-queue.json" in str(row.get("evidence")),
                                           "跑完后执行，改成了" in str(row.get("evidence"))), (True, True))
        eng, d, n = Eng(True), tmpdir(), N()
        fn = make(eng, d, n)
        fn(order("set_config", "q2", sent=int(time.time()) - phone.MAX_AGE - 60, value="TO-5"))
        eng.busy = False
        fn.drain()
        check("排到过期都没执行：没过", (mc.read(d).get("#23") or {}).get("status"), FAIL)
        check("没过推群", len(n.failed("#23")), 1)
        real_add = phone.CmdQueue.add
        phone.CmdQueue.add = lambda self, body, now=None: phone.QUEUED      # says queued, writes nothing
        try:
            eng, d, n = Eng(True), tmpdir(), N()
            make(eng, d, n)(order("set_config", "q3", value="1-7"))
        finally:
            phone.CmdQueue.add = real_add
        check("说排了却不在文件里：没过", (mc.read(d).get("#23") or {}).get("status"), FAIL)
    finally:
        C.apply_command = real_apply

    # ------------------------------------------------------------------ #39 through publish_state


    class FakeBox:
        """The mailbox as _start_phone_channel uses it; `ok` decides each publish."""
        ok = [True]

        def __init__(self, topic, pin, state_dir, cos=None):
            self.topic, self.cos, self.enabled = topic, cos, True
            self.quota = phone.Quota(state_dir)
            self.last_error, self.last_route = "", ""

        def publish(self, body):
            good = FakeBox.ok.pop(0) if FakeBox.ok else True
            self.last_route = "腾讯云" if good else ""
            self.last_error = "" if good else "腾讯云 COS 没存上（回 403），ntfy 也没发出去（ntfy 回 502（试了 2 次））"
            return good

        def report(self):
            return {"connected": True, "down_since": None, "drops": [], "backlog_missed": False,
                    "backlog_why": "", "backlog_late": None}

        def fetch(self):
            return []

        def listen(self, on_cmd, stop, **kw):
            return None


    class FakeHb:
        def __init__(self, *a, **k):
            pass

        def loop(self, stop):
            return None

        def cos_report(self):
            return {"cos": False}


    STATE = [{"at": 1}]       # what the faked state_payload hands out


    def channel(d, n, results, state=None):
        """_start_phone_channel with the fakes; the push_state it returns."""
        FakeBox.ok = list(results)
        STATE[0] = dict(state or {"at": 1})
        cfg = types.SimpleNamespace(phone_topic="topic-abc", phone_pin="8964", state_dir=d,
                                    cos_secret_id="", cos_secret_key="", cos_bucket="", cos_region="")
        return phone_channel._start_phone_channel(types.SimpleNamespace(stop_event=None), cfg,
                                                types.SimpleNamespace(scripts_running=lambda: False),
                                                n, boot_stages.log)


    saved_channel = (phone.Mailbox, phone.Heartbeat, phone.state_payload, boot_stages.ensure_automas)
    phone.Mailbox, phone.Heartbeat = FakeBox, FakeHb
    phone.state_payload = lambda cfg, state_dir: dict(STATE[0])
    boot_stages.ensure_automas = lambda *a, **k: True


    print("\n[#39 每一份状态都送到了手机（经 publish_state，关机前那份时判）]")
    d, n = tmpdir(), N()
    w = Watch(d)
    push = channel(d, n, [True, True, True])
    push("手机请求")
    check("开机、手机请求都不判 #39", "#39" in mc.read(d), False)
    saved_channel[0]._carried_by_ntfy("回 403")         # COS refused one, ntfy carried it: got over by itself
    w.settle()
    push("关机前")
    w.close()
    row = mc.read(d).get("#39") or {}
    check("三份都送到：过", row.get("status"), PASS)
    check("依据：次数、走哪条、自己好了的那条只进日报",
          ("上报状态 3 次，送到 3 次（腾讯云 3）" in str(row.get("evidence")), "只进了日报" in str(row.get("evidence"))),
          (True, True))
    push("关机前")                                      # the machine stayed on: the next shift starts afresh
    check("下一班重新数", "上报状态 1 次，送到 1 次" in str((mc.read(d).get("#39") or {}).get("evidence")), True)
    d, n = tmpdir(), N()
    w = Watch(d)
    push = channel(d, n, [True, False])
    push("关机前")
    w.close()
    row = mc.read(d).get("#39") or {}
    check("关机前那份没送到：没过", row.get("status"), FAIL)
    check("依据带原因", "ntfy 回 502" in str(row.get("evidence")), True)
    check("没过推群（走 notifier，带 alert）", [a for _t, _b2, a in n.failed("#39")], [True])
    d, n = tmpdir(), N()
    w = Watch(d)
    push = channel(d, n, [True, True])
    phone.log.warning("状态没能发到信箱：ntfy 回 429 42908 daily message quota reached"
                                           "（本机今天记了 0 条，ntfy 每天 250 条，北京时间 8 点清零）")
    w.settle()
    push("关机前")
    w.close()
    check("旧报错又出现（旧代码在跑）：没过", "旧报错又出现了" in str((mc.read(d).get("#39") or {}).get("evidence")), True)

    print("\n[停止前的那份：没过的走 errwatch 进群，不在停服务的 30 秒里等网络]")
    d, n = tmpdir(), N()
    w = Watch(d)
    bad_receipt = {"relay": {"最近指令": [{"at": "10-06 21:31", "action": "skip_today", "ok": True,
                                         "text": "今天（2026-10-06）跳过队列「晚班」：队列「晚班」：定时关闭（备份 Q.json），过后自动恢复"}],
                             "今天跳过队列": ["晚班"]}}
    push = channel(d, n, [True, True], state=bad_receipt)     # 开机 judges #15 with n; reset below
    n.sent.clear()
    (Path(d) / mc.STATE_FILE).unlink(missing_ok=True)
    push("停止前")
    w.close()
    check("没用 notifier", n.sent, [])
    check("errwatch 把 #15 推进了群，标题和依据都在",
          [t for t, b in w.group.sent if t.startswith(f"{texts.MACHINECHECK_FAIL}：#15 ") and "备份 Q.json" in b] != [], True)
    phone.Mailbox, phone.Heartbeat, phone.state_payload, boot_stages.ensure_automas = saved_channel

    # ------------------------------------------------------------------ #40
    print("\n[#40 手机信箱每天 250 条的额度中继没用完]")
    d = tmpdir()
    q = phone.Quota(d)
    q.add("hb", 150)
    q.add("state", 40)
    q.add("bye", 2)


    def quota_ctx(q, since):
        return {"why": "关机前", "tally": {"since": since},
                "quota": {"day": q.day(), "total": q.total(), "own": q.own(), "full": q.full(), "raw": q.read()}}


    t0 = time.time() - 5
    v = judged(d, "phone_state", quota_ctx(q, t0))
    check("192 条，没用完：过", (status(v, "#40"), "已用 192 条" in ev(v, "#40")), (PASS, True))
    w = Watch(d)
    q.mark_full("ntfy 回 429 42908 daily message quota reached")
    w.settle()
    n = N()
    v = judged(d, "phone_state", quota_ctx(q, t0), n)
    w.close()
    check("用完了：没过", (status(v, "#40"), "已经拒收" in ev(v, "#40")), (FAIL, True))
    check("没过推群", len(n.failed("#40")), 1)

    # ------------------------------------------------------------------ #41
    print("\n[#41 开机没读到的手机指令，连上后补读到]")
    d = tmpdir()
    w = Watch(d)
    t0 = time.time() - 5
    box = phone.Mailbox("topic-x", "8964", d)


    def timed_out(since="24h"):
        raise TimeoutError("timed out")


    box._read_backlog = timed_out
    check("开机读信箱超时：先不丢", (box.fetch(), box.backlog_missed), ([], True))
    box._read_backlog = lambda since="24h": [{"action": "skip_shutdown", "on": True}]
    got_cmds = []
    box._late_backlog(got_cmds.append, None)
    w.settle()
    v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "mailbox": box.report()})
    w.close()
    check("补读到了：过", status(v, "#41"), PASS)
    check("依据：开机那次的原因、补读到几条、只进日报",
          ("TimeoutError: timed out" in ev(v, "#41"), "补读到 1 条" in ev(v, "#41"), "只进了日报" in ev(v, "#41")),
          (True, True, True))
    check("那条指令照样交出去了", got_cmds, [{"action": "skip_shutdown", "on": True}])
    d = tmpdir()
    box = phone.Mailbox("topic-x", "8964", d)
    box._read_backlog = timed_out
    box.fetch()
    n = N()
    v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "mailbox": box.report()}, n)
    check("到关机前都没补读到：没过", (status(v, "#41"), "没补读到" in ev(v, "#41")), (FAIL, True))
    check("没过推群", len(n.failed("#41")), 1)
    d = tmpdir()
    v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0},
                                  "mailbox": phone.Mailbox("topic-x", "8964", d).report()})
    check("开机就读到了：不判", status(v, "#41"), None)

    # ------------------------------------------------------------------ #45
    print("\n[#45 手机通道断了自己连上（10054 被对方断开，连上后补收）]")
    d = tmpdir()
    w = Watch(d)
    t0 = time.time() - 5
    done = {"stop": False, "n": 0}


    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            done["stop"] = True
            return False

        def __iter__(self):
            return iter([json.dumps({"event": "keepalive", "time": int(time.time())}).encode()])

        def close(self):
            pass


    def flaky_urlopen(req, timeout=None):
        done["n"] += 1
        if done["n"] == 1:
            raise urllib.error.URLError(ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。"))
        return Resp()


    real_urlopen = urllib.request.urlopen
    urllib.request.urlopen = flaky_urlopen
    try:
        box = phone.Mailbox("topic-x", "8964", d)
        box._sleep = lambda s: None
        box.listen(lambda body: None, lambda: done["stop"])
    finally:
        urllib.request.urlopen = real_urlopen
    w.settle()
    v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "mailbox": box.report()})
    w.close()
    check("断了一次自己连上：过", status(v, "#45"), PASS)
    check("依据：哪一次、什么原因、只进日报", ("10054" in ev(v, "#45"), "只进了日报" in ev(v, "#45")), (True, True))
    d = tmpdir()
    w = Watch(d)
    phone.log.warning("手机通道断了，5 秒后重连")         # the 10-06 sweep's line
    w.settle()
    n = N()
    v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "mailbox": box.report()}, n)
    w.close()
    check("旧报错又出现：没过", (status(v, "#45"), "旧报错又出现了" in ev(v, "#45")), (FAIL, True))
    check("没过推群", len(n.failed("#45")), 1)
    down = dict(box.report(), connected=False, down_since=time.time() - 900)
    v = judged(tmpdir(), "phone_state", {"why": "关机前", "tally": {"since": t0}, "mailbox": down})
    check("关机前已经断了 15 分钟：没过", (status(v, "#45"), "已经断了 15 分钟" in ev(v, "#45")), (FAIL, True))

    # ------------------------------------------------------------------ #50
    print("\n[#50 三家停服维护公告：缓存一小时，第一次没响应重试取到只进日报]")
    saved_m = (maintenance.SOURCES, maintenance._sleep, maintenance.urllib.request.urlopen)
    maintenance._CACHE.clear()
    maintenance._STATS.clear()
    tries = {"n": 0}


    class Page:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return "<html>news</html>".encode()


    def slow_once(req, timeout=None):
        tries["n"] += 1
        if tries["n"] == 1:
            raise TimeoutError("timed out")
        return Page()


    d = tmpdir()
    w = Watch(d)
    t0 = time.time() - 5
    maintenance._sleep = lambda s: None
    maintenance.urllib.request.urlopen = slow_once
    maintenance.SOURCES = {"明日方舟": lambda now: (maintenance._get("https://ak.hypergryph.com/news"), None)[1],
                           "终末地": lambda now: None, "鸣潮": lambda now: None}
    try:
        maintenance.today()
        maintenance.today()                          # the next state push: served from the cache
        w.settle()
        v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0, "n": 2}, "maintenance": maintenance.stats()})
        check("两次上报只真取了一次、重试取到：过", status(v, "#50"), PASS)
        check("依据：真去取的次数、只进日报", ("明日方舟 1 次" in ev(v, "#50"), "只进了日报" in ev(v, "#50")), (True, True))

        def down_site(now):
            raise TimeoutError("timed out")
        maintenance._CACHE.clear()
        maintenance._STATS.clear()
        maintenance.SOURCES = {"明日方舟": lambda now: None, "终末地": down_site, "鸣潮": lambda now: None}
        maintenance.today()
        w.settle()
        n = N()
        v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0, "n": 1}, "maintenance": maintenance.stats()},
                   n)
        check("终末地取不到：没过", (status(v, "#50"), "终末地最近一次" in ev(v, "#50")), (FAIL, True))
        check("那条报错进了群（报警抄件里有）", "没好的 1 次都进了群" in ev(v, "#50"), True)
        check("没过推群", len(n.failed("#50")), 1)
    finally:
        maintenance.SOURCES, maintenance._sleep, maintenance.urllib.request.urlopen = saved_m
        maintenance._CACHE.clear()
        maintenance._STATS.clear()
        w.close()

    # ------------------------------------------------------------------ #56
    print("\n[#56 心跳写得进腾讯云，写不进又好了的只进日报]")
    answers = ["timed out", None]
    # Heartbeat.cos_beat reads cos_put from heartbeat.py's own globals.
    real_put = phone_heartbeat.cos_put
    phone_heartbeat.cos_put = lambda cos, key, data, timeout, **kw: answers.pop(0) if answers else None
    d = tmpdir()
    w = Watch(d)
    t0 = time.time() - 5
    try:
        hb = phone.Heartbeat("topic-x", d, post=lambda *a: None, cos=object())
        hb.cos_beat()
        hb.cos_beat()
        w.settle()
        v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "heartbeat": hb.cos_report()})
        check("一跳没写上、下一跳好了：过", (status(v, "#56"), "写上 1 次" in ev(v, "#56"), "只进了日报" in ev(v, "#56")),
              (PASS, True, True))
        same = {"since": time.time(), "base": {"heartbeat": hb.cos_report()}}
        check("机器没关、下一班一跳都没写：不判（按上一班末的数算）",
              status(judged(d, "phone_state", {"why": "关机前", "tally": same, "heartbeat": hb.cos_report()}), "#56"), None)
        phone_heartbeat.cos_put = lambda cos, key, data, timeout, **kw: "回 503"
        hb2 = phone.Heartbeat("topic-x", d, post=lambda *a: None, cos=object())
        hb2.cos_beat()
        hb2._cos_down = time.time() - 700            # the outage began 11 minutes ago
        hb2.cos_beat()
        w.settle()
        n = N()
        v = judged(d, "phone_state", {"why": "关机前", "tally": {"since": t0}, "heartbeat": hb2.cos_report()}, n)
        check("写不进 11 分钟：没过", (status(v, "#56"), "分钟写不进腾讯云" in ev(v, "#56")), (FAIL, True))
        check("没过推群", len(n.failed("#56")), 1)
    finally:
        phone_heartbeat.cos_put = real_put
        w.close()

    print("\n[卡池那段没给 notifier：没过的走 errwatch，标题是「🔬 上机核对没过」，正文带依据]")
    d = tmpdir()
    w = Watch(d)
    tr = _b.Trace.new()
    _b._wuwa_calendar_start(notice, "余心所向九死未悔", now, end, lambda u: None, {}, tr)
    _b.save_trace(d, now, "", tr)
    w.close()
    check("进了群", [(t, "读图没有结果" in b) for t, b in w.group.sent if t.startswith(texts.MACHINECHECK_FAIL)],
          [(texts.machinecheck_failed("#2", mc.CHECKS["#2"].what) if "#2" in mc.CHECKS else "#2", True)])

    _b._pause = saved_pause
    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
    skland.get_did, skland.login, skland.refresh, skland.bindings = _REAL_SKLAND


def _part_mc_runs():
    """Machine checks judged from a run record (ark_relay/features/machinechecks.py, event 「run」).

The user, 2026-10-06 04:59: the open ledger items must be confirmed by the machine
after a deploy, not by a person reading logs. Each check here gets a recorded or
realistic run (PASS, nothing pushed) and a broken one (FAIL, pushed to the group),
and handle._handle is driven once per script to show the wiring: the verdict lands
in state/machinecheck.json right after the record is booked.

    Formerly test_mc_runs.py.
    """
    import json
    import logging
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    (TMP / "history").mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_STATE_DIR=str(TMP / "state"),
                      SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                      WECOM_BOT_URL="", ARK_PHONE_TOPIC="", ARK_LOG_FILE=str(TMP / "relay.log"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import errwatch as alertlog, handle
    from ark_relay.features import collect_retry
    from ark_relay.features import collector_maaend, outcome
    from ark_relay.features import okww_overlay
    from ark_relay.core import texts
    from ark_relay.core import engine as eng_mod
    from ark_relay.features import machinecheck as mc
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.core.notify import route_of

    FIX = fx_dir(Path(__file__), "fixtures")


    class N:
        """A notifier that keeps a copy of every group alarm, as notify.Notifier does (alertlog.py)."""

        def __init__(self, state_dir=None, refuse=False):
            self.sent = []
            self.state_dir = state_dir
            self.refuse = refuse

        def send(self, title, body="", alert=False, **kw):
            self.sent.append((title, body, alert))
            if self.refuse:
                return ["企业微信机器人: 45009"]
            if self.state_dir and route_of(title, alert=alert) == "group":
                alertlog.AlertLog(self.state_dir).record(title, body)
            return []

        def send_group(self, title, body=""):
            return self.send(title, body, alert=True)


    mc.load()
    NOW = datetime(2026, 10, 6, 21, 40, tzinfo=SERVER_TZ)


    def judge(cid, ctx, state=None):
        """(status, evidence, pushed titles) of check `cid` on `ctx`; status None when it said nothing."""
        state = state or tmpdir()
        n = N()
        got = dict(mc.judge(state, "run", dict(ctx), notifier=n, now=NOW))
        r = got.get(cid)
        pushed = [t for t, _, a in n.sent if a and t.startswith(texts.machinecheck_failed(cid, ""))]
        if r is not None:
            print(f"    {cid} {r.status}: {r.evidence}")
        return (r.status if r else None), (r.evidence if r else ""), pushed


    def rec(script, run_id, started, ok=True, raw=None, minutes=30, failed=None):
        return RunRecord(run_id=run_id, script=script, user={"MaaEnd": "endfield", "OK-WW": "wuwa"}.get(script, "ark"),
                         started=started, finished=started + timedelta(minutes=minutes), ok=ok,
                         failed_tasks=list(failed or []), raw=dict(raw or {}))


    def ww(lines, day="2026-10-06"):
        """OK-WW log lines as AUTO-MAS keeps them (tests/replay/2026-09-07/wuwa)."""
        return "\n".join(f"{day} 09:{20 + i // 60:02d}:{i % 60:02d},100 INFO TaskExecutor {x}" for i, x in enumerate(lines))


    WWREC = rec("OK-WW", "2026-10-06/wuwa/OK-WW-05-19-17", datetime(2026, 10, 6, 9, 19, 17, tzinfo=SERVER_TZ))


    def wwctx(lines, **kw):
        return dict({"rec": WWREC, "raw": {}, "log_text": ww(lines)}, **kw)


    # ------------------------------------------------------------------ #4
    print("\n[#4 周本领奖：领完回读到少了一次才算]")
    WEEKLY_IN = ["FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0",
                 "FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：3/3_1.00, x60_0.79]",
                 "FarmEchoTask:teleport_to_boss prepared as realm", "FarmEchoTask:enter combat None",
                 "FarmEchoTask:周本领奖：打完了，去结晶按 F", "FarmEchoTask:周本领奖：认出弹窗，点确认。读到 …",
                 "FarmEchoTask:周本领奖：已点确认"]
    st, ev, pushed = judge("#4", wwctx(WEEKLY_IN + ["FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3"]))
    check("read-back dropped: PASS, nothing pushed", (st, pushed), ("PASS", []))
    check("evidence is the read-back line", "回读确认领到，本周剩余 3/3→2/3" in ev)
    st, ev, pushed = judge("#4", wwctx(WEEKLY_IN + ["FarmEchoTask:周本领奖：回读次数没变（3/3），这次没领到"]))
    check("read-back unchanged: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("evidence says it was not claimed", "没领到" in ev)
    st, ev, _ = judge("#4", wwctx(WEEKLY_IN[:3] + ["FarmEchoTask:周本领奖：这一圈没打起来（进场后一直没进战斗），不去找结晶"]))
    check("10-05 shape (in, never fought): FAIL", st, "FAIL")
    check("…saying it never fought", "没有开打" in ev)
    st, _, _ = judge("#4", wwctx(["FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0",
                                  "FarmEchoTask:本周周本次数已领满（0/3），不进本，跳过"]))
    check("week already capped: not judged", st, None)
    st, _, _ = judge("#4", wwctx(WEEKLY_IN + ["FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3"],
                                 raw={"hand_started": "task-1"}))
    check("a run a person started: not judged (only unattended runs count)", st, None)
    st, _, _ = judge("#4", wwctx(["DailyTask:open_daily"]))
    check("no weekly boss in the run: not judged", st, None)

    # ------------------------------------------------------------------ #27
    print("\n[#27 周本「确认前往」后读屏认出选等级页]")
    DIALOG = ["FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0",
              "FarmEchoTask:限时提前开放的剧情提示框，点确认前往。框里读到：提前到达目标位置可能影响剧情体验，是否确认前往？"]
    st, ev, pushed = judge("#27", wwctx(DIALOG + [
        "FarmEchoTask:限时提前开放：确认后是这个 Boss 的选等级页，按正常进本走（选等级→单人挑战→开启挑战）。整屏读到 定序诸理之律 推荐等级40-90 单人挑战",
        "FarmEchoTask:teleport_to_boss prepared as realm", "FarmEchoTask:enter combat None"]))
    check("level page read, then a fight: PASS", (st, pushed), ("PASS", []))
    check("evidence names the level page", "选等级页" in ev)
    st, ev, pushed = judge("#27", wwctx(DIALOG + [
        "FarmEchoTask:进本：限时提前开放确认后（in_world=True）这一屏认不出，停下不走（不去大世界走路）。整屏读到 终端"]))
    check("screen not recognised after the dialog: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("evidence is the stop line", "这一屏认不出" in ev)
    st, ev, _ = judge("#27", wwctx(DIALOG + [
        "FarmEchoTask:限时提前开放：确认后是这个 Boss 的选等级页，按正常进本走（选等级→单人挑战→开启挑战）。整屏读到 …",
        "FarmEchoTask:周本：补点单人挑战 3 次都没进开启挑战"]))
    check("page read but never got in: FAIL", st, "FAIL")
    st, _, _ = judge("#27", wwctx(WEEKLY_IN))
    check("no dialog this run: not judged", st, None)

    # ------------------------------------------------------------------ #5 / #25 / #26
    print("\n[#5 只刷指定点位的改动贴上了]")
    NEST = {"checks": [], "msg": None, "expect_nest": True, "only_nest": "落渊南丘"}
    NEST_OK = ["NightmareNestTask:open_boss_book canxiang", "NightmareNestTask:opened gray_book_boss",
               "NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）",
               "NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2",
               "NightmareNestTask:nightmare nest: 点进点位 41:3（截图 nest_go）", "NightmareNestTask:enter combat None"]
    st, ev, pushed = judge("#5", wwctx(NEST_OK, outcome=NEST))
    check("filter announced: PASS", (st, pushed), ("PASS", []))
    check("evidence is the filter line", "只刷 ['落渊南丘']" in ev)
    st, ev, pushed = judge("#5", wwctx(["NightmareNestTask:nightmare nest: 只刷指定点位的改动没装上，这一轮不刷巢穴"], outcome=NEST))
    check("not installed: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    st, ev, _ = judge("#5", wwctx(["NightmareNestTask:opened gray_book_boss",
                                   "NightmareNestTask:left_click 已击败残象：0/48 (1729, 347) after_sleep 2"], outcome=NEST))
    check("list opened with no filter line (10-04 / 10-05): FAIL", st, "FAIL")
    st, _, _ = judge("#5", wwctx(NEST_OK, outcome=dict(NEST, only_nest="")))
    check("no 「only these nests」 setting: not judged", st, None)
    # Audit 11-08 C-11: a nest fought with no filter line and no 「opened gray_book_boss」 line
    # (an upstream that logs the page under other words) is the copy missing from that run.
    st, ev, pushed = judge("#5", wwctx(["NightmareNestTask:open_boss_book canxiang",
                                        "NightmareNestTask:enter combat None"], outcome=NEST))
    check("fought a nest, no filter line, no page line: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("……the evidence is the fight line", "enter combat" in ev, True)
    st, _, _ = judge("#5", wwctx(["NightmareNestTask:open_boss_book canxiang",
                                  "NightmareNestTask:Traceback (most recent call last):"], outcome=NEST))
    check("started, cut short before any nest (no page, no fight): not judged", st, None)

    print("\n[#25 残象聚落只认战斗]")
    TEN05 = ["NightmareNestTask:opened gray_book_boss", "NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）",
             "NightmareNestTask:Box(已击败残象：0/48) is not complete",
             "NightmareNestTask:nightmare nest unreachable, skip this run: go_nest:48:18"]
    good = outcome.okww_checks(ww(TEN05), expect_nest=True, only_nest="落渊南丘")
    st, ev, pushed = judge("#25", wwctx(TEN05, outcome=dict(NEST, checks=good), raw={"okww_steps": ["残象聚落（开了界面就退出，一次没打）"]}))
    check("10-05 morning with today's verdict (not farmed): PASS", (st, pushed), ("PASS", []))
    check("evidence says it was not counted", "没记成刷了" in ev)
    old = [outcome.Check("残象聚落", True, "有进本/战斗记录")]       # the verdict before 10-05 14:27
    st, ev, pushed = judge("#25", wwctx(TEN05, outcome=dict(NEST, checks=old), raw={"okww_steps": ["残象聚落"]}))
    check("the same morning booked as farmed (the old verdict): FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("evidence quotes the nest's last line", "unreachable" in ev)
    st, ev, _ = judge("#25", wwctx(NEST_OK, outcome=dict(NEST, checks=outcome.okww_checks(ww(NEST_OK), expect_nest=True,
                                                                                            only_nest="落渊南丘"))))
    check("a real fight booked as farmed: PASS on the combat line", (st, "NightmareNestTask:enter combat" in ev), ("PASS", True))

    print("\n[#26 find_nest：日志和覆盖层报告一致]")
    rep_dir = tmpdir()
    okww_overlay.REPORT = rep_dir / "ark-okww-overlay.json"


    def report(applied, adapted=(), skipped=(), at=None):
        okww_overlay.REPORT.write_text(json.dumps({"applied": list(applied), "adapted": [{"what": w, "why": "x"} for w in adapted],
                                                   "skipped": [{"what": w, "why": "x"} for w in skipped], "error": ""},
                                                  ensure_ascii=False), encoding="utf-8")
        t = (at or WWREC.started + timedelta(seconds=20)).timestamp()
        os.utime(okww_overlay.REPORT, (t, t))
        return okww_overlay.report_snapshot()


    snap = report(["NightmareNestTask.find_nest", "NightmareNestTask.run"])
    check("report_snapshot reads the report and when it was written",
          (snap["applied"][0], snap["written"][:19]), ("NightmareNestTask.find_nest", "2026-10-06T09:19:37"))
    st, ev, pushed = judge("#26", wwctx(NEST_OK, overlay=snap))
    check("log and report both say installed: PASS", (st, pushed), ("PASS", []))
    st, ev, pushed = judge("#26", wwctx(["NightmareNestTask:nightmare nest: 只刷指定点位的改动没装上，这一轮不刷巢穴"], overlay=snap))
    check("log says not installed, report says installed (the 10-05 contradiction): FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("evidence carries both", "对不上" in ev and "装上" in ev)
    snap2 = report(["NightmareNestTask.run"], skipped=["NightmareNestTask.find_nest"])
    st, _, _ = judge("#26", wwctx(["NightmareNestTask:nightmare nest: 只刷指定点位的改动没装上，这一轮不刷巢穴"], overlay=snap2))
    check("both say not installed: consistent (PASS here; #5 says FAIL)", st, "PASS")
    later = report(["NightmareNestTask.find_nest"], at=WWREC.finished + timedelta(hours=2))
    st, _, _ = judge("#26", wwctx(NEST_OK, overlay=later))
    check("report rewritten by a later OK-WW start: not judged on this run", st, None)
    st, ev, _ = judge("#26", wwctx(NEST_OK, overlay={}))
    check("no report at all: FAIL", st, "FAIL")
    okww_overlay.REPORT.unlink()
    check("report_snapshot: {} when there is no report", okww_overlay.report_snapshot(), {})

    # ------------------------------------------------------------------ MaaEnd
    END_LOG = (FIX / "maaend-farm-drops" / "2026-09-27.log").read_text(encoding="utf-8")
    ENDREC = rec("MaaEnd", "2026-09-27/endfield/MaaEnd-05-35-00", datetime(2026, 9, 27, 9, 35, tzinfo=SERVER_TZ), minutes=40)


    def endctx(text=END_LOG, raw=None, **kw):
        return dict({"rec": ENDREC, "raw": raw if raw is not None else collector_maaend.parse_maaend_log(write(text)),
                     "log_text": text}, **kw)


    def write(text):
        f = tmpdir() / "MaaEnd.log"
        f.write_text(text, encoding="utf-8")
        return f


    print("\n[#20 产出和剩余理智按游戏结算记（09-27 协议空间：两次进入、一次到账）]")
    raw = collector_maaend.parse_maaend_log(write(END_LOG))
    st, ev, pushed = judge("#20", endctx(raw=raw))
    check("today's reading of the real 09-27 log: PASS", (st, pushed), ("PASS", []))
    check("evidence has the game's items and reading", "折金票×68000" in ev and "当前理智 117/360" in ev)
    bad = dict(raw, maaend_farm_runs=2, sanity=0)        # what the reading before 09-29 01:32 booked
    st, ev, pushed = judge("#20", endctx(raw=bad))
    check("the old reading (2 runs, 0 left): FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("evidence names both numbers", "趟数 2≠1" in ev and "剩余理智 0≠117" in ev)
    st, _, _ = judge("#20", endctx(raw=dict(raw, maaend_farm_drops={})))
    check("the output row empty (before the fix): FAIL", st, "FAIL")
    essence = (FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log").read_text(encoding="utf-8")
    st, _, _ = judge("#20", endctx(text=essence))
    check("essence farming (no item list): not judged", st, None)

    print("\n[#20 剩余理智按最后一次领奖的到账算（daysim-R3：10-07、10-08、10-11 最后一次是单倍）]")
    # The three real runs the day replays found (docs/BACKLOG.md daysim-R3). Each ends with a
    # single-reward claim (折金票 ×34000) after the last reading: 117 -> 37 (10-07, 10-11;
    # 10-08's first reading 237 = 37 + 200 regenerated), 118 + one potion -> 78 (10-08). The
    # old #20 took one claim as the largest drop between readings (160) and wanted 0.
    R3 = FIX / "maaend-sanity-1013"
    for name, left in (("2026-10-07_MaaEnd-05-29-05", 37), ("2026-10-08_MaaEnd-05-29-15", 78),
                       ("2026-10-11_MaaEnd-05-30-34", 37)):
        text = (R3 / f"{name}.log").read_text(encoding="utf-8")
        raw = collector_maaend.parse_maaend_log(write(text))
        check(f"{name}: the collector books {left} left", raw.get("sanity"), left)
        st, ev, pushed = judge("#20", endctx(text=text, raw=raw))
        check(f"{name}: #20 agrees ({left} left): PASS, nothing pushed", (st, pushed), ("PASS", []))
        check(f"{name}: evidence names the single-reward claim and {left}",
              "折金票×34000" in ev and f"剩 {left}" in ev, True)
        st, ev, pushed = judge("#20", endctx(text=text, raw=dict(raw, sanity=0)))
        check(f"{name}: 0 left (the last claim charged as a double one): FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
        check(f"{name}: evidence names 0≠{left}", f"剩余理智 0≠{left}" in ev, True)

    print("\n[#7 环境监测：每趟收下那一段的框架日志，只收不判，不推]")
    # The coordinator, 2026-10-06: no line of its own in the AUTO-MAS log is no proof of
    # failure (the 110 s run of 09-04 wrote none either), and the repo has no framework-log
    # sample of 环境监测 to tell working from not. So #7 captures and never pushes on what
    # it captured. The node names below are placeholders in MaaFW's event-line shape
    # (fixtures/collect-watch-2026-09-14/maafw-attempt3.log); the check does not read meaning
    # into them.
    ENV_FW = "[2026-09-27 09:42:{}][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65][MaaNS::EventDispatcher::notify] "
    fwdir = tmpdir()
    (fwdir / "debug").mkdir(parents=True)
    (fwdir / "debug" / "maafw.log").write_text("\n".join([
        ENV_FW.format("50.900") + '!!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] [details={"name":"BeforeWindow"}]',
        ENV_FW.format("51.200") + '!!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.Starting] [details={"entry":"PlaceholderEntry","task_id":200000013}]',
        ENV_FW.format("52.000") + '!!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] [details={"name":"PlaceholderNodeA","task_id":200000013}]',
        ENV_FW.format("55.500") + '!!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] [details={"name":"PlaceholderNodeB","task_id":200000013}]',
        ENV_FW.format("57.300") + '!!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.Succeeded] [details={"entry":"PlaceholderEntry","task_id":200000013}]',
    ]) + "\n", encoding="utf-8")
    state = tmpdir()
    st, ev, pushed = judge("#7", endctx(maaend_dir=str(fwdir)), state=state)
    check("09-27 (6 s, no line of its own in the AUTO-MAS log), framework lines there: PASS (captured), nothing pushed",
          (st, pushed), ("PASS", []))
    check("the daily line says it is capture only, with the window, the task and the nodes",
          ev.startswith("只收不判：环境监测 6 秒（09:42:51→09:42:57）") and "PlaceholderEntry" in ev
          and "PlaceholderNodeA、PlaceholderNodeB" in ev)
    kept = state / "machinecheck-env" / "2026-09-27_endfield_MaaEnd-05-35-00.log"
    check("the stretch is kept in state/machinecheck-env/<run>.log, named in the line",
          (kept.is_file(), "machinecheck-env/2026-09-27_endfield_MaaEnd-05-35-00.log" in ev), (True, True))
    body = kept.read_text(encoding="utf-8") if kept.is_file() else ""
    check("only the task's own window (start 09:42:51 → finish 09:42:57) is kept",
          ("PlaceholderNodeB" in body, "BeforeWindow" in body), (True, False))
    check("the check is kind B (judged when the next 环境监测 run comes) and never says done/not done",
          (mc.CHECKS["#7"].kind, "只收不判" in mc.CHECKS["#7"].what), ("B", True))
    nofw = tmpdir()
    state = tmpdir()
    st, ev, pushed = judge("#7", endctx(maaend_dir=str(nofw)), state=state)
    check("no framework log for the window: not judged, nothing pushed", (st, pushed), (None, []))
    st, ev, pushed = judge("#7", endctx(maaend_dir=str(nofw)), state=state)
    check("the second run in a row without it: FAIL (missing evidence), pushed", (st, len(pushed)), ("FAIL", 1))
    check("…saying why there is none", "连续 2 趟" in ev and "框架日志" in ev)
    st, _, _ = judge("#7", endctx(maaend_dir=str(fwdir)), state=state)
    check("a run with the lines again: captured, the count starts over", st, "PASS")
    st, _, pushed = judge("#7", endctx(maaend_dir=str(nofw)), state=state)
    check("one miss after that: not judged again", (st, pushed), (None, []))
    st, _, _ = judge("#7", endctx(text=essence, maaend_dir=str(fwdir)), state=tmpdir())
    check("a run without 环境监测: not judged", st, None)

    print("\n[#28 四个任务：图片在、终末地自己的记录不在 → 不再算过（真数据见 test_mc28.py）]")
    state = tmpdir()
    shots = {}
    for t in ("赠送干员礼物", "装备制造", "转交委托", "环境监测"):
        p = state / "shots" / "2026-09-27" / "MaaEnd-09-36-00" / f"094300-{t}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"png")
        shots[t] = p.relative_to(state).as_posix()
    times = collector_maaend.task_times(END_LOG)
    check("the 09-27 log ran all four", all(t in times for t in shots), True)
    st, ev, pushed = judge("#28", endctx(raw=dict(raw, tasks_shot_files=shots), maaend_dir=str(tmpdir())), state=state)
    check("a picture for each but no MaaFW log: not judged (was PASS on the picture alone)", (st, pushed), (None, []))

    print("\n[#30 基质刷取领奖后失败：背包满了 / 原始日志]")
    BAG = (FIX / "maaend_bagfull_2026-09-25.log").read_text(encoding="utf-8")
    end = tmpdir()
    (end / "debug").mkdir(parents=True)
    (end / "debug" / "maafw.log").write_bytes((FIX / "maaend_bagfull_2026-09-25_maafw.log").read_bytes())
    check("claim_failures finds the essence failure after the click",
          [x[0] for x in collector_maaend.claim_failures(BAG)], ["基质刷取"])
    bag_raw = collector_maaend.parse_maaend_log(write(BAG), end)
    BAGREC = rec("MaaEnd", "2026-09-25/endfield/MaaEnd-05-54-06", datetime(2026, 9, 25, 9, 54, 6, tzinfo=SERVER_TZ),
                 ok=False, raw=bag_raw, failed=bag_raw.get("tasks_failed"))
    st, ev, pushed = judge("#30", {"rec": BAGREC, "raw": bag_raw, "log_text": BAG, "maaend_dir": str(end)})
    check("storage-full notice seen, alarm says 背包满了: PASS", (st, pushed), ("PASS", []))
    check("evidence is the notice line", "仓储空间已满" in ev)
    no_fw = tmpdir()
    (no_fw / "debug").mkdir(parents=True)
    bare = collector_maaend.parse_maaend_log(write(BAG), no_fw)
    BARE = rec("MaaEnd", BAGREC.run_id, BAGREC.started, ok=False, raw=bare, failed=bare.get("tasks_failed"))
    st, ev, pushed = judge("#30", {"rec": BARE, "raw": bare, "log_text": BAG, "maaend_dir": str(no_fw)})
    check("no notice: the alarm carries the raw lines: PASS", (st, "原始日志" in ev), ("PASS", True))
    lost = dict(bare)
    lost.pop("maaend_claim_lines", None)
    BAD = rec("MaaEnd", BAGREC.run_id, BAGREC.started, ok=False, raw=lost, failed=lost.get("tasks_failed"))
    st, ev, pushed = judge("#30", {"rec": BAD, "raw": lost, "log_text": BAG, "maaend_dir": str(no_fw)})
    check("neither the cause nor the raw lines: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    wrong = dict(bag_raw, maaend_fail_causes={})
    WRONG = rec("MaaEnd", BAGREC.run_id, BAGREC.started, ok=False, raw=wrong, failed=wrong.get("tasks_failed"))
    st, ev, _ = judge("#30", {"rec": WRONG, "raw": wrong, "log_text": BAG, "maaend_dir": str(end)})
    check("the notice was there but the cause not named: FAIL", (st, "仓储空间已满" in ev), ("FAIL", True))

    print("\n[#29 采集撞上「战斗中无法使用」的那条路线]")
    COLLECT = "\n".join([
        "[2026-10-05 10:01:54.000] 任务开始: 🌿自动采集",
        "[2026-10-05 10:05:10.000] 路线14：四号谷地-晶化多齿叶",
        "[2026-10-05 10:09:16.566] 路线15：武陵-红矛叶",
        "[2026-10-05 10:12:40.000] 路线16：武陵-协议纹石",
        "[2026-10-05 10:20:00.000] 任务完成: 🌿自动采集"])
    fw = tmpdir()
    (fw / "debug").mkdir(parents=True)
    P = "[2026-10-05 10:{}][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65][MaaNS::EventDispatcher::notify] "
    FW_HIT = (P.format("10:03.000") + '[msg=Node.Recognition.Succeeded] [details={"name":"AutoCollectFindButtonUsing",'
              '"reco_detail":{"text":"战斗中无法使用"}}]')
    FW_END = P.format("12:30.000") + '!!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] [details={"name":"AutoCollectRoute15End"}]'
    FW_ESC = P.format("10:05.000") + '[msg=Node.Recognition.Succeeded] [details={"text":"' + json.dumps("战斗中无法使用").strip('"') + '"}]'
    (fw / "debug" / "maafw.log").write_text(FW_HIT + "\n" + FW_HIT.replace("Px7172", "Px18500") + "\n" + FW_ESC + "\n"
                                           + FW_END + "\n", encoding="utf-8")
    CREC = rec("MaaEnd", "2026-10-05/endfield/MaaEnd-06-01-00", datetime(2026, 10, 5, 10, 1, tzinfo=SERVER_TZ))
    hits = collector_maaend.maafw_grep(str(fw), datetime(2026, 10, 5, 10, 0), datetime(2026, 10, 5, 10, 20), ("战斗中无法使用",))
    check("maafw_grep: the plain line once (the second process's echo dropped), and the JSON-escaped one",
          [h[12:20] for h in hits], ["10:10:03", "10:10:05"])
    check("maafw_grep: nothing outside the window",
          collector_maaend.maafw_grep(str(fw), datetime(2026, 10, 5, 10, 11), datetime(2026, 10, 5, 10, 20),
                                      ("战斗中无法使用",)), [])
    st, _, _ = judge("#29", {"rec": CREC, "raw": {}, "log_text": COLLECT, "maaend_dir": str(fw)})
    check("the toast text alone, no picture: not judged (the text is in no real log, ledger #29)", st, None)
    # Judged by MaaEnd's on_error picture of the relay-device node inside a route's window
    # (tests/test_collect.py has the real 10-05 / 10-08 / 10-12 runs).
    SHOT = "2026.10.05-10.10.03.000___MapNavigatorObstacleDevice_InteractPost.png"
    (fw / "debug" / "on_error").mkdir()
    (fw / "debug" / "on_error" / SHOT).write_bytes(b"")
    booked = outcome.maaend_checks(COLLECT, [SHOT])
    st, ev, pushed = judge("#29", {"rec": CREC, "raw": {}, "log_text": COLLECT, "maaend_dir": str(fw),
                                   "outcome": {"checks": booked}})
    check("route 15 hit it and was booked for the retry: PASS", (st, pushed), ("PASS", []))
    check("evidence names the route and the picture", "路线15：武陵-红矛叶" in ev and SHOT in ev)
    st, ev, pushed = judge("#29", {"rec": CREC, "raw": {}, "log_text": COLLECT, "maaend_dir": str(fw),
                                   "outcome": {"checks": [outcome.Check("出错截图 1 张（已重试恢复）", True)]}})
    check("the picture taken as 「已重试恢复」, route not booked: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    st, _, _ = judge("#29", {"rec": CREC, "raw": {}, "log_text": COLLECT, "maaend_dir": str(tmpdir())})
    check("the picture never seen: not judged", st, None)

    # ------------------------------------------------------------------ #6 / #24a, #43 / #46, #24b
    print("\n[#6 / #24a 做完以后装新版重启：判过的不重判，进过群的就是没过]")
    RID = "2026-10-04/endfield/MaaEnd-05-50-53"
    UR = {RID: {"version": "v2.32.0-beta.1", "started": "2026-10-04T09:50:53+08:00",
                "done": "2026-10-04/endfield/MaaEnd-05-26-41", "held": False}}
    R4 = rec("MaaEnd", RID, datetime(2026, 10, 4, 9, 50, 53, tzinfo=SERVER_TZ), ok=False)
    state = tmpdir()
    st, ev, pushed = judge("#6", {"rec": R4, "raw": {}, "update_restarts": UR}, state=state)
    check("let go, no alarm copy: PASS", (st, pushed), ("PASS", []))
    check("evidence names both runs", "MaaEnd-05-50-53" in ev and "MaaEnd-05-26-41" in ev)
    check("#24a judged the same run on its own row", (mc.read(state).get("#24a") or {}).get("status"), "PASS")
    st, _, _ = judge("#6", {"rec": R4, "raw": {}, "update_restarts": UR}, state=state)
    check("the same restart is judged once", st, None)
    state = tmpdir()
    alertlog.AlertLog(state).record(texts.failed("MaaEnd"), "重试 2 次全部失败，已交给我们这边去查。\n· 失败于：MaaEnd 装新版 v2.32.0-beta.1 后自己重启，这一次重试被用掉",
                                    now=datetime(2026, 10, 4, 1, 51, 26, tzinfo=alertlog.timezone.utc))
    st, ev, pushed = judge("#6", {"rec": R4, "raw": {}, "update_restarts": UR}, state=state)
    check("10-04 09:51:26 「❌ MaaEnd 失败」 in the alarm copies: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    check("evidence is that alarm", "2026-10-04 09:51:26" in ev and "❌ MaaEnd 失败" in ev)
    st, _, _ = judge("#6", {"rec": R4, "raw": {}, "update_restarts": {RID: dict(UR[RID], held=True)}}, state=tmpdir())
    check("still held (the push step lets it go): not judged yet", st, None)
    st, _, _ = judge("#6", {"rec": R4, "raw": {}, "update_restarts": {RID: dict(UR[RID], done="")}}, state=tmpdir())
    check("no done round in the shift: not this case", st, None)
    # Two restarts settled in one batch: both are marked seen at once, so the verdict must
    # cover both (until 2026-10-13 the first FAIL returned and the second was never judged).
    RID2 = "2026-10-04/endfield/MaaEnd-06-40-02"
    UR2 = dict(UR, **{RID2: {"version": "v2.32.0-beta.2", "started": "2026-10-04T10:40:02+08:00",
                             "done": "2026-10-04/endfield/MaaEnd-05-26-41", "held": False}})
    noisy = [{"msg": "MaaEnd-06-40-02 重启后读不到记录", "pushed": False, "recovered": False}]
    state = tmpdir()
    alertlog.AlertLog(state).record(texts.failed("MaaEnd"), "重试 2 次全部失败，已交给我们这边去查。\n· 失败于：MaaEnd 装新版 v2.32.0-beta.1 后自己重启，这一次重试被用掉",
                                    now=datetime(2026, 10, 4, 1, 51, 26, tzinfo=alertlog.timezone.utc))
    st, ev, _ = judge("#6", {"rec": R4, "raw": {}, "update_restarts": UR2, "relay_errors": noisy}, state=state)
    check("two restarts, both wrong: FAIL", st, "FAIL")
    check("…naming both: the alarm copy of the first and the relay error of the second",
          ("MaaEnd-05-50-53" in ev and "却进了群" in ev, "MaaEnd-06-40-02" in ev and "会进群的报错" in ev), (True, True))
    st, _, _ = judge("#6", {"rec": R4, "raw": {}, "update_restarts": UR2, "relay_errors": noisy}, state=state)
    check("…and neither is judged again", st, None)

    print("\n[#43 / #46 没干完的每一趟都进了群]")
    undone = "OK-WW 这一轮有 1 项没干成，但它自己没报错：\n· 残象聚落：点了点位，但传送不过去，一次没打"
    state = tmpdir()
    alertlog.AlertLog(state).record(texts.ROUND_INCOMPLETE, undone)
    row = json.loads((state / "alerts").glob("*.jsonl").__next__().read_text(encoding="utf-8"))
    ctx = {"rec": WWREC, "raw": {}, "outcome": {"checks": [], "msg": undone}, "alerts": [row]}
    st, ev, pushed = judge("#46", ctx, state=state)
    check("the alarm is among the copies: PASS", (st, pushed), ("PASS", []))
    check("evidence names the alarm", texts.ROUND_INCOMPLETE in ev)
    st, ev, pushed = judge("#46", dict(ctx, alerts=[]), state=tmpdir())
    check("no copy of it: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    st, ev, _ = judge("#46", dict(ctx, alerts=[], unsent=[WWREC.run_id]), state=tmpdir())
    check("…saying the push is queued when it is", "排在下一轮重推" in ev)
    st, _, _ = judge("#46", dict(ctx, outcome={"checks": [], "msg": None}), state=tmpdir())
    check("nothing undone: not judged", st, None)
    st, _, _ = judge("#43", ctx, state=state)
    check("#43 is MaaEnd's: not judged on an OK-WW run", st, None)

    print("\n[#24b 预更新没结论：再试一次，还没结论就进群（读 relay.log）]")
    relay = Path(os.environ["ARK_LOG_FILE"])
    today = datetime.now(tz=SERVER_TZ).strftime("%m-%d")
    relay.write_text("\n".join([
        f"{today} 08:46:10 INFO    ark.service  预更新：MAA 没给出结论（MAA 180 秒内没给出更新结论），再试一次",
        f"{today} 08:50:34 WARNING ark.service  预更新有 1 项没能确认：",
        "· MAA 180 秒内没给出更新结论"]) + "\n", encoding="utf-8")
    state = tmpdir()
    alertlog.AlertLog(state).record(texts.unconfirmed("预更新", 1), "· MAA 180 秒内没给出更新结论")
    st, ev, pushed = judge("#24b", {"rec": WWREC, "raw": {}}, state=state)
    check("retried, still unconfirmed, alarm in the copies: PASS", (st, pushed), ("PASS", []))
    check("evidence starts with the retry line's time", ev.startswith(f"{today} 08:46:10"))
    st, _, _ = judge("#24b", {"rec": WWREC, "raw": {}}, state=state)
    check("the same pre-update is judged once", st, None)
    st, ev, pushed = judge("#24b", {"rec": WWREC, "raw": {}}, state=tmpdir())
    check("no copy of the alarm: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
    relay.write_text(f"{today} 08:50:34 WARNING ark.service  预更新有 1 项没能确认：\n", encoding="utf-8")
    st, ev, _ = judge("#24b", {"rec": WWREC, "raw": {}}, state=tmpdir())
    check("unconfirmed without a second try: FAIL", (st, "再试一次" in ev), ("FAIL", True))
    RETRY = f"{today} 08:46:10 INFO    ark.service  预更新：OK-WW 没给出结论（OK-WW 预更新：拿不到控制台会话，**没有检查更新**），再试一次"
    relay.write_text("\n".join([
        RETRY,
        f"{today} 08:49:02 WARNING ark.service  预更新：OK-WW 第一次没给出结论，再试一次给出了结论",
        "OK-WW 预更新：拿不到控制台会话，**没有检查更新**"]) + "\n", encoding="utf-8")
    st, ev, pushed = judge("#24b", {"rec": WWREC, "raw": {}}, state=tmpdir())
    check("retried and the second try gave a verdict: PASS", (st, pushed, "第二次给出了结论" in ev), ("PASS", [], True))
    # A stop during the second try (boot_stages._once_more) logs the retry line and nothing after.
    relay.write_text(RETRY + "\n", encoding="utf-8")
    st, _, _ = judge("#24b", {"rec": WWREC, "raw": {}}, state=tmpdir())
    check("retry line but no verdict and no alarm line (stopped mid-retry): not judged, not PASS", st, None)
    relay.write_text("", encoding="utf-8")
    st, _, _ = judge("#24b", {"rec": WWREC, "raw": {}}, state=tmpdir())
    check("no pre-update trouble today: not judged", st, None)
    check("#24c / #24d are listed as not machine-checkable, with the reason",
          ("#24c" in mc.CANNOT and "10-06" in mc.CANNOT["#24c"][1], "#24d" in mc.CANNOT), (True, True))

    # ------------------------------------------------------------------ wiring through handle._handle
    print("\n[handle._handle: the checks are judged right after the record is booked]")


    class Src:
        def fetch(self, seen):
            return []


    handle._ship_evidence = lambda eng, r: ""
    handle._weekly_gates = lambda eng, r: None
    collect_retry.restore_master = lambda cfg: ""


    def build(notifier_refuses=False):
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.maaend_dir = tmpdir()
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=N(cfg.state_dir, notifier_refuses))
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._archive_maaend_evidence = lambda r: None
        return e


    e = build()
    e._verify_outcome = lambda rr: None
    okww_log = TMP / "history" / "OK-WW-05-19-17.log"
    okww_log.write_text(ww(WEEKLY_IN + ["FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3",
                                        "DailyTask:Daily Task Completed", "TacetTask:enter combat"]), encoding="utf-8")
    r = rec("OK-WW", "2026-10-06/wuwa/OK-WW-05-19-17", datetime(2026, 10, 6, 9, 19, 17, tzinfo=SERVER_TZ))
    r.log_path = okww_log
    handle._handle(e, r)
    saved = mc.read(e.cfg.state_dir)
    check("#4 judged and kept in state/machinecheck.json", (saved.get("#4") or {}).get("status"), "PASS")
    check("with the run's own read-back line", "3/3→2/3" in (saved.get("#4") or {}).get("evidence", ""))
    check("nothing pushed for a PASS", [t for t, _, a in e.notifier.sent if a], [])

    print("\n[handle._handle: an undone OK-WW round's alarm is checked against the alarm copies]")
    okww_log.write_text(ww(["NightmareNestTask:opened gray_book_boss", "DailyTask:Daily Task Completed",
                            "TacetTask:enter combat"]), encoding="utf-8")
    e = build()
    e._verify_outcome = lambda rr: handle._judged(rr, [outcome.Check("残象聚落", False, "一次没打")], "OK-WW",
                                                  expect_nest=True, only_nest="")
    handle._handle(e, r)
    check("#46: the alarm went out and its copy is there", (mc.read(e.cfg.state_dir).get("#46") or {}).get("status"), "PASS")
    e = build(notifier_refuses=True)
    e._verify_outcome = lambda rr: handle._judged(rr, [outcome.Check("残象聚落", False, "一次没打")], "OK-WW",
                                                  expect_nest=True, only_nest="")
    handle._handle(e, r)
    check("#46: the group refused it: FAIL", (mc.read(e.cfg.state_dir).get("#46") or {}).get("status"), "FAIL")
    check("…and the FAIL itself was pushed (tried; the same group refused it)",
          any(t.startswith(texts.machinecheck_failed("#46", "")) for t, _, a in e.notifier.sent if a), True)

    print("\n[handle._handle: a broken check context never breaks the booking]")
    e = build()
    real = handle._run_ctx
    handle._run_ctx = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
    errs = []
    h = type("H", (logging.Handler,), {"emit": lambda self, rr: errs.append(rr.getMessage())})(level=logging.ERROR)
    handle.log.addHandler(h)
    try:
        handle._handle(e, r)
    finally:
        handle._run_ctx = real
        handle.log.removeHandler(h)
    check("the record is on the ledger", [x["run_id"] for x in e.state.read_ledger("2026-10-06")], [r.run_id])
    check("an ERROR says the machine check did not run (errwatch pushes it)", any("上机核对没跑成" in m for m in errs))

    print("\n[handle._mark_task_shots keeps each picture's path]")
    e = build()
    day = e.cfg.state_dir / "shots" / "2026-09-27" / "MaaEnd-09-36-00"
    day.mkdir(parents=True)
    for t, hhmmss in (("环境监测", "094258"), ("装备制造", "094000")):
        f = day / f"{hhmmss}-{t}.png"
        f.write_bytes(b"png")
        at = datetime.strptime(f"2026-09-27 {hhmmss}", "%Y-%m-%d %H%M%S").replace(tzinfo=SERVER_TZ).timestamp()
        os.utime(f, (at, at))
    mrec = rec("MaaEnd", "2026-09-27/endfield/MaaEnd-05-35-00", datetime(2026, 9, 27, 9, 35, tzinfo=SERVER_TZ), minutes=40)
    mrec.log_path = write(END_LOG)
    handle._mark_task_shots(e, mrec)
    check("tasks_shot as before", sorted(mrec.raw.get("tasks_shot") or []), ["环境监测"])
    check("tasks_shot_files names the picture under the state folder",
          mrec.raw.get("tasks_shot_files"), {"环境监测": "shots/2026-09-27/MaaEnd-09-36-00/094258-环境监测.png"})

    print("\n[handle._run_ctx: a run log that cannot be read is said, and marked in the context]")
    e = build()
    unreadable = TMP / "history" / "a-directory.log"
    unreadable.mkdir(exist_ok=True)              # read_text raises IsADirectoryError / PermissionError
    ur = rec("OK-WW", "2026-10-06/wuwa/OK-WW-06-00-00", datetime(2026, 10, 6, 10, 0, 0, tzinfo=SERVER_TZ))
    ur.log_path = unreadable
    warned = []
    wh = type("W", (logging.Handler,), {"emit": lambda self, rr: warned.append(rr.getMessage())})(level=logging.WARNING)
    handle.log.addHandler(wh)
    try:
        ctx = handle._run_ctx(e, ur, handle._RunWatch(e))
    finally:
        handle.log.removeHandler(wh)
    check("log_text stays \"\" and log_unreadable is set", (ctx["log_text"], ctx.get("log_unreadable")), ("", True))
    check("one WARNING naming the run", len(warned) == 1 and ur.run_id in warned[0], True)
    ctx_ok = handle._run_ctx(e, r, handle._RunWatch(e))
    check("a readable log -> no log_unreadable key", "log_unreadable" in ctx_ok, False)


def _part_mc_runs_state_read_fails():  # noqa: C901
    """A failed read of state/machinecheck-runs.json never rewrites it from nothing.

Review of commit 28306025 (10-17), left open there:
  _hold_28's first read and _state_set's own read both fell back to {} when the read
  failed, so one failed read at the moment a hold was written rewrote the file with
  that one hold: every other held #28 FAIL was gone and never pushed (a lost alarm),
  and the seen lists (#6 / #24a) and miss counts (#7-miss, #28-miss) went with it.

Now a read that fails leaves the file as it was and is an ERROR; a hold that cannot
be kept is pushed at once and marked sent (#28|<run id>) once that push went out
(Result.after_push, called by judge), so an older entry of the same run on file is
not pushed again when its hold ends. Also a Windows sharing violation on os.replace:
the file stays as it was, nothing is left behind.

Since the 10-17 review (test_mc28.py) a read that fails once is tried
again (mc.LOCK_WAITS) and gets through, so the 「cannot be read」 cases here keep
failing on every try; a file that keeps reading as something other than a table is
copied aside and replaced.

    Formerly test_mc_runs_state_read_fails.py.
    """
    import json
    import logging
    import os


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                      ARK_AUTOMAS_DIR=str(TMP / "nowhere"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                      ARK_LOG_FILE=str(TMP / "relay.log"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import texts
    from ark_relay.features import machinecheck as mc
    from ark_relay.features import machinechecks as runs

    DAY = "2026-10-08"
    R1, R2, R3 = (f"{DAY}/endfield/MaaEnd-0{h}-00-00" for h in (1, 2, 3))
    REAL_READ_TEXT, REAL_REPLACE = Path.read_text, os.replace
    MC28 = texts.machinecheck_failed("#28", "")


    class Errors(logging.Handler):
        def __init__(self):
            super().__init__(logging.ERROR)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())


    ERRORS = Errors()
    runs._log_runs.addHandler(ERRORS)


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", alert=False, **kw):
            self.sent.append((title, body))
            return []


    class Rec:
        def __init__(self, rid):
            self.run_id, self.script, self.user = rid, "MaaEnd", "endfield"


    def entry(rid):
        return {"script": "MaaEnd", "user": "endfield", "day": DAY, "tasks": ["装备制造"],
                "evidence": f"{rid} 装备制造没做成", "covered": []}


    def fresh(*held):
        """A state folder whose machinecheck-runs.json holds `held` and the other keys."""
        state = tmpdir() / "state"
        state.mkdir()
        data = {runs.HELD_28: {rid: entry(rid) for rid in held}, "#7-miss": 2, "#28-miss": 1,
                "#6": ["a", "b"], "#24a": ["x"]}
        (state / runs.SEEN_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return state


    def marks():
        got = set()
        return got, (lambda day, key: (day, key) in got, lambda day, key: got.add((day, key)))


    def ctx(state, rid, alerted):
        return {"rec": Rec(rid), "held": [rid], "state_dir": state, "day": DAY, "alerted": alerted,
                "unverified_alarm": []}


    class read_fails:
        """Reads of machinecheck-runs.json fail `n` times with `exc` (a string: read as that text)."""

        def __init__(self, exc, n=1):
            self.exc, self.n = exc, n

        def __enter__(self):
            def _read(path, *a, **kw):
                if self.n and path.name == runs.SEEN_FILE:
                    self.n -= 1
                    if isinstance(self.exc, str):
                        return self.exc
                    raise self.exc
                return REAL_READ_TEXT(path, *a, **kw)
            Path.read_text = _read
            return self

        def __exit__(self, *a):
            Path.read_text = REAL_READ_TEXT


    class replace_locked:
        """os.replace onto machinecheck-runs.json fails as Windows does while another
    handle has it open (ERROR_SHARING_VIOLATION -> PermissionError)."""

        def __enter__(self):
            def _replace(src, dst, *a, **kw):
                if Path(dst).name == runs.SEEN_FILE:
                    raise PermissionError(13, "The process cannot access the file because it is "
                                              "being used by another process (test)")
                return REAL_REPLACE(src, dst, *a, **kw)
            os.replace = _replace
            return self

        def __exit__(self, *a):
            os.replace = REAL_REPLACE


    def raw(state):
        return (state / runs.SEEN_FILE).read_bytes()


    def held(state):
        return sorted(runs._state_get(state, runs.HELD_28) or {})


    def settle(state, alerted, notes):
        """settle_28 with every hold over; the run ids #28 pushed so far."""
        runs.settle_28(state, lambda script, user: True, lambda day: [], notes, alerted=alerted)
        return sorted(rid for rid in (R1, R2, R3) for t, b in notes.sent if t.startswith(MC28) and rid in b)


    def r28(state, rid, alerted):
        """_fail_28, then what judge does once the push went out (Result.after_push)."""
        r = runs._fail_28(ctx(state, rid, alerted), ["装备制造"], entry(rid)["evidence"])
        if r.after_push:
            r.after_push()
        return r


    class no_waits:
        """A lock that outlasts every wait, without the test sleeping through the waits."""

        def __enter__(self):
            self.was, mc.LOCK_WAITS = mc.LOCK_WAITS, (0.0, 0.0, 0.0)
            return self

        def __exit__(self, *a):
            mc.LOCK_WAITS = self.was


    mc.load()
    BAD_READS = [("OSError (Windows sharing violation on read)", PermissionError(13, "locked (test)")),
                 ("ValueError (broken JSON)", '{"#28-held": {'),
                 ("ValueError (UnicodeDecodeError)", UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"))]

    try:
        for name, exc in BAD_READS:
            print(f"\n[a hold is written while one read fails: {name}; R1, R2 held]")
            state = fresh(R1, R2)
            got, alerted = marks()
            ERRORS.lines.clear()
            with read_fails(exc) as rf:
                r = r28(state, R3, alerted)
            check("the read did fail", rf.n, 0)
            check("read again and held: R3 waits beside R1 and R2", (r.deferred, held(state)), (True, [R1, R2, R3]))
            check("…the other keys kept", (runs._state_get(state, "#6"), runs._state_get(state, "#28-miss")),
                  (["a", "b"], 1))
            check("…no ERROR, nothing marked", (ERRORS.lines, got), ([], set()))
            check("R1, R2 and R3 each reach the group once when their hold ends", settle(state, alerted, Notes()),
                  sorted([R1, R2, R3]))
            check("nothing of #28 is left waiting", held(state), [])

        print("\n[a hold is written while every read fails (a lock outlasting the waits); R1, R2 held]")
        state = fresh(R1, R2)
        before = raw(state)
        got, alerted = marks()
        ERRORS.lines.clear()
        with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=99):
            r = runs._fail_28(ctx(state, R3, alerted), ["装备制造"], entry(R3)["evidence"])
        check("machinecheck-runs.json is left as it was", raw(state) == before)
        check("R3 is a plain FAIL, pushed at once", (r.status, r.deferred), (mc.FAIL, False))
        check("…not marked sent before its push", got, set())
        r.after_push()
        check("…marked sent once it went out", got, {(DAY, f"#28|{R3}")})
        check("the failed read is an ERROR", any(runs.SEEN_FILE in x for x in ERRORS.lines))
        check("R1 and R2 still reach the group when their hold ends", settle(state, alerted, Notes()),
              sorted([R1, R2]))
        check("nothing of #28 is left waiting", held(state), [])

        print("\n[_state_set while every read fails: the other keys stay]")
        state = fresh(R1, R2)
        before = raw(state)
        with no_waits(), read_fails(OSError(5, "Input/output error (test)"), n=99):
            wrote = runs._state_set(state, "#7-miss", 3)
        check("not written", wrote, False)
        check("machinecheck-runs.json is left as it was", raw(state) == before)
        check("a later set keeps every other key", runs._state_set(state, "#7-miss", 3), True)
        data = json.loads(raw(state))
        check("…held FAILs, seen lists and counts", (sorted(data[runs.HELD_28]), data["#6"], data["#28-miss"],
                                                    data["#7-miss"]), (sorted([R1, R2]), ["a", "b"], 1, 3))

        print("\n[_mark_seen while every read fails: the seen list is not cut to the new ids]")
        state = fresh()
        with no_waits(), read_fails(OSError(5, "Input/output error (test)"), n=99):
            runs._mark_seen(state, "#6", ["c"])
        check("the list as it was", runs._state_get(state, "#6"), ["a", "b"])
        runs._mark_seen(state, "#6", ["c"])
        check("…and added to once it reads", runs._state_get(state, "#6"), ["a", "b", "c"])

        print("\n[the file keeps reading as something other than a table: copied aside, then replaced]")
        state = fresh(R1)
        before = raw(state)
        ERRORS.lines.clear()
        with no_waits(), read_fails('[]', n=99):
            wrote = runs._state_set(state, "#28-miss", 0)
        check("written, and that is one ERROR", (wrote, len([x for x in ERRORS.lines if runs.SEEN_FILE in x])),
              (True, 1))
        copies = [p for p in state.iterdir() if ".corrupt-" in p.name]
        check("what was there is kept in the copy", [p.read_bytes() == before for p in copies], [True])

        print("\n[R1 held already; judged again while every read fails: one push, not two]")
        state = fresh(R1, R2)
        got, alerted = marks()
        with no_waits(), read_fails(OSError(5, "Input/output error (test)"), n=99):
            r = r28(state, R1, alerted)
        check("R1 pushed at once", r.deferred, False)
        check("…so its hold ending pushes only R2", settle(state, alerted, Notes()), [R2])
        check("nothing of #28 is left waiting", held(state), [])

        print("\n[Windows: os.replace onto machinecheck-runs.json is refused (sharing violation)]")
        state = fresh(R1, R2)
        before = raw(state)
        got, alerted = marks()
        ERRORS.lines.clear()
        with no_waits(), replace_locked():
            r3 = r28(state, R3, alerted)
            r1 = r28(state, R1, alerted)
        check("machinecheck-runs.json is left as it was", raw(state) == before)
        check("no temp file left behind", sorted(p.name for p in state.iterdir()), [runs.SEEN_FILE])
        check("R3 and R1 are plain FAILs, pushed at once", (r3.deferred, r1.deferred), (False, False))
        check("…and marked sent", got, {(DAY, f"#28|{R3}"), (DAY, f"#28|{R1}")})
        check("each refused write is an ERROR", len([x for x in ERRORS.lines if "PermissionError" in x]), 2)
        notes = Notes()
        with no_waits(), replace_locked():
            first = settle(state, alerted, notes)
            second = settle(state, alerted, notes)
        check("while still locked: R2 pushed once over two ticks, R1 not again", (first, second), ([R2], [R2]))
        check("…both still on file", held(state), sorted([R1, R2]))
        third = settle(state, alerted, notes)
        check("unlocked: cleared without another push", (third, held(state)), ([R2], []))
    finally:
        Path.read_text, os.replace = REAL_READ_TEXT, REAL_REPLACE

    print()
    if fails:
        print(f"✗ {len(fails)} 条没过：{fails}")
        sys.exit(1)
    print("all checks passed")


def _part_mc_system():  # noqa: C901
    """Machine checks of the relay's own machinery (ark_relay/features/machinechecks.py).

The user, 2026-10-06 04:59: the machine must check the open ledger items by itself
after a deploy, instead of a person reading logs. Each check here gets a realistic
input that passes and a broken one that fails - and every FAIL is pushed to the
group (alert=True) - and the wiring at the natural point is driven for real: the
last boot stage reading the previous session of relay.log, unresolved.send, the
overrun check, the make-up, the MaaEnd pre-update, the watchdog, the desktop agent's
trace, the busy-snapshot note and the game-update stage. The relay.log lines below
have the shape __main__._setup_logging writes; their texts are the ones the modules
log (quoted next to each constant in system.py).

    Formerly test_mc_system.py.
    """
    import json
    import os
    import types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api", "win32con", "win32file",
                  "servicemanager", "win32process", "pythoncom"):
        sys.modules.setdefault(_name, _Stub(_name))

    import boot_stages
    from ark_relay.features import machinecheck as mc
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import machinechecks as sysmc


    class N:
        """A notifier that keeps what was sent; with `copies`, it also writes the alarm
    copy the way notify.Notifier does for a delivered group alarm (alertlog)."""

        def __init__(self, copies=True):
            self.sent = []
            self.copies = copies
            self.state_dir = None

        def send(self, title, body="", alert=False, **kw):
            self.sent.append((title, body, alert))
            if self.copies and alert and self.state_dir:
                from ark_relay.features import errwatch as alertlog
                alertlog.AlertLog(self.state_dir).record(title, body)
            return []

        def alert_log(self):
            return None

        def fails(self, cid):
            return [b for t, b, a in self.sent if t.startswith(f"🔬 上机核对没过：{cid} ") and a]


    NOW = datetime(2026, 10, 7, 8, 50, tzinfo=SERVER_TZ)


    def judge(event, ctx, d, n=None):
        n = n or N()
        got = dict(mc.judge(d, event, ctx, notifier=n, now=NOW))
        return got, n


    def logline(stamp, msg, level="INFO", name="ark.service", more=()):
        return "\n".join([f"{stamp} {level:<7} {name}  {msg}", *more])


    START = "服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）"
    MARK = "中继代码版本 v20261006120000"
    BOOT_NOW = [logline("10-07 08:46:10", START), logline("10-07 08:46:10", MARK)]


    def write_log(lines):
        d = tmpdir()
        f = d / "relay.log"
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return d, f


    def at_boot(lines, d=None):
        """Judge the boot event against a relay.log made of `lines` (then this boot)."""
        sd, f = write_log(list(lines) + BOOT_NOW)
        sd = d or sd
        got, n = judge("boot", {"log_file": str(f)}, sd)
        return got, n, sd, f


    EVENING = [
        logline("10-06 21:20:05", START), logline("10-06 21:20:05", MARK),
        logline("10-06 21:20:40", "📱 已上报状态到手机（开机；今天 ntfy 已用 12 条）"),
        logline("10-06 21:58:01", "📱 已上报状态到手机（关机前；今天 ntfy 已用 20 条）"),
        logline("10-06 21:58:03", "本轮已处理完毕，60 秒后关机", name="ark.engine"),
        logline("10-06 21:59:04", "中继自己发出了关机命令，AUTO-MAS 后台此时退出（退出码 0x1），按关机处理，不算故障，不再重新打开它"),
        logline("10-06 21:59:05", "收到停止通知（Windows 关机）"),
        logline("10-06 21:59:05", "收到停止信号，退出"),
        logline("10-06 21:59:09", "📱 已上报状态到手机（停止前；今天 ntfy 已用 21 条）"),
        logline("10-06 21:59:09", "主流程已返回，向 SCM 报告已停止；还活着的线程：phone-heartbeat"),
    ]

    print("[#11 停服务时推最后一份状态：上一段日志里收到停止通知，停止前那份送到了 → 过]")
    got, n, sd, f = at_boot(EVENING)
    check("#11 过了", got["#11"].status, mc.PASS)
    check("依据是停止通知和送达那一行", got["#11"].evidence,
          "10-06 21:59:05 收到停止通知（Windows 关机）；10-06 21:59:09 📱 已上报状态到手机（停止前；今天 ntfy 已用 21 条）")
    again, n2 = judge("boot", {"log_file": str(f)}, sd)
    check("下次开机读到的还是同一段：不再判", "#11" in again, False)

    print("[#11 停止前那份没送出去（日志说了原因）→ 没过，进群]")
    bad = [x if "停止前；" not in x else logline("10-06 21:59:09", "状态没能上报到手机（停止前）：COS 403；手机上留着上一份状态",
                                             level="WARNING") for x in EVENING]
    got, n, _, _ = at_boot(bad)
    check("#11 没过", got["#11"].status, mc.FAIL)
    check("推了一条，带原因", any("COS 403" in b for b in n.fails("#11")), True)

    print("[#11 关机前那份已送到，看门服务代发的停止前那份没发完 → 照样没过（发失败本身就是要看的毛病）]")
    # The watchdog's own failure line, verbatim from relay.log 10-11 15:42:28. The page holds
    # the 关机前 state, but a stop push that failed is a fault of the push path the next
    # shutdown needs, so it is not covered by the 关机前 fallback (only a stop push that
    # left no line at all is: the case below). No such session is on record (10-11 15:42
    # had no 关机前 push); this pins the order of the checks in _stop_push.
    dog = [x if "停止前；" not in x else logline(
               "10-06 21:59:40", "状态没能上报到手机（停止前）：看门服务等了 35 秒还没发完，Windows 要关机了不再等；手机上留着上一份状态",
               level="WARNING", name="ark.app.stop_push") for x in EVENING]
    got, n, _, _ = at_boot(dog)
    check("#11 没过", got["#11"].status, mc.FAIL)
    check("依据是看门服务那一行", "看门服务等了 35 秒还没发完" in got["#11"].evidence, True)

    print("[#11 中继自己关机时停止前那份没来得及，关机前那份已送到 → 过，写明]")
    cut = [x for x in EVENING if "停止前；" not in x and "主流程已返回" not in x]
    got, n, _, _ = at_boot(cut)
    check("#11 过了", got["#11"].status, mc.PASS)
    check("说的是关机前那份", "关机前那份已送到" in got["#11"].evidence, True)

    print("[#11 不是中继关的机（手动关机），停止前那份没出来 → 没过]")
    manual = [x for x in cut if "关机前；" not in x and "60 秒后关机" not in x and "此时退出" not in x]
    got, n, _, _ = at_boot(manual)
    check("#11 没过", got["#11"].status, mc.FAIL)
    check("说中继先停下了", "中继先停下了" in got["#11"].evidence, True)

    print("[#11 上一个进程没收到停止通知就没了（Windows 关机没通知到中继）→ 没过]")
    died = EVENING[:4]
    got, n, _, _ = at_boot(died)
    check("#11 没过", got["#11"].status, mc.FAIL)
    check("依据是那一段的最后一行", got["#11"].evidence.endswith("10-06 21:58:01 📱 已上报状态到手机（关机前；今天 ntfy 已用 20 条）"), True)

    print("[#11 上一段没写出版本那一行就没了（刚起就崩）→ 照判（审计 11-08 C-13：以前当老代码跳过）；自更新那一段跳过，判再前一段]")
    early = [logline("10-07 08:45:50", START)]
    got, n, _, _ = at_boot(EVENING + early)
    check("刚起就崩的那一段：判了，没过", got["#11"].status, mc.FAIL)
    check("……依据是它仅有的那一行", "服务模式启动" in got["#11"].evidence, True)
    old = [x for x in EVENING if MARK not in x]
    got, _, _, _ = at_boot(old)
    check("没有版本那一行、别的都在的一段：照常判", got["#11"].status, mc.PASS)
    selfupd = [logline("10-07 08:45:50", START), logline("10-07 08:45:50", MARK),
               logline("10-07 08:46:01", "代码已更新，重启以立即生效: ark_relay/core/engine.py")]
    got, _, _, _ = at_boot(EVENING + selfupd)
    check("跳过自更新那一段，判前一晚", got["#11"].evidence.startswith("10-06 21:59:05"), True)

    print("[#11 安装版自更新那一段（app_main 的写法）也跳过，不当成「没收到停止通知就没了」]")
    import app_main
    pkg_upd = [logline("10-07 08:45:50", START), logline("10-07 08:45:50", MARK),
               logline("10-07 08:46:01", f"{app_main.SELF_UPDATE_LINE}: ark_relay/core/engine.py", name="ark.app")]
    got, n, _, _ = at_boot(EVENING + pkg_upd)
    check("跳过安装版自更新那一段，判前一晚", got["#11"].evidence.startswith("10-06 21:59:05"), True)
    check("没进群", len(n.fails("#11")), 0)
    # The same log is what a forced shutdown leaves when it comes between the update and the
    # restarted relay's first line: the updating session is skipped all the same.

    print("[#11 的标题不再写「停服务」：安装版没有服务了，标题和日报样例都按中继说]")
    check("#11 标题", "停服务" in mc.CHECKS["#11"].what, False)
    check("日报样例", "停服务" in (Path(__file__).resolve().parents[1] / "ark_relay" / "core" / "texts.py")
          .read_text(encoding="utf-8"), False)
    _ops = (Path(__file__).resolve().parents[2] / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    check("文档核对查的是安装版的看门服务和计划任务，不是已停用的老服务",
          ("<!-- check: svc ark-relay -->" in _ops, "<!-- check: task ark-relay -->" in _ops,
           "<!-- check: svc ArkRelayWatchdog -->" in _ops, "<!-- check: task \\ArkRelay\\main -->" in _ops),
          (False, False, True, True))

    print("\n[#37/#38 中继自己关机后：后台退出按关机处理、没去重开 → 都过]")
    got, n, _, _ = at_boot(EVENING)
    check("#37 过了", got["#37"].status, mc.PASS)
    check("#37 依据是「按关机处理」那一行", "按关机处理，不算故障" in got["#37"].evidence, True)
    check("#38 过了", got["#38"].status, mc.PASS)
    print("[#37/#38 关机后后台「意外退出」、中继去重开 → 都没过，进群]")
    broke = EVENING[:5] + [
        logline("10-06 21:59:04", "AUTO-MAS 后台意外退出了（退出码 0x1，窗口也没了，当时机器没在关机，也没在装更新）；重新起来了写进日报，查 3 次还没起来报到群里"),
        logline("10-06 21:59:04", "AUTO-MAS 没在运行，中继正在重新打开它（第 1 次）"),
    ] + EVENING[6:]
    got, n, _, _ = at_boot(broke)
    check("#37 没过", got["#37"].status, mc.FAIL)
    check("#38 没过", got["#38"].status, mc.FAIL)
    check("两条都推了", (len(n.fails("#37")), len(n.fails("#38"))), (1, 1))
    check("#38 依据是重开那一行", "中继正在重新打开它" in got["#38"].evidence, True)
    print("[#38 关机被人取消（系统事件 1075）后机器开着，中继去重开调度程序 → 过（10-24 21:36 报警 4074ce7d）]")
    cancelled = EVENING[:6] + [
        logline("10-06 21:59:08", "不关机：关机命令 21:58 发出后，21:59:07 被取消了（系统事件 1075），中继不会再自己关机", name="ark.shutdown"),
        logline("10-06 22:09:40", "AUTO-MAS 没在运行，中继正在重新打开它（第 1 次）", level="WARNING"),
    ] + EVENING[6:]
    got, n, _, _ = at_boot(cancelled)
    check("#38 过了", got["#38"].status, mc.PASS)
    check("#38 依据写到关机被取消", "关机被取消" in got["#38"].evidence, True)
    check("没进群", len(n.fails("#38")), 0)
    print("[#38 关机取消之前就去重开 → 照样没过]")
    early = EVENING[:5] + [
        logline("10-06 21:58:30", "AUTO-MAS 没在运行，中继正在重新打开它（第 1 次）", level="WARNING"),
        logline("10-06 21:59:08", "不关机：关机命令 21:58 发出后，21:59:07 被取消了（系统事件 1075），中继不会再自己关机", name="ark.shutdown"),
    ] + EVENING[6:]
    got, n, _, _ = at_boot(early)
    check("#38 没过", got["#38"].status, mc.FAIL)
    got, _, _, _ = at_boot(manual)
    check("不是中继关的机：#37/#38 不判", ("#37" in got, "#38" in got), (False, False))

    print("\n[#59 系统的程序启动通知断了又自己订上：报群一次（或期间已报过群、这一行记成自己好了），diag 说出是哪种]")
    # Since 324b640b (2026-10-10) a drop of unknown cause that came back by itself is pushed
    # to the group once (procwatch._subscribed: no errwatch.recovered() unless the outage was
    # already pushed meanwhile). The lines are the machine's: relay.log 10-06 16:16:59 and
    # 18:08:22 (the day replay's 2026-10-06 events.jsonl lines 215 and 288), two drops with
    # the same words on one day; the push text is errwatch's (texts.relay_error_body).
    WMI = "系统的程序启动通知断过 15 秒（远程过程调用失败，0x800706BE），已经自己重新订上"
    DIAG = ("diag: hresult 0x80020009, scode 0x800706BE, source SWbemEventSource, text 远程过程调用失败。; "
            "subscription up 18.3 s, 0 events, last -; relay up 37 s; machine up 0:29:01; "
            "WMI hosts at subscribe [winmgmt pid 3560; WmiPrvSE pids 3836] now [winmgmt pid 2596; WmiPrvSE pids 6280]; "
            "hypothesis: H1 WMI service restarted (winmgmt pid 3560 -> 2596)")
    WMI_HELD = ("系统的程序启动通知断过 640 秒（远程过程调用失败，0x800706BE），已经自己重新订上（期间报过群）")
    wmi_session = EVENING[:3] + [logline("10-06 21:25:00", WMI, level="WARNING", more=[DIAG])] + EVENING[3:]


    def errkinds(sd, line, recovered=True):
        (sd / "errkinds").mkdir(parents=True, exist_ok=True)
        (sd / "errkinds" / "2026-10-06.json").write_text(json.dumps(
            {"ark.service|x": {"first": "2026-10-06 21:25:00", "count": 1, "pushed": 0 if recovered else 1,
                               "level": "WARNING", "where": "ark.service", "line": line,
                               **({"recovered": True} if recovered else {})}},
            ensure_ascii=False), encoding="utf-8")


    def pushed(sd, *hms):
        (sd / "alerts").mkdir(exist_ok=True)
        with (sd / "alerts" / "20261006.jsonl").open("a", encoding="utf-8") as f:
            for at in hms:
                f.write(json.dumps({"ts": f"2026-10-06 {at}", "title": "🩺 中继自己报错了",
                                    "text": f"中继自己报错了（{at}），出在「主程序」。它说：{WMI}\n已交给我们这边去修。"},
                                   ensure_ascii=False) + "\n")


    sd, f = write_log(wmi_session + BOOT_NOW)
    errkinds(sd, WMI, recovered=False)
    pushed(sd, "21:25:00")
    got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
    check("报群一次（324b640b 的做法）→ 过了", got["#59"].status, mc.PASS)
    check("说出原因（H1）", got["#59"].evidence.endswith("原因：WMI 服务自己重启过"), True)
    check("过了不再推 🔬", n.fails("#59"), [])
    sd, f = write_log(wmi_session + BOOT_NOW)
    errkinds(sd, WMI, recovered=False)
    pushed(sd, "16:16:59", "21:25:00")
    got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
    check("同一天前一次同样的话报过群，不算这一次报了两次", got["#59"].status, mc.PASS)
    sd, f = write_log(wmi_session + BOOT_NOW)
    errkinds(sd, WMI, recovered=False)
    pushed(sd, "21:25:00", "21:25:00")
    got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
    check("同一次报了两次群 → 没过", (got["#59"].status, "2 次" in got["#59"].evidence), (mc.FAIL, True))
    sd, f = write_log(wmi_session + BOOT_NOW)
    errkinds(sd, WMI, recovered=False)
    got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
    check("没报群也没记成自己好了 → 没过", (got["#59"].status, "没进群" in got["#59"].evidence), (mc.FAIL, True))
    held = EVENING[:3] + [logline("10-06 21:25:00", WMI_HELD, level="WARNING", more=[DIAG])] + EVENING[3:]
    sd, f = write_log(held + BOOT_NOW)
    errkinds(sd, WMI_HELD)
    got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
    check("期间已报过群、这一行记成自己好了、不再报 → 过了", got["#59"].status, mc.PASS)
    sd, f = write_log(held + BOOT_NOW)
    errkinds(sd, WMI_HELD)
    (sd / "alerts").mkdir()
    (sd / "alerts" / "20261006.jsonl").write_text(json.dumps(
        {"ts": "2026-10-06 21:25:01", "title": "🩺 中继自己报错了",
         "text": f"中继自己报错了（21:25:00），出在「主程序」。它说：{WMI_HELD}"}, ensure_ascii=False) + "\n", encoding="utf-8")
    got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
    check("记成自己好了却又进了群（一个故障两次）→ 没过", (got["#59"].status, "进了群" in got["#59"].evidence), (mc.FAIL, True))
    old_diag = DIAG.split("; hypothesis:")[0]
    sd, f = write_log(EVENING[:3] + [logline("10-06 21:25:00", WMI, level="WARNING", more=[old_diag])] + EVENING[3:] + BOOT_NOW)
    errkinds(sd, WMI, recovered=False)
    pushed(sd, "21:25:00")
    got, n = judge("boot", {"log_file": str(f), "now": NOW}, sd)
    check("diag 说不出是哪种 → 没过，原样带上 diag", (got["#59"].status, "WMI hosts at subscribe" in got["#59"].evidence),
          (mc.FAIL, True))
    got, _, _, _ = at_boot(EVENING)
    check("没断过：不判", "#59" in got, False)

    print("\n[#63 开机后 state.json 里没有 maaend_disabled_spmed 了 → 过；还在 → 没过]")
    from ark_relay.core.statestore import StateStore
    sd = tmpdir()
    got, n = judge("boot", {}, sd)
    check("#63 过了", got["#63"].status, mc.PASS)
    StateStore(sd).set("updates", "maaend_disabled_spmed", {"tasks": ["AutoUseSpMedication"], "since": "2026-09-03"})
    got, n = judge("boot", {}, sd)
    check("#63 没过", got["#63"].status, mc.FAIL)
    check("依据带那条记录", "AutoUseSpMedication" in got["#63"].evidence, True)
    check("推了", len(n.fails("#63")), 1)

    print("\n[#14 往返核对：机器核不了，写明原因]")
    check("#14 在核不了的单子上", "#14" in mc.CANNOT, True)
    check("原因一句话", "机器自己从不改它" in mc.CANNOT["#14"][1], True)

    print("\n[#18 调度程序开着非自动代理的任务：快照算在忙 → 过；算不忙 → 没过；判过的不再判]")
    sd = tmpdir()
    (sd / sysmc.BUSY_FILE).write_text(json.dumps({"seen": [
        {"at": "10-06 20:01:02", "task": "ab12", "mode": "ScriptConfig", "busy": True, "line": "快照里列着、没完成：MAA 运行"}]},
        ensure_ascii=False), encoding="utf-8")
    got, _ = judge("boot", {}, sd)
    check("#18 过了", got["#18"].status, mc.PASS)
    got, _ = judge("boot", {}, sd)
    check("判过的不再判", "#18" in got, False)
    (sd / sysmc.BUSY_FILE).write_text(json.dumps({"seen": [
        {"at": "10-06 20:05:00", "task": "cd34", "mode": "ScriptConfig", "busy": False, "line": "调度程序日志 20:04:10 创建任务 cd34"}]},
        ensure_ascii=False), encoding="utf-8")
    got, n = judge("boot", {}, sd)
    check("#18 没过，推了", (got["#18"].status, len(n.fails("#18"))), (mc.FAIL, 1))

    print("\n[#21/#34 报警真的进了群（报警抄送里有这一条）→ 过；抄送里没有 → 没过]")
    for cid, kind in (("#21", "手动"), ("#34", "未解决")):
        sd = tmpdir()
        n = N()
        n.state_dir = sd
        title, body = "❌ 明日方舟早班没跑成", f"{'这一趟是有人在 AUTO-MAS 上手动开的，不是定时开的。' if kind == '手动' else ''}卡在 开始唤醒"
        n.send(title, body, alert=True)
        ctx = {"kind": kind, "run_id": "2026-10-06/arknights/MAA-09-05-00", "title": title, "body": body,
               "sent": True, "copies": True}
        got, _ = judge("unresolved", ctx, sd)
        check(f"{cid} 过了", got[cid].status, mc.PASS)
        got, n2 = judge("unresolved", ctx, tmpdir())
        check(f"{cid} 抄送里没有：没过，推了", (got[cid].status, len(n2.fails(cid))), (mc.FAIL, 1))
        got, _ = judge("unresolved", dict(ctx, copies=False), tmpdir())
        check(f"{cid} 发送方不留抄送：不判", cid in got, False)
    got, _ = judge("unresolved", {"kind": "理智", "run_id": "x", "title": "t", "body": "b", "sent": True, "copies": True}, tmpdir())
    check("别的种类不归 #21/#34", ("#21" in got, "#34" in got), (False, False))

    print("\n[#55 班次超时：有人手动开的不报 → 过；报的是班次自己的 → 过；日志里找不到是谁开的 → 没过]")
    base = {"kind": "队列超时", "queue": "晚班", "hhmm": "21:30", "task_id": "68b6e221"}
    got, _ = judge("unresolved", dict(base, alarmed=False, create="10-03 00:19:50 创建任务 68b6e221，模式 AutoProxy，触发来源 manual_task"), tmpdir())
    check("#55 手动的没报：过", got["#55"].status, mc.PASS)
    got, _ = judge("unresolved", dict(base, alarmed=True, sent=True, create="09-25 21:30:00 创建任务 e715210d，模式 AutoProxy，触发来源 scheduled_task"), tmpdir())
    check("#55 班次自己的报了：过", got["#55"].status, mc.PASS)
    got, n = judge("unresolved", dict(base, alarmed=True, sent=True, create=""), tmpdir())
    check("#55 找不到是谁开的：没过，推了", (got["#55"].status, len(n.fails("#55"))), (mc.FAIL, 1))

    print("\n[#31 看门狗结束 MaaEnd：进程表里没了 → 过；还在 / 结束不了 / 读不到 → 没过]")
    res = {"pid": 30000, "reason": "插件崩溃", "ok": True, "why": "", "gone": True, "waited": 30}
    got, _ = judge("watchdog", {"action": "kill", "result": res}, tmpdir())
    check("#31 过了", got["#31"].status, mc.PASS)
    for label, extra in (("还在", {"gone": False}), ("结束不了", {"ok": False, "gone": False, "why": "退出码 128"}),
                         ("读不到", {"gone": None})):
        got, n = judge("watchdog", {"action": "kill", "result": dict(res, **extra)}, tmpdir())
        check(f"#31 {label}：没过，推了", (got["#31"].status, len(n.fails("#31"))), (mc.FAIL, 1))
    print("\n[#32 关机前补跑采集路线：跑出结论 → 过；没结论 → 没过]")
    done = {"routes": ["AutoCollectRoute15", "AutoCollectRoute16"], "passed": ["AutoCollectRoute16"],
            "failed": ["AutoCollectRoute15"], "unknown": [], "note": "",
            "nodes": {"AutoCollectRoute16": "[2026-10-06 21:40:01.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute16End\"}"}}
    labels = {"AutoCollectRoute15": "路线15：红矛叶", "AutoCollectRoute16": "路线16：协议纹石"}
    got, _ = judge("makeup", {"kind": "采集路线", "result": done, "labels": labels}, tmpdir())
    check("#32 过了", got["#32"].status, mc.PASS)
    check("依据带 maafw.log 那一行", "AutoCollectRoute16End" in got["#32"].evidence, True)
    got, n = judge("makeup", {"kind": "采集路线", "result": dict(done, unknown=["AutoCollectRoute15"],
                                                               note="MaaEnd 起来 60 秒了还不响应"), "labels": labels}, tmpdir())
    check("#32 没结论：没过，推了", (got["#32"].status, len(n.fails("#32"))), (mc.FAIL, 1))

    from ark_relay.features import collect_retry as cr
    maafw = ("[2026-10-06 21:20:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15End\"}\n"
             "[2026-10-06 21:40:01.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute16End\"}\n"
             "[2026-10-06 21:41:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15Failed\"}\n")
    nodes = cr.node_lines(maafw, ["AutoCollectRoute15", "AutoCollectRoute16"], "2026-10-06 21:30:00")
    check("补跑判结论用的那几行 maafw.log 留下来（窗口之前那次不算）",
          {k: v.split('"name":"')[1][:-2] for k, v in nodes.items()},
          {"AutoCollectRoute15": "AutoCollectRoute15Failed", "AutoCollectRoute16": "AutoCollectRoute16End"})

    print("\n[#33 补跑：派下去、记录落地 → 过；没跑出记录 / 没跑成 → 没过；按规矩不补 → 不判]")
    ent = {"result": "ok", "record": "2026-10-06/endfield/MaaEnd-14-02-11", "dispatched_at": "2026-10-06T14:01:30+08:00"}
    got, _ = judge("makeup", {"kind": "补跑", "script": "MaaEnd", "result": ent}, tmpdir())
    check("#33 走通：过", got["#33"].status, mc.PASS)
    got, _ = judge("makeup", {"kind": "补跑", "script": "MaaEnd", "result": dict(ent, result="failed", note="基质刷取")}, tmpdir())
    check("#33 补跑也没成（但跑了）：过", got["#33"].status, mc.PASS)
    got, n = judge("makeup", {"kind": "补跑", "script": "MaaEnd", "result": {"result": "no_record", "dispatched_at": ent["dispatched_at"]}}, tmpdir())
    check("#33 没跑出记录：没过，推了", (got["#33"].status, len(n.fails("#33"))), (mc.FAIL, 1))
    got, _ = judge("makeup", {"kind": "补跑", "script": "MaaEnd", "result": {"result": "gave_up", "note": "找不到终末地的母本"}}, tmpdir())
    check("#33 没跑成：没过", got["#33"].status, mc.FAIL)
    got, _ = judge("makeup", {"kind": "补跑", "script": "MAA", "result": {"result": "gave_up", "note": "不补跑：调试模式开着"}}, tmpdir())
    check("#33 按规矩不补：不判", "#33" in got, False)

    print("\n[#65 明日方舟没进游戏、记录上却没有 maa_unreachable（旧版记的账或两边判断走散）→ 没过，带上存下的日志；同一条只判一次]")
    sd = tmpdir()
    cap = {"gui": 3, "asst": 2, "path": "state/machinecheck/maa-not-started/x.log", "last": "[2026-10-06 09:05:30][ERR] 连接失败"}
    ctx = {"kind": "没进游戏", "script": "MAA", "run_id": "2026-10-06/arknights/MAA-09-05-00", "failed": "开始唤醒", "captured": cap}
    got, n = judge("makeup", ctx, sd)
    check("#65 没过，推了", (got["#65"].status, len(n.fails("#65"))), (mc.FAIL, 1))
    check("依据带存下的日志路径和最后一行", ("x.log" in got["#65"].evidence, "连接失败" in got["#65"].evidence), (True, True))
    got, _ = judge("makeup", ctx, sd)
    check("同一条不再判", "#65" in got, False)
    got, _ = judge("makeup", dict(ctx, run_id="2026-10-06/arknights/MAA-21-30-00", written=True), sd)
    check("写了 maa_unreachable：过", got["#65"].status, mc.PASS)

    print("\n[#60 桌面助手：找不到窗口传回 focus_missing、不点；两个字整行才点]")
    agent_missing = {"what": "agent", "focus": "Games", "acts": ["ocr"], "clicks": False, "focus_missing": True,
                     "log": ["focus: 没有 Games 的窗口", "ocr 3 行"], "clicked": []}
    click_ok = {"what": "agent", "focus": "Endfield", "acts": ["click_text"], "text": "确认", "clicks": True,
                "focus_missing": False, "log": ["focus: Endfield 「Endfield」", "click_text: 点了「确认」", "click 960,700"],
                "clicked": [[960, 700]]}
    got, _ = judge("gameupdate", {"screens": [agent_missing, click_ok]}, tmpdir())
    check("#60 过了", got["#60"].status, mc.PASS)
    old_agent = dict(agent_missing, focus_missing=False)
    got, n = judge("gameupdate", {"screens": [old_agent]}, tmpdir())
    check("#60 没传回 focus_missing：没过，推了", (got["#60"].status, len(n.fails("#60"))), (mc.FAIL, 1))
    clicked_anyway = dict(agent_missing, acts=["click_text"], clicks=True, text="更新游戏", clicked=[[1, 2]])
    got, _ = judge("gameupdate", {"screens": [clicked_anyway]}, tmpdir())
    check("#60 找不到窗口还点了：没过", got["#60"].status, mc.FAIL)
    wrong_line = dict(click_ok, log=["click_text: 点了「确认更新」"])
    got, _ = judge("gameupdate", {"screens": [wrong_line]}, tmpdir())
    check("#60 两个字点到别的行：没过", got["#60"].status, mc.FAIL)
    got, _ = judge("gameupdate", {"screens": [dict(click_ok, log=["click 960,700"])]}, tmpdir())
    check("#60 没说点的是哪行：没过", got["#60"].status, mc.FAIL)

    print("\n[#61 启动器下载时屏上的字：认出「正在下载」→ 过；等待中一个也认不出、或连着 3 帧认不出 → 没过]")
    waiting = {"what": "launcher", "game": "终末地", "stage": "wait", "unread": "", "busy": "正在下载", "ready": False,
               "line": "正在下载 1.2GB/8.5GB", "dump": "正在下载 1.2GB/8.5GB / 暂停", "shot": "shot-1.png"}
    got, _ = judge("gameupdate", {"screens": [waiting]}, tmpdir())
    check("#61 过了", got["#61"].status, mc.PASS)
    unknown = dict(waiting, busy="", line="", dump="版本更新公告 / 活动")
    got, n = judge("gameupdate", {"screens": [unknown, unknown]}, tmpdir())
    check("#61 等待中一个也认不出：没过，推了", (got["#61"].status, len(n.fails("#61"))), (mc.FAIL, 1))
    got, n = judge("gameupdate", {"screens": [waiting, unknown, unknown, unknown]}, tmpdir())
    check("#61 连着 3 帧认不出：没过，推了", (got["#61"].status, len(n.fails("#61"))), (mc.FAIL, 1))
    got, n = judge("gameupdate", {"screens": [waiting, unknown, waiting]}, tmpdir())
    check("#61 夹在中间的一帧认不出：过了，不推", (got["#61"].status, len(n.fails("#61"))), (mc.PASS, 0))


    print("\n[#64 终末地公告读不到：报警进了群 → 过；抄送里没有 → 没过]")
    sd = tmpdir()
    n = N()
    n.state_dir = sd
    probs = ["终末地：官方公告读不到，今天有没有版本更新不知道"]
    title, body = "⚠️ 游戏更新有 1 项没能确认", "· " + probs[0]
    n.send(title, body, alert=True)
    gctx = {"problems": probs, "title": title, "body": body, "sent": True, "copies": True}
    got, _ = judge("gameupdate", gctx, sd)
    check("#64 过了", got["#64"].status, mc.PASS)
    got, n2 = judge("gameupdate", gctx, tmpdir())
    check("#64 抄送里没有：没过，推了", (got["#64"].status, len(n2.fails("#64"))), (mc.FAIL, 1))
    got, _ = judge("gameupdate", dict(gctx, problems=["鸣潮：官方公告读不到，今天是不是维护日不知道"]), sd)
    check("别的问题不归 #64", "#64" in got, False)

    # ------------------------------------------------------------------ wiring

    print("\n[接线：最后一个开机步骤读上一段 relay.log 判 #11/#37/#38/#63]")
    sd, f = write_log(EVENING + BOOT_NOW)
    n = N()
    cfg = types.SimpleNamespace(state_dir=sd)
    saved_env = os.environ.get("ARK_LOG_FILE")
    os.environ["ARK_LOG_FILE"] = str(f)
    try:
        boot_stages._stage_machinecheck(cfg, n, boot_stages.log)
    finally:
        if saved_env is None:
            os.environ.pop("ARK_LOG_FILE", None)
        else:
            os.environ["ARK_LOG_FILE"] = saved_env
    rows = mc.read(sd)
    check("记进了 machinecheck.json", {k: rows.get(k, {}).get("status") for k in ("#11", "#37", "#38", "#63")},
          {"#11": "PASS", "#37": "PASS", "#38": "PASS", "#63": "PASS"})
    check("事件是开机", rows.get("#11", {}).get("event"), "boot")
    src = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
    check("开机写那一行的字和核对认的字一样", f'log.info("{sysmc.CODE_MARK} v%s"' in src, True)
    check("service.main 最后跑这一步", "boot_stages._stage_machinecheck(cfg, notifier, log)\n        _loop(" in
          (Path(__file__).resolve().parents[1] / "service.py").read_text(encoding="utf-8"), True)

    print("\n[接线：unresolved.send 推出去后判 #21/#34（真抄送）]")
    from ark_relay.core import engine as eng_mod
    from ark_relay.features import handle as unresolved
    from ark_relay.core.config import Config
    from ark_relay.core.ledger import State


    class Src:
        def fetch(self, seen):
            return []


    def engine(sd, n):
        cfg = Config()
        cfg.state_dir = sd
        cfg.automas_dir = None
        return eng_mod.Engine(cfg, source=Src(), state=State(sd), notifier=n)


    sd = tmpdir()
    n = N()
    n.state_dir = sd
    e = engine(sd, n)
    unresolved.send(e, "2026-10-06", "手动", "2026-10-06/arknights/MAA-01-02-03", "❌ 明日方舟晚班没跑成",
                    "这一趟是有人在 AUTO-MAS 上手动开的，不是定时开的。\n卡在 开始唤醒")
    check("#21 记了过", mc.read(sd).get("#21", {}).get("status"), "PASS")
    sd = tmpdir()
    n = N(copies=False)
    e = engine(sd, n)
    unresolved.send(e, "2026-10-06", "未解决", "2026-10-06/arknights/MAA-09-05-00", "❌ 明日方舟早班没跑成", "补跑也没成")
    check("#34 抄送里没有：记了没过", mc.read(sd).get("#34", {}).get("status"), "FAIL")
    check("…并且进群", len(n.fails("#34")), 1)

    print("\n[接线：班次超时检查——有人手动开的任务不报，#55 记过（依据是 app.log 那一行）]")
    from ark_relay.features import runwatch
    sd = tmpdir()
    automas = tmpdir()
    (automas / "debug").mkdir()
    (automas / "debug" / "app.log").write_text(
        "2026-10-03 00:19:50.991 | INFO     | 业务调度 | 创建任务: 68b6e221-419d-444b-aff7-8643822c64ce, 模式: AutoProxy, 触发来源: manual_task\n",
        encoding="utf-8")
    n = N()
    e = engine(sd, n)
    e.cfg.automas_dir = automas
    q = {"name": "晚班", "uid": "q-evening"}
    saved = runwatch.overrun_moments
    runwatch.overrun_moments = lambda eng, now: iter([(q, "21:30", "q-evening", datetime(2026, 10, 2, 21, 30, tzinfo=SERVER_TZ),
                                                       19, datetime(2026, 10, 2, 22, 19, tzinfo=SERVER_TZ), 7)])
    try:
        runwatch.check_overrun(e, datetime(2026, 10, 3, 0, 43, tzinfo=SERVER_TZ), {"tasks": [
            {"taskId": "68b6e221-419d-444b-aff7-8643822c64ce", "queueId": "q-evening", "mode": "AutoProxy",
             "task_info": [{"name": "MAA", "status": "运行"}]}]})
    finally:
        runwatch.overrun_moments = saved
    check("没报超时", [t for t, _, a in n.sent if a], [])
    row = mc.read(sd).get("#55", {})
    check("#55 记了过", row.get("status"), "PASS")
    check("依据是 app.log 的 manual_task 那一行", "触发来源 manual_task" in row.get("evidence", ""), True)

    print("\n[接线：明日方舟没进游戏、记录上没有 maa_unreachable → 存下 MAA 自己的 gui.log / asst.log 那一段，#65 没过并进群，同一条只一次（写了标记的真样本见 test_maa_unreachable.py）]")
    from ark_relay.features import makeup
    from ark_relay.core.config import RunRecord
    sd = tmpdir()
    maa = tmpdir()
    (maa / "debug").mkdir()
    (maa / "debug" / "gui.log").write_text("[2026-10-06 08:00:00][INF] 早上那趟\n[2026-10-06 09:05:10][INF] 开始唤醒\n"
                                           "[2026-10-06 09:05:40][ERR] 连接模拟器失败\n", encoding="utf-8")
    (maa / "debug" / "asst.log").write_text("[2026-10-06 09:05:12.100][INF] Connect\n  continued line\n"
                                            "[2026-10-06 09:20:00.000][INF] 下一趟\n", encoding="utf-8")
    n = N()
    e = engine(sd, n)
    e.cfg.maa_dir = maa
    rec = RunRecord(run_id="2026-10-06/arknights/MAA-09-05-00", script="MAA", user="arknights",
                    started=datetime(2026, 10, 6, 9, 5, tzinfo=SERVER_TZ), finished=datetime(2026, 10, 6, 9, 6, tzinfo=SERVER_TZ),
                    ok=False, failed_tasks=["开始唤醒"])
    makeup.never_started(e, rec)
    makeup.never_started(e, rec)
    check("#65 没过，推了一次", len(n.fails("#65")), 1)
    saved_log = sd / "machinecheck" / "maa-not-started" / "2026-10-06_arknights_MAA-09-05-00.log"
    text = saved_log.read_text(encoding="utf-8") if saved_log.exists() else ""
    check("存下了这一趟的 gui.log 两行", ("开始唤醒" in text, "连接模拟器失败" in text, "早上那趟" in text), (True, True, False))
    check("asst.log 那一段（续行跟着）", ("Connect" in text, "continued line" in text, "下一趟" in text), (True, True, False))
    check("依据里写了存的位置", str(saved_log) in mc.read(sd).get("#65", {}).get("evidence", "") or
          "maa-not-started" in mc.read(sd).get("#65", {}).get("evidence", ""), True)

    print("\n[接线：补跑记录落地 → #33 记过]")
    sd = tmpdir()
    n = N()
    e = engine(sd, n)
    day = "2026-10-06"
    (sd / "makeup").mkdir()
    (sd / "makeup" / f"{day}.json").write_text(json.dumps({"MaaEnd": {
        "result": "dispatched", "dispatched_at": "2026-10-06T14:01:30+08:00", "run_id": "2026-10-06/endfield/MaaEnd-09-30-00",
        "tries": 1}}), encoding="utf-8")
    mrec = RunRecord(run_id="2026-10-06/endfield/MaaEnd-14-02-11", script="MaaEnd", user="endfield",
                     started=datetime(2026, 10, 6, 14, 2, 11, tzinfo=SERVER_TZ), finished=datetime(2026, 10, 6, 14, 30, tzinfo=SERVER_TZ),
                     ok=True)
    makeup.on_record(e, mrec)
    check("#33 记了过", mc.read(sd).get("#33", {}).get("status"), "PASS")

    print("\n[接线：看门狗结束 MaaEnd 说成功了，下一眼进程表里它还在 → 警告 + #31 没过进群]")
    from ark_relay.features import maaend_watchdog as wd
    sd = tmpdir()
    debug = tmpdir() / "debug"
    debug.mkdir()
    (debug / "go-service.stderr.log").write_text("", encoding="utf-8")
    t = [1000.0]
    procs = [("MaaEnd.exe", 30000), ("go-service.exe", 21932)]
    n = N()
    dog = wd.Watchdog(n, debug, clock=lambda: t[0], snapshot=lambda: {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]},
                      processes=lambda: procs, kill=lambda pid, image: (True, ""), plugin_paths=lambda: {},
                      active=True, state_dir=sd)
    dog.tick(1, "")
    (debug / "go-service.stderr.log").write_text("Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456\n", encoding="utf-8")
    t[0] += 31
    dog.tick(2, "")
    check("结束了一次（报了卡死）", [x for x, _, _ in n.sent if "卡" in x] != [], True)
    check("还没下结论", "#31" in mc.read(sd), False)
    t[0] += 31
    dog.tick(3, "")
    check("#31 没过，进群", (mc.read(sd).get("#31", {}).get("status"), len(n.fails("#31"))), ("FAIL", 1))
    sd2 = tmpdir()
    n = N()
    procs2 = [("MaaEnd.exe", 30001)]
    dog = wd.Watchdog(n, debug, clock=lambda: t[0], snapshot=lambda: {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]},
                      processes=lambda: procs2, kill=lambda pid, image: (procs2.clear(), (True, ""))[1],
                      plugin_paths=lambda: {}, active=True, state_dir=sd2)
    dog.tick(1, "")
    (debug / "go-service.stderr.log").write_text("panic: runtime error\n", encoding="utf-8")
    t[0] += 31
    dog.tick(2, "")
    t[0] += 31
    dog.tick(3, "")
    check("真结束了：#31 记过", mc.read(sd2).get("#31", {}).get("status"), "PASS")

    print("\n[接线：桌面助手每次运行都记进 trace；更新流程把读到的启动器画面记下 → #60/#61 判得出]")
    from ark_relay.core import desktop as dk
    from ark_relay.features import gameupdate, gameupdate_games as gg


    def agent(results):
        def spawn(exe, cwd, args):
            res = Path(args[-1])
            res.write_text(json.dumps(results.pop(0), ensure_ascii=False), encoding="utf-8")
            return True
        return spawn


    desk = dk.Desktop(tmpdir(), spawn=agent([
        {"ok": True, "focus_missing": True, "clicked": [], "ocr": [], "log": ["focus: 没有 Games 的窗口"]},
        {"ok": True, "clicked": [[960, 700]], "ocr": [{"text": "确认", "x": 900, "y": 690, "w": 120, "h": 20}],
         "log": ["focus: Endfield 「Endfield」", "click_text: 点了「确认」", "click 960,700"]},
    ]), timeout=5)
    desk.read(focus="Games")
    desk.click_text("确认", focus="Endfield")
    check("两次运行都记了", [x.get("what") for x in desk.trace], ["agent", "agent"])
    check("记下 focus_missing 字段", desk.trace[0].get("focus_missing"), True)
    got, _ = judge("gameupdate", {"screens": desk.trace}, tmpdir())
    check("#60 判过", got["#60"].status, mc.PASS)
    check("脚本里点之前会说点了哪一行", "click_text: 点了「$($hit.text)」" in dk.AGENT_PS, True)


    class Desk:
        """A launcher that is downloading, then ready."""

        def __init__(self, screens):
            self.screens = screens
            self.trace = []

        def note(self, **kw):
            self.trace.append(kw)

        def read(self, focus=None, settle_ms=0):
            if focus == "Endfield":
                return scr("点击任意位置继续")        # the game's title screen after the update
            return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]

        def click_text(self, text, focus=None):
            return True

        def click(self, x, y, focus=None):
            return True


    def scr(*texts):
        return dk.Screen([dk.Line(t, 0, i * 30, 100, 20) for i, t in enumerate(texts)], Path("shot.png"))


    d = Desk([scr("更新游戏"), scr("正在下载 1.2GB/8.5GB", "暂停"), scr("开始游戏")])
    saved = (gg.kill, gg._spawn)
    gg.kill, gg._spawn = (lambda *a: None), (lambda *a, **k: True)
    try:
        gg.update_endfield(d, Path("Endfield.exe"), Path("Launcher.exe"), budget_s=60, poll_s=0, sleep=lambda s: None)
    finally:
        gg.kill, gg._spawn = saved
    stages = [(x.get("stage"), x.get("busy")) for x in d.trace if x.get("what") == "launcher"]
    check("第一眼和等待中都记下了", stages[:2], [("first", ""), ("wait", "正在下载")])
    got, _ = judge("gameupdate", {"screens": d.trace}, tmpdir())
    check("#61 判过", got["#61"].status, mc.PASS)
    check("run_deferred 用过的那张桌子的 trace 拿得到", (gameupdate._LAST_DESK.__setitem__(0, d), gameupdate.last_trace())[1] == d.trace, True)

    print("\n[#61 重放 10-15 12:32-12:49 那一轮：没认出字的帧不到连着 3 帧不报，连着 3 帧才报；「系统提示」那一帧算认出]")
    # relay.log 2026-10-15 (ark-evidence/daily/2026-10-15/relay-2026-10-15.log lines 753-811), the
    # round after c47dfca6: the first look was the disk-space 「系统提示」 (12:32:13, 「确认」 clicked),
    # then one wait frame each ~36 s. A frame the log shows as Line(text='正在下载', x=1376, y=788,
    # w=64, h=16) is replayed with that line; a frame the log shows as desktop-icon text (the
    # wait loop logged dump(4) when no word was read) is replayed with those icon lines only.
    # 12:44:15 is the alarm's frame: its screenshot shot-84e4bfdf.png shows the launcher in
    # front with 「正在下载」 on the yellow button, so on that frame the OCR missed the button.
    # The other four such frames have no screenshot here; the replay keeps them as read.
    ICONS = ["控]面板", "Clashfor", "Windows", "EPIC", "EPICGames", "Launcher", "0", "ToDesk"]


    def frame(stamp, *extra, icons=ICONS):
        lines = [dk.Line(t, 90, 61 + 17 * i, 50, 11) for i, t in enumerate(icons)] + list(extra)
        return dk.Screen(lines, Path(f"shot-{stamp}.png"))


    DL = dk.Line("正在下载", 1376, 788, 64, 16)
    INST = dk.Line("安装中", 1384, 788, 47, 16)
    SPACE = [dk.Line("系统提示", 929, 416, 64, 16), dk.Line("-所需空间：", 749, 475, 77, 12)]
    waits_1015 = ([frame(f"1232-{i:02d}", DL) for i in range(20)]                     # 12:32:49-12:43:39
                  + [dk.Screen(frame("x").lines, Path("shot-84e4bfdf.png"))]            # 12:44:15
                  + [frame("124450", dk.Line("@正在下载", 1324, 782, 116, 26))]         # 12:44:50
                  + [frame("124525", DL)]                                               # 12:45:25
                  + [frame("124601", icons=["控制面板", "Clashfor", "Windows", "2"]),     # 12:46:01
                     frame("124637", icons=["控]面板", "Clashfor", "Windows", "EPIC"])]  # 12:46:37
                  + [frame("124718", INST), frame("124757", INST)]                      # 12:47:18-12:47:57
                  + [frame("124833", icons=["控制面板", "Clashfor", "Windows", "EPIC"]),  # 12:48:33
                     frame("124909", icons=["控]面板", "Clashfor", "Windows", "EPIC"])]  # 12:49:09
                  + [frame("ready", dk.Line("开始游戏", 1376, 788, 64, 16))])


    def replay(screens):
        d = Desk([frame("123213", *SPACE)] + screens)
        saved = (gg.kill, gg._spawn)
        gg.kill, gg._spawn = (lambda *a: None), (lambda *a, **k: True)
        try:
            out = gg.update_endfield(d, Path("Endfield.exe"), Path("Launcher.exe"), budget_s=60, poll_s=0,
                                     sleep=lambda s: None)
        finally:
            gg.kill, gg._spawn = saved
        return d, out


    d, out = replay(list(waits_1015))
    check("这一轮装完了", out, "终末地 客户端已通过启动器更新")
    notes = [x for x in d.trace if x.get("what") == "launcher"]
    check("第一眼是「系统提示」，记成认出的框", (notes[0].get("stage"), notes[0].get("dialog")), ("first", True))
    check("等待中 30 帧，5 帧没认出字", (len(notes) - 1, sum(1 for x in notes[1:] if not (x.get("busy") or x.get("ready") or x.get("dialog")))), (30, 5))
    check("「@正在下载」那一帧算认出", notes[22].get("busy"), "正在下载")
    got, n = judge("gameupdate", {"screens": d.trace}, tmpdir())
    check("#61 过了，没推群", (got["#61"].status, len(n.fails("#61"))), (mc.PASS, 0))
    check("过的那行说了 30 帧里 5 帧没认出、最长连着 2 帧", "等待中 30 帧里 5 帧没认出字（最长连着 2 帧" in got["#61"].evidence, True)

    print("  （同一轮里真的连着 3 帧认不出 → 没过，推了，带第一帧截图）")
    three = waits_1015[:21] + [frame("x1"), frame("x2")] + waits_1015[21:]   # 12:44:15 then two more
    d, _ = replay(three)
    got, n = judge("gameupdate", {"screens": d.trace}, tmpdir())
    check("#61 没过，推了", (got["#61"].status, len(n.fails("#61"))), (mc.FAIL, 1))
    check("说连着 3 帧，第一帧是 12:44:15 那张", ("连着 3 帧" in got["#61"].evidence,
                                              "shot-84e4bfdf.png" in got["#61"].evidence), (True, True))

    print("  （等待中又弹出「系统提示」→ 点「确认」，那一帧不算认不出）")
    d = Desk([scr("更新游戏"), dk.Screen([*SPACE], Path("shot-dlg.png")), scr("正在下载"), scr("开始游戏")])
    saved = (gg.kill, gg._spawn)
    gg.kill, gg._spawn = (lambda *a: None), (lambda *a, **k: True)
    try:
        gg.update_endfield(d, Path("Endfield.exe"), Path("Launcher.exe"), budget_s=60, poll_s=0, sleep=lambda s: None)
    finally:
        gg.kill, gg._spawn = saved
    waits = [(x.get("busy"), x.get("dialog")) for x in d.trace if x.get("what") == "launcher" and x.get("stage") == "wait"]
    check("等待中第一帧是框", waits[0], ("", True))
    got, _ = judge("gameupdate", {"screens": d.trace}, tmpdir())
    check("#61 过了", got["#61"].status, mc.PASS)

    print("  （分轮判：一次跑里两轮，第二轮一帧也没认出 → 没过；两轮边上各一两帧不连成 3 帧）")
    note = {"what": "launcher", "game": "终末地", "unread": "", "ready": False, "dialog": False, "line": "", "dump": "", "shot": "s.png"}
    busy = dict(note, stage="wait", busy="正在下载")
    miss = dict(note, stage="wait", busy="")
    first = dict(note, stage="first", busy="")
    got, n = judge("gameupdate", {"screens": [first, busy, busy, first, miss, miss]}, tmpdir())
    check("第二轮全没认出：没过", (got["#61"].status, len(n.fails("#61"))), (mc.FAIL, 1))
    got, _ = judge("gameupdate", {"screens": [first, busy, miss, miss, first, miss, busy]}, tmpdir())
    check("跨轮的 2+1 帧不连起来：过了", got["#61"].status, mc.PASS)

    print("\n[接线：开机游戏更新那步报了「终末地公告读不到」→ #64 判过（真抄送）]")
    sd = tmpdir()
    n = N()
    n.state_dir = sd
    saved = (gameupdate.should_run, gameupdate.boot_check, gameupdate.mark_run, boot_stages._seconds_to_next_queue)
    gameupdate.should_run = lambda *a, **k: True
    gameupdate.boot_check = lambda cfg, budget_s, now: ([], ["终末地：官方公告读不到，今天有没有版本更新不知道"])
    gameupdate.mark_run = lambda *a, **k: None
    boot_stages._seconds_to_next_queue = lambda *a: 600.0
    try:
        boot_stages._stage_gameupdate(types.SimpleNamespace(state_dir=sd, automas_dir=None), n, boot_stages.log)
    finally:
        gameupdate.should_run, gameupdate.boot_check, gameupdate.mark_run, boot_stages._seconds_to_next_queue = saved
    check("#64 记了过", mc.read(sd).get("#64", {}).get("status"), "PASS")

    print("\n[接线：问调度程序忙不忙时，开着非自动代理的任务记一笔（#18 开机时判）]")
    sd = tmpdir()
    automas = tmpdir()
    (automas / "debug").mkdir()
    now = datetime(2026, 10, 6, 20, 5, tzinfo=SERVER_TZ)
    (automas / "debug" / "app.log").write_text(
        "2026-10-06 20:04:10.100 | INFO     | 业务调度 | 创建任务: cd34ef56-0000-1111-2222-333344445555, 模式: ScriptConfig, 触发来源: manual_task\n",
        encoding="utf-8")
    saved = dict(eng_mod._BUSY_SEEN)
    eng_mod._BUSY_SEEN.update(state_dir=sd, automas_dir=automas)
    try:
        eng_mod._note_other_modes({"tasks": []}, False, now=now)
        eng_mod._note_other_modes({"tasks": []}, False, now=now)
        eng_mod._note_other_modes({"tasks": [{"taskId": "ab12", "mode": "ScriptConfig",
                                              "task_info": [{"name": "MAA", "status": "运行"}]}]}, True, now=now)
    finally:
        eng_mod._BUSY_SEEN.clear()
        eng_mod._BUSY_SEEN.update(saved)
    seen = json.loads((sd / sysmc.BUSY_FILE).read_text(encoding="utf-8"))["seen"]
    check("记了两笔（同一个任务同一个答案只记一次）", [(o["task"][:4], o["busy"]) for o in seen], [("cd34", False), ("ab12", True)])
    got, n = judge("boot", {}, sd)
    check("#18 有一笔算不忙：没过，推了", (got["#18"].status, len(n.fails("#18"))), (mc.FAIL, 1))
    check("依据是 app.log 那一行", "模式 ScriptConfig" in got["#18"].evidence, True)


def _part_mc_system_fixes():
    """What writing the machine checks of the relay's machinery found broken, fixed (each red on the old code).

1. service.py: SvcStop pushes the last state on the SCM's thread after setting the
   stop event; the main thread came out of the loop at once and went on to
   os._exit, so the 「停止前」 push (5-20 s) was cut off. SvcDoRun now waits for it
   (STOP_PUSH_WAIT_S). SvcStop also says which control stopped it, so a Windows
   shutdown reaching SvcShutdown shows in relay.log (machine check #11).
2. service.py: the WMI listener's diag line names the case it fits (H1 the WMI
   service restarted / H2 a provider host is gone / H3 neither), as the
   _wmi_hosts docstring defines them (machine check #59).
3. (removed 2026-10-11: the MaaEnd pre-update it covered was handed to AUTO-MAS.)
4. maaend_watchdog.py: a kill taskkill called a success is looked at again; still
   in the process list is said as a WARNING (machine check #31).
5. desktop.py: the agent says which whole OCR line click_text hit (machine check #60).

    Formerly test_mc_system_fixes.py.
    """
    import logging
    import os
    import threading
    import time
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    class ServiceFramework:
        def __init__(self, args):
            self.args = args

        def ReportServiceStatus(self, status):  # noqa: N802
            pass


    w32su = _Stub("win32serviceutil")
    w32su.ServiceFramework = ServiceFramework
    sys.modules["win32serviceutil"] = w32su
    for name in ("win32service", "win32event", "win32api", "win32con", "win32file", "servicemanager",
                 "win32process", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    cwd = os.getcwd()
    import service  # it changes the working directory to relay/
    from ark_relay.features import procwatch, procwatch as wmi_diag
    os.chdir(cwd)


    class Lines(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.got = []

        def emit(self, r):
            self.got.append((r.levelno, r.getMessage()))


    print("[1. Windows 关机：SvcShutdown → SvcStop 说是关机；主线程等停止前那份状态推完再结束进程]")
    svc = service.ArkRelayService(["ark-relay"])
    events = []


    def slow_push(why):
        time.sleep(0.4)
        events.append(("pushed", why))
        return True


    svc._push_state = slow_push
    svc.main = lambda: None
    real_exit = os._exit
    os._exit = lambda code: events.append(("exit", code))
    h = Lines()
    service.log.addHandler(h)
    service.log.setLevel(logging.INFO)
    try:
        t = threading.Thread(target=svc.SvcShutdown)
        t.start()
        time.sleep(0.1)          # SvcStop is inside its push, as on the machine
        svc.SvcDoRun()
        t.join(2)
    finally:
        os._exit = real_exit
        service.log.removeHandler(h)
    check("停止前那份推完了才结束进程", [e[0] for e in events], ["pushed", "exit"])
    check("SvcStop 说了是 Windows 关机", [m for _, m in h.got if m.startswith("收到停止通知")], ["收到停止通知（Windows 关机）"])

    print("[1b. 清单-1108 A-07：第二次停止（关机消息和停止请求两个线程都来了）不再推一遍、不再挂第二个强退]")
    h2 = Lines()
    service.log.addHandler(h2)
    timers = []
    real_timer = service.threading.Timer
    service.threading.Timer = lambda *a, **k: timers.append(a) or types.SimpleNamespace(daemon=True, start=lambda: None)
    try:
        svc.SvcStop()
    finally:
        service.threading.Timer = real_timer
        service.log.removeHandler(h2)
    check("第二次：没再推、没再挂强退，只记一行",
          ([e for e in events if e[0] == "pushed"], timers, [m for _, m in h2.got if m.startswith("又收到一次停止")]),
          ([("pushed", "停止前")], [], ["又收到一次停止（Windows 关机），第一次的停止还在做"]))
    fresh = service.ArkRelayService(["ark-relay"])
    fresh._push_state = lambda why: (_ for _ in ()).throw(AssertionError("the hard exit must be armed before this"))
    service.threading.Timer = lambda *a, **k: timers.append(a) or types.SimpleNamespace(daemon=True, start=lambda: None)
    try:
        fresh.SvcStop()
    finally:
        service.threading.Timer = real_timer
    check("强退在停止前那份推送之前就挂上了", [t[0] for t in timers], [15])

    print("\n[2. WMI 订阅断了：diag 行写明是哪种情况]")
    watch = procwatch._ProcessWatch(object(), {"ok": True}, service.log, lambda: None)
    watch.hosts = "winmgmt pid 1234; WmiPrvSE pids 5,6"
    real_hosts = wmi_diag._wmi_hosts
    try:
        for now, want in (("winmgmt pid 4321; WmiPrvSE pids 5,6", "hypothesis: H1 WMI service restarted (winmgmt pid 1234 -> 4321)"),
                          ("winmgmt pid 1234; WmiPrvSE pids 6", "hypothesis: H2 WMI provider host gone (WmiPrvSE pid 5)"),
                          ("winmgmt pid 1234; WmiPrvSE pids 5,6,9", "hypothesis: H3 WMI service and provider hosts unchanged"),
                          ("winmgmt pid ?; WmiPrvSE pids 5,6", "hypothesis: unknown (WMI hosts unreadable)")):
            wmi_diag._wmi_hosts = lambda now=now: now
            diag = watch._diag(None, "hresult 0x80020009, scode 0x800706BE", time.monotonic())
            check(want[12:30], diag.endswith(want), True)
    finally:
        wmi_diag._wmi_hosts = real_hosts

    print("\n[2b. WMI drop: the System log's SCM lines for winmgmt, picked out of wevtutil /f:xml]")
    NS = "xmlns='http://schemas.microsoft.com/win/2004/08/events/event'"


    def _ev(eid, when, data, binary=""):
        d = "".join(f"<Data Name='param{i}'>{v}</Data>" for i, v in enumerate(data, 1))
        b = f"<Binary>{binary}</Binary>" if binary else ""
        return (f"<Event {NS}><System><Provider Name='Service Control Manager'/>"
                f"<EventID Qualifiers='16384'>{eid}</EventID><TimeCreated SystemTime='{when}'/></System>"
                f"<EventData>{d}{b}</EventData></Event>")


    # 「winmgmt/4」 as UTF-16LE hex, the way 7036 carries the service key name.
    WINMGMT_BIN = "winmgmt/4".encode("utf-16-le").hex().upper() + "0000"
    xml = (_ev(7036, "2026-10-06T08:16:40.1234567Z", ["Windows Management Instrumentation", "已停止"], WINMGMT_BIN)
           + _ev(7036, "2026-10-06T08:16:41.0000000Z", ["Windows Update", "正在运行"],
                 "wuauserv/4".encode("utf-16-le").hex().upper())
           + _ev(7031, "2026-10-06T08:16:40.0000000Z", ["Windows 管理规范", "1", "60000", "1", "重新启动服务"],
                 WINMGMT_BIN)
           + _ev(7040, "2026-10-06T08:16:39.0000000Z", ["Windows Management Instrumentation", "自动启动", "按需启动", "winmgmt"])
           + _ev(7045, "2026-10-06T08:16:38.0000000Z", ["winmgmt"]))
    got = wmi_diag._scm_winmgmt(xml)
    check("取到 winmgmt 的三条（7036 停止、7031 崩溃、7040 改启动类型）",
          got, "SCM winmgmt: 7036 08:16:40Z Windows Management Instrumentation|已停止; "
               "7031 08:16:40Z Windows 管理规范|1|60000|1|重新启动服务; "
               "7040 08:16:39Z Windows Management Instrumentation|自动启动|按需启动|winmgmt")
    check("别的服务的、不是那几种事件号的都不要", "wuauserv" not in got and "Windows Update" not in got and "7045" not in got)
    check("一条都没有时说没有", wmi_diag._scm_winmgmt(""), "SCM winmgmt: none in 5 min")
    check("读不到 wevtutil 时说读不到", wmi_diag._wmi_scm_events().startswith("SCM winmgmt: "), True)
    real_run = wmi_diag.subprocess.run
    try:
        for enc in ("utf-8", "gbk", "utf-16-le"):
            wmi_diag.subprocess.run = lambda *a, enc=enc, **k: types.SimpleNamespace(stdout=xml.encode(enc))
            check(f"wevtutil 输出是 {enc} 也读得出中文", "已停止" in wmi_diag._wmi_scm_events(), True)
    finally:
        wmi_diag.subprocess.run = real_run

    print("\n[4. 看门狗：结束命令说成功了，下一眼 MaaEnd 还在 → 说出来（WARNING）]")
    from ark_relay.features import maaend_watchdog as wd
    debug = tmpdir() / "debug"
    debug.mkdir()
    (debug / "go-service.stderr.log").write_text("", encoding="utf-8")
    clock = [1000.0]
    sent = []
    dog = wd.Watchdog(types.SimpleNamespace(send=lambda t, b="", **k: sent.append(t) or []), debug,
                      clock=lambda: clock[0], snapshot=lambda: {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]},
                      processes=lambda: [("MaaEnd.exe", 30000)], kill=lambda pid, image: (True, ""),
                      plugin_paths=lambda: {}, active=True)
    h = Lines()
    wd.log.addHandler(h)
    try:
        dog.tick(1, "")
        (debug / "go-service.stderr.log").write_text("Exception 0xc0000005 0x0 0x0 0x0\n", encoding="utf-8")
        clock[0] += 31
        dog.tick(2, "")
        clock[0] += 31
        dog.tick(3, "")
    finally:
        wd.log.removeHandler(h)
    check("结束过一次", len(sent) >= 1, True)
    check("说了它还在", [lvl for lvl, m in h.got if "命令说成功了" in m and "还在" in m], [logging.WARNING])

    print("\n[5. 桌面助手：click_text 点之前说点的是哪一整行]")
    from ark_relay.core import desktop as dk
    check("脚本里有那一行", "[void]$log.Add(\"click_text: 点了「$($hit.text)」\")" in dk.AGENT_PS, True)


def _part_selfcheck_main():
    """Boot self-check: every broken assumption is named and pushed to the group at
once; the daily report gets the two relay lines a person used to run by hand.

2026-09-17: the process table had been unreadable for three weeks (wmic gone)
and the relay found out from a lost queue. The self-check exists so a boot
tells on itself instead.

    Formerly test_selfcheck.py.
    """
    import copy
    import json
    import tempfile
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import selfcheck
    from ark_relay.core import mastercfg as mascontract, texts
    from ark_relay.core.notify import route_of
    from ark_relay.features import commands


    # The machine's AUTO-MAS as /api/scripts/get answers it: the script ids and names of
    # fixtures/automas-config-2026-10-11 (the machine's own config), with the update
    # settings the switch-over handed it (relay/handover/automas_handover.py): 10a read back
    # True in switch.log 10-11 10:04:30; 10b set and read back 10-12 (commit a0a7b7f2:
    # Game.Enabled true, Game.Path D:\Wuthering Waves\launcher.exe; Game.IfAutoUpdate is
    # AUTO-MAS's default true, fixtures/automas-models/config.py.txt OkwwConfig).
    _CFG = json.loads((fx_dir(Path(__file__), "fixtures") / "automas-config-2026-10-11" / "config"
                       / "ScriptConfig.json").read_text(encoding="utf-8"))
    MACHINE_SCRIPTS = {sid: {"Info": dict(sc["Info"])} for sid, sc in _CFG.items() if sid != "instances"}
    for _sc in MACHINE_SCRIPTS.values():
        if _sc["Info"]["Name"] == "MAA":
            _sc["Run"] = {"IfCheckGameUpdate": True, "IfAutoInstallGameApk": True, "HardTimeLimit": 120}
        if _sc["Info"]["Name"] == "OK-WW":
            _sc["Game"] = {"Enabled": True, "Type": "Client", "Path": "D:\\Wuthering Waves\\launcher.exe",
                           "IfAutoUpdate": True}
    mas_scripts = {"data": MACHINE_SCRIPTS}


    def _fake_mas(path, body=None, timeout=20):
        if path != "/api/scripts/get":
            raise AssertionError(f"endpoint not prepared by this test: {path}")
        if isinstance(mas_scripts, Exception):
            raise mas_scripts
        return {"code": 200, **mas_scripts}


    commands._mas = _fake_mas
    launchers = {"D:\\Wuthering Waves\\launcher.exe"}      # the files that exist on the fake machine
    selfcheck._is_file = lambda p: p in launchers


    class _Notifier:
        channels = ["企业微信机器人"]

        def __init__(self):
            self.sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert))
            return []


    with tempfile.TemporaryDirectory() as td:
        import os
        os.environ["ARK_LOG_FILE"] = str(Path(td) / "log" / "relay.log")
        cfg = types.SimpleNamespace(automas_dir=td, state_dir=Path(td) / "state", history_dir=td,
                                    phone_topic="ark-x", phone_pin="1234")
        good = dict(procs=lambda: [(1, r"D:\ark\automas\repo\main.py")], mas_up=lambda: True,
                    schedule=lambda: [{"name": "早班", "times": ["09:00"]}], channels=lambda: ["群"],
                    run_ok=lambda cmd: (True, ""), has_module=lambda m: True,
                    # The AUTO-MAS settings check reads config files; test_mas.py covers it.
                    contract=lambda automas_dir: mascontract.Result([], [], 1),
                    # 11-06 12:07 the machine answered this after VBS was turned off (VT-x again).
                    virt=lambda: "VBS=0 HV=False")

        print("[一切正常：全部成立、不报警]")
        cs = selfcheck.run(cfg, **good)
        check("15 项", len(cs), 15)
        check("全部成立", [c.name for c in cs if not c.ok], [])
        check("每一项的名字都是人话", [texts.plain(c.name) for c in cs if texts.plain(c.name)], [])

        print("\n[09-17 那种机器：进程表读不到、调度程序没应答、任务计划没了]")
        bad = dict(good, procs=lambda: None, mas_up=lambda: False,
                   run_ok=lambda cmd: (False, "退出码 1") if cmd[0] == "schtasks" else (True, ""))
        cs = selfcheck.run(cfg, **bad)
        names = [c.name for c in cs if c.ok is False]
        check("点名进程表", any("怎么启动" in n for n in names))
        check("点名调度程序没应答", "调度程序有应答" in names)
        check("点名任务计划", "调度程序的开机任务计划还在" in names)
        check("别的项照常成立", len(names), 3)
        # 2026-10-10 16:14:07: one unreadable process table showed as two failures.
        dep = [c for c in cs if c.name == "调度程序的后台程序在跑"][0]
        check("后台程序那项判不了，不算不成立", dep.ok, None)
        check("进程表那项说明后台程序判不了", any("判不了" in c.detail for c in cs if c.ok is False))
        rows_ok = [(1, "python.exe other.py")]
        cs = selfcheck.run(cfg, **dict(good, procs=lambda: rows_ok))
        check("读得到进程表、后台不在才算不成立", [c.name for c in cs if c.ok is False], ["调度程序的后台程序在跑"])
        # OK-WW's script is a main.py too (preupdate_okww.py); it is not the AUTO-MAS backend.
        okww = [(7, r"D:\ark\okww\data\apps\ok-ww\python\python.exe D:\ark\okww\data\apps\ok-ww\working\main.py -t 2 -e")]
        cs = selfcheck.run(cfg, **dict(good, procs=lambda: okww))
        check("OK-WW's main.py is not taken for the backend", [c.name for c in cs if c.ok is False], ["调度程序的后台程序在跑"])
        machine = [(5088, r"D:\ark\automas\runtime\environment\venv\Scripts\python.exe main.py")]  # test_procs.py
        cs = selfcheck.run(cfg, **dict(good, procs=lambda: machine))
        check("the machine's backend line (10-10) still counts", [c.name for c in cs if c.ok is False], [])
        cs = selfcheck.run(cfg, **dict(good, procs=lambda: [(9, "d:/ARK/AutoMAS/repo/MAIN.PY")]))
        check("/ and case do not matter", [c.name for c in cs if c.ok is False], [])

        print("\n[10-01..10-05 那种机器：没装 Pillow，读长图每次都 ModuleNotFoundError]")
        cs = selfcheck.run(cfg, **dict(good, has_module=lambda m: m != "PIL"))
        miss = [c for c in cs if not c.ok]
        check("只点名读图组件", [c.name for c in miss], ["中继装了读图组件（读官方长图（卡池几点几分）、压缩报警截图）"])
        check("说怎么补", miss and "pip install Pillow" in miss[0].detail)
        check("真查：本机查得到标准库、查不到不存在的包",
              (selfcheck._has_module("json"), selfcheck._has_module("no_such_pkg_ark")), (True, False))

        print("\n[11-04 21:25 那种机器：系统自己打开了「基于虚拟化的安全」，雷电落到慢路]")
        # 11-06 10:2x the machine read VirtualizationBasedSecurityStatus 2 while VBS was on;
        # 12:07 after it was turned off: 0, HypervisorPresent False.
        cs = selfcheck.run(cfg, **dict(good, virt=lambda: "VBS=2 HV=True"))
        miss = [c for c in cs if not c.ok]
        check("VBS on: only this line fails", [(c.name, c.ok) for c in miss], [(selfcheck.VIRT_NAME, False)])
        check("VBS on: the detail says what it costs", bool(miss) and "70 多秒" in miss[0].detail)
        check("VBS on: the detail is plain words", [texts.plain(c.detail) for c in miss if texts.plain(c.detail)], [])
        cs = selfcheck.run(cfg, **dict(good, virt=lambda: "VBS=0 HV=True"))
        miss = [c for c in cs if not c.ok]
        check("another hypervisor holds VT-x: fails too", [(c.name, c.ok) for c in miss], [(selfcheck.VIRT_NAME, False)])
        check("that detail is plain words too", [texts.plain(c.detail) for c in miss if texts.plain(c.detail)], [])
        cs = selfcheck.run(cfg, **dict(good, virt=lambda: "VBS=1 HV=False"))
        check("configured but not running (needs a reboot): holds", [c.name for c in cs if not c.ok], [])

        def _no_pwsh():
            raise FileNotFoundError(2, "pwsh")
        for label, reader in (("the query cannot start", _no_pwsh), ("an empty answer", lambda: ""),
                              ("an answer it cannot read", lambda: "Get-CimInstance : 拒绝访问")):
            cs = selfcheck.run(cfg, **dict(good, virt=reader))
            check(f"{label}: not judged (None), never an alarm",
                  [(c.name, c.ok) for c in cs if not c.ok], [(selfcheck.VIRT_NAME, None)])

        print("\n[AUTO-MAS 还管着两个游戏客户端的更新（交接 10a、10b）：被改掉了就点名]")
        # s26 audit 2026-10-13: the handover runs once; an AUTO-MAS upgrade or a click in its
        # window could turn these off again and nobody would update the client.
        UPD = "调度程序还管着两个游戏客户端的更新（明日方舟、鸣潮）"
        cs = selfcheck.run(cfg, **good)
        check("the machine's values: the line holds", [(c.name, c.ok) for c in cs if c.name == UPD], [(UPD, True)])
        for script, field, value in (("MAA", ("Run", "IfCheckGameUpdate"), False),
                                     ("MAA", ("Run", "IfAutoInstallGameApk"), False),
                                     ("OK-WW", ("Game", "Enabled"), False),
                                     ("OK-WW", ("Game", "IfAutoUpdate"), False),
                                     ("OK-WW", ("Game", "Path"), ""),
                                     ("OK-WW", ("Game", "Path"), "D:\\Wuthering Waves Game\\Wuthering Waves.exe"),
                                     ("OK-WW", ("Game", "Path"), "D:\\Gone\\launcher.exe")):
            changed = copy.deepcopy(MACHINE_SCRIPTS)
            sc = next(v for v in changed.values() if v["Info"]["Name"] == script)
            sc[field[0]][field[1]] = value
            mas_scripts = {"data": changed}
            cs = selfcheck.run(cfg, **good)
            bad_lines = [c for c in cs if c.ok is False]
            check(f"{script} {'.'.join(field)} = {value!r}: only this line fails",
                  [c.name for c in bad_lines], [UPD])
            check(f"{script} {'.'.join(field)} = {value!r}: the detail is plain words",
                  [texts.plain(c.detail) for c in bad_lines if texts.plain(c.detail)], [])
        changed = copy.deepcopy(MACHINE_SCRIPTS)
        del next(v for v in changed.values() if v["Info"]["Name"] == "OK-WW")["Game"]["IfAutoUpdate"]
        mas_scripts = {"data": changed}
        cs = selfcheck.run(cfg, **good)
        check("a setting missing from the answer fails too", [c.name for c in cs if c.ok is False], [UPD])
        mas_scripts = {"data": {k: v for k, v in MACHINE_SCRIPTS.items() if v["Info"]["Name"] != "OK-WW"}}
        cs = selfcheck.run(cfg, **good)
        check("no OK-WW script: fails", [c.name for c in cs if c.ok is False], [UPD])
        mas_scripts = ConnectionRefusedError(61, "Connection refused")
        cs = selfcheck.run(cfg, **dict(good, mas_up=lambda: False))
        check("AUTO-MAS not answering: one failure (its own line), this one cannot be judged",
              ([c.name for c in cs if c.ok is False], [c.ok for c in cs if c.name == UPD]), (["调度程序有应答"], [None]))
        mas_scripts = TimeoutError("timed out")
        cs = selfcheck.run(cfg, **good)
        check("answers the probe but not this read: fails", [c.name for c in cs if c.ok is False], [UPD])
        mas_scripts = {"data": MACHINE_SCRIPTS}

        print("\n[report：不成立就群报一条，全成立不报]")
        import logging
        from ark_relay.features import errwatch

        class _Rec(logging.Handler):
            def __init__(self):
                super().__init__()
                self.records = []

            def emit(self, record):
                self.records.append(record)
        rec = _Rec()
        selfcheck.log.addHandler(rec)
        selfcheck.log.setLevel(logging.INFO)
        n = _Notifier()
        selfcheck.run = (lambda _run: lambda cfg, **kw: _run(cfg, **dict(bad, channels=kw.get("channels"))))(selfcheck.run)
        selfcheck.report(cfg, n)
        check("报了一条", len(n.sent), 1)
        check("标题", n.sent and n.sent[0][0] == texts.SELFCHECK_FAILED)
        check("是报警", n.sent and n.sent[0][2] is True)
        check("正文列出不成立的项", n.sent and "任务计划" in n.sent[0][1] and "3 项不成立" in n.sent[0][1])
        check("正文是人话", n.sent and texts.plain(n.sent[0][1]), [])
        check("走群", route_of(texts.SELFCHECK_FAILED, alert=True), "group")
        # Each ✗ line repeats that one alarm: errwatch must not push it again.
        crosses = [r for r in rec.records if "✗" in r.getMessage()]
        check("✗ 行有 3 条", len(crosses), 3)
        check("✗ 行都标了「已进群」，不再单独推", all(getattr(r, errwatch.PUSHED, False) for r in crosses))
        check("判不了那项记成 ？、不是警告",
              [(r.levelno, "？" in r.getMessage()) for r in rec.records if "后台程序在跑" in r.getMessage()],
              [(logging.INFO, True)])
        n2 = _Notifier()
        n2.send = lambda *a, **k: ["企业微信机器人：超时"]
        rec.records.clear()
        selfcheck.report(cfg, n2)
        check("没发出去就不标，照常由报错转发推",
              [getattr(r, errwatch.PUSHED, False) for r in rec.records if "✗" in r.getMessage()], [False] * 3)

    print("\n[进程表读取：没有系统 WMI 的机器上返回「读不到」，不假装活着]")
    from ark_relay.core import desktop as procs
    check("这台没有 pywin32 的 Mac 上返回 None", procs.python_processes(), None)

    print("\n[日报两行：从当天 relay.log 来]")
    log = """09-17 08:45:28 WARNING ark.service  AUTO-MAS 接口不在，拉起它
09-17 08:46:46 INFO    ark.service  AUTO-MAS 已拉起（24 秒）
09-17 10:48:40 ERROR   ark.service  进程启动事件监听中断，改用 120 秒活性检查，5 秒后重订阅
09-17 21:20:39 WARNING ark.service  AUTO-MAS 接口不在，拉起它
09-17 21:21:28 ERROR   ark.service  AUTO-MAS 拉起后 45 秒内接口仍不通
09-16 21:21:00 ERROR   ark.service  昨天的，不算
09-18 08:45:50 INFO    ark.service  AUTO-MAS 自己起来了（等了 21 秒）
"""
    lines = selfcheck.daily_lines("2026-09-17", log)
    check("两行", len(lines), 2)
    check("错误计数 2、第一条 10:48、出在主程序", "报错 2 条" in lines[0] and "10:48" in lines[0] and "主程序" in lines[0])
    check("原话有术语就不照抄", any(k in lines[0] for k in ("留在", "见中继日志", "已记日志")))
    check("开机两次：重开后起来了 24 秒；重开后还是没应答", "24 秒" in lines[1] and "还是没应答" in lines[1])
    lines2 = selfcheck.daily_lines("2026-09-18", log)
    check("没报错就说没报错", lines2[0], "· 中继今天没有报错")
    check("自己起来了 21 秒", "自己起来了（等了 21 秒）" in lines2[1])
    check("两行都是人话", [texts.plain(x) for x in lines + lines2 if texts.plain(x)], [])
    # relay.log unreadable: the section says so instead of vanishing (audit row selfcheck.py:207).
    missing = selfcheck.daily_section("2026-09-18", "/nonexistent/relay.log")
    check("missing log -> the section says it is missing", missing, "中继体检\n· 中继日志读不到（文件不在）")
    import unittest.mock as _mock
    with _mock.patch("ark_relay.core.statestore.tail_bytes", side_effect=PermissionError(13, "locked")):
        check("locked log -> the section says it cannot be opened",
              selfcheck.daily_section("2026-09-18", "/locked/relay.log"),
              "中继体检\n· 中继日志读不到（被占用或没有权限）")
    check("the unreadable line is plain words", texts.plain(missing), [])

    print("\n[a start that died before the self-check is not 「开机时已经在」 (real 10-10 16:28-17:22)]")
    # relay.log 10-10 16:28-16:32: 15 starts about 18 s apart, none reaching the boot
    # self-check (the AUTO-MAS step runs before it), then boots that did reach it.
    crash = (fx_dir(Path(__file__), "fixtures") / "relay-1010-crashloop-boots.log").read_text(encoding="utf-8")
    boots = selfcheck.daily_lines("2026-10-10", crash)[1].removeprefix("· 调度程序开机：").split("；")
    check("22 starts", len(boots), 22)
    check("the 15 crash-loop starts read as stopped before the AUTO-MAS step",
          [b for b in boots[:15] if not b.endswith("中继刚启动就停了，还没看调度程序在不在")], [])
    check("16:32:46, 16:33, 16:59:30, 17:02:25 and 17:21 reached the self-check: already up",
          [b for b in boots if b.endswith("开机时已经在")],
          ["16:32 开机时已经在", "16:33 开机时已经在", "16:59 开机时已经在", "17:02 开机时已经在", "17:21 开机时已经在"])
    check("the line is plain words", texts.plain("；".join(boots)), [])

    print("\n[a self-update restart is not a crash (real 10-05 21:20, 10-07 08:45 / 21:20, 10-08 20:05)]")
    # Each of these starts fetched a new version and restarted before the boot
    # self-check; the restarted start that follows reached it.
    upd = (fx_dir(Path(__file__), "fixtures") / "relay-selfupdate-restart-boots.log").read_text(encoding="utf-8")
    got = {d: selfcheck.daily_lines(d, upd)[1] for d in ("2026-10-05", "2026-10-07", "2026-10-08")}
    check("10-05", got["2026-10-05"], "· 调度程序开机：21:20 装新版后自己重启了；21:20 开机时已经在")
    check("10-07", got["2026-10-07"], "· 调度程序开机：08:45 装新版后自己重启了；08:45 自己起来了（等了 19 秒）；"
          "21:20 装新版后自己重启了；21:20 自己起来了（等了 13 秒）")
    check("10-08", got["2026-10-08"], "· 调度程序开机：20:05 装新版后自己重启了；20:06 自己起来了（等了 3 秒）")
    check("the 10-10 crash loop still reads as a crash",
          [b for b in boots[:15] if not b.endswith("中继刚启动就停了，还没看调度程序在不在")], [])
    # A stop mid-boot (service._stop_in_boot) - not in the real log yet; the line is the one service.py writes.
    stop = ("10-10 22:30:11 INFO    ark.service  服务模式启动，监视 D:\\ark\\automas\\history（变更即处理，兜底 30 秒）\n"
            "10-10 22:30:12 INFO    ark.service  开机还没走完就收到停止，后面几步不做了，直接退出\n")
    check("a stop mid-boot", selfcheck.daily_lines("2026-10-10", stop)[1], "· 调度程序开机：22:30 开机还没走完就被叫停了")
    check("the new words are plain", texts.plain("；".join(got.values()) + "开机还没走完就被叫停了"), [])

    print()
    if fails:
        print("FAILED:", fails); sys.exit(1)
    print("all checks passed")


def _part_selfcheck_one_push():
    """A failing boot self-check reaches the group once, through the real errwatch handler.

alerts/20261010.jsonl 16:14:08-16:14:14 (and again at 16:33, 16:59, 17:02): each
「🩺 开机自检没过」 was followed by one 「🩺 中继自己报错了」 per failing ✗ line,
because errwatch pushed the ✗ WARNINGs the self-check had already put in its own
alarm. 38246899 (10-10 17:44) marks those lines `errwatch.group_pushed`; no
self-check line has failed on the machine since, so this is where the fix is run:
selfcheck.report with one forced failing check, under a real
errwatch.ErrorKindAlert on the "ark" logger (a push = a record reaching its
_take), counts the pushes. When the self-check's own send fails, the ✗ line is
not marked and errwatch carries it instead (still one push).

    Formerly test_selfcheck_one_push.py.
    """
    import logging
    import tempfile

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    from ark_relay.core import texts
    from ark_relay.features import errwatch
    from ark_relay.features import selfcheck


    class _Notifier:
        channels = ["企业微信机器人"]

        def __init__(self, errs=()):
            self.sent, self._errs = [], list(errs)

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append(title)
            return self._errs


    CHECKS = [selfcheck.Check("看得到机器上在跑哪些程序", True),
              selfcheck.Check("调度程序的后台程序在跑", False, "没找到 AUTO-MAS 的后台进程"),
              selfcheck.Check("状态目录能写", True)]
    selfcheck.run = lambda cfg, **kw: list(CHECKS)


    def pushes(notifier):
        """(what the self-check sent itself, what errwatch took) for one report()."""
        with tempfile.TemporaryDirectory() as td:
            h = errwatch.ErrorKindAlert(_Notifier(), state_dir=Path(td) / "state", known={})
            taken = []
            h._take = taken.append
            ark = logging.getLogger(errwatch.ARK)
            ark.addHandler(h)
            try:
                selfcheck.report(None, notifier)
            finally:
                ark.removeHandler(h)
        return notifier.sent, [r.getMessage() for r in taken]


    print("[one failing check, the alarm went out: one push in all]")
    sent, taken = pushes(_Notifier())
    check("the self-check sent its alarm once", sent, [texts.SELFCHECK_FAILED])
    check("errwatch takes nothing more (the ✗ line is marked as delivered)", taken, [])

    print("[the self-check's own send failed: errwatch carries the ✗ line instead]")
    sent, taken = pushes(_Notifier(errs=["企业微信机器人：超时"]))
    check("the send was tried once", sent, [texts.SELFCHECK_FAILED])
    check("errwatch takes the one ✗ line", [m.split("：")[0] for m in taken], ["开机自检 ✗ 调度程序的后台程序在跑"])

    print("[all checks pass: nothing at all]")
    CHECKS[1] = selfcheck.Check("调度程序的后台程序在跑", True)
    check("no push", pushes(_Notifier()), ([], []))


def _part_machinecheck_main():
    """Machine checks: the machine confirms deployed changes by itself (machinecheck.py).

The user, 2026-10-06 04:59: the machine must check the open ledger items by itself
after a deploy, instead of a person reading logs. Every FAIL goes to the group,
every time it is judged; PASS and still-waiting go to the daily report only.

    Formerly test_machinecheck.py.
    """
    import logging
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features import machinecheck as mc
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.notify import route_of


    class N:
        def __init__(self):
            self.sent = []

        def send(self, title, body, alert=False, **kw):
            self.sent.append((title, body, alert))
            return []


    mc.load()
    real = dict(mc.CHECKS), dict(mc.CANNOT)
    mc.CHECKS.clear()
    mc.CANNOT.clear()
    try:
        seen = {}

        @mc.check("#901", "样例：跑完看日志里有没有那一行", "A", "run")
        def _a(ctx):
            line = ctx.get("line")
            if line is None:
                return None
            return mc.Result(mc.PASS if "已领到" in line else mc.FAIL, line)

        @mc.check("#902", "样例：等手机指令", "B", "phone_cmd")
        def _b(ctx):
            seen["ctx"] = ctx
            return mc.Result(mc.PASS, f"回执：{ctx.get('msg')}")

        @mc.check("#903", "样例：自己会出错的核对", "A", "run")
        def _c(ctx):
            raise RuntimeError("boom")

        mc.cannot("#904", "样例：核不了的", "要人在电脑上跑一个工具")
        d = tmpdir()
        now = datetime(2026, 10, 6, 21, 40, tzinfo=SERVER_TZ)
        n = N()
        print("[没被触发：什么都不记]")
        check("run 事件但没给那一行：#901 不判", [c for c, _ in mc.judge(d, "run", {}, notifier=n, now=now)], [])
        check("没推", n.sent, [])
        print("[过了：只记，不推]")
        got = mc.judge(d, "run", {"line": "周本领奖：已领到"}, version="v1", notifier=n, now=now)
        check("判了 #901 过了", [(c, r.status) for c, r in got], [("#901", mc.PASS)])
        check("过了不推", n.sent, [])
        check("记进状态：结论、依据、版本", {k: mc.read(d)["#901"][k] for k in ("status", "evidence", "version")},
              {"status": "PASS", "evidence": "周本领奖：已领到", "version": "v1"})
        print("[没过：每次都推，进群]")
        mc.judge(d, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n, now=now)
        mc.judge(d, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n, now=now)
        check("没过两次，推两次", len(n.sent), 2)
        check("都带 alert=True", [a for _, _, a in n.sent], [True, True])
        check("标题走群", route_of(n.sent[0][0], alert=True) if n.sent else None, "group")
        check("正文带依据", "没认出领奖弹窗" in n.sent[0][1] if n.sent else False, True)
        check("记了没过的次数", mc.read(d)["#901"]["fails"], 2)
        print("[核对自己出错：记 ERROR（会进群），不当成过了]")
        errs = []
        h = type("H", (logging.Handler,), {"emit": lambda self, r: errs.append(r.levelno)})()
        mc.log.addHandler(h)
        mc.judge(d, "run", {"line": "x"}, notifier=n, now=now)
        mc.log.removeHandler(h)
        check("有一条 ERROR", logging.ERROR in errs, True)
        check("#903 没有结论", "#903" in mc.read(d), False)
        print("[B 类：触发时拿到事件内容]")
        mc.judge(d, "phone_cmd", {"action": "skip_today", "msg": "调度程序已确认"}, notifier=n, now=now)
        check("看到了指令", (seen["ctx"]["action"], seen["ctx"]["event"]), ("skip_today", "phone_cmd"))
        print("[日报一段]")
        sec = mc.daily_section(d)
        check("有标题", sec.startswith("上机核对"), True)
        check("没过的打 ❌", "❌ #901" in sec, True)
        check("过了的打 ✅", "✅ #902" in sec, True)
        check("没判的写在等", "⏳ #903" in sec, True)
        check("核不了的写明原因", "✋ #904 样例：核不了的：机器核不了，要人在电脑上跑一个工具" in sec, True)
        print("[登记写错就拒绝]")
        for label, args in (("类别只能 A/B", ("#905", "x", "C", "run")), ("事件要认识", ("#906", "x", "A", "nope")),
                            ("至少一个事件", ("#907", "x", "A"))):
            try:
                mc.check(*args)(lambda c: None)
                check(label, "registered", "refused")
            except ValueError:
                check(label, "refused", "refused")
        try:
            mc.judge(d, "nope", {})
            check("不认识的事件拒绝", "judged", "refused")
        except ValueError:
            check("不认识的事件拒绝", "refused", "refused")
        print("[state file exists but cannot be read: said once, not overwritten, FAILs still pushed]")
        d2 = tmpdir()
        sf = d2 / mc.STATE_FILE
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text("{corrupt", encoding="utf-8")
        getattr(mc, "_last_error", {}).clear()
        warned = []
        wh = type("W", (logging.Handler,), {"emit": lambda self, r: warned.append(r.levelno)})(level=logging.WARNING)
        mc.log.addHandler(wh)
        n2 = N()
        mc.judge(d2, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n2, now=now)
        check("one WARNING", warned.count(logging.WARNING), 1)
        check("the unreadable file is left as it was (no other check's history overwritten)",
              sf.read_text(encoding="utf-8"), "{corrupt")
        check("the FAIL is still pushed", len(n2.sent), 1)
        mc.judge(d2, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n2, now=now)
        check("same condition again -> no second WARNING", warned.count(logging.WARNING), 1)
        sf.write_text("{}", encoding="utf-8")
        mc.judge(d2, "run", {"line": "周本领奖：已领到"}, notifier=n2, now=now)
        check("readable again -> written, no WARNING", (mc.read(d2).get("#901", {}).get("status"),
                                                        warned.count(logging.WARNING)), ("PASS", 1))
        sf.write_text("{corrupt", encoding="utf-8")
        mc.judge(d2, "run", {"line": "周本领奖：已领到"}, notifier=n2, now=now)
        check("broken again after a good read -> WARNING again", warned.count(logging.WARNING), 2)
        d3 = tmpdir()
        mc.judge(d3, "run", {"line": "周本领奖：已领到"}, notifier=n2, now=now)
        check("no state file yet is not an error -> written, no WARNING",
              (mc.read(d3).get("#901", {}).get("status"), warned.count(logging.WARNING)), ("PASS", 2))
        mc.log.removeHandler(wh)
    finally:
        mc.CHECKS.clear()
        mc.CHECKS.update(real[0])
        mc.CANNOT.clear()
        mc.CANNOT.update(real[1])


def _part_machinecheck_wait():
    """E2 of the deploy: machinecheck_wait.py decides boot-judged-and-quiet / alarm / wait.

The gate reads the two files the relay keeps - state/machinecheck.json and
state/alerts/<day>.jsonl - and answers whether this deploy's version has had
its boot batch judged and whether the group was quiet since. These checks pin
the three verdicts on realistic rows, including the traps: an old version's row
must not count, a non-boot event is not the boot batch, and an alarm wins over
a judged boot.

    Formerly test_machinecheck_wait.py.
    """
    import contextlib
    import io
    import json
    import os

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT.parent / "scripts" / "windows"))
    from machinecheck_wait import alerts_with_version, boot_judged, main, read_rows, verdict


    def mc_row(**kw):
        base = {"status": "PASS", "evidence": "x", "at": "2026-10-06 06:20:00",
                "version": "", "event": "", "passes": 1}
        base.update(kw)
        return base


    def alert_row(**kw):
        base = {"ts": "2026-10-06 06:20:00", "game": "鸣潮", "title": "t",
                "text": "x", "version": "", "evidence_run": ""}
        base.update(kw)
        return base


    d = tmpdir()

    print("[an empty state dir waits]")
    check("read_rows on a missing file is {}", read_rows(str(d), "missing.json"), {})
    check("no boot row", boot_judged(str(d), "v1"), False)
    check("no alarms", alerts_with_version(str(d), "v1"), [])
    check("verdict wait", verdict(str(d), "v1"), ("wait", []))

    print("[a boot row of this version means the batch judged]")
    (d / "machinecheck.json").write_text(json.dumps({"#63": mc_row(version="v1", event="boot")},
                                                    ensure_ascii=False), encoding="utf-8")
    check("boot judged", boot_judged(str(d), "v1"), True)
    check("verdict boot", verdict(str(d), "v1"), ("boot", []))
    check("an older version's row does not count", boot_judged(str(d), "v0"), False)

    print("[a non-boot event is not the boot batch]")
    (d / "machinecheck.json").write_text(json.dumps({"#21": mc_row(version="v1", event="unresolved")},
                                                    ensure_ascii=False), encoding="utf-8")
    check("unresolved row is not boot", boot_judged(str(d), "v1"), False)
    check("so it still waits", verdict(str(d), "v1"), ("wait", []))

    print("[a group push of this version is an alarm, and beats a judged boot]")
    (d / "machinecheck.json").write_text(json.dumps({"#63": mc_row(version="v1", event="boot")},
                                                    ensure_ascii=False), encoding="utf-8")
    ad = d / "alerts"
    ad.mkdir()
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v1", title="上机核对 #2 没过"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    st, alarms = verdict(str(d), "v1")
    check("alarm wins over a judged boot", st, "alarm")
    check("the push is listed", [a["title"] for a in alarms], ["上机核对 #2 没过"])

    print("[an older version's push does not alarm this deploy]")
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    check("old version is quiet, boot still judged", verdict(str(d), "v1"), ("boot", []))

    print("[a malformed alerts line is skipped, a good one read]")
    (ad / "20261006.jsonl").write_text(
        "not json\n" + json.dumps(alert_row(version="v1", title="good"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    check("one good row survives the junk",
          [a["title"] for a in alerts_with_version(str(d), "v1")], ["good"])


    def run_main(state_dir, version):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = main([state_dir, version, "0"])
        return rc, out.getvalue()


    print("[a torn last line (a push being appended) is not read as quiet]")
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n"
        + '{"ts": "2026-10-06 06:21:00", "game": "鸣潮", "ti', encoding="utf-8")
    check("boot judged but the alerts are torn: wait", verdict(str(d), "v1"), ("wait", []))
    rc, out = run_main(str(d), "v1")
    check("main does not print MCWAIT_OK", "MCWAIT_OK" in out, False)
    check("main exits 2 at the timeout (torn line)", rc, 2)
    check("the timeout line names the file", "20261006.jsonl" in out, True)
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n"
        + json.dumps(alert_row(version="v1", title="torn one"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    check("once the line is whole the next poll sees the alarm", verdict(str(d), "v1")[0], "alarm")

    print("[an old file's torn last line (a past crash) is skipped with one note, not waited on]")
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n"
        + '{"ts": "2026-10-03 06:21:00", "game": "鸣潮", "ti', encoding="utf-8")
    old = os.stat(ad / "20261006.jsonl").st_mtime - 3 * 86400
    os.utime(ad / "20261006.jsonl", (old, old))
    notes = io.StringIO()
    with contextlib.redirect_stdout(notes):
        first = verdict(str(d), "v1")
        second = verdict(str(d), "v1")
    check("boot judged and the torn file is days old: boot", first, ("boot", []))
    check("still boot on the next poll", second, ("boot", []))
    check("the note names the file", "20261006.jsonl" in notes.getvalue(), True)
    check("the note is printed once over two polls", notes.getvalue().count("20261006.jsonl"), 1)
    rc, out = run_main(str(d), "v1")
    check("main passes over an old torn line", (rc, "MCWAIT_OK" in out), (0, True))

    print("[an unreadable alerts file is not read as quiet]")
    (ad / "20261006.jsonl").write_text(
        json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n", encoding="utf-8")
    check("readable and quiet: boot", verdict(str(d), "v1"), ("boot", []))
    # chmod 0 makes a file unreadable on POSIX only; on Windows it only sets the read-only
    # flag (docs.python.org/3/library/os.html#os.chmod). There a byte-range lock over the
    # whole file makes reads of it fail, in this process and in run_main's.
    _lock = None
    if os.name == "nt":
        import msvcrt
        _lock = open(ad / "20261006.jsonl", "r+b")
        msvcrt.locking(_lock.fileno(), msvcrt.LK_NBLCK, max(1, (ad / "20261006.jsonl").stat().st_size))
    else:
        os.chmod(ad / "20261006.jsonl", 0)
    try:
        check("unreadable: wait", verdict(str(d), "v1"), ("wait", []))
        rc, out = run_main(str(d), "v1")
        check("main exits 2 at the timeout (unreadable file)", rc, 2)
        check("the timeout line says it could not read the file", "20261006.jsonl" in out, True)
    finally:
        if _lock is not None:
            _lock.seek(0)
            msvcrt.locking(_lock.fileno(), msvcrt.LK_UNLCK, max(1, (ad / "20261006.jsonl").stat().st_size))
            _lock.close()
        else:
            os.chmod(ad / "20261006.jsonl", 0o644)

    print("[pushes docs/NOTIFICATIONS.md routes `group (report)` are not alarms]")
    # The real rows: 10-13 10:00 the 🖼️ 无音区产出 the owner asked for (version 20261012131940;
    # the old gate printed MCWAIT_ALARM 1 on it), and 10-12 08:46 a 🩺 中继自己报错了 alarm.
    DOC = str(ROOT.parent / "docs" / "NOTIFICATIONS.md")
    real = [json.loads(ln) for ln in (fx_dir(ROOT, "fixtures") / "alerts-e2-report-push.jsonl")
            .read_text(encoding="utf-8").splitlines() if ln.strip()]
    tacet, fault = real
    e = tmpdir()
    (e / "alerts").mkdir()
    (e / "machinecheck.json").write_text(json.dumps({"#63": mc_row(version="20261012131940", event="boot")}),
                                         encoding="utf-8")


    def run_doc(state_dir, version, *rows):
        (Path(state_dir) / "alerts" / "20261013.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = main([state_dir, version, "0", DOC])
        return rc, out.getvalue()


    rc, out = run_doc(str(e), "20261012131940", tacet)
    check("无音区产出 only: exit 0", rc, 0)
    check("it is listed as INFO, not ALARM", ("INFO" in out and "无音区产出" in out, "ALARM" in out), (True, False))
    banner = dict(tacet, title="🎴 明天开新卡池：鸣潮", text="明天 10:00 开新卡池")
    rc, out = run_doc(str(e), "20261012131940", banner)
    check("明天开新卡池：<games> (title cut at the placeholder): exit 0", rc, 0)
    rc, out = run_doc(str(e), "20261012131940", tacet, dict(fault, version="20261012131940"))
    check("a real alarm next to it still fails: exit 1", rc, 1)
    check("only the alarm is an ALARM line", (out.count("ALARM 2026"), "MCWAIT_ALARM 1" in out), (1, True))
    rc, out = run_doc(str(e), "20261012131940", dict(fault, title="🌙 关机被取消", version="20261012131940"))
    check("🌙 关机被取消 is routed `group` in the page, so it counts", rc, 1)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = main([str(e), "20261012131940", "0", str(e / "no-such-page.md")])
    check("page missing: every group push counts again (exit 1, with a NOTE)",
          (rc, "NOTE" in out.getvalue()), (1, True))


def _part_replay():
    import fnmatch
    import json
    import os
    import shutil
    import sys
    import tempfile
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _tmp import fx_dir
    from ark_relay.core import collector

    REPLAY = fx_dir(ROOT, "replay")
    FLOOR = 40          # minimum corpus size, see main()
    # Raised from 10 to 40 on 2026-09-08 when the corpus grew from 1 day (10 records)
    # to 4 days (42): the 09-01 weekly boss stuck on its results page, the 09-04/09-05
    # essence runs farming the wrong region, and 09-01 Endfield's 「赠送干员礼物」
    # failure. The floor exists so the corpus cannot quietly disappear - `.gitignore`'s
    # `*.log` once kept the whole corpus out of the repo, and this test printed
    # "all checks passed" with not a single sample.
    FIELDS = ("okww_steps", "okww_unreachable", "okww_error", "okww_farm", "okww_runs",
              "okww_stamina_spent", "okww_stamina_left", "maaend_name_mismatch", "tasks_failed",
              "tasks_done", "okww_exit_race", "maaend_unreachable", "maaend_unreachable_shape")



    # The os module has PRIO_DARWIN_PROCESS from Python 3.12 on; deploy-relay.sh runs some of these scripts with
    # the system python3 (3.9), where reading it raised AttributeError. 4 is its value in <sys/resource.h>.

    def snapshot(rec) -> dict:
        out = {"script": rec.script, "ok": rec.ok, "failed_tasks": rec.failed_tasks,
               "duration_known": rec.duration_known}
        for k in FIELDS:
            if k in rec.raw:
                out[k] = rec.raw[k]
        return out


    def cases() -> list[tuple[str, Path, Path, object]]:
        """(label, record json, day root, expected) for every record, in the order they are checked."""
        out = []
        for exp_file in sorted(REPLAY.glob("*/*/expected.json")):
            expected = json.loads(exp_file.read_text(encoding="utf-8"))
            day_root = exp_file.parents[2]
            for stem, want in expected.items():
                out.append((f"{exp_file.parent.relative_to(REPLAY)}/{stem}", exp_file.parent / f"{stem}.json",
                            day_root, want))
        return out


    def judge(js: Path, day_root: Path):
        """What the collector makes of one record, as compared with expected.json."""
        rec = collector.parse_record(js, day_root)
        return snapshot(rec) if rec else None




    def judge_all(todo: list[tuple[str, Path, Path, object]]) -> list:
        return [judge(js, day_root) for _, js, day_root, _ in todo]


    def verdict_cases() -> list[tuple[str, Path, Path, dict, dict]]:
        """(label, record json, day root, sidecar, expected) for every record a verdict.json names.

    The outcome check (features/alarm/verdict.py) reads more than the record: MaaEnd's
    own app log (whose wrap-up line tells 「did not exit」 apart). A sample that brings
    it lists it per record in verdict.json: {stem: {"maaend_debug": [file, ...],
    "want": {"says": first line or null, "maaend_no_self_exit": bool}}}. Added
    2026-10-11 so the deploy gate's replay pass reaches verdict.py on a real run
    (changed_covered.py: 「判定类模块改了却没有回放案例跑到」).
    """
        out = []
        for vf in sorted(REPLAY.glob("*/*/verdict.json")):
            for stem, spec in json.loads(vf.read_text(encoding="utf-8")).items():
                out.append((f"{vf.parent.relative_to(REPLAY)}/{stem} (verdict)", vf.parent / f"{stem}.json",
                            vf.parents[2], spec, spec.get("want") or {}))
        return out


    def verdict_judge(js: Path, day_root: Path, spec: dict) -> dict:
        """What the outcome check makes of one record, with its sidecar files where the relay reads them."""
        from ark_relay.core.ledger import State
        from ark_relay.features import handle, handle as verdict
        rec = collector.parse_record(js, day_root)
        with tempfile.TemporaryDirectory() as tmp:
            maaend = Path(tmp) / "maaend"
            (maaend / "debug").mkdir(parents=True)
            for name in spec.get("maaend_debug") or []:
                # The relay reads only debug/20??-??-??-*.log (gamelogs._maaend_app_log); a
                # fixture-style name like app-2026-10-10-3.log would be skipped without a word
                # and the run judged as if MaaEnd's own log were missing.
                if not fnmatch.fnmatch(name, "20??-??-??-*.log"):
                    raise ValueError(f"{js.parent / 'verdict.json'}: {name!r} is not named the way MaaEnd "
                                 "names its app log (2026-10-10-3.log), the relay would not read it")
                dst = maaend / "debug" / name
                shutil.copy(js.parent / name, dst)
                # MaaEnd writes its log during the run: dated at the run's end, not at the copy
                os.utime(dst, (rec.finished.timestamp(), rec.finished.timestamp()))
            eng = type("Eng", (), {})()
            eng.cfg = type("Cfg", (), {"maaend_dir": str(maaend), "history_dir": None, "automas_dir": None,
                                       "maa_dir": None, "state_dir": None})()
            eng.state = State(Path(tmp) / "state")
            eng.state.append_ledger(rec)
            real_ship = handle._ship_evidence
            handle._ship_evidence = lambda eng, rec: None      # never upload from a test
            try:
                says = verdict._verify_outcome(eng, rec)
            finally:
                handle._ship_evidence = real_ship
        return {"says": says.splitlines()[0] if says else None,
                "maaend_no_self_exit": "maaend_no_self_exit" in rec.raw}


    def main() -> int:
        fails = []
        todo = cases()
        n = len(todo)
        for (label, _, _, want), got in zip(todo, judge_all(todo), strict=True):
            if got != want:
                fails.append(label)
                print(f"  ✗ {label}")
                for k in sorted(set(want or {}) | set(got or {})):
                    if (got or {}).get(k) != (want or {}).get(k):
                        print(f"      {k}: 期望 {(want or {}).get(k)!r} 实际 {(got or {}).get(k)!r}")
            else:
                print(f"  ✓ {label}")
        for label, js, day_root, spec, want in verdict_cases():
            got = verdict_judge(js, day_root, spec)
            if got != want:
                fails.append(label)
                print(f"  ✗ {label}: 期望 {want!r} 实际 {got!r}")
            else:
                print(f"  ✓ {label}")
        # The floor: finding no corpus at all must never pass. Both gates look only
        # for "passed" on the last line, so "replayed 0, all checks passed" would leave
        # every judging function in the collector unprotected without a word -
        # measured 2026-09-08, after .gitignore swallowed the corpus, that was the output.
        if n < FLOOR:
            fails.append(f"回放样本只找到 {n} 条（至少要有 {FLOOR} 条）"
                     "——语料库丢了、被 .gitignore 挡了，或者目录层级变了")
            print(f"  ✗ 语料库只找到 {n} 条，期望至少 {FLOOR} 条")
        print(f"\n回放 {n} 条，" + (f"FAILED: {len(fails)}" if fails else "all checks passed"))
        return 1 if fails else 0


    if __name__ == "__main__":
        sys.exit(main())


if __name__ == "__main__":
    sys.exit(run_parts([_part_mc_phone_banners, _part_mc_runs, _part_mc_runs_state_read_fails, _part_mc_system, _part_mc_system_fixes, _part_selfcheck_main, _part_selfcheck_one_push, _part_machinecheck_main, _part_machinecheck_wait, _part_replay]))
