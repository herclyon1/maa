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
   because taking the drag over from the list at its top needs preventDefault on touchmove. */
(() => {
  "use strict";
  const REST_Y = 62, TRAVEL = 894, DISMISS_Y = REST_Y + TRAVEL, RESPONSE = .3441, C = .55, E = 200, DECEL_T = .099, FLING = 1000;
  const sheet = document.querySelector("#picker"); if (!sheet) return;
  const card = sheet.querySelector(".card"), dim = sheet.querySelector(".dim"), list = sheet.querySelector(".plist");
  const st = { y: REST_Y, v: 0, target: REST_Y, raf: 0, last: 0, t0: 0, zeta: 1, live: false, drag: null };
  Object.defineProperty(st, "x", { get() { return this.y; }, set(v) { this.y = v; } });   // Motion.spring's state names
  const dimAlpha = () => parseFloat(getComputedStyle(sheet).getPropertyValue("--ios-dimming").match(/\/\s*([\d.]+)/)?.[1] || ".2");   // .2 light / .48 dark (tokens)
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
  const settle = (target, v0, zeta) => { st.target = target; st.v = v0; st.zeta = zeta; st.live = true; st.last = st.t0 = performance.now(); st.first = 0; st.elapsed = 0; if (!st.raf) st.raf = requestAnimationFrame(tick); };
  /* the gesture */
  const begin = (x, y, target, t) => {
    if (!sheet.classList.contains("in") || st.raf) return;
    const inList = list && list.contains(target);
    st.drag = { x0: x, y0: y, t0: t, inList, taken: false, dead: false, samples: [], lastY: y, lastT: t, y: st.y };
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
    const raw = REST_Y + dy;
    if (raw < REST_Y) { const u = REST_Y - raw; st.y = REST_Y - E * (1 - 1 / (1 + C * u / E)); } else st.y = Math.min(DISMISS_Y, raw);
    write();
  };
  const end = (cancelled) => {
    const d = st.drag; st.drag = null; if (!d || !d.taken) return;
    const s = d.samples, vNew = s.length ? s[s.length - 1].v : 0, vPrev = s.length > 1 ? s[s.length - 2] : null;
    const v = vPrev && vPrev.dt > 1.2e-7 ? .2 * vNew + .8 * vPrev.v : vNew;                            // velocityInView (§8b)
    if (cancelled) { settle(REST_Y, 0, 1); return; }
    const p = st.y, proj = p + DECEL_T * v;                                                             // _projectedPoint
    const toDismiss = v > 0 && (Math.abs(v) >= FLING || (DISMISS_Y - proj) < (proj - REST_Y));         // nearer dismiss, or a downward fling
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
