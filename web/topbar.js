/* topbar.js — the navigation bar's scroll behaviour (BOARD.md #4, 2026-09-20): large title → small title, the bar's bottom edge line,
   release snapping and the pull-down stretch, all from remote-ref/nav-bar-scroll-formula.md (§0–§3 decompiled UIKit, §10 probe reads).
   Takes over from view.js's onScroll (--bar / --big / --title); that entry keeps a one-line guard `if (window.Topbar) return;`.
   Geometry (§10, UIProbe largetitle page): the bar rests at 106 and collapses to 54 (_restingHeights [54, 106]); the large-title item's
   preferredHeight p = 52 = restingHeightOfTitleView, layoutMinimumHeight 0 (collapsible), b = 14. On this page the bar (.topbar) is the
   54-pt small bar and the large title (header h1) scrolls in the flow under it, so the collapse range p is measured once at rest:
   p = (h1 bottom) − (bar bottom); the native ratio (52 on a 106/54 bar) is not assumed (§10 note).
   Per scroll (§2.1/§2.4/§2.5): s = content scrolled past rest (1:1 with the finger, clamped to [0, p]); c = p − s;
   progress = c ≥ p − b ? 1 : (c ≤ 0 ? 0 : (c − b) / (p − b)); the switch is binary at progress < 0.05 (⇔ s > 0.95 (p − b)) and each
   title crosses over with a 0.2 s opacity transition (2.5; no translation — §6 item 8); the large title is clipped at the bar's bottom
   edge while it slides under (clipsToBounds, §4 item 1), not faded. Bottom edge line (§3): hidden while the content is at rest at the top
   (shouldHideAtTop), shown once scrolled — its fade, if any, is unread (instant here).
   Release snap (2.8): when a scroll ends inside the collapse range the target is the nearest resting point — midpoint rule; the curve is
   UIScrollView's standard deceleration to it (§2.8b, settle() below).
   Pull-down stretch (2.7): scale = clamp(1 + (h − h_rest) / (displayScale × screenH × 0.66), 1, 1.1) with h − h_rest = the overscroll;
   the title's anchor point for that scale is unread (leading baseline used).
   Unread (left as the old behaviour / untouched): the pocket material (五个闭包), the replay layer, the edge line fade. */
