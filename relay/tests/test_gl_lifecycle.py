"""gamesim T15: process lifecycle on recorded process lists and logs.

Each case under gamesim/corpus/lifecycle/ is one failure seen on the game machine:
the processes that were running (paths and pids from the machine's own logs), how
the machine answered the relay's kill and list commands, and what the relay must
have left behind. Expected values come from those records and the fix commits'
measured statements, never from the code under test.

The Windows side is a fake, because Windows is outside the test: `WinSim` keeps a
process table and evaluates the commands the relay sends it - taskkill, tasklist,
schtasks, and the Get-CimInstance pipelines it hands to PowerShell. The pipelines
are evaluated, not recognised by shape: a filter that names the wrong program
(python.exe for pythonw.exe, launcher.exe for launcher_main.exe) selects nothing,
as it did on the machine. A pipeline stage the fake does not know raises, so a
changed query fails loudly instead of passing.

The same file runs against older trees to prove each case red at its <fix>~1:
module paths moved (ark_relay.preupdate_okww -> ark_relay.features.preupdate...)
and signatures grew, so entry points are found by name and called with only the
keyword arguments they accept.
"""
from __future__ import annotations

import fnmatch
import importlib
import inspect
import json
import logging
import re
import shlex
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path, PureWindowsPath

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
CORPUS = HERE / "gamesim" / "corpus" / "lifecycle"

PREUPDATE_OKWW = ("ark_relay.features.preupdate.preupdate_okww", "ark_relay.preupdate_okww",
                  "ark_relay.preupdate")
ECHOFARM = ("ark_relay.features.echofarm.echofarm", "ark_relay.echofarm")

FAILED: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(label)


def load(names: tuple[str, ...]):
    """The first of `names` that this tree has. Only a missing module itself moves on
    to the next name; an import error inside it propagates."""
    for name in names:
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if not (exc.name and name.startswith(exc.name)):
                raise
    raise ModuleNotFoundError(f"none of {names} in this tree")


def call(fn, **kwargs):
    """fn(**kwargs) with only the keyword arguments its signature has."""
    params = inspect.signature(fn).parameters
    return fn(**{k: v for k, v in kwargs.items() if k in params})


# --- virtual time ---------------------------------------------------------------

_REAL_SLEEP, _REAL_MONOTONIC = time.sleep, time.monotonic


class VirtualTime:
    """time.sleep / time.monotonic for one case: sleeping only moves the clock.

    Also swapped into every relay function whose default argument is the real
    time.sleep or time.monotonic (bound when the module was imported, so patching
    the time module alone would not reach them)."""

    def __init__(self) -> None:
        self.now = 1000.0
        self._saved: list = []

    def sleep(self, seconds) -> None:
        self.now += max(0.0, float(seconds))

    def monotonic(self) -> float:
        return self.now

    def _swap(self, value):
        if value is _REAL_SLEEP:
            return self.sleep
        if value is _REAL_MONOTONIC:
            return self.monotonic
        return value

    def __enter__(self):
        time.sleep, time.monotonic = self.sleep, self.monotonic
        for name, mod in list(sys.modules.items()):
            if not (name == "ark_relay" or name.startswith("ark_relay.")) or mod is None:
                continue
            for obj in list(vars(mod).values()):
                if not (inspect.isfunction(obj) and obj.__module__ == name):
                    continue
                if obj.__defaults__:
                    new = tuple(self._swap(d) for d in obj.__defaults__)
                    if new != obj.__defaults__:
                        self._saved.append((obj, "__defaults__", obj.__defaults__))
                        obj.__defaults__ = new
                if obj.__kwdefaults__:
                    new_kw = {k: self._swap(v) for k, v in obj.__kwdefaults__.items()}
                    if new_kw != obj.__kwdefaults__:
                        self._saved.append((obj, "__kwdefaults__", obj.__kwdefaults__))
                        obj.__kwdefaults__ = new_kw
        return self

    def __exit__(self, *exc) -> None:
        time.sleep, time.monotonic = _REAL_SLEEP, _REAL_MONOTONIC
        for obj, attr, value in reversed(self._saved):
            setattr(obj, attr, value)


