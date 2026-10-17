"""state.json reads that a Windows lock refuses, and alarm day marks written by two
writers: no alarm pushed twice, no mark lost, no relay state lost.

Review of 99999b8e (10-17), one scenario per finding:
  1. A plain read of state.json that hit a lock (PermissionError, or any OSError)
     copied the healthy file aside as state.json.corrupt-* and cached {} until the
     file's mtime changed: every alarm day mark answered "not sent", so an alarm going
     through unresolved.send was pushed a second time. A write that met an OSError
     other than a lock on its read put the near-empty fallback over the file; the
     legacy sweep did the same after a plain read that a lock refused; a state.json
     holding JSON that is not a table crashed every read.
  2. daymarks._mark_alerted built the day's list from a read outside the write lock
     (served from the cached copy) and set() wrote it whole: a mark another writer
     made in between was dropped.
"""
import json
import logging
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay.core import statestore
from ark_relay.core.statestore import StateStore
from ark_relay.features.alarm import handle, unresolved

fails = []
DAY = "2026-10-08"
MARK = f"alerted:{DAY}"
REAL_READ_TEXT = Path.read_text
NO_WAITS = (0.0, 0.0, 0.0)


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Lines(logging.Handler):
    """WARNING and up on ark.statestore: each such line is a group message."""

    def __init__(self, logger):
        super().__init__(logging.WARNING)
        self.lines = []
        logger.addHandler(self)

    def emit(self, record):
        self.lines.append(record.getMessage())


LINES = Lines(statestore.log)


class read_fails:
    """Path.read_text of state.json raises `exc` (default: the PermissionError a
    Windows sharing violation becomes) while inside, every time."""

    def __init__(self, exc=None):
        self.exc = exc or PermissionError(13, "state.json being scanned (test)")
        self.tries = 0

    def __enter__(self):
        self.waits = statestore.LOCK_WAITS
        statestore.LOCK_WAITS = NO_WAITS

        def _read(path, *a, **kw):
            if Path(path).name == statestore.FILE:
                self.tries += 1
                raise self.exc
            return REAL_READ_TEXT(path, *a, **kw)
        Path.read_text = _read
        return self

    def __exit__(self, *a):
        Path.read_text = REAL_READ_TEXT
        statestore.LOCK_WAITS = self.waits


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", alert=False, **kw):
        self.sent.append(title)
        return []


class Eng:
    """What unresolved.send and daymarks use of the engine: one long-lived store."""

    def __init__(self, d):
        self.state = types.SimpleNamespace(dir=d, store=StateStore(d))
        self.notifier = Notes()

    def _already_alerted(self, day, key):
        return handle._already_alerted(self, day, key)

    def _mark_alerted(self, day, key):
        return handle._mark_alerted(self, day, key)


