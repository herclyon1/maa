"""MAA collector, login reachability, cross-game outcome verification, and game-log error checks."""
from __future__ import annotations

# ruff: noqa: PLC0415
import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, fx_dir, require, run_parts, tmpdir

_SHARED = (check, fails, fx_dir, require, tmpdir)


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


def _stub_pywin32():
    """service.py imports pywin32 at module scope; stub what is missing so the
    module-level helpers can be imported on any machine."""
    for name in ("win32serviceutil", "win32service", "win32event", "win32api",
                 "win32con", "win32file", "servicemanager", "win32process",
                 "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(name, _Stub(name))


class _NoSource:
    """A record source with nothing new."""
    def fetch(self, seen):
        return []


class _Warnings(logging.Handler):
    """Keeps every record from WARNING up."""
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, r):
        self.records.append(r)


class _Notes:
    """A notifier that keeps (title, body, alert) and answers `answer` ([] when not given)."""
    def __init__(self, answer=None):
        self.sent, self._answer = [], answer

    def send(self, title, body="", **kw):
        self.sent.append((title, body, kw.get("alert", False)))
        return [] if self._answer is None else self._answer


def _part_activity_topup():
    """A waveplate-short daily activity is topped up by the evening shift (features/makeup/activity.py).
    """
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import activity, makeup
    from ark_relay.features import outcome

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
    """「重试 N 次全部失败」 counts the failed streak of this shift, not the whole day."""
    import json
    import tempfile
    import types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import RunRecord
    from ark_relay.features import handle as records

    FIX = fx_dir(Path(__file__), "fixtures") / "ledger-2026-10-10-maa.jsonl"

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



def _part_claim_no_claim_gate():
    """The claim patch must never spend waveplates while the 4-cost echo farm runs."""
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import echofarm
    from ark_relay.features import okww_overlay

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
    # 2026-11-20: while farming, the pickup toast's main stat is read first and logged
    # (「刷声骸掉落：」, counted by echofarm); nothing else happens.
    check("刷声骸时先记一行掉落的主词条", [e for e in t.events if e.startswith("log:刷声骸掉落：")][:1] != [], True)
    check("上游的掉落计数照跑", [e for e in t.events if not e.startswith("log:")][:1], ["upstream-incr"])
    check("没走去结晶、没按 F、没点确认、没重进", [e for e in t.events if not e.startswith("log:")][1:], [])
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
    import time
    from ark_relay.features import collector_maa
    REPLAY = fx_dir(Path(__file__), "replay") / "2026-09-07" / "arknights" / "MAA-05-03-55.log"
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
    """假报警两例（2026-09-02 早班实录）："""
    import json
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.features import maintenance as efstatus
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
    data = json.loads((fx_dir(Path(__file__), "fixtures") / "ef_bulletin_2026-09-02.json").read_text(encoding="utf-8"))
    hint = efstatus.update_hint(datetime(2026, 9, 2, 10, 30, tzinfo=SERVER_TZ), fetch=lambda: data)
    check("认出今天 10:00 版本更新", hint, "官方公告：今天 09:00 「雪凇幽梦」版本更新")
    check("别的日子→空", efstatus.update_hint(datetime(2026, 9, 3, 10, 30, tzinfo=SERVER_TZ), fetch=lambda: data), "")
    check("接口挂了→空不炸", efstatus.update_hint(fetch=lambda: (_ for _ in ()).throw(OSError())), "")


def _part_flush_waits_own_script():
    """A held failure alarm waits only for its own script, never for the whole queue."""
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
        e = eng.Engine(cfg, source=_NoSource(), state=State(cfg.state_dir), notifier=_Notes(False))
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
    """
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features import collect_retry as cr
    from ark_relay.features import makeup
    from ark_relay.features import collect_watch
    from ark_relay.features import collector_maaend as cm

    FIX = fx_dir(Path(__file__), "fixtures") / "maaend-2026-10-29"

    def collector_line(t, node):
        return (f"[2026-11-05 {t}.737] 2026-11-05T{t}+08:00 ERR github.com/MaaXYZ/MaaEnd/agent/go-service/"
                f"common/failurecollector/action.go:60 > FailureCollector subtask failed task={node}")

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
    REAL = fx_dir(Path(__file__), "fixtures") / "maaend-2026-11-05"
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
    from ark_relay.features import handle as pushes
    from ark_relay.features.handle import _gave_up_phrase
    phrase = _gave_up_phrase("不补跑：" + texts.makeup_only_gathering("10:24"))
    title, head = pushes._unresolved_title_head("终末地", "早班", phrase, "自动采集", "https://example.test/x")
    check("title", title, "⚠️ 终末地早班没干完")
    check("first line", head.splitlines()[0], "终末地早班跑完了但没干完：自动采集，这一类不整轮补跑（证据包 https://example.test/x）")
    check("then why no whole make-up", head.splitlines()[1],
          "没补跑：10:24 那一遍除了自动采集，别的都干完了，整轮再跑只会把干完的再做一遍；没走通的采集路线关机前单独补")
    check("plain words", texts.plain(title + head.replace("https://example.test/x", "")), [])
    t2, h2 = pushes._unresolved_title_head("终末地", "早班", "补跑也没成", "自动采集", "")
    check("any other make-up outcome: as before", (t2, h2), (texts.unresolved("终末地", "早班"),
                                                         texts.unresolved_head("终末地", "早班", "补跑也没成", "自动采集", "")))


def _part_healthcheck_annihilation():
    """The evening health check judges annihilation by the post-hand-over model."""
    import ast
    import time
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.annihilation import week_key

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
    """库街区 answering HTTP 200 with an error code in the body is a failed fetch."""
    import json
    import logging
    import tempfile
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ark_relay.features.banners as _b
    from ark_relay.features import wuwa as W
    from ark_relay.features import wuwa as H
    from ark_relay.features import wuwa as P

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
        except Exception as e:  # noqa: BLE001
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

    home = json.loads((fx_dir(Path(__file__), "fixtures") / "wuwa_home.json").read_text(encoding="utf-8"))
    g = Grab()
    _b.log.addHandler(g)
    _b._json = lambda url, *a, **k: (home if url.endswith("/homepage/getPage")
                                     else ERR if url.endswith("/getEntryDetail") else offline(url))
    _b._text = offline
    try:
        try:
            _b._wuwa(NOW, notes={}, trace=_b.Trace.new())
        except Exception:  # noqa: BLE001
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
    """
    import logging
    import time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import statestore as logfile

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
    src = logging.getLogger("ark.test_verify_maa")
    lf = logfile._log_logfile
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
    """A relay.log slice across New Year keeps the January lines."""
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
    from ark_relay.features.evidence import slice_log

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


def _part_main_logfile_silent():
    """relay.log that cannot be created is said once errwatch is listening (audit
docs/SILENT-FAILURES-AUDIT.md, __main__.py:75).
    """
    import ast
    import logging
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    _stub_pywin32()

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
    """Monthly-card reminders (user order 2026-09-26 02:47, spec BOARD/月卡到期提示-规格.md)."""
    from datetime import date

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import phone as monthcard
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
    from ark_relay.features import commands
    check("白名单、免确认", "monthcard" in commands.REVERSIBLE, True)
    p2 = tmpdir()
    monthcard.apply(p2, {"game": "终末地", "add": 1, "at": "2026-09-25T15:30:00Z"}, today=D)
    check("不带 last 只带 at（隔夜收到）：按发出那天的上海日期算第 1 天",
          monthcard.status(p2, today=D)["终末地"]["最后领取"], "2026-10-24")


def _part_nofarm_visible():
    """A one-shot switch nobody displays is a switch that gets forgotten."""
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
    from ark_relay.features import okww_overlay
    got = re.findall(r'^NO_STAMINA_FLAG = r"([^"]+)"', okww_overlay.source_text(), re.M)
    check("the override's path string equals NO_STAMINA_FARM_FLAG", got, [config.NO_STAMINA_FARM_FLAG])
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    check("and that is the value it runs with", ns.get("NO_STAMINA_FLAG"), config.NO_STAMINA_FARM_FLAG)


def _part_refresh_raw_unread():
    """refresh_raw applies the "MAA sanity never read" rule, like bookkeeping does."""
    #!/usr/bin/env python3
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector

    D = fx_dir(Path(__file__), "fixtures") / "refresh-unread-1009"
    e = json.loads((D / "ledger.jsonl").read_text(encoding="utf-8"))
    out = collector.refresh_raw(e, D)
    check("unread after refresh", (out.get("sanity"), out["raw"].get("sanity"), out["raw"].get("sanity_unread")),
          (None, None, True))


def _part_revive_gates():
    """The revival must not force-kill a window that is legitimately busy."""

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    _stub_pywin32()

    from ark_relay.features import automas_keeper, automas_keeper as automas_procs

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

    def main():
        orig = automas_procs.subprocess.run

        # 1. Installer on screen -> veto, whatever else is true.
        automas_procs.subprocess.run = _fake_run(
            {"tasklist /nh": b"AUTO-MAS-Setup.exe  1234 Console"})
        check("安装程序在跑时 _installer_running", automas_procs._installer_running(), True)

        # 2. Ordinary process list -> no veto.
        automas_procs.subprocess.run = _fake_run({"tasklist /nh": b"explorer.exe 4 Console"})
        check("平时 _installer_running", automas_procs._installer_running(), False)

        def boom(cmd, **kw): raise OSError("no tasklist")
        automas_procs.subprocess.run = boom
        check("探测失败时 _installer_running 答「不知道」(None)",
              automas_procs._installer_running(), None)
        check("探测失败时 _automas_shell_running 保守取 True",
              automas_procs._automas_shell_running(), True)

        # 4. Shell detection reads the shell, not the backend.
        automas_procs.subprocess.run = _fake_run(
            {"imagename eq auto-mas.exe": b"AUTO-MAS.exe  18864 Console"})
        check("窗口在时 _automas_shell_running", automas_procs._automas_shell_running(), True)
        automas_procs.subprocess.run = _fake_run(
            {"imagename eq auto-mas.exe": b"INFO: No tasks are running"})
        check("窗口不在时 _automas_shell_running", automas_procs._automas_shell_running(), False)

        # 5. The grace period is long enough for a real first-run wizard and far
        #    shorter than the stuck state it guards against.
        check("宽限期至少 10 分钟", automas_keeper.SHELL_GRACE_SECONDS >= 600, True)

        automas_procs.subprocess.run = orig

    main()


def _part_scan_skips_seen():
    """scan() 对处理过的记录不再解析：先按路径算 run_id，见过的直接跳过。"""
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
    check("只返回没见过的", [r.run_id for r in out], ["2026-09-07/arknights/MAA-05-00-00"])
    check("见过的根本不解析（解析次数）", len(calls), 1)


def _part_setup_tasks_verify():
    """setup-tasks.ps1's verify list covers what the relay itself needs."""
    import re

    ROOT = Path(__file__).resolve().parents[2]
    PS1 = (ROOT / "scripts" / "windows" / "setup-tasks.ps1").read_text(encoding="utf-8")
    NEW_TASK_FOLDER, NEW_TASK_NAME, NEW_WATCHDOG = "\\ArkRelay", "main", "ArkRelayWatchdog"

    verify = PS1[PS1.find('"--- verify ---"'):]
    tasks = re.findall(r'foreach \(\$t in @\(([^)]*)\)\)', verify)
    services = re.findall(r'foreach \(\$s in @\(([^)]*)\)\)', verify)
    listed_tasks = re.findall(r'"([^"]+)"', tasks[0]) if tasks else []
    listed_services = re.findall(r'"([^"]+)"', services[0]) if services else []
    check("AUTO-MAS_AutoStart still checked", "AUTO-MAS_AutoStart" in listed_tasks, True)
    check("the relay's task, as retire_legacy names it", f"{NEW_TASK_FOLDER}\\{NEW_TASK_NAME}" in listed_tasks, True)
    check("the watchdog service, as retire_legacy names it", NEW_WATCHDOG in listed_services, True)
    check("a service that is there but not running is not OK", "-ne \"Running\"" in verify, True)


