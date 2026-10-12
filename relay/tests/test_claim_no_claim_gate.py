"""The claim patch must never spend waveplates while the 4-cost echo farm runs.

Claiming a boss reward costs 60 waveplates every time. Farming echoes is free. On
2026-09-09 the time-bounded farm was wired onto the very branch that claims, so an
unattended overnight run would have drained the waveplates and then the reserve.
The gate is a marker file the relay writes while farming; this pins both halves of
it together so neither can drift away from the other.

Since 2026-09-09 (d035709a) the gate lives in the ok_tasks overlay's incr_drop (the
old text patch and the code that restored it were removed 2026-10-12), so the gate is
tested on the overlay that actually runs.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
from ark_relay.features.echofarm import echofarm
from ark_relay.features.okww_patch import okww_overlay

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


class FarmEchoTask:
    def incr_drop(self, dropped):
        self.events.append("upstream-incr")

    def handle_claim_button(self):
        # Upstream's own (BaseWWTask.handle_claim_button): ESC, i.e. 取消.
        self.events.append("upstream-esc")
        return True


_mods = {"src": types.ModuleType("src"), "src.task": types.ModuleType("src.task"),
         "src.task.FarmEchoTask": types.SimpleNamespace(FarmEchoTask=FarmEchoTask)}
_saved = {k: sys.modules.get(k) for k in _mods}
sys.modules.update(_mods)
ns = {}
exec(compile(okww_overlay.source_text(), "ark_overrides.py", "exec"), ns)
ns["_install_claim"]()
for k, v in _saved.items():
    if v is None:
        sys.modules.pop(k, None)
    else:
        sys.modules[k] = v


class Task(FarmEchoTask):
    """Inside the weekly realm right after a fight: everything the claim would touch."""
    def __init__(self, boss="Weekly Challenge"):
        self.events, self._in_realm = [], True
        self.config = {"Teleport to Boss": boss}
        for name in ("in_world", "walk_to_treasure", "pick_f", "click_dialog_right_button", "ocr",
                     "send_key", "back", "click", "teleport_to_configured_boss_and_prepare"):
            setattr(self, name, (lambda n: lambda *a, **kw: self.events.append(n))(name))
        self.in_world = lambda: False
        self.wait_until = lambda cond, **kw: cond()
        self.find_treasure_icon = lambda: True
        self.log_info = lambda msg: self.events.append(f"log:{msg}")


print("[改动文件里的闸：挂着标记时，打完周本什么都不碰]")
flag = tmpdir() / "ark-okww-farm.no-claim"
ns["NO_CLAIM"] = str(flag)
flag.write_text("farming 4c echoes\n", encoding="utf-8")
try:
    t = Task()
    t.incr_drop(True)
finally:
    flag.unlink()
check("上游的掉落计数照跑", t.events[:1], ["upstream-incr"])
check("没走去结晶、没按 F、没点确认、没重进", t.events[1:], [])
flag.write_text("farming 4c echoes\n", encoding="utf-8")
try:
    t = Task()
    t.handle_claim_button()
finally:
    flag.unlink()
check("挂着标记时领奖弹窗照上游按 ESC（取消），不点确认", t.events, ["upstream-esc"])
t = Task()
t.ocr = lambda *a, **kw: []
t.box_of_screen = lambda *a: None
t.sleep = lambda s: None
t.log_error = lambda msg, notify=False: t.events.append(f"err:{msg}")
t.incr_drop(True)
check("摘掉标记：同一圈会去结晶按 F（闸真的是那个文件）", [e for e in t.events if not e.startswith("log:")][1:3],
      ["walk_to_treasure", "pick_f"])
check("按 F 后没领到（这里假的 pick_f 什么都没弹）：不停、不报错、不重进",
      [e for e in t.events if e.startswith("err:") or e == "teleport_to_configured_boss_and_prepare"], [])

print("[中继写的路径和改动文件读的路径是同一个]")
name = Path(echofarm.NO_CLAIM.replace("\\", "/")).name
check(f"文件名一致（{name}）", Path(okww_overlay.source_text().split('NO_CLAIM = "')[1].split('"')[0]).name, name)

print("[刷声骸走的是强敌（Boss Challenge），领奖钩子本来就不碰；上游自己退本再按 F 重进]")
t = Task(boss="Boss Challenge")
t.incr_drop(True)
check("强敌：只跑上游的掉落计数", t.events, ["upstream-incr"])
t = Task(boss="Boss Challenge")
t.handle_claim_button()
check("强敌：领奖弹窗照上游按 ESC", t.events, ["upstream-esc"])
check("中继刷声骸写的是 Boss Challenge", '"Teleport to Boss": "Boss Challenge"' in Path(echofarm.__file__).read_text(encoding="utf-8"))
check("不补「不退本按 F 重进」的理由写在钩子里", "enter_configured_boss_realm_from_f" in okww_overlay.source_text()
      and "FarmEchoTask.py:147-152" in okww_overlay.source_text())

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
