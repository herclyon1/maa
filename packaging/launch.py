"""Start the relay from the version folder named in current.txt (the packaged install).

The scheduled task \\ArkRelay\\main runs `runtime\\python\\pythonw.exe launch.py`. This file
sits outside the version folders and never changes, so an update or a rollback only has
to rewrite current.txt. `launch.py stop` / `launch.py rollback` pass through to app_main.
"""
import runpy
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
CODE = APP / "versions" / (APP / "current.txt").read_text(encoding="ascii").strip()
sys.path.insert(0, str(CODE))
sys.argv[0] = str(CODE / "app_main.py")
runpy.run_path(str(CODE / "app_main.py"), run_name="__main__")
