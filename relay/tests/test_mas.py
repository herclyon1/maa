"""AUTO-MAS from the relay side: its address, the mas-api tool, its field labels and the user the phone looks at; its YAML config, the settings contract, the beta3 user.

One part per former file, each run on its own (tests/_parts.py): test_mas.py, test_masconfig_yaml.py, test_mascontract.py, test_masuser_beta3.py.
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


def _part_masconfig_yaml():
    """AUTO-MAS v5.8's YAML settings read like v5.7's JSON (core/masconfig.py, core/miniyaml.py).

Ledger #113 (2026-10-23 08:48 Beijing): AUTO-MAS updated itself to v5.8.0-beta.1, moved
config/QueueConfig.json, ScriptConfig.json and PlanConfig.json into config/legacy-json and kept
the settings in queues.yaml, scripts.yaml and plans.yaml, with every time as UTC ISO. The relay
then found 「设置里一个脚本、队列都没有」 and 「读取 QueueConfig.json 失败: [Errno 2]」.
The YAML here is written in the shape of that machine's own files (indentless sequences, long
JSON strings folded in single quotes, quoted UTC times); the files themselves are not in this
public repo. Against the real files, miniyaml matched PyYAML on all four and plan.schedule,
plan._scripts, plan.next_plan and mascontract.check gave the same answers as from the JSON.

    Formerly test_masconfig_yaml.py.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import masconfig, miniyaml, plan


    print("[miniyaml: the constructs AUTO-MAS's files use]")
    doc = miniyaml.loads("""\
order:
- uid: aaa
  type: QueueConfig
- uid: bbb
  type: QueueConfig
data:
  aaa:
    Info:
      Name: 早班
      TimeEnabled: true
      Delay: 0
      Ratio: 1.5
      ScriptAfterTask: null
      Note: ~
    Pipeline: '{"Data": {"Week": "2026-W42",
      "Notes": "it''s", "Tag": "[{\\"text\\": \\"日常\\"}]"},
      "Run": 2}'
    Quoted: "a\\tb \\u4e2d
      c"
    Long: a plain line
      that folds
    Empty: {}
    None: []
    '2026-10-22': date key
""")
    check("an indentless sequence under its key", [x["uid"] for x in doc["order"]], ["aaa", "bbb"])
    info = doc["data"]["aaa"]["Info"]
    check("true / int / float / null / ~", (info["TimeEnabled"], info["Delay"], info["Ratio"],
                                            info["ScriptAfterTask"], info["Note"]), (True, 0, 1.5, None, None))
    check("a single-quoted string folded over three lines, '' kept as one quote",
          json.loads(doc["data"]["aaa"]["Pipeline"]), {"Data": {"Week": "2026-W42", "Notes": "it's",
                                                                "Tag": '[{"text": "日常"}]'}, "Run": 2})
    check("a double-quoted string: escapes and folding", doc["data"]["aaa"]["Quoted"], "a\tb 中 c")
    check("a plain scalar folded over lines", doc["data"]["aaa"]["Long"], "a plain line that folds")
    check("{} and []", (doc["data"]["aaa"]["Empty"], doc["data"]["aaa"]["None"]), ({}, []))
    check("a quoted key stays a string", doc["data"]["aaa"]["2026-10-22"], "date key")
    for bad in ("a: [1, 2]\n", "a: |\n  text\n", "a: &x 1\n", "a: !!str 1\n"):
        try:
            miniyaml.loads(bad)
            check(f"refuses {bad.strip()!r}", "parsed", "ValueError")
        except ValueError:
            check(f"refuses {bad.strip()!r}", True)

    print("\n[masconfig: v5.8's layout read in v5.7's shape]")
    QUEUES = """\
order:
- uid: q1
  type: QueueConfig
data:
  q1:
    Data:
      LastTimedStart: '2026-10-22T01:00:00Z'
    Info:
      Name: 早班
      TimeEnabled: true
      StartUpMode: Never
      AfterAccomplish: NoAction
    TimeSet:
      order:
      - uid: t1
        type: TimeSet
      data:
        t1:
          Info:
            Days:
            - Monday
            - Tuesday
            - Wednesday
            - Thursday
            - Friday
            - Saturday
            - Sunday
            Enabled: true
            Time: '2000-01-01T01:00:00Z'
    QueueItem:
      order:
      - uid: i1
        type: QueueItem
      data:
        i1:
          Info:
            ScriptId: s1
          Schedule:
            Days:
            - Monday
            - Tuesday
            - Wednesday
            - Thursday
            - Friday
            - Saturday
            - Sunday
            Enabled: true
            Mode: fixed_time
            Time: '1999-12-31T16:00:00Z'
"""
    old = masconfig.legacy(miniyaml.loads(QUEUES))
    check("order -> instances", old["instances"], [{"uid": "q1", "type": "QueueConfig"}])
    check("sub-collections go under SubConfigsInfo", sorted(old["q1"]["SubConfigsInfo"]), ["QueueItem", "TimeSet"])
    ts = old["q1"]["SubConfigsInfo"]["TimeSet"]["t1"]["Info"]
    check("09:00 Beijing written as 2000-01-01T01:00:00Z reads back as 09:00 (v5.7's form)", ts["Time"], "09:00")
    check("LastTimedStart in v5.7's form", old["q1"]["Data"]["LastTimedStart"], "2026-10-22 09:00")
    check("a queue item's time too",
          old["q1"]["SubConfigsInfo"]["QueueItem"]["i1"]["Schedule"]["Time"], "00:00")

    print("\n[the reader finds the YAML only when the JSON is gone]")
    root = tmpdir()
    cfg = root / "config"
    cfg.mkdir()
    (cfg / "queues.yaml").write_text(QUEUES, encoding="utf-8")
    check("no JSON: the YAML", masconfig.source(cfg / "QueueConfig.json").name, "queues.yaml")
    sched = plan.schedule(root)
    check("plan.schedule sees the 09:00 morning queue (10-23 it saw none)",
          [(q["name"], q["times"], q["items"]) for q in sched], [("早班", ["09:00"], ["s1"])])
    (cfg / "QueueConfig.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    check("JSON there (AUTO-MAS before v5.8): the JSON", masconfig.source(cfg / "QueueConfig.json").name,
          "QueueConfig.json")
    try:
        masconfig.read(cfg / "ScriptConfig.json")
        check("neither file: the error reading the JSON gives", "read", "FileNotFoundError")
    except FileNotFoundError:
        check("neither file: the error reading the JSON gives", True)

    print("\n[offline file-edit fallback on v5.8 YAML (11-08 [D-05])]")
    import os
    from ark_relay.features.phone import commands
    from ark_relay.features.schedule import queues

    yroot = tmpdir()
    ycfg = yroot / "config"
    ycfg.mkdir()
    (ycfg / "queues.yaml").write_text(QUEUES, encoding="utf-8")
    SCRIPTS_YAML = """\
order:
- uid: s1
  type: ScriptConfig
- uid: s2
  type: ScriptConfig
data:
  s1:
    Info:
      Name: MAA
    UserData:
      order:
      - uid: u1
        type: MAAUserConfig
      data:
        u1:
          Info:
            Name: 默认用户
            Stage: CE-6
            MedicineNumb: 0
  s2:
    Info:
      Name: MaaEnd
    Game:
      WaitTime: 60
"""
    (ycfg / "scripts.yaml").write_text(SCRIPTS_YAML, encoding="utf-8")
    os.environ["ARK_AUTOMAS_DIR"] = str(yroot)
    orig_backend = commands._backend_scripts
    orig_refusal = commands._stage_refusal
    orig_q_backend = queues._enabled_via_backend
    commands._backend_scripts = lambda: (None, "")
    commands._stage_refusal = lambda s: ""
    queues._enabled_via_backend = lambda name, enabled: None
    try:
        ok_s, msg_s = commands._set_stage("1-7")
        check("YAML _set_stage ok", ok_s, True)
        check("YAML _set_stage read back", masconfig.read(ycfg / "ScriptConfig.json")["s1"]["SubConfigsInfo"]["UserData"]["u1"]["Info"]["Stage"], "1-7")
        ok_m, msg_m = commands._set_medicine(5)
        check("YAML _set_medicine ok", ok_m, True)
        check("YAML _set_medicine read back", masconfig.read(ycfg / "ScriptConfig.json")["s1"]["SubConfigsInfo"]["UserData"]["u1"]["Info"]["MedicineNumb"], 5)
        ok_w, msg_w = commands._set_wait_time(120)
        check("YAML _set_wait_time ok", ok_w, True)
        check("YAML _set_wait_time read back", masconfig.read(ycfg / "ScriptConfig.json")["s2"]["Game"]["WaitTime"], 120)
        ok_q, msg_q = queues.apply(yroot, "早班", enabled=False)
        check("YAML queues.apply ok", ok_q, True)
        check("YAML queues.apply read back", masconfig.read(ycfg / "QueueConfig.json")["q1"]["Info"]["TimeEnabled"], False)
        check("no stray JSON written next to YAML", (ycfg / "QueueConfig.json").exists() or (ycfg / "ScriptConfig.json").exists(), False)
    finally:
        commands._backend_scripts = orig_backend
        commands._stage_refusal = orig_refusal
        queues._enabled_via_backend = orig_q_backend


