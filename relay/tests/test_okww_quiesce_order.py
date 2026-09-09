"""Stopping OK-WW has to kill the script before the game.

2026-09-09: the user stopped the echo farm from his phone, the relay reported it
stopped and put the config back - and 鸣潮 was still on screen. Two reasons, both
here: the game was killed first, so OK-WW was still alive to start it again; and the
process filter only matched `python.exe`, while the echo farm is deliberately launched
with `pythonw.exe` so no console window covers the game.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate_okww as pk

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


calls = []
real_run = subprocess.run


class Done:
    returncode = 0
    stdout = b""
    stderr = b""


subprocess.run = lambda *a, **k: (calls.append(list(a[0]) if a else []), Done())[1]
try:
    pk._okww_quiesce(sleep=lambda _s: None)
finally:
    subprocess.run = real_run

flat = ["\n".join(str(x) for x in c) for c in calls]
script_at = next((i for i, c in enumerate(flat) if "ok-ww" in c and "CimInstance" in c), -1)
game_at = next((i for i, c in enumerate(flat) if "Client-Win64-Shipping.exe" in c), -1)

print("[顺序：先停脚本，再关游戏]")
check("停脚本这步在", script_at >= 0)
check("关游戏这步在", game_at >= 0)
check("脚本排在游戏前面", script_at >= 0 and game_at >= 0 and script_at < game_at)

print("[进程名：pythonw 也要算，刷声骸用的就是它]")
check("匹配 pythonw.exe", any("pythonw.exe" in c for c in flat))
check("匹配 python.exe", any("python.exe" in c for c in flat))

print("[游戏那几个进程一个都不能漏]")
for name in ("ok-ww.exe", "Wuthering Waves.exe", "Client-Win64-Shipping.exe", "KRSDKExternal.exe"):
    check(f"关掉 {name}", any(name in c for c in flat))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
