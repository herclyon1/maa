"""「新的一周」通知要带上鸣潮周本（用户 2026-09-07）。

2026-09-07（周一）08:48 的通知只有「新的一周，剿灭已重新开启」，
周本那边 weeklyboss.json 里 done_week 还是上周（2026-W36），
用户看不到周本这周会不会打、打哪个、打几次。
"""
import json, os, sys, types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import weeklyboss as W
from ark_relay.config import SERVER_TZ

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402
TMP = tmpdir()
os.environ["ARK_OKWW_LOG"] = str(TMP / "ok.log")
STATE = TMP / "state"; STATE.mkdir()
CFG = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"; CFG.mkdir(parents=True)
(CFG / "DailyTask.json").write_text(json.dumps({W.KEY: []}), encoding="utf-8")
(CFG / "FarmEchoTask.json").write_text(json.dumps({}), encoding="utf-8")

MON = datetime(2026, 9, 7, 8, 48, tzinfo=SERVER_TZ)          # 2026-W37
(STATE / "weeklyboss.json").write_text(json.dumps(
    {"enabled": True, "index": 1, "count": 3, "level": "90",
     "name": "千傀重楼", "done_week": "2026-W36"}), encoding="utf-8")
g = W.WeeklyBossGate(STATE, TMP / "automas")

print("[机器上 09-07 的状态：上周领满，周一开机]")
line = g.maybe_reopen(MON)
check("说清打哪个", line, "鸣潮 · 周本：千傀重楼，本周还没领满")
check("记账已清", "done_week" in g._load(), False)
check("同一次开机再问就不再说", g.maybe_reopen(MON), "")
check("week_line 仍能报状态", g.week_line(MON), "鸣潮 · 周本：千傀重楼，本周还没领满")

print("[本周已领满 / 开关关着]")
g.on_success  # noqa: B018 - 只是确认接口还在
s = g._load(); s["done_week"] = "2026-W37"; g._save(s)
check("已领满", g.week_line(MON), "鸣潮 · 周本：千傀重楼 本周三次已领满，暂停到下周一")
check("没有总开关", "开" in g.settings(MON), False)

print("[开机那一段：剿灭、周常乐园、周本合成一条「新的一周」，三行都在]")
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
import service  # noqa: E402

sent = []
class N:
    def send(self, title, body): sent.append((title, body))
class Log:
    def exception(self, *a, **k): print("    EXC", a)
class Gate:
    def __init__(self, reopen, line): self._r, self._l = reopen, line; self.enforced = 0
    def maybe_reopen(self): return self._r
    def week_line(self): return self._l
    def enforce(self): self.enforced += 1
class Eng:
    def __init__(self, ann, garden, boss):
        self._annihilation, self._garden, self._weeklyboss = ann, garden, boss
    def _enforce_annihilation(self): pass

A_NEW = "明日方舟 · 剿灭：新的一周，已重新开启（Annihilation）"
A_LINE = "明日方舟 · 剿灭：本周还没打满，开关开着（Annihilation）"
G_LINE = "鸣潮 · 周常乐园：本周还没做，每趟都会去检查"
B_LINE = "鸣潮 · 周本：千傀重楼，本周还没领满"

sent.clear()
service._stage_annihilation(Eng(Gate(A_NEW, A_LINE), Gate(G_LINE, G_LINE), Gate(B_LINE, B_LINE)), N(), Log())
check("三个都过周：一条通知三行", sent, [("🗓️ 新的一周", "\n".join([A_NEW, G_LINE, B_LINE]))])

sent.clear(); boss = Gate("", "鸣潮 · 周本：千傀重楼 本周三次已领满，暂停到下周一"); garden = Gate("", G_LINE)
service._stage_annihilation(Eng(Gate(A_NEW, A_LINE), garden, boss), N(), Log())
check("只有剿灭过周：另外两个也报状态", sent,
      [("🗓️ 新的一周", "\n".join([A_NEW, G_LINE, "鸣潮 · 周本：千傀重楼 本周三次已领满，暂停到下周一"]))])

sent.clear(); boss = Gate(B_LINE, B_LINE); garden = Gate(G_LINE, G_LINE)
service._stage_annihilation(Eng(Gate("", A_LINE), garden, boss), N(), Log())
check("剿灭没过周（上周没打）：仍然三行", sent, [("🗓️ 新的一周", "\n".join([A_LINE, G_LINE, B_LINE]))])
check("周本说「恢复」之前先真挂上", boss.enforced, 1)
check("周常乐园同理", garden.enforced, 1)

sent.clear()
service._stage_annihilation(Eng(Gate("", A_LINE), Gate("", G_LINE), Gate("", B_LINE)), N(), Log())
check("都没过周：不发", sent, [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