(() => {
  "use strict";
  const root = document.documentElement;
  const bar = document.getElementById("topbar"), h1 = document.querySelector("header h1");
  if (!bar || !h1) return;
  const B = 14, THRESH = 0.05, FADE_S = 0.2, STRETCH_MAX = 1.1, STRETCH_K = 0.66;
  const ZONE_BELOW = 7.67;   // §10b ①: the large-title label box sits 3.67 under the bar zone and 7.67 above the zone's bottom (probe, 34 pt bold label 40.67 tall)
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  let p = 52, restBottom = 0, barBottom = 0, dragging = false, snapping = false, snapRaf = 0, lastTouchEnd = -1e9;
  const api = { snap: true };   // snap: the 2.8 release retarget (accept-topbar.js turns it off while it scrolls programmatically)
  /* 顶栏红 (老网页 09-23; simulator A, 20219fa, ?only=topbar, the probe's per-measure log): the collapse range was read at a scroll event whose
     scrollY was 0 while the FIXED bar's rect still sat at the previous scroll's layout viewport — logged: bar bottom 146 against 116 at rest, the h1
     and the root already at 0 — so p came out 21.89 (other runs 41.89 / 5.89) instead of 51.89, and it held until the next rest at the top: the full
     run's 50.889 vs 51.89 and the 51.4 switch 0.001 pt short. The bar is pinned at the top (top 0 in index.html .topbar), so its bottom is its height;
     the title's document position is read against the root's box from the same layout read (not rect + window.scrollY). */
  let lastMeasure = null;
  const measure = () => {   // the collapse range p and where the bar's bottom edge is (at rest at the top, on load / resize)
    const hr = h1.getBoundingClientRect(), br = bar.getBoundingClientRect(), dt = root.getBoundingClientRect().top;
    barBottom = br.height; restBottom = hr.bottom - dt; p = Math.max(1, restBottom + ZONE_BELOW - barBottom);   // p = the title zone (label box + 7.67) = 52 in the native geometry (§10 / §10b)
    lastMeasure = { y: window.scrollY, barRectBottom: br.bottom, barBottom, p };   // accept-topbar.js: the bar's rect at the read vs the height used
  };
  /* §2.4/§2.5 progress → the two titles' alpha (binary, transitions in CSS) */
  const progressOf = (s) => { const c = p - s; return c >= p - B ? 1 : (c <= 0 ? 0 : (c - B) / (p - B)); };
  const snapTarget = (s) => (s < p / 2 ? 0 : p);   // 2.8: nearest resting point, midpoint rule (s in the collapse range)
  const stretchOf = (over) => clamp(1 + over / (devicePixelRatio * screen.height * STRETCH_K), 1, STRETCH_MAX);   // 2.7 (over = pull-down pt)
  const apply = () => {
    const y = window.scrollY; if (y === 0) measure();   // at rest the geometry is re-read (layout may have changed since load: fonts, data, header content)
    const s = clamp(y, 0, p), inline = s >= p - 0.5 ? 1 : 0;   // §10b ④ (probe): the switch when the zone is fully under the bar (s ≈ 52), not at §2.5's 0.95·(p − b) = 36 — R17 / 老网页 to reconcile; progressOf() kept for the record
    const clip = Math.max(0, barBottom - (restBottom - y - h1.offsetHeight));   // how much of the large title is under the bar (px from its top)
    const st = root.style;
    st.setProperty("--tb-s", s.toFixed(2)); st.setProperty("--tb-small", String(inline)); st.setProperty("--tb-large", String(1 - inline));
    st.setProperty("--tb-clip", Math.min(clip, h1.offsetHeight + 2).toFixed(2) + "px");
    st.setProperty("--tb-edge", y > 0.5 ? "1" : "0"); st.setProperty("--bar", y > 0.5 ? "1" : "0");   // the edge line: 0/1 here, its 0.517 s fade-in curve is in topbar.css (§10b ②)
    st.setProperty("--tb-stretch", "1");   // §10b ③ (probe): the large title does not scale when pulled past the top — it only translates with the content; stretchOf() (2.7) kept for the record
  };
  /* 2.8 release snap curve — nav-bar-scroll-formula.md §2.8b (decompiled, R45): §2.8 only moves the deceleration TARGET to the detent;
     the content then follows UIScrollView's standard deceleration to it: x(t) = target − Δ·r^(1000 t), r = 0.998 per ms
     (_adjustedDecelerationFactor when the velocity change is < .25), time constant ≈ 0.5 s, no overshoot.
     G16 (数据核 2026-09-23 19:42, nav-bar-scroll-formula.md §2.8c; probe tools/uiprobe/g16/g16-scroll-table.txt): the probe's 22-sample table
     with an 11 % overshoot (§10b ④, BAR_T / BAR_P) is NOT a bar animation — no bounds / position animation on UINavigationBar, model = presentation
     every frame, bar height = −contentOffset.y − 62 on all 174 frames: it is the table's own deceleration carrying past the top edge (3.333 pt at
     +816 ms) and coming back, released WITH velocity (−.3747 pt/ms, the last move's velocity kept through a 3 s hold). So the page adds no bar
     overshoot: the large title rides the page's own scroll 1:1 (WebKit's edge bounce is the scroll view's own); this snap starts from a settled
     scroll (velocity 0), where the read chain has no overshoot. The edge-bounce formula (_smoothScrollWithUpdateTime: past the edge) is unread.
     BAR_T / BAR_P stay only as the record of that table, not used. */
  const SNAP_R = 0.998;
  const snapProgress = (ms) => (ms <= 0 ? 0 : 1 - Math.pow(SNAP_R, ms));   // §2.8b: progress = 1 − r^(ms)
  const SNAP_END_MS = Math.ceil(Math.log(0.5 / 200) / Math.log(SNAP_R));   // ≈ 3 s: 200 pt would be within 0.5 pt of the target
  const BAR_T = [0, 39, 73, 140, 173, 206, 239, 273, 306, 339, 373, 406, 439, 473, 506, 539, 573, 606, 639, 673, 706, 739, 773];
  const BAR_P = [0, .115, .278, .506, .712, .842, .962, 1.056, 1.103, 1.111, 1.107, 1.094, 1.081, 1.064, 1.051, 1.043, 1.030, 1.026, 1.017, 1.013, 1.009, 1.009, 1];
  /* 2.8 release snap: only when the scroll settled inside the collapse range and no finger is down */
  const settle = () => {
    if (dragging || snapping || !api.snap || performance.now() - lastTouchEnd > 1500 || (window.__kbdSettling && window.__kbdSettling())) return;   // I3: while view.js settles a field focus / the keyboard it owns the resting point (it applies snapTarget itself, keeping the field visible)   // only after a finger just let go (2.8 is a drag-end retarget); programmatic scrolls (tab tap → top spring) are left alone
    const y = window.scrollY; if (!(y > 0.5 && y < p - 0.5)) return;
    const target = snapTarget(y), t0 = performance.now(), y0 = y;
    snapping = true;
    const f = (now) => {
      const yy = target + (y0 - target) * (1 - snapProgress(now - t0));
      if (Math.abs(yy - target) < 0.5 || now - t0 >= SNAP_END_MS) { window.scrollTo(0, target); snapping = false; apply(); return; }   // §2.8b: exponential approach; done within 0.5 pt
      window.scrollTo(0, yy); snapRaf = requestAnimationFrame(f);
    };
    snapRaf = requestAnimationFrame(f);
  };
  let settleTimer = 0;
  const onScroll = () => { apply(); clearTimeout(settleTimer); if ("onscrollend" in window) return; settleTimer = setTimeout(settle, 120); };
  addEventListener("scroll", onScroll, { passive: true });
  /* ---- R3 the scroll pocket (BOARD round 2; material from the read keys only, A20) ----
     Layers (nav-pocket-sdfdump-2026-09-19.md §1 / §2, the dumps uiprobe-sdf-navpocket-{light,dark}.json; nav-bar-scroll-formula.md §3.3 / §3.4 / §6b):
     ScrollEdgeEffectView 440 × 116 (the status bar 62 + the collapsed bar 54), alpha 0 at rest at the top (shouldHideAtTop) / 1 once scrolled;
     under it, in z-order: the Replay layer — a CABackdropLayer 440 × 116 with backdrop enabled 0 (samples nothing) and a flat gradient white·white
     light / black·black dark, opacity .5 light / .6 dark (§6b: replayLightModeAlpha .5 / replayDarkModeAlpha .6; the dumps' opacity .5 / .6000);
     above it the blur backdrop (scale .5) with filters [variableBlur inputRadius 2 + inputMaskImage 1 × 384 + BlurFill 16 / darken .4 / lighten .6 /
     normal .25 (dark .6 / .4 / 0), colorMatrix diag 1.1969 / 1.0712 / 1.232 with bias .03 (the dump's 4 × 5), sdrNormalize clamp 1 / preserveHue 1];
     a ⅓ pt hairline at the bottom, black α .10 light / white α .10 dark.
     Here: a fixed layer at the top, height = safe-area-top + 54, opacity from --tb-edge (0 at rest, 1 once scrolled); inside it a clone of #app kept
     on the page's pixels (translateY(−scrollY) per scroll, re-cloned when #app's children change) through one SVG filter in the layers' order:
     the flat replay flood composited over the content first (it lies under the blur backdrop, so the backdrop samples it), then the blur
     (feGaussianBlur σ = 2 ÷ .5 = 4 pt: the radius is in samples of the half-resolution capture, the same reading as alert-pipeline-plan §1.3),
     BlurFill as in menu-card-material §7.2 (bf at σ 16 ÷ .5 = 32 pt — 近似 mip, as the read says), the colour matrix, then a hairline element.
     The variable blur's mask: R3′ below (R46 read the 1 × 384 column; wired as the copy's mask-image). Not built: sdrNormalize (a no-op on 8-bit
     values); the status-bar replay layer (elsewhere, unread); backdrop-filter cannot take an SVG filter, hence the clone. */
  const POCKET = { light: { replay: [255, 255, 255, 0.5], blur: 2, scale: 0.5, bf: 16, darken: 0.4, lighten: 0.6, normal: 0.25, matrix: [1.1969, -0.1789, -0.018, 0, 0.03, -0.0531, 1.0712, -0.0181, 0, 0.03, -0.0532, -0.1787, 1.232, 0, 0.03], hairline: [0, 0, 0, 0.1] },
    dark: { replay: [0, 0, 0, 0.6], darken: 0.6, lighten: 0.4, normal: 0, hairline: [255, 255, 255, 0.1] } };
  /* R3′ — the variable blur's inputMaskImage: a 1 × 384 column (R46 read it; nav-bar-scroll-formula.md §3.4a). R3′ wired it as an alpha mask-image; R3″
     (below) reads the shader: the R channel scales the blur LEVEL per row and the fade term is 1 for every row of this mask, so the alpha mask is gone and
     the column drives the level mix (pocketMask() is kept for the record / TopbarPocket.mask.css). The column is stretched over the layer's FULL height —
     R50 (§6c): VariableBlurFilter::render samples the mask through (T · diag(bounds w, h))⁻¹ (0x1c39909a0–0x1c3990a68), row i ↔ y = (i + ½)/384 × H (R3⁗).
     G17 / G31 — the column is GENERATED, not tabled: `_UICreatePocketBlurAndFillMaskImage` 0x1c42ace3c + its getter 0x1c42acba4 (§6d′): t = i / (n − 1);
     per ramp t ≤ start → start value, t ≥ end → end value, else start + (end − start) · ease((t − start)/(end − start)); byte = (int)(v × 255) (truncates);
     ease = kCAMediaTimingFunctionEaseInEaseOut = cubic-bezier(.42, 0, .58, 1); R = ramp 0 (G = ramp 1 ≡ 1, the fill, unused here). The ramp endpoints are
     数据's probe reads of the info block the function stores (remote-ref/tools/uiprobe/uiprobe-g17-pocketinfo-A.json, 模拟器 A, iOS 27.0, 09-23 22:47–49,
     light = dark): portrait after scrolling (440 × 116 backdrop layer) ramp 0 = (0.5344827586206896, 1) → (1, 0.25); landscape (956 × 78) ramp 0 =
     (0.1794871794871795, 1) → (1, 0.25). Which geometric quantity gives the start is not read yet (§6d‴), so the page takes those two read values by
     orientation — no rule is derived from them. This generator (double-precision bisection of the bezier) reproduces all 8 probe columns byte for byte
     (both orientations, the at-rest single ramp too) and the old R46 156-pt table exactly (0 of 384 rows differ). */
  const POCKET_RAMP = { portrait: [0.5344827586206896, 1, 1, 0.25], landscape: [0.1794871794871795, 1, 1, 0.25] }, POCKET_MASK_ROWS = 384;
  const pocketBez = (a, b, s) => 3 * (1 - s) * (1 - s) * s * a + 3 * (1 - s) * s * s * b + s * s * s;
  const pocketEase = (x) => { let lo = 0, hi = 1; for (let k = 0; k < 60; k++) { const m = (lo + hi) / 2; if (pocketBez(0.42, 0.58, m) < x) lo = m; else hi = m; } return pocketBez(0, 1, (lo + hi) / 2); };
  const pocketColumn = ([a0, v0, a1, v1], n = POCKET_MASK_ROWS) => Array.from({ length: n }, (_, i) => { const t = i / (n - 1); return Math.trunc((t <= a0 ? v0 : t >= a1 ? v1 : v0 + (v1 - v0) * pocketEase((t - a0) / (a1 - a0))) * 255); });
  const pocketOrient = () => (matchMedia("(orientation: landscape)").matches ? "landscape" : "portrait");
  const pocketCols = {}; const pocketMaskCol = () => { const o = pocketOrient(); return pocketCols[o] || (pocketCols[o] = pocketColumn(POCKET_RAMP[o])); };
  const pocketMask = () => { const col = pocketMaskCol(), stops = []; for (let i = 0; i < col.length; i++) stops.push(`rgba(0,0,0,${(col[i] / 255).toFixed(4)}) ${((i + 0.5) / col.length * 100).toFixed(3)}%`); return `linear-gradient(to bottom, ${stops.join(", ")})`; };
  const pocketTheme = () => (matchMedia("(prefers-color-scheme: dark)").matches && root.dataset.theme !== "light") || root.dataset.theme === "dark" ? "dark" : "light";
  const pocketKeys = (th) => ({ ...POCKET.light, ...(th === "dark" ? POCKET.dark : {}) });
  const NS = "http://www.w3.org/2000/svg";
  /* R3″ — the pocket blur as the native computes it (default.metallib `variable_blur_frag_lpf` + `variable_blur_downsample_frag_lpf`, QuartzCore
     `VariableBlurFilter::render` 0x1c399060c → `Context::variable_blur_surface` 0x1c39060e8; nav-bar-scroll-formula.md §3.4b):
       r(y)  = 1.6 · inputRadius · (device px/pt · layer scale .5) · mask.R(y)          — max_blur = radius_px × 1.6 (+0x2a0 / 0x1c3bafae0), × the mask's R
       L(y)  = r ≥ 2 ? log2 r : log2(1 + r/2), ≥ 0                                        — the pyramid level read (trilinear), four taps at ±L·¼ texel
       out   = the pyramid at level L: levels built by the 13-tap kernel (centre .1055, ±1.96 axis .0902 ×4, ±1.96 diagonal .0771 ×4, ±3.92 axis .0563 ×4,
               source-level texels, bilinear); BlurFill from the same pyramid at L_fill = log2(1.6 · 16 · px/pt), mask.G = the fill amount (255 → 1);
       fade  = saturate((r − .02)/.08) with inputFade (0x1c3bb13a0/4: .08, −.02) — 1 for every row here (r ≥ 1.19), so the layer's alpha is NOT masked.
     Here: the trilinear level mix per row is exact — three pre-blurred copies (levels 1–3) and the source (level 0), weighted per row by the tent
     weights w_k(y) = max(0, 1 − |L(y) − k|) from a 1 × 384 weights image (R = w0, G = w1, B = w2, w3 = 1 − R − G − B) stretched over the pocket
     (feImage in the copy's coordinates, moved with the scroll); each level's kernel is a Gaussian of the level's measured std (VB_STD, base px:
     the 13-tap chain's phase-averaged impulse response, tools/vb_kernel.py) — 剖面近似, quantified (R3‴, tools/vb_gauss_dev.py): the exact kernel is
     flatter-topped; on a black/white edge the two blurs differ by ≤ .0053 (1.4/255, RMS .0007), on a 1-px line ≤ .0039 — under one 8-bit level. The exact
     kernel per frame would be feConvolveMatrix 19×19 + 37×37 + (73×73 split) ≈ 4700 MAC/px ≈ 2.1 G MAC per scroll frame at 3× (SVG has no downsampling;
     WebGL cannot read the page) — not built. The ±L/4-texel taps (≤ .6 base px) are left out. The BlurFill blur = one Gaussian of the level mix's std at L_fill (the fill is the same pyramid). */
  const VB = { radius: 2, scale: 0.5, fill: 16, k: 1.6, std: [0, 2.147, 4.694, 9.581, 19.263, 38.579, 77.023], maskRows: POCKET_MASK_ROWS };
  const vbLevel = (r) => Math.max(0, r >= 2 ? Math.log2(r) : Math.log2(1 + r / 2));
  const vbMixStd = (L) => { const k = Math.min(Math.floor(L), VB.std.length - 2), f = L - k; return Math.sqrt((1 - f) * VB.std[k] ** 2 + f * VB.std[k + 1] ** 2); };   // the std of a two-level mix
  const vbBase = () => (window.devicePixelRatio || 1) * VB.scale;   // base px per pt of the pyramid (the backdrop capture at layer scale .5)
  const vbMaskR = (row) => pocketMaskCol()[Math.min(Math.max(row, 0), VB.maskRows - 1)] / 255;
  const vbImg = {};
  const vbWeights = () => { const o = pocketOrient(); if (vbImg[o]) return vbImg[o]; const c = document.createElement("canvas"); c.width = 1; c.height = VB.maskRows; const x = c.getContext("2d"); const im = x.createImageData(1, VB.maskRows); const base = vbBase();
    for (let i = 0; i < VB.maskRows; i++) { const L = vbLevel(VB.k * VB.radius * base * vbMaskR(i)); const w = [0, 1, 2].map((k) => Math.max(0, 1 - Math.abs(L - k)));
      im.data[i * 4] = Math.round(w[0] * 255); im.data[i * 4 + 1] = Math.round(w[1] * 255); im.data[i * 4 + 2] = Math.round(w[2] * 255); im.data[i * 4 + 3] = 255; }
    x.putImageData(im, 0, 0); return (vbImg[o] = c.toDataURL("image/png")); };
  const pocketFilter = (th) => { const k = pocketKeys(th); let svg = document.getElementById("topbar-pocket-svg"); if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "topbar-pocket-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    const rp = k.replay, base = vbBase(), sig = [1, 2, 3].map((lv) => VB.std[lv] / base), bfs = vbMixStd(vbLevel(VB.k * VB.fill * base)) / base;
    const sel = (row) => `<feColorMatrix in="wimg" type="matrix" values="${[0, 1, 2].map((c) => (row === c ? "1" : "0")).join(" ")} 0 0  ${[0, 1, 2].map((c) => (row === c ? "1" : "0")).join(" ")} 0 0  ${[0, 1, 2].map((c) => (row === c ? "1" : "0")).join(" ")} 0 0  0 0 0 1 0" result="w${row}"/>`;
    svg.innerHTML = `<filter id="topbar-pocket-f" filterUnits="userSpaceOnUse" x="0" y="0" width="1" height="1" color-interpolation-filters="sRGB" data-theme="${th}" data-sigma="${sig.map((v) => v.toFixed(4)).join(",")}" data-bf-sigma="${bfs.toFixed(4)}" data-base="${base}">`
      + `<feFlood flood-color="rgb(${rp[0]},${rp[1]},${rp[2]})" flood-opacity="${rp[3]}" result="rp"/><feComposite in="rp" in2="SourceGraphic" operator="over" result="src"/>`   // the Replay layer under the blur backdrop
      + `<feGaussianBlur in="src" stdDeviation="${sig[0]}" result="b1"/><feGaussianBlur in="src" stdDeviation="${sig[1]}" result="b2"/><feGaussianBlur in="src" stdDeviation="${sig[2]}" result="b3"/>`
      + `<feImage href="${vbWeights()}" preserveAspectRatio="none" x="0" y="0" width="1" height="1" result="wimg"/>` + sel(0) + sel(1) + sel(2)
      + `<feColorMatrix in="wimg" type="matrix" values="-1 -1 -1 0 1  -1 -1 -1 0 1  -1 -1 -1 0 1  0 0 0 1 0" result="w3"/>`
      + `<feBlend in="src" in2="w0" mode="multiply" result="p0"/><feBlend in="b1" in2="w1" mode="multiply" result="p1"/><feBlend in="b2" in2="w2" mode="multiply" result="p2"/><feBlend in="b3" in2="w3" mode="multiply" result="p3"/>`
      + `<feComposite in="p0" in2="p1" operator="arithmetic" k2="1" k3="1" result="s01"/><feComposite in="s01" in2="p2" operator="arithmetic" k2="1" k3="1" result="s012"/><feComposite in="s012" in2="p3" operator="arithmetic" k2="1" k3="1" result="blur"/>`
      + `<feGaussianBlur in="src" stdDeviation="${bfs}" result="bf"/>`
      + `<feBlend in="blur" in2="bf" mode="darken" result="mn"/><feBlend in="blur" in2="bf" mode="lighten" result="mx"/>`
      + `<feComposite in="mn" in2="mx" operator="arithmetic" k2="${k.darken}" k3="${k.lighten}" result="dl"/><feComposite in="dl" in2="blur" operator="arithmetic" k2="1" k3="${1 - k.darken - k.lighten}" result="bfo"/>`
      + `<feComposite in="bfo" in2="bf" operator="arithmetic" k2="${1 - k.normal}" k3="${k.normal}" result="c"/>`
      + `<feColorMatrix in="c" type="matrix" values="${k.matrix.join(" ")} 0 0 0 1 0" result="cm"/></filter>`; return k; };
  /* the filter region and the weights image follow the pocket's box in the copy's own coordinates (the copy is translated by top0 − scrollY after
     the filter, so the pocket's rows sit at y = scrollY − top0 … + H in the copy): set per scroll */
  const pocketRegion = () => { const f = document.getElementById("topbar-pocket-f"); if (!f || !pocket.copy || !pocket.el) return; const H = pocket.el.offsetHeight, W = pocket.copy.offsetWidth, y = window.scrollY - pocket.top0, m = Math.ceil(3 * (VB.std[6] / vbBase()));   // margin = 3 σ of the widest blur
    f.setAttribute("x", String(-m)); f.setAttribute("y", String(y - m)); f.setAttribute("width", String(W + 2 * m)); f.setAttribute("height", String(H + 2 * m));
    const im = f.querySelector("feImage"); if (im) { im.setAttribute("x", "0"); im.setAttribute("y", String(y)); im.setAttribute("width", String(W)); im.setAttribute("height", String(H)); } };
  const pocket = { el: null, copy: null, hair: null, theme: null, main: document.getElementById("app") };
  const pocketBuild = () => { if (!pocket.main) return; const th = pocketTheme(); const k = pocketFilter(th);
    if (!pocket.el) { pocket.el = document.createElement("div"); pocket.el.className = "topbar-pocket"; pocket.el.setAttribute("aria-hidden", "true"); pocket.hair = document.createElement("i"); pocket.hair.className = "topbar-pocket-hair"; document.body.appendChild(pocket.el); }
    if (pocket.copy) pocket.copy.remove(); const copy = pocket.main.cloneNode(true); copy.removeAttribute("id"); copy.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); copy.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim, nav.tabs").forEach((e) => e.remove()); copy.className = "topbar-pocket-copy"; copy.inert = true;
    const mr = pocket.main.getBoundingClientRect(); copy.style.cssText = `position:absolute;left:${mr.left}px;top:0;width:${mr.width}px;min-height:${Math.max(mr.height, innerHeight)}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor};filter:url(#topbar-pocket-f)`;   // the page colour under #app (R57′: #app paints no background; a transparent-backed copy blurs to α < 1) /* R3″: no alpha mask — the mask scales the blur level per row inside the filter (fade ≡ 1 for this mask); the replay fill stays under it (the pocket's own background below) */
    const rp = k.replay; pocket.el.style.background = `rgba(${rp[0]},${rp[1]},${rp[2]},${rp[3]})`;   /* the Replay layer: a flat fill over the content, under the blur layer (§6b), not masked */ pocket.el.appendChild(copy); pocket.el.appendChild(pocket.hair); pocket.copy = copy; pocket.theme = th; pocket.top0 = mr.top + window.scrollY;
    const h = k.hairline; pocket.hair.style.background = `rgba(${h[0]},${h[1]},${h[2]},${h[3]})`; pocketPlace(); };
  const pocketPlace = () => { if (!pocket.copy) return; pocket.copy.style.transform = `translateY(${(pocket.top0 - window.scrollY).toFixed(2)}px)`; pocketRegion(); };
  const pocketObs = new MutationObserver(() => { clearTimeout(pocket.t); pocket.t = setTimeout(pocketBuild, 60); });
  if (pocket.main) { pocketBuild(); pocketObs.observe(pocket.main, { childList: true, subtree: true, characterData: true }); addEventListener("scroll", pocketPlace, { passive: true }); try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", pocketBuild); matchMedia("(orientation: landscape)").addEventListener("change", pocketBuild); } catch (e) {} }   // the mask column is per orientation (G17)
  window.TopbarPocket = { keys: pocketKeys, theme: pocketTheme, rebuild: pocketBuild, get el() { return pocket.el; }, get top0() { return pocket.top0; }, mask: { rows: POCKET_MASK_ROWS, ramps: POCKET_RAMP, column: pocketColumn, orient: pocketOrient, get values() { return pocketMaskCol().slice(); }, css: pocketMask }, vb: { ...VB, level: vbLevel, mixStd: vbMixStd, base: vbBase, maskR: vbMaskR, weights: vbWeights, region: pocketRegion } };
  if ("onscrollend" in window) addEventListener("scrollend", () => { if (!dragging) settle(); });
  addEventListener("touchstart", () => { dragging = true; if (snapping) { cancelAnimationFrame(snapRaf); snapping = false; } }, { passive: true });
  addEventListener("touchend", () => { dragging = false; lastTouchEnd = performance.now(); }, { passive: true }); addEventListener("touchcancel", () => { dragging = false; lastTouchEnd = performance.now(); }, { passive: true });
  addEventListener("resize", () => { measure(); apply(); });
  addEventListener("load", () => { measure(); apply(); });   // the stylesheets are all in effect by then (a late topbar.css would leave p from index.html's geometry)
  /* p used to be re-read only at scrollY 0 (apply), on resize and on load: a layout change while the page was scrolled left it stale until the next
     return to the top — 老网页's run of 0fe960c on 模拟器 A (OPEN.md 09-23 18:50) read p 50.889 against a geometry of 51.889 (the switch rows then
     missed by that 1 pt), and accept-topbar's own note has 51.89 vs 52.406 in a dark run. The formula is scroll-invariant (模拟器 B, WebKit: 51.889 at
     scrollY 0 / 1 / 5 / 20 / 40 / 52 / 60 / 200; the pull-down scale keeps the title's bottom, transform-origin 0 100%), so any size change of the
     title, its header or the bar re-measures at once. What moved it on A was measured afterwards (老网页, the probe's per-measure log): not a size change
     but the fixed bar's rect lagging one layout viewport at a scroll event — measure() above now reads the bar's height, so a re-measure while scrolled is exact */
  if (window.ResizeObserver) { const ro = new ResizeObserver(() => { measure(); apply(); }); for (const el of [h1, h1.closest("header"), bar]) if (el) ro.observe(el, { box: "border-box" }); }
  if (document.fonts) document.fonts.addEventListener("loadingdone", () => { measure(); apply(); });
  measure(); apply();
  Object.assign(api, { measure, apply, progressOf, snapTarget, snapProgress, stretchOf, B, THRESH, FADE_S, ZONE_BELOW, SNAP_R, BAR_T, BAR_P }); Object.defineProperty(api, "p", { get: () => p }); Object.defineProperty(api, "lastMeasure", { get: () => lastMeasure }); window.Topbar = api;
})();
