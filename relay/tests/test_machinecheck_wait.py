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

print("[an old file's torn last line (a past crash) is skipped with one note, not waited on]")
(ad / "20261006.jsonl").write_text(
    json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n"
    + '{"ts": "2026-10-03 06:21:00", "game": "鸣潮", "ti', encoding="utf-8")
old = os.stat(ad / "20261006.jsonl").st_mtime - 3 * 86400
os.utime(ad / "20261006.jsonl", (old, old))
notes = io.StringIO()
with contextlib.redirect_stdout(notes):
    first = verdict(str(d), "v1")
    second = verdict(str(d), "v1")
check("boot judged and the torn file is days old: boot", first, ("boot", []))
check("still boot on the next poll", second, ("boot", []))
check("the note names the file", "20261006.jsonl" in notes.getvalue(), True)
check("the note is printed once over two polls", notes.getvalue().count("20261006.jsonl"), 1)
rc, out = run_main(str(d), "v1")
check("main passes over an old torn line", (rc, "MCWAIT_OK" in out), (0, True))

print("[an unreadable alerts file is not read as quiet]")
(ad / "20261006.jsonl").write_text(
    json.dumps(alert_row(version="v0", title="old"), ensure_ascii=False) + "\n", encoding="utf-8")
check("readable and quiet: boot", verdict(str(d), "v1"), ("boot", []))
# chmod 0 makes a file unreadable on POSIX only; on Windows it only sets the read-only
# flag (docs.python.org/3/library/os.html#os.chmod). There a byte-range lock over the
# whole file makes reads of it fail, in this process and in run_main's.
_lock = None
if os.name == "nt":
    import msvcrt
    _lock = open(ad / "20261006.jsonl", "r+b")
    msvcrt.locking(_lock.fileno(), msvcrt.LK_NBLCK, max(1, (ad / "20261006.jsonl").stat().st_size))
else:
    os.chmod(ad / "20261006.jsonl", 0)
try:
    check("unreadable: wait", verdict(str(d), "v1"), ("wait", []))
    rc, out = run_main(str(d), "v1")
    check("main exits 2 at the timeout (unreadable file)", rc, 2)
    check("the timeout line says it could not read the file", "20261006.jsonl" in out, True)
finally:
    if _lock is not None:
        _lock.seek(0)
        msvcrt.locking(_lock.fileno(), msvcrt.LK_UNLCK, max(1, (ad / "20261006.jsonl").stat().st_size))
        _lock.close()
    else:
        os.chmod(ad / "20261006.jsonl", 0o644)

print("[pushes docs/NOTIFICATIONS.md routes `group (report)` are not alarms]")
# The real rows: 10-13 10:00 the 🖼️ 无音区产出 the owner asked for (version 20261012131940;
# the old gate printed MCWAIT_ALARM 1 on it), and 10-12 08:46 a 🩺 中继自己报错了 alarm.
DOC = str(ROOT.parent / "docs" / "NOTIFICATIONS.md")
real = [json.loads(ln) for ln in (ROOT / "tests" / "fixtures" / "alerts-e2-report-push.jsonl")
        .read_text(encoding="utf-8").splitlines() if ln.strip()]
tacet, fault = real
e = tmpdir()
(e / "alerts").mkdir()
(e / "machinecheck.json").write_text(json.dumps({"#63": mc_row(version="20261012131940", event="boot")}),
                                     encoding="utf-8")


def run_doc(state_dir, version, *rows):
    (Path(state_dir) / "alerts" / "20261013.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = main([state_dir, version, "0", DOC])
    return rc, out.getvalue()


rc, out = run_doc(str(e), "20261012131940", tacet)
check("无音区产出 only: exit 0", rc, 0)
check("it is listed as INFO, not ALARM", ("INFO" in out and "无音区产出" in out, "ALARM" in out), (True, False))
banner = dict(tacet, title="🎴 明天开新卡池：鸣潮", text="明天 10:00 开新卡池")
rc, out = run_doc(str(e), "20261012131940", banner)
check("明天开新卡池：<games> (title cut at the placeholder): exit 0", rc, 0)
rc, out = run_doc(str(e), "20261012131940", tacet, dict(fault, version="20261012131940"))
check("a real alarm next to it still fails: exit 1", rc, 1)
check("only the alarm is an ALARM line", (out.count("ALARM 2026"), "MCWAIT_ALARM 1" in out), (1, True))
rc, out = run_doc(str(e), "20261012131940", dict(fault, title="🌙 关机被取消", version="20261012131940"))
check("🌙 关机被取消 is routed `group` in the page, so it counts", rc, 1)

out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = main([str(e), "20261012131940", "0", str(e / "no-such-page.md")])
check("page missing: every group push counts again (exit 1, with a NOTE)",
      (rc, "NOTE" in out.getvalue()), (1, True))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
