"""The weekly boss: the count, the cycle, reopening.

One part per former file, each run on its own (tests/_parts.py): test_weeklyboss_count.py, test_weeklyboss_cycle.py, test_weeklyboss_reopen.py.
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


def _part_weeklyboss_count():
    """「任务跑完」不等于「三次领满」。

The weekly reward is claimed after the fight, 60 waveplates per claim (entering is free), so short waveplates mean fewer claims.
2026-08-31 实测：贝币刷取把波片吃到只剩 1 点，第二天早上只回到约 147，
只够领两次。而 on_success 原来只要任务跑完就记「本周已打」并摘掉开关——
第三次就永远丢了，而且不出声。

现在改成读游戏页面上的「本周剩余可收取次数」，归零才记账。

    Formerly test_weeklyboss_count.py.
    """
    import os, sys
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import weeklyboss as W
    from ark_relay.core.config import SERVER_TZ

    TMP = tmpdir()
    LOG = TMP / "ok-ww.log"
    os.environ["ARK_OKWW_LOG"] = str(LOG)
    STATE = TMP / "state"; STATE.mkdir()
    NOW = datetime(2026, 8, 31, 20, 0, tzinfo=SERVER_TZ)


    def gate():
        g = W.WeeklyBossGate(STATE, None)
        g.configure(index=1)
        return g

    def write(*lines):
        LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n[读得出剩余次数]")
    write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：3/3')]")
    check("读到 3", W.remaining_from_log(), 3)
    write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：3/3')]",
          "周本本周剩余次数原文: [Box(text='本周剩余可收取次数：1/3')]")
    check("取最后一条", W.remaining_from_log(), 1)
    write("什么都没有")
    check("读不到就是 None", W.remaining_from_log(), None)

    print("\n[weekly boss position: OK-WW lists 9 (total_weekly_number)]")
    (TMP / "sx").mkdir(); gx = W.WeeklyBossGate(TMP / "sx", None)
    check("9 is accepted", gx.configure(index=9)[0], True)
    check("10 is refused", gx.configure(index=10)[0], False)
    check("20 is refused", gx.configure(index=20)[0], False)
    check("0 is refused", gx.configure(index=0)[0], False)
    check("the refusal names the range", "1~9" in gx.configure(index=10)[1], True)

    print("\n[还剩就不许记账]")
    write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：2/3')]")
    g = gate()
    msg = g.on_success(NOW)
    check("说清楚还剩几次", "还剩 2 次" in msg, True)
    check("没记成已打完", g.settings(NOW)["本周已打"], False)

    print("\n[归零才记账]")
    write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：0/3')]")
    msg = g.on_success(NOW)
    check("记成已打完", g.settings(NOW)["本周已打"], True)
    check("话说得对", "三次已领满" in msg and msg.startswith("鸣潮 · 周本："), True)

    print("\n[读不到时宁可不记]")
    STATE2 = TMP / "s2"; STATE2.mkdir()
    write("什么都没有")
    g2 = W.WeeklyBossGate(STATE2, None); g2.configure(index=1)
    check("不记账", g2.on_success(NOW), "")
    check("开关继续挂着", g2.settings(NOW)["本周已打"], False)

    # docs/SILENT-FAILURES-AUDIT.md weeklyboss.py:263 - this was INFO only, so a broken
    # OCR patch meant the boss was never booked done and nobody was told.
    print("\n[remaining claims unreadable after a won round: a WARNING, not INFO]")
    import logging


    class _Lines(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelname, record.getMessage()))


    _log = _Lines()
    logging.getLogger(W.log.name.rsplit(".", 1)[0]).addHandler(_log)   # every relay logger's parent
    STATE3 = TMP / "s3"; STATE3.mkdir()
    write("什么都没有")
    check("still not booked", W.WeeklyBossGate(STATE3, None).on_success(NOW), "")
    check("one WARNING says the count could not be read",
          len([m for lv, m in _log.lines if lv == "WARNING" and "剩余次数" in m]), 1)

    print("\n[周日留下的 0/3 不算周一这趟（11-08 [D-02]）]")
    (TMP / "sd2").mkdir(); g2 = W.WeeklyBossGate(TMP / "sd2", None); g2.configure(index=1)
    write("2026-08-30 21:00:00,000 INFO 周本本周剩余次数原文: [Box(text='本周剩余可收取次数：0/3')]",
          "2026-08-31 20:00:05,000 INFO 进入周本失败")
    MON = datetime(2026, 8, 31, 20, 0, tzinfo=SERVER_TZ)
    check("周一这趟没读到次数：不记成打满", g2.on_success(MON, since=MON), "")
    write("2026-08-30 21:00:00,000 INFO 周本本周剩余次数原文: [Box(text='本周剩余可收取次数：0/3')]",
          "2026-08-31 20:00:05,000 INFO 周本本周剩余次数原文: [Box(text='本周剩余可收取次数：0/3')]")
    check("周一这趟自己读到 0/3：记成打满", "已领满" in g2.on_success(MON, since=MON), True)

    print("\n[周本序号：True / 乱值不收（11-08 [D-03]）]")
    check("True is refused", gx.configure(index=True)[0], False)
    check("'x' is refused", gx.configure(index="x")[0], False)
    check("'3' is accepted", gx.configure(index="3")[0], True)


def _part_weeklyboss_cycle():
    """周本要和剿灭一个作息：周一 04:00 自动挂回来，领满就摘掉、之后不再检测。

