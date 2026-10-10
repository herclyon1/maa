"""Build the installer, install it, run the relay once, uninstall, check nothing is left.

Run by .github/workflows/package-windows.yml on a GitHub Windows runner
("Windows virtual machines are configured to run as administrators with User
Account Control (UAC) disabled", docs.github.com, GitHub-hosted runners), never
on the game machine. Every name comes from relay/handover/package-items.json;
while any value there still starts with CONFIRM the script stops before
building anything.

Stages, each printed as it finishes; the first hard failure stops the run:
  1 build      ISCC.exe <iss>  (Inno Setup is on the runner image: InnoSetup 6.7.1,
               actions/runner-images Windows2025-Readme.md, image 20261004)
  2 install    <setup.exe> /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=<file>
  3 installed  relay/handover/leftovers.py installed
  4 one round  write a test .env (no shutdown, no pushes, AUTO-MAS pointed at an
               empty folder), start the main program through the installed
               scheduled task (package-items.json "tasks"), wait for
               startup_log_line in log_file. If the task does not bring it up
               (it runs only in a logged-on session; the runner may have none),
               that is printed as UNTESTED and the main program is started
               directly as package-items.json "main_command" says.
  5 watchdog   kill the main program, report whether it comes back within 90 s.
               UNTESTED, not failed, when it does not: the watchdog starts it
               through the same logon-session task.
  6 uninstall  <install_dir>\\unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART,
               then wait (up to 120 s) until <install_dir> is gone: the
               uninstaller hands off to a copy of itself and returns at once
  7 clean      relay/handover/leftovers.py uninstalled
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOVER = ROOT / "relay" / "handover"
ISCC = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
OUT = ROOT / "package-smoke"
# The test .env (relay/ark_relay/config.py: ARK_SHUTDOWN_AFTER_RUN is on only
# when "1", ARK_REPORT_BEFORE_SHUTDOWN defaults to "1"): no power-off, no group
# or phone pushes (no keys at all), and
# AUTO-MAS / the three tools pointed at empty folders so nothing is started.
TEST_ENV = {
    "ARK_SHUTDOWN_AFTER_RUN": "0",
    "ARK_REPORT_BEFORE_SHUTDOWN": "0",
    "ARK_AUTOMAS_DIR": str(OUT / "fake-automas"),
    "ARK_HISTORY_DIR": str(OUT / "fake-automas" / "history"),
    "ARK_MAA_DIR": str(OUT / "fake-maa"),
    "ARK_MAAEND_DIR": str(OUT / "fake-maaend"),
    "ARK_OKWW_DIR": str(OUT / "fake-okww"),
}


def say(stage: str, ok: "bool | None", detail: str = "") -> None:
    """ok True/False; None = could not be tried here (UNTESTED, does not fail the run)."""
    word = "UNTESTED" if ok is None else "ok" if ok else "FAIL"
    print(f"[{word}] {stage}" + (f": {detail}" if detail else ""), flush=True)


def run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)


def leftovers(mode: str) -> bool:
    r = run([sys.executable, str(HANDOVER / "leftovers.py"), mode], timeout=300)
    print(r.stdout + r.stderr)
    return r.returncode == 0


def main_pids(match: str) -> list[int]:
    r = run(["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"])
    return [int(line.split("\t", 1)[0]) for line in r.stdout.splitlines()
            if "\t" in line and match in line.split("\t", 1)[1] and "package_smoke" not in line]


def wait_for_line(log: Path, line: str, after: int, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if line in log.read_text(encoding="utf-8", errors="replace")[after:]:
                return True
        except OSError:
            pass
        time.sleep(3)
    return False


def main() -> int:
    pkg = json.loads((HANDOVER / "package-items.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(HANDOVER))
    import leftovers as L  # noqa: PLC0415
    if todo := L.unconfirmed(pkg):
        say("0 names", False, "package-items.json still has placeholders: " + ", ".join(todo))
        return 1
    OUT.mkdir(exist_ok=True)
    for d in ("fake-automas/history", "fake-maa", "fake-maaend", "fake-okww"):
        (OUT / d).mkdir(parents=True, exist_ok=True)

    # The installer compiles a staged folder (embedded Python, packages, code), so it is
    # built by the package's own build script, not by ISCC on the .iss alone.
    if not ISCC.exists():
        say("1 build", False, f"{ISCC} not on this runner")
        return 1
    r = run([sys.executable if a == "python" else str(ROOT / a) if a.endswith(".py") else a
             for a in pkg["build"]] + ["--iscc", str(ISCC)],
            timeout=1800)
    print(r.stdout[-4000:] + r.stderr[-2000:])
    built = sorted(ROOT.glob(pkg["setup_exe_glob"]))
    if r.returncode != 0 or not built:
        say("1 build", False, f"build exit {r.returncode}")
        return 1
    shutil.copy2(built[-1], OUT / "setup.exe")
    say("1 build", True)

    r = run([str(OUT / "setup.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             f"/LOG={OUT / 'install.log'}", *pkg.get("install_args", [])])
    if r.returncode != 0:
        say("2 install", False, f"exit {r.returncode}; see install.log")
        return 1
    say("2 install", True)

    if not leftovers("installed"):
        say("3 installed", False)
        return 1
    say("3 installed", True)

    env_file = Path(pkg["env_file"])
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("".join(f"{k}={v}\n" for k, v in TEST_ENV.items()), encoding="utf-8")
    # The installer already started the relay (before this .env existed): stop it, so
    # the start below is a fresh one that reads the test .env.
    inst = Path(pkg["install_dir"])
    run([str(inst / "runtime" / "python" / "python.exe"), str(inst / "launch.py"), "stop"], timeout=90)
    log = Path(pkg["log_file"])
    start = log.stat().st_size if log.exists() else 0
    main_proc = None
    task = pkg["tasks"][0]
    run(["schtasks", "/run", "/tn", task])
    up = wait_for_line(log, pkg["startup_log_line"], start, 90)
    say("4a started by the scheduled task", True if up else None,
        "" if up else f"{task} did not bring it up within 90 s (no logon session on the runner?)")
    if not up:
        cmd = [a.replace("<install_dir>", pkg["install_dir"]).replace("<data_dir>", pkg["data_dir"])
               for a in pkg["main_command"]]
        main_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        up = wait_for_line(log, pkg["startup_log_line"], start, 180)
    say("4 one round", up, "" if up else f"no {pkg['startup_log_line']!r} in {log} within 180 s")
    if not up:
        if main_proc:
            main_proc.kill()
        return 1

    pids = main_pids(pkg["main_process_match"])
    for pid in pids:
        run(["taskkill", "/PID", str(pid), "/F"])
    back = False
    deadline = time.time() + 90
    while time.time() < deadline and not back:
        time.sleep(5)
        back = bool(set(main_pids(pkg["main_process_match"])) - set(pids))
    say("5 watchdog", True if back else None,
        ("came back" if back else "did not come back within 90 s") + f" after killing {pids}")
    for pid in main_pids(pkg["main_process_match"]):
        run(["taskkill", "/PID", str(pid), "/F"])

    unins = Path(pkg["install_dir"]) / "unins000.exe"
    r = run([str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    if r.returncode != 0:
        say("6 uninstall", False, f"exit {r.returncode}")
        return 1
    # The uninstaller hands off to a copy of itself and returns at once: wait for it.
    deadline = time.time() + 120
    while Path(pkg["install_dir"]).exists() and time.time() < deadline:
        time.sleep(3)
    gone = not Path(pkg["install_dir"]).exists()
    say("6 uninstall", gone, "" if gone else f"{pkg['install_dir']} still there after 120 s")
    if not gone:
        return 1

    clean = leftovers("uninstalled")
    say("7 clean", clean)
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
