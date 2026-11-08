"""The installed relay starts programs itself; each scheduled-task launch has a name of its own
(audit 11-08 A-21; dispatch relay-opt-round4-1108 R4-02; preupdate_common._spawn_here).

The relay now runs in the logged-on user's session (app_main.py, \\ArkRelay\\main, highest
privileges), yet every picture, click and launcher start still went through PowerShell
building a scheduled task and waiting 3 s, and that task was named after the program only,
so two launches of one program within those 3 s (two threads taking pictures) replaced or
unregistered each other's task. Pinned here, with Windows faked:

* elevated on the console session: Popen, no PowerShell; out of the relay task's job
  (CREATE_BREAKAWAY_FROM_JOB), the logged-on user's environment, a console window or
  CREATE_NO_WINDOW as asked, SW_SHOWMINNOACTIVE when minimized; the hidden route writes no
  pythonw launcher;
* breakaway refused (access denied): the task route, now and for every later start;
* another start failure, or not on the console / not elevated / no environment: the task
  route, as before;
* the task route: a new task name on every launch, under the program's stem.
"""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir

from ark_relay.features.preupdate import preupdate_common as C

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(label)


class SI:
    """subprocess.STARTUPINFO (Windows only)."""

    def __init__(self):
        self.dwFlags, self.wShowWindow = 0, 0


popens, tasks = [], []
answer = [None]          # an OSError to raise from Popen, or None


def fake_popen(argv, **kw):
    popens.append((list(argv), kw))
    if answer[0] is not None:
        raise answer[0]
    return SimpleNamespace(pid=4242)


def fake_task(exe, cwd, args=(), **kw):
    tasks.append((Path(exe).name, tuple(args)))
    return True


here = [True]
saved = (subprocess.Popen, getattr(subprocess, "STARTUPINFO", None), C._here_in_console, C._logon_env,
         C._spawn_via_task, C._direct_refused[0])
subprocess.Popen, subprocess.STARTUPINFO = fake_popen, SI
C._here_in_console = lambda: here[0]
C._logon_env = lambda: {"USERPROFILE": "C:\\Users\\Administrator", "PATH": "C:\\Windows"}
C._spawn_via_task = fake_task
EXE = Path("D:/ark/okww/ok-ww.exe")
work = tmpdir()
try:
    print("[中继就在桌面会话里：直接启动，不走 PowerShell 计划任务]")
    check("启动成功", C._spawn_interactive(EXE, work, ("-t", "1"), require_console=True, minimized=True), True)
    argv, kw = popens[-1]
    check("命令行原样", argv, [str(EXE), "-t", "1"])
    check("脱离中继计划任务的作业（中继重启不连带）", bool(kw["creationflags"] & C._CREATE_BREAKAWAY_FROM_JOB), True)
    check("带自己的控制台（和计划任务那条路一样）", bool(kw["creationflags"] & C._CREATE_NEW_CONSOLE), True)
    check("用登录用户的环境变量，不是中继的", kw["env"].get("USERPROFILE"), "C:\\Users\\Administrator")
    check("最小化、不抢前台", (kw["startupinfo"].dwFlags & C._STARTF_USESHOWWINDOW, kw["startupinfo"].wShowWindow),
          (C._STARTF_USESHOWWINDOW, C._SW_SHOWMINNOACTIVE))
    check("工作目录", kw["cwd"], str(work))
    check("没建计划任务", tasks, [])

    print("\n[无窗口那条路：CREATE_NO_WINDOW，不写 pythonw 启动器]")
    PS = Path("C:/Program Files/PowerShell/7/pwsh.exe")
    check("启动成功", C._spawn_hidden_via_task(PS, work, ("-File", "a.ps1")), True)
    argv, kw = popens[-1]
    check("没有窗口", bool(kw["creationflags"] & C._CREATE_NO_WINDOW), True)
    check("……也不另开控制台", bool(kw["creationflags"] & C._CREATE_NEW_CONSOLE), False)
    check("……照样脱离作业", bool(kw["creationflags"] & C._CREATE_BREAKAWAY_FROM_JOB), True)
    check("没写无窗口启动器", (work / C.HIDDEN_LAUNCHER_NAME).exists(), False)
    check("没建计划任务", tasks, [])

    print("\n[启动失败（不是不许脱离）：这一次走计划任务，下次照旧先直接启动]")
    answer[0] = FileNotFoundError(2, "not found")
    check("走计划任务启动成功", C._spawn_interactive(EXE, work, require_console=True), True)
    check("计划任务启动的是它", tasks[-1][0], "ok-ww.exe")
    answer[0] = None
    n = len(tasks)
    C._spawn_interactive(EXE, work, require_console=True)
    check("下一次又直接启动了", len(tasks), n)

    print("\n[作业不许脱离（拒绝访问）：这次和以后都走计划任务]")
    denied = OSError(13, "Access is denied")
    denied.winerror = C._ERROR_ACCESS_DENIED
    answer[0] = denied
    n_pop, n = len(popens), len(tasks)
    check("走计划任务启动成功", C._spawn_interactive(EXE, work, require_console=True), True)
    answer[0] = None
    C._spawn_interactive(EXE, work, require_console=True)
    check("之后不再试直接启动", (len(popens) - n_pop, len(tasks) - n), (1, 2))
    C._direct_refused[0] = False

    print("\n[不在桌面会话 / 不是管理员 / 取不到环境：照旧走计划任务]")
    here[0] = False
    n_pop = len(popens)
    C._spawn_hidden_via_task(PS, work, ())
    check("不在桌面会话：没直接启动", len(popens), n_pop)
    here[0] = True
    C._logon_env = lambda: None
    C._spawn_interactive(EXE, work, require_console=True)
    check("取不到登录用户的环境：没直接启动", len(popens), n_pop)
