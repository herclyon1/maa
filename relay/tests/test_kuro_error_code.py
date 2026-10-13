"""库街区 answering HTTP 200 with an error code in the body is a failed fetch.

Every saved success carries "code": 200. An error body ({"code": <other>,
"data": null}) used to read as an empty list or an empty post at four places -
_kuro_gacha, _wuwa_first_half_end, _wuwa (wiki homepage / entry names) and
update_wuwa_history - i.e. "nothing found", with no log line. Each now raises
KuroAnswerProblem into that place's existing failure path.
"""
import json
import logging
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ark_relay.features.banners.banners as _b
from ark_relay.features.banners import wuwa as W
from ark_relay.features.banners import wuwa_history as H
from ark_relay.features.banners import wuwa_posters as P

fails = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        fails.append(label)


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.recs = []

    def emit(self, record):
        self.recs.append((record.levelno, record.getMessage()))


ERR = {"code": 1511, "msg": "系统繁忙", "data": None}
NOW = datetime(2026, 10, 13, 12, 0)


def raises(fn):
    try:
        fn()
    except P.KuroAnswerProblem as e:
        return str(e)
    except Exception as e:   # noqa: BLE001 - reported as the wrong kind
        return f"other {type(e).__name__}"
    return None


print("[the check itself]")
ok_body = {"code": 200, "data": {"list": []}}
check("code 200 passes through", P.kuro_checked(ok_body, "x"), ok_body)
check("no code at all is left to the shape checks", P.kuro_checked({"data": {"list": []}}, "x"), {"data": {"list": []}})
check("code 1511 raises and names the code", "code=1511" in (raises(lambda: P.kuro_checked(ERR, "x")) or ""), True)

print("[_kuro_gacha]")
check("an error list raises instead of returning None",
      "code=1511" in (raises(lambda: P._kuro_gacha("3.7", "某池", NOW, lambda path, payload: ERR)) or ""), True)
posts = {"code": 200, "data": {"list": [{"postTitle": "[某池]角色活动唤取", "postId": "9",
                                         "publishTime": int(datetime(2026, 10, 1).timestamp() * 1000)}]}}
check("an error post detail raises too",
      "帖子 9" in (raises(lambda: P._kuro_gacha("3.7", "某池", NOW,
                                                 lambda path, payload: posts if path == P._KURO_NEWS else ERR)) or ""), True)

print("[_wuwa_first_half_end: the failure is listed and warned about]")
g = Grab()
_b.log.addHandler(g)
try:
    end = W._wuwa_first_half_end("3.8", NOW, None, _b.Trace.new(), lambda path, payload: ERR, None)
finally:
    _b.log.removeHandler(g)
check("no end", end, None)
check("one WARNING naming the failed notice fetch",
      [m for lv, m in g.recs if lv == logging.WARNING and "库街区唤取公告取不到" in m and "KuroAnswerProblem" in m] != [], True)

print("[_wuwa: the wiki homepage error is \"not read\", an entry error is warned]")
real = _b._json, _b._text


def offline(url, *a, **k):
    raise OSError("offline")


_b._json, _b._text = (lambda url, *a, **k: ERR if url.endswith("/homepage/getPage") else offline(url)), offline
try:
    why = raises(lambda: _b._wuwa(NOW, notes={}, trace=_b.Trace.new()))
finally:
    _b._json, _b._text = real
check("homepage error body raises (collect records it as not read)", "/wiki/core/homepage/getPage" in (why or ""), True)

home = json.loads((Path(__file__).parent / "fixtures" / "wuwa_home.json").read_text(encoding="utf-8"))
g = Grab()
_b.log.addHandler(g)
_b._json = lambda url, *a, **k: (home if url.endswith("/homepage/getPage")
                                 else ERR if url.endswith("/getEntryDetail") else offline(url))
_b._text = offline
try:
    try:
        _b._wuwa(NOW, notes={}, trace=_b.Trace.new())
    except Exception:   # noqa: BLE001 - only the entry warning matters here
        pass
finally:
    _b._json, _b._text = real
    _b.log.removeHandler(g)
check("entry name error body: WARNING 查不到名字",
      [m for lv, m in g.recs if lv == logging.WARNING and "查不到名字" in m] != [], True)

print("[update_wuwa_history]")
with tempfile.TemporaryDirectory() as td:
    menu = json.dumps([])
    why = raises(lambda: H.update_wuwa_history(td, NOW, get=lambda path, payload: ERR, article_get=lambda u: menu))
    check("an error list raises (update_history reports the step as not done)", "code=1511" in (why or ""), True)

    two = {"code": 200, "data": {"list": [
        {"postTitle": "[甲]角色活动唤取", "postId": "1", "publishTime": 2},
        {"postTitle": "[乙]角色活动唤取", "postId": "2", "publishTime": 1}]}}
    good = {"code": 200, "data": {"postDetail": {"postContent": [{"contentType": 1, "content": "甲的正文"}]}}}

    def get(path, payload):
        if path == P._KURO_NEWS:
            return two
        return good if payload["postId"] == "1" else ERR
    why = raises(lambda: H.update_wuwa_history(td, NOW, get=get, article_get=lambda u: menu))
    cache = json.loads((Path(td) / "banners" / "ww-notices.json").read_text(encoding="utf-8"))
    check("an error post raises", "帖子 2" in (why or ""), True)
    check("the post fetched before it is kept, the failed one is not cached as empty",
          sorted(cache["text"]), ["1"])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
