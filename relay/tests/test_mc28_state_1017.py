"""Machine check #28's held FAILs and state/machinecheck-runs.json under the failures a
Windows relay meets: one cause reaches the group once, and no alarm is lost.

Review of 46e7e5bc (10-17), one scenario per finding:
  1. covered_28 read the file once to see whether anything was held, and returned
     without a word when that read failed: the 「没证据」 alarm went out, the cover was
     not written, and settle_28 pushed the same cause as #28's own FAIL.
  2. _hold_28, when the hold could not be kept, marked the run sent (#28|<run id>)
     before judge pushed: a push that failed then left an older entry of the run on
     file dropped by settle_28 without any push.
  3. judge wrote machinecheck.json with nothing around it: a Windows lock on it raised
     out of judge and none of that judging's FAILs was pushed.
  4. A machinecheck-runs.json that stayed broken (bad JSON, a UTF-8 BOM from a hand
     edit, not a table) stopped every settle without a word and made every later
     write an ERROR.
  5. A brief lock on os.replace was one group ERROR per refused write.
  6. #7-miss / #28-miss were read apart from their write: one failed read started
     the streak over at 1.
  7. _seen read as an empty set on a failed read: #6 / #24a judged a settled
     restart again.
  8. pushes._push_unverified marked its record before covered_28: a state.json that
     could not take the mark skipped the cover, logged 「没证据」这一项没能推到群里
     though it went out, and #28 then pushed the same cause again.

Review of 9743738a (10-17):
  9. held_stuck sent a group ERROR for an unreadable stretch even when the last good
     read held nothing - noise origin/main did not have.
 10. every read that kept failing slept all of mc.LOCK_WAITS, about six times a
     booking: ~3 s of the engine thread per booking while a lock lasted.
 11. _state_read(None) raised TypeError (Path(None)); the old _state_get gave None.
 12. StateStore._flush had no lock waits, and unresolved.send let a failed day mark
     after a push that went out escape: _push_now skipped the #28 cover and #28
     pushed the same cause again, with a misleading 「没能推到群里」 line.

Review of 87b9ee74 (10-17):
 13. covered_28 wrote through _state_update on every 「没证据」 alarm: with the file
     locked it logged a group ERROR about a cover it had nothing to write, even when
     the last good read held nothing - noise origin/main did not have (as item 9).
"""
import contextlib
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_mc28_one_alarm as base  # its own scenarios run on import

from ark_relay.core import statestore, texts
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.alarm import handle, pushes, runchecks
from ark_relay.features.selfcheck import machinecheck as mc
from ark_relay.features.selfcheck.machinechecks import runs
from _tmp import tmpdir

fails = []
DAY = "2026-10-08"
R1, R2, R3 = (f"{DAY}/endfield/MaaEnd-0{h}-00-00" for h in (1, 2, 3))
MC28 = texts.machinecheck_failed("#28", "")
REAL_READ_TEXT, REAL_REPLACE, REAL_MC_WRITE = Path.read_text, os.replace, mc._write
REAL_TASK_WINDOW, REAL_WINDOW = runs._task_window, runs.cm.maafw_window
REAL_TASK_TIMES, REAL_TRAIL = runs.cm.task_times, runs.maaend_fwlog.trail_table
REAL_RUNS_TIME, REAL_SS_WRITE = runs.time, statestore.atomic_write_text
NO_WAITS = (0.0, 0.0, 0.0)


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Errors(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


ERRORS = Errors()
for name in ("ark.runs", "ark.machinecheck", "ark.pushes", "ark.unresolved", "ark.statestore"):
    logging.getLogger(name).addHandler(ERRORS)
pushes.log.addHandler(ERRORS)


class Notes:
    def __init__(self, errs=()):
        self.sent, self.errs = [], list(errs)

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body))
        return list(self.errs)


class Rec:
    def __init__(self, rid):
        self.run_id, self.script, self.user = rid, "MaaEnd", "endfield"


def entry(rid):
    return {"script": "MaaEnd", "user": "endfield", "day": DAY, "tasks": ["装备制造"],
            "evidence": f"{rid} 装备制造没做成", "covered": []}


