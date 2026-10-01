/* glass-hl.js — the KeyFill highlight (the inner bright edge) of the tab bar platter and the round glass buttons (外观 10-01, BOARD --glass-rim job):
   replaces the shared white inset .5 rim (--glass-rim, all four sides alike) on these elements; the menu keeps --glass-rim (its highlight is unread).
   Read (simulator A iOS 27.0, UIProbe): the platter's UISDFView effect CASDFKeyFillHighlightEffect + vibrantColorMatrix, light = dark
   (BOARD/evidence/外观-1001-标签栏/uiprobe-subtree-root2-{light,dark}.json) — the same keys as the glass buttons (deep-materials.md:82, 200 × 50;
   glass-button-press-formula.md:232–256, the 44 circle):
     key: angle 0 (dir (sin 0, −cos 0) = up), height 1, spread 1.3963, amount .5, colour white; fill: angle π (down), the same; curvature .75;
     diffuse: amount × .15, height × 8, spread × .65; layer filter vibrantColorMatrix rows (1.1202 −.1894 −.019 | −.0563 .9871 −.0191 | −.0563 −.1893 1.1574) + .1471, clamp 1.
   Formula: keyfill-highlight.md §2 — band(h, cos s, bias, dir, curvature): e = −d, t = sat(e/h), prof = mix(t < 1, 1 − t, curvature),
     aa = sat(e/fw + .5)·sat((h − e)/fw + .5), fw = (|n_x| + |n_y|)/px-per-pt, ang = sat((n·dir − cos s)/(1 − cos s)), v = prof·aa·ang (0 when e < −5),
     v′ = v/(1 + bias(1 − v)), bias = 1/amount − 2; three emits (main key + fill, diffuse key, diffuse fill), each out ← (1 − α)·out + α·V(out).
   So only the sides the spread reaches (top and bottom, spread 80°) get a line — the straight left / right edges of the capsule get none.
   Compositing: V for a grey backdrop = clamp(.9118·B + .1471) (the matrix's row sums; the saturation part S(1.29) is dropped — 近似, exact on greys).
     The three emits are run on a reference backdrop B_ref and the result drawn as ONE white layer at α = (out(B_ref) − B_ref)/(1 − B_ref), normal
     blending (a mix-blend-mode child of the backdrop-filtered element blends inside its isolated group, not with the page — tried: the multiply layer
     painted the dark platter white). Exact at B = B_ref: light .98 (the platter body on white, measured 250 / 251; V clamps to 1 there, so any light
     backdrop ≥ .92 is exact too), dark .13 (the native platter body on black, 33 / 255); other backdrops 近似.
   The map is painted per size (cached); while glassbtn.js grows a button (44 → 60) the map stretches until the size holds 120 ms (then it is redrawn). */
