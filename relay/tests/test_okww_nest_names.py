"""「Only these nests」: the cap rule and the overlay's nest names, both must pass.

outcome.nest_filter_checks told nests apart by the denominator of 「已击败残象 N/D」
(more different caps than names asked for = a nest outside the setting). The
overlay now logs 「nightmare nest: nest name: <name>」 for each nest it enters, just
before the count box is clicked (「?」 when no name was read). With the filter on,
the overlay only clicks a row beside a wanted name and logs that name, so the names
alone never go red; 5352dfd8 let them replace the cap rule, which is what catches a
click on the neighbouring row (review 2026-10-13, item 17). Now both run: the cap
rule over every click, named or 「?」, and per wanted name no two different caps.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify import outcome

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


T = "2026-10-14 09:00:{:02d},000 INFO TaskExecutor NightmareNestTask:{}"


def lines(*events, only="落渊南丘"):
    out = [T.format(0, f"nightmare nest: 只刷 {[n for n in only.split(',')]}")]
    for i, (kind, val) in enumerate(events, 1):
        out.append(T.format(i, f"left_click 已击败残象：0/{val} (1729, 347) after_sleep 2" if kind == "click"
                            else f"nightmare nest: nest name: {val}"))
    out.append(T.format(59, "enter combat None"))          # a fight, so the scope item is said
    return "\n".join(out) + "\n"


def scope(text, only):
    return [(c.ok, c.detail) for c in outcome.nest_filter_checks(text, only) if c.label == "残象聚落没进别的点位"]


print("[review case: two clicks both logged 落渊南丘, caps 48 and 41 -> red]")
text = lines(("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41), ("name", "落渊南丘残象聚落"))
got = scope(text, "落渊南丘")
check("red", [ok for ok, _ in got], [False])
check("says the two caps", "48、41" in (got[0][1] if got else ""), True)

print("\n[real order (name, then click), both wanted nests: green]")
text = lines(("name", "梦枢天罗残象聚落"), ("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41),
             only="梦枢天罗,落渊南丘")
check("green", [ok for ok, _ in scope(text, "梦枢天罗,落渊南丘")], [True])
check("each click gets the name logged before it", outcome._nest_clicks(text),
      [("48", "梦枢天罗残象聚落"), ("41", "落渊南丘残象聚落")])

print("\n[two wanted nests, a third click on the neighbouring 48 row under 落渊南丘's name: red]")
text = lines(("name", "梦枢天罗残象聚落"), ("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41),
             ("name", "落渊南丘残象聚落"), ("click", 48), only="梦枢天罗,落渊南丘")
got = scope(text, "梦枢天罗,落渊南丘")
check("red although only two caps in all", [ok for ok, _ in got], [False])
check("names the name with two caps", "「落渊南丘」" in (got[0][1] if got else ""), True)

print("\n[a 「?」 click still counts for the cap rule]")
text = lines(("name", "落渊南丘残象聚落"), ("click", 41), ("name", "?"), ("click", 48))
check("named 41 + unnamed 48 for one wanted name: red", [ok for ok, _ in scope(text, "落渊南丘")], [False])

print("\n[old logs without name lines: the cap rule as before]")
text = lines(("click", 48), ("click", 48))
check("same cap twice: green", [ok for ok, _ in scope(text, "落渊南丘")], [True])
text = lines(("click", 48), ("click", 41))
check("two caps for one name: red", [ok for ok, _ in scope(text, "落渊南丘")], [False])

print("\n[the Mac-side checkers pass the configured names, not a literal (10-15, alarm f7a4bb6a)]")
# okww_effective.py and healthcheck.py passed 「落渊南丘」 after 2a7ff78d moved to two nests,
# so the 10-15 09:20 run - 梦枢天罗 48 then 落渊南丘 41, exactly the setting - printed ❌.
import re  # noqa: E402
from ark_relay.core.mastercfg_okww import ONLY_NESTS  # noqa: E402
text = lines(("name", "梦枢天罗残象聚落"), ("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41),
             only=",".join(ONLY_NESTS))
check("the 10-15 run under the configured names: green", [ok for ok, _ in scope(text, ",".join(ONLY_NESTS))], [True])
LIB = Path(__file__).resolve().parents[2] / "scripts" / "mac" / "lib"
literal = re.compile(r"nest_filter_checks\(\s*[^,()]+,\s*([\"'])[^\"']*\1\s*\)")
for name in ("okww_effective.py", "healthcheck.py"):
    src = (LIB / name).read_text(encoding="utf-8")
    check(f"{name} calls nest_filter_checks", "nest_filter_checks(" in src, True)
    check(f"{name}: no literal nest name passed to it", literal.findall(src), [])

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
