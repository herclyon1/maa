#!/usr/bin/env python3
"""裁剪 / 缩放 wingui.sh 取回的整屏截图，并把图上的像素坐标换算回游戏坐标。

整屏是 3840x1243（双显示器拼出来的），直接看会被缩成一条、字全糊。
游戏窗口在左上角 0,0-1920,1080，裁出来放大才认得出界面。

用法一 —— 裁图：
    shotcrop.py <源图> <目标图> [x0,y0,x1,y1] [宽度]
    默认裁 0,0,1920,1080，缩到 1400 宽。

用法二 —— 把你在裁出来的图上量到的坐标换算成 wingui.sh click 要的坐标：
    shotcrop.py --map <x0,y0,x1,y1> <宽度> <图上x> <图上y>

    换算是必须的。你在一张「裁过又缩过」的图上量到的 (px,py)
    不等于屏幕坐标，直接拿去 click 会点偏到别的控件上。
"""
import sys
from PIL import Image


def main():
    if sys.argv[1:2] == ["--map"]:
        box = [int(v) for v in sys.argv[2].split(",")]
        wide = int(sys.argv[3])
        px, py = float(sys.argv[4]), float(sys.argv[5])
        scale = (box[2] - box[0]) / wide          # 裁剪保持了长宽比，横竖同一个系数
        print(f"{round(box[0] + px * scale)} {round(box[1] + py * scale)}")
        return

    src, dst = sys.argv[1], sys.argv[2]
    box = [int(v) for v in sys.argv[3].split(",")] if len(sys.argv) > 3 else [0, 0, 1920, 1080]
    wide = int(sys.argv[4]) if len(sys.argv) > 4 else 1400

    im = Image.open(src).crop(tuple(box))
    w, h = im.size
    tall = max(1, round(h * wide / w))
    im.resize((wide, tall)).save(dst)
    print(f"{src} {box} -> {dst} {wide}x{tall}")
    print(f"换算坐标: shotcrop.py --map {','.join(map(str, box))} {wide} <图上x> <图上y>")


main()
