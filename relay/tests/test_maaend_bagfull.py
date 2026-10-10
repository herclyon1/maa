#!/usr/bin/env python3
"""An essence claim that never lands: a full bag when the storage-full notice was
seen, otherwise an ordinary failure that carries the raw MaaEnd lines.

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
full bag. Since 2026-10-06 such a failure is reported as the task failing, like any
other (no softened 「unconfirmed」 cause), and the raw lines from the claim click to
the failure - the run log's and the framework log's - go with the failure text, so
whatever else made it fail can be read off them.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import collector_maaend as cm
from ark_relay import texts
from ark_relay.core import ledger as core
from ark_relay.collector_maaend import CLAIM_UNCONFIRMED, parse_maaend_log
from ark_relay.config import SERVER_TZ, RunRecord
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

FAILED: list[str] = []
FIX = Path(__file__).resolve().parent / "fixtures"
# Two framework lines in the shape of fixtures/collect-watch-2026-09-14/maafw-attempt3.log
# (an event line and the same event from the second process), moved to the seconds
# between the 09-24 click (10:16:26) and its failure (10:16:51); plus one line of a
# later minute that must stay out.
FW_IN_WINDOW = (
    '[2026-09-24 10:16:40.100][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65]'
    '[MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] '
    '[details={"action_id":500000076,"focus":null,"name":"AutoEssenceClaimConfirm","task_id":200000013}] \n'
    '[2026-09-24 10:16:40.101][INF][Px18500][Tx10532][Utils/EventDispatcher.hpp][L65]'
    '[MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] '
    '[details={"action_id":500000076,"focus":null,"name":"AutoEssenceClaimConfirm","task_id":200000013}] \n'
    '[2026-09-24 10:16:45.000][DBG][Px7172][Tx32558][OCRer.cpp][L90][MaaNS::VisionNS::OCRer::analyze] noise\n'
    '[2026-09-24 10:20:00.000][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65]'
    '[MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.Starting] later\n')


def require(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILED.append(name)


def failure_text(raw: dict) -> str:
    t0 = datetime(2026, 9, 24, 10, 0, tzinfo=SERVER_TZ)
    r = RunRecord(run_id="2026-09-24/endfield/MaaEnd-06-07-50", script="MaaEnd", user="endfield",
                  started=t0, finished=t0, ok=False, failed_tasks=list(raw.get("tasks_failed") or []), raw=raw)
    return core.format_failure(r)[1]


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
    require("a proven full bag carries no raw lines", not r.get("maaend_claim_lines"), repr(r.get("maaend_claim_lines")))

    print("[no storage-full notice: an ordinary failure, with the raw lines]")
    bare = parse_maaend_log(FIX / "maaend_bagfull_2026-09-25.log")
    require("without the framework log no cause is named (no softened 「unconfirmed」)",
            not bare.get("maaend_fail_causes"), repr(bare.get("maaend_fail_causes")))
    require("... and the failure is still a failure",
            "基质刷取" in (bare.get("tasks_failed") or []), repr(bare.get("tasks_failed")))
    claim = (bare.get("maaend_claim_lines") or {}).get("基质刷取") or {}
    require("the run log's lines from the click to the failure, verbatim",
            claim.get("run") == ["[2026-09-25 09:53:13.162] 👆点击确认领取按钮",
                                 "[2026-09-25 09:53:38.147] 任务失败: 🎱基质刷取"], repr(claim.get("run")))
    require("no MaaEnd folder: the framework part says why it is missing",
            (claim.get("fw"), claim.get("fw_why")) == ([], "没配终末地的目录"), repr(claim))
    body = failure_text(bare)
    require("the failure text names the task plainly", "· 失败于：赠送干员礼物、基质刷取、日常奖励领取" in body, body)
    require("... with no softened cause or bag advice",
            CLAIM_UNCONFIRMED not in body and "请看一眼背包" not in body and "也是这个样子" not in body, body)
    require("... and carries the raw lines", "[2026-09-25 09:53:13.162] 👆点击确认领取按钮" in body
            and "[2026-09-25 09:53:38.147] 任务失败: 🎱基质刷取" in body, body)

    empty = tmpdir()
    (empty / "debug").mkdir(parents=True)
    (empty / "debug" / "maafw.log").write_text("", encoding="utf-8")
    c24 = parse_maaend_log(FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log", empty)
    require("09-24: claim click then failure, no storage-full notice -> no cause",
            not c24.get("maaend_fail_causes"), repr(c24.get("maaend_fail_causes")))
    require("09-24: the essence failure is still reported",
            "基质刷取" in (c24.get("tasks_failed") or []), repr(c24.get("tasks_failed")))
    c24c = (c24.get("maaend_claim_lines") or {}).get("基质刷取") or {}
    require("09-24: the run log stretch starts at the click and ends at the failure",
            bool(c24c.get("run")) and "点击确认领取按钮" in c24c["run"][0] and "任务失败" in c24c["run"][-1],
            repr(c24c.get("run")))
    require("09-24: an empty framework log is said, not hidden",
            (c24c.get("fw"), c24c.get("fw_why")) == ([], "框架日志里这段时间没有记录"), repr(c24c))
    late = tmpdir()
    (late / "debug").mkdir(parents=True)
    (late / "debug" / "maafw.log").write_bytes(
        (FIX / "maaend_bagfull_2026-09-25_maafw.log").read_bytes())
    c24b = parse_maaend_log(FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log", late)
    require("a notice from another day's run does not count",
            not c24b.get("maaend_fail_causes"), repr(c24b.get("maaend_fail_causes")))

    print("[the framework log's lines of the same seconds go with it]")
    fwd = tmpdir()
    (fwd / "debug").mkdir(parents=True)
    (fwd / "debug" / "maafw.log").write_text(FW_IN_WINDOW, encoding="utf-8")
    cw = ((parse_maaend_log(FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log", fwd)
           .get("maaend_claim_lines") or {}).get("基质刷取") or {})
    fw = cw.get("fw") or []
    require("the event line inside the window, once (the second process's copy dropped)",
            len(fw) == 1 and "AutoEssenceClaimConfirm" in fw[0], repr(fw))
    require("stamp and level kept, process / thread / source brackets dropped",
            bool(fw) and fw[0].startswith("[2026-09-24 10:16:40.100][INF] !!!OnEventNotify!!!")
            and "Px7172" not in fw[0], repr(fw))
    require("lines after the failure are left out", not any("10:20:00" in x for x in fw), repr(fw))
    require("each line is cut to a length", all(len(x) <= 201 for x in fw), repr([len(x) for x in fw]))
    body = failure_text(parse_maaend_log(FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log", fwd))
    require("the failure text carries the framework line under its heading",
            texts.CLAIM_LINES_FW in body and "AutoEssenceClaimConfirm" in body, body)

    print("[a long stretch is capped: first and last lines, the count of the rest]")
    many = [f"[2026-09-24 10:16:{i:02d}.000] 第 {i} 行" for i in range(40)]
    capped = cm._cap(many)
    require("first and last lines kept, one line for the rest",
            capped[:cm.CLAIM_HEAD_LINES] == many[:cm.CLAIM_HEAD_LINES]
            and capped[-cm.CLAIM_TAIL_LINES:] == many[-cm.CLAIM_TAIL_LINES:]
            and capped[cm.CLAIM_HEAD_LINES] == texts.claim_lines_skipped(40 - cm.CLAIM_HEAD_LINES - cm.CLAIM_TAIL_LINES),
            repr(capped))

    ok = parse_maaend_log(FIX / "maaend_full_2026-09-01.log")
    require("a normal run has no causes", not ok.get("maaend_fail_causes"),
            repr(ok.get("maaend_fail_causes")))
    require("... and no claim lines", not ok.get("maaend_claim_lines"), repr(ok.get("maaend_claim_lines")))
    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: {FAILED}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