def fresh(*held, raw=None):
    """A state folder whose machinecheck-runs.json holds `held` and the other keys, or
    the bytes / text `raw`."""
    state = tmpdir() / "state"
    state.mkdir()
    data = {runs.HELD_28: {rid: entry(rid) for rid in held}, "#7-miss": 1, "#28-miss": 1, "#6": [R1]}
    raw = json.dumps(data, ensure_ascii=False) if raw is None else raw
    (state / runs.SEEN_FILE).write_bytes(raw.encode("utf-8") if isinstance(raw, str) else raw)
    return state


def on_file(state, key):
    return json.loads((state / runs.SEEN_FILE).read_text(encoding="utf-8-sig")).get(key)


def marks():
    got = set()
    return got, (lambda day, key: (day, key) in got, lambda day, key: got.add((day, key)))


def settle(state, alerted, notes):
    """settle_28 with every hold over; the run ids #28 pushed so far."""
    runs.settle_28(state, lambda script, user: True, lambda day: [], notes, alerted=alerted)
    return sorted(rid for rid in (R1, R2, R3) for t, b in notes.sent if t.startswith(MC28) and rid in b)


def ctx28(state, rid, alerted):
    return {"rec": Rec(rid), "held": [rid], "state_dir": state, "day": DAY, "alerted": alerted,
            "unverified_alarm": []}


class read_fails:
    """Path.read_text of machinecheck-runs.json fails `n` times with `exc`."""

    def __init__(self, exc, n=1):
        self.exc, self.n = exc, n

    def __enter__(self):
        def _read(path, *a, **kw):
            if self.n and path.name == runs.SEEN_FILE:
                self.n -= 1
                raise self.exc
            return REAL_READ_TEXT(path, *a, **kw)
        Path.read_text = _read
        return self

    def __exit__(self, *a):
        Path.read_text = REAL_READ_TEXT


class replace_locked:
    """os.replace onto machinecheck-runs.json refused `n` times as Windows refuses a
    file another handle holds open (ERROR_SHARING_VIOLATION -> PermissionError)."""

    def __init__(self, n):
        self.n = n

    def __enter__(self):
        def _replace(src, dst, *a, **kw):
            if self.n and Path(dst).name == runs.SEEN_FILE:
                self.n -= 1
                raise PermissionError(13, "being used by another process (test)")
            return REAL_REPLACE(src, dst, *a, **kw)
        os.replace = _replace
        return self

    def __exit__(self, *a):
        os.replace = REAL_REPLACE


class no_waits:
    """A lock that outlasts every wait, without the test sleeping through the waits."""

    def __enter__(self):
        self.was = getattr(mc, "LOCK_WAITS", None)
        mc.LOCK_WAITS = NO_WAITS
        return self

    def __exit__(self, *a):
        if self.was is None:
            del mc.LOCK_WAITS
        else:
            mc.LOCK_WAITS = self.was


def judge_one(state, result, notifier):
    """mc.judge with one check of event 「run」 that returns `result`."""
    saved = dict(mc.CHECKS)
    mc.CHECKS.clear()
    mc.CHECKS["#28"] = mc.Check("#28", saved["#28"].what, "A", ("run",), lambda ctx: result)
    try:
        return mc.judge(state, "run", {}, notifier=notifier)
    finally:
        mc.CHECKS.clear()
        mc.CHECKS.update(saved)


def mc28_sent(notes):
    return len([t for t, _ in notes.sent if t.startswith(MC28)])


def section(title, fn):
    print(f"\n[{title}]")
    ERRORS.lines.clear()
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - a crash is this item failing; the others still run
        check(f"{title}: ran to the end", f"{type(exc).__name__}: {exc}", "")
    finally:
        Path.read_text, os.replace, mc._write = REAL_READ_TEXT, REAL_REPLACE, REAL_MC_WRITE
        runs.time, statestore.atomic_write_text = REAL_RUNS_TIME, REAL_SS_WRITE


mc.load()


def item1():
    for exc in (PermissionError(13, "locked (test)"), OSError(5, "Input/output error (test)")):
        state = fresh(R1)
        with read_fails(exc) as rf:
            runs.covered_28(state, "MaaEnd", DAY, ["装备制造"])
        check(f"the first read did fail ({type(exc).__name__})", rf.n, 0)
        check("…the cover is on file anyway",
              ((on_file(state, runs.HELD_28) or {}).get(R1) or {}).get("covered"), ["装备制造"])
        _, alerted = marks()
        check("…so the end of the hold pushes nothing of R1", settle(state, alerted, Notes()), [])
    state = fresh(R1)
    before = (state / runs.SEEN_FILE).read_bytes()
    runs.covered_28(state, "MaaEnd", "2026-10-09", ["装备制造"])
    check("an alarm about another day changes nothing", (state / runs.SEEN_FILE).read_bytes(), before)


