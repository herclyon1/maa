"""relay.log that cannot be created is said once errwatch is listening (audit
docs/SILENT-FAILURES-AUDIT.md, __main__.py:75).

_setup_logging runs before errwatch is installed, so a WARNING there would reach
stderr only. It keeps the OSError instead; boot_stages._stage_bootstrap says it
right after errwatch.install, so the group hears that the relay is running with
no relay.log (evidence slices, self-check and machine checks lose their source).
"""
import ast
import logging
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp import tmpdir


class _Any:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return _Any()
    def __getattr__(self, _): return _Any()


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


for name in ("win32serviceutil", "win32service", "win32event", "win32api",
             "win32con", "win32file", "servicemanager", "win32process",
             "win32security", "win32ts", "win32profile", "wmi", "pythoncom"):
    sys.modules.setdefault(name, _Stub(name))

import boot_stages  # noqa: E402
from ark_relay import __main__ as relay_main  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'} {label}: {got!r}")
    if not ok:
        fails.append(label)


print("[_setup_logging keeps the OSError when relay.log cannot be created]")
root = logging.getLogger()
saved_handlers, saved_env = root.handlers[:], os.environ.get("ARK_LOG_FILE")
blocker = tmpdir() / "not-a-dir"
blocker.write_text("x", encoding="utf-8")
try:
    root.handlers.clear()
    os.environ["ARK_LOG_FILE"] = str(blocker / "relay.log")    # its parent is a file
    relay_main._setup_logging(verbose=False)
    err = getattr(relay_main, "log_file_error", lambda: None)()
    check("the error is kept", isinstance(err, OSError), True)
    for h in root.handlers:
        h.close()
    root.handlers.clear()
    os.environ["ARK_LOG_FILE"] = str(tmpdir() / "relay.log")
    relay_main._setup_logging(verbose=False)
    check("a later good setup clears it", getattr(relay_main, "log_file_error", lambda: None)(), None)
    err_path = blocker / "relay.log"
finally:
    for h in root.handlers:
        h.close()
    root.handlers[:] = saved_handlers
    if saved_env is None:
        os.environ.pop("ARK_LOG_FILE", None)
    else:
        os.environ["ARK_LOG_FILE"] = saved_env

print("[boot_stages says it, once errwatch is installed]")
said = []
grab = type("G", (logging.Handler,), {"emit": lambda self, r: said.append((r.levelno, r.getMessage()))})()
svc = boot_stages.log
svc.addHandler(grab)
try:
    say = getattr(boot_stages, "_say_log_file_problem", None)
    if say is None:
        check("boot_stages has the step", False, True)
    else:
        relay_main._LOG_FILE_ERROR[0] = NotADirectoryError(20, "Not a directory", str(err_path))
        say(svc)
        check("one WARNING naming relay.log", [lv for lv, m in said if "relay.log" in m], [logging.WARNING])
        said.clear()
        relay_main._LOG_FILE_ERROR[0] = None
        say(svc)
        check("no error -> nothing said", said, [])
finally:
    svc.removeHandler(grab)
    if hasattr(relay_main, "_LOG_FILE_ERROR"):
        relay_main._LOG_FILE_ERROR[0] = None

print("[...and it runs right after errwatch.install in _stage_bootstrap]")
src = Path(boot_stages.__file__).read_text(encoding="utf-8")
fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_stage_bootstrap")
calls = [(n.lineno, ast.unparse(n.func)) for n in ast.walk(fn) if isinstance(n, ast.Call)]
install = [ln for ln, f in calls if f == "errwatch.install"]
step = [ln for ln, f in calls if f == "_say_log_file_problem"]
check("called once, after errwatch.install", (len(step), bool(install and step and step[0] > install[0])),
      (1, True))

print("\n" + ("FAILED: " + ", ".join(fails) if fails else "all checks passed"))
sys.exit(1 if fails else 0)
