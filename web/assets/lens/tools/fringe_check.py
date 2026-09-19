#!/usr/bin/env python3
"""A1 8× colour-fringe check — the three thresholds of the acceptance order (2026-09-19) on a screenshot of the lens held at the
divider (x 110–330 on the 440-pt screen), for the B4-c' wiring and the data session's C1:
  1. share of coloured pixels (max − min of RGB > 40) in the outer 12 pt of the lens capsule (native light 1.36 %, dark 1.38 %)
  2. mean / median saturation (max − min) of those pixels (native 69 / 62, dark 71 / 63)
  3. the colour order at the ends: per 2-pt row the dominant hue of the coloured pixels beyond |x| 98 — light: the right end
     has blue rows above yellow rows (per streak), the left end yellow above blue; dark (white labels on dark): the reverse
     (the native dark crop reads right yellow-above-blue, left blue-above-yellow) — reported as the row sequence and a
     centroid test; the theme is read off the band's mean luminance (< 128 = dark) unless --theme is given.
Every render is measured at the native's 3 px/pt: a 6 px/pt wksnap render is box-filtered to 3 first (--measure 3).

usage: fringe_check.py <png> [--layout auto|wksnap|seghold|native-crop] [--lens x,y,w,h] [--scale px_per_pt] [--measure 3] [--json]
  auto (by image width): 2640 → wksnap (the lens test page, 440×956 @6: lens 110,110.89,220,44); 1320 → seghold (index.html ?seghold,
  standalone 3×: lens 110,731.67,220,44 — the track top 737.67 of the C1 tables); 1560×420 → native-crop (tools/touch/
  seg-native-dragmid-{light,dark}.png: lens x 126 … 1428 px, centre row = height / 2). --lens (pt) and --scale override.
"""
import argparse, json, sys
import numpy as np
from PIL import Image

LAYOUTS = {"wksnap": (6.0, (110.0, 110.89, 220.0, 44.0)), "seghold": (3.0, (110.0, 731.67, 220.0, 44.0))}
THR = 40          # coloured = max − min > THR
BAND = 12.0       # the outer band (pt) measured from the capsule edge
END = 98.0        # the ends: |x − centre| > END


