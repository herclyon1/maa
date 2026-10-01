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
   time (the loupe's flex stretch is drawn in the geometry mode below, R64, from the first drag frame; the ±1.6 pt wobble after the drop: its source is read — tab-lens-motion.md
   数据核 G10, the platter's presentation x jumps 83 → 0 for one frame +.923 s into the drop and the flex integrator takes the kick — but not drawn: the
   integrator's acceleration form and updateFlex's target clamp are unread and this page's chain answers the same kick in the other direction (老网页核
   G10, same file); a quick tap without the +140 ms lift = lift + slide together, the fall on arrival — tab-lens-motion.md §3a R33, driven below). The drag (nav.drag while lifted) follows the
   finger by tab-lens-motion.md §6.6: target = finger x − a·W + W/2 (a = the press point's fraction in the item), the left edge hard-clamped to
   the items' run, spring ζ .85 / .2 retargeted on every move, no rubber band; after the up ζ .85 / .4 (R106: §6.9's "no gesture" pair) to the item under the finger (view.js's
   choice). The flex stretch (loupe sX / sY, drift tx = sX(1 − sX)·55): this layered mode does not draw it; the geometry mode (default) does (R64).
   Not drawn yet (material, the ui session's tokens): the KeyFill highlight, the ring shadow, the dark line, the little glow (α 0 → .2).
   Instrument: window.__tabLens = the per-frame state (t s since the start, p, x, v, target, set, s, phase; settled = both springs at their targets, S1). */
/* GEOMETRY MODE (BOARD.md #7a, 2026-09-20 — the default tonight; ?tlens=material restores the layered lens above): no material at all — the page's own
   .glide (the selection view, index.html's rules for its glass stay) is driven per frame: size (w0 + 16p) × (54 + 16p) about the item's centre
   (tab-lens-motion.md §0 / §4: 94×54 → 110×70 read as +16 on both axes; r = h/2 through the capsule's border-radius), lift ζ 1 / .25, drop ζ 1 / .4,
   position ζ .85 / .4 to a pressed item, the drag by §6.6 (ζ .85 / .2, the finger rule, hard clamp) and ζ .85 / .4 (R106) to the item under the finger after
   the up — all through Motion.spring (motion.js #1). The lift's delays are the page's own timers (+140 ms on another item, +125 ms on the selected,
   interaction spec §2 T1 / T3 via tokens.css --ios-touch-tab-*-delay): the spring starts at the class the page sets. The style below (injected) takes the
   glide's CSS scale rules and transitions out of the way while the driver owns the box. Not drawn: the ±1.6 pt wobble after the drop (see above). Unread: the spec's
   119×64 / 103×63 vs the read 110×70.
   R64 (界面, flex-interaction.md §1–§3, tab-lens-motion.md §6.4 / §6.6): the flex stretch while the lens moves — view.js's B5 chain (globals
   flexIntegrator / flexSpec / flexTargets / springStep, the same _UIFlexInteraction reading) fed with this lens's own presented centre every frame;
   the variant from the MODEL bounds (§7.4: a step at lift / unlift — lifted (w0 + 16) × (h0 + 16) → d = 70 → t = 1 → the loupe row: pts 100, min .75,
   max 1.15, N 2500, scaleSpring ζ 1 / .5, tracking ζ .9 / .5 while the finger is down); targets sX / sY / drift by §3 (the [0.9, 1.1] hard clamp on the
   targets), the three floats on the flex spring; presented box = W·sX × H·sY about the centre x + sX·dx (§6.4: the drift is added in the scaled
   coordinates). Active from the first frame the lens travels — the drag, the press-glide to another item and the quick tap (界面 09-24 re-read, see
   the flex block below: native peaks 118.8 × 60.0 tap / 126.1 × 63.2 press-glide) — until the floats settle after the up. Not read: the retargetImpulse gap (§6.4: the native peak 1.109 vs the chain's 1.085 — no impulse in the loupe spec), the interaction
   pulse draws nothing here: the loupe variant's four interactionPulse keys are ScalePtsX / Y 0, DriftRatio 0, NormalizationFactor 1
   (tools/uiprobe/uiprobe-obj-spec-_UIFlexInteractionLoupeVariantSpec.json; seg-lens-refraction.md line 321 table) → scale × lerp(1, (W − 0)/W, p) = 1. Instrument: window.__tabLens.flex = { sx, sy, dx, target, spec, sp, accel, vel, trace }.
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
  const SP_LIFT = { z: 1, w: 2 * Math.PI / .25 }, SP_DROP = { z: 1, w: 2 * Math.PI / .4 }, SP_POS = { z: .85, w: 2 * Math.PI / .4 };
  /* the SIZE's fall is not SP_DROP: setLifted:NO runs two blocks (tab-lens-motion.md §5a R36, 0x1c54c82b8) — block ① on spec.unLiftSpring (Large = ζ 1 / .25,
     §5a R16 probe), block ② on the hard-coded ζ 1 / .4 (the material / displacement amount). The §2 table's lensPres (③ drop, the same probe) follows
     block ①: width excess ratio to the .033 frame .64 / .36 / .19 / .09 at .067 / .100 / .133 / .167 s vs ζ 1 / .25 .63 / .36 / .19 / .10 (ζ 1 / .4:
     .80 / .59 / .42 / .29), start ≈ 116 × 74 = the R108 lifted size. Before (2026-09-24 用户「单点玻璃钮就会出现回落动画异常」): the size rode p on ζ 1 / .4,
     100 ms into the fall 53 % of the lift left against the native 29 %. The lift itself is ζ 1 / .25 for both (Large liftSpring = §0). Geometry mode only. */
  const SP_UNLIFT = { z: 1, w: 2 * Math.PI / .25 };   // tab-lens-motion.md §0 / §4: lift, drop, the jump to a pressed item (the ① trace)
  const SP_DRAG = { z: .85, w: 2 * Math.PI / .2 }, SP_RELEASE = { z: .85, w: 2 * Math.PI / .4 };   /* R106 (tab-lens-motion.md §6.9 ③ / R106): after the up the highlight is cleared and the "no gesture" pair .85 / .4 drives the frame + lens to the selected item (0x1c50e8774); the .9 / .4 of before was _UIFloatingTabBar's, not this bar's */
  const DROP_WITHIN = 8;                                                    /* R106 (§6.9 ①): setLifted(false) only when there is no highlight AND |target − presented| < 8 pt (0x1c50e8634–0x1c50e8650) — after the up the lens slides first and falls within 8 pt of its target (the R33 tap's "arrival at .5 pt" was that rule seen late) */
  /* G10 (tab-lens-motion.md「数据核 G10」① / ⑤, probe lenstrace C / C3 runs; flex-interaction.md §8): after the fall starts the platter's presented frame x reads 0 for one frame
     (+.923 s, C3 +.933) — the flex's point goes through the presentation layers to the outermost space, so it jumps left by the platter's x for that frame and the
     integrator kicks the targets (1.221 / .723 …); the fall group's completion block deactivates the flex at +1.283 s (C3: up +1.308 − fall +.025) — scaleX set to 1
     on that frame, scaleY back on its spring. The page's platter x = the nav's left in the viewport. */
  const FLEX_KICK_S = .923, FLEX_OFF_S = 1.283;
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
      if (wk && WK_ON) wk.postMessage({ k: "gesture", gid: ++wkGid });   // the worker's per-gesture counts start here (fluency-rec.js lw; its line for the last press asked for its report in its own capture listener, earlier)
      finger.down = true; finger.a = a; finger.x = e.clientX - r.left; finger.moved = false; finger.x0 = e.clientX; finger.last = { t: e.type, pt: e.pointerType, id: e.pointerId, at: performance.now(), target: e.target && e.target.tagName ? e.target.tagName.toLowerCase() + "." + (e.target.className || "") : null };
      if (st && st.nav === nav) st.pressed = !RM();   // R59′d: the lift belongs to the down itself (no highlight → no lift under Reduce Motion)
      if (loop) loop.retarget();
      else if (MODE === "geometry" && st && st.nav === nav && ready) { const tx = rmTarget(st); window.__tabLensRM = { at: performance.now(), target: tx, X: st.X, started: !RM() || (tx != null && Math.abs(tx - st.X) > .5) }; if (!RM() || (tx != null && Math.abs(tx - st.X) > .5)) { st.lastX = st.X; start(st); } } }, true);   // R59′d: the driver starts on the down (its first tick = the lift's t0); RM: only when there is somewhere to slide   // R59′b: the slide begins at the down, no lift
    nav.addEventListener("pointermove", (e) => { finger.last = { t: e.type, pt: e.pointerType, id: e.pointerId, at: performance.now() }; if (!finger.down) return; finger.x = e.clientX - nav.getBoundingClientRect().left; if (Math.abs(e.clientX - finger.x0) >= 1) finger.moved = true; if (loop) loop.retarget(); }, true);
    for (const t of ["pointerup", "pointercancel"]) nav.addEventListener(t, (e) => { if (wk && WK_ON && finger.down) wk.postMessage({ k: "up" }); finger.last = { t: e.type, pt: e.pointerType, id: e.pointerId, at: performance.now() }; finger.down = false; finger.x = null; finger.moved = false; if (st) st.pressed = false; if (loop) loop.retarget(); }, true);
  };
  /* R59′b: the Reduce Motion target = the §6.6 finger rule (finger x − a·W + W/2 = the pressed item's centre at the down), hard-clamped to the items' run */
  const rmTarget = (st) => { if (finger.x == null) return null; const w = parseFloat(st.glide.style.width) || st.glide.offsetWidth; const navBox = st.nav.getBoundingClientRect(), segBox = st.seg.getBoundingClientRect();
    const min = segBox.left - navBox.left + (parseFloat(getComputedStyle(st.seg).paddingLeft) || 0), max = segBox.right - navBox.left - (parseFloat(getComputedStyle(st.seg).paddingRight) || 0);
    return Math.max(min, Math.min(max - w, finger.x - finger.a * w)) + w / 2; };
  const attach = (nav, redraw = true) => {
    const glide = nav.querySelector(".glide"), seg = nav.querySelector(".seg"), main = document.getElementById("app");
    if (!glide || !seg || !main) return null;
    nav.classList.add("tlens"); trackFinger(nav);
    const st = { nav, glide, seg, main, X: centreOf(glide), lastX: centreOf(glide) };
    /* redraw false (an animated tabs-changed): the canvas still follows the bar's new size (glAttach swaps / creates the lens; the nav is already at its final
       width — the leaving buttons are position:absolute, view.js layoutTabs), but the textures are left to "tabs-settled": painted here they came from the
       platter and buttons of the item-set animation's first frame (the 09-23 bug below), and the 20–28 ms redrawNow landed in the tap's first frames
       (动效-0930-透镜重挂 probe: backdropMs 20–28 of a 20–28 ms seg:gl-redraw-task, the warm-up's gl.finish 0–1 ms; the settled repaint 3–4 ms) */
    if (MODE === "geometry" && GL_ON) glAttach(st).then((g) => { if (redraw && g && g.nav === nav) { try { g.lens.redrawBackdrop(); } catch (e) {} } });   // the items may have changed (tabs-changed): the textures again, at idle in the package's own way
    return st;
  };
  /* ---- geometry mode ---- */
  /* the driver's output goes to custom properties on nav (not the glide: the glide's inline left / width stay view.js's and are the TARGET the
     observer reads; a per-frame write on the glide itself would come back through the observer as a new target). While .tl-on is set the box
     rules below take the glide over — `!important` because the values they replace are inline (view.js's left / width) */
  const GEO_CSS = `nav.tabs.tlens .glide.lift,nav.tabs.tlens .glide.lift-sel,nav.tabs.tlens.drag .glide.lift-sel{scale:1 1}
nav.tabs.tlens.tl-on .glide,nav.tabs.tlens.tl-on.drag .glide{transition:none;left:var(--tl-left) !important;width:var(--tl-w) !important;top:var(--tl-top) !important;height:var(--tl-h) !important;bottom:auto !important}
nav.tabs.tlens.tl-wk .glide{visibility:hidden}`;   /* tl-wk: the worker's canvas draws the glide (startGeo paint) */
  /* only while the driver runs (.tl-on): outside it the page's own CSS slide holds the glide (index.html: left / width on --ios-motion-lens-duration /
     -easing, the probe's ζ .85 / .4 as an easing). A plain tap on another tab (no lift — the up came before +140 ms) is driven: lift + slide at once, the
     fall starting on the frame the slide arrives (tab-lens-motion.md §3a R33, the 60 / 90 ms records; the R33 block in startGeo, the observer below) */
  const injectGeoStyle = () => { if (document.getElementById("tab-lens-geo-style")) return; const s = document.createElement("style"); s.id = "tab-lens-geo-style"; s.textContent = GEO_CSS; document.head.appendChild(s); };
  const spring = (st, target, sp, dt) => (window.Motion && Motion.spring ? Motion.spring(st, target, [sp.z, 2 * Math.PI / sp.w], dt) : step(st, target, sp, dt));
  /* ---- R2 (b): the material through lens-webgl.js, over the bar (验收's call: a flat platter fill — the page under the bar cannot be drawn into a canvas,
     标不可表达; the items' copies, the displacement, the KeyFill line, the ring shadow, the dispersion are the package's, from the tab5 family's maps
     and keys (tab5/lens-filter.svg data-s 40 / 48 (98) / fringe 16; tab5/lens-field.json heights 54 … 70; tab-lens-native.md §0 / §3: Backdrop +9/36,
     ClearGlass −17.5/11.2, ContentLensing −14/11.2 are the maps' formula, README §0.8.1). The lift rides the 98 set (the lifted size) stretched over the
     growing box, as the segment lens rides its 220 set (README §0.3). The items' 1.16 scale of the SelectedContentView copy: drawn in the shader (lens-webgl.js
     itemScaled, items in glFrame). Not drawn: the blurred page in the platter (不可表达), _UITabSelectionView's own α 1 → 0 (the glide stays the geometry driver's).
     ?tlens-gl=0 leaves the canvas out (geometry only). */
  const GLM = 24;                                                            // the canvas extends the bar's box by this on every side (the lifted 98 × 70 over a 62 bar + the fringe wrapper 16)
  const GL_ON = q.get("tlens-gl") !== "0" && !!window.LensWebGL && LensWebGL.available();
  let glSets = null, glHeights = null, glo = null, glReady = null;
  /* ---- the worker path (动效 10-01, 验收's dispatch; BOARD/evidence/动效-1001-镜片Worker/README.md): on Blink with OffscreenCanvas the lens canvas is handed to
     assets/lens/lens-worker.js (transferControlToOffscreen) — Chrome on Android runs the page's rAF at 60 Hz once no input arrives (ThrottleMainFrameTo60Hz; the
     phone's flu 10-01: fi 8.3 while the finger is down, 16.6 after the lift) and a Dedicated Worker's own rAF is not throttled (the same records: a worker rAF
     at 8.3 ms after the lift). The driver (springs, flex, DOM) stays here: while the finger is down every frame's setState goes to the worker (drawn at its
     next rAF), after the lift the rest of the motion goes once as a table (startGeo TABLE) the worker plays on its own clock. Off: WebKit (CSS.supports("mix-blend-mode",
     "plus-darker"), menu.js's test — the throttle this answers is Chrome's, the iPhone keeps the main-thread lens as it is), no Worker / OffscreenCanvas /
     transferControlToOffscreen, the instrument clocks (?tlens-clock), ?lensworker=0, and ?accept unless ?lensworker=1 (accept-run.py's default CDP virtual
     time starts Chrome with --enable-begin-frame-control: the worker's rAF got no frames there — the G4 / R2 rows read 0 drawn frames; on the wall clock
     with ?lensworker=1 the tab rows pass as on the main thread) — the main-thread lens below, unchanged. The worker answering "fail"
     (no webgl2 in it, a compile error) or dying drops every worker canvas and rebuilds the main-thread lens (wkFail). */
  const LWSIM = q.get("lwsim") === "1";
  let WK_ON = MODE === "geometry" && CLOCK === "raf" && q.get("lensworker") !== "0" && !(q.has("accept") && q.get("lensworker") !== "1") && !LWSIM && !(window.CSS && CSS.supports && CSS.supports("mix-blend-mode", "plus-darker"))
    && typeof Worker === "function" && typeof OffscreenCanvas === "function" && !!(window.HTMLCanvasElement && HTMLCanvasElement.prototype.transferControlToOffscreen);
  let wk = null, wkSeq = 0, wkGid = 0, wkRid = 0, glRun = 0; const wkP = new Map(), wkWait = new Map();
  const wkWorker = () => { if (wk) return wk; const base = (me && me.src) || location.href;
    wk = new Worker(new URL("lens-worker.js" + new URL(base).search, base));   // the page's ?v= on the worker (and through it on its importScripts of lens-webgl.js): the same build, the service worker's copy offline
    wk.onmessage = (e) => { const m = e.data, P = m.id != null ? wkP.get(m.id) : null;
      switch (m.k) {
        case "ready": if (P) { P.setsS = m.sets; Object.assign(P.stats, m.stats); P.stats.warmMs = m.warmMs; P.res(true); } break;   // the constants lens-webgl.js reports (labMode, rmax, labelStages, fields, linComp …)
        case "sets": if (P) P.setsS = m.sets; break;
        case "fail": if (P) P.res(false); wkFail("init: " + m.err); break;
        case "err": window.__tabLensErr = "worker: " + m.err; break;
        case "drew": if (P) P.drewRun = m.r; break;
        case "stats": if (P && !(m.q < P.restQ)) { P.stats.last = m.last; P.stats.frames = m.frames; P.stats.set = m.set; } break;   // a frame drawn before the last rest was asked for is not the canvas's state any more
        case "lost": if (P) P.lost = true; break;
        case "restored": if (P) { P.lost = false; P.restored = (P.restored || 0) + 1; } break;
        case "report": case "draws": { const f = wkWait.get(m.rid); wkWait.delete(m.rid); if (f) f(m.k === "report" ? m.lw : m.t); break; }
      } };
    wk.onerror = (e) => wkFail("worker: " + (e && e.message));
    if (q.has("accept") || q.get("lwstats") === "1") wk.postMessage({ k: "echo", on: true });   // stats.last per drawn frame back here (the acceptance's G4 / R2 rows read them); not in production
    return wk; };
  const wkFail = (why) => { if (!WK_ON) return; WK_ON = false; window.__tabLensWKErr = why; console.warn("tab-lens worker: " + why + " — the main-thread lens");
    const elOf = (g) => (g.canvas.parentElement && g.canvas.parentElement.classList.contains("lens-clip") ? g.canvas.parentElement : g.canvas);
    for (const [k, v] of [...glWait]) if (v.g.lens.wk) { glWait.delete(k); v.el.remove(); }
    if (glo && glo.lens.wk) { elOf(glo).remove(); glo.nav.classList.remove("tl-wk"); glo = null; }
    for (const P of wkP.values()) P.res(false); wkP.clear(); try { if (wk) wk.terminate(); } catch (e) {} wk = null;
    if (st && st.nav) glAttach(st).then((g) => { if (g) { try { g.lens.redrawBackdrop(); } catch (e) {} } }); };
  /* the proxy: the lens object glAttach / glSwap / glFrame / the acceptance use (ready, sets, stats, gl.isContextLost, setState, redrawBackdrop, destroy), its GL in the
     worker. The backdrop is painted HERE as before (lens-webgl.js painter: the page's callbacks into the attached scratch canvases — WebKit's text smoothing note there),
     then handed over as ImageBitmaps (premultiply / no colour conversion = the canvas upload's flags). Messages before the init (the paint is async) wait in a queue. */
  const wkCreate = (canvas, opts) => { const w = wkWorker(), id = ++wkSeq; let res; const ready = new Promise((r) => { res = r; });
    const DPR = opts.dpr, W = opts.width, H = opts.height, region = { x: 0, y: 0, w: W, h: H }, BO = { premultiplyAlpha: "premultiply", colorSpaceConversion: "none" };
    const off = canvas.transferControlToOffscreen();
    const PT = LensWebGL.painter(opts, () => ({ width: W, height: H, region }), DPR);
    let inited = false, redrawPending = 0, q = 0; const queue = [];
    const send = (m, tr) => { m.id = id; m.q = ++q; if (!inited) queue.push([m, tr]); else w.postMessage(m, tr || []); };
    const P = { wk: true, id, canvas, ready, res, lost: false, drewRun: 0, setsS: {}, stats: { frames: 0, last: null, set: 0, warmMs: null, prewarm: {} },
      get sets() { return P.setsS; }, gl: { isContextLost: () => P.lost },
      setState: (s) => { if (s && s.lift > 0) { send({ k: "state", s }); return; } send({ k: "rest" }); P.restQ = q; P.stats.last = { lift: 0, pd: s && s.pd != null ? s.pd : 1, platterAlpha: 0, platterColorAlpha: 0, t: performance.now() }; },   // lift 0 = glRest: the worker clears at its next rAF; stats.last says so now (the main-thread lens's clear is synchronous; the acceptance's R2 row reads it a frame after the stop)
      table: (T, tr) => send(Object.assign({ k: "table" }, T), tr), cancel: () => send({ k: "cancel" }), activate: () => send({ k: "active" }),
      redrawBackdrop: (o) => { const go = () => { redrawPending = 0; paint().then(([page, labels]) => send({ k: "bitmaps", page, labels }, [page, labels]), () => {}); };   // deferred to the next task like lens-webgl.js's (the tap's first frames stay free)
        if (o && o.sync) { go(); return; } if (!redrawPending) redrawPending = setTimeout(go, 0); },
      destroy: () => { send({ k: "destroy" }); PT.remove(); wkP.delete(id); }, lose: () => send({ k: "lose" }), restore: () => send({ k: "restore" }) };
    const paint = () => { const t0 = performance.now(), { pg, p } = PT.scratchCanvases(); PT.draw2d(pg, "page"); if (opts.labelsDirect) PT.drawLabelsDirect(p); else PT.draw2d(p, "labels");
      const li = opts.labelsDirect ? p : PT.labelsAlpha(pg, p); P.stats.prewarm.backdropDrawMs = performance.now() - t0; try { performance.measure("seg:gl-redraw", { start: t0, end: performance.now() }); } catch (e) {}
      return Promise.all([createImageBitmap(pg, BO), createImageBitmap(li, BO)]); };
    const abs = (u) => new URL(u, location.href).href, sets = {};
    for (const [k, s] of Object.entries(opts.sets)) sets[k] = Object.assign({}, s, { bg: abs(s.bg), lab: abs(s.lab), ab: abs(s.ab) });   // the worker's own URL base is assets/lens/
    const wo = { sets, preload: opts.preload, dpr: DPR, width: W, height: H, margin: opts.margin, ink: opts.ink, warm: opts.warm, labelsDirect: opts.labelsDirect, rmax: opts.rmax, labelStages: opts.labelStages, search: location.search };
    wkP.set(id, P);
    paint().then(([page, labels]) => { w.postMessage({ k: "init", id, canvas: off, opts: wo, bitmaps: { page, labels } }, [off, page, labels]); inited = true; for (const [m, tr] of queue) w.postMessage(m, tr || []); queue.length = 0; },
      (e) => { res(false); wkFail("paint: " + (e && e.message || e)); });
    return P; };
  /* instrument / recorder hook: on() = the worker draws the bar's lens; report(cb) = this gesture's frames (fluency-rec.js lw); draws(cb) = the last 600 draws
     [epoch ms, cx, w, h, lift]; lose() / restore() = WEBGL_lose_context on the worker's context; proxy() = the lens proxy; made() / live() = worker canvases */
  window.__tabLensWK = { on: () => !!(WK_ON && glo && glo.lens.wk), path: () => (glo ? (glo.lens.wk ? "worker" : "main") : null), err: () => window.__tabLensWKErr || null,
    report: (cb) => { if (!wk || !WK_ON) { cb(null); return; } const rid = ++wkRid; wkWait.set(rid, cb); if (wkWait.size > 20) wkWait.delete(wkWait.keys().next().value); wk.postMessage({ k: "report", rid }); },
    draws: (cb) => { if (!wk) { cb(null); return; } const rid = ++wkRid; wkWait.set(rid, cb); wk.postMessage({ k: "draws", rid }); },
    lose: () => { if (glo && glo.lens.wk) glo.lens.lose(); }, restore: () => { if (glo && glo.lens.wk) glo.lens.restore(); }, proxy: () => glo && glo.lens,
    made: () => wkSeq, live: () => wkP.size };   // made = worker canvases created so far, live = not destroyed (GL_KEEP 2: the other shift's waits built)
  const glLoad = async () => { if (glReady) return glReady; glReady = (async () => { try {
      const svgTxt = await (await fetch(FAMILY + "lens-filter.svg")).text(); const svg = document.importNode(new DOMParser().parseFromString(svgTxt, "text/html").querySelector("svg"), true);
      svg.setAttribute("data-tab-lens-gl", FAMILY); svg.setAttribute("aria-hidden", "true"); svg.style.cssText = "position:absolute;width:0;height:0;display:none"; document.body.appendChild(svg);   // the maps' hrefs and data-s for setsFromFilters; no engine fix (the GPU samples the plain maps); display:none: a data table only, out of every whole-document style recalc (1278 elements; 数据 09-30, see view.js segFilterSvg)
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
  /* One lens per bar size, kept (中继二 09-30, segall 续): a shift change swaps the tab set (早班 5 items 416 wide / 晚班 3 items 290), and every switch used
     to destroy the lens and create a new one — a fresh WebGL context, the shader compile (getShaderParameter), the map loads and texture uploads: 52.6 % of
     the samples inside the segment's release handler, its own time 14–18 ms of a 45–66 ms release frame (simulator B timeline, BOARD/evidence/segall-0930/tl/).
     The lens of the other size now waits off the DOM and is put back when the bar returns to it (the caller's deferred redrawBackdrop repaints its textures
     from the settled bar, as after a create); at most GL_KEEP wait, the least recently used destroyed; a context lost while detached is dropped and built anew. */
  /* GL_KEEP 2 (数据 10-01, 验收 02:50): the other shift's width is built ahead at idle (glWarmOther below) and kept, so the first shift change after load
     swaps instead of creating in the segment's release task (Chrome ×4: glAttach 56–60 ms there, evidence/数据-1001-分段按下 cold3 / cold4) */
  const GL_KEEP = 2, glWait = new Map(), glKey = (w, h) => w + "x" + h;
  const glStash = () => { if (!glo) return; const el = glo.canvas.parentElement && glo.canvas.parentElement.classList.contains("lens-clip") ? glo.canvas.parentElement : glo.canvas; el.remove();
    const k = glKey(glo.w, glo.h), old = glWait.get(k); if (old && old.g !== glo) { try { old.g.lens.destroy(); } catch (e) {} } glWait.delete(k); glWait.set(k, { g: glo, el }); glo = null;
    while (glWait.size > GL_KEEP) { const [k0, v] = glWait.entries().next().value; glWait.delete(k0); try { v.g.lens.destroy(); } catch (e) {} } };
  const glSwap = (nav, w, h) => { const k = glKey(w, h), v = glWait.get(k); if (v) glWait.delete(k);   // taken out before the stash, so the eviction never picks it
    const ok = v && v.g.nav === nav && !v.g.lens.gl.isContextLost(); if (v && !ok) { try { v.g.lens.destroy(); } catch (e) {} }
    glStash(); if (!ok) return null;
    for (const e of nav.querySelectorAll(":scope > canvas.tlens-gl, :scope > .lens-clip")) e.remove(); nav.appendChild(v.el); LensWebGL.clipCanvas(v.g.canvas, { y: true }); glo = v.g; if (glo.lens.wk) glo.lens.activate(); return glo; };   // the worker counts its frames for the active one (fluency-rec lw)
  /* pre = { w, h }: build a lens of that size off the DOM and leave it waiting in glWait (glWarmOther); glo and the bar are not touched */
  const glHave = (nav, w, h) => (glo && glo.nav === nav && glo.w === w && glo.h === h) || glWait.has(glKey(w, h));
  const glAttach0 = async (st, pre) => { if (!GL_ON) return null; if (!(await glLoad())) return null; const nav = st.nav;
    if (pre) { if (glHave(nav, pre.w, pre.h)) return null; } else { if (glo && glo.nav === nav && glo.w === nav.offsetWidth && glo.h === nav.offsetHeight) return glo; if (glSwap(nav, nav.offsetWidth, nav.offsetHeight)) return glo; }
    await glPrefetchIcons(nav); const navW = pre ? pre.w : nav.offsetWidth, navH = pre ? pre.h : nav.offsetHeight; if (!navW) return null;
    if (pre && glHave(nav, navW, navH)) return null;
    if (!pre && glo && glo.nav === nav && glo.w === navW && glo.h === navH) return glo;   // a concurrent attach finished during the awaits (R96: two canvases used to pile up in the bar)
    if (!pre && glSwap(nav, navW, navH)) return glo;   // the size moved during the awaits, or a concurrent attach left a lens of another size: keep it, and reuse a waiting one
    if (!pre) for (const e of nav.querySelectorAll(":scope > canvas.tlens-gl, :scope > .lens-clip")) e.remove();   // R96: never two canvases (a stale one reached x 516 in 界面's log)
    const canvas = document.createElement("canvas"); canvas.className = "tlens-gl"; canvas.style.cssText = `position:absolute;left:${-GLM}px;top:${-GLM}px;width:${navW + 2 * GLM}px;height:${navH + 2 * GLM}px;pointer-events:none;z-index:3`; if (!pre) nav.appendChild(canvas);
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
    let lens; try { lens = WK_ON ? wkCreate(canvas, opts) : LensWebGL.create(canvas, opts); } catch (e) { console.warn("tab-lens gl", e); canvas.remove(); return null; }   // the worker path: the canvas goes to lens-worker.js (above)
    if (!lens) { canvas.remove(); return null; }
    if (pre) { const g = { nav, canvas, lens, w: navW, h: navH, top }; glWait.set(glKey(navW, navH), { g, el: canvas });   // glSwap appends and clips it when the bar takes this size
      while (glWait.size > GL_KEEP) { const [k0, v] = glWait.entries().next().value; glWait.delete(k0); try { v.g.lens.destroy(); } catch (e) {} } return g; }
    LensWebGL.clipCanvas(canvas, { y: true });   // R96: clipped to the viewport (nav ± 24 reaches x 452 / y 968 on a 440 × 956 screen with five tabs) — re-measured on resize below
    glo = { nav, canvas, lens, w: navW, h: navH, top }; if (lens.wk) lens.activate(); return glo; };
  /* The other shift's bar: view.js layoutTabs — 早班 three games = 5 tabs, 晚班 one = 3. Its size is measured on an invisible clone of the bar with that many
     buttons (the same CSS; appended beside the nav, outside tab-lens's own observer on the nav), then that lens is built at idle, never during a touch or a
     glide. Any other count builds nothing ahead (the switch creates as before); a hidden bar (< 2 tabs) clones hidden, measures 0 and builds nothing.
     The measure is one forced layout of the clone, at idle. */
  const GL_OTHER = { 5: 3, 3: 5 };
  let glWarmQ = 0;
  const glOtherSize = (nav, n2) => { const c = nav.cloneNode(true); c.removeAttribute("id"); c.setAttribute("aria-hidden", "true"); c.inert = true;
    for (const e of c.querySelectorAll("canvas, .lens-clip")) e.remove(); for (const e of c.querySelectorAll(":scope > button")) e.remove();   // removed-set buttons parked on the nav
    const seg = c.querySelector(":scope > .seg"); if (!seg) return null; const bs = [...seg.querySelectorAll(":scope > button")]; if (!bs.length) return null;
    while (bs.length > n2) bs.pop().remove(); while (bs.length < n2) { const b = bs[bs.length - 1].cloneNode(true); b.classList.remove("on"); seg.appendChild(b); bs.push(b); }
    c.style.visibility = "hidden"; c.style.pointerEvents = "none"; nav.after(c); const w = c.offsetWidth, h = c.offsetHeight; c.remove(); return w ? { w, h } : null; };
  const glWarmOther = (st) => { const nav = st.nav, seg = nav.querySelector(":scope > .seg"); if (!seg || glWarmQ) return; const n2 = GL_OTHER[seg.querySelectorAll(":scope > button").length]; if (!n2) return;
    glWarmQ = 1; const idle = (f) => (window.requestIdleCallback ? requestIdleCallback(f, { timeout: 3000 }) : setTimeout(f, 500));
    let tries = 0; const go = () => { if ((finger.down || loop || nav.classList.contains("tl-on")) && ++tries < 20) { setTimeout(() => idle(go), 500); return; }   // never inside a touch or a glide (≤ 10 s of waiting)
      if (tries >= 20) { glWarmQ = 0; return; }
      glWarmQ = 0; if (!nav.isConnected || st.nav !== nav || document.hidden) return; const sz = glOtherSize(nav, n2); if (!sz || glHave(nav, sz.w, sz.h)) return;
      const t0 = performance.now(); glAttach0(st, sz).then((g) => { if (g) try { performance.measure("tab:gl-warm-other", { start: t0, end: performance.now() }); } catch (e) {} }); };
    setTimeout(() => idle(go), 500); };
  const glAttach = async (st, pre) => { const g = await glAttach0(st, pre); if (!pre && g) glWarmOther(st); return g; };
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
  /* r = the driver run (the worker answers its first lifted draw: startGeo hides the glide then), t = the frame's epoch time (the worker logs the age of what it draws) */
  const glFrame = (st, p, x, W, H, pad, h0, run, tf) => { if (!glo || glo.nav !== st.nav) return; const nb = st.nav.getBoundingClientRect(); const l = nb.left + x - W / 2, t = nb.top + pad + h0 / 2 - H / 2;
    const wh = (Math.min(l + W + 100, document.documentElement.clientWidth) - Math.max(l - 100, 0)) / (Math.min(t + H + 100, innerHeight) - Math.max(t - 100, 0));   // formula §3b.6: the capture box = frame ± 100 clamped to the screen
    try { glo.lens.setState({ cx: x + GLM, cy: pad + h0 / 2 + GLM, w: W, h: H, lift: p, pd: p, wh, platter: { rgba: st.selRest || (st.selRest = selRest(st.nav)), alpha: 1 - p }, items: { scale: 1 + (ITEM - 1) * p, cy: (st.itemC || (st.itemC = itemCentres(st.nav))).cy, cx: st.itemC.cx }, r: run, t: tf == null ? undefined : performance.timeOrigin + tf }); } catch (e) { window.__tabLensErr = String(e && e.stack || e); } };
  /* the SelectedContentView copy's items 1 → 1.16 about their own centres on the lift progress (tab-lens-native.md §3, tab-lens-motion.md §4: one ζ 1 / .25
     spring for every lift quantity, the drop ζ 1 / .4 back) — lens-webgl.js itemScaled samples the label texture at c + (q − c) / s, c = the nearest item's
     centre; the centres in the backdrop's coordinates (nav-relative + GLM, as the labels callback draws them), read once per press */
  const itemCentres = (nav) => { const nb = nav.getBoundingClientRect(), bs = [...nav.querySelectorAll(".seg button")].map((b) => b.getBoundingClientRect());
    return { cy: bs.length ? bs[0].top + bs[0].height / 2 - nb.top + GLM : 0, cx: bs.map((r) => r.left + r.width / 2 - nb.left + GLM) }; };
  const glRest = (st) => { if (!glo || glo.nav !== st.nav) return; try { glo.lens.setState({ cx: 0, cy: 0, w: 82, h: 54, lift: 0 }); } catch (e) {} };
  /* the flex integrator with a copy (动效 10-01, the lift's table below runs a copy of the driver ahead): view.js's flexIntegrator keeps its state in a closure,
     so the copy replays the samples it was fed since its last reset (its own rule: a gap > .05 s re-seeds it — the log restarts there), bit for bit */
  const mkVI = () => { const vi = flexIntegrator(), log = []; let lt = null;
    return { add(p, t) { if (lt !== null && t - lt > .05) log.length = 0; log.push(p, t); if (lt === null || t > lt) lt = t; vi.add(p, t); }, get velocity() { return vi.velocity; }, get acceleration() { return vi.acceleration; },
      clone() { const c = mkVI(); for (let i = 0; i < log.length; i += 2) c.add(log[i], log[i + 1]); return c; } }; };
  /* TABLE (动效 10-01; BOARD/evidence/动效-1001-镜片Worker): after the lift no input reaches the page, Chrome on Android drops its rAF to 60 Hz (ThrottleMainFrameTo60Hz)
     while the lens canvas lives in a worker whose rAF is not throttled (lens-worker.js). On the first frame without the finger the driver runs a COPY of itself ahead —
     the same integ() below at the timestamps now + k/120 s (a fixed 1/120 s grid: the flex integrator's EMA is per sample and the R106 arrival / G10 kick / FLEX_OFF
     rules are sequential, so the motion is not a pure function of t for Motion.sample; 120 Hz = the display's frames, the rate the driver runs at while the finger
     is down), with the DOM / finger read once (snap) — to the stop rule, ≤ T_MAX nodes — and posts the nodes once (rows: cx, w, h, p, wh and their time derivatives
     from the springs' own velocities, for the worker's Hermite between nodes). The driver itself then REPLAYS the same nodes (the same code on the same inputs: the
     same numbers) for the DOM side (--tl-*, the classes, the stop), so the canvas and the glide never part. Any retarget (a press, the observer, tabs-changed,
     hidden, stop) first catches the driver up to the node at that moment (what the worker shows), cancels the table, then retargets from there. ?lwsim=1 (an
     instrument): the table and its replay without the worker — the main-thread GL draws the replayed nodes (the driver at a fixed 120 Hz, for the curve checks). */
  const TDT = 1000 / 120, T_MAX = 720, ROW = 9;
  const startGeo = (st) => {
    if (loop) { loop.stop("restart"); }
    st.selRest = null; st.itemC = null;                                                     // G4: the grey is read again on every press (theme / page colour may have changed)
    const nav = st.nav, glide = st.glide;
    if (!nav.offsetWidth) return;                                            // html.kbd: the bar is display:none, its geometry 0 — nothing to drive
    const w0 = parseFloat(glide.style.width) || glide.offsetWidth || 82, h0 = glide.offsetHeight || 54, pad = glide.offsetTop;   // the resting box = the item's (view.js's inline left / width; top = the bar's pad)
    /* D = the driver's whole state in one object (so the table can run a copy): P = the material's lift progress, Q = the size's (SP_UNLIFT above), XS = the position,
       X = its target (mirrored to st.X), rm, pTarget, posSpring, phase, arrived (R33), fl = the flex (R64), last = the time the springs were stepped to */
    const D = { P: { x: 0, v: 0 }, Q: { x: 0, v: 0 }, XS: { x: st.lastX, v: 0 }, X: st.X, rm: false, pTarget: 1, last: clockNow(), phase: "lift", frameN: 0, posSpring: SP_POS, arrived: false, fl: null, sim: false };
    let running = true; const t0 = D.last;
    /* R64: the flex interaction's integrator and three floats (view.js B5 helpers; without them the box is the lift's alone) */
    const FLEX_OK = typeof flexIntegrator === "function" && typeof flexSpec === "function" && typeof flexTargets === "function" && typeof springStep === "function";
    D.fl = FLEX_OK ? { vi: mkVI(), sx: { x: 1, v: 0 }, sy: { x: 1, v: 0 }, dx: { x: 0, v: 0 }, out: { sx: 1, sy: 1, dx: 0 }, tg: null, spec: null, sp: null, trace: [] } : null;
    const segBox = st.seg.getBoundingClientRect(), navBox = nav.getBoundingClientRect(), track = { min: segBox.left - navBox.left + (parseFloat(getComputedStyle(st.seg).paddingLeft) || 0), max: segBox.right - navBox.left - (parseFloat(getComputedStyle(st.seg).paddingRight) || 0) };
    /* R33 (tab-lens-motion.md §3a): a quick tap on another item (the up before the +140 ms lift) — the lens lifts and slides at once (ζ 1 / .25 with
       ζ .85 / .4) and starts falling (ζ 1 / .4) on the frame the slide arrives, not at the up, not earlier for an early up; the arrival = the position
       spring first within .5 pt (1 px at 2×) of the target */
    const tap = !!st.tap;
    /* what setTargets and the arrival rule read of the page: live (null → read now) or a table's snapshot */
    const snapNow = () => ({ lifted: glide.classList.contains("lift") || glide.classList.contains("lift-sel"), pressed: !!st.pressed, drag: nav.classList.contains("drag"), centre: centreOf(glide), rm: RM(), finger: { down: finger.down, x: finger.x, a: finger.a, moved: finger.moved } });
    /* the lift target: 1 while the page holds the highlight (lift / lift-sel); after the up (no highlight) it stays 1 until the lens is within DROP_WITHIN of its target, then 0 (R106 ①);
       a quick tap (R33: the lift never got its class) rides the same rule: up (1 until within 8) then the fall; Reduce Motion never lifts */
    const setTargets = (D, sn) => { const s = sn || snapNow(), F = s.finger, lifted = s.lifted || (s.pressed && F.down), dragging = lifted && F.down && F.x != null && (s.drag || F.moved), rm = s.rm;   // R59′d: lifted from the down (st.pressed), dragging once the finger has moved
      D.rm = rm;
      if (rm && F.down && F.x != null) { const left = Math.max(track.min, Math.min(track.max - w0, F.x - F.a * w0)); D.X = left + w0 / 2; D.posSpring = SP_RM; D.phase = "rm"; }   // R59′b: the slide to the pressed item from the down, the finger rule while moving, ζ .9 / .2
      else if (dragging) { const left = Math.max(track.min, Math.min(track.max - w0, F.x - F.a * w0)); D.X = left + w0 / 2; D.posSpring = SP_DRAG; D.phase = "drag"; }
      else if (s.pressed && F.down && F.x != null) { const left = Math.max(track.min, Math.min(track.max - w0, F.x - F.a * w0)); D.X = left + w0 / 2; D.posSpring = SP_POS; D.phase = Math.abs(D.X - D.XS.x) > .5 ? "move" : "lift"; }   // R59′d: began → the pressed item's frame (§6.9 ②), the "began" pair .85 / .4
      else if (tap) { D.X = s.centre; D.posSpring = rm ? SP_RM : SP_POS; D.phase = D.arrived ? "drop" : "tap"; }
      else { D.X = s.centre; D.posSpring = lifted ? SP_POS : (rm ? SP_RM : SP_RELEASE); D.phase = lifted ? (Math.abs(D.X - D.XS.x) > .5 ? "move" : "lift") : "drop"; }   // after the up: §6.9's "no gesture" pair .85 / .4 (RM .9 / .2) to view.js's selection
      const near = Math.abs(D.X - D.XS.x) < DROP_WITHIN; D.arrived = tap ? (D.arrived || near) : D.arrived;
      D.pTarget = rm ? 0 : lifted ? 1 : (near ? 0 : 1); if (!lifted && !near && !rm) D.phase = tap ? "tap" : "slide";   // R106 ①: no highlight → lifted until within 8 pt of the target
      if (!D.sim) { st.X = D.X; st.rm = rm; } };
    setTargets(D, null);
    /* one step of the driver to `now` (the springs, R106's arrival, the flex) → the frame's geometry; no DOM write (paint below), so a copy can run it ahead */
    const integ = (D, now, sn) => {
      const dt = Math.min(1, (now - D.last) / 1000), XS0 = { x: D.XS.x, v: D.XS.v }; D.last = now; D.frameN++;   // XS0: the position at the frame's start (view.js flexGrid interpolates the fed centre between it and the end)
      spring(D.P, D.pTarget, D.pTarget > .5 ? SP_LIFT : SP_DROP, dt); spring(D.Q, D.pTarget, D.pTarget > .5 ? SP_LIFT : SP_UNLIFT, dt); spring(D.XS, D.X, D.posSpring, dt);
      if (D.pTarget > .5 && !D.rm && !(sn ? sn.lifted : (glide.classList.contains("lift") || glide.classList.contains("lift-sel"))) && Math.abs(D.XS.x - D.X) < DROP_WITHIN) { if (tap && !D.arrived && !D.sim) st.tapArrivedAt = now; D.arrived = true; setTargets(D, sn); }   // R106 ①: the fall begins on the frame the lens comes within 8 pt of its target (no highlight)
      const p = Math.max(0, Math.min(1, D.P.x)), q = Math.max(0, Math.min(1, D.Q.x)), x = D.XS.x, W = w0 + LIFT_W * q, H = h0 + LIFT_H * q;
      /* R64 — the flex, once per frame: the presented centre (position + the drift in the scaled coordinates) into the integrator, the variant from the
         model bounds (lifted (w0 + 16) × (h0 + 16) while the lift target is up, the resting box otherwise — §7.4), updateFlex's targets, the three floats
         on the tracking spring while the finger is down, else the scaleSpring */
      let Wp = W, Hp = H, xc = x, flexOn = false; const fl = D.fl, fdown = sn ? sn.finger.down : finger.down;
      /* when: the fall animation group's completion block sets activation mode 1 (flex-interaction.md §8 ③, 0x1c54c9a28, §5b R73) — the integrator is cleared and
         the targets go back to identity, scaleX is set to 1 on that frame, the other floats settle on their spring from where they are (tab-lens-motion.md
         「数据核 G10」⑤: C3 +1.308, scaleY back to 1 by +1.608); the frame is FLEX_OFF_S after the fall starts (above). The START = the lift (§8 ③ reads mode 3 from the lift, 0x1c54c8258): 界面 09-24 re-read on
         simulator B (BOARD/evidence/界面-0924/tap/b-motion.json, r33b.sh; the probe's lensPres checked against the held screenshot b-hold1.png to 1 pt:
         rim 116.5 × 74.7 vs 115.5 × 74.0) — a quick tap on another item stretches while it travels (lensPresTransform 1.083 / .861, peak 118.8 × 60.0 and
         119.4 × 60.1, = §3a's 120.8 × 60.6), the press-glide too (peak 126.1 × 63.2, = §3 ①'s 126.2 × 63.1); R108's 116.7 × 74.0 is a press on the
         selected item, where the lens does not travel and the integrator reads no motion */
      if (fl && (D.phase === "drag" || D.phase === "tap" || D.phase === "move") && !fl.active) { fl.active = true; fl.vi = mkVI(); }
      if (fl && fl.active) { if (D.pTarget !== 0) { fl.fallAt = null; fl.kicked = false; } else if (fl.fallAt == null) fl.fallAt = now; }
      const sinceFall = fl && fl.fallAt != null ? (now - fl.fallAt) / 1000 : -1;
      const FG = typeof flexGrid === "function" && FLEX_GRID_HZ > 0;   // view.js flexGrid: the flex on its own fixed grid (below); the deactivate and the kick then fall on grid samples too
      if (fl && fl.active && sinceFall >= FLEX_OFF_S && !FG) { fl.active = false; fl.vi = mkVI(); fl.sx = { x: 1, v: 0 }; fl.fallAt = null; fl.kicked = false; }   // G10 ⑤: the completion block's deactivate
      const flexMoving = fl && (Math.abs(fl.out.sx - 1) >= .002 || Math.abs(fl.out.sy - 1) >= .002 || Math.abs(fl.out.dx) >= .1 || Math.abs(fl.sx.v) >= .01 || Math.abs(fl.sy.v) >= .01 || Math.abs(fl.dx.v) >= .5);
      if (fl && !fl.active && !flexMoving && (fl.out.sx !== 1 || fl.out.sy !== 1 || fl.out.dx !== 0)) { fl.sx = { x: 1, v: 0 }; fl.sy = { x: 1, v: 0 }; fl.dx = { x: 0, v: 0 }; fl.out = { sx: 1, sy: 1, dx: 0 }; }
      if (fl && (fl.active || flexMoving)) { flexOn = true;
        const Wm = D.pTarget > .5 ? w0 + LIFT_W : w0, Hm = D.pTarget > .5 ? h0 + LIFT_H : h0;
        const spec = flexSpec(Wm, Hm), sp = fdown ? [spec.tzeta, spec.tresp] : [spec.zeta, spec.resp];
        let kick = false, fed = null;
        if (FG) {   // view.js flexGrid (动效 10-01, 验收 decision b): fed at fixed grid times from the run's start, not once per frame — the same flex at any frame rate
          if (fl.anchor == null) fl.anchor = t0;
          let cur = null;   // this grid sample's feed, for its trace entry (one entry per grid sample: the acceptance's per-step rows read the grid)
          flexGrid(fl, now - dt * 1000, now, { x0: XS0.x, v0: XS0.v, x1: D.XS.x, v1: D.XS.v }, (tn, xn, out) => {
            const since = fl.fallAt != null ? (tn - fl.fallAt) / 1000 : -1; cur = { kick: false, fed: null, x: xn, since };
            if (!fl.active) return null;
            if (since >= FLEX_OFF_S) { fl.active = false; fl.vi = mkVI(); fl.sx = { x: 1, v: 0 }; fl.fallAt = null; fl.kicked = false; return null; }   // G10 ⑤: the completion block's deactivate, on the first grid sample FLEX_OFF_S after the fall
            const k = !fl.kicked && since >= FLEX_KICK_S; if (k) { fl.kicked = true; kick = true; }   // G10 ①: one sample of the point without the platter's x — the first grid sample FLEX_KICK_S after the fall
            cur.kick = k; cur.fed = xn + out.sx * out.dx - (k ? navBox.left : 0); fl.vi.add(cur.fed, tn / 1000); return flexTargets(spec, Wm, Hm, fl.vi.acceleration, fl.vi.velocity); }, sp,
            (tn, tg) => { if (fl.trace && fl.trace.length < 600) fl.trace.push({ t: tn, dt: 1 / FLEX_GRID_HZ, kick: cur.kick, fed: cur.fed, since: cur.since, px: navBox.left, active: fl.active, sx: fl.sx.x, sy: fl.sy.x, dx: fl.dx.x, vsx: fl.sx.v, vsy: fl.sy.v, vdx: fl.dx.v, tSx: tg.sX, tSy: tg.sY, tDx: tg.drift, sp, accel: fl.vi.acceleration, vel: fl.vi.velocity, Wm, Hm, x: cur.x, W, H, grid: true }); });
          fl.spec = spec; fl.sp = sp; if (!fl.tg) fl.tg = { sX: 1, sY: 1, drift: 0 };
        } else {   // ?flexgrid=0: once per frame (the former path)
          kick = fl.active && !fl.kicked && sinceFall >= FLEX_KICK_S; if (kick) fl.kicked = true;   // G10 ①: one frame of the point without the platter's x
          fed = x + fl.out.sx * fl.out.dx - (kick ? navBox.left : 0); if (fl.active) fl.vi.add(fed, now / 1000);
          const tg = fl.active ? flexTargets(spec, Wm, Hm, fl.vi.acceleration, fl.vi.velocity) : { sX: 1, sY: 1, drift: 0 };
          springStep(fl.sx, tg.sX, sp, dt); springStep(fl.sy, tg.sY, sp, dt); springStep(fl.dx, tg.drift, sp, dt);
          fl.out = { sx: fl.sx.x, sy: fl.sy.x, dx: fl.dx.x }; fl.tg = tg; fl.spec = spec; fl.sp = sp; }
        Wp = W * fl.out.sx; Hp = H * fl.out.sy; xc = x + fl.out.sx * fl.out.dx;   // §6.6 / §6.4: W·sX × H·sY, tx = sX·dx
        if (!FG && fl.trace && fl.trace.length < 600) fl.trace.push({ t: now, dt, kick, fed, since: sinceFall, px: navBox.left, active: fl.active, sx: fl.out.sx, sy: fl.out.sy, dx: fl.out.dx, vsx: fl.sx.v, vsy: fl.sy.v, vdx: fl.dx.v, tSx: fl.tg.sX, tSy: fl.tg.sY, tDx: fl.tg.drift, sp, accel: fl.vi.acceleration, vel: fl.vi.velocity, Wm, Hm, x, W, H });
      }
      const flexRest = !fl || (!fl.active && fl.out.sx === 1 && fl.out.sy === 1 && fl.out.dx === 0);
      const done = D.pTarget === 0 && p < .002 && Math.abs(D.P.v) < .02 && q < .002 && Math.abs(D.Q.v) < .02 && Math.abs(D.XS.x - D.X) < .05 && Math.abs(D.XS.v) < 1 && flexRest && !(D.rm && fdown);   // R59′b: parked on the item while the finger is down (view.js's box is still the old item until the up)
      return { p, q, x, W, H, Wp, Hp, xc, flexOn, done };
    };
    /* the frame's DOM side: the glide's box: the centre x from the position spring (+ the flex drift), the vertical centre = the resting centre (pad + h0 / 2);
       gl: the canvas too (glFrame — the worker gets the state, or the main-thread GL draws it); not while the worker plays a table */
    let runId = ++glRun;
    const paint = (o, gl) => {
      nav.style.setProperty("--tl-left", (o.xc - o.Wp / 2) + "px"); nav.style.setProperty("--tl-w", o.Wp + "px"); nav.style.setProperty("--tl-top", (pad + h0 / 2 - o.Hp / 2) + "px"); nav.style.setProperty("--tl-h", o.Hp + "px");
      if (!nav.classList.contains("tl-on")) nav.classList.add("tl-on");
      if (gl) glFrame(st, o.p, o.xc, o.Wp, o.Hp, pad, h0, runId, D.last);
      /* the worker path: the canvas capsule (opaque while p > 0, the grey drawn in it as the platter uniform — G4 below) covers the glide on the main-thread path, drawn
         in the same frame; the worker's frame lands on its own (≤ 1 frame apart, and on its own clock after the lift), so the DOM glide is hidden once the worker has
         drawn this run's first lifted frame (its "drew" answer), until the stop — no sliver of a glide a frame behind / ahead of the lens */
      const fl = D.fl, flexRest = !fl || (!fl.active && fl.out.sx === 1 && fl.out.sy === 1 && fl.out.dx === 0);
      const still = Math.abs(D.P.x - D.pTarget) < .002 && Math.abs(D.P.v) < .02 && Math.abs(D.XS.x - D.X) < .05 && Math.abs(D.XS.v) < 1 && (!fl || (Math.abs(fl.out.sx - 1) < 1e-3 && Math.abs(fl.out.sy - 1) < 1e-3 && Math.abs(fl.out.dx) < .05));   // the flex decays towards 1 / 0 without reaching it (read .99997 / 1.00005 / .0008 on a held lift, .9995 / 1.0008 / −.025 parked in a drag)
      /* 外观 10-01 17:1x: a held lift at rest (both springs at their targets — the thresholds of `settled` below — and the flex within 1e-3 of rest) shows the DOM glide again:
         the lens and the glide then sit still in the same place, so no sliver; and the main-thread path showed the glide under the lens rim's anti-aliased pixels
         (held press vs old: 2 cells ΔE ≤ 3.3 with it hidden, SAME with it shown — 动效 evidence/动效-1001-镜片Worker/README.md:57). Any motion hides it again. */
      if (o.p > 0 && glo && glo.nav === nav && glo.lens.wk && glo.lens.drewRun === runId) { if (still) { if (nav.classList.contains("tl-wk")) nav.classList.remove("tl-wk"); } else if (!nav.classList.contains("tl-wk")) nav.classList.add("tl-wk"); }
      window.__tabLens = { t: (D.last - t0) / 1000, t0, tf: D.last, p: o.p, v: D.P.v, q: o.q, x: o.x, xv: D.XS.v, target: D.X, set: 0, s: 1, phase: D.phase, w: o.W, h: o.H, wp: o.Wp, hp: o.Hp, xc: o.xc, frame: D.frameN, mode: "geometry", rm: !!D.rm,
        settled: Math.abs(D.P.x - D.pTarget) < .002 && Math.abs(D.P.v) < .02 && Math.abs(D.XS.x - D.X) < .05 && Math.abs(D.XS.v) < 1,   // read-only (S1, 2号 13:1x): both springs at their current targets — the stop rule's thresholds below, whatever the target is (a held lift, a parked drag); the flex is not in it (its floats are exposed above)
        flex: fl ? { sx: fl.out.sx, sy: fl.out.sy, dx: fl.out.dx, target: fl.tg, spec: fl.spec, sp: fl.sp, accel: fl.vi.acceleration, vel: fl.vi.velocity, trace: fl.trace } : null, table: T ? T.n : 0, rest: flexRest };   // tf = the time the springs were stepped to: a retarget after it (the up) integrates from here; table = the nodes of the table being replayed (0: integrating per frame)
    };
    let T = null, lastOut = null, repaint = false;
    const cloneD = (D) => { const C = { ...D, P: { ...D.P }, Q: { ...D.Q }, XS: { ...D.XS }, sim: true };
      if (D.fl) { const f = D.fl; C.fl = { ...f, vi: f.vi.clone(), sx: { ...f.sx }, sy: { ...f.sy }, dx: { ...f.dx }, out: { ...f.out }, trace: null }; } return C; };
    const buildTable = (now) => {
      const tb = performance.now(), sn = snapNow(), S = cloneD(D), nb = nav.getBoundingClientRect(), cw = document.documentElement.clientWidth, ih = innerHeight;
      const rows = new Float64Array(T_MAX * ROW); let n = 0;
      const put = (S, o) => { const fl = S.fl, on = o.flexOn, sx = on ? fl.out.sx : 1, sy = on ? fl.out.sy : 1, ddx = on ? fl.out.dx : 0, vsx = on ? fl.sx.v : 0, vsy = on ? fl.sy.v : 0, vdx = on ? fl.dx.v : 0;
        const dq = S.Q.x > 0 && S.Q.x < 1 ? S.Q.v : 0, dp = S.P.x > 0 && S.P.x < 1 ? S.P.v : 0;   // the clamp of p / q to [0, 1]: no slope outside it
        const l = nb.left + o.xc - o.Wp / 2, t = nb.top + pad + h0 / 2 - o.Hp / 2, wh = (Math.min(l + o.Wp + 100, cw) - Math.max(l - 100, 0)) / (Math.min(t + o.Hp + 100, ih) - Math.max(t - 100, 0));   // glFrame's capture box
        const a = n * ROW; rows[a] = o.xc + GLM; rows[a + 1] = o.Wp; rows[a + 2] = o.Hp; rows[a + 3] = o.p; rows[a + 4] = wh;
        rows[a + 5] = (S.XS.v + vsx * ddx + sx * vdx) / 1000; rows[a + 6] = (LIFT_W * dq * sx + o.W * vsx) / 1000; rows[a + 7] = (LIFT_H * dq * sy + o.H * vsy) / 1000; rows[a + 8] = dp / 1000; n++; };   // d/dt per ms: xc = x + sX·dx, W·sX, H·sY, p
      put(S, lastOut); let done = lastOut.done;
      while (!done && n < T_MAX) { const o = integ(S, now + n * TDT, sn); put(S, o); done = o.done; }
      T = { t0: now, n, next: 1, sn };
      const c = { cy: pad + h0 / 2 + GLM, rgba: st.selRest || (st.selRest = selRest(nav)), item: ITEM, icy: (st.itemC || (st.itemC = itemCentres(nav))).cy, icx: st.itemC.cx };
      const keep = rows.slice(0, n * ROW);
      window.__tabLensTable = { t0: now, epoch: performance.timeOrigin + now, dt: TDT, n, rows: keep, c, done, ms: performance.now() - tb };   // instrument (the curve checks; ms = this frame's sampling cost)
      if (!LWSIM && glo && glo.nav === nav && glo.lens.wk) { const r = keep.slice(); glo.lens.table({ t0: performance.timeOrigin + now, dt: TDT, n, rows: r, c, r: runId }, [r.buffer]); }
      try { performance.measure("tab:lw-table", { start: tb, end: performance.now() }); } catch (e) {} };
    const catchUp = (until) => { while (T.next < T.n && T.t0 + T.next * TDT <= until) { const o = integ(D, T.t0 + T.next * TDT, T.sn); T.next++; lastOut = o; if (o.done) break; } };
    const frame = (now) => { try { frame0(now); } catch (e) { window.__tabLensErr = String(e && e.stack || e); console.error("tab-lens frame", e); stop(); } };
    const frame0 = (now) => {
      if (!running) return;
      if (T) {   // replaying the table: the nodes up to this frame (the frame's own timestamp sits on a node give or take the clock's rounding: + 1 ms)
        const n0 = T.next; catchUp(now + 1);
        if (T.next !== n0) { paint(lastOut, LWSIM); if (lastOut.done) { if (!LWSIM) void nav.getBoundingClientRect(); stop(); return; } }   // the stop frame as on the main-thread path: there glFrame reads the bar's box after the frame's --tl-* and before the stop (a style + layout flush); without it Chrome 154 ran the glide's CSS left transition (index.html, .55 s) from the last --tl-left to view.js's left after every tap (a 0.009 px slide; view.js's .tcs / .tcg restyled for .55 s, the recorder's line 470 ms longer) — headless, tools/trtap.py
        if (T.next >= T.n) { T = null; if (!LWSIM && glo && glo.lens.wk) glo.lens.cancel(); }   // T_MAX reached without the stop rule: integrate per frame from here
        tick(frame); return; }
      if (now <= D.last) { if (repaint && lastOut) { repaint = false; paint(lastOut, true); } tick(frame); return; }   // a frame stamped before the start (Chrome: rAF's `now` = the frame's start, which can precede the call that started the loop) — or before the node a retarget caught up to: nothing to integrate yet
      repaint = false; const o = integ(D, now, null); lastOut = o; paint(o, true);
      if (o.done) { stop(); return; }
      if ((LWSIM || (glo && glo.nav === nav && glo.lens.wk && !glo.lens.lost)) && !finger.down && !D.rm && !(glide.classList.contains("lift") || glide.classList.contains("lift-sel"))) buildTable(now);   // the lift: no input from here on (Reduce Motion keeps the per-frame path)
      tick(frame);
    };
    const retarget = () => { if (T) { catchUp(performance.now()); if (window.__tabLensTable) window.__tabLensTable.cancel = { at: performance.now(), node: T.next }; T = null; repaint = true; if (!LWSIM && glo && glo.lens.wk) glo.lens.cancel(); } setTargets(D, null); };   // the worker stops at the row it drew; the driver goes on from the node of this moment
    const stop = (why) => { running = false; T = null; glRest(st); st.tap = false; window.__tabLensStop = { why: why || "settled", at: performance.now(), phase: D.phase, x: D.XS.x, target: D.X };   // instrument: why the driver stopped (the acceptance reads it)
      nav.classList.remove("tl-on", "tl-wk"); for (const k of ["--tl-left", "--tl-w", "--tl-top", "--tl-h"]) nav.style.removeProperty(k);   // rest: the glide shows view.js's own box again (its inline left / width = the selected item)
      if (loop && loop.stop === stop) loop = null; window.__tabLens = null; };
    loop = { stop, retarget, st };
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
        if (f) { const l0 = SL + AM, t0s = ST + AM, wh = (Math.min(l0 + W + 100, document.documentElement.clientWidth) - Math.max(l0 - 100, 0)) / (Math.min(t0s + H + 100, innerHeight) - Math.max(t0s - 100, 0));
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
    /* a rebuild = the bar's own layers (.plat / .glide / .seg) added or removed; view.js's item-set animation moves the leaving buttons into nav while they fade
       (view.js layoutTabs `nav.appendChild(b)`) and removes them when it settles (tabSetAnimate `b.remove()`), and glAttach swaps its canvas / .lens-clip —
       none of those is a rebuild (each re-attached, redrew the backdrop and stopped a running lift) */
    const layer = (n) => n.nodeType === 1 && n.matches(".plat, .glide, .seg");
    for (const m of muts) { if (m.type === "childList" && m.target === nav) { if ([...m.addedNodes].some(layer) || [...m.removedNodes].some(layer)) rebuilt = true; } else if (m.type === "attributes" && m.target !== nav && m.target.classList && m.target.classList.contains("glide") && !(m.attributeName === "style" && loop && m.target.style.transformOrigin && m.oldValue === null)) glideChanged = true; }
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
  const onTabsChanged = (e) => { const nav = document.getElementById("tabs"); if (!nav || !ready) return; if (loop) loop.stop("tabs-changed"); st = attach(nav, !(e && e.detail && e.detail.animated)); if (st) { st.X = centreOf(st.glide); st.lastX = st.X; } };   // detail.animated (view.js layoutTabs): the backdrop waits for "tabs-settled" below
  const init = async () => {
    if (MODE === "geometry") { injectGeoStyle(); ready = true; } else await loadFilters();
    const nav = document.getElementById("tabs"); if (!nav) return;
    nav.addEventListener("tabs-changed", onTabsChanged);
    /* 用户 09-23 18:27 真机 ②「切换到晚班再切早班的时候会出现晚班的底图重叠」: tabs-changed fires on the first frame of view.js's item-set animation, so
       the backdrop above was painted from a platter still 290 → 416 wide and buttons still at their old x (模拟器 B, evidence 界面-串2-②-底图画布.json: the
       live 1392×330 page canvas had its capsule at css 45..370 of a 416 bar, the item canvas its first icon 45 px right) — the lens then showed that 晚班
       layout under the new one on every lift. Painted again from the settled bar when the animation ends (view.js tabSetAnimate "tabs-settled"). */
    nav.addEventListener("tabs-settled", () => { if (MODE === "geometry" && GL_ON && st && st.nav === nav) glAttach(st).then((g) => { if (g && g.nav === nav) { try { g.lens.redrawBackdrop(); } catch (e) {} } }); });
    st = attach(nav);
    mo.observe(nav, { subtree: true, childList: true, attributes: true, attributeFilter: ["class", "style"] });   // nav itself is static; view.js rewrites its children on every render
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", init); else init();
})();
