"""Weekly boss claim: upstream's claim step with 确认 for its ESC, and the read-back.

Runs the real overlay (claim hook, level-page read, 开启挑战 split) against
upstream's own call order, with the game's real text:

  (E) crystal -> F -> claim dialog -> 确认 (not ESC) -> 「波片不够，动用备用体力」 ->
      确认 again -> settlement page -> 「退出副本」
  backup used and still short (10-12 11:44): 取消, skipped as short, no solute
  read-back: the way back in reads the counter on the level page, which has to be
      one less - ok-script.log 2026-10-05 22:13:04 3/3, 22:15:19 2/3, 22:17:31 1/3,
      22:39:48 0/3; unchanged / unread / some other number stops
  no crystal / the walk to it fails (10-12 09:52:20, OK-WW-05-18-47.log:1103-1109):
      no stop, the lap goes back to upstream
  a dialog that is not the claim dialog, or not the weekly boss: upstream's ESC
  unread 「本周剩余可收取次数」 before entering: stop, not 「enter anyway」
  开启挑战: the waveplate dialog is looked for over ~5 s, not once (08-31), and a
      dialog that is up but not recognised is never confirmed
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
    # Upstream v3.7.4 BaseWWTask.py:520-526, verbatim: ESC, i.e. 取消.
    def handle_claim_button(self):
        while self.wait_until(self.has_claim, raise_if_not_found=False, time_out=1.5):
            self.sleep(0.5)
            self.send_key('esc')
            self.sleep(0.5)
            return True

    # Upstream v3.7.4 BaseWWTask.py:584-590, with find_one('pick_up_f...') as `f_up`.
    def pick_f(self, handle_claim=True):
        if self.f_up:
            self.send_key('f', after_sleep=1)
            if not handle_claim:
                return True
            if not self.handle_claim_button():
                return True

    def click_on_book_target(self, serial_number, total_number, structure=None):
        self.events.append("book")
        return True                 # the team screen, no spoiler dialog

    # Upstream v3.7.3 BaseWWTask.py:1115-1117, verbatim: the overlay replaces it
    # only while its source still hashes to the pin.
    def click_team_challenge(self):
        self.wait_click_feature('team_start_challenge', raise_if_not_found=True, click_after_delay=0.5, after_sleep=1)
        self.wait_click_skip_dialog_confirm()


class FarmEchoTask(BaseWWTask):
    def teleport_to_configured_boss(self):
        # Upstream v3.7.3 FarmEchoTask.py:268-304, reduced to the steps after the book.
        self.entries += 1
        is_team = self.click_on_book_target(1, 9)
        if is_team and not self.arena:
            self.click_configured_boss_level()
            self.click(0.880, 0.911, after_sleep=2)
            self.click_team_challenge()
        self.wait_in_team_and_world(time_out=120)
        return is_team

    def teleport_to_configured_boss_and_prepare(self):
        # Upstream v3.7.3 FarmEchoTask.py:243-266, reduced.
        try:
            self.teleport_to_configured_boss()
        except Exception as e:
            raise RuntimeError("Teleport to boss failed") from e
        self.prepared = "realm"

    def click_configured_boss_level(self):
        self.events.append("level")

    def combat_once(self, wait_combat_time=200, raise_if_not_found=True, target=False):
        return True

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
exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
if "FarmEchoTask.incr_drop" not in ns["_applied"]:
    ns["_install_claim"]()
check("领奖、走去结晶、读次数、开启挑战四处都换上了", all(x in ns["_applied"] for x in (
    "FarmEchoTask.handle_claim_button", "FarmEchoTask.incr_drop", "FarmEchoTask.click_configured_boss_level",
    "FarmEchoTask.click_team_challenge")))
ns["NO_CLAIM"] = str(Path(__file__).resolve().parent / "no-such-no-claim-flag")

# Real text. The claim dialog: the old patch's own note of the full-screen OCR
# (okww_patches/claim.py, removed 2026-10-12); the counter: ok-script.log 2026-10-05 (see the docstring).
CLAIM_DIALOG = ["领取奖励需消耗60点结晶波片，请确认是否领取？", "取消", "确认"]
SETTLEMENT = ["挑战成功", "退出副本", "重新挑战"]
PAGE = {3: ["本周剩余可收取次数：3/3_1.00", "x60_0.79"], 2: ["本周剩余可收取次数：2/3_1.00", "x60_0.79"],
        1: ["本周剩余可收取次数：1/3_1.00", "x60_0.79"], 0: ["本周剩余可收取次数：0/3_0.99", "x60_0.79"]}
UNREAD = ["x60_0.79"]


class _At:
    """An OCR box with a place on the 1920x1080 screen."""
    def __init__(self, name, x, y):
        self.name, self.x, self.y, self.width, self.height = name, x, y, 40, 30

    def __str__(self):
        # ok-script's Box repr as the 10-12 log prints it
        return (f"Box(name='{self.name}', x={self.x}, y={self.y}, width={self.width}, "
                f"height={self.height}, confidence=100)")


def claim_screen(wave, spare, cap="240"):
    """The claim dialog over the top bar (10-12 11:44:41: backup 24 at x=1208, y=50)."""
    return [_At(str(spare), 1208, 50), _At(f"{wave}/{cap}", 1480, 50), _At("15652", 1800, 50),
            _At(CLAIM_DIALOG[0], 700, 500), _At("取消", 640, 700), _At("确认", 1280, 700)]


# The claim dialog with a readable bar: 240 full (「240/240+」, 0921-weekly.log:18), and
# 41 + backup 24 (enough with the backup, 10-12 11:44 numbers moved up by 24).
FULL = claim_screen(240, 0, cap="240+")
TOPUP = claim_screen(41, 24)


def task(left=None, pages=(), screens=(), after=(), dialogs=(), gems=0, arena_at=None, crystal=True,
         walk_error=None, claim_up=True, boss="Weekly Challenge"):
    t = object.__new__(FarmEchoTask)
    t.events, t.logs, t.errors, t.shots = [], [], [], []
    t.entries, t.arena, t.reads_after = 0, False, 0
    t.pages, t.screens, t.after, t.dialogs = list(pages), list(screens), list(after), list(dialogs)
    t.gems, t.arena_at, t.crystal, t.walk_error = gems, arena_at, crystal, walk_error
    t.claim_up, t.f_up = claim_up, True
    t.config = {"Teleport to Boss": boss}
    t._in_realm = True
    if left is not None:
        t._ark_weekly_left = left

    def ocr(box=None, **kw):
        if box == (0.58, 0.80):
            return t.pages.pop(0) if t.pages else UNREAD
        if box == (0.20, 0.35):
            t.reads_after += 1
            return t.after.pop(0) if t.after else []
        if box == (0.0, 0.0):
            return t.screens.pop(0) if t.screens else ["某个没见过的画面"]
        return []
    t.ocr = ocr
    t.box_of_screen = lambda x, y, to_x, to_y: (x, y)
    t.height_of_screen = lambda r: r * 1080
    t.in_world = lambda: False
    t.in_team_and_world = lambda: t.arena_at is not None and t.reads_after >= t.arena_at
    t.log_info = lambda msg, notify=False: t.logs.append(msg)
    t.log_error = lambda msg, notify=False: t.errors.append((msg, notify))
    t.screenshot = lambda name: t.shots.append(name)
    t.sleep = lambda s: None
    t.wait_until = lambda cond, **kw: cond()
    t.has_claim = lambda: t.claim_up
    t.find_treasure_icon = lambda: t.crystal

    def walk():
        t.events.append("walk")
        if t.walk_error:
            raise t.walk_error
    t.walk_to_treasure = walk

    def right():
        t.events.append("confirm")
        return "confirm-btn"
    t.click_dialog_right_button = right
    t.click_dialog_left_button = lambda: t.events.append("cancel")

    def click(*a, **kw):
        t.events.append("solo" if a[:2] == (0.880, 0.911) else f"click:{a[0]}")
    t.click = click
    t.click_relative = lambda x, y, **kw: t.events.append(f"rel:{x},{y}")
    t.back = lambda after_sleep=0: t.events.append("back")
    t.send_key = lambda key, **kw: t.events.append(f"key:{key}")
    t.ensure_main = lambda time_out=30: t.events.append("main")
    t.wait_in_team_and_world = lambda time_out=10, raise_if_not_found=True, esc=False: True

    def wait_feature(feature, **kw):
        if feature == "gem_add_stamina":
            if t.gems > 0:
                t.gems -= 1
                return "gem"
            return None
        return True                 # team_start_challenge is there
    t.wait_feature = wait_feature

    def wait_click_ocr(match=None, **kw):
        seen = t.screens.pop(0) if t.screens else ["某个没见过的画面"]
        hit = [b for b in seen if match.search(str(b))]
        if hit:
            t.events.append(f"click:{hit[0]}")
            return hit
        return None
    t.wait_click_ocr = wait_click_ocr
    t.wait_click_feature = lambda feature, **kw: t.events.append("start")
    t.wait_click_skip_dialog_confirm = lambda *a, **kw: t.events.append("skip-confirm")
    t.find_one = lambda *a, **kw: t.dialogs.pop(0) if t.dialogs else None
    return t


def lap(t):
    """One lap's end: the fight is over, upstream calls incr_drop. 'stop' on a deliberate stop."""
    try:
        t.incr_drop(True)
    except Disabled:
        return "stop"
    return "on"