def _part_tape():  # noqa: C901
    """The relay's day tape (ark_relay/features/selfcheck.py, daysim W8)."""
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
    sys.path[:0] = [str(ROOT / "relay"), str(HERE), str(ROOT / "scripts" / "mac")]

    os.environ["ARK_STATE_DIR"] = str(tmpdir())
    os.environ["ARK_MAS_PORT"] = "36163"

    try:
        from ark_relay.features import selfcheck as tape
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
        from ark_relay.features import banners
        from ark_relay.features import maintenance as efstatus, maintenance
        from ark_relay.features import redbutton as mas_client
        from ark_relay.features import shutdown

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

        def esc(v) -> str:
            return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    .replace("'", "&apos;").replace('"', "&quot;"))

        class SysEvent:
            def __init__(self, t: float, event_id: int, provider: str, data: dict) -> None:
                self.t, self.event_id, self.provider, self.data = t, event_id, provider, data

            def xml(self) -> str:
                when = datetime.fromtimestamp(self.t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z"
                data = "".join(f"<Data Name='{esc(k)}'>{esc(v)}</Data>" for k, v in self.data.items())
                return (f"<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>"
                        f"<Provider Name='{esc(self.provider)}'/><EventID>{self.event_id}</EventID>"
                        f"<TimeCreated SystemTime='{when}'/><Channel>System</Channel><Computer>INS</Computer></System>"
                        f"<EventData>{data}</EventData></Event>")

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
        from ark_relay.features import redbutton as mas_client
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
        import re

        import redact

        # The game UID label, read from the one copy of the pattern (lint-repo.sh, the identity check).
        lint = (ROOT / "scripts" / "mac" / "lint-repo.sh").read_text(encoding="utf-8")
        identity = re.compile(re.search(r"^ID_RE='([^']+)'", lint, re.M).group(1).encode())
        check("key-name hints are scripts/mac/redact.py's", tape.KEY_HINTS, redact.SECRET_KEY_HINTS)
        check("key-name exceptions are scripts/mac/redact.py's", tape.KEY_ALLOW, redact.SECRET_KEY_ALLOW)
        check("tape's mask is redact.py's", tape.MASK, redact.MASK)
        st = fresh(bj(2026, 10, 12, 12))
        akid = "AK" + "ID" + "Ab1" * 11                        # built here so this file holds no key shape
        hook = "https://qyapi.weixin.qq.com/cgi-bin/" + "webhook/send?key=" + "1a2b3c4d-" * 4
        uid = "\u7279\u5f81\u7801" + "\uff1a" + "123456789"        # the UID label, built here (lint item 11)
        body = json.dumps({"link": f"x.zip?q-ak={akid}&q-signature={'ab' * 20}", "hook": hook,
                           "Password": "hunter2hunter2", "MirrorChyanCDK": "x" * 20, "ocr": f"id {uid}",
                           "keyword": "kept"}).encode()
        tape.answer("web", hook, req={"SendKey": "SCT" + "q" * 20}, body=body)
        tape.answer("mas", "/api/x", body=("plain " + uid).encode())
        raw = (st / "tape" / "20261012.jsonl").read_bytes()
        # A COS signature alone opens nothing and committed recordings keep it, so it is not counted.
        check("no secret shape left", [n for n, pat, _r in tape.SECRET_PATTERNS if n != "cos-signature" and re.search(pat, raw)], [])
        require("no game UID left (lint item 11's pattern)", not identity.search(raw))
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
        tape.uninstall()
        require("no thread left behind", threading.active_count() <= 2, threading.enumerate())

    print(f"\n{'all checks passed' if not fails else f'{len(fails)} failed: {fails}'}")


def _part_transitional():
    """「中途重启」不是失败。"""
    import json
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import collector, collector as transport

    def write(root: Path, stem: str, result: str) -> Path:
        d = root / "2026-08-28" / "wuwa"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{stem}.json"
        f.write_text(json.dumps({"general_result": result}, ensure_ascii=False),
                     encoding="utf-8")
        return f

    def main() -> None:
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

    main()


def _part_undone_fallback_full():
    """When the 「⚠️ 这一轮没干完」 push fails, the fallback errwatch pushes carries the
whole message, not its first line.
    """
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
    from ark_relay.features import errwatch, handle

    class Notes:
        def __init__(self, errs):
            self.sent, self.errs = [], errs

        def send(self, title, body="", **kw):
            self.sent.append((title, body))
            return list(self.errs)

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
        e = eng_mod.Engine(cfg, source=_NoSource(), state=State(cfg.state_dir), notifier=Notes(errs))
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._verify_outcome = lambda r: MSG
        rec = RunRecord(run_id="2026-10-11/wuwa/OK-WW-05-00-05", script="OK-WW", user="wuwa",
                        started=START, finished=START + timedelta(minutes=30), ok=True)
        grab = _Warnings()
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



def _part_verdict_no_history_log():
    """A run AUTO-MAS booked as 「正常退出」 with no history .log is not verified, not
「everything done」.
    """
    import types
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core.config import SERVER_TZ, RunRecord
    from ark_relay.features import handle as verdict

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



def _part_weekly_three_claims():
    """The weekly boss claims every reward left in one run, not one a day."""

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector
    from ark_relay.features import okww_overlay
    from ark_relay.features import weeklyboss

    REPLAY = fx_dir(Path(__file__), "replay") / "2026-09-07" / "wuwa"

    print("[真实日志：09-07 那三次是报错重试凑的，每次调用只领 1 次]")
    first = (REPLAY / "OK-WW-06-00-55.log").read_text(encoding="utf-8", errors="replace")
    retry = (REPLAY / "OK-WW-06-08-44.log").read_text(encoding="utf-8", errors="replace")
    check("第一趟领了几次", first.count("周本领奖：已点确认"), 1)
    check("第一趟领完就报错（AUTO-MAS 因此重试）", "farm 4c error" in first, True)
    check("重试那趟进本前剩余", weeklyboss.left_after_claims(retry.split("周本领奖")[0]), 1)
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


def _part_maa_checks():
    """MAA 的结果核对——2026-08-30 之前这里是个洞，第一版判据又太吵。"""
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.handle import _maa_app_log
    from ark_relay.features.outcome import maa_checks, summarize

    CHAINS = ["StartUp", "Fight", "Infrast", "Recruit", "Mall", "Award", "CloseDown"]

    def run(chains=CHAINS, *, drop_end=(), error=(), stopped=(), extra=""):
        """造一段 asst.log：每条链一对 Start/Completed，可指定谁不收尾/谁报错。"""
        out = []
        for c in chains:
            out.append(f'[2026-08-30 09:00:00][INF] TaskChainStart '
                       f'{{"taskchain":"{c}","taskid":1}}')
            if c in error:
                out.append(f'[2026-08-30 09:10:00][INF] TaskChainError '
                           f'{{"taskchain":"{c}","taskid":1}}')
            elif c in stopped:
                out.append(f'[2026-08-30 09:10:00][INF] TaskChainStopped '
                           f'{{"taskchain":"{c}","taskid":1}}')
            elif c not in drop_end:
                out.append(f'[2026-08-30 09:10:00][INF] TaskChainCompleted '
                           f'{{"taskchain":"{c}","taskid":1}}')
        return "\n".join(out) + extra

    def main():
        print("正常一轮：七条链各一对，不许推送")
        check("全绿", summarize(maa_checks(run()), "MAA"), None)

        print("已确认无害的噪音不许把它变成告警")
        noisy = run(extra="\n[2026-08-30 09:05:00][ERR] skill has no recognition result" * 21
                          + "\n[2026-08-30 09:05:00][ERR] Unknown task: FightSeries-OldMethodFlag" * 10
                          + "\n[2026-08-30 09:06:00][TRC] asst::InfrastAbstractTask::on_run_fails | enter")
        check("噪音再多也全绿", summarize(maa_checks(noisy), "MAA"), None)

        print("开了没收尾——这才是「队列卡死、自己不吭声」的形状")
        got = maa_checks(run(drop_end=("Infrast",)))
        check("判失败", any(c.label == "每一项都做到了结尾" and not c.ok for c in got), True)
        check("说出是哪条链",
              any("Infrast" in c.detail for c in got if not c.ok), True)

        print("任务链报错 / 被中止")
        check("Error 判失败",
              any(not c.ok for c in maa_checks(run(error=("Fight",)))), True)
        check("Stopped 判失败",
              any(not c.ok for c in maa_checks(run(stopped=("Mall",)))), True)

        print("已完成的链后面多一条停止回执不算中止（2026-09-22 21:47:10.864 CloseDown 真实形状）")
        late = run(extra='\n[2026-09-22 21:47:11][INF] TaskChainStopped {"taskchain":"CloseDown","taskid":7}')
        check("收尾后的停止回执全绿", summarize(maa_checks(late), "MAA"), None)

        print("一条任务链事件都没有 = 窗口切错，不许当成没问题")
        got2 = maa_checks("随便什么日志，没有 TaskChain")
        check("判失败", any(not c.ok for c in got2), True)
        check("空文本同样不许全绿", summarize(maa_checks(""), "MAA") is not None, True)

        print("_maa_app_log 的切窗：起点和终点都要管")
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            dbg = Path(d) / "debug"
            dbg.mkdir()
            (dbg / "asst.log").write_text(
                "[2026-08-29 21:42:19][TRC] 上一趟\n"
                "  上一趟的续行\n"
                "[2026-08-30 09:09:41][INF] 本趟\n"
                "  本趟的续行\n"
                "[2026-08-30 23:00:00][INF] 下一趟\n",
                encoding="utf-8")
            got3 = _maa_app_log(d, datetime(2026, 8, 30, 9, 0),
                                datetime(2026, 8, 30, 10, 0))
            check("上一趟不带进来", "上一趟" in got3, False)
            check("上一趟的续行也不带", "上一趟的续行" in got3, False)
            check("本趟带进来", "本趟" in got3, True)
            check("本趟的续行带进来", "本趟的续行" in got3, True)
            check("下一趟不带进来（这就是没有上界时的 bug）", "下一趟" in got3, False)

            no_top = _maa_app_log(d, datetime(2026, 8, 30, 9, 0))
            check("不给上界时下一趟会进来（duration_known=False 时的取舍）",
                  "下一趟" in no_top, True)

            check("目录没配返回 None（不是空串——空串会被判据当成全绿）",
                  _maa_app_log(None, datetime(2026, 1, 1)), None)
            check("窗口内一行都没有也返回 None",
                  _maa_app_log(d, datetime(2030, 1, 1)), None)

    main()


def _part_maa_closedown_postaction():
    """MAA's CloseDown post-action cut off by AUTO-MAS's own close is not 「开了没收尾」."""
    #!/usr/bin/env python3

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.outcome import maa_checks

    LOG = (fx_dir(Path(__file__), "fixtures") / "maa-2026-10-21" / "asst-callbacks.log").read_text(encoding="utf-8")

    def bad(checks):
        return {c.label: c.detail for c in checks if not c.ok}

    require("the real record ends with a CloseDown start and no receipt",
            LOG.rstrip().endswith('"taskchain":"CloseDown","taskid":7,"uuid":"d912769d7cb0ae0a"}')
            or 'TaskChainStart {"taskchain":"CloseDown"' in LOG.splitlines()[-1])
    got = bad(maa_checks(LOG))
    require("CloseDown after AllTasksCompleted is not 「开了没收尾」", "每一项都做到了结尾" not in got, repr(got))

    no_all_done = "\n".join(l for l in LOG.splitlines() if "AllTasksCompleted" not in l)
    require("without AllTasksCompleted a dangling CloseDown still fails",
            "CloseDown" in bad(maa_checks(no_all_done)).get("每一项都做到了结尾", ""))

    lines = LOG.splitlines()
    award_start = next(i for i, l in enumerate(lines) if 'TaskChainStart {"taskchain":"Award"' in l)
    cut_award = "\n".join(l for i, l in enumerate(lines) if not (i > award_start and '"taskchain":"Award"' in l and "Start" not in l))
    require("another dangling chain still fails",
            "Award" in bad(maa_checks(cut_award)).get("每一项都做到了结尾", ""))


def _part_maa_config_rejected():
    """MAA refusing its own config, a round with no fight, and sanity MAA never read."""
    import json
    import os
    import shutil
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

    from ark_relay.core import collector, summary, texts
    from ark_relay.features import handle
    from ark_relay.features import makeup
    from ark_relay.core import ledger as core
    from ark_relay.core import engine as eng_mod
    from ark_relay.features import machinecheck as _mc
    from ark_relay.features.collector_maa import parse_maa_log
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State

    _mc.load()
    _mc_real = dict(_mc.CHECKS)
    _mc.CHECKS.clear()     # machine checks have their own tests (tests/test_mc.py)

    FX = fx_dir(Path(__file__), "fixtures") / "maa-2026-10-10"
    SANITY_UNREAD = getattr(texts, "SANITY_UNREAD", "理智没读到")   # getattr: the red run predates it

    def history(day: str) -> Path:
        """The fixture records under history/<day>/arknights/, log dates moved to `day`
    (a make-up is only for a failure of today, makeup.eligible)."""
        d = HIST / day / "arknights"
        d.mkdir(parents=True, exist_ok=True)
        for f in FX.iterdir():
            if f.suffix == ".log":
                (d / f.name).write_text(f.read_text(encoding="utf-8").replace("2026-10-10", day), encoding="utf-8")
            else:
                shutil.copy(f, d / f.name)
        return d

    print("[MAA 自己不接受配置：从这一趟自己的日志里认出来，写明哪个任务、哪一关]")
    bad = parse_maa_log(FX / "MAA-05-02-18.log")
    good = parse_maa_log(FX / "MAA-08-05-07.log")
    rej = bad.get("maa_config_rejected") or ""
    check("失败那一趟：认出 MAA 不接受配置", bool(rej))
    check("写了任务名「理智作战」和「序列化失败」", ("理智作战" in rej, "序列化失败" in rej), (True, True))
    check("写了关卡 YW-4（取自 GetFightStage 那一行）", "YW-4" in rej)
    check("正常那一趟：没有这一项", "maa_config_rejected" in good, False)

    print("\n[打了几仗：日志读到了就记（0 也记）；读不到就不记，没数据不是零]")
    check("失败那一趟：0 仗", bad.get("fight_count"), 0)
    check("正常那一趟：14 仗（开始行动 1~10、11~14）", good.get("fight_count"), 14)
    check("正常那一趟：打过关的次数照旧", good.get("run_times"), 14)

    day = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
    H = history(day)
    r_bad = collector.parse_record(H / "MAA-05-02-18.json", HIST)
    r_first = collector.parse_record(H / "MAA-05-00-01.json", HIST)
    r_good = collector.parse_record(H / "MAA-08-05-07.json", HIST)
    check("只有 json 的那一趟（第一次）：不记打了几仗", "fight_count" in (r_first.raw or {}), False)

    print("\n[理智：MAA 没读到（0 且没有回满时间）就是没读到，不是 0]")
    check("失败那一趟：理智记为没读到", (r_bad.sanity, r_bad.raw.get("sanity_unread")), (None, True))
    check("正常那一趟：理智 2 照旧", (r_good.sanity, r_good.raw.get("sanity_unread")), (2, None))
    _, body = core.format_failure(r_bad)
    check("报警里写「理智没读到」", SANITY_UNREAD in body)
    check("报警里不再写「剩余理智 0」", "剩余理智 0" in body, False)
    check("报警里写 MAA 不接受这份配置、哪个任务、哪一关",
          ("不接受这份配置" in body, "理智作战" in body, "YW-4" in body), (True, True, True))
    check("报警里写「一仗都没打」", "一仗都没打" in body)
    _, body_first = core.format_failure(r_first)
    check("日志都没有的那一趟：不说一仗都没打", "一仗都没打" in body_first, False)

    def build():
        cfg = Config()
        cfg.state_dir = tmpdir()
        cfg.automas_dir = AUTOMAS
        e = eng_mod.Engine(cfg, source=type("Src", (), {"fetch": lambda self, seen: []})(),
                           state=State(cfg.state_dir), notifier=_Notes())
        e._scripts_running = lambda: False
        e._script_running = lambda name: False
        e._unfinished_queues = lambda now, entries: []
        e._deferred_update_busy = lambda: False
        return e

    handle._ship_evidence = lambda eng, rec: ""
    summary.diagnose = lambda *a, **k: ""
    dispatched = []
    makeup._dispatch = lambda script: (dispatched.append(script), (True, "ok"))[1]
    makeup._kill_game = lambda: None

    print("\n[补跑：不接受配置的不补，理由写明；不再说「拿不准」]")
    e = build()
    e.state.append_ledger(r_bad)
    why = makeup.maa_work_done(e, r_bad)
    check("理由：MAA 不接受这份配置（理智作战 序列化失败，关卡 YW-4），原样补跑还是一样",
          why, "MAA 不接受这份配置（理智作战 序列化失败，关卡 YW-4），原样补跑还是一样")
    plain = collector.parse_record(H / "MAA-05-02-18.json", HIST)
    plain.raw.pop("maa_config_rejected", None)
    e = build()
    e.state.append_ledger(plain)
    why0 = makeup.maa_work_done(e, plain)
    check("别的失败、日志里 0 仗：说一仗都没打，不说拿不准", ("一仗都没打" in why0, "拿不准" in why0), (True, False))
    check("还是不补（只有没进游戏的才整轮补跑）", bool(why0))
    unread = collector.parse_record(H / "MAA-05-00-01.json", HIST)
    e = build()
    e.state.append_ledger(unread)
    check("日志读不到：照旧拿不准", "拿不准" in makeup.maa_work_done(e, unread))

    print("\n[整条链：两次失败落地 → 同一轮就进群一次，不压着等重试、不派补跑]")
    e = build()
    for r in (collector.parse_record(H / "MAA-05-00-01.json", HIST),
              collector.parse_record(H / "MAA-05-02-18.json", HIST)):
        e._handle(r)
    e._flush_pending()
    group = [(t, b) for t, b, a in e.notifier.sent if a]
    check("这一轮就进群一次", [t for t, _ in group], [texts.unresolved("明日方舟", "早班")])
    check("不再压着", dict(e._pending), {})
    body = group[-1][1] if group else ""
    check("开头写明没补跑的原因：不接受这份配置", "没补跑：MAA 不接受这份配置（理智作战 序列化失败，关卡 YW-4），原样补跑还是一样" in body)
    check("不再说拿不准", "拿不准" in body, False)
    check("理智没读到，不是 0", (SANITY_UNREAD in body, "剩余理智 0" in body), (True, False))
    makeup.maybe_run(e)
    check("没派补跑", dispatched, [])
    mk = makeup.read_marker(e.cfg.state_dir, day).get("MAA") or {}
    check("当天补跑记成不补，写明原因", (mk.get("result"), "不接受这份配置" in str(mk.get("note"))),
          (makeup.GAVE_UP, True))

    print("\n[记录落地顺序反过来（带原因的先到、只有 json 的后到）：照样这一轮进群、说清原因]")
    e = build()
    for r in (collector.parse_record(H / "MAA-05-02-18.json", HIST),
              collector.parse_record(H / "MAA-05-00-01.json", HIST)):
        e._handle(r)
    e._flush_pending()
    group2 = [(t, b) for t, b, a in e.notifier.sent if a]
    check("这一轮就进群一次", [t for t, _ in group2], [texts.unresolved("明日方舟", "早班")])
    body2 = group2[-1][1] if group2 else ""
    check("还是说 MAA 不接受这份配置、哪一关", ("没补跑：MAA 不接受这份配置" in body2, "YW-4" in body2), (True, True))
    check("还是说一仗都没打、理智没读到", ("一仗都没打" in body2, SANITY_UNREAD in body2), (True, True))
    check("两次都算上", "重试 2 次" in body2)
    if "--show" in sys.argv and group:
        print("\n----- alarm -----\n" + group[-1][0] + "\n" + body + "\n-----------------")

    _mc.CHECKS.update(_mc_real)


def _part_maa_start_watchdog():
    """A hung Arknights start -> end MAA.exe so AUTO-MAS restarts it now, not 45 minutes later (#137).
    """
    from datetime import datetime, timedelta

    TMP = tmpdir()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.core.notify import route_of
    from ark_relay.features import maa_start_watchdog as W

    T0 = datetime(2026, 11, 5, 9, 3, 23)
    PID = 16328

    def line(at, rest, pid=PID):
        return f"[{at:%Y-%m-%d %H:%M:%S}.760][INF][Px{pid}][Tx43461] {rest}\n"

    def chain(kind, name="StartUp"):
        return f'Assistant::append_callback | {kind} {{"taskchain":"{name}","taskid":1,"uuid":"d912769d7cb0ae0a"}}'

    def sub(task, n=1, name="StartUp", kind="SubTaskStart"):
        return ('Assistant::append_callback | ' + kind + ' {"class":"asst::ProcessTask","details":{"action":"ClickSelf",'
                f'"algorithm":"MatchTemplate","exec_times":{n},"max_times":2147483647,'
                '"result":{"rect":[611,652,58,58],"score":0.808239,"template":"GameStart.png"},'
                f'"task":"{task}"}},"first":["StartAtHome","StartWithSanity","SwitchTheme@ToggleSettingsMenu",'
                '"StartUpBegin"],"pre_task":"StartUpBegin","subtask":"ProcessTask",'
                f'"taskchain":"{name}","taskid":0,"uuid":"d912769d7cb0ae0a"}}')

    CUR_TASK = '{"class":"asst::ProcessTask","cur_task":"StartUp@GameStart","details":{"cur_retry":0,"retry_times":50}}'
    BANNER = ["-----------------------------", "MaaCore Process Start", "Version v6.21.4"]

    class World:
        """The machine as the watchdog sees it."""

        def __init__(self, name):
            self.dir = TMP / name
            (self.dir / "debug").mkdir(parents=True)
            self.log = self.dir / "debug" / "asst.log"
            self.log.write_bytes(b"")
            self.clock = T0
            self.snap = {"tasks": [{"task_info": [{"name": "MAA", "status": "运行"},
                                                  {"name": "MaaEnd", "status": "等待"}]}]}
            self.procs = [("System", 4), ("MAA.exe", PID), ("dnplayer.exe", 9000)]
            self.kills, self.sent = [], []
            self.kill_result = (True, "")
            self.dog = W.Watchdog(self, self.dir, now=lambda: self.clock, snapshot=lambda: self.snap,
                                  processes=lambda: self.procs, kill=self._kill, active=True)

        def _kill(self, pid, image):
            self.kills.append((pid, image))
            return self.kill_result

        def send(self, title, body, alert=False):
            self.sent.append((title, body, alert))
            return []

        def write(self, text):
            with self.log.open("ab") as fh:
                fh.write(text.encode("utf-8"))

        def at(self, t):
            self.clock = t
            return self.dog.tick()

    def hang_until(w, end, start=T0, pid=PID, every=4.4):
        """The 11-05 shape up to `end`: start, the resource check at +22 s, presses every 4.4 s."""
        w.write(line(start, chain("TaskChainStart"), pid))
        w.write(line(start + timedelta(seconds=3), sub("StartUpBegin"), pid))
        w.write(line(start + timedelta(seconds=22), sub("GameStartCheckResourceOCR"), pid))
        t, n = start + timedelta(seconds=29), 0
        while t <= end:
            n += 1
            w.write(line(t, sub("GameStart", n), pid))
            w.write(line(t + timedelta(seconds=3), sub("GameStart", n, kind="SubTaskCompleted"), pid))
            w.write(line(t + timedelta(seconds=4), CUR_TASK, pid))
            t += timedelta(seconds=every)
        return n

    print("[the 11-05 hang]")
    w = World("hang")
    check_at = T0 + timedelta(seconds=22)                    # the last resource-check screen, 09:03:45
    presses = hang_until(w, check_at + timedelta(seconds=299))
    check("4:59 after the last resource check: nothing", w.at(check_at + timedelta(seconds=299)), None)
    check("nothing ended yet", w.kills, [])
    w.write(line(check_at + timedelta(seconds=299.5), sub("GameStart", presses + 1)))
    presses += 1
    title = w.at(check_at + timedelta(seconds=300))
    check("5:00 after it: MAA is ended", title, texts.MAA_START_STUCK_KILLED)
    check("only MAA.exe, by the PID that wrote the start", w.kills, [(PID, "MAA.exe")])
    check("one group alarm", [(t, a) for t, _, a in w.sent], [(texts.MAA_START_STUCK_KILLED, True)])
    body = w.sent[0][1]
    check("the body says when the start began", "MAA 09:03 开始开明日方舟，5 分钟了还没进到游戏里" in body, True)
    check("the body counts the presses", f"「开始唤醒」点了 {presses} 次画面都没变" in body, True)
    check("the body says how long nothing moved", "最近 5 分钟没在下载更新，也没在校验资源" in body, True)
    check("a later look: no second kill, no second alarm", (w.at(check_at + timedelta(seconds=400)), len(w.kills), len(w.sent)),
          (None, 1, 1))

    print("[a normal start, a download, a resource check]")
    w = World("normal")
    w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=29), sub("GameStart"))
            + line(T0 + timedelta(seconds=66), chain("TaskChainCompleted"))
            + line(T0 + timedelta(seconds=67), chain("TaskChainStart", "Fight")))
    check("finished in 66 s: nothing open", (w.at(T0 + timedelta(minutes=30)), w.dog.start), (None, None))
    w = World("download")
    w.write(line(T0, chain("TaskChainStart")))
    t = T0 + timedelta(seconds=30)
    while t < T0 + timedelta(minutes=20):
        w.write(line(t, sub("GameStartUpdateOCR")))
        t += timedelta(seconds=6)
    check("20 minutes of a download: not a hang", w.at(T0 + timedelta(minutes=20)), None)
    check("the download moved the clock", w.dog.start.progress > T0 + timedelta(minutes=19), True)
    w.write(line(T0 + timedelta(minutes=20, seconds=10), sub("GameStart")))
    check("4 minutes after the download ended: still nothing", w.at(T0 + timedelta(minutes=24)), None)
    check("5 minutes after: ended", w.at(T0 + timedelta(minutes=25)), texts.MAA_START_STUCK_KILLED)
    check("its text: 25 minutes in, quiet for the last 5", "25 分钟了还没进到游戏里" in w.sent[0][1]
          and "最近 5 分钟没在下载更新" in w.sent[0][1], True)

    print("[never blind]")
    for label, change in (("no snapshot", lambda w: setattr(w, "snap", None)),
                          ("MAA 完成 in the snapshot", lambda w: setattr(w, "snap", {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"}]}]})),
                          ("no process list", lambda w: setattr(w, "procs", None)),
                          ("a different MAA.exe PID", lambda w: setattr(w, "procs", [("MAA.exe", 19236)])),
                          ("PID there but not MAA.exe", lambda w: setattr(w, "procs", [("svchost.exe", PID)]))):
        w = World("blind-" + str(abs(hash(label))))
        hang_until(w, T0 + timedelta(minutes=10))
        change(w)
        check(label + ": nothing ended", (w.at(T0 + timedelta(minutes=10)), w.kills, w.sent), (None, [], []))
    w = World("gone")
    hang_until(w, T0 + timedelta(minutes=10))
    w.procs = [("System", 4)]
    w.at(T0 + timedelta(minutes=10))
    check("the MAA that began it is gone: the start is forgotten", w.dog.start, None)

    print("[a new MAA, a closed chain, other chains]")
    w = World("retry")
    hang_until(w, T0 + timedelta(minutes=10))
    w.write("".join(line(T0 + timedelta(minutes=10, seconds=5), b, 19236) for b in BANNER))
    check("a new MAA's banner clears the open start", (w.at(T0 + timedelta(minutes=11)), w.dog.start), (None, None))
    w.procs = [("MAA.exe", 19236)]
    hang_until(w, T0 + timedelta(minutes=17), start=T0 + timedelta(minutes=11), pid=19236)
    check("the retry's own clock: 5:00 after its own check screen",
          (w.at(T0 + timedelta(minutes=11, seconds=22 + 299)), w.at(T0 + timedelta(minutes=11, seconds=22 + 300))),
          (None, texts.MAA_START_STUCK_KILLED))
    check("the retry's PID is the one ended", w.kills, [(19236, "MAA.exe")])
    w = World("same-pid")
    hang_until(w, T0 + timedelta(minutes=10))
    w.write("".join(line(T0 + timedelta(minutes=10, seconds=5), b) for b in BANNER))
    check("a banner from the same PID (reused) still clears it", (w.at(T0 + timedelta(minutes=11)), w.dog.start), (None, None))
    for kind in ("TaskChainError", "TaskChainStopped"):
        w = World("closed-" + kind)
        hang_until(w, T0 + timedelta(minutes=10))
        w.write(line(T0 + timedelta(minutes=10, seconds=1), chain(kind)))
        check(kind + " closes the start", (w.at(T0 + timedelta(minutes=11)), w.dog.start), (None, None))
    w = World("other-chain")
    w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=40), sub("GameStart", name="Fight"))
            + line(T0 + timedelta(seconds=41), chain("TaskChainCompleted", "Fight")))
    w.at(T0 + timedelta(minutes=1))
    check("a Fight press and a Fight end do not touch the start", (w.dog.start.presses, w.dog.start.at), (0, T0))

    print("[reading asst.log]")
    w = World("partial")
    whole = line(T0, chain("TaskChainStart"))
    w.write(whole[:40])
    w.at(T0 + timedelta(seconds=1))
    check("half a line: not read yet", w.dog.start, None)
    w.write(whole[40:])
    w.at(T0 + timedelta(seconds=2))
    check("the rest of it: read once", w.dog.start.at if w.dog.start else None, T0)
    w = World("rotated")
    hang_until(w, T0 + timedelta(minutes=2))
    w.at(T0 + timedelta(minutes=2))
    w.log.write_bytes(("".join(line(T0 + timedelta(minutes=3, seconds=1), b, 19236) for b in BANNER)
                       + line(T0 + timedelta(minutes=4), chain("TaskChainStart"), 19236)).encode())
    w.at(T0 + timedelta(minutes=4, seconds=10))
    check("a rotated log is read from its start", (w.dog.start.pid, w.dog.start.at), (19236, T0 + timedelta(minutes=4)))
    w = World("midway")
    filler = line(T0 - timedelta(hours=1), "x" * 300)
    w.write(filler * (W.BACKLOG_BYTES // len(filler) + 50))
    hang_until(w, T0 + timedelta(minutes=6))
    check("relay started mid-hang: the backlog finds the start and ends it", w.at(T0 + timedelta(minutes=6)),
          texts.MAA_START_STUCK_KILLED)
    w = World("old-open")
    w.write(line(T0 - timedelta(hours=12), chain("TaskChainStart"), 777))
    w.procs = [("MAA.exe", PID)]
    check("an old start left open by a MAA that is gone: nothing", (w.at(T0), w.kills), (None, []))
    w = World("off")
    w.dog.active = False
    hang_until(w, T0 + timedelta(minutes=10))
    check("not on Windows: never looks", (w.at(T0 + timedelta(minutes=10)), w.kills), (None, []))

    print("[the alarm]")
    w = World("kill-fails")
    w.kill_result = (False, "退出码 128")
    hang_until(w, T0 + timedelta(minutes=6))
    check("kill failed: its own title", w.at(T0 + timedelta(minutes=6)), texts.MAA_START_STUCK_KILL_FAILED)
    check("kill failed: says so", "结束 MAA 没成功（退出码 128）" in w.sent[0][1], True)
    check("kill failed: still one alarm", (w.at(T0 + timedelta(minutes=7)), len(w.sent)), (None, 1))
    for t in (texts.MAA_START_STUCK_KILLED, texts.MAA_START_STUCK_KILL_FAILED):
        check(f"{t}: the group route", route_of(t, alert=True), "group")
    for b in (texts.maa_start_stuck_body("09:03", 5, 69, True, "", 5),
              texts.maa_start_stuck_body("09:03", 25, 0, True, "", 5),
              texts.maa_start_stuck_body("09:03", 5, 69, False, "结束命令 30 秒没返回", 5)):
        check("plain language: " + b[:24], texts.plain(b), [])

    print("[the restart mark: the shift's clocks restart from the kill, as after AUTO-MAS's own timeout]")
    import types
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.core.statestore import StateStore
    from ark_relay.features import runwatch
    w = World("mark")
    w.dog.state_dir = w.dir / "state"
    w.dog.state_dir.mkdir()
    hang_until(w, T0 + timedelta(minutes=6))
    kill_at = T0 + timedelta(minutes=6)
    w.at(kill_at)
    store = StateStore(w.dog.state_dir)
    check("the kill leaves the timeout mark of its own moment", store.get("marks", "alerted:2026-11-05"),
          ["超时|MAA|09:09:23"])
    eng = types.SimpleNamespace(state=types.SimpleNamespace(store=store))
    due = datetime(2026, 11, 5, 9, 0, tzinfo=SERVER_TZ)
    check("runwatch.retry_clock restarts the shift from it", runwatch.retry_clock(eng, due, 87),
          datetime(2026, 11, 5, 9, 9, 23, tzinfo=SERVER_TZ))
    w = World("mark-failed-kill")
    w.dog.state_dir = w.dir / "state"
    w.dog.state_dir.mkdir()
    w.kill_result = (False, "退出码 128")
    hang_until(w, T0 + timedelta(minutes=6))
    w.at(T0 + timedelta(minutes=6))
    check("a kill that failed leaves no mark (nothing restarted)",
          StateStore(w.dog.state_dir).get("marks", "alerted:2026-11-05"), None)

    print("\n[audit 11-08 B-05: StartUp's end lost to a rotation does not get a fighting MAA killed]")
    w = World("rotated-mid-start")
    w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=30), sub("StartUpBegin")))
    w.at(T0 + timedelta(seconds=31))
    # MAA writes StartUp's completion into asst.log, then rotates it before the next read.
    w.write(line(T0 + timedelta(seconds=60), chain("TaskChainCompleted")))
    w.log.rename(w.log.with_name("asst.bak.log"))
    w.log.write_bytes(line(T0 + timedelta(seconds=70), sub("FightBegin", name="Fight")).encode())
    w.at(T0 + timedelta(seconds=75))
    check("the completion line is read from asst.bak.log", w.dog.start, None)
    w = World("rotated-lost")
    w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=30), sub("StartUpBegin")))
    w.at(T0 + timedelta(seconds=31))
    w.log.write_bytes(line(T0 + timedelta(seconds=70), chain("TaskChainStart", "Fight")).encode())   # no bak at all
    w.at(T0 + timedelta(seconds=75))
    check("no completion anywhere, but a Fight chain of the same MAA began: start closed", w.dog.start, None)
    check("so nothing is killed 10 minutes into the fight", (w.at(T0 + timedelta(minutes=10)), w.kills), (None, []))
    w = World("other-pid-chain")
    w.write(line(T0, chain("TaskChainStart")) + line(T0 + timedelta(seconds=5), chain("TaskChainStart", "Fight"), pid=999))
    w.at(T0 + timedelta(seconds=6))
    check("another MAA's chain does not close this start", w.dog.start and w.dog.start.pid, PID)


