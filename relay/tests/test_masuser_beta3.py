"""The relay reads and writes the MAA user's settings where AUTO-MAS keeps them.

AUTO-MAS v5.7.0-beta.3 (its own updater, game machine 10-14 08:46 Beijing) moved the stage
items into a Stage group and Annihilation into Task, and stopped keeping them in Info. From
then on the relay saw nothing: the stage gate logged its "current stage" placeholder at
08:55:27 instead of YW-4, and the snapshot, the plan, the annihilation switch and the phone's
stage / sanity-potion writes all used Info.* (ark_relay/core/masuser.py has the details).
Each check below fails on the code before the fix and holds for both layouts.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
import _stagegate_fx as fx

os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import masuser, plan
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.schedule import stagegate as sg
from ark_relay.features.phone import snapshot, commands

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


OLD = {"Info": {"Stage": "YW-4", "MedicineNumb": 3, "Annihilation": "Close"}, "Task": {}}
NEW = {"Info": {"Name": "x"}, "Stage": {"Stage": "YW-4", "MedicineNumb": 3},
       "Task": {"Annihilation": "Close"}}

print("[masuser]")
for name, u in (("old (Info)", OLD), ("beta.3 (Stage / Task)", NEW)):
    check(f"{name}: Stage", masuser.get(u, "Stage"), "YW-4")
    check(f"{name}: MedicineNumb", masuser.get(u, "MedicineNumb"), 3)
    check(f"{name}: Annihilation", masuser.get(u, "Annihilation"), "Close")
    check(f"{name}: info_view has the stage", masuser.info_view(u).get("Stage"), "YW-4")
check("old: Info.MedicineNumb stays", masuser.resolve(OLD, "Info.MedicineNumb"), "Info.MedicineNumb")
check("beta.3: Info.MedicineNumb -> Stage.MedicineNumb", masuser.resolve(NEW, "Info.MedicineNumb"), "Stage.MedicineNumb")
check("beta.3: Info.Annihilation -> Task.Annihilation", masuser.resolve(NEW, "Info.Annihilation"), "Task.Annihilation")
check("an item that did not move keeps its path", masuser.resolve(NEW, "Task.IfFight"), "Task.IfFight")

SAT9 = datetime(2026, 10, 10, 9, 0, tzinfo=SERVER_TZ)
MORNING = fx.maa_dir(tmpdir())
print("[stage gate on a beta.3 config]")
check("beta.3: the gate reads Stage.Stage (YW-4 is a definite no on the 10-10 files)",
      sg.run_verdict(fx.automas_dir(tmpdir(), beta3=True), MORNING, SAT9)[:2], (sg.NO, "YW-4"))
check("old layout unchanged", sg.run_verdict(fx.automas_dir(tmpdir()), MORNING, SAT9)[:2], (sg.NO, "YW-4"))

print("[plan and snapshot on a beta.3 config]")
d = fx.automas_dir(tmpdir(), beta3=True)
maa = next(s for s in plan._scripts(d / "config").values() if s.get("kind") == "MAA")
check("plan: stage mode", maa.get("stage_mode"), "Fixed")
check("plan: stage", (maa.get("stage_info") or {}).get("Stage"), "YW-4")
check("plan: annihilation from Task", maa.get("annihilation"), "Annihilation")
snap = snapshot.maa_from_files(d)
check("snapshot: 关卡", snap.get("关卡"), "YW-4")
check("snapshot: 理智药", snap.get("理智药"), 0)
check("snapshot: 剿灭", snap.get("剿灭"), "Annihilation")

print("[phone writes go where the user keeps the item]")
sent = []
real = commands._find_user, commands._mas
try:
    user = json.loads(json.dumps(NEW))
    commands._find_user = lambda script: ("S", "U", user)

    def fake_mas(route, payload):
        if route.endswith("/update"):
            sent.append(payload["data"])
            for g, items in payload["data"].items():
                user.setdefault(g, {}).update(items)
            return {"code": 200}
        return {"data": {"U": user}}
    commands._mas = fake_mas
    failed, before, now = commands._user_item_via_api("MAA", "Info.MedicineNumb", 5)
    check("beta.3: the write goes to Stage.MedicineNumb and reads back 5", (failed, before, now, sent), ("", 3, 5, [{"Stage": {"MedicineNumb": 5}}]))
finally:
    commands._find_user, commands._mas = real

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
