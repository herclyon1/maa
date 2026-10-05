"""gameupdate_games.emulator_boot: True only once adb answers with an installed client.

No test before (audit 2026-10-05, E). It is referenced (gameupdate.py:48/78,
gameupdate_games.py:547), so it is tested rather than deleted. Pinned: an
emulator that is already up is left alone; one that is not gets its zombie
processes cleared and is started through the console-session launcher; a
launch that fails or an emulator that never answers is False, never True.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import gameupdate_games as GG

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


LD = Path(__file__).parent / "ldconsole.exe"     # never executed: run/spawn are fakes
DEVICES_UP = "List of devices attached\nemulator-5554\tdevice\n"
DEVICES_DOWN = "List of devices attached\n"


class Machine:
    def __init__(self, *, up=False, comes_up=True, version="versionName=2.6.21"):
        self.up, self.comes_up, self.version = up, comes_up, version
        self.calls, self.spawned = [], []

    def run(self, args, *_a):
        self.calls.append(list(args))
        if args[-1] == "devices":
            return DEVICES_UP if self.up else DEVICES_DOWN
        if "dumpsys" in args[-1]:
            return self.version
        return ""

    def spawn(self, exe, args):
        self.spawned.append((str(exe).replace("\\", "/").rsplit("/", 1)[-1], args))
        self.up = self.comes_up
        return True

    def killed(self):
        return [c[-1] for c in self.calls if c[0] == "taskkill"]


def boot(m, **kw):
    return GG.emulator_boot(None, LD, 1, run=m.run, sleep=lambda _s: None, spawn=m.spawn, **kw)


print("[already up]")
m = Machine(up=True)
check("True", boot(m), True)
check("nothing killed", m.killed(), [])
check("nothing started", m.spawned, [])

print("[down -> cleared and started]")
m = Machine(up=False)
check("True once adb answers", boot(m), True)
check("zombies cleared first", m.killed(), list(GG._EMU_EXES))
check("started via the shortcut target with the instance index",
      m.spawned, [("dnplayer.exe", ("index=1",))])

print("[launch refused (e.g. no console session)]")
m = Machine(up=False)
m.spawn = lambda exe, args: False
check("False, no waiting", boot(m), False)

print("[never answers]")
m = Machine(up=False, comes_up=False)
check("False after the wait", boot(m, wait_s=0.05), False)

print("[adb answers but no client installed]")
m = Machine(up=True, version="")
check("False: an emulator without the game is not booted for our purpose",
      boot(m, wait_s=0.05), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
