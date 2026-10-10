"""A skip of a queue that did not take effect, or whose restore failed, reaches the group.

engine._observe_modes sent every message of modes.process_skip under texts.SKIP_MODE,
which notify.route_of sends to the log only - so 「跳过「早班」失败：…——没生效，今天
照常跑」 (the queue the user wanted skipped runs anyway) and 「跳过「早班」后恢复失败：…」
(the queue stays switched off) never reached anyone. The user's rule, 2026-10-06:
「不论多少次什么错误都要发」 - a failure that did not recover goes to the group every
time. The acknowledgements of a skip that took stay on the log route.

Driven through a real Engine tick step with modes.process_skip's real code; only
queues.apply (AUTO-MAS's answer) and plan.schedule are faked.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay import engine as eng_mod
from ark_relay import modes, texts
from ark_relay import plan as _plan
from ark_relay import queues as _q
from ark_relay.config import SERVER_TZ, Config
from ark_relay.core import State
from ark_relay.notify import route_of

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", alert=False, **kw):
        self.sent.append((title, body, alert))
        return []


class Src:
    def fetch(self, seen):
        return []


ANSWER = {"早班": (True, "调度程序已确认")}
live = {"早班": True}


def fake_apply(d, q, enabled):
    ok, detail = ANSWER[q]
    if ok:
        live[q] = enabled
    return ok, detail


_real = _q.apply, _plan.schedule
_q.apply = fake_apply
_plan.schedule = lambda d: [{"name": q, "times": ["09:00"]} for q in live if live[q]]


def engine():
    sd = tmpdir()
    cfg = Config()
    cfg.state_dir = sd
    cfg.automas_dir = tmpdir()
    live["早班"] = True
    return eng_mod.Engine(cfg, source=Src(), state=State(sd), notifier=Notes())


def pushed(e):
    return [(t, a, route_of(t, alert=a)) for t, b, a in e.notifier.sent]


today = datetime.now(tz=SERVER_TZ).strftime("%Y-%m-%d")
try:
    print("[跳过没生效（调度程序没接受）：进群一条，说今天照常跑]")
    e = engine()
    ANSWER["早班"] = (False, "队列「早班」定时关闭没生效：调度程序里它仍是开启")
    modes.add_day_queue(e.state.dir, today, "早班")
    e._observe_modes()
    got = pushed(e)
    check("一条报警，走群", [(a, r) for _, a, r in got], [(True, "group")])
    check("正文就是那句失败", any("没生效，今天照常跑" in b for _, b, _ in e.notifier.sent), True)
    e._observe_modes()
    check("下一轮同一句不再推（同一个错，一次）", len(e.notifier.sent), 1)

    print("[跳过生效了：确认那条照旧只进日志]")
    e = engine()
    ANSWER["早班"] = (True, "调度程序已确认")
    modes.add_day_queue(e.state.dir, today, "早班")
    e._observe_modes()
    got = pushed(e)
    check("一条，标题是跳过模式，不带报警", [(t, a) for t, a, _ in got], [(texts.SKIP_MODE, False)])
    check("走日志", [r for _, _, r in got], ["log"])

    print("[推送没送出去：记一条 WARNING，带原话]")
    e = engine()
    ANSWER["早班"] = (False, "调度程序没有应答")
    modes.add_day_queue(e.state.dir, today, "早班")
    tries = []
    e.notifier.send = lambda t, b="", alert=False, **k: (tries.append((t, alert)), ["群机器人发送失败"])[1]
    import logging
    seen = []
    h = type("H", (logging.Handler,), {"emit": lambda self, r: seen.append((r.levelno, r.getMessage()))})()
    eng_mod.log.addHandler(h)
    try:
        e._observe_modes()
    finally:
        eng_mod.log.removeHandler(h)
    check("推了，没送出", tries, [(eng_mod.SKIP_FAILED, True)])
    check("记一条 WARNING，带那句失败（错误推送会把它补推进群）",
          [lvl for lvl, m in seen if "没生效，今天照常跑" in m and "没推出去" in m], [logging.WARNING])
finally:
    _q.apply, _plan.schedule = _real

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
