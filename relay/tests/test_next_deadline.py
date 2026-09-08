"""When the loop is allowed to sleep until - the one number that decides
whether the relay wakes up at all.

`Engine.next_deadline` replaced polling: instead of waking every few minutes to
ask the clock, the loop sleeps until the exact moment a purely time-based
decision can change. That makes it the single point where two opposite failures
live, and no test had ever called it.

* Return a moment that is already past and the loop busy-spins.
* Return None, or a moment too late, and the relay sleeps through the daily
  report - and because shutdown waits for the report, the machine stays on all
  night. That exact outcome happened on 2026-09-04 through a different route.

The queue times here are read from a fake AUTO-MAS config on disk, the same way
the real one reads them, so "moving a queue in AUTO-MAS moves the deadline with
it" is covered too.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)


def write_queues(times_by_name):
    """A QueueConfig.json shaped the way AUTO-MAS writes it."""
    doc = {"instances": []}
    for i, (name, times) in enumerate(times_by_name.items()):
        uid = f"q{i}"
        doc["instances"].append({"uid": uid})
        doc[uid] = {
            "Info": {"Name": name, "TimeEnabled": True},
            "SubConfigsInfo": {
                "TimeSet": {str(n): {"Info": {"Enabled": True, "Time": t}}
                            for n, t in enumerate(times)},
                "QueueItem": {"0": {"Info": {"ScriptId": "s0"}}},
            },
        }
    (AUTOMAS / "config" / "QueueConfig.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")


write_queues({"早班": ["09:00"], "晚班": ["21:30"]})
(AUTOMAS / "config" / "ScriptConfig.json").write_text(
    json.dumps({"instances": []}), encoding="utf-8")

os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), ARK_CHECK_TIMES="09:00,21:30",
                  SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                  WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
(TMP / "history").mkdir(exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import engine as eng                        # noqa: E402
from ark_relay.config import SERVER_TZ, Config             # noqa: E402
from ark_relay.core import State                           # noqa: E402
from ark_relay.missed import MISSED_GRACE_MIN              # noqa: E402
from ark_relay.shutdown import CHECK_OPEN_MIN              # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


class Notes:
    def send(self, title, body="", **kw):
        return False


class Src:
    def fetch(self, seen):
        return []


def build(state_dir=None):
    cfg = Config()
    cfg.state_dir = state_dir or tmpdir()
    e = eng.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    return e


def at(hh, mm, day=8):
    return datetime(2026, 9, day, hh, mm, tzinfo=SERVER_TZ)


print("[早上 08:00：最近的一件事是 09:00 那个检查点（09:02）]")
e = build()
when, why = e.next_deadline(at(8, 0))
check("时刻", when, at(9, 0) + timedelta(minutes=CHECK_OPEN_MIN))
check("理由说的是检查点", "检查点" in why, True)

print("\n[09:10：检查点过了，下一件是「早班漏没漏跑」（09:25）]")
when, why = e.next_deadline(at(9, 10))
check("时刻", when, at(9, 0) + timedelta(minutes=MISSED_GRACE_MIN))
check("理由点名了队列", "早班" in why, True)

print("\n[已经告警过的队列不再排队，否则同一件事反复叫醒]")
e._missed_alerted.add("2026-09-08/早班/09:00")
when, why = e.next_deadline(at(9, 10))
check("跳到晚班那一档", when.hour >= 21, True)

print("\n[日报没发时，21:30 的截止时刻必须在候选里]")
e2 = build()
when, why = e2.next_deadline(at(21, 0))
check("21:30 截止", (when, why), (at(21, 30), "日报截止"))

print("\n[日报发过了就不再为它醒——不然每轮都算一遍已经做完的事]")
e2.state.mark_report_sent("2026-09-08")
when, why = e2.next_deadline(at(21, 0))
check("换成别的理由", why != "日报截止", True)
check("仍然有下一个时刻", when is not None, True)

print("\n[永远不给一个已经过去的时刻：给了循环就空转]")
e3 = build()
bad = []
for hh in range(24):
    for mm in (0, 1, 29, 30, 31, 59):
        now = at(hh, mm)
        got = e3.next_deadline(now)
        if got is None:
            bad.append(f"{hh:02d}:{mm:02d} 没有下一个时刻")
        elif got[0] <= now:
            bad.append(f"{hh:02d}:{mm:02d} 给了过去的 {got[0]}")
check("一天 144 个时刻全部合法", bad[:3], [])

print("\n[今天的都过完了就滚到明天，不许返回 None]")
when, why = e3.next_deadline(at(23, 59))
check("落在明天", when.date(), at(0, 0, day=9).date())

print("\n[已经下过关机令就别再醒了——机器马上就没了]")
e4 = build()
e4._shutdown_issued = True
check("返回 None", e4.next_deadline(at(9, 0)), None)

print("\n[队列时间改了，醒来的时刻跟着改（读的是 AUTO-MAS 自己那份）]")
write_queues({"早班": ["07:15"], "晚班": ["21:30"]})
e5 = build()
when, why = e5.next_deadline(at(6, 0))
check("跟着挪到 07:15 那一档", when, at(7, 15) + timedelta(minutes=MISSED_GRACE_MIN))
check("理由点名新队列时刻", "07:15" in why, True)
write_queues({"早班": ["09:00"], "晚班": ["21:30"]})

print("\n[队列时间写坏了不许把整个循环带走]")
doc = json.loads((AUTOMAS / "config" / "QueueConfig.json").read_text(encoding="utf-8"))
doc["q0"]["SubConfigsInfo"]["TimeSet"]["0"]["Info"]["Time"] = "坏掉的时刻"
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(doc, ensure_ascii=False),
                                                     encoding="utf-8")
e6 = build()
raised = ""
try:
    got = e6.next_deadline(at(6, 0))
except Exception as exc:  # noqa: BLE001
    raised = f"{type(exc).__name__}: {exc}"
check("不抛异常", raised, "")
check("坏的那档被跳过，好的还在", got is not None, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
