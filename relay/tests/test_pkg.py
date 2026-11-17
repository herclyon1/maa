"""Packaged installation layout, service stop loop, switchover, and manifest coverage."""
from __future__ import annotations

# ruff: noqa: PLC0415
import contextlib
import importlib.util
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _parts import check, fails, require, run_parts, tmpdir

_SHARED = (check, fails, require, tmpdir)


def _load(name, path):
    """Load a script outside the relay package as a module."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _quiet(fn, *args):
    """Run `fn`, return (its result, the lines it printed)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*args)
    return rc, buf.getvalue().splitlines()


def _iss_proc(code: str, name: str) -> str:
    """The text of one procedure / function in the installer's [Code] section."""
    m = re.search(rf"\n(?:procedure|function) {name}\b.*?\nend;", code, re.S)
    return m.group(0) if m else ""


def _part_pkg_appfiles_update():
    """A relay deploy keeps every installer-written file current, or refuses loudly."""
    import hashlib
    import subprocess
    import tempfile

    ROOT = Path(__file__).resolve().parents[2]
    PD_PATH = ROOT / "scripts/windows/pkg_deploy.py"


    pd = _load("pkg_deploy", PD_PATH)
    pa = _load("pkg_appfiles", ROOT / "scripts/mac/lib/pkg_appfiles.py")


    def sha(p: Path) -> str:
        return hashlib.sha1(p.read_bytes()).hexdigest()


    FILES = pa.app_files()

    print("[every file the installer writes has an owner in the deploy]")
    iss = (ROOT / "packaging/ark-relay.iss").read_text(encoding="utf-8-sig")
    dests = sorted(set(re.findall(r'^Source: "([^"]+)"', iss, re.M)))
    owner = {
        "legacy.py": "appfiles", "switch.py": "appfiles", "{#Stage}\\launch.py": "appfiles",
        "{#Stage}\\handover\\*": "appfiles", "{#Stage}\\watchdog\\*": "watchdog step (5.3)",
        "{#Stage}\\versions\\*": "version folder (3p/4p)", "{#Stage}\\current.txt": "commit (4p)",
        "{#Stage}\\runtime\\*": "runtime swap (3.0p/4.6p)",
    }
    check("no [Files] entry without an owner", [d for d in dests if d not in owner], [])
    check("the plain files are the ones appfiles carries",
          sorted(FILES), ["handover/automas_handover.py", "handover/leftovers.py", "handover/legacy-items.json",
                          "handover/package-items.json", "launch.py", "legacy.py", "switch.py"])
    build = (ROOT / "packaging/build.py").read_text(encoding="utf-8")
    check("build.py stages launch.py from packaging/ and handover from relay/handover",
          ('HERE / "launch.py"' in build, 'RELAY / "handover"' in build), (True, True))
    check("sources: launch.py, switch.py, legacy.py from packaging/",
          [FILES[k].relative_to(ROOT).as_posix() for k in ("launch.py", "switch.py", "legacy.py")],
          ["packaging/launch.py", "packaging/switch.py", "packaging/legacy.py"])


    def make_app(td: str, old: "dict[str, str]") -> Path:
        """A temp {app} holding the repo's files, except `old` (rel -> other content)."""
        app = Path(td) / "ArkRelay"
        app.mkdir()
        (app / "current.txt").write_text("20261011000000\n", encoding="ascii")
        for rel, src in FILES.items():
            dst = app / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(old[rel].encode() if rel in old else src.read_bytes())
        return app


    def info_of(app: Path) -> str:
        return "\n".join(f"SHA {rel} {pd._sha1(app / rel)}" for rel in FILES)


    def stage_send(app: Path, rels, content=None):
        """What 4.5p does on the machine before `appfiles`: an empty incoming folder holding
    the files sent; returns the <rel>=<sha1> arguments (of the repo file)."""
        _quiet(pd.appfiles_stage, app)
        pairs = []
        for rel in rels:
            dst = app / pd.APPFILES_IN / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes((content or {}).get(rel, FILES[rel].read_bytes()))
            pairs.append(f"{rel}={sha(FILES[rel])}")
        return pairs


    for rel in FILES:
        print(f"[{rel}]")
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td, {})
            check("unchanged: not in the deploy's list", rel in pa.changed(info_of(app), FILES), False)
        with tempfile.TemporaryDirectory() as td:
            old = '{"old": true}\n' if rel.endswith(".json") else "OLD = 1\n"
            app = make_app(td, {rel: old})
            check("changed: in the deploy's list, alone", pa.changed(info_of(app), FILES), [rel])
            rc, out = _quiet(pd.appfiles, app, stage_send(app, [rel]))
            check("changed: swapped", (rc, out), (0, [f"APPFILE {rel}", "APPFILES_OK 1"]))
            check("changed: reads back as the repo file", sha(app / rel), sha(FILES[rel]))
            check("changed: no .new and no incoming folder left",
                  ((app / (rel + ".new")).exists(), (app / pd.APPFILES_IN).exists()), (False, False))
            check("changed: the deploy's list is empty now", pa.changed(info_of(app), FILES), [])
            rc, out = _quiet(pd.appfiles_back, app)
            check("appfiles-back: the old one back", (app / rel).read_text(encoding="utf-8"), old)
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td, {rel: "OLD = 1\n"})
            broken = b"{not json" if rel.endswith(".json") else b"def broken(:\n"
            pairs = [f"{rel}={hashlib.sha1(broken).hexdigest()}"]
            _quiet(pd.appfiles_stage, app)
            (app / pd.APPFILES_IN / rel).parent.mkdir(parents=True, exist_ok=True)
            (app / pd.APPFILES_IN / rel).write_bytes(broken)
            rc, out = _quiet(pd.appfiles, app, pairs)
            check("does not load: exit 1, nothing changed",
                  (rc, out[-1].startswith("APPFILES_FAIL nothing changed"), (app / rel).read_text(encoding="utf-8")),
                  (1, True, "OLD = 1\n"))
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td, {rel: "OLD = 1\n"})
            pairs = stage_send(app, [rel], {rel: FILES[rel].read_bytes()[:-1]})
            rc, out = _quiet(pd.appfiles, app, pairs)
            check("arrived damaged: exit 1, nothing changed",
                  (rc, out[-1].startswith("APPFILES_FAIL nothing changed"), (app / rel).read_text(encoding="utf-8")),
                  (1, True, "OLD = 1\n"))

    print("[several at once, one of them new on the machine; appfiles-back undoes all]")
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td, {"launch.py": "OLD = 1\n", "switch.py": "OLD = 2\n"})
        (app / "handover" / "leftovers.py").unlink()
        want = pa.changed(info_of(app), FILES)
        check("the three in the list", sorted(want), ["handover/leftovers.py", "launch.py", "switch.py"])
        rc, out = _quiet(pd.appfiles, app, stage_send(app, want))
        check("all swapped", (rc, out[-1]), (0, "APPFILES_OK 3"))
        _quiet(pd.appfiles_back, app)
        check("back: old contents, the new one gone",
              ((app / "launch.py").read_text(encoding="utf-8"), (app / "switch.py").read_text(encoding="utf-8"),
               (app / "handover" / "leftovers.py").exists()), ("OLD = 1\n", "OLD = 2\n", False))
        rc, out = _quiet(pd.appfiles_back, app)
        check("back again: nothing left to put back", out, ["APPFILES_BACK 0"])
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td, {"launch.py": "OLD = 1\n"})
        _quiet(pd.appfiles, app, stage_send(app, ["launch.py"]))
        (app / "launch.py").write_text("NEXT = 1\n", encoding="utf-8")
        _quiet(pd.appfiles_stage, app)                       # the next deploy starts
        _quiet(pd.appfiles_back, app)
        check("an earlier deploy's backup is dropped at the next stage (back cannot restore it)",
              (app / "launch.py").read_text(encoding="utf-8"), "NEXT = 1\n")

    print("[deploy-pkg.sh 4.5p in bash: ssh and the package's Python run locally on a temp {app}]")
    # deploy-pkg.sh runs on the Mac only. Its block run in bash on the Windows CI job
    # printed nothing it was asked for (run 38360295330: every check on its output red)
    # and would say nothing about the Mac anyway: this part runs on the Mac (the deploy
    # gate), the Windows job runs the rest of this file (pkg_deploy.py, which runs on
    # the machine).
    ON_MAC_LIKE = sys.platform != "win32"
    pkg_sh = (ROOT / "scripts/mac/lib/deploy-pkg.sh").read_text(encoding="utf-8")
    block = pkg_sh[pkg_sh.index("# >>> appfiles step"):pkg_sh.index("# <<< appfiles step")]
    sha_fn = next(x for x in pkg_sh.splitlines() if x.startswith("pkg_sha1() "))


    def bash_appfiles(app: Path):
        info = subprocess.run([sys.executable, str(PD_PATH), "info", str(app), *FILES],
                              capture_output=True, text=True).stdout
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "info.txt").write_text(info, encoding="utf-8")
            changed = subprocess.run([sys.executable, str(ROOT / "scripts/mac/lib/pkg_appfiles.py"), "changed",
                                      str(Path(td) / "info.txt")], capture_output=True, text=True).stdout.strip()
            log = Path(td) / "calls"
            script = f"""
set -euo pipefail
HERE={str(ROOT / "relay")!r}
SSH_OPTS=(-o ConnectTimeout=15)
USER_AT=Administrator@host
APP_WIN='C:\\Program Files\\ArkRelay'
PKG_DEPLOY='C:\\Users\\Administrator\\ark-pkg-deploy.py'
{sha_fn}
ssh() {{ while [ "$1" = -o ]; do shift 2; done; shift; echo "ssh $*" >>{str(log)!r}; bash -c "$*"; }}
pkg_py() {{ echo "pkg_py $2" >>{str(log)!r}; local c=$2; shift 3; python3 {str(PD_PATH)!r} "$c" {str(app)!r} "$@"; }}
APPFILES_LIST=$(python3 "$HERE/../scripts/mac/lib/pkg_appfiles.py" list)
APP_CHANGED=$1
{block}
if [ -n "$APP_CHANGED" ]; then pkg_appfiles_step && echo STEP_OK || echo "STEP_FAIL $APPFILES_WHY"; else echo NOTHING; fi
"""
            r = subprocess.run(["bash", "-c", script, "step", changed], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.stderr.strip():
                print("    bash stderr:", r.stderr.strip()[-300:])
            calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
            return changed, r.stdout.splitlines(), calls


    if ON_MAC_LIKE:
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td, {})
            changed, out, calls = bash_appfiles(app)
            check("all the same: nothing in the list, no command to the machine", (changed, out, calls), ("", ["NOTHING"], []))
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td, {"launch.py": "OLD = 1\n", "handover/legacy-items.json": "[]\n"})
            changed, out, calls = bash_appfiles(app)
            check("two changed: the list", changed.split(), ["launch.py", "handover/legacy-items.json"])
            check("stage, one tar stream, then appfiles", [c.split()[1] for c in calls], ["appfiles-stage", "tar", "appfiles"])
            check("step OK, each file named", (out[-1], sum("APPFILE " in x for x in out)), ("STEP_OK", 2))
            check("both now the repo's", (sha(app / "launch.py"), sha(app / "handover/legacy-items.json")),
                  (sha(FILES["launch.py"]), sha(FILES["handover/legacy-items.json"])))
            check("nothing else touched", pa.changed(info_of(app), FILES), [])
    else:
        print('  (skipped on Windows: see above)')

    print("[the runtime: a gap when it is not what the repo builds]")
    req = (ROOT / "relay/requirements.txt").read_text(encoding="utf-8")
    want_py = pa.py_version(build)
    pins, loose = pa.pins(req)
    check("requirements.txt pins read (pywin32's win32 marker kept)", (pins, loose), ({"pillow": "12.3.0", "pywin32": "312"}, []))
    check("build.py PY_VERSION read", want_py, "3.14.8")
    good = "RUNTIME_PY=3.14.8\nRUNTIME_PKG pillow==12.3.0\nRUNTIME_PKG pywin32==312\nRUNTIME_PKG pip==25.0\n"
    check("the same: no gap", pa.runtime_gap(good, req, want_py), [])
    check("names compared as PEP 503 (Pillow / pillow)", pa.runtime_gap(good.replace("pillow", "Pillow"), req, want_py), [])
    check("another Python: a gap", len(pa.runtime_gap(good.replace("3.14.8", "3.14.7"), req, want_py)), 1)
    check("another Pillow: a gap naming both versions",
          pa.runtime_gap(good.replace("12.3.0", "12.2.0"), req, want_py), ["pillow 12.2.0 -> 12.3.0 (relay/requirements.txt)"])
    check("pywin32 missing: a gap", pa.runtime_gap(good.replace("RUNTIME_PKG pywin32==312\n", ""), req, want_py),
          ["pywin32 not installed -> 312 (relay/requirements.txt)"])
    check("a pin raised in the repo: a gap", len(pa.runtime_gap(good, req.replace("Pillow==12.3.0", "Pillow==12.4.0"), want_py)), 1)
    check("a new package in the repo: a gap", len(pa.runtime_gap(good, req + "\nrequests==2.32.0\n", want_py)), 1)
    check("a loose requirement cannot be checked: a gap", len(pa.runtime_gap(good, req + "\nrequests>=2\n", want_py)), 1)
    check("a Linux-only line is not for the machine", pa.runtime_gap(good, req + '\nuvloop==0.21; sys_platform == "linux"\n', want_py), [])
    check("info without runtime lines: a gap", len(pa.runtime_gap("", req, want_py)) >= 1, True)
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td, {})
        out = subprocess.run([sys.executable, str(PD_PATH), "info", str(app)], capture_output=True, text=True).stdout
        check("pkg_deploy.py info reports the runtime it runs on",
              f"RUNTIME_PY={sys.version.split()[0]}" in out.splitlines(), True)

    print("[the order in deploy-pkg.sh]")
    anchors = ['info "$APP_WIN" $(cut -f1 <<<"$APPFILES_LIST")', "runtime-gap \"$GATED/pkg-info.txt\"",
               'pkg_py "$PKG_DEPLOY" stage "$APP_WIN"', 'pkg_py "$PKG_DEPLOY" commit "$APP_WIN"',
               "\n  if ! pkg_appfiles_step; then", "\nPKG_ENC=", "$WATCH_S\" deploy --pkg",
               'BACK=$(pkg_py "$PKG_DEPLOY" back "$APP_WIN" "$PREV"', 'appfiles-back "$APP_WIN" | tail -1 | sed \'s/^/    /\'',
               "\npkg_watchdog_step \"$WD_SHA\"\n"]
    pos = [pkg_sh.find(a) for a in anchors]
    check("every anchor there", [a for a, p in zip(anchors, pos, strict=True) if p < 0], [])
    check("info -> runtime gate -> stage -> commit -> 4.5p -> restart -> watch -> rollback (with appfiles-back) -> 5.3",
          pos == sorted(pos), True)
    fail45 = pkg_sh[pkg_sh.find("\n  if ! pkg_appfiles_step; then"):pkg_sh.find("APPFILES_SWAPPED=1")]
    check("4.5p failed: appfiles-back, current.txt back, exit 8 (no restart)",
          ("appfiles-back" in fail45, 'back "$APP_WIN" "$PREV"' in fail45, "exit 8" in fail45, "pkg_restart" in fail45),
          (True, True, True, False))

    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_pkg_install_messages():
    """What the installer and switch.py tell him matches what they did."""

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent


    iss = (ROOT / "packaging" / "ark-relay.iss").read_text(encoding="utf-8-sig")
    code = iss.split("[Code]", 1)[1]
    switch_src = (ROOT / "packaging" / "switch.py").read_text(encoding="utf-8")


    def boxes(body: str) -> "list[str]":
        """The text of each MsgBox in `body`, its string pieces joined."""
        out = []
        for m in re.finditer(r"MsgBox\((.*?),\s*mb\w+,", body, re.S):
            out.append("".join(re.findall(r"'([^']*)'", m.group(1))))
        return out


    print("[a failed switch-over: the box says what happened]")
    step = _iss_proc(code, "CurStepChanged")
    texts = boxes(step)
    check("CurStepChanged has message boxes", len(texts) >= 1, True)
    check("no box says the old relay took over", [t for t in texts if "退回老中继" in t], [])
    failed_box = next((t for t in texts if "新中继没有装好" in t), "")
    check("the failed-switch box says the new relay was switched on again",
          "重新打开" in failed_box, True)
    check("the failed-switch box names launch.py rollback",
          "launch.py" in failed_box and "rollback" in failed_box, True)
    check("the failed-switch box points at switch.log", "switch.log" in failed_box, True)

    print("[a cancelled upgrade whose resume failed: a restart, not a re-login]")
    # switch.py stop writes the stop marker; a resume that fails before start_watchdog leaves
    # it, and the relay's guard leaves the watchdog down until the next boot (switch.py
    # WATCHDOG_MARKER), so a re-login brings back the relay but not its watchdog.
    resume_box = " ".join(boxes(_iss_proc(code, "DeinitializeSetup")))
    check("the failed-resume box does not promise a re-login", "重新登录" in resume_box, False)
    check("the failed-resume box says a restart brings it back", "重启电脑" in resume_box, True)

    print("[switch.py's own lines say the same]")
    for phrase in ("reverting to the old relay", "the old relay back on", "退回老中继"):
        check(f"switch.py no longer prints {phrase!r}", phrase in switch_src.split('"""', 2)[2], False)
    check("no function named after going back to the old relay",
          "_back_to_old" in switch_src, False)
    check("the docstring no longer promises 'the new one or the old one'",
          "the new one or the old one" in switch_src, False)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_pkg_layout_names():
    """Every pkg_layout name the packaged relay's callers use exists in pkg_layout.py."""
    import ast

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    CALLERS = {
        RELAY / "app_main.py": "pkg_layout",
        ROOT / "scripts" / "windows" / "pkg_deploy.py": "pl",
    }

    tree = ast.parse((RELAY / "pkg_layout.py").read_text(encoding="utf-8"))
    defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    defined |= {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
                if isinstance(t, ast.Name)}
    defined |= {a.asname or a.name for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names}

    for path, alias in CALLERS.items():
        used = set(re.findall(rf"\b{alias}\.([A-Za-z_]\w*)", path.read_text(encoding="utf-8")))
        missing = sorted(used - defined)
        print(f"{'ok' if not missing else 'FAIL'} {path.name}: uses {sorted(used)}; missing {missing}")
        if not used:
            fails.append(f"{path.name}: no {alias}.x use found (alias changed?)")
        if missing:
            fails.append(f"{path.name}: {missing}")

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_pkg_pin_whole_write():
    """The rollback pin and current.txt are written whole: temp file, then os.replace."""
    import os

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import pkg_layout


    code = tmpdir()
    (code / "state").mkdir()
    pkg_layout._pin(code, 20261012111426)
    check("pin written", pkg_layout._pinned(code), 20261012111426)

    real_replace = os.replace


    def cut(*_a, **_k):
        raise OSError("power cut")


    os.replace = cut
    try:
        pkg_layout._pin(code, 20261012130559)
    except OSError:
        pass
    os.replace = real_replace
    check("a write cut before the swap keeps the old pin", pkg_layout._pinned(code), 20261012111426)

    app = tmpdir()
    pkg_layout._set_current(app, "20261012111426")
    os.replace = cut
    try:
        pkg_layout._set_current(app, "20261012130559")
    except OSError:
        pass
    os.replace = real_replace
    check("a write cut before the swap keeps current.txt", pkg_layout.current(app), "20261012111426")

    pkg_layout._pin(code, 0)
    check("pin 0 removes the file", (code / "state" / pkg_layout.PIN_FILE).exists(), False)

    # 清单-1108 A-07: after a rollback the record names the code that runs, and the pin is
    # the floor selfupdate.check compares against (the version rolled away from is not new).
    from ark_relay.features import selfupdate
    root = tmpdir()
    here = root / "20261012111426"
    (here / "state").mkdir(parents=True)
    pkg_layout._pin(here, 20261012130559)
    pkg_layout.record_running_version(here)
    check("a rolled-back relay records the version it runs", selfupdate._applied_version(here), 20261012111426)
    check("…and check counts from the version it rolled away from", selfupdate._rollback_floor(here), 20261012130559)
    check("no pin: no floor", selfupdate._rollback_floor(tmpdir()), 0)

    print("\n" + ("all checks passed" if not fails else f"{len(fails)} FAILED: {fails}"))


