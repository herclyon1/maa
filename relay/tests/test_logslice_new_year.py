"""A relay.log slice across New Year keeps the January lines.

relay.log stamps `MM-DD HH:MM:SS` without a year; slice_log dated every such
line in the year of the window's start, so for a window 12-31 23:50 -> 01-01
00:20 the 01-01 lines landed eleven months before it and were dropped (audit
s17, low item).
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ["TZ"] = "Asia/Shanghai"
time.tzset()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.features.evidence.logslice import slice_log  # noqa: E402
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


d = tmpdir()
src = d / "relay.log"
src.write_text("12-31 23:40:00 INFO before the window\n"
               "12-31 23:55:00 INFO old year\n"
               "  continuation of the old-year line\n"
               "01-01 00:05:00 INFO new year\n"
               "01-01 00:30:00 INFO after the window\n", encoding="utf-8")
window = (datetime(2026, 12, 31, 23, 50).timestamp(), datetime(2027, 1, 1, 0, 20).timestamp())
print("[a window across New Year]")
out = slice_log(src, window, d / "out" / "relay.log")
text = out.read_text(encoding="utf-8") if out else ""
check("the December line inside is kept, with its continuation",
      ("old year" in text, "continuation" in text), (True, True))
check("the January line inside is kept", "new year" in text)
check("the lines outside stay out", ("before the window" in text, "after the window" in text), (False, False))

print("\n[an ordinary window is unchanged]")
src.write_text("10-12 10:00:00 INFO a\n10-12 11:00:00 INFO b\n", encoding="utf-8")
out = slice_log(src, (datetime(2026, 10, 12, 10, 30).timestamp(), datetime(2026, 10, 12, 11, 30).timestamp()),
                d / "out2" / "relay.log")
check("only the line inside", out.read_text(encoding="utf-8") if out else "", "10-12 11:00:00 INFO b\n")

if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
print("\nall passed")
