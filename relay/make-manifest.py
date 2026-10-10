#!/usr/bin/env python3
"""Regenerate manifest.json from the working tree.

Run this after changing any relay file, before pushing. The game machine's
selfupdate trusts the pushed manifest completely, and a stale one does not
merely miss an update - at the next boot it actively reverts the machine to
whatever the repo last said. A brand-new .py/.md/.txt/.json file is created by
selfupdate on its own since 2026-09-15 (selfupdate._NEW_FILE_SUFFIXES); any other
new file must still be deployed by hand once.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# RELEASE-NOTES.md must be pushed along with the rest: the update announcement
# reads it out, and what it reads is "which problems got fixed". On 2026-08-26, when
# this feature was first added, it was left out of the manifest; the deploy reported
# "success" while the file was simply not on the machine, and the announcement
# silently fell back to listing file names — the feature was not live at all. This is
# exactly what "pushed != in effect" means.
_extra = [f for f in ("RELEASE-NOTES.md",) if (HERE / f).exists()]
# Every file under ark_relay/ ships: the .py files at any depth (core/, features/<name>/,
# the machine checks, the OK-WW patches) and the OK-WW payload under okww_patch/okww_files
# (.py whole-file replacements and the .txt pristine fragments the linters must not
# compile). A hand-written list drifted from the tree twice: boot_stages.py on 2026-09-08
# and an okww_files fragment on 2026-09-09 were left off the machine.
_tree = [p.relative_to(HERE).as_posix() for p in sorted((HERE / "ark_relay").rglob("*"))
         if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".txt")]
files = sorted(_tree + [p.name for p in HERE.glob("*.py") if p.name != "make-manifest.py"] + _extra)
# Monotonic version. selfupdate refuses any manifest older than the one the
# machine has applied: a CDN can hold a whole stale snapshot (old manifest plus
# matching old files), which is internally consistent and would silently roll
# the machine back without this gate.
version = int(datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
# `ref` names the git tag deploy-relay.sh pushes on the commit that carries this
# manifest. The machine fetches the files at that tag when it has to use the
# GitHub doors: a tag never moves, so a mirror cannot hand back last week's copy
# of a file - which is exactly what cdn and gcore did on the evening of
# 2026-09-18, eight hours after the push and the purge, at `@main`.
# `sha256` is what the relay checks each file by since 2026-10-07 (selfupdate.
# _expected_hashes; hashlib lists SHA-1 as legacy). `files` stays SHA-1 for one
# version: a machine still on the older code reads only `files`, and it must be
# able to update onto the code that reads `sha256`. scripts/mac/deploy-relay.sh
# (its ark-verify.py) also still compares `files` as SHA-1. Once every machine
# runs the SHA-256 code, `files` can carry SHA-256 too and the verify script
# switch with it.
manifest = {"version": version,
            "ref": f"relay-{version}",
            "files": {
    f: hashlib.sha1((HERE / f).read_bytes()).hexdigest()
    for f in files},
            "sha256": {
    f: hashlib.sha256((HERE / f).read_bytes()).hexdigest()
    for f in files}}
(HERE / "manifest.json").write_text(
    json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"manifest.json 已重建：{len(files)} 个文件")
