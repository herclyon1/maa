"""Every OK-WW config value the relay writes is one upstream defines, keeps at load and reads (gamesim T12).

The relay writes OK-WW's config files from four places: the phone page
(mastercfg_okww.write_okww, DailyTask.json), the weekly boss and weekly garden
switches (weeklyboss / garden enforce, DailyTask.json + FarmEchoTask.json in the
AUTO-MAS master) and the echo farm (echofarm.start, the working FarmEchoTask.json).
Each of them runs here for real, into a tree shaped like the machine's whose files
hold what ok-script itself writes when there is none (the task's default_config).
The result is then judged by upstream, read from the copies fetched by tag
(relay/tests/gamesim/upstream/: OK-WW v3.7.4, ok-script 2.0.8):

  - ok-script's own Config.verify_config keeps every written key with the written
    value (an unknown key is dropped and a wrong type is reset at load: PITFALLS
    2026-09-10, the nest filter that farmed all four nests 09-10..09-13);
  - the value is one of the drop-down / multi-selection options upstream lists, and a
    serial is within the list upstream clicks through (total_weekly_number,
    total_boss_number, the Tacet / Forgery structure sums);
  - upstream reads the key, and a key written for a mode ('Teleport to Boss') is read
    on that mode's path, with the overlay installed (10-13 11:31-11:45: Boss Level 80
    written for Boss Challenge, fought at Lv.90 every lap; 35d6166b);
  - the cross-file rules upstream raises on before login hold (DailyTask.
    validate_additional_tasks, DailyTask.py:138-156; 08b71251);
  - a key the overlay reads that upstream does not define comes from the AUTO-MAS
    master, never from the loaded config it was dropped from (85ca8649).

    relay-python tests/test_gl_okww_config.py              # every case
    relay-python tests/test_gl_okww_config.py echofarm     # some cases (names below)
"""
import ast
import importlib
import inspect
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "gamesim" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "gamesim" / "tools"))
import fetch_upstream as fu
from _tmp import tmpdir
from okww_schema import ModeReads, Schema, read_sites

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


# OK-WW on the game PC: v3.7.4 (「ok-script init v3.7.4」, app.2026-10-13 line 517; see
# test_gl_okww_contract.py). Its requirements.txt pins the ok-script it runs on (line 26).
OKWW = "v3.7.4"
OKSCRIPT = "2.0.8"
SCHEMA = Schema(OKWW, OKSCRIPT)
FARM, DAILY, NEST = (SCHEMA.task(c) for c in ("FarmEchoTask", "DailyTask", "NightmareNestTask"))
TACET, FORGERY = SCHEMA.task("TacetTask"), SCHEMA.task("ForgeryTask")
# The relay's server clock is UTC+8 (config.SERVER_TZ); 2026-10-12 is a Monday after the
# 04:00 weekly reset, so both weekly switches want their task listed.
MONDAY = datetime(2026, 10, 12, 10, 0, tzinfo=timezone(timedelta(hours=8)))

# The serials upstream clicks through a list of a fixed length (click_on_book_target(serial,
# total_number, ...)): a serial past the end lands on another entry or none.
SERIAL_LIMIT = {
    ("FarmEchoTask", "Which Weekly Boss to Teleport"): FARM.attrs.get("total_weekly_number"),
    ("FarmEchoTask", "Which Boss Challenge to Teleport"): FARM.attrs.get("total_boss_number"),
    ("DailyTask", "Which Tacet Suppression to Farm"): TACET.attrs.get("total_number"),
    ("DailyTask", "Which Forgery Challenge to Farm"): FORGERY.attrs.get("total_number"),
}
# Settings whose meaning depends on a mode setting of the same file: upstream's own
# sub_configs (FarmEchoTask.py:44-50: Boss Level and the serial under each teleport target).
MODE_KEY = {"FarmEchoTask": "Teleport to Boss"}

# Known violations not fixed yet, each with where the fix belongs. The check below passes
# only while the violations found are exactly these: a new one, or one of these fixed,
# fails until this table is updated.
OPEN = {
    "echofarm.start: FarmEchoTask/Which Boss Challenge to Teleport accepts 21..30, upstream "
    "lists 20 (FarmEchoTask.py:64 total_boss_number = 20)":
        "echofarm.start bounds the boss to 1..30 (echofarm.py, `if not 1 <= boss <= 30`); "
        "the bound should be upstream's total_boss_number - an edit to an existing file, "
        "reported to the main session by gamesim U10 (2026-10-13)",
}


