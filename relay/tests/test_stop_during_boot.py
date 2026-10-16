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


print("[stop during the boot pre-update (10-16 02:35): no OK-WW launch, no mark_run, no alarm]")
# 2026-10-16 02:35: a deploy rollback stopped the relay mid pre-update. A stop that only
# ended the AUTO-MAS wait would go straight on to launch OK-WW (boot_stages forbids a
# stopping process to start programs), and a pre-update cut short must be neither marked
# done nor reported as 「没能确认」: the next boot runs it again.
from ark_relay.features.okww_patch import okww_overlay  # noqa: E402
from ark_relay.features.phone import commands  # noqa: E402
from ark_relay.features.preupdate import preupdate  # noqa: E402


class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **k):
        self.sent.append((title, k.get("alert", False)))
        return []


def preupdate_stage(stop_in: str, notes_first: bool = False):
    """Run _stage_preupdate with every program step faked; `stop_in` names the step during
    which SvcStop arrives ("automas", "okww" or "" for none). Returns what ran."""
    ran: list[str] = []
    cfg = types.SimpleNamespace(automas_dir=Path("automas"), okww_dir=Path("okww"),
                                state_dir=Path("state-never-written"))
    notifier = _Notifier()

    def automas(*_a, problems=None, **_k):
        ran.append("automas")
        if notes_first:
            problems.append("AUTO-MAS 预更新：等了 180 秒仍问不到更新状态，**没有检查更新**")
        if stop_in == "automas":
            errwatch.mark_stopping()
        return ""

    def okww(*_a, problems=None, **_k):
        ran.append("okww")
        if stop_in == "okww":
            errwatch.mark_stopping()
        return ""
    saved = (preupdate.wanted_today, preupdate.should_run, preupdate.mark_run, preupdate.run_automas,
             preupdate.run_okww, commands.mas_up, okww_overlay.retry_pending, okww_overlay.drift_line,
             boot_stages._seconds_to_next_queue)
    preupdate.wanted_today = lambda *a, **k: True
    preupdate.should_run = lambda *a, **k: True
    preupdate.mark_run = lambda *a, **k: ran.append("mark_run")
    preupdate.run_automas = automas
    preupdate.run_okww = okww
    commands.mas_up = lambda *a, **k: True
    okww_overlay.retry_pending = lambda *a, **k: ran.append("retry_pending")
    okww_overlay.drift_line = lambda *a, **k: ran.append("drift_line") and ""
    boot_stages._seconds_to_next_queue = lambda *a, **k: 10 * 3600.0   # room for a second try
    # win32api is stubbed above, so GetSystemMetrics would read as "Windows is going down".
    real_shutting, errwatch.system_shutting_down = errwatch.system_shutting_down, lambda: False
    try:
        boot_stages._stage_preupdate(cfg, notifier, logging.getLogger("ark.test_stop_during_boot"))
    finally:
        (preupdate.wanted_today, preupdate.should_run, preupdate.mark_run, preupdate.run_automas,
         preupdate.run_okww, commands.mas_up, okww_overlay.retry_pending, okww_overlay.drift_line,
         boot_stages._seconds_to_next_queue) = saved
        errwatch._stopping.clear()
        errwatch.system_shutting_down = real_shutting
    return ran, [t for t, alert in notifier.sent if alert]


ran, alarms = preupdate_stage("")
check("no stop: both items, overrides, mark_run", ran, ["automas", "okww", "retry_pending", "drift_line", "mark_run"])
ran, alarms = preupdate_stage("automas")
check("(d) stop during the AUTO-MAS item: OK-WW never launched, no mark_run", ran, ["automas"])
check("(d) no alarm", alarms, [])
ran, alarms = preupdate_stage("okww")
check("(e) stop during the OK-WW item: no override writes, no mark_run", ran, ["automas", "okww"])
check("(e) no alarm", alarms, [])
ran, alarms = preupdate_stage("automas", notes_first=True)
check("a stopping relay gives an item no second try, and says nothing", (ran, alarms), (["automas"], []))


print("[a stop during the second try is not a verdict: no recovered (self-fixed) line]")


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.got = []

    def emit(self, record):
        self.got.append((record.levelname, bool(getattr(record, errwatch.RECOVERED, False))))


def once_more_stopped_on_retry():
    """Try 1 leaves a note; SvcStop arrives during try 2, which returns no note."""
    tries = []

    def step(problems):
        tries.append(1)
        if len(tries) == 1:
            problems.append("OK-WW 预更新：拿不到控制台会话，**没有检查更新**")
        else:
            errwatch.mark_stopping()
        return ""

    log = logging.getLogger("ark.test_stop_during_boot")
    rec = _Records()
    log.addHandler(rec)
    saved = boot_stages._seconds_to_next_queue, errwatch.system_shutting_down
    boot_stages._seconds_to_next_queue = lambda *a, **k: 10 * 3600.0   # room for a second try
    errwatch.system_shutting_down = lambda: False
    problems: list[str] = []
    try:
        boot_stages._once_more(types.SimpleNamespace(automas_dir=Path("automas")), log, "OK-WW",
                               240.0, problems, step)
    finally:
        boot_stages._seconds_to_next_queue, errwatch.system_shutting_down = saved
        errwatch._stopping.clear()
        log.removeHandler(rec)
    return len(tries), [r for r in rec.got if r[0] == "WARNING" or r[1]]


tries, warned = once_more_stopped_on_retry()
check("the retry ran (the stop came during it)", tries, 2)
check("no WARNING and no recovered-tagged line", warned, [])


print("[every boot puts back a switch a killed pre-update left off]")
from ark_relay.features.preupdate import preupdate_okww  # noqa: E402
asked = []
saved = (preupdate_okww.restore_autostart_leftover, okww_overlay.install, okww_overlay.write_master_pointer,
         okww_overlay.report_line, okww_overlay.drift_line)
preupdate_okww.restore_autostart_leftover = lambda okww, state: asked.append((okww, state)) or ""
okww_overlay.install = okww_overlay.write_master_pointer = lambda *a, **k: ""
okww_overlay.report_line = okww_overlay.drift_line = lambda *a, **k: ""
try:
    boot_stages._stage_patch_okww(types.SimpleNamespace(automas_dir=None, okww_dir=Path("okww"), state_dir=Path("st")),
                                  _Notifier(), logging.getLogger("ark.test_stop_during_boot"))
finally:
    (preupdate_okww.restore_autostart_leftover, okww_overlay.install, okww_overlay.write_master_pointer,
     okww_overlay.report_line, okww_overlay.drift_line) = saved
check("_stage_patch_okww restores from the record", asked, [(Path("okww"), Path("st"))])

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
