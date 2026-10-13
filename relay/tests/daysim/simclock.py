"""Fake clock and cooperative scheduler for the full-day relay simulator (daysim).

Design: daysim design.md section 1, "Fake clock" and "Scheduler and quiescence".
`install()` must run before any relay module is imported, so that modules which bind
`from datetime import datetime` or `from time import monotonic` at import time bind
the sim versions (the probe did the same, probe.py:69).

Time model
- Sim time is an epoch float, `now()`. Between jumps it is constant: code runs in
  zero sim time.
- It moves only inside a wait made by the main thread (`advance()`, or any sim wait
  the main thread makes: sleep, Condition / Event / queue waits, lock waits,
  Thread.join), and only when every live helper thread started after install() is
  parked in a sim wait. It then jumps to the earliest of: the main thread's own
  deadline, the next input scheduled with `at()`, the earliest parked helper's
  deadline. Due inputs run on the main thread; due helpers are woken; then the
  driver waits for quiescence again before the next jump.
- Sim waits: time.sleep, threading.Condition.wait (so Event.wait, queue.Queue
  get/put, Semaphore, Barrier, threading.Timer), threading.Lock / RLock acquire
  when contended, Thread.join, queue.SimpleQueue (the pure-Python one, so
  ThreadPoolExecutor workers park), and `park()` for the fakes of other units.
- A helper that stays unparked for `stall_s` real seconds while the main thread
  waits to move time is a sim error ("unparked"): it is recorded with the thread's
  stack, the thread is left out of quiescence until it parks again, and the day
  goes on.

File times
- os.stat / os.lstat / os.fstat and os.scandir entries: a time field that lies
  between the first step of the step log and real now was written while the sim
  ran, and is mapped to the sim time that was current at that real instant.
  Anything older (recorded inputs stamped with os.utime to their recorded times,
  files that predate the run) passes through unchanged. A file stamped with
  os.utime(times=/ns=) keeps its stamped mtime as long as that mtime is unchanged,
  even when the stamp falls inside the window. The rule needs no path prefix.
- The step log can be kept in a file (`steplog=`), so a later boot (a new process
  over the same state dir) maps the files an earlier boot wrote.
- Files written before install() keep their real mtimes: the caller stamps seed
  files with os.utime.
- Limit: the mapping relies on file timestamps and time.time_ns() reading the same
  clock at the same resolution. Measured on the Mac (APFS, 20000 writes): every
  mtime lay between time_ns() read before the write and after it. A file system
  with coarse timestamps can put a write made just after a step into the step
  before.
"""
from __future__ import annotations

import _thread
import bisect
import datetime as _dtmod
import functools
import heapq
import itertools
import logging
import os
import queue as _queue
import sys
import threading
import time as _time
import traceback
import types

# The originals, taken before anything is patched. Fakes of other units use these
# for real waits (REAL.sleep) and real stamps.
REAL = types.SimpleNamespace(
    time=_time.time, time_ns=_time.time_ns, monotonic=_time.monotonic, sleep=_time.sleep,
    localtime=_time.localtime, gmtime=_time.gmtime, strftime=_time.strftime,
    ctime=_time.ctime, asctime=_time.asctime,
    datetime=_dtmod.datetime, date=_dtmod.date,
    stat=os.stat, lstat=os.lstat, fstat=os.fstat, scandir=os.scandir, utime=os.utime,
    cond_wait=threading.Condition.wait, cond_notify=threading.Condition.notify,
    thread_start=threading.Thread.start, thread_join=threading.Thread.join,
    bootstrap_inner=threading.Thread._bootstrap_inner,
    Lock=threading.Lock, RLock=threading.RLock, SimpleQueue=_queue.SimpleQueue,
    queue_time=_queue.time, threading_time=threading._time,
)