print("[(E) 结晶按 F→领奖弹窗点确认（不按 ESC）→波片不够动用备用体力→确认→结算页「退出副本」→回去读到 2/3]")
t = task(left=3, pages=[PAGE[2]], screens=[TOPUP, SETTLEMENT], gems=1)
check("没停", lap(t), "on")
claim = t.events[:t.events.index("click:退出副本") + 1]
check("走去结晶、按 F、确认、备用体力两下、返回、再确认、点退出副本", claim,
      ["incr", "walk", "key:f", "confirm", "rel:0.7,0.71", "rel:0.7,0.71", "back", "click:confirm-btn",
       "click:退出副本"])
check("领奖弹窗上没按 ESC（上游那一下换成了确认）", "key:esc" in t.events, False)
check("认出弹窗那句照旧（中继认它算打过一场）", any(m.startswith("周本领奖：认出弹窗，点确认") for m in t.logs))
check("说了动用备用体力", "周本领奖：波片不够，动用备用体力" in t.logs)
check("截了领奖那一刻", "weekly_claimed" in t.shots)
check("说了已点确认（中继数点击次数）", "周本领奖：已点确认" in t.logs)
check("结算页点了退出副本", "周本领奖：结算页点了「退出副本」" in t.logs)
check("回读确认 3/3→2/3", "周本领奖：回读确认领到，本周剩余 3/3→2/3" in t.logs)
check("重进了本（选等级→单人挑战→开启挑战）", [e for e in t.events if e in ("level", "solo", "start")],
      ["level", "solo", "start"])
