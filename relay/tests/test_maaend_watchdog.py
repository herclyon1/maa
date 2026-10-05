"""MaaEnd hung -> end MaaEnd.exe so AUTO-MAS retries now, not 45 minutes later.

2026-10-01 15:30:03: MaaEnd was on 「信用点购物」 when its plugin
D:\\ark\\maaend\\agent\\go-service.exe crashed. go-service.stderr.log line 1 was
`Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456`; maafw.log never
gained another line, MaaEnd.exe sat there alive, and only AUTO-MAS's 45-minute
limit ended it at 16:10:00. 2026-09-28 11:22:10 had the same 41-minute gap.
Normal runs never go more than 65 s between two maafw.log lines.

Replayed here with that day's shape. The clock, the AUTO-MAS snapshot, the
process list, the kill and the files are all stand-ins; nothing touches a real
process.
"""
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import collect_watch, maaend_watchdog, texts
from ark_relay.notify import route_of

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


CRASH_LINE = "Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456"
RUNNING = {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"},
                                    {"name": "OK-WW", "status": "异常"},
                                    {"name": "MaaEnd", "status": "运行"}]}]}
WAITING = {"tasks": [{"task_info": [{"name": "MAA", "status": "运行"},
                                    {"name": "MaaEnd", "status": "等待"}]}]}
DONE = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "完成"}]}]}
MAAEND_PID = 21260
ALL_UP = [("System", 4), ("Endfield.exe", 18800), ("MaaEnd.exe", MAAEND_PID),
          ("go-service.exe", 21932), ("cpp-algo.exe", 21940), ("python.exe", 9000)]
NO_GO = [p for p in ALL_UP if p[0] != "go-service.exe"]


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []


