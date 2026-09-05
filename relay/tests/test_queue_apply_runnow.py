"""队列启停和「现在跑一趟」不能一调用就崩。

2026-09-02 加 names 模块（队列改名早班/晚班）时，queues.apply 和
commands._run_now 里各留着一个叫 names 的局部列表。Python 把它当整个函数的
局部变量，函数第一行 names.canonical() 就 UnboundLocalError——四天里
跳过队列、待办里的队列开关、手机上的「现在跑一趟」每次都崩。
61 个测试全绿，因为没有一个测试真的调用过这两个函数。
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ark_relay import commands, queues  # noqa: E402

fails = []

# ---- queues.apply：真跑一遍，改完读回 ----
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "config").mkdir()
(tmp / "config" / "QueueConfig.json").write_text(json.dumps({
    "instances": [{"uid": "q1"}],
    "q1": {"Info": {"Name": "早班", "TimeEnabled": True},
           "SubConfigsInfo": {"TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "09:00"}}},
                              "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}},
}, ensure_ascii=False), encoding="utf-8")
(tmp / "config" / "ScriptConfig.json").write_text(json.dumps({
    "instances": [{"uid": "s1"}],
    "s1": {"Info": {"Name": "MAA", "Path": "D:\\ark\\maa"}, "SubConfigsInfo": {"UserData": {}}},
}), encoding="utf-8")

try:
    ok, msg = queues.apply(tmp, "早班", enabled=False)
except Exception as exc:  # noqa: BLE001
    fails.append(f"queues.apply 抛异常：{type(exc).__name__}: {exc}")
else:
    if not ok:
        fails.append(f"queues.apply 应成功：{msg}")
    got = json.loads((tmp / "config" / "QueueConfig.json").read_text(encoding="utf-8"))
    if got["q1"]["Info"]["TimeEnabled"] is not False:
        fails.append("queues.apply 没把定时关掉")
    # 旧名字要能认（names.canonical 的用武之地）
    ok2, msg2 = queues.apply(tmp, "新队列", enabled=True)
    if not ok2 or "早班" not in msg2:
        fails.append(f"旧名「新队列」没被换成早班：{ok2} {msg2}")
    # 不存在的队列：报错里要列出现有的
    ok3, msg3 = queues.apply(tmp, "不存在", enabled=True)
    if ok3 or "早班" not in msg3:
        fails.append(f"不存在的队列应失败并列出现有队列：{msg3}")

# ---- commands._run_now：把后端接口换成假的 ----
calls = []
def fake_mas(path, body=None, timeout=20):
    calls.append((path, body))
    if path == "/api/queue/get":
        return {"data": {"qid1": {"Info": {"Name": "早班"}}, "qid2": {"Info": {"Name": "晚班"}}}}
    if path == "/api/dispatch/start":
        return {"status": "success"}
    raise AssertionError(path)
commands._mas = fake_mas
try:
    ok, msg = commands._run_now("Evening-MAA")   # 旧名
except Exception as exc:  # noqa: BLE001
    fails.append(f"_run_now 抛异常：{type(exc).__name__}: {exc}")
else:
    if not ok or "晚班" not in msg:
        fails.append(f"_run_now 旧名应映射到晚班并成功：{ok} {msg}")
    if ("/api/dispatch/start", {"taskId": "qid2", "mode": "AutoProxy"}) not in calls:
        fails.append(f"没有派发晚班：{calls}")
    ok4, msg4 = commands._run_now("没有的队列")
    if ok4 or "早班" not in msg4 or "晚班" not in msg4:
        fails.append(f"不存在的队列应失败并列出现有队列：{msg4}")

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
