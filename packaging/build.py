#!/usr/bin/env python3
"""Build the relay installer: stage the install folder, then compile it with Inno Setup.

    python packaging/build.py                 stage into packaging/stage, then run ISCC
    python packaging/build.py --stage-only    stage only (any OS; no ISCC needed)
    python packaging/build.py --runtime-only <dir>
                                              only <dir>/runtime/python (any OS): what a
                                              relay deploy sends when the machine's runtime
                                              differs (scripts/mac/lib/deploy-pkg.sh)

Runs on Windows with Python 3.14.8, the version the game machine and the CI job use
(.github/workflows/relay-windows.yml). What it puts in the stage, matching
packaging/ark-relay.iss:

    runtime/python/     the official embeddable Python (python.org), its ._pth opened to
                        Lib/site-packages, the packages in relay/requirements.txt
                        installed there as wheels, pywin32's DLLs and pythonservice.exe
                        copied next to python.exe so the watchdog service can load them
    versions/<n>/       the relay files listed in relay/manifest.json (the same set a
                        deploy ships), n = the manifest version; the build stops unless
                        every file's hash matches the manifest
    current.txt         n
    launch.py           packaging/launch.py
    watchdog/           packaging/watchdog/ark_watchdog.py
    handover/           relay/handover (AUTO-MAS handover, legacy list)

The embeddable Python "does not support pip"; packages are meant to be installed into
it from outside (https://docs.python.org/3/using/windows.html, "The embeddable
package"), which is what the `pip install --target` below does. The packages are passed
as the exact pins relay/requirements.txt has for Windows (pkg_appfiles.pins), not as
`-r requirements.txt`: pip evaluates an environment marker such as
`sys_platform == "win32"` against the Python running pip, not against --platform, so
on the Mac `-r` silently left pywin32 out (2026-10-11, the first --runtime-only try).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PY_VERSION = "3.14.8"
PY_TAG = "314"
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
REPO = Path(__file__).resolve().parents[1]
RELAY = REPO / "relay"
HERE = Path(__file__).resolve().parent
ISCC_DEFAULT = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")


def runtime_pins() -> "list[str]":
    """`name==version` for every package relay/requirements.txt pins for the Windows
    machine, read by the parser the deploy compares the machine's runtime with."""
    spec = importlib.util.spec_from_file_location(
        "pkg_appfiles", REPO / "scripts" / "mac" / "lib" / "pkg_appfiles.py")
    pa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pa)
    pins, loose = pa.pins((RELAY / "requirements.txt").read_text(encoding="utf-8"))
    if loose:
        raise SystemExit("relay/requirements.txt: not an exact pin: " + "; ".join(loose))
    return [f"{name}=={version}" for name, version in sorted(pins.items())]


def stage_runtime(stage: Path, cache: Path) -> Path:
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
                    "--target", str(site), *runtime_pins()], check=True)
    # pywin32's post-install copies these next to the interpreter; a service host
    # (pythonservice.exe) must find pywintypes / pythoncom and python314.dll there.
    for dll in (site / "pywin32_system32").glob("*.dll"):
        shutil.copy2(dll, py / dll.name)
    shutil.copy2(site / "win32" / "pythonservice.exe", py / "pythonservice.exe")
    return py


NOTES = "RELEASE-NOTES.md"


def _git(*args: str) -> "bytes | None":
    """stdout of a git command run in the repo; None when it fails or git is missing."""
    try:
        r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _hashes_match(data: bytes, rel: str, manifest: dict) -> bool:
    return (hashlib.sha256(data).hexdigest() == manifest["sha256"].get(rel)
            and hashlib.sha1(data).hexdigest() == manifest["files"].get(rel))


