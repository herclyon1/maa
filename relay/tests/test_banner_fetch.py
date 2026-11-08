"""Fetching banners and posts: a missed post, Bilibili's pinned post, event expiry, a silent upstream post.

One part per former file, each run on its own (tests/_parts.py): test_banner_post_miss.py, test_bili_pinned_post.py, test_event_expiry.py, test_upstream_post_silent.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


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
    from ark_relay.features.banners import banners as _b
    from ark_relay.features.alarm import errwatch
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.desktop import Line

    FX = Path(__file__).parent / "fixtures"


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
    import ark_relay.features.banners.banners as _b
    from ark_relay.features.banners import wuwa_posters as P


    fx = json.loads((Path(__file__).parent / "fixtures" / "ww-bili-feed-2026-10-05.json").read_text(encoding="utf-8"))
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


def _part_upstream_post_silent():
    """upstream-post.py must tell "the repo has no template" from "gh failed".

Silent-failure audit rows scripts/mac/upstream-post.py:60 and :76: any gh
failure on the ISSUE_TEMPLATE listing or on PULL_REQUEST_TEMPLATE.md read as
"the repo has none". The empty result was written to _parsed.json (which
UPSTREAM_POST_OFFLINE reuses) and `lint <repo> - <draft>` then passed a draft
against no template at all. A real 404 still means "none"; anything else has
to stop the gate and leave the cache alone.

    Formerly test_upstream_post_silent.py.
    """
    import base64
    import contextlib
    import importlib.util
    import io
    import json
    import os
    import subprocess

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / "relay" / "tests"))

    spec = importlib.util.spec_from_file_location("upstream_post", ROOT / "scripts" / "mac" / "upstream-post.py")
    up = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(up)
    os.environ.pop("UPSTREAM_POST_OFFLINE", None)

    REPO = "owner/repo"
    NOT_FOUND = "gh: Not Found (HTTP 404)\n"
    SEEDED = {"bug.md": {"kind": "md", "title": "[Bug]", "labels": [], "fields": [["复现步骤", True]],
                         "route": "issue", "notes": []}}


    def fake_gh(issue_list_err, pr_err):
        """gh that fails the two template reads with the given stderr; issue search returns nothing."""
        def gh(*args):
            path = args[1] if len(args) > 1 else ""
            if path.endswith("/ISSUE_TEMPLATE") and issue_list_err:
                raise subprocess.CalledProcessError(1, ["gh", *args], output="", stderr=issue_list_err)
            if path.endswith("PULL_REQUEST_TEMPLATE.md") and pr_err:
                raise subprocess.CalledProcessError(1, ["gh", *args], output="", stderr=pr_err)
            if "/issues?" in path:
                return ""
            raise AssertionError(f"unexpected gh call {args}")
        return gh


    def run(argv, issue_list_err, pr_err):
        d = tmpdir()
        up.CACHE = d / "cache"
        cached = up.CACHE / REPO.replace("/", "__") / "_parsed.json"
        cached.parent.mkdir(parents=True)
        cached.write_text(json.dumps(SEEDED, ensure_ascii=False), encoding="utf-8")
        before = cached.read_bytes()
        draft = d / "draft.md"
        draft.write_text("# 一个标题\n正文一句话。\n", encoding="utf-8")
        up._gh = fake_gh(issue_list_err, pr_err)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = up.main([a if a != "DRAFT" else str(draft) for a in argv])
        return rc, out.getvalue(), cached.read_bytes() == before, cached


    print("[a real 404 on both still means: the repo has no templates]")
    rc, out, same, cached = run(["lint", REPO, "-", "DRAFT"], NOT_FOUND, NOT_FOUND)
    check("lint with - passes", rc, 0)
    check("the cache now says no templates", json.loads(cached.read_text(encoding="utf-8")), {})

    print("[the issue template listing fails for another reason]")
    rc, out, same, _ = run(["lint", REPO, "-", "DRAFT"], "error connecting to api.github.com\n", NOT_FOUND)
    check("lint refuses (non-zero)", rc != 0, True)
    check("the gh error is printed", "error connecting to api.github.com" in out, True)
    check("the cached templates are untouched", same, True)

    print("[the PR template read fails for another reason]")
    rc, out, same, _ = run(["rules", REPO], NOT_FOUND, "HTTP 502: Bad Gateway\n")
    check("rules exits non-zero", rc != 0, True)
    check("the gh error is printed", "HTTP 502" in out, True)
    check("the cached templates are untouched", same, True)


    print("[one listed issue template fails to fetch for another reason]")
    BUG_MD = "---\nname: Bug\ntitle: \"[Bug] \"\n---\n## 复现步骤\n"
    real_run = subprocess.run


    def fake_run(args, **kw):
        """base64 runs for real; a direct gh call (the pre-fix per-template fetch) fails like the network."""
        if args and args[0] == "gh":
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="error connecting to api.github.com\n")
        return real_run(args, **kw)


    def template_gh(template_err):
        def gh(*args):
            path = args[1] if len(args) > 1 else ""
            if path.endswith("/ISSUE_TEMPLATE"):
                return '["bug.md"]'
            if path.endswith("/ISSUE_TEMPLATE/bug.md"):
                if template_err:
                    raise subprocess.CalledProcessError(1, ["gh", *args], output="", stderr=template_err)
                return base64.b64encode(BUG_MD.encode()).decode()
            if path.endswith("PULL_REQUEST_TEMPLATE.md"):
                raise subprocess.CalledProcessError(1, ["gh", *args], output="", stderr=NOT_FOUND)
            raise AssertionError(f"unexpected gh call {args}")
        return gh


    def run_rules(template_err):
        d = tmpdir()
        up.CACHE = d / "cache"
        rd = up.CACHE / REPO.replace("/", "__")
        rd.mkdir(parents=True)
        (rd / "_parsed.json").write_text(json.dumps(SEEDED, ensure_ascii=False), encoding="utf-8")
        (rd / "bug.md").write_text(BUG_MD, encoding="utf-8")
        before = {f.name: f.read_bytes() for f in rd.iterdir()}
        up._gh = template_gh(template_err)
        up.subprocess.run = fake_run
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = up.main(["rules", REPO])
        finally:
            up.subprocess.run = real_run
        return rc, out.getvalue(), before == {f.name: f.read_bytes() for f in rd.iterdir()}, rd


    rc, out, same, rd = run_rules("error connecting to api.github.com\n")
    check("rules exits non-zero when a template fetch fails", rc != 0, True)
    check("the template fetch error is printed", "error connecting" in out, True)
    check("no cached file was rewritten", same, True)
    rc, out, same, rd = run_rules(None)
    check("a good fetch still exits 0", rc, 0)
    check("and caches the parsed template with its title prefix",
          json.loads((rd / "_parsed.json").read_text(encoding="utf-8")).get("bug.md", {}).get("title"), "[Bug] ")


if __name__ == "__main__":
    sys.exit(run_parts([_part_banner_post_miss, _part_bili_pinned_post, _part_event_expiry, _part_upstream_post_silent]))
