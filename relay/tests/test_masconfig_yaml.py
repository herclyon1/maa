"""AUTO-MAS v5.8's YAML settings read like v5.7's JSON (core/masconfig.py, core/miniyaml.py).

Ledger #113 (2026-10-23 08:48 Beijing): AUTO-MAS updated itself to v5.8.0-beta.1, moved
config/QueueConfig.json, ScriptConfig.json and PlanConfig.json into config/legacy-json and kept
the settings in queues.yaml, scripts.yaml and plans.yaml, with every time as UTC ISO. The relay
then found 「设置里一个脚本、队列都没有」 and 「读取 QueueConfig.json 失败: [Errno 2]」.
The YAML here is written in the shape of that machine's own files (indentless sequences, long
JSON strings folded in single quotes, quoted UTC times); the files themselves are not in this
public repo. Against the real files, miniyaml matched PyYAML on all four and plan.schedule,
plan._scripts, plan.next_plan and mascontract.check gave the same answers as from the JSON.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.core import masconfig, miniyaml, plan
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


print("[miniyaml: the constructs AUTO-MAS's files use]")
doc = miniyaml.loads("""\
order:
- uid: aaa
  type: QueueConfig
- uid: bbb
  type: QueueConfig
data:
  aaa:
    Info:
      Name: 早班
      TimeEnabled: true
      Delay: 0
      Ratio: 1.5
      ScriptAfterTask: null
      Note: ~
    Pipeline: '{"Data": {"Week": "2026-W42",
      "Notes": "it''s", "Tag": "[{\\"text\\": \\"日常\\"}]"},
      "Run": 2}'
    Quoted: "a\\tb \\u4e2d
      c"
    Long: a plain line
      that folds
    Empty: {}
    None: []
    '2026-10-22': date key
""")
check("an indentless sequence under its key", [x["uid"] for x in doc["order"]], ["aaa", "bbb"])
info = doc["data"]["aaa"]["Info"]
check("true / int / float / null / ~", (info["TimeEnabled"], info["Delay"], info["Ratio"],
                                        info["ScriptAfterTask"], info["Note"]), (True, 0, 1.5, None, None))
check("a single-quoted string folded over three lines, '' kept as one quote",
      json.loads(doc["data"]["aaa"]["Pipeline"]), {"Data": {"Week": "2026-W42", "Notes": "it's",
                                                            "Tag": '[{"text": "日常"}]'}, "Run": 2})
check("a double-quoted string: escapes and folding", doc["data"]["aaa"]["Quoted"], "a\tb 中 c")
check("a plain scalar folded over lines", doc["data"]["aaa"]["Long"], "a plain line that folds")
check("{} and []", (doc["data"]["aaa"]["Empty"], doc["data"]["aaa"]["None"]), ({}, []))
check("a quoted key stays a string", doc["data"]["aaa"]["2026-10-22"], "date key")
for bad in ("a: [1, 2]\n", "a: |\n  text\n", "a: &x 1\n", "a: !!str 1\n"):
    try:
        miniyaml.loads(bad)
        check(f"refuses {bad.strip()!r}", "parsed", "ValueError")
    except ValueError:
        check(f"refuses {bad.strip()!r}", True)

print("\n[masconfig: v5.8's layout read in v5.7's shape]")
QUEUES = """\
order:
- uid: q1
  type: QueueConfig
data:
  q1:
    Data:
      LastTimedStart: '2026-10-22T01:00:00Z'
    Info:
      Name: 早班
      TimeEnabled: true
      StartUpMode: Never
      AfterAccomplish: NoAction
    TimeSet:
      order:
      - uid: t1
        type: TimeSet
      data:
        t1:
          Info:
            Days:
            - Monday
            - Tuesday
            - Wednesday
            - Thursday
            - Friday
            - Saturday
            - Sunday
            Enabled: true
            Time: '2000-01-01T01:00:00Z'
    QueueItem:
      order:
      - uid: i1
        type: QueueItem
      data:
        i1:
          Info:
            ScriptId: s1
          Schedule:
            Days:
            - Monday
            - Tuesday
            - Wednesday
            - Thursday
            - Friday
            - Saturday
            - Sunday
            Enabled: true
            Mode: fixed_time
            Time: '1999-12-31T16:00:00Z'
"""
old = masconfig.legacy(miniyaml.loads(QUEUES))
check("order -> instances", old["instances"], [{"uid": "q1", "type": "QueueConfig"}])
check("sub-collections go under SubConfigsInfo", sorted(old["q1"]["SubConfigsInfo"]), ["QueueItem", "TimeSet"])
ts = old["q1"]["SubConfigsInfo"]["TimeSet"]["t1"]["Info"]
check("09:00 Beijing written as 2000-01-01T01:00:00Z reads back as 09:00 (v5.7's form)", ts["Time"], "09:00")
check("LastTimedStart in v5.7's form", old["q1"]["Data"]["LastTimedStart"], "2026-10-22 09:00")
check("a queue item's time too",
      old["q1"]["SubConfigsInfo"]["QueueItem"]["i1"]["Schedule"]["Time"], "00:00")

print("\n[the reader finds the YAML only when the JSON is gone]")
root = tmpdir()
cfg = root / "config"
cfg.mkdir()
(cfg / "queues.yaml").write_text(QUEUES, encoding="utf-8")
check("no JSON: the YAML", masconfig.source(cfg / "QueueConfig.json").name, "queues.yaml")
sched = plan.schedule(root)
check("plan.schedule sees the 09:00 morning queue (10-23 it saw none)",
      [(q["name"], q["times"], q["items"]) for q in sched], [("早班", ["09:00"], ["s1"])])
(cfg / "QueueConfig.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
check("JSON there (AUTO-MAS before v5.8): the JSON", masconfig.source(cfg / "QueueConfig.json").name,
      "QueueConfig.json")
try:
    masconfig.read(cfg / "ScriptConfig.json")
    check("neither file: the error reading the JSON gives", "read", "FileNotFoundError")
except FileNotFoundError:
    check("neither file: the error reading the JSON gives", True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
