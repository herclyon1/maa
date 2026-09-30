"""The red button on the phone must not say 「已停一切」 unless it checked.

The conclusion of 2026-08-26, in the user's own words, was 「你没有进行任何有效的停止
行为，全是我手动关的」. The phone button kept that shape: stop through the AUTO-MAS
API, run taskkill twice, then return a hard-coded success - no look at what was
actually left, and the message went straight out as a push.

Two things make that worse than doing nothing. AUTO-MAS retries the whole queue when
one of its members is killed under it, so "killed it twice" says nothing about the
state half a minute later; and the process list it did surface never contained
Wuthering Waves' real process names, which is exactly how the 08-26 check passed
while the game was running.

So: verify, retry once, and tell the truth either way.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import commands

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


print("[要杀要查的名单里必须有鸣潮的三个真名——08-26 的假确认就漏在这里]")
for exe in ("Wuthering Waves.exe", "Client-Win64-Shipping.exe", "KRSDKExternal.exe",
            "ok-ww.exe", "MAA.exe", "MaaEnd.exe", "Endfield.exe", "dnplayer.exe"):
    check(f"名单含 {exe}", exe in commands._ESTOP_EXES, True)
print("  ✓ 终末地启动器 Games.exe 也在" if "Games.exe" in commands._ESTOP_EXES else "")
check("终末地启动器也在", "Games.exe" in commands._ESTOP_EXES, True)


class Rig:
    """Stands in for the four actions: API stop, kill, who is alive, which AUTO-MAS tasks are unfinished.

    task_rounds are the successive answers to the AUTO-MAS task check (None =
    unreadable); when omitted the answer is "no tasks", so the older scenarios
    exercise the process check alone."""

    def __init__(self, alive_rounds, task_rounds=()):
        self.alive_rounds = list(alive_rounds)
        self.task_rounds = list(task_rounds)
        self.kills = 0
        self.stops = 0
        self.slept = 0
        self.state = tmpdir()

    def install(self):
        commands._estop_stop_via_mas = lambda: (setattr(self, "stops", self.stops + 1),
                                                ["早班"])[1]
        commands._estop_kill = lambda: setattr(self, "kills", self.kills + 1)
        commands._estop_alive = lambda: (self.alive_rounds.pop(0)
                                         if self.alive_rounds else [])
        commands._estop_live_tasks = lambda: (self.task_rounds.pop(0)
                                              if self.task_rounds else [])
        return self

    def sleep(self, n):
        self.slept += n

    def run(self):
        return commands.estop(sleep=self.sleep, state_dir=self.state)


real = (commands._estop_stop_via_mas, commands._estop_kill, commands._estop_alive,
        commands._estop_live_tasks, commands._mas)

print("\n[一轮就干净：说成功，而且说的是「确认没了」不是「已经杀过了」]")
r = Rig([[]]).install()
ok, msg = r.run()
check("返回成功", ok, True)
check("话里说了确认", "确认没了" in msg, True)
check("只停了一轮接口", r.stops, 1)

print("\n[第一次查还有残留：必须再停一轮，然后才许说成功]")
r = Rig([["MAA.exe"], []]).install()
ok, msg = r.run()
check("返回成功", ok, True)
check("停了两轮接口", r.stops, 2)

print("\n[两轮都停不住：不许说成功，要点名还活着谁，并指到 estop.sh]")
r = Rig([["Client-Win64-Shipping.exe"], ["Client-Win64-Shipping.exe"]]).install()
ok, msg = r.run()
check("返回失败", ok, False)
check("不含「已停一切」", "已停一切" in msg, False)
check("点名了还活着的（用中文说游戏名）", "鸣潮" in msg, True)
check("指到电脑上的紧急停止脚本", "紧急停止" in msg, True)
check("说清为什么中继自己停不住", "整队重跑" in msg, True)
check("不许在推送里出现进程名", "Client-Win64-Shipping" in msg, False)

print("\n[进程表读不到时按「还活着」算——不知道不许说成全清]")
r = Rig([["进程表读不到"], ["进程表读不到"]]).install()
ok, msg = r.run()
check("返回失败", ok, False)
check("话里说了读不到", "进程表读不到" in msg, True)

print("\n[09-30 早上那样：游戏都杀没了，AUTO-MAS 已经换到下一个脚本在跑——再停一轮，清了才说成功]")
r = Rig([[], []], [[("t-2", "MaaEnd")], []]).install()
ok, msg = r.run()
check("返回成功", ok, True)
check("因为 AUTO-MAS 还有任务而停了第二轮", r.stops, 2)
check("成功的话里也说了 AUTO-MAS 没有在跑的任务", "AUTO-MAS 也没有在跑的任务了" in msg, True)

print("\n[两轮后 AUTO-MAS 还记着有任务在跑：不许说成功，点名那个任务]")
r = Rig([[], []], [[("t-2", "早班")], [("t-3", "早班")]]).install()
ok, msg = r.run()
check("返回失败", ok, False)
check("以「没停干净：」开头", msg.startswith("没停干净："), True)
check("点名了 AUTO-MAS 还在跑的任务", "AUTO-MAS 还记着有任务在跑：早班" in msg, True)
check("不含「已停一切」", "已停一切" in msg, False)
check("指到电脑上的紧急停止脚本", "紧急停止" in msg, True)
check("说清为什么中继自己停不住", "整队重跑" in msg, True)

print("\n[进程和任务都还在：两样都点名，游戏用中文名]")
r = Rig([["MaaEnd.exe"], ["MaaEnd.exe"]], [[("t", "早班")], [("t", "早班")]]).install()
ok, msg = r.run()
check("返回失败", ok, False)
check("游戏用中文名", "终末地的脚本" in msg, True)
check("任务也点名", "早班" in msg, True)
check("不出现进程名", "MaaEnd.exe" in msg, False)

print("\n[AUTO-MAS 的任务列表读不到：按「还在跑」算，不许说全清]")
r = Rig([[], []], [None, None]).install()
ok, msg = r.run()
check("返回失败", ok, False)
check("再停了一轮", r.stops, 2)
check("以「没停干净：」开头", msg.startswith("没停干净："), True)
check("说了问不到", "问不到 AUTO-MAS 还有没有任务在跑" in msg, True)

print("\n[按下的时间写进 estop-windows.json：开始和结束都有，读回来是一段]")
r = Rig([[]]).install()
r.run()
rows = json.loads((r.state / commands.ESTOP_WINDOWS_FILE).read_text(encoding="utf-8"))
check("记了一笔", len(rows), 1)
check("有开始也有结束", sorted(rows[0]), ["end", "start"])
wins = commands.estop_windows(r.state)
check("读回来一段", len(wins), 1)
check("开始不晚于结束", wins[0][0] <= wins[0][1], True)
check("带时区（北京时间）", wins[0][0].utcoffset().total_seconds(), 8 * 3600)

print("\n[按了没写完（中继中途死了）：没有结束的按开始后 10 分钟算]")
d = tmpdir()
(d / commands.ESTOP_WINDOWS_FILE).write_text(
    json.dumps([{"start": "2026-09-30T09:46:40+08:00"}]), encoding="utf-8")
w = commands.estop_windows(d)
check("结束 = 开始 + 10 分钟", (w[0][1] - w[0][0]).total_seconds(), 600.0)
check("没有文件时是空的", commands.estop_windows(tmpdir()), [])
(d / commands.ESTOP_WINDOWS_FILE).write_text("{坏", encoding="utf-8")
check("坏文件不抛异常", commands.estop_windows(d), [])

print("\n[只留最近 20 笔]")
d = tmpdir()
for _ in range(25):
    Rig([[]]).install()
    commands.estop(sleep=lambda n: None, state_dir=d)
check("20 笔", len(json.loads((d / commands.ESTOP_WINDOWS_FILE).read_text(encoding="utf-8"))), 20)

(commands._estop_stop_via_mas, commands._estop_kill, commands._estop_alive,
 commands._estop_live_tasks, commands._mas) = real

print("\n[停的时候发的是 AUTO-MAS 在跑任务的 taskId，不是脚本 / 队列编号（09-30 的根因）]")
calls = []


def fake_mas(path, body=None, timeout=20):
    calls.append((path, body))
    if path == "/api/scripts/get":
        return {"data": {"script-uuid": {"Info": {"Name": "OK-WW"}}}}
    if path == "/api/queue/get":
        return {"data": {"queue-uuid": {"Info": {"Name": "早班"}}}}
    return {"code": 200, "message": "操作成功"}


commands._mas = fake_mas
commands._estop_live_tasks = lambda: [("dispatch-abc", "MaaEnd"), ("dispatch-def", "早班")]
got = commands._estop_stop_via_mas()
check("返回停到的标签", got, ["MaaEnd", "早班"])
check("按 taskId 逐个发停止", calls, [("/api/dispatch/stop", {"taskId": "dispatch-abc"}),
                                    ("/api/dispatch/stop", {"taskId": "dispatch-def"})])
check("没去读脚本和队列编号", any(p in ("/api/scripts/get", "/api/queue/get") for p, _ in calls), False)

calls.clear()
commands._estop_live_tasks = lambda: None
got = commands._estop_stop_via_mas()
check("读不到在跑的任务：不谎称停到了什么", got, [])
check("读不到时退回按脚本 / 队列编号发（无害）", [b for p, b in calls if p == "/api/dispatch/stop"],
      [{"taskId": "script-uuid"}, {"taskId": "queue-uuid"}])
commands._mas, commands._estop_live_tasks = real[4], real[3]

print("\n[读 AUTO-MAS 在跑的任务：用 GET 读 runtime-snapshot，只收没结束的，口径和 engine 同一个]")
import urllib.request as _ur                                      # noqa: E402
real_urlopen = _ur.urlopen
seen_req = []


class Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


SNAP = {"tasks": [
    {"taskId": "done-1", "mode": "AutoProxy",
     "task_info": [{"name": "OK-WW", "status": "完成"}]},
    {"taskId": "live-2", "mode": "AutoProxy",
     "task_info": [{"name": "OK-WW", "status": "完成"}, {"name": "MaaEnd", "status": "运行"}]},
    {"taskId": "fresh-3", "mode": "早班", "task_info": []},
]}


def fake_urlopen(req, timeout=None):
    seen_req.append(req)
    return Resp(json.dumps(SNAP, ensure_ascii=False).encode("utf-8"))


_ur.urlopen = fake_urlopen
live = commands._estop_live_tasks()
check("只收没结束的两个", [t for t, _ in live], ["live-2", "fresh-3"])
check("标签用任务名以「、」连", live[0][1], "OK-WW、MaaEnd")
check("没有任务名时用 mode", live[1][1], "早班")
check("是 GET（传的是地址，不带请求体）", isinstance(seen_req[0], str), True)
check("读的是 runtime-snapshot", seen_req[0].endswith("/api/dispatch/runtime-snapshot"), True)
from ark_relay import engine as _engine                           # noqa: E402
check("和 engine 的判断一致", bool(live), _engine._judge_snapshot(SNAP))


def _down(*a, **k):
    raise OSError("连不上")


_ur.urlopen = _down
check("读不到时返回 None（不是空列表）", commands._estop_live_tasks(), None)
_ur.urlopen = real_urlopen

print("\n[查活着谁：认名字不分大小写，一个不落]")
import subprocess as _sp                                          # noqa: E402
import os as _os                                                  # noqa: E402
real_run, real_name = _sp.run, _os.name
_os.name = "nt"


class Out:
    def __init__(self, text):
        self.stdout = text.encode("utf-8")


_sp.run = lambda *a, **k: Out('"MAA.exe","1","Console"\n"client-win64-shipping.exe","2","C"\n')
check("大小写不同也认得出", set(commands._estop_alive()),
      {"MAA.exe", "Client-Win64-Shipping.exe"})
_sp.run = lambda *a, **k: Out('"explorer.exe","1","Console"\n')
check("干净时是空的", commands._estop_alive(), [])


def _boom(*a, **k):
    raise OSError("tasklist 挂了")


_sp.run = _boom
check("读不到时不许返回空", commands._estop_alive(), ["读不到正在运行的程序列表"])
_sp.run, _os.name = real_run, real_name

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
