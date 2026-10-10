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
from ark_relay import report as _report
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


saved_reader, saved_idle = shutdown.shutdown_event_xml, getattr(shutdown, "console_idle_s", None)
asked = []


def run(xmls, idle, issued):
    """decide at ISSUED_STUCK_MIN after `issued`, the day's report already out (10-01 21:48:40)."""
    shutdown.shutdown_event_xml = lambda s, ids=(1074, 1075), x=xmls: asked.append((s, ids)) or x
    shutdown.console_idle_s = lambda i=idle: i
    e = engine(issued.replace(hour=23, minute=59))     # before that day's cutoff, on purpose
    e._shutdown_issued, e._shutdown_issued_at = True, issued
    e.state.report_sent = lambda d: d == f"{issued:%Y-%m-%d}"
    at = issued + timedelta(minutes=STUCK_MIN)
    v = shutdown.decide(e, at)
    shutdown._say_if_moment_passed(e, at, v)
    return e, v, at


def nextday(issued):
    return f"{issued + timedelta(days=1):%Y-%m-%d}"

print(" [10-01 真实事件：566 输入唤醒屏幕在 1075 之前 16 秒 -> 有人在用，只记日报]")
issued = datetime(2026, 10, 1, 21, 48, 52, tzinfo=SERVER_TZ)
e, v, at = run(REAL_1001, None, issued)            # idle unreadable: the 566 alone decides
check("10-01：判为有人在用的取消", v.code, "cancelled")
check("10-01：写着几点发、几点被哪个账户取消、几点有键鼠",
      all(w in v.reason for w in ("21:48", "21:49:52", "INS\\Administrator", "21:49:36 有键鼠")), True)
check("10-01：读系统日志时带上 566", asked[-1][1], (1074, 1075, 566))
check("10-01：读的时间窗盖住命令发出时刻", asked[-1][0] >= (at - issued).total_seconds(), True)
check("10-01：不进群", e.sent, [])
noted = _report.cancels_of_day(e.state.dir, nextday(issued))
check("10-01：当天日报已发，记进下一份", "21:49:52" in noted and "有键鼠" in noted, True)
check("10-01：当天那份不再记", _report.cancels_of_day(e.state.dir, f"{issued:%Y-%m-%d}"), "")
check("10-01：文字是人话", texts.plain(noted), [])
shutdown._say_if_moment_passed(e, at + timedelta(minutes=5), shutdown.decide(e, at + timedelta(minutes=5)))
check("10-01：同一次取消，日报只记一行", len(_report.cancels_of_day(e.state.dir, nextday(issued)).splitlines()), 1)

print(" [10-02 真实事件：7 秒后被取消、没有 566；取消前后没有键鼠（空闲 11 分钟）-> 进群]")
issued = datetime(2026, 10, 2, 21, 49, 1, tzinfo=SERVER_TZ)
e, v, at = run(REAL_1002, 11 * 60, issued)
check("10-02 没人动：判为看不出有人的取消", v.code, "cancelled-unseen")
check("10-02 没人动：进群，不等日报截止", [(t, a) for t, _, a in e.sent], [(texts.NO_SHUTDOWN, True)])
body = e.sent[0][1] if e.sent else ""
check("10-02 没人动：群里写着几点、哪个账户、取消前后没人动",
      all(w in body for w in ("21:49", "21:49:08", "INS\\Administrator", "没有键鼠操作")), True)
check("10-02 没人动：文字是人话", texts.plain(body), [])
check("10-02 没人动：不记日报", _report.cancels_of_day(e.state.dir, nextday(issued)), "")
shutdown.console_idle_s = lambda: 0                # someone touches it later: same power-off, same verdict
shutdown._say_if_moment_passed(e, at + timedelta(minutes=5), shutdown.decide(e, at + timedelta(minutes=5)))
check("10-02 没人动：同一次取消只推一次", len(e.sent), 1)

print(" [10-02 真实事件：那晚其实有人在运行框里打了 shutdown -a；取消后还有键鼠（空闲不到一分钟）-> 只记日报]")
e, v, at = run(REAL_1002, 0, issued)
check("10-02 有人：判为有人在用的取消", v.code, "cancelled")
check("10-02 有人：不进群", e.sent, [])
check("10-02 有人：记进日报", "21:49:08" in _report.cancels_of_day(e.state.dir, nextday(issued)), True)
e, v, at = run(REAL_1002, 9 * 60, issued)          # last input up to 10 min ago, i.e. around the 7-second abort
check("10-02 取消那一刻前后有键鼠、之后没再动：算有人", v.code, "cancelled")

print(" [10-02 真实事件：空闲时间读不到 -> 进群，写明读不到]")
e, v, at = run(REAL_1002, None, issued)
check("读不到空闲：看不出有人", v.code, "cancelled-unseen")
check("读不到空闲：写明读不到", "读不到这台电脑有没有键鼠操作" in v.reason, True)

print(" [不是取消的情况]")
issued = datetime(2026, 10, 1, 21, 48, 52, tzinfo=SERVER_TZ)
for label, xmls, want in (
        ("取消之后又有 1074（又有人下了关机）：照旧没关下去", [ev(1074, "2026-10-01T13:55:00Z")] + REAL_1001, "not-down"),
        ("只有中继的 1074：没关下去", [ev(1074, "2026-10-01T13:48:52Z")], "not-down"),
        ("系统日志读不到：照旧没关下去", None, "not-down")):
    e, v, at = run(xmls, 0, issued)
    check(label, v.code, want)