check("开启挑战后什么都没确认", "skip-confirm" in t.events, False)
check("没报错", t.errors, [])
check("这次的读数记下当下一次的「领前」", t._ark_weekly_left, 2)

print("\n[波片够、不弹补体力：确认一下就到结算页]")
t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
check("没停", lap(t), "on")
check("确认一次就退出副本", t.events[:5], ["incr", "walk", "key:f", "confirm", "click:退出副本"])
check("没碰备用体力", [e for e in t.events if e.startswith("rel:") or e == "back"], [])

print("\n[周一一趟三次：3/3→2/3→1/3→0/3，最后那次只读数，0/3 不进本]")
t = task(left=3, pages=[PAGE[2], PAGE[1], PAGE[0]], screens=[FULL, SETTLEMENT] * 3)
got = [lap(t), lap(t), lap(t)]
check("前两圈接着打，第三圈领完停（有意跳过）", got, ["on", "on", "stop"])
check("三次回读都对上", [m for m in t.logs if "回读确认" in m],
      ["周本领奖：回读确认领到，本周剩余 3/3→2/3", "周本领奖：回读确认领到，本周剩余 2/3→1/3",
       "周本领奖：回读确认领到，本周剩余 1/3→0/3"])
check("开启挑战只点了两次", t.events.count("start"), 2)
check("读到 0/3 退回主界面", t.events[-1], "main")
check("说了已领满", "本周周本次数已领满（0/3），不进本，跳过" in t.logs)
check("一次 ESC 都没按", "key:esc" in t.events, False)
check("没报错", t.errors, [])

def on_screen(t):
    t.height_of_screen = lambda r: r * 1080
    return t


print("\n[领奖弹窗：波片 17 + 备用 24 不够 60（10-12 11:44）：先读顶栏，点取消、按波片不足跳过，不动备用体力]")
t = on_screen(task(left=3, screens=[claim_screen(17, 24)], gems=2))
check("跳过（结束这趟周本）", lap(t), "stop")
check("按 F 后直接点取消", t.events[:4], ["incr", "walk", "key:f", "cancel"])
check("没点确认、没碰备用体力", [e for e in t.events if e in ("confirm", "back") or e.startswith("rel:")], [])
check("说了波片不足那句（中继认它是波片不足）",
      any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))
