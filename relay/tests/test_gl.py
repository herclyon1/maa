"""Game-layer tests that no other script runs on its own: the lifecycle corpus, the log contract, the MAA and MaaEnd config copies.

One part per former file, each run on its own (tests/_parts.py): test_gl_lifecycle.py, test_gl_log_contract.py, test_gl_maa_config.py, test_gl_maaend_config.py.
"""
from __future__ import annotations

# Each part imports the relay itself, after its own environment is set, as the file it was did at
# its top.
# ruff: noqa: PLC0415
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir  # after the path

# What the parts share (tests/_parts.py), named here so a file whose parts use only some of it
# still reads as using all of it.
_SHARED = (check, fails, require, tmpdir)


def _part_gl_lifecycle():  # noqa: C901 - the whole body of the file this part was
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

    Formerly test_gl_lifecycle.py.
    """

    import fnmatch
    import importlib
    import inspect
    import json
    import logging
    import re
    import shlex
    import subprocess
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


def _part_gl_log_contract():
    """The T7 log contract on the Mac (gamesim design 3): runs gamesim/chain/test_log_contract.py.

That test judges, with the relay's own verdict code, the real machine logs the relay once misread
and the scenario logs the real overlay printed on Windows (committed copies in
gamesim/chain/logs/). It lives under gamesim/chain/ because the Windows job runs it on fresh logs
(ci_prepare.py, lane `installed`); this file puts the same check in the Mac gate, which runs
tests/test_*.py only.

    relay-python tests/test_gl_log_contract.py

    Formerly test_gl_log_contract.py.
    """
    import subprocess

    CHAIN = Path(__file__).resolve().parent / "gamesim" / "chain" / "test_log_contract.py"

    p = subprocess.run([sys.executable, str(CHAIN)], capture_output=True, text=True, encoding="utf-8")
    out = p.stdout + p.stderr
    print(out.rstrip())
    last = (out.strip().splitlines() or [""])[-1]
    if p.returncode != 0 or not last.endswith("all checks passed"):
        print("FAILED: gamesim/chain/test_log_contract.py")
        sys.exit(1)
    print("all checks passed")


def _part_gl_maa_config():  # noqa: C901 - the whole body of the file this part was
    """T12 for MAA: what our code writes into MAA's and AUTO-MAS's configs is what they read.

Every expected verdict below comes from a machine record or from the pinned upstream
sources (gamesim/upstream/maa-v6.19.0, the version installed since 10-12, SOURCE.txt;
maa-v6.19.0-beta.1 for the 10-10 replay), never from the relay code
under test. Upstream rules that are code are executed from the pinned files
(gamesim/lib/maa_schema.py); the one fake, the AUTO-MAS backend, is pinned by the body
hashes of the handlers it stands in for.

