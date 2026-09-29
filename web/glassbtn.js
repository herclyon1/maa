/* glassbtn.js — the round glass buttons' press (返回 .pnav .navbtn.pback, ✕ #discard and ✓ #save in the editing top bar): the lift of the box, the
   icon's alpha, and the 70 pt release rule (BOARD.md #5, R4, R71′; night batch: scale and timing only — the state-3 material and the glow are unread
   and untouched). The three buttons are 44 × 44 (tokens.css --ios-nav-button; the accept checks it).
   Basis:
   · glass-button-press-formula.md §0 / §2: the glass is `flexible` → _UIFlexInteraction; the lift target L = (min(W, H) + 16) / min(W, H)
     (liftScalePoints 16: 44 → 60, × 1.3636); the touch is a tap when the finger lifts within 70 pt of the button (state-tables/button.md, spec §4).
   · §7 (R11a): the press changes no material key — the SDF element grows 44 × 44 r 22 → 60 × 60 r 30 (the circle keeps its shape) and the icon's
     UIImageView alpha goes 1 → .2 while its wrapper scales × 1.3636. So the box is driven, not a transform: width / height = 44·x, margins
     −(44·x − 44)/2 keep the centre; the glyph (::before) scales by --gb-scale.
   · §7c (R71, 数据 probe: tracecls _UIModernBarButton + anims, 60 Hz, two recordings): the geometry is a per-frame model write with NO CAAnimation
     (the anims command read 0 animations at +127 / +328 / +627 while held and none for the geometry after the up), so its curve is the probe's frames
     and nothing else — the §7b spring ζ .625 / .262 was a fit and is withdrawn. Lift (width 32 → …, t from the down): +52.6 still 32, +69.3 34.48,
     +102.6 39.36, +136 42.6, +169 44.05, +202.6 44.48 (peak × 1.390), +236 44.26, +336 43.61, then held 43.6 (× 1.3636 = L). Release (t from the up):
     +19 unchanged, +36 42.37, +69 40.92, +103 37.3, +136 33.36, +169 30.88, +203 29.25, +236 28.78 (trough × .899), +353 30.1, +386 31.13, +453 32.89,
     +653 31.76, ≈ +800 32. The icon: alpha 1 → .2 with no transition (the first frame after the down, +19.3 ms, is already .2), and on the up ONE
     CABasicAnimation opacity .2 → 1, duration .47 s, timingFunction default (.25, .1, .25, 1), beginTime = up + 11.7 ms (read twice: 12.7 / 11.7).
   The tables are followed by linear interpolation between adjacent probe frames (the value between two frames is not read).
   §7d (R81, 数据 probe: 60 / 120 ms taps and a re-press mid-fall): ① a tap whose up comes before the first grown frame (+69.3) never lifts — the
   geometry stays 32 and only the icon drops to .2 for a frame and fades back (fade begin up + 21.5); ② a release mid-lift: the lift keeps rising ≈ 30 ms
   (one to two frames) after the up (120 ms tap: 41.51 = × 1.297 at up + 30), then falls on the release table's own timeline from that value — the
   trough comes at the same up + 230…236 and its depth follows the start (× .917 from 41.5, × .899 from 43.6) — drawn here as the release table scaled
   to the value at the reversal (k chosen for continuity at up + 30); ③ a re-press mid-fall: the icon returns to .2 within a frame (the fade withdrawn),
   the geometry keeps falling until the lift table's start (the probe: trough down₂ + 38, first grown frame down₂ + 71 = the from-rest +69.3) and then
   re-lifts from the current value on the lift table's timeline — peak × 1.385 at down₂ + 204 from 34.14 = exactly the table scaled to the remaining
   excursion (34.14/32 + .39·(1.3636 − 1.067)/.3636 = 1.385), settling at 43.6; ④ the fade's begin was read 21.5 / 25.3 / 17.6 / 11.3 ms after the up
   (§7c: 12.7 / 11.7) — the first read, 11.7, is kept (the spread is noted, not averaged).
   Unread, left out: the flex stretch while dragging (§2 "按住拖动"; the ultraSmall parameters are read — flex-interaction.md §2, pts 10 / N 10000 / .9–1.1 / T 2000 — but which of §3's terms the glass button takes (preferredFlexSources) and its internalTranslation are not) — the scale stays at L while held; the state-3
   material key. The glow is drawn (P0a, §7e — see the block above GLOW). Without Motion
   (motion.js: click / swallowNextClick) nothing is installed.
   The click: the page's own handlers stay on the buttons; a release inside 70 pt fires Motion.click(el) (the browser's own click for the touch is
   swallowed, B14's rule), a release outside fires nothing (the browser's click — the button holds pointer capture — is swallowed too). */
