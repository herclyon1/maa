"""app_main.stop(): a stop event this account may not set ends the task at once.

2026-10-11: on the cloud runner the relay ran as SYSTEM and the runner's admin could
not open its stop event (winerror 5). stop() took that for "event not made yet" and
waited its 40 s, exit 1, relay still up (package-windows runs 38095462157 and
38095838036). Now access denied ends the task (schtasks /end) straight away; only a
missing event (winerror 2, the relay still starting) is waited for.
"""
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))

import app_main  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Relay:
    """A fake relay: `answers` is what each ask() gets; it exits `exit_after` s after a
    stop that reached it (asked or the task ended)."""

    def __init__(self, answers, exit_after=3.0):
        self.t = 0.0
        self.answers = list(answers)
        self.exit_after = exit_after
        self.stop_at = None
        self.asks = 0
        self.ended_at = None

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def running(self):
        return self.stop_at is None or self.t < self.stop_at + self.exit_after

    def ask(self):
        self.asks += 1
        got = self.answers.pop(0) if self.answers else self.answers_last
        self.answers_last = got
        if got == "asked":
            self.stop_at = self.t
        return got

    def end_task(self):
        self.ended_at = self.t
        self.stop_at = self.t


def stop(r):
    return app_main._stop(r.running, r.ask, r.end_task, sleep=r.sleep, clock=r.clock)


print("[access denied: the task is ended at once, no 40 s wait]")
r = Relay(["denied"], exit_after=1.0)
check("result", stop(r), 0)
check("task ended at the first ask", r.ended_at, 0.0)
check("done in seconds", r.t <= 3.0, True)
check("asked once", r.asks, 1)

print("[event not made yet (relay starting): asked again, no task end]")
r = Relay(["not yet", "not yet", "asked"])
check("result", stop(r), 0)
check("no task end", r.ended_at, None)
check("asks", r.asks, 3)

print("[normal stop]")
r = Relay(["asked"])
check("result", stop(r), 0)
check("no task end", r.ended_at, None)

print("[access denied and the task end does not take: 1 after STOP_WAIT_S, one end only]")
r = Relay(["denied"], exit_after=10_000)
ends = []
r.end_task = lambda: ends.append(r.t)
check("result", stop(r), 1)
check("task ended once", len(ends), 1)
check("gave up at STOP_WAIT_S", app_main.STOP_WAIT_S <= r.t <= app_main.STOP_WAIT_S + 1, True)

print("[not running at all]")
r = Relay([], exit_after=0)
r.stop_at = -1.0
check("result", stop(r), 0)
check("never asked", r.asks, 0)

print("[the hard end is written to the relay's log first (review round 9 #25)]")
order = []
r = Relay(["denied"], exit_after=1.0)
real_end = r.end_task
r.end_task = lambda: (order.append("end"), real_end())
app_main._stop(r.running, r.ask, r.end_task, sleep=r.sleep, clock=r.clock,
               note=lambda msg: order.append(("note", msg)))
check("note before the end", [o if o == "end" else o[0] for o in order], ["note", "end"])
check("note names the task and the account", app_main.MAIN_TASK in order[0][1] and "账号" in order[0][1],
      True)

from _tmp import tmpdir  # noqa: E402
import os  # noqa: E402
log = tmpdir() / "relay.log"
log.write_text("10-11 08:00:00 INFO    ark.app  earlier line\n", encoding="utf-8")
os.environ["ARK_LOG_FILE"] = str(log)
app_main._log_line("停止请求被拒：测试")
lines = log.read_text(encoding="utf-8").splitlines()
check("earlier line kept", lines[0].endswith("earlier line"), True)
check("one line added", len(lines), 2)
check("relay's format, WARNING", " WARNING ark.app.stop  停止请求被拒：测试" in lines[1], True)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
