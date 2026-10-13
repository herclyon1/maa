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
from ark_relay.features.echofarm import echofarm
from ark_relay.core.config import SERVER_TZ
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
_real_stop_script = echofarm.stop_okww_script
echofarm.stop_okww_script = lambda: launched.append("script") or True
# The marker file lives in C:\ProgramData on the machine. Point it at a temp path so
# the tests never write into the repo (and never into a real machine path either).
echofarm.NO_CLAIM = str(tmpdir() / "no-claim")

print("[配置路径：按机器上的真实布局找，找不到就说找不到]")
_empty = tmpdir()
check("没有配置文件时不假装有", echofarm._cfg_path(_empty).is_file(), False)
check("目录是 None 时返回 None", echofarm._cfg_path(None), None)

print("[结束时刻：认得 08:30，认不出的一律拒绝]")
now = datetime(2026, 9, 9, 4, 0, tzinfo=SERVER_TZ)
NOW = now
check("今天还没到就是今天", echofarm.resolve_until("08:30", now).strftime("%m-%d %H:%M"), "09-09 08:30")
check("已经过了就是明天", echofarm.resolve_until("03:00", now).strftime("%m-%d %H:%M"), "09-10 03:00")
for bad in ("25:00", "8点半", "", None, "08:70"):
    check(f"拒绝 {bad!r}", echofarm.resolve_until(bad, now), None)

print("\n[开跑：配置改成打指定 boss，原来那份完整存下来]")
c = fresh()
ok, msg = echofarm.start(c, 1, "08:30", "天傀劫煞", now=NOW)
check("开跑了", ok, True)
check("话里有目标和时刻", "天傀劫煞" in msg and "08:30" in msg, True)
check("真的启动了一次", len(launched), 1)
after = cfg_now(c)
check("改成了打强敌", after["Teleport to Boss"], "Boss Challenge")
check("第几个", after["Which Boss Challenge to Teleport"], 1)
check("次数交给时钟，不再是 3", after["Repeat Farm Count"], echofarm.BIG_COUNT)
check("等级是会掉声骸的最低一档 80（50 级不掉声骸）", after["Boss Level"], "80")
check("配置里写的就是 FARM_LEVEL", after["Boss Level"], echofarm.FARM_LEVEL)
check("不是原来那个 90", echofarm.FARM_LEVEL != ORIGINAL["Boss Level"], True)
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

print("\n[跑到一半改收工时刻：提前或延后都行，别的不动]")
c = fresh()
echofarm._launch = lambda: (launched.append(1), (True, ""))[1]
echofarm.start(c, 1, "08:30", "天傀劫煞", now=NOW)
_before = dict(echofarm.current(c.state_dir))
ok, msg = echofarm.retime(c, "21:00", now=NOW)
check("改成功", ok, True)
check("话里有新旧两个时刻", "08:30" in msg and "21:00" in msg, True)
check("话里说了还剩多久", "还剩" in msg, True)
check("记录里的收工时刻真的变了", echofarm.current(c.state_dir)["until"][11:], "21:00")
check("原配置一字没动", echofarm.current(c.state_dir)["saved"], _before["saved"])
check("开跑时刻没被改掉", echofarm.current(c.state_dir)["started"], _before["started"])
check("提前也行", echofarm.retime(c, "05:00", now=NOW)[1].count(":") >= 2, True)
# A time already past rolls to tomorrow, the same rule as starting a farm.
check("已经过去的时刻算明天的，和开跑时同一条规则",
      echofarm.retime(c, "03:00", now=datetime(2026, 9, 9, 4, 0, tzinfo=SERVER_TZ))[0], True)
check("确实记成了明天", echofarm.current(c.state_dir)["until"][:10], "2026-09-10")
for bad in ("25:00", "九点", ""):
    check(f"看不懂的时刻拒绝 {bad!r}", echofarm.retime(c, bad, now=NOW)[0], False)
echofarm.finish(c, "收尾")
check("没在刷的时候改不了", echofarm.retime(c, "21:00", now=NOW)[0], False)
check("而且说清是没在刷", "没有在刷" in echofarm.retime(c, "21:00", now=NOW)[1], True)

print("\n[手动停：一样还原]")
c = fresh()
echofarm.start(c, 3, "08:30", "第 3 个")
note = echofarm.finish(c, "手动停止")
check("话里说是手动停的", "手动停止" in note, True)
check("配置还原", cfg_now(c), ORIGINAL)