(function () {
  "use strict";
  const H1 = 1, S = 1.3963, CURV = .75, DH = 8, DS = .65, DA = .15, AMT = .5, VM = .0882, VB = .1471, M = 1;
  const sat = (x) => x < 0 ? 0 : x > 1 ? 1 : x;
  const sdf = (px, py, bx, by, r) => { const qx = Math.abs(px) - bx + r, qy = Math.abs(py) - by + r, ox = Math.max(qx, 0), oy = Math.max(qy, 0);
    const l = Math.hypot(ox, oy), d = l + Math.min(Math.max(qx, qy), 0) - r;
    let nx, ny; if (l > 0) { nx = ox / l; ny = oy / l; } else if (qx > qy) { nx = 1; ny = 0; } else { nx = 0; ny = 1; }
    return [d, nx * Math.sign(px || 1), ny * Math.sign(py || 1)]; };
  const band = (e, fw, ny, h, cs, bias, dy, curv) => {   // dir = (0, dy): n·dir = ny·dy
    if (e < -5) return 0;
    const t = sat(e / h), prof = (t < 1 ? 1 : 0) * (1 - curv) + (1 - t) * curv, aa = sat(e / fw + .5) * sat((h - e) / fw + .5), ang = sat((ny * dy - cs) / (1 - cs));
    const v = prof * aa * ang; return v / (1 + bias * (1 - v)); };
  const cs1 = Math.cos(S), csD = Math.cos(DS * S), b1 = 1 / AMT - 2, bD = 1 / (DA * AMT) - 2;
  const V = (x) => Math.min(1, (1 - VM) * x + VB);
  const paintGen = function* (W, H, dpr, bref) {
    const cw = Math.round((W + 2 * M) * dpr), ch = Math.round((H + 2 * M) * dpr), bx = W / 2, by = H / 2, r = Math.min(W, H) / 2;
    const mk = () => { const c = document.createElement("canvas"); c.width = cw; c.height = ch; return c; };
    const cp = mk(), ip = cp.getContext("2d").createImageData(cw, ch), pp = ip.data;
    /* the straight run of a capsule (|x| ≤ bx − r, the top / bottom edges) depends on y only: one column computed and copied across */
    const i0 = Math.ceil((M + (W > H ? r : bx)) * dpr), i1 = W > H ? Math.floor((M + W - r) * dpr) - 1 : -1;
    for (let j = 0; j < ch; j++, yield) for (let i = 0; i < cw; i++) {   // one row per step (warm slices it)
      const o = (j * cw + i) * 4;
      if (i1 >= i0 && i > i0 && i <= i1) { const m = (j * cw + i0) * 4; pp[o] = pp[o + 1] = pp[o + 2] = 255; pp[o + 3] = pp[m + 3]; continue; }
      const x = (i + .5) / dpr - M - bx, y = (j + .5) / dpr - M - by, [d, nx, ny] = sdf(x, y, bx, by, r), e = -d, fw = Math.max((Math.abs(nx) + Math.abs(ny)) / dpr, 1e-4);
      const main = Math.min(1, band(e, fw, ny, H1, cs1, b1, -1, CURV) + band(e, fw, ny, H1, cs1, b1, 1, CURV));
      const dk = band(e, fw, ny, DH * H1, csD, bD, -1, 1), df = band(e, fw, ny, DH * H1, csD, bD, 1, 1);
      let out = bref; for (const al of [main, dk, df]) out = (1 - al) * out + al * V(out);   // keyfill §2: three sover emits, V on the current value
      pp[o] = pp[o + 1] = pp[o + 2] = 255; pp[o + 3] = Math.round(sat((out - bref) / (1 - bref)) * 255);
    }
    cp.getContext("2d").putImageData(ip, 0, 0); return cp.toDataURL("image/png");
  };
  const paint = (W, H, dpr, bref) => { const g = paintGen(W, H, dpr, bref); let s; do s = g.next(); while (!s.done); return s.value; };
  const cache = {}, SEL = "nav.tabs .plat, .navbtn";
  const layer = (host) => { let l = host.querySelector(":scope > .ghl");
    if (!l) { l = document.createElement("div"); l.className = "ghl"; l.setAttribute("aria-hidden", "true"); host.appendChild(l); } return l; };
  const draw = (host) => {
    const W = host.offsetWidth, H = host.offsetHeight; if (!W || !H) return;
    const dark = matchMedia("(prefers-color-scheme: dark)").matches, bref = dark ? .13 : .98;
    const dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1)), key = W + "x" + H + "@" + dpr + (dark ? "d" : "l");
    if (host.__ghl === key) return; host.__ghl = key;
    const href = cache[key] || (cache[key] = paint(W, H, dpr, bref));
    layer(host).style.backgroundImage = `url("${href}")`;
  };
  /* 外观 10-01 11:1x: the platter's other widths are painted ahead, at idle, in slices (≤ 5 ms of rows, then the next idle callback) — the first shift of a
     load used to paint the new bar width on the spot (16–31 ms here, 15–24 in glass-hl.js; evidence/外观-1001-切班归因/README.md). The bar's width for n tabs
     = min(n × --ios-tab-button-w + 2 × --ios-tab-button-pad, viewport − 24) (index.html nav.tabs max-width; read 290 for 3 tabs, 370 / 416 for 5 at 394 / 440),
     n = 2…6 (the shifts' tab counts are 3 and 5 in the demo; a game set can differ); the height and the theme are the current ones. */
  const pending = [], idle = (f) => (window.requestIdleCallback ? requestIdleCallback(f, { timeout: 4000 }) : setTimeout(f, 200));
  let warming = false;
  const warmStep = (dl) => { const t0 = performance.now();
    while (pending.length) { const job = pending[0]; if (cache[job.key]) { pending.shift(); continue; }
      if (!job.g) job.g = paintGen(...job.args);
      let s; do s = job.g.next(); while (!s.done && performance.now() - t0 < 5 && (!dl || dl.didTimeout || dl.timeRemaining() > 1));
      if (s.done) { cache[job.key] = s.value; pending.shift(); if (performance.now() - t0 >= 5) break; } else break; }
    if (pending.length) idle(warmStep); else warming = false; };
  const warm = () => { const plat = document.querySelector("nav.tabs .plat"); if (!plat || !plat.offsetHeight) return;
    const cs = getComputedStyle(document.documentElement), bw = parseFloat(cs.getPropertyValue("--ios-tab-button-w")), pad = parseFloat(cs.getPropertyValue("--ios-tab-button-pad"));
    if (!(bw > 0) || !(pad >= 0)) return;
    const cap = document.documentElement.clientWidth - 24, H = plat.offsetHeight;
    for (let n = 2; n <= 6; n++) { const W = Math.round(Math.min(n * bw + 2 * pad, cap)), j = (() => { const dark = matchMedia("(prefers-color-scheme: dark)").matches, dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1)); return { key: W + "x" + H + "@" + dpr + (dark ? "d" : "l"), args: [W, H, dpr, dark ? .13 : .98] }; })(); if (!cache[j.key] && !pending.some((p) => p.key === j.key)) pending.push(j); }
    if (pending.length && !warming) { warming = true; idle(warmStep); } };
  /* hosts are found once at idle (scan) and then only among ADDED nodes (a childList MutationObserver, no attribute watching); show / hide and size changes
     come from the ResizeObserver every host is put in (its first call, and 0 → W when a hidden host shows, draws at once; later size changes wait for the size to
     hold 120 ms). 外观 10-01 10:3x: the old observer watched class / hidden on the whole body and re-ran querySelectorAll + offsetWidth on every host in the next
     frame — 16–52 ms per switch of shift in the phone's long frames (数据 evidence/数据-1001-今早长帧/README.md:23–25). */
  const timers = new WeakMap(), later = (h) => { clearTimeout(timers.get(h)); timers.set(h, setTimeout(() => draw(h), 120)); };
  const hosts = new Set(), seen = new WeakSet();
  const ro = window.ResizeObserver ? new ResizeObserver((es) => { for (const e of es) { const h = e.target; if (!h.isConnected) { hosts.delete(h); ro.unobserve(h); continue; } if (h.__ghl) later(h); else draw(h); } }) : null;
  const add = (h) => { if (seen.has(h)) return; seen.add(h); hosts.add(h); if (ro) ro.observe(h); else if (h.offsetWidth) draw(h); if (h.matches("nav.tabs .plat")) warm(); };   // a new bar (view.js rebuilds it per shift): its other widths are queued if not cached
  const scan = () => { for (const h of document.querySelectorAll(SEL)) add(h); };
  const redrawAll = () => { for (const h of hosts) { if (!h.isConnected) { hosts.delete(h); continue; } if (h.offsetWidth) draw(h); } warm(); };   // the theme: the map depends on it, the size does not change
  const added = (ms) => { for (const m of ms) for (const n of m.addedNodes) { if (n.nodeType !== 1) continue; if (n.matches(SEL)) add(n); if (n.firstElementChild) for (const h of n.querySelectorAll(SEL)) add(h); } };
  const start = () => {
    (window.requestIdleCallback || ((f) => setTimeout(f, 200)))(() => { scan(); warm(); }, { timeout: 1500 });
    const mq = matchMedia("(prefers-color-scheme: dark)"); (mq.addEventListener ? mq.addEventListener("change", redrawAll) : mq.addListener(redrawAll));
    if (window.MutationObserver) new MutationObserver(added).observe(document.body, { childList: true, subtree: true });   // the bar and the pushed pages' buttons appear after load
  };
  window.GlassHL = { paint, scan, hosts, warm, cacheKeys: () => Object.keys(cache), pending: () => pending.map((p) => p.key) };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
