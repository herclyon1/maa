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
# RELEASE-NOTES.md must be pushed along with the rest: the update announcement
# reads it out, and what it reads is "which problems got fixed". On 2026-08-26, when
# this feature was first added, it was left out of the manifest; the deploy reported
# "success" while the file was simply not on the machine, and the announcement
# silently fell back to listing file names — the feature was not live at all. This is
# exactly what "pushed != in effect" means.
_extra = [f for f in ("RELEASE-NOTES.md",) if (HERE / f).exists()]
# okww_files holds the whole-source patches for OK-WW (full-file replacement plus a
# hash guard). They are not covered by the ark_relay/*.py glob, and leaving them out
# makes the patch module on the machine report a missing reference file — another
# "deploy succeeded but the feature is not live".
_nested = [p.relative_to(HERE).as_posix()
           for p in sorted((HERE / "ark_relay" / "okww_files").glob("*.py"))
           # Pristine upstream fragments are kept as .txt so the linters do not try
           # to compile a method body as a module. They still have to ship: on
           # 2026-09-09 one was left out and the service crashed on import.
           + sorted((HERE / "ark_relay" / "okww_files").glob("*.txt"))
           + sorted((HERE / "ark_relay" / "okww_patches").glob("*.py"))]
files = sorted(
    [p.relative_to(HERE).as_posix() for p in (HERE / "ark_relay").glob("*.py")]
    # 顶层的 .py 一律收（不再手写名单）。2026-09-08 栽过：`boot_stages.py` 从
    # service.py 拆出来之后没进这份手写名单，于是**没被推上机器**——而逐文件哈希
    # 核对只检查「清单里有的文件」，清单里没有它，那道闸门一路绿灯，
    # 服务却因为 ModuleNotFoundError 起不来，通知链路直接断了。
    # 手写名单和「目录里实际有什么」迟早会分家，所以改成扫目录。
    + _nested + [p.name for p in HERE.glob("*.py")
                 if p.name != "make-manifest.py"] + _extra)
# Monotonic version. selfupdate refuses any manifest older than the one the
# machine has applied: a CDN can hold a whole stale snapshot (old manifest plus
# matching old files), which is internally consistent and would silently roll
# the machine back without this gate.
manifest = {"version": int(datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")),
            "files": {
    f: hashlib.sha1((HERE / f).read_bytes()).hexdigest()
    for f in files}}
(HERE / "manifest.json").write_text(
    json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"manifest.json 已重建：{len(files)} 个文件")
