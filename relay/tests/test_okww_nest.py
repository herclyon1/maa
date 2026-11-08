"""OK-WW's nest and weekly boss: the capture, the expected count, fought then full, names, the travel retry, v3.7.3, no challenge window, the weekly boss step, entry paths, spend.

One part per former file, each run on its own (tests/_parts.py): test_okww_nest_capture.py, test_okww_nest_expected.py, test_okww_nest_fought_then_full.py, test_okww_nest_names.py, test_okww_nest_travel_retry.py, test_okww_nest_v373.py, test_okww_no_challenge_window.py, test_okww_weekly_boss_step.py, test_okww_weekly_entry_paths.py, test_okww_weekly_spend.py.
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


def _part_okww_nest_capture():
    """Nest overrides, part two: both entries, an unread count, an adapted install.

* DailyTask's 「Farm Nightmare Nest for Daily Echo」 calls run_capture_mode directly
  (upstream v3.7.3 DailyTask.py:106), which went round our run(): no filter gate, no
  「列表里没找到」 alarm, no per-run resets. Both entries now share one wrapper.
* A row whose nest name was read and whose 「已击败残象：x/y」 was not used to be skipped
  without a word - with two wanted nests, the other one being full, the log said
  「都已打满」. Now: screenshot nest_count_unread, the raw read in the log, an alarm.
* find_nest installed adapted to a changed upstream body says so in OK-WW's log on
  every run, and the run's report carries it beside the nest.

Runs upstream's real v3.7.3 NightmareNestTask (fixture) against the overlay.

    Formerly test_okww_nest_capture.py.
    """
    import re
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww, outcome
    from ark_relay.features.okww_patch import okww_overlay


    # The OK-WW the machine runs (test_gl_okww_contract.INSTALLED); v3.7.3/v3.7.4 body until 2026-11-02.
    UPSTREAM = (Path(__file__).resolve().parent / "gamesim" / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task" / "NightmareNestTask.py.txt").read_text(encoding="utf-8")


    def upstream_class(text=UPSTREAM):
        class WWOneTimeTask:
            def run(self):
                pass

            def tr(self, msg):          # ok-script's translation, English here
                return msg

        ok = types.ModuleType("ok")
        ok.Logger = types.SimpleNamespace(get_logger=lambda name: types.SimpleNamespace(info=lambda *a: None))
        ok.run_task = lambda *a, **kw: None
        combat = types.ModuleType("src.task.BaseCombatTask")
        combat.BaseCombatTask = type("BaseCombatTask", (), {})
        combat.CharRevivedException = type("CharRevivedException", (Exception,), {})
        onetime = types.ModuleType("src.task.WWOneTimeTask")
        onetime.WWOneTimeTask = WWOneTimeTask
        sys.modules.update({"ok": ok, "cv2": types.ModuleType("cv2"), "config": types.SimpleNamespace(config={}),
                            "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
                            "src.task.BaseCombatTask": combat, "src.task.WWOneTimeTask": onetime})
        path = tmpdir() / "NightmareNestTask.py"
        path.write_text(text, encoding="utf-8")
        mod = types.ModuleType("src.task.NightmareNestTask")
        mod.__file__ = str(path)
        exec(compile(text, str(path), "exec"), mod.__dict__)
        sys.modules["src.task.NightmareNestTask"] = mod
        return mod.NightmareNestTask


    def overlay(cls_text=UPSTREAM):
        cls = upstream_class(cls_text)
        ns = {}
        exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
        for k in ("_applied", "_skipped", "_adapted"):
            ns[k].clear()
        ns["TaskDisabledException"] = type("TaskDisabledException", (Exception,), {})
        ns["_install_nest"]()
        return cls, ns


    class Box:
        def __init__(self, name, y, height=30):
            self.name, self.x, self.y, self.width, self.height = name, 889, y, 198, height


    def fake(cls, pages, ns, only="落渊南丘", capture=False):
        """A task whose screen is pages[page]; a page may be a list of reads, used in turn."""
        t = object.__new__(cls)
        t.config = {ns["ONLY_NESTS"]: only, "Which to Farm": ["Tacet Discord Nest"]}
        t.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        t._unreachable_nests, t._nest_deaths, t.queues = set(), {}, []
        t._nest_tab_of_current_nest = "go_nest"
        t._capture_mode = t._capture_success = False
        t.page, t.reads, t.events, t.errors, t.infos, t.fought, t.shots = 0, 0, [], [], [], [], []

        def ocr(x, y, to_x, to_y, match=None):
            screen = pages[t.page]
            if screen and isinstance(screen[0], list):          # successive reads of one page
                screen = screen[min(t.reads, len(screen) - 1)]
                if match:
                    t.reads += 1
            return [Box(b.name, b.y, b.height) for b in screen if not match or match.search(b.name)]
        t.ocr = ocr
        t.open_boss_book = lambda name: setattr(t, "page", 0)
        t.click = lambda *a, **kw: setattr(t, "page", 1) if a and a[0] == 0.9730 else None
        t.openF2Book = lambda name: t.events.append("book")
        # DailyTask replaces ensure_main with a no-op before run_capture_mode (DailyTask.py:98).
        t.ensure_main = (lambda *a, **kw: None) if capture else (lambda time_out=0: t.events.append("main"))
        t.log_info = lambda msg, notify=False: t.infos.append(msg)
        t.log_error = lambda msg, notify=False: t.errors.append((msg, notify))
        t.screenshot = lambda name: t.shots.append(name)
        t.sleep = lambda s: None
        t.width_of_screen = lambda f: f * 1920
        t.height_of_screen = lambda f: f * 1080

        def combat_nest(nest):
            t.fought.append(nest.cache_key)
            t._capture_success = capture       # a capture lap that got its echo ends the loop
        t.combat_nest = combat_nest
        return t


    NAME_NEW, NAME_NANQIU = Box("新区残象聚落", 300), Box("落渊南丘残象聚落", 450)
    PAGE2 = [Box("别的残象聚落", 300), Box("已击败残象：3/24", 374)]


    def page1(nanqiu):
        return [NAME_NEW, Box("已击败残象：0/48", 374), NAME_NANQIU, Box(f"已击败残象：{nanqiu}", 524)]


    # 南丘's count box centre is (524 + 15) / 1080 = 0.499 of the screen: row slot 25.
    NANQIU_KEY = "go_nest:41:25"

    Nest, ns = overlay()

    print("\n[两个入口都换上了]")
    check("run 与 run_capture_mode 都换上了", all(f"NightmareNestTask.{m}" in ns["_applied"]
                                                for m in ("run", "run_capture_mode")))
    check("没有跳过的", ns["_skipped"], [])

    for entry in ("run", "run_capture_mode"):
        capture = entry == "run_capture_mode"
        print(f"\n[{entry}：上一轮留下的状态先清掉]")
        t = fake(Nest, [page1("10/41"), PAGE2], ns, capture=capture)
        # Left over from a previous call on the same instance (DailyTask keeps one):
        # without the reset this stamp reads as 「tried, no progress」 and 南丘 is skipped.
        t._ark_nest_tried = {f"{NANQIU_KEY}@10"}
        t._ark_nest_progress = {NANQIU_KEY: "10"}
        t._ark_nest_seen, t._ark_nest_missed = True, ["旧的"]
        getattr(t, entry)()
        check("进了南丘", t.fought[:1], [NANQIU_KEY])
        if capture:
            check("抓到声骸就收手（只打一局）", len(t.fought), 1)
        check("过滤来源本轮说了", any("nightmare nest: 只刷 ['落渊南丘']" in m for m in t.infos))
        check("没报错", t.errors, [])

        print(f"\n[{entry}：两屏都没有南丘，结束时报一次]")
        t = fake(Nest, [[NAME_NEW, Box("已击败残象：0/48", 374)], PAGE2], ns, capture=capture)
        getattr(t, entry)()
        check("一局没打", t.fought, [])
        check("报了一次列表里没找到，并推送", [("列表里没找到指定的点位" in e[0], e[1]) for e in t.errors],
              [(True, True)])

    print("\n[find_nest 换不上：两个入口都不刷]")
    gone = UPSTREAM.replace("    def find_nest(self):", "    def find_nest_renamed(self):")
    check("样本确实改到了", gone != UPSTREAM)
    Nest3, ns3 = overlay(gone)
    check("find_nest 记为没贴上", [s["what"] for s in ns3["_skipped"]], ["NightmareNestTask.find_nest"])
    for entry in ("run", "run_capture_mode"):
        t = fake(Nest3, [page1("10/41"), PAGE2], ns3, capture=entry == "run_capture_mode")
        getattr(t, entry)()
        check(f"{entry} 一局没打", t.fought, [])
        check(f"{entry} 说了这一轮不刷", any("这一轮不刷巢穴" in m for m in t.infos))

    print("\n[南丘的名字读到了、计数没读到：停下、截图、报警，不说打满]")
    misread = [NAME_NEW, Box("已击败残象：0/48", 374), NAME_NANQIU, Box("已击败残象：1O/41", 524)]
    t = fake(Nest, [misread, PAGE2], ns)
    t.run()
    check("一局没打（也没去打上面那个 0/48）", t.fought, [])
    check("截了 nest_count_unread", t.shots, ["nest_count_unread"])
    check("报警一次，并推送", [e[1] for e in t.errors], [True])
    msg = t.errors[0][0] if t.errors else ""
    check("报警写明计数没读到", ns["NEST_COUNT_UNREAD"] in msg)
    check("报警带着识字原文", "1O/41" in msg)
    check("报警写明不是打满", "不是打满" in msg)
    check("没说已打满", any("都已打满" in m for m in t.infos), False)

    print("\n[两个指定点位：一个满了、一个计数没读到 → 不能报「都已打满」]")
    two = [Box("落渊南丘残象聚落", 300), Box("已击败残象：41/41", 374),
           Box("别处残象聚落", 450), Box("已击败", 524)]
    t = fake(Nest, [two, PAGE2], ns, only="落渊南丘,别处")
    t.run()
    check("一局没打", t.fought, [])
    check("没说已打满", any("都已打满" in m for m in t.infos), False)
    check("报的是计数没读到", [ns["NEST_COUNT_UNREAD"] in e[0] for e in t.errors], [True])

    print("\n[计数那一行一时没渲染出来：再看一眼，读到了就照常刷，不报警]")
    late = [[NAME_NEW, Box("已击败残象：0/48", 374), NAME_NANQIU],      # wanted_rows' wait: one count is up
            [NAME_NEW, Box("已击败残象：0/48", 374), NAME_NANQIU],      # find_nest's first read: 南丘 not yet
            page1("10/41")]                                              # the second look
    t = fake(Nest, [late, PAGE2], ns)
    t.run()
    check("进了南丘", t.fought[:1], [NANQIU_KEY])
    check("没报警", t.errors, [])
    check("没截计数没读到的图", "nest_count_unread" in t.shots, False)

    print("\n[上游改了 find_nest、按新版适配装上：每轮在 OK-WW 日志里说一句]")
    changed = UPSTREAM.replace("counts = self.ocr(0.35, 0.25, 1, 0.96, match=self.count_re)",
                               "counts = self.ocr(0.35, 0.3, 1, 0.96, match=self.count_re)  # moved again")
    check("样本确实改到了", changed != UPSTREAM)
    Nest2, ns2 = overlay(changed)
    check("记在已适配里", [a["what"] for a in ns2["_adapted"]], ["NightmareNestTask.find_nest"])
    for entry in ("run", "run_capture_mode"):
        t = fake(Nest2, [page1("10/41"), PAGE2], ns2, capture=entry == "run_capture_mode")
        getattr(t, entry)()
        check(f"{entry} 说了过滤是适配装上的", any(ns2["NEST_ADAPTED"] in m for m in t.infos))
        check(f"{entry} 照样只进南丘", t.fought[:1], [NANQIU_KEY])
    t = fake(Nest, [page1("10/41"), PAGE2], ns)
    t.run()
    check("没适配时不说", any(ns["NEST_ADAPTED"] in m for m in t.infos), False)

    print("\n[中继读日志：两句新话进了结果判定和日报]")
    check("计数没读到：覆盖层与判定用同一句", ns["NEST_COUNT_UNREAD"], outcome._NEST_COUNT_UNREAD)
    check("已适配：覆盖层与判定用同一句", ns["NEST_ADAPTED"], outcome._NEST_ADAPTED)
    # Lines as OK-WW writes them: ok-script prefixes log_info / log_error with the task name.
    head = ("2026-10-06 09:20:01 INFO TaskExecutor NightmareNestTask:open_boss_book canxiang\n"
            "2026-10-06 09:20:02 INFO TaskExecutor NightmareNestTask:nightmare nest: 只刷 ['落渊南丘']（设置来自母本）\n")
    unread_log = head + ("2026-10-06 09:20:05 ERROR TaskExecutor NightmareNestTask:nightmare nest: "
                         f"{ns['NEST_COUNT_UNREAD']}（名字所在行 [465]），这一屏不刷——**不是打满**。\n")
    steps = collector_okww._okww_steps(unread_log, 0)
    check("日报：计数没读到", [s for s in steps if "残象聚落" in s], ["残象聚落（计数没读到，停下没刷）"])
    verdict = [k for k in outcome.okww_checks(unread_log, expect_nest=True) if "残象聚落" in k.label]
    check("判定：残象聚落不算过", [(k.ok, "计数没读到" in k.detail) for k in verdict], [(False, True)])
    adapted_log = head + (f"2026-10-06 09:20:02 INFO TaskExecutor NightmareNestTask:nightmare nest: "
                          f"{ns['NEST_ADAPTED']}，这一轮请核对只进了指定点位\n"
                          "2026-10-06 09:21:00 INFO TaskExecutor NightmareNestTask:enter combat None\n")
    steps = collector_okww._okww_steps(adapted_log, 0)
    check("日报：残象聚落旁写着按新版适配", [s for s in steps if "残象聚落" in s],
          ["残象聚落（只刷指定点位的过滤按 OK-WW 新版适配，请核对）"])
    plain = head + "2026-10-06 09:21:00 INFO TaskExecutor NightmareNestTask:enter combat None\n"
    check("没适配时日报照旧", [s for s in collector_okww._okww_steps(plain, 0) if "残象聚落" in s], ["残象聚落"])

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_nest_expected():
    """Whether a run should have farmed nests follows upstream's own condition.