(function () {
  if (!window.Motion || typeof Motion.click !== "function") return;
  const SEL = ".pnav .navbtn, .topbar .navbtn";
  const LIFT_PT = 16, SLOP = 70, W_TRACE = 32;   // W_TRACE: the traced layer's resting width (§7c: _UIModernBarButton presentation 32 → 43.6)
  /* §7c frames as [ms, scale = width / 32]; the held value is L itself (43.6 / 32 = 1.3625 read, = the §2 formula's 1.3636 within the trace's precision) */
  const LIFT_T = [[52.6, 1], [69.3, 34.48 / W_TRACE], [102.6, 39.36 / W_TRACE], [136, 42.6 / W_TRACE], [169, 44.05 / W_TRACE], [202.6, 44.48 / W_TRACE], [236, 44.26 / W_TRACE], [336, 43.61 / W_TRACE], [353, 60 / 44]];
  const REL_T = [[0, 60 / 44], [19, 60 / 44], [36, 42.37 / W_TRACE], [69, 40.92 / W_TRACE], [103, 37.3 / W_TRACE], [136, 33.36 / W_TRACE], [169, 30.88 / W_TRACE], [203, 29.25 / W_TRACE], [236, 28.78 / W_TRACE], [353, 30.1 / W_TRACE], [386, 31.13 / W_TRACE], [453, 32.89 / W_TRACE], [653, 31.76 / W_TRACE], [800, 1]];
  const LIFT_START = LIFT_T[0][0], LIFT_FIRST = LIFT_T[1][0], REVERSE_MS = 30, ICON_ALPHA_HELD = 0.2, ICON_BACK = { delay: 11.7, duration: 470, curve: "cubic-bezier(0.25, 0.1, 0.25, 1)" };   // LIFT_FIRST: the first grown frame (an up before it: no lift, §7d ①); REVERSE_MS: the lift runs on ≈ 30 ms past the up (§7d ②)
  const interp = (T, t) => { if (t <= T[0][0]) return T[0][1]; for (let i = 1; i < T.length; i++) { if (t <= T[i][0]) { const [t0, v0] = T[i - 1], [t1, v1] = T[i]; return v0 + (v1 - v0) * (t - t0) / (t1 - t0); } } return T[T.length - 1][1]; };
  const L_END = 60 / 44;   // the tables' held / start value (a 44 button): other sizes scale the tables' excursion by (L − 1) / (L_END − 1)
  const liftAt = (t, from = 1, L = L_END) => from + (interp(LIFT_T, t) - 1) * (L - from) / (L_END - 1);   // from 1 the table itself; from a mid-release value the same shape over what is left (待读)
  const releaseAt = (t, from = L_END) => 1 + (interp(REL_T, t) - 1) * (from - 1) / (L_END - 1);          // from L the table itself; from a mid-lift value the same shape scaled (待读)
  const live = new Map();   // el → { phase: "hold" | "release", x, from, L, t0, raf, w0, h0, ... }
  const L = (el) => { const r = el.getBoundingClientRect(), m = Math.min(r.width, r.height); return m > 0 ? (m + LIFT_PT) / m : 1; };
  /* the 70 pt margin is around the control's bounds, not the scaled presentation: centre from the (transformed) rect — the origin is the centre, so it
     does not move — and the half-sizes from the layout box (offsetWidth / Height are untransformed) */
  const inside = (el, x, y) => { const r = el.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2, hw = el.offsetWidth / 2, hh = el.offsetHeight / 2;
    return x >= cx - hw - SLOP && x <= cx + hw + SLOP && y >= cy - hh - SLOP && y <= cy + hh + SLOP; };
  /* The glow (P0a; glass-button-press-formula.md §7b / §7e, the data session's probe 09-23 16:5x). The held button gets _UIFlexInteractionGlowContainerView (the
     box, clipsToBounds, allowsGroupBlending 0) with BigGlow (a white view filling it) and LittleGlow (66 × 66 in the 44 box's space = 150 %, centred;
     the glow IS its CA shadow: pill, shadowRadius 33 = its half-width, opacity 1, white). Both carry a backdrop-aware vibrantColorMatrix, and such a
     filter uses only the layer's α: out = (1 − α)·B + α·clamp(M·B + bias) (keyfill-highlight.md §2) — in CSS an element with only a backdrop-filter
     (M·B + bias) and its opacity / mask as α. The matrices, split from the probe's values by row sums only (§7e): BigGlow saturate(1.2) contrast(.90909)
     brightness(1.1) (= S(1.2) + .05), LittleGlow saturate(1.5) brightness(1.6667) light / brightness(4) dark (dodge .4 / .75 folded in: 1/(1 − dodge)).
     LittleGlow's α = a circle of radius R convolved with a Gaussian σ = R (keyfill §5.2c, pill → the analytic form): α(u) = P(|N(u, 1)| ≤ 1), u = r / R,
     centre 1 − e^−½ = .3935 — drawn per pixel into a mask. Clip (§7e, 4th read): the portal #58's mask is the platform's SDF circle of the held button
     (60 × 60 r 30), so the glow is clipped to the button's circle. Timing = the probe's presentation frames (no CAAnimation on either layer; linear
     between frames like the geometry tables), t from the down / up: BigGlow uiprobe-motion-glass3-bigglow.json (2nd recording), LittleGlow
     uiprobe-motion-glass3-littleglow.json (opacity and, on the release, scale 1 → 4).
     Placement: in Chrome a backdrop-filter inside the button sees only the button's own paint, not the glass under it (the button has a backdrop-filter,
     so it is the backdrop root — measured headless 09-23 17:0x); the glow is therefore a sibling laid over the button. Deviation, noted: natively the
     icon is drawn above the glow (held json: the image view #38–43 comes after the glow container #32 inside the portal's source), here the icon under the
     glow is brightened too.
     Unread: a release before the glow reached 1 and a re-press during its fade — the tables are scaled from the value at that moment, as the geometry's are. */
  const BIG_IN = [[23.5, 0], [56.9, .4409], [74, .7215], [90, .8734], [107, .9454], [124, .9773], [140, .9908], [157, 1]];
  const BIG_OUT = [[23.5, 1], [40.2, .9756], [57, .9251], [74, .8588], [90, .7845], [107, .7076], [124, .6318], [140, .5594], [157, .4917], [174, .4297], [190, .3735], [207, .3233], [224, .2787], [240, .2394], [257, .2050], [274, .1750], [290, .1491], [307, .1267], [324, .1074], [340, .0909], [357, .0768], [374, .0648], [390, .0546], [407, .0459], [424, .0386], [440, .0324], [457, .0271], [474, .0227], [490, .0190], [507, .0159], [524, .0133], [540, .0111], [557, .0092], [574, .0077], [590, .0064], [607, .0053], [624, 0]];
  const LIT_IN = [[74.4, 0], [91.1, .5698], [107.7, .7948], [124.4, .9089], [141.1, .9614], [157.8, .9841], [174.4, .9936], [191.1, 1]];
  const LIT_OUT = [[24.4, 1, 1], [41.1, .9847, 1.0459], [57.7, .9396, 1.1811], [74.4, .8765, 1.3706], [91, .8036, 1.5892], [107.7, .727, 1.819], [124.4, .6506, 2.0481], [141.1, .5772, 2.2685], [157.7, .5082, 2.4753], [174.4, .4448, 2.6657], [191.1, .3871, 2.8386], [207.7, .3354, 2.9939], [224.4, .2894, 3.1319], [241.1, .2488, 3.2537], [257.7, .2132, 3.3604], [274.4, .1822, 3.4535], [291.1, .1553, 3.5342], [307.7, .132, 3.6039], [324.4, .112, 3.664], [341.1, .0949, 3.7154], [357.8, .0802, 3.7595], [374.4, .0677, 3.797], [391.1, .057, 3.8289], [407.7, .048, 3.8561], [424.4, .0403, 3.879], [441.1, .0338, 3.8985], [457.7, .0284, 3.9149], [474.4, .0238, 3.9287], [491.1, .0199, 3.9404], [507.7, .0166, 3.9501], [524.4, .0139, 3.9584], [541.1, .0116, 3.9653], [557.8, .0097, 3.971], [574.4, .008, 3.9759], [591.1, .0067, 3.9799], [607.7, .0056, 3.9833], [624.4, 0, 3.9861]];
  const LIT_OUT_A = LIT_OUT.map((r) => [r[0], r[1]]), LIT_OUT_S = LIT_OUT.map((r) => [r[0], r[2]]), GLOW_END = 624.4;
  /* α(u) of the shadow: ∫₀¹ ρ e^−(ρ² + u²)/2 I₀(uρ) dρ (the disc of radius 1 under a unit Gaussian centred u away), Simpson on 100 steps (the table is built once, when the page is idle) */
  const I0 = (x) => { let s = 1, term = 1; for (let k = 1; k < 12; k++) { term *= (x / 2) * (x / 2) / (k * k); s += term; } return s; };
  const glowAlpha = (u) => { const n = 100, h = 1 / n; let acc = 0; for (let i = 0; i <= n; i++) { const r = i * h, f = r * Math.exp(-(r * r + u * u) / 2) * I0(u * r); acc += f * (i === 0 || i === n ? 1 : i % 2 ? 4 : 2); } return acc * h / 3; };
  let maskURL = "";
  const glowMask = () => { if (maskURL) return maskURL; const N = 256, c = document.createElement("canvas"); c.width = c.height = N; const g = c.getContext("2d"), im = g.createImageData(N, N);
    const tab = []; for (let i = 0; i <= 1024; i++) tab.push(glowAlpha(i * Math.SQRT2 / 1024));   // u 0 … √2 (the canvas spans the layer, u ∈ [−1, 1] on each axis)
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) { const u = Math.hypot((x + .5) / (N / 2) - 1, (y + .5) / (N / 2) - 1), f = u / Math.SQRT2 * 1024, i = Math.min(1023, Math.floor(f)), a = tab[i] + (tab[i + 1] - tab[i]) * (f - i), o = (y * N + x) * 4;
      im.data[o] = im.data[o + 1] = im.data[o + 2] = 255; im.data[o + 3] = Math.round(a * 255); }
    g.putImageData(im, 0, 0); maskURL = c.toDataURL(); return maskURL; };
  const glows = new Map();   // el → { node, big, little, phase, t0, bFrom, lFrom, b, l, s, raf }
  const glowAt = (phase, t, bFrom = 0, lFrom = 0) => phase === "hold"
    ? { b: bFrom + (1 - bFrom) * interp(BIG_IN, t), l: lFrom + (1 - lFrom) * interp(LIT_IN, t), s: 1 }
    : { b: bFrom * interp(BIG_OUT, t), l: lFrom * interp(LIT_OUT_A, t), s: interp(LIT_OUT_S, t) };
  const glowPlace = (el, g) => { const st = live.get(el), x = st ? st.x : 1, w = g.w0 * x, h = g.h0 * x, n = g.node.style; n.left = (g.x0 - (w - g.w0) / 2) + "px"; n.top = (g.y0 - (h - g.h0) / 2) + "px"; n.width = w + "px"; n.height = h + "px"; };
  const glowTick = (el) => (now) => { const g = glows.get(el); if (!g) return; const t = now - g.t0, v = glowAt(g.phase, t, g.bFrom, g.lFrom);
    g.b = v.b; g.l = v.l; g.s = v.s; g.t = t; glowPlace(el, g); g.big.style.opacity = v.b.toFixed(4); g.little.style.opacity = v.l.toFixed(4); g.little.style.transform = `translate(-50%, -50%) scale(${v.s.toFixed(4)})`;
    if (g.phase === "release" && t >= GLOW_END) { glowStrip(el); return; }
    g.raf = requestAnimationFrame(glowTick(el)); };
  const glowDown = (el, now) => { let g = glows.get(el);
    if (!g) { const node = document.createElement("gb-glow"); node.className = "gb-glow"; node.setAttribute("aria-hidden", "true"); node.innerHTML = '<gb-big class="gb-big"></gb-big><gb-little class="gb-little"></gb-little>';   // own tag names: the bars' "span" rules (the top bar's title) must not reach them
      const little = node.lastChild; little.style.webkitMaskImage = little.style.maskImage = `url(${glowMask()})`; el.after(node); g = { node, big: node.firstChild, little, b: 0, l: 0, s: 1, raf: 0 }; glows.set(el, g); }
    { const st = live.get(el), ml = parseFloat(el.style.marginLeft) || 0, mt = parseFloat(el.style.marginTop) || 0; g.x0 = el.offsetLeft - ml; g.y0 = el.offsetTop - mt; g.w0 = st ? st.w0 : el.offsetWidth; g.h0 = st ? st.h0 : el.offsetHeight; }   // the resting box, read once: the frames place the glow from the geometry's own x (no layout read per frame)
    if (g.raf) cancelAnimationFrame(g.raf);
    g.phase = "hold"; g.t0 = now; g.bFrom = g.b; g.lFrom = g.l; g.raf = requestAnimationFrame(glowTick(el)); };
  const glowUp = (el, now) => { const g = glows.get(el); if (!g) return; if (g.raf) cancelAnimationFrame(g.raf); g.phase = "release"; g.t0 = now; g.bFrom = g.b; g.lFrom = g.l; g.raf = requestAnimationFrame(glowTick(el)); };
  const glowStrip = (el) => { const g = glows.get(el); if (!g) return; if (g.raf) cancelAnimationFrame(g.raf); g.node.remove(); glows.delete(el); };
  (window.requestIdleCallback || ((f) => setTimeout(f, 1500)))(() => glowMask());   // the mask (≈ 100k ops) off the first press
  const GLOW = { built: true, bigGlow: { filter: "saturate(1.2) contrast(.90909) brightness(1.1)" }, littleGlow: { size: "150 %", filter: { light: "saturate(1.5) brightness(1.6667)", dark: "saturate(1.5) brightness(4)" }, alphaCentre: 1 - Math.exp(-.5) },
    clip: "the button's circle (#58 mask: SDF 60 × 60 r 30)", deviation: "icon brightened (natively above the glow)" };
  const box = (el, st, x) => { const w0 = st.w0, h0 = st.h0;
    el.style.width = (w0 * x) + "px"; el.style.height = (h0 * x) + "px"; el.style.marginLeft = (-(w0 * x - w0) / 2) + "px"; el.style.marginTop = (-(h0 * x - h0) / 2) + "px";
    el.style.setProperty("--gb-scale", String(x)); };
  const clear = (el) => { for (const k of ["width", "height", "margin-left", "margin-top", "--gb-scale"]) el.style.removeProperty(k); };
  /* the icon: .2 at once on the down (no animation, §7c), back to 1 on the up along the read CABasicAnimation — .47 s on the default timing function
     (.25, .1, .25, 1) beginning up + 11.7 ms — written per frame by the release loop (a CSS transition toggled by a class did not start in Chrome) */
  const bez = (x1, y1, x2, y2) => (x) => { if (x <= 0) return 0; if (x >= 1) return 1; let lo = 0, hi = 1; for (let i = 0; i < 30; i++) { const s = (lo + hi) / 2, xs = 3 * (1 - s) * (1 - s) * s * x1 + 3 * (1 - s) * s * s * x2 + s * s * s; if (xs < x) lo = s; else hi = s; } const s = (lo + hi) / 2; return 3 * (1 - s) * (1 - s) * s * y1 + 3 * (1 - s) * s * s * y2 + s * s * s; };
  const ICON_CURVE = bez(0.25, 0.1, 0.25, 1);
  const iconAt = (t) => t <= ICON_BACK.delay ? ICON_ALPHA_HELD : ICON_ALPHA_HELD + (1 - ICON_ALPHA_HELD) * ICON_CURVE((t - ICON_BACK.delay) / ICON_BACK.duration);   // t ms from the up
  const iconHeld = (el) => { el.style.setProperty("--gb-icon-alpha", String(ICON_ALPHA_HELD)); };
  const iconSet = (el, a) => { const st = live.get(el); if (st) st.icon = Math.min(1, a); if (a >= 1) el.style.removeProperty("--gb-icon-alpha"); else el.style.setProperty("--gb-icon-alpha", a.toFixed(4)); };
  /* the geometry of a frame (§7c tables, §7d transitions):
       hold     — from the down: until the lift table's start a re-press keeps the previous fall (st.prevRel: the release it interrupted, on its own up clock),
                  then liftAt from the value at that moment (st.from is set on the first lifting frame)
       release  — from the up: a lift still in progress runs on for REVERSE_MS, then the release table scaled by k (continuity at the reversal); a
                  settled hold (x at L) takes the table as is from the up (k 1) */
  const relValue = (rel, tUp) => 1 + (interp(REL_T, tUp) - 1) * rel.k;
  const tick = (el) => (now) => { const st = live.get(el); if (!st) return;
    const t = now - st.t0; st.tLast = t;   // the table's own time: from the down (hold) or from the up (release); a frame stamped before the origin reads the table's first value
    if (st.phase === "hold") {
      if (st.prevRel && t < LIFT_START) { st.x = relValue(st.prevRel, now - st.prevRel.upAt); box(el, st, st.x); st.raf = requestAnimationFrame(tick(el)); return; }   // §7d ③: the fall goes on until the lift table's start
      if (st.prevRel) { st.liftFrom = st.x; st.prevRel = null; }   // the re-lift starts from the value the fall reached (the table scaled to what is left)
      st.x = liftAt(t, st.liftFrom, st.L); box(el, st, st.x); st.raf = requestAnimationFrame(tick(el)); return; }
    /* release */
    if (st.rising && t < REVERSE_MS) { st.x = liftAt(now - st.downAt, st.liftFrom, st.L); box(el, st, st.x); iconSet(el, iconAt(t)); st.raf = requestAnimationFrame(tick(el)); return; }   // §7d ②: the lift runs on ≈ 30 ms past the up
    if (st.rising) { const T = interp(REL_T, t); st.k = Math.abs(T - 1) > 1e-6 ? (st.x - 1) / (T - 1) : (st.x - 1) / (st.L - 1); st.rising = false; }   // k: the release table scaled to meet the value at the reversal (from 43.6 this is 1)
    if (st.k === 0) { st.x = 1; clear(el); } else { st.x = relValue(st, t); box(el, st, st.x); }   // k 0 (§7d ①: never lifted): the geometry keeps its resting box, only the icon runs
    iconSet(el, iconAt(t));
    if (t >= REL_T[REL_T.length - 1][0]) { st.x = 1; clear(el); iconSet(el, 1); live.delete(el); return; }
    st.raf = requestAnimationFrame(tick(el)); };
  const run = (el, st) => { if (st.raf) cancelAnimationFrame(st.raf); st.raf = requestAnimationFrame(tick(el)); };
  const down = (el, e) => {
    const prev = live.get(el), now = performance.now();
    if (prev && prev.raf) cancelAnimationFrame(prev.raf);
    const w0 = prev ? prev.w0 : el.offsetWidth, h0 = prev ? prev.h0 : el.offsetHeight, m0 = Math.min(w0, h0);   // the RESTING box (a re-press finds the box scaled: L from the rect would be wrong)
    const st = { phase: "hold", x: prev ? prev.x : 1, from: prev ? prev.x : 1, liftFrom: prev ? prev.x : 1, L: m0 > 0 ? (m0 + LIFT_PT) / m0 : 1, w0, h0, t0: now, downAt: now, raf: 0, pointerId: e.pointerId, in: true, fx: e.clientX, fy: e.clientY, timer: 0,
      prevRel: prev && prev.phase === "release" ? { upAt: prev.upAt, k: prev.k == null ? (prev.from - 1) / (L_END - 1) : prev.k } : null };   // x: the scale; fx / fy: the finger; prevRel: the fall this press interrupts (§7d ③: it goes on until the lift table's start)
    live.set(el, st); iconHeld(el); glowDown(el, now);   // the icon: .2 within a frame, a running fade withdrawn (§7d ③)
    /* the lift's first frame is LIFT_T[0] (+52.6 still resting, +69.3 the first grown frame): the loop starts at the table's first knot; a re-press mid-fall keeps
       the fall running until then (the loop runs from now) */
    if (prev) run(el, st); else st.timer = setTimeout(() => { st.timer = 0; if (live.get(el) === st && st.phase === "hold") run(el, st); }, LIFT_START);
    const move = (ev) => { if (ev.pointerId !== st.pointerId) return; st.fx = ev.clientX; st.fy = ev.clientY; st.in = inside(el, ev.clientX, ev.clientY); };
    const detach = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", cancel); };
    st.detach = detach;
    const end = (ev, cancelled) => { if (ev.pointerId !== st.pointerId) return;
      detach();
      const hit = !cancelled && inside(el, ev.clientX, ev.clientY);
      if (st.timer) { clearTimeout(st.timer); st.timer = 0; }   // released before the lift began: nothing lifted, nothing to bring back
      const tHeld = performance.now() - st.downAt;
      const noLift = !st.raf || (tHeld < LIFT_FIRST && !st.prevRel);   // §7d ①: an up before the first grown frame (+69.3) never lifts — the geometry stays at rest
      if (noLift) { st.x = 1; clear(el); }
      const settled = Math.abs(st.x - st.L) < .002 && tHeld > LIFT_T[LIFT_T.length - 1][0];
      st.phase = "release"; st.t0 = performance.now(); st.upAt = st.t0; st.from = st.x; st.k = noLift ? 0 : (settled ? 1 : null); st.rising = !noLift && !settled;   // rising: the lift runs on REVERSE_MS, then k by continuity (§7d ②)
      if (st.prevRel) st.prevRel = null;
      glowUp(el, st.t0);
      run(el, st);   // the release loop: the box along REL_T (nothing to move when k is 0) and the icon's alpha along iconAt, to +800
      Motion.swallowNextClick(el);   // the browser's click for this touch (the button holds the capture, so it comes wherever the finger lifted)
      if (hit) Motion.click(el); };
    const up = (ev) => end(ev, false), cancel = (ev) => end(ev, true);
    el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", cancel);
    try { el.setPointerCapture(e.pointerId); } catch {}
  };
  document.addEventListener("pointerdown", (e) => { if (e.pointerType === "mouse" && e.button !== 0) return; const el = e.target.closest && e.target.closest(SEL); if (!el || el.disabled) return; down(el, e); });
  /* hidden strips the press (BOARD A6 template): no scale left on a button, no click fired for a touch the page never saw end */
  document.addEventListener("visibilitychange", () => { if (!document.hidden) return; for (const [el, st] of live) { if (st.raf) cancelAnimationFrame(st.raf); if (st.timer) clearTimeout(st.timer); if (st.detach) st.detach(); if (st.phase === "hold") Motion.swallowNextClick(el); clear(el); iconSet(el, 1); glowStrip(el); live.delete(el); } });
  window.GlassBtn = { L, glowAt, glowAlpha, glowState: (el) => { const g = glows.get(el); return g ? { phase: g.phase, t: g.t, b: g.b, l: g.l, s: g.s, node: g.node } : null }, state: (el) => { const st = live.get(el); return st ? { phase: st.phase, x: st.x, from: st.from, k: st.k, rising: !!st.rising, resuming: !!st.prevRel, t0: st.t0, downAt: st.downAt, upAt: st.upAt, started: !st.timer, inside: st.in, w0: st.w0, icon: st.icon == null ? (st.phase === "hold" ? ICON_ALPHA_HELD : 1) : st.icon, tLast: st.tLast } : null }, SLOP, LIFT_START, LIFT_FIRST, REVERSE_MS, ICON_ALPHA_HELD, ICON_BACK, iconAt, LIFT_T: LIFT_T.map((k) => [...k]), REL_T: REL_T.map((k) => [...k]), liftAt, releaseAt, glow: GLOW };
})();
