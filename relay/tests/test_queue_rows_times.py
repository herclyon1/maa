#!/usr/bin/env python3
"""queue_rows gives each queue its start times (「时刻」), also while its timer is off.

A skip for today turns the queue's timer off (modes.py), and next_plan lists timed
queues only, so the phone's row of a skipped shift had no time to show (App review
10-14, 状态 page). Base data: the real 10-11 AUTO-MAS config (早班 09:00, 晚班 21:30).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import plan

FAILED: list[str] = []
REAL = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11"


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


print("[real 10-11 config]")
rows = plan.queue_rows(REAL)
want = {q["name"]: q["times"] for q in plan._queues(REAL / "config")}
require("each queue has its times, as the plan reads them",
        all(r.get("时刻") == want[r["名"]] for r in rows) and all(r.get("时刻") for r in rows), repr(rows))

print("[a queue skipped today: timer off, times kept]")
root = tmpdir()
shutil.copytree(REAL, root / "a")
qf = root / "a" / "config" / "QueueConfig.json"
d = json.loads(qf.read_text(encoding="utf-8"))
uid = d["instances"][0]["uid"]
d[uid]["Info"]["TimeEnabled"] = False
qf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
off = plan.queue_rows(root / "a")
require("定时 off but 时刻 still there", off[0]["定时"] is False and off[0].get("时刻") == rows[0].get("时刻"), repr(off[0]))

print("all checks passed" if not FAILED else "FAILED: " + ", ".join(FAILED))
sys.exit(1 if FAILED else 0)
