#!/usr/bin/env python3
"""queue_rows' 「开机跑」 comes from AUTO-MAS v5.7's StartUpMode.

v5.7 replaced the bool StartUpEnabled with StartUpMode (Never / Always /
DailyFirst; app/models/config.py migrates True -> Always, False -> Never). The
relay still read StartUpEnabled, so on the real 10-11 config every queue said
「开机跑」: None.
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


print("[real 10-11 config: both queues StartUpMode Never]")
rows = plan.queue_rows(REAL)
require("开机跑 is False, not None", [r["开机跑"] for r in rows] == [False, False], repr(rows))

print("[Always and DailyFirst both run at start-up]")
root = tmpdir()
shutil.copytree(REAL, root / "a")
qf = root / "a" / "config" / "QueueConfig.json"
d = json.loads(qf.read_text(encoding="utf-8"))
uids = [i["uid"] for i in d["instances"]]
d[uids[0]]["Info"]["StartUpMode"] = "Always"
d[uids[1]]["Info"]["StartUpMode"] = "DailyFirst"
qf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
rows = plan.queue_rows(root / "a")
require("both say True", [r["开机跑"] for r in rows] == [True, True], repr(rows))

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
