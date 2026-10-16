"""display_wake: the display is woken while AUTO-MAS starts Endfield through its launcher.

2026-10-16 13:21 (a hand-started make-up), attempt 1: the game PC's display had been
off (power plan, 300 s idle), the Hypergryph launcher kept its main window hidden
(games.log 13:21:31.615 bMainWndHide:true / 13:21:31.616 「display off」), AUTO-MAS
only wakes a running screensaver, and at 13:23:36 it gave up: 「游戏启动失败: 等待终末地
游戏窗口超时」. Nothing in the relay woke the display.

Fixture: the real app.log lines of that day (HTTP request lines left out):
09:33:54-09:34:05 (OK-WW finishing, then MaaEnd refused at its config check: no
launch), 13:21:13-13:26:14 (attempt 1 hand-off 13:21:28.423, timeout 13:23:36.444,
attempt 2 hand-off 13:23:36.799, game up 13:26:14.036) and 13:53:00-13:54:52 (attempt 3).
"""
import json
import logging
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay.core import config, desktop, watch
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.run import display_wake as dw

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


FIX = Path(__file__).resolve().parent / "fixtures" / "display-wake-2026-10-16" / "app.log"
LINES = FIX.read_text(encoding="utf-8").splitlines()


def at(hms: str) -> datetime:
    return datetime.fromisoformat(f"2026-10-16 {hms}").replace(tzinfo=SERVER_TZ)


def stamp(line: str) -> datetime:
    return datetime.fromisoformat(line[:23]).replace(tzinfo=SERVER_TZ)


class _ClockTail:
    """app.log as the thread sees it at `now`: every line written by then, once."""

    def __init__(self, lines):
        self.lines, self.i, self.now = lines, 0, None

    def read(self):
        out = []
        while self.i < len(self.lines) and stamp(self.lines[self.i]) <= self.now:
            out.append(self.lines[self.i])
            self.i += 1
        return out


def replay(lines, start: str, end: str, every: float = dw.POLL_SECONDS):
    """Run the thread's step on a fake clock that looks every `every` seconds (the
    backstop alone, no change notification). Returns the moments a wake was issued."""
    waker, tail, wakes = dw.Waker(), _ClockTail(lines), []
    now, stop = at(start), at(end)
    while now <= stop:
        tail.now = now
        dw.step(waker, tail, lambda: wakes.append(tail.now) or True, now)
        now += timedelta(seconds=every)
    return wakes


print("[attempt 1, 13:21: the display is woken right after AUTO-MAS hands off to the launcher]")
HANDOFF1, TIMEOUT1 = at("13:21:28.423"), at("13:23:36.444")
wakes = replay(LINES, "13:21:00", "13:27:00")
first = wakes[0] if wakes else None
check("a wake is issued for attempt 1", first is not None)
if first:
    check(f"first wake {first:%H:%M:%S} within one backstop look of the hand-off line",
          HANDOFF1 <= first <= HANDOFF1 + timedelta(seconds=dw.POLL_SECONDS))
    check("well inside AUTO-MAS's 120 s launcher wait", first < HANDOFF1 + timedelta(seconds=120))
att1 = [w for w in wakes if w < TIMEOUT1]
check("re-woken at most every REWAKE_SECONDS during attempt 1",
      all((b - a).total_seconds() >= dw.REWAKE_SECONDS for a, b in zip(att1, att1[1:], strict=False)))
HANDOFF2, UP2 = at("13:23:36.799"), at("13:26:14.036")
att2 = [w for w in wakes if w >= TIMEOUT1]
check("attempt 2 (retry) re-arms and wakes at once",
      bool(att2) and att2[0] <= HANDOFF2 + timedelta(seconds=dw.POLL_SECONDS))
check("no wake after AUTO-MAS logs 运行脚本任务 (game up, 13:26:14)", [w for w in wakes if w > UP2], [])
print(f"    wakes: {', '.join(f'{w:%H:%M:%S}' for w in wakes)}")

print("\n[a change notification: the wake follows the hand-off line within a second or two]")
wakes = replay(LINES, "13:21:27", "13:21:40", every=1.0)
check("woken by 13:21:30", bool(wakes) and wakes[0] <= at("13:21:30"))

print("\n[attempt 3, 13:53: woken, then left alone once the game is up]")
wakes = replay(LINES, "13:52:50", "14:05:00")
check("one wake right after 13:53:33.918",
      bool(wakes) and at("13:53:33.918") <= wakes[0] <= at("13:53:44"))
check("none after 13:54:52 (运行脚本任务)", [w for w in wakes if w > at("13:54:52.502")], [])

print("\n[no MaaEnd launch, no wake: OK-WW finishing and MaaEnd refused at its config check, 09:33-09:34]")
check("no wake 09:33:50-09:40:00", replay(LINES, "09:33:50", "09:40:00"), [])

