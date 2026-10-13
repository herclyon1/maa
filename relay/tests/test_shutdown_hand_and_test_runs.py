"""Hand-started and test-window runs never join a 早班/晚班 round nor move the skip key.

Replays the real ledgers of 2026-10-10..13 (fixtures/shutdown-1010-1013: the machine's
ledger rows cut to the fields the shutdown decision reads, its test-windows.json and
relay-dispatches.json) at every moment relay.log shows a power-off verdict.

Two of them went wrong on the old code:
* 10-12 21:45:34 the relay stayed on as 「最近一轮是手动触发的」 (a round started by hand) - the two
  test-window MaaEnd runs (18:26, 20:04, hand_started) were chained into the 21:30
  evening shift, whose first record then sat nowhere near a scheduled time;
* 10-13 11:13:55 「本轮已处理完毕，60 秒后关机」 - the hand-started test OK-WW of 11:07 was
  chained into the morning shift, and as a 4th ledger row it moved the skip key from
  2026-10-13:3 (the spent 「下次跑完不关机」, 10:00:36) to :4, so the skip no longer held.
The user's rule (10-10 18:31, DECISIONS D-1010-关机): only a finished 早班/晚班 powers off.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import plan
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.shutdown import shutdown

FIX = Path(__file__).resolve().parent / "fixtures" / "shutdown-1010-1013"
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def ledger(day):
    p = FIX / f"ledger-{day}.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


class Eng:
    """The engine as the shutdown decision sees it, at moment `now`: only the records
    that had landed (finished) by then exist."""
    _gu_rerun_at = None

    def __init__(self, now):
        self.now = now
        self.cfg = SimpleNamespace(state_dir=FIX, automas_dir=None)
        self.state = SimpleNamespace(read_ledger=self.read_ledger)

    def read_ledger(self, day):
        return [e for e in ledger(day)
                if datetime.fromisoformat(e.get("finished") or e["started"]) <= self.now]

    def _round_is_manual(self, group):
        return shutdown._round_is_manual(self, group)


# The machine's AUTO-MAS schedule: 早班 09:00, 晚班 21:30 (every shift record in the fixtures).
plan.schedule = lambda _d: [{"name": "早班", "times": ["09:00"], "items": ["s1"]}, {"name": "晚班", "times": ["21:30"], "items": ["s1"]}]


def at(s):
    return datetime.fromisoformat(f"2026-{s}").replace(tzinfo=SERVER_TZ)


def manual(when):
    eng = Eng(at(when))
    return shutdown._last_round_manual(eng, eng.now, shutdown._recent_entries(eng, eng.now))


def key(when):
    eng = Eng(at(when))
    return shutdown._shutdown_key(eng, eng.now)


print("[the two moments that went wrong]")
check("10-12 21:45:34 晚班 MAA 21:30 finished: a shift, not 「手动触发」 (test-window MaaEnd 18:26 / 20:04 left out)",
      manual("10-12T21:45:34"), False)
check("10-13 11:13:55 newest record is the hand-started test OK-WW 11:07: manual, stays on",
      manual("10-13T11:13:55"), True)
check("10-13 10:00:36 the spent 「下次跑完不关机」 recorded 2026-10-13:3 (relay.log 34010)",
      key("10-13T10:00:36"), "2026-10-13:3")
check("10-13 11:13:55 the test OK-WW does not move the skip key: still :3, the skip holds",
      key("10-13T11:13:55"), "2026-10-13:3")
check("10-12 21:45:34 key counts the shift records only (6 of 9 rows; hand 11:41, test 18:26 / 20:04 left out)",
      key("10-12T21:45:34"), "2026-10-12:6")

print("\n[10-12 12:10:36: the newest record was the hand-started OK-WW 11:41 - stays on]")
check("manual", manual("10-12T12:10:36"), True)

print("\n[every other verdict of 10-10..10-13 is unchanged]")
check("10-10 09:39:30 早班 done -> not manual (relay.log: 60 秒后关机)", manual("10-10T09:39:30"), False)
check("10-10 12:25:09 hand-started MAA 12:05 -> manual (relay.log: 最近一轮是手动触发的)",
      manual("10-10T12:25:09"), True)
check("10-10 21:50:00 晚班 done -> not manual", manual("10-10T21:50:00"), False)
check("10-11 09:59:27 早班 done -> not manual (the skip gate held it, relay.log 31916)",
      manual("10-11T09:59:27"), False)
check("10-11 21:45:42 晚班 done -> not manual (relay.log: 60 秒后关机)", manual("10-11T21:45:42"), False)
check("10-13 10:00:36 早班 done -> not manual (the mark was spent here)", manual("10-13T10:00:36"), False)

print("\n[a scheduled record is still chained as before: a retry within the round]")
check("10-12 11:39 早班 with the MaaEnd retry 10:59 -> not manual", manual("10-12T11:39:00"), False)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
