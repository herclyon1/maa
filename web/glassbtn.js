/* glassbtn.js — the round glass buttons' press (返回 .pnav .navbtn.pback, ✕ #discard and ✓ #save in the editing top bar): the lift scale and its
   two springs, and the 70 pt release rule (BOARD.md #5, night batch: scale and timing only — the state-3 material and the glow are unread and untouched).
   Basis (read values, glass-button-press-formula.md §0 table / §2): the glass is `flexible` → _UIFlexInteraction; its pan recogniser is active from
   touchesBegan, so on the down the button's scale springs to L = (min(W, H) + 16) / min(W, H) (liftScalePoints 16: 44 → 1.3636) on the
   ultraSmall TRACKING spring ζ .625 / response .262 s; on the up it springs back to 1 on the non-tracking spring ζ .375 / response .4 s
   (underdamped: it overshoots below 1 and settles); the touch is a tap when the finger lifts within 70 pt of the button (state-tables/button.md,
   interaction-spec §4). The three buttons are 44 × 44 (tokens.css --ios-nav-button; the accept checks it).
   Unread, left out: the flex stretch while dragging (§2 "按住拖动", flex-interaction.md §3 ultraSmall) — the scale stays at L while held; the
   state-3 material key and the glow layers (§6.1 / §6.4); the sampled peak 1.135 vs the formula's 1.364 (§6.5, BOARD 5a) — the formula's value
   is used until the read says otherwise. Springs: Motion.spring only (motion.js #1). Without Motion nothing is installed.
   The click: the page's own handlers stay on the buttons; a release inside 70 pt fires Motion.click(el) (the browser's own click for the touch is
   swallowed, B14's rule), a release outside fires nothing (the browser's click — the button holds pointer capture — is swallowed too). */
(function () {
  if (!window.Motion || typeof Motion.spring !== "function") return;
  const SEL = ".pnav .navbtn, .topbar .navbtn";
  const TRACK = [0.625, 0.262], RELEASE = [0.375, 0.4], LIFT_PT = 16, SLOP = 70;
  const live = new Map();   // el → { s: {x, v}, phase: "hold" | "release", target, t0, prev, raf, x0, y0, inside }
  const L = (el) => { const r = el.getBoundingClientRect(), m = Math.min(r.width, r.height); return m > 0 ? (m + LIFT_PT) / m : 1; };
  /* the 70 pt margin is around the control's bounds, not the scaled presentation: centre from the (transformed) rect — the origin is the centre, so it
     does not move — and the half-sizes from the layout box (offsetWidth / Height are untransformed) */
  const inside = (el, x, y) => { const r = el.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2, hw = el.offsetWidth / 2, hh = el.offsetHeight / 2;
    return x >= cx - hw - SLOP && x <= cx + hw + SLOP && y >= cy - hh - SLOP && y <= cy + hh + SLOP; };
  const apply = (el, st) => { el.style.transform = st.s.x === 1 && st.phase === "release" && Math.abs(st.s.v) < 0.01 ? "" : `scale(${st.s.x})`; };
  const tick = (el) => (now) => { const st = live.get(el); if (!st) return;
    const dt = Math.min(0.04, Math.max(0, (now - st.prev) / 1000)); st.prev = now;
    Motion.spring(st.s, st.target, st.phase === "hold" ? TRACK : RELEASE, dt); apply(el, st);
    if (st.phase === "release" && Math.abs(st.s.x - 1) < 0.001 && Math.abs(st.s.v) < 0.01) { el.style.transform = ""; live.delete(el); return; }
    st.raf = requestAnimationFrame(tick(el)); };
  const run = (el, st) => { if (st.raf) cancelAnimationFrame(st.raf); st.prev = performance.now(); st.t0 = st.prev; st.raf = requestAnimationFrame(tick(el)); };
  const down = (el, e) => {
    const prev = live.get(el); const s = prev ? prev.s : { x: 1, v: 0 };   // a press during the previous release continues from its value and velocity
    if (prev && prev.raf) cancelAnimationFrame(prev.raf);
    const st = { s, phase: "hold", target: L(el), t0: 0, prev: 0, raf: 0, pointerId: e.pointerId, in: true, x: e.clientX, y: e.clientY };
    live.set(el, st); el.style.transformOrigin = "50% 50%"; run(el, st);
    const move = (ev) => { if (ev.pointerId !== st.pointerId) return; st.x = ev.clientX; st.y = ev.clientY; st.in = inside(el, ev.clientX, ev.clientY); };
    const detach = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", cancel); };
    st.detach = detach;
    const end = (ev, cancelled) => { if (ev.pointerId !== st.pointerId) return;
      detach();
      const hit = !cancelled && inside(el, ev.clientX, ev.clientY);
      st.phase = "release"; st.target = 1; run(el, st);
      Motion.swallowNextClick(el);   // the browser's click for this touch (the button holds the capture, so it comes wherever the finger lifted)
      if (hit) Motion.click(el); };
    const up = (ev) => end(ev, false), cancel = (ev) => end(ev, true);
    el.addEventListener("pointermove", move); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", cancel);
    try { el.setPointerCapture(e.pointerId); } catch {}
  };
  document.addEventListener("pointerdown", (e) => { if (e.pointerType === "mouse" && e.button !== 0) return; const el = e.target.closest && e.target.closest(SEL); if (!el || el.disabled) return; down(el, e); });
  /* hidden strips the press (BOARD A6 template): no scale left on a button, no click fired for a touch the page never saw end */
  document.addEventListener("visibilitychange", () => { if (!document.hidden) return; for (const [el, st] of live) { if (st.raf) cancelAnimationFrame(st.raf); if (st.detach) st.detach(); if (st.phase === "hold") Motion.swallowNextClick(el); el.style.transform = ""; } live.clear(); });
  window.GlassBtn = { L, state: (el) => { const st = live.get(el); return st ? { phase: st.phase, target: st.target, x: st.s.x, v: st.s.v, t0: st.t0, inside: st.in } : null }, SLOP, TRACK: [...TRACK], RELEASE: [...RELEASE] };
})();
