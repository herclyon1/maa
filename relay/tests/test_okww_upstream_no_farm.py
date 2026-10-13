"""When upstream's own gate skips the stamina farm, the verdict says so.

Upstream v3.7.4 DailyTask.run farms stamina only while open_daily reads the
180-waveplate daily task under 180 and the activity points under 100
(DailyTask.py:86-93); at 180 the farm block (:117-128) is skipped without a line.
The overlay's claim_daily then farms it anyway (the standing order 「刷到空」) and
says 「上游这趟不刷体力（…）」 first. A run with no stamina fight and no
「not enough stamina」 said only 「既没进本，也没说体力不足」 (audit 3 item 11 /
audit 2026-10-13 item 22). Lines below are in upstream's and the overlay's format.
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


T = "2026-10-14 09:{:02d}:00,000 {} TaskExecutor {}"
OPEN = [T.format(27, "INFO", "DailyTask:open_daily"),
        T.format(27, "INFO", "DailyTask:info_set current daily progress 180"),
        T.format(27, "INFO", "DailyTask:info_set total daily points 60")]
LEFTOVER = T.format(28, "INFO", "DailyTask:上游这趟不刷体力（已用 180/180，活跃度满 False），按「刷到空」把剩下的体力刷掉")
DONE = T.format(40, "INFO", "DailyTask:Daily Task Completed")


def stamina(*lines):
    got = [c for c in outcome.okww_checks("\n".join([*OPEN, *lines, DONE]) + "\n", expect_nest=False)
           if c.label == "刷体力"]
    return [(c.ok, c.detail) for c in got]


print("[180/180, the overlay's leftover farm fought: green]")
check("green", stamina(LEFTOVER, T.format(29, "INFO", "TacetTask:enter combat None")), [(True, "")])

print("\n[180/180, the leftover farm raised: red, saying so]")
got = stamina(LEFTOVER, T.format(29, "ERROR", "DailyTask:补刷体力出错，照常领日常奖励: Teleport failed"))
check("red", [ok for ok, _ in got], [False])
check("names upstream's skip and the error",
      bool(got) and "上游这趟不刷体力" in got[0][1] and "补刷时出错：Teleport failed" in got[0][1], True)

print("\n[180/180, no leftover line at all: red, upstream's gate named]")
got = stamina()
check("red", [ok for ok, _ in got], [False])
check("says upstream read 180/180 and the leftover farm did not run",
      bool(got) and "180/180" in got[0][1] and "补刷没有跑到" in got[0][1], True)

print("\n[under 180, nothing: the old wording]")
text = "\n".join([T.format(27, "INFO", "DailyTask:info_set current daily progress 0"), DONE]) + "\n"
check("unchanged", [c.detail for c in outcome.okww_checks(text, expect_nest=False) if c.label == "刷体力"],
      ["既没进本，也没说体力不足"])

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
