"""活动结束后的提醒：三天窗口，文案讲的是活动商店。

2026-08-24 运营看到"活动「直到大地变成一颗酸橙」已结束——主关卡若还是活动关，
下一轮必失败，记得换关"，说它过时。查了真机数据：活动是 08-22 03:59 结束的，
距今 2.77 天，**三天窗口本身是生效的**，第二天就会自己消失。过时的是内容——
主关卡早就是 AT-4 这种常驻关，"换关"永远不可能适用。

改成两件事：说活动商店该搬空了（结束后真正还来得及做的事），并写出这条提醒
还会出现多久，免得同一句话连出三天看起来像卡死。
"""
import json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core.plan import activity_countdown        # noqa: E402

CN = timezone(timedelta(hours=8))
fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


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
import logging  # noqa: E402
from ark_relay.core import plan as _plan  # noqa: E402


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
check("读不了的说一次", [m for lv, m in _g.lines if lv == logging.WARNING and "活动缓存读不了" in m] != [], True)
n = len(_g.lines)
activity_countdown(None, now=NOW, cache_path=broken)
check("同一个毛病不重复说", len(_g.lines), n)
activity_countdown(None, now=NOW, cache_path=cache("又好了", NOW + timedelta(days=1)))
check("好了以后忘掉，下次坏了再说", "activity" in _plan._last_error, False)
check("还没有缓存（新装的 MAA）：只记一行，不推群",
      (activity_countdown(None, now=NOW, cache_path=TMP / "none.json"),
       [lv for lv, m in _g.lines if "活动缓存还没有" in m]), ("", [logging.INFO]))
_plan.log.removeHandler(_g)
_plan.log.setLevel(_lvl)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
