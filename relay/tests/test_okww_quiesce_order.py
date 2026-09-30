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

print("[鸣潮启动器 launcher.exe：只按完整路径停，别处同名的不动（2026-09-30）]")
import json  # noqa: E402

PROCS = [{"ProcessId": 4242, "ExecutablePath": "D:\\Wuthering Waves\\launcher.exe"},
         {"ProcessId": 5151, "ExecutablePath": "C:\\Program Files\\Other Game\\launcher.exe"}]


class Listed(Done):
    stdout = json.dumps(PROCS).encode()


calls.clear()


def fake_run(*a, **k):
    cmd = list(a[0]) if a else []
    calls.append(cmd)
    return Listed() if any("Name='launcher.exe'" in str(x) for x in cmd) else Done()


subprocess.run = fake_run
try:
    pk._okww_quiesce(sleep=lambda _s: None)
finally:
    subprocess.run = real_run
kills = [c for c in calls if c[:1] == ["taskkill"]]
check("路径是 \\Wuthering Waves\\launcher.exe 的那个被停（按 PID）",
      ["taskkill", "/F", "/PID", "4242"] in kills)
check("别处的 launcher.exe 不动", any("5151" in c for c in kills), False)
check("从不按进程名 launcher.exe 去杀", any("launcher.exe" in c for c in kills), False)
check("列进程只查 launcher.exe", sum(1 for c in calls if any("Name='launcher.exe'" in str(x) for x in c)), 1)
check("只有一个时 PowerShell 给的是对象不是数组，也认", (
    lambda: (setattr(Listed, "stdout", json.dumps(PROCS[0]).encode()),
             setattr(subprocess, "run", fake_run),
             pk._stop_wuwa_launcher())[-1])(), [4242])
subprocess.run = real_run
check("路径大小写与斜杠不影响", pk._is_wuwa_launcher("d:/wuthering waves/LAUNCHER.EXE"), True)
check("游戏目录里的不算", pk._is_wuwa_launcher("D:\\Wuthering Waves Game\\launcher.exe"), False)
check("读不到进程列表 → 什么都不停", (
    lambda: (setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no pwsh"))),
             pk._stop_wuwa_launcher())[-1])(), [])
subprocess.run = real_run

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