def folder(data=None):
    d = tmpdir()
    if data is not None:
        (d / statestore.FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return d


def bump(d, by=5):
    """Move state.json's mtime on, as a write by another writer does."""
    st = (d / statestore.FILE).stat()
    os.utime(d / statestore.FILE, (st.st_atime, st.st_mtime + by))


def on_disk(d):
    return json.loads(REAL_READ_TEXT(d / statestore.FILE, encoding="utf-8"))


def corrupt_copies(d):
    return sorted(p.name for p in d.glob(statestore.FILE + ".corrupt-*"))


def forget(d):
    """This process has read nothing of `d` yet (a relay just started)."""
    getattr(statestore, "_LAST_GOOD", {}).pop(str(d / statestore.FILE), None)


def section(title, fn):
    print(f"\n[{title}]")
    LINES.lines.clear()
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - a crash is this item failing; the others still run
        check(f"{title}: ran to the end", f"{type(exc).__name__}: {exc}", "")
    finally:
        Path.read_text = REAL_READ_TEXT


def item1a():
    d = folder()
    eng = Eng(d)
    title = "明日方舟 没跑成（test）"
    check("first push goes out", unresolved.send(eng, DAY, "未解决", "run-1", title, "body"), True)
    StateStore(d).set("versions", "okww", "v9")     # another writer: the file's mtime moves on
    bump(d)
    with read_fails():
        again = unresolved.send(eng, DAY, "未解决", "run-1", title, "body")
        marked = handle._already_alerted(eng, DAY, unresolved._key("未解决", "run-1"))
    check("state.json locked: the replayed record is not pushed again",
          (again, eng.notifier.sent.count(title)), (True, 1))
    check("state.json locked: its day mark still reads as sent", marked, True)
    check("a healthy file a lock refused is not copied aside", corrupt_copies(d), [])
    check("no WARNING / ERROR (group message) for a lock on a plain read", LINES.lines, [])
    check("the lock gone, the next read sees what the other writer wrote",
          eng.state.store.get("versions", "okww"), "v9")


def item1b():
    d = folder({"marks": {MARK: ["k"]}, "modes": {"debug_until": "2026-10-08 23:00"}})
    before = (d / statestore.FILE).read_bytes()
    forget(d)
    cold = StateStore(d)
    with read_fails() as lock:
        cold.get("marks", MARK)
    check("a first read waits the lock out before giving up", lock.tries, len(NO_WAITS) + 1)
    check("the lock gone, the same instance reads the file (nothing cached from the lock)",
          cold.get("marks", MARK), ["k"])
    check("the file is left as it was", (d / statestore.FILE).read_bytes(), before)
    check("and not copied aside", corrupt_copies(d), [])
    check("no WARNING / ERROR", LINES.lines, [])


def item1c():
    d = folder({"marks": {MARK: ["k"]}, "modes": {"skip_next_shutdown": True}})
    StateStore(d).get("marks", MARK)                # read once in this process
    bump(d)
    with read_fails() as lock:
        got = (StateStore(d).get("marks", MARK), StateStore(d).get("modes", "skip_next_shutdown"))
    check("a store built per call answers with what this process read last", got, (["k"], True))
    check("and does not sleep through the lock waits for it", lock.tries, 2)


def item1d():
    d = folder({"marks": {MARK: ["k"]}, "weekly": {"garden": {"done_week": "2026-W41"}}})
    store = StateStore(d)
    store.get("marks", MARK)
    bump(d)
    try:
        with read_fails(OSError(5, "Input/output error (test)")):
            store.set("versions", "okww", "v9")
        raised = ""
    except OSError as exc:
        raised = type(exc).__name__
    check("a write whose read meets another OSError raises", raised, "OSError")
    check("and leaves everything on file", on_disk(d),
          {"marks": {MARK: ["k"]}, "weekly": {"garden": {"done_week": "2026-W41"}}})
    check("not copied aside", corrupt_copies(d), [])


def item1e():
    d = folder()
    (d / statestore.FILE).write_text("[1, 2]", encoding="utf-8")
    try:
        got = StateStore(d).get("marks", MARK)
    except Exception as exc:  # noqa: BLE001
        got = f"{type(exc).__name__}: {exc}"
    check("state.json holding a list (not a table) reads as empty", got, None)
    check("and is copied aside before anything overwrites it", len(corrupt_copies(d)), 1)


def item1f():
    d = folder({"versions": {"code": "20261017"}, "marks": {MARK: ["k"]}})
    (d / "okww-version.txt").write_text("v3.6.5", encoding="utf-8")
    forget(d)
    statestore._SWEPT.discard(str(d))
    with read_fails():
        StateStore(d)
    check("legacy sweep with state.json locked leaves it as it was", on_disk(d),
          {"versions": {"code": "20261017"}, "marks": {MARK: ["k"]}})
    check("and moves no legacy file", (d / "okww-version.txt").exists(), True)
    StateStore(d)
    check("the lock gone, the next StateStore sweeps it in",
          (on_disk(d)["versions"].get("okww"), on_disk(d)["marks"].get(MARK)), ("v3.6.5", ["k"]))


def item2():
    d = folder({"marks": {}})
    one, two = Eng(d), Eng(d)
    one.state.store.get("marks", MARK)              # one's cached copy: no marks yet
    m0 = (d / statestore.FILE).stat().st_mtime
    two._mark_alerted(DAY, "b")
    # The second write lands within the clock's resolution: the mtime reads as it
    # did when `one` cached the file (put back by hand here).
    os.utime(d / statestore.FILE, (m0, m0))
    one._mark_alerted(DAY, "a")
    check("two writers marking the same day: both marks are on file",
          sorted(on_disk(d)["marks"].get(MARK) or []), ["a", "b"])
    check("and each reads both back", (one._already_alerted(DAY, "b"), two._already_alerted(DAY, "a")),
          (True, True))


for title, fn in (("1a: state.json locked after an alarm went out: not pushed again", item1a),
                  ("1b: the first read of state.json locked", item1b),
                  ("1c: a store built per call while state.json is locked", item1c),
                  ("1d: a write whose read meets an OSError other than a lock", item1d),
                  ("1e: state.json that is JSON but not a table", item1e),
                  ("1f: the legacy sweep while state.json is locked", item1f),
                  ("2: two writers marking one day's alarms", item2)):
    section(title, fn)

print()
if fails:
    print(f"✗ {len(fails)} 条没过：{fails}")
    sys.exit(1)
print("all checks passed")
