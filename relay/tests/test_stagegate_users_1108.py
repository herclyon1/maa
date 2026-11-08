"""Several MAA users: one user's stage MAA cannot reach is said, users AUTO-MAS does not run
are not looked at, and a pull never takes MAA from a user whose stage is reachable
(audit 11-08 B-D23; dispatch relay-opt-round4-1108 R4-06; stagegate.run_verdict / _gate_due).

Before: run_verdict answered "no" only when every user was "no", so with a second account on
a reachable stage the first account's unreachable one went unsaid (its MAA run then stops at
「Cannot set stage」), and a user AUTO-MAS skips (Info.Status off, RemainedDay 0 -
app/task/manager_base.py is_user_selected) counted like the others.

Not changed, on purpose: several stages for one user, the first unreachable and another
reachable, stays "unknown" - AUTO-MAS sends the Routine fight with UseOptionalStage True
(app/task/MAA/AutoProxy.py ~1883, the v6.19.0 copy under gamesim/upstream) and MAA's GUI
picks the first stage open today, which the relay does not replicate.
"""
import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
import _stagegate_fx as fx

os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.schedule import stagegate as sg

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


SAT9 = datetime(2026, 10, 10, 9, 0, tzinfo=SERVER_TZ)
MORNING = fx.maa_dir(tmpdir())          # YW-4 has no navigation task here; 1-7 has


def two_users(second_stage="1-7", first_info=None):
    """The fixture's MAA user 「arknights」 on YW-4, plus 「小号」 on `second_stage`."""
    d = fx.automas_dir(tmpdir())
    p = d / "config" / "ScriptConfig.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    users = data["S-MAA"]["SubConfigsInfo"]["UserData"]
    users["U1"]["Info"].update(first_info or {})
    users["instances"].append({"uid": "U3"})
    users["U3"] = {"Info": {"Name": "小号", "Stage": second_stage, "Stage_1": "-", "Stage_2": "-", "Stage_3": "-",
                            "StageMode": "Fixed", "MedicineNumb": 0}, "Task": {"IfFight": True}}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return d


print("[两个用户，一个走不到：说走不到，点名是哪个用户]")
every = []
v, stage, why = sg.run_verdict(two_users(), MORNING, SAT9, [], every)
check("结论是走不到", (v, stage), (sg.NO, "YW-4"))
check("原因点名用户", why.startswith("用户「arknights」："), True)
check("每个用户的结论都给出来", [x[0] for x in every], [sg.NO, sg.YES])
check("两个都走不到：照旧走不到", sg.run_verdict(two_users("YW-4"), MORNING, SAT9)[0], sg.NO)
check("两个都走得到：走得到", sg.run_verdict(two_users("1-7", {"Stage": "1-7"}), MORNING, SAT9)[0], sg.YES)

print("\n[AUTO-MAS 不跑的用户不看（Status 关、RemainedDay 0）]")
check("走不到的那个 Status 关着：走得到", sg.run_verdict(two_users(first_info={"Status": False}), MORNING, SAT9)[0],
      sg.YES)
check("走不到的那个 RemainedDay 0：走得到", sg.run_verdict(two_users(first_info={"RemainedDay": 0}), MORNING, SAT9)[0],
      sg.YES)
check("RemainedDay 还有天数：照看", sg.run_verdict(two_users(first_info={"RemainedDay": 3}), MORNING, SAT9)[0], sg.NO)
one = fx.automas_dir(tmpdir())
p1 = one / "config" / "ScriptConfig.json"
d1 = json.loads(p1.read_text(encoding="utf-8"))
d1["S-MAA"]["SubConfigsInfo"]["UserData"]["U1"]["Info"]["Status"] = False
p1.write_text(json.dumps(d1, ensure_ascii=False), encoding="utf-8")
check("只有一个用户、它不跑：没有用户可看，不拦", sg.run_verdict(one, MORNING, SAT9), (sg.YES, "", "MAA 没有用户"))

print("\n[一个用户、首关走不到、备选走得到：照旧不拦（MAA 按开放日挑，中继不复刻）]")
check("首关 YW-4、备选 1-7：不知道", sg.run_verdict(fx.automas_dir(tmpdir(), stage_1="1-7"), MORNING, SAT9)[0],
      sg.UNKNOWN)


class Note:
    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body, alert))
        return []


print("\n[打开「拿掉 MAA」时：只有一个用户走不到，只报不拿（拿掉会连走得到的那个一起拿）]")
pulled = []
saved = sg.PULL_FROM_QUEUE
sg.PULL_FROM_QUEUE = True
try:
    cfg = types.SimpleNamespace(state_dir=tmpdir(), automas_dir=two_users(), maa_dir=MORNING)
    n = Note()
    sg.step(cfg, n, datetime(2026, 10, 10, 8, 52, tzinfo=SERVER_TZ), busy=lambda: False,
            skipper=lambda q, s: pulled.append((q, s)) or {"queue": q, "script": s}, restorer=lambda rec: True)
    check("没拿掉 MAA", pulled, [])
    check("报了一次「走不到、MAA 照跑」", [t for t, _b, _a in n.sent], [texts.stage_gate_warn("早班")])
    check("……里面点名用户", "arknights" in n.sent[0][1], True)
finally:
    sg.PULL_FROM_QUEUE = saved

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
