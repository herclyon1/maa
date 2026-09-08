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
    """An OK-WW tree shaped the way the machine's is: the live config sits under
    the pyappify working directory, not at the install root. The first attempt on
    2026-09-09 looked at the root and the command answered 「找不到」."""
    root = tmpdir()
    d = root.joinpath(*echofarm._WORKING, "configs")
    d.mkdir(parents=True)
    (d / "FarmEchoTask.json").write_text(json.dumps(ORIGINAL, ensure_ascii=False), encoding="utf-8")
    return Cfg(root)


def cfg_now(c):
    return json.loads(echofarm._cfg_path(c.okww_dir).read_text(encoding="utf-8"))


launched = []
echofarm._launch = lambda: (launched.append(1), (True, ""))[1]
echofarm.stop_okww = lambda: launched.append("stop")
# The marker file lives in C:\ProgramData on the machine. Point it at a temp path so
# the tests never write into the repo (and never into a real machine path either).
echofarm.NO_CLAIM = str(tmpdir() / "no-claim")

print("[配置路径：按机器上的真实布局找，找不到就说找不到]")
_empty = tmpdir()
check("没有配置文件时不假装有", echofarm._cfg_path(_empty).is_file(), False)
check("目录是 None 时返回 None", echofarm._cfg_path(None), None)

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
check("等级压到最低档，不然打不过", after["Boss Level"], echofarm.FARM_LEVEL)
check("最低档不是原来那个 90", echofarm.FARM_LEVEL != ORIGINAL["Boss Level"], True)
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


print("\n[刷声骸期间必须挂着「不领奖」标记：领一次奖 60 波片，通宵刷会掏空账号]")
echofarm._launch = lambda: (launched.append(1), (True, ""))[1]
c = fresh()
check("开跑前没有标记", echofarm.no_claim_on(), False)
echofarm.start(c, 1, "08:30", "天傀劫煞")
check("开跑后标记挂上了", echofarm.no_claim_on(), True)
echofarm.finish(c, "手动停止")
check("收工后标记撤了", echofarm.no_claim_on(), False)

print("\n[启动失败也不许把标记留在机器上]")
c = fresh()
echofarm._launch = lambda: (False, "计划任务起不来")
echofarm.start(c, 1, "08:30", "天傀劫煞")
check("失败后没留标记", echofarm.no_claim_on(), False)
echofarm._launch = lambda: (launched.append(1), (True, ""))[1]

print("\n[OK-WW 长时间一行日志都不写就自己停下来并说话]")
# 2026-09-09: the game exited mid-farm and OK-WW sat against a window that was no
# longer there - six minutes without a single line and not one word about it.
# Silence that long now ends the run and says so.
import ark_relay.weeklyboss as _wb                                # noqa: E402
_real_log = _wb._okww_log
_logfile = tmpdir() / "ok-ww.log"
_logfile.write_text("x", encoding="utf-8")
_wb._okww_log = lambda: _logfile
try:
    check("读不出日志时不猜", echofarm.quiet_minutes(datetime(2026, 9, 9, 5, 0, tzinfo=SERVER_TZ)) is not None, True)
    c = fresh()
    echofarm.start(c, 1, "08:30", "天傀劫煞")
    _rec = echofarm.current(c.state_dir)
    _rec["started"] = "2026-09-09 04:00"
    echofarm._store(c.state_dir).set("queues", "echo_farm", _rec)
    import os as _os
    _quiet_since = datetime(2026, 9, 9, 4, 30, tzinfo=SERVER_TZ).timestamp()
    _os.utime(_logfile, (_quiet_since, _quiet_since))
    check("刚开跑一分钟不算停", echofarm.tick(c, datetime(2026, 9, 9, 4, 1, tzinfo=SERVER_TZ)), "")
    _before = len(launched)
    check("停了三分钟就自己重开", echofarm.tick(c, datetime(2026, 9, 9, 4, 35, tzinfo=SERVER_TZ)), "")
    check("真的重开了一次", len(launched) - _before, 1)
    check("重开次数记下来了", echofarm.current(c.state_dir)["restarts"], 1)
    check("刚重开完不重复开", echofarm.tick(c, datetime(2026, 9, 9, 4, 36, tzinfo=SERVER_TZ)), "")
    check("还是只开过一次", len(launched) - _before, 1)
    check("这时还在刷，没收工", bool(echofarm.current(c.state_dir)), True)

    print("\n[重开了还是不写日志就别硬撑，收工并说清重开过几次]")
    _rec2 = echofarm.current(c.state_dir)
    _rec2["restarts"] = echofarm.MAX_RESTARTS
    echofarm._store(c.state_dir).set("queues", "echo_farm", _rec2)
    note = echofarm.tick(c, datetime(2026, 9, 9, 4, 55, tzinfo=SERVER_TZ))
    check("收工了", "天傀劫煞" in note and "重开" in note, True)
    check("配置还原了", cfg_now(c), ORIGINAL)
    check("状态清空", echofarm.current(c.state_dir), {})
    check("标记也撤了", echofarm.no_claim_on(), False)
    _wb._okww_log = lambda: None
    c = fresh()
    echofarm.start(c, 1, "08:30", "天傀劫煞")
    check("读不到日志时不许乱停", echofarm.tick(c, datetime(2026, 9, 9, 5, 0, tzinfo=SERVER_TZ)), "")
    echofarm.finish(c, "收尾")
finally:
    _wb._okww_log = _real_log

print("\n[开跑时刻读不出来也不当成卡死]")
check("读不出开跑时刻返回 None", echofarm._started_at({"started": "不是时间"}), None)
check("读得出就是那个时刻", echofarm._started_at({"started": "2026-09-09 04:00"}).hour, 4)

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
    import importlib
    _mod = importlib.reload(sys.modules["ark_relay.echofarm"])
    _mod.stop_okww()
    check("结束了计划任务", any("schtasks" in c and "/end" in c for c in _ran), True)
    check("任务名对得上", any(_mod.TASK_NAME in c for c in _ran), True)
    check("把 OK-WW 的进程也停了", _quiesced, [1])
finally:
    _sp.run, _pk._okww_quiesce = _real_run, _real_q

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
