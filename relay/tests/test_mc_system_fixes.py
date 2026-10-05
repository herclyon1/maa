"""What writing the machine checks of the relay's machinery found broken, fixed (each red on the old code).

1. service.py: SvcStop pushes the last state on the SCM's thread after setting the
   stop event; the main thread came out of the loop at once and went on to
   os._exit, so the 「停止前」 push (5-20 s) was cut off. SvcDoRun now waits for it
   (STOP_PUSH_WAIT_S). SvcStop also says which control stopped it, so a Windows
   shutdown reaching SvcShutdown shows in relay.log (machine check #11).
2. service.py: the WMI listener's diag line names the case it fits (H1 the WMI
   service restarted / H2 a provider host is gone / H3 neither), as the
   _wmi_hosts docstring defines them (machine check #59).
3. preupdate_maaend.py: the settings were written with a MaaEnd that was already
   open, which saves its own copy over them (docs/BACKLOG.md, 2026-09-30 audit).
   It is closed first, and confirmed gone (machine check #17).
4. maaend_watchdog.py: a kill taskkill called a success is looked at again; still
   in the process list is said as a WARNING (machine check #31).
5. desktop.py: the agent says which whole OCR line click_text hit (machine check #60).
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f": {got!r} != {want!r}"))
    if not ok:
        fails.append(label)


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


class ServiceFramework:
    def __init__(self, args):
        self.args = args

    def ReportServiceStatus(self, status):  # noqa: N802 - pywin32's name
        pass


w32su = _Stub("win32serviceutil")
w32su.ServiceFramework = ServiceFramework
sys.modules["win32serviceutil"] = w32su
for name in ("win32service", "win32event", "win32api", "win32con", "win32file", "servicemanager",
             "win32process", "pythoncom"):
    sys.modules.setdefault(name, _Stub(name))

cwd = os.getcwd()
import service  # noqa: E402  (it changes the working directory to relay/)
os.chdir(cwd)


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.got = []

    def emit(self, r):
        self.got.append((r.levelno, r.getMessage()))


print("[1. Windows 关机：SvcShutdown → SvcStop 说是关机；主线程等停止前那份状态推完再结束进程]")
svc = service.ArkRelayService(["ark-relay"])
events = []


def slow_push(why):
    time.sleep(0.4)
    events.append(("pushed", why))
    return True


svc._push_state = slow_push
svc.main = lambda: None
real_exit = os._exit
os._exit = lambda code: events.append(("exit", code))
h = Lines()
logging.getLogger("ark.service").addHandler(h)
logging.getLogger("ark.service").setLevel(logging.INFO)
try:
    t = threading.Thread(target=svc.SvcShutdown)
    t.start()
    time.sleep(0.1)          # SvcStop is inside its push, as on the machine
    svc.SvcDoRun()
    t.join(2)
finally:
    os._exit = real_exit
    logging.getLogger("ark.service").removeHandler(h)
check("停止前那份推完了才结束进程", [e[0] for e in events], ["pushed", "exit"])
check("SvcStop 说了是 Windows 关机", [m for _, m in h.got if m.startswith("收到停止通知")], ["收到停止通知（Windows 关机）"])

print("\n[2. WMI 订阅断了：diag 行写明是哪种情况]")
watch = service._ProcessWatch(object(), {"ok": True}, logging.getLogger("ark.service"), lambda: None)
watch.hosts = "winmgmt pid 1234; WmiPrvSE pids 5,6"
real_hosts = service._wmi_hosts
try:
    for now, want in (("winmgmt pid 4321; WmiPrvSE pids 5,6", "hypothesis: H1 WMI service restarted (winmgmt pid 1234 -> 4321)"),
                      ("winmgmt pid 1234; WmiPrvSE pids 6", "hypothesis: H2 WMI provider host gone (WmiPrvSE pid 5)"),
                      ("winmgmt pid 1234; WmiPrvSE pids 5,6,9", "hypothesis: H3 WMI service and provider hosts unchanged"),
                      ("winmgmt pid ?; WmiPrvSE pids 5,6", "hypothesis: unknown (WMI hosts unreadable)")):
        service._wmi_hosts = lambda now=now: now
        diag = watch._diag(None, "hresult 0x80020009, scode 0x800706BE", time.monotonic())
        check(want[12:30], diag.endswith(want), True)
finally:
    service._wmi_hosts = real_hosts

print("\n[3. 预更新：终末地程序本来就开着 → 先关掉、确认没了，再改它的设置]")
from ark_relay import preupdate_maaend as pm  # noqa: E402
md = tmpdir()
(md / "MaaEnd.exe").write_text("", encoding="utf-8")
(md / "config").mkdir()
(md / "config" / "mxu-MaaEnd.json").write_text(json.dumps({"settings": {"autoStartInstanceId": "inst-1"}}),
                                               encoding="utf-8")
order = []
listing = [b'"MaaEnd.exe","4321","Console","1","120,000 K"\r\n', "INFO: 没有运行的带有指定标准的任务。\r\n".encode("gbk")]


def fake_run(args, **kw):
    if args[0] == "tasklist":
        order.append("tasklist")
        return types.SimpleNamespace(returncode=0, stdout=listing.pop(0) if listing else b"", stderr=b"")
    order.append(" ".join(args[:2]))
    return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


real = pm.subprocess, pm._maaend_autostart_instance, pm._spawn_interactive
pm.subprocess = types.SimpleNamespace(run=fake_run, SubprocessError=subprocess.SubprocessError,
                                      TimeoutExpired=subprocess.TimeoutExpired)
pm._maaend_autostart_instance = lambda d, v: (order.append(f"write:{v!r}"), "inst-1")[1]
pm._spawn_interactive = lambda *a, **k: False
probs = []
try:
    pm.run(md, budget_s=1, problems=probs, sleep=lambda s: None)
finally:
    pm.subprocess, pm._maaend_autostart_instance, pm._spawn_interactive = real
first_write = order.index("write:''") if "write:''" in order else -1
check("改设置之前先结束了开着的 MaaEnd", "taskkill /IM" in order[:max(first_write, 0)], True)
check("关完又看了一眼才改", order[:4], ["tasklist", "taskkill /IM", "tasklist", "write:''"])

print("\n[4. 看门狗：结束命令说成功了，下一眼 MaaEnd 还在 → 说出来（WARNING）]")
from ark_relay import maaend_watchdog as wd  # noqa: E402
debug = tmpdir() / "debug"
debug.mkdir()
(debug / "go-service.stderr.log").write_text("", encoding="utf-8")
clock = [1000.0]
sent = []
dog = wd.Watchdog(types.SimpleNamespace(send=lambda t, b="", **k: sent.append(t) or []), debug,
                  clock=lambda: clock[0], snapshot=lambda: {"tasks": [{"task_info": [{"name": "MaaEnd", "status": "运行"}]}]},
                  processes=lambda: [("MaaEnd.exe", 30000)], kill=lambda pid, image: (True, ""),
                  plugin_paths=lambda: {}, active=True)
h = Lines()
logging.getLogger("ark.maaend_watchdog").addHandler(h)
try:
    dog.tick(1, "")
    (debug / "go-service.stderr.log").write_text("Exception 0xc0000005 0x0 0x0 0x0\n", encoding="utf-8")
    clock[0] += 31
    dog.tick(2, "")
    clock[0] += 31
    dog.tick(3, "")
finally:
    logging.getLogger("ark.maaend_watchdog").removeHandler(h)
check("结束过一次", len(sent) >= 1, True)
check("说了它还在", [lvl for lvl, m in h.got if "命令说成功了" in m and "还在" in m], [logging.WARNING])

print("\n[5. 桌面助手：click_text 点之前说点的是哪一整行]")
from ark_relay import desktop as dk  # noqa: E402
check("脚本里有那一行", "[void]$log.Add(\"click_text: 点了「$($hit.text)」\")" in dk.AGENT_PS, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
