"""「确认前往」 on a 限时提前开放 boss: look where it put us, and claim only after a fight.

2026-10-05 the weekly boss 千傀重楼 showed the spoiler dialog for the first time
(「提前到达目标位置可能影响剧情体验，是否确认前往？」). The override assumed, from
天傀劫煞 on 09-09, that confirming lands in the arena. It did not (ok-script.log):

    10:33:46 the spoiler dialog is recognised and confirmed
    10:33:48 the override logs 「直接进场」 (straight into the arena) - unchecked
    10:33:49 boss_string is []
    10:34:04 wait_until timeout in_team_and_world 10 seconds
    10:34:08 周本领奖：打完了，去结晶按 F            <- no fight happened
    10:34:38 周本领奖：这一步没做成 WaitFailedException()
    10:34:50 farm 4c error (ESC opened the open world's 终端, screenshot 10-34-52.368)

Now: wait for the load, write down the screen, and go by upstream's own in_realm():
in a realm it is the arena; otherwise upstream walks from the target location to
the fight or the F, the way it does after any teleport near a boss. And the claim
walks to the crystal only in a lap that fought.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import okww_overlay

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


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
        # Upstream waits for the travel / team screen after 「前往」; the spoiler
        # dialog is in the way, so the wait runs out.
        raise Exception("wait_feature timeout")


class FarmEchoTask(BaseWWTask):
    def teleport_to_configured_boss(self):
        is_team = self.click_on_book_target(1, 4)
        self.events.append("upstream-after-book")      # never reached on the dialog path
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
check("三处都换上了", all(x in ns["_applied"] for x in (
    "BaseWWTask.click_on_book_target", "FarmEchoTask.teleport_to_configured_boss",
    "FarmEchoTask.combat_once", "FarmEchoTask.incr_drop")))

DIALOG = "提前到达目标位置可能影响剧情体验，是否确认前往？ 取消 确认"


def task(realm, world=False, landing="", combat=True):
    t = object.__new__(FarmEchoTask)
    t.events, t.logs, t.shots, t.waits = [], [], [], []
    t.realm, t.world, t.landing, t.combat, t.revive = realm, world, landing, combat, False
    t.config = {"Teleport to Boss": "Weekly Challenge"}
    t._in_realm = True
    t.ocr = lambda box=None, **kw: [DIALOG] if box == "dialog" else [t.landing]
    t.box_of_screen = lambda x, y, to_x, to_y: "dialog" if (x, y) == (0.25, 0.40) else "full"
    t.log_info = lambda msg, notify=False: t.logs.append(msg)
    t.click_dialog_right_button = lambda: t.events.append("confirm")
    t.wait_in_team_and_world = lambda time_out=10, raise_if_not_found=True, esc=False: t.waits.append(time_out)
    t.screenshot = lambda name: t.shots.append(name)
    t.in_realm = lambda: t.realm
    t.in_world = lambda: t.world
    t.wait_feature = lambda *a, **kw: None
    t.walk_to_treasure = lambda: t.events.append("treasure")
    t.pick_f = lambda handle_claim=True: t.events.append("f")
    t.sleep = lambda s: None
    return t


print("\n[确认后落在 Boss 场地里（09-09 天傀劫煞那种）：照旧当已进本]")
t = task(realm=True, landing="Lv.90 千傀重楼")
t.teleport_to_configured_boss_and_prepare()
check("点了确认", t.events[:1], ["confirm"])
check("等进场给足 120 秒（和上游传送后一样）", t.waits, [120])
check("当成已进本", t.prepared, "realm")
check("没走上游的传送后走路", "walk" in t.events, False)
check("落地截了图", t.shots, ["early_open_landed"])
check("框里的字记下了", any("框里读到：提前到达目标位置" in m for m in t.logs))
check("落地读到的字记下了", any("in_realm=True" in m and "千傀重楼" in m for m in t.logs))

print("\n[确认后落在大世界目标附近（10-05 千傀重楼那种）：交给上游走到 Boss 或 F]")
t = task(realm=False, world=True, landing="终端")
t.teleport_to_configured_boss_and_prepare()
check("走了上游传送后的走法", t.events.count("walk"), 1)
check("上游走完说进本了", t.prepared, "realm")
check("退本不回信标（和上游传送路一致）", t.realm_entry_at_heal_point, False)
check("没再说「直接进场」", any("直接进场" in m for m in t.logs), False)
check("说了在大世界目标附近", any("大世界目标附近" in m for m in t.logs))
check("上游开书之后那几步没跑", "upstream-after-book" in t.events, False)

print("\n[确认后是选等级页（10-05 22:05 周本天演溯心那种）：按正常进本走，不等 120 秒、不走路]")
TEAM_PAGE = "定序诸理之律 140 114/240+） 推荐等级90 本周剩余可收取次数：3/3 x60 单人挑战"
t = task(realm=False, landing=TEAM_PAGE)
t.clicks = []
t.click = lambda *a, **kw: t.clicks.append(a)
t.click_configured_boss_level = lambda: t.events.append("level")
t.click_team_challenge = lambda: t.events.append("challenge")
t.teleport_to_configured_boss_and_prepare()
check("选等级→单人挑战→开启挑战", [e for e in t.events if e in ("level", "challenge")], ["level", "challenge"])
check("单人挑战点的是上游那个位置", t.clicks, [(0.880, 0.911)])
check("当成已进本", t.prepared, "realm")
check("没走大世界的路", "walk" in t.events, False)
check("没先干等 120 秒（只在进本后等）", t.waits, [120])
check("截了选等级页", t.shots, ["early_open_team"])
check("说了是选等级页", any("选等级页" in m for m in t.logs))

print("\n[这一圈没打起来：不去找结晶]")
t = task(realm=True, combat=False)
t.combat_once(wait_combat_time=5, raise_if_not_found=False)
t.incr_drop(False)
check("记下没打起来", t._ark_fought, False)
check("没走去结晶", "treasure" in t.events, False)
check("说了为什么", any("这一圈没打起来" in m for m in t.logs))
check("留了图", "weekly_no_fight" in t.shots)

print("\n[这一圈打过了：照常去结晶按 F]")
t = task(realm=True, combat=True)
t.combat_once(wait_combat_time=5, raise_if_not_found=False)
t.incr_drop(True)
check("记下打过", t._ark_fought, True)
check("去了结晶", "treasure" in t.events)

print("\n[复活那一下也算打过]")
t = task(realm=True)
t.revive = True
check("复活后返回 None", t.combat_once(), None)
check("算打过", t._ark_fought, True)

# The coverage driver runs every test in one process: leave sys.modules as found.
for k, v in _saved.items():
    if v is None:
        sys.modules.pop(k, None)
    else:
        sys.modules[k] = v

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
