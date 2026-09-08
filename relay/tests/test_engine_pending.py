"""engine.py 里没人碰过的四段：告警落盘、首启接管历史、在跑判断的缓存、tick 逐段兜底。

这个文件防的是四类损失，每一类都真的发生过或者差一点发生：

* **告警重复推 → 群里被轰炸**。2026-09-08 上午 `_persist_pending` 这一行炸了
  （它调的 `State.save_pending` 被贴了个 `@property`），失败记录永远落不了账，
  同一条每十几秒重推一次，推了半小时。`test_state_pending.py` 钉的是 State 那一层，
  这里钉的是 Engine 这一层：存进去、换个进程读回来，`_pending` / `_recovered` 还在。
* **中继重启就丢告警**。机器一天硬断电两次，压在内存里的告警等于没有。
* **首次启动把几百条历史当新失败推一遍**。`bootstrap` 没有任何测试调用过。
* **写配置撞上正在跑的脚本**（826 那一类）。`scripts_running` 是「现在能不能写配置」
  的唯一判据，它的三秒缓存要是把「在跑」缓存成「没在跑」，配置就会写进 AUTO-MAS
  正在读的那一份，然后被内存副本冲掉——刷错关卡、烧理智药。
* **一段出错带走后面的段**。2026-09-04 明日安排那段的 ImportError 把日报和关机
  一起带走，机器整夜没关。`test_tick_isolation.py` 只试了「漏跑检查」这一段，
  这里把九段逐个弄坏一遍，确认剩下八段照跑。
"""
import json
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"
(AUTOMAS / "config").mkdir(parents=True)
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({"instances": []}), encoding="utf-8")
HIST = TMP / "history"
HIST.mkdir()
os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(TMP / "state"), SERVERCHAN_KEY="", ARK_LLM_KEY="",
                  WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="", ARK_PHONE_TOPIC="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay import engine as eng                       # noqa: E402
from ark_relay import modes                               # noqa: E402
from ark_relay.config import SERVER_TZ, Config, RunRecord  # noqa: E402
from ark_relay.core import State                          # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        fails.append(label)


class Notes:
    """假通知渠道：只记下来，不发出去。"""

    def __init__(self):
        self.sent = []

    def send(self, title, body="", **kw):
        self.sent.append((title, body))
        return False        # False = 送出去了（真 Notifier 的口径：返回值是「有没有失败」）


class Src:
    """假记录源：只给没见过的记录。"""

    def __init__(self, records=()):
        self.records = list(records)
        self.calls = 0

    def fetch(self, seen):
        self.calls += 1
        return [r for r in self.records if r.run_id not in (seen or set())]


def rec(run_id, script="OK-WW", user="wuwa", ok=False):
    now = datetime.now(tz=SERVER_TZ)
    return RunRecord(run_id=run_id, script=script, user=user,
                     started=now - timedelta(minutes=10), finished=now,
                     ok=ok, failed_tasks=[] if ok else ["任务执行：某个错"], raw={})


def build(state_dir=None, source=None):
    """一台干净的中继。state_dir 复用同一个就等于「重启一次」。"""
    cfg = Config()
    cfg.state_dir = state_dir or tmpdir()
    e = eng.Engine(cfg, source=source or Src(), state=State(cfg.state_dir),
                   notifier=Notes())
    e._scripts_running = lambda: False
    return e


# ---------------------------------------------------------------- 告警落盘

print("[待推告警落盘：存进去，重启后还在（09-08 轰炸事故就炸在这一行）]")
sdir = tmpdir()
e1 = build(sdir)
e1._pending[("OK-WW", "wuwa")] = rec("2026-09-08/wuwa/OK-WW-05-22-26")
e1._recovered[("MaaEnd", "endfield")] = rec("2026-09-08/endfield/MaaEnd-06-01-00",
                                            script="MaaEnd", user="endfield")
raised = ""
try:
    e1._persist_pending()
except Exception as exc:  # noqa: BLE001
    raised = f"{type(exc).__name__}: {exc}"
check("_persist_pending 不抛异常", raised, "")

e2 = build(sdir)          # 重启：同一个 state 目录，全新实例
check("重启后待推告警还在", list(e2._pending), [("OK-WW", "wuwa")])
check("重启后自愈告警也还在", list(e2._recovered), [("MaaEnd", "endfield")])
check("内容没走样", e2._pending[("OK-WW", "wuwa")].failed_tasks, ["任务执行：某个错"])
check("run_id 对得上", e2._pending[("OK-WW", "wuwa")].run_id,
      "2026-09-08/wuwa/OK-WW-05-22-26")
check("重启不算「已处理」", e2._pending[("OK-WW", "wuwa")].ok, False)

print("\n[推出去之后要能清干净，否则下次开机又推一遍]")
e2._pending.clear()
e2._recovered.clear()
e2._persist_pending()
e3 = build(sdir)
check("清空后重启是空的", (dict(e3._pending), dict(e3._recovered)), ({}, {}))

