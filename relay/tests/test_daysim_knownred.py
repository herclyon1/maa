"""The day gate's known-red list (tests/daysim/knownred.py, known-red.json) and its self-check patch.

What is pinned here:
- a failure line the day's entry lists is known red; any other line is new red, and
  the budget line and invariant 5 (sim errors) are never excused;
- the list shrinks to empty: an entry that matches fewer or more lines than its
  `count` is stale, one past `expires` (at most 7 days after `added`) is refused,
  one whose report has no open todo `- [ ] **<bug>:` is refused (a closed report =
  a fixed bug), as is an unknown field or a bad regex;
- the committed known-red.json loads today, every entry names an open docs/BACKLOG.md
  todo, and each committed day's list of known lines is what the replay produced on
  2026-10-13 19:27 (run.py --all: 10-12 / 10-13 two Server酱 「⚙️ 配置已更新」 receipts
  each); 10-06's two #59 pushes (daysim-R1, fixed 2026-10-13) are no longer excused;
- badfix/R36.patch names one day and the lines that must go red, and still applies
  to the code (git apply --check on a copy of shutdown.py).
"""
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "daysim"))
sys.path.insert(0, str(HERE))
import knownred  # noqa: E402
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


R2 = "^strict: no entry expects push serverchan \\S+ '⚙️ 配置已更新："
LINE_A = "strict: no entry expects push serverchan 2026-10-13T11:24:31+08:00 '⚙️ 配置已更新：调试模式'"
LINE_B = "strict: no entry expects push serverchan 2026-10-13T11:53:07+08:00 '⚙️ 配置已更新：空（安全状态）'"
R36 = ("1013-12 must_not, happened: kind='power' window=['11:05', '11:58']")


def entry(**f):
    e = {"day": "2026-10-13", "bug": "daysim-R2", "report": "docs/BACKLOG.md", "added": "2026-10-13",
         "expires": "2026-10-20", "count": 2, "excuses": [R2], "why": "a reason"}
    e.update(f)
    return e


print("[split: known lines, new lines, stale entries]")
sp = knownred.split("2026-10-13", [LINE_A, LINE_B], [entry()])
check("both listed lines are known red, nothing new", (len(sp.known), sp.new, sp.stale, sp.ok), (2, [], [], True))
sp = knownred.split("2026-10-13", [LINE_A, LINE_B, R36], [entry()])
check("an unlisted line on the same day is new red", (sp.new, sp.ok), ([R36], False))
sp = knownred.split("2026-10-12", [LINE_A, LINE_B], [entry()])
check("an entry excuses only its own day", (len(sp.new), sp.ok), (2, False))
sp = knownred.split("2026-10-13", [LINE_A], [entry()])
check("one of two lines gone: stale (partly fixed), gate fails", (len(sp.stale), sp.ok), (1, False))
sp = knownred.split("2026-10-13", [], [entry()])
check("bug fixed (no line left): stale, gate fails until the entry goes", (len(sp.stale), sp.ok), (1, False))
sp = knownred.split("2026-10-13", [LINE_A, LINE_B, LINE_A], [entry()])
check("a third line of the same shape: stale (count changed)", (len(sp.stale), sp.ok), (1, False))
sp = knownred.split("2026-10-13", [LINE_A], [entry()], check_stale=False)
check("a partial day (--until) does not judge staleness", sp.ok, True)
for line in ("budget: 200.0 s CPU, cap 180 s", "invariant 5: sim error: {'what': 'unparked'}"):
    sp = knownred.split("2026-10-13", [line], [entry(excuses=[".*"], count=1)])
    check(f"never excused: {line.split(':')[0]}", (sp.new, sp.ok), ([line], False))

print("\n[load: the list cannot grow stale or permanent]")
TODAY = date(2026, 10, 14)
tmp = tmpdir()
repo = tmp / "repo"
(repo / "docs").mkdir(parents=True)
(repo / "docs" / "BACKLOG.md").write_text("## Todo\n- [ ] **daysim-R2: something (added 2026-10-13).**\n"
                                          "- [x] **daysim-R9: fixed.**\n", encoding="utf-8")

