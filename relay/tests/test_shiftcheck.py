"""After-shift check (selfcheck/shiftcheck.py): the four sign-off items the relay had no
check for, judged once after every finished morning / evening shift.

The four come from scripts/mac/lib/healthcheck.py sections 3 and 6 (the 游戏-中继二
scope cut of 10-10 23:3x, less MAA's IfActivityFirst and IfFight - his own phone
settings, dropped by 验收 on 10-11). Each item has a red and a green case; the run is tied to
the shutdown decision's own "this shift finished" test (shutdown._not_shift), so a
round started by hand or a shift whose records this boot never saw land is not
checked; the line reaches the daily report's relay section and is never pushed.
"""
import inspect
import json
import logging
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ
from ark_relay.core.statestore import StateStore
from ark_relay.features.selfcheck import selfcheck, shiftcheck
from ark_relay.features.shutdown import shutdown

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def by_name(checks, name):
    return next(c for c in checks if c.name == name)


print("[each item: green, red, unreadable]")
green = shiftcheck.judge("", False, False, "", [])
check("four items", len(green), 4)
check("all green", [c.ok for c in green], [True] * 4)
check("all green -> one line saying so", shiftcheck.summary("晚班", green), "收工体检（晚班）4 项都对")
check("his own MAA settings are not judged (活动关优先 / 作战开关)",
      [c.name for c in green if "活动关" in c.name or "作战" in c.name], [])

red = shiftcheck.judge(texts.annihilation_off_body("明日方舟 · 剿灭"), True, True, "2026-10-11 20:50",
                       [{"since": "2026-10-11 09:12:00", "until": "2026-10-11 09:40:00"},
                        {"since": "2026-10-11 10:00:00", "until": None}])
check("annihilation Close, week not done -> red with the boot alarm's words",
      (by_name(red, texts.SHIFTCHECK_ANNIHILATION).ok, by_name(red, texts.SHIFTCHECK_ANNIHILATION).detail),
      (False, texts.annihilation_off_body("明日方舟 · 剿灭")))
check("「下次跑完不关机」 armed -> red", by_name(red, texts.SHIFTCHECK_SKIP).ok, False)
check("debug mode on -> red, says until when",
      (by_name(red, texts.SHIFTCHECK_DEBUG).ok, "2026-10-11 20:50" in by_name(red, texts.SHIFTCHECK_DEBUG).detail),
      (False, True))
check("a test window still open -> red, names the open one (not the closed one)",
      (by_name(red, texts.SHIFTCHECK_TEST_WINDOW).ok, "10:00:00" in by_name(red, texts.SHIFTCHECK_TEST_WINDOW).detail),
      (False, True))
check("closed test windows only -> green",
      by_name(shiftcheck.judge("", False, False, "", [{"since": "a", "until": "b"}]),
              texts.SHIFTCHECK_TEST_WINDOW).ok, True)
line = shiftcheck.summary("早班", red)
check("red line counts four not held", line.startswith("收工体检（早班）4 项里 4 项不对、0 项判不了："), True)
check("red line is plain language", texts.plain(line), [])
check("red line is one line (the daily report reads relay.log line by line)", "\n" in line, False)

unread = shiftcheck.judge(None, False, False, "", [])
check("annihilation switch unreadable -> cannot be judged (None), not green",
      by_name(unread, texts.SHIFTCHECK_ANNIHILATION).ok, None)
check("unreadable line says 判不了", "1 项判不了" in shiftcheck.summary("晚班", unread), True)

print("\n[once per finished shift, on the tick, before the report and the shutdown]")
src = inspect.getsource(__import__("ark_relay.core.engine", fromlist=["Engine"]).Engine.tick)
check("tick runs 收工体检 before 日报 and 关机",
      0 < src.index('"收工体检"') < src.index('"日报"') < src.index('"关机"'), True)


class Gate:
    def __init__(self, line=""):
        self.line = line

    def switch_off_line(self, now=None):
        return self.line


