"""After an update or a rollback the relay starts again within seconds, not with the
watchdog's next check.

2026-10-11 (review round 7 #22, round 2 #13): restart_soon ran `cmd /c timeout /t 3 &
schtasks /run` detached. timeout.exe needs console input and returns at once in a
detached process, so the task run came while the relay still held the task and was
ignored (MultipleInstances IgnoreNew); only the watchdog brought it back, up to 30 s
later. Now packaging/launch.py `relaunch` waits for the relay's mutex to go before it
runs the task, and runs it again if the relay does not show.
"""
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
ROOT = RELAY.parent
sys.path.insert(0, str(RELAY))
sys.path.insert(0, str(ROOT / "packaging"))

import launch  # noqa: E402
import pkg_layout  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Machine:
    """A fake clock, the relay's mutex and the task. `exits_after`: polls until the old
    relay is gone (None = never). `ignored_runs`: task runs that start nothing."""

    def __init__(self, exits_after, ignored_runs=0, alive_now=True):
        self.t = 0.0
        self.polls = 0
        self.exits_after = exits_after
        self.ignored = ignored_runs
        self.alive = alive_now
        self.runs = []                  # clock time of each task run
        self.alive_at_run = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def running(self):
        self.polls += 1
        if self.alive and self.exits_after is not None and self.polls > self.exits_after:
            self.alive = False
        return self.alive

    def run_task(self):
        self.runs.append(self.t)
        self.alive_at_run.append(self.alive)
        if self.alive:
            return                      # IgnoreNew: the running one stays, nothing new
        if self.ignored:
            self.ignored -= 1
            return
        self.alive = True
        self.exits_after = None


def relaunch(m):
    return launch.relaunch(running=m.running, run_task=m.run_task, sleep=m.sleep, clock=m.clock)


print("[the old relay takes 6 s to exit: one task run, after it is gone]")
m = Machine(exits_after=12)
check("result", relaunch(m), 0)
check("task runs", len(m.runs), 1)
check("relay was gone at the run", m.alive_at_run, [False])
check("run came within a second of the exit", m.runs[0] <= 6.5, True)

print("[the first task run starts nothing: it is run again]")
m = Machine(exits_after=4, ignored_runs=1)
check("result", relaunch(m), 0)
check("task runs", len(m.runs), 2)
check("second run within TASK_UP_S of the first", m.runs[1] - m.runs[0] <= launch.TASK_UP_S + 0.5, True)

print("[the relay is already gone when the helper starts (rollback stops it first)]")
m = Machine(exits_after=0)
check("result", relaunch(m), 0)
check("task run at once", m.runs, [0.0])

print("[the old relay never exits: no task run, exit 1]")
m = Machine(exits_after=None)
check("result", relaunch(m), 1)
check("task runs", m.runs, [])
check("gave up after EXIT_WAIT_S", launch.EXIT_WAIT_S <= m.t <= launch.EXIT_WAIT_S + 1, True)

print("[no task run starts anything: exit 2 after TASK_TRIES]")
m = Machine(exits_after=0, ignored_runs=99)
check("result", relaunch(m), 2)
check("task runs", len(m.runs), launch.TASK_TRIES)

print("[the watchdog starts it first: the helper's run is a no-op and it reports 0]")
m = Machine(exits_after=2)
real_run = m.run_task


def watchdog_first():
    m.alive = True                      # the watchdog's run won the race
    m.exits_after = None
    real_run()


m.run_task = watchdog_first
check("result", relaunch(m), 0)

print("[restart_soon starts launch.py relaunch with the package's pythonw, detached]")
app = Path("C:/Program Files/ArkRelay")
calls = []


def popen(cmd, creationflags=0):
    calls.append((cmd, creationflags))


pkg_layout.restart_soon(app, popen=popen)
check("one process", len(calls), 1)
cmd, flags = calls[0]
check("command", cmd, [str(app / "runtime" / "python" / "pythonw.exe"), str(app / "launch.py"),
                       "relaunch"])
check("no cmd.exe / timeout.exe in it", any("timeout" in c or c.lower().startswith("cmd") for c in cmd),
      False)
if sys.platform == "win32":
    import subprocess
    check("detached", bool(flags & subprocess.DETACHED_PROCESS), True)
    check("own process group", bool(flags & subprocess.CREATE_NEW_PROCESS_GROUP), True)

print("[a job that forbids breakaway: started again without that flag]")
calls.clear()


def popen_no_breakaway(cmd, creationflags=0):
    calls.append(creationflags)
    if len(calls) == 1 and sys.platform == "win32":
        raise PermissionError(5, "Access is denied")


pkg_layout.restart_soon(app, popen=popen_no_breakaway)
if sys.platform == "win32":
    import subprocess
    check("two tries", len(calls), 2)
    check("second without breakaway", bool(calls[1] & subprocess.CREATE_BREAKAWAY_FROM_JOB), False)
else:
    check("started", len(calls), 1)

print("[launch.py's names match app_main's]")
import app_main  # noqa: E402
check("mutex", launch.MUTEX, app_main.MUTEX)
check("task", launch.MAIN_TASK, pkg_layout.MAIN_TASK)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
