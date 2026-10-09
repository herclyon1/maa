"""E2 of the deploy: machinecheck_wait.py decides boot-judged-and-quiet / alarm / wait.

The gate reads the two files the relay keeps - state/machinecheck.json and
state/alerts/<day>.jsonl - and answers whether this deploy's version has had
its boot batch judged and whether the group was quiet since. These checks pin
the three verdicts on realistic rows, including the traps: an old version's row
must not count, a non-boot event is not the boot batch, and an alarm wins over
a judged boot.
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "scripts" / "windows"))
from machinecheck_wait import alerts_with_version, boot_judged, main, read_rows, verdict  # noqa: E402

from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def mc_row(**kw):
    base = {"status": "PASS", "evidence": "x", "at": "2026-10-06 06:20:00",
            "version": "", "event": "", "passes": 1}
    base.update(kw)
    return base


def alert_row(**kw):
    base = {"ts": "2026-10-06 06:20:00", "game": "鸣潮", "title": "t",
            "text": "x", "version": "", "evidence_run": ""}
    base.update(kw)
    return base


d = tmpdir()

print("[an empty state dir waits]")
check("read_rows on a missing file is {}", read_rows(str(d), "missing.json"), {})
check("no boot row", boot_judged(str(d), "v1"), False)
check("no alarms", alerts_with_version(str(d), "v1"), [])
check("verdict wait", verdict(str(d), "v1"), ("wait", []))

print("[a boot row of this version means the batch judged]")
(d / "machinecheck.json").write_text(json.dumps({"#63": mc_row(version="v1", event="boot")},
                                                ensure_ascii=False), encoding="utf-8")
check("boot judged", boot_judged(str(d), "v1"), True)
check("verdict boot", verdict(str(d), "v1"), ("boot", []))
check("an older version's row does not count", boot_judged(str(d), "v0"), False)

print("[a non-boot event is not the boot batch]")
(d / "machinecheck.json").write_text(json.dumps({"#21": mc_row(version="v1", event="unresolved")},
                                                ensure_ascii=False), encoding="utf-8")
check("unresolved row is not boot", boot_judged(str(d), "v1"), False)
check("so it still waits", verdict(str(d), "v1"), ("wait", []))

print("[a group push of this version is an alarm, and beats a judged boot]")
(d / "machinecheck.json").write_text(json.dumps({"#63": mc_row(version="v1", event="boot")},
                                                ensure_ascii=False), encoding="utf-8")
ad = d / "alerts"
ad.mkdir()
(ad / "20261006.jsonl").write_text(
    json.dumps(alert_row(version="v1", title="上机核对 #2 没过"), ensure_ascii=False) + "\n",
    encoding="utf-8")
st, alarms = verdict(str(d), "v1")
check("alarm wins over a judged boot", st, "alarm")
check("the push is listed", [a["title"] for a in alarms], ["上机核对 #2 没过"])

print("[an older version's push does not alarm this deploy]")
(ad / "20261006.jsonl").write_text(
    json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n",
    encoding="utf-8")
check("old version is quiet, boot still judged", verdict(str(d), "v1"), ("boot", []))

print("[a malformed alerts line is skipped, a good one read]")
(ad / "20261006.jsonl").write_text(
    "not json\n" + json.dumps(alert_row(version="v1", title="good"), ensure_ascii=False) + "\n",
    encoding="utf-8")
check("one good row survives the junk",
      [a["title"] for a in alerts_with_version(str(d), "v1")], ["good"])



def run_main(state_dir, version):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = main([state_dir, version, "0"])
    return rc, out.getvalue()


print("[a torn last line (a push being appended) is not read as quiet]")
(ad / "20261006.jsonl").write_text(
    json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n"
    + '{"ts": "2026-10-06 06:21:00", "game": "鸣潮", "ti', encoding="utf-8")
check("boot judged but the alerts are torn: wait", verdict(str(d), "v1"), ("wait", []))
rc, out = run_main(str(d), "v1")
check("main does not print MCWAIT_OK", "MCWAIT_OK" in out, False)
check("main exits 2 at the timeout (torn line)", rc, 2)
check("the timeout line names the file", "20261006.jsonl" in out, True)
(ad / "20261006.jsonl").write_text(
    json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n"
    + json.dumps(alert_row(version="v1", title="torn one"), ensure_ascii=False) + "\n",
    encoding="utf-8")
check("once the line is whole the next poll sees the alarm", verdict(str(d), "v1")[0], "alarm")

print("[an unreadable alerts file is not read as quiet]")
(ad / "20261006.jsonl").write_text(
    json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n", encoding="utf-8")
check("readable and quiet: boot", verdict(str(d), "v1"), ("boot", []))
os.chmod(ad / "20261006.jsonl", 0)
try:
    check("unreadable: wait", verdict(str(d), "v1"), ("wait", []))
    rc, out = run_main(str(d), "v1")
    check("main exits 2 at the timeout (unreadable file)", rc, 2)
    check("the timeout line says it could not read the file", "20261006.jsonl" in out, True)
finally:
    os.chmod(ad / "20261006.jsonl", 0o644)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
