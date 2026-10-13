"""「Only these nests」 is checked by the nest's name when the overlay logs it.

outcome.nest_filter_checks told nests apart by the denominator of 「已击败残象 N/D」
only; three nests share the cap 48, so entering another 48-nest looked in scope
(audit 2026-10-13 item 10). The overlay now logs 「nightmare nest: nest name: <name>」
for each nest it clicks (「?」 when no name was read); the names are compared with
the setting (substring: OCR reads 「落渊南丘残象聚落」 for 「落渊南丘」). Logs without
the line keep the denominator rule.
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


T = "2026-10-13 09:27:{:02d},000 INFO TaskExecutor NightmareNestTask:{}"
FILTER = T.format(1, "nightmare nest: 只刷 ['落渊南丘']（设置来自母本）")


def entered(i, cap, name):
    return [T.format(10 + i, f"left_click 已击败残象：0/{cap} (1729, 348) after_sleep 2"),
            T.format(11 + i, f"nightmare nest: nest name: {name}"),
            T.format(12 + i, "enter combat None")]


def scope(text, only):
    got = [c for c in outcome.nest_filter_checks(text, only) if c.label == "残象聚落没进别的点位"]
    return [(c.ok, c.detail) for c in got]


print("[two nests with the same cap 48, one outside the setting: red by name]")
text = "\n".join([FILTER, *entered(0, 48, "梦枢天罗残象聚落"), *entered(5, 48, "落渊南丘残象聚落")])
got = scope(text, "梦枢天罗")
check("red", [ok for ok, _ in got], [False])
check("names the nest outside", "落渊南丘残象聚落" in (got[0][1] if got else ""), True)

print("\n[every nest entered is in the setting: green]")
check("both asked for", [ok for ok, _ in scope(text, "梦枢天罗,落渊南丘")], [True])

print("\n[name not read (「?」): the denominator rule]")
text = "\n".join([FILTER, *entered(0, 48, "?"), *entered(5, 48, "?")])
check("same cap twice reads as one nest (old rule, unchanged)", [ok for ok, _ in scope(text, "落渊南丘")], [True])
text = "\n".join([FILTER, *entered(0, 48, "?"), *entered(5, 41, "?")])
check("two caps for one name: red (old rule)", [ok for ok, _ in scope(text, "落渊南丘")], [False])

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
