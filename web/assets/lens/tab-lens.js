/* tab-lens.js — the tab bar's lifted selection lens (GOAL 3; README §0.8 / §0.8.1 / §0.8.3). One line to include, after view.js:
     <script src="assets/lens/tab-lens.js"></script>          (?tlens=0 off; ?tlens-ab=0 without the colour fringe; data-family="assets/lens/tab5/")
   What it is: the Liquid Glass lens that lifts off the selected tab (formula.md §4b — the segment lens's layer structure with the tab's keys,
   tab-lens-native.md §0 / §3), driven by the states view.js's attachTabBar already sets on the page (nothing in view.js changes): .glide gets
   `lift-sel` (+125 ms on the selected item) / `lift` (+140 ms on another item), its inline left / width = the item under the finger, nav gets
   `drag`, the classes go at the up, `button.on` moves at a selection. This script only watches those (MutationObserver) and draws.
   Layers (one fixed element .tabbar-lens in screen coordinates; the platter's presentation scale is NOT an ancestor transform of the filtered
   layers — the engine fact of calib/webkit-region-under-scale.html is read at ½ only — it is folded into the layout and the filter scale):
     .stack (lens box + 16 pt; the colour fringe chain #tab-lens-f-ab-<w> on it, W/H per frame from the capture box — layer 5)
       .base   the plain copy under the wrapper: the page (a clone of <main>), the platter (clone-blurred page + the glass fill), the items
       .warp > .disp (#tab-lens-f-bg-<w>, layer 1 = BackdropView +9/36 after glassBackground −10.5/7): the same copy with the items punched
               out inside the capsule (DestOut #76, α = the lift progress; the box corners keep them — the map's clamp reads them at the rim)
       .ish    the inner shadow #37 (#tab-lens-f-ish: keyfill-highlight.md §5.2c op·M·blur_σ(M − M↓7), keys .06 / (0, 7) / r 3, α × progress)
       .warpl > .displ (#tab-lens-f-lab-<w>, layers 2 + 4 = ContentLensing −14/11.2 then ClearGlass −17.5/11.2): the SelectedContentView copy —
               the items at scale 1 → 1.16 about their own centres, capsule-clipped BEFORE the filter (the layer's border-radius)
   Geometry (tab-lens-native.md §3, formula.md §5b): model = the platter's resting frame; lens model box at progress p = (w0 + 16p) × (54 + 16p),
   r = h/2, centred on the item (w0 = the item width: 82 on the 440 screen, the tab5/ family; the native 94 → 110 read as +16 on both axes);
   presented = model scaled 1 → 1.0516 about the platter centre (the real .plat / .seg / .glide carry that scale, --tplatter-scale); the maps
   (model pt) are stretched over the presented box and the feDisplacementMap scale = data-s × p × s. Set = the nearest even width of the family.
   Motion (tab-lens-motion.md §4, the read curves): lift = ONE spring ζ 1 / response .25 s for every quantity (size, r, the three amounts,
   _UITabSelectionView α 1 → 0 (= .glide, --tsel-alpha), DestOut 0 → 1, items 1 → 1.16, platter 1 → 1.0516); drop = the same back with
   ζ 1 / .4 s; page change while held (press another item / drag) = position ζ .85 / .4 s from the old centre to the new + the lift at the same
   time (the flex stretch of the loupe is NOT drawn: no read sets beyond the lift for this family; the ±1.6 pt wobble after the drop unread; a
   quick tap without the +140 ms lift keeps view.js's glide slide — the tap's lens trace is unread). The drag (nav.drag while lifted) follows the
   finger by tab-lens-motion.md §6.6: target = finger x − a·W + W/2 (a = the press point's fraction in the item), the left edge hard-clamped to
   the items' run, spring ζ .85 / .2 retargeted on every move, no rubber band; after the up ζ .85 / .4 (R106: §6.9's "no gesture" pair) to the item under the finger (view.js's
   choice). The flex stretch (loupe sX / sY, drift tx = sX(1 − sX)·55) is read but not drawn (per-axis map scaling needed).
   Not drawn yet (material, the ui session's tokens): the KeyFill highlight, the ring shadow, the dark line, the little glow (α 0 → .2).
   Instrument: window.__tabLens = the per-frame state (t s since the start, p, x, v, target, set, s, phase; settled = both springs at their targets, S1). */
/* GEOMETRY MODE (BOARD.md #7a, 2026-09-20 — the default tonight; ?tlens=material restores the layered lens above): no material at all — the page's own
   .glide (the selection view, index.html's rules for its glass stay) is driven per frame: size (w0 + 16p) × (54 + 16p) about the item's centre
   (tab-lens-motion.md §0 / §4: 94×54 → 110×70 read as +16 on both axes; r = h/2 through the capsule's border-radius), lift ζ 1 / .25, drop ζ 1 / .4,
   position ζ .85 / .4 to a pressed item, the drag by §6.6 (ζ .85 / .2, the finger rule, hard clamp) and ζ .85 / .4 (R106) to the item under the finger after
   the up — all through Motion.spring (motion.js #1). The lift's delays are the page's own timers (+140 ms on another item, +125 ms on the selected,
   interaction spec §2 T1 / T3 via tokens.css --ios-touch-tab-*-delay): the spring starts at the class the page sets. The style below (injected) takes the
   glide's CSS scale rules and transitions out of the way while the driver owns the box. Unread: the ±1.6 pt wobble after the drop, the spec's
   119×64 / 103×63 vs the read 110×70.
   R64 (界面, flex-interaction.md §1–§3, tab-lens-motion.md §6.4 / §6.6): the flex stretch while the lens moves — view.js's B5 chain (globals
   flexIntegrator / flexSpec / flexTargets / springStep, the same _UIFlexInteraction reading) fed with this lens's own presented centre every frame;
   the variant from the MODEL bounds (§7.4: a step at lift / unlift — lifted (w0 + 16) × (h0 + 16) → d = 70 → t = 1 → the loupe row: pts 100, min .75,
   max 1.15, N 2500, scaleSpring ζ 1 / .5, tracking ζ .9 / .5 while the finger is down); targets sX / sY / drift by §3 (the [0.9, 1.1] hard clamp on the
   targets), the three floats on the flex spring; presented box = W·sX × H·sY about the centre x + sX·dx (§6.4: the drift is added in the scaled
   coordinates). Active from the first drag frame (the selection gesture's pan) until the floats settle after the up; the press-glide to another item
   is left as the pure lift (the ① trace of tab-lens-motion.md §4 reads the lift sizes alone there). Not read: the retargetImpulse gap (§6.4: the native peak 1.109 vs the chain's 1.085 — no impulse in the loupe spec), the interaction
   pulse (§3, four parameters unread). Instrument: window.__tabLens.flex = { sx, sy, dx, target, spec, sp, accel, vel, trace }.
   REDUCE MOTION (R59′b / R59′b′ / R59′b″; page-inventory.md §12b ② decompiled + the R59″ records tools/touch/seg-native-r59-motion.json tabhold / tabtap,
   the R94 frames tools/uiprobe/uiprobe-r94-frames.json; the springs from tab-lens-motion.md §6.9 = 老网页 R105's read of this bar's real tracker
   UIKit._UITabBarVisualProvider_Floating): with Reduce Motion on nothing lifts (no setLifted:, the .95 platter scale needs a trait this bar lacks) but
   _UIContinuousSelectionGestureRecognizer begins at the down and the selection frame + the lens (one and the same motion, 数据 R94: equal to 0.00 on 238
   frames) spring to the target. Six springs (0x1c50e8654–0x1c50e87a4, UIViewSpringAnimationBehavior dampingRatio:response:): Reduce Motion ON → position
   AND size ζ .9 / .2 (0x1c50e8690 / 0x1c50e86c4); RM off and the gesture changed → .85 / .2 position, .85 / .3 size; otherwise .85 / .4 / .85 / .6. Target
   (handleSelectionGesture 0x1c50e9078 → updateLensView 0x1c50e8180): frame.x = clamp(finger + offset, platter.minX + a·W, maxX − (1 − a)·W) − a·W with a =
   the press point's fraction in the item (= the §6.6 finger rule, offset 0 here); the R94 frames fit that rule + ζ .9 / .2 + a 2-frame delivery latency to
   1.15 pt rms (§6.9 ④, tools/lens/r94sim.py) and the slide-at-down records to .11. Here (geometry mode): the driver starts at the pointerdown, p stays 0
   (rest box, no flex), the position spring ζ .9 / .2 to the finger target (the pressed item's centre at the down; every move adopted on the next tick —
   no artificial latency: the page's own event → rAF path is its delivery), the loop keeps running while the finger is down (the lens parks on the item —
   the glide's own CSS box is still the old item until view.js selects at the up), after the up the RM pair again (R106 ②: the up commits synchronously, clears the highlight, and the "no gesture" spring — RM .9 / .2, else .85 / .4 — takes
   the frame + lens to the selected item; then ① the fall within 8 pt). The
   non-RM pairs: position .85 / .2 (drag) = SP_DRAG ✓, .85 / .4 = SP_POS ✓; the size pairs .85 / .3 / .85 / .6 act on the selection frame's width when
   the highlighted item's width differs — this bar's items share --ios-tab-button-w, so no width spring runs here (记录); the lift's 94 → 110 is the
   material's setLifted spring (§0 / §4, ζ 1 / .25), not these six. Detected like view.js: window.__forceRM (the acceptance's switch), else
   prefers-reduced-motion. ?tlens=material unchanged. */
