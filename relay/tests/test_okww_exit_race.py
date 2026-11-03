"""AUTO-MAS 说「OK-WW 在完成任务前退出」，但 OK-WW 自己写了 Daily Task Completed → 这趟是做完的。

2026-09-06 早班：09:36:18 Completed，09:36:24 进程退出，AUTO-MAS 只看见进程没了，
记成失败；重试那趟无事可做记成 ✅、五行全是「—」。日报因此 ❌ + 空 ✅，用户问是不是代码改坏了。
以证据（OK-WW 自己的日志）为准。
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ark_relay.core import collector
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

# 2026-11-03 ledger #135: OK-WW v3.7.14-beta.2 logged zh_CN completion then -e closed
# the hwnd; AUTO-MAS saw connected:0 and recorded disconnect. The start-of-round
# 4C farm prompt must not be mistaken for end-of-round completion.
d1103 = root / "2026-11-03" / "5e401e6c"; d1103.mkdir(parents=True)
(d1103 / "0.log").write_text(
    "2026-11-03 09:36:14,193 INFO TaskExecutor DailyTask:每日任务已完成，开始传送并刷取4C声骸\n"
    "2026-11-03 09:37:56,826 INFO TaskExecutor TacetTask:info_set current_stamina 240\n"
    "2026-11-03 09:38:08,164 INFO TaskExecutor TacetTask:当前体力大于等于双倍, 使用双倍体力\n"
    "2026-11-03 09:44:27,058 INFO TaskExecutor TacetTask:体力已用尽\n"
    "2026-11-03 09:44:50,415 INFO TaskExecutor DailyTask:每日任务已完成\n", encoding="utf-8")
rec3 = collector.parse_db_record(
    ("5e401e6c", "2026-11-03T05:35:08", "2026-11-03", "wuwa", "OK-WW",
     "OK-WW 未连接游戏客户端", "{}", "2026-11-03/5e401e6c/0.log"),
    root)
if rec3 is None or not rec3.ok or not rec3.raw.get("okww_exit_race"):
    fails.append(f"2026-11-03 每日任务已完成 + 未连接游戏客户端 应判成功：{rec3}")
refreshed = collector.refresh_raw(
    {"run_id": "2026-11-03/wuwa/OK-WW-05-35-08", "script": "OK-WW", "ok": False,
     "failed_tasks": ["OK-WW 未连接游戏客户端"],
     "raw": {"general_result": "OK-WW 未连接游戏客户端", "automas_record_id": "5e401e6c"}},
    root, None)
if not refreshed.get("ok") or refreshed.get("raw", {}).get("okww_stopped") != "体力不够再开一局":
    fails.append(f"refresh_raw 没按 automas_record_id 恢复成功：{refreshed}")

# A run with only the start-of-round 4C prompt that later raised in the weekly boss stays failed.
d1103_fail = root / "2026-11-03" / "160a2a9f"; d1103_fail.mkdir(parents=True)
(d1103_fail / "0.log").write_text(
    "2026-11-03 09:18:10,000 INFO TaskExecutor DailyTask:每日任务已完成，开始传送并刷取4C声骸\n"
    "2026-11-03 09:25:07,521 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本领奖：这一圈打完没看到结晶，不领就会被上游按 ESC 退本，停下。\n"
    "2026-11-03 09:25:08,100 ERROR TaskExecutor TaskExecutor:📅 每日任务异常停止 Traceback (most recent call last):\n"
    "ark_overrides.ArkStopped: 周本领奖\n", encoding="utf-8")
rec4 = collector.parse_db_record(
    ("160a2a9f", "2026-11-03T05:17:16", "2026-11-03", "wuwa", "OK-WW",
     "OK-WW 未连接游戏客户端", "{}", "2026-11-03/160a2a9f/0.log"),
    root)
if rec4 is None or rec4.ok:
    fails.append(f"只有开头刷 4C 提示、中途报错的不能判成功：{rec4}")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
