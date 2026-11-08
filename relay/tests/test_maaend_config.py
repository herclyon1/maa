"""MaaEnd's config: the controller cache, defs 2.28, migrated options, the stock switch and unread defs, a name mismatch, the phone page beta5, a skipped schedule and its report, write and read back.

One part per former file, each run on its own (tests/_parts.py): test_maaend_controller_cache.py, test_maaend_defs_228.py, test_maaend_migrate_options.py, test_maaend_migrate_stock_switch.py, test_maaend_migrate_unread_defs.py, test_maaend_name_mismatch.py, test_maaend_phone_page_beta5.py, test_maaend_schedule_skip.py, test_maaend_skipped_report.py, test_maaend_write_readback.py.
"""
from __future__ import annotations

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


def _part_maaend_controller_cache():  # noqa: C901 - the whole body of the file this part was
    """Every relay write of a MaaEnd task's switch leaves the master as MXU's UI saves it.

MXU keeps a per-controller copy of each task's switch (`enabledByController`) and
on every save writes `cacheTaskEnabledForController(cache, inst.controllerName,
enabled)` (MXU src/utils/taskControllerCache.ts, src/stores/appStore.ts
generateConfig; ported in gamesim/lib/maaend_schema.py with its source pinned by
test_gl_maaend_config.py). Until 2026-10-17 two of the three relay writers set only
`enabled` (mastercfg.write_maaend "@enabled", sanity_plan._toggle_sanity_tasks), and
makeup._set_flag flipped every key of the cache. The master read off the game PC on
2026-10-16 (fixtures/maaend-v2.33-essence/master-1016.json) carries such stale
copies: ProtocolSpace enabled=False with {"Win32-Front": true}; AutoEssence a bare
`true`.

Checked here, on that master: after each relay write the touched task has
`enabled == enabledByController["Win32-Front"]` with the cache a dict, and an MXU
load + save of the written file changes no flag; the relay's setter agrees with the
port of MXU's function on every shape of cache.

Old code runs this file too (the red-before-green proof): a missing function is a
failed case, not a crash.

    Formerly test_maaend_controller_cache.py.
    """
    #!/usr/bin/env python3

    import json
    import types

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE / "gamesim" / "lib"))

    import maaend_schema as ms
    from ark_relay.core import mastercfg
    from ark_relay.features.makeup import makeup
    from ark_relay.features.weekly import sanity_plan

    FX = HERE / "fixtures" / "maaend-v2.33-essence"
    MASTER = json.loads((FX / "master-1016.json").read_text(encoding="utf-8"))
    CTRL = "Win32-Front"
    FAILED: list[str] = []


    def require(name: str, ok: bool, detail: object = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": {detail}"))
        if not ok:
            FAILED.append(name)


    def put_master(doc: dict) -> Path:
        """A fresh AUTO-MAS dir holding `doc` as the MaaEnd master; returns its root."""
        root = tmpdir()
        d = root / "data" / "sid" / "Default" / "ConfigFile"
        d.mkdir(parents=True)
        (d / "mxu-MaaEnd.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return root


    def master_file(root: Path) -> Path:
        return root / "data" / "sid" / "Default" / "ConfigFile" / "mxu-MaaEnd.json"


    def task_of(doc: dict, name: str) -> dict:
        return next(t for t in doc["instances"][0]["tasks"] if t.get("taskName") == name)


    def flags(doc: dict) -> list:
        return [(t.get("taskName"), t.get("enabled"), t.get("enabledByController"))
                for inst in doc.get("instances") or [] for t in inst.get("tasks") or []]


    def check_written(label: str, root: Path, touched: list[str], untouched: dict) -> None:
        """The touched tasks are consistent and survive an MXU load + save; the others
    are byte-for-byte what they were."""
        doc = json.loads(master_file(root).read_text(encoding="utf-8"))
        saved = ms.mxu_load_save_flags(doc)
        for name in touched:
            t = task_of(doc, name)
            cache = t.get("enabledByController")
            require(f"[{label}] {name}: cache is a dict", isinstance(cache, dict), cache)
            require(f"[{label}] {name}: enabled == enabledByController[{CTRL}]",
                    isinstance(cache, dict) and cache.get(CTRL) is t.get("enabled"), (t.get("enabled"), cache))
            st = task_of(saved, name)
            require(f"[{label}] {name}: an MXU load + save changes no flag",
                    (st.get("enabled"), st.get("enabledByController")) == (t.get("enabled"), cache),
                    (st.get("enabledByController"), cache))
        for name, was in untouched.items():
            require(f"[{label}] {name} left as it was", task_of(doc, name) == was, task_of(doc, name))


    def section_fixture() -> None:
        print("[fixture: the 10-16 master carries stale per-controller copies]")
        saved = ms.mxu_load_save_flags(MASTER)
        require("[fixture] ProtocolSpace enabled=False, cache {Win32-Front: true}",
                (task_of(MASTER, "ProtocolSpace")["enabled"], task_of(MASTER, "ProtocolSpace")["enabledByController"])
                == (False, {CTRL: True}))
        require("[fixture] AutoEssence cache is a bare true", task_of(MASTER, "AutoEssence")["enabledByController"] is True)
        require("[fixture] an MXU load + save of it would rewrite those two",
                [n for (n, *_a), b in zip(flags(MASTER), flags(saved), strict=True) if tuple(_a) != b[1:]]
                == ["ProtocolSpace", "AutoEssence"], flags(saved))


    def section_port() -> None:
        print("[port: the relay setter is MXU's cacheTaskEnabledForController]")
        port = ms.cache_task_enabled_for_controller
        require("[port] bare boolean -> dict", port(True, CTRL, False) == {CTRL: False})
        require("[port] missing -> dict", port(None, CTRL, True) == {CTRL: True})
        require("[port] other controllers kept", port({"ADB": False, CTRL: True}, CTRL, False) == {"ADB": False, CTRL: False})
        require("[port] no controller name -> cache as it was", port(True, None, False) is True and port(None, "", True) is None)
        setter = getattr(mastercfg, "set_maaend_enabled", None)
        require("[port] mastercfg.set_maaend_enabled exists", setter is not None)
        if setter is None:
            return
        for cache in ("<absent>", None, True, False, {}, {CTRL: True}, {CTRL: False}, {"ADB": True}, {"ADB": False, CTRL: True}):
            for ctrl in (CTRL, None, ""):
                for on in (True, False):
                    for was in (True, False):
                        t = {"taskName": "X", "enabled": was}
                        if cache != "<absent>":
                            t["enabledByController"] = json.loads(json.dumps(cache))
                        before = json.loads(json.dumps(t))
                        changed = setter(t, on, ctrl)
                        want_cache = port(before.get("enabledByController"), ctrl, on)
                        want = {"taskName": "X", "enabled": on}
                        if want_cache is not None or "enabledByController" in before:
                            want["enabledByController"] = want_cache
                        case = f"cache={cache!r} ctrl={ctrl!r} {was}->{on}"
                        if t != want or changed != (t != before):
                            require(f"[port] setter == port ({case})", False, (t, want, changed))
                            return
        require("[port] setter == port on every cache shape, controller and value", True)


    def section_write_maaend() -> None:
        print("[mastercfg.write_maaend @enabled]")
        root = put_master(MASTER)
        keep = {n: task_of(MASTER, n) for n in ("AutoEssence", "DailyRewards")}
        ok, msg = mastercfg.write_maaend(root, FX, "ProtocolSpace/@enabled", True)
        require("[write_maaend] ProtocolSpace on accepted", ok, msg)
        check_written("write_maaend on", root, ["ProtocolSpace"], keep)
        ok, msg = mastercfg.write_maaend(root, FX, "ProtocolSpace/@enabled", False)
        require("[write_maaend] ProtocolSpace off accepted", ok, msg)
        check_written("write_maaend off", root, ["ProtocolSpace"], keep)
        ok, msg = mastercfg.write_maaend(root, FX, "AutoEssence/@enabled", False)
        require("[write_maaend] AutoEssence (bare true cache) off accepted", ok, msg)
        check_written("write_maaend bare", root, ["AutoEssence"], {"DailyRewards": keep["DailyRewards"]})


    def section_sanity_plan() -> None:
        print("[sanity_plan.set_plan]")
        root = put_master(MASTER)
        before = master_file(root).read_bytes()
        ok, msg = sanity_plan.set_plan(root, "Essence")
        require("[sanity_plan] the plan already in force: no write (a stale cache alone is no change)",
                ok and master_file(root).read_bytes() == before, msg)
        keep = {"DailyRewards": task_of(MASTER, "DailyRewards")}
        ok, msg = sanity_plan.set_plan(root, "OperatorProgression", "T-Creds")
        require("[sanity_plan] switch to ProtocolSpace accepted", ok, msg)
        check_written("sanity_plan ProtocolSpace", root, ["ProtocolSpace", "AutoEssence"], keep)
        doc = json.loads(master_file(root).read_text(encoding="utf-8"))
        require("[sanity_plan] ProtocolSpace on, AutoEssence off",
                (task_of(doc, "ProtocolSpace")["enabled"], task_of(doc, "AutoEssence")["enabled"]) == (True, False))
        ok, msg = sanity_plan.set_plan(root, "Essence")
        require("[sanity_plan] switch back to essence accepted", ok, msg)
        check_written("sanity_plan Essence", root, ["ProtocolSpace", "AutoEssence"], keep)


    def section_makeup() -> None:
        print("[makeup.stash_first]")
        doc = json.loads(json.dumps(MASTER))
        doc["instances"][0]["tasks"].append({"taskName": makeup.STASH, "enabled": False,
                                             "enabledByController": True, "optionValues": {}})
        root = put_master(doc)
        cfg = types.SimpleNamespace(automas_dir=root, state_dir=tmpdir(), maaend_dir=FX)
        keep = {n: task_of(doc, n) for n in ("ProtocolSpace", "AutoEssence", "DailyRewards")}
        changed, why = makeup.stash_first(cfg, "run-1", makeup.datetime(2026, 10, 17, 4, 0, tzinfo=makeup.SERVER_TZ))
        require("[makeup] 存放背包 switched on and moved first", changed and why == "", (changed, why))
        check_written("makeup bare", root, [makeup.STASH], keep)
        makeup.restore(cfg)
        require("[makeup] restore puts the original flags back",
                flags(json.loads(master_file(root).read_text(encoding="utf-8"))) == flags(doc))

        # Another controller's entry is MXU's, not the relay's: it stays as it was.
        doc2 = json.loads(json.dumps(MASTER))
        doc2["instances"][0]["tasks"].insert(0, {"taskName": makeup.STASH, "enabled": True,
                                                 "enabledByController": {"ADB": False, CTRL: True},
                                                 "optionValues": {}})
        root2 = put_master(doc2)
        cfg2 = types.SimpleNamespace(automas_dir=root2, state_dir=tmpdir(), maaend_dir=FX)
        before = master_file(root2).read_bytes()
        changed, why = makeup.stash_first(cfg2, "run-2", makeup.datetime(2026, 10, 17, 4, 0, tzinfo=makeup.SERVER_TZ))
        require("[makeup] on and first already: nothing written, other controller's copy kept",
                not changed and why == "" and master_file(root2).read_bytes() == before, (changed, why))

        # On and first with a stale bare-boolean copy: a stale copy alone makes no write.
        doc3 = json.loads(json.dumps(MASTER))
        doc3["instances"][0]["tasks"].insert(0, {"taskName": makeup.STASH, "enabled": True,
                                                 "enabledByController": True, "optionValues": {}})
        root3 = put_master(doc3)
        cfg3 = types.SimpleNamespace(automas_dir=root3, state_dir=tmpdir(), maaend_dir=FX)
        before = master_file(root3).read_bytes()
        changed, why = makeup.stash_first(cfg3, "run-3", makeup.datetime(2026, 10, 17, 4, 0, tzinfo=makeup.SERVER_TZ))
        require("[makeup] on and first with a bare-true copy: nothing written",
                not changed and why == "" and master_file(root3).read_bytes() == before, (changed, why))

        # This controller's copy says off while enabled is true: switched on in both.
        doc4 = json.loads(json.dumps(MASTER))
        doc4["instances"][0]["tasks"].insert(0, {"taskName": makeup.STASH, "enabled": True,
                                                 "enabledByController": {"ADB": True, CTRL: False},
                                                 "optionValues": {}})
        root4 = put_master(doc4)
        cfg4 = types.SimpleNamespace(automas_dir=root4, state_dir=tmpdir(), maaend_dir=FX)
        changed, why = makeup.stash_first(cfg4, "run-4", makeup.datetime(2026, 10, 17, 4, 0, tzinfo=makeup.SERVER_TZ))
        require("[makeup] this controller's copy off: written", changed and why == "", (changed, why))
        check_written("makeup ctrl-off", root4, [makeup.STASH], keep)
        st = task_of(json.loads(master_file(root4).read_text(encoding="utf-8")), makeup.STASH)
        require("[makeup] the other controller's entry is kept", st["enabledByController"] == {"ADB": True, CTRL: True},
                st["enabledByController"])


    def main() -> int:
        for section in (section_fixture, section_port, section_write_maaend, section_sanity_plan, section_makeup):
            try:
                section()
            except Exception as exc:  # noqa: BLE001 - any error is this section's failure, reported
                require(f"{section.__name__} ran", False, f"{type(exc).__name__}: {exc}")
        if FAILED:
            print(f"FAILED {len(FAILED)}: {FAILED}")
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_maaend_defs_228():
    """The phone page must show Chinese names and real choices on MaaEnd v2.28.

On 2026-09-09 the user's phone showed AutoEssenceDoOverride, AutoEssenceObtainMode
and friends as raw keys, with the claim-mode select collapsed into a text box.
v2.28.0-beta.4 had moved tasks/AutoEssence.json into a subfolder, the relay read
definitions by file name, found nothing, and fell back to the key - silently.
He asked: 「不是说强制要求了人话界面吗？」 This test runs read_maaend over the real
v2.28 files (fetched off the machine that night) and refuses any raw key.

The same release removed the standalone AutoUseSpMedication task; the config
still carries it. That has to be reported as an orphan, not shown as a live
setting.

    Formerly test_maaend_defs_228.py.
    """
    import json
    import re

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import mastercfg

    HAN = re.compile(r"[一-鿿]")


    FX = Path(__file__).resolve().parent / "fixtures" / "maaend228"
    root = tmpdir()
    automas = root / "AUTO-MAS"
    cf = automas / "data" / "x" / "Default" / "ConfigFile"
    cf.mkdir(parents=True)
    # The master as it was on the machine that night: AutoEssence without the two
    # new booster keys, plus the orphaned standalone task.
    (cf / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"tasks": [
        {"taskName": "AutoEssence", "enabled": True, "optionValues": {
            "AutoEssenceDoOverride": {"type": "switch", "value": False},
            "AutoEssenceObtainMode": {"type": "select", "caseName": "ObtainScaling1"},
            "AutoEssenceRepeatCount": {"type": "input", "values": {"AutoEssenceRepeatCountValue": "99"}},
            "AutoEssenceChooseLocation": {"type": "checkbox", "caseNames": ["WLSwordVaultDale"]},
            "EssenceFilterAfterBattle": {"type": "switch", "value": True},
        }},
        {"taskName": "AutoUseSpMedication", "enabled": True, "optionValues": {
            "AutoUseSpMedicationExpireWithinDays": {"type": "select", "caseName": "Days3"}}},
        {"taskName": "AutoCollect", "enabled": True, "optionValues": {
            "AutoCollectRoutes": {"type": "checkbox", "caseNames": ["Route1"]},
            "AutoCollectSchedule": {"type": "checkbox", "caseNames": ["AutoCollectScheduleMonday"]}}},
    ]}]}, ensure_ascii=False), encoding="utf-8")

    r = mastercfg.read_maaend(automas, FX)
    K = "AutoEssence/AutoEssenceSpMedicationExpireWithinDays"

    print("[每一项都要有中文名——原始键名出现在手机上就是失败]")
    raw = {k: v for k, v in r["labels"].items() if not HAN.search(v or "")}
    check("没有一项是英文键名", raw, {})
    check("没有列进「没翻译」的", r.get("untranslated"), [])
    for k in ("AutoEssence/AutoEssenceObtainMode", "AutoEssence/AutoUseSpMedication", K, "AutoCollect/AutoCollectSchedule"):
        check(f"{k} 是选择项，有可选值", bool(r["options"].get(k)), True)
    check("加强剂窗口的可选值就是 MaaEnd 定义的那五档",
          [v for _, v in r["options"].get(K, [])], ["All", "Days10", "Days7", "Days3", "Days1"])
    check("可选值的名字也是中文", all(HAN.search(l) for l, _ in r["options"].get(K, [])), True)
    check("配置里还没有的项按定义默认值显示", r["values"].get(K), "Days3")

    print("\n[这一版脚本已经没有的任务要报成孤儿，不能当成还在跑]")
    check("孤儿任务", r.get("orphans"), ["AutoUseSpMedication"])
    check("孤儿任务的设置不再当成活的展示",
          any(k.startswith("AutoUseSpMedication/") for k in r["values"]), False)

    print("\n[写：只认定义里的值；定义声明了的项可以按默认形状建出来]")
    ok, msg = mastercfg.write_maaend(automas, FX, K, "Days99")
    check("不认识的值被拒", ok, False)
    ok, msg = mastercfg.write_maaend(automas, FX, K, "All")
    check("All 写进去了", ok, True)
    check("回读是 All", mastercfg.read_maaend(automas, FX)["values"].get(K), "All")
    ok, msg = mastercfg.write_maaend(automas, FX, "AutoEssence/不存在的项", "x")
    check("定义里没有的项仍然拒绝造", ok, False)

    print("\n[死条目不光报警，要清掉——但要两个独立信号都说它死了才动手]")
    import logging


    class _Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.recs = []
            self.titles = []

        def emit(self, record):
            self.recs.append((record.levelno, record.getMessage()))
            self.titles.append((getattr(record, "ark_alarm", None) or (None,))[0])


    _g = _Grab()
    mastercfg.log.addHandler(_g)
    removed, note = mastercfg.prune_maaend_orphans(automas, FX)
    mastercfg.log.removeHandler(_g)
    check("清掉的正是那一条", removed, ["AutoUseSpMedication"])
    check("删了就 WARNING（报群），点名删了哪一项、原来开着",
          [lv for lv, m in _g.recs if "AutoUseSpMedication（开着）" in m and "删掉" in m], [logging.WARNING])
    from ark_relay.core import texts as _tx
    check("删了的那条以自己的标题进群（「🧹 终末地配置清掉了死条目」）", _tx.MAAEND_PRUNED in _g.titles, True)
    check("话里说清清了什么、备份在哪", "AutoUseSpMedication" in note and "bak-orphans" in note, True)
    after = mastercfg.read_maaend(automas, FX)
    check("清完不再是孤儿", after.get("orphans"), [])
    check("别的任务一个没少", sorted(t["taskName"] for t in json.loads((cf / "mxu-MaaEnd.json").read_text(encoding="utf-8"))["instances"][0]["tasks"]),
          ["AutoCollect", "AutoEssence"])
    check("再跑一遍什么都不做", mastercfg.prune_maaend_orphans(automas, FX), ([], ""))
    check("备份文件在", bool(list(cf.glob("mxu-MaaEnd.json.bak-orphans-*"))), True)
    # CreditShoppingN2 is declared by a file that only parses with the full JSONC
    # stripper; the definitions index knows it, so it must never be pruned.
    (cf / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"tasks": [
        {"taskName": "CreditShoppingN2", "enabled": True, "optionValues": {}},
        {"taskName": "__MXU_WEBHOOK__", "enabled": True, "optionValues": {}}]}]}), encoding="utf-8")
    check("定义里有的不算孤儿（CreditShoppingN2）", mastercfg.read_maaend(automas, FX).get("orphans"), [])
    check("不会误删", mastercfg.prune_maaend_orphans(automas, FX)[0], [])

    print("\n[绝不删 MaaEnd 还定义着的：定义看不全就不动，WARNING 说明原因]")
    import shutil


    def _fx_copy():
        d = tmpdir() / "maaend"
        shutil.copytree(FX, d)
        return d


    def _master(tasks):
        (cf / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"tasks": tasks}]}), encoding="utf-8")


    ORPHAN_OFF = {"taskName": "AutoUseSpMedication", "enabled": False, "optionValues": {}}
    _master([dict(ORPHAN_OFF)])
    _g = _Grab()
    mastercfg.log.addHandler(_g)
    removed, note = mastercfg.prune_maaend_orphans(automas, FX)
    mastercfg.log.removeHandler(_g)
    check("关着的残留照样清掉", removed, ["AutoUseSpMedication"])
    check("关着的删了也 WARNING（每次删都报群），写明原来关着",
          [lv for lv, m in _g.recs if "AutoUseSpMedication（关着）" in m and "删掉" in m], [logging.WARNING])

    # A definition file that does not parse but names the candidate: it may still be defined.
    fx = _fx_copy()
    bad = fx / "tasks" / "CreditShopping.json"
    bad.write_text('{ "task": [ {"name": "AutoUseSpMedication"} ] <<< not json', encoding="utf-8")
    _master([dict(ORPHAN_OFF, enabled=True)])
    _g = _Grab()
    mastercfg.log.addHandler(_g)
    removed, note = mastercfg.prune_maaend_orphans(automas, fx)
    mastercfg.log.removeHandler(_g)
    check("读不了的定义文件里提到它：不删", removed, [])
    check("不删也 WARNING（报群），说明为什么", [lv for lv, m in _g.recs if "没有删" in m and "CreditShopping.json" in m],
          [logging.WARNING])
    check("说明里点名是哪个文件", "CreditShopping.json" in note and "AutoUseSpMedication" in note, True)
    check("母本一个字没动", json.loads((cf / "mxu-MaaEnd.json").read_text(encoding="utf-8"))["instances"][0]["tasks"],
          [dict(ORPHAN_OFF, enabled=True)])

    # interface.json (MaaEnd's own list of definition files) unreadable: the fallback glob may miss files.
    fx = _fx_copy()
    (fx / "interface.json").write_text("{ broken", encoding="utf-8")
    _master([dict(ORPHAN_OFF, enabled=True)])
    removed, note = mastercfg.prune_maaend_orphans(automas, fx)
    check("定义清单读不了：不删、说明原因", (removed, "interface.json" in note), ([], True))

    # A listed definition file that exists but cannot be opened.
    fx = _fx_copy()
    (fx / "tasks" / "PuzzleSolver.json").unlink()
    (fx / "tasks" / "PuzzleSolver.json").mkdir()
    _master([dict(ORPHAN_OFF, enabled=True)])
    removed, note = mastercfg.prune_maaend_orphans(automas, fx)
    check("定义文件打不开：不删、说明是哪个", (removed, "PuzzleSolver.json" in note), ([], True))


