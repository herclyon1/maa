"""The three writers that touch production config, and the reader of the
sanity-booster step.

This is the 826 class of code: it edits the files the scripts actually run
from. The accident that day was a value written into production whose meaning
had been inferred rather than confirmed - it changed which stage was farmed and
burnt sanity potions. Nothing here had a test.

* `mastercfg.write_maa` may only ever accept the seven values MAA itself
  declares, must write **both** copies (the master and MAA's own, which the
  master overwrites at launch), and must read back what it wrote before
  reporting success. 「写完就说设好了」 is forbidden.
* `gameupdate.maaend_enable` switches whole tasks back on - and only on (the
  user, 2026-10-06: 「我开的任务是谁说要关的」). Reporting a change that did not
  happen means the morning queue silently runs the wrong set of tasks.
* `gameupdate.spmed_shape` reads the sanity-booster's confirm node. It no longer
  decides whether the task may run (it always runs); a shape other than the
  fixed one rings the group at boot. It looks at the shape, not at a version
  number: on 2026-09-03 the upstream fix was still unmerged.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import gameupdate, mastercfg
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
        {"Type": "Award", "Award": True, "Mail": False, "FreeGacha": False, "Orundum": False,
         "Mining": False, "SpecialAccess": False},
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

print("\n[领取奖励的开关：邮件那项 09-14 发现一直是关的]")
automas3, maa3 = maa_tree("Money")
check("读出来是关", mastercfg.read_maa(automas3)["values"].get("Award/Mail"), False)
ok, msg = mastercfg.write_maa(automas3, maa3, "Award/Mail", True)
check("成功", ok, True)
check("报告写清前后", "关 → 开" in msg and "邮件" in msg, True)
for f in (automas3 / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json", maa3 / "config" / "gui.new.json"):
    check(f"{f.parent.parent.name} 那份写了", mastercfg._maa_award(json.loads(f.read_text(encoding="utf-8")))["Mail"], True)
check("读回是开", mastercfg.read_maa(automas3)["values"].get("Award/Mail"), True)
ok, msg = mastercfg.write_maa(automas3, maa3, "Award/Mail", True)
check("本来就是开的", ok and "本来就是" in msg, True)
ok, msg = mastercfg.write_maa(automas3, maa3, "Award/Mail", "yes")
check("非布尔值拒绝", ok, False)
ok, msg = mastercfg.write_maa(automas3, maa3, "Award/FreeGacha", True)
check("免费单抽没开放，拒绝", ok, False)
check("其他开关也在", set(k for k in mastercfg.read_maa(automas3)["values"] if k.startswith("Award/")),
      {"Award/Mail", "Award/Orundum", "Award/Mining", "Award/SpecialAccess"})

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


print("\n[MaaEnd 开回任务：只报真的改了的那些，没有关的路]")
root, path = maaend_master([{"taskName": "自动吃药", "enabled": False},
                            {"taskName": "基质筛选", "enabled": True}])
changed = gameupdate.maaend_enable(Cfg(root), {"自动吃药", "基质筛选"})
check("只有原来是关的那个算改了", changed, (["自动吃药"], [], ""))
after = json.loads(path.read_text(encoding="utf-8"))["instances"][0]["tasks"]
check("盘上两个都是开的", [t["enabled"] for t in after], [True, True])
try:
    gameupdate.maaend_enable(Cfg(root), {"自动吃药"}, False)
    can_off = True
except TypeError:
    can_off = False
check("没有「关」这个参数", can_off, False)
check("以前那个能开能关的函数没了", hasattr(gameupdate, "maaend_set_enabled"), False)

print("\n[没有一个需要改时，一个字节都不许写]")
before = path.read_bytes()
check("返回空", gameupdate.maaend_enable(Cfg(root), {"自动吃药"}), ([], [], ""))
check("文件没动", path.read_bytes(), before)

print("\n[点名的任务不存在：不许连累别的任务，单列出来]")
check("单列", gameupdate.maaend_enable(Cfg(root), {"不存在的任务"}), ([], ["不存在的任务"], ""))
check("文件还是没动", path.read_bytes(), before)

print("\n[找不到母本时说出来，和「本来就开着」分得开——否则调用方会把记录删掉]")
check("空目录", gameupdate.maaend_enable(Cfg(tmpdir()), {"自动吃药"}), ([], [], "找不到终末地的母本"))
check("automas_dir 是 None", gameupdate.maaend_enable(Cfg(None), {"自动吃药"}), ([], [], "找不到终末地的母本"))

# ------------------------------------------------- MaaEnd：理智药那个确认节点长什么样

def nodes(node):
    d = tmpdir()
    (d / "resource" / "pipeline").mkdir(parents=True)
    (d / "resource" / "pipeline" / "nodes.json").write_text(
        json.dumps({"AutoUseSpMedicationQuickUse": node} if node is not None else {},
                   ensure_ascii=False), encoding="utf-8")
    return d


print("\n[理智药那个确认节点：修好了才认，光换版本号不算；认不出的每次开机报群，任务照开]")
fixed = {"recognition": {"param": {"all_of": [{"recognition": "OCR", "expected": "确认"}]}}}
check("修好了", gameupdate.spmed_shape(nodes(fixed)), "fixed")
broken = {"recognition": {"param": {"all_of": [{"expected": "确认"}]}}}
check("形状不对就是没修", gameupdate.spmed_shape(nodes(broken)), "broken")
check("all_of 是空的：认不出", gameupdate.spmed_shape(
    nodes({"recognition": {"param": {"all_of": []}}})), "unknown")
check("节点整个不在：改名或拿掉了", gameupdate.spmed_shape(nodes(None)), "missing")
check("节点不是字典：认不出", gameupdate.spmed_shape(nodes("会开的")), "unknown")
check("文件不存在：读不到", gameupdate.spmed_shape(tmpdir()), "unreadable")
check("目录是 None：没东西可查", gameupdate.spmed_shape(None), "")

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
