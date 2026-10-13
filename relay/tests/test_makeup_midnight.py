"""A MAA round that crossed midnight sits on two ledger files; the make-up reads both.

Real records (state/ledger-2026-10-02.jsonl and -03.jsonl, copied into
tests/fixtures/ledger-midnight-*.jsonl): the evening retry chain ran 23:40 -> 01:35.
`MAA-19-44-16` (23:44:58 -> 00:18:54, 「MAA 部分任务执行失败」, 34 minutes of fighting)
is filed on 10-02; the next attempt `MAA-20-18-59` (00:19:45) on 10-03. With that
attempt's failure set to a login failure, maa_work_done read only 10-03 and said
「never got going」 - a whole re-run, a second round of potions (audit s16 #1).
on_record likewise tied only 10-03's failures to a successful make-up.
"""
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR=str(TMP / "AUTO-MAS"),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.core.config import RunRecord   # noqa: E402
from ark_relay.core.ledger import State                   # noqa: E402
from ark_relay.features.makeup import makeup              # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class Eng:
    def __init__(self, days=("2026-10-02", "2026-10-03")):
        d = tmpdir()
        for day in days:
            shutil.copy(FX / f"ledger-midnight-{day}.jsonl", d / f"ledger-{day}.jsonl")
        self.state = State(d)
        self.cfg = type("C", (), {"state_dir": d})()


makeup._machinecheck = lambda eng, ev: None


def at(s):
    return datetime.fromisoformat(s)


def rec(run_id, started, finished, ok, failed):
    return RunRecord(run_id=run_id, script="MAA", user="arknights", started=at(started),
                     finished=at(finished), ok=ok, failed_tasks=failed, raw={})


print("\n[跨午夜那一轮：昨天那份账本里打过仗的那次也算，不再整个补跑]")
e = Eng()
held = rec("2026-10-02/arknights/MAA-20-18-59", "2026-10-03T00:19:45+08:00",
           "2026-10-03T00:19:46+08:00", False, ["MAA 未能正确登录 PRTS"])
why = makeup.maa_work_done(e, held)
check("23:44 那次打了 34 分钟 → 不补", bool(why), True)
morning = rec("2026-10-03/arknights/MAA-05-00-02", "2026-10-03T09:00:50+08:00",
              "2026-10-03T09:01:20+08:00", False, ["MAA 未能正确登录 PRTS"])
check("早上 9 点那一轮跟昨晚隔了好几个小时 → 照样补",
      makeup.maa_work_done(Eng(days=("2026-10-02",)), morning), "")

print("\n[补跑走通：昨天那份里同一轮的失败也记上补跑做成，前面走通的那轮不动]")
e = Eng()
since = at("2026-10-03T01:40:00+08:00")
makeup._write_marker(e.cfg.state_dir, "2026-10-03", {"MAA": {
    "dispatched_at": since.isoformat(), "result": makeup.DISPATCHED, "tries": 1}})
mk = rec("2026-10-03/arknights/MAA-makeup", "2026-10-03T01:41:00+08:00",
         "2026-10-03T02:00:00+08:00", True, [])
makeup.on_record(e, mk)
y = {x["run_id"]: x for x in e.state.read_ledger("2026-10-02")}
t = {x["run_id"]: x for x in e.state.read_ledger("2026-10-03")}


def tied(rows):
    return [k for k, v in rows.items() if (v.get("raw") or {}).get("makeup_ok")]


check("今天那 4 次都记上", len(tied(t)), 4)
check("昨天 23:40 起那 6 次都记上", len(tied(y)), 6)
check("昨天 21:30 走通那次不动", bool((y["2026-10-02/arknights/MAA-17-30-03"].get("raw") or {}).get("makeup_ok")), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