class Rec(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


rec = Rec()
shiftcheck.log.addHandler(rec)
shiftcheck.log.setLevel(logging.DEBUG)

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    (td / "automas" / "config").mkdir(parents=True)

    due = datetime(2026, 10, 11, 21, 30, tzinfo=SERVER_TZ)
    booted = due - timedelta(minutes=15)
    now = due + timedelta(hours=1)
    store = StateStore(td)
    eng = SimpleNamespace(
        cfg=SimpleNamespace(state_dir=td, automas_dir=td / "automas"),
        state=SimpleNamespace(store=store, dir=td),
        _annihilation=Gate(""), _handled_any=True,
        _boot_time=lambda now: booted,
        _recent_entries=lambda now: [{"script": "MAA", "started": (due + timedelta(minutes=2)).isoformat()}],
        _last_round_manual=lambda now, entries: False,
    )
    real_queues = shutdown._shift_queues
    shutdown._shift_queues = lambda e, n, b: [{"name": "晚班", "due": due, "kinds": ["MAA"]}]
    try:
        got = shiftcheck.maybe_run(eng, now)
        check("finished shift -> checked", got is not None and [c.ok for c in got], [True] * 4)
        check("the line went to relay.log at INFO", [(r.levelno, r.getMessage()) for r in rec.records],
              [(logging.INFO, "收工体检（晚班）4 项都对")])
        check("second tick of the same shift -> not again", shiftcheck.maybe_run(eng, now + timedelta(minutes=1)), None)
        check("the shift is remembered across a restart (state.json marks)",
              StateStore(td).get("marks", shiftcheck.MARK), due.isoformat())

        # A new shift (next morning) is checked again; this one with every item red.
        due2 = datetime(2026, 10, 12, 5, 0, tzinfo=SERVER_TZ)
        shutdown._shift_queues = lambda e, n, b: [{"name": "早班", "due": due2, "kinds": ["MAA"]}]
        eng._boot_time = lambda now: due2 - timedelta(minutes=15)
        eng._recent_entries = lambda now: [{"script": "MAA", "started": (due2 + timedelta(minutes=1)).isoformat()}]
        eng._annihilation = Gate(texts.annihilation_off_body("明日方舟 · 剿灭"))
        store.set("modes", "skip_next_shutdown", True)
        store.set("modes", "debug_until", "2099-01-01 00:00")
        (td / "test-windows.json").write_text(json.dumps([{"since": "2026-10-12 04:50:00", "until": None}]),
                                              encoding="utf-8")
        rec.records.clear()
        got = shiftcheck.maybe_run(eng, due2 + timedelta(hours=2))
        check("next shift, every item red, read from the state files", got and [c.ok for c in got], [False] * 4)
        check("red still INFO only (WARNING would reach the group through errwatch)",
              [r.levelno for r in rec.records], [logging.INFO])
        check("red line names the morning shift", rec.records[0].getMessage().startswith("收工体检（早班）4 项里 4 项不对"),
              True)

        # Not finished / not a scheduled shift: nothing.
        due3 = due2 + timedelta(hours=16, minutes=30)
        shutdown._shift_queues = lambda e, n, b: [{"name": "晚班", "due": due3, "kinds": ["MAA", "OK-WW"]}]
        eng._boot_time = lambda now: due3 - timedelta(minutes=15)
        eng._recent_entries = lambda now: [{"script": "MAA", "started": (due3 + timedelta(minutes=1)).isoformat()}]
        check("a script of the shift not recorded yet -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)),
              None)
        eng._recent_entries = lambda now: [{"script": k, "started": (due3 + timedelta(minutes=1)).isoformat()}
                                           for k in ("MAA", "OK-WW")]
        eng._last_round_manual = lambda now, entries: True
        check("last round started by hand -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)
        eng._last_round_manual = lambda now, entries: False
        eng._handled_any = False
        check("records never seen landing on this boot (relay restarted after the shift) -> not checked",
              shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)
        eng._handled_any = True
        eng._boot_time = lambda now: None
        check("boot time unknown -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)
        eng._boot_time = lambda now: due3 - timedelta(minutes=15)
        shutdown._shift_queues = lambda e, n, b: []
        check("no scheduled shift on this boot -> not checked", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), None)

        # A queue with no name (plan gives "?"): labelled by its time.
        due4 = due3 + timedelta(hours=8)
        shutdown._shift_queues = lambda e, n, b: [{"name": "?", "due": due4, "kinds": ["MAA"]}]
        eng._boot_time = lambda now: due4 - timedelta(minutes=15)
        eng._recent_entries = lambda now: [{"script": "MAA", "started": (due4 + timedelta(minutes=1)).isoformat()}]
        rec.records.clear()
        shiftcheck.maybe_run(eng, due4 + timedelta(hours=1))
        check("unnamed 05:xx queue -> 早班", rec.records and rec.records[0].getMessage().startswith("收工体检（早班）"), True)
        eng._boot_time = lambda now: due3 - timedelta(minutes=15)
        eng._recent_entries = lambda now: [{"script": k, "started": (due3 + timedelta(minutes=1)).isoformat()}
                                           for k in ("MAA", "OK-WW")]

        # A crash inside the check: ERROR, said in the line, not run again on the next tick.
        shutdown._shift_queues = lambda e, n, b: [{"name": "晚班", "due": due3, "kinds": ["MAA", "OK-WW"]}]
        real_read = shiftcheck.read
        shiftcheck.read = lambda e, n: 1 / 0
        rec.records.clear()
        try:
            check("crash -> []", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1)), [])
        finally:
            shiftcheck.read = real_read
        check("crash is a relay fault: ERROR with its traceback (errwatch pushes it), saying the shift was not checked",
              [(r.levelno, r.getMessage(), bool(r.exc_info)) for r in rec.records],
              [(logging.ERROR, texts.shiftcheck_broken("晚班"), True)])
        check("crashed shift not retried on every tick", shiftcheck.maybe_run(eng, due3 + timedelta(hours=1, minutes=1)),
              None)
    finally:
        shutdown._shift_queues = real_queues

print("\n[the daily report's relay section quotes each shift's line]")
log = """10-11 21:20:00 INFO    ark.service  服务模式启动
10-11 21:21:00 INFO    ark.service  AUTO-MAS 自己起来了（等了 21 秒）
10-11 22:31:05 INFO    ark.shiftcheck  收工体检（晚班）4 项里 1 项不对、0 项判不了：调试模式：开着，到 2026-10-12 04:50，这期间跑完不关机
10-10 22:31:05 INFO    ark.shiftcheck  收工体检（晚班）4 项都对
10-11 06:40:00 INFO    ark.shiftcheck  收工体检（早班）4 项都对
"""
lines = selfcheck.daily_lines("2026-10-11", log)
check("both shifts of the day quoted after the two relay lines, not yesterday's",
      lines[2:], ["· 收工体检（晚班）4 项里 1 项不对、0 项判不了：调试模式：开着，到 2026-10-12 04:50，这期间跑完不关机",
                  "· 收工体检（早班）4 项都对"])
check("the shift line does not count as a boot", lines[1], "· 调度程序开机：21:21 自己起来了（等了 21 秒）")
check("no shift line -> still the two lines", len(selfcheck.daily_lines("2026-10-09", log)), 2)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