print("\n[bounded: a hand-off with no end line wakes for WINDOW_SECONDS at most]")
only = [ln for ln in LINES if ln.startswith("2026-10-16 13:21:28.423")]
wakes = replay(only, "13:21:00", "13:45:00")
check("hand-off line alone gives wakes", bool(wakes))
check(f"at most {dw.WINDOW_SECONDS // dw.REWAKE_SECONDS} wakes ({len(wakes)})",
      len(wakes) <= dw.WINDOW_SECONDS // dw.REWAKE_SECONDS)
check("none later than WINDOW_SECONDS after the hand-off",
      all(w < HANDOFF1 + timedelta(seconds=dw.WINDOW_SECONDS) for w in wakes))

print("\n[an old hand-off line read again (app.log re-read from its start) wakes nothing]")
waker = dw.Waker()
waker.feed(only)
check("not due 10 minutes later", waker.due(at("13:31:30")), False)

print("\n[a failed wake is retried after REWAKE_SECONDS]")
waker, tail, calls = dw.Waker(), _ClockTail(only), []
for hms in ("13:21:29", "13:21:59", "13:22:29", "13:22:30"):
    tail.now = at(hms)
    dw.step(waker, tail, lambda: calls.append(tail.now) or False, at(hms))
check("tried at 13:21:29 and again at 13:22:29", calls, [at("13:21:29"), at("13:22:29")])


class _Levels(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.levels = []

    def emit(self, record):
        self.levels.append(record.levelno)


lv = _Levels()
dw.log.addHandler(lv)
_old_level = dw.log.level
dw.log.setLevel(logging.DEBUG)
waker, tail = dw.Waker(), _ClockTail(only)


def _boom():
    raise OSError("no agent")


for hms in ("13:21:29", "13:22:29", "13:23:29"):
    tail.now = at(hms)
    dw.step(waker, tail, _boom, at(hms))
dw.log.removeHandler(lv)
dw.log.setLevel(_old_level)
check("a failing wake goes to the group (WARNING) once per attempt, then only to the log",
      lv.levels, [logging.WARNING, logging.INFO, logging.INFO])

print("\n[Tail: starts at the end of app.log, follows AUTO-MAS's rotation]")
d = tmpdir()
f = d / "app.log"
f.write_text("\n".join(LINES[:40]) + "\n", encoding="utf-8")
t = dw.Tail(f)
check("lines from before the start are not read", t.read(), [])
with f.open("a", encoding="utf-8") as fh:
    fh.write(LINES[57] + "\n" + LINES[58][:30])
check("an appended line is read, a half line is held", t.read(), [LINES[57]])
f.write_text(LINES[58] + "\n", encoding="utf-8")
check("after rotation the new file is read from its start", t.read(), [LINES[58]])

print("\n[Desktop.wake: one windowless agent run with the wake act; the agent wakes the display]")
calls = []


def _spawn(tag):
    def spawn(exe, cwd, args):
        req, res = Path(args[-2]), Path(args[-1])
        calls.append((tag, json.loads(req.read_text(encoding="utf-8"))["actions"]))
        res.write_text(json.dumps({"ok": True, "log": ["wake"], "ocr": [], "clicked": []}), encoding="utf-8")
        return True
    return spawn


dk = desktop.Desktop(tmpdir() / "state", spawn=_spawn("window"), spawn_hidden=_spawn("hidden"), timeout=5)
check("wake() reports success", dk.wake(), True)
check("windowless route, the single wake act", calls, [("hidden", [{"act": "wake"}])])
check("the agent's wake act calls WakeDisplay", "'wake' { WakeDisplay;" in desktop.AGENT_PS)

print("\n[start(): the thread reads a live app.log and wakes (Windows switched on, the agent faked)]")
woken = threading.Event()
real_windows, real_wake, real_poll = config.IS_WINDOWS, desktop.Desktop.wake, dw.POLL_SECONDS
real_watch = watch.start
try:
    config.IS_WINDOWS = True
    watch.start = lambda path, ev: False      # no change notification: the backstop alone
    desktop.Desktop.wake = lambda self: woken.set() or True
    dw.POLL_SECONDS = 0.3
    root = tmpdir()
    (root / "debug").mkdir()
    applog = root / "debug" / "app.log"
    applog.write_text(LINES[0] + "\n", encoding="utf-8")

    class _Cfg:
        automas_dir = str(root)
        state_dir = str(tmpdir())

    check("start() arms the thread", dw.start(_Cfg), True)
    now = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
    with applog.open("a", encoding="utf-8") as fh:
        fh.write(f"{now}.423 | INFO     | MaaEnd 自动代理 | 启动方式为「启动器启动」，将由 MAS 经终末地官方启动器拉起游戏\n")
    check("woken within 3 s of the hand-off line landing", woken.wait(3.0))
finally:
    config.IS_WINDOWS, desktop.Desktop.wake, watch.start = real_windows, real_wake, real_watch
    time.sleep(dw.POLL_SECONDS)
    dw.POLL_SECONDS = real_poll


class _NoDir:
    automas_dir = None
    state_dir = str(tmpdir())


config.IS_WINDOWS = True
check("no AUTO-MAS folder: start() returns False", dw.start(_NoDir), False)
config.IS_WINDOWS = real_windows

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
