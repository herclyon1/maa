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
"""
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.core import texts
from ark_relay.features.okww_patch import okww_overlay
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
    """Upstream's NightmareNestTask, loaded from a real file so inspect.getsource works."""
    class WWOneTimeTask:
        def run(self):
            pass

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
check("上游 v3.7.3 find_nest 的哈希就是我们钉的", ns["_src_sha"](Nest.find_nest), ns["_NEST_FIND_SHA"])
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
sys.exit(1 if fails else 0)
