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

print("\n[audit 11-08 B-01: readers of a ledger entry's log find v5.8's <date>/<record id>/0.log]")
if True:
    from ark_relay.core.ledger import strip_incomplete_items
    from ark_relay.features.makeup import collect_retry as cr
    from ark_relay.features.verify import outcome
    end = by.get("2026-10-28/endfield/MaaEnd-05-33-08")
    entry = {"script": "MaaEnd", "run_id": end.run_id, "raw": dict(end.raw)} if end else {}
    got = collector.resolve_history_log(history, entry)
    check("resolve_history_log finds the 0.log by the record id", got and got.parts[-3:],
          ("2026-10-28", "b6acb2fc-cd77-4f28-86dd-6f192c7d2f86", "0.log"))
    check("no record id and no old .log: None", collector.resolve_history_log(history, {"run_id": "2026-10-28/x/y"}), None)
    check("the gathering retry reads the day's MaaEnd log (was: never found, so never retried)",
          cr._history_log(history, entry) == got, True)
    ok = outcome.latest_okww_run_log(FX / "history")
    check("latest_okww_run_log finds an OK-WW 0.log through history.db (was: only OK-WW-*.log)",
          bool(ok) and ok[0].parts[-2] in ("978d8567-f7bf-4f9f-b402-6afca1880ba0",
                                           "a1a4259e-e90d-4749-bbbd-57f63d6ffd62"), True)
    two = ("MaaEnd 这一轮有 2 项没干成，但它自己没报错：\n· 自动采集 真的走了路线：30 秒就报\n"
           "· 基质刷取 真的刷了：5 秒就报\n干成的：MaaEnd 跑完")
    check("a re-walked gathering clears only its own item", strip_incomplete_items(two, cr.GATHERING_UNDONE),
          "MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n· 基质刷取 真的刷了：5 秒就报\n干成的：MaaEnd 跑完")
    check("gathering the only item: cleared",
          strip_incomplete_items("MaaEnd 这一轮有 1 项没干成，但它自己没报错：\n· 自动采集 真的走了路线：x", cr.GATHERING_UNDONE), "")
    check("the gathering settings item is not the retry's to clear",
          strip_incomplete_items("MaaEnd 这一轮没按你的设置跑：\n· 自动采集的设置：3 个路线选项", cr.GATHERING_UNDONE),
          "MaaEnd 这一轮没按你的设置跑：\n· 自动采集的设置：3 个路线选项")
    fw = ("[2026-10-27 22:10:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15End\"}\n"
          "[2026-10-28 10:05:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15Failed\"}\n")
    check("yesterday's later clock time is not after today's retry start",
          cr.judge(fw, ["AutoCollectRoute15"], "2026-10-28 10:00:00"), {"AutoCollectRoute15": False})
    fw2 = ("[2026-10-27 23:58:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15Start\"}\n"
           "[2026-10-28 00:03:00.000][INF] x [msg=Node.Action.Starting] {\"name\":\"AutoCollectRoute15End\"}\n")
    check("a retry begun before midnight still reads the lines after it",
          cr.judge(fw2, ["AutoCollectRoute15"], "2026-10-27 23:57:00"), {"AutoCollectRoute15": True})

print("\n[audit 11-08 B-07: history.db failing in a row, a same-second row, a 0.log not there yet]")
if True:
    import logging
    import sqlite3

    class _Cap(logging.Handler):
        def __init__(self):
            super().__init__()
            self.rows = []

        def emit(self, r):
            self.rows.append((r.levelname, r.getMessage()))
    cap = _Cap()
    logging.getLogger(collector.log.name).addHandler(cap)
    bad = tmpdir() / "bad" / "automas"
    (bad / "data").mkdir(parents=True)
    (bad / "history").mkdir()
    (bad / "data" / "history.db").write_bytes(b"not a database at all" * 100)
    collector._db_fail_streak[0] = 0
    for _ in range(5):
        collector._db_rows(bad / "history")
    warns = [m for lv, m in cap.rows if lv == "WARNING" and "history.db" in m]
    check("unreadable 5 times in a row: one WARNING (at the 3rd)", len(warns), 1)
    collector._db_rows(FX / "history")
    check("read again: the streak is reset", collector._db_fail_streak[0], 0)
    logging.getLogger(collector.log.name).removeHandler(cap)

    twin = tmpdir() / "twin"
    shutil.copytree(FX, twin / "automas")
    db = twin / "automas" / "data" / "history.db"
    con = sqlite3.connect(db)
    row = list(con.execute("SELECT * FROM records WHERE script_name='MAA'").fetchone())
    cols = [r[1] for r in con.execute("pragma table_info(records)")]
    row[cols.index("id")] = "0badc0de-0000-0000-0000-000000000000"
    row[cols.index("timestamp")] = row[cols.index("timestamp")] + 0.2      # same second, a bit later
    row[cols.index("log_path")] = "2026-10-28/0badc0de-0000-0000-0000-000000000000/0.log"
    con.execute(f"INSERT INTO records VALUES ({','.join('?' * len(row))})", row)
    con.commit()
    con.close()
    th = twin / "automas" / "history"
    shutil.copytree(th / "2026-10-28" / "71bade62-8710-47f9-bd0d-3ef3f4efab47",
                    th / "2026-10-28" / "0badc0de-0000-0000-0000-000000000000")
    ids = sorted(r.run_id for r in collector.scan(th, set()) if r.script == "MAA")
    check("two MAA rows of one second: both booked, the later one suffixed",
          ids, ["2026-10-28/arknights/MAA-05-01-00", "2026-10-28/arknights/MAA-05-01-00-0badc0de"])
    (th / "2026-10-28" / "0badc0de-0000-0000-0000-000000000000" / "0.log").unlink()
    collector._db_log_missing.clear()
    ids = [r.run_id for r in collector.scan(th, {"2026-10-28/arknights/MAA-05-01-00"}) if r.script == "MAA"]
    check("its 0.log not there yet: waited for, not booked without it", ids, [])

if fails:
    print(f"✗ {len(fails)} 项不过")
    sys.exit(1)
print("PASS test_collect_history_db")
