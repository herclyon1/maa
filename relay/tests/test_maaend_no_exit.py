"""MaaEnd finished every task and never exited: end it 30 s after tasks-completed.

2026-10-01: MaaEnd logged 「kind: tasks-completed」 at 16:58:22 and closed the
game, but never wrote 「自动执行任务完成，关闭自身」 nor exited; AUTO-MAS kept it
「运行」 until 17:27:43. Normal runs exit 0.7-4.0 s after tasks-completed. The
user agreed the rule on 2026-10-01 20:35 (D129). MXU lines verbatim from
D:\\ark\\maaend\\debug\\2026-10-01-6.log and 2026-09-30-4.log.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import maaend_watchdog, texts

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []


RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
WAITING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "完成"}]}]}
PID = 11224
PROCS = [("Endfield.exe", 18800), ("MaaEnd.exe", PID), ("System", 4)]   # plugins already gone


class Rig:
    def __init__(self, mxu_lines, snap=RUNNING):
        self.debug = tmpdir() / "debug"
        self.debug.mkdir()
        (self.debug / "go-service.stderr.log").write_text("", encoding="utf-8")
        (self.debug / "2026-10-01-6.log").write_text("\n".join(mxu_lines) + "\n", encoding="utf-8")
        self.t, self.wall = 1000.0, datetime(2026, 10, 1, 16, 58, 22)
        self.snap, self.killed, self.notes = snap, [], Notes()
        self.dog = maaend_watchdog.Watchdog(
            self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: self.snap,
            processes=lambda: PROCS, kill=self._kill, wallclock=lambda: self.wall,
            plugin_paths=lambda: {}, active=True)
        self.dog.tick(1, "")                          # first sight of this MaaEnd

    def _kill(self, pid, image):
        self.killed.append((pid, image))
        return True, ""

    def at(self, hh, mm, ss):
        new = datetime(2026, 10, 1, hh, mm, ss)
        self.t += (new - self.wall).total_seconds()
        self.wall = new
        return self.dog.tick(1, "")


HUNG = ["2026-10-01 16:58:19 DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: task-progress",
        "2026-10-01 16:58:22 DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: tasks-completed"]
NORMAL = ["2026-09-30 18:18:35 INFO  [App] 自动执行任务完成，关闭自身",
          "2026-09-30 18:18:35 DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: tasks-completed"]

print("[10-01 16:58:22 replay: no closing line, still running]")
r = Rig(HUNG)
check("16:58:40 (18 s): wait", (r.at(16, 58, 40), r.killed), (None, []))
title = r.at(16, 58, 53)
check("16:58:53 (31 s): MaaEnd.exe ended by PID + name", r.killed, [(PID, "MaaEnd.exe")])
check("one alarm", len(r.notes.sent), 1)
check("title", title, texts.MAAEND_STUCK_KILLED)
check("reason names the completion time and the wait",
      "所有任务 16:58:22 已完成，31 秒后仍没有自己退出" in r.notes.sent[0][1], True)
check("is a group alarm", r.notes.sent[0][2], True)
r.at(16, 59, 30)
check("not ended twice", len(r.killed), 1)

print("\n[normal end: closing line written (same second, before tasks-completed)]")
r = Rig(NORMAL)
r.t += 65
r.wall = datetime(2026, 9, 30, 18, 19, 40)
check("65 s later: nothing", (r.dog.tick(1, ""), r.killed), (None, []))

print("\n[AUTO-MAS no longer says 运行 -> nothing]")
r = Rig(HUNG, snap=WAITING)
check("past 30 s: nothing", (r.at(16, 59, 30), r.killed), (None, []))

print("\n[no tasks-completed yet -> this rule does nothing]")
r = Rig(["2026-10-01 16:30:00 DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: task-progress"])
check("16:59:30: nothing from this rule", (r.at(16, 59, 30), r.killed), (None, []))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
