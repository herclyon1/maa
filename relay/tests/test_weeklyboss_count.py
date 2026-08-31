"""「任务跑完」不等于「三次领满」。

周本奖励是**进本时扣 60 结晶波片**给的，波片不够就少领几次。
2026-08-31 实测：贝币刷取把波片吃到只剩 1 点，第二天早上只回到约 147，
只够领两次。而 on_success 原来只要任务跑完就记「本周已打」并摘掉开关——
第三次就永远丢了，而且不出声。

现在改成读游戏页面上的「本周剩余可收取次数」，归零才记账。
"""
import os, sys, tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import weeklyboss as W
from ark_relay.config import SERVER_TZ

TMP = Path(tempfile.mkdtemp())
LOG = TMP / "ok-ww.log"
os.environ["ARK_OKWW_LOG"] = str(LOG)
STATE = TMP / "state"; STATE.mkdir()
NOW = datetime(2026, 8, 31, 20, 0, tzinfo=SERVER_TZ)

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)

def gate():
    g = W.WeeklyBossGate(STATE, None)
    g.configure(enabled=True, index=1, count=3)
    return g

def write(*lines):
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")

print("\n[读得出剩余次数]")
write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：3/3')]")
check("读到 3", W.remaining_from_log(), 3)
write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：3/3')]",
      "周本本周剩余次数原文: [Box(text='本周剩余可收取次数：1/3')]")
check("取最后一条", W.remaining_from_log(), 1)
write("什么都没有")
check("读不到就是 None", W.remaining_from_log(), None)

print("\n[还剩就不许记账]")
write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：2/3')]")
g = gate()
msg = g.on_success(NOW)
check("说清楚还剩几次", "还剩 2 次" in msg, True)
check("没记成已打完", g.settings()["本周已打"], False)

print("\n[归零才记账]")
write("周本本周剩余次数原文: [Box(text='本周剩余可收取次数：0/3')]")
msg = g.on_success(NOW)
check("记成已打完", g.settings()["本周已打"], True)
check("话说得对", "领满三次" in msg, True)

print("\n[读不到时宁可不记]")
STATE2 = TMP / "s2"; STATE2.mkdir()
write("什么都没有")
g2 = W.WeeklyBossGate(STATE2, None); g2.configure(enabled=True)
check("不记账", g2.on_success(NOW), "")
check("开关继续挂着", g2.settings()["本周已打"], False)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
