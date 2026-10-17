"""T11: every MaaEnd option the relay writes is one the installed MaaEnd defines,
and survives MXU's load unchanged.

Judged only against upstream (gamesim/upstream/, see gamesim/lib/maaend_schema.py):
MaaEnd's own definition files at the installed tag and the MXU source MXU@2.7.1
runs. MXU's load and run rules are ported from TypeScript; the ports are first
checked against MXU's own output on the machine (section A), so every later
verdict rests on a log line, not on the relay's code:

A  ports match the machine
   - MXU load warnings: master 09-10 under v2.28.0-beta.5 gives exactly the 39
     「已不存在，已丢弃保存值」 lines of fixtures/maaend-2026-09-10/app-2026-09-10-4.log;
     master 10-10 under v2.32.0 the 6 「类型已从 "checkbox" 变更为 "switch"」 lines
     of fixtures/maaend-2026-10-10/app-2026-10-10-3.log.
   - pipeline overrides: the same masters give byte-for-byte the
     `entry=..., pipelineOverride=[...]` lines MXU logged (AutoCollectSchedule
     09-10; AutoStockStapleSchedule and DailyRewardStart 10-10).
B  [ca3ba0d5] the relay's definition index holds every task MaaEnd declares and
   calls no task an orphan that MXU keeps (09-10: CreditShopping.json's
   `"enabled": false //...` hid CreditShoppingN2); [2367548d] MXU's own
   __MXU_*__ entries are never orphans.
C  [a210327f] the relay's index holds every option definition exactly as MaaEnd
   wrote it (the trailing-comma regex turned AutoStockStaple's `\\d{6,}` into
   `\\d{6}`, so a reserve of 12000000 was refused).
D  [258d7847] after the relay's boot migration the 09-10 master loads in MXU
   with no warning on its tasks (09-10: 36 「已丢弃保存值」, ran nothing);
   [85ac4eb8] nor on recentlyClosed (09-10 16:42: 33 「已不存在」);
   [76df1839] the 10-10 master under v2.32.0 loads clean and each 自动囤货 buy
   list is carried into its new switch + Items checkbox (10-03..10-10 bought
   the defaults). Both masters also migrate clean to the installed tag.
E  write_maaend round trip on the installed tag: every value MaaEnd declares for
   the sanity_sink tasks' options is accepted, read back equal, and kept by MXU
   unchanged; an undeclared case (RewardsSetA) is refused and the file untouched.
F  [8ed7f476] sanity_plan: its tab/line/location/reward tables name only cases
   the installed tag declares and cover every reward case; set_plan with each
   declared plan writes values MXU keeps and that the run actually reads
   (pipeline resolver); "RewardsSetA" never reaches the file.
G  prune, makeup, collect_retry and mastercfg's migration constants name only
   tasks, options, cases and pipeline nodes the installed tag defines.

Old code runs this file too (the red-before-green proofs): modules are imported
from where they lived then, and a missing function is reported as a failed case.
"""
from __future__ import annotations

import collections
import hashlib
import importlib
import inspect
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "gamesim" / "lib"))

import maaend_schema as ms  # noqa: E402
from _tmp import tmpdir  # noqa: E402

FX = HERE / "fixtures"
MASTER_0910 = FX / "maaend-2026-09-10" / "master-before.json"
MASTER_1010 = FX / "maaend-2026-10-10" / "master-before.json"
LOG_0910 = FX / "maaend-2026-09-10" / "app-2026-09-10-4.log"
LOG_1010 = FX / "maaend-2026-10-10" / "app-2026-10-10-3.log"
V0910, V1010 = "v2.28.0-beta.5", "v2.32.0"   # 「当前版本」 in those two logs