def _part_maaend_migrate_options():
    """The master config must be rewritten when MaaEnd changes an option's format.

Real files, 2026-09-10: the AUTO-MAS master as it was that morning, and the
v2.28.0-beta.5 definitions of AutoCollect and AutoEssence. MaaEnd discards a
saved value whose option it no longer has, so the old 自动采集 route list has to
become the per-region lists it replaced - with the same routes picked - and
the location list of 基质刷取 needs the AutoEssenceMenu key it now hangs under.

    Formerly test_maaend_migrate_options.py.
    """
    import json
    import shutil
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import mastercfg

    FIX = Path(__file__).parent / "fixtures" / "maaend-2026-09-10"


    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        # A MaaEnd install with only the two task files that matter, listed in
        # interface.json the way the real one lists them.
        maaend = d / "maaend"
        (maaend / "tasks" / "AutoEssence").mkdir(parents=True)
        shutil.copy(FIX / "tasks" / "AutoCollect.json", maaend / "tasks" / "AutoCollect.json")
        shutil.copy(FIX / "tasks" / "AutoEssence" / "AutoEssence.json",
                    maaend / "tasks" / "AutoEssence" / "AutoEssence.json")
        iface = json.loads((FIX / "interface.json").read_text(encoding="utf-8"))
        iface["import"] = ["tasks/AutoCollect.json", "tasks/AutoEssence/AutoEssence.json"]
        (maaend / "interface.json").write_text(json.dumps(iface), encoding="utf-8")
        # And the AUTO-MAS master where the relay expects it.
        automas = d / "automas"
        cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfgdir.mkdir(parents=True)
        master = cfgdir / "mxu-MaaEnd.json"
        shutil.copy(FIX / "master-before.json", master)

        def task(doc, name):
            return next(t for t in doc["instances"][0]["tasks"] if t.get("taskName") == name)

        before = json.loads(master.read_text(encoding="utf-8"))
        old_routes = set(task(before, "AutoCollect")["optionValues"]["AutoCollectRoutes"]["caseNames"])
        check("样本确实还是旧写法", "AutoCollectRoutes" in task(before, "AutoCollect")["optionValues"])

        changes, note = mastercfg.migrate_maaend_options(automas, maaend)
        print("\n".join("    " + c for c in changes))
        check("有改动", bool(changes))
        after = json.loads(master.read_text(encoding="utf-8"))
        ac = task(after, "AutoCollect")["optionValues"]

        print("\n[自动采集：一份路线表拆成两个区域，勾的还是那些]")
        check("旧键没了", "AutoCollectRoutes" not in ac and "AutoCollectCommonRoutes" not in ac)
        valley = set(ac["AutoCollectValleyIVRareRoutes"]["caseNames"])
        wuling = set(ac["AutoCollectWulingRareRoutes"]["caseNames"])
        check("四号谷地的稀有路线 = 原来勾的 ∩ 该区域的", valley, {"Route4", "Route5", "Route6", "Route13", "Route14"})
        check("武陵的稀有路线 = 原来勾的 ∩ 该区域的",
              wuling, {"Route1", "Route2", "Route3", "Route7", "Route8", "Route9", "Route10", "Route11", "Route12", "Route15", "Route16", "Route17"})
        check("两边合起来一条不少", valley | wuling, old_routes)
        check("原来没勾普通路线，现在也不勾", ac["AutoCollectValleyIVCommonRoutes"]["caseNames"], [])
        check("区域开关打开", ac["AutoCollectValleyIV"]["value"] and ac["AutoCollectWuling"]["value"])
        check("模式补上 Always", ac["AutoCollectMode"]["caseName"], "Always")
        check("值的写法和 MaaEnd 自己存的一样", ac["AutoCollectValleyIVRareRoutes"]["type"], "checkbox")

        print("\n[基质刷取：地点还是藏剑谷/清波寨，菜单键补上]")
        ae = task(after, "AutoEssence")["optionValues"]
        check("地点没被动", ae["AutoEssenceChooseLocation"]["caseNames"], ["WLSwordVaultDale", "WLQingboStockade"])
        check("补上 AutoEssenceMenu=Random", ae.get("AutoEssenceMenu", {}).get("caseName"), "Random")
        check("吃药那项补上", ae.get("AutoUseSpMedication", {}).get("caseName"), "UseMedication")
        check("死键 SelectInputLanguage 去掉", "EssenceFilterAfterBattleSelectInputLanguage" not in ae)
        check("次数 99 没被动", ae["AutoEssenceRepeatCount"]["values"]["AutoEssenceRepeatCountValue"], "99")

        print("\n[不该碰的]")
        check("定义文件不在索引里的任务（CreditShoppingN2）原样",
              task(after, "CreditShoppingN2")["optionValues"], task(before, "CreditShoppingN2")["optionValues"])
        check("MXU 自己的 __ 任务原样",
              [t for t in after["instances"][0]["tasks"] if t["taskName"].startswith("__")],
              [t for t in before["instances"][0]["tasks"] if t["taskName"].startswith("__")])
        check("任务数不变", len(after["instances"][0]["tasks"]), len(before["instances"][0]["tasks"]))
        check("留了备份", any(p.name.startswith("mxu-MaaEnd.json.bak-migrate-") for p in cfgdir.iterdir()))
        check("说明是人话，带备份名", "备份" in note and "按原意改写" in note)

        print("\n[界面的「最近关闭」历史也不能留旧键——MaaEnd 每次加载都会拿它报警]")
        rc_before = before.get("recentlyClosed") or []
        rc_after = after.get("recentlyClosed") or []
        check("原样本里确实有带旧键的历史",
              any("AutoCollectRoutes" in (t.get("optionValues") or {}) for e in rc_before for t in e.get("tasks") or []))
        check("改完历史里没有 AutoCollectRoutes",
              any("AutoCollectRoutes" in (t.get("optionValues") or {}) for e in rc_after for t in e.get("tasks") or []), False)
        check("改完历史里没有 AutoEssenceChallengeMode",
              any("AutoEssenceChallengeMode" in (t.get("optionValues") or {}) for e in rc_after for t in e.get("tasks") or []), False)
        check("定义没读到的任务（SellProduct）那条历史不动",
              any(t.get("taskName") == "SellProduct" for e in rc_after for t in e.get("tasks") or []))
        check("说明里提到了清历史", "最近关闭" in note)

        print("\n[再跑一次：没有改动]")
        changes2, note2 = mastercfg.migrate_maaend_options(automas, maaend)
        check("幂等", (changes2, note2), ([], ""))


