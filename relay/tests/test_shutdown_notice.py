"""The 「今晚不关机」 message must never go out when the machine is in fact shutting down.

At 22:46 on 2026-09-09 the command had already been sent, and the push still read
「到点了但没关机：关机令已经下过了。机器会一直开着」 - then the machine shut down.
The verdict code for "the command has gone out" was listed among the reasons a machine
stays awake, and its wording read as though someone had ordered it to stay on.
"""
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ark_relay import shutdown, texts
from ark_relay.config import SERVER_TZ

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


src = Path(shutdown.__file__).read_text(encoding="utf-8")

print("[关机命令已经发出去，就不是「没关机」]")
check("中继自己发出的关机是唯一不推的码", getattr(shutdown, "RELAY_POWER_OFF", None), "issued")
check("没有「卡住才推」的名单了", hasattr(shutdown, "_STUCK_CODES"), False)
verdict = re.search(r'Verdict\(False, "issued", "([^"]+)"\)', src)
check("找得到那句话", bool(verdict))
check("不再像「有人下令别关」", "已经下过了" in (verdict.group(1) if verdict else ""), False)
check("改成说清是正在关", "机器正在关" in src)


class _Store:
    def __init__(self):
        self.d = {}

    def get(self, ns, key):
        return self.d.get((ns, key))

    def set(self, ns, key, value):
        self.d[(ns, key)] = value


def engine(cutoff):
    sent = []
    return SimpleNamespace(
        state=SimpleNamespace(store=_Store(), dir=tmpdir(), read_ledger=lambda day: []),
        notifier=SimpleNamespace(send=lambda t, b, alert=False: sent.append((t, b, alert)) or []),
        _report_cutoff=lambda now: cutoff, sent=sent, cfg=SimpleNamespace(shutdown_after_run=True),
        _shutdown_issued=False, _shutdown_key=lambda now: f"{now:%Y-%m-%d}:3")


NIGHT = datetime(2026, 10, 6, 22, 0, tzinfo=SERVER_TZ)
CUTOFF = NIGHT.replace(hour=21, minute=30)

print("[一个原因一条：同一个原因反复判只推一次，换了原因再推（2026-10-06 之前一天只推第一条）]")
e = engine(CUTOFF)
running = shutdown.Verdict(False, "running", "还有脚本或游戏在跑")
for i in range(3):
    shutdown._say_if_moment_passed(e, NIGHT + timedelta(minutes=i), running)
check("同一个原因判三次：一条", [t for t, _, _ in e.sent], [texts.NO_SHUTDOWN])
check("是群报警", [a for _, _, a in e.sent], [True])
check("正文写着原因", "还有脚本或游戏在跑" in e.sent[0][1])
pending = shutdown.Verdict(False, "pending", "还有告警没推出去")
shutdown._say_if_moment_passed(e, NIGHT + timedelta(minutes=5), pending)
check("那个原因没了、另一个原因又让机器开着：再推一条", len(e.sent), 2)
check("第二条说的是新原因", "还有告警没推出去" in (e.sent[-1][1] if e.sent else ""))
shutdown._say_if_moment_passed(e, NIGHT + timedelta(minutes=6), pending)
check("新原因再判一次：不再推", len(e.sent), 2)
e = engine(CUTOFF)
shutdown._say_if_moment_passed(e, CUTOFF - timedelta(minutes=1), running)
check("还没到点：不推", e.sent, [])

