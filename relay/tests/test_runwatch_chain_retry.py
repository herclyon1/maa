"""The overrun limit counts a shift whose failed attempt AUTO-MAS retried successfully as clean.

Audit s18 F1 (10-13): _chain called a run unclean when any record failed, even when
AUTO-MAS's retry of that script then succeeded, so the 09:00 shift was clean on only
2 of 13 days (10-01..10-13) and planned_minutes fell back to the longest of all
days. Each script is now judged by its last record in the chain, and a run a person
started at AUTO-MAS (raw.hand_started) is not part of the shift's chain.
Fixtures: the morning lines of the machine's ledgers 10-05, 10-08, 10-12.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))

from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.run import runwatch  # noqa: E402

FIX = RELAY / "tests" / "fixtures" / "runwatch-chain-1005-1012"
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def morning(day):
    rows = [json.loads(x) for x in (FIX / f"ledger-2026-10-{day:02d}-morning.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]
    return runwatch._chain(rows, datetime(2026, 10, day, 9, 0, tzinfo=SERVER_TZ))


check("10-12: MaaEnd 10:05 failed, its 10:59 retry succeeded -> clean; "
      "the hand-started OK-WW 11:41-11:49 does not lengthen it", morning(12), (158, True, False))
check("10-08: three failed MaaEnd attempts, the last (10:35-11:12) succeeded -> clean", morning(8),
      (132, True, False))
check("10-05: MaaEnd's last record failed (a retry used up by its self-update) -> not clean",
      morning(5), (150, False, False))

if fails:
    print("FAIL:", fails)
    sys.exit(1)
print("all checks passed")
