#!/usr/bin/env python3
"""Essence target mode with nothing left to farm is its own ending: not a
false green, not work done.

Real record, 2026-10-16: AUTO-MAS history MaaEnd-09-53-33 and MaaEnd's own app
log 2026-10-16-3.log, both read from the game PC unchanged into
replay/2026-10-16/endfield/ (test_replay.py replays the same record through the
outcome check, verdict.json: says nothing). Only 玉中身 is ticked in
target mode; its essence was already owned, so 基质刷取 spent 180 s on the
inventory scan and ended with 「🎯目标模式：勾选武器的基质均已满足，结束任务」
(upstream autoessence/plan_action.go "all targets satisfied"). The relay knew
only 「已完成一次基质刷取|理智不足」 as work and 「根据执行周期跳过」 as a skip, so at
14:12:12 it pushed a group alert saying the task had reported done after 180 s
with no trace of farming in the log.

The negative case keeps the generic 「基质目标已满足或任务结束」 line that
AutoEssenceOnComplete prints on any target-mode ending: alone, it must still
alert.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay.core import ledger as core
from ark_relay.core import texts
from ark_relay.core.config import SERVER_TZ
from ark_relay.features.verify.collector_maaend import parse_maaend_log
from ark_relay.features.verify.outcome import maaend_checks, summarize

REC = Path(__file__).resolve().parent / "replay" / "2026-10-16" / "endfield"
HIST = (REC / "MaaEnd-09-53-33.log").read_text(encoding="utf-8")
APP = "\n" + (REC / "2026-10-16-3.log").read_text(encoding="utf-8")
MET_LINE = "勾选武器的基质均已满足"
GENERIC = "基质目标已满足或任务结束"
FAILED: list[str] = []


def require(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILED.append(name)


def bad(checks) -> dict:
    return {c.label: c.detail for c in checks if not c.ok}


def without_met(text: str) -> str:
    return "\n".join(x for x in text.splitlines() if MET_LINE not in x) + "\n"


def ent(raw: dict, incomplete) -> dict:
    st = datetime(2026, 10, 16, 13, 54, 57, tzinfo=SERVER_TZ)
    fin = datetime(2026, 10, 16, 14, 11, 39, tzinfo=SERVER_TZ)
    return {"run_id": "2026-10-16/endfield/MaaEnd-09-53-33", "script": "MaaEnd", "user": "u", "ok": True,
            "started": st.isoformat(), "finished": fin.isoformat(), "incomplete": incomplete,
            "duration_known": True, "transitional": False, "failed_tasks": [],
            "raw": raw, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}


def main() -> int:
    require("fixture has the real ending lines", MET_LINE in HIST and GENERIC in HIST)

    print("[10-16 14:10 那趟：勾选的武器基质已经齐了，没刷]")
    checks = maaend_checks(HIST + APP, [], own_log=True)
    b = bad(checks)
    require("基质刷取 is not judged undone", not any(k.startswith("基质刷取") for k in b), repr(b))
    msg = summarize(checks, "MaaEnd")
    require("no group alert for the whole run", msg is None, repr(msg))

    # With a real failure in the same run the summary is written: the target-met
    # task has its own line and is not listed as done.
    fake = ("[2026-10-16 14:12:00.000] 任务开始: ⚔️协议空间\n"
            "[2026-10-16 14:12:20.000] 任务完成: ⚔️协议空间\n")
    msg2 = summarize(maaend_checks(HIST + fake + APP, [], own_log=True), "MaaEnd") or ""
    lines2 = msg2.splitlines()
    require("own line 「勾选的武器基质已经齐了、没刷：基质刷取」",
            texts.OUTCOME_ESSENCE_MET_HEAD + "基质刷取" in lines2, msg2)
    require("not listed under 干成的",
            not any(ln.startswith("干成的") and "基质刷取" in ln for ln in lines2), msg2)

    print("[只有通用那句「基质目标已满足或任务结束」：照旧报]")
    generic = without_met(HIST)
    require("negative fixture keeps the generic line only", GENERIC in generic and MET_LINE not in generic)
    bg = bad(maaend_checks(generic + APP, [], own_log=True))
    require("still judged undone, with the seconds",
            "180 秒" in bg.get("基质刷取 真的刷了", ""), repr(bg))

    print("[日报：一行说清没刷、可以换武器]")
    d = tmpdir()
    raw = parse_maaend_log(REC / "MaaEnd-09-53-33.log")
    require("parser: target met recorded", raw.get("maaend_essence_met") is True, repr(raw.get("maaend_essence_met")))
    require("parser: not booked as a farm of 0 runs", "maaend_farm" not in raw, repr(raw.get("maaend_farm")))
    _t, body = core.format_daily("2026-10-16", [ent(raw, msg)])
    require("daily report says it plainly", texts.ESSENCE_TARGET_MET in body, body)
    require("... does not say 刷 基质刷取", "刷 基质刷取" not in body, body)
    require("... the row is not ⚠️ / 没干完", "没干完" not in body and not body.startswith("⚠️"), body)

    (d / "generic.log").write_text(generic, encoding="utf-8")
    graw = parse_maaend_log(d / "generic.log")
    require("parser: generic line alone is not target met",
            "maaend_essence_met" not in graw and graw.get("maaend_farm") == "基质刷取", repr(graw.get("maaend_farm")))

    for t in (texts.ESSENCE_TARGET_MET, texts.OUTCOME_ESSENCE_MET_HEAD):
        require(f"plain language: {t}", texts.plain(t) == [], repr(texts.plain(t)))

    print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
