#!/usr/bin/env python3
"""git push 之后清 jsDelivr 的缓存，让第二扇门立刻拿到新内容。

jsDelivr 对 @main 这类分支引用缓存约 12 小时。平时无所谓——机器先试
raw.githubusercontent，那边永远是新鲜的；但 raw 整晚黑掉的时候（2026-08-17、
2026-08-20 都发生过）机器只剩 jsDelivr 这扇门，不清缓存，一条早上推的暂停
指令要到半夜才生效——8/17 那晚的事故就是这么来的。

用法：改完 relay/ 或 queue/ 并 git push 之后跑一次：

    python3 scripts/mac/purge-cdn.py

清单 = queue/ 下的两个 JSON + relay/manifest.json + manifest 里列出的每个
文件。清失败只是回到「等缓存过期」，不影响 raw 那扇门，所以任何失败都不
中断，只打印。
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = "https://purge.jsdelivr.net/gh/herclyon1/maa@main/"

paths = ["queue/config.json", "queue/watchdog.json", "relay/manifest.json"]
try:
    manifest = json.loads((REPO / "relay" / "manifest.json").read_text(encoding="utf-8"))
    paths += [f"relay/{rel}" for rel in manifest.get("files", {})]
except (OSError, json.JSONDecodeError) as exc:
    print(f"读不到本地 manifest（{exc}），只清固定清单")

for p in paths:
    try:
        with urllib.request.urlopen(BASE + p, timeout=20) as resp:  # noqa: S310
            ok = json.loads(resp.read()).get("status") in ("finished", "pending")
        print(("✓ " if ok else "? ") + p)
    except Exception as exc:  # noqa: BLE001 - purge 失败不值得中断
        print(f"✗ {p}: {exc}")
