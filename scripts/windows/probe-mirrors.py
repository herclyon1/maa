#!/usr/bin/env python3
"""在游戏机上实测各种「中国大陆怎么拿到 GitHub 内容」的方案，用数据选路。

背景：这台机器 github.com / api.github.com 在 TCP 层就不通，
raw.githubusercontent 实测 2/8、平均 38 秒，jsDelivr 快但缓存不是原子刷新
（推送后有一段时间给的是旧副本）。所以「更新通道」一直是这套系统最脆的一环。

用法（在游戏机上跑，不联动任何服务）：

    python probe-mirrors.py

每个候选打 6 次，报成功率、耗时、以及**内容是不是最新的**——最后一项才是
关键：一个又快又稳但永远给旧内容的镜像，比不通还危险。
"""
from __future__ import annotations

import json
import time
import urllib.request

OWNER, REPO, BRANCH = "herclyon1", "maa", "main"
FILE = "relay/manifest.json"
N = 6
TIMEOUT = 15

CANDIDATES = [
    # 官方直连（基准）
    ("raw.githubusercontent", f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{FILE}"),
    # jsDelivr 各边缘
    ("jsdelivr-fastly", f"https://fastly.jsdelivr.net/gh/{OWNER}/{REPO}@{BRANCH}/{FILE}"),
    ("jsdelivr-cdn", f"https://cdn.jsdelivr.net/gh/{OWNER}/{REPO}@{BRANCH}/{FILE}"),
    ("jsdelivr-gcore", f"https://gcore.jsdelivr.net/gh/{OWNER}/{REPO}@{BRANCH}/{FILE}"),
    # 国内 Git 托管的镜像仓库（需要先把仓库镜像过去，见 docs）
    ("gitcode", f"https://raw.gitcode.com/{OWNER}/{REPO}/raw/{BRANCH}/{FILE}"),
    ("gitee", f"https://gitee.com/{OWNER}/{REPO}/raw/{BRANCH}/{FILE}"),
    # 公共 GitHub 反代（可用性起伏很大，实测为准）
    ("ghproxy-ghfast", f"https://ghfast.top/https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{FILE}"),
    ("ghproxy-net", f"https://gh-proxy.com/https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{FILE}"),
    ("moeyy", f"https://github.moeyy.xyz/https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{FILE}"),
]


def probe(url: str) -> tuple[int, list[int], dict, int | None]:
    ok, ms, errs, version = 0, [], {}, None
    for _ in range(N):
        t = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ark-probe"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310
                body = resp.read()
            data = json.loads(body)
            version = data.get("version")
            ok += 1
            ms.append(int((time.time() - t) * 1000))
        except Exception as exc:  # noqa: BLE001 - 探测就是要吃掉所有异常
            k = type(exc).__name__
            errs[k] = errs.get(k, 0) + 1
        time.sleep(0.5)
    return ok, ms, errs, version


def main() -> None:
    print(f"每个候选 {N} 次，超时 {TIMEOUT}s\n")
    fresh = None
    rows = []
    for name, url in CANDIDATES:
        ok, ms, errs, ver = probe(url)
        rows.append((name, ok, ms, errs, ver))
        if name == "raw.githubusercontent" and ver:
            fresh = ver          # 官方直连的内容按定义就是最新的
        avg = int(sum(ms) / len(ms)) if ms else 0
        print(f"{name:24} {ok}/{N}  平均{avg:6d}ms  版本={ver}  {errs or ''}")

    print("\n结论：")
    for name, ok, ms, _errs, ver in rows:
        if ok == 0:
            continue
        avg = int(sum(ms) / len(ms))
        stale = (fresh is not None and ver is not None and ver != fresh)
        tag = "内容陈旧 ⚠️" if stale else "内容最新 ✅"
        print(f"  {name:24} 可用 {ok}/{N}，{avg}ms，{tag}")
    if fresh is None:
        print("  （raw 一次都没通，无法判定谁的内容是最新的）")


if __name__ == "__main__":
    main()
