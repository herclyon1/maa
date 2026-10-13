#!/usr/bin/env python3
"""「明日安排」 names every AUTO-MAS after-run action, not only "Shutdown".

AUTO-MAS v5.7 QueueConfig Info.AfterAccomplish takes NoAction, Shutdown,
ShutdownForce, Reboot, Hibernate, Sleep, KillSelf, Logoff (models/config.py).
The plan only recognised "Shutdown", so a queue set to force shut down or
hibernate showed no line at all. Base data: the real 10-11 config (NoAction).
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

# next_plan's maintenance notices come from the official sites; nothing here is about
# them, and no relay test may reach the internet (run 38363145659 sat in those
# fetches on Windows until the 180 s limit).
plan.maintenance_lines = lambda day: []

FAILED: list[str] = []
REAL = Path(__file__).resolve().parent / "fixtures" / "automas-config-2026-10-11"


def require(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '❌'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def power_lines(after: "str | None") -> list[str]:
    root = tmpdir()
    shutil.copytree(REAL, root / "a")
    qf = root / "a" / "config" / "QueueConfig.json"
    d = json.loads(qf.read_text(encoding="utf-8"))
    if after is not None:
        for inst in d["instances"]:
            d[inst["uid"]]["Info"]["AfterAccomplish"] = after
    qf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return [ln for ln in plan.next_plan(root / "a").splitlines() if ln.startswith("⏻")]


require("real config (NoAction): no power line", power_lines(None) == [], repr(power_lines(None)))
require("Shutdown still says 关机", power_lines("Shutdown") == ["⏻ 跑完自动关机"] * 2, repr(power_lines("Shutdown")))
for value, zh in (("ShutdownForce", "强制关机"), ("Hibernate", "休眠"), ("Reboot", "重启"),
                  ("Sleep", "睡眠"), ("KillSelf", "退出 AUTO-MAS"), ("Logoff", "注销")):
    got = power_lines(value)
    require(f"{value} -> {zh}", got == [f"⏻ 跑完自动{zh}"] * 2, repr(got))

print("FAILED: " + ", ".join(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
