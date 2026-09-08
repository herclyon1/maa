#!/usr/bin/env python3
"""Are the desktop stream launchers built from the current parameters?

The parameters live in one place, `scripts/mac/lib/moonlight-params.sh`, but the
two desktop apps are **compiled snapshots** of them: clang bakes the values into
each launcher's argv. Change a parameter and the command line (stream-ins.sh)
picks it up immediately while the icons the user double-clicks keep the old value.
Both still launch, neither complains, and nothing in the repo notices - the claim
in MAC-CHANGES.md §3 that the two agree had no check behind it.

So: read the parameters, then look for them inside each built binary.

    python3 scripts/mac/lib/stream_apps_current.py

Missing apps are not a failure. This repo is checked out on more than one machine
and only this Mac has them; there is nothing to compare there.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PARAMS = HERE / "moonlight-params.sh"
DESK = pathlib.Path.home() / "Desktop"


def params() -> dict[str, str]:
    text = PARAMS.read_text(encoding="utf-8")
    out = {}
    for key in ("MOON_RES", "MOON_BITRATE", "MOON_CODEC"):
        m = re.search(rf"^{key}=(\S+)", text, re.M)
        if m:
            out[key] = m.group(1).strip("'\"")
    return out


def built() -> list[pathlib.Path]:
    return sorted(p for p in DESK.glob("*.app")
                  if (p / "Contents" / "MacOS" / "launcher").is_file()
                  and "串流" in p.name)


def main() -> int:
    want = params()
    if not want:
        print("✗ 读不出串流参数，moonlight-params.sh 的写法变了？")
        return 1
    apps = built()
    if not apps:
        print("· 这台机器上没有串流启动器，跳过")
        return 0
    bad = 0
    checked = 0
    for app in apps:
        exe = app / "Contents" / "MacOS" / "launcher"
        blob = subprocess.run(["strings", str(exe)], capture_output=True,
                              text=True, errors="replace").stdout
        # 「强制关闭串流」 is a launcher too but it does not stream anything, so it
        # carries no parameters to compare. Only the ones that pass --bitrate do.
        if "--bitrate" not in blob:
            continue
        checked += 1
        # The codec and bitrate differ per app on purpose (one is the HEVC 4:4:4
        # variant), so only the values every launcher must share are compared.
        missing = [k for k in ("MOON_RES",) if want[k] not in blob]
        if missing:
            bad += 1
            print(f"✗ {app.name}: 里面没有 {', '.join(want[k] for k in missing)}"
                  f" —— 参数改过但没重跑 scripts/mac/make-stream-apps.sh")
        else:
            print(f"✓ {app.name}: 分辨率对得上（{want['MOON_RES']}）")
    if not checked:
        print("· 桌面上没有会传参数的串流图标，跳过")
    if bad:
        print("桌面图标是参数的编译快照，改完参数必须重跑 make-stream-apps.sh，"
              "否则命令行已生效、双击的图标还是旧值，两边都不报错。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
