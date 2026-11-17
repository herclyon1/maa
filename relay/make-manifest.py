#!/usr/bin/env python3
"""Regenerate manifest.json from the working tree."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_extra = [f for f in ("RELEASE-NOTES.md",) if (HERE / f).exists()]
_tree = [p.relative_to(HERE).as_posix() for p in sorted((HERE / "ark_relay").rglob("*"))
         if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".txt")]
files = sorted(_tree + [p.name for p in HERE.glob("*.py") if p.name != "make-manifest.py"] + _extra)
# Monotonic version. selfupdate refuses any manifest older than the one the
# machine has applied: a CDN can hold a whole stale snapshot (old manifest plus
# matching old files), which is internally consistent and would silently roll
# the machine back without this gate.
version = int(datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
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