UTC8 = _dtmod.timezone(_dtmod.timedelta(hours=8))
INFINITE = 0xFFFFFFFF          # win32event.INFINITE: advance() waits without a deadline
# design.md section 1: "A helper not parked within 2 s real time is a sim error".
STALL_S = 2.0
# Real-time poll of the driver while helpers run (stall checks) and of a helper parked
# on a predicate nobody pokes. Both are wake-ups for a re-check, not sim time.
DRIVER_POLL_S = 0.005
HELPER_POLL_S = 0.02


class SimError(RuntimeError):
    """The simulation itself cannot go on (stalled, ran past `until`)."""


class SimStopped(SystemExit):
    """Raised in a helper's sim wait after stop(). stop() makes threading.excepthook skip
    it (the default hook only skips SystemExit itself, not subclasses)."""


class _Rec:
    """One thread as the scheduler sees it."""

    __slots__ = ("deadline", "error", "ident", "name", "on", "ready", "result",
                 "rogue", "since", "state", "tracked", "wake")

    def __init__(self, name: str, tracked: bool, ident: int | None = None):
        self.name, self.tracked, self.ident = name, tracked, ident
        self.state = "run"          # run | park | done
        self.since = REAL.monotonic()
        self.deadline = self.ready = self.on = self.wake = self.error = None
        self.result = False
        self.rogue = False


class _State:
    def __init__(self):
        self.lock = _thread.allocate_lock()     # guards everything below
        self.kick = _thread.allocate_lock()     # released to wake the driver
        self.kick.acquire()
        self.installed = self.stopped = False
        self.t = 0.0
        self.mono_base = self.power_on = 0.0
        self.until: float | None = None
        self.stall_s = STALL_S
        self.main_ident = 0
        self.events: list = []                  # heap of (t, seq, fn, tag)
        self.seq = itertools.count()
        self.recs: dict[int, _Rec] = {}         # by thread ident
        self.unborn: set[_Rec] = set()          # started, not yet running Python code
        self.outputs: list[dict] = []
        self.steps_real: list[int] = []         # real time_ns of each clock change
        self.steps_sim: list[float] = []        # sim time from that real instant on
        self.steplog = None
        self.stamped: dict[str, int] = {}       # abspath -> mtime_ns set by os.utime


_st = _State()


# ------------------------------------------------------------------ public interface
def now() -> float:
    """Sim time, epoch seconds."""
    return _st.t


def iso(t: float | None = None) -> str:
    """Sim time (or `t`) as ISO 8601 in UTC+8, the events.jsonl / outputs.json form."""
    return REAL.datetime.fromtimestamp(_st.t if t is None else t, UTC8).isoformat()


def at(t, fn, tag: str = "") -> None:
    """Run `fn()` on the main thread when sim time reaches `t` (epoch float, aware
    datetime or ISO string). Inputs due at the same time run in the order given."""
    ts = _as_epoch(t)
    with _st.lock:
        heapq.heappush(_st.events, (ts, next(_st.seq), fn, tag))
    _kick()


def park(timeout: float | None = None, ready=None, *, on=None):
    """Sim wait for the calling thread.

    Returns the first value of `ready()` that is not None / False, or False when
    `timeout` sim seconds pass (None = no deadline); 0 counts as a value. `ready` is
    called under the scheduler's own (non-reentrant) lock, from whichever thread
    evaluates it (the driver, a notifier, a lock releaser), and the value it returns
    is handed to the waiter exactly once (an auto-reset handle may reset itself
    inside it). So it must be cheap, must not block, must not raise, and must not
    take a threading lock, log, notify or call poke(). On the main thread this drives
    the clock; on a helper it parks. `on` names the object waited on, for poke(on).
    """
    if not _st.installed:
        raise RuntimeError("simclock.install() has not run")
    ident = _thread.get_ident()
    if ident == _st.main_ident:
        return _drive(timeout, ready)
    return _park_helper(ident, timeout, ready, on)


def advance(handles_ready=None, timeout_ms=None):
    """The fake WaitForMultipleObjects: wait until `handles_ready()` returns a value
    other than None (the signalled index, returned) or `timeout_ms` passes (None
    returned). timeout_ms None or INFINITE waits without a deadline. Meant for the
    main thread; on a helper it parks the same way."""
    timeout = None if timeout_ms is None or timeout_ms == INFINITE else timeout_ms / 1000.0
    r = park(timeout, handles_ready)
    return None if r is False else r


