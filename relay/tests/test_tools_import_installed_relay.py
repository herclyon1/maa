"""Tools that import ark_relay on the gaming machine import the installed relay's code.

Since the switch-over (packaging/switch.py install) the relay runs
C:\\Program Files\\ArkRelay\\versions\\<current.txt>\\ (relay/pkg_layout.py), and
C:\\ProgramData\\ark-relay holds only its data. The ark_relay folder still lying there is
the old relay's, frozen at the switch-over. Until 2026-10-11 healthcheck.py,
okww_effective.py, config-check.py, okww-landed.py, maaend_only_task.py,
waittime_roundtrip.py, boot_check_remote.py, the desktop switch skip-shutdown.bat and the
commands in docs/OPERATIONS.md all put that folder on sys.path: every check judged the
machine by the old code, and healthcheck.py's ensure_patches wrote the old OK-WW patches
over newer fixes. They now take the folder from scripts/mac/lib/relay_code.py (the .bat,
which sits alone on his desktop, reads current.txt itself).

Checked here:
  1. nothing under scripts/ or docs/ puts C:\\ProgramData\\ark-relay itself (literally, or
     through a name or %VAR% bound to it in the same file) on sys.path, or reads a file
     under C:\\ProgramData\\ark-relay\\ark_relay - except the listed files that are about
     the old relay on purpose;
  2. each of those tools imports relay_code on a line winrun.sh's module shipping sees;
  3. relay_code.code_root() picks versions\\<current.txt>, and the old folder (saying so)
     only when there is no installed relay;
  4. skip-shutdown.bat reads current.txt, has CRLF line endings, and does not start a
     for /f command with a quote (cmd /c then drops the first and last quote and the
     Python path no longer parses: its menu read 「读不出来」 every time, seen on the machine
     2026-10-11; with LF line endings cmd.exe ran fragments of its lines as commands).
"""
import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "mac" / "lib"))
import relay_code  # noqa: E402

fails = []


def require(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok or not detail else f": {detail}"))
    if not ok:
        fails.append(name)


# Files that address the old relay's folder on purpose.
ALLOW = {
    "scripts/mac/lib/relay_code.py": "the fallback for a machine without the installed relay",
    "scripts/windows/skip-shutdown.bat": "the same fallback, inline (checked in section 4)",
    "scripts/mac/deploy-relay.sh": "its old-layout branch deploys the old relay into that folder",
    "scripts/windows/smoke.py": "deploy smoke; deploy-pkg.sh passes --pkg-version, the default is the old layout",
}

# The old folder itself: backslashes as written in .py / .md / .bat / .sh (one, or doubled
# inside a string literal), optionally a trailing one, then the end of the literal.
OLD = r"ProgramData(?:\\{1,2}|/)ark-relay(?:\\{1,2}|/)?"
OLD_END = OLD + r"""\\?["')%]"""
SYSPATH = re.compile(r"sys\.path\.(?:insert|append)\(([^)\n]*)\)")
BIND_PY = re.compile(r"""(?:^|[;\s])([A-Za-z_]\w*)\s*=\s*[^;\n]*?""" + OLD_END, re.M)
BIND_BAT = re.compile(r"""^\s*set\s+"?([A-Za-z_]\w*)=[^\n"]*""" + OLD + r"""\s*"?\s*$""", re.M | re.I)
OLD_CODE_FILE = re.compile(OLD + r"(?:\\{1,2}|/)ark_relay\b")


def offences(text: str) -> list:
    out = []
    names = set(BIND_PY.findall(text)) | set(BIND_BAT.findall(text))
    for m in SYSPATH.finditer(text):
        arg = m.group(1) + ")"
        if re.search(OLD_END, arg) or re.search(OLD + r"\\?\\?\"", arg):
            out.append(m.group(0)[:120])
            continue
        for n in names:
            if re.search(rf"\b{n}\b|%{n}%", m.group(1)):
                out.append(f"{m.group(0)[:100]} ({n} = the old folder)")
    out += [f"reads old code: {m.group(0)}" for m in OLD_CODE_FILE.finditer(text)]
    return out


def scan(paths) -> dict:
    found = {}
    for p in paths:
        rel = p.relative_to(ROOT).as_posix()
        if rel in ALLOW:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "ark-relay" not in text:
            continue
        hits = offences(text)
        if hits:
            found[rel] = hits
    return found


print("[1. nothing puts the old folder on sys.path]")
files = [p for d in ("scripts", "docs") for p in (ROOT / d).rglob("*")
         if p.is_file() and p.suffix in (".py", ".sh", ".md", ".bat", ".ps1", ".txt")]
found = scan(files)
require(f"{len(files)} files under scripts/ and docs/", not found,
      "; ".join(f"{k}: {v[0]}" for k, v in sorted(found.items())))

