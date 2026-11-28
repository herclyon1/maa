#!/opt/homebrew/bin/python3
"""Print the echo-set badge templates the OK-WW overlay matches pickup toasts against.

    .venv-relaytest/bin/python scripts/mac/echo-set-badges.py [ark-remote checkout]

The 11 sonata-set icons of ark-remote (Sources/ArkRemote/Resources/Module.xcassets/
echo-set-N.imageset, 76x76 PNGs from the Kuro wiki; names from WuwaPage.setIcons), each cut
12% at every edge (the badge's ring), laid on black and scaled to 15x15 RGB, base64 of the
raw bytes. The output is pasted into relay/ark_relay/features/okww_files/ark_overrides.tasks.py
as ECHO_SET_BADGES: on the machine the overlay is one file, so the templates travel inside it.

Checked 2026-11-20 against nine real 千傀重楼 toasts (relay/tests/fixtures/echo_badges): each
scored 0.89-0.91 on its own set and at most 0.54 on any other.
"""
import base64
import sys
from pathlib import Path

from PIL import Image

NAMES = ("长路启航之星", "斑驳粉饰之沫", "听唤语义之愿", "雪落无声之愿", "剪心辑梦之影", "羽落空尘之歌",
         "清邪荡煞之心", "冥途夜行之灯", "衔梦照世之心", "镜影流电之瞬", "茜染怀想之花")   # echo-set-1..11
SIZE = 15


def template(png: Path) -> bytes:
    im = Image.open(png).convert("RGBA")
    w, h = im.size
    m = round(w * 0.12)
    im = im.crop((m, m, w - m, h - m))
    base = Image.new("RGBA", im.size, (0, 0, 0, 255))
    base.alpha_composite(im)
    return base.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).tobytes()


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Claude" / "ark-remote")
    assets = root / "Sources" / "ArkRemote" / "Resources" / "Module.xcassets"
    print("ECHO_SET_BADGES = {")
    for i, name in enumerate(NAMES, 1):
        raw = template(assets / f"echo-set-{i}.imageset" / f"echo-set-{i}.png")
        print(f'    "{name}": "{base64.b64encode(raw).decode()}",')
    print("}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
