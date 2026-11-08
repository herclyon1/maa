"""The weekly garden gate: the gate, the roll-over after a tick, the unified gate.

One part per former file, each run on its own (tests/_parts.py): test_garden_gate.py, test_garden_rollover_after_tick.py, test_garden_unified.py.
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


def _part_garden_gate():
    """周常乐园的周门：本周做完就关掉检查，周一 04:00 开回来。

和剿灭那道门是同一个形状，所以周界口径必须一致——直接复用
`annihilation.week_key`，不许自己再算一遍。这个文件把三件事钉住：

  1. 周界就是周一 04:00（周一 03:59 还算上一周）；
  2. 记账只写状态文件，不碰配置（落盘交给 enforce）；
  3. enforce 幂等，而且新的一周会把检查放回去。

    Formerly test_garden_gate.py.
    """
    import json
    import tempfile
    from datetime import datetime, timedelta

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import garden
    from ark_relay.features.weekly.annihilation import week_key
    from ark_relay.core.config import SERVER_TZ

    FAILED = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}, want {want!r}")
        if not ok:
            FAILED.append(name)


    def test_week_boundary() -> None:
        """周一 04:00 才翻篇。03:59 跑的那轮必须还算上一周。"""
        print("[周界：周一 04:00]")
        mon = datetime(2026, 8, 24, 3, 59, tzinfo=SERVER_TZ)      # 周一 03:59
        check("周一 03:59 和上周日同一周",
              week_key(mon) == week_key(mon - timedelta(hours=6)), True)
        check("周一 04:01 已经是新的一周",
              week_key(mon + timedelta(minutes=2)) != week_key(mon), True)


    def _make_master(root: Path, tasks: list[str]) -> Path:
        """造一份和机器上一样的母本：<automas>/data/<sid>/Default/ConfigFile/DailyTask.json"""
        d = root / "automas" / "data" / "c5e96ddc" / "Default" / "ConfigFile"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "DailyTask.json"
        f.write_text(json.dumps({
            "Which to Farm": "Forgery Challenge",
            garden.KEY: list(tasks),
            "Exit After Task": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return root / "automas"


    def _read(automas: Path) -> list[str]:
        f = automas / "data" / "c5e96ddc" / "Default" / "ConfigFile" / "DailyTask.json"
        return json.loads(f.read_text(encoding="utf-8"))[garden.KEY]


    def _other_keys(automas: Path) -> dict:
        f = automas / "data" / "c5e96ddc" / "Default" / "ConfigFile" / "DailyTask.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if k != garden.KEY}


    def test_gate(tmp: Path) -> None:
        print("[记账 → 落盘 → 周一恢复]")
        now = datetime(2026, 8, 26, 12, 0, tzinfo=SERVER_TZ)   # 周三
        automas = _make_master(tmp, [garden.TASK_NAME, "Other Task"])
        g = garden.GardenGate(tmp, automas)
        before_other = _other_keys(automas)

        msg = g.on_success(now)
        check("第一次记账有回话", bool(msg), True)
        check("记账**不碰配置**（落盘留给 enforce）",
              garden.TASK_NAME in _read(automas), True)
        check("状态文件记下了本周", json.loads((tmp / "state.json").read_text())["weekly"]["garden"]["done_week"],
              week_key(now))
        check("同一周重复记账不再啰嗦", g.on_success(now), "")

        check("enforce 生效", g.enforce(now), True)
        check("检查已关掉", garden.TASK_NAME in _read(automas), False)
        check("同组别的任务没被误伤", "Other Task" in _read(automas), True)
        check("DailyTask 其余键原样保留", _other_keys(automas), before_other)
        check("已经关掉了就不再重复写", g.enforce(now), False)

        nxt = now + timedelta(days=7)
        check("新的一周会把检查放回去", g.enforce(nxt), True)
        check("检查回来了", garden.TASK_NAME in _read(automas), True)
        # The earlier week's booking is left for maybe_reopen at boot, so the new-week
        # notice still sees the roll-over (audit 10-13, test_garden_rollover_after_tick.py).
        check("过期记账留给开机清", json.loads((tmp / "state.json").read_text())["weekly"]["garden"].get("done_week"),
              week_key(now))
        check("开机清账并说新的一周", bool(g.maybe_reopen(nxt)), True)
        check("过期记账已清掉", json.loads((tmp / "state.json").read_text())["weekly"].get("garden") or {}, {})

        # Written but read back unchanged (another program wrote it back): not reported as set,
        # False, pushed again next round (audit 11-08 D-13).
        g.on_success(nxt)
        real_write = garden.atomic_write_text
        garden.atomic_write_text = lambda f, text: None          # the write "went through", the file did not change
        try:
            check("写了但读回来没变：不算改成", g.enforce(nxt), False)
            check("……开关还在（没谎称关了）", garden.TASK_NAME in _read(automas), True)
        finally:
            garden.atomic_write_text = real_write
        check("下一轮照常写成", g.enforce(nxt), True)

        # 找不到母本时必须安静地不动手，而不是抛异常把中继带崩
        g2 = garden.GardenGate(tmp, tmp / "nowhere")
        g2._save({"done_week": week_key(now)})
        check("母本找不到时 enforce 返回 False 而不炸", g2.enforce(now), False)


    def main(tmp: Path) -> int:
        test_week_boundary()
        test_gate(tmp)
        print("all checks passed" if not FAILED else f"FAILED: {FAILED}")
        return 0 if not FAILED else 1


    if __name__ == "__main__":
        with tempfile.TemporaryDirectory() as t:
            raise SystemExit(main(Path(t)))


def _part_garden_rollover_after_tick():
    """A periodic tick after Monday 04:00 must not eat the weekly garden's roll-over.

