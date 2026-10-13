#!/usr/bin/env python3
"""The 「后来在 … 那趟重试里」 note names the retry by its start, on both clocks.

Real 2026-10-08 Endfield records (fixtures/ledger-1008-maaend-two-lists.jsonl):
the 09:30 run's 自动采集 was done by the 10:35→11:12 run. The note said
「后来在 11:12 那趟重试里」: the finish time, machine clock only, while the run's
own line reads 「10:35→11:12 … 东京 11:35→12:12」.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import ledger as core  # noqa: E402

es = [json.loads(x) for x in (Path(__file__).parent / "fixtures" / "ledger-1008-maaend-two-lists.jsonl").read_text(encoding="utf-8").splitlines()]
notes = core.retried_notes(es)
got = notes.get("2026-10-08/endfield/MaaEnd-05-29-15", "")
ok = got == "自动采集　后来在 10:35（东京 11:35）开始的那趟重试里做成了"
print(("  ✓ " if ok else "  ✗ ") + got)
sys.exit(0 if ok else 1)
