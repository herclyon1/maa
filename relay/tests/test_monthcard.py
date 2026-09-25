"""Monthly-card reminders (user order 2026-09-26 02:47, spec BOARD/月卡到期提示-规格.md).

His own definition of the last claim day, verbatim: 「有效期比如说还剩一天，那就是到明天登录时领取算最后一次」
So the last claim day = today + days left; a renewal adds 30 per purchase; a lapsed card restarts on the
purchase day (day 1). From five days before the last claim day, one Server酱 a day,
and a push that reached nobody must be tried again rather than lost for the day.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import monthcard
from ark_relay.notify import route_of
from _tmp import tmpdir

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


D = date(2026, 9, 26)
s = tmpdir()

print("[还剩 X 天：最后领取 = 今天 + X]")
ok, msg = monthcard.apply(s, {"game": "明日方舟", "left": 3}, today=D)
check("接受", ok, True)
check("回执", msg, "明日方舟月卡：最后一次领取 9 月 29 日（还剩 3 天）")
check("状态", monthcard.status(s, today=D),
      {"明日方舟": {"最后领取": "2026-09-29", "还剩": 3, "已过期": False}})

print("\n[续费：在最后领取日上加 30×N]")
ok, msg = monthcard.apply(s, {"game": "明日方舟", "add": 2}, today=D)
check("回执", msg, "明日方舟月卡：最后一次领取 11 月 28 日（还剩 63 天）")

print("\n[没登记过 / 已过期：买的当天是第 1 天]")
ok, msg = monthcard.apply(s, {"game": "鸣潮", "add": 1}, today=D)
check("新登记", monthcard.status(s, today=D)["鸣潮"]["最后领取"], "2026-10-25")
monthcard.apply(s, {"game": "终末地", "left": 0}, today=date(2026, 9, 1))
check("过期后状态", monthcard.status(s, today=D)["终末地"], {"最后领取": "2026-09-01", "还剩": -25, "已过期": True})
monthcard.apply(s, {"game": "终末地", "add": 1}, today=D)
check("过期后续费从今天算", monthcard.status(s, today=D)["终末地"]["最后领取"], "2026-10-25")
check("最后领取日当天续费接着加", monthcard.apply(tmpdir(), {"game": "鸣潮", "left": 0}, today=D)[0], True)
s2 = tmpdir()
monthcard.apply(s2, {"game": "鸣潮", "left": 0}, today=D)
monthcard.apply(s2, {"game": "鸣潮", "add": 1}, today=D)
check("还剩 0 天续一次 = 今天 + 30", monthcard.status(s2, today=D)["鸣潮"]["最后领取"], "2026-10-26")

print("\n[拒收]")
for cmd, why in (({"game": "原神", "left": 3}, "不认识的游戏"), ({"game": "明日方舟"}, "两个都没填"),
                 ({"game": "明日方舟", "add": 1, "left": 3}, "两个都填"), ({"game": "明日方舟", "add": 0}, "0 次"),
                 ({"game": "明日方舟", "add": 13}, "超 12 次"), ({"game": "明日方舟", "left": -1}, "负天数"),
                 ({"game": "明日方舟", "left": 401}, "超 400 天"), ({"game": "明日方舟", "left": 2.5}, "小数"),
                 ({"game": "明日方舟", "add": True}, "布尔")):
    before = monthcard.status(s, today=D)
    check(f"拒：{why}", monthcard.apply(s, cmd, today=D)[0], False)
    check(f"拒后不改：{why}", monthcard.status(s, today=D), before)
check("字符串数字照收", monthcard.apply(tmpdir(), {"game": "明日方舟", "left": "3"}, today=D)[0], True)

print("\n[提醒：还剩 0–5 天每天一条，三家合一条，过期后不发]")
n = tmpdir()
check("没登记不发", monthcard.due_notice(n, today=D), None)
monthcard.apply(n, {"game": "明日方舟", "left": 6}, today=D)
check("还剩 6 天不发", monthcard.due_notice(n, today=D), None)
monthcard.apply(n, {"game": "明日方舟", "left": 5}, today=D)
monthcard.apply(n, {"game": "鸣潮", "left": 1}, today=D)
monthcard.apply(n, {"game": "终末地", "left": 0}, today=date(2026, 9, 20))
title, body = monthcard.due_notice(n, today=D)
check("标题", title, "💳 月卡快到期")
check("正文按剩余天数排、过期的不在内", body,
      "鸣潮月卡还剩 1 天，最后一次领取是 9 月 27 日\n明日方舟月卡还剩 5 天，最后一次领取是 10 月 1 日")
check("走 Server酱", route_of(title), "info")
check("没送到就不算发过：下一轮还给", monthcard.due_notice(n, today=D) is not None, True)
monthcard.mark_sent(n, today=D)
check("送到后当天不再发", monthcard.due_notice(n, today=D), None)
check("第二天再发", monthcard.due_notice(n, today=date(2026, 9, 27)) is not None, True)
check("最后领取日当天（还剩 0）还发", "鸣潮月卡还剩 0 天" in monthcard.due_notice(n, today=date(2026, 9, 27))[1], True)
check("全过期后不发", monthcard.due_notice(n, today=date(2026, 10, 2)), None)

print("\n[登记文件坏了：按没登记处理，不抛]")
b = tmpdir()
(b / monthcard.FILE).write_text("{坏", encoding="utf-8")
check("状态为空", monthcard.status(b, today=D), {})
check("仍能登记", monthcard.apply(b, {"game": "鸣潮", "left": 2}, today=D)[0], True)
check("坏文件留了副本", (b / (monthcard.FILE + ".bad")).read_text(encoding="utf-8"), "{坏")

print("\n[主循环那一步：送到才记已发]")
from types import SimpleNamespace  # noqa: E402
from ark_relay.engine import Engine  # noqa: E402
e = tmpdir()
monthcard.apply(e, {"game": "鸣潮", "left": 2})
sent, answer = [], [["Server酱"]]
fake = SimpleNamespace(state=SimpleNamespace(dir=e),
                       notifier=SimpleNamespace(send=lambda t, b: sent.append(t) or answer[0]))
Engine._monthcard_notice(fake)
check("推了一条", sent, ["💳 月卡快到期"])
Engine._monthcard_notice(fake)
check("没送到：下一轮再推", sent, ["💳 月卡快到期"] * 2)
answer[0] = []
Engine._monthcard_notice(fake)
Engine._monthcard_notice(fake)
check("送到后当天不再推", len(sent), 3)

print("\n[经手机指令正门]")
import os  # noqa: E402
os.environ["ARK_STATE_DIR"] = str(tmpdir())
from ark_relay import commands  # noqa: E402
check("白名单、免确认", "monthcard" in commands.REVERSIBLE, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
