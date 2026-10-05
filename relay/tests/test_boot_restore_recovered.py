"""boot_stages._stage_reenable_maaend: a narrowed MaaEnd master left over from the
last session and put back at boot is a fault the relay got over by itself.

The user on 2026-10-06 05:07, about faults the relay recovered from by itself: 「报错后自己好了的，只进日报、不进群」.
Until then 「开机：…（上次关机前没改回）」 was a plain WARNING, so a master the
relay had just put right before anything ran still rang the group. Now:
* put back (the gathering routes, or the make-up's narrowing) -> one WARNING
  marked errwatch.recovered(): not pushed, in the daily report tagged with
  the words 「自己好了，只进日报」 there;
* could not be put back -> the WARNING stays plain, pushed.
Every other step of the stage is faked; a real errwatch handler on the
stage's logger shows what is pushed and what the daily report lists.
"""
import logging
import sys
import tempfile
import time
import types
from datetime import datetime
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
from ark_relay import collect_retry, errwatch, gameupdate, makeup, mastercfg  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


class Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [(r.getMessage(), bool(getattr(r, errwatch.RECOVERED, False)))
                for r in self.records if r.levelno == logging.WARNING]


class Pushes:
    def __init__(self):
        self.sent = []

    def send(self, title, body, **k):
        self.sent.append((title, body))
        return []


def run(restore_master, try_restore):
    """One pass of the stage with the two restores faked; (records, pushes, state dir)."""
    state = Path(tempfile.mkdtemp(prefix="boot-restore-"))
    rec, pushes = Records(), Pushes()
    lg = logging.getLogger(f"ark.test_boot_restore.{id(rec)}")
    lg.propagate = False
    lg.setLevel(logging.DEBUG)
    lg.addHandler(rec)
    h = errwatch.ErrorKindAlert(pushes, state_dir=state, known={}, pace=0, retry=(0.05,))
    lg.addHandler(h)
    collect_retry.restore_master = restore_master
    makeup.maaend_still_running = lambda state_dir: False
    makeup.try_restore = try_restore
    cfg = types.SimpleNamespace(state_dir=state, automas_dir=state, maaend_dir=state)
    boot_stages._stage_reenable_maaend(cfg, types.SimpleNamespace(send=lambda *a, **k: []), lg)
    end = time.time() + 3
    while time.time() < end and h.pending():
        time.sleep(0.02)
    time.sleep(0.1)
    h.close()
    return rec, pushes, state


saved = (gameupdate.maaend_reenable_records, gameupdate.spmed_check, mastercfg.prune_maaend_orphans,
         mastercfg.migrate_maaend_options, collect_retry.restore_master, makeup.maaend_still_running,
         makeup.try_restore)
gameupdate.maaend_reenable_records = lambda cfg: None
gameupdate.spmed_check = lambda cfg: None
mastercfg.prune_maaend_orphans = lambda a, m: ([], "")
mastercfg.migrate_maaend_options = lambda a, m: (False, "")
ROUTES = "母本里的采集路线已改回原来的 12 条（2026-10-05/endfield/MaaEnd-21-40-00 那趟之后临时改过）"
MAKEUP = "终末地母本已改回补跑前的样子"
try:
    print("[both narrowings left over and put back at boot: daily report only]")
    rec, pushes, state = run(lambda cfg: ROUTES, lambda cfg, notifier=None: (MAKEUP, ""))
    warns = rec.warnings()
    check("two WARNINGs, both marked recovered", [r for _, r in warns], [True, True])
    check("they say what was put back and that it was left over",
          all("上次关机前没改回" in m and "这次开机改回了" in m for m, _ in warns) and len(warns) == 2)
    check("nothing reached the group", pushes.sent, [])
    section = errwatch.daily_section(state, datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d"))
    check("the daily report lists them, tagged 「自己好了，只进日报」",
          "采集路线已改回" in section and section.count("自己好了，只进日报") == 2)

    print("\n[the make-up's narrowing could not be put back: pushed]")
    rec, pushes, state = run(lambda cfg: "", lambda cfg, notifier=None: ("", "找不到终末地的母本"))
    check("one WARNING, not marked recovered", [r for _, r in rec.warnings()], [False])
    check("it reached the group", len(pushes.sent), 1)

    print("\n[nothing left over: nothing said]")
    rec, pushes, state = run(lambda cfg: "", lambda cfg, notifier=None: ("", ""))
    check("no WARNING", rec.warnings(), [])
finally:
    (gameupdate.maaend_reenable_records, gameupdate.spmed_check, mastercfg.prune_maaend_orphans,
     mastercfg.migrate_maaend_options, collect_retry.restore_master, makeup.maaend_still_running,
     makeup.try_restore) = saved

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
