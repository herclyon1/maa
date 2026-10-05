"""A phone order pressed while a script runs waits for the run to end - it is not dropped.

Until 2026-10-05 every order but 「下次跑完不关机」 / 调试模式 that arrived during a
run got a 「等这一趟跑完再按一次」 push and nothing else: no receipt, and its
message id was already recorded as handled (phone.Mailbox.listen), so no later
boot ever ran it - while the App told the user the change was
「推迟到跑完再生效」. Pinned here:

* during a run the order goes to disk (phone.CmdQueue), is not applied, and
  nothing is pushed to the group or Server酱;
* once nothing runs, the queue is applied in arrival order through the same
  apply_command, each with its receipt, and one state is pushed;
* the queue survives a relay restart;
* the existing expiry rules hold at drain time (24 h from the send; skip_today's
  own `day`), an expired order gets a failure receipt and is not applied;
* the same message id is queued and run once;
* skip_shutdown / debug_mode still act at once;
* Engine.tick drains before its shutdown decision.
"""
import os
import sys
import time
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for name in ("win32serviceutil", "win32service", "win32event", "win32api",
             "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(name, _Stub(name))

from _tmp import tmpdir                 # noqa: E402

os.environ.update(ARK_STATE_DIR=str(tmpdir()), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")

import ark_relay.commands as C          # noqa: E402
import boot_stages                      # noqa: E402
from ark_relay import modes, phone      # noqa: E402
from ark_relay.config import SERVER_TZ  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


class Eng:
    def __init__(self, busy):
        self.busy = busy

    def scripts_running(self):
        return self.busy


class Notes:
    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body))
        return False


class Log:
    def __init__(self):
        self.lines = []

    def _rec(self, fmt, *a, **k):
        self.lines.append(fmt % a if a else fmt)

    info = warning = debug = _rec

    def exception(self, fmt, *a, **k):
        self.lines.append("EXC " + (fmt % a if a else fmt))


class HB:
    def watch(self): pass


APPLIED: list = []


def fake_apply(body):
    APPLIED.append(body["action"] + (f":{body['value']}" if "value" in body else ""))
    assert "_meta" not in body, "apply_command must never see _meta"
    return True, f"改好了 {body.get('value', '')}".strip()


def order(action, mid, sent=None, **kw):
    """An order as phone.stamp hands it over."""
    body = {"action": action, "confirmed": True, **kw}
    body["_meta"] = {"sent": int(time.time()) if sent is None else sent,
                     "ntfy_time": int(time.time()), "ntfy_id": mid, "via": "live"}
    return body


def make(engine, state_dir, notes=None, pushed=None, log=None):
    """A fresh run_phone_cmd: building it again on the same dir is a relay restart."""
    pusher = phone.StatePusher(lambda why: (pushed.append(why) if pushed is not None else None) or True)
    return boot_stages._make_phone_cmd(engine, notes or Notes(), log or Log(), HB(), pusher, state_dir)


REAL_APPLY = C.apply_command
C.apply_command = fake_apply      # bound into the closure when _make_phone_cmd runs

print("[跑着的时候：改设置落盘排队，不当场改，什么都不推]")
d = tmpdir()
eng = Eng(busy=True)
notes, pushed, lg = Notes(), [], Log()
fn = make(eng, d, notes, pushed, lg)
APPLIED.clear()
fn(order("set_config", "m1", value="1-7"))
fn(order("skip_today", "m2", queue="晚班", day="2026-10-05"))
fn(order("run_now", "m3", queue="早班"))
check("一条也没执行", APPLIED, [])
check("群 / Server酱 什么都没推", notes.sent, [])
check("状态没推（还没变）", pushed, [])
check("没写回执（回执只有成 / 不成两种，排队不算）", modes.receipts(d), [])
q = phone.CmdQueue(d)
check("三条按到达顺序落在盘上", [i["body"]["action"] for i in q._read()["items"]],
      ["set_config", "skip_today", "run_now"])