# 2026-10-12 (mute audit item 9): a wrap-up that says something went wrong (the farm
# stopped because OK-WW could not be relaunched or farmed nothing, the end time unreadable,
# the game left open, the boss setting not put back) went to Server酱 only, inside the
# 「🥚 刷声骸收工」 text. A fault still there reaches the group; a clean wrap-up stays info.
print("\n[the engine's wrap-up: a failed one is a group alarm, a clean one is not]")
import types  # noqa: E402
from datetime import timedelta  # noqa: E402
from ark_relay.core import texts  # noqa: E402
from ark_relay.core.engine import Engine  # noqa: E402
from ark_relay.core.notify import route_of  # noqa: E402


class _Sent:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []


def _wrapup(c):
    """The engine's tick step on the real clock; (route, is a wrap-up title) of each push."""
    eng = types.SimpleNamespace(cfg=c, notifier=_Sent())
    Engine._echo_farm_deadline(eng)
    return [(route_of(t, alert=a), "收工" in t) for t, _, a in eng.notifier.sent]


def _farm(**fields):
    c = fresh()
    echofarm.start(c, 1, "08:30", "天傀劫煞", now=NOW)      # until 2026-09-09 08:30: long past
    rec = echofarm.current(c.state_dir)
    rec.update(fields)
    echofarm._store(c.state_dir).set("queues", "echo_farm", rec)
    return c


import ark_relay.features.weekly.weeklyboss as _wbw                               # noqa: E402
_wrap_log = tmpdir() / "wrap.log"
_wrap_real = _wbw._okww_log
_wbw._okww_log = lambda: _wrap_log
_wrap_log.write_text("2026-09-09 04:01:00,000 INFO TaskExecutor FarmEchoTask:enter combat None\n"
                     "2026-09-09 04:02:00,000 INFO TaskExecutor FarmEchoTask:farm echo on the face\n",
                     encoding="utf-8")
check("on time, all put back, OK-WW farmed: one info wrap-up", _wrapup(_farm()), [("info", True)])
# 2026-10-13 audit: a night that farmed nothing ended as a clean 「到点了」.
_wrap_log.write_text("2026-09-09 03:00:00,000 INFO TaskExecutor FarmEchoTask:farm echo before the start\n"
                     + "".join(f"2026-09-09 04:{m:02d}:00,000 INFO hwnd_window changed\n" for m in range(1, 50)),
                     encoding="utf-8")
check("on time but nothing farmed since the start: the group", _wrapup(_farm()), [("group", True)])
_c0 = _farm()
_note0, _bad0 = echofarm.tick_result(_c0)
check("…and the line says nothing was farmed", ("一次都没刷到" in _note0, _bad0), (True, True))
_wrap_log.write_text("2026-09-09 04:01:00,000 INFO TaskExecutor FarmEchoTask:enter combat None\n"
                     "2026-09-09 04:02:00,000 INFO TaskExecutor FarmEchoTask:farm echo on the face\n",
                     encoding="utf-8")
