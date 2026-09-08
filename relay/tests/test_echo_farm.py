"""Farm a boss until a wall-clock time, then put everything back.

Asked for on 2026-09-09 as 「刷的时候不要按次数，而是时间来」 - to a clock time, not a
repeat count. OK-WW only counts runs, so the clock lives in the relay. Two things must hold or
this quietly costs him tomorrow's morning run: the FarmEchoTask config is shared
with the daily's weekly-boss step and has to be restored exactly, and a failure to
launch must not leave the config pointed somewhere else.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import echofarm
from ark_relay.config import SERVER_TZ
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


ORIGINAL = {"Teleport to Boss": "Weekly Challenge", "Boss Level": "90",
            "Which Boss Challenge to Teleport": 1, "Which Weekly Boss to Teleport": 1,
            "Repeat Farm Count": 3, "Echo Pickup Method": "Walk"}


class Cfg:
    def __init__(self, root):
        self.okww_dir = root
        self.state_dir = root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)


def fresh():
    root = tmpdir()
    (root / "configs").mkdir(parents=True)
    (root / "configs" / "FarmEchoTask.json").write_text(
        json.dumps(ORIGINAL, ensure_ascii=False), encoding="utf-8")
    return Cfg(root)


def cfg_now(c):
    return json.loads((c.okww_dir / "configs" / "FarmEchoTask.json").read_text(encoding="utf-8"))


launched = []
echofarm._launch = lambda: (launched.append(1), (True, ""))[1]
echofarm.stop_okww = lambda: launched.append("stop")

print("[结束时刻：认得 08:30，认不出的一律拒绝]")
now = datetime(2026, 9, 9, 4, 0, tzinfo=SERVER_TZ)
check("今天还没到就是今天", echofarm.resolve_until("08:30", now).strftime("%m-%d %H:%M"), "09-09 08:30")
check("已经过了就是明天", echofarm.resolve_until("03:00", now).strftime("%m-%d %H:%M"), "09-10 03:00")
for bad in ("25:00", "8点半", "", None, "08:70"):
    check(f"拒绝 {bad!r}", echofarm.resolve_until(bad, now), None)

print("\n[开跑：配置改成打指定 boss，原来那份完整存下来]")
c = fresh()
ok, msg = echofarm.start(c, 1, "08:30", "天傀劫煞")
check("开跑了", ok, True)
check("话里有目标和时刻", "天傀劫煞" in msg and "08:30" in msg, True)
check("真的启动了一次", len(launched), 1)
after = cfg_now(c)
check("改成了打强敌", after["Teleport to Boss"], "Boss Challenge")
check("第几个", after["Which Boss Challenge to Teleport"], 1)
check("次数交给时钟，不再是 3", after["Repeat Farm Count"], echofarm.BIG_COUNT)
check("原配置一字不落地存着", echofarm.current(c.state_dir)["saved"], ORIGINAL)

print("\n[正在刷的时候不许再开一趟]")
ok2, msg2 = echofarm.start(c, 2, "09:00", "别的")
check("被拒", ok2, False)
check("说清在刷什么、刷到几点", "天傀劫煞" in msg2 and "08:30" in msg2, True)

print("\n[没到点什么都不做]")
check("还早", echofarm.tick(c, datetime(2026, 9, 9, 7, 0, tzinfo=SERVER_TZ)), "")
check("还在记录里", bool(echofarm.current(c.state_dir)), True)

print("\n[到点：停掉、原样还原、状态清空]")
note = echofarm.tick(c, datetime(2026, 9, 9, 8, 30, tzinfo=SERVER_TZ))
check("出了收工的话", "到点了" in note and "天傀劫煞" in note, True)
check("停过了", "stop" in launched, True)
check("配置一字不差地还原", cfg_now(c), ORIGINAL)
check("状态清空", echofarm.current(c.state_dir), {})
check("再 tick 一次什么都不做", echofarm.tick(c, datetime(2026, 9, 9, 9, 0, tzinfo=SERVER_TZ)), "")

print("\n[手动停：一样还原]")
c = fresh()
echofarm.start(c, 3, "08:30", "第 3 个")
note = echofarm.finish(c, "手动停止")
check("话里说是手动停的", "手动停止" in note, True)
check("配置还原", cfg_now(c), ORIGINAL)

print("\n[启动失败时不许把配置留在改过的样子]")
c = fresh()
echofarm._launch = lambda: (False, "计划任务起不来")
ok3, msg3 = echofarm.start(c, 1, "08:30", "天傀劫煞")
check("报失败", ok3, False)
check("话里说了已还原", "已还原" in msg3, True)
check("配置确实没动", cfg_now(c), ORIGINAL)
check("没留下半个状态", echofarm.current(c.state_dir), {})

print("\n[「第几个」只收 1..30 的数字]")
echofarm._launch = lambda: (True, "")
for bad in (0, 31, "一", None):
    c2 = fresh()
    check(f"拒绝 {bad!r}", echofarm.start(c2, bad, "08:30")[0], False)
    check(f"拒绝 {bad!r} 后配置没动", cfg_now(c2), ORIGINAL)

print("\n[收工那一步本身：先停计划任务，再把 OK-WW 的进程停干净]")
# The real function, not the stub - it is what actually ends the run on the machine.
import subprocess as _sp                                          # noqa: E402
import ark_relay.preupdate_okww as _pk                            # noqa: E402
_ran, _quiesced = [], []
_real_run, _real_q = _sp.run, _pk._okww_quiesce
_sp.run = lambda *a, **k: _ran.append(list(a[0]) if a else []) or None
_pk._okww_quiesce = lambda *a, **k: _quiesced.append(1)
try:
    # The stub above replaced the module attribute; reload to get the real one back.
    import importlib                                              # noqa: E402
    _mod = importlib.reload(sys.modules["ark_relay.echofarm"])
    _mod.stop_okww()
    check("结束了计划任务", any("schtasks" in c and "/end" in c for c in _ran), True)
    check("任务名对得上", any(_mod.TASK_NAME in c for c in _ran), True)
    check("把 OK-WW 的进程也停了", _quiesced, [1])
finally:
    _sp.run, _pk._okww_quiesce = _real_run, _real_q

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
