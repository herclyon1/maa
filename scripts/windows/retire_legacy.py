"""Retire the old relay from the game machine; only the new one (C:\\Program Files\\ArkRelay) stays.

    scripts/mac/winrun.sh --py scripts/windows/retire_legacy.py        dry run: prints the plan
    scripts/mac/winrun.sh --py scripts/windows/retire_legacy.py --go   does it

What goes (user 10-11 17:23, asked whether all of the old relay could be taken off and
replaced by the new one): the old service ark-relay and its event-log source, the old
logon task \\ark-relay, the old relay's code in C:\\ProgramData\\ark-relay,
C:\\ProgramData\\ark-relay-deploy-prev, and the unused ark-* leftovers in C:\\ProgramData
(no reference anywhere in the repo; the inventory of 2026-10-11).

Nothing is deleted. Files and folders are moved into C:\\ProgramData\\ark-relay-retired-1011
under their path relative to C:\\ProgramData, and each move is a line in manifest.txt there
(~/Claude/CLAUDE.md safety rule 4: shared things are not deleted without checking who uses
them; a move can be undone). Before the service and the task are deleted, `sc qc`,
`sc qfailure`, the service's registry key, the event-log key and `schtasks /query /xml`
are saved into the same folder, so both can be rebuilt. The folder is for clearing after
30 days.

Guards (any one failing: nothing is changed):
  * the new relay runs: task \\ArkRelay\\main running, service ArkRelayWatchdog running,
    C:\\Program Files\\ArkRelay\\current.txt present (exit 2);
  * no planned move is, contains, or lies inside a kept path (KEEP, KEEP_GLOBS, the live
    state folder read from .env) (exit 3);
  * nothing kept names a planned move: kept scripts and .env, every scheduled task's
    actions, the desktops' scripts and shortcuts (exit 3);
  * the old service is stopped (two relays running needs a look first) (exit 3);
  * --go only: the process is elevated (exit 4).

After this the way back from a broken new version is the previous version folder
(`launch.py rollback`); `switch.py revert` says the old relay is retired.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PROGRAMDATA = Path(r"C:\ProgramData")
PACKAGE = Path(r"C:\Program Files\ArkRelay")
RETIRED_NAME = "ark-relay-retired-1011"
DATA_NAME = "ark-relay"
OLD_SERVICE = "ark-relay"
OLD_TASK = "\\ark-relay"
SERVICE_KEY = r"HKLM\SYSTEM\CurrentControlSet\Services\ark-relay"
EVENTLOG_KEY = r"HKLM\SYSTEM\CurrentControlSet\Services\EventLog\Application\ark-relay"
NEW_TASK_FOLDER, NEW_TASK_NAME = "\\ArkRelay", "main"
NEW_WATCHDOG = "ArkRelayWatchdog"
KEEP_DAYS = 30

# --- what moves (paths relative to C:\ProgramData) ---------------------------------
# The old relay's code in the data folder: packaging/legacy.py OLD_CODE (deployed by
# scripts/mac/deploy-relay.sh) plus what the machine held on 2026-10-11 16:37.
OLD_CODE = ["ark_relay", "run.py", "service.py", "boot_stages.py", "app_main.py",
            "pkg_layout.py", "manifest.json", "RELEASE-NOTES.md", "requirements.txt",
            "make-manifest.py", "USER-SWITCHES.txt", "README.md", "ark-relay.ps1",
            "__pycache__", "ark-relay.cmd", "morning-report.cmd", "skip-shutdown.bat",
            "ark-state", "ocrcrop-test", "last-run.txt", "plan-check.txt"]
MOVE = [f"{DATA_NAME}/{n}" for n in OLD_CODE] + [
    "ark-relay-deploy-prev",            # scripts/mac/deploy-relay.sh:344, old deploy backup
    # No reference anywhere in the repo (git grep, 2026-10-11):
    "ark-copilot.log", "ark-hist", "ark-morning-watch.json", "ark-queue-events.py",
    "ark-shot.jpg", "ark-sr58.log", "ark-startup-backup", "ark-startup.log",
    "ark-state-dump.json", "ark-su2.log", "ark-t13", "ark-tmp", "focus-watch.bat",
]
MOVE_GLOBS = [f"{DATA_NAME}/.env.bak*", "okww-shot-*.png"]

# --- what stays -------------------------------------------------------------------
# The new relay's data, the echo-farm files and tasks it owns, and what Mac-side tools
# still write here. Nothing may move that is one of these, holds one, or lies inside one.
KEEP = {
    f"{DATA_NAME}/.env": "new relay's settings",
    f"{DATA_NAME}/state": "new relay's state",
    f"{DATA_NAME}/state/legacy-takeover.json": "new relay's takeover record",
    f"{DATA_NAME}/relay.log": "new relay's log",
    f"{DATA_NAME}/watchdog.log": "new watchdog's log",
    f"{DATA_NAME}/switch.log": "installer steps log",
    f"{DATA_NAME}/start-error.txt": "packaging/launch.py START_ERROR",
    f"{DATA_NAME}/watchdog-stopped.txt": "packaging/switch.py WATCHDOG_MARKER",
    "ark-okww-overlay.json": "relay/ark_relay/features/okww_patch/okww_overlay.py",
    "ark-okww-master.txt": "relay/ark_relay/features/okww_patch/okww_overlay.py",
    "ark-okww-stop.bat": "relay/ark_relay/features/echofarm/echofarm.py",
    "ark-shot.png": "scripts/mac/adbdo.sh",
    "ark-queue-watch.json": "scripts/mac/lib/queue_events.py",
    "arklog.py": "scripts/mac/winrun.sh ships it on every call",
    "okww-run.bat": "scripts/mac/okww-task.sh",
    RETIRED_NAME: "where retired things go",
}
KEEP_GLOBS = {
    f"{DATA_NAME}/relay.log*": "new relay's log",
    "ark-okww-farm.*": "relay/ark_relay/features/echofarm/echofarm.py",
    "ark-gui*": "scripts/mac/wingui.sh",
    "winrun*": "scripts/mac/winrun.sh",
    "winps-*": "scripts/mac/winps.sh",
}
KEEP_OUTSIDE = {                        # absolute; never under C:\ProgramData
    r"C:\Program Files\ArkRelay": "the new relay",
    r"C:\Program Files\Python314": "winrun.sh runs every remote script with it",
    r"C:\Program Files\PowerShell\7": "pwsh: repo CLAUDE.md rule 2, wingui.sh",
    r"D:\ark\automas\environment\python\pythonservice.exe": "legacy-items.json: unchecked",
}
KEEP_TASKS = {"\\ArkRelay\\main", "\\ark-okww-farm", "\\ark-okww-stop", "\\AUTO-MAS_AutoStart",
              "\\ark-gui", "\\ark-okww", "\\1232", "\\MAA \u5b98", "\\maaend",
              "\\\u81ea\u52d5\u95dc\u6a5f"}
KEEP_SERVICES = {NEW_WATCHDOG, "sshd"}
# Unused-looking but still referenced (docs/OPERATIONS.md, scripts/windows/ark-do.ps1):
# the references go first, then these. Printed, not moved.
LEFT = {
    "ark-cmd.txt": "referenced by docs/OPERATIONS.md, scripts/windows/ark-do.ps1",
    "ark-do.log": "referenced by docs/OPERATIONS.md, scripts/windows/ark-do.ps1",
    f"{DATA_NAME}/.env.env.bak": "an .env backup outside the agreed .env.bak* pattern",
}
# Names in C:\ProgramData that look like ours; any not planned, kept or left is listed.
OURS_LIKE = ["ark-*", "okww-shot-*", "focus-watch*"]
# Kept files that can name a path (a kept .bat starting something we move would break):
# their text is searched for every planned move. Logs are not: they quote old paths.
SCRIPT_SUFFIXES = (".bat", ".cmd", ".ps1", ".py", ".vbs")
# Not searched: the Mac-side tools' per-call files, rewritten by every call (winrun.sh's
# winrun.ps1 holds the last inline command, winrun-run-*.py is this very script).
REF_SKIP = ["winrun*", "winps-*"]
DESKTOPS = [Path(r"C:\Users\Administrator\Desktop"), Path(r"C:\Users\Public\Desktop")]


def _read_text(p: Path) -> str:
    try:
        b = p.read_bytes()[:1_000_000]
    except OSError:
        return ""
    if b.startswith((b"\xff\xfe", b"\xfe\xff")):
        return b.decode("utf-16", "replace")
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("mbcs" if os.name == "nt" else "latin-1", "replace")


def _norm(p: "Path | str") -> str:
    return str(p).replace("\\", "/").rstrip("/").lower()


def _inside(a: str, b: str) -> bool:
    """a is b or lies inside b (normalised paths)."""
    return a == b or a.startswith(b + "/")


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def state_dir(data: Path) -> Path:
    """The live state folder as the new relay resolves it (relay/pkg_layout.state_dir):
    .env's ARK_STATE_DIR, relative ones under the data folder; else <data>/state."""
    try:
        text = (data / ".env").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    value = ""
    for line in text.splitlines():
        m = re.match(r"\s*(?:export\s+)?ARK_STATE_DIR\s*=\s*(.*)$", line)
        if m:
            value = m.group(1).strip().strip('"').strip("'")
    if not value:
        return data / "state"
    p = Path(value)
    return p if p.is_absolute() or re.match(r"^[A-Za-z]:[\\/]", value) else data / value


