"""A hung Arknights start -> end MAA.exe so AUTO-MAS restarts it now, not 45 minutes later (#137).

2026-11-05 早班: MAA began starting the game at 09:03:23 (asst.log TaskChainStart StartUp), saw
the integrity-check screen at 09:03:45 (GameStartCheckResourceOCR 「资源完整性」), then pressed
「开始唤醒」 every 4.4 s (GameStart, 609 times) until AUTO-MAS's own limit at 09:48:24. Normal
starts take 58-66 s; the retry took 101 s.

Replayed here with that day's line shapes. The clock, the AUTO-MAS snapshot, the process list,
the kill and the log file are stand-ins; nothing touches a real process. Checked:
* the 11-05 hang is ended 5 minutes after the last resource-check screen, not before, once;
* a normal start, a download (GameStartUpdateOCR repeating) and a resource check are not hangs;
* never blind: no snapshot, MAA not 「运行」, no process list, or the MAA that began the start gone;
* a new MAA (banner, new PID) or a closed chain (Completed / Error / Stopped) clears the start;
* other chains' presses do not count; reading resumes across partial lines, a rotated log and a
  relay that starts mid-hang (the backlog read, its first partial line skipped);
* the alarm: group route, the kill-failed title, and plain language for both texts;
* a kill that worked leaves 「超时|MAA|<time>」, so runwatch.retry_clock restarts the shift's clocks.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import texts  # noqa: E402
from ark_relay.core.notify import route_of  # noqa: E402
from ark_relay.features.run import maa_start_watchdog as W  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


T0 = datetime(2026, 11, 5, 9, 3, 23)
PID = 16328


def line(at, rest, pid=PID):
    return f"[{at:%Y-%m-%d %H:%M:%S}.760][INF][Px{pid}][Tx43461] {rest}\n"


def chain(kind, name="StartUp"):
    return f'Assistant::append_callback | {kind} {{"taskchain":"{name}","taskid":1,"uuid":"d912769d7cb0ae0a"}}'


def sub(task, n=1, name="StartUp", kind="SubTaskStart"):
    return ('Assistant::append_callback | ' + kind + ' {"class":"asst::ProcessTask","details":{"action":"ClickSelf",'
            f'"algorithm":"MatchTemplate","exec_times":{n},"max_times":2147483647,'
            '"result":{"rect":[611,652,58,58],"score":0.808239,"template":"GameStart.png"},'
            f'"task":"{task}"}},"first":["StartAtHome","StartWithSanity","SwitchTheme@ToggleSettingsMenu",'
            '"StartUpBegin"],"pre_task":"StartUpBegin","subtask":"ProcessTask",'
            f'"taskchain":"{name}","taskid":0,"uuid":"d912769d7cb0ae0a"}}')


CUR_TASK = '{"class":"asst::ProcessTask","cur_task":"StartUp@GameStart","details":{"cur_retry":0,"retry_times":50}}'
BANNER = ["-----------------------------", "MaaCore Process Start", "Version v6.21.4"]


class World:
    """The machine as the watchdog sees it."""

    def __init__(self, name):
        self.dir = TMP / name
        (self.dir / "debug").mkdir(parents=True)
        self.log = self.dir / "debug" / "asst.log"
        self.log.write_bytes(b"")
        self.clock = T0
        self.snap = {"tasks": [{"task_info": [{"name": "MAA", "status": "运行"},
                                              {"name": "MaaEnd", "status": "等待"}]}]}
        self.procs = [("System", 4), ("MAA.exe", PID), ("dnplayer.exe", 9000)]
        self.kills, self.sent = [], []
        self.kill_result = (True, "")
        self.dog = W.Watchdog(self, self.dir, now=lambda: self.clock, snapshot=lambda: self.snap,
                              processes=lambda: self.procs, kill=self._kill, active=True)

    def _kill(self, pid, image):
        self.kills.append((pid, image))
        return self.kill_result

    def send(self, title, body, alert=False):
        self.sent.append((title, body, alert))
        return []

    def write(self, text):
        with self.log.open("ab") as fh:
            fh.write(text.encode("utf-8"))

    def at(self, t):
        self.clock = t
        return self.dog.tick()


def hang_until(w, end, start=T0, pid=PID, every=4.4):
    """The 11-05 shape up to `end`: start, the resource check at +22 s, presses every 4.4 s."""
    w.write(line(start, chain("TaskChainStart"), pid))
    w.write(line(start + timedelta(seconds=3), sub("StartUpBegin"), pid))
    w.write(line(start + timedelta(seconds=22), sub("GameStartCheckResourceOCR"), pid))
    t, n = start + timedelta(seconds=29), 0
    while t <= end:
        n += 1
        w.write(line(t, sub("GameStart", n), pid))
        w.write(line(t + timedelta(seconds=3), sub("GameStart", n, kind="SubTaskCompleted"), pid))
        w.write(line(t + timedelta(seconds=4), CUR_TASK, pid))
        t += timedelta(seconds=every)
    return n


print("[the 11-05 hang]")
w = World("hang")
check_at = T0 + timedelta(seconds=22)                    # the last resource-check screen, 09:03:45
presses = hang_until(w, check_at + timedelta(seconds=299))
check("4:59 after the last resource check: nothing", w.at(check_at + timedelta(seconds=299)), None)
check("nothing ended yet", w.kills, [])
w.write(line(check_at + timedelta(seconds=299.5), sub("GameStart", presses + 1)))
presses += 1
title = w.at(check_at + timedelta(seconds=300))
check("5:00 after it: MAA is ended", title, texts.MAA_START_STUCK_KILLED)
check("only MAA.exe, by the PID that wrote the start", w.kills, [(PID, "MAA.exe")])
check("one group alarm", [(t, a) for t, _, a in w.sent], [(texts.MAA_START_STUCK_KILLED, True)])
body = w.sent[0][1]
check("the body says when the start began", "MAA 09:03 开始开明日方舟，5 分钟了还没进到游戏里" in body, True)
check("the body counts the presses", f"「开始唤醒」点了 {presses} 次画面都没变" in body, True)
check("the body says how long nothing moved", "最近 5 分钟没在下载更新，也没在校验资源" in body, True)
check("a later look: no second kill, no second alarm", (w.at(check_at + timedelta(seconds=400)), len(w.kills), len(w.sent)),
      (None, 1, 1))

print("[a normal start, a download, a resource check]")
w = World("normal")
w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=29), sub("GameStart"))
        + line(T0 + timedelta(seconds=66), chain("TaskChainCompleted"))
        + line(T0 + timedelta(seconds=67), chain("TaskChainStart", "Fight")))
check("finished in 66 s: nothing open", (w.at(T0 + timedelta(minutes=30)), w.dog.start), (None, None))
w = World("download")
w.write(line(T0, chain("TaskChainStart")))
t = T0 + timedelta(seconds=30)
while t < T0 + timedelta(minutes=20):
    w.write(line(t, sub("GameStartUpdateOCR")))
    t += timedelta(seconds=6)
check("20 minutes of a download: not a hang", w.at(T0 + timedelta(minutes=20)), None)
check("the download moved the clock", w.dog.start.progress > T0 + timedelta(minutes=19), True)
w.write(line(T0 + timedelta(minutes=20, seconds=10), sub("GameStart")))
check("4 minutes after the download ended: still nothing", w.at(T0 + timedelta(minutes=24)), None)
check("5 minutes after: ended", w.at(T0 + timedelta(minutes=25)), texts.MAA_START_STUCK_KILLED)
check("its text: 25 minutes in, quiet for the last 5", "25 分钟了还没进到游戏里" in w.sent[0][1]
      and "最近 5 分钟没在下载更新" in w.sent[0][1], True)

print("[never blind]")
for label, change in (("no snapshot", lambda w: setattr(w, "snap", None)),
                      ("MAA 完成 in the snapshot", lambda w: setattr(w, "snap", {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"}]}]})),
                      ("no process list", lambda w: setattr(w, "procs", None)),
                      ("a different MAA.exe PID", lambda w: setattr(w, "procs", [("MAA.exe", 19236)])),
                      ("PID there but not MAA.exe", lambda w: setattr(w, "procs", [("svchost.exe", PID)]))):
    w = World("blind-" + str(abs(hash(label))))
    hang_until(w, T0 + timedelta(minutes=10))
    change(w)
    check(label + ": nothing ended", (w.at(T0 + timedelta(minutes=10)), w.kills, w.sent), (None, [], []))
w = World("gone")
hang_until(w, T0 + timedelta(minutes=10))
w.procs = [("System", 4)]
w.at(T0 + timedelta(minutes=10))
check("the MAA that began it is gone: the start is forgotten", w.dog.start, None)

print("[a new MAA, a closed chain, other chains]")
w = World("retry")
hang_until(w, T0 + timedelta(minutes=10))
w.write("".join(line(T0 + timedelta(minutes=10, seconds=5), b, 19236) for b in BANNER))
check("a new MAA's banner clears the open start", (w.at(T0 + timedelta(minutes=11)), w.dog.start), (None, None))
w.procs = [("MAA.exe", 19236)]
hang_until(w, T0 + timedelta(minutes=17), start=T0 + timedelta(minutes=11), pid=19236)
check("the retry's own clock: 5:00 after its own check screen",
      (w.at(T0 + timedelta(minutes=11, seconds=22 + 299)), w.at(T0 + timedelta(minutes=11, seconds=22 + 300))),
      (None, texts.MAA_START_STUCK_KILLED))
check("the retry's PID is the one ended", w.kills, [(19236, "MAA.exe")])
w = World("same-pid")
hang_until(w, T0 + timedelta(minutes=10))
w.write("".join(line(T0 + timedelta(minutes=10, seconds=5), b) for b in BANNER))
check("a banner from the same PID (reused) still clears it", (w.at(T0 + timedelta(minutes=11)), w.dog.start), (None, None))
for kind in ("TaskChainError", "TaskChainStopped"):
    w = World("closed-" + kind)
    hang_until(w, T0 + timedelta(minutes=10))
    w.write(line(T0 + timedelta(minutes=10, seconds=1), chain(kind)))
    check(kind + " closes the start", (w.at(T0 + timedelta(minutes=11)), w.dog.start), (None, None))
w = World("other-chain")
w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=40), sub("GameStart", name="Fight"))
        + line(T0 + timedelta(seconds=41), chain("TaskChainCompleted", "Fight")))
w.at(T0 + timedelta(minutes=1))
check("a Fight press and a Fight end do not touch the start", (w.dog.start.presses, w.dog.start.at), (0, T0))

print("[reading asst.log]")
w = World("partial")
whole = line(T0, chain("TaskChainStart"))
w.write(whole[:40])
w.at(T0 + timedelta(seconds=1))
check("half a line: not read yet", w.dog.start, None)
w.write(whole[40:])
w.at(T0 + timedelta(seconds=2))
check("the rest of it: read once", w.dog.start.at if w.dog.start else None, T0)
w = World("rotated")
hang_until(w, T0 + timedelta(minutes=2))
w.at(T0 + timedelta(minutes=2))
w.log.write_bytes(("".join(line(T0 + timedelta(minutes=3, seconds=1), b, 19236) for b in BANNER)
                   + line(T0 + timedelta(minutes=4), chain("TaskChainStart"), 19236)).encode())
w.at(T0 + timedelta(minutes=4, seconds=10))
check("a rotated log is read from its start", (w.dog.start.pid, w.dog.start.at), (19236, T0 + timedelta(minutes=4)))
w = World("midway")
filler = line(T0 - timedelta(hours=1), "x" * 300)
w.write(filler * (W.BACKLOG_BYTES // len(filler) + 50))
hang_until(w, T0 + timedelta(minutes=6))
check("relay started mid-hang: the backlog finds the start and ends it", w.at(T0 + timedelta(minutes=6)),
      texts.MAA_START_STUCK_KILLED)
w = World("old-open")
w.write(line(T0 - timedelta(hours=12), chain("TaskChainStart"), 777))
w.procs = [("MAA.exe", PID)]
check("an old start left open by a MAA that is gone: nothing", (w.at(T0), w.kills), (None, []))
w = World("off")
w.dog.active = False
hang_until(w, T0 + timedelta(minutes=10))
check("not on Windows: never looks", (w.at(T0 + timedelta(minutes=10)), w.kills), (None, []))

print("[the alarm]")
w = World("kill-fails")
w.kill_result = (False, "退出码 128")
hang_until(w, T0 + timedelta(minutes=6))
check("kill failed: its own title", w.at(T0 + timedelta(minutes=6)), texts.MAA_START_STUCK_KILL_FAILED)
check("kill failed: says so", "结束 MAA 没成功（退出码 128）" in w.sent[0][1], True)
check("kill failed: still one alarm", (w.at(T0 + timedelta(minutes=7)), len(w.sent)), (None, 1))
for t in (texts.MAA_START_STUCK_KILLED, texts.MAA_START_STUCK_KILL_FAILED):
    check(f"{t}: the group route", route_of(t, alert=True), "group")
for b in (texts.maa_start_stuck_body("09:03", 5, 69, True, "", 5),
          texts.maa_start_stuck_body("09:03", 25, 0, True, "", 5),
          texts.maa_start_stuck_body("09:03", 5, 69, False, "结束命令 30 秒没返回", 5)):
    check("plain language: " + b[:24], texts.plain(b), [])

print("[the restart mark: the shift's clocks restart from the kill, as after AUTO-MAS's own timeout]")
import types  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.core.statestore import StateStore  # noqa: E402
from ark_relay.features.run import runwatch  # noqa: E402
w = World("mark")
w.dog.state_dir = w.dir / "state"
w.dog.state_dir.mkdir()
hang_until(w, T0 + timedelta(minutes=6))
kill_at = T0 + timedelta(minutes=6)
w.at(kill_at)
store = StateStore(w.dog.state_dir)
check("the kill leaves the timeout mark of its own moment", store.get("marks", "alerted:2026-11-05"),
      ["超时|MAA|09:09:23"])
eng = types.SimpleNamespace(state=types.SimpleNamespace(store=store))
due = datetime(2026, 11, 5, 9, 0, tzinfo=SERVER_TZ)
check("runwatch.retry_clock restarts the shift from it", runwatch.retry_clock(eng, due, 87),
      datetime(2026, 11, 5, 9, 9, 23, tzinfo=SERVER_TZ))
w = World("mark-failed-kill")
w.dog.state_dir = w.dir / "state"
w.dog.state_dir.mkdir()
w.kill_result = (False, "退出码 128")
hang_until(w, T0 + timedelta(minutes=6))
w.at(T0 + timedelta(minutes=6))
check("a kill that failed leaves no mark (nothing restarted)",
      StateStore(w.dog.state_dir).get("marks", "alerted:2026-11-05"), None)

print("\n[audit 11-08 B-05: StartUp's end lost to a rotation does not get a fighting MAA killed]")
w = World("rotated-mid-start")
w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=30), sub("StartUpBegin")))
w.at(T0 + timedelta(seconds=31))
# MAA writes StartUp's completion into asst.log, then rotates it before the next read.
w.write(line(T0 + timedelta(seconds=60), chain("TaskChainCompleted")))
w.log.rename(w.log.with_name("asst.bak.log"))
w.log.write_bytes(line(T0 + timedelta(seconds=70), sub("FightBegin", name="Fight")).encode())
w.at(T0 + timedelta(seconds=75))
check("the completion line is read from asst.bak.log", w.dog.start, None)
w = World("rotated-lost")
w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=30), sub("StartUpBegin")))
w.at(T0 + timedelta(seconds=31))
w.log.write_bytes(line(T0 + timedelta(seconds=70), chain("TaskChainStart", "Fight")).encode())   # no bak at all
w.at(T0 + timedelta(seconds=75))
check("no completion anywhere, but a Fight chain of the same MAA began: start closed", w.dog.start, None)
check("so nothing is killed 10 minutes into the fight", (w.at(T0 + timedelta(minutes=10)), w.kills), (None, []))
w = World("other-pid-chain")
w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=5), chain("TaskChainStart", "Fight"), pid=999))
w.at(T0 + timedelta(seconds=6))
check("another MAA's chain does not close this start", w.dog.start and w.dog.start.pid, PID)

print("all checks passed" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
