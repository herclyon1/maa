"""A pinned old post on page 1 does not stop the Bilibili feed paging.

Page 1 of the real feed (ww-bili-feed-2026-10-05.json) starts with a pinned post
from 09-19 above the 10-04/10-05 items. Paging stopped on the page's OLDEST item
being past the cutoff, so once the pinned post aged past it the feed stopped at
page 1 every day and the Bilibili door was closed without a word. It now stops
on the page's NEWEST item.
"""
import json
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ark_relay.features.banners.banners as _b
from ark_relay.features.banners import wuwa_posters as P

fails = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