shutdown.shutdown_event_xml, shutdown.console_idle_s = saved_reader, saved_idle
e = engine(CUTOFF)
e._shutdown_issued, e._shutdown_issued_at = True, issued
check("命令刚发出不久：不读系统日志，照旧「正在关」",
      (shutdown.decide(e, issued + timedelta(minutes=1)).code), "issued")
check("cancelled_at：事件串是空的", shutdown.cancelled_at([]), None)
check("cancel_event：真实 1075 的账户是 param2",
      getattr(shutdown, "cancel_event", lambda x: (None, None))(REAL_1002)[1], "INS\\Administrator")

print("[query user 的空闲列（2026-10-10 机器上以 SYSTEM 读到的原样）]")
parse = getattr(shutdown, "parse_console_idle", lambda out: "missing")
QU = (" 用户名                会话名             ID  状态    空闲时间   登录时间\n"
      " administrator         console             1  运行中      无     2026/10/10 11:45\n")
check("「无」= 一分钟内有键鼠", parse(QU), 0)
check("分钟数", parse(QU.replace("无", "9")), 540)
check("天+时:分", parse(QU.replace("无", "1+02:05")), ((24 + 2) * 60 + 5) * 60)
check("没有 console 那行：读不到", parse(QU.splitlines()[0]), None)
import subprocess  # noqa: E402 - console_idle_s imports it at call time; stubbed here, put back below

_real_run = subprocess.run
subprocess.run = lambda *a, **k: SimpleNamespace(stdout=QU, returncode=1)    # quser exits 1 as SYSTEM, output intact
check("console_idle_s：读 query user 的 console 行", getattr(shutdown, "console_idle_s", lambda: "missing")(), 0)


def _boom(*a, **k):
    raise FileNotFoundError("query")


subprocess.run = _boom
check("console_idle_s：query 跑不起来 = 读不到", getattr(shutdown, "console_idle_s", lambda: "missing")(), None)
subprocess.run = _real_run

print("[除了中继自己发出的关机，每个不关机的原因都进群（2026-10-06：之前 off/debug/skipped/uptime/"
      "makeup/nothing-done/report 七个不推）]")
codes = set(re.findall(r'Verdict\((?:True|False),\s*"([^"]+)"', src))
check("decide 的码都找到了", {"off", "debug", "skipped", "issued", "not-down", "cancelled", "uptime", "makeup",
                             "not-shift", "shift-ahead", "in-use", "report", "running", "go"} <= codes)
# cancelled / in-use / not-shift: daily report only; shift-ahead: neither (below)
for code in sorted(codes - {"go", "issued", "cancelled", "in-use", "not-shift", "shift-ahead"}):
    e = engine(CUTOFF)
    reason = f"测试原因 {code}" if code != "debug" else "调试模式开着，这一次关机跳过"
    shutdown._say_if_moment_passed(e, NIGHT, shutdown.Verdict(False, code, reason))
    check(f"{code}：到点后进群", [(t, a) for t, _, a in e.sent], [(texts.NO_SHUTDOWN, True)])
e = engine(CUTOFF)
shutdown._say_if_moment_passed(e, NIGHT, shutdown.Verdict(False, "issued", "关机命令已经发出去了，机器正在关"))
check("issued（中继自己在关机）：不推", e.sent, [])
for code, why in (("off", "关机功能没开"), ("uptime", "开机不够久"),
                  ("report", "到点该关机了，但日报还没发出去，继续等")):
    check(f"{code} 的原因在 decide 里原样写着", f'"{code}", "{why}"' in src)

print("[not a shift ending (18:31) / someone using it (18:30): daily report once, never the group]")
from ark_relay import report  # noqa: E402
from ark_relay.statestore import StateStore  # noqa: E402
for code, reason, line in (
        ("not-shift", "不是早班/晚班跑完，不关机（这次是 10-06 11:45 开的机，之后没有到点的排期）", "不是早班/晚班跑完"),
        ("in-use", "有人在用这台电脑（1 分钟内还有键鼠操作），等没人用满 15 分钟再关", "有人在用这台电脑")):
    e = engine(CUTOFF)
    e.state.store = StateStore(e.state.dir)       # the real one: it refuses marks not in statestore.FIELDS
    e.state.report_sent = lambda day: False
    e._boot_time = lambda now: NIGHT.replace(hour=11, minute=45)
    for i in range(3):
        shutdown._say_if_moment_passed(e, NIGHT + timedelta(minutes=i), shutdown.Verdict(False, code, reason))
    check(f"{code}: not pushed", e.sent, [])
    got = report.cancels_of_day(e.state.dir, f"{NIGHT:%Y-%m-%d}")
    check(f"{code}: one line in the daily report", (got.count("\n") + 1 if got else 0, line in got), (1, True))
e = engine(CUTOFF)
e.state.report_sent = lambda day: False
shutdown._say_if_moment_passed(e, NIGHT, shutdown.Verdict(False, "shift-ahead", "等排期的那趟跑完再判关机（排期 21:30 那趟还没开始）"))
check("shift-ahead: not pushed", e.sent, [])
check("shift-ahead: not in the daily report", report.cancels_of_day(e.state.dir, f"{NIGHT:%Y-%m-%d}"), "")

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
