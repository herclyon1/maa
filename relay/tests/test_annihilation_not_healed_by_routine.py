"""A Routine success does not heal an Annihilation failure; a locked 代理指挥 is named.

2026-10-26 Beijing: AUTO-MAS ran MAA in its Annihilation mode three times (09:00:57,
09:02:41, 09:04:5x), each stopped ten seconds into the fight at MAA's
Annihilation@UnableToAgent2 (the new map 灰石剧场, 代理指挥 locked; 每周报酬 0/1800),
then ran the Routine mode, which went through at 09:24. The relay read the Routine
success as AUTO-MAS's retry of the held failure: relay.log 09:24:51 「↩️ MAA 重试后成功，
改为自愈通知」 and 「自己好了，只进日报」; the daily line said 「09:07 补跑成功」. The
week's annihilation was never done and the group never heard of it - against the
user's rule that only what recovered by itself stays out of the group (relay/USER-SWITCHES.txt,
handle._flush_pending). Pinned here:

* a Routine success leaves a held Annihilation failure held, and it reaches the group;
* an Annihilation success still heals a held Annihilation failure (only the daily report);
* the asst.log line Annihilation@UnableToAgent marks the record, and the alarm and the
  daily row say 代理指挥 is locked (texts.ANNIHILATION_NO_PROXY);
* the daily report no longer calls the Routine run a 「补跑成功」 of the annihilation.
"""
import json
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

from ark_relay.features.alarm import handle  # noqa: E402
from ark_relay.features.alarm import records  # noqa: E402
from ark_relay.features.verify import outcome  # noqa: E402
from ark_relay.features.makeup import makeup  # noqa: E402
from ark_relay.core import texts  # noqa: E402
from ark_relay.core import engine as eng_mod  # noqa: E402
from ark_relay.core import ledger_report  # noqa: E402
from ark_relay.core.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core.ledger import State  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def automas_dir() -> Path:
    root = tmpdir()
    (root / "config").mkdir()
    sc = {"instances": [{"uid": "s-MAA"}], "s-MAA": {"Info": {"Name": "MAA", "Path": r"D:\ark\MAA"}}}
    qc = {"instances": [{"uid": "q0"}], "q0": {
        "Info": {"Name": "早班", "TimeEnabled": True},
        "SubConfigsInfo": {"TimeSet": {"instances": [], "t0": {"Info": {"Enabled": True, "Time": "09:00"}}},
                           "QueueItem": {"instances": [], "i0": {"Info": {"ScriptId": "s-MAA"}}}}}}
    (root / "config" / "ScriptConfig.json").write_text(json.dumps(sc), encoding="utf-8")
    (root / "config" / "QueueConfig.json").write_text(json.dumps(qc), encoding="utf-8")
    return root


AUTOMAS = automas_dir()
DAY = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)


def at(hh, mm=0, ss=0):
    return DAY.replace(hour=hh, minute=mm, second=ss)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return []

    def went_to_group(self):
        return True


class Src:
    def fetch(self, seen):
        return []


def build():
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.automas_dir = AUTOMAS
    cfg.maa_dir = None
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._unfinished_queues = lambda now, entries: []
    e._deferred_update_busy = lambda: False
    e._verify_outcome = lambda r: None
    e._archive_maaend_evidence = lambda r: None
    e._maintenance_today = lambda game: False
    return e


def rec(started, minutes, ok, annihilation, failed=None):
    raw = {"annihilation": True, "fight_count": 0} if annihilation else {}
    if annihilation and ok:   # what collector_maa reads off a full annihilation week
        raw.update(fight_count=1, annihilation_progress=[1800, 1800], annihilation_done=True)
    return RunRecord(run_id=f"{started:%Y-%m-%d}/arknights/MAA-{started:%H-%M-%S}", script="MAA", user="arknights",
                     started=started, finished=started + timedelta(minutes=minutes), ok=ok,
                     failed_tasks=[] if ok else list(failed or ["剿灭作战"]), raw=dict(raw))


def alarms(e):
    return [(t, b) for t, b, a in e.notifier.sent if a]


handle._ship_evidence = lambda eng, r: ""
handle._weekly_gates = lambda eng, r: None

# What MAA's asst.log said at the first attempt's stop (2026-10-26 09:02:39), trimmed.
LOCKED_LOG = ("[2026-10-26 09:02:38.378][INF] Start Task Chain: StartUp\n"
              "[2026-10-26 09:02:39.816][TRC] asst::PipelineAnalyzer::analyze | MatchTemplate Annihilation@UnableToAgent2\n"
              "[2026-10-26 09:02:40.343][INF] Assistant::append_callback | TaskChainError {\"taskchain\":\"Fight\"}\n")

print("[the asst.log line marks a locked 代理指挥]")
check("Annihilation@UnableToAgent2 is a locked proxy", outcome.maa_annihilation_no_proxy(LOCKED_LOG))
check("a plain fight failure is not", outcome.maa_annihilation_no_proxy("TaskChainError {\"taskchain\":\"Fight\"}"), False)

print("\n[three Annihilation failures, then a Routine success: not healed, the group hears it]")
e = build()
handle._maa_app_log = lambda maa_dir, started, until=None: LOCKED_LOG
fails_in = [rec(at(9, 0, 57), 2, False, True), rec(at(9, 2, 41), 2, False, True), rec(at(9, 4, 51), 2, False, True)]
for r in fails_in:
    handle._handle(e, r)
check("the last Annihilation failure is held", (e._pending.get(("MAA", "arknights")) or fails_in[0]).run_id,
      fails_in[-1].run_id)
check("…marked as a locked proxy", bool((e._pending[("MAA", "arknights")].raw or {}).get("annihilation_no_proxy")))
handle._maa_app_log = lambda maa_dir, started, until=None: ""
routine = rec(at(9, 6, 56), 17, True, False)
handle._handle(e, routine)
check("the Routine success left it held (not moved to recovered)",
      (("MAA", "arknights") in e._pending, ("MAA", "arknights") in e._recovered), (True, False))
check("…and the ledger's later success skips the Routine run", records._later_success(e, fails_in[-1]), "")
e._flush_pending()
makeup.maybe_run(e, at(9, 30))
e._flush_pending()
got = alarms(e)
check("one alarm reached the group", len(got), 1)
check("…counting the three Annihilation tries, not the Routine round", any("重试 3 次" in b for _, b in got))
check("…it says 代理指挥 is locked", any(texts.ANNIHILATION_NO_PROXY in b for _, b in got))
check("…nothing held afterwards", ("MAA", "arknights") in e._pending, False)

print("\n[the daily report: no 「补跑成功」 for the Routine run, the reason is the locked proxy]")
entries = e.state.read_ledger(f"{DAY:%Y-%m-%d}")
groups = ledger_report._bare_failure_groups(entries, [x for x in entries if not x["ok"]], [("早班", "09:00")])
line = ledger_report._bare_line(next(iter(groups.values())))
check("the row names the locked proxy", texts.ANNIHILATION_NO_PROXY in line)
check("…and no make-up success", "补跑成功" in line, False)

print("\n[an Annihilation success still heals a held Annihilation failure]")
e = build()
handle._maa_app_log = lambda maa_dir, started, until=None: ""
first = rec(at(9, 0, 57), 2, False, True)
handle._handle(e, first)
handle._handle(e, rec(at(9, 3, 0), 15, True, True))
check("moved to recovered", (("MAA", "arknights") in e._pending, ("MAA", "arknights") in e._recovered), (False, True))
e._flush_pending()
check("no failure alarm", [t for t, _ in alarms(e) if "没跑成" in t], [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
