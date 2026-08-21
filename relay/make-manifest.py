#!/usr/bin/env python3
"""Regenerate manifest.json from the working tree.

Run this after changing any relay file, before pushing. The game machine's
selfupdate trusts the pushed manifest completely, and a stale one does not
merely miss an update - at the next boot it actively reverts the machine to
whatever the repo last said. A brand-new file must also be deployed by hand
once: selfupdate refuses to create files that do not already exist there.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
files = sorted(
    [p.relative_to(HERE).as_posix() for p in (HERE / "ark_relay").glob("*.py")]
    + ["run.py", "service.py"])
# Monotonic version. selfupdate refuses any manifest older than the one the
# machine has applied: a CDN can hold a whole stale snapshot (old manifest plus
# matching old files), which is internally consistent and would silently roll
# the machine back without this gate.
manifest = {"version": int(datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")),
            "files": {
    f: hashlib.sha1((HERE / f).read_bytes()).hexdigest()  # noqa: S324 - change detection
    for f in files}}
(HERE / "manifest.json").write_text(
    json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"manifest.json 已重建：{len(files)} 个文件")
