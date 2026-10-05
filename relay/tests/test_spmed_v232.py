"""The booster's confirm step under its v2.32 name is the fixed shape: no boot alarm.

The operator read the machine's live nodes.json on 2026-10-06 (MaaEnd v2.32 beta):
AutoUseSpMedicationQuickUse is gone, the confirm step is now
__AutoUseSpMedicationUseEmergencySpBooster, whose all_of holds only a node name -
the 09-03 bug (an inline OCR without its own recognition block) cannot occur there.
Until this change the relay looked for the old name only, so every boot on the
machine would have rung 「⚠️ 终末地应急理智加强剂：中继确认不了…」 for nothing.
"""
import json
import shutil
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
              "win32con", "win32file", "servicemanager", "win32process",
              "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(_name, _Stub(_name))

from _tmp import tmpdir  # noqa: E402
import boot_stages  # noqa: E402
from ark_relay import gameupdate, mastercfg, texts  # noqa: E402

fails = []
LIVE = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.32-spmed"


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def maaend_with(nodes: dict) -> Path:
    d = tmpdir()
    (d / "resource" / "pipeline").mkdir(parents=True)
    (d / "resource" / "pipeline" / "nodes.json").write_text(json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
    return d


class N:
    def __init__(self):
        self.sent = []

    def send(self, title, body, alert=False, **kw):
        self.sent.append((title, alert))
        return []


class Log:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def exception(self, *a, **k): pass


def boot_alarms(maaend_dir) -> list:
    """What the boot stage pushes about the booster for this MaaEnd folder."""
    real = gameupdate.maaend_reenable_records, mastercfg.prune_maaend_orphans
    gameupdate.maaend_reenable_records = lambda cfg: None
    mastercfg.prune_maaend_orphans = lambda *a: ([], "")
    try:
        n = N()
        cfg = types.SimpleNamespace(maaend_dir=str(maaend_dir), automas_dir=None, state_dir=str(tmpdir()))
        boot_stages._stage_reenable_maaend(cfg, n, Log())
        return [t for t, a in n.sent if t == texts.SPMED_UNRECOGNISED and a]
    finally:
        gameupdate.maaend_reenable_records, mastercfg.prune_maaend_orphans = real


print("[v2.32 的真实节点（机器上的 nodes.json）：认得是修好的写法，不报群]")
live = tmpdir() / "maaend"
shutil.copytree(LIVE, live)
check("认得", gameupdate.spmed_shape(live), "fixed")
check("开机不报群", boot_alarms(live), [])

print("[09-03 那种坏写法（行内 OCR 没有自己的 recognition）：报群]")
broken_inline = {"param": {"expected": ["使用"]}, "type": "OCR"}
for name in ("AutoUseSpMedicationQuickUse", "__AutoUseSpMedicationUseEmergencySpBooster"):
    d = maaend_with({name: {"recognition": {"param": {"all_of": ["YellowConfirmButtonType2", broken_inline]},
                                            "type": "And"}}})
    check(f"{name}：判成坏的", gameupdate.spmed_shape(d), "broken")
    check(f"{name}：开机报群一条", len(boot_alarms(d)), 1)

print("[两个名字都没有：报群]")
d = maaend_with({"SomethingElse": {}})
check("判成没有这个节点", gameupdate.spmed_shape(d), "missing")
check("开机报群一条", len(boot_alarms(d)), 1)

print("[旧名字下修好的写法（PR #5453）照样认得]")
d = maaend_with({"AutoUseSpMedicationQuickUse": {"recognition": {"param": {"all_of": [
    "YellowConfirmButtonType2", {"recognition": {"param": {"expected": ["使用"]}, "type": "OCR"}}]}, "type": "And"}}})
check("认得", gameupdate.spmed_shape(d), "fixed")

print("[all_of 空着或里面有认不出的东西：判成认不出，报群]")
for label, all_of in (("空的", []), ("有个数字", ["YellowConfirmButtonType2", 3])):
    d = maaend_with({"__AutoUseSpMedicationUseEmergencySpBooster": {"recognition": {"param": {"all_of": all_of},
                                                                                     "type": "And"}}})
    check(f"{label}：认不出", gameupdate.spmed_shape(d), "unknown")
    check(f"{label}：报群", len(boot_alarms(d)), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
