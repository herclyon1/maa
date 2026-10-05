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
"""
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import collector_okww, okww_overlay, outcome
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


UPSTREAM = (Path(__file__).resolve().parent / "fixtures"
            / "okww-NightmareNestTask-v3.7.3.py.txt").read_text(encoding="utf-8")


def upstream_class(text=UPSTREAM):
    class WWOneTimeTask:
        def run(self):
            pass

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
sys.exit(1 if fails else 0)
