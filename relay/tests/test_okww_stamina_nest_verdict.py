"""刷体力 and the nest item are judged from the lines of the task that did the work.

Three holes found 10-13 against upstream OK-WW v3.7.4 (on the game PC since 10-06):

  stamina (a)  「enter combat」 is CombatCheck.py:181, logged by every fighting task. The
               weekly boss and the nest (both run before stamina farming) print it,
               so a run that spent no stamina passed 刷体力. Only TacetTask /
               ForgeryTask / SimulationTask lines count now.
  stamina (b)  farm_tacet / farm_domain give up after three revives and return
               quietly (TacetTask.py:79, DomainTask.py:73, 「exceeded recovery
               retries (3), stop farming」): that is a failed 刷体力 now.
  stamina (c)  when our get_stamina override cannot read 数/数 it returns -1 and logs
               「按没读到处理（-1）」; upstream then says 「used all stamina」
               (TacetTask.py:63-66, :105) or 「not enough stamina」 (DomainTask.py:61-63)
               though nothing was read. With no stamina fight that is a failure.
  nest         「click_team_challenge」, 「wait_in_team_and_world」 and 「echo captured」 are
               never logged by upstream (BaseWWTask.py:678-683, :1115-1117 have no log
               call; 「echo captured」 is only an argument at NightmareNestTask.py:74,
               stored without logging at CombatCheck.py:58-61). They appear only in
               traceback frames of other tasks' errors (fixtures/m6-okww/0921-weekly.log:
               27-28), which booked an unreachable nest as fought. The daily-report
               step and the verdict now read one classifier, outcome.nest_state.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.verify import collector_okww, outcome

fails = []
FX = Path(__file__).resolve().parent / "fixtures"


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def line(t, who, msg):
    return f"2026-10-13 10:{t},000 INFO TaskExecutor {who}:{msg}\n"


def stamina(text):
    got = [c for c in outcome.okww_checks(text, expect_nest=False, expect_daily=False) if c.label == "刷体力"]
    return (got[0].ok, got[0].detail) if got else None


def stopped(text):
    out = {}
    collector_okww._okww_progress(text, out)
    return out.get("okww_stopped")


# Read with a fallback so that the checks run, and fail, on code without them.
UNREAD_SAY = getattr(outcome, "STAMINA_UNREAD_SAY", "体力读不出来，没刷")
nest_state = getattr(outcome, "nest_state", lambda text: None)
UNREAD = "体力读了 1 次都没有「数/数」，按没读到处理（-1），不当 0"

print("[stamina (a): the weekly boss's and the nest's fights are not stamina farming]")
weekly_only = (line("00:01", "FarmEchoTask", "teleport_to_boss prepared as realm")
               + line("00:20", "FarmEchoTask", "enter combat None")
               + line("01:30", "FarmEchoTask", "start walk_to_treasure")
               + line("02:00", "NightmareNestTask", "enter combat None"))
ok, why = stamina(weekly_only)
check("weekly boss + nest fights only: 刷体力 not passed", ok, False)
check("…and it says nothing was entered", "既没进本" in why)
ok, _ = stamina(weekly_only + line("05:00", "TacetTask", "enter combat None"))
check("a TacetTask fight passes", ok, True)
ok, _ = stamina(weekly_only + line("05:00", "SimulationTask", "start walk_to_treasure"))
check("a SimulationTask walk to the treasure passes", ok, True)
ok, why = stamina(weekly_only + line("05:00", "ForgeryTask", "not enough stamina"))
check("ForgeryTask 「not enough stamina」 with no fight: passed as a shortage", (ok, why), (True, "体力不足，本来就没得刷"))

print("\n[stamina (d): the 「不刷体力」 flag file was there - not farmed, and said why]")
flagged = (weekly_only
           + line("04:00", "TacetTask", "刷体力已禁用（标记文件在），这一趟不花波片")
           + line("06:00", "DailyTask", "Daily Task Completed"))
ok, why = stamina(flagged)
check("the flag line: 刷体力 not passed, with the flag as the reason", (ok, why), (False, "不刷体力的标记还在"))
check("the daily report's stop reason says the same", stopped(flagged), "不刷体力的标记还在")
ok, why = stamina(weekly_only + line("04:00", "ForgeryTask", "刷体力已禁用（标记文件在），这一趟不花波片"))
check("ForgeryTask prefix too", (ok, why), (False, "不刷体力的标记还在"))

print("\n[stamina (b): three revives and upstream stops farming - a failure]")
died = (line("05:00", "TacetTask", "info_set current_stamina 180")
        + line("05:10", "TacetTask", "enter combat None")
        + line("05:40", "TacetTask", "farm_tacet: death recovered, re-enter from F2 book")
        + line("06:10", "TacetTask", "enter combat None")
        + line("06:40", "TacetTask", "farm_tacet: death recovered, re-enter from F2 book")
        + line("07:10", "TacetTask", "enter combat None")
        + line("07:40", "TacetTask", "farm_tacet: exceeded recovery retries (3), stop farming"))
ok, why = stamina(died)
check("farm_tacet exceeded recovery retries: 刷体力 failed", ok, False)
check("…says the character died 3 times and farming stopped", ("死了 3 次" in why, "停止刷体力" in why), (True, True))
check("daily report does not say 「体力不够再开一局」", stopped(died) == "体力不够再开一局", False)
check("daily report gives the same reason", stopped(died), why)
ok, _ = stamina(line("05:00", "ForgeryTask", "enter combat None")
                + line("07:40", "ForgeryTask", "farm_domain: exceeded recovery retries (3), stop farming"))
check("farm_domain exceeded recovery retries: failed too", ok, False)
ok, _ = stamina(line("05:00", "TacetTask", "enter combat None")
                + line("07:40", "FarmEchoTask", "farm 4c: exceeded recovery retries (3), stop farming"))
check("the echo farm's own give-up is not a stamina failure", ok, True)

print("\n[stamina (c): -1 read, then upstream's 「used all stamina」 / 「not enough stamina」]")
tacet_unread = (line("05:00", "TacetTask", UNREAD)
                + line("05:00", "TacetTask", "info_set current_stamina -1")
                + line("05:02", "TacetTask", UNREAD)
                + line("05:02", "TacetTask", "info_set current_stamina -1")
                + line("05:03", "TacetTask", "used all stamina"))
ok, why = stamina(weekly_only + tacet_unread)
check("tacet: -1 twice then 「used all stamina」, no tacet fight: failed", ok, False)
check("…says stamina could not be read", why, UNREAD_SAY)
check("daily report says the same, not 「体力不够再开一局」", stopped(weekly_only + tacet_unread), UNREAD_SAY)
domain_unread = (line("05:00", "SimulationTask", UNREAD)
                 + line("05:00", "SimulationTask", "info_set current_stamina -1")
                 + line("05:01", "SimulationTask", "not enough stamina"))
ok, why = stamina(domain_unread)
check("simulation: -1 then 「not enough stamina」: failed, not 「体力不足」", (ok, why), (False, UNREAD_SAY))
check("daily report does not say 「一局都没开成」", stopped(domain_unread), UNREAD_SAY)
reread = (line("05:00", "TacetTask", UNREAD)
          + line("05:00", "TacetTask", "info_set current_stamina -1")
          + line("05:02", "TacetTask", "info_set current_stamina 30")
          + line("05:03", "TacetTask", "used all stamina"))
ok, why = stamina(reread)
check("tacet: -1, then the click-and-reread got 30, then 「used all stamina」: a real shortage", (ok, why),
      (True, "体力不足，本来就没得刷"))
check("…and the daily report keeps its usual wording", stopped(reread), "体力不够再开一局")
after_fight = (line("05:00", "TacetTask", "info_set current_stamina 180")
               + line("05:10", "TacetTask", "enter combat None")
               + line("06:00", "TacetTask", "体力领奖框读了 3 次都没有「数/数」，按没读到处理（-1），不当 0"))
ok, _ = stamina(after_fight)
check("a -1 in the reward dialog after a tacet fight still passes", ok, True)
ok, _ = stamina(line("05:00", "DailyTask", UNREAD) + line("05:03", "TacetTask", "info_set current_stamina 20")
                + line("05:03", "TacetTask", "used all stamina"))
check("a -1 logged by another task does not taint the tacet shortage", ok, True)

print("\n[nest: an unreachable nest plus another task's traceback is not a fight]")
weekly_err = (FX / "m6-okww" / "0921-weekly.log").read_text(encoding="utf-8")
check("the 0921 log carries click_team_challenge only in traceback frames",
      ("self.click_team_challenge()" in weekly_err, "NightmareNestTask:" in weekly_err), (True, False))
unreachable = (line("00:01", "NightmareNestTask", "opened gray_book_boss")
               + line("00:05", "NightmareNestTask", "nightmare nest unreachable, skip this run: go_nest:48:18")
               + weekly_err)
check("_NEST_ENGAGED does not match", bool(outcome._NEST_ENGAGED.search(unreachable)), False)
got = {c.label: c for c in outcome.okww_checks(unreachable, expect_nest=True, expect_daily=False, expect_stamina=False)}
check("verdict: 残象聚落 not done", got["残象聚落"].ok, False)
check("verdict: says travel failed", "传送不过去" in got["残象聚落"].detail)
step = collector_okww._nest_step(unreachable)
check("daily step is not the bare name (booked as farmed)", step in ("残象聚落", "梦魇巢穴"), False)
check("daily step says travel failed", "传送不过去" in step)
for frame in ("    self.wait_in_team_and_world(time_out=120)\n",
              "    return self.reset_to_false(reason='echo captured')\n"):
    t = line("00:05", "NightmareNestTask", "nightmare nest unreachable, skip this run") + frame
    check(f"a traceback frame {frame.strip()[:30]!r} is no fight", nest_state(t), "unreachable")

print("\n[nest: the step and the verdict read one classifier, in every state]")
SAMPLES = {
    "filter_missing": line("00:01", "NightmareNestTask", outcome._NEST_FILTER_MISSING),
    "not_found": line("00:01", "NightmareNestTask", "nightmare nest: 列表里没找到指定的点位 ['落渊南丘']"),
    "count_unread": line("00:01", "NightmareNestTask", "nightmare nest: " + outcome._NEST_COUNT_UNREAD),
    "full": line("00:01", "NightmareNestTask", "nightmare nest: 指定点位都已打满，跳过"),
    "fought": line("00:01", "NightmareNestTask", "enter combat None"),
    "partly": line("00:01", "NightmareNestTask", "enter combat None")
              + line("00:02", "NightmareNestTask",
                     "nightmare nest: 传送两次都不过去，这一轮不打了 go_nest:48:18（梦枢天罗残象聚落）"),
    "unreachable": line("00:01", "NightmareNestTask", "nightmare nest unreachable, skip this run"),
    "failed": line("00:01", "NightmareNestTask", "opened gray_book_boss")
              + "2026-10-13 10:00:02,000 ERROR TaskExecutor DailyTask:NightmareNestTask Failed\n",
    "quit": line("00:01", "NightmareNestTask", "opened gray_book_boss"),
}
for key, text in SAMPLES.items():
    check(f"{key}: nest_state", nest_state(text), key)
    verdict = [c for c in outcome.okww_checks(text, expect_nest=True, expect_daily=False, expect_stamina=False)
               if c.label.startswith("残象聚落") and not c.label.startswith(("残象聚落只刷", "残象聚落没进"))]
    step = collector_okww._nest_step(text)
    bare = step in ("残象聚落", "梦魇巢穴")
    check(f"{key}: step booked as farmed ⇔ verdict 「残象聚落」 ok", bare,
          bool(verdict) and verdict[0].ok and verdict[0].label == "残象聚落")
    check(f"{key}: step and verdict agree on done / not done", ("已刷满" in step or bare), verdict[0].ok)
check("fought, then the task failed: still booked as fought by both",
      (nest_state(SAMPLES["fought"] + SAMPLES["failed"]),
       collector_okww._nest_step(SAMPLES["fought"] + SAMPLES["failed"])), ("fought", "梦魇巢穴"))

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
