#!/usr/bin/env python3
"""把 wingui.sh 取回的整屏截图裁成游戏窗口那块，再缩到能看清字的尺寸。

整屏是 3840x1243（双显示器拼出来的），直接看会被缩成一条，字全糊。
游戏在左上角 1920x1080，裁出来放大才认得出界面。
"""
import sys
from PIL import Image

src = sys.argv[1]
dst = sys.argv[2]
box = [int(v) for v in sys.argv[3].split(",")] if len(sys.argv) > 3 else [0, 0, 1920, 1080]
wide = int(sys.argv[4]) if len(sys.argv) > 4 else 1400

im = Image.open(src).crop(tuple(box))
w, h = im.size
im.resize((wide, max(1, round(h * wide / w)))).save(dst)
print(f"{src} {box} -> {dst} {wide}x{round(h * wide / w)}")
