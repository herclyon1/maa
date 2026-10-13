"""A skip that failed stays a failure when its red receipt could not be written.

Audit s1 (outside its scope, modes.py:467, 10-13): engine.skip_failed tells a failed
skip from an acknowledgement only by the red receipt modes writes with the same words.
_skip_receipt swallowed a write failure, so the failure went out on the quiet
acknowledgement route (texts.SKIP_MODE) instead of the SKIP_FAILED group alarm, and
the phone page kept showing the press's green 「已记下」.
"""
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))

from _tmp import tmpdir  # noqa: E402

from ark_relay.core import engine  # noqa: E402
from ark_relay.features.modes import modes  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


sd = tmpdir()
other = tmpdir()
real_add = modes.add_receipt


def broken_add(*a, **k):
    raise OSError(28, "No space left on device")


modes.add_receipt = broken_add
try:
    msg = modes._engage_failed(sd, "早班", "调度程序没回应")
finally:
    modes.add_receipt = real_add

check("nothing reached the receipts file", (sd / modes._RECEIPTS).exists(), False)
check("the failure is still a failure for the engine", engine.skip_failed(sd, msg), True)
check("the phone page lists it as red", [r["ok"] for r in modes.receipts(sd) if r["text"] == msg], [False])
check("another state folder does not see it", engine.skip_failed(other, msg), False)

ok_msg = "今天（2026-10-13）跳过队列「晚班」：已临时停用，过后自动恢复"
modes._skip_receipt(sd, "skip_today", True, ok_msg)
check("a written green receipt is still an acknowledgement", engine.skip_failed(sd, ok_msg), False)

if fails:
    print("FAIL:", fails)
    sys.exit(1)
print("all ok")