OK-WW v3.7.4 DailyTask.py:84-93 runs the nests when 「Auto Farm all Nightmare
Nest」 is an additional task, or when 「Farm Nightmare Nest for Daily Echo」 (default
True, :37) is on, the farm target is not Tacet Suppression (the default) and the
daily reward is not ready. gamelogs._okww_nest_expected also said True for a
leftover 「Only Farm These Nests」 text or the echo flag alone, so unticking 「Auto
Farm all Nightmare Nest」 turned every daily red (audit 2026-10-13 item 9). The
daily-reward part is the log's (outcome.okww_checks), not the config's.

    Formerly test_okww_nest_expected.py.
    """
    import json

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.alarm.gamelogs import _okww_nest_expected


    def automas(daily=None, nest=None):
        root = tmpdir()
        d = root / "data" / "okww-id" / "Default" / "ConfigFile"
        d.mkdir(parents=True)
        if daily is not None:
            (d / "DailyTask.json").write_text(json.dumps(daily), encoding="utf-8")
        if nest is not None:
            (d / "NightmareNestTask.json").write_text(json.dumps(nest), encoding="utf-8")
        return root


    ADDS = "Additional Tasks to Run After Daily Task"
    ECHO = "Farm Nightmare Nest for Daily Echo"
    AUTO = "Auto Farm all Nightmare Nest"

    print("[Auto Farm all Nightmare Nest: nests run]")
    check("in the additional tasks", _okww_nest_expected(automas({ADDS: [AUTO], ECHO: False})), True)

    print("\n[the daily-echo flag: only when the farm target is not Tacet Suppression]")
    check("flag on, farming Tacet (upstream skips the nest)",
          _okww_nest_expected(automas({ECHO: True, "Which to Farm": "Tacet Suppression", ADDS: []})), False)
    check("flag on, farming Forgery", _okww_nest_expected(automas({ECHO: True, "Which to Farm": "Forgery Challenge"})), True)
    check("flag absent = default on; target absent = default Tacet", _okww_nest_expected(automas({ADDS: []})), False)
    check("flag absent = default on, farming Simulation",
          _okww_nest_expected(automas({"Which to Farm": "Simulation Challenge"})), True)
    check("flag off, farming Forgery", _okww_nest_expected(automas({ECHO: False, "Which to Farm": "Forgery Challenge"})), False)

    print("\n[a leftover nest filter does not make nests run]")
    check("filter text, Auto Farm unticked, farming Tacet",
          _okww_nest_expected(automas({ECHO: True, ADDS: []}, {"Only Farm These Nests": "落渊南丘"})), False)

    print("\n[the config cannot be read: None, never a guess]")
    check("no automas dir", _okww_nest_expected(None), None)
    check("no DailyTask.json (only the nest config)",
          _okww_nest_expected(automas(None, {"Only Farm These Nests": "落渊南丘"})), None)

    print("\n[the verdict's 「cannot read the config」 item names the file that decides (item 19)]")
    import types

    from ark_relay.features.alarm import verdict

    seen = {}
    real_judged = verdict._judged
    verdict._judged = lambda rec, checks, *a, **k: seen.setdefault("checks", checks)
    try:
        log = tmpdir() / "OK-WW.log"
        log.write_text("Daily Task Completed\n", encoding="utf-8")
        rec = types.SimpleNamespace(script="OK-WW", log_path=log)
        eng = types.SimpleNamespace(cfg=types.SimpleNamespace(automas_dir=automas(None, {"Only Farm These Nests": "x"})))
        verdict._verify_outcome(eng, rec)
    finally:
        verdict._judged = real_judged
    detail = next((c.detail for c in seen.get("checks", []) if c.label == "能读到 OK-WW 生效中的配置"), "")
    check("names DailyTask.json", "DailyTask.json" in detail, True)
    check("no longer names NightmareNestTask.json", "NightmareNestTask.json" in detail, False)

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_nest_fought_then_full():
    """A nest fought until full is 「fought」, not 「full, skipped」 (audit 2026-10-13 item 11).

outcome.nest_state checked 「指定点位都已打满，跳过」 before the fight lines, so the
usual morning run - fight the nest, then find every chosen nest full - was
reported as a skip: verdict 「残象聚落（已满，跳过）」 and step 「残象聚落（已刷满）」
on every real run 10-06 .. 10-13 (machine-okww-logs). Only a run that found the
nests full before any fight is a skip.

    Formerly test_okww_nest_fought_then_full.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww as co, outcome


    T = "2026-10-13 09:27:{:02d},000 INFO TaskExecutor NightmareNestTask:{}"
    CLICK = T.format(34, "left_click 已击败残象：0/48 (1729, 348) after_sleep 2")
    FIGHT = T.format(46, "enter combat None")
    FULL = T.format(59, "nightmare nest: 指定点位都已打满，跳过（截图 nest_all_full）")

    print("[fought, then all full: fought]")
    both = "\n".join([CLICK, FIGHT, FULL])
    check("nest_state", outcome.nest_state(both), "fought")
    check("the step does not say 已刷满", "已刷满" in co._nest_step(both), False)
    got = [c for c in outcome.okww_checks(both, expect_nest=True) if c.label.startswith("残象聚落")]
    check("the verdict item", [(c.label, c.ok) for c in got], [("残象聚落", True)])

    print("\n[full before any fight: a skip]")
    check("nest_state", outcome.nest_state(FULL), "full")
    got = [c for c in outcome.okww_checks(FULL, expect_nest=True) if c.label.startswith("残象聚落")]
    check("the verdict item", [(c.label, c.ok) for c in got], [("残象聚落（已满，跳过）", True)])

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_nest_names():
    """「Only these nests」: the cap rule and the overlay's nest names, both must pass.

outcome.nest_filter_checks told nests apart by the denominator of 「已击败残象 N/D」
(more different caps than names asked for = a nest outside the setting). The
overlay now logs 「nightmare nest: nest name: <name>」 for each nest it enters, just
before the count box is clicked (「?」 when no name was read). With the filter on,
the overlay only clicks a row beside a wanted name and logs that name, so the names
alone never go red; 5352dfd8 let them replace the cap rule, which is what catches a
click on the neighbouring row (review 2026-10-13, item 17). Now both run: the cap
rule over every click, named or 「?」, and per wanted name no two different caps.

    Formerly test_okww_nest_names.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import outcome


    T = "2026-10-14 09:00:{:02d},000 INFO TaskExecutor NightmareNestTask:{}"


    def lines(*events, only="落渊南丘"):
        out = [T.format(0, f"nightmare nest: 只刷 {[n for n in only.split(',')]}")]
        for i, (kind, val) in enumerate(events, 1):
            out.append(T.format(i, f"left_click 已击败残象：0/{val} (1729, 347) after_sleep 2" if kind == "click"
                                else f"nightmare nest: nest name: {val}"))
        out.append(T.format(59, "enter combat None"))          # a fight, so the scope item is said
        return "\n".join(out) + "\n"


    def scope(text, only):
        return [(c.ok, c.detail) for c in outcome.nest_filter_checks(text, only) if c.label == "残象聚落没进别的点位"]


    print("[review case: two clicks both logged 落渊南丘, caps 48 and 41 -> red]")
    text = lines(("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41), ("name", "落渊南丘残象聚落"))
    got = scope(text, "落渊南丘")
    check("red", [ok for ok, _ in got], [False])
    check("says the two caps", "48、41" in (got[0][1] if got else ""), True)

    print("\n[real order (name, then click), both wanted nests: green]")
    text = lines(("name", "梦枢天罗残象聚落"), ("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41),
                 only="梦枢天罗,落渊南丘")
    check("green", [ok for ok, _ in scope(text, "梦枢天罗,落渊南丘")], [True])
    check("each click gets the name logged before it", outcome._nest_clicks(text),
          [("48", "梦枢天罗残象聚落"), ("41", "落渊南丘残象聚落")])

    print("\n[two wanted nests, a third click on the neighbouring 48 row under 落渊南丘's name: red]")
    text = lines(("name", "梦枢天罗残象聚落"), ("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41),
                 ("name", "落渊南丘残象聚落"), ("click", 48), only="梦枢天罗,落渊南丘")
    got = scope(text, "梦枢天罗,落渊南丘")
    check("red although only two caps in all", [ok for ok, _ in got], [False])
    check("names the name with two caps", "「落渊南丘」" in (got[0][1] if got else ""), True)

    print("\n[a 「?」 click still counts for the cap rule]")
    text = lines(("name", "落渊南丘残象聚落"), ("click", 41), ("name", "?"), ("click", 48))
    check("named 41 + unnamed 48 for one wanted name: red", [ok for ok, _ in scope(text, "落渊南丘")], [False])

    print("\n[old logs without name lines: the cap rule as before]")
    text = lines(("click", 48), ("click", 48))
    check("same cap twice: green", [ok for ok, _ in scope(text, "落渊南丘")], [True])
    text = lines(("click", 48), ("click", 41))
    check("two caps for one name: red", [ok for ok, _ in scope(text, "落渊南丘")], [False])

    print("\n[the Mac-side checkers pass the configured names, not a literal (10-15, alarm f7a4bb6a)]")
    # okww_effective.py and healthcheck.py passed 「落渊南丘」 after 2a7ff78d moved to two nests,
    # so the 10-15 09:20 run - 梦枢天罗 48 then 落渊南丘 41, exactly the setting - printed ❌.
    import re
    from ark_relay.core.mastercfg_okww import ONLY_NESTS
    text = lines(("name", "梦枢天罗残象聚落"), ("click", 48), ("name", "落渊南丘残象聚落"), ("click", 41),
                 only=",".join(ONLY_NESTS))
    check("the 10-15 run under the configured names: green", [ok for ok, _ in scope(text, ",".join(ONLY_NESTS))], [True])
    LIB = Path(__file__).resolve().parents[2] / "scripts" / "mac" / "lib"
    literal = re.compile(r"nest_filter_checks\(\s*[^,()]+,\s*([\"'])[^\"']*\1\s*\)")
    for name in ("okww_effective.py", "healthcheck.py"):
        src = (LIB / name).read_text(encoding="utf-8")
        check(f"{name} calls nest_filter_checks", "nest_filter_checks(" in src, True)
        check(f"{name}: no literal nest name passed to it", literal.findall(src), [])

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_nest_travel_retry():
    """A nest given up after two failed travels is 「not done」 in the verdict and the report, even when another nest was fought.

