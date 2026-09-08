"""「有脚本在跑吗」先问 AUTO-MAS，不只看进程名。

2026-09-07 10:15：OK-WW 09:19 起跑了三趟（AUTO-MAS 整段结束 10:16 才写记录），
_scripts_running 的进程名单里没有 OK-WW，中继以为什么都没在跑，
75 分钟一到就发了「OK-WW 没有运行」「MaaEnd 没有运行」两条假报警。
runtime-snapshot 是 AUTO-MAS 自己的口径：每个脚本 完成/异常/运行/等待。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import engine

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

# 2026-09-07 10:18 机器上拿到的真实样本（MAA 完成、OK-WW 异常、MaaEnd 运行）
REAL = {"tasks": [{"taskId": "8cebb1be", "mode": "AutoProxy", "stopping": False,
                   "task_info": [
                       {"name": "MAA", "status": "完成", "userList": [{"name": "arknights", "status": "完成"}]},
                       {"name": "OK-WW", "status": "异常", "userList": [{"name": "wuwa", "status": "异常"}]},
                       {"name": "MaaEnd", "status": "运行", "userList": [{"name": "endfield", "status": "运行"}]}]}],
        "scheduledScripts": []}
check("MaaEnd 运行中 → 在跑", engine._judge_snapshot(REAL), True)

waiting = {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"}, {"name": "OK-WW", "status": "等待"}]}]}
check("OK-WW 还在等待 → 在跑（假报警就是这一格）", engine._judge_snapshot(waiting), True)
check("刚派下去、还没有状态 → 在跑", engine._judge_snapshot({"tasks": [{"task_info": []}]}), True)
done = {"tasks": [{"task_info": [{"name": "MAA", "status": "完成"}, {"name": "OK-WW", "status": "异常"}]}]}
check("全部终态 → 没在跑", engine._judge_snapshot(done), False)
check("没有任务 → 没在跑", engine._judge_snapshot({"tasks": []}), False)
check("空回复 → 没在跑", engine._judge_snapshot(None), False)
check("没见过的状态 → 当作在跑", engine._judge_snapshot({"tasks": [{"task_info": [{"status": "重试中"}]}]}), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
