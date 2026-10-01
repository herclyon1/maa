"""The shutdown floor is an alarm: once 「开机不够久」 passes, the relay judges again.

2026-10-01: the relay restarted at 18:03:57, judged 「开机不够久」 at 18:04:15
(floor 600 s) and then slept until its next alarm, 21:30. Nothing judged again
when the floor passed at 18:13:57.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(TMP / "history").mkdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), ARK_SHUTDOWN_AFTER_RUN="1",
                  ARK_SHUTDOWN_MIN_UPTIME="600", ARK_CHECK_TIMES="",
                  SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                  WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import engine as eng                     # noqa: E402
from ark_relay.config import SERVER_TZ, Config          # noqa: E402
from ark_relay.core import State                        # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Notes:
    def send(self, title, body="", **kw):
        return False


def at(hh, mm, ss=0):
    return datetime(2026, 10, 1, hh, mm, ss, tzinfo=SERVER_TZ)


def build(after_run=True):
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.shutdown_after_run = after_run
    e = eng.Engine(cfg, source=None, state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._started_at = at(18, 3, 57)
    return e


print("[10-01: restarted 18:03:57, floor 600 s -> the next alarm is 18:13:57]")
when, why = build().next_deadline(at(18, 4, 15))
check("when", when, at(18, 13, 57))
check("why", why, "开机满下限，重新判一次关机")

print("\n[past the floor it is no longer an alarm]")
d = build().next_deadline(at(18, 20))
check("not the floor any more", bool(d) and d[1] == "开机满下限，重新判一次关机", False)

print("\n[shutdown switched off -> no floor alarm]")
d = build(after_run=False).next_deadline(at(18, 4, 15))
check("no floor alarm", bool(d) and d[1] == "开机满下限，重新判一次关机", False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
