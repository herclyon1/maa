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
  const st = { p: 0, v: 0, target: 0, raf: 0, last: 0, dir: 0, pg: null, dim: null, titleStart: 0 };
  const W = () => window.innerWidth;
  const parallax = () => -(W() - Math.round(.7 * W()));   // −132 at 440
  const write = () => {
    const pg = st.pg, p = Math.max(0, Math.min(1, st.p)), root = document.body;
    pg.style.setProperty("--nav-x", (W() * (1 - p)).toFixed(2) + "px");
    root.style.setProperty("--nav-from", (parallax() * p).toFixed(2) + "px");
    st.dim.style.setProperty("--nav-dim", p.toFixed(4));
    pg.style.setProperty("--nav-edge", (st.dir > 0 ? 1 - p : p).toFixed(4));   // strip alpha = 1 − (the running transition's own progress): push p, pop 1 − p
    const a = st.dir > 0 ? fIn(u2(p)) : 1 - fOut(u1(1 - p));   // pop runs p 1 → 0 in the same variable: the old page's items fade out with f_out
    pg.style.setProperty("--nav-in", a.toFixed(4));
    pg.style.setProperty("--nav-title", (st.titleStart * (1 - p)).toFixed(2) + "px");
  };
  const settled = () => Math.abs(st.p - st.target) < .001 && Math.abs(st.v) < .01;
  const tick = (now) => {
    if (!st.first) st.first = now;
    const dt = Math.min(1, Math.max(0, (now - st.last) / 1000)); st.last = now; st.elapsed += dt;   // elapsed: the spring's own time (the accept compares the shown values at it)   // the step is closed-form: a slow frame gets its whole elapsed time (a .05 clamp halved the motion on 100 ms frames)
    Motion.spring(st, st.target, SPRING, dt);   // st.x is st.p: the state object is {p, v} under the names Motion expects
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
    for (const k of ["--nav-x", "--nav-edge", "--nav-in", "--nav-title"]) pg.style.removeProperty(k);
    document.body.style.removeProperty("--nav-from"); st.dim.style.setProperty("--nav-dim", "0");
    if (st.target === 1) { pg.classList.add("in"); document.body.classList.add("pushed"); }               // rest = index.html's own classes
    else { pg.classList.remove("in", "out"); document.body.classList.remove("pushed"); pg.hidden = true; }
  };
  const start = (dir) => {
    const pg = st.pg;
    if (!st.dim) { st.dim = document.createElement("div"); st.dim.className = "nav-dim"; document.body.appendChild(st.dim); }
    st.dir = dir; st.target = dir > 0 ? 1 : 0;
    if (!pg.classList.contains("nav-live")) {            // from rest: p = 0 (hidden) or 1 (shown), no velocity
      st.p = dir > 0 ? 0 : 1; st.v = 0;
      pg.classList.remove("in", "out"); pg.hidden = false; document.body.classList.remove("pushed");
      const title = pg.querySelector(".ptitle"), bar = pg.querySelector(".pnav");
      if (title && bar) { const tr = title.getBoundingClientRect(), br = bar.getBoundingClientRect(), side = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ios-nav-side")) || 20;
        st.titleStart = (br.right - side) - tr.left; }    // the title area's right end (the bar minus the side inset — this page's own geometry) → its place
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
  window.Nav = { open, back: () => { if (st.pg) start(-1); }, state: st, fIn, fOut, u1, u2, SPRING };
})();
