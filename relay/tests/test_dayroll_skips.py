"""A machine left on past midnight puts back the queue-command skips of the day before.

Review fix 6 of the 2026-10-11 hand-over: the put-back of a phone queue command's
today-only skip (gameupdate.restore_skips(before_day=...)) ran only at boot, so on
a machine left running for days the queue item kept that weekday off. The main
loop's _DayRoll wakes just past local midnight and puts them back; the game
update's own hold is left to run_deferred.
"""
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir


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

import service  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402
from ark_relay.features.gameupdate import gameupdate  # noqa: E402
from ark_relay.features.phone import commands  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        fails.append(label)


class Log:
    def __init__(self): self.lines = []
    def info(self, msg, *a, **k): self.lines.append(msg % a)
    def warning(self, *a, **k): pass
    def exception(self, *a, **k): self.lines.append("exception")


D = datetime(2026, 10, 12, 23, 0, tzinfo=SERVER_TZ)
state = tmpdir()


def rec(script, item, **kw):
    return dict({"queue": "早班", "queueId": "q1", "queueItemId": item, "script": script, "scriptId": "s-" + item,
                 "position": 0, "day": "2026-10-12", "days": ["Monday"]}, **kw)


gameupdate._add_skip(state, rec("MaaEnd", "i2", source="queue"))       # a queue command's skip
gameupdate._add_skip(state, rec("OK-WW", "i3", why="维护"))           # the update's
gameupdate._add_skip(state, rec("MAA", "i1", why="维护"))
gameupdate._add_skip(state, rec("MAA", "i1", source="queue"))          # held by both

put = []
ok_restore = [False]


def restorer(r):
    put.append(r["script"])
    return ok_restore[0]


commands.restore_script_in_queue = restorer
cfg = types.SimpleNamespace(state_dir=state)
log = Log()
roll = service._DayRoll(cfg, log, now=D)

print("[the loop wakes just past midnight]")
check("23:59:30 with an hour to sleep: 31 s", roll.cap_wait(3600, D.replace(minute=59, second=30)), 31.0)
check("a nearer alarm stays", roll.cap_wait(10, D.replace(minute=59, second=30)), 10)

print("\n[before midnight nothing is put back]")
check("23:59:59", (roll.check(D.replace(minute=59, second=59)), put), ([], []))

print("\n[past midnight: AUTO-MAS not answering, kept and tried again]")
n1 = D + timedelta(hours=1, seconds=1)
check("first try fails", (roll.check(n1), put, roll.pending), ([], ["MaaEnd"], True))
ok_restore[0] = True
put.clear()
check("the next wake puts it back", (roll.check(n1 + timedelta(minutes=5)), put),
      (["MaaEnd→「早班」"], ["MaaEnd"]))
check("…and logs it", any("过了零点" in line for line in log.lines), True)
left = sorted((r["script"], tuple(sorted(gameupdate._sources(r)))) for r in gameupdate.skips(state))
check("the update's holds stay (MAA keeps the update's, loses the queue's)", left,
      [("MAA", ("update",)), ("OK-WW", ("update",))])
put.clear()
check("nothing more the same day", (roll.check(n1 + timedelta(hours=3)), put, roll.pending), ([], [], False))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
