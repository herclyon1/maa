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
               empty folder). The runner has no logged-on session, and the
               installed task runs only in one, so for this test the task's
               principal is switched to SYSTEM (no logon needed) and the .env
               sets ARK_WATCHDOG_TEST_NO_LOGON=1 (the watchdog skips its "anyone
               logged on" check). Start the main program through the task, wait
               for startup_log_line in log_file. If the task does not bring it
               up, that FAILS the run; the main program is then started directly
               (package-items.json "main_command") so the stages after still run.
  4c restart   pkg_layout.restart_soon, then `launch.py stop` (as at the end of an
               update) from a scheduled task whose process then exits, watchdog
               still off: a new main program within 15 s
  5 watchdog   kill the main program; the watchdog must notice and run the task
               again (its check is every 30 s): FAIL unless it is back within
               120 s and watchdog.log has the restart line.
               Not covered here, checked on the machine at switch-over: the task
               starting in his logon session, and the watchdog's logon check.
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
    "ARK_WATCHDOG_TEST_NO_LOGON": "1",
    # The relay will not start without a group robot (Config.validate). This one is
    # the runner's own discard port: every push fails on the runner, none leaves it.
    "WECOM_BOT_URL": "http://127.0.0.1:9/cgi-bin/webhook/send?key=ci",
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
            # `after` is a size in bytes (stat): slice the bytes, then decode. Slicing the
            # decoded text by it skipped past new Chinese lines (run 38092084872).
            if line in log.read_bytes()[after:].decode("utf-8", errors="replace"):
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

    # The test .env before the install, as on the game machine, where the data folder
    # and its .env are there before the package: the installer waits for the relay to
    # come up, and without a configuration the relay stops at once.
    env_file = Path(pkg["env_file"])
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("".join(f"{k}={v}\n" for k, v in TEST_ENV.items()), encoding="utf-8")

    r = run([str(OUT / "setup.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             f"/LOG={OUT / 'install.log'}", *pkg.get("install_args", [])])
    if r.returncode != 0:
        say("2 install", False, f"exit {r.returncode}; see install.log")
        run_main_once(pkg)
        return 1
    say("2 install", True)

    if not leftovers("installed"):
        say("3 installed", False)
        return 1
    say("3 installed", True)

    # The installer started the relay (and waited for it, someone being logged on at
    # the runner's console): stop the watchdog and then it (switch.py stop), so the start
    # below is the scheduled task's. With the watchdog left on, it started the relay
    # again within its 30 s check, before this stage read the log's size, and the task
    # run was then ignored (IgnoreNew): run 38091604241. The watchdog comes back on for
    # stage 5.
    inst = Path(pkg["install_dir"])
    inst_py = str(inst / "runtime" / "python" / "python.exe")
    run([inst_py, str(inst / "switch.py"), "stop"], timeout=120)
    failed = False
    task = pkg["tasks"][0]
    folder, _, name = task.rpartition("\\")
    r = run(["powershell", "-NoProfile", "-Command",
             f"Set-ScheduledTask -TaskPath '{folder}\\' -TaskName '{name}' -Principal "
             "(New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest)"
             " | Out-Null"])
    print(r.stdout + r.stderr)
    say("4a task set to run without a logon session (test only)", r.returncode == 0)
    log = Path(pkg["log_file"])
    start = log.stat().st_size if log.exists() else 0
    main_proc = None
    run(["schtasks", "/run", "/tn", task])
    up = wait_for_line(log, pkg["startup_log_line"], start, 120)
    say("4b started by the scheduled task", up, "" if up else f"{task} did not bring it up within 120 s")
    failed |= not up
    if not up and main_pids(pkg["main_process_match"]):
        # The task did start it, only slowly: keep waiting rather than start a second
        # copy (which would leave at once on the relay's mutex, but muddle stage 5).
        up = wait_for_line(log, pkg["startup_log_line"], start, 180)
    elif not up:
        cmd = [a.replace("<install_dir>", pkg["install_dir"]).replace("<data_dir>", pkg["data_dir"])
               for a in pkg["main_command"]]
        # python.exe in place of pythonw.exe: pythonw has no stderr, and a relay that
        # dies before its log is set up leaves its traceback only there.
        cmd[0] = cmd[0].replace("pythonw.exe", "python.exe")
        direct_log = (OUT / "main-direct.log").open("w", encoding="utf-8")  # noqa: SIM115
        main_proc = subprocess.Popen(cmd, stdout=direct_log, stderr=subprocess.STDOUT)
        up = wait_for_line(log, pkg["startup_log_line"], start, 180)
    say("4 one round", up, "" if up else f"no {pkg['startup_log_line']!r} in {log} within 180 s")
    if not up:
        if main_proc:
            main_proc.kill()
            try:
                print((OUT / "main-direct.log").read_text(encoding="utf-8", errors="replace")[-4000:])
            except OSError:
                pass
        return 1

    failed |= not restart_after_update(pkg, inst, inst_py, log)

    run(["sc.exe", "start", pkg["services"][0]["name"]])
    wd_log = Path(pkg["data_dir"]) / "watchdog.log"
    time.sleep(5)                      # its first check is 30 s after the start
    wd_start = wd_log.stat().st_size if wd_log.exists() else 0
    pids = main_pids(pkg["main_process_match"])
    for pid in pids:
        run(["taskkill", "/PID", str(pid), "/F"])
    back = False
    deadline = time.time() + 120
    while time.time() < deadline and not back:
        time.sleep(5)
        back = bool(set(main_pids(pkg["main_process_match"])) - set(pids))
    restarted = wait_for_line(wd_log, "跑了一次计划任务（成功）", wd_start, 5)
    try:
        print(wd_log.read_bytes()[wd_start:].decode("utf-8", errors="replace")[-2000:])
    except OSError:
        print(f"no {wd_log}")
    ok5 = back and restarted
    say("5 watchdog", ok5, f"killed {pids}; back: {back}; restart line in watchdog.log: {restarted}")
    failed |= not ok5
    for pid in main_pids(pkg["main_process_match"]):
        run(["taskkill", "/PID", str(pid), "/F"])

    unins = Path(pkg["install_dir"]) / "unins000.exe"
    r = run([str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             f"/LOG={OUT / 'uninstall.log'}"])
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
    return 0 if clean and not failed else 1


RESTART_WITHIN_S = 15      # "within seconds"; the watchdog alone would take up to 30 s


CI_TASK = "\\ArkRelayCI\\restart-soon"


def timeout_without_console() -> float:
    """Seconds a detached `cmd /c timeout /t 3 /nobreak` takes: the old restart_soon's
    wait. Printed as evidence for the cause of #22 (expected: well under 3)."""
    t = time.time()
    subprocess.Popen(["cmd", "/c", "timeout /t 3 /nobreak >nul"],
                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS).wait(30)
    return time.time() - t


def restart_after_update(pkg: dict, inst: Path, inst_py: str, log: Path) -> bool:
    """4c: what an update does at its end - pkg_layout.restart_soon from a process the
    task scheduler started, which then exits, and the relay exits - with the watchdog
    still stopped, so only restart_soon's helper can bring it back. The helper must
    outlive the task's process, and the relay must be running again (a new process)
    within RESTART_WITHIN_S of its exit. Before 2026-10-11 the helper's task run came
    while the relay still lived and was ignored; this stage would have failed (review
    round 7 #22)."""
    print(f"timeout /t 3 without a console took {timeout_without_console():.1f} s", flush=True)
    code = inst / "versions" / (inst / "current.txt").read_text(encoding="ascii").strip()
    caller = OUT / "ci_restart_soon.py"
    caller.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0, sys.argv[1])\n"
                      "import pkg_layout\npkg_layout.restart_soon(Path(sys.argv[2]))\n", encoding="utf-8")
    folder, _, name = CI_TASK.rpartition("\\")
    r = run(["powershell", "-NoProfile", "-Command",
             f"$a = New-ScheduledTaskAction -Execute '{inst_py}' -Argument '\"{caller}\" \"{code}\" \"{inst}\"';"
             f"$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest;"
             f"Register-ScheduledTask -TaskPath '{folder}\\' -TaskName '{name}' -Action $a -Principal $p -Force"
             " | Out-Null"])
    print(r.stdout + r.stderr)
    before = set(main_pids("relaunch"))
    run(["schtasks", "/run", "/tn", CI_TASK])
    helper: set[int] = set()
    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(2)
        helper = set(main_pids("relaunch")) - before
        state = run(["powershell", "-NoProfile", "-Command",
                     f"(Get-ScheduledTask -TaskPath '{folder}\\' -TaskName '{name}').State"]).stdout.strip()
        if helper and state != "Running":
            break
    run(["schtasks", "/delete", "/tn", CI_TASK, "/f"])
    if not helper:
        say("4c restart after an update", False, f"no launch.py relaunch alive after {CI_TASK} ended")
        return False
    old = set(main_pids(pkg["main_process_match"])) - helper
    start = log.stat().st_size if log.exists() else 0
    r = run([inst_py, str(inst / "launch.py"), "stop"], timeout=120)
    t0 = time.time()
    if r.returncode != 0:
        say("4c restart after an update", False, f"launch.py stop exit {r.returncode}")
        return False
    new: set[int] = set()
    while time.time() - t0 < RESTART_WITHIN_S and not new:
        time.sleep(1)
        new = set(main_pids(pkg["main_process_match"])) - old - helper
    took = time.time() - t0
    up = bool(new) and wait_for_line(log, pkg["startup_log_line"], start, 120)
    ok = bool(new) and took <= RESTART_WITHIN_S and up
    say("4c restart after an update", ok,
        f"helper {sorted(helper)} outlived the task; old {sorted(old)}, new {sorted(new)} "
        f"after {took:.0f} s (limit {RESTART_WITHIN_S}); startup line: {up}")
    return ok


def run_main_once(pkg: dict) -> None:
    """After a failed start: run the installed relay with python.exe for 30 s and keep
    what it prints (a relay that dies before its log exists says why only on stderr)."""
    cmd = [a.replace("<install_dir>", pkg["install_dir"]).replace("<data_dir>", pkg["data_dir"])
           for a in pkg["main_command"]]
    cmd[0] = cmd[0].replace("pythonw.exe", "python.exe")
    if not Path(cmd[0]).exists():
        print("no", cmd[0])
        return
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        out = f"exit {r.returncode}\n{r.stdout}{r.stderr}"
    except subprocess.TimeoutExpired as exc:
        # run() has killed it; what it printed so far may come back as bytes
        got = [x.decode("utf-8", "replace") if isinstance(x, bytes) else (x or "")
               for x in (exc.stdout, exc.stderr)]
        out = "still running after 30 s (killed)\n" + "".join(got)
    (OUT / "main-direct.log").write_text(out, encoding="utf-8")
    print(out[-4000:])


def keep_logs() -> None:
    """The relay's, the watchdog's and switch.py's logs next to ours, for the artifact."""
    pkg = json.loads((HANDOVER / "package-items.json").read_text(encoding="utf-8"))
    for name in ("relay.log", "watchdog.log", "switch.log"):
        src = Path(pkg["data_dir"]) / name
        if src.exists():
            shutil.copy2(src, OUT / f"data-{name}")


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        try:
            keep_logs()
        except OSError as exc:
            print("could not copy the data logs:", exc)
    sys.exit(rc)
