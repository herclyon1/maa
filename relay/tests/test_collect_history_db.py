"""AUTO-MAS v5.8.0-beta.2 records runs in data/history.db, not in per-run JSON files.

The machine updated itself to it on 2026-10-28 08:47. The relay read only the JSON
layout, booked none of that morning's runs (MAA 09:01, OK-WW 09:18 and 09:19, MaaEnd
09:33) and pushed 「早班 没有运行」 at 10:04 (ledger #120). The fixture is that
morning's real history.db and the five 0.log files it points to.
"""
import shutil
import sys
from datetime import timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.core import collector
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


FX = Path(__file__).resolve().parent / "fixtures" / "automas-58-history-2026-10-28"
BJ = timezone(timedelta(hours=8))

if True:
    root = tmpdir() / "automas"
    shutil.copytree(FX, root)
    history = root / "history"

    recs = collector.scan(history, set())
    by = {r.run_id: r for r in recs}
    print("scan 读到：", [(r.run_id, r.script, r.ok) for r in recs])

    check("读到 4 趟（MaaEnd 装更新那一条不算一趟）", len(recs), 4)
    check("run_id 跟旧格式同一种形状", sorted(by), sorted([
        "2026-10-28/arknights/MAA-05-01-00",
        "2026-10-28/wuwa/OK-WW-05-18-01",
        "2026-10-28/wuwa/OK-WW-05-19-51",
        "2026-10-28/endfield/MaaEnd-05-33-08",
    ]))

    maa = by.get("2026-10-28/arknights/MAA-05-01-00")
    if maa:
        check("MAA 成功", maa.ok)
        check("MAA 开始时间（北京）取日志第一行 09:01", maa.started.astimezone(BJ).strftime("%H:%M"), "09:01")
        check("MAA 结束时间（北京）取日志最后一行 09:17", maa.finished.astimezone(BJ).strftime("%H:%M"), "09:17")
        check("MAA 理智从 {kind, value} 拆出来是 2", maa.raw.get("sanity"), 2)
        check("MAA 掉落从 {kind, value} 拆出来、按关卡摊平", (maa.raw.get("drop_statistics") or {}).get("固源岩"), 24)
        check("MAA 公招统计从 {kind, value} 拆出来", maa.raw.get("recruit_statistics"), {"4★": 2, "3★": 1})
        check("MAA 带着 AUTO-MAS 的记录编号", maa.raw.get("automas_record_id"), "71bade62-8710-47f9-bd0d-3ef3f4efab47")
        check("MAA 日志路径是 0.log", maa.log_path and maa.log_path.name, "0.log")

    first = by.get("2026-10-28/wuwa/OK-WW-05-18-01")
    if first:
        check("OK-WW 游戏更新那一趟算过渡、不算失败", (first.transitional, first.failed_tasks), (True, []))
        check("OK-WW 脚本名从前缀读出", first.script, "OK-WW")
    okww = by.get("2026-10-28/wuwa/OK-WW-05-19-51")
    check("OK-WW 重跑那一趟成功", bool(okww and okww.ok))
    end = by.get("2026-10-28/endfield/MaaEnd-05-33-08")
    check("MaaEnd 成功", bool(end and end.ok))
    if end:
        check("MaaEnd 结束时间（北京）10:03", end.finished.astimezone(BJ).strftime("%H:%M"), "10:03")

    # already seen: nothing comes back
    check("都记过的再扫一遍是空的", collector.scan(history, set(by)), [])

    # no history.db (AUTO-MAS before v5.8.0-beta.2): the JSON layout alone, no error
    (root / "data" / "history.db").unlink()
    check("没有 history.db 时什么也不读、不报错", collector.scan(history, set()), [])

if fails:
    print(f"✗ {len(fails)} 项不过")
    sys.exit(1)
print("PASS test_collect_history_db")