# The scan has to recognise each shape the tools used before 2026-10-11.
SHAPES = {
    "literal": 'import sys\nsys.path.insert(0, r"C:\\ProgramData\\ark-relay")\n',
    "named": 'R = Path(r"C:\\ProgramData\\ark-relay")\nsys.path.insert(0, str(R))\n',
    "one line": 'root = pathlib.Path(r"C:\\ProgramData\\ark-relay"); sys.path.insert(0, str(root))\n',
    "bat": "set RELAY=C:\\ProgramData\\ark-relay\n\"%PY%\" -c \"import sys; sys.path.insert(0, r'%RELAY%')\"\n",
    "doc": 'winps.sh \'& py -c "import sys; sys.path.insert(0, r\\"C:\\ProgramData\\ark-relay\\"); x"\'\n',
    "old code file": 'ref = Path(r"C:\\ProgramData\\ark-relay\\ark_relay\\okww_files")\n',
}
for name, text in SHAPES.items():
    require(f"scan catches the {name} shape", bool(offences(text)), text)
DATA_ONLY = ('_load_dotenv(Path(r"C:\\ProgramData\\ark-relay\\.env"))\n'
             'st = Path(r"C:\\ProgramData\\ark-relay\\state")\n'
             'set DATA=C:\\ProgramData\\ark-relay\nPath(r\'%DATA%\\state\')\n')
require("scan leaves data paths alone", not offences(DATA_ONLY), str(offences(DATA_ONLY)))

print("\n[2. the tools import relay_code where winrun ships it]")
winrun = (ROOT / "scripts" / "mac" / "winrun.sh").read_text(encoding="utf-8")
m = re.search(r"grep -oE '(\^\(from\|import\) \+\[a-z_\]\[a-z0-9_\]\*)'", winrun)
require("winrun.sh still ships same-folder modules by their import line", bool(m))
SHIP = re.compile(m.group(1) if m else r"^(from|import) +[a-z_][a-z0-9_]*", re.M)
TOOLS = {
    "scripts/mac/lib/healthcheck.py": "use_relay_code()",
    "scripts/mac/lib/okww_effective.py": "use_relay_code()",
    "scripts/mac/lib/maaend_only_task.py": "use_relay_code()",
    "scripts/mac/lib/waittime_roundtrip.py": "use_relay_code()",
    "scripts/mac/lib/boot_check_remote.py": "code_root()",
    "scripts/windows/okww-landed.py": "use_relay_code()",
    "scripts/mac/config-check.py": "use_relay_code()",   # inside PROBE, shipped as its own file
}
for rel, call in TOOLS.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    shipped = any(s.split()[-1] == "relay_code" for s in SHIP.findall(text)) or \
        any(line.split()[1] == "relay_code" for line in text.splitlines()
            if SHIP.match(line) and len(line.split()) > 1)
    require(f"{rel}: imports relay_code at column 0 and calls {call}", shipped and call in text)

print("\n[3. relay_code.code_root]")
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    app, legacy = t / "ArkRelay", t / "ark-relay"
    (app / "versions" / "20261011073720" / "ark_relay").mkdir(parents=True)
    (app / "versions" / "20261011073720" / "ark_relay" / "__init__.py").write_text("")
    (app / "current.txt").write_text("20261011073720\n", encoding="ascii")
    got = relay_code.code_root(app, legacy)
    require("installed: versions\\<current.txt>", got == (app / "versions" / "20261011073720", True), str(got))
    (app / "current.txt").write_text("20261011999999\n", encoding="ascii")
    require("current.txt naming a folder without ark_relay: the old folder",
          relay_code.code_root(app, legacy) == (legacy, False))
    err = io.StringIO()
    saved = list(sys.path)
    with contextlib.redirect_stderr(err):
        got = relay_code.use_relay_code(t / "nothing", legacy)
    first = sys.path[0]
    sys.path[:] = saved
    require("no installed relay: the old folder, first on sys.path", got == legacy and first == str(legacy))
    require("... and one line on stderr saying so", "no installed relay" in err.getvalue()
          and "{" not in err.getvalue(), err.getvalue())

print("\n[4. skip-shutdown.bat]")
raw = (ROOT / "scripts" / "windows" / "skip-shutdown.bat").read_bytes()
lines = raw.split(b"\n")[:-1] if raw.endswith(b"\n") else raw.split(b"\n")
lf_only = sum(not l.endswith(b"\r") for l in lines)
require("CRLF on every line", lf_only == 0, f"{lf_only} LF-only lines")
bat = raw.decode("utf-8")
require("reads current.txt for the code folder",
      '"%APP%\\current.txt"' in bat and "%APP%\\versions\\%%v" in bat)
require("puts the code folder (not the data folder) on sys.path",
      bat.count("sys.path.insert(0, r'%CODE%')") == 3 and "sys.path.insert(0, r'%DATA%')" not in bat)
quoted = re.findall(r"""for /f [^\n]*?in \('"[^\n]*""", bat)
require("no for /f command starts with a quote", not quoted, quoted[0][:80] if quoted else "")
require("says when it falls back to the old code", "if defined OLDCODE echo" in bat)
require("runs the installed relay's own Python, never AUTO-MAS's",
        'set "PY=%APP%\\runtime\\python\\python.exe"' in bat and "automas" not in bat.lower())

print("\n" + ("FAILED: " + "; ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
