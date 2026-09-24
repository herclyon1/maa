/* refresh.js — pull to refresh as UIRefreshControl (iOS 27 modern content view), geometry and timing only (BOARD.md #8, R5, R5′ / R39; night batch).
   Source of every number: remote-ref/refresh-native-formula.md (UIKitCore decompiled, addresses in that file's §0–§2, §10, §11, §11a). Nothing here
   is sampled or guessed; sub-effects that file marks unread (§6) are left out and listed at the end.

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
     spun α   = in the SAME spring block (_setSpunAppearance 0x1c415940c, §11 item 3 / §11a): the replicator's instanceAlphaOffset → .08
                ([0x1c571a6b8]) and instanceColor → the tint at α 0 (_effectiveTintColorWithAlpha: 0) — arm i α = clamp((1 − p) + i·.08·p, 0, 1)
                with p the spring's progress; at rest 0 / .08 / .16 / .24 / .32 / .40 / .48 / .56 (a wheel with a fading tail; the seed's own .6 is
                in the colour token, R5)
     bloom    = at the trigger each arm (the seed layer) goes to scale 1.2 about its centre + 2 pt outward in 0.05 s linear, then back to
                identity in 0.15 s ease-in-out (§11a: _bloom 0x1c4159b68 = animateWithDuration:[0x1c5718128] .05 options 0x30000 (curve 3
                linear) → _setBloomedAppearance, completion _unbloom 0x1c4159af0 = animateWithDuration:[0x1c5717f40] .15 options 0 (curve 0
                easeInEaseOut (.42, 0, .58, 1), seg-value-change-content.md §5b) → _setUnbloomedAppearance = CGAffineTransformIdentity;
                _bloomedSeedTransform 0x1c41595b4 = identity ⊕ MakeScale([0x1c5717f18] 1.2, 1.2) ⊕ MakeTranslation(0, −2))
     tick     = while refreshing: +45° every 125 ms, discrete (calculationModeDiscrete), 1 s a turn, repeating                    (_tick 0x1c4159da8)
     goAway   = endRefreshing: 0.3 s ease-in-out (.42, 0, .58, 1), alpha → 0, the replicator's transform = current × rotate(3.1316) ×
                scale([0x1c5717f60] 0.001) — it shrinks to a point while turning half a turn (_goAway 0x1c4159f30 / block 0x1c4159fa0, §11a)
     inset    = while refreshing the content is inset by the control's height 60 (_addInsetHeight: 0x1c41231a0 → -[UIScrollView
                _addRefreshInset:] 0x1c4e3f7fc, contentInset only, no animation); endRefreshing removes it (_removeRefreshInset: 0x1c4e3f8a4)
                and, with the finger up, scrolls the content back in 0.3 s with progress sin²(π/2 · f) (_endRefreshingAnimated: 0x1c4123410 →
                _setAbsoluteContentOffset:animated: → curve 0, _contentOffsetAnimationDuration .3; tabscroll/README.md §2b path B). With the
                finger down at the end the inset just goes and the scroll view's own bounce lands at the new rest (general scroll physics).
   visibleHeight is the finger's pull beyond the top while scrollY ≤ 0 (the rubber-band mapping of UIScrollView is unread, §6.3 — the finger's
   distance is used as is).

   The inset on the web (R5′): UIKit's contentInset changes the rest position without moving the content (the offset is kept, the bounce lands
   at the new rest). A CSS inset moves the content, and while the finger is down the browser holds the content by its own overscroll offset, so
   an inset change under the finger would be a 60 pt hop. Rule here: an inset change is applied when the finger is up, or at the release — the
   moment the browser's bounce-back starts and lands at the new rest. The inset is the header's top margin (body.ptr-inset > header, R68′):
   §12 (R68, _UINavigationBarLayout _updateRefreshControlLayoutData 0x1c496da20) — the hosted refresh control is a bar layout item of order 70,
   stacked ABOVE the large-title item (order 60) and below the 54 pt content bar (order 80); the control is 60 high and centred in its item
   (height / centerY constraints 0x1c4155e98–0x1c4155ee8) → the band is safe-area + 54…114 with the spinner centre at +84 (R5's placement, =
   数据 R13's measured (220, 146)), and the large title together with everything under it is pushed down 60 while refreshing.

   States (the decompiled machine, §0 "状态机"): 0 idle · 1 revealing · 3 refreshing · 4 going away. (2 is the instantaneous trigger step; 5 / 6 are
   the bounce-back edge cases, not modelled — a finger returning during 4 is treated as a new pull.)

   Left out (unread in the source, refresh-native-formula.md §6): the rubber-band mapping of the pull (§6.3 — the finger's distance is used), the
   concealing mask when the content scrolls over the control (§6.5), the haptic (§6.6).
   Instruments: window.Refresh.__drive({ pull, v, down }) feeds a pull without touch events; Refresh.trace = the frames of state 3 (t from the
   trigger, rot, p, b, the arms' alphas and arm 7's transform) and Refresh.backTrace = the frames of the scroll-back (t, margin), both on the
   driver's own frame clock (accept-refresh.js, A15). */
