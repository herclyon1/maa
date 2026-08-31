"""周本要和剿灭一个作息：周一 04:00 自动挂回来，领满就摘掉、之后不再检测。

用户 2026-08-31：「我要的是能做到像明日方舟的剿灭那样的，每周一自动刷新
状态，然后优先打周本三次，完事才是普通体力副本。打完副本计入已完成，
并且之后不再检测，周一刷新。」

这里只测「挂上/摘掉/周一挂回来」这条状态机；
「周本排在体力副本之前」由 DailyTask 的顺序补丁保证，
见 test_okww_patch.py 与 docs/OKWW-WEEKLY-BOSS.md。
"""
import json, os, sys, tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import weeklyboss as W
from ark_relay.config import SERVER_TZ

TMP = Path(tempfile.mkdtemp())
LOG = TMP / "ok.log"; os.environ["ARK_OKWW_LOG"] = str(LOG)
STATE = TMP / "state"; STATE.mkdir()
# 假 AUTO-MAS：母本目录靠 DailyTask.json 认出来
CFG = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"
CFG.mkdir(parents=True)
(CFG / "DailyTask.json").write_text(json.dumps(
    {W.KEY: ["Auto Farm all Nightmare Nest"]}), encoding="utf-8")
(CFG / "FarmEchoTask.json").write_text(json.dumps({}), encoding="utf-8")

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

def tasks():
    return json.loads((CFG / "DailyTask.json").read_text(encoding="utf-8"))[W.KEY]

def at(mon_day, hh, mm=0):
    return datetime(2026, 8, mon_day, hh, mm, tzinfo=SERVER_TZ)

def left(n):
    LOG.write_text(f"周本本周剩余次数原文: [本周剩余可收取次数：{n}/3]\n", encoding="utf-8")

g = W.WeeklyBossGate(STATE, TMP / "automas")
g.configure(enabled=True, index=1, count=3, level="90")

print("\n[开着就挂上，配置一起写对]")
g.enforce(at(31, 10))
check("附加任务里有周本", W.TASK_NAME in tasks(), True)
farm = json.loads((CFG / "FarmEchoTask.json").read_text(encoding="utf-8"))
check("传送目标", farm.get("Teleport to Boss"), W.WEEKLY)
check("难度是最高级", farm.get("Boss Level"), W.MAX_LEVEL)
check("次数", farm.get("Repeat Farm Count"), 3)

print("\n[没领满就一直挂着——这正是剿灭没有、而周本必须有的]")
left(2)
g.on_success(at(31, 11))
g.enforce(at(31, 11))
check("还剩 2 次，开关不许摘", W.TASK_NAME in tasks(), True)

print("\n[领满才摘掉，之后不再检测]")
left(0)
g.on_success(at(31, 12))
check("记成本周已打", g.settings()["本周已打"], True)
g.enforce(at(31, 12))
check("附加任务里已摘掉", W.TASK_NAME in tasks(), False)
g.enforce(at(31, 20))          # 同一周内反复跑，不许再挂回去
check("同周内再跑也不挂回来", W.TASK_NAME in tasks(), False)

print("\n[周一 04:00 前仍算上一周]")
# 2026-09-07 是周一。03:59 仍属于上一周，不许刷新。
g.enforce(datetime(2026, 9, 7, 3, 59, tzinfo=SERVER_TZ))
check("周一 03:59 还不刷新", W.TASK_NAME in tasks(), False)

print("\n[过了周一 04:00 自动挂回来]")
g.enforce(datetime(2026, 9, 7, 4, 1, tzinfo=SERVER_TZ))
check("下周一自动挂回来", W.TASK_NAME in tasks(), True)
check("状态不再显示「本周已打」",
      g.settings(datetime(2026, 9, 7, 4, 1, tzinfo=SERVER_TZ))["本周已打"], False)

print("\n[关掉总开关就一直摘着]")
g.configure(enabled=False)
g.enforce(datetime(2026, 9, 7, 5, 0, tzinfo=SERVER_TZ))
check("关掉就摘掉", W.TASK_NAME in tasks(), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
