/* sheet.js — drag-to-dismiss for the picker sheet (#picker), BOARD.md #10 (+ #11: the dimming and the corner along the travel).
   Basis: remote-ref/sheet-native-formula.md §5 / §7b / §8b (iOS 27.0 UIKitCore UISheetPresentationController, the old page session's
   decompile) and pagesheet-motion.md (数据). Every number below is a read original; the unread ones are named and left out.
   geometry: container = the screen, the card rests at y 62 (safe-area top) = large, the only detent; dismiss = the card fully below
     (y 956 = 62 + 894); percentDisplayed = (956 − y) / 894, linear (single detent — measured, sheet-native-formula.md line 102: nine release points to 5 places;
     the multi-detent form is unread, not used by a one-detent sheet)
   follow: y = 62 + finger Δy, 1:1 (handlePan: 0x1c3c78008 → draggingChangedInSource:), no spring while the finger is down
   above the top detent: y = 62 − d, d = E·(1 − 1/(1 + .55·u/E)), u = the finger's upward excess, c = .55 (__UIScrollViewRubberBandCoefficient
     0x1c4e3f3f0), E = clamp(.25 × 894, 0, 200) = 200 (SheetLayoutInfo._rubberBandExtentBeyondMaximumOffset 0x1c5399428, branch A)
   velocity: UIPanGestureRecognizer velocityInView — per move a sample v_i = Δy/Δt (Δt ≤ 1 ms → 0); v = .2·v_newest + .8·v_previous
     (previous present and its dt > 1.2e−7), else v_newest (§8b 速度估计器)
   release: projection p′ = p + .099·v (deceleration .99 → .099 s; v down positive, pt/s; 0x1c3c78c98, 0x1c5717fe8); only large and
     dismiss exist: p′ nearer dismiss → dismiss, else back to 62; |v| ≥ 1000 pt/s downward → dismiss even when p′ stays in large's region
     (0x1c5718170); an upward fling with no higher detent → back to 62
   settle: spring response .3441 (ω 18.26), ζ 1 when |v| < 1000, ζ .8 when ≥ 1000 (_setInteractionEndedSpringParameters:, 0x1c57181c0),
     from the release y with the release velocity; the dimming rides percentDisplayed; corner 38 stays through the motion (§7b 圆角: static)
   done / back buttons keep index.html's own spring path (Behaviour 5); this file only adds the gesture. Touch events (not pointer events)
   because taking the drag over from the list at its top needs preventDefault on touchmove.
   The settle on the compositor (中继一 10-01): Chrome on Android throttles main frames — rAF, style, layout — to 60 Hz while no input is coming
     (Chromium ThrottleMainFrameTo60Hz, on by default there; CL 6054335), so the settle driven by tick() after the finger is up ran at 60 on a 120 Hz
     phone (ark-diag/flu/20261001020900-2962f687-1.json) — and custom properties (--sheet-y / --sheet-dim) never animate on the compositor anyway.
     The same closed-form spring (Motion.spring, from the release (y, v)) is sampled into two Web Animations started at the release time t0:
     .card transform translateY(y − 62) and .dim opacity percentDisplayed (the values write() would give at those times). Samples come from
     Motion.sample (motion.js; steps ≤ 1 / 120 s, halved while a chord misses the spring by > .003 pt or the dimming by > 3e−4 at 1/4, 1/2, 3/4 —
     plain 1 / 120 s chords miss by up to ~2 pt early in a dismiss, h²/8 · ω²·Δy), then Motion.thin keeps each property's own nodes: the card
     ~all of them, the dim 3–46 instead of 133–551 (its opacity is linear in y, so its 3e−4 needs far fewer; BOARD/evidence/中继一-1001-dedup). The end is tick()'s own: the instant t* where |y − target| < .1 and |v| < 5 first
     holds (bisected), the spring's value up to t*, then a step to the target — so a frame at any time shows what tick() would have written there.
     transform / opacity run on the compositor (headless Chrome 154, 440×956, main thread blocked 500 ms from +20 ms after a release at 262: no
     compositeFailed on either animation, 24 draws in the middle 400 ms, the card's top at 22 positions 177 → 1 (the rAF path: frozen at 193);
     old and new at the old path's frame times: ≤ .0055 pt / 5.1e−5 opacity over back / dismiss / fling ζ .8 / upward fling / rubber band —
     BOARD/evidence/中继一-1001-合成器/sheet; after the Motion.sample / thin dedup ≤ .007 pt / 3.1e−4 opacity, the opacity at its 3e−4 tolerance
     by construction — BOARD/evidence/中继一-1001-dedup). The finish no longer leaves index.html's transition running from the last frame's value (≤ .13 pt). While the
     animations run, state.y / v / elapsed are computed from the spring at the animation's current time (what the style shows). The finish writes
     the rest state first, then cancels the animations, in one task (no frame of the CSS base value between). A touch on the moving sheet catches it
     (the old tick() path ignored such a touch): the spring's value at now − t0 is written to --sheet-y, the animations are cancelled and the touch
     is the sheet's drag from there — the rAF path catches the same way. WebKit, reduced motion, no Element.animate, or ?sheetwa=0 keep the rAF path. */
