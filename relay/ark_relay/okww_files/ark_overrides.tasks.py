"""Ark's changes to OK-WW, installed without editing a single upstream file.

ok-script has a documented extension point: with `custom_tasks: True` (which
ok-wuthering-waves sets in its own config.py) the task manager creates an
`ok_tasks/` folder in the working directory and **executes every .py in it** at
startup, before any task runs. It only executes a file that defines at least one
top-level class, so `_Marker` below is load-bearing even though it does nothing.

Running there lets this file rebind methods on upstream's own classes. Python
looks a method up on the class at call time, so a rebind reaches instances that
were already constructed - including the built-in FarmEchoTask that DailyTask
finds through `get_task_by_class`. Subclassing cannot do that: that lookup
returns the first matching instance and the built-ins are registered first.

**Every rebind is checked before it happens.** A method that upstream renamed or
refactored away would otherwise be replaced under a name nobody calls, and the
behaviour would go missing without a word - the exact failure the text patches
kept producing. What was checked, applied and skipped is written to
`ark-okww-overlay.json`, which the relay reads at boot and pushes.
"""
import hashlib
import inspect
import json
import os
import traceback

REPORT = r"C:\ProgramData\ark-okww-overlay.json"
NO_CLAIM = "C:/ProgramData/ark-okww-farm.no-claim"

_applied: "list[str]" = []
_skipped: "list[dict]" = []


def _src_sha(fn) -> str:
    try:
        return hashlib.sha1(inspect.getsource(fn).encode("utf-8")).hexdigest()[:12]
    except (OSError, TypeError):
        return ""


def override(cls, name, *, expect_sha=None):
    """Rebind `cls.name`, but only when upstream still looks the way we think.

    `expect_sha` is for a method we copied wholesale: when upstream's own source
    changes, our copy is stale by definition and applying it would quietly undo
    their fix. Without it, the check is just that the attribute exists.
    """
    def wrap(fn):
        label = f"{cls.__name__}.{name}"
        old = getattr(cls, name, None)
        if old is None:
            _skipped.append({"what": label, "why": "上游没有这个方法了（改名或删了）"})
            return fn
        if expect_sha:
            got = _src_sha(old)
            if got != expect_sha:
                _skipped.append({"what": label,
                                 "why": f"上游正文变了（现在 {got or '读不到'}，我们照着 {expect_sha} 抄的）"})
                return fn
        setattr(cls, name, fn)
        _applied.append(label)
        return fn
    return wrap


def farming_echoes() -> bool:
    """True while the relay is farming 4-cost echoes."""
    return os.path.exists(NO_CLAIM)


class _Marker:
    """ok-script only executes a file that defines a class. This is that class."""


def _install():
    from src.task.FarmEchoTask import FarmEchoTask

    @override(FarmEchoTask, "revive_action")
    def revive_action(self):
        # Inside a realm upstream gives up on reviving - there is no teleport tower
        # to run back to - so one death stops the whole task. For an overnight farm
        # that means standing still until morning. The death dialog is on screen and
        # OK-WW already recognises it, so find the confirm button by its own text and
        # take the next lap. **By text, not by position**: the dialog is titled
        # 「选择复苏物品」, and matching 复苏 clicked the title itself on 2026-09-09.
        if not self._in_realm:
            self.teleport_to_heal()
            self.run_until(lambda: False, 's', 1, running=True)
            self.teleport_to_nearest_boss()
            self.sleep(0.5)
            self.run_until(lambda: self.in_combat() or self.find_treasure_icon(),
                           'w', time_out=12, running=True, target=True)
            self.execute_treasure_hunt()
            self.is_revived = True
            return True
        if not farming_echoes():
            return False
        try:
            found = self.ocr(box=self.box_of_screen(0.0, 0.0, 1.0, 1.0)) or []
            text = ' '.join(str(b) for b in found)
            if '复苏物品' not in text and '复活' not in text:
                self.log_info(f'刷声骸模式：这不像死亡弹窗，不乱点。整屏读到 {found}')
                return False
            button = None
            for b in found:
                name = str(getattr(b, 'name', '') or '').strip()
                if '确认' in name and len(name) <= 6:
                    button = b
                    break
            if button is None:
                self.log_info(f'刷声骸模式：死亡弹窗上没找到「确认」，整屏读到 {found}')
                return False
            self.log_info(f'刷声骸模式：角色阵亡，用一个复苏物品点「{button}」，接着刷')
            self.click(button, after_sleep=3)
            self.wait_in_team_and_world(time_out=120)
            self.is_revived = True
            return True
        except Exception as e:  # noqa: BLE001 - a failed revive must not kill the run
            self.log_info(f'刷声骸模式：复活这一步没做成 {e!r}')
            return False


def _write_report(error=""):
    try:
        with open(REPORT, "w", encoding="utf-8") as fh:
            json.dump({"applied": _applied, "skipped": _skipped, "error": error},
                      fh, ensure_ascii=False)
    except OSError:
        pass


try:
    _install()
except Exception:  # noqa: BLE001 - never stop OK-WW from starting
    _write_report(traceback.format_exc()[-800:])
else:
    _write_report()
