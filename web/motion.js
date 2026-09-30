/* motion.js — the page's shared motion primitives (BOARD.md #1, 2026-09-19): the three pieces the device checks of B14 settled
   (remote-ref/tools/touch/b14-cell-{8bf3bcd,65850cb}.md, seg-webgl-c6c35aa.md), pulled out of controls.js so every control uses ONE copy.
   Global `window.Motion`; referenced lazily (inside handlers), so the script order among the control files does not matter.
   - spring(s, target, [zeta, response], dt): one closed-form step of x'' = −ω²(x − target) − 2ζωx', ω = 2π / response, from the current
     value / velocity (s = {x, v}); ζ < 1 underdamped, ζ ≥ 1 critical — the same formula as view.js springStep (flex-interaction.md §6).
   - afterPaint(fn): rAF → rAF. A rAF callback runs before its frame's paint, so a callback nested in a second rAF runs only after the first
     frame was painted; a setTimeout(0) after a rAF is NOT guaranteed to wait for the paint on the device (数据 3ecf176 check).
   - swallowNextClick(el, ms): the browser's own click for a touch the page already handled arrives 40–60 ms after the up on Android
     (数据 seg-webgl-c6c35aa.md ①), long after any 0-ms flag; the element carries data-rc until that click is swallowed, or ms.
   - click(el): the click the page fires itself (never swallowed).
   - sample(f, T, tol, {h0, hmin, knots}): error-adaptive keyframes for a curve that Web Animations will play back linearly (easing linear) — see below.
   - thin(nodes, i0, i1, tol, err): one property's own keyframes out of a shared sample — see below.
   - css(str): a CSS value string as numbers + a rebuild, so string-producing code can be sampled numerically — see below. */
