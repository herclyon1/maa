# vb_step_kernel.py — the exact integer-grid weights of ONE pyramid step (variable_blur_downsample_frag_lpf): an output pixel of level k+1 at (j, i) samples level k at
# (2i + 1, 2j + 1) + the 13 tap offsets with bilinear filtering; expanding each bilinear tap onto the four texels gives a fixed weight table over level-k
# texels (relative to the texel 2i + 1 − ½ … i.e. the boundary), independent of (i, j). Also the à trous (undecimated) chain and its std per level.
import numpy as np
TAPS = [((0, 0), 0.105497)] + [((s * 1.9600850, 0), 0.090186) for s in (1, -1)] + [((0, s * 1.9600850), 0.090186) for s in (1, -1)] \
     + [((sx * 1.9600850, sy * 1.9600850), 0.077098) for sx in (1, -1) for sy in (1, -1)] + [((s * 3.920676, 0), 0.056341) for s in (1, -1)] + [((0, s * 3.920676), 0.056341) for s in (1, -1)]
def step_kernel():
    """weights over source texels for the output pixel whose sampling centre is at source coordinate 2i+1 (texel centres at n + .5): the sample at
    x = 2i + 1 + ox has fx = x − .5 = 2i + .5 + ox → texels floor(fx), floor(fx)+1 with (1 − t, t)"""
    K = {}
    for (ox, oy), w in TAPS:
        fx, fy = 0.5 + ox, 0.5 + oy   # relative to texel 2i (index 0 = texel 2i)
        x0, y0 = int(np.floor(fx)), int(np.floor(fy)); tx, ty = fx - x0, fy - y0
        for (dx, wx) in ((x0, 1 - tx), (x0 + 1, tx)):
            for (dy, wy) in ((y0, 1 - ty), (y0 + 1, ty)):
                if wx * wy: K[(dx, dy)] = K.get((dx, dy), 0.0) + w * wx * wy
    xs = [k[0] for k in K]; ys = [k[1] for k in K]; x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    M = np.zeros((y1 - y0 + 1, x1 - x0 + 1))
    for (dx, dy), w in K.items(): M[dy - y0, dx - x0] = w
    return M, (x0, y0)
if __name__ == '__main__':
    M, (x0, y0) = step_kernel(); print('step kernel', M.shape, 'origin texel', (x0, y0), 'sum', M.sum().round(6))
    np.set_printoptions(precision=5, suppress=True, linewidth=200); print(M)
    # the à trous chain at level-0 resolution: level k = level k−1 ⊛ dilate(M, 2^(k−1)); its std
    def dil(M, d):
        h, w = M.shape; D = np.zeros(((h - 1) * d + 1, (w - 1) * d + 1))
        D[::d, ::d] = M; return D
    from numpy.fft import fft2, ifft2
    N = 512; img = np.zeros((N, N)); img[N // 2, N // 2] = 1.0
    def conv(img, K):
        out = np.zeros_like(img); h, w = K.shape; oy, ox = h // 2, w // 2
        for dy in range(h):
            for dx in range(w):
                if K[dy, dx]: out += K[dy, dx] * np.roll(np.roll(img, dy - oy, axis=0), dx - ox, axis=1)
        return out
    cur = img; j, i = np.mgrid[0:N, 0:N]
    for k in range(1, 4):
        cur = conv(cur, dil(M, 2 ** (k - 1))); s = cur.sum(); mx = (cur * i).sum() / s; sx = np.sqrt((cur * (i - mx) ** 2).sum() / s)
        print(f'a trous level {k}: kernel order {(M.shape[0] - 1) * 2 ** (k - 1) + 1} (dilated step) · chained footprint std {sx:.3f} base px (pyramid phase-avg: {[2.147, 4.694, 9.581][k - 1]})')
