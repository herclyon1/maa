"""Switching between the old relay and the package, both ways, on a clean Windows runner.

Run by .github/workflows/package-switch.yml, never on the game machine. What
package_smoke.py does not cover: a machine that already runs the old relay. Here the
old relay is installed first the way main installs it, then:

  1 build        the package (as package_smoke.py)
  2 old relay    main's relay/ files (its manifest.json list, as deploy-relay.sh pushes
                 them) into C:\\ProgramData\\ark-relay, pywin32 into the runner's Python
                 (the machine's Python314 has it, commit 0df8a910), `service.py --startup
                 auto install`, restart-on-failure as on the machine (legacy-items.json:
                 sc qc 2026-10-11 03:41, restart 3 s), started. The old logon launcher
                 task ark-relay, disabled as on the machine, and three more legacy items.
                 A stand-in AUTO-MAS backend (fake_automas.py) on 127.0.0.1:36163 with
                 the old relay's weekly annihilation record in state\\state.json.
  3 switch       the installer, handover on (no /SKIPHANDOVER): old service stopped and
                 disabled, launcher task still disabled, new relay running, AUTO-MAS
                 settings handed over and their old values in state\\automas-handover.json
  3g guard       the relay starts its watchdog again (relay/watchdog_guard.py, looks every
                 GUARD_EVERY_S here): a plain `sc stop` (no marker: not on purpose, and a
                 clean stop fires no failure action) is undone within a minute; with the
                 stop marker switch.py and estop.sh write, the watchdog stays down; marker
                 deleted, it comes back
  4 upgrade      the installer again over it: handover skipped (backup unchanged, no
                 setting written), watchdog updated in place (exit 0), relay running
  5 revert       switch.py revert: AUTO-MAS settings back as before, backup gone, old
                 service running on automatic start, launcher task as before (disabled),
                 watchdog and logon task disabled, new relay stopped
  6 switch again the installer once more: handed over again, new relay running
  7 deploy       scripts/mac/lib/deploy-pkg.sh end to end (deploy_pkg_e2e.sh, ssh and
                 scp stood in): a new version folder, current.txt switched, the watch;
                 on the runner the watch cannot pass (no AUTO-MAS, so no
                 「已挂上 AUTO-MAS 进程句柄」), so the expected end is its automatic way
                 back: exit 12, current.txt on the previous folder, the relay running
  8 handover     automas_handover.py plan / apply / rollback against a second stand-in
                 backend, one case each: this week's annihilation done by the relay,
                 done in an earlier week, never closed by the relay, a map he chose,
                 quick config off, AUTO-MAS busy, AUTO-MAS not answering
  9 uninstall    unins000.exe: AUTO-MAS settings put back, everything of the package and
                 the old relay gone (leftovers.py uninstalled), his .env kept

Each check prints [ok] / [FAIL] / [UNTESTED]; the run fails if any check failed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import package_smoke as P  # noqa: E402
from package_smoke import run, say, wait_for_line  # noqa: E402

ROOT, HANDOVER = P.ROOT, P.HANDOVER
OUT = ROOT / "package-switch"
CI = ROOT / "scripts" / "ci"
PORT, CASE_PORT = 36163, 36164
FAKE = OUT / "fake-automas"           # the AUTO-MAS folder the relay is pointed at
CASES = OUT / "fake-automas-cases"
OLD_SERVICE, OLD_TASK = "ark-relay", "ark-relay"
# Legacy items the uninstall must remove (relay/handover/legacy-items.json, action remove).
OLD_EXTRA_TASKS = ["ark-do", "ark-focus-watch"]
OLD_EXTRA_FILES = [r"C:\ProgramData\ark-do.ps1", r"C:\ProgramData\focus-watch.py"]
ANN_RESTORE = "Chernobog"
# The guard's first look and its interval (relay/watchdog_guard.py FIRST_S / EVERY_S,
# 60 s / 180 s on the machine), shortened through the .env the relay loads.
GUARD_FIRST_S, GUARD_EVERY_S = 10, 15
WD = "ArkRelayWatchdog"           # the map the old relay saved before closing the switch

sys.path.insert(0, str(HANDOVER))
import automas_handover as H  # noqa: E402 - stdlib only

WEEK = H.this_week()
FAILED: list[str] = []


def check(stage: str, ok: "bool | None", detail: str = "") -> bool:
    say(stage, ok, detail)
    if ok is False:
        FAILED.append(stage)
    return bool(ok)


def wait_until(fn, seconds: float, step: float = 2.0) -> bool:
    deadline = time.time() + seconds
    while True:
        if fn():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(step)


def sc_field(verb: str, name: str, field: str) -> str:
    """'RUNNING' from `sc query` STATE, 'AUTO_START' from `sc qc` START_TYPE; '' = no service."""
    r = subprocess.run(["sc.exe", verb, name], capture_output=True, text=True, errors="replace")
    for line in r.stdout.splitlines():
        if line.strip().startswith(field):
            return line.split(":", 1)[1].split()[-1]
    return ""


def task_state(name: str, path: str = "\\") -> str:
    """Ready / Disabled / Running from the Task Scheduler (not localised); '' = no task."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"(Get-ScheduledTask -TaskPath '{path}' -TaskName '{name}' -ErrorAction SilentlyContinue).State"],
                       capture_output=True, text=True, errors="replace")
    return r.stdout.strip()


