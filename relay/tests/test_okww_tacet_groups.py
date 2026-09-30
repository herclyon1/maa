"""WuWa 3.7 put two tacet fields at the top of the F2 list; OK-WW still clicks by the old groups.

In-game read on 2026-09-30 (BOARD/evidence/鸣潮3.7-选项-0930/README.md): 沉心域 and
烬心域 now sit above 方擎西峰 under 瑝珑·梦州, so 「素材获取 → 无音清剿」 is grouped
4 / 5 / 5 / 7. Upstream v3.6.9-beta.1 still sets `self.structure = [2, 5, 5, 7]`
and click_on_book_target scrolls by that list, so every field from the fifth down
is clicked on the wrong row, and the last two raise IndexError outright.

The fix is an ok_tasks override, not a source edit (test_patch_inventory pins that
no upstream file is edited). This runs upstream's real TacetTask - the file as
shipped in v3.6.9-beta.1, stored as a fixture - against the override.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import okww_overlay, outcome

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


UPSTREAM = (Path(__file__).resolve().parent / "fixtures"
            / "okww-TacetTask-v3.6.9-beta.1.py.txt").read_text(encoding="utf-8")


def upstream_class(text=UPSTREAM):
    """Upstream's TacetTask with its base classes stubbed; click_on_book_target records its arguments."""
    clicks = []

    class Base:
        def __init__(self, *a, **kw):
            self.default_config = {}
            self.logs = []

        def log_info(self, msg):
            self.logs.append(msg)

        def info_set(self, key, value):
            pass

        def click_on_book_target(self, serial_number, total_number, structure=None):
            clicks.append((serial_number, total_number, list(structure)))
            return True

    ok = types.ModuleType("ok")
    ok.Logger = types.SimpleNamespace(get_logger=lambda name: None)
    combat = types.ModuleType("src.task.BaseCombatTask")
    combat.BaseCombatTask = type("BaseCombatTask", (), {})
    combat.CharRevivedException = Exception
    onetime = types.ModuleType("src.task.WWOneTimeTask")
    onetime.WWOneTimeTask = Base
    sys.modules.update({"ok": ok, "src": types.ModuleType("src"),
                        "src.task": types.ModuleType("src.task"),
                        "src.task.BaseCombatTask": combat,
                        "src.task.WWOneTimeTask": onetime})
    mod = types.ModuleType("src.task.TacetTask")
    exec(compile(text, "TacetTask.py", "exec"), mod.__dict__)
    sys.modules["src.task.TacetTask"] = mod
    return mod.TacetTask, clicks


def overlay():
    """A fresh copy of the overrides file. Its own install block fails here (no OK-WW) and is caught."""
    ns = {}
    exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
    ns["_applied"].clear()
    ns["_skipped"].clear()
    return ns


LAST = 20       # 无光之森, the 21st field in the 3.7 list

print("[上游原样：3.7 的列表按旧分组点，最后两个直接报错]")
check("fixture 就是上游那一行", "self.structure = [2, 5, 5, 7]" in UPSTREAM)
Tacet, clicks = upstream_class()
try:
    Tacet().teleport_to_tacet(LAST)
    raised = False
except IndexError:
    raised = True
check("不改的话第 21 个抛 IndexError", raised)
Tacet().teleport_to_tacet(7)
check("不改的话第 8 个按 [2, 5, 5, 7] 共 19 个去滚", clicks[-1], (8, 19, [2, 5, 5, 7]))

print("\n[装上改动：旧分组换成 [4, 5, 5, 7]，走的还是上游自己的 teleport_to_tacet]")
ns = overlay()
Tacet, clicks = upstream_class()
ns["_install_tacet_groups"]()
check("记在已绑定里", ns["_applied"], ["TacetTask.teleport_to_tacet"])
check("没有跳过", ns["_skipped"], [])
t = Tacet()
check("第 21 个不再报错", t.teleport_to_tacet(LAST), True)
check("点的时候按 [4, 5, 5, 7] 共 21 个", clicks[-1], (21, 21, [4, 5, 5, 7]))
check("日志说了从什么改成什么", t.logs[-1],
      "无音区分组：上游还是 [2, 5, 5, 7]，按鸣潮 3.7 改成 [4, 5, 5, 7]（共 21 个）")
t.teleport_to_tacet(7)
check("第二次照新分组点", clicks[-1], (8, 21, [4, 5, 5, 7]))
check("第二次不再说「改成」", "改成" in t.logs[-1], False)
check("第二次也留一行痕迹", t.logs[-1].startswith("无音区分组："))
t.teleport_to_tacet(0)
check("第 1 个还是第 1 个", clicks[-1], (1, 21, [4, 5, 5, 7]))

print("\n[机器上 09-30 已手改成新分组：认得出来，不叠第二次]")
HAND = ("self.structure = [4, 5, 5, 7]  # ark-relay: WuWa 3.7 added 沉心域 / 烬心域 at the top "
        "(2026-09-30)")
ns = overlay()
Tacet, clicks = upstream_class(UPSTREAM.replace("self.structure = [2, 5, 5, 7]", HAND))
ns["_install_tacet_groups"]()
t = Tacet()
t.teleport_to_tacet(LAST)
check("手改过的照原样点", clicks[-1], (21, 21, [4, 5, 5, 7]))
check("日志说没动", t.logs[-1], "无音区分组：[4, 5, 5, 7]（共 21 个），不是 3.7 之前的旧分组，照这份点")

print("\n[上游以后改了分组（旧分组对不上）：安静照上游的点，不硬改]")
for later in ([4, 5, 5, 7], [2, 4, 5, 5, 7], [3, 5, 5, 7]):
    ns = overlay()
    Tacet, clicks = upstream_class(UPSTREAM.replace("[2, 5, 5, 7]", repr(later)))
    ns["_install_tacet_groups"]()
    t = Tacet()
    t.teleport_to_tacet(0)
    check(f"上游 {later} 原样传下去", clicks[-1], (1, sum(later), later))
    check(f"上游 {later} 不记跳过", ns["_skipped"], [])

print("\n[上游把 teleport_to_tacet 改名了：不绑，记进跳过，照样上报]")
ns = overlay()
upstream_class(UPSTREAM.replace("def teleport_to_tacet(", "def go_to_tacet("))
ns["_install_tacet_groups"]()
check("没绑上", ns["_applied"], [])
check("跳过里点了名", [s["what"] for s in ns["_skipped"]], ["TacetTask.teleport_to_tacet"])

print("\n[日报核对：传送去了无音区就得有「无音区分组」那一行]")
LABEL = "无音区分组改动在跑（鸣潮 3.7 新增两个）"
went = "2026-10-01 09:30:00,000 INFO TaskExecutor TacetTask:info_set Teleport to Tacet Suppression 2\n"
ours = ("2026-10-01 09:29:59,900 INFO TaskExecutor TacetTask:无音区分组：上游还是 [2, 5, 5, 7]，"
        "按鸣潮 3.7 改成 [4, 5, 5, 7]（共 21 个）\n")
by = {c.label: c.ok for c in outcome.patch_effect_checks(ours + went)}
check("有那一行就算跑到了", by.get(LABEL), True)
by = {c.label: c.ok for c in outcome.patch_effect_checks(went)}
check("没有那一行就报没跑到", by.get(LABEL), False)
check("没传送就不评判", LABEL in {c.label for c in outcome.patch_effect_checks("DailyTask:x\n")}, False)
check("绑定登记到了这条核对", outcome.PATCH_COVERAGE.get("TacetTask.teleport_to_tacet"), LABEL)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