Cases (a name on the command line runs only those cases):

  pin         the pinned files are byte-identical to SOURCE.txt; the upstream functions
              the relay imitates (stagegate: FightTask::set_params,
              StageNavigationTask::set_stage_name) or this test fakes (the backend
              handlers, ConfigItem.setValue) still have the bodies they were checked
              against; MAA still prints drop lines the way collector_maa reads them.
  yw4         2026-10-10: the phone set the stage to YW-4 at 04:25 and MAA refused the
              Fight task at 09:01 (序列化失败), stopping the whole run. With MAA's task
              tree as on the machine that morning (v6.19.0-beta.1 resource/tasks plus
              Stages/YW.json at MAA dev c09d3fe7) set_stage must refuse YW-4 and send
              nothing; with YW.json at cc780293 (YW-4 added; MAA took YW-4 on 10-11) it
              must go through. Red at 3fce7262~1, green at 3fce7262.
  annihilation 2026-08-31: the weekly switch restored by editing ScriptConfig.json while
              AUTO-MAS ran was washed back to Close from its memory copy and the week
              went unplayed. The writer of Info.Annihilation must go through the
              backend and leave the file alone. The writer is whatever this tree has:
              annihilation.WeeklyGate.maybe_reopen before the 10-11 switch-over,
              relay/handover step 13 since. Red at 2a6ff6da~1, green at 2a6ff6da.
  user        set_stage / set_medicine through the backend: each field written is
              declared on AUTO-MAS's MaaUserConfig, its value passes AUTO-MAS's own
              validator, AutoProxy reads it, and ScriptConfig.json is not touched.
  handover    the values relay/handover writes for MAA (steps 13 and 10a) pass
              AUTO-MAS's validators and are read; the week marker it writes into
              Data.AnnihilationCompletedWeek equals AUTO-MAS's own
              (_current_week_marker on game_now), across the Monday 04:00 reset and the
              ISO year turn.
  guinew      gui.new.json: our drone values are MAA's UsesOfDronesList, our Award
              switches are AwardTask properties MaaCore reads; write_maa into a copy of
              the machine's tree, then AUTO-MAS's own _copy_source_config and
              _find_task_source hand MAA a task carrying the value, under a $type MAA
              can deserialise, with nothing else changed.

    Formerly test_gl_maa_config.py.
    """

    import contextlib
    import copy
    import importlib
    import io
    import json
    import logging
    import os
    import shutil
    import threading
    import types
    from datetime import datetime, timedelta, timezone
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    sys.path.insert(0, str(HERE.parent / "handover"))
    sys.path.insert(0, str(HERE))


    class _Any:
        """Stands in for any pywin32 attribute (the phone commands pull in service helpers)."""
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _): return _Any()


    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _Any


    for _name in ("win32serviceutil", "win32service", "win32event", "win32api",
                  "win32con", "win32file", "servicemanager", "win32process",
                  "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
        sys.modules.setdefault(_name, _Stub(_name))

    from gamesim.lib import maa_schema as S

    MACHINE = HERE / "gamesim" / "maa" / "machine"
    SCRIPT_CONFIG = json.loads((MACHINE / "ScriptConfig.json").read_text(encoding="utf-8"))
    GUI_NEW = (MACHINE / "gui.new.json").read_bytes()
    MAA_SID = next(i["uid"] for i in SCRIPT_CONFIG["instances"] if i["type"] == "MaaConfig")

    # Body hashes of the upstream functions the relay imitates or this test fakes. A new pin
    # whose bodies differ turns `pin` red before anything else: re-check stagegate.py against
    # the new set_params / set_stage_name, and _Backend against the new handlers.
    PINNED_BODIES = {
        ("maa", "src/MaaCore/Assistant.cpp", "asst::Assistant::append_task"):
            "753ff4dfa408bd0be33caca33e862b6ebdd87cd5d7d93e3994db06d3352d7770",
        ("maa", "src/MaaCore/Task/Interface/FightTask.cpp", "asst::FightTask::set_params"):
            "eeaa4158b47e3c3e20fc93607a69dc750dfddf4bff50b82b2b4b95ae61edc815",
        ("maa", "src/MaaCore/Task/Fight/StageNavigationTask.cpp", "asst::StageNavigationTask::set_stage_name"):
            "ee2eedbfaf848191db38e1da587079d15e38783c9de2081bf8ab9ef86d02ef5c",
        ("automas", "app/api/scripts.py", "get_script"):
            "33a4fe52689e4e1e0bc22992d5df219db014621d670ad78c754358134dadcc6c",
        ("automas", "app/api/scripts.py", "update_script"):
            "31263dc778a616530ad2bfeb901c608e05725f48583ee3c3927a6efd9f2b964a",
        ("automas", "app/api/scripts.py", "get_user"):
            "aaab65fcbea758118252bf46aa44b9316dfce1e75230b7e659b3186e48d9988d",
        ("automas", "app/api/scripts.py", "update_user"):
            "adf5b637f3accf6d28d60fab98035c35f57c2a6331f71a3cc373f3f40d56137d",
        ("automas", "app/models/ConfigBase.py", "ConfigItem.setValue"):
            "a95cd9a53c4841022301c48e3c42aab3441971da2820a170e7c5175229bc6d85",
    }

    # How MAA prints a drop line; collector_maa._DROP_ITEM / _maa_count read exactly this shape
    # ("龙门币 : 10.1k (+1440)"). A new pin that prints otherwise turns `pin` red.
    PRINTED = {
        "src/MaaWpfGui/Main/AsstProxy.cs": [
            'allDrops += $"{itemName} : {totalQuantity.FormatNumber(false)}";',
            'allDrops += $" (+{addQuantity.FormatNumber(false)})";'],
        "src/MaaWpfGui/Extensions/NumberExtensions.cs": [
            '>= 1_000_000_000 => $"{n / 1_000_000_000.0:#.#}B",',
            '>= 1_000_000 => $"{n / 1_000_000.0:#.#}M",',
            '>= 10_000 => $"{n / 1_000.0:#.#}k",'],
    }

    EVIDENCE = {
        "yw4_set": "relay.log 10-10 04:25:27 ark.service 「📱 手机指令 set_stage：刷取关卡：1-7 → YW-4（调度程序已确认）」",
        "yw4_refused": ("MAA asst.log 2026-10-10 09:01:10.060-.061 (COS bundle 2026-10-10_arknights_MAA-05-00-01): "
                        "'Unknown task: YW-4' / 'The stage name is not in invalid, or is not main line stage YW-4' / "
                        "'Cannot set stage YW-4' / 'append_task | invalid params'; gui.log 09:01:10.061 "
                        "「理智作战: 理智作战 序列化失败」 then 「已停止」, three times (09:01, 09:02, 09:03)"),
        "yw4_taken": ("MAA asst.log 2026-10-11 21:30:43.511 append_task Fight {\"stage\":\"YW-4\",...} -> "
                      "'directly task YW-4', set_params leave (no error)"),
        "maa_tree": ("MAA gui.log 2026-10-10 09:01:08 'Resource Time: 2026/10/10 07:31:13' (MaaResource 8d949986, "
                     "version.json last_updated 2026-10-09 23:31:13 UTC); MAA dev c09d3fe7 2026-10-09 10:06Z added "
                     "Stages/YW.json without YW-4, cc780293 2026-10-10 02:22Z added YW-4"),
        "one_seven": "MAA asst.log 2026-10-06 21:31:12.189 append_task Fight {\"stage\":\"1-7\",...} -> 'directly task 1-7', task_id 2",
        "washout": ("2a6ff6da message: 2026-08-31 04:01 「新的一周，剿灭已恢复为 Annihilation」 was written to the file and read "
                    "back, AUTO-MAS was running and rewrote the file from memory, the value went back to Close and the "
                    "week's annihilation never ran"),
    }


    # ---------- the AUTO-MAS backend (fake; handlers pinned in PINNED_BODIES) ----------

    class _Backend:
        """AUTO-MAS's /api/scripts endpoints over a copy of the machine's ScriptConfig.

    Like app/api/scripts.py: get returns {code, index, data}; update merges the posted
    groups key by key, each value through the item's own upstream validator
    (ConfigItem.setValue: validate, else correct). It never writes ScriptConfig.json:
    the running AUTO-MAS keeps its copy in memory, so the file on disk is exactly what
    the writer under test left there.
    """

        def __init__(self) -> None:
            backend = self

            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"] or 0)) or b"{}")
                    reply = json.dumps(backend.answer(self.path, body)).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(reply)))
                    self.end_headers()
                    self.wfile.write(reply)

                def log_message(self, *a):
                    pass

            self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            threading.Thread(target=self.srv.serve_forever, daemon=True).start()
            self.port = self.srv.server_address[1]
            self.cfg: dict = {}
            self.calls: list[tuple[str, dict]] = []

        def reset(self, cfg: dict) -> None:
            self.cfg, self.calls = copy.deepcopy(cfg), []

        def updates(self) -> list[tuple[str, dict]]:
            return [(p, b) for p, b in self.calls if p.endswith("/update")]

        def user(self) -> dict:
            ud = self.cfg[MAA_SID]["SubConfigsInfo"]["UserData"]
            return ud[ud["instances"][0]["uid"]]

        def answer(self, path: str, body: dict) -> dict:
            self.calls.append((path, body))
            scripts = {k: v for k, v in self.cfg.items() if k != "instances"}
            sid = body.get("scriptId")
            if path == "/api/scripts/get":
                return {"code": 200, "status": "success", "message": "",
                        "index": [i for i in self.cfg["instances"] if not sid or i["uid"] == sid],
                        "data": {k: {g: v for g, v in sc.items() if g != "SubConfigsInfo"}
                                 for k, sc in scripts.items() if not sid or k == sid}}
            if path == "/api/scripts/user/get":
                ud = scripts[sid]["SubConfigsInfo"]["UserData"]
                return {"code": 200, "status": "success", "message": "", "index": ud["instances"],
                        "data": {k: v for k, v in ud.items() if k != "instances"
                                 and (not body.get("userId") or k == body["userId"])}}
            if path == "/api/scripts/update":
                self._merge(scripts[sid], body.get("data") or {}, "MaaConfig")
                return {"code": 200, "status": "success", "message": ""}
            if path == "/api/scripts/user/update":
                user = scripts[sid]["SubConfigsInfo"]["UserData"][body["userId"]]
                self._merge(user, body.get("data") or {}, "MaaUserConfig")
                return {"code": 200, "status": "success", "message": ""}
            return {"code": 500, "status": "error", "message": f"not in the fake: {path}"}

        @staticmethod
        def _merge(node: dict, data: dict, cls: str) -> None:
            for group, items in data.items():
                for key, value in items.items():
                    try:
                        v = S.validator_for(cls, f"{group}.{key}")
                    except (KeyError, ValueError):
                        v = None
                    node.setdefault(group, {})[key] = value if v is None or v.validate(value) else v.correct(value)


    # ---------- the tree the relay sees ----------

    TMP = tmpdir()
    BACKEND = _Backend()
    AUTOMAS = TMP / "AUTO-MAS"
    STATE = TMP / "state"
    os.environ.update(ARK_STATE_DIR=str(STATE), ARK_AUTOMAS_DIR=str(AUTOMAS),
                      ARK_MAS_PORT=str(BACKEND.port), SERVERCHAN_KEY="", ARK_LLM_KEY="")
    MAA_TREES = {name: S.make_maa_install(TMP / f"maa-{name}", yw)
                 for name, yw in (("tag", None), ("morning", "c09d3fe7"), ("evening", "cc780293"))}


    def _script_config_file() -> Path:
        return AUTOMAS / "config" / "ScriptConfig.json"


    def _start(cfg: dict, maa: str = "tag") -> bytes:
        """Backend and file both hold `cfg`; MAA is the named tree. Returns the file's bytes."""
        BACKEND.reset(cfg)
        f = _script_config_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8")
        os.environ["ARK_MAA_DIR"] = str(MAA_TREES[maa])
        return f.read_bytes()


    def _file(before: bytes) -> str:
        return "untouched" if _script_config_file().read_bytes() == before else "rewritten"


    def _with_user(**info) -> dict:
        cfg = copy.deepcopy(SCRIPT_CONFIG)
        ud = cfg[MAA_SID]["SubConfigsInfo"]["UserData"]
        ud[ud["instances"][0]["uid"]]["Info"].update(info)
        return cfg


    def _module(*names: str):
        """The first of `names` this tree has (modules moved on 2026-10-11)."""
        for name in names:
            try:
                mod = importlib.import_module(name)
            except ModuleNotFoundError as exc:
                if exc.name and name.startswith(exc.name):
                    continue
                raise
            if hasattr(mod, "MAS_API"):   # trees before config.mas_base() read a constant
                mod.MAS_API = f"http://127.0.0.1:{BACKEND.port}"
            return mod
        return None


    def _commands():
        return _module("ark_relay.features.phone.commands", "ark_relay.commands")


    def _quiet(fn, *a, **k):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = fn(*a, **k)
        return result, out.getvalue()


    # ---------- cases ----------

    def case_pin() -> None:
        for pin in S.PINS:
            check(f"pinned files match SOURCE.txt: {pin.name}", S.pin_problems(pin), [])
        for (repo, path, fn), want in PINNED_BODIES.items():
            body = S.cpp_body(path, fn) if repo == "maa" else S.py_body(path, fn)
            check(f"upstream body unchanged: {path} {fn}", S.body_sha(body), want)
        for path, lines in PRINTED.items():
            text = S.maa_text(path)
            check(f"MAA prints drop lines as collector_maa reads them: {path}",
                  [ln for ln in lines if ln not in text], [])


    def case_yw4() -> None:
        commands = _commands()
        before = _start(_with_user(Stage="1-7"), "morning")
        ok, msg = commands._set_stage("YW-4")
        check("YW-4 on the 10-10 morning tree: refused (" + EVIDENCE["yw4_refused"][:60] + "...)", ok, False)
        check("YW-4 on the 10-10 morning tree: nothing sent to AUTO-MAS", BACKEND.updates(), [])
        check("YW-4 on the 10-10 morning tree: AUTO-MAS still has 1-7", BACKEND.user()["Info"]["Stage"], "1-7")
        check("YW-4 on the 10-10 morning tree: ScriptConfig.json untouched", _file(before), "untouched")
        if ok:
            print(f"      reply: {msg}")

        _start(_with_user(Stage="1-7"), "evening")
        ok, msg = commands._set_stage("YW-4")
        require("YW-4 once YW.json has it (10-11): accepted", ok, msg)
        check("YW-4 once YW.json has it (10-11): AUTO-MAS now has YW-4", BACKEND.user()["Info"]["Stage"], "YW-4")


    def case_annihilation() -> None:
        _commands()   # the backend client the old annihilation module borrows
        old = _module("ark_relay.annihilation")
        STATE.mkdir(parents=True, exist_ok=True)
        before = _start(_with_user(Annihilation="Close"))
        if old is not None and hasattr(old, "WeeklyGate") and hasattr(old.WeeklyGate, "maybe_reopen"):
            (STATE / "annihilation.json").write_text(json.dumps(
                {"done_week": "2026-W35", "restore_to": "Annihilation"}), encoding="utf-8")
            sh = timezone(timedelta(hours=8))
            writer = "annihilation.WeeklyGate.maybe_reopen at 2026-08-31 04:01"
            _quiet(old.WeeklyGate(STATE, AUTOMAS).maybe_reopen, datetime(2026, 8, 31, 4, 1, tzinfo=sh))
        else:
            handover = importlib.import_module("automas_handover")
            (STATE / "state.json").write_text(json.dumps({"weekly": {"annihilation": {
                "done_week": "2026-W35", "restore_to": "Annihilation"}}}), encoding="utf-8")
            writer = "relay/handover step 13"
            _quiet(handover.plan, STATE, TMP / "okww", False, True, ["13"])
        sent = [b.get("data") for p, b in BACKEND.updates() if p == "/api/scripts/user/update"]
        check(f"{writer}: Info.Annihilation sent to the running AUTO-MAS ({EVIDENCE['washout'][:50]}...)",
              sent, [{"Info": {"Annihilation": "Annihilation"}}])
        check(f"{writer}: ScriptConfig.json untouched while AUTO-MAS runs", _file(before), "untouched")
        check(f"{writer}: AUTO-MAS holds Annihilation", BACKEND.user()["Info"]["Annihilation"], "Annihilation")


    def _field_ok(label: str, cls: str, field: str, value, reads: dict) -> None:
        try:
            v = S.validator_for(cls, field)
        except KeyError:
            require(f"{label}: {field} is declared on AUTO-MAS {cls}", False, "not declared")
            return
        require(f"{label}: {field}={value!r} passes AUTO-MAS's {type(v).__name__}", v.validate(value))
        require(f"{label}: {field} is read by AUTO-MAS", field in reads, "no reader in " + ", ".join(S.READERS))


    def _sent_fields(path_suffix: str) -> list[tuple[str, object]]:
        out = []
        for p, b in BACKEND.updates():
            if p.endswith(path_suffix):
                for group, items in (b.get("data") or {}).items():
                    out += [(f"{group}.{k}", v) for k, v in items.items()]
        return out


    def case_user() -> None:
        commands = _commands()
        reads = S.automas_reads()
        for label, call in (("set_stage 1-7 (" + EVIDENCE["one_seven"][:40] + "...)", lambda: commands._set_stage("1-7")),
                            ("set_medicine 0", lambda: commands._set_medicine(0)),
                            ("set_medicine 999", lambda: commands._set_medicine(999))):
            before = _start(_with_user(Stage="YW-4", MedicineNumb=5), "tag")
            ok, msg = call()
            require(f"{label}: accepted", ok, msg)
            fields = _sent_fields("/user/update")
            require(f"{label}: one field sent", len(fields) == 1, repr(fields))
            for field, value in fields:
                _field_ok(label, "MaaUserConfig", field, value, reads)
            check(f"{label}: ScriptConfig.json untouched", _file(before), "untouched")

        # Probes at AUTO-MAS's own range ends: whatever set_medicine lets through must be a
        # value AUTO-MAS keeps (out of range it would quietly clamp it: RangeValidator.correct).
        v = S.validator_for("MaaUserConfig", "Info.MedicineNumb")
        for n in (v.min - 1, v.min, v.max, v.max + 1):
            _start(_with_user(MedicineNumb=5), "tag")
            ok, _ = commands._set_medicine(n)
            sent = [value for field, value in _sent_fields("/user/update") if field == "Info.MedicineNumb"]
            require(f"set_medicine {n}: sends only what AUTO-MAS keeps", all(v.validate(x) for x in sent),
                    f"sent {sent}")


    class _Clock(datetime):
        """datetime whose now() is AT (a virtual clock for both sides)."""
        AT = datetime(2026, 1, 1, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.AT.astimezone(tz) if tz else cls.AT


    def case_handover() -> None:
        handover = importlib.import_module("automas_handover")
        reads = S.automas_reads()
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / "state.json").write_text(json.dumps({"weekly": {"annihilation": {
            "done_week": "2026-W35", "restore_to": "Annihilation"}}}), encoding="utf-8")
        _start(_with_user(Annihilation="Close"))
        BACKEND.cfg[MAA_SID]["Run"].update(IfCheckGameUpdate=False, IfAutoInstallGameApk=False)
        _quiet(handover.plan, STATE, TMP / "okww", False, True, ["13", "10a"])
        user_fields = _sent_fields("/user/update")
        script_fields = _sent_fields("/scripts/update")
        check("handover: user fields written", sorted(f for f, _ in user_fields), ["Info.Annihilation"])
        check("handover: script fields written", sorted(f for f, _ in script_fields),
              ["Run.IfAutoInstallGameApk", "Run.IfCheckGameUpdate"])
        for field, value in user_fields:
            _field_ok("handover", "MaaUserConfig", field, value, reads)
        for field, value in script_fields:
            _field_ok("handover", "MaaConfig", field, value, reads)
        _field_ok("handover", "MaaUserConfig", "Data.AnnihilationCompletedWeek", handover.this_week(), reads)

        proxy = S.load_upstream("app/task/MAA/AutoProxy.py", ["_current_week_marker"], {"datetime": datetime})
        const = S.load_upstream("app/utils/constants.py", ["UTC4", "ARKNIGHTS_GAME_DAY_TZ", "get_game_day_tz", "game_now"],
                                {"timezone": timezone, "timedelta": timedelta, "datetime": _Clock})
        weekly = _module("ark_relay.features.weekly.annihilation", "ark_relay.annihilation")
        sh = timezone(timedelta(hours=8))
        real = handover.datetime
        handover.datetime = _Clock
        try:
            for at in (datetime(2026, 8, 31, 3, 59, tzinfo=sh), datetime(2026, 8, 31, 4, 0, tzinfo=sh),
                       datetime(2026, 10, 18, 23, 59, tzinfo=sh), datetime(2026, 12, 28, 4, 0, tzinfo=sh),
                       datetime(2027, 1, 4, 3, 59, tzinfo=sh), datetime(2027, 1, 4, 4, 0, tzinfo=sh)):
                _Clock.AT = at
                want = proxy["_current_week_marker"](const["game_now"]("Official"))
                check(f"week marker {at:%Y-%m-%d %H:%M} Beijing: handover writes AUTO-MAS's", handover.this_week(), want)
                check(f"week marker {at:%Y-%m-%d %H:%M} Beijing: the relay's reader agrees", weekly.week_key(at), want)
        finally:
            handover.datetime = real


    def case_guinew() -> None:
        mcfg = _module("ark_relay.core.mastercfg_maa", "ark_relay.mastercfg")
        infrast_cs = "src/MaaWpfGui/Configuration/Single/MaaTask/InfrastTask.cs"
        award_cs = "src/MaaWpfGui/Configuration/Single/MaaTask/AwardTask.cs"
        check("drone values = MAA's UsesOfDronesList", [k for k, _ in mcfg.MAA_DRONES], S.drone_keys())
        check("UsesOfDrones is a string property of InfrastTask", S.cs_properties(infrast_cs).get("UsesOfDrones"), "string")
        drones = S.core_param("src/MaaWpfGui/Models/AsstTasks/AsstInfrastTask.cs", "UsesOfDrones")
        require(f"MaaCore's Infrast reads {drones!r}",
                drones in S.core_reads("src/MaaCore/Task/Interface/InfrastTask.cpp"), "not read")
        award_reads = S.core_reads("src/MaaCore/Task/Interface/AwardTask.cpp")
        for key, _ in mcfg.MAA_AWARD:
            check(f"Award/{key} is a bool property of AwardTask", S.cs_properties(award_cs).get(key), "bool")
            param = S.core_param("src/MaaWpfGui/Models/AsstTasks/AsstAwardTask.cs", key)
            require(f"Award/{key} reaches MaaCore as {param!r}", param in award_reads, "not read")

        const = S.load_upstream("app/utils/constants.py", ["MAA_TASKS", "MAA_TASKS_ZH"], {})
        zh = dict(zip(const["MAA_TASKS"], const["MAA_TASKS_ZH"], strict=True))
        preset = S.load_upstream("app/task/MAA/base_preset.py", ["maa_task_identity"], {})
        proxy = S.load_upstream("app/task/MAA/AutoProxy.py", ["_find_task_source"],
                                {"deepcopy": copy.deepcopy, "maa_task_identity": preset["maa_task_identity"]})
        copy_source = S.load_method("app/task/MAA/AutoProxy.py", "AutoProxyTask._copy_source_config",
                                    {"shutil": shutil, "Path": Path,
                                     "logger": types.SimpleNamespace(info=lambda *a, **k: None)})
        user = SCRIPT_CONFIG[MAA_SID]["SubConfigsInfo"]["UserData"]
        mode = user[user["instances"][0]["uid"]]["Info"]["Mode"]
        require("the machine's MAA user takes its config from the script folder (Info.Mode 脚本)",
                mode == "脚本" and 'f"data/{self.script_info.script_id}/Default/ConfigFile"'
                in S.automas_text("app/task/MAA/AutoProxy.py"), mode)
        derived = S.derived_types()

        writes = [("Infrast/UsesOfDrones", "Infrast", "UsesOfDrones", v) for v in S.drone_keys()]
        writes += [(f"Award/{k}", "Award", k, flip) for k, _ in mcfg.MAA_AWARD for flip in (False, True)]
        for path, task_type, key, value in writes:
            root = TMP / "guinew" / f"{path.replace('/', '-')}-{value}"
            master = root / "AUTO-MAS" / "data" / MAA_SID / "Default" / "ConfigFile"
            maa_config = root / "MAA" / "config"
            for d in (master, maa_config):
                d.mkdir(parents=True)
                (d / "gui.new.json").write_bytes(GUI_NEW)
            ok, msg = mcfg.write_maa(root / "AUTO-MAS", root / "MAA", path, value)
            require(f"write_maa {path}={value!r}: accepted", ok, msg)
            (maa_config / "gui.new.json").write_bytes(GUI_NEW)   # AUTO-MAS overwrites MAA's own copy anyway
            copy_source(types.SimpleNamespace(maa_set_path=maa_config), master)
            doc = json.loads((maa_config / "gui.new.json").read_text(encoding="utf-8"))
            queue = doc["Configurations"][doc["Current"]]["TaskQueue"]
            task = proxy["_find_task_source"](queue, zh[task_type], task_type) or {}
            check(f"{path}={value!r}: AUTO-MAS hands MAA the value", task.get(key), value)
            require(f"{path}={value!r}: under a $type MAA deserialises", task.get("$type") in derived, task.get("$type"))
            want = json.loads(GUI_NEW)
            for t in want["Configurations"][want["Current"]]["TaskQueue"]:
                if t.get("TaskType") == task_type:
                    t[key] = value
            check(f"{path}={value!r}: nothing else in gui.new.json changed", doc, want)


    CASES = {"pin": case_pin, "yw4": case_yw4, "annihilation": case_annihilation,
             "user": case_user, "handover": case_handover, "guinew": case_guinew}


    def main() -> int:
        logging.disable(logging.WARNING)
        for name in sys.argv[1:] or list(CASES):
            print(f"[{name}]")
            CASES[name]()
        BACKEND.srv.shutdown()
        if fails:
            print(f"FAIL: {len(fails)} check(s): " + "; ".join(fails[:6]))
            return 1
        print("all checks passed")
        return 0


    if __name__ == "__main__":
        sys.exit(main())