用户 2026-08-31：「我要的是能做到像明日方舟的剿灭那样的，每周一自动刷新
状态，然后优先打周本三次，完事才是普通体力副本。打完副本计入已完成，
并且之后不再检测，周一刷新。」

这里只测「挂上/摘掉/周一挂回来」这条状态机；
「周本排在体力副本之前」由 ok_tasks 覆盖层的 DailyTask.run 钩子保证，
见 docs/OKWW-WEEKLY-BOSS.md。

    Formerly test_weeklyboss_cycle.py.
    """
    import json, os, sys
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import weeklyboss as W
    from ark_relay.core.config import SERVER_TZ

    TMP = tmpdir()
    LOG = TMP / "ok.log"; os.environ["ARK_OKWW_LOG"] = str(LOG)
    STATE = TMP / "state"; STATE.mkdir()
    # 假 AUTO-MAS：母本目录靠 DailyTask.json 认出来
    CFG = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"
    CFG.mkdir(parents=True)
    (CFG / "DailyTask.json").write_text(json.dumps(
        {W.KEY: ["Auto Farm all Nightmare Nest"]}), encoding="utf-8")
    (CFG / "FarmEchoTask.json").write_text(json.dumps({}), encoding="utf-8")


    def tasks():
        return json.loads((CFG / "DailyTask.json").read_text(encoding="utf-8"))[W.KEY]

    def at(mon_day, hh, mm=0):
        return datetime(2026, 8, mon_day, hh, mm, tzinfo=SERVER_TZ)

    def left(n):
        LOG.write_text(f"周本本周剩余次数原文: [本周剩余可收取次数：{n}/3]\n", encoding="utf-8")

    g = W.WeeklyBossGate(STATE, TMP / "automas")
    g.configure(index=1)

    print("\n[开着就挂上，配置一起写对]")
    g.enforce(at(31, 10))
    check("附加任务里有周本", W.TASK_NAME in tasks(), True)
    farm = json.loads((CFG / "FarmEchoTask.json").read_text(encoding="utf-8"))
    check("传送目标", farm.get("Teleport to Boss"), W.WEEKLY)
    check("难度是最高级", farm.get("Boss Level"), W.MAX_LEVEL)
    check("次数", farm.get("Repeat Farm Count"), 3)

    print("\n[没领满就一直挂着——这正是剿灭没有、而周本必须有的]")
    left(2)
    g.on_success(at(31, 11))
    g.enforce(at(31, 11))
    check("还剩 2 次，开关不许摘", W.TASK_NAME in tasks(), True)

    print("\n[领满才摘掉，之后不再检测]")
    left(0)
    g.on_success(at(31, 12))
    check("记成本周已打", g.settings(at(31, 12))["本周已打"], True)
    g.enforce(at(31, 12))
    check("附加任务里已摘掉", W.TASK_NAME in tasks(), False)
    g.enforce(at(31, 20))          # 同一周内反复跑，不许再挂回去
    check("同周内再跑也不挂回来", W.TASK_NAME in tasks(), False)

    print("\n[周一 04:00 前仍算上一周]")
    # 2026-09-07 是周一。03:59 仍属于上一周，不许刷新。
    g.enforce(datetime(2026, 9, 7, 3, 59, tzinfo=SERVER_TZ))
    check("周一 03:59 还不刷新", W.TASK_NAME in tasks(), False)

    print("\n[过了周一 04:00 自动挂回来]")
    g.enforce(datetime(2026, 9, 7, 4, 1, tzinfo=SERVER_TZ))
    check("下周一自动挂回来", W.TASK_NAME in tasks(), True)
    check("状态不再显示「本周已打」",
          g.settings(datetime(2026, 9, 7, 4, 1, tzinfo=SERVER_TZ))["本周已打"], False)

    print("\n[没有总开关：和剿灭一样，只有「本周做完」才摘掉]")
    check("settings 里没有开关", "开" in g.settings(datetime(2026, 9, 7, 5, 0, tzinfo=SERVER_TZ)), False)
    check("次数固定 3", g.settings()["打几次"], 3)
    check("等级固定 90", g.settings()["难度等级"], "90")

    # docs/SILENT-FAILURES-AUDIT.md weeklyboss.py:75 - an unreadable FarmEchoTask.json
    # used to leave the weekly boss armed with no teleport target and no word.
    print("\n[FarmEchoTask.json unreadable while switching on: said once per condition]")
    import logging


    class _Lines(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append((record.levelname, record.getMessage()))


    _log = _Lines()
    logging.getLogger(W.log.name.rsplit(".", 1)[0]).addHandler(_log)   # every relay logger's parent
    MON = datetime(2026, 9, 7, 5, 0, tzinfo=SERVER_TZ)
    (CFG / "FarmEchoTask.json").write_text("{ torn", encoding="utf-8")
    g.enforce(MON)
    g.enforce(MON)
    farm_warn = lambda: [m for lv, m in _log.lines if lv == "WARNING" and W.FARM in m]  # noqa: E731
    check("one WARNING for two rounds (enforce runs every round)", len(farm_warn()), 1)
    # 2026-10-13 audit: the task stayed listed with no target, and upstream's
    # validate_additional_tasks then raises before login (the whole daily fails).
    check("no target: the weekly boss is not left listed", W.TASK_NAME in tasks(), False)
    (CFG / "FarmEchoTask.json").write_text(json.dumps({}), encoding="utf-8")
    g.enforce(MON)
    check("readable again: the target is written",
          json.loads((CFG / "FarmEchoTask.json").read_text(encoding="utf-8")).get("Teleport to Boss"), W.WEEKLY)
    check("readable again: listed again", W.TASK_NAME in tasks(), True)

    (CFG / "FarmEchoTask.json").write_text("{ torn", encoding="utf-8")
    g.enforce(MON)
    check("after it cleared, a new failure is said again", len(farm_warn()), 2)

    print("\n[the target is written before the task is listed; a failed write lists nothing]")
    (CFG / "DailyTask.json").write_text(json.dumps({W.KEY: []}), encoding="utf-8")
    (CFG / "FarmEchoTask.json").write_text(json.dumps({"Teleport to Boss": "No"}), encoding="utf-8")
    order = []
    _real_write = W._write


    def _spy(f, cfg):
        order.append(Path(f).name)
        return _real_write(f, cfg)


    W._write = _spy
    try:
        g.enforce(MON)
    finally:
        W._write = _real_write
    check("FarmEchoTask.json first, DailyTask.json after", order, [W.FARM, W.DAILY])
    check("…and listed", W.TASK_NAME in tasks(), True)
    (CFG / "DailyTask.json").write_text(json.dumps({W.KEY: []}), encoding="utf-8")
    (CFG / "FarmEchoTask.json").write_text(json.dumps({"Teleport to Boss": "No"}), encoding="utf-8")
    W._write = lambda f, cfg: False if Path(f).name == W.FARM else _real_write(f, cfg)
    try:
        g.enforce(MON)
    finally:
        W._write = _real_write
    check("target write failed: the task is not listed", W.TASK_NAME in tasks(), False)
    g.enforce(MON)
    check("next round with a writable target: listed", W.TASK_NAME in tasks(), True)
    (CFG / "FarmEchoTask.json").write_text(json.dumps({}), encoding="utf-8")
    g.enforce(MON)


def _part_weeklyboss_reopen():
    """「新的一周」通知要带上鸣潮周本（用户 2026-09-07）。

