"""Every line of USER-SWITCHES.txt says why what it keeps from the group may stay there.

The user, 2026-10-10 13:35 (Tokyo), quoted in USER-SWITCHES.txt's header: alarms were switched
off while the bugs under them were never fixed, and that has no place in the relay. Until then a line only had to quote him (tests/test_user_switches.py); the WMI drop after a
restart and MaaEnd not exiting were daily-report-only under his 2026-10-06 05:07 rule on
faults that fixed themselves, while neither cause was known and both kept happening.

Each entry now ends in `| verdict: <kind> - <why>`, one of:
  fixed <sha>     the cause was fixed in that commit (it must exist in this repository);
  normal-state    not a fault: the why names what makes it normal. The part before the first
                  ";" (what is kept from the group) may not call the cause unknown;
  task-switch     one of his tasks switched off on his order; the line may not keep a
                  failure from the group.
Every place in the code that keeps a failure from the group must have a line
(test_user_switches.py), so every such place carries one of these verdicts.
"""
import re
import subprocess
import sys
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
LIST = RELAY / "USER-SWITCHES.txt"

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


VERDICT_RE = re.compile(r"\s\|\s+verdict:\s+(?P<kind>fixed|normal-state|task-switch)\b\s*(?P<rest>.*)$")
SHA_RE = re.compile(r"^(?P<sha>[0-9a-f]{7,40})\b")
UNKNOWN = ("not known", "unknown", "unexplained", "nothing explained", "not found", "tbd", "to be checked",
           "不明", "待查", "没查清", "还没查")
KEPT = ("recovered", "daily report only", "daily-report-only", "not pushed", "只进日报", "不进群")


def commit_exists(sha: str) -> bool:
    r = subprocess.run(["git", "-C", str(RELAY), "cat-file", "-e", f"{sha}^{{commit}}"],
                       capture_output=True, timeout=30)
    return r.returncode == 0


def problems(line: str, has_commit=commit_exists) -> list[str]:
    """What is wrong with one entry line's verdict ([] when nothing)."""
    m = VERDICT_RE.search(line)
    if line.count("| verdict:") != 1 or not m:
        return ["no `| verdict: fixed <sha> | normal-state - why | task-switch - why` at its end"]
    kind, rest = m["kind"], m["rest"].lstrip(" -").strip()
    head = line[:m.start()]
    if kind == "fixed":
        s = SHA_RE.match(rest)
        if not s:
            return ["fixed without a commit"]
        if not has_commit(s["sha"]):
            return [f"fixed by {s['sha']}, which is not a commit here"]
        return []
    if len(rest) < 20:
        return [f"{kind} without a why"]
    if kind == "normal-state":
        kept = rest.split(";")[0].lower()
        bad = [w for w in UNKNOWN if w in kept]
        return [f"normal-state while its cause is unknown ({bad[0]})"] if bad else []
    what = head.lower()
    bad = [w for w in KEPT if w in what]
    return [f"task-switch that keeps a failure from the group ({bad[0]})"] if bad else []


print("[the gate itself rejects the known-bad shapes]")
GOOD = "x.py:f | does a thing | 「他的话」 | 2026-10-10 13:35"
check("no verdict", bool(problems(GOOD)), True)
check("normal-state for a cause nobody found",
      bool(problems(GOOD + " | verdict: normal-state - it came back by itself, 根因不明 so far")), True)
check("normal-state for a cause nobody found (English)",
      bool(problems(GOOD + " | verdict: normal-state - the drop's cause is not known, it came back")), True)
check("fixed with a commit that does not exist",
      bool(problems(GOOD + " | verdict: fixed deadbeef0", has_commit=lambda s: False)), True)
check("fixed with no commit", bool(problems(GOOD + " | verdict: fixed - trust me")), True)
check("normal-state without a why", bool(problems(GOOD + " | verdict: normal-state - ok")), True)
check("task-switch that keeps a failure out",
      bool(problems("x.py:f | marked recovered (daily report only) | 「他的话」 | 2026-10-10 13:35"
                    " | verdict: task-switch - his order to switch the farm off")), True)
check("two verdicts", bool(problems(GOOD + " | verdict: task-switch - his order | verdict: fixed abc1234")), True)
check("a good normal-state passes",
      problems(GOOD + " | verdict: normal-state - an outside site answered its one retry; both failing is pushed, "
                      "why it fails is not known"), [])
check("a good fixed passes", problems(GOOD + " | verdict: fixed abc1234", has_commit=lambda s: True), [])
check("the commit lookup itself works (HEAD)", commit_exists("HEAD"), True)

print("[every line of USER-SWITCHES.txt]")
entries = [(i, l.strip()) for i, l in enumerate(LIST.read_text(encoding="utf-8").splitlines(), 1)
           if l.strip() and not l.lstrip().startswith("#")]
check("the list has lines", len(entries) > 0, True)
kinds = {}
for i, line in entries:
    got = problems(line)
    check(f"USER-SWITCHES.txt:{i} {line.split(' | ')[0]}", got, [])
    m = VERDICT_RE.search(line)
    if m:
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
print(f"  · {len(entries)} lines: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
