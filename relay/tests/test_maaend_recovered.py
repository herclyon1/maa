"""MaaEnd hung and the relay ends it: which of the two log lines is "recovered".

The morning shift of 2026-10-06 pushed three messages for one event - the watchdog
ERROR, the ⚠️ notice, the bookkeeping ERROR (all in relay-1006.log). The ⚠️ stays a
group alarm (it is written for the human). The other two are the same event written
as ERRORs in the log; the user's rule of 2026-10-06 05:07 made them daily-report-only
when the relay's own kill let AUTO-MAS wrap the round up. Since 2026-10-10 both are
pushed again: why MaaEnd does not exit is not known and it keeps happening (10-09
09:33, 10-10 09:38), so it is not a fault that fixed itself. What follows was:

* the watchdog's 「MaaEnd 卡死」 WARNING after a crash / stall / plugin-gone kill:
  the ⚠️ is that event's one push (errwatch.group_pushed);
* handle._mark_no_self_exit's 「🟠 任务全部完成」 bookkeeping line: pushed, unless
  AUTO-MAS (v5.7.0-beta.2) logged that it ended the finished MaaEnd right after
  recording the result - then recovered (daily report) with a 「自愈待查」 red item.
  The watchdog no longer judges a MaaEnd that finished but did not exit (upstream
  MistEO/MXU#371): AUTO-MAS ends it itself.

MXU lines and the stderr crash line are verbatim machine lines (the same ones
test_maaend_watchdog.py replays, from D:\\ark\\maaend\\debug);
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

from ark_relay.features.alarm import errwatch, handle          # noqa: E402
from ark_relay.features.run import maaend_watchdog          # noqa: E402
from ark_relay.core import techlog, texts          # noqa: E402
from ark_relay.core.config import SERVER_TZ, RunRecord                       # noqa: E402

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
    sd = tmpdir() / "state"                          # its own tech/ next to it (techlog.tech_dir)
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
    """One watchdog with everything outside replaced."""

    def __init__(self, mxu_lines):
        self.debug = tmpdir() / "debug"
        self.debug.mkdir()
        self.stderr = self.debug / "go-service.stderr.log"
        self.stderr.write_text("", encoding="utf-8")
        (self.debug / "2026-10-01-6.log").write_text("\n".join(mxu_lines) + "\n", encoding="utf-8")
        self.t, self.wall = 1000.0, datetime(2026, 10, 1, 16, 58, 22)
        self.notes, self.killed = Notes(), []
        self.procs = list(PROCS)
        self.dog = maaend_watchdog.Watchdog(
            self.notes, self.debug, clock=lambda: self.t, snapshot=lambda: RUNNING,
            processes=lambda: list(self.procs), kill=self._kill,
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


def recovered_of(records, *parts):
    rows = [r for r in records if all(p in r.getMessage() for p in parts)]
    assert rows, f"no log record matching {parts}"
    return [getattr(r, errwatch.RECOVERED, False) for r in rows]


print("[finished, did not exit -> left to AUTO-MAS (v5.7.0-beta.2): no kill, no send, no WARNING]")
h, sd = watch()
try:
    d = Dog(HUNG_MXU)
    for hh, mm, ss in ((16, 58, 53), (16, 59, 24), (17, 0, 0)):     # well past the old 30 s
        check(f"{hh}:{mm:02d}:{ss:02d}: nothing done", d.at(hh, mm, ss), None)
    check("never killed", d.killed, [])
    check("nothing sent", d.notes.sent, [])
    check("no 「卡死」 line", LINES.said("MaaEnd 卡死"), [])
    check("nothing queued for the group", h.pending(), [])
finally:
    unwatch(h)

print("\n[crash -> the ⚠️ is the one push; the 「卡死」 WARNING repeats it and is not queued (2026-10-11)]")
h, sd = watch()
try:
    d = Dog([])
    d.stderr.write_text(CRASH_LINE + "\n", encoding="utf-8")
    d.at(16, 59, 0)                                   # crash read -> kill
    check("the 「卡死」 WARNING is not marked recovered", recovered_of(LINES.records, "MaaEnd 卡死"), [False])
    check("it is not queued for the group (errwatch.group_pushed: the ⚠️ went out)",
          [str(x.get("line"))[:9] for x in h.pending()], [])
    check("the ⚠️ notice still rings", [(t, a) for t, _, a in d.notes.sent],
          [(texts.MAAEND_STUCK_KILLED, True)])
finally:
    unwatch(h)

print("\n[bookkeeping: the 「🟠 任务全部完成」 line with no AUTO-MAS kill line is pushed]")


class _Cfg:
    def __init__(self, history_dir=None):
        self.history_dir = history_dir                # None: no app.log read, idle stays 0


class _State:
    def __init__(self):
        self.marks = []

    def mark_raw(self, *a):
        self.marks.append(a)


class _Eng:
    def __init__(self, history_dir=None):
        self.cfg = _Cfg(history_dir)
        self.state = _State()


def automas_app_log(lines):
    """<automas>/history next to <automas>/debug/app.log, as collector reads it."""
    root = tmpdir() / "automas"
    (root / "history").mkdir(parents=True)
    (root / "debug").mkdir()
    (root / "debug" / "app.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root / "history"


SHIPPED = []
_real_ship = handle._ship_evidence


def _fake_ship(eng, rec):
    # The real one uploads to COS; here only who asked for a bundle is recorded.
    SHIPPED.append(rec.run_id)
    rec.raw["evidence_page"] = "https://example.invalid/bundle"
    return rec.raw["evidence_page"]


handle._ship_evidence = _fake_ship
h, sd = watch()
try:
    rec = RunRecord(run_id="2026-10-06/endfield/MaaEnd-05-28-01", script="MaaEnd", user="endfield",
                    started=datetime(2026, 10, 6, 9, 51, 51, tzinfo=SERVER_TZ),
                    finished=datetime(2026, 10, 6, 9, 52, 54, tzinfo=SERVER_TZ), ok=True)
    handle._mark_no_self_exit(_Eng(), rec)
    check("the bookkeeping line is not marked recovered",
          recovered_of(LINES.records, "🟠 MaaEnd", "任务全部完成"), [False])
    check("it is queued for the group", any("任务全部完成" in str(x.get("line")) for x in h.pending()), True)
    # 10-06 09:51:51 and 10-09 09:31:56: an ok run ships no bundle on the failure
    # path, so MXU's log of the hang never left the machine. The no-exit run ships one.
    check("the no-exit run ships its evidence bundle", SHIPPED, [rec.run_id])
    handle._mark_no_self_exit(_Eng(), rec)
    check("a replay of the same record does not ship it twice", SHIPPED, [rec.run_id])
finally:
    handle._ship_evidence = _real_ship
    unwatch(h)

print("\n[bookkeeping: AUTO-MAS ended the finished MaaEnd -> recovered, a red item, not pushed]")
# AUTO-MAS v5.7.0-beta.2 app/task/MaaEnd/AutoProxy.py: check_log logs the result, then
# _wait_maaend_stage logs the kill; the result line's shape is the machine's
# (2026-10-01 16:10:00.012 in that day's evidence bundle, automas-app.log).
MAS_RESULT = "2026-10-06 09:52:55.101 | INFO     | MaaEnd 自动代理 | MaaEnd 任务结果: Success!, 日志锁已释放"
MAS_ENDED = "2026-10-06 09:52:55.104 | WARNING  | MaaEnd 自动代理 | MaaEnd 队列已结束但进程未退出，正在中止脚本进程"
handle._ship_evidence = _fake_ship
SHIPPED.clear()
h, sd = watch()
try:
    rec = RunRecord(run_id="2026-10-06/endfield/MaaEnd-05-28-02", script="MaaEnd", user="endfield",
                    started=datetime(2026, 10, 6, 9, 51, 51, tzinfo=SERVER_TZ),
                    finished=datetime(2026, 10, 6, 9, 52, 54, tzinfo=SERVER_TZ), ok=True)
    eng = _Eng(automas_app_log([MAS_RESULT, MAS_ENDED]))
    handle._mark_no_self_exit(eng, rec)
    rows = LINES.said("MaaEnd", "任务全部完成", "AUTO-MAS")
    # 10-12 20:5x the user: 「这个不算修好了吗？MaS不是修好了吗？修好了还报什么？」 -
    # AUTO-MAS ends it by design every time: one INFO line, no red item.
    check("one INFO line naming AUTO-MAS's kill", [r.levelno for r in rows], [logging.INFO])
    check("not marked recovered", [getattr(r, errwatch.RECOVERED, False) for r in rows], [False])
    red = [t for f in sorted(techlog.tech_dir(sd).glob("*.md")) for _, t in techlog.unhandled(f.read_text(encoding="utf-8"))
           if "任务全部完成" in t]
    check("no red item for it", red, [])
    check("nothing queued for the group", h.pending(), [])
    check("still booked for the technical log", [m[2:] for m in eng.state.marks], [("maaend_no_self_exit", 0)])
    check("still ships its evidence bundle", SHIPPED, [rec.run_id])
finally:
    handle._ship_evidence = _real_ship
    unwatch(h)

print("\n[bookkeeping: an AUTO-MAS kill line from another run is not this run's]")
handle._ship_evidence = _fake_ship
h, sd = watch()
try:
    late = "2026-10-06 09:55:00.000 | WARNING  | MaaEnd 自动代理 | MaaEnd 队列已结束但进程未退出，正在中止脚本进程"
    rec = RunRecord(run_id="2026-10-06/endfield/MaaEnd-05-28-03", script="MaaEnd", user="endfield",
                    started=datetime(2026, 10, 6, 9, 51, 51, tzinfo=SERVER_TZ),
                    finished=datetime(2026, 10, 6, 9, 52, 54, tzinfo=SERVER_TZ), ok=True)
    handle._mark_no_self_exit(_Eng(automas_app_log([MAS_RESULT, late])), rec)
    check("not marked recovered", recovered_of(LINES.records, "🟠 MaaEnd", "任务全部完成"), [False])
    check("it is queued for the group", any("任务全部完成" in str(x.get("line")) for x in h.pending()), True)
finally:
    handle._ship_evidence = _real_ship
    unwatch(h)

ARK_LOGGER.removeHandler(LINES)
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