class Rig:
    """One watchdog with every outside thing replaced."""

    def __init__(self, *, snap=RUNNING, procs=ALL_UP, kill_ok=True, active=True, paths=None):
        self.t = 1000.0
        self.snap, self.procs = snap, procs
        self.kill_ok = kill_ok
        self.killed = []
        self.notes = Notes()
        self.debug = tmpdir() / "debug"
        self.debug.mkdir()
        self.stderr = self.debug / "go-service.stderr.log"
        self.stderr.write_text("", encoding="utf-8")
        self.lines = 0
        self.stamp = "2026-10-01 15:20:00"
        agent = str(self.debug.parent / "agent")
        self.paths = paths if paths is not None else {21932: os.path.join(agent, "go-service.exe"),
                                                       21940: os.path.join(agent, "cpp-algo.exe")}
        self.images = []
        self.dog = maaend_watchdog.Watchdog(
            self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: self.snap,
            processes=lambda: self.procs, kill=self._kill, plugin_paths=lambda: self.paths,
            active=active)

    def _kill(self, pid, image):
        self.killed.append(pid)
        self.images.append(image)
        return (True, "") if self.kill_ok else (False, "退出码 128")

    def step(self, seconds, *, new_lines=0, stamp=None):
        """Let `seconds` pass, with `new_lines` appended to maafw.log meanwhile."""
        self.t += seconds
        self.lines += new_lines
        if stamp:
            self.stamp = stamp
        return self.dog.tick(self.lines, self.stamp)

    def run_for(self, seconds, every=60, **kw):
        out = []
        for _ in range(int(seconds // every)):
            if r := self.step(every, **kw):
                out.append(r)
        return out


print("[2026-10-01：MaaEnd 在跑，go-service 崩溃 → 结束 MaaEnd 一次，群里一条报警]")
r = Rig()
r.run_for(240, new_lines=40)                       # MaaEnd running fine for 4 minutes
check("崩溃前什么都不做", (r.killed, r.notes.sent), ([], []))
r.stderr.write_text(CRASH_LINE + "\nPC=0x7ffc630b5456\n\ngoroutine 1 gp=0xc000002380 m=0 mp=0x1 "
                    "[syscall, 5 minutes]:\n", encoding="utf-8")
r.step(60)
check("结束的是 MaaEnd.exe（和它的两个插件），没碰游戏", r.killed, [MAAEND_PID, 21932, 21940])
check("只发一条", len(r.notes.sent), 1)
title, body, alert = r.notes.sent[0]
check("标题", title, texts.MAAEND_STUCK_KILLED)
check("是真报警", alert, True)
check("走群机器人", route_of(title, alert=True), "group")
check("正文有错误码 0xc0000005", "0xc0000005" in body, True)
check("正文说已结束", "已结束 MaaEnd" in body, True)
check("正文是人话", texts.plain(body), [])
r.run_for(600)
check("同一个 MaaEnd 不再结束第二次", r.killed, [MAAEND_PID, 21932, 21940])
check("也不再报第二次", len(r.notes.sent), 1)

print("\n[maafw.log 10 分钟没有新行 → 结束 + 报警；9 分钟不动作]")
r = Rig()
r.run_for(300, new_lines=50, stamp="2026-10-01 15:30:03")
r.run_for(540)                                     # 9 minutes with no new line
check("9 分钟：不动作", (r.killed, r.notes.sent), ([], []))
r.step(60)
check("10 分钟：结束 MaaEnd", r.killed[:1], [MAAEND_PID])
check("报警一条", len(r.notes.sent), 1)
body = r.notes.sent[0][1] if r.notes.sent else ""
check("正文写 10 分钟和最后一行时间", ("10 分钟" in body, "15:30:03" in body), (True, True))
check("正文是人话", texts.plain(body), [])

print("\n[正常：每 65 秒一行新日志 → 不动作]")
r = Rig()
r.run_for(65 * 40, every=65, new_lines=1)
check("43 分钟里一次都没结束", (r.killed, r.notes.sent), ([], []))

print("\n[MaaEnd 不是「运行」→ 不判、不杀]")
for label, snap in (("等待", WAITING), ("完成", DONE), ("问不到快照", None)):
    r = Rig(snap=snap)
    r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    r.run_for(1800)
    check(f"{label}：30 分钟没新行、stderr 有崩溃，也不动作", (r.killed, r.notes.sent), ([], []))

print("\n[从等待变成运行：10 分钟从变成运行那一刻算，不从上一行日志算]")
r = Rig(snap=WAITING)
r.run_for(1800)
r.snap = RUNNING
r.run_for(120, new_lines=5)                        # first sight at +60 s, a new line at +120 s
r.run_for(540)                                     # +660 s: 9 minutes since that line
check("最后一行后 9 分钟：不动作", r.killed, [])
r.step(60)
check("满 10 分钟：结束", r.killed[:1], [MAAEND_PID])

print("\n[go-service 不在：只见到一次不动作，隔 ≥60 秒连续两次才动作]")
r = Rig()
r.run_for(240, new_lines=20)
r.procs = NO_GO
r.step(60, new_lines=5)
check("第一次不在：不动作", r.killed, [])
r.procs = ALL_UP
r.step(60, new_lines=5)
r.procs = NO_GO
r.step(30, new_lines=5)
check("中间又见到了，重新数：不动作", r.killed, [])
r.step(30, new_lines=5)
check("隔 30 秒第二次不在：还不动作", r.killed, [])
r.step(30, new_lines=5)
check("隔 ≥60 秒第二次不在：结束（插件已不在，只结束 MaaEnd 和 cpp-algo）", r.killed, [MAAEND_PID, 21940])
body = r.notes.sent[0][1] if r.notes.sent else ""
check("正文说插件不在了", "go-service.exe 已经不在了" in body, True)
check("正文是人话", texts.plain(body), [])

print("\n[MaaEnd 刚起不满 3 分钟：插件还没起来是正常的 → 不动作]")
r = Rig(procs=[p for p in NO_GO if p[0] != "cpp-algo.exe"])
r.run_for(120, new_lines=10)
check("2 分钟里不在两次：不动作", r.killed, [])
r.run_for(180, new_lines=10)
check("满 3 分钟后再连续两次不在：动作", r.killed[:1], [MAAEND_PID])

print("\n[MaaEnd 换了新的一次（PID 变了）：旧的计时和旧的崩溃都不算]")
r = Rig()
r.run_for(240, new_lines=20)
r.procs = [("MaaEnd.exe", 30000)]
r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")   # the previous run's dump, still in the file
r.step(60)
check("新 PID 第一次见到时 stderr 已有的内容不算", r.killed, [])
r.stderr.write_text("", encoding="utf-8")                   # go-service relaunched: file rewritten
r.step(60, new_lines=5)
r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
r.step(60, new_lines=5)
check("重写后的新崩溃照样认得出", r.killed[:1], [30000])

print("\n[结束失败 → 报警写没结束成]")
r = Rig(kill_ok=False)
r.run_for(240, new_lines=20)
r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
r.step(60)
check("试着结束了一次", r.killed, [MAAEND_PID])
title, body, alert = r.notes.sent[0] if r.notes.sent else ("", "", False)
check("标题说没能结束", title, texts.MAAEND_STUCK_KILL_FAILED)
check("是真报警，走群", (alert, route_of(title, alert=True)), (True, "group"))
check("正文写结束没成功和原因", ("结束 MaaEnd 没成功" in body, "退出码 128" in body), (True, True))
check("正文是人话", texts.plain(body), [])
r.run_for(600)
check("同一个 PID 不再试、不再报", (len(r.killed), len(r.notes.sent)), (1, 1))

print("\n[不是 Windows：整个看门狗不动作]")
r = Rig(active=False)
r.run_for(240, new_lines=20)
r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
r.run_for(1800)
check("什么都不做", (r.killed, r.notes.sent), ([], []))

print("\n[MaaEnd.exe 不在：没东西可结束]")
r = Rig(procs=[p for p in ALL_UP if p[0] != "MaaEnd.exe"])
r.run_for(1800)
check("不动作", r.killed, [])

print("\n[maafw.log 的行数：跟轮转，变短但 bak 里有新行也算有新行]")


class _Cfg:
    pass


cfg = _Cfg()
cfg.maaend_dir = str(tmpdir())
cfg.state_dir = tmpdir()  # collect_watch.start prunes old task shots there
(Path(cfg.maaend_dir) / "debug").mkdir()
lp = Path(cfg.maaend_dir) / "debug" / "maafw.log"
lp.write_text("[2026-10-01 15:29:00.000][INF] a\n" * 50, encoding="utf-8")
w = collect_watch.Watcher(cfg, Notes())
w.poll()
seen = w.lines_seen
check("读到 50 行", seen, 50)
check("最后一行的时间", w.last_stamp, "2026-10-01 15:29:00")
with lp.open("a", encoding="utf-8") as fh:
    fh.write("[2026-10-01 15:30:03.511][INF] b\n")
lp.rename(lp.parent / "maafw.bak.2026.10.01-15.30.04.000.log")
lp.write_text("", encoding="utf-8")                # MaaFW started over; the new file is empty
w.poll()
check("新文件更短，旧文件尾巴上那一行算新行", w.lines_seen, seen + 1)
check("最后一行时间跟着更新", w.last_stamp, "2026-10-01 15:30:03")
w.poll()
check("没有新内容就不涨", w.lines_seen, seen + 1)

print("\n[监听线程：日志不动也每隔一段时间叫一次看门狗]")
ticks = []


class _FakeDog:
    def __init__(self, *a, **kw):
        pass

    def tick(self, lines, stamp):
        ticks.append(lines)


real_dog, real_tick = maaend_watchdog.Watchdog, collect_watch.TICK_SECONDS
maaend_watchdog.Watchdog, collect_watch.TICK_SECONDS = _FakeDog, 0.2
try:
    check("挂上了", collect_watch.start(cfg, Notes()), True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(ticks) < 3:
        time.sleep(0.1)
    check("文件一动不动，看门狗也被叫到了至少 3 次", len(ticks) >= 3, True)
finally:
    maaend_watchdog.Watchdog, collect_watch.TICK_SECONDS = real_dog, real_tick
check("线程还活着", any(t.name == "collect-watch" for t in threading.enumerate()), True)

print("\n[taskkill carries the image name, so a reused PID is never someone else]")
r = Rig()
r.run_for(240, new_lines=40)
r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
r.step(60)
check("names passed with each PID", r.images, ["MaaEnd.exe", "go-service.exe", "cpp-algo.exe"])

print("\n[a plugin-named program outside <maaend>\\agent is left alone]")
r = Rig(paths={21932: "C:\\other\\go-service.exe", 21940: str(Path(tmpdir()) / "agent" / "cpp-algo.exe")})
r.run_for(240, new_lines=40)
r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
r.step(60)
check("only MaaEnd.exe ended", r.killed, [MAAEND_PID])
r = Rig()
r.paths = {21932: str(r.debug.parent / "agent2" / "go-service.exe"),
           21940: str(r.debug.parent / "agent" / "cpp-algo.exe")}
r.run_for(240, new_lines=40)
r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
r.step(60)
check("a sibling folder agent2 is not agent", r.killed, [MAAEND_PID, 21940])
r = Rig(paths={})
r.run_for(240, new_lines=40)
r.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
r.step(60)
check("paths unreadable -> plugins not ended", r.killed, [MAAEND_PID])

print("\n[not one maafw.log line read for this MaaEnd: report once, never kill]")
r = Rig()
out = r.run_for(1200)                              # 20 minutes, no line at all
check("nothing ended", r.killed, [])
check("one alarm, the blind one", [t for t, _, _ in r.notes.sent], [texts.MAAEND_WATCH_BLIND])
check("it is a group alarm", route_of(texts.MAAEND_WATCH_BLIND, alert=True), "group")
# One fault, one push - per MaaEnd, not per PID number for ever: once MaaEnd is gone,
# a later one that drew the same PID (Windows reuses them) and cannot be read either
# is a second fault and rings again (until 2026-10-06 the blind mark was never
# forgotten, so it stayed silent).
r.procs = [p for p in ALL_UP if p[0] != "MaaEnd.exe"]
r.step(60)
r.procs = ALL_UP
r.run_for(1200)
check("a later MaaEnd with the same PID, unreadable too: rings again",
      [t for t, _, _ in r.notes.sent], [texts.MAAEND_WATCH_BLIND, texts.MAAEND_WATCH_BLIND])
check("still nothing ended", r.killed, [])
r = Rig()
r.run_for(120, new_lines=5)
r.run_for(660)
check("lines once, then silence -> the normal stall kill", r.killed, [MAAEND_PID, 21932, 21940])

print("\n[_taskkill reads success from the output: a filter that matches nothing still exits 0]")
real_run = maaend_watchdog.subprocess.run
calls = []


def fake_run(out, rc=0):
    def run(args, **kw):
        calls.append(args)
        return type("R", (), {"returncode": rc, "stdout": out.encode("gbk"), "stderr": b""})()
    return run


try:
    maaend_watchdog.subprocess.run = fake_run("成功: 已终止 PID 为 21260 的进程。")
    check("成功 -> ended", maaend_watchdog._taskkill(21260, "MaaEnd.exe"), (True, ""))
    check("filters on PID and image", calls[-1], ["taskkill", "/F", "/FI", "PID eq 21260", "/FI", "IMAGENAME eq MaaEnd.exe"])
    maaend_watchdog.subprocess.run = fake_run("信息: 没有运行的带有指定标准的任务。")
    check("no match, exit 0 -> not ended", maaend_watchdog._taskkill(21260, "MaaEnd.exe")[0], False)
    maaend_watchdog.subprocess.run = fake_run("错误: 无法终止", rc=128)
    check("exit 128 -> not ended", maaend_watchdog._taskkill(21260, "MaaEnd.exe"), (False, "退出码 128"))
finally:
    maaend_watchdog.subprocess.run = real_run

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
