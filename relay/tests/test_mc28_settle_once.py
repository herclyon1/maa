"""A held #28 FAIL reaches the group once, even when a state file cannot be written
or read at the wrong moment.

Review of runs.settle_28 / runs._hold_28 (10-17):
  A. settle_28 pushed, then mc.restate raised (machinecheck.json not written): the
     entry stayed in machinecheck-runs.json and the next settle pushed it again.
  B. machinecheck-runs.json cannot be replaced (a Windows sharing violation on
     os.replace): _state_set dropped the error, the entry stayed, and every settle
     pushed the same FAIL again - 1, 2, 3 pushes over three ticks, no ERROR logged.
  C. _hold_28 wrote the hold, then read it back; one failed read made it push a plain
     FAIL at once while the entry stayed held, so the end of the hold pushed it again.

Each tick is one handle._flush_pending (it settles the held FAILs at its end), on the
held abort of test_mc28_one_alarm.py whose retries never get through.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_mc28_one_alarm as base  # its own scenarios run on import

from ark_relay.core import config as config_mod
from ark_relay.features.alarm import handle, unresolved
from ark_relay.features.makeup import makeup
from ark_relay.features.selfcheck import machinecheck as mc
from ark_relay.features.selfcheck.machinechecks import runs

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Errors(logging.Handler):
    """ERROR lines of runs.py's logger."""

    def __init__(self):
        super().__init__(logging.ERROR)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


ERRORS = Errors()
runs.log.addHandler(ERRORS)

REAL_AFTER, REAL_REFUSE = unresolved.after_makeup, makeup.refuse_rejected
REAL_WRITE_TEXT, REAL_MC_WRITE = config_mod.atomic_write_text, mc._write
REAL_READ_TEXT = Path.read_text
unresolved.after_makeup = lambda eng, rec, now=None: (unresolved.UNRESOLVED, "补跑也没成")
makeup.refuse_rejected = lambda eng, rec: None


def pushes(notes):
    return len(base.mc28_pushes(notes))


try:
    print("\n[A: machinecheck.json cannot be written once, right after #28's push]")
    e, notes, state = base.engine()
    base.book(e, base.ABORT, ok=False)
    check("held, nothing sent at booking", base.group(notes), [])
    left = {"n": 1}

    def _mc_write_fails_once(state_dir, data):
        if left["n"]:
            left["n"] -= 1
            raise OSError(13, "Permission denied (test)")
        return REAL_MC_WRITE(state_dir, data)

    mc._write = _mc_write_fails_once
    handle._flush_pending(e)
    mc._write = REAL_MC_WRITE
    first = pushes(notes)
    handle._flush_pending(e)
    check("the write did fail during that settle", left["n"], 0)
    check("#28 pushed once after the first tick", first, 1)
    check("…and still once after the second", pushes(notes), 1)
    check("nothing of #28 is left waiting", base.held_28(state), {})

    print("\n[B: machinecheck-runs.json cannot be replaced at all while the hold ends]")
    e, notes, state = base.engine()
    base.book(e, base.ABORT, ok=False)
    check("held, nothing sent at booking", base.group(notes), [])
    held_before = list(base.held_28(state))

    def _runs_file_locked(path, text, newline=None):
        if Path(path).name == runs.SEEN_FILE:
            raise PermissionError(13, "The process cannot access the file (test)")
        return REAL_WRITE_TEXT(path, text, newline)

    config_mod.atomic_write_text = _runs_file_locked
    ERRORS.lines.clear()
    counts = []
    try:
        for _ in range(3):
            handle._flush_pending(e)
            counts.append(pushes(notes))
    finally:
        config_mod.atomic_write_text = REAL_WRITE_TEXT
    check("#28 pushes over three ticks: once, not once per tick", counts, [1, 1, 1])
    check("the hold could not be cleared, and that is an ERROR",
          any("#28" in x and runs.SEEN_FILE in x for x in ERRORS.lines), True)
    check("the entry is still on file while the file is locked", list(base.held_28(state)), held_before)
    handle._flush_pending(e)
    check("once the file can be written: cleared", base.held_28(state), {})
    check("…without another push", pushes(notes), 1)

    print("\n[C: the hold is written, then one read of machinecheck-runs.json fails]")
    e, notes, state = base.engine()
    armed = {"read": False, "hit": 0}

    def _arm_after_hold(path, text, newline=None):
        armed["read"] = False
        REAL_WRITE_TEXT(path, text, newline)
        if Path(path).name == runs.SEEN_FILE and runs.HELD_28 in text and not armed["hit"]:
            armed["read"] = True

    def _read_fails_once(self, *a, **kw):
        if armed["read"] and self.name == runs.SEEN_FILE:
            armed["read"], armed["hit"] = False, armed["hit"] + 1
            raise OSError(5, "Input/output error (test)")
        return REAL_READ_TEXT(self, *a, **kw)

    config_mod.atomic_write_text = _arm_after_hold
    Path.read_text = _read_fails_once
    try:
        base.book(e, base.ABORT, ok=False)
    finally:
        config_mod.atomic_write_text, Path.read_text = REAL_WRITE_TEXT, REAL_READ_TEXT
    at_booking = pushes(notes)
    handle._flush_pending(e)
    handle._flush_pending(e)
    check("no #28 push at booking: the hold was written", at_booking, 0)
    check("#28 pushed once in all, when the hold ended", pushes(notes), 1)
    check("nothing of #28 is left waiting", base.held_28(state), {})
finally:
    unresolved.after_makeup, makeup.refuse_rejected = REAL_AFTER, REAL_REFUSE
    config_mod.atomic_write_text, mc._write, Path.read_text = REAL_WRITE_TEXT, REAL_MC_WRITE, REAL_READ_TEXT

print()
if fails or base.fails:
    print(f"✗ {len(fails)} 条没过：{fails}")
    sys.exit(1)
print("all checks passed")
