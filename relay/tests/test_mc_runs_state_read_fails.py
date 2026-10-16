"""A failed read of state/machinecheck-runs.json never rewrites it from nothing.

Review of commit 28306025 (10-17), left open there:
  _hold_28's first read and _state_set's own read both fell back to {} when the read
  failed, so one failed read at the moment a hold was written rewrote the file with
  that one hold: every other held #28 FAIL was gone and never pushed (a lost alarm),
  and the seen lists (#6 / #24a) and miss counts (#7-miss, #28-miss) went with it.

Now a read that fails leaves the file as it was and is an ERROR; a hold that cannot
be kept is pushed at once and marked sent (#28|<run id>), so an older entry of the
same run on file is not pushed again when its hold ends. Also a Windows sharing
violation on os.replace: the file stays as it was, nothing is left behind.
"""
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                  ARK_AUTOMAS_DIR=str(TMP / "nowhere"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                  ARK_LOG_FILE=str(TMP / "relay.log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import texts                                    # noqa: E402
from ark_relay.features.selfcheck import machinecheck as mc         # noqa: E402
from ark_relay.features.selfcheck.machinechecks import runs         # noqa: E402

fails = []
DAY = "2026-10-08"
R1, R2, R3 = (f"{DAY}/endfield/MaaEnd-0{h}-00-00" for h in (1, 2, 3))
REAL_READ_TEXT, REAL_REPLACE = Path.read_text, os.replace
MC28 = texts.machinecheck_failed("#28", "")


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
runs.log.addHandler(ERRORS)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body))
        return []


class Rec:
    def __init__(self, rid):
        self.run_id, self.script, self.user = rid, "MaaEnd", "endfield"


def entry(rid):
    return {"script": "MaaEnd", "user": "endfield", "day": DAY, "tasks": ["装备制造"],
            "evidence": f"{rid} 装备制造没做成", "covered": []}


