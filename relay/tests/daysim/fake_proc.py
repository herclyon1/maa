"""Day simulator: the Windows world behind `subprocess`, and the process table it reads.

Every `subprocess.run/Popen/call/check_call/check_output` (and `os.system/popen`) the
relay makes is answered here from a WinState - the Windows side of the World - and
never reaches a real program. Routed by argv[0]:

    tasklist   rows from the process table (table or CSV, /NH, /FI IMAGENAME|PID eq)
    taskkill   ends table processes (/IM, /PID, /FI, /T); exit codes as on the machine
    schtasks   /create /delete /run /end /query against the task table; /run and /end
               call WinState hooks, so whether a program starts is the World's decision
    sc         `sc query NAME` from the service table
    wevtutil   `qe System /q:XPATH /f:xml` from the System log the World keeps
    pwsh       (PowerShell 7 only; 5.1 is unrouted, the repo forbids it) the closed set of
               PowerShell pipelines the relay sends (Get-CimInstance
               Win32_Process ... | Where/Select/ConvertTo-Json/Stop-Process/-f format)
               and the scheduled-task launch block (preupdate_common._spawn_via_task)
    shutdown   /s starts a countdown (engine._power_off:922 asks for /t 60), /a aborts it;
               both are outputs ("power"), and the countdown's end flips WinState.power

Anything else is unrouted: it is written to the scheduler's "sim_errors" output and
SimAbort (a BaseException, so the relay's `except Exception` cannot swallow it) is
raised. On a Mac an unrouted `shutdown /s` would be macOS's own shutdown.

Scheduler use (W1's interface, design section 2): `now()`, `at(t, fn, tag)`,
`out(kind, **fields)`. `out` kinds are the outputs.json keys: "power", "procs",
"sim_errors"; every record carries `t` as ISO 8601 with +08:00.

Text the real programs print is Chinese (the machine runs a Chinese Windows) and is
encoded as GBK, the console code page there; PowerShell 7 output is UTF-8.
"""
from __future__ import annotations

import fnmatch
import io
import json
import ntpath
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))
STILL_ACTIVE = 259           # GetExitCodeProcess while a process runs
EXIT_KILLED = 1              # the exit code taskkill /F leaves behind
SM_SHUTTINGDOWN = 0x2000     # GetSystemMetrics index (errwatch.SM_SHUTTINGDOWN)


class SimAbort(BaseException):
    """The relay did something the simulated world has no answer for: the day stops.

    BaseException on purpose: wmi_diag._wmi_scm_events and procwatch.cycle catch
    Exception, which would turn a gap in the fakes into a quiet wrong answer."""


def stamp(t: float) -> str:
    """Sim seconds as the ISO 8601 Beijing time every output record carries."""
    return datetime.fromtimestamp(t, BEIJING).isoformat(timespec="seconds")


def sim_error(sched, what: str, detail: str):
    """Record a sim error on the scheduler and return the SimAbort to raise."""
    sched.out("sim_errors", t=stamp(sched.now()), what=what, detail=detail)
    return SimAbort(f"{what}: {detail}")


# ---------------------------------------------------------------- process table

@dataclass
class Proc:
    pid: int
    image: str                   # e.g. "python.exe"
    cmdline: str = ""
    exe: str = ""                # ExecutablePath
    session: int = 1             # 0 = Services, 1 = Console
    mem_k: int = 10_000
    parent: int = 0
    started: float = 0.0
    ended: "float | None" = None
    exit_code: "int | None" = None
    protected: bool = False      # taskkill from session 0 is refused (the game's anti-cheat)

    @property
    def alive(self) -> bool:
        return self.ended is None