(function () {
  const ptr = document.getElementById("ptr"), ai = document.getElementById("ptrai"), app = document.body;   // app: the inset host (body.ptr-inset > header margin-top, R68′)
  /* I2 (D72, inventory-plan.md §5): the pushed page (#subpage at rest = body.pushed, nav.js / view.js openPage) is its own scroll view — the pull
     starts at ITS top and the inset goes on ITS body (#subpage.ptr-inset > .pbody, refresh.css); `host` is fixed at the trigger until the inset is gone */
  const pushed = () => (app.classList.contains("pushed") ? document.getElementById("subpage") : null);
  const topOf = () => { const pg = pushed(); return pg ? pg.scrollTop : window.scrollY; };
  let host = app;
  if (!ptr || !ai) return;
  const arms = [...ai.querySelectorAll("i")];
  const H_CTL = 60, ROT_SPUN = 3.1316, TICK_MS = 125, TICK_DEG = 45, GOAWAY_MS = 300, GOAWAY_SCALE = 0.001, SPIN_CAP_S = 4, K_PER_V = 48.333, K_MIN = 5, K_MAX = 150;
  const BLOOM_MS = 50, UNBLOOM_MS = 150, BLOOM_SCALE = 1.2, BLOOM_DY = -2, ARM_CENTRE = 10, SPUN_ALPHA_OFF = 0.08, BACK_MS = 300;   // §11a; ARM_CENTRE: the arm's centre is 10 pt from the ring's centre (inner end 5, outer 15, §10)
  const DEG = 180 / Math.PI;
  /* cubic-bezier(x1, y1, x2, y2) as y(x): Newton from s = x, bisection fallback (the curve is monotone in x) */
  const bezier = (x1, y1, x2, y2) => (x) => {
    if (x <= 0) return 0; if (x >= 1) return 1;
    const X = (s) => 3 * (1 - s) * (1 - s) * s * x1 + 3 * (1 - s) * s * s * x2 + s * s * s, Y = (s) => 3 * (1 - s) * (1 - s) * s * y1 + 3 * (1 - s) * s * s * y2 + s * s * s;
    let s = x;
    for (let i = 0; i < 8; i++) { const d = 3 * (1 - s) * (1 - s) * x1 + 6 * (1 - s) * s * (x2 - x1) + 3 * s * s * (1 - x2); if (Math.abs(d) < 1e-6) break; const e = X(s) - x; if (Math.abs(e) < 1e-7) return Y(s); s -= e / d; }
    if (!(s >= 0 && s <= 1) || Math.abs(X(s) - x) > 1e-5) { let lo = 0, hi = 1; for (let i = 0; i < 40; i++) { s = (lo + hi) / 2; if (X(s) < x) lo = s; else hi = s; } }
    return Y(s);
  };
  const EASE_IN_OUT = bezier(0.42, 0, 0.58, 1);   // UIView curve 0 = kCAMediaTimingFunctionEaseInEaseOut (seg-value-change-content.md §5b)
  const H = () => (window.visualViewport ? window.visualViewport.height : innerHeight);
  const maxSnap = (titleH = 0) => (titleH + 100) * 1.125 * Math.max(H(), 372) / 568;
  const snapH = () => Math.max(0, Math.min(Math.round(H() / 2), maxSnap()));
  const armAlpha = (i, show) => Math.max(0, Math.min(1, 1 + i * (show - 1))) * show;
  const spunAlpha = (i, p) => Math.max(0, Math.min(1, (1 - p) + i * SPUN_ALPHA_OFF * p));   // instanceColor α 1 → 0 and instanceAlphaOffset 0 → .08 along the spring's progress p
  const backProgress = (f) => Math.pow(Math.sin(Math.PI / 2 * Math.max(0, Math.min(1, f))), 2);   // UIAnimation curve 0 (tabscroll/README §2b B)

  let state = 0, pull = 0, rot = 0, raf = 0, spin = null, spinT0 = 0, tickT0 = 0, tickBase = 0, goT0 = 0, goRot0 = 0, y0 = null, lastY = 0, lastT = 0, vel = 0, refreshing = null;
  let touching = false, insetWant = false, insetOn = false, back = null, bloomT0 = 0, bloomB = 0, bloomOn = false, trace = [], backTrace = [];
  /* each tab is its own scroll view (UITabBarController, view.js selectTab: every tab keeps its own scroll position), so the control and its inset
     belong to the tab the pull started on (tabOf): away from it the inset comes off at once — in the frame of the tab swap — and the control is
     hidden; back on it while still refreshing, the inset goes back on. Before (数据 09-24, inspector timeline out/tl2-tl.json, tools/数据-流畅度): the
     refresh ended on the tab switched to and its 300 ms scroll-back re-laid the whole page every frame there — 切到终末地 after 下拉刷新, 5–6 frames of 31–84 ms */
  let tabOf = null; const tabNow = () => (typeof curTab === "string" ? curTab : null);
  const setArms = (show) => { arms.forEach((a, i) => { a.style.opacity = armAlpha(i, show).toFixed(3); }); ptr.style.opacity = show > 0 ? "1" : "0"; };
  const setXf = (deg, scale) => { ai.style.transform = `rotate(${deg.toFixed(2)}deg)` + (scale != null && scale !== 1 ? ` scale(${scale.toFixed(4)})` : ""); };
  const setState = (s) => { if (s === state) return; state = s; ptr.dataset.state = String(s); ptr.classList.toggle("refreshing", s === 3); };
  /* the bloom, b ∈ [0, 1]: each arm keeps its instance rotation (the stylesheet's rotate(i·45°)) and gets the seed transform before it — scale
     1 + .2b about the arm's own centre (10 pt from the ring's centre), then 2b pt outward */
  const setBloom = (b) => {
    bloomB = b;
    if (b <= 0) { if (bloomOn) { arms.forEach((a) => { a.style.transform = ""; }); bloomOn = false; } return; }
    bloomOn = true;
    const s = (1 + (BLOOM_SCALE - 1) * b).toFixed(4), dy = (BLOOM_DY * b - ARM_CENTRE).toFixed(3);
    arms.forEach((a, i) => { a.style.transform = `rotate(${i * TICK_DEG}deg) translateY(${dy}px) scale(${s}) translateY(${ARM_CENTRE}px)`; });
  };
  /* the inset (body.ptr-inset > header margin-top: the large title and the list go down together, §12) — applied / removed only with the finger up (see the header) */
  const insetApply = () => { if (insetOn || !app) return; insetOn = true; back = null; host = pushed() || app; host.classList.add("ptr-inset"); host.style.setProperty("--ptr-inset", H_CTL + "px"); };
  const insetClear = () => { if (!app) return; host.classList.remove("ptr-inset"); host.style.removeProperty("--ptr-inset"); host = app; back = null; };
  const insetRemove = (animated, now) => {
    if (!insetOn) return; insetOn = false; if (!app) return;
    if (!animated) { insetClear(); return; }
    /* _removeRefreshInset: keeps the content where it is (the offset stays) — here scrollY takes up to 60 of the change at once; what is left (the part
       within the inset) scrolls back over BACK_MS with progress sin²(π/2 · f) */
    const s = (host === app ? window.scrollY : host.scrollTop) || 0, keep = Math.max(0, Math.min(H_CTL, s));
    if (keep > 0) { if (host === app) window.scrollTo(0, s - keep); else host.scrollTop = s - keep; }
    const from = H_CTL - keep;
    if (from <= 0) { insetClear(); return; }
    back = { t0: now, from }; backTrace = []; host.style.setProperty("--ptr-inset", from + "px"); ensureLoop();
  };
  const insetSync = (now) => { if (touching) return; if (insetWant && !insetOn) insetApply(); else if (!insetWant && insetOn) insetRemove(false, now); };   // at the release: pending changes go in without animation (the browser's bounce is the motion)
  const ensureLoop = () => { if (!raf) raf = requestAnimationFrame(frame); };
  const reset = () => { cancelAnimationFrame(raf); raf = 0; spin = null; rot = 0; pull = 0; setBloom(0); setArms(0); setXf(0); ai.style.opacity = ""; insetWant = false; insetOn = false; insetClear(); setState(0); tabOf = null; ptr.style.visibility = ""; };

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
  /* state 3: the spin spring (rotation → 3.1316 rad, ζ 1, ω = √k, k from the pull velocity) carrying the arms' alphas to the spun table, the
     bloom (.05 s out, .15 s back), the inset 60, then the 125 ms / 45° tick */
  const trigger = () => {
    setState(3); ptr.style.opacity = "1";
    const k = Math.max(K_MIN, Math.min(K_MAX, Math.abs(vel) * K_PER_V)), w = Math.sqrt(k);
    spin = { s: { x: rot, v: 0 }, from: rot, target: rot + ROT_SPUN * DEG, resp: 2 * Math.PI / w, k }; spinT0 = performance.now(); bloomT0 = spinT0; tickT0 = 0; frame.prev = spinT0;   // the first step integrates from the trigger, not from a stale frame
    trace = []; Refresh.lastK = k;
    arms.forEach((a) => { a.style.opacity = "1"; });   // _cleanUpAfterRevealing: the reveal's end state (all arms lit) is where the spring starts
    insetWant = true; tabOf = pushed() ? null : tabNow(); insetSync(spinT0);
    cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
    refreshing = Refresh.onRefresh ? Refresh.onRefresh() : typeof window.pullRefresh === "function" ? window.pullRefresh() : (typeof window.ping === "function" ? window.ping() : Promise.resolve());   // the page's refresh (view.js pullRefresh: the 库存 page's Stockpile.load(true) or live.js ping); accept swaps its own
    Promise.resolve(refreshing).catch(() => {}).finally(() => { if (state === 3) endRefreshing(); });
  };
  const frame = (now) => {
    raf = 0;
    if (tabOf !== null && host === app) { const away = tabNow() !== tabOf; ptr.style.visibility = away ? "hidden" : "";
      if (away && (insetOn || back)) { insetOn = false; insetClear(); } else if (!away && state === 3 && insetWant && !insetOn && !touching) insetApply(); }
    const dt = Math.min(0.05, Math.max(0, (now - (frame.prev || now)) / 1000));
    if (state === 3) {
      const tb = now - bloomT0;
      if (tb < BLOOM_MS + UNBLOOM_MS) setBloom(tb < BLOOM_MS ? tb / BLOOM_MS : 1 - EASE_IN_OUT((tb - BLOOM_MS) / UNBLOOM_MS)); else if (bloomOn) setBloom(0);
      let p = 1;
      if (spin) {
        const t = (now - spinT0) / 1000;
        if (window.Motion) window.Motion.spring(spin.s, spin.target, [1, spin.resp], dt); else spin.s.x = spin.target;
        rot = spin.s.x; p = Math.max(0, Math.min(1, (rot - spin.from) / (spin.target - spin.from)));
        if (t >= SPIN_CAP_S || Math.abs(spin.s.x - spin.target) < 0.05) { rot = spin.target; spin = null; tickT0 = now; tickBase = rot; p = 1; }
      } else {
        rot = tickBase + Math.floor((now - tickT0) / TICK_MS) * TICK_DEG;   // discrete: a jump every 125 ms, no interpolation
      }
      setXf(rot);
      arms.forEach((a, i) => { a.style.opacity = spunAlpha(i, p).toFixed(3); });
      if (trace.length < 600) trace.push({ t: (now - spinT0) / 1000, rot, p, b: bloomB, a: arms.map((a) => parseFloat(a.style.opacity)), xf: arms[7] ? arms[7].style.transform : "" });
    } else if (state === 4) {
      const u = Math.min(1, (now - goT0) / GOAWAY_MS), e = EASE_IN_OUT(u);
      ai.style.opacity = String(1 - e); setXf(goRot0 + ROT_SPUN * DEG * e, 1 - (1 - GOAWAY_SCALE) * e);
      if (u >= 1) { rot = 0; pull = 0; setBloom(0); setArms(0); setXf(0); ai.style.opacity = ""; setState(0); tabOf = null; ptr.style.visibility = ""; }
    }
    if (back) {
      const f = Math.min(1, (now - back.t0) / BACK_MS), m = back.from * (1 - backProgress(f));
      if (app) host.style.setProperty("--ptr-inset", m.toFixed(3) + "px");
      if (backTrace.length < 200) backTrace.push({ t: (now - back.t0) / 1000, m });
      if (f >= 1) insetClear();
    }
    frame.prev = now;
    if (state === 3 || state === 4 || back) raf = requestAnimationFrame(frame);
  };
  const endRefreshing = () => {
    if (state !== 3) return;
    setState(4); spin = null; setBloom(0); goT0 = performance.now(); goRot0 = rot; frame.prev = goT0;
    insetWant = false; if (!touching) insetRemove(true, goT0);   // finger down: the inset goes at the release, the scroll view's own bounce lands at the new rest
    cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
  };

  /* touch: the pull is the finger's travel below its start while the page is at the top */
  /* I2: a refresh that re-renders the content (the 库存 page's Stockpile.load paints its loading row at once) detaches the node under the finger;
     the rest of that touch (moves, the end) is still dispatched to that node but no longer bubbles to window — the release was lost (probe
     2026-09-23: 15 of 21 moves and no touchend reached window, the inset never went on). So move / end are also heard on the touch's own target;
     `seen` keeps an event that does bubble from being handled twice. */
  const seen = new WeakSet(); let tgt = null;
  const listen = (el, on) => { if (!el || !el.addEventListener) return; const f = on ? "addEventListener" : "removeEventListener"; el[f]("touchmove", onMove, { passive: true }); el[f]("touchend", onEnd, { passive: true }); el[f]("touchcancel", onEnd, { passive: true }); };
  addEventListener("touchstart", (e) => { if (e.touches.length === 1 && e.target !== tgt) { listen(tgt, false); tgt = e.target; listen(tgt, true); } touching = true; if (e.touches.length !== 1) { y0 = null; return; } y0 = !app.classList.contains("nav-live") && topOf() <= 0 ? e.touches[0].clientY : null; lastY = e.touches[0].clientY; lastT = e.timeStamp; vel = 0; }, { passive: true });
  function onMove(e) {
    if (seen.has(e)) return; seen.add(e);
    if (y0 === null || state === 3 || state === 4) return;
    const y = e.touches[0].clientY, dt = (e.timeStamp - lastT) / 1000; if (dt > 0) vel = (y - lastY) / dt; lastY = y; lastT = e.timeStamp;
    reveal(y - y0, true);
  }
  addEventListener("touchmove", onMove, { passive: true });
  const up = () => { touching = false; insetSync(performance.now()); if (y0 === null) return; y0 = null; if (state === 1) { setState(0); setArms(0); } };   // released before f reached 1: nothing happens (the trigger needs the finger)
  function onEnd(e) { if (seen.has(e)) return; seen.add(e); if (e.touches && e.touches.length) return; up(); }
  addEventListener("touchend", onEnd, { passive: true }); addEventListener("touchcancel", onEnd, { passive: true });

  const Refresh = {
    maxSnap, snapH, armAlpha, spunAlpha, backProgress, easeInOut: EASE_IN_OUT, get state() { return state; }, get pull() { return pull; }, get rotation() { return rot; }, get spin() { return spin; },
    get insetOn() { return insetOn; }, get back() { return back; }, get trace() { return trace; }, get backTrace() { return backTrace; },
    endRefreshing, reset, lastK: null, onRefresh: null,   // onRefresh: () => Promise — the refresh to wait for (default live.js ping())
    /* instrument: __drive({ pull, v, down }) — a pull of `pull` pt with velocity v pt/s and the finger down / up, no touch events */
    __drive(o) { if (o.v != null) vel = o.v; if (o.down === false) { up(); return state; } touching = true; y0 = 0; reveal(o.pull || 0, true); return state; }
  };
  window.Refresh = Refresh;
})();
