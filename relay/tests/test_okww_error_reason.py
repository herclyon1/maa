"""OK-WW 失败原因要写真的，「进不了游戏」只给真没进去的那种。

2026-09-07 早班三趟：开头一句「waiting for game to start error … is not connected」
（几秒后就连上了），跑了 41 分钟，倒在周本结算页（FarmEchoTask 抛 WaitFailedException），
没开过无音区的局。日报把三趟都写成「进不了游戏（服务器维护／客户端待更新），今天跳过」。
用户：「这三次报错可不是因为他没进去游戏。这个检查报错原因的机制有问题。」
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

TODAY = """2026-09-07 09:19:33,751 INFO MainThread ok:ok-script init v3.6.7
2026-09-07 09:20:14,057 ERROR ok.core.start_controller start_controller:Game window is not connected BitBlt_True_1920x1080
2026-09-07 09:20:14,057 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮   is not connected, please select the game window.
2026-09-07 09:20:29,575 INFO ok.core.start_controller start_controller:check_device_error: capturing frame (1920, 1080)
2026-09-07 09:20:35,000 INFO TaskExecutor DailyTask:info_set current task wait main esc=True
2026-09-07 09:24:01,913 ERROR TaskExecutor CombatCheck:target_enemy failed, try recheck break out of combat
2026-09-07 10:00:32,309 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认
2026-09-07 10:00:43,326 INFO TaskExecutor TaskExecutor:wait_until timeout <function FindFeature.wait_click_feature.<locals>.<lambda> at 0x0000021FA99996C0> 10 seconds
2026-09-07 10:00:43,366 ERROR TaskExecutor FarmEchoTask:farm 4c error, try handle monthly card Traceback (most recent call last):
  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\src\\task\\FarmEchoTask.py", line 103, in run
    return self.do_run()
  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\ok\\task\\TaskExecutor.py", line 445, in wait_condition
    raise WaitFailedException()
ok.task.exceptions.WaitFailedException
2026-09-07 10:00:44,876 ERROR TaskExecutor DailyTask:run_task_by_class <class 'src.task.FarmEchoTask.FarmEchoTask'> Traceback (most recent call last):
  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\ok\\task\\task.py", line 1116, in run_task_by_class
    task.run()
ok.task.exceptions.WaitFailedException
2026-09-07 10:00:44,885 INFO TaskExecutor DailyTask:info_set 错误
2026-09-07 10:00:44,891 ERROR TaskExecutor TaskExecutor:📅 Daily Task exception stopped Traceback (most recent call last):
  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\ok\\task\\TaskExecutor.py", line 571, in execute
    task.run()
ok.task.exceptions.WaitFailedException
2026-09-07 10:00:44,900 INFO TaskExecutor FeatureSet:read_from_json D:\\ark\\okww\\data\\apps\\ok-ww\\working\\assets
"""
STUCK = """2026-09-02 09:18:58,791 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮 is not connected
2026-09-02 09:19:10,000 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮 is not connected
"""
import tempfile
d = Path(tempfile.mkdtemp())
(d / "today.log").write_text(TODAY, encoding="utf-8")
(d / "stuck.log").write_text(STUCK, encoding="utf-8")

print("[今天的形状：开头窗口连不上、后来跑了 41 分钟、倒在周本]")
t = collector.parse_okww_log(d / "today.log")
check("不是「进不了游戏」", t.get("okww_unreachable"), None)
check("真实原因是人话", t.get("okww_error"), "周本：打完 Boss 领完奖之后没能退出副本")
import re as _re
check("通知字段里除 Boss 外不许有英文", bool(_re.search(r"[A-Za-z]", (t.get("okww_error") or "").replace("Boss", ""))), False)

print("[2026-09-02 的形状：只会等窗口，什么都没干]")
s = collector.parse_okww_log(d / "stuck.log")
check("这才是进不了游戏", s.get("okww_unreachable"), True)
check("没有 traceback 就没有原因", s.get("okww_error"), None)

print("[记录里失败清单换成真实原因]")
import json
h = d / "2026-09-07" / "wuwa"; h.mkdir(parents=True)
(h / "OK-WW-05-19-17.json").write_text(json.dumps({"general_result": "OK-WW 流程产生错误，请检查游戏状态"}), encoding="utf-8")
(h / "OK-WW-05-19-17.log").write_text(TODAY, encoding="utf-8")
rec = collector.parse_record(h / "OK-WW-05-19-17.json", d)
check("判失败", rec.ok, False)
check("失败于写真实原因", rec.failed_tasks, ["周本：打完 Boss 领完奖之后没能退出副本"])
check("不标 unreachable", rec.raw.get("okww_unreachable"), None)

print("[没见过的原文、认识的异常：按异常写具体的，带等了多久]")
UNKNOWN = TODAY.replace("FarmEchoTask:farm 4c error, try handle monthly card", "TacetTask:some brand new english message")
(d / "unknown.log").write_text(UNKNOWN, encoding="utf-8")
u = collector.parse_okww_log(d / "unknown.log")
check("按异常写", u.get("okww_error"), "无音区：等一个画面没等到（等了 10 秒）")
check("不漏英文", bool(_re.search(r"[A-Za-z]", u.get("okww_error") or "")), False)

print("[原文和异常都不认识：不许说「出错」这种模糊话，要明说不认识、要补翻译]")
UNK2 = UNKNOWN.replace("ok.task.exceptions.WaitFailedException", "ok.task.exceptions.SomethingNewException")
(d / "unk2.log").write_text(UNK2, encoding="utf-8")
u2 = collector.parse_okww_log(d / "unk2.log")
check("明说不认识", u2.get("okww_error"), "无音区：报了中继还不认识的错，原文已记进日志，要补翻译")
check("不出现「出错」「这一步」这类模糊词", any(k in (u2.get("okww_error") or "") for k in ("这一步", "出错", "异常", "错误")), False)
check("不漏英文", bool(_re.search(r"[A-Za-z]", u2.get("okww_error") or "")), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
