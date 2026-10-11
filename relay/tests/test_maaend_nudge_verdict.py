"""One MaaEnd hang, two exits that book it: the watchdog's and the outcome check's.

Since 5e6085de the watchdog asks a finished MaaEnd that does not exit (upstream
MistEO/MXU#371) to stop once; MaaEnd leaving on that request is booked as
recovered at the watchdog's exit (Watchdog._verify_nudge: daily report, one
「自愈待查」 red item, not the group). The same run then reaches the outcome check
(verdict._mark_no_self_exit), whose 「🟠 MaaEnd … 任务全部完成，但跑完没自己退出」
WARNING was pushed regardless - one event half recovered, half pushed. The
watchdog now books each request's fate in StateStore marks (NUDGE_MARK) and the
outcome check books the 🟠 line the same way when that run exited on the request.

Replayed end to end, watchdog then outcome check, on one state directory:

* the three hangs (10-06 09:51:51, 10-09 09:31:56, 10-10 09:37:28). MXU's side is
  the machine's own log: for 10-10 the full file
  (fixtures/maaend-2026-10-10/app-2026-10-10-3.log); for 10-06 / 10-09 the cut in
  fixtures/mxu-371/ with the one 「开始执行任务, 数量: 16」 line put back in front of
  「任务已提交」 (the cut starts there; 16 is the task_ids count on that very line,
  and the line's shape is verbatim from 10-10 09:14:37). AUTO-MAS's side (the run's
  history log) of those three days is not in the fixtures, so it is the real
  all-done round of 2026-09-28 (fixtures/maaend-farm-drops/2026-09-28a.log, 16
  tasks, itself a no-exit hang at 11:22:10) plus the 「停止任务」 pair the request
  adds (shape: fixtures/maaend_stop_task_2026-10-08.log lines 20-21);
* the outcome check landing before the watchdog has seen MaaEnd go (AUTO-MAS
  records the run 0.7-4.0 s after the exit, the watchdog looks every 30-60 s);
* MaaEnd killed for not exiting - after an accepted request, after a request that
  failed, or with two MaaEnd up so none was sent: the watchdog books the kill in
  NUDGE_MARK before it, and its 「MaaEnd 卡死」 WARNING is the hang's push; the 🟠
  line is booked on the ledger (daily report, technical log) and not pushed again
  (BACKLOG, 验收 2026-10-11 22:3x: one hang, one push). Machine check #31's FAIL
  for the request is still pushed as well: every FAIL is, every time it is judged
  (docs/NOTIFICATIONS.md 🔬 row, test_machinecheck.py);
* no request and no kill at all, a dropped request, and a row left 「asked」 by a
  relay restart: the watchdog pushed nothing, so the 🟠 line is the push;
* one booked request is claimed by one run only.
"""
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import techlog, texts  # noqa: E402
from ark_relay.core.config import SERVER_TZ, RunRecord  # noqa: E402
from ark_relay.core.ledger import State  # noqa: E402
from ark_relay.features.alarm import errwatch, handle, verdict  # noqa: E402
from ark_relay.features.run import maaend_watchdog  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures"
MXU = FX / "mxu-371"
HISTORY = (FX / "maaend-farm-drops" / "2026-09-28a.log").read_text(encoding="utf-8").rstrip("\n") + (
    "\n[2026-09-28 11:22:40.413] 任务开始: 停止任务\n[2026-09-28 11:22:40.513] 任务完成: 停止任务\n")
COUNT_LINE = "{day} {hms} INFO  [Task] 实例 AUTO-MAS: 开始执行任务, 数量: 16"
NO_EXIT = "任务全部完成，但跑完没自己退出"
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


class Refuses:
    """errwatch's notifier: the group refuses, so what it queues stays queued (readable)."""

    def send_group(self, title, body):
        return ["企业微信机器人：拒收"]

    def send(self, title, body, **kw):
        return ["拒收"]


ARK_LOGGER = logging.getLogger(errwatch.ARK)


