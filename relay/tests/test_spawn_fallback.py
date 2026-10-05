"""require_console must hold on every way out of _spawn_interactive.

Audit 2026-10-05 (C, preupdate_common.py:327-328): when pywin32 failed to
import, _spawn_interactive went straight to _spawn_detached - a plain launch
into session 0 - even with require_console=True. That is the exact path the
flag was added to refuse after 2026-08-25, when OK-WW launched into session 0
never ran its updater and the unchanged version file was reported as
「无需更新」. The callers (preupdate_maa, preupdate_okww, gameupdate_games)
already record a problem on False; they only have to be given the False.

Also covers _spawn_fallback itself, which had no test: scheduled task first,
then require_console decides.
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate_common as C

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


# Never touched: _spawn_via_task and _spawn_detached are stubbed below.
EXE = Path(__file__).parent / "MAA.exe"
CWD = Path(__file__).parent
NO_PYWIN32 = {m: None for m in ("win32con", "win32process", "win32profile", "win32ts")}


def run(fn, *, task_ok, **kw):
    detached = []
    with mock.patch.object(C, "_spawn_via_task", lambda *a, **k: task_ok), \
         mock.patch.object(C, "_spawn_detached", lambda *a, **k: detached.append(a) or True):
        got = fn(EXE, CWD, **kw)
    return got, len(detached)


print("[_spawn_fallback]")
check("task works -> True, no plain launch",
      run(lambda e, c, **k: C._spawn_fallback(e, c, (), **k), task_ok=True, require_console=True),
      (True, 0))
check("task fails + require_console -> False, no plain launch",
      run(lambda e, c, **k: C._spawn_fallback(e, c, (), **k), task_ok=False, require_console=True),
      (False, 0))
check("task fails, console not required -> plain launch",
      run(lambda e, c, **k: C._spawn_fallback(e, c, (), **k), task_ok=False, require_console=False),
      (True, 1))

print("[_spawn_interactive without pywin32]")
with mock.patch.dict(sys.modules, NO_PYWIN32):
    check("require_console, task fails -> False (was: session-0 launch, True)",
          run(C._spawn_interactive, task_ok=False, require_console=True), (False, 0))
    check("require_console, task works -> True via the task",
          run(C._spawn_interactive, task_ok=True, require_console=True), (True, 0))
    check("console not required, task fails -> plain launch still allowed",
          run(C._spawn_interactive, task_ok=False, require_console=False), (True, 1))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
