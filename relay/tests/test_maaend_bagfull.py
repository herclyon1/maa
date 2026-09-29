#!/usr/bin/env python3
"""An essence claim that never lands is reported as a full bag.

The fixture is the AUTO-MAS log of the 2026-09-25 09:50 MaaEnd run (evidence
bundle 2026-09-25/endfield/MaaEnd-05-47-21), verbatim: 「点击确认领取按钮」,
then 「任务失败: 🎱基质刷取」 25 seconds later. The user ruled it a full bag
on 2026-09-26 16:30, not an upstream bug.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import core, texts
from ark_relay.collector_maaend import parse_maaend_log

FAILED: list[str] = []
FIX = Path(__file__).resolve().parent / "fixtures"


def require(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILED.append(name)


def main() -> int:
    r = parse_maaend_log(FIX / "maaend_bagfull_2026-09-25.log")
    causes = r.get("maaend_fail_causes") or {}
    require("the essence failure after the claim click is a full bag",
            causes == {"基质刷取": "背包满了"}, repr(causes))
    require("failure names stay unchanged (retries and alert keys match on them)",
            r.get("tasks_failed") == ["赠送干员礼物", "基质刷取", "日常奖励领取"],
            repr(r.get("tasks_failed")))
    line = core._fmt_failed(r["tasks_failed"], causes=causes)
    require("the alert line names the cause",
            line == "失败于：赠送干员礼物、基质刷取（背包满了）、日常奖励领取", line)
    advice = texts.known_cause(causes)
    require("the alert says to clear the bag", "清出背包空间" in advice, advice)
    require("the advice passes the plain-words gate", not texts.plain(advice),
            repr(texts.plain(advice)))

    ok = parse_maaend_log(FIX / "maaend_full_2026-09-01.log")
    require("a normal run has no causes", not ok.get("maaend_fail_causes"),
            repr(ok.get("maaend_fail_causes")))
    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: {FAILED}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
