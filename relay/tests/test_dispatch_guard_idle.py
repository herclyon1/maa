"""run-one.sh wait-idle waits on dispatch_guard.py idle's exit code, not on the status wording.

2026-10-24 a hand-written wait grepped 「脚本在跑: []」 while the status line says 「脚本在跑: 无」,
and kept waiting long after the morning shift had ended (he asked 「不是已经跑完了吗？」).
"""
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "windows" / "dispatch_guard.py"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def idle_exit(tasklist: str, okww_pids: str = "") -> int:
    """dispatch_guard.py idle's exit code with `tasklist` as the process list and
    `okww_pids` as the PowerShell query for OK-WW's own python (okww_pids)."""
    real_run = subprocess.run

    def fake(cmd, *a, **k):
        out = tasklist if cmd == ["tasklist"] else okww_pids
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    subprocess.run = fake
    argv = sys.argv
    sys.argv = [str(GUARD), "idle"]
    try:
        runpy.run_path(str(GUARD), run_name="__main__")
    except SystemExit as e:
        return int(e.code or 0)
    finally:
        subprocess.run, sys.argv = real_run, argv
    return 0


print("[idle：只看有没有脚本或游戏在跑，退出码说话]")
check("什么都没在跑 → 0", idle_exit("System Idle Process  0\nexplorer.exe  1234\n"), 0)
check("MaaEnd 在跑 → 3", idle_exit("MaaEnd.exe  4321\n"), 3)
check("只有游戏开着 → 3", idle_exit("Endfield.exe  5555\n"), 3)
check("OK-WW 自己的 python 在跑 → 3", idle_exit("explorer.exe  1234\n", okww_pids="7996\n"), 3)
run_one = (ROOT / "scripts" / "mac" / "run-one.sh").read_text(encoding="utf-8")
check("run-one.sh wait-idle 用的是 idle 的退出码，不 grep 状态那一行", ("--py \"$G\" idle" in run_one, "grep" in run_one), (True, False))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