# --- the machine (replaced by a fake in relay/tests/test_retire_legacy.py) ----------
class Machine:
    def _sc(self, *args: str) -> "subprocess.CompletedProcess":
        return subprocess.run(["sc", *args], capture_output=True, timeout=60)

    def service_state(self, name: str) -> "int | None":
        """SERVICE_STATUS dwCurrentState (1 stopped, 4 running); None = no such service.
        The number, not the localised word."""
        r = self._sc("query", name)
        if r.returncode == 1060:
            return None
        m = re.search(rb"STATE\s*:\s*(\d+)", r.stdout)
        return int(m.group(1)) if m else -1

    def new_task_running(self) -> bool:
        """\\ArkRelay\\main's IRegisteredTask.State is TASK_STATE_RUNNING (4)."""
        try:
            import win32com.client  # noqa: PLC0415
            sched = win32com.client.Dispatch("Schedule.Service")
            sched.Connect()
            return sched.GetFolder(NEW_TASK_FOLDER).GetTask(NEW_TASK_NAME).State == 4
        except Exception as e:  # noqa: BLE001 - no pywin32 / no task: not running
            print("  task state unknown:", e)
            return False

    def task_exists(self, name: str) -> bool:
        return subprocess.run(["schtasks", "/query", "/tn", name], capture_output=True,
                              timeout=60).returncode == 0

    def reg_key_exists(self, key: str) -> bool:
        return subprocess.run(["reg", "query", key], capture_output=True,
                              timeout=60).returncode == 0

    def references(self) -> "list[tuple[str, str]]":
        """(where, text) for what outside C:\\ProgramData can start something: every
        scheduled task's actions (but the old one, deleted here), and the desktops'
        scripts and shortcut targets."""
        out = []
        try:
            import win32com.client  # noqa: PLC0415
            sched = win32com.client.Dispatch("Schedule.Service")
            sched.Connect()

            def walk(folder):
                for t in folder.GetTasks(1):           # TASK_ENUM_HIDDEN
                    if t.Path.lower() == OLD_TASK.lower():
                        continue
                    acts = []
                    for a in t.Definition.Actions:
                        acts.append(" ".join(str(getattr(a, k, "") or "")
                                             for k in ("Path", "Arguments", "WorkingDirectory")))
                    out.append((f"task {t.Path}", "\n".join(acts)))
                for f in folder.GetFolders(0):
                    walk(f)
            walk(sched.GetFolder("\\"))
        except Exception as e:  # noqa: BLE001
            out.append(("task list", f"<unreadable: {e}>"))
        shell = None
        for d in DESKTOPS:
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for n in names:
                p = d / n
                if p.suffix.lower() in SCRIPT_SUFFIXES:
                    out.append((str(p), _read_text(p)))
                elif p.suffix.lower() == ".lnk":
                    try:
                        if shell is None:
                            import win32com.client  # noqa: PLC0415
                            shell = win32com.client.Dispatch("WScript.Shell")
                        lnk = shell.CreateShortcut(str(p))
                        out.append((str(p), f"{lnk.TargetPath} {lnk.Arguments} {lnk.WorkingDirectory}"))
                    except Exception as e:  # noqa: BLE001
                        out.append((str(p), f"<unreadable: {e}>"))
        return out

    def is_admin(self) -> bool:
        try:
            import ctypes  # noqa: PLC0415
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            return False

    def capture(self, cmd: list[str]) -> "tuple[int, bytes]":
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def run(self, cmd: list[str]) -> int:
        rc, out = self.capture(cmd)
        print("   ", " ".join(cmd), "->", rc)
        if rc:
            print("     ", out.decode("mbcs" if os.name == "nt" else "utf-8", "replace").strip()[:300])
        return rc


