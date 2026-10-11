"""A desktop picture never puts a window on the screen.

2026-10-11 09:39 (evidence 2026-10-11_endfield_MaaEnd-05-30-34): the task-end
picture after 信用点购物 started PowerShell through the Interactive scheduled
task; its console window took the foreground from Endfield, which MaaEnd drives
with its foreground controller. The game stayed behind the taskbar for 25 s
(maafw.log: 159 x 「Failed to ensure foreground window before screencap」), the
taskbar covered the 「ENDFIELD」 mark MaaEnd's InMenuList check reads, and
转交委托 failed. Every picture or read that does not bring a window to the front
must go through the windowless route: pythonw.exe starting PowerShell with
CREATE_NO_WINDOW. No Windows here: spawns are faked.
"""
import ast
import json
import sys
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay.core.desktop import POWERSHELL, Desktop
from ark_relay.features.preupdate import preupdate_common as C
from _tmp import tmpdir

fails = []


def check(label, got, want=True):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {label}" if ok else f"  ✗ {label}: {got!r} != {want!r}")
    if not ok:
        fails.append(label)


def fake(tag, calls):
    """A spawn that behaves like the agent and records which route was used."""
    def spawn(exe, cwd, args):
        calls.append((tag, PureWindowsPath(exe).name))
        req, res = Path(args[-2]), Path(args[-1])
        r = json.loads(req.read_text(encoding="utf-8"))
        if r.get("shot"):
            Path(r["shot"]).write_bytes(b"\x89PNG fake")
        res.write_text(json.dumps({"ok": True, "log": [], "ocr": [], "clicked": []}), encoding="utf-8")
        return True
    return spawn


print("[the task-end picture and a plain read take the windowless route]")
calls = []
d = Desktop(tmpdir() / "state", spawn=fake("window", calls), spawn_hidden=fake("hidden", calls), timeout=5)
check("screenshot() got a file", d.screenshot() is not None, True)
d.read()
d.read_file(tmpdir() / "x.png")
check("screenshot, read and read_file all went windowless", [c[0] for c in calls], ["hidden"] * 3)
check("it is still PowerShell that runs the agent", {c[1] for c in calls}, {"powershell.exe"})

print("\n[a run that brings a window to the front keeps the measured route]")
calls.clear()
d.read(focus="Games")
check("focus -> the console-window route", [c[0] for c in calls], ["window"])

print("\n[a test that passes only spawn gets it for both]")
calls.clear()
Desktop(tmpdir() / "state", spawn=fake("only", calls), timeout=5).screenshot()
check("spawn used", [c[0] for c in calls], ["only"])

print("\n[the real default: no injected spawn uses the windowless launcher]")
d0 = Desktop(tmpdir() / "state")
check("hidden default is _spawn_hidden_default", d0._spawn_hidden, Desktop._spawn_hidden_default)
check("focus default is _spawn_default", d0._spawn, Desktop._spawn_default)

print("\n[the plan the scheduled task runs]")
cwd = tmpdir() / "desktop"
pyw = PureWindowsPath(r"C:\Program Files\ArkRelay\runtime\python\pythonw.exe")
PS = PureWindowsPath(POWERSHELL)   # Windows path semantics for .stem / .name on any host
prog, args, task = C.hidden_plan(PS, cwd, ("-File", "agent.ps1"), pyw)
check("the task starts pythonw.exe (a GUI program, no console)", prog.name, "pythonw.exe")
check("isolated mode, then the launcher, then PowerShell and its arguments",
      args, ("-I", str(cwd / C.HIDDEN_LAUNCHER_NAME), str(POWERSHELL), "-File", "agent.ps1"))
check("its own task name, apart from the focus route's",
      (task, task != C._task_name(PS.stem)), ("ark-preupdate-launch-powershell-hidden", True))

print("\n[the launcher starts its child with CREATE_NO_WINDOW and waits for it]")
tree = ast.parse(C.HIDDEN_LAUNCHER)
calls_ast = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "call"]
flags = [kw.value.value for c in calls_ast for kw in c.keywords
         if kw.arg == "creationflags" and isinstance(kw.value, ast.Constant)]
check("subprocess.call (waits), creationflags 0x08000000", flags, [0x08000000])

print("\n[_spawn_hidden_via_task writes the launcher and hands the plan to the task route]")
seen = []
saved = C._spawn_via_task, C._pythonw
try:
    C._spawn_via_task = lambda exe, cwd, args=(), **kw: seen.append((PureWindowsPath(exe).name, args, kw)) or True
    C._pythonw = lambda: pyw
    work = tmpdir() / "work"
    got = C._spawn_hidden_via_task(PS, work, ("-File", "a.ps1"))
    check("launched", got, True)
    check("launcher written next to the script", (work / C.HIDDEN_LAUNCHER_NAME).read_text(encoding="utf-8"),
          C.HIDDEN_LAUNCHER)
    check("task route got pythonw.exe and the hidden task name",
          (seen[0][0], seen[0][2]["task"].endswith("-hidden")), ("pythonw.exe", True))

    print("\n[no pythonw.exe: falls back to the plain route instead of not taking the picture]")
    seen.clear()
    C._pythonw = lambda: None
    C._spawn_hidden_via_task(PS, work, ("-File", "a.ps1"))
    check("plain route with PowerShell itself", (seen[0][0], seen[0][2]), ("powershell.exe", {}))

    print("\n[the OK-WW failure screenshot goes windowless too]")
    from ark_relay.features.alarm import handle
    used = []
    saved_h = C._spawn_hidden_via_task

    def hidden(exe, cwd, args=()):
        used.append(PureWindowsPath(exe).name)
        out.write_bytes(b"\x89PNG" + b"0" * 20_000)
        return True
    C._spawn_hidden_via_task = hidden
    C._spawn_via_task = lambda *a, **k: used.append("plain") or True
    try:
        out = tmpdir() / "screen.png"
        check("screenshot saved", handle._screenshot_to(out), True)
        check("only the windowless route was used", used, ["pwsh.exe"])
    finally:
        C._spawn_hidden_via_task = saved_h
finally:
    C._spawn_via_task, C._pythonw = saved

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
