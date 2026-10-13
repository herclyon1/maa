"""「重试 N 次全部失败」 counts the failed streak of this shift, not the whole day.

Real MAA rows of 2026-10-10 (tests/fixtures/ledger-2026-10-10-maa.jsonl, copied
from the machine's ledger): three morning failures (alarmed at 09:03:39 as
「重试 3 次」), a person's own run at 12:05 and the evening run at 21:30. Had the
evening run failed once, the old count (every row of the day) said 5 (audit
2026-10-13 s7 #4 / s1 #1).
"""
import json
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core.config import RunRecord
from ark_relay.features.alarm import records

FIX = Path(__file__).parent / "fixtures" / "ledger-2026-10-10-maa.jsonl"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def rec_of(e: dict) -> RunRecord:
    return RunRecord(run_id=e["run_id"], script=e["script"], user=e["user"], ok=e["ok"],
                     started=datetime.fromisoformat(e["started"]),
                     finished=datetime.fromisoformat(e["finished"]),
                     failed_tasks=list(e["failed_tasks"]), raw=dict(e["raw"]),
                     transitional=e["transitional"])


real = [json.loads(line) for line in FIX.read_text(encoding="utf-8").splitlines()]
with tempfile.TemporaryDirectory() as td:
    def eng_of(rows):
        return types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=None, state_dir=td),
                                     state=types.SimpleNamespace(read_ledger=lambda day: rows))

    print("[the real morning alarm: three failures in a row]")
    check("MAA-05-02-18 -> 3", records._attempts(eng_of(real), rec_of(real[2]), "2026-10-10"), 3)

    print("\n[the evening run failing once: the morning and a person's run are not its tries]")
    evening = dict(real[4], ok=False, failed_tasks=["MAA 在完成任务前中止"])
    rows = real[:4] + [evening]
    check("evening failure -> 1, not 5", records._attempts(eng_of(rows), rec_of(evening), "2026-10-10"), 1)

    print("\n[a success earlier in the same shift ends the streak before it]")
    again = dict(evening, run_id="2026-10-10/arknights/MAA-18-10-00",
                 started="2026-10-10T22:10:00+08:00", finished="2026-10-10T22:11:00+08:00")
    rows = real + [again]
    check("failure after the 21:30 success -> 1", records._attempts(eng_of(rows), rec_of(again), "2026-10-10"), 1)

    print("\n[a healed streak counts up to the success that healed it]")
    check("morning healed later -> 3", records._attempts(eng_of(real), rec_of(real[0]), "2026-10-10"), 3)

    print("\n[a retry that got through counts as the last try (「跑了 N 次」)]")
    healed = dict(real[2], run_id="2026-10-10/arknights/MAA-05-10-00", ok=True, failed_tasks=[],
                  started="2026-10-10T09:10:00+08:00", finished="2026-10-10T09:30:00+08:00")
    rows = real[:3] + [healed] + real[3:]
    check("three failures and the success -> 4", records._attempts(eng_of(rows), rec_of(real[0]), "2026-10-10"), 4)

print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
