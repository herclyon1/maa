"""The three writers that touch production config, and the one reader that
decides whether a broken task may be switched back on.

This is the 826 class of code: it edits the files the scripts actually run
from. The accident that day was a value written into production whose meaning
had been inferred rather than confirmed - it changed which stage was farmed and
burnt sanity potions. Nothing here had a test.

* `mastercfg.write_maa` may only ever accept the seven values MAA itself
  declares, must write **both** copies (the master and MAA's own, which the
  master overwrites at launch), and must read back what it wrote before
  reporting success. 「写完就说设好了」 is forbidden.
* `gameupdate.maaend_set_enabled` switches whole tasks on and off. Reporting a
  change that did not happen means the morning queue silently runs the wrong
  set of tasks.
* `gameupdate.spmed_fix_present` decides whether the sanity-booster task may be
  re-enabled. It deliberately looks at the shape of the fix, not at a version
  number: on 2026-09-03 the upstream fix was still unmerged, so re-enabling by
  version alone just buys another wasted failure.
* `MaaEndConfig.describe` is what the report says a setting currently is. A
  wrong answer here is worse than no answer - it is a status line that lies.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import gameupdate, mastercfg
from ark_relay.maaend import MaaEndConfig
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


def maa_tree(drones="Money"):
    """An AUTO-MAS data dir holding MAA's master config, plus a MAA dir."""
    root = tmpdir()
    master = root / "AUTO-MAS" / "data" / "abc123" / "Default" / "ConfigFile"
    master.mkdir(parents=True)
    doc = {"Current": "Default", "Configurations": {"Default": {"TaskQueue": [
        {"Type": "StartUp"},
        {"Type": "Infrast", "UsesOfDrones": drones},
    ]}}}
    (master / "gui.new.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    maa = root / "MAA" / "config"
    maa.mkdir(parents=True)
    (maa / "gui.new.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return root / "AUTO-MAS", root / "MAA"


def drones_in(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return mastercfg._maa_infrast(doc)["UsesOfDrones"]


print("[无人机用途：改一次，两份都写到了]")
automas, maa = maa_tree("Money")
ok, msg = mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "PureGold")
check("成功", ok, True)
check("母本写了", drones_in(automas / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json"),
      "PureGold")
check("MAA 目录那份也写了", drones_in(maa / "config" / "gui.new.json"), "PureGold")
check("报告写清前后", ("龙门币" in msg and "赤金" in msg), True)
check("报告说了写了几份", "2 份" in msg, True)

print("\n[本来就是这个值：照样算成功，但不许假装改过]")
ok, msg = mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "PureGold")
check("成功", ok, True)
check("说的是「本来就用在」", "本来就用在" in msg, True)

print("\n[不认识的取值必须当场拒绝——826 就是编了一个含义写进去]")
ok, msg = mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "黄金")
check("拒绝", ok, False)
check("盘上没被改", drones_in(maa / "config" / "gui.new.json"), "PureGold")
check("报告列出合法取值", "_NotUse" in msg, True)

print("\n[没开放的路径一律拒绝，不许顺手写别的字段]")
ok, msg = mastercfg.write_maa(automas, maa, "Infrast/Drones", "Money")
check("拒绝", ok, False)
check("说清只开放哪一项", "Infrast/UsesOfDrones" in msg, True)

print("\n[母本里没有基建任务：拒绝，而不是凭空造一个]")
automas2, maa2 = maa_tree()
f = automas2 / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json"
f.write_text(json.dumps({"Current": "Default",
                         "Configurations": {"Default": {"TaskQueue": [{"Type": "StartUp"}]}}}),
             encoding="utf-8")
ok, msg = mastercfg.write_maa(automas2, maa2, "Infrast/UsesOfDrones", "Money")
check("拒绝", ok, False)
check("说清找不到什么", "UsesOfDrones" in msg, True)

print("\n[找不到母本时不许说成功]")
ok, msg = mastercfg.write_maa(tmpdir(), None, "Infrast/UsesOfDrones", "Money")
check("拒绝", ok, False)
check("说清是找不到母本", "找不到" in msg, True)

# ------------------------------------------------- MaaEnd：开关任务

class Cfg:
    def __init__(self, automas_dir):
        self.automas_dir = automas_dir


def maaend_master(tasks):
    root = tmpdir()
    d = root / "data" / "xyz" / "Default" / "ConfigFile"
    d.mkdir(parents=True)
    doc = {"instances": [{"tasks": tasks}]}
    (d / "mxu-MaaEnd.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return root, d / "mxu-MaaEnd.json"


print("\n[MaaEnd 开关任务：只报真的改了的那些]")
root, path = maaend_master([{"taskName": "自动吃药", "enabled": True},
                            {"taskName": "基质筛选", "enabled": False}])
changed = gameupdate.maaend_set_enabled(Cfg(root), {"自动吃药", "基质筛选"}, False)
check("只有原来是开的那个算改了", changed, ["自动吃药"])
after = json.loads(path.read_text(encoding="utf-8"))["instances"][0]["tasks"]
check("盘上两个都是关的", [t["enabled"] for t in after], [False, False])

print("\n[没有一个需要改时，一个字节都不许写]")
before = path.read_bytes()
check("返回空", gameupdate.maaend_set_enabled(Cfg(root), {"自动吃药"}, False), [])
check("文件没动", path.read_bytes(), before)

print("\n[点名的任务不存在：不许连累别的任务]")
check("返回空", gameupdate.maaend_set_enabled(Cfg(root), {"不存在的任务"}, True), [])
check("文件还是没动", path.read_bytes(), before)

print("\n[找不到 AUTO-MAS 目录时安静返回空，别抛]")
check("空目录", gameupdate.maaend_set_enabled(Cfg(tmpdir()), {"自动吃药"}, True), [])
check("automas_dir 是 None", gameupdate.maaend_set_enabled(Cfg(None), {"自动吃药"}, True), [])

# ------------------------------------------------- MaaEnd：理智药补丁在不在

def nodes(node):
    d = tmpdir()
    (d / "resource" / "pipeline").mkdir(parents=True)
    (d / "resource" / "pipeline" / "nodes.json").write_text(
        json.dumps({"AutoUseSpMedicationQuickUse": node} if node is not None else {},
                   ensure_ascii=False), encoding="utf-8")
    return d


print("\n[理智药那个确认节点：修好了才认，光换版本号不算]")
fixed = {"recognition": {"param": {"all_of": [{"recognition": "OCR", "expected": "确认"}]}}}
check("修好了", gameupdate.spmed_fix_present(nodes(fixed)), True)
broken = {"recognition": {"param": {"all_of": [{"expected": "确认"}]}}}
check("形状不对就是没修", gameupdate.spmed_fix_present(nodes(broken)), False)
check("all_of 是空的也是没修", gameupdate.spmed_fix_present(
    nodes({"recognition": {"param": {"all_of": []}}})), False)
check("节点整个不在", gameupdate.spmed_fix_present(nodes(None)), False)
check("节点不是字典", gameupdate.spmed_fix_present(nodes("会开的")), False)
check("文件不存在", gameupdate.spmed_fix_present(tmpdir()), False)
check("目录是 None", gameupdate.spmed_fix_present(None), False)

# ------------------------------------------------- MaaEnd：读回当前设置

def maaend_root(task):
    d = tmpdir()
    (d / "config").mkdir(parents=True)
    (d / "config" / "mxu-MaaEnd.json").write_text(
        json.dumps({"instances": [{"tasks": [task]}]}, ensure_ascii=False), encoding="utf-8")
    return MaaEndConfig(d)


print("\n[读回当前设置：四种取值各说各的话，读不到就说不出来，不许瞎编]")
c = maaend_root({"taskName": "协议空间", "optionValues": {
    "选择": {"type": "select", "caseName": "武器培养"},
    "闪避": {"type": "switch", "value": True},
    "关掉的": {"type": "switch", "value": False},
    "周期": {"type": "checkbox", "caseNames": ["周一", "周四"]},
    "上限": {"type": "input", "values": {"次数": 3}},
}})
check("select 报名字", c.describe("协议空间", "选择"), "武器培养")
check("switch 开", c.describe("协议空间", "闪避"), "on")
check("switch 关", c.describe("协议空间", "关掉的"), "off")
check("checkbox 逗号连起来", c.describe("协议空间", "周期"), "周一,周四")
check("input 出原值", json.loads(c.describe("协议空间", "上限")), {"次数": 3})
check("没有这个选项时给空串", c.describe("协议空间", "不存在"), "")
check("没有这个任务时给空串", c.describe("不存在的任务", "选择"), "")
check("配置文件不在时给空串，不抛", MaaEndConfig(tmpdir()).describe("协议空间", "选择"), "")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
