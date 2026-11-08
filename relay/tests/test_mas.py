"""AUTO-MAS from the relay side: its address, the mas-api tool, its field labels and the user the phone looks at.

One part per former file, each run on its own (tests/_parts.py): test_mas_address.py, test_mas_api_silent.py, test_mas_labels.py, test_mas_user_pick_1108.py.
"""
# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_mas_address():
    """AUTO-MAS 的地址只有一处出处，而且 ARK_MAS_PORT 真的管得住全部。

2026-09-08 审出来：地址在 relay 里有 4 份（commands / snapshot / engine 各自写死
36163，只有预更新那份读 ARK_MAS_PORT），改端口只有四分之一生效——而「四分之一生效」
比「完全不生效」难查得多。

还有一条：出处**必须是函数**。config.py 顶部那段注释写着，模块级读 os.environ 会在
.env 加载之前求值，做成常量等于让这个变量「设了也不生效」。

    Formerly test_mas_address.py.
    """
    import ast
    import os
    import re

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))


    print("[地址只有一处出处]")
    hard = []
    for p in sorted([p for p in (ROOT / "ark_relay").rglob("*.py") if not {"okww_files", "machinechecks"} & set(p.parts)]):
        if p.name == "config.py":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if re.search(r"127\.0\.0\.1:\s*\{?36163|:36163", line):
                hard.append(f"{p.name}:{i}")
    check("别处不许再写死", hard, [])

    print("[出处是函数，不是模块级常量]")
    cfg = ast.parse((ROOT / "ark_relay" / "core" / "config.py").read_text(encoding="utf-8"))
    names = {n.name for n in cfg.body if isinstance(n, ast.FunctionDef)}
    check("config.mas_base 存在且是函数", "mas_base" in names, True)
    consts = [t.id for n in cfg.body if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name)]
    check("没有模块级的地址常量", [c for c in consts if "MAS" in c.upper()], [])

    print("[ARK_MAS_PORT 真的管用]")
    from ark_relay.core.config import mas_base
    old = os.environ.get("ARK_MAS_PORT")
    try:
        os.environ["ARK_MAS_PORT"] = "39999"
        check("改端口立刻生效", mas_base(), "http://127.0.0.1:39999")
        del os.environ["ARK_MAS_PORT"]
        check("不设时回落到 36163", mas_base(), "http://127.0.0.1:36163")
    finally:
        if old is None:
            os.environ.pop("ARK_MAS_PORT", None)
        else:
            os.environ["ARK_MAS_PORT"] = old


def _part_mas_api_silent():
    """mas-api.py must exit non-zero when AUTO-MAS answered with an HTTP error.

Silent-failure audit rows scripts/mac/mas-api.py:50 and :58: an HTTP 4xx/5xx
came back as {"__status", "__detail"} or {"__status", "__body"}, was printed,
and the tool exited 0.

    Formerly test_mas_api_silent.py.
    """
    import contextlib
    import importlib.util
    import io

    ROOT = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("mas_api", ROOT / "scripts" / "mac" / "mas-api.py")
    mas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mas)


    def run(answer):
        mas.call = lambda path, body=None, method="POST": answer
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = mas.main(["post", "/api/scripts/get"])
        return rc, out.getvalue()


    print("[HTTP error with a JSON body]")
    rc, out = run({"__status": 422, "__detail": {"detail": "field required"}})
    check("the detail is printed", "field required" in out, True)
    check("exit 1", rc, 1)

    print("[HTTP error with a non-JSON body]")
    rc, out = run({"__status": 500, "__body": "Internal Server Error"})
    check("the body is printed", "Internal Server Error" in out, True)
    check("exit 1 (non-JSON body)", rc, 1)

    print("[normal answers stay 0]")
    check("a dict answer exits 0", run({"code": 200, "data": {}})[0], 0)
    check("a list answer exits 0", run([{"a": 1}])[0], 0)


