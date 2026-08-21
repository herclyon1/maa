"""Exercise the shutdown gate changes against a fake AUTO-MAS + ledger.

Covers the bug being fixed (restart after the run leaves nobody to shut down)
and the two ways the fix could itself cost a run (powering off before the
queue, powering off mid-queue).
"""
import json, os, sys, tempfile
from datetime import datetime, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
AUTOMAS = TMP / "AUTO-MAS"; (AUTOMAS / "config").mkdir(parents=True)
STATE = TMP / "state"; STATE.mkdir()
HIST = TMP / "history"; HIST.mkdir()

# AUTO-MAS's real config shape: instances[] + a node per uid.
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({
    "instances": [{"uid": "q1"}],
    "q1": {"Info": {"Name": "Evening-MAA", "TimeEnabled": True,
                    "AfterAccomplish": "NoAction"},
           "SubConfigsInfo": {
               "TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "21:30"}}},
               "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}}}),
    encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({
    "instances": [{"uid": "s1"}],
    "s1": {"Info": {"Name": "arknights", "Path": "D:\\MAA-v5.1.0-win-x64"},
           "SubConfigsInfo": {"UserData": {"u1": {
               "Info": {"Name": "arknights", "Stage": "1-7", "MedicineNumb": 0},
               "Task": {}}}}}}),
    encoding="utf-8")

os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(STATE), ARK_SHUTDOWN_AFTER_RUN="1",
                  ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.config import Config, SERVER_TZ           # noqa: E402
from ark_relay.core import State                        # noqa: E402
from ark_relay.notify import Notifier                   # noqa: E402
from ark_relay import engine as eng                     # noqa: E402
from ark_relay import plan                              # noqa: E402

cfg = Config()
print("queues seen by plan:", [q["name"] for q in plan.schedule(cfg.automas_dir)])

state = State(cfg.state_dir)
E = eng.Engine(cfg, source=None, state=state, notifier=Notifier(cfg))
E._scripts_running = lambda: False           # no games on this Mac
E._idle_checkpoint = lambda now=None: False  # test the normal path only

# GetTickCount64 is Windows-only; drive the uptime gate explicitly instead.
BOOT = [None]
E._boot_time = lambda now: BOOT[0]

DAY = "2026-08-21"
def ledger(*rows):
    # jsonl, one record per line - the real format
    for d in (DAY, "2026-08-20"):
        (STATE / f"ledger-{d}.jsonl").write_text("", encoding="utf-8")
    (STATE / f"ledger-{DAY}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")

def at(hh, mm):
    return datetime(2026, 8, 21, hh, mm, tzinfo=SERVER_TZ)

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
    if not ok:
        fails.append(label)

run = {"script": "MAA", "started": at(21, 31).isoformat(),
       "finished": at(22, 15).isoformat(), "ok": True, "run_id": "x"}

print("\n[the bug] relay restarted after the run finished")
ledger(run)
E._handled_any = False                    # a fresh process, as after selfupdate
E._started_at = at(22, 20)                # started after the queue
BOOT[0] = at(21, 20)                      # machine booted for this queue
check("work_is_done at 22:25", E._work_is_done(at(22, 25), E._recent_entries(at(22, 25))), True)

print("\n[regression] must NOT power off a machine booted AFTER the queue ran")
# Somebody powers the machine on at 22:20 to work on it. The 21:30 queue is
# still inside its two-hour window and its records are in the ledger, so
# without the uptime gate this reads as "everything finished, shut down".
BOOT[0] = at(22, 20)
check("booted after the queue -> hold",
      E._work_is_done(at(22, 30), E._recent_entries(at(22, 30))), False)
BOOT[0] = None
check("uptime unknown -> hold",
      E._work_is_done(at(22, 30), E._recent_entries(at(22, 30))), False)
BOOT[0] = at(21, 20)

print("\n[regression] must NOT power off before its own queue")
ledger()
check("work_is_done at 21:00 (queue still ahead)",
      E._work_is_done(at(21, 0), E._recent_entries(at(21, 0))), False)
check("work_is_done at 08:50 (nothing due at all)",
      E._work_is_done(at(8, 50), E._recent_entries(at(8, 50))), False)

print("\n[regression] must NOT power off mid-queue")
ledger()
check("due at 21:30, no records yet -> 21:40",
      E._work_is_done(at(21, 40), E._recent_entries(at(21, 40))), False)

print("\n[maintenance hold]")
mark = STATE / "ark-do-last.txt"
check("no marker -> -1", E._hands_on_machine(at(22, 25)), -1)
mark.write_text(str(int(at(22, 20).timestamp())), encoding="ascii")
check("5 minutes ago", E._hands_on_machine(at(22, 25)), 300)
check("held (5min < 20min)", 0 <= E._hands_on_machine(at(22, 25)) < eng.MAINTENANCE_HOLD_SEC, True)
check("released after 25 minutes",
      0 <= E._hands_on_machine(at(22, 45)) < eng.MAINTENANCE_HOLD_SEC, False)
mark.write_text("not-a-number", encoding="ascii")
check("corrupt marker ignored", E._hands_on_machine(at(22, 25)), -1)
mark.write_text(str(int(at(23, 59).timestamp())), encoding="ascii")
check("future marker ignored", E._hands_on_machine(at(22, 25)), -1)
mark.unlink()

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
