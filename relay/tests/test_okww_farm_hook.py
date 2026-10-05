"""Daily task: additional tasks first, the stamina farm to empty, one settlement shot.

Runs the real overlay against a stand-in for upstream v3.7.3 DailyTask.run
(DailyTask.py:77-136, reduced to its calls) and the three farm_* methods, with the
numbers the game showed on 2026-09-07 (tests/replay/2026-09-07/wuwa):

  open_daily_first      the weekly boss (additional tasks) runs before the daily's
                        stamina read; its error does not take the daily down; the
                        trailing run_additional_tasks is a no-op; the next run resets
  _farm_hook            farm_tacet / farm_forgery / farm_simulation lose daily= and
                        used_stamina= (must_use 0: farm to empty); the no-farm flag
                        file stops all three
  claim_daily           upstream farms only when `not daily_reward_ready and
                        used_stamina < 180` (DailyTask.py:88-89). After the weekly
                        boss spent 180 the gate is shut and the rest of the stamina
                        sat unused; the overlay farms it before claim_daily
  use_stamina           the tacet settlement keeps one screenshot (tacet_drops) when
                        the farm stops there
  get_stamina           the 数/数 read, with the real OCR text, in and out of the
                        reward dialog
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
REPLAY = Path(__file__).resolve().parent / "replay" / "2026-09-07" / "wuwa"


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def logged(path, lineno, pattern):
    """The integer `pattern` captures on line `lineno` of a replay log (1-based)."""
    # Bytes, not read_text: the logs mix CRLF with bare CR, and universal newlines
    # would count the bare CRs as lines and shift every number grep -n gives.
    line = path.read_bytes().decode("utf-8").split("\n")[lineno - 1].rstrip("\r")
    m = re.search(pattern, line)
    assert m, f"{path.name}:{lineno} no longer reads {pattern!r}: {line}"
    return int(m.group(1))


# Real numbers. OK-WW-07-27-50.log:410-411 read the daily after the farm had spent
# 180 (the old copy farmed on anyway: :419-420 read 75 + 26 and went in);
# OK-WW-06-08-44.log:131 read 120 earlier that morning.
DAY = REPLAY / "OK-WW-07-27-50.log"
USED_FULL = logged(DAY, 410, r"DailyTask:info_set current daily progress (\d+)$")
POINTS = logged(DAY, 411, r"DailyTask:info_set total daily points (\d+)$")
CURRENT = logged(DAY, 419, r"TacetTask:info_set current_stamina (\d+)$")
BACK_UP = logged(DAY, 420, r"TacetTask:info_set back_up_stamina (\d+)$")
USED_PART = logged(REPLAY / "OK-WW-06-08-44.log", 131, r"current daily progress (\d+)$")


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


number_re = re.compile(r"^(\d+)$")
stamina_re = re.compile(r"^(\d+)/(\d+)$")
EV = []          # one call order across every task object


class Box:
    def __init__(self, name, x=0):
        self.name, self.x = name, x


class BaseWWTask(metaclass=_Any):
    # Upstream v3.7.3 BaseWWTask.py:409-424, verbatim: the overlay replaces it only
    # while its source still hashes to the pin (8ba6c1344ff8).
    def get_stamina(self):
        boxes = self.wait_ocr(0.49, 0.0, 0.92, 0.10, raise_if_not_found=False,
                              match=[number_re, stamina_re])
        if not boxes:
            self.screenshot('stamina_error')
            return -1, -1, -1
        current = 0
        back_up = 0
        for box in boxes:
            if match := stamina_re.search(box.name):
                current = int(match.group(1))
            elif match := number_re.search(box.name):
                back_up = int(match.group(1))
        self.info_set('current_stamina', current)
        self.info_set('back_up_stamina', back_up)
        return current, back_up, current + back_up


class TacetTask(BaseWWTask):
    def farm_tacet(self, daily=False, used_stamina=0, config=None, max_recovery_retries=3):
        # TacetTask.py:48-55: must_use is how much the daily step insists on spending.
        must_use = 180 - used_stamina if daily else 0
        EV.append(("farm_tacet", must_use, config))
        if self.farm_error:
            raise self.farm_error

    def use_stamina(self, once, must_use=0):
        # Upstream reads the stamina inside the reward dialog; the overlay's
        # get_stamina keys on this caller's name.
        self.read = self.get_stamina()
        return self.result


class ForgeryTask(BaseWWTask):
    def farm_forgery(self, daily=False, used_stamina=0, config=None):
        EV.append(("farm_forgery", 180 - used_stamina if daily else 0, config))


class SimulationTask(BaseWWTask):
    def farm_simulation(self, daily=False, used_stamina=0, config=None):
        EV.append(("farm_simulation", 180 - used_stamina if daily else 0, config))


class DailyTask(BaseWWTask):
    def run(self):
        # Upstream v3.7.3 DailyTask.py:77-136, the calls in order (validation, login
        # and the nightmare nest left out).
        used_stamina, daily_reward_ready = self.open_daily()
        need_stamina = not daily_reward_ready and used_stamina < 180
        if need_stamina:
            target = self.config.get('Which to Farm', self.support_tasks[0])
            if target == self.support_tasks[0]:
                self.get_task_by_class(TacetTask).farm_tacet(daily=True, used_stamina=used_stamina,
                                                             config=self.config)
            elif target == self.support_tasks[1]:
                self.get_task_by_class(ForgeryTask).farm_forgery(daily=True, used_stamina=used_stamina,
                                                                 config=self.config)
            else:
                self.get_task_by_class(SimulationTask).farm_simulation(daily=True, used_stamina=used_stamina,
                                                                       config=self.config)
            self.sleep(4)
        self.claim_daily()
        self.claim_mail()
        self.sleep(1)
        self.claim_battle_pass()
        self.run_additional_tasks()
        self.log_info('Daily Task Completed', notify=True)

    def open_daily(self):
        EV.append("open_daily")
        return self.used, self.points >= 100

    def run_additional_tasks(self):
        EV.append("additional")
        if self.additional_error:
            raise self.additional_error

    def claim_daily(self):
        EV.append("claim_daily")

    def claim_mail(self):
        EV.append("claim_mail")

    def claim_battle_pass(self):
        EV.append("claim_battle_pass")


mods = {
    "ok": types.SimpleNamespace(TaskDisabledException=Disabled,
                                Logger=types.SimpleNamespace(get_logger=lambda n: types.SimpleNamespace(
                                    info=lambda *a, **k: None, error=lambda *a, **k: None))),
    "src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
    "src.task.BaseCombatTask": types.SimpleNamespace(CharRevivedException=Revived),
    "src.task.BaseWWTask": types.SimpleNamespace(BaseWWTask=BaseWWTask),
    "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=_Any("FarmEchoTask", (), {})),
    "src.task.DailyTask": types.SimpleNamespace(DailyTask=DailyTask),
    "src.task.TacetTask": types.SimpleNamespace(TacetTask=TacetTask),
    "src.task.ForgeryTask": types.SimpleNamespace(ForgeryTask=ForgeryTask),
    "src.task.SimulationTask": types.SimpleNamespace(SimulationTask=SimulationTask),
}
_saved = {k: sys.modules.get(k) for k in mods}
sys.modules.update(mods)

ns = {}
exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
print("[绑定都换上了]")
for b in ("DailyTask.run", "DailyTask.open_daily", "DailyTask.run_additional_tasks", "DailyTask.claim_daily",
          "TacetTask.farm_tacet", "ForgeryTask.farm_forgery", "SimulationTask.farm_simulation",
          "TacetTask.use_stamina", "BaseWWTask.get_stamina"):
    check(f"{b} 已换上", b in ns["_applied"])

tmp = str(tmpdir("ark-farm-hook-"))
no_farm = os.path.join(tmp, "no-stamina-farm.flag")
ns["NO_STAMINA_FLAG"] = no_farm
SUPPORT = ["Tacet Suppression", "Forgery Challenge", "Simulation Challenge"]


def wire(t):
    t.logs, t.shots, t.sleeps, t.info = [], [], [], {}
    t.log_info = lambda msg, notify=False: t.logs.append(msg)
    t.log_error = lambda msg, exception=None: t.logs.append(msg)
    t.screenshot = lambda name: t.shots.append(name)
    t.sleep = lambda s: t.sleeps.append(s)
    t.info_set = lambda k, v: t.info.__setitem__(k, v)
    t.ensure_main = lambda time_out=30: EV.append("ensure_main")
    return t


def daily(used, points=POINTS, target=SUPPORT[0], additional_error=None, farm_error=None):
    EV.clear()
    farms = {c: wire(object.__new__(c)) for c in (TacetTask, ForgeryTask, SimulationTask)}
    farms[TacetTask].farm_error = farm_error
    d = wire(object.__new__(DailyTask))
    d.used, d.points, d.additional_error = used, points, additional_error
    d.config = {"Which to Farm": target}
    d.support_tasks = SUPPORT
    d.get_task_by_class = lambda cls: farms[cls]
    d.farms = farms
    return d


def farm_calls():
    return [e for e in EV if isinstance(e, tuple)]


# ---------------------------------------------------------------------------
print(f"\n[附加任务（周本）排在读日常之前；尾巴上那次是空操作。已用 {USED_PART}/180]")
d = daily(USED_PART)
d.run()
check("顺序：附加任务 → 读日常 → 刷体力 → 领日常", EV,
      ["additional", "open_daily", ("farm_tacet", 0, d.config), "claim_daily", "claim_mail",
       "claim_battle_pass"])
check("附加任务只跑了一次（上游尾巴那次没再跑）", EV.count("additional"), 1)
check("刷体力丢掉了 daily=/used_stamina=：must_use 0，刷到空", farm_calls()[0][1], 0)
check("上游自己刷了，就不补刷", any("上游这趟不刷体力" in m for m in d.logs), False)
check("上游读到的数留着", getattr(d, "_ark_daily_read", None), (USED_PART, False))

print("\n[同一个实例跑第二趟：附加任务照样先跑]")
d.run()
check("第二趟也有附加任务", EV.count("additional"), 2)
check("第二趟附加任务仍在读日常之前", EV.index("additional", 6) < EV.index("open_daily", 6))

print("\n[附加任务出错不拖垮当趟日常]")
d = daily(USED_PART, additional_error=RuntimeError("Teleport to boss failed"))
d.run()
check("记了错", any("附加任务出错，不拖垮当趟日常" in m for m in d.logs))
check("留了图", d.shots, ["additional_tasks_error"])
check("日常照跑：刷体力、领日常都在", farm_calls() != [] and "claim_daily" in EV)
check("尾巴上没有再跑一次", EV.count("additional"), 1)

print("\n[附加任务里主动停（TaskDisabledException）也只记一笔，日常照跑]")
d = daily(USED_PART, additional_error=Disabled())
d.run()
check("日常照跑", "claim_daily" in EV)

# ---------------------------------------------------------------------------
print(f"\n[周本花掉 {USED_FULL}：上游的闸门关了，剩下的 {CURRENT} + {BACK_UP} 照样刷掉]")
d = daily(USED_FULL)
d.run()
check(f"读到已用 {USED_FULL}/180、活跃度 {POINTS}（OK-WW-07-27-50.log:410-411）",
      getattr(d, "_ark_daily_read", None), (USED_FULL, False))
check("补刷了一次无音区，must_use 0", farm_calls(), [("farm_tacet", 0, d.config)])
check("补刷在领日常之前", EV.index(("farm_tacet", 0, d.config)) < EV.index("claim_daily"))
check("说了为什么补刷", any(f"上游这趟不刷体力（已用 {USED_FULL}/180" in m for m in d.logs))
check("补刷后照上游那样等 4 秒", 4 in d.sleeps)
check("「Daily Task Completed」在补刷之后（中继拿它当收尾）",
      d.logs.index("Daily Task Completed") > next(i for i, m in enumerate(d.logs) if "上游这趟不刷体力" in m))

print("\n[活跃度已满 100：上游也不刷，照样补刷]")
d = daily(0, points=100)
d.run()
check("补刷了一次", farm_calls(), [("farm_tacet", 0, d.config)])
check("只刷了一次", len(farm_calls()), 1)

print("\n[凝素领域 / 模拟领域：上游刷时丢参数，上游不刷时补刷的是同一个]")
for target, name in ((SUPPORT[1], "farm_forgery"), (SUPPORT[2], "farm_simulation")):
    d = daily(USED_PART, target=target)
    d.run()
    check(f"{name}：上游刷，must_use 0", farm_calls(), [(name, 0, d.config)])
    d = daily(USED_FULL, target=target)
    d.run()
    check(f"{name}：上游不刷，补刷的也是它", farm_calls(), [(name, 0, d.config)])

print("\n[补刷出错：记一笔、回主界面，日常奖励照领]")
d = daily(USED_FULL, farm_error=RuntimeError("can't find gray_book_boss"))
d.run()
check("记了错", any("补刷体力出错，照常领日常奖励" in m for m in d.logs))
check("留了图", d.shots, ["leftover_farm_error"])
check("回了主界面再领", EV.index("ensure_main") < EV.index("claim_daily"))
check("日常奖励照领", "claim_daily" in EV)

print("\n[补刷时主动停（TaskDisabledException）照原样往上抛]")
d = daily(USED_FULL, farm_error=Disabled())
try:
    d.run()
    raised = False
except Disabled:
    raised = True
check("往上抛", raised)
check("没领日常", "claim_daily" in EV, False)

print("\n[标记文件在：三种刷体力都不花波片，补刷那条也不花]")
Path(no_farm).write_text("")
for used in (USED_PART, USED_FULL):
    d = daily(used)
    d.run()
    farm = d.farms[TacetTask]
    check(f"已用 {used}：一次都没进本", farm_calls(), [])
    check(f"已用 {used}：说了刷体力已禁用", any("刷体力已禁用（标记文件在）" in m for m in farm.logs))
check("补刷那条没有重复禁用的话", sum("刷体力已禁用" in m for m in d.farms[TacetTask].logs), 1)
for cls, name in ((ForgeryTask, "farm_forgery"), (SimulationTask, "farm_simulation")):
    EV.clear()
    t = wire(object.__new__(cls))
    check(f"{name} 也挡住", getattr(t, name)(daily=True, used_stamina=0, config={}), None)
    check(f"{name} 没进本", farm_calls(), [])
os.remove(no_farm)

# ---------------------------------------------------------------------------
print("\n[无音区结算：刷不动了停在结算页，留一张 tacet_drops]")
t = wire(object.__new__(TacetTask))
t.wait_ocr = lambda *a, **kw: [Box(str(BACK_UP), 1), Box(f"{CURRENT}/240", 2)]
t.result = (False, 60)
check("返回值原样", t.use_stamina(once=60, must_use=0), (False, 60))
check("留了图", t.shots, ["tacet_drops"])
t.result = (True, 60)
t.shots = []
check("还能接着刷：返回值原样", t.use_stamina(once=60, must_use=0), (True, 60))
check("还能接着刷：不留图", t.shots, [])

print("\n[体力读数：领奖框里读字原文进日志，真实文本]")
t.result = (False, 60)
t.use_stamina(once=60)
check(f"读到 {CURRENT}+{BACK_UP}（OK-WW-07-27-50.log:419-420）", t.read, (CURRENT, BACK_UP, CURRENT + BACK_UP))
check("current_stamina 照上游记", t.info.get("current_stamina"), CURRENT)
check("读字原文进了日志（领奖框）", any(m.startswith("体力读字原文领奖框（第 1 次）") for m in t.logs))

# 2026-09-21 10:25:49 (test_m6_okww.py:52): the reward dialog showed 剩余180 with no
# 数/数 at all; upstream took that as 0. Five reads 1 s apart, then unknown, not 0.
t = wire(object.__new__(TacetTask))
t.wait_ocr = lambda *a, **kw: [Box("挑战成功", 1), Box("剩余180", 2)]
t.result = (True, 60)
t.use_stamina(once=60)
check("一直没有 数/数：-1，不当 0", t.read, (-1, -1, -1))
check("领奖框里读了 5 次", sum(m.startswith("体力读字原文领奖框") for m in t.logs), 5)
check("每次之间睡 1 秒", t.sleeps, [1, 1, 1, 1])
check("留了 stamina_error 图", "stamina_error" in t.shots)

# 2026-09-13 09:33:01 (test_outcome.py:127): outside the dialog, one read.
t = wire(object.__new__(TacetTask))
t.wait_ocr = lambda *a, **kw: [Box("55", 1), Box("239/240", 2), Box("+", 3)]
check("书页上读一次：239 + 55", t.get_stamina(), (239, 55, 294))
check("书页上只读一次", sum(m.startswith("体力读字原文") for m in t.logs), 1)

for k, v in _saved.items():
    if v is None:
        sys.modules.pop(k, None)
    else:
        sys.modules[k] = v

print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
