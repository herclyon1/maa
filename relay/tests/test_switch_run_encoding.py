"""switch.run decodes Windows tools' output in the console code page, not UTF-8.

2026-10-13 (audit of the install / switch-over block, item 4): the machine's switch.log
(the install of 2026-10-11 10:04) has `[SC] ChangeServiceConfig �ɹ�` where sc.exe wrote
成功 in code page 936; switch.run decoded every tool's output as UTF-8. Now "oem".
The codec exists only on Windows, so this checks what run() passes to subprocess.run
and that 936 bytes decode cleanly under the code page "oem" maps to on his machine.
"""
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY.parent / "packaging"))

import switch  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Done:
    returncode, stdout, stderr = 0, "", ""


seen = {}


def fake_run(cmd, **kw):
    seen.update(kw)
    return Done()


had_flag = hasattr(switch.subprocess, "CREATE_NO_WINDOW")
saved = switch.subprocess.run
switch.subprocess.run = fake_run
if not had_flag:
    switch.subprocess.CREATE_NO_WINDOW = 0
try:
    switch.run("sc.exe", "config", "ArkRelayWatchdog", "start=", "auto")
finally:
    switch.subprocess.run = saved
    if not had_flag:
        del switch.subprocess.CREATE_NO_WINDOW

print("[switch.run]")
check("decodes in the console code page", seen.get("encoding"), "oem")
check("never raises on a byte it cannot map", seen.get("errors"), "replace")
sc_ok = "[SC] ChangeServiceConfig 成功".encode("cp936")
check("the machine's bytes read back under cp936 (what oem is there)",
      sc_ok.decode("cp936"), "[SC] ChangeServiceConfig 成功")
check("and were mojibake under UTF-8", "成功" in sc_ok.decode("utf-8", "replace"), False)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
