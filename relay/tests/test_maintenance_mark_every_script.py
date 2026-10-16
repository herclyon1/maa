"""A failure inside an official maintenance window is marked for every script, on
the ledger and in the persisted hold, and its re-run is registered.

Audit 2026-10-13 s7 #1 / s1 #2: the mark sat in _archive_maaend_evidence - after
the ledger line was written and after its early returns - so the daily report
booked a plain failure, gameupdate.needs_rerun (it reads the ledger) never re-ran
what the 「进不了游戏」 alarm promised, and MAA / OK-WW never got the mark. The
alarm text also said 「20 秒内」 while the threshold is 30 seconds.
Review of 308e21b3: the mark is for a scheduled run being held (and the MaaEnd
update-restart hold, which lost it); a hand-started run (held only for its own
task's retries since 2026-10-16) and a MAA failure pushed at once on the update day
are not booked ⏸ nor re-run by the relay.
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                  ARK_AUTOMAS_DIR=str(TMP / "nowhere"), ARK_MAAEND_DIR="", SERVERCHAN_KEY="",
                  ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import engine as eng_mod                # noqa: E402
from ark_relay.core import texts                          # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core.ledger import State                    # noqa: E402
from ark_relay.features.alarm import handle                # noqa: E402
from ark_relay.features.gameupdate import gameupdate       # noqa: E402
from ark_relay.features.makeup import collect_retry        # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body))
        return []


class Src:
    def fetch(self, seen):
        return []


handle._ship_evidence = lambda eng, rec: ""
handle._hand_started = lambda eng, rec: ""
handle._weekly_gates = lambda eng, rec: None
handle._archive_okww_evidence = lambda eng, rec: None
collect_retry.restore_master = lambda cfg: ""


def build(state_dir):
    cfg = Config()
    cfg.state_dir = state_dir
    cfg.maaend_dir = None
    e = eng_mod.Engine(cfg, source=Src(), state=State(state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    return e


EVENING = datetime(2026, 10, 12, 21, 30, 5, tzinfo=SERVER_TZ)
WHY = "官方公告：10-12 21:00–23:00 终末地停服维护"

print("[MaaEnd fails inside the maintenance window]")
state = TMP / "s1"
state.mkdir()
gameupdate.save_windows(state, {"终末地": (EVENING - timedelta(minutes=30), EVENING + timedelta(hours=1, minutes=30), WHY)})
e = build(state)
rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-17-30-05", script="MaaEnd", user="endfield",
                started=EVENING, finished=EVENING + timedelta(minutes=3), ok=False,
                failed_tasks=["协议空间"], raw={})
handle._handle(e, rec)
row = next(x for x in e.state.read_ledger("2026-10-12") if x["run_id"] == rec.run_id)
check("the ledger line carries the mark", (row.get("raw") or {}).get("maintenance"), WHY)
held = State(state).load_pending().get("pending") or []
check("the persisted hold carries it (survives a restart)",
      [(p.get("raw") or {}).get("maintenance") for p in held], [WHY])
check("the game is registered for the re-run", "终末地" in gameupdate.pending(state), True)
check("needs_rerun reads it from the ledger",
      gameupdate.needs_rerun(state, EVENING + timedelta(hours=2), "MaaEnd"), True)

print("\n[MAA fails inside the maintenance window (pushed at once as the update day)]")
# Review of 308e21b3: the alarm says the evening shift runs it again, so it is not
# booked ⏸ nor re-run by the relay (the mark is for scheduled runs being held).
state = TMP / "s2"
state.mkdir()
gameupdate.save_windows(state, {"明日方舟": (EVENING - timedelta(minutes=30), EVENING + timedelta(hours=1), "明日方舟停服维护")})
e = build(state)
rec = RunRecord(run_id="2026-10-12/arknights/MAA-17-30-05", script="MAA", user="arknights",
                started=EVENING, finished=EVENING + timedelta(minutes=1), ok=False,
                failed_tasks=["MAA 在完成任务前中止"], raw={})
handle._handle(e, rec)
row = next(x for x in e.state.read_ledger("2026-10-12") if x["run_id"] == rec.run_id)
check("pushed as the update day", [t for t, _ in e.notifier.sent][-1:], [texts.failed("MAA")])
check("MAA's ledger line has no maintenance mark", (row.get("raw") or {}).get("maintenance"), None)
check("明日方舟 is not registered for a relay re-run", "明日方舟" in gameupdate.pending(state), False)
check("needs_rerun stays false", gameupdate.needs_rerun(state, EVENING + timedelta(hours=2), "MAA"), False)

print("\n[a hand-started MaaEnd failure inside the window: pushed, not marked, not re-run]")
state = TMP / "s4"
state.mkdir()
gameupdate.save_windows(state, {"终末地": (EVENING - timedelta(minutes=30), EVENING + timedelta(hours=1, minutes=30), WHY)})
e = build(state)
rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-17-35-00", script="MaaEnd", user="endfield",
                started=EVENING + timedelta(minutes=5), finished=EVENING + timedelta(minutes=8), ok=False,
                failed_tasks=["协议空间"], raw={})
handle._hand_started = lambda eng, r: "task-hand"
handle._handle(e, rec)
handle._hand_started = lambda eng, r: ""
row = next(x for x in e.state.read_ledger("2026-10-12") if x["run_id"] == rec.run_id)
# Held until its task's later attempts decide (handle._hold_hand_started), then pushed
# by the flush - not through its maintenance branch (no 进不了游戏 / re-run for it).
check("the persisted hold has no maintenance mark",
      [(p.get("raw") or {}).get("maintenance") for p in State(state).load_pending().get("pending") or []], [None])
e._flush_pending()
check("pushed once the task's attempts are over", len(e.notifier.sent), 1)
check("no maintenance mark on its ledger line", (row.get("raw") or {}).get("maintenance"), None)
check("终末地 is not registered for a relay re-run", "终末地" in gameupdate.pending(state), False)
check("needs_rerun stays false", gameupdate.needs_rerun(state, EVENING + timedelta(hours=2), "MaaEnd"), False)

print("\n[a MaaEnd update restart held inside the window keeps the mark]")
state = TMP / "s5"
state.mkdir()
gameupdate.save_windows(state, {"终末地": (EVENING - timedelta(minutes=30), EVENING + timedelta(hours=1, minutes=30), WHY)})
e = build(state)
rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-17-40-00", script="MaaEnd", user="endfield",
                started=EVENING + timedelta(minutes=10), finished=EVENING + timedelta(minutes=11), ok=False,
                failed_tasks=["协议空间"], raw={"maaend_update_restart": "v1.2.3"})
handle._handle(e, rec)
row = next(x for x in e.state.read_ledger("2026-10-12") if x["run_id"] == rec.run_id)
check("held", (rec.script, rec.user) in e._pending, True)
check("the ledger line carries the mark", (row.get("raw") or {}).get("maintenance"), WHY)
held = State(state).load_pending().get("pending") or []
check("the persisted hold carries it", [(p.get("raw") or {}).get("maintenance") for p in held], [WHY])
check("终末地 is registered for the re-run", "终末地" in gameupdate.pending(state), True)

print("\n[the 「进不了游戏」 text states the real threshold]")
state = TMP / "s3"
state.mkdir()
e = build(state)
rec = RunRecord(run_id="2026-10-12/endfield/MaaEnd-06-04-00", script="MaaEnd", user="endfield",
                started=EVENING - timedelta(hours=11), finished=EVENING - timedelta(hours=11) + timedelta(minutes=2),
                ok=False, failed_tasks=["协议空间"],
                raw={"maaend_unreachable": True, "maaend_unreachable_why": "官方公告：今天版本更新"})
e._pending[(rec.script, rec.user)] = rec
e._flush_pending()
body = "\n".join(b for _, b in e.notifier.sent)
check("says 30 seconds", "30 秒内失败" in body, True)
check("never 20 seconds", "20 秒" in body, False)

print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
