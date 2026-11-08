"""M6, the run counts and sanity spent against the real 09-20..22 logs; and the OK-WW report fixes on the machine's own logs.

One part per former file, each run on its own (tests/_parts.py): test_m6_counts.py, test_m6_okww.py.
"""
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


def _part_m6_counts():
    """M6 (2026-09-23): run counts and sanity spent against the real 09-20..22 logs.

* MAA: a drop block line with no "(+N)" ("酯原料 : 2") ended the block, so the
  "当前次数" after it was lost - 1-7 farmed 19 times was reported x10.
  The count now comes from MAA's own "开始行动 a~b 次" numbering.
* MaaEnd: five runs read 237/158/78/38/38/39; median step 79 gave "395"
  for 5 x 80 = 400.

    Formerly test_m6_counts.py.
    """
    import sys, pathlib, tempfile
    from datetime import datetime, timedelta
    from unittest import mock
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_maa, collector_maaend
    from ark_relay.core import plan
    from ark_relay.features.weekly import annihilation
    from ark_relay.core.config import SERVER_TZ


    def chk(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r}, want {want!r}")

    # history/2026-09-20/arknights/MAA-05-00-01.log lines 86-114 (report headers dropped)
    maa = """[2026-09-20 09:02:43.459][INF][TaskQueueViewModel]     <2> 开始行动 1~10 次, -60理智
理智: 117/210
[2026-09-20 09:04:10.692][INF][TaskQueueViewModel]     <2> 1-7 掉落统计: 
龙门币 : 720 (+720)
固源岩 : 14 (+14)
基础作战记录 : 13 (+13)
酯原料 : 2 (+2)
破损装置 : 2 (+2)
当前次数 : 10
[2026-09-20 09:04:26.536][INF][TaskQueueViewModel]     <2> 开始行动 11~19 次, -54理智
理智: 57/210
[2026-09-20 09:05:53.031][INF][TaskQueueViewModel]     <2> 1-7 掉落统计: 
龙门币 : 1368 (+648)
基础作战记录 : 26 (+13)
固源岩 : 23 (+9)
破损装置 : 3 (+1)
双酮 : 1 (+1)
赤金 : 1 (+1)
酯原料 : 2
当前次数 : 9
[2026-09-20 09:06:15.563][INF][TaskQueueViewModel]     <2> 完成任务: 理智作战
"""
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "maa.log"
        f.write_text(maa, encoding="utf-8")
        r = collector_maa.parse_maa_log(f)
        chk("方舟 09-20 早 次数", r.get("run_times"), 19)
        chk("方舟 09-20 早 理智", r.get("sanity_spent"), 114)
        chk("方舟 09-20 早 酯原料", r.get("drop_statistics", {}).get("酯原料"), 2)
        chk("方舟 09-20 早 龙门币", r.get("drop_statistics", {}).get("龙门币"), 1368)
        # "开始行动 21 次" (single run) counts too - 09-20 21:36:28
        f.write_text(maa + "[2026-09-20 21:36:28.217][INF][TaskQueueViewModel]     <2> 开始行动 20~21 次, -12理智\n", encoding="utf-8")
        chk("方舟 单趟编号", collector_maa.parse_maa_log(f).get("run_times"), 21)

    end = "\n".join([
        "[2026-09-22 09:47:29.620] 任务开始: 🎱基质刷取",
        *[f"[2026-09-22 09:4{i}:00.000] 当前理智 {v}/360" for i, v in enumerate([237, 158, 78, 38, 38, 39])],
        *["[2026-09-22 09:50:42.245] ✅已完成一次基质刷取"] * 5,
        "[2026-09-22 09:58:39.769] 任务完成: 🎱基质刷取",
    ])
    chk("终末地 09-22 理智", collector_maaend._maaend_farm(end).get("maaend_sanity_spent"), 400)

    # plan: gathering routes live under per-region keys since MaaEnd split them
    # (mxu-MaaEnd.json 2026-09-23: ValleyIV rare 5 + Wuling rare 12 = 17 walked 09-21)
    ov = {
        "AutoCollectValleyIV": {"type": "switch", "value": True},
        "AutoCollectValleyIVRareRoutes": {"caseNames": ["Route4", "Route5", "Route6", "Route13", "Route14"]},
        "AutoCollectValleyIVCommonRoutes": {"caseNames": []},
        "AutoCollectWuling": {"type": "switch", "value": True},
        "AutoCollectWulingRareRoutes": {"caseNames": [f"Route{i}" for i in (1, 2, 3, 7, 8, 9, 10, 11, 12, 15, 16, 17)]},
        "AutoCollectSchedule": {"caseNames": ["AutoCollectScheduleMonday"]},
    }
    chk("采集路线 新两键", plan._collect_route_count(ov), 17)
    ov["AutoCollectWuling"]["value"] = False
    chk("采集路线 关掉的区不算", plan._collect_route_count(ov), 5)
    chk("采集路线 旧键仍认", plan._collect_route_count({"AutoCollectRoutes": {"caseNames": ["a", "b"]}}), 2)

    # plan: tomorrow's annihilation follows AUTO-MAS's week record
    # (Data.AnnihilationCompletedWeek) since the 2026-10-11 hand-over, item 13.
    sun = datetime(2026, 9, 20, 21, 0, tzinfo=SERVER_TZ)
    done_this_week = {"Info": {"Annihilation": "Annihilation"},
                      "Data": {"AnnihilationCompletedWeek": annihilation.week_key(sun)}}
    with mock.patch.object(annihilation, "_maa_user", lambda d: done_this_week):
        with mock.patch.object(plan, "_tomorrow", lambda: sun + timedelta(days=1)):
            chk("周日排周一 剿灭照打（新的一周）", plan._annihilation_done_tomorrow(pathlib.Path("automas")), False)
        with mock.patch.object(plan, "_tomorrow", lambda: sun - timedelta(days=2)):
            chk("周五排周六 本周已打满", plan._annihilation_done_tomorrow(pathlib.Path("automas")), True)

    if fails:
        print("\n".join(fails)); sys.exit(1)
    print("all checks passed")