def watch():
    sd = tmpdir() / "state"                      # its own tech/ next to it, never the shared $TMPDIR/tech
    h = errwatch.ErrorKindAlert(Refuses(), state_dir=sd, known={}, retry=(3600.0,), fallback_after=1e9)
    ARK_LOGGER.addHandler(h)
    return h, sd


def unwatch(h):
    ARK_LOGGER.removeHandler(h)
    h.close()


def reds(sd):
    out = []
    for f in sorted(techlog.tech_dir(sd).glob("*.md")):
        out += techlog.unhandled(f.read_text(encoding="utf-8"))
    return out


def queued(h, part):
    return [str(x.get("line")) for x in h.pending() if part in str(x.get("line"))]


RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
DONE = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "完成"}]}]}


def mxu_text(log_name):
    """MXU's own log of that run, as the machine wrote it (see the module docstring)."""
    if log_name == "2026-10-10-3.log":
        return (FX / "maaend-2026-10-10" / "app-2026-10-10-3.log").read_text(encoding="utf-8")
    lines = (MXU / log_name).read_text(encoding="utf-8").splitlines()
    at = next(i for i, x in enumerate(lines) if "任务已提交, task_ids:" in x)
    assert lines[at].split("task_ids: [", 1)[1].split("]")[0].count(",") == 15   # 16 task ids on the line itself
    lines.insert(at, COUNT_LINE.format(day=lines[at][:10], hms=lines[at][11:19]))
    return "\n".join(lines) + "\n"


class Rig:
    """The watchdog on one MXU log, and an engine for the outcome check on the same state dir."""

    def __init__(self, log_name, pid, first_seen, nudge_result=(True, ""), exits_on_nudge=True):
        self.maaend = tmpdir() / "maaend"
        self.debug = self.maaend / "debug"
        self.debug.mkdir(parents=True)
        (self.debug / "go-service.stderr.log").write_text("", encoding="utf-8")
        (self.debug / log_name).write_text(mxu_text(log_name), encoding="utf-8")
        self.pid, self.seen = pid, first_seen
        self.procs = [("Endfield.exe", 18800), ("MaaEnd.exe", pid), ("go-service.exe", 21932), ("System", 4)]
        self.snap = RUNNING
        self.t, self.wall, self.lines = 1000.0, first_seen, 0
        self.nudges, self.killed, self.notes = [], [], Notes()
        self.nudge_result, self.exits_on_nudge = nudge_result, exits_on_nudge
        self.state_dir = tmpdir() / "relaystate"
        self.dog = maaend_watchdog.Watchdog(
            self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: self.snap,
            processes=lambda: list(self.procs), kill=self._kill, wallclock=lambda: self.wall,
            plugin_paths=lambda: {21932: str(self.maaend / "agent" / "go-service.exe")}, active=True,
            nudge=self._nudge, state_dir=self.state_dir)
        self.tick()
        self.history = tmpdir() / "MaaEnd.log"
        self.history.write_text(HISTORY, encoding="utf-8")

    def _nudge(self):
        self.nudges.append(self.wall.strftime("%H:%M:%S"))
        if self.nudge_result[0] and self.exits_on_nudge:
            self.procs = [p for p in self.procs if p[1] != self.pid]
        return self.nudge_result

    def _kill(self, pid, image):
        self.killed.append((pid, image))
        self.procs = [p for p in self.procs if p[1] != pid]
        return True, ""

    def tick(self):
        self.lines += 1
        return self.dog.tick(self.lines, "")

    def at(self, wall, lines_move=False):
        self.t += (wall - self.wall).total_seconds()
        self.wall = wall
        if not lines_move:
            self.lines -= 1
        return self.tick()

    def run_record(self, finished, run_id=None):
        """AUTO-MAS's record of this run: started just before MaaEnd was first seen."""
        return RunRecord(run_id=run_id or f"{self.seen:%Y-%m-%d}/endfield/MaaEnd-{self.seen:%H-%M-%S}",
                         script="MaaEnd", user="endfield",
                         started=(self.seen - timedelta(seconds=5)).replace(tzinfo=SERVER_TZ),
                         finished=finished.replace(tzinfo=SERVER_TZ), ok=True, log_path=self.history)

    def outcome(self, rec):
        """verdict._verify_outcome on this run, as handle.py calls it."""
        eng = type("Eng", (), {})()
        eng.cfg = type("Cfg", (), {"maaend_dir": str(self.maaend), "history_dir": None,
                                   "automas_dir": None, "maa_dir": None})()
        eng.state = State(self.state_dir)
        eng.state.append_ledger(rec)
        return verdict._verify_outcome(eng, rec)


