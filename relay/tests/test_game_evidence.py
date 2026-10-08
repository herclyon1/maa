"""The daily report counts a task as done only with evidence from the game.

2026-10-05: four MaaEnd tasks (gifts, gear assembly, delivery jobs, environment
monitoring) had nothing in the log but 「任务开始」 / 「任务完成」 and were counted
as done - the program's own word. Evidence is a line the run wrote between a
task's start and its finish (an item gained, a sanity reading, ...), a
task-end picture (task_shots.py), or for the weekly items the game's own
counter. A task without any is named 「没证据，不算完成」: neither done nor failed,
and the day's title is no longer 全绿 for it. No alarm is raised for it.
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
os.environ.update(ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="",
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import collector, collector_maaend, collector_okww, core, handle, outcome, texts  # noqa: E402
from ark_relay.config import SERVER_TZ, RunRecord  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  ✓ {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


FX = Path(__file__).parent / "fixtures"
FULL = (FX / "maaend_full_2026-09-01.log").read_text(encoding="utf-8")

print("[每一项的证据：开始和完成之间 MaaEnd 自己写的别的行]")
ev = collector_maaend.task_evidence(FULL)
check("只有开始/完成两行的：没证据", (ev["赠送干员礼物"], ev["装备制造"], ev["拜访好友"]), ("", "", ""))
check("有「获得」行的：那一行", ev["基建任务"], "获得 燎石子簇 ×1")
check("读到身上没有加强剂也是游戏里的读数", ev["应急理智加强剂"], "没有应急理智加强剂，结束任务")
retry = ("[2026-10-05 10:41:05.000] 任务开始: 🎁赠送干员礼物\n[2026-10-05 10:41:09.000] 任务完成: 🎁赠送干员礼物\n"
         "[2026-10-05 11:00:00.000] 任务开始: 🎁赠送干员礼物\n[2026-10-05 11:00:03.000] 获得 信用 ×400\n"
         "[2026-10-05 11:00:05.000] 任务完成: 🎁赠送干员礼物\n"
         "[2026-10-05 11:01:00.000] 任务开始: 🔧装备制造\n[2026-10-05 11:01:01.000] 获得 嵌晶玉 ×25\n"
         "[2026-10-05 11:01:02.000] 任务失败: 🔧装备制造\n")
ev2 = collector_maaend.task_evidence(retry)
check("同一项跑两次：有证据的那次算", ev2.get("赠送干员礼物"), "获得 信用 ×400")
check("失败的那项不进证据表", "装备制造" in ev2, False)
check("每项的起止时间（最后一次）", collector_maaend.task_times(retry)["赠送干员礼物"],
      (datetime(2026, 10, 5, 11, 0, 0), datetime(2026, 10, 5, 11, 0, 5)))
log_path = TMP / "MaaEnd.log"
log_path.write_text(FULL, encoding="utf-8")
parsed = collector.parse_maaend_log(log_path)
check("解析结果带证据表", parsed.get("tasks_evidence", {}).get("信用点购物"), "获得 折金票 ×2000")

print("\n[任务结束截图也算证据（task_shots 存的图，按名字和完成时刻对上）]")
ROUND = ("[2026-10-05 10:41:05.000] 任务开始: 🎁赠送干员礼物\n[2026-10-05 10:42:10.000] 任务完成: 🎁赠送干员礼物\n"
         "[2026-10-05 10:42:11.000] 任务开始: 🔧装备制造\n[2026-10-05 10:43:20.000] 任务完成: 🔧装备制造\n"
         "[2026-10-05 10:43:21.000] 任务开始: 🚚转交委托\n[2026-10-05 10:44:30.000] 任务完成: 🚚转交委托\n")
hist = TMP / "MaaEnd-06-39-48.log"
hist.write_text(ROUND, encoding="utf-8")
STATE = TMP / "state"
run_dir = STATE / "shots" / "2026-10-05" / "MaaEnd-10-41-05"
run_dir.mkdir(parents=True)


def picture(name, at):
    p = run_dir / f"{name}.png"
    p.write_bytes(b"png")
    ts = datetime.strptime(f"2026-10-05 {at}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=SERVER_TZ).timestamp()
    os.utime(p, (ts, ts))


picture("104105-赠送干员礼物", "10:41:08")     # the launch's first-start picture: not an end picture
picture("104213-赠送干员礼物", "10:42:15")     # its end picture
picture("104322-装备制造", "10:43:25")         # end picture of 装备制造
started = datetime(2026, 10, 5, 10, 41, 0, tzinfo=SERVER_TZ)
rec = RunRecord(run_id="2026-10-05/endfield/MaaEnd-06-39-48", script="MaaEnd", user="endfield",
                started=started, finished=started + timedelta(minutes=4), ok=True,
                raw={"tasks_done": ["赠送干员礼物", "装备制造", "转交委托"]}, log_path=hist)
eng = SimpleNamespace(cfg=SimpleNamespace(state_dir=STATE))
handle._mark_task_shots(eng, rec)
check("有结束截图的两项记下", rec.raw.get("tasks_shot"), ["赠送干员礼物", "装备制造"])
rec.raw["tasks_evidence"] = collector_maaend.task_evidence(ROUND)
check("没截图也没读数的那项没证据", core.maaend_unverified(rec.raw), ["转交委托"])
only_start = RunRecord(run_id="x", script="MaaEnd", user="endfield", started=started,
                       finished=started + timedelta(minutes=4), ok=True, raw={}, log_path=hist)
(run_dir / "104213-赠送干员礼物.png").unlink()
(run_dir / "104322-装备制造.png").unlink()
handle._mark_task_shots(eng, only_start)
check("只有开跑前那张（离完成一分多钟）不算", only_start.raw.get("tasks_shot"), None)
# refresh_raw re-parses only the log; the picture list must survive it.
hdir = TMP / "history" / "2026-10-05" / "endfield"
hdir.mkdir(parents=True)
(hdir / "MaaEnd-06-39-48.log").write_text(ROUND, encoding="utf-8")
entry = {"run_id": rec.run_id, "script": "MaaEnd", "ok": True, "raw": dict(rec.raw)}
fresh = collector.refresh_raw(entry, TMP / "history")
check("重算 raw 不丢截图证据", fresh["raw"].get("tasks_shot"), ["赠送干员礼物", "装备制造"])
check("重算后证据表还在", core.maaend_unverified(fresh["raw"]), ["转交委托"])

print("\n[日报：只把有证据的算做了，没证据的点名；标题不再是全绿]")


def ent(run_id, script, hh, mm, dur, ok=True, **kw):
    st = datetime(2026, 10, 5, hh, mm, tzinfo=SERVER_TZ)
    e = {"run_id": run_id, "script": script, "user": "u", "ok": ok,
         "started": st.isoformat(), "finished": (st + timedelta(minutes=dur)).isoformat(),
         "duration_known": True, "transitional": False, "failed_tasks": [] if ok else ["x"],
         "raw": {}, "drops": {}, "recruits": {}, "sanity": None, "sanity_full_at": ""}
    e.update(kw)
    return e


end = ent("2026-10-05/endfield/MaaEnd-06-39-48", "MaaEnd", 10, 41, 4, raw=fresh["raw"])
title, body = core.format_daily("2026-10-05", [end])
check("做了只列有证据的", "做了 赠送干员礼物、装备制造" in body)
check("没证据的点名，不算完成", f"{core.UNVERIFIED}：转交委托" in body)
check("标题：没证据，不是全绿", title, "📋 10-05 · 终末地 1 项没证据，不算完成 ❔")
check("脚注只列有证据的", core.daily_footnote([end]), "———————\n日常：1.赠送干员礼物 2.装备制造")
all_ok = ent("2026-10-05/endfield/MaaEnd-06-39-48", "MaaEnd", 10, 41, 4,
             raw=dict(fresh["raw"], tasks_shot=["赠送干员礼物", "装备制造", "转交委托"]))
check("三项都有证据：全绿", core.format_daily("2026-10-05", [all_ok])[0], "📋 10-05 · 全绿 ✅")
old = ent("2026-10-05/endfield/MaaEnd-1", "MaaEnd", 9, 0, 4, raw={"tasks_done": ["赠送干员礼物"]})
check("账上没有证据表（日志找不到了）：按没证据", core.maaend_unverified(old["raw"]), ["赠送干员礼物"])
later = ent("2026-10-05/endfield/MaaEnd-2", "MaaEnd", 11, 0, 4,
            raw={"tasks_done": ["赠送干员礼物"], "tasks_evidence": {"赠送干员礼物": "获得 信用 ×400"}})
check("同一天另一趟有证据：整天不算没证据", core.day_unverified([old, later]), [])
check("红按钮停掉的那趟不算", core.day_unverified([dict(old, raw=dict(old["raw"], manual_stop="09:01 停一切"))]), [])

print("\n[重试里「做成了」也要证据]")
failed = ent("2026-10-05/endfield/MaaEnd-0", "MaaEnd", 8, 0, 4, ok=False, failed_tasks=["转交委托"])
retry_bare = ent("2026-10-05/endfield/MaaEnd-3", "MaaEnd", 8, 10, 2,
                 raw={"tasks_done": ["转交委托"], "tasks_evidence": {"转交委托": ""}})
check("重试只有「任务完成」：不说做成了", core.retried_notes([failed, retry_bare])[failed["run_id"]],
      "转交委托　后来在 08:12 那趟重试里程序说做完了，但没证据，不算完成")
retry_ev = dict(retry_bare, raw={"tasks_done": ["转交委托"], "tasks_evidence": {"转交委托": "获得 信用 ×100"}})
check("重试有读数：做成了", core.retried_notes([failed, retry_ev])[failed["run_id"]], "转交委托　后来在 08:12 那趟重试里做成了")

print("\n[明日方舟剿灭：没读到「剿灭模式 x/y」不算打满]")
anni = ent("2026-10-05/arknights/MAA-1", "MAA", 21, 30, 20, raw={"annihilation": True, "annihilation_done": True})
t, b = core.format_daily("2026-10-05", [anni])
check("不再说「本周剿灭此前已完成」", "此前已完成" in b, False)
check("说没读到进度、不算打满", "没读到剿灭进度，本周按没打满算" in b)
check("标题点名", t, "📋 10-05 · 明日方舟 1 项没证据，不算完成 ❔")
fought = ent("2026-10-05/arknights/MAA-2", "MAA", 21, 30, 20, raw={"annihilation": True, "sanity_spent": 25})
check("打了但没进度：也不说「已打剿灭」", "已打剿灭" in core.format_daily("2026-10-05", [fought])[1], False)
full = ent("2026-10-05/arknights/MAA-3", "MAA", 21, 30, 20,
           raw={"annihilation": True, "annihilation_progress": [1800, 1800], "annihilation_done": True})
check("读到 1800/1800：打满，全绿", core.format_daily("2026-10-05", [full])[0], "📋 10-05 · 全绿 ✅")
short = ent("2026-10-05/arknights/MAA-4", "MAA", 9, 0, 2, ok=False, failed_tasks=["MAA 部分任务执行失败"],
            raw={"annihilation": True, "maa_sanity_short": {"have": 17, "cost": 25}})
check("理智不够没打的：不算没证据（另有说法）", core.day_unverified([short]), [])

print("\n[鸣潮周常乐园：只跑了没读到做完，不算完成]")
G = "2026-09-14 10:02:11,001 INFO TaskExecutor GardenTask:Garden current: [Box(name='2000/2000')]\n"
steps = collector_okww._okww_steps(G, 0)
check("步骤写不算完成", steps, ["周常乐园（没读到做完，不算完成）"])
ww = ent("2026-10-05/wuwa/OK-WW-1", "OK-WW", 9, 0, 20, raw={"okww_steps": steps})
check("标题点名", core.format_daily("2026-10-05", [ww])[0], "📋 10-05 · 鸣潮 1 项没证据，不算完成 ❔")
done_g = collector_okww._okww_steps(G + "2026-09-14 10:02:12,001 INFO TaskExecutor GardenTask:乐园任务完成, 已达到上限\n", 0)
check("读到「乐园任务完成」：做完", done_g, ["周常乐园（本周已完成）"])

print("\n[只进日报，不报警：结果核对不因没证据而判没干完]")
check("MaaEnd 结果核对不变（没证据不是失败）",
      [c.label for c in outcome.maaend_checks(ROUND, [], own_log=False) if not c.ok and "转交委托" in c.label], [])

print("\n[文案是人话]")
check("没证据那句", texts.plain(core.UNVERIFIED), [])
check("标题那句", texts.plain("终末地 1 项没证据，不算完成 ❔"), [])

print("\n[MaaEnd 自己的「停止任务」不是游戏里的任务（10-08 日报「终末地 1 项没证据」就是它）]")
# The 10:32 attempt of 2026-10-08 (evidence bundle MaaEnd-06-31-06): two tasks, then
# AUTO-MAS stopped MaaEnd for its update and the log says 「任务完成: 停止任务」.
stop = collector.parse_maaend_log(FX / "maaend_stop_task_2026-10-08.log")
check("日志里解析出了停止任务", "停止任务" in (stop.get("tasks_done") or []), True)
stop["tasks_shot"] = ["赠送干员礼物", "装备制造"]   # 103411 / 103416 in that bundle
check("两项都有任务结束截图：这一趟没有没证据的项", core.maaend_unverified(stop), [])
check("日报整天不算没证据", core.day_unverified([{"script": "MaaEnd", "ok": False, "raw": stop}]), [])
check("日常清单里也不列停止任务", "停止任务" in core._maaend_listed(stop), False)

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