class ProcTable:
    """The machine's processes. The World starts and ends them from the record; the
    relay ends them through taskkill / Stop-Process. Listeners hear every start and
    exit (fake_win: WMI start traces, process handles)."""

    def __init__(self, first_pid: int = 4000):
        self._procs: dict[int, Proc] = {}
        self._next = first_pid
        self._lock = threading.RLock()
        self.on_start: list = []     # fn(proc)
        self.on_exit: list = []      # fn(proc)

    def start(self, image: str, cmdline: str = "", *, exe: str = "", session: int = 1,
              pid: "int | None" = None, parent: int = 0, t: float = 0.0,
              protected: bool = False, mem_k: int = 10_000) -> Proc:
        with self._lock:
            if pid is None:
                while self._next in self._procs:
                    self._next += 4
                pid = self._next
                self._next += 4
            p = Proc(pid, image, cmdline or image, exe, session, mem_k, parent, t,
                     protected=protected)
            self._procs[pid] = p
        for fn in list(self.on_start):
            fn(p)
        return p

    def end(self, pid: int, code: int = 0, t: float = 0.0) -> bool:
        with self._lock:
            p = self._procs.get(pid)
            if p is None or not p.alive:
                return False
            p.ended, p.exit_code = t, code
        for fn in list(self.on_exit):
            fn(p)
        return True

    def get(self, pid: int) -> "Proc | None":
        return self._procs.get(pid)

    def alive(self) -> list[Proc]:
        with self._lock:
            return sorted((p for p in self._procs.values() if p.alive), key=lambda p: p.pid)

    def named(self, image: str) -> list[Proc]:
        pat = image.lower()
        return [p for p in self.alive() if fnmatch.fnmatchcase(p.image.lower(), pat)]

    def children(self, pid: int) -> list[Proc]:
        return [p for p in self.alive() if p.parent == pid]


# ---------------------------------------------------------------- System log

_EVT_NS = "http://schemas.microsoft.com/win/2004/08/events/event"


@dataclass
class SysEvent:
    t: float
    event_id: int
    provider: str
    data: dict = field(default_factory=dict)    # EventData Name -> text
    binary_hex: str = ""

    def xml(self) -> str:
        when = datetime.fromtimestamp(self.t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z"
        data = "".join(f"<Data Name='{_xml_esc(k)}'>{_xml_esc(v)}</Data>" for k, v in self.data.items())
        binary = f"<Binary>{self.binary_hex}</Binary>" if self.binary_hex else ""
        return (f"<Event xmlns='{_EVT_NS}'><System><Provider Name='{_xml_esc(self.provider)}'/>"
                f"<EventID>{self.event_id}</EventID><TimeCreated SystemTime='{when}'/>"
                f"<Channel>System</Channel><Computer>INS</Computer></System>"
                f"<EventData>{data}{binary}</EventData></Event>")


def _xml_esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("'", "&apos;").replace('"', "&quot;"))


_XP_IDS = re.compile(r"\(?\s*EventID\s*=\s*\d+(?:\s+or\s+EventID\s*=\s*\d+)*\s*\)?")
_XP_PROVIDER = re.compile(r"Provider\[@Name='([^']*)'\]")
_XP_WINDOW = re.compile(r"TimeCreated\[timediff\(@SystemTime\)\s*<=\s*(\d+)\]")


def match_xpath(xpath: str) -> "tuple[set[int] | None, str | None, int | None]":
    """(event ids, provider, window ms) of the System-log XPath shapes the relay sends;
    ValueError for anything else (the fake would otherwise answer a query it ignored)."""
    body = xpath.strip()
    if not (body.startswith("*[System[") and body.endswith("]]")):
        raise ValueError(f"XPath not modelled: {xpath}")
    body = body[len("*[System["):-2]
    ids = provider = window = None
    if m := _XP_IDS.search(body):
        ids = {int(x) for x in re.findall(r"\d+", m.group(0))}
        body = body.replace(m.group(0), " ", 1)
    if m := _XP_PROVIDER.search(body):
        provider = m.group(1)
        body = body.replace(m.group(0), " ", 1)
    if m := _XP_WINDOW.search(body):
        window = int(m.group(1))
        body = body.replace(m.group(0), " ", 1)
    if re.sub(r"\band\b", " ", body).strip():
        raise ValueError(f"XPath not modelled: {xpath}")
    return ids, provider, window


# ---------------------------------------------------------------- the Windows side of the World

