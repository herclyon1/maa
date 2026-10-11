"""When the boot-window pre-update is wanted: only before a queue still to come
today that runs OK-WW, the one program it still launches (its update overwrites
the local patches, re-applied right after). MaaEnd's own update is AUTO-MAS's
job since the 2026-10-11 switch-over. The launching itself is Windows-only.
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"; (AUTOMAS / "config").mkdir(parents=True)

def write_schedule(*queues):
    """queues: (name, time, [script kinds])"""
    q, s, insts, sinsts = {}, {}, [], []
    for i, (name, t, kinds) in enumerate(queues):
        quid = f"q{i}"
        insts.append({"uid": quid})
        items = {}
        for j, kind in enumerate(kinds):
            suid = f"s{i}{j}"
            sinsts.append({"uid": suid})
            path = {"MaaEnd": "D:\\ark\\MaaEnd", "OK-WW": "D:\\ark\\okww"}.get(
                kind, "D:\\MAA-v5.1.0-win-x64")
            s[suid] = {"Info": {"Name": kind, "Path": path},
                       "SubConfigsInfo": {"UserData": {}}}
            items[f"i{j}"] = {"Info": {"ScriptId": suid}}
        q[quid] = {"Info": {"Name": name, "TimeEnabled": True},
                   "SubConfigsInfo": {"TimeSet": {"t": {"Info": {"Enabled": True, "Time": t}}},
                                      "QueueItem": items}}
    q["instances"] = insts; s["instances"] = sinsts
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps(q), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps(s), encoding="utf-8")

os.environ.update(ARK_HISTORY_DIR=str(TMP), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate            # noqa: E402
from ark_relay.config import SERVER_TZ   # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

def at(hh, mm):
    return datetime(2026, 8, 22, hh, mm, tzinfo=SERVER_TZ)

print("[when to pre-update]")
write_schedule(("新队列", "09:00", ["MAA", "OK-WW", "MaaEnd"]),
               ("Evening-MAA", "21:30", ["MAA"]))
check("08:47, morning queue still ahead", preupdate.wanted_today(AUTOMAS, at(8, 47)), True)
check("21:22, only MAA left tonight",     preupdate.wanted_today(AUTOMAS, at(21, 22)), False)
check("11:00, morning queue已过",          preupdate.wanted_today(AUTOMAS, at(11, 0)), False)

write_schedule(("Evening-Both", "21:30", ["MAA", "OK-WW"]))
check("evening queue does run OK-WW",     preupdate.wanted_today(AUTOMAS, at(21, 22)), True)

write_schedule(("新队列", "09:00", ["MAA", "MaaEnd"]))
check("no OK-WW anywhere",                preupdate.wanted_today(AUTOMAS, at(8, 47)), False)
check("…but asked for MaaEnd it is there", preupdate.wanted_today(AUTOMAS, at(8, 47), kind="MaaEnd"), True)
check("no AUTO-MAS dir",                  preupdate.wanted_today(None, at(8, 47)), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
