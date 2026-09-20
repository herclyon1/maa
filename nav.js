/* nav.js — UINavigationController push / pop for the page's pushed page (#subpage), BOARD.md #2. Every number is a read original
   (remote-ref/nav-native-formula.md §0–§1, the old page session's decompile of iOS 27.0 UIKitCore _UINavigationParallaxTransition +
   _UIFluidParallaxTransitionSettings); the unread parts are left empty and named (nav.css, §5).
   p(t): ONE spring ζ 1 / response .3 (ω₀ 20.944) from rest, 0 → 1 (noninteractiveSpring, _UIFluidParallaxTransitionSettings.setDefaultValues
     0x1c5410f44; the .35 s "transitionDuration" is only the shell), stepped per frame by Motion.spring.
   push: new page x = W(1 − p); old page x = −(W − round(.7 W))·p = −.3 W·p (parallaxOffset [0x1c57184d0] = .7, gap 0);
         dimming (black .1) alpha = p; the top card's left edge strip alpha = 1 − p; nav bar items of the new page alpha = f_in(u₂),
         u₂ = the second key segment [.5 − .075, 1], f_in = cubic-bezier(.75,.1,.75,.1); the title slides from the title area's right end.
   pop: the same spring, roles swapped (top page x = W·p, page below −.3 W(1 − p), dimming 1 − p, strip 1 − p, items fade out with
        f_out = cubic-bezier(.25,.9,.25,.9) over [0, .575]).
   Interrupt (pop while pushing): the spring continues from its current value / velocity toward the new target (retargetImpulse .02 of
   the settings is NOT applied: how AnimationKit adds it to the velocity is unread — 待读). Interactive back = #12 (nav-edge.js).
   R47′ (nav-native-formula.md §5g, _animateScaleTransition 0x1c3cf7b74 / _animateLargeTitleView 0x1c3cf85b8, the scale style of a large-title
   push): the root's large title (body > header h1) is not faded away as content — its label scales about its own centre to the new back button's
   content bounds (the chevron: no back label → the imageView is the reference, __applyStretchTransformForTitleViewAndBackButtonLayout mode 2:
   MakeScale(w_ref / w_large, h_ref / h_large), 0x1c3d00b40–0x1c3d00b84) while its centre moves −d·p toward the reference (d = §5d's
   _titleTransitionDistance, the same d as the chevron's R21e′ start offset; 0x1c3cf866c / 0x1c3cf8858) and, the texts differing (h1 string vs
   nil), its alpha runs the keyframe [0, .6] → 0 (0x1c3cf7db4–0x1c3cf7e10). The new back button: body alpha 1, its content alpha keyframe
   [.5, 1] 0 → 1 (prepare 0x1c3cf629c–0x1c3cf62e4; 0x1c3cf7de8–0x1c3cf7e20); the chevron image starts at scale .7 ([0x1c57184d0]) and
   (+7, +5) pt from its final frame with alpha 0 and pops out in the keyframe [.9, 1] (0x1c3cf61b8–0x1c3cf6288, 0x1c3cf7ed8–0x1c3cf7f5c).
   The pop (§5g′, _UINavigationBarTransitionContextPop _animateScaleTransition 0x1c3cfa864, R69′): scale / centre / the back content's offset are
   the push reversed (mode 5, 0x1c3cfa918–0x1c3cfa928; back content 0 → (d.x − adj, d.y) 0x1c3cfa89c–0x1c3cfa8c4), but the alpha keyframes are
   the pop's own, in its progress u = 1 − p: the old back button's content → 0 over [0, .6] (kf1 block_2 0x1c3cfabc0 / 0x1c3cfac14), the root
   large title held at 0 over [0, .5] (kf2 block_3 0x1c3cfac34) then → 1 over [.5, 1] (kf3 block_4 0x1c3cfac44); the chevron shrinks out over
   [0, .1] to scale .7 / (+7, +5) / alpha 0 (block_6 0x1c3cface4) — the push's [.9, 1] pop-out read backwards in p. The back button's body fades
   with the bar's items (§0 f_out) as before.
   On this page the large title is page content that parallaxes with the root (−.3 W·p); natively it is the bar's and does not, so the h1's own
   translate compensates the parallax and its centre moves exactly −d·p on screen. Segment interpolation inside a keyframe is drawn linear
   (§5g 未读 ①: the keyframe state's use of curve bit 5 is unread — 待读).
   Hook: view.js openPage's first line `if (window.Nav) return Nav.open(title, html);` (A7). */