# --- the fake Windows -----------------------------------------------------------

class Unknown(AssertionError):
    """A command the fake does not model: the query changed and must be looked at."""


_CIM = re.compile(r'Get-CimInstance Win32_Process -Filter "(?P<filter>[^"]*)" \| (?P<rest>.*)\Z', re.S)
_CLAUSE = re.compile(r"\$_\.(?P<field>\w+) -like '(?P<pat>[^']*)'\Z")
_FIELDS = {"Name": "name", "ProcessId": "pid", "ExecutablePath": "path", "CommandLine": "cmdline"}


class WinSim:
    """The machine's process table and the commands that act on it.

    `refused`: process names a kill from session 0 (the relay's service) does not
    reach. A kill run from the interactive session (the scheduled task's .bat)
    reaches every process. `task_route`: what a Register-ScheduledTask launch does
    ("starts" or "fails")."""

    def __init__(self, procs: list[dict], refused=(), task_route: str = "starts") -> None:
        self.procs = {int(p["pid"]): dict(p) for p in procs}
        self.refused = {n.lower() for n in refused}
        self.task_route = task_route
        self.tasks: dict[str, str] = {}
        self.events: list[dict] = []
        self.launches: list[tuple[str, int]] = []

    # process table
    def alive_roles(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for p in self.procs.values():
            out.setdefault(p.get("role", ""), []).append(p["name"])
        return out

    def _kill(self, pid: int, session: int, how: str) -> bool:
        p = self.procs.get(pid)
        if p is None:
            return False
        roles_alive = sorted({q.get("role", "") for q in self.procs.values()})
        ok = not (session == 0 and p["name"].lower() in self.refused)
        self.events.append({"kill": p["name"], "role": p.get("role", ""), "pid": pid, "how": how,
                            "session": session, "done": ok, "alive_before": roles_alive})
        if ok:
            del self.procs[pid]
        return ok

    # commands
    def run(self, args, *a, **k):
        argv = [str(x) for x in (args if isinstance(args, (list, tuple)) else shlex.split(args))]
        exe = PureWindowsPath(argv[0]).name.lower() if argv else ""
        if exe in ("taskkill", "taskkill.exe"):
            return self._taskkill(argv, session=0)
        if exe in ("tasklist", "tasklist.exe"):
            return self._done(argv, 0, self._tasklist())
        if exe in ("schtasks", "schtasks.exe"):
            return self._schtasks(argv)
        if any(x.lower() == "-command" for x in argv[1:]):
            # PowerShell 7, or 5.1 in the oldest trees: told apart by the call, not the name.
            return self._pwsh(argv)
        raise Unknown(f"command not modelled: {argv!r}")

    def popen(self, args, *a, **k):
        # A plain detached launch from the relay's own session: session 0.
        argv = [str(x) for x in args]
        self.launches.append((PureWindowsPath(argv[0]).name, 0))
        return types.SimpleNamespace(pid=0, wait=lambda *_a, **_k: 0, poll=lambda: None)

    @staticmethod
    def _done(argv, code: int, out: str = "", err: str = ""):
        return subprocess.CompletedProcess(argv, code, out.encode("utf-8"), err.encode("utf-8"))

    def _taskkill(self, argv, session: int):
        up = [x.upper() for x in argv]
        if "/PID" in up:
            pids = [int(argv[up.index("/PID") + 1])]
        elif "/IM" in up:
            name = argv[up.index("/IM") + 1].strip('"').lower()
            pids = [pid for pid, p in self.procs.items() if p["name"].lower() == name]
            self.events.append({"kill_by_name": name, "session": session,
                                "alive_before": sorted({q.get("role", "") for q in self.procs.values()})})
        else:
            raise Unknown(f"taskkill form not modelled: {argv!r}")
        if not pids:
            # Not recorded on the machine; the relay only ever tells zero from non-zero.
            return self._done(argv, 128, err="ERROR: not found")
        done = [self._kill(pid, session, "taskkill") for pid in pids]
        return self._done(argv, 0 if all(done) else 1, err="" if all(done) else "ERROR: Access is denied.")

    def _tasklist(self) -> str:
        # Layout not recorded; the relay only looks for program names in it.
        rows = ["Image Name                     PID Session Name        Session#    Mem Usage",
                "========================= ======== ================ =========== ============"]
        rows += [f"{p['name']:<25} {pid:>8} {'Console' if p.get('session') else 'Services':<16} "
                 f"{p.get('session', 0):>11} {'1,000 K':>12}" for pid, p in self.procs.items()]
        return "\r\n".join(rows) + "\r\n"

    def _schtasks(self, argv):
        up = [x.lower() for x in argv]
        verb = up[1] if len(up) > 1 else ""
        name = argv[up.index("/tn") + 1] if "/tn" in up else ""
        if verb in ("/end", "/delete"):
            # Ending the farm's task stops its own process only: OK-WW lived on after
            # it on 2026-09-09 (93ec907b), so it touches nothing here.
            return self._done(argv, 0)
        if verb == "/create":
            self.tasks[name] = argv[up.index("/tr") + 1]
            return self._done(argv, 0)
        if verb == "/run":
            bat = self.tasks.get(name)
            if bat is None:
                return self._done(argv, 1, err="ERROR: The system cannot find the file specified.")
            for line in Path(bat).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.lower() == "@echo off":
                    continue
                parts = shlex.split(line)
                if PureWindowsPath(parts[0]).name.lower() not in ("taskkill", "taskkill.exe"):
                    raise Unknown(f"stop .bat line not modelled: {line!r}")
                self._taskkill(parts, session=1)
            return self._done(argv, 0)
        raise Unknown(f"schtasks form not modelled: {argv!r}")

    def _pwsh(self, argv):
        try:
            ps = argv[[x.lower() for x in argv].index("-command") + 1]
        except (ValueError, IndexError):
            raise Unknown(f"pwsh call without -Command: {argv!r}") from None
        if "Register-ScheduledTask" in ps:
            if self.task_route != "starts":
                return self._done(argv, 1, err="Register-ScheduledTask failed")
            m = re.search(r"""-Execute (?:'((?:[^']|'')*)'|"([^"]*)")""", ps)
            self.launches.append((PureWindowsPath((m.group(1) or m.group(2)) if m else "?").name, 1))
            return self._done(argv, 0)
        m = _CIM.match(ps.strip())
        if not m:
            raise Unknown(f"PowerShell not modelled: {ps!r}")
        filt = m.group("filter")
        names = re.findall(r"Name='([^']*)'", filt)
        if not names or filt != " OR ".join(f"Name='{n}'" for n in names):
            raise Unknown(f"-Filter not modelled: {filt!r}")
        rows = [p for p in self.procs.values() if p["name"].lower() in {n.lower() for n in names}]
        out = ""
        for stage in (s.strip() for s in m.group("rest").split(" | ")):
            if stage.startswith("Where-Object {") and stage.endswith("}"):
                clauses = [_CLAUSE.match(c.strip()) for c in
                           re.split(r"\s+-or\s+", stage[len("Where-Object {"):-1].strip())]
                if not all(clauses) or any(c.group("field") not in _FIELDS for c in clauses):
                    raise Unknown(f"Where-Object not modelled: {stage!r}")
                # -like: case-insensitive wildcard, backslash an ordinary character.
                rows = [p for p in rows if any(
                    fnmatch.fnmatchcase(str(p.get(_FIELDS[c.group("field")], "")).lower(),
                                        c.group("pat").lower()) for c in clauses)]
            elif stage == "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }":
                for p in list(rows):
                    self._kill(int(p["pid"]), 0, "Stop-Process")
                rows = []
            elif stage.startswith("Select-Object "):
                fields = [f.strip() for f in stage[len("Select-Object "):].split(",")]
                if any(f not in _FIELDS for f in fields):
                    raise Unknown(f"Select-Object not modelled: {stage!r}")
                rows = [{f: p.get(_FIELDS[f]) for f in fields} for p in rows]
            elif stage == "ConvertTo-Json -Compress":
                # No object: no output. One: a bare object, not a list.
                out = "" if not rows else json.dumps(rows[0] if len(rows) == 1 else rows,
                                                     ensure_ascii=False)
            else:
                raise Unknown(f"pipeline stage not modelled: {stage!r}")
        return self._done(argv, 0, out)


# The Windows-only creation flags a detached launch passes (values from the Python
# docs, subprocess "Windows Constants"); absent on macOS.
_WIN_FLAGS = {"CREATE_NEW_PROCESS_GROUP": 0x00000200, "DETACHED_PROCESS": 0x00000008,
              "CREATE_NO_WINDOW": 0x08000000}


class Patched:
    """subprocess.run / Popen go to the fake for the length of one case."""

    def __init__(self, sim: WinSim) -> None:
        self.sim = sim

    def __enter__(self):
        self._run, self._popen = subprocess.run, subprocess.Popen
        subprocess.run, subprocess.Popen = self.sim.run, self.sim.popen
        self._added = [n for n in _WIN_FLAGS if not hasattr(subprocess, n)]
        for n in self._added:
            setattr(subprocess, n, _WIN_FLAGS[n])
        return self.sim

    def __exit__(self, *exc) -> None:
        subprocess.run, subprocess.Popen = self._run, self._popen
        for n in self._added:
            delattr(subprocess, n)


class Records(logging.Handler):
    """Every log record of one case, kept for the verdict (and off the console)."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record) -> None:
        try:
            self.lines.append(record.getMessage())
        except Exception:  # noqa: BLE001 - a bad log call must not hide the verdict
            self.lines.append(str(record.msg))

    def __enter__(self):
        root = logging.getLogger()
        self._level = root.level
        root.addHandler(self)
        root.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *exc) -> None:
        root = logging.getLogger()
        root.removeHandler(self)
        root.setLevel(self._level)


def judge(case: dict, sim: WinSim, outcome: dict) -> None:
    """Every `expect` entry of `case` against what the fake machine ended with."""
    for exp in case["expect"]:
        label = f"{case['id']} {outcome.get('variant', '')} {exp['id']}".replace("  ", " ")
        kind = exp["kind"]
        if kind == "none_alive":
            alive = sim.alive_roles()
            check(f"{label}: still running", sorted(n for r in exp["roles"] for n in alive.get(r, [])), [])
        elif kind == "no_kill_while_alive":
            targets = {p["name"].lower() for p in case["processes"] if p["role"] == exp["target_role"]}
            early = sorted({(e.get("kill_by_name") or e.get("kill", "")).lower() for e in sim.events
                            if (e.get("kill_by_name") or e.get("kill", "")).lower() in targets
                            and exp["alive_role"] in e["alive_before"]})
            check(f"{label}: game kills issued while the script still ran", early, [])
        elif kind == "no_log_containing":
            check(f"{label}: log lines with {exp['text']}",
                  [s for s in outcome["log"] if exp["text"] in s], [])
        elif kind == "problems_nonempty":
            check(f"{label}: a problem was noted", bool(outcome["problems"]), True)
        else:
            raise Unknown(f"expect kind not modelled: {kind!r}")


def _procs(case: dict) -> list[dict]:
    return [{k: v for k, v in p.items() if k not in ("evidence", "not_recorded")} for p in case["processes"]]


def run_l1(case: dict, tmp: Path) -> None:
    echofarm = load(ECHOFARM)
    if hasattr(echofarm, "STOP_BAT"):
        # A Windows path on macOS is a file name in the cwd; keep the .bat in tmp.
        echofarm.STOP_BAT = str(tmp / "ark-okww-stop.bat")
    sim = WinSim(_procs(case), refused=case["machine"]["session0_kill_refused"])
    with Records() as rec, VirtualTime() as vt, Patched(sim):
        call(echofarm.stop_okww, sleep=vt.sleep, clock=vt.monotonic)
    judge(case, sim, {"log": rec.lines})


def run_l2(case: dict, tmp: Path) -> None:
    pk = load(PREUPDATE_OKWW)
    sim = WinSim(_procs(case), refused=case["machine"]["session0_kill_refused"])
    with Records() as rec, VirtualTime() as vt, Patched(sim):
        call(pk._okww_quiesce, sleep=vt.sleep, launcher_root=PureWindowsPath(case["launcher_root"]))
    judge(case, sim, {"log": rec.lines})


def _fake_pywin32(spec: dict, tried: list[str]) -> dict[str, types.ModuleType]:
    """pywin32 as the machine answered on 2026-08-25: a console session exists, and
    CreateProcessAsUser fails with 740. Anything else it is asked raises
    AttributeError, which the relay treats as "this route does not work"."""
    class error(Exception):
        """pywintypes.error, under its own name."""

        def __init__(self, winerror, funcname, strerror):
            super().__init__(winerror, funcname, strerror)
            self.winerror, self.funcname, self.strerror = winerror, funcname, strerror

    def create_process_as_user(*_a, **_k):
        tried.append("CreateProcessAsUser")
        raise error(*spec["CreateProcessAsUser_error"])

    token = types.SimpleNamespace(Close=lambda: None)
    mods = {
        "pywintypes": types.SimpleNamespace(error=error),
        "win32con": types.SimpleNamespace(CREATE_NEW_CONSOLE=0x10, MAXIMUM_ALLOWED=0x02000000),
        "win32process": types.SimpleNamespace(CREATE_UNICODE_ENVIRONMENT=0x400,
                                              STARTUPINFO=types.SimpleNamespace,
                                              CreateProcessAsUser=create_process_as_user),
        "win32profile": types.SimpleNamespace(CreateEnvironmentBlock=lambda *_a: {}),
        "win32ts": types.SimpleNamespace(WTSGetActiveConsoleSessionId=lambda: spec["console_session"],
                                         WTSQueryUserToken=lambda _s: token),
        "win32security": types.SimpleNamespace(),
        "win32api": types.SimpleNamespace(),
    }
    out = {}
    for name, ns in mods.items():
        mod = types.ModuleType(name)
        mod.__dict__.update(vars(ns))
        out[name] = mod
    return out


def run_l3(case: dict, tmp: Path) -> None:
    pk = load(PREUPDATE_OKWW)
    for variant in case["variants"]:
        root = tmp / variant["id"]
        app = root / "data" / "apps" / "ok-ww"
        (app / "working" / "configs").mkdir(parents=True)
        (root / "ok-ww.exe").write_bytes(b"")
        (app / "working" / "configs" / "Basic Options.json").write_text(
            json.dumps(case["basic_options"], ensure_ascii=False), encoding="utf-8")
        state = {k: v for k, v in case["app_json"].items() if k not in ("evidence", "not_recorded")}
        (app / "app.json").write_text(json.dumps(state), encoding="utf-8")
        sim = WinSim([], task_route=variant["task_route"])
        tried: list[str] = []
        fakes = _fake_pywin32(case["pywin32"], tried)
        saved = {n: sys.modules.get(n) for n in fakes}
        problems: list[str] = []
        try:
            sys.modules.update(fakes)
            with Records() as rec, VirtualTime(), Patched(sim):
                call(pk.run_okww, okww_dir=root, problems=problems)
        finally:
            for n, m in saved.items():
                if m is None:
                    sys.modules.pop(n, None)
                else:
                    sys.modules[n] = m
        print(f"  ({variant['id']}: token route {tried or 'not tried'}; launches {sim.launches}; "
              f"problems {problems})")
        judge(case, sim, {"variant": variant["id"], "log": rec.lines, "problems": problems})


RUNNERS = {"echofarm.stop_okww": run_l1, "preupdate_okww._okww_quiesce": run_l2,
           "preupdate_okww.run_okww": run_l3}


def main(argv: list[str]) -> int:
    """All cases; `--only L3` runs one (the red/green runs against older trees, where
    a case's entry point may not exist yet)."""
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    cases = sorted(CORPUS.glob("*.json"))
    check("lifecycle cases in the corpus", len(cases), 3)
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        if only and case["id"] != only:
            continue
        print(f"[{case['id']} {case['date']}: {case['failure'][:70]}]")
        for exp in case["expect"]:
            check(f"{case['id']} {exp['id']} carries evidence", bool(exp.get("evidence")), True)
        with tempfile.TemporaryDirectory(prefix="gl-lifecycle-") as tmp:
            RUNNERS[case["entry"]](case, Path(tmp))
    print("\n" + ("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
