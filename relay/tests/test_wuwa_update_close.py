"""Closing WuWa for real: the game, OK-WW and the Kuro launcher (preupdate_okww._okww_close).

The launcher runs as launcher_main.exe in a version folder
(D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe), which the old full-path match on
…\\Wuthering Waves\\launcher.exe missed (2026-09-30). And 「已关掉」 was said without
looking: taskkill from session 0 does not reach the game under its anti-cheat
(echofarm._kill_on_desktop, 2026-09-09), and its return code was never read.

The relay's own WuWa client update through the launcher (update_wuwa, whose ready
words and timeouts were tested here) went on 2026-10-12: AUTO-MAS updates the
client before an OK-WW run (item 10b).
"""
import json
import subprocess
import sys
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay.features.echofarm import echofarm
from ark_relay.features.preupdate import preupdate_okww as pk

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


nosleep = lambda s: None  # noqa: E731

print("[启动器进程：按启动器目录前缀认 launcher.exe 和 launcher_main.exe]")
root = PureWindowsPath("D:/Wuthering Waves")
check("版本子目录里的 launcher_main.exe", pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe", root), True)
check("入口壳 launcher.exe", pk._is_wuwa_launcher("D:\\Wuthering Waves\\launcher.exe", root), True)
check("斜杠和大小写不影响", pk._is_wuwa_launcher("d:/wuthering waves/2.6.5.0/LAUNCHER_MAIN.EXE", root), True)
check("别的目录同名不算", pk._is_wuwa_launcher("C:\\Other\\launcher_main.exe", root), False)
check("前缀要到目录边界（Wuthering Waves Game 不算）",
      pk._is_wuwa_launcher("D:\\Wuthering Waves Game\\launcher.exe", root), False)
check("同目录别的程序不算", pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\Client.exe", root), False)
check("没有目录时按 \\Wuthering Waves\\ 这一段认 launcher_main.exe",
      pk._is_wuwa_launcher("D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe"), True)
check("没有目录时游戏本体目录不算", pk._is_wuwa_launcher("D:\\Wuthering Waves Game\\launcher_main.exe"), False)

print("[taskkill 看返回码：失败的不算关掉]")
PROCS = [{"ProcessId": 4242, "ExecutablePath": "D:\\Wuthering Waves\\launcher.exe"},
         {"ProcessId": 4343, "ExecutablePath": "D:\\Wuthering Waves\\2.6.5.0\\launcher_main.exe"},
         {"ProcessId": 5151, "ExecutablePath": "C:\\Program Files\\Other\\launcher_main.exe"}]


class R:
    def __init__(self, rc=0, out=b""):
        self.returncode, self.stdout, self.stderr = rc, out, b"ERROR: Access is denied."


calls = []
real_run = subprocess.run


def fake_run(cmd, *a, **k):
    calls.append(list(cmd))
    if any("launcher_main.exe" in str(x) and "CimInstance" in str(x) for x in cmd):
        return R(0, json.dumps(PROCS).encode())
    if cmd[:3] == ["taskkill", "/F", "/PID"]:
        return R(0 if cmd[3] == "4242" else 1)
    return R()


subprocess.run = fake_run
try:
    stopped = pk._stop_wuwa_launcher(root)
finally:
    subprocess.run = real_run
kills = [c for c in calls if c[:1] == ["taskkill"]]
check("两个都试了（按 PID）", [c[3] for c in kills], ["4242", "4343"])
check("只记返回 0 的那个", stopped, [4242])
check("别处的不碰", any("5151" in c for c in kills), False)
check("列进程一次查两个名字", sum(1 for c in calls if any("Name='launcher_main.exe'" in str(x) for x in c)), 1)

print("[_okww_close：关完复查，剩下的从桌面会话再关一次，再说实话]")
bat = tmpdir() / "ark-okww-stop.bat"
echofarm.STOP_BAT = str(bat)          # never the repo cwd
alive = {"game": ["Client-Win64-Shipping.exe"], "procs": [PROCS[1]]}
real_alive = echofarm.game_alive
echofarm.game_alive = lambda: list(alive["game"])
calls.clear()


def run2(cmd, *a, **k):
    calls.append(list(cmd))
    if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd):
        return R(0, json.dumps(alive["procs"]).encode())
    if cmd[:1] == ["taskkill"]:
        return R(1)                   # session 0 cannot reach it
    if cmd[:2] == ["schtasks", "/run"]:
        alive["game"], alive["procs"] = [], []    # the desktop door worked
    return R()


subprocess.run = run2
try:
    left = pk._okww_close(sleep=nosleep, launcher_root=root)
finally:
    subprocess.run = real_run
check("桌面那边关掉了 → []", left, [])
text = bat.read_text(encoding="utf-8")
check("bat 里按 PID 关启动器", "taskkill /F /PID 4343" in text, True)
check("bat 里照旧按名字关游戏", 'taskkill /F /IM "Client-Win64-Shipping.exe"' in text, True)
check("走了计划任务", any(c[:2] == ["schtasks", "/run"] for c in calls), True)

alive.update(game=["Client-Win64-Shipping.exe"], procs=[PROCS[1]])


def run3(cmd, *a, **k):
    calls.append(list(cmd))
    if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd):
        return R(0, json.dumps(alive["procs"]).encode())
    return R(1) if cmd[:1] == ["taskkill"] else R()


subprocess.run = run3
try:
    left = pk._okww_close(sleep=nosleep, launcher_root=root)
finally:
    subprocess.run = real_run
check("都没关掉 → 点名", left, ["Client-Win64-Shipping.exe", "launcher_main.exe"])

alive.update(game=[], procs=[])
subprocess.run = lambda cmd, *a, **k: (_ for _ in ()).throw(OSError("no pwsh")) \
    if any("CimInstance" in str(x) and "launcher_main.exe" in str(x) for x in cmd) else R()
try:
    left, pids = pk._okww_left(root)
finally:
    subprocess.run = real_run
check("启动器列表读不到 → 说读不到，不当没了", left, ["鸣潮启动器（查不到它还开没开着）"])
check("…也没有 PID 可关", pids, [])
echofarm.game_alive = real_alive

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
