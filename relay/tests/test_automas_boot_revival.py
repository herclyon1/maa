"""The boot-time revival must wait for a shell that is already starting, kill the
runtime as well when it does restart, and the keeper must not go blind without wmic.

Real sequence, 2026-09-17 21:20 (first evening boot after AUTO-MAS v5.5.0-beta.6):
21:20:28 the logon task starts AUTO-MAS.exe, which begins its bootstrap
(repo sync, managed Python, locked dependencies); 21:20:39 the relay finds no
API, runs `taskkill /IM AUTO-MAS.exe` at once, `schtasks /run`; the bootstrap
child `auto-mas-runtime.exe` (pid 19116) survives and keeps the environment
lock; 21:20:45 the new shell fails with MUTATION_IN_PROGRESS and parks on
「等待用户处理」; 21:21:28 the relay gives up after 45 s with one ERROR line and
no alarm; the keeper (wmic gone since 25H2) reads "cannot tell" as alive and
never tries again; 21:30 the queue does not run; 21:55 「该跑没跑」.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom",
             "win32com", "win32com.client"):
    sys.modules.setdefault(name, _Stub(name))

import boot_stages  # noqa: E402
import service  # noqa: E402
from ark_relay import commands, texts  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


boot_stages.time.sleep = lambda s: None
clock = {"t": 0.0}
boot_stages.time.monotonic = lambda: clock["t"]


def _tick(seconds):
    """Every sleep(3) inside _wait_for_api advances the fake clock."""
    def sleep(s):
        clock["t"] += s
    boot_stages.time.sleep = sleep


_tick(3)
# The win32 stubs above answer every call with a truthy object, which would make
# errwatch.system_shutting_down() read "going down"; the stop signal is driven
# explicitly by the cases below.
boot_stages._stop_requested = lambda: False
revived = []
boot_stages._revive_automas = lambda: revived.append(clock["t"])


def _api(up_after):
    """mas_up() answers True once the fake clock passes `up_after` seconds."""
    return lambda: clock["t"] >= up_after


print("[窗口已在、接口还没开：等它，不杀]")
clock["t"] = 0; revived.clear()
boot_stages.shell_running = lambda: True
commands.mas_up = _api(30)
check("等到接口开了就返回 True", boot_stages.ensure_automas(timeout=120, grace=150), True)
check("没有杀过一次", revived, [])
check("等了约 30 秒", 27 <= clock["t"] <= 33)

print("\n[窗口在但宽限期内接口一直不开：宽限期满才杀、再等 timeout]")
clock["t"] = 0; revived.clear()
commands.mas_up = _api(10**9)
check("最终返回 False", boot_stages.ensure_automas(timeout=120, grace=150), False)
check("杀了一次", len(revived), 1)
check("是在宽限期（150 秒）之后才杀的", revived[0] >= 150)
check("杀完又等了 timeout", clock["t"] >= 150 + 120)

print("\n[窗口根本不在：立刻拉起]")
clock["t"] = 0; revived.clear()
boot_stages.shell_running = lambda: False
commands.mas_up = _api(20)
check("拉起后接口开了返回 True", boot_stages.ensure_automas(timeout=120, grace=150), True)
check("立刻杀/拉起，没有先等宽限期", revived == [0.0])

print("\n[等待中收到停止信号：立刻返回，不杀不拉，不发「AUTO-MAS 没起来」]")
# 2026-09-18 23:10: the self-update restarted the service inside this 150 s wait;
# SvcStop waited 15 s and the hard guard force-exited the process.
clock["t"] = 0; revived.clear()
boot_stages.shell_running = lambda: True
commands.mas_up = _api(10**9)
boot_stages._stop_requested = lambda: clock["t"] >= 9
check("停止一到就返回 False", boot_stages.ensure_automas(timeout=120, grace=150), False)
check("在停止后一次轮询内退出（不到 15 秒）", clock["t"] < 15, True)
check("没有杀过 AUTO-MAS", revived, [])
clock["t"] = 0; revived.clear()
boot_stages.shell_running = lambda: False
boot_stages._stop_requested = lambda: True
check("窗口不在但正在停止：也不拉", boot_stages.ensure_automas(timeout=120, grace=150), False)
check("确实没拉", revived, [])
boot_stages._stop_requested = lambda: False

print("\n[接口本来就通：什么都不做]")
clock["t"] = 0; revived.clear()
commands.mas_up = lambda: True
check("直接 True", boot_stages.ensure_automas(), True)
check("没动手", revived, [])

print("\n[_revive_automas 连 auto-mas-runtime.exe 一起杀]")
ran = []
real_revive = boot_stages.__dict__["_revive_automas"]
import importlib  # noqa: E402
importlib.reload(boot_stages)
boot_stages.time.sleep = lambda s: None
boot_stages.subprocess.run = lambda cmd, **kw: ran.append(" ".join(cmd))
boot_stages._revive_automas()
check("先杀窗口", any("taskkill /IM AUTO-MAS.exe /F" in c for c in ran))
check("再杀 runtime（不杀它，新窗口会卡在 MUTATION_IN_PROGRESS）",
      any("taskkill /IM auto-mas-runtime.exe /F" in c for c in ran))
check("然后 /end 再 /run", ran[-2].startswith("schtasks /end") and ran[-1].startswith("schtasks /run"))
check("杀窗口在杀 runtime 之前",
      [i for i, c in enumerate(ran) if "AUTO-MAS.exe" in c][0]
      < [i for i, c in enumerate(ran) if "auto-mas-runtime.exe" in c][0])

print("\n[开机拉不起来要立刻报警（群）]")
check("文案在 texts 里且是人话", texts.plain(texts.automas_boot_down_body()), [])
from ark_relay.notify import route_of  # noqa: E402
check("走群机器人", route_of(texts.AUTOMAS_DOWN, alert=True), "group")

print("\n[没有 wmic 的机器上 keeper 不许装瞎]")
service._python_processes = lambda: None          # the query itself failed
commands.mas_up = lambda: False
check("进程表读不到、接口不通 → 不在（以前是「假定活着」）", service._automas_running(), False)
commands.mas_up = lambda: True
check("进程表读不到、接口通 → 在", service._automas_running(), True)
service._python_processes = lambda: [(4132, r'"C:\Program Files\Python314\python.exe" C:\ProgramData\x.py')]
commands.mas_up = lambda: True
check("有 python 但不是 main.py → 不在（接口不算，句柄要挂在进程上）",
      service._automas_running(), False)
service._python_processes = lambda: [(21932, r'"D:\ark\automas\runtime\environment\python\python.exe" D:\ark\automas\repo\main.py')]
check("有 main.py → 在", service._automas_running(), True)

print("\n[AUTO-MAS 的收尾记录不当成一趟运行核对]")
from ark_relay import handle  # noqa: E402
check("识别文本来自真实记录", handle.MAAEND_NOTHING_TO_RUN in handle.MAAEND_NOTHING_TO_RUN_LOG)
import tempfile  # noqa: E402
from datetime import datetime  # noqa: E402
from ark_relay.config import RunRecord, SERVER_TZ  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    lp = Path(td) / "MaaEnd-06-32-49.log"
    lp.write_text("MaaEnd 没有可执行任务，请检查任务配置, 无日志记录", encoding="utf-8")
    rec = RunRecord(run_id="2026-09-17/endfield/MaaEnd-06-32-49", script="MaaEnd", user="endfield",
                    started=datetime(2026, 9, 17, 10, 32, 49, tzinfo=SERVER_TZ),
                    finished=datetime(2026, 9, 17, 10, 32, 49, tzinfo=SERVER_TZ), ok=True,
                    raw={"maaend_result": "[自动采集] MaaEnd 没有可执行任务，请检查任务配置"}, log_path=lp)
    eng = types.SimpleNamespace(cfg=types.SimpleNamespace(maaend_dir=td, automas_dir=td, maa_dir=td))
    check("收尾记录 → 不报「没干完」", handle._verify_outcome(eng, rec), None)

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("all checks passed")
