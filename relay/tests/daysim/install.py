#!/usr/bin/env python3
"""daysim: the game programs' own files the relay reads, which a day's pull does not carry.

The pull (scripts/mac/pull-day.sh) brings the relay's state, the run history, the game
logs and AUTO-MAS's config/. The relay also reads files of the installed programs, and
without them a replayed day is full of WARNINGs the machine never logged (the real
relay.log of 10-06, 10-12 and 10-13 has none of 「母本配置文件不在」, 「找不到 app.asar」,
「读不到 MaaEnd 的 interface.json」, 「找不到 OK-WW 母本 DailyTask.json」 or 「MAA 的关卡资料读不了」):

* AUTO-MAS's master copies, `<automas>/data/<script uid>/Default/ConfigFile/`
  (config.master_config_dir): OK-WW's task JSONs and MaaEnd's mxu-MaaEnd.json;
* OK-WW: `ok-ww.exe` (preupdate_okww checks it exists), `data/apps/ok-ww/app.json`
  (its version), `working/configs/` (Basic Options, the script-side copies);
* MaaEnd: interface.json, its imported task files, locales/interface/zh_cn.json,
  resource/pipeline/nodes.json (the stamina-booster node), config/mxu-MaaEnd.json;
* MAA: resource/tasks/** (stagegate: does the stage's navigation task exist);
* AUTO-MAS: resources/app.asar (plan._asar_value_labels; see `asar_stub`).

Sources (all read-only copies already on this Mac; nothing is fetched here):

* `u0`: gamesim U0's read of the game PC on 2026-10-13 17:06 +09:00 (winps.sh
  Get-Content / scp --get, nothing started on the machine): `verbatim/` byte copies,
  `redacted/` the same with secrets masked (its masked.tsv). Its manifest.tsv gives
  each file's machine mtime. MaaEnd there is v2.33.0-beta.3, OK-WW v3.7.4.
* `maa-pin`: gamesim U12's upstream copy of MAA v6.19.0-beta.1 resource/tasks
  (commit 54d20df3, the machine ran beta.2), plus Stages/YW.json from MAA dev
  cc780293 (absent from beta.1; the owner had it put on the machine 10-10 12:57,
  docs/MAA-EVENTS-AND-SSS.md; the record's stage gate says 「YW-4 —— 走得到」).

The copies live in the corpus (`~/Claude/daysim-corpus/_install/`, outside the repo:
nodes.json alone is 3.8 MB); `install.json` next to this file lists every one with
its sha256, so a replay refuses a changed copy. They are as of 10-13: a day before
that gets the 10-13 install (the versions differ: MaaEnd v2.31 on 10-06, v2.32 on
10-12), marked in each boot's sim notes. Rebuild:

    python3.14 -I install.py build --u0 <gamesim/u0> --maa-pin <u12/pin/maa> --yw <YW.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "install.json"
# The corpus root; DAYSIM_CORPUS points elsewhere (CI unpacks the light packs there, pack.py).
CORPUS_ROOT = Path(os.environ.get("DAYSIM_CORPUS") or Path.home() / "Claude" / "daysim-corpus")
ROOT = CORPUS_ROOT / "_install"
BJ = timezone(timedelta(hours=8))

# u0 files left out: the pyappify launcher script and requirements.txt (the relay
# reads neither). MAA's gui.new.json is u0's redacted machine copy (10-11 08:46:15):
# u0's versions.json notes daydata's copy differs from the machine's.
U0_SKIP = ("D/ark/okww/data/apps/ok-ww/.pyappify-shortcut.py",
           "D/ark/okww/data/apps/ok-ww/working/requirements.txt")
OKWW_CONFIGS = "D/ark/okww/data/apps/ok-ww/working/configs/"
MAAEND_CONFIG = "D/ark/maaend/config/mxu-MaaEnd.json"
# ScriptConfig.json's instance types whose master copy lives under data/<uid>/.
MASTER_OF = {"OkwwConfig": "okww", "MaaEndConfig": "maaend", "MaaConfig": "maa"}
# MAA's master is its gui.new.json (mastercfg_maa.maa_master); the day's pull carries
# MAA's own copy, which AUTO-MAS copies the master over before each run.
MAA_GUI = "D/ark/maa/config/gui.new.json"
# Files the relay only checks for: echofarm._launch refuses to start OK-WW's farm
# without OK-WW's pythonw.exe and main.py (the farm itself is OK-WW's, replayed from
# its log); ok-ww.exe for the pre-update (preupdate_okww.run_okww).
PLACEHOLDERS = ("D/ark/okww/ok-ww.exe", "D/ark/okww/data/apps/ok-ww/python/pythonw.exe",
                "D/ark/okww/data/apps/ok-ww/working/main.py")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ build (one-off)

def build(u0: Path, maa_pin: Path, yw: Path) -> dict:
    mtimes = {}
    for line in (u0 / "manifest.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        f = line.split("\t")
        if len(f) > 5 and f[5]:
            mtimes[f[5].split("/", 1)[1]] = f[2]          # local_path minus verbatim/|redacted/
    files = []

    def add(src: Path, rel: str, mtime: str, how: str) -> None:
        dst = ROOT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        files.append({"path": rel, "sha256": sha256(dst), "len": dst.stat().st_size, "mtime": mtime, "src": how})

    for kind in ("verbatim", "redacted"):
        for src in sorted((u0 / kind).rglob("*")):
            rel = src.relative_to(u0 / kind).as_posix()
            if src.is_file() and rel not in U0_SKIP:
                add(src, rel, mtimes.get(rel, ""), f"u0 {kind}")
    for src in sorted((maa_pin / "resource" / "tasks").rglob("*.json")):
        rel = "D/ark/maa/" + src.relative_to(maa_pin).as_posix()
        add(src, rel, "", "maa-pin v6.19.0-beta.1 54d20df3")
    add(yw, "D/ark/maa/resource/tasks/Stages/YW.json", "", "maa-pin dev cc780293")
    doc = {"about": "daysim install copies; see install.py", "as_of": "2026-10-13T17:06:37+09:00",
           "files": sorted(files, key=lambda x: x["path"])}
    MANIFEST.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


# ------------------------------------------------------------------ plant (every day)

def _stamp(mtime: str, t0: float) -> float:
    """A copy's mtime on the sim tree: its machine mtime, but never after the day
    starts (a 10-13 copy planted into 10-06 must not look written in the future)."""
    try:
        t = datetime.fromisoformat(mtime).replace(tzinfo=BJ).timestamp() if mtime else t0 - 1
    except ValueError:
        t = t0 - 1
    return min(t, t0 - 1)


def script_uids(tree: Path, automas_rel: str) -> dict:
    """{"okww": uid, "maaend": uid} from the day's ScriptConfig.json instances."""
    try:
        doc = json.loads((tree / automas_rel / "config" / "ScriptConfig.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return {MASTER_OF[i["type"]]: i["uid"] for i in doc.get("instances") or []
            if isinstance(i, dict) and i.get("type") in MASTER_OF and i.get("uid")}


def plant(tree: Path, t0: float, *, automas_rel: str, clone, nests: str = "",
          root: Path = ROOT, man: "dict | None" = None) -> list[str]:
    """Put every install copy into the sim tree (where the seed has no file of its own)
    and the master copies under data/<uid>/. Returns what could not be planted."""
    missing = []
    man = man if man is not None else load()
    uids = script_uids(tree, automas_rel)
    for f in man["files"]:
        src = root / f["path"]
        if not src.is_file() or src.stat().st_size != f["len"]:
            missing.append(f["path"])
            continue
        targets = [tree / f["path"]]
        if f["path"].startswith(OKWW_CONFIGS) and "okww" in uids:
            targets.append(tree / automas_rel / "data" / uids["okww"] / "Default" / "ConfigFile"
                           / f["path"][len(OKWW_CONFIGS):])
        if f["path"] == MAAEND_CONFIG and "maaend" in uids:
            targets.append(tree / automas_rel / "data" / uids["maaend"] / "Default" / "ConfigFile" / "mxu-MaaEnd.json")
        t = _stamp(f["mtime"], t0)
        for dst in targets:
            if dst.exists():
                continue
            clone(src, dst)
            os.utime(dst, (t, t))
    if nests and "okww" in uids:
        set_nests(tree / automas_rel / "data" / uids["okww"] / "Default" / "ConfigFile" / "NightmareNestTask.json",
                  nests, t0)
    gui = tree / MAA_GUI
    if gui.is_file() and "maa" in uids:
        dst = tree / automas_rel / "data" / uids["maa"] / "Default" / "ConfigFile" / "gui.new.json"
        if not dst.exists():
            clone(gui, dst)
            os.utime(dst, (gui.stat().st_mtime,) * 2)
    for rel in PLACEHOLDERS:
        f = tree / rel
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"")
            os.utime(f, (t0 - 1, t0 - 1))
    return missing


