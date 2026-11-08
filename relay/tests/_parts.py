"""Run the parts of a merged test file one after another, each as if it were its own file.

Each `_part_*` function of a merged file is a former test file's whole body (dispatch
relay-slim-round1-1108). Until 2026-10-07 changed_covered.py ran several files in one
process, and a fake one file left in place broke the next (its executed_modules docstring),
so every part here starts from the same state as a fresh process would give it as far as
the relay can see, and what it changed is put back before the next one:

* sys.modules: every module the part imported is dropped, so the next part imports the
  relay afresh, with its own environment, and no patched module attribute survives;
* the attributes of every module that was already loaded (stdlib fakes: urlopen,
  subprocess.run, time.sleep), os.environ, sys.path, sys.argv and the working directory;
* every logger's handlers, level, propagate and disabled flags (a part that set
  propagate=False on "ark.preupdate" would otherwise silence the next part's capture).

A part ends by returning, or by sys.exit(code) as the file used to: 0 / None is a pass.
"""
from __future__ import annotations

import logging
import os
import sys
import traceback


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
    }


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
        snap = _snapshot()
        code = 0
        try:
            part()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except BaseException:      # noqa: BLE001 - a crashing part is a failed part, the rest still run
            traceback.print_exc()
            code = 1
        finally:
            sys.stdout.flush()
            _restore(snap)
        if code:
            failed.append(part.__name__)
    print("\n" + (f"FAILED parts: {', '.join(failed)}" if failed else f"all {len(parts)} parts passed"))
    return 1 if failed else 0