def _part_maa_unreachable_cleared_notes():
    """test_maa_unreachable.py still passes on a relay tree whose RELEASE-NOTES.md is empty."""

    import shutil
    import subprocess

    HERE = Path(__file__).resolve().parent
    RELAY = HERE.parent
    sys.path.insert(0, str(HERE))

    print("[部署后更新说明被清空：明日方舟进不了游戏那套测试照样跑完]")
    shadow = tmpdir()
    # A copy, not a symlink: the relay tests also run on Windows CI.
    shutil.copytree(RELAY / "ark_relay", shadow / "ark_relay",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (shadow / "RELEASE-NOTES.md").write_text("", encoding="utf-8")
    p = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, 'tests'); import test_verify_maa; test_verify_maa._part_maa_unreachable()",
                        "--relay", str(shadow)],
                       cwd=str(RELAY), capture_output=True, text=True, encoding="utf-8", timeout=60)
    check("退出码 0", p.returncode, 0)
    check("没有 StopIteration", "StopIteration" in p.stderr, False)
    check("最后一节也跑到了", "补跑落地后：更新照常起" in p.stdout, True)
    if fails:
        print(p.stdout[-2000:])
        print(p.stderr[-2000:])

    print("\nall checks passed" if not fails else f"\n{len(fails)} check(s) failed")


