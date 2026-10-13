"""Echo farm and weekly boss: deaths go to upstream, and retries stop after three failures.

Runs the real overlay against stand-ins for upstream v3.7.4 (FarmEchoTask.py:92-106
revive_action, :108-125 run, :182-183 the is_revived continue, :216-229 the do_run
re-teleport) and checks:

  revive_action   not overridden any more (2026-10-13). Ours confirmed the revive
                  popup inside a realm while farming echoes and spent a revive item
                  per death; v3.7.4 hands a realm death to BaseCombatTask.revive_action
                  (:227-240), which cancels the popup and leaves the realm to heal,
                  and do_run re-teleports (at most 3 times per run)
  combat_once     swallows CharRevivedException only when the revive put us back at
                  the boss (is_revived: upstream's overworld revive), so the loop takes
                  its `if self.is_revived: continue`; a realm death (echo farm or
                  weekly boss) goes up to upstream's do_run handler, which re-teleports
  FarmEchoTask.run  upstream v3.7.4 retries by calling self.run(retries - 1) from its
                  own except (FarmEchoTask.py:122-123), so the wrapper must take and
                  pass on `retries` (10-13: it took none, and the retry was a
                  TypeError); it stops at _MAX_FARM_RETRIES and leaves the depth
                  counter at 0 for the next run
  scope           the one realm death on record (tests/replay/2026-09-01) was raised
                  from inside combat_once, which is where the overlay looks at it
"""
import os
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.features.okww_patch import okww_overlay

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
        # Upstream v3.7.4 FarmEchoTask.py:92-106, reduced: in a realm it hands over to
        # BaseCombatTask.revive_action (:227-240: close_revive_popup cancels the popup,
        # then leave and heal; returns True, is_revived untouched); in the overworld it
        # walks back to the boss and sets is_revived.
        if not self._in_realm:
            self.events.append("upstream-revive")
            self.is_revived = True
            return True
        self.events.append("cancel-popup")
        return True

    def run(self, retries=3):
        # Upstream v3.7.4 FarmEchoTask.py:108-125, verbatim apart from the stand-ins
        # (start_time and WWOneTimeTask.run left out): the retry is self.run(retries - 1)
        # from its own except, i.e. through whatever FarmEchoTask.run is bound to.
        self.retries_seen.append(retries)
        try:
            return self.do_run()
        except Disabled:
            pass
        except Exception:
            self.log_info("farm 4c error, try handle monthly card")
            if retries > 0 and (self.handle_claim_button() or self.handle_monthly_card()):
                self.run(retries - 1)
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
for b in ("FarmEchoTask.combat_once", "FarmEchoTask.run"):
    check(f"{b} 已换上", b in ns["_applied"])
print("[revive_action is upstream's own again]")
check("revive_action not in the applied list", "FarmEchoTask.revive_action" in ns["_applied"], False)
check("FarmEchoTask.revive_action is still upstream's function",
      FarmEchoTask.__dict__["revive_action"].__qualname__, "FarmEchoTask.revive_action")
check("the overlay source has no revive_action override",
      '@override(FarmEchoTask, "revive_action")' in okww_overlay.source_text(), False)

# farming_echoes() is 「the no-claim flag file exists」; point it at a temp file.
tmp = str(tmpdir("ark-revive-"))
flag = os.path.join(tmp, "ark-okww-farm.no-claim")
ns["NO_CLAIM"] = flag

def task(in_realm=True):
    t = object.__new__(FarmEchoTask)
    t.events, t.logs, t.clicks, t.waits = [], [], [], []
    t._in_realm = in_realm
    t.is_revived = False
    t.dies = False
    t.bodies, t.failures, t.claim_button = 0, 0, True
    t.retries_seen = []
    t.log_info = lambda msg, notify=False: t.logs.append(msg)
    t.log_error = lambda msg, notify=False, **kw: t.logs.append(msg)
    t.click = lambda target, after_sleep=0: t.clicks.append(str(getattr(target, "name", target)))
    t.wait_in_team_and_world = lambda time_out=10, **kw: t.waits.append(time_out) or True
    return t


# ---------------------------------------------------------------------------
print("\n[revive_action: a realm death while farming echoes runs upstream's revive (cancel the popup), no revive item]")
Path(flag).write_text("")
t = task()
check("returns upstream's result", t.revive_action(), True)
check("upstream cancelled the popup", t.events, ["cancel-popup"])
check("nothing clicked by the overlay (no 「确认」, no revive item)", t.clicks, [])
check("is_revived not set (do_run re-teleports)", t.is_revived, False)
os.remove(flag)

# ---------------------------------------------------------------------------
print("\n[combat_once: a realm death while farming echoes goes up to upstream's do_run re-teleport]")
Path(flag).write_text("")
t = task()
t.dies = True
try:
    t.combat_once(wait_combat_time=5, raise_if_not_found=False)
    raised = False
except Revived:
    raised = True
check("CharRevivedException goes up (do_run: re-teleport, cap 3)", raised)
check("did not say it carries on in place", any("复活成功" in m for m in t.logs), False)
os.remove(flag)

print("\n[combat_once：上游的复活（周本）照样往上抛，交给 do_run 重新传送]")
t = task()
t.dies = True
try:
    t.combat_once(wait_combat_time=5, raise_if_not_found=False)
    raised = False
except Revived:
    raised = True
check("CharRevivedException 往上抛", raised)
check("没说「接着刷」", any("复活成功" in m for m in t.logs), False)

