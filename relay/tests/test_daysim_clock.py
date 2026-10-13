"""daysim's fake clock and scheduler (relay/tests/daysim/simclock.py).

design.md section 6, unit W1. This pins: the clock jumps straight to the earliest
wake; it never moves while a helper thread runs; a helper not parked within 2 s real
time is flagged; date.today / strftime / logging stamps follow sim time; os.stat on an
input returns its recorded mtime and on a file written during the run the sim time it
was written at, also from a later boot (a new process over the same step log).
"""
import io
import logging
import os
import queue
import shutil
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# The machine's zone where it can be set (time.tzset is Unix only,
# docs.python.org/3/library/time.html#time.tzset). Every expected stamp below is also
# computed from the real time functions, so the checks hold in any zone (the Windows CI).
if hasattr(time, "tzset"):
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "daysim"))
import simclock  # noqa: E402 - after the path set-up above
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def require(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f": {detail}"))
    if not ok:
        fails.append(name)


R = simclock.REAL
D = tmpdir("daysim-clock-")
OLD = D / "before-install.txt"
OLD.write_text("written before the sim started", encoding="utf-8")
STEPLOG = D / "steps.log"
S0 = R.datetime(2026, 10, 12, 8, 40, tzinfo=simclock.UTC8).timestamp()

simclock.install("2026-10-12T08:40:00+08:00", power_on="2026-10-12T08:38:00+08:00", steplog=STEPLOG)

# Only now the relay: its `from datetime import datetime` must bind the sim class.
import datetime  # noqa: E402
from ark_relay.features.evidence import logslice  # noqa: E402


def steps_since(base):
    """(sim offset, real ns) of every clock step after `base`, from the step log."""
    rows = []
    for line in STEPLOG.read_text(encoding="utf-8").splitlines():
        r, s = line.split()
        if float(s) > base:
            rows.append((round(float(s) - base, 3), int(r)))
    return rows


def spawn(name, fn):
    t = threading.Thread(target=fn, name=name, daemon=True)
    t.start()
    return t


print("\n[clock reads follow sim time]")
local0 = R.localtime(S0)
check("time.time", time.time(), S0)
check("time.time_ns", time.time_ns(), int(S0) * 1_000_000_000)
check("datetime.now", datetime.datetime.now(), R.datetime.fromtimestamp(S0))
check("datetime.now(tz)", datetime.datetime.now(simclock.UTC8).strftime("%m-%d %H:%M"), "10-12 08:40")
check("datetime.utcnow", datetime.datetime.utcnow(), R.datetime(2026, 10, 12, 0, 40))
check("date.today", datetime.date.today(), R.date.fromtimestamp(S0))
from datetime import date as date_after, datetime as dt_after  # noqa: E402

check("`from datetime import datetime` after install binds the sim class", dt_after, simclock.FakeDT)
check("`from datetime import date` after install binds the sim class", date_after, simclock.FakeDate)
check("a relay module bound the sim class at import", logslice.datetime, simclock.FakeDT)
require("a real datetime is still a datetime.datetime", isinstance(R.datetime(2026, 1, 1), datetime.datetime))
require("a sim datetime is a real datetime", isinstance(datetime.datetime.now(), R.datetime))
require("a real date is a datetime.date", isinstance(R.date(2026, 1, 1), datetime.date))
require("a real date is not a datetime.datetime", not isinstance(R.date(2026, 1, 1), datetime.datetime))
check("time.strftime without a time", time.strftime("%Y-%m-%d %H:%M:%S"), R.strftime("%Y-%m-%d %H:%M:%S", local0))
check("time.strftime with a time is untouched", time.strftime("%Y", R.localtime(0)), R.strftime("%Y", R.localtime(0)))
check("time.localtime()", tuple(time.localtime()), tuple(local0))
check("time.localtime(0) is untouched", tuple(time.localtime(0)), tuple(R.localtime(0)))
check("time.gmtime() hour:minute", time.gmtime()[3:5], (0, 40))
check("time.ctime()", time.ctime(), R.ctime(S0))
check("monotonic counts from power-on", time.monotonic(), 120.0)
check("perf_counter is the same clock", time.perf_counter(), 120.0)
check("GetTickCount64 (uptime_ms)", simclock.uptime_ms(), 120_000)
simclock.set_power_on("2026-10-12T08:30:00+08:00")
check("uptime_ms after set_power_on", simclock.uptime_ms(), 600_000)
if hasattr(time, "tzset"):
    check("Beijing wall clock on this host", time.strftime("%Y-%m-%d %H:%M:%S"), "2026-10-12 08:40:00")

