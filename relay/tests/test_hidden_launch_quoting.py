"""The windowless launch builds a PowerShell command that survives a path with a space.

2026-10-11 (07d90b11) the windowless route moved the program path into the task's
arguments. `subprocess.list2cmdline` puts double quotes round any argument with a
space, and `_spawn_via_task` pasted that string inside a double-quoted PowerShell
string (`-Argument "..."`): the first inner quote closed it. The OK-WW failure
screenshot starts C:\\Program Files\\PowerShell\\7\\pwsh.exe (handle.py, `_PWSH7`), so
its task action got a cut-off argument string plus loose words, and the picture was
never taken. relay.log has no 「pwsh.exe（无窗口）」 line since that change.

No PowerShell here: the command `_spawn_via_task` hands to pwsh is captured and
parsed with PowerShell's argument-mode quoting rules (about_Quoting_Rules,
about_Parsing), then the -Argument value is split the way a Windows program splits
its command line (CommandLineToArgvW), and must give back the exact arguments.
"""
import subprocess
import sys
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.features.preupdate import preupdate_common as C  # noqa: E402
from _tmp import tmpdir  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def ps_statements(script: str) -> list[list[str]]:
    """Statements of a PowerShell command line, each a list of argument-mode tokens.

    Quoting as PowerShell reads it: '...' is literal ('' is one quote); "..." ends at
    the next unescaped " (`x and "" escape); a token that starts with a quote ends at
    its closing quote, a bare token runs on through embedded quoted parts until white
    space or ';'. Enough for the one statement under test; not a full parser."""
    out, cur, i, n = [], [], 0, len(script)
    while i < n:
        c = script[i]
        if c in " \t":
            i += 1
            continue
        if c == ";":
            out.append(cur)
            cur = []
            i += 1
            continue
        tok, started_quoted = "", c in "'\""
        while i < n and script[i] not in " \t;":
            q = script[i]
            if q == "'":
                i += 1
                while i < n:
                    if script[i] == "'" and i + 1 < n and script[i + 1] == "'":
                        tok += "'"
                        i += 2
                    elif script[i] == "'":
                        i += 1
                        break
                    else:
                        tok += script[i]
                        i += 1
            elif q == '"':
                i += 1
                while i < n:
                    if script[i] == "`" and i + 1 < n:
                        tok += script[i + 1]
                        i += 2
                    elif script[i] == '"' and i + 1 < n and script[i + 1] == '"':
                        tok += '"'
                        i += 2
                    elif script[i] == '"':
                        i += 1
                        break
                    else:
                        tok += script[i]
                        i += 1
            else:
                tok += q
                i += 1
                continue
            if started_quoted:
                break
        cur.append(tok)
    if cur:
        out.append(cur)
    return out


def win_argv(line: str) -> list[str]:
    """Split a command line as the C runtime / CommandLineToArgvW does (the inverse of list2cmdline)."""
    args, cur, inq, have, i = [], "", False, False, 0
    while i < len(line):
        c = line[i]
        if c == "\\":
            j = i
            while j < len(line) and line[j] == "\\":
                j += 1
            k = j - i
            if j < len(line) and line[j] == '"':
                cur += "\\" * (k // 2)
                if k % 2:
                    cur += '"'
                    i = j + 1
                else:
                    i = j
                have = True
                continue
            cur += "\\" * k
            i = j
            have = True
            continue
        if c == '"':
            inq = not inq
            have = True
            i += 1
            continue
        if c in " \t" and not inq:
            if have:
                args.append(cur)
            cur, have = "", False
            i += 1
            continue
        cur += c
        have = True
        i += 1
    if have:
        args.append(cur)
    return args


def action_params(script: str) -> dict:
    """The New-ScheduledTaskAction statement as {"-Execute": v, ..., "loose": [...]}."""
    stmt = next(s for s in ps_statements(script) if any("New-ScheduledTaskAction" in t for t in s))
    toks = stmt[stmt.index(next(t for t in stmt if t.endswith("New-ScheduledTaskAction"))) + 1:]
    got, loose, i = {}, [], 0
    while i < len(toks):
        if toks[i] in ("-Execute", "-Argument", "-WorkingDirectory") and i + 1 < len(toks):
            got[toks[i]] = toks[i + 1]
            i += 2
        else:
            loose.append(toks[i])
            i += 1
    got["loose"] = loose
    return got


def captured_command(exe, cwd, args):
    """The -Command string _spawn_hidden_via_task passes to pwsh, with pythonw.exe present."""
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    saved = C.subprocess.run, C._pythonw, C._pwsh
    C.subprocess.run = fake_run
    C._pythonw = lambda: PureWindowsPath(r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe")
    C._pwsh = lambda: str(C._PWSH7)
    try:
        ok = C._spawn_hidden_via_task(exe, cwd, args)
    finally:
        C.subprocess.run, C._pythonw, C._pwsh = saved
    check("the launch reports success", ok, True)
    return seen[0][seen[0].index("-Command") + 1]


print("[the OK-WW failure screenshot: pwsh.exe under C:\\Program Files, windowless]")
work = tmpdir() / "desktop"             # no space: the program path alone breaks the old string
ps1 = r"C:\ProgramData\ark-relay\state\okww-shot.ps1"
script_args = ("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1)
cmd = captured_command(PureWindowsPath(str(C._PWSH7)), work, script_args)
got = action_params(cmd)
_, want_args, _ = C.hidden_plan(PureWindowsPath(str(C._PWSH7)), work, script_args,
                                PureWindowsPath(r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe"))
check("no loose word left beside -Execute / -Argument / -WorkingDirectory", got["loose"], [])
check("-Execute is pythonw.exe, whole", got.get("-Execute"),
      r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe")
check("-Argument is the whole list2cmdline string", got.get("-Argument"), subprocess.list2cmdline(list(want_args)))
check("the task's program gets back every argument, pwsh.exe's path in one piece",
      win_argv(got.get("-Argument", "")), list(want_args))
check("-WorkingDirectory is the folder", got.get("-WorkingDirectory"), str(work))

print("\n[a program path with no space: the route that worked before still does]")
cmd = captured_command(PureWindowsPath(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
                       tmpdir() / "desktop", ("-File", "agent.ps1"))
got = action_params(cmd)
check("no loose word", got["loose"], [])
check("arguments round-trip", win_argv(got.get("-Argument", ""))[-3:],
      [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", "-File", "agent.ps1"])

print("\n[a folder with a space and a quote in its name: the quote is written twice inside '...']")
odd = tmpdir() / "it's here"
cmd = captured_command(PureWindowsPath(str(C._PWSH7)), odd, ("-File", "a.ps1"))
got = action_params(cmd)
check("no loose word", got["loose"], [])
check("-WorkingDirectory keeps the quote and the space", got.get("-WorkingDirectory"), str(odd))
check("the launcher path in the folder comes back whole", (win_argv(got.get("-Argument", "")) + ["", ""])[1],
      str(odd / C.HIDDEN_LAUNCHER_NAME))

print("\n[the tokenizer itself reads the 10-11 command the way PowerShell does]")
old = ('$a=New-ScheduledTaskAction -Execute "C:\\py\\pythonw.exe" -Argument "-I C:\\w\\l.py '
       '"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -File a.ps1" -WorkingDirectory "C:\\w";')
got = action_params(old)
check("the old double-quoted -Argument is cut at the inner quote", got.get("-Argument"), "-I C:\\w\\l.py ")
check("and leaves loose words that bind to no parameter", len(got["loose"]) > 0, True)

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
