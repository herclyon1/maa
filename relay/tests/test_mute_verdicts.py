"""Every line of USER-SWITCHES.txt says why what it keeps from the group may stay there.

The user, 2026-10-10 13:35 (Tokyo), quoted in USER-SWITCHES.txt's header: alarms were switched
off while the bugs under them were never fixed, and that has no place in the relay. Until then a line only had to quote him (tests/test_user_switches.py); the WMI drop after a
restart and MaaEnd not exiting were daily-report-only under his 2026-10-06 05:07 rule on
faults that fixed themselves, while neither cause was known and both kept happening.

Each entry now ends in `| verdict: <kind> - <why>`, one of:
  fixed <sha>     the cause was fixed in that commit (it must exist in this repository);
  normal-state    not a fault: the why names what makes it normal. The part before the first
                  ";" (what is kept from the group) may not call the cause unknown. Since
                  2026-10-11 the why may not lean on the user's words (his words, he asked,
                  his order, a date of his: his words say what he wants, not that a thing is
                  normal) and must name a source that holds: code `file.py:function` (the
                  function must be defined in that file), a log with its date, a docs/ or
                  relay/ file that exists, a URL, or `commit <sha>` that exists;
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


REPO = RELAY.parent
# A normal-state why says why the thing is not a fault. The user's words say what result he
# wants (column 3); they are not evidence that something is normal. The user, 2026-10-11 18:07,
# had every decision that rested on his words marked lazy and re-decided on reasons. So a why
# that leans on him fails, and a why must name at least one source that can be checked.
LAZY_RE = re.compile(r"his words|his own words|he asked|he did not want|he wants|his order|his rule|he said|"
                     r"on his\b|\bhis \d{1,2}:\d{2}|\bhis \d{2}-\d{2}|(?:the user|user|他)\W{0,3}(?:\d{4}-)?\d{2}-\d{2}|"
                     r"原话|按他|照他|他说|用户说", re.I)
CODE_REF_RE = re.compile(r"(?P<path>[\w./-]+\.py):(?P<name>[A-Za-z_][\w.]*)")
DOC_REF_RE = re.compile(r"(?P<path>(?:docs|relay)/[\w./-]+\.(?:md|txt))")
LOG_REF_RE = re.compile(r"\b(?:relay\.log|app\.log|maafw\.log|ok-ww log|okww log|system log|event (?:id )?\d{3,5})\b"
                        r"[^;]*?\b\d{2}-\d{2}\b", re.I)
URL_RE = re.compile(r"https?://\S+")
COMMIT_REF_RE = re.compile(r"\bcommit (?P<sha>[0-9a-f]{7,40})\b")


def code_ref_holds(path: str, name: str) -> bool:
    """`path.py:name` names a file under relay/ (or the repo) that defines or assigns `name`'s last part."""
    for base in (RELAY, REPO):
        f = base / path
        if f.is_file():
            leaf = re.escape(name.split(".")[-1].split("[")[0])
            src = f.read_text(encoding="utf-8")
            return bool(re.search(rf"^\s*(?:async\s+)?(?:def|class)\s+{leaf}\b|^\s*{leaf}\s*[:=]", src, re.M))
    return False


def reason_problems(why: str, has_commit=commit_exists) -> list[str]:
    """A normal-state why: no lean on the user's words, and at least one source that holds."""
    out = []
    lazy = LAZY_RE.search(why)
    if lazy:
        out.append(f"normal-state whose why leans on the user's words ({lazy.group(0)!r}), not a reason")
    sources = 0
    for m in CODE_REF_RE.finditer(why):
        if code_ref_holds(m["path"], m["name"]):
            sources += 1
        else:
            out.append(f"cites {m['path']}:{m['name']}, which is not defined there")
    for m in DOC_REF_RE.finditer(why):
        if (REPO / m["path"]).is_file():
            sources += 1
        else:
            out.append(f"cites {m['path']}, which does not exist")
    for m in COMMIT_REF_RE.finditer(why):
        if has_commit(m["sha"]):
            sources += 1
        else:
            out.append(f"cites commit {m['sha']}, which is not a commit here")
    sources += len(LOG_REF_RE.findall(why)) + len(URL_RE.findall(why))
    if not sources:
        out.append("normal-state with no source (code `file.py:function`, a log with its date, "
                   "docs/…, a URL or `commit <sha>`)")
    return out


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
        if bad:
            return [f"normal-state while its cause is unknown ({bad[0]})"]
        return reason_problems(rest, has_commit)
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
check("normal-state whose why is the user's words (10-06 weekly boss line)",
      bool(problems(GOOD + " | verdict: normal-state - the weekly boss short on crystal waveplates is the game's "
                           "resources, not a fault (his 10-06 10:34 words)")), True)
check("normal-state resting on what he asked for",
      bool(problems(GOOD + " | verdict: normal-state - he asked for that one message only; see "
                           "ark_relay/core/notify.py:route_of")), True)
check("normal-state with a reason but no source",
      bool(problems(GOOD + " | verdict: normal-state - an outside site answered its one retry; both failing is pushed")),
      True)
check("normal-state citing a function that is not there",
      bool(problems(GOOD + " | verdict: normal-state - an outside site answered its one retry "
                           "(ark_relay/core/notify.py:no_such_function_here); both failing is pushed")), True)
check("normal-state citing a doc that is not there",
      bool(problems(GOOD + " | verdict: normal-state - the game's own rule, docs/NO-SUCH-FILE.md; both failing is pushed")),
      True)
check("a good normal-state passes (code source)",
      problems(GOOD + " | verdict: normal-state - an outside site answered its one retry "
                      "(ark_relay/core/notify.py:route_of); both failing is pushed, why it fails is not known"), [])
check("a good normal-state passes (log source)",
      problems(GOOD + " | verdict: normal-state - Windows logged the power-off request first "
                      "(System log 1074 at 10-10 04:27:24, the drop at 04:28:45); a drop before it is pushed"), [])
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