buf = io.StringIO()
log = logging.getLogger("ark.test_daysim_clock")
handler = logging.StreamHandler(buf)
handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
log.addHandler(handler)
log.propagate = False
log.warning("first")
check("logging stamp", buf.getvalue().split(" first")[0], R.strftime("%Y-%m-%d %H:%M:%S", local0))
rec = simclock.out("push", ch="group", title="t")
check("out() stamps sim time", (rec["t"], rec["kind"], rec["ch"]), ("2026-10-12T08:40:00+08:00", "push", "group"))

print("\n[the clock jumps to the earliest wake]")
base = simclock.now()
trace = []
ev = threading.Event()
q = queue.Queue()


def a_sleeper():
    time.sleep(30)
    trace.append(("sleep 30", simclock.now() - base))


def b_event():
    got = ev.wait(10)
    trace.append(("event.wait 10", simclock.now() - base, got))


def c_queue():
    try:
        q.get(timeout=20)
    except queue.Empty:
        trace.append(("queue.get 20", simclock.now() - base))


simclock.at(simclock.iso(base + 15), lambda: trace.append(("input", simclock.now() - base)), "t+15")
helpers = [spawn("a", a_sleeper), spawn("b", b_event), spawn("c", c_queue)]
r0 = R.monotonic()
got = simclock.advance(lambda: None, 60_000)
trace.append(("main", simclock.now() - base))
real_s = R.monotonic() - r0
check("main's wait times out", got, None)
check("wakes in time order, each at its own sim time", trace,
      [("event.wait 10", 10.0, False), ("input", 15.0), ("queue.get 20", 20.0), ("sleep 30", 30.0), ("main", 60.0)])
check("the clock visited only the wake times", [s for s, _ in steps_since(base)], [10.0, 15.0, 20.0, 30.0, 60.0])
require("an hour of waits took no real waiting", real_s < 1.5, f"{real_s:.2f} s")
for t in helpers:
    t.join()
check("joining finished helpers moves no time", simclock.now() - base, 60.0)
base = simclock.now()
flag = []
simclock.at(base + 7, lambda: flag.append(1), "signal")
check("advance returns index 0 when an input signals it", simclock.advance(lambda: 0 if flag else None, 60_000), 0)
check("at the input's time", simclock.now() - base, 7.0)
check("timeout 0 returns at once", simclock.advance(lambda: None, 0), None)
check("and moves nothing", simclock.now() - base, 7.0)

print("\n[the clock never moves while a helper runs]")
base = simclock.now()
seen = {}


def worker():
    time.sleep(5)
    seen["start"] = (simclock.now() - base, R.time_ns())
    R.sleep(0.3)                       # real work: running, not parked
    seen["end"] = (simclock.now() - base, R.time_ns())
    time.sleep(5)


t = spawn("worker", worker)
simclock.advance(None, 20_000)
steps = steps_since(base)
check("sim time did not move during the helper's real work", (seen["start"][0], seen["end"][0]), (5.0, 5.0))
check("steps", [s for s, _ in steps], [5.0, 10.0, 20.0])
check("no step was taken while it ran", [s for s, r in steps if seen["start"][1] < r < seen["end"][1]], [])
require("the next step came after it parked", steps[1][1] > seen["end"][1], str(steps))
t.join()

print("\n[locks, conditions, joins, timers and pools are sim waits]")
base = simclock.now()
lock = threading.Lock()
got_lock = []