check("没说认出弹窗点确认（中继不当它领过）", any(m.startswith("周本领奖：认出弹窗") for m in t.logs), False)
check("留图", "weekly_short_claim" in t.shots)
check("按跳过结束：没留失败原因", getattr(t, "_ark_failed", None), None)
check("没当报错推送", t.errors, [])

print("\n[领奖弹窗：波片 41 + 备用 24 够 60：照旧确认、动用备用体力一次、领到]")
t = on_screen(task(left=3, pages=[PAGE[2]], screens=[claim_screen(41, 24), SETTLEMENT], gems=1))
check("没停", lap(t), "on")
check("确认后动用备用体力", t.events[3:6], ["confirm", "rel:0.7,0.71", "rel:0.7,0.71"])
check("回读确认 3/3→2/3", "周本领奖：回读确认领到，本周剩余 3/3→2/3" in t.logs)

print("\n[领奖弹窗：波片 60 够：照旧确认一下就到结算页]")
t = on_screen(task(left=3, pages=[PAGE[2]], screens=[claim_screen(60, 0), SETTLEMENT]))
check("没停", lap(t), "on")
check("确认一次就退出副本", t.events[:5], ["incr", "walk", "key:f", "confirm", "click:退出副本"])

print("\n[the claim dialog's bar: 「240/240+」 (0921-weekly.log:18) reads as 240, backup 0]")
check("240/240+", ns["_waveplates"](on_screen(task()), claim_screen(240, 0, cap="240+")), (240, 0))
check("41/240", ns["_waveplates"](on_screen(task()), claim_screen(41, 24)), (41, 24))
check("0/240+ with a backup of 136 (the level page, 10-05 22:17:31)",
      ns["_waveplates"](on_screen(task()), claim_screen(0, 136, cap="240+")), (0, 136))
t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
check("240/240+: not stopped", lap(t), "on")
check("240/240+: the two values are in the log", "周本领奖：顶栏读到波片 240/240，备用 0" in t.logs)
check("the claim line shows the /240 token", any(m.startswith("周本领奖：认出弹窗") and "240/240+" in m for m in t.logs))

print("\n[bar not read: no blind 确认 (10-12 11:44 spent the backup that way) - picture, phone, stop]")
t = task(left=3, pages=[PAGE[2]], screens=[[_At(CLAIM_DIALOG[0], 700, 500)], SETTLEMENT], gems=2)
check("stopped", lap(t), "stop")
check("nothing confirmed, backup untouched", [e for e in t.events if e in ("confirm", "back") or e.startswith("rel:")], [])
check("picture", "weekly_claim_bar_unread" in t.shots)
check("pushed to the phone, as a failure", len(t.errors) == 1 and t.errors[0][1] and "顶栏的波片没读全" in t.errors[0][0])
check("ends as failed (a reason is kept)", "顶栏的波片没读全" in (getattr(t, "_ark_failed", None) or ""))

print("\n[顶栏读到够（41+24）、备用体力用上了仍不够（又弹补体力）：返回、点取消、按波片不足跳过，不动结晶溶剂]")
t = task(left=3, screens=[TOPUP], gems=2)
check("跳过（结束这趟周本）", lap(t), "stop")
check("备用体力一轮之后返回、取消，没再确认",
      t.events[3:], ["confirm", "rel:0.7,0.71", "rel:0.7,0.71", "back", "click:confirm-btn", "back", "cancel"])
check("说了波片不足那句（中继认它是波片不足）",
      any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))
check("没说已点确认", "周本领奖：已点确认" in t.logs, False)
check("留图", "weekly_short_claim" in t.shots)
check("按跳过结束：没留失败原因", getattr(t, "_ark_failed", None), None)
check("没当报错推送", t.errors, [])

print("\n[10-12 15:29 / 15:31: backup 0, waveplates short -> cancelled before 确认; the top-up (solute) is never clicked]")
t = task(left=3, screens=[claim_screen(17, 0)], gems=2)
check("skipped as short", lap(t), "stop")
check("no confirm, no top-up clicks", [e for e in t.events if e in ("confirm", "back") or e.startswith("rel:")], [])
check("the shortage line", any(m.startswith("结晶波片不足，取消并跳过本次周本") for m in t.logs))