# sha256 of the MXU code each port follows (maaend_schema.PORTS), at MXU v2.7.1.
PORT_PINS = {
    "createDefaultOptionValue": "a7c8bfd416c6b440",
    "sanitizeOptionValue": "47b594f0e7643250",
    "sanitizeOptionValues": "f0b5807cf20204f9",
    "YES/NO case names": "7ddee5fa82636db2",
    "findSwitchCase": "b5c4547b383dcd57",
    "convertHotkeyKeyName": "a9a793fd7b67f095",
    "splitHotkeyCombo": "fb160ac4e67b01b4",
    "collectOptionOverrides": "fcd18f3f8f6cfc2c",
    "generateTaskPipelineOverride": "64daf60f1cd1289c",
    "mergeImported": "a68d7ccf80b72618",
    "cleanOptionValues": "48cff5c7c85660d8",
    "load: valid task names": "d4433f61ef5c09f9",
    "load: recentlyClosed": "b8c24ff83d9b53be",
    "cacheTaskEnabledForController": "b4ffde4802a1c9c4",
    "load: task flags": "568ec765bb15c733",
    "save: task flags": "ba3f8fc6aacf54df",
}

FAILED: list[str] = []


def require(name: str, ok: bool, detail: object = "") -> None:
    """`name` starts with its case in brackets, e.g. "[D 76df1839] ..."."""
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": {detail}"))
    if not ok:
        FAILED.append(name)


def _import(*names: str):
    for n in names:
        try:
            return importlib.import_module(n)
        except ImportError:
            continue
    return None


mastercfg = _import("ark_relay.core.mastercfg", "ark_relay.mastercfg")
sanity_plan = _import("ark_relay.features.weekly.sanity_plan", "ark_relay.sanity_plan")
collect_retry = _import("ark_relay.features.makeup.collect_retry", "ark_relay.collect_retry")
makeup = _import("ark_relay.features.makeup.makeup", "ark_relay.makeup")

# Each definition file is parsed once per content by the relay's own `_jsonc`
# and the result handed back on every later read of the same bytes. The relay
# reparses the whole install (5 MB) on each write_maaend call; without this the
# file would not fit gate 0's 10 s. The returned value is exactly what `_jsonc`
# returned for those bytes, and section B/C compare it with MaaEnd's files.
_REAL_JSONC = mastercfg._jsonc
_BY_CONTENT: dict[str, object] = {}
_PATH_KEY: dict[tuple, str] = {}


def _jsonc_once(path):
    st = Path(path).stat()
    pk = (str(path), st.st_mtime_ns, st.st_size)
    key = _PATH_KEY.get(pk)
    if key is None:
        key = _PATH_KEY[pk] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if key not in _BY_CONTENT:
        _BY_CONTENT[key] = _REAL_JSONC(path)
    return _BY_CONTENT[key]


mastercfg._jsonc = _jsonc_once


def defs_dir(version: str) -> Path:
    """A full install-shaped copy of a stored tag (the relay reads a directory)."""
    return ms.materialize(ms.UPSTREAM / f"maaend-{version}", tmpdir("gl-maaend-defs-"))


DIRS = {v: defs_dir(v) for v in (V0910, V1010, ms.INSTALLED)}
DEFS = {v: ms.Defs(d) for v, d in DIRS.items()}
INST = DEFS[ms.INSTALLED]


def workspace(master: "Path | dict") -> "tuple[Path, Path]":
    """(AUTO-MAS dir, master file) laid out as on the machine."""
    automas = tmpdir("gl-maaend-") / "automas"
    cfg = automas / "data" / "59da8762" / "Default" / "ConfigFile"
    cfg.mkdir(parents=True)
    f = cfg / "mxu-MaaEnd.json"
    doc = master if isinstance(master, dict) else json.loads(Path(master).read_text(encoding="utf-8"))
    f.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return automas, f


def load(f: Path) -> dict:
    return json.loads(f.read_text(encoding="utf-8"))


def task_of(doc: dict, name: str) -> dict:
    return next(t for t in doc["instances"][0]["tasks"] if t.get("taskName") == name)


def warnings(doc: dict, defs: ms.Defs, part: str = "all") -> list[str]:
    """MXU's load warnings for one part of the config: "instances",
    "recentlyClosed" or "all"."""
    keep = {"instances": ("instances",), "recentlyClosed": ("recentlyClosed",)}.get(
        part, ("instances", "recentlyClosed", "globalOptionValues"))
    return ms.mxu_load({k: v for k, v in doc.items() if k in keep or k not in
                        ("instances", "recentlyClosed", "globalOptionValues")}, defs)


def migrated(master: Path, version: str) -> "tuple[Path, Path, list]":
    """The master after the relay's boot migration against `version` (as is
    when this relay has no migration)."""
    automas, f = workspace(master)
    fn = getattr(mastercfg, "migrate_maaend_options", None)
    changes = fn(automas, DIRS[version])[0] if fn else []
    return automas, f, changes


