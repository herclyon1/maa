/* platter-glass.js — the tab bar platter's glassBackground edge terms (外观 10-01, BOARD ⑤A): the in-shader KeyFill STROKE and the RingShadow,
   drawn as one black-alpha layer over nav.tabs .plat (the borrowed glass-button drop shadow is gone: index.html .plat).
   Keys (read, simulator A iOS 27.0, UIProbe subtree of UILayoutContainerView › _GlassGroupView › UISDFBackdropView glassBackground, light + dark:
   BOARD/evidence/外观-1001-标签栏/platter-glassBackground-both.json) — the same 70-key set as the alert's (alert-glass.js KEYS):
     KeyFill  Amount .4, Angle π/2, ColorBias −.3, Height .5333, EffectOffset −.5333, SpreadSDR 1.85 light / 1.309 dark
     Ring     Opacity .06, StrokeWidth 4, Offset 8, BlurRadius 5, Mask 1
   Formulas: keyfill-highlight.md §2c (stroke_mode 1: (Offset < 0) ∧ |Height + Offset| < .001) and §4 (ring shadow), as alert-glass.js R57″ builds them:
     d = the capsule's SDF (pt, outside +), fw = 1 / px-per-pt, cov = sat(.5 − d/fw)
     KeyFill: band = cov < 1 and d − .5333 < fw/2; v = (1 − cov) · sat((.5333 − d)/fw + .5); n = the SDF normal, dir = (sin π/2, −cos π/2) = (1, 0),
       S = cos(SpreadSDR); a± = v · sat((±n·dir − S)/(1 − S)); k = Σ a / (1 + u(1 − a)), u = 1/Amount − 2 = .5
       screen rgb′ = B″ · (1 + ColorBias · k · (3 − 2B″)), B″ = mix(B, min(face(B), B), k)
     Ring: d_r = the SDF at p − (0, 8) (the shape moved down 8); ring = N((d_r + 4)/5) − N(d_r/5); term = .06 · ring · cov (Mask 1 → inside only);
       black source-over at α = term — exact, independent of the backdrop.
   Approximation (标 近似): the KeyFill's darkening depends on the backdrop B per pixel; a black layer can only scale B by a constant, so the layer uses
   α = −ColorBias · k · (3 − 2·B_ref) with B_ref = 1 light (exact on white: 1 − .3k) and 0 dark (exact on black, where the line is invisible anyway);
   B″ = B taken (min(face(B), B) = B on the light backdrops measured: face white 1.03 / fill white .2). The glass body (blur, face, bleed, refraction)
   is not touched here — still the glass-button recipe in index.html (unread vs the platter keys, BOARD/evidence/外观-1001-标签栏/README.md). */
