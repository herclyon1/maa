"""The watchdog's two group-bot messages read as plain words, like every relay push.

packaging/watchdog/ark_watchdog.py imports pywin32, so its texts are read with ast,
not imported. Both titles must also be rows of docs/NOTIFICATIONS.md's route table
(test_notify_routing.py then checks that they route to the group).

The other way round, relay/watchdog_guard.py's two ERRORs go to the group as they are,
through errwatch (「🩺 中继自己报错了」), so they are held to the same plain words (review
round 10 #29: 「拉起」 got through because log lines skip plain()). Every Chinese line the
guard logs is checked too.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay"))

from ark_relay.core.texts import plain  # noqa: E402

src = (ROOT / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8")
texts = {t.id: ast.literal_eval(n.value) for n in ast.parse(src).body
         if isinstance(n, ast.Assign) for t in n.targets
         if isinstance(t, ast.Name) and t.id.startswith("ALERT_")}
doc = (ROOT / "docs" / "NOTIFICATIONS.md").read_text(encoding="utf-8")

bad = 0
if set(texts) != {"ALERT_DOWN", "ALERT_NOBODY"}:
    print("FAIL: expected ALERT_DOWN and ALERT_NOBODY, found", sorted(texts))
    bad += 1
for name, text in texts.items():
    filled = text.format(n=3, s=30)
    problems = plain(filled)
    title = filled.split("\n", 1)[0]
    row = f"| {title} | group |" in doc
    print(f"{'ok' if not problems and row else 'FAIL'} {name}: {problems or 'plain'}; table row: {row}")
    bad += bool(problems) or not row
import watchdog_guard as G  # noqa: E402

guard_alerts = {k: v for k, v in vars(G).items() if k.startswith("ALERT_")}
if set(guard_alerts) != {"ALERT_GAVE_UP", "ALERT_CANNOT_LOOK"}:
    print("FAIL: expected ALERT_GAVE_UP and ALERT_CANNOT_LOOK in watchdog_guard, found", sorted(guard_alerts))
    bad += 1
for name, text in guard_alerts.items():
    # Filled the way failed() fills it; the reason is one _start writes.
    problems = plain(text % (3, "开到一半自己停了"))
    print(f"{'ok' if not problems else 'FAIL'} watchdog_guard.{name}: {problems or 'plain'}")
    bad += bool(problems)
guard_src = (ROOT / "relay" / "watchdog_guard.py").read_text(encoding="utf-8")
logged = [c.value for c in ast.walk(ast.parse(guard_src))
          if isinstance(c, ast.Constant) and isinstance(c.value, str) and "\n" not in c.value
          and any("\u4e00" <= ch <= "\u9fff" for ch in c.value)]   # docstrings have line breaks
for text in logged:
    problems = plain(text.replace("%d", "3").replace("%s", "原因").replace("{START_WAIT_S}", "45"))
    if problems:
        print(f"FAIL watchdog_guard copy {text!r}: {problems}")
        bad += 1
print(f"{'ok' if logged else 'FAIL'} watchdog_guard: {len(logged)} Chinese strings read")
bad += not logged
print("\n" + ("FAILED" if bad else "all checks passed"))
sys.exit(1 if bad else 0)
