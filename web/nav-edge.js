/* nav-edge.js — the interactive back gesture on the pushed page (#subpage), BOARD.md #12. Basis: remote-ref/nav-native-formula.md §0 rows
   交互式返回 / 手指 → 进度 / 橡皮筋 / 松手 / 速度统计, §2, §3 (iOS 27.0 UIKitCore _UINavigationInteractiveTransition + UIScreenEdgePan
   settings; the old page session's decompile). Read values only; the unread parts are named and left out.
   recognition: the screen's left edge, region W × .10 (IsLargeFormatPhone; .09 otherwise — the MG flag of this phone is unread, .10 used:
     44 pt at W 440), hysteresis 15 pt before it begins, angle window 155° (2.7053 rad) about the edge normal
     (_UIScreenEdgePanRecognizerEdgeSettings 0x1c43969d4); the recognizer engine is read (nav-native-formula.md §5c / §5e / §5i): the
     decision is taken at the first sample beyond 15 pt from the touch-down (atan2 vs the edge normal, remainderl, |Δθ| < 77.5°), the
     translation counts from the touch-down minus the pan's 10 pt hysteresis (below), and the "edge-angle-window decay" test
     (_incorporateIncrementalSampleAtLocation: 0x1c4398650–0x1c43986b0) compares a register that is zeroed at 0x1c43984e8 and never
     written again against max(20, 15·tan(77.5°)·(1 − t/.5)) — it can never fail in iOS 27.0, so there is no dwell / drift rule to
     mirror (BOARD R67); content_backswipe (anywhere on the page) is a feature flag of unknown state — not done
   percent: base + Δx / W (coef +1; base = the running pop's percent when interrupting one) (handleNavigationTransition: 0x1c4c3b788);
     fluid rubber band beyond [0, 1]: > 1 → 1 + .5(1 − 1/(1 + .55(q − 1)/.5)); < 0 → −.5(1 − 1/(1 + .55(−q)/.5)) (0x1c4c3b88c, c .55)
   drive: the percent is the target of the tracking spring ζ .85 / .08 in nav.js (setFractionComplete:)
   statistics (_updateStatistics: 0x1c4c3b0b0): a sample per move (the first at began); dropped when Δt < 10 ms and (≤ 1 ms or no
     movement); v = velocity / W (W/s) with velocityInView = .2·v_newest + .8·v_previous of the pan's own samples (sheet-formula §8b, the
     same recognizer class); a = (v − v_prev)/Δt, each change clamped to ±5; v̄, ā = cumulative means of the first 3 samples, then a
     rolling 3-sample mean; the edge-flick phase holds while |v̄| ≥ 1.5 W/s from began and ends for good once below
   release (popGesture:… 0x1c4c3b46c, §3): proj = q + .35·v̄ + .5·.35²·ā; thr = min(187.5 / W, .5) (0x1c5721ac0); with ≥ 3 samples in the
     changed state finish = proj > thr, else finish = v̄ > 0; v_out = W·v_prev × (edge flick ? 4.25 : 1) (0x2f8 / 0x2f0); then nav.js's
     release spring ζ .85 / .3 with v_out / W to 1 (finish → popped) or 0 (cancel → back). */