@dataclass
class Plan:
    moves: list = field(default_factory=list)        # (src Path, dst Path)
    keep: list = field(default_factory=list)         # (path, why) - kept (printed when present)
    left: list = field(default_factory=list)         # (path, why) - present, not moved
    service: bool = False                             # old service present
    eventlog: bool = False                            # its event-log source present
    task: bool = False                                # old logon task present
    blocked: list = field(default_factory=list)      # guard failures: nothing is done
    aborted: list = field(default_factory=list)      # keep-list hits: nothing is done


def new_relay_problems(machine, package: Path) -> list[str]:
    problems = []
    if not machine.new_task_running():
        problems.append(f"task {NEW_TASK_FOLDER}\\{NEW_TASK_NAME} is not running")
    if machine.service_state(NEW_WATCHDOG) != 4:
        problems.append(f"service {NEW_WATCHDOG} is not running")
    if not (package / "current.txt").is_file():
        problems.append(f"{package / 'current.txt'} is missing")
    return problems


def make_plan(machine, pd: Path = PROGRAMDATA, package: Path = PACKAGE,
              keep_outside: "dict | None" = None) -> Plan:
    plan = Plan()
    plan.blocked = new_relay_problems(machine, package)
    if plan.blocked:
        return plan
    data = pd / DATA_NAME
    retired = pd / RETIRED_NAME

    keep_paths = {}                    # normalised path -> (path as given, why)
    for rel, why in KEEP.items():
        keep_paths[_norm(pd / rel)] = (pd / rel, why)
    for pattern, why in KEEP_GLOBS.items():
        for p in pd.glob(pattern):
            keep_paths[_norm(p)] = (p, why)
    live = state_dir(data)
    keep_paths[_norm(live)] = (live, "live state folder (.env ARK_STATE_DIR, else state)")
    for p, why in (KEEP_OUTSIDE if keep_outside is None else keep_outside).items():
        keep_paths[_norm(p)] = (Path(p), why)

    sources = [pd / rel for rel in MOVE]
    for pattern in MOVE_GLOBS:
        sources += sorted(pd.glob(pattern))
    seen = set()
    for src in sources:
        if _norm(src) in seen or not (src.exists() or src.is_symlink()):
            continue
        seen.add(_norm(src))
        s = _norm(src)
        for k, (shown, why) in keep_paths.items():
            if _inside(s, k) or _inside(k, s):
                plan.aborted.append(f"{src} would move kept {shown} ({why})")
        plan.moves.append((src, retired / src.relative_to(pd)))

    for _k, (shown, why) in sorted(keep_paths.items()):
        plan.keep.append((shown, why))
    for rel, why in LEFT.items():
        if (pd / rel).exists():
            plan.left.append((pd / rel, why))
    accounted = seen | set(keep_paths) | {_norm(pd / rel) for rel in LEFT}
    accounted.add(_norm(data))
    try:
        entries = sorted(os.listdir(pd))
    except OSError:
        entries = []
    for name in entries:
        if any(fnmatch.fnmatch(name.lower(), pat) for pat in OURS_LIKE) and \
                _norm(pd / name) not in accounted:
            plan.left.append((pd / name, "not in any list: left as it is"))

    # Anything kept that names a planned move would break once it is gone.
    refs = [(str(shown), _read_text(Path(shown))) for _k, (shown, _why) in keep_paths.items()
            if Path(shown).is_file() and (Path(shown).suffix.lower() in SCRIPT_SUFFIXES
                                          or Path(shown).name.lower() == ".env")
            and not any(fnmatch.fnmatch(Path(shown).name.lower(), g) for g in REF_SKIP)]
    refs += machine.references()
    for where, text in refs:
        if text.startswith("<unreadable"):          # cannot tell: do not guess
            plan.aborted.append(f"{where} {text}")
        flat = _norm(text).replace("%programdata%", _norm(pd))
        for src, _dst in plan.moves:
            s = _norm(src)
            if re.search(re.escape(s) + r"(?![\w.-])", flat):
                plan.aborted.append(f"{where} names {src}, which would move")

    state = machine.service_state(OLD_SERVICE)
    plan.service = state is not None
    if state not in (None, 1):
        plan.aborted.append(f"old service {OLD_SERVICE} is not stopped (state {state})")
    plan.eventlog = machine.reg_key_exists(EVENTLOG_KEY)
    plan.task = machine.task_exists(OLD_TASK)
    if OLD_SERVICE in KEEP_SERVICES or OLD_TASK in KEEP_TASKS:
        plan.aborted.append("the old service or task is on the keep list")
    return plan


