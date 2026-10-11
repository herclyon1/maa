#!/usr/bin/env python3
"""The Mac half of keeping the installed relay's files outside the version folders current.

The installer (packaging/ark-relay.iss, staged by packaging/build.py) writes, besides
{app}\\versions\\<n> and current.txt, which every deploy already writes:

    {app}\\launch.py              packaging/launch.py
    {app}\\switch.py              packaging/switch.py
    {app}\\legacy.py              packaging/legacy.py
    {app}\\handover\\*             relay/handover/* (tracked files)
    {app}\\watchdog\\ark_watchdog.py   packaging/watchdog/ark_watchdog.py
    {app}\\runtime\\python\\       python.org's embeddable Python + relay/requirements.txt

Until 2026-10-11 nothing else wrote them, so a change to any of them shipped only by
running setup.exe again. The user, 10-11 16:48: 「打包漏多少东西？能不能一次性搞好？」
lib/deploy-pkg.sh now asks the machine for each file's sha1 (pkg_deploy.py info) and
swaps only the ones that differ: the plain files (APP_FILES) before the relay restarts
on the new version, so the restart and the watch run through the new launch.py; the
watchdog after the watch (pkg_deploy.py watchdog, it needs a service restart).

The runtime ({app}\\runtime\\python) used to be the installer's alone, and the deploy
refused when it differed, so a Python patch release meant setup.exe again (the user,
10-11 16:37, quoted in relay/tests/test_pkg_runtime_update.py). Now the deploy compares the machine's runtime (Python version, the pinned
packages) with packaging/build.py PY_VERSION and relay/requirements.txt, and when they
differ it builds the runtime the installer would (build.py --runtime-only, on the Mac),
sends it with a sha1 per file, has the machine check it and run it (pkg_deploy.py
runtime-check), and swaps it in right before the restart (pkg_deploy.py runtime, run on
the new runtime's own python.exe: the relay and the watchdog hold the old one's DLLs,
so both are stopped first, and the old folder stays as python.prev for runtime-back).
The same runtime: nothing is built, sent or run.

    pkg_appfiles.py list                 "<rel>\\t<source, from the repo root>" per plain file
    pkg_appfiles.py changed <info>       the rels whose sha1 on the machine differs
    pkg_appfiles.py runtime-gap <info>   one line per difference; exit 1 when any
    pkg_appfiles.py runtime-want         the wanted Python version, then name==version per pin
    pkg_appfiles.py runtime-list <dir>   "<sha1> <path>" for every file under <dir>
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def app_files(repo: Path = REPO) -> "dict[str, Path]":
    """{app}-relative path -> repo file, for every plain installer-written file (the
    watchdog and the runtime have their own steps). handover is the tracked files, as
    build.py stages them from a checkout."""
    files = {"launch.py": repo / "packaging" / "launch.py",
             "switch.py": repo / "packaging" / "switch.py",
             "legacy.py": repo / "packaging" / "legacy.py"}
    try:
        tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "relay/handover"],
                                 capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        tracked = [p.relative_to(repo).as_posix() for p in sorted((repo / "relay" / "handover").rglob("*"))
                   if p.is_file() and "__pycache__" not in p.parts]
    for rel in tracked:
        files[rel[len("relay/"):]] = repo / rel
    return files


def _sha1(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()


def changed(info: str, files: "dict[str, Path]") -> "list[str]":
    """The rels whose sha1 on the machine (info's `SHA <rel> <sha1>` lines; MISSING when
    absent) is not the repo file's. A rel info did not report counts as changed."""
    remote = {}
    for line in info.splitlines():
        parts = line.split(" ")
        if len(parts) == 3 and parts[0] == "SHA":
            remote[parts[1]] = parts[2]
    return [rel for rel, src in files.items() if remote.get(rel) != _sha1(src)]


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()       # PEP 503


def pins(requirements: str) -> "tuple[dict[str, str], list[str]]":
    """name -> pinned version for the machine (Windows), and the lines that are not an
    exact pin (they cannot be checked, so they count as a gap)."""
    out, loose = {}, []
    for raw in requirements.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        req, _, marker = line.partition(";")
        marker = marker.strip()
        if "sys_platform" in marker and "win32" not in marker:
            continue                                   # not for the Windows machine
        m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s,]+)", req.strip())
        if m:
            out[_norm(m.group(1))] = m.group(2)
        else:
            loose.append(line)
    return out, loose


def py_version(build_py: str) -> str:
    m = re.search(r'^PY_VERSION = "([^"]+)"', build_py, re.M)
    return m.group(1) if m else ""


def runtime_gap(info: str, requirements: str, want_py: str) -> "list[str]":
    """What differs between the machine's runtime (info's RUNTIME_PY= and
    `RUNTIME_PKG <name>==<version>` lines) and what the repo builds."""
    have_py, have = "", {}
    for line in info.splitlines():
        if line.startswith("RUNTIME_PY="):
            have_py = line.split("=", 1)[1].strip()
        elif line.startswith("RUNTIME_PKG "):
            name, _, ver = line[len("RUNTIME_PKG "):].partition("==")
            have[_norm(name.strip())] = ver.strip()
    gaps = []
    if have_py != want_py:
        gaps.append(f"Python {have_py or 'unknown'} -> {want_py or 'unknown'} (packaging/build.py PY_VERSION)")
    want, loose = pins(requirements)
    for name, ver in sorted(want.items()):
        if have.get(name) != ver:
            gaps.append(f"{name} {have.get(name, 'not installed')} -> {ver} (relay/requirements.txt)")
    gaps += [f"not an exact pin, cannot be checked: {line} (relay/requirements.txt)" for line in loose]
    return gaps


def pins_of_repo() -> "tuple[dict[str, str], list[str]]":
    return pins((REPO / "relay" / "requirements.txt").read_text(encoding="utf-8"))


def runtime_list(folder: Path) -> "list[str]":
    """"<sha1> <path under folder, /-separated>" per file: what pkg_deploy.py
    runtime-check verifies the runtime sent against (files.sha1)."""
    return [f"{_sha1(p)} {p.relative_to(folder).as_posix()}"
            for p in sorted(folder.rglob("*")) if p.is_file()]


def main(argv: "list[str]") -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "list":
        for rel, src in app_files().items():
            print(f"{rel}\t{src.relative_to(REPO).as_posix()}")
        return 0
    if cmd == "changed":
        print("\n".join(changed(Path(argv[2]).read_text(encoding="utf-8"), app_files())))
        return 0
    if cmd == "runtime-gap":
        gaps = runtime_gap(Path(argv[2]).read_text(encoding="utf-8"),
                           (REPO / "relay" / "requirements.txt").read_text(encoding="utf-8"),
                           py_version((REPO / "packaging" / "build.py").read_text(encoding="utf-8")))
        print("\n".join(gaps))
        return 1 if gaps else 0
    if cmd == "runtime-want":
        pins, loose = pins_of_repo()
        if loose:
            print("not an exact pin: " + "; ".join(loose), file=sys.stderr)
            return 1
        print(py_version((REPO / "packaging" / "build.py").read_text(encoding="utf-8")))
        print("\n".join(f"{name}=={ver}" for name, ver in sorted(pins.items())))
        return 0
    if cmd == "runtime-list":
        print("\n".join(runtime_list(Path(argv[2]))))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
