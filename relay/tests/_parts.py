"""Run the parts of a merged test file one after another, each as if it were its own file,
and the helpers every part shares (dispatches relay-slim-round1-1108 / round2-1108).

Each `_part_*` function of a merged file is a former test file's body. Until 2026-10-07
changed_covered.py ran several files in one process, and a fake one file left in place broke
the next (its executed_modules docstring), so every part here starts from the state a fresh
process would give it as far as the relay can see, and what it changed is put back before
the next one:

* first its loose ends: every logging handler it attached is closed (errwatch's push thread
  ends with its handler) and every thread it started gets a moment to finish - until
  round 2 a push thread still running when its modules were dropped died on
  「No module named 'ark_relay'」;
* sys.modules: every module the part imported is dropped, so the next part imports the
  relay afresh, with its own environment, and no patched module attribute survives;
* the attributes of every module that was already loaded (stdlib fakes: urlopen,
  subprocess.run, time.sleep), os.environ, sys.path, sys.argv and the working directory;
* every logger's handlers, level, propagate and disabled flags.

relay/tests/ is on sys.path before any part runs (for _tmp and this module); relay/ is not.

The shared helpers: `check(label, got, want)` and `require(name, ok, detail)`
(scripts/mac/lib/checkshape.py: one meaning each), `fails`, `tmpdir`. A part fails when it
records a failed check, or ends with sys.exit(code) non-zero, or raises.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

# relay/tests/ only. relay/ itself is not put here: each part adds it as its file did, and a
# part may test what happens before it is there (test_deploy's deploy_watch part reads a cap
# from a relay folder that does not exist and wants ModuleNotFoundError).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir  # after the path, as every test file imports it

__all__ = ["check", "fails", "require", "run_parts", "tmpdir"]

# The failed checks of the part running now; emptied before each part.
fails: list[str] = []
# How long a part's own threads get to finish once it is over (a push thread delivering to
# a fake notifier ends at once; one blocked on a real wait is left, daemon as it was).
SETTLE_S = 2.0


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)
    return ok


def require(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok or not detail else f": {detail}"))
    if not ok:
        fails.append(name)
    return bool(ok)


def _loggers() -> dict:
    out = {"": logging.getLogger()}
    for name, lg in logging.Logger.manager.loggerDict.items():
        if isinstance(lg, logging.Logger):
            out[name] = lg
    return out


def _snapshot() -> dict:
    mods = dict(sys.modules)
    return {
        "mods": mods,
        "dicts": {n: dict(m.__dict__) for n, m in mods.items() if m is not None and hasattr(m, "__dict__")},
        "env": dict(os.environ),
        "path": list(sys.path),
        "argv": list(sys.argv),
        "cwd": os.getcwd(),
        "loggers": {n: (list(lg.handlers), lg.level, lg.propagate, lg.disabled) for n, lg in _loggers().items()},
        "threads": set(threading.enumerate()),
    }


def _settle(s: dict) -> None:
    """Close what the part left running while its modules are still loaded."""
    before = {id(h) for handlers, *_ in s["loggers"].values() for h in handlers}
    for lg in _loggers().values():
        for h in list(lg.handlers):
            if id(h) not in before:
                try:
                    h.close()
                except Exception:  # noqa: BLE001 - a handler that cannot close is dropped all the same
                    pass
    ew = sys.modules.get("ark_relay.features.alarm.errwatch")
    h = (getattr(ew, "_handler", None) or [None])[0] if ew is not None else None
    if h is not None:
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    end = time.monotonic() + SETTLE_S
    for t in [t for t in threading.enumerate() if t not in s["threads"]]:
        t.join(max(0.0, end - time.monotonic()))


def _restore(s: dict) -> None:
    for name in [n for n in sys.modules if n not in s["mods"]]:
        del sys.modules[name]
    for name, m in s["mods"].items():
        sys.modules[name] = m
    for name, saved in s["dicts"].items():
        m = s["mods"][name]
        try:
            cur = m.__dict__
            for k in [k for k in cur if k not in saved]:
                del cur[k]
            for k, v in saved.items():
                if cur.get(k, cur) is not v:
                    cur[k] = v
        except (TypeError, AttributeError):
            continue        # a read-only module dict holds nothing a test can swap
    sys.path[:] = s["path"]
    sys.argv[:] = s["argv"]
    os.environ.clear()
    os.environ.update(s["env"])
    os.chdir(s["cwd"])
    for name, lg in _loggers().items():
        handlers, level, propagate, disabled = s["loggers"].get(name, ([], logging.NOTSET, True, False))
        lg.handlers[:] = handlers
        lg.setLevel(level)
        lg.propagate, lg.disabled = propagate, disabled
    logging.Logger.manager._clear_cache()


def run_parts(parts) -> int:
    """Run each part in turn; 0 when every part passed, else 1. Never stops at a failed part."""
    failed = []
    for part in parts:
        print(f"\n===== {part.__name__}", flush=True)
        fails.clear()
        snap = _snapshot()
        code = 0
        t0 = time.monotonic()
        try:
            part()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except BaseException:      # noqa: BLE001 - a crashing part is a failed part, the rest still run
            traceback.print_exc()
            code = 1
        finally:
            sys.stdout.flush()
            _settle(snap)
            _restore(snap)
        print(f"  ({part.__name__}: {time.monotonic() - t0:.1f} s)")
        if fails:
            print(f"  FAILED: {', '.join(fails)}")
            code = code or 1
        if code:
            failed.append(part.__name__)
    print("\n" + (f"FAILED parts: {', '.join(failed)}" if failed else f"all {len(parts)} parts passed"))
    return 1 if failed else 0