(() => {
  "use strict";
  const SPRING = [1, .3];                       // noninteractiveSpring ζ 1 / response .3
  const SEG = { mid: .5, overlap: .15 };        // key segments: [0, .5 + .075] and [.5 − .075, 1] (overlap .15 × .5)
  const bez = (x1, y1, x2, y2) => (x) => {      // y of the cubic bezier at abscissa x (CAMediaTimingFunction semantics)
    let lo = 0, hi = 1; for (let i = 0; i < 24; i++) { const t = (lo + hi) / 2, cx = 3 * x1 * t * (1 - t) * (1 - t) + 3 * x2 * t * t * (1 - t) + t * t * t; if (cx < x) lo = t; else hi = t; }
    const t = (lo + hi) / 2; return 3 * y1 * t * (1 - t) * (1 - t) + 3 * y2 * t * t * (1 - t) + t * t * t;
  };
  const fIn = bez(.75, .1, .75, .1), fOut = bez(.25, .9, .25, .9);
  const u1 = (p) => Math.max(0, Math.min(1, p / (SEG.mid + SEG.overlap / 2)));                                     // first segment [0, .575]
  const u2 = (p) => Math.max(0, Math.min(1, (p - (SEG.mid - SEG.overlap / 2)) / (1 - (SEG.mid - SEG.overlap / 2)))); // second [.425, 1]
  const st = { p: 0, v: 0, target: 0, raf: 0, last: 0, dir: 0, pg: null, dim: null, titleStart: 0, backDx: 0, backDy: 0, h1: null, trace: [] };
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const KF = { h1Out: [0, .6], backIn: [.5, 1], chev: [.9, 1], popBackOut: [0, .6], popH1In: [.5, 1] };   // §5g push keyframes (start, end) in p: large title alpha → 0; back content alpha → 1; chevron pop-out. §5g′ pop keyframes in u = 1 − p: old back content → 0; large title → 1 (held 0 before .5); the chevron's [0, .1] shrink-out = chev read backwards
  const CHEV0 = { scale: .7, dx: 7, dy: 5 };                     // the chevron's prepared start: MakeScale(.7) [0x1c57184d0], final frame + (+7, +5) pt (flags bit 1 → −7: RTL, not this page)
  const seg = ([a, b], p) => clamp01((p - a) / (b - a));
  const W = () => window.innerWidth;
  const parallax = () => -(W() - Math.round(.7 * W()));   // −132 at 440
  const write = () => {
    const pg = st.pg, p = st.tracking ? st.p : Math.max(0, Math.min(1, st.p)), root = document.body;   // the interactive drive may rubber-band past [0, 1] (fluid percent)
    pg.style.setProperty("--nav-x", (W() * (1 - p)).toFixed(2) + "px");
    root.style.setProperty("--nav-from", (parallax() * p).toFixed(2) + "px");
    st.dim.style.setProperty("--nav-dim", p.toFixed(4));
    pg.style.setProperty("--nav-edge", (st.dir > 0 ? 1 - p : p).toFixed(4));   // strip alpha = 1 − (the running transition's own progress): push p, pop 1 − p
    const a = st.dir > 0 ? fIn(u2(p)) : 1 - fOut(u1(1 - p));   // pop runs p 1 → 0 in the same variable: the old page's items fade out with f_out
    pg.style.setProperty("--nav-in", a.toFixed(4));
    pg.style.setProperty("--nav-title", (st.titleStart * (1 - p)).toFixed(2) + "px");
    pg.style.setProperty("--nav-back-dx", (st.backDx * (1 - p)).toFixed(2) + "px");   // the back chevron starts at the root's large-title label centre (§5d: d = label.center − content origin, 2-D) and rides p home; pop runs it back
    pg.style.setProperty("--nav-back-dy", (st.backDy * (1 - p)).toFixed(2) + "px");
    /* R47′ — the large title (mode 2, §5g): scale 1 → (w_chev / w_h1, h_chev / h_h1) about the text's centre, centre −d·p on screen (the header's
       parallax compensated), alpha keyframe [0, .6] → 0; the same functions of p on the pop (mirror, 待读 ②) */
    const u = 1 - p, h = st.h1, kOut = st.dir > 0 ? 1 - seg(KF.h1Out, p) : seg(KF.popH1In, u);   // the large title's alpha: push [0, .6] → 0 in p; pop held 0 then [.5, 1] → 1 in u (R69′)
    if (h) {
      const sx = 1 + (h.sx - 1) * p, sy = 1 + (h.sy - 1) * p, dx = -st.backDx * p - parallax() * p, dy = -st.backDy * p;
      root.style.setProperty("--nav-h1-ox", h.ox.toFixed(2) + "px"); root.style.setProperty("--nav-h1-oy", h.oy.toFixed(2) + "px");
      root.style.setProperty("--nav-h1-sx", sx.toFixed(5)); root.style.setProperty("--nav-h1-sy", sy.toFixed(5));
      root.style.setProperty("--nav-h1-dx", dx.toFixed(2) + "px"); root.style.setProperty("--nav-h1-dy", dy.toFixed(2) + "px");
      root.style.setProperty("--nav-h1-a", kOut.toFixed(4));
    }
    /* the back button on a push: body alpha 1 (prepare), content alpha keyframe [.5, 1], the chevron image alpha / scale / offset keyframe [.9, 1] from
       .7× and (+7, +5); on a pop the body fades with the bar's items (§0 f_out) and the content shows (pop keyframes unread) */
    const kIn = st.dir > 0 ? seg(KF.backIn, p) : 1 - seg(KF.popBackOut, u), kc = seg(KF.chev, p);   // back content alpha: push [.5, 1] → 1 in p, pop [0, .6] → 0 in u; the chevron keyframe in p both ways (pop = the first 10 % shrink-out)
    pg.style.setProperty("--nav-back-a", st.dir > 0 ? "1" : a.toFixed(4));
    pg.style.setProperty("--nav-chev-a", (kIn * kc).toFixed(4));
    pg.style.setProperty("--nav-chev-s", (CHEV0.scale + (1 - CHEV0.scale) * kc).toFixed(4));
    pg.style.setProperty("--nav-chev-kx", (CHEV0.dx * (1 - kc)).toFixed(2) + "px"); pg.style.setProperty("--nav-chev-ky", (CHEV0.dy * (1 - kc)).toFixed(2) + "px");
    if (st.trace.length < 400) st.trace.push({ p, el: st.elapsed || 0, dir: st.dir, h1: h ? { sx: 1 + (h.sx - 1) * p, sy: 1 + (h.sy - 1) * p, dx: -st.backDx * p - parallax() * p, dy: -st.backDy * p, a: kOut } : null, back: { a: st.dir > 0 ? 1 : a, ca: kIn * kc, cs: CHEV0.scale + (1 - CHEV0.scale) * kc, kx: CHEV0.dx * (1 - kc), ky: CHEV0.dy * (1 - kc) } });
  };
  const settled = () => Math.abs(st.p - st.target) < .001 && Math.abs(st.v) < .01;
  const tick = (now) => {
    if (!st.first) st.first = now;
    const dt = Math.min(1, Math.max(0, (now - st.last) / 1000)); st.last = now; st.elapsed += dt;   // elapsed: the spring's own time (the accept compares the shown values at it)   // the step is closed-form: a slow frame gets its whole elapsed time (a .05 clamp halved the motion on 100 ms frames)
    Motion.spring(st, st.target, st.spring || SPRING, dt);   // st.x is st.p: the state object is {p, v} under the names Motion expects
    if (st.tracking) { write(); st.raf = requestAnimationFrame(tick); return; }   // an interactive drive never settles by itself: the finger owns the target
    if (settled()) { st.p = st.target; st.v = 0; write(); st.raf = 0; finish(); return; }
    write(); st.raf = requestAnimationFrame(tick);
  };
  // Motion.spring reads/writes s.x / s.v: alias p as x
  Object.defineProperty(st, "x", { get() { return this.p; }, set(v) { this.p = v; } });
  const run = () => { if (st.raf) return; st.last = st.t0 = performance.now(); st.first = 0; st.elapsed = 0; st.raf = requestAnimationFrame(tick); };   // t0 = the spring's own clock (the page's first frame after a show may come late: reported by the accept, not judged)
  const finish = () => {
    const pg = st.pg;
    pg.classList.remove("nav-live"); document.body.classList.remove("nav-live");
    pg.style.transition = "none"; Motion.afterPaint(() => pg.style.removeProperty("transition"));   // index.html's .35 s transition must not replay the last step
    for (const k of ["--nav-x", "--nav-edge", "--nav-in", "--nav-title", "--nav-back-dx", "--nav-back-dy", "--nav-back-a", "--nav-chev-a", "--nav-chev-s", "--nav-chev-kx", "--nav-chev-ky"]) pg.style.removeProperty(k);
    for (const k of ["--nav-from", "--nav-h1-ox", "--nav-h1-oy", "--nav-h1-sx", "--nav-h1-sy", "--nav-h1-dx", "--nav-h1-dy", "--nav-h1-a"]) document.body.style.removeProperty(k);
    st.dim.style.setProperty("--nav-dim", "0");
    if (st.target === 1) { pg.classList.add("in"); document.body.classList.add("pushed"); }               // rest = index.html's own classes
    else { pg.classList.remove("in", "out"); document.body.classList.remove("pushed"); pg.hidden = true; }
  };
  const start = (dir) => {
    const pg = st.pg;
    if (!st.dim) { st.dim = document.createElement("div"); st.dim.className = "nav-dim"; document.body.appendChild(st.dim); }
    st.dir = dir; st.target = dir > 0 ? 1 : 0; st.tracking = false; st.spring = SPRING;
    if (!pg.classList.contains("nav-live")) {            // from rest: p = 0 (hidden) or 1 (shown), no velocity
      st.p = dir > 0 ? 0 : 1; st.v = 0;
      pg.classList.remove("in", "out"); pg.hidden = false; document.body.classList.remove("pushed");
      const title = pg.querySelector(".ptitle"), bar = pg.querySelector(".pnav");
      if (title && bar) { const tr = title.getBoundingClientRect(), br = bar.getBoundingClientRect(), side = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ios-nav-side")) || 20;
        st.titleStart = (br.right - side) - tr.left; }    // the title area's right end (the bar minus the side inset — this page's own geometry) → its place
      /* R21e′ (nav-native-formula.md §5d, _prepareScaleTransition 0x1c3cf606c): the new back button's content starts offset by d = the root's
         large-title label centre − the content's origin (the chevron has no text label → the content frame's top-left, 0x1c3d0083c), both axes;
         adj = 0 (no back label). Measured in page-local coordinates: the page rests at x 0, so the chevron's resting origin = its offset inside the page. */
      const back = pg.querySelector(".pback"), h1 = document.querySelector("body > header h1"), header = document.querySelector("body > header");
      st.backDx = st.backDy = 0; st.h1 = null; st.trace = [];
      if (back && h1 && h1.firstChild) { const rg = document.createRange(); rg.selectNodeContents(h1); const hr = rg.getBoundingClientRect(), pr = pg.getBoundingClientRect(), bb = back.getBoundingClientRect(), cs = getComputedStyle(back, "::before");
        const shift = header ? (parseFloat(getComputedStyle(header).translate) || 0) : 0;   // a pop from rest measures the header at its parallaxed −.3 W (body.pushed): d is the RESTING label centre − the chevron origin
        const cw = parseFloat(cs.width) || 0, ch = parseFloat(cs.height) || 0, ox = (bb.left - pr.left) + (bb.width - cw) / 2, oy = (bb.top - pr.top) + (bb.height - ch) / 2;   // the chevron's resting origin inside the page
        if (hr.width > 0) { st.backDx = (hr.left - shift + hr.width / 2) - ox; st.backDy = (hr.top + hr.height / 2) - oy;
          /* R47′: the large title's scale reference (mode 2) = the chevron's bounds over the text's bounds; the scale is about the TEXT's centre, set
             as the h1 box's transform-origin (the h1 is a left-aligned block wider than its text) */
          const hb = h1.getBoundingClientRect();
          if (cw > 0 && ch > 0 && hr.height > 0) st.h1 = { sx: cw / hr.width, sy: ch / hr.height, ox: (hr.left - hb.left) + hr.width / 2, oy: (hr.top - hb.top) + hr.height / 2, w: hr.width, h: hr.height, cw, ch }; } }
      pg.classList.add("nav-live"); document.body.classList.add("nav-live"); write();
    }
    run();
  };
  const open = (title, html) => {
    const pg = document.querySelector("#subpage"); if (!pg) return;
    st.pg = pg;
    pg.querySelector(".ptitle").textContent = title; pg.querySelector(".pbody").innerHTML = html;
    pg.scrollTop = 0;
    start(1);
    const back = () => start(-1);
    pg.querySelector(".pback").onclick = back;
    return back;
  };
  /* the interactive pop (nav-edge.js, BOARD #12; nav-native-formula.md §0 / §2): while the finger is down the progress value follows the
     gesture's percent through the interactiveSpring's TRACKING triple ζ .85 / response .08 (0x1c5410ffc–0x1c5411054; setFractionComplete:
     0x1c54d3ea0 → 0x1c54d4c14); at the release the same animator continues to 1 (finish) or 0 (cancel) on the spring's normal triple
     ζ .85 / .3 with the handed-over velocity (0x1c40e7c54 → _continueAnimationWithStartingVelocity:). Here p = 1 − percent. */
  const TRACK = [.85, .08], RELEASE = [.85, .3];
  const interactive = {
    begin() {   // pop starts interactively: from the shown page (p 1), or from a running transition's current value (pauseInteractiveTransition)
      if (!st.pg || st.pg.hidden) return false;
      if (!st.pg.classList.contains("nav-live")) { st.p = 1; st.v = 0; st.dir = -1; st.pg.classList.remove("in", "out"); document.body.classList.remove("pushed"); st.pg.classList.add("nav-live"); document.body.classList.add("nav-live"); write(); }
      st.dir = -1; st.tracking = true; st.spring = TRACK; st.target = st.p; run(); return true;
    },
    percent() { return 1 - st.p; },
    set(q) { st.target = 1 - q; },   // q = the gesture's percent (rubber-banded by the caller)
    end(finish, vProgress) {   // vProgress = the handed-over velocity in progress units / s (percent increasing = p decreasing)
      st.tracking = false; st.spring = RELEASE; st.v = -vProgress; st.target = finish ? 0 : 1; st.last = performance.now(); run();
    },
  };
  window.Nav = { open, back: () => { if (st.pg) start(-1); }, state: st, fIn, fOut, u1, u2, SPRING, TRACK, RELEASE, interactive, KF, CHEV0, seg, parallax };
})();
