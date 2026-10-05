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
* after the first lap the book is reopened from the open world (ensure_main first).
"""
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import okww_overlay
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
check("第二次开书之前先回大世界", t.events[:4], ["main", "book", "main", "book"])
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

print("\n[find_nest 根本换不上：这一轮不刷，绝不按上游刷全部]")
gone = UPSTREAM.replace("    def find_nest(self):", "    def find_nest_renamed(self):")
Nest3 = upstream_class(gone)
Nest3.find_nest = Nest3.find_nest_renamed
del Nest3.find_nest
ns3 = overlay()
ns3["_install_nest"]()
check("find_nest 记为没贴上", [s["what"] for s in ns3["_skipped"]], ["NightmareNestTask.find_nest"])
t = fake(Nest3, [page1("10/41"), PAGE2], ns3)
t.run()
check("一局没打", t.fought, [])
check("说了这一轮不刷", any("这一轮不刷巢穴" in m for m in t.infos))

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
