#!/usr/bin/env python3
"""git push 之后清 jsDelivr 缓存，并**确认机器真的能拿到新代码**才算完。

为什么要有校验这一步（2026-08-21 凌晨实测发现）：

jsDelivr 的刷新**不是原子的**。清完缓存之后，`relay/*.py` 已经是新的，
`relay/manifest.json` 却还是旧的——两者互相对不上。而自更新的逻辑是
"照 manifest 的哈希去校验下载的文件"，于是每个文件都判校验失败，整套更新
整体放弃。日志里看起来像"下载失败"，实际是 CDN 内部不自洽。

判据必须和机器的实际取件逻辑一致（2026-08-21 傍晚修正）：机器不是只问一扇
门，它**问遍所有门取版本最大的那份清单**，然后逐个文件按哈希校验、不对就换
下一扇门。原先这个脚本只盯 fastly 一扇，于是 fastly 慢刷新的那几分钟里它报
失败，而机器其实早就能正常更新了——判据比现实严，等于制造假警报。

所以现在的判据是：所有门里最新的那份清单等于本地这一版，并且清单里的每个
文件**至少有一扇门**能给出哈希正确的内容。同时报出每扇门的状态，好知道会
不会全部落到最慢的 raw 上（那样 240 秒预算可能不够）。

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
# 和 relay/ark_relay/selfupdate.py 的 _alternates 保持同一组门、同一个顺序。
DOORS = [
    ("fastly", f"https://fastly.jsdelivr.net/gh/{GH}@main/"),
    ("cdn", f"https://cdn.jsdelivr.net/gh/{GH}@main/"),
    ("gcore", f"https://gcore.jsdelivr.net/gh/{GH}@main/"),
    ("raw", f"https://raw.githubusercontent.com/{GH}/main/"),
]
# raw 慢得多（实测中位数 38 秒），给它单独的超时。
TIMEOUTS = {"raw": 40}
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

    print("▶ 等各扇门凑齐（判据同机器：最新清单 = 本地版本，且每个文件至少一扇门给得对）")
    want_ver = local.get("version")

    def door_manifest(base: str, name: str):
        try:
            return json.loads(_get(base + "relay/manifest.json",
                                   TIMEOUTS.get(name, 20)))
        except Exception:  # noqa: BLE001
            return None

    for i in range(1, ATTEMPTS + 1):
        # 1) 清单：机器取所有门里版本最大的那份。
        seen = {}
        for name, base in DOORS:
            m = door_manifest(base, name)
            seen[name] = m.get("version") if m else None
        states = "  ".join(f"{n}={seen[n] or '?'}" for n, _ in DOORS)
        best = max((v for v in seen.values() if v), default=None)
        if best != want_ver:
            print(f"  [{i}/{ATTEMPTS}] 最新清单 v{best} ≠ 本地 v{want_ver}   {states}")
            time.sleep(GAP)
            continue

        # 2) 文件：每个文件只要有一扇门给得对就行，机器会自己换门。
        fresh = [n for n, _ in DOORS if seen[n] == want_ver]
        missing, only_raw = [], []
        for rel, sha in sorted(local.get("files", {}).items()):
            served_by = []
            for name, base in DOORS:
                if seen[name] != want_ver:
                    continue        # 这扇门的清单都是旧的，文件多半也旧
                try:
                    got = _get(base + f"relay/{rel}", TIMEOUTS.get(name, 20))
                except Exception:  # noqa: BLE001
                    continue
                if hashlib.sha1(got).hexdigest() == sha:  # noqa: S324
                    served_by.append(name)
            if not served_by:
                missing.append(rel)
            elif served_by == ["raw"]:
                only_raw.append(rel)

        if missing:
            print(f"  [{i}/{ATTEMPTS}] 还有 {len(missing)} 个文件没有任何门给得对"
                  f"，例如 {missing[0]}   {states}")
            time.sleep(GAP)
            continue

        print(f"✅ 通道可用（v{want_ver}）：清单齐了的门 = {'、'.join(fresh)}")
        if only_raw:
            print(f"⚠️ 其中 {len(only_raw)} 个文件只有 raw 给得出来（raw 实测中位数 38 秒）。")
            print("   机器能更新，但会慢；若离开机时间很近，宁可走 deploy-relay.sh。")
        return 0

    print("⚠️ 等待窗口内没凑齐。GitHub 上的代码是对的，但**自更新此刻拿不到**——")
    print("   要立刻生效请走：ARK_HOST=<游戏机IP> scripts/mac/deploy-relay.sh")
    return 1


if __name__ == "__main__":
    sys.exit(main())