def load(path, layout, lens, scale, measure):
    im = Image.open(path).convert("RGB"); w, h = im.size
    if layout == "auto": layout = "native-crop" if (w, h) == (1560, 420) else "wksnap" if w == 2640 else "seghold" if w == 1320 else None
    if layout == "native-crop":
        k = (1428 - 126) / 220.0; cx, cy = (126 + 1428) / 2 / k, h / 2 / k; hw, hh = 110.0, 22.0
    else:
        if layout not in LAYOUTS and not (lens and scale): sys.exit(f"unknown layout for a {w}×{h} image: pass --lens x,y,w,h --scale px_per_pt")
        k = scale or LAYOUTS[layout][0]; x, y, lw, lh = lens or LAYOUTS[layout][1]; cx, cy, hw, hh = x + lw / 2, y + lh / 2, lw / 2, lh / 2
    if measure and k > measure and abs(k / measure - round(k / measure)) < 1e-6:     # box-filter to the measuring scale
        f = int(round(k / measure)); im = im.resize((w // f, h // f), Image.BOX); k = k / f
    return np.asarray(im).astype(int), k, cx, cy, hw, hh


def band_stats(a, k, cx, cy, hw, hh):
    H, W, _ = a.shape; r = hh
    bins = {"L": [0] * 6, "R": [0] * 6}; n = 0; sats = []; strongest = (0, None); luma = 0.0
    ys = np.arange(int((cy - hh) * k), int((cy + hh) * k)); xs = np.arange(int((cx - hw) * k), int((cx + hw) * k))
    for yy in ys:
        if yy < 0 or yy >= H: continue
        y = yy / k - cy
        for xx in xs:
            if xx < 0 or xx >= W: continue
            x = xx / k - cx; c = (hw - r) if x > 0 else -(hw - r)
            dist = (r - np.hypot(x - c, y)) if abs(x) > hw - r else (hh - abs(y))
            if dist < 0 or dist >= BAND: continue
            n += 1; p = a[yy, xx]; sv = int(p.max() - p.min()); luma += float(p.mean())
            if sv > THR:
                bins["L" if x < 0 else "R"][min(5, int(dist // 2))] += 1; sats.append(sv)
                if sv > strongest[0]: strongest = (sv, (round(float(x), 1), round(float(y), 1), tuple(int(v) for v in p)))
    tot = sum(bins["L"]) + sum(bins["R"])
    return {"n_band_px": n, "band_luma": round(luma / n, 1) if n else 0, "coloured_px": tot, "share_pct": round(tot / n * 100, 2) if n else None, "sat_mean": round(float(np.mean(sats)), 1) if sats else None,
            "sat_median": round(float(np.median(sats)), 1) if sats else None, "bins_2pt_from_edge_L": bins["L"], "bins_2pt_from_edge_R": bins["R"], "strongest": strongest[1]}


def end_order(a, k, cx, cy, hw, dark=False):
    H, W, _ = a.shape; out = {}
    for side, name in ((1, "right"), (-1, "left")):
        rows = []; blue_rows = []; yellow_rows = []
        x0, x1 = (cx + END, cx + hw) if side > 0 else (cx - hw, cx - END)
        for yr in range(-11, 12, 2):
            acc = np.zeros(3); cnt = 0
            for yy in range(int((cy + yr - 1) * k), int((cy + yr + 1) * k)):
                if yy < 0 or yy >= H: continue
                for xx in range(int(x0 * k), int(x1 * k)):
                    if xx < 0 or xx >= W: continue
                    p = a[yy, xx]
                    if p.max() - p.min() > THR: acc += p - p.mean(); cnt += 1
            if cnt:
                r, g, b = acc / cnt; tag = "B" if b > r + 10 else "Y" if r > b + 10 else "~"
                rows.append(f"{yr:+d}:{tag}{cnt}")
                if tag == "B": blue_rows += [yr] * cnt
                if tag == "Y": yellow_rows += [yr] * cnt
            else: rows.append(f"{yr:+d}:-")
        cb = float(np.mean(blue_rows)) if blue_rows else None; cyl = float(np.mean(yellow_rows)) if yellow_rows else None
        blue_above = (side > 0) != dark                      # light: right blue-above, left yellow-above; dark: reversed
        expect = "blue above yellow" if blue_above else "yellow above blue"
        ok = None if cb is None or cyl is None else ((cb < cyl) if blue_above else (cyl < cb))
        out[name] = {"rows": " ".join(rows), "blue_centroid_row": None if cb is None else round(cb, 1), "yellow_centroid_row": None if cyl is None else round(cyl, 1), "expected": expect, "ok": ok}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("png"); ap.add_argument("--layout", default="auto"); ap.add_argument("--lens", help="x,y,w,h in pt"); ap.add_argument("--scale", type=float, help="px per pt of the image")
    ap.add_argument("--measure", type=float, default=3.0, help="px per pt to measure at (box filter down to it; 0 = as is)"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--theme", choices=["light", "dark"], help="the colour order expected (auto: the band's mean luminance)")
    a = ap.parse_args()
    lens = tuple(float(v) for v in a.lens.split(",")) if a.lens else None
    img, k, cx, cy, hw, hh = load(a.png, a.layout, lens, a.scale, a.measure)
    stats = band_stats(img, k, cx, cy, hw, hh)
    theme = a.theme or ("dark" if stats["band_luma"] < 128 else "light")
    res = {"file": a.png, "px_per_pt": round(k, 3), "lens_centre_pt": [round(cx, 2), round(cy, 2)], "theme": theme, **stats, "ends": end_order(img, k, cx, cy, hw, theme == "dark")}
    if a.json: print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print(f"{a.png}: measured at {k:g} px/pt, lens centre ({cx:.2f}, {cy:.2f}), theme {theme} (band luma {res['band_luma']})")
    print(f"  1. coloured share of the outer 12 pt: {res['share_pct']} %  (coloured {res['coloured_px']} of {res['n_band_px']}; per 2-pt bin from the edge L {res['bins_2pt_from_edge_L']} R {res['bins_2pt_from_edge_R']})  native light 1.36 / dark 1.38")
    print(f"  2. saturation mean / median: {res['sat_mean']} / {res['sat_median']}  native light 69 / 62, dark 71 / 63; strongest px {res['strongest']}")
    for side in ("right", "left"):
        e = res["ends"][side]; print(f"  3. {side} end rows (y down, 2-pt): {e['rows']}  → blue centroid {e['blue_centroid_row']}, yellow {e['yellow_centroid_row']}: expected {e['expected']}: {'OK' if e['ok'] else 'NO' if e['ok'] is False else 'n/a'}")


if __name__ == "__main__": main()
