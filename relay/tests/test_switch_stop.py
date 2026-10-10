"""switch.py stop() - before an upgrade, at uninstall and at revert - ends the update's
restart helper before it stops the relay.

2026-10-11 (review round 8 #23): stop() stopped the watchdog and the relay but not
`launch.py relaunch` (pkg_layout.restart_soon). Within two minutes of a self-update or
rollback the helper started the relay again under the installer, or left one running
after an uninstall. a8c22829's launch.py gives up once a running watchdog stops, but not
a helper that started while the watchdog was down, nor one from an older package; stop()
now ends it as scripts/mac/estop.sh does.
"""
import fnmatch
import subprocess
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(RELAY))
sys.path.insert(0, str(ROOT / "packaging"))

import pkg_layout  # noqa: E402
import switch  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def like(text: str, pattern: str) -> bool:
    """PowerShell -like: wildcards * ? [], case-insensitive."""
    return fnmatch.fnmatchcase(text.lower(), pattern.lower())


print("[stop(): watchdog, then the helper, then the relay]")
steps = []
real_run, real_wd = switch.run, switch.stop_watchdog
switch.run = lambda *cmd: steps.append(("run", tuple(map(str, cmd)))) or 0
switch.stop_watchdog = lambda: steps.append(("watchdog",))
try:
    switch.stop()
finally:
    switch.run, switch.stop_watchdog = real_run, real_wd


def kind(step):
    if step[0] == "watchdog":
        return "watchdog"
    cmd = step[1]
    if cmd[0] == "powershell.exe" and switch.HELPER_LIKE in cmd[-1]:
        return "helper"
    if cmd[-2:] == (str(switch.APP / "launch.py"), "stop"):
        return "relay"
    return "other: " + " ".join(cmd)


check("order", [kind(s) for s in steps], ["watchdog", "helper", "relay"])
ps = next((s[1][-1] for s in steps if kind(s) == "helper"), "")
check("looks only at pythonw.exe (restart_soon starts the helper with it)",
      "Name='pythonw.exe'" in ps, True)
check("ends what it finds", "Stop-Process" in ps, True)

print("[the match: the helper restart_soon starts, and nothing else]")
calls = []
pkg_layout.restart_soon(Path("C:/Program Files/ArkRelay"), popen=lambda cmd, creationflags=0: calls.append(cmd))
helper_line = subprocess.list2cmdline(calls[0])
check("restart_soon's helper matches", like(helper_line, switch.HELPER_LIKE), True)
check("same match as estop.sh",
      f"-like '{switch.HELPER_LIKE}'" in (ROOT / "scripts" / "mac" / "estop.sh").read_text(encoding="utf-8"),
      True)
relay_line = subprocess.list2cmdline([r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe",
                                      r"C:\Program Files\ArkRelay\launch.py"])
check("the relay itself (task \\ArkRelay\\main) does not match", like(relay_line, switch.HELPER_LIKE), False)
stop_line = subprocess.list2cmdline([str(switch.PY), str(switch.APP / "launch.py"), "stop"])
check("launch.py stop does not match", like(stop_line, switch.HELPER_LIKE), False)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