class WinState:
    """What Windows knows that the relay asks about: processes, power, scheduled tasks,
    services, the System log. The World (W5) owns one and drives it from the record;
    fake_proc and fake_win read and change it.

    Hooks the World may set (None = the default stated):
      on_task_run(name, task)       schtasks /run of an existing task (default: marks it running)
      on_task_end(name, task)       schtasks /end (default: marks it not running)
      on_spawn(exe, args, cwd, task) PowerShell scheduled-task launch (default: a table process)
      on_power_off(t)               the shutdown countdown ran out (default: nothing more)
    """

    def __init__(self, sched, *, power_on: float, procs: "ProcTable | None" = None):
        self.sched = sched
        self.procs = procs or ProcTable()
        self.power_on = power_on          # GetTickCount64 = now - power_on
        self.power = "on"                 # on | countdown | going_down
        self.shutdown_at: "float | None" = None
        self._gen = 0                     # bumps on every /s and /a; a stale countdown does nothing
        self.tasks: dict[str, dict] = {}  # key: task name, no leading backslash, lowercase
        self.services: dict[str, dict] = {}   # key: service name lowercase
        self.sys_events: list[SysEvent] = []
        self.wmi_ok = True                # GetObject("winmgmts:...") succeeds
        self.on_task_run = None
        self.on_task_end = None
        self.on_spawn = None
        self.on_power_off = None

    # -- set-up helpers the World uses
    def add_task(self, name: str, tr: str = "", running: bool = False) -> dict:
        task = {"name": "\\" + name.lstrip("\\"), "tr": tr, "running": running}
        self.tasks[_task_key(name)] = task
        return task

    def add_service(self, name: str, state: str = "RUNNING", pid: int = 0) -> dict:
        svc = {"name": name, "state": state, "pid": pid}
        self.services[name.lower()] = svc
        return svc

    def add_baseline(self, t: float) -> None:
        """The processes, services and tasks every boot of the game machine has, so the
        relay's own probes (winmgmt pid, WmiPrvSE, AUTO-MAS task) find what they find there."""
        pr = self.procs
        pr.start("System", "", session=0, pid=4, t=t)
        host = pr.start("svchost.exe", r"C:\WINDOWS\system32\svchost.exe -k netsvcs -p -s Winmgmt",
                        exe=r"C:\WINDOWS\system32\svchost.exe", session=0, t=t)
        pr.start("WmiPrvSE.exe", r"C:\WINDOWS\system32\wbem\wmiprvse.exe",
                 exe=r"C:\WINDOWS\system32\wbem\wmiprvse.exe", session=0, t=t)
        pr.start("explorer.exe", r"C:\WINDOWS\Explorer.EXE", exe=r"C:\WINDOWS\explorer.exe", t=t)
        self.add_service("winmgmt", "RUNNING", host.pid)
        self.add_task("AUTO-MAS_AutoStart")
        self.add_task(r"ArkRelay\main", running=True)

    def log_event(self, t: float, event_id: int, provider: str, data: "dict | None" = None,
                  binary_hex: str = "") -> SysEvent:
        ev = SysEvent(t, event_id, provider, dict(data or {}), binary_hex)
        self.sys_events.append(ev)
        self.sys_events.sort(key=lambda e: e.t)
        return ev

    def query_events(self, xpath: str, now: float, newest_first: bool) -> list[SysEvent]:
        ids, provider, window = match_xpath(xpath)
        out = [e for e in self.sys_events
               if e.t <= now
               and (ids is None or e.event_id in ids)
               and (provider is None or e.provider == provider)
               and (window is None or (now - e.t) * 1000 <= window)]
        return out[::-1] if newest_first else out

    @property
    def shutting_down(self) -> bool:
        """GetSystemMetrics(SM_SHUTTINGDOWN): only once the power-off has begun, not in the countdown."""
        return self.power == "going_down"

    # -- power (shutdown.exe)
    def begin_countdown(self, seconds: int) -> None:
        self._gen += 1
        gen = self._gen
        self.power = "countdown"
        self.shutdown_at = self.sched.now() + seconds
        self.sched.at(self.shutdown_at, lambda: self._countdown_done(gen), "shutdown-countdown")

    def abort_countdown(self) -> None:
        self._gen += 1
        self.power, self.shutdown_at = "on", None

    def _countdown_done(self, gen: int) -> None:
        if gen != self._gen or self.power != "countdown":
            return
        self.power = "going_down"
        if self.on_power_off is not None:
            self.on_power_off(self.sched.now())


def _task_key(name: str) -> str:
    return name.strip().lstrip("\\").lower()


# ---------------------------------------------------------------- text the real programs print

def _gbk(s: str) -> bytes:
    return s.encode("gbk", "replace")


TL_NONE = "信息: 没有运行的任务匹配指定标准。\r\n"
TK_NONE_FI = "信息: 没有运行的带有指定标准的任务。\r\n"
TK_NOT_FOUND = 128
NOT_FOUND_FILE = "错误: 系统找不到指定的文件。\r\n"
SHUTDOWN_PENDING = 1190      # ERROR_SHUTDOWN_IS_SCHEDULED
NO_SHUTDOWN = 1116           # ERROR_NO_SHUTDOWN_IN_PROGRESS
SC_NO_SERVICE = 1060         # ERROR_SERVICE_DOES_NOT_EXIST