print("[关机命令发出去十分钟以上机器还开着：没关下去，推（2026-10-06 之前一直判「正在关」，不吭声）]")
STUCK_MIN = getattr(shutdown, "ISSUED_STUCK_MIN", 10)
e = engine(NIGHT + timedelta(hours=3))          # long before that day's cutoff, on purpose
e._shutdown_issued = True
e._shutdown_issued_at = NIGHT
v = shutdown.decide(e, NIGHT + timedelta(minutes=STUCK_MIN - 1))
check("刚发出去不久：还是「正在关」", v.code, "issued")
shutdown._say_if_moment_passed(e, NIGHT + timedelta(minutes=STUCK_MIN - 1), v)
check("正在关：不推", e.sent, [])
later = NIGHT + timedelta(minutes=STUCK_MIN)
v = shutdown.decide(e, later)
check(f"{STUCK_MIN} 分钟后还在判：没关下去", v.code, "not-down")
check("原因写着几点发的命令", "22:00" in v.reason and "没有关下去" in v.reason)
shutdown._say_if_moment_passed(e, later, v)
check("推了，不等日报截止", [t for t, _, _ in e.sent], [texts.NO_SHUTDOWN])
shutdown._say_if_moment_passed(e, later + timedelta(hours=1), shutdown.decide(e, later + timedelta(hours=1)))
check("同一次没关下去：只推一次", len(e.sent), 1)
check("文字是人话", texts.plain(e.sent[0][1]) if e.sent else [], [])
e = engine(CUTOFF)
e._shutdown_issued = True                        # issued, but not when (an engine from before 10-06)
check("不知道几点发的：照旧「正在关」", shutdown.decide(e, later).code, "issued")

print("[除了中继自己发出的关机，每个不关机的原因都进群（2026-10-06：之前 off/debug/skipped/uptime/"
      "makeup/nothing-done/report 七个不推）]")
codes = set(re.findall(r'Verdict\((?:True|False),\s*"([^"]+)"', src))
check("decide 的码都找到了", {"off", "debug", "skipped", "issued", "not-down", "uptime", "makeup",
                             "nothing-done", "report", "running", "go"} <= codes)
for code in sorted(codes - {"go", "issued"}):
    e = engine(CUTOFF)
    reason = f"测试原因 {code}" if code != "debug" else "调试模式开着，这一次关机跳过"
    shutdown._say_if_moment_passed(e, NIGHT, shutdown.Verdict(False, code, reason))
    check(f"{code}：到点后进群", [(t, a) for t, _, a in e.sent], [(texts.NO_SHUTDOWN, True)])
e = engine(CUTOFF)
shutdown._say_if_moment_passed(e, NIGHT, shutdown.Verdict(False, "issued", "关机命令已经发出去了，机器正在关"))
check("issued（中继自己在关机）：不推", e.sent, [])
for code, why in (("off", "关机功能没开"), ("uptime", "开机不够久"),
                  ("nothing-done", "本次开机还没有跑完任何队列"),
                  ("report", "到点该关机了，但日报还没发出去，继续等")):
    check(f"{code} 的原因在 decide 里原样写着", f'"{code}", "{why}"' in src)

print("[调试模式吃掉这次关机：也推「今晚不关机」（2026-10-06 之前直接返回，群里不知道）]")
e = engine(CUTOFF)
e.state.dir = tmpdir()
e._last_wait_note = ""
real_debug = shutdown.modes.debug_active
shutdown.modes.debug_active = lambda d: True
try:
    got = shutdown._maybe_shutdown(e, NIGHT)
finally:
    shutdown.modes.debug_active = real_debug
check("调试模式：不关机", got, False)
check("调试模式：进群一条「今晚不关机」", [(t, a) for t, _, a in e.sent], [(texts.NO_SHUTDOWN, True)])
check("…说的是调试模式开着", "调试模式开着" in (e.sent[0][1] if e.sent else ""))
check("…这一次机会照旧记下（到期不补关）", shutdown.modes.shutdown_skipped(e.state.dir), f"{NIGHT:%Y-%m-%d}:3")
check("…文字是人话", texts.plain(e.sent[0][1]) if e.sent else ["没推"], [])
v = shutdown.decide(e, NIGHT)
check("调试模式过了、这次机会已吃掉：skipped", v.code, "skipped")
shutdown._say_if_moment_passed(e, NIGHT + timedelta(minutes=1), v)
check("skipped 也进群，说清是怎么跳过的", "下次跑完不关机" in (e.sent[-1][1] if e.sent else ""))
check("…文字是人话", texts.plain(e.sent[-1][1]) if e.sent else ["没推"], [])

print("[刷声骸那条要说清刷到几点，不能只说「在刷」]")
check("理由里带收工时刻", "才收工" in src)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
