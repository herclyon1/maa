"""Two threads writing state.json must not lose each other's key.

Audit s9 A2 (2026-10-13): the phone listen thread writes queues.phone_seen and,
through live commands, modes.* (set_debug, set_skip_shutdown ...), while the
engine thread writes the same file. StateStore.set/pop did load-modify-write with
no lock, and config.atomic_write_bytes always used the same temp name
(state.json.tmp). Run with two threads: 200/200 trials lost one update, 199 raised
FileNotFoundError on the rename. A lost modes.skip_next_shutdown means the reply
says 「已记下」 and the machine powers off anyway.

Both halves are made deterministic here: the first writer is held between its read
and its write while the second writer runs.
"""
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import config, statestore  # noqa: E402
from ark_relay.core.statestore import StateStore  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


print("[a second writer runs while the first is between its read and its write]")
d = tmpdir()
StateStore(d).set("queues", "phone_seen", [])
real_write = statestore.atomic_write_text
errors: list = []
other: list = []


def slow_first_write(path, text, *a, **k):
    # Only the first write is slowed down: the engine-thread writer below.
    if not other:
        def phone_thread():
            try:
                StateStore(d).set("queues", "phone_seen", ["ntfy-1"])
            except Exception as exc:  # noqa: BLE001 - recorded for the check
                errors.append(exc)
        t = threading.Thread(target=phone_thread)
        other.append(t)
        t.start()
        time.sleep(0.3)          # the phone thread gets every chance to write now
    return real_write(path, text, *a, **k)


statestore.atomic_write_text = slow_first_write
try:
    StateStore(d).set("modes", "debug_until", "2026-10-13 21:10")
finally:
    statestore.atomic_write_text = real_write
other[0].join(5)
s = StateStore(d)
check("the engine thread's key is there", s.get("modes", "debug_until"), "2026-10-13 21:10")
check("the phone thread's key is there", s.get("queues", "phone_seen"), ["ntfy-1"])
check("no writer raised", errors, [])

print("\n[pop is under the same lock]")
other.clear()


def slow_first_write2(path, text, *a, **k):
    if not other:
        t = threading.Thread(target=lambda: StateStore(d).set("queues", "phone_seen", ["ntfy-2"]))
        other.append(t)
        t.start()
        time.sleep(0.3)
    return real_write(path, text, *a, **k)


statestore.atomic_write_text = slow_first_write2
try:
    StateStore(d).pop("modes", "debug_until")
finally:
    statestore.atomic_write_text = real_write
other[0].join(5)
s = StateStore(d)
check("the popped key is gone", s.get("modes", "debug_until"), None)
check("the other thread's write survived the pop", s.get("queues", "phone_seen"), ["ntfy-2"])

print("\n[two writes of the same file never share a temp file]")
d2 = tmpdir()
target = d2 / "state.json"
real_fsync = config.os.fsync
inner_err: list = []
nested = []


def fsync_then_second_write(fd):
    real_fsync(fd)
    if not nested:
        nested.append(1)
        # A second writer of the same path while the first one's temp file is open.
        try:
            config.atomic_write_bytes(target, b'{"b": 1}')
        except OSError as exc:
            inner_err.append(exc)


config.os.fsync = fsync_then_second_write
outer_err = None
try:
    config.atomic_write_bytes(target, b'{"a": 1}')
except OSError as exc:
    outer_err = exc
finally:
    config.os.fsync = real_fsync
check("the inner write did not fail", inner_err, [])
check("the outer write did not fail", repr(outer_err) if outer_err else None, None)
check("the last write wins, whole", target.read_bytes(), b'{"a": 1}')
check("no temp file left behind", sorted(p.name for p in d2.iterdir()), ["state.json"])

print("\n[a temp file a power cut left behind is removed at the next start once it is a day old]")
d3 = tmpdir()
(d3 / "state.json").write_text("{}", encoding="utf-8")
old_tmp = d3 / "state.json.abc123.tmp"
fresh_tmp = d3 / "state.json.def456.tmp"
legacy_tmp = d3 / "state.json.tmp"
other_tmp = d3 / "ledger-2026-10-13.jsonl.xyz.tmp"
for f in (old_tmp, fresh_tmp, legacy_tmp, other_tmp):
    f.write_text("{", encoding="utf-8")
two_days_ago = time.time() - 2 * 86400
for f in (old_tmp, legacy_tmp, other_tmp):
    os.utime(f, (two_days_ago, two_days_ago))
statestore._SWEPT.discard(str(d3))
statestore.StateStore(d3)
check("old state.json temp files are gone, a fresh one (a live write) and other files stay",
      sorted(p.name for p in d3.iterdir()),
      sorted(["state.json", fresh_tmp.name, other_tmp.name]))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
