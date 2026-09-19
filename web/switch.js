/* switch.js — UISwitch (Solarium UISwitchModernVisualElement) on .sw, BOARD.md #13: the B13 state machine of the controls branch
   (3008bf5) re-split into its own file on the night base; into night for the morning look, NOT into the release (用户 23:5x).
   Basis: remote-ref/switch-native-formula.md §0–§4 §9 (iOS 27.0 UIKitCore decompile), dispatch-B13-switch.md; the numbers are read
   originals (fallbacks here = the same values; the --ios-* tokens of the controls branch are listed in BOARD/status-老网页.md for 验收).
   Hook: view.js installNative's .sw pointerdown handler yields on its first line when window.Switch exists (A7 guard). */
(() => {
  "use strict";
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
  /* the spring step is motion.js's (ω = 2π / response, ζ): each state keeps {x, v, target, resp, z} */
  const spring = (s, dt) => Motion.spring(s, s.target, [s.z == null ? 1 : s.z, s.resp], dt);
  const swWrite = (sw, st) => {
    const sx = 1 + st.lift.x * (st.liftSX - 1), sy = 1 + st.lift.x * (st.liftSY - 1);
    sw.style.setProperty("--kx", (st.pos.x - SW_BASE[0]).toFixed(3) + "px");
    sw.style.setProperty("--ksx", sx.toFixed(4)); sw.style.setProperty("--ksy", sy.toFixed(4));
    sw.style.setProperty("--lift", Math.max(0, Math.min(1, st.lift.x)).toFixed(4));
  };
  const swRun = (sw, st) => {
    if (st.raf) return;
    st.last = performance.now();
    const tick = (now) => {
      const dt = Math.min(1, Math.max(0, (now - st.last) / 1000)); st.last = now;   // closed-form: a slow frame gets its whole elapsed time
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
    if (!st) st = sw._sw = { pos: { x: SW_BASE[initialOn ? 1 : 0], v: 0, target: SW_BASE[initialOn ? 1 : 0], resp: .3 }, lift: { x: 0, v: 0, target: 0, resp: .25 }, raf: 0, last: 0, hangT: 0, pressT: 0, held: false };
    let on = initialOn, pending = "tap", t = 0, lastX = e.clientX, liftAt = 0;
    const target = () => {
      const raw = SW_BASE[on ? 1 : 0] + t, lo = SW_BASE[0], hi = SW_BASE[1];
      if (raw > hi) return hi + (reduceMotion.matches ? 0 : rubber(raw - hi, T.rbLimit, T.rbSlope));
      if (raw < lo) return lo - (reduceMotion.matches ? 0 : rubber(lo - raw, T.rbLimit, T.rbSlope));
      return raw;
    };
    const retarget = () => { st.pos.target = target(); swRun(sw, st); };
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
          st.hangT = setTimeout(() => { st.lift.target = 0; st.lift.resp = T.unliftResp; st.lift.z = T.unliftZeta; swRun(sw, st); }, wait);   // spec.unLiftSpring ζ .7 / .5
        }
        if (on !== initialOn) input.dispatchEvent(new Event("change", { bubbles: true }));
      },
    })) { delete sw.dataset.pe; return; }
    if (!sw.classList.contains("drive")) { st.pos.x = st.pos.target = SW_BASE[initialOn ? 1 : 0]; st.pos.v = 0; }   // a rested switch starts at its rest position (a programmatic change may have moved it)
    st.pos.resp = T.posResp; st.liftSX = T.liftW / T.knobW; st.liftSY = T.liftH / T.knobH;
    clearTimeout(st.hangT); clearTimeout(st.pressT); st.held = true;
    swWrite(sw, st); sw.classList.add("drive");
    st.pressT = setTimeout(() => {   // longPress began at +.01 s: pressed
      sw.classList.add("pressed");
      if (!reduceMotion.matches) { liftAt = performance.now(); st.lift.target = 1; st.lift.resp = T.liftResp; st.lift.z = T.liftZeta; }   // spec.liftSpring (small variant: ζ .625 / .27 — overshoots 8 %: 58 → 59.7 at +173 ms)
      retarget();
    }, T.press);
  });
  window.Switch = { version: "B13 3008bf5 → night", SW_BASE };
})();
