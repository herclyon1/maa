#!/usr/bin/env python3
"""git push 之后清 jsDelivr 缓存，并**确认真的刷新了**才算完。

为什么要有校验这一步（2026-08-21 凌晨实测发现）：

jsDelivr 的刷新**不是原子的**。清完缓存之后，`relay/*.py` 已经是新的，
`relay/manifest.json` 却还是旧的——两者互相对不上。而自更新的逻辑是
"照 manifest 的哈希去校验下载的文件"，于是每个文件都判校验失败，整套更新
整体放弃。日志里看起来像"下载失败"，实际是 CDN 内部不自洽。

后果是：只 push 不校验的话，自更新会有一段**长度不可知**的失效窗口，而且
静默。所以这个脚本清完之后会一直等到 CDN 的 manifest 与本地一致、且每个
文件的哈希都对得上，才报成功。等不到就明确报出来，让人知道此刻只能走
手动部署（scripts/mac/deploy-relay.sh）。

    python3 scripts/mac/purge-cdn.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GH = "herclyon1/maa"
PURGE = f"https://purge.jsdelivr.net/gh/{GH}@main/"
# 校验走实测最快的那扇门（见 relay/ark_relay/selfupdate.py 的 _alternates）。
READ = f"https://fastly.jsdelivr.net/gh/{GH}@main/"
ATTEMPTS, GAP = 8, 20


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ark-purge"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def main() -> int:
    local_path = REPO / "relay" / "manifest.json"
    try:
        local = json.loads(local_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"✗ 读不到本地 manifest（{exc}），先跑 relay/make-manifest.py")
        return 1

    paths = ["queue/config.json", "queue/watchdog.json", "relay/manifest.json"]
    paths += [f"relay/{rel}" for rel in local.get("files", {})]

    print(f"▶ 清缓存：{len(paths)} 个文件")
    for p in paths:
        try:
            ok = json.loads(_get(PURGE + p)).get("status") in ("finished", "pending")
            print(("  ✓ " if ok else "  ? ") + p)
        except Exception as exc:  # noqa: BLE001 - 清不动不致命，后面校验说了算
            print(f"  ✗ {p}: {exc}")

    print("▶ 等 CDN 变得自洽（manifest 与文件互相对得上，且是本地这一版）")
    want_ver = local.get("version")
    for i in range(1, ATTEMPTS + 1):
        try:
            remote = json.loads(_get(READ + "relay/manifest.json"))
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{ATTEMPTS}] 取 CDN manifest 失败：{exc}")
            time.sleep(GAP)
            continue
        if want_ver and remote.get("version") != want_ver:
            print(f"  [{i}/{ATTEMPTS}] CDN manifest 还是旧的"
                  f"（{remote.get('version')} ≠ 本地 {want_ver}）")
            time.sleep(GAP)
            continue
        bad = []
        for rel, sha in sorted(remote.get("files", {}).items()):
            try:
                if hashlib.sha1(_get(READ + f"relay/{rel}")).hexdigest() != sha:  # noqa: S324
                    bad.append(rel)
            except Exception:  # noqa: BLE001
                bad.append(rel)
        if not bad:
            print(f"✅ CDN 已同步（v{remote.get('version')}），自更新通道可用")
            return 0
        print(f"  [{i}/{ATTEMPTS}] 还有 {len(bad)} 个文件没刷新，例如 {bad[0]}")
        time.sleep(GAP)

    print("⚠️ CDN 在等待窗口内没同步完。GitHub 上的代码是对的，但**自更新此刻拿不到**——")
    print("   要立刻生效请走：ARK_HOST=<游戏机IP> scripts/mac/deploy-relay.sh")
    return 1


if __name__ == "__main__":
    sys.exit(main())