def notes_as_deployed(manifest: dict) -> "bytes | None":
    """relay/RELEASE-NOTES.md as the manifest describes it; None when no copy matches.

    deploy-relay.sh builds the manifest with the notes filled in, publishes, then empties
    the notes and commits both in the commit it tags with the manifest's `ref` (its
    0.5 gate, the clearing after publish-cos.py, and the commit at its end). So at every
    deploy tip the tree's notes are empty and differ from the manifest (2026-10-13:
    7ce92679, d6fb8004, 45584225), and the tagged commit holds the emptied copy too; the
    filled one is in the tag's parent. Tried in order, the first whose sha256 and sha1
    both match: the tree, `<ref>^`, `<ref>`. A checkout without the tag (CI: depth 1, no
    tags) fetches it first."""
    tree = RELAY / NOTES
    if tree.is_file() and _hashes_match(tree.read_bytes(), NOTES, manifest):
        return tree.read_bytes()
    ref = str(manifest.get("ref") or "")
    if not ref:
        return None
    if _git("rev-parse", "--verify", "--quiet", f"{ref}^^{{commit}}") is None:
        shallow = (_git("rev-parse", "--is-shallow-repository") or b"").strip() == b"true"
        _git("fetch", "--quiet", *(["--depth=2"] if shallow else []), "origin", "tag", ref)
    for rev in (f"{ref}^", ref):
        data = _git("show", f"{rev}:relay/{NOTES}")
        if data is not None and _hashes_match(data, NOTES, manifest):
            print(f"{NOTES}: taken from {rev} (the tree's copy is not the deployed one)")
            return data
    return None


def check_manifest(manifest: dict) -> "bytes | None":
    """Stop unless relay/manifest.json matches the tree, file for file and hash for hash.
    Returns RELEASE-NOTES.md as deployed (see notes_as_deployed), or None when the
    manifest does not list it.

    The installed relay updates itself against the deployed manifest by these hashes;
    a package built from a stale one ships files the manifest does not describe
    (2026-10-11: f5726361 changed four relay files after the last regeneration)."""
    files = manifest["sha256"]
    tree = {p.relative_to(RELAY).as_posix() for p in (RELAY / "ark_relay").rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".txt")}
    tree |= {p.name for p in RELAY.glob("*.py") if p.name != "make-manifest.py"}
    problems = [f"not listed: {rel}" for rel in sorted(tree - files.keys())]
    notes = None
    for rel, want in sorted(files.items()):
        src = RELAY / rel
        if rel == NOTES:
            notes = notes_as_deployed(manifest)
            if notes is None:
                problems.append(f"hash differs: {rel} (not in the tree, nor at "
                                f"{manifest.get('ref')}^ / {manifest.get('ref')})")
        elif not src.is_file():
            problems.append(f"listed, missing: {rel}")
        elif hashlib.sha256(src.read_bytes()).hexdigest() != want or \
                hashlib.sha1(src.read_bytes()).hexdigest() != manifest["files"].get(rel):
            problems.append(f"hash differs: {rel}")
    if problems:
        raise SystemExit("relay/manifest.json does not match the files; run "
                         "relay/make-manifest.py and commit it, then build again:\n  "
                         + "\n  ".join(problems))
    return notes


def stage_code(stage: Path) -> str:
    manifest = json.loads((RELAY / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest["version"])
    notes = check_manifest(manifest)
    files = manifest["sha256"]
    dest = stage / "versions" / version
    for rel in files:
        src = RELAY / rel
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        if rel == NOTES and notes is not None:
            (dest / rel).write_bytes(notes)
        else:
            shutil.copy2(src, dest / rel)
    shutil.copy2(RELAY / "manifest.json", dest / "manifest.json")
    (stage / "current.txt").write_text(version + "\n", encoding="ascii")
    return version


def stage_rest(stage: Path) -> None:
    shutil.copy2(HERE / "launch.py", stage / "launch.py")
    # The switch-over's AUTO-MAS step and the legacy list (relay/handover, standard
    # library only, run by packaging/switch.py and legacy.py).
    shutil.copytree(RELAY / "handover", stage / "handover",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (stage / "watchdog").mkdir()
    shutil.copy2(HERE / "watchdog" / "ark_watchdog.py", stage / "watchdog" / "ark_watchdog.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-only", action="store_true")
    ap.add_argument("--runtime-only", metavar="DIR")
    ap.add_argument("--iscc", default=str(ISCC_DEFAULT))
    args = ap.parse_args()
    if args.runtime_only:
        out = Path(args.runtime_only)
        if out.exists():
            shutil.rmtree(out)
        print("runtime staged", stage_runtime(out, HERE / "cache"))
        return 0
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