def _part_maaend_migrate_stock_switch():
    """自动囤货's buy lists must survive MaaEnd turning them from checkbox into switch.

Real files, 2026-10-10: the AUTO-MAS master (only the AutoStockStaple task and
one untouched task kept) and MaaEnd's AutoStockStaple.json of that day. From
10-03 every MaaEnd launch logged 「选项 "AutoStockBuy…" 的类型已从 "checkbox" 变更为
"switch"，已重置为默认值」 six times and bought by the defaults, not by the
per-item lists the master holds. The migration carries each list over to the
new `<key>Items` checkbox, with the switch on when anything was picked.

    Formerly test_maaend_migrate_stock_switch.py.
    """
    import json
    import shutil
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import mastercfg

    FIX = Path(__file__).parent / "fixtures" / "maaend-2026-10-10"
    KEYS = ("AutoStockBuyDailyGoodsValleyIV", "AutoStockBuyStockFactoryGoodsValleyIV",
            "AutoStockBuyCulturalGoodsValleyIV", "AutoStockBuyDailyGoodsWuling",
            "AutoStockBuyStockFactoryGoodsWuling", "AutoStockBuyCulturalGoodsWuling")


    def stock(doc):
        return next(t for t in doc["instances"][0]["tasks"] if t.get("taskName") == "AutoStockStaple")["optionValues"]


    def setup(d: Path, master_doc: dict) -> "tuple[Path, Path, Path]":
        maaend = d / "maaend"
        (maaend / "tasks").mkdir(parents=True)
        shutil.copy(FIX / "AutoStockStaple.json", maaend / "tasks" / "AutoStockStaple.json")
        (maaend / "interface.json").write_text(json.dumps({"import": ["tasks/AutoStockStaple.json"]}),
                                               encoding="utf-8")
        (maaend / "locales" / "interface").mkdir(parents=True)
        shutil.copy(FIX / "zh_cn-AutoStockStaple.json", maaend / "locales" / "interface" / "zh_cn.json")
        automas = d / "automas"
        cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfgdir.mkdir(parents=True)
        (cfgdir / "mxu-MaaEnd.json").write_text(json.dumps(master_doc, ensure_ascii=False), encoding="utf-8")
        return automas, maaend, cfgdir


    before = json.loads((FIX / "master-before.json").read_text(encoding="utf-8"))
    picks = {k: stock(before)[k]["caseNames"] for k in KEYS}
    check("样本确实还是旧写法（6 项都是多选）", all(stock(before)[k]["type"] == "checkbox" for k in KEYS))

    with tempfile.TemporaryDirectory() as d:
        automas, maaend, cfgdir = setup(Path(d), before)
        master = cfgdir / "mxu-MaaEnd.json"
        changes, note = mastercfg.migrate_maaend_options(automas, maaend)
        print("\n".join("    " + c for c in changes))
        after = json.loads(master.read_text(encoding="utf-8"))
        ov = stock(after)

        print("\n[6 个清单：开关按有没有勾设，勾的物品原样搬到 …Items]")
        check("6 项都改了", len(changes), 6)
        for k in KEYS:
            check(f"{k} 是开关", ov[k]["type"], "switch")
            check(f"{k} 开关 = 原来有没有勾", ov[k]["value"], bool(picks[k]))
            check(f"{k}Items = 原来勾的", ov[k + "Items"], {"type": "checkbox", "caseNames": picks[k]})
        check("谷地工业货品原来一样没勾 → 关（不再买探测器、罗盘）",
              ov["AutoStockBuyStockFactoryGoodsValleyIV"]["value"], False)
        check("谷地日用只勾了雅各布遗产", ov["AutoStockBuyDailyGoodsValleyIVItems"]["caseNames"], ["JakubsLegacy"])

        print("\n[不该碰的]")
        check("限购数量原样", {k: v for k, v in ov.items() if k.endswith("Limit")},
              {k: v for k, v in stock(before).items() if k.endswith("Limit")})
        check("区域开关、排班原样", {k: ov[k] for k in ("AutoStockStapleValleyIV", "AutoStockStapleWuling",
                                                       "AutoStockStapleSchedule")},
              {k: stock(before)[k] for k in ("AutoStockStapleValleyIV", "AutoStockStapleWuling",
                                             "AutoStockStapleSchedule")})
        check("定义不在索引里的任务（DailyRewards）原样",
              after["instances"][0]["tasks"][1], before["instances"][0]["tasks"][1])
        check("留了原样备份", [json.loads(p.read_text(encoding="utf-8")) for p in cfgdir.iterdir()
                           if p.name.startswith("mxu-MaaEnd.json.bak-migrate-")], [before])
        check("说明是人话，带备份名", "备份" in note and "改成了开关" in note)
        check("说明用游戏里的中文名", "四号谷地稳定物资购买 · 工业货品：改成了开关，设为关（原来一样都没勾）" in note)
        check("说明里没有英文键名", "AutoStockBuy" in note, False)

        print("\n[再跑一次：没有改动]")
        check("幂等", mastercfg.migrate_maaend_options(automas, maaend), ([], ""))

    print("\n[勾了新清单里没有的物品：不猜，原样留着让核对去报]")
    odd = json.loads(json.dumps(before))
    stock(odd)["AutoStockBuyDailyGoodsValleyIV"]["caseNames"] = ["JakubsLegacy", "NoSuchItem"]
    with tempfile.TemporaryDirectory() as d:
        automas, maaend, cfgdir = setup(Path(d), odd)
        changes, _ = mastercfg.migrate_maaend_options(automas, maaend)
        ov = stock(json.loads((cfgdir / "mxu-MaaEnd.json").read_text(encoding="utf-8")))
        check("那一项不动", ov["AutoStockBuyDailyGoodsValleyIV"], {"type": "checkbox", "caseNames": ["JakubsLegacy", "NoSuchItem"]})
        check("其余 5 项照迁", len(changes), 5)


