"""Echo farm: revive in place inside a realm, and stop retrying after three failures.

Runs the real overlay against stand-ins for upstream v3.7.3 (FarmEchoTask.py:91-117,
:174-179, :204-216) and checks four things:

  revive_action   inside a realm while farming echoes it clicks the dialog's own
                  「确认」 - never the 「选择复苏物品」 title (2026-09-09) - and says
                  it revived; everywhere else upstream's own revive runs
  combat_once     swallows CharRevivedException when the revive put us back at the
                  boss (is_revived: ours in a realm, upstream's in the overworld), so
                  the loop takes its `if self.is_revived: continue`; the weekly boss's
                  tower revive goes up to upstream's do_run handler, which re-teleports
  FarmEchoTask.run  upstream retries by calling run() from its own except with no
                  limit; the wrapper stops at _MAX_FARM_RETRIES and leaves the depth
                  counter at 0 for the next run
  scope           the one realm death on record (tests/replay/2026-09-01) was raised
                  from inside combat_once, which is where the overlay catches it
"""
import os
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import okww_overlay

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # removes the folder at exit, pass or fail

fails = []
REPLAY = Path(__file__).resolve().parent / "replay"


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
    """A stand-in upstream class: any method the overlay reads exists and does nothing."""
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def anything(self, *a, **kw):
            return None
        return anything


class Box:
    """ok-script's OCR box: the overlay reads .name and str()."""
    def __init__(self, name, x=0, y=0, width=10, height=10):
        self.name, self.x, self.y, self.width, self.height = name, x, y, width, height

    def __str__(self):
        return f"Box(name='{self.name}', x={self.x}, y={self.y}, width={self.width}, height={self.height})"


class BaseWWTask(metaclass=_Any):
    pass


class FarmEchoTask(BaseWWTask):
    def revive_action(self):
        # Upstream v3.7.3 FarmEchoTask.py:91-105, reduced: in a realm it hands over to
        # BaseCombatTask.revive_action (tower revive, returns True, is_revived
        # untouched); in the overworld it walks back to the boss and sets is_revived.
        self.events.append("upstream-revive")
        if not self._in_realm:
            self.is_revived = True
        return True

    def run(self):
        # Upstream v3.7.3 FarmEchoTask.py:107-117, verbatim apart from the stand-ins.
        try:
            return self.do_run()
        except Disabled:
            pass
        except Exception:
            self.log_info("farm 4c error, try handle monthly card")
            if self.handle_claim_button() or self.handle_monthly_card():
                self.run()
            else:
                raise

    def do_run(self):
        self.bodies += 1
        if self.bodies <= self.failures:
            raise RuntimeError("Teleport to boss failed")
        return "farmed"

    def handle_claim_button(self):
        return self.claim_button

    def handle_monthly_card(self):
        return False

    def combat_once(self, wait_combat_time=200, raise_if_not_found=True, target=False):
        # What BaseCombatTask.raise_not_in_combat (:310-332) does on a death: call
        # revive_action, then raise CharRevivedException when it returned True.
        if self.dies:
            if self.revive_action():
                raise Revived("combat check not in combat")
            raise RuntimeError("revive failed")
        return True


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
print("[绑定都换上了]")
for b in ("FarmEchoTask.revive_action", "FarmEchoTask.combat_once", "FarmEchoTask.run"):
    check(f"{b} 已换上", b in ns["_applied"])

# farming_echoes() is 「the no-claim flag file exists」; point it at a temp file.
tmp = str(tmpdir("ark-revive-"))
flag = os.path.join(tmp, "ark-okww-farm.no-claim")
ns["NO_CLAIM"] = flag

TITLE = Box("选择复苏物品", 820, 300, 280, 40)
CONFIRM = Box("确认", 1100, 760, 60, 30)
CANCEL = Box("取消", 760, 760, 60, 30)
ITEM = Box("复苏药剂x9", 900, 500, 120, 30)


def task(screen=(TITLE, ITEM, CANCEL, CONFIRM), in_realm=True):
    t = object.__new__(FarmEchoTask)
    t.events, t.logs, t.clicks, t.waits = [], [], [], []
    t.screen = list(screen)
    t._in_realm = in_realm
    t.is_revived = False
    t.dies = False
    t.bodies, t.failures, t.claim_button = 0, 0, True
    t.ocr = lambda box=None, **kw: list(t.screen)
    t.box_of_screen = lambda *a: a
    t.log_info = lambda msg, notify=False: t.logs.append(msg)
    t.click = lambda target, after_sleep=0: t.clicks.append(str(getattr(target, "name", target)))
    t.wait_in_team_and_world = lambda time_out=10, **kw: t.waits.append(time_out) or True
    return t


# ---------------------------------------------------------------------------
print("\n[revive_action：刷声骸、在副本里，点弹窗自己的「确认」，不点标题]")
Path(flag).write_text("")
t = task()
check("返回 True", t.revive_action(), True)
check("点的是「确认」，不是「选择复苏物品」标题", t.clicks, ["确认"])
check("等回到队伍画面（120 秒）", t.waits, [120])
check("is_revived 置上", t.is_revived, True)
check("没走上游那份", "upstream-revive" in t.events, False)
check("日志说了用复苏物品", any("角色阵亡，用一个复苏物品点「" in m for m in t.logs))

print("\n[revive_action：屏上只有标题、没有短的「确认」——不乱点]")
t = task(screen=(TITLE, ITEM, Box("确认使用复苏物品后恢复全队生命值", 0, 0)))
check("返回 False", t.revive_action(), False)
check("一下都没点", t.clicks, [])
check("日志说了没找到确认", any("没找到「确认」" in m for m in t.logs))

