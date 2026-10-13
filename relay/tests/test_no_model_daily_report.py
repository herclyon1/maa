#!/usr/bin/env python3
"""The model-written daily report is gone; the template is the only path.

Retired on 08-30 (66711d4f: 「模型写日报是废除的规划（太贵）」) yet report.py still
tried summary.daily_report first; relay.log has 0 「日报由模型撰写」 lines and 129
「日报用结构化模板」. Had it run, it would have skipped split_test (test-window
runs in the report) and the retry / make-up / stage-gate lines.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.core import summary
from ark_relay.features.report import report

fails = []
for label, ok in (("summary.daily_report removed", not hasattr(summary, "daily_report")),
                  ("_compose_daily has no model branch", "日报由模型撰写" not in inspect.getsource(report._compose_daily))):
    print(("  ✓ " if ok else "  ✗ ") + label)
    if not ok:
        fails.append(label)
print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
