"""The booster's confirm step in MaaEnd v2.33.0-rc.1 (OCR on the dialog's button region) is known-good.

MaaEnd updated itself on the machine to v2.33.0-rc.1 at 2026-10-16 13:53 Beijing. Upstream PR #6476
(commit cfd2e875): game 1.6 changed the restore-sanity dialog's confirm icon, so
YellowConfirmButtonType2 no longer matched; __AutoUseSpMedicationUseEmergencySpBooster now clicks the
text 确认 its own OCR finds inside roi [860,465,300,90]. The relay only knew the all_of shapes, so the
16:42 Tokyo boot rang 「⚠️ 终末地应急理智加强剂：中继确认不了…」 for a step that works. Fixture:
tests/fixtures/maaend-v2.33.0-rc.1-spmed (the live node, verbatim).
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
from ark_relay.features.gameupdate import gameupdate  # noqa: E402
from ark_relay.core import mastercfg, texts  # noqa: E402

fails = []
LIVE = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.33.0-rc.1-spmed"
V232 = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.32-spmed"


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
    real = mastercfg.prune_maaend_orphans
    mastercfg.prune_maaend_orphans = lambda *a: ([], "")
    try:
        n = N()
        cfg = types.SimpleNamespace(maaend_dir=str(maaend_dir), automas_dir=None, state_dir=str(tmpdir()))
        boot_stages._stage_reenable_maaend(cfg, n, Log())
        return [t for t, a in n.sent if t == texts.SPMED_UNRECOGNISED and a]
    finally:
        mastercfg.prune_maaend_orphans = real


print("[v2.33.0-rc.1 的真实节点（机器上的 nodes.json）：认得，不报群]")
live = tmpdir() / "maaend"
shutil.copytree(LIVE, live)
check("认得是按文字认确认按钮的写法", gameupdate.spmed_shape(live), "ocr")
check("开机不报群", boot_alarms(live), [])

print("[v2.32 的老写法照样认得]")
old = tmpdir() / "maaend"
shutil.copytree(V232, old)
check("认得", gameupdate.spmed_shape(old), "fixed")
check("开机不报群", boot_alarms(old), [])

rc1 = json.loads((LIVE / "resource" / "pipeline" / "nodes.json").read_text(encoding="utf-8"))
NAME = "__AutoUseSpMedicationUseEmergencySpBooster"


def variant(edit, name=NAME):
    node = json.loads(json.dumps(rc1[NAME]))
    edit(node)
    return maaend_with({name: node})


print("[和 rc.1 不一样的文字识别写法：认不出，报群]")
for label, edit in (
        ("没有 roi（会点到背后奖励页的领取）", lambda n: n["recognition"]["param"].pop("roi")),
        ("roi 不是四个数", lambda n: n["recognition"]["param"].update(roi=[860, 465, 300])),
        ("expected 是空的", lambda n: n["recognition"]["param"].update(expected=[])),
        ("没有点击动作", lambda n: n.pop("action")),
        ("识别类型不是 OCR", lambda n: n["recognition"].update(type="TemplateMatch")),
        ("认的字是「领取」（背后奖励页的按钮）", lambda n: n["recognition"]["param"].update(expected=["领取"])),
        ("认的字是任意文字", lambda n: n["recognition"]["param"].update(expected=[".*"])),
        ("确认之外还认「领取」", lambda n: n["recognition"]["param"]["expected"].append("领取")),
        ("认的字里没有「确认」", lambda n: n["recognition"]["param"].update(expected=["(?i)Confirm"])),
        ("roi 是全屏", lambda n: n["recognition"]["param"].update(roi=[0, 0, 1280, 720])),
        ("roi 是 [0,0,0,0]（框架当全屏）", lambda n: n["recognition"]["param"].update(roi=[0, 0, 0, 0])),
        ("roi 挪到左上角", lambda n: n["recognition"]["param"].update(roi=[0, 0, 10, 10])),
        ("roi 上游微调过", lambda n: n["recognition"]["param"].update(roi=[860, 465, 300, 100])),
        ("roi 带小数", lambda n: n["recognition"]["param"].update(roi=[860.0, 465, 300, 90])),
        ("roi 是节点名", lambda n: n["recognition"]["param"].update(roi="SomeNode")),
        ("expected 是一个字符串", lambda n: n["recognition"]["param"].update(expected="确认")),
        ("识别结果取反", lambda n: n.update(inverse=True)),
        ("节点被停用", lambda n: n.update(enabled=False)),
        ("点击位置另给（target）", lambda n: n.update(target=[100, 100, 10, 10])),
        ("点击位置偏移（target_offset）", lambda n: n.update(target_offset=[0, 300, 0, 0])),
        ("OCR 里又夹了 all_of", lambda n: n["recognition"]["param"].update(all_of=["X"])),
        ("type/param 摊平（九月那种错写法）", lambda n: n.update(
            recognition={"type": "OCR", "roi": [860, 465, 300, 90], "expected": ["确认"]})),
        ("action 写成 {type: Click}", lambda n: n.update(action={"type": "Click"}))):
    d = variant(edit)
    check(f"{label}：认不出", gameupdate.spmed_shape(d), "unknown")
    check(f"{label}：开机报群一条", len(boot_alarms(d)), 1)

print("[识别结果不取反、节点明写启用、v2.36.0 扩大的确认框：照样认得]")
for label, edit in (("inverse: false", lambda n: n.update(inverse=False)),
                    ("enabled: true", lambda n: n.update(enabled=True)),
                    ("v2.36.0 roi [860,465,390,120] (PR #6933)", lambda n: n["recognition"]["param"].update(roi=[860, 465, 390, 120]))):
    v = variant(edit)
    check(f"{label}：认得", gameupdate.spmed_shape(v), "ocr")
    check(f"{label}：开机不报群", boot_alarms(v), [])

print("[同样的写法挂在 v2.32 以前的旧名字下：认不出，报群]")
d = variant(lambda n: None, name="AutoUseSpMedicationQuickUse")
check("认不出", gameupdate.spmed_shape(d), "unknown")
check("开机报群一条", len(boot_alarms(d)), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