def run(case: str, section) -> None:
    """Run one section; an exception (old code lacking a function) fails that case."""
    try:
        section()
    except Exception as exc:  # noqa: BLE001 - any error is this case's failure, reported
        require(f"[{case}] {section.__name__} ran", False, f"{type(exc).__name__}: {exc}")


print("[pins: the stored upstream files are unedited; MXU's ported code is unchanged]")
for d in sorted(ms.UPSTREAM.iterdir()):
    if d.is_dir() and d.name.startswith(("maaend-", "mxu-")):
        require(f"[pin] {d.name} matches its SOURCE.txt", not ms.verify(d), ms.verify(d)[:3])
require("[pin] the installed tag is stored", ms.INSTALLED_DIR.is_dir(), ms.INSTALLED_EVIDENCE)
for name, want in PORT_PINS.items():
    got = hashlib.sha256(ms.port_region(name).encode("utf-8")).hexdigest()[:16]
    require(f"[pin] MXU {name} unchanged", got == want, f"{got} != {want}: re-read the port")
for v, d in DEFS.items():
    require(f"[pin] {v}: no option or task declared twice", not d.dup_options and not d.dup_tasks,
          (d.dup_options, d.dup_tasks))


def ports_match_the_machine() -> None:
    print("[A: the MXU ports reproduce MXU's own log lines]")
    for master, log, v in ((MASTER_0910, LOG_0910, V0910), (MASTER_1010, LOG_1010, V1010)):
        got = collections.Counter(ms.mxu_load(json.loads(master.read_text(encoding="utf-8")), DEFS[v]))
        want = collections.Counter(ms.mxu_warnings(log.read_text(encoding="utf-8")))
        require(f"[A] {master.parent.name} under {v}: {sum(want.values())} load warnings as logged",
              got == want, (got - want, want - got))
    for master, log, v, entries in (
            (MASTER_0910, LOG_0910, V0910, ("AutoCollectSchedule",)),
            (MASTER_1010, LOG_1010, V1010, ("AutoStockStapleSchedule", "DailyRewardStart"))):
        doc = json.loads(master.read_text(encoding="utf-8"))
        inst = doc["instances"][0]
        logged = ms.logged_overrides(log.read_text(encoding="utf-8"))
        res = ms.Resolver(DEFS[v])
        for t in inst["tasks"]:
            entry = (DEFS[v].tasks.get(t.get("taskName")) or {}).get("entry")
            if entry in entries:
                got, _ = res.task(t, inst["controllerName"], inst["resourceName"], doc.get("globalOptionValues"))
                require(f"[A] {v} {entry}: pipeline override as MXU logged it", got == logged[entry],
                      f"{len(got)} vs {len(logged[entry])} parts")


def index_and_orphans() -> None:
    print("[B: the relay's definition index and orphan list match MaaEnd and MXU]")
    for v in (V0910, ms.INSTALLED):
        _opts, tasks = mastercfg._maaend_defs(DIRS[v])
        missing = sorted(set(DEFS[v].tasks) - set(tasks))
        require(f"[B ca3ba0d5] {v}: every task MaaEnd declares is indexed", not missing, missing)
    doc = json.loads(MASTER_0910.read_text(encoding="utf-8"))
    dropped = [w for w in ms.mxu_load(doc, DEFS[V0910]) if "无效任务" in w]
    automas, _ = workspace(MASTER_0910)
    orphans = mastercfg.read_maaend(automas, DIRS[V0910]).get("orphans") or []
    special = ms.special_task_names()
    require("[B 2367548d] no MXU built-in task is called an orphan",
          not [o for o in orphans if o in special], orphans)
    require("[B ca3ba0d5] orphans are exactly the tasks MXU drops (none on 09-10)",
          orphans == [] and dropped == [], (orphans, dropped))


