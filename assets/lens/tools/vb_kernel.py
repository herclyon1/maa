# vb_kernel.py — the effective full-resolution kernel of QuartzCore's variableBlur mip pyramid, evaluated from the read shaders
# (default.metallib variable_blur_downsample_frag_lpf: 13 taps at (0,0) w .105497; (±1.96,0),(0,±1.96) w .090186; (±1.96,±1.96) w .077098;
# (±3.92,0),(0,±3.92) w .056341, offsets in SOURCE-level texels, bilinear, clamp_to_zero; each level = half the size; variable_blur_frag_lpf:
# trilinear read at level L = log2(r) (r ≥ 2) or log2(1 + r/2), r = 1.6 × radius_px × mask, four taps at ±L·(¼ texel of the base)).
# Output: per level k the phase-averaged kernel's std (base px) and the effective std at a given r; no fitting — the numbers are the formula's.
import numpy as np
W = 512
TAPS = [((0, 0), 0.105497)] + [((s * 1.9600850, 0), 0.090186) for s in (1, -1)] + [((0, s * 1.9600850), 0.090186) for s in (1, -1)] \
     + [((sx * 1.9600850, sy * 1.9600850), 0.077098) for sx in (1, -1) for sy in (1, -1)] + [((s * 3.920676, 0), 0.056341) for s in (1, -1)] + [((0, s * 3.920676), 0.056341) for s in (1, -1)]
def bilinear(img, x, y):
    """sample img (H×W) at texel coords (x, y) — texel centres at integer + .5; clamp_to_zero outside"""
    H, Wd = img.shape; fx, fy = x - 0.5, y - 0.5; x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int); tx, ty = fx - x0, fy - y0
    def px(i, j):
        i = np.asarray(i); j = np.asarray(j); ok = (i >= 0) & (i < Wd) & (j >= 0) & (j < H); out = np.zeros(np.broadcast(i, j).shape); ii = np.clip(i, 0, Wd - 1); jj = np.clip(j, 0, H - 1); out[ok] = img[jj[ok], ii[ok]]; return out
    return (1 - tx) * (1 - ty) * px(x0, y0) + tx * (1 - ty) * px(x0 + 1, y0) + (1 - tx) * ty * px(x0, y0 + 1) + tx * ty * px(x0 + 1, y0 + 1)
def down(img):
    H, Wd = img.shape; h, w = H // 2, Wd // 2; j, i = np.mgrid[0:h, 0:w]; cx, cy = (i + 0.5) * 2, (j + 0.5) * 2   # output texel centre in source texels
    out = np.zeros((h, w))
    for (ox, oy), wt in TAPS: out += wt * bilinear(img, cx + ox, cy + oy)
    return out
def effective(level_imgs, L):
    """the fragment at base texel centre p reads level L (trilinear = mix of floor/ceil levels, bilinear each) — return the full-res image"""
    k0 = int(np.floor(L)); f = L - k0; H, Wd = level_imgs[0].shape; j, i = np.mgrid[0:H, 0:Wd]; p = ((i + 0.5) / Wd, (j + 0.5) / H)
    def rd(k):
        img = level_imgs[k]; h, w = img.shape; return bilinear(img, p[0] * w, p[1] * h)
    return (1 - f) * rd(k0) + f * rd(min(k0 + 1, len(level_imgs) - 1)) if f > 0 else rd(k0)
def stats(img):
    H, Wd = img.shape; j, i = np.mgrid[0:H, 0:Wd]; s = img.sum(); mx, my = (img * i).sum() / s, (img * j).sum() / s
    return s, np.sqrt((img * (i - mx) ** 2).sum() / s), np.sqrt((img * (j - my) ** 2).sum() / s)
if __name__ == '__main__':
    import sys
    rs = [float(a) for a in sys.argv[1:]] or [4.8]
    acc = {}
    phases = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 1), (3, 2), (1, 3), (2, 2)]   # sub-grid phases of the impulse (the pyramid is shift-variant)
    for k in range(0, 7): acc[k] = []
    for (px_, py_) in phases:
        base = np.zeros((W, W)); base[W // 2 + py_, W // 2 + px_] = 1.0
        levels = [base]
        for k in range(6): levels.append(down(levels[-1]))
        for k in range(0, 7): acc[k].append(np.roll(np.roll(effective(levels, float(k)), -py_, axis=0), -px_, axis=1))   # re-centred on the impulse
    print('level  sum   std_x  std_y  (base px, phase-averaged; std of the effective full-res kernel)')
    for k in range(0, 7):
        m = np.mean(acc[k], axis=0); s, sx, sy = stats(m); print(f'{k:5d}  {s:.3f}  {sx:6.3f} {sy:6.3f}')
    for r in rs:
        L = max(0.0, np.log2(r) if r >= 2 else np.log2(1 + r / 2)); k0 = int(np.floor(L)); f = L - k0
        imgs = []
        for (px_, py_) in phases:
            base = np.zeros((W, W)); base[W // 2 + py_, W // 2 + px_] = 1.0; levels = [base]
            for k in range(6): levels.append(down(levels[-1]))
            e = effective(levels, L)
            # the four taps at ±L/4 base texels: average of the four shifted reads
            d = L / 4.0; H, Wd = e.shape; j, i = np.mgrid[0:H, 0:Wd]; e4 = np.zeros_like(e)
            for sx in (1, -1):
                for sy in (1, -1): e4 += 0.25 * bilinear(e, i + 0.5 + sx * d, j + 0.5 + sy * d)
            imgs.append(np.roll(np.roll(e4, -py_, axis=0), -px_, axis=1))
        m = np.mean(imgs, axis=0); s, sx, sy = stats(m)
        print(f'r {r:.3f} → L {L:.3f} (levels {k0}/{k0 + 1} mix {f:.2f}): sum {s:.3f} std {sx:.3f} / {sy:.3f} base px')
