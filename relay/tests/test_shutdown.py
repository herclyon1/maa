"""Exercise the shutdown gate against a fake AUTO-MAS + ledger.

Since 2026-10-10 18:31 (the user: 「你们有且只允许早班晚班跑完后执行自动关机，他妈的瞎搞
什么呢。」) only the decision right after a scheduled shift finished on this boot may power
off: not one after a relay restart, not one on a machine booted by hand, not before or
during the queue.
"""
import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir
TMP = tmpdir()
AUTOMAS = TMP / "AUTO-MAS"; (AUTOMAS / "config").mkdir(parents=True)
STATE = TMP / "state"; STATE.mkdir()
HIST = TMP / "history"; HIST.mkdir()

# AUTO-MAS's real config shape: instances[] + a node per uid.
(AUTOMAS / "config" / "QueueConfig.json").write_text(json.dumps({
    "instances": [{"uid": "q1"}],
    "q1": {"Info": {"Name": "Evening-MAA", "TimeEnabled": True,
                    "AfterAccomplish": "NoAction"},
           "SubConfigsInfo": {
               "TimeSet": {"t1": {"Info": {"Enabled": True, "Time": "21:30"}}},
               "QueueItem": {"i1": {"Info": {"ScriptId": "s1"}}}}}}),
    encoding="utf-8")
(AUTOMAS / "config" / "ScriptConfig.json").write_text(json.dumps({
    "instances": [{"uid": "s1"}],
    "s1": {"Info": {"Name": "arknights", "Path": "D:\\MAA-v5.1.0-win-x64"},
           "SubConfigsInfo": {"UserData": {"u1": {
               "Info": {"Name": "arknights", "Stage": "1-7", "MedicineNumb": 0},
               "Task": {}}}}}}),
    encoding="utf-8")

os.environ.update(ARK_HISTORY_DIR=str(HIST), ARK_AUTOMAS_DIR=str(AUTOMAS),
                  ARK_STATE_DIR=str(STATE), ARK_SHUTDOWN_AFTER_RUN="1",
                  ARK_SHUTDOWN_MIN_UPTIME="600", SERVERCHAN_KEY="", ARK_LLM_KEY="")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ark_relay.config import Config, SERVER_TZ           # noqa: E402
from ark_relay.core import State                        # noqa: E402
from ark_relay.notify import Notifier                   # noqa: E402
from ark_relay import engine as eng                     # noqa: E402
from ark_relay.statestore import StateStore  # noqa: E402
from ark_relay import plan                              # noqa: E402

cfg = Config()
print("queues seen by plan:", [q["name"] for q in plan.schedule(cfg.automas_dir)])

state = State(cfg.state_dir)
E = eng.Engine(cfg, source=None, state=state, notifier=Notifier(cfg))
E._scripts_running = lambda: False           # no games on this Mac

# GetTickCount64 is Windows-only; drive the uptime gate explicitly instead.
BOOT = [None]
E._boot_time = lambda now: BOOT[0]

DAY = "2026-08-21"
def ledger(*rows):
    # jsonl, one record per line - the real format
    for d in (DAY, "2026-08-20"):
        (STATE / f"ledger-{d}.jsonl").write_text("", encoding="utf-8")
    (STATE / f"ledger-{DAY}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")

def at(hh, mm):
    return datetime(2026, 8, 21, hh, mm, tzinfo=SERVER_TZ)

fails = []
def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
    if not ok:
        fails.append(label)

run = {"script": "MAA", "started": at(21, 31).isoformat(),
       "finished": at(22, 15).isoformat(), "ok": True, "run_id": "x"}

from ark_relay import shutdown as sd                    # noqa: E402
E.state.report_sent = lambda d: True          # the report gate is not what is tested here


def verdict(now):
    return sd.decide(E, now).code


print("\n[18:31] the shift finished on this boot and this relay saw it land: go")
ledger(run)
E._handled_any = True
E._started_at = at(21, 20)
BOOT[0] = at(21, 20)                      # machine booted for this queue
check("shift done at 22:25", verdict(at(22, 25)), "go")

