"""队列改名「早班/晚班」后，旧名字（新队列 / Evening-MAA）仍然被认。

排队中的手机指令、跳过标记、恢复标记里都可能还是旧名；改名不能让它们
变成「没有这个队列」。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
STATE = tmpdir()
os.environ["ARK_STATE_DIR"] = str(STATE)
from ark_relay import commands, names  # noqa: E402
from ark_relay.statestore import StateStore  # noqa: E402

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)

print("[canonical]")
check("新队列→早班", names.canonical("新队列"), "早班")
check("Evening-MAA→晚班", names.canonical("Evening-MAA"), "晚班")
check("现名原样", names.canonical("早班"), "早班")
check("带空白也认", names.canonical(" 新队列 "), "早班")
check("未知名原样", names.canonical("别的"), "别的")
check("空→空", names.canonical(""), "")

print("[skip_today 落盘的是现名]")
ok, msg = commands._skip_today("Evening-MAA")
marks = {k: v for k, v in StateStore(STATE).section("queues").items() if k.startswith("skip_day:")}
check("成功", ok, True)
check("标记内容", list(marks.values()), ["晚班"])
check("提示用现名", "「晚班」" in msg, True)

print("[默认队列是早班]")
ok, msg = commands.apply_command({"action": "skip_today"})
check("默认早班", any(v == "早班" for k, v in StateStore(STATE).section("queues").items()
                    if k.startswith("skip_day:")), True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
