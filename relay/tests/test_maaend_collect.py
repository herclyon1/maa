"""MaaEnd's gathering: a full bag (and its gathering), the close-game wrap-up, collect items v2.36, Xianlu, farm drops, two farms.

One part per former file, each run on its own (tests/_parts.py): test_maaend_bagfull.py, test_maaend_bagfull_collect.py, test_maaend_close_game_wrapup.py, test_maaend_collect_items_v236.py, test_maaend_collect_xianlu.py, test_maaend_farm_drops.py, test_maaend_two_farms.py.
"""
from __future__ import annotations

# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_maaend_bagfull():
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

    Formerly test_maaend_bagfull.py.
    """
    #!/usr/bin/env python3

    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.verify import collector_maaend as cm
    from ark_relay.core import texts
    from ark_relay.core import ledger as core
    from ark_relay.features.verify.collector_maaend import CLAIM_UNCONFIRMED, parse_maaend_log
    from ark_relay.core.config import SERVER_TZ, RunRecord

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


def _part_maaend_bagfull_collect():
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

Also: without the framework log the click-then-fail is still reported - as an
ordinary failure carrying the raw lines around the claim (since 2026-10-06; it was a
softened 「unconfirmed」 cause before), never silently dropped - and the evening
recompute does not downgrade a full bag proven at bookkeeping time once MaaEnd has
wiped its debug folder.

    Formerly test_maaend_bagfull_collect.py.
    """
    #!/usr/bin/env python3

    import json
    import os


    os.environ.update(ARK_STATE_DIR=str(tmpdir()), ARK_AUTOMAS_DIR="", ARK_MAAEND_DIR="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import collector, texts
    from ark_relay.features.makeup import makeup
    from ark_relay.features.report import report
    from ark_relay.core import ledger as core
    from ark_relay.features.verify.collector_maaend import BAG_FULL, CLAIM_UNCONFIRMED
    from ark_relay.core.config import Config
    from ark_relay.core.transport import LocalSource

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
        bag_full = getattr(makeup, "bag_full", lambda c: None)
        require("the make-up clears the bag first", bag_full(causes) is True, repr(causes))

        print("[the same run when the framework log has no notice: an ordinary failure with its raw lines]")
        bare = fetch(history(), maaend(with_notice=False))
        bc = (bare.raw.get("maaend_fail_causes") or {}) if bare else {}
        require("still a failure", bare is not None and bare.ok is False and "基质刷取" in bare.failed_tasks)
        require("no cause is named (no softened 「unconfirmed」)", bc == {}, repr(bc))
        line = core._fmt_failed(bare.raw.get("tasks_failed") or [], causes=bc) if bare else ""
        require("the alert line is the plain failure", line == "失败于：赠送干员礼物、基质刷取、日常奖励领取", line)
        require("no bag advice", texts.known_cause(bc) == "", texts.known_cause(bc))
        claim = ((bare.raw.get("maaend_claim_lines") or {}).get("基质刷取") or {}) if bare else {}
        require("the raw run-log lines travel with the record",
                claim.get("run") == ["[2026-09-25 09:53:13.162] 👆点击确认领取按钮",
                                     "[2026-09-25 09:53:38.147] 任务失败: 🎱基质刷取"], repr(claim))
        _, body = core.format_failure(bare) if bare else ("", "")
        require("... and reach the failure text", "[2026-09-25 09:53:13.162] 👆点击确认领取按钮" in body, body)
        require("the make-up does not clear the bag without the notice", bag_full(bc) is False, repr(bc))
        nodir = fetch(history(), None)
        require("no MaaEnd folder at all: still a failure, raw lines attached, no cause",
                nodir is not None and not nodir.raw.get("maaend_fail_causes")
                and bool(((nodir.raw.get("maaend_claim_lines") or {}).get("基质刷取") or {}).get("run")))
        old = {"基质刷取": CLAIM_UNCONFIRMED}
        require("a ledger line from before 2026-10-06 is shown as a plain failure too",
                (core._fmt_failed(["基质刷取"], causes=old), texts.known_cause(old)) == ("失败于：基质刷取", ""),
                repr((core._fmt_failed(["基质刷取"], causes=old), texts.known_cause(old))))

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


def _part_maaend_close_game_wrapup():
    """关闭游戏（PC） is the round's wrap-up step, not a daily task.

The fixture is the real 2026-10-12 MaaEnd-14-25-41 ledger record: tasks_done
['日常奖励领取', '关闭游戏（PC）'], 关闭游戏 with no log evidence and no task picture.
Before, the report counted it as a daily task and called it 「没证据，不算完成」
(and pushes.py sends that list to the group); a gathering-only record holding it
was not recognised as gathering-only either.

    Formerly test_maaend_close_game_wrapup.py.
    """
    #!/usr/bin/env python3
    import json
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import ledger_report, ledger_rows
    from ark_relay.core.config import SERVER_TZ


    e = json.loads((Path(__file__).parent / "fixtures" / "ledger-1012-maaend-close-game.jsonl").read_text(encoding="utf-8"))
    raw = e["raw"]
    check("not unverified", ledger_rows.maaend_unverified(raw), [])
    check("not listed", ledger_rows._maaend_listed(raw), ["日常奖励领取"])
    notes = ledger_rows._block_maaend(e, raw, datetime(2026, 10, 12, 18, 28, tzinfo=SERVER_TZ))[4]
    check("notes name the daily task only", notes, ["做了 日常奖励领取"])

    gather = {"ok": True}
    graw = {"maaend_collect_skipped": "周日", "tasks_done": ["自动采集", "关闭游戏（PC）"]}
    check("gathering-only with 关闭游戏", ledger_report._skipped_gathering_only(gather, graw), True)


def _part_maaend_collect_items_v236():
    """MaaEnd v2.36.0-beta.5 picks 自动采集 by item, not by route (installed 2026-10-29 10:27 Beijing).

Real files from that release (tasks/AutoCollect.json and the zh_cn locale, fetched from MaaEnd/MaaEnd at the
tag). The four *Routes checkboxes became *Items checkboxes; the relay logged eight 「没有中文名」 warnings and
the gathering retry stopped recognising failures (账本 #122). Checked here:
- the master's route picks become the items those routes gathered (route 7 gathered two);
- the phone page lists the item lists with Chinese names and real choices, nothing untranslated;
- the retry reads v2.36's failure texts and keeps only the failed item's nodes in its override.

    Formerly test_maaend_collect_items_v236.py.
    """
    import json
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import mastercfg
    from ark_relay.features.makeup import collect_retry as cr
    from ark_relay.features.verify import collector_maaend as cm, outcome

    FIX = Path(__file__).parent / "fixtures" / "maaend-2026-10-29"


    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        maaend = d / "maaend"
        (maaend / "tasks").mkdir(parents=True)
        (maaend / "locales" / "interface").mkdir(parents=True)
        (maaend / "tasks" / "AutoCollect.json").write_bytes((FIX / "tasks" / "AutoCollect.json").read_bytes())
        (maaend / "locales" / "interface" / "zh_cn.json").write_bytes(
            (FIX / "locales" / "interface" / "zh_cn.json").read_bytes())
        (maaend / "interface.json").write_text(json.dumps({"import": ["tasks/AutoCollect.json"]}), encoding="utf-8")
        automas = d / "automas"
        cfgdir = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfgdir.mkdir(parents=True)
        master = cfgdir / "mxu-MaaEnd.json"
        old = {
            "AutoCollectValleyIV": {"type": "switch", "value": True},
            "AutoCollectValleyIVRareRoutes": {"type": "checkbox", "caseNames": ["Route4", "Route13"]},
            "AutoCollectValleyIVCommonRoutes": {"type": "checkbox", "caseNames": ["CommonRoute1"]},
            "AutoCollectWuling": {"type": "switch", "value": True},
            "AutoCollectWulingRareRoutes": {"type": "checkbox", "caseNames": ["Route7", "Route15", "Route99"]},
            "AutoCollectWulingCommonRoutes": {"type": "checkbox", "caseNames": ["CommonRoute5"]},
            "AutoCollectMode": {"type": "select", "caseName": "Always"},
        }
        master.write_text(json.dumps({"instances": [{"tasks": [
            {"taskName": "AutoCollect", "enabled": True, "optionValues": old}]}]}), encoding="utf-8")

        changes, note = mastercfg.migrate_maaend_options(automas, maaend)
        print("\n".join("    " + c for c in changes))
        ov = json.loads(master.read_text(encoding="utf-8"))["instances"][0]["tasks"][0]["optionValues"]
        check("四号谷地稀有：路线4、13 → 纯晶多齿叶、中黯石",
              ov.get("AutoCollectValleyIVRareItems", {}).get("caseNames"),
              ["item_plant_crylplant_1_2", "item_plant_spcstone_1_2"])
        check("四号谷地一般：线路1 → 映火荞花", ov.get("AutoCollectValleyIVCommonItems", {}).get("caseNames"),
              ["item_plant_moss_spc_1"])
        check("武陵稀有：路线7 → 血菌和武陵石两样，路线15 → 红矛叶",
              ov.get("AutoCollectWulingRareItems", {}).get("caseNames"),
              ["item_plant_mushroom_2_1", "item_plant_spcstone_2_2", "item_plant_crylplant_2_3"])
        check("武陵一般：线路5 → 蓬茸锦草", ov.get("AutoCollectWulingCommonItems", {}).get("caseNames"),
              ["item_plant_grass_spc_1"])
        check("旧的路线项都去掉了", [k for k in ov if k.endswith("Routes")], [])
        check("对不上的路线（Route99）在说明里点了名", any("Route99" in c for c in changes))
        check("区域开关和模式原样留着", (ov["AutoCollectValleyIV"], ov["AutoCollectMode"]["caseName"]),
              ({"type": "switch", "value": True}, "Always"))

        r = mastercfg.read_maaend(automas, maaend)
        A = "AutoCollect/"
        for k in ("AutoCollectValleyIVRareItems", "AutoCollectValleyIVCommonItems",
                  "AutoCollectWulingRareItems", "AutoCollectWulingCommonItems"):
            check(f"手机页有 {k}，中文名", any("一" <= ch <= "鿿" for ch in r["labels"].get(A + k, "")))
        check("手机页没有没翻译的项", [k for k in r.get("untranslated", []) if k.startswith(A)], [])
        names = dict((v, n) for n, v in r["options"][A + "AutoCollectWulingRareItems"])
        check("武陵稀有的可选值带中文名", (names.get("item_plant_mushroom_2_1"), names.get("item_plant_spcstone_2_2")),
              ("血菌", "武陵石"))

        zh = json.loads((FIX / "locales" / "interface" / "zh_cn.json").read_text(encoding="utf-8"))
        labels = cr.failed_labels_from_locale(zh)
        check("补跑认得新版失败提示", labels.get("纯晶多齿叶采集失败"), "AutoCollectValleyIVChrysodendra1")
        check("两样一条路线的也认得", labels.get("血菌、武陵石采集失败"), "AutoCollectWulingBloodcapWulingstone1")
        log = "[12:00:01] 纯晶多齿叶采集失败\n[12:03:00] 轻黯石采集失败\n[12:05:00] 星门菌采集失败\n"
        check("从日志里挑出失败的路线", cr.failed_routes(log, labels),
              ["AutoCollectValleyIVChrysodendra1", "AutoCollectValleyIVKalkonyx1", "AutoCollectWulingCosmagaric1"])
        parts = [{
            "__AutoCollectValleyIVChrysodendraDispatch": {"enabled": True},
            "__AutoCollectValleyIVChrysodendraSkipped": {"enabled": True},
            "AutoCollectValleyIVChrysodendra1Start": {"enabled": True},
            "__AutoCollectWulingCrimsonSpearleafDispatch": {"enabled": True},
            "__AutoCollectWulingCrimsonSpearleafSkipped": {"enabled": True},
            "AutoCollectWulingCrimsonSpearleaf1Start": {"enabled": True},
            "AutoCollectScheduleEnabled": {"attach": {"monday": True}},
        }]
        o = cr.build_override(parts, ["AutoCollectValleyIVChrysodendra1"], "thursday")
        check("补跑只留失败那样的调度和路线",
              sorted(k for k in o if "Chrysodendra" in k or "CrimsonSpearleaf" in k),
              ["AutoCollectValleyIVChrysodendra1Start", "__AutoCollectValleyIVChrysodendraDispatch",
               "__AutoCollectValleyIVChrysodendraSkipped"])
        check("今天是采集日", o["AutoCollectScheduleEnabled"]["attach"].get("thursday"), True)
        o2 = cr.build_override([{}], ["AutoCollectWulingCosmagaric1"], "thursday")
        check("日志里没有的那样也会补上调度入口", (o2.get("__AutoCollectWulingCosmagaricDispatch"),
                                             o2.get("AutoCollectWulingCosmagaric1Start")),
              ({"enabled": True}, {"enabled": True}))
        mf = ('[2026-10-29 12:00:00.000][INF] [msg=Node.Action.Starting] {"name":"__AutoCollectValleyIVChrysodendra1Failed"}\n'
              '[2026-10-29 12:00:05.000][INF] [msg=Node.Action.Starting] {"name":"AutoCollectWulingCosmagaric1End"}\n')
        check("补跑结论认新版节点", cr.judge(mf, ["AutoCollectValleyIVChrysodendra1", "AutoCollectWulingCosmagaric1"],
                                         "00:00:00"),
              {"AutoCollectValleyIVChrysodendra1": False, "AutoCollectWulingCosmagaric1": True})

        # Real 2026-11-02 morning MaaEnd-06-37-16 log lines (ledger #134): 16 item-named routes in 1654 s.
        log_1102 = "\n".join([
            "[2026-11-02 10:37:28.880] 开始执行任务, 数量: 1",
            "[2026-11-02 11:02:29.664] 任务开始: 🧺自动采集",
            "[2026-11-02 11:02:29.665] 正在前往四号谷地扫描拥有物资",
            "[2026-11-02 11:02:51.970] 正在前往武陵扫描拥有物资",
            "[2026-11-02 11:03:04.220] 仓库库存同步完成，开始按目标库存筛选采集物",
            "[2026-11-02 11:03:05.320] 采集纯晶多齿叶",
            "[2026-11-02 11:04:52.668] 采集轻黯石",
            "[2026-11-02 11:06:37.493] 采集轻红柱状菌",
            "[2026-11-02 11:07:39.258] 采集中黯石",
            "[2026-11-02 11:10:23.899] 采集晶化多齿叶",
            "[2026-11-02 11:11:23.671] 采集受蚀玉化叶",
            "[2026-11-02 11:13:02.786] 采集至晶多齿叶",
            "[2026-11-02 11:14:00.095] 采集血菌、武陵石",
            "[2026-11-02 11:17:37.438] 采集星门菌",
            "[2026-11-02 11:18:54.406] 采集燎石",
            "[2026-11-02 11:20:59.443] 采集重红柱状菌",
            "[2026-11-02 11:22:42.233] 采集重黯石",
            "[2026-11-02 11:24:21.668] 采集中红柱状菌",
            "[2026-11-02 11:25:10.574] 采集红矛叶",
            "[2026-11-02 11:26:26.877] 采集协议纹石",
            "[2026-11-02 11:28:24.733] 采集塔罗斯菌",
            "[2026-11-02 11:30:03.197] 任务完成: 🧺自动采集",
            "[2026-11-02 11:31:57.991] 自动执行任务完成",
        ])
        checks = {c.label: c.ok for c in outcome.maaend_checks(log_1102, [], own_log=True)}
        check("11-02 早班 16 条新版采集路线判为「自动采集 真的走了路线」", checks.get("自动采集 真的走了路线"), True)
        log_p = d / "0.log"
        log_p.write_text(log_1102, encoding="utf-8")
        parsed = cm.parse_maaend_log(log_p)
        check("11-02 早班路线计数 16/16", (parsed.get("maaend_collect_done"), parsed.get("maaend_collect_total")), (16, 16))

        shot = "2026.11.02-11.21.15.123___MapNavigatorObstacleDevice_InteractPost.png"
        check("新版路线撞上中继器能对上路线 ID",
              cr.blocked_route_ids(log_1102, [shot], zh),
              {"AutoCollectWulingRubyBolete1": [shot]})
        mf_blocked = (
            '[2026-11-02 11:20:59.400][INF] [msg=Node.Recognition.Succeeded] {"name":"AutoCollectWulingRubyBolete1Start"}\n'
            '[2026-11-02 11:22:40.000][INF] [msg=Node.Action.Starting] {"name":"AutoCollectWulingRubyBolete1End"}\n'
        )
        check("补跑复查认得新版路线节点窗口",
              cr.retry_blocked(mf_blocked, ["AutoCollectWulingRubyBolete1"], "11:00:00", [shot]),
              {"AutoCollectWulingRubyBolete1": [shot]})

    print("\nall checks passed" if not fails else f"\n{len(fails)} FAILED: {fails}")


def _part_maaend_collect_xianlu():
    """自动采集 walking only routes 1-3 is work done, not a false green.

MaaEnd spells its first routes 「线路N：」 (fixtures/maaend-collect-xianlu-1012.log:
the start, 线路1-3 and finish lines of 2026-10-12 MaaEnd-06-04-00.log). The work
check accepted only 「路线N：」, so a day with routes 1-3 alone would be red.

    Formerly test_maaend_collect_xianlu.py.
    """
    #!/usr/bin/env python3

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify.outcome import maaend_checks

    text = (Path(__file__).parent / "fixtures" / "maaend-collect-xianlu-1012.log").read_text(encoding="utf-8")
    got = {c.label: c.ok for c in maaend_checks(text, []) if "自动采集" in c.label}
    ok = got.get("自动采集 真的走了路线") is True
    print(("  ✓ " if ok else "  ✗ ") + f"线路1-3 count as walked routes: {got}")
    print("\n" + ("all checks passed" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


def _part_maaend_farm_drops():
    """MaaEnd farming drops read from its 「获得以下物品：」 blocks (2026-09-29).

MaaEnd prints a claim's items as a block whose item lines carry no 「获得」
(fixtures/maaend-farm-drops/2026-09-27.log lines 320-322: the header, then
one line per item with its count). `_maaend_farm` only knew 「是X基质」
lines and the single-line 「获得 X ×n」, so after the switch to 协议空间
`maaend_farm_drops` stayed empty and the daily report printed no output row.
Every log below is a real, unedited MaaEnd log from the machine
(fixtures/maaend-farm-drops/).

    Formerly test_maaend_farm_drops.py.
    """
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_maaend

    D = pathlib.Path(__file__).resolve().parent / "fixtures" / "maaend-farm-drops"


    def chk(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r}, want {want!r}")


    def farm(name):
        return collector_maaend._maaend_farm((D / name).read_text(encoding="utf-8"))


    def pick(d):
        """Farm name, place, runs and drops. Sanity is checked separately below,
    only for the Protocol Space logs, where it was worked out by hand."""
        keys = ("maaend_farm", "maaend_farm_place", "maaend_farm_runs", "maaend_farm_drops")
        return {k: d[k] for k in keys if k in d}


    def sanity(name):
        r = collector_maaend.parse_maaend_log(D / name)
        return {k: r.get(k) for k in ("maaend_sanity_spent", "sanity", "sanity_cap", "protocol_runs")}


    # Protocol Space, 2026-09-27 09:45: two entries, one claim that landed.
    # Line 317 reads 277, 318-319 claim, 320-322 the block; line 350 reads 117,
    # 351-352 claim, 353 「理智不足，结束任务」 with no block - refused. So one
    # run, 160 spent (277 -> 117), 117 left.
    # The exact dict also proves the 基建任务 / 信用点购物 / 选剑演武 /
    # 日常奖励领取 blocks of the same log (信用, 武库配额, 协议棱柱 …) stay out.
    chk("09-27 协议空间", pick(farm("2026-09-27.log")),
        {"maaend_farm": "协议空间", "maaend_farm_runs": 1,
         "maaend_farm_drops": {"折金票": 68000, "行动资历": 960}})
    chk("09-27 理智", sanity("2026-09-27.log"),
        {"maaend_sanity_spent": 160, "sanity": 117, "sanity_cap": 360, "protocol_runs": 2})

    # Protocol Space, 2026-09-28 10:46: two claims, both landed. Line 307 reads
    # 326, 310-312 block; line 339 reads 166, 342-344 block; 354 「理智不足，
    # 结束任务」 comes after the second block. 160 per run (326 -> 166), so 320
    # spent and 166 - 160 = 6 left.
    chk("09-28a 协议空间", pick(farm("2026-09-28a.log")),
        {"maaend_farm": "协议空间", "maaend_farm_runs": 2,
         "maaend_farm_drops": {"折金票": 136000, "行动资历": 1920}})
    chk("09-28a 理智", sanity("2026-09-28a.log"),
        {"maaend_sanity_spent": 320, "sanity": 6, "sanity_cap": 360, "protocol_runs": 2})

    # Negative: 2026-09-28 12:10:45 opened 协议空间 with 17 sanity, never got
    # 「进入协议空间成功」, and went straight on to 选剑演武.
    r = farm("2026-09-28b.log")
    chk("09-28b 没进去", pick(r), {"maaend_farm": "协议空间"})
    full = collector_maaend.parse_maaend_log(D / "2026-09-28b.log")
    chk("09-28b 次数", full.get("maaend_farm_runs"), None)
    chk("09-28b 产出", full.get("maaend_farm_drops"), None)
    chk("09-28b 理智不足", full.get("sanity_exhausted"), True)
    chk("09-28b 理智", sanity("2026-09-28b.log"),
        {"maaend_sanity_spent": None, "sanity": 17, "sanity_cap": 360, "protocol_runs": None})

    # Essence, 2026-09-24 10:09: two runs, ten 「是X基质」 lines, no block.
    chk("09-24 基质刷取", pick(farm("2026-09-24_MaaEnd-06-07-50.log")),
        {"maaend_farm": "基质刷取", "maaend_farm_place": "清波寨", "maaend_farm_runs": 2,
         "maaend_farm_drops": {"无暇基质": 6, "高纯基质": 4}})

    # Essence, 2026-09-25 09:44: the claim never landed (full bag), nothing counted.
    chk("09-25 基质刷取 背包满", pick(farm("2026-09-25_MaaEnd-05-25-36.log")),
        {"maaend_farm": "基质刷取", "maaend_farm_place": "清波寨"})

    # The same 09-27 log has plenty of blocks outside the farming task; the
    # block reader sees them, the farm reader must not.
    whole = collector_maaend._item_blocks((D / "2026-09-27.log").read_text(encoding="utf-8").splitlines())
    chk("09-27 全日 信用", whole.get("信用"), 20 + 400 + 300)
    chk("09-27 全日 武库配额", whole.get("武库配额"), 80)
    chk("09-27 产出不含信用", "信用" in (farm("2026-09-27.log").get("maaend_farm_drops") or {}), False)

    # Not tied to the task name: the same log with the task renamed is still read
    # as the farming task because its own lines carry 「当前理智 N/M」.
    t27 = (D / "2026-09-27.log").read_text(encoding="utf-8")
    renamed = t27.replace("⚔️协议空间", "⚔️某新理智玩法")
    chk("改名 仍认", pick(collector_maaend._maaend_farm(renamed)),
        {"maaend_farm": "某新理智玩法", "maaend_farm_runs": 1,
         "maaend_farm_drops": {"折金票": 68000, "行动资历": 960}})
    # Renamed and without the sanity readings: no farming task at all, and the
    # 基建任务 / 信用点购物 blocks do not turn into one.
    bare = "\n".join(x for x in renamed.splitlines() if "当前理智" not in x)
    chk("改名无理智行 不认", collector_maaend._maaend_farm(bare), {})

    # Block boundary: the first non-item line closes it, even at the same
    # timestamp; a framework line closes it too.
    lines = [
        "[2026-09-27 09:46:37.319] 获得以下物品：",
        "[2026-09-27 09:46:37.319] 折金票 ×68000",
        "[2026-09-27 09:46:37.319] 继续行动",
        "[2026-09-27 09:46:37.319] 行动资历 ×960",
        "[2026-09-27 09:46:38.000] 获得以下物品：",
        "[2026-09-27 09:46:38.000] 信用 ×20",
        "[2026-09-27 09:46:38.001][ERR][Px1][Tx1][A.cpp][L1][f] size x 16",
        "[2026-09-27 09:46:38.002] 信用 ×400",
    ]
    chk("块边界", collector_maaend._item_blocks(lines), {"折金票": 68000, "信用": 20})

    if fails:
        print("\n".join(fails)); sys.exit(1)
    print("all checks passed")


def _part_maaend_two_farms():
    """Both sanity tasks in one round are both read.

ProtocolSpace sits before AutoEssence and the phone page can switch each on
(mastercfg `@enabled`). No real round has run both yet, so the round here is
two real segments back to back: the 协议空间 task of
fixtures/maaend-farm-drops/2026-09-27.log and the 基质刷取 task of
2026-09-24_MaaEnd-06-07-50.log, each from its 「任务开始」 to its own end line.
Before 2026-10-06 only the first was read: the essence runs and drops vanished.

    Formerly test_maaend_two_farms.py.
    """
    #!/usr/bin/env python3


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.verify import collector_maaend as cm

    FAILED: list[str] = []
    D = Path(__file__).resolve().parent / "fixtures" / "maaend-farm-drops"


    def require(name: str, ok: bool, detail: str = "") -> None:
        print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  -- {detail}"))
        if not ok:
            FAILED.append(name)


    def _task(path: Path, key: str) -> str:
        lines = path.read_text(encoding="utf-8").splitlines()
        a = next(i for i, x in enumerate(lines) if "任务开始" in x and key in x)
        b = next(i for i, x in enumerate(lines) if i > a and ("任务完成" in x or "任务失败" in x) and key in x)
        return "\n".join(lines[a:b + 1]) + "\n"


    def main() -> int:
        ps = _task(D / "2026-09-27.log", "协议空间")
        ess = _task(D / "2026-09-24_MaaEnd-06-07-50.log", "基质刷取")
        one_ps, one_ess = cm._maaend_farm(ps), cm._maaend_farm(ess)
        both = cm._maaend_farm(ps + ess)
        require("each part alone farmed something", one_ps.get("maaend_farm_runs") and one_ess.get("maaend_farm_runs"),
                repr((one_ps, one_ess)))
        require("both tasks are named", both.get("maaend_farm") == "协议空间、基质刷取", repr(both.get("maaend_farm")))
        require("runs add up", both.get("maaend_farm_runs") ==
                one_ps["maaend_farm_runs"] + one_ess["maaend_farm_runs"], repr(both.get("maaend_farm_runs")))
        want = dict(one_ps.get("maaend_farm_drops") or {})
        for k, n in (one_ess.get("maaend_farm_drops") or {}).items():
            want[k] = want.get(k, 0) + n
        require("drops of both are kept", both.get("maaend_farm_drops") == want, repr(both.get("maaend_farm_drops")))
        require("a single task reads as before", cm._maaend_farm(ps) == one_ps)
        print()
        if FAILED:
            print(f"FAILED {len(FAILED)}: {FAILED}")
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())


if __name__ == "__main__":
    sys.exit(run_parts([_part_maaend_bagfull, _part_maaend_bagfull_collect, _part_maaend_close_game_wrapup, _part_maaend_collect_items_v236, _part_maaend_collect_xianlu, _part_maaend_farm_drops, _part_maaend_two_farms]))
