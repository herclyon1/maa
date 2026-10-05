#!/usr/bin/env python3
"""The 2026-09-25 full bag is still found by the collector on the machine.

The parser only proves a full bag from MaaEnd's framework log, which lives in
<maaend_dir>/debug (collector_maaend._maaend_fail_causes). This replays the
real 09-25 evidence through the path the relay really takes - LocalSource ->
collector.scan -> parse_record -> parse_maaend_log - and checks that the MaaEnd
folder from Config reaches the parser:

* fixtures/maaend_bagfull_2026-09-25.log is that run's AUTO-MAS log, verbatim;
* fixtures/maaend_bagfull_2026-09-25_maafw.log is the two OCR lines of the
  storage-full notice from that run's maafw.log, verbatim.

The AUTO-MAS result line is the single-name shape of the real ones in
tests/replay (「MaaEnd 部分任务执行失败: 🎱基质刷取」); the 09-25 result JSON
itself is not on file.

Also: without the framework log the click-then-fail is still reported (as
unconfirmed, never silently dropped), and the evening recompute does not
downgrade a full bag proven at bookkeeping time once MaaEnd has wiped its
debug folder.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

os.environ.update(ARK_STATE_DIR=str(tmpdir()), ARK_AUTOMAS_DIR="", ARK_MAAEND_DIR="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import collector, core, makeup, report, texts
from ark_relay.collector_maaend import BAG_FULL, CLAIM_UNCONFIRMED
from ark_relay.config import Config
from ark_relay.transport import LocalSource

FIX = Path(__file__).resolve().parent / "fixtures"
FAILED: list[str] = []
STEM = "MaaEnd-05-47-21"


def require(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
    if not ok:
        FAILED.append(name)


def history() -> Path:
    root = tmpdir()
    d = root / "2026-09-25" / "endfield"
    d.mkdir(parents=True)
    (d / f"{STEM}.json").write_text(json.dumps({"maaend_result": "MaaEnd 部分任务执行失败: 🎱基质刷取"},
                                               ensure_ascii=False), encoding="utf-8")
    (d / f"{STEM}.log").write_bytes((FIX / "maaend_bagfull_2026-09-25.log").read_bytes())
    return root


def maaend(with_notice: bool) -> Path:
    root = tmpdir()
    (root / "debug").mkdir(parents=True)
    body = (FIX / "maaend_bagfull_2026-09-25_maafw.log").read_bytes() if with_notice else b""
    (root / "debug" / "maafw.log").write_bytes(body)
    return root


def fetch(hist: Path, end: Path | None):
    cfg = Config()
    cfg.history_dir = hist
    cfg.maaend_dir = end
    recs = LocalSource(cfg).fetch(set())
    return recs[0] if len(recs) == 1 else None


def main() -> int:
    print("[09-25 through the collector, MaaEnd folder from Config]")
    rec = fetch(history(), maaend(with_notice=True))
    require("one record", rec is not None)
    if rec is None:
        print(f"FAILED {len(FAILED)}: {FAILED}")
        return 1
    causes = rec.raw.get("maaend_fail_causes") or {}
    require("still a failure", rec.ok is False and "基质刷取" in rec.failed_tasks,
            repr((rec.ok, rec.failed_tasks)))
    require("the full bag is found through the collector", causes.get("基质刷取") == BAG_FULL, repr(causes))
    require("the alarm text says to clear the bag", "清出背包空间" in texts.known_cause(causes),
            texts.known_cause(causes))
    require("the make-up clears the bag first",
            makeup.plan_maaend({"instances": [{"tasks": [{"taskName": makeup.STASH},
                                                         {"taskName": "AutoEssence", "customName": "基质刷取"}]}]},
                               ["基质刷取"], causes, {})[0][:1] == [makeup.STASH], repr(causes))

    print("[the same run when the framework log has no notice: reported, unconfirmed]")
    bare = fetch(history(), maaend(with_notice=False))
    bc = (bare.raw.get("maaend_fail_causes") or {}) if bare else {}
    require("still a failure", bare is not None and bare.ok is False and "基质刷取" in bare.failed_tasks)
    require("the click-then-fail is kept, as unconfirmed", bc.get("基质刷取") == CLAIM_UNCONFIRMED, repr(bc))
    line = core._fmt_failed(bare.raw.get("tasks_failed") or [], causes=bc) if bare else ""
    require("the alert line says what was seen", CLAIM_UNCONFIRMED in line, line)
    advice = texts.known_cause(bc)
    require("the advice does not claim a full bag", "清出背包空间" not in advice and "仓储已满" in advice, advice)
    require("the advice passes the plain-words gate", not texts.plain(advice), repr(texts.plain(advice)))
    require("the make-up does not clear the bag on an unconfirmed cause",
            makeup.STASH not in makeup.plan_maaend(
                {"instances": [{"tasks": [{"taskName": makeup.STASH},
                                          {"taskName": "AutoEssence", "customName": "基质刷取"}]}]},
                ["基质刷取"], bc, {})[0], repr(bc))
    nodir = fetch(history(), None)
    require("no MaaEnd folder at all: still reported as unconfirmed",
            nodir is not None and (nodir.raw.get("maaend_fail_causes") or {}).get("基质刷取") == CLAIM_UNCONFIRMED)

    print("[evening recompute (report): a proven full bag is not downgraded]")
    hist = history()
    entry = {"run_id": f"2026-09-25/endfield/{STEM}", "script": "MaaEnd", "ok": False,
             "failed_tasks": ["基质刷取"], "raw": {"maaend_fail_causes": {"基质刷取": BAG_FULL}}}
    later = collector.refresh_raw(entry, hist, maaend(with_notice=False))
    require("debug folder wiped since: still 背包满了",
            (later["raw"].get("maaend_fail_causes") or {}).get("基质刷取") == BAG_FULL, repr(later["raw"]))
    fresh = collector.refresh_raw(dict(entry, raw={}), hist, maaend(with_notice=True))
    require("an old entry without the cause gets it from the framework log",
            (fresh["raw"].get("maaend_fail_causes") or {}).get("基质刷取") == BAG_FULL, repr(fresh["raw"]))

    # The daily report's recompute hands the MaaEnd folder on.
    seen: list = []

    class Stop(Exception):
        pass

    def spy(e, hist_dir, end_dir=None):
        seen.append(end_dir)
        raise Stop

    class Eng:
        cfg = Config()

    Eng.cfg.history_dir = hist
    Eng.cfg.maaend_dir = Path("/maaend")
    real, collector.refresh_raw = collector.refresh_raw, spy
    try:
        report._compose_daily(Eng(), "2026-09-25", [entry])
    except Stop:
        pass
    finally:
        collector.refresh_raw = real
    require("the daily report recomputes with the MaaEnd folder", seen == [Path("/maaend")], repr(seen))

    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: {FAILED}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