print("\n[18:31] relay restarted after the run finished: not a shift ending, stays on")
# Until 2026-10-10 this was the bug the file was written for (nobody left to power off);
# under the whitelist it is exactly what must not power off.
E._handled_any = False                    # a fresh process, as after selfupdate
E._started_at = at(22, 20)
check("restarted after the shift -> not-shift", verdict(at(22, 35)), "not-shift")
E._handled_any = True
E._started_at = at(21, 20)

print("\n[regression] must NOT power off a machine booted AFTER the queue ran")
BOOT[0] = at(22, 20)
check("booted after the queue -> not-shift", verdict(at(22, 35)), "not-shift")
BOOT[0] = None
check("boot time unknown -> not-shift", verdict(at(22, 35)), "not-shift")
BOOT[0] = at(21, 20)

print("\n[regression] must NOT power off before its own queue")
ledger()
check("21:25, the 21:30 queue still ahead -> shift-ahead", verdict(at(21, 25)), "shift-ahead")
BOOT[0] = at(8, 40)
check("08:50, nothing due at all -> not-shift", verdict(at(8, 50)), "not-shift")
BOOT[0] = at(21, 20)

print("\n[regression] must NOT power off mid-queue")
ledger()
check("due at 21:30, no records yet -> 21:40", verdict(at(21, 40)) == "go", False)

print("\n[18:31] a long shift ends past the old two-hour window: still its shift")
long_run = dict(run, finished=at(23, 50).isoformat())
ledger(long_run)
check("finished 23:50, judged 23:55 -> go", verdict(at(23, 55)), "go")

print("\n[调试模式] 吃掉一次关机机会，而不是到期就补关")
# 用户 2026-08-31：「我开了调试模式是指把一次队列的中继关机指令跳过，
# 而不是中继一直尝试关机，要不然人类没办法使用这个电脑每次都要开调试模式。」
# 改判前：调试模式只是让每次判定返回 False，判定每 30 秒重来，到期后条件
# 没变就立刻关机——人一走开机器自己关了。
# 改判后：生效期间记下「这一次关机机会」并吃掉它；到期后只要没有新队列
# 跑完（机会标识没变）就不补关；新队列一跑完标识变了，恢复正常关机。
# 这里把真正执行关机那步挡掉，只看判定结果。
issued = []
# Like the real subprocess.run: a finished process with exit code 0 (_power_off reads it).
eng.subprocess = type("X", (), {"run": staticmethod(
    lambda *a, **k: issued.append(a) or eng.subprocess.CompletedProcess(a, 0, b"", b"")),
    "CompletedProcess": __import__("subprocess").CompletedProcess})()
ledger(run)
E._handled_any = True
E._started_at = at(21, 20)
BOOT[0] = at(21, 20)
E.state.report_sent = lambda d: True          # 日报已发，不在那道门上卡住
E._last_round_manual = lambda now, entries: False
E._unfinished_queues = lambda now, entries: []

# _maybe_shutdown 查调试模式时用的是**真实**当前时间（生产里 now 就是真实
# 时间，这个参数只为其余判定服务），所以到期点要按真实时钟写。
store = StateStore(STATE)                    # 开关都在 state.json 的 modes 段
def dbg_set(v): store.set("modes", "debug_until", v)
def dbg_clear(): store.pop("modes", "debug_until")
def skipped_clear(): store.pop("modes", "shutdown_skipped")
real = datetime.now(tz=SERVER_TZ)
skipped_clear()

dbg_set(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}")
E._shutdown_issued = False; issued.clear()
check("调试模式生效中：不关机", E._maybe_shutdown(at(23, 0)), False)
check("生效中没有发出关机命令", len(issued), 0)
check("并且把这一次机会记下来了",
      store.get("modes", "shutdown_skipped"), "2026-08-21:1")

dbg_set(f"{real - timedelta(hours=1):%Y-%m-%d %H:%M}")
E._shutdown_issued = False; issued.clear()
check("到期后没有新队列跑完：仍然不关机（人可能正在用）",
      E._maybe_shutdown(at(23, 30)), False)
check("到期后也没有发出关机命令", len(issued), 0)