def item2():
    state = fresh(R1)                     # an older entry of R1 on file
    got, alerted = marks()
    with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=99):
        r = runs._fail_28(ctx28(state, R1, alerted), ["装备制造"], entry(R1)["evidence"])
    check("the hold could not be kept: a FAIL pushed at once", (r.status, r.deferred), (mc.FAIL, False))
    check("…not marked sent before its push", got, set())
    judge_one(state, r, Notes(errs=["企业微信 500 (test)"]))
    check("the push failed: still not marked sent", got, set())
    check("…so the older entry of R1 is pushed when its hold ends", settle(state, alerted, Notes()), [R1])

    state = fresh(R1)
    got, alerted = marks()
    with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=99):
        r = runs._fail_28(ctx28(state, R1, alerted), ["装备制造"], entry(R1)["evidence"])
    notes = Notes()
    judge_one(state, r, notes)
    check("a push that went out is marked sent", got, {(DAY, f"#28|{R1}")})
    check("…so the older entry of R1 is dropped without a second push",
          (mc28_sent(notes), settle(state, alerted, Notes())), (1, []))


def item3():
    state = tmpdir() / "state"
    state.mkdir()

    def _locked(state_dir, data):
        raise PermissionError(13, "The process cannot access the file (test)")

    mc._write = _locked
    notes = Notes()
    try:
        judge_one(state, mc.Result(mc.FAIL, "装备制造没做成 (test)"), notes)
    except OSError as exc:
        check("judge does not raise", type(exc).__name__, "")
    check("machinecheck.json locked: the FAIL is pushed all the same", mc28_sent(notes), 1)
    check("…and the write that failed is an ERROR", any(mc.STATE_FILE in x for x in ERRORS.lines))


def item4():
    good = json.dumps({runs.HELD_28: {R1: entry(R1)}, "#6": [R1]}, ensure_ascii=False)
    state = fresh(raw=b"\xef\xbb\xbf" + good.encode("utf-8"))
    check("a file with a UTF-8 BOM (Notepad) is read", sorted(runs._state_get(state, runs.HELD_28) or {}), [R1])
    check("…and written to, keeping what was in it",
          (runs._state_set(state, "#7-miss", 3), sorted(on_file(state, runs.HELD_28) or {})), (True, [R1]))
    check("…without an ERROR", ERRORS.lines, [])

    for name, text in (("broken JSON", good[:-9]), ("not a table", "[1, 2]")):
        ERRORS.lines.clear()
        state = fresh(raw=text)
        _, alerted = marks()
        r = runs._fail_28(ctx28(state, R3, alerted), ["装备制造"], entry(R3)["evidence"])
        runs._state_set(state, "#7-miss", 1)
        runs._mark_seen(state, "#6", [R2])
        copies = sorted(p.name for p in state.iterdir() if ".corrupt-" in p.name)
        check(f"{name}: copied aside as it was",
              (len(copies), (state / copies[0]).read_text(encoding="utf-8") if copies else None), (1, text))
        check(f"{name}: one ERROR over three writes", len([x for x in ERRORS.lines if runs.SEEN_FILE in x]), 1)
        if name == "broken JSON":
            check("…naming the held FAIL it took with it", any(R1 in x for x in ERRORS.lines))
        check(f"{name}: then written from empty: R3 held, the others written",
              (r.deferred, sorted(on_file(state, runs.HELD_28) or {}), on_file(state, "#7-miss"),
               on_file(state, "#6")), (True, [R3], 1, [R2]))



