"""A malformed ledger line must not be able to keep the machine powered on.

The ledger is line-delimited JSON on a box that is hard power-cut twice a day.
A line can end up valid JSON yet incomplete, and a dozen call sites read these
fields directly - including the deterministic report layout, which is the last
fallback when the wording model is down. A KeyError there means the daily
report is never sent, and the shutdown path waits for a sent report.
"""
import json, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import State, format_daily  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

GOOD = {"run_id": "2026-08-21/arknights/21-30-00", "script": "MAA",
        "user": "arknights", "started": "2026-08-21T21:30:00+08:00",
        "finished": "2026-08-21T22:15:00+08:00", "ok": True,
        "failed_tasks": [], "raw": {"sanity": 6}}

def ledger(*lines):
    d = Path(tempfile.mkdtemp())
    (d / "ledger-2026-08-21.jsonl").write_text("\n".join(lines), encoding="utf-8")
    return State(d)

print("[a good line survives]")
check("kept", len(ledger(json.dumps(GOOD)).read_ledger("2026-08-21")), 1)

print("\n[torn line: valid JSON, missing fields]")
st = ledger(json.dumps(GOOD), json.dumps({"script": "MaaEnd"}))
entries = st.read_ledger("2026-08-21")
check("incomplete one dropped", len(entries), 1)
check("the good one kept", entries[0]["run_id"], GOOD["run_id"])

print("\n[unparseable line]")
check("dropped", len(ledger(json.dumps(GOOD), "{not json").read_ledger("2026-08-21")), 1)

print("\n[a JSON value that is not an object]")
check("dropped", len(ledger(json.dumps(GOOD), "[1,2,3]", '"x"').read_ledger("2026-08-21")), 1)

print("\n[the report still renders - this is the whole point]")
entries = ledger(json.dumps(GOOD), json.dumps({"script": "MaaEnd"})).read_ledger("2026-08-21")
try:
    title, body = format_daily("2026-08-21", entries)
    check("rendered", bool(title and body), True)
    check("mentions the surviving run", "MAA" in body, True)
except Exception as exc:                       # noqa: BLE001
    check(f"rendered (raised {exc!r})", False, True)

print("\n[every entry malformed: still no crash]")
entries = ledger(json.dumps({"script": "MAA"}), "{bad").read_ledger("2026-08-21")
check("nothing survives", entries, [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
