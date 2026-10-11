"""The machine side of deploy-relay.sh for the installed relay (packaging/ark-relay.iss).

The installed relay runs the version folder named in {app}\\current.txt
(relay/pkg_layout.py). A deploy never writes into the folder in use: the files go
into a new folder, which becomes current only once every hash matches, and going
back is pointing current.txt at the previous folder again. Run with the package's
own Python ({app}\\runtime\\python\\python.exe), the one the relay runs on.

    pkg_deploy.py info    <app> [<rel>...]   CUR=<folder in use>  STATEDIR=<relay state dir>
                                             CONSOLE=  WATCHDOG_SHA=  SHA <rel> <sha1> each
                                             RUNTIME_PY=<version>  RUNTIME_PKG <name>==<v> each
    pkg_deploy.py stage   <app>              INCOMING=<empty folder to extract into>
    pkg_deploy.py commit  <app>              hashes, then INCOMING -> versions\\<n>, current.txt
                                             -> it; NAME=<n> PREV=<old>; or MISMATCH ...
    pkg_deploy.py back    <app> <folder>     current.txt -> <folder>; CURRENT=<folder>
    pkg_deploy.py appfiles-stage <app>       APPFILES_IN=<empty folder to extract into>
    pkg_deploy.py appfiles <app> <rel>=<sha1>...
                                             the files in APPFILES_IN replace {app}\\<rel>
                                             (hash and compile checked first, the old ones
                                             kept); APPFILE <rel> each, APPFILES_OK <n>, or
                                             APPFILES_FAIL <why> with nothing changed
    pkg_deploy.py appfiles-back <app>        the files the last `appfiles` replaced put back
    pkg_deploy.py watchdog <app> <sha1> <file>
                                             <file> (packaging/watchdog/ark_watchdog.py, sent
                                             by the deploy) becomes {app}\\watchdog\\ark_watchdog.py
                                             and the service is restarted on it;
                                             WATCHDOG=unchanged / updated / disabled, or
                                             WATCHDOG_FAIL <why> (exit 1)

Everything it prints for the script is KEY=value on its own line.

The watchdog service lives outside the version folders ({app}\\watchdog), and until
2026-10-11 only the installer wrote it, so a watchdog fix (d0c0e12b, the shutdown push)
could ship only by running setup.exe again. `info` reports the installed file's sha1;
the deploy sends the file and runs `watchdog` only when that differs from the repo's.
The same holds for launch.py, switch.py, legacy.py and handover\\ (`appfiles`), and
`info` reports the runtime so the deploy can refuse code the runtime cannot run
(scripts/mac/lib/pkg_appfiles.py says why the runtime itself stays the installer's).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DATA = Path(r"C:\ProgramData\ark-relay")
INCOMING = ".incoming"
APPFILES_IN = ".appfiles-incoming"
APPFILES_PREV = ".appfiles-prev"       # what the last `appfiles` replaced, for appfiles-back
APPFILES_NEW = ".new-files"            # in APPFILES_PREV: rels that did not exist before
WATCHDOG = "ArkRelayWatchdog"
# packaging/switch.py WATCHDOG_MARKER, relay/watchdog_guard.py MARKER: written before a
# stop, so the relay's guard does not start the watchdog again meanwhile; deleted by
# every start. Not imported from {app}\switch.py: the installer writes that file, and
# the copy on the machine may predate the marker (added 10-11 09:12) - the same reason
# relay/watchdog_guard.py _start keeps its own copy of the start watch.
WATCHDOG_MARKER = DATA / "watchdog-stopped.txt"
WATCHDOG_STOP_S = 30
WATCHDOG_WAIT_S = 45       # switch.py WATCHDOG_WAIT_S: the SCM's start timeout is 30 s
WATCHDOG_STEADY_S = 5      # watchdog_guard.py STEADY_S: still RUNNING this long = it came up


def _layout(code: Path):
    """relay/pkg_layout.py from the given version folder (and its ark_relay)."""
    sys.path.insert(0, str(code))
    import pkg_layout  # noqa: PLC0415
    return pkg_layout


def _drop(folder: Path) -> None:
    link = folder / "state"
    if link.is_symlink() or os.path.isjunction(link):
        os.rmdir(link)                      # the junction only, never the data behind it
    shutil.rmtree(folder, ignore_errors=True)


def _state_dir() -> Path:
    """What the relay uses (relay/app_main.py _prepare_env): ARK_STATE_DIR from .env,
    else <data>\\state."""
    try:
        for line in (DATA / ".env").read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip() == "ARK_STATE_DIR" and value.strip():
                p = Path(value.split("#")[0].strip().strip('"').strip("'"))
                return p if p.is_absolute() else DATA / p   # pkg_layout.state_dir
    except OSError:
        pass
    return DATA / "state"


def _console_user() -> str:
    """Who is logged on at the console ('' = nobody). The relay runs only in that
    session, so with nobody there a new version cannot be started and judged."""
    try:
        import win32ts  # noqa: PLC0415 - the package's Python has pywin32
        sid = win32ts.WTSGetActiveConsoleSessionId()
        if sid == 0xFFFFFFFF:
            return ""
        return win32ts.WTSQuerySessionInformation(None, sid, win32ts.WTSUserName) or ""
    except Exception as e:  # noqa: BLE001
        print("console user unknown:", e)
        return "?"


def _sha1(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else "MISSING"


def _runtime() -> "tuple[str, list[tuple[str, str]]]":
    """This Python's version and its installed distributions: run with the package's
    python.exe, that is {app}\\runtime\\python and its Lib\\site-packages."""
    import importlib.metadata  # noqa: PLC0415
    import platform  # noqa: PLC0415
    pkgs = sorted({(d.metadata["Name"] or "?", d.version) for d in importlib.metadata.distributions()})
    return platform.python_version(), pkgs


def info(app: Path, rels: "list[str] | None" = None) -> int:
    print("CUR=" + (app / "current.txt").read_text(encoding="ascii").strip())
    print(f"STATEDIR={_state_dir()}")
    print(f"CONSOLE={_console_user()}")
    print(f"WATCHDOG_SHA={_sha1(app / 'watchdog' / 'ark_watchdog.py')}")
    for rel in rels or []:
        print(f"SHA {rel} {_sha1(app / rel)}")
    py, pkgs = _runtime()
    print(f"RUNTIME_PY={py}")
    for name, version in pkgs:
        print(f"RUNTIME_PKG {name}=={version}")
    return 0


def appfiles_stage(app: Path) -> int:
    """An empty APPFILES_IN; also drops an earlier deploy's APPFILES_PREV, so an
    appfiles-back in this deploy can only put back what this deploy replaced."""
    inc = app / APPFILES_IN
    shutil.rmtree(inc, ignore_errors=True)
    shutil.rmtree(app / APPFILES_PREV, ignore_errors=True)
    inc.mkdir(parents=True)
    print(f"APPFILES_IN={inc}")
    return 0


def _loads(p: Path) -> str:
    """'' when the file is fit to be used: a .py compiles with this Python (the one that
    runs it), a .json parses; else why not."""
    try:
        if p.suffix == ".py":
            compile(p.read_bytes(), str(p), "exec")
        elif p.suffix == ".json":
            json.loads(p.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError) as exc:
        return f"{p.name}: {exc}"
    return ""


def appfiles(app: Path, pairs: "list[str]") -> int:
    """Replace {app}\\<rel> with APPFILES_IN\\<rel> for each <rel>=<sha1>. Nothing changes
    unless every file sent has its sha1 and loads; each replace is a rename over the old
    file (never half-written), the old one kept in APPFILES_PREV; any failure puts back
    what was already replaced. The files are not in use at that moment: launch.py is read
    when a process starts, the others only by the installer's steps."""
    inc, prev = app / APPFILES_IN, app / APPFILES_PREV
    want = dict(pair.split("=", 1) for pair in pairs)
    bad = [f"{rel}: {_sha1(inc / rel)[:8]} != {sha[:8]}" for rel, sha in want.items() if _sha1(inc / rel) != sha]
    if not bad:
        bad = [why for why in (_loads(inc / rel) for rel in want) if why]
    if bad:
        print("APPFILES_FAIL nothing changed: " + "; ".join(bad))
        shutil.rmtree(inc, ignore_errors=True)
        return 1
    shutil.rmtree(prev, ignore_errors=True)
    prev.mkdir()
    new = []
    try:
        for rel, sha in want.items():
            dst = app / rel
            if dst.is_file():
                (prev / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, prev / rel)
            else:
                new.append(rel)
                (prev / APPFILES_NEW).write_text("\n".join(new) + "\n", encoding="utf-8")
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".new")
            shutil.copy2(inc / rel, tmp)
            os.replace(tmp, dst)
            if _sha1(dst) != sha:
                raise OSError(f"{rel} reads back as {_sha1(dst)[:8]}, not {sha[:8]}")
            print(f"APPFILE {rel}")
    except OSError as exc:
        print(f"APPFILES_FAIL {exc}")
        appfiles_back(app)
        return 1
    finally:
        shutil.rmtree(inc, ignore_errors=True)
    print(f"APPFILES_OK {len(want)}")
    return 0