def definitions_intact() -> None:
    print("[C: option definitions reach the relay exactly as MaaEnd wrote them]")
    for v in (V0910, ms.INSTALLED):
        opts, _ = mastercfg._maaend_defs(DIRS[v])
        bad = sorted(k for k, d in DEFS[v].options.items() if opts.get(k) != d)
        require(f"[C a210327f] {v}: all {len(DEFS[v].options)} option definitions identical", not bad, bad[:5])
    automas, f = migrated(MASTER_0910, ms.INSTALLED)[:2]
    box = INST.options["AutoStockReserveWuling"]["inputs"][0]
    for value in ("12000000", "240000", "1000", "abc"):
        want = bool(re.fullmatch(box["verify"], value))
        ok, why = mastercfg.write_maaend(automas, DIRS[ms.INSTALLED], "AutoStockStaple/AutoStockReserveWuling", value)
        require(f"[C a210327f] reserve {value}: written={ok}, MaaEnd's verify says {want}", ok == want, why)


def migration() -> None:
    print("[D: after the relay's migration MXU loads the master without a warning]")
    _, f, _ = migrated(MASTER_0910, V0910)
    doc = load(f)
    require(f"[D 258d7847] 09-10 master under {V0910}: tasks load clean",
          not warnings(doc, DEFS[V0910], "instances"), warnings(doc, DEFS[V0910], "instances")[:3])
    require(f"[D 85ac4eb8] 09-10 master under {V0910}: recentlyClosed loads clean",
          not warnings(doc, DEFS[V0910], "recentlyClosed"), len(warnings(doc, DEFS[V0910], "recentlyClosed")))
    old = task_of(json.loads(MASTER_1010.read_text(encoding="utf-8")), "AutoStockStaple")["optionValues"]
    lists = {k: v["caseNames"] for k, v in old.items() if v.get("type") == "checkbox"
             and DEFS[V1010].kind(k) == "switch"}
    _, f, _ = migrated(MASTER_1010, V1010)
    doc = load(f)
    require(f"[D 76df1839] 10-10 master under {V1010}: loads clean", not warnings(doc, DEFS[V1010]),
          warnings(doc, DEFS[V1010])[:3])
    inst = doc["instances"][0]
    _, reached = ms.Resolver(DEFS[V1010]).task(task_of(doc, "AutoStockStaple"), inst["controllerName"],
                                               inst["resourceName"], doc.get("globalOptionValues"))
    for key, picked in lists.items():
        on = reached.get(key) == {"type": "switch", "value": bool(picked)}
        items = (reached.get(key + "Items") or {}).get("caseNames") if picked else []
        require(f"[D 76df1839] {key}: run reads switch {'on' if picked else 'off'} and the {len(picked)} picks",
              on and items == picked, (reached.get(key), items))
    for master in (MASTER_0910, MASTER_1010):
        automas, f, _ = migrated(master, ms.INSTALLED)
        doc = load(f)
        require(f"[D] {master.parent.name} migrated to {ms.INSTALLED}: loads clean",
              not warnings(doc, INST), warnings(doc, INST)[:3])
        again = mastercfg.migrate_maaend_options(automas, DIRS[ms.INSTALLED])[0]
        require(f"[D] {master.parent.name}: a second migration changes nothing", again == [], again)


def _values(od: dict) -> list:
    """Every value MaaEnd declares for an option, in write_maaend's input shape."""
    kind = od.get("type") or "select"
    names = [str(c["name"]) for c in od.get("cases") or []]
    if kind == "select":
        return names
    if kind == "switch":
        return [True, False]
    if kind == "checkbox":
        return [[n] for n in names] + ([names] if len(names) > 1 else [])
    if kind == "input":
        boxes = od.get("inputs") or []
        if len(boxes) == 1:
            return [str(boxes[0].get("default") or "")]
        return [{b["name"]: str(b.get("default") or "") for b in boxes}]
    return []


def _shape(kind: str, value) -> dict:
    if kind == "select":
        return {"type": "select", "caseName": value}
    if kind == "switch":
        return {"type": "switch", "value": value}
    if kind == "checkbox":
        return {"type": "checkbox", "caseNames": value}
    return {"type": "input"}