def _mod(*names):
    """The first of these modules that imports (the relay was split into packages on 10-10)."""
    for name in names:
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError:
            continue
    raise ModuleNotFoundError(names[0])


# ── a machine-shaped tree ───────────────────────────────────────────────────────
TASKS = {"FarmEchoTask": FARM, "DailyTask": DAILY, "NightmareNestTask": NEST}


_SRC = {}


class Machine:
    """D:/ark/okww (the working dir OK-WW runs from: app.2026-10-13 line 517) and AUTO-MAS's
    master ConfigFile (config.master_config_dir), every task file holding its defaults -
    what ok-script's Config writes when there is no file (ok/util/config.py reset_to_default).
    The upstream source under working/ is one shared, read-only copy."""

    def __init__(self):
        if "dir" not in _SRC:
            _SRC["dir"] = fu.materialize(SCHEMA.okww, tmpdir())
        root = tmpdir()
        self.okww = root / "okww"
        self.working = self.okww / "data" / "apps" / "ok-ww" / "working"
        self.working.mkdir(parents=True)
        for entry in _SRC["dir"].iterdir():
            (self.working / entry.name).symlink_to(entry)
        self.automas = root / "automas"
        self.master = self.automas / "data" / "sid" / "Default" / "ConfigFile"
        self.state = root / "state"
        self.state.mkdir()
        for d in (self.working / "configs", self.master):
            d.mkdir(parents=True, exist_ok=True)
            for name, task in TASKS.items():
                (d / f"{name}.json").write_text(json.dumps(task.defaults, ensure_ascii=False), encoding="utf-8")

    def doc(self, where, name):
        return json.loads((where / f"{name}.json").read_text(encoding="utf-8"))


def judge(task_name, doc, written, who):
    """Problems with `written` (key -> value) as found in `doc`, the file after the write."""
    task = TASKS[task_name]
    kept, _changed = SCHEMA.verify(task.defaults, doc)
    out = []
    for key, value in written.items():
        where = f"{who}: {task_name}/{key}={value!r}"
        if key not in task.defaults:
            out.append(f"{where}: upstream {task_name} has no such setting (dropped at load)")
            continue
        if kept.get(key) != value:
            out.append(f"{where}: ok-script keeps {kept.get(key)!r} at load")
        kind = task.types.get(key) or {}
        opts = kind.get("options") if isinstance(kind, dict) else None
        if kind.get("type") == "drop_down" and value not in (opts or []):
            out.append(f"{where}: not one of upstream's options {opts}")
        if kind.get("type") == "multi_selection" and not set(value or []) <= set(opts or []):
            out.append(f"{where}: {sorted(set(value) - set(opts or []))} not among upstream's options")
        top = SERIAL_LIMIT.get((task_name, key))
        if top is not None and not (isinstance(value, int) and 1 <= value <= top):
            out.append(f"{who}: {task_name}/{key} accepts {value}, upstream lists {top}")
        if not SCHEMA.reads(key):
            out.append(f"{where}: upstream never reads it")
        mode_key = MODE_KEY.get(task_name)
        mode = written.get(mode_key, doc.get(mode_key)) if mode_key else None
        subs = ((task.types.get(mode_key) or {}).get("sub_configs") or {}).get(mode, []) if mode else []
        if key in subs and not mode_reads(task_name).read_under(key, mode):
            out.append(f"{where}: nothing reads it when {mode_key} is {mode!r}")
    return out


_MODE_READS = {}


def mode_reads(task_name):
    if task_name not in _MODE_READS:
        _MODE_READS[task_name] = ModeReads(SCHEMA, task_name, overlay_text(strict=False))
    return _MODE_READS[task_name]


def changed(before, after):
    """The keys a whole-file writer set: those whose value differs from before the write."""
    return {k: v for k, v in after.items() if before.get(k, object()) != v}


def cross_file(daily, farm, nest):
    """Upstream DailyTask.validate_additional_tasks (DailyTask.py:138-156): the daily raises
    before login on a listed task whose other file says it cannot run."""
    out = []
    listed = daily.get("Additional Tasks to Run After Daily Task") or []
    if "Teleport and Farm 4C Echo" in listed and farm.get("Teleport to Boss", "No") == "No":
        out.append("Teleport and Farm 4C Echo listed while FarmEchoTask's Teleport to Boss is No")
    if "Auto Farm all Nightmare Nest" in listed and not nest.get("Which to Farm"):
        out.append("Auto Farm all Nightmare Nest listed while NightmareNestTask's Which to Farm is empty")
    return out


