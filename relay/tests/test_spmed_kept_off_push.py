"""A MaaEnd task the relay keeps off because it cannot tell whether upstream fixed it
is pushed, not only logged (2026-10-06 audit).

gameupdate.maaend_reenable_spmed_if_updated used to switch 应急理智加强剂 back on
for an unknown node shape with 「要是明天又失败就再关」 - nothing in the relay ever
switches it off again. It now keeps the task off and adds a line to `problems`;
boot_stages._stage_reenable_maaend must push those lines under the same title as
boot_check's problems (「⚠️ 游戏更新没能确认」, info route, docs/NOTIFICATIONS.md).
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for name in ("win32serviceutil", "win32service", "win32event", "win32api",
             "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(name, _Stub(name))

import boot_stages                                   # noqa: E402
from ark_relay import gameupdate as gu, mastercfg, notify  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class Notifier:
    def __init__(self): self.sent = []
    def send(self, title, body, **k): self.sent.append((title, body))


class Log:
    def __init__(self): self.lines = []
    def info(self, *a, **k): self.lines.append(("info", a))
    def warning(self, *a, **k): self.lines.append(("warning", a))
    def exception(self, *a, **k): self.lines.append(("exception", a))


LINE = "终末地：MaaEnd 已是 v2.28.0-beta.4，加强剂那一步的写法认不出（这一步里有：next、action），看不出修没修，任务继续关着"
gu.maaend_reenable_if_updated = lambda cfg: ""
gu.maaend_reenable_next_boot = lambda cfg: ""
gu.maaend_reenable_spmed_if_updated = lambda cfg, problems=None: problems.append(LINE) or ""
mastercfg.prune_maaend_orphans = lambda *a: ([], "")
mastercfg.migrate_maaend_options = lambda *a: ([], "")

print("[加强剂认不出写法 → 继续关着，推「游戏更新没能确认」]")
n, lg = Notifier(), Log()
boot_stages._stage_reenable_maaend(types.SimpleNamespace(automas_dir=None, maaend_dir=None, state_dir=None), n, lg)
check("推了一条，标题 = 游戏更新没能确认（1 项）", n.sent, [("⚠️ 游戏更新没能确认（1 项）", "· " + LINE)])
check("没说「已开回」", any("已开回" in t for t, _b in n.sent), False)
check("这个标题走 info，不进群", notify.route_of("⚠️ 游戏更新没能确认（1 项）"), "info")
# Later steps of the stage (route restore) need a real AUTO-MAS dir; only the
# re-enable step is under test here.
check("开回那一步没出错", [x for x in lg.lines if x == ("exception", ("开回 MaaEnd 任务出错",))], [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
