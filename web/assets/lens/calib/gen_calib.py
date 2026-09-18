"""WebKit feDisplacementMap calibration (2026-09-19): constant / ramp / step maps on isolated marks, so the displacement the
engine actually applies can be read off the render (check_calib.py). Writes calib-*.png (440×88, the same encoding as the lens
maps: byte = 128 + u·255/40, S 40) and webkit-displacement.html. Render with wksnap, then check_calib.py <png>."""
import sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gen_lens_maps import write_png

W, H, S = 440, 88, 40.0
XS = (np.arange(W) + 0.5) / 2.0
CONST = [-0.25, -0.5, -0.75, -1, -1.25, -1.5, -1.75, -2, -2.5, -3, -3.75, -4, -5.25, -6, -8, -12, 1, 1.25, 2.5, 4, 8, 12]
YCONST = [-4, -1, 1, 4]

def write_map(name, ux, uy):
    ux = np.broadcast_to(np.asarray(ux, float), (W,)); uy = np.broadcast_to(np.asarray(uy, float), (W,))
    r = np.clip(np.rint(128 + ux * 255 / S), 0, 255).astype(np.uint8); g = np.clip(np.rint(128 + uy * 255 / S), 0, 255).astype(np.uint8)
    row = bytes(np.stack([r, g, np.full(W, 255, np.uint8), np.full(W, 255, np.uint8)], axis=1).reshape(-1))
    write_png(name, W, H, [row] * H)

def main():
    here = os.path.dirname(os.path.abspath(__file__)); os.chdir(here)
    ids = []
    for v in CONST: write_map(f"calib-x{v:g}.png", v, 0.0); ids.append(f"x{v:g}")
    for v in YCONST: write_map(f"calib-y{v:g}.png", 0.0, v); ids.append(f"y{v:g}")
    write_map("calib-ramp.png", np.clip(-(XS - 200) * 0.5, -10, 0), 0.0); ids.append("ramp")      # 0 → −10 over box x 200…220
    write_map("calib-step.png", np.where(XS >= 200, -4.0, 0.0), 0.0); ids.append("step")           # −4 beyond box x 200
    css = "body{margin:0;background:#fff}.box{position:absolute;left:110px;width:220px;height:44px;overflow:hidden}.mark{position:absolute;background:#000}"
    filt = "".join(f'<filter id="{n}" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB"><feImage href="calib-{n}.png" preserveAspectRatio="none" result="m"/><feDisplacementMap in="SourceGraphic" in2="m" scale="40" xChannelSelector="R" yChannelSelector="G"/></filter>' for n in ids)
    marks = '<div class="mark" style="left:60px;top:0;width:4px;height:44px"></div><div class="mark" style="left:120px;top:20px;width:60px;height:4px"></div><div class="mark" style="left:205px;top:0;width:3px;height:44px"></div>'
    boxes = f'<div class="box" style="top:10px">{marks}</div>' + "".join(f'<div class="box" style="top:{60 + i * 50}px;filter:url(#{n})">{marks}</div>' for i, n in enumerate(ids))
    # viewport + standalone metas (the data session's simulator run 2026-09-19: without them iOS lays the page out at 980 px and scales it, and the
    # step cannot be read at 3×; the standalone window is where the page is accepted)
    head = '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="apple-mobile-web-app-capable" content="yes"><title>feDisplacementMap calibration</title>'
    open("webkit-displacement.html", "w").write(f'<!doctype html><html><head>{head}<style>{css}</style></head><body><svg width="0" height="0" style="position:absolute">{filt}</svg>{boxes}</body></html>')
    open("ids.txt", "w").write("\n".join(ids)); print(len(ids), "maps; page height", 60 + len(ids) * 50 + 50)

if __name__ == "__main__": main()
