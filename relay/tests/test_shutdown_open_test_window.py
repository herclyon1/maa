"""A test window can never swallow a 早班/晚班, even when test-off is never run.

The review of 25ebc227 (10-13): a window with no "until" counted as lasting forever,
so every later record - real shift runs included - was a test run; the newest round
read as manual, the skip key stopped at 2026-10-13:3, and the machine never powered
off (the real 10-13 ledger with the 11:05 window left open and an evening shift
added: 21:50 stayed on). A scheduled shift starting while a window was open counted
as test too.

Replays the real ledgers of fixtures/shutdown-1010-1013 with the windows left open,
plus a 晚班 on 10-13 (MAA 21:30, MaaEnd 21:46, shaped like the 10-12 / 10-11 ones).
"""
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import plan
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.shutdown import shutdown

FIX = Path(__file__).resolve().parent / "fixtures" / "shutdown-1010-1013"
fails = []

EVENING = [
    {"run_id": "2026-10-13/arknights/MAA-17-30-20", "script": "MAA", "user": "arknights",
     "started": "2026-10-13T21:30:20+08:00", "finished": "2026-10-13T21:45:10+08:00", "ok": True, "failed_tasks": []},
    {"run_id": "2026-10-13/endfield/MaaEnd-17-46-00", "script": "MaaEnd", "user": "endfield",
     "started": "2026-10-13T21:46:00+08:00", "finished": "2026-10-13T22:05:00+08:00", "ok": True, "failed_tasks": []},
]


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def state_dir(windows, extra=(), strip_hand=()):
    """A copy of the fixture state with `windows` as test-windows.json, `extra` records
    appended to their day's ledger, and raw.hand_started dropped from run ids `strip_hand`."""
    d = Path(tempfile.mkdtemp(prefix="shutdown-open-window-"))
    for p in FIX.iterdir():
        shutil.copy(p, d / p.name)
    (d / "test-windows.json").write_text(json.dumps(windows), encoding="utf-8")
    for e in extra:
        with (d / f"ledger-{e['started'][:10]}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(e) + "\n")
    for p in d.glob("ledger-*.jsonl"):
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        for r in rows:
            if r["run_id"] in strip_hand:
                r.get("raw", {}).pop("hand_started", None)
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return d


class Eng:
    """The engine as the shutdown decision sees it at `now`: only records landed by then."""
    _gu_rerun_at = None

    def __init__(self, d, now):
        self.d, self.now = d, now
        self.cfg = SimpleNamespace(state_dir=d, automas_dir=None)
        self.state = SimpleNamespace(read_ledger=self.read_ledger)

    def read_ledger(self, day):
        p = self.d / f"ledger-{day}.jsonl"
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []
        return [e for e in rows if datetime.fromisoformat(e.get("finished") or e["started"]) <= self.now]

    def _round_is_manual(self, group):
        return shutdown._round_is_manual(self, group)


plan.schedule = lambda _d: [{"name": "早班", "times": ["09:00"], "items": ["s1"]}, {"name": "晚班", "times": ["21:30"], "items": ["s1"]}]


def at(s):
    return datetime.fromisoformat(f"2026-{s}").replace(tzinfo=SERVER_TZ)


def manual(d, when):
    eng = Eng(d, at(when))
    return shutdown._last_round_manual(eng, eng.now, shutdown._recent_entries(eng, eng.now))


def key(d, when):
    eng = Eng(d, at(when))
    return shutdown._shutdown_key(eng, eng.now)


real = json.loads((FIX / "test-windows.json").read_text(encoding="utf-8"))
open_all = [{k: v for k, v in w.items() if k != "until"} for w in real]

print("[the review's case: the 10-13 11:05 OK-WW window never closed, a 晚班 runs that evening]")
d = state_dir(open_all, EVENING)
check("21:50 晚班 MAA 21:30 finished: a shift, not 「手动触发」", manual(d, "10-13T21:50:00"), False)
check("21:50 the key moves past the spent skip :3 -> :4 (powers off)", key(d, "10-13T21:50:00"), "2026-10-13:4")
check("22:06 晚班 MaaEnd finished too: still a shift, key :5", (manual(d, "10-13T22:06:00"), key(d, "10-13T22:06:00")),
      (False, "2026-10-13:5"))
check("11:13:55 the hand-started test OK-WW still keeps it on, key :3", (manual(d, "10-13T11:13:55"), key(d, "10-13T11:13:55")),
      (True, "2026-10-13:3"))

print("\n[every real 10-10..10-13 verdict holds with all windows left open (10-12 20:03 open covers 21:30)]")
for when, want in [("10-10T09:39:30", False), ("10-10T12:25:09", True), ("10-10T21:50:00", False),
                   ("10-11T09:59:27", False), ("10-11T21:45:42", False), ("10-12T11:39:00", False),
                   ("10-12T12:10:36", True), ("10-12T21:45:34", False), ("10-13T10:00:36", False)]:
    check(f"{when} manual={want}", manual(d, when), want)
check("10-12 21:45:34 key counts the 6 shift rows", key(d, "10-12T21:45:34"), "2026-10-12:6")
check("10-13 10:00:36 key :3", key(d, "10-13T10:00:36"), "2026-10-13:3")

print("\n[a 晚班 that starts while a fresh window is open (opened 21:20, never closed)]")
d = state_dir(real + [{"since": "2026-10-13T21:20:00+08:00", "what": "MAA"}], EVENING)
check("21:50 MAA 21:30 is the shift's: not manual, key :4", (manual(d, "10-13T21:50:00"), key(d, "10-13T21:50:00")),
      (False, "2026-10-13:4"))
check("22:06 MaaEnd 21:46 continues the shift: not manual, key :5",
      (manual(d, "10-13T22:06:00"), key(d, "10-13T22:06:00")), (False, "2026-10-13:5"))

print("\n[a test run AUTO-MAS could not tell was hand-started is still a test run inside its window]")
d = state_dir(open_all, strip_hand={"2026-10-13/wuwa/OK-WW-07-05-49"})
check("11:13:55 OK-WW 11:07 (window opened 11:05, after the shift ended): manual, key :3",
      (manual(d, "10-13T11:13:55"), key(d, "10-13T11:13:55")), (True, "2026-10-13:3"))

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
