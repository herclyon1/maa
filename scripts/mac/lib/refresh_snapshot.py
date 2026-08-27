#!/usr/bin/env python3
"""重新拉一份森空岛快照（角色练度／库存／材料表）。在 Mac 上直接跑，不碰游戏机。

    python3 scripts/mac/lib/refresh_snapshot.py

token 读 ~/.config/ark/.env。三份快照落到会话临时目录，供 snapshot.fresh() 用。
"""
from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "relay"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ark_relay import skland          # noqa: E402
from snapshot import FILES, SNAP_DIR  # noqa: E402

ENV = Path.home() / ".config/ark/.env"


def _retry(fn, tries=4, wait=2):
    """东京 → 上海跨境链路会瞬时抖动，首次 TLS 握手超时是常态。"""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(wait)
    raise last


def refresh(quiet: bool = False) -> None:
    """拉三份快照。**只在用户说「刷新」时调用**——不许挂在读取路径上自动跑。"""
    tok = next(l.split("=", 1)[1].strip()
               for l in ENV.read_text(encoding="utf-8").splitlines()
               if l.startswith("SKLAND_TOKEN="))
    cred = _retry(lambda: skland.refresh(skland.login(tok)))
    rid, sid = skland.endfield_role(cred)

    def pull(path, q=""):
        url = f"https://zonai.skland.com{path}" + (f"?{q}" if q else "")
        raw = _retry(lambda: urllib.request.urlopen(
            urllib.request.Request(url, headers=skland.sign_headers(cred, url)),
            timeout=30).read())
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        d = json.loads(raw.decode())
        if d.get("code") not in (0, None):
            raise RuntimeError(f"{path} → {d.get('code')} {d.get('message')}")
        return d["data"]

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    for kind, path, q in (
        ("card", "/api/v1/game/endfield/card/detail", f"roleId={rid}&serverId={sid}"),
        ("inv", "/web/v1/game/endfield/calculate/user-game-data",
         f"roleId={rid}&serverId={sid}"),
        ("mat", "/web/v1/game/endfield/calculate/material-list", ""),
    ):
        data = pull(path, q)
        (SNAP_DIR / FILES[kind]).write_text(json.dumps(data, ensure_ascii=False),
                                            encoding="utf-8")
        if not quiet:
            print(f"  ✅ {kind:<5} {FILES[kind]}")
    print(f"🔄 快照已刷新 {time.strftime('%H:%M:%S')}"
          f"　（官方数据本身仍有约 30 分钟同步延迟）")


def main() -> int:
    refresh()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
