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
from ark_relay.features.okww_patch import okww_overlay

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
import tempfile  # noqa: E402
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
sys.exit(1 if fails else 0)