def write_round_trip() -> None:
    print("[E: write_maaend round trip on the installed tag]")
    automas, f, _ = migrated(MASTER_0910, ms.INSTALLED)
    sinks = [n for n, t in INST.tasks.items() if "sanity_sink" in (t.get("group") or [])]
    tree = getattr(mastercfg, "MAAEND_TREE_TASKS", ())
    require("[E] the relay's tree tasks are MaaEnd's sanity_sink tasks", set(tree) <= set(sinks), (tree, sinks))
    last: dict = {}
    bad: list = []
    count = 0
    for task in sinks:
        for opt in sorted(ms.option_tree(INST, task) - set(INST.global_option)):
            od = INST.options.get(opt) or {}
            kind = od.get("type") or "select"
            for value in _values(od):
                ok, why = mastercfg.write_maaend(automas, DIRS[ms.INSTALLED], f"{task}/{opt}", value)
                count += 1
                entry = (task_of(load(f), task).get("optionValues") or {}).get(opt)
                problem = None if ok else why
                if ok and kind != "input" and entry != _shape(kind, value):
                    problem = f"read back {entry!r}"
                if ok and kind == "input":
                    want = value if isinstance(value, dict) else {(od.get("inputs") or [{}])[0].get("name"): value}
                    if {k: (entry or {}).get("values", {}).get(k) for k in want} != want:
                        problem = f"read back {entry!r}"
                if ok and not problem:
                    problem = ms.entry_check(INST, task, opt, entry)
                if problem:
                    bad.append((f"{task}/{opt}", value, problem))
                else:
                    last[f"{task}/{opt}"] = value
    require(f"[E] {count} declared values written, read back, kept by MXU", not bad, bad[:4])
    shown = mastercfg.read_maaend(automas, DIRS[ms.INSTALLED]).get("values") or {}
    differ = [k for k, v in last.items() if k in shown and shown[k] != v and not isinstance(v, dict)]
    require("[E] read_maaend shows the last value written", not differ, differ[:4])
    require("[E] nothing written makes MXU warn", not warnings(load(f), INST), warnings(load(f), INST)[:3])
    before = f.read_bytes()
    ok, why = mastercfg.write_maaend(automas, DIRS[ms.INSTALLED], "ProtocolSpace/OperatorEXPRewardsSetOption",
                                     "RewardsSetA")
    require("[E] an undeclared case (RewardsSetA) is refused, file untouched",
          not ok and f.read_bytes() == before, why)


def _set_plan(automas, tab, line, rset):
    kw = {}
    if "maaend_dir" in inspect.signature(sanity_plan.set_plan).parameters:
        kw["maaend_dir"] = DIRS[ms.INSTALLED]
    return sanity_plan.set_plan(automas, tab, line, rset, **kw)


def sanity_plan_writes() -> None:
    print("[F: sanity_plan names MaaEnd's cases and its writes take effect]")
    tabs = INST.cases("ProtocolSpaceTab")
    labels = getattr(sanity_plan, "TAB_LABELS", {})
    require("[F] every ProtocolSpace tab sanity_plan offers is a ProtocolSpaceTab case",
          set(labels) - {"Essence"} <= set(tabs), sorted(set(labels) - {"Essence"} - set(tabs)))
    lines = getattr(sanity_plan, "LINE_OPTIONS", {})
    wrong = sorted((t, x) for t, xs in lines.items() for x in xs if x not in INST.cases(t))
    require("[F] every line sanity_plan offers is a case of its tab", not wrong, wrong)
    locs = getattr(sanity_plan, "LOCATION_LABELS", {})
    require("[F] every essence location sanity_plan names is a case",
          set(locs) <= set(INST.cases("AutoEssenceChooseLocation")),
          sorted(set(locs) - set(INST.cases("AutoEssenceChooseLocation"))))
    declared = {(line, c) for t in tabs for line in INST.cases(t) for c in INST.cases(f"{line}RewardsSetOption")}
    table = set(getattr(sanity_plan, "REWARD", {}))
    require("[F 8ed7f476] the reward table holds exactly the declared (line, reward case) pairs",
          table == declared, (sorted(table - declared)[:4], sorted(declared - table)[:4]))
    automas, f, _ = migrated(MASTER_0910, ms.INSTALLED)
    res = ms.Resolver(INST)
    bad: list = []
    written = 0
    for tab in tabs:
        for line in INST.cases(tab):
            for rset in INST.cases(f"{line}RewardsSetOption") or [""]:
                ov = task_of(load(f), "ProtocolSpace").get("optionValues") or {}
                keys = ["ProtocolSpaceTab", tab] + ([f"{line}RewardsSetOption"] if rset else [])
                before = f.read_bytes()
                ok, why = _set_plan(automas, tab, line, rset)
                if not ok:
                    if all(k in ov for k in keys) or f.read_bytes() != before:
                        bad.append((tab, line, rset, why))
                    continue
                written += 1
                doc = load(f)
                inst = doc["instances"][0]
                _, reached = res.task(task_of(doc, "ProtocolSpace"), inst["controllerName"],
                                      inst["resourceName"], doc.get("globalOptionValues"))
                want = {"ProtocolSpaceTab": tab, tab: line} | ({f"{line}RewardsSetOption": rset} if rset else {})
                got = {k: (reached.get(k) or {}).get("caseName") for k in want}
                if got != want or warnings(doc, INST, "instances"):
                    bad.append((tab, line, rset, got, warnings(doc, INST, "instances")[:2]))
    require(f"[F 8ed7f476] set_plan with each declared plan writes what the run reads ({written} written)",
          written > 0 and not bad, bad[:3])
    _set_plan(automas, "OperatorProgression", "OperatorEXP", "RewardsSetA")
    require("[F 8ed7f476] set_plan(..., RewardsSetA) leaves nothing MXU rejects",
          not warnings(load(f), INST), warnings(load(f), INST)[:2])