SHIPPED = []
_real_ship = handle._ship_evidence


def _fake_ship(eng, rec):
    # The real one uploads to COS; here only who asked for a bundle is recorded.
    SHIPPED.append(rec.run_id)
    rec.raw["evidence_page"] = "https://example.invalid/bundle"
    return rec.raw["evidence_page"]


handle._ship_evidence = _fake_ship

CASES = (  # (MXU log, MaaEnd PID, MaaEnd first seen, tasks-completed) - test_maaend_nudge.py's three hangs
    ("2026-10-06-2.log", 16864, datetime(2026, 10, 6, 9, 29, 10), datetime(2026, 10, 6, 9, 51, 51)),
    ("2026-10-09-3.log", 19168, datetime(2026, 10, 9, 9, 11, 15), datetime(2026, 10, 9, 9, 31, 56)),
    ("2026-10-10-3.log", 7788, datetime(2026, 10, 10, 9, 14, 25), datetime(2026, 10, 10, 9, 37, 28)),
)
S = timedelta(seconds=1)

try:
    for log_name, pid, seen, done in CASES:
        print(f"\n[{done:%m-%d %H:%M:%S} hang: stop request accepted, MaaEnd exits; watchdog sees it, then the outcome check runs]")
        h, sd = watch()
        r = Rig(log_name, pid, seen)
        r.at(done - 20 * S, lines_move=True)
        r.at(done + 37 * S)                           # the stop request; MaaEnd leaves within the second
        check("one stop request, no kill", (len(r.nudges), r.killed), (1, []))
        r.snap = DONE
        r.at(done + 68 * S)                           # the watchdog sees the PID gone
        rec = r.run_record(done + 39 * S)             # AUTO-MAS recorded the end ~1-2 s after the exit
        r.outcome(rec)
        check("the run is booked 「跑完没自己退出」 on the ledger (daily report)",
              "maaend_no_self_exit" in rec.raw, True)
        check("the 🟠 line is among the technical log's red items", any(NO_EXIT in t for _, t in reds(sd)), True)
        check("group: nothing queued for this hang (no 🟠, no 「卡死」)",
              (queued(h, NO_EXIT), queued(h, "卡死"), r.notes.sent), ([], [], []))
        check("technical log: the watchdog's red item and the 🟠's, both 「自愈待查」",
              sorted((techlog.SELF_HEAL in t, NO_EXIT in t, "MXU#371" in t) for _, t in reds(sd)),
              [(True, False, True), (True, True, True)])
        check("the evidence bundle still ships", SHIPPED[-1:], [rec.run_id])
        unwatch(h)

    print("\n[10-10 hang: the outcome check runs before the watchdog has seen MaaEnd go (state still 「asked」)]")
    h, sd = watch()
    log_name, pid, seen, done = CASES[2]
    r = Rig(log_name, pid, seen)
    r.at(done - 20 * S, lines_move=True)
    r.at(done + 37 * S)
    rec = r.run_record(done + 39 * S)
    r.outcome(rec)                                    # AUTO-MAS already recorded; the watchdog's next look is later
    check("no 🟠 queued for the group", queued(h, NO_EXIT), [])
    check("its red item is written", [NO_EXIT in t for _, t in reds(sd)], [True])
    r.snap = DONE
    r.at(done + 68 * S)                               # the watchdog's own recovered line follows
    check("still nothing for the group, two red items", (h.pending(), len(reds(sd))), ([], 2))
    unwatch(h)

    print("\n[10-10 hang: request accepted, MaaEnd still there -> killed; one group push, the 「卡死」]")
    h, sd = watch()
    r = Rig(log_name, pid, seen, exits_on_nudge=False)
    r.at(datetime(2026, 10, 10, 9, 37, 8), lines_move=True)
    r.at(datetime(2026, 10, 10, 9, 37, 40))
    r.at(datetime(2026, 10, 10, 9, 38, 11))
    check("killed, with its plugin", r.killed, [(7788, "MaaEnd.exe"), (21932, "go-service.exe")])
    rec = r.run_record(datetime(2026, 10, 10, 9, 38, 13))
    r.outcome(rec)
    check("errwatch: one push for the hang, the 「卡死」 WARNING (no 🟠)",
          (len(h.pending()), len(queued(h, "卡死")), queued(h, NO_EXIT)), (1, 1, []))
    check("…plus machine check #31's FAIL, pushed every time it is judged (docs/NOTIFICATIONS.md 🔬 row)",
          [t[:12] for t, _, _ in r.notes.sent], ["🔬 上机核对没过：#31"])
    check("the run is still booked 「跑完没自己退出」 (daily report, technical log)", "maaend_no_self_exit" in rec.raw, True)
    check("no red item: nothing fixed itself", reds(sd), [])
    unwatch(h)

    print("\n[10-09 hang: the request itself failed (no answer) -> killed; 🟠 pushed]")
    h, sd = watch()
    log_name, pid, seen, done = CASES[1]
    r = Rig(log_name, pid, seen, nudge_result=(False, texts.MXU_STOP_NO_ANSWER))
    r.at(datetime(2026, 10, 9, 9, 31, 46), lines_move=True)
    r.at(datetime(2026, 10, 9, 9, 32, 16))
    r.at(datetime(2026, 10, 9, 9, 32, 47))
    check("killed, with its plugin", r.killed, [(19168, "MaaEnd.exe"), (21932, "go-service.exe")])
    r.outcome(r.run_record(datetime(2026, 10, 9, 9, 32, 49)))
    check("errwatch: one push, the 「卡死」 WARNING (no 🟠)",
          (len(h.pending()), len(queued(h, "卡死")), queued(h, NO_EXIT)), (1, 1, []))
    check("…plus #31's FAIL", [t[:12] for t, _, _ in r.notes.sent], ["🔬 上机核对没过：#31"])
    check("no red item", reds(sd), [])
    unwatch(h)

    print("\n[10-10 hang with two MaaEnd up: no request sent at all -> killed; one push, the 「卡死」]")
    h, sd = watch()
    log_name, pid, seen, done = CASES[2]
    r = Rig(log_name, pid, seen)
    r.procs.append(("MaaEnd.exe", 12702))             # the second one bound 12702 (10-09 / 10-10 08:46)
    r.at(datetime(2026, 10, 10, 9, 37, 8), lines_move=True)
    r.at(datetime(2026, 10, 10, 9, 37, 40))
    r.at(datetime(2026, 10, 10, 9, 38, 11))
    check("no request, killed by PID", (r.nudges, r.killed), ([], [(7788, "MaaEnd.exe"), (21932, "go-service.exe")]))
    r.outcome(r.run_record(datetime(2026, 10, 10, 9, 38, 13)))
    check("errwatch: one push, the 「卡死」 WARNING (no 🟠)",
          (len(h.pending()), len(queued(h, "卡死")), queued(h, NO_EXIT)), (1, 1, []))
    check("…plus #31's FAIL", [t[:12] for t, _, _ in r.notes.sent], ["🔬 上机核对没过：#31"])
    unwatch(h)

    print("\n[10-10 hang killed, then a later run of the same day that did not exit and was not killed -> 🟠 pushed]")
    h, sd = watch()
    r = Rig(log_name, pid, seen, exits_on_nudge=False)
    r.at(datetime(2026, 10, 10, 9, 37, 8), lines_move=True)
    r.at(datetime(2026, 10, 10, 9, 37, 40))
    r.at(datetime(2026, 10, 10, 9, 38, 11))
    r.outcome(r.run_record(datetime(2026, 10, 10, 9, 38, 13)))
    later = r.run_record(datetime(2026, 10, 10, 9, 38, 20), run_id="2026-10-10/endfield/MaaEnd-later")
    r.outcome(later)
    check("the kill's row is claimed by its own run only: the later run's 🟠 is pushed",
          [later.run_id in x for x in queued(h, NO_EXIT)], [True])
    unwatch(h)

    print("\n[10-06 run: no stop request at all (watchdog never looked), no closing line -> 🟠 pushed]")
    h, sd = watch()
    log_name, pid, seen, done = CASES[0]
    r = Rig(log_name, pid, seen)                      # first sight only: no request is ever sent
    r.outcome(r.run_record(done + 64 * S))
    check("no stop request was made", r.nudges, [])
    check("the 🟠 line is queued for the group", len(queued(h, NO_EXIT)), 1)
    check("no red item", reds(sd), [])
    unwatch(h)

    print("\n[accepted request nobody judged for 5 minutes (dropped) -> 🟠 pushed]")
    h, sd = watch()
    log_name, pid, seen, done = CASES[2]
    r = Rig(log_name, pid, seen, exits_on_nudge=False)
    r.at(datetime(2026, 10, 10, 9, 37, 8), lines_move=True)
    r.at(datetime(2026, 10, 10, 9, 37, 40))
    r.snap = DONE
    r.at(datetime(2026, 10, 10, 9, 43, 0))            # 320 s: dropped without a verdict
    r.procs = [p for p in r.procs if p[1] != 7788]
    r.outcome(r.run_record(datetime(2026, 10, 10, 9, 43, 30)))
    check("the 🟠 line is queued for the group", len(queued(h, NO_EXIT)), 1)
    unwatch(h)

    print("\n[accepted request, then the relay restarted (row left 「asked」) and MaaEnd hung on until AUTO-MAS's own 40-minute end -> 🟠 pushed]")
    h, sd = watch()
    r = Rig(log_name, pid, seen, exits_on_nudge=False)
    r.at(datetime(2026, 10, 10, 9, 37, 8), lines_move=True)
    r.at(datetime(2026, 10, 10, 9, 37, 40))           # accepted; no later watchdog look (a fresh relay forgot it)
    r.outcome(r.run_record(datetime(2026, 10, 10, 10, 17, 40)))
    check("the 🟠 line is queued for the group", len(queued(h, NO_EXIT)), 1)
    check("no red item for it", [NO_EXIT in t for _, t in reds(sd)], [])
    unwatch(h)

    print("\n[one booked request, one run: a second record in the same window does not claim it]")
    h, sd = watch()
    r = Rig(log_name, pid, seen)
    r.at(done - 20 * S, lines_move=True)
    r.at(done + 37 * S)
    r.snap = DONE
    r.at(done + 68 * S)
    r.outcome(r.run_record(done + 39 * S))
    other = r.run_record(done + 40 * S, run_id="2026-10-10/endfield/MaaEnd-other")
    r.outcome(other)
    check("the first run is recovered, the second one is pushed", len(queued(h, NO_EXIT)), 1)
    check("…and the pushed one is the second run", [other.run_id in x for x in queued(h, NO_EXIT)], [True])
    again = r.run_record(done + 39 * S)               # a replay of the first record
    before = len(queued(h, NO_EXIT))
    r.outcome(again)
    check("a replay of the first record is still recovered", len(queued(h, NO_EXIT)), before)
    unwatch(h)
finally:
    handle._ship_evidence = _real_ship

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