def set_nests(f: Path, nests: str, t0: float) -> None:
    """The master's 「Only Farm These Nests」 (mastercfg_okww.OKWW_READONLY). OK-WW drops a
    key it does not declare when it saves its own copy, so the script-side copy u0 read
    has none; the master's value is the one the overrides log as 「设置来自母本」."""
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    doc["Only Farm These Nests"] = nests
    f.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.utime(f, (t0 - 1, t0 - 1))


def asar_stub(tree: Path, automas_rel: str, state_rel: str) -> str:
    """resources/app.asar as the relay last saw it: plan._asar_value_labels caches the
    labels it read in state/asar-labels.json under the stamp "<size>-<int mtime>", and
    a file with that size and mtime is a cache hit, so the bundle (71 MB) is never read.
    A sparse file of that size costs no disk. Returns the stamp used, "" when the
    day's state has no cache."""
    try:
        stamp = json.loads((tree / state_rel / "asar-labels.json").read_text(encoding="utf-8"))["stamp"]
        size, mtime = (int(x) for x in str(stamp).split("-"))
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    f = tree / automas_rel / "resources" / "app.asar"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "wb") as fh:
        fh.truncate(size)
    os.utime(f, (mtime, mtime))
    return stamp


def check(root: Path = ROOT) -> list[str]:
    """Copies whose sha256 differs from install.json (a full read)."""
    return [f["path"] for f in load()["files"]
            if not (root / f["path"]).is_file() or sha256(root / f["path"]) != f["sha256"]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--u0", required=True)
    b.add_argument("--maa-pin", required=True)
    b.add_argument("--yw", required=True)
    sub.add_parser("check")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        doc = build(Path(a.u0), Path(a.maa_pin), Path(a.yw))
        print(f"{len(doc['files'])} files under {ROOT}")
        return 0
    bad = check()
    print("\n".join(bad) or "all copies match install.json")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