print("\n[bar reads 240 but the game still opens the top-up dialog -> cancel, picture, stop; no top-up clicks]")
t = task(left=3, screens=[FULL, SETTLEMENT], gems=1)
check("stopped", lap(t), "stop")
check("confirm, then back + cancel, no top-up clicks", t.events[3:], ["confirm", "back", "cancel"])
check("picture of the dialog", "weekly_topup_unexpected" in t.shots)
check("pushed, as a failure", len(t.errors) == 1 and t.errors[0][1] and "不点补充" in t.errors[0][0])
check("not counted as clicked", "周本领奖：已点确认" in t.logs, False)

print("\n[a claim made through upstream's own pickup (pick_f in walk_find_echo) leaves us in the world: still read back and re-entered]")
t = task(left=3, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
check("upstream's pick_f took the claim and clicked 退出副本", t.pick_f(), None)
check("the claim flag is set", getattr(t, "_ark_claimed", False), True)
t.in_world = lambda: True                    # 退出副本 put us in the open world
check("incr_drop does not stop", lap(t), "on")
check("read back 3/3->2/3", "周本领奖：回读确认领到，本周剩余 3/3→2/3" in t.logs)
check("went back in (level page)", "level" in t.events)
check("flag cleared", t._ark_claimed, False)
check("no second walk to a crystal", t.events.count("walk"), 0)

print("\n[回读次数没变：这次没领到，截图报手机，停下不再进本]")
t = task(left=2, pages=[PAGE[2]], screens=[FULL, SETTLEMENT])
check("停下", lap(t), "stop")
check("报到手机", t.errors, [("周本领奖：回读次数没变（2/3），这次没领到", True)])
check("留图", "weekly_claim_unchanged" in t.shots)
check("没点上游的选等级、没点开启挑战", [e for e in t.events if e in ("level", "start")], [])

print("\n[回读没读到：截图报手机，停下]")
t = task(left=3, pages=[UNREAD], screens=[FULL, SETTLEMENT])
check("停下", lap(t), "stop")
check("报到手机", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
check("原文进日志", any("回读时选等级页读到" in m and "x60_0.79" in m for m in t.logs))
check("留图", "weekly_readback_unread" in t.shots)

print("\n[重进没经过选等级页（直接落在场地里）：次数没回读，停下]")
t = task(left=3, screens=[FULL, SETTLEMENT])
t.arena = True
check("停下", lap(t), "stop")
check("报回读没读到", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
check("回读的账清掉，下一趟不拿它比", t._ark_claim_before, None)

print("\n[no 「退出副本」 after 确认 (10-05 10:34:50 farm 4c error): picture, phone, stop - no ESC, no re-entry]")
t = task(left=3, screens=[FULL])
check("stopped", lap(t), "stop")
check("pushed with the screen's text",
      len(t.errors) == 1 and t.errors[0][1] and "没等到结算页" in t.errors[0][0] and "某个没见过的画面" in t.errors[0][0])
check("picture", "weekly_no_settlement" in t.shots)
check("no ESC, no back", [e for e in t.events if e in ("key:esc", "back")], [])
check("no re-entry", t.entries, 0)
check("ends as failed", "没等到结算页" in (getattr(t, "_ark_failed", None) or ""))

print("\n[今早 09:51:50 那种：战斗判定先断、走去结晶 30 秒没走到（WaitFailedException）：不停，交回上游]")
# ev OK-WW-05-18-47.log:1102-1109 - 「farm echo walk_find_echo None」, 「去结晶按 F」,
# walk_to_treasure, 09:52:20 WaitFailedException, then 「这一趟按失败结束」 and the run gone.


class WaitFailedException(Exception):
    """ok.WaitFailedException."""


t = task(left=3, walk_error=WaitFailedException())
check("没停", lap(t), "on")
check("走了一趟结晶，没按 F", [e for e in t.events if e in ("walk", "key:f")], ["walk"])
check("说了没走到、交回上游", any("没走到结晶" in m and "WaitFailedException" in m for m in t.logs))
check("没留失败原因（不再按失败结束）", getattr(t, "_ark_failed", None), None)
check("没报错、没截停下的图", (t.errors, t.shots), ([], []))
check("没点任何确认、没 ESC", [e for e in t.events if e in ("confirm", "cancel", "key:esc")], [])

print("\n[没看到结晶（Boss 还在 / 这一圈没打起来）：不走、不停，交回上游]")
t = task(left=3, crystal=False)
check("没停", lap(t), "on")
check("没走去结晶、没按 F", [e for e in t.events if e in ("walk", "key:f")], [])
check("说了为什么", any("没看到结晶" in m for m in t.logs))
check("没报错", t.errors, [])

print("\n[领奖钩子遇到的不是领奖弹窗（退出副本的确认框也是这个取消按钮）：照上游按 ESC，不点确认]")
t = task(screens=[["是否退出副本？", "取消", "确认"]])
check("返回 True（上游的语义）", t.handle_claim_button(), True)
check("按的是 ESC，没点确认", [e for e in t.events if e in ("key:esc", "confirm")], ["key:esc"])

print("\n[没有弹窗：什么都不点，返回 None（上游的语义）]")
t = task(claim_up=False)
check("返回 None", t.handle_claim_button(), None)
check("什么都没点", t.events, [])

print("\n[不是周本（刷声骸走的是强敌）：领奖弹窗照上游按 ESC]")
t = task(boss="Boss Challenge", screens=[CLAIM_DIALOG])
check("返回 True", t.handle_claim_button(), True)
check("按的是 ESC，没点确认", [e for e in t.events if e in ("key:esc", "confirm")], ["key:esc"])

print("\n[进本前选等级页没读到本周剩余次数：截图报手机，停下不进本]")
t = task(pages=[UNREAD])
try:
    t.teleport_to_configured_boss_and_prepare()
    got = "in"
except Disabled:
    got = "stop"
check("停下（有意跳过，不算失败）", got, "stop")
check("报到手机、带原文", len(t.errors) == 1 and t.errors[0][1] and "x60_0.79" in t.errors[0][0])
check("留图", "weekly_left_unread" in t.shots)
check("没点上游的选等级、没点单人挑战", [e for e in t.events if e in ("level", "solo", "start")], [])

print("\n[进本前读到 3/3（22:13:04）：照常进本，记下 3]")
t = task(pages=[PAGE[3]])
t.teleport_to_configured_boss_and_prepare()
check("进了本", t.prepared, "realm")
check("记下 3", t._ark_weekly_left, 3)

print("\n[开启挑战后第 3 次才读到波片不足（08-31 那种第一眼没读到）：点取消，跳过]")
t = task(after=[[], [], ["结晶波片不足，无法获取奖励"]])
try:
    t.click_team_challenge()
    got = "on"
except Disabled:
    got = "skip"
check("跳过", got, "skip")
check("点了取消，没点确认", [e for e in t.events if e in ("cancel", "confirm", "skip-confirm")], ["cancel"])
check("留图", "nowave_dialog" in t.shots)
check("日志照旧（日报认这句）", "结晶波片不足，取消并跳过本次周本" in t.logs)
check("缺波片按跳过结束：没留失败原因", getattr(t, "_ark_failed", None), None)

print("\n[开启挑战后有对话框、字一直认不出：不点确认，截图报手机，停下]")
t = task(dialogs=["btn"] * 6)
try:
    t.click_team_challenge()
    got = "on"
except Disabled:
    got = "stop"
check("停下", got, "stop")
check("看满了整段（6 眼）", t.reads_after, 6)
check("没点确认也没点取消", [e for e in t.events if e in ("cancel", "confirm", "skip-confirm")], [])
check("留图", "challenge_dialog_unknown" in t.shots)
check("报到手机", len(t.errors) == 1 and t.errors[0][1] and "认不出的对话框" in t.errors[0][0])

print("\n[开启挑战后没有对话框、到了场地：不再看，也不点任何确认]")
t = task(arena_at=2)
t.click_team_challenge()
check("看到进场就停（2 眼）", t.reads_after, 2)
check("什么都没确认", [e for e in t.events if e in ("cancel", "confirm", "skip-confirm")], [])
check("没报错", t.errors, [])

print("\n[开启挑战后一直加载中、没有对话框：看满整段，不点确认，接着走]")
t = task()
t.click_team_challenge()
check("看满 6 眼", t.reads_after, 6)
check("什么都没确认", [e for e in t.events if e in ("cancel", "confirm", "skip-confirm")], [])

# The coverage driver runs every test in one process: leave sys.modules as found.
for k, v in _saved.items():
    if v is None:
        sys.modules.pop(k, None)
    else:
        sys.modules[k] = v

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
