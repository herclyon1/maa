"""MaaEnd finished every task but did not exit: ask MXU to stop once, kill only if that fails.

MXU leaving on the request is a fault that fixed itself: one WARNING marked
errwatch.recovered() (daily report, 自己好了, not pushed) whose errwatch door writes
one 「自愈待查」 red item to the technical log (techlog.self_heal, commit dae12439),
so a session still looks at it. The kill fallback is the 「MaaEnd 卡死」 WARNING
that errwatch pushes to the group.

Upstream MistEO/MXU#371 (open, no fix as of v2.7.1, the version installed on the
machine - MaaEnd.exe FileVersion 2.7.1): with --quit-after-run, MXU reads its
backend state 300 ms after 「tasks-completed」; the backend still says running
because stopping the two agents took longer (mxu-tauri.log 2026-10-10:
`maa_get_all_states called` at 09:37:28 while `Waiting for agent process #0 to
exit...` only ended at 09:37:29), no later event comes, and the exit never fires.
MXU's own way back: POST /api/maa/instances/<id>/tasks/stop emits 「task-stopped」,
the frontend re-reads the state 300 ms later, sees not-running, and exits.

The three hangs of the last seven days, replayed from MXU's own logs
(fixtures/mxu-371/, cut from D:\\ark\\maaend\\debug\\<day>-<n>.log: the
--quit-after-run line, then everything from 「任务已提交」 to the end) and the
relay.log lines the watchdog wrote then (RELAY_LOG below, verbatim from
C:\\ProgramData\\ark-relay\\relay.log), and one normal exit (10-08 11:12:49, the closing line written) that must not be
touched. The nudge, the clock, the process list and the kill are stand-ins.
"""
import io
import json
import logging
import os
import sys
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import techlog, texts  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.features.run import maaend_watchdog  # noqa: E402
from ark_relay.features.selfcheck import machinecheck as mc  # noqa: E402
from ark_relay.features.verify import collector_maaend  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures"
MXU = FX / "mxu-371"
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


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def said(self, *parts):
        return [r for r in self.records if all(p in r.getMessage() for p in parts)]


LINES = Lines()
maaend_watchdog.log.addHandler(LINES)
maaend_watchdog.log.setLevel(logging.DEBUG)


class Refuses:
    """errwatch's notifier: the group refuses, so what it queues stays queued (readable)."""

    def send_group(self, title, body):
        return ["企业微信机器人：拒收"]

    def send(self, title, body, **kw):
        return ["拒收"]


ARK_LOGGER = logging.getLogger(errwatch.ARK)


def watch():
    """errwatch as on the machine: its door for recovered records writes the red item."""
    sd = tmpdir() / "state"                      # its own tech/ next to it (techlog.tech_dir)
    h = errwatch.ErrorKindAlert(Refuses(), state_dir=sd, known={}, retry=(3600.0,), fallback_after=1e9)
    ARK_LOGGER.addHandler(h)
    return h, sd


def unwatch(h):
    ARK_LOGGER.removeHandler(h)
    h.close()


def reds(sd):
    """(id, text) of every unhandled red item in any technical-log day next to `sd`."""
    out = []
    for f in sorted(techlog.tech_dir(sd).glob("*.md")):
        out += techlog.unhandled(f.read_text(encoding="utf-8"))
    return out

RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
DONE = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "完成"}]}]}


