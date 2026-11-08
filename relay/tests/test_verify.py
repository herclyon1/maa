"""Verdicts on a run: activity top-ups, attempt streaks, the claim gate, drops, episodes, a flush that waits for its own script, gathering route nodes, the annihilation health check, Kuro error codes, silent logs, a log slice over the new year, month cards, no-farm visible, unread raw refreshes, revive gates, scans that skip what they saw, setup tasks, the tape, transitional states, the undone fallback, a verdict with no history log, the weekly three claims.

One part per former file, each run on its own (tests/_parts.py): test_activity_topup.py, test_attempts_streak.py, test_claim_no_claim_gate.py, test_drops.py, test_episodes.py, test_flush_waits_own_script.py, test_gathering_route_node_failed.py, test_healthcheck_annihilation.py, test_kuro_error_code.py, test_logfile_silent.py, test_logslice_new_year.py, test_main_logfile_silent.py, test_monthcard.py, test_nofarm_visible.py, test_refresh_raw_unread.py, test_revive_gates.py, test_scan_skips_seen.py, test_setup_tasks_verify.py, test_tape.py, test_transitional.py, test_undone_fallback_full.py, test_verdict_no_history_log.py, test_weekly_three_claims.py.
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


def _part_activity_topup():
    """A waveplate-short daily activity is topped up by the evening shift (features/makeup/activity.py).

2026-10-23: OK-WW started the morning with 98/240 waveplates and no backup (he had spent them
himself), spent 80, and the daily stopped at 80 points; the group got an alarm. His rule (quoted
in activity.py): no alarm, a word in the group, the evening tops it up, an alarm if the evening
fails too. The lines below are that morning's own (ok-script.log 09:28:40-09:29:22); the queues are the machine's (早班
09:00, 晚班 21:30, AUTO-MAS v5.8 YAML).

    Formerly test_activity_topup.py.
    """
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.makeup import activity, makeup
    from ark_relay.features.verify import outcome


    MORNING = """\
2026-10-23 09:28:35,899 INFO TaskExecutor BaseWWTask:当前体力大于等于双倍, 99 >= 80
2026-10-23 09:28:40,123 INFO TaskExecutor BaseWWTask:current stamina: 19 not enough to continue
2026-10-23 09:28:44,124 INFO TaskExecutor ForgeryTask:used all stamina
2026-10-23 09:29:13,332 INFO TaskExecutor DailyTask:活跃奖励：活跃度 80
2026-10-23 09:29:22,684 INFO TaskExecutor DailyTask:活跃奖励：领完核对通过（活跃度 80，已领 20、40、60、80，各档对勾分 20:0.97，40:0.93，60:0.98，80:0.96，100:0.49）
"""
    QUEUES = """\
order:
- uid: q1
  type: QueueConfig
- uid: q2
  type: QueueConfig
data:
  q1:
    Info:
      Name: 早班
      TimeEnabled: true
    TimeSet:
      order:
      - uid: t1
        type: TimeSet
      data:
        t1:
          Info:
            Enabled: true
            Time: '2000-01-01T01:00:00Z'
    QueueItem:
      order:
      - uid: i1
        type: QueueItem
      data:
        i1:
          Info:
            ScriptId: okww
  q2:
    Info:
      Name: 晚班
      TimeEnabled: true
    TimeSet:
      order:
      - uid: t2
        type: TimeSet
      data:
        t2:
          Info:
            Enabled: true
            Time: '2000-01-01T13:30:00Z'
    QueueItem:
      order:
      - uid: i2
        type: QueueItem
      data:
        i2:
          Info:
            ScriptId: maa
"""


    def at(hh, mm):
        return datetime(2026, 10, 23, hh, mm, tzinfo=SERVER_TZ)


    def setup():
        root = tmpdir()
        (root / "config").mkdir()
        (root / "config" / "queues.yaml").write_text(QUEUES, encoding="utf-8")
        group = []
        eng = types.SimpleNamespace(
            cfg=types.SimpleNamespace(state_dir=tmpdir(), automas_dir=root),
            notifier=types.SimpleNamespace(
                send_group=lambda t, b: (group.append((t, b)), [])[1],
                send=lambda t, b, alert=False: (group.append(("ALARM " + t if alert else t, b)), [])[1]))
        return eng, group


    def rec(run_id, start, end):
        return types.SimpleNamespace(script="OK-WW", run_id=run_id, started=start, finished=end)


    print("[早班：波片用完、活跃 80 → 不报警，群里说一声，记下晚班 21:30 补]")
    eng, group = setup()
    checks = outcome.daily_reward_checks(MORNING)
    check("没改之前：活跃这一项是没干完", [c.ok for c in checks if c.label == activity.LABEL], [False])
    activity.morning(eng, rec("OK-WW-05-16-50", at(9, 18), at(9, 30)), MORNING, checks)
    item = next(c for c in checks if c.label == activity.LABEL)
    check("这一项不再算没干完（不进「这一轮没干完」）", item.ok, True)
    check("账上写着早班几分、晚班几点补", ("早班 80 分" in item.detail, "21:30" in item.detail), (True, True))
    check("整轮判下来没有没干完的项", outcome.summarize(checks, "OK-WW"), None)
    check("群里说了一声（通知，不是报警）", [t for t, _ in group], ["🔁 鸣潮早班活跃没满，晚班补"])
    check("那一声里有分数和晚班时刻", ("80 分" in group[0][1], "21:30" in group[0][1], "晚班还没满会再报" in group[0][1]),
          (True, True, True))
    booked = activity.read(eng.cfg.state_dir, "2026-10-23")
    check("记下了晚班的时刻", booked.get("due", "")[11:16], "21:30")
    checks2 = outcome.daily_reward_checks(MORNING)
    activity.morning(eng, rec("OK-WW-05-16-50", at(9, 18), at(9, 30)), MORNING, checks2)
    check("同一条记录再判一次（重放）：群里不再说第二遍", len(group), 1)
    check("…而且已经记过的这一天，再短就照常算没干完", [c.ok for c in checks2 if c.label == activity.LABEL], [False])

    print("\n[不是波片不够、或者今天后面没有排期：照常报]")
    eng2, group2 = setup()
    c = outcome.daily_reward_checks("2026-10-23 09:29:13,332 INFO TaskExecutor DailyTask:活跃奖励：活跃度 80\n")
    activity.morning(eng2, rec("r2", at(9, 18), at(9, 30)), "活跃奖励：活跃度 80", c)
    check("日志里没说波片用完 → 还是没干完、群里不说", ([x.ok for x in c if x.label == activity.LABEL], group2), ([False], []))
    eng3, group3 = setup()
    c = outcome.daily_reward_checks(MORNING)
    activity.morning(eng3, rec("r3", at(21, 30), at(21, 45)), MORNING, c)
    check("晚班之后才短（今天没有下一班）→ 照常报", ([x.ok for x in c if x.label == activity.LABEL], group3), ([False], []))

    print("\n[到点、空闲才派；派一次；等它出结果才关机 / 发日报]")
    sent = []
    makeup._dispatch = lambda script: (sent.append(script), (True, "脚本「OK-WW」已单独开跑"))[1]
    blocked = {"why": ""}
    makeup._blocked = lambda e, now: blocked["why"]
    import ark_relay.core.engine as _engine
    _engine.forget_scripts_cache = lambda: None
    check("21:30 之前：不派", activity.maybe_run(eng, at(12, 0)), False)
    check("21:30 之前：关机和日报不等它（早班照常关机）", activity.holding(eng, at(12, 0)), "")
    check("醒来的时刻是 21:30", activity.next_moment(eng.cfg.state_dir, at(12, 0))[0], at(21, 30))
    check("21:30 到了：关机和日报等它", activity.holding(eng, at(21, 31)), "鸣潮活跃晚班补还没完")
    blocked["why"] = "队列「晚班」还差 MAA"
    check("晚班 MAA 还在跑：先不派", (activity.maybe_run(eng, at(21, 31)), sent), (False, []))
    blocked["why"] = ""
    check("跑完空闲了：派鸣潮一次", (activity.maybe_run(eng, at(21, 50)), sent), (True, ["OK-WW"]))
    check("派过就不再派", (activity.maybe_run(eng, at(22, 0)), sent), (False, ["OK-WW"]))
    check("还没出结果：继续等", activity.holding(eng, at(22, 0)), "鸣潮活跃晚班补还没完")
    _tr = rec("OK-WW-13-50-00", at(21, 50), at(21, 52))
    _tr.transitional = True
    activity.on_record(eng, _tr)
    check("audit 11-08 B-07: a 「游戏更新成功，即将重启任务」 record is not the top-up's", activity.holding(eng, at(21, 53)),
          "鸣潮活跃晚班补还没完")
    activity.on_record(eng, rec("OK-WW-13-50-12", at(21, 50), at(22, 5)))
    check("补的那一趟记录到了：不再等", activity.holding(eng, at(22, 6)), "")
    ev = outcome.daily_reward_checks(MORNING)
    activity.morning(eng, rec("OK-WW-13-50-12", at(21, 50), at(22, 5)), MORNING, ev)
    check("补完还没满：照常是没干完（「这一轮没干完」报警）", [c.ok for c in ev if c.label == activity.LABEL], [False])
    check("群里没有多出一句「晚班补」", len(group), 1)

    print("\n[晚班没补成也是没满：派不下去、派了没记录、那晚没开机，都报一次警]")
    eng4, group4 = setup()
    activity.morning(eng4, rec("r4", at(9, 18), at(9, 30)), MORNING, outcome.daily_reward_checks(MORNING))
    makeup._dispatch = lambda script: (False, "调度程序没回应")
    t = at(21, 40)
    results = []
    for k in range(3):
        activity.maybe_run(eng4, t)
        results.append(activity.read(eng4.cfg.state_dir, "2026-10-23").get("result"))
        t += timedelta(seconds=activity.RETRY_GAP_S + 1)
    check("前两次记「派不下去」、第三次放手", results, ["couldnt_run", "couldnt_run", "gave_up"])
    check("放手后关机和日报不再等", activity.holding(eng4, t), "")
    alarms = [b for tt, b in group4 if tt.startswith("ALARM ⚠️ 这一轮没干完")]
    check("三次没派下去：报一次警，说清没满和为什么", (len(alarms), "80 分" in alarms[0], "没派下去" in alarms[0]),
          (1, True, True))
    activity.maybe_run(eng4, t + timedelta(minutes=30))
    check("不重复报", len([1 for tt, _ in group4 if tt.startswith("ALARM")]), 1)
    eng5, group5 = setup()
    activity.morning(eng5, rec("r5", at(9, 18), at(9, 30)), MORNING, outcome.daily_reward_checks(MORNING))
    makeup._dispatch = lambda script: (True, "ok")
    activity.maybe_run(eng5, at(21, 40))
    late = at(21, 40) + activity.STALE + timedelta(minutes=1)
    check("派了但一直没有记录：过了 STALE 不再等", activity.holding(eng5, late), "")
    activity.maybe_run(eng5, late)
    check("…并且报一次警（派了没记录）", [("还没有这一趟的记录" in b) for tt, b in group5 if tt.startswith("ALARM")], [True])
    eng6, group6 = setup()
    activity.morning(eng6, rec("r6", at(9, 18), at(9, 30)), MORNING, outcome.daily_reward_checks(MORNING))
    activity.maybe_run(eng6, datetime(2026, 10, 24, 9, 0, tzinfo=SERVER_TZ))
    check("那晚没开机、第二天才醒：报一次警（晚班没补上）",
          [("晚班没补上" in b) for tt, b in group6 if tt.startswith("ALARM")], [True])


def _part_attempts_streak():
    """「重试 N 次全部失败」 counts the failed streak of this shift, not the whole day.

Real MAA rows of 2026-10-10 (tests/fixtures/ledger-2026-10-10-maa.jsonl, copied
from the machine's ledger): three morning failures (alarmed at 09:03:39 as
「重试 3 次」), a person's own run at 12:05 and the evening run at 21:30. Had the
evening run failed once, the old count (every row of the day) said 5 (audit
2026-10-13 s7 #4 / s1 #1).

    Formerly test_attempts_streak.py.
    """
    import json
    import tempfile
    import types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import RunRecord
    from ark_relay.features.alarm import records

    FIX = Path(__file__).parent / "fixtures" / "ledger-2026-10-10-maa.jsonl"


    def rec_of(e: dict) -> RunRecord:
        return RunRecord(run_id=e["run_id"], script=e["script"], user=e["user"], ok=e["ok"],
                         started=datetime.fromisoformat(e["started"]),
                         finished=datetime.fromisoformat(e["finished"]),
                         failed_tasks=list(e["failed_tasks"]), raw=dict(e["raw"]),
                         transitional=e["transitional"])


    real = [json.loads(line) for line in FIX.read_text(encoding="utf-8").splitlines()]
    with tempfile.TemporaryDirectory() as td:
        def eng_of(rows):
            return types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=None, state_dir=td),
                                         state=types.SimpleNamespace(read_ledger=lambda day: rows))

        print("[the real morning alarm: three failures in a row]")
        check("MAA-05-02-18 -> 3", records._attempts(eng_of(real), rec_of(real[2]), "2026-10-10"), 3)

        print("\n[the evening run failing once: the morning and a person's run are not its tries]")
        evening = dict(real[4], ok=False, failed_tasks=["MAA 在完成任务前中止"])
        rows = real[:4] + [evening]
        check("evening failure -> 1, not 5", records._attempts(eng_of(rows), rec_of(evening), "2026-10-10"), 1)

        print("\n[a success earlier in the same shift ends the streak before it]")
        again = dict(evening, run_id="2026-10-10/arknights/MAA-18-10-00",
                     started="2026-10-10T22:10:00+08:00", finished="2026-10-10T22:11:00+08:00")
        rows = real + [again]
        check("failure after the 21:30 success -> 1", records._attempts(eng_of(rows), rec_of(again), "2026-10-10"), 1)

        print("\n[a healed streak counts up to the success that healed it]")
        check("morning healed later -> 3", records._attempts(eng_of(real), rec_of(real[0]), "2026-10-10"), 3)

        print("\n[a retry that got through counts as the last try (「跑了 N 次」)]")
        healed = dict(real[2], run_id="2026-10-10/arknights/MAA-05-10-00", ok=True, failed_tasks=[],
                      started="2026-10-10T09:10:00+08:00", finished="2026-10-10T09:30:00+08:00")
        rows = real[:3] + [healed] + real[3:]
        check("three failures and the success -> 4", records._attempts(eng_of(rows), rec_of(real[0]), "2026-10-10"), 4)

    print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")


def _part_claim_no_claim_gate():
    """The claim patch must never spend waveplates while the 4-cost echo farm runs.

Claiming a boss reward costs 60 waveplates every time. Farming echoes is free. On
2026-09-09 the time-bounded farm was wired onto the very branch that claims, so an
unattended overnight run would have drained the waveplates and then the reserve.
The gate is a marker file the relay writes while farming; this pins both halves of
it together so neither can drift away from the other.

Since 2026-09-09 (d035709a) the gate lives in the ok_tasks overlay's incr_drop (the
old text patch and the code that restored it were removed 2026-10-12), so the gate is
tested on the overlay that actually runs.

    Formerly test_claim_no_claim_gate.py.
    """
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.echofarm import echofarm
    from ark_relay.features.okww_patch import okww_overlay


    class FarmEchoTask:
        def incr_drop(self, dropped):
            self.events.append("upstream-incr")

        def handle_claim_button(self):
            # Upstream's own (BaseWWTask.handle_claim_button): ESC, i.e. 取消.
            self.events.append("upstream-esc")
            return True


    _mods = {"src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
             "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=FarmEchoTask)}
    _saved = {k: sys.modules.get(k) for k in _mods}
    sys.modules.update(_mods)
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    ns["_install_claim"]()
    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


    class Task(FarmEchoTask):
        """Inside the weekly realm right after a fight: everything the claim would touch."""
        def __init__(self, boss="Weekly Challenge"):
            self.events, self._in_realm = [], True
            self.config = {"Teleport to Boss": boss}
            for name in ("in_world", "walk_to_treasure", "pick_f", "click_dialog_right_button", "ocr",
                         "send_key", "back", "click", "teleport_to_configured_boss_and_prepare"):
                setattr(self, name, (lambda n: lambda *a, **kw: self.events.append(n))(name))
            self.in_world = lambda: False
            self.wait_until = lambda cond, **kw: cond()
            self.find_treasure_icon = lambda: True
            self.log_info = lambda msg: self.events.append(f"log:{msg}")


    print("[改动文件里的闸：挂着标记时，打完周本什么都不碰]")
    flag = tmpdir() / "ark-okww-farm.no-claim"
    ns["NO_CLAIM"] = str(flag)
    flag.write_text("farming 4c echoes\n", encoding="utf-8")
    try:
        t = Task()
        t.incr_drop(True)
    finally:
        flag.unlink()
    check("上游的掉落计数照跑", t.events[:1], ["upstream-incr"])
    check("没走去结晶、没按 F、没点确认、没重进", t.events[1:], [])
    flag.write_text("farming 4c echoes\n", encoding="utf-8")
    try:
        t = Task()
        t.handle_claim_button()
    finally:
        flag.unlink()
    check("挂着标记时领奖弹窗照上游按 ESC（取消），不点确认", t.events, ["upstream-esc"])
    t = Task()
    t.ocr = lambda *a, **kw: []
    t.box_of_screen = lambda *a: None
    t.sleep = lambda s: None
    t.log_error = lambda msg, notify=False: t.events.append(f"err:{msg}")
    t.incr_drop(True)
    check("摘掉标记：同一圈会去结晶按 F（闸真的是那个文件）", [e for e in t.events if not e.startswith("log:")][1:3],
          ["walk_to_treasure", "pick_f"])
    check("按 F 后没领到（这里假的 pick_f 什么都没弹）：不停、不报错、不重进",
          [e for e in t.events if e.startswith("err:") or e == "teleport_to_configured_boss_and_prepare"], [])

    print("[中继写的路径和改动文件读的路径是同一个]")
    name = Path(echofarm.NO_CLAIM.replace("\\", "/")).name
    check(f"文件名一致（{name}）", Path(okww_overlay.source_text().split('NO_CLAIM = "')[1].split('"')[0]).name, name)

    print("[刷强敌（Boss Challenge）时领奖钩子本来就不碰；刷周本（10-22 起）靠上面那道标记；上游自己退本再按 F 重进]")
    t = Task(boss="Boss Challenge")
    t.incr_drop(True)
    check("强敌：只跑上游的掉落计数", t.events, ["upstream-incr"])
    t = Task(boss="Boss Challenge")
    t.handle_claim_button()
    check("强敌：领奖弹窗照上游按 ESC", t.events, ["upstream-esc"])
    _src = Path(echofarm.__file__).read_text(encoding="utf-8")
    check("中继刷强敌写的是 Boss Challenge", '"Boss Challenge"' in _src)
    # A weekly-boss farm writes Weekly Challenge, where only the marker keeps the claim hooks off: the marker must be up
    # before OK-WW starts, on the one start path both kinds take.
    check("刷周本也是先挂标记再启动（同一个 start）",
          0 <= _src.index("_set_no_claim(True)") < _src.index("ok, why = _launch()"))
    check("不补「不退本按 F 重进」的理由写在钩子里", "enter_configured_boss_realm_from_f" in okww_overlay.source_text()
          and "FarmEchoTask.py:147-152" in okww_overlay.source_text())


def _part_drops():
    """MAA's drop blocks carry a running total per stage. Both directions are easy
