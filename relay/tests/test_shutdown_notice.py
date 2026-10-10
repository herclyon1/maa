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

print("[every reason the machine stays on: nothing pushed (10-10 23:22: only 「关机被取消」 is)]")
e = engine(CUTOFF)
for code, why in (("running", "还有脚本或游戏在跑"), ("pending", "还有告警没推出去"), ("debug", "调试模式开着"),
                  ("not-shift", "不是早班/晚班跑完"), ("shift-running", "等排期的那趟跑完再判关机")):
    shutdown._say_if_moment_passed(e, NIGHT, shutdown.Verdict(False, code, why))
check("none of them pushed", e.sent, [])
check("the 「今晚不关机」 title is gone", hasattr(texts, "NO_SHUTDOWN"), False)

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
check("pushed 「关机被取消」 at once", [(t, a) for t, _, a in e.sent], [(texts.SHUTDOWN_CANCELLED, True)])
check("one plain line with the time", e.sent[0][1] if e.sent else "", f"关机没成功（关机命令 22:00 发出，过了 {STUCK_MIN} 分钟机器还开着）")
shutdown._say_if_moment_passed(e, later + timedelta(hours=1), shutdown.decide(e, later + timedelta(hours=1)))
check("同一次没关下去：只推一次", len(e.sent), 1)
check("文字是人话", texts.plain(e.sent[0][1]) if e.sent else [], [])
e = engine(CUTOFF)
e._shutdown_issued = True                        # issued, but not when (an engine from before 10-06)
check("不知道几点发的：照旧「正在关」", shutdown.decide(e, later).code, "issued")

print("[关机命令被取消了：取消前后有人在用 -> 只记日报；看不出有人 -> 进群（2026-10-10）]")
NS = "http://schemas.microsoft.com/win/2004/08/events/event"
FIX = Path(__file__).resolve().parent / "fixtures"
# Real System log events read on the machine 2026-10-10 (newest first, as shutdown_event_xml returns them):
# 10-01: 1074 13:48:52Z (the relay), 566 13:49:36Z (Reason 32, input woke the display), 1075 13:49:52Z by INS\Administrator.
# 10-02: 1074 13:49:01Z (the relay), 1075 13:49:08Z by INS\Administrator, no 566.
REAL_1001 = (FIX / "system-1001-cancel.xml").read_text(encoding="utf-8").splitlines()
REAL_1002 = (FIX / "system-1002-cancel.xml").read_text(encoding="utf-8").splitlines()


def ev(eid, utc):
    data = "".join(f"<Data>{d}</Data>" for d in ("C:\\Windows\\system32\\shutdown.exe (INS)", "INS",
                                                   "x", "0x80040001", "关机", "ark-relay: run complete",
                                                   "INS\\Administrator")) if eid == 1074 else ""
    return (f'<Event xmlns="{NS}"><System><EventID>{eid}</EventID>'
            f'<TimeCreated SystemTime="{utc}"/></System><EventData>{data}</EventData></Event>')


saved_reader = shutdown.shutdown_event_xml
asked = []


def run(xmls, idle, issued):
    """decide at ISSUED_STUCK_MIN after `issued`, the day's report already out (10-01 21:48:40)."""
    shutdown.shutdown_event_xml = lambda s, ids=(1074, 1075), x=xmls: asked.append((s, ids)) or x
    e = engine(issued.replace(hour=23, minute=59))     # before that day's cutoff, on purpose
    e._shutdown_issued, e._shutdown_issued_at = True, issued
    e.state.report_sent = lambda d: d == f"{issued:%Y-%m-%d}"
    at = issued + timedelta(minutes=STUCK_MIN)
    v = shutdown.decide(e, at)
    shutdown._say_if_moment_passed(e, at, v)
    return e, v, at