def _part_maa_window_overlap():
    """时间窗的 5 分钟余量会伸进下一趟，把下一趟的「开始」当成本趟的悬挂。"""

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import outcome

    def ev(ts, kind, chain):
        return (f'[2026-08-31 {ts}][INF][Px][Tx] '
                f'TaskChain{kind} {{"taskchain":"{chain}","uuid":"x"}}')

    # 第一趟：StartUp/Fight/CloseDown 各一对。之后是第二趟，只到 Infrast 开始就被切断。
    OVERLAP = "\n".join([
        ev("21:31:10", "Start", "StartUp"), ev("21:32:10", "Completed", "StartUp"),
        ev("21:32:11", "Start", "Fight"),   ev("21:33:30", "Completed", "Fight"),
        ev("21:33:31", "Start", "CloseDown"), ev("21:33:35", "Completed", "CloseDown"),
        # ↓ 这些是第二趟的，被 5 分钟余量捞进来了
        ev("21:33:50", "Start", "StartUp"), ev("21:34:40", "Completed", "StartUp"),
        ev("21:34:41", "Start", "Fight"),   ev("21:35:20", "Completed", "Fight"),
        ev("21:35:21", "Start", "Infrast"),          # 「完成」在 21:43，窗口够不到
    ])

    print("\n[越界的下一趟不许算进本趟]")
    res = outcome.maa_checks(OVERLAP)
    bad = [c for c in res if not c.ok]
    check("没有误报", [c.name for c in bad], [])

    print("\n[真的悬挂还是要报]")
    REAL = "\n".join([
        ev("21:31:10", "Start", "StartUp"), ev("21:32:10", "Completed", "StartUp"),
        ev("21:32:11", "Start", "Infrast"),          # 本趟自己的 Infrast 没收尾
    ])
    bad = [c for c in outcome.maa_checks(REAL) if not c.ok]
    check("报出来了", len(bad) >= 1, True)
    check("说的是 Infrast", any("Infrast" in (c.detail or "") for c in bad), True)

    print("\n[单趟不受影响]")
    ONE = "\n".join([
        ev("21:33:50", "Start", "StartUp"), ev("21:34:40", "Completed", "StartUp"),
        ev("21:35:21", "Start", "Infrast"), ev("21:43:20", "Completed", "Infrast"),
    ])
    check("全过", [c.name for c in outcome.maa_checks(ONE) if not c.ok], [])


def _part_maa_write_master_first():
    """MAA setting writes: the master copy is required, and a failure says what was written."""
    #!/usr/bin/env python3

    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.core import mastercfg

    DOC = {"Current": "Default", "Configurations": {"Default": {"TaskQueue": [
        {"Type": "StartUp"}, {"Type": "Infrast", "UsesOfDrones": "Money"}]}}}

    def drones(f: Path) -> str:
        return mastercfg._maa_infrast(json.loads(f.read_text(encoding="utf-8")))["UsesOfDrones"]

    def tree(master_doc=DOC, own_doc=DOC):
        root = tmpdir()
        automas, maa = root / "AUTO-MAS", root / "MAA"
        mf = automas / "data" / "abc123" / "Default" / "ConfigFile" / "gui.new.json"
        mf.parent.mkdir(parents=True)
        if master_doc is not None:
            mf.write_text(json.dumps(master_doc), encoding="utf-8")
        own = maa / "config" / "gui.new.json"
        own.parent.mkdir(parents=True)
        own.write_text(own_doc if isinstance(own_doc, str) else json.dumps(own_doc), encoding="utf-8")
        return automas, maa, mf, own

    def write(automas, maa):
        """write_maa's reply; an exception escaping it is a failure, kept as text."""
        try:
            return mastercfg.write_maa(automas, maa, "Infrast/UsesOfDrones", "PureGold")
        except Exception as exc:  # noqa: BLE001
            return None, f"raised {type(exc).__name__}: {exc}"

    print("[no master copy, MAA's own copy present]")
    automas, maa, mf, own = tree(master_doc=None)
    ok, msg = write(automas, maa)
    require("refused", ok is False, msg)
    require("MAA's own copy untouched", drones(own) == "Money", drones(own))
    require("says the master is missing", "母本" in msg, msg)

    print("[MAA's own copy has no Infrast task]")
    automas, maa, mf, own = tree(own_doc={"Current": "Default", "Configurations": {"Default": {"TaskQueue": []}}})
    ok, msg = write(automas, maa)
    require("refused", ok is False, msg)
    require("the master was not written either", drones(mf) == "Money", drones(mf))

    print("[MAA's own copy does not parse]")
    automas, maa, mf, own = tree(own_doc="{broken")
    ok, msg = write(automas, maa)
    require("refused without an exception, master untouched", ok is False and drones(mf) == "Money", msg)

    print("[MAA's own copy fails at write time, after the master]")
    automas, maa, mf, own = tree()
    real = mastercfg._write_maa_copies.__globals__["atomic_write_text"]

    def fail_own(path, text):
        if Path(path) == own:
            raise PermissionError("locked")
        real(path, text)

    mastercfg._write_maa_copies.__globals__["atomic_write_text"] = fail_own
    try:
        ok, msg = write(automas, maa)
    finally:
        mastercfg._write_maa_copies.__globals__["atomic_write_text"] = real
    require("master is written", drones(mf) == "PureGold", drones(mf))
    require("the reply says the master is already changed", "母本已经改好" in msg, msg)