def appfiles_back(app: Path) -> int:
    """Put back what the last `appfiles` replaced and remove what it added."""
    prev = app / APPFILES_PREV
    if not prev.is_dir():
        print("APPFILES_BACK 0")
        return 0
    n = 0
    for p in sorted(prev.rglob("*")):
        rel = p.relative_to(prev).as_posix()
        if p.is_file() and rel != APPFILES_NEW:
            os.replace(p, app / rel)
            n += 1
    try:
        added = (prev / APPFILES_NEW).read_text(encoding="utf-8").split()
    except OSError:
        added = []
    for rel in added:
        (app / rel).unlink(missing_ok=True)
        n += 1
    shutil.rmtree(prev, ignore_errors=True)
    print(f"APPFILES_BACK {n}")
    return 0


def stage(app: Path) -> int:
    inc = app / "versions" / INCOMING
    if inc.exists():
        _drop(inc)
    inc.mkdir(parents=True)
    print(f"INCOMING={inc}")
    return 0


def commit(app: Path) -> int:
    inc = app / "versions" / INCOMING
    manifest = json.loads((inc / "manifest.json").read_text(encoding="utf-8"))
    bad = []
    for rel, sha in manifest["files"].items():
        p = inc / rel
        got = hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else "MISSING"
        if got != sha:
            bad.append(f"{rel}: {got[:8]} != {sha[:8]}")
    if bad:
        print("MISMATCH " + "; ".join(bad))
        return 1
    print(f"HASH-OK {len(manifest['files'])}")
    pl = _layout(inc)
    prev = pl.current(app)
    pl.link_state(inc, pl.state_dir(DATA))
    version = str(manifest["version"])
    name, n = version, 0
    while (app / "versions" / name).exists():
        n += 1                              # the same version again: another copy, as an update does
        name = f"{version}-{n}"
    new = app / "versions" / name
    os.replace(inc, new)
    # _layout put .incoming on sys.path, and it is gone now: import from where it went
    # (cloud run 38093957453: "No module named 'ark_relay'" here, nothing switched).
    sys.path.insert(0, str(new))
    from ark_relay import selfupdate  # noqa: PLC0415 - from the folder just committed
    selfupdate._remember_version(new, int(version))   # else self-update would undo the deploy
    pl._pin(new, 0)                     # a deployed version ends a rollback's hold
    pl._set_current(app, name)
    pl._prune(app, keep={name, prev})
    print(f"NAME={name}")
    print(f"PREV={prev}")
    return 0