def item4b():
    state = fresh(R1, R2)
    check("read once while it can be read", sorted(runs._state_get(state, runs.HELD_28) or {}), [R1, R2])

    class Eng:
        class cfg:
            state_dir = None
        _pending = {}
        notifier = Notes()
        state = type("S", (), {"read_ledger": staticmethod(lambda day: [])})()

        def _script_running(self, name):
            return False

        def _already_alerted(self, day, key):
            return False

        def _mark_alerted(self, day, key):
            pass

    Eng.cfg.state_dir = state
    eng = Eng()
    with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
        for _ in range(3):
            runchecks._settle_held(eng)
    stuck = [x for x in ERRORS.lines if runs.SEEN_FILE in x]
    check("three ticks locked: one ERROR", len(stuck), 1)
    check("…naming the holds stuck behind it", bool(stuck) and R1 in stuck[0] and R2 in stuck[0])
    runchecks._settle_held(eng)
    check("readable again: both settled, each pushed once",
          (mc28_sent(eng.notifier), on_file(state, runs.HELD_28)), (2, {}))


def item5():
    state = fresh(R1)
    with replace_locked(2) as rl:
        wrote = runs._state_set(state, "#7-miss", 2)
    check("os.replace refused twice, then let through", rl.n, 0)
    check("…written, no ERROR", (wrote, on_file(state, "#7-miss"), ERRORS.lines), (True, 2, []))
    check("…no temp file left behind", sorted(p.name for p in state.iterdir()), [runs.SEEN_FILE])
    with no_waits(), replace_locked(99):
        wrote = runs._state_set(state, "#7-miss", 5)
    check("a lock that outlasts the waits: not written, one ERROR",
          (wrote, on_file(state, "#7-miss"), len([x for x in ERRORS.lines if "PermissionError" in x])),
          (False, 2, 1))


def item6():
    t0 = datetime(2026, 10, 8, 10, 0, tzinfo=SERVER_TZ)
    t1 = datetime(2026, 10, 8, 10, 2, tzinfo=SERVER_TZ)
    rec = type("R", (), {"run_id": R2, "script": "MaaEnd", "user": "endfield", "started": t0})()
    runs._task_window = lambda text, task: (t0, t1)
    runs.cm.maafw_window = lambda d, a, b: ([], "maafw.log 里这一段没有（test）")
    try:
        state = fresh()
        with read_fails(PermissionError(13, "locked (test)")) as rf:
            r = runs._c7({"rec": rec, "raw": {}, "log_text": "", "state_dir": state})
        check("#7: the read did fail once", rf.n, 0)
        check("#7: 1 on file + this run = 2, not started over at 1", on_file(state, "#7-miss"), 2)
        check("…so this second run in a row is the FAIL", getattr(r, "status", None), mc.FAIL)
    finally:
        runs._task_window, runs.cm.maafw_window = REAL_TASK_WINDOW, REAL_WINDOW
    e = {"t0": t0.isoformat(), "t1": t1.isoformat(), "found": False, "unread": True}
    runs.cm.task_times = lambda text: {"装备制造": (t0, t1)}
    runs.maaend_fwlog.trail_table = lambda d, times, text="": ({"装备制造": dict(e)}, "日志换过（test）")
    try:
        state = fresh()
        with read_fails(OSError(5, "Input/output error (test)")) as rf:
            runs._c28({"rec": rec, "raw": {}, "log_text": "", "state_dir": state, "held": []})
        check("#28: the read did fail once", rf.n, 0)
        check("#28: 1 on file + this run = 2, not started over at 1", on_file(state, "#28-miss"), 2)
        state = fresh()
        with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=99):
            r = runs._c28({"rec": rec, "raw": {}, "log_text": "", "state_dir": state, "held": []})
        check("#28: the count unreadable: the unread task waits, nothing reset on file",
              (r, on_file(state, "#28-miss")), (None, 1))
    finally:
        runs.cm.task_times, runs.maaend_fwlog.trail_table = REAL_TASK_TIMES, REAL_TRAIL


def item7():
    t0 = datetime(2026, 10, 8, 10, 0, tzinfo=SERVER_TZ)
    rec = type("R", (), {"run_id": R2, "script": "MaaEnd", "user": "endfield", "started": t0})()
    restarts = {R1: {"version": "v1.2.3", "started": t0.isoformat(), "done": R2, "held": False}}

    def ctx(state):
        return {"rec": rec, "raw": {}, "state_dir": state, "update_restarts": restarts, "relay_errors": []}

    state = fresh()                       # R1 is on #6's seen list
    with read_fails(PermissionError(13, "locked (test)")):
        r = runs._update_restart_check(ctx(state), "#6")
    check("one failed read: R1 judged already, not judged again", r, None)
    with no_waits(), read_fails(OSError(5, "Input/output error (test)"), n=99):
        r = runs._update_restart_check(ctx(state), "#24a")
    check("unreadable: not judged (it may have been)", r, None)
    check("…and not marked seen meanwhile", on_file(state, "#24a"), None)
    check("readable again: judged then",
          getattr(runs._update_restart_check(ctx(state), "#24a"), "status", None), mc.PASS)


