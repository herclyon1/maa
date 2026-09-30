"""maaend.apply_changes：改 MaaEnd 配置的那个写入器。

**为什么补这一个**（2026-09-08 审出来）：这个函数会往游戏机上真正生效的配置里写东西，
写错就是刷错关卡、烧理智药——826 事故就是这么来的——而它**一行测试都没有**。
同一天还把它从 127 行拆成了四步，没有测试的话，「拆完行为没变」这句话谁都担保不了。

四种选项类型（select / switch / checkbox / input）各测一遍能改成，
再逐条测那些**必须拒绝**的情形：拼错的选项名、类型对不上的指令、不在合法取值里的值。
拒绝这件事比改成更重要：写进一条 MaaEnd 根本不看的设置，人会以为改生效了。

Since 2026-09-30 the file written is AUTO-MAS's master copy
(data/<sid>/Default/ConfigFile/mxu-MaaEnd.json), not MaaEnd's own
config/mxu-MaaEnd.json: AUTO-MAS copies the master directory over the latter
before every run, so writing it reported a change that never happened.
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


SID = "5c7e0000-0000-0000-0000-00000000maae"


def master(root):
    return root / "automas" / "data" / SID / "Default" / "ConfigFile" / "mxu-MaaEnd.json"


def own(root):
    """MaaEnd's own copy - overwritten from the master before every run, never written."""
    return root / "config" / "mxu-MaaEnd.json"


def apply(root, changes):
    return maaend.apply_changes(root, changes, root / "automas", root / "bak")


def fixture():
    """一份最小但形状真实的 MaaEnd 安装：配置 + 任务定义。"""
    root = tmpdir()
    (root / "config").mkdir(parents=True)
    (root / "tasks").mkdir(parents=True)
    master(root).parent.mkdir(parents=True)
    master(root).write_text(json.dumps({
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
    own(root).write_text('{"instances": [{"tasks": []}], "note": "MaaEnd 自己那份"}',
                         encoding="utf-8")
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
    cfg = json.loads(master(root).read_text(encoding="utf-8"))
    return cfg["instances"][0]["tasks"][0]["optionValues"][option]


OWN = '{"instances": [{"tasks": []}], "note": "MaaEnd 自己那份"}'


print("[四种类型都能改，而且真的落到盘上]")
r = fixture()
ok, msg = apply(r, [
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
check("留了备份，放在母本目录外面", len(list((r / "bak").glob("mxu-MaaEnd.bak-*.json"))), 1)
check("母本目录里没有 .bak（整目录会被拷进 MaaEnd）",
      [f.name for f in master(r).parent.iterdir()], ["mxu-MaaEnd.json"])
check("MaaEnd 自己那份一个字节没动", own(r).read_text(encoding="utf-8"), OWN)

print("\n[enabled 跟着同一条指令走，控制器那份也要跟上]")
r = fixture()
ok, _ = apply(r, [{"task": "ProtocolSpace", "option": "AutoFightDodge",
                                  "value": True, "enabled": False}])
cfg = json.loads(master(r).read_text(encoding="utf-8"))
node = cfg["instances"][0]["tasks"][0]
check("任务被停用", node["enabled"], False)
check("controller 那份也停用", node["enabledByController"]["ctrl1"], False)

print("\n[该拒绝的一条都不许放过——放过就是安静地写错]")
for label, change, hint in [
    ("任务名不存在", {"task": "NoSuchTask", "option": "x", "case": "y"}, "没有任务"),
    ("选项名拼错", {"task": "ProtocolSpace", "option": "AutoFihgtDodge", "value": True}, "没有选项"),
    ("给开关发了 case", {"task": "ProtocolSpace", "option": "AutoFightDodge", "case": "开"}, "要给的是"),
    ("取值不在合法表里", {"task": "ProtocolSpace", "option": "ProtocolSpaceTab", "case": "凭空捏造"}, "不接受"),
    ("多选项给了非数组", {"task": "ProtocolSpace", "option": "Schedule", "cases": "一"}, "需要 cases 数组"),
    ("多选项含非法值", {"task": "ProtocolSpace", "option": "Schedule", "cases": ["一", "九"]}, "不接受"),
    ("输入项给了非对象", {"task": "ProtocolSpace", "option": "Limits", "values": [1]}, "需要 values 对象"),
    ("输入框不存在", {"task": "ProtocolSpace", "option": "Limits", "values": {"nope": 1}}, "没有输入框"),
    ("未知类型不敢改", {"task": "ProtocolSpace", "option": "Weird", "case": "y"}, "未知类型"),
]:
    r = fixture()
    before = master(r).read_text(encoding="utf-8")
    ok, msg = apply(r, [change])
    check(f"{label} → 拒绝", ok, False)
    check(f"{label} → 说清了为什么", hint in msg, True)
    check(f"{label} → 文件一个字没动",
          master(r).read_text(encoding="utf-8"), before)

print("\n[整批要么全落地要么全不落地]")
r = fixture()
before = master(r).read_text(encoding="utf-8")
ok, msg = apply(r, [
    {"task": "ProtocolSpace", "option": "AutoFightDodge", "value": False},   # 这条合法
    {"task": "ProtocolSpace", "option": "ProtocolSpaceTab", "case": "瞎写"},  # 这条不合法
])
check("有一条不合法就整批拒绝", ok, False)
check("前一条也没落盘", master(r).read_text(encoding="utf-8"), before)

print("\n[没有改动时不写盘、不留备份]")
r = fixture()
ok, msg = apply(r, [])
check("空指令算成功", ok, True)
check("明说没东西可改", "没有需要改动" in msg, True)
check("不留备份", (r / "bak").exists(), False)

print("\n[配置本身坏了要拒绝，而不是覆盖掉]")
r = fixture()
master(r).write_text("{ 这不是 JSON", encoding="utf-8")
ok, msg = apply(r, [{"task": "ProtocolSpace", "option": "AutoFightDodge",
                                    "value": False}])
check("坏 JSON → 拒绝", ok, False)
check("说的是 JSON 不合法", "不是合法 JSON" in msg, True)

print("\n[母本找不到：拒绝，绝不退回去写 MaaEnd 自己那份]")
r = fixture()
master(r).unlink()
ok, msg = apply(r, [{"task": "ProtocolSpace", "option": "AutoFightDodge", "value": False}])
check("找不到母本 → 拒绝", ok, False)
check("说了找不到的是母本", "母本" in msg, True)
check("MaaEnd 自己那份没被改", own(r).read_text(encoding="utf-8"), OWN)
ok, msg = maaend.apply_changes(r, [{"task": "x", "option": "y", "value": 1}], None, r / "bak")
check("AUTO-MAS 目录没给 → 拒绝", (ok, "母本" in msg), (False, True))

print("\n[写完读出来和写的不一样：换回原样并报失败]")
r = fixture()
before = master(r).read_text(encoding="utf-8")
real_write = maaend.atomic_write_text
maaend.atomic_write_text = lambda path, text, **k: Path(path).write_text(text[:-1] + " ", encoding="utf-8")
try:
    ok, msg = apply(r, [{"task": "ProtocolSpace", "option": "AutoFightDodge", "value": False}])
finally:
    maaend.atomic_write_text = real_write
check("读出来不一致 → 报失败", (ok, "读出来和写的不一样" in msg), (False, True))
check("母本换回了原样", master(r).read_text(encoding="utf-8"), before)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