def print_plan(plan: Plan, pd: Path) -> None:
    retired = pd / RETIRED_NAME
    print(f"[move into {retired}]  {len(plan.moves)}")
    for src, dst in plan.moves:
        print(f"  {src}  ->  {dst}  ({_size(src)} bytes)")
    print("[delete, saved first]")
    print(f"  service {OLD_SERVICE}: {'present' if plan.service else 'not present'}")
    print(f"  event-log source {EVENTLOG_KEY}: {'present' if plan.eventlog else 'not present'}")
    print(f"  task {OLD_TASK}: {'present' if plan.task else 'not present'}")
    print(f"[left where it is, not moved]  {len(plan.left)}")
    for p, why in plan.left:
        print(f"  {p}  ({why})")
    present = [(k, why) for k, why in plan.keep if Path(k).exists()]
    print(f"[kept: present on this machine]  {len(present)}")
    for k, why in present:
        print(f"  {k}  ({why})")
    print(f"  tasks kept: {', '.join(sorted(KEEP_TASKS))}")
    print(f"  services kept: {', '.join(sorted(KEEP_SERVICES))}")


class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path

    def line(self, *parts: str) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("\t".join([time.strftime("%Y-%m-%d %H:%M:%S"), *parts]) + "\n")


def _save(machine, manifest: Manifest, retired: Path, name: str, cmd: list[str]) -> bool:
    rc, out = machine.capture(cmd)
    (retired / name).write_bytes(out)
    manifest.line("saved", " ".join(cmd), f"-> {retired / name}", f"rc {rc}")
    return rc == 0


