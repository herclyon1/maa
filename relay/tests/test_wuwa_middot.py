"""A debut whose name has a middle dot is not dropped as a rerun.

The Kuro wiki spells 秧秧·玄翎 with U+00B7 (wuwa_catalogue_2026-09-12.json); the
in-game notice spells it 秧秧・玄翎 with U+30FB (maint/ww_notice.json). _wuwa keeps
only the running pools whose character is in the bulletin's 「全新角色」 section,
comparing the strings as they are, so the running debut was filtered out as a
rerun and its line vanished without a warning. Runs _wuwa itself with fakes.
"""
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


WIKI = "秧秧·玄翎"       # U+00B7, as the wiki writes it
GAME = "秧秧・玄翎"       # U+30FB, as the game notice writes it
NOW = datetime(2026, 10, 13, 12, 0)

home = {"code": 200, "data": {"contentJson": {"sideModules": [{
    "title": "角色活动唤取",
    "content": {"tabs": [{"name": "某某之池",
                          "countDown": {"dateRange": ["2026-10-01 11:00", "2026-10-22 09:59"]},
                          "imgs": [{"linkConfig": {"entryId": 777}}]}]}}]}}}
notice = {
    "game": [{"tabTitle": "3.7版本内容说明",
              "content": f"<p>全新角色</p><p>5星共鸣者「{GAME}」</p>"
                         "<p>※可通过[某某之池]角色活动唤取获得</p><p>全新武器</p>"}],
    "recommend": [{"tabTitle": "[某某之池]角色活动唤取",
                   "content": f"5星角色「{GAME}」 活动时间✦ 2026年10月01日11:00 ~ 2026年10月22日09:59"}],
}


def fake_json(url, *a, **k):
    if url == W._WW_NOTICE:
        return notice
    if url.endswith("/wiki/core/homepage/getPage"):
        return home
    if url.endswith("/wiki/core/catalogue/item/getEntryDetail"):
        return {"code": 200, "data": {"name": WIKI}}
    if url.endswith("/wiki/core/catalogue/item/getPage"):
        return {"code": 200, "data": {"results": {"records": []}}}
    raise OSError(f"offline: {url}")


def offline(url, *a, **k):
    raise OSError(f"offline: {url}")


print("[parsers fold every middle dot to U+00B7]")
check("bulletin debut", W.parse_wuwa_preview(notice["game"][0]["content"]), [(WIKI, "某某之池")])
check("notice banner", W.parse_wuwa_notice_banners(notice)[0].chars, (WIKI,))
for dot in ("·", "・", "･", "•", "‧"):
    check(f"U+{ord(dot):04X} folds", W._one_dot(f"秧秧{dot}玄翎"), WIKI)

print("[_wuwa keeps the running debut]")
real = _b._json, _b._text
_b._json, _b._text = fake_json, offline
try:
    tr = _b.Trace.new()
    got, _nxt = _b._wuwa(NOW, notes={}, trace=tr)
finally:
    _b._json, _b._text = real
check("the running debut is reported", [(b.name, b.chars) for b in got], [("某某之池", (WIKI,))])
check("the game notice is matched to it",
      any("游戏公告" in x and "某某之池" in x for x in tr.sources), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
