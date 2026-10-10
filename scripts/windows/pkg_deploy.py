"""The machine side of deploy-relay.sh for the installed relay (packaging/ark-relay.iss).

The installed relay runs the version folder named in {app}\\current.txt
(relay/pkg_layout.py). A deploy never writes into the folder in use: the files go
into a new folder, which becomes current only once every hash matches, and going
back is pointing current.txt at the previous folder again. Run with the package's
own Python ({app}\\runtime\\python\\python.exe), the one the relay runs on.

    pkg_deploy.py info    <app>              CUR=<folder in use>  STATEDIR=<relay state dir>
    pkg_deploy.py stage   <app>              INCOMING=<empty folder to extract into>
    pkg_deploy.py commit  <app>              hashes, then INCOMING -> versions\\<n>, current.txt
                                             -> it; NAME=<n> PREV=<old>; or MISMATCH ...
    pkg_deploy.py back    <app> <folder>     current.txt -> <folder>; CURRENT=<folder>

Everything it prints for the script is KEY=value on its own line.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

DATA = Path(r"C:\ProgramData\ark-relay")
INCOMING = ".incoming"


def _layout(code: Path):
    """relay/pkg_layout.py from the given version folder (and its ark_relay)."""
    sys.path.insert(0, str(code))
    import pkg_layout  # noqa: PLC0415
    return pkg_layout


def _drop(folder: Path) -> None:
    link = folder / "state"
    if link.is_symlink() or os.path.isjunction(link):
        os.rmdir(link)                      # the junction only, never the data behind it
    shutil.rmtree(folder, ignore_errors=True)


def _state_dir() -> Path:
    """What the relay uses (relay/app_main.py _prepare_env): ARK_STATE_DIR from .env,
    else <data>\\ark-state."""
    try:
        for line in (DATA / ".env").read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip() == "ARK_STATE_DIR" and value.strip():
                return Path(value.split("#")[0].strip().strip('"').strip("'"))
    except OSError:
        pass
    return DATA / "ark-state"


def info(app: Path) -> int:
    print("CUR=" + (app / "current.txt").read_text(encoding="ascii").strip())
    print(f"STATEDIR={_state_dir()}")
    return 0


def stage(app: Path) -> int:
    inc = app / "versions" / INCOMING
    if inc.exists():
        _drop(inc)
    inc.mkdir(parents=True)
    print(f"INCOMING={inc}")
    return 0


def commit(app: Path) -> int:
    inc = app / "versions" / INCOMING
    manifest = json.loads((inc / "manifest.json").read_text(encoding="utf-8"))
    bad = []
    for rel, sha in manifest["files"].items():
        p = inc / rel
        got = hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else "MISSING"
        if got != sha:
            bad.append(f"{rel}: {got[:8]} != {sha[:8]}")
    if bad:
        print("MISMATCH " + "; ".join(bad))
        return 1
    print(f"HASH-OK {len(manifest['files'])}")
    pl = _layout(inc)
    prev = pl.current(app)
    pl.link_state(inc, DATA)
    version = str(manifest["version"])
    name, n = version, 0
    while (app / "versions" / name).exists():
        n += 1                              # the same version again: another copy, as an update does
        name = f"{version}-{n}"
    new = app / "versions" / name
    os.replace(inc, new)
    from ark_relay import selfupdate  # noqa: PLC0415 - from the folder just committed
    selfupdate._remember_version(new, int(version))   # else self-update would undo the deploy
    pl._pin(new, 0)                     # a deployed version ends a rollback's hold
    pl._set_current(app, name)
    pl._prune(app, keep={name, prev})
    print(f"NAME={name}")
    print(f"PREV={prev}")
    return 0


def back(app: Path, folder: str) -> int:
    if not (app / "versions" / folder / "app_main.py").is_file():
        print(f"NO-FOLDER {folder}")
        return 1
    pl = _layout(app / "versions" / folder)
    pl._set_current(app, folder)
    print("CURRENT=" + pl.current(app))
    return 0


def main(argv: list[str]) -> int:
    cmd, app = argv[1], Path(argv[2])
    if cmd == "info":
        return info(app)
    if cmd == "stage":
        return stage(app)
    if cmd == "commit":
        return commit(app)
    if cmd == "back":
        return back(app, argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