_OVERLAY = {}


def overlay_text(strict=True):
    """The overrides file OK-WW runs with. Not strict: '' for a relay that had none (before
    09-09 the changes were text patches, okww_patches), where upstream's paths are all there is."""
    if "text" not in _OVERLAY:
        try:
            ov = _mod("ark_relay.features.okww_patch.okww_overlay", "ark_relay.okww_overlay")
        except ModuleNotFoundError:
            if strict:
                raise
            return ""
        _OVERLAY["text"] = ov.source_text()
    return _OVERLAY["text"]


# ── cases ───────────────────────────────────────────────────────────────────────
def case_reader():
    """The schema reader against the upstream lines it reads (FarmEchoTask.py etc., v3.7.4)."""
    print("\n[the schema reader reproduces upstream's own lines]")
    check("FarmEchoTask.py:24 'Boss Level': \"80\"", FARM.defaults.get("Boss Level"), "80")
    check("FarmEchoTask.py:51 Boss Level options", FARM.types["Boss Level"]["options"], ["50", "60", "70", "80", "90"])
    check("FarmEchoTask.py:41-42 Teleport to Boss options", FARM.types["Teleport to Boss"]["options"],
          ["No", "Weekly Challenge", "Boss Challenge", "Special Nightmare"])
    check("FarmEchoTask.py:63-64 total_weekly_number 9, total_boss_number 20",
          (FARM.attrs.get("total_weekly_number"), FARM.attrs.get("total_boss_number")), (9, 20))
    check("FarmEchoTask.py:25 'Repeat Farm Count': 10000", FARM.defaults.get("Repeat Farm Count"), 10000)
    check("ok-script task.py:1154 add_exit_after_config adds Exit After Task", FARM.defaults.get("Exit After Task"), False)
    check("DailyTask.py:32 'Which to Farm' defaults to support_tasks[0]", DAILY.defaults.get("Which to Farm"),
          "Tacet Suppression")
    check("DailyTask.py:64-72 Additional Tasks options", DAILY.types["Additional Tasks to Run After Daily Task"]["options"],
          ["Check Weekly Garden", "Auto Farm all Nightmare Nest", "Merge Echo If discarded > 1000",
           "Teleport and Farm 4C Echo"])
    check("TacetTask.py:18-19 total 4+5+5+7", TACET.attrs.get("total_number"), 21)
    check("ForgeryTask.py:23-24 total 5+5+5+5", FORGERY.attrs.get("total_number"), 20)
    check("NightmareNestTask.py:25 and :38 replace, then extend, default_config",
          NEST.defaults, {"_enabled": True, "Which to Farm": ["Nightmare Purification", "Tacet Discord Nest"]})
    for t in (FARM, DAILY, NEST, TACET, FORGERY):
        check(f"{t.name}: every config statement of its __init__ chain evaluated", t.skipped, [])
        # verify() runs without a validator: BaseTask.validate asks validate_config, whose
        # ok-script body is `pass` (task.py:1340-1341); an override would change that.
        owner = SCHEMA.method(t.name, "validate_config")
        check(f"{t.name}: validate_config is ok-script's own", owner[0] if owner else None, "BaseTask")
    req = fu.read_files(SCHEMA.okww)["requirements.txt"].decode("utf-8")
    check(f"OK-WW {OKWW} runs on ok-script {OKSCRIPT} (requirements.txt)",
          f"ok-script[ocr,qt]=={OKSCRIPT}" in req.splitlines(), True)


def case_loader():
    """ok-script's own loader, as PITFALLS 2026-09-10 describes it."""
    print("\n[ok-script's Config.verify_config, run from the fetched copy]")
    kept, changed = SCHEMA.verify(NEST.defaults, dict(NEST.defaults, **{"Only Farm These Nests": "落渊南丘"}))
    check("a key upstream does not define is dropped at load", "Only Farm These Nests" in kept, False)
    check("…and the file is rewritten", changed, True)
    kept, _ = SCHEMA.verify(FARM.defaults, dict(FARM.defaults, **{"Boss Level": 80}))
    check("a value of another type is put back to the default", kept["Boss Level"], "80")
    kept, changed = SCHEMA.verify(FARM.defaults, dict(FARM.defaults, **{"Boss Level": "90"}))
    check("a right value is kept, file untouched", (kept["Boss Level"], changed), ("90", False))