print("\n[盘上有一条残缺记录，不许连累好的那条]")
sdir2 = tmpdir()
st = State(sdir2)
from ark_relay.transport import record_to_payload            # noqa: E402
try:
    st.save_pending({"pending": [record_to_payload(rec("2026-09-08/wuwa/OK-WW-1")),
                                 {"run_id": "缺时间字段"}],
                     "recovered": []})
except Exception as exc:  # noqa: BLE001 - 保住 FAILED 那一行，别变成一串回溯
    fails.append(f"save_pending 抛异常：{type(exc).__name__}: {exc}")
e4 = build(sdir2)
check("好的那条读回来了", [r.run_id for r in e4._pending.values()],
      ["2026-09-08/wuwa/OK-WW-1"])

print("\n[从没存过时不许抛异常（全新机器第一次开机走的就是这条）]")
raised = ""
try:
    build(tmpdir())
except Exception as exc:  # noqa: BLE001
    raised = f"{type(exc).__name__}: {exc}"
check("空目录能起来", raised, "")


# ---------------------------------------------------------------- 首次启动

print("\n[bootstrap：第一次启动把已有历史当作已处理]")
old = [rec(f"2026-09-01/wuwa/OK-WW-0{i}") for i in range(1, 4)]
sdir3 = tmpdir()
src = Src(old)
e5 = build(sdir3, source=src)
check("接管了 3 条历史", e5.bootstrap(), 3)
check("三条都记成已处理", sorted(e5.state.seen), sorted(r.run_id for r in old))
check("seen 文件已落盘", e5.state.seen_path.exists(), True)

print("\n[接管完再跑一轮，一条都不许推出去]")
before = len(e5.notifier.sent)
check("这一轮没有新记录", e5.tick(), 0)
check("没有推送", len(e5.notifier.sent), before)

print("\n[第二次启动不是「第一次」：历史不再接管，新记录才算新闻]")
e6 = build(sdir3, source=Src(old))
check("不再接管", e6.bootstrap(), 0)

print("\n[历史是空的时候也要留下记号，否则下次开机又被当成第一次]")
sdir4 = tmpdir()
e7 = build(sdir4, source=Src([]))
check("没有可接管的", e7.bootstrap(), 0)
check("空文件也要建出来", e7.state.seen_path.exists(), True)
e8 = build(sdir4, source=Src([rec("2026-09-08/wuwa/OK-WW-新的")]))
check("下次启动不再当第一次", e8.bootstrap(), 0)


# ---------------------------------------------------------------- 在跑判断

print("\n[scripts_running：三秒缓存——一轮里十几处都在问，只许问一次]")
real_os, real_busy, real_sub = eng.os, eng._automas_busy, eng.subprocess
asked = []


def fake_busy():
    asked.append(1)
    return fake_busy.answer


try:
    eng.os = types.SimpleNamespace(name="nt")     # 只用到 os.name 这一处
    eng._automas_busy = fake_busy

    fake_busy.answer = True
    eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
    check("第一次问 AUTO-MAS", eng.Engine._scripts_running(), True)
    check("确实问了一次", len(asked), 1)
    check("三秒内直接用上次的答案", eng.Engine._scripts_running(), True)
    check("没有再问第二次", len(asked), 1)

    fake_busy.answer = False
    eng.subprocess = types.SimpleNamespace(     # AUTO-MAS 说没在跑时才会去翻进程表
        run=lambda *a, **k: types.SimpleNamespace(stdout=b""),
        SubprocessError=real_sub.SubprocessError)
    check("缓存期内答案不变", eng.Engine._scripts_running(), True)
    check("缓存命中就没去问", len(asked), 1)
    eng._SCRIPTS_CACHE["at"] -= eng._SCRIPTS_TTL + 1        # 缓存过期
    check("过期后重新问", eng.Engine._scripts_running(), False)
    check("确实又问了", len(asked), 2)

    print("\n[缓存只敢缓存三秒：写配置要靠它判断，缓存久了就写进正在跑的那一份（826 那一类）]")
    check("TTL 不超过 3 秒", eng._SCRIPTS_TTL <= 3.0, True)

    print("\n[public 的 scripts_running 和内部判断必须是同一个答案]")
    e9 = build()
    del e9._scripts_running                     # 用回真的那个
    eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
    fake_busy.answer = True
    check("对外一致", e9.scripts_running(), True)

    print("\n[问不出来的时候宁可当作在跑：判断错方向就是写坏配置]")
    fake_busy.answer = None

    def blow_up(*a, **k):
        raise OSError("tasklist 跑不起来")

    eng.subprocess = types.SimpleNamespace(run=blow_up,
                                           SubprocessError=real_sub.SubprocessError)
    eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
    check("进程表也问不到 → 当作在跑", eng.Engine._scripts_running(), True)

    print("\n[Endfield.exe 也要算：MaaEnd 自己没有进程，只盯 MaaEnd.exe 会整段瞎掉]")
    for name, want in ((b"Endfield.exe", True), (b"MAA.exe", True),
                       (b"MaaEnd.exe", True), (b"explorer.exe", False)):
        eng.subprocess = types.SimpleNamespace(
            run=lambda *a, **k: types.SimpleNamespace(stdout=b'"%s","123"\r\n' % name),
            SubprocessError=real_sub.SubprocessError)
        eng._SCRIPTS_CACHE.update(at=-1e9, val=False)
        check(f"进程表里只有 {name.decode()}", eng.Engine._scripts_running(), want)
