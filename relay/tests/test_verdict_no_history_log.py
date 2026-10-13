"""A run AUTO-MAS booked as 「正常退出」 with no history .log is not verified, not
「everything done」.

Audit 2026-10-13 s8 #4: verdict._verify_outcome returned None (= all done) when
the history log was missing or empty, contradicting its own rule that empty text
is a false green; collector sets log_path None when the .log is absent. The
machine's copied history (10-06..10-13, 38 records + hist.zip) has a .log for
every .json, so no real record shows it yet; the rule follows the code.
"""
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core.config import SERVER_TZ, RunRecord
from ark_relay.features.alarm import verdict

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


START = datetime(2026, 10, 12, 10, 59, 40, tzinfo=SERVER_TZ)
root = tmpdir()
eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=root, maa_dir=None, automas_dir=None,
                                                      state_dir=root))


def rec(script, log_path=None):
    user = {"MAA": "arknights", "MaaEnd": "endfield", "OK-WW": "wuwa"}[script]
    return RunRecord(run_id=f"2026-10-12/{user}/{script}-06-58-38", script=script, user=user,
                     started=START, finished=START + timedelta(minutes=40), ok=True, log_path=log_path)


for script in ("MaaEnd", "OK-WW"):
    print(f"[{script}: no history .log]")
    msg = verdict._verify_outcome(eng, rec(script))
    check("not 「everything done」", msg is not None, True)
    check("says the log is missing", "AUTO-MAS 这一轮的运行日志" in (msg or ""), True)

print("[MaaEnd: an empty history .log]")
empty = root / "MaaEnd-06-58-38.log"
empty.write_text("", encoding="utf-8")
check("not 「everything done」", verdict._verify_outcome(eng, rec("MaaEnd", empty)) is not None, True)

print("[MAA: judged from its own log, the history log is not needed]")
msg = verdict._verify_outcome(eng, rec("MAA")) or ""
check("asks for MAA's own log, not AUTO-MAS's", ("MAA 自己的日志" in msg, "AUTO-MAS 这一轮" in msg), (True, False))

print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")
sys.exit(1 if fails else 0)
