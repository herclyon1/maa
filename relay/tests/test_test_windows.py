"""Records inside a marked test window stay out of the daily report's rows.

Fixture: the real ledger of 2026-09-14 - the 09:00 queue (rows 0-9, retries
included, running until 11:49) and then my test dispatches from 12:57 (two
killed runs, one gathering-only run with two retries).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import core

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


FIX = Path(__file__).resolve().parent / "fixtures" / "ledger-2026-09-14" / "ledger.jsonl"
entries = [json.loads(x) for x in FIX.read_text(encoding="utf-8").splitlines() if x.strip()]
check("样本 16 条", len(entries), 16)

print("[真实账本 + 标记的测试窗口：窗口里的六条收起，其余全是正常行]")
windows = [{"since": "2026-09-14T12:50:00+08:00", "until": "2026-09-14T13:50:00+08:00", "what": "MaaEnd"}]
queue, tests = core.split_test(entries, windows)
check("正常 10 条", len(queue), 10)
check("测试 6 条", [m["run_id"].rsplit("/", 1)[-1] for m in tests],
      ["MaaEnd-08-57-04", "MaaEnd-09-03-54", "MaaEnd-09-06-20", "MaaEnd-09-08-10", "MaaEnd-09-37-59", "MaaEnd-09-43-32"])
check("队列里的重试照旧是正常行", any(e["run_id"].endswith("MaaEnd-07-20-27") for e in queue), True)

print("\n[没有标记窗口：手动跑的也是正常行（版本更新后的手动重跑必须进日报）]")
q2, t2 = core.split_test(entries, [])
check("全部是正常行", (len(q2), t2), (16, []))
q3, t3 = core.split_test(entries, [{"since": "bad"}])
check("坏窗口当没有", (len(q3), t3), (16, []))

print("\n[窗口没关（until 为空）：从 since 起全算测试——所以测完必须 test-off]")
q4, t4 = core.split_test(entries, [{"since": "2026-09-14T12:50:00+08:00", "until": None}])
check("12:50 以后的全收起", len(t4), 6)

print("\n[日报只列正常的，测试那几趟不成行]")
title, body = core.format_daily("2026-09-14", queue)
check("没有 12:57 那趟", "12:58→13:03" in body, False)
check("早班的终末地还在", "MaaEnd" in body, True)
t_all, b_all = core.format_daily("2026-09-14", entries)
check("不标记的话它们本来会出现", "12:58→13:03" in b_all, True)

print("\n[AUTO-MAS 自己没拉起模拟器的那一秒不成行（10:51 那条）]")
check("旧记录里 transitional 还是 False", next(e for e in entries if e["run_id"].endswith("06-51-56"))["transitional"], False)
check("日报里没有「模拟器启动失败」", "模拟器启动失败" in body, False)
check("也没有那条 10:51 时长未知", "10:51　时长未知" in body, False)
check("标题不因它算失败", "失败" in title, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