def _part_m6_okww():
    """M6 OK-WW report fixes, replayed on the machine's own logs (slices under
fixtures/m6-okww, cut from the 09-21 and 09-22 runs pulled back on 09-23).

- 09-21 weekly boss: the Teleport-to-Boss key is logged before the book opens;
  the run never got in (no start-challenge button, then Teleport to boss
  failed) and used to be reported as fought-but-unclaimed.
- 09-22 weekly boss: read 0/3 before entering and skipped - full, but not by
  this run.
- 09-21 tacet: the reward dialog showed 180 left, OK-WW read 0 (reserve 240)
  and stopped. The correction from the dialog's 「剩余 N」 was deleted on
  2026-10-13 (audit item 13): none of the real dialog lines the override logs
  carries 「剩余」, so it never applied; the last reading is reported as such.

    Formerly test_m6_okww.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww as c, outcome as o

    FX = Path(__file__).resolve().parent / "fixtures" / "m6-okww"
    bad = []


    def check(label, got, want):
        print(("  ✓ " if got == want else "  ✗ ") + label + ("" if got == want else f": got {got!r}, want {want!r}"))
        if got != want:
            bad.append(label)


    r = c.parse_okww_log(FX / "0921-weekly.log")
    t = (FX / "0921-weekly.log").read_text(encoding="utf-8")
    # 「等了 10 秒」: the timeout line is 0.6 s before the header but more than 600
    # characters back (collector_okww._wait_before, audit 2026-10-13 item 8).
    check("09-21 失败原因不再说「没能退出副本」", r.get("okww_error"), "周本：选了等级后没等到「开启挑战」，没进本，一次没打（等了 10 秒）")
    check("09-21 步骤：没进本", [s for s in r.get("okww_steps", []) if "周本" in s], ["周本（没进本，一次没打，原因见失败于）"])
    check("09-21 核对：没进本不说「打了」",
          [(k.label, k.ok, k.detail) for k in o.okww_checks(t, expect_nest=False) if "周本" in k.label],
          [("周本", False, "没进本，一次没打：选了等级后没等到「开启挑战」")])

    r = c.parse_okww_log(FX / "0922-weekly.log")
    t = (FX / "0922-weekly.log").read_text(encoding="utf-8")
    check("09-22 0/3：说清不是这一趟领的", [s for s in r.get("okww_steps", []) if "周本" in s],
          ["周本（已完成：进本前读到本周 0/3，早已领满，这一趟没领）"])
    check("09-22 0/3 仍算本周已完成（每周记账看「已完成」）", "已完成" in r["okww_steps"][0], True)
    check("09-22 核对不报错", all(k.ok for k in o.okww_checks(t, expect_nest=False) if "周本" in k.label), True)

    tacet = (FX / "0921-tacet.log").read_text(encoding="utf-8")
    p = FX.parent.parent / "_m6_tacet_tmp.log"
    try:
        p.write_text(tacet, encoding="utf-8")
        r = c.parse_okww_log(p)
        check("没有领奖框原文时照旧：最后一次读数 0", (r.get("okww_stamina_left"), r.get("okww_stamina_left_exact")), (0, False))
    finally:
        p.unlink(missing_ok=True)

    if bad:
        print("FAILED: " + ", ".join(bad))
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    sys.exit(run_parts([_part_m6_counts, _part_m6_okww]))
