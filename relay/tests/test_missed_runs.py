"""A queue that was due and produced nothing must alarm - and must not alarm
when the machine simply was not awake for it.

The distinction used to be made with the relay's own start time, which every
selfupdate resets. An update that ran past the queue's time therefore made the
new process disqualify itself and swallow a real missed run.
"""
import json, os, sys, tempfile
from datetime import datetime
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
AUTOMAS = TMP / "AUTO-MAS"; (AUTOMAS / "config").mkdir(parents=True)
STATE = TMP / "state"; STATE.mkdir()
HIST = TMP / "history"; HIST.mkdir()

(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({
    "instances": [{"uid": "q1"}],
    "q1": {"Info": {"Name": "Evening-MAA", "TimeEnabled": True},
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

from ark_relay.config import Config, SERVER_TZ  # noqa: E402
from ark_relay.core import State                # noqa: E402
from ark_relay.notify import Notifier           # noqa: E402
from ark_relay.engine import Engine             # noqa: E402

sent = []
class FakeNotifier(Notifier):
    def send(self, title, body):
        sent.append(title)
        return []

cfg = Config()
E = Engine(cfg, source=None, state=State(cfg.state_dir), notifier=FakeNotifier(cfg))
BOOT = [None]
E._boot_time = lambda now: BOOT[0]

def at(hh, mm):
    return datetime(2026, 8, 21, hh, mm, tzinfo=SERVER_TZ)

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

def reset():
    sent.clear()
    E._missed_alerted.clear()

print("[the swallowed alarm] selfupdate restarted the relay past the queue time")
reset()
BOOT[0] = at(21, 20)        # the machine WAS awake for 21:30
E._started_at = at(21, 33)  # but this process only started at 21:33
E._check_missed_runs(at(22, 0))
check("alarms", len(sent), 1)

print("\n[machine really was off] must stay quiet")
reset()
BOOT[0] = at(22, 40)        # powered on well after the queue
E._started_at = at(22, 42)
E._check_missed_runs(at(23, 10))
check("silent", len(sent), 0)

print("\n[not late yet] grace is 25 minutes")
reset()
BOOT[0] = at(21, 20); E._started_at = at(21, 22)
E._check_missed_runs(at(21, 50))
check("silent at +20min", len(sent), 0)
reset()
E._check_missed_runs(at(21, 56))
check("alarms at +26min", len(sent), 1)

print("\n[it did run] must stay quiet")
reset()
(STATE / "ledger-2026-08-21.jsonl").write_text(json.dumps({
    "script": "MAA", "started": at(21, 31).isoformat(),
    "finished": at(22, 15).isoformat(), "ok": True, "run_id": "x"}), encoding="utf-8")
BOOT[0] = at(21, 20); E._started_at = at(21, 22)
E._check_missed_runs(at(22, 30))
check("silent", len(sent), 0)
(STATE / "ledger-2026-08-21.jsonl").unlink()

print("\n[alarms once, not every tick]")
reset()
BOOT[0] = at(21, 20); E._started_at = at(21, 22)
for _ in range(5):
    E._check_missed_runs(at(22, 0))
check("exactly one", len(sent), 1)

print("\n[uptime unknown] falls back to the relay's start time")
reset()
BOOT[0] = None
E._started_at = at(21, 33)
E._check_missed_runs(at(22, 0))
check("silent, as before this change", len(sent), 0)

print("\n[partial queue] MAA ran, MaaEnd never did, relay restarted past the time")
# Same fix, second site: _check_partial_queues used the relay's start time too.
reset()
(STATE / "ledger-2026-08-21.jsonl").write_text(json.dumps({
    "script": "MAA", "started": at(21, 31).isoformat(),
    "finished": at(21, 55).isoformat(), "ok": True, "run_id": "x"}), encoding="utf-8")
import ark_relay.plan as _plan
_orig = _plan.recent_due_queues
_plan.recent_due_queues = lambda d, n, window_minutes=120: [
    {"name": "Evening-MAA", "due": at(21, 30), "kinds": ["MAA", "MaaEnd"]}]
BOOT[0] = at(21, 20)
E._started_at = at(21, 40)          # restarted after the queue started
E._check_partial_queues(at(23, 0), "2026-08-21",
                        E.state.read_ledger("2026-08-21"))
check("alarms about the missing MaaEnd", len(sent), 1)

reset()
BOOT[0] = at(23, 0)                 # machine genuinely was not awake
E._check_partial_queues(at(23, 30), "2026-08-21",
                        E.state.read_ledger("2026-08-21"))
check("silent when the machine was off", len(sent), 0)
_plan.recent_due_queues = _orig
(STATE / "ledger-2026-08-21.jsonl").unlink()

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