def other_writers() -> None:
    print("[G: prune, makeup, collect_retry and mastercfg constants name what MaaEnd defines]")
    automas, f, _ = migrated(MASTER_0910, ms.INSTALLED)
    removed, _ = mastercfg.prune_maaend_orphans(automas, DIRS[ms.INSTALLED])
    dropped = [w for w in ms.mxu_load(load(f), INST) if "无效任务" in w]
    require("[G] prune removes exactly what MXU would drop (nothing)", removed == [] and not dropped,
          (removed, dropped))
    require(f"[G] makeup's {makeup.STASH} is a MaaEnd task", makeup.STASH in INST.tasks)
    entry_task = collect_retry.ENTRY.replace("Schedule", "")
    require(f"[G] collect_retry's {collect_retry.ENTRY} is {entry_task}'s entry",
          (INST.tasks.get(entry_task) or {}).get("entry") == collect_retry.ENTRY)
    routes = sorted(o for o in ms.option_tree(INST, entry_task) if collect_retry._ROUTE_OPT.match(o))
    require(f"[G] collect_retry's {len(routes)} route lists are checkboxes",
          bool(routes) and all(INST.kind(o) == "checkbox" for o in routes), routes)
    rids = sorted(set(collect_retry.failed_labels_from_locale(INST.zh).values()))
    logged = ms.logged_overrides(LOG_1010.read_text(encoding="utf-8"))[collect_retry.ENTRY]
    for v, nodes_of in ((V1010, logged), (ms.INSTALLED, logged)):
        built = collect_retry.build_override(nodes_of, rids, "monday")
        missing = sorted(ms.override_nodes(built) - DEFS[v].nodes)
        require(f"[G] {v}: retry override for all {len(rids)} routes names only pipeline nodes",
              bool(rids) and not missing, missing[:5])
    split = getattr(mastercfg, "_COLLECT_SPLIT", {})
    bad = [n for old, news in split.items() if old not in INST.options for n in news if INST.kind(n) != "checkbox"]
    require("[G] the gathering-split targets are checkboxes", not bad, bad)
    for opt, case in (("AutoCollectMode", "Always"), ("AutoEssenceMenu", "Random"),
                      ("AutoUseSpMedication", "UseMedication")):
        require(f"[G] migration's {opt}={case} is a declared case (when the option exists)",
              opt not in INST.options or case in INST.cases(opt), INST.cases(opt))


run("A", ports_match_the_machine)
run("B", index_and_orphans)
run("C", definitions_intact)
run("D", migration)
run("E", write_round_trip)
run("F", sanity_plan_writes)
run("G", other_writers)

opts_after, _ = mastercfg._maaend_defs(DIRS[ms.INSTALLED])
require("[pin] the parsed definitions were not changed by the code under test",
      opts_after == INST.options)

if FAILED:
    print(f"\n{len(FAILED)} failed:")
    for name in FAILED:
        print("  " + name)
    sys.exit(1)
print("\nall checks passed")