(() => {
  "use strict";
  const REGION = .10, HYST = 15, ANGLE = 2.7053, DECEL_T = .35, THR_PT = 187.5, FLICK = 1.5, BOOST = 4.25, RB_EXT = .5, RB_C = .55;
  const PAN_HYST = 10;   // the pan's own hysteresis (+[UIPanGestureRecognizer _defaultHysteresis] 0x1c4380c10): at recognition the translation, counted from the touch-down, is reduced by it (_removeHysteresisFromTranslation 0x1c43821dc, nav-native-formula.md §5e)
  const pg = document.querySelector("#subpage"); if (!pg) return;
  const W = () => document.documentElement.clientWidth;   // the screen width, not innerWidth (nav.js W: overflow widens innerWidth)
  const rubber = (q) => q > 1 ? 1 + RB_EXT * (1 - 1 / (1 + RB_C * (q - 1) / RB_EXT)) : q < 0 ? -RB_EXT * (1 - 1 / (1 + RB_C * (-q) / RB_EXT)) : q;
  const mean = (arr) => arr.reduce((s, x) => s + x, 0) / arr.length;
  let g = null;
  const stats = (v, t, first) => {
    const s = g.stats;
    if (!first) { const dt = t - s.t; if (dt < .010 && (dt <= .001 || v === s.vRaw)) return; }
    const dt = first ? 0 : t - s.t;
    let a = first || dt <= 0 ? 0 : (v - s.v) / dt; if (!first) a = Math.max(s.a - 5, Math.min(s.a + 5, a));   // each change clamped to ±5
    s.vs.push(v); s.as.push(a); if (s.vs.length > 3) { s.vs.shift(); s.as.shift(); }
    s.vPrev = s.v; s.v = v; s.a = a; s.t = t; s.n++; s.vRaw = v;
    s.vBar = mean(s.vs); s.aBar = mean(s.as);
    if (s.flick && Math.abs(s.vBar) < FLICK) s.flick = false;   // the edge-flick phase, once left, never returns
  };
  const velocityInView = () => { const p = g.pan; return p.prev && p.prev.dt > 1.2e-7 ? .2 * p.newest.v + .8 * p.prev.v : (p.newest ? p.newest.v : 0); };
  const onDown = (e) => {
    if (!e.isPrimary || pg.hidden || (e.pointerType === "mouse" && e.button !== 0)) return;
    if (e.clientX > W() * REGION) return;                       // outside the edge region
    g = { x0: e.clientX, y0: e.clientY, t0: e.timeStamp / 1000, began: false, dead: false, base: 0, q: 0, id: e.pointerId, lastX: e.clientX, lastT: e.timeStamp / 1000,
          pan: { newest: null, prev: null }, stats: { vs: [], as: [], n: 0, v: 0, a: 0, t: 0, vPrev: 0, vRaw: 0, vBar: 0, aBar: 0, flick: true }, state: "possible" };
    try { pg.setPointerCapture(e.pointerId); } catch (err) {}
    pg.addEventListener("pointermove", onMove); pg.addEventListener("pointerup", onUp); pg.addEventListener("pointercancel", onCancel);
  };
  const onMove = (e) => {
    if (!g || g.dead || e.pointerId !== g.id) return;
    const t = e.timeStamp / 1000, dx = e.clientX - g.x0, dy = e.clientY - g.y0;
    if (!g.began) {
      const pdt = t - g.lastT; if (pdt > 0) { g.pan.prev = g.pan.newest; g.pan.newest = { v: pdt <= .001 ? 0 : (e.clientX - g.lastX) / pdt, dt: pdt }; }   // the pan's samples run from the touch-down
      g.lastX = e.clientX; g.lastT = t;
      if (Math.hypot(dx, dy) <= HYST) return;                                                 // hysteresis 15 pt: decided at the first sample strictly beyond it (_UIScreenEdgePanRecognizer 0x1c4398568: dist > hysteresis)
      const ang = Math.atan2(Math.abs(dy), dx);                                              // angle from the edge normal (+x)
      if (dx <= 0 || ang > ANGLE / 2) { g.dead = true; return; }                            // outside the 155° window: not an edge pan
      if (!Nav.interactive.begin()) { g.dead = true; return; }
      g.began = true; g.state = "began"; g.base = Nav.interactive.percent();   // the translation keeps counting from the touch-down (x0), minus PAN_HYST (§5e): ≥ 5 pt at this first sample
      stats(velocityInView() / W(), t, true); return;                                         // the first sample at began carries the finger's velocity
    }
    const dt = t - g.lastT;
    if (dt > 0) { g.pan.prev = g.pan.newest; g.pan.newest = { v: dt <= .001 ? 0 : (e.clientX - g.lastX) / dt, dt }; }
    g.lastX = e.clientX; g.lastT = t;
    g.state = "changed";
    const q = g.base + Math.max(0, e.clientX - g.x0 - PAN_HYST) / W(); g.q = q;   // t' = max(0, t − 10) for a rightward pan (0x1c4382260–0x1c43822c0)
    Nav.interactive.set(rubber(q));
    stats(velocityInView() / W(), t, false);
    if (e.cancelable) e.preventDefault();
  };
  const finishGesture = (cancelled) => {
    pg.removeEventListener("pointermove", onMove); pg.removeEventListener("pointerup", onUp); pg.removeEventListener("pointercancel", onCancel);
    const gg = g; g = null; if (!gg || !gg.began) return;
    if (cancelled) { Nav.interactive.end(false, 0); return; }
    const s = gg.stats, q = gg.q, w = W();
    const proj = q + DECEL_T * s.vBar + .5 * DECEL_T * DECEL_T * s.aBar, thr = Math.min(THR_PT / w, .5);
    const finish = (s.n >= 3 && gg.state === "changed") ? proj > thr : (s.vBar > 0 && gg.state !== "began");
    const vOut = w * s.vPrev * (s.flick ? BOOST : 1);        // pt/s handed over
    Nav.interactive.end(finish, vOut / w);
    window.NavEdge.last = { q, vBar: s.vBar, aBar: s.aBar, proj, thr, n: s.n, finish, vOut, flick: s.flick };
  };
  const onUp = (e) => { if (g && e.pointerId === g.id) finishGesture(false); };
  const onCancel = (e) => { if (g && e.pointerId === g.id) finishGesture(true); };
  pg.addEventListener("pointerdown", onDown);
  window.NavEdge = { REGION, HYST, ANGLE, PAN_HYST, DECEL_T, THR_PT, FLICK, BOOST, rubber, last: null, live: () => g ? { q: g.q, base: g.base, x0: g.x0, began: g.began, dead: g.dead } : null };   // live: the running gesture's numbers (the accept reads them mid-drag)
})();