def _part_mas_labels():
    """AUTO-MAS field labels: every labelled ConfigItem is read (audit 11 #4, 2026-10-13).

mas_labels matched `## 中文名` + `self.X = ConfigItem(` lazily up to a `
)`. A
one-line ConfigItem(...) has no such line of its own, so the match swallowed
the next field and its label went to the wrong key or nowhere; the MaaEnd
sanity-task fields are declared as `config.X = ConfigItem` in the module-level
init_maaend_task_config(config), which MaaEndUserConfig calls with itself, and
were not read at all. Of the 19 SHOWN fields 7 had no label.

The fixture is AUTO-MAS app/models/config.py at v5.7.0-beta.2 (ff285a39), the version
the machine runs since 2026-10-11 08:48 (relay.log 「AUTO-MAS 已更新到 v5.7.0-beta.2」),
byte-identical to gamesim/upstream/maa-v6.19.0/automas/app/models/config.py.txt. Audit 11
ran on an older copy that lacked beta.2's Info_IfScriptBeforeTask / ScriptAfterTask,
Update_*, Embedded_FollowSource and Run_LoopGuard; the labels below are the same on both.
Of the 7, Task.TaskIndex (OK-WW) carries only a `#`
comment and Task.IfSanity / Task.IfAutoUseSpMedication are no ConfigItem in
this file (only schema.py Field descriptions): no `##` label exists for them.

    Formerly test_mas_labels.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.phone import mas_labels


    # Kept as .txt so the repo's Python tools (ruff, the comment ratchet) do not read
    # upstream code as ours; laid out as AUTO-MAS's app/models for the run.
    SRC = Path(__file__).resolve().parent / "fixtures" / "automas-models" / "config.py.txt"
    AM = tmpdir()
    (AM / "app" / "models").mkdir(parents=True)
    (AM / "app" / "models" / "config.py").write_bytes(SRC.read_bytes())
    out = mas_labels._mas_labels(AM)


    def label(game, path):
        return (out[game].get(path) or {}).get("label")


    print("[the AUTO-MAS source audit 11 ran on]")
    check("MAA Info.MedicineNumb (one-line ConfigItem before it)", label("MAA", "Info.MedicineNumb"), "理智药数量")
    check("MAA Task.IfFight (one-line ConfigItem)", label("MAA", "Task.IfFight"), "是否理智作战")
    check("MAA Task.IfStartUp keeps its own label (not swallowed)", label("MAA", "Task.IfStartUp"), "是否自动唤醒")
    check("MAA Info.Notes (one line) keeps its own label", label("MAA", "Info.Notes"), "备注")
    check("MaaEnd Task.SanityTaskType (config. in init_maaend_task_config)",
          label("MaaEnd", "Task.SanityTaskType"), "理智任务类型")
    check("MaaEnd Task.AutoEssenceSpecifiedLocation", label("MaaEnd", "Task.AutoEssenceSpecifiedLocation"), "基质刷取地点")
    check("multi-line items still read: MAA Info.Annihilation options",
          (label("MAA", "Info.Annihilation"), (out["MAA"].get("Info.Annihilation") or {}).get("options", [])[:2]),
          ("剿灭模式", ["Close", "Annihilation"]))
    check("OK-WW Task.WhichToFarm", label("OK-WW", "Task.WhichToFarm"), "每日任务体力用途")
    shown = sorted(f"{g}|{p}" for g in out for p in mas_labels.SHOWN if p in out[g])
    check("SHOWN fields labelled: 16 of 19 (TaskIndex, IfSanity, IfAutoUseSpMedication have none)", len(shown), 16)
    # No label may land on a field other than its own: each `##` line is the line
    # right above its ConfigItem in the source.
    src = SRC.read_text(encoding="utf-8")
    wrong = [f"{g}|{p}" for g, items in out.items() for p, info in items.items()
             if f'## {info["label"]}\n' not in src]
    check("every label is a `## ` line of the source", wrong, [])

    print("\n[a wrapped one-line call and a comment with a parenthesis]")
    d = tmpdir()
    (d / "app" / "models").mkdir(parents=True)
    (d / "app" / "models" / "config.py").write_text('''
def init_x(config) -> None:
    ## 甲
    config.Task_A = ConfigItem("Task", "A", 0)  # a (comment
    ## 乙
    config.Task_B = ConfigItem(
        "Task",
        "B",
        "x)",  # a ) in a string and a comment
        OptionsValidator(["p", "q"]),
    )


class MaaEndUserConfig(ConfigBase):
    def __init__(self):
        ## 丙
        self.Info_C = ConfigItem("Info", "C", f(1, 2))
        ## 丁
        self.Info_D = ConfigItem("Info", "D", 1)
        init_x(self)
''', encoding="utf-8")
    got = mas_labels._mas_labels(d)["MaaEnd"]
    check("labels", {k: v["label"] for k, v in got.items()},
          {"Info.C": "丙", "Info.D": "丁", "Task.A": "甲", "Task.B": "乙"})
    check("options inside a wrapped call", got.get("Task.B", {}).get("options"), ["p", "q"])


def _part_mas_user_pick():
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

    Formerly test_mas_user_pick_1108.py.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import masuser, plan
    from ark_relay.features.phone import commands, snapshot


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


if __name__ == "__main__":
    sys.exit(run_parts([_part_mas_address, _part_mas_api_silent, _part_mas_labels, _part_mas_user_pick]))
