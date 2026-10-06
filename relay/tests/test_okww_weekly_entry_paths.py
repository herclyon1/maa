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
        # Upstream v3.7.3 FarmEchoTask.py:268-304, reduced to the steps after the book.
        is_team = self.click_on_book_target(1, 4)
        self.events.append("after-book")
        if is_team:
            if self.config.get('Teleport to Boss', 'No') == 'Weekly Challenge':
                self.click_configured_boss_level()
                self.click(0.880, 0.911, after_sleep=2)
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
        self.events.append("level")

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
    t.wait_click_skip_dialog_confirm = lambda: t.events.append("skip-confirm")
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

print("\n[波片不足挡住开启挑战：点取消，不白打——正常状态，按跳过结束，不按失败]")
t = task(book="team", start=None, looks=[("结晶波片不足，无法获取奖励", False, False)])
check("按跳过结束", stopped(t), "skip")
check("没留失败原因", getattr(t, "_ark_failed", None), None)
check("点了取消", "cancel" in t.events)
check("说了波片不足", any("波片不足挡住开启挑战" in m for m in t.logs))
check("没写按失败结束", any(ns["FAILED_MARK"] in m for m in t.logs), False)

print("\n[开启挑战后弹出波片不足：点取消，不白打——按跳过结束]")
t = task(book="team", after=["结晶波片不足"])
check("按跳过结束", stopped(t), "skip")
check("没留失败原因", getattr(t, "_ark_failed", None), None)
check("点开启挑战后点了取消", [e for e in t.events if e in ("start", "cancel")], ["start", "cancel"])
check("没写按失败结束", any(ns["FAILED_MARK"] in m for m in t.logs), False)
check("留了图", "nowave_dialog" in t.shots)

print("\n[这一圈没打起来：不去找结晶]")
t = task()
t.combat = False
t.combat_once(wait_combat_time=5, raise_if_not_found=False)
t.incr_drop(False)
check("记下没打起来", t._ark_fought, False)
check("没走去结晶", "treasure" in t.events, False)
check("说了为什么", any("这一圈没打起来" in m for m in t.logs))
check("留了图", "weekly_no_fight" in t.shots)

print("\n[这一圈打过了：照常去结晶按 F；按 F 后认不出领奖弹窗就截图停下，不乱点]")
t = task()
t.combat_once(wait_combat_time=5, raise_if_not_found=False)
try:
    t.incr_drop(True)
    got = "went on"
except Disabled:
    got = "stopped"
check("记下打过", t._ark_fought, True)
check("去了结晶", "treasure" in t.events)
check("认不出弹窗：停下", got, "stopped")
check("认不出弹窗：截图 no_claim_ui", "no_claim_ui" in t.shots)
check("认不出弹窗：没点确认", "confirm" in t.events, False)

print("\n[领奖弹窗点了确认：留一张领奖那一刻的图（中继二 10-05 23:3x）]")
t = task(looks=[("领取奖励需消耗 60 结晶波片 取消 确认", False, False), ("挑战成功 退出副本", False, False)])
t.in_world = lambda: False
t._ark_weekly_left = 1
t.click_dialog_right_button = lambda: "confirm-btn"
t.book, t.left = "team", LEFT_0       # the way back in reads the counter: 0/3
t.combat_once(wait_combat_time=5, raise_if_not_found=False)
try:
    t.incr_drop(True)
except Disabled:
    pass
check("说了已点确认", any(m == "周本领奖：已点确认" for m in t.logs))
check("截了领奖那一刻", "weekly_claimed" in t.shots)
check("点了退出副本、三次领满不再进本", any("退出副本" in m for m in t.logs) and any("已领满" in m for m in t.logs)
      and "start" not in t.events)

print("\n[复活那一下也算打过；周本的复活交给上游 do_run 重新传送]")
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
check("算打过", t._ark_fought, True)

# The coverage driver runs every test in one process: leave sys.modules as found.
for k, v in _saved.items():
    if v is None:
        sys.modules.pop(k, None)
    else:
        sys.modules[k] = v

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