class Rig:
    """One watchdog on one real MXU log; `nudge` decides what the stop request does."""

    def __init__(self, log_name, pid, first_seen, nudge_result=(True, ""), exits_on_nudge=True):
        self.debug = tmpdir() / "debug"
        self.debug.mkdir()
        (self.debug / "go-service.stderr.log").write_text("", encoding="utf-8")
        (self.debug / log_name).write_text((MXU / log_name).read_text(encoding="utf-8"), encoding="utf-8")
        self.pid = pid
        self.procs = [("Endfield.exe", 18800), ("MaaEnd.exe", pid), ("go-service.exe", 21932), ("System", 4)]
        self.snap = RUNNING
        self.t, self.wall, self.lines = 1000.0, first_seen, 0
        self.nudges, self.killed, self.notes = [], [], Notes()
        self.nudge_result, self.exits_on_nudge = nudge_result, exits_on_nudge
        self.state = tmpdir()
        self.dog = maaend_watchdog.Watchdog(
            self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: self.snap,
            processes=lambda: list(self.procs), kill=self._kill, wallclock=lambda: self.wall,
            plugin_paths=lambda: {}, active=True, nudge=self._nudge, state_dir=self.state)
        self.tick()                                   # first sight of this MaaEnd

    def _nudge(self):
        self.nudges.append(self.wall.strftime("%H:%M:%S"))
        if self.nudge_result[0] and self.exits_on_nudge:
            self.procs = [p for p in self.procs if p[1] != self.pid]   # MXU exits within the next second
        return self.nudge_result

    def _kill(self, pid, image):
        self.killed.append((pid, image))
        self.procs = [p for p in self.procs if p[1] != pid]
        return True, ""

    def tick(self):
        self.lines += 1                               # maafw.log keeps moving until the end: no stall
        return self.dog.tick(self.lines, "")

    def at(self, hh, mm, ss, lines_move=True):
        new = self.wall.replace(hour=hh, minute=mm, second=ss)
        self.t += (new - self.wall).total_seconds()
        self.wall = new
        if not lines_move:
            self.lines -= 1
        return self.tick()


RELAY_LOG = {
    16864: "10-06 09:52:54 WARNING ark.maaend_watchdog  MaaEnd 卡死（PID 16864）：判定原因：MaaEnd 所有任务 09:51:51 已完成，63 秒后仍没有自己退出（正常 4 秒内退出）。；已结束",
    19168: "10-09 09:33:00 WARNING ark.maaend_watchdog  MaaEnd 卡死（PID 19168）：判定原因：MaaEnd 所有任务 09:31:56 已完成，63 秒后仍没有自己退出（正常 4 秒内退出）。；已结束",
    7788: "10-10 09:38:32 WARNING ark.maaend_watchdog  MaaEnd 卡死（PID 7788）：判定原因：MaaEnd 所有任务 09:37:28 已完成，64 秒后仍没有自己退出（正常 4 秒内退出）。；已结束",
}
CASES = (  # (log, pid, MaaEnd first seen, tasks-completed)
    ("2026-10-06-2.log", 16864, datetime(2026, 10, 6, 9, 29, 10), (9, 51, 51)),
    ("2026-10-09-3.log", 19168, datetime(2026, 10, 9, 9, 11, 15), (9, 31, 56)),
    ("2026-10-10-3.log", 7788, datetime(2026, 10, 10, 9, 14, 25), (9, 37, 28)),
)


def plus(hms, s):
    d = datetime(2026, 1, 1, *hms) + timedelta(seconds=s)
    return d.hour, d.minute, d.second