def poke(on=None) -> None:
    """Re-check parked predicates now (all, or those waiting `on` an object), instead
    of on the next poll. Fakes call this after they signal a handle."""
    with _st.lock:
        for rec in list(_st.recs.values()):
            if rec.state == "park" and rec.ready is not None and (on is None or rec.on is on):
                r = rec.ready()
                if r is not None and r is not False:
                    _wake_locked(rec, r)
    _kick()


def out(kind: str, **fields) -> dict:
    """Record one output (push, power command, sim_error, ...) stamped with sim time."""
    with _st.lock:
        return _out_locked(kind, **fields)


def outputs() -> list[dict]:
    """Everything out() recorded, in order."""
    with _st.lock:
        return list(_st.outputs)


def sim_errors() -> list[dict]:
    """The outputs of kind sim_error."""
    return [o for o in outputs() if o["kind"] == "sim_error"]


def uptime_ms() -> int:
    """GetTickCount64: sim time since the World powered the machine on."""
    return int(round((_st.t - _st.power_on) * 1000))


def set_power_on(t) -> None:
    """The World powered the machine on at `t` (uptime_ms counts from here)."""
    _st.power_on = _as_epoch(t)


def to_sim(real_ns: int) -> int | None:
    """Sim time_ns that was current at real instant `real_ns`, or None when that instant
    lies outside the run (before its first step, or after real now)."""
    steps = _st.steps_real
    if not steps or real_ns < steps[0] or real_ns > REAL.time_ns():
        return None
    i = bisect.bisect_right(steps, real_ns) - 1
    return int(round(_st.steps_sim[i] * 1e9))


def stop() -> None:
    """End of the run: every parked helper is released with SimStopped, later helper
    waits raise it, main-thread waits return at once without moving time. Lock waits
    become real waits, so `with` blocks and finally clauses unwind cleanly."""
    prev = threading.excepthook        # the hook in place now, the relay's own if it set one

    def hook(args):
        if not issubclass(args.exc_type, SimStopped):
            prev(args)

    threading.excepthook = hook
    with _st.lock:
        _st.stopped = True
        for rec in list(_st.recs.values()):
            if rec.state == "park":
                rec.error = SimStopped()
                _wake_locked(rec, False)
    _kick()


def install(start, *, power_on=None, steplog=None, until=None, stall_s: float = STALL_S) -> None:
    """Patch the clock, the waits and the stat calls. Call once, before importing the relay.

    start: sim time to begin at (epoch float, aware datetime or ISO string).
    power_on: when the machine came up (uptime_ms, monotonic); default `start`.
    steplog: file that keeps the real->sim step log across boots of one day.
    until: a jump past this sim time is a SimError (a day that never stops).
    """
    if _st.installed:
        raise RuntimeError("simclock is already installed")
    t0 = _as_epoch(start)
    _st.t = t0
    _st.power_on = _st.mono_base = t0 if power_on is None else _as_epoch(power_on)
    _st.until = None if until is None else _as_epoch(until)
    _st.stall_s = float(stall_s)
    main = threading.main_thread()
    _st.main_ident = main.ident
    _st.recs[main.ident] = _Rec(main.name, tracked=False, ident=main.ident)
    if steplog is not None:
        _load_steplog(os.fspath(steplog))
    _st.installed = True
    _step_locked(t0)
    _patch_time()
    _patch_datetime()
    _patch_threading()
    _patch_os()
    # LogRecord.relativeCreated counts from logging's import; make it count from start.
    logging._startTime = int(round(t0 * 1e9))


# ------------------------------------------------------------------ scheduler core
def _as_epoch(t) -> float:
    if isinstance(t, str):
        t = REAL.datetime.fromisoformat(t)
    if isinstance(t, REAL.datetime):
        if t.tzinfo is None:
            raise ValueError(f"naive datetime {t!r}: give a zone")
        return t.timestamp()
    return float(t)


