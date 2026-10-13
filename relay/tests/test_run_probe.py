"""run-probe.py (watch-run.sh's probe on the game machine): a MaaEnd update install is UPD, not FAIL.

Run over the real records of 2026-10-06..13, 6 of 38 came out `ok=0` with
「[更新] Success!」 (10-13 MaaEnd-05-59-12 among them), so watch-run.sh printed a FAIL
for every MaaEnd update the relay itself logs as 「不算一趟运行」 (collector.py
_judge_result). The records here are real results (10-13 05-59-12 and MAA-05-00-23,
10-10 05-13-19, 10-08 05-29-15), gathered under one day folder, copied from
the machine's AUTO-MAS history (fixtures/automas-runprobe/).
"""
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "automas-runprobe"
spec = importlib.util.spec_from_file_location("run_probe", ROOT / "scripts" / "windows" / "run-probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def lines(day):
    probe.HISTORY = str(FIX)
    out = io.StringIO()
    sys.argv = ["run-probe.py", day]
    with contextlib.redirect_stdout(out):
        probe.main()
    rows = {}
    for ln in out.getvalue().splitlines():
        tag, stem, kind, ok, res = ln.split("|", 4)
        rows[stem] = (tag, kind, ok, json.loads(res))
    return rows


rows = lines("2026-10-13")
print("[the 10-13 MaaEnd update record]")
check("UPD, ok 1, not a FAIL", rows.get("MaaEnd-05-59-12"), ("UPD", "MaaEnd", "1", "[更新] Success!"))
print("[real runs are judged as before]")
check("MaaEnd Success!: REC ok", rows.get("MaaEnd-05-13-19"), ("REC", "MaaEnd", "1", "Success!"))
check("MaaEnd partial failure: REC fail", rows.get("MaaEnd-05-29-15", ("",) * 4)[:3], ("REC", "MaaEnd", "0"))
check("MAA Success!: REC ok", rows.get("MAA-05-00-23", ("",) * 4)[:3], ("REC", "MAA", "1"))
print("[the same rule as the relay's collector]")
check("「[更新] 跳过更新」 is not a run either", probe.judge("MaaEnd", "[更新] 跳过更新"), ("UPD", "1"))
check("a failed update is a failed record", probe.judge("MaaEnd", "[更新] MaaEnd 更新失败，已停止后续任务: x"), ("REC", "0"))
check("a stage-labelled success is a success", probe.judge("MaaEnd", "[日常] Success!"), ("REC", "1"))
check("an unknown label is a failure (as collector._split_stage)", probe.judge("MaaEnd", "[新阶段] Success!"), ("REC", "0"))
sys.path.insert(0, str(ROOT / "relay"))
from ark_relay.core import collector  # noqa: E402
check("the labels match collector.py", (probe.STAGE_LABELS, probe.UPDATE_LABEL, probe.UPDATE_FINE),
      (collector._STAGE_LABELS, collector._UPDATE_LABEL, collector._UPDATE_FINE))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
