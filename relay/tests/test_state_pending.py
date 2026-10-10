"""待推告警的存/取。**这条路没有测试过，结果炸在生产上。**

2026-09-08 上午：`core.State.save_pending` 上面被贴了一行多余的 `@property`。
后果不是「保存失败」这么轻——属性访问本身就抛 TypeError（getter 缺 payload），
于是 `_persist_pending` 每一轮都炸，三条鸣潮失败记录永远落不了账；
中继下一轮扫到它们，当成**新**失败又推一遍，每十几秒一条，把用户的群轰炸了半小时。

88 个测试里没有任何一个调用过 save_pending，静态检查也没有「@property 带参数」
这条规则，所以这行改动一路绿灯上了机器。这个文件补的就是那条路。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.config import SERVER_TZ, RunRecord
from ark_relay.core import State
from ark_relay.transport import record_to_payload, payload_to_record
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


def rec(run_id="2026-09-08/wuwa/OK-WW-05-22-26"):
    now = datetime.now(tz=SERVER_TZ)
    return RunRecord(run_id=run_id, script="OK-WW", user="wuwa",
                     started=now - timedelta(minutes=10), finished=now,
                     ok=False, failed_tasks=["任务执行：某个错"], raw={})


print("[save_pending 是方法，不是属性——这正是 09-08 那次的原形]")
check("是普通函数", type(State.__dict__["save_pending"]).__name__, "function")
check("不是 property", isinstance(State.__dict__["save_pending"], property), False)

print("\n[存进去、另起一个实例读回来，内容一样]")
d = tmpdir()
st = State(d)
payload = {"pending": [record_to_payload(rec())], "recovered": []}
st.save_pending(payload)
back = State(d).load_pending()
check("pending 条数", len(back.get("pending") or []), 1)
check("run_id 对得上", back["pending"][0]["run_id"], "2026-09-08/wuwa/OK-WW-05-22-26")
check("recovered 空", back.get("recovered"), [])

print("\n[读回来能还原成记录，告警才发得出去]")
r2 = payload_to_record(back["pending"][0])
check("脚本名", r2.script, "OK-WW")
check("失败任务", r2.failed_tasks, ["任务执行：某个错"])
check("不是成功", r2.ok, False)

print("\n[空的也存得下：清空待推队列走的就是这条路]")
st.save_pending({"pending": [], "recovered": []})
check("清空后读回来是空的", State(d).load_pending(), {"pending": [], "recovered": []})

print("\n[没存过时读回空字典，不抛异常]")
check("空目录", State(tmpdir()).load_pending(), {})

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
