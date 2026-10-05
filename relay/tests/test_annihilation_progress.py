"""Annihilation is done for the week only when MAA's own progress line says so.

Audit 2026-10-05 (B/D, collector_maa.py:146-149): a log with no
「剿灭模式 N / M」 line was marked annihilation_done=True whenever no sanity was
spent, and handle.py then closed annihilation for the whole week. The real
counter-example is tests/fixtures/ledger-2026-09-14/ledger.jsonl lines 1-3: the
pass never started (sanity 17, the stage needs 25), spent nothing, and every one
of the three records carries annihilation_done=True.

Positive case: the real 2026-09-07 log, which fights to 1800 / 1800.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay import collector_maa, core
from ark_relay.config import SERVER_TZ

HERE = Path(__file__).parent
REAL = HERE / "replay" / "2026-09-07" / "arknights" / "MAA-05-00-00.log"
LEDGER = HERE / "fixtures" / "ledger-2026-09-14" / "ledger.jsonl"

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


lines = REAL.read_text(encoding="utf-8").splitlines(keepends=True)

with tmpdir() as d:
    d = Path(d)
    print("[real 09-07 log: fought to 1800 / 1800]")
    full = collector_maa.parse_maa_log(REAL)
    check("done", full.get("annihilation_done"), True)
    check("progress", full.get("annihilation_progress"), [1800, 1800])
    check("no unread marker", "annihilation_progress_unread" in full, False)

    print("[same log cut after 1480 / 1800: not done]")
    cut = next(i for i, l in enumerate(lines) if "剿灭模式 : 1480 / 1800" in l)
    p = d / "cut.log"
    p.write_text("".join(lines[:cut + 1]), encoding="utf-8")
    r = collector_maa.parse_maa_log(p)
    check("done", r.get("annihilation_done"), False)
    check("progress", r.get("annihilation_progress"), [1480, 1800])

    print("[pass that never started: no progress line, nothing spent (09-14 shape)]")
    # The 09-07 log up to 「开始任务: 剿灭作战」, then the real 2026-09-14 09:02
    # lines quoted in outcome.py: sanity 17 read, stage costs 25, 0 fights.
    start = next(i for i, l in enumerate(lines) if "开始任务: 剿灭作战" in l)
    short = ("[2026-09-14 09:02:20.100][INF] asst::FightTimesTaskPlugin::analyze_sanity_remain "
             "Current Sanity: 17 , Max Sanity: 210\n"
             '[2026-09-14 09:02:20.101][INF] SubTaskExtraInfo {"class":"asst::FightTimesTaskPlugin",'
             '"details":{"sanity_cost":25,"series":1,"times_finished":0}\n'
             "[2026-09-14 09:02:21.000][INF][TaskQueueViewModel]     <2> 任务出错: 剿灭作战\n")
    p = d / "short.log"
    p.write_text("".join(lines[:start + 1]) + short, encoding="utf-8")
    r = collector_maa.parse_maa_log(p)
    check("is annihilation", r.get("annihilation"), True)
    check("nothing spent", r.get("sanity_spent"), None)
    check("NOT done", r.get("annihilation_done"), False)
    check("unread marker", r.get("annihilation_progress_unread"), True)
    # handle.py:513 closes the week on exactly this condition.
    check("weekly gate would not close",
          bool(r.get("annihilation") and r.get("annihilation_done")), False)

    print("[annihilation line but nothing after it: still not done]")
    p = d / "bare.log"
    p.write_text("".join(lines[:start + 1]), encoding="utf-8")
    check("done", collector_maa.parse_maa_log(p).get("annihilation_done"), False)

print("[the 09-14 ledger lines 1-3 are the shape that used to be marked done]")
old = [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines()[:3]]
check("all three: sanity short and no progress",
      all(e["raw"].get("maa_sanity_short") == {"have": 17, "cost": 25}
          and not e["raw"].get("annihilation_progress") for e in old), True)
check("all three were marked done before this fix",
      [e["raw"].get("annihilation_done") for e in old], [True, True, True])


def ent(raw):
    st = datetime(2026, 10, 5, 9, 0, tzinfo=SERVER_TZ)
    return {"run_id": "2026-10-05/arknights/MAA-05-00-00", "script": "MAA", "user": "u",
            "ok": True, "started": st.isoformat(),
            "finished": (st + timedelta(minutes=2)).isoformat(),
            "duration_known": True, "transitional": False, "failed_tasks": [],
            "raw": raw, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}


print("[day's record]")
_, body = core.format_daily("2026-10-05", [ent({"annihilation": True, "annihilation_done": False,
                                               "annihilation_progress_unread": True})])
check("unread says not counted", "剿灭进度没读到，不算完成" in body, True)
check("unread does not say fought", "已打剿灭" in body, False)
_, body = core.format_daily("2026-10-05", [ent({"annihilation": True, "annihilation_done": True,
                                               "annihilation_progress": [1800, 1800]})])
check("full progress still says capped", "本周剿灭已打满（1800/1800）" in body, True)
_, body = core.format_daily("2026-10-05", [ent({"annihilation": True, "annihilation_done": False,
                                               "annihilation_progress": [1480, 1800]})])
check("partial progress still warns", "剿灭只打到 1480/1800" in body, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
