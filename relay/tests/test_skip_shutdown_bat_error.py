"""skip-shutdown.bat shows Python's own error when the status read gives nothing.

The status read sent stderr to nul (`2^>nul`), so every failure - an import error
after a version change, an unreadable state.json - showed the same 「读不出来 ——
中继没装好，或者 Python 路径不对」. Now stderr goes to a temp file that is typed
when the read gives nothing (and the missing-Python case says that). STATE is
also cleared before each read: a menu redraw after a failed read showed the
previous value. No cmd.exe on the Mac, so the file is read as text.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
bat = (ROOT / "scripts" / "windows" / "skip-shutdown.bat").read_bytes().decode("utf-8").replace("\r\n", "\n")

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


read = next((ln for ln in bat.splitlines() if ln.startswith("for /f") and "skip_armed" in ln), "")
check("the status read is there", bool(read), True)
check("its stderr is not thrown away", "2^>nul" in read, False)
m = re.search(r'2\^>"(%\w+%)"', read)
check("its stderr goes to a file", bool(m), True)
var = m.group(1) if m else "%ERRF%"
empty = bat[bat.find('if "%STATE%"==""'):bat.find(") else (", bat.find('if "%STATE%"==""'))]
check("an empty read types that file", f'type "{var}"' in empty, True)
check("the old blanket reason is gone", "中继没装好，或者 Python 路径不对" in empty, False)
before = bat[:bat.find(read)] if read else ""
check("STATE is cleared before each read", 'set "STATE="' in before[before.rfind(":menu"):], True)
check("the error file is cleared before each read", f'del "{var}"' in before[before.rfind(":menu"):], True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
