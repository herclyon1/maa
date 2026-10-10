"""Machine checks judged from a run record (ark_relay/machinechecks/runs.py, event 「run」).

The user, 2026-10-06 04:59: the open ledger items must be confirmed by the machine
after a deploy, not by a person reading logs. Each check here gets a recorded or
realistic run (PASS, nothing pushed) and a broken one (FAIL, pushed to the group),
and handle._handle is driven once per script to show the wiring: the verdict lands
in state/machinecheck.json right after the record is booked.
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
(TMP / "history").mkdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_STATE_DIR=str(TMP / "state"),
                  SERVERCHAN_KEY="", ARK_LLM_KEY="", WECOM_CORPID="", WECOM_SECRET="",
                  WECOM_BOT_URL="", ARK_PHONE_TOPIC="", ARK_LOG_FILE=str(TMP / "relay.log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import alertlog, collect_retry, collector_maaend, handle, okww_overlay, outcome, texts  # noqa: E402
from ark_relay import engine as eng_mod  # noqa: E402
from ark_relay import machinecheck as mc  # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.ledger import State  # noqa: E402
from ark_relay.notify import route_of  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class N:
    """A notifier that keeps a copy of every group alarm, as notify.Notifier does (alertlog.py)."""

    def __init__(self, state_dir=None, refuse=False):
        self.sent = []
        self.state_dir = state_dir
        self.refuse = refuse

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body, alert))
        if self.refuse:
            return ["企业微信机器人: 45009"]
        if self.state_dir and route_of(title, alert=alert) == "group":
            alertlog.AlertLog(self.state_dir).record(title, body)
        return []

    def send_group(self, title, body=""):
        return self.send(title, body, alert=True)


mc.load()
NOW = datetime(2026, 10, 6, 21, 40, tzinfo=SERVER_TZ)


def judge(cid, ctx, state=None):
    """(status, evidence, pushed titles) of check `cid` on `ctx`; status None when it said nothing."""
    state = state or tmpdir()
    n = N()
    got = dict(mc.judge(state, "run", dict(ctx), notifier=n, now=NOW))
    r = got.get(cid)
    pushed = [t for t, _, a in n.sent if a and t.startswith(texts.machinecheck_failed(cid, ""))]
    if r is not None:
        print(f"    {cid} {r.status}: {r.evidence}")
    return (r.status if r else None), (r.evidence if r else ""), pushed


def rec(script, run_id, started, ok=True, raw=None, minutes=30, failed=None):
    return RunRecord(run_id=run_id, script=script, user={"MaaEnd": "endfield", "OK-WW": "wuwa"}.get(script, "ark"),
                     started=started, finished=started + timedelta(minutes=minutes), ok=ok,
                     failed_tasks=list(failed or []), raw=dict(raw or {}))


def ww(lines, day="2026-10-06"):
    """OK-WW log lines as AUTO-MAS keeps them (tests/replay/2026-09-07/wuwa)."""
    return "\n".join(f"{day} 09:{20 + i // 60:02d}:{i % 60:02d},100 INFO TaskExecutor {x}" for i, x in enumerate(lines))


WWREC = rec("OK-WW", "2026-10-06/wuwa/OK-WW-05-19-17", datetime(2026, 10, 6, 9, 19, 17, tzinfo=SERVER_TZ))


def wwctx(lines, **kw):
    return dict({"rec": WWREC, "raw": {}, "log_text": ww(lines)}, **kw)


# ------------------------------------------------------------------ #4
print("\n[#4 周本领奖：领完回读到少了一次才算]")
WEEKLY_IN = ["FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0",
             "FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：3/3_1.00, x60_0.79]",
             "FarmEchoTask:teleport_to_boss prepared as realm", "FarmEchoTask:enter combat None",
             "FarmEchoTask:周本领奖：打完了，去结晶按 F", "FarmEchoTask:周本领奖：认出弹窗，点确认。读到 …",
             "FarmEchoTask:周本领奖：已点确认"]
st, ev, pushed = judge("#4", wwctx(WEEKLY_IN + ["FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3"]))
check("read-back dropped: PASS, nothing pushed", (st, pushed), ("PASS", []))
check("evidence is the read-back line", "回读确认领到，本周剩余 3/3→2/3" in ev)
st, ev, pushed = judge("#4", wwctx(WEEKLY_IN + ["FarmEchoTask:周本领奖：回读次数没变（3/3），这次没领到"]))
check("read-back unchanged: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
check("evidence says it was not claimed", "没领到" in ev)
st, ev, _ = judge("#4", wwctx(WEEKLY_IN[:3] + ["FarmEchoTask:周本领奖：这一圈没打起来（进场后一直没进战斗），不去找结晶"]))
check("10-05 shape (in, never fought): FAIL", st, "FAIL")
check("…saying it never fought", "没有开打" in ev)
st, _, _ = judge("#4", wwctx(["FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0",
                              "FarmEchoTask:本周周本次数已领满（0/3），不进本，跳过"]))
check("week already capped: not judged", st, None)
st, _, _ = judge("#4", wwctx(WEEKLY_IN + ["FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3"],
                             raw={"hand_started": "task-1"}))
check("a run a person started: not judged (only unattended runs count)", st, None)
st, _, _ = judge("#4", wwctx(["DailyTask:open_daily"]))
check("no weekly boss in the run: not judged", st, None)

# ------------------------------------------------------------------ #27
print("\n[#27 周本「确认前往」后读屏认出选等级页]")
DIALOG = ["FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0",
          "FarmEchoTask:限时提前开放的剧情提示框，点确认前往。框里读到：提前到达目标位置可能影响剧情体验，是否确认前往？"]
st, ev, pushed = judge("#27", wwctx(DIALOG + [
    "FarmEchoTask:限时提前开放：确认后是这个 Boss 的选等级页，按正常进本走（选等级→单人挑战→开启挑战）。整屏读到 定序诸理之律 推荐等级40-90 单人挑战",
    "FarmEchoTask:teleport_to_boss prepared as realm", "FarmEchoTask:enter combat None"]))
check("level page read, then a fight: PASS", (st, pushed), ("PASS", []))
check("evidence names the level page", "选等级页" in ev)
st, ev, pushed = judge("#27", wwctx(DIALOG + [
    "FarmEchoTask:进本：限时提前开放确认后（in_world=True）这一屏认不出，停下不走（不去大世界走路）。整屏读到 终端"]))
check("screen not recognised after the dialog: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
check("evidence is the stop line", "这一屏认不出" in ev)
st, ev, _ = judge("#27", wwctx(DIALOG + [
    "FarmEchoTask:限时提前开放：确认后是这个 Boss 的选等级页，按正常进本走（选等级→单人挑战→开启挑战）。整屏读到 …",
    "FarmEchoTask:周本：补点单人挑战 3 次都没进开启挑战"]))
check("page read but never got in: FAIL", st, "FAIL")
st, _, _ = judge("#27", wwctx(WEEKLY_IN))
check("no dialog this run: not judged", st, None)

# ------------------------------------------------------------------ #5 / #25 / #26
print("\n[#5 只刷指定点位的改动贴上了]")
NEST = {"checks": [], "msg": None, "expect_nest": True, "only_nest": "落渊南丘"}
NEST_OK = ["NightmareNestTask:open_boss_book canxiang", "NightmareNestTask:opened gray_book_boss",
           "NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）",
           "NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2",
           "NightmareNestTask:nightmare nest: 点进点位 41:3（截图 nest_go）", "NightmareNestTask:enter combat None"]
st, ev, pushed = judge("#5", wwctx(NEST_OK, outcome=NEST))
check("filter announced: PASS", (st, pushed), ("PASS", []))
check("evidence is the filter line", "只刷 ['落渊南丘']" in ev)
st, ev, pushed = judge("#5", wwctx(["NightmareNestTask:nightmare nest: 只刷指定点位的改动没装上，这一轮不刷巢穴"], outcome=NEST))
check("not installed: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
st, ev, _ = judge("#5", wwctx(["NightmareNestTask:opened gray_book_boss",
                               "NightmareNestTask:left_click 已击败残象：0/48 (1729, 347) after_sleep 2"], outcome=NEST))
check("list opened with no filter line (10-04 / 10-05): FAIL", st, "FAIL")
st, _, _ = judge("#5", wwctx(NEST_OK, outcome=dict(NEST, only_nest="")))
check("no 「only these nests」 setting: not judged", st, None)

print("\n[#25 残象聚落只认战斗]")
TEN05 = ["NightmareNestTask:opened gray_book_boss", "NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）",
         "NightmareNestTask:Box(已击败残象：0/48) is not complete",
         "NightmareNestTask:nightmare nest unreachable, skip this run: go_nest:48:18"]
good = outcome.okww_checks(ww(TEN05), expect_nest=True, only_nest="落渊南丘")
st, ev, pushed = judge("#25", wwctx(TEN05, outcome=dict(NEST, checks=good), raw={"okww_steps": ["残象聚落（开了界面就退出，一次没打）"]}))
check("10-05 morning with today's verdict (not farmed): PASS", (st, pushed), ("PASS", []))
check("evidence says it was not counted", "没记成刷了" in ev)
old = [outcome.Check("残象聚落", True, "有进本/战斗记录")]       # the verdict before 10-05 14:27
st, ev, pushed = judge("#25", wwctx(TEN05, outcome=dict(NEST, checks=old), raw={"okww_steps": ["残象聚落"]}))
check("the same morning booked as farmed (the old verdict): FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
check("evidence quotes the nest's last line", "unreachable" in ev)
st, ev, _ = judge("#25", wwctx(NEST_OK, outcome=dict(NEST, checks=outcome.okww_checks(ww(NEST_OK), expect_nest=True,
                                                                                        only_nest="落渊南丘"))))
check("a real fight booked as farmed: PASS on the combat line", (st, "NightmareNestTask:enter combat" in ev), ("PASS", True))

print("\n[#26 find_nest：日志和覆盖层报告一致]")
rep_dir = tmpdir()
okww_overlay.REPORT = rep_dir / "ark-okww-overlay.json"


def report(applied, adapted=(), skipped=(), at=None):
    okww_overlay.REPORT.write_text(json.dumps({"applied": list(applied), "adapted": [{"what": w, "why": "x"} for w in adapted],
                                               "skipped": [{"what": w, "why": "x"} for w in skipped], "error": ""},
                                              ensure_ascii=False), encoding="utf-8")
    t = (at or WWREC.started + timedelta(seconds=20)).timestamp()
    os.utime(okww_overlay.REPORT, (t, t))
    return okww_overlay.report_snapshot()


snap = report(["NightmareNestTask.find_nest", "NightmareNestTask.run"])
check("report_snapshot reads the report and when it was written",
      (snap["applied"][0], snap["written"][:19]), ("NightmareNestTask.find_nest", "2026-10-06T09:19:37"))
st, ev, pushed = judge("#26", wwctx(NEST_OK, overlay=snap))
check("log and report both say installed: PASS", (st, pushed), ("PASS", []))
st, ev, pushed = judge("#26", wwctx(["NightmareNestTask:nightmare nest: 只刷指定点位的改动没装上，这一轮不刷巢穴"], overlay=snap))
check("log says not installed, report says installed (the 10-05 contradiction): FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
check("evidence carries both", "对不上" in ev and "装上" in ev)
snap2 = report(["NightmareNestTask.run"], skipped=["NightmareNestTask.find_nest"])
st, _, _ = judge("#26", wwctx(["NightmareNestTask:nightmare nest: 只刷指定点位的改动没装上，这一轮不刷巢穴"], overlay=snap2))
check("both say not installed: consistent (PASS here; #5 says FAIL)", st, "PASS")
later = report(["NightmareNestTask.find_nest"], at=WWREC.finished + timedelta(hours=2))
st, _, _ = judge("#26", wwctx(NEST_OK, overlay=later))
check("report rewritten by a later OK-WW start: not judged on this run", st, None)
st, ev, _ = judge("#26", wwctx(NEST_OK, overlay={}))
check("no report at all: FAIL", st, "FAIL")
okww_overlay.REPORT.unlink()
check("report_snapshot: {} when there is no report", okww_overlay.report_snapshot(), {})

# ------------------------------------------------------------------ MaaEnd
END_LOG = (FIX / "maaend-farm-drops" / "2026-09-27.log").read_text(encoding="utf-8")
ENDREC = rec("MaaEnd", "2026-09-27/endfield/MaaEnd-05-35-00", datetime(2026, 9, 27, 9, 35, tzinfo=SERVER_TZ), minutes=40)


def endctx(text=END_LOG, raw=None, **kw):
    return dict({"rec": ENDREC, "raw": raw if raw is not None else collector_maaend.parse_maaend_log(write(text)),
                 "log_text": text}, **kw)


def write(text):
    f = tmpdir() / "MaaEnd.log"
    f.write_text(text, encoding="utf-8")
    return f


print("\n[#20 产出和剩余理智按游戏结算记（09-27 协议空间：两次进入、一次到账）]")
raw = collector_maaend.parse_maaend_log(write(END_LOG))
st, ev, pushed = judge("#20", endctx(raw=raw))
check("today's reading of the real 09-27 log: PASS", (st, pushed), ("PASS", []))
check("evidence has the game's items and reading", "折金票×68000" in ev and "当前理智 117/360" in ev)
bad = dict(raw, maaend_farm_runs=2, sanity=0)        # what the reading before 09-29 01:32 booked
st, ev, pushed = judge("#20", endctx(raw=bad))
check("the old reading (2 runs, 0 left): FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
check("evidence names both numbers", "趟数 2≠1" in ev and "剩余理智 0≠117" in ev)
st, _, _ = judge("#20", endctx(raw=dict(raw, maaend_farm_drops={})))
check("the output row empty (before the fix): FAIL", st, "FAIL")
essence = (FIX / "maaend-farm-drops" / "2026-09-24_MaaEnd-06-07-50.log").read_text(encoding="utf-8")
st, _, _ = judge("#20", endctx(text=essence))
check("essence farming (no item list): not judged", st, None)

print("\n[#7 环境监测：每趟收下那一段的框架日志，只收不判，不推]")
# The coordinator, 2026-10-06: no line of its own in the AUTO-MAS log is no proof of
# failure (the 110 s run of 09-04 wrote none either), and the repo has no framework-log
# sample of 环境监测 to tell working from not. So #7 captures and never pushes on what
# it captured. The node names below are placeholders in MaaFW's event-line shape
# (fixtures/collect-watch-2026-09-14/maafw-attempt3.log); the check does not read meaning
# into them.
ENV_FW = "[2026-09-27 09:42:{}][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65][MaaNS::EventDispatcher::notify] "
fwdir = tmpdir()
(fwdir / "debug").mkdir(parents=True)
(fwdir / "debug" / "maafw.log").write_text("\n".join([
    ENV_FW.format("50.900") + '!!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] [details={"name":"BeforeWindow"}]',
    ENV_FW.format("51.200") + '!!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.Starting] [details={"entry":"PlaceholderEntry","task_id":200000013}]',
    ENV_FW.format("52.000") + '!!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] [details={"name":"PlaceholderNodeA","task_id":200000013}]',
    ENV_FW.format("55.500") + '!!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] [details={"name":"PlaceholderNodeB","task_id":200000013}]',
    ENV_FW.format("57.300") + '!!!OnEventNotify!!! [handle=true] [msg=Tasker.Task.Succeeded] [details={"entry":"PlaceholderEntry","task_id":200000013}]',
]) + "\n", encoding="utf-8")
state = tmpdir()
st, ev, pushed = judge("#7", endctx(maaend_dir=str(fwdir)), state=state)
check("09-27 (6 s, no line of its own in the AUTO-MAS log), framework lines there: PASS (captured), nothing pushed",
      (st, pushed), ("PASS", []))
check("the daily line says it is capture only, with the window, the task and the nodes",
      ev.startswith("只收不判：环境监测 6 秒（09:42:51→09:42:57）") and "PlaceholderEntry" in ev
      and "PlaceholderNodeA、PlaceholderNodeB" in ev)
kept = state / "machinecheck-env" / "2026-09-27_endfield_MaaEnd-05-35-00.log"
check("the stretch is kept in state/machinecheck-env/<run>.log, named in the line",
      (kept.is_file(), "machinecheck-env/2026-09-27_endfield_MaaEnd-05-35-00.log" in ev), (True, True))
body = kept.read_text(encoding="utf-8") if kept.is_file() else ""
check("only the task's own window (start 09:42:51 → finish 09:42:57) is kept",
      ("PlaceholderNodeB" in body, "BeforeWindow" in body), (True, False))
check("the check is kind B (judged when the next 环境监测 run comes) and never says done/not done",
      (mc.CHECKS["#7"].kind, "只收不判" in mc.CHECKS["#7"].what), ("B", True))
nofw = tmpdir()
state = tmpdir()
st, ev, pushed = judge("#7", endctx(maaend_dir=str(nofw)), state=state)
check("no framework log for the window: not judged, nothing pushed", (st, pushed), (None, []))
st, ev, pushed = judge("#7", endctx(maaend_dir=str(nofw)), state=state)
check("the second run in a row without it: FAIL (missing evidence), pushed", (st, len(pushed)), ("FAIL", 1))
check("…saying why there is none", "连续 2 趟" in ev and "框架日志" in ev)
st, _, _ = judge("#7", endctx(maaend_dir=str(fwdir)), state=state)
check("a run with the lines again: captured, the count starts over", st, "PASS")
st, _, pushed = judge("#7", endctx(maaend_dir=str(nofw)), state=state)
check("one miss after that: not judged again", (st, pushed), (None, []))
st, _, _ = judge("#7", endctx(text=essence, maaend_dir=str(fwdir)), state=tmpdir())
check("a run without 环境监测: not judged", st, None)

print("\n[#28 四个任务都有结束时的截图]")
state = tmpdir()
shots = {}
for t in ("赠送干员礼物", "装备制造", "转交委托", "环境监测"):
    p = state / "shots" / "2026-09-27" / "MaaEnd-09-36-00" / f"094300-{t}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"png")
    shots[t] = p.relative_to(state).as_posix()
times = collector_maaend.task_times(END_LOG)
check("the 09-27 log ran all four", all(t in times for t in shots), True)
st, ev, pushed = judge("#28", endctx(raw=dict(raw, tasks_shot_files=shots)), state=state)
check("a picture for each: PASS", (st, pushed), ("PASS", []))
check("evidence names the pictures", "shots/2026-09-27/MaaEnd-09-36-00/094300-装备制造.png" in ev)
st, ev, pushed = judge("#28", endctx(raw=dict(raw, tasks_shot_files={k: v for k, v in shots.items() if k != "转交委托"})),
                       state=state)
check("one missing: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
check("evidence names the missing one", ev.startswith("转交委托 做完了"))

print("\n[#30 基质刷取领奖后失败：背包满了 / 原始日志]")
BAG = (FIX / "maaend_bagfull_2026-09-25.log").read_text(encoding="utf-8")
end = tmpdir()
(end / "debug").mkdir(parents=True)
(end / "debug" / "maafw.log").write_bytes((FIX / "maaend_bagfull_2026-09-25_maafw.log").read_bytes())
check("claim_failures finds the essence failure after the click",
      [x[0] for x in collector_maaend.claim_failures(BAG)], ["基质刷取"])
bag_raw = collector_maaend.parse_maaend_log(write(BAG), end)
BAGREC = rec("MaaEnd", "2026-09-25/endfield/MaaEnd-05-54-06", datetime(2026, 9, 25, 9, 54, 6, tzinfo=SERVER_TZ),
             ok=False, raw=bag_raw, failed=bag_raw.get("tasks_failed"))
st, ev, pushed = judge("#30", {"rec": BAGREC, "raw": bag_raw, "log_text": BAG, "maaend_dir": str(end)})
check("storage-full notice seen, alarm says 背包满了: PASS", (st, pushed), ("PASS", []))
check("evidence is the notice line", "仓储空间已满" in ev)
no_fw = tmpdir()
(no_fw / "debug").mkdir(parents=True)
bare = collector_maaend.parse_maaend_log(write(BAG), no_fw)
BARE = rec("MaaEnd", BAGREC.run_id, BAGREC.started, ok=False, raw=bare, failed=bare.get("tasks_failed"))
st, ev, pushed = judge("#30", {"rec": BARE, "raw": bare, "log_text": BAG, "maaend_dir": str(no_fw)})
check("no notice: the alarm carries the raw lines: PASS", (st, "原始日志" in ev), ("PASS", True))
lost = dict(bare)
lost.pop("maaend_claim_lines", None)
BAD = rec("MaaEnd", BAGREC.run_id, BAGREC.started, ok=False, raw=lost, failed=lost.get("tasks_failed"))
st, ev, pushed = judge("#30", {"rec": BAD, "raw": lost, "log_text": BAG, "maaend_dir": str(no_fw)})
check("neither the cause nor the raw lines: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
wrong = dict(bag_raw, maaend_fail_causes={})
WRONG = rec("MaaEnd", BAGREC.run_id, BAGREC.started, ok=False, raw=wrong, failed=wrong.get("tasks_failed"))
st, ev, _ = judge("#30", {"rec": WRONG, "raw": wrong, "log_text": BAG, "maaend_dir": str(end)})
check("the notice was there but the cause not named: FAIL", (st, "仓储空间已满" in ev), ("FAIL", True))

print("\n[#29 采集撞上「战斗中无法使用」的那条路线]")
COLLECT = "\n".join([
    "[2026-10-05 10:01:54.000] 任务开始: 🌿自动采集",
    "[2026-10-05 10:05:10.000] 路线14：四号谷地-晶化多齿叶",
    "[2026-10-05 10:09:16.566] 路线15：武陵-红矛叶",
    "[2026-10-05 10:12:40.000] 路线16：武陵-协议纹石",
    "[2026-10-05 10:20:00.000] 任务完成: 🌿自动采集"])
fw = tmpdir()
(fw / "debug").mkdir(parents=True)
P = "[2026-10-05 10:{}][INF][Px7172][Tx32558][Utils/EventDispatcher.hpp][L65][MaaNS::EventDispatcher::notify] "
FW_HIT = (P.format("10:03.000") + '[msg=Node.Recognition.Succeeded] [details={"name":"AutoCollectFindButtonUsing",'
          '"reco_detail":{"text":"战斗中无法使用"}}]')
FW_END = P.format("12:30.000") + '!!!OnEventNotify!!! [handle=true] [msg=Node.Action.Starting] [details={"name":"AutoCollectRoute15End"}]'
FW_ESC = P.format("10:05.000") + '[msg=Node.Recognition.Succeeded] [details={"text":"' + json.dumps("战斗中无法使用").strip('"') + '"}]'
(fw / "debug" / "maafw.log").write_text(FW_HIT + "\n" + FW_HIT.replace("Px7172", "Px18500") + "\n" + FW_ESC + "\n"
                                       + FW_END + "\n", encoding="utf-8")
CREC = rec("MaaEnd", "2026-10-05/endfield/MaaEnd-06-01-00", datetime(2026, 10, 5, 10, 1, tzinfo=SERVER_TZ))
hits = collector_maaend.maafw_grep(str(fw), datetime(2026, 10, 5, 10, 0), datetime(2026, 10, 5, 10, 20), ("战斗中无法使用",))
check("maafw_grep: the plain line once (the second process's echo dropped), and the JSON-escaped one",
      [h[12:20] for h in hits], ["10:10:03", "10:10:05"])
check("maafw_grep: nothing outside the window",
      collector_maaend.maafw_grep(str(fw), datetime(2026, 10, 5, 10, 11), datetime(2026, 10, 5, 10, 20),
                                  ("战斗中无法使用",)), [])
st, ev, pushed = judge("#29", {"rec": CREC, "raw": {}, "log_text": COLLECT, "maaend_dir": str(fw)})
check("route 15 hit it, and its End event followed: PASS", (st, pushed), ("PASS", []))
check("evidence names the route", "路线15：武陵-红矛叶" in ev and "AutoCollectRoute15End" in ev)
st, ev, pushed = judge("#29", {"rec": CREC, "raw": {}, "maaend_dir": str(fw),
                               "log_text": COLLECT.replace("[2026-10-05 10:12:40.000] 路线16",
                                                           "[2026-10-05 10:11:00.000] 路线15：武陵-红矛叶采集失败\n"
                                                           "[2026-10-05 10:12:40.000] 路线16")})
check("that route then logged 采集失败: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
(fw / "debug" / "maafw.log").write_text(FW_HIT + "\n", encoding="utf-8")
st, ev, _ = judge("#29", {"rec": CREC, "raw": {}, "log_text": COLLECT, "maaend_dir": str(fw)})
check("no sign the route finished: FAIL (no guess)", (st, "AutoCollectRoute15End" in ev), ("FAIL", True))
st, _, _ = judge("#29", {"rec": CREC, "raw": {}, "log_text": COLLECT, "maaend_dir": str(tmpdir())})
check("the message never seen: not judged", st, None)

# ------------------------------------------------------------------ #6 / #24a, #43 / #46, #24b
print("\n[#6 / #24a 做完以后装新版重启：判过的不重判，进过群的就是没过]")
RID = "2026-10-04/endfield/MaaEnd-05-50-53"
UR = {RID: {"version": "v2.32.0-beta.1", "started": "2026-10-04T09:50:53+08:00",
            "done": "2026-10-04/endfield/MaaEnd-05-26-41", "held": False}}
R4 = rec("MaaEnd", RID, datetime(2026, 10, 4, 9, 50, 53, tzinfo=SERVER_TZ), ok=False)
state = tmpdir()
st, ev, pushed = judge("#6", {"rec": R4, "raw": {}, "update_restarts": UR}, state=state)
check("let go, no alarm copy: PASS", (st, pushed), ("PASS", []))
check("evidence names both runs", "MaaEnd-05-50-53" in ev and "MaaEnd-05-26-41" in ev)
check("#24a judged the same run on its own row", (mc.read(state).get("#24a") or {}).get("status"), "PASS")
st, _, _ = judge("#6", {"rec": R4, "raw": {}, "update_restarts": UR}, state=state)
check("the same restart is judged once", st, None)
state = tmpdir()
alertlog.AlertLog(state).record(texts.failed("MaaEnd"), "重试 2 次全部失败，需要处理。\n· 失败于：MaaEnd 装新版 v2.32.0-beta.1 后自己重启，这一次重试被用掉",
                                now=datetime(2026, 10, 4, 1, 51, 26, tzinfo=alertlog.timezone.utc))
st, ev, pushed = judge("#6", {"rec": R4, "raw": {}, "update_restarts": UR}, state=state)
check("10-04 09:51:26 「❌ MaaEnd 失败」 in the alarm copies: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
check("evidence is that alarm", "2026-10-04 09:51:26" in ev and "❌ MaaEnd 失败" in ev)
st, _, _ = judge("#6", {"rec": R4, "raw": {}, "update_restarts": {RID: dict(UR[RID], held=True)}}, state=tmpdir())
check("still held (the push step lets it go): not judged yet", st, None)
st, _, _ = judge("#6", {"rec": R4, "raw": {}, "update_restarts": {RID: dict(UR[RID], done="")}}, state=tmpdir())
check("no done round in the shift: not this case", st, None)

print("\n[#43 / #46 没干完的每一趟都进了群]")
undone = "OK-WW 这一轮有 1 项没干成，但它自己没报错：\n· 残象聚落：点了点位，但传送不过去，一次没打"
state = tmpdir()
alertlog.AlertLog(state).record(texts.ROUND_INCOMPLETE, undone)
row = json.loads((state / "alerts").glob("*.jsonl").__next__().read_text(encoding="utf-8"))
ctx = {"rec": WWREC, "raw": {}, "outcome": {"checks": [], "msg": undone}, "alerts": [row]}
st, ev, pushed = judge("#46", ctx, state=state)
check("the alarm is among the copies: PASS", (st, pushed), ("PASS", []))
check("evidence names the alarm", texts.ROUND_INCOMPLETE in ev)
st, ev, pushed = judge("#46", dict(ctx, alerts=[]), state=tmpdir())
check("no copy of it: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
st, ev, _ = judge("#46", dict(ctx, alerts=[], unsent=[WWREC.run_id]), state=tmpdir())
check("…saying the push is queued when it is", "排在下一轮重推" in ev)
st, _, _ = judge("#46", dict(ctx, outcome={"checks": [], "msg": None}), state=tmpdir())
check("nothing undone: not judged", st, None)
st, _, _ = judge("#43", ctx, state=state)
check("#43 is MaaEnd's: not judged on an OK-WW run", st, None)

print("\n[#24b 预更新没结论：再试一次，还没结论就进群（读 relay.log）]")
relay = Path(os.environ["ARK_LOG_FILE"])
today = datetime.now(tz=SERVER_TZ).strftime("%m-%d")
relay.write_text("\n".join([
    f"{today} 08:46:10 INFO    ark.service  预更新：MAA 没给出结论（MAA 180 秒内没给出更新结论），再试一次",
    f"{today} 08:50:34 WARNING ark.service  预更新有 1 项没能确认：",
    "· MAA 180 秒内没给出更新结论"]) + "\n", encoding="utf-8")
state = tmpdir()
alertlog.AlertLog(state).record(texts.unconfirmed("预更新", 1), "· MAA 180 秒内没给出更新结论")
st, ev, pushed = judge("#24b", {"rec": WWREC, "raw": {}}, state=state)
check("retried, still unconfirmed, alarm in the copies: PASS", (st, pushed), ("PASS", []))
check("evidence starts with the retry line's time", ev.startswith(f"{today} 08:46:10"))
st, _, _ = judge("#24b", {"rec": WWREC, "raw": {}}, state=state)
check("the same pre-update is judged once", st, None)
st, ev, pushed = judge("#24b", {"rec": WWREC, "raw": {}}, state=tmpdir())
check("no copy of the alarm: FAIL, pushed", (st, len(pushed)), ("FAIL", 1))
relay.write_text(f"{today} 08:50:34 WARNING ark.service  预更新有 1 项没能确认：\n", encoding="utf-8")
st, ev, _ = judge("#24b", {"rec": WWREC, "raw": {}}, state=tmpdir())
check("unconfirmed without a second try: FAIL", (st, "再试一次" in ev), ("FAIL", True))
relay.write_text("", encoding="utf-8")
st, _, _ = judge("#24b", {"rec": WWREC, "raw": {}}, state=tmpdir())
check("no pre-update trouble today: not judged", st, None)
check("#24c / #24d are listed as not machine-checkable, with the reason",
      ("#24c" in mc.CANNOT and "10-06" in mc.CANNOT["#24c"][1], "#24d" in mc.CANNOT), (True, True))

# ------------------------------------------------------------------ wiring through handle._handle
print("\n[handle._handle: the checks are judged right after the record is booked]")


class Src:
    def fetch(self, seen):
        return []


handle._ship_evidence = lambda eng, r: ""
handle._weekly_gates = lambda eng, r: None
collect_retry.restore_master = lambda cfg: ""


def build(notifier_refuses=False):
    cfg = Config()
    cfg.state_dir = tmpdir()
    cfg.maaend_dir = tmpdir()
    e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=N(cfg.state_dir, notifier_refuses))
    e._scripts_running = lambda: False
    e._script_running = lambda name: False
    e._archive_maaend_evidence = lambda r: None
    return e


e = build()
e._verify_outcome = lambda rr: None
okww_log = TMP / "history" / "OK-WW-05-19-17.log"
okww_log.write_text(ww(WEEKLY_IN + ["FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3",
                                    "DailyTask:Daily Task Completed", "TacetTask:enter combat"]), encoding="utf-8")
r = rec("OK-WW", "2026-10-06/wuwa/OK-WW-05-19-17", datetime(2026, 10, 6, 9, 19, 17, tzinfo=SERVER_TZ))
r.log_path = okww_log
handle._handle(e, r)
saved = mc.read(e.cfg.state_dir)
check("#4 judged and kept in state/machinecheck.json", (saved.get("#4") or {}).get("status"), "PASS")
check("with the run's own read-back line", "3/3→2/3" in (saved.get("#4") or {}).get("evidence", ""))
check("nothing pushed for a PASS", [t for t, _, a in e.notifier.sent if a], [])

print("\n[handle._handle: an undone OK-WW round's alarm is checked against the alarm copies]")
okww_log.write_text(ww(["NightmareNestTask:opened gray_book_boss", "DailyTask:Daily Task Completed",
                        "TacetTask:enter combat"]), encoding="utf-8")
e = build()
e._verify_outcome = lambda rr: handle._judged(rr, [outcome.Check("残象聚落", False, "一次没打")], "OK-WW",
                                              expect_nest=True, only_nest="")
handle._handle(e, r)
check("#46: the alarm went out and its copy is there", (mc.read(e.cfg.state_dir).get("#46") or {}).get("status"), "PASS")
e = build(notifier_refuses=True)
e._verify_outcome = lambda rr: handle._judged(rr, [outcome.Check("残象聚落", False, "一次没打")], "OK-WW",
                                              expect_nest=True, only_nest="")
handle._handle(e, r)
check("#46: the group refused it: FAIL", (mc.read(e.cfg.state_dir).get("#46") or {}).get("status"), "FAIL")
check("…and the FAIL itself was pushed (tried; the same group refused it)",
      any(t.startswith(texts.machinecheck_failed("#46", "")) for t, _, a in e.notifier.sent if a), True)

print("\n[handle._handle: a broken check context never breaks the booking]")
e = build()
real = handle._run_ctx
handle._run_ctx = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
errs = []
h = type("H", (logging.Handler,), {"emit": lambda self, rr: errs.append(rr.getMessage())})(level=logging.ERROR)
handle.log.addHandler(h)
try:
    handle._handle(e, r)
finally:
    handle._run_ctx = real
    handle.log.removeHandler(h)
check("the record is on the ledger", [x["run_id"] for x in e.state.read_ledger("2026-10-06")], [r.run_id])
check("an ERROR says the machine check did not run (errwatch pushes it)", any("上机核对没跑成" in m for m in errs))

print("\n[handle._mark_task_shots keeps each picture's path]")
e = build()
day = e.cfg.state_dir / "shots" / "2026-09-27" / "MaaEnd-09-36-00"
day.mkdir(parents=True)
for t, hhmmss in (("环境监测", "094258"), ("装备制造", "094000")):
    f = day / f"{hhmmss}-{t}.png"
    f.write_bytes(b"png")
    at = datetime.strptime(f"2026-09-27 {hhmmss}", "%Y-%m-%d %H%M%S").replace(tzinfo=SERVER_TZ).timestamp()
    os.utime(f, (at, at))
mrec = rec("MaaEnd", "2026-09-27/endfield/MaaEnd-05-35-00", datetime(2026, 9, 27, 9, 35, tzinfo=SERVER_TZ), minutes=40)
mrec.log_path = write(END_LOG)
handle._mark_task_shots(e, mrec)
check("tasks_shot as before", sorted(mrec.raw.get("tasks_shot") or []), ["环境监测"])
check("tasks_shot_files names the picture under the state folder",
      mrec.raw.get("tasks_shot_files"), {"环境监测": "shots/2026-09-27/MaaEnd-09-36-00/094258-环境监测.png"})

print("\n[handle._run_ctx: a run log that cannot be read is said, and marked in the context]")
e = build()
unreadable = TMP / "history" / "a-directory.log"
unreadable.mkdir(exist_ok=True)              # read_text raises IsADirectoryError / PermissionError
ur = rec("OK-WW", "2026-10-06/wuwa/OK-WW-06-00-00", datetime(2026, 10, 6, 10, 0, 0, tzinfo=SERVER_TZ))
ur.log_path = unreadable
warned = []
wh = type("W", (logging.Handler,), {"emit": lambda self, rr: warned.append(rr.getMessage())})(level=logging.WARNING)
handle.log.addHandler(wh)
try:
    ctx = handle._run_ctx(e, ur, handle._RunWatch(e))
finally:
    handle.log.removeHandler(wh)
check("log_text stays \"\" and log_unreadable is set", (ctx["log_text"], ctx.get("log_unreadable")), ("", True))
check("one WARNING naming the run", len(warned) == 1 and ur.run_id in warned[0], True)
ctx_ok = handle._run_ctx(e, r, handle._RunWatch(e))
check("a readable log -> no log_unreadable key", "log_unreadable" in ctx_ok, False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