finally:
    (subprocess.Popen, _si, C._here_in_console, C._logon_env, C._spawn_via_task, C._direct_refused[0]) = saved
    if _si is None:
        del subprocess.STARTUPINFO
    else:
        subprocess.STARTUPINFO = _si

print("[走不了直接启动的原因：每个原因在日志里说一次（INFO），部署后看得见]")
import logging  # noqa: E402
said = []


class _Rows(logging.Handler):
    def emit(self, record):
        said.append((record.levelname, record.getMessage()))


h = _Rows()
C.log.addHandler(h)
level = C.log.level
C.log.setLevel(logging.DEBUG)
C._not_here_said[0] = ""
try:
    C._here_in_console()            # this Mac: no pywin32
    C._here_in_console()
finally:
    C.log.removeHandler(h)
    C.log.setLevel(level)
check("说了一次、是 INFO、说了原因", [(lv, "看不出中继是不是在桌面会话里" in m) for lv, m in said], [("INFO", True)])

print("\n[计划任务那条路：每次一个新任务名]")
scripts = []
real_run = subprocess.run
subprocess.run = lambda argv, **kw: scripts.append(argv[-1]) or SimpleNamespace(returncode=0, stderr=b"")
try:
    C._spawn_via_task(PS, work, ("-File", "a.ps1"))
    C._spawn_via_task(PS, work, ("-File", "a.ps1"))
    C._spawn_via_task(PS, work, (), task="ark-efstart")
finally:
    subprocess.run = real_run


def name_of(ps):
    return ps.split('Register-ScheduledTask -TaskName "', 1)[1].split('"', 1)[0]


names = [name_of(s) for s in scripts]
check("两次启动同一个程序：任务名不同", names[0] != names[1], True)
check("……都以程序名开头", all(n.startswith(C._task_name(PS.stem) + "-") for n in names[:2]), True)
check("……一个脚本里注册、启动、注销的是同一个名字", all(s.count(f'"{n}"') == 4 for s, n in zip(scripts, names, strict=True)), True)
check("指定了任务名的也加后缀", names[2].startswith("ark-efstart-") and len(names[2]) == len("ark-efstart-") + 8, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