to get wrong, and both have been wrong in production.

The log lines here are the real format, taken from a 2026-08-15 run:

    [2026-08-15 09:06:29.091][INF][TaskQueueViewModel]     <2> TO-5 掉落统计: 
    龙门币 : 864 (+864)
    [2026-08-15 09:06:58.883][INF][TaskQueueViewModel]     <2> 完成任务: 理智作战

The stage line carries a bracketed timestamp; the item lines do not, and the
next timestamped line is what closes the block. An earlier version of this file
used timestamps without brackets, which `_HAS_TS` does not match - so the block
never closed and the tests passed without exercising the real path.

    Formerly test_drops.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector


    P = "[INF][TaskQueueViewModel]     <2>"
    def ts(hhmmss: str, rest: str) -> str:
        return f"[2026-08-15 {hhmmss}.091]{P} {rest}"

    def parse(log: str) -> dict:
        p = tmpdir() / "run.log"
        p.write_text(log, encoding="utf-8")
        return collector.parse_maa_log(p)

    print("[sanity: the real format parses at all]")
    out = parse("\n".join([
        ts("09:04:12", "开始行动 1~6 次, -72理智"),
        ts("09:06:29", "TO-5 掉落统计: "),
        "龙门币 : 864 (+864)",
        ts("09:06:58", "完成任务: 理智作战"),
    ]))
    check("stage found", out.get("stages"), ["TO-5"])
    check("drop found", out.get("drop_statistics"), {"龙门币": 864})
    check("sanity spent", out.get("sanity_spent"), 72)

    print("\n[one stage, two batches - running total, take the last]")
    out = parse("\n".join([
        ts("09:04:12", "开始行动 1~10 次, -120理智"),
        ts("09:25:00", "TO-5 掉落统计: "),
        "龙门币 : 1440 (+1440)",
        "技巧概要·卷2 : 2 (+2)",
        "当前次数 : 10",
        ts("09:26:00", "开始行动 11~17 次, -84理智"),
        ts("09:45:00", "TO-5 掉落统计: "),
        "龙门币 : 2448 (+1008)",
        "技巧概要·卷2 : 4 (+2)",
        "当前次数 : 7",
        ts("09:46:00", "完成任务: 理智作战"),
    ]))
    check("龙门币 = last block, not the sum", out["drop_statistics"]["龙门币"], 2448)
    check("技巧概要·卷2", out["drop_statistics"]["技巧概要·卷2"], 4)
    check("次数 IS summed", out.get("run_times"), 17)
    check("one stage", out.get("stages"), ["TO-5"])
    check("sanity summed", out.get("sanity_spent"), 204)

    print("\n[two different stages - totals are per stage, summed across]")
    out = parse("\n".join([
        ts("21:32:00", "剿灭作战 掉落统计: "),
        "龙门币 : 500 (+500)",
        "当前次数 : 1",
        ts("21:34:00", "完成任务: 剿灭作战"),
        ts("22:10:00", "1-7 掉落统计: "),
        "龙门币 : 2448 (+2448)",
        "当前次数 : 17",
        ts("22:11:00", "完成任务: 理智作战"),
    ]))
    check("龙门币 summed ACROSS stages", out["drop_statistics"]["龙门币"], 2948)
    check("both stages", out.get("stages"), ["剿灭作战", "1-7"])
    check("次数 summed", out.get("run_times"), 18)

    print("\n[two stages, two batches each - both rules at once]")
    out = parse("\n".join([
        ts("09:00:00", "剿灭作战 掉落统计: "),
        "龙门币 : 300 (+300)",
        ts("09:05:00", "剿灭作战 掉落统计: "),
        "龙门币 : 500 (+200)",
        ts("09:10:00", "1-7 掉落统计: "),
        "龙门币 : 1000 (+1000)",
        ts("09:20:00", "1-7 掉落统计: "),
        "龙门币 : 2448 (+1448)",
        ts("09:21:00", "完成任务: 理智作战"),
    ]))
    check("500 + 2448", out["drop_statistics"]["龙门币"], 2948)

    print("\n[a timestamped line really does close the block]")
    # If it did not, 完成任务 and everything after would keep feeding the block.
    out = parse("\n".join([
        ts("09:10:00", "1-7 掉落统计: "),
        "龙门币 : 1000 (+1000)",
        ts("09:11:00", "完成任务: 理智作战"),
        "龙门币 : 9999 (+8999)",
    ]))
    check("stray line after the block ignored", out["drop_statistics"]["龙门币"], 1000)

    print("\n[medicine]")
    out = parse("\n".join([
        ts("09:04:03", "已使用理智药 1(+1)"),
        ts("09:10:00", "1-7 掉落统计: "),
        "龙门币 : 1000 (+1000)",
        ts("09:11:00", "完成任务: 理智作战"),
    ]))
    check("medicine used", out.get("medicine_used"), 1)

    print("\n[no drops at all]")
    out = parse(ts("21:30:00", "开始任务") + "\n" + ts("21:31:00", "任务完成"))
    check("no key", "drop_statistics" in out, False)

    print("\n[MAA's ~9000-character 「Request body:」 lines: parsed fast, same result]")
    # The stage-drop pattern `(\S+)\s*掉落统计` backtracked quadratically over a long run
    # of non-blanks: 1.3 s for one such line, 6.6 s for this file (2026-09-07 morning).
    import time
    from ark_relay.features.verify import collector_maa
    REPLAY = Path(__file__).resolve().parent / "replay" / "2026-09-07" / "arknights" / "MAA-05-03-55.log"
    real = REPLAY.read_text(encoding="utf-8", errors="replace")
    body = max(real.splitlines(), key=len)
    check("the real line is a long Request body", (len(body) > 9000, "Request body:" in body), (True, True))
    t0 = time.perf_counter()
    got = collector_maa._maa_scan_lines(body)
    check("one such line scans in well under 0.1 s", time.perf_counter() - t0 < 0.1, True)
    check("and yields nothing, as before (it holds no 掉落统计)", got, ({}, [], 0, 0, 0))
    t0 = time.perf_counter()
    got = collector_maa._maa_scan_lines(real)
    check("the whole file scans in under a second", time.perf_counter() - t0 < 1.0, True)
    # What the old code gave for this file (measured before the change, 6.6 s).
    check("same stages, drops, sanity and runs as before", got,
          ({"SR-5": {"龙门币": 720, "旧磁带": 60, "糖": 4, "装置": 2, "倒吊人": 1}}, ["SR-5"], 60, 0, 5))
    t0 = time.perf_counter()
    got = collector_maa._maa_scan_lines(body + "\n" + ts("09:06:29", "TO-5 掉落统计: ") + "\n龙门币 : 864 (+864)\n"
                                        + ts("09:06:58", "完成任务: 理智作战"))
    check("a drop block after such a line still parses, fast",
          (got[0], got[1], time.perf_counter() - t0 < 0.1), ({"TO-5": {"龙门币": 864}}, ["TO-5"], True))


def _part_episodes():
    """假报警两例（2026-09-02 早班实录）：

鸣潮：09:18 客户端更新重启（transitional）、09:20 失败、09:28 成功 →
      日报写了两个 ❌ 还推了 ⚠️ 自愈。应当整串算「更新插曲」：↪️、不计失败。
终末地：服务器维护，三趟每个任务 20 秒内失败、零完成 → 报了三次失败。
      应当认出「进不了游戏」：⏸、不计失败、只发一条说明。

    Formerly test_episodes.py.
    """
    import json
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.features.maintenance import efstatus
    from ark_relay.core import ledger as core
    from ark_relay.core.config import SERVER_TZ


    print("[maaend_unreachable：任务全部秒败、零完成]")
    def maaend_log(gap_s=20, done_at=None, n=4):
        t = datetime(2026, 9, 2, 9, 56, 23)
        names = ["🎁赠送干员礼物", "🔧装备制造", "🤝拜访好友", "🎁基建任务", "🛍️信用点购物"][:n]
        out = []
        for i, nm in enumerate(names):
            out.append(f"[{t:%Y-%m-%d %H:%M:%S}.249] 任务开始: {nm}")
            t += timedelta(seconds=gap_s)
            kind = "完成" if done_at == i else "失败"
            out.append(f"[{t:%Y-%m-%d %H:%M:%S}.717] 任务{kind}: {nm}")
        out.append(f"[{t:%Y-%m-%d %H:%M:%S}.145] 任务开始: ⛔ 结束进程")
        out.append(f"[{t:%Y-%m-%d %H:%M:%S}.595] 任务失败: ⛔ 结束进程")
        return "\n".join(out)
    check("今天的形状 → 进不了游戏", collector.maaend_unreachable(maaend_log()), True)
    check("有一个完成 → 不是", collector.maaend_unreachable(maaend_log(done_at=1)), False)
    check("每个卡 5 分钟 → 不是（那是真故障）", collector.maaend_unreachable(maaend_log(gap_s=300)), False)
    check("只败 2 个 → 不够数", collector.maaend_unreachable(maaend_log(n=2)), False)
    check("结束进程那条不算", "结束进程" in maaend_log(), True)
    # The shape is not proof (a lost game window or a crash at the title screen
    # looks the same): the parser only records the shape; handle._confirm_unreachable
    # sets maaend_unreachable, the flag that silences, on official evidence only.
    import tempfile
    with tempfile.TemporaryDirectory() as _d:
        _p = Path(_d) / "MaaEnd-09-56-23.log"
        _p.write_text(maaend_log(), encoding="utf-8")
        _raw = collector.parse_maaend_log(_p)
    check("解析只记形状", _raw.get("maaend_unreachable_shape"), True)
    check("解析不直接判进不了游戏", "maaend_unreachable" in _raw, False)

    print("[episode_kinds + 日报]")
    def ent(run_id, script, hh, mm, dur, ok, transitional=False, raw=None, failed=None):
        st = datetime(2026, 9, 2, hh, mm, tzinfo=SERVER_TZ)
        return {"run_id": run_id, "script": script, "user": "u", "ok": ok,
                "started": st.isoformat(), "finished": (st + timedelta(minutes=dur)).isoformat(),
                "duration_known": True, "transitional": transitional,
                "failed_tasks": failed or ([] if ok else ["x"]), "raw": raw or {}}
    today = [
        ent("maa", "MAA", 9, 0, 17, True),
        ent("ww1", "OK-WW", 9, 18, 1, False, transitional=True),
        ent("ww2", "OK-WW", 9, 20, 7, False, failed=["OK-WW 流程产生错误，请检查游戏状态"]),
        ent("ww3", "OK-WW", 9, 28, 13, True),
        ent("ef1", "MaaEnd", 9, 42, 6, False, raw={"maaend_unreachable": True}),
        ent("ef2", "MaaEnd", 9, 49, 6, False, raw={"maaend_unreachable": True}),
        ent("ef3", "MaaEnd", 9, 56, 5, False, raw={"maaend_unreachable": True}),
    ]
    k = core.episode_kinds(today)
    check("更新重启那条", k.get("ww1"), "update")
    check("紧跟的失败也是插曲", k.get("ww2"), "update")
    check("成功那条不标", k.get("ww3"), None)
    check("终末地三条都是维护", [k.get(x) for x in ("ef1", "ef2", "ef3")], ["maintenance"] * 3)
    title, body = core.format_daily("2026-09-02", today)
    check("标题不再是 5 项失败", "维护日跳过，其余全绿 ✅" in title, True)
    check("没有 ❌", "❌" in body, False)
    check("鸣潮画 ↪️", body.count("↪️ 鸣潮"), 2)
    check("终末地画 ⏸", body.count("⏸ 终末地"), 3)
    check("插曲说明", "游戏更新后重跑，不算失败" in body, True)
    # 2026-09-12 09:21: the dialog was the anti-cheat module refreshing, no client file
    # changed - the note must not claim the game updated.
    for change, files, want in (("anticheat", ["AntiCheatExpert\\pld.dat"], "游戏更新成功（只更新了反作弊组件），重启后重跑，不算失败"),
                                ("none", [], "游戏弹了「即将重启」但客户端文件没有变，重启后重跑，不算失败"),
                                ("patch", ["Content\\Paks\\pakchunk0.pak"], "游戏更新成功（更新了客户端文件），重启后重跑，不算失败"),
                                ("unknown", [], "游戏弹了「即将重启」，重启后重跑；客户端有没有换文件没查到，不算失败")):
        ace = [ent("w1", "OK-WW", 9, 20, 1, False, transitional=True, raw={"okww_restart_dialog": True, "okww_client_change": change, "okww_client_files": files}),
               ent("w2", "OK-WW", 9, 22, 15, True)]
        tech: list = []
        _, bace = core.format_daily("2026-09-12", ace, tech=tech)
        # File names go to the technical log, not the report (D-1010).
        check(f"重启弹窗：{change} 换了的文件进技术日志、不进日报",
              (all(f in " ".join(tech) for f in files), any(f in bace for f in files)), (True, False))
        check(f"重启弹窗：{change} 的说法是定论不是猜测", want in bace and "多半" not in bace, True)
    check("维护说明", "进不了游戏" in body, True)

    print("[终末地只差自动采集 / 应急理智加强剂：照样算失败（2026-10-06 起，之前是 🟡 不计失败）]")
    # The user, 2026-10-06: 「不论多少次什么错误都要发」 - the soft kind is gone: such a run is
    # alarmed on, and the daily report says it failed, with the routes named
    # (the user asked on 2026-09-12: 「没做成哪些，做成了哪些」).
    soft = [ent("m", "MAA", 9, 0, 17, True), ent("s", "MaaEnd", 9, 28, 50, False, failed=["应急理智加强剂", "自动采集"],
                raw={"maaend_collect_done": 13, "maaend_collect_total": 15, "maaend_collect_failed": ["路线15：红矛叶", "路线16：协议纹石"]})]
    check("不再分成 soft", core.episode_kinds(soft).get("s"), None)
    ts, bs = core.format_daily("2026-09-03", soft)
    check("标题算失败", "终末地失败 1 次 ⚠️" in ts, True)
    check("画 ❌ 并点名没走通的路线", "❌ 终末地" in bs
          and "失败于：应急理智加强剂、自动采集；自动采集 13/15 条走通，没走通：路线15：红矛叶、路线16：协议纹石" in bs, True)
    check("不再写「不算失败」「上游问题」", ("不算失败" in bs, "上游问题" in bs, "个别上游项" in ts), (False, False, False))
    md = [ent("u", "MAA", 9, 0, 17, False, failed=["开始唤醒"], raw={"maintenance_day": True})]
    check("更新日的明日方舟失败也算失败", (core.episode_kinds(md), "明日方舟没跑成" in core.format_daily("2026-09-03", md)[0]),
          ({}, True))

    print("[真故障不能被顺手洗白]")
    real = [ent("a", "OK-WW", 9, 18, 7, False), ent("b", "OK-WW", 9, 28, 13, True)]
    check("没有更新重启的失败→不是插曲", core.episode_kinds(real), {})
    t2, b2 = core.format_daily("2026-09-02", real)
    check("标题说鸣潮没跑成（一趟什么都没做成的失败）", "鸣潮没跑成 ⚠️" in t2, True)
    streak_no_success = [ent("a", "OK-WW", 9, 18, 1, False, transitional=True), ent("b", "OK-WW", 9, 20, 7, False)]
    check("更新重启后最终没成功→仍是失败", core.episode_kinds(streak_no_success), {})

    print("[官方公告：今天是不是版本更新日]")
    data = json.loads((Path(__file__).parent / "fixtures" / "ef_bulletin_2026-09-02.json").read_text(encoding="utf-8"))
    hint = efstatus.update_hint(datetime(2026, 9, 2, 10, 30, tzinfo=SERVER_TZ), fetch=lambda: data)
    check("认出今天 10:00 版本更新", hint, "官方公告：今天 09:00 「雪凇幽梦」版本更新")
    check("别的日子→空", efstatus.update_hint(datetime(2026, 9, 3, 10, 30, tzinfo=SERVER_TZ), fetch=lambda: data), "")
    check("接口挂了→空不炸", efstatus.update_hint(fetch=lambda: (_ for _ in ()).throw(OSError())), "")