for log_name, pid, seen, done in CASES:
    day = log_name[:10]
    print(f"\n[{day} {done[0]:02d}:{done[1]:02d}:{done[2]:02d} tasks-completed, no closing line: stop request, MaaEnd exits]")
    hms = "%02d:%02d:%02d" % done
    check("the MXU log's tasks-completed is the one the relay judged then",
          (f"{day} {hms} " in (MXU / log_name).read_text(encoding="utf-8"), f"所有任务 {hms} 已完成" in RELAY_LOG[pid]),
          (True, True))
    LINES.records.clear()
    h, sd = watch()
    r = Rig(log_name, pid, seen)
    r.at(*plus(done, -20))                            # a check just before the end: arms CHECK_EVERY
    check("7 s after tasks-completed: nothing yet", (r.at(*plus(done, 7)), r.nudges, r.killed), (None, [], []))
    r.at(*plus(done, 37), lines_move=False)
    check("first check >= 10 s after: one stop request", r.nudges, ["%02d:%02d:%02d" % plus(done, 37)])
    check("no kill on the stop request", r.killed, [])
    r.snap = DONE                                     # MaaEnd gone: AUTO-MAS judged the run and moved on
    r.at(*plus(done, 68), lines_move=False)
    check("gone at the next check: never killed", r.killed, [])
    check("no group alarm", r.notes.sent, [])
    rec = LINES.said("MXU#371", "自己退出")
    check("one WARNING naming the upstream workaround", [x.levelno for x in rec], [logging.WARNING])
    check("marked recovered (fixed itself: daily report, not the group)",
          [getattr(x, errwatch.RECOVERED, False) for x in rec], [True])
    check("no other WARNING for this run",
          [x.getMessage() for x in LINES.records if x.levelno >= logging.WARNING and x not in rec], [])
    check("nothing queued for the group", h.pending(), [])
    red = reds(sd)
    check("one 「自愈待查」 red item in the technical log, naming the stop request",
          [(techlog.SELF_HEAL in t, "MXU#371" in t) for _, t in red], [(True, True)])
    unwatch(h)
    msg = rec[0].getMessage() if rec else ""
    check("it says when the tasks finished", "%02d:%02d:%02d" % done in msg, True)
    check("it says after how many seconds the request went", "37 秒" in msg, True)
    check("#31 judged the stop request: PASS", mc.read(r.state).get("#31", {}).get("status"), "PASS")
    check("no 「卡死」 line for this run", LINES.said("MaaEnd 卡死"), [])
    r.at(*plus(done, 100), lines_move=False)
    check("not asked twice", len(r.nudges), 1)

print("\n[10-10 replay: stop request accepted but MaaEnd still there -> kill, its WARNING goes to the group]")
LINES.records.clear()
h, sd = watch()
r = Rig("2026-10-10-3.log", 7788, datetime(2026, 10, 10, 9, 14, 25), exits_on_nudge=False)
r.at(9, 37, 8)
r.at(9, 37, 40, lines_move=False)
check("asked once at 09:37:40", r.nudges, ["09:37:40"])
title = r.at(9, 38, 11, lines_move=False)
check("31 s later still there: MaaEnd.exe ended", r.killed, [(7788, "MaaEnd.exe")])
check("title returned", title, texts.MAAEND_STUCK_KILLED)
stuck = LINES.said("MaaEnd 卡死")
check("one 「卡死」 WARNING, not marked recovered: errwatch pushes it to the group",
      [(x.levelno, getattr(x, errwatch.RECOVERED, False)) for x in stuck], [(logging.WARNING, False)])
body = stuck[0].getMessage() if stuck else ""
check("it keeps the no-exit reason", "所有任务 09:37:28 已完成" in body, True)
check("it says the stop request did not make it exit", "先请 MaaEnd 自己收尾退出" in body, True)
check("no ⚠️ on top (main's rule: the WARNING is its one push)",
      [t for t, _, _ in r.notes.sent if t == texts.MAAEND_STUCK_KILLED], [])
check("#31 for the stop request: FAIL (it did not work)", any(t.startswith("🔬") and "#31" in t for t, _, _ in r.notes.sent), True)
check("the 「卡死」 WARNING is queued for the group", any("MaaEnd 卡死" in str(x.get("line")) for x in h.pending()), True)
check("no red item: nothing fixed itself", reds(sd), [])
unwatch(h)

print("\n[10-09 replay: the stop request itself failed (MXU not answering) -> kill as today, its WARNING to the group]")
LINES.records.clear()
r = Rig("2026-10-09-3.log", 19168, datetime(2026, 10, 9, 9, 11, 15), nudge_result=(False, texts.MXU_STOP_NO_ANSWER))
r.at(9, 31, 46)
title = r.at(9, 32, 16, lines_move=False)         # 20 s after: request fails, not yet 30 s (D129 floor)
check("asked once", r.nudges, ["09:32:16"])
check("not killed before the agreed 30 s", r.killed, [])
title = r.at(9, 32, 47, lines_move=False)
check("51 s: killed", r.killed, [(19168, "MaaEnd.exe")])
body = " ".join(x.getMessage() for x in LINES.said("MaaEnd 卡死"))
check("the pushed WARNING names why the request failed", texts.MXU_STOP_NO_ANSWER in body, True)
check("not recovered", [getattr(x, errwatch.RECOVERED, False) for x in LINES.said("MaaEnd 卡死")], [False])

