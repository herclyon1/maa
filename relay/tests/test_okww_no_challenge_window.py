"""The no-challenge-button reason is told from the line of the same raise, by time.

collector_okww._okww_say turned 「Teleport to boss failed」 into the reason that the
challenge button never came when the overlay's 「找不到开启挑战」 line was within
3000 characters before the traceback header - a guess about stack lengths. On every
real log with both (2026-09-01 05:43, 06:35; fixtures/m6-okww/0921-weekly.log) the
line is 0.001-0.02 s before its header. Now: within 2 s before the header's own
timestamp (audit 2026-10-13 item 24, the rule of 29a44215 / bec95a17), the old
window only for a header line without a timestamp. Lines in upstream's format.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify import collector_okww as co

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


STACK = "".join(f'  File "x{i}.py", line {i}, in f\n    g()\n' for i in range(200))   # ~5.5 KB
NO_BTN = "2026-09-21 10:20:58,624 INFO TaskExecutor FarmEchoTask:找不到开启挑战，整屏读到: [失坠困咎之庭_1.00]\n"


def head(ts):
    return (f"2026-09-21 {ts} ERROR TaskExecutor FarmEchoTask:farm 4c error, try handle monthly card "
            "Traceback (most recent call last):\n")


TAIL = "    raise RuntimeError('Teleport to boss failed') from e\nRuntimeError: Teleport to boss failed\n"
SAY = "选了等级后没等到「开启挑战」"

print("[the real fixture still reads as no challenge button]")
real = (Path(__file__).resolve().parent / "fixtures" / "m6-okww" / "0921-weekly.log").read_text(encoding="utf-8")
check("0921-weekly", SAY in co._okww_error(real), True)

print("\n[the line 0.02 s before, but more than 3000 characters back: found]")
text = NO_BTN + STACK + head("10:20:58,644") + TAIL
check("found by time", SAY in co._okww_error(text), True)

print("\n[the line a minute before, close in the text: another event]")
text = NO_BTN.replace("10:20:58,624", "10:19:50,000") + head("10:20:58,644") + TAIL
check("not this raise", SAY in co._okww_error(text), False)

print("\n[header without a timestamp: the 3000-character window]")
text = NO_BTN + " ERROR TaskExecutor FarmEchoTask:farm 4c error Traceback (most recent call last):\n" + TAIL
check("near in the text: found", co._said_before(text, text.index(" ERROR"), co._NO_CHALLENGE), True)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
