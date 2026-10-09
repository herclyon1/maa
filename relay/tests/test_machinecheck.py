"""Machine checks: the machine confirms deployed changes by itself (machinecheck.py).

The user, 2026-10-06 04:59: the machine must check the open ledger items by itself
after a deploy, instead of a person reading logs. Every FAIL goes to the group,
every time it is judged; PASS and still-waiting go to the daily report only.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp import tmpdir
from ark_relay import machinecheck as mc
from ark_relay.config import SERVER_TZ
from ark_relay.notify import route_of

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}")
    if not ok:
        fails.append(label)


class N:
    def __init__(self):
        self.sent = []

    def send(self, title, body, alert=False, **kw):
        self.sent.append((title, body, alert))
        return []


mc.load()
real = dict(mc.CHECKS), dict(mc.CANNOT)
mc.CHECKS.clear()
mc.CANNOT.clear()
try:
    seen = {}

    @mc.check("#901", "样例：跑完看日志里有没有那一行", "A", "run")
    def _a(ctx):
        line = ctx.get("line")
        if line is None:
            return None
        return mc.Result(mc.PASS if "已领到" in line else mc.FAIL, line)

    @mc.check("#902", "样例：等手机指令", "B", "phone_cmd")
    def _b(ctx):
        seen["ctx"] = ctx
        return mc.Result(mc.PASS, f"回执：{ctx.get('msg')}")

    @mc.check("#903", "样例：自己会出错的核对", "A", "run")
    def _c(ctx):
        raise RuntimeError("boom")

    mc.cannot("#904", "样例：核不了的", "要人在电脑上跑一个工具")
    d = tmpdir()
    now = datetime(2026, 10, 6, 21, 40, tzinfo=SERVER_TZ)
    n = N()
    print("[没被触发：什么都不记]")
    check("run 事件但没给那一行：#901 不判", [c for c, _ in mc.judge(d, "run", {}, notifier=n, now=now)], [])
    check("没推", n.sent, [])
    print("[过了：只记，不推]")
    got = mc.judge(d, "run", {"line": "周本领奖：已领到"}, version="v1", notifier=n, now=now)
    check("判了 #901 过了", [(c, r.status) for c, r in got], [("#901", mc.PASS)])
    check("过了不推", n.sent, [])
    check("记进状态：结论、依据、版本", {k: mc.read(d)["#901"][k] for k in ("status", "evidence", "version")},
          {"status": "PASS", "evidence": "周本领奖：已领到", "version": "v1"})
    print("[没过：每次都推，进群]")
    mc.judge(d, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n, now=now)
    mc.judge(d, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n, now=now)
    check("没过两次，推两次", len(n.sent), 2)
    check("都带 alert=True", [a for _, _, a in n.sent], [True, True])
    check("标题走群", route_of(n.sent[0][0], alert=True) if n.sent else None, "group")
    check("正文带依据", "没认出领奖弹窗" in n.sent[0][1] if n.sent else False, True)
    check("记了没过的次数", mc.read(d)["#901"]["fails"], 2)
    print("[核对自己出错：记 ERROR（会进群），不当成过了]")
    errs = []
    h = type("H", (logging.Handler,), {"emit": lambda self, r: errs.append(r.levelno)})()
    mc.log.addHandler(h)
    mc.judge(d, "run", {"line": "x"}, notifier=n, now=now)
    mc.log.removeHandler(h)
    check("有一条 ERROR", logging.ERROR in errs, True)
    check("#903 没有结论", "#903" in mc.read(d), False)
    print("[B 类：触发时拿到事件内容]")
    mc.judge(d, "phone_cmd", {"action": "skip_today", "msg": "调度程序已确认"}, notifier=n, now=now)
    check("看到了指令", (seen["ctx"]["action"], seen["ctx"]["event"]), ("skip_today", "phone_cmd"))
    print("[日报一段]")
    sec = mc.daily_section(d)
    check("有标题", sec.startswith("上机核对"), True)
    check("没过的打 ❌", "❌ #901" in sec, True)
    check("过了的打 ✅", "✅ #902" in sec, True)
    check("没判的写在等", "⏳ #903" in sec, True)
    check("核不了的写明原因", "✋ #904 样例：核不了的：机器核不了，要人在电脑上跑一个工具" in sec, True)
    print("[登记写错就拒绝]")
    for label, args in (("类别只能 A/B", ("#905", "x", "C", "run")), ("事件要认识", ("#906", "x", "A", "nope")),
                        ("至少一个事件", ("#907", "x", "A"))):
        try:
            mc.check(*args)(lambda c: None)
            check(label, "registered", "refused")
        except ValueError:
            check(label, "refused", "refused")
    try:
        mc.judge(d, "nope", {})
        check("不认识的事件拒绝", "judged", "refused")
    except ValueError:
        check("不认识的事件拒绝", "refused", "refused")
    print("[state file exists but cannot be read: said once, not overwritten, FAILs still pushed]")
    d2 = tmpdir()
    sf = d2 / mc.STATE_FILE
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text("{corrupt", encoding="utf-8")
    getattr(mc, "_last_error", {}).clear()
    warned = []
    wh = type("W", (logging.Handler,), {"emit": lambda self, r: warned.append(r.levelno)})(level=logging.WARNING)
    mc.log.addHandler(wh)
    n2 = N()
    mc.judge(d2, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n2, now=now)
    check("one WARNING", warned.count(logging.WARNING), 1)
    check("the unreadable file is left as it was (no other check's history overwritten)",
          sf.read_text(encoding="utf-8"), "{corrupt")
    check("the FAIL is still pushed", len(n2.sent), 1)
    mc.judge(d2, "run", {"line": "周本领奖：没认出领奖弹窗"}, notifier=n2, now=now)
    check("same condition again -> no second WARNING", warned.count(logging.WARNING), 1)
    sf.write_text("{}", encoding="utf-8")
    mc.judge(d2, "run", {"line": "周本领奖：已领到"}, notifier=n2, now=now)
    check("readable again -> written, no WARNING", (mc.read(d2).get("#901", {}).get("status"),
                                                    warned.count(logging.WARNING)), ("PASS", 1))
    sf.write_text("{corrupt", encoding="utf-8")
    mc.judge(d2, "run", {"line": "周本领奖：已领到"}, notifier=n2, now=now)
    check("broken again after a good read -> WARNING again", warned.count(logging.WARNING), 2)
    d3 = tmpdir()
    mc.judge(d3, "run", {"line": "周本领奖：已领到"}, notifier=n2, now=now)
    check("no state file yet is not an error -> written, no WARNING",
          (mc.read(d3).get("#901", {}).get("status"), warned.count(logging.WARNING)), ("PASS", 2))
    mc.log.removeHandler(wh)
finally:
    mc.CHECKS.clear()
    mc.CHECKS.update(real[0])
    mc.CANNOT.clear()
    mc.CANNOT.update(real[1])

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
