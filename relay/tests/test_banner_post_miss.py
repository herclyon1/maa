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
"""
import json
import logging
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import banners as _b
from ark_relay import errwatch, texts
from ark_relay.config import SERVER_TZ
from ark_relay.desktop import Line

FX = Path(__file__).parent / "fixtures"
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: 得到 {got!r}，应为 {want!r}")
    if not ok:
        fails.append(label)


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
sys.exit(1 if fails else 0)