def case_mastercfg():
    """The phone page's OK-WW writes (mastercfg_okww.write_okww; 0a69e862, a3bf4e82)."""
    print("\n[phone page -> master DailyTask.json]")
    m = _mod("ark_relay.core.mastercfg_okww", "ark_relay.mastercfg_okww")
    takes_dir = "okww_dir" in inspect.signature(m.write_okww).parameters
    problems, refused_valid = [], []
    for key in m.OKWW_SHOWN["DailyTask.json"]:
        default = DAILY.defaults[key]
        if isinstance(default, int):
            domain = list(range(-1, 41))
        else:
            domain = list((DAILY.types.get(key) or {}).get("options") or []) + ["Bogus", ""]
        for value in domain:
            mc = Machine()
            kw = {"okww_dir": mc.okww} if takes_dir else {}
            ok, _why = m.write_okww(mc.automas, f"DailyTask.json/{key}", value, **kw)
            if ok:
                problems += judge("DailyTask", mc.doc(mc.master, "DailyTask"), {key: value}, "write_okww")
            elif value in ((DAILY.types.get(key) or {}).get("options") or []):
                refused_valid.append(f"{key}={value!r}")
    serial = [p for p in problems if "upstream lists" in p]
    check("every drop-down value write_okww accepts is one upstream keeps, lists and reads",
          [p for p in problems if p not in serial], [])
    check("every serial write_okww accepts is within upstream's list (a3bf4e82)", serial, [])
    check("no option upstream lists is refused", refused_valid, [])


def case_weekly():
    """The weekly boss switch (weeklyboss.enforce; 08b71251)."""
    print("\n[weekly boss switch -> master DailyTask.json + FarmEchoTask.json]")
    W = _mod("ark_relay.features.weekly.weeklyboss", "ark_relay.weeklyboss")
    problems, accepted = [], []
    os.environ["ARK_OKWW_LOG"] = str(tmpdir() / "ok.log")
    for index in range(0, 12):
        mc = Machine()
        g = W.WeeklyBossGate(mc.state, mc.automas)
        ok, _why = g.configure(index=index)
        if not ok:
            continue
        accepted.append(index)
        g.enforce(MONDAY)
        daily, farm = mc.doc(mc.master, "DailyTask"), mc.doc(mc.master, "FarmEchoTask")
        problems += judge("FarmEchoTask", farm, changed(FARM.defaults, farm), "weeklyboss")
        problems += judge("DailyTask", daily, changed(DAILY.defaults, daily), "weeklyboss")
        problems += cross_file(daily, farm, mc.doc(mc.master, "NightmareNestTask"))
    check("configure takes exactly upstream's weekly list (1..total_weekly_number)",
          accepted, list(range(1, FARM.attrs["total_weekly_number"] + 1)))
    check("every value enforce writes is one upstream keeps, lists and reads; no cross-file break", problems, [])
    # 08b71251: the master FarmEchoTask.json unreadable (a torn write) while the switch is on.
    mc = Machine()
    (mc.master / "FarmEchoTask.json").write_text("{ torn", encoding="utf-8")
    g = W.WeeklyBossGate(mc.state, mc.automas)
    g.configure(index=1)
    g.enforce(MONDAY)
    check("FarmEchoTask.json unreadable: the daily is not left to raise before login",
          cross_file(mc.doc(mc.master, "DailyTask"), {}, mc.doc(mc.master, "NightmareNestTask")), [])


def case_garden():
    """The weekly garden switch (garden.enforce)."""
    print("\n[weekly garden switch -> master DailyTask.json]")
    G = _mod("ark_relay.features.weekly.garden", "ark_relay.garden")
    mc = Machine()
    daily = mc.doc(mc.master, "DailyTask")
    daily["Additional Tasks to Run After Daily Task"] = []
    (mc.master / "DailyTask.json").write_text(json.dumps(daily), encoding="utf-8")
    G.GardenGate(mc.state, mc.automas).enforce(MONDAY)
    daily = mc.doc(mc.master, "DailyTask")
    check("the garden is listed", "Check Weekly Garden" in daily["Additional Tasks to Run After Daily Task"], True)
    check("…as a value upstream keeps, lists and reads", judge(
        "DailyTask", daily, {"Additional Tasks to Run After Daily Task":
                             daily["Additional Tasks to Run After Daily Task"]}, "garden"), [])


