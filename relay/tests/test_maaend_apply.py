"""maaend.apply_changes：改 MaaEnd 配置的那个写入器。

**为什么补这一个**（2026-09-08 审出来）：这个函数会往游戏机上真正生效的配置里写东西，
写错就是刷错关卡、烧理智药——826 事故就是这么来的——而它**一行测试都没有**。
同一天还把它从 127 行拆成了四步，没有测试的话，「拆完行为没变」这句话谁都担保不了。

四种选项类型（select / switch / checkbox / input）各测一遍能改成，
再逐条测那些**必须拒绝**的情形：拼错的选项名、类型对不上的指令、不在合法取值里的值。
拒绝这件事比改成更重要：写进一条 MaaEnd 根本不看的设置，人会以为改生效了。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import maaend
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


def fixture():
    """一份最小但形状真实的 MaaEnd 安装：配置 + 任务定义。"""
    root = tmpdir()
    (root / "config").mkdir(parents=True)
    (root / "tasks").mkdir(parents=True)
    (root / "config" / "mxu-MaaEnd.json").write_text(json.dumps({
        "instances": [{"tasks": [{
            "id": "abc", "taskName": "ProtocolSpace", "enabled": True,
            "enabledByController": {"ctrl1": True},
            "optionValues": {
                "ProtocolSpaceTab": {"type": "select", "caseName": "OperatorProgression"},
                "AutoFightDodge": {"type": "switch", "value": True},
                "Schedule": {"type": "checkbox", "caseNames": ["一", "二", "三"]},
                "Limits": {"type": "input", "values": {"max": 3}},
                "Weird": {"type": "radio", "caseName": "x"},
            }}]}]
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # MaaEnd 自己的定义文件，合法取值只认这里写的
    (root / "tasks" / "ProtocolSpace.json").write_text("""{
      // 带注释和尾逗号，MaaEnd 的定义文件就长这样
      "option": {
        "ProtocolSpaceTab": {"cases": [{"name": "OperatorProgression"},
                                       {"name": "WeaponProgression"},]},
        "Schedule": {"cases": [{"name": "一"}, {"name": "二"},
                               {"name": "三"}, {"name": "四"}]},
      }
    }""", encoding="utf-8")
    return root


def live(root, option):
    cfg = json.loads((root / "config" / "mxu-MaaEnd.json").read_text(encoding="utf-8"))
    return cfg["instances"][0]["tasks"][0]["optionValues"][option]


print("[四种类型都能改，而且真的落到盘上]")
r = fixture()
ok, msg = maaend.apply_changes(r, [
    {"task": "ProtocolSpace", "option": "ProtocolSpaceTab", "case": "WeaponProgression"},
    {"task": "ProtocolSpace", "option": "AutoFightDodge", "value": False},
    {"task": "ProtocolSpace", "option": "Schedule", "cases": ["一", "四"]},
    {"task": "ProtocolSpace", "option": "Limits", "values": {"max": 9}},
])
check("整批成功", ok, True)
check("select 落盘", live(r, "ProtocolSpaceTab")["caseName"], "WeaponProgression")
check("switch 落盘", live(r, "AutoFightDodge")["value"], False)
check("checkbox 落盘", live(r, "Schedule")["caseNames"], ["一", "四"])
check("input 落盘", live(r, "Limits")["values"]["max"], 9)
check("说明里点了名", "ProtocolSpaceTab" in msg, True)
check("留了备份", len(list((r / "config").glob("*.bak-*.json"))), 1)

print("\n[enabled 跟着同一条指令走，控制器那份也要跟上]")
r = fixture()
ok, _ = maaend.apply_changes(r, [{"task": "ProtocolSpace", "option": "AutoFightDodge",
                                  "value": True, "enabled": False}])
cfg = json.loads((r / "config" / "mxu-MaaEnd.json").read_text(encoding="utf-8"))
node = cfg["instances"][0]["tasks"][0]
check("任务被停用", node["enabled"], False)
check("controller 那份也停用", node["enabledByController"]["ctrl1"], False)

print("\n[该拒绝的一条都不许放过——放过就是安静地写错]")
for label, change, hint in [
    ("任务名不存在", {"task": "NoSuchTask", "option": "x", "case": "y"}, "没有任务"),
    ("选项名拼错", {"task": "ProtocolSpace", "option": "AutoFihgtDodge", "value": True}, "没有选项"),
    ("给开关发了 case", {"task": "ProtocolSpace", "option": "AutoFightDodge", "case": "开"}, "需要字段"),
    ("取值不在合法表里", {"task": "ProtocolSpace", "option": "ProtocolSpaceTab", "case": "凭空捏造"}, "不接受"),
    ("多选项给了非数组", {"task": "ProtocolSpace", "option": "Schedule", "cases": "一"}, "需要 cases 数组"),
    ("多选项含非法值", {"task": "ProtocolSpace", "option": "Schedule", "cases": ["一", "九"]}, "不接受"),
    ("输入项给了非对象", {"task": "ProtocolSpace", "option": "Limits", "values": [1]}, "需要 values 对象"),
    ("输入框不存在", {"task": "ProtocolSpace", "option": "Limits", "values": {"nope": 1}}, "没有输入框"),
    ("未知类型不敢改", {"task": "ProtocolSpace", "option": "Weird", "case": "y"}, "未知类型"),
]:
    r = fixture()
    before = (r / "config" / "mxu-MaaEnd.json").read_text(encoding="utf-8")
    ok, msg = maaend.apply_changes(r, [change])
    check(f"{label} → 拒绝", ok, False)
    check(f"{label} → 说清了为什么", hint in msg, True)
    check(f"{label} → 文件一个字没动",
          (r / "config" / "mxu-MaaEnd.json").read_text(encoding="utf-8"), before)

print("\n[整批要么全落地要么全不落地]")
r = fixture()
before = (r / "config" / "mxu-MaaEnd.json").read_text(encoding="utf-8")
ok, msg = maaend.apply_changes(r, [
    {"task": "ProtocolSpace", "option": "AutoFightDodge", "value": False},   # 这条合法
    {"task": "ProtocolSpace", "option": "ProtocolSpaceTab", "case": "瞎写"},  # 这条不合法
])
check("有一条不合法就整批拒绝", ok, False)
check("前一条也没落盘", (r / "config" / "mxu-MaaEnd.json").read_text(encoding="utf-8"), before)

print("\n[没有改动时不写盘、不留备份]")
r = fixture()
ok, msg = maaend.apply_changes(r, [])
check("空指令算成功", ok, True)
check("明说没东西可改", "没有需要改动" in msg, True)
check("不留备份", len(list((r / "config").glob("*.bak-*.json"))), 0)

print("\n[配置本身坏了要拒绝，而不是覆盖掉]")
r = fixture()
(r / "config" / "mxu-MaaEnd.json").write_text("{ 这不是 JSON", encoding="utf-8")
ok, msg = maaend.apply_changes(r, [{"task": "ProtocolSpace", "option": "AutoFightDodge",
                                    "value": False}])
check("坏 JSON → 拒绝", ok, False)
check("说的是 JSON 不合法", "不是合法 JSON" in msg, True)

print("\n[配置文件不在也要说清楚]")
r = tmpdir()
ok, msg = maaend.apply_changes(r, [{"task": "x", "option": "y", "value": 1}])
check("找不到配置 → 拒绝", ok, False)
check("说了找不到哪个文件", "找不到 MaaEnd 配置" in msg, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
