"""三家停服维护公告解析——夹具是 2026-09-02/03 从官网原样抓的页面。"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import maintenance as M
from ark_relay.config import SERVER_TZ

FX = Path(__file__).parent / "fixtures" / "maint"
fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

from ark_relay import banners as B                                  # noqa: E402

FXT = FX.parent
# The JSON endpoints, recorded 2026-10-07 (the Wuthering Waves site's article
# index and its 3.6 预告 2026-09-12); the in-game notice is of 2026-09-02.
JSON_FX = {B._AK_NEWS_API.format(cat="ANNOUNCEMENT", page=1): FX / "ak_announcement_p1.json",
           B._AK_POST.format(cid="5102"): FX / "ak_5102.json",
           B._EF_CMS_LIST.format(page=1): FX / "ef_list_p1.json",
           B._EF_CMS_POST.format(cid="1164"): FX / "ef_1164.json",
           B._WW_SITE_ARTICLES: FXT / "wuwa_site_articles_2026-09-12.json",
           B._WW_SITE_ARTICLE.format(id="5282"): FXT / "wuwa_site_article_5282.json",
           M._WW_NOTICE: FX / "ww_notice.json"}
asked = []


def fake_get(url):
    asked.append(url)
    f = JSON_FX.get(url)
    if not f:
        raise KeyError(url)
    return f.read_text(encoding="utf-8", errors="replace")

now = datetime(2026, 9, 3, 0, 30, tzinfo=SERVER_TZ)
ak = M.arknights_window(now, get=fake_get)
check("方舟：09-04 06:00–12:00", (ak[0].strftime("%m-%d %H:%M"), ak[1].strftime("%H:%M")) if ak else None, ("09-04 06:00", "12:00"))
check("方舟：公告标题进证据", "[明日方舟]09月04日06:00版本更新停机维护公告" in ak[2], True)
check("方舟：只读公告页的列表和那一帖（接口）", [u for u in asked if "hypergryph" in u],
      [B._AK_NEWS_API.format(cat="ANNOUNCEMENT", page=1), B._AK_POST.format(cid="5102")])
ef = M.endfield_window(now, get=fake_get)
check("终末地：09-02 06:00–12:00", (ef[0].strftime("%m-%d %H:%M"), ef[1].strftime("%H:%M")) if ef else None, ("09-02 06:00", "12:00"))
check("终末地：取的是预告帖 1164", ef[2], "官方公告：「雪凇幽梦」版本预下载与更新预告（09-02 06:00–12:00）")
# The page bodies of 2026-09-02/03 read the same windows as the endpoints' posts.
check("方舟：旧网页正文与接口正文窗口一致",
      M._AK_BODY.search(M._text((FX / "ak_5102.html").read_text(encoding="utf-8", errors="replace"))).groups(),
      M._AK_BODY.search(B.ak_post_text(fake_get, "5102")).groups())
check("终末地：旧网页正文与接口正文窗口一致",
      M._EF_BODY.search(M._text((FX / "ef_1164.html").read_text(encoding="utf-8", errors="replace"))).groups(),
      M._EF_BODY.search(B._ef_cms_text(json.loads(fake_get(B._EF_CMS_POST.format(cid="1164")))["data"]["data"])).groups())
# A reply that is not code 0 is a failure, never "no maintenance".
bad_code = lambda u: '{"code":1,"msg":"x"}'  # noqa: E731
for name, fn in (("方舟", M.arknights_window), ("终末地", M.endfield_window)):
    try:
        fn(now, get=bad_code)
        check(f"{name}：code 不是 0 要报错", "没报错", "报错")
    except ValueError:
        check(f"{name}：code 不是 0 要报错", "报错", "报错")

# Wuthering Waves: the site's 3.6 预告 (posted 08-13) a week ahead, the in-game
# notice not asked; once the window is over, the in-game notice.
asked.clear()
ww_pre = M.wuwa_window(datetime(2026, 8, 15, 9, 0, tzinfo=SERVER_TZ), get=fake_get)
check("鸣潮：官网维护预告提前一周给出 08-20 04:00–11:00",
      (ww_pre[0].strftime("%m-%d %H:%M"), ww_pre[1].strftime("%H:%M"), ww_pre[2]) if ww_pre else None,
      ("08-20 04:00", "11:00", "官方公告：《鸣潮》3.6版本更新维护预告（08-20 04:00–11:00）"))
check("鸣潮：有预告就不读游戏内公告", M._WW_NOTICE in asked, False)
check("鸣潮：维护当天照样是预告的窗口",
      M.wuwa_window(datetime(2026, 8, 20, 8, 0, tzinfo=SERVER_TZ), get=fake_get)[0].strftime("%m-%d %H:%M"), "08-20 04:00")
asked.clear()
ww = M.wuwa_window(now, get=fake_get)
check("鸣潮：08-20 04:00–11:00", (ww[0].strftime("%m-%d %H:%M"), ww[1].strftime("%H:%M")) if ww else None, ("08-20 04:00", "11:00"))
check("鸣潮：预告的窗口过了，读游戏内公告", M._WW_NOTICE in asked, True)
src = {"明日方舟": lambda n: ak, "终末地": lambda n: ef, "鸣潮": lambda n: ww}
check("09-04 当天：只有方舟在维护", list(M.today(datetime(2026, 9, 4, 8, 46, tzinfo=SERVER_TZ), sources=src)), ["明日方舟"])
check("09-02 当天：只有终末地", list(M.today(datetime(2026, 9, 2, 8, 46, tzinfo=SERVER_TZ), sources=src)), ["终末地"])
check("09-03：谁都不维护", M.today(datetime(2026, 9, 3, 8, 46, tzinfo=SERVER_TZ), sources=src), {})
bad = {"明日方舟": lambda n: (_ for _ in ()).throw(OSError("net"))}
check("取不到就当没有，不炸", M.today(now, sources=bad), {})
failed = []
M.today(now, sources={**bad, "终末地": lambda n: None}, failed=failed)
check("取不到的记进 failed，读到了没有的不记", failed, ["明日方舟"])
# ---- 明日安排里的维护提示（用户 2026-09-03：「这个务必要体现」）----
# maintenance_lines 是这条要求唯一的落点，之前没有任何测试碰过它。漏掉这一行，
# 队列会在停服时段照常开跑：全是失败，客户端也不会更新。
from ark_relay import plan as P                                     # noqa: E402
from datetime import date                                           # noqa: E402

_real_today = M.today
M.today = lambda at: {"明日方舟": ak}
lines = P.maintenance_lines(date(2026, 9, 4))
check("维护当天出一行", len(lines), 1)
check("点名游戏", "明日方舟" in lines[0], True)
check("写清窗口", "09-04 06:00–12:00" in lines[0], True)
check("说清当天不跑它", "当天队列里不跑它" in lines[0], True)
check("说清跑完就更新客户端", "更新客户端" in lines[0], True)
check("说清开服后补跑", "12:00 开服后单独补跑" in lines[0], True)

M.today = lambda at: {"明日方舟": ak, "终末地": ef}
check("两家维护就出两行", len(P.maintenance_lines(date(2026, 9, 4))), 2)

M.today = lambda at: {}
check("没人维护就一行都不出", P.maintenance_lines(date(2026, 9, 3)), [])

M.today = lambda at: (_ for _ in ()).throw(OSError("net"))
check("取不到公告时安静返回空，不许把明日安排带走", P.maintenance_lines(date(2026, 9, 4)), [])
M.today = _real_today

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
