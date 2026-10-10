"""Start the relay from the version folder named in current.txt (the packaged install).

The scheduled task \\ArkRelay\\main runs `runtime\\python\\pythonw.exe launch.py`. This file
sits outside the version folders and never changes, so an update or a rollback only has
to rewrite current.txt. `launch.py stop` / `launch.py rollback` pass through to app_main.
"""
import runpy
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent


def _key(name):
    head, _, tail = name.partition("-")
    return (int(head), int(tail or 0)) if (head + tail).isdigit() else (0, 0)


def _code_folder():
    """current.txt's folder; when that is missing or broken, the newest complete one
    (otherwise every start would fail the same way until someone fixed the file)."""
    try:
        cur = APP / "versions" / (APP / "current.txt").read_text(encoding="ascii").strip()
        if (cur / "app_main.py").is_file():
            return cur
    except (OSError, ValueError):
        pass
    ok = [p for p in (APP / "versions").iterdir()
          if not p.name.startswith(".") and (p / "app_main.py").is_file()]
    return max(ok, key=lambda p: _key(p.name))


CODE = _code_folder()
sys.path.insert(0, str(CODE))
sys.argv[0] = str(CODE / "app_main.py")
runpy.run_path(str(CODE / "app_main.py"), run_name="__main__")