def _kick() -> None:
    k = _st.kick
    if k.locked():
        try:
            k.release()
        except RuntimeError:        # another kick released it first
            pass


def _out_locked(kind: str, **fields) -> dict:
    rec = {"t": iso(), "kind": kind, **fields}
    _st.outputs.append(rec)
    return rec


def _step_locked(t: float) -> None:
    """Move the clock and log the step (real time taken after quiescence)."""
    _st.t = t
    r = REAL.time_ns()
    if _st.steps_real and r <= _st.steps_real[-1]:
        r = _st.steps_real[-1] + 1
    _st.steps_real.append(r)
    _st.steps_sim.append(t)
    if _st.steplog is not None:
        _st.steplog.write(f"{r} {t!r}\n")
        _st.steplog.flush()


def _load_steplog(path: str) -> None:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r, s = line.split()
                    _st.steps_real.append(int(r))
                    _st.steps_sim.append(float(s))
    _st.steplog = open(path, "a", encoding="utf-8")     # kept open for the whole run


def _wake_locked(rec: _Rec, result) -> None:
    rec.state = "run"
    rec.result = result
    rec.ready = rec.on = None
    rec.since = REAL.monotonic()
    w = rec.wake
    if w is not None and w.locked():
        w.release()


def _rec_for(ident: int) -> _Rec:
    rec = _st.recs.get(ident)
    if rec is None:      # a thread started before install(): its timers count, it is not waited for
        rec = _st.recs[ident] = _Rec(f"untracked-{ident}", tracked=False, ident=ident)
    return rec


def _park_helper(ident: int, timeout, ready, on):
    with _st.lock:
        if _st.stopped:
            raise SimStopped()
        rec = _rec_for(ident)
        if ready is not None:
            r = ready()
            if r is not None and r is not False:
                return r
        if timeout is not None and timeout <= 0:
            return False
        rec.state = "park"
        rec.deadline = None if timeout is None else _st.t + float(timeout)
        rec.ready, rec.on, rec.result, rec.error = ready, on, False, None
        rec.rogue = False
        rec.wake = wake = _thread.allocate_lock()
        wake.acquire()
    _kick()
    poll = HELPER_POLL_S if ready is not None else -1
    while True:
        wake.acquire(True, poll)
        with _st.lock:
            if rec.state != "park":
                rec.wake = None
                if rec.error is not None:
                    err, rec.error = rec.error, None
                    raise err
                return rec.result
            if ready is not None:
                r = ready()
                if r is not None and r is not False:
                    _wake_locked(rec, r)
                    rec.wake = None
                    return r


def _drive(timeout, ready):
    """A main-thread wait: move sim time until `ready()` or the deadline."""
    deadline = None if timeout is None else _st.t + max(0.0, float(timeout))
    began = REAL.monotonic()
    while True:
        due: list | None = []
        with _st.lock:
            if ready is not None:
                r = ready()
                if r is not None and r is not False:
                    return r
            if _st.stopped or (deadline is not None and _st.t >= deadline):
                return False
            running = _running_locked(began)
            if not running and not _wake_ready_locked():
                due = _jump_locked(deadline)
                if due is not None and not due:
                    continue
        if due:
            _fire(due)
        else:
            _st.kick.acquire(True, DRIVER_POLL_S)


def _running_locked(began: float) -> list[_Rec]:
    """Tracked helpers not parked; flags the ones unparked for longer than stall_s."""
    real = REAL.monotonic()
    run = []
    for rec in itertools.chain(_st.unborn, _st.recs.values()):
        if not rec.tracked or rec.state != "run" or rec.rogue:
            continue
        if real - max(rec.since, began) > _st.stall_s:
            _flag_locked(rec)
            continue
        run.append(rec)
    return run


def _flag_locked(rec: _Rec) -> None:
    rec.rogue = True
    frame = sys._current_frames().get(rec.ident) if rec.ident is not None else None
    stack = "".join(traceback.format_stack(frame)[-8:]) if frame is not None else ""
    _out_locked("sim_error", what="unparked", thread=rec.name,
                detail=f"not parked in a sim wait within {_st.stall_s:g} s real time", stack=stack)


