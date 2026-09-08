"""三家停服维护公告解析——夹具是 2026-09-02/03 从官网原样抓的页面。"""
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

def fake_get(url):
    m = {"https://ak.hypergryph.com/news": "ak_news.html", "https://ak.hypergryph.com/news/5102": "ak_5102.html",
         "https://endfield.hypergryph.com/news": "ef_news.html", "https://endfield.hypergryph.com/news/1164": "ef_1164.html",
         M._WW_NOTICE: "ww_notice.json"}
    name = m.get(url)
    if not name:
        raise KeyError(url)
    return (FX / name).read_text(encoding="utf-8", errors="replace")

now = datetime(2026, 9, 3, 0, 30, tzinfo=SERVER_TZ)
ak = M.arknights_window(now, get=fake_get)
check("方舟：09-04 06:00–12:00", (ak[0].strftime("%m-%d %H:%M"), ak[1].strftime("%H:%M")) if ak else None, ("09-04 06:00", "12:00"))
ef = M.endfield_window(now, get=fake_get)
check("终末地：09-02 06:00–12:00", (ef[0].strftime("%m-%d %H:%M"), ef[1].strftime("%H:%M")) if ef else None, ("09-02 06:00", "12:00"))
ww = M.wuwa_window(now, get=fake_get)
check("鸣潮：08-20 04:00–11:00", (ww[0].strftime("%m-%d %H:%M"), ww[1].strftime("%H:%M")) if ww else None, ("08-20 04:00", "11:00"))
src = {"明日方舟": lambda n: ak, "终末地": lambda n: ef, "鸣潮": lambda n: ww}
check("09-04 当天：只有方舟在维护", list(M.today(datetime(2026, 9, 4, 8, 46, tzinfo=SERVER_TZ), sources=src)), ["明日方舟"])
check("09-02 当天：只有终末地", list(M.today(datetime(2026, 9, 2, 8, 46, tzinfo=SERVER_TZ), sources=src)), ["终末地"])
check("09-03：谁都不维护", M.today(datetime(2026, 9, 3, 8, 46, tzinfo=SERVER_TZ), sources=src), {})
bad = {"明日方舟": lambda n: (_ for _ in ()).throw(OSError("net"))}
check("取不到就当没有，不炸", M.today(now, sources=bad), {})
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