def holder():
    with lock:
        spawn("waiter", lambda: (lock.acquire(), got_lock.append(simclock.now() - base), lock.release()))
        time.sleep(5)


t = spawn("holder", holder)
simclock.advance(None, 10_000)
check("a helper blocked on a lock waits in sim time and gets it at release", got_lock, [5.0])
t.join()
cv = threading.Condition()
woke = []


def cv_waiter():
    with cv:
        woke.append(("ready", simclock.now()))
        cv.wait()
        woke.append(("woken", simclock.now()))


base = simclock.now()
t = spawn("cv", cv_waiter)
simclock.park(None, lambda: woke or None)       # the main thread waits until it is in
with cv:
    cv.notify()
t.join()
check("a notify hands over at the same sim time", [w[1] - base for w in woke], [0.0, 0.0])
q2 = queue.Queue()
out_q = []
t = spawn("q", lambda: out_q.append((q2.get(), simclock.now() - base)))
q2.put("x")
t.join()
check("a queue hand-over at the same sim time", out_q, [("x", 0.0)])
t = spawn("long", lambda: time.sleep(20))
t.join(5)
check("join(5) on a helper still asleep returns after 5 sim seconds", (simclock.now() - base, t.is_alive()), (5.0, True))
t.join()
check("join() returns when it ends", simclock.now() - base, 20.0)
base = simclock.now()
fired = []
threading.Timer(15, lambda: fired.append(simclock.now() - base)).start()
simclock.advance(None, 30_000)
check("threading.Timer(15) fires 15 sim seconds later", fired, [15.0])
base = simclock.now()
with ThreadPoolExecutor(max_workers=2) as pool:
    fut = pool.submit(lambda: (time.sleep(3), simclock.now() - base)[1])
    check("a pool task sleeping 3 s", fut.result(), 3.0)
check("pool shut down without moving time", simclock.now() - base, 3.0)
check("no sim error so far", simclock.sim_errors(), [])

print("\n[a helper not parked within 2 s real time is flagged]")
base = simclock.now()
stop_busy = []


def busy():
    while not stop_busy:
        R.sleep(0.01)                  # a busy loop: never in a sim wait


t = spawn("busy-helper", busy)
r0 = R.monotonic()
simclock.advance(None, 1000)
flagged_after = R.monotonic() - r0
errs = simclock.sim_errors()
check("one sim error", [(e["what"], e["thread"]) for e in errs], [("unparked", "busy-helper")])
stack = errs[0]["stack"] if errs else ""
require("it names the busy loop in the stack", "busy" in stack, stack[-300:])
require("flagged after 2 s real time, not long after", 2.0 <= flagged_after < 3.0, f"{flagged_after:.2f} s")
check("then the day went on", simclock.now() - base, 1.0)
stop_busy.append(1)
t.join()
check("joining the flagged thread once it ends", t.is_alive(), False)

print("\n[file times: inputs keep recorded times, run writes get sim times]")
inp = D / "input.json"
inp.write_text("{}", encoding="utf-8")
recorded = R.datetime(2026, 10, 12, 6, 0, tzinfo=simclock.UTC8).timestamp()
os.utime(inp, (recorded, recorded))
check("os.stat on an input", os.stat(inp).st_mtime, recorded)
check("Path.stat on an input", inp.stat().st_mtime, recorded)
check("os.path.getmtime on an input", os.path.getmtime(inp), recorded)
check("os.lstat on an input", os.lstat(inp).st_mtime, recorded)
check("a file from before install is untouched", os.stat(OLD).st_mtime_ns, R.stat(OLD).st_mtime_ns)
s1 = simclock.now()
f1 = D / "written-1.txt"
f1.write_text("one", encoding="utf-8")
R.sleep(0.05)                          # keep the writes clear of the step on coarse file clocks
simclock.advance(None, 90_000)
R.sleep(0.05)
f2 = D / "written-2.txt"
f2.write_text("two", encoding="utf-8")
require("the real mtime is a real time, a day after the sim", R.stat(f1).st_mtime > s1 + 3600, str(R.stat(f1).st_mtime))
check("os.stat on a file written at s1", os.stat(f1).st_mtime, s1)
check("st_mtime_ns too", os.stat(f1).st_mtime_ns, int(s1) * 1_000_000_000)
check("the tuple field ST_MTIME too", os.stat(f1)[stat.ST_MTIME], int(s1))
check("os.stat on a file written 90 s later", os.stat(f2).st_mtime, s1 + 90)
with open(f2, "rb") as fh:
    check("os.fstat", os.fstat(fh.fileno()).st_mtime, s1 + 90)