def _wake_ready_locked() -> bool:
    woke = False
    for rec in list(_st.recs.values()):
        if rec.state == "park" and rec.ready is not None:
            r = rec.ready()
            if r is not None and r is not False:
                _wake_locked(rec, r)
                woke = True
    return woke


def _jump_locked(deadline):
    """Everyone is parked: jump to the earliest wake, wake due helpers, return due inputs
    (None: nothing to jump to while a flagged thread still runs)."""
    cands = [] if deadline is None else [deadline]
    if _st.events:
        cands.append(_st.events[0][0])
    cands += [r.deadline for r in _st.recs.values() if r.state == "park" and r.deadline is not None]
    if not cands:
        if any(r.rogue and r.state == "run" for r in _st.recs.values()):
            return None         # only a flagged thread can still change something: wait for it
        _out_locked("sim_error", what="stalled",
                    detail="the main thread waits with no deadline, no input left, "
                           "and every helper is parked without a timer")
        raise SimError("stalled: nothing can wake the main thread")
    target = min(cands)
    if _st.until is not None and target > _st.until:
        _out_locked("sim_error", what="past_until", detail=f"next wake {iso(target)} is after {iso(_st.until)}")
        raise SimError(f"ran past {iso(_st.until)}")
    if target > _st.t:
        _step_locked(target)
    due = []
    while _st.events and _st.events[0][0] <= _st.t:
        due.append(heapq.heappop(_st.events))
    for rec in list(_st.recs.values()):
        if rec.state == "park" and rec.deadline is not None and rec.deadline <= _st.t:
            _wake_locked(rec, False)
    return due


def _fire(due) -> None:
    for _t, _seq, fn, tag in due:
        try:
            fn()
        except Exception:  # noqa: BLE001 - a broken input is reported, the day goes on
            out("sim_error", what="input", tag=tag, detail=traceback.format_exc()[-2000:])


# ------------------------------------------------------------------ time and datetime
def _now_ns() -> int:
    return int(round(_st.t * 1e9))


def _monotonic() -> float:
    return _st.t - _st.mono_base


def _monotonic_ns() -> int:
    return int(round((_st.t - _st.mono_base) * 1e9))


def _sleep(secs) -> None:
    secs = float(secs)
    if secs < 0:
        raise ValueError("sleep length must be non-negative")
    if secs == 0:
        REAL.sleep(0)
        return
    park(secs)


def _patch_time() -> None:
    t = _time
    t.time, t.time_ns = now, _now_ns
    t.monotonic, t.monotonic_ns = _monotonic, _monotonic_ns
    t.perf_counter, t.perf_counter_ns = _monotonic, _monotonic_ns
    t.sleep = _sleep
    t.localtime = lambda secs=None: REAL.localtime(_st.t if secs is None else secs)
    t.gmtime = lambda secs=None: REAL.gmtime(_st.t if secs is None else secs)
    t.strftime = lambda fmt, tt=None: REAL.strftime(fmt, REAL.localtime(_st.t) if tt is None else tt)
    t.ctime = lambda secs=None: REAL.ctime(_st.t if secs is None else secs)
    t.asctime = lambda tt=None: REAL.asctime(REAL.localtime(_st.t) if tt is None else tt)
    # Bound at their import, before install(): the deadline loops of Queue.get/put and
    # Condition.wait_for / Semaphore.acquire would otherwise count real time.
    _queue.time = _monotonic
    threading._time = _monotonic


class _DTMeta(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, REAL.datetime)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, REAL.datetime)


class FakeDT(REAL.datetime, metaclass=_DTMeta):
    """datetime.datetime with now/today/utcnow on sim time; real datetimes pass isinstance."""

    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(_st.t, tz)

    @classmethod
    def today(cls):
        return cls.fromtimestamp(_st.t)

    @classmethod
    def utcnow(cls):
        return cls.fromtimestamp(_st.t, _dtmod.timezone.utc).replace(tzinfo=None)


