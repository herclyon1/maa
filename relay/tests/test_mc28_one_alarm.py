"""MaaEnd stopping itself inside one of the four tasks, with no other run of the day to
make up for it, reaches the group once per abort: not twice, and not zero times.

Review of verify ledger #28 (item 2), as the machine books it: when MaaEnd stops
itself AUTO-MAS marks every later task failed, so the run is booked ok=False with 13
failed tasks (the 10-08 sim ledger, MaaEnd-06-31-06) and held for its retry
(handle._hold_for_retry); the retry MaaEnd-06-34-21 is booked ok=True three minutes
later and pushes 「终末地早班 2 项没证据」 naming 装备制造 with MaaEnd's own reason
(pushes._push_unverified). Machine check #28 had already pushed 「上机核对没过：#28」
for the same abort at the held booking - one cause, two messages. Now a #28 FAIL of a
held record waits for the hold to end (runs._hold_28) and is then settled
(runs.settle_28): carried by a 「没证据」 alarm actually sent for those tasks, made up
for by another run of the day, or pushed on its own.

And a second abort of the same day must still reach the group: the 「没证据」 alarm is
keyed by its items, so a second run leaving the same items unbacked sends nothing,
and #28 must then push (it used to be marked as riding along with an alarm that
did not go out).

Data: the real 2026-10-08 runs (fixtures/maaend-task-trail/: AUTO-MAS logs, MaaFW's
lines of 10-08), booked through handle._handle on one Engine per scenario.
"""
import gzip
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                  ARK_AUTOMAS_DIR=str(TMP / "nowhere"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="",
                  ARK_LOG_FILE=str(TMP / "relay.log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core import engine as eng_mod, texts          # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core.ledger import State                     # noqa: E402
from ark_relay.features.alarm import handle, runchecks, unresolved  # noqa: E402
from ark_relay.features.makeup import makeup                # noqa: E402
from ark_relay.features.selfcheck import machinecheck as mc  # noqa: E402
from ark_relay.features.selfcheck.machinechecks import runs  # noqa: E402
from ark_relay.features.verify import collector_maaend      # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "maaend-task-trail"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body, alert))
        return []


class Src:
    def fetch(self, seen):
        return []


handle._ship_evidence = lambda eng, rec: "https://cos.example/endfield.zip"
handle._hand_started = lambda eng, rec: ""
handle._weekly_gates = lambda eng, rec: None

# AUTO-MAS's failed list for MaaEnd-06-31-06 (the 10-08 sim ledger): every task after
# the abort; 装备制造 itself is not on it.
FAILED_0631 = ["拜访好友", "基建任务", "信用点购物", "转交委托", "据点交易", "环境监测", "自动囤货", "售卖弹性物资",
               "购买稳定物资", "协议空间", "选剑演武", "自动采集", "日常奖励领取"]
ABORT = ("2026-10-08_MaaEnd-06-31-06.log", datetime(2026, 10, 8, 10, 32, 8, tzinfo=SERVER_TZ), 2.2)
RETRY = ("2026-10-08_MaaEnd-06-34-21.log", datetime(2026, 10, 8, 10, 35, 24, tzinfo=SERVER_TZ), 38)
CRAFTED = ("2026-10-08_MaaEnd-05-29-15.log", datetime(2026, 10, 8, 9, 30, 13, tzinfo=SERVER_TZ), 60)
MC28_FAILED = texts.machinecheck_failed("#28", "")
REASON = "· 装备制造：终末地自己检查画面没过，把后面的任务全停了，这一项没做成"


def held_28(state):
    return runs._state_get(state, getattr(runs, "HELD_28", "#28-held")) or {}


def engine(state=None):
    """(Engine, Notes, state folder): a fresh Engine on `state` (a new folder when None)."""
    cfg = Config()
    if state is None:
        state = tmpdir() / "state"
        state.mkdir()
    cfg.state_dir = state
    end = tmpdir()
    (end / "debug").mkdir()
    (end / "debug" / "maafw.log").write_bytes(gzip.decompress((FIX / "maafw-2026-10-08.log.gz").read_bytes()))
    cfg.maaend_dir = str(end)
    notes = Notes()
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=notes)
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._verify_outcome = lambda r: None
    return e, notes, state


def book(e, run, ok, rid=None, later_h=0):
    name, started, mins = run
    started += timedelta(hours=later_h)
    log = FIX / name
    rec = RunRecord(run_id=rid or f"2026-10-08/endfield/{name[11:-4]}", script="MaaEnd", user="endfield",
                    started=started, finished=started + timedelta(minutes=mins), ok=ok,
                    failed_tasks=[] if ok else list(FAILED_0631),
                    raw=collector_maaend.parse_maaend_log(log), log_path=log)
    handle._handle(e, rec)
    return rec


def group(*notes):
    return [(t, b) for n in notes for t, b, alert in n.sent if alert]


def show(*notes):
    for t, b in group(*notes):
        print(f"    group: {t} | {b[:120]!r}")


def mc28_pushes(*notes):
    return [b for t, b in group(*notes) if t.startswith(MC28_FAILED)]


print("[real shape: 06-31-06 ok=False with 13 failed tasks, held; its retry 06-34-21 ok=True]")
e, notes, state = engine()
book(e, ABORT, ok=False)
check("nothing reaches the group while the abort waits for its retry", group(notes), [])
row = mc.read(state).get("#28") or {}
ev = str(row.get("evidence") or "")
check("#28's FAIL of the held abort is on record, saying it waits for the retry",
      (row.get("status"), "等这一班的重试跑完" in ev), ("FAIL", True))
check("…and does not say it went to the group", "进群里" in ev or "已写在" in ev, False)
check("…and is kept to be settled", list(held_28(state)), ["2026-10-08/endfield/MaaEnd-06-31-06"])
book(e, RETRY, ok=True)
handle._flush_pending(e)
show(notes)
check("one group message for the abort and the retry", len(group(notes)), 1)
title, body = group(notes)[0] if group(notes) else ("", "")
check("…the retry's 「没证据」 alarm for both items", title, texts.unverified_alarm("终末地", "早班", 2))
check("…carrying MaaEnd's own verdict and reason for 装备制造",
      (REASON in body, "账号编号显示不全" in body), (True, True))
check("no 「上机核对没过：#28」 of its own", mc28_pushes(notes), [])
check("nothing of #28 is left waiting", held_28(state), {})
check("the per-record note is dropped after the checks", runchecks._UNVERIFIED, {})

print("\n[real shape twice the same day: abort + retry in the morning, abort + retry in the evening]")
e, notes, state = engine()
book(e, ABORT, ok=False)
book(e, RETRY, ok=True)
handle._flush_pending(e)
n_morning = len(group(notes))
book(e, ABORT, ok=False, rid="2026-10-08/endfield/MaaEnd-14-31-06", later_h=8)
book(e, RETRY, ok=True, rid="2026-10-08/endfield/MaaEnd-14-34-21", later_h=8)
handle._flush_pending(e)
show(notes)
check("the morning abort: one message", n_morning, 1)
check("the evening abort reaches the group too: two messages in all", len(group(notes)), 2)
check("…the second is #28's own FAIL naming 装备制造 and MaaEnd's reason (the 「没证据」 alarm for "
      "the same items went out in the morning)",
      [("装备制造" in b, "账号编号显示不全" in b) for b in mc28_pushes(notes)], [(True, True)])
check("nothing of #28 is left waiting", held_28(state), {})

print("\n[ok=True abort twice the same day: the 「没证据」 alarm for the same items goes out once]")
e, notes, state = engine()
book(e, ABORT, ok=True)
book(e, ABORT, ok=True, rid="2026-10-08/endfield/MaaEnd-14-31-06", later_h=8)
show(notes)
got = group(notes)
check("two group messages for two aborts", len(got), 2)
check("…the first the 「没证据」 alarm with the reason",
      (got[0][0] if got else "", REASON in (got[0][1] if got else "")),
      (texts.unverified_alarm("终末地", "早班", 1), True))
check("…the second #28's own FAIL", len(mc28_pushes(notes)), 1)
check("…which is not marked as riding along with an alarm that did not go out",
      "已写在「没证据」" in str((mc.read(state).get("#28") or {}).get("evidence")), False)

print("\n[the same ok=True record replayed (its handling broke off): still the one alarm it sent]")
e, notes, state = engine()
book(e, ABORT, ok=True)
book(e, ABORT, ok=True)
show(notes)
check("one group message, the 「没证据」 alarm", [t for t, _ in group(notes)],
      [texts.unverified_alarm("终末地", "早班", 1)])

print("\n[the held abort's retries never get through: its alarm goes out, and so does #28's FAIL]")
e, notes, state = engine()
real_after, real_refuse = unresolved.after_makeup, makeup.refuse_rejected
unresolved.after_makeup = lambda eng, rec, now=None: (unresolved.UNRESOLVED, "补跑也没成")
makeup.refuse_rejected = lambda eng, rec: None
try:
    book(e, ABORT, ok=False)
    check("waiting, nothing sent", group(notes), [])
    handle._flush_pending(e)
finally:
    unresolved.after_makeup, makeup.refuse_rejected = real_after, real_refuse
show(notes)
check("two messages: the failure alarm and #28's FAIL", len(group(notes)), 2)
check("#28's FAIL for 装备制造 went out once the hold ended",
      [("装备制造" in b, "账号编号显示不全" in b) for b in mc28_pushes(notes)], [(True, True)])
check("nothing of #28 is left waiting", held_28(state), {})

print("\n[a relay restart between the abort and its retry]")
e, notes, state = engine()
book(e, ABORT, ok=False)
e2, notes2, _ = engine(state)
check("the abort is still held after the restart",
      [r.run_id for r in e2._pending.values()], ["2026-10-08/endfield/MaaEnd-06-31-06"])
book(e2, RETRY, ok=True)
handle._flush_pending(e2)
show(notes, notes2)
check("one group message, the 「没证据」 alarm with the reason",
      [(t, REASON in b) for t, b in group(notes, notes2)],
      [(texts.unverified_alarm("终末地", "早班", 2), True)])

print("\n[a run of the same day that crafted is booked after the held abort: made up for]")
e, notes, state = engine()
book(e, ABORT, ok=False)
book(e, CRAFTED, ok=True, rid="2026-10-08/endfield/MaaEnd-07-29-15")
handle._flush_pending(e)
show(notes)
check("no group message names 装备制造", [t for t, b in group(notes) if "装备制造" in t + b], [])
check("no 「上机核对没过：#28」", mc28_pushes(notes), [])
check("nothing of #28 is left waiting", held_28(state), {})
sec = [x for x in mc.daily_section(state).splitlines() if "#28" in x]
print(f"    daily: {sec}")
check("the daily section says the abort's 装备制造 failed and was made up for",
      any("装备制造" in x and "不用人管" in x for x in sec), True)

print()
if fails:
    print(f"✗ {len(fails)} 条没过：{fails}")
    sys.exit(1)
print("all checks passed")
