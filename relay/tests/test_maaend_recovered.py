"""MaaEnd hung and the relay ends it: which of the two log lines is "recovered".

The morning shift of 2026-10-06 pushed three messages for one event - the watchdog
ERROR, the ⚠️ notice, the bookkeeping ERROR (all in relay-1006.log). The ⚠️ stays a
group alarm (it is written for the human). The other two are the same event written
as ERRORs in the log; the user's rule of 2026-10-06 05:07 makes them daily-report-only
when the relay's own kill let AUTO-MAS wrap the round up:

* the watchdog's 「MaaEnd 卡死」 WARNING, but only for the no-exit reason (every task
  done, just did not exit) with a kill that took: a crash / stall / plugin-gone, or a
  kill that did not take, is a fault still there and is pushed;
* handle._mark_no_self_exit's 「🟠 任务全部完成」 bookkeeping line: every task was done,
  so the round recovered by itself - daily report only.

MXU lines and the stderr crash line are verbatim machine lines (the same ones
test_maaend_no_exit.py and test_maaend_watchdog.py replay, from D:\\ark\\maaend\\debug);
the 10-06 evidence pack is not in COS (a successful run has no bundle), so the 09:51:51
lines themselves could not be fetched.
"""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import errwatch, handle, maaend_watchdog, texts          # noqa: E402
from ark_relay.config import SERVER_TZ, RunRecord                       # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Notes:
    """The watchdog's notifier: the ⚠️ notice lands here."""

    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []


class Refuses:
    """errwatch's notifier: the group refuses, so what it queues stays queued."""

    def send_group(self, title, body):
        return ["企业微信机器人：拒收"]

    def send(self, title, body, **kw):
        return ["拒收"]


class Lines(logging.Handler):
    """Captures every ark.* record, so the test can read `ark_recovered`."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def said(self, *parts):
        return [r for r in self.records if all(p in r.getMessage() for p in parts)]


ARK_LOGGER = logging.getLogger(errwatch.ARK)
LINES = Lines()
ARK_LOGGER.addHandler(LINES)
ARK_LOGGER.setLevel(logging.DEBUG)


def watch():
    sd = tmpdir()
    h = errwatch.ErrorKindAlert(Refuses(), state_dir=sd, known={}, retry=(3600.0,), fallback_after=1e9)
    ARK_LOGGER.addHandler(h)
    LINES.records.clear()
    return h, sd


def unwatch(h):
    ARK_LOGGER.removeHandler(h)
    h.close()


RUNNING = {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]}
PID = 11224
PROCS = [("MaaEnd.exe", PID), ("Endfield.exe", 18800)]   # no plugins: the kill loop stays quiet
CRASH_LINE = "Exception 0xc0000005 0x0 0xffffffffffffffff 0x7ffc630b5456"
HUNG_MXU = ["2026-10-01 16:58:19 DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: task-progress",
            "2026-10-01 16:58:22 DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: tasks-completed"]


class Dog:
    """One watchdog with everything outside replaced (the shape of test_maaend_no_exit)."""

    def __init__(self, mxu_lines):
        self.debug = tmpdir() / "debug"
        self.debug.mkdir()
        self.stderr = self.debug / "go-service.stderr.log"
        self.stderr.write_text("", encoding="utf-8")
        (self.debug / "2026-10-01-6.log").write_text("\n".join(mxu_lines) + "\n", encoding="utf-8")
        self.t, self.wall = 1000.0, datetime(2026, 10, 1, 16, 58, 22)
        self.notes = Notes()
        self.dog = maaend_watchdog.Watchdog(
            self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: RUNNING,
            processes=lambda: PROCS, kill=self._kill, wallclock=lambda: self.wall,
            plugin_paths=lambda: {}, active=True)
        self.dog.tick(1, "")                          # first sight of this MaaEnd

    def _kill(self, pid, image):
        return True, ""

    def at(self, hh, mm, ss):
        new = datetime(2026, 10, 1, hh, mm, ss)
        self.t += (new - self.wall).total_seconds()
        self.wall = new
        return self.dog.tick(1, "")


def recovered_of(records, *parts):
    rows = [r for r in records if all(p in r.getMessage() for p in parts)]
    assert rows, f"no log record matching {parts}"
    return [getattr(r, errwatch.RECOVERED, False) for r in rows]


print("[no-exit, kill took -> the 「卡死」 WARNING is daily-only, the ⚠️ still rings]")
h, sd = watch()
try:
    d = Dog(HUNG_MXU)
    check("18 s: not yet", d.at(16, 58, 40), None)
    d.at(16, 58, 53)                                  # 31 s after tasks-completed: kill
    check("the 「卡死」 WARNING is marked recovered", recovered_of(LINES.records, "MaaEnd 卡死"), [True])
    check("nothing queued for the group", h.pending(), [])
    check("the ⚠️ notice is still a group alarm",
          [(t, a) for t, _, a in d.notes.sent], [(texts.MAAEND_STUCK_KILLED, True)])
finally:
    unwatch(h)

print("\n[crash -> the same 「卡死」 WARNING is a plain WARNING and is queued]")
h, sd = watch()
try:
    d = Dog([])                                       # no tasks-completed: not the no-exit rule
    d.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    d.at(16, 59, 0)                                   # crash read -> kill
    check("the 「卡死」 WARNING is not marked recovered", recovered_of(LINES.records, "MaaEnd 卡死"), [False])
    check("it is queued for the group", any("MaaEnd 卡死" in str(x.get("line")) for x in h.pending()), True)
    check("the ⚠️ notice still rings", [(t, a) for t, _, a in d.notes.sent],
          [(texts.MAAEND_STUCK_KILLED, True)])
finally:
    unwatch(h)

print("\n[bookkeeping: the 「🟠 任务全部完成」 line is daily-only]")


class _Cfg:
    history_dir = None                                # no app.log read: idle stays 0


class _State:
    def mark_raw(self, *a):
        pass


class _Eng:
    def __init__(self):
        self.cfg = _Cfg()
        self.state = _State()


h, sd = watch()
try:
    rec = RunRecord(run_id="2026-10-06/endfield/MaaEnd-05-28-01", script="MaaEnd", user="endfield",
                    started=datetime(2026, 10, 6, 9, 51, 51, tzinfo=SERVER_TZ),
                    finished=datetime(2026, 10, 6, 9, 52, 54, tzinfo=SERVER_TZ), ok=True)
    handle._mark_no_self_exit(_Eng(), rec)
    check("the bookkeeping line is marked recovered",
          recovered_of(LINES.records, "🟠 MaaEnd", "任务全部完成"), [True])
    check("nothing queued for the group", h.pending(), [])
finally:
    unwatch(h)

ARK_LOGGER.removeHandler(LINES)
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
