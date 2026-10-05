"""A MaaEnd that stopped between two tasks is not a finished round.

`_judge_result` overrules AUTO-MAS in two places when MaaEnd's own log says the
round was done: 「部分任务执行失败: X」 (AUTO-MAS's stale name table, 2026-09-06
SellProduct -> 据点交易) and 「MaaEnd 进程超时」 (done, then never exited,
2026-09-28 11:22). Both used to accept any log in which every started task also
completed. A MaaEnd that died or was killed right after one task's 「任务完成」
leaves exactly such a log, while the tasks AUTO-MAS names never started - and the
run went into the ledger and the daily report as green.

The round is finished only when its closing task (「❌关闭游戏（PC）」 since
2026-09-18, 「⛔ 结束进程」 before) ran last and completed.

Real data: fixtures/maaend-farm-drops/2026-09-28a.log (the 09-28 11:22
done-then-hung run, ends with 关闭游戏（PC） at lines 811-812) and
fixtures/maaend_full_2026-09-01.log (ends with 结束进程 at lines 49-50). The
stopped-between-tasks logs are real prefixes of 2026-09-28a.log.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from ark_relay import collector
sys.path.insert(0, str(HERE))
from _tmp import tmpdir

FIX = HERE / "fixtures"
LOG_0928 = (FIX / "maaend-farm-drops" / "2026-09-28a.log").read_text(encoding="utf-8").splitlines(keepends=True)
LOG_0901 = (FIX / "maaend_full_2026-09-01.log").read_text(encoding="utf-8")
# Line 164 starts 环境监测, line 165 completes it, and line 166 starts the next task.
assert "任务完成: 🌿环境监测" in LOG_0928[164], LOG_0928[164]
assert "任务开始: 🌿环境监测" in LOG_0928[163], LOG_0928[163]
assert "任务完成: ❌关闭游戏（PC）" in LOG_0928[-1], LOG_0928[-1]
STOPPED = "".join(LOG_0928[:165])     # stopped right after 环境监测 completed
STUCK = "".join(LOG_0928[:164])       # 环境监测 started, never ended
FULL = "".join(LOG_0928)

fails = []
root = tmpdir()
day = root / "2026-09-28" / "endfield"
day.mkdir(parents=True)
_n = [0]


def record(result, log, stem=None):
    _n[0] += 1
    stem = stem or f"MaaEnd-06-{_n[0]:02d}-00"
    (day / f"{stem}.json").write_text(json.dumps({"maaend_result": result}, ensure_ascii=False), encoding="utf-8")
    (day / f"{stem}.log").write_text(log, encoding="utf-8")
    return stem, collector.parse_record(day / f"{stem}.json", root)


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


print("[stopped after 环境监测; AUTO-MAS lists 自动采集, which never started]")
stem_stopped, r = record("[日常] MaaEnd 部分任务执行失败: 🧺自动采集", STOPPED)
check("not a success", r.ok, False)
check("keeps AUTO-MAS's list", r.failed_tasks, ["自动采集"])
check("not marked as a name mismatch", r.raw.get("maaend_name_mismatch"), None)

print("\n[stopped after 环境监测, killed for 进程超时]")
_, r = record("MaaEnd 进程超时", STOPPED)
check("not a success", r.ok, False)
check("says it timed out", r.failed_tasks, ["MaaEnd 进程超时"])
check("not marked done-then-hung", r.raw.get("maaend_done_then_hung"), None)

print("\n[the full 09-28 11:22 log, killed for 进程超时 -> done, then hung]")
_, r = record("MaaEnd 进程超时", FULL)
check("ok", r.ok, True)
check("no failures", r.failed_tasks, [])
check("marked done-then-hung", r.raw.get("maaend_done_then_hung"), True)

print("\n[the full 09-28 log, AUTO-MAS cannot match a renamed task (关闭游戏 era)]")
_, r = record("MaaEnd 部分任务执行失败: SellProduct", FULL)
check("ok", r.ok, True)
check("records the name AUTO-MAS missed", r.raw.get("maaend_name_mismatch"), ["SellProduct"])

print("\n[the full 09-01 log, renamed task (结束进程 era)]")
d01 = root / "2026-09-01" / "endfield"
d01.mkdir(parents=True)
(d01 / "MaaEnd-03-00-00.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: SellProduct"}, ensure_ascii=False), encoding="utf-8")
(d01 / "MaaEnd-03-00-00.log").write_text(LOG_0901, encoding="utf-8")
r = collector.parse_record(d01 / "MaaEnd-03-00-00.json", root)
check("ok", r.ok, True)
check("records the name AUTO-MAS missed", r.raw.get("maaend_name_mismatch"), ["SellProduct"])

print("\n[stuck mid-task: 环境监测 started, no end]")
_, r = record("MaaEnd 部分任务执行失败: 🌿环境监测", STUCK)
check("partial failure stays a failure", (r.ok, r.failed_tasks), (False, ["环境监测"]))
_, r = record("MaaEnd 进程超时", STUCK)
check("timeout stays a failure", (r.ok, r.failed_tasks), (False, ["MaaEnd 进程超时"]))

print("\n[never started: the log has no task line at all]")
_, r = record("MaaEnd 部分任务执行失败: 🎁赠送干员礼物", "".join(LOG_0928[:13]))
check("partial failure stays a failure", (r.ok, r.failed_tasks), (False, ["赠送干员礼物"]))
_, r = record("MaaEnd 进程超时", "".join(LOG_0928[:13]))
check("timeout stays a failure", (r.ok, r.failed_tasks), (False, ["MaaEnd 进程超时"]))

print("\n[closing task started but never completed]")
_, r = record("MaaEnd 进程超时", "".join(LOG_0928[:-1]))
check("not a success", r.ok, False)

print("\n[a task started after the closing task]")
_, r = record("MaaEnd 进程超时", FULL + "[2026-09-28 11:22:11.000] 任务开始: 🧺自动采集\n"
              "[2026-09-28 11:22:12.000] 任务完成: 🧺自动采集\n")
check("not a success", r.ok, False)

print("\n[re-judging the ledger only moves towards done]")
run_id = f"2026-09-28/endfield/{stem_stopped}"
old = {"run_id": run_id, "script": "MaaEnd", "ok": False, "failed_tasks": ["自动采集"], "raw": {}}
fresh = collector.refresh_raw(old, root)
check("stopped run stays failed", (fresh.get("ok"), fresh.get("failed_tasks")), (False, ["自动采集"]))
old_ok = {"run_id": run_id, "script": "MaaEnd", "ok": True, "failed_tasks": [], "raw": {}}
fresh = collector.refresh_raw(old_ok, root)
check("an entry already marked ok is left ok", (fresh.get("ok"), fresh.get("failed_tasks")), (True, []))

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