(function () {
  "use strict";
  const K = { h: .5333, off: -.5333, amountU: 1 / .4 - 2, bias: -.3, spread: { light: 1.85, dark: 1.309 }, ringOp: .06, ringS: 4, ringOff: 8, ringR: 5 };
  const M = 2;   // canvas margin around the platter (pt): the stroke reaches .5333 + half a pixel outside; the ring (Mask 1) stays inside
  const sat = (x) => x < 0 ? 0 : x > 1 ? 1 : x;
  /* standard normal CDF (Abramowitz–Stegun 7.1.26 via erf, |error| < 1.5e-7) — the shader's half-precision polynomial is the same function to ±1e-3 */
  const N = (x) => { const z = Math.abs(x) / Math.SQRT2, t = 1 / (1 + .3275911 * z),
    e = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - .284496736) * t + .254829592) * t * Math.exp(-z * z); return x >= 0 ? .5 * (1 + e) : .5 * (1 - e); };
  /* capsule / rounded-box SDF in pt about the box centre (half sizes bx, by, radius r) and its outward normal */
  const sdf = (px, py, bx, by, r) => { const qx = Math.abs(px) - bx + r, qy = Math.abs(py) - by + r, ox = Math.max(qx, 0), oy = Math.max(qy, 0);
    const l = Math.hypot(ox, oy), d = l + Math.min(Math.max(qx, qy), 0) - r;
    let nx, ny; if (l > 0) { nx = ox / l; ny = oy / l; } else if (qx > qy) { nx = 1; ny = 0; } else { nx = 0; ny = 1; }
    return [d, nx * Math.sign(px || 1), ny * Math.sign(py || 1)]; };
  const paint = (W, H, dark, dpr) => {
    const cw = Math.round((W + 2 * M) * dpr), ch = Math.round((H + 2 * M) * dpr), c = document.createElement("canvas"); c.width = cw; c.height = ch;
    const ctx = c.getContext("2d"), id = ctx.createImageData(cw, ch), px = id.data, fw = 1 / dpr, bx = W / 2, by = H / 2, r = Math.min(W, H) / 2;
    const S = Math.cos(dark ? K.spread.dark : K.spread.light), bref = dark ? 0 : 1;
    /* the straight run (|x| ≤ bx − r) depends on y only: one column is computed and copied across (the caps get every pixel) — 22.8 → a few ms at 416×62 ×3 */
    const i0 = Math.ceil((M + r) * dpr), i1 = Math.floor((M + W - r) * dpr) - 1, mid = i1 >= i0 ? i0 : -1;
    for (let j = 0; j < ch; j++) for (let i = 0; i < cw; i++) {
      if (mid >= 0 && i > i0 && i <= i1) { const o = (j * cw + i) * 4, m = (j * cw + i0) * 4; px[o + 3] = px[m + 3]; continue; }
      const x = (i + .5) / dpr - M - bx, y = (j + .5) / dpr - M - by;
      const [d, nx] = sdf(x, y, bx, by, r), cov = sat(.5 - d / fw);
      let term = 0;
      if (cov > 0) { const dr = sdf(x, y - K.ringOff, bx, by, r)[0]; term = K.ringOp * sat(N((dr + K.ringS) / K.ringR) - N(dr / K.ringR)) * cov; }
      let akf = 0;
      if (cov < 1 && d + K.off < fw / 2) {
        const v = (1 - cov) * sat((-(d + K.off)) / fw + .5);
        let k = 0; for (const s of [1, -1]) { const a = v * sat((s * nx - S) / (1 - S)); k += a / (1 + K.amountU * (1 - a)); }
        akf = sat(-K.bias * k * (3 - 2 * bref));
      }
      const a = 1 - (1 - term) * (1 - akf); if (a <= 0) continue;
      const o = (j * cw + i) * 4; px[o] = px[o + 1] = px[o + 2] = 0; px[o + 3] = Math.round(a * 255);
    }
    ctx.putImageData(id, 0, 0); return c.toDataURL("image/png");
  };
  const cache = {};
  let el = null, last = "";
  const draw = () => {
    const plat = document.querySelector("nav.tabs .plat"); if (!plat) return;
    const W = plat.offsetWidth, H = plat.offsetHeight; if (!W || !H) return;
    const dark = matchMedia("(prefers-color-scheme: dark)").matches, dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1)), key = W + "x" + H + (dark ? "d" : "l") + dpr;
    if (!el || el.parentNode !== plat) { el = document.createElement("div"); el.className = "plat-edge"; el.setAttribute("aria-hidden", "true"); plat.appendChild(el); last = ""; }
    if (key === last) return; last = key;
    const href = cache[key] || (cache[key] = paint(W, H, dark, dpr));
    el.style.backgroundImage = `url("${href}")`;
  };
  const start = () => {
    /* first paint at idle: 6–9 ms at 416×62 ×3 in desktop Chrome (the straight run copied), several times that on a phone — kept out of the load */
    (window.requestIdleCallback || ((f) => setTimeout(f, 200)))(() => draw(), { timeout: 1500 });
    const plat = document.querySelector("nav.tabs .plat");
    if (plat && window.ResizeObserver) new ResizeObserver(() => draw()).observe(plat);
    else addEventListener("resize", draw);
    const mq = matchMedia("(prefers-color-scheme: dark)"); (mq.addEventListener ? mq.addEventListener("change", draw) : mq.addListener(draw));
    const nav = document.getElementById("tabs"); if (nav && window.MutationObserver) new MutationObserver(() => draw()).observe(nav, { childList: true });   // view.js builds the bar's children after load
  };
  window.PlatterGlass = { draw, paint };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
