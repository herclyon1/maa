"""The phone's changes, its snapshot and the plan look at one and the same AUTO-MAS user
(audit 11-08 D-11; dispatch relay-opt-round6-1108 R6-01; masuser.pick).

Before: commands._find_user (every phone change through the backend) took the first user,
snapshot._mas / maa_from_files (what the phone shows) and plan._scripts (the plan text)
went through every user and kept the last. With two users the phone showed one account and
changed the other. Pinned here, with two MAA users:

* both run: the first, everywhere;
* the first one AUTO-MAS does not run (Info.Status off, or RemainedDay 0 -
  manager_base.is_user_selected): the second, everywhere;
* neither runs: the first, everywhere;
* the backend's reply or the file's UserData holding an "instances" list: skipped.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay.core import masuser, plan
from ark_relay.features.phone import commands, snapshot

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


def user(stage, **info):
    return {"Info": {"Name": stage, "Stage": stage, "Stage_1": "-", "Stage_2": "-", "Stage_3": "-",
                     "StageMode": "Fixed", "MedicineNumb": 0, **info}, "Task": {"IfFight": True}}


def world(first_info=None, second_info=None):
    users = {"instances": [{"uid": "U1"}, {"uid": "U2"}],
             "U1": user("1-7", **(first_info or {})), "U2": user("CE-6", **(second_info or {}))}
    d = tmpdir()
    (d / "config").mkdir()
    (d / "config" / "ScriptConfig.json").write_text(json.dumps(
        {"instances": [{"uid": "S"}], "S": {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"},
                                            "SubConfigsInfo": {"UserData": users}}}, ensure_ascii=False),
        encoding="utf-8")
    return d, users


def answers(d, users):
    """(phone change goes to, phone shows from the backend, phone shows from the file, plan shows)."""
    def mas(path, body=None, timeout=15):
        if path == "/api/scripts/get":
            return {"data": {"S": {"Info": {"Name": "MAA"}}}}
        if path == "/api/scripts/user/get":
            return {"data": users}
        raise AssertionError(path)
    saved = (commands._mas, snapshot._post)
    commands._mas = mas
    snapshot._post = lambda path, body=None, timeout=15: mas(path, body)
    try:
        uid = commands._find_user("MAA")[1]
        out = {}
        snapshot._mas(out)
        shown = (out.get("MAA") or {}).get("关卡")
    finally:
        commands._mas, snapshot._post = saved
    files = snapshot.maa_from_files(d)["关卡"]
    planned = next(iter(plan._scripts(d / "config").values())).get("stage_info", {}).get("Stage")
    return users[uid]["Info"]["Stage"], shown, files, planned


print("[两个账号都会跑：都看第一个]")
check("改的、显示的（后台）、显示的（文件）、安排里的", answers(*world()), ("1-7",) * 4)

print("\n[第一个停用（Status 关）：都看第二个]")
check("同一个账号", answers(*world(first_info={"Status": False})), ("CE-6",) * 4)

print("\n[第一个剩余天数 0：都看第二个]")
check("同一个账号", answers(*world(first_info={"RemainedDay": 0})), ("CE-6",) * 4)

print("\n[两个都不跑：退回第一个]")
check("同一个账号", answers(*world(first_info={"Status": False}, second_info={"Status": False})), ("1-7",) * 4)

print("\n[pick 本身]")
check("没有用户", masuser.pick({}), None)
check("只有 instances 列表", masuser.pick({"instances": [{"uid": "U1"}]}), None)
check("后台的回答里先列 instances 也跳过", masuser.pick({"instances": [], "U9": {"Info": {}}})[0], "U9")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