2026-09-07（周一）08:48 的通知只有「新的一周，剿灭已重新开启」，
周本那边 weeklyboss.json 里 done_week 还是上周（2026-W36），
用户看不到周本这周会不会打、打哪个、打几次。

    Formerly test_weeklyboss_reopen.py.
    """
    import json, os, sys, types
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import weeklyboss as W
    from ark_relay.core.config import SERVER_TZ


    TMP = tmpdir()
    os.environ["ARK_OKWW_LOG"] = str(TMP / "ok.log")
    STATE = TMP / "state"; STATE.mkdir()
    CFG = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"; CFG.mkdir(parents=True)
    (CFG / "DailyTask.json").write_text(json.dumps({W.KEY: []}), encoding="utf-8")
    (CFG / "FarmEchoTask.json").write_text(json.dumps({}), encoding="utf-8")

    MON = datetime(2026, 9, 7, 8, 48, tzinfo=SERVER_TZ)          # 2026-W37
    (STATE / "weeklyboss.json").write_text(json.dumps(
        {"enabled": True, "index": 1, "count": 3, "level": "90",
         "name": "千傀重楼", "done_week": "2026-W36"}), encoding="utf-8")
    g = W.WeeklyBossGate(STATE, TMP / "automas")

    print("[机器上 09-07 的状态：上周领满，周一开机]")
    line = g.maybe_reopen(MON)
    check("说清打哪个", line, "鸣潮 · 周本：千傀重楼，本周还没领满")
    check("记账已清", "done_week" in g._load(), False)
    check("同一次开机再问就不再说", g.maybe_reopen(MON), "")
    check("week_line 仍能报状态", g.week_line(MON), "鸣潮 · 周本：千傀重楼，本周还没领满")

    print("[本周已领满 / 开关关着]")
    g.on_success  # noqa: B018 - 只是确认接口还在
    s = g._load(); s["done_week"] = "2026-W37"; g._save(s)
    check("已领满", g.week_line(MON), "鸣潮 · 周本：千傀重楼 本周三次已领满，暂停到下周一")
    check("没有总开关", "开" in g.settings(MON), False)

    print("[开机那一段：剿灭、周常乐园、周本合成一条「新的一周」，三行都在]")
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
    # 开机的各个阶段 2026-09-08 从 service.py 搬进了 boot_stages.py；
    # 私有名要用就直接引它本尊，不经 service.py 转手。
    import boot_stages

    sent = []
    class N:
        def send(self, title, body, **kw): sent.append((title, body))
    class Log:
        def exception(self, *a, **k): print("    EXC", a)
    class Gate:
        def __init__(self, reopen, line): self._r, self._l = reopen, line; self.enforced = 0
        def maybe_reopen(self): return self._r
        def week_line(self): return self._l
        def enforce(self): self.enforced += 1
    class AnniStatus:
        """Annihilation since the 2026-10-11 hand-over: a status line only, no roll-over."""
        def __init__(self, line): self._l = line
        def week_line(self): return self._l
        def maybe_reopen(self): raise AssertionError("annihilation must not roll over in the relay any more")
        def enforce(self): raise AssertionError("annihilation must not be enforced by the relay any more")
    class Eng:
        def __init__(self, ann, garden, boss):
            self._annihilation, self._garden, self._weeklyboss = ann, garden, boss

    A_LINE = "明日方舟 · 剿灭：本周还没打满，开关开着（Annihilation）"
    G_LINE = "鸣潮 · 周常乐园：本周还没做，每趟都会去检查"
    B_LINE = "鸣潮 · 周本：千傀重楼，本周还没领满"
    B_FULL = "鸣潮 · 周本：千傀重楼 本周三次已领满，暂停到下周一"

    sent.clear(); boss = Gate(B_LINE, B_LINE); garden = Gate(G_LINE, G_LINE)
    boot_stages._stage_annihilation(Eng(AnniStatus(A_LINE), garden, boss), N(), Log())
    check("both roll over: one notice, annihilation status first", sent, [("🗓️ 新的一周", "\n".join([A_LINE, G_LINE, B_LINE]))])
    check("weekly boss is really put back before saying so", boss.enforced, 1)
    check("weekly garden likewise", garden.enforced, 1)

    sent.clear(); garden = Gate(G_LINE, G_LINE)
    boot_stages._stage_annihilation(Eng(AnniStatus(A_LINE), garden, Gate("", B_FULL)), N(), Log())
    check("only the garden rolls over: the other two still report", sent,
          [("🗓️ 新的一周", "\n".join([A_LINE, G_LINE, B_FULL]))])

    sent.clear()
    boot_stages._stage_annihilation(Eng(AnniStatus(A_LINE), Gate("", G_LINE), Gate("", B_LINE)), N(), Log())
    check("nothing rolls over: nothing sent (annihilation alone never triggers it)", sent, [])

    sent.clear()
    boot_stages._stage_annihilation(Eng(None, Gate(G_LINE, G_LINE), Gate("", B_LINE)), N(), Log())
    check("no annihilation gate: the other lines still go out", sent, [("🗓️ 新的一周", "\n".join([G_LINE, B_LINE]))])


if __name__ == "__main__":
    sys.exit(run_parts([_part_weeklyboss_count, _part_weeklyboss_cycle, _part_weeklyboss_reopen]))