def _part_flush_waits_own_script():
    """A held failure alarm waits only for its own script, never for the whole queue.

2026-10-01 morning shift: OK-WW timed out three times in a row, two hours each
(09:18 / 11:20 / 13:21), and AUTO-MAS wrote all three records at 15:23:06. The
relay held the failure, and _flush_pending's first line returned while anything
was running - MaaEnd started at 15:23, so the alarm stayed held. At 17:12 the
user asked why a shift due to end four hours earlier was still stuck.

Replayed here with that day's shape: three OK-WW failures plus the real
runtime-snapshot read on the machine at 16:11 (MAA done, OK-WW failed, MaaEnd running).
Before the fix nothing is pushed; after it, exactly one alarm.

    Formerly test_flush_waits_own_script.py.
    """
    import json
    import os
    from datetime import datetime


    TMP = tmpdir()
    AUTOMAS = TMP / "AUTO-MAS"
    (AUTOMAS / "config").mkdir(parents=True)
    (AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    (AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
    HIST = TMP / "history"
    HIST.mkdir()
    os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State


    class Notes:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", **kw):
            self.sent.append((title, body, kw.get("alert", False)))
            return False


    class Src:
        def fetch(self, seen):
            return []


    def snap(okww, maaend):
        """The runtime-snapshot read on the machine at 2026-10-01 16:11, two statuses swapped in."""
        return {"tasks": [{"taskId": "8f47a684", "mode": "AutoProxy", "stopping": False,
                           "task_info": [
                               {"name": "MAA", "status": "完成", "userList": [{"name": "arknights", "status": "完成"}]},
                               {"name": "OK-WW", "status": okww, "userList": [{"name": "wuwa", "status": okww}]},
                               {"name": "MaaEnd", "status": maaend, "userList": [{"name": "endfield", "status": maaend}]}]}],
                "scheduledScripts": []}


    TODAY = snap("异常", "运行")


    def okww_rounds():
        """That day's three rounds: two hours each, written together at 15:23:06."""
        out = []
        for run_id, a, b in (("2026-10-01/wuwa/OK-WW-05-18-20", (9, 18), (11, 20)),
                             ("2026-10-01/wuwa/OK-WW-07-20-22", (11, 20), (13, 21)),
                             ("2026-10-01/wuwa/OK-WW-09-21-22", (13, 21), (15, 23))):
            out.append(RunRecord(run_id=run_id, script="OK-WW", user="wuwa",
                                 started=datetime(2026, 10, 1, *a, tzinfo=SERVER_TZ),
                                 finished=datetime(2026, 10, 1, *b, tzinfo=SERVER_TZ),
                                 ok=False, failed_tasks=["OK-WW 运行超时"], raw={}))
        return out


    def build(snapshot):
        cfg = Config()
        cfg.state_dir = tmpdir()
        e = eng.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes())
        # The queue-wide check answers truthfully (MaaEnd running -> busy), as on the machine
        e._scripts_running = lambda: True if snapshot is None else eng._judge_snapshot(snapshot)
        eng._automas_snapshot = lambda: snapshot
        for r in okww_rounds():
            e._pending[(r.script, r.user)] = r          # a later round replaces the earlier one, as in _hold_for_retry
        return e


    real_win, real_snapshot = eng.config.IS_WINDOWS, getattr(eng, "_automas_snapshot", None)
    try:
        eng.config.IS_WINDOWS = True

        print("[10-01 回放：OK-WW 已「异常」、MaaEnd 还在跑 → OK-WW 的告警现在就推]")
        e = build(TODAY)
        e._flush_pending()
        alarms = [t for t, _, alert in e.notifier.sent if alert]
        check("推了一条真报警", len(alarms), 1)
        check("推的是 OK-WW", any("OK-WW" in t or "鸣潮" in t for t in alarms), True)
        check("推完从待推里拿掉", dict(e._pending), {})

        print("\n[OK-WW 自己还在重试 → 照旧等它]")
        e = build(snap("运行", "等待"))
        e._flush_pending()
        check("一条都不推", e.notifier.sent, [])
        check("还在待推里", list(e._pending), [("OK-WW", "wuwa")])

        print("\n[OK-WW 排着队还没轮到（等待）→ 也算在跑]")
        e = build(snap("等待", "等待"))
        e._flush_pending()
        check("一条都不推", e.notifier.sent, [])

        print("\n[问不到 AUTO-MAS → 退回整条队列的判断，宁可多等]")
        e = build(None)
        e._flush_pending()
        check("一条都不推", e.notifier.sent, [])
        check("还在待推里", list(e._pending), [("OK-WW", "wuwa")])

        print("\n[audit 11-08 C-03: one alarm that cannot go out does not hold the ones after it]")
        e = build(TODAY)
        second = okww_rounds()[-1]
        second.user, second.run_id = "wuwa2", "2026-10-01/wuwa2/OK-WW-09-21-22"
        e._pending[(second.script, second.user)] = second
        _calls = []

        def _first_fails(title, body="", **kw):
            _calls.append(title)
            return ["群机器人没回"] if len(_calls) == 1 else []
        e.notifier.send = _first_fails
        e._flush_pending()
        check("both tried this tick", len(_calls), 2)
        check("the one that failed stays held, the other is out", list(e._pending), [("OK-WW", "wuwa")])

        print("\n[只看名字对得上的那一格]")
        check("MaaEnd 运行 → MaaEnd 在跑", eng._script_unfinished(TODAY, "MaaEnd"), True)
        check("OK-WW 异常 → OK-WW 不在跑", eng._script_unfinished(TODAY, "OK-WW"), False)
        check("MAA 完成 → MAA 不在跑", eng._script_unfinished(TODAY, "MAA"), False)
        check("刚派下去没状态 → 当作在跑", eng._script_unfinished({"tasks": [{"task_info": []}]}, "OK-WW"), True)
        check("没有任务 → 不在跑", eng._script_unfinished({"tasks": []}, "OK-WW"), False)
    finally:
        eng.config.IS_WINDOWS, eng._automas_snapshot = real_win, real_snapshot


def _part_gathering_route_node_failed():
    """A gathering route whose own Goto / Start node fails is booked as failed, and gets no whole make-up.

2026-11-05 早班 (Beijing): MaaEnd's 10:22 attempt finished every task but one route, 协议纹石（路线2）,
whose Goto node failed (maafw.log 11:20:43 Node.PipelineNode.Failed AutoCollectWulingProtocolith2Goto).
The 11:26 attempt was logged out mid-run (「登录认证已失效」 at 11:43:57) and every route after that failed
at its Start node within 20 s. Such a failure writes no 「…采集失败」 line: the AUTO-MAS history log has
「FailureCollector subtask failed task=AutoCollectValleyIVPinkBolete1Start」 instead, and the relay booked
that attempt as 17 of 17 routes walked; the live watch said 「日志里没有点名哪条路线」. Then the relay's
make-up ran the whole script a fourth time although the first attempt had done everything else.

Checked here, with the line shapes of that morning:
* collector_maaend books the routes the failure collector named as failed - by item through MaaEnd's
  locale, else by the 「采集…」 line before the failure line - and leaves a log without them as before;
* collect_retry.failed_routes returns them for the per-route retry, route_label gives v2.36 routes their
  Chinese words, and judge counts a route's own failed node as a failure;
* collect_watch's live pattern names the route in all three shapes;
* makeup.maaend_round_only_gathering: no whole make-up when an attempt of the round ran to its end
  with gathering the only unfinished task; a make-up as before otherwise.

    Formerly test_gathering_route_node_failed.py.
    """
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features.makeup import collect_retry as cr
    from ark_relay.features.makeup import makeup
    from ark_relay.features.run import collect_watch
    from ark_relay.features.verify import collector_maaend as cm

    FIX = Path(__file__).parent / "fixtures" / "maaend-2026-10-29"


    def collector_line(t, node):
        return (f"[2026-11-05 {t}.737] 2026-11-05T{t}+08:00 ERR github.com/MaaXYZ/MaaEnd/agent/go-service/"
                f"common/failurecollector/action.go:60 > FailureCollector subtask failed task={node}")


    # The 11:26 attempt's gathering, as its AUTO-MAS history log has it (two routes walked, then the
    # logout; 协议纹石（路线2） is a Wuling route the 10-29 locale does not have).
    LOG = "\n".join([
        "[2026-11-05 11:39:04.400] 任务开始: 🧺自动采集",
        "[2026-11-05 11:39:40.100] 采集纯晶多齿叶",
        "[2026-11-05 11:41:30.200] 采集轻黯石",
        "[2026-11-05 11:43:08.300] 采集轻红柱状菌",
        "[2026-11-05 11:43:56.522] [2026-11-05 11:43:56.497][ERR][Px21872][Tx56783][navigation_state_machine.cpp][L297]"
        "[mapnavigator::NavigationStateMachine::failNavigation] Localization lost beyond timeout (re-acquire failed; "
        "likely shoved off-route into another zone); terminating navigation.",
        collector_line("11:43:56", "AutoCollectValleyIVPinkBolete1Start"),
        "[2026-11-05 11:43:56.884] 采集中黯石",
        collector_line("11:50:06", "AutoCollectValleyIVAuronyx1Start"),
        "[2026-11-05 11:53:34.367] 采集协议纹石（路线2）",
        collector_line("11:53:54", "AutoCollectWulingProtocolith2Start"),
        "[2026-11-05 11:54:57.226] 任务失败: 🧺自动采集",
        "[2026-11-05 11:54:57.394] 任务开始: 📅日常奖励领取",
    ]) + "\n"

    print("[collector_maaend: the routes the failure collector named]")
    check("route ids in order", cm.collector_failed_routes(LOG),
          ["AutoCollectValleyIVPinkBolete1", "AutoCollectValleyIVAuronyx1", "AutoCollectWulingProtocolith2"])
    with tempfile.TemporaryDirectory() as d:
        maaend = Path(d) / "maaend"
        (maaend / "locales" / "interface").mkdir(parents=True)
        (maaend / "locales" / "interface" / "zh_cn.json").write_bytes(
            (FIX / "locales" / "interface" / "zh_cn.json").read_bytes())
        log = Path(d) / "0.log"
        log.write_text(LOG, encoding="utf-8")
        items = cm.route_items(maaend)
        check("locale: route id -> item", items.get("AutoCollectValleyIVPinkBolete1"), "轻红柱状菌")
        out = cm.parse_maaend_log(log, maaend)
        check("booked failed: by locale, the Wuling one by its line", out.get("maaend_collect_failed"),
              ["采集轻红柱状菌", "采集中黯石", "采集协议纹石（路线2）"])
        check("walked 2 of 5, not 5 of 5", (out.get("maaend_collect_done"), out.get("maaend_collect_total")), (2, 5))
        check("ids kept for the record", out.get("maaend_collect_failed_ids"),
              ["AutoCollectValleyIVPinkBolete1", "AutoCollectValleyIVAuronyx1", "AutoCollectWulingProtocolith2"])
        out0 = cm.parse_maaend_log(log, None)
        check("no locale: every one by the line before it", out0.get("maaend_collect_failed"),
              ["采集轻红柱状菌", "采集中黯石", "采集协议纹石（路线2）"])
        plain = Path(d) / "1.log"
        plain.write_text("\n".join(l for l in LOG.splitlines() if "FailureCollector" not in l) + "\n", encoding="utf-8")
        out1 = cm.parse_maaend_log(plain, maaend)
        check("without failure lines: as before", (out1.get("maaend_collect_failed"), out1.get("maaend_collect_done"),
                                                   out1.get("maaend_collect_total")), (None, 5, 5))

        print("[collect_retry: the per-route retry gets them]")
        zh = cr._locale(maaend)
        check("failed_routes", cr.failed_routes(LOG, cr.failed_labels_from_locale(zh)),
              ["AutoCollectValleyIVPinkBolete1", "AutoCollectValleyIVAuronyx1", "AutoCollectWulingProtocolith2"])
        with_line = LOG.replace("[2026-11-05 11:41:30.200] 采集轻黯石",
                                "[2026-11-05 11:41:30.200] 采集轻黯石\n[2026-11-05 11:42:00.000] 轻黯石采集失败")
        check("a 「…采集失败」 line first, then the collector's", cr.failed_routes(with_line, cr.failed_labels_from_locale(zh))[:2],
              ["AutoCollectValleyIVKalkonyx1", "AutoCollectValleyIVPinkBolete1"])
        print("[collect_retry: routes walked earlier today are not retried]")
        by_label = cr.route_ids_by_label(zh)
        check("walked: the two routes before the logout", cr.walked_routes(LOG, by_label, cr.failed_labels_from_locale(zh)),
              {"AutoCollectValleyIVChrysodendra1", "AutoCollectValleyIVKalkonyx1"})
        cut = "\n".join(LOG.splitlines()[:3]) + "\n"
        check("a run cut while a route was open: that route not counted", cr.walked_routes(cut, by_label),
              {"AutoCollectValleyIVChrysodendra1"})
        summary = ("[2026-11-05 11:00:00.000] 采集轻黯石\n[2026-11-05 11:05:00.000] 采集纯晶多齿叶\n"
                   "[2026-11-05 11:06:00.000] 轻黯石采集失败\n[2026-11-05 11:06:01.000] 任务失败: 🧺自动采集\n")
        check("a 「…采集失败」 summary at the end fails that route by name, not the last one",
              cr.walked_routes(summary, by_label, cr.failed_labels_from_locale(zh)), {"AutoCollectValleyIVChrysodendra1"})
        hist = Path(d) / "history"
        hist.mkdir()
        (hist / "r1.log").write_text("\n".join(LOG.splitlines()[:3] + ["[2026-11-05 10:50:00.000] 采集轻红柱状菌",
                                                                        "[2026-11-05 11:00:00.000] 任务完成: 🧺自动采集"]),
                                     encoding="utf-8")
        (hist / "r2.log").write_text(LOG, encoding="utf-8")
        entries = [{"script": "MaaEnd", "run_id": "r1"}, {"script": "MaaEnd", "run_id": "r2"}]
        check("walked today: the first run's routes count for the second run's failures",
              cr.walked_today(entries, hist, by_label, None, zh),
              {"AutoCollectValleyIVChrysodendra1", "AutoCollectValleyIVKalkonyx1", "AutoCollectValleyIVPinkBolete1"})
        check("route_label: a v2.36 route in Chinese", cr.route_label("AutoCollectValleyIVPinkBolete1", zh), "采集轻红柱状菌")
        check("route_label: unknown stays the id", cr.route_label("AutoCollectWulingProtocolith2", zh),
              "AutoCollectWulingProtocolith2")

    FW = "\n".join([
        "[2026-11-05 13:01:10.100][INF][Px1][Tx1][EventDispatcher.cpp][L1][MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! "
        "[handle=true] [msg=Node.Action.Starting] [details={\"action_id\":1,\"name\":\"AutoCollectValleyIVChrysodendra1End\",\"task_id\":2}]",
        "[2026-11-05 13:02:20.702][INF][Px1][Tx1][EventDispatcher.cpp][L1][MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! "
        "[handle=true] [msg=Node.PipelineNode.Failed] [details={\"focus\":null,\"name\":\"AutoCollectWulingProtocolith2Goto\",\"node_id\":3}]",
        "[2026-11-05 13:03:00.000][INF][Px1][Tx1][EventDispatcher.cpp][L1][MaaNS::EventDispatcher::notify] !!!OnEventNotify!!! "
        "[handle=true] [msg=Node.PipelineNode.Failed] [details={\"focus\":null,\"name\":\"AutoCollectAfterStashBackpack\",\"node_id\":4}]",
    ])
    def watched(line):
        m = collect_watch._ROUTE_FAILED.search(line)
        return (m.group(1) or m.group(2)) if m else None


    print("[the real 11-05 lines (fixtures/maaend-2026-11-05)]")
    REAL = Path(__file__).parent / "fixtures" / "maaend-2026-11-05"
    real_hist = (REAL / "history-MaaEnd-07-24-54-gathering.log").read_text(encoding="utf-8")
    check("15 routes named by the failure collector", len(cm.collector_failed_routes(real_hist)), 15)
    with tempfile.TemporaryDirectory() as d2:
        lp = Path(d2) / "0.log"
        lp.write_text(real_hist, encoding="utf-8")
        real_out = cm.parse_maaend_log(lp, None)
        check("the logged-out attempt: 2 of 17 walked, not 17 of 17",
              (real_out.get("maaend_collect_done"), real_out.get("maaend_collect_total")), (2, 17))
        check("its first failed route is the one the logout hit", (real_out.get("maaend_collect_failed") or [""])[0], "采集轻红柱状菌")
    real_fw = (REAL / "maafw-route-node-failed.log").read_text(encoding="utf-8")
    check("judge on the real maafw lines", cr.judge(real_fw, ["AutoCollectWulingProtocolith2", "AutoCollectValleyIVPinkBolete1"], "11:00:00"),
          {"AutoCollectWulingProtocolith2": False, "AutoCollectValleyIVPinkBolete1": False})
    check("the live watch on the real lines", [watched(x) for x in real_fw.splitlines()],
          ["WulingProtocolith2", None, "ValleyIVPinkBolete1", None])

    print("[collect_retry.judge: a route's own failed node]")
    check("End passes, a failed Goto fails, a non-route node is ignored",
          cr.judge(FW, ["AutoCollectValleyIVChrysodendra1", "AutoCollectWulingProtocolith2", "AutoCollectValleyIVAuronyx1"], "13:00:00"),
          {"AutoCollectValleyIVChrysodendra1": True, "AutoCollectWulingProtocolith2": False, "AutoCollectValleyIVAuronyx1": None})
    check("node_lines quotes the failed node", "AutoCollectWulingProtocolith2Goto" in
          cr.node_lines(FW, ["AutoCollectWulingProtocolith2"], "13:00:00").get("AutoCollectWulingProtocolith2", ""), True)

    print("[collect_watch: the live line names the route]")


    check("a failed Goto node", watched(FW.splitlines()[1]), "WulingProtocolith2")
    check("the old Failed node", watched('[msg=Node.Action.Starting] [details={"name":"AutoCollectRoute10Failed"}]'), "Route10")
    check("v2.36's __…Failed node", watched('[msg=Node.Action.Starting] [details={"name":"__AutoCollectValleyIVChrysodendra1Failed"}]'),
          "ValleyIVChrysodendra1")
    check("not a route: none", watched(FW.splitlines()[2]), None)
    check("ResetFailures is not a failure", watched('[msg=Node.Action.Starting] [details={"name":"AutoCollectResetFailures"}]'), None)

    print("[makeup: no whole make-up when one attempt left only gathering]")
    ROWS = [
        {"script": "MaaEnd", "user": "endfield", "run_id": "MaaEnd-06-22-52", "started": "2026-11-05T10:24:37+08:00", "ok": False,
         "raw": {"maaend_result": "MaaEnd 部分任务执行失败: 🧺自动采集"}},
        {"script": "MaaEnd", "user": "endfield", "run_id": "MaaEnd-07-24-54", "started": "2026-11-05T11:26:30+08:00", "ok": False,
         "raw": {"maaend_result": "MaaEnd 部分任务执行失败: 🧺自动采集、📅日常奖励领取"}},
        {"script": "MaaEnd", "user": "endfield", "run_id": "MaaEnd-08-01-16", "started": "2026-11-05T12:02:51+08:00", "ok": False,
         "raw": {"maaend_result": "运行超过 120 分钟，已终止"}},
    ]


    def ledger_of(rows):
        return lambda day: list(rows)


    why = makeup.maaend_round_only_gathering(ledger_of(ROWS), ROWS[2])
    check("the 11-05 round: no whole make-up, because of the 10:24 attempt", why, texts.makeup_only_gathering("10:24"))
    check("in plain words", texts.plain(why), [])
    check("a round whose complete attempts had more than gathering left: make-up as before",
          makeup.maaend_round_only_gathering(ledger_of(ROWS[1:]), ROWS[2]), "")
    earlier_ok = [dict(ROWS[0], ok=True)] + ROWS[1:]
    check("an ok row ends the round: an earlier round's attempt does not count",
          makeup.maaend_round_only_gathering(ledger_of(earlier_ok), ROWS[2]), "")
    other_user = [dict(ROWS[0], user="someone")] + ROWS[1:]
    check("another account's attempt does not count", makeup.maaend_round_only_gathering(ledger_of(other_user), ROWS[2]), "")


    def broken(day):
        raise OSError("unreadable")


    check("an unreadable ledger: make-up as before", makeup.maaend_round_only_gathering(broken, ROWS[2]), "")
    check("the held attempt itself left only gathering", makeup.maaend_round_only_gathering(ledger_of(ROWS[:1]), ROWS[0]),
          texts.makeup_only_gathering("10:24"))

    print("[the alarm: 「没干完」, not 「没跑成」]")
    from ark_relay.features.alarm import pushes
    from ark_relay.features.alarm.unresolved import _gave_up_phrase
    phrase = _gave_up_phrase("不补跑：" + texts.makeup_only_gathering("10:24"))
    title, head = pushes._unresolved_title_head("终末地", "早班", phrase, "自动采集", "https://example.test/x")
    check("title", title, "⚠️ 终末地早班没干完")
    check("first line", head.splitlines()[0], "终末地早班跑完了但没干完：自动采集，这一类不补跑（证据包 https://example.test/x）")
    check("then why no whole make-up", head.splitlines()[1],
          "没补跑：10:24 那一遍除了自动采集，别的都干完了，整轮再跑只会把干完的再做一遍；没走通的采集路线关机前单独补")
    check("plain words", texts.plain(title + head.replace("https://example.test/x", "")), [])
    t2, h2 = pushes._unresolved_title_head("终末地", "早班", "补跑也没成", "自动采集", "")
    check("any other make-up outcome: as before", (t2, h2), (texts.unresolved("终末地", "早班"),
                                                         texts.unresolved_head("终末地", "早班", "补跑也没成", "自动采集", "")))

    print("all checks passed" if not fails else f"FAILED: {fails}")


def _part_healthcheck_annihilation():
    """The evening health check judges annihilation by the post-hand-over model.

Review fix 3 of the 2026-10-11 hand-over (item 13): scripts/mac/lib/healthcheck.py
still required Info.Annihilation == "Close", the value the relay used to write
after the week's pass. AUTO-MAS now keeps the switch on the map and the week in
Data.AnnihilationCompletedWeek, so that check failed every night. The script runs
on the game machine against a live AUTO-MAS, so only its two pure functions are
loaded here (by AST, without running the script's top level).

    Formerly test_healthcheck_annihilation.py.
    """
    import ast
    import time
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.weekly.annihilation import week_key

    SRC = Path(__file__).resolve().parents[2] / "scripts" / "mac" / "lib" / "healthcheck.py"


    text = SRC.read_text(encoding="utf-8")
    tree = ast.parse(text)
    ns: dict = {}
    wanted = {"game_week", "annihilation_check"}
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    check("both functions are in healthcheck.py", sorted(n.name for n in found), sorted(wanted))
    exec(compile(ast.Module(body=found, type_ignores=[]), str(SRC), "exec"), ns)

    print("[the old rule is gone]")
    check("no check that wants the switch Close", 'get("Annihilation") == "Close"' in text, False)

    if "annihilation_check" in ns:
        ac, W = ns["annihilation_check"], "2026-W41"
        print("\n[the new rule]")
        check("on the map, week not done: fine (AUTO-MAS will fight it)",
              ac({"Annihilation": "Annihilation"}, {"AnnihilationCompletedWeek": "2026-W40"}, W)[0], True)
        check("on the map, week done: fine", ac({"Annihilation": "Annihilation"}, {"AnnihilationCompletedWeek": W}, W)[0],
              True)
        check("Close, week not done: wrong (nothing reopens it)",
              ac({"Annihilation": "Close"}, {"AnnihilationCompletedWeek": "2026-W40"}, W)[0], False)
        check("Close, no record at all: wrong", ac({"Annihilation": "Close"}, {}, W)[0], False)
        check("Close, week done: fine (same rule as the boot alarm)",
              ac({"Annihilation": "Close"}, {"AnnihilationCompletedWeek": W}, W)[0], True)
        check("the detail names the value", "'Close'" in ac({"Annihilation": "Close"}, {}, W)[1], True)

    # time.tzset is POSIX only; the game machine itself runs on Beijing time, so on a
    # Windows runner (UTC) this part cannot set the clock and is left to the Mac gate.
    if "game_week" in ns and hasattr(time, "tzset"):
        print("\n[its week marker is the relay's (Monday 04:00 server time reset)]")
        import os
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Shanghai"          # the game machine's clock
        time.tzset()
        try:
            for t in (datetime(2026, 10, 5, 3, 59, tzinfo=SERVER_TZ), datetime(2026, 10, 5, 4, 1, tzinfo=SERVER_TZ),
                      datetime(2026, 1, 7, 12, 0, tzinfo=SERVER_TZ)):
                check(f"{t:%m-%d %H:%M}", ns["game_week"](t.timestamp()), week_key(t))
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()


def _part_kuro_error_code():
    """库街区 answering HTTP 200 with an error code in the body is a failed fetch.

Every saved success carries "code": 200. An error body ({"code": <other>,
"data": null}) used to read as an empty list or an empty post at four places -
_kuro_gacha, _wuwa_first_half_end, _wuwa (wiki homepage / entry names) and
update_wuwa_history - i.e. "nothing found", with no log line. Each now raises
KuroAnswerProblem into that place's existing failure path.

    Formerly test_kuro_error_code.py.
    """
    import json
    import logging
    import tempfile
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ark_relay.features.banners.banners as _b
    from ark_relay.features.banners import wuwa as W
    from ark_relay.features.banners import wuwa_history as H
    from ark_relay.features.banners import wuwa_posters as P


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.recs = []

        def emit(self, record):
            self.recs.append((record.levelno, record.getMessage()))


    ERR = {"code": 1511, "msg": "系统繁忙", "data": None}
    NOW = datetime(2026, 10, 13, 12, 0)


    def raises(fn):
        try:
            fn()
        except P.KuroAnswerProblem as e:
            return str(e)
        except Exception as e:   # noqa: BLE001 - reported as the wrong kind
            return f"other {type(e).__name__}"
        return None


    print("[the check itself]")
    ok_body = {"code": 200, "data": {"list": []}}
    check("code 200 passes through", P.kuro_checked(ok_body, "x"), ok_body)
    check("no code at all is left to the shape checks", P.kuro_checked({"data": {"list": []}}, "x"), {"data": {"list": []}})
    check("code 1511 raises and names the code", "code=1511" in (raises(lambda: P.kuro_checked(ERR, "x")) or ""), True)

    print("[_kuro_gacha]")
    check("an error list raises instead of returning None",
          "code=1511" in (raises(lambda: P._kuro_gacha("3.7", "某池", NOW, lambda path, payload: ERR)) or ""), True)
    posts = {"code": 200, "data": {"list": [{"postTitle": "[某池]角色活动唤取", "postId": "9",
                                             "publishTime": int(datetime(2026, 10, 1).timestamp() * 1000)}]}}
    check("an error post detail raises too",
          "帖子 9" in (raises(lambda: P._kuro_gacha("3.7", "某池", NOW,
                                                     lambda path, payload: posts if path == P._KURO_NEWS else ERR)) or ""), True)

    print("[_wuwa_first_half_end: the failure is listed and warned about]")
    g = Grab()
    _b.log.addHandler(g)
    try:
        end = W._wuwa_first_half_end("3.8", NOW, None, _b.Trace.new(), lambda path, payload: ERR, None)
    finally:
        _b.log.removeHandler(g)
    check("no end", end, None)
    check("one WARNING naming the failed notice fetch",
          [m for lv, m in g.recs if lv == logging.WARNING and "库街区唤取公告取不到" in m and "KuroAnswerProblem" in m] != [], True)

    print("[_wuwa: the wiki homepage error is \"not read\", an entry error is warned]")
    real = _b._json, _b._text


    def offline(url, *a, **k):
        raise OSError("offline")


    _b._json, _b._text = (lambda url, *a, **k: ERR if url.endswith("/homepage/getPage") else offline(url)), offline
    try:
        why = raises(lambda: _b._wuwa(NOW, notes={}, trace=_b.Trace.new()))
    finally:
        _b._json, _b._text = real
    check("homepage error body raises (collect records it as not read)", "/wiki/core/homepage/getPage" in (why or ""), True)

    home = json.loads((Path(__file__).parent / "fixtures" / "wuwa_home.json").read_text(encoding="utf-8"))
    g = Grab()
    _b.log.addHandler(g)
    _b._json = lambda url, *a, **k: (home if url.endswith("/homepage/getPage")
                                     else ERR if url.endswith("/getEntryDetail") else offline(url))
    _b._text = offline
    try:
        try:
            _b._wuwa(NOW, notes={}, trace=_b.Trace.new())
        except Exception:   # noqa: BLE001 - only the entry warning matters here
            pass
    finally:
        _b._json, _b._text = real
        _b.log.removeHandler(g)
    check("entry name error body: WARNING 查不到名字",
          [m for lv, m in g.recs if lv == logging.WARNING and "查不到名字" in m] != [], True)

    print("[update_wuwa_history]")
    with tempfile.TemporaryDirectory() as td:
        menu = json.dumps([])
        why = raises(lambda: H.update_wuwa_history(td, NOW, get=lambda path, payload: ERR, article_get=lambda u: menu))
        check("an error list raises (update_history reports the step as not done)", "code=1511" in (why or ""), True)

        two = {"code": 200, "data": {"list": [
            {"postTitle": "[甲]角色活动唤取", "postId": "1", "publishTime": 2},
            {"postTitle": "[乙]角色活动唤取", "postId": "2", "publishTime": 1}]}}
        good = {"code": 200, "data": {"postDetail": {"postContent": [{"contentType": 1, "content": "甲的正文"}]}}}

        def get(path, payload):
            if path == P._KURO_NEWS:
                return two
            return good if payload["postId"] == "1" else ERR
        why = raises(lambda: H.update_wuwa_history(td, NOW, get=get, article_get=lambda u: menu))
        cache = json.loads((Path(td) / "banners" / "ww-notices.json").read_text(encoding="utf-8"))
        check("an error post raises", "帖子 2" in (why or ""), True)
        check("the post fetched before it is kept, the failed one is not cached as empty",
              sorted(cache["text"]), ["1"])


def _part_logfile_silent():
    """A relay.log rotation that keeps failing is said through logging, once per
failure streak (audit docs/SILENT-FAILURES-AUDIT.md, logfile.py:63).

The line used to be written straight into the file from inside the handler,
so errwatch (a handler on the "ark" logger) never saw it and nobody was told
that relay.log had stopped rotating.

    Formerly test_logfile_silent.py.
    """
    import logging
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import logfile


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.records = []

        def emit(self, record):
            self.records.append((record.levelno, record.getMessage()))

        def take(self, level):
            out = [m for lv, m in self.records if lv == level]
            self.records.clear()
            return out


    d = tmpdir()
    h = logfile.RelayLogHandler(d / "relay.log", max_bytes=2000, backups=2)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s", "%m-%d %H:%M:%S"))
    # As in production (__main__._setup_logging puts it on the root logger): the
    # lines of every ark.* logger, ark.logfile included, reach this handler.
    src = logging.getLogger("ark.test_verify")
    lf = logfile.log
    saved_prop = src.propagate, lf.propagate
    src.propagate = lf.propagate = False
    src.addHandler(h)
    lf.addHandler(h)
    grab = Grab()
    lf.addHandler(grab)
    real_rotate = h.rotate


    def locked(src_, dst):
        raise PermissionError(32, "being used by another process")


    try:
        print("[rotation keeps failing: one WARNING through logging]")
        h.rotate = locked
        for i in range(60):
            src.warning("held %03d %s", i, "y" * 40)
        w = grab.take(logging.WARNING)
        check("one WARNING on ark.logfile (errwatch sees ark.*)", len(w), 1)
        check("it says the rotation failed", bool(w) and "轮转没成" in w[0], True)
        text = (d / "relay.log").read_text(encoding="utf-8")
        check("the file still has every line", sum(f"held {i:03d}" in text for i in range(60)), 60)
        check("the file has the line too", "轮转没成" in text, True)

        print("[the retry fails again: no second WARNING]")
        h._retry_at = time.monotonic() - 1
        src.warning("still held")
        check("no second WARNING in the same streak", grab.take(logging.WARNING), [])

        print("[the lock clears: rotated; a new streak warns again]")
        h.rotate = real_rotate
        h._retry_at = time.monotonic() - 1
        src.warning("after the lock")
        check("rotated", (d / "relay.log.1").exists(), True)
        check("no WARNING on success", grab.take(logging.WARNING), [])
        h.rotate = locked
        for i in range(60):
            src.warning("held again %03d %s", i, "z" * 40)
        check("a new streak -> WARNING again", len(grab.take(logging.WARNING)), 1)
    finally:
        src.removeHandler(h)
        lf.removeHandler(h)
        lf.removeHandler(grab)
        src.propagate, lf.propagate = saved_prop
        h.close()


def _part_logslice_new_year():
    """A relay.log slice across New Year keeps the January lines.

relay.log stamps `MM-DD HH:MM:SS` without a year; slice_log dated every such
line in the year of the window's start, so for a window 12-31 23:50 -> 01-01
00:20 the 01-01 lines landed eleven months before it and were dropped (audit
s17, low item).

    Formerly test_logslice_new_year.py.
    """
    import os
    import time
    from datetime import datetime

    # The machine's zone where it can be set. time.tzset is Unix only ("Availability: Unix",
    # docs.python.org/3/library/time.html#time.tzset); the window and the stamps below are
    # both local wall-clock times, so the test holds in any zone (the Windows runner: UTC).
    if hasattr(time, "tzset"):
        os.environ["TZ"] = "Asia/Shanghai"
        time.tzset()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.evidence.logslice import slice_log


    d = tmpdir()
    src = d / "relay.log"
    src.write_text("12-31 23:40:00 INFO before the window\n"
                   "12-31 23:55:00 INFO old year\n"
                   "  continuation of the old-year line\n"
                   "01-01 00:05:00 INFO new year\n"
                   "01-01 00:30:00 INFO after the window\n", encoding="utf-8")
    window = (datetime(2026, 12, 31, 23, 50).timestamp(), datetime(2027, 1, 1, 0, 20).timestamp())
    print("[a window across New Year]")
    out = slice_log(src, window, d / "out" / "relay.log")
    text = out.read_text(encoding="utf-8") if out else ""
    check("the December line inside is kept, with its continuation",
          ("old year" in text, "continuation" in text), (True, True))
    check("the January line inside is kept", "new year" in text)
    check("the lines outside stay out", ("before the window" in text, "after the window" in text), (False, False))

    print("\n[an ordinary window is unchanged]")
    src.write_text("10-12 10:00:00 INFO a\n10-12 11:00:00 INFO b\n", encoding="utf-8")
    out = slice_log(src, (datetime(2026, 10, 12, 10, 30).timestamp(), datetime(2026, 10, 12, 11, 30).timestamp()),
                    d / "out2" / "relay.log")
    check("only the line inside", out.read_text(encoding="utf-8") if out else "", "10-12 11:00:00 INFO b\n")

    if fails:
        print(f"\n{len(fails)} failed")
        sys.exit(1)
    print("\nall passed")


def _part_main_logfile_silent():
    """relay.log that cannot be created is said once errwatch is listening (audit
docs/SILENT-FAILURES-AUDIT.md, __main__.py:75).

_setup_logging runs before errwatch is installed, so a WARNING there would reach
stderr only. It keeps the OSError instead; boot_stages._stage_bootstrap says it
right after errwatch.install, so the group hears that the relay is running with
no relay.log (evidence slices, self-check and machine checks lose their source).

    Formerly test_main_logfile_silent.py.
    """
    import ast
    import logging
    import os
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    import boot_stages
    from ark_relay import __main__ as relay_main


    print("[_setup_logging keeps the OSError when relay.log cannot be created]")
    root = logging.getLogger()
    saved_handlers, saved_env = root.handlers[:], os.environ.get("ARK_LOG_FILE")
    blocker = tmpdir() / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    try:
        root.handlers.clear()
        os.environ["ARK_LOG_FILE"] = str(blocker / "relay.log")    # its parent is a file
        relay_main._setup_logging(verbose=False)
        err = getattr(relay_main, "log_file_error", lambda: None)()
        check("the error is kept", isinstance(err, OSError), True)
        for h in root.handlers:
            h.close()
        root.handlers.clear()
        os.environ["ARK_LOG_FILE"] = str(tmpdir() / "relay.log")
        relay_main._setup_logging(verbose=False)
        check("a later good setup clears it", getattr(relay_main, "log_file_error", lambda: None)(), None)
        err_path = blocker / "relay.log"
    finally:
        for h in root.handlers:
            h.close()
        root.handlers[:] = saved_handlers
        if saved_env is None:
            os.environ.pop("ARK_LOG_FILE", None)
        else:
            os.environ["ARK_LOG_FILE"] = saved_env

    print("[boot_stages says it, once errwatch is installed]")
    said = []
    grab = type("G", (logging.Handler,), {"emit": lambda self, r: said.append((r.levelno, r.getMessage()))})()
    svc = boot_stages.log
    svc.addHandler(grab)
    try:
        say = getattr(boot_stages, "_say_log_file_problem", None)
        if say is None:
            check("boot_stages has the step", False, True)
        else:
            relay_main._LOG_FILE_ERROR[0] = NotADirectoryError(20, "Not a directory", str(err_path))
            say(svc)
            check("one WARNING naming relay.log", [lv for lv, m in said if "relay.log" in m], [logging.WARNING])
            said.clear()
            relay_main._LOG_FILE_ERROR[0] = None
            say(svc)
            check("no error -> nothing said", said, [])
    finally:
        svc.removeHandler(grab)
        if hasattr(relay_main, "_LOG_FILE_ERROR"):
            relay_main._LOG_FILE_ERROR[0] = None

    print("[...and it runs right after errwatch.install in _stage_bootstrap]")
    src = Path(boot_stages.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_stage_bootstrap")
    calls = [(n.lineno, ast.unparse(n.func)) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    install = [ln for ln, f in calls if f == "errwatch.install"]
    step = [ln for ln, f in calls if f == "_say_log_file_problem"]
    check("called once, after errwatch.install", (len(step), bool(install and step and step[0] > install[0])),
          (1, True))


def _part_monthcard():
    """Monthly-card reminders (user order 2026-09-26 02:47, spec BOARD/月卡到期提示-规格.md).

His own definition of the last claim day, verbatim: 「有效期比如说还剩一天，那就是到明天登录时领取算最后一次」
So the last claim day = today + days left; a renewal adds 30 per purchase; a lapsed card restarts on the
purchase day (day 1). From five days before the last claim day, one Server酱 a day,
and a push that reached nobody must be tried again rather than lost for the day.

    Formerly test_monthcard.py.
    """
    from datetime import date

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.phone import monthcard
    from ark_relay.core.notify import route_of


    D = date(2026, 9, 26)
    s = tmpdir()

    print("[还剩 X 天：最后领取 = 今天 + X]")
    ok, msg = monthcard.apply(s, {"game": "明日方舟", "left": 3}, today=D)
    check("接受", ok, True)
    check("回执", msg, "明日方舟月卡：最后一次领取 9 月 29 日（还剩 3 天）")
    check("状态", {g: {k: v for k, v in r.items() if k != "登记于"} for g, r in monthcard.status(s, today=D).items()},
          {"明日方舟": {"最后领取": "2026-09-29", "还剩": 3, "已过期": False}})

    print("\n[续费：在最后领取日上加 30×N]")
    ok, msg = monthcard.apply(s, {"game": "明日方舟", "add": 2}, today=D)
    check("回执", msg, "明日方舟月卡：最后一次领取 11 月 28 日（还剩 63 天）")

    print("\n[没登记过 / 已过期：买的当天是第 1 天]")
    ok, msg = monthcard.apply(s, {"game": "鸣潮", "add": 1}, today=D)
    check("新登记", monthcard.status(s, today=D)["鸣潮"]["最后领取"], "2026-10-25")
    monthcard.apply(s, {"game": "终末地", "left": 0}, today=date(2026, 9, 1))
    check("过期后状态", {k: v for k, v in monthcard.status(s, today=D)["终末地"].items() if k != "登记于"},
          {"最后领取": "2026-09-01", "还剩": -25, "已过期": True})
    monthcard.apply(s, {"game": "终末地", "add": 1}, today=D)
    check("过期后续费从今天算", monthcard.status(s, today=D)["终末地"]["最后领取"], "2026-10-25")
    check("最后领取日当天续费接着加", monthcard.apply(tmpdir(), {"game": "鸣潮", "left": 0}, today=D)[0], True)
    s2 = tmpdir()
    monthcard.apply(s2, {"game": "鸣潮", "left": 0}, today=D)
    monthcard.apply(s2, {"game": "鸣潮", "add": 1}, today=D)
    check("还剩 0 天续一次 = 今天 + 30", monthcard.status(s2, today=D)["鸣潮"]["最后领取"], "2026-10-26")

    print("\n[手机算好的日期：带 last 就照用，at 存成登记时间，旧的不盖新的]")
    p = tmpdir()
    ok, msg = monthcard.apply(p, {"game": "鸣潮", "left": 3, "last": "2026-09-28", "at": "2026-09-25T18:30:00.123Z"}, today=D)
    check("隔天才收到也照手机的日期", (ok, monthcard.status(p, today=D)["鸣潮"]["最后领取"]), (True, "2026-09-28"))
    check("登记于 = 手机登记时间（上海钟、带毫秒）", monthcard.status(p, today=D)["鸣潮"]["登记于"], "2026-09-26T02:30:00.123+08:00")
    ok, msg = monthcard.apply(p, {"game": "鸣潮", "left": 1, "last": "2026-09-20", "at": "2026-09-25T18:00:00Z"}, today=D)
    check("更早的登记（重发晚到）不改", (ok, monthcard.status(p, today=D)["鸣潮"]["最后领取"]), (True, "2026-09-28"))
    check("回执说明没改", msg.endswith("（已有更晚的登记，这条没改）"), True)
    monthcard.apply(p, {"game": "鸣潮", "add": 1, "last": "2026-10-28", "at": "2026-09-25T19:00:00Z"}, today=D)
    check("更晚的登记照改", monthcard.status(p, today=D)["鸣潮"]["最后领取"], "2026-10-28")
    monthcard.apply(p, {"game": "鸣潮", "add": 1}, today=D)
    check("不带 last 照旧自己算", monthcard.status(p, today=D)["鸣潮"]["最后领取"], "2026-11-27")
    check("不带 at 也有登记于", "登记于" in monthcard.status(p, today=D)["鸣潮"], True)
    for cmd, why in (({"game": "鸣潮", "left": 3, "last": "9-28"}, "日期格式不对"),
                     ({"game": "鸣潮", "left": 3, "last": "2029-01-01"}, "日期太远"),
                     ({"game": "鸣潮", "left": 3, "at": "昨天"}, "时间看不懂"),
                     ({"game": "鸣潮", "left": -1, "last": "2026-09-28"}, "带 last 也照查 left")):
        before = monthcard.status(p, today=D)
        check(f"拒：{why}", monthcard.apply(p, cmd, today=D)[0], False)
        check(f"拒后不改：{why}", monthcard.status(p, today=D), before)

    print("\n[拒收]")
    for cmd, why in (({"game": "原神", "left": 3}, "不认识的游戏"), ({"game": "明日方舟"}, "两个都没填"),
                     ({"game": "明日方舟", "add": 1, "left": 3}, "两个都填"), ({"game": "明日方舟", "add": 0}, "0 次"),
                     ({"game": "明日方舟", "add": 13}, "超 12 次"), ({"game": "明日方舟", "left": -1}, "负天数"),
                     ({"game": "明日方舟", "left": 401}, "超 400 天"), ({"game": "明日方舟", "left": 2.5}, "小数"),
                     ({"game": "明日方舟", "add": True}, "布尔")):
        before = monthcard.status(s, today=D)
        check(f"拒：{why}", monthcard.apply(s, cmd, today=D)[0], False)
        check(f"拒后不改：{why}", monthcard.status(s, today=D), before)
    check("字符串数字照收", monthcard.apply(tmpdir(), {"game": "明日方舟", "left": "3"}, today=D)[0], True)

    print("\n[提醒：还剩 0–5 天每天一条，三家合一条，过期后不发]")
    n = tmpdir()
    check("没登记不发", monthcard.due_notice(n, today=D), None)
    monthcard.apply(n, {"game": "明日方舟", "left": 6}, today=D)
    check("还剩 6 天不发", monthcard.due_notice(n, today=D), None)
    monthcard.apply(n, {"game": "明日方舟", "left": 5}, today=D)
    monthcard.apply(n, {"game": "鸣潮", "left": 1}, today=D)
    monthcard.apply(n, {"game": "终末地", "left": 0}, today=date(2026, 9, 20))
    title, body = monthcard.due_notice(n, today=D)
    check("标题", title, "💳 月卡快到期")
    check("正文按剩余天数排、过期的不在内", body,
          "鸣潮月卡还剩 1 天，最后一次领取是 9 月 27 日\n明日方舟月卡还剩 5 天，最后一次领取是 10 月 1 日")
    check("走 Server酱", route_of(title), "info")
    check("没送到就不算发过：下一轮还给", monthcard.due_notice(n, today=D) is not None, True)
    monthcard.mark_sent(n, today=D)
    check("送到后当天不再发", monthcard.due_notice(n, today=D), None)
    check("第二天再发", monthcard.due_notice(n, today=date(2026, 9, 27)) is not None, True)
    check("最后领取日当天（还剩 0）还发", "鸣潮月卡还剩 0 天" in monthcard.due_notice(n, today=date(2026, 9, 27))[1], True)
    check("全过期后不发", monthcard.due_notice(n, today=date(2026, 10, 2)), None)

    print("\n[登记文件坏了：按没登记处理，不抛]")
    b = tmpdir()
    (b / monthcard.FILE).write_text("{坏", encoding="utf-8")
    check("状态为空", monthcard.status(b, today=D), {})
    check("仍能登记", monthcard.apply(b, {"game": "鸣潮", "left": 2}, today=D)[0], True)
    check("坏文件留了副本", (b / (monthcard.FILE + ".bad")).read_text(encoding="utf-8"), "{坏")

    print("\n[主循环那一步：送到才记已发]")
    from types import SimpleNamespace
    from ark_relay.core.engine import Engine
    e = tmpdir()
    monthcard.apply(e, {"game": "鸣潮", "left": 2})
    sent, answer = [], [["Server酱"]]
    fake = SimpleNamespace(state=SimpleNamespace(dir=e),
                           notifier=SimpleNamespace(send=lambda t, b: sent.append(t) or answer[0]))
    Engine._monthcard_notice(fake)
    check("推了一条", sent, ["💳 月卡快到期"])
    Engine._monthcard_notice(fake)
    check("没送到：下一轮再推", sent, ["💳 月卡快到期"] * 2)
    answer[0] = []
    Engine._monthcard_notice(fake)
    Engine._monthcard_notice(fake)
    check("送到后当天不再推", len(sent), 3)

    print("\n[经手机指令正门]")
    import os
    os.environ["ARK_STATE_DIR"] = str(tmpdir())
    from ark_relay.features.phone import commands
    check("白名单、免确认", "monthcard" in commands.REVERSIBLE, True)
    p2 = tmpdir()
    monthcard.apply(p2, {"game": "终末地", "add": 1, "at": "2026-09-25T15:30:00Z"}, today=D)
    check("不带 last 只带 at（隔夜收到）：按发出那天的上海日期算第 1 天",
          monthcard.status(p2, today=D)["终末地"]["最后领取"], "2026-10-24")


def _part_nofarm_visible():
    """A one-shot switch nobody displays is a switch that gets forgotten.

`no-stamina-farm.flag` is set by hand while testing the weekly boss and makes the
patched OK-WW skip stamina entirely. Nothing reported it: tomorrow's plan still
announced what the stamina would be spent on, healthcheck still ticked, and the
phone page still offered the choice. Only an ssh session running okww-landed.py by
hand could see it. Forget it and waveplates sit at the 240 cap, overflowing every
minute, while every surface says farming is happening.

This is the same shape as 「下次跑完不关机」, which has already cost a whole night
twice - and the answer is the same: the switch has to show up where the person is
looking.

    Formerly test_nofarm_visible.py.
    """
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    STATE = tmpdir()
    os.environ["ARK_STATE_DIR"] = str(STATE)

    from ark_relay.core import config
    from ark_relay.core import plan
    from ark_relay.core.config import no_stamina_farm

    # The relay reads the fixed path the OK-WW override obeys, whatever ARK_STATE_DIR
    # says; the test points that one constant at a temp file.
    REAL_FLAG = config.NO_STAMINA_FARM_FLAG
    FLAG = tmpdir() / "no-stamina-farm.flag"
    config.NO_STAMINA_FARM_FLAG = str(FLAG)


    DAILY = {"Which to Farm": "Simulation Domain"}

    print("[没挂开关时，一切照旧]")
    check("读出来是没挂", no_stamina_farm(), False)
    line = plan._okww_farm_bit(DAILY, {"Simulation Domain": "模拟领域"})
    check("照常预告刷什么", line.startswith("体力刷"), True)
    check("不提那个开关", "不刷体力" in line, False)

    print("\n[挂上开关：明日安排必须改口，而且要说清怎么恢复]")
    FLAG.touch()
    check("读出来是挂着的", no_stamina_farm(), True)
    line = plan._okww_farm_bit(DAILY, {"Simulation Domain": "模拟领域"})
    check("不再说在刷什么", line.startswith("体力刷"), False)
    check("说清今天不刷", "今天不刷体力" in line, True)
    check("说清波片会涨到上限", "上限" in line, True)
    check("说清怎么恢复", "关掉这个开关才恢复" in line, True)

    print("\n[删掉之后自己恢复，不需要谁去清什么状态]")
    FLAG.unlink()
    check("读出来又是没挂", no_stamina_farm(), False)
    check("预告也回来了", plan._okww_farm_bit(DAILY, {"Simulation Domain": "模拟领域"}
                                              ).startswith("体力刷"), True)

    print("\n[ARK_STATE_DIR does not move the flag (audit 2026-10-13): OK-WW reads no env var]")
    (STATE / "no-stamina-farm.flag").touch()
    check("a flag under ARK_STATE_DIR is not the flag", no_stamina_farm(), False)
    (STATE / "no-stamina-farm.flag").unlink()
    config.NO_STAMINA_FARM_FLAG = REAL_FLAG

    print("\n[the path the OK-WW override reads is the one read here]")
    import re
    from ark_relay.features.okww_patch import okww_overlay
    got = re.findall(r'^NO_STAMINA_FLAG = r"([^"]+)"', okww_overlay.source_text(), re.M)
    check("the override's path string equals NO_STAMINA_FARM_FLAG", got, [config.NO_STAMINA_FARM_FLAG])
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    check("and that is the value it runs with", ns.get("NO_STAMINA_FLAG"), config.NO_STAMINA_FARM_FLAG)


def _part_refresh_raw_unread():
    """refresh_raw applies the "MAA sanity never read" rule, like bookkeeping does.

Real 2026-10-09 MAA-08-03-19 (fixtures/refresh-unread-1009): Success!, combat off,
AUTO-MAS wrote sanity 0 with no refill sentence. It was booked before the rule
(cf246b6f) as sanity 0; re-reported, it has to read as unread, not 0. The log is
the original's first 8 and last 5 lines.

    Formerly test_refresh_raw_unread.py.
    """
    #!/usr/bin/env python3
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector

    D = Path(__file__).parent / "fixtures" / "refresh-unread-1009"
    e = json.loads((D / "ledger.jsonl").read_text(encoding="utf-8"))
    out = collector.refresh_raw(e, D)
    got = (out.get("sanity"), out["raw"].get("sanity"), out["raw"].get("sanity_unread"))
    ok = got == (None, None, True)
    print(("  ✓ " if ok else "  ✗ ") + f"unread after refresh: {got}")
    print("\n" + ("all checks passed" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


def _part_revive_gates():
    """The revival must not force-kill a window that is legitimately busy.

On 2026-08-22 an AUTO-MAS update was running its first-time environment
wizard - installing Python, pip and git, then cloning the backend. Throughout
that, no backend process exists. The revival read that as the stuck state it
guards against and ran `taskkill /IM AUTO-MAS.exe /F` twice, mid-clone. The
wizard then reported "所有镜像源都尝试失败" although every mirror was reachable
and carried the branch; the update completed on its own the moment the relay
was stopped.

    Formerly test_revive_gates.py.
    """
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    # service.py imports pywin32 at module scope; stub what is missing so the
    # module-level helpers can be imported on any machine.
    class _Any:
        """Stands in for any pywin32 attribute: callable, subclassable, truthy."""
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))

    from ark_relay.features.host import automas_keeper, automas_procs


    class _Out:
        def __init__(self, data): self.stdout = data


    def _fake_run(mapping):
        def run(cmd, **kw):
            key = " ".join(cmd).lower()
            for needle, data in mapping.items():
                if needle in key:
                    return _Out(data)
            return _Out(b"")
        return run


    def check(name, got, want):
        print(f"  {'ok  ' if got == want else 'FAIL'} {name}: got {got!r}, want {want!r}")
        return got == want


    def main():
        ok = True
        orig = automas_procs.subprocess.run

        # 1. Installer on screen -> veto, whatever else is true.
        automas_procs.subprocess.run = _fake_run(
            {"tasklist /nh": b"AUTO-MAS-Setup.exe  1234 Console"})
        ok &= check("安装程序在跑时 _installer_running", automas_procs._installer_running(), True)

        # 2. Ordinary process list -> no veto.
        automas_procs.subprocess.run = _fake_run({"tasklist /nh": b"explorer.exe 4 Console"})
        ok &= check("平时 _installer_running", automas_procs._installer_running(), False)

        # 3. tasklist unavailable -> unknown (None), and _revive keeps its hands
        #    off on unknown. The wrong failure here kills a window; the right one
        #    merely delays a revival. (None rather than True since 2026-10-07: True
        #    made _revive say an installer was running when nobody had looked;
        #    the hold itself is pinned in test_procs.py.)
        def boom(cmd, **kw): raise OSError("no tasklist")
        automas_procs.subprocess.run = boom
        ok &= check("探测失败时 _installer_running 答「不知道」(None)",
                    automas_procs._installer_running(), None)
        ok &= check("探测失败时 _automas_shell_running 保守取 True",
                    automas_procs._automas_shell_running(), True)

        # 4. Shell detection reads the shell, not the backend.
        automas_procs.subprocess.run = _fake_run(
            {"imagename eq auto-mas.exe": b"AUTO-MAS.exe  18864 Console"})
        ok &= check("窗口在时 _automas_shell_running", automas_procs._automas_shell_running(), True)
        automas_procs.subprocess.run = _fake_run(
            {"imagename eq auto-mas.exe": b"INFO: No tasks are running"})
        ok &= check("窗口不在时 _automas_shell_running", automas_procs._automas_shell_running(), False)

        # 5. The grace period is long enough for a real first-run wizard and far
        #    shorter than the stuck state it guards against.
        ok &= check("宽限期至少 10 分钟", automas_keeper.SHELL_GRACE_SECONDS >= 600, True)

        automas_procs.subprocess.run = orig
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_scan_skips_seen():
    """scan() 对处理过的记录不再解析：先按路径算 run_id，见过的直接跳过。

2026-09-07 实测：每个周期把整个 history 目录几百条记录全部重新解析一遍再过滤，
启动一次十几秒、停服务撞 15 秒硬保险、8 月的老失败记录每次都重新报警。

    Formerly test_scan_skips_seen.py.
    """
    import json, os, sys, time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector

    root = tmpdir()
    for day, stem in (("2026-08-25", "MAA-05-00-00"), ("2026-09-07", "MAA-05-00-00")):
        d = root / day / "arknights"; d.mkdir(parents=True)
        (d / f"{stem}.json").write_text(json.dumps({"maa_result": "Success!"}), encoding="utf-8")
        (d / f"{stem}.log").write_text("x\n", encoding="utf-8")
        old = time.time() - 600
        os.utime(d / f"{stem}.json", (old, old))
    calls = []
    orig = collector.parse_record
    collector.parse_record = lambda p, r, *a: calls.append(p.name) or orig(p, r, *a)
    seen = {"2026-08-25/arknights/MAA-05-00-00"}
    out = collector.scan(root, seen)
    ok1 = [r.run_id for r in out] == ["2026-09-07/arknights/MAA-05-00-00"]
    ok2 = len(calls) == 1
    print("  ", "✓" if ok1 else "✗", "只返回没见过的", [r.run_id for r in out])
    print("  ", "✓" if ok2 else "✗", "见过的根本不解析（解析次数）", len(calls))
    print("all checks passed" if ok1 and ok2 else "FAILED")
    sys.exit(0 if ok1 and ok2 else 1)


def _part_setup_tasks_verify():
    """setup-tasks.ps1's verify list covers what the relay itself needs.

Its header and docs/OPERATIONS.md say it checks the scheduled tasks this system
needs, but until 2026-10-13 it checked only AUTO-MAS_AutoStart: a machine without
the installed relay's task (\\ArkRelay\\main) or its watchdog service
(ArkRelayWatchdog) printed OK. The names come from retire_legacy.py, which checks
exactly these before it retires the old service (new_relay_problems). No pwsh on
the Mac, so the script is read as text.

    Formerly test_setup_tasks_verify.py.
    """
    import importlib.util
    import re

    ROOT = Path(__file__).resolve().parents[2]
    PS1 = (ROOT / "scripts" / "windows" / "setup-tasks.ps1").read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("retire_legacy", ROOT / "scripts" / "windows" / "retire_legacy.py")
    rl = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts" / "windows"))
    sys.modules["retire_legacy"] = rl
    spec.loader.exec_module(rl)


    verify = PS1[PS1.find('"--- verify ---"'):]
    tasks = re.findall(r'foreach \(\$t in @\(([^)]*)\)\)', verify)
    services = re.findall(r'foreach \(\$s in @\(([^)]*)\)\)', verify)
    listed_tasks = re.findall(r'"([^"]+)"', tasks[0]) if tasks else []
    listed_services = re.findall(r'"([^"]+)"', services[0]) if services else []
    check("AUTO-MAS_AutoStart still checked", "AUTO-MAS_AutoStart" in listed_tasks, True)
    check("the relay's task, as retire_legacy names it", f"{rl.NEW_TASK_FOLDER}\\{rl.NEW_TASK_NAME}" in listed_tasks, True)
    check("the watchdog service, as retire_legacy names it", rl.NEW_WATCHDOG in listed_services, True)
    check("a service that is there but not running is not OK", "-ne \"Running\"" in verify, True)


def _part_tape():  # noqa: C901 - the whole body of the file this part was
    """The relay's day tape (ark_relay/features/selfcheck/tape.py, daysim W8).

* the hooks: mas_client.mas_post, engine._automas_snapshot, shutdown.shutdown_event_xml,
  maintenance._get, efstatus.update_hint and banners._json / _text each put what they
  received on the tape, and still return / raise exactly as before;
* recording never gets in the way: a broken tape folder or a failing write changes
  nothing the caller sees; before install() nothing is written at all;
* masking: the secret shapes, key-name masking and the game UID label never reach the
  file (the lists are the ones scripts/mac/redact.py and slice.py use);
* the day cap (one `truncated` line, then nothing, also after a restart), pruning of old
  day files, the Beijing day boundary, and repeats written once (also across a restart);
* round trip: the 2026-10-09 maintenance notice, hand-written in days/2026-10-09/
  outside.jsonl, is served to the real maintenance reader with the tape on; slice.py
  turns that tape into `web` events at the same times with the same answers, and the
  World's own handler (World.state_effect) replays both into the same window. The
  config read at boot becomes the t0 `mas_config` in place of the reconstructed one.

Sizes behind DAY_CAP_BYTES / BODY_CAP, measured 2026-10-14 by replaying every recorded
day (relay/tests/daysim/run.py --all --keep) with the hooks in place: 0.45 MB per day
(10-06 453 804 B, 10-07 450 817, 10-08 450 194, 10-09 455 531, 10-11 457 539, 10-12
451 810, 10-13 448 000 bytes), 94 % of it web answers; the biggest single answer
210 425 bytes (a banner source); 14-28 AUTO-MAS lines a day after repeats are dropped.

    Formerly test_tape.py.
    """
    import hashlib
    import json
    import os
    import threading
    import urllib.error
    import urllib.request
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    HERE = Path(__file__).resolve().parent
    ROOT = HERE.parents[1]
    sys.path[:0] = [str(ROOT / "relay"), str(HERE), str(HERE / "daysim"), str(ROOT / "scripts" / "mac")]

    os.environ["ARK_STATE_DIR"] = str(tmpdir())
    os.environ["ARK_MAS_PORT"] = "36163"

    try:
        from ark_relay.features.selfcheck import tape
    except ImportError:          # the code before W8: every check below fails at its assertion
        tape = None

    BJ = timezone(timedelta(hours=8))


    def bj(*a) -> datetime:
        return datetime(*a, tzinfo=BJ)


    class Clock:
        """tape's `datetime`, with now() pinned to `at` (Beijing)."""
        at = bj(2026, 10, 9, 8, 48, 56)

        class DT(datetime):
            @classmethod
            def now(cls, tz=None):
                return Clock.at.astimezone(tz) if tz else Clock.at.replace(tzinfo=None)


    def lines(state: Path, day: str) -> list[dict]:
        p = state / "tape" / f"{day}.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


    class Resp:
        """What urlopen hands back: a context manager with read() and a status."""
        def __init__(self, body: bytes, status: int = 200):
            self.body, self.status = body, status

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return self.body


    def serve(table: dict):
        """A urlopen answering by URL prefix: bytes -> 200, an exception -> raised."""
        calls = []

        def urlopen(req, timeout=None, **k):
            url = req if isinstance(req, str) else req.full_url
            calls.append(url)
            for prefix, ans in table.items():
                if url.startswith(prefix):
                    if isinstance(ans, BaseException):
                        raise ans
                    return Resp(ans)
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        urlopen.calls = calls
        return urlopen


    def fresh(day_at: datetime, automas: "Path | None" = None) -> Path:
        Clock.at = day_at
        st = tmpdir()
        tape.install(st, automas)
        return st


    # ---------------------------------------------------------------------------------
    def check_noop_before_install() -> None:
        print("\n[nothing is written before install()]")
        tape.uninstall()
        st = Path(os.environ["ARK_STATE_DIR"])
        tape.answer("mas", "/api/queue/get", body=b"{}")
        tape.syslog((1074,), 60, [])
        require("no tape folder appears", not (st / "tape").exists(), list(st.iterdir()))


    def check_hooks() -> None:
        print("\n[each hook puts what it received on the tape and behaves as before]")
        from ark_relay.core import engine
        from ark_relay.features.banners import banners
        from ark_relay.features.maintenance import efstatus, maintenance
        from ark_relay.features.phone import mas_client
        from ark_relay.features.shutdown import shutdown

        st = fresh(bj(2026, 10, 12, 10, 0, 0))
        base = "http://127.0.0.1:36163"
        real = urllib.request.urlopen
        snap = {"tasks": [{"taskId": "t1", "task_info": [{"name": "MAA", "status": "运行"}]}]}
        urllib.request.urlopen = serve({
            base + "/api/queue/get": json.dumps({"code": 200, "data": {"q": 1}}).encode(),
            base + "/api/dispatch/runtime-snapshot": json.dumps(snap).encode(),
            base + "/api/dispatch/start": urllib.error.HTTPError(base + "/api/dispatch/start", 500, "boom", {}, None),
            efstatus._URL: json.dumps({"code": 0, "data": {}}).encode(),
            "https://prts.wiki/": json.dumps({"parse": {"wikitext": {"*": "x"}}}).encode(),
            "https://endfield.hypergryph.com/": "<html>ef</html>".encode(),
            "https://ak.hypergryph.com/api/news": json.dumps({"code": 0, "data": {"list": [], "end": True}}).encode(),
        })
        try:
            check("mas_post returns the decoded answer", mas_client.mas_post("/api/queue/get", {"queueId": "q"}),
                  {"code": 200, "data": {"q": 1}})
            mas_client.mas_post("/api/queue/get", {"queueId": "q"})             # same answer: not written again
            try:
                mas_client.mas_post("/api/dispatch/start", {"mode": "x"})
                raised = None
            except urllib.error.HTTPError as exc:
                raised = exc.code
            check("mas_post still raises the HTTP error", raised, 500)
            check("runtime-snapshot still parsed", engine._automas_snapshot(), snap)
            check("efstatus reads as before (no update today)", efstatus.update_hint(now=bj(2026, 10, 12, 10)), "")
            check("banners._json returns the answer", banners._json("https://prts.wiki/api.php?page=x", "ua"),
                  {"parse": {"wikitext": {"*": "x"}}})
            check("banners._text returns the page", banners._text("https://endfield.hypergryph.com/v", "ua"),
                  "<html>ef</html>")
            check("maintenance._get returns the page",
                  json.loads(maintenance._get("https://ak.hypergryph.com/api/news?category=NEWS&page=1"))["code"], 0)
            try:
                maintenance._get("https://nowhere.invalid/x", timeout=1)
                raised = None
            except Exception as exc:  # noqa: BLE001
                raised = type(exc).__name__
            check("maintenance._get still raises what urlopen raised", raised, "URLError")
        finally:
            urllib.request.urlopen = real

        # The System log: the real reader through a stand-in win32evtlog.
        from fake_proc import SysEvent
        ev = SysEvent(bj(2026, 10, 12, 9, 59, 1).timestamp(), 1074, "User32",
                      {"param1": r"C:\WINDOWS\system32\shutdown.exe (INS)", "param7": "NT AUTHORITY\\SYSTEM"})
        evtlog = SimpleNamespace(EvtQueryChannelPath=1, EvtQueryReverseDirection=0x200, EvtRenderEventXml=1,
                                 EvtQuery=lambda *a: iter([ev]), EvtRender=lambda e, flag: e.xml())
        evtlog.EvtNext = lambda q, n: tuple(x for _, x in zip(range(n), q, strict=False))
        sys.modules["win32evtlog"] = evtlog
        try:
            check("shutdown_event_xml returns the event", shutdown.shutdown_event_xml(600), [ev.xml()])
            shutdown.shutdown_event_xml(600)                                    # the same event: not again
        finally:
            del sys.modules["win32evtlog"]
        check("unreadable System log: still None", shutdown.shutdown_event_xml(600), None)

        recs = lines(st, "20261012")
        kinds = [(r["kind"], r.get("path") or r.get("url") or "") for r in recs]
        check("the tape's lines, in order", kinds, [
            ("boot", ""), ("mas", "/api/queue/get"), ("mas", "/api/dispatch/start"),
            ("mas", "/api/dispatch/runtime-snapshot"), ("web", efstatus._URL),
            ("web", "https://prts.wiki/api.php?page=x"), ("web", "https://endfield.hypergryph.com/v"),
            ("web", "https://ak.hypergryph.com/api/news?category=NEWS&page=1"), ("web", "https://nowhere.invalid/x"),
            ("syslog", ""), ("syslog", "")])
        q = recs[1]
        check("an AUTO-MAS answer: request, status, length, hash, body",
              (q["req"], q["status"], q["len"], q["json"]),
              ({"queueId": "q"}, 200, len(json.dumps({"code": 200, "data": {"q": 1}})), {"code": 200, "data": {"q": 1}}))
        check("its hash is the received bytes'", q["sha256"],
              hashlib.sha256(json.dumps({"code": 200, "data": {"q": 1}}).encode()).hexdigest())
        check("a failed call: status and error", (recs[2]["status"], recs[2]["error"].split(":")[0]), (500, "HTTPError"))
        check("a page that is not JSON is kept as text", recs[6]["text"], "<html>ef</html>")
        check("maintenance's answer carries the real status", recs[7]["status"], 200)
        check("the System log event as read", recs[9]["events"], [ev.xml()])
        check("the unreadable read", recs[10]["error"].split(":")[0], "ModuleNotFoundError")


    def check_never_in_the_way() -> None:
        print("\n[a broken tape changes nothing the relay sees]")
        from ark_relay.features.phone import mas_client
        blocker = tmpdir() / "state-is-a-file"
        blocker.write_text("x")
        Clock.at = bj(2026, 10, 12, 11)
        tape.install(blocker)                              # <file>/tape cannot be made
        real = urllib.request.urlopen
        urllib.request.urlopen = serve({"http://127.0.0.1:36163/api/queue/get": b'{"code": 200}'})
        try:
            check("mas_post with an unwritable tape folder", mas_client.mas_post("/api/queue/get"), {"code": 200})
            st = fresh(bj(2026, 10, 12, 11))
            broken = tape._append
            tape._append = lambda *a: (_ for _ in ()).throw(OSError(28, "No space left on device"))
            try:
                check("mas_post with a write that fails", mas_client.mas_post("/api/queue/get"), {"code": 200})
                tape.syslog((1074,), 60, ["<Event/>"])
                tape.answer("web", "https://x.invalid/", body=b"\xff\xfe broken")
            finally:
                tape._append = broken
            require("no exception left any entry point", True)
            require("nothing half-written", not (st / "tape" / "20261012.jsonl").exists()
                    or all(json.loads(x) for x in (st / "tape" / "20261012.jsonl").read_text().splitlines()))
        finally:
            urllib.request.urlopen = real


    def check_masking() -> None:
        print("\n[secrets never reach the file]")
        import redact
        import slice as sl
        from pack import identity_pattern
        check("key-name hints are scripts/mac/redact.py's", tape.KEY_HINTS, redact.SECRET_KEY_HINTS)
        check("key-name exceptions are scripts/mac/redact.py's", tape.KEY_ALLOW, redact.SECRET_KEY_ALLOW)
        check("slice.py masks the tape's shapes", sl.SECRET_PATTERNS, tape.SECRET_PATTERNS)
        check("tape's mask is redact.py's", tape.MASK, redact.MASK)
        st = fresh(bj(2026, 10, 12, 12))
        akid = "AK" + "ID" + "Ab1" * 11                        # built here so this file holds no key shape
        hook = "https://qyapi.weixin.qq.com/cgi-bin/" + "webhook/send?key=" + "1a2b3c4d-" * 4
        uid = "\u7279\u5f81\u7801" + "\uff1a" + "123456789"        # the UID label, built here (lint item 12)
        body = json.dumps({"link": f"x.zip?q-ak={akid}&q-signature={'ab' * 20}", "hook": hook,
                           "Password": "hunter2hunter2", "MirrorChyanCDK": "x" * 20, "ocr": f"id {uid}",
                           "keyword": "kept"}).encode()
        tape.answer("web", hook, req={"SendKey": "SCT" + "q" * 20}, body=body)
        tape.answer("mas", "/api/x", body=("plain " + uid).encode())
        raw = (st / "tape" / "20261012.jsonl").read_bytes()
        check("no secret shape left (slice.secret_hits)", sl.secret_hits(raw), [])
        require("no game UID left (lint item 12's pattern)", not identity_pattern().search(raw))
        rec = [json.loads(x) for x in raw.decode().splitlines()][1]
        check("secret-named values masked, others kept",
              (rec["json"]["Password"], rec["json"]["MirrorChyanCDK"], rec["json"]["keyword"], rec["req"]["SendKey"]),
              (redact.MASK, redact.MASK, "kept", redact.MASK))
        require("the URL's webhook key masked", rec["url"].endswith("key=REDACTED"), rec["url"])
        require("UID digits masked to their length", "UIDREDACT" in rec["json"]["ocr"], rec["json"]["ocr"])
        check("hash is of the received bytes", rec["sha256"], hashlib.sha256(body).hexdigest())


    def check_cap_and_prune() -> None:
        print("\n[day cap, restart after it, old days pruned]")
        cap = tape.DAY_CAP_BYTES
        tape.DAY_CAP_BYTES = 2000
        try:
            st = fresh(bj(2026, 10, 12, 13))
            for i in range(40):
                tape.answer("mas", "/api/dispatch/runtime-snapshot", body=json.dumps({"i": i, "pad": "x" * 50}).encode())
            p = st / "tape" / "20261012.jsonl"
            recs = lines(st, "20261012")
            check("exactly one truncated line, the last", [r["kind"] for r in recs].count("truncated"), 1)
            check("... and it is the last line", recs[-1]["kind"], "truncated")
            size = p.stat().st_size
            require("the file stays near the cap", size <= 2000 + 200, size)
            tape.install(st)                                  # a restart the same day
            tape.answer("mas", "/api/other", body=b"{}")
            check("nothing more after a restart", p.stat().st_size, size)
        finally:
            tape.DAY_CAP_BYTES = cap
        st = tmpdir()
        d = st / "tape"
        d.mkdir()
        for name in ("20260920.jsonl", "20260929.jsonl", "20260930.jsonl", "20261011.jsonl", "notes.txt"):
            (d / name).write_text("{}\n")
        Clock.at = bj(2026, 10, 13, 0, 5)
        tape.install(st)
        check("days before the 14 kept are deleted, other files kept", sorted(p.name for p in d.iterdir()),
              ["20260930.jsonl", "20261011.jsonl", "20261013.jsonl", "notes.txt"])


    def check_day_boundary_and_repeats() -> None:
        print("\n[Beijing day boundary; a repeat is written once, also across a restart]")
        automas = tmpdir()
        (automas / "config").mkdir()
        (automas / "config" / "QueueConfig.json").write_text('{"Queue": 1, "Token": "abc"}', encoding="utf-8")
        st = fresh(bj(2026, 10, 12, 23, 59, 50), automas)
        tape.answer("mas", "/api/queue/get", body=b'{"a": 1}')
        Clock.at = bj(2026, 10, 12, 23, 59, 58)
        tape.answer("mas", "/api/queue/get", body=b'{"a": 1}')
        Clock.at = bj(2026, 10, 13, 0, 0, 1)                 # 2026-10-12 16:00:01 UTC
        tape.answer("mas", "/api/queue/get", body=b'{"a": 1}')
        Clock.at = bj(2026, 10, 13, 0, 5)
        tape.answer("mas", "/api/queue/get", body=b'{"a": 1}')
        Clock.at = bj(2026, 10, 13, 0, 9)
        tape.answer("mas", "/api/queue/get", body=b'{"a": 2}')
        tape.install(st, automas)                           # a restart
        Clock.at = bj(2026, 10, 13, 0, 10)
        tape.answer("mas", "/api/queue/get", body=b'{"a": 2}')
        d12, d13 = lines(st, "20261012"), lines(st, "20261013")
        cfg3 = ["config"] * len(tape.CONFIG_FILES)
        check("10-12: boot, the config files, the answer once", [r["kind"] for r in d12], ["boot", *cfg3, "mas"])
        check("10-13 opens with the config read at midnight, then the answer again",
              [r["kind"] for r in d13], ["mas", *cfg3, "mas", "boot"])
        check("config: masked by key name; a missing file says so",
              [(r["file"], r.get("json") or r["error"].split(":")[0]) for r in d12[1:4]],
              [("QueueConfig.json", {"Queue": 1, "Token": tape.MASK}), ("ScriptConfig.json", "FileNotFoundError"),
               ("PlanConfig.json", "FileNotFoundError")])
        changed = d13[1 + len(cfg3)]
        check("a changed answer says when the old one was last seen, and how often",
              (changed["json"], changed["prev_seen"], changed["repeats"]), ({"a": 2}, "2026-10-13T00:05:00.000+08:00", 1))
        check("10-13 has one config snapshot (the restart found it)", [r["kind"] for r in d13].count("config"), len(cfg3))


    def check_round_trip() -> None:
        print("\n[round trip: 10-09's maintenance notice, recorded by the real reader, replays as hand-written]")
        import fake_net
        import slice as sl
        import world as W
        from ark_relay.features.maintenance import maintenance

        day = "2026-10-09"
        hand = [e for e in W.load_outside(day) if e["kind"] == "web"]
        check("10-09 has the two hand-written web answers", len(hand), 2)
        t_read = bj(2026, 10, 9, 8, 48, 56)                   # relay.log:29955, the relay's first look

        class Sched:
            def __init__(self, t):
                self.t, self.outs = t, []

            def now(self):
                return self.t

            def park(self, timeout, ready):
                return ready()

            def out(self, kind, **f):
                self.outs.append((kind, f))

            wake = kick = lambda self: None

        def world_net(events):
            """A FakeNet given `events` through the World's own handler (state_effect)."""
            net = fake_net.FakeNet(Sched(t_read.timestamp())).install()
            stand_in = SimpleNamespace(net=net)
            for it in W.timeline(events):
                W.World.state_effect(stand_in, it, live=True)
            return net

        def window():
            win = maintenance.arknights_window(now=t_read, get=maintenance._get)
            return (win[0].isoformat(), win[1].isoformat(), win[2]) if win else None

        # 1. Record: the hand-written answers served, the real reader runs with the tape on.
        automas = tmpdir()
        (automas / "config").mkdir()
        qc = automas / "config" / "QueueConfig.json"
        qc.write_text(json.dumps({"QueueConfig": {"Name": "q"}, "SecretKey": "s3cr3t-value"}), encoding="utf-8")
        os.utime(qc, (bj(2026, 10, 8, 22).timestamp(),) * 2)
        st = fresh(bj(2026, 10, 9, 8, 30), automas)         # the day's first boot
        Clock.at = t_read
        try:
            world_net(hand)
            got_hand = window()
        finally:
            fake_net.FakeNet.uninstall()
        check("the hand-written answers give the logged window", got_hand,
              ("2026-10-09T06:00:00+08:00", "2026-10-09T12:00:00+08:00", got_hand and got_hand[2]))

        # 2. Slice the tape as the pull would hold it.
        dd = tmpdir()
        (dd / sl.TAPE).mkdir(parents=True)
        (dd / sl.TAPE / "20261009.jsonl").write_bytes((st / "tape" / "20261009.jsonl").read_bytes())
        t0 = sl.day_start(day)
        ctx = sl.Day(day, t0, t0 + 86400, dd, tmpdir())
        taped = sl.do_tape(ctx)
        evs = [ev for _t, _s, ev in sorted(ctx.events, key=lambda e: (e[0], e[1]))]
        web = [e for e in evs if e["kind"] == "web"]
        check("the tape gives as many web answers as were hand-written", len(web), len(hand))
        check("same times (from 00:00) and same answers", [(e["t"], e["answer"]) for e in web],
              [(e["t"], e["answer"]) for e in hand])
        require("each tape URL starts with the hand-written prefix",
                all(w["prefix"].startswith(h["prefix"]) for w, h in zip(web, hand, strict=True)),
                [(w["prefix"], h["prefix"]) for w, h in zip(web, hand, strict=False)])

        # 3. Replay: the World's handler with the tape's events gives the same window.
        try:
            world_net(web)
            got_tape = window()
        finally:
            fake_net.FakeNet.uninstall()
        check("replayed from the tape: the same window", got_tape, got_hand)

        # 4. The config the relay found at boot is the day's t0 config.
        cfg = [e for e in evs if e["kind"] == "mas_config"]
        check("one t0 mas_config from the tape", [(e["t"], e["path"], e.get("from_tape")) for e in cfg],
              [("2026-10-09T00:00:00+08:00", "D:/ark/automas/config/QueueConfig.json", True)])
        check("... which replaces the reconstructed one", taped, {"QueueConfig.json"})
        data = json.loads((ctx.corpus / cfg[0]["file"]).read_text(encoding="utf-8"))
        check("... with the recorded content, secret masked", data,
              {"QueueConfig": {"Name": "q"}, "SecretKey": tape.MASK})


    def check_cut_line_and_restart_times() -> None:
        print("\n[a line cut by a power-off; a change first seen after a restart]")
        import slice as sl
        st = tmpdir()
        (st / "tape").mkdir()
        cut = '{"t":"2026-10-12T21:40:00.000+08:00","kind":"web","url":"https://x.invalid/a","status":200,"len":2,"sha'
        (st / "tape" / "20261012.jsonl").write_text(
            '{"t":"2026-10-12T08:00:00.000+08:00","kind":"boot","pid":1}\n' + cut, encoding="utf-8")
        Clock.at = bj(2026, 10, 12, 21, 45)
        tape.install(st)
        check("no tape in a pull without one", sl.read_tape(tmpdir(), "2026-10-12"), ("", []))
        text = (st / "tape" / "20261012.jsonl").read_text(encoding="utf-8")
        check("the cut line is ended where it was cut", text.splitlines()[1], cut)
        dd = tmpdir()
        (dd / sl.TAPE).mkdir(parents=True)
        (dd / sl.TAPE / "20261012.jsonl").write_text(text, encoding="utf-8")
        check("slice skips the cut line and reads the next boot", [(n, r["kind"]) for n, r in sl.read_tape(dd, "2026-10-12")[1]],
              [(1, "boot"), (3, "boot")])

        dd = tmpdir()
        (dd / sl.TAPE).mkdir(parents=True)
        rows = [{"t": "2026-10-12T08:00:00.000+08:00", "kind": "boot", "pid": 1},
                {"t": "2026-10-12T08:01:00.000+08:00", "kind": "web", "url": "https://x.invalid/n", "status": 200,
                 "len": 1, "sha256": "a", "json": 1},
                {"t": "2026-10-12T12:00:00.000+08:00", "kind": "boot", "pid": 2},
                {"t": "2026-10-12T12:01:00.000+08:00", "kind": "web", "url": "https://x.invalid/n", "status": 200,
                 "len": 1, "sha256": "b", "json": 2, "prev_seen": "2026-10-12T08:01:00.000+08:00", "repeats": 0},
                {"t": "2026-10-12T12:31:00.000+08:00", "kind": "web", "url": "https://x.invalid/n", "status": 200,
                 "len": 1, "sha256": "c", "json": 3, "prev_seen": "2026-10-12T12:21:00.000+08:00", "repeats": 20}]
        (dd / sl.TAPE / "20261012.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        t0 = sl.day_start("2026-10-12")
        ctx = sl.Day("2026-10-12", t0, t0 + 86400, dd, tmpdir())
        sl.do_tape(ctx)
        check("first answer from 00:00; after a restart from the boot; else halfway",
              [(e["t"], e["answer"]) for _t, _s, e in sorted(ctx.events, key=lambda e: e[0]) if e["kind"] == "web"],
              [("2026-10-12T00:00:00+08:00", 1), ("2026-10-12T12:00:00+08:00", 2), ("2026-10-12T12:26:00+08:00", 3)])


    def check_syslog_slice() -> None:
        print("\n[a System log event on the tape becomes a syslog event at its own time]")
        import slice as sl
        from fake_proc import SysEvent
        ev = SysEvent(bj(2026, 10, 12, 21, 31, 5).timestamp(), 1075, "User32",
                      {"param1": "INS", "param2": "INS\\Administrator"})
        st = fresh(bj(2026, 10, 12, 21, 32))
        tape.syslog((1074, 1075), 600, [ev.xml()])
        dd = tmpdir()
        (dd / sl.TAPE).mkdir(parents=True)
        (dd / sl.TAPE / "20261012.jsonl").write_bytes((st / "tape" / "20261012.jsonl").read_bytes())
        t0 = sl.day_start("2026-10-12")
        ctx = sl.Day("2026-10-12", t0, t0 + 86400, dd, tmpdir())
        sl.do_tape(ctx)
        got = [(e["t"], e["event_id"], e["provider"], e["data"]) for _t, _s, e in ctx.events if e["kind"] == "syslog"]
        check("event id, provider, data and time as logged", got,
              [("2026-10-12T21:31:05+08:00", 1075, "User32", {"param1": "INS", "param2": "INS\\Administrator"})])


    if tape is None:
        require("ark_relay.features.selfcheck.tape exists", False, "no tape module")
    else:
        tape.datetime = Clock.DT
        check_noop_before_install()
        check_hooks()
        check_never_in_the_way()
        check_masking()
        check_cap_and_prune()
        check_day_boundary_and_repeats()
        check_round_trip()
        check_cut_line_and_restart_times()
        check_syslog_slice()
        tape.uninstall()
        require("no thread left behind", threading.active_count() <= 2, threading.enumerate())

    print(f"\n{'all checks passed' if not fails else f'{len(fails)} failed: {fails}'}")


def _part_transitional():
    """「中途重启」不是失败。

2026-08-28：中继在日报里列了四项失败，其中一项是鸣潮客户端更新后
正常重启。根因在 AUTO-MAS：`task/Okww/AutoProxy.py:50-54` 把
「游戏更新成功, 游戏即将重启」和「未连接游戏客户端」「流程产生错误」
一起放进 `_OKWW_BUILTIN_FATAL`，于是它写出一条非成功结果、标记 ERROR。

中继照单全收就是假警报。这组用例把新口径钉住：这类记录既不算成功、
也不进失败清单，而且这个标记必须能穿过 payload 往返（重启后重放会用到）。

    Formerly test_transitional.py.
    """
    import json
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import collector, transport

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    def write(root: Path, stem: str, result: str) -> Path:
        d = root / "2026-08-28" / "wuwa"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{stem}.json"
        f.write_text(json.dumps({"general_result": result}, ensure_ascii=False),
                     encoding="utf-8")
        return f


    def main() -> int:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)

            print("[客户端更新后重启：不是失败]")
            f = write(root, "OK-WW-05-32-24", "游戏更新成功，即将重启任务")
            rec = collector.parse_record(f, root)
            check("解析出来了", rec is not None, True)
            check("不算成功", rec.ok, False)
            check("标为中途重启", rec.transitional, True)
            check("失败清单是空的", rec.failed_tasks, [])

            print("\n[真故障：照旧算失败]")
            f2 = write(root, "OK-WW-05-40-00", "OK-WW 流程产生错误，请检查游戏状态")
            r2 = collector.parse_record(f2, root)
            check("不算成功", r2.ok, False)
            check("不是中途重启", r2.transitional, False)
            check("失败清单有内容", bool(r2.failed_tasks), True)

            print("\n[正常成功]")
            f3 = write(root, "OK-WW-05-50-00", "Success!")
            r3 = collector.parse_record(f3, root)
            check("算成功", r3.ok, True)
            check("不是中途重启", r3.transitional, False)

            print("\n[标记必须穿过 payload 往返]")
            p = transport.record_to_payload(rec)
            check("payload 带着这个键", p.get("transitional"), True)
            check("中途重启不附日志尾巴", p.get("log_tail"), "")
            back = transport.payload_to_record(p)
            check("读回来还是中途重启", back.transitional, True)
            old = {k: v for k, v in p.items() if k != "transitional"}
            check("老 payload 没这个键时默认 False（不改判历史）",
                  transport.payload_to_record(old).transitional, False)

        print("\nall checks passed" if not FAILED else f"\nFAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        raise SystemExit(main())


def _part_undone_fallback_full():
    """When the 「⚠️ 这一轮没干完」 push fails, the fallback errwatch pushes carries the
whole message, not its first line.

Audit 2026-10-13 s7 #6: errwatch keeps first_line only, and the WARNING's first
line ends at 「有项目没干成：」 (relay.log 10-11 09:30:45, 10-12 10:04:11), so the
undone items were cut off and the line went out under the relay-error title.

    Formerly test_undone_fallback_full.py.
    """
    import logging
    import os
    from datetime import datetime, timedelta


    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"),
                      ARK_AUTOMAS_DIR=str(TMP / "nowhere"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                      WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import engine as eng_mod, texts
    from ark_relay.core.config import SERVER_TZ, Config, RunRecord
    from ark_relay.core.ledger import State
    from ark_relay.features.alarm import errwatch, handle


    class Notes:
        def __init__(self, errs):
            self.sent, self.errs = [], errs

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return list(self.errs)


    class Src:
        def fetch(self, seen):
            return []


    class Grab(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.records = []

        def emit(self, r):
            self.records.append(r)


    handle._ship_evidence = lambda eng, rec: "https://cos.example/okww.zip"
    handle._hand_started = lambda eng, rec: ""
    handle._weekly_gates = lambda eng, rec: None
    handle._push_unverified = lambda eng, rec: None

    MSG = "OK-WW 这一轮有 2 项没干成，但它自己没报错：\n· 刷体力：没进本\n· 每日任务：活跃度 80/100"
    START = datetime(2026, 10, 11, 9, 0, 5, tzinfo=SERVER_TZ)


    def run(errs):
        cfg = Config()
        cfg.state_dir = TMP / f"s-{len(errs)}"
        cfg.state_dir.mkdir()
        e = eng_mod.Engine(cfg, source=Src(), state=State(cfg.state_dir), notifier=Notes(errs))
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: MSG
        rec = RunRecord(run_id="2026-10-11/wuwa/OK-WW-05-00-05", script="OK-WW", user="wuwa",
                        started=START, finished=START + timedelta(minutes=30), ok=True)
        grab = Grab()
        handle.log.addHandler(grab)
        try:
            handle._handle(e, rec)
        finally:
            handle.log.removeHandler(grab)
        return [r for r in grab.records if "有项目没干成" in r.getMessage()]


    print("[the push failed: errwatch gets the whole message under the alarm's title]")
    lines = run(["group robot down"])
    check("one WARNING", len(lines), 1)
    given = getattr(lines[0], errwatch.ALARM, None) if lines else None
    check("its own title", given[0] if given else None, texts.ROUND_INCOMPLETE)
    check("every undone item in the body", bool(given) and "刷体力：没进本" in given[1] and "每日任务" in given[1], True)
    check("the evidence link too", bool(given) and "https://cos.example/okww.zip" in given[1], True)

    print("\n[the push went out: no second copy (group_pushed as before)]")
    lines = run([])
    check("not an own alarm", getattr(lines[0], errwatch.ALARM, None) if lines else "-", None)

    print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")


def _part_verdict_no_history_log():
    """A run AUTO-MAS booked as 「正常退出」 with no history .log is not verified, not
「everything done」.

Audit 2026-10-13 s8 #4: verdict._verify_outcome returned None (= all done) when
the history log was missing or empty, contradicting its own rule that empty text
is a false green; collector sets log_path None when the .log is absent. The
machine's copied history (10-06..10-13, 38 records + hist.zip) has a .log for
every .json, so no real record shows it yet; the rule follows the code.

    Formerly test_verdict_no_history_log.py.
    """
    import types
    from datetime import datetime, timedelta


    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.features.alarm import verdict


    START = datetime(2026, 10, 12, 10, 59, 40, tzinfo=SERVER_TZ)
    root = tmpdir()
    eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=root, maa_dir=None, automas_dir=None,
                                                          state_dir=root))


    def rec(script, log_path=None):
        user = {"MAA": "arknights", "MaaEnd": "endfield", "OK-WW": "wuwa"}[script]
        return RunRecord(run_id=f"2026-10-12/{user}/{script}-06-58-38", script=script, user=user,
                         started=START, finished=START + timedelta(minutes=40), ok=True, log_path=log_path)


    for script in ("MaaEnd", "OK-WW"):
        print(f"[{script}: no history .log]")
        msg = verdict._verify_outcome(eng, rec(script))
        check("not 「everything done」", msg is not None, True)
        check("says the log is missing", "AUTO-MAS 这一轮的运行日志" in (msg or ""), True)

    print("[MaaEnd: an empty history .log]")
    empty = root / "MaaEnd-06-58-38.log"
    empty.write_text("", encoding="utf-8")
    check("not 「everything done」", verdict._verify_outcome(eng, rec("MaaEnd", empty)) is not None, True)

    print("[MAA: judged from its own log, the history log is not needed]")
    msg = verdict._verify_outcome(eng, rec("MAA")) or ""
    check("asks for MAA's own log, not AUTO-MAS's", ("MAA 自己的日志" in msg, "AUTO-MAS 这一轮" in msg), (True, False))

    print(f"\n{'all passed' if not fails else f'{len(fails)} failed: {fails}'}")


def _part_weekly_three_claims():
    """The weekly boss claims every reward left in one run, not one a day.

The user, 2026-09-29 13:28: the report said 「领了 1 次，本周还剩 1 次」 - one
claim a day, three days for what one Monday run should do. One claim per call
to FarmEchoTask was never a design: until 2026-09-07 the three claims came
from AUTO-MAS retrying an error (replay/2026-09-07/wuwa below). The claim step
then learned to click 「退出副本」, the error and the retries went away, and the
laps after the claim ran in the open world where nothing is claimed.

    Formerly test_weekly_three_claims.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.features.okww_patch import okww_overlay
    from ark_relay.features.weekly import weeklyboss


    REPLAY = Path(__file__).resolve().parent / "replay" / "2026-09-07" / "wuwa"

    print("[真实日志：09-07 那三次是报错重试凑的，每次调用只领 1 次]")
    first = (REPLAY / "OK-WW-06-00-55.log").read_text(encoding="utf-8", errors="replace")
    retry = (REPLAY / "OK-WW-06-08-44.log").read_text(encoding="utf-8", errors="replace")
    check("第一趟领了几次", first.count("周本领奖：已点确认"), 1)
    check("第一趟领完就报错（AUTO-MAS 因此重试）", "farm 4c error" in first, True)
    check("重试那趟进本前剩余", weeklyboss.left_after_claims(retry.split("周本领奖")[0]), 1)
    # 09-07 predates the read-back: its 「已点确认」 is a click, so the switch keeps the
    # pre-entry reading (2) and the next entry's own reading (1/3, the retry) decides.
    check("第一趟之后剩余：没回读就不减，留进本前读数 2", weeklyboss.left_after_claims(first), 2)
    check("重试那趟自己读到 1", weeklyboss.left_after_claims(retry), 1)

    print("\n[领完之后：还有剩余就走上游进本路径重进，领满才停]")
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)


    class Skip(Exception):
        """Stands in for ok's TaskDisabledException."""


    ns["TaskDisabledException"] = Skip
    # What _install_hooks does inside OK-WW: the stop that ends a run as failed unwinds
    # as a TaskDisabledException subclass (FarmEchoTask.run turns it into a failure).
    ns["_ArkStop"] = type("ArkStop", (Skip,), {})
    left_of = ns["_weekly_left"]
    after = ns["_after_claim"]
    readback = ns["_readback"]
    check("读出 2/3", left_of("[本周剩余可收取次数：2/3_1.00, x60_0.79]"), 2)
    check("读出 3/3（OCR 的全角斜杠）", left_of("本周剩余可收取次数：3／3"), 3)
    check("读不到就是 None", left_of("[x60_0.79]"), None)

    # The level page as the game showed it on the way back in, ok-script.log 2026-10-05:
    # 22:15:19 after the first claim, 22:17:31 after the second, 22:39:48 after the third.
    PAGE = {2: "本周剩余可收取次数：2/3_1.00", 1: "本周剩余可收取次数：1/3_1.00", 0: "本周剩余可收取次数：0/3_0.99"}


    class Task:
        def __init__(self, left, reads=(), fail=None):
            self._ark_weekly_left, self.fail, self.reads = left, fail, list(reads)
            self.entries, self.logs, self.errors, self.shots = 0, [], [], []

        def log_info(self, msg):
            self.logs.append(msg)

        def log_error(self, msg, notify=False):
            self.errors.append((msg, notify))

        def screenshot(self, name):
            self.shots.append(name)

        def teleport_to_configured_boss_and_prepare(self):
            """The way back in up to the level page, as click_configured_boss_level reads
        it (the real one runs in test_okww_daily.py)."""
            self.entries += 1
            if self.fail:
                raise self.fail
            raw = self.reads.pop(0)
            now = left_of(raw)
            before, self._ark_claim_before = self._ark_claim_before, None
            readback(self, before, now, raw)
            self._ark_weekly_left = now
            if now == 0:
                raise Skip()            # the 0/3 skip: no 单人挑战


    def run(start, reads):
        """Upstream's loop, reduced: every lap ends in a claim inside the realm and
    _after_claim takes the way back in, until a deliberate stop ends the task."""
        t = Task(start, reads)
        claims = 0
        try:
            while claims < 5:
                claims += 1
                after(t)
        except Skip:
            pass
        return claims, t.entries, t


    def stops(t):
        try:
            after(t)
        except Skip:
            return True
        return False


    c, e, t = run(3, [PAGE[2], PAGE[1], PAGE[0]])
    check("周一 3/3：一趟领 3 次，进选等级页 3 次（最后一次只读数，0/3 不进本）", (c, e), (3, 3))
    check("每次都回读确认", [m for m in t.logs if "回读确认" in m],
          ["周本领奖：回读确认领到，本周剩余 3/3→2/3", "周本领奖：回读确认领到，本周剩余 2/3→1/3",
           "周本领奖：回读确认领到，本周剩余 1/3→0/3"])
    check("没有报错", t.errors, [])
    check("领满读到 0/3 是真没事可做：不按失败结束", getattr(t, "_ark_failed", None), None)
    c, e, t = run(2, [PAGE[1], PAGE[0]])
    check("周二 2/3：一趟领 2 次", (c, e), (2, 2))
    c, e, t = run(1, [PAGE[0]])
    check("只剩 1 次：领完回去读一眼 0/3 就停", (c, e), (1, 1))
    check("领满写日志", t.logs[0], "周本领奖：本周三次已领满，回选等级页读一眼次数核对（读到 0/3 就不进本）")

    t = Task(2, [PAGE[2]])
    check("回读次数没变：停下", stops(t), True)
    check("回读次数没变：按失败结束，不是跳过", t._ark_failed, "周本领奖：回读次数没变（2/3），这次没领到")
    check("回读次数没变：报到手机", t.errors, [("周本领奖：回读次数没变（2/3），这次没领到", True)])
    check("回读次数没变：留图", t.shots, ["weekly_claim_unchanged"])
    t = Task(3, ["[x60_0.79]"])
    check("回读没读到：停下", stops(t), True)
    check("回读没读到：报到手机", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
    check("回读没读到：原文进日志", any("x60_0.79" in m for m in t.logs), True)
    t = Task(3, [PAGE[1]])
    check("回读少了两次：对不上也停", (stops(t), t.shots), (True, ["weekly_readback_mismatch"]))

    t = Task(None)
    check("进本前没读到：停下，不再进本", (stops(t), t.entries), (True, 0))
    check("进本前没读到：报到手机", t.errors[0][1] and "没读到本周剩余次数" in t.errors[0][0], True)
    t = Task(3, fail=Skip())
    try:
        after(t)
        check("波片不够 / 0/3 的有意跳过要往上抛", "没抛", "抛了")
    except Skip:
        check("波片不够 / 0/3 的有意跳过要往上抛", "抛了", "抛了")
    check("有意跳过不留回读的账", getattr(t, "_ark_claim_before", None), None)
    t = Task(3, fail=RuntimeError("Teleport to boss failed"))
    check("重进失败、没到选等级页：停下", stops(t), True)
    check("重进失败：说了没回读", any("没回读" in m and "Teleport to boss failed" in m for m in t.logs), True)
    check("重进失败：报回读没读到", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
    check("重进失败：回读的账清掉", t._ark_claim_before, None)

    print("\n[领奖钩子里真的调了它，且在 try 外面（有意跳过不被吞）]")
    src = okww_overlay.source_text()
    body = src[src.index("def incr_drop"):src.index("class _EarlyOpen")]
    check("退出副本后调 _after_claim", "_after_claim(self)" in body, True)
    tail = body[body.index("except Exception as exc"):]
    check("_after_claim 在 except 之后", "_after_claim(self)" in tail, True)
    check("进本前把剩余次数存下", "self._ark_weekly_left = now" in src, True)
    check("选等级页上做回读", "_readback(self, before, now, raw)" in src, True)

    print("\n[日报与开关：按游戏计数的最后一次读数（进本前或领完回读）]")
    d = tmpdir()


    def steps(text):
        f = d / "x.log"
        f.write_text(text, encoding="utf-8")
        return collector.parse_okww_log(f).get("okww_steps") or []


    HEAD = "2026-10-05 10:01:00,000 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
    OCR = "2026-10-05 10:02:00,000 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：{k}/3_0.99, x60_0.79]\n"
    CLAIM = "2026-10-05 10:03:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认\n"
    BACK = "2026-10-05 10:03:05,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 {k}/3→{n}/3\n"


    def claim(k):
        """One claim the overlay re-read the counter for: k left before it."""
        return CLAIM + BACK.format(k=k, n=k - 1)


    three = HEAD + OCR.format(k=3) + claim(3) + OCR.format(k=2) + claim(2) + OCR.format(k=1) + claim(1)
    check("一趟三次：日报写本周已领满", steps(three), ["周本（已完成，领了 3 次，本周已领满）"])
    check("一趟三次：开关记账剩 0（最后一次回读 1/3→0/3）", weeklyboss.left_after_claims(three), 0)
    SKIP = "2026-10-05 10:04:00,000 INFO TaskExecutor FarmEchoTask:本周周本次数已领满（0/3），不进本，跳过\n"
    back = three + OCR.format(k=0) + SKIP
    check("第三次后回读 0/3 再跳过：日报照旧写领了 3 次", steps(back), ["周本（已完成，领了 3 次，本周已领满）"])
    check("第三次后回读 0/3：开关记账剩 0", weeklyboss.left_after_claims(back), 0)
    two = HEAD + OCR.format(k=3) + claim(3) + OCR.format(k=2) + claim(2)
    check("波片只够两次：还剩 1 次", steps(two), ["周本（已完成，领了 2 次，本周还剩 1 次）"])
    check("3/3 领 1 次还剩 2 次", steps(HEAD + OCR.format(k=3) + claim(3)),
          ["周本（已完成，领了 1 次，本周还剩 2 次）"])
    check("只剩 1 次领完：本周已领满", steps(HEAD + OCR.format(k=1) + claim(1)),
          ["周本（已完成，领了 1 次，本周已领满）"])

    print("\n[只点了确认、没回读：不算领到，开关不记账]")
    clicks = HEAD + OCR.format(k=3) + CLAIM + OCR.format(k=2) + CLAIM + OCR.format(k=1) + CLAIM
    check("三次只点确认：日报不写已完成", steps(clicks), ["周本（点了确认 3 次、领完没再读次数，没核实领到）"])
    check("三次只点确认：剩余按最后一次读数 1，不减", weeklyboss.left_after_claims(clicks), 1)
    check("回读次数没变：剩余按回读的数", weeklyboss.left_after_claims(
        HEAD + OCR.format(k=2) + CLAIM + "x FarmEchoTask:周本领奖：回读次数没变（2/3），这次没领到\n"), 2)
    check("回读没读到：剩余按进本前读数", weeklyboss.left_after_claims(
        HEAD + OCR.format(k=2) + CLAIM + "x FarmEchoTask:周本领奖：回读没读到本周剩余次数\n"), 2)
    check("一个读数都没有：None", weeklyboss.left_after_claims(HEAD + CLAIM), None)


if __name__ == "__main__":
    sys.exit(run_parts([_part_activity_topup, _part_attempts_streak, _part_claim_no_claim_gate, _part_drops, _part_episodes, _part_flush_waits_own_script, _part_gathering_route_node_failed, _part_healthcheck_annihilation, _part_kuro_error_code, _part_logfile_silent, _part_logslice_new_year, _part_main_logfile_silent, _part_monthcard, _part_nofarm_visible, _part_refresh_raw_unread, _part_revive_gates, _part_scan_skips_seen, _part_setup_tasks_verify, _part_tape, _part_transitional, _part_undone_fallback_full, _part_verdict_no_history_log, _part_weekly_three_claims]))
