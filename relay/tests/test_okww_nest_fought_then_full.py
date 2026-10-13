"""A nest fought until full is 「fought」, not 「full, skipped」 (audit 2026-10-13 item 11).

outcome.nest_state checked 「指定点位都已打满，跳过」 before the fight lines, so the
usual morning run - fight the nest, then find every chosen nest full - was
reported as a skip: verdict 「残象聚落（已满，跳过）」 and step 「残象聚落（已刷满）」
on every real run 10-06 .. 10-13 (machine-okww-logs). Only a run that found the
nests full before any fight is a skip.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify import collector_okww as co, outcome  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


T = "2026-10-13 09:27:{:02d},000 INFO TaskExecutor NightmareNestTask:{}"
CLICK = T.format(34, "left_click 已击败残象：0/48 (1729, 348) after_sleep 2")
FIGHT = T.format(46, "enter combat None")
FULL = T.format(59, "nightmare nest: 指定点位都已打满，跳过（截图 nest_all_full）")

print("[fought, then all full: fought]")
both = "\n".join([CLICK, FIGHT, FULL])
check("nest_state", outcome.nest_state(both), "fought")
check("the step does not say 已刷满", "已刷满" in co._nest_step(both), False)
got = [c for c in outcome.okww_checks(both, expect_nest=True) if c.label.startswith("残象聚落")]
check("the verdict item", [(c.label, c.ok) for c in got], [("残象聚落", True)])

print("\n[full before any fight: a skip]")
check("nest_state", outcome.nest_state(FULL), "full")
got = [c for c in outcome.okww_checks(FULL, expect_nest=True) if c.label.startswith("残象聚落")]
check("the verdict item", [(c.label, c.ok) for c in got], [("残象聚落（已满，跳过）", True)])

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