class _DateMeta(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, REAL.date)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, REAL.date)


class FakeDate(REAL.date, metaclass=_DateMeta):
    """datetime.date with today() on sim time; real dates pass isinstance."""

    @classmethod
    def today(cls):
        return cls.fromtimestamp(_st.t)


def _patch_datetime() -> None:
    _dtmod.datetime = FakeDT
    _dtmod.date = FakeDate


# ------------------------------------------------------------------ threading
class SimLock:
    """threading.Lock whose contended acquire is a sim wait."""

    __slots__ = ("__weakref__", "_lock", "_nwait")

    def __init__(self):
        self._lock = _thread.allocate_lock()
        self._nwait = 0

    def acquire(self, blocking=True, timeout=-1):
        if self._lock.acquire(False):
            return True
        if not blocking:
            if timeout != -1:
                raise ValueError("can't specify a timeout for a non-blocking call")
            return False
        if timeout < 0 and timeout != -1:
            raise ValueError("timeout value must be a non-negative number")
        if _st.stopped:
            return self._lock.acquire(True, timeout)
        with _st.lock:
            self._nwait += 1
        try:
            return park(None if timeout == -1 else timeout, self._try, on=self) is not False
        finally:
            with _st.lock:
                self._nwait -= 1

    def _try(self):
        return self._lock.acquire(False)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()

    def release(self):
        self._lock.release()
        if self._nwait:
            poke(self)

    def locked(self):
        return self._lock.locked()

    def _at_fork_reinit(self):
        self._lock._at_fork_reinit()

    def __repr__(self):
        return f"<simclock.SimLock {'locked' if self.locked() else 'unlocked'}>"


class SimRLock(threading._PyRLock):
    """threading.RLock built on SimLock, so Condition() and logging handlers park too."""

    def __init__(self):
        super().__init__()
        self._block = SimLock()


def _cond_wait(self, timeout=None):
    if not self._is_owned():
        raise RuntimeError("cannot wait on un-acquired lock")
    waiter = _thread.allocate_lock()
    waiter.acquire()
    self._waiters.append(waiter)
    saved = self._release_save()
    gotit = False
    try:
        gotit = park(timeout, functools.partial(waiter.acquire, False), on=self) is not False
        return gotit
    finally:
        self._acquire_restore(saved)
        if not gotit:
            try:
                self._waiters.remove(waiter)
            except ValueError:
                pass


def _cond_notify(self, n=1):
    REAL.cond_notify(self, n)
    poke(self)


def _thread_start(self):
    rec = _Rec(self.name, tracked=True)
    self._simclock_rec = rec
    with _st.lock:
        _st.unborn.add(rec)
    try:
        REAL.thread_start(self)
    except BaseException:
        with _st.lock:
            _st.unborn.discard(rec)
            rec.state = "done"
        raise


def _bootstrap_inner(self):
    rec = self.__dict__.get("_simclock_rec")
    if rec is not None:
        with _st.lock:
            rec.ident = _thread.get_ident()
            _st.recs[rec.ident] = rec
            _st.unborn.discard(rec)
    try:
        REAL.bootstrap_inner(self)
    finally:
        if rec is not None:
            with _st.lock:
                rec.state = "done"
            _kick()


def _thread_join(self, timeout=None):
    if not self._initialized:
        raise RuntimeError("Thread.__init__() not called")
    if not self._started.is_set():
        raise RuntimeError("cannot join thread before it is started")
    if self is threading.current_thread():
        raise RuntimeError("cannot join current thread")
    rec = self.__dict__.get("_simclock_rec")

    def gone():
        return (rec is not None and rec.state == "done") or not self.is_alive()

    if park(timeout, gone) is not False:
        REAL.thread_join(self)      # past its last line of Python: reap it