check("落盘的带着 _meta（回执要 sent，去重要 id）",
      q._read()["items"][0]["body"]["_meta"]["ntfy_id"], "m1")
check("日志说了排队", any("排队" in x for x in lg.lines), True)

print("\n[同一条消息 id 只排一次]")
fn(order("set_config", "m1", value="1-7"))
check("还是三条", len(q), 3)

print("\n[还在跑时到了 tick：不动]")
check("drain 一条没跑", fn.drain(), 0)
check("还是三条", len(q), 3)

print("\n[中继重启：队列还在，跑完后按顺序执行]")
eng2 = Eng(busy=False)
notes2, pushed2 = Notes(), []
fn2 = make(eng2, d, notes2, pushed2)
APPLIED.clear()
check("跑了三条", fn2.drain(), 3)
check("按到达顺序走同一个 apply_command", APPLIED, ["set_config:1-7", "skip_today", "run_now"])
rc = modes.receipts(d)
check("每条一张回执", [(r["action"], r["ok"]) for r in rc],
      [("set_config", True), ("skip_today", True), ("run_now", True)])
check("回执带发出时间", all("sent" in r for r in rc), True)
check("三条合成一份状态", pushed2, ["改完配置（3 次合成一次）"])
check("群 / Server酱 什么都没推", notes2.sent, [])
check("队列空了", len(q), 0)

print("\n[执行过的 id 再来一次：不再排、不再跑]")
eng2.busy = True
APPLIED.clear()
fn2(order("set_config", "m1", value="1-7"))
check("没排进去", len(q), 0)
eng2.busy = False
fn2.drain()
check("没再执行", APPLIED, [])

print("\n[过期：发出超过 24 小时才轮到它——不执行，回执写明]")
d3 = tmpdir()
eng3 = Eng(busy=True)
fn3 = make(eng3, d3)
old = int(time.time()) - phone.MAX_AGE - 60
fn3(order("set_config", "x1", sent=old, value="TO-5"))
eng3.busy = False
APPLIED.clear()
fn3.drain()
check("没执行", APPLIED, [])
rc3 = modes.receipts(d3)
check("一张失败回执", [(r["action"], r["ok"]) for r in rc3], [("set_config", False)])
check("回执用人话说过期了", "过期没执行" in rc3[0]["text"] and "24 小时" in rc3[0]["text"], True)

