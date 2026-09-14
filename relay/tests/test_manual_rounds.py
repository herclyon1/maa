"""Hand-started test runs stay out of the daily report's rows.

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

print("[真实账本：早班那一串（含重试）算队列的，12:57 起的六条算手动]")
queue, manual = core.split_manual(entries, ["09:00", "21:30"])
check("队列 10 条", len(queue), 10)
check("手动 6 条", [m["run_id"].rsplit("/", 1)[-1] for m in manual],
      ["MaaEnd-08-57-04", "MaaEnd-09-03-54", "MaaEnd-09-06-20", "MaaEnd-09-08-10", "MaaEnd-09-37-59", "MaaEnd-09-43-32"])
check("队列里的重试没被当成手动（11:21 那趟离 09:00 两小时）",
      any(e["run_id"].endswith("MaaEnd-07-20-27") for e in queue), True)

print("\n[没有排班时间就分不出来，全部算队列的]")
q2, m2 = core.split_manual(entries, [])
check("全在队列里", (len(q2), m2), (16, []))

print("\n[日报只列队列的，手动那几趟不成行]")
title, body = core.format_daily("2026-09-14", queue)
check("没有 12:57 那趟", "12:57" in body, False)
check("早班的终末地还在", "MaaEnd" in body, True)
t_all, b_all = core.format_daily("2026-09-14", entries)
check("不过滤的话它们本来会出现", "12:58→13:03" in b_all, True)

print("\n[AUTO-MAS 自己没拉起模拟器的那一秒不成行（10:51 那条）]")
check("旧记录里 transitional 还是 False", next(e for e in entries if e["run_id"].endswith("06-51-56"))["transitional"], False)
check("日报里没有「模拟器启动失败」", "模拟器启动失败" in body, False)
check("也没有那条 10:51 时长未知", "10:51　时长未知" in body, False)
check("标题不因它算失败", "失败" in title, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