def back(app: Path, folder: str) -> int:
    if not (app / "versions" / folder / "app_main.py").is_file():
        print(f"NO-FOLDER {folder}")
        return 1
    pl = _layout(app / "versions" / folder)
    pl._set_current(app, folder)
    print("CURRENT=" + pl.current(app))
    return 0


class WinService:
    """The service side of update_watchdog on Windows (the package's Python has pywin32).
    Each call returns "" when it worked, else why not."""

    def __init__(self, app: Path) -> None:
        self.py = app / "runtime" / "python" / "python.exe"

    def start_type(self) -> str:
        """"AUTO" / "DISABLED" / "OTHER", or "MISSING" when it is not installed."""
        import pywintypes  # noqa: PLC0415
        import win32service  # noqa: PLC0415
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            try:
                svc = win32service.OpenService(scm, WATCHDOG, win32service.SERVICE_QUERY_CONFIG)
            except pywintypes.error as exc:
                if exc.winerror == 1060:             # ERROR_SERVICE_DOES_NOT_EXIST
                    return "MISSING"
                raise
            try:
                t = win32service.QueryServiceConfig(svc)[1]
            finally:
                win32service.CloseServiceHandle(svc)
        finally:
            win32service.CloseServiceHandle(scm)
        return {win32service.SERVICE_AUTO_START: "AUTO",
                win32service.SERVICE_DISABLED: "DISABLED"}.get(t, "OTHER")

    def install(self, script: Path) -> str:
        """ark_watchdog.py install, as switch.py install runs it: registered already, so
        ChangeServiceConfig (ERROR_SERVICE_EXISTS) and the preshutdown time-out."""
        r = subprocess.run([str(self.py), str(script), "install"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = " ".join((r.stdout + " " + r.stderr).split())
        if out:
            print("install:", out[-300:])
        return "" if r.returncode == 0 else f"ark_watchdog.py install exit {r.returncode}"

    def _state(self) -> int:
        import win32serviceutil  # noqa: PLC0415
        return win32serviceutil.QueryServiceStatus(WATCHDOG)[1]

    def stop(self) -> str:
        """Marker first, then stop, waited for (switch.py stop_watchdog)."""
        import pywintypes  # noqa: PLC0415
        import win32service  # noqa: PLC0415
        import win32serviceutil  # noqa: PLC0415
        try:
            WATCHDOG_MARKER.write_text(time.strftime("%Y-%m-%d %H:%M:%S pkg_deploy.py\n"), encoding="utf-8")
        except OSError as exc:
            return f"stop marker not written: {exc}"
        for _ in range(WATCHDOG_STOP_S):
            try:
                state = self._state()
                if state == win32service.SERVICE_STOPPED:
                    return ""
                if state == win32service.SERVICE_RUNNING:
                    win32serviceutil.StopService(WATCHDOG)
            except pywintypes.error as exc:
                if exc.winerror != 1062:             # ERROR_SERVICE_NOT_ACTIVE: stopped meanwhile
                    return f"stop: {exc.winerror} {exc.strerror}"
            time.sleep(1)
        return f"still not stopped after {WATCHDOG_STOP_S} s"

    def start(self) -> str:
        """Marker gone, then start and watch it come up (switch.py start_watchdog,
        watchdog_guard.py _start): RUNNING and still RUNNING WATCHDOG_STEADY_S later."""
        import pywintypes  # noqa: PLC0415
        import win32service  # noqa: PLC0415
        import win32serviceutil  # noqa: PLC0415
        try:
            WATCHDOG_MARKER.unlink(missing_ok=True)
        except OSError as exc:
            print("stop marker not deleted:", exc)
        try:
            win32serviceutil.StartService(WATCHDOG)
        except pywintypes.error as exc:
            if exc.winerror != 1056:                 # ERROR_SERVICE_ALREADY_RUNNING
                return f"start: {exc.winerror} {exc.strerror}"
        deadline = time.monotonic() + WATCHDOG_WAIT_S
        since = None
        while time.monotonic() < deadline:
            try:
                state = self._state()
            except pywintypes.error as exc:
                return f"state unknown after start: {exc.winerror} {exc.strerror}"
            if state == win32service.SERVICE_RUNNING:
                since = since or time.monotonic()
                if time.monotonic() - since >= WATCHDOG_STEADY_S:
                    return ""
            elif state == win32service.SERVICE_STOPPED:
                return "stopped again during its start"
            else:
                since = None
            time.sleep(1)
        return f"not running {WATCHDOG_WAIT_S} s after the start"

    def running(self) -> bool:
        import win32service  # noqa: PLC0415
        return self._state() == win32service.SERVICE_RUNNING


def update_watchdog(app: Path, want: str, staged: Path, svc) -> int:
    """Make {app}\\watchdog\\ark_watchdog.py the file `staged` (sha1 `want`) and the service
    run it: copy -> install -> restart (stop, start) -> verify RUNNING.

    The same file already there: nothing at all. Disabled (switch.py revert switched the
    new relay off on purpose) or not installed: nothing either, said so. A step that fails
    puts the previous file back and starts the service on it, so the machine is never left
    without a watchdog; the deploy reports the failure (the relay itself is live by then).
    The stop marker is gone after every start, so even a start that failed here is tried
    again by the relay's guard at its next look (relay/watchdog_guard.py)."""
    dst = app / "watchdog" / "ark_watchdog.py"
    got = _sha1(staged)
    if got != want:
        print(f"WATCHDOG_FAIL the file sent is {got[:8]}, not {want[:8]}: nothing changed")
        return 1
    if _sha1(dst) == want:
        print("WATCHDOG=unchanged")
        return 0
    why = _loads(staged)
    if why:
        print(f"WATCHDOG_FAIL the file sent does not compile ({why}): nothing changed")
        return 1
    kind = svc.start_type()
    if kind == "DISABLED":
        print("WATCHDOG=disabled")                   # off on purpose: not switched back on
        return 0
    if kind == "MISSING":
        print(f"WATCHDOG_FAIL service {WATCHDOG} is not installed: nothing changed")
        return 1
    prev = dst.with_name(dst.name + ".prev")
    had = dst.is_file()
    if had:
        shutil.copy2(dst, prev)
    tmp = dst.with_name(dst.name + ".new")
    shutil.copy2(staged, tmp)
    os.replace(tmp, dst)                             # no half-written file for a restart to load
    print("WATCHDOG_STEP copy")
    for step, call in (("install", lambda: svc.install(dst)), ("stop", svc.stop), ("start", svc.start)):
        why = call()
        if why:
            break
        print(f"WATCHDOG_STEP {step}")
    else:
        if svc.running():
            print("WATCHDOG_STEP verify")
            print("WATCHDOG=updated")
            return 0
        step, why = "verify", "not RUNNING after the start"
    print(f"WATCHDOG_FAIL {step}: {why}")
    if had:
        os.replace(prev, dst)
    svc.stop()
    back = svc.start()
    print("WATCHDOG_RESTORED " + ("running on the previous file" if not back else f"previous file back, but {back}"))
    return 1


def main(argv: list[str]) -> int:
    cmd, app = argv[1], Path(argv[2])
    if cmd == "info":
        return info(app, argv[3:])
    if cmd == "appfiles-stage":
        return appfiles_stage(app)
    if cmd == "appfiles":
        return appfiles(app, argv[3:])
    if cmd == "appfiles-back":
        return appfiles_back(app)
    if cmd == "stage":
        return stage(app)
    if cmd == "commit":
        return commit(app)
    if cmd == "back":
        return back(app, argv[3])
    if cmd == "watchdog":
        return update_watchdog(app, argv[3], Path(argv[4]), WinService(app))
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
