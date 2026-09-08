"""周常乐园和剿灭、周本一套接口：settings / week_line / maybe_reopen / configure。

用户 2026-09-07：「鸣潮有两个东西，一个是周常乐园（不消耗体力完成），一个是周本
材料（一周三次，要消耗体力）。我希望手机网页界面操作逻辑、中继每周判定他们的
逻辑、推送的通知里应该统一。目前通知是散开的而且没有周常乐园。」
"""
import json, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import garden as G
from ark_relay.config import SERVER_TZ
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

TMP = tmpdir()
CFG = TMP / "automas" / "data" / "sid" / "Default" / "ConfigFile"; CFG.mkdir(parents=True)
(CFG / "DailyTask.json").write_text(json.dumps({G.KEY: ["Check Weekly Garden"]}), encoding="utf-8")
def tasks():
    return json.loads((CFG / "DailyTask.json").read_text(encoding="utf-8"))[G.KEY]

MON = datetime(2026, 9, 7, 8, 48, tzinfo=SERVER_TZ)
SUN = datetime(2026, 9, 6, 12, 0, tzinfo=SERVER_TZ)
g = G.GardenGate(TMP / "state", TMP / "automas")

print("[默认开着、本周没做]")
check("settings", g.settings(SUN), {"本周已完成": False})
check("week_line", g.week_line(SUN), "鸣潮 · 周常乐园：本周还没做，每趟都会去检查")

print("[周日做完 → 记账、摘掉]")
check("on_success 的话", g.on_success(SUN), "鸣潮 · 周常乐园：本周已完成，暂停检查到下周一")
check("本周已完成", g.settings(SUN)["本周已完成"], True)
check("week_line", g.week_line(SUN), "鸣潮 · 周常乐园：本周已完成，暂停检查到下周一")
check("enforce 摘掉", g.enforce(SUN), True)
check("母本里没了", G.TASK_NAME in tasks(), False)

print("[周一开机 → maybe_reopen 清账并给出状态行，enforce 挂回去]")
check("maybe_reopen", g.maybe_reopen(MON), "鸣潮 · 周常乐园：本周还没做，每趟都会去检查")
check("再问就不说了", g.maybe_reopen(MON), "")
check("enforce 挂回去", g.enforce(MON), True)
check("母本里回来了", G.TASK_NAME in tasks(), True)

print("[没有总开关：和剿灭一样只显示状态]")
check("settings 里没有开关", "开" in g.settings(MON), False)
check("没有 configure", hasattr(g, "configure"), False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