def _part_maa_unreachable():

    import gzip
    import shutil

    HERE = Path(__file__).resolve().parent
    RELAY = HERE.parent
    if "--relay" in sys.argv:
        RELAY = Path(sys.argv[sys.argv.index("--relay") + 1]).resolve()
    sys.path.insert(0, str(RELAY))

    from ark_relay.core import collector
    from ark_relay.core import engine as eng_mod
    from ark_relay.core.config import Config
    from ark_relay.core.ledger import State
    from ark_relay.features import gameupdate
    from ark_relay.features import makeup
    from ark_relay.features import machinecheck as mc

    CORPUS = fx_dir(HERE, "gamesim") / "corpus" / "maa" / "history"

    class N:
        def __init__(self):
            self.sent = []

        def send(self, title, body="", alert=False, **kw):
            self.sent.append((title, body, alert))
            return []

        def alert_log(self):
            return None

    def booked(day: str, stem: str):
        """The corpus record as the collector books it: AUTO-MAS's layout
    <history>/<date>/<user>/<stem>.json + .log, parsed by parse_record."""
        root = tmpdir()
        dest = root / day / "arknights"
        dest.mkdir(parents=True)
        shutil.copyfile(CORPUS / day / f"{stem}.json", dest / f"{stem}.json")
        (dest / f"{stem}.log").write_bytes(gzip.decompress((CORPUS / day / f"{stem}.log.gz").read_bytes()))
        return collector.parse_record(dest / f"{stem}.json", root)

    def engine(sd: Path):
        cfg = Config()
        cfg.state_dir = sd
        cfg.automas_dir = None
        cfg.maa_dir = tmpdir()            # MAA's own debug logs: none kept for the corpus runs
        return eng_mod.Engine(cfg, source=_NoSource(), state=State(sd), notifier=N())

    print("\n[没进游戏：2026-09-23 MAA-05-00-01「MAA 未能正确登录 PRTS」]")
    rec = booked("2026-09-23", "MAA-05-00-01")
    check("认成明日方舟的失败", (rec.script, rec.ok, rec.failed_tasks), ("MAA", False, ["MAA 未能正确登录 PRTS"]))
    check("记录上写了「进不了游戏」", rec.raw.get("maa_unreachable"), True)
    sd = tmpdir()
    e = engine(sd)
    check("补跑的判断：没开始干活，可以补", makeup.maa_work_done(e, rec), "")
    makeup.never_started(e, rec)
    row = mc.read(sd).get("#65") or {}
    check("#65 过了", row.get("status"), mc.PASS)
    check("#65 没往群里推", [t for t, _, alert in e.notifier.sent if alert], [])
    State(sd).append_ledger(rec)
    check("客户端更新后会重跑它", gameupdate.needs_rerun(sd, rec.started, "MAA"), True)

    print("\n[打过仗才失败：2026-08-26 MAA-11-03-30「MAA 部分任务执行失败」]")
    rec = booked("2026-08-26", "MAA-11-03-30")
    check("是失败、有干活的证据", (rec.ok, bool(rec.raw.get("drop_statistics") or rec.raw.get("stages"))), (False, True))
    check("记录上不写「进不了游戏」", "maa_unreachable" in rec.raw, False)
    sd = tmpdir()
    e = engine(sd)
    check("补跑的判断也说不是没进游戏", makeup.maa_work_done(e, rec) != "", True)
    State(sd).append_ledger(rec)
    check("客户端更新后不重跑", gameupdate.needs_rerun(sd, rec.started, "MAA"), False)

    print("\n[跑成了：2026-09-23 MAA-05-03-07「Success!」]")
    rec = booked("2026-09-23", "MAA-05-03-07")
    check("成功、不写「进不了游戏」", (rec.ok, "maa_unreachable" in rec.raw), (True, False))

    print("\n[一条规则：语料里每一条明日方舟失败，记账写的标记和补跑的判断都对得上]")
    sd = tmpdir()
    e = engine(sd)
    seen, disagree = 0, []
    for js in sorted(CORPUS.glob("*/*.json")):
        if js.name == "expected.json" or not js.with_suffix(".log.gz").exists():
            continue
        r = booked(js.parent.name, js.stem)
        if r is None or r.ok or r.script != "MAA" or not r.failed_tasks:
            continue
        seen += 1
        if bool(r.raw.get("maa_unreachable")) != (makeup.maa_work_done(e, r) == ""):
            disagree.append(r.run_id)
    check("看过的失败不少于 20 条", seen >= 20, True)
    check("没有一条对不上", disagree, [])

    print("\n[同一轮：前一次打过仗才中止、后一次没登录上，客户端更新后不再整轮重跑]")
    from datetime import datetime
    from ark_relay.core.config import SERVER_TZ

    def today_round(*picks, maintenance=False):
        """Book the corpus records onto today's ledger one hour apart from 05:00; the
    last is the round's latest attempt. Returns (state dir, engine, last record)."""
        now = datetime.now(tz=SERVER_TZ)
        sd = tmpdir()
        e = engine(sd)
        last = None
        for i, (cday, stem) in enumerate(picks):
            r = booked(cday, stem)
            r.run_id = f"{now:%Y-%m-%d}/arknights/{stem}"
            r.started = now.replace(hour=5 + i, minute=0, second=1, microsecond=0)
            r.finished = r.started.replace(minute=10)
            last = r
            if i == len(picks) - 1 and maintenance:
                r.raw.pop("maa_unreachable", None)
                r.raw["maintenance"] = "05:00-10:00"
            e.state.append_ledger(r)
        return sd, e, last

    A, B, OK = ("2026-08-26", "MAA-05-16-47"), ("2026-09-23", "MAA-05-00-01"), ("2026-09-23", "MAA-05-03-07")
    a = booked(*A)
    check("A：失败、吃过理智药、不写「进不了游戏」",
          (a.ok, bool(a.raw.get("medicine_used")), "maa_unreachable" in a.raw), (False, True, False))
    sd, e, b = today_round(A, B)
    check("B 自己写了「进不了游戏」", b.raw.get("maa_unreachable"), True)
    check("补跑的判断：这一轮打过仗，不补", makeup.maa_work_done(e, b) != "", True)
    check("客户端更新后不整轮重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), False)
    sd, e, b = today_round(A, B, maintenance=True)
    check("B 撞上维护：这一轮打过仗，维护后也不整轮重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), False)
    # The round crossed midnight: A started yesterday 23:50, B today 00:05 (AUTO-MAS's
    # retry within makeup.RETRY_CHAIN); the ledger files each by its own start day.
    from datetime import timedelta
    sd = tmpdir()
    e = engine(sd)
    today0 = datetime.now(tz=SERVER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    for (cday, stem), start in ((A, today0 - timedelta(minutes=10)), (B, today0 + timedelta(minutes=5))):
        r = booked(cday, stem)
        r.run_id = f"{start:%Y-%m-%d}/arknights/{stem}"
        r.started, r.finished = start, start + timedelta(minutes=8)
        e.state.append_ledger(r)
    check("跨午夜的一轮：前一天打过仗，客户端更新后也不整轮重跑", gameupdate.needs_rerun(sd, r.started, "MAA"), False)
    # Controls: the round rule still re-runs a round that never got going.
    sd, e, b = today_round(B)
    check("只有 B 一次：重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), True)
    sd, e, b = today_round(A, OK, B)
    check("A 和 B 中间跑成过一轮：B 这一轮没开始干活，重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), True)
    check("补跑的判断也一样", makeup.maa_work_done(e, b), "")
    sd, e, b = today_round(B, maintenance=True)
    check("只有 B 一次、撞上维护：维护后重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), True)
    # A maintenance attempt whose failure text is not a login failure but shows no work
    # (the servers were down, so it could not fight) is still re-run after the update.
    sd = tmpdir()
    b = booked(*B)
    b.run_id = f"{datetime.now(tz=SERVER_TZ):%Y-%m-%d}/arknights/MAA-05-00-01"
    b.started = b.finished = datetime.now(tz=SERVER_TZ).replace(hour=5, minute=0, second=1, microsecond=0)
    b.failed_tasks = ["MAA 在完成任务前中止"]
    b.raw.pop("maa_unreachable", None)
    b.raw["maintenance"] = "05:00-10:00"
    State(sd).append_ledger(b)
    check("撞上维护、没打过仗的别的失败：维护后照旧重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), True)
    # The same attempt with its log unread (no fight count): the marked span reaches
    # 45 minutes past the window, when the servers may be up, so it may have fought.
    sd = tmpdir()
    b.raw.pop("fight_count", None)
    State(sd).append_ledger(b)
    check("撞上维护、日志没读到的别的失败：拿不准打没打过，不重跑", gameupdate.needs_rerun(sd, b.started, "MAA"), False)

    print("\n[整轮不补时发一条通知（Server酱，不进群）说为什么]")
    import types
    from ark_relay.core import texts
    for label, maint in (("登录不上", False), ("撞上维护", True)):
        sd, e, b = today_round(A, B, maintenance=maint)
        notes, reran, problems, sent = [], [], [], []
        gameupdate._rerun_script(types.SimpleNamespace(state_dir=sd), b.started,
                                 lambda s: sent.append(s) or (True, "ok"), "MAA", reran, problems, notes)
        check(f"{label}：没派明日方舟", (sent, reran, problems), ([], [], []))
        why = makeup.maa_round_work_done(State(sd).read_ledger, e.state.read_ledger(f"{b.started:%Y-%m-%d}")[-1],
                                         downtime=maint)
        check(f"{label}：说了为什么不补跑（补跑的同一条理由）",
              (bool(why), notes), (True, [f"MAA：客户端更新好了，这一轮不再整轮补跑：{why}"]))
        # A fought (fight_count 8, medicine_used 2): the reason names it, not 「拿不准」.
        check(f"{label}：理由说的是前面打过仗、吃过理智药",
              ("这一轮已经开始干活" in why, "吃过理智药" in why, "拿不准" in why), (True, True, False))
        check(f"{label}：那句话是大白话", [texts.plain(n) for n in notes], [[]])
    sd, e, b = today_round(B)
    notes, reran, sent = [], [], []
    gameupdate._rerun_script(types.SimpleNamespace(state_dir=sd), b.started,
                             lambda s: sent.append(s) or (True, "ok"), "MAA", reran, [], notes)
    check("只有 B 一次：照旧补跑、不多说话", (sent, reran, notes), (["MAA"], ["MAA"], []))

    # Where the note lands: the engine sends run_deferred's notes; follow it through
    # notify.route_of. It is not an alarm, so the info route only (notify._INFO_ORDER),
    # never the group - and the release note must say so (it claimed the group before).
    from ark_relay.core import notify
    sd, e, b = today_round(A, B)
    e._unfinished_queues = lambda *a, **k: []
    e._scripts_running = lambda *a, **k: False

    def _deferred(cfg, now=None, dispatch=None, **k):
        out: list = []
        gameupdate._rerun_script(cfg, now, lambda s: (True, "ok"), "MAA", [], [], out)
        return out, [], []

    real_gu = (gameupdate.pending, gameupdate.run_deferred)
    gameupdate.pending = lambda state_dir: {"明日方舟": "今天官方维护"}
    gameupdate.run_deferred = _deferred
    try:
        e._maybe_deferred_update()
        t = getattr(e, "_gu_thread", None)
        if t is not None:
            t.join(10)
    finally:
        gameupdate.pending, gameupdate.run_deferred = real_gu
    routes = [notify.route_of(title, alert=alert) for title, body, alert in e.notifier.sent
              if "不再整轮补跑" in body]
    check("不补跑的那句：走通知，不进群", routes, ["info"])
    check("通知那一路就是 Server酱", notify._ORDERS["info"], ("Server酱",))
    # deploy-relay.sh empties RELEASE-NOTES.md and commits that on every deploy, so the
    # line is gone between deploys: check its wording only while it is there.
    line = next((x for x in (RELAY / "RELEASE-NOTES.md").read_text(encoding="utf-8").splitlines()
                 if "不再把整轮重跑" in x), None)
    if line is None:
        print("  ok   更新说明里没有这一行（部署后清空是正常状态），措辞检查跳过")
    else:
        check("更新说明说对了去处：不说「群里会说」，说不进群", ("群里" in line, "不进群" in line), (False, True))

    print("\n[维护日：补跑刚派下去还没落地，队列后更新先不起，不会把同一趟明日方舟再派一次]")
    from datetime import datetime
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import makeup as mk

    now = datetime.now(tz=SERVER_TZ)
    day = now.strftime("%Y-%m-%d")
    rec = booked("2026-09-23", "MAA-05-00-01")
    rec.run_id = f"{day}/arknights/MAA-05-00-01"
    rec.started = rec.finished = now.replace(hour=0, minute=0, second=1)
    sd = tmpdir()
    e = engine(sd)
    e.state.append_ledger(rec)
    e._unfinished_queues = lambda *a, **k: []
    mk._write_marker(sd, day, {"MAA": {"result": mk.DISPATCHED, "dispatched_at": now.isoformat(),
                                       "run_id": rec.run_id, "tries": 1}})
    ran: list = []
    real_gu = (gameupdate.pending, gameupdate.run_deferred)
    gameupdate.pending = lambda state_dir: {"明日方舟": "今天官方维护"}
    gameupdate.run_deferred = lambda cfg, now=None, dispatch=None, **k: (ran.append(gameupdate.needs_rerun(sd, now, "MAA")) or ([], [], []))
    try:
        e._maybe_deferred_update()
        t = getattr(e, "_gu_thread", None)
        if t is not None:
            t.join(10)
        check("补跑在路上：更新没起", ran, [])
        check("没往群里推", [x for x in e.notifier.sent if x[2]], [])
        mk._write_marker(sd, day, {"MAA": {"result": mk.OK, "dispatched_at": now.isoformat(),
                                           "run_id": rec.run_id, "record": rec.run_id, "tries": 1}})
        e._maybe_deferred_update()
        e._gu_thread.join(10)
        check("补跑落地后：更新照常起", len(ran), 1)
    finally:
        gameupdate.pending, gameupdate.run_deferred = real_gu


def _part_outcome_main():
    """结果核对：出现在日志里 != 做成了。"""

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ark_relay.features.outcome import maa_sanity_short, maaend_checks, okww_checks, patch_effect_checks, summarize

    def bad_labels(checks):
        return sorted(c.label for c in checks if not c.ok)

    def main() -> None:
        print("[三轮真实日志：任务起来了但一场没打]")
        # 11:13 那轮：找到了任务、开了界面，然后原地退出
        text = ("NightmareNestTask:opened gray_book_boss\n"
                "NightmareNestTask:open_boss_book canxiang\n"
                "DailyTask:Daily Task Completed\n"
                "ForgeryTask:not enough stamina\n")
        got = okww_checks(text, expect_nest=True)
        check("残象聚落被判为没干成", "残象聚落" in bad_labels(got), True)
        check("每日任务算跑完", "每日任务跑完" not in bad_labels(got), True)
        check("体力不足不算故障", "刷体力" not in bad_labels(got), True)

        print("\n[配置里的点位名对不上——这是故障，不是「已满」]")
        text2 = ("NightmareNestTask:nightmare nest: 列表里没找到指定的点位 ['落渊南丘']\n"
                 "DailyTask:Daily Task Completed\n"
                 "ForgeryTask:enter combat None\n")
        got2 = okww_checks(text2, expect_nest=True)
        check("点位找不到算故障", "残象聚落" in bad_labels(got2), True)
        check("说清是名字对不上，让人去核对（不写「多半」）",
              any("核对配置里的名字" in c.detail and "多半" not in c.detail for c in got2 if not c.ok), True)

        print("\n[真的打了——这才算干成]")
        text3 = ("NightmareNestTask:open_boss_book canxiang\n"
                 "Box(name='已击败残象：0/41', x=890, y=373) is not complete\n"
                 "NightmareNestTask:enter combat None\n"
                 "DailyTask:Daily Task Completed\n"
                 "ForgeryTask:enter combat None\n")
        got3 = okww_checks(text3, expect_nest=True)
        check("有战斗证据就算干成", bad_labels(got3), [])
        check("全都干成时不报警", summarize(got3, "OK-WW"), None)

        print("\n[点位已打满：正常，不该报警]")
        text4 = ("NightmareNestTask:nightmare nest: 指定点位都已打满，跳过\n"
                 "DailyTask:Daily Task Completed\n"
                 "ForgeryTask:used all stamina\n")
        got4 = okww_checks(text4, expect_nest=True)
        check("已满不算故障", bad_labels(got4), [])

        print("\n[没配残象聚落时不该凭空要求它]")
        got5 = okww_checks("DailyTask:Daily Task Completed\nForgeryTask:enter combat None\n",
                           expect_nest=False)
        check("不检查没配置的项", bad_labels(got5), [])

        print("\n[MaaEnd 卡弹窗：自己不报错，靠 on_error 截图抓出来]")
        mtext = "2026-08-27 09:51:24 INFO [App] 自动执行任务完成，关闭自身\n"
        shots = ["2026.08.27-09.44.59.746_SceneAnyEnterWorld.png",
                 "2026.08.27-09.51.23.972_SceneAnyEnterWorld.png"]
        mgot = maaend_checks(mtext, shots)
        check("「跑完了」不等于「没卡住」", "界面没卡住" in bad_labels(mgot), True)
        check("跑完这一项仍算通过", "MaaEnd 跑完" not in bad_labels(mgot), True)
        msg = summarize(mgot, "MaaEnd")
        check("会给出人话告警", msg is not None and "没干成" in msg, True)
        check("告警里带上截图名", "SceneAnyEnterWorld" in (msg or ""), True)

        print("\n[MaaEnd 干净跑完]")
        check("没有截图就不报警", summarize(maaend_checks(mtext, []), "MaaEnd"), None)

        text6 = ("DailyTask:info_set current daily progress 0\n"
                 "DailyTask:info_set total daily points 110\n"
                 "DailyTask:info_set current task claim daily\n"
                 "DailyTask:Daily Task Completed\n")
        got6 = okww_checks(text6, expect_nest=True)
        check("开始时已完成→不报警", summarize(got6, "OK-WW"), None)
        check("开始时已完成→只有一条「仅领奖」",
              [c.label for c in got6], ["今日日常此前已完成，本轮仅领奖"])
        # 已完成但连领奖收尾都没跑完——这个才要报
        got7 = okww_checks("DailyTask:info_set total daily points 110\n",
                           expect_nest=True)
        check("已完成但没收尾→要报", summarize(got7, "OK-WW") is not None, True)
        # 正常早班：开始时 90 分未满，照常核对
        text8 = ("DailyTask:info_set total daily points 90\n"
                 "NightmareNestTask:open_boss_book canxiang\n"
                 "DailyTask:Daily Task Completed\n"
                 "ForgeryTask:not enough stamina\n")
        got8 = okww_checks(text8, expect_nest=True)
        check("未满时照常核对（巢穴没打要报）",
              any(c.label == "残象聚落" and not c.ok for c in got8), True)

        print("\n[每条改动：触发了就得有它那句话（2026-09-07 周本、09-13 巢穴真实行）]")
        wk = ("2026-09-07 10:06:33,670 INFO TaskExecutor FarmEchoTask:left_click boss_proceed (1824, 416) after_sleep 1\n"
              "2026-09-07 10:06:35,359 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：2/3_1.00, x60_0.79]\n")
        check("周本触发且有痕迹", bad_labels(patch_effect_checks(wk)), [])
        wk_bad = wk.splitlines()[0] + "\n"
        check("周本触发但没痕迹＝改动没跑到", "周本改动在跑（进本前读剩余次数）" in bad_labels(patch_effect_checks(wk_bad)), True)
        check("没触发就不评判", patch_effect_checks("DailyTask:Daily Task Completed\n"), [])
        # An empty read proves the override ran, not that it read the count.
        wk_empty = wk.replace("[本周剩余可收取次数：2/3_1.00, x60_0.79]", "[]")
        check("读到空列表不算痕迹", "周本改动在跑（进本前读剩余次数）" in bad_labels(patch_effect_checks(wk_empty)), True)
        day = ("2026-09-13 09:21:58,916 INFO TaskExecutor NightmareNestTask:opened gray_book_boss\n"
               "2026-09-13 12:45:52,773 INFO TaskExecutor NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）\n"
               "2026-09-13 09:33:01,760 INFO TaskExecutor TacetTask:info_set current_stamina 239\n")
        check("M7 之前的日志没有体力原文＝体力改动没跑", bad_labels(patch_effect_checks(day, tacet_shot_today=True)),
              ["体力读数改动在跑（读字原文进日志）"])
        day += "2026-09-13 09:33:01,700 INFO TaskExecutor TacetTask:体力读字原文（第 1 次）: ['55', '239/240', '+']\n"
        check("巢穴＋顺序都对", bad_labels(patch_effect_checks(day, tacet_shot_today=True)), [])
        check("刷了无音区但没留图", "无音区改动在跑（结算页留图）" in bad_labels(patch_effect_checks(day, tacet_shot_today=False)), True)
        day_old = day.replace("nightmare nest: 只刷 ['落渊南丘']（设置来自母本）", "left_click 已击败残象：0/48")
        check("09-13 09:19 那种：打开了页面却没有「只刷」＝没跑到", "巢穴改动在跑（只刷指定点位）" in bad_labels(patch_effect_checks(day_old)), True)
        wrong_order = "\n".join(day.splitlines()[2:3] + day.splitlines()[0:2]) + "\n"
        check("刷体力在巢穴之前＝顺序改动没生效", "日常改动在跑（附加任务提到刷体力之前）" in bad_labels(patch_effect_checks(wrong_order)), True)

        print("\n[MAA 理智不够没打：2026-09-14 09:02 剿灭真实行]")
        sh = ("[2026-09-14 09:02:17.941][INF][Px14564][Tx21613] asst::FightTimesTaskPlugin::analyze_sanity_remain Current Sanity: 17 , Max Sanity: 210\n"
              '[2026-09-14 09:02:17.941][INF][Px14564][Tx21613] Assistant::append_callback | SubTaskExtraInfo {"class":"asst::FightTimesTaskPlugin","details":{"sanity_cost":25,"series":1,"times_finished":0},"subtask":"FightTimesTask","taskchain":"Fight","taskid":2}\n')
        check("17 < 25 且 0 次 = 理智不够", maa_sanity_short(sh), {"have": 17, "cost": 25})
        check("打了一次就不算", maa_sanity_short(sh.replace('"times_finished":0', '"times_finished":1')), None)
        check("理智够就不算", maa_sanity_short(sh.replace("Current Sanity: 17", "Current Sanity: 90")), None)
        check("没有这些行就不判", maa_sanity_short("TaskChainStart Fight\n"), None)
        no_conn = ("[2026-11-09 09:01:43.100][INF][Px12844][Tx3] -----------------------------\n"
                   "[2026-11-09 09:01:57.063][INF][Px12844][Tx11] connect return: false\n")
        nxt = ("[2026-11-09 09:03:19.000][INF][Px2236][Tx5] -----------------------------\n"
               + sh.replace("2026-09-14 09:02:17", "2026-11-09 09:04:43").replace("Px14564", "Px2236")
                   .replace("Current Sanity: 17", "Current Sanity: 20"))
        check("下一趟（另一个 MAA 进程）读的理智不算到没连上的这一趟", maa_sanity_short(no_conn + nxt), None)
        check("那一趟自己读的照算", maa_sanity_short(nxt), {"have": 20, "cost": 25})

        print("\n[周本没领奖＝没干成（2026-09-14 09:19 真实行）]")
        wb = ("2026-09-14 10:02:00,000 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
              "2026-09-14 10:02:15,000 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：3/3_1.00, x60_0.79]\n"
              "2026-09-14 10:02:30,615 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm\n"
              "2026-09-14 10:02:32,000 INFO TaskExecutor FarmEchoTask:enter combat None\n"
              "2026-09-14 10:04:16,000 INFO TaskExecutor FarmEchoTask:left_click claim_cancel_button_hcenter_vcenter (538, 675) after_sleep 0\n"
              "DailyTask:Daily Task Completed\n"
              "ForgeryTask:used all stamina\n")
        check("打了没领＝红", "周本领到了奖励" in bad_labels(okww_checks(wb, expect_nest=False)), True)
        nowb = wb.replace("2026-09-14 10:02:30,615 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm\n", "")
        nowb = nowb.replace("2026-09-14 10:02:32,000 INFO TaskExecutor FarmEchoTask:enter combat None\n", "")
        check("没进本不说「打了」", bad_labels(okww_checks(nowb, expect_nest=False)).count("周本"), 1)
        check("触发→痕迹也报", "周本领奖改动在跑（打完按 F 领奖）" in bad_labels(patch_effect_checks(wb)), True)
        ok_line = "2026-09-14 10:04:25,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3\n"
        click = "2026-09-14 10:04:20,000 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认\n"
        wb_ok = wb + click + ok_line
        check("回读确认领到＝绿", "周本领到了奖励" not in bad_labels(okww_checks(wb_ok, expect_nest=False)), True)
        check("回读确认领到＝改动有痕迹", bad_labels(patch_effect_checks(wb_ok)), [])
        # The click alone is logged before anything shows the claim landed.
        only_click = okww_checks(wb + click, expect_nest=False)
        check("只有「已点确认」＝不算领到", "周本领到了奖励" in bad_labels(only_click), True)
        check("只有「已点确认」：说没回读",
              [c.detail for c in only_click if c.label == "周本领到了奖励"],
              ["点了确认 1 次、领完没再读次数，没核实领到"])
        check("只有「已点确认」＝改动没做成", "周本领奖改动在跑（打完按 F 领奖）" in bad_labels(patch_effect_checks(wb + click)), True)
        same = wb + click + "2026-09-14 10:04:25,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读次数没变（3/3），这次没领到\n"
        check("回读次数没变＝红、说没领到",
              [c.detail for c in okww_checks(same, expect_nest=False) if c.label == "周本领到了奖励"],
              ["领完再读次数没变 1 次，没领到"])
        unread = wb + click + "2026-09-14 10:04:25,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读没读到本周剩余次数\n"
        check("回读没读到＝红", "周本领到了奖励" in bad_labels(okww_checks(unread, expect_nest=False)), True)
        # Failure lines of the claim hook are not its trace (they used to match 「周本领奖：」).
        for fail_line in ("周本领奖：这一步没做成 WaitFailedException()",
                          "周本领奖：没认出领奖弹窗，整屏读到 [x60_0.79]"):
            got = patch_effect_checks(wb + f"2026-09-14 10:04:20,000 INFO TaskExecutor FarmEchoTask:{fail_line}\n")
            check(f"失败行不算痕迹：{fail_line[:12]}", "周本领奖改动在跑（打完按 F 领奖）" in bad_labels(got), True)
        wb_cap = wb.replace("3/3_1.00", "0/3_0.99") + "FarmEchoTask:本周周本次数已领满（0/3），不进本，跳过\n"
        check("本周领满＝绿", "周本领到了奖励" not in bad_labels(okww_checks(wb_cap, expect_nest=False)), True)
        short_label = "周本（结晶波片不足，奖励没领）"
        short_old = wb + "2026-09-14 10:04:20,000 INFO TaskExecutor FarmEchoTask:结晶波片不足，取消并跳过本次周本\n"
        got_old = okww_checks(short_old, expect_nest=False)
        check("波片不足（旧行）＝红、进群", (bad_labels(got_old), "结晶波片不足" in (summarize(got_old, "OK-WW") or "")),
              ([short_label], True))
        check("波片不足（旧行）＝说奖励没领", [(c.label, c.ok, c.detail) for c in got_old if c.label.startswith("周本")],
              [(short_label, False, "周本奖励没领：结晶波片不足")])
        short_new = short_old + ("2026-09-14 10:04:21,000 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束："
                                 "周本：结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」）\n")
        got_new = okww_checks(short_new, expect_nest=False)
        check("波片不足（新行，覆盖层按失败结束）＝红、进群",
              (bad_labels(got_new), summarize(got_new, "OK-WW") is not None), ([short_label], True))
        check("波片不足（新行）＝说奖励没领", [c.label for c in got_new if c.label.startswith("周本")], [short_label])
        got_part = okww_checks(wb_ok + short_new.replace(wb, ""), expect_nest=False)
        check("领到一次后波片不足＝红、说领到几次",
              [(c.label, c.ok) for c in got_part if c.label.startswith("周本")],
              [("周本（这一趟领到了 1 次，之后结晶波片不足，剩下的奖励没领）", False)])
        check("领到一次后波片不足＝进群", summarize(got_part, "OK-WW") is not None, True)
        # A genuinely incomplete weekly run still fails and reaches the group: the claim
        # step is absent AND no waveplate shortage explains it.
        check("没进本的周本仍然进群", summarize(okww_checks(nowb, expect_nest=False), "OK-WW") is not None, True)
        weekly_full = (fx_dir(Path(__file__), "fixtures")
                       / "okww-1006-weekly-full.log").read_text(encoding="utf-8")
        wfull = okww_checks(weekly_full, expect_nest=False, expect_daily=False, expect_stamina=False)
        check("更新说明里的「结晶波片不足」不再判没干完", "周本领到了奖励" not in bad_labels(wfull), True)
        check("更新说明里的「结晶波片不足」不进群", summarize(wfull, "OK-WW"), None)
        real_short = ("2026-10-06 09:21:23,627 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
                      "2026-10-06 09:21:52,194 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：3/3_0.99, x60_0.79]\n"
                      "2026-10-06 09:21:59,000 INFO TaskExecutor FarmEchoTask:波片不足挡住开启挑战，点取消跳过本次周本\n"
                      "2026-10-06 09:22:00,000 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本：结晶波片不够领奖（游戏提示「结晶波片不足，无法获取奖励」），点了取消，这一趟没打\n")
        got_real = okww_checks(real_short, expect_nest=False, expect_daily=False, expect_stamina=False)
        check("真的波片不足进群", "结晶波片不足" in (summarize(got_real, "OK-WW") or ""), True)
        check("真的波片不足＝说奖励没领", [(c.label, c.ok) for c in got_real], [(short_label, False)])
        # A changelog or other non-task line carrying the overlay's wording does not count.
        fake = real_short.replace("INFO TaskExecutor FarmEchoTask:波片不足", "INFO MainThread pyappify-update:波片不足")
        check("别的进程行里的波片不足不算", summarize(okww_checks(fake, expect_nest=False, expect_daily=False,
                                                             expect_stamina=False), "OK-WW") is not None, True)
        stop_unknown = wb + "2026-09-14 10:04:21,000 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本：回读没读到本周剩余次数\n"
        check("不认识的画面停下＝红", "周本领到了奖励" in bad_labels(okww_checks(stop_unknown, expect_nest=False)), True)
        # Any other reason the week's claim was not made still reaches the group.
        check("周本别的原因没领仍进群", summarize(okww_checks(stop_unknown, expect_nest=False), "OK-WW") is not None, True)
        check("周本打了没领（没有波片不足）仍进群", summarize(okww_checks(wb, expect_nest=False), "OK-WW") is not None, True)
        skip_day = nowb.replace("3/3_1.00", "0/3_0.99") + "FarmEchoTask:本周周本次数已领满（0/3），不进本，跳过\n"
        check("0/3 跳过的日子不评判领奖改动（没打就没得领）", bad_labels(patch_effect_checks(skip_day)), [])

        print("\n[进了本没打：2026-10-05 早班真实行（ark-evidence 2026-10-05_wuwa_OK-WW-05-39-25）]")
        # Landed, 「打完了」 20 seconds later, no 「FarmEchoTask:enter combat」 at all.
        oct5 = ("2026-10-05 10:33:22,369 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
                "2026-10-05 10:33:35,438 INFO TaskExecutor FarmEchoTask:left_click boss_proceed (1824, 416) after_sleep 1\n"
                "2026-10-05 10:33:48,793 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm\n"
                "2026-10-05 10:33:49,173 INFO TaskExecutor FarmEchoTask:start wait in combat\n"
                "2026-10-05 10:33:49,217 INFO TaskExecutor FarmEchoTask:boss_string is []\n"
                "2026-10-05 10:34:08,629 INFO TaskExecutor FarmEchoTask:farm echo walk_find_echo None\n"
                "2026-10-05 10:34:08,702 INFO TaskExecutor FarmEchoTask:周本领奖：打完了，去结晶按 F\n"
                "2026-10-05 10:34:08,702 INFO TaskExecutor FarmEchoTask:start walk_to_treasure\n"
                "2026-10-05 10:34:38,744 INFO TaskExecutor FarmEchoTask:周本领奖：这一步没做成 WaitFailedException()\n"
                "2026-10-05 10:35:53,304 INFO TaskExecutor TacetTask:enter combat None\n")
        got = okww_checks(oct5, expect_nest=False, expect_daily=False, expect_stamina=False)
        check("10-05：说进了本一次没打，不说「打了没领」",
              [(c.label, c.detail) for c in got], [("周本", "进了本，但日志里没有开打的记录：一次没打")])
        check("10-05：别的任务的 enter combat 不算周本开打",
              "周本领奖改动在跑（打完按 F 领奖）" in bad_labels(patch_effect_checks(oct5)), False)

        print("\n[只刷落渊南丘：2026-09-13 真实日志——四个点位全进了，四天没人发现]")
        text5 = ("2026-09-13 09:22:07,105 INFO TaskExecutor NightmareNestTask:Box(name='已击败残象：0/41', x=889, y=373, width=195, height=30, confidence=100) is not complete\n"
                 "2026-09-13 09:22:07,306 INFO TaskExecutor NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2\n"
                 "2026-09-13 09:24:38,554 INFO TaskExecutor NightmareNestTask:left_click 已击败残象：0/48 (1729, 567) after_sleep 2\n"
                 "2026-09-13 09:26:59,672 INFO TaskExecutor NightmareNestTask:left_click 已击败残象：0/48 (1729, 722) after_sleep 2\n"
                 "2026-09-13 09:30:25,602 INFO TaskExecutor NightmareNestTask:left_click 已击败残象：0/24 (1729, 868) after_sleep 2\n"
                 "2026-09-13 09:31:27,063 INFO TaskExecutor NightmareNestTask:nightmare nest: combat detected after pickup\n"
                 "DailyTask:Daily Task Completed\n"
                 "ForgeryTask:used all stamina\n")
        got5 = okww_checks(text5, expect_nest=True, only_nest="落渊南丘")
        check("没有「只刷」那一行 = 过滤没生效", "残象聚落只刷指定点位（过滤生效）" in bad_labels(got5), True)
        check("三种计数上限 = 进了别的点位", "残象聚落没进别的点位" in bad_labels(got5), True)
        check("细节点名 41、48、24", any("41、48、24" in c.detail for c in got5 if not c.ok), True)
        check("旧判据仍把它当「有战斗记录」——所以以前是绿的", "残象聚落" not in bad_labels(got5), True)

        print("\n[只刷落渊南丘：2026-09-09 09:21 真实日志——只进了 0/41，正确]")
        text6 = ("NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）\n"
                 "2026-09-09 09:21:24 NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2\n"
                 "2026-09-09 09:22:21 NightmareNestTask:left_click 已击败残象：0/41 (1729, 347) after_sleep 2\n"
                 "2026-09-09 09:26:01 NightmareNestTask:nightmare nest: 指定点位都已打满，跳过\n"
                 "DailyTask:Daily Task Completed\n"
                 "ForgeryTask:used all stamina\n")
        got6 = okww_checks(text6, expect_nest=True, only_nest="落渊南丘")
        check("过滤生效且只进一个点位", bad_labels(got6), [])
        check("没配过滤就不加这两条", [c.label for c in okww_checks(text6, expect_nest=True) if "指定点位" in c.label or "别的点位" in c.label], [])

    main()


def _part_outcome_nest_words():
    """The nest-filter check says what the log shows, not what might have happened."""

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import outcome

    DAY_1005 = """\
2026-10-05 10:35:06,057 INFO TaskExecutor NightmareNestTask:opened gray_book_boss
2026-10-05 10:35:14,196 INFO TaskExecutor NightmareNestTask:Box(name='已击败残象：0/48', x=889, y=374, width=198, height=30, confidence=100) is not complete
2026-10-05 10:35:14,398 INFO TaskExecutor NightmareNestTask:left_click 已击败残象：0/48 (1729, 348) after_sleep 2
2026-10-05 10:35:18,183 INFO TaskExecutor NightmareNestTask:nightmare nest unreachable, skip this run: go_nest:48:18
"""

    print("\n[10-05 那种：没过滤、点了一个没传送过去]")
    c = outcome.nest_filter_checks(DAY_1005, "落渊南丘")[0]
    check("判过滤没生效", c.ok, False)
    check("不再说「刷了全部」", "刷了全部" in c.detail, False)
    check("说了一个都没刷", "一个都没刷" in c.detail)

    print("\n[没过滤、一个都没进]")
    c = outcome.nest_filter_checks("NightmareNestTask:opened gray_book_boss\n", "落渊南丘")[0]
    check("说了一个点位都没进", "一个点位都没进" in c.detail)

    print("\n[过滤改动没装上、这一轮没刷：算没干成、要进群（10-12 他「有错，但是不报，那是比报错更严重的事情」）]")
    text = ("NightmareNestTask:opened gray_book_boss\n"
            "NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）\n"
            "NightmareNestTask:nightmare nest: 只刷指定点位的改动没装上，这一轮不刷巢穴\n")
    nest = [x for x in outcome.okww_checks(text, expect_nest=True, expect_daily=False, expect_stamina=False,
                                           only_nest="落渊南丘") if x.label.startswith("残象聚落")]
    nest = [x for x in nest if x.label == "残象聚落"]
    check("巢穴判没干成", [x.ok for x in nest], [False])
    check("说清是补丁没贴上", "补丁没贴上" in nest[0].detail, True)

    print("\n[10-05 整段：点了 0/48、传送不过去、F2 打不开、任务崩了——一次没打，不许算干成]")
    CRASH = DAY_1005 + """\
2026-10-05 10:35:22,335 ERROR TaskExecutor NightmareNestTask:can't find gray_book_boss, make sure f2 is the hotkey for book
2026-10-05 10:35:22,358 ERROR TaskExecutor DailyTask:NightmareNestTask Failed Traceback (most recent call last):
"""
    got = outcome.okww_checks(CRASH, expect_nest=True, expect_daily=False, expect_stamina=False, only_nest="落渊南丘")
    by = {x.label: x for x in got}
    check("「is not complete」那行不算打过", bool(outcome._NEST_ENGAGED.search(CRASH)), False)
    check("残象聚落判没干成", by["残象聚落"].ok, False)
    check("说传送不过去、一次没打", "一次没打" in by["残象聚落"].detail)
    check("没打就不写「没进别的点位」", "残象聚落没进别的点位" in by, False)
    from ark_relay.features import outcome as collector_okww
    check("错误翻译不再说「打了」", "打了" in collector_okww._okww_error(
        "DailyTask:NightmareNestTask Failed Traceback (most recent call last):\nException: boom"), False)

    print("\n[真打过的早上（10-03 那种）：进了战斗才算干成]")
    FOUGHT = DAY_1005.replace("nightmare nest unreachable, skip this run: go_nest:48:18",
                              "enter combat None")
    got = outcome.okww_checks(FOUGHT, expect_nest=True, expect_daily=False, expect_stamina=False)
    check("有 enter combat 就算干成", [x.ok for x in got if x.label == "残象聚落"], [True])

    print("\n[只刷两个（他 10-12 11:2x：梦枢天罗、落渊南丘）：进两个点位不算进了别的]")
    TWO = ("NightmareNestTask:nightmare nest: 只刷 ['梦枢天罗', '落渊南丘']（设置来自母本）\n"
           "NightmareNestTask:left_click 已击败残象：0/48 (1729, 348) after_sleep 2\n"
           "NightmareNestTask:enter combat None\n"
           "NightmareNestTask:left_click 已击败残象：0/41 (1729, 420) after_sleep 2\n"
           "NightmareNestTask:enter combat None\n")
    got = {x.label: x.ok for x in outcome.nest_filter_checks(TWO, "梦枢天罗,落渊南丘")}
    check("两个点位：没进别的点位", got.get("残象聚落没进别的点位"), True)
    got = {x.label: x.ok for x in outcome.nest_filter_checks(TWO, "落渊南丘")}
    check("设置只一个却进了两个：照旧判进了别的", got.get("残象聚落没进别的点位"), False)
    THREE = TWO + "NightmareNestTask:left_click 已击败残象：0/45 (1729, 500) after_sleep 2\n"
    got = {x.label: x.ok for x in outcome.nest_filter_checks(THREE, "梦枢天罗，落渊南丘")}
    check("设置两个却进了三个：判进了别的", got.get("残象聚落没进别的点位"), False)

    from ark_relay.core import mastercfg as mastercfg_okww
    check("他定的两个", list(mastercfg_okww.ONLY_NESTS), ["梦枢天罗", "落渊南丘"])
    check("全角逗号也认", mastercfg_okww.nest_names(" 梦枢天罗，落渊南丘 "), ["梦枢天罗", "落渊南丘"])

    print("\n[日常早做完的第二趟（10-12 11:41 补跑）：周本停下照样判没干成]")
    SECOND = ("DailyTask:info_set total daily points 160\n"
              "FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
              "FarmEchoTask:teleport_to_boss prepared as Weekly Challenge\n"
              "FarmEchoTask:周本领奖：认出弹窗，点确认。读到 ...\n"
              "FarmEchoTask:周本领奖：已点确认\n"
              "FarmEchoTask:" + outcome.FAILED_MARK + "周本领奖：点了确认后没等到结算页（没有「退出副本」），停下不按 ESC。\n"
              "NightmareNestTask:nightmare nest: 只刷 ['梦枢天罗', '落渊南丘']（设置来自母本）\n"
              "NightmareNestTask:left_click 已击败残象：0/48 (1729, 348) after_sleep 2\n"
              "NightmareNestTask:enter combat None\n"
              "NightmareNestTask:nightmare nest: 指定点位都已打满，跳过（截图 nest_all_full）\n"
              "DailyTask:Daily Task Completed\n")
    got = {x.label: x for x in outcome.okww_checks(SECOND, expect_nest=True, only_nest="梦枢天罗,落渊南丘")}
    check("认出日常早做完", got["今日日常此前已完成，本轮仅领奖"].ok)
    check("周本判没干成", got["周本领到了奖励"].ok, False)
    check("说了停在哪", "没等到结算页" in got["周本领到了奖励"].detail)
    nest = [x.ok for k, x in got.items() if k.startswith("残象聚落") and "点位" not in k]
    check("聚落照判（跑了就判）", nest, [True])
    check("不要刷体力那项", "刷体力" in got, False)
    got = {x.label for x in outcome.okww_checks(SECOND.replace("NightmareNestTask", "X"), expect_nest=True)}
    check("这趟没跑聚落就不判聚落", [k for k in got if k.startswith("残象聚落") and "点位" not in k], [])

    # Since a8cc86b6 the overlay no longer ends the run as failed here: it logs the line below
    # (okww_files/ark_overrides.tasks.py, weekly claim) and hands the lap back to upstream.
    # Same run with today's line: still no confirmed claim, so still not claimed.
    SECOND_NOW = SECOND.replace(
        "FarmEchoTask:" + outcome.FAILED_MARK + "周本领奖：点了确认后没等到结算页（没有「退出副本」），停下不按 ESC。\n",
        "FarmEchoTask:周本领奖：点了确认后没看到「退出副本」，交回上游。整屏读到 挑战成功\n")
    check("新句子样本确实换掉了旧句子", outcome.FAILED_MARK in SECOND_NOW, False)
    got = {x.label: x for x in outcome.okww_checks(SECOND_NOW, expect_nest=True, only_nest="梦枢天罗,落渊南丘")}
    check("新句子：认出日常早做完", got["今日日常此前已完成，本轮仅领奖"].ok)
    check("新句子：周本照样判没领到", got["周本领到了奖励"].ok, False)

    print("\n[兜底：日志有「这一趟按失败结束」或「附加任务出错」，不管别的分支怎么判，这趟都不算干成]")
    WHY = "周本领奖：点了确认后没等到结算页（没有「退出副本」），停下不按 ESC。"
    TAIL = ("2026-10-12 07:45:20,100 INFO TaskExecutor DailyTask:info_set total daily points 160\n"
            "2026-10-12 07:58:51,996 INFO TaskExecutor DailyTask:Daily Task Completed\n")
    REAL_1141 = ("2026-10-12 07:44:30,000 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
                 "2026-10-12 07:44:40,000 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as Weekly Challenge\n"
                 "2026-10-12 07:44:52,609 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认\n"
                 "2026-10-12 07:45:02,499 ERROR TaskExecutor FarmEchoTask:" + outcome.FAILED_MARK + WHY + "\n"
                 "2026-10-12 07:45:02,600 ERROR TaskExecutor DailyTask:附加任务出错，不拖垮当趟日常: " + WHY
                 + " Traceback (most recent call last):\n"
                 '  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\src\\task\\DailyTask.py", line 1, in run\n'
                 + TAIL)
    got = outcome.okww_checks(REAL_1141, expect_nest=False)
    bad = [x for x in got if not x.ok]
    check("11:41 那种：判没干成", bool(bad))
    check("11:41 那种：同一个原因只报一条（周本那项已经说了）", len(bad), 1)
    check("11:41 那种：说了停在哪", "没等到结算页" in bad[0].detail if bad else False)

    # The shape no other branch catches: dailies done, the additional task raised before the
    # weekly book was opened (no 「Teleport to Boss Weekly Challenge」), so origin/main judged
    # every item green and the run was booked silently.
    ADD_ONLY = ("2026-10-05 10:34:52,359 ERROR TaskExecutor DailyTask:附加任务出错，不拖垮当趟日常:  "
                "Traceback (most recent call last):\n" + TAIL)
    got = outcome.okww_checks(ADD_ONLY, expect_nest=False)
    check("只有附加任务出错：判没干成", [x.ok for x in got if x.label == "附加任务出错"], [False])
    check("只有附加任务出错：会推送", outcome.summarize(got, "OK-WW") is not None)
    check("没写原因就照实说", [x.detail for x in got if x.label == "附加任务出错"], ["日志里只有这一句，没写原因"])

    REASON = ("2026-09-21 10:21:00,184 ERROR TaskExecutor DailyTask:附加任务出错，不拖垮当趟日常: "
              "Teleport to boss failed Traceback (most recent call last):\n" + TAIL)
    got = outcome.okww_checks(REASON, expect_nest=False)
    check("原因去掉 Traceback 尾巴", [x.detail for x in got if x.label == "附加任务出错"], ["Teleport to boss failed"])

    ENDED = ("2026-10-12 07:50:00,000 ERROR TaskExecutor FarmEchoTask:" + outcome.FAILED_MARK
             + "连续 3 次失败，退出本次任务，不再重试\n" + TAIL)
    got = outcome.okww_checks(ENDED, expect_nest=False)
    check("刷声骸按失败结束（不是周本）：判没干成",
          [(x.ok, x.detail) for x in got if x.label == "这一趟按失败结束"],
          [(False, "连续 3 次失败，退出本次任务，不再重试")])
    check("干净的日常早做完：照旧全绿", outcome.summarize(outcome.okww_checks(TAIL, expect_nest=False), "OK-WW"), None)


def _part_gamelog_errors():
    import logging
    import os
    import types
    from datetime import datetime

    TMP = tmpdir()
    os.environ.update(ARK_STATE_DIR=str(TMP / "state"), ARK_HISTORY_DIR=str(TMP / "history"), ARK_AUTOMAS_DIR="")
    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))
    from ark_relay.core import statestore as techlog, texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features import errwatch
    from ark_relay.features import outcome as ge

    # One real line per known shape, as the machine wrote it.
    SAMPLES = {
        "MAA": [
            "[2026-09-27 09:00:55.117][ERR][AutoStart]              <2> Failed to set startup: No value exists with that name.",
            "[2026-10-02 21:46:55.570][ERR][TaskQueueViewModel]     <2> 识别错误, 已返回",
            "[2026-10-29 21:34:09.756][ERR][GameDataReportService]  <2> Error during HTTP POST request to https://penguin-stats.io/PenguinStats/api/v2/report",
        ],
        "MaaEnd": [
            "[2026-10-21 09:55:08.002] [2026-10-21 09:55:07.977][ERR][Px6540][Tx4086][navigation_state_machine.cpp][L2696][mapnavigator::NavigationStateMachine::FailNavigation] Off-route with no route progress past the wedge timeout; terminating so the pipeline can retry. [current_distance=9.953856] [yaw_error=59.709557] [stalled_ms=0]",
            "[2026-09-27 09:33:23.006][ERR][Px23408][Tx41825][TemplateMatcher.cpp][L54][MaaNS::VisionNS::TemplateMatcher::template_match] __CancelButtonType1Icon templ size is too large [image=[258,20,16]] [templ=[29,29,16]]",
            "[2026-09-27 09:43:52.582][ERR][Px23408][Tx41825][Vision/VisionUtils.hpp][L349][MaaNS::VisionNS::correct_roi] roi is out of range [image.size()=[1280,720]] [res=[67,722,143,40]]",
            "[2026-09-27 09:44:13.860][ERR][Px23408][Tx41825][RuntimeCache.cpp][L66][MaaNS::RuntimeCache::set_reco_detail] uid is invalid ",
            "[2026-09-27 09:33:24.290][ERR][Px23408][Tx41825][ActionHelper.cpp][L30][MaaNS::TaskNS::ActionHelper::wait_freezes] failed to get target rect for wait_freezes [noti_ctx.name=__SceneImageCheckFinishExitSuccess]",
            "[2026-09-28 11:09:53.122][ERR][Px9932][Tx43027][PipelineTask.cpp][L292][MaaNS::TaskNS::PipelineTask::recognize_list] get_pipeline_data failed, node not exist [node={\"anchor\":true,\"jump_back\":true,\"name\":\"__ScenePrivateMapSwipeToStep0Anchor\"}]",
        ],
        "OK-WW": [
            "2026-09-27 09:17:33,335 ERROR ok.core.start_controller start_controller:Game window is not connected BitBlt_True_1920x1080",
            "2026-11-22 09:25:05,233 ERROR ok.core.start_controller bitblt_utils:capture_by_bitblt invalid params: hwnd=0, w=1920, h=1080",
            "2026-09-27 09:17:33,339 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮   is not connected, please select the game window.",
            "2026-09-29 09:20:35,119 ERROR ok.core.start_controller start_controller:waiting for game to start error Selected capture method is not supported by the game or your system!",
            "2026-09-27 09:18:09,708 ERROR TaskExecutor bitblt_utils:capture_by_bitblt exception: BitBlt failed",
            "2026-10-05 09:41:00,433 ERROR TaskExecutor post_message:PostMessage error 590386: (1400, 'PostMessage', '无效的窗口句柄。')",
            "2026-09-27 09:21:24,985 ERROR TaskExecutor CombatCheck:target_enemy failed, try recheck break out of combat",
            "2026-09-27 09:21:24,986 ERROR TaskExecutor BaseCombatTask:combat check not in combat",
            "2026-09-30 18:01:49,174 ERROR TaskExecutor Denia:clicked liberation but no effect",
            "2026-11-16 09:58:53,023 ERROR TaskExecutor BaseCombatTask:too long a liberation, the boss was killed by the liberation",
            "2026-10-10 09:06:42,695 ERROR TaskExecutor BaseCombatTask:not in_team while switching",
            "2026-10-15 09:20:31,117 ERROR ok.core.start_controller DeviceManager:refresh error Traceback (most recent call last):",
            "2026-10-15 09:20:31,127 ERROR ok.core.start_controller start_controller:check_device_error exception: 'NoneType' object is not subscriptable Traceback (most recent call last):",
            "2026-10-15 09:20:31,127 ERROR ok.core.start_controller start_controller:waiting for game to start error 'NoneType' object is not subscriptable",
        ],
    }
    ROUND_1015 = """\
2026-10-15 09:20:31,117 ERROR ok.core.start_controller DeviceManager:refresh error Traceback (most recent call last):
  File "D:\\ark\\okww\\data\\apps\\ok-ww\\working\\ok\\util\\window.py", line 343, in is_match
pywintypes.error: (1400, 'GetClassName', '无效的窗口句柄。')
2026-10-15 09:20:31,118 INFO ok.core.start_controller start_controller:start_device: None
2026-10-15 09:20:31,127 ERROR ok.core.start_controller start_controller:check_device_error exception: 'NoneType' object is not subscriptable Traceback (most recent call last):
TypeError: 'NoneType' object is not subscriptable
2026-10-15 09:20:31,127 ERROR ok.core.start_controller start_controller:waiting for game to start error 'NoneType' object is not subscriptable 
2026-10-15 09:20:33,135 ERROR ok.core.start_controller start_controller:waiting for game to start error Selected capture method is not supported by the game or your system! 
2026-10-15 09:22:59,239 ERROR TaskExecutor CombatCheck:target_enemy failed, try recheck break out of combat 
2026-10-15 09:22:59,239 ERROR TaskExecutor BaseCombatTask:combat check not in combat 
2026-10-15 09:25:19,909 ERROR TaskExecutor Qingxiao:clicked liberation but no effect 
2026-10-15 09:31:40,834 INFO TaskExecutor DailyTask:Daily Task Completed
"""
    # Real failures inside rounds booked as a success: never on the list.
    MUST_PUSH = {
        "OK-WW": [
            "2026-09-29 09:28:53,798 ERROR TaskExecutor DailyTask:can not battle pass, maybe ended",
            "2026-10-05 10:34:50,807 ERROR TaskExecutor FarmEchoTask:farm 4c error, try handle monthly card Traceback (most recent call last):",
            "2026-10-05 10:35:22,335 ERROR TaskExecutor NightmareNestTask:can't find gray_book_boss, make sure f2 is the hotkey for book",
            "2026-10-05 10:34:52,359 ERROR TaskExecutor DailyTask:附加任务出错，不拖垮当趟日常:  Traceback (most recent call last):",
            "2026-10-15 09:25:00,000 ERROR TaskExecutor DeviceManager:refresh error Traceback (most recent call last):",
            "2026-10-15 09:20:31,127 ERROR ok.core.start_controller start_controller:waiting for game to start error 'NoneType' object has no attribute 'hwnd'",
            "2026-11-22 09:30:00,000 ERROR TaskExecutor bitblt_utils:capture_by_bitblt invalid params: hwnd=0, w=1920, h=1080",
            "2026-11-22 09:25:05,233 ERROR ok.core.start_controller bitblt_utils:capture_by_bitblt invalid params: hwnd=1312226, w=0, h=1080",
        ],
        "MAA": [
            "[2026-10-02 23:40:26.537][ERR][VersionUpdateDialogViewModel] <2> mirrorc failed",
            # Made up from the real penguin-stats.io line: the backup domain failing too is not recovered.
            "[2026-10-29 21:34:09.813][ERR][GameDataReportService]  <2> Error during HTTP POST request to https://penguin-stats.cn/PenguinStats/api/v2/report",
        ],
        "MaaEnd": [
            # Made up from the real anchor line: a node that does not exist without being an anchor.
            "[2026-09-28 11:09:53.122][ERR][Px9932][Tx43027][PipelineTask.cpp][L292][MaaNS::TaskNS::PipelineTask::recognize_list] get_pipeline_data failed, node not exist [node={\"jump_back\":true,\"name\":\"SomeNodeThatIsGone\"}]",
        ],
    }
    # Entries that may say not-a-fault (line-number free: matched by script and a sample they match).
    NOT_A_FAULT = {
        ("OK-WW", "too long a liberation"):
            "OK-WW leaves a fight when a liberation plays past 7 s, the target having died in it (src/char/BaseChar.py:665); "
        "the task's own next step (the claim) checks the result - 11-16 09:59:13 the weekly boss claimed (ledger #175)",
        ("MAA", "Failed to set startup: No value exists with that name."):
            "MAA elevated removing a start-with-Windows value that is not there (BOARD 未进群报错-MAA-MaaEnd-1010)",
        ("MaaEnd", "templ size is too large"):
            "MaaFramework: a template larger than its search region counts as not found; the pipeline goes on",
        ("MaaEnd", "roi is out of range"):
            "MaaFramework drops a search region that starts past the screen (VisionUtils.hpp L347-350)",
        ("MaaEnd", "uid is invalid"):
            "MaaFramework refuses to store the detail of a recognition that returned early (RuntimeCache.cpp L63-67)",
        ("MaaEnd", "failed to get target rect for wait_freezes"):
            "MaaFramework skips the freeze wait of an inverted node (ActionHelper.cpp L38-42, TaskBase.cpp L202-211)",
        ("MaaEnd", '"anchor":true'):
            "MaaFramework skips an [Anchor] candidate whose anchor is not set, by design (PipelineProtocol L1478-1479)",
    }
    UNKNOWN = ("not known", "unknown", "unexplained", "not found yet", "tbd", "to be checked", "不明", "待查", "没查清")

    print("[the registry: shape, why, source, a real sample per entry]")
    entries, problems = ge.parse(ge.REGISTRY.read_text(encoding="utf-8"))
    check("every line parses", problems, [])
    check("it has entries for all three scripts", {e.script for e in entries}, {"MAA", "MaaEnd", "OK-WW"})
    for e in entries:
        tag = f"line {e.line_no} {e.script}"
        check(f"{tag}: a why of some length", len(e.why) >= 30, True)
        check(f"{tag}: the why does not call the cause unknown", [w for w in UNKNOWN if w in e.why.lower()], [])
        check(f"{tag}: a source", len(e.source) >= 10, True)
        hits = [s for s in SAMPLES.get(e.script, []) if e.pattern.search(s)]
        check(f"{tag}: matches a real sample", bool(hits), True)
        if e.kind == "not-a-fault":
            ok = any(k[0] == e.script and any(k[1] in s for s in hits) for k in NOT_A_FAULT)
            check(f"{tag}: not-a-fault is on NOT_A_FAULT", ok, True)
    for script, lines in SAMPLES.items():
        for s in lines:
            check(f"sample is listed: {s[:70]}", ge.known(script, s) is not None, True)
    for script, lines in MUST_PUSH.items():
        for s in lines:
            check(f"real failure is not listed: {s[:70]}", ge.known(script, s), None)

    print("[a source on this Mac's BOARD exists (2026-10-12: nine OK-WW lines cited a file that had moved)]")
    BOARD = Path.home() / "Money" / "styl-work" / "BOARD"
    if BOARD.is_dir():
        for e in entries:
            if e.source.startswith("~/"):
                where = e.source.split(" (", 1)[0]
                check(f"line {e.line_no}: its source {where} exists", Path(where).expanduser().is_file(), True)

    print("[the 10-15 09:20 round (alarm f7a4bb6a): every ERROR line is listed, as recovered]")
    check("nothing unlisted in the whole round", ge.unregistered("OK-WW", ROUND_1015), [])
    check("the start-wait kinds count as recovered, not not-a-fault",
          sorted({e.kind for e, _l, _n in ge.recovered_kinds("OK-WW", ROUND_1015)}), ["recovered"])

    print("[the parser refuses the bad shapes]")
    bad = ("MAA | x | verdict: fine - it is ok | src\n"
       "MAA | ( | verdict: recovered - a long enough reason for a bad regex | src\n"
       "Foo | x | verdict: recovered - a long enough reason for a bad script | src\n"
       "MAA | x | recovered - no verdict: prefix here at all, so it is refused | src\n"
       "MAA | x | verdict: recovered - three parts only\n")
    _, probs = ge.parse(bad)
    check("five bad lines, five problems", len(probs), 5)

    print("[unregistered: listed lines drop out, the rest folded by shape]")
    text = "\n".join(SAMPLES["OK-WW"] + MUST_PUSH["OK-WW"][:1] * 3 + ["2026-10-11 09:00:00,000 INFO fine"])
    got = ge.unregistered("OK-WW", text)
    check("one shape left, seen three times", [(("battle pass" in line), n) for line, n in got], [(True, 3)])
    check("nothing for a log with listed lines only", ge.unregistered("OK-WW", "\n".join(SAMPLES["OK-WW"])), [])
    check("an unknown script reads nothing", ge.unregistered("X", "\n".join(MUST_PUSH["OK-WW"])), [])

    print("[check_round: one alarm per round, plain words, raw lines to the technical log]")

    ARK = logging.getLogger(errwatch.ARK)
    h = _Warnings()
    ARK.addHandler(h)
    try:
        sd = TMP / "r" / "state"
        sd.mkdir(parents=True)
        logp = TMP / "r" / "OK-WW-09-12-00.log"
        logp.write_text(text, encoding="utf-8")
        started = datetime(2026, 10, 11, 9, 12, tzinfo=SERVER_TZ)
        rec = types.SimpleNamespace(script="OK-WW", run_id="2026-10-11/wuwa/OK-WW-09-12-00", log_path=logp,
                                    started=started)
        eng = types.SimpleNamespace(cfg=types.SimpleNamespace(state_dir=str(sd)))
        found = ge.check_round(eng, rec)
        check("returns the unlisted shape", len(found), 1)
        pushed = [r for r in h.records if not getattr(r, errwatch.RECOVERED, False)]
        check("one pushed WARNING (the listed recovered lines are the round's other, recovered one)",
              (len(pushed), len(h.records)), (1, 2))
        alarm = getattr(pushed[0], errwatch.ALARM, None) if pushed else None
        check("with its own title and body", alarm, (texts.gamelog_unknown_errors("鸣潮"),
                                                    texts.gamelog_unknown_errors_body("鸣潮", "09:12", 1)))
        check("title and body read as plain words", (texts.plain(alarm[0]), texts.plain(alarm[1])) if alarm else None,
              ([], []))
        red = techlog.unhandled(techlog.path_for("2026-10-11", sd).read_text(encoding="utf-8"))
        check("one red item quoting the raw line", [("can not battle pass" in t, rec.run_id in t) for _, t in red],
              [(True, True)])
        h.records.clear()
        logp.write_text("\n".join(SAMPLES["OK-WW"]), encoding="utf-8")
        check("a log with listed recovered lines only: nothing unlisted", ge.check_round(eng, rec), [])
        check("... but one WARNING marked recovered for the round, not pushed",
              [(getattr(r, errwatch.RECOVERED, False), getattr(r, errwatch.ALARM, None)) for r in h.records],
              [(True, None)])
        check("... naming the run and each recovered kind once",
              bool(h.records) and rec.run_id in h.records[0].getMessage()
              and h.records[0].getMessage().count("combat check not in combat") == 1, True)
        check("... its first line (what the daily report quotes) is plain words, the same every run",
              [texts.plain(errwatch.first_line(r)) for r in h.records], [[]])
        h.records.clear()
        maa = types.SimpleNamespace(script="MAA", run_id="2026-10-11/ak/MAA-09-00-00", log_path=TMP / "r" / "gui.log",
                                    started=started)
        maa.log_path.write_text(SAMPLES["MAA"][0], encoding="utf-8")
        check("a log with listed not-a-fault lines only: nothing at all", (ge.check_round(eng, maa), h.records), ([], []))
        h.records.clear()
        rec.log_path = TMP / "r" / "missing.log"
        ge.check_round(eng, rec)
        check("an unreadable log is said, never taken as clean", [("日志读不了" in r.getMessage()) for r in h.records],
              [True])
    finally:
        ARK.removeHandler(h)

    print("[handle's success path calls it]")
    src = (RELAY / "ark_relay" / "features" / "handle.py").read_text(encoding="utf-8")
    body = src[src.index("def _handle_success"):src.index("def _retry_healed")]
    check("_handle_success calls gamelog_errors.check_round", "gamelog_errors.check_round(eng, rec)" in body, True)
    check("after the outcome check's early return", body.index("gamelog_errors.check_round") > body.index("_verify_outcome"),
          True)

    print("[OK-WW v3.7.14 zh_CN framework lines are read as the listed English (ledger #136, 11-04 09:21)]")
    ZH_1104 = ("2026-11-04 09:21:32,965 ERROR ok.core.start_controller start_controller:waiting for game to start error "
           "当前游戏或模拟器不支持选择的截图方式!")
    check("the 11-04 zh capture-method line is not unregistered", ge.unregistered("OK-WW", ZH_1104), [])
    check("it counts as the recovered capture-method entry",
          [e.pattern.pattern for e, _, _ in ge.recovered_kinds("OK-WW", ZH_1104)] ==
          [ge.known("OK-WW", "2026-10-10 09:20:00,000 ERROR ok.core.start_controller start_controller:waiting for game "
                "to start error Selected capture method is not supported by the game or your system!").pattern.pattern],
          True)

    print("[OK-WW v3.8.9 start-wait BitBlt hwnd=0 and zh_CN window-not-connected lines (ledger #189, 11-22 09:25)]")
    ROUND_1122 = "\n".join([
        "2026-11-22 09:25:05,233 ERROR ok.core.start_controller bitblt_utils:capture_by_bitblt invalid params: hwnd=0, w=1920, h=1080",
        "2026-11-22 09:25:05,234 ERROR ok.core.start_controller start_controller:Game window is not connected BitBlt_True_0x0",
        "2026-11-22 09:25:05,235 ERROR ok.core.start_controller start_controller:waiting for game to start error 鸣潮  未连接，请选择正确的游戏窗口。",
    ])
    check("11-22 #189: all three start-wait lines are registered", ge.unregistered("OK-WW", ROUND_1122), [])
    check("11-22 #189: all three count as recovered",
          [(e.kind, n) for e, _, n in ge.recovered_kinds("OK-WW", ROUND_1122)],
          [("recovered", 1), ("recovered", 1), ("recovered", 1)])
    ZH_1122 = ("2026-11-22 09:25:05,235 ERROR ok.core.start_controller start_controller:waiting for game to start error "
               "鸣潮  未连接，请选择正确的游戏窗口。")
    check("11-22 #189: zh not-connected maps to the listed English not-connected entry",
          [e.pattern.pattern for e, _, _ in ge.recovered_kinds("OK-WW", ZH_1122)] ==
          [ge.known("OK-WW", "2026-09-27 09:17:33,339 ERROR ok.core.start_controller start_controller:waiting for game "
                "to start error 鸣潮   is not connected, please select the game window.").pattern.pattern],
          True)
    check("a real failure in zh still reaches the group", len(ge.unregistered(
        "OK-WW", "2026-11-04 09:30:00,000 ERROR TaskExecutor 无法领取先约电台奖励")), 1)


def _part_m6_counts():
    """M6 (2026-09-23): run counts and sanity spent against the real 09-20..22 logs."""
    import sys, pathlib, tempfile
    from datetime import datetime, timedelta
    from unittest import mock
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from ark_relay.features import collector_maa, collector_maaend
    from ark_relay.core import plan
    from ark_relay.features import annihilation
    from ark_relay.core.config import SERVER_TZ

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
        check("方舟 09-20 早 次数", r.get("run_times"), 19)
        check("方舟 09-20 早 理智", r.get("sanity_spent"), 114)
        check("方舟 09-20 早 酯原料", r.get("drop_statistics", {}).get("酯原料"), 2)
        check("方舟 09-20 早 龙门币", r.get("drop_statistics", {}).get("龙门币"), 1368)
        f.write_text(maa + "[2026-09-20 21:36:28.217][INF][TaskQueueViewModel]     <2> 开始行动 20~21 次, -12理智\n", encoding="utf-8")
        check("方舟 单趟编号", collector_maa.parse_maa_log(f).get("run_times"), 21)

    end = "\n".join([
        "[2026-09-22 09:47:29.620] 任务开始: 🎱基质刷取",
        *[f"[2026-09-22 09:4{i}:00.000] 当前理智 {v}/360" for i, v in enumerate([237, 158, 78, 38, 38, 39])],
        *["[2026-09-22 09:50:42.245] ✅已完成一次基质刷取"] * 5,
        "[2026-09-22 09:58:39.769] 任务完成: 🎱基质刷取",
    ])
    check("终末地 09-22 理智", collector_maaend._maaend_farm(end).get("maaend_sanity_spent"), 400)

    ov = {
        "AutoCollectValleyIV": {"type": "switch", "value": True},
        "AutoCollectValleyIVRareRoutes": {"caseNames": ["Route4", "Route5", "Route6", "Route13", "Route14"]},
        "AutoCollectValleyIVCommonRoutes": {"caseNames": []},
        "AutoCollectWuling": {"type": "switch", "value": True},
        "AutoCollectWulingRareRoutes": {"caseNames": [f"Route{i}" for i in (1, 2, 3, 7, 8, 9, 10, 11, 12, 15, 16, 17)]},
        "AutoCollectSchedule": {"caseNames": ["AutoCollectScheduleMonday"]},
    }
    check("采集路线 新两键", plan._collect_route_count(ov), 17)
    ov["AutoCollectWuling"]["value"] = False
    check("采集路线 关掉的区不算", plan._collect_route_count(ov), 5)
    check("采集路线 旧键仍认", plan._collect_route_count({"AutoCollectRoutes": {"caseNames": ["a", "b"]}}), 2)

    sun = datetime(2026, 9, 20, 21, 0, tzinfo=SERVER_TZ)
    done_this_week = {"Info": {"Annihilation": "Annihilation"},
                      "Data": {"AnnihilationCompletedWeek": annihilation.week_key(sun)}}
    with mock.patch.object(annihilation, "_maa_user", lambda d: done_this_week):
        with mock.patch.object(plan, "_tomorrow", lambda: sun + timedelta(days=1)):
            check("周日排周一 剿灭照打（新的一周）", plan._annihilation_done_tomorrow(pathlib.Path("automas")), False)
        with mock.patch.object(plan, "_tomorrow", lambda: sun - timedelta(days=2)):
            check("周五排周六 本周已打满", plan._annihilation_done_tomorrow(pathlib.Path("automas")), True)


def _part_m6_okww():
    """M6 OK-WW report fixes, replayed on the machine's own logs (slices under
fixtures/m6-okww, cut from the 09-21 and 09-22 runs pulled back on 09-23).
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features import outcome as c, outcome as o

    FX = fx_dir(Path(__file__), "fixtures") / "m6-okww"

    r = c.parse_okww_log(FX / "0921-weekly.log")
    t = (FX / "0921-weekly.log").read_text(encoding="utf-8")
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


if __name__ == "__main__":
    sys.exit(run_parts([_part_activity_topup, _part_attempts_streak, _part_claim_no_claim_gate, _part_drops, _part_episodes, _part_flush_waits_own_script, _part_gathering_route_node_failed, _part_healthcheck_annihilation, _part_kuro_error_code, _part_logfile_silent, _part_logslice_new_year, _part_main_logfile_silent, _part_monthcard, _part_nofarm_visible, _part_refresh_raw_unread, _part_revive_gates, _part_scan_skips_seen, _part_setup_tasks_verify, _part_tape, _part_transitional, _part_undone_fallback_full, _part_verdict_no_history_log, _part_weekly_three_claims, _part_maa_checks, _part_maa_closedown_postaction, _part_maa_config_rejected, _part_maa_start_watchdog, _part_maa_unreachable_cleared_notes, _part_maa_window_overlap, _part_maa_write_master_first, _part_maa_unreachable, _part_outcome_main, _part_outcome_nest_words, _part_gamelog_errors, _part_m6_counts, _part_m6_okww]))
