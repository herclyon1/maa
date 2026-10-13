"""desktop.kill says when taskkill did not end a program (review 2026-10-13, s5 #8).

kill() dropped every taskkill result, so 「access denied」 (exit code 1) looked to
its callers (the game-update flows, the make-up) exactly like a kill that worked.
Now: exit 0 (ended) and 128 (no such program running) are fine; anything else, or
a taskkill that could not run, is a WARNING and kill() returns False.
No Windows here: subprocess.run is faked.
"""
import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import desktop

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


codes = {}


def fake_run(cmd, **kw):
    name = cmd[-1]
    if codes.get(name) == "missing":
        raise FileNotFoundError(2, "taskkill not found")
    rc = codes.get(name, 0)
    out = {0: "成功: 已终止进程 \"x\"。", 128: "错误: 没有找到进程 \"x\"。", 1: "错误: 无法终止进程，拒绝访问。"}
    return types.SimpleNamespace(returncode=rc, stdout=out.get(rc, "").encode("gbk"), stderr=b"")


g = Grab()
desktop.log.addHandler(g)
real_run = desktop.subprocess.run
desktop.subprocess.run = fake_run
try:
    print("[结束了、本来就不在：都算好]")
    codes.update({"Games.exe": 0, "Endfield.exe": 128})
    check("返回成功", desktop.kill("Endfield.exe", "Games.exe"), True)
    check("没有警告", g.lines, [])

    print("\n[拒绝访问：返回失败，警告里有程序名和 taskkill 原话]")
    codes.update({"Games.exe": 1})
    got = desktop.kill("Endfield.exe", "Games.exe")
    check("返回失败", got, False)
    check("一条警告", len(g.lines), 1)
    check("警告写了是哪个程序、退出码和原话",
          bool(g.lines) and "Games.exe" in g.lines[0] and "1" in g.lines[0] and "拒绝访问" in g.lines[0], True)

    print("\n[taskkill 本身起不来：也算失败]")
    g.lines.clear()
    codes.update({"Games.exe": "missing"})
    check("返回失败", desktop.kill("Games.exe"), False)
    check("一条警告", len(g.lines), 1)
finally:
    desktop.subprocess.run = real_run
    desktop.log.removeHandler(g)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
