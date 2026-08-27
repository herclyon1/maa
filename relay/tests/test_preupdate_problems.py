"""预更新查不出结果时，必须报错，而不是静静地当成「无需更新」。

2026-08-25 早上的实况：控制台令牌拿不到 → OK-WW 被扔进 session 0 →
它的更新流程根本没跑 → 版本文件原样不动 → 中继把这读成
「预更新：OK-WW 无需更新（v3.6.4）」写进日志就完事了。
而 v3.6.5 当时已经发布十四个小时，CNB 镜像上也有。手动在控制台会话里
重启一次，十秒就更新完了。

**假的「没问题」比诚实的失败更糟**：没人会去查一件被报告为正常的事。
所以每个 run_* 都要能把「我没能确认」这件事送出函数，
service.py 再把它作为**报警**发出去（不是日常通知）。
"""
import ast, os, sys, tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.update(ARK_STATE_DIR=str(TMP), ARK_HISTORY_DIR=str(TMP))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import preupdate            # noqa: E402

fails = []
def check(label, got, want=True):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


print("[每个 run_* 都收得下 problems]")
import inspect                              # noqa: E402
for name in ("run_maa", "run", "run_automas", "run_okww"):
    sig = inspect.signature(getattr(preupdate, name))
    check(f"{name} 有 problems 参数", "problems" in sig.parameters)

print("\n[找不到程序 = 一个问题，不是沉默]")
empty = TMP / "empty"
empty.mkdir(exist_ok=True)
for name, fn in (("MAA", preupdate.run_maa), ("OK-WW", preupdate.run_okww)):
    problems = []
    fn(empty, budget_s=1, problems=problems)
    check(f"{name} 找不到 exe 会报一条", len(problems), 1)
    check(f"{name} 的问题里点名了程序", any(name in p for p in problems))

print("\n[AUTO-MAS 读不到版本号也要报]")
problems = []
preupdate.run_automas(empty, budget_s=1, problems=problems)
check("报了一条", len(problems), 1)
check("说的是没有检查更新", any("没有检查更新" in p for p in problems))

print("\n[problems 为 None 时不能炸]")
try:
    preupdate.run_okww(empty, budget_s=1)
    preupdate.run_maa(empty, budget_s=1)
    preupdate.run_automas(empty, budget_s=1)
    check("默认不传也安全", True)
except Exception as e:                      # noqa: BLE001
    check(f"默认不传也安全（炸了：{e}）", False)

print("\n[service.py 用报警级发出去，而不是日常通知]")
src = (Path(__file__).resolve().parents[1] / "service.py").read_text(encoding="utf-8")
check("收集 problems", "problems: list[str] = []" in src)
for name in ("run_maa", "run", "run_automas", "run_okww"):
    check(f"{name} 传了 problems", f"problems=problems)" in src)
    break
check("四个都传了", src.count("problems=problems") >= 4)
i = src.find("预更新没能确认")
block = src[i:i + 400] if i >= 0 else ""
check("有「预更新没能确认」这条通知", i >= 0)
check("走 alert=True（报警，会全渠道发）", "alert=True" in block)
check("明说了这不是「无需更新」", "这不是「无需更新」" in src)

print("\n[没有回到旧的「安静即成功」写法]")
p = (Path(__file__).resolve().parents[1] / "ark_relay" / "preupdate.py").read_text(encoding="utf-8")
check("不再用「45 秒还是 idle 就算没更新」", "+ 45" not in p)
check("靠版本列表判断检查过没有", "before_avail" in p)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
