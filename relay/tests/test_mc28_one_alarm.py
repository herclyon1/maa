"""MaaEnd stopping itself inside one of the four tasks, with no other run of the day to
make up for it, is one group message, not two.

Review of verify ledger #28 (item 2): the booking pushed 「终末地早班 1 项没证据」 for
装备制造 (pushes._push_unverified) and machine check #28 then pushed
「上机核对没过：#28」 for the same task - one cause, two messages. Now the 「没证据」
alarm carries what MaaEnd's own record shows for the task (it stopped itself after its
scene check, with its own reason), and #28's FAIL is recorded but rides along with it.

Data: the real 2026-10-08 MaaEnd-06-31-06 run (fixtures/maaend-task-trail/: its
AUTO-MAS log and MaaFW's lines of 10-08), booked through handle._handle on a real
Engine with no earlier run that day, so nothing heals the abort.
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
from ark_relay.features.alarm import handle, runchecks      # noqa: E402
from ark_relay.features.selfcheck import machinecheck as mc  # noqa: E402
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


def book(name):
    """Book one fixture run on a fresh Engine; (group sends, state folder)."""
    cfg = Config()
    cfg.state_dir = tmpdir() / "state"
    cfg.state_dir.mkdir()
    end = tmpdir()
    (end / "debug").mkdir()
    (end / "debug" / "maafw.log").write_bytes(gzip.decompress((FIX / "maafw-2026-10-08.log.gz").read_bytes()))
    cfg.maaend_dir = str(end)
    notes = Notes()
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=notes)
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._verify_outcome = lambda r: None
    log = FIX / name
    started = datetime(2026, 10, 8, 10, 32, 8, tzinfo=SERVER_TZ)
    rec = RunRecord(run_id="2026-10-08/endfield/MaaEnd-06-31-06", script="MaaEnd", user="endfield",
                    started=started, finished=started + timedelta(minutes=2, seconds=10), ok=True,
                    failed_tasks=[], raw=collector_maaend.parse_maaend_log(log), log_path=log)
    handle._handle(e, rec)
    return [(t, b) for t, b, alert in notes.sent if alert], cfg.state_dir


print("[10-08 06-31-06 alone that day: 装备制造 aborted by MaaEnd itself, nothing heals it]")
group, state = book("2026-10-08_MaaEnd-06-31-06.log")
for t, b in group:
    print(f"    group: {t} | {b[:160]!r}")
about = [(t, b) for t, b in group if "装备制造" in t + b]
check("one group message about it", len(about), 1)
title, body = about[0] if about else ("", "")
check("…the 「没证据」 alarm", title, texts.unverified_alarm("终末地", "早班", 1))
check("…carrying what MaaEnd's own record shows: it stopped itself, and its reason",
      ("· 装备制造：终末地自己检查画面没过，把后面的任务全停了，这一项没做成" in body, "账号编号显示不全" in body),
      (True, True))
check("…in plain Chinese", texts.plain(title + body), [])
check("no 「上机核对没过：#28」 of its own", [t for t, _ in group if t.startswith(texts.machinecheck_failed("#28", ""))], [])
row = mc.read(state).get("#28") or {}
check("#28's FAIL is on record, saying it went in that alarm",
      (row.get("status"), str(row.get("evidence") or "").endswith("已写在「没证据」那条报警里一起进群")), ("FAIL", True))
check("the daily section shows it as a FAIL", any(x.startswith("❌ #28 ") for x in mc.daily_section(state).splitlines()))
check("the per-record note is dropped after the checks", runchecks._UNVERIFIED, {})

print()
if fails:
    print(f"✗ {len(fails)} 条没过：{fails}")
    sys.exit(1)
print("all checks passed")