finally:
    eng.os, eng._automas_busy, eng.subprocess = real_os, real_busy, real_sub
    eng._SCRIPTS_CACHE.update(at=-1e9, val=False)


# ---------------------------------------------------------------- tick 逐段兜底

print("\n[tick 逐段兜底：九段里随便哪一段炸，另外八段照跑]")
STEPS = ("_patch_okww_if_updated", "_flush_pending", "_enforce_annihilation",
         "_weekly_gates", "_check_missed_runs", "_maybe_interim_report",
         "_maybe_deferred_update", "_maybe_daily_report", "_maybe_shutdown")


def arm(engine, broken):
    """把九段全换成记录器，其中一段改成会炸的。

    只写一个 `step`，坏不坏由闭包里的 name 决定——原来写成 if/else 里各一个
    同名 def，死代码闸门会判成「后一个把前一个盖掉」。那道闸门看不懂分支，
    而它拦住的那类错（同作用域重名，后者静静覆盖前者）值得留着，所以改测试。
    """
    ran = []

    def make(name):
        def step(*a, **k):
            ran.append(name)            # 记下来再炸，证明它确实被调到了
            if name == broken:
                raise RuntimeError(f"「{name}」这一段坏了")
        return step

    for name in STEPS:
        setattr(engine, name, make(name))
    return ran


e10 = build()
for broken in STEPS:
    ran = arm(e10, broken)
    raised = ""
    try:
        e10.tick()
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    check(f"「{broken}」炸了不许把异常抛出 tick", raised, "")
    missing = [s for s in STEPS if s not in ran]
    check(f"「{broken}」炸了，其余八段照跑", missing, [])

print("\n[日报和关机是最后两段，被前面任何一段带走 = 机器整夜不关]")
for broken in STEPS[:-2]:
    ran = arm(e10, broken)
    try:
        e10.tick()
    except Exception as exc:  # noqa: BLE001 - 保住 FAILED 那一行，别变成一串回溯
        fails.append(f"「{broken}」把异常抛出了 tick：{type(exc).__name__}")
    check(f"「{broken}」炸了，日报和关机仍然跑到",
          ("_maybe_daily_report" in ran, "_maybe_shutdown" in ran), (True, True))

print("\n[跳过模式那一段炸了也不许带走 tick（它在逐段循环之外）]")
real_skip = modes.process_skip
try:
    def boom(*a, **k):
        raise RuntimeError("QueueConfig 读不了")

    modes.process_skip = boom
    ran = arm(e10, None)
    raised = ""
    try:
        e10.tick()
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    check("跳过模式出错不抛出 tick", raised, "")
    check("九段照跑", [s for s in STEPS if s not in ran], [])
finally:
    modes.process_skip = real_skip

print("\n[同一条跳过模式的报错，一轮一轮地重复推 = 又一次群轰炸]")
try:
    modes.process_skip = lambda *a, **k: ["队列「早班」不见了，恢复标记还压着"]
    e11 = build()
    e11._scripts_running = lambda: False
    for _ in range(5):
        e11._observe_modes()
    check("同一句只推一次", len(e11.notifier.sent), 1)
finally:
    modes.process_skip = real_skip

print("\n[处理单条记录出错，不许带走同一轮里的其他记录]")
e12 = build(source=Src([rec("r1"), rec("r2"), rec("r3")]))
handled = []


def flaky(r):
    handled.append(r.run_id)
    if r.run_id == "r2":
        raise RuntimeError("这条记录处理不了")


e12._handle = flaky
for name in STEPS:
    setattr(e12, name, lambda *a, **k: None)
check("三条都试过了", (e12.tick(), sorted(handled)), (3, ["r1", "r2", "r3"]))
check("成功的两条记成已处理", sorted(e12.state.seen), ["r1", "r3"])


print("[读模式开关炸了，也不许带走整轮——日报和关机在最后]")
eng2 = build()
ran = []
eng2._observe_modes = lambda: (_ for _ in ()).throw(RuntimeError("模式文件读坏了"))
for name in ("_patch_okww_if_updated", "_flush_pending", "_maybe_daily_report"):
    setattr(eng2, name, (lambda n=name: (lambda *a, **k: ran.append(n)))())
try:
    eng2.tick()
    check("tick 没有把异常抛出去", True, True)
except Exception as e:                      # noqa: BLE001
    check(f"tick 没有把异常抛出去（抛了 {e}）", False, True)
check("后面的段照样跑到了", "_maybe_daily_report" in ran, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