10-27 the 快速旅行 click on 梦枢天罗 took no effect (someone was connected over
TeamViewer at 09:22:44-09:23:51), the nest was cached as unreachable, 落渊南丘 was
fought, and nest_state read the fight and booked the run 「fought」: the report said
鸣潮 ran fine while one of the two nests he asked for was never farmed
(fixtures/okww-1027-nest-unreachable.log, the real task lines 09:22:58-09:25:32).

The overlay now retries a failed travel once and logs NEST_GAVE_UP_LINE only when the
second try fails too (test_okww_nest_v373.py); this is the relay reading that line.

    Formerly test_okww_nest_travel_retry.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.okww_patch import okww_overlay
    from ark_relay.features.verify import collector_okww as co, outcome


    REAL = (Path(__file__).resolve().parent / "fixtures" / "okww-1027-nest-unreachable.log").read_text(encoding="utf-8")
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    GAVE_UP = ns["NEST_GAVE_UP_LINE"]


    def verdict(text):
        got = [c for c in outcome.okww_checks(text, expect_nest=True, expect_daily=False, expect_stamina=False)
               if c.label == "残象聚落"]
        return (got[0].ok, got[0].detail) if got else None


    def after(text, at, msg):
        """`text` with one NightmareNestTask line inserted before the line stamped `at`."""
        line = f"2026-10-27 {at},000 INFO TaskExecutor NightmareNestTask:{msg}\n"
        i = text.index(f"2026-10-27 {at}")
        return text[:i] + line + text[i:]


    print("[the real 10-27 log, before the overlay retried: booked 「fought」 - the gap]")
    check("nest_state", outcome.nest_state(REAL), "fought")
    check("no nest given up (the line did not exist yet)", outcome.nests_given_up(REAL), [])

    print("\n[retried and travelled: still 「fought」, nothing named]")
    retried = after(REAL, "09:25:05,676", "nightmare nest: 传送不过去，马上再试一次 go_nest:48:18")
    check("nest_state", outcome.nest_state(retried), "fought")
    check("verdict ok", verdict(retried), (True, "有进本/战斗记录"))
    check("step is the bare name", co._nest_step(retried), "残象聚落")

    print("\n[the second try failed too: 「partly」, red, the nest named]")
    both = after(retried, "09:25:18,365", f"{GAVE_UP}go_nest:48:18（梦枢天罗残象聚落）")
    check("the relay's pattern reads the overlay's own line", outcome.nests_given_up(both), ["梦枢天罗残象聚落"])
    check("nest_state", outcome.nest_state(both), "partly")
    check("verdict red, names the nest", verdict(both),
          (False, "有一处点位传送两次都不过去，那一处没打（梦枢天罗残象聚落）"))
    check("step says which one was not farmed", co._nest_step(both), "残象聚落（有一处传送两次都不过去，那一处没打）（梦枢天罗残象聚落）")

    print("\n[given up and nothing else fought: 「unreachable」 as before]")
    alone = REAL[:REAL.index("2026-10-27 09:25:05,676")] + f"2026-10-27 09:25:05,700 INFO TaskExecutor NightmareNestTask:{GAVE_UP}go_nest:48:18（梦枢天罗残象聚落）\n"
    check("nest_state", outcome.nest_state(alone), "unreachable")
    check("verdict red", verdict(alone)[0], False)

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_nest_v373():
    """OK-WW v3.7.3 changed find_nest; the 「only 落渊南丘」 filter must survive that and the next one.

10-03 upstream moved the nest list's OCR box from 0.13 to 0.25 and added a second,
scrolled page (go_nest_scroll). Our find_nest was pinned to the old body, so the
mornings of 10-04 and 10-05 skipped it: upstream picked the top 0/48 nest, called it
unreachable a second after clicking travel, left the map open, and died on
「can't find gray_book_boss」 (ok-script.log 10-05 10:35:14 - 10:35:22). The relay then
pushed 「这一轮没干完」 twice.

This runs upstream's real v3.7.3 NightmareNestTask (fixture, stored as shipped) against
the override:
* the pin matches v3.7.3, and a changed body is adapted to, not skipped;
* the box top is read from upstream (0.25), not hard-coded;
* a page without 南丘 is not an error - only 「no page had it」 is, once, at the end;
* after 「nightmare nest unreachable」 the map is closed once before the book is opened
  again - also inside the daily, where upstream replaces the nest task's ensure_main
  with a do-nothing lambda (v3.7.4 DailyTask.py:98-99), so ensure_main cannot do it.

    Formerly test_okww_nest_v373.py.
    """
    import re
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import texts
    from ark_relay.features.okww_patch import okww_overlay


    # The OK-WW the machine runs (test_gl_okww_contract.INSTALLED); v3.7.3/v3.7.4 body until 2026-11-02.
    UPSTREAM = (Path(__file__).resolve().parent / "gamesim" / "upstream" / "okww-v3.7.14-beta.2" / "src" / "task" / "NightmareNestTask.py.txt").read_text(encoding="utf-8")


    def upstream_class(text=UPSTREAM):
        """Upstream's NightmareNestTask, loaded from a real file so inspect.getsource works."""
        class WWOneTimeTask:
            def run(self):
                pass

            def tr(self, msg):          # ok-script's translation, English here
                return msg

        ok = types.ModuleType("ok")
        ok.Logger = types.SimpleNamespace(get_logger=lambda name: types.SimpleNamespace(info=lambda *a: None))
        combat = types.ModuleType("src.task.BaseCombatTask")
        combat.BaseCombatTask = type("BaseCombatTask", (), {})
        combat.CharRevivedException = type("CharRevivedException", (Exception,), {})
        onetime = types.ModuleType("src.task.WWOneTimeTask")
        onetime.WWOneTimeTask = WWOneTimeTask
        sys.modules.update({"ok": ok, "cv2": types.ModuleType("cv2"), "config": types.SimpleNamespace(config={}),
                            "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
                            "src.task.BaseCombatTask": combat, "src.task.WWOneTimeTask": onetime})
        ok.run_task = lambda *a, **kw: None
        path = tmpdir() / "NightmareNestTask.py"
        path.write_text(text, encoding="utf-8")
        mod = types.ModuleType("src.task.NightmareNestTask")
        mod.__file__ = str(path)
        exec(compile(text, str(path), "exec"), mod.__dict__)
        sys.modules["src.task.NightmareNestTask"] = mod
        return mod.NightmareNestTask


    def overlay():
        ns = {}
        exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
        for k in ("_applied", "_skipped", "_adapted"):
            ns[k].clear()
        ns["TaskDisabledException"] = type("TaskDisabledException", (Exception,), {})
        return ns


    class Box:
        def __init__(self, name, y, height=30):
            self.name, self.x, self.y, self.width, self.height = name, 889, y, 198, height

        def __repr__(self):
            return self.name


    def fake(cls, pages, ns, only="落渊南丘"):
        """A task whose screen is `pages[page]`; go_nest_scroll's click turns the page."""
        t = object.__new__(cls)
        t.config = {ns["ONLY_NESTS"]: only, "Which to Farm": ["Tacet Discord Nest"]}   # the master's value
        t.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        t._unreachable_nests, t._nest_deaths, t.queues = set(), {}, []
        t._nest_tab_of_current_nest = "go_nest"
        t.page, t.tops, t.events, t.errors, t.infos, t.fought = 0, [], [], [], [], []

        def ocr(x, y, to_x, to_y, match=None):
            t.tops.append(y)
            # Fresh boxes every read, as OCR gives: find_nest moves the one it returns.
            return [Box(b.name, b.y, b.height) for b in pages[t.page] if not match or match.search(b.name)]
        t.ocr = ocr
        t.open_boss_book = lambda name: setattr(t, "page", 0)
        t.click = lambda *a, **kw: setattr(t, "page", 1) if a and a[0] == 0.9730 else None
        t.openF2Book = lambda name: t.events.append("book")
        t.ensure_main = lambda time_out=0: t.events.append("main")
        t.log_info = lambda msg, notify=False: t.infos.append(msg)
        t.log_error = lambda msg, notify=False: t.errors.append(msg)
        t.sleep = lambda s: None
        t.width_of_screen = lambda f: f * 1920
        t.height_of_screen = lambda f: f * 1080
        t.combat_nest = lambda nest: t.fought.append(nest.cache_key)
        return t


    Nest = upstream_class()
    ns = overlay()

    print("\n[钉的是 v3.7.3 的 find_nest]")
    check("上游（机器上装的版本）find_nest 的哈希就是我们钉的", ns["_src_sha"](Nest.find_nest), ns["_NEST_FIND_SHA"])
    check("识字区上沿从上游读出来是 0.25", ns["_upstream_nest_top"](Nest.find_nest), 0.25)
    ns["_install_nest"]()
    check("find_nest 换上了", "NightmareNestTask.find_nest" in ns["_applied"])
    check("没有跳过的", ns["_skipped"], [])
    check("也没有要适配的", ns["_adapted"], [])

    # 南丘 (/41) is the second row since 3.7; a new /48 nest sits on top (10-05 10:35:14 read 0/48 at y=374).
    NAME_NEW, NAME_NANQIU = Box("新区残象聚落", 300), Box("落渊南丘残象聚落", 450)


    def page1(nanqiu):
        return [NAME_NEW, Box("已击败残象：0/48", 374), NAME_NANQIU, Box(f"已击败残象：{nanqiu}", 524)]


    PAGE2 = [Box("别的残象聚落", 300), Box("已击败残象：3/24", 374)]

    print("\n[南丘没满：只进南丘，不碰上面那个 0/48]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns)
    t.run()
    check("打了一局", len(t.fought), 1)
    check("进的是 /41 那一行（南丘）", ":41:" in (t.fought or [""])[0])
    check("识字区一律用 0.25", set(t.tops), {0.25})
    check("no extra ensure_main between the books when nothing was unreachable", t.events[:3], ["main", "book", "book"])
    check("计数没涨就不再进", any("no progress after an attempt" in m for m in t.infos))
    check("没报错", t.errors, [])

    print("\n[南丘满了：第二屏没有南丘也不报错]")
    t = fake(Nest, [page1("41/41"), PAGE2], ns)
    t.run()
    check("一局没打", t.fought, [])
    check("说了已打满", any("指定点位都已打满" in m for m in t.infos))
    check("第二屏找不到南丘不算错", t.errors, [])

    print("\n[两屏都没有南丘：结束时报一次]")
    t = fake(Nest, [[NAME_NEW, Box("已击败残象：0/48", 374)], PAGE2], ns)
    t.run()
    check("一局没打", t.fought, [])
    check("只报一次", len(t.errors), 1)
    check("报的是列表里没找到", "列表里没找到指定的点位" in (t.errors or [""])[0])

    print("\n[上游下次再改 find_nest：照样换上并按新版读识字区，不跳过]")
    changed = UPSTREAM.replace("counts = self.ocr(0.35, 0.25, 1, 0.96, match=self.count_re)",
                               "counts = self.ocr(0.35, 0.3, 1, 0.96, match=self.count_re)  # moved again")
    check("样本确实改到了", changed != UPSTREAM)
    Nest2 = upstream_class(changed)
    ns2 = overlay()
    ns2["_install_nest"]()
    check("find_nest 仍然换上了", "NightmareNestTask.find_nest" in ns2["_applied"])
    check("记在「已适配」里", [a["what"] for a in ns2["_adapted"]], ["NightmareNestTask.find_nest"])
    check("不在「没贴上」里", ns2["_skipped"], [])
    t = fake(Nest2, [page1("10/41"), PAGE2], ns2)
    t.run()
    check("识字区跟着上游改成 0.3", set(t.tops), {0.3})
    check("照样只进南丘", ":41:" in (t.fought or [""])[0])

    print("\n[进点位和传送不过去都留图（中继二 10-05 23:3x）]")
    check("进点位、传送两处都换上了", all(x in ns["_applied"] for x in (
        "NightmareNestTask.combat_nest", "NightmareNestTask._travel_to_nest_or_skip")))
    t = fake(Nest, [page1("10/41"), PAGE2], ns)
    del t.combat_nest
    t.shots, t.backs = [], []
    t.screenshot = lambda name: t.shots.append(name)
    t.wait_feature = lambda *a, **kw: (_ for _ in ()).throw(Exception("wait_feature timeout"))
    try:
        Nest.combat_nest(t, Box("落渊南丘残象聚落", 450))
    except Exception:  # noqa: BLE001 - the fake wait times out, as upstream's does
        pass
    check("点进点位前截了列表", t.shots[:1], ["nest_go"])
    check("日志说了点进点位", any("点进点位" in m for m in t.infos))
    t.shots = []
    t.wait_until = lambda *a, **kw: None          # no 快速旅行 button: unreachable
    t.back = lambda after_sleep=0: t.backs.append(1)
    nest = types.SimpleNamespace(cache_key="落渊南丘:41:450")
    check("传送不过去照上游返回 False", Nest._travel_to_nest_or_skip(t, nest), False)
    check("传送前后各一张图", t.shots, ["nest_travel", "nest_unreachable"])
    check("上游那句 unreachable 照样写", any("nightmare nest unreachable" in m for m in t.infos))
    check("我们那句「传送不过去」也写了（日报靠它核这层在跑）", any("nightmare nest: 传送不过去" in m for m in t.infos))

    print("\n[find_nest 根本换不上：这一轮不刷，绝不按上游刷全部]")
    gone = UPSTREAM.replace("    def find_nest(self):", "    def find_nest_renamed(self):")
    Nest3 = upstream_class(gone)
    Nest3.find_nest = Nest3.find_nest_renamed
    del Nest3.find_nest
    ns3 = overlay()
    ns3["_install_nest"]()
    check("find_nest 记为没贴上", [s["what"] for s in ns3["_skipped"]], ["NightmareNestTask.find_nest"])
    check("原因说的是方法没了，不是上沿读不出", ["没有这个方法了" in s["why"] for s in ns3["_skipped"]], [True])
    t = fake(Nest3, [page1("10/41"), PAGE2], ns3)
    t.run()
    check("一局没打", t.fought, [])
    check("说了这一轮不刷", any("这一轮不刷巢穴" in m for m in t.infos))

    print("\n[上游的识字区上沿读不出来：不猜 0.25，记为没贴上进群，这一轮不刷]")
    # 10-03 v3.7.3 moved the box from 0.13 to 0.25 and an unreachable 0/48 nest was clicked
    # without a word. A guessed top is that failure again, so an unreadable or implausible
    # one keeps find_nest out and goes through the not-applied report like any skip.
    OCR_LINE = "counts = self.ocr(0.35, 0.25, 1, 0.96, match=self.count_re)"
    unreadable = UPSTREAM.replace(OCR_LINE, "box = (0.35, 0.25, 1, 0.96)\n"
                                  "        counts = self.ocr(*box, match=self.count_re)")
    too_low = UPSTREAM.replace(OCR_LINE, "counts = self.ocr(0.35, 0.7, 1, 0.96, match=self.count_re)")
    check("样本确实改到了", unreadable != UPSTREAM and too_low != UPSTREAM)
    for label, text in (("正则对不上", unreadable), ("读到的值不像样（0.7）", too_low)):
        Nest4 = upstream_class(text)
        ns4 = overlay()
        check(f"{label}：读不出上沿", ns4["_upstream_nest_top"](Nest4.find_nest), None)
        ns4["_install_nest"]()
        check(f"{label}：find_nest 没换上", "NightmareNestTask.find_nest" in ns4["_applied"], False)
        check(f"{label}：记为没贴上", [s["what"] for s in ns4["_skipped"]], ["NightmareNestTask.find_nest"])
        check(f"{label}：不记为已适配", ns4["_adapted"], [])
        check(f"{label}：别的巢穴改动照样换上", all(x in ns4["_applied"] for x in (
            "NightmareNestTask.run", "NightmareNestTask.get_nest_to_go")))
        t = fake(Nest4, [page1("10/41"), PAGE2], ns4)
        t.run()
        check(f"{label}：一局没打", t.fought, [])
        check(f"{label}：没拿任何上沿去识字（不猜 0.25）", t.tops, [])
        check(f"{label}：说了这一轮不刷", any("这一轮不刷巢穴" in m for m in t.infos))
        # The existing not-applied path, end to end: the overrides' own report file ->
        # okww_overlay.report_line -> the boot push title (boot_stages: alert=True, group).
        report = tmpdir() / "ark-okww-overlay.json"
        real_os, real_report = ns4["os"], okww_overlay.REPORT
        ns4["os"], ns4["REPORT"] = types.SimpleNamespace(name="nt"), str(report)
        try:
            ns4["_write_report"]()
        finally:
            ns4["os"] = real_os
        okww_overlay.REPORT = report
        try:
            line = okww_overlay.report_line()
        finally:
            okww_overlay.REPORT = real_report
        check(f"{label}：开机推送里有 find_nest 没贴上",
              "没贴上" in line and "NightmareNestTask.find_nest" in line and "上沿" in line)
        check(f"{label}：推送标题是没贴上", texts.patches(1, [line]), "⚠️ OK-WW 补丁有 1 条没贴上（共 1 条）")

    print("\n[daily: ensure_main is upstream's no-op lambda; an unreachable nest leaves the map open -> one back before the book]")
    ns5 = overlay()
    ns5["_install_nest"]()
    t = fake(Nest, [page1("10/41"), PAGE2], ns5)
    t.ensure_main = lambda *a, **kw: None            # DailyTask.py:99, verbatim shape
    t.world, t.shots = False, []
    t.in_team_and_world = lambda: t.world


    def _back(after_sleep=0):
        t.events.append("back")
        t.world = len([e for e in t.events if e == "back"]) >= 2   # upstream's back, then ours


    t.back = _back
    t.screenshot = lambda name: t.shots.append(name)
    t.find_one = lambda *a, **kw: None
    t._find_travel_button = lambda: None
    t.wait_until = lambda cond, **kw: None if cond == t._find_travel_button else cond()
    nest = types.SimpleNamespace(cache_key="落渊南丘:41:450")
    check("travel fails as upstream's does", Nest._travel_to_nest_or_skip(t, nest), False)
    check("upstream's own back ran, the map is still open", (t.events, t.world), (["back"], False))
    Nest.get_nest_to_go(t)
    check("one more back, then the book", t.events[:3], ["back", "back", "book"])
    check("no picture of a stuck map", "nest_map_still_open" in t.shots, False)

    print("\n[the world is already on screen after the unreachable nest -> no back (it would open the game menu)]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns5)
    t.ensure_main = lambda *a, **kw: None
    t.in_team_and_world = lambda: True
    t.back = lambda after_sleep=0: t.events.append("back")
    t._ark_close_map = True
    Nest.get_nest_to_go(t)
    check("straight to the book", t.events[:1], ["book"])

    print("\n[the back did not bring the world back -> picture and a log line, the book is tried anyway]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns5)
    t.ensure_main = lambda *a, **kw: None
    t.in_team_and_world = lambda: False
    t.back = lambda after_sleep=0: t.events.append("back")
    t.wait_until = lambda cond, **kw: cond()
    t.shots = []
    t.screenshot = lambda name: t.shots.append(name)
    t.box_of_screen = lambda *a: a
    t.ocr = lambda *a, **kw: []
    t._ark_close_map = True
    Nest.get_nest_to_go(t)
    check("one back, then the book", t.events[:2], ["back", "book"])
    check("picture of the stuck map", t.shots, ["nest_map_still_open"])
    check("said so in the log", any("关了一次地图，还是没回到大世界" in m for m in t.infos))

    print("\n[nothing unreachable -> get_nest_to_go never presses back]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns5)
    t.in_team_and_world = lambda: False
    t.back = lambda after_sleep=0: t.events.append("back")
    Nest.get_nest_to_go(t)
    check("no back", "back" in t.events, False)

    print("\n[the nest clicked is logged by name as well as by key: 「nightmare nest: nest name: <name>」]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns)
    t.run()
    key = t.fought[0]
    t.shots = []
    t.screenshot = lambda name: t.shots.append(name)
    t.wait_feature = lambda *a, **kw: (_ for _ in ()).throw(Exception("wait_feature timeout"))
    try:
        Nest.combat_nest(t, types.SimpleNamespace(cache_key=key))
    except Exception:  # noqa: BLE001 - the fake wait times out, as upstream's does
        pass
    check("the key line as before", any(m == f"nightmare nest: 点进点位 {key}（截图 nest_go）" for m in t.infos))
    check("the name line, as OCR read it beside the count",
          [m for m in t.infos if m.startswith("nightmare nest: nest name: ")], ["nightmare nest: nest name: 落渊南丘残象聚落"])
    check("the prefix is a constant the relay can import", ns["NEST_NAME_LINE"], "nightmare nest: nest name: ")
    t.infos = []
    try:
        Nest.combat_nest(t, types.SimpleNamespace(cache_key="go_nest:48:999"))
    except Exception:  # noqa: BLE001
        pass
    check("a key with no name read: 「?」", [m for m in t.infos if m.startswith("nightmare nest: nest name: ")],
          ["nightmare nest: nest name: ?"])

    print("\n[without the 只刷 filter the name is read too (one more read of the list), not 「?」]")
    t = fake(Nest, [page1("10/41"), PAGE2], ns, only="")
    t.run()
    key = t.fought[0]
    t.screenshot = lambda name: None
    t.wait_feature = lambda *a, **kw: (_ for _ in ()).throw(Exception("wait_feature timeout"))
    try:
        Nest.combat_nest(t, types.SimpleNamespace(cache_key=key))
    except Exception:  # noqa: BLE001
        pass
    check("no filter: the first row's name, 「新区残象聚落」", [m for m in t.infos if m.startswith("nightmare nest: nest name: ")],
          ["nightmare nest: nest name: 新区残象聚落"])

    print("\n[10-27: a travel that failed once is tried again at once; only a second failure gives the nest up]")
    # ok-script.log 10-27 09:23:00-09:25:18: 梦枢天罗 0/48 clicked, 快速旅行 at 09:23:03 took no
    # effect (TeamViewer connected 09:22:44-09:23:51), 「unreachable, skip this run」 at
    # 09:25:04, then 「skip cached unreachable nightmare nest: go_nest:48:18」 and 落渊南丘 only.
    NestTarget = sys.modules["src.task.NightmareNestTask"].NestTarget
    MENGSHU = [Box("梦枢天罗残象聚落", 300), Box("已击败残象：0/48", 374),
               Box("落渊南丘残象聚落", 450), Box("已击败残象：10/41", 524)]


    def travel_fake(ns_, results):
        """A nest run whose 快速旅行 works or not by `results`, in order (True = travelled; then always works)."""
        t = fake(Nest, [MENGSHU, PAGE2], ns_, only="梦枢天罗,落渊南丘")
        tries = iter(results)
        t.shots = []
        t.screenshot = lambda name: t.shots.append(name)
        t.in_team_and_world = lambda: True               # the map closed: no extra back
        t.back = lambda after_sleep=0: t.events.append("back")
        t._find_first_feature = lambda names, threshold: None
        t.find_one = lambda *a, **kw: None
        t.wait_in_team_and_world = lambda **kw: True
        # Upstream's travel: no 快速旅行 button found = unreachable, as a click that did nothing.
        t.wait_until = lambda cond, **kw: (Box("gray_teleport", 1007) if next(tries, True) else None) \
            if cond == t._find_travel_button else cond()
        t.combat_nest = lambda nest: t.fought.append(nest.cache_key) if Nest._travel_to_nest_or_skip(t, nest) else None
        return t


    ns6 = overlay()
    ns6["_install_nest"]()
    t = travel_fake(ns6, [False, True])
    t.run()
    mengshu = [k for k in t.fought if k.endswith(":48:18")]
    check("fail, then travel: 梦枢天罗 fought on the second try", len(mengshu), 1)
    check("落渊南丘 still fought after it", len(t.fought), 2)
    check("said it tries again", [m for m in t.infos if "马上再试一次" in m], [f"nightmare nest: 传送不过去，马上再试一次 {mengshu[0]}"])
    check("no give-up line", any(m.startswith(ns6["NEST_GAVE_UP_LINE"]) for m in t.infos), False)

    t = travel_fake(ns6, [False, False, True])
    t.run()
    check("fail twice: 梦枢天罗 not fought, 落渊南丘 still is", [k.split(":")[1] for k in t.fought], ["41"])
    gave_up = [m for m in t.infos if m.startswith(ns6["NEST_GAVE_UP_LINE"])]
    check("the give-up line names the nest", [m.endswith("（梦枢天罗残象聚落）") for m in gave_up], [True])
    check("then cached as upstream does", any("skip cached unreachable nightmare nest" in m for m in t.infos), True)
    check("tried exactly twice", sum("nightmare nest unreachable" in m for m in t.infos), 2)

    print("\n[the retry is per run: the next run tries again, then retries again]")
    t2 = travel_fake(ns6, [False, True])
    t2.__dict__.update(_ark_travel_retried={"go_nest:48:18"})   # left over from an earlier run
    t2.run()
    check("a new run starts with nothing retried", [k.split(":")[1] for k in t2.fought], ["48", "41"])

    print("\n[a nest whose travel failed once is not cached: its key and no-progress stamp are dropped]")
    t = travel_fake(ns6, [False])
    key = "go_nest:48:18"
    t._ark_nest_progress, t._ark_nest_tried, t._ark_travel_retried = {key: "0"}, {f"{key}@0"}, set()
    t._unreachable_nests.add(key)                          # what upstream does for a NestTarget
    check("travel fails as upstream's", Nest._travel_to_nest_or_skip(t, NestTarget(Box("x", 0), key)), False)
    check("un-cached", key in t._unreachable_nests, False)
    check("stamp dropped", t._ark_nest_tried, set())
    check("both pictures as before", t.shots, ["nest_travel", "nest_unreachable"])

    print("\n" +("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_no_challenge_window():
    """The no-challenge-button reason is told from the line of the same raise, by time.

collector_okww._okww_say turned 「Teleport to boss failed」 into the reason that the
challenge button never came when the overlay's 「找不到开启挑战」 line was within
3000 characters before the traceback header - a guess about stack lengths. On every
real log with both (2026-09-01 05:43, 06:35; fixtures/m6-okww/0921-weekly.log) the
line is 0.001-0.02 s before its header. Now: within 2 s before the header's own
timestamp (audit 2026-10-13 item 24, the rule of 29a44215 / bec95a17), the old
window only for a header line without a timestamp. Lines in upstream's format.

    Formerly test_okww_no_challenge_window.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww as co


    STACK = "".join(f'  File "x{i}.py", line {i}, in f\n    g()\n' for i in range(200))   # ~5.5 KB
    NO_BTN = "2026-09-21 10:20:58,624 INFO TaskExecutor FarmEchoTask:找不到开启挑战，整屏读到: [失坠困咎之庭_1.00]\n"


    def head(ts):
        return (f"2026-09-21 {ts} ERROR TaskExecutor FarmEchoTask:farm 4c error, try handle monthly card "
                "Traceback (most recent call last):\n")


    TAIL = "    raise RuntimeError('Teleport to boss failed') from e\nRuntimeError: Teleport to boss failed\n"
    SAY = "选了等级后没等到「开启挑战」"

    print("[the real fixture still reads as no challenge button]")
    real = (Path(__file__).resolve().parent / "fixtures" / "m6-okww" / "0921-weekly.log").read_text(encoding="utf-8")
    check("0921-weekly", SAY in co._okww_error(real), True)

    print("\n[the line 0.02 s before, but more than 3000 characters back: found]")
    text = NO_BTN + STACK + head("10:20:58,644") + TAIL
    check("found by time", SAY in co._okww_error(text), True)

    print("\n[the line a minute before, close in the text: another event]")
    text = NO_BTN.replace("10:20:58,624", "10:19:50,000") + head("10:20:58,644") + TAIL
    check("not this raise", SAY in co._okww_error(text), False)

    print("\n[header without a timestamp: the 3000-character window]")
    text = NO_BTN + " ERROR TaskExecutor FarmEchoTask:farm 4c error Traceback (most recent call last):\n" + TAIL
    check("near in the text: found", co._said_before(text, text.index(" ERROR"), co._NO_CHALLENGE), True)

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_weekly_boss_step():
    """周本要进 OK-WW 的步骤清单，否则「领满记账、周一恢复」永远触发不了。

2026-09-07：三趟各领一次（3/3→0），手动补跑碰上「次数已达上限」正常退出，
账本步骤里只有「无音区 ×1、残象聚落、周常乐园」，周本一个字没有，
handle 里找「4C声骸 已完成」自然找不到，周本状态一直是「本周还没领满」。

    Formerly test_okww_weekly_boss_step.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.core import collector


    d = tmpdir()
    def steps(text):
        f = d / "x.log"; f.write_text(text, encoding="utf-8")
        return collector.parse_okww_log(f).get("okww_steps") or []

    HEAD = "2026-09-07 11:28:57,378 INFO TaskExecutor FarmEchoTask:info_set Teleport to Boss Weekly Challenge 0\n"
    OCR = "2026-09-07 11:29:12,120 INFO TaskExecutor FarmEchoTask:周本本周剩余次数原文: [本周剩余可收取次数：{k}/3_0.99, x60_0.79]\n"
    CLAIM = "2026-09-07 10:00:32,309 INFO TaskExecutor FarmEchoTask:周本领奖：已点确认\n"
    CAP = "2026-09-07 11:31:04,847 INFO TaskExecutor FarmEchoTask:周本领奖：没认出领奖弹窗，整屏读到 [提示_1.00, 收取物资次数已达到上限，是否退出副本？_0.99, 退出副本_1.00]\n"
    ERR = "2026-09-07 10:00:43,366 ERROR TaskExecutor FarmEchoTask:farm 4c error, try handle monthly card Traceback (most recent call last):\n"

    # The overlay's read-back after a claim (format fixed with the overlay; see outcome.WEEKLY_CLAIM_OK).
    BACK = "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 {k}/3→{n}/3\n"
    SAME = "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读次数没变（{k}/3），这次没领到\n"
    UNREAD = "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读没读到本周剩余次数\n"
    LAND = "2026-09-07 10:06:50,862 INFO TaskExecutor FarmEchoTask:teleport_to_boss prepared as realm\n"
    FIGHT = "2026-09-07 10:06:52,779 INFO TaskExecutor FarmEchoTask:enter combat None\n"

    check("领满后进本：已完成、已领满", steps(HEAD + OCR.format(k=0) + CAP), ["周本（已完成，本周已领满）"])
    check("领了一次、回读确认：正常退出", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2)),
          ["周本（已完成，领了 1 次，本周还剩 2 次）"])
    check("领了一次但卡结算页（09-07 早）、回读确认", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2) + ERR),
          ["周本（领了 1 次，之后出错，原因见失败于）"])

    print("\n[「已点确认」只是点了，回读确认才算领到]")
    check("旧日志只有「已点确认」：不算领到、不写已完成", steps(HEAD + OCR.format(k=3) + CLAIM),
          ["周本（点了确认 1 次、领完没再读次数，没核实领到）"])
    check("旧日志只有「已点确认」又出错（09-07 早的原样）", steps(HEAD + OCR.format(k=3) + CLAIM + ERR),
          ["周本（点了确认 1 次、领完没再读次数，没核实领到，之后出错，原因见失败于）"])
    check("回读次数没变：没领到", steps(HEAD + OCR.format(k=2) + CLAIM + SAME.format(k=2)),
          ["周本（领完再读次数没变 1 次，没领到）"])
    check("回读没读到：不算领到", steps(HEAD + OCR.format(k=2) + CLAIM + UNREAD),
          ["周本（领完再读没读到剩余次数 1 次，没核实领到）"])
    check("一次确认、一次没变：领了 1 次另说那次", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2) + CLAIM + SAME.format(k=2)),
          ["周本（已完成，领了 1 次，本周还剩 2 次；另有领完再读次数没变 1 次，没领到）"])

    print("\n[剩余次数没读到不等于领满]")
    # A verified claim with no counter reading anywhere: unknown, never 「本周已领满」.
    no_read = HEAD + CLAIM + "2026-09-07 10:00:35,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 ?/3→?/3\n"
    check("这种行不会被当成回读确认", steps(no_read), ["周本（点了确认 1 次、领完没再读次数，没核实领到）"])
    from ark_relay.features.verify import outcome
    orig = outcome.weekly_left
    outcome.weekly_left = lambda text: None
    try:
        check("领到了但读不到剩余：说没读到，不说领满", steps(HEAD + CLAIM + BACK.format(k=3, n=2)),
              ["周本（已完成，领了 1 次，本周剩余次数没读到）"])
    finally:
        outcome.weekly_left = orig

    print("\n[没有开打的记录就不说「打了」]")
    check("打了没领（有 enter combat）", steps(HEAD + OCR.format(k=3) + LAND + FIGHT), ["周本（打了，没领到奖励）"])
    check("进了本没打（10-05 早：只有 prepared as）", steps(HEAD + OCR.format(k=3) + LAND), ["周本（进了本，没打起来，没领到奖励）"])
    check("没进本", steps(HEAD + OCR.format(k=3)), ["周本（没进本，一次没打）"])
    # Real line, replay 2026-09-01 OK-WW-06-58-23 (11:01:39): used to read 「打了，没领到奖励」.
    NOWAVE = "2026-09-01 11:01:39,518 INFO TaskExecutor FarmEchoTask:波片不足挡住开启挑战，点取消跳过本次周本\n"
    check("波片不够跳过：说奖励没领、没打", steps(HEAD + OCR.format(k=1) + NOWAVE), ["周本（奖励没领：结晶波片不足，这一趟没打）"])
    # On 2026-10-06 the overlay also ended the run as failed right after the skip line
    # (since 2026-10-07 it ends as skipped, _skip_short); old logs keep that line.
    # Constructed from that day's click_team_challenge wording.
    NOWAVE_END = ("2026-09-01 11:01:40,000 ERROR TaskExecutor FarmEchoTask:这一趟按失败结束：周本：结晶波片不够领奖"
              "（游戏提示「结晶波片不足，无法获取奖励」），点了取消，这一趟没打\n")
    check("波片不够跳过＋按失败结束：日报同一行", steps(HEAD + OCR.format(k=1) + NOWAVE + NOWAVE_END),
          ["周本（奖励没领：结晶波片不足，这一趟没打）"])
    check("领到一次后波片不够：日报说剩下的没领", steps(HEAD + OCR.format(k=3) + CLAIM + BACK.format(k=3, n=2) + NOWAVE + NOWAVE_END),
          ["周本（已完成，领了 1 次，本周还剩 2 次；剩下的奖励没领：结晶波片不足）"])
    check("没开周本就不写", steps("2026-09-07 11:34:06,670 INFO TaskExecutor DailyTask:open_daily\n"), [])
    check("剩余 0 次、没弹上限对话（09-02 的样本）：也算已领满", steps(HEAD + OCR.format(k=0)), ["周本（已完成，本周已领满）"])

    print("\n[周常乐园：上游现在记的是中文「乐园任务完成, 已达到上限」（GardenTask.run，2026-09-14 读的源码）]")
    G = "2026-09-14 10:02:11,001 INFO TaskExecutor GardenTask:Garden current: [Box(name='2000/2000')]\n"
    check("做完了（中文）", steps(G + "2026-09-14 10:02:12,001 INFO TaskExecutor GardenTask:乐园任务完成, 已达到上限\n"), ["周常乐园（本周已完成）"])
    check("做完了（旧英文）", steps("x GardenTask:weekly garden already completed\n"), ["周常乐园（本周已完成）"])
    # Only the counter read, no 「乐园任务完成」: not shown as done (2026-10-05 evidence rule).
    check("跑了但没有完成那句：不算完成", steps(G), ["周常乐园（没读到做完，不算完成）"])


def _part_okww_weekly_entry_paths():  # noqa: C901 - the whole body of the file this part was
    """Weekly boss entry: one path that looks at every screen, for every screen seen so far.

The entry broke one shape at a time: first only the plain entry was known, then a
「限时提前开放」 spoiler dialog that dropped us in the arena (2026-09-09 天傀劫煞),
then a dialog that opened the boss's level page (2026-10-05 22:05, 天演溯心) - which
the 10-05 morning run took for the arena and the 22:05 run walked the open world
for. This file runs every known screen through the real overlay, upstream's own
call order around it, and the real text the game showed:

  (a) dialog -> level page   ok-script.log 2026-10-05 22:17:26 / 22:17:31
  (b) dialog -> arena        bosstip.py (2026-09-09)
  (c) no dialog -> level page   tests/replay/2026-09-07/wuwa/OK-WW-06-00-55.log:160-168
  (c') the travel / team screen comes after upstream's 10 s
  anything else -> screenshot, the screen's text in the log, stop; never a walk

and the two deliberate stops on the way in: 0/3 claims left, short on waveplates.

    Formerly test_okww_weekly_entry_paths.py.
    """
    import types

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.okww_patch import okww_overlay


    class Disabled(Exception):
        """ok.TaskDisabledException."""


    class Revived(Exception):
        """src.task.BaseCombatTask.CharRevivedException."""


    class _Any(type):
        """A stand-in upstream class: any method _install_hooks reads exists and does nothing."""
        def __getattr__(cls, name):
            if name.startswith("__"):
                raise AttributeError(name)

            def anything(self, *a, **kw):
                return None
            return anything


    class BaseWWTask(metaclass=_Any):
        def click_on_book_target(self, serial_number, total_number, structure=None):
            # Upstream (v3.7.3 BaseWWTask.py:1070-1112): click 前往, then wait 10 s for
            # the travel or team screen; True means the team screen.
            self.events.append("book")
            if self.book == "team":
                return True
            raise Exception("wait_feature timeout")

        # Upstream v3.7.3 BaseWWTask.py:1115-1117, verbatim: the overlay replaces it
        # only while its source still hashes to the pin.
        def click_team_challenge(self):
            self.wait_click_feature('team_start_challenge', raise_if_not_found=True, click_after_delay=0.5, after_sleep=1)
            self.wait_click_skip_dialog_confirm()


    class FarmEchoTask(BaseWWTask):
        def teleport_to_configured_boss(self):
            # Upstream v3.7.4 FarmEchoTask.py:273-308, reduced to the steps after the book.
            is_team = self.click_on_book_target(1, 4)
            self.events.append("after-book")
            if is_team:
                if self.config.get('Teleport to Boss', 'No') == 'Weekly Challenge':
                    self.click_configured_boss_level()
                    self.click_solo_challenge()
                self.click_team_challenge()
            else:
                self.realm_entry_at_heal_point = False
                self.events.append("travel")
            self.wait_in_team_and_world(time_out=120)
            self.sleep(2)
            return is_team

        def teleport_to_configured_boss_and_prepare(self):
            # Upstream v3.7.3 FarmEchoTask.py:243-266, reduced.
            try:
                if self.teleport_to_configured_boss():
                    walk = "realm"
                else:
                    walk = self.walk_after_boss_teleport()
            except Exception as e:
                raise RuntimeError("Teleport to boss failed") from e
            self.prepared = walk

        def walk_after_boss_teleport(self):
            self.events.append("walk")
            return "realm"

        def click_configured_boss_level(self):
            # Upstream's level click; the overlay reads the claims left before it.
            if getattr(self, "level_missing", False):
                raise RuntimeError("Can not find boss level 80")   # upstream's own raise (:370)
            self.events.append("level")

        # Upstream v3.7.4 FarmEchoTask.py:374-378, verbatim.
        def click_solo_challenge(self):
            self.click(0.880, 0.911, after_sleep=2)
            self.wait_click_skip_dialog_confirm(time_out=1)

        def combat_once(self, wait_combat_time=200, raise_if_not_found=True, target=False):
            if self.revive:
                raise Revived()
            return self.combat

        def incr_drop(self, dropped):
            self.events.append("incr")


    mods = {
        "ok": types.SimpleNamespace(TaskDisabledException=Disabled,
                                    Logger=types.SimpleNamespace(get_logger=lambda n: types.SimpleNamespace(
                                        info=lambda *a, **k: None, error=lambda *a, **k: None))),
        "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
        "src.task.BaseCombatTask": types.SimpleNamespace(CharRevivedException=Revived),
        "src.task.BaseWWTask": types.SimpleNamespace(BaseWWTask=BaseWWTask),
        "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=FarmEchoTask),
    }
    for name in ("DailyTask", "ForgeryTask", "SimulationTask", "TacetTask"):
        mods[f"src.task.{name}"] = types.SimpleNamespace(**{name: _Any(name, (), {})})
    _saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    ns = {}
    # Loading the file installs everything it can, as on the machine; the nest part
    # finds no NightmareNestTask here and stops the chain before the claim, so the
    # claim is installed by hand - once, or the wrappers would wrap each other.
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    if "FarmEchoTask.incr_drop" not in ns["_applied"]:
        ns["_install_claim"]()
    check("进本这几处都换上了", all(x in ns["_applied"] for x in (
        "BaseWWTask.click_on_book_target", "FarmEchoTask.teleport_to_configured_boss",
        "FarmEchoTask.click_configured_boss_level", "FarmEchoTask.combat_once", "FarmEchoTask.incr_drop")))
    check("开启挑战那段的钉值对得上上游 3.7.3 原文（daeaf5a0f809）",
          "FarmEchoTask.click_team_challenge" in ns["_applied"])
    check("不再有「认不出就去大世界走路」那条", "_EarlyLanded" in ns, False)

    # Real text. ok-script.log 2026-10-05 22:17:26 (the dialog box) and 22:17:31 (the
    # whole screen after 确认, as logged - the first 300 characters).
    DIALOG = ["Box(name='提前到达目标位置可能影响剧情体验，是否确认前往？', x=600, y=502, width=693, height=33, confidence=99)"]
    LEVEL_PAGE = ("Box(name='定序诸理之律', x=102, y=52, width=168, height=33, confidence=100) "
                  "Box(name='136', x=1326, y=42, width=72, height=43, confidence=100) "
                  "Box(name='0/240+', x=1584, y=40, width=254, height=45, confidence=97) "
                  "Box(name='推荐等级40', x=206, y=169, width=150, height=39, confidence=100) Box(name='天演溯心', x=121")
    LEFT_2 = ["本周剩余可收取次数：2/3_1.00", "x60_0.79"]          # replay 09-07 :160
    LEFT_1 = ["本周剩余可收取次数：1/3_1.00", "x60_0.79"]          # ok-script.log 10-05 22:17:31
    LEFT_0 = ["本周剩余可收取次数：0/3_1.00", "x60_0.79"]
    LOADING = ("", False, False)
    ARENA = ("Lv.90", True, True)
    WORLD = ("终端", True, False)


    class Late:
        name = "team_close"


    def task(book="dialog", looks=(LOADING,), left=LEFT_1, start=True, after=(), late=None):
        t = object.__new__(FarmEchoTask)
        t.events, t.logs, t.shots, t.waits, t.clicks = [], [], [], [], []
        t.book, t.looks, t.i, t.left, t.start, t.after, t.late = book, list(looks), 0, left, start, list(after), late
        t.combat, t.revive = True, False
        t.config = {"Teleport to Boss": "Weekly Challenge"}
        t._in_realm = True

        def look():
            return t.looks[min(max(t.i - 1, 0), len(t.looks) - 1)]

        def ocr(box=None, **kw):
            if box == (0.25, 0.40):
                return DIALOG if t.book == "dialog" else ["Box(name='传送', x=1, y=1)"]
            if box == (0.58, 0.80):
                return t.left
            if box == (0.20, 0.35):
                return t.after
            if box == (0.0, 0.0):
                t.i += 1
                return [look()[0]]
            return []
        t.ocr = ocr
        t.box_of_screen = lambda x, y, to_x, to_y: (x, y)
        t.in_team_and_world = lambda: look()[1]
        t.in_realm = lambda: look()[2]
        t.in_world = lambda: look()[1] and not look()[2]
        t.log_info = lambda msg, notify=False: t.logs.append(msg)
        t.log_error = lambda msg, notify=False: t.logs.append(msg)
        t.find_one = lambda *a, **kw: None          # no dialog after 开启挑战
        t.click_dialog_right_button = lambda: t.events.append("confirm")
        t.click_dialog_left_button = lambda: t.events.append("cancel")
        t.wait_in_team_and_world = lambda time_out=10, raise_if_not_found=True, esc=False: t.waits.append(time_out) or True
        t.screenshot = lambda name: t.shots.append(name)
        t.click = lambda *a, **kw: t.clicks.append(a)
        t.ensure_main = lambda time_out=30: t.events.append("main")

        def wait_feature(feature, **kw):
            if feature == "team_start_challenge":
                return t.start
            return t.late
        t.wait_feature = wait_feature

        def wait_click_feature(feature, **kw):
            if not t.start:
                raise Exception("no team_start_challenge")
            t.events.append("start")
        t.wait_click_feature = wait_click_feature
        t.wait_click_skip_dialog_confirm = lambda **kw: t.events.append("skip-confirm")
        t.wait_until = lambda cond, **kw: cond()
        t.walk_to_treasure = lambda: t.events.append("treasure")
        t.pick_f = lambda handle_claim=True: t.events.append("f")
        t.sleep = lambda s: None
        return t


    def entered(t):
        return [e for e in t.events if e in ("confirm", "level", "start", "walk", "travel")]


    def stopped(t):
        try:
            t.teleport_to_configured_boss_and_prepare()
        except ns["_ArkStop"]:
            # The overlay's own stop: FarmEchoTask.run ends the run as FAILED when a
            # reason was kept, as SKIPPED when none was (_skip_short).
            why = getattr(t, "_ark_failed", None)
            return f"fail: {why}" if why else "skip"
        except Disabled:
            return "skip"
        except RuntimeError as exc:
            return f"stop: {exc}"
        return "in"


    print("\n[(a) 有框→确认后是选等级页（10-05 22:17 天演溯心）：交回上游原路，选等级→单人挑战→开启挑战]")
    t = task(looks=[LOADING, (LEVEL_PAGE, False, False)])
    check("进了本", stopped(t), "in")
    check("点确认→选等级→开启挑战", entered(t), ["confirm", "level", "start"])
    check("单人挑战点的是上游那个位置", t.clicks, [(0.880, 0.911)])
    check("走的是上游开书之后的原路", "after-book" in t.events)
    check("当成已进本", t.prepared, "realm")
    check("加载慢一拍也等到了（看了两眼）", t.i, 2)
    check("截了选等级页", "early_open_team" in t.shots)
    check("说了是选等级页、框里读到什么", any("选等级页" in m for m in t.logs)
          and any("框里读到：" in m and "剧情体验" in m for m in t.logs))
    check("读了本周剩余次数", t._ark_weekly_left, 1)

    print("\n[(b) 有框→确认后直接在 Boss 场地里（09-09 天傀劫煞）：当已进本，不点选等级]")
    t = task(looks=[LOADING, LOADING, ARENA])
    check("进了本", stopped(t), "in")
    check("只点了确认", entered(t), ["confirm"])
    check("当成已进本", t.prepared, "realm")
    check("截了落地图", "early_open_landed" in t.shots)
    check("说了直接进场", any("直接进场" in m for m in t.logs))

    print("\n[the same arena drop reached from TacetTask / ForgeryTask (click_on_book_target is bound on BaseWWTask): no _EarlyOpen]")
    t = task(looks=[LOADING, LOADING, ARENA])
    t.config = {"Which Tacet Suppression to Farm": 1}
    try:
        got = t.click_on_book_target(1, 21, [4, 5, 5, 7])
    except ns["_EarlyOpen"]:
        got = "raised _EarlyOpen"
    check("returns upstream's team-screen answer, True", got, True)
    check("the boss teleport flag is not left set", getattr(t, "_ark_boss_teleport", False), False)

    print("\n[(c) 没有框（09-07 正常进本）：上游原路，选等级→单人挑战→开启挑战]")
    t = task(book="team", left=LEFT_2)
    check("进了本", stopped(t), "in")
    check("选等级→开启挑战，没点确认", entered(t), ["level", "start"])
    check("单人挑战点的是上游那个位置", t.clicks, [(0.880, 0.911)])
    check("读了本周剩余次数 2/3", t._ark_weekly_left, 2)
    check("没截认不出的图", "weekly_entry_unknown" in t.shots, False)

    print("\n[(c') 没有框、传送界面过了上游的 10 秒才来：多等 15 秒等到队伍界面，照常进本]")
    t = task(book="slow", late=Late())
    check("进了本", stopped(t), "in")
    check("选等级→开启挑战", entered(t), ["level", "start"])
    check("说了多等到了", any("多等 15 秒等到了" in m for m in t.logs))

    class Map:
        name = "fast_travel_custom"


    print("\n[有框→确认后是传送地图（09-09 868d09f5 处理过、cfdd4f04 丢了）：讨伐强敌按上游传送原路走]")
    t = task(late=Map())
    t.config = {"Teleport to Boss": "Boss Challenge"}
    check("进了本", stopped(t), "in")
    check("走的是上游传送那条（不是队伍界面）", entered(t), ["confirm", "travel", "walk"])
    check("截了地图", "early_open_map" in t.shots)

    print("\n[有框→周本却出了传送地图：周本没有地图这一屏，截图停下，不走路]")
    t = task(late=Map())
    check("停下了", stopped(t).startswith("stop:"))
    check("没走路", "walk" in t.events, False)
    check("截了认不出的图", "weekly_entry_unknown" in t.shots)

    print("\n[有框→确认后是队伍界面：按上游原路进本]")
    t = task(late=Late())
    check("进了本", stopped(t), "in")
    check("选等级→开启挑战", entered(t), ["confirm", "level", "start"])

    print("\n[有框→确认后落在大世界：认不出，截图停下，不走路]")
    t = task(looks=[LOADING, WORLD, WORLD, WORLD])
    got = stopped(t)
    check("停下了（上游的 Teleport to boss failed）", got.startswith("stop: Teleport to boss failed"))
    check("没去大世界走路", "walk" in t.events, False)
    check("没点选等级", "level" in t.events, False)
    check("截了认不出的图", "weekly_entry_unknown" in t.shots)
    check("日志写了认不出和整屏的字", any("认不出" in m and "终端" in m and "in_world=True" in m for m in t.logs))

    print("\n[有框→确认后两分钟都没认出的画面：截图停下]")
    t = task(looks=[("加载中", False, False)])
    check("停下了", stopped(t).startswith("stop:"))
    check("看满了两分钟（60 眼）", t.i, 60)
    check("截了认不出的图", "weekly_entry_unknown" in t.shots)
    check("没走路", "walk" in t.events, False)

    print("\n[没有框、多等 15 秒也没来：截图停下，不走路]")
    t = task(book="slow", late=None, looks=[("某个没见过的界面", False, False)])
    check("停下了", stopped(t).startswith("stop:"))
    check("截了认不出的图", "weekly_entry_unknown" in t.shots)
    check("日志写了整屏的字", any("认不出" in m and "某个没见过的界面" in m for m in t.logs))
    check("没走路", "walk" in t.events, False)

    print("\n[选等级页上读到 0/3：不进本，跳过（不算失败）]")
    t = task(looks=[LOADING, (LEVEL_PAGE, False, False)], left=LEFT_0)
    check("跳过", stopped(t), "skip")
    check("没点开启挑战", "start" in t.events, False)
    check("退回主界面", "main" in t.events)
    check("说了已领满", any("已领满（0/3）" in m for m in t.logs))

    class _At:
        """An OCR box with a place on the 1920x1080 screen."""
        def __init__(self, name, x, y):
            self.name, self.x, self.y, self.width, self.height = name, x, y, 40, 30

        def __str__(self):
            return f"Box(name='{self.name}', x={self.x}, y={self.y}, width=40, height=30, confidence=100)"


    # The reminder after 单人挑战 (v3.7.4 FarmEchoTask.py:375-376: 「无法获取奖励, 是否继续进入」;
    # the game's wording, docs/OKWW-WEEKLY-BOSS.md), over the top bar (backup, waveplates/240).
    REMINDER = "结晶波片不足，无法获取奖励，请确认是否继续进入？"


    def solo_dialog(t, wave, spare, text=REMINDER):
        """After the click on 单人挑战 a dialog is up, until 取消 or 确认 is clicked."""
        t.height_of_screen = lambda r: r * 1080
        t.dialog_up = False
        bar = ([_At(str(spare), 1208, 50)] if spare is not None else []) + \
              ([_At(f"{wave}/240", 1480, 50)] if wave is not None else [])
        screen = bar + [_At(text, 700, 500), _At("取消", 640, 700), _At("确认", 1280, 700)]
        base_ocr, base_click = t.ocr, t.click

        def ocr(box=None, **kw):
            if box == (0.0, 0.0) and t.dialog_up:
                return list(screen)
            return base_ocr(box=box, **kw)

        def click(*a, **kw):
            base_click(*a, **kw)
            if a[:2] == (0.880, 0.911):
                t.dialog_up = True

        def answer(name):
            t.events.append(name)
            t.dialog_up = False
        t.ocr, t.click = ocr, click
        t.find_one = lambda *a, **kw: "confirm-btn" if t.dialog_up else None
        t.click_dialog_left_button = lambda: answer("cancel")
        t.click_dialog_right_button = lambda: answer("confirm")
        return t


    print("\n[v3.7.4: after 单人挑战 the 「无法获取奖励」 reminder, waveplates 17 + backup 24 < 60 -> 取消, skipped as short]")
    t = solo_dialog(task(book="team"), 17, 24)
    check("skipped", stopped(t), "skip")
    check("no reason kept (a shortage, not a failure)", getattr(t, "_ark_failed", None), None)
    check("取消 clicked, never 确认, 开启挑战 never clicked", [e for e in t.events if e in ("cancel", "confirm", "start")], ["cancel"])
    check("upstream's confirm-and-tick never ran", "skip-confirm" in t.events, False)
    check("the shortage line the relay reads", any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))
    check("the two values in the log", any("顶栏读到波片 17/240，备用 24" in m for m in t.logs))
    check("picture", "nowave_dialog" in t.shots)
    check("no failed mark", any(ns["FAILED_MARK"] in m for m in t.logs), False)

    print("\n[the reminder with waveplates 41 + backup 24 >= 60 contradicts the game (it shows only when short) -> 取消, picture, stop]")
    t = solo_dialog(task(book="team"), 41, 24)
    got = stopped(t)
    check("stopped as failed, saying the read and the game disagree", got.startswith("fail:") and "读数和游戏对不上" in got)
    check("取消 clicked, never 确认, 开启挑战 never clicked", [e for e in t.events if e in ("cancel", "confirm", "start")], ["cancel"])
    check("no tick (upstream's wait_click_skip_dialog_confirm not called)", "skip-confirm" in t.events, False)
    check("picture of the dialog", "solo_dialog_contradicts" in t.shots)
    check("not the shortage line (not a skip)", any(m.startswith("结晶波片不足") for m in t.logs), False)

    print("\n[a dialog after 单人挑战 that is not the reminder -> picture, phone, stop; nothing clicked]")
    t = solo_dialog(task(book="team"), 41, 24, text="某个没见过的对话框")
    got = stopped(t)
    check("stopped as failed", got.startswith("fail:") and "认不出的对话框" in got)
    check("nothing answered, 开启挑战 not clicked", [e for e in t.events if e in ("cancel", "confirm", "start")], [])
    check("picture", "solo_dialog_unknown" in t.shots)

    print("\n[the reminder but the top bar is not read -> no blind 确认: picture, stop]")
    t = solo_dialog(task(book="team"), None, None)
    got = stopped(t)
    check("stopped as failed", got.startswith("fail:") and "顶栏的波片没读全" in got)
    check("nothing answered", [e for e in t.events if e in ("cancel", "confirm", "start")], [])
    check("picture", "solo_dialog_bar_unread" in t.shots)

    print("\n[no dialog after 单人挑战 -> straight on to 开启挑战, nothing answered]")
    t = task(book="team", left=LEFT_2)
    check("went in", stopped(t), "in")
    check("level, 开启挑战; no 确认/取消", entered(t), ["level", "start"])

    print("\n[echo farm on the weekly config (no-claim flag): upstream's click_solo_challenge runs, tick and all]")
    import tempfile
    flag = Path(tempfile.mkdtemp(prefix="ark-entry-")) / "ark-okww-farm.no-claim"
    flag.write_text("")
    real_flag, ns["NO_CLAIM"] = ns["NO_CLAIM"], str(flag)
    try:
        t = solo_dialog(task(book="team"), 17, 24)
        t.wait_click_skip_dialog_confirm = lambda **kw: t.events.append(f"skip-confirm {kw}")
        t.click_solo_challenge()
    finally:
        flag.unlink()
        flag.parent.rmdir()
        ns["NO_CLAIM"] = real_flag
    check("upstream's own: the click, then confirm-and-tick within 1 s",
          (t.clicks, [e for e in t.events if e.startswith("skip-confirm")]), ([(0.880, 0.911)], ["skip-confirm {'time_out': 1}"]))

    print("\n[echo farm (Boss Challenge): a 4C boss's level page has no weekly counter -> upstream's level click, no stop]")
    t = task(left=["Box(name='推荐等级50', x=206, y=169)"])
    t.config = {"Teleport to Boss": "Boss Challenge"}
    got = "on"
    try:
        t.click_configured_boss_level()
    except Exception as exc:  # noqa: BLE001 - the 10-13 bug: weekly_left_unread on the first realm boss
        got = f"stop: {exc!r} {getattr(t, '_ark_failed', None)}"
    check("not stopped", got, "on")
    check("upstream's level click ran", t.events, ["level"])
    check("no weekly screenshot, no weekly read", (t.shots, any("周本本周剩余次数原文" in m for m in t.logs)), ([], False))

    print("\n[echo farm (Boss Challenge) through the book onto the level page -> Boss Level picked, 单人挑战, then 开启挑战]")
    LEVEL_PAGE = ["Box(name='推荐等级80', x=206, y=169)", "Box(name='推荐等级90', x=206, y=609)", "Box(name='单人挑战', x=1650, y=980)"]


    def boss_challenge(screen, start_btn=False, missing=False):
        t = task(book="team")
        t.config = {"Teleport to Boss": "Boss Challenge", "Boss Level": "80"}
        base = t.ocr

        def ocr(box=None, **kw):
            if box == (0.0, 0.0):
                return list(screen)
            if box == (0.030, 0.113):
                return [b for b in screen if "推荐等级" in b]
            return base(box=box, **kw)
        t.ocr = ocr
        t.find_one = lambda feature, **kw: "start-btn" if start_btn and feature == "team_start_challenge" else None
        t.level_missing = missing
        t.wait_click_skip_dialog_confirm = lambda **kw: t.events.append("skip-confirm")
        return t


    t = boss_challenge(LEVEL_PAGE)
    check("went in", stopped(t), "in")
    check("level, then upstream's 单人挑战 (click and confirm-and-tick), then 开启挑战",
          ([e for e in t.events if e in ("level", "skip-confirm", "start")], (0.880, 0.911) in t.clicks),
          (["level", "skip-confirm", "start"], True))
    check("logged the level clicked and what the page listed",
          any(m.startswith("刷声骸选等级：选等级页点了 Lv.80。读到 ") and "推荐等级90" in m for m in t.logs))

    print("\n[echo farm (Boss Challenge) through the book onto a team screen with no level list -> logged once, on as upstream]")
    t = boss_challenge(["Box(name='开启挑战', x=1750, y=980)"], start_btn=True)
    check("went in", stopped(t), "in")
    check("no level click, no 单人挑战; 开启挑战", ([e for e in t.events if e in ("level", "skip-confirm", "start")],
                                              (0.880, 0.911) in t.clicks), (["start"], False))
    check("one line, with the screen", [m for m in t.logs if m.startswith("刷声骸选等级：")],
          ["刷声骸选等级：前往后是队伍界面（没有选等级页），不选等级，按游戏记住的等级进（设置 Lv.80）。"
           "整屏读到 Box(name='开启挑战', x=1750, y=980)"])

    print("\n[the level page without the configured level -> no raise: logged, 单人挑战, 开启挑战]")
    t = boss_challenge(LEVEL_PAGE, missing=True)
    check("went in", stopped(t), "in")
    check("单人挑战 and 开启挑战 still", [e for e in t.events if e in ("level", "skip-confirm", "start")], ["skip-confirm", "start"])
    check("said the level was not found", any("选等级页上没找到 Lv.80" in m for m in t.logs))

    print("\n[nothing known after 前往 -> logged once, on as upstream (no raise from here)]")
    t = boss_challenge(["Box(name='加载中', x=1, y=1)"])
    check("went in", stopped(t), "in")
    check("one 「认不出的画面」 line", sum(m.startswith("刷声骸选等级：前往后是认不出的画面") for m in t.logs), 1)

    print("\n[the weekly boss keeps upstream's own level and 单人挑战 calls: no second level pick]")
    t = solo_dialog(task(book="team", left=LEFT_2), 0, 0)
    t.find_one = lambda *a, **kw: None
    stopped(t)
    check("no 刷声骸选等级 line on the weekly path", any(m.startswith("刷声骸选等级") for m in t.logs), False)

    print("\n[周本的复活交给上游 do_run 重新传送]")
    # The weekly boss is not the echo farm, so the revive is upstream's tower revive and
    # the exception goes up to do_run (v3.7.3 FarmEchoTask.py:204-216); the in-place
    # revive that combat_once swallows is in test_okww_revive_and_retry.py.
    t = task()
    t.revive = True
    try:
        t.combat_once()
        went_up = False
    except Revived:
        went_up = True
    check("周本的复活往上抛给上游", went_up)

    # The coverage driver runs every test in one process: leave sys.modules as found.
    for k, v in _saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_okww_weekly_spend():
    """Verified weekly-boss claims count in 「消耗 波片」 (audit 2026-10-13 item 12).

okww_stamina_spent was summed only from the drops between get_stamina readings
(`info_set current_stamina`). The weekly claim does not take a reading, so its
60 waveplates per claim were missing: 10-12 11:41 (okww-task.sh 2) claimed three
times, read back 3->2->1->0, and the run showed no waveplates spent at all. Each
verified claim now adds 60, unless a drop between two readings already shows it.

    Formerly test_okww_weekly_spend.py.
    """

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ark_relay.features.verify import collector_okww as co


    def spent(*lines):
        p = tmpdir() / "OK-WW.log"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return co.parse_okww_log(p).get("okww_stamina_spent")


    def claim(before):
        return (f"2026-10-12 11:5{before},000 INFO TaskExecutor FarmEchoTask:"
                f"周本领奖：回读确认领到，本周剩余 {before}/3→{before - 1}/3")


    def reading(n, task="TacetTask"):
        return f"2026-10-12 11:40:00,000 INFO TaskExecutor {task}:info_set current_stamina {n}"


    print("[claims with no reading around them: 60 each]")
    check("three verified claims", spent(claim(3), claim(2), claim(1)), 180)

    print("\n[a claim between two readings whose drop shows it: not counted twice]")
    check("240 -> claim -> 180", spent(reading(240, "FarmEchoTask"), claim(3), reading(180, "FarmEchoTask")), 60)
    check("240 -> claim -> 240 (no drop shown): still 60", spent(reading(240), claim(3), reading(240)), 60)

    print("\n[stamina farm and claims in one run: both]")
    check("tacet 240 -> 120, then one claim", spent(reading(240), reading(120), claim(1)), 180)

    print("\n[a claim that did not read back as taken costs nothing here]")
    same = "2026-10-12 11:50,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读次数没变（2/3），这次没领到"
    check("unchanged count", spent(same), None)

    print("\n[a drop a little short of 60 is the claim plus regeneration (item 18)]")
    # review-C/wk.py: 100 -> claim -> 42 twelve minutes later reported 118.
    t = ("2026-10-14 09:00:00,000 INFO TaskExecutor TacetTask:info_set current_stamina 100\n"
         "2026-10-14 09:10:00,000 INFO TaskExecutor FarmEchoTask:周本领奖：回读确认领到，本周剩余 3/3→2/3\n"
         "2026-10-14 09:12:00,000 INFO TaskExecutor TacetTask:info_set current_stamina 42\n")
    check("100 -> claim -> 42: 58, not 118", spent(t), 58)


    def full(*lines):
        p = tmpdir() / "OK-WW.log"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return co.parse_okww_log(p)


    TOPUP = "2026-10-12 15:29:47,649 INFO TaskExecutor FarmEchoTask:周本领奖：波片不够，动用备用体力"
    print("\n[a claim topped up with backup: the backup is counted (item 18)]")
    bar = "2026-10-12 15:29:44,000 INFO TaskExecutor FarmEchoTask:周本领奖：顶栏读到波片 20/240，备用 100"
    got = full(bar, TOPUP, claim(3))
    check("top bar read: 20 waveplates, 40 backup", (got.get("okww_stamina_spent"), got.get("okww_backup_spent")), (20, 40))
    print("\n[10-12 15:29 / 15:31 shape: topped up, top bar not logged - said, not guessed]")
    got = full(claim(3), TOPUP, claim(2), TOPUP, claim(1))
    check("only the plain claim in 波片", got.get("okww_stamina_spent"), 60)
    check("the two topped-up claims counted as unread", got.get("okww_weekly_topup_unread"), 2)
    from datetime import datetime

    from ark_relay.core import ledger_rows
    cost = ledger_rows._block_okww(got, datetime(2026, 10, 12, 15, 33))[1]
    check("the daily report says so", any("另有周本领奖 2 次用备用体力补足" in c for c in cost), True)
    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


if __name__ == "__main__":
    sys.exit(run_parts([_part_okww_nest_capture, _part_okww_nest_expected, _part_okww_nest_fought_then_full, _part_okww_nest_names, _part_okww_nest_travel_retry, _part_okww_nest_v373, _part_okww_no_challenge_window, _part_okww_weekly_boss_step, _part_okww_weekly_entry_paths, _part_okww_weekly_spend]))
