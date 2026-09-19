/* controls.js — the press states of two controls, each a state machine on the page's pointer events (loaded after view.js: it uses
   view.js's press() / touchMs() / touchPx() helpers). Every number is a probe or decompile original recorded in remote-ref (the source is
   named where the number is used); nothing here is sampled or guessed. The colours / curves live in controls.css + tokens.css.
   B14 list-row press — remote-ref/cell-native.md §0 (iOS 27.0 probe, deep-hook diff), state-tables/cell.md, dispatch-B14-cell.md.
   B13 switch — switch-native-formula.md §0–§4 (iOS 27.0 UIKitCore decompile), dispatch-B13-switch.md; tokens.css "B13 UISwitch". */
(() => {
  "use strict";

  /* ---------------- B14: UITableViewCell press on .row.nav / .sheet .row.check / .acts button (the blue / red action rows) ----------------
     Timeline (cell-native.md §0, state-tables/cell.md):
       down          nothing changes (UIScrollView delaysContentTouches: 150 ms — --ios-touch-highlight-delay)
       down +150 ms  the fill switches INSTANTLY to the highlight colour (no CAAnimation) and the separator goes to opacity 0 → class .hl
       up            the fade highlight → resting starts on the next frame (+4…17 ms): .5 s cubic-bezier(.42,0,.58,1) → class .hl-out
                     (UIView animateWithDuration:0.5 options:0, curve easeInOut, from deselectRow(animated:)); the selection (our click) fires
                     one frame after that — once the fade's first frame is on screen — because the page's actions block (confirm()) or
                     replace the frame (openPage), which the device check (数据 b14-cell-8bf3bcd.md) saw swallowing the highlight
       short tap     (up before +150 ms) the highlight still shows one frame at +150 (up +16…18) and the fade starts at that moment; the click
                     follows the same way (highlight frame painted → fade frame painted → click), never before the highlight was on screen
       cancel        scrolling ≥ 12 pt vertically (threshold 10 = --ios-touch-scroll-threshold) or the finger 15 pt outside the card's edge:
                     the highlight goes off INSTANTLY (.hl-cut kills the base transition of .acts button for that frame) and the up selects
                     nothing — UITableView touchesCancelled: (0x1c4b31830) / touchesMoved: (0x1c4b306a8) un-highlight through
                     _highlightRowAtIndexPath:{none} animated:__UIShouldAnimateDefaultCellHighlightAndSelection, and that function
                     (0x1c3f1c170) returns NO for every idiom but Vision (6) — old page session, iOS 27.0 UIKitCore
       a fast swipe (20 pt within 40 ms) is cancelled before the 150 ms fire, so it never highlights (C9)
     Horizontal movement inside the card (8 / 15 / 100 pt) keeps the press and still selects (C7 C10) — a browser would not deliver its own
     click after such a drag, so the click is ours (fired at the up) and the browser's own click for the same touch is swallowed, the way
     view.js installPressables does it for UIButtons. The alert's action buttons keep installPressables (dialog .acts button). */
  const ROW_SEL = ".row.nav, .sheet .row.check, .acts button";
  const ROW_MS = () => touchMs("--ios-touch-highlight-delay", 150);
  const ROW_FADE_MS = () => touchMs("--ios-motion-row-release-duration", 500);
  const ROW_SCROLL_PT = () => touchPx("--ios-touch-scroll-threshold", 10);
  const ROW_EDGE_PT = 15;   // state-tables/cell.md C11: 15 pt past the card's edge = cancel (no token: the probe's own step, not a UIKit constant read)
  let ghost = false, synthetic = false;   // the browser's own click after our up / the click we fire
  function fadeOut(el) {   // .hl → .hl-out in one style change, so the transition runs highlight → resting
    el.classList.add("hl-out"); el.classList.remove("hl");
    let done = false;
    const end = () => { if (done) return; done = true; el.removeEventListener("transitionend", onEnd); el.classList.remove("hl-out"); };
    const onEnd = (ev) => { if (ev.target === el && ev.propertyName === "background-color") end(); };
    el.addEventListener("transitionend", onEnd);
    setTimeout(end, ROW_FADE_MS() + 100);   // a fallback: the transition may be skipped (display change, reduced motion)
  }
  document.addEventListener("pointerdown", (e) => {
    const el = e.target.closest && e.target.closest(ROW_SEL); if (!el || el.disabled || el.closest("dialog")) return;
    if (!e.isPrimary || el.dataset.rp) return;
    const card = el.closest(".group, .plist, .card") || el.parentElement, cr = card.getBoundingClientRect();
    const x0 = e.clientX, y0 = e.clientY, T = ROW_SCROLL_PT();
    let lit = false, over = false, released = false, timer = 0;
    const select = () => { synthetic = true; try { el.click(); } finally { synthetic = false; } };
    /* the release sequence from a lit row, each step AFTER A PAINT: rAF callbacks run before the frame's paint and a setTimeout(0)
       registered inside one runs after it — so "rAF then setTimeout 0" = the next painted frame. Frame 1 paints the fade's start
       (.hl → .hl-out), then the selection runs: an action that blocks the main thread (confirm()) or replaces the content (openPage)
       can no longer swallow the highlight / the fade's first frame (数据 fd0731b device check: two rAFs alone still blocked before a paint) */
    const afterPaint = (fn) => requestAnimationFrame(() => setTimeout(fn, 0));
    const release = () => requestAnimationFrame(() => { fadeOut(el); setTimeout(select, 0); });
    const light = () => {   // +150 ms: the highlight, instant; if the finger is already up, one painted frame of it, then the release
      timer = 0; if (over && !released) return; lit = true; el.classList.add("hl"); if (released) afterPaint(release);
    };
    const cancel = () => {   // instant off (no transition even on .acts button, whose rest rule carries one), no select
      if (over) return; over = true; clearTimeout(timer); timer = 0; delete el.dataset.rp;
      if (lit) { lit = false; el.classList.add("hl-cut"); el.classList.remove("hl"); requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("hl-cut"))); }
    };
    if (!press(el, e, {
      move: (ev) => { if (over) return; if (Math.abs(ev.clientY - y0) > T || ev.clientX < cr.left - ROW_EDGE_PT || ev.clientX > cr.right + ROW_EDGE_PT) cancel(); },
      end: (ev, cancelled) => {
        if (cancelled) { cancel(); return; }
        if (over) return;
        over = true; released = true; delete el.dataset.rp;
        ghost = true; setTimeout(() => { ghost = false; }, 0);   // the browser's click for this touch (if it comes) arrives before this
        if (lit) release();             // a short tap: the pending 150 ms timer lights the row, then light() runs the same release
      },
    })) return;
    el.dataset.rp = "1";
    timer = setTimeout(light, ROW_MS());
  });
  document.addEventListener("click", (e) => {
    if (synthetic) return;
    if (ghost && e.target.closest && e.target.closest(ROW_SEL)) { ghost = false; e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);

  /* ---------------- B13: UISwitch (Solarium UISwitchModernVisualElement) on .sw ----------------
     Gesture (switch-native-formula.md §2, iOS 27.0 UIKitCore): a UILongPressGestureRecognizer with minimumPressDuration .01 s and a pan with
     no hysteresis. began (+10 ms) = pressed: pending = !on (the tap's preset), the knob's position spring is retargeted (no displacement), the
     lens lifts (37×24 → 58×38.33), the well border grows 2 → 15.5 (CSS, .pressed). Every move: the knob's target = base(on) + translation,
     clamped to [20.5, 42.5] with the excess rubber-banded ±12·(1 − 1/(1 + .55·o/12)) (0x1c414e998–0x1c414e9ec), through the same ζ 1 / .3
     spring continuing from the current value and velocity (_transitionKnobToPressed:on:animated: 0x1c414e084–0x1c414e0b0); |translation| > 25
     toward the other state flips the displayed value at once and zeroes the translation (_updateMovementVectorForPanInitiatedChanges
     0x1c414bba4), after which 25 the other way flips back. ended: the tap's pending value applies only if no pan flip took it over
     (canApplyPendingOnValueForGesture:, 0x1c414c900–0x1c414c938); pressed = 0 → the knob returns to base(on), the lens un-lifts at
     max(up, lift + lensHangTime .22 s) (seg-lens-refraction.md §4.4 timer), valueChanged after the commit if the value differs from the
     initial one. cancelled: nothing more flips. Reduce motion: no lift, no rubber band (0x1c414f4e0, 0x1c414e998).
     Springs: x'' = −ω²(x − target) − 2ζωx', ω = 2π / response, stepped analytically per frame (flex-interaction.md §6): the knob's position
     ζ 1 / .3; the lens's lift ζ .625 / .27 and un-lift ζ .7 / .5 = _UILiquidLensViewSpec.small (switch-native-formula.md §9; tokens). */
  const SW_BASE = [20.5, 42.5];   // knob centre x off / on (_knobPositionAdjusted:… 0x1c414e88c–0x1c414e8a8); translate = centre − 20.5
  const swNum = (name, fallback) => { const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)); return Number.isNaN(v) ? fallback : v; };
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const rubber = (o, limit, slope) => limit * (1 - 1 / (1 + slope * o / limit));
  /* one analytic step of a damped spring x'' = −ω²(x − target) − 2ζωx' from the current value / velocity; ζ = 1: (A + Bt)e^{−ωt} with
     A = x − target, B = v + ωA; ζ < 1: e^{−ζωt}(A cos ω_d t + B sin ω_d t), ω_d = ω√(1 − ζ²), B = (v + ζωA)/ω_d (flex-interaction.md §6) */
  const spring = (s, dt) => {
    const z = s.z == null ? 1 : s.z, w = s.w, A = s.x - s.target;
    if (z >= 1) { const B = s.v + w * A, e = Math.exp(-w * dt); s.x = s.target + (A + B * dt) * e; s.v = (B - w * (A + B * dt)) * e; return; }
    const wd = w * Math.sqrt(1 - z * z), B = (s.v + z * w * A) / wd, e = Math.exp(-z * w * dt), c = Math.cos(wd * dt), sn = Math.sin(wd * dt);
    s.x = s.target + e * (A * c + B * sn); s.v = e * ((-z * w * A + wd * B) * c + (-z * w * B - wd * A) * sn);
  };
  const swWrite = (sw, st) => {
    const sx = 1 + st.lift.x * (st.liftSX - 1), sy = 1 + st.lift.x * (st.liftSY - 1);
    sw.style.setProperty("--kx", (st.pos.x - SW_BASE[0]).toFixed(3) + "px");
    sw.style.setProperty("--ksx", sx.toFixed(4)); sw.style.setProperty("--ksy", sy.toFixed(4));
    sw.style.setProperty("--lift", Math.max(0, Math.min(1, st.lift.x)).toFixed(4));
  };
  /* an event between two frames: bring the springs up to the event's instant first, so a retarget starts from the value at that instant
     and not from the last frame's (the up's knob travel read one frame ahead in the device / headless checks) */
  const swCatchUp = (st) => { if (!st.raf) return; const now = performance.now(), dt = Math.min(.05, Math.max(0, (now - st.last) / 1000)); spring(st.pos, dt); spring(st.lift, dt); st.last = now; };
  const swRun = (sw, st) => {
    if (st.raf) return;
    st.last = performance.now();
    const tick = (now) => {
      const dt = Math.min(.05, Math.max(0, (now - st.last) / 1000)); st.last = now;
      spring(st.pos, dt); spring(st.lift, dt);
      const posDone = Math.abs(st.pos.x - st.pos.target) < .02 && Math.abs(st.pos.v) < .5, liftDone = Math.abs(st.lift.x - st.lift.target) < .004 && Math.abs(st.lift.v) < .04;   // .004 of the lift = .002 of scale (< ⅒ px on the 58-pt knob)
      if (posDone) { st.pos.x = st.pos.target; st.pos.v = 0; }
      if (liftDone) { st.lift.x = st.lift.target; st.lift.v = 0; }
      swWrite(sw, st);
      if (posDone && liftDone && !st.held) { st.raf = 0; sw.classList.remove("drive"); return; }   // settled and released: the rest rules take over (same values)
      st.raf = requestAnimationFrame(tick);
    };
    st.raf = requestAnimationFrame(tick);
  };
  document.addEventListener("pointerdown", (e) => {
    const sw = e.target.closest && e.target.closest(".sw"); if (!sw) return;
    const input = sw.querySelector("input"); if (!input || input.disabled || !e.isPrimary) return;
    e.preventDefault();
    /* the browser's own click after the up would toggle the checkbox a second time (2026-09-15 12:0x on his Android); view.js's capture
       click listener swallows the click that carries dataset.pe */
    sw.dataset.pe = "1";
    const T = { press: touchMs("--ios-touch-switch-press-delay", 10), flip: touchPx("--ios-touch-switch-flip-distance", 25),
                rbLimit: touchPx("--ios-touch-switch-rubber-limit", 12), rbSlope: swNum("--ios-touch-switch-rubber-slope", .55),
                hang: touchMs("--ios-touch-switch-hang", 220), liftW: touchPx("--ios-switch-knob-lift-w", 58), liftH: touchPx("--ios-switch-knob-lift-h", 38.33),
                knobW: touchPx("--ios-switch-knob-w", 37), knobH: touchPx("--ios-switch-knob-h", 24),
                posResp: swNum("--ios-motion-switch-knob-response", .3), liftResp: swNum("--ios-motion-switch-lift-response", .27), liftZeta: swNum("--ios-motion-switch-lift-damping", .625),
                unliftResp: swNum("--ios-motion-switch-unlift-response", .5), unliftZeta: swNum("--ios-motion-switch-unlift-damping", .7) };
    const initialOn = input.checked;
    let st = sw._sw;
    if (!st) st = sw._sw = { pos: { x: SW_BASE[initialOn ? 1 : 0], v: 0, target: SW_BASE[initialOn ? 1 : 0], w: 0 }, lift: { x: 0, v: 0, target: 0, w: 0 }, raf: 0, last: 0, hangT: 0, pressT: 0, held: false };
    let on = initialOn, pending = "tap", t = 0, lastX = e.clientX, liftAt = 0;
    const target = () => {
      const raw = SW_BASE[on ? 1 : 0] + t, lo = SW_BASE[0], hi = SW_BASE[1];
      if (raw > hi) return hi + (reduceMotion.matches ? 0 : rubber(raw - hi, T.rbLimit, T.rbSlope));
      if (raw < lo) return lo - (reduceMotion.matches ? 0 : rubber(lo - raw, T.rbLimit, T.rbSlope));
      return raw;
    };
    const retarget = () => { swCatchUp(st); st.pos.target = target(); swRun(sw, st); };
    const setOn = (v) => { on = v; input.checked = v; };   // interactiveChangeToDisplayedOn: → setOn:animated: — the well's border colour (.18 s) / width follow :checked in CSS
    if (!press(sw, e, {
      move: (ev) => {
        t += ev.clientX - lastX; lastX = ev.clientX;
        if (on ? t < -T.flip : t > T.flip) { setOn(!on); pending = "pan"; t = 0; }
        retarget();
      },
      end: (ev, cancelled) => {
        clearTimeout(st.pressT);
        if (!cancelled && pending === "tap") setOn(!on);
        st.held = false; t = 0; sw.classList.remove("pressed"); retarget();
        if (st.lift.target === 1) {
          const wait = Math.max(0, liftAt + T.hang - performance.now());
          st.hangT = setTimeout(() => { swCatchUp(st); st.lift.target = 0; st.lift.w = 2 * Math.PI / T.unliftResp; st.lift.z = T.unliftZeta; swRun(sw, st); }, wait);   // spec.unLiftSpring ζ .7 / .5
        }
        if (on !== initialOn) input.dispatchEvent(new Event("change", { bubbles: true }));
      },
    })) { delete sw.dataset.pe; return; }
    if (!sw.classList.contains("drive")) { st.pos.x = st.pos.target = SW_BASE[initialOn ? 1 : 0]; st.pos.v = 0; }   // a rested switch starts at its rest position (a programmatic change may have moved it)
    st.pos.w = 2 * Math.PI / T.posResp; st.liftSX = T.liftW / T.knobW; st.liftSY = T.liftH / T.knobH;
    clearTimeout(st.hangT); clearTimeout(st.pressT); st.held = true;
    swWrite(sw, st); sw.classList.add("drive");
    st.pressT = setTimeout(() => {   // longPress began at +.01 s: pressed
      sw.classList.add("pressed");
      if (!reduceMotion.matches) { swCatchUp(st); liftAt = performance.now(); st.lift.target = 1; st.lift.w = 2 * Math.PI / T.liftResp; st.lift.z = T.liftZeta; }   // spec.liftSpring (small variant: ζ .625 / .27 — overshoots 8 %: 58 → 59.7 at +173 ms)
      retarget();
    }, T.press);
  });
})();