print("\n[two MaaEnd.exe up (10-09 / 10-10 08:46 had that, the second on 12702) -> no request, kill by PID as before]")
LINES.records.clear()
r = Rig("2026-10-10-3.log", 7788, datetime(2026, 10, 10, 9, 14, 25))
r.procs.append(("MaaEnd.exe", 9999))
r.at(9, 37, 8)
r.at(9, 37, 40, lines_move=False)                # 12 s: would ask, but cannot tell which MXU it reaches
check("no request sent", r.nudges, [])
r.at(9, 38, 11, lines_move=False)
check("killed by its PID only", r.killed, [(7788, "MaaEnd.exe")])
check("the WARNING says why no request went", texts.MXU_STOP_TWO in " ".join(x.getMessage() for x in LINES.said("MaaEnd 卡死")), True)

print("\n[accepted request, then nobody judges for 5 minutes (AUTO-MAS not 运行) -> no exit claimed]")
LINES.records.clear()
r = Rig("2026-10-10-3.log", 7788, datetime(2026, 10, 10, 9, 14, 25), exits_on_nudge=False)
r.at(9, 37, 8)
r.at(9, 37, 40, lines_move=False)
check("asked once", r.nudges, ["09:37:40"])
r.snap = DONE
r.at(9, 43, 0, lines_move=False)                  # 320 s later
r.procs = [p for p in r.procs if p[1] != 7788]   # ended by something else
r.at(9, 43, 40, lines_move=False)
check("no 「自己退出」 line claimed", LINES.said("自己退出"), [])
check("no #31 verdict claimed", mc.read(r.state).get("#31"), None)

print("\n[10-08 normal exit: closing line written -> no stop request, nothing]")
r = Rig("2026-10-08-5.log", 5000, datetime(2026, 10, 8, 10, 35, 30))
r.at(11, 12, 40)
r.at(11, 13, 20, lines_move=False)
r.at(11, 13, 55, lines_move=False)
check("nothing asked, nothing killed, nothing sent", (r.nudges, r.killed, r.notes.sent), ([], [], []))

print("\n[the real stop request: port from MXU's own log, across its 1 MB rotation; one POST]")
d = tmpdir() / "debug"
d.mkdir()
# 2026-10-10: the AUTO-MAS launch logged its port at 09:14:21 and mxu-tauri.log
# rotated at 09:14:23, so the live file no longer has the line.
(d / "mxu-tauri_2026-10-10_09-14-23.log").write_text(
    "[2026-10-10][08:46:20][INFO][mxu_lib::web_server] Web server listening on http://127.0.0.1:12702 (fallback from default port 12701)\n"
    "[2026-10-10][09:14:21][INFO][mxu_lib::web_server] Web server listening on http://127.0.0.1:12701\n", encoding="utf-8")
(d / "mxu-tauri.log").write_text(
    "[2026-10-10][09:37:28][INFO][mxu_lib::commands::maa_agent] stop_agent_impl called for instance: automas\n",
    encoding="utf-8")
os.utime(d / "mxu-tauri_2026-10-10_09-14-23.log", (1, 1))
check("port from the rotated file", maaend_watchdog._mxu_port(d), 12701)
(d / "mxu-tauri.log").write_text(
    "[2026-10-09][08:46:18][INFO][mxu_lib::web_server] Web server listening on http://127.0.0.1:12702 (fallback from default port 12701)\n",
    encoding="utf-8")