with os.scandir(D) as it:
    by_name = {e.name: e.stat().st_mtime for e in it}
check("os.scandir entries", (by_name["input.json"], by_name["written-1.txt"], by_name["written-2.txt"]),
      (recorded, s1, s1 + 90))
check("os.walk still lists them", sorted(f for _r, _d, fs in os.walk(D) for f in fs if f.startswith("written")),
      ["written-1.txt", "written-2.txt"])
f3 = D / "copy-of-1.txt"
shutil.copy2(f1, f3)
check("shutil.copy2 carries the sim mtime", os.stat(f3).st_mtime, s1)
f4 = D / "stamped.txt"
f4.write_text("x", encoding="utf-8")
inside = R.time_ns() - 1_000_000
os.utime(f4, ns=(inside, inside))
check("an explicit stamp inside the run's real window is kept", os.stat(f4).st_mtime_ns, inside)
R.sleep(0.05)
f4.write_text("rewritten", encoding="utf-8")
check("rewritten afterwards, it maps again", os.stat(f4).st_mtime, simclock.now())
check("to_sim on a real instant before the run", simclock.to_sim(R.stat(OLD).st_mtime_ns), None)

print("\n[a later boot maps what an earlier boot wrote]")
child = D / "child.py"
child.write_text(
    "import os, sys\n"
    f"sys.path.insert(0, {str(HERE / 'daysim')!r})\n"
    "import simclock\n"
    f"simclock.install({s1 + 3600!r}, steplog={str(STEPLOG)!r})\n"
    f"print(os.stat({str(f1)!r}).st_mtime, os.stat({str(f2)!r}).st_mtime, os.stat({str(inp)!r}).st_mtime)\n",
    encoding="utf-8")
child_out = D / "child.out"
with open(child_out, "w", encoding="utf-8") as fh:
    rc = subprocess.run([sys.executable, "-I", str(child)], stdout=fh, stderr=subprocess.STDOUT, check=False).returncode
text = child_out.read_text(encoding="utf-8")
check("the child ran", rc, 0)
check("it sees both files at their sim times and the input at its recorded time",
      [float(x) for x in text.split()] if rc == 0 else text, [s1, s1 + 90, recorded])

print("\n[stop() ends parked helpers]")
ended = []


def forever():
    try:
        time.sleep(10 ** 9)
    except simclock.SimStopped:
        ended.append("stopped")


t = spawn("forever", forever)
simclock.park(None, lambda: any(r.state == "park" for r in simclock._st.recs.values()
                                 if r.name == "forever") or None)
simclock.stop()
for _ in range(300):
    if not t.is_alive():
        break
    R.sleep(0.01)
check("the parked helper got SimStopped and ended", (ended, t.is_alive()), (["stopped"], False))
before = simclock.now()
time.sleep(100)
check("a main-thread wait after stop() moves nothing", simclock.now(), before)
try:
    raise simclock.SimError("x")
except RuntimeError as exc:
    check("SimError is a RuntimeError", str(exc), "x")
check("a SimLock reports its state", repr(simclock.SimLock()), "<simclock.SimLock unlocked>")
require("threading.RLock is the sim one", isinstance(threading.RLock(), simclock.SimRLock))
check("only the one sim error", len(simclock.sim_errors()), 1)
check("outputs keep everything out() recorded", [o["kind"] for o in simclock.outputs()], ["push", "sim_error"])


def main():
    if fails:
        print(f"\n{len(fails)} failed: {fails}")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