def _part_maaend_migrate_unread_defs():
    """migrate_maaend_options does not drop a live value because a definition file was unreadable.

MaaEnd v2.32: 9 of its 46 tasks take options from another file (AutoCollect and
four others from StashBackpack.json, AutoEssence from Location/*.json). When such
a file did not parse, its options looked dead and the migration deleted their
values from the master copy - MaaEnd then runs on defaults. prune_maaend_orphans
already refused on the same blind spots (8dbd1d3b); now the migration does too.

    Formerly test_maaend_migrate_unread_defs.py.
    """
    #!/usr/bin/env python3

    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import mastercfg

    FAILED: list[str] = []


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    def setup(stash_text: str, interface: "str | None" = '{"import": ["tasks/AutoCollect.json", "tasks/StashBackpack.json"]}'):
        root = tmpdir()
        automas = root / "automas"
        cfg = automas / "data" / "sid" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        (cfg / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
            {"taskName": "AutoCollect", "enabled": True, "optionValues": {
                "AutoCollectMode": {"type": "select", "caseName": "Always"},
                "StashBackpackMode": {"type": "select", "caseName": "Deposit"},
                "OldDeadKey": {"type": "switch", "value": True}}}]}]}), encoding="utf-8")
        maaend = root / "maaend"
        (maaend / "tasks").mkdir(parents=True)
        if interface is not None:
            (maaend / "interface.json").write_text(interface, encoding="utf-8")
        (maaend / "tasks" / "AutoCollect.json").write_text(json.dumps({
            "task": [{"name": "AutoCollect", "option": ["AutoCollectMode", "StashBackpackMode"]}],
            "option": {"AutoCollectMode": {"type": "select", "cases": [{"name": "Always"}]}}}), encoding="utf-8")
        (maaend / "tasks" / "StashBackpack.json").write_text(stash_text, encoding="utf-8")
        return automas, maaend, cfg / "mxu-MaaEnd.json"


    def values(master: Path) -> dict:
        return json.loads(master.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["optionValues"]


    GOOD = json.dumps({"option": {"StashBackpackMode": {"type": "select", "cases": [{"name": "Deposit"}]}}})
    BROKEN = GOOD[:-1] + " oops"           # StashBackpack.json does not parse but names its option

    print("[every definition read: a dead key goes, the live ones stay]")
    automas, maaend, master = setup(GOOD)
    changes, note = mastercfg.migrate_maaend_options(automas, maaend)
    require("OldDeadKey is removed", "OldDeadKey" not in values(master), note)
    require("StashBackpackMode is kept", "StashBackpackMode" in values(master), note)

    print("[StashBackpack.json does not parse]")
    automas, maaend, master = setup(BROKEN)
    changes, note = mastercfg.migrate_maaend_options(automas, maaend)
    require("StashBackpackMode is not deleted", "StashBackpackMode" in values(master), repr(values(master)))
    require("the migration refuses and names the file", not changes and "StashBackpack.json" in note, note)
    require("nothing else is rewritten either", "OldDeadKey" in values(master), repr(values(master)))

    print("[interface.json unreadable: the file list is a guess]")
    automas, maaend, master = setup(GOOD, interface="{broken")
    changes, note = mastercfg.migrate_maaend_options(automas, maaend)
    require("refuses when MaaEnd's own file list cannot be read",
            not changes and "interface.json" in note and "OldDeadKey" in values(master), note)

    print("[the AUTO-MAS instance, not just the first one (11-08 [D-08])]")
    from ark_relay.core import mastercfg as _mc
    _doc = {"instances": [{"id": "other", "tasks": [{"taskName": "T", "x": 1}]},
                          {"id": "automas", "tasks": [{"taskName": "T", "x": 2}]}]}
    require("picks id automas", (_mc._maaend_task(_doc, "T") or {}).get("x") == 2)
    require("no automas: the first",
            (_mc._maaend_task({"instances": [{"tasks": [{"taskName": "T", "x": 3}]}]}, "T") or {}).get("x") == 3)

    print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
    sys.exit(1 if FAILED else 0)


def _part_maaend_name_mismatch():
    """When AUTO-MAS cannot name a renamed MaaEnd task, the relay judges by MaaEnd's own log.

2026-09-06 05:40: MaaEnd v2.28.0-beta.1 relabelled SellProduct as 「据点交易」. The
run's log has 16 of 16 tasks 「任务完成」 and no 「任务失败」, and it ends after
「任务完成: 📅日常奖励领取」 with no closing task (no 关闭游戏 / 结束进程 line). AUTO-MAS
still recorded 「部分任务执行失败: SellProduct」 (its English fallback when it finds no
task file for the name, AUTO-MAS#573) and ran two retry rounds.

Every input here is a real machine record, read as it is:
  - the 09-06 05:40 record from the T9 corpus
    (gamesim/corpus/maaend/v3-0906-automas-misjudged/, U13b), whole and as a real prefix;
  - the 09-18 05:26 record (fixtures/maaend-2026-09-18/), a real 「任务失败」.
An earlier version of this test used a hand-typed 09-06 log with an invented
「⛔ 结束进程」 line the machine log does not have (grep -c 结束进程 = 0), so it passed
while the real run was booked failed (e539a57f).

    Formerly test_maaend_name_mismatch.py.
    """
    import json
    import pathlib
    import shutil

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

    HERE = pathlib.Path(__file__).resolve().parent
    REAL_0906 = (HERE / "gamesim" / "corpus" / "maaend" / "v3-0906-automas-misjudged" / "automas" / "history"
                 / "2026-09-06" / "endfield" / "MaaEnd-05-40-21")
    REAL_0918 = HERE / "fixtures" / "maaend-2026-09-18" / "MaaEnd-05-26-03"


    log_0906 = REAL_0906.with_suffix(".log").read_text(encoding="utf-8")
    lines_0906 = log_0906.splitlines(keepends=True)
    # What the test leans on, from the real file.
    assert "结束进程" not in log_0906 and "关闭游戏" not in log_0906, "the real 09-06 log has no closing task"
    assert log_0906.count("任务开始: ") == 16 and log_0906.count("任务完成: ") == 16 and "任务失败" not in log_0906
    CUT = next(i for i, ln in enumerate(lines_0906) if "任务开始: 🛒据点交易" in ln) + 1
    assert "任务完成: 🛒据点交易" not in "".join(lines_0906[:CUT])

    root = tmpdir()
    d = root / "2026-09-06" / "endfield"
    d.mkdir(parents=True)
    shutil.copy2(REAL_0906.with_suffix(".json"), d / "MaaEnd-05-40-21.json")
    shutil.copy2(REAL_0906.with_suffix(".log"), d / "MaaEnd-05-40-21.log")

    print("[09-06 05:40, the real record: 16/16 complete, no closing task, AUTO-MAS lists SellProduct]")
    rec = collector.parse_record(d / "MaaEnd-05-40-21.json", root)
    check("booked done", (rec.ok, rec.failed_tasks) if rec else None, (True, []))
    check("records the name AUTO-MAS could not look up", rec and rec.raw.get("maaend_name_mismatch"), ["SellProduct"])

    print("\n[the same real log cut where 据点交易 started: stuck mid-task]")
    (d / "MaaEnd-06-14-25.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: SellProduct"},
                                                       ensure_ascii=False), encoding="utf-8")
    (d / "MaaEnd-06-14-25.log").write_text("".join(lines_0906[:CUT]), encoding="utf-8")
    rec3 = collector.parse_record(d / "MaaEnd-06-14-25.json", root)
    check("a task started and never ended is not cleared", rec3.ok if rec3 else None, False)

    print("\n[the same real log, AUTO-MAS lists a display name that never started]")
    (d / "MaaEnd-06-20-00.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: ⚔️协议空间"},
                                                       ensure_ascii=False), encoding="utf-8")
    shutil.copy2(REAL_0906.with_suffix(".log"), d / "MaaEnd-06-20-00.log")
    rec5 = collector.parse_record(d / "MaaEnd-06-20-00.json", root)
    check("a listed task that never started keeps the failure (no closing task to show the round ended)",
          (rec5.ok, rec5.failed_tasks) if rec5 else None, (False, ["协议空间"]))

    print("\n[09-18 05:26, a real 「任务失败: 🎱基质刷取」]")
    d18 = root / "2026-09-18" / "endfield"
    d18.mkdir(parents=True)
    shutil.copy2(REAL_0918.with_suffix(".json"), d18 / "MaaEnd-05-26-03.json")
    shutil.copy2(REAL_0918.with_suffix(".log"), d18 / "MaaEnd-05-26-03.log")
    rec2 = collector.parse_record(d18 / "MaaEnd-05-26-03.json", root)
    check("a real failure stays a failure", (rec2.ok, rec2.failed_tasks) if rec2 else None, (False, ["基质刷取"]))

    # AUTO-MAS's own emulator-launch miss (2026-09-14 10:51:56, verbatim): a one-line
    # log, superseded one second later. Neither a failure nor a success.
    print("\n[AUTO-MAS's 模拟器启动失败 stub]")
    (d / "MaaEnd-06-51-56.json").write_text(json.dumps({"maaend_result": "[自动采集] 模拟器启动失败"}, ensure_ascii=False),
                                            encoding="utf-8")
    (d / "MaaEnd-06-51-56.log").write_text("模拟器启动失败, 无日志记录\n", encoding="utf-8")
    rec4 = collector.parse_record(d / "MaaEnd-06-51-56.json", root)
    check("transitional, no failure", (rec4.transitional, rec4.failed_tasks) if rec4 else None, (True, []))

    print("\n[re-judging the ledger only moves towards done]")
    old_entry = {"run_id": "2026-09-06/endfield/MaaEnd-05-40-21", "script": "MaaEnd", "ok": False,
                 "failed_tasks": ["SellProduct"], "raw": {}}
    fresh = collector.refresh_raw(old_entry, root)
    check("the 09-06 entry booked failed is re-judged done", (fresh.get("ok"), fresh.get("failed_tasks")), (True, []))
    old_bad = {"run_id": "2026-09-18/endfield/MaaEnd-05-26-03", "script": "MaaEnd", "ok": False,
               "failed_tasks": ["基质刷取"], "raw": {}}
    check("a real failure is not re-judged done", bool(collector.refresh_raw(old_bad, root).get("ok")), False)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_maaend_phone_page_beta5():
    """The phone page must show the per-region gathering lists MaaEnd v2.28.0-beta.5 uses.

On 2026-09-10 the relay had already rewritten the master for the new format, but
the page's whitelist still asked for the removed AutoCollectRoutes key, so the
gathering section showed only the schedule. The user: 「手机遥控器页面你也没修啊。
按照他新版本格式去修。」 This runs read_maaend over the real beta.5 definitions and
locale (fetched off the machine that day) with the migrated master, and requires
every new key to appear with a Chinese name, real choices and the picks kept.

    Formerly test_maaend_phone_page_beta5.py.
    """
    import re

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import mastercfg

    HAN = re.compile(r"[一-鿿]")


    FX = Path(__file__).resolve().parent / "fixtures" / "maaend-2026-09-10"
    root = tmpdir()
    automas = root / "AUTO-MAS"
    cf = automas / "data" / "x" / "Default" / "ConfigFile"
    cf.mkdir(parents=True)
    (cf / "mxu-MaaEnd.json").write_text((FX / "master-before.json").read_text(encoding="utf-8"),
                                        encoding="utf-8")
    mastercfg.migrate_maaend_options(automas, FX)
    r = mastercfg.read_maaend(automas, FX)
    A = "AutoCollect/"

    print("[新格式的每一项都在页上，而且都是中文名]")
    for opt in ("AutoCollectSchedule", "AutoCollectMode", "AutoCollectValleyIV",
                "AutoCollectValleyIVRareRoutes", "AutoCollectValleyIVCommonRoutes",
                "AutoCollectWuling", "AutoCollectWulingRareRoutes", "AutoCollectWulingCommonRoutes"):
        check(f"{opt} 有值", A + opt in r["values"], True)
        check(f"{opt} 有中文名", bool(HAN.search(r["labels"].get(A + opt) or "")), True)
    # Only this test's task: the fixture's 09-10 definitions predate what other shown tasks ask for.
    check("没有列进「没翻译」的", [k for k in r.get("untranslated") or [] if k.startswith(A)], [])
    check("旧的 AutoCollectRoutes 不再出现", A + "AutoCollectRoutes" in r["values"], False)

    print("\n[路线清单是可勾选的，名字带材料名，勾选保留原样]")
    check("四号谷地稀有路线的可选值", [v for _, v in r["options"][A + "AutoCollectValleyIVRareRoutes"]],
          ["Route4", "Route5", "Route6", "Route13", "Route14"])
    check("武陵稀有路线的可选值", [v for _, v in r["options"][A + "AutoCollectWulingRareRoutes"]],
          ["Route1", "Route2", "Route3", "Route7", "Route8", "Route9", "Route10", "Route11",
           "Route12", "Route15", "Route16", "Route17"])
    check("路线名写着材料", all("：" in l for l, _ in r["options"][A + "AutoCollectWulingRareRoutes"]), True)
    check("四号谷地勾的还是原来那几条", r["values"][A + "AutoCollectValleyIVRareRoutes"],
          ["Route4", "Route5", "Route6", "Route13", "Route14"])
    check("一般采集物没勾", r["values"][A + "AutoCollectWulingCommonRoutes"], [])
    check("地区开关是布尔", r["values"][A + "AutoCollectWuling"], True)
    check("采集模式有两档", [v for _, v in r["options"][A + "AutoCollectMode"]], ["Always", "TargetInventory"])
    check("采集模式当前是按勾选路线", r["values"][A + "AutoCollectMode"], "Always")

    print("\n[页上改了能写回去]")
    ok, msg = mastercfg.write_maaend(automas, FX, A + "AutoCollectWulingCommonRoutes", ["CommonRoute3"])
    check("勾一条一般路线", ok, True)
    check("回读是那一条", mastercfg.read_maaend(automas, FX)["values"][A + "AutoCollectWulingCommonRoutes"],
          ["CommonRoute3"])
    ok, msg = mastercfg.write_maaend(automas, FX, A + "AutoCollectMode", "TargetInventory")
    check("换采集模式", ok, True)
    ok, msg = mastercfg.write_maaend(automas, FX, A + "AutoCollectValleyIV", False)
    check("关掉一个地区", ok, True)
    check("回读关了", mastercfg.read_maaend(automas, FX)["values"][A + "AutoCollectValleyIV"], False)
    ok, msg = mastercfg.write_maaend(automas, FX, A + "AutoCollectWulingRareRoutes", ["Route99"])
    check("不存在的路线被拒", ok, False)


