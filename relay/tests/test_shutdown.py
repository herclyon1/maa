"""Exercise the shutdown gate against a fake AUTO-MAS + ledger.

Covers the bug being fixed (a restart after the run leaves nobody to shut the
machine down) and the three ways the fix could itself cost a run: powering off
before the queue, mid-queue, or on a machine somebody booted afterwards to work
on.
"""
import json, os, sys, tempfile
from datetime import datetime, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
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
from ark_relay import plan                              # noqa: E402

cfg = Config()
print("queues seen by plan:", [q["name"] for q in plan.schedule(cfg.automas_dir)])

state = State(cfg.state_dir)
E = eng.Engine(cfg, source=None, state=state, notifier=Notifier(cfg))
E._scripts_running = lambda: False           # no games on this Mac
E._idle_checkpoint = lambda now=None: False  # test the normal path only

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

print("\n[the bug] relay restarted after the run finished")
ledger(run)
E._handled_any = False                    # a fresh process, as after selfupdate
E._started_at = at(22, 20)                # started after the queue
BOOT[0] = at(21, 20)                      # machine booted for this queue
check("work_is_done at 22:25", E._work_is_done(at(22, 25), E._recent_entries(at(22, 25))), True)

print("\n[regression] must NOT power off a machine booted AFTER the queue ran")
# Somebody powers the machine on at 22:20 to work on it. The 21:30 queue is
# still inside its two-hour window and its records are in the ledger, so
# without the uptime gate this reads as "everything finished, shut down".
BOOT[0] = at(22, 20)
check("booted after the queue -> hold",
      E._work_is_done(at(22, 30), E._recent_entries(at(22, 30))), False)
BOOT[0] = None
check("uptime unknown -> hold",
      E._work_is_done(at(22, 30), E._recent_entries(at(22, 30))), False)
BOOT[0] = at(21, 20)

print("\n[regression] must NOT power off before its own queue")
ledger()
check("work_is_done at 21:00 (queue still ahead)",
      E._work_is_done(at(21, 0), E._recent_entries(at(21, 0))), False)
check("work_is_done at 08:50 (nothing due at all)",
      E._work_is_done(at(8, 50), E._recent_entries(at(8, 50))), False)

print("\n[regression] must NOT power off mid-queue")
ledger()
check("due at 21:30, no records yet -> 21:40",
      E._work_is_done(at(21, 40), E._recent_entries(at(21, 40))), False)

print("\n[调试模式] 吃掉一次关机机会，而不是到期就补关")
# 用户 2026-08-31：「我开了调试模式是指把一次队列的中继关机指令跳过，
# 而不是中继一直尝试关机，要不然人类没办法使用这个电脑每次都要开调试模式。」
# 改判前：调试模式只是让每次判定返回 False，判定每 30 秒重来，到期后条件
# 没变就立刻关机——人一走开机器自己关了。
# 改判后：生效期间记下「这一次关机机会」并吃掉它；到期后只要没有新队列
# 跑完（机会标识没变）就不补关；新队列一跑完标识变了，恢复正常关机。
# 这里把真正执行关机那步挡掉，只看判定结果。
issued = []
eng.subprocess = type("X", (), {"run": staticmethod(lambda *a, **k: issued.append(a))})()
ledger(run)
E._handled_any = True
E._started_at = at(21, 20)
BOOT[0] = at(21, 20)
E.state.report_sent = lambda d: True          # 日报已发，不在那道门上卡住
E._last_round_manual = lambda now, entries: False
E._unfinished_queues = lambda now, entries: []

# _maybe_shutdown 查调试模式时用的是**真实**当前时间（生产里 now 就是真实
# 时间，这个参数只为其余判定服务），所以到期点要按真实时钟写。
dbg = STATE / "debug-until.txt"
skipped = STATE / "shutdown-skipped.txt"
real = datetime.now(tz=SERVER_TZ)
skipped.unlink(missing_ok=True)

dbg.write_text(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}", encoding="utf-8")
E._shutdown_issued = False; issued.clear()
check("调试模式生效中：不关机", E._maybe_shutdown(at(23, 0)), False)
check("生效中没有发出关机命令", len(issued), 0)
check("并且把这一次机会记下来了",
      skipped.read_text(encoding="utf-8").strip(), "2026-08-21:1")

