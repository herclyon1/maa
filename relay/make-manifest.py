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
# RELEASE-NOTES.md 必须一起推：更新播报会念它，念的是「修好了什么毛病」。
# 2026-08-26 第一次加这个功能时忘了加进清单，部署报「成功」而机器上根本没有
# 这个文件，播报静静退回列文件名——功能等于没上。这就是「推上去 ≠ 生效」。
_extra = [f for f in ("RELEASE-NOTES.md",) if (HERE / f).exists()]
# okww_files 里是打给 OK-WW 的整份源码补丁（整文件替换 + 哈希守卫）。
# 它们不在 ark_relay/*.py 的通配范围内，漏掉的话补丁模块在机器上会
# 报「缺少参照文件」——又是一次「部署成功但功能没上」。
_nested = [p.relative_to(HERE).as_posix()
           for p in sorted((HERE / "ark_relay" / "okww_files").glob("*.py"))]
files = sorted(
    [p.relative_to(HERE).as_posix() for p in (HERE / "ark_relay").glob("*.py")]
    + _nested + ["run.py", "service.py"] + _extra)
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
