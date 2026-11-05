"""A script that timed out and was retried by AUTO-MAS restarts the shift's clock (ledger #138).

2026-11-05 09:00 早班: MAA's first attempt hung at StartUp (asst.log: 609 clicks of 开始唤醒) until
AUTO-MAS's timeout at 09:48 and a retry, which then passed StartUp at 09:51 and finished at 10:08.
MaaEnd started only at 10:22, and at 10:57 both runwatch's overrun alarm and shutdown's no-result
alarm counted 87 + 30 minutes from 09:00 - on top of the timeout alarm already pushed for MAA.

Checked here: runwatch.retry_clock reads the 「超时|<script>|<HH:MM:SS>」 marks check_timeouts leaves;
only a timeout between the shift's time and its planned end counts; the latest one wins; the
no-result clock (shutdown._overdue_from) and the overrun deadline (runwatch.overrun_moments) both
start from it; without a retry everything is as before, texts included.
"""
import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import texts  # noqa: E402
from ark_relay.core.config import SERVER_TZ  # noqa: E402
from ark_relay.features.run import runwatch  # noqa: E402
from ark_relay.features.shutdown import shutdown  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


class Store:
    def __init__(self, marks):
        self.marks = marks

    def get(self, ns, key):
        return self.marks.get(key) if ns == "marks" else None


def eng_with(marks):
    return types.SimpleNamespace(state=types.SimpleNamespace(store=Store(marks)))


def t(h, m, s=0, day=5):
    return datetime(2026, 11, day, h, m, s, tzinfo=SERVER_TZ)


due = t(9, 0)
LIMIT = 87          # 「近 7 天最长 87 分钟跑完」 in the 10:57 alarm
DAY = "alerted:2026-11-05"

print("[retry_clock]")
check("no marks: nothing restarts the clock", runwatch.retry_clock(eng_with({}), due, LIMIT), None)
check("no state at all (bare engine): None", runwatch.retry_clock(types.SimpleNamespace(), due, LIMIT), None)
e = eng_with({DAY: ["超时|MAA|09:48:12", "队列超时|早班|09:00"]})
check("MAA timed out at 09:48 and was retried: from 09:48", runwatch.retry_clock(e, due, LIMIT), t(9, 48, 12))
e = eng_with({DAY: ["超时|MAA|09:48:12", "超时|MAA|10:30:00"]})
check("two timeouts in the run: the later one", runwatch.retry_clock(e, due, LIMIT), t(10, 30))
e = eng_with({DAY: ["超时|MAA|08:59:59"]})
check("a timeout before the shift's time does not count", runwatch.retry_clock(e, due, LIMIT), None)
e = eng_with({DAY: ["超时|MaaEnd|10:57:01"]})
check("a timeout after the planned end (10:57) moves nothing", runwatch.retry_clock(e, due, LIMIT), None)
e = eng_with({DAY: ["超时|MAA|bad", "nonsense"]})
check("malformed marks are skipped", runwatch.retry_clock(e, due, LIMIT), None)
eve = t(21, 20)
e = eng_with({DAY: [], "alerted:2026-11-06": ["超时|OK-WW|00:10:00"]})
check("an evening shift's timeout after midnight is read from the next day",
      runwatch.retry_clock(e, eve, 180), t(0, 10, 0, day=6))

print("[shutdown._overdue_from: the no-result clock]")
e = eng_with({DAY: ["超时|MAA|09:48:12"]})
check("without the limit: the queue's time, as before", shutdown._overdue_from(e, due, ["MaaEnd"]), due)
check("with the limit: from the retry", shutdown._overdue_from(e, due, ["MaaEnd"], LIMIT), t(9, 48, 12))
e._gu_rerun_at, e._gu_reran = t(12, 2, 15), {"MaaEnd"}
check("a later update re-run still wins", shutdown._overdue_from(e, due, ["MaaEnd"], LIMIT), t(12, 2, 15))
e._gu_rerun_at = t(9, 30)
check("an earlier update re-run loses to the later retry", shutdown._overdue_from(e, due, ["MaaEnd"], LIMIT), t(9, 48, 12))
deadline = shutdown._overdue_from(eng_with({DAY: ["超时|MAA|09:48:12"]}), due, ["MaaEnd"], LIMIT) \
    + timedelta(minutes=LIMIT + runwatch.OVERRUN_SLACK_MIN)
check("the 11-05 case: no alarm at 10:57", t(10, 57) < deadline, True)
check("a MaaEnd that hangs after the retry is still caught (11:45)", deadline, t(11, 45, 12))

print("[runwatch.overrun_moments: the overrun deadline]")
auto = TMP / "automas"
(auto / "config").mkdir(parents=True)
doc = {"instances": [{"uid": "q1", "type": "QueueConfig"}],
       "q1": {"Info": {"Name": "早班", "TimeEnabled": True},
              "SubConfigsInfo": {"TimeSet": {"0": {"Info": {"Enabled": True, "Time": "09:00"}}},
                                 "QueueItem": {"0": {"Info": {"ScriptId": "s0"}}}}}}
(auto / "config" / "QueueConfig.json").write_text(json.dumps(doc), encoding="utf-8")
with mock.patch.object(runwatch, "planned_minutes", lambda *a: (LIMIT, 7)):
    for label, marks, want in (("no retry: 09:00 + 87 + 30", {}, t(10, 57)),
                               ("MAA retried at 09:48: 09:48 + 87 + 30", {DAY: ["超时|MAA|09:48:12"]}, t(11, 45, 12))):
        stub = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=auto), state=types.SimpleNamespace(store=Store(marks)))
        got = [dl for _, hhmm, _, d, _, dl, _ in runwatch.overrun_moments(stub, t(10, 57)) if hhmm == "09:00"]
        check(label, got, [want])

print("[texts: what the alarm says]")
old = texts.shift_no_result_body("早班", due, t(11, 50), "MaaEnd", LIMIT, 30, 7)
check("no retry: the no-result text has no restart clause", "重新算" in old, False)
new = texts.shift_no_result_body("早班", due, t(11, 50), "MaaEnd", LIMIT, 30, 7, restarted=t(9, 48, 12))
check("after a retry it says when the clock restarted", "AUTO-MAS 09:48 重试，从那时重新算" in new, True)
ov = texts.shift_overrun_body("早班", due, t(11, 50), LIMIT, 30, "", "", 7, restarted=t(9, 48, 12))
check("the overrun text ends at the restarted deadline", "该在 11:45 前结束" in ov, True)
ov0 = texts.shift_overrun_body("早班", due, t(11, 50), LIMIT, 30, "", "", 7)
check("without a retry the overrun deadline is 10:57 as before", "该在 10:57 前结束" in ov0 and "重新算" not in ov0, True)

print("all checks passed" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
