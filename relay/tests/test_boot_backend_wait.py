"""Boot steps that need the AUTO-MAS backend wait for it right before they run.

Real sequence, 2026-10-17 21:20 (relay-2026-10-17.log on the evidence bucket):
21:20:55 ensure_automas logged that AUTO-MAS came up by itself after 24 s; 21:21:25
efstart_setup found the API refusing the connection (a WARNING, ledger #104); 21:21:30
the boot self-check failed its "scheduler answers" and "backend process running" lines
(the self-check alarm, ledger #105). The backend's processes then on the machine had
started 21:21:34 and it answered again by 21:23: AUTO-MAS restarted its own backend
mid-boot, and the steps judged it in the gap.

Here the backend is down for the first polls (a fake clock, no real sleep): the boot
steps must wait and pass with no alarm; still down past the limit, the same failure
lines as before must come, saying how long they waited. Fails on the code before
boot_stages.await_backend (the steps asked once, at once).
"""
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import boot_stages  # noqa: E402
from ark_relay.core import texts  # noqa: E402
from ark_relay.features.gameupdate import efstart_setup  # noqa: E402
from ark_relay.features.phone import commands  # noqa: E402
from ark_relay.features.selfcheck import selfcheck  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class _Rec(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [r.getMessage() for r in self.records if r.levelno >= logging.WARNING]


class _Notifier:
    channels = ["企业微信机器人"]

    def __init__(self):
        self.sent = []

    def send(self, title, body, *, alert=False, daily=False):
        self.sent.append((title, body, alert))
        return []


# The fake machine: the clock only moves when the relay sleeps; the backend answers
# from `back_at` on (None: never).
now = [0.0]
back_at = [None]
polls = [0]


def _up() -> bool:
    polls[0] += 1
    return back_at[0] is not None and now[0] >= back_at[0]


# The relay's own waits read the time module (as tests/test_automas_boot_one_alarm.py
# fakes it); nothing else in this test sleeps.
boot_stages.time.monotonic = lambda: now[0]
boot_stages.time.sleep = lambda s: now.__setitem__(0, now[0] + s)
boot_stages._stop_requested = lambda: False
commands.mas_up = _up


def _mas(path, body=None, timeout=20):
    if not _up():
        raise ConnectionRefusedError(10061, "refused")
    return {"code": 200, "data": {}}


commands._mas = _mas


def _install(cfg):
    """efstart_setup.install's answer when the API refuses (its own text) or answers."""
    if not _up():
        return False, ["调度程序没应答，终末地的开游戏设置没核对：连不上"]
    return True, []


efstart_setup.install = _install
efstart_setup.check_d3d11 = lambda: None

BACKEND = (4242, r"D:\ark\automas\AUTO-MAS\backend\.venv\Scripts\python.exe D:\ark\automas\AUTO-MAS\main.py")
_real_run = selfcheck.run


def _run(cfg, **kw):
    """The real self-check, its machine reads faked: the process table holds the
    backend only while the API answers (a restarting backend has neither)."""
    return _real_run(cfg, procs=lambda: [BACKEND] if _up() else [(1, "explorer.exe")],
                     run_ok=lambda cmd: (True, ""), schedule=lambda: [{"times": ["21:30"]}],
                     contract=lambda d: types.SimpleNamespace(missing=[], unreadable=[], judged=True),
                     has_module=lambda m: True, **kw)


selfcheck.run = _run
# The scripts' update settings are another line's business (an empty fake reply has none).
selfcheck._handed_updates_gaps = lambda data: []


def boot(down_for):
    """Power on with the backend down for `down_for` seconds (None: never back); run the
    two steps that alarmed on 10-17. Returns (warnings, notifier, the self-check lines)."""
    now[0], polls[0] = 1000.0, 0
    back_at[0] = None if down_for is None else now[0] + down_for
    boot_stages._backend_gave_up = [None]
    rec = _Rec()
    lg = logging.getLogger("ark.test_boot_backend_wait")
    lg.handlers[:] = [rec]
    lg.setLevel(logging.INFO)
    lg.propagate = False
    selfcheck.log.handlers[:] = [rec]
    selfcheck.log.setLevel(logging.INFO)
    n = _Notifier()
    with tempfile.TemporaryDirectory() as td:
        os.environ["ARK_LOG_FILE"] = str(Path(td) / "relay.log")
        cfg = types.SimpleNamespace(automas_dir=None, state_dir=td, history_dir=td,
                                    phone_topic="t", phone_pin="p")
        boot_stages._stage_endfield_start(cfg, n, lg)
        boot_stages._stage_selfcheck(cfg, n, lg)
    lines = {r.getMessage() for r in rec.records if r.getMessage().startswith("开机自检")}
    return rec.warnings(), n, lines


def mas_lines(lines):
    return sorted(x for x in lines if "调度程序有应答" in x or "后台程序在跑" in x)


print("\n[10-17 21:21: the backend restarts and is back after 60 s - the steps wait, no alarm]")
warns, n, lines = boot(60)
check("no WARNING (efstart_setup's 「连不上」 is not logged)", warns, [])
check("no self-check alarm", [t for t, _, _ in n.sent if t == texts.SELFCHECK_FAILED], [])
check("both AUTO-MAS self-check lines pass",
      mas_lines(lines), sorted(["开机自检 ✓ 调度程序的后台程序在跑", "开机自检 ✓ 调度程序有应答"]))
check("waited about the 60 s, not the whole limit", 1060 <= now[0] < 1060 + 2 * boot_stages.BACKEND_POLL_SECONDS)
check("polled every few seconds, not once", polls[0] > 10)

print("\n[the backend never comes back - the same failures as before, saying the wait]")
warns, n, lines = boot(None)
limit = boot_stages.BACKEND_WAIT_SECONDS
check("efstart_setup's WARNING, its own text kept",
      [w for w in warns if "终末地开游戏的设置没全对上" in w and "调度程序没应答，终末地的开游戏设置没核对：连不上" in w
       and f"等了 {limit} 秒" in w] != [])
check("the self-check alarm, once", [t for t, _, _ in n.sent].count(texts.SELFCHECK_FAILED), 1)
body = next((b for t, b, _ in n.sent if t == texts.SELFCHECK_FAILED), "")
check("its body lists 调度程序有应答 with the wait", f"调度程序有应答：开机后中继叫过它一次，又等了 {limit} 秒，仍然没有应答" in body)
check("its body lists 调度程序的后台程序在跑", "调度程序的后台程序在跑" in body)
check("the boot waited the limit once, not again for the self-check",
      now[0], 1000.0 + limit)

print("\n[the backend answers at once - nothing waits, nothing is logged about it]")
warns, n, lines = boot(0)
check("no WARNING", warns, [])
check("no time spent", now[0], 1000.0)

print("\n[ensure_automas already gave up (revived, 120 s, 🔌 sent): no second wait]")
real_revive, real_shell = boot_stages._revive_automas, boot_stages.shell_running
boot_stages._revive_automas, boot_stages.shell_running = (lambda: None), (lambda: False)
now[0], back_at[0] = 1000.0, None
boot_stages._backend_gave_up = [None]
boot_stages.ensure_automas(timeout=120)
boot_stages._revive_automas, boot_stages.shell_running = real_revive, real_shell
t_after = now[0]
rec = _Rec()
lg = logging.getLogger("ark.test_boot_backend_wait")
lg.handlers[:] = [rec]
lg.propagate = False
with tempfile.TemporaryDirectory() as td:
    boot_stages._stage_endfield_start(types.SimpleNamespace(automas_dir=None, state_dir=td), _Notifier(), lg)
check("the step did not wait again", now[0], t_after)
check("its failure line says the 120 s", any("等了 120 秒" in w for w in rec.warnings()))

print("\n[a stop mid-wait: the step neither waits on nor alarms]")
now[0], back_at[0] = 1000.0, None
boot_stages._backend_gave_up = [None]
stops = iter([False, False, True])
boot_stages._stop_requested = lambda: next(stops, True)
rec = _Rec()
lg = logging.getLogger("ark.test_boot_backend_wait")
lg.handlers[:] = [rec]
lg.propagate = False
with tempfile.TemporaryDirectory() as td:
    boot_stages._stage_endfield_start(types.SimpleNamespace(automas_dir=None, state_dir=td), _Notifier(), lg)
check("no WARNING", rec.warnings(), [])
check("stopped after a few polls", now[0] < 1000.0 + 4 * boot_stages.BACKEND_POLL_SECONDS)
boot_stages._stop_requested = lambda: False

if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("\nall checks passed")
