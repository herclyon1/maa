"""The watchdog's two group-bot messages read as plain words, like every relay push.

packaging/watchdog/ark_watchdog.py imports pywin32, so its texts are read with ast,
not imported. Both titles must also be rows of docs/NOTIFICATIONS.md's route table
(test_notify_routing.py then checks that they route to the group).
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
sys.exit(1 if bad else 0)
