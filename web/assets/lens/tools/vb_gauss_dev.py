# vb_gauss_dev.py — how far the same-std Gaussian is from the exact pyramid kernel (phase-averaged), per level: L1 distance of the 2D kernels, max |diff| at the
# centre, and the RMS difference of the two blurs on a black/white edge and on a 1-pt line (base px units; 1.5 px/pt on a 3× device)
import numpy as np, sys
sys.path.insert(0, '.')
from vb_kernel import down, effective, W, stats
def pyramid_kernel(k):
    phases = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 1), (3, 2), (1, 3), (2, 2)]; acc = []
    for (px_, py_) in phases:
        base = np.zeros((W, W)); base[W // 2 + py_, W // 2 + px_] = 1.0; levels = [base]
        for _ in range(k): levels.append(down(levels[-1]))
        acc.append(np.roll(np.roll(effective(levels, float(k)), -py_, axis=0), -px_, axis=1))
    return np.mean(acc, axis=0)
def gauss(sig):
    j, i = np.mgrid[0:W, 0:W]; g = np.exp(-((i - W // 2) ** 2 + (j - W // 2) ** 2) / (2 * sig * sig)); return g / g.sum()
for k in (1, 2, 3):
    K = pyramid_kernel(k); s, sx, sy = stats(K); G = gauss(sx)
    l1 = np.abs(K - G).sum(); c = W // 2
    prof = lambda M: M[c, c:c + 24]
    # blurred edge (x ≥ c → 1) and a 1-px line: RMS differences over the image
    from numpy.fft import fft2, ifft2
    conv = lambda img, Kk: np.real(ifft2(fft2(img) * fft2(np.fft.ifftshift(Kk))))
    edge = np.zeros((W, W)); edge[:, c:] = 1.0; line = np.zeros((W, W)); line[:, c] = 1.0
    de = conv(edge, K) - conv(edge, G); dl = conv(line, K) - conv(line, G)
    print(f'level {k}: std {sx:.3f} base px · L1(K − G) {l1:.4f} · centre K {K[c, c]:.5f} vs G {G[c, c]:.5f} · edge RMS diff {np.sqrt((de ** 2).mean()):.5f} (max {np.abs(de).max():.4f}) · line max diff {np.abs(dl).max():.5f}')
    print('   radial profile K:', ' '.join(f'{v:.4f}' for v in prof(K)[:12]))
    print('   radial profile G:', ' '.join(f'{v:.4f}' for v in prof(G)[:12]))