def case_echofarm():
    """The echo farm (echofarm.start; 21dac430, 35d6166b)."""
    print("\n[echo farm -> working configs/FarmEchoTask.json, the file OK-WW loads]")
    E = _mod("ark_relay.features.echofarm.echofarm", "ark_relay.echofarm")
    E._launch = lambda: (True, "")
    E.NO_CLAIM = str(tmpdir() / "no-claim")
    problems, accepted, writes = [], [], []
    real_write = E._write_cfg
    # What start sets is what it hands to _write_cfg (a key it sets to the value already
    # there, Boss Level "80" over upstream's default "80", is still its write).
    E._write_cfg = lambda path, values: (writes.append(dict(values)), real_write(path, values))[1]

    class Cfg:
        pass

    for boss in range(0, 32):
        mc = Machine()
        cfg = Cfg()
        cfg.okww_dir, cfg.state_dir, cfg.automas_dir = mc.okww, mc.state, mc.automas
        writes.clear()
        ok, _why = E.start(cfg, boss, "08:30")
        if not ok:
            continue
        accepted.append(boss)
        farm = mc.doc(mc.working / "configs", "FarmEchoTask")
        for values in writes:
            problems += judge("FarmEchoTask", farm, values, "echofarm.start")
    E._write_cfg = real_write
    check("start farms boss 1 in a machine-shaped tree", 1 in accepted, True)
    found = sorted(set(problems))
    over = [p for p in found if "Which Boss Challenge to Teleport accepts" in p]
    unread = [p for p in found if "nothing reads it when" in p]
    rest = [p for p in found if p not in over and p not in unread]
    nums = sorted(int(p.split("accepts ")[1].split(",")[0]) for p in over)
    if nums:
        found_open = [f"echofarm.start: FarmEchoTask/Which Boss Challenge to Teleport accepts "
                      f"{nums[0]}..{nums[-1]}, upstream lists {FARM.attrs['total_boss_number']} "
                      "(FarmEchoTask.py:64 total_boss_number = 20)"]
    else:
        found_open = []
    for p in found_open:
        print(f"  ! OPEN {p}\n         fix: {OPEN.get(p, 'not in the OPEN table')}")
    check("every setting start writes for its teleport target is read on that target's path (35d6166b)",
          unread, [])
    check("every other value start writes is one upstream keeps, lists and reads", rest, [])
    check("the known open violations are exactly OPEN", sorted(found_open), sorted(OPEN))


def case_overlay():
    """Keys the overlay reads from a loaded config (85ca8649)."""
    print("\n[every key the overlay reads survives the load, or comes from the master]")
    text = overlay_text()
    tree = ast.parse(text)
    consts = {n.targets[0].id: n.value.value for n in tree.body
              if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
              and isinstance(n.value, ast.Constant)}
    defined = set().union(*(SCHEMA.task(c).defaults for c in (
        "FarmEchoTask", "DailyTask", "NightmareNestTask", "TacetTask", "ForgeryTask", "SimulationTask")))
    funcs = {f.name: f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)}

    def gets(node):
        """Keys read with .get(KEY) from anything that is not a task config."""
        out = set()
        for c in ast.walk(node):
            if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "get" and c.args
                    and not (isinstance(c.func.value, ast.Attribute) and c.func.value.attr == "config")):
                a = c.args[0]
                k = a.value if isinstance(a, ast.Constant) else consts.get(getattr(a, "id", ""))
                if isinstance(k, str):
                    out.add(k)
        return out

    from_master = set()
    for f in funcs.values():
        if any(isinstance(n, ast.Name) and n.id == "MASTER_POINTER" for n in ast.walk(f)):
            from_master |= gets(f)
            for c in ast.walk(f):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in funcs:
                    from_master |= gets(funcs[c.func.id])
    loose = sorted({f"{r.key} (overlay line {r.line})" for r in read_sites(tree, consts, "overlay")
                    if r.key not in defined and r.key not in from_master})
    check("no overlay read depends on a key ok-script drops at load", loose, [])


CASES = {"reader": case_reader, "loader": case_loader, "mastercfg": case_mastercfg, "weekly": case_weekly,
         "garden": case_garden, "echofarm": case_echofarm, "overlay": case_overlay}


def main():
    wanted = sys.argv[1:] or list(CASES)
    for name in wanted:
        CASES[name]()
    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
