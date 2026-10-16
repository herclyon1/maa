"""scripts/mac/lib/automas_contract_watch.py: a new AUTO-MAS release is compared with the settings
the relay reads before the game machine installs it.

AUTO-MAS v5.7.0-beta.3 was published 2026-10-13 07:23 UTC and installed on the machine 10-14
08:46 Beijing; it moved the MAA user's stage items from Info to Stage. With the relay's list as it
stood before masuser (every MAA user item in Info), the tool must name that move from the release's
app/models/config.py alone; with the current list (ark_relay/core/mascontract.py + masuser) it must
report nothing for v5.7.0-beta.4, and for v5.7.0-beta.3 and v5.7.0-beta.2 only the two MaaEnd
launcher settings beta.4 brought in (Game.LaunchMode, Game.LauncherPath; read since 10-16).

Fixtures (public upstream source): fixtures/automas-models/config.py.txt is v5.7.0-beta.2's whole
config.py (already used by test_mas_labels.py); config-v5.7.0-beta.3-excerpt.py.txt holds only the
ConfigItem statements of the listed settings from v5.7.0-beta.3, verbatim, under their classes;
config-v5.7.0-beta.4-excerpt.py.txt the same from v5.7.0-beta.4.
GitHub itself is not asked here (main() is given the file); the exit codes are checked on that path.
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts" / "mac" / "lib"))
sys.path.insert(0, str(HERE.parent))
from ark_relay.core import masuser  # noqa: E402 - after the sys.path lines above
try:
    import automas_contract_watch as w
    from ark_relay.core import mascontract
except ImportError:          # the code before this change
    w = mascontract = None

BETA2 = HERE / "fixtures" / "automas-models" / "config.py.txt"
BETA3 = HERE / "fixtures" / "automas-models" / "config-v5.7.0-beta.3-excerpt.py.txt"
BETA4 = HERE / "fixtures" / "automas-models" / "config-v5.7.0-beta.4-excerpt.py.txt"
# The two MaaEnd settings AUTO-MAS v5.7.0-beta.4 brought in (PR #1394, the launcher start);
# the relay reads them since 10-16 (efstart_setup), so an older release lacks them.
NEW_IN_BETA4 = ["MaaEndConfig Game.LaunchMode", "MaaEndConfig Game.LauncherPath"]
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


def run_main(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = w.main(list(argv))
    return code, buf.getvalue()


check("the tool and the relay's list exist", w is not None and mascontract is not None)
if w is not None and mascontract is not None:
    beta2, beta3 = w.parse(BETA2.read_text(encoding="utf-8")), w.parse(BETA3.read_text(encoding="utf-8"))
    beta4 = w.parse(BETA4.read_text(encoding="utf-8"))

    def named(gaps):
        return [g.split(":")[0] for g in gaps]
    # The list as it stood before masuser: the moved MAA user items read from Info only.
    before = [mascontract.Item(i.kind, i.level, "Info", i.key, i.use, i.source)
              if i.level == "user" and i.key in masuser.MOVED else i for i in mascontract.CONTRACT]

    print("[v5.7.0-beta.3 against the list before masuser: the 10-14 move is named]")
    gaps = w.compare(beta3, before)
    moved = sorted(g.split(":")[0] + " -> " + g.split("moved to ")[1].split(" (")[0]
                   for g in gaps if "moved to" in g)
    check("every MAA user item the relay read from Info is reported moved", moved, [
        "MaaUserConfig Info.Annihilation -> Task.Annihilation",
        "MaaUserConfig Info.MedicineNumb -> Stage.MedicineNumb",
        "MaaUserConfig Info.SeriesNumb -> Stage.SeriesNumb",
        "MaaUserConfig Info.Stage -> Stage.Stage",
        "MaaUserConfig Info.StageMode -> Stage.StageMode",
        "MaaUserConfig Info.Stage_1 -> Stage.Stage_1",
        "MaaUserConfig Info.Stage_2 -> Stage.Stage_2",
        "MaaUserConfig Info.Stage_3 -> Stage.Stage_3",
    ])
    check("nothing else is reported but the two settings beta.4 brought in",
          sorted(set(named(gaps)) - {m.split(" -> ")[0] for m in moved}), NEW_IN_BETA4)
    check("v5.7.0-beta.2 against that same list: only those two (it still kept the rest in Info)",
          named(w.compare(beta2, before)), NEW_IN_BETA4)

    print("\n[the current list (mascontract + masuser)]")
    check("v5.7.0-beta.4: nothing changed", w.compare(beta4, mascontract.CONTRACT, masuser.MOVED), [])
    check("v5.7.0-beta.3: only the two settings beta.4 brought in",
          named(w.compare(beta3, mascontract.CONTRACT, masuser.MOVED)), NEW_IN_BETA4)
    check("v5.7.0-beta.2: the same two", named(w.compare(beta2, mascontract.CONTRACT, masuser.MOVED)), NEW_IN_BETA4)

    print("\n[a key a release drops is reported, a whole class too]")
    fake = [mascontract.Item("MAA", "user", "Stage", "NoSuchKey", "stage", "x.py:f"),
            mascontract.Item("plan", "plan", "Info", "Mode", "plan_table", "x.py:f")]
    no_plan = {k: v for k, v in beta3.items() if k != "MaaPlanConfig"}
    out = w.compare(no_plan, fake, masuser.MOVED)
    check("a dropped key", any(g.startswith("MaaUserConfig Stage.NoSuchKey: no longer defined") for g in out))
    check("a dropped class", any(g.startswith("MaaPlanConfig Info.Mode: class MaaPlanConfig is gone") for g in out))

    print("\n[parsing: helpers called with self, f-string keys, loop rows]")
    check("MaaEnd's helper items count for MaaEndUserConfig",
          ("Task", "SanityTaskType") in beta3["MaaEndUserConfig"])
    check("f\"If{task}\" becomes the pattern If*", ("Task", "If*") in beta3["MaaEndUserConfig"])
    check("legacy_group is read", beta3["MaaUserConfig"][("Stage", "Stage")], ("Info", "Stage"))

    print("\n[exit codes]")
    code, text = run_main("--file", str(BETA4))
    check("nothing changed: exit 0", code, 0)
    orig = mascontract.CONTRACT
    mascontract.CONTRACT = tuple(before)
    try:
        code, text = run_main("--file", str(BETA4))
    finally:
        mascontract.CONTRACT = orig
    check("something changed: exit 2", code, 2)
    check("and it is printed", "Info.Stage: moved to Stage.Stage" in text)
    real_http = w._http
    w._gh = lambda path: None

    def offline(url):
        raise w.urllib.error.URLError("offline")
    w._http = offline
    try:
        code, text = run_main()
    finally:
        w._http = real_http
    check("GitHub cannot be read: exit 3", code, 3)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
