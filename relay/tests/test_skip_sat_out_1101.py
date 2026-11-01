"""A queue skipped on purpose stays skipped for that day's checks after its restore.

2026-11-01: 晚班 was skipped (skip_today), the machine stayed on, the restore re-enabled the
queue at 22:03:45 (Beijing) and at 22:03:47 the missed-run check pushed 「🔌 晚班 没有运行」;
the overdue check and the shutdown wait also still counted 晚班 as missing MAA.
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
STATE = TMP / "state"
STATE.mkdir()
HIST = TMP / "history"
HIST.mkdir()

(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({
    "instances": [{"uid": "q1"}],
    "q1": {"Info": {"Name": "晚班", "TimeEnabled": True},
           "SubConfigsInfo": {
               "TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "21:30"}}},
               "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}}}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({
    "instances": [{"uid": "s1"}],
    "s1": {"Info": {"Name": "arknights", "Path": "D:\\MAA-v5.1.0-win-x64"},
           "SubConfigsInfo": {"UserData": {"u1": {"Info": {"Name": "arknights"}}}}}}),
    encoding="utf-8")

os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(STATE), SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core.config import Config, SERVER_TZ  # noqa: E402
from ark_relay.core.ledger import State  # noqa: E402
from ark_relay.core.notify import Notifier  # noqa: E402
from ark_relay.core.engine import Engine  # noqa: E402
from ark_relay.features.modes import modes  # noqa: E402
from ark_relay.features.schedule import queues as _q  # noqa: E402
from ark_relay.features.shutdown import shutdown  # noqa: E402

sent = []


class FakeNotifier(Notifier):
    def send(self, title, body, *, alert=False, daily=False):
        sent.append((title, alert))
        return []


cfg = Config()
E = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=FakeNotifier(cfg))
E._boot_time = lambda now: at(8, 0)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def at(hh, mm):
    return datetime(2026, 11, 1, hh, mm, 45, tzinfo=SERVER_TZ)


DAY = "2026-11-01"


def reset():
    sent.clear()
    E._missed_alerted.clear()
    E.state.store.pop("marks", f"alerted:{DAY}")
    E.state.store.pop("queues", f"skip_done:{DAY}")


print("[control] not skipped: 22:03 with no 21:30 record still alarms")
reset()
E._check_missed_runs(at(22, 3))
check("alarms", len(sent), 1)

print("\n[the 11-01 false alarm] skipped, engaged, restored after the slot: silent")
reset()
real_apply = _q.apply
_q.apply = lambda d, q, enabled: (True, "")
try:
    modes.add_day_queue(STATE, DAY, "晚班")
    modes.process_skip(STATE, AUTOMAS, at(21, 8))     # engages: marker for today
    check("engaged", modes.skipped_today_all(STATE, at(21, 9)), ["晚班"])
    modes.process_skip(STATE, AUTOMAS, at(22, 3))     # past the slot: restored, marker dropped
    check("phone switch is off again", modes.skipped_today_all(STATE, at(22, 4)), [])
    check("but the day remembers it sat out", modes.sat_out(STATE, DAY), ["晚班"])
finally:
    _q.apply = real_apply
E._check_missed_runs(at(22, 3))
check("no 「没有运行」", sent, [])

print("\n[overdue and shutdown] the skipped queue owes no script")
q = {"name": "晚班", "due": at(21, 30).replace(second=0), "kinds": ["MAA"]}
check("missing kinds", shutdown._missing_kinds(E, q, []), [])

print("\n[only that day] tomorrow's 21:30 is checked as usual")
check("tomorrow not sat out", modes.sat_out(STATE, "2026-11-02"), [])

print("\nall checks passed" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