def problems(*entries, today=TODAY):
    f = tmp / "kr.json"
    f.write_text(json.dumps({"entries": list(entries)}), encoding="utf-8")
    try:
        knownred.load(f, today=today, repo=repo)
        return []
    except knownred.KnownRedError as exc:
        return exc.args[0]

check("a well-formed entry with an open report loads", problems(entry()), [])
check("expired: refused", len(problems(entry(), today=date(2026, 10, 21))), 1)
check("expires more than 7 days after added: refused", len(problems(entry(expires="2026-10-21"))), 1)
check("report closed ([x]): refused", len(problems(entry(bug="daysim-R9"))), 1)
check("bug not in the report: refused", len(problems(entry(bug="daysim-R7"))), 1)
check("report file missing: refused", len(problems(entry(report="docs/NOPE.md"))), 1)
check("unknown field: refused", len(problems({**entry(), "until": "x"})), 1)
check("bad regex: refused", len(problems(entry(excuses=["("]))), 1)
check("count 0: refused", len(problems(entry(count=0))), 1)

print("\n[the committed list]")
entries = knownred.load()
check("known-red.json loads today", isinstance(entries, list), True)
check("its days and bugs", sorted((e["day"], e["bug"], e["count"]) for e in entries),
      [("2026-10-12", "daysim-R2", 2), ("2026-10-13", "daysim-R2", 2)])
R1_LINES = [   # run.py --all, 2026-10-13 19:27: the #59 pushes daysim-R1 caused, fixed 2026-10-13
    "strict: no entry expects push group 2026-10-06T16:43:29+08:00 '🔬 上机核对没过：#59 "
    "系统的程序启动通知断了又自己订上的，只进日报不进群，并写明是哪种原因'",
    "strict: no entry expects push group 2026-10-06T18:23:23+08:00 '🔬 上机核对没过：#59 "
    "系统的程序启动通知断了又自己订上的，只进日报不进群，并写明是哪种原因'"]
sp = knownred.split("2026-10-06", R1_LINES, entries)
check("2026-10-06: R1's #59 pushes, should they come back, are new red", (sp.new, sp.ok), (R1_LINES, False))
check("2026-10-06: a clean day passes", knownred.split("2026-10-06", [], entries).ok, True)
measured = {   # run.py --all, 2026-10-13 19:27 (scratchpad base.txt), the strict lines of each day
    "2026-10-12": ["strict: no entry expects push serverchan 2026-10-12T08:45:38+08:00 '⚙️ 配置已更新：调试模式'",
                   "strict: no entry expects push serverchan 2026-10-12T14:23:11+08:00 '⚙️ 配置已更新：空（安全状态）'"],
    "2026-10-13": [LINE_A, LINE_B],
}
for day, lines in measured.items():
    sp = knownred.split(day, lines, entries)
    check(f"{day}: the measured red is exactly the listed red", (len(sp.known), sp.new, sp.stale), (2, [], []))
    sp = knownred.split(day, [*lines, R36], entries)
    check(f"{day}: R36's power-off on top is new red", sp.new, [R36])

print("\n[badfix/R36.patch]")
patch = HERE / "daysim" / "badfix" / "R36.patch"
text = patch.read_text(encoding="utf-8")
check("one Day: line", [ln for ln in text.splitlines() if ln.startswith("Day: ")], ["Day: 2026-10-13"])
check("Expect: lines name 1013-12 and invariant 2",
      [ln.split()[1] for ln in text.splitlines() if ln.startswith("Expect: ")], ["^1013-12", "^invariant"])
tmp = tmpdir()
src = HERE.parent / "ark_relay" / "features" / "shutdown" / "shutdown.py"
dst = tmp / "relay" / src.relative_to(HERE.parent)
dst.parent.mkdir(parents=True)
shutil.copy2(src, dst)
p = subprocess.run(["git", "apply", "--check", str(patch)], cwd=tmp, capture_output=True, text=True,
                   check=False)
check("the patch still applies to the code", (p.returncode, p.stderr.strip()[:200]), (0, ""))

print()
if fails:
    print(f"FAILED: {len(fails)}: {fails}")
    sys.exit(1)
print("all checks passed")