def new_running(pkg: dict) -> bool:
    return bool(P.main_pids(pkg["main_process_match"]))


def fake_values(d: Path) -> dict:
    scripts = json.loads((d / "config" / "ScriptConfig.json").read_text(encoding="utf-8"))
    setting = json.loads((d / "config" / "Config.json").read_text(encoding="utf-8"))
    import fake_automas as F  # noqa: PLC0415
    maa = scripts[F.MAA]
    user = maa["SubConfigsInfo"]["UserData"][F.UID]
    return {"Annihilation": user["Info"]["Annihilation"],
            "AnnihilationCompletedWeek": user["Data"].get("AnnihilationCompletedWeek"),
            "IfCheckGameUpdate": maa["Run"]["IfCheckGameUpdate"],
            "IfAutoInstallGameApk": maa["Run"]["IfAutoInstallGameApk"],
            "IfSelfStart": setting["Start"]["IfSelfStart"]}


def update_calls(d: Path) -> int:
    try:
        return sum("/update\t" in ln for ln in (d / "calls.log").read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


def start_fake(d: Path, port: int, over: dict) -> subprocess.Popen:
    run([sys.executable, str(CI / "fake_automas.py"), "seed", str(d), json.dumps(over)])
    log = (OUT / f"fake-{port}.log").open("a", encoding="utf-8")  # noqa: SIM115
    proc = subprocess.Popen([sys.executable, str(CI / "fake_automas.py"), "serve", str(d), str(port)],
                            stdout=log, stderr=subprocess.STDOUT)

    def up() -> bool:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/setting/get", data=b"{}")
            with urllib.request.urlopen(req, timeout=3):
                return True
        except OSError:
            return False
    if not wait_until(up, 20, 0.5):
        raise RuntimeError(f"stand-in backend on {port} did not come up")
    return proc


def switch_log(pkg: dict) -> Path:
    return Path(pkg["data_dir"]) / "switch.log"


def size(p: Path) -> int:
    return p.stat().st_size if p.exists() else 0


def tail_from(p: Path, at: int) -> str:
    try:
        return p.read_bytes()[at:].decode("utf-8", errors="replace")
    except OSError:
        return ""


def setup(pkg: dict, name: str) -> int:
    r = run([str(OUT / "setup.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             f"/LOG={OUT / (name + '.log')}"], timeout=900)
    return r.returncode


# ---------- stages ----------

def build(pkg: dict) -> bool:
    if not P.ISCC.exists():
        return check("1 build", False, f"{P.ISCC} not on this runner")
    r = run([sys.executable if a == "python" else str(ROOT / a) if a.endswith(".py") else a
             for a in pkg["build"]] + ["--iscc", str(P.ISCC)], timeout=1800)
    print(r.stdout[-3000:] + r.stderr[-2000:])
    built = sorted(ROOT.glob(pkg["setup_exe_glob"]))
    if r.returncode != 0 or not built:
        return check("1 build", False, f"build exit {r.returncode}")
    shutil.copy2(built[-1], OUT / "setup.exe")
    return check("1 build", True)


def install_old(pkg: dict) -> bool:
    data = Path(pkg["data_dir"])
    manifest = subprocess.run(["git", "show", "origin/main:relay/manifest.json"], cwd=ROOT,
                              capture_output=True, check=True).stdout
    files = list(json.loads(manifest)["files"]) + ["manifest.json"]
    for rel in files:
        blob = subprocess.run(["git", "show", f"origin/main:relay/{rel}"], cwd=ROOT,
                              capture_output=True).stdout
        dst = data / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(blob)
    print(f"old relay: {len(files)} files from origin/main into {data}")
    r = run([sys.executable, "-m", "pip", "install", "--quiet", "pywin32"], timeout=600)
    print(r.stdout[-1000:] + r.stderr[-1000:])
    r = run([sys.executable, str(data / "service.py"), "--startup", "auto", "install"], timeout=120)
    print(r.stdout + r.stderr)
    run(["sc.exe", "failure", OLD_SERVICE, "reset=", "60",
         "actions=", "restart/3000/restart/3000/restart/3000"])
    # The pre-service launcher (legacy-items.json: disabled on the machine, runs ark-relay.ps1
    # at logon). Its script here only leaves a mark, so a run of it would show.
    (data / "ark-relay.ps1").write_text(
        "Set-Content -Path 'C:\\ProgramData\\ark-relay\\launcher-ran.txt' -Value (Get-Date)\n", encoding="utf-8")
    run(["schtasks", "/create", "/tn", OLD_TASK, "/sc", "onlogon", "/ru", "SYSTEM", "/f", "/tr",
         f'powershell -NoProfile -ExecutionPolicy Bypass -File "{data / "ark-relay.ps1"}"'])
    run(["schtasks", "/change", "/tn", OLD_TASK, "/disable"])
    for t in OLD_EXTRA_TASKS:
        run(["schtasks", "/create", "/tn", t, "/sc", "once", "/st", "23:59", "/ru", "SYSTEM", "/f",
             "/tr", "cmd /c exit 0"])
    for f in OLD_EXTRA_FILES:
        Path(f).write_text("legacy\n", encoding="utf-8")
    log = Path(pkg["log_file"])
    at = size(log)
    run(["sc.exe", "start", OLD_SERVICE])
    up = wait_until(lambda: sc_field("query", OLD_SERVICE, "STATE") == "RUNNING", 60)
    booted = up and wait_for_line(log, pkg["startup_log_line"], at, 120)
    check("2a old relay service running", up, sc_field("query", OLD_SERVICE, "STATE"))
    check("2b old relay booted (startup line in relay.log)", booted)
    check("2c old launcher task disabled, as on the machine", task_state(OLD_TASK) == "Disabled", task_state(OLD_TASK))
    return up and booted


def expect_new_on(pkg: dict, stage: str, at: int) -> None:
    text = tail_from(switch_log(pkg), at)
    check(f"{stage}: switch.py says the relay is running", "relay running" in text)
    retried = [ln for ln in text.splitlines() if "watchdog not running after start attempt" in ln]
    if retried:   # switch.start_watchdog had to start it again: worth knowing, not a failure
        print(f"note {stage}: " + " | ".join(retried))
    check(f"{stage}: old service stopped",
          wait_until(lambda: sc_field("query", OLD_SERVICE, "STATE") == "STOPPED", 60),
          sc_field("query", OLD_SERVICE, "STATE"))
    check(f"{stage}: old service disabled", sc_field("qc", OLD_SERVICE, "START_TYPE") == "DISABLED",
          sc_field("qc", OLD_SERVICE, "START_TYPE"))
    check(f"{stage}: old launcher task still disabled", task_state(OLD_TASK) == "Disabled", task_state(OLD_TASK))
    check(f"{stage}: watchdog running",
          wait_until(lambda: sc_field("query", "ArkRelayWatchdog", "STATE") == "RUNNING", 30),
          sc_field("query", "ArkRelayWatchdog", "STATE"))
    folder, _, name = pkg["tasks"][0].rpartition("\\")
    check(f"{stage}: logon task enabled", task_state(name, folder + "\\") in ("Ready", "Running"),
          task_state(name, folder + "\\"))
    check(f"{stage}: new relay running", wait_until(lambda: new_running(pkg), 60))
    check(f"{stage}: no watchdog stop marker left (start_watchdog deletes it)",
          not marker(pkg).exists())


def marker(pkg: dict) -> Path:
    return Path(pkg["data_dir"]) / "watchdog-stopped.txt"


def guard(pkg: dict) -> None:
    """3g: the relay brings back a watchdog nobody stopped on purpose, and only that one."""
    log = Path(pkg["log_file"])
    at = size(log)
    back = GUARD_FIRST_S + 2 * GUARD_EVERY_S + 30
    run(["sc.exe", "stop", WD])
    check("3g guard: watchdog stopped by a plain sc stop",
          wait_until(lambda: sc_field("query", WD, "STATE") == "STOPPED", 30), sc_field("query", WD, "STATE"))
    check(f"3g guard: the relay started it again within {back} s",
          wait_until(lambda: sc_field("query", WD, "STATE") == "RUNNING", back), sc_field("query", WD, "STATE"))
    # Logged once the watchdog has stayed RUNNING for watchdog_guard.STEADY_S (5 s).
    check("3g guard: relay.log says so", wait_for_line(log, "已重新打开，确认在跑", at, 20))

    marker(pkg).write_text("ci\n", encoding="utf-8")
    run(["sc.exe", "stop", WD])
    check("3g guard: watchdog stopped with the marker",
          wait_until(lambda: sc_field("query", WD, "STATE") == "STOPPED", 30), sc_field("query", WD, "STATE"))
    time.sleep(2 * GUARD_EVERY_S + 5)
    check("3g guard: stopped on purpose stays stopped", sc_field("query", WD, "STATE") == "STOPPED",
          sc_field("query", WD, "STATE"))
    marker(pkg).unlink()
    check("3g guard: marker gone, the relay starts it again",
          wait_until(lambda: sc_field("query", WD, "STATE") == "RUNNING", GUARD_EVERY_S + 30),
          sc_field("query", WD, "STATE"))
    check("3g guard: new relay still running", new_running(pkg))


HANDED = {"Annihilation": ANN_RESTORE, "AnnihilationCompletedWeek": WEEK, "IfCheckGameUpdate": True,
          "IfAutoInstallGameApk": True, "IfSelfStart": True}


def main() -> int:
    pkg = json.loads((HANDOVER / "package-items.json").read_text(encoding="utf-8"))
    if todo := __import__("leftovers").unconfirmed(pkg):
        return int(not check("0 names", False, ", ".join(todo)))
    OUT.mkdir(exist_ok=True)
    data = Path(pkg["data_dir"])
    state = data / "state"
    backup = state / H.BACKUP_FILE
    env = dict(P.TEST_ENV)
    env.update({"ARK_AUTOMAS_DIR": str(FAKE), "ARK_HISTORY_DIR": str(FAKE / "history"),
                # the machine's old relay keeps its state here (docs/OPERATIONS.md:548,
                # deploy-relay.sh MC_STATE_ARG); the handover reads state.json from it
                "ARK_STATE_DIR": str(state),
                "ARK_WDGUARD_FIRST_S": str(GUARD_FIRST_S), "ARK_WDGUARD_EVERY_S": str(GUARD_EVERY_S)})
    for d in (FAKE / "history", Path(env["ARK_MAA_DIR"]), Path(env["ARK_MAAEND_DIR"]), Path(env["ARK_OKWW_DIR"])):
        d.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    Path(pkg["env_file"]).write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
    (state / "state.json").write_text(json.dumps(
        {"weekly": {"annihilation": {"done_week": WEEK, "restore_to": ANN_RESTORE}}}), encoding="utf-8")
    fake = start_fake(FAKE, PORT, {})
    before = fake_values(FAKE)
    print("AUTO-MAS stand-in before:", before)

    if not build(pkg):
        return 1
    if not install_old(pkg):
        return 1

    # 3 switch over
    at = size(switch_log(pkg))
    rc = setup(pkg, "install-1")
    check("3 switch: installer exit 0", rc == 0, f"exit {rc}")
    expect_new_on(pkg, "3 switch", at)
    now = fake_values(FAKE)
    check("3 switch: AUTO-MAS settings handed over", now == HANDED, f"{now}")
    check("3 switch: their old values saved", backup.exists())
    check("3 switch: package items present", P.leftovers("installed"))
    guard(pkg)

    # 4 upgrade over it
    at, calls, saved = size(switch_log(pkg)), update_calls(FAKE), backup.read_bytes() if backup.exists() else b""
    rc = setup(pkg, "install-2")
    text = tail_from(switch_log(pkg), at)
    check("4 upgrade: installer exit 0", rc == 0, f"exit {rc}")
    check("4 upgrade: handover skipped", "AUTO-MAS handover already done" in text)
    check("4 upgrade: no AUTO-MAS setting written", update_calls(FAKE) == calls,
          f"{update_calls(FAKE) - calls} updates")
    check("4 upgrade: backup unchanged", backup.exists() and backup.read_bytes() == saved)
    check("4 upgrade: watchdog updated in place", "ark_watchdog.py install -> 0" in text)
    expect_new_on(pkg, "4 upgrade", at)

    # 5 revert
    inst = Path(pkg["install_dir"])
    py = str(inst / "runtime" / "python" / "python.exe")
    log = Path(pkg["log_file"])
    log_at = size(log)
    r = run([py, str(inst / "switch.py"), "revert"], timeout=300)
    print(r.stdout[-3000:] + r.stderr[-2000:])
    check("5 revert: exit 0", r.returncode == 0, f"exit {r.returncode}")
    now = fake_values(FAKE)
    check("5 revert: AUTO-MAS settings as before", now == before, f"{now}")
    check("5 revert: backup gone", not backup.exists())
    check("5 revert: old service running",
          wait_until(lambda: sc_field("query", OLD_SERVICE, "STATE") == "RUNNING", 60),
          sc_field("query", OLD_SERVICE, "STATE"))
    check("5 revert: old service on automatic start", sc_field("qc", OLD_SERVICE, "START_TYPE") == "AUTO_START",
          sc_field("qc", OLD_SERVICE, "START_TYPE"))
    check("5 revert: old relay booted", wait_for_line(log, pkg["startup_log_line"], log_at, 120))
    check("5 revert: old launcher task as before (disabled)", task_state(OLD_TASK) == "Disabled",
          task_state(OLD_TASK))
    check("5 revert: watchdog disabled", sc_field("qc", "ArkRelayWatchdog", "START_TYPE") == "DISABLED",
          sc_field("qc", "ArkRelayWatchdog", "START_TYPE"))
    check("5 revert: watchdog stopped", sc_field("query", "ArkRelayWatchdog", "STATE") == "STOPPED",
          sc_field("query", "ArkRelayWatchdog", "STATE"))
    folder, _, name = pkg["tasks"][0].rpartition("\\")
    check("5 revert: logon task disabled", task_state(name, folder + "\\") == "Disabled",
          task_state(name, folder + "\\"))
    check("5 revert: new relay stopped", wait_until(lambda: not new_running(pkg), 30))

    # 6 switch again
    at = size(switch_log(pkg))
    rc = setup(pkg, "install-3")
    check("6 switch again: installer exit 0", rc == 0, f"exit {rc}")
    expect_new_on(pkg, "6 switch again", at)
    now = fake_values(FAKE)
    check("6 switch again: AUTO-MAS settings handed over again", now == HANDED, f"{now}")
    check("6 switch again: old values saved again", backup.exists())

    deploy(pkg)
    handover_cases(inst)

    # 9 uninstall (the stand-in still answering: the uninstall puts AUTO-MAS back first)
    r = run([str(inst / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
             f"/LOG={OUT / 'uninstall.log'}"])
    check("9 uninstall: exit 0", r.returncode == 0, f"exit {r.returncode}")
    gone = wait_until(lambda: not inst.exists(), 120, 3)
    check("9 uninstall: install folder gone", gone)
    now = fake_values(FAKE)
    check("9 uninstall: AUTO-MAS settings as before", now == before, f"{now}")
    check("9 uninstall: nothing of the package or the old relay left", P.leftovers("uninstalled"))
    left = [n for n in ("service.py", "run.py", "boot_stages.py", "ark_relay", "manifest.json")
            if (data / n).exists()]
    check("9 uninstall: old relay code gone from the data folder", not left, ", ".join(left))
    check("9 uninstall: his .env kept", Path(pkg["env_file"]).exists())
    check("9 uninstall: old relay service gone", sc_field("query", OLD_SERVICE, "STATE") == "")
    fake.kill()
    print("\nFAILED: " + "; ".join(FAILED) if FAILED else "\nall checks passed")
    return 1 if FAILED else 0


def deploy(pkg: dict) -> None:
    """Stage 7: deploy-pkg.sh as deploy-relay.sh runs it, against this runner."""
    app = Path(pkg["install_dir"])
    prev = (app / "current.txt").read_text(encoding="ascii").strip()
    Path(r"C:\Users\Administrator").mkdir(exist_ok=True)     # where deploy-pkg.sh copies its scripts
    bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if not bash.exists():
        check("7 deploy", None, f"no {bash}")
        return
    env_ = dict(__import__("os").environ, WATCH_S="30")
    r = subprocess.run([str(bash), str(CI / "deploy_pkg_e2e.sh")], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=900, env=env_)
    out = r.stdout + r.stderr
    (OUT / "deploy-pkg.log").write_text(out, encoding="utf-8")
    print(out[-6000:])
    new = next((ln.split("→")[1].split("（")[0].strip() for ln in out.splitlines() if "current.txt：" in ln and "→" in ln), "")
    cur = (app / "current.txt").read_text(encoding="ascii").strip()
    check("7 deploy: new version folder committed and current.txt switched to it", bool(new) and new != prev,
          f"{prev} -> {new or '?'}")
    check("7 deploy: new folder kept", bool(new) and (app / "versions" / new / "app_main.py").is_file())
    if r.returncode == 12:
        check("7 deploy: watch failed as expected on the runner, went back by itself (exit 12)", True)
        check("7 deploy: current.txt back on the previous folder", cur == prev, f"current.txt {cur}, before {prev}")
    elif r.returncode == 0:
        check("7 deploy: exit 0 (the watch passed)", True)
        check("7 deploy: current.txt on the new folder", cur == new, f"current.txt {cur}")
    else:
        check("7 deploy: deploy-pkg.sh ended 0 or 12", False, f"exit {r.returncode}")
    check("7 deploy: relay running after it", wait_until(lambda: new_running(pkg), 60))


def handover_cases(inst: Path) -> None:
    """Stage 8: the handover script on its own, against a second stand-in backend."""
    import os  # noqa: PLC0415
    py = str(inst / "runtime" / "python" / "python.exe")
    script = str(inst / "handover" / "automas_handover.py")
    env_ = dict(os.environ, ARK_MAS_PORT=str(CASE_PORT))
    proc = start_fake(CASES, CASE_PORT, {})

    def ho(action: str, sd: Path) -> int:
        r = subprocess.run([py, script, action, "--state-dir", str(sd)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env_, timeout=120)
        print(f"$ automas_handover.py {action} -> {r.returncode}\n{r.stdout}{r.stderr}")
        return r.returncode

    def case(name: str, over: dict, rec: "dict | None", want_rc: int, want: dict) -> None:
        run([sys.executable, str(CI / "fake_automas.py"), "seed", str(CASES), json.dumps(over)])
        sd = OUT / "cases" / name
        shutil.rmtree(sd, ignore_errors=True)
        sd.mkdir(parents=True)
        if rec is not None:
            (sd / "state.json").write_text(json.dumps({"weekly": {"annihilation": rec}}), encoding="utf-8")
        start = fake_values(CASES)
        rc = ho("plan", sd)
        check(f"8 {name}: plan exit {want_rc}, writes nothing",
              rc == want_rc and update_calls(CASES) == 0 and fake_values(CASES) == start, f"exit {rc}")
        rc = ho("apply", sd)
        now = fake_values(CASES)
        got = {k: now[k] for k in want}
        check(f"8 {name}: apply exit {want_rc}, settings {want}", rc == want_rc and got == want,
              f"exit {rc}, {got}")
        rc = ho("rollback", sd)
        check(f"8 {name}: rollback puts everything back", rc == 0 and fake_values(CASES) == start
              and not (sd / H.BACKUP_FILE).exists(), f"exit {rc}, {fake_values(CASES)}")

    done = {"done_week": WEEK, "restore_to": ANN_RESTORE}
    case("this-week", {}, done, 0, {"Annihilation": ANN_RESTORE, "AnnihilationCompletedWeek": WEEK})
    case("earlier-week", {}, {"done_week": "2026-W01", "restore_to": ANN_RESTORE}, 0,
         {"Annihilation": ANN_RESTORE, "AnnihilationCompletedWeek": "2026-W40"})
    case("never-closed-by-relay", {}, {}, 0, {"Annihilation": "Close", "AnnihilationCompletedWeek": "2026-W40"})
    case("his-own-map", {"annihilation": "Annihilation"}, done, 0, {"Annihilation": "Annihilation"})
    case("quick-config-off", {"quick": False}, done, 1,
         {"Annihilation": "Close", "AnnihilationCompletedWeek": "2026-W40", "IfCheckGameUpdate": True})

    # AUTO-MAS busy: every update refused; nothing changes, the backup stays for a later rollback
    run([sys.executable, str(CI / "fake_automas.py"), "seed", str(CASES), "{}"])
    sd = OUT / "cases" / "busy"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "state.json").write_text(json.dumps({"weekly": {"annihilation": done}}), encoding="utf-8")
    start = fake_values(CASES)
    (CASES / "mode.txt").write_text("running", encoding="utf-8")
    rc = ho("apply", sd)
    check("8 busy: apply refused (exit 1), nothing changed", rc == 1 and fake_values(CASES) == start, f"exit {rc}")
    rc = ho("rollback", sd)
    check("8 busy: rollback while busy exits 1 and keeps the backup", rc == 1 and (sd / H.BACKUP_FILE).exists(),
          f"exit {rc}")
    (CASES / "mode.txt").write_text("up", encoding="utf-8")
    rc = ho("rollback", sd)
    check("8 busy: rollback once idle", rc == 0 and fake_values(CASES) == start
          and not (sd / H.BACKUP_FILE).exists(), f"exit {rc}")

    proc.kill()
    proc.wait()
    rc = ho("plan", sd)
    check("8 not answering: exit 2", rc == 2, f"exit {rc}")


def keep_logs() -> None:
    pkg = json.loads((HANDOVER / "package-items.json").read_text(encoding="utf-8"))
    for name in ("relay.log", "watchdog.log", "switch.log"):
        src = Path(pkg["data_dir"]) / name
        if src.exists():
            shutil.copy2(src, OUT / f"data-{name}")
    for d in (FAKE, CASES):
        for f in ("config/ScriptConfig.json", "config/Config.json", "calls.log"):
            if (d / f).exists():
                shutil.copy2(d / f, OUT / f"{d.name}-{f.replace('/', '-')}")
    # The Service Control Manager's own record (start timeouts 7000/7009, crashes 7031/7034):
    # a service that never logged its start leaves its reason only here.
    scm = ("*[System[Provider[@Name='Service Control Manager'] and "
           "(EventID=7000 or EventID=7009 or EventID=7011 or EventID=7023 or EventID=7024 "
           "or EventID=7031 or EventID=7034 or EventID=7036)]]")
    for cmd, name in ((["sc.exe", "qc", OLD_SERVICE], "sc-qc-ark-relay.txt"),
                      (["schtasks", "/query", "/fo", "list"], "schtasks.txt"),
                      (["wevtutil", "qe", "System", f"/q:{scm}", "/f:text", "/c:300", "/rd:true"],
                       "scm-events.txt")):
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        (OUT / name).write_text(r.stdout + r.stderr, encoding="utf-8")


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    finally:
        try:
            keep_logs()
        except OSError as exc:
            print("could not copy the logs:", exc)
    sys.exit(rc)