def _part_pkg_runtime_update():  # noqa: C901
    """A relay deploy swaps the installed relay's runtime when it is not what the repo builds."""
    import os
    import subprocess
    import tempfile
    import zipfile

    ROOT = Path(__file__).resolve().parents[2]
    PD_PATH = ROOT / "scripts/windows/pkg_deploy.py"
    PA_PATH = ROOT / "scripts/mac/lib/pkg_appfiles.py"


    pd = _load("pkg_deploy", PD_PATH)
    pa = _load("pkg_appfiles", PA_PATH)
    build = _load("build", ROOT / "packaging/build.py")


    WANT_PY = pa.py_version((ROOT / "packaging/build.py").read_text(encoding="utf-8"))
    PINS = build.runtime_pins()

    print("[build.py: what the runtime is built from]")
    check("PY_VERSION", build.PY_VERSION, "3.14.8")
    check("the embeddable zip of that version", build.EMBED_URL.endswith(f"/{build.PY_VERSION}/python-{build.PY_VERSION}-embed-amd64.zip"), True)
    check("pins from requirements.txt's Windows lines, pywin32 included", PINS, ["pillow==12.3.0", "pywin32==312"])
    for wf in ("relay-windows.yml", "package-windows.yml", "package-switch.yml"):
        got = re.findall(r"python-version: '([^']+)'", (ROOT / ".github/workflows" / wf).read_text(encoding="utf-8"))
        # relay-windows.yml sets it up once per job (tests, day-replay); each must be the same.
        check(f"{wf} sets up the same Python", sorted(set(got)) if got else got, [build.PY_VERSION])

    print("[build.py stage_runtime: pins as arguments, laid out as the installer has it]")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cache = td / "cache"
        cache.mkdir()
        with zipfile.ZipFile(cache / Path(build.EMBED_URL).name, "w") as z:
            z.writestr("python.exe", "EXE")
            z.writestr("python314._pth", "python314.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n")
        calls = []
        real_run = build.subprocess.run

        def fake_run(cmd, check=False, **kw):
            calls.append(cmd)
            site = Path(cmd[cmd.index("--target") + 1])
            (site / "pywin32_system32").mkdir(parents=True)
            (site / "pywin32_system32" / "pywintypes314.dll").write_text("DLL")
            (site / "win32").mkdir()
            (site / "win32" / "pythonservice.exe").write_text("SVC")
            return subprocess.CompletedProcess(cmd, 0)

        build.subprocess.run = fake_run
        try:
            py = build.stage_runtime(td / "out", cache)
        finally:
            build.subprocess.run = real_run
        cmd = calls[0]
        check("one pip run, the pins as arguments, no -r", (len(calls), cmd[-2:], "-r" in cmd), (1, PINS, False))
        check("for the machine: win_amd64, cp, this Python version",
              (cmd[cmd.index("--platform") + 1], cmd[cmd.index("--implementation") + 1], cmd[cmd.index("--python-version") + 1]),
              ("win_amd64", "cp", build.PY_VERSION))
        check("returns runtime/python", py, td / "out" / "runtime" / "python")
        check("._pth opened to site-packages, site imported",
              (py / "python314._pth").read_text(encoding="utf-8").splitlines()[-2:], ["Lib\\site-packages", "import site"])
        check("pywin32's DLLs and pythonservice.exe next to python.exe",
              ((py / "pywintypes314.dll").is_file(), (py / "pythonservice.exe").is_file()), (True, True))


    # ---------- the machine side, with the services and processes stood in ----------

    def probe_json(py, pkgs):
        return py, dict(pkgs)


    GOOD = probe_json(WANT_PY, {"Pillow": "12.3.0", "pywin32": "312", "pip": "25.0"})
    OLD = probe_json("3.14.7", {"Pillow": "12.3.0", "pywin32": "311"})


    class FakeRuntime:
        """Records each call. probe answers by what the python.exe probed holds (OLD / NEW);
    holders() returns `busy` that many times before it is empty."""

        def __init__(self, kind="AUTO", busy=0, new=GOOD, fail=()):
            self.kind, self.busy, self.new, self.fail = kind, busy, new, set(fail)
            self.calls = []

        def start_type(self):
            self.calls.append("start_type")
            return self.kind

        def stop_watchdog(self):
            self.calls.append("stop_watchdog")
            return "stuck" if "stop_watchdog" in self.fail else ""

        def start_watchdog(self):
            self.calls.append("start_watchdog")
            if "start_watchdog" in self.fail:
                self.fail.discard("start_watchdog")       # the start on the previous runtime works
                return "stopped again during its start"
            return ""

        def stop_relay(self):
            self.calls.append("stop_relay")
            if "stop_relay" in self.fail:
                raise FileNotFoundError(2, "The system cannot find the file specified")
            return ""

        def holders(self):
            self.calls.append("holders")
            if self.busy == "always" or self.busy > 0:
                if self.busy != "always":
                    self.busy -= 1
                return ["5912 pythonw.exe"]
            return []

        def probe(self, exe):
            what = Path(exe).read_text(encoding="utf-8")
            self.calls.append(("probe", what))
            if "probe" in self.fail:
                raise OSError("exit 3221225781")
            return self.new if what == "NEW" else OLD

        def sleep(self, s):
            pass


    def make_app(td, *, staged=True):
        """A temp {app}: runtime\\python (OLD) and, staged, runtime\\.incoming with python\\
    (NEW) and files.sha1 as the deploy sends them."""
        app = Path(td) / "ArkRelay"
        cur = app / "runtime" / "python"
        (cur / "Lib").mkdir(parents=True)
        (cur / "python.exe").write_text("OLD", encoding="utf-8")
        (cur / "pythonservice.exe").write_text("OLDSVC", encoding="utf-8")
        (cur / "Lib" / "old.py").write_text("x = 1\n", encoding="utf-8")
        if staged:
            inc = app / "runtime" / pd.RUNTIME_IN
            new = inc / "python"
            (new / "Lib" / "site-packages").mkdir(parents=True)
            (new / "python.exe").write_text("NEW", encoding="utf-8")
            (new / "pythonservice.exe").write_text("NEWSVC", encoding="utf-8")
            (new / "Lib" / "site-packages" / "pywintypes.py").write_text("y = 2\n", encoding="utf-8")
            (inc / pd.RUNTIME_LIST).write_text("\n".join(pa.runtime_list(new)) + "\n", encoding="utf-8")
        return app


    def tree(folder: Path):
        return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8")
                for p in sorted(folder.rglob("*")) if p.is_file()} if folder.is_dir() else None


    OLD_TREE = {"Lib/old.py": "x = 1\n", "python.exe": "OLD", "pythonservice.exe": "OLDSVC"}
    NEW_TREE = {"Lib/site-packages/pywintypes.py": "y = 2\n", "python.exe": "NEW", "pythonservice.exe": "NEWSVC"}

    print("[runtime-check: the runtime sent, checked and run before anything changes]")
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        ops = FakeRuntime()
        rc, out = _quiet(pd.runtime_check, app, WANT_PY, PINS, ops)
        check("complete and the one wanted: ready, its python.exe named",
              (rc, out[-1]), (0, f"RUNTIME_READY={app / 'runtime' / pd.RUNTIME_IN / 'python' / 'python.exe'}"))
        check("every file counted", out[0], "RUNTIME_FILES 3")
        check("only the new python.exe was run, nothing stopped", ops.calls, [("probe", "NEW")])
        check("runtime\\python untouched", tree(app / "runtime" / "python"), OLD_TREE)
    for label, damage, want in (
            ("a file arrived damaged", lambda inc: (inc / "python" / "python.exe").write_text("NEX", encoding="utf-8"), "file(s) wrong"),
            ("a file not in the list", lambda inc: (inc / "python" / "extra.dll").write_text("?", encoding="utf-8"), "not listed: extra.dll"),
            ("a listed file missing", lambda inc: (inc / "python" / "Lib" / "site-packages" / "pywintypes.py").unlink(), "pywintypes.py: MISSING"),
            ("no list", lambda inc: (inc / pd.RUNTIME_LIST).unlink(), "no files.sha1")):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td)
            damage(app / "runtime" / pd.RUNTIME_IN)
            ops = FakeRuntime()
            rc, out = _quiet(pd.runtime_check, app, WANT_PY, PINS, ops)
            check(f"{label}: refused, nothing run", (rc, out[-1].startswith("RUNTIME_FAIL nothing changed"), want in out[-1], ops.calls),
                  (1, True, True, []))
    for label, ops, want in (
            ("another Python", FakeRuntime(new=probe_json("3.14.7", {"Pillow": "12.3.0", "pywin32": "312"})), "Python 3.14.7 != " + WANT_PY),
            ("pywin32 not the pin", FakeRuntime(new=probe_json(WANT_PY, {"Pillow": "12.3.0", "pywin32": "311"})), "pywin32 311 != 312"),
            ("it does not run", FakeRuntime(fail={"probe"}), "does not run")):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td)
            rc, out = _quiet(pd.runtime_check, app, WANT_PY, PINS, ops)
            check(f"{label}: refused", (rc, want in out[-1]), (1, True))
    check("names compared as PEP 503", pd.runtime_gaps(probe_json(WANT_PY, {"PILLOW": "12.3.0", "PyWin32": "312"}), WANT_PY, PINS), [])

    print("[runtime: different = copy beside, stop, two renames, verify, watchdog on the new one]")
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        ops = FakeRuntime(busy=2)
        rc, out = _quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
        check("exit 0, swapped", (rc, out[-1]), (0, f"RUNTIME=swapped {WANT_PY} {' '.join(PINS)}"))
        check("calls in order: watchdog stopped first, waited until nothing runs from it, the new one probed, watchdog started",
              ops.calls, ["start_type", "stop_watchdog", "stop_relay", "holders", "holders", "holders", ("probe", "NEW"), "start_watchdog"])
        check("steps printed in order", [x for x in out if x.startswith("RUNTIME_STEP")],
              ["RUNTIME_STEP copy", "RUNTIME_STEP stop", "RUNTIME_STEP rename", "RUNTIME_STEP verify", "RUNTIME_STEP watchdog"])
        check("no python.next left", (app / "runtime" / pd.RUNTIME_NEXT).exists(), False)
        check("runtime\\python is the new one", tree(app / "runtime" / "python"), NEW_TREE)
        check("the old one is python.prev", tree(app / "runtime" / pd.RUNTIME_PREV), OLD_TREE)
        check(".incoming kept (it is the swap's interpreter, and runtime-back's)",
              tree(app / "runtime" / pd.RUNTIME_IN / "python"), NEW_TREE)
        rc, out = _quiet(pd.runtime_back, app, FakeRuntime())
        check("runtime-back after it: the old one back", (rc, out[-1], tree(app / "runtime" / "python")),
              (0, "RUNTIME_BACK restored", OLD_TREE))
        check("runtime-back: the new one kept as python.failed", tree(app / "runtime" / pd.RUNTIME_FAILED), NEW_TREE)
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        ops = FakeRuntime(kind="DISABLED")
        rc, out = _quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
        check("watchdog disabled (a revert): swapped, the watchdog neither stopped nor started",
              (rc, ops.calls), (0, ["start_type", "stop_relay", "holders", ("probe", "NEW")]))

    print("[runtime: a failure before the rename changes nothing]")
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td, staged=False)
        ops = FakeRuntime()
        rc, out = _quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
        check("nothing staged: exit 1, no call at all", (rc, ops.calls, tree(app / "runtime" / "python")), (1, [], OLD_TREE))
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        ops = FakeRuntime(busy="always")
        rc, out = _quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
        check("still running from it after the stops: exit 1, nothing changed, the watchdog started again",
              (rc, out[-2].startswith("RUNTIME_FAIL stop: still running"), ops.calls[-1], tree(app / "runtime" / "python"),
               (app / "runtime" / pd.RUNTIME_PREV).exists()), (1, True, "start_watchdog", OLD_TREE, False))
        check("waited RUNTIME_FREE_S looks", ops.calls.count("holders"), pd.RUNTIME_FREE_S)
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        ops = FakeRuntime(fail={"stop_watchdog"})
        rc, out = _quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
        check("watchdog does not stop: exit 1, the relay not even stopped, nothing changed",
              (rc, "stop_relay" in ops.calls, tree(app / "runtime" / "python")), (1, False, OLD_TREE))
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        ops = FakeRuntime()
        real_rename, tries = os.rename, []

        def locked(src, dst):
            tries.append(1)
            raise PermissionError(5, "Access is denied", str(src))

        pd.os.rename = locked
        try:
            rc, out = _quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
        finally:
            pd.os.rename = real_rename
        check("the folder cannot be renamed: tried RENAME_TRIES times, exit 1, nothing changed, watchdog started",
              (len(tries), rc, out[-2].startswith("RUNTIME_FAIL rename"), ops.calls[-1], tree(app / "runtime" / "python")),
              (pd.RENAME_TRIES, 1, True, "start_watchdog", OLD_TREE))

    print("[runtime: a failure after the rename puts the previous runtime back]")
    for label, ops, step in (
            ("the new one is not the one wanted", FakeRuntime(new=probe_json(WANT_PY, {"Pillow": "12.3.0", "pywin32": "311"})), "verify"),
            ("the new one does not run", FakeRuntime(fail={"probe"}), "verify"),
            ("the watchdog does not come up on it", FakeRuntime(fail={"start_watchdog"}), "watchdog")):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td)
            rc, out = _quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
            check(f"{label}: exit 1, failed at {step}, restored",
                  (rc, out[-2].startswith(f"RUNTIME_FAIL {step}"), out[-1]), (1, True, "RUNTIME_RESTORED the previous runtime is back"))
            check(f"{label}: runtime\\python is the old one again, the new one in python.failed, no python.prev",
                  (tree(app / "runtime" / "python"), tree(app / "runtime" / pd.RUNTIME_FAILED), (app / "runtime" / pd.RUNTIME_PREV).exists()),
                  (OLD_TREE, NEW_TREE, False))
            check(f"{label}: stopped again before the restore, watchdog started last",
                  (ops.calls.count("stop_relay"), ops.calls[-1]), (2, "start_watchdog"))
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        ops = FakeRuntime()
        real_copytree = pd.shutil.copytree

        def half_copy(src, dst, **kw):
            Path(dst).mkdir()
            (Path(dst) / "python.exe").write_text("NE", encoding="utf-8")
            raise OSError(28, "There is not enough space on the disk")

        pd.shutil.copytree = half_copy
        try:
            rc, out = _quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
        finally:
            pd.shutil.copytree = real_copytree
        check("the copy beside it breaks half way: exit 1 before anything is stopped, the half copy gone",
              (rc, out[-1].startswith("RUNTIME_FAIL copy"), ops.calls, tree(app / "runtime" / "python"),
               (app / "runtime" / pd.RUNTIME_NEXT).exists()), (1, True, [], OLD_TREE, False))
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        ops = FakeRuntime()
        real_rename, seen = os.rename, []

        def second_fails(src, dst):
            seen.append(Path(src).name)
            if Path(src).name == pd.RUNTIME_NEXT:
                raise PermissionError(5, "Access is denied", str(src))
            real_rename(src, dst)

        pd.os.rename = second_fails
        try:
            rc, out = _quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
        finally:
            pd.os.rename = real_rename
        check("python.next cannot take the name: restored, python.prev back as python",
              (rc, out[-2].startswith("RUNTIME_FAIL rename"), out[-1], tree(app / "runtime" / "python"),
               (app / "runtime" / pd.RUNTIME_PREV).exists()),
              (1, True, "RUNTIME_RESTORED the previous runtime is back", OLD_TREE, False))

    print("[the relay is stopped with the swap's own Python: runtime\\python may be missing then]")
    real_run, seen_cmd = pd.subprocess.run, []


    def capture(cmd, **kw):
        seen_cmd.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")


    pd.subprocess.run = capture
    try:
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / "ArkRelay"
            check("WinRuntime.stop_relay answers", pd.WinRuntime(app).stop_relay(), "")
    finally:
        pd.subprocess.run = real_run
    check("launch.py stop runs on sys.executable, not on runtime\\python\\python.exe",
          seen_cmd[-1], [sys.executable, str(app / "launch.py"), "stop"])
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        (app / "runtime" / "python").rename(app / "runtime" / pd.RUNTIME_PREV)   # the swap died between its renames
        ops = FakeRuntime(fail={"stop_relay"})
        rc, out = _quiet(pd.runtime_back, app, ops)
        check("runtime-back with no runtime\\python and a relay stop that raises: still restored",
              (rc, out[-1], tree(app / "runtime" / "python"), ops.calls[-1]), (0, "RUNTIME_BACK restored", OLD_TREE, "start_watchdog"))

    print("[runtime-back, runtime-stage, runtime-done]")
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        ops = FakeRuntime()
        rc, out = _quiet(pd.runtime_back, app, ops)
        check("no python.prev: nothing put back, only the watchdog started (a lost answer may have stopped it)",
              (rc, out, ops.calls, tree(app / "runtime" / "python")), (0, ["RUNTIME_BACK nothing"], ["start_type", "start_watchdog"], OLD_TREE))
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        for name in (pd.RUNTIME_PREV, pd.RUNTIME_FAILED):
            (app / "runtime" / name).mkdir()
            (app / "runtime" / name / "python.exe").write_text("EARLIER", encoding="utf-8")
        rc, out = _quiet(pd.runtime_stage, app)
        check("runtime-stage: an empty .incoming, an earlier change's python.prev and python.failed gone",
              (out, os.listdir(app / "runtime" / pd.RUNTIME_IN), (app / "runtime" / pd.RUNTIME_PREV).exists(),
               (app / "runtime" / pd.RUNTIME_FAILED).exists(), tree(app / "runtime" / "python")),
              ([f"RUNTIME_IN={app / 'runtime' / pd.RUNTIME_IN}"], [], False, False, OLD_TREE))
        rc, out = _quiet(pd.runtime_back, app, FakeRuntime())
        check("so a runtime-back in this deploy cannot bring back an earlier runtime", out, ["RUNTIME_BACK nothing"])
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        _quiet(pd.runtime_swap, app, WANT_PY, PINS, FakeRuntime())
        _quiet(pd.runtime_done, app)
        check("runtime-done: .incoming gone, python.prev kept",
              ((app / "runtime" / pd.RUNTIME_IN).exists(), tree(app / "runtime" / pd.RUNTIME_PREV)), (False, OLD_TREE))


    # ---------- deploy-pkg.sh in bash ----------

    pkg_sh = (ROOT / "scripts/mac/lib/deploy-pkg.sh").read_text(encoding="utf-8")


    def block(name):
        return pkg_sh[pkg_sh.index(f"# >>> {name}"):pkg_sh.index(f"# <<< {name}")]


    FAKE_BUILD = r"""#!/bin/bash
# Stands in for "python3.14 packaging/build.py --runtime-only DIR": a runtime whose
# python.exe is a shell script answering pkg_deploy.py's PROBE.
set -e
[ -n "$FAIL_BUILD" ] && { echo "pip: no matching distribution" >&2; exit 1; }
py="$3/runtime/python"
mkdir -p "$py/Lib"
printf '#!/bin/sh\necho %s\n' "'$PROBE_OUT'" >"$py/python.exe"
chmod +x "$py/python.exe"
echo SVC >"$py/pythonservice.exe"
echo "x = 1" >"$py/Lib/site.py"
"""


    def bash_prepare(app: Path, probe_out: str, fail_build=False):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            log = td / "calls"
            fake = td / "python3.14"
            fake.write_text(FAKE_BUILD, encoding="utf-8")
            fake.chmod(0o755)
            script = f"""
set -euo pipefail
HERE={str(ROOT / "relay")!r}
SSH_OPTS=(-o ConnectTimeout=15)
USER_AT=Administrator@host
APP_WIN='C:\\Program Files\\ArkRelay'
PKG_DEPLOY='C:\\Users\\Administrator\\ark-pkg-deploy.py'
PY314={str(fake)!r}
ssh() {{ while [ "$1" = -o ]; do shift 2; done; shift; echo "ssh $*" >>{str(log)!r}; bash -c "$*"; }}
pkg_py() {{ echo "pkg_py $2" >>{str(log)!r}; local c=$2; shift 3; python3 {str(PD_PATH)!r} "$c" {str(app)!r} "$@"; }}
{block("runtime prepare")}
if pkg_runtime_prepare; then echo "READY $RUNTIME_PY_EXE"; echo "WANT ${{RUNTIME_WANT[*]}}"; else echo "NOT_READY $RUNTIME_WHY"; fi
"""
            env = dict(os.environ, PROBE_OUT=probe_out, FAIL_BUILD="1" if fail_build else "")
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
            if r.stderr.strip():
                print("    bash stderr:", r.stderr.strip()[-300:])
            calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
            return r.stdout.splitlines(), [c.split()[1] for c in calls]


    print("[deploy-pkg.sh 3.0p in bash: built, staged, sent, checked and run on a temp {app}]")
    GOOD_JSON = '{"py": "%s", "pkgs": {"Pillow": "12.3.0", "pywin32": "312"}}' % WANT_PY
    # The "python.exe" probed here is a shell script, which Windows cannot start, and the
    # block's tar takes macOS's --no-mac-metadata: this part runs on the Mac (the deploy
    # gate), where 3.0p itself runs; the Windows CI job runs the rest of this file. The
    # same holds for the gate and 4.6p blocks below: deploy-pkg.sh runs on the Mac only,
    # and run in bash on the Windows CI job they printed nothing they were asked for
    # (run 38360295330: every check on their output red).
    ON_MAC_LIKE = sys.platform != "win32"
    if not ON_MAC_LIKE:
        print("  (skipped on Windows: see above)")
    else:
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td, staged=False)
            out, calls = bash_prepare(app, GOOD_JSON)
            check("ready: the new python.exe in .incoming named", out[-2], f"READY {app / 'runtime' / pd.RUNTIME_IN / 'python' / 'python.exe'}")
            check("the wanted runtime as pkg_deploy.py takes it", out[-1], f"WANT {WANT_PY} {' '.join(PINS)}")
            check("stage, one tar stream, check", calls, ["runtime-stage", "tar", "runtime-check"])
            check("runtime\\python untouched", tree(app / "runtime" / "python"), OLD_TREE)
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td, staged=False)
            out, calls = bash_prepare(app, '{"py": "3.14.7", "pkgs": {"Pillow": "12.3.0", "pywin32": "311"}}')
            check("the machine runs a different one: not ready, said why", (out[-1].startswith("NOT_READY nothing changed: the new runtime is not the one wanted"),
                                                                             tree(app / "runtime" / "python")), (True, OLD_TREE))
        with tempfile.TemporaryDirectory() as td:
            app = make_app(td, staged=False)
            out, calls = bash_prepare(app, GOOD_JSON, fail_build=True)
            check("the build fails on the Mac: not ready, no command to the machine",
                  (out[-1].startswith("NOT_READY 在 Mac 上打运行环境失败"), calls), (True, []))

    print("[deploy-pkg.sh gate: the same runtime = nothing built, sent or run]")
    gate = pkg_sh[pkg_sh.index("RUNTIME_SWAP=0\n"):pkg_sh.index("INC=$(pkg_py")]


    def bash_gate(info: str, prepare_ok=True):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "pkg-info.txt").write_text(info, encoding="utf-8")
            script = f"""
set -euo pipefail
HERE={str(ROOT / "relay")!r}
GATED={td!r}
PREV=20261011000000
pkg_runtime_prepare() {{ echo PREPARE_CALLED; {"true" if prepare_ok else "RUNTIME_WHY=x; false"}; }}
{gate}
echo "SWAP=$RUNTIME_SWAP"
"""
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace")
            return r.returncode, r.stdout.splitlines()


    same = f"RUNTIME_PY={WANT_PY}\nRUNTIME_PKG pillow==12.3.0\nRUNTIME_PKG pywin32==312\n"
    if ON_MAC_LIKE:
        rc, out = bash_gate(same)
        check("the same: no prepare, no swap", (rc, out), (0, ["SWAP=0"]))
        rc, out = bash_gate(same.replace("pywin32==312", "pywin32==311").replace(WANT_PY, "3.14.7"))
        check("different: both gaps named, prepared, swap later", (rc, "PREPARE_CALLED" in out, out[-1], sum("->" in x for x in out)),
              (0, True, "SWAP=1", 2))
        rc, out = bash_gate(same.replace(WANT_PY, "3.14.7"), prepare_ok=False)
        check("different, not ready: exit 5 before any code is pushed", (rc, "SWAP=1" in out), (5, False))
    else:
        print('  (skipped on Windows: see the 3.0p part)')

    print("[deploy-pkg.sh 4.6p in bash: the machine's answer read]")


    def bash_swap(answer: str, info_after: str):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "calls"
            (Path(td) / "answer").write_text(answer + "\n", encoding="utf-8")
            (Path(td) / "info").write_text(info_after, encoding="utf-8")
            script = f"""
set -euo pipefail
HERE={str(ROOT / "relay")!r}
GATED={td!r}
APP_WIN='C:\\Program Files\\ArkRelay'
PKG_DEPLOY='C:\\Users\\Administrator\\ark-pkg-deploy.py'
RUNTIME_PY_EXE='C:\\Program Files\\ArkRelay\\runtime\\.incoming\\python\\python.exe'
RUNTIME_WANT=({WANT_PY} {' '.join(PINS)})
pkg_py_at() {{ echo "pkg_py_at $1 $3 ${{*:4}}" >>{str(log)!r}; cat {str(Path(td) / "answer")!r}; }}
pkg_py() {{ echo "pkg_py $2" >>{str(log)!r}; cat {str(Path(td) / "info")!r}; }}
{block("runtime swap")}
if pkg_runtime_swap; then echo "SWAPPED $RUNTIME_TOUCHED"; else echo "FAILED $RUNTIME_TOUCHED $RUNTIME_WHY"; fi
"""
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.stderr.strip():
                print("    bash stderr:", r.stderr.strip()[-300:])
            return r.stdout.splitlines(), log.read_text(encoding="utf-8").splitlines() if log.exists() else []


    if ON_MAC_LIKE:
        ok_answer = f"RUNTIME_STEP stop\nRUNTIME_STEP copy\nRUNTIME_STEP verify\nRUNTIME_STEP watchdog\nRUNTIME=swapped {WANT_PY}"
        out, calls = bash_swap(ok_answer, same)
        check("swapped and the same check passes on what now runs", out[-1], "SWAPPED 1")
        check("the swap runs on the new runtime's python.exe, with the wanted runtime; then info on runtime\\python",
              calls, [f"pkg_py_at C:\\Program Files\\ArkRelay\\runtime\\.incoming\\python\\python.exe runtime C:\\Program Files\\ArkRelay {WANT_PY} {' '.join(PINS)}",
                      "pkg_py info"])
        out, calls = bash_swap(ok_answer, same.replace("pywin32==312", "pywin32==311"))
        check("swapped but the check does not pass: failed", out[-1].startswith("FAILED 1 换完再核对不上：pywin32 311 -> 312"), True)
        out, calls = bash_swap("RUNTIME_STEP stop\nRUNTIME_FAIL verify: pywin32 311 != 312\nRUNTIME_RESTORED the previous runtime is back", same)
        check("the machine reports a failure: failed with its reason, no info", (out[-1], len(calls)), ("FAILED 1 verify: pywin32 311 != 312", 1))
        out, calls = bash_swap("", same)
        check("no answer (connection lost): failed, touched (the way back runs runtime-back)", out[-1].startswith("FAILED 1 机器上没给结果"), True)
    else:
        print('  (skipped on Windows: see the 3.0p part)')

    print("[the order in deploy-pkg.sh]")
    anchors = ['info "$APP_WIN" $(cut -f1 <<<"$APPFILES_LIST")', '\n  if ! pkg_runtime_prepare; then', 'pkg_py "$PKG_DEPLOY" stage "$APP_WIN"',
               'pkg_py "$PKG_DEPLOY" commit "$APP_WIN"', "\n  if ! pkg_appfiles_step; then", '\n  pkg_runtime_swap || FAILED_WHY=',
               '\nif [ -z "$FAILED_WHY" ]; then\n  echo "▶ 5/5', "\n  pkg_restart\n", "$WATCH_S\" deploy --pkg",
               '"$PKG_DEPLOY" runtime-back "$APP_WIN"', 'BACK=$(pkg_py "$PKG_DEPLOY" back "$APP_WIN" "$PREV"', "\n  exit 13\n",
               'pkg_py "$PKG_DEPLOY" runtime-done "$APP_WIN"', '\npkg_watchdog_step "$WD_SHA"\n']
    pos = [pkg_sh.find(a) for a in anchors]
    check("every anchor there", [a for a, p in zip(anchors, pos, strict=True) if p < 0], [])
    check("info -> prepare -> stage -> commit -> 4.5p -> 4.6p -> restart -> watch -> runtime-back before current.txt back -> runtime-done -> 5.3",
          pos == sorted(pos), True)
    gate_fail = pkg_sh[pkg_sh.find("\n  if ! pkg_runtime_prepare; then"):pkg_sh.find("RUNTIME_SWAP=1")]
    check("not ready: exit 5", "\n    exit 5\n" in gate_fail, True)
    way_back = pkg_sh[pkg_sh.find('if [ -n "$FAILED_WHY" ]; then\n  echo "❌❌'):pkg_sh.find("\n  exit 13\n")]
    check("the way back runs runtime-back only when this deploy touched the runtime, on the new runtime's python.exe",
          'if [ "$RUNTIME_TOUCHED" = 1 ]; then\n    echo "▶ 运行环境换回原来的' in way_back and 'pkg_py_at "$RUNTIME_PY_EXE" "$PKG_DEPLOY" runtime-back' in way_back, True)

    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_pkg_state_dir():
    """The packaged relay reads and writes its code version in one state folder."""
    import os

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(RELAY))
    sys.path.insert(0, str(ROOT / "scripts" / "windows"))


    TMP = tmpdir()
    DATA = TMP / "data"
    DATA.mkdir()
    os.environ["ARK_HOME"] = str(DATA)
    for k in ("ARK_STATE_DIR", "ARK_LOG_FILE"):
        os.environ.pop(k, None)

    import app_main
    import pkg_deploy
    import pkg_layout
    from ark_relay.features import selfupdate
    from ark_relay.core.config import Config
    from ark_relay.core.statestore import StateStore


    print("[app_main: ARK_STATE_DIR defaults to the folder selfupdate writes to]")
    check("app_main.DATA is ARK_HOME", app_main.DATA, DATA)
    app_main._prepare_env()
    check("ARK_STATE_DIR", os.environ.get("ARK_STATE_DIR"), str(DATA / "state"))
    check("Config().state_dir", Path(Config().state_dir), DATA / "state")

    print("[a version folder's state junction and the boot see the same versions.code]")
    code = TMP / "app" / "versions" / "20261011"
    code.mkdir(parents=True)
    (DATA / "state").mkdir(exist_ok=True)
    pkg_layout.link_state(code, pkg_layout.state_dir(DATA))   # a junction on Windows, a symlink here
    selfupdate._remember_version(code, 20261011)
    check("versions.code read at boot", StateStore(Path(Config().state_dir)).get("versions", "code"),
          "20261011")
    check("selfupdate reads it back", selfupdate._applied_version(code), 20261011)

    print("[pkg_deploy STATEDIR with no ARK_STATE_DIR in .env]")
    check("pkg_deploy._state_dir()", pkg_deploy._state_dir(), app_main.state_default(pkg_deploy.DATA))

    print("[.env naming a folder still wins]")
    os.environ.pop("ARK_STATE_DIR")
    (DATA / ".env").write_text(f"ARK_STATE_DIR={TMP / 'elsewhere'}\n", encoding="utf-8")
    app_main._prepare_env()
    check("ARK_STATE_DIR from .env", os.environ.get("ARK_STATE_DIR"), str(TMP / "elsewhere"))


    def boot_version_line() -> str:
        """What boot_stages logs as 「中继代码版本 v%s」."""
        return "v" + (StateStore(Path(Config().state_dir)).get("versions", "code") or "?")


    pkg_deploy.DATA = DATA          # C:\ProgramData\ark-relay on the machine
    for label, env_line, want in (
            ("no ARK_STATE_DIR in .env", "", DATA / "state"),
            (".env: ARK_STATE_DIR=./ark-state (the old relay's default, relative)",
             "ARK_STATE_DIR=./ark-state\n", DATA / "ark-state"),
            (".env: ARK_STATE_DIR=<absolute ark-state>",
             f"ARK_STATE_DIR={DATA / 'ark-state'}\n", DATA / "ark-state")):
        print(f"[{label}: selfupdate writes and the boot reads one folder]")
        os.environ.pop("ARK_STATE_DIR", None)
        (DATA / ".env").write_text(env_line, encoding="utf-8")
        app_main._prepare_env()
        check("ARK_STATE_DIR resolved", Path(os.environ["ARK_STATE_DIR"]), want)
        check("pkg_deploy STATEDIR agrees", pkg_deploy._state_dir(), want)
        v = code.parent / f"v-{abs(hash(label)) % 10000}"
        v.mkdir()
        pkg_layout.link_state(v, pkg_layout.state_dir(DATA))
        selfupdate._remember_version(v, 20261012)
        check("the state link points at it", Path(os.path.realpath(v / "state")), Path(os.path.realpath(want)))
        check("boot line", boot_version_line(), "v20261012")

    print("[.env changed after the link was made: the link is made again]")
    os.environ.pop("ARK_STATE_DIR", None)
    (DATA / ".env").write_text("", encoding="utf-8")
    app_main._prepare_env()
    v = code.parent / "v-relink"
    v.mkdir()
    pkg_layout.link_state(v, pkg_layout.state_dir(DATA))
    check("first: <data>/state", Path(os.path.realpath(v / "state")), Path(os.path.realpath(DATA / "state")))
    (DATA / ".env").write_text("ARK_STATE_DIR=./ark-state\n", encoding="utf-8")
    os.environ.pop("ARK_STATE_DIR", None)
    app_main._prepare_env()
    pkg_layout.link_state(v, pkg_layout.state_dir(DATA))
    check("then: <data>/ark-state", Path(os.path.realpath(v / "state")), Path(os.path.realpath(DATA / "ark-state")))
    selfupdate._remember_version(v, 20261013)
    check("boot line after the change", boot_version_line(), "v20261013")
    check("the old folder's data is still there", (DATA / "state" / "state.json").exists(), True)

    print("\n[清单-1108 A-07: a crash of the main flow goes where the watchdog reads start errors]")
    crash = TMP / "crash"
    crash.mkdir()
    app_main._record_crash("Traceback (most recent call last):\nRuntimeError: boom", data=crash)
    app_main._record_crash("Traceback (most recent call last):\nRuntimeError: again", data=crash)
    got = (crash / app_main.START_ERROR).read_text(encoding="utf-8")
    check("both crashes, newest last, with the version folder",
          (got.count("app_main.py run"), got.rstrip().endswith("RuntimeError: again"), f"({app_main.HERE.name})" in got),
          (2, True, True))
    check("the same file the watchdog reads", app_main.START_ERROR, "start-error.txt")
    (crash / app_main.START_ERROR).write_text("x" * app_main.START_ERROR_MAX, encoding="utf-8")
    app_main._record_crash("RuntimeError: last", data=crash)
    check("kept to the newest START_ERROR_MAX characters",
          len((crash / app_main.START_ERROR).read_text(encoding="utf-8")), app_main.START_ERROR_MAX)
    app_main._record_crash("RuntimeError: nowhere", data=crash / "missing" / "dir")
    check("a folder that is not there: nothing raised", (crash / "missing").exists(), False)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_pkg_switch_failed_announce():
    """A switch to the new version folder that fails says 「更新没生效」, not 「中继已更新」."""
    import logging
    import os

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))


    TMP = tmpdir()
    DATA = TMP / "data"
    DATA.mkdir()
    os.environ["ARK_HOME"] = str(DATA)
    for k in ("ARK_STATE_DIR", "ARK_LOG_FILE"):
        os.environ.pop(k, None)

    import pkg_layout
    from ark_relay.features import selfupdate


    app = TMP / "app"
    here = app / "versions" / "100"
    here.mkdir(parents=True)
    (here / "app_main.py").write_text("# v100\n", encoding="utf-8")
    (app / "current.txt").write_text("100\n", encoding="ascii")
    pkg_layout.link_state(here, pkg_layout.state_dir(DATA))
    pkg_layout.record_running_version(here)
    selfupdate._remember_announced(here, 100)     # v100 was announced when it landed


    def landed_round(root: Path) -> list[str]:
        # What selfupdate.check does on a round that lands (selfupdate.py, end of check).
        selfupdate._remember_version(root, 200)
        selfupdate._clear_failure(root)
        selfupdate._record_announcement(root, {"version": 200, "previous": 100, "files": ["x.py"]})
        return ["x.py"]


    print("switch raises after check landed")
    real_replace = os.replace


    def folder_in_use(a, b):
        if str(a).endswith(pkg_layout.STAGING):
            raise PermissionError(5, "Access is denied (folder in use)")
        return real_replace(a, b)


    os.replace = folder_in_use
    try:
        pkg_layout.update(here, landed_round)
        raised = None
    except PermissionError as exc:
        raised = exc
    finally:
        os.replace = real_replace
    check("update raised", type(raised).__name__, "PermissionError")
    check("still running folder 100", pkg_layout.current(app), "100")
    check("staging copy dropped", (app / "versions" / pkg_layout.STAGING).exists(), False)
    check("record names the folder in use", selfupdate._applied_version(here), 100)
    check("no 「中继已更新」 for code that is not running", selfupdate.pending_announcement(here), None)
    fail = selfupdate.take_failure(here) or {}
    check("「更新没生效」 recorded: remote", fail.get("remote"), 200)
    check("「更新没生效」 recorded: local", fail.get("local"), 100)
    check("「更新没生效」 recorded: files", fail.get("files"), ["x.py"])
    check("「更新没生效」 has a reason", bool(fail.get("reason")), True)

    print("power cut between check and the switch")
    # The interrupted round's note survives in the shared state; the next start runs
    # record_running_version on the old folder before anything announces.
    landed_round(here)
    pkg_layout.record_running_version(here)
    check("record back on the folder in use", selfupdate._applied_version(here), 100)
    check("note for v200 dropped at the next start", selfupdate.pending_announcement(here), None)

    print("a note for the folder in use stays (first boot after a real switch)")
    new = app / "versions" / "200"
    new.mkdir()
    (new / "app_main.py").write_text("# v200\n", encoding="utf-8")
    pkg_layout.link_state(new, pkg_layout.state_dir(DATA))
    (app / "current.txt").write_text("200\n", encoding="ascii")
    landed_round(new)
    pkg_layout.record_running_version(new)
    note = selfupdate.pending_announcement(new) or {}
    check("note for v200 announced by v200", (note.get("version"), note.get("files")), (200, ["x.py"]))

    print("restart_soon raises after current.txt was switched")
    import app_main

    LOG = logging.getLogger("ark.test_pkg")

    real = pkg_layout.update, pkg_layout.restart_soon, pkg_layout.app_root


    def no_restart(_app):
        raise OSError(2, "pythonw.exe not found")


    pkg_layout.update = lambda _here, _check: ["x.py"]
    pkg_layout.restart_soon = no_restart
    pkg_layout.app_root = lambda _here: app
    try:
        got = app_main._packaged_selfupdate(LOG)
    finally:
        pkg_layout.update, pkg_layout.restart_soon, pkg_layout.app_root = real
    check("process exits so the watchdog starts the switched folder", got, True)

    print("told to stop during the update: switched, exits, no restart behind the stop (audit 11-08 A-23)")
    from ark_relay.features import errwatch
    restarts = []
    pkg_layout.update = lambda _here, _check: ["x.py"]
    pkg_layout.restart_soon = lambda a: restarts.append(a)
    pkg_layout.app_root = lambda _here: app
    real_down = errwatch.going_down
    errwatch.going_down = lambda: True
    try:
        got = app_main._packaged_selfupdate(LOG)
    finally:
        pkg_layout.update, pkg_layout.restart_soon, pkg_layout.app_root = real
        errwatch.going_down = real_down
    check("stopping: exits, restart_soon not called", (got, restarts), (True, []))
    pkg_layout.update = lambda _here, _check: ["x.py"]
    pkg_layout.restart_soon = lambda a: restarts.append(a)
    pkg_layout.app_root = lambda _here: app
    try:
        got = app_main._packaged_selfupdate(LOG)
    finally:
        pkg_layout.update, pkg_layout.restart_soon, pkg_layout.app_root = real
    check("not stopping: restarts as before", (got, restarts), (True, [app]))

    print("an update that changes nothing still continues the boot")
    pkg_layout.update = lambda _here, _check: []
    try:
        got = app_main._packaged_selfupdate(LOG)
    finally:
        pkg_layout.update = real[0]
    check("nothing changed: boot continues", got, False)

    if fails:
        print("FAIL:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_pkg_switch_flushed():
    """The new version folder is on disk before current.txt names it."""
    import os

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))


    TMP = tmpdir()
    DATA = TMP / "data"
    DATA.mkdir()
    os.environ["ARK_HOME"] = str(DATA)
    for k in ("ARK_STATE_DIR", "ARK_LOG_FILE"):
        os.environ.pop(k, None)

    import pkg_layout
    from ark_relay.features import selfupdate


    app = TMP / "app"
    here = app / "versions" / "100"
    (here / "ark_relay" / "core").mkdir(parents=True)
    (here / "app_main.py").write_text("# v100\n", encoding="utf-8")
    (here / "ark_relay" / "core" / "x.py").write_text("X = 1\n", encoding="utf-8")
    (app / "current.txt").write_text("100\n", encoding="ascii")
    pkg_layout.link_state(here, pkg_layout.state_dir(DATA))
    pkg_layout.record_running_version(here)
    (DATA / "state" / "shared.txt").write_text("data folder, not the code\n", encoding="utf-8")


    def landed_round(root: Path) -> list[str]:
        (root / "ark_relay" / "core" / "x.py").write_text("X = 2\n", encoding="utf-8")
        (root / "ark_relay" / "core" / "new.py").write_text("N = 1\n", encoding="utf-8")
        selfupdate._remember_version(root, 200)
        return ["ark_relay/core/x.py", "ark_relay/core/new.py"]


    synced: set[int] = set()
    at_switch: set[int] = set()
    real_fsync, real_set_current = os.fsync, pkg_layout._set_current


    def recording_fsync(fd):
        synced.add(os.fstat(fd).st_ino)
        return real_fsync(fd)


    def snapshot_set_current(a, name):
        at_switch.update(synced)
        return real_set_current(a, name)


    os.fsync = recording_fsync
    pkg_layout._set_current = snapshot_set_current
    try:
        got = pkg_layout.update(here, landed_round)
    finally:
        os.fsync, pkg_layout._set_current = real_fsync, real_set_current

    new = app / "versions" / "200"
    check("switched to the new folder", (pkg_layout.current(app), len(got)), ("200", 2))
    code_files = sorted(p for p in new.rglob("*") if p.is_file() and "state" not in p.relative_to(new).parts)
    check("the new folder has its code files", [p.relative_to(new).as_posix() for p in code_files],
          ["app_main.py", "ark_relay/core/new.py", "ark_relay/core/x.py"])
    check("every code file fsynced before current.txt was written",
          [p.relative_to(new).as_posix() for p in code_files if p.stat().st_ino not in at_switch], [])
    if os.name != "nt":
        dirs = [new, new / "ark_relay", new / "ark_relay" / "core"]
        check("its folders fsynced before current.txt was written",
              [str(d.relative_to(app)) for d in dirs if d.stat().st_ino not in at_switch], [])
    check("the shared state behind the junction is not walked",
          (DATA / "state" / "shared.txt").stat().st_ino in at_switch, False)

    print("[a file that cannot be opened for the flush is skipped, the rest still flushed]")
    held = tmpdir() / "v"
    (held / "sub").mkdir(parents=True)
    (held / "a.py").write_text("a", encoding="utf-8")
    (held / "sub" / "b.py").write_text("b", encoding="utf-8")
    opened: list = []


    def picky_open(path, mode="r", *a, **k):
        if Path(path).name == "a.py":
            raise PermissionError(13, "held by a scanner")
        opened.append(Path(path).name)
        return open(path, mode, *a, **k)


    pkg_layout.open = picky_open
    try:
        pkg_layout._flush_tree(held)
        raised = False
    except OSError:
        raised = True
    finally:
        del pkg_layout.open
    check("one held file does not stop the flush (no error)", raised, False)
    check("the other file is still flushed", opened, ["b.py"])

    if fails:
        print("FAIL:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_pkg_update_nothing_changed():
    """A deploy with nothing to change leaves the recorded code version on the folder in use."""
    import os

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))


    TMP = tmpdir()
    DATA = TMP / "data"
    DATA.mkdir()
    os.environ["ARK_HOME"] = str(DATA)
    for k in ("ARK_STATE_DIR", "ARK_LOG_FILE"):
        os.environ.pop(k, None)

    import pkg_layout
    from ark_relay.features import selfupdate


    app = TMP / "app"
    here = app / "versions" / "5"
    here.mkdir(parents=True)
    (here / "app_main.py").write_text("# v5\n", encoding="utf-8")
    (app / "current.txt").write_text("5\n", encoding="ascii")
    pkg_layout.link_state(here, pkg_layout.state_dir(DATA))
    pkg_layout.record_running_version(here)
    check("record starts on the running folder", selfupdate._applied_version(here), 5)


    def check_nothing_to_change(root: Path) -> list[str]:
        # What selfupdate.check does for a newer manifest whose files all match:
        # nothing staged, the manifest's version recorded, [] returned.
        selfupdate._remember_version(root, 7)
        return []


    got = pkg_layout.update(here, check_nothing_to_change)
    check("update returns nothing", got, [])
    check("still running folder 5", pkg_layout.current(app), "5")
    check("staging copy dropped", (app / "versions" / pkg_layout.STAGING).exists(), False)
    check("record names the folder in use, not v7", selfupdate._applied_version(here), 5)

    if fails:
        print("FAIL:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_pkg_watchdog_update():
    """A relay deploy updates the watchdog service's file when it changed (no setup.exe)."""
    import hashlib
    import os
    import subprocess
    import tempfile
    import time
    import types

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(RELAY))

    import watchdog_guard as G

    spec = importlib.util.spec_from_file_location("pkg_deploy", ROOT / "scripts/windows/pkg_deploy.py")
    pd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pd)


    def sha(text: str) -> str:
        return hashlib.sha1(text.encode()).hexdigest()


    class FakeService:
        """Records each call; `fail` names the step that returns a reason."""

        def __init__(self, app: Path, kind="AUTO", fail="", running=True):
            self.dst = app / "watchdog" / "ark_watchdog.py"
            self.kind, self.fail, self.is_running = kind, fail, running
            self.calls = []

        def start_type(self):
            self.calls.append("start_type")
            return self.kind

        def install(self, script):
            # What the file holds when install runs proves the copy came first.
            self.calls.append(("install", Path(script).read_text(encoding="utf-8")))
            return "exit 1" if self.fail == "install" else ""

        def stop(self):
            self.calls.append("stop")
            return "stuck" if self.fail == "stop" else ""

        def start(self):
            self.calls.append(("start", self.dst.read_text(encoding="utf-8")))
            if self.fail == "start":
                self.fail = ""          # the second start (on the previous file) works
                return "stopped again during its start"
            return ""

        def running(self):
            self.calls.append("running")
            return self.is_running


    def setup(td: str, installed="OLD", sent="NEW"):
        app = Path(td) / "ArkRelay"
        (app / "watchdog").mkdir(parents=True)
        (app / "watchdog" / "ark_watchdog.py").write_text(installed, encoding="utf-8")
        staged = Path(td) / "ark-watchdog-new.py"
        staged.write_text(sent, encoding="utf-8")
        return app, staged


    def run(app, want, staged, svc):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = pd.update_watchdog(app, want, staged, svc)
        return rc, buf.getvalue().splitlines()


    print("[update_watchdog: the same file = nothing at all]")
    with tempfile.TemporaryDirectory() as td:
        app, staged = setup(td, "SAME", "SAME")
        svc = FakeService(app)
        rc, out = run(app, sha("SAME"), staged, svc)
        check("exit 0", rc, 0)
        check("no service call", svc.calls, [])
        check("says unchanged", out, ["WATCHDOG=unchanged"])

    print("[update_watchdog: changed = copy, install, restart (stop, start), verify]")
    with tempfile.TemporaryDirectory() as td:
        app, staged = setup(td)
        svc = FakeService(app)
        rc, out = run(app, sha("NEW"), staged, svc)
        check("exit 0", rc, 0)
        check("calls in order, install and start already on the new file", svc.calls,
              ["start_type", ("install", "NEW"), "stop", ("start", "NEW"), "running"])
        check("steps printed in order", [x for x in out if x.startswith("WATCHDOG")],
              ["WATCHDOG_STEP copy", "WATCHDOG_STEP install", "WATCHDOG_STEP stop",
               "WATCHDOG_STEP start", "WATCHDOG_STEP verify", "WATCHDOG=updated"])
        check("installed file is the new one", (app / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), "NEW")
        check("no .new left behind", (app / "watchdog" / "ark_watchdog.py.new").exists(), False)

    print("[update_watchdog: nothing changed when it must not]")
    with tempfile.TemporaryDirectory() as td:
        app, staged = setup(td)
        svc = FakeService(app, kind="DISABLED")
        rc, out = run(app, sha("NEW"), staged, svc)
        check("disabled (a revert): exit 0, said so", (rc, out), (0, ["WATCHDOG=disabled"]))
        check("disabled: not installed (that would switch it back to automatic), not started",
              svc.calls, ["start_type"])
        check("disabled: file untouched", (app / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), "OLD")
    with tempfile.TemporaryDirectory() as td:
        app, staged = setup(td)
        svc = FakeService(app, kind="MISSING")
        rc, out = run(app, sha("NEW"), staged, svc)
        check("not installed: exit 1, loud", (rc, out[-1].startswith("WATCHDOG_FAIL")), (1, True))
        check("not installed: file untouched", (app / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), "OLD")
    with tempfile.TemporaryDirectory() as td:
        app, staged = setup(td, sent="NEW, cut sho")
        svc = FakeService(app)
        rc, out = run(app, sha("NEW, cut short"), staged, svc)
        check("file sent does not match its sha1: exit 1, no service call", (rc, svc.calls), (1, []))
        check("bad transfer: file untouched", (app / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), "OLD")

    print("[update_watchdog: a failed step puts the previous file back and starts it]")
    for step, want_calls in (
            ("install", ["start_type", ("install", "NEW"), "stop", ("start", "OLD")]),
            ("stop", ["start_type", ("install", "NEW"), "stop", "stop", ("start", "OLD")]),
            ("start", ["start_type", ("install", "NEW"), "stop", ("start", "NEW"), "stop", ("start", "OLD")])):
        with tempfile.TemporaryDirectory() as td:
            app, staged = setup(td)
            svc = FakeService(app, fail=step)
            rc, out = run(app, sha("NEW"), staged, svc)
            check(f"{step} fails: exit 1", rc, 1)
            check(f"{step} fails: says which step", any(x.startswith(f"WATCHDOG_FAIL {step}:") for x in out), True)
            check(f"{step} fails: calls", svc.calls, want_calls)
            check(f"{step} fails: previous file back", (app / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8"), "OLD")
            check(f"{step} fails: says it runs on the previous file", out[-1], "WATCHDOG_RESTORED running on the previous file")
            check(f"{step} fails: never says updated", "WATCHDOG=updated" in out, False)
    with tempfile.TemporaryDirectory() as td:
        app, staged = setup(td)
        svc = FakeService(app, running=False)
        rc, out = run(app, sha("NEW"), staged, svc)
        check("not RUNNING at the verify: exit 1, verify named", (rc, any(x.startswith("WATCHDOG_FAIL verify:") for x in out)), (1, True))

    print("[WinService.stop / start: the stop marker, and the relay's guard meanwhile]")


    class PyWinError(Exception):
        def __init__(self, winerror, strerror=""):
            super().__init__(winerror, strerror)
            self.winerror, self.strerror = winerror, strerror


    RUNNING, STOPPED = 4, 1
    service = {"state": RUNNING}
    events = []


    def _status(name):
        return (0x10, service["state"], 0, 0, 0, 0, 0)


    def _stop(name):
        events.append(("StopService", pd.WATCHDOG_MARKER.exists()))
        service["state"] = STOPPED


    def _start(name):
        events.append(("StartService", pd.WATCHDOG_MARKER.exists()))
        service["state"] = RUNNING


    fake = {
        "pywintypes": types.SimpleNamespace(error=PyWinError),
        "win32service": types.SimpleNamespace(SERVICE_RUNNING=RUNNING, SERVICE_STOPPED=STOPPED),
        "win32serviceutil": types.SimpleNamespace(QueryServiceStatus=_status, StopService=_stop,
                                                  StartService=_start),
    }
    saved = {k: sys.modules.get(k) for k in fake}
    real_sleep, real_marker = pd.time.sleep, pd.WATCHDOG_MARKER
    clock = [1000.0]
    real_mono = pd.time.monotonic
    with tempfile.TemporaryDirectory() as td:
        try:
            sys.modules.update(fake)
            pd.WATCHDOG_MARKER = Path(td) / "watchdog-stopped.txt"

            def fake_sleep(s):
                clock[0] += s

            pd.time.sleep = fake_sleep
            pd.time.monotonic = lambda: clock[0]
            ws = pd.WinService(Path(td))
            check("stop returns ''", ws.stop(), "")
            check("marker written before StopService", events, [("StopService", True)])
            # The relay's guard looking now: stopped, automatic, marker from this boot.
            guard = G.Guard(lambda: ("STOPPED", "AUTO"), lambda: events.append("GUARD_START") or "",
                            lambda: G.marker_this_boot(pd.WATCHDOG_MARKER, time.time() - 3600))
            check("the guard reads it as stopped on purpose", guard.tick(), "stopped on purpose")
            check("the guard did not start it", "GUARD_START" in events, False)
            check("start returns '' once RUNNING steady", ws.start(), "")
            check("marker deleted before StartService", events[-1], ("StartService", False))
            check("no marker left (the guard covers any later stop)", pd.WATCHDOG_MARKER.exists(), False)
            check("verify", ws.running(), True)
        finally:
            pd.time.sleep, pd.time.monotonic = real_sleep, real_mono
            pd.WATCHDOG_MARKER = real_marker
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    print("[deploy-pkg.sh step 5.3, run in bash with scp and pkg_py stood in]")
    # deploy-pkg.sh runs on the Mac only. Its block run in bash on the Windows CI job
    # recorded no call at all (run 38360295330: IndexError on calls[0]) and would say
    # nothing about the Mac anyway: this part runs on the Mac (the deploy gate), the
    # Windows job runs the rest of this file (pkg_deploy.py, which runs on the machine).
    ON_MAC_LIKE = sys.platform != "win32"
    pkg_sh = (ROOT / "scripts/mac/lib/deploy-pkg.sh").read_text(encoding="utf-8")
    block = pkg_sh[pkg_sh.index("# >>> watchdog step"):pkg_sh.index("# <<< watchdog step")]
    sha_fn = next(x for x in pkg_sh.splitlines() if x.startswith("pkg_sha1() "))
    src = ROOT / "packaging/watchdog/ark_watchdog.py"
    src_sha = hashlib.sha1(src.read_bytes()).hexdigest()


    def bash_step(installed_sha: str, machine_out: str, scp_rc: int = 0):
        with tempfile.TemporaryDirectory() as td:
            calls = Path(td) / "calls"
            script = f"""
set -euo pipefail
HERE={str(RELAY)!r}
SSH_OPTS=(-o ConnectTimeout=15)
USER_AT=Administrator@host
APP_WIN='C:\\Program Files\\ArkRelay'
PKG_DEPLOY='C:\\Users\\Administrator\\ark-pkg-deploy.py'
WD_SRC="$HERE/../packaging/watchdog/ark_watchdog.py"
WD_STAGED='C:\\Users\\Administrator\\ark-watchdog-new.py'
{sha_fn}
scp() {{ echo "scp $*" >>{str(calls)!r}; return {scp_rc}; }}
pkg_py() {{ echo "pkg_py $*" >>{str(calls)!r}; printf '%s\\n' "$MACHINE_OUT"; }}
{block}
pkg_watchdog_step "$1"
echo "FAIL_WHY=$WATCHDOG_FAIL_WHY"
"""
            r = subprocess.run(["bash", "-c", script, "step", installed_sha], capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               env={**os.environ, "MACHINE_OUT": machine_out, "LC_ALL": "en_US.UTF-8"})
            if r.stderr.strip():
                print("    bash stderr:", r.stderr.strip()[-300:])
            got = calls.read_text().splitlines() if calls.exists() else []
            return r.returncode, r.stdout.splitlines(), got


    if ON_MAC_LIKE:
        rc, out, calls = bash_step(src_sha, "WATCHDOG=updated")
        check("unchanged: bash exit 0", rc, 0)
        check("unchanged: no scp, no machine command", calls, [])
        check("unchanged: one line, then no failure", (len(out), out[-1]), (2, "FAIL_WHY="))
        rc, out, calls = bash_step("0" * 40, "WATCHDOG_STEP copy\nWATCHDOG_STEP install\nWATCHDOG_STEP stop\n"
                                             "WATCHDOG_STEP start\nWATCHDOG_STEP verify\nWATCHDOG=updated")
        check("changed: scp the file, then pkg_deploy.py watchdog with its sha1 and the staged path",
              [c.split()[0] for c in calls], ["scp", "pkg_py"])
        check("changed: the scp sends packaging/watchdog/ark_watchdog.py",
              "packaging/watchdog/ark_watchdog.py Administrator@host:C:/Users/Administrator/ark-watchdog-new.py" in calls[0], True)
        check("changed: machine command", calls[1],
              f"pkg_py C:\\Users\\Administrator\\ark-pkg-deploy.py watchdog C:\\Program Files\\ArkRelay {src_sha} "
              "C:\\Users\\Administrator\\ark-watchdog-new.py")
        check("changed: no failure", out[-1], "FAIL_WHY=")
        check("changed: steps shown", sum(x.strip().startswith("WATCHDOG_STEP") for x in out), 5)
        rc, out, calls = bash_step("0" * 40, "WATCHDOG_STEP copy\nWATCHDOG_FAIL start: stopped again during its start\n"
                                             "WATCHDOG_RESTORED running on the previous file")
        check("machine failure: bash still exit 0 (the relay is live; deploy-relay.sh reports it)", rc, 0)
        check("machine failure: WATCHDOG_FAIL_WHY names it and the restore",
              ("stopped again during its start" in out[-1], "running on the previous file" in out[-1]), (True, True))
        rc, out, calls = bash_step("0" * 40, "")
        check("no answer from the machine: a failure too", out[-1].startswith("FAIL_WHY=") and len(out[-1]) > len("FAIL_WHY="), True)
        rc, out, calls = bash_step("0" * 40, "WATCHDOG=updated", scp_rc=1)
        check("scp failed: no machine command, a failure", ([c.split()[0] for c in calls], len(out[-1]) > len("FAIL_WHY=")),
              (["scp"], True))
        rc, out, calls = bash_step("", "WATCHDOG=updated")
        check("no WATCHDOG_SHA from info (old machine script): treated as changed", [c.split()[0] for c in calls],
              ["scp", "pkg_py"])
    else:
        print('  (skipped on Windows: see above)')

    print("[where the step sits]")
    p = {k: pkg_sh.find(k) for k in ("WD_SHA=$(sed -n 's/^WATCHDOG_SHA=//p' <<<\"$INFO\")", "grep -q '^WATCH_OK' \"$WATCH_OUT\"",
                                     "\n  exit 13\nfi", "\npkg_watchdog_step \"$WD_SHA\"\n", "\nCHANGED=\"\"\n")}
    check("deploy-pkg.sh: every anchor there", [k for k, v in p.items() if v < 0], [])
    order = list(p.values())
    check("deploy-pkg.sh: sha read from info, after the watch and the rollback exits, before the hand-over",
          order == sorted(order), True)
    check("deploy-pkg.sh: the staged file is deleted on exit", "del $WD_STAGED" in pkg_sh, True)
    sh = (ROOT / "scripts/mac/deploy-relay.sh").read_text(encoding="utf-8")
    q = {k: sh.find(k) for k in ('\nWATCHDOG_FAIL_WHY=""\n', 'lib/deploy-pkg.sh"', "grep -q '^SMOKE_OK$'", 'publish-cos.py"',
                                 'if [ -n "$WATCHDOG_FAIL_WHY" ]; then\n  echo "❌❌ 中继已上线', 'echo "✅ 部署完成',
                                 "push -q origin HEAD:refs/heads/main", "lib/ff-toplevel.sh",
                                 'if [ -n "$WATCHDOG_FAIL_WHY" ]; then\n  echo "❌❌ 再说一遍', "\n  exit 14\nfi")}
    check("deploy-relay.sh: every anchor there", [k for k, v in q.items() if v < 0], [])
    order = list(q.values())
    check("deploy-relay.sh: set for both layouts first; reported after the smoke and COS; exit 14 last",
          order == sorted(order), True)
    check("deploy-relay.sh: exit 14 is the last command", sh.rstrip().endswith("exit 14\nfi"), True)

    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("all checks passed")


def _part_stop_denied():
    """app_main.stop(): a stop event this account may not set ends the task at once."""

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    import app_main


    class Relay:
        """A fake relay: `answers` is what each ask() gets; it exits `exit_after` s after a
    stop that reached it (asked or the task ended)."""

        def __init__(self, answers, exit_after=3.0):
            self.t = 0.0
            self.answers = list(answers)
            self.exit_after = exit_after
            self.stop_at = None
            self.asks = 0
            self.ended_at = None

        def clock(self):
            return self.t

        def sleep(self, s):
            self.t += s

        def running(self):
            return self.stop_at is None or self.t < self.stop_at + self.exit_after

        def ask(self):
            self.asks += 1
            got = self.answers.pop(0) if self.answers else self.answers_last
            self.answers_last = got
            if got == "asked":
                self.stop_at = self.t
            return got

        def end_task(self):
            self.ended_at = self.t
            self.stop_at = self.t


    def stop(r):
        return app_main._stop(r.running, r.ask, r.end_task, sleep=r.sleep, clock=r.clock)


    print("[access denied: the task is ended at once, no 40 s wait]")
    r = Relay(["denied"], exit_after=1.0)
    check("result", stop(r), 0)
    check("task ended at the first ask", r.ended_at, 0.0)
    check("done in seconds", r.t <= 3.0, True)
    check("asked once", r.asks, 1)

    print("[event not made yet (relay starting): asked again, no task end]")
    r = Relay(["not yet", "not yet", "asked"])
    check("result", stop(r), 0)
    check("no task end", r.ended_at, None)
    check("asks", r.asks, 3)

    print("[normal stop]")
    r = Relay(["asked"])
    check("result", stop(r), 0)
    check("no task end", r.ended_at, None)

    print("[access denied and the task end does not take: 1 after STOP_WAIT_S, one end only]")
    r = Relay(["denied"], exit_after=10_000)
    ends = []
    r.end_task = lambda: ends.append(r.t)
    check("result", stop(r), 1)
    check("task ended once", len(ends), 1)
    check("gave up at STOP_WAIT_S", app_main.STOP_WAIT_S <= r.t <= app_main.STOP_WAIT_S + 1, True)

    print("[not running at all]")
    r = Relay([], exit_after=0)
    r.stop_at = -1.0
    check("result", stop(r), 0)
    check("never asked", r.asks, 0)

    print("[the hard end is written to the relay's log first (review round 9 #25)]")
    order = []
    r = Relay(["denied"], exit_after=1.0)
    real_end = r.end_task
    r.end_task = lambda: (order.append("end"), real_end())
    app_main._stop(r.running, r.ask, r.end_task, sleep=r.sleep, clock=r.clock,
                   note=lambda msg: order.append(("note", msg)))
    check("note before the end", [o if o == "end" else o[0] for o in order], ["note", "end"])
    check("note names the task and the account", app_main.MAIN_TASK in order[0][1] and "账号" in order[0][1],
          True)

    import os
    log = tmpdir() / "relay.log"
    log.write_text("10-11 08:00:00 INFO    ark.app  earlier line\n", encoding="utf-8")
    os.environ["ARK_LOG_FILE"] = str(log)
    app_main._log_line("停止请求被拒：测试")
    lines = log.read_text(encoding="utf-8").splitlines()
    check("earlier line kept", lines[0].endswith("earlier line"), True)
    check("one line added", len(lines), 2)
    check("relay's format, WARNING", " WARNING ark.app.stop  停止请求被拒：测试" in lines[1], True)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_stop_event_manual_reset():
    """停服务的事件必须是手动复位的（CreateEvent 第二个参数为 1）。"""

    SRC = Path(__file__).resolve().parents[1] / "service.py"
    text = SRC.read_text(encoding="utf-8")
    # 只盯 stop_event；proc_evt（进程退出）只有主循环一个消费者，自动复位是对的。
    hits = re.findall(r"self\.stop_event\s*=\s*win32event\.CreateEvent\(None,\s*(\d)\s*,", text)
    print("  stop_event 的 CreateEvent 第二个参数：", hits)
    ok = hits == ["1"]

    run = text[text.index("def SvcDoRun"):text.index("\n    def ", text.index("def SvcDoRun") + 10)]
    tail_ok = ("ReportServiceStatus(win32service.SERVICE_STOPPED)" in run
               and run.rstrip().endswith("os._exit(0)"))
    print("  SvcDoRun 以 ReportServiceStatus(STOPPED) + os._exit 收尾：", tail_ok)
    ok = ok and tail_ok
    print("all checks passed" if ok else "FAILED: stop_event 不是手动复位（CreateEvent 第二个参数要是 1）")
    sys.exit(0 if ok else 1)


def _part_stop_push_errwatch_budget():
    """stop-push's errwatch: the relay's power-off probe, and the whole run inside the watchdog's time.
    """
    import logging
    import os
    import subprocess
    import threading
    import time
    from datetime import datetime, timedelta

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))

    DATA = tmpdir()
    (DATA / "state").mkdir()
    os.environ.update(ARK_HOME=str(DATA), ARK_PHONE_TOPIC="arktest-topic", ARK_PHONE_PIN="1234",
                      SERVERCHAN_KEY="", WECOM_CORPID="", WECOM_SECRET="", WECOM_BOT_URL="")
    for _k in ("ARK_LOG_FILE", "ARK_STATE_DIR", "ARK_AUTOMAS_DIR"):
        os.environ.pop(_k, None)

    import app_main
    from ark_relay.core.config import SERVER_TZ, Config
    from ark_relay.core.ledger import State
    from ark_relay.features import errwatch
    from ark_relay.features import phone
    from ark_relay.features import shutdown

    STOP_PUSH_LOG = "ark.app.stop_push"   # app_main's logger for the watchdog's stop push


    class Eng:
        def __init__(self, state_dir):
            self.state = State(state_dir)


    STATE = app_main._relay_env()      # what stop_push and its Config() use
    record = getattr(shutdown, "_record_poweroff", lambda eng, at: None)
    recorded = getattr(shutdown, "relay_poweroff_recorded", lambda sd, now=None: False)
    now = datetime.now(tz=SERVER_TZ)

    print("[1. the relay's own power-off, seen from stop-push's process]")
    eng = Eng(STATE)
    record(eng, now - timedelta(minutes=1))
    check("recorded a minute ago: the relay's own power-off", recorded(STATE, now), True)
    check(f"recorded {shutdown.ISSUED_STUCK_MIN} min ago: stale, not ours any more",
          recorded(STATE, now + timedelta(minutes=shutdown.ISSUED_STUCK_MIN)), False)
    app_main._stop_push_errwatch(Config())
    check("stop-push's errwatch asks it: relay_shutdown_issued() is true", errwatch.relay_shutdown_issued(), True)
    record(eng, None)
    check("countdown cancelled: not the relay's power-off", errwatch.relay_shutdown_issued(), False)
    check("nothing recorded at all: not ours", recorded(DATA / "elsewhere", now), False)

    print("[2. the whole stop-push path inside the watchdog's time]")
    src = (RELAY.parent / "packaging" / "watchdog" / "ark_watchdog.py").read_text(encoding="utf-8")
    PUSH_TIMEOUT_S = int(re.search(r"^PUSH_TIMEOUT_S\s*=\s*(\d+)", src, re.M).group(1))
    release = threading.Event()


    class Hang:
        """The group never answers: errwatch's push is in flight for the whole drain."""
        _state_dir = STATE

        def send(self, *a, **k):
            release.wait(120)
            return []

        def __getattr__(self, name):
            return lambda *a, **k: []


    h = errwatch._handler[0]
    h._notifier = Hang()
    logging.getLogger(STOP_PUSH_LOG).warning("a WARNING the group does not acknowledge")
    phone.state_cos = lambda cfg: object()
    phone.send_state = lambda box, cfg, why, log: release.wait(120) or (False, "")   # the send hangs
    WAIT = 0.5
    t0 = time.monotonic()
    code = app_main.stop_push(wait_s=WAIT)
    took = time.monotonic() - t0
    around = took - WAIT
    check("the send ran out its time: exit code 1", code, 1)
    check(f"the drain is in it ({around:.2f} s around the send, drain default 3 s)", around >= 2.5, True)
    t1 = time.monotonic()
    # A fresh interpreter importing what stop_push imports (this process has them loaded already).
    subprocess.run([sys.executable, "-c", "import app_main, ark_relay.__main__, ark_relay.core.notify, "
                    "ark_relay.core.statestore, ark_relay.features.errwatch, ark_relay.features.phone, "
                    "ark_relay.features.shutdown"], cwd=RELAY, check=True, capture_output=True)
    start = time.monotonic() - t1
    total = app_main.STOP_PUSH_WAIT_S + around + start
    check(f"{app_main.STOP_PUSH_WAIT_S} s send + {around:.2f} s drain and the rest + {start:.2f} s start"
          f" = {total:.1f} s < the watchdog's {PUSH_TIMEOUT_S} s", total < PUSH_TIMEOUT_S, True)
    release.set()

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_switch_resume():
    """An upgrade that is cancelled after it stopped the relay starts the previous version again.
    """
    import tempfile

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(ROOT / "packaging"))

    import switch


    def resume_in(app: Path, current: str, *, watchdog_rc=0):
        """switch.resume(current) with APP = app and nothing run; the steps taken and its code."""
        steps = []
        saved = switch.APP, switch.run, switch.start_watchdog
        switch.APP = app
        switch.run = lambda *cmd: steps.append(" ".join(map(str, cmd))) or 0
        switch.start_watchdog = lambda: steps.append("start_watchdog") or watchdog_rc
        try:
            rc = switch.resume(current)
        finally:
            switch.APP, switch.run, switch.start_watchdog = saved
        return steps, rc


    def make_app(root: Path, current: "str | None", folders: list[str]) -> Path:
        app = root / "ArkRelay"
        for name in folders:
            (app / "versions" / name).mkdir(parents=True)
            (app / "versions" / name / "app_main.py").write_text("", encoding="ascii")
        app.mkdir(exist_ok=True)
        if current is not None:
            (app / "current.txt").write_text(current + "\r\n", encoding="ascii")
        return app


    def current_of(app: Path) -> str:
        p = app / "current.txt"
        return p.read_text(encoding="ascii").strip() if p.exists() else "(none)"


    TASK_RUN = f"schtasks.exe /run /tn {switch.TASK_PATH}{switch.TASK_NAME}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        print("[cancelled before current.txt was copied: start what is there]")
        app = make_app(tmp / "a", "1300", ["1300"])
        steps, rc = resume_in(app, "1300")
        check("current.txt unchanged", current_of(app), "1300")
        check("watchdog started, then the task run", steps, ["start_watchdog", TASK_RUN])
        check("exit 0", rc, 0)

        print("[cancelled after current.txt was copied, new folder rolled back]")
        app = make_app(tmp / "b", "1310", ["1300"])
        steps, rc = resume_in(app, "1300")
        check("current.txt back on the version that ran", current_of(app), "1300")
        check("no temp file left", (app / "current.txt.tmp").exists(), False)
        check("then watchdog and task", steps, ["start_watchdog", TASK_RUN])

        print("[cancelled after current.txt was copied, new folder still there]")
        app = make_app(tmp / "c", "1310", ["1300", "1310"])
        resume_in(app, "1300")
        check("current.txt back on the version that ran", current_of(app), "1300")

        print("[the previous folder is not complete: current.txt left alone]")
        app = make_app(tmp / "d", "1310", ["1310"])
        (app / "versions" / "1300").mkdir()
        steps, rc = resume_in(app, "1300")
        check("current.txt unchanged", current_of(app), "1310")
        check("still started", steps, ["start_watchdog", TASK_RUN])

        print("[no name from the installer (no current.txt before): left alone]")
        app = make_app(tmp / "e", "1310", ["1310"])
        resume_in(app, "")
        check("current.txt unchanged", current_of(app), "1310")

        print("[watchdog did not come up: the task still runs, exit says so]")
        app = make_app(tmp / "f", "1300", ["1300"])
        steps, rc = resume_in(app, "1300", watchdog_rc=1)
        check("task run anyway", steps, ["start_watchdog", TASK_RUN])
        check("exit 1", rc, 1)

    print("[uninstall's way back is the same start()]")
    src = (ROOT / "packaging" / "switch.py").read_text(encoding="utf-8")
    body = src.split("def uninstall()", 1)[1].split("\ndef ", 1)[0]
    check("uninstall calls start() when AUTO-MAS is not put back", "start()" in body, True)
    check("switch.py dispatches resume with --current=",
          'args[:1] == ["resume"]' in src and '"--current="' in src, True)

    print("[the installer: DeinitializeSetup resumes only between stop and the switch-over]")
    iss = (ROOT / "packaging" / "ark-relay.iss").read_text(encoding="utf-8-sig")
    code = iss.split("[Code]", 1)[1]


    prep, step, deinit = _iss_proc(code, "PrepareToInstall"), _iss_proc(code, "CurStepChanged"), _iss_proc(code, "DeinitializeSetup")
    check("PrepareToInstall sets the flag before switch.py stop",
          0 <= prep.find("StoppedForUpgrade := True") < prep.find("stop',"), True)
    check("ssPostInstall clears it before switch.py install",
          0 <= step.find("StoppedForUpgrade := False") < step.find("RunSwitch(Args)"), True)
    check("DeinitializeSetup exists and is guarded by the flag",
          "if not StoppedForUpgrade then" in deinit, True)
    check("DeinitializeSetup runs switch.py resume with the old current.txt",
          "RunSwitch('resume \"--current=' + OldCurrent + '\"')" in deinit, True)
    files = iss.split("[Files]", 1)[1].split("\n[", 1)[0]
    sources = re.findall(r'^Source: "([^"]+)"', files, re.M)
    check("switch.py and legacy.py are copied before everything else",
          sources[:2], ["legacy.py", "switch.py"])

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_switch_run_encoding():
    """switch.run decodes Windows tools' output in the console code page, not UTF-8."""

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY.parent / "packaging"))

    import switch


    class Done:
        returncode, stdout, stderr = 0, "", ""


    seen = {}


    def fake_run(cmd, **kw):
        seen.update(kw)
        return Done()


    had_flag = hasattr(switch.subprocess, "CREATE_NO_WINDOW")
    saved = switch.subprocess.run
    switch.subprocess.run = fake_run
    if not had_flag:
        switch.subprocess.CREATE_NO_WINDOW = 0
    try:
        switch.run("sc.exe", "config", "ArkRelayWatchdog", "start=", "auto")
    finally:
        switch.subprocess.run = saved
        if not had_flag:
            del switch.subprocess.CREATE_NO_WINDOW

    print("[switch.run]")
    check("decodes in the console code page", seen.get("encoding"), "oem")
    check("never raises on a byte it cannot map", seen.get("errors"), "replace")
    sc_ok = "[SC] ChangeServiceConfig 成功".encode("cp936")
    check("the machine's bytes read back under cp936 (what oem is there)",
          sc_ok.decode("cp936"), "[SC] ChangeServiceConfig 成功")
    check("and were mojibake under UTF-8", "成功" in sc_ok.decode("utf-8", "replace"), False)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_switch_stop():
    """switch.py stop() - before an upgrade, at uninstall and at revert - ends the update's
restart helper before it stops the relay.
    """
    import fnmatch
    import subprocess

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(RELAY))
    sys.path.insert(0, str(ROOT / "packaging"))

    import pkg_layout
    import switch


    def like(text: str, pattern: str) -> bool:
        """PowerShell -like: wildcards * ? [], case-insensitive."""
        return fnmatch.fnmatchcase(text.lower(), pattern.lower())


    print("[stop(): watchdog, then the helper, then the relay]")
    steps = []
    real_run, real_wd = switch.run, switch.stop_watchdog
    switch.run = lambda *cmd: steps.append(("run", tuple(map(str, cmd)))) or 0
    switch.stop_watchdog = lambda: steps.append(("watchdog",))
    try:
        switch.stop()
    finally:
        switch.run, switch.stop_watchdog = real_run, real_wd


    def kind(step):
        if step[0] == "watchdog":
            return "watchdog"
        cmd = step[1]
        if cmd[0] == "powershell.exe" and switch.HELPER_LIKE in cmd[-1]:
            return "helper"
        if cmd[-2:] == (str(switch.APP / "launch.py"), "stop"):
            return "relay"
        return "other: " + " ".join(cmd)


    check("order", [kind(s) for s in steps], ["watchdog", "helper", "relay"])
    ps = next((s[1][-1] for s in steps if kind(s) == "helper"), "")
    check("looks only at pythonw.exe (restart_soon starts the helper with it)",
          "Name='pythonw.exe'" in ps, True)
    check("ends what it finds", "Stop-Process" in ps, True)

    print("[the match: the helper restart_soon starts, and nothing else]")
    calls = []
    pkg_layout.restart_soon(Path("C:/Program Files/ArkRelay"), popen=lambda cmd, creationflags=0: calls.append(cmd))
    helper_line = subprocess.list2cmdline(calls[0])
    check("restart_soon's helper matches", like(helper_line, switch.HELPER_LIKE), True)
    check("same match as estop.sh",
          f"-like '{switch.HELPER_LIKE}'" in (ROOT / "scripts" / "mac" / "estop.sh").read_text(encoding="utf-8"),
          True)
    relay_line = subprocess.list2cmdline([r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe",
                                          r"C:\Program Files\ArkRelay\launch.py"])
    check("the relay itself (task \\ArkRelay\\main) does not match", like(relay_line, switch.HELPER_LIKE), False)
    stop_line = subprocess.list2cmdline([str(switch.PY), str(switch.APP / "launch.py"), "stop"])
    check("launch.py stop does not match", like(stop_line, switch.HELPER_LIKE), False)

    print("[uninstall(): the task, then its \\ArkRelay\\ folder in Task Scheduler]")


    class FakeScheduler:
        """Schedule.Service as delete_task_folder uses it; `fail` makes DeleteFolder raise."""

        def __init__(self, fail=False):
            self.fail, self.calls = fail, []

        def GetFolder(self, path):  # noqa: N802
            self.calls.append(("GetFolder", path))
            return self

        def DeleteFolder(self, name, flags):  # noqa: N802
            self.calls.append(("DeleteFolder", name, flags))
            if self.fail:
                raise OSError("the folder still holds a task")


    steps = []
    saved = (switch.stop, switch._handover_rollback, switch.run, switch._mark_watchdog_stopped,
             switch.legacy.remove, switch.delete_task_folder)
    sched = FakeScheduler()
    real_delete = switch.delete_task_folder
    switch.stop = lambda: steps.append("stop")
    switch._handover_rollback = lambda: 0
    switch.run = lambda *cmd: steps.append(" ".join(map(str, cmd[:2]))) or 0
    switch._mark_watchdog_stopped = lambda on: None
    switch.legacy.remove = lambda: steps.append("legacy")
    switch.delete_task_folder = lambda: steps.append("folder") or real_delete(connect=lambda: sched)
    try:
        rc = switch.uninstall()
    finally:
        (switch.stop, switch._handover_rollback, switch.run, switch._mark_watchdog_stopped,
         switch.legacy.remove, switch.delete_task_folder) = saved
    check("uninstall exit", rc, 0)
    check("folder deleted after the task", steps.index("folder") > steps.index("schtasks.exe /delete"), True)
    check("the root folder deletes ArkRelay with flags 0", sched.calls, [("GetFolder", "\\"), ("DeleteFolder", "ArkRelay", 0)])
    check("a folder that cannot go does not fail the uninstall",
          switch.delete_task_folder(connect=lambda: FakeScheduler(fail=True)), False)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_switch_uninstall():
    """An uninstall that fails part way still does every other step and says what is left."""
    import tempfile

    RELAY = Path(__file__).resolve().parents[1]
    ROOT = RELAY.parent
    sys.path.insert(0, str(ROOT / "packaging"))

    import legacy
    import switch


    def quiet(fn, *args):
        """fn's result with its prints swallowed; an exception becomes its name (a failed
    check, not a crash)."""
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return fn(*args)
        except Exception as exc:  # noqa: BLE001
            return f"raised {type(exc).__name__}"


    NAMES = ("APP", "stop", "start", "_handover_rollback", "run", "delete_task_folder",
             "_mark_watchdog_stopped")


    def uninstall_in(tmp: Path, *, rollback_rc=0, raise_in=""):
        """switch.uninstall() with every Windows call faked; the steps taken, its code and
    the uninstall-left.txt text ('' = none)."""
        steps = []
        app = tmp / "ArkRelay"
        (app / "versions" / "1300").mkdir(parents=True, exist_ok=True)
        left_file = tmp / "uninstall-left.txt"

        def maybe_raise(name):
            steps.append(name)
            if name == raise_in:
                raise OSError(f"{name} is locked")

        def fake_run(*cmd):
            name = "watchdog remove" if "ark_watchdog.py" in " ".join(map(str, cmd)) else "task delete"
            maybe_raise(name)
            return 0

        saved = [getattr(switch, n) for n in NAMES] + [legacy.remove, getattr(switch, "UNINSTALL_LEFT", None)]
        switch.APP = app
        switch.stop = lambda: steps.append("stop") or 0
        switch.start = lambda: steps.append("start") or 0
        switch._handover_rollback = lambda: steps.append("rollback") or rollback_rc
        switch.run = fake_run
        switch.delete_task_folder = lambda: maybe_raise("task folder") or True
        switch._mark_watchdog_stopped = lambda on: maybe_raise("marker")
        legacy.remove = lambda: maybe_raise("legacy remove") or []
        switch.UNINSTALL_LEFT = left_file
        try:
            rc = quiet(switch.uninstall)
        finally:
            for n, v in zip(NAMES, saved[:len(NAMES)], strict=True):
                setattr(switch, n, v)
            legacy.remove = saved[len(NAMES)]
            if saved[-1] is None:
                del switch.UNINSTALL_LEFT
            else:
                switch.UNINSTALL_LEFT = saved[-1]
        left = left_file.read_text(encoding="utf-8") if left_file.exists() else ""
        return steps, rc, left


    ALL = ["stop", "rollback", "watchdog remove", "marker", "task delete", "task folder",
           "legacy remove"]

    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        print("[everything works: exit 0, nothing listed]")
        steps, rc, left = uninstall_in(t / "a")
        check("every step", steps, ALL)
        check("exit 0", rc, 0)
        check("no uninstall-left.txt", left, "")

        print("[AUTO-MAS not put back: nothing removed, relay started, exit 3]")
        steps, rc, left = uninstall_in(t / "b", rollback_rc=1)
        check("steps", steps, ["stop", "rollback", "start"])
        check("exit 3", rc, 3)

        for broken in ("watchdog remove", "marker", "task delete", "task folder", "legacy remove"):
            print(f"[{broken} raises: every other step still runs, exit 7, listed]")
            steps, rc, left = uninstall_in(t / broken.replace(" ", "-"), raise_in=broken)
            check(f"{broken}: every step tried", steps, ALL)
            check(f"{broken}: exit 7 (not 0, not 3)", rc, 7)
            check(f"{broken}: listed in uninstall-left.txt", f"{broken} is locked" in left, True)

    print("[legacy.remove: one item that fails does not stop the rest]")
    deleted, runs = [], []
    saved = (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
             legacy.service_exists, legacy.TAKEOVER_RECORD)


    def fake_delete(p):
        if "locked" in str(p):
            raise PermissionError(f"{p} in use")
        deleted.append(str(p))
        return []


    legacy.items = lambda: [
        {"kind": "file", "path": "C:\\locked.bat", "action": "remove"},
        {"kind": "file", "path": "C:\\free.bat", "action": "remove"},
        {"kind": "task", "name": "ark-old", "action": "remove"},
        {"kind": "service", "name": "ark-svc", "action": "takeover"},
        {"kind": "file", "path": "C:\\kept.txt", "action": "keep"},
    ]
    legacy._delete_path = fake_delete
    legacy._run = lambda *cmd: runs.append(" ".join(cmd)) or (5 if cmd[:2] == ("sc", "delete") else 0)
    legacy._task_names = lambda: ["ark-old"]
    legacy.service_exists = lambda name: True
    with tempfile.TemporaryDirectory() as t:
        legacy.TAKEOVER_RECORD = Path(t) / "legacy-takeover.json"
        try:
            out = quiet(legacy.remove)
        finally:
            (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
             legacy.service_exists, legacy.TAKEOVER_RECORD) = saved
    check("the items after the locked one still removed",
          (deleted, "schtasks /delete /tn ark-old /f" in runs), (["C:\\free.bat"], True))
    check("returns what was not removed (the locked file, the failed sc delete)",
          isinstance(out, list) and len(out) == 2 and "locked.bat" in out[0] and "ark-svc" in out[1], True)
    legacy.items = lambda: (_ for _ in ()).throw(ValueError("bad json"))
    try:
        out = quiet(legacy.remove)
    finally:
        legacy.items = saved[0]
    check("an unreadable list is one failure, not an exception",
          isinstance(out, list) and len(out) == 1 and "bad json" in out[0], True)

    print("[uninstall removes the OK-WW overlay file, and nothing else in OK-WW]")
    # gamesim U9 reported that no code removes ok_tasks/ark_overrides.py (its install cycle
    # deleted the file itself). It is removed: legacy-items.json lists it as a `file` item with
    # action `takeover`, and legacy.remove() deletes every remove/takeover item. Pinned here with
    # the real list, the real remove() and the real _delete_path.
    sys.path.insert(0, str(RELAY))
    from pathlib import PureWindowsPath
    from ark_relay.features import okww_overlay

    OKWW_ROOT = PureWindowsPath(r"D:\ark\okww")     # the machine's OK-WW folder (legacy-items.json)
    want = PureWindowsPath(*okww_overlay._WORKING, okww_overlay.TASKS_DIR, okww_overlay.FILE_NAME)
    saved_items_file = legacy.ITEMS
    legacy.ITEMS = RELAY / "handover" / "legacy-items.json"     # handover\ next to legacy.py when packaged
    real_items = legacy.items()
    ours = [it for it in real_items if it.get("kind") == "file"
            and PureWindowsPath(it["path"]).name == okww_overlay.FILE_NAME]
    check("legacy-items.json lists the overlay file once, as removed at uninstall",
          [(it["action"] in ("remove", "takeover"), PureWindowsPath(it["path"]) == OKWW_ROOT / want) for it in ours],
          [(True, True)])
    asked = []
    saved = (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
             legacy.service_exists, legacy.TAKEOVER_RECORD)
    legacy._delete_path = lambda p: asked.append(PureWindowsPath(str(p))) or []
    legacy._run = lambda *cmd: 0
    legacy._task_names = lambda: []
    legacy.service_exists = lambda name: False
    with tempfile.TemporaryDirectory() as t:
        legacy.TAKEOVER_RECORD = Path(t) / "legacy-takeover.json"
        try:
            quiet(legacy.remove)
        finally:
            (legacy.items, legacy._delete_path, legacy._run, legacy._task_names,
             legacy.service_exists, legacy.TAKEOVER_RECORD) = saved
            legacy.ITEMS = saved_items_file
    check("remove() with the real list deletes the overlay file", OKWW_ROOT / want in asked, True)
    check("and nothing else under OK-WW's folder",
          [str(p) for p in asked if str(p).lower().startswith(str(OKWW_ROOT).lower() + "\\")
           and not (p.match("*.py.bak-*") and p.parent.name == "task")], [str(OKWW_ROOT / want)])
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / "okww"
        dest = okww_overlay.target(root)
        dest.parent.mkdir(parents=True)
        dest.write_text("# ours\n", encoding="utf-8")
        theirs = dest.parent / "user_task.py"           # a task the owner put there himself
        theirs.write_text("# his\n", encoding="utf-8")
        upstream = root.joinpath(*okww_overlay._WORKING, "src", "task", "DailyTask.py")
        upstream.parent.mkdir(parents=True)
        upstream.write_text("# upstream\n", encoding="utf-8")
        local = {**ours[0], "path": str(root.joinpath(*PureWindowsPath(ours[0]["path"]).relative_to(OKWW_ROOT).parts))} \
            if ours else {}
        failed, _ = quiet(legacy._remove_one, local, None) if ours else ([], None)
        check("the real removal of that item: our file gone, his task and upstream's file kept",
              (failed, dest.exists(), theirs.exists(), upstream.exists()), ([], False, True, True))

    print("[the uninstaller: 「中继已经重新开起来，什么都没删」 only for exit 3]")
    iss = (ROOT / "packaging" / "ark-relay.iss").read_text(encoding="utf-8-sig")
    m = re.search(r"\nprocedure CurUninstallStepChanged\b.*?\nend;", iss, re.S)
    body = m.group(0) if m else ""
    branches = re.split(r"\n    (?:else )?if Rc ", body)
    restarted = [b.split("\n", 1)[0] for b in branches if "中继已经重新开起来，什么都没删" in b]
    check("that message sits only in the Rc = 3 branch", restarted, ["= 3 then"])
    seven = next((b for b in branches if b.startswith("= 7 then")), "")
    check("exit 7 shows what is left (uninstall-left.txt) and does not abort",
          ("UninstallLeft()" in seven, "RaiseException" in seven), (True, False))
    check("the left list is read from the file switch.py writes",
          "uninstall-left.txt" in iss and switch.UNINSTALL_LEFT.name == "uninstall-left.txt"
          if hasattr(switch, "UNINSTALL_LEFT") else False, True)
    other = next((b for b in branches if b.startswith("<> 0 then")), "")
    check("any other code starts the relay again before aborting",
          0 <= other.find("RunSwitch('start')") < other.find("RaiseException"), True)

    print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))


