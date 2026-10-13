#!/usr/bin/env python3
"""Fetch a MAA / AUTO-MAS upstream pin into relay/tests/gamesim/upstream/maa-<tag>/.

The pin is what gamesim/lib/maa_schema.py reads: MAA's GUI task classes, the GUI -> core
parameter maps, the core functions that take or refuse a task, MAA's drop-line formatting,
every resource/tasks/**/*.json at the tag, and the AUTO-MAS files that read a MAA script's
config. Files are stored byte for byte (Python sources with a .txt suffix, so the repo's
linters skip them); SOURCE.txt lists repo, tag, commit, git blob sha1 and sha256 per file,
and maa_schema.pin_problems() refuses any file that differs from its row. Nobody edits a
pin by hand: rerun this and commit the result.

    fetch_pin.py v6.19.0 --compare v6.19.0-beta.1 --note "<why this version>"
    fetch_pin.py v6.19.0-beta.1 --dev c09d3fe7 --dev cc780293   # how U12 built its pin

`--dev` lays a MAA dev commit's Stages/YW.json beside the tree (maa-dev-<commit>/), as
MAA's resource update did on the machine. Needs `gh` (GitHub API) and network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

UPSTREAM = Path(__file__).resolve().parents[1] / "upstream"
MAA = "MaaAssistantArknights/MaaAssistantArknights"
AM = "AUTO-MAS-Project/AUTO-MAS"
# The AUTO-MAS installed on the machine (U12: v5.7.0-beta.2, unchanged through 10-13).
AM_TAG, AM_C = "v5.7.0-beta.2", "ff285a39fa9de631b44e1cf0a64979772ab5bb58"
MAA_FILES = [
    "include/AsstCaller.h",
    "src/MaaCore/AsstCaller.cpp",
    "src/MaaCore/Assistant.cpp",
    "src/MaaCore/Task/Interface/FightTask.cpp",
    "src/MaaCore/Task/Fight/StageNavigationTask.cpp",
    "src/MaaCore/Task/Interface/InfrastTask.cpp",
    "src/MaaCore/Task/Interface/AwardTask.cpp",
    "src/MaaWpfGui/Configuration/Single/MaaTask/BaseTask.cs",
    "src/MaaWpfGui/Configuration/Single/MaaTask/InfrastTask.cs",
    "src/MaaWpfGui/Configuration/Single/MaaTask/AwardTask.cs",
    "src/MaaWpfGui/Models/AsstTasks/AsstInfrastTask.cs",
    "src/MaaWpfGui/Models/AsstTasks/AsstAwardTask.cs",
    "src/MaaWpfGui/ViewModels/UserControl/TaskQueue/InfrastSettingsUserControlModel.cs",
]
# How MAA prints a drop block (collector_maa._DROP_ITEM reads it): AsstProxy "StageDrops"
# and FormatNumber. Only in pins fetched by this tool; U12's beta.1 pin predates them.
MAA_PRINT_FILES = [
    "src/MaaWpfGui/Main/AsstProxy.cs",
    "src/MaaWpfGui/Extensions/NumberExtensions.cs",
]
AM_FILES = [
    "app/models/config.py",
    "app/models/ConfigBase.py",
    "app/task/MAA/base_preset.py",
    "app/task/MAA/AutoProxy.py",
    "app/task/MAA/manager.py",
    "app/task/game_update.py",
    "app/utils/constants.py",
    "app/api/scripts.py",
]
YW = "resource/tasks/Stages/YW.json"
# GitHub answered a raw file in under 2 s from this Mac (U1, measured 2026-10-13); a minute
# leaves room for a slow link without hanging forever.
TIMEOUT_S = 60


def gh(path: str):
    return json.loads(subprocess.check_output(["gh", "api", path], timeout=TIMEOUT_S))


def tag_commit(repo: str, tag: str) -> str:
    ref = gh(f"repos/{repo}/git/ref/tags/{tag}")["object"]
    while ref["type"] == "tag":                # annotated tag -> its object
        ref = gh(f"repos/{repo}/git/tags/{ref['sha']}")["object"]
    return ref["sha"]


def blobs(repo: str, commit: str) -> dict[str, str]:
    t = gh(f"repos/{repo}/git/trees/{commit}?recursive=1")
    if t["truncated"]:
        raise SystemExit(f"{repo}@{commit}: tree listing truncated")
    return {e["path"]: e["sha"] for e in t["tree"] if e["type"] == "blob"}


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--dev", action="append", default=[], help="MAA dev commit whose Stages/YW.json to add")
    ap.add_argument("--compare", help="an earlier MAA tag to list the differing pinned files against")
    ap.add_argument("--note", default="", help="one line on why this version is pinned")
    args = ap.parse_args()
    out = UPSTREAM / f"maa-{args.tag}"
    commit = tag_commit(MAA, args.tag)
    rows = []

    def put(local: str, repo: str, tag: str, at: str, path: str, tree: dict) -> None:
        with urllib.request.urlopen(f"https://raw.githubusercontent.com/{repo}/{at}/{path}",
                                    timeout=TIMEOUT_S) as r:
            data = r.read()
        if tree.get(path) != blob_sha(data):
            raise SystemExit(f"blob mismatch {repo}@{at} {path}")
        dst = out / local
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        rows.append((local, repo, tag, at, path, blob_sha(data), hashlib.sha256(data).hexdigest()))

    tree = blobs(MAA, commit)
    tasks = sorted(p for p in tree if p.startswith("resource/tasks/") and p.endswith(".json"))
    files = MAA_FILES + [p for p in MAA_PRINT_FILES if p in tree] + tasks
    for p in files:
        put(f"maa/{p}", MAA, args.tag, commit, p, tree)
    for short in args.dev:
        full = gh(f"repos/{MAA}/commits/{short}")["sha"]
        put(f"maa-dev-{short[:8]}/{YW}", MAA, "dev", full, YW, blobs(MAA, full))
    am = blobs(AM, AM_C)
    for p in AM_FILES:
        put(f"automas/{p}.txt", AM, AM_TAG, AM_C, p, am)

    with (out / "SOURCE.txt").open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Upstream files for the MAA static config checks, written by gamesim/maa/fetch_pin.py {args.tag}.\n")
        f.write("# Fetched verbatim by tag/commit; never hand-edited. Python sources carry a .txt\n")
        f.write("# suffix so the repo's linters do not treat them as our code.\n")
        if args.note:
            f.write(f"# {args.note}\n")
        f.write(f"# MAA {args.tag} = {commit}; AUTO-MAS {AM_TAG} = {AM_C}.\n")
        if args.compare:
            old_c = tag_commit(MAA, args.compare)
            old = blobs(MAA, old_c)
            differs = [p for p in files if old.get(p) != tree[p]]
            added = [p for p in tasks if p not in old]
            f.write(f"# Compared with MAA {args.compare} ({old_c}): {len(differs)} pinned file(s) differ"
                    + (": " + ", ".join(differs) if differs else "") + ".\n")
            f.write(f"# Task files present at {args.tag} and not at {args.compare}: "
                    + (", ".join(added) if added else "none") + ".\n")
        f.write("# local\trepo\ttag\tcommit\tupstream path\tgit blob sha1\tsha256\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    print(f"{out}: {len(rows)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
