"""maaend.apply_changes when MaaEnd's option definition cannot be read.

The audit of 2026-10-05 (补丁审查-1005, MaaEnd D5/E): a single-select change was
refused when its definition could not be read (「读不到合法取值，拒绝盲改」), but
a multi-select (checkbox) change went straight to disk - `legal and c not in
legal` lets every value through when `legal` is empty. Neither of the two ways
of "cannot read the definition" (file missing, file unreadable) had a test.

Built from real data: the machine's own mxu-MaaEnd.json of 2026-09-10
(fixtures/maaend-2026-09-10/master-before.json) as the AUTO-MAS master, and the
real interface.json / task definitions of that day and of v2.30.0-rc.1.

The "file missing" case is not hypothetical. Since v2.28.0-beta.4 AutoEssence's
definitions live in tasks/AutoEssence/AutoEssence.json (see the interface.json
import list), while option_spec looks for tasks/AutoEssence.json - so on the
real install every AutoEssence checkbox (AutoEssenceSchedule,
AutoEssenceChooseLocation) was written unchecked.

On origin/main the select checks for "missing" and "truncated" already pass
(they pin the behaviour the checkbox path now copies); for a non-UTF-8 file or
a non-dict option definition both select and checkbox crashed apply_changes
with an exception instead of refusing.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import maaend
from _tmp import tmpdir

FIX = Path(__file__).resolve().parent / "fixtures"
DAY = FIX / "maaend-2026-09-10"
PS = FIX / "maaend-protocolspace-v2.30.0-rc.1" / "tasks" / "ProtocolSpace.json"
SID = "5c7e0000-0000-0000-0000-00000000maae"

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


def master(root):
    return root / "automas" / "data" / SID / "Default" / "ConfigFile" / "mxu-MaaEnd.json"


def install(protocolspace: "bytes | None"):
    """The real 09-10 install; ProtocolSpace.json is the given bytes, or absent."""
    root = tmpdir()
    shutil.copy2(DAY / "interface.json", root / "interface.json")
    shutil.copytree(DAY / "tasks", root / "tasks")
    if protocolspace is not None:
        (root / "tasks" / "ProtocolSpace.json").write_bytes(protocolspace)
    master(root).parent.mkdir(parents=True)
    shutil.copy2(DAY / "master-before.json", master(root))
    return root


def apply(root, change):
    """(ok, message); an exception counts as a crash, not as a refusal."""
    try:
        return maaend.apply_changes(root, [change], root / "automas", root / "bak")
    except Exception as exc:  # noqa: BLE001 - the test reports it
        return None, f"崩了：{type(exc).__name__}: {exc}"


def refused(label, root, change):
    before = master(root).read_bytes()
    ok, msg = apply(root, change)
    check(f"{label} → 拒绝", ok, False)
    check(f"{label} → 说了读不到合法取值", "读不到" in msg and "合法取值" in msg, True)
    check(f"{label} → 母本一个字节没动", master(root).read_bytes() == before, True)
    check(f"{label} → 没留备份（什么都没写）", (root / "bak").exists(), False)


REAL_PS = PS.read_bytes()
CB = {"task": "ProtocolSpace", "option": "ProtocolSpaceSchedule",
      "cases": ["ProtocolSpaceScheduleMonday", "ProtocolSpaceScheduleThursday"]}
SEL = {"task": "ProtocolSpace", "option": "ProtocolSpaceTab", "case": "WeaponProgression"}

print("[对照：定义读得到时，多选照常能改、非法值照常拒绝]")
r = install(REAL_PS)
ok, msg = apply(r, CB)
check("合法的多选值 → 改成", ok, True)
cfg = json.loads(master(r).read_text(encoding="utf-8"))
node = next(t for t in cfg["instances"][0]["tasks"] if t["taskName"] == "ProtocolSpace")
check("落到母本上", node["optionValues"]["ProtocolSpaceSchedule"]["caseNames"], CB["cases"])
r = install(REAL_PS)
ok, msg = apply(r, dict(CB, cases=["ProtocolSpaceScheduleMonday", "凭空捏造"]))
check("非法的多选值 → 拒绝", (ok, "不接受" in msg), (False, True))

print("\n[定义文件不在：真实布局 —— AutoEssence 的定义在 tasks/AutoEssence/AutoEssence.json]")
r = install(REAL_PS)
check("前提：tasks/AutoEssence.json 确实不在", (r / "tasks" / "AutoEssence.json").exists(), False)
refused("AutoEssence 多选（合法值）", r,
        {"task": "AutoEssence", "option": "AutoEssenceSchedule",
         "cases": ["AutoEssenceScheduleMonday"]})
refused("AutoEssence 多选（凭空的值）", r,
        {"task": "AutoEssence", "option": "AutoEssenceChooseLocation", "cases": ["凭空捏造"]})
refused("AutoEssence 单选", r,
        {"task": "AutoEssence", "option": "AutoEssenceObtainMode", "case": "Discard"})

print("\n[定义文件不在：ProtocolSpace.json 被删掉]")
r = install(None)
refused("多选", r, CB)
refused("单选", r, SEL)

print("\n[定义文件读不懂：真实文件被截断一半（不是合法 JSON）]")
r = install(REAL_PS[: len(REAL_PS) // 2])
refused("多选", r, CB)
refused("单选", r, SEL)

print("\n[定义文件读不懂：不是 UTF-8（UTF-16 存的同一份文件）]")
r = install(REAL_PS.decode("utf-8").encode("utf-16"))
refused("多选", r, CB)
refused("单选", r, SEL)

print("\n[定义文件里这个选项的形状不对：option 不是字典]")
r = install(json.dumps({"option": {"ProtocolSpaceSchedule": ["不是字典"],
                                   "ProtocolSpaceTab": "也不是"}}).encode("utf-8"))
refused("多选", r, CB)
refused("单选", r, SEL)

print("\n[不再有读 MaaEnd 自己那份配置的入口（每轮开跑前被母本覆盖，生产没人调）]")
check("没有 describe", hasattr(maaend.MaaEndConfig, "describe"), False)
check("没有 load", hasattr(maaend.MaaEndConfig, "load"), False)
check("没有 config_path", hasattr(maaend.MaaEndConfig(tmpdir()), "config_path"), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