print("\n[revive_action：屏上不是死亡弹窗——不乱点]")
t = task(screen=(Box("挑战成功"), Box("退出副本"), CONFIRM))
check("返回 False", t.revive_action(), False)
check("一下都没点", t.clicks, [])
check("日志说了不像死亡弹窗", any("这不像死亡弹窗" in m for m in t.logs))

print("\n[revive_action：OCR 出错也不把这一趟拖垮]")
t = task()
t.ocr = lambda **kw: (_ for _ in ()).throw(RuntimeError("capture lost"))
check("返回 False", t.revive_action(), False)
check("日志说了复活没做成", any("复活这一步没做成" in m for m in t.logs))

print("\n[revive_action：不在副本 / 不在刷声骸——上游那份照跑]")
t = task(in_realm=False)
check("大世界：返回上游的结果", t.revive_action(), True)
check("大世界：走的是上游", t.events, ["upstream-revive"])
check("大世界：没点弹窗", t.clicks, [])
os.remove(flag)
t = task()
t.revive_action()
check("周本（没在刷声骸）：走的是上游", t.events, ["upstream-revive"])
check("周本：is_revived 没置上（塔边复活）", t.is_revived, False)

# ---------------------------------------------------------------------------
print("\n[combat_once：原地复活后吞掉复活异常，接着刷下一趟]")
Path(flag).write_text("")
t = task()
t.dies = True
check("返回 None，不往上抛", t.combat_once(wait_combat_time=5, raise_if_not_found=False), None)
check("is_revived 留着给上游的 continue（FarmEchoTask.py:179）", t.is_revived, True)
check("算打过", t._ark_fought, True)
check("日志：复活成功，接着刷", any("复活成功，接着刷下一趟" in m for m in t.logs))

print("\n[combat_once：上游的复活（周本）照样往上抛，交给 do_run 重新传送]")
os.remove(flag)
t = task()
t.dies = True
try:
    t.combat_once(wait_combat_time=5, raise_if_not_found=False)
    raised = False
except Revived:
    raised = True
check("CharRevivedException 往上抛", raised)
check("没说「接着刷」", any("复活成功" in m for m in t.logs), False)
check("这一圈仍算打过", t._ark_fought, True)

print("\n[combat_once：上游大世界那份复活也回到了 boss 跟前（is_revived），同样接着刷、不受 3 次上限]")
t = task(in_realm=False)
t.dies = True
check("返回 None，不往上抛", t.combat_once(), None)
check("走的是上游的复活", t.events, ["upstream-revive"])
check("is_revived 留着", t.is_revived, True)

print("\n[combat_once：没死就原样返回]")
t = task()
check("返回上游的结果", t.combat_once(), True)
check("算打过", t._ark_fought, True)

# ---------------------------------------------------------------------------
print("\n[FarmEchoTask.run：上游自己的 except 里无限重试，包一层数到 3 就停]")
cap = ns["_MAX_FARM_RETRIES"]
check("上限是 3", cap, 3)
t = task()
t.failures = 99
try:
    t.run()
    stopped = False
except Disabled:
    stopped = True
check("第 4 次调用抛 TaskDisabledException 到外面", stopped)
check("上游正文只跑了 3 次", t.bodies, cap)
check("日志：连续 3 次失败", any(f"连续 {cap} 次失败，退出本次任务，不再重试" in m for m in t.logs))
check("上游每次都记了 farm 4c error", sum("farm 4c error" in m for m in t.logs), cap)
check("深度计数归零", t._ark_depth, 0)

print("\n[FarmEchoTask.run：下一次运行从 0 数起]")
t.bodies = 0
try:
    t.run()
except Disabled:
    pass
check("又是 3 次", t.bodies, cap)
check("深度计数归零", t._ark_depth, 0)

print("\n[FarmEchoTask.run：第 2 次成了就不再报停]")
t = task()
t.failures = 1
try:
    t.run()
    stopped = False
except Disabled:
    stopped = True
check("没抛", stopped, False)
check("跑了 2 次", t.bodies, 2)
check("没说连续失败", any("连续" in m for m in t.logs), False)
check("深度计数归零", t._ark_depth, 0)

print("\n[FarmEchoTask.run：上游自己放弃（没领奖按钮也没月卡）时原样抛]")
t = task()
t.failures, t.claim_button = 99, False
try:
    t.run()
    got = None
except RuntimeError as e:
    got = str(e)
check("上游的错原样上来", got, "Teleport to boss failed")
check("只跑了 1 次", t.bodies, 1)
check("深度计数归零", t._ark_depth, 0)

# ---------------------------------------------------------------------------
print("\n[有记录的那次副本里阵亡，是在 combat_once 里抛的（覆盖面就在那儿）]")
log = (REPLAY / "2026-09-01" / "wuwa" / "OK-WW-02-01-22.log").read_text(encoding="utf-8")
dead = log.index("FarmEchoTask:raise_not_in_combat char dead")
check("2026-09-01 06:03:27 阵亡", "2026-09-01 06:03:27,238 INFO TaskExecutor FarmEchoTask:raise_not_in_combat char dead" in log)
check("上游当时复活失败", "06:03:27,239 INFO TaskExecutor FarmEchoTask:info_set Revive Failed" in log)
trace = log[dead:dead + 1500]
check("报错的那一圈停在 farm 4c error", "farm 4c error, try handle monthly card" in trace)
check("调用栈里是 do_run → combat_once", bool(re.search(r"in do_run\s+self\.combat_once\(", trace)))

for k, v in _saved.items():
    if v is None:
        sys.modules.pop(k, None)
    else:
        sys.modules[k] = v

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