_c1 = _farm()
_note1, _bad1 = echofarm.tick_result(_c1)
check("a farmed night's line gives the count", ("记到 2 次进展" in _note1, _bad1), (True, False))
_wbw._okww_log = lambda: None
check("on time, OK-WW log unreadable: the group (unknown is not fine)", _wrapup(_farm()), [("group", True)])
_c2 = fresh()
echofarm.start(_c2, 1, "08:30", "天傀劫煞", now=NOW)
_note2, _bad2 = echofarm._finish(_c2, "手动停止")
check("a stop by hand is not judged on progress", _bad2, False)
_wbw._okww_log = lambda: _wrap_log
check("end time unreadable, farm stopped: the group", _wrapup(_farm(until="坏的")), [("group", True)])
_launch_was, _quiet_was = echofarm._launch, echofarm.quiet_minutes
echofarm._launch = lambda: (False, "启动计划任务失败")
echofarm.quiet_minutes = lambda now=None, since=None: 30.0
try:
    tomorrow = (datetime.now(tz=SERVER_TZ) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    got = _wrapup(_farm(until=tomorrow, started="2026-09-09 04:00"))
finally:
    echofarm._launch, echofarm.quiet_minutes = _launch_was, _quiet_was
check("OK-WW stopped and the relaunch failed: the group", got, [("group", True)])
_stop_was = echofarm.stop_okww
echofarm.stop_okww = lambda: texts.echo_farm_game_left(["Client-Win64-Shipping.exe"])
try:
    got = _wrapup(_farm())
finally:
    echofarm.stop_okww = _stop_was
check("on time but the game left open: the group", got, [("group", True)])
_wbw._okww_log = _wrap_real

# docs/SILENT-FAILURES-AUDIT.md echofarm.py:423 - a failed restore used to replace
# the note, so 「游戏没关掉」 from stop_okww never reached the receipt.
print("\n[finish: every warning reaches the receipt, none overwrites another]")
_stub_stop = echofarm.stop_okww
echofarm.stop_okww = lambda: "；**游戏没关掉（Client-Win64-Shipping.exe），已交给我们这边去关**"
try:
    c = fresh()
    echofarm.start(c, 3, "08:30", "第 3 个")
    echofarm._cfg_path(c.okww_dir).unlink()
    note = echofarm.finish(c, "手动停止")
    check("config missing: says so", "找不到配置文件" in note, True)
    check("…and still says the game is up", "游戏没关掉" in note, True)
    c = fresh()
    echofarm.start(c, 3, "08:30", "第 3 个")
    _real_write = echofarm.atomic_write_text
    echofarm.atomic_write_text = lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
    try:
        note = echofarm.finish(c, "手动停止")
    finally:
        echofarm.atomic_write_text = _real_write
    check("restore failed: says so", "没能改回去" in note, True)
    check("…and still says the game is up", "游戏没关掉" in note, True)
finally:
    echofarm.stop_okww = _stub_stop

print("\n[还原的是母本那份，不是 working 里上一次刷声骸留下的]")
# 2026-09-09: the working file already held a farm's 「Boss Challenge / 30」 when
# the next farm started, so 「配置已还原」 restored a farm config.
c = fresh()
leftover = dict(ORIGINAL, **{"Teleport to Boss": "Boss Challenge", "Repeat Farm Count": 30})
echofarm._cfg_path(c.okww_dir).write_text(json.dumps(leftover, ensure_ascii=False), encoding="utf-8")
c.automas_dir = tmpdir()
_md = c.automas_dir / "data" / "sid" / "Default" / "ConfigFile"; _md.mkdir(parents=True)
(_md / "DailyTask.json").write_text("{}", encoding="utf-8")
(_md / "FarmEchoTask.json").write_text(json.dumps(ORIGINAL, ensure_ascii=False), encoding="utf-8")
echofarm.start(c, 3, "08:30", "第 3 个")
check("刷的时候是刷声骸的设置", cfg_now(c)["Which Boss Challenge to Teleport"], 3)
echofarm.finish(c, "手动停止")
check("停了以后是母本的周本设置，不是 working 里的残留", cfg_now(c), ORIGINAL)

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
import ark_relay.features.weekly.weeklyboss as _wb                                # noqa: E402
_real_log = _wb._okww_log
_logfile = tmpdir() / "ok-ww.log"
_logfile.write_text("2026-09-09 04:30:00 INFO farm echo on the face\n", encoding="utf-8")
_wb._okww_log = lambda: _logfile
try:
    check("读不出日志时不猜", echofarm.quiet_minutes(datetime(2026, 9, 9, 5, 0, tzinfo=SERVER_TZ)) is not None, True)
    c = fresh()
    echofarm.start(c, 1, "08:30", "天傀劫煞", now=NOW)
    _rec = echofarm.current(c.state_dir)
    _rec["started"] = "2026-09-09 04:00"
    echofarm._store(c.state_dir).set("queues", "echo_farm", _rec)
    import os as _os
    _quiet_since = datetime(2026, 9, 9, 4, 30, tzinfo=SERVER_TZ).timestamp()
    _os.utime(_logfile, (_quiet_since, _quiet_since))
    check("刚开跑一分钟不算停", echofarm.tick(c, datetime(2026, 9, 9, 4, 1, tzinfo=SERVER_TZ)), "")
    _before = len(launched)
    check("五分钟没刷到东西就自己重开", echofarm.tick(c, datetime(2026, 9, 9, 4, 36, tzinfo=SERVER_TZ)), "")
    check("真的重开了一次", launched[_before:].count(1), 1)
    check("重开次数记下来了", echofarm.current(c.state_dir)["restarts"], 1)
    check("刚重开完不重复开", echofarm.tick(c, datetime(2026, 9, 9, 4, 38, tzinfo=SERVER_TZ)), "")
    check("还是只开过一次", launched[_before:].count(1), 1)
    check("第一次只重开脚本，不动游戏", "stop" in launched[_before:], False)
    # 2026-10-13 audit: nothing was stopped before the first relaunch, so a live
    # OK-WW and a new `pythonw main.py -t 2 -e` could both drive one game.
    check("first relaunch: the old OK-WW script is stopped before the new one starts",
          launched[_before:], ["script", 1])

    # 2026-09-09: the game itself wedged on a loading screen and restarting the
    # script against it did nothing, twice, while the farm stood still.
    _rec3 = echofarm.current(c.state_dir)
    _rec3["restarted"] = "2026-09-09 04:36"
    echofarm._store(c.state_dir).set("queues", "echo_farm", _rec3)
    _mid = len(launched)
    check("还是没进展就再来一次", echofarm.tick(c, datetime(2026, 9, 9, 4, 42, tzinfo=SERVER_TZ)), "")
    check("第二次连游戏一起重启", "stop" in launched[_mid:], True)
    check("重开次数记到 2", echofarm.current(c.state_dir)["restarts"], 2)
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

print("\n[判据是「有没有刷到东西」，不是「日志有没有在写」]")
# 2026-09-09: the game hung on a loading screen for sixteen minutes while OK-WW kept
# writing window-size and update-check lines. A watchdog that measured silence saw a
# busy log and never fired, and restarting the script against a wedged game did
# nothing twice over.
_noisy = tmpdir() / "noisy.log"
_wb2 = __import__("ark_relay.features.weekly.weeklyboss", fromlist=["x"])
_real2 = _wb2._okww_log
_wb2._okww_log = lambda: _noisy
try:
    _noisy.write_text(
        "2026-09-09 04:00:00 INFO farm echo on the face\n"
        + "".join(f"2026-09-09 04:{m:02d}:00 INFO hwnd_window:do_update_window_size changed\n"
                 for m in range(1, 40)),
        encoding="utf-8")
    stuck = echofarm.quiet_minutes(datetime(2026, 9, 9, 4, 40, tzinfo=SERVER_TZ))
    check("日志一直在写，但四十分钟没刷到东西 → 算卡住", round(stuck), 40)
    _noisy.write_text(
        "2026-09-09 04:00:00 INFO hwnd_window:do_update_window_size changed\n"
        "2026-09-09 04:39:00 INFO FarmEchoTask:farm echo walk_find_echo True\n",
        encoding="utf-8")
    fresh_ = echofarm.quiet_minutes(datetime(2026, 9, 9, 4, 40, tzinfo=SERVER_TZ))
    check("刚刷到东西就不算卡住", round(fresh_), 1)
    check("阈值给到五分钟（一趟约一分钟，死一次约两分钟）",
          echofarm.RESTART_QUIET_MINUTES, 5)

    # 2026-10-13 audit: a game in a retry loop logs 20-39 KB a minute, so the last
    # progress line falls out of the 300 KB tail. The fallback was the file's mtime -
    # "now" for a log that keeps growing - so quiet read 0 and nothing ever fired.
    import os as _os2
    _noise = "".join(f"2026-09-09 05:{m // 60:02d}:{m % 60:02d},000 INFO TaskExecutor retry loop "
                     + "x" * 200 + "\n" for m in range(0, 3000))
    _noisy.write_text("2026-09-09 04:00:00,000 INFO FarmEchoTask:farm echo on the face\n" + _noise,
                      encoding="utf-8")
    check("fixture: the progress line is beyond the 300 KB tail",
          _noisy.stat().st_size - len("2026-09-09 04:00:00,000 INFO FarmEchoTask:farm echo on the face\n")
          > echofarm._TAIL_BYTES, True)
    _t = datetime(2026, 9, 9, 5, 50, tzinfo=SERVER_TZ)
    _os2.utime(_noisy, (_t.timestamp(), _t.timestamp()))
    check("no progress in the tail: measured from the launch, not the fresh mtime",
          round(echofarm.quiet_minutes(_t, datetime(2026, 9, 9, 5, 20, tzinfo=SERVER_TZ))), 30)
    check("no launch time: measured from the tail's first line (a floor)",
          echofarm.quiet_minutes(_t) >= 5, True)
    _c3 = fresh()
    echofarm.start(_c3, 1, "08:30", "天傀劫煞", now=NOW)
    _r3 = echofarm.current(_c3.state_dir)
    _r3["started"] = "2026-09-09 05:20"
    echofarm._store(_c3.state_dir).set("queues", "echo_farm", _r3)
    _was3 = echofarm._launch
    _l3 = []
    echofarm._launch = lambda: (_l3.append(1), (True, ""))[1]
    try:
        echofarm.tick(_c3, _t)
    finally:
        echofarm._launch = _was3
    check("a noisy stuck farm gets its restart", (len(_l3), echofarm.current(_c3.state_dir).get("restarts")), (1, 1))
    echofarm.finish(_c3, "收尾")
finally:
    _wb2._okww_log = _real2

print("\n[an earlier session's progress in the same file does not count for this launch]")
# 2026-10-13 review replay: the machine's real ok-script.2026-10-12.log, cut at
# 15:25:32 (the farm launched 15:23 after a morning run whose last progress line is
# 11:47:53). Read with a 15:28 restart at 15:33:30, quiet was 225.6 minutes - past
# STALL_MINUTES, a failed stop for a farm 10 minutes old.
import gzip as _gz                                                                 # noqa: E402
_day = tmpdir() / "ok-script.2026-10-12.log"
_day.write_bytes(_gz.decompress((Path(__file__).resolve().parent / "fixtures"
                                 / "ok-script-2026-10-12-cut-152532.log.gz").read_bytes()))
_real4 = _wbw._okww_log
_wbw._okww_log = lambda: _day
try:
    _q = echofarm.quiet_minutes(datetime(2026, 10, 12, 15, 33, 30, tzinfo=SERVER_TZ),
                                datetime(2026, 10, 12, 15, 28, tzinfo=SERVER_TZ))
    check("measured from the 15:28 restart, not the 11:47 line", round(_q, 1), 5.5)
    check("…so below the stall stop", _q < echofarm.STALL_MINUTES, True)
    _q0 = echofarm.quiet_minutes(datetime(2026, 10, 12, 15, 25, 40, tzinfo=SERVER_TZ),
                                 datetime(2026, 10, 12, 15, 23, tzinfo=SERVER_TZ))
    check("two minutes into the launch reads two minutes", round(_q0, 1), 2.7)
finally:
    _wbw._okww_log = _real4

print("\n[进度关键词：只认今天真的会写出来的句子]")
# Real lines: OK-WW v3.7.3's from tests/replay/2026-09-07/wuwa/OK-WW-06-00-55.log
# (lines 168, 226, 275), the overrides' copied from their log_info calls.
_replay = (Path(__file__).resolve().parent / "replay" / "2026-09-07" / "wuwa"
           / "OK-WW-06-00-55.log").read_text(encoding="utf-8")
from ark_relay.features.okww_patch import okww_overlay as _ov                         # noqa: E402
_overrides = _ov.source_text()
for _k in echofarm.PROGRESS:
    check(f"「{_k}」今天还有人写（上游真实日志或覆盖层）", _k in _replay or _k in _overrides, True)
_REAL = [
    "2026-09-07 10:06:50,862 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm",
    "2026-09-07 10:06:52,779 INFO TaskExecutor FarmEchoTask:enter combat None",
    "2026-09-07 10:07:53,984 INFO TaskExecutor FarmEchoTask:farm echo on the face",
    "2026-09-09 04:39:00,000 INFO TaskExecutor FarmEchoTask:限时提前开放：确认后直接进场，in_realm=True，整屏读到 []",
    "2026-09-09 04:39:00,000 INFO TaskExecutor FarmEchoTask:刷声骸模式：复活成功，接着刷下一趟",
]
for _line in _REAL:
    _msg = _line.split("FarmEchoTask:", 1)[1]
    check(f"真有人写：{_msg[:30]}", _line in _replay or _msg.split("，")[0] in _overrides, True)
    check(f"算进度：{_msg[:30]}", any(k in _line for k in echofarm.PROGRESS), True)
_NOT = [
    # The retired bosstip text patch's sentence: nothing writes it any more.
    "2026-09-09 04:39:00,000 INFO TaskExecutor FarmEchoTask:限时提前开放：已经在场地里，跳过队伍和传送这两步",
    # The overrides when the death dialog is not one they know: stuck, not moving.
    "2026-09-09 04:39:00,000 INFO TaskExecutor FarmEchoTask:刷声骸模式：这不像死亡弹窗，不乱点。整屏读到 []",
    "2026-09-09 04:39:00,000 INFO TaskExecutor FarmEchoTask:刷声骸模式：复活这一步没做成 TimeoutError()",
]
for _line in _NOT:
    check(f"不算进度：{_line.split('FarmEchoTask:', 1)[1][:30]}", any(k in _line for k in echofarm.PROGRESS), False)
_wb3 = __import__("ark_relay.features.weekly.weeklyboss", fromlist=["x"])
_real3, _f3 = _wb3._okww_log, tmpdir() / "kw.log"
_wb3._okww_log = lambda: _f3
try:
    _f3.write_text(_REAL[0] + "\n" + "\n".join(_NOT) + "\n", encoding="utf-8")
    check("卡在认不出的死亡弹窗上：从最后一次真进度算起",
          round(echofarm.quiet_minutes(datetime(2026, 9, 9, 4, 40, tzinfo=SERVER_TZ))),
          round((datetime(2026, 9, 9, 4, 40) - datetime(2026, 9, 7, 10, 6, 50)).total_seconds() / 60))
    _f3.write_text("\n".join(_NOT) + "\n" + _REAL[3] + "\n", encoding="utf-8")
    check("确认后直接进场算刚动过", round(echofarm.quiet_minutes(datetime(2026, 9, 9, 4, 40, tzinfo=SERVER_TZ))), 1)
finally:
    _wb3._okww_log = _real3

print("\n[开跑时刻读不出来也不当成卡死]")
check("读不出开跑时刻返回 None", echofarm._started_at({"started": "不是时间"}), None)
check("读得出就是那个时刻", echofarm._started_at({"started": "2026-09-09 04:00"}).hour, 4)

print("\n[stopping only the old script: confirmed gone, or the full stop]")
# 2026-10-13: the old script was given a blind two seconds; now it is looked for again.
import ark_relay.features.preupdate.preupdate_okww as _pk  # noqa: E402
_pk_real = _pk._stop_okww_python, _pk.okww_python_pids
_seen = iter([[4242], [4242], []])
_naps = []
_pk._stop_okww_python = lambda: None
_pk.okww_python_pids = lambda: next(_seen)
try:
    check("gone on the third look: True", _real_stop_script(sleep=_naps.append), True)
    check("…after two one-second looks", _naps, [1, 1])
    _pk.okww_python_pids = lambda: None
    _naps.clear()
    check("never readable: False", _real_stop_script(sleep=_naps.append), False)
    check("…after ten looks", len(_naps), 10)
finally:
    _pk._stop_okww_python, _pk.okww_python_pids = _pk_real
_c3 = fresh()
echofarm.start(_c3, 1, "08:30", "天傀劫煞", now=NOW)
_r3 = echofarm.current(_c3.state_dir)
_r3["started"] = "2026-09-09 04:00"
echofarm._store(_c3.state_dir).set("queues", "echo_farm", _r3)
_wb._okww_log = lambda: _logfile
echofarm.stop_okww_script = lambda: launched.append("script") and False
try:
    _b3 = len(launched)
    echofarm.tick(_c3, datetime(2026, 9, 9, 4, 36, tzinfo=SERVER_TZ))
    check("an old script that will not go: the full stop before the relaunch",
          launched[_b3:], ["script", "stop", 1])
finally:
    echofarm.stop_okww_script = lambda: launched.append("script") or True
    _wb._okww_log = _real_log

print("\n[收工那一步本身：先停计划任务，再把 OK-WW 的进程停干净]")
# The real function, not the stub - it is what actually ends the run on the machine.
import subprocess as _sp                                          # noqa: E402
import ark_relay.features.preupdate.preupdate_okww as _pk                            # noqa: E402
_ran, _quiesced = [], []
_real_run, _real_q = _sp.run, _pk._okww_quiesce
class _Done:
    returncode = 0
    stdout = b""
    stderr = b""


_sp.run = lambda *a, **k: (_ran.append(list(a[0]) if a else []), _Done())[1]
_pk._okww_quiesce = lambda *a, **k: _quiesced.append(1)
try:
    # The stub above replaced the module attribute; reload to get the real one back.
    import importlib
    _mod = importlib.reload(sys.modules["ark_relay.features.echofarm.echofarm"])
    _mod.STOP_BAT = str(tmpdir() / "ark-okww-stop.bat")   # never the repo cwd
    _mod.stop_okww()
    check("结束了计划任务", any("schtasks" in c and "/end" in c for c in _ran), True)
    check("任务名对得上", any(_mod.TASK_NAME in c for c in _ran), True)
    check("把 OK-WW 的进程也停了", _quiesced, [1])
    check("游戏也关干净了就不多话", _mod.stop_okww(sleep=lambda _s: None), "")

    print("\n[游戏关不掉就必须说出来，不许报「已收工」]")
    # 2026-09-09: 收工 said 「配置已还原」 twice while 鸣潮 was still on screen. The
    # relay is a service in session 0 and taskkill from there does not reach the game.
    _mod.game_alive = lambda: ["Client-Win64-Shipping.exe"]
    _ran.clear()
    _note = _mod.stop_okww(sleep=lambda _s: None)
    check("话里点名还活着的进程", "Client-Win64-Shipping.exe" in _note, True)
    check("话里说了没关掉、已交给我们这边去关", ("没关掉" in _note, "已交给我们这边去关" in _note), (True, True))
    check("从交互桌面那边补了一刀", any(_mod.STOP_TASK in c for c in _ran), True)

    # docs/SILENT-FAILURES-AUDIT.md echofarm.py:250 - a process list that cannot be
    # read is not a clean desktop.
    print("\n[tasklist fails: never read as 「the game is closed」]")
    _mod = importlib.reload(sys.modules["ark_relay.features.echofarm.echofarm"])
    _mod.STOP_BAT = str(tmpdir() / "ark-okww-stop.bat")
    _sp.run = lambda *a, **k: (_ for _ in ()).throw(OSError("tasklist missing"))
    left = _mod.game_alive()
    check("not empty", bool(left), True)
    check("names no real process (nothing gets killed by that name)",
          any(x in _mod.GAME_PROCS for x in left), False)
    _sp.run = lambda *a, **k: (_ran.append(list(a[0]) if a else []), _Done())[1] \
        if a and a[0] and a[0][0] != "tasklist" else (_ for _ in ()).throw(OSError("tasklist missing"))
    _note = _mod.stop_okww(sleep=lambda _s: None)
    check("stop does not say 收工 cleanly", _note != "" and "程序列表" in _note, True)

    # 2026-10-13 audit: game_alive looked only at the game's process names, so a
    # stop could say clean while OK-WW (pythonw.exe) lived on and later wrote its
    # in-memory config over the restored FarmEchoTask.json.
    print("\n[OK-WW's own pythonw counts as still up]")
    class _Py(_Done):
        stdout = b'[{"ProcessId": 777}]'
    _ran.clear()
    _sp.run = lambda *a, **k: (_ran.append(list(a[0]) if a else []),
                               _Py() if a and any("pythonw.exe" in str(x) for x in a[0]) else _Done())[1]
    check("a live OK-WW script is named", _mod.game_alive(), [_mod.okww_script_name(777)])
    _note = _mod.stop_okww(sleep=lambda _s: None)
    check("stop does not report clean while it lives", "编号 777" in _note, True)
    check("the desktop kill takes it by PID",
          "taskkill /F /PID 777" in Path(_mod.STOP_BAT).read_text(encoding="utf-8"), True)
    _sp.run = lambda *a, **k: (_ for _ in ()).throw(OSError("no pwsh")) \
        if a and any("pythonw.exe" in str(x) for x in a[0]) else _Done()
    check("python list unreadable: not read as gone", _mod.game_alive(), [_mod.UNREADABLE_SCRIPT])
    _sp.run = lambda *a, **k: _Done()
    check("nothing up: clean", _mod.game_alive(), [])
finally:
    _sp.run, _pk._okww_quiesce = _real_run, _real_q

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
