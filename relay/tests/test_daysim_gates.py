"""The day simulator runs the relay on a Mac and tells it "you are the machine".

It does that with one switch, `config.IS_WINDOWS`. A gate that asks `os.name` or
`sys.platform` itself would still see the Mac, and its branch (the busy / overrun
checks, the emergency-stop process list, OK-WW's process check, the MaaEnd
watchdog, the desktop pictures) would silently never run in the simulation - the
very code whose bugs a whole-day replay is meant to catch.

Checked here:
  1. no runtime `os.name` / `sys.platform` / `platform.system()` read is left
     outside config.py, except the files listed in REAL_HOST with the reason each
     one must keep seeing the real host;
  2. nothing imports IS_WINDOWS by name (`from ...config import IS_WINDOWS` would
     freeze the value at import, before the simulator sets it);
  3. each of the 11 former gates reads `config.IS_WINDOWS`;
  4. the read happens at call time: flipping the switch flips the gates' answers.
"""
import ast
import sys
import types
from pathlib import Path

RELAY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELAY))

from ark_relay.core import config                                  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}: {got!r}" if not ok else f"  ✓ {label}")
    if not ok:
        print(f"      want: {want!r}")
        fails.append(label)


# Files that must keep asking the real host, by file, with the reason.
REAL_HOST = {
    # Junction vs symlink and fsync of a folder are facts of the filesystem the
    # package lives on; the simulator's "you are the machine" must not make a Mac
    # run `cmd /c mklink`.
    "pkg_layout.py": "real filesystem: junction vs symlink, folder fsync",
    # CREATE_NO_WINDOW exists only in Windows' subprocess module; this asks whether
    # a real console is attached.
    "app_main.py": "real console and Windows-only subprocess flags",
    # Runs inside OK-WW's own Python, which cannot import the relay's config.
    "ark_relay/features/okww_patch/okww_files/ark_overrides.tasks.py":
        "runs in OK-WW's process, not the relay's",
}

# The 11 gates the simulator needs to flip (design E1), as (file, function).
GATES = [
    ("ark_relay/core/engine.py", "_script_running"),
    ("ark_relay/core/engine.py", "_scripts_running"),
    ("ark_relay/core/engine.py", "_run_watch"),
    ("ark_relay/features/phone/redbutton.py", "_estop_alive"),
    ("ark_relay/features/evidence/task_shots.py", "start"),
    ("ark_relay/features/banners/wuwa_posters.py", "image_reader"),
    ("ark_relay/features/okww_patch/okww_overlay.py", "okww_running"),
    ("ark_relay/features/run/maaend_watchdog.py", "__init__"),
    ("ark_relay/features/phone/mailbox.py", "close"),
    ("ark_relay/core/watch.py", "start"),
    ("ark_relay/__main__.py", "_pid_alive"),
]


def relay_sources():
    for p in sorted(RELAY.rglob("*.py")):
        rel = p.relative_to(RELAY).as_posix()
        if rel.startswith("tests/") or "__pycache__" in p.parts:
            continue
        yield rel, ast.parse(p.read_text(encoding="utf-8"), filename=rel)


def platform_reads(tree):
    """Line numbers of os.name, sys.platform and platform.system() reads."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if (n.value.id, n.attr) in (("os", "name"), ("sys", "platform"), ("platform", "system")):
                out.append(n.lineno)
    return sorted(out)


def reads_is_windows(fn):
    return any(isinstance(n, ast.Attribute) and n.attr == "IS_WINDOWS"
               and isinstance(n.value, ast.Name) and n.value.id == "config"
               for n in ast.walk(fn))


print("\n[1. no platform read outside config.py and the real-host files]")
trees = dict(relay_sources())
left = {rel: platform_reads(t) for rel, t in trees.items()}
left = {rel: lines for rel, lines in left.items()
        if lines and rel != "ark_relay/core/config.py" and rel not in REAL_HOST}
check("every other file asks config.IS_WINDOWS", left, {})
cfg_lines = platform_reads(trees["ark_relay/core/config.py"])
check("config.py reads os.name exactly once", len(cfg_lines), 1)
check("IS_WINDOWS is the real host by default", getattr(config, "IS_WINDOWS", None), sys.platform == "win32")
for rel in REAL_HOST:
    check(f"{rel} still exists (else drop it from REAL_HOST)", rel in trees, True)

print("\n[2. nobody freezes the switch at import]")
frozen = [f"{rel}:{n.lineno}" for rel, t in trees.items() for n in ast.walk(t)
          if isinstance(n, ast.ImportFrom) and any(a.name == "IS_WINDOWS" for a in n.names)]
check("no `from ... import IS_WINDOWS`", frozen, [])

print("\n[3. each of the 11 gates reads config.IS_WINDOWS]")
for rel, name in GATES:
    fns = [n for n in ast.walk(trees[rel])
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    check(f"{rel} {name}", any(reads_is_windows(f) for f in fns), True)

print("\n[4. the switch is read at call time]")
from ark_relay.core import procs                                   # noqa: E402
from ark_relay.features.evidence import task_shots                 # noqa: E402
from ark_relay.features.okww_patch import okww_overlay as ov       # noqa: E402
from ark_relay.features.run import maaend_watchdog as mw           # noqa: E402

real_switch, real_pp = config.IS_WINDOWS, procs.python_processes
procs.python_processes = lambda **kw: [(7, r"D:\ark\okww\data\apps\ok-ww\python\pythonw.exe main.py -t 1")]
try:
    config.IS_WINDOWS = False
    check("off: OK-WW check says it cannot tell", ov.okww_running(), None)
    check("off: no picture thread", task_shots.start(types.SimpleNamespace()), None)
    check("off: MaaEnd watchdog idle", mw.Watchdog(None, "debug", clock=lambda: 0.0).active, False)
    config.IS_WINDOWS = True
    check("on: OK-WW check reads the process list", ov.okww_running(), True)
    check("on: MaaEnd watchdog active", mw.Watchdog(None, "debug", clock=lambda: 0.0).active, True)
finally:
    config.IS_WINDOWS, procs.python_processes = real_switch, real_pp

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