print("\n[combat_once：上游大世界那份复活也回到了 boss 跟前（is_revived），同样接着刷、不受 3 次上限]")
t = task(in_realm=False)
t.dies = True
check("返回 None，不往上抛", t.combat_once(), None)
check("走的是上游的复活", t.events, ["upstream-revive"])
check("is_revived 留着", t.is_revived, True)

print("\n[combat_once：没死就原样返回]")
t = task()
check("返回上游的结果", t.combat_once(), True)

# ---------------------------------------------------------------------------
print("\n[FarmEchoTask.run：上游自己的 except 里无限重试，包一层数到 3 就停——按失败结束，不是跳过]")
cap = ns["_MAX_FARM_RETRIES"]
check("上限是 3", cap, 3)
t = task()
t.failures = 99
got = None
try:
    t.run()
except Exception as e:  # noqa: BLE001
    got = e
check("连续失败：任务按失败结束（OK-WW 记失败的普通异常）", type(got).__name__, "ArkStopped")
check("不是 OK-WW 的「跳过」（TaskDisabledException）", isinstance(got, Disabled), False)
check("失败原因写在异常里", str(got), f"连续 {cap} 次失败，退出本次任务，不再重试")
check("上游正文只跑了 3 次", t.bodies, cap)
check("日志：连续 3 次失败", any(f"连续 {cap} 次失败，退出本次任务，不再重试" in m for m in t.logs))
check("日志：按失败结束", any(m.startswith(ns["FAILED_MARK"]) for m in t.logs))
check("上游每次都记了 farm 4c error", sum("farm 4c error" in m for m in t.logs), cap)
check("深度计数归零", t._ark_depth, 0)

print("\n[FarmEchoTask.run：下一次运行从 0 数起]")
t.bodies = 0
try:
    t.run()
except ns["ArkStopped"]:
    pass
check("又是 3 次", t.bodies, cap)
check("深度计数归零", t._ark_depth, 0)

print("\n[FarmEchoTask.run：中途认不出的画面停下（_stop）——上游 run() 照常收尾，最外层按失败结束]")
t = task()
t.screenshot = lambda name: t.events.append(f"shot {name}")


def _odd_lap(self=t):
    self.bodies += 1
    ns["_stop"](self, "weekly_claim_unchanged", "周本领奖：回读次数没变（2/3），这次没领到")
t.do_run = _odd_lap
got = None
try:
    t.run()
except Exception as e:  # noqa: BLE001
    got = e
check("按失败结束", (type(got).__name__, str(got)), ("ArkStopped", "周本领奖：回读次数没变（2/3），这次没领到"))
check("上游的 except TaskDisabledException 收了这一停：没重试、没 farm 4c error",
      (t.bodies, any("farm 4c error" in m for m in t.logs)), (1, False))
check("留了图", "shot weekly_claim_unchanged" in t.events, True)
check("深度计数归零、原因清掉", (t._ark_depth, t._ark_failed), (0, None))

print("\n[FarmEchoTask.run: a waveplate shortage (_skip_short) is a normal state - returns, no FAILED_MARK, no ArkStopped]")
t = task()


def _short_lap(self=t):
    self.bodies += 1
    self.log_info("波片不足挡住开启挑战，点取消跳过本次周本")
    ns["_skip_short"](self)
t.do_run = _short_lap
got = "returned"
try:
    t.run()
except Exception as e:  # noqa: BLE001
    got = e
check("缺波片：正常返回，不抛 ArkStopped", got, "returned")
check("缺波片：日志没有按失败结束", any(m.startswith(ns["FAILED_MARK"]) for m in t.logs), False)
check("缺波片：上游收了这一停，没重试", (t.bodies, any("farm 4c error" in m for m in t.logs)), (1, False))
check("缺波片：深度归零、没留原因", (t._ark_depth, t._ark_failed), (0, None))

print("\n[FarmEchoTask.run: a non-waveplate stop right after still raises ArkStopped]")
t = task()
t.screenshot = lambda name: t.events.append(f"shot {name}")


def _odd_lap2(self=t):
    self.bodies += 1
    ns["_stop"](self, "weekly_claim_unchanged", "周本领奖：回读次数没变（2/3），这次没领到")
t.do_run = _odd_lap2
got = None
try:
    t.run()
except Exception as e:  # noqa: BLE001
    got = e
check("非波片停下仍按失败结束", (type(got).__name__, str(got)), ("ArkStopped", "周本领奖：回读次数没变（2/3），这次没领到"))
check("非波片停下：日志写了按失败结束", any(m.startswith(ns["FAILED_MARK"]) for m in t.logs), True)

print("\n[FarmEchoTask.run：真没事可做（上游自己的跳过）照旧是跳过]")
t = task()


def _done_lap(self=t):
    self.bodies += 1
    raise Disabled()
t.do_run = _done_lap
got = "returned"
try:
    t.run()
except Exception as e:  # noqa: BLE001
    got = e
check("上游的跳过：正常返回，不算失败", got, "returned")

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
check("v3.7.4 retry count passed through the wrapper: 3, then 2", t.retries_seen, [3, 2])

print("\n[FarmEchoTask.run: v3.7.4 self.run(retries - 1) goes through the wrapper without a TypeError]")
t = task()
t.failures = 1
got = None
try:
    got = t.run()
except TypeError as e:  # the 10-13 bug: the wrapper was def run(self)
    got = f"TypeError: {e}"
check("retry after one failure returns upstream's result", got, None)
check("upstream body ran twice", t.bodies, 2)
check("each retry reached upstream with one less", t.retries_seen, [3, 2])
t = task()
t.failures = 0
check("run(retries=1) reaches upstream as 1", (t.run(1), t.retries_seen), ("farmed", [1]))

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