def fresh(*held):
    """A state folder whose machinecheck-runs.json holds `held` and the other keys."""
    state = tmpdir() / "state"
    state.mkdir()
    data = {runs.HELD_28: {rid: entry(rid) for rid in held}, "#7-miss": 2, "#28-miss": 1,
            "#6": ["a", "b"], "#24a": ["x"]}
    (state / runs.SEEN_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return state


def marks():
    got = set()
    return got, (lambda day, key: (day, key) in got, lambda day, key: got.add((day, key)))


def ctx(state, rid, alerted):
    return {"rec": Rec(rid), "held": [rid], "state_dir": state, "day": DAY, "alerted": alerted,
            "unverified_alarm": []}


class read_fails:
    """Reads of machinecheck-runs.json fail `n` times with `exc` (a string: read as that text)."""

    def __init__(self, exc, n=1):
        self.exc, self.n = exc, n

    def __enter__(self):
        def _read(path, *a, **kw):
            if self.n and path.name == runs.SEEN_FILE:
                self.n -= 1
                if isinstance(self.exc, str):
                    return self.exc
                raise self.exc
            return REAL_READ_TEXT(path, *a, **kw)
        Path.read_text = _read
        return self

    def __exit__(self, *a):
        Path.read_text = REAL_READ_TEXT


class replace_locked:
    """os.replace onto machinecheck-runs.json fails as Windows does while another
    handle has it open (ERROR_SHARING_VIOLATION -> PermissionError)."""

    def __enter__(self):
        def _replace(src, dst, *a, **kw):
            if Path(dst).name == runs.SEEN_FILE:
                raise PermissionError(13, "The process cannot access the file because it is "
                                          "being used by another process (test)")
            return REAL_REPLACE(src, dst, *a, **kw)
        os.replace = _replace
        return self

    def __exit__(self, *a):
        os.replace = REAL_REPLACE


def raw(state):
    return (state / runs.SEEN_FILE).read_bytes()


def held(state):
    return sorted(runs._state_get(state, runs.HELD_28) or {})


def settle(state, alerted, notes):
    """settle_28 with every hold over; the run ids #28 pushed so far."""
    runs.settle_28(state, lambda script, user: True, lambda day: [], notes, alerted=alerted)
    return sorted(rid for rid in (R1, R2, R3) for t, b in notes.sent if t.startswith(MC28) and rid in b)


def r28(state, rid, alerted):
    return runs._fail_28(ctx(state, rid, alerted), ["装备制造"], entry(rid)["evidence"])


mc.load()
BAD_READS = [("OSError (Windows sharing violation on read)", PermissionError(13, "locked (test)")),
             ("ValueError (broken JSON)", '{"#28-held": {'),
             ("ValueError (UnicodeDecodeError)", UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"))]

try:
    for name, exc in BAD_READS:
        print(f"\n[a hold is written while one read fails: {name}; R1, R2 held]")
        state = fresh(R1, R2)
        before = raw(state)
        got, alerted = marks()
        ERRORS.lines.clear()
        with read_fails(exc) as rf:
            r = r28(state, R3, alerted)
        check("the read did fail", rf.n, 0)
        check("machinecheck-runs.json is left as it was", raw(state) == before)
        check("R3 is a plain FAIL, pushed at once", (r.status, r.deferred), (mc.FAIL, False))
        check("…and marked sent", got, {(DAY, f"#28|{R3}")})
        check("the failed read is an ERROR", any(runs.SEEN_FILE in x for x in ERRORS.lines))
        check("R1 and R2 still reach the group when their hold ends", settle(state, alerted, Notes()),
              sorted([R1, R2]))
        check("nothing of #28 is left waiting", held(state), [])

    print("\n[_state_set while one read fails: the other keys stay]")
    state = fresh(R1, R2)
    before = raw(state)
    with read_fails(OSError(5, "Input/output error (test)")):
        wrote = runs._state_set(state, "#7-miss", 3)
    check("not written", wrote, False)
    check("machinecheck-runs.json is left as it was", raw(state) == before)
    check("a later set keeps every other key", runs._state_set(state, "#7-miss", 3), True)
    data = json.loads(raw(state))
    check("…held FAILs, seen lists and counts", (sorted(data[runs.HELD_28]), data["#6"], data["#28-miss"],
                                                data["#7-miss"]), (sorted([R1, R2]), ["a", "b"], 1, 3))

    print("\n[_mark_seen while one read fails: the seen list is not cut to the new ids]")
    state = fresh()
    with read_fails('{"#6": ['):
        runs._mark_seen(state, "#6", ["c"])
    check("the list as it was", runs._state_get(state, "#6"), ["a", "b"])
    runs._mark_seen(state, "#6", ["c"])
    check("…and added to once it reads", runs._state_get(state, "#6"), ["a", "b", "c"])

    print("\n[the file reads as something other than a table: nothing is written]")
    state = fresh(R1)
    before = raw(state)
    ERRORS.lines.clear()
    with read_fails('[]', n=99):
        wrote = runs._state_set(state, "#28-miss", 0)
    check("not written, and that is an ERROR", (wrote, len([x for x in ERRORS.lines if runs.SEEN_FILE in x])),
          (False, 1))
    check("machinecheck-runs.json is left as it was", raw(state) == before)

    print("\n[R1 held already; judged again while the read fails: one push, not two]")
    state = fresh(R1, R2)
    got, alerted = marks()
    with read_fails(OSError(5, "Input/output error (test)")):
        r = r28(state, R1, alerted)
    check("R1 pushed at once", r.deferred, False)
    check("…so its hold ending pushes only R2", settle(state, alerted, Notes()), [R2])
    check("nothing of #28 is left waiting", held(state), [])

    print("\n[Windows: os.replace onto machinecheck-runs.json is refused (sharing violation)]")
    state = fresh(R1, R2)
    before = raw(state)
    got, alerted = marks()
    ERRORS.lines.clear()
    with replace_locked():
        r3 = r28(state, R3, alerted)
        r1 = r28(state, R1, alerted)
    check("machinecheck-runs.json is left as it was", raw(state) == before)
    check("no temp file left behind", sorted(p.name for p in state.iterdir()), [runs.SEEN_FILE])
    check("R3 and R1 are plain FAILs, pushed at once", (r3.deferred, r1.deferred), (False, False))
    check("…and marked sent", got, {(DAY, f"#28|{R3}"), (DAY, f"#28|{R1}")})
    check("each refused write is an ERROR", len([x for x in ERRORS.lines if "PermissionError" in x]), 2)
    notes = Notes()
    with replace_locked():
        first = settle(state, alerted, notes)
        second = settle(state, alerted, notes)
    check("while still locked: R2 pushed once over two ticks, R1 not again", (first, second), ([R2], [R2]))
    check("…both still on file", held(state), sorted([R1, R2]))
    third = settle(state, alerted, notes)
    check("unlocked: cleared without another push", (third, held(state)), ([R2], []))
finally:
    Path.read_text, os.replace = REAL_READ_TEXT, REAL_REPLACE

print()
if fails:
    print(f"✗ {len(fails)} 条没过：{fails}")
    sys.exit(1)
print("all checks passed")