def item8():
    e, notes, state = base.engine()
    base.book(e, base.ABORT, ok=False)
    real_mark = e._mark_alerted
    mine = f"{pushes.UNVERIFIED_BY}|"

    def _mark(day, key):
        if key.startswith(mine):
            raise PermissionError(13, "state.json locked (test)")
        return real_mark(day, key)

    e._mark_alerted = _mark
    try:
        base.book(e, base.RETRY, ok=True)
    finally:
        e._mark_alerted = real_mark
    handle._flush_pending(e)
    base.show(notes)
    check("one group message for the abort and the retry", len(base.group(notes)), 1)
    check("…no 「上机核对没过：#28」 of its own", base.mc28_pushes(notes), [])
    check("no ERROR saying the 「没证据」 alarm did not go out", [x for x in ERRORS.lines if "没能推到群里" in x], [])
    check("the mark that could not be written is an ERROR saying so",
          any("已经发出" in x and "没记下" in x for x in ERRORS.lines))
    check("nothing of #28 is left waiting", base.held_28(state), {})


class Eng4b:
    """The engine attributes runchecks._settle_held reads."""
    _pending = {}
    state = type("S", (), {"read_ledger": staticmethod(lambda day: [])})()

    def __init__(self, state):
        self.cfg = type("C", (), {"state_dir": state})()
        self.notifier = Notes()

    def _script_running(self, name):
        return False

    def _already_alerted(self, day, key):
        return False

    def _mark_alerted(self, day, key):
        pass


def item9():
    state = fresh()                       # nothing held
    check("read once while it can be read: nothing held", runs._state_get(state, runs.HELD_28), {})
    eng = Eng4b(state)
    with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
        for _ in range(3):
            runchecks._settle_held(eng)
    check("locked, the last good read held nothing: no ERROR",
          [x for x in ERRORS.lines if runs.SEEN_FILE in x], [])
    ERRORS.lines.clear()
    state = fresh(R1)                     # never read in this process: what is held is unknown
    with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
        for _ in range(3):
            runchecks._settle_held(Eng4b(state))
    stuck = [x for x in ERRORS.lines if runs.SEEN_FILE in x]
    check("locked, never read: one ERROR saying what is held is not known",
          (len(stuck), bool(stuck) and "不知道" in stuck[0]), (1, True))


class Sleeps:
    """runs.time with a sleep that only counts."""

    def __init__(self):
        self.n = 0

    def sleep(self, s):
        self.n += 1


def one_pass():
    """runs.one_pass, or no pass at all where there is none (before 10-17)."""
    return getattr(runs, "one_pass", contextlib.nullcontext)()


class ss_no_waits:
    """statestore.LOCK_WAITS set to no waits (set even where it does not exist yet)."""

    def __enter__(self):
        self.was = getattr(statestore, "LOCK_WAITS", None)
        statestore.LOCK_WAITS = NO_WAITS

    def __exit__(self, *a):
        if self.was is None:
            del statestore.LOCK_WAITS
        else:
            statestore.LOCK_WAITS = self.was


