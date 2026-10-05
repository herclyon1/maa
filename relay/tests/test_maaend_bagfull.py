#!/usr/bin/env python3
"""An essence claim that never lands is reported as a full bag.

The fixture is the AUTO-MAS log of the 2026-09-25 09:50 MaaEnd run (evidence
bundle 2026-09-25/endfield/MaaEnd-05-47-21), verbatim: 「点击确认领取按钮」,
then 「任务失败: 🎱基质刷取」 25 seconds later. The user ruled it a full bag
on 2026-09-26 16:30, not an upstream bug. The proof is MaaEnd's OCR of the
mail opened seconds later: maaend_bagfull_2026-09-25_maafw.log is the two
DailyEmailConfirmTSA OCR lines carrying 「因仓储空间已满」, verbatim from that
run's maafw.log (evidence 2026-09-25_endfield_MaaEnd-05-54-06, logs zip).

Counter-example: fixtures/maaend-farm-drops/2026-09-24_MaaEnd-06-07-50.log has
the same claim click then 「任务失败: 🎱基质刷取」 (10:16:51), but the mail right
after was claimed and that run's maafw logs (evidence
2026-09-24_endfield_MaaEnd-06-07-50) carry no storage-full notice - so not a
full bag; the click-then-fail is still kept, as CLAIM_UNCONFIRMED.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import core, texts
from ark_relay.collector_maaend import CLAIM_UNCONFIRMED, parse_maaend_log
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

FAILED: list[str] = []
FIX = Path(__file__).resolve().parent / "fixtures"


def require(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILED.append(name)


def main() -> int:
    end = tmpdir()
    (end / "debug").mkdir(parents=True)
    (end / "debug" / "maafw.log").write_bytes(
        (FIX / "maaend_bagfull_2026-09-25_maafw.log").read_bytes())
    r = parse_maaend_log(FIX / "maaend_bagfull_2026-09-25.log", end)
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

    bare = parse_maaend_log(FIX / "maaend_bagfull_2026-09-25.log")
    require("without the framework log it is not called a full bag, but kept as unconfirmed",
            bare.get("maaend_fail_causes") == {"基质刷取": CLAIM_UNCONFIRMED}, repr(bare.get("maaend_fail_causes")))
    require("... and the failure is still a failure",
            "基质刷取" in (bare.get("tasks_failed") or []), repr(bare.get("tasks_failed")))
    empty = tmpdir()
    (empty / "debug").mkdir(parents=True)
    (empty / "debug" / "maafw.log").write_text("", encoding="utf-8")
    c24 = parse_maaend_log(FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log", empty)
    require("09-24: claim click then failure, no storage-full notice -> not a full bag (unconfirmed)",
            c24.get("maaend_fail_causes") == {"基质刷取": CLAIM_UNCONFIRMED}, repr(c24.get("maaend_fail_causes")))
    require("09-24: the essence failure is still reported",
            "基质刷取" in (c24.get("tasks_failed") or []), repr(c24.get("tasks_failed")))
    late = tmpdir()
    (late / "debug").mkdir(parents=True)
    (late / "debug" / "maafw.log").write_bytes(
        (FIX / "maaend_bagfull_2026-09-25_maafw.log").read_bytes())
    c24b = parse_maaend_log(FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log", late)
    require("a notice from another day's run does not count",
            c24b.get("maaend_fail_causes") == {"基质刷取": CLAIM_UNCONFIRMED}, repr(c24b.get("maaend_fail_causes")))

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
