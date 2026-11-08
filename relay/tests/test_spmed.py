"""The emergency sanity potion: kept off the push, v2.32, v2.33-rc.1.

One part per former file, each run on its own (tests/_parts.py): test_spmed_kept_off_push.py, test_spmed_v232.py, test_spmed_v233_rc1.py.
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


def _part_spmed_kept_off_push():
    """应急理智加强剂 is never kept off; a booster step the relay cannot recognise rings the
group at every boot (2026-10-06).

Until 2026-10-06 boot_stages._stage_reenable_maaend kept the task off while
gameupdate could not tell whether upstream had fixed the booster's confirm node, and
said so under 「⚠️ 游戏更新没能确认」 (info route), once per MaaEnd version. The user,
2026-10-06, on the sanity booster: 「那个要一直开着，如果上游maaend改了导致没生效就要报警」,
and on who switched it off: 「我开的任务是谁说要关的」. Now the task is not touched, and every boot that finds the step in a shape the
relay does not know to work pushes texts.SPMED_UNRECOGNISED to the group
(docs/NOTIFICATIONS.md). (The file keeps its old name: the test map lists it.)

Input: the real v2.30.0-beta.4 nodes.json (fixtures/maaend-v2.30.0-beta.4-spmed) with
the confirm step removed under both of its names (AutoUseSpMedicationQuickUse and,
from v2.30/v2.32, __AutoUseSpMedicationUseEmergencySpBooster) - the real file has the
new one in the fixed shape and rings nothing (test_spmed_v232.py) - and the machine's
master (fixtures/maaend-2026-09-10/master-before.json) with the booster task on.

    Formerly test_spmed_kept_off_push.py.
    """
    import json
    import shutil
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    import boot_stages
    from ark_relay.features.makeup import collect_retry
    from ark_relay.features.gameupdate import gameupdate as gu
    from ark_relay.core import mastercfg, notify, texts


    class Notifier:
        def __init__(self): self.sent = []
        def send(self, title, body, **k): self.sent.append((title, body, bool(k.get("alert"))))


    class Log:
        def __init__(self): self.lines = []
        def info(self, *a, **k): self.lines.append(("info", a))
        def warning(self, *a, **k): self.lines.append(("warning", a))
        def exception(self, *a, **k): self.lines.append(("exception", a))


    mastercfg.prune_maaend_orphans = lambda *a: ([], "")
    mastercfg.migrate_maaend_options = lambda *a: ([], "")
    collect_retry.restore_master = lambda cfg: ""
    FIX = Path(__file__).resolve().parent / "fixtures"
    TITLE = getattr(texts, "SPMED_UNRECOGNISED", "<no such title>")

    root = tmpdir()
    maaend = root / "maaend"
    (maaend / "resource" / "pipeline").mkdir(parents=True)
    shutil.copy(FIX / "maaend-v2.30.0-beta.4-spmed" / "interface.json", maaend / "interface.json")
    _nodes = json.loads((FIX / "maaend-v2.30.0-beta.4-spmed" / "resource" / "pipeline" / "nodes.json")
                        .read_text(encoding="utf-8"))
    for _gone in ("AutoUseSpMedicationQuickUse", "__AutoUseSpMedicationUseEmergencySpBooster"):
        _nodes.pop(_gone, None)
    (maaend / "resource" / "pipeline" / "nodes.json").write_text(json.dumps(_nodes, ensure_ascii=False),
                                                                 encoding="utf-8")
    master = root / "automas" / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"
    master.parent.mkdir(parents=True)
    doc = json.loads((FIX / "maaend-2026-09-10" / "master-before.json").read_text(encoding="utf-8"))
    doc["instances"][0]["tasks"].append({"taskName": "AutoUseSpMedication", "enabled": True,
                                         "enabledByController": {"Win32-Front": True}})
    master.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "state").mkdir()
    cfg = types.SimpleNamespace(automas_dir=root / "automas", maaend_dir=maaend, state_dir=root / "state")
    before = master.read_bytes()

    print("[the booster step under neither of its names - every boot rings the group, the task is left on]")
    for boot in (1, 2, 3):
        n, lg = Notifier(), Log()
        boot_stages._stage_reenable_maaend(cfg, n, lg)
        check(f"boot {boot}: one push, to the group", [(t, a) for t, _b, a in n.sent], [(TITLE, True)])
    check("the master is not touched", master.read_bytes() == before, True)
    check("the title routes to the group", notify.route_of(TITLE, alert=True), "group")
    body = n.sent[-1][1] if n.sent else ""
    check("the text is plain Chinese", texts.plain(body), [])
    check("the text says the task stays on", "一直开着，中继不会关它" in body, True)
    check("not the old info title", [t for t, _b, _a in n.sent if "没能确认" in t], [])

    print("\n[the check failing does not take the stage down]")
    real = getattr(gu, "spmed_check", None)
    gu.spmed_check = lambda cfg: (_ for _ in ()).throw(OSError("磁盘读不了"))
    n, lg = Notifier(), Log()
    boot_stages._stage_reenable_maaend(cfg, n, lg)
    check("logged as an exception, nothing pushed", ([x[0] for x in lg.lines if x[0] == "exception"], n.sent),
          (["exception"], []))
    if real is not None:
        gu.spmed_check = real


def _part_spmed_v232():
    """The booster's confirm step under its v2.32 name is the fixed shape: no boot alarm.

The operator read the machine's live nodes.json on 2026-10-06 (MaaEnd v2.32 beta):
AutoUseSpMedicationQuickUse is gone, the confirm step is now
__AutoUseSpMedicationUseEmergencySpBooster, whose all_of holds only a node name -
the 09-03 bug (an inline OCR without its own recognition block) cannot occur there.
Until this change the relay looked for the old name only, so every boot on the
machine would have rung 「⚠️ 终末地应急理智加强剂：中继确认不了…」 for nothing.

    Formerly test_spmed_v232.py.
    """
    import json
    import shutil
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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

    import boot_stages
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.core import mastercfg, texts

    LIVE = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.32-spmed"


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


def _part_spmed_v233_rc1():
    """The booster's confirm step in MaaEnd v2.33.0-rc.1 (OCR on the dialog's button region) is known-good.

MaaEnd updated itself on the machine to v2.33.0-rc.1 at 2026-10-16 13:53 Beijing. Upstream PR #6476
(commit cfd2e875): game 1.6 changed the restore-sanity dialog's confirm icon, so
YellowConfirmButtonType2 no longer matched; __AutoUseSpMedicationUseEmergencySpBooster now clicks the
text 确认 its own OCR finds inside roi [860,465,300,90]. The relay only knew the all_of shapes, so the
16:42 Tokyo boot rang 「⚠️ 终末地应急理智加强剂：中继确认不了…」 for a step that works. Fixture:
tests/fixtures/maaend-v2.33.0-rc.1-spmed (the live node, verbatim).

    Formerly test_spmed_v233_rc1.py.
    """
    import json
    import shutil
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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

    import boot_stages
    from ark_relay.features.gameupdate import gameupdate
    from ark_relay.core import mastercfg, texts

    LIVE = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.33.0-rc.1-spmed"
    V232 = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.32-spmed"


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


if __name__ == "__main__":
    sys.exit(run_parts([_part_spmed_kept_off_push, _part_spmed_v232, _part_spmed_v233_rc1]))