# 早班又跑了一趟，流水多一条 —— 这是一次新的关机机会
ledger(run, dict(run, run_id="y"))
E._shutdown_issued = False; issued.clear()
check("下一趟队列跑完：恢复正常关机", E._maybe_shutdown(at(23, 40)), True)
check("这次确实发出了关机命令", len(issued), 1)

dbg_clear(); skipped_clear()
ledger(run)
E._shutdown_issued = False; issued.clear()
check("没开过调试模式时，本来就该关机", E._maybe_shutdown(at(23, 0)), True)

print("\n[人工开关] 桌面那个 .bat：只跳过下一次，用完即失效")
# 用户 2026-08-31：「你给一个人类好去调这个模式的方法，独立于你的。」
# 它不带到期时间，就是把**下一次真正要执行的关机**吃掉一次。
dbg_clear(); skipped_clear()
ledger(run)
store.set("modes", "skip_next_shutdown", True)
E._shutdown_issued = False; issued.clear()
check("按下之后：这一次不关机", E._maybe_shutdown(at(23, 0)), False)
check("没有发出关机命令", len(issued), 0)
check("标记被用掉了（用完即失效）", bool(store.get("modes", "skip_next_shutdown")), False)

E._shutdown_issued = False; issued.clear()
check("同一次机会不会因为标记没了就补关",
      E._maybe_shutdown(at(23, 10)), False)

ledger(run, dict(run, run_id="y"))
E._shutdown_issued = False; issued.clear()
check("下一趟队列跑完：正常关机（不用再按一次才关）",
      E._maybe_shutdown(at(23, 40)), True)
skipped_clear()

print("\n[手动关调试] 明确关掉要恢复正常，自然到期不恢复")
from ark_relay import modes                                 # noqa: E402
# 2026-08-31：我维护完手动关掉调试模式，机器却因为「这次已跳过」的标记
# 还在，准备空开一整夜到早班跑完。明确说「关掉」＝维护结束，标记要一起清。
dbg_set(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}")
skipped_clear(); store.pop("modes", "skip_next_shutdown")
ledger(run)
E._shutdown_issued = False; issued.clear()
E._maybe_shutdown(at(23, 0))                       # 生效中，吃掉一次
check("先确认标记确实写下了", bool(store.get("modes", "shutdown_skipped")), True)
modes.set_debug(STATE, off=True)                   # 人明确关掉
check("手动关掉后标记被清掉", bool(store.get("modes", "shutdown_skipped")), False)
E._shutdown_issued = False; issued.clear()
check("于是恢复正常关机", E._maybe_shutdown(at(23, 5)), True)
skipped_clear(); dbg_clear()

print("\n[手机开关] 待办指令 skip_shutdown：手机上改仓库里那个文件")
# 用户 2026-08-31：「我要的是手机上面操作」。中继本来就有「公开仓库放一个
# 文件、手机网页编辑」的收信通道，这里把开关接进那条通道。
os.environ["ARK_STATE_DIR"] = str(STATE)
from ark_relay.commands import apply_command, ALLOWED       # noqa: E402

check("动作在白名单里", "skip_shutdown" in ALLOWED, True)
skipped_clear(); store.pop("modes", "skip_next_shutdown")
E._shutdown_issued = False              # no countdown of ours running here

ok, msg = apply_command({"action": "skip_shutdown"})
check("下指令后开关打开", (ok, modes.skip_armed(STATE)), (True, True))
ok, _ = apply_command({"action": "skip_shutdown", "off": True})
check("再下一条 off 就关掉", (ok, modes.skip_armed(STATE)), (True, False))

# 不在白名单的动作必须被拒
ok, _ = apply_command({"action": "poweroff_now"})
check("白名单外的动作照样拒绝", ok, False)

# 关机前那一拉：人在最后一刻按下也来得及
ledger(run)
E._shutdown_issued = False; issued.clear()
E._before_shutdown = lambda: apply_command({"action": "skip_shutdown"})
check("关机前拉到了「别关机」：不关", E._maybe_shutdown(at(23, 0)), False)
check("并且没有发出关机命令", len(issued), 0)