(() => {
  "use strict";
  const REST_Y = 62, TRAVEL = 894, DISMISS_Y = REST_Y + TRAVEL, RESPONSE = .3441, C = .55, E = 200, DECEL_T = .099, FLING = 1000;
  const sheet = document.querySelector("#picker"); if (!sheet) return;
  const card = sheet.querySelector(".card"), dim = sheet.querySelector(".dim"), list = sheet.querySelector(".plist");
  /* WebKit keeps the rAF path, as menu.js does (aad04315, menu.js: "WebKit (no main-frame throttle; clip-path animations not composited there) and
     reduced motion keep the rAF path"): no 60 Hz main-frame throttle there, so nothing to gain and the path is untested on it. Same test as menu.js WK. */
  const WK = typeof CSS !== "undefined" && CSS.supports("mix-blend-mode", "plus-darker");
  const WA = !WK && typeof Element !== "undefined" && typeof Element.prototype.animate === "function" && !/[?&]sheetwa=0\b/.test(location.search);
  const reduce = () => { try { return matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return false; } };
  const st = { _y: REST_Y, _v: 0, _elapsed: 0, target: REST_Y, raf: 0, last: 0, t0: 0, zeta: 1, live: false, drag: null, wa: null };
  const spring = (w, t) => { if (t >= w.T) return { x: w.target, v: 0 }; return Motion.spring({ x: w.y0, v: w.v0 }, w.target, [w.zeta, RESPONSE], t); };   // the settle's closed form at t s after t0
  const waT = (w) => Math.max(0, (w.card.currentTime || 0) / 1000);   // the animation's current time = what the style shows now
  Object.defineProperties(st, {
    y: { enumerable: true, get() { return this.wa ? spring(this.wa, waT(this.wa)).x : this._y; }, set(v) { this._y = v; } },
    v: { enumerable: true, get() { return this.wa ? spring(this.wa, waT(this.wa)).v : this._v; }, set(v) { this._v = v; } },
    elapsed: { enumerable: true, get() { return this.wa ? Math.min(waT(this.wa), this.wa.T) : this._elapsed; }, set(v) { this._elapsed = v; } },
    x: { get() { return this.y; }, set(v) { this.y = v; } },   // Motion.spring's state names
  });
  const dimAlpha = () => parseFloat(getComputedStyle(sheet).getPropertyValue("--ios-dimming").match(/\/\s*([\d.]+)/)?.[1] || ".2");   // .2 light / .48 dark (tokens)
  const shownAt = (y) => Math.max(0, Math.min(1, (DISMISS_Y - y) / TRAVEL));
  const write = () => {
    const y = st.y, shown = Math.max(0, Math.min(1, (DISMISS_Y - y) / TRAVEL));
    sheet.style.setProperty("--sheet-y", (y - REST_Y).toFixed(2) + "px");   // the card's own rest is y 62: translate = y − 62
    sheet.style.setProperty("--sheet-dim", shown.toFixed(4));               // .dim's own colour carries the .2 / .48: opacity = percentDisplayed
  };
  const go = () => { if (!sheet.classList.contains("sheet-live")) { sheet.classList.add("sheet-live"); } write(); };
  const finish = () => {
    sheet.classList.remove("sheet-live"); sheet.style.removeProperty("--sheet-y"); sheet.style.removeProperty("--sheet-dim");
    if (st.target === DISMISS_Y) { sheet.classList.remove("in"); document.documentElement.classList.remove("sheet-open"); sheet.removeAttribute("open"); st.y = REST_Y; }
    else { st.y = REST_Y; sheet.classList.add("in"); }   // rest = index.html's state; the values are equal, nothing transitions
    st.v = 0; st.live = false;
  };
  const tick = (now) => {
    if (!st.first) st.first = now;
    const dt = Math.min(1, Math.max(0, (now - st.last) / 1000)); st.last = now; st.elapsed += dt;
    Motion.spring(st, st.target, [st.zeta, RESPONSE], dt);
    const done = Math.abs(st.y - st.target) < .1 && Math.abs(st.v) < 5;
    if (done) { st.y = st.target; st.v = 0; write(); st.raf = 0; finish(); return; }
    write(); st.raf = requestAnimationFrame(tick);
  };
  /* the settle as keyframes: see the header. null when the spring is done at release (tick() ends it on its first frame) */
  const TOL_Y = .003, TOL_O = 3e-4, H = 1 / 120;
  const waSample = (w) => {
    const done = (s) => Math.abs(s.x - w.target) < .1 && Math.abs(s.v) < 5, at = (t) => Motion.spring({ x: w.y0, v: w.v0 }, w.target, [w.zeta, RESPONSE], t);
    if (done(at(0))) return null;
    let i = 1; while (i < 480 && !done(at(i * H))) i++;   // 4 s cap: the spring rests in < 1 s
    let lo = (i - 1) * H, hi = i * H; for (let k = 0; k < 40; k++) { const m = (lo + hi) / 2; if (done(at(m))) hi = m; else lo = m; }
    /* keyframes through Motion.sample (motion.js) on [y, shownAt(y)], then Motion.thin per property (as view.js's re-order does): the card keeps the
       nodes its translate needs, the dim the nodes its opacity needs, each within its own tolerance of the spring at the probes */
    const tol = [TOL_Y, TOL_O], T = hi, nd = Motion.sample((t) => { const y = at(t).x; return [y, shownAt(y)]; }, T, tol, { h0: H });
    const card = Motion.thin(nd, 0, 1, tol, nd.err).map((i) => ({ offset: nd[i][0] / T, transform: `translateY(${(nd[i][1][0] - REST_Y).toFixed(3)}px)` }));
    const dim = Motion.thin(nd, 1, 2, tol, nd.err).map((i) => ({ offset: nd[i][0] / T, opacity: nd[i][1][1].toFixed(5) }));
    card[card.length - 1].offset = dim[dim.length - 1].offset = 1;
    card.push({ offset: 1, transform: `translateY(${(w.target - REST_Y).toFixed(3)}px)` }); dim.push({ offset: 1, opacity: shownAt(w.target).toFixed(5) });   // tick()'s snap to the target at t*
    return { T, card, dim };
  };
  const waRun = (target, v0, zeta) => {
    const w = { y0: st._y, v0, target, zeta, t0: performance.now() }, k = waSample(w); if (!k) return false;
    const o = { duration: k.T * 1000, fill: "both", easing: "linear" };
    w.T = k.T; w.card = card.animate(k.card, o); w.dim = dim.animate(k.dim, o); w.card.startTime = w.dim.startTime = w.t0; st.t0 = w.t0; st.wa = w;
    w.card.onfinish = () => { if (st.wa !== w) return; st.wa = null; st._y = target; st._v = 0; st._elapsed = w.T; finish(); w.card.cancel(); w.dim.cancel(); };   // rest state first, then the animations off: one task
    return true;
  };
  const settle = (target, v0, zeta) => {
    if (WA && !reduce()) { st.target = target; st.zeta = zeta; st.live = true; st.first = 0; st._v = v0; st._elapsed = 0; if (waRun(target, v0, zeta)) return; }
    st.target = target; st.v = v0; st.zeta = zeta; st.live = true; st.last = st.t0 = performance.now(); st.first = 0; st.elapsed = 0; if (!st.raf) st.raf = requestAnimationFrame(tick); };
  /* a touch on the moving sheet catches it where the spring is now (the curve, not a style read) */
  const catchSheet = () => {
    const w = st.wa;
    if (w) { const s = spring(w, Math.max(0, (performance.now() - w.t0) / 1000)); st.wa = null; st._y = s.x; st._v = 0; write(); w.card.cancel(); w.dim.cancel(); return true; }
    if (st.raf) { cancelAnimationFrame(st.raf); st.raf = 0; st.v = 0; return true; }   // the rAF path: st.y is its last frame
    return false;
  };
  /* the gesture */
  const begin = (x, y, target, t) => {
    if (!sheet.classList.contains("in")) return;
    const caught = catchSheet(), inList = list && list.contains(target), y0 = st.y, d0 = REST_Y - y0;
    const raw0 = d0 > 0 ? REST_Y - (E / C) * d0 / (E - d0) : y0;   // the finger position that puts the sheet at y0 (the rubber band inverted above the top)
    st.drag = { x0: x, y0: y, t0: t, inList, taken: caught, dead: false, samples: [], lastY: y, lastT: t, y: y0, raw0 };   // a caught sheet is the finger's from the start
  };
  const move = (x, y, t, ev) => {
    const d = st.drag; if (!d || d.dead) return;
    const dx = x - d.x0, dy = y - d.y0;
    if (!d.taken) {
      if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 6) { d.dead = true; return; }            // a sideways move is not ours
      if (dy > 0 && (!d.inList || list.scrollTop <= 0)) { d.taken = true; go(); }                    // down, and the list is at its top → the sheet's
      else if (dy < 0 && !d.inList) { d.taken = true; go(); }                                        // up on the bar: the rubber band
      else if (Math.abs(dy) > 6) { d.dead = true; return; }                                          // the list scrolls
      if (!d.taken) return;
    }
    if (ev && ev.cancelable) ev.preventDefault();
    const dt = (t - d.lastT) / 1000; if (dt > 0) { d.samples.push({ v: dt <= .001 ? 0 : (y - d.lastY) / dt, dt }); if (d.samples.length > 2) d.samples.shift(); }
    d.lastY = y; d.lastT = t;
    const raw = d.raw0 + dy;
    if (raw < REST_Y) { const u = REST_Y - raw; st.y = REST_Y - E * (1 - 1 / (1 + C * u / E)); } else st.y = Math.min(DISMISS_Y, raw);
    write();
  };
  const end = (cancelled) => {
    const d = st.drag; st.drag = null; if (!d || !d.taken) return;
    const s = d.samples, vNew = s.length ? s[s.length - 1].v : 0, vPrev = s.length > 1 ? s[s.length - 2] : null;
    const v = vPrev && vPrev.dt > 1.2e-7 ? .2 * vNew + .8 * vPrev.v : vNew;                            // velocityInView (§8b)
    if (cancelled) { settle(REST_Y, 0, 1); return; }
    const p = st.y, proj = p + DECEL_T * v;                                                             // _projectedPoint
    const toDismiss = v >= FLING || (v > -FLING && (DISMISS_Y - proj) < (proj - REST_Y));              // a downward fling, or below 1000 pt/s the projection alone
    /* sheet-native-formula.md line 16: "任意速度 < 1000 只看投影落点" — a still (v 0) or slowly rising release whose p′ is nearer dismiss dismisses;
       the old `v > 0 &&` sent those back to 62 (reachable once a moving sheet can be caught: catch it low, lift). An upward fling ≥ 1000 → 62 (line 60). */
    settle(toDismiss ? DISMISS_Y : REST_Y, v, Math.abs(v) >= FLING ? .8 : 1);
  };
  card.addEventListener("touchstart", (e) => { if (e.touches.length !== 1) return; const t = e.touches[0]; begin(t.clientX, t.clientY, e.target, e.timeStamp); }, { passive: true });
  card.addEventListener("touchmove", (e) => { if (e.touches.length !== 1) return; const t = e.touches[0]; move(t.clientX, t.clientY, e.timeStamp, e); }, { passive: false });
  card.addEventListener("touchend", () => end(false)); card.addEventListener("touchcancel", () => end(true));
  card.addEventListener("pointerdown", (e) => { if (e.pointerType !== "mouse" || e.button !== 0) return; begin(e.clientX, e.clientY, e.target, e.timeStamp);
    const mv = (ev) => move(ev.clientX, ev.clientY, ev.timeStamp, null), up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); end(false); };
    addEventListener("pointermove", mv); addEventListener("pointerup", up); });
  window.Sheet = { state: st, REST_Y, DISMISS_Y, E, C, RESPONSE, FLING, DECEL_T, begin, move, end };
})();
