"""A shutdown command that failed must not count as a power-off (review of 2026-10-07, item 1).

`shutdown /s` was run with check=False and its exit code never read: when Windows
refuses (1190, a shutdown is already scheduled; or no privilege) _power_off still
returned True, shutdown._maybe_shutdown set _shutdown_issued and marked the
machine as going down, and every teardown after that was waved through as "the
relay's own power-off" while the machine stayed on.

Pinned: a non-zero exit code returns False; one ERROR line carries the exit
code and what shutdown printed (errwatch pushes a new kind of ERROR to the
group - the existing alarm path); and 「本轮已处理完毕，60 秒后关机」 is written only
after the command succeeded, because machine checks #37/#38 read that line as
proof the relay powered the machine off.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import engine
from ark_relay.machinechecks.system import POWER_OFF

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}（要 {want!r}）" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.rows = []

    def emit(self, record):
        self.rows.append((record.levelno, record.getMessage()))


class _Done:
    def __init__(self, code, err=b""):
        self.returncode, self.stdout, self.stderr = code, b"", err


grab = _Grab()
lg = engine.log
lg.addHandler(grab)
lg.setLevel(logging.DEBUG)
orig = engine.subprocess.run

print("[shutdown 退出码 1190（已经排了一次关机）：没关成]")
# What Windows prints is in the console codepage (GBK on the machine).
engine.subprocess.run = lambda cmd, **kw: _Done(1190, "系统关机已经安排好了。(1190)".encode("gbk"))
grab.rows.clear()
check("返回 False", engine.Engine._power_off(None), False)
errs = [m for lv, m in grab.rows if lv >= logging.ERROR]
check("记了一条 ERROR", len(errs), 1)
check("ERROR 里有退出码", bool(errs) and "1190" in errs[0], True)
check("ERROR 里有 Windows 说的原话", bool(errs) and "系统关机已经安排好了" in errs[0], True)
check("没写「60 秒后关机」", any(m.startswith(POWER_OFF) for _, m in grab.rows), False)

print("[shutdown 退出码 0：关了]")
engine.subprocess.run = lambda cmd, **kw: _Done(0)
grab.rows.clear()
check("返回 True", engine.Engine._power_off(None), True)
check("写了「60 秒后关机」", any(m.startswith(POWER_OFF) for _, m in grab.rows), True)
check("没有 ERROR", [m for lv, m in grab.rows if lv >= logging.ERROR], [])

print("[shutdown 根本跑不起来：没关成]")
def _boom(cmd, **kw):
    raise OSError("shutdown.exe not found")
engine.subprocess.run = _boom
grab.rows.clear()
check("返回 False", engine.Engine._power_off(None), False)
check("没写「60 秒后关机」", any(m.startswith(POWER_OFF) for _, m in grab.rows), False)

engine.subprocess.run = orig
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