def item10():
    state = fresh(R1)
    clock = runs.time = Sleeps()
    with read_fails(PermissionError(13, "locked (test)"), n=999):
        runs._state_read(state)
        runs._state_read(state)
    waits = len(mc.LOCK_WAITS)
    check("outside a booking or tick each locked read waits all of LOCK_WAITS", clock.n, 2 * waits)
    clock.n = 0
    with read_fails(PermissionError(13, "locked (test)"), n=999), one_pass():
        got = [runs._state_read(state) for _ in range(6)]
    check("inside one: only the first read waits, every read is None (never {})",
          (clock.n, got), (waits, [None] * 6))
    clock.n = 0
    with read_fails(PermissionError(13, "locked (test)"), n=999), one_pass():
        runs._state_read(state)
    check("the next booking or tick waits once again", clock.n, waits)
    clock.n = 0
    with one_pass():
        with read_fails(PermissionError(13, "locked (test)"), n=999):
            runs._state_read(state)
        runs._state_read(state)           # readable again: the lock is over
        with read_fails(PermissionError(13, "locked (test)"), n=999):
            runs._state_read(state)
    check("a lock that ends and comes back in one pass is waited out again", clock.n, 2 * waits)

    e, notes, st = base.engine()
    clock.n = 0
    with read_fails(PermissionError(13, "locked (test)"), n=9999):
        base.book(e, base.ABORT, ok=False)
        handle._flush_pending(e)
    check("one booking and one tick with the file locked: LOCK_WAITS waited once each",
          clock.n, 2 * waits)


def item11():
    clock = runs.time = Sleeps()
    try:
        got = (runs._state_read(None), runs._state_get(None, runs.HELD_28), runs._seen(None, "#6"),
               runs.held_stuck(None), runs._state_set(None, "#7-miss", 1))
    except TypeError as exc:
        got = f"TypeError: {exc}"
    check("no state folder: unreadable, nothing raised", got, (None, None, None, None, False))
    check("…without waiting", clock.n, 0)


def item12():
    st = tmpdir() / "state"
    st.mkdir()
    store = statestore.StateStore(st)
    left = [2]

    def _locked_twice(path, text):
        if left[0] and Path(path).name == statestore.FILE:
            left[0] -= 1
            raise PermissionError(13, "state.json being scanned (test)")
        return REAL_SS_WRITE(path, text)

    statestore.atomic_write_text = _locked_twice
    try:
        with ss_no_waits():
            store.set("marks", f"alerted:{DAY}", ["k"])
        wrote = json.loads((st / statestore.FILE).read_text(encoding="utf-8"))["marks"].get(f"alerted:{DAY}")
    except OSError as exc:
        wrote = f"{type(exc).__name__}: {exc}"
    finally:
        statestore.atomic_write_text = REAL_SS_WRITE
    check("state.json locked twice, then let through: the day mark is written", wrote, ["k"])



def item12b():
    st = tmpdir() / "state"
    st.mkdir()
    statestore.StateStore(st).set("marks", f"alerted:{DAY}", ["k"])
    good = (st / statestore.FILE).read_text(encoding="utf-8")

    def _read(path, *a, **kw):
        if path.name == statestore.FILE:
            raise PermissionError(13, "state.json being scanned (test)")
        return REAL_READ_TEXT(path, *a, **kw)

    Path.read_text = _read
    try:
        with ss_no_waits():
            statestore.StateStore(st).set("marks", f"alerted:{DAY}", ["k", "k2"])
        raised = ""
    except OSError as exc:
        raised = type(exc).__name__
    finally:
        Path.read_text = REAL_READ_TEXT
    check("a write whose read stays locked raises, never writing the empty fallback over it",
          (raised, (st / statestore.FILE).read_text(encoding="utf-8")), ("PermissionError", good))


def item12c():
    e, notes, state = base.engine()
    base.book(e, base.ABORT, ok=False)
    real_mark = e._mark_alerted

    def _mark(day, key):
        raise PermissionError(13, "state.json locked (test)")

    e._mark_alerted = _mark
    try:
        base.book(e, base.RETRY, ok=True)
    finally:
        e._mark_alerted = real_mark
    handle._flush_pending(e)
    base.show(notes)
    check("every day mark refused: one group message for the abort and the retry", len(base.group(notes)), 1)
    check("…no 「上机核对没过：#28」 of its own", base.mc28_pushes(notes), [])
    check("…not kept to be sent again", e._unsent_unresolved, [])
    check("no ERROR saying the 「没证据」 alarm did not go out", [x for x in ERRORS.lines if "没能推到群里" in x], [])
    said = [x for x in ERRORS.lines if "没记" in x]
    check("one ERROR saying the alarm went out and its mark did not land",
          (len(said), bool(said) and "已进群" in said[0]), (1, True))
    check("nothing of #28 is left waiting", base.held_28(state), {})



