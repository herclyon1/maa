"""A held failure pushed later is pushed with the evidence captured when it was held.

Audit 2026-10-13 review of s7 #2 (fdc53123): a held OK-WW / MaaEnd failure pushed
after a person's hand-started success went through handle._failure_alarm, which
captured evidence again into the held run's folder - the person's screen, log tail
and MaaEnd debug logs over the real ones. manualstops._push_before_stop (a held
failure a 停一切 cut off) had the same flaw. Each capture is counted per run here.
"""
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
(AUTOMAS / "debug").mkdir()
for name in ("QueueConfig.json", "ScriptConfig.json"):
    (AUTOMAS / "config" / name).write_text(json.dumps({"instances": []}), encoding="utf-8")
HIST = TMP / "history"
HIST.mkdir()
os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.features.alarm import handle, manualstops   # noqa: E402
from ark_relay.core import engine as eng_mod                 # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core.ledger import State                        # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent, self.bodies = [], []

    def send(self, title, body="", **kw):
        self.sent.append((title, kw.get("alert", False)))
        self.bodies.append(body)
        return []      # no errors: sent


class Src:
    def fetch(self, seen):
        return []


captures = Counter()
handle._archive_okww_evidence = lambda eng, r: captures.update([r.run_id])
handle._weekly_gates = lambda eng, r: None
handle._ship_evidence = lambda eng, r: ""
HAND = {"OK-WW-ok", "MaaEnd-ok"}
handle._hand_started = lambda eng, r: "task-1" if r.run_id in HAND else ""


def build():
    cfg = Config()
    cfg.state_dir = TMP / "state"
    cfg.state_dir.mkdir(exist_ok=True)
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._verify_outcome = lambda r: None
    e._archive_maaend_evidence = lambda r: captures.update([r.run_id])
    return e


def rec(run_id, started, ok=False, script="OK-WW", user="wuthering"):
    return RunRecord(run_id=run_id, script=script, user=user, started=started,
                     finished=started + timedelta(minutes=5), ok=ok,
                     failed_tasks=[] if ok else ["日常任务"], raw={})


T0 = datetime(2026, 10, 12, 6, 0, tzinfo=SERVER_TZ)

for script, user in (("OK-WW", "wuthering"), ("MaaEnd", "endfield")):
    print(f"\n[{script}：定时那趟失败压着，后来有人手动跑成 → 照报，不再取证]")
    captures.clear()
    e = build()
    e._handle(rec(f"{script}-fail", T0, script=script, user=user))
    check("压着了", (script, user) in e._pending)
    check("压着时取了一次证", captures[f"{script}-fail"], 1)
    e._handle(rec(f"{script}-ok", T0 + timedelta(hours=1), ok=True, script=script, user=user))
    check("压着的那条报出去了", (script, user) in e._pending, False)
    check("报的时候没再往它的证据夹里取证（还是 1 次）", captures[f"{script}-fail"], 1)

    print(f"\n[{script}：停一切前压着的失败 → 照报，不再取证]")
    captures.clear()
    e = build()
    held = rec(f"{script}-fail2", T0, script=script, user=user)
    e._handle(held)
    manualstops._push_before_stop(e, held, "06:30 停一切")
    check("停一切那条报出去了", bool(e.notifier.sent))
    check("报的时候没再取证（还是 1 次）", captures[f"{script}-fail2"], 1)

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项：{fails}"))
sys.exit(1 if fails else 0)