def _part_gl_maaend_config():  # noqa: C901 - the whole body of the file this part was
    """T11: every MaaEnd option the relay writes is one the installed MaaEnd defines,
and survives MXU's load unchanged.

Judged only against upstream (gamesim/upstream/, see gamesim/lib/maaend_schema.py):
MaaEnd's own definition files at the installed tag and the MXU source MXU@2.7.1
runs. MXU's load and run rules are ported from TypeScript; the ports are first
checked against MXU's own output on the machine (section A), so every later
verdict rests on a log line, not on the relay's code:

A  ports match the machine
   - MXU load warnings: master 09-10 under v2.28.0-beta.5 gives exactly the 39
     「已不存在，已丢弃保存值」 lines of fixtures/maaend-2026-09-10/app-2026-09-10-4.log;
     master 10-10 under v2.32.0 the 6 「类型已从 "checkbox" 变更为 "switch"」 lines
     of fixtures/maaend-2026-10-10/app-2026-10-10-3.log.
   - pipeline overrides: the same masters give byte-for-byte the
     `entry=..., pipelineOverride=[...]` lines MXU logged (AutoCollectSchedule
     09-10; AutoStockStapleSchedule and DailyRewardStart 10-10).
B  [ca3ba0d5] the relay's definition index holds every task MaaEnd declares and
   calls no task an orphan that MXU keeps (09-10: CreditShopping.json's
   `"enabled": false //...` hid CreditShoppingN2); [2367548d] MXU's own
   __MXU_*__ entries are never orphans.
C  [a210327f] the relay's index holds every option definition exactly as MaaEnd
   wrote it (the trailing-comma regex turned AutoStockStaple's `\\d{6,}` into
   `\\d{6}`, so a reserve of 12000000 was refused).
D  [258d7847] after the relay's boot migration the 09-10 master loads in MXU
   with no warning on its tasks (09-10: 36 「已丢弃保存值」, ran nothing);
   [85ac4eb8] nor on recentlyClosed (09-10 16:42: 33 「已不存在」);
   [76df1839] the 10-10 master under v2.32.0 loads clean and each 自动囤货 buy
   list is carried into its new switch + Items checkbox (10-03..10-10 bought
   the defaults). Both masters also migrate clean to the installed tag.
E  write_maaend round trip on the installed tag: every value MaaEnd declares for
   the sanity_sink tasks' options is accepted, read back equal, and kept by MXU
   unchanged; an undeclared case (RewardsSetA) is refused and the file untouched.
F  [8ed7f476] sanity_plan: its tab/line/location/reward tables name only cases
   the installed tag declares and cover every reward case; set_plan with each
   declared plan writes values MXU keeps and that the run actually reads
   (pipeline resolver); "RewardsSetA" never reaches the file.
G  prune, makeup, collect_retry and mastercfg's migration constants name only
   tasks, options, cases and pipeline nodes the installed tag defines.

Old code runs this file too (the red-before-green proofs): modules are imported
from where they lived then, and a missing function is reported as a failed case.

    Formerly test_gl_maaend_config.py.
    """

    import collections
    import hashlib
    import importlib
    import inspect
    import json
    import re

    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE / "gamesim" / "lib"))

    import maaend_schema as ms

    FX = HERE / "fixtures"
    MASTER_0910 = FX / "maaend-2026-09-10" / "master-before.json"
    MASTER_1010 = FX / "maaend-2026-10-10" / "master-before.json"
    LOG_0910 = FX / "maaend-2026-09-10" / "app-2026-09-10-4.log"
    LOG_1010 = FX / "maaend-2026-10-10" / "app-2026-10-10-3.log"
    V0910, V1010 = "v2.28.0-beta.5", "v2.32.0"   # 「当前版本」 in those two logs

    # sha256 of the MXU code each port follows (maaend_schema.PORTS), at MXU v2.7.1.
    PORT_PINS = {
        "createDefaultOptionValue": "a7c8bfd416c6b440",
        "sanitizeOptionValue": "47b594f0e7643250",
        "sanitizeOptionValues": "f0b5807cf20204f9",
        "YES/NO case names": "7ddee5fa82636db2",
        "findSwitchCase": "b5c4547b383dcd57",
        "convertHotkeyKeyName": "a9a793fd7b67f095",
        "splitHotkeyCombo": "fb160ac4e67b01b4",
        "collectOptionOverrides": "fcd18f3f8f6cfc2c",
        "generateTaskPipelineOverride": "64daf60f1cd1289c",
        "mergeImported": "a68d7ccf80b72618",
        "cleanOptionValues": "48cff5c7c85660d8",
        "load: valid task names": "d4433f61ef5c09f9",
        "load: recentlyClosed": "b8c24ff83d9b53be",
        "cacheTaskEnabledForController": "b4ffde4802a1c9c4",
        "load: task flags": "568ec765bb15c733",
        "save: task flags": "ba3f8fc6aacf54df",
    }

    FAILED: list[str] = []


    def require(name: str, ok: bool, detail: object = "") -> None:
        """`name` starts with its case in brackets, e.g. "[D 76df1839] ..."."""
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": {detail}"))
        if not ok:
            FAILED.append(name)


    def _import(*names: str):
        for n in names:
            try:
                return importlib.import_module(n)
            except ImportError:
                continue
        return None


    mastercfg = _import("ark_relay.core.mastercfg", "ark_relay.mastercfg")
    sanity_plan = _import("ark_relay.features.weekly.sanity_plan", "ark_relay.sanity_plan")
    collect_retry = _import("ark_relay.features.makeup.collect_retry", "ark_relay.collect_retry")
    makeup = _import("ark_relay.features.makeup.makeup", "ark_relay.makeup")

    # Each definition file is parsed once per content by the relay's own `_jsonc`
    # and the result handed back on every later read of the same bytes. The relay
    # reparses the whole install (5 MB) on each write_maaend call; without this the
    # file would not fit gate 0's 10 s. The returned value is exactly what `_jsonc`
    # returned for those bytes, and section B/C compare it with MaaEnd's files.
    _REAL_JSONC = mastercfg._jsonc
    _BY_CONTENT: dict[str, object] = {}
    _PATH_KEY: dict[tuple, str] = {}


    def _jsonc_once(path):
        st = Path(path).stat()
        pk = (str(path), st.st_mtime_ns, st.st_size)
        key = _PATH_KEY.get(pk)
        if key is None:
            key = _PATH_KEY[pk] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if key not in _BY_CONTENT:
            _BY_CONTENT[key] = _REAL_JSONC(path)
        return _BY_CONTENT[key]


    mastercfg._jsonc = _jsonc_once


    def defs_dir(version: str) -> Path:
        """A full install-shaped copy of a stored tag (the relay reads a directory)."""
        return ms.materialize(ms.UPSTREAM / f"maaend-{version}", tmpdir("gl-maaend-defs-"))


    DIRS = {v: defs_dir(v) for v in (V0910, V1010, ms.INSTALLED)}
    DEFS = {v: ms.Defs(d) for v, d in DIRS.items()}
    INST = DEFS[ms.INSTALLED]


    def workspace(master: "Path | dict") -> "tuple[Path, Path]":
        """(AUTO-MAS dir, master file) laid out as on the machine."""
        automas = tmpdir("gl-maaend-") / "automas"
        cfg = automas / "data" / "59da8762" / "Default" / "ConfigFile"
        cfg.mkdir(parents=True)
        f = cfg / "mxu-MaaEnd.json"
        doc = master if isinstance(master, dict) else json.loads(Path(master).read_text(encoding="utf-8"))
        f.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return automas, f


    def load(f: Path) -> dict:
        return json.loads(f.read_text(encoding="utf-8"))


    def task_of(doc: dict, name: str) -> dict:
        return next(t for t in doc["instances"][0]["tasks"] if t.get("taskName") == name)


    def warnings(doc: dict, defs: ms.Defs, part: str = "all") -> list[str]:
        """MXU's load warnings for one part of the config: "instances",
    "recentlyClosed" or "all"."""
        keep = {"instances": ("instances",), "recentlyClosed": ("recentlyClosed",)}.get(
            part, ("instances", "recentlyClosed", "globalOptionValues"))
        return ms.mxu_load({k: v for k, v in doc.items() if k in keep or k not in
                            ("instances", "recentlyClosed", "globalOptionValues")}, defs)


    def migrated(master: Path, version: str) -> "tuple[Path, Path, list]":
        """The master after the relay's boot migration against `version` (as is
    when this relay has no migration)."""
        automas, f = workspace(master)
        fn = getattr(mastercfg, "migrate_maaend_options", None)
        changes = fn(automas, DIRS[version])[0] if fn else []
        return automas, f, changes


    def run(case: str, section) -> None:
        """Run one section; an exception (old code lacking a function) fails that case."""
        try:
            section()
        except Exception as exc:  # noqa: BLE001 - any error is this case's failure, reported
            require(f"[{case}] {section.__name__} ran", False, f"{type(exc).__name__}: {exc}")


    print("[pins: the stored upstream files are unedited; MXU's ported code is unchanged]")
    for d in sorted(ms.UPSTREAM.iterdir()):
        if d.is_dir() and d.name.startswith(("maaend-", "mxu-")):
            require(f"[pin] {d.name} matches its SOURCE.txt", not ms.verify(d), ms.verify(d)[:3])
    require("[pin] the installed tag is stored", ms.INSTALLED_DIR.is_dir(), ms.INSTALLED_EVIDENCE)
    for name, want in PORT_PINS.items():
        got = hashlib.sha256(ms.port_region(name).encode("utf-8")).hexdigest()[:16]
        require(f"[pin] MXU {name} unchanged", got == want, f"{got} != {want}: re-read the port")
    for v, d in DEFS.items():
        require(f"[pin] {v}: no option or task declared twice", not d.dup_options and not d.dup_tasks,
              (d.dup_options, d.dup_tasks))


    def ports_match_the_machine() -> None:
        print("[A: the MXU ports reproduce MXU's own log lines]")
        for master, log, v in ((MASTER_0910, LOG_0910, V0910), (MASTER_1010, LOG_1010, V1010)):
            got = collections.Counter(ms.mxu_load(json.loads(master.read_text(encoding="utf-8")), DEFS[v]))
            want = collections.Counter(ms.mxu_warnings(log.read_text(encoding="utf-8")))
            require(f"[A] {master.parent.name} under {v}: {sum(want.values())} load warnings as logged",
                  got == want, (got - want, want - got))
        for master, log, v, entries in (
                (MASTER_0910, LOG_0910, V0910, ("AutoCollectSchedule",)),
                (MASTER_1010, LOG_1010, V1010, ("AutoStockStapleSchedule", "DailyRewardStart"))):
            doc = json.loads(master.read_text(encoding="utf-8"))
            inst = doc["instances"][0]
            logged = ms.logged_overrides(log.read_text(encoding="utf-8"))
            res = ms.Resolver(DEFS[v])
            for t in inst["tasks"]:
                entry = (DEFS[v].tasks.get(t.get("taskName")) or {}).get("entry")
                if entry in entries:
                    got, _ = res.task(t, inst["controllerName"], inst["resourceName"], doc.get("globalOptionValues"))
                    require(f"[A] {v} {entry}: pipeline override as MXU logged it", got == logged[entry],
                          f"{len(got)} vs {len(logged[entry])} parts")


    def index_and_orphans() -> None:
        print("[B: the relay's definition index and orphan list match MaaEnd and MXU]")
        for v in (V0910, ms.INSTALLED):
            _opts, tasks = mastercfg._maaend_defs(DIRS[v])
            missing = sorted(set(DEFS[v].tasks) - set(tasks))
            require(f"[B ca3ba0d5] {v}: every task MaaEnd declares is indexed", not missing, missing)
        doc = json.loads(MASTER_0910.read_text(encoding="utf-8"))
        dropped = [w for w in ms.mxu_load(doc, DEFS[V0910]) if "无效任务" in w]
        automas, _ = workspace(MASTER_0910)
        orphans = mastercfg.read_maaend(automas, DIRS[V0910]).get("orphans") or []
        special = ms.special_task_names()
        require("[B 2367548d] no MXU built-in task is called an orphan",
              not [o for o in orphans if o in special], orphans)
        require("[B ca3ba0d5] orphans are exactly the tasks MXU drops (none on 09-10)",
              orphans == [] and dropped == [], (orphans, dropped))


    def definitions_intact() -> None:
        print("[C: option definitions reach the relay exactly as MaaEnd wrote them]")
        for v in (V0910, ms.INSTALLED):
            opts, _ = mastercfg._maaend_defs(DIRS[v])
            bad = sorted(k for k, d in DEFS[v].options.items() if opts.get(k) != d)
            require(f"[C a210327f] {v}: all {len(DEFS[v].options)} option definitions identical", not bad, bad[:5])
        automas, f = migrated(MASTER_0910, ms.INSTALLED)[:2]
        box = INST.options["AutoStockReserveWuling"]["inputs"][0]
        for value in ("12000000", "240000", "1000", "abc"):
            want = bool(re.fullmatch(box["verify"], value))
            ok, why = mastercfg.write_maaend(automas, DIRS[ms.INSTALLED], "AutoStockStaple/AutoStockReserveWuling", value)
            require(f"[C a210327f] reserve {value}: written={ok}, MaaEnd's verify says {want}", ok == want, why)


    def migration() -> None:
        print("[D: after the relay's migration MXU loads the master without a warning]")
        _, f, _ = migrated(MASTER_0910, V0910)
        doc = load(f)
        require(f"[D 258d7847] 09-10 master under {V0910}: tasks load clean",
              not warnings(doc, DEFS[V0910], "instances"), warnings(doc, DEFS[V0910], "instances")[:3])
        require(f"[D 85ac4eb8] 09-10 master under {V0910}: recentlyClosed loads clean",
              not warnings(doc, DEFS[V0910], "recentlyClosed"), len(warnings(doc, DEFS[V0910], "recentlyClosed")))
        old = task_of(json.loads(MASTER_1010.read_text(encoding="utf-8")), "AutoStockStaple")["optionValues"]
        lists = {k: v["caseNames"] for k, v in old.items() if v.get("type") == "checkbox"
                 and DEFS[V1010].kind(k) == "switch"}
        _, f, _ = migrated(MASTER_1010, V1010)
        doc = load(f)
        require(f"[D 76df1839] 10-10 master under {V1010}: loads clean", not warnings(doc, DEFS[V1010]),
              warnings(doc, DEFS[V1010])[:3])
        inst = doc["instances"][0]
        _, reached = ms.Resolver(DEFS[V1010]).task(task_of(doc, "AutoStockStaple"), inst["controllerName"],
                                                   inst["resourceName"], doc.get("globalOptionValues"))
        for key, picked in lists.items():
            on = reached.get(key) == {"type": "switch", "value": bool(picked)}
            items = (reached.get(key + "Items") or {}).get("caseNames") if picked else []
            require(f"[D 76df1839] {key}: run reads switch {'on' if picked else 'off'} and the {len(picked)} picks",
                  on and items == picked, (reached.get(key), items))
        for master in (MASTER_0910, MASTER_1010):
            automas, f, _ = migrated(master, ms.INSTALLED)
            doc = load(f)
            require(f"[D] {master.parent.name} migrated to {ms.INSTALLED}: loads clean",
                  not warnings(doc, INST), warnings(doc, INST)[:3])
            again = mastercfg.migrate_maaend_options(automas, DIRS[ms.INSTALLED])[0]
            require(f"[D] {master.parent.name}: a second migration changes nothing", again == [], again)


    def _values(od: dict) -> list:
        """Every value MaaEnd declares for an option, in write_maaend's input shape."""
        kind = od.get("type") or "select"
        names = [str(c["name"]) for c in od.get("cases") or []]
        if kind == "select":
            return names
        if kind == "switch":
            return [True, False]
        if kind == "checkbox":
            return [[n] for n in names] + ([names] if len(names) > 1 else [])
        if kind == "input":
            boxes = od.get("inputs") or []
            if len(boxes) == 1:
                return [str(boxes[0].get("default") or "")]
            return [{b["name"]: str(b.get("default") or "") for b in boxes}]
        return []


    def _shape(kind: str, value) -> dict:
        if kind == "select":
            return {"type": "select", "caseName": value}
        if kind == "switch":
            return {"type": "switch", "value": value}
        if kind == "checkbox":
            return {"type": "checkbox", "caseNames": value}
        return {"type": "input"}


    def write_round_trip() -> None:
        print("[E: write_maaend round trip on the installed tag]")
        automas, f, _ = migrated(MASTER_0910, ms.INSTALLED)
        sinks = [n for n, t in INST.tasks.items() if "sanity_sink" in (t.get("group") or [])]
        tree = getattr(mastercfg, "MAAEND_TREE_TASKS", ())
        require("[E] the relay's tree tasks are MaaEnd's sanity_sink tasks", set(tree) <= set(sinks), (tree, sinks))
        last: dict = {}
        bad: list = []
        count = 0
        for task in sinks:
            for opt in sorted(ms.option_tree(INST, task) - set(INST.global_option)):
                od = INST.options.get(opt) or {}
                kind = od.get("type") or "select"
                for value in _values(od):
                    ok, why = mastercfg.write_maaend(automas, DIRS[ms.INSTALLED], f"{task}/{opt}", value)
                    count += 1
                    entry = (task_of(load(f), task).get("optionValues") or {}).get(opt)
                    problem = None if ok else why
                    if ok and kind != "input" and entry != _shape(kind, value):
                        problem = f"read back {entry!r}"
                    if ok and kind == "input":
                        want = value if isinstance(value, dict) else {(od.get("inputs") or [{}])[0].get("name"): value}
                        if {k: (entry or {}).get("values", {}).get(k) for k in want} != want:
                            problem = f"read back {entry!r}"
                    if ok and not problem:
                        problem = ms.entry_check(INST, task, opt, entry)
                    if problem:
                        bad.append((f"{task}/{opt}", value, problem))
                    else:
                        last[f"{task}/{opt}"] = value
        require(f"[E] {count} declared values written, read back, kept by MXU", not bad, bad[:4])
        shown = mastercfg.read_maaend(automas, DIRS[ms.INSTALLED]).get("values") or {}
        differ = [k for k, v in last.items() if k in shown and shown[k] != v and not isinstance(v, dict)]
        require("[E] read_maaend shows the last value written", not differ, differ[:4])
        require("[E] nothing written makes MXU warn", not warnings(load(f), INST), warnings(load(f), INST)[:3])
        before = f.read_bytes()
        ok, why = mastercfg.write_maaend(automas, DIRS[ms.INSTALLED], "ProtocolSpace/OperatorEXPRewardsSetOption",
                                         "RewardsSetA")
        require("[E] an undeclared case (RewardsSetA) is refused, file untouched",
              not ok and f.read_bytes() == before, why)


    def _set_plan(automas, tab, line, rset):
        kw = {}
        if "maaend_dir" in inspect.signature(sanity_plan.set_plan).parameters:
            kw["maaend_dir"] = DIRS[ms.INSTALLED]
        return sanity_plan.set_plan(automas, tab, line, rset, **kw)


    def sanity_plan_writes() -> None:
        print("[F: sanity_plan names MaaEnd's cases and its writes take effect]")
        tabs = INST.cases("ProtocolSpaceTab")
        labels = getattr(sanity_plan, "TAB_LABELS", {})
        require("[F] every ProtocolSpace tab sanity_plan offers is a ProtocolSpaceTab case",
              set(labels) - {"Essence"} <= set(tabs), sorted(set(labels) - {"Essence"} - set(tabs)))
        lines = getattr(sanity_plan, "LINE_OPTIONS", {})
        wrong = sorted((t, x) for t, xs in lines.items() for x in xs if x not in INST.cases(t))
        require("[F] every line sanity_plan offers is a case of its tab", not wrong, wrong)
        locs = getattr(sanity_plan, "LOCATION_LABELS", {})
        require("[F] every essence location sanity_plan names is a case",
              set(locs) <= set(INST.cases("AutoEssenceChooseLocation")),
              sorted(set(locs) - set(INST.cases("AutoEssenceChooseLocation"))))
        declared = {(line, c) for t in tabs for line in INST.cases(t) for c in INST.cases(f"{line}RewardsSetOption")}
        table = set(getattr(sanity_plan, "REWARD", {}))
        require("[F 8ed7f476] the reward table holds exactly the declared (line, reward case) pairs",
              table == declared, (sorted(table - declared)[:4], sorted(declared - table)[:4]))
        automas, f, _ = migrated(MASTER_0910, ms.INSTALLED)
        res = ms.Resolver(INST)
        bad: list = []
        written = 0
        for tab in tabs:
            for line in INST.cases(tab):
                for rset in INST.cases(f"{line}RewardsSetOption") or [""]:
                    ov = task_of(load(f), "ProtocolSpace").get("optionValues") or {}
                    keys = ["ProtocolSpaceTab", tab] + ([f"{line}RewardsSetOption"] if rset else [])
                    before = f.read_bytes()
                    ok, why = _set_plan(automas, tab, line, rset)
                    if not ok:
                        if all(k in ov for k in keys) or f.read_bytes() != before:
                            bad.append((tab, line, rset, why))
                        continue
                    written += 1
                    doc = load(f)
                    inst = doc["instances"][0]
                    _, reached = res.task(task_of(doc, "ProtocolSpace"), inst["controllerName"],
                                          inst["resourceName"], doc.get("globalOptionValues"))
                    want = {"ProtocolSpaceTab": tab, tab: line} | ({f"{line}RewardsSetOption": rset} if rset else {})
                    got = {k: (reached.get(k) or {}).get("caseName") for k in want}
                    if got != want or warnings(doc, INST, "instances"):
                        bad.append((tab, line, rset, got, warnings(doc, INST, "instances")[:2]))
        require(f"[F 8ed7f476] set_plan with each declared plan writes what the run reads ({written} written)",
              written > 0 and not bad, bad[:3])
        _set_plan(automas, "OperatorProgression", "OperatorEXP", "RewardsSetA")
        require("[F 8ed7f476] set_plan(..., RewardsSetA) leaves nothing MXU rejects",
              not warnings(load(f), INST), warnings(load(f), INST)[:2])


    def other_writers() -> None:
        print("[G: prune, makeup, collect_retry and mastercfg constants name what MaaEnd defines]")
        automas, f, _ = migrated(MASTER_0910, ms.INSTALLED)
        removed, _ = mastercfg.prune_maaend_orphans(automas, DIRS[ms.INSTALLED])
        dropped = [w for w in ms.mxu_load(load(f), INST) if "无效任务" in w]
        require("[G] prune removes exactly what MXU would drop (nothing)", removed == [] and not dropped,
              (removed, dropped))
        require(f"[G] makeup's {makeup.STASH} is a MaaEnd task", makeup.STASH in INST.tasks)
        entry_task = collect_retry.ENTRY.replace("Schedule", "")
        require(f"[G] collect_retry's {collect_retry.ENTRY} is {entry_task}'s entry",
              (INST.tasks.get(entry_task) or {}).get("entry") == collect_retry.ENTRY)
        routes = sorted(o for o in ms.option_tree(INST, entry_task) if collect_retry._ROUTE_OPT.match(o))
        require(f"[G] collect_retry's {len(routes)} route lists are checkboxes",
              bool(routes) and all(INST.kind(o) == "checkbox" for o in routes), routes)
        rids = sorted(set(collect_retry.failed_labels_from_locale(INST.zh).values()))
        logged = ms.logged_overrides(LOG_1010.read_text(encoding="utf-8"))[collect_retry.ENTRY]
        for v, nodes_of in ((V1010, logged), (ms.INSTALLED, logged)):
            built = collect_retry.build_override(nodes_of, rids, "monday")
            # ArkRelay* nodes are the relay's own, defined whole in the override (collect_retry.OBSTACLE_COMBAT_WAIT);
            # every node they and the rest name must still be MaaEnd's
            own = {n for n in built if n.startswith("ArkRelay")}
            missing = sorted(ms.override_nodes(built) - DEFS[v].nodes - own)
            require(f"[G] {v}: retry override for all {len(rids)} routes names only pipeline nodes",
                  bool(rids) and not missing, missing[:5])
        split = getattr(mastercfg, "_COLLECT_SPLIT", {})
        bad = [n for old, news in split.items() if old not in INST.options for n in news if INST.kind(n) != "checkbox"]
        require("[G] the gathering-split targets are checkboxes", not bad, bad)
        for opt, case in (("AutoCollectMode", "Always"), ("AutoEssenceMenu", "Random"),
                          ("AutoUseSpMedication", "UseMedication")):
            require(f"[G] migration's {opt}={case} is a declared case (when the option exists)",
                  opt not in INST.options or case in INST.cases(opt), INST.cases(opt))


    run("A", ports_match_the_machine)
    run("B", index_and_orphans)
    run("C", definitions_intact)
    run("D", migration)
    run("E", write_round_trip)
    run("F", sanity_plan_writes)
    run("G", other_writers)

    opts_after, _ = mastercfg._maaend_defs(DIRS[ms.INSTALLED])
    require("[pin] the parsed definitions were not changed by the code under test",
          opts_after == INST.options)

    if FAILED:
        print(f"\n{len(FAILED)} failed:")
        for name in FAILED:
            print("  " + name)
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    sys.exit(run_parts([_part_gl_lifecycle, _part_gl_log_contract, _part_gl_maa_config, _part_gl_maaend_config]))
