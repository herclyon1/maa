#!/usr/bin/env python3
"""The daily report says a weekday-skipped MaaEnd task was skipped: not done,
not missing.

collector_maaend puts every task followed by 「现在游戏时间是周X，根据执行周期跳过任务」
into raw["maaend_tasks_skipped"] ({task: weekday}) and leaves it out of
tasks_done. The report (core._block_maaend, core.daily_footnote) has to read
that field: before, only 自动采集 had a sentence, so a skipped 协议空间 simply
vanished from the report - neither done nor said to be skipped.

The skip lines are the real ones from tests/replay/2026-09-05 MaaEnd-05-27-42.log
(lines 534-536) with the task-start line of the real 09-27 协议空间 run
(fixtures/maaend-farm-drops/2026-09-27.log); no real log of a skipped
协议空间 exists yet. The other lines are verbatim task lines of 2026-09-06.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir  # noqa: E402
from ark_relay import core  # noqa: E402
from ark_relay.collector_maaend import parse_maaend_log  # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402

FAILED: list[str] = []
HERE = Path(__file__).resolve().parent

LOG = ("[2026-09-06 09:41:39.529] 任务开始: 🎁赠送干员礼物\n"
       "[2026-09-06 09:44:06.485] 任务完成: 🎁赠送干员礼物\n"
       "[2026-09-06 09:51:43.971] 任务开始: 🛒据点交易\n"
       "[2026-09-06 09:53:39.232] 任务完成: 🛒据点交易\n"
       "[2026-09-06 09:53:40.071] 任务开始: ⚔️协议空间\n"
       "[2026-09-06 09:53:40.154] 现在游戏时间是周二，根据执行周期跳过任务\n"
       "[2026-09-06 09:53:40.221] 任务完成: ⚔️协议空间\n"
       "[2026-09-06 09:53:41.000] 任务开始: 📅日常奖励领取\n"
       "[2026-09-06 09:55:00.000] 任务完成: 📅日常奖励领取\n")


def require(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILED.append(name)


def ent(raw: dict) -> dict:
    st = datetime(2026, 9, 6, 9, 41, tzinfo=SERVER_TZ)
    return {"run_id": "2026-09-06/endfield/MaaEnd-05-40-21", "script": "MaaEnd", "user": "u", "ok": True,
            "started": st.isoformat(), "finished": (st + timedelta(minutes=14)).isoformat(),
            "duration_known": True, "transitional": False, "failed_tasks": [],
            "raw": raw, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}


def main() -> int:
    p = tmpdir() / "MaaEnd-05-40-21.log"
    p.write_text(LOG, encoding="utf-8")
    raw = parse_maaend_log(p)
    require("parser: 协议空间 skipped on 周二", raw.get("maaend_tasks_skipped") == {"协议空间": "周二"},
            repr(raw.get("maaend_tasks_skipped")))

    _title, body = core.format_daily("2026-09-06", [ent(raw)])
    require("the report says it was skipped by schedule, with the weekday",
            "按排班跳过、没有做：协议空间（今天周二）" in body, body)
    require("... and does not list it as done or farmed",
            "做了 赠送干员礼物、据点交易、日常奖励领取" in body and "刷 协议空间" not in body, body)
    foot = core.daily_footnote([ent(raw)])
    require("the daily list does not count it", "协议空间" not in foot and "据点交易" in foot, foot)

    # 自动采集 keeps its own sentence, said once (not again in the generic one).
    gather = parse_maaend_log(HERE / "replay" / "2026-09-05" / "endfield" / "MaaEnd-05-27-42.log")
    _t3, b3 = core.format_daily("2026-09-05", [ent(gather)])
    require("a skipped 自动采集 keeps its own sentence", "自动采集 今天周六不是采集日" in b3, b3)
    require("... and is not repeated in the generic one", "按排班跳过、没有做：自动采集" not in b3, b3)
    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: {FAILED}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
