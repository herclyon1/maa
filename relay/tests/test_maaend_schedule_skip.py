#!/usr/bin/env python3
"""A task MaaEnd skips by its weekday schedule is reported as skipped, not done.

MaaEnd prints 「任务完成」 for it anyway. Real case: tests/replay/2026-09-05
MaaEnd-05-27-42.log lines 534-536 (自动采集 opened, then the line
「现在游戏时间是周六，根据执行周期跳过任务」 is printed in the log, and the task closed). The same 执行周期 checkbox sits on ProtocolSpace and AutoEssence
(tests/fixtures/maaend228/tasks/*.json), so the 协议空间 case below is those
three real lines with the task-start line of the real 09-27 协议空间 run
(fixtures/maaend-farm-drops/2026-09-27.log) - no real log of that skip exists yet.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ark_relay.collector_maaend import parse_maaend_log
from _tmp import tmpdir

FAILED: list[str] = []
HERE = Path(__file__).resolve().parent


def require(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILED.append(name)


def main() -> int:
    r = parse_maaend_log(HERE / "replay" / "2026-09-05" / "endfield" / "MaaEnd-05-27-42.log")
    require("skipped gathering is not listed as done", "自动采集" not in (r.get("tasks_done") or []),
            repr(r.get("tasks_done")))
    require("... it is listed as skipped with its weekday",
            (r.get("maaend_tasks_skipped") or {}).get("自动采集") == "周六", repr(r.get("maaend_tasks_skipped")))
    require("the old gathering key is kept", r.get("maaend_collect_skipped") == "周六",
            repr(r.get("maaend_collect_skipped")))

    ps = tmpdir() / "ps.log"
    ps.write_text("[2026-09-27 09:45:11.071] 任务开始: ⚔️协议空间\n"
                  "[2026-09-27 09:45:11.154] 现在游戏时间是周二，根据执行周期跳过任务\n"
                  "[2026-09-27 09:45:11.221] 任务完成: ⚔️协议空间\n", encoding="utf-8")
    p = parse_maaend_log(ps)
    require("skipped 协议空间 is not listed as done", "协议空间" not in (p.get("tasks_done") or []),
            repr(p.get("tasks_done")))
    require("... it is listed as skipped", (p.get("maaend_tasks_skipped") or {}).get("协议空间") == "周二",
            repr(p.get("maaend_tasks_skipped")))
    require("... and no 「刷 协议空间 ×0」 farming section", not p.get("maaend_farm"), repr(p.get("maaend_farm")))

    full = parse_maaend_log(HERE / "fixtures" / "maaend-farm-drops" / "2026-09-27.log")
    require("a run that really farmed is unchanged", full.get("maaend_farm") == "协议空间"
            and "协议空间" in (full.get("tasks_done") or []) and not full.get("maaend_tasks_skipped"),
            repr((full.get("maaend_farm"), full.get("maaend_tasks_skipped"))))
    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: {FAILED}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
