"""When AUTO-MAS cannot name a renamed MaaEnd task, the relay judges by MaaEnd's own log.

2026-09-06 05:40: MaaEnd v2.28.0-beta.1 relabelled SellProduct as 「据点交易」. The
run's log has 16 of 16 tasks 「任务完成」 and no 「任务失败」, and it ends after
「任务完成: 📅日常奖励领取」 with no closing task (no 关闭游戏 / 结束进程 line). AUTO-MAS
still recorded 「部分任务执行失败: SellProduct」 (its English fallback when it finds no
task file for the name, AUTO-MAS#573) and ran two retry rounds.

Every input here is a real machine record, read as it is:
  - the 09-06 05:40 record from the T9 corpus
    (gamesim/corpus/maaend/v3-0906-automas-misjudged/, U13b), whole and as a real prefix;
  - the 09-18 05:26 record (fixtures/maaend-2026-09-18/), a real 「任务失败」.
An earlier version of this test used a hand-typed 09-06 log with an invented
「⛔ 结束进程」 line the machine log does not have (grep -c 结束进程 = 0), so it passed
while the real run was booked failed (e539a57f).
"""
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay.core import collector
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _tmp import tmpdir

HERE = pathlib.Path(__file__).resolve().parent
REAL_0906 = (HERE / "gamesim" / "corpus" / "maaend" / "v3-0906-automas-misjudged" / "automas" / "history"
             / "2026-09-06" / "endfield" / "MaaEnd-05-40-21")
REAL_0918 = HERE / "fixtures" / "maaend-2026-09-18" / "MaaEnd-05-26-03"

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


log_0906 = REAL_0906.with_suffix(".log").read_text(encoding="utf-8")
lines_0906 = log_0906.splitlines(keepends=True)
# What the test leans on, from the real file.
assert "结束进程" not in log_0906 and "关闭游戏" not in log_0906, "the real 09-06 log has no closing task"
assert log_0906.count("任务开始: ") == 16 and log_0906.count("任务完成: ") == 16 and "任务失败" not in log_0906
CUT = next(i for i, ln in enumerate(lines_0906) if "任务开始: 🛒据点交易" in ln) + 1
assert "任务完成: 🛒据点交易" not in "".join(lines_0906[:CUT])

root = tmpdir()
d = root / "2026-09-06" / "endfield"
d.mkdir(parents=True)
shutil.copy2(REAL_0906.with_suffix(".json"), d / "MaaEnd-05-40-21.json")
shutil.copy2(REAL_0906.with_suffix(".log"), d / "MaaEnd-05-40-21.log")

print("[09-06 05:40, the real record: 16/16 complete, no closing task, AUTO-MAS lists SellProduct]")
rec = collector.parse_record(d / "MaaEnd-05-40-21.json", root)
check("booked done", (rec.ok, rec.failed_tasks) if rec else None, (True, []))
check("records the name AUTO-MAS could not look up", rec and rec.raw.get("maaend_name_mismatch"), ["SellProduct"])

print("\n[the same real log cut where 据点交易 started: stuck mid-task]")
(d / "MaaEnd-06-14-25.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: SellProduct"},
                                                   ensure_ascii=False), encoding="utf-8")
(d / "MaaEnd-06-14-25.log").write_text("".join(lines_0906[:CUT]), encoding="utf-8")
rec3 = collector.parse_record(d / "MaaEnd-06-14-25.json", root)
check("a task started and never ended is not cleared", rec3.ok if rec3 else None, False)

print("\n[the same real log, AUTO-MAS lists a display name that never started]")
(d / "MaaEnd-06-20-00.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: ⚔️协议空间"},
                                                   ensure_ascii=False), encoding="utf-8")
shutil.copy2(REAL_0906.with_suffix(".log"), d / "MaaEnd-06-20-00.log")
rec5 = collector.parse_record(d / "MaaEnd-06-20-00.json", root)
check("a listed task that never started keeps the failure (no closing task to show the round ended)",
      (rec5.ok, rec5.failed_tasks) if rec5 else None, (False, ["协议空间"]))

print("\n[09-18 05:26, a real 「任务失败: 🎱基质刷取」]")
d18 = root / "2026-09-18" / "endfield"
d18.mkdir(parents=True)
shutil.copy2(REAL_0918.with_suffix(".json"), d18 / "MaaEnd-05-26-03.json")
shutil.copy2(REAL_0918.with_suffix(".log"), d18 / "MaaEnd-05-26-03.log")
rec2 = collector.parse_record(d18 / "MaaEnd-05-26-03.json", root)
check("a real failure stays a failure", (rec2.ok, rec2.failed_tasks) if rec2 else None, (False, ["基质刷取"]))

# AUTO-MAS's own emulator-launch miss (2026-09-14 10:51:56, verbatim): a one-line
# log, superseded one second later. Neither a failure nor a success.
print("\n[AUTO-MAS's 模拟器启动失败 stub]")
(d / "MaaEnd-06-51-56.json").write_text(json.dumps({"maaend_result": "[自动采集] 模拟器启动失败"}, ensure_ascii=False),
                                        encoding="utf-8")
(d / "MaaEnd-06-51-56.log").write_text("模拟器启动失败, 无日志记录\n", encoding="utf-8")
rec4 = collector.parse_record(d / "MaaEnd-06-51-56.json", root)
check("transitional, no failure", (rec4.transitional, rec4.failed_tasks) if rec4 else None, (True, []))

print("\n[re-judging the ledger only moves towards done]")
old_entry = {"run_id": "2026-09-06/endfield/MaaEnd-05-40-21", "script": "MaaEnd", "ok": False,
             "failed_tasks": ["SellProduct"], "raw": {}}
fresh = collector.refresh_raw(old_entry, root)
check("the 09-06 entry booked failed is re-judged done", (fresh.get("ok"), fresh.get("failed_tasks")), (True, []))
old_bad = {"run_id": "2026-09-18/endfield/MaaEnd-05-26-03", "script": "MaaEnd", "ok": False,
           "failed_tasks": ["基质刷取"], "raw": {}}
check("a real failure is not re-judged done", bool(collector.refresh_raw(old_bad, root).get("ok")), False)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