print("\n[skip_today 指定的那天已过：走它自己原有的过期判断，失败回执]")
C.apply_command = REAL_APPLY            # the real one: its own `day` check decides
d4 = tmpdir()
os.environ["ARK_STATE_DIR"] = str(d4)
eng4 = Eng(busy=True)
fn4 = make(eng4, d4)
yesterday = (datetime.now(tz=SERVER_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
fn4(order("skip_today", "y1", queue="晚班", day=yesterday))
eng4.busy = False
fn4.drain()
rc4 = modes.receipts(d4)
check("一张失败回执", [(r["action"], r["ok"]) for r in rc4], [("skip_today", False)])
check("说的是那天已过", "过期" in rc4[0]["text"], True)
check("没跳过任何队列", list(modes.skipped_today_all(d4)), [])
C.apply_command = fake_apply

print("\n[跑着的时候：下次跑完不关机 / 调试模式照旧当场执行]")
d5 = tmpdir()
eng5 = Eng(busy=True)
fn5 = make(eng5, d5)
APPLIED.clear()
fn5(order("skip_shutdown", "s1", on=True))
fn5(order("debug_mode", "s2"))
check("两条都当场执行了", APPLIED, ["skip_shutdown", "debug_mode"])
check("没有排队", len(phone.CmdQueue(d5)), 0)

print("\n[没在跑但前面还有排着的：新来的排在后面，一起按顺序跑]")
d6 = tmpdir()
eng6 = Eng(busy=True)
fn6 = make(eng6, d6)
APPLIED.clear()
fn6(order("set_config", "a1", value="A"))
eng6.busy = False
# Scripts stopped but no tick has drained yet; a new order arrives first.
fn6(order("set_config", "a2", value="B"))
check("先 A 后 B", APPLIED, ["set_config:A", "set_config:B"])
check("队列空了", len(phone.CmdQueue(d6)), 0)

print("\n[跑到一半又开跑：剩下的继续等]")
d7 = tmpdir()
eng7 = Eng(busy=True)
fn7 = make(eng7, d7)
for i in range(3):
    fn7(order("set_config", f"b{i}", value=str(i)))
APPLIED.clear()
def _apply_then_busy(body):
    out = fake_apply(body)
    eng7.busy = True          # a queue started right after the first order
    return out


eng7.busy = False
C.apply_command = _apply_then_busy
fn7 = make(eng7, d7)
fn7.drain()
C.apply_command = fake_apply
check("只跑了第一条", APPLIED, ["set_config:0"])
check("剩两条还在盘上", len(phone.CmdQueue(d7)), 2)

print("\n[Engine.tick：先跑排队的手机指令，再做模式和关机判断]")
from ark_relay import engine as engmod       # noqa: E402
from ark_relay.config import Config          # noqa: E402
from ark_relay.core import State             # noqa: E402

cfg = Config()
cfg.state_dir = tmpdir()
E = engmod.Engine(cfg, source=types.SimpleNamespace(fetch=lambda seen: []),
                  state=State(cfg.state_dir), notifier=Notes())
E._scripts_running = lambda: False
calls = []
STEPS = ("_echo_farm_deadline", "_patch_okww_if_updated", "_run_watch", "_flush_pending",
         "_enforce_annihilation", "_weekly_gates", "_monthcard_notice", "_check_missed_runs",
         "_maybe_interim_report", "_maybe_deferred_update", "_maybe_daily_report")
for name in STEPS:
    setattr(E, name, lambda *a, **k: None)
E._observe_modes = lambda: calls.append("modes")

# The real drain, wired the way boot_stages wires it.
d8 = tmpdir()
eng8 = Eng(busy=True)
fn8 = make(eng8, d8)
fn8(order("run_now", "r1", queue="早班"))
eng8.busy = False
E._phone_drain = lambda: calls.append("drain:" + str(fn8.drain()))
seen_at_shutdown = []
E._maybe_shutdown = lambda *a, **k: (calls.append("shutdown"), seen_at_shutdown.append(list(APPLIED)))
APPLIED.clear()
E.tick()
check("顺序：排队指令 → 模式 → 关机判断", calls, ["drain:1", "modes", "shutdown"])
check("关机判断时那条「现在跑」已经执行", seen_at_shutdown, [["run_now"]])

print("\n[排队那段炸了，也不许带走整轮]")
calls.clear()
E._phone_drain = lambda: (_ for _ in ()).throw(RuntimeError("队列文件读坏了"))
try:
    E.tick()
    check("tick 没把异常抛出去", True, True)
except Exception as exc:                     # noqa: BLE001
    check(f"tick 没把异常抛出去（抛了 {exc}）", False, True)
check("后面照样到了关机判断", calls, ["modes", "shutdown"])

print("\n[没接手机通道（单测 / 没配 topic）：tick 照旧]")
calls.clear()
E._phone_drain = None
E.tick()
check("照旧", calls, ["modes", "shutdown"])

print("\n[坏掉的队列文件：当空的，不抛]")
d9 = tmpdir()
(d9 / phone.CMD_QUEUE_FILE).write_text("{坏的", encoding="utf-8")
check("读成空", len(phone.CmdQueue(d9)), 0)
check("还能接着排", phone.CmdQueue(d9).add(order("set_config", "z1", value="1")), True)
check("排进去了", len(phone.CmdQueue(d9)), 1)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
