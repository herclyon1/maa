"""Every line of USER-SWITCHES.txt says why what it keeps from the group may stay there.

The user, 2026-10-10 13:35 (Tokyo), quoted in USER-SWITCHES.txt's header: alarms were switched
off while the bugs under them were never fixed, and that has no place in the relay. Until then a line only had to quote him (tests/test_user_switches.py); the WMI drop after a
restart and MaaEnd not exiting were daily-report-only under his 2026-10-06 05:07 rule on
faults that fixed themselves, while neither cause was known and both kept happening.

Each entry now ends in `| verdict: <kind> - <why>`, one of:
  fixed <sha>     the cause was fixed in that commit (it must exist in this repository);
  normal-state    `normal-state - recovered: <why>; <what is pushed when it does not>` - the
                  fault fixed itself; after the first ";" the line says what is pushed when it
                  does not, and the place's own code writes the red item for it
                  (errwatch.recovered(), techlog.self_heal, handle._self_heal_red), so a
                  session looks at why (the user, 2026-10-11 17:44);
                  `normal-state - not-a-fault: <why>` - only for a place on NOT_A_FAULT below,
                  each with its source. Either way the part before the first ";" may not call
                  the cause unknown. The user, 2026-10-11 17:43: 「如果不是自己好了禁止只进日报」;
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


# Places that keep something from the group because it is not a fault at all - not
# because it fixed itself. Adding one means editing this test, with its source.
NOT_A_FAULT = {
    "ark_relay/features/alarm/handle.py:_drop_update_after_done":
        "MaaEnd installing its own new build after the shift's round was done: the upstream "
        "update, no work left undone (acceptance 2026-10-11 17:4x reading of USER-SWITCHES)",
    "ark_relay/features/okww_patch/okww_files/ark_overrides.tasks.py:_skip_short":
        "weekly boss short on crystal waveplates: the game's resources (user 2026-10-06 10:34, "
        "memory normal-state-not-an-alarm)",
    "ark_relay/features/shutdown/shutdown.py:_say_if_moment_passed":
        "why the machine stays on past its moment; he asked only for 「关机被取消」 (user 2026-10-10 23:22)",
    "ark_relay/features/host/procwatch.py:_ProcessWatch._push_open_drop":
        "Windows tearing WMI down after a power-off request it logged (System log 1074) is the "
        "shutdown itself (user 2026-10-10 13:35 asked for the cause to be told apart, not silenced)",
}
# What writes the red item for a fault that fixed itself (techlog.self_heal).
RED_WRITERS = re.compile(r"\brecovered\(\)|\btechlog\.self_heal\(|\b_self_heal_red\(")

VERDICT_RE = re.compile(r"\s\|\s+verdict:\s+(?P<kind>fixed|normal-state|task-switch)\b\s*(?P<rest>.*)$")
SHA_RE = re.compile(r"^(?P<sha>[0-9a-f]{7,40})\b")
UNKNOWN = ("not known", "unknown", "unexplained", "nothing explained", "not found", "tbd", "to be checked",
           "不明", "待查", "没查清", "还没查")
KEPT = ("recovered", "daily report only", "daily-report-only", "not pushed", "只进日报", "不进群")


def commit_exists(sha: str) -> bool:
    r = subprocess.run(["git", "-C", str(RELAY), "cat-file", "-e", f"{sha}^{{commit}}"],
                       capture_output=True, timeout=30)
    return r.returncode == 0


def place_source(key: str) -> "str | None":
    """The source of the function a line's key names (file:func, file:Class.method,
    nested defs dotted), or None when it is not there."""
    import ast  # noqa: PLC0415
    file, _, dotted = key.partition(":")
    path = RELAY / file
    try:
        text = path.read_text(encoding="utf-8")
        node = ast.parse(text)
    except (OSError, SyntaxError):
        return None
    for part in dotted.split("."):
        node = next((n for n in ast.walk(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     and n.name == part and n is not node), None)
        if node is None:
            return None
    return ast.get_source_segment(text, node)


def problems(line: str, has_commit=commit_exists, source=place_source) -> list[str]:
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
        key = line.split(" | ")[0].strip()
        if rest.startswith("not-a-fault:"):
            return [] if key in NOT_A_FAULT else [f"not-a-fault, but {key} is not on NOT_A_FAULT"]
        if not rest.startswith("recovered:"):
            return ["normal-state is neither `recovered:` nor `not-a-fault:`"]
        _, sep, unhealed = rest.partition(";")
        if not sep or "push" not in unhealed.lower():
            return ["recovered without saying what is pushed when it does not recover (after the first \";\")"]
        code = source(key)
        if code is None:
            return [f"recovered, but {key} is not in the code"]
        if not RED_WRITERS.search(code):
            return [f"recovered, but {key} writes no red item (errwatch.recovered() / techlog.self_heal)"]
        return []
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
HEALS = lambda key: "def f():\n    log.warning('x', extra=errwatch.recovered())\n"   # noqa: E731
QUIET = lambda key: "def f():\n    log.info('x 自己好了')\n"                           # noqa: E731
check("a good recovered passes",
      problems(GOOD + " | verdict: normal-state - recovered: an outside site answered its one retry; both failing is "
                      "pushed, why it fails is not known", source=HEALS), [])
check("normal-state without recovered: / not-a-fault:",
      bool(problems(GOOD + " | verdict: normal-state - an outside site answered its one retry; both failing is pushed",
                    source=HEALS)), True)
check("recovered that writes no red item",
      bool(problems(GOOD + " | verdict: normal-state - recovered: an outside site answered its one retry; both "
                           "failing is pushed", source=QUIET)), True)
check("recovered that never says what is pushed when it does not recover",
      bool(problems(GOOD + " | verdict: normal-state - recovered: an outside site answered its one retry", source=HEALS)),
      True)
check("not-a-fault for a place not on NOT_A_FAULT",
      bool(problems(GOOD + " | verdict: normal-state - not-a-fault: the daily report says it, that is enough")), True)
check("not-a-fault for a place on NOT_A_FAULT passes",
      problems("ark_relay/features/host/procwatch.py:_ProcessWatch._push_open_drop | x | 「他的话」 | 2026-10-10 13:35"
               " | verdict: normal-state - not-a-fault: Windows tearing WMI down after a power-off request"), [])
check("the place finder finds a method", "def _push_open_drop" in (place_source("ark_relay/features/host/procwatch.py:_ProcessWatch._push_open_drop") or ""),
      True)
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
listed = {line.split(" | ")[0].strip() for _, line in entries}
for key in NOT_A_FAULT:
    check(f"NOT_A_FAULT {key} has its line", key in listed, True)

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