check("the live file's line wins (the 12702 fallback)", maaend_watchdog._mxu_port(d), 12702)
check("no line anywhere: 12701", maaend_watchdog._mxu_port(tmpdir()), 12701)


class Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


calls = []


def opener(states, stop_body='{"ok":true}'):
    def _open(req, timeout):
        calls.append((req.get_method(), req.full_url, req.data, timeout))
        if req.full_url.endswith("/maa/state"):
            return Resp(json.dumps(states))
        return Resp(stop_body)
    return _open


(d / "mxu-tauri.log").write_text("", encoding="utf-8")
calls.clear()
ok = maaend_watchdog._mxu_stop(d, opener=opener({"instances": {"automas": {"is_running": False}}}))
check("one instance (the backend already idle, #371's case): stop sent", ok, (True, ""))
check("GET state then POST stop for that instance, short timeouts",
      [(m, u, dt, to) for m, u, dt, to in calls],
      [("GET", "http://127.0.0.1:12701/api/maa/state", None, 5),
       ("POST", "http://127.0.0.1:12701/api/maa/instances/automas/tasks/stop", b"{}", 5)])
calls.clear()
ok = maaend_watchdog._mxu_stop(d, opener=opener({"instances": {"a": {"is_running": False}, "b": {"is_running": True}}}))
check("two instances: the running one", (ok, calls[-1][1].rsplit("/", 3)[-3]), ((True, ""), "b"))
calls.clear()
ok, why = maaend_watchdog._mxu_stop(d, opener=opener({"instances": {"a": {}, "b": {}}}))
check("two idle instances: not guessed, no POST", (ok, len(calls), bool(why)), (False, 1, True))


def http_500(req, timeout):
    if req.full_url.endswith("/maa/state"):
        return Resp('{"instances": {"automas": {}}}')
    raise urllib.error.HTTPError(req.full_url, 500, "Internal Server Error", {},
                                 io.BytesIO(b'{"error":"Tasker not created"}'))


LINES.records.clear()
ok, why = maaend_watchdog._mxu_stop(d, opener=http_500)
check("MXU answers 500 (web_server.rs handle_stop_task): failed", (ok, why), (False, texts.mxu_stop_refused(500)))
check("its own words go to the log", len(LINES.said("Tasker not created")), 1)
ok, why = maaend_watchdog._mxu_stop(d, opener=opener({"instances": {"automas": {}}}, '{"ok":false}'))
check("200 without ok:true: failed", ok, False)


def refused(req, timeout):
    raise ConnectionRefusedError(10061, "refused")


ok, why = maaend_watchdog._mxu_stop(d, opener=refused)
check("nothing listening: failed, said plainly", (ok, bool(why)), (False, True))

print("\n[the relay's own reading of a nudged run: MaaEnd's 「停止任务」 after the closing task]")
# MaaTaskerPostStop is an EmptyTask whose run() returns true (MaaFramework
# v5.14.2 Task/EmptyTask.h), so MXU prints 「任务开始/任务完成: 停止任务」 - the
# real shape is fixtures/maaend_stop_task_2026-10-08.log lines 20-21.
base = (FX / "maaend-farm-drops" / "2026-09-28a.log").read_text(encoding="utf-8")
check("the 09-28 round as it is: all done", collector_maaend._maaend_all_done(base), True)
nudged = base.rstrip("\n") + ("\n[2026-09-28 11:22:40.413] 任务开始: 停止任务"
                              "\n[2026-09-28 11:22:40.513] 任务完成: 停止任务\n")
check("with the stop task after 关闭游戏: still all done", collector_maaend._maaend_all_done(nudged), True)
cut = base[:base.rindex("[2026-09-28 11:22:07.978]")] + ("[2026-09-28 11:22:40.413] 任务开始: 停止任务\n"
                                                         "[2026-09-28 11:22:40.513] 任务完成: 停止任务\n")
check("the stop task does not stand in for a missing 关闭游戏", collector_maaend._maaend_all_done(cut), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
