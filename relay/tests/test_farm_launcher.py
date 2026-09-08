"""The farm launcher must not leave a console window on top of the game.

2026-09-09: the .bat ran pythonw in the foreground, so cmd.exe's console stayed open
over the middle of the screen for the whole run. OK-WW screenshots the game window,
read the black console where the confirm dialog should have been, and every teleport
failed with 「Teleport to boss failed」. Three runs, no echoes, and not one line in the
log pointing at the window. `start ""` hands OK-WW off and lets the .bat end.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import os
import subprocess

from ark_relay import echofarm
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


root = tmpdir()
py = root / "data" / "apps" / "ok-ww" / "python" / "pythonw.exe"
main = root.joinpath(*echofarm._WORKING, "main.py")
py.parent.mkdir(parents=True)
main.parent.mkdir(parents=True)
py.write_text("", encoding="utf-8")
main.write_text("", encoding="utf-8")

bat = tmpdir() / "farm.bat"
echofarm.BAT = str(bat)
os.environ["ARK_OKWW_DIR"] = str(root)

ran = []
real_run = subprocess.run


class Done:
    returncode = 0
    stderr = b""


subprocess.run = lambda *a, **k: (ran.append(list(a[0]) if a else []), Done())[1]
try:
    ok, why = echofarm._launch()
finally:
    subprocess.run = real_run

print("[启动脚本本身]")
check("说启动成功", ok)
check("没有理由要报", why, "")
text = bat.read_text(encoding="utf-8")
check("用 start 交棒后立刻退出", 'start ""' in text)
check("交给 pythonw，它自己不带控制台", "pythonw.exe" in text)
check("工作目录切到 OK-WW 那边", "cd /d" in text)
check("跑的是 FarmEchoTask 那一号", f"-t {echofarm.OKWW_TASK_INDEX}" in text)

print("[计划任务这一步]")
check("建了任务", any("schtasks" in c and "/create" in c for c in ran))
check("跑了任务", any("schtasks" in c and "/run" in c for c in ran))
check("任务在交互桌面上跑", any("/it" in c for c in ran))

print("[程序不在就直说，不要建一个跑不起来的任务]")
py.unlink()
ok2, why2 = echofarm._launch()
check("报失败", ok2, False)
check("话里说了找不到什么", "找不到" in why2)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
