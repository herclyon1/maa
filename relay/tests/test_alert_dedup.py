"""同一件事当天只推一次告警。

2026-09-01 群里同一个 OK-WW 失败连推三条（17:00/08:29/11:54），
用户：「赶紧去修，报了三次了。」键=脚本+失败在哪一步：
同一步反复失败不许反复推；换一步失败是新事，照报；跨天重置。
"""
import sys, tempfile, types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay.engine import Engine

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok: fails.append(label)

E = object.__new__(Engine)
E.state = types.SimpleNamespace(dir=Path(tempfile.mkdtemp()))
rec = types.SimpleNamespace(script="OK-WW", user="wuwa", failed_tasks=["流程产生错误"])

k = E._alert_key(rec)
check("第一次：没报过", E._already_alerted("2026-09-01", k), False)
E._mark_alerted("2026-09-01", k)
check("第二次：同键当天挡住", E._already_alerted("2026-09-01", k), True)
rec2 = types.SimpleNamespace(script="OK-WW", user="wuwa", failed_tasks=["在完成任务前退出"])
check("换一步失败：是新事，放行", E._already_alerted("2026-09-01", E._alert_key(rec2)), False)
check("跨天重置", E._already_alerted("2026-09-02", k), False)
E._mark_alerted("2026-09-01", E._alert_key(rec2))
check("两键共存互不干扰", E._already_alerted("2026-09-01", k), True)
rec3 = types.SimpleNamespace(script="OK-WW", user="wuwa", failed_tasks=None)
check("failed_tasks 为空不炸", isinstance(E._alert_key(rec3), str), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
