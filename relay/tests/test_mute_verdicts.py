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
                  the cause unknown. The user, 2026-10-11 17:43: 「如果不是自己好了禁止只进日报」.
                  Since 2026-10-11 the why (after `recovered:` / `not-a-fault:`, and each
                  NOT_A_FAULT source) may not lean on the user's words (his words, he asked,
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


# Places that keep something from the group because it is not a fault at all - not
# because it fixed itself. Adding one means editing this test, with its source.
NOT_A_FAULT = {
    "ark_relay/features/alarm/handle.py:_drop_update_after_done":
        "MaaEnd installing its own new build after the shift's round had done its work: the upstream "
        "update, no work left undone (ark_relay/features/alarm/handle.py:_update_restart_done checks the "
        "done round; without one ark_relay/features/alarm/handle.py:_flush_pending pushes the restart)",
    "ark_relay/features/okww_patch/okww_files/ark_overrides.tasks.py:_skip_short":
        "only the skip is normal: no fight for no reward and no AUTO-MAS retry that would find no more "
        "waveplates; the shortage itself is red and pushed (ark_relay/features/verify/outcome.py:okww_checks)",
    "ark_relay/features/shutdown/shutdown.py:_say_if_moment_passed":
        "why the machine stays on past its moment: each reason is a state whose fault pushes on its own path "
        "(ark_relay/features/run/runwatch.py:check_timeouts, ark_relay/features/alarm/handle.py:_flush_pending); "
        "the relay losing track is a WARNING (ark_relay/features/shutdown/shutdown.py:RELAY_LOST_TRACK)",
    "ark_relay/features/host/procwatch.py:_ProcessWatch._push_open_drop":
        "Windows tearing WMI down after a power-off request it logged is the shutdown itself (System log "
        "1074 at 10-10 04:27:24, the drop at 04:28:45); a drop before the request still pushes "
        "(ark_relay/features/host/procwatch.py:_ProcessWatch._push_open_drop)",
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
            if key not in NOT_A_FAULT:
                return [f"not-a-fault, but {key} is not on NOT_A_FAULT"]
            return reason_problems(rest[len("not-a-fault:"):], has_commit)
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
        return reason_problems(rest[len("recovered:"):], has_commit)
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
      problems(GOOD + " | verdict: normal-state - recovered: an outside site answered its one retry "
                      "(ark_relay/core/notify.py:route_of); both failing is pushed, why it fails is not known",
               source=HEALS), [])
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
DROP = "ark_relay/features/host/procwatch.py:_ProcessWatch._push_open_drop"
check("not-a-fault for a place on NOT_A_FAULT passes",
      problems(DROP + " | x | 「他的话」 | 2026-10-10 13:35 | verdict: normal-state - not-a-fault: Windows tearing "
                      "WMI down after a power-off request it logged (System log 1074 at 10-10 04:27:24)"), [])
check("the place finder finds a method", "def _push_open_drop" in (place_source(DROP) or ""), True)
R = " | verdict: normal-state - recovered: "
check("normal-state whose why is the user's words (10-06 weekly boss line)",
      bool(problems(GOOD + " | verdict: normal-state - not-a-fault: the weekly boss short on crystal waveplates is the "
                           "game's resources, not a fault (his 10-06 10:34 words)")), True)
check("not-a-fault on NOT_A_FAULT resting on what he asked for (10-10 stay-on line)",
      bool(problems("ark_relay/features/shutdown/shutdown.py:_say_if_moment_passed | x | 「他的话」 | 2026-10-10 23:22"
                    " | verdict: normal-state - not-a-fault: he asked for that one message only; see "
                    "ark_relay/core/notify.py:route_of")), True)
check("recovered with a reason but no source",
      bool(problems(GOOD + R + "an outside site answered its one retry; both failing is pushed", source=HEALS)), True)
check("recovered citing a function that is not there",
      bool(problems(GOOD + R + "an outside site answered its one retry "
                               "(ark_relay/core/notify.py:no_such_function_here); both failing is pushed",
                    source=HEALS)), True)
check("recovered citing a doc that is not there",
      bool(problems(GOOD + R + "the game's own rule, docs/NO-SUCH-FILE.md; both failing is pushed", source=HEALS)),
      True)
check("a good recovered passes (log source)",
      problems(GOOD + R + "it came back on the next try (relay.log 10-10 04:28:51); both failing is pushed",
               source=HEALS), [])
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
for key, why in NOT_A_FAULT.items():
    check(f"NOT_A_FAULT {key} has its line", key in listed, True)
    check(f"NOT_A_FAULT {key} gives a reason with a source", reason_problems(why), [])

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