def _part_manifest_covers_tree():
    import json
    import shutil
    import subprocess
    import tempfile

    RELAY = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(RELAY))


    original = (RELAY / "manifest.json").read_bytes()
    man = json.loads(original.decode("utf-8"))
    listed = set(man["files"])

    print("[顶层每个 .py 都在清单里]")
    top = {p.name for p in RELAY.glob("*.py")} - {"make-manifest.py"}
    check("顶层 .py 全覆盖", sorted(top - listed), [])
    check("service.py 在", "service.py" in listed, True)
    check("boot_stages.py 在（就是它没进清单，服务起不来）", "boot_stages.py" in listed, True)

    print("\n[ark_relay 包里每个 .py 都在清单里]")
    pkg = {p.relative_to(RELAY).as_posix() for p in (RELAY / "ark_relay").rglob("*.py")}
    check("包内 .py 全覆盖", sorted(pkg - listed), [])

    print("\n[清单里的每个文件都真的存在——否则部署会推一个空气]")
    check("清单无幽灵条目",
          sorted(f for f in listed if f != "RELEASE-NOTES.md" and not (RELAY / f).exists()), [])

    print("\n[新放一个文件进去，重新生成的清单必须收它]")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "relay"
        shutil.copytree(RELAY, copy,
                        ignore=shutil.ignore_patterns("tests", "state", "__pycache__"))
        (copy / "zz_manifest_probe.py").write_text("# 临时探针，测完就删\n", encoding="utf-8")
        out = subprocess.run([sys.executable, "make-manifest.py"], cwd=copy,
                             capture_output=True, text=True)
        check("生成器跑得起来", out.returncode, 0)
        again = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
        check("新文件被收进清单", "zz_manifest_probe.py" in again["files"], True)
        check("副本里的清单和真清单文件集一致（除探针）",
              sorted(set(again["files"]) - {"zz_manifest_probe.py"}), sorted(listed))

    check("真树里没留下探针", (RELAY / "zz_manifest_probe.py").exists(), False)
    check("真清单测试前后逐字节不变", (RELAY / "manifest.json").read_bytes() == original, True)

    print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    sys.exit(run_parts([_part_pkg_appfiles_update, _part_pkg_install_messages, _part_pkg_layout_names, _part_pkg_pin_whole_write, _part_pkg_runtime_update, _part_pkg_state_dir, _part_pkg_switch_failed_announce, _part_pkg_switch_flushed, _part_pkg_update_nothing_changed, _part_pkg_watchdog_update, _part_stop_denied, _part_stop_event_manual_reset, _part_stop_push_errwatch_budget, _part_switch_resume, _part_switch_run_encoding, _part_switch_stop, _part_switch_uninstall, _part_manifest_covers_tree]))