dbg.write_text(f"{real - timedelta(hours=1):%Y-%m-%d %H:%M}", encoding="utf-8")
E._shutdown_issued = False; issued.clear()
check("到期后没有新队列跑完：仍然不关机（人可能正在用）",
      E._maybe_shutdown(at(23, 30)), False)
check("到期后也没有发出关机命令", len(issued), 0)

# 早班又跑了一趟，流水多一条 —— 这是一次新的关机机会
ledger(run, dict(run, run_id="y"))
E._shutdown_issued = False; issued.clear()
check("下一趟队列跑完：恢复正常关机", E._maybe_shutdown(at(23, 40)), True)
check("这次确实发出了关机命令", len(issued), 1)

dbg.unlink(missing_ok=True); skipped.unlink(missing_ok=True)
ledger(run)
E._shutdown_issued = False; issued.clear()
check("没开过调试模式时，本来就该关机", E._maybe_shutdown(at(23, 0)), True)

print("\n[人工开关] 桌面那个 .bat：只跳过下一次，用完即失效")
# 用户 2026-08-31：「你给一个人类好去调这个模式的方法，独立于你的。」
# 它不带到期时间，就是把**下一次真正要执行的关机**吃掉一次。
flag = STATE / "skip-next-shutdown.flag"
dbg.unlink(missing_ok=True); skipped.unlink(missing_ok=True)
ledger(run)
flag.write_text("skip", encoding="utf-8")
E._shutdown_issued = False; issued.clear()
check("按下之后：这一次不关机", E._maybe_shutdown(at(23, 0)), False)
check("没有发出关机命令", len(issued), 0)
check("标记被用掉了（用完即失效）", flag.exists(), False)

E._shutdown_issued = False; issued.clear()
check("同一次机会不会因为标记没了就补关",
      E._maybe_shutdown(at(23, 10)), False)

ledger(run, dict(run, run_id="y"))
E._shutdown_issued = False; issued.clear()
check("下一趟队列跑完：正常关机（不用再按一次才关）",
      E._maybe_shutdown(at(23, 40)), True)
skipped.unlink(missing_ok=True)

print("\n[手动关调试] 明确关掉要恢复正常，自然到期不恢复")
from ark_relay import modes                                 # noqa: E402
# 2026-08-31：我维护完手动关掉调试模式，机器却因为「这次已跳过」的标记
# 还在，准备空开一整夜到早班跑完。明确说「关掉」＝维护结束，标记要一起清。
dbg.write_text(f"{real + timedelta(hours=1):%Y-%m-%d %H:%M}", encoding="utf-8")
skipped.unlink(missing_ok=True); flag.unlink(missing_ok=True)
ledger(run)
E._shutdown_issued = False; issued.clear()
E._maybe_shutdown(at(23, 0))                       # 生效中，吃掉一次
check("先确认标记确实写下了", skipped.exists(), True)
modes.set_debug(STATE, off=True)                   # 人明确关掉
check("手动关掉后标记被清掉", skipped.exists(), False)
E._shutdown_issued = False; issued.clear()
check("于是恢复正常关机", E._maybe_shutdown(at(23, 5)), True)
skipped.unlink(missing_ok=True); dbg.unlink(missing_ok=True)

print("\n[手机开关] 待办指令 skip_shutdown：手机上改仓库里那个文件")
# 用户 2026-08-31：「我要的是手机上面操作」。中继本来就有「公开仓库放一个
# 文件、手机网页编辑」的收信通道，这里把开关接进那条通道。
os.environ["ARK_STATE_DIR"] = str(STATE)
from ark_relay.commands import apply_command, ALLOWED       # noqa: E402

check("动作在白名单里", "skip_shutdown" in ALLOWED, True)
skipped.unlink(missing_ok=True); flag.unlink(missing_ok=True)

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
skipped.unlink(missing_ok=True); flag.unlink(missing_ok=True)
def boom():
    raise RuntimeError("网络不通")
E._before_shutdown = boom
E._shutdown_issued = False; issued.clear()
check("关机前那一拉失败：按原计划关机", E._maybe_shutdown(at(23, 0)), True)
E._before_shutdown = None
skipped.unlink(missing_ok=True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