(() => {
  "use strict";
  const spring = (s, target, [zeta, response], dt) => {
    if (!(dt > 0)) return s;
    const w = 2 * Math.PI / response, dx = s.x - target, v = s.v;
    if (zeta < 1) {
      const wd = w * Math.sqrt(1 - zeta * zeta), B = (v + zeta * w * dx) / wd, e = Math.exp(-zeta * w * dt), c = Math.cos(wd * dt), sn = Math.sin(wd * dt);
      s.x = target + e * (dx * c + B * sn); s.v = e * (-zeta * w * (dx * c + B * sn) + (-dx * wd * sn + B * wd * c));
    } else {
      const e = Math.exp(-w * dt), B = v + w * dx; s.x = target + e * (dx + B * dt); s.v = e * (B - w * (dx + B * dt));
    }
    return s;
  };
  const afterPaint = (fn) => requestAnimationFrame(() => requestAnimationFrame(fn));
  let synthetic = false;
  const swallowNextClick = (el, ms = 700) => { el.dataset.rc = "1"; setTimeout(() => { delete el.dataset.rc; }, ms); };
  const click = (el) => { synthetic = true; try { el.click(); } finally { synthetic = false; } };
  document.addEventListener("click", (e) => {
    if (synthetic) return;
    const el = e.target.closest && e.target.closest("[data-rc]");
    if (el) { delete el.dataset.rc; e.preventDefault(); e.stopImmediatePropagation(); }   // the browser's click for a press the page handled
  }, true);
  /* sample(f, T, tol, opts) → [[t, values], …] from t = 0 to T inclusive (动效 10-01, the approach of nav.js waPlay on relay1-comp-nav: a fixed 1/120 s grid
     played linearly missed the nav push's spring by 1.7 px near t0). Each step is as long as a straight line between its ends stays within tol of f at ¼ ½ ¾
     of the step: ≤ h0, doubled after a pass, halved on a miss, ≥ hmin (a step at the floor is taken as is). f(t) → an array of numbers (the same length at
     every t); it is evaluated OUT OF ORDER (probes inside a step, retries after a halving), so it must be a pure function of t. tol: one tolerance per
     component (or one number for all). knots: ascending times a step may not cross — the corners of a piecewise-linear table (a step straddling a corner
     otherwise halves down to hmin around it, and the corner itself is only approximated). One unit for T, h0, hmin, knots and f's argument; the defaults
     are seconds (h0 1/120, hmin h0 / 64 = 1/7680). Tolerance: .004 px in nav.js made ~1400 keyframes and a 13 ms tap task; callers here use .05 px for
     lengths and 5e-3 for alpha. out.evals = the number of f calls (the cost). A probe is at t + hh·r and a step ends at t + hh, so after a miss the halved
     step's end and its ½ probe are the old ½ and ¼ probes (a power-of-two scale is exact in floating point), and the step after it often lands on the
     failed step's end and ¾ probe: every value is kept for the call (a Map by t) and reused, not re-evaluated (the 随机模式 menu's open: 607 → 501 evaluations). */
  const sample = (f, T, tol, { h0 = 1 / 120, hmin = h0 / 64, knots = null } = {}) => {
    let evals = 1; const memo = new Map(), F = (t) => { let v = memo.get(t); if (v === undefined) { evals++; v = f(t); memo.set(t, v); } return v; };
    const v0 = f(0), n = v0.length, tl = typeof tol === "number" ? new Array(n).fill(tol) : tol, out = [[0, v0]];
    const err = new Array(n).fill(0), e = new Array(n), R = [0.5, 0.25, 0.75];   // err: per component, the largest probe deviation of the steps taken (Motion.thin's budget)
    const ok = (a, fa, hh, fb, all) => { e.fill(0); for (const r of R) { const fr = F(a + hh * r); for (let i = 0; i < n; i++) { const d = Math.abs(fr[i] - (fa[i] + (fb[i] - fa[i]) * r)); if (!(d <= tl[i]) && !all) return false; if (!(d <= e[i])) e[i] = d; } } return true; };
    const ks = knots || [], eps = 1e-9 * Math.max(1, T); let t = 0, h = h0, k = 0;
    while (T - t > eps) {
      while (k < ks.length && ks[k] <= t + eps) k++;
      const lim = k < ks.length && ks[k] < T ? ks[k] : T, fa = out[out.length - 1][1]; let hh = Math.min(h, lim - t), miss = false, b, fb;   // hh: this step (clipped at the next knot / T)
      for (;;) { const end = lim - t - hh <= eps; if (end) hh = lim - t; b = end ? lim : t + hh; fb = F(b); if (ok(t, fa, hh, fb, hh <= hmin) || hh <= hmin) break; hh /= 2; miss = true; }   // at the floor the probes still run (err)
      for (let i = 0; i < n; i++) if (!(e[i] <= err[i])) err[i] = e[i];
      out.push([b, fb]); t = b; h = Math.min(h0, (miss ? hh : h) * 2);
    }
    out.evals = evals; out.err = err; return out; };
  /* thin(nodes, i0, i1, tol, err) → the indices of nodes kept for components i0 … i1 − 1 (one property's own keyframes out of a shared sample): a node goes
     when the straight line between its kept neighbours stays within tol − err of every node in between, component by component. The sample's line is
     within err of f at its probes (sample's out.err), a line within tol − err of the sample's nodes is within tol − err of the sample's line (both are
     straight between those nodes), so within tol of f at the same probes — the guarantee sample gives, not a looser one. A component whose own error
     already used its tolerance keeps every node. */
  const thin = (nodes, i0, i1, tol, err) => { const keep = [0], m = nodes.length, k = i1 - i0, d = [], lo = new Array(k), hi = new Array(k);
    for (let i = i0; i < i1; i++) d.push(Math.max(0, (typeof tol === "number" ? tol : tol[i]) - (err ? err[i] : 0)));
    for (let a = 0; a < m - 1;) { const [ta, va] = nodes[a]; lo.fill(-Infinity); hi.fill(Infinity); let c = a + 1;   // lo / hi: the slopes from node a that pass every node so far within d (one pass, O(n))
      for (let nx = a + 1; nx < m; nx++) { const [tn, vn] = nodes[nx], dt = tn - ta; let fits = true;
        for (let q = 0; q < k && fits; q++) { const s = (vn[i0 + q] - va[i0 + q]) / dt; if (s < lo[q] || s > hi[q]) fits = false; }
        if (!fits) break; c = nx;
        for (let q = 0; q < k; q++) { const x = vn[i0 + q] - va[i0 + q]; lo[q] = Math.max(lo[q], (x - d[q]) / dt); hi[q] = Math.min(hi[q], (x + d[q]) / dt); } }
      keep.push(c); a = c; }
    return keep; };
  /* css(str) → { nums, units, key, build(nums) }: "inset(1.2px 3px 4px 5px round 6px)" → nums [1.2, 3, 4, 5, 6], units ["px" ×5], build → the string with new
     numbers; key = the shape: the identifiers in order and where the numbers stand ("inset#px#px#px#px round#px"; punctuation is not compared).
     css.scan(str, out) pushes the numbers onto out and returns the key (the per-probe path: one native match(), no parts kept). Identifiers are taken
     whole (the 3 of translate3d / scale3d is not a number); a number may carry a sign and an exponent (String(2.5e-7) = "2.5e-7"). Two strings of one
     shape are the same function list, which Web Animations interpolates argument by argument (CSS Transforms 2 §16 "Interpolation of Transforms", same
     functions; Filter Effects 1 §12 filter interpolation; CSS Shapes 1 basic-shape interpolation) — so a straight line between two keyframes' numbers is
     what the compositor draws between them. build writes each number rounded to 1e-5 (no exponent form). */
  const TOK = /[A-Za-z_]\w*|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g;
  const scan = (str, out) => { const m = str.match(TOK); let key = "";
    if (m) for (const x of m) { const c = x.charCodeAt(0); if ((c >= 48 && c <= 57) || c === 45 || c === 43 || c === 46) { out.push(+x); key += "#"; } else key += key && key.charCodeAt(key.length - 1) !== 35 ? " " + x : x; }
    return key; };
  const css = (str) => { str = String(str); const nums = [], key = scan(str, nums), parts = [], units = []; let last = 0, m; TOK.lastIndex = 0;
    while ((m = TOK.exec(str))) { const c = m[0].charCodeAt(0); if ((c >= 48 && c <= 57) || c === 45 || c === 43 || c === 46) { parts.push(str.slice(last, m.index)); last = m.index + m[0].length; const u = /^[A-Za-z_]\w*/.exec(str.slice(last)); units.push(u ? u[0] : ""); } }   // the unit: an identifier right after the number
    parts.push(str.slice(last));
    return { nums, units, key, build: (v) => { let o = parts[0]; for (let i = 0; i < v.length; i++) o += String(Math.round(v[i] * 1e5) / 1e5) + parts[i + 1]; return o; } }; };
  css.scan = (str, out) => scan(String(str), out);
  window.Motion = { spring, afterPaint, swallowNextClick, click, isSynthetic: () => synthetic, sample, thin, css };
})();
