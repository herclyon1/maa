"""A stop that arrives while the relay is still booting ends it at once.

Cloud package smoke, 2026-10-10 22:30:11 and 22:37:42: `launch.py stop` came one
second after start, SvcStop's 15-second hard exit fired, and its thread dump showed
MainThread in http.client (boot pushes retrying against a refused port) with the
errwatch push thread asleep in a 30 s retry backoff. Two fixes, one check each:
1. service.main checks for a stop between boot steps and returns;
2. the errwatch push thread's backoff wakes on close() instead of sleeping it out.
Since audit s23 F3 (10-13) the alarm-copy flushes and the OK-WW overrides run after
the self-update, so a self-update boot runs them once, in the process that stays.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for name in ("win32serviceutil", "win32service", "win32event", "win32api",
             "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(name, _Stub(name))

import boot_stages  # noqa: E402
import service  # noqa: E402
from _tmp import tmpdir  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


STAGES = ("selfupdate", "flush_copies", "patch_okww", "backfill_manual_stops", "announce_update",
          "evidence_sources", "inbox_and_phone", "stagegate", "selfcheck", "preupdate",
          "reenable_maaend", "collect_watch", "gameupdate", "annihilation", "machinecheck")


def boot(stop_during: str | None, updated: bool = False) -> list[str]:
    """Run service.main with every boot step recorded; `stop_during` asks for a
    stop while that step runs (as SvcStop does from another thread); `updated`
    makes the self-update find new code (the outgoing process returns)."""
    ran: list[str] = []
    svc = service.ArkRelayService.__new__(service.ArkRelayService)
    svc._stop_asked = threading.Event()

    def step(name):
        def run(*_a, **_k):
            ran.append(name)
            if name == stop_during:
                svc._stop_asked.set()
            if name == "selfupdate":
                return updated
            if name == "inbox_and_phone":
                return None, None, None
            return None
        return run

    saved = {}
    for name in STAGES:
        saved[name] = getattr(boot_stages, f"_stage_{name}", None)
        setattr(boot_stages, f"_stage_{name}", step(name))
    real_bootstrap, real_net, real_loop = boot_stages._stage_bootstrap, service._wait_for_network, service._loop
    boot_stages._stage_bootstrap = lambda: (logging.getLogger("ark.test"), None, None, None)
    service._wait_for_network = lambda log: None
    service._loop = lambda *a, **k: ran.append("loop")
    try:
        svc.main()
    finally:
        for name, fn in saved.items():
            if fn is None:
                delattr(boot_stages, f"_stage_{name}")
            else:
                setattr(boot_stages, f"_stage_{name}", fn)
        boot_stages._stage_bootstrap, service._wait_for_network, service._loop = \
            real_bootstrap, real_net, real_loop
    return ran


print("[no stop: every boot step, then the main loop]")
check("steps", boot(None), list(STAGES) + ["loop"])

print("[stop during the update announcement (the smoke's case): nothing after it]")
check("steps", boot("announce_update"), list(STAGES[:STAGES.index("announce_update") + 1]))

print("[stop during patch_okww: nothing after it]")
check("steps", boot("patch_okww"), list(STAGES[:STAGES.index("patch_okww") + 1]))

print("[stop during the self-update: not even the OK-WW overrides]")
check("steps", boot("selfupdate"), ["selfupdate"])

print("[self-update found new code: the outgoing process flushes and patches nothing]")
# relay.log 10-05 21:20:19 / 21:20:27: the same 🩹 note from the outgoing and the
# new process, 8 s apart (audit s23 F3).
check("steps", boot(None, updated=True), ["selfupdate"])

print("[stop during the inbox step: no stage gate, no pre-update, no loop]")
check("steps", boot("inbox_and_phone"), list(STAGES[:STAGES.index("inbox_and_phone") + 1]))


print("[errwatch: close() ends the push thread inside a retry backoff]")


class Refused:
    def __init__(self):
        self.tries = threading.Event()

    def send(self, title, body, **k):
        self.tries.set()
        return ["企业微信机器人: refused"]


notifier = Refused()
h = errwatch.ErrorKindAlert(notifier, state_dir=tmpdir(), known={}, retry=(30.0,))
lg = logging.getLogger("ark.test.stopwake")
lg.propagate = False
lg.addHandler(h)
lg.warning("something went wrong")
check("first push tried", notifier.tries.wait(5), True)
sender = h._sender
time.sleep(0.2)                     # into the 30 s backoff
t0 = time.monotonic()
h.close()
sender.join(5)
check("push thread gone after close()", sender.is_alive(), False)
check("close() woke it in under 2 s", time.monotonic() - t0 < 2, True)
check("record still queued for the next start", len(h.pending()), 1)
lg.removeHandler(h)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
