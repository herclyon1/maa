"""The Wuthering Waves version-news post: a door's miss is INFO, no door is one WARNING.

10-05 21:47:23 (#58) 「库街区官方资讯里没找到 3.7 版本资讯帖」 was a WARNING on its
own, before the Bilibili copy was even asked. Every WARNING is pushed to the
group now (2026-10-06; the user: 「你正常情况应该一条都不发的」), so the rule is:
库街区 missing the post while Bilibili has it is INFO; neither giving the
second half's time is one WARNING naming what each door said. A 库街区 answer
without a list is a source problem (KuroListProblem, kept in the trace), not
"no post". Fixtures are the real 3.7 post (库街区 list 10-01, Bilibili feed,
the poster's OCR) as test_banners.py uses them; no network.
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import banners as _b
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

    def warnings(self):
        return [m for lv, m in self.recs if lv >= logging.WARNING]


logs = Logs()
_b.log.addHandler(logs)
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

print("\n[库街区回的不是列表：记成来源问题，B 站有就不报 WARNING]")
logs.recs.clear()
tr = _b.Trace.new()
got = _b._wuwa_poster_span("3.7", "余心所向九死未悔", "锁暝", now, read, tr,
                           lambda p, d: {"code": 220, "msg": "系统繁忙", "data": None}, bili(feed))
check("还是拿到时间", got, span)
check("不报 WARNING", logs.warnings(), [])
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

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