# 拉不到不等于有人喊停
skipped_clear(); store.pop("modes", "skip_next_shutdown")
def boom():
    raise RuntimeError("网络不通")
E._before_shutdown = boom
E._shutdown_issued = False; issued.clear()
check("关机前那一拉失败：按原计划关机", E._maybe_shutdown(at(23, 0)), True)
E._before_shutdown = None
skipped_clear()


print("\n[countdown] 「别关机」 pressed inside the relay's own 60-second countdown")
# 2026-10-09 22:42: the order only stored "skip the next one" and Windows
# powered off at 22:43 anyway (relay.log 22:43:14 heartbeat bye).
calls = []
RC = {"/a": 0}
def fake_run(args, *a, **k):
    calls.append(list(args))
    rc = RC["/a"] if list(args)[:2] == ["shutdown", "/a"] else 0
    return __import__("subprocess").CompletedProcess(args, rc, b"", b"")
eng.subprocess = type("X", (), {"run": staticmethod(fake_run),
                                "CompletedProcess": __import__("subprocess").CompletedProcess})()
from ark_relay import shutdown as sd, errwatch    # noqa: E402
skipped_clear(); store.pop("modes", "skip_next_shutdown")
ledger(run)
E._shutdown_issued = False; calls.clear()
check("countdown: power-off issued", E._maybe_shutdown(at(23, 0)), True)
check("countdown: errwatch marked stopping", errwatch._stopping.is_set(), True)
calls.clear()
ok, msg = apply_command({"action": "skip_shutdown"})
check("countdown: order accepted", ok, True)
check("countdown: shutdown /a was run", ["shutdown", "/a"] in calls, True)
check("countdown: engine no longer going down", E._shutdown_issued, False)
check("countdown: no flag left over for tomorrow", modes.skip_armed(STATE), False)
check("countdown: this opportunity marked skipped",
      store.get("modes", "shutdown_skipped"), E._shutdown_key(at(23, 0)))
check("countdown: errwatch no longer stopping", errwatch._stopping.is_set(), False)
calls.clear()
check("countdown: next 30-second round does not power off again",
      E._maybe_shutdown(at(23, 1)), False)
check("countdown: and issued nothing", [c for c in calls if c[:2] == ["shutdown", "/s"]], [])
ledger(run, dict(run, run_id="y"))
calls.clear()
check("countdown: next queue round powers off as usual", E._maybe_shutdown(at(23, 40)), True)

print("\n[countdown] Windows says no countdown (1116): behave as before")
RC["/a"] = 1116
skipped_clear(); store.pop("modes", "skip_next_shutdown")
ok, _ = apply_command({"action": "skip_shutdown"})
check("1116: flag stored as before", (ok, modes.skip_armed(STATE)), (True, True))
store.pop("modes", "skip_next_shutdown")

print("\n[countdown] no power-off issued: shutdown /a is not even tried")
RC["/a"] = 0
E._shutdown_issued = False; calls.clear()
ok, _ = apply_command({"action": "skip_shutdown"})
check("no countdown: flag stored", (ok, modes.skip_armed(STATE)), (True, True))
check("no countdown: shutdown /a not run", ["shutdown", "/a"] in calls, False)
store.pop("modes", "skip_next_shutdown")

print("\n[countdown] cancel (off) never touches the countdown")
ledger(run, dict(run, run_id="y"), dict(run, run_id="z"))
skipped_clear()
E._shutdown_issued = False
check("cancel: power-off issued", E._maybe_shutdown(at(23, 50)), True)
calls.clear()
ok, _ = apply_command({"action": "skip_shutdown", "off": True})
check("cancel: shutdown /a not run", ["shutdown", "/a"] in calls, False)
check("cancel: still going down", E._shutdown_issued, True)

print("\n[countdown] shutdown /a refused: reported, machine still going down")
RC["/a"] = 5
ok, msg = apply_command({"action": "skip_shutdown"})
check("refused: order reported as failed", ok, False)
check("refused: still going down", E._shutdown_issued, True)
check("refused: no flag stored", modes.skip_armed(STATE), False)
E._shutdown_issued = False; sd._ISSUED[0] = None; skipped_clear()

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
