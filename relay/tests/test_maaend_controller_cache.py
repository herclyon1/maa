#!/usr/bin/env python3
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
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "gamesim" / "lib"))

import maaend_schema as ms  # noqa: E402
from _tmp import tmpdir  # noqa: E402
from ark_relay.core import mastercfg  # noqa: E402
from ark_relay.features.makeup import makeup  # noqa: E402
from ark_relay.features.weekly import sanity_plan  # noqa: E402

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
