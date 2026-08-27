"""活动结束后的提醒：三天窗口，文案讲的是活动商店。

2026-08-24 运营看到"活动「直到大地变成一颗酸橙」已结束——主关卡若还是活动关，
下一轮必失败，记得换关"，说它过时。查了真机数据：活动是 08-22 03:59 结束的，
距今 2.77 天，**三天窗口本身是生效的**，第二天就会自己消失。过时的是内容——
主关卡早就是 AT-4 这种常驻关，"换关"永远不可能适用。

改成两件事：说活动商店该搬空了（结束后真正还来得及做的事），并写出这条提醒
还会出现多久，免得同一句话连出三天看起来像卡死。
"""
import json, os, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.plan import activity_countdown        # noqa: E402

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

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
