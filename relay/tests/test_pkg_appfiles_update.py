"""A relay deploy keeps every installer-written file current, or refuses loudly.

The user, 10-11 16:48: 「打包漏多少东西？能不能一次性搞好？」 packaging/ark-relay.iss
writes, outside the version folders, launch.py, switch.py, legacy.py, handover\\*,
watchdog\\* and runtime\\; until 10-11 only setup.exe ever wrote them again. Checked here:
  - every [Files] entry of the .iss has an owner in the deploy (so a new installer-written
    path cannot be left out silently);
  - per plain file (launch.py, switch.py, legacy.py, each handover file): unchanged =
    the deploy does nothing with it; changed = swapped, read back, and put back by
    appfiles-back; a file that does not load or arrives damaged = nothing changed;
  - the Mac half of step 4.5p run in bash, with ssh and the package's Python stood in by
    local commands that run the real scripts/windows/pkg_deploy.py on a temp {app};
  - the runtime: what the machine has against packaging/build.py PY_VERSION and
    relay/requirements.txt; a difference refuses the deploy before anything changes;
  - the order of it all in deploy-pkg.sh.
The watchdog file has its own test (test_pkg_watchdog_update.py).
"""
import contextlib
import hashlib
import importlib.util
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PD_PATH = ROOT / "scripts/windows/pkg_deploy.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pd = load("pkg_deploy", PD_PATH)
pa = load("pkg_appfiles", ROOT / "scripts/mac/lib/pkg_appfiles.py")

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
    "{#Stage}\\runtime\\*": "runtime gate (refuses)",
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
    quiet(pd.appfiles_stage, app)
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
        rc, out = quiet(pd.appfiles, app, stage_send(app, [rel]))
        check("changed: swapped", (rc, out), (0, [f"APPFILE {rel}", "APPFILES_OK 1"]))
        check("changed: reads back as the repo file", sha(app / rel), sha(FILES[rel]))
        check("changed: no .new and no incoming folder left",
              ((app / (rel + ".new")).exists(), (app / pd.APPFILES_IN).exists()), (False, False))
        check("changed: the deploy's list is empty now", pa.changed(info_of(app), FILES), [])
        rc, out = quiet(pd.appfiles_back, app)
        check("appfiles-back: the old one back", (app / rel).read_text(encoding="utf-8"), old)
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td, {rel: "OLD = 1\n"})
        broken = b"{not json" if rel.endswith(".json") else b"def broken(:\n"
        pairs = [f"{rel}={hashlib.sha1(broken).hexdigest()}"]
        quiet(pd.appfiles_stage, app)
        (app / pd.APPFILES_IN / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / pd.APPFILES_IN / rel).write_bytes(broken)
        rc, out = quiet(pd.appfiles, app, pairs)
        check("does not load: exit 1, nothing changed",
              (rc, out[-1].startswith("APPFILES_FAIL nothing changed"), (app / rel).read_text(encoding="utf-8")),
              (1, True, "OLD = 1\n"))
    with tempfile.TemporaryDirectory() as td:
        app = make_app(td, {rel: "OLD = 1\n"})
        pairs = stage_send(app, [rel], {rel: FILES[rel].read_bytes()[:-1]})
        rc, out = quiet(pd.appfiles, app, pairs)
        check("arrived damaged: exit 1, nothing changed",
              (rc, out[-1].startswith("APPFILES_FAIL nothing changed"), (app / rel).read_text(encoding="utf-8")),
              (1, True, "OLD = 1\n"))

print("[several at once, one of them new on the machine; appfiles-back undoes all]")
with tempfile.TemporaryDirectory() as td:
    app = make_app(td, {"launch.py": "OLD = 1\n", "switch.py": "OLD = 2\n"})
    (app / "handover" / "leftovers.py").unlink()
    want = pa.changed(info_of(app), FILES)
    check("the three in the list", sorted(want), ["handover/leftovers.py", "launch.py", "switch.py"])
    rc, out = quiet(pd.appfiles, app, stage_send(app, want))
    check("all swapped", (rc, out[-1]), (0, "APPFILES_OK 3"))
    quiet(pd.appfiles_back, app)
    check("back: old contents, the new one gone",
          ((app / "launch.py").read_text(encoding="utf-8"), (app / "switch.py").read_text(encoding="utf-8"),
           (app / "handover" / "leftovers.py").exists()), ("OLD = 1\n", "OLD = 2\n", False))
    rc, out = quiet(pd.appfiles_back, app)
    check("back again: nothing left to put back", out, ["APPFILES_BACK 0"])
with tempfile.TemporaryDirectory() as td:
    app = make_app(td, {"launch.py": "OLD = 1\n"})
    quiet(pd.appfiles, app, stage_send(app, ["launch.py"]))
    (app / "launch.py").write_text("NEXT = 1\n", encoding="utf-8")
    quiet(pd.appfiles_stage, app)                       # the next deploy starts
    quiet(pd.appfiles_back, app)
    check("an earlier deploy's backup is dropped at the next stage (back cannot restore it)",
          (app / "launch.py").read_text(encoding="utf-8"), "NEXT = 1\n")

print("[deploy-pkg.sh 4.5p in bash: ssh and the package's Python run locally on a temp {app}]")
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

print("[the runtime: refused when it is not what the repo builds]")
req = (ROOT / "relay/requirements.txt").read_text(encoding="utf-8")
want_py = pa.py_version(build)
pins, loose = pa.pins(req)
check("requirements.txt pins read (pywin32's win32 marker kept)", (pins, loose), ({"pillow": "12.3.0", "pywin32": "311"}, []))
check("build.py PY_VERSION read", want_py, "3.14.7")
good = "RUNTIME_PY=3.14.7\nRUNTIME_PKG pillow==12.3.0\nRUNTIME_PKG pywin32==311\nRUNTIME_PKG pip==25.0\n"
check("the same: no gap", pa.runtime_gap(good, req, want_py), [])
check("names compared as PEP 503 (Pillow / pillow)", pa.runtime_gap(good.replace("pillow", "Pillow"), req, want_py), [])
check("another Python: a gap", len(pa.runtime_gap(good.replace("3.14.7", "3.14.6"), req, want_py)), 1)
check("another Pillow: a gap naming both versions",
      pa.runtime_gap(good.replace("12.3.0", "12.2.0"), req, want_py), ["pillow 12.2.0 -> 12.3.0 (relay/requirements.txt)"])
check("pywin32 missing: a gap", pa.runtime_gap(good.replace("RUNTIME_PKG pywin32==311\n", ""), req, want_py),
      ["pywin32 not installed -> 311 (relay/requirements.txt)"])
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
check("every anchor there", [a for a, p in zip(anchors, pos) if p < 0], [])
check("info -> runtime gate -> stage -> commit -> 4.5p -> restart -> watch -> rollback (with appfiles-back) -> 5.3",
      pos == sorted(pos), True)
gate = pkg_sh[pkg_sh.find("runtime-gap"):pkg_sh.find('pkg_py "$PKG_DEPLOY" stage')]
check("runtime gap: exit 5 before anything is pushed", "\n  exit 5\n" in gate, True)
fail45 = pkg_sh[pkg_sh.find("\n  if ! pkg_appfiles_step; then"):pkg_sh.find("APPFILES_SWAPPED=1")]
check("4.5p failed: appfiles-back, current.txt back, exit 8 (no restart)",
      ("appfiles-back" in fail45, 'back "$APP_WIN" "$PREV"' in fail45, "exit 8" in fail45, "pkg_restart" in fail45),
      (True, True, True, False))

if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all checks passed")
