"""时间窗的 5 分钟余量会伸进下一趟，把下一趟的「开始」当成本趟的悬挂。

2026-08-31 晚上实测：第一趟 21:30:50→21:33:38（窗口到 21:38:38），
第二趟 21:33:43 就开跑，Infrast 21:35 开始、21:43 完成。
第一趟的窗口捞到了「Infrast 开始」却够不到「完成」，
推了一条「开了没收尾：Infrast」——而基建好好干完了，纯误报。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import outcome

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

def ev(ts, kind, chain):
    return (f'[2026-08-31 {ts}][INF][Px][Tx] '
            f'TaskChain{kind} {{"taskchain":"{chain}","uuid":"x"}}')

# 第一趟：StartUp/Fight/CloseDown 各一对。之后是第二趟，只到 Infrast 开始就被切断。
OVERLAP = "\n".join([
    ev("21:31:10", "Start", "StartUp"), ev("21:32:10", "Completed", "StartUp"),
    ev("21:32:11", "Start", "Fight"),   ev("21:33:30", "Completed", "Fight"),
    ev("21:33:31", "Start", "CloseDown"), ev("21:33:35", "Completed", "CloseDown"),
    # ↓ 这些是第二趟的，被 5 分钟余量捞进来了
    ev("21:33:50", "Start", "StartUp"), ev("21:34:40", "Completed", "StartUp"),
    ev("21:34:41", "Start", "Fight"),   ev("21:35:20", "Completed", "Fight"),
    ev("21:35:21", "Start", "Infrast"),          # 「完成」在 21:43，窗口够不到
])

print("\n[越界的下一趟不许算进本趟]")
res = outcome.maa_checks(OVERLAP)
bad = [c for c in res if not c.ok]
check("没有误报", [c.name for c in bad], [])

print("\n[真的悬挂还是要报]")
REAL = "\n".join([
    ev("21:31:10", "Start", "StartUp"), ev("21:32:10", "Completed", "StartUp"),
    ev("21:32:11", "Start", "Infrast"),          # 本趟自己的 Infrast 没收尾
])
bad = [c for c in outcome.maa_checks(REAL) if not c.ok]
check("报出来了", len(bad) >= 1, True)
check("说的是 Infrast", any("Infrast" in (c.detail or "") for c in bad), True)

print("\n[单趟不受影响]")
ONE = "\n".join([
    ev("21:33:50", "Start", "StartUp"), ev("21:34:40", "Completed", "StartUp"),
    ev("21:35:21", "Start", "Infrast"), ev("21:43:20", "Completed", "Infrast"),
])
check("全过", [c.name for c in outcome.maa_checks(ONE) if not c.ok], [])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
