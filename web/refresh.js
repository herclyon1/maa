/* refresh.js — pull to refresh as UIRefreshControl (iOS 27 modern content view), geometry and timing only (BOARD.md #8, night batch).
   Source of every number: remote-ref/refresh-native-formula.md (UIKitCore decompiled, addresses in that file's §0–§2). Nothing here is sampled or
   guessed; sub-effects that file marks unread (§6) are left out and listed at the end.

   Model (§2):
     H        = the scroll view's height = the visual viewport's height (innerHeight; the page's body is the scroll view)
     maxSnap  = (titleH + 100) × 1.125 × max(H, 372) / 568   — no title here → 112.5 × max(H, 372) / 568   (0x1c415a27c / 0x1c415a228)
     snap     = clamp(round(H / 2), 0, maxSnap)                                                             (0x1c4122c48)
     show     = min(1, visibleHeight / maxSnap)   → the arms' 1 s reveal animation dragged by timeOffset = show (§0 "拉出时怎么画出来")
     arm i α  = clamp(1 + i·(show − 1), 0, 1) × show   (instanceAlphaOffset −1 → 0 with the replicator's alpha 0 → 1, §0 / §4.1)
     f        = clamp(visibleHeight / (state 0 or 3 ? h_ctl 60 : snap), 0, 1)                                  (0x1c4122190)
     trigger  = state 1 and f ≥ 1 and the finger still down (isTracking) — not on the release                 (0x1c4122944–0x1c412297c)
     spin     = spring on the rotation to 3.1316 rad: m 1, k = clamp(|v_y| × 48.333, 5, 150), c 5000, 4 s cap; CASpringAnimation does not
                allow overdamping by default → drawn critically damped, ζ 1, ω = √k (§2 "k")
     tick     = while refreshing: +45° every 125 ms, discrete (calculationModeDiscrete), 1 s a turn, repeating                    (_tick 0x1c4159da8)
     goAway   = endRefreshing: 0.3 s ease-in-out, alpha → 0 and rotate a further 3.1316 rad                                   (_goAway 0x1c4159f30)
   visibleHeight is the finger's pull beyond the top while scrollY ≤ 0 (the rubber-band mapping of UIScrollView is unread, §6.3 — the finger's
   distance is used as is).

   States (the decompiled machine, §0 "状态机"): 0 idle · 1 revealing · 3 refreshing · 4 going away. (2 is the instantaneous trigger step; 5 / 6 are
   the bounce-back edge cases, not modelled — a finger returning during 4 is treated as a new pull.)

   Left out (unread in the source, refresh-native-formula.md §6): the arms' length / ring radius / placement (the page keeps the 20 pt activity
   indicator bars of the Kit dump: index.html .ai), the content inset 60 while refreshing and its scroll-back curve (§6.3 — adding the inset with an
   unread return curve would end in a jump), the 0.05 s bloom transform, the spun instanceAlphaOffset .08 semantics, the haptic.
   Instrument: window.Refresh.__drive({ pull, v, down }) feeds a pull without touch events (accept-refresh.js). */
