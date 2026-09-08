"""AUTO-MAS 说「OK-WW 在完成任务前退出」，但 OK-WW 自己写了 Daily Task Completed → 这趟是做完的。

2026-09-06 早班：09:36:18 Completed，09:36:24 进程退出，AUTO-MAS 只看见进程没了，
记成失败；重试那趟无事可做记成 ✅、五行全是「—」。日报因此 ❌ + 空 ✅，用户问是不是代码改坏了。
以证据（OK-WW 自己的日志）为准。
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay import collector
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _tmp import tmpdir

fails = []
root = tmpdir()
d = root / "2026-09-06" / "wuwa"; d.mkdir(parents=True)
(d / "OK-WW-05-20-17.json").write_text(json.dumps({"general_result": "OK-WW 在完成任务前退出"}, ensure_ascii=False), encoding="utf-8")
(d / "OK-WW-05-20-17.log").write_text(
    "2026-09-06 09:20:48,000 INFO TacetTask: start\n"
    "2026-09-06 09:36:18,776 INFO TaskExecutor DailyTask:Daily Task Completed\n"
    "2026-09-06 09:36:24,007 INFO MainThread handler:handler stopping global\n", encoding="utf-8")
rec = collector.parse_record(d / "OK-WW-05-20-17.json", root)
if rec is None or not rec.ok:
    fails.append(f"日志里有 Completed 却仍判失败：{rec and rec.failed_tasks}")
if rec is not None and not rec.raw.get("okww_exit_race"):
    fails.append("没有标记这是 AUTO-MAS 的时序误判")

# 真没做完的（日志里没有 Completed）照样是失败
(d / "OK-WW-05-50-00.json").write_text(json.dumps({"general_result": "OK-WW 在完成任务前退出"}, ensure_ascii=False), encoding="utf-8")
(d / "OK-WW-05-50-00.log").write_text("2026-09-06 09:50:00,000 INFO TacetTask: start\n", encoding="utf-8")
rec2 = collector.parse_record(d / "OK-WW-05-50-00.json", root)
if rec2 is None or rec2.ok:
    fails.append("没有 Completed 的退出应仍判失败")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
