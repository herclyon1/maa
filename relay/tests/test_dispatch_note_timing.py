"""The relay notes "this run is mine" right before the dispatch call, after the
OK-WW overlay step.

Evidence audit 2026-10-13: commands.run_script / _run_now called _note_dispatch
first and okww_overlay.retry_pending second. The overlay step has no time limit,
so a slow one let AUTO-MAS create the task more than trigger.MATCH_AFTER_S (60 s)
after the note, and trigger.hand_started_task then booked the relay's own run as
hand-started (no make-up, no overrun alarm).
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.guard import trigger  # noqa: E402
from ark_relay.features.okww_patch import okww_overlay as ov  # noqa: E402
from ark_relay.features.phone import commands  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


clock = {"t": datetime(2026, 10, 13, 8, 0, 0, tzinfo=SERVER_TZ)}
created: list[trigger.Task] = []


def slow_overlay(where):
    clock["t"] += timedelta(seconds=120)     # an overlay step that takes two minutes
    return ""


def mas(path, body=None):
    if path == "/api/scripts/get":
        return {"data": {"s1": {"Info": {"Name": "OK-WW"}}}}
    if path == "/api/queue/get":
        return {"data": {"q1": {"Info": {"Name": "早班"}}}}
    # AUTO-MAS labels the relay's start manual_task, like a click on its screen.
    created.append(trigger.Task(id=body["taskId"], mode="AutoProxy", source=trigger.MANUAL,
                                created=clock["t"] + timedelta(seconds=2)))
    return {"status": "success"}


real = (ov.retry_pending, commands._mas, trigger.note_dispatch)
real_note = trigger.note_dispatch
ov.retry_pending = slow_overlay
commands._mas = mas
trigger.note_dispatch = lambda state_dir, what, now=None: real_note(state_dir, what, now=clock["t"])
state = Path(os.environ["ARK_STATE_DIR"])
try:
    print("[a slow overlay step before a single-script dispatch]")
    check("dispatched", commands.run_script("OK-WW")[0], True)
    check("the relay's own run is not hand-started", trigger.hand_started_task(created[-1], state), False)

    print("\n[a slow overlay step before a queue dispatch]")
    clock["t"] += timedelta(hours=1)
    check("dispatched", commands._run_now("早班")[0], True)
    check("the relay's own run is not hand-started", trigger.hand_started_task(created[-1], state), False)
finally:
    ov.retry_pending, commands._mas, trigger.note_dispatch = real

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
