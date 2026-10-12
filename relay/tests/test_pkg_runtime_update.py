"""A relay deploy swaps the installed relay's runtime when it is not what the repo builds.

Until 2026-10-11 only setup.exe replaced {app}\\runtime\\python, and a deploy whose
runtime differed stopped with exit 5, so every Python patch release meant running the
installer again. The user's words, 10-11 16:37, kept verbatim: 「为啥要重新安装？你们现在搞一次更新这么麻烦了吗？」
Now (packaging/README.md, "The runtime"): 3.0p builds the runtime on the Mac
(packaging/build.py --runtime-only), sends it, and the machine checks and runs it
(pkg_deploy.py runtime-check); 4.6p swaps it in on its own python.exe (pkg_deploy.py
runtime) right before the restart; a failure puts the previous runtime back. Checked here:
  - build.py: the pins come from relay/requirements.txt's Windows lines (pywin32 too, on
    a Mac, where pip's marker evaluation dropped it: the first --runtime-only try,
    10-11), the runtime is staged as the installer stages it, the workflows use the
    same Python;
  - pkg_deploy.py with a stand-in for the services and processes: different = swapped
    in this order and verified; the same = deploy-pkg.sh never calls the machine;
    a failed stop / rename / verify / watchdog start = the previous runtime back as it
    was; runtime-back and the leftovers;
  - deploy-pkg.sh's 3.0p and 4.6p blocks in bash (ssh and the machine's Python run
    locally on a temp {app}; the "python.exe" probed is a shell script), and the order.
"""
import contextlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PD_PATH = ROOT / "scripts/windows/pkg_deploy.py"
PA_PATH = ROOT / "scripts/mac/lib/pkg_appfiles.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pd = load("pkg_deploy", PD_PATH)
pa = load("pkg_appfiles", PA_PATH)
build = load("build", ROOT / "packaging/build.py")

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


def quiet(fn, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*args)
    return rc, buf.getvalue().splitlines()


WANT_PY = pa.py_version((ROOT / "packaging/build.py").read_text(encoding="utf-8"))
PINS = build.runtime_pins()

print("[build.py: what the runtime is built from]")
check("PY_VERSION", build.PY_VERSION, "3.14.8")
check("the embeddable zip of that version", build.EMBED_URL.endswith(f"/{build.PY_VERSION}/python-{build.PY_VERSION}-embed-amd64.zip"), True)
check("pins from requirements.txt's Windows lines, pywin32 included", PINS, ["pillow==12.3.0", "pywin32==312"])
for wf in ("relay-windows.yml", "package-windows.yml", "package-switch.yml"):
    got = re.findall(r"python-version: '([^']+)'", (ROOT / ".github/workflows" / wf).read_text(encoding="utf-8"))
    check(f"{wf} sets up the same Python", got, [build.PY_VERSION])

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
    rc, out = quiet(pd.runtime_check, app, WANT_PY, PINS, ops)
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
        rc, out = quiet(pd.runtime_check, app, WANT_PY, PINS, ops)
        check(f"{label}: refused, nothing run", (rc, out[-1].startswith("RUNTIME_FAIL nothing changed"), want in out[-1], ops.calls),
              (1, True, True, []))
for label, ops, want in (
        ("another Python", FakeRuntime(new=probe_json("3.14.7", {"Pillow": "12.3.0", "pywin32": "312"})), "Python 3.14.7 != " + WANT_PY),
        ("pywin32 not the pin", FakeRuntime(new=probe_json(WANT_PY, {"Pillow": "12.3.0", "pywin32": "311"})), "pywin32 311 != 312"),
        ("it does not run", FakeRuntime(fail={"probe"}), "does not run")):
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td)
        rc, out = quiet(pd.runtime_check, app, WANT_PY, PINS, ops)
        check(f"{label}: refused", (rc, want in out[-1]), (1, True))
check("names compared as PEP 503", pd.runtime_gaps(probe_json(WANT_PY, {"PILLOW": "12.3.0", "PyWin32": "312"}), WANT_PY, PINS), [])

print("[runtime: different = copy beside, stop, two renames, verify, watchdog on the new one]")
with tempfile.TemporaryDirectory() as td:
    app = make_app(td)
    ops = FakeRuntime(busy=2)
    rc, out = quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
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
    rc, out = quiet(pd.runtime_back, app, FakeRuntime())
    check("runtime-back after it: the old one back", (rc, out[-1], tree(app / "runtime" / "python")),
          (0, "RUNTIME_BACK restored", OLD_TREE))
    check("runtime-back: the new one kept as python.failed", tree(app / "runtime" / pd.RUNTIME_FAILED), NEW_TREE)