def _part_mascontract():
    """The relay notices at once when an AUTO-MAS update moves a setting it reads.

10-14: AUTO-MAS v5.7.0-beta.3, installed by the relay's own pre-update at 08:46 Beijing, moved
the MAA user's stage items from Info to a new Stage group. The relay read Info, got nothing,
treated it as "no stage set" (stage gate placeholder at 08:55:27), and nothing reached the
group for 13 hours: the boot self-check had run at 08:45, on the old version.

* ark_relay/core/mascontract.py lists every AUTO-MAS setting the relay reads, and check()
  finds each one in the config files (through masuser for the moved keys);
* the boot self-check has it as one item, and a miss reaches the group with the self-check;
* right after the pre-update installs a new AUTO-MAS (and only then) the check runs again and
  a miss goes to the group under its own title.
Each part fails on the code before it (no list, no item, no hook).

    Formerly test_mascontract.py.
    """
    import inspect
    import json
    import os
    import types

    import _stagegate_fx as fx

    os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features.phone import commands
    from ark_relay.features.preupdate import preupdate_automas as P
    from ark_relay.features.selfcheck import selfcheck
    try:
        from ark_relay.core import mascontract
    except ImportError:          # the code before this change
        mascontract = None


    def edit_user(root: Path, fn) -> Path:
        """Apply fn to the MAA user of the fixture's ScriptConfig.json."""
        f = root / "config" / "ScriptConfig.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        fn(data["S-MAA"]["SubConfigsInfo"]["UserData"]["U1"])
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return root


    def drop_stage(user):
        """A later AUTO-MAS that keeps the main stage neither in Stage nor in Info."""
        user["Stage"].pop("Stage")
        user["Info"].pop("Stage", None)


    print("[the list of AUTO-MAS settings the relay reads]")
    check("ark_relay/core/mascontract.py exists", mascontract is not None)
    if mascontract is not None:
        items = mascontract.CONTRACT
        check("it lists the moved stage items at their new group",
              {("Stage", k) for k in ("Stage", "StageMode", "MedicineNumb")} <= {(i.group, i.key) for i in items})
        check("each item names its reader and a feature with plain words",
              [i.path for i in items if not i.source or i.use not in texts.MAS_SETTING_WHAT
               or i.use not in texts.MAS_SETTING_BREAKS], [])
        check("every script kind, the queue and the plan table are covered",
              {i.kind for i in items}, {"MAA", "MaaEnd", "OK-WW", "queue", "plan"})

    print("\n[the check on AUTO-MAS v5.7.0-beta.3's layout]")
    if mascontract is not None:
        beta3 = fx.automas_dir(tmpdir(), beta3=True)
        res = mascontract.check(beta3)
        check("beta.3 layout: nothing missing", [i.path for i in res.missing], [])
        check("beta.3 layout: the items were judged, not skipped", res.judged >= 30)
        check("beta.3 layout: no file unreadable", res.unreadable, [])

        def to_info(user):
            """The same user as an AUTO-MAS before beta.3 keeps it: the moved items in Info."""
            for k, g in mascontract.masuser.MOVED.items():
                if k in (user.get(g) or {}):
                    user["Info"][k] = user[g].pop(k)
        old = edit_user(fx.automas_dir(tmpdir(), beta3=True), to_info)
        check("the same items kept in Info (before beta.3) also pass", [i.path for i in mascontract.check(old).missing], [])

        gone = edit_user(fx.automas_dir(tmpdir(), beta3=True), drop_stage)
        res = mascontract.check(gone)
        check("a stage kept in neither Stage nor Info fails and names it",
              [(i.kind, i.path) for i in res.missing], [("MAA", "Stage.Stage")])
        lines = texts.mas_contract_lines(res.missing)
        check("the plain line says which setting and which column",
              lines, ["中继读不到方舟的关卡设置（关卡一栏里找不到），开跑前查关卡、明日安排、手机上显示和修改关卡都不对了"])
        check("that line is plain words", [p for x in lines for p in texts.plain(x)], [])

    print("\n[settings new in AUTO-MAS v5.7.0-beta.4: MaaEnd's launcher start (10-16)]")
    # 10-16: beta.4 (PR #1394) brought Game.LaunchMode / Game.LauncherPath, and its pre-run check
    # found no launcher from the relay's .cmd in Game.Path; the 早班 MaaEnd never ran. The relay
    # now reads and writes all three (efstart_setup). The two new ones are judged only on beta.4
    # or later: the recorded days of the day simulator run v5.6.2 to beta.3.
    if mascontract is not None:
        launch = {(i.kind, i.path) for i in mascontract.CONTRACT if i.use == "maaend_launch"}
        check("MaaEnd Game.Path, Game.LaunchMode, Game.LauncherPath, Game.ControllerType are listed",
              launch, {("MaaEnd", "Game.Path"), ("MaaEnd", "Game.LaunchMode"), ("MaaEnd", "Game.LauncherPath"),
                       ("MaaEnd", "Game.ControllerType")})
        check("version order: beta.4 after beta.3, the release after its betas",
              (mascontract.version_key("v5.7.0-beta.3") < mascontract.version_key("v5.7.0-beta.4")
               < mascontract.version_key("v5.7.0") < mascontract.version_key("v5.7.1-beta.1"),
               mascontract.version_key("nonsense")), (True, None))
        b3 = fx.automas_dir(tmpdir(), beta3=True)
        new_keys = [("MaaEnd", "Game.LaunchMode"), ("MaaEnd", "Game.LauncherPath")]
        check("beta.4 installed, the two new keys absent: both named",
              [(i.kind, i.path) for i in mascontract.check(b3, "v5.7.0-beta.4").missing], new_keys)
        check("beta.3 installed: they are not judged", mascontract.check(b3, "v5.7.0-beta.3").missing, [])
        check("version unknown: not judged either", mascontract.check(b3, "").missing, [])

        def add_launch(root):
            f = root / "config" / "ScriptConfig.json"
            data = json.loads(f.read_text(encoding="utf-8"))
            data["S-END"]["Game"].update(LaunchMode="Launcher", LauncherPath="")
            f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return root
        check("beta.4 with them in place: nothing missing",
              mascontract.check(add_launch(fx.automas_dir(tmpdir(), beta3=True)), "v5.7.0-beta.4").missing, [])

        def drop_path(root):
            f = root / "config" / "ScriptConfig.json"
            data = json.loads(f.read_text(encoding="utf-8"))
            data["S-END"]["Game"].pop("Path")
            f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return root
        check("Game.Path is judged on every version",
              [(i.kind, i.path) for i in mascontract.check(drop_path(fx.automas_dir(tmpdir(), beta3=True))).missing],
              [("MaaEnd", "Game.Path")])

    print("\n[「MaaEnd 启动」's window settings, written by the relay since 10-17]")
    # efstart_setup sets Game.SetResolution / CloseOnFinish / RestoreDisplayType / RestoreResolution
    # and reads Game.ControllerType (maaend_launch.check). An AUTO-MAS that drops one must be
    # reported: listed, judged on every version (MaaEndConfig has them since v5.7.0-beta.2 at
    # least), and a missing one named in one plain line.
    if mascontract is not None:
        WINDOW_KEYS = ("SetResolution", "CloseOnFinish", "RestoreDisplayType", "RestoreResolution")
        window = [(i.kind, i.path, i.since) for i in mascontract.CONTRACT if i.use == "maaend_window"]
        check("the four window settings are listed, judged on every version",
              window, [("MaaEnd", f"Game.{k}", "") for k in WINDOW_KEYS])

        def drop_window(root):
            f = root / "config" / "ScriptConfig.json"
            data = json.loads(f.read_text(encoding="utf-8"))
            for k in (*WINDOW_KEYS, "ControllerType"):
                data["S-END"]["Game"].pop(k)
            f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return root
        gone = mascontract.check(drop_window(fx.automas_dir(tmpdir(), beta3=True)))
        check("an AUTO-MAS that drops them: all five named",
              sorted((i.kind, i.path) for i in gone.missing),
              sorted([("MaaEnd", f"Game.{k}") for k in (*WINDOW_KEYS, "ControllerType")]))
        lines = texts.mas_contract_lines(gone.missing)
        check("plain lines for them, one per feature", (len(lines), [p for x in lines for p in texts.plain(x)]), (2, []))
        check("the fixture as on the machine: nothing missing",
              mascontract.check(fx.automas_dir(tmpdir(), beta3=True)).missing, [])

    print("\n[the boot self-check has it as one item, routed like the others]")
    SELF_GOOD = dict(procs=lambda: [(1, r"D:\ark\automas\repo\main.py")], mas_up=lambda: True,
                     schedule=lambda: [{"name": "早班", "times": ["09:00"]}], channels=lambda: ["群"],
                     run_ok=lambda cmd: (True, ""), has_module=lambda m: True)


    class _Notifier:
        channels = ["企业微信机器人"]

        def __init__(self):
            self.sent = []

        def send(self, title, body, *, alert=False, daily=False):
            self.sent.append((title, body, alert))
            return []


    def self_items(root):
        cfg = types.SimpleNamespace(automas_dir=str(root), state_dir=Path(root) / "state", history_dir=str(root),
                                    phone_topic="ark-x", phone_pin="1234")
        # The update settings are read from the backend; it is not asked in this test.
        orig = selfcheck._handed_updates_gaps
        orig_mas = commands._mas
        commands._mas = lambda *a, **k: {"data": {}}
        selfcheck._handed_updates_gaps = lambda scripts: []
        try:
            return selfcheck.run(cfg, **SELF_GOOD)
        finally:
            selfcheck._handed_updates_gaps, commands._mas = orig, orig_mas


    name = getattr(texts, "MAS_CONTRACT_CHECK", "中继要读的调度程序设置都在原处")
    os.environ["ARK_LOG_FILE"] = str(tmpdir() / "log" / "relay.log")
    good = [c for c in self_items(fx.automas_dir(tmpdir(), beta3=True)) if c.name == name]
    check("the self-check has the item", len(good), 1)
    check("it holds on the beta.3 layout", [c.ok for c in good], [True])
    bad = [c for c in self_items(edit_user(fx.automas_dir(tmpdir(), beta3=True), drop_stage)) if c.name == name]
    check("it fails when the stage cannot be found", [c.ok for c in bad], [False])
    check("its detail names the setting", bool(bad) and "方舟的关卡设置" in bad[0].detail)
    empty = [c for c in self_items(tmpdir()) if c.name == name]
    check("no settings folder: not judged (the queue line says it), not a second failure",
          [c.ok for c in empty], [None])

    print("\n[right after the pre-update installed a new AUTO-MAS, and only then]")
    has_hook = "after_update" in inspect.signature(P.run_automas).parameters
    check("run_automas takes an after_update hook", has_hook)


    def update_run(*, need: bool, confirmed: bool) -> list:
        """run_automas against a fake backend; the versions after_update was called with."""
        seen: list = []
        orig = (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version)

        def post(path, body=None):
            if path == "/api/update/check":
                return {"if_need_update": need, "latest_version": "v5.7.0-beta.3"}
            return {}
        P._mas_post, P._automas_version, P._live_version = post, (lambda _r: "v5.7.0-beta.2"), (lambda: "v5.7.0-beta.2")
        P._wait_for_package = lambda _root, _deadline, *_a: Path("UpdatePack_v5.7.0-beta.3.zip")
        P._wait_for_version = (lambda want, _d, *_a: want) if confirmed else (lambda want, _d, *_a: "v5.7.0-beta.2")
        try:
            kw = {"after_update": seen.append} if has_hook else {}
            P.run_automas(Path("."), budget_s=1, problems=[], **kw)
        finally:
            (P._mas_post, P._automas_version, P._live_version, P._wait_for_package, P._wait_for_version) = orig
        return seen


    check("a new version came up: the check runs once, with it", update_run(need=True, confirmed=True), ["v5.7.0-beta.3"])
    check("no update: no check", update_run(need=False, confirmed=False), [])
    check("install not confirmed (version unchanged): no check", update_run(need=True, confirmed=False), [])
    boot = (Path(__file__).resolve().parents[1] / "boot_stages.py").read_text(encoding="utf-8")
    check("the boot's pre-update passes the hook", "after_update=" in boot and "report_contract" in boot)

    print("\n[the post-update check pushes a miss to the group, under its own title]")
    report = getattr(selfcheck, "report_contract", None)
    check("selfcheck.report_contract exists", report is not None)
    if report is not None:
        n = _Notifier()
        cfg = types.SimpleNamespace(automas_dir=str(edit_user(fx.automas_dir(tmpdir(), beta3=True), drop_stage)))
        c = report(cfg, n, "v5.7.0-beta.3")
        check("a miss: one alarm", [(t, a) for t, _, a in n.sent], [(texts.AUTOMAS_CONTRACT, True)])
        body = n.sent[0][1] if n.sent else ""
        check("it says the version and what stops working",
              "v5.7.0-beta.3" in body and "方舟的关卡设置" in body and "开跑前查关卡" in body)
        check("the alarm is plain words", texts.plain(texts.AUTOMAS_CONTRACT + body), [])
        check("returns the failed check", c.ok, False)
        n = _Notifier()
        report(types.SimpleNamespace(automas_dir=str(fx.automas_dir(tmpdir(), beta3=True))), n, "v5.7.0-beta.3")
        check("nothing missing: nothing pushed", n.sent, [])
        n = _Notifier()
        report(types.SimpleNamespace(automas_dir=str(fx.automas_dir(tmpdir(), beta3=True))), n, "v5.7.0-beta.4")
        check("just updated to beta.4 and its launcher settings are not there: the alarm names them",
              bool(n.sent) and "终末地的游戏位置和开游戏方式" in n.sent[0][1])
        check("that alarm is plain words", texts.plain(n.sent[0][1] if n.sent else ""), [])

        class _Log:
            def __init__(self):
                self.warned = []

            def warning(self, msg, *args, **kw):
                self.warned.append(msg % args)

            def info(self, msg, *args, **kw):
                pass
        lg = _Log()
        c = report(types.SimpleNamespace(automas_dir=str(tmpdir())), _Notifier(), "v5.7.0-beta.3", lg)
        check("files unreadable after an update: not judged, and said as a WARNING (errwatch pushes it)",
              (c.ok, len(lg.warned)), (None, 1))

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_masuser_beta3():
    """The relay reads and writes the MAA user's settings where AUTO-MAS keeps them.

AUTO-MAS v5.7.0-beta.3 (its own updater, game machine 10-14 08:46 Beijing) moved the stage
items into a Stage group and Annihilation into Task, and stopped keeping them in Info. From
then on the relay saw nothing: the stage gate logged its "current stage" placeholder at
08:55:27 instead of YW-4, and the snapshot, the plan, the annihilation switch and the phone's
stage / sanity-potion writes all used Info.* (ark_relay/core/masuser.py has the details).
Each check below fails on the code before the fix and holds for both layouts.

    Formerly test_masuser_beta3.py.
    """
    import json
    import os
    from datetime import datetime

    import _stagegate_fx as fx

    os.environ.update(SERVERCHAN_KEY="", ARK_LLM_KEY="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import masuser, plan
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.schedule import stagegate as sg
    from ark_relay.features.phone import snapshot, commands


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


if __name__ == "__main__":
    sys.exit(run_parts([_part_mas_address, _part_mas_api_silent, _part_mas_labels, _part_mas_user_pick, _part_masconfig_yaml, _part_mascontract, _part_masuser_beta3]))
