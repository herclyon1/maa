"""Weekly boss claim: what the game shows decides, and anything unknown stops.

Runs the real overlay (claim hook, level-page read, 开启挑战 split) against
upstream's own call order, with the game's real text:

  (E) claim dialog -> confirm -> 「波片不够，动用备用体力」 -> confirm again -> settlement
      page -> 「退出副本」
  read-back: the way back in reads the counter on the level page, which has to be
      one less - ok-script.log 2026-10-05 22:13:04 3/3, 22:15:19 2/3, 22:17:31 1/3,
      22:39:48 0/3; unchanged / unread / some other number stops
  no settlement page after 确认: stop, no ESC (10-05 10:34:50 「farm 4c error」)
  unread 「本周剩余可收取次数」 before entering: stop, not 「enter anyway」
  a lap whose fight was never recorded: no walk to a crystal
  开启挑战: the waveplate dialog is looked for over ~5 s, not once (08-31), and a
      dialog that is up but not recognised is never confirmed
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
check("领奖、读次数、开启挑战三处都换上了", all(x in ns["_applied"] for x in (
    "FarmEchoTask.incr_drop", "FarmEchoTask.click_configured_boss_level", "FarmEchoTask.click_team_challenge")))
ns["NO_CLAIM"] = str(Path(__file__).resolve().parent / "no-such-no-claim-flag")

# Real text. The claim dialog: the old patch's own note of the full-screen OCR
# (okww_patches/claim.py); the counter: ok-script.log 2026-10-05 (see the docstring).
CLAIM_DIALOG = ["领取奖励需消耗60点结晶波片，请确认是否领取？", "取消", "确认"]
SETTLEMENT = ["挑战成功", "退出副本", "重新挑战"]
PAGE = {3: ["本周剩余可收取次数：3/3_1.00", "x60_0.79"], 2: ["本周剩余可收取次数：2/3_1.00", "x60_0.79"],
        1: ["本周剩余可收取次数：1/3_1.00", "x60_0.79"], 0: ["本周剩余可收取次数：0/3_0.99", "x60_0.79"]}
UNREAD = ["x60_0.79"]


def task(left=None, pages=(), screens=(), after=(), dialogs=(), backup=False, arena_at=None, fought=True):
    t = object.__new__(FarmEchoTask)
    t.events, t.logs, t.errors, t.shots = [], [], [], []
    t.entries, t.arena, t.reads_after = 0, False, 0
    t.pages, t.screens, t.after, t.dialogs = list(pages), list(screens), list(after), list(dialogs)
    t.backup, t.arena_at = backup, arena_at
    t.config = {"Teleport to Boss": "Weekly Challenge"}
    t._in_realm = True
    if left is not None:
        t._ark_weekly_left = left
    if fought is not None:
        t._ark_fought = fought

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
    t.in_world = lambda: False
    t.in_team_and_world = lambda: t.arena_at is not None and t.reads_after >= t.arena_at
    t.log_info = lambda msg, notify=False: t.logs.append(msg)
    t.log_error = lambda msg, notify=False: t.errors.append((msg, notify))
    t.screenshot = lambda name: t.shots.append(name)
    t.sleep = lambda s: None
    t.walk_to_treasure = lambda: t.events.append("walk")
    t.pick_f = lambda handle_claim=True: t.events.append("f")

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
            return "gem" if t.backup else None
        return True                 # team_start_challenge is there
    t.wait_feature = wait_feature
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


print("[(E) 领奖弹窗→确认→波片不够动用备用体力→确认→结算页「退出副本」→回去读到 2/3]")
t = task(left=3, pages=[PAGE[2]], screens=[CLAIM_DIALOG, SETTLEMENT], backup=True)
check("没停", lap(t), "on")
claim = t.events[:t.events.index("click:退出副本") + 1]
check("按 F、确认、备用体力两下、返回、再确认、点退出副本", claim,
      ["incr", "walk", "f", "confirm", "rel:0.7,0.71", "rel:0.7,0.71", "back", "click:confirm-btn", "click:退出副本"])
check("说了动用备用体力", "周本领奖：波片不够，动用备用体力" in t.logs)
check("截了领奖那一刻", "weekly_claimed" in t.shots)
check("结算页点了退出副本", "周本领奖：结算页点了「退出副本」" in t.logs)
check("回读确认 3/3→2/3", "周本领奖：回读确认领到，本周剩余 3/3→2/3" in t.logs)
check("重进了本（选等级→单人挑战→开启挑战）", [e for e in t.events if e in ("level", "solo", "start")],
      ["level", "solo", "start"])
check("开启挑战后什么都没确认", "skip-confirm" in t.events, False)
check("没报错", t.errors, [])
check("这次的读数记下当下一次的「领前」", t._ark_weekly_left, 2)

print("\n[周一一趟三次：3/3→2/3→1/3→0/3，最后那次只读数，0/3 不进本]")
t = task(left=3, pages=[PAGE[2], PAGE[1], PAGE[0]], screens=[CLAIM_DIALOG, SETTLEMENT] * 3)
got = [lap(t), lap(t), lap(t)]
check("前两圈接着打，第三圈领完停（有意跳过）", got, ["on", "on", "stop"])
check("三次回读都对上", [m for m in t.logs if "回读确认" in m],
      ["周本领奖：回读确认领到，本周剩余 3/3→2/3", "周本领奖：回读确认领到，本周剩余 2/3→1/3",
       "周本领奖：回读确认领到，本周剩余 1/3→0/3"])
check("开启挑战只点了两次", t.events.count("start"), 2)
check("读到 0/3 退回主界面", t.events[-1], "main")
check("说了已领满", "本周周本次数已领满（0/3），不进本，跳过" in t.logs)
check("没报错", t.errors, [])

print("\n[回读次数没变：这次没领到，截图报手机，停下不再进本]")
t = task(left=2, pages=[PAGE[2]], screens=[CLAIM_DIALOG, SETTLEMENT])
check("停下", lap(t), "stop")
check("报到手机", t.errors, [("周本领奖：回读次数没变（2/3），这次没领到", True)])
check("留图", "weekly_claim_unchanged" in t.shots)
check("没点上游的选等级、没点开启挑战", [e for e in t.events if e in ("level", "start")], [])

print("\n[回读没读到：截图报手机，停下]")
t = task(left=3, pages=[UNREAD], screens=[CLAIM_DIALOG, SETTLEMENT])
check("停下", lap(t), "stop")
check("报到手机", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
check("原文进日志", any("回读时选等级页读到" in m and "x60_0.79" in m for m in t.logs))
check("留图", "weekly_readback_unread" in t.shots)

print("\n[重进没经过选等级页（直接落在场地里）：次数没回读，停下]")
t = task(left=3, screens=[CLAIM_DIALOG, SETTLEMENT])
t.arena = True
check("停下", lap(t), "stop")
check("报回读没读到", t.errors, [("周本领奖：回读没读到本周剩余次数", True)])
check("回读的账清掉，下一趟不拿它比", t._ark_claim_before, None)

print("\n[点了确认后没等到结算页：截图、整屏进日志、停下，不按 ESC，不重进]")
t = task(left=3, screens=[CLAIM_DIALOG])
check("停下", lap(t), "stop")
check("留图", "weekly_no_settlement" in t.shots)
check("报到手机、带整屏的字", len(t.errors) == 1 and t.errors[0][1] and "某个没见过的画面" in t.errors[0][0])
check("没按 ESC、没返回", [e for e in t.events if e in ("key:esc", "back")], [])
check("没重进", t.entries, 0)

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

print("\n[这一圈打没打没记到（combat_once 的钩子没跑）：不去找结晶]")
t = task(left=3, fought=None)
check("没停", lap(t), "on")
check("没走去结晶", "walk" in t.events, False)
check("留图", "weekly_fight_unknown" in t.shots)
check("说了为什么", any("打没打没记到" in m for m in t.logs))

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