with tempfile.TemporaryDirectory() as td:
    app = make_app(td)
    ops = FakeRuntime(kind="DISABLED")
    rc, out = quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
    check("watchdog disabled (a revert): swapped, the watchdog neither stopped nor started",
          (rc, ops.calls), (0, ["start_type", "stop_relay", "holders", ("probe", "NEW")]))

print("[runtime: a failure before the rename changes nothing]")
with tempfile.TemporaryDirectory() as td:
    app = make_app(td, staged=False)
    ops = FakeRuntime()
    rc, out = quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
    check("nothing staged: exit 1, no call at all", (rc, ops.calls, tree(app / "runtime" / "python")), (1, [], OLD_TREE))
with tempfile.TemporaryDirectory() as td:
    app = make_app(td)
    ops = FakeRuntime(busy="always")
    rc, out = quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
    check("still running from it after the stops: exit 1, nothing changed, the watchdog started again",
          (rc, out[-2].startswith("RUNTIME_FAIL stop: still running"), ops.calls[-1], tree(app / "runtime" / "python"),
           (app / "runtime" / pd.RUNTIME_PREV).exists()), (1, True, "start_watchdog", OLD_TREE, False))
    check("waited RUNTIME_FREE_S looks", ops.calls.count("holders"), pd.RUNTIME_FREE_S)
with tempfile.TemporaryDirectory() as td:
    app = make_app(td)
    ops = FakeRuntime(fail={"stop_watchdog"})
    rc, out = quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
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
        rc, out = quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
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
        rc, out = quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
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
        rc, out = quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
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
        rc, out = quiet(pd.runtime_swap, app, WANT_PY, PINS, ops)
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
    rc, out = quiet(pd.runtime_back, app, ops)
    check("runtime-back with no runtime\\python and a relay stop that raises: still restored",
          (rc, out[-1], tree(app / "runtime" / "python"), ops.calls[-1]), (0, "RUNTIME_BACK restored", OLD_TREE, "start_watchdog"))

print("[runtime-back, runtime-stage, runtime-done]")
with tempfile.TemporaryDirectory() as td:
    app = make_app(td)
    ops = FakeRuntime()
    rc, out = quiet(pd.runtime_back, app, ops)
    check("no python.prev: nothing put back, only the watchdog started (a lost answer may have stopped it)",
          (rc, out, ops.calls, tree(app / "runtime" / "python")), (0, ["RUNTIME_BACK nothing"], ["start_type", "start_watchdog"], OLD_TREE))
with tempfile.TemporaryDirectory() as td:
    app = make_app(td)
    for name in (pd.RUNTIME_PREV, pd.RUNTIME_FAILED):
        (app / "runtime" / name).mkdir()
        (app / "runtime" / name / "python.exe").write_text("EARLIER", encoding="utf-8")
    rc, out = quiet(pd.runtime_stage, app)
    check("runtime-stage: an empty .incoming, an earlier change's python.prev and python.failed gone",
          (out, os.listdir(app / "runtime" / pd.RUNTIME_IN), (app / "runtime" / pd.RUNTIME_PREV).exists(),
           (app / "runtime" / pd.RUNTIME_FAILED).exists(), tree(app / "runtime" / "python")),
          ([f"RUNTIME_IN={app / 'runtime' / pd.RUNTIME_IN}"], [], False, False, OLD_TREE))
    rc, out = quiet(pd.runtime_back, app, FakeRuntime())
    check("so a runtime-back in this deploy cannot bring back an earlier runtime", out, ["RUNTIME_BACK nothing"])
with tempfile.TemporaryDirectory() as td:
    app = make_app(td)
    quiet(pd.runtime_swap, app, WANT_PY, PINS, FakeRuntime())
    quiet(pd.runtime_done, app)
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
# gate), where 3.0p itself runs; the Windows CI job runs the rest of this file.
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
rc, out = bash_gate(same)
check("the same: no prepare, no swap", (rc, out), (0, ["SWAP=0"]))
rc, out = bash_gate(same.replace("pywin32==312", "pywin32==311").replace(WANT_PY, "3.14.7"))
check("different: both gaps named, prepared, swap later", (rc, "PREPARE_CALLED" in out, out[-1], sum("->" in x for x in out)),
      (0, True, "SWAP=1", 2))
rc, out = bash_gate(same.replace(WANT_PY, "3.14.7"), prepare_ok=False)
check("different, not ready: exit 5 before any code is pushed", (rc, "SWAP=1" in out), (5, False))

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
