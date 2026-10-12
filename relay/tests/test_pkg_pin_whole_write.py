"""The rollback pin and current.txt are written whole: temp file, then os.replace.

Before 2026-10-12 _pin wrote the file in place. A power cut mid-write left it empty;
_pinned read that as 0, the rollback was forgotten and selfupdate moved straight back
into the version it had rolled away from.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

import pkg_layout  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


code = tmpdir()
(code / "state").mkdir()
pkg_layout._pin(code, 20261012111426)
check("pin written", pkg_layout._pinned(code), 20261012111426)

real_replace = os.replace


def cut(*_a, **_k):
    raise OSError("power cut")


os.replace = cut
try:
    pkg_layout._pin(code, 20261012130559)
except OSError:
    pass
os.replace = real_replace
check("a write cut before the swap keeps the old pin", pkg_layout._pinned(code), 20261012111426)

app = tmpdir()
pkg_layout._set_current(app, "20261012111426")
os.replace = cut
try:
    pkg_layout._set_current(app, "20261012130559")
except OSError:
    pass
os.replace = real_replace
check("a write cut before the swap keeps current.txt", pkg_layout.current(app), "20261012111426")

pkg_layout._pin(code, 0)
check("pin 0 removes the file", (code / "state" / pkg_layout.PIN_FILE).exists(), False)

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