def item12d():
    e, notes, state = base.engine()
    base.book(e, base.ABORT, ok=False)
    mark = f"{pushes.UNVERIFIED_KIND}|"

    def _locked(path, text):
        # state.json held by a scan from the 「没证据」 day mark on: that write and every
        # later one of the booking are refused.
        if Path(path).name == statestore.FILE and mark in text:
            raise PermissionError(13, "state.json being scanned (test)")
        return REAL_SS_WRITE(path, text)

    statestore.atomic_write_text = _locked
    try:
        with ss_no_waits():
            base.book(e, base.RETRY, ok=True)
    finally:
        statestore.atomic_write_text = REAL_SS_WRITE
    handle._flush_pending(e)
    base.show(notes)
    check("state.json refused the mark: one group message for the abort and the retry", len(base.group(notes)), 1)
    check("…no 「上机核对没过：#28」 of its own", base.mc28_pushes(notes), [])
    check("no ERROR saying the 「没证据」 alarm did not go out", [x for x in ERRORS.lines if "没能推到群里" in x], [])
    said = [x for x in ERRORS.lines if "没记" in x]
    check("one ERROR for the lock: the alarm went out, its mark did not land",
          (len(said), bool(said) and "已进群" in said[0]), (1, True))
    check("the mark not on file is not answered from memory either",
          any(str(k).startswith(mark) for k in e.state.store.get("marks", f"alerted:{DAY}") or []), False)


def item13():
    e, notes, state = base.engine()
    (state / runs.SEEN_FILE).write_text(json.dumps({"#6": []}), encoding="utf-8")
    check("read once while it can be read: nothing held", runs._state_get(state, runs.HELD_28), None)
    cover = "已由「没证据」报警带上"
    with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
        base.book(e, base.RETRY, ok=True)       # a 「没证据」 run, nothing held
        handle._flush_pending(e)
    check("the 「没证据」 alarm reaches the group once", len(base.group(notes)), 1)
    check("locked, the last good read held nothing: no ERROR about the #28 cover",
          [x for x in ERRORS.lines if cover in x], [])
    check("…the write the booking could not make is still one ERROR",
          len([x for x in ERRORS.lines if runs.SEEN_FILE in x]), 1)
    ERRORS.lines.clear()
    state = fresh(R1)                     # never read in this process: what is held is unknown
    with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
        runs.covered_28(state, "MaaEnd", DAY, ["装备制造"])
    check("locked, never read: the cover not written is still an ERROR",
          len([x for x in ERRORS.lines if cover in x]), 1)
    ERRORS.lines.clear()
    state = fresh(R1)
    check("read once: R1 held", list(runs._state_get(state, runs.HELD_28) or {}), [R1])
    with no_waits(), read_fails(PermissionError(13, "locked (test)"), n=999):
        runs.covered_28(state, "MaaEnd", DAY, ["装备制造"])
    check("locked while a FAIL was held: the cover not written is still an ERROR",
          len([x for x in ERRORS.lines if cover in x]), 1)


for title, fn in (("1: covered_28 when its read fails once", item1),
                  ("2: a held run's FAIL pushed at once is marked sent only after its push", item2),
                  ("3: machinecheck.json locked while judging", item3),
                  ("4: a machinecheck-runs.json that stays broken", item4),
                  ("4b: held FAILs stuck behind a machinecheck-runs.json that stays locked", item4b),
                  ("5: a brief Windows lock on os.replace", item5),
                  ("6: #7 / #28 miss counts in one read and write", item6),
                  ("7: #6 / #24a when the seen list cannot be read", item7),
                  ("8: 「没证据」 sent, then its record's mark cannot be written", item8),
                  ("9: locked while nothing is held: no ERROR", item9),
                  ("10: a lock is waited out once per booking or tick", item10),
                  ("11: no state folder", item11),
                  ("12: state.json locked a moment while an alarm's day mark is written", item12),
                  ("12b: state.json locked while a write reads it first", item12b),
                  ("12c: 「没证据」 sent, then no day mark can be written", item12c),
                  ("12d: 「没证据」 sent, then state.json refuses its day mark", item12d),
                  ("13: covered_28 locked while nothing is held: no ERROR", item13)):
    section(title, fn)

print()
if fails or base.fails:
    print(f"✗ {len(fails)} 条没过：{fails}")
    sys.exit(1)
print("all checks passed")
