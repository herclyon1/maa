"""Wuthering Waves banners: how the bulletin and the notices are read (2026-10-13 audit).

* Collaboration and memory banners say 「角色联动唤取」 / 「角色忆旅唤取」, not only
  「角色活动唤取」; the pool-name and notice-title patterns took only 活动.
* A bulletin that yields no debut (title or 「全新角色」 format changed) dropped every
  running pool without a log line; it now warns and reports them all.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ark_relay.features.banners.banners as _b
from ark_relay.features.banners import wuwa as W

fails = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


print("[collaboration and memory banners: 联动 / 忆旅 as well as 活动]")
for kind in ("活动", "联动", "忆旅"):
    body = f"<p>全新角色</p><p>5星共鸣者「某人」</p><p>※可通过[某池]角色{kind}唤取获得</p><p>全新武器</p>"
    check(f"bulletin pool name, 角色{kind}唤取", W.parse_wuwa_preview(body), [("某人", "某池")])
    nb = W.parse_wuwa_notice_banners({"recommend": [{
        "tabTitle": f"[某池]角色{kind}唤取",
        "content": "5星角色「某人」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}]})
    check(f"notice banner, 角色{kind}唤取", [(x.name, x.chars) for x in nb], [("某池", ("某人",))])
check("a weapon banner is still not a character banner",
      W.parse_wuwa_notice_banners({"recommend": [{
          "tabTitle": "「碎骨」武器联动唤取",
          "content": "5星武器「某刀」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}]}), [])


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.recs = []

    def emit(self, record):
        self.recs.append((record.levelno, record.getMessage()))


def offline(url, *a, **k):
    raise OSError(f"offline: {url}")


def home(*tabs):
    """A wiki homepage with one character tab per (banner, entry id, start, end)."""
    return {"code": 200, "data": {"contentJson": {"sideModules": [{
        "title": "角色活动唤取",
        "content": {"tabs": [{"name": n, "countDown": {"dateRange": [a, z]},
                              "imgs": [{"linkConfig": {"entryId": e}}]} for n, e, a, z in tabs]}}]}}}


def run_wuwa(now, page, notice, names, catalogue=None):
    """_wuwa against fakes; (banners, next, notes, WARNING messages)."""
    def fake(url, *a, **k):
        if url == W._WW_NOTICE:
            return notice
        if url.endswith("/wiki/core/homepage/getPage"):
            return page
        if url.endswith("/getEntryDetail"):
            eid = dict(x.split("=") for x in a[1].decode().split("&"))["id"]
            return {"code": 200, "data": {"name": names[eid]}}
        if url.endswith("/wiki/core/catalogue/item/getPage"):
            return {"code": 200, "data": {"results": {"records": catalogue or []}}}
        raise OSError(f"offline: {url}")
    g = Grab()
    _b.log.addHandler(g)
    real = _b._json, _b._text
    _b._json, _b._text = fake, offline
    notes: dict = {}
    try:
        got, nxt = _b._wuwa(now, notes=notes, trace=_b.Trace.new())
    finally:
        _b._json, _b._text = real
        _b.log.removeHandler(g)
    return got, nxt, notes, [m for lv, m in g.recs if lv == logging.WARNING]


print("[no debut read from a fetched bulletin: warn, and report the running pools]")
NOW = datetime(2026, 10, 13, 12, 0)
page = home(("某某之池", "1", "2026-10-01 11:00", "2026-10-22 09:59"))
renamed = {"game": [{"tabTitle": "3.7版本更新公告", "content": "<p>全新角色</p><p>5星共鸣者「某人」</p>"}]}
got, _n, _notes, warns = run_wuwa(NOW, page, renamed, {"1": "某人"})
check("bulletin title changed: the running pool is still reported", [b.name for b in got], ["某某之池"])
check("…with a WARNING naming why", [m for m in warns if "读不出这一版的新角色" in m and "版本内容说明" in m] != [], True)
reshaped = {"game": [{"tabTitle": "3.7版本内容说明", "content": "<p>全新角色</p><p>五星角色：某人</p><p>全新武器</p>"}]}
got, _n, _notes, warns = run_wuwa(NOW, page, reshaped, {"1": "某人"})
check("全新角色 format changed: the running pool is still reported", [b.name for b in got], ["某某之池"])
check("…with a WARNING", [m for m in warns if "读不出这一版的新角色" in m and "写法变了" in m] != [], True)
fine = {"game": [{"tabTitle": "3.7版本内容说明",
                  "content": "<p>全新角色</p><p>5星共鸣者「别人」</p><p>※可通过[别的池]角色活动唤取获得</p><p>全新武器</p>"}]}
got, _n, _notes, warns = run_wuwa(NOW, page, fine, {"1": "某人"})
check("a readable debut list still drops a rerun", [b.name for b in got], [])
check("…without that WARNING", [m for m in warns if "读不出这一版的新角色" in m], [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