def _part_maaend_schedule_skip():
    """A task MaaEnd skips by its weekday schedule is reported as skipped, not done.

MaaEnd prints 「任务完成」 for it anyway. Real case: tests/replay/2026-09-05
MaaEnd-05-27-42.log lines 534-536 (自动采集 opened, then the line
「现在游戏时间是周六，根据执行周期跳过任务」 is printed in the log, and the task closed). The same 执行周期 checkbox sits on ProtocolSpace and AutoEssence
(tests/fixtures/maaend228/tasks/*.json), so the 协议空间 case below is those
three real lines with the task-start line of the real 09-27 协议空间 run
(fixtures/maaend-farm-drops/2026-09-27.log) - no real log of that skip exists yet.

    Formerly test_maaend_schedule_skip.py.
    """
    #!/usr/bin/env python3


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.verify.collector_maaend import parse_maaend_log

    FAILED: list[str] = []
    HERE = Path(__file__).resolve().parent


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
        if not ok:
            FAILED.append(name)


    def main() -> int:
        r = parse_maaend_log(HERE / "replay" / "2026-09-05" / "endfield" / "MaaEnd-05-27-42.log")
        require("skipped gathering is not listed as done", "自动采集" not in (r.get("tasks_done") or []),
                repr(r.get("tasks_done")))
        require("... it is listed as skipped with its weekday",
                (r.get("maaend_tasks_skipped") or {}).get("自动采集") == "周六", repr(r.get("maaend_tasks_skipped")))
        require("the old gathering key is kept", r.get("maaend_collect_skipped") == "周六",
                repr(r.get("maaend_collect_skipped")))

        ps = tmpdir() / "ps.log"
        ps.write_text("[2026-09-27 09:45:11.071] 任务开始: ⚔️协议空间\n"
                      "[2026-09-27 09:45:11.154] 现在游戏时间是周二，根据执行周期跳过任务\n"
                      "[2026-09-27 09:45:11.221] 任务完成: ⚔️协议空间\n", encoding="utf-8")
        p = parse_maaend_log(ps)
        require("skipped 协议空间 is not listed as done", "协议空间" not in (p.get("tasks_done") or []),
                repr(p.get("tasks_done")))
        require("... it is listed as skipped", (p.get("maaend_tasks_skipped") or {}).get("协议空间") == "周二",
                repr(p.get("maaend_tasks_skipped")))
        require("... and no 「刷 协议空间 ×0」 farming section", not p.get("maaend_farm"), repr(p.get("maaend_farm")))

        full = parse_maaend_log(HERE / "fixtures" / "maaend-farm-drops" / "2026-09-27.log")
        require("a run that really farmed is unchanged", full.get("maaend_farm") == "协议空间"
                and "协议空间" in (full.get("tasks_done") or []) and not full.get("maaend_tasks_skipped"),
                repr((full.get("maaend_farm"), full.get("maaend_tasks_skipped"))))
        print()
        if FAILED:
            print(f"FAILED {len(FAILED)}: {FAILED}")
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_maaend_skipped_report():
    """The daily report says a weekday-skipped MaaEnd task was skipped: not done,
not missing.

collector_maaend puts every task followed by 「现在游戏时间是周X，根据执行周期跳过任务」
into raw["maaend_tasks_skipped"] ({task: weekday}) and leaves it out of
tasks_done. The report (core._block_maaend, core.daily_footnote) has to read
that field: before, only 自动采集 had a sentence, so a skipped 协议空间 simply
vanished from the report - neither done nor said to be skipped.

The skip lines are the real ones from tests/replay/2026-09-05 MaaEnd-05-27-42.log
(lines 534-536) with the task-start line of the real 09-27 协议空间 run
(fixtures/maaend-farm-drops/2026-09-27.log); no real log of a skipped
协议空间 exists yet. The other lines are verbatim task lines of 2026-09-06.

    Formerly test_maaend_skipped_report.py.
    """
    #!/usr/bin/env python3

    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import ledger as core
    from ark_relay.features.verify.collector_maaend import parse_maaend_log
    from ark_relay.core.config import SERVER_TZ

    FAILED: list[str] = []
    HERE = Path(__file__).resolve().parent

    LOG = ("[2026-09-06 09:41:39.529] 任务开始: 🎁赠送干员礼物\n"
           "[2026-09-06 09:44:06.485] 任务完成: 🎁赠送干员礼物\n"
           "[2026-09-06 09:51:43.971] 任务开始: 🛒据点交易\n"
           "[2026-09-06 09:53:39.232] 任务完成: 🛒据点交易\n"
           "[2026-09-06 09:53:40.071] 任务开始: ⚔️协议空间\n"
           "[2026-09-06 09:53:40.154] 现在游戏时间是周二，根据执行周期跳过任务\n"
           "[2026-09-06 09:53:40.221] 任务完成: ⚔️协议空间\n"
           "[2026-09-06 09:53:41.000] 任务开始: 📅日常奖励领取\n"
           "[2026-09-06 09:55:00.000] 任务完成: 📅日常奖励领取\n")


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
        if not ok:
            FAILED.append(name)


    def ent(raw: dict) -> dict:
        st = datetime(2026, 9, 6, 9, 41, tzinfo=SERVER_TZ)
        return {"run_id": "2026-09-06/endfield/MaaEnd-05-40-21", "script": "MaaEnd", "user": "u", "ok": True,
                "started": st.isoformat(), "finished": (st + timedelta(minutes=14)).isoformat(),
                "duration_known": True, "transitional": False, "failed_tasks": [],
                "raw": raw, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}


    def main() -> int:
        p = tmpdir() / "MaaEnd-05-40-21.log"
        p.write_text(LOG, encoding="utf-8")
        raw = parse_maaend_log(p)
        require("parser: 协议空间 skipped on 周二", raw.get("maaend_tasks_skipped") == {"协议空间": "周二"},
                repr(raw.get("maaend_tasks_skipped")))

        # The three tasks that ran have a task-end picture each (cloud-alerts-1006:
        # done needs game evidence); the skipped one has none and is not listed anyway.
        raw = dict(raw, tasks_shot=["赠送干员礼物", "据点交易", "日常奖励领取"])
        _title, body = core.format_daily("2026-09-06", [ent(raw)])
        require("the report says it was skipped by schedule, with the weekday",
                "按排班跳过、没有做：协议空间（今天周二）" in body, body)
        require("... and does not list it as done or farmed",
                "做了 赠送干员礼物、据点交易、日常奖励领取" in body and "刷 协议空间" not in body, body)
        foot = core.daily_footnote([ent(raw)])
        require("the daily list does not count it", "协议空间" not in foot and "据点交易" in foot, foot)

        # 自动采集 keeps its own sentence, said once (not again in the generic one).
        gather = parse_maaend_log(HERE / "replay" / "2026-09-05" / "endfield" / "MaaEnd-05-27-42.log")
        _t3, b3 = core.format_daily("2026-09-05", [ent(gather)])
        require("a skipped 自动采集 keeps its own sentence", "自动采集 今天周六不是采集日" in b3, b3)
        require("... and is not repeated in the generic one", "按排班跳过、没有做：自动采集" not in b3, b3)
        print()
        if FAILED:
            print(f"FAILED {len(FAILED)}: {FAILED}")
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_maaend_write_readback():
    """write_maaend reads back the very item it wrote and compares it with what it wrote.

The old read-back went through read_maaend, which covers only the items the phone
page shows: a valid write of 自动囤货's reserve said 「'240000' → None」, and a file
that came back different from what was written still answered success.
Fixture: tests/fixtures/maaend-v2.32-autostock (upstream excerpt, see SOURCE.txt).

    Formerly test_maaend_write_readback.py.
    """
    #!/usr/bin/env python3

    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import mastercfg

    FX = Path(__file__).resolve().parent / "fixtures" / "maaend-v2.32-autostock"
    PATH = "AutoStockStaple/AutoStockReserveWuling"
    FAILED: list[str] = []


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
        if not ok:
            FAILED.append(name)


    def master() -> Path:
        automas = tmpdir() / "automas"
        cfg = automas / "data" / "sid" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        (cfg / "mxu-MaaEnd.json").write_text(json.dumps({"instances": [{"id": "automas", "tasks": [
            {"taskName": "AutoStockStaple", "enabled": True, "optionValues": {
                "AutoStockReserveWuling": {"type": "input", "values": {"ReserveWuling": "240000"}}}},
        ]}]}), encoding="utf-8")
        return automas


    # 1. A good write names the value it read back, not None.
    ok, msg = mastercfg.write_maaend(master(), FX, PATH, "240001")
    require("write 240001 succeeds", ok, msg)
    require("the answer shows the value read back", msg.endswith("'240000' → '240001'"), msg)

    # 2. The file comes back different from what was written: refused.
    real = mastercfg.atomic_write_text
    mastercfg.atomic_write_text = lambda path, text, **k: Path(path).write_text(
        text.replace('"240001"', '"240000"'), encoding="utf-8")
    try:
        ok, msg = mastercfg.write_maaend(master(), FX, PATH, "240001")
    finally:
        mastercfg.atomic_write_text = real
    require("a read-back that differs from the write is not a success", not ok, msg)

    # 3. The task switch still reads back too.
    automas = master()
    ok, msg = mastercfg.write_maaend(automas, FX, "AutoStockStaple/@enabled", False)
    require("switching the task off succeeds and says so", ok and msg.endswith("True → False"), msg)
    mastercfg.atomic_write_text = lambda path, text, **k: Path(path).write_text(
        text.replace('"enabled": false', '"enabled": true'), encoding="utf-8")
    try:
        ok, msg = mastercfg.write_maaend(master(), FX, "AutoStockStaple/@enabled", False)
    finally:
        mastercfg.atomic_write_text = real
    require("a task switch that reads back unchanged is not a success", not ok, msg)

    print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_maaend_controller_cache, _part_maaend_defs_228, _part_maaend_migrate_options, _part_maaend_migrate_stock_switch, _part_maaend_migrate_unread_defs, _part_maaend_name_mismatch, _part_maaend_phone_page_beta5, _part_maaend_schedule_skip, _part_maaend_skipped_report, _part_maaend_write_readback]))
