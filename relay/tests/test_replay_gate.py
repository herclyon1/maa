"""Deploy gate E1: the offline replay of outcome / errwatch over the real 2026-10-06 logs.

Before a deploy, ``scripts/mac/deploy-relay.sh`` runs ``ark_relay.replay`` over
the two checked-in fixtures - the OK-WW weekly-boss run whose update note once
matched 「结晶波片不足」, and the relay.log fragment holding the banner calendar
#2 and shutdown snapshot false alarms. This test pins what the replay must see:
the current code pushes nothing, the pre-fix code pushes exactly the false
alarms, and a genuine ERROR still pushes.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ark_relay import outcome  # noqa: E402
from ark_relay import replay  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
OKWW = (FIX / "okww-1006-run.log").read_text(encoding="utf-8")
RELAY = (FIX / "relay-1006-false-alarms.log").read_text(encoding="utf-8")

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


print("[OK-WW: the update note once matched 「结晶波片不足」]")
check("this code pushes nothing", replay.okww_pushes(OKWW), [])

orig = outcome._task_lines
outcome._task_lines = lambda t: t  # pre-fix reading: every line, update note included
try:
    old = replay.okww_pushes(OKWW)
    check("pre-fix code pushes exactly one", len(old), 1)
    check("it is the waveplate-shortage false alarm", "结晶波片不足" in (old[0] if old else ""), True)
finally:
    outcome._task_lines = orig

print("[relay.log: the banner calendar #2 and shutdown snapshot false alarms]")
check("this code pushes nothing", replay.errwatch_pushes(RELAY), [])
check("pre-fix code pushes the five false alarms",
      [p["where"] for p in replay.errwatch_pushes(RELAY, quiet=())],
      ["ark.banners", "ark.banners", "ark.phone_banners", "ark.snapshot", "ark.snapshot"])

print("[a genuine ERROR still pushes; INFO / diag / traceback lines do not]")
check("a real ERROR line pushes",
      replay.errwatch_pushes("10-06 06:20:17 ERROR   ark.engine  采集超时：残象聚落"),
      [{"where": "ark.engine", "line": "采集超时：残象聚落", "lineno": 1}])
check("INFO and bare diag / traceback lines are skipped",
      replay.errwatch_pushes('10-06 06:20:17 INFO    ark.machinecheck  ok\ndiag: x\n  File "x"\nTraceback (most recent call last):\n'),
      [])

print("[the deploy script's entry point over both fixtures]")
check("main exits 0, deploy may proceed",
      replay.main([str(FIX / "okww-1006-run.log"), str(FIX / "relay-1006-false-alarms.log")]), 0)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
