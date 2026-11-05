"""Endfield's failure retry limit in AUTO-MAS kept at 1 (run_limit.py).

2026-11-05 morning one failed Endfield round ran three times under AUTO-MAS's
Run.RunTimesLimit=3, five with the make-up. The limit went to 1 that day, through
AUTO-MAS's API: an AUTO-MAS update or one click in its window puts it back. The backend's
read and write are stand-ins here. Checked:
* at 1: no write, nothing said;
* back at 3: written back to 1, one Server酱 line (not the group), once a day however often;
* refused while the script runs (「正在运行」): no count, the next tick writes it;
* refused for another reason ALARM_AFTER ticks in a row: one group alarm, not repeated;
* backend down or no such script: nothing;
* a replayed day before 2026-11-05 (the decision's day): nothing.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ
from ark_relay.core.notify import route_of
from ark_relay.features.phone import commands
from ark_relay.features.schedule import run_limit as R

fails = []


def check(label, got, want=True):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + label + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


class Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body, alert))
        return []


class Eng:
    def __init__(self):
        self.notifier = Notifier()


state = {"limit": 1, "up": True, "refuse": "", "writes": 0}


def fake_backend():
    if not state["up"]:
        return None, ""
    return {"data": {"sid-end": {"Info": {"Name": "MaaEnd"}, "Run": {"RunTimesLimit": state["limit"]}},
                     "sid-ark": {"Info": {"Name": "MAA"}, "Run": {"RunTimesLimit": 3}}}}, ""


def fake_write(reply, script, path, value):
    state["writes"] += 1
    check("只改终末地的 Run.RunTimesLimit、改成 1", (script, path, value), ("MaaEnd", "Run.RunTimesLimit", 1))
    if state["refuse"]:
        return False, "调度程序没有接受这次修改：" + state["refuse"]
    state["limit"] = value
    return True, "失败重试上限 3 → 1（调度程序已确认）"


commands._backend_scripts = fake_backend
commands._script_item_via_api = fake_write
DAY = datetime(2026, 11, 6, 9, 0, tzinfo=SERVER_TZ)
NEXT_DAY = datetime(2026, 11, 7, 9, 0, tzinfo=SERVER_TZ)

print("[是 1：不写、不通知]")
e = Eng()
R.step(e, DAY)
check("没写", state["writes"], 0)
check("没通知", e.notifier.sent, [])

print("\n[被改回 3：改回 1，Server酱说一句，同一天只说一次]")
state["limit"] = 3
R.step(e, DAY)
check("改回 1", (state["writes"], state["limit"]), (1, 1))
check("说了一句，不进群", [(t, a) for t, _, a in e.notifier.sent], [(texts.RUN_LIMIT_RESET, False)])
check("这句走 Server酱", route_of(texts.RUN_LIMIT_RESET), "info")
check("说清楚是几改回几", "变成了 3" in e.notifier.sent[0][1] and "改回 1" in e.notifier.sent[0][1], True)
state["limit"] = 3
R.step(e, DAY)
check("同一天又被改回：照改", (state["writes"], state["limit"]), (2, 1))
check("同一天不再说第二遍", len(e.notifier.sent), 1)
state["limit"] = 3
R.step(e, NEXT_DAY)
check("第二天又被改回：再说一句", len(e.notifier.sent), 2)

print("\n[调度程序在跑、不收改动：不算失败，下一轮改]")
e = Eng()
state.update(limit=3, refuse="正在运行，无法更新配置项", writes=0)
for _ in range(R.ALARM_AFTER + 1):
    R.step(e, DAY)
check("每一轮都试了", state["writes"], R.ALARM_AFTER + 1)
check("在跑时改不了：不报警", e.notifier.sent, [])
state["refuse"] = ""
R.step(e, DAY)
check("跑完那一轮改回去了", state["limit"], 1)
check("改回来了说一句", [t for t, _, _ in e.notifier.sent], [texts.RUN_LIMIT_RESET])

print("\n[别的原因连着改不回来：进群一次]")
e = Eng()
state.update(limit=3, refuse="写入失败: 连接被拒绝", writes=0)
for _ in range(R.ALARM_AFTER):
    R.step(e, DAY)
check("第 3 次进群报警一次", [(t, a) for t, _, a in e.notifier.sent], [(texts.RUN_LIMIT_STUCK, True)])
check("报警进群", route_of(texts.RUN_LIMIT_STUCK, alert=True), "group")
check("报警里有调度程序的原话", "连接被拒绝" in e.notifier.sent[0][1], True)
R.step(e, DAY)
check("第 4 次不再重复报", len(e.notifier.sent), 1)

print("\n[读不到调度程序、或者回放 11-05 以前的日子：什么都不做]")
e = Eng()
state.update(limit=3, up=False, refuse="", writes=0)
R.step(e, DAY)
check("调度程序没开：没写", state["writes"], 0)
state["up"] = True
R.step(e, datetime(2026, 10, 13, 8, 55, tzinfo=SERVER_TZ))
check("11-05 以前的日子：没写", state["writes"], 0)
check("什么都没说", e.notifier.sent, [])

print("\n[文案]")
for s in (texts.run_limit_reset_body("终末地", 3, 1), texts.run_limit_stuck_body("终末地", 3, 1, "x")):
    check("没有英文变量名", "RunTimesLimit" in s, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