(function () {
  const q = new URLSearchParams(location.search);
  if (q.get("tlens") === "0") return;
  const MODE = q.get("tlens") === "material" ? "material" : "geometry";
  const me = document.currentScript;
  const FAMILY = (me && me.dataset.family) || "assets/lens/tab5/";
  const FRINGE = q.get("tlens-ab") !== "0";
  /* instrument (wksnap's offscreen WKWebView never fires requestAnimationFrame and throttles timers — document hidden): ?tlens-clock=timer drives the
     loop by setTimeout; ?tlens-clock=manual gives the loop a virtual clock stepped by window.__tabLensStep(dt_ms) from the test script (deterministic:
     the springs integrate the dt they are given). The device uses requestAnimationFrame. */
  const CLOCK = q.get("tlens-clock") || "raf";
  let vnow = 0, pendingTick = null;
  const clockNow = () => CLOCK === "manual" ? vnow : performance.now();
  const tick = (fn) => { if (CLOCK === "manual") pendingTick = fn; else if (CLOCK === "timer") setTimeout(() => fn(performance.now()), 16.667); else requestAnimationFrame(fn); };
  window.__tabLensStep = (dt) => { vnow += dt; const f = pendingTick; pendingTick = null; if (f) f(vnow); return !!f; };
  window.__tabLensGL = () => glo;   // the WebGL overlay (R2), for the acceptance
  const AM = 16;                                                              // the fringe wrapper's margin (lens-field.json aberration.wrapper; ≥ the 15 pt tap span)
  const LIFT = 16, PLATTER = 1.0516, ITEM = 1.16;                             // +16 on both axes (94×54 → 110×70 — the selection frame's CGRectInset(−8, −8), §6 line 100), platter 1.0516, items 1.16 (tab-lens-native.md §3); the material mode still uses it
  /* R59′d (老网页 R108, tab-lens-motion.md §6.9 ⑤; probe tools/uiprobe/uiprobe-motion-tabdrag-light.json, the selected item held still 615 ms): the LENS view's presented size leaves 94 × 54 on
     the frame after the down (+14 still 94, +47 95.76, +97 105.07, +130 110.14, +180 114.55, +197 115.34) on ζ 1 / .25 towards 116.7 wide (the fit's target; the bounds settle 115.7 by +464
     after a .5 % flex wobble) and 74.0 high (the +464 row: 73.99, d 1.005); there is no timer anywhere in the down → setLifted chain (touchesBegan 0x1c42552c8 … setLifted 0x1c54c7ea0, four
     springs at once) — the +125 / +140 ms of the tokens were the recording's latency. So the geometry driver lifts from the pointerdown itself (the next tick), by LIFT_W / LIFT_H, not
     waiting for view.js's +140 / +125 ms class (which still arrives and is then redundant). */
  const LIFT_W = 116.7 - 94, LIFT_H = 74.0 - 54;
  const SP_LIFT = { z: 1, w: 2 * Math.PI / .25 }, SP_DROP = { z: 1, w: 2 * Math.PI / .4 }, SP_POS = { z: .85, w: 2 * Math.PI / .4 };   // tab-lens-motion.md §0 / §4: lift, drop, the jump to a pressed item (the ① trace)
  const SP_DRAG = { z: .85, w: 2 * Math.PI / .2 }, SP_RELEASE = { z: .85, w: 2 * Math.PI / .4 };   /* R106 (tab-lens-motion.md §6.9 ③ / R106): after the up the highlight is cleared and the "no gesture" pair .85 / .4 drives the frame + lens to the selected item (0x1c50e8774); the .9 / .4 of before was _UIFloatingTabBar's, not this bar's */
  const DROP_WITHIN = 8;                                                    /* R106 (§6.9 ①): setLifted(false) only when there is no highlight AND |target − presented| < 8 pt (0x1c50e8634–0x1c50e8650) — after the up the lens slides first and falls within 8 pt of its target (the R33 tap's "arrival at .5 pt" was that rule seen late) */
  const SP_RM = { z: .9, w: 2 * Math.PI / .2 };                             // R59′b″: Reduce Motion's own pair, position and size (tab-lens-motion.md §6.9 ③: 0x1c50e8690 / 0x1c50e86c4) — the records' .11 / 1.15 pt rms in the header
  const RM = () => (window.__forceRM != null ? !!window.__forceRM : matchMedia("(prefers-reduced-motion: reduce)").matches);   // tab-lens-motion.md §6.6 (UIKitCore _animateSelection, checked on the drag trace rms .55 / max .75 by the old page): the finger-following spring while highlighted, the spring after the up
  const step = (st, target, sp, dt) => {                                      // analytic damped-spring step from (x, v): ζ ≥ 1 critically damped, else under-damped
    const dx = st.x - target;
    if (sp.z >= 1) { const A = dx, B = st.v + sp.w * dx, e = Math.exp(-sp.w * dt); st.x = target + (A + B * dt) * e; st.v = (B - sp.w * (A + B * dt)) * e; }
    else { const wd = sp.w * Math.sqrt(1 - sp.z * sp.z), e = Math.exp(-sp.z * sp.w * dt), A = dx, B = (st.v + sp.z * sp.w * dx) / wd, c = Math.cos(wd * dt), s = Math.sin(wd * dt);
      st.x = target + e * (A * c + B * s); st.v = e * (-sp.z * sp.w * (A * c + B * s) + wd * (B * c - A * s)); }
  };
  const sets = [];                                                            // the family's widths (from the filter ids), ascending
  const setFor = (w) => { let best = sets[0] || 82, d = Infinity; for (const s of sets) { const dd = Math.abs(s - w); if (dd < d) { d = dd; best = s; } } return best; };
  const sOf = (id) => { const f = document.getElementById(id); return f ? parseFloat(f.getAttribute("data-s")) || 40 : 40; };   // data-s = the set's encoding S (× SS when lens-supersample.js folded it in)

  /* the filters: the family's lens-filter.svg is fetched and inserted (its feImage hrefs are the page's paths), then the two engine corrections re-run over it */
  let ready = false;
  const loadFilters = async () => {
    try {
      const txt = await (await fetch(FAMILY + "lens-filter.svg")).text();
      const svg = document.importNode(new DOMParser().parseFromString(txt, "text/html").querySelector("svg"), true);   // the HTML parser, as index.html's inline copy: the file's comments hold "--" (XML would refuse them)
      svg.setAttribute("data-tab-lens", FAMILY); document.body.appendChild(svg);
      for (const f of svg.querySelectorAll('filter[id^="tab-lens-f-bg-"]')) sets.push(parseInt(f.id.slice("tab-lens-f-bg-".length), 10));
      sets.sort((a, b) => a - b);
      if (window.LENS_SS_APPLY) window.LENS_SS_APPLY();
      if (window.LENS_MAP_DPR_APPLY) window.LENS_MAP_DPR_APPLY();
      if (window.LENS_ENGINE_FIX_APPLY) await window.LENS_ENGINE_FIX_APPLY();
      ready = true;
    } catch (e) { console.warn("tab-lens: filters", e); }
  };

  const el = (cls, parent, css) => { const d = document.createElement("div"); d.className = cls; if (css) d.style.cssText = css; if (parent) parent.appendChild(d); return d; };
  const stripIds = (n) => { n.removeAttribute("id"); for (const c of n.querySelectorAll("[id]")) c.removeAttribute("id"); return n; };
  /* a copy of the page (what lies under the bar): <main> cloned without ids, laid out at the page's width; the body colour behind it */
  const pageCopy = (parent, main, mr) => { const w = el("pg", parent, `position:absolute;inset:0;overflow:hidden;background:${getComputedStyle(document.body).backgroundColor}`);   // overflow hidden: WebKit takes an overflowing child into a filter's objectBoundingBox region — the page clone must not enlarge the lens filters' buffers
    const m = stripIds(main.cloneNode(true)); m.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;margin:0;pointer-events:none`; w.appendChild(m); w._m = m; return w; };
  /* the platter as the lens sees it: the capsule (scaled 1 → 1.0516 with the real one) holding the page blurred by the glass recipe (a
     backdrop-filter inside a software-filtered layer does not blur — README §0.8.1 — so the copy blurs a page clone with `filter`) and the fill + rim */
  const BM = 32;                                                              // the blurred clone's clip margin beyond the platter box: > 3σ of the glass blur (10 px), so the capsule's edge sees real pixels
  const platterCopy = (parent, main, mr, pr) => { const pl = el("pl", parent, `position:absolute;left:0;top:0;width:${pr.width}px;height:${pr.height}px`);
    const inv = el("inv", pl); const bp = el("blurpg", inv, `position:absolute;left:${-BM}px;top:${-BM}px;width:${pr.width + 2 * BM}px;height:${pr.height + 2 * BM}px;overflow:hidden;background:${getComputedStyle(document.body).backgroundColor}`);
    const m = stripIds(main.cloneNode(true)); m.style.cssText = `position:absolute;left:${mr.left - pr.left + BM}px;top:${mr.top - pr.top + BM}px;width:${mr.width}px;margin:0;pointer-events:none`; bp.appendChild(m);
    el("fill", pl); return pl; };
  /* the items as a shell <nav class="tabs"> (so index.html's nav.tabs button rules dress the copies; the page copies live outside any nav.tabs) */
  const itemsCopy = (parent, nav, seg, pr) => { const sh = nav.cloneNode(false); sh.removeAttribute("id"); sh.removeAttribute("hidden"); sh.classList.remove("drag", "tlens");
    sh.style.cssText = `position:absolute;left:0;top:0;bottom:auto;width:${pr.width}px;height:${pr.height}px;max-width:none;margin:0;padding:0;display:block;transform:none;z-index:auto;pointer-events:none`;
    const s = seg.cloneNode(true); s.removeAttribute("id"); for (const b of s.querySelectorAll("button")) b.removeAttribute("id"); s.style.cssText = `position:absolute;left:0;top:0;width:${pr.width}px;height:${pr.height}px;box-sizing:border-box`;
    sh.appendChild(s); parent.appendChild(sh); return sh; };

  /* the item under the finger / the selection, in platter (nav) coordinates: the glide's INLINE left / width (view.js's liftTo / glide() write them;
     offsetLeft would read the glide's CSS transition mid-flight, i.e. the old value on the frame the target changes) */
  const centreOf = (g) => { const l = parseFloat(g.style.left), w = parseFloat(g.style.width); return (isNaN(l) ? g.offsetLeft : l) + (isNaN(w) ? g.offsetWidth : w) / 2; };
  let loop = null;
  /* the finger (tab-lens-motion.md §6.6: while the selection view is highlighted its target is finger x − a·W + W/2, a = where in the item the
     finger went down (0 … 1), the left edge hard-clamped to the track [track.minX, track.maxX − W] — no rubber band; the landing = the item under
     the finger): read here from the same pointer events view.js's press() handles, capture phase, nothing consumed */
  const finger = { x: null, a: .5, down: false, moved: false, x0: 0 }; window.__tabLensFinger = finger;   // instrument (#15 device record: seg-frames-logger.js tab reading)
  const trackFinger = (nav) => {
    if (nav.__tlensFinger) return; nav.__tlensFinger = true;
    nav.addEventListener("pointerdown", (e) => { const r = nav.getBoundingClientRect(); const bs = [...nav.querySelectorAll(".seg button")];
      let a = .5; for (const b of bs) { const q = b.getBoundingClientRect(); if (e.clientX >= q.left && e.clientX <= q.right) { a = (e.clientX - q.left) / q.width; break; } }
      finger.down = true; finger.a = a; finger.x = e.clientX - r.left; finger.moved = false; finger.x0 = e.clientX; finger.last = { t: e.type, pt: e.pointerType, id: e.pointerId, at: performance.now(), target: e.target && e.target.tagName ? e.target.tagName.toLowerCase() + "." + (e.target.className || "") : null };
      if (st && st.nav === nav) st.pressed = !RM();   // R59′d: the lift belongs to the down itself (no highlight → no lift under Reduce Motion)
      if (loop) loop.retarget();
      else if (MODE === "geometry" && st && st.nav === nav && ready) { const tx = rmTarget(st); window.__tabLensRM = { at: performance.now(), target: tx, X: st.X, started: !RM() || (tx != null && Math.abs(tx - st.X) > .5) }; if (!RM() || (tx != null && Math.abs(tx - st.X) > .5)) { st.lastX = st.X; start(st); } } }, true);   // R59′d: the driver starts on the down (its first tick = the lift's t0); RM: only when there is somewhere to slide   // R59′b: the slide begins at the down, no lift
    nav.addEventListener("pointermove", (e) => { finger.last = { t: e.type, pt: e.pointerType, id: e.pointerId, at: performance.now() }; if (!finger.down) return; finger.x = e.clientX - nav.getBoundingClientRect().left; if (Math.abs(e.clientX - finger.x0) >= 1) finger.moved = true; if (loop) loop.retarget(); }, true);
    for (const t of ["pointerup", "pointercancel"]) nav.addEventListener(t, (e) => { finger.last = { t: e.type, pt: e.pointerType, id: e.pointerId, at: performance.now() }; finger.down = false; finger.x = null; finger.moved = false; if (st) st.pressed = false; if (loop) loop.retarget(); }, true);
  };
  /* R59′b: the Reduce Motion target = the §6.6 finger rule (finger x − a·W + W/2 = the pressed item's centre at the down), hard-clamped to the items' run */
  const rmTarget = (st) => { if (finger.x == null) return null; const w = parseFloat(st.glide.style.width) || st.glide.offsetWidth; const navBox = st.nav.getBoundingClientRect(), segBox = st.seg.getBoundingClientRect();
    const min = segBox.left - navBox.left + (parseFloat(getComputedStyle(st.seg).paddingLeft) || 0), max = segBox.right - navBox.left - (parseFloat(getComputedStyle(st.seg).paddingRight) || 0);
    return Math.max(min, Math.min(max - w, finger.x - finger.a * w)) + w / 2; };
  const attach = (nav) => {
    const glide = nav.querySelector(".glide"), seg = nav.querySelector(".seg"), main = document.getElementById("app");
    if (!glide || !seg || !main) return null;
    nav.classList.add("tlens"); trackFinger(nav);
    const st = { nav, glide, seg, main, X: centreOf(glide), lastX: centreOf(glide) };
    if (MODE === "geometry" && GL_ON) glAttach(st).then((g) => { if (g && g.nav === nav) { try { g.lens.redrawBackdrop(); } catch (e) {} } });   // the items may have changed (tabs-changed): the textures again, at idle in the package's own way
    return st;
  };
  /* ---- geometry mode ---- */
  /* the driver's output goes to custom properties on nav (not the glide: the glide's inline left / width stay view.js's and are the TARGET the
     observer reads; a per-frame write on the glide itself would come back through the observer as a new target). While .tl-on is set the box
     rules below take the glide over — `!important` because the values they replace are inline (view.js's left / width) */
  const GEO_CSS = `nav.tabs.tlens .glide.lift,nav.tabs.tlens .glide.lift-sel,nav.tabs.tlens.drag .glide.lift-sel{scale:1 1}
nav.tabs.tlens.tl-on .glide,nav.tabs.tlens.tl-on.drag .glide{transition:none;left:var(--tl-left) !important;width:var(--tl-w) !important;top:var(--tl-top) !important;height:var(--tl-h) !important;bottom:auto !important}`;
  /* only while the driver runs (.tl-on): a plain tap on another tab (no lift — the up came before +140 ms) keeps the page's own CSS slide
     (index.html: left / width on --ios-motion-lens-duration / -easing, the probe's ζ .85 / .4 as an easing); the read says the lens lifts while it
     slides on such a tap (tab-lens-motion.md §0 "换页滑动"), but when it drops after landing is not read — unread, not driven tonight */
  const injectGeoStyle = () => { if (document.getElementById("tab-lens-geo-style")) return; const s = document.createElement("style"); s.id = "tab-lens-geo-style"; s.textContent = GEO_CSS; document.head.appendChild(s); };
  const spring = (st, target, sp, dt) => (window.Motion && Motion.spring ? Motion.spring(st, target, [sp.z, 2 * Math.PI / sp.w], dt) : step(st, target, sp, dt));
  /* ---- R2 (b): the material through lens-webgl.js, over the bar (验收's call: a flat platter fill — the page under the bar cannot be drawn into a canvas,
     标不可表达; the items' copies, the displacement, the KeyFill line, the ring shadow, the dispersion are the package's, from the tab5 family's maps
     and keys (tab5/lens-filter.svg data-s 40 / 48 (98) / fringe 16; tab5/lens-field.json heights 54 … 70; tab-lens-native.md §0 / §3: Backdrop +9/36,
     ClearGlass −17.5/11.2, ContentLensing −14/11.2 are the maps' formula, README §0.8.1). The lift rides the 98 set (the lifted size) stretched over the
     growing box, as the segment lens rides its 220 set (README §0.3). Not drawn: the items' 1.16 scale of the SelectedContentView copy (the package
     has no label scale: 待做), the blurred page in the platter (不可表达), _UITabSelectionView's own α 1 → 0 (the glide stays the geometry driver's).
     ?tlens-gl=0 leaves the canvas out (geometry only). */
  const GLM = 24;                                                            // the canvas extends the bar's box by this on every side (the lifted 98 × 70 over a 62 bar + the fringe wrapper 16)
  const GL_ON = q.get("tlens-gl") !== "0" && !!window.LensWebGL && (() => { try { return !!document.createElement("canvas").getContext("webgl2"); } catch (e) { return false; } })();
  let glSets = null, glHeights = null, glo = null, glReady = null;
  const glLoad = async () => { if (glReady) return glReady; glReady = (async () => { try {
      const svgTxt = await (await fetch(FAMILY + "lens-filter.svg")).text(); const svg = document.importNode(new DOMParser().parseFromString(svgTxt, "text/html").querySelector("svg"), true);
      svg.setAttribute("data-tab-lens-gl", FAMILY); svg.setAttribute("aria-hidden", "true"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg);   // the maps' hrefs and data-s for setsFromFilters; no engine fix (the GPU samples the plain maps)
      const field = await (await fetch(FAMILY + "lens-field.json")).json(); glHeights = {}; for (const [w, v] of Object.entries(field.sets || {})) glHeights[w] = v.h;
      glSets = LensWebGL.setsFromFilters("tab", glHeights); for (const w of Object.keys(glSets)) glSets[w].model = +w <= 110 ? [+w, glSets[w].h || +w - 40] : [110, 70];   // R37: the set's model box for the in-shader label field — the lift path's model bounds are the set itself (94×54 → 110×70), the stretch sets are the 110×70 model scaled (tab/lens-field.json sets.model)
      return Object.keys(glSets).length > 0; } catch (e) { console.warn("tab-lens gl: family", e); return false; } })(); return glReady; };
  const maskCache = new Map();
  const loadImage = (src) => new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
  const cssUrl = (v) => { const m = /url\("?([^")]+)"?\)/.exec(v || ""); return m ? m[1] : null; };
  const tintedIcon = (src, colour, w, h) => { const key = src + "|" + colour + "|" + w + "x" + h; if (maskCache.has(key)) return maskCache.get(key); const img = maskCache.get(src); if (!img) return null;
    const c = document.createElement("canvas"); const dpr = window.devicePixelRatio || 1; c.width = Math.max(1, Math.round(w * dpr)); c.height = Math.max(1, Math.round(h * dpr)); const x = c.getContext("2d"); x.scale(dpr, dpr); x.drawImage(img, 0, 0, w, h); x.globalCompositeOperation = "source-in"; x.fillStyle = colour; x.fillRect(0, 0, w, h); maskCache.set(key, c); return c; };
  const glPrefetchIcons = async (nav) => { const jobs = []; for (const el of nav.querySelectorAll(".seg button .sf")) { const src = cssUrl(getComputedStyle(el).webkitMaskImage || getComputedStyle(el).maskImage); if (src && !maskCache.has(src)) jobs.push(loadImage(src).then((i) => { if (i) maskCache.set(src, i); })); }
    for (const img of nav.querySelectorAll(".seg button img")) if (!img.complete) jobs.push(new Promise((r) => { img.onload = r; img.onerror = r; })); await Promise.all(jobs); };
  const glAttach = async (st) => { if (!GL_ON) return null; if (!(await glLoad())) return null; const nav = st.nav; if (glo && glo.nav === nav && glo.w === nav.offsetWidth && glo.h === nav.offsetHeight) return glo; if (glo) { try { glo.lens.destroy(); } catch (e) {} (glo.canvas.parentElement && glo.canvas.parentElement.classList.contains("lens-clip") ? glo.canvas.parentElement : glo.canvas).remove(); glo = null; }
    await glPrefetchIcons(nav); const navW = nav.offsetWidth, navH = nav.offsetHeight; if (!navW) return null;
    if (glo && glo.nav === nav && glo.w === navW && glo.h === navH) return glo;   // a concurrent attach finished during the awaits (R96: two canvases used to pile up in the bar)
    for (const e of nav.querySelectorAll(":scope > canvas.tlens-gl, :scope > .lens-clip")) e.remove();   // R96: never two canvases (a stale one reached x 516 in 界面's log)
    const canvas = document.createElement("canvas"); canvas.className = "tlens-gl"; canvas.style.cssText = `position:absolute;left:${-GLM}px;top:${-GLM}px;width:${navW + 2 * GLM}px;height:${navH + 2 * GLM}px;pointer-events:none;z-index:3`; nav.appendChild(canvas);
    const widths = Object.keys(glSets).map(Number), top = Math.max(...widths);
    const ink = () => { const b = nav.querySelector(".seg button:not(.on) span:last-child") || nav.querySelector(".seg button span:last-child"); const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)/.exec(b ? getComputedStyle(b).color : ""); return m ? [+m[1], +m[2], +m[3]] : [0, 0, 0]; };
    const opts = { sets: glSets, preload: [top], dpr: window.devicePixelRatio || 1, width: navW + 2 * GLM, height: navH + 2 * GLM, margin: 16, ink: ink(), warm: true, labelsDirect: true,   // icons of any colour + labels: drawn with their own alpha (no single-ink recovery)
      rmax: 1e6, labelStages: [-14, 11.2, -17.5, 11.2],   // the tab lens is a capsule r = h/2 (tab-lens-native.md §0: cornerRadii 35 = 70/2 on every element; R37 fix: the outline terms used the segment lens's r 22); its label stack ContentLensing −14 / 11.2 then ClearGlass −17.5 / 11.2 (tab-lens-native.md §3, tab/lens-field.json parameters.label)
      backdrop: (x, which) => { const nb = nav.getBoundingClientRect(), plat = nav.querySelector(".plat"), pr = plat ? plat.getBoundingClientRect() : nb;
        if (which === "page") {   // the page colour everywhere (the page's content under the bar is 不可表达 here), then the platter's fill over it as the capsule it is (验收: (b) flat fill; the blurred page in the platter is not drawn)
          x.fillStyle = getComputedStyle(document.body).backgroundColor || "#fff"; x.fillRect(0, 0, navW + 2 * GLM, navH + 2 * GLM);
          const cs = plat ? getComputedStyle(plat) : getComputedStyle(nav); x.fillStyle = cs.backgroundColor; x.beginPath(); x.roundRect(pr.left - nb.left + GLM, pr.top - nb.top + GLM, pr.width, pr.height, Math.min(pr.width, pr.height) / 2); x.fill(); }
        else { for (const b of nav.querySelectorAll(".seg button")) { const cs = getComputedStyle(b), sel = b.querySelector(".tcs") || b; const icon = sel.querySelector(".sf"), img = sel.querySelector("img"), lab = sel.querySelector("span:last-child");   // the lens shows SelectedContentView — every item's selected copy (.tcs, view.js tabClip; P0b-数据.md 14:1x)
            if (icon) { const r = icon.getBoundingClientRect(), src = cssUrl(getComputedStyle(icon).webkitMaskImage || getComputedStyle(icon).maskImage); const t = src && tintedIcon(src, getComputedStyle(icon).backgroundColor, r.width, r.height); if (t) x.drawImage(t, r.left - nb.left + GLM, r.top - nb.top + GLM, r.width, r.height); }
            if (img && img.complete && img.naturalWidth) { const r = img.getBoundingClientRect(); x.drawImage(img, r.left - nb.left + GLM, r.top - nb.top + GLM, r.width, r.height); }
            if (lab) { const r = lab.getBoundingClientRect(), lc = getComputedStyle(lab); x.font = lc.font; x.fillStyle = lc.color; x.textAlign = "center"; x.textBaseline = "middle"; x.fillText(lab.textContent, r.left - nb.left + r.width / 2 + GLM, r.top - nb.top + r.height / 2 + GLM); } } } } };
    let lens; try { lens = LensWebGL.create(canvas, opts); } catch (e) { console.warn("tab-lens gl", e); canvas.remove(); return null; }
    if (!lens) { canvas.remove(); return null; }
    LensWebGL.clipCanvas(canvas, { y: true });   // R96: clipped to the viewport (nav ± 24 reaches x 452 / y 968 on a 440 × 956 screen with five tabs) — re-measured on resize below
    glo = { nav, canvas, lens, w: navW, h: navH, top }; return glo; };
  /* G4 / 用户 09-23 18:27 真机 ④「圆钮落回标签时的动画有问题，会闪一下白色」: _UITabSelectionView (the grey under the selected item) fades back on the
     drop's own spring, α = 1 − p from the first drop frame (数据 A53 probe, NATIVE-GAP.md 数据核 G4: +1003 0 → +1020 .029 → +1053 .186 → +1103 .466 →
     +1203 .821 → +1386 .983 = (1 + ωt)e^(−ωt), ω 15.71, the drop spring; tab-lens-motion.md: every lift quantity on one spring). The canvas capsule is
     opaque while p > 0, so the grey is drawn in it as the platter uniform (the segment lens's restingBackground path, view.js segGl): the glide's own
     colour = its backdrop filter (--lens-filter: saturate · brightness · contrast; blur is the identity on a flat colour) applied, in sRGB as CSS filter
     functions are (Filter Effects 1 §13), to the flat backdrop the canvas draws (body background, the platter fill over it). Before, alpha 0: the
     capsule showed that white backdrop until the driver stopped and the DOM glide came back (2号 rec new-4 f094–f109, 16 frames white). */
  const selRest = (nav) => { const rgb = (c) => { const m = /rgba?\(([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?/.exec(c || ""); return m ? [+m[1] / 255, +m[2] / 255, +m[3] / 255, m[4] == null ? 1 : +m[4]] : [1, 1, 1, 0]; };
    const bg = rgb(getComputedStyle(document.body).backgroundColor), plat = nav.querySelector(".plat"), pf = rgb(plat ? getComputedStyle(plat).backgroundColor : "");
    let c = [0, 1, 2].map((i) => pf[i] * pf[3] + (bg[3] ? bg[i] : 1) * (1 - pf[3]));
    const g = nav.querySelector(".glide"), f = g ? (getComputedStyle(g).backdropFilter || getComputedStyle(g).webkitBackdropFilter || "") : "", cl = (v) => Math.max(0, Math.min(1, v));
    for (const [, fn, a] of f.matchAll(/(saturate|brightness|contrast)\(([\d.]+)\)/g)) { const s = +a;
      if (fn === "saturate") { const [r, gg, b] = c; c = [cl((.213 + .787 * s) * r + (.715 - .715 * s) * gg + (.072 - .072 * s) * b), cl((.213 - .213 * s) * r + (.715 + .285 * s) * gg + (.072 - .072 * s) * b), cl((.213 - .213 * s) * r + (.715 - .715 * s) * gg + (.072 + .928 * s) * b)]; }
      else if (fn === "brightness") c = c.map((v) => cl(v * s)); else c = c.map((v) => cl((v - .5) * s + .5)); }
    return [c[0] * 255, c[1] * 255, c[2] * 255, 1]; };
  const glFrame = (st, p, x, W, H, pad, h0) => { if (!glo || glo.nav !== st.nav) return; const nb = st.nav.getBoundingClientRect(); const l = nb.left + x - W / 2, t = nb.top + pad + h0 / 2 - H / 2;
    const wh = (Math.min(l + W + 100, innerWidth) - Math.max(l - 100, 0)) / (Math.min(t + H + 100, innerHeight) - Math.max(t - 100, 0));   // formula §3b.6: the capture box = frame ± 100 clamped to the screen
    try { glo.lens.setState({ cx: x + GLM, cy: pad + h0 / 2 + GLM, w: W, h: H, lift: p, pd: p, wh, platter: { rgba: st.selRest || (st.selRest = selRest(st.nav)), alpha: 1 - p } }); } catch (e) { window.__tabLensErr = String(e && e.stack || e); } };
  const glRest = (st) => { if (!glo || glo.nav !== st.nav) return; try { glo.lens.setState({ cx: 0, cy: 0, w: 82, h: 54, lift: 0 }); } catch (e) {} };
  const startGeo = (st) => {
    if (loop) { loop.stop("restart"); }
    st.selRest = null;                                                       // G4: the grey is read again on every press (theme / page colour may have changed)
    const nav = st.nav, glide = st.glide;
    if (!nav.offsetWidth) return;                                            // html.kbd: the bar is display:none, its geometry 0 — nothing to drive
    const w0 = parseFloat(glide.style.width) || glide.offsetWidth || 82, h0 = glide.offsetHeight || 54, pad = glide.offsetTop;   // the resting box = the item's (view.js's inline left / width; top = the bar's pad)
    const P = { x: 0, v: 0 }, XS = { x: st.lastX, v: 0 };
    let pTarget = 1, running = true, last = clockNow(), t0 = last, phase = "lift", frameN = 0, posSpring = SP_POS;
    /* R64: the flex interaction's integrator and three floats (view.js B5 helpers; without them the box is the lift's alone) */
    const FLEX_OK = typeof flexIntegrator === "function" && typeof flexSpec === "function" && typeof flexTargets === "function" && typeof springStep === "function";
    const fl = FLEX_OK ? { vi: flexIntegrator(), sx: { x: 1, v: 0 }, sy: { x: 1, v: 0 }, dx: { x: 0, v: 0 }, out: { sx: 1, sy: 1, dx: 0 }, tg: null, spec: null, sp: null, trace: [] } : null;
    const segBox = st.seg.getBoundingClientRect(), navBox = nav.getBoundingClientRect(), track = { min: segBox.left - navBox.left + (parseFloat(getComputedStyle(st.seg).paddingLeft) || 0), max: segBox.right - navBox.left - (parseFloat(getComputedStyle(st.seg).paddingRight) || 0) };
    /* R33 (tab-lens-motion.md §3a): a quick tap on another item (the up before the +140 ms lift) — the lens lifts and slides at once (ζ 1 / .25 with
       ζ .85 / .4) and starts falling (ζ 1 / .4) on the frame the slide arrives, not at the up, not earlier for an early up; the arrival = the position
       spring first within .5 pt (1 px at 2×) of the target */
    const tap = !!st.tap; let arrived = false;
    /* the lift target: 1 while the page holds the highlight (lift / lift-sel); after the up (no highlight) it stays 1 until the lens is within DROP_WITHIN of its target, then 0 (R106 ①);
       a quick tap (R33: the lift never got its class) rides the same rule: up (1 until within 8) then the fall; Reduce Motion never lifts */
    const setTargets = () => { const lifted = glide.classList.contains("lift") || glide.classList.contains("lift-sel") || (st.pressed && finger.down), dragging = lifted && finger.down && finger.x != null && (nav.classList.contains("drag") || finger.moved), rm = RM();   // R59′d: lifted from the down (st.pressed), dragging once the finger has moved
      st.rm = rm;
      if (rm && finger.down && finger.x != null) { const left = Math.max(track.min, Math.min(track.max - w0, finger.x - finger.a * w0)); st.X = left + w0 / 2; posSpring = SP_RM; phase = "rm"; }   // R59′b: the slide to the pressed item from the down, the finger rule while moving, ζ .9 / .2
      else if (dragging) { const left = Math.max(track.min, Math.min(track.max - w0, finger.x - finger.a * w0)); st.X = left + w0 / 2; posSpring = SP_DRAG; phase = "drag"; }
      else if (st.pressed && finger.down && finger.x != null) { const left = Math.max(track.min, Math.min(track.max - w0, finger.x - finger.a * w0)); st.X = left + w0 / 2; posSpring = SP_POS; phase = Math.abs(st.X - XS.x) > .5 ? "move" : "lift"; }   // R59′d: began → the pressed item's frame (§6.9 ②), the "began" pair .85 / .4
      else if (tap) { st.X = centreOf(glide); posSpring = rm ? SP_RM : SP_POS; phase = arrived ? "drop" : "tap"; }
      else { st.X = centreOf(glide); posSpring = lifted ? SP_POS : (rm ? SP_RM : SP_RELEASE); phase = lifted ? (Math.abs(st.X - XS.x) > .5 ? "move" : "lift") : "drop"; }   // after the up: §6.9's "no gesture" pair .85 / .4 (RM .9 / .2) to view.js's selection
      const near = Math.abs(st.X - XS.x) < DROP_WITHIN; arrived = tap ? (arrived || near) : arrived;
      pTarget = rm ? 0 : lifted ? 1 : (near ? 0 : 1); if (!lifted && !near && !rm) phase = tap ? "tap" : "slide"; };   // R106 ①: no highlight → lifted until within 8 pt of the target
    setTargets();
    const frame = (now) => { try { frame0(now); } catch (e) { window.__tabLensErr = String(e && e.stack || e); console.error("tab-lens frame", e); stop(); } };
    const frame0 = (now) => {
      if (!running) return;
      if (now <= last) { tick(frame); return; }                             // a frame stamped before the start (Chrome: rAF's `now` = the frame's start, which can precede the call that started the loop): nothing to integrate yet
      const dt = Math.min(1, (now - last) / 1000); last = now; frameN++;
      spring(P, pTarget, pTarget > .5 ? SP_LIFT : SP_DROP, dt); spring(XS, st.X, posSpring, dt);
      if (pTarget > .5 && !st.rm && !(glide.classList.contains("lift") || glide.classList.contains("lift-sel")) && Math.abs(XS.x - st.X) < DROP_WITHIN) { if (tap && !arrived) st.tapArrivedAt = now; arrived = true; setTargets(); }   // R106 ①: the fall begins on the frame the lens comes within 8 pt of its target (no highlight)
      const p = Math.max(0, Math.min(1, P.x)), x = XS.x, W = w0 + LIFT_W * p, H = h0 + LIFT_H * p;
      /* R64 — the flex, once per frame: the presented centre (position + the drift in the scaled coordinates) into the integrator, the variant from the
         model bounds (lifted (w0 + 16) × (h0 + 16) while the lift target is up, the resting box otherwise — §7.4), updateFlex's targets, the three floats
         on the tracking spring while the finger is down, else the scaleSpring */
      let Wp = W, Hp = H, xc = x;
      if (fl && phase === "drag") fl.active = true;   // the flex runs from the first drag frame (the selection gesture's pan; the ① press-glide trace shows the pure lift sizes — no stretch there) until the floats have settled after the up
      if (fl && fl.active && phase !== "drag" && Math.abs(fl.out.sx - 1) < .002 && Math.abs(fl.out.sy - 1) < .002 && Math.abs(fl.out.dx) < .1) { fl.active = false; fl.sx = { x: 1, v: 0 }; fl.sy = { x: 1, v: 0 }; fl.dx = { x: 0, v: 0 }; fl.out = { sx: 1, sy: 1, dx: 0 }; fl.vi = flexIntegrator(); }
      if (fl && fl.active) {
        fl.vi.add(x + fl.out.sx * fl.out.dx, now / 1000);
        const Wm = pTarget > .5 ? w0 + LIFT_W : w0, Hm = pTarget > .5 ? h0 + LIFT_H : h0;
        const spec = flexSpec(Wm, Hm), tg = flexTargets(spec, Wm, Hm, fl.vi.acceleration, fl.vi.velocity), sp = finger.down ? [spec.tzeta, spec.tresp] : [spec.zeta, spec.resp];
        springStep(fl.sx, tg.sX, sp, dt); springStep(fl.sy, tg.sY, sp, dt); springStep(fl.dx, tg.drift, sp, dt);
        fl.out = { sx: fl.sx.x, sy: fl.sy.x, dx: fl.dx.x }; fl.tg = tg; fl.spec = spec; fl.sp = sp;
        Wp = W * fl.out.sx; Hp = H * fl.out.sy; xc = x + fl.out.sx * fl.out.dx;   // §6.6 / §6.4: W·sX × H·sY, tx = sX·dx
        if (fl.trace.length < 600) fl.trace.push({ t: now, dt, sx: fl.out.sx, sy: fl.out.sy, dx: fl.out.dx, vsx: fl.sx.v, vsy: fl.sy.v, vdx: fl.dx.v, tSx: tg.sX, tSy: tg.sY, tDx: tg.drift, sp, accel: fl.vi.acceleration, vel: fl.vi.velocity, Wm, Hm, x, W, H });
      }
      /* the glide's box: the centre x from the position spring (+ the flex drift), the vertical centre = the resting centre (pad + h0 / 2) */
      nav.style.setProperty("--tl-left", (xc - Wp / 2) + "px"); nav.style.setProperty("--tl-w", Wp + "px"); nav.style.setProperty("--tl-top", (pad + h0 / 2 - Hp / 2) + "px"); nav.style.setProperty("--tl-h", Hp + "px");
      if (!nav.classList.contains("tl-on")) nav.classList.add("tl-on");
      glFrame(st, p, xc, Wp, Hp, pad, h0);
      const flexRest = !fl || !fl.active;
      window.__tabLens = { t: (now - t0) / 1000, t0, tf: last, p, v: P.v, x, xv: XS.v, target: st.X, set: 0, s: 1, phase, w: W, h: H, wp: Wp, hp: Hp, xc, frame: frameN, mode: "geometry", rm: !!st.rm,
        settled: Math.abs(P.x - pTarget) < .002 && Math.abs(P.v) < .02 && Math.abs(XS.x - st.X) < .05 && Math.abs(XS.v) < 1,   // read-only (S1, 2号 13:1x): both springs at their current targets — the stop rule's thresholds below, whatever the target is (a held lift, a parked drag); the flex is not in it (its floats are exposed above)
        flex: fl ? { sx: fl.out.sx, sy: fl.out.sy, dx: fl.out.dx, target: fl.tg, spec: fl.spec, sp: fl.sp, accel: fl.vi.acceleration, vel: fl.vi.velocity, trace: fl.trace } : null };   // tf = this frame's timestamp: a retarget after it (the up) integrates from here
      if (pTarget === 0 && p < .002 && Math.abs(P.v) < .02 && Math.abs(XS.x - st.X) < .05 && Math.abs(XS.v) < 1 && flexRest && !(st.rm && finger.down)) { stop(); return; }   // R59′b: parked on the item while the finger is down (view.js's box is still the old item until the up)
      tick(frame);
    };
    const stop = (why) => { running = false; glRest(st); st.tap = false; window.__tabLensStop = { why: why || "settled", at: performance.now(), phase, x: XS.x, target: st.X };   // instrument: why the driver stopped (the acceptance reads it)
      nav.classList.remove("tl-on"); for (const k of ["--tl-left", "--tl-w", "--tl-top", "--tl-h"]) nav.style.removeProperty(k);   // rest: the glide shows view.js's own box again (its inline left / width = the selected item)
      if (loop && loop.stop === stop) loop = null; window.__tabLens = null; };
    loop = { stop, retarget: setTargets, st };
    tick(frame);
  };
  const start = (st) => {
    if (MODE === "geometry") return startGeo(st);
    if (loop) { loop.stop(); }
    const nav = st.nav, glide = st.glide, main = st.main;
    const pr = nav.getBoundingClientRect(), mr = main.getBoundingClientRect(), PC = { x: pr.width / 2, y: pr.height / 2 };
    const w0 = parseFloat(glide.style.width) || glide.offsetWidth || (sets[0] || 82), h0 = glide.offsetHeight || 54;   // the resting lens = the item's box (view.js: the button's offsetWidth; 82 on the 440 screen)
    /* the element and its layers */
    const root = el("tabbar-lens tlens on", document.body, "position:fixed;left:0;top:0;width:0;height:0;pointer-events:none;z-index:7");
    const stack = el("stack", root), base = el("base", stack), warp = el("warp", stack), disp = el("disp", warp), ish = el("ish", stack), warpl = el("warpl", stack), displ = el("displ", warpl);
    const copy = el("copy", disp), copyl = el("copy", displ), copyb = el("copy", base);
    // .base: page + platter + items (undisplaced; the fringe taps read it around the lens)
    const bPg = pageCopy(copyb, main, mr), bPl = platterCopy(copyb, main, mr, pr), bIt = itemsCopy(copyb, nav, st.seg, pr);
    // layer 1's copy: page + platter + the items outside the capsule (+ inside at 1 − DestOut)
    const pg = pageCopy(copy, main, mr), pl = platterCopy(copy, main, mr, pr), punchOut = el("punch", copy, "position:absolute;inset:0"), punchIn = el("punchin", copy, "position:absolute;inset:0");
    const itOut = itemsCopy(punchOut, nav, st.seg, pr), itIn = itemsCopy(punchIn, nav, st.seg, pr);
    // layers 2 + 4's copy: the items at 1.16 (label shell)
    const itLab = itemsCopy(copyl, nav, st.seg, pr);
    if (!FRINGE) stack.style.filter = "none";
    /* springs: p = the lift progress (everything rides it), X = the lens's model centre x */
    const P = { x: 0, v: 0 }, XS = { x: st.lastX, v: 0 };
    let pTarget = 1, running = true, last = clockNow(), t0 = last, curSet = 0, abKey = "", phase = "lift", frameN = 0;
    const glideOrigin = () => { glide.style.transformOrigin = `${PC.x - glide.offsetLeft}px ${PC.y - glide.offsetTop}px`; };   // the glide scales about the platter centre, like the platter
    let posSpring = SP_POS;
    const segBox = st.seg.getBoundingClientRect(), navBox = nav.getBoundingClientRect(), track = { min: segBox.left - navBox.left + (parseFloat(getComputedStyle(st.seg).paddingLeft) || 0), max: segBox.right - navBox.left - (parseFloat(getComputedStyle(st.seg).paddingRight) || 0) };   // the items' run in platter coordinates
    const setTargets = () => { const lifted = glide.classList.contains("lift") || glide.classList.contains("lift-sel"), dragging = lifted && nav.classList.contains("drag") && finger.down && finger.x != null;
      pTarget = lifted ? 1 : 0;
      if (dragging) { const left = Math.max(track.min, Math.min(track.max - w0, finger.x - finger.a * w0)); st.X = left + w0 / 2; posSpring = SP_DRAG; phase = "drag"; }   // §6.6: target = the finger, hard clamp, ζ .85 / .2 retargeted on every move
      else { st.X = centreOf(glide); posSpring = lifted ? SP_POS : SP_RELEASE; phase = lifted ? (Math.abs(st.X - XS.x) > .5 ? "move" : "lift") : "drop"; }   // the jump to a pressed item ζ .85 / .4 (§3); after the up ζ .9 / .4 to the item under the finger (§6.6)
      glideOrigin(); };
    setTargets();
    const frame = (now) => { try { frame0(now); } catch (e) { window.__tabLensErr = String(e && e.stack || e); console.error("tab-lens frame", e); stop(); } };
    const frame0 = (now) => {
      if (!running) return;
      const dt = Math.min(1, Math.max(0, (now - last) / 1000)); last = now; frameN++;   // time-based like a CA spring (a stalled frame lands where the clock says; only a > 1 s stall is cut)
      step(P, pTarget, pTarget > .5 ? SP_LIFT : SP_DROP, dt); step(XS, st.X, posSpring, dt);
      const p = Math.max(0, Math.min(1, P.x)), s = 1 + (PLATTER - 1) * p, x = XS.x;
      const wm = w0 + LIFT * p, hm = h0 + LIFT * p, set = setFor(Math.round(wm));
      const cx = PC.x + s * (x - PC.x), cy = PC.y, W = s * wm, H = s * hm, R = H / 2;
      const L = cx - W / 2 - AM, T = cy - H / 2 - AM;                     // the stack box in platter coordinates
      const SL = pr.left + L, ST = pr.top + T;                            // … on screen
      root.style.left = SL + "px"; root.style.top = ST + "px"; root.style.width = (W + 2 * AM) + "px"; root.style.height = (H + 2 * AM) + "px";
      root.style.setProperty("--rr", R + "px");
      for (const e of [warp, warpl, ish]) { e.style.left = AM + "px"; e.style.top = AM + "px"; e.style.width = W + "px"; e.style.height = H + "px"; }
      // the copies keep their screen positions: offsets relative to the stack box (base) / the lens box (warp, warpl)
      const off = (w, dx, dy) => { w.style.left = dx + "px"; w.style.top = dy + "px"; };
      for (const [pgw, dx, dy] of [[bPg, 0, 0], [pg, AM, AM]]) { off(pgw._m, mr.left - SL - dx, mr.top - ST - dy); }   // dx / dy = the layer's origin from the stack's (the lens layers sit AM inside)
      for (const [w, dx, dy] of [[bPl, 0, 0], [pl, AM, AM], [bIt, 0, 0], [itOut, AM, AM], [itIn, AM, AM], [itLab, AM, AM]]) off(w, -L - dx, -T - dy);
      for (const w of [bPl, pl, bIt, itOut, itIn, itLab]) w.style.transform = `scale(${s.toFixed(5)})`;
      for (const w of [bPl, pl]) w.firstElementChild.style.transform = `scale(${(1 / s).toFixed(6)})`;
      itLab.style.setProperty("--titem", (1 + (ITEM - 1) * p).toFixed(5));
      punchIn.style.opacity = (1 - p).toFixed(4);                        // DestOut #76 α 0 → 1 on the lift spring: the real items inside the capsule fade out of the capture
      punchIn.style.clipPath = `inset(0 round ${R.toFixed(3)}px)`;
      punchOut.style.clipPath = `path(evenodd, "M0 0H${W.toFixed(3)}V${H.toFixed(3)}H0Z M${R.toFixed(3)} 0H${(W - R).toFixed(3)}A${R.toFixed(3)} ${R.toFixed(3)} 0 0 1 ${(W - R).toFixed(3)} ${H.toFixed(3)}H${R.toFixed(3)}A${R.toFixed(3)} ${R.toFixed(3)} 0 0 1 ${R.toFixed(3)} 0Z")`;
      if (set !== curSet) { curSet = set; disp.style.filter = `url(#tab-lens-f-bg-${set})`; displ.style.filter = `url(#tab-lens-f-lab-${set})`; if (FRINGE) stack.style.filter = document.getElementById(`tab-lens-f-ab-${set}`) ? `url(#tab-lens-f-ab-${set})` : "none"; }
      for (const id of [`tab-lens-f-bg-${set}`, `tab-lens-f-lab-${set}`]) { const fd = document.querySelector(`#${id} feDisplacementMap`); if (fd) fd.setAttribute("scale", (sOf(id) * p * s).toFixed(3)); }
      if (FRINGE) {                                                       // layer 5: W/H = the capture box (lens screen frame ± 100 clamped to the screen), taps ±S_ab·k × p × s
        const f = document.getElementById(`tab-lens-f-ab-${set}`);
        if (f) { const l0 = SL + AM, t0s = ST + AM, wh = (Math.min(l0 + W + 100, innerWidth) - Math.max(l0 - 100, 0)) / (Math.min(t0s + H + 100, innerHeight) - Math.max(t0s - 100, 0));
          const key = `${set}|${wh.toFixed(4)}|${(p * s).toFixed(4)}`;
          if (key !== abKey) { abKey = key; const m = f.querySelector(`#tab-lens-f-ab-${set}-wh`); if (m) m.setAttribute("values", `${wh.toFixed(4)} 0 0 0 ${(0.5 * (1 - wh)).toFixed(4)}  0 ${(1 / wh).toFixed(4)} 0 0 ${(0.5 * (1 - 1 / wh)).toFixed(4)}  0 0 1 0 0  0 0 0 1 0`);
            const S = parseFloat(f.getAttribute("data-s")) || 16, taps = f.querySelectorAll("feDisplacementMap"), n = taps.length; taps.forEach((t, i) => t.setAttribute("scale", (S * p * s * (1 - 2 * i / (n - 1))).toFixed(3))); } }
      }
      ish.style.opacity = p.toFixed(4);
      nav.style.setProperty("--tplatter-scale", s.toFixed(5)); nav.style.setProperty("--tsel-alpha", (1 - p).toFixed(4));
      window.__tabLens = { t: (now - t0) / 1000, p, v: P.v, x, xv: XS.v, target: st.X, set, s, phase, w: W, h: H, frame: frameN };
      if (pTarget === 0 && p < .002 && Math.abs(P.v) < .02 && Math.abs(XS.x - st.X) < .05) { stop(); return; }
      tick(frame);
    };
    const stop = () => { running = false; root.remove(); nav.style.removeProperty("--tplatter-scale"); nav.style.removeProperty("--tsel-alpha"); glide.style.removeProperty("transform-origin"); if (loop && loop.stop === stop) loop = null; window.__tabLens = null; };
    loop = { stop, retarget: setTargets, st };
    tick(frame);
  };

  /* watch the page's own state: the glide's classes and inline box (view.js's liftTo / glide()), the bar's rebuilds (every render replaces nav's children) */
  let st = null;
  const onMut = (muts) => {
    const nav = document.getElementById("tabs"); if (!nav || !ready) return;
    let rebuilt = false, glideChanged = false;
    for (const m of muts) { if (m.type === "childList" && m.target === nav) rebuilt = true; else if (m.type === "attributes" && m.target !== nav && m.target.classList && m.target.classList.contains("glide") && !(m.attributeName === "style" && loop && m.target.style.transformOrigin && m.oldValue === null)) glideChanged = true; }
    if (rebuilt || !st || st.nav !== nav || st.glide !== nav.querySelector(".glide")) { if (loop) loop.stop("rebuild"); st = attach(nav); if (!st) return; }
    const onChanged = muts.some((m) => m.type === "attributes" && m.attributeName === "class" && m.target !== nav && m.target.matches && m.target.matches(".seg button"));   // the selection moved in this batch (button.on)
    if (!glideChanged && !onChanged) return;
    const g = st.glide, lifted = g.classList.contains("lift") || g.classList.contains("lift-sel"), cur = centreOf(g);
    if (loop) { loop.retarget(); return; }                                        // a retarget while running: the item under the finger moved / the selection landed — setTargets reads view.js's box itself; while dragging the finger rule wins (#7b: `st.X = cur` here overwrote it on every move)
    if (lifted) { st.lastX = st.X; start(st); }                                   // the lift begins from the resting centre the glide had before this mutation
    else if (MODE === "geometry" && onChanged && glideChanged && Math.abs(cur - st.X) > .5) { st.lastX = st.X; st.tap = true; start(st); }   // R33: a quick tap on another item — lift + slide together, the fall on arrival
    st.X = cur;
  };
  const mo = new MutationObserver((muts) => { try { onMut(muts); } catch (e) { window.__tabLensErr = String(e && e.stack || e); console.error("tab-lens", e); } });
  document.addEventListener("visibilitychange", () => { if (document.hidden && loop) loop.stop("hidden"); });   // hidden strips the state (BOARD A6 template): the glide shows view.js's box
  /* R0② (BOARD round 2): the bar's nodes persist across a tab-set change (view.js layoutTabs reconciles in place, ui 807da64) — the page dispatches
     "tabs-changed" on nav after it placed the glide on the selected item; the driver re-reads the bar from the same nodes (a loop in flight is stopped:
     the items' run changed under it) instead of waiting for new nodes. The childList branch of the observer stays for a real rebuild. */
  addEventListener("resize", () => { if (glo && glo.canvas && window.LensWebGL) LensWebGL.clipCanvas(glo.canvas, { y: true }); });   // R96: the bar recentres on a width change
  const onTabsChanged = () => { const nav = document.getElementById("tabs"); if (!nav || !ready) return; if (loop) loop.stop("tabs-changed"); st = attach(nav); if (st) { st.X = centreOf(st.glide); st.lastX = st.X; } };
  const init = async () => {
    if (MODE === "geometry") { injectGeoStyle(); ready = true; } else await loadFilters();
    const nav = document.getElementById("tabs"); if (!nav) return;
    nav.addEventListener("tabs-changed", onTabsChanged);
    st = attach(nav);
    mo.observe(nav, { subtree: true, childList: true, attributes: true, attributeFilter: ["class", "style"] });   // nav itself is static; view.js rewrites its children on every render
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", init); else init();
})();
