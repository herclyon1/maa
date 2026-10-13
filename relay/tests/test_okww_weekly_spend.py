"""Verified weekly-boss claims count in 「消耗 波片」 (audit 2026-10-13 item 12).

okww_stamina_spent was summed only from the drops between get_stamina readings
(`info_set current_stamina`). The weekly claim does not take a reading, so its
60 waveplates per claim were missing: 10-12 11:41 (okww-task.sh 2) claimed three
times, read back 3->2->1->0, and the run showed no waveplates spent at all. Each
verified claim now adds 60, unless a drop between two readings already shows it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.features.verify import collector_okww as co
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def spent(*lines):
    p = tmpdir() / "OK-WW.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return co.parse_okww_log(p).get("okww_stamina_spent")


def claim(before):
    return (f"2026-10-12 11:5{before},000 INFO TaskExecutor FarmEchoTask:"
            f"周本领奖：回读确认领到，本周剩余 {before}/3→{before - 1}/3")


def reading(n, task="TacetTask"):
    return f"2026-10-12 11:40:00,000 INFO TaskExecutor {task}:info_set current_stamina {n}"


print("[claims with no reading around them: 60 each]")
check("three verified claims", spent(claim(3), claim(2), claim(1)), 180)

print("\n[a claim between two readings whose drop shows it: not counted twice]")
check("240 -> claim -> 180", spent(reading(240, "FarmEchoTask"), claim(3), reading(180, "FarmEchoTask")), 60)
check("240 -> claim -> 240 (no drop shown): still 60", spent(reading(240), claim(3), reading(240)), 60)

print("\n[stamina farm and claims in one run: both]")
check("tacet 240 -> 120, then one claim", spent(reading(240), reading(120), claim(1)), 180)

print("\n[a claim that did not read back as taken costs nothing here]")
same = "2026-10-12 11:50,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读次数没变（2/3），这次没领到"
check("unchanged count", spent(same), None)

print("\n[a drop a little short of 60 is the claim plus regeneration (item 18)]")
# review-C/wk.py: 100 -> claim -> 42 twelve minutes later reported 118.
t = ("2026-10-14 09:00:00,000 INFO TaskExecutor TacetTask:info_set current_stamina 100\n"
     "2026-10-14 09:10:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3\n"
     "2026-10-14 09:12:00,000 INFO TaskExecutor TacetTask:info_set current_stamina 42\n")
check("100 -> claim -> 42: 58, not 118", spent(t), 58)


def full(*lines):
    p = tmpdir() / "OK-WW.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return co.parse_okww_log(p)


TOPUP = "2026-10-12 15:29:47,649 INFO TaskExecutor FarmEchoTask:周本领奖：波片不够，动用备用体力"
print("\n[a claim topped up with backup: the backup is counted (item 18)]")
bar = "2026-10-12 15:29:44,000 INFO TaskExecutor FarmEchoTask:周本领奖：顶栏读到波片 20/240，备用 100"
got = full(bar, TOPUP, claim(3))
check("top bar read: 20 waveplates, 40 backup", (got.get("okww_stamina_spent"), got.get("okww_backup_spent")), (20, 40))
print("\n[10-12 15:29 / 15:31 shape: topped up, top bar not logged - said, not guessed]")
got = full(claim(3), TOPUP, claim(2), TOPUP, claim(1))
check("only the plain claim in 波片", got.get("okww_stamina_spent"), 60)
check("the two topped-up claims counted as unread", got.get("okww_weekly_topup_unread"), 2)
from datetime import datetime  # noqa: E402

from ark_relay.core import ledger_rows  # noqa: E402
cost = ledger_rows._block_okww(got, datetime(2026, 10, 12, 15, 33))[1]
check("the daily report says so", any("另有周本领奖 2 次用备用体力补足" in c for c in cost), True)
print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