(function () {
  const ptr = document.getElementById("ptr"), ai = document.getElementById("ptrai");
  if (!ptr || !ai) return;
  const arms = [...ai.querySelectorAll("i")];
  const H_CTL = 60, ROT_SPUN = 3.1316, TICK_MS = 125, TICK_DEG = 45, GOAWAY_MS = 300, SPIN_CAP_S = 4, K_PER_V = 48.333, K_MIN = 5, K_MAX = 150;
  const H = () => (window.visualViewport ? window.visualViewport.height : innerHeight);
  const maxSnap = (titleH = 0) => (titleH + 100) * 1.125 * Math.max(H(), 372) / 568;
  const snapH = () => Math.max(0, Math.min(Math.round(H() / 2), maxSnap()));
  const armAlpha = (i, show) => Math.max(0, Math.min(1, 1 + i * (show - 1))) * show;

  let state = 0, pull = 0, rot = 0, raf = 0, spin = null, spinT0 = 0, tickT0 = 0, tickBase = 0, goT0 = 0, y0 = null, lastY = 0, lastT = 0, vel = 0, refreshing = null;
  const setArms = (show) => { arms.forEach((a, i) => { a.style.opacity = armAlpha(i, show).toFixed(3); }); ptr.style.opacity = show > 0 ? "1" : "0"; };
  const setRot = (deg) => { ai.style.transform = `rotate(${deg.toFixed(2)}deg)`; };
  const setState = (s) => { if (s === state) return; state = s; ptr.dataset.state = String(s); ptr.classList.toggle("refreshing", s === 3); };
  const reset = () => { cancelAnimationFrame(raf); raf = 0; spin = null; rot = 0; pull = 0; setArms(0); setRot(0); ai.style.opacity = ""; setState(0); };

  /* state 1: the reveal follows the pull; f ≥ 1 with the finger down → trigger (state 3) */
  const fOf = () => Math.max(0, Math.min(1, pull / (state === 0 || state === 3 ? H_CTL : snapH())));   // f's divisor is the CURRENT state's (0x1c4122190): h_ctl 60 in 0 / 3, snap in 1
  const reveal = (visible, down) => {
    pull = Math.max(0, visible);
    const show = Math.min(1, pull / maxSnap());
    if (state === 0) { if (fOf() > 0 && pull > 5) setState(1); else return; }
    if (state !== 1) return;
    setArms(show);
    const f = fOf();   // recomputed in state 1 (divisor snap): the trigger test of _recomputeNewState
    if (f >= 1 && down) trigger();
    else if (f < 1 && pull <= 5) { setState(0); setArms(0); }
  };
  /* state 3: the spin spring (rotation → 3.1316 rad, ζ 1, ω = √k, k from the pull velocity), all arms lit, then the 125 ms / 45° tick */
  const trigger = () => {
    setState(3); arms.forEach((a) => { a.style.opacity = "1"; }); ptr.style.opacity = "1";
    const k = Math.max(K_MIN, Math.min(K_MAX, Math.abs(vel) * K_PER_V)), w = Math.sqrt(k);
    spin = { s: { x: rot, v: 0 }, target: rot + ROT_SPUN * 180 / Math.PI, resp: 2 * Math.PI / w, k }; spinT0 = performance.now(); tickT0 = 0; frame.prev = spinT0;   // the first step integrates from the trigger, not from a stale frame
    Refresh.lastK = k;
    cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
    refreshing = Refresh.onRefresh ? Refresh.onRefresh() : (typeof window.ping === "function" ? window.ping() : Promise.resolve());   // the page's refresh (live.js ping); accept swaps its own
    Promise.resolve(refreshing).catch(() => {}).finally(() => { if (state === 3) endRefreshing(); });
  };
  const frame = (now) => {
    if (state === 3) {
      if (spin) {
        const t = (now - spinT0) / 1000, dt = Math.min(0.05, Math.max(0, (now - (frame.prev || now)) / 1000));
        if (window.Motion) window.Motion.spring(spin.s, spin.target, [1, spin.resp], dt); else spin.s.x = spin.target;
        rot = spin.s.x; setRot(rot);
        if (t >= SPIN_CAP_S || Math.abs(spin.s.x - spin.target) < 0.05) { rot = spin.target; setRot(rot); spin = null; tickT0 = now; tickBase = rot; }
      } else {
        rot = tickBase + Math.floor((now - tickT0) / TICK_MS) * TICK_DEG; setRot(rot);   // discrete: a jump every 125 ms, no interpolation
      }
      frame.prev = now; raf = requestAnimationFrame(frame); return;
    }
    if (state === 4) {
      const u = Math.min(1, (now - goT0) / GOAWAY_MS), e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;   // ease-in-out (UIView curve 0)
      ai.style.opacity = String(1 - e); setRot(rot + ROT_SPUN * 180 / Math.PI * e);
      if (u >= 1) { reset(); return; }
      frame.prev = now; raf = requestAnimationFrame(frame); return;
    }
  };
  const endRefreshing = () => { if (state !== 3) return; setState(4); spin = null; goT0 = performance.now(); frame.prev = goT0; cancelAnimationFrame(raf); raf = requestAnimationFrame(frame); };

  /* touch: the pull is the finger's travel below its start while the page is at the top */
  addEventListener("touchstart", (e) => { if (e.touches.length !== 1) { y0 = null; return; } y0 = window.scrollY <= 0 ? e.touches[0].clientY : null; lastY = e.touches[0].clientY; lastT = e.timeStamp; vel = 0; }, { passive: true });
  addEventListener("touchmove", (e) => {
    if (y0 === null || state === 3 || state === 4) return;
    const y = e.touches[0].clientY, dt = (e.timeStamp - lastT) / 1000; if (dt > 0) vel = (y - lastY) / dt; lastY = y; lastT = e.timeStamp;
    reveal(y - y0, true);
  }, { passive: true });
  const up = () => { if (y0 === null) return; y0 = null; if (state === 1) { setState(0); setArms(0); } };   // released before f reached 1: nothing happens (the trigger needs the finger)
  addEventListener("touchend", up, { passive: true }); addEventListener("touchcancel", up, { passive: true });

  const Refresh = {
    maxSnap, snapH, armAlpha, get state() { return state; }, get pull() { return pull; }, get rotation() { return rot; }, get spin() { return spin; },
    endRefreshing, reset, lastK: null, onRefresh: null,   // onRefresh: () => Promise — the refresh to wait for (default live.js ping())
    /* instrument: __drive({ pull, v, down }) — a pull of `pull` pt with velocity v pt/s and the finger down / up, no touch events */
    __drive(o) { if (o.v != null) vel = o.v; if (o.down === false) { up(); return state; } y0 = 0; reveal(o.pull || 0, true); return state; }
  };
  window.Refresh = Refresh;
})();