def _split_cmdline(s: str) -> list[str]:
    """A command string the Windows way, enough for the relay's own strings."""
    return [a.replace('"', "") for a in re.findall(r'(?:"[^"]*"|[^\s"])+', s)]


class _Unrouted(Exception):
    """Inside the router: this argv has no model. Turned into a sim error by _answer."""


@dataclass
class _Answer:
    rc: int = 0
    out: bytes = b""
    err: bytes = b""


# ---------------------------------------------------------------- the router

class ProcRouter:
    """Replaces subprocess's entry points with answers from a WinState."""

    def __init__(self, sched, win: WinState):
        self.sched, self.win = sched, win
        self.calls: list[dict] = []        # every command: t, argv, rc
        self._saved: dict = {}

    # -- installing
    def install(self) -> "ProcRouter":
        for name, fn in (("run", self.run), ("Popen", self._popen_class()),
                         ("call", self.call), ("check_call", self.check_call),
                         ("check_output", self.check_output),
                         ("getoutput", self._unrouted_shell), ("getstatusoutput", self._unrouted_shell)):
            self._saved[("subprocess", name)] = getattr(subprocess, name)
            setattr(subprocess, name, fn)
        for name, val in (("CREATE_NO_WINDOW", 0x08000000), ("CREATE_NEW_PROCESS_GROUP", 0x200),
                          ("DETACHED_PROCESS", 0x8), ("CREATE_NEW_CONSOLE", 0x10),
                          ("STARTF_USESHOWWINDOW", 1), ("SW_HIDE", 0)):
            if not hasattr(subprocess, name):
                self._saved[("subprocess", name)] = None
                setattr(subprocess, name, val)
        for name in ("system", "popen"):
            self._saved[("os", name)] = getattr(os, name)
            setattr(os, name, self._unrouted_shell)
        return self

    def uninstall(self) -> None:
        for (mod, name), val in self._saved.items():
            target = subprocess if mod == "subprocess" else os
            if val is None:
                delattr(target, name)
            else:
                setattr(target, name, val)
        self._saved.clear()

    def _unrouted_shell(self, cmd, *a, **k):
        raise sim_error(self.sched, "unrouted command", str(cmd))

    # -- subprocess API
    def run(self, args, *a, input=None, capture_output=False, timeout=None, check=False, **kw):
        ans = self._answer(args)
        if capture_output:
            kw["stdout"] = kw["stderr"] = subprocess.PIPE
        out, err = self._shape(ans, kw)
        if check and ans.rc:
            raise subprocess.CalledProcessError(ans.rc, args, out, err)
        return subprocess.CompletedProcess(args, ans.rc, out, err)

    def call(self, args, *a, **kw) -> int:
        return self._answer(args).rc

    def check_call(self, args, *a, **kw) -> int:
        rc = self._answer(args).rc
        if rc:
            raise subprocess.CalledProcessError(rc, args)
        return 0

    def check_output(self, args, *a, **kw):
        kw.pop("stdout", None)
        r = self.run(args, stdout=subprocess.PIPE, **kw)
        if r.returncode:
            raise subprocess.CalledProcessError(r.returncode, args, r.stdout, r.stderr)
        return r.stdout

    def _popen_class(self):
        router = self

        class FakePopen:
            """subprocess.Popen answered at construction: nothing is started."""

            def __init__(self, args, *a, **kw):
                self.args = args
                self._ans = router._answer(args)
                self.returncode = self._ans.rc
                self.pid = 0
                self._out, self._err = router._shape(self._ans, kw)
                self.stdout = self._stream(self._out)
                self.stderr = self._stream(self._err)
                self.stdin = None

            @staticmethod
            def _stream(data):
                if data is None:
                    return None
                return io.StringIO(data) if isinstance(data, str) else io.BytesIO(data)

            def communicate(self, input=None, timeout=None):
                return self._out, self._err

            def wait(self, timeout=None):
                return self.returncode

            def poll(self):
                return self.returncode

            def kill(self):
                pass

            def terminate(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return FakePopen

    @staticmethod
    def _shape(ans: _Answer, kw: dict):
        """(stdout, stderr) as the caller asked: None when not piped, text when asked for."""
        pipe = subprocess.PIPE
        out = ans.out if kw.get("stdout") == pipe else None
        if kw.get("stderr") == subprocess.STDOUT and out is not None:
            out, err = ans.out + ans.err, None
        else:
            err = ans.err if kw.get("stderr") == pipe else None
        if kw.get("text") or kw.get("universal_newlines") or kw.get("encoding") or kw.get("errors"):
            enc, errors = kw.get("encoding") or "gbk", kw.get("errors") or "strict"
            out = None if out is None else out.decode(enc, errors).replace("\r\n", "\n")
            err = None if err is None else err.decode(enc, errors).replace("\r\n", "\n")
        return out, err

    # -- routing
    def _answer(self, args) -> _Answer:
        argv = _split_cmdline(args) if isinstance(args, str) else [str(a) for a in args]
        name = ntpath.basename(argv[0]).lower() if argv else ""
        if name.endswith(".exe"):
            name = name[:-4]
        route = {"tasklist": self._tasklist, "taskkill": self._taskkill, "schtasks": self._schtasks,
                 "sc": self._sc, "wevtutil": self._wevtutil, "pwsh": self._pwsh,
                 "shutdown": self._shutdown}.get(name)
        try:
            if route is None:
                raise _Unrouted("no route for this program")
            ans = route(argv[1:], argv)
        except _Unrouted as why:
            raise sim_error(self.sched, "unrouted command", f"{' '.join(argv)} ({why})") from None
        self.calls.append({"t": self.sched.now(), "argv": argv, "rc": ans.rc})
        return ans

    def _acted(self, argv: list[str], action: str, **f) -> None:
        self.sched.out("procs", t=stamp(self.sched.now()), action=action, argv=argv, **f)

    # tasklist ----------------------------------------------------------------
    @staticmethod
    def _flags(args: list[str], with_value: set[str]) -> "tuple[dict[str, list[str]], list[str]]":
        """/X value pairs (repeatable) and bare /Y flags, keys lowercase without the slash."""
        vals: dict[str, list[str]] = {}
        bare = []
        i = 0
        while i < len(args):
            a = args[i]
            if not a.startswith("/"):
                raise _Unrouted(f"argument {a!r} not modelled")
            key = a[1:].lower()
            if key in with_value:
                if i + 1 >= len(args):
                    raise _Unrouted(f"{a} without a value")
                vals.setdefault(key, []).append(args[i + 1])
                i += 2
            else:
                bare.append(key)
                i += 1
        return vals, bare

    @staticmethod
    def _filter(procs: list[Proc], filters: list[str]) -> list[Proc]:
        for f in filters:
            m = re.fullmatch(r"\s*(IMAGENAME|PID)\s+eq\s+(.+?)\s*", f, re.I)
            if not m:
                raise _Unrouted(f"filter {f!r} not modelled")
            key, val = m.group(1).upper(), m.group(2)
            if key == "PID":
                procs = [p for p in procs if str(p.pid) == val]
            else:
                procs = [p for p in procs if fnmatch.fnmatchcase(p.image.lower(), val.lower())]
        return procs

    def _tasklist(self, args, argv) -> _Answer:
        vals, bare = self._flags(args, {"fo", "fi"})
        if set(bare) - {"nh"}:
            raise _Unrouted(f"flags {bare} not modelled")
        fmt = (vals.get("fo") or ["TABLE"])[-1].upper()
        if fmt not in ("TABLE", "CSV"):
            raise _Unrouted(f"/FO {fmt} not modelled")
        rows = self._filter(self.win.procs.alive(), vals.get("fi", []))
        if not rows:
            return _Answer(0, _gbk(TL_NONE))
        nh = "nh" in bare
        lines = []
        if fmt == "CSV":
            if not nh:
                lines.append('"映像名称","PID","会话名      ","会话#   ","内存使用 "')
            lines += [f'"{p.image}","{p.pid}","{_session_name(p)}","{p.session}","{p.mem_k:,} K"'
                      for p in rows]
        else:
            lines.append("")
            if not nh:
                lines.append(f"{'映像名称':<21} {'PID':>8} {'会话名':<13} {'会话#':>10} {'内存使用':>8}")
                lines.append("========================= ======== ================ =========== ============")
            lines += [f"{p.image[:25]:<25} {p.pid:>8} {_session_name(p):<16} {p.session:>11} "
                      f"{f'{p.mem_k:,} K':>12}" for p in rows]
        return _Answer(0, _gbk("\r\n".join(lines) + "\r\n"))

    # taskkill ----------------------------------------------------------------
    def _taskkill(self, args, argv) -> _Answer:
        vals, bare = self._flags(args, {"im", "pid", "fi"})
        if set(bare) - {"f", "t"}:
            raise _Unrouted(f"flags {bare} not modelled")
        alive = self.win.procs.alive()
        out, err, rc = [], [], 0
        chosen: list[tuple[Proc, str]] = []
        for name in vals.get("im", []):
            hit = self._filter(alive, [f"IMAGENAME eq {name}"] + vals.get("fi", []))
            if not hit:
                err.append(f'错误: 没有找到进程 "{name}"。')
                rc = TK_NOT_FOUND
            chosen += [(p, "im") for p in hit]
        for pid in vals.get("pid", []):
            hit = self._filter(alive, [f"PID eq {pid}"] + vals.get("fi", []))
            if not hit:
                err.append(f'错误: 没有找到进程 "{pid}"。')
                rc = TK_NOT_FOUND
            chosen += [(p, "pid") for p in hit]
        if not vals.get("im") and not vals.get("pid"):
            if not vals.get("fi"):
                raise _Unrouted("taskkill with nothing to select")
            chosen = [(p, "pid") for p in self._filter(alive, vals["fi"])]
            if not chosen:
                return _Answer(0, _gbk(TK_NONE_FI))
        if "t" in bare:
            seen = {p.pid for p, _ in chosen}
            todo = [p for p, _ in chosen]
            while todo:
                for c in self.win.procs.children(todo.pop().pid):
                    if c.pid not in seen:
                        seen.add(c.pid)
                        chosen.append((c, "pid"))
                        todo.append(c)
        ended = []
        now = self.sched.now()
        for p, how in chosen:
            if p.protected:
                err.append(f"错误: 无法终止 PID 为 {p.pid} 的进程。\r\n原因: 拒绝访问。")
                rc = rc or 1
                continue
            if self.win.procs.end(p.pid, EXIT_KILLED, now):
                ended.append(p.pid)
                out.append(f'成功: 已终止进程 "{p.image}"，其 PID 为 {p.pid}。' if how == "im"
                           else f"成功: 已终止 PID 为 {p.pid} 的进程。")
        if ended or chosen:
            self._acted(argv, "taskkill", pids=ended, rc=rc)
        return _Answer(rc, _gbk("".join(s + "\r\n" for s in out)), _gbk("".join(s + "\r\n" for s in err)))

    # schtasks ----------------------------------------------------------------
    def _schtasks(self, args, argv) -> _Answer:
        if not args:
            raise _Unrouted("schtasks without a verb")
        verb = args[0].lower()
        vals, bare = self._flags(args[1:], {"tn", "tr", "sc", "st", "ru", "rp", "sd", "fo"})
        name = (vals.get("tn") or [""])[-1]
        key = _task_key(name)
        task = self.win.tasks.get(key)
        if verb == "/create":
            if set(bare) - {"f", "it"} or not name:
                raise _Unrouted(f"/create {bare} not modelled")
            if task is not None and "f" not in bare:
                return _Answer(1, b"", _gbk(f'错误: 无法创建计划任务 "{name}"，因为它已经存在。\r\n'))
            self.win.add_task(name, (vals.get("tr") or [""])[-1])
            self._acted(argv, "task_create", task=name)
            return _Answer(0, _gbk(f'成功: 成功创建计划任务 "{name}"。\r\n'))
        if verb not in ("/delete", "/run", "/end", "/query"):
            raise _Unrouted(f"schtasks {verb} not modelled")
        if set(bare) - {"f"} or not name:
            raise _Unrouted(f"schtasks {verb} {bare} not modelled")
        if task is None:
            return _Answer(1, b"", _gbk(NOT_FOUND_FILE))
        if verb == "/delete":
            del self.win.tasks[key]
            self._acted(argv, "task_delete", task=name)
            return _Answer(0, _gbk(f'成功: 计划的任务 "{name}" 被成功删除。\r\n'))
        if verb == "/run":
            self._acted(argv, "task_run", task=name)
            if self.win.on_task_run is not None:
                self.win.on_task_run(name, task)
            else:
                task["running"] = True
            return _Answer(0, _gbk(f'成功: 尝试运行 "{name}"。\r\n'))
        if verb == "/end":
            self._acted(argv, "task_end", task=name)
            if self.win.on_task_end is not None:
                self.win.on_task_end(name, task)
            else:
                task["running"] = False
            return _Answer(0, _gbk(f'成功: 计划任务 "{name}" 已成功终止。\r\n'))
        state = "正在运行" if task["running"] else "就绪"
        return _Answer(0, _gbk(f"\r\n文件夹: \\\r\n任务名                                   下次运行时间           模式\r\n"
                               f"======================================== ====================== ===============\r\n"
                               f"{task['name']:<40} N/A                    {state}\r\n"))

    # sc ----------------------------------------------------------------------
    def _sc(self, args, argv) -> _Answer:
        if len(args) != 2 or args[0].lower() != "query":
            raise _Unrouted("only `sc query NAME` is modelled")
        svc = self.win.services.get(args[1].lower())
        if svc is None:
            return _Answer(SC_NO_SERVICE, _gbk("[SC] EnumQueryServicesStatus:OpenService 失败 1060:\r\n\r\n"
                                               "指定的服务未安装。\r\n\r\n"))
        code = {"RUNNING": 4, "STOPPED": 1, "START_PENDING": 2, "STOP_PENDING": 3}[svc["state"]]
        return _Answer(0, _gbk(f"\r\nSERVICE_NAME: {svc['name']}\r\n"
                               f"        TYPE               : 10  WIN32_OWN_PROCESS\r\n"
                               f"        STATE              : {code}  {svc['state']}\r\n"
                               f"        WIN32_EXIT_CODE    : 0  (0x0)\r\n\r\n"))

    # wevtutil ----------------------------------------------------------------
    def _wevtutil(self, args, argv) -> _Answer:
        if len(args) != 4 or args[0].lower() != "qe" or args[1] != "System" \
                or not args[2].lower().startswith("/q:") or args[3].lower() != "/f:xml":
            raise _Unrouted("only `wevtutil qe System /q:XPATH /f:xml` is modelled")
        try:
            evs = self.win.query_events(args[2][3:], self.sched.now(), newest_first=False)
        except ValueError as exc:
            raise _Unrouted(str(exc)) from None
        return _Answer(0, "".join(e.xml() for e in evs).encode("utf-8"))

    # PowerShell --------------------------------------------------------------
    def _pwsh(self, args, argv) -> _Answer:
        low = [a.lower() for a in args]
        if "-command" not in low:
            raise _Unrouted("only -Command scripts are modelled")
        i = low.index("-command")
        if i + 2 != len(args) or any(a not in ("-noprofile", "-executionpolicy", "bypass") for a in low[:i]):
            raise _Unrouted("PowerShell switches not modelled")
        script = args[i + 1]
        if "Register-ScheduledTask" in script:
            return self._ps_launch(script, argv)
        return self._ps_pipeline(script, argv)

    def _ps_launch(self, script: str, argv) -> _Answer:
        """preupdate_common._spawn_via_task: register a one-shot task, start it, unregister it."""
        def lit(flag: str) -> "str | None":
            m = re.search(flag + r" '((?:[^']|'')*)'", script)
            return m.group(1).replace("''", "'") if m else None
        exe, cwd = lit("-Execute"), lit("-WorkingDirectory")
        task = re.search(r'Register-ScheduledTask -TaskName "([^"]+)"', script)
        if exe is None or cwd is None or task is None or "Start-ScheduledTask" not in script:
            raise _Unrouted("scheduled-task launch block not recognised")
        args = lit("-Argument") or ""
        self._acted(argv[:1] + ["<launch block>"], "spawn", exe=exe, args=args, task=task.group(1))
        if self.win.on_spawn is not None:
            self.win.on_spawn(exe, args, cwd, task.group(1))
        else:
            self.win.procs.start(ntpath.basename(exe), f'"{exe}" {args}'.strip(), exe=exe,
                                 t=self.sched.now())
        return _Answer(0)

    def _ps_pipeline(self, script: str, argv) -> _Answer:
        stages = [s.strip() for s in _split_pipeline(script)]
        m = re.fullmatch(r'Get-CimInstance Win32_Process -Filter "(.+)"', stages[0], re.S)
        if not m:
            raise _Unrouted(f"pipeline start {stages[0][:60]!r} not modelled")
        names = re.findall(r"Name\s*=\s*'([^']+)'", m.group(1))
        if not names or re.sub(r"Name\s*=\s*'[^']+'|\bor\b", " ", m.group(1), flags=re.I).strip():
            raise _Unrouted(f"-Filter {m.group(1)!r} not modelled")
        rows = [p for p in self.win.procs.alive() if p.image.lower() in {n.lower() for n in names}]
        objs: "list[dict] | None" = [{"ProcessId": p.pid, "Name": p.image, "CommandLine": p.cmdline,
                                      "ExecutablePath": p.exe or None} for p in rows]
        text: "list[str] | None" = None
        for st in stages[1:]:
            if objs is None:
                raise _Unrouted(f"stage after output {st[:60]!r} not modelled")
            if w := re.fullmatch(r"Where-Object \{ \$_\.(\w+) -like '((?:[^']|'')*)' \}", st):
                pat = w.group(2).replace("''", "'").lower()
                objs = [o for o in objs if fnmatch.fnmatchcase(str(o.get(w.group(1)) or "").lower(), pat)]
            elif s := re.fullmatch(r"Select-Object ([\w, ]+)", st):
                keep = [k.strip() for k in s.group(1).split(",")]
                objs = [{k: o.get(k) for k in keep} for o in objs]
            elif st == "ConvertTo-Json -Compress":
                text = [] if not objs else [json.dumps(objs[0] if len(objs) == 1 else objs,
                                                       ensure_ascii=False, separators=(",", ":"))]
                objs = None
            elif st == "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }":
                now = self.sched.now()
                ended = [o["ProcessId"] for o in objs if self.win.procs.end(o["ProcessId"], EXIT_KILLED, now)]
                self._acted(argv[:1] + ["<Stop-Process>"], "stop_process", pids=ended)
                text, objs = [], None
            elif f := re.fullmatch(r"ForEach-Object \{ '((?:[^']|'')*)' -f ((?:\$_\.\w+(?:, )?)+) \}", st):
                fmt = f.group(1).replace("''", "'")
                keys = re.findall(r"\$_\.(\w+)", f.group(2))
                text = [fmt.format(*["" if o.get(k) is None else o.get(k) for k in keys]) for o in objs]
                objs = None
            else:
                raise _Unrouted(f"stage {st[:60]!r} not modelled")
        if objs is not None:
            raise _Unrouted("pipeline ends in objects; their default formatting is not modelled")
        return _Answer(0, "".join(t + "\r\n" for t in text).encode("utf-8"))

    # shutdown ----------------------------------------------------------------
    def _shutdown(self, args, argv) -> _Answer:
        vals, bare = self._flags(args, {"t", "d", "c"})
        now = self.sched.now()
        cmd = " ".join(argv)
        if bare == ["a"] and not vals:
            if self.win.power != "countdown":
                self.sched.out("power", t=stamp(now), cmd=cmd, rc=NO_SHUTDOWN)
                return _Answer(NO_SHUTDOWN, b"", _gbk("无法中止系统关机，因为没有进行中的关机。(1116)\r\n"))
            self.win.abort_countdown()
            self.win.log_event(now, 1075, "User32", {"param1": "INS", "param2": "NT AUTHORITY\\SYSTEM"})
            self.sched.out("power", t=stamp(now), cmd=cmd, rc=0)
            return _Answer(0)
        if bare != ["s"] or set(vals) - {"t", "d", "c"}:
            raise _Unrouted(f"shutdown {args} not modelled")
        if self.win.power != "on":
            self.sched.out("power", t=stamp(now), cmd=cmd, rc=SHUTDOWN_PENDING)
            return _Answer(SHUTDOWN_PENDING, b"", _gbk("系统已计划关机。(1190)\r\n"))
        delay = int((vals.get("t") or ["30"])[-1])     # shutdown.exe's own default is 30 s
        self.win.begin_countdown(delay)
        self.win.log_event(now, 1074, "User32", {
            "param1": r"C:\WINDOWS\system32\shutdown.exe (INS)", "param2": "INS",
            "param3": "其他(计划内)", "param4": "0x80040001", "param5": "关机",
            "param6": (vals.get("c") or [""])[-1], "param7": "NT AUTHORITY\\SYSTEM"})
        self.sched.out("power", t=stamp(now), cmd=cmd, rc=0)
        return _Answer(0)


def _session_name(p: Proc) -> str:
    return "Services" if p.session == 0 else "Console"


def _split_pipeline(script: str) -> list[str]:
    """Split a PowerShell pipeline on the | outside quotes and braces."""
    parts, cur, depth, quote = [], [], 0, ""
    for ch in script:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    return parts
