"""stop-push's errwatch: the relay's power-off probe, and the whole run inside the watchdog's time.

Review of e20dc77f + 7c1ba65c (audit 2026-10-13 s5):
  1. `app_main.py stop-push` installed errwatch without the relay's power-off probe, so
     errwatch.relay_shutdown_issued() was always false in that process. The engine that
     knows lives in the relay's process; the relay now keeps the moment in state.json
     (shutdown._record_poweroff) and stop-push's probe reads it
     (shutdown.relay_poweroff_recorded), cleared when the countdown is cancelled and
     stale after ISSUED_STUCK_MIN, as boot_stages._relay_poweroff_live.
  2. The lint commit moved stop-push's drain from 2 s to errwatch.drain's default (3 s);
     the slow-network test stubs the drain out. Here the real stop_push runs with the
     send hanging and a WARNING the group never acknowledges, the drain as it is, and
     STOP_PUSH_WAIT_S + what stop_push adds around the send + a Python start must stay
     inside the watchdog's PUSH_TIMEOUT_S (packaging/watchdog/ark_watchdog.py).
"""
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

DATA = tmpdir()
(DATA / "state").mkdir()
os.environ.update(ARK_HOME=str(DATA), ARK_PHONE_TOPIC="arktest-topic", ARK_PHONE_PIN="1234",
                  SERVERCHAN_KEY="", WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="")
for _k in ("ARK_LOG_FILE", "ARK_STATE_DIR", "ARK_AUTOMAS_DIR"):
    os.environ.pop(_k, None)

import app_main  # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config  # noqa: E402
from ark_relay.core.ledger import State  # noqa: E402
from ark_relay.features.alarm import errwatch  # noqa: E402
from ark_relay.features.phone import phone  # noqa: E402
from ark_relay.features.shutdown import shutdown  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


class Eng:
    def __init__(self, state_dir):
        self.state = State(state_dir)


STATE = app_main._relay_env()      # what stop_push and its Config() use
record = getattr(shutdown, "_record_poweroff", lambda eng, at: None)
recorded = getattr(shutdown, "relay_poweroff_recorded", lambda sd, now=None: False)
now = datetime.now(tz=SERVER_TZ)

print("[1. the relay's own power-off, seen from stop-push's process]")
eng = Eng(STATE)
record(eng, now - timedelta(minutes=1))
check("recorded a minute ago: the relay's own power-off", recorded(STATE, now), True)
check(f"recorded {shutdown.ISSUED_STUCK_MIN} min ago: stale, not ours any more",
      recorded(STATE, now + timedelta(minutes=shutdown.ISSUED_STUCK_MIN)), False)
app_main._stop_push_errwatch(Config())
check("stop-push's errwatch asks it: relay_shutdown_issued() is true", errwatch.relay_shutdown_issued(), True)
record(eng, None)
check("countdown cancelled: not the relay's power-off", errwatch.relay_shutdown_issued(), False)
check("nothing recorded at all: not ours", recorded(DATA / "elsewhere", now), False)

print("[2. the whole stop-push path inside the watchdog's time]")
src = (RELAY.parent / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8")
PUSH_TIMEOUT_S = int(re.search(r"^PUSH_TIMEOUT_S\s*=\s*(\d+)", src, re.M).group(1))
release = threading.Event()


class Hang:
    """The group never answers: errwatch's push is in flight for the whole drain."""
    _state_dir = STATE

    def send(self, *a, **k):
        release.wait(120)
        return []

    def __getattr__(self, name):
        return lambda *a, **k: []


h = errwatch._handler[0]
h._notifier = Hang()
logging.getLogger("ark.app.stop_push").warning("a WARNING the group does not acknowledge")
phone.state_cos = lambda cfg: object()
phone.send_state = lambda box, cfg, why, log: release.wait(120) or (False, "")   # the send hangs
WAIT = 0.5
t0 = time.monotonic()
code = app_main.stop_push(wait_s=WAIT)
took = time.monotonic() - t0
around = took - WAIT
check("the send ran out its time: exit code 1", code, 1)
check(f"the drain is in it ({around:.2f} s around the send, drain default 3 s)", around >= 2.5, True)
t1 = time.monotonic()
# A fresh interpreter importing what stop_push imports (this process has them loaded already).
subprocess.run([sys.executable, "-c", "import app_main, ark_relay.__main__, ark_relay.core.notify, "
                "ark_relay.core.statestore, ark_relay.features.alarm.errwatch, ark_relay.features.phone.phone, "
                "ark_relay.features.shutdown.shutdown"], cwd=RELAY, check=True, capture_output=True)
start = time.monotonic() - t1
total = app_main.STOP_PUSH_WAIT_S + around + start
check(f"{app_main.STOP_PUSH_WAIT_S} s send + {around:.2f} s drain and the rest + {start:.2f} s start"
      f" = {total:.1f} s < the watchdog's {PUSH_TIMEOUT_S} s", total < PUSH_TIMEOUT_S, True)
release.set()

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