Audit 2026-10-13 (weekly block, finding 3). GardenGate.enforce() popped a
done_week from an earlier week itself (garden.py:113-114, :132-133), so the
boot-time WeekGate.maybe_reopen found nothing to roll over and the garden never
joined the new-week notice. The machine's record of Monday 2026-10-05 (Beijing
time, relay.log of the 10-13 copy):

    10-05 04:43:37 INFO    ark.garden  周常乐园检查已恢复
    10-05 08:45:19 INFO    ark.service  服务模式启动 ...
    10-05 08:46:03 INFO    ark.weeklyboss  新的一周，周本记账已清（上周 2026-W40）

No 「新的一周，周常乐园记账已清」 line: the 04:43 tick had already cleared it.
That day's new-week notice went out only because the weekly boss rolled over;
with only the garden done the week before, none would have gone out.

Replayed here: garden done in 2026-W40, switch off; ticks at 04:43:37 and 05:00
on Monday 10-05; boot at 08:46:03.

    Formerly test_garden_rollover_after_tick.py.
    """

    import json
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import boot_stages
    from ark_relay.core import texts
    from ark_relay.core.config import SERVER_TZ
    from ark_relay.features.weekly import garden as G
    from ark_relay.features.weekly.annihilation import week_key

    FAILED: list[str] = []


    def check(name, got, want):
        ok = got == want
        print(f"  {'ok ' if ok else 'FAIL'}  {name}: got {got!r}")
        if not ok:
            FAILED.append(name)


    SAT = datetime(2026, 10, 3, 20, 0, tzinfo=SERVER_TZ)
    TICK = datetime(2026, 10, 5, 4, 43, 37, tzinfo=SERVER_TZ)
    TICK2 = datetime(2026, 10, 5, 5, 0, 0, tzinfo=SERVER_TZ)
    BOOT = datetime(2026, 10, 5, 8, 46, 3, tzinfo=SERVER_TZ)


    class AtBoot(G.GardenGate):
        """The gate as the boot stage calls it (no `now`), pinned to 10-05 08:46:03."""

        def maybe_reopen(self, now=None):
            return super().maybe_reopen(now or BOOT)

        def enforce(self, now=None):
            return super().enforce(now or BOOT)

        def week_line(self, now=None):
            return super().week_line(now or BOOT)


    class Notifier:
        def __init__(self):
            self.sent = []

        def send(self, title, body, **kw):
            self.sent.append((title, body))
            return []


    class Log:
        def exception(self, *a, **k):
            FAILED.append("boot stage logged an exception")

        def warning(self, *a, **k):
            pass


    def master(tmp: Path) -> Path:
        cfg = tmp / "automas" / "data" / "sid" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        (cfg / "DailyTask.json").write_text(json.dumps({G.KEY: [G.TASK_NAME]}), encoding="utf-8")
        return cfg / "DailyTask.json"


    def switch_on(f: Path) -> bool:
        return G.TASK_NAME in json.loads(f.read_text(encoding="utf-8"))[G.KEY]


    check("10-03 is game-week 2026-W40", week_key(SAT), "2026-W40")
    check("10-05 04:43 is the new week 2026-W41", week_key(TICK), "2026-W41")

    print("\n[garden done in W40, switched off]")
    tmp = tmpdir()
    f = master(tmp)
    g = AtBoot(tmp / "state", tmp / "automas")
    g.on_success(SAT)
    check("switched off in W40", (g.enforce(SAT), switch_on(f)), (True, False))

    print("\n[Monday 04:43:37 tick puts the switch back; 05:00 tick finds nothing to do]")
    check("04:43:37 switch back on", (g.enforce(TICK), switch_on(f)), (True, True))
    check("05:00 no change", g.enforce(TICK2), False)
    check("not done this week", g.settings(TICK2), {"本周已完成": False})

    print("\n[08:46:03 boot: the garden still rolls over into the new week]")
    n = Notifier()
    engine = type("E", (), {"_garden": g, "_weeklyboss": None, "_annihilation": None})()
    boot_stages._stage_annihilation(engine, n, Log())
    check("a new-week notice goes out", [t for t, _ in n.sent], [texts.NEW_WEEK])
    check("it carries the garden's line", [b for _, b in n.sent], ["鸣潮 · 周常乐园：本周还没做，每趟都会去检查"])
    check("asked again: nothing more", g.maybe_reopen(), "")
    check("switch stays on", switch_on(f), True)

    print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
    sys.exit(1 if FAILED else 0)


def _part_garden_unified():
    """周常乐园和剿灭、周本一套接口：settings / week_line / maybe_reopen / configure。