print(" [an aborted power-off, whoever did it: one line to the group, nobody named (10-10 23:22)]")
# The user, 2026-10-10 23:22 (Tokyo), quoted in USER-SWITCHES.txt at _say_if_moment_passed.
for label, xmls, when in (("10-01 (a 566 before the abort)", REAL_1001, datetime(2026, 10, 1, 21, 48, 52, tzinfo=SERVER_TZ)),
                          ("10-02 (no 566, 7 s after the command)", REAL_1002, datetime(2026, 10, 2, 21, 49, 1, tzinfo=SERVER_TZ))):
    e, v, at = run(xmls, None, when)
    check(f"{label}: cancelled", v.code, "cancelled")
    check(f"{label}: says when it went out and when it was cancelled",
          all(w in v.reason for w in (f"{when:%H:%M}", "被取消了")), True)
    check(f"{label}: does not say who", "Administrator" in v.reason or "键鼠" in v.reason, False)
    check(f"{label}: pushed once, the time only", [(t, b) for t, b, _ in e.sent], [(texts.SHUTDOWN_CANCELLED, f"关机被取消（{v.reason.split('，')[1][:5]}）")])
    check(f"{label}: nothing kept for the daily report", sorted(p.name for p in Path(e.state.dir).glob("shutdown-cancels-*")), [])
    shutdown._say_if_moment_passed(e, at + timedelta(minutes=5), shutdown.decide(e, at + timedelta(minutes=5)))
    check(f"{label}: still one push five minutes on", len(e.sent), 1)
check("the reader still asks for the 566 (harmless) and covers the command", asked[-1][0] >= STUCK_MIN * 60, True)
check("no 「cancelled-unseen」 any more", "cancelled-unseen" in src, False)
check("nothing reads who uses the console", any(w in src for w in ("console_idle_s", "query user", "IN_USE_IDLE_MIN")), False)

print(" [不是取消的情况]")
issued = datetime(2026, 10, 1, 21, 48, 52, tzinfo=SERVER_TZ)
for label, xmls, want in (
        ("取消之后又有 1074（又有人下了关机）：照旧没关下去", [ev(1074, "2026-10-01T13:55:00Z")] + REAL_1001, "not-down"),
        ("只有中继的 1074：没关下去", [ev(1074, "2026-10-01T13:48:52Z")], "not-down"),
        ("系统日志读不到：照旧没关下去", None, "not-down")):
    e, v, at = run(xmls, 0, issued)
    check(label, v.code, want)
shutdown.shutdown_event_xml = saved_reader
e = engine(CUTOFF)
e._shutdown_issued, e._shutdown_issued_at = True, issued
check("命令刚发出不久：不读系统日志，照旧「正在关」",
      (shutdown.decide(e, issued + timedelta(minutes=1)).code), "issued")
check("cancelled_at：事件串是空的", shutdown.cancelled_at([]), None)
check("cancel_event：真实 1075 的账户是 param2",
      getattr(shutdown, "cancel_event", lambda x: (None, None))(REAL_1002)[1], "INS\\Administrator")

print("[every other code decide returns: not pushed, not in the daily report (10-10 23:22)]")
codes = set(re.findall(r'Verdict\((?:True|False),\s*"([^"]+)"', src))
check("decide's codes found", {"off", "debug", "skipped", "issued", "not-down", "cancelled", "uptime", "makeup",
                               "not-shift", "report", "running", "go"} <= codes)
for code in sorted(codes - {"go", "not-down", "cancelled"}) + ["shift-ahead", "shift-running"]:
    e = engine(CUTOFF)
    e.state.report_sent = lambda day: False
    e._boot_time = lambda now: NIGHT.replace(hour=11, minute=45)
    shutdown._say_if_moment_passed(e, NIGHT, shutdown.Verdict(False, code, f"测试原因 {code}"))
    check(f"{code}: not pushed", e.sent, [])
    check(f"{code}: nothing kept for the daily report", sorted(p.name for p in Path(e.state.dir).glob("shutdown-cancels-*")), [])
for code, why in (("off", "关机功能没开"), ("uptime", "开机不够久"),
                  ("report", "到点该关机了，但日报还没发出去，继续等")):
    check(f"{code} 的原因在 decide 里原样写着", f'"{code}", "{why}"' in src)

print("[debug mode eats this power-off: recorded, nothing pushed]")
e = engine(CUTOFF)
e.state.dir = tmpdir()
e._last_wait_note = ""
real_debug = shutdown.modes.debug_active
shutdown.modes.debug_active = lambda d: True
try:
    got = shutdown._maybe_shutdown(e, NIGHT)
finally:
    shutdown.modes.debug_active = real_debug
check("debug: no power-off", got, False)
check("debug: nothing pushed", e.sent, [])
check("…this occasion recorded as before (no late power-off)", shutdown.modes.shutdown_skipped(e.state.dir), f"{NIGHT:%Y-%m-%d}:3")
check("after it: skipped", shutdown.decide(e, NIGHT).code, "skipped")

print("[刷声骸那条要说清刷到几点，不能只说「在刷」]")
check("理由里带收工时刻", "才收工" in src)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
