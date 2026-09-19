#!/usr/bin/env python3
"""B7: the page sheet's static geometry — a render of sheet-test.html (wksnap 440×956, 6 px/pt) against the native presented frame
(tools/touch/sheet-native-{light,dark}-presented.png, 3 px/pt): sheet top row, the top-left corner contour against a circle R 38,
the dimmed rows' colour, the Done disc's bounding box, the check glyph's box, the title's box. usage: geom_check.py <native.png> <web.png> [--dark] [--out side-by-side.png]"""
import argparse
import numpy as np
from PIL import Image


def measure(path, k, dark):
    a = np.asarray(Image.open(path).convert("RGB")).astype(int); H, W, _ = a.shape
    col = a[:, int(220 * k)]
    sheet = (28, 28, 30) if dark else (242, 242, 247)
    d = np.abs(col - np.array(sheet)).sum(axis=1); top = next(i for i in range(int(40 * k), int(120 * k)) if d[i] < 12) / k
    dim = tuple(int(v) for v in a[:int(56 * k), int(220 * k)].mean(axis=0))
    cont = []
    for y in np.arange(62.17, 100, 1.0):
        row = a[int(round(y * k))]; dd = np.abs(row - np.array(sheet)).sum(axis=1); xs = np.where(dd < 12)[0]
        if len(xs): cont.append((y, xs.min() / k))
    err = [abs(x - (38 - np.sqrt(38 ** 2 - (100 - y) ** 2))) for y, x in cont if y < 100]
    m = (a[..., 2] > 200) & (a[..., 0] < 80) & (a[..., 1] > 100) & (a[..., 1] < 180); ys, xs = np.where(m)
    disc = (round(xs.min() / k, 2), round(ys.min() / k, 2), round((xs.max() + 1) / k, 2), round((ys.max() + 1) / k, 2))
    sub = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]; w = sub.min(axis=2) > 235; wy, wx = np.where(w)
    glyph = (round((xs.min() + wx.min()) / k, 2), round((ys.min() + wy.min()) / k, 2), round((xs.min() + wx.max() + 1) / k, 2), round((ys.min() + wy.max() + 1) / k, 2)) if len(wy) else None
    reg = a[int(85 * k):int(125 * k), int(150 * k):int(300 * k)]; tm = (reg.min(axis=2) > 150) if dark else (reg.max(axis=2) < 120); ty, tx = np.where(tm)
    title = (round(150 + tx.min() / k, 2), round(85 + ty.min() / k, 2), round(150 + (tx.max() + 1) / k, 2), round(85 + (ty.max() + 1) / k, 2)) if len(ty) else None
    return {"sheet_top": round(top, 2), "dim_rgb": dim, "corner_mean_err_R38": round(float(np.mean(err)), 2), "corner_rows": cont[:6], "done_disc": disc, "check_glyph": glyph, "title": title}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("native"); ap.add_argument("web"); ap.add_argument("--dark", action="store_true"); ap.add_argument("--out")
    a = ap.parse_args()
    n = measure(a.native, 3.0, a.dark); w = measure(a.web, 6.0, a.dark)
    for key in ("sheet_top", "dim_rgb", "corner_mean_err_R38", "done_disc", "check_glyph", "title"):
        print(f"{key:22s} native {n[key]}   web {w[key]}")
    print("corner contour rows (y, x) native", [(round(y, 2), round(x, 2)) for y, x in n["corner_rows"]], "web", [(round(y, 2), round(x, 2)) for y, x in w["corner_rows"]])
    if a.out:
        nat = Image.open(a.native).convert("RGB").crop((0, 0, 1320, 140 * 3)); web = Image.open(a.web).convert("RGB").crop((0, 0, 2640, 140 * 6)).resize((1320, 420), Image.BOX)
        m = Image.new("RGB", (1320, 850), (255, 0, 255)); m.paste(nat, (0, 0)); m.paste(web, (0, 430)); m.save(a.out)


if __name__ == "__main__": main()
