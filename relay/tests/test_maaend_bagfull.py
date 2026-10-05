#!/usr/bin/env python3
"""An essence claim that never lands is reported as a full bag - only with the
storage-full wording in the log.

The fixture is the AUTO-MAS log of the 2026-09-25 09:50 MaaEnd run (evidence
bundle 2026-09-25/endfield/MaaEnd-05-47-21), verbatim: 「点击确认领取按钮」,
then 「任务失败: 🎱基质刷取」 25 seconds later. The user ruled it a full bag
on 2026-09-26 16:30, not an upstream bug; the storage-full notice was in
maafw.log's OCR, not in this run log. Since 2026-10-05 the click-then-fail
shape alone gives no cause (a stalled claim has the same shape and must not
trigger the bag clearing); the cause needs the storage-full wording itself.
"""
from __future__ import annotations

import sys
import tempfile
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
    real = (FIX / "maaend_bagfull_2026-09-25.log").read_text(encoding="utf-8")
    # Counter-example: the click-then-fail shape with no storage-full wording
    # (the run log as it really is) is an ordinary failure, no cause.
    r0 = parse_maaend_log(FIX / "maaend_bagfull_2026-09-25.log")
    require("click then fail, no storage-full wording -> no cause",
            not r0.get("maaend_fail_causes"), repr(r0.get("maaend_fail_causes")))
    require("... and the failure is still listed",
            r0.get("tasks_failed") == ["赠送干员礼物", "基质刷取", "日常奖励领取"],
            repr(r0.get("tasks_failed")))
    # Same log with the storage-full wording in it -> 背包满了.
    tmp = Path(tempfile.mkdtemp()) / "bagfull-with-notice.log"
    tmp.write_text(real.replace("收取暂存区物资", "收取暂存区物资\n[2026-09-25 09:53:41.000] 背包已满"),
                   encoding="utf-8")
    r = parse_maaend_log(tmp)
    causes = r.get("maaend_fail_causes") or {}
    require("the essence failure after the claim click, with the storage-full wording, is a full bag",
            causes == {"基质刷取": "背包满了"}, repr(causes))
    require("failure names stay unchanged (retries and alert keys match on them)",
            r.get("tasks_failed") == ["赠送干员礼物", "基质刷取", "日常奖励领取"],
            repr(r.get("tasks_failed")))
    # Storage-full wording but the essence task failed elsewhere (not after the
    # claim click) -> no cause either.
    other = tmp.with_name("other.log")
    other.write_text(real.replace("[2026-09-25 09:53:13.162] 👆点击确认领取按钮\n", "")
                     .replace("收取暂存区物资", "收取暂存区物资\n[2026-09-25 09:53:41.000] 背包已满"),
                     encoding="utf-8")
    ro = parse_maaend_log(other)
    require("storage-full wording without the claim click -> no cause",
            not ro.get("maaend_fail_causes"), repr(ro.get("maaend_fail_causes")))
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