用户 2026-09-07：「鸣潮有两个东西，一个是周常乐园（不消耗体力完成），一个是周本
材料（一周三次，要消耗体力）。我希望手机网页界面操作逻辑、中继每周判定他们的
逻辑、推送的通知里应该统一。目前通知是散开的而且没有周常乐园。」

    Formerly test_garden_unified.py.
    """
    import json, sys
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.weekly import garden as G
    from ark_relay.core.config import SERVER_TZ


    TMP = tmpdir()
    CFG = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"; CFG.mkdir(parents=True)
    (CFG / "DailyTask.json").write_text(json.dumps({G.KEY: ["Check Weekly Garden"]}), encoding="utf-8")
    def tasks():
        return json.loads((CFG / "DailyTask.json").read_text(encoding="utf-8"))[G.KEY]

    MON = datetime(2026, 9, 7, 8, 48, tzinfo=SERVER_TZ)
    SUN = datetime(2026, 9, 6, 12, 0, tzinfo=SERVER_TZ)
    g = G.GardenGate(TMP / "state", TMP / "automas")

    print("[默认开着、本周没做]")
    check("settings", g.settings(SUN), {"本周已完成": False})
    check("week_line", g.week_line(SUN), "鸣潮 · 周常乐园：本周还没做，每趟都会去检查")

    print("[周日做完 → 记账、摘掉]")
    check("on_success 的话", g.on_success(SUN), "鸣潮 · 周常乐园：本周已完成，暂停检查到下周一")
    check("本周已完成", g.settings(SUN)["本周已完成"], True)
    check("week_line", g.week_line(SUN), "鸣潮 · 周常乐园：本周已完成，暂停检查到下周一")
    check("enforce 摘掉", g.enforce(SUN), True)
    check("母本里没了", G.TASK_NAME in tasks(), False)

    print("[周一开机 → maybe_reopen 清账并给出状态行，enforce 挂回去]")
    check("maybe_reopen", g.maybe_reopen(MON), "鸣潮 · 周常乐园：本周还没做，每趟都会去检查")
    check("再问就不说了", g.maybe_reopen(MON), "")
    check("enforce 挂回去", g.enforce(MON), True)
    check("母本里回来了", G.TASK_NAME in tasks(), True)

    print("[没有总开关：和剿灭一样只显示状态]")
    check("settings 里没有开关", "开" in g.settings(MON), False)
    check("没有 configure", hasattr(g, "configure"), False)


if __name__ == "__main__":
    sys.exit(run_parts([_part_garden_gate, _part_garden_rollover_after_tick, _part_garden_unified]))