def _save_task_xml(machine, manifest: Manifest, retired: Path) -> bool:
    """schtasks /query /xml, rewritten as UTF-16 with BOM: the XML declares UTF-16 and
    `schtasks /create /xml` reads it back as such."""
    rc, out = machine.capture(["schtasks", "/query", "/tn", OLD_TASK, "/xml"])
    if out.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = out.decode("utf-16")
    else:
        text = out.decode("mbcs" if os.name == "nt" else "utf-8", "replace")
    (retired / "ark-relay.task.xml").write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))
    manifest.line("saved", f"schtasks /query /tn {OLD_TASK} /xml",
                  f"-> {retired / 'ark-relay.task.xml'}", f"rc {rc}")
    return rc == 0 and "<Task" in text


def apply(plan: Plan, machine, pd: Path = PROGRAMDATA) -> int:
    """--go: save, delete the service and the task, move the files. 0 = all done."""
    retired = pd / RETIRED_NAME
    retired.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(retired / "manifest.txt")
    manifest.line("start", f"retire_legacy.py --go; clear this folder after {KEEP_DAYS} days "
                  f"({time.strftime('%Y-%m-%d', time.localtime(time.time() + KEEP_DAYS * 86400))})")
    errors = 0

    if plan.service:
        saved = all([
            _save(machine, manifest, retired, "ark-relay.sc-qc.txt", ["sc", "qc", OLD_SERVICE]),
            _save(machine, manifest, retired, "ark-relay.sc-qfailure.txt",
                  ["sc", "qfailure", OLD_SERVICE]),
            _save(machine, manifest, retired, "ark-relay.service.reg.log",
                  ["reg", "export", SERVICE_KEY, str(retired / "ark-relay.service.reg"), "/y"]),
        ])
        if saved and machine.run(["sc", "delete", OLD_SERVICE]) == 0:
            manifest.line("deleted", f"service {OLD_SERVICE}")
        else:
            errors += 1
            manifest.line("FAILED", f"service {OLD_SERVICE} not deleted (saved: {saved})")
    if plan.eventlog:
        saved = _save(machine, manifest, retired, "ark-relay.eventlog.reg.log",
                      ["reg", "export", EVENTLOG_KEY, str(retired / "ark-relay.eventlog.reg"), "/y"])
        if saved and machine.run(["reg", "delete", EVENTLOG_KEY, "/f"]) == 0:
            manifest.line("deleted", f"registry {EVENTLOG_KEY}")
        else:
            errors += 1
            manifest.line("FAILED", f"registry {EVENTLOG_KEY} not deleted (saved: {saved})")
    if plan.task:
        saved = _save_task_xml(machine, manifest, retired)
        if saved and machine.run(["schtasks", "/delete", "/tn", OLD_TASK, "/f"]) == 0:
            manifest.line("deleted", f"task {OLD_TASK}")
        else:
            errors += 1
            manifest.line("FAILED", f"task {OLD_TASK} not deleted (saved: {saved})")

    for src, dst in plan.moves:
        if not (src.exists() or src.is_symlink()):
            manifest.line("skipped", str(src), "already gone")
            continue
        if dst.exists():
            errors += 1
            manifest.line("FAILED", str(src), f"-> {dst} already exists")
            print("  not moved (target exists):", src)
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            manifest.line("moved", str(src), f"-> {dst}")
            print("  moved", src)
        except OSError as e:
            errors += 1
            manifest.line("FAILED", str(src), f"-> {dst}", repr(e))
            print("  not moved:", src, e)

    manifest.line("restore", "files: move each back from this folder to C:\\ProgramData\\<same "
                  "relative path>; task: schtasks /create /tn \\ark-relay /xml ark-relay.task.xml; "
                  "service: sc create ark-relay binPath= <BINARY_PATH_NAME in ark-relay.sc-qc.txt> "
                  "start= disabled, then reg import ark-relay.service.reg and "
                  "ark-relay.eventlog.reg")
    manifest.line("end", f"{errors} error(s)")
    print(f"done, {errors} error(s); manifest: {manifest.path}")
    return 1 if errors else 0


def main(argv: "list[str] | None" = None, machine=None, pd: Path = PROGRAMDATA,
         package: Path = PACKAGE, keep_outside: "dict | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--go", action="store_true", help="do it (default: dry run)")
    args = ap.parse_args(argv)
    machine = machine or Machine()
    plan = make_plan(machine, pd, package, keep_outside)
    if plan.blocked:
        print("new relay not running - nothing done:")
        for b in plan.blocked:
            print("  " + b)
        return 2
    print_plan(plan, pd)
    if plan.aborted:
        print("ABORTED - nothing done:")
        for a in plan.aborted:
            print("  " + a)
        return 3
    if not args.go:
        print(f"elevated: {'yes' if machine.is_admin() else 'no (--go would stop here)'}")
        print("dry run: nothing changed (run with --go to do it)")
        return 0
    if not machine.is_admin():
        print("not elevated - nothing done")
        return 4
    return apply(plan, machine, pd)


if __name__ == "__main__":
    sys.exit(main())