def _patch_threading() -> None:
    threading.Lock = SimLock
    threading.RLock = SimRLock
    threading.Condition.wait = _cond_wait
    threading.Condition.notify = _cond_notify
    threading.Thread.start = _thread_start
    threading.Thread._bootstrap_inner = _bootstrap_inner
    threading.Thread.join = _thread_join
    _queue.SimpleQueue = _queue._PySimpleQueue


# ------------------------------------------------------------------ file times
_TIME_FIELDS = (("st_atime_ns", "st_atime", 7), ("st_mtime_ns", "st_mtime", 8),
                ("st_ctime_ns", "st_ctime", 9), ("st_birthtime_ns", "st_birthtime", None))


def _key(path, dir_fd=None):
    if dir_fd is not None or isinstance(path, int):
        return None
    try:
        return os.path.abspath(os.fspath(path))
    except TypeError:
        return None


def _mapped(res, key):
    steps = _st.steps_real
    if not steps:
        return res
    lo, hi = steps[0], REAL.time_ns()
    cls, (seq, extra) = res.__reduce__()
    stamped = key is not None and _st.stamped.get(key) == extra.get("st_mtime_ns")
    seq = list(seq)
    changed = False
    for ns_key, f_key, idx in _TIME_FIELDS:
        if f_key not in extra or (stamped and f_key in ("st_atime", "st_mtime")):
            continue
        real_ns = extra[ns_key] if ns_key in extra else int(round(extra[f_key] * 1e9))
        if not lo <= real_ns <= hi:
            continue
        sim_ns = to_sim(real_ns)
        if sim_ns is None:
            continue
        changed = True
        extra[f_key] = sim_ns / 1e9
        if ns_key in extra:
            extra[ns_key] = sim_ns
        if idx is not None:
            seq[idx] = sim_ns // 1_000_000_000
    return cls(tuple(seq), extra) if changed else res


def _stat(path, *, dir_fd=None, follow_symlinks=True):
    return _mapped(REAL.stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks), _key(path, dir_fd))


def _lstat(path, *, dir_fd=None):
    return _mapped(REAL.lstat(path, dir_fd=dir_fd), _key(path, dir_fd))


def _fstat(fd):
    return _mapped(REAL.fstat(fd), None)


def _utime(path, times=None, *, dir_fd=None, follow_symlinks=True, **ns):
    REAL.utime(path, times, dir_fd=dir_fd, follow_symlinks=follow_symlinks, **ns)
    key = _key(path, dir_fd)
    if key is not None and (times is not None or ns.get("ns") is not None):
        stamped = REAL.stat(path, follow_symlinks=follow_symlinks).st_mtime_ns
        with _st.lock:
            _st.stamped[key] = stamped


class _Entry:
    """os.DirEntry whose stat() is mapped; everything else is the real entry's."""

    __slots__ = ("_e",)

    def __init__(self, e):
        self._e = e

    def __getattr__(self, name):
        return getattr(self._e, name)

    def __fspath__(self):
        return self._e.__fspath__()

    def __repr__(self):
        return repr(self._e)

    def stat(self, *, follow_symlinks=True):
        return _mapped(self._e.stat(follow_symlinks=follow_symlinks), _key(self._e.path))


class _Scandir:
    __slots__ = ("_it",)

    def __init__(self, it):
        self._it = it

    def __iter__(self):
        return self

    def __next__(self):
        return _Entry(next(self._it))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._it.close()

    def close(self):
        self._it.close()


def _scandir(path="."):
    return _Scandir(REAL.scandir(path))


def _patch_os() -> None:
    pairs = ((REAL.stat, _stat), (REAL.lstat, _lstat), (REAL.fstat, _fstat),
             (REAL.scandir, _scandir), (REAL.utime, _utime))
    # shutil decides on its fd-based rmtree by membership in these sets.
    for s in (os.supports_dir_fd, os.supports_fd, os.supports_follow_symlinks, os.supports_effective_ids):
        for real, fake in pairs:
            if real in s:
                s.add(fake)
    os.stat, os.lstat, os.fstat, os.scandir, os.utime = _stat, _lstat, _fstat, _scandir, _utime
