"""Read the applied displacement from a render of webkit-displacement.html (device px per CSS px = argv[2], default 6):
python3 check_calib.py <render.png> [px_per_css]. Prints per map: the shift of the vertical mark (x) / horizontal mark (y),
the expected value (−u) and the difference."""
import sys, os
import numpy as np
from PIL import Image

def crossings(g, start, k):
    out = []
    for i in range(len(g) - 1):
        if (g[i] - 0.5) * (g[i + 1] - 0.5) < 0: out.append(start + (i + (0.5 - g[i]) / (g[i + 1] - g[i])) / k)
    return out

def main():
    here = os.path.dirname(os.path.abspath(__file__)); ids = open(os.path.join(here, "ids.txt")).read().split()
    k = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
    a = np.asarray(Image.open(sys.argv[1]).convert("L")).astype(float) / 255
    def xe(top, x0=160, x1=185): return crossings(a[int(round((top + 22) * k)), int(x0 * k):int(x1 * k)], x0, k)
    def ye(top, y0=10, y1=34): return crossings(a[int(round((top + y0) * k)):int(round((top + y1) * k)), int(250 * k)], y0, k)
    bx, by = xe(10), ye(10)
    print(f"unfiltered: mark edges x {[round(v, 2) for v in bx]} y {[round(v, 2) for v in by]}")
    for i, n in enumerate(ids):
        top = 60 + i * 50
        if n.startswith("x"):
            e = xe(top); u = float(n[1:]); s = [round(v - b, 2) for v, b in zip(e, bx)]
            print(f"{n:8s} map u {u:+6.2f} → applied {[-v for v in s]} (short by {[round(u + v, 2) for v in s]})")
        elif n.startswith("y"):
            e = ye(top); u = float(n[1:]); s = [round(v - b, 2) for v, b in zip(e, by)]
            print(f"{n:8s} map u {u:+6.2f} → applied {[-v for v in s]} (short by {[round(u + v, 2) for v in s]})")
        else:
            print(f"{n:8s} edges x 300…330: {[round(v, 2) for v in xe(top, 300, 330)]}")

if __name__ == "__main__": main()
