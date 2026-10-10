#!/usr/bin/env python3
"""Build the relay installer: stage the install folder, then compile it with Inno Setup.

    python packaging/build.py                 stage into packaging/stage, then run ISCC
    python packaging/build.py --stage-only    stage only (any OS; no ISCC needed)

Runs on Windows with Python 3.14.7, the version the game machine and the CI job use
(.github/workflows/relay-windows.yml). What it puts in the stage, matching
packaging/ark-relay.iss:

    runtime/python/     the official embeddable Python (python.org), its ._pth opened to
                        Lib/site-packages, the packages in relay/requirements.txt
                        installed there as wheels, pywin32's DLLs and pythonservice.exe
                        copied next to python.exe so the watchdog service can load them
    versions/<n>/       the relay files listed in relay/manifest.json (the same set a
                        deploy ships), n = the manifest version
    current.txt         n
    launch.py           packaging/launch.py
    watchdog/           packaging/watchdog/ark_watchdog.py

The embeddable Python "does not support pip"; packages are meant to be installed into
it from outside (https://docs.python.org/3/using/windows.html, "The embeddable
package"), which is what the `pip install --target` below does.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PY_VERSION = "3.14.7"
PY_TAG = "314"
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
REPO = Path(__file__).resolve().parents[1]
RELAY = REPO / "relay"
HERE = Path(__file__).resolve().parent
ISCC_DEFAULT = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")


def stage_runtime(stage: Path, cache: Path) -> None:
    py = stage / "runtime" / "python"
    py.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / Path(EMBED_URL).name
    if not zip_path.exists():
        print("download", EMBED_URL)
        urllib.request.urlretrieve(EMBED_URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(py)
    pth = py / f"python{PY_TAG}._pth"
    lines = [ln for ln in pth.read_text(encoding="utf-8").splitlines() if ln.strip() != "#import site"]
    pth.write_text("\n".join(lines + ["Lib\\site-packages", "import site", ""]), encoding="utf-8")
    site = py / "Lib" / "site-packages"
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                    "--no-compile", "--only-binary=:all:", "--platform", "win_amd64",
                    "--python-version", PY_VERSION, "--implementation", "cp",
                    "--target", str(site), "-r", str(RELAY / "requirements.txt")], check=True)
    # pywin32's post-install copies these next to the interpreter; a service host
    # (pythonservice.exe) must find pywintypes / pythoncom and python314.dll there.
    for dll in (site / "pywin32_system32").glob("*.dll"):
        shutil.copy2(dll, py / dll.name)
    shutil.copy2(site / "win32" / "pythonservice.exe", py / "pythonservice.exe")


def stage_code(stage: Path) -> str:
    manifest = json.loads((RELAY / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest["version"])
    files = manifest.get("sha256") or manifest["files"]
    dest = stage / "versions" / version
    for rel in files:
        src = RELAY / rel
        if not src.is_file():
            raise SystemExit(f"manifest lists {rel} but relay/{rel} is missing: regenerate manifest.json")
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / rel)
    shutil.copy2(RELAY / "manifest.json", dest / "manifest.json")
    (stage / "current.txt").write_text(version + "\n", encoding="ascii")
    return version


def stage_rest(stage: Path) -> None:
    shutil.copy2(HERE / "launch.py", stage / "launch.py")
    (stage / "watchdog").mkdir()
    shutil.copy2(HERE / "watchdog" / "ark_watchdog.py", stage / "watchdog" / "ark_watchdog.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-only", action="store_true")
    ap.add_argument("--iscc", default=str(ISCC_DEFAULT))
    args = ap.parse_args()
    stage = HERE / "stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    version = stage_code(stage)
    stage_rest(stage)
    if args.stage_only:
        print("staged code version", version, "(no runtime: --stage-only)")
        return 0
    stage_runtime(stage, HERE / "cache")
    subprocess.run([args.iscc, f"/DStage={stage}", f"/DAppVersion={version}",
                    f"/O{HERE / 'dist'}", str(HERE / "ark-relay.iss")], check=True)
    print("built", HERE / "dist" / f"ArkRelay-Setup-{version}.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
