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
     initial one. cancelled: nothing more flips. Reduce motion (the switch itself asks _AXSReduceMotionEnabled, the lens does not): the lens is
     never lifted (_transitionKnobToPressed:on:animated: 0x1c414e6c4 → setLifted:NO 0x1c414e760), the pressed knob stays 37 × 24
     (_knobBoundsPressed: 0x1c414f4ec–0x1c414f510) and the rubber band is skipped (_knobPositionAdjusted:… 0x1c414e910, 0x1c414e934 / 0x1c414e9b0).
     Springs: x'' = −ω²(x − target) − 2ζωx', ω = 2π / response, stepped analytically per frame (flex-interaction.md §6): the knob's position
     ζ 1 / .3; the lens's lift ζ .625 / .27 and un-lift ζ .7 / .5 = _UILiquidLensViewSpec.small (switch-native-formula.md §9; tokens).
     R70′ — the knob's flex stretch (switch-native-formula.md §12, R70 decompiled; §12a, R70″ probe frames): _UIFlexInteraction on the knob lens is
     switched to activation mode 3 (always active) by setLifted:YES (0x1c54c8244–0x1c54c8258 — the pressed transition at +10 ms) and back to 1
     (deactivate) at setLifted:NO (0x1c54c9a24 — the un-lift after the hang timer); flexSources = 2: the stretch is driven by the knob's OWN presented
     motion through the velocity integrator (flex-interaction.md §1: 5 samples, EMA .3, hysteresis .05 s, directionless acceleration), not by the
     finger's translation; spec = liquidLensWithSize:(58 × 38.33) → t = (38.33 − 37) / 33 = .0403 interpolated smallLoupe → loupe (flex-interaction.md
     §7.4, view.js flexSpec — the same helper as the segmented lens): ζ .5777 / .4463, pts 13.63, min .9 / max 1.1, N 2020. (§9's "N 9697" interpolated
     from the small body's 10000: replaying the R70″ probe frames through this chain — scratchpad r70_replay.py, written into switch-native-formula.md
     §12b — gives peak sX 1.0095 / 1.0270 and drift .28 / .78 against the probe's 1.0097 / 1.0280 and .29 / .83 with N 2020, but 1.002 / 1.006 with 9697:
     the §7.4 interpolation is the one the lens runs.) Targets per updateFlex (§3: m = a / N, per-axis range lo / hi, hard clamp [.9, 1.1]) on the lifted
     bounds; the three floats on the spec spring; presented knob = lift scale × (sX, sY) and translated by sX·drift (the same composition as the
     tab lens, tab-lens-motion.md §6.4). §12a frames (slow / fast drag): peak sX 1.0097 / 1.028 with sX·sY ≈ 1, tx +.29 / +.83, the reverse stretch
     while decelerating and during the drop, back to 1 ≈ .25–.35 s after the motion stops. Unread: the interaction pulse (§3, four parameters).
     The well container clips only the track content (§12: _switchWellContainerView clipsToBounds in dynamic mode; the knob lens is a sibling above
     it) — here the track gradient is the span's background (clipped by its own rounded box) and the knob ::after is never clipped (no overflow rule). */
  const SW_BASE = [20.5, 42.5];   // knob centre x off / on (_knobPositionAdjusted:… 0x1c414e88c–0x1c414e8a8); translate = centre − 20.5
  const FLEX_OK = typeof flexIntegrator === "function" && typeof flexTargets === "function" && typeof springStep === "function";   // view.js's B5 chain (globals of a classic script)
  const swFlexSpec = (W, H) => (typeof flexSpec === "function" ? flexSpec(W, H) : { pts: 13.63, min: .9, max: 1.1, N: 2020, zeta: .5777, resp: .4463, tzeta: .5737, tresp: .4463 });   // liquidLensWithSize:(58 × 38.33): the smallLoupe → loupe interpolation at t .0403 (flex-interaction.md §7.4; view.js flexSpec / FLEX_VARIANT are the read constants)
  const swFlexNew = (W, H) => ({ vi: flexIntegrator(), sx: { x: 1, v: 0 }, sy: { x: 1, v: 0 }, dx: { x: 0, v: 0 }, out: { sx: 1, sy: 1, dx: 0 }, active: false, spec: swFlexSpec(W, H), tg: null, trace: [] });
  const swFlexRest = (fl) => !fl || (Math.abs(fl.out.sx - 1) < .002 && Math.abs(fl.out.sy - 1) < .002 && Math.abs(fl.out.dx) < .05);
  /* one frame of the flex (R70′): active → the knob's presented centre (position + sX·drift) into the integrator and updateFlex's targets on the lifted bounds; inactive →
     the targets are identity and the floats settle on the same spring (the trace of §12a shows the reverse stretch decaying through the drop) */
  const swFlexStep = (st, now, dt) => {
    const fl = st.flex; if (!fl || !(dt > 0)) return;
    let tg = { sX: 1, sY: 1, drift: 0 };
    if (fl.active) { fl.vi.add(st.pos.x + fl.out.sx * fl.out.dx, now / 1000); tg = flexTargets(fl.spec, st.liftW, st.liftH, fl.vi.acceleration, fl.vi.velocity); }
    const sp = [fl.spec.zeta, fl.spec.resp];
    springStep(fl.sx, tg.sX, sp, dt); springStep(fl.sy, tg.sY, sp, dt); springStep(fl.dx, tg.drift, sp, dt);
    fl.out = { sx: fl.sx.x, sy: fl.sy.x, dx: fl.dx.x }; fl.tg = tg;
    if (fl.trace.length < 600) fl.trace.push({ t: now, dt, active: fl.active, sx: fl.out.sx, sy: fl.out.sy, dx: fl.out.dx, vsx: fl.sx.v, vsy: fl.sy.v, vdx: fl.dx.v, tSx: tg.sX, tSy: tg.sY, tDx: tg.drift, accel: fl.active ? fl.vi.acceleration : 0, vel: fl.active ? fl.vi.velocity : 0, pos: st.pos.x });
  };
  const swNum = (name, fallback) => { const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)); return Number.isNaN(v) ? fallback : v; };
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const rubber = (o, limit, slope) => limit * (1 - 1 / (1 + slope * o / limit));
  /* the spring step is motion.js's (ω = 2π / response, ζ): each state keeps {x, v, target, resp, z} */
  const spring = (s, dt) => { s.el = (s.el || 0) + dt; return Motion.spring(s, s.target, [s.z == null ? 1 : s.z, s.resp], dt); };   // s.el = the spring's own time since its last retarget (the checks compare at it)
  /* a retarget while the driver runs: first bring both springs up to this moment with their old targets (the driver's last tick is a frame
     timestamp, up to a frame before the event — without this the new target got that pre-event time credited: the knob ran ≈ 1 frame
     ahead of the up, 15.4 pt at +101 ms for 13.8), then the new target starts from now. Every retarget goes through here. */
  const swSync = (st) => {
    if (!st.raf) return;
    const now = performance.now(), dt = Math.min(1, Math.max(0, (now - st.last) / 1000));
    if (dt > 0) { spring(st.pos, dt); spring(st.lift, dt); st.last = now; }
  };
  const swAim = (s, target, resp, z) => { s.target = target; if (resp != null) s.resp = resp; if (z != null) s.z = z; s.el = 0; };
  const swWrite = (sw, st) => {
    const fl = st.flex, fsx = fl ? fl.out.sx : 1, fsy = fl ? fl.out.sy : 1, fdx = fl ? fl.out.sx * fl.out.dx : 0;   // R70′: the flex on top of the lift (scale × scale; the drift in the scaled coordinates)
    const sx = (1 + st.lift.x * (st.liftSX - 1)) * fsx, sy = (1 + st.lift.x * (st.liftSY - 1)) * fsy;
    sw.style.setProperty("--kx", (st.pos.x - SW_BASE[0]).toFixed(3) + "px"); sw.style.setProperty("--kdx", fdx.toFixed(3) + "px");
    sw.style.setProperty("--ksx", sx.toFixed(4)); sw.style.setProperty("--ksy", sy.toFixed(4));
    st.written = { ksx: +sx.toFixed(4), ksy: +sy.toFixed(4), kdx: +fdx.toFixed(3), kx: +(st.pos.x - SW_BASE[0]).toFixed(3), lift: st.lift.x, sx: fsx, sy: fsy, dx: fl ? fl.out.dx : 0 };   // the driver's last WRITE (accept A15: swSync steps the springs between frames without writing — the state and the style differ until the next tick)
    sw.style.setProperty("--lift", Math.max(0, Math.min(1, st.lift.x)).toFixed(4));
  };
  const swRun = (sw, st) => {
    if (st.raf) return;
    st.last = performance.now();
    const tick = (now) => {
      const dt = Math.min(1, Math.max(0, (now - st.last) / 1000)); if (now > st.last) st.last = now;   // closed-form: a slow frame gets its whole elapsed time; a frame stamped before the last sync adds nothing and does not move the clock back
      spring(st.pos, dt); spring(st.lift, dt); swFlexStep(st, now, dt);
      const posDone = Math.abs(st.pos.x - st.pos.target) < .02 && Math.abs(st.pos.v) < .5, liftDone = Math.abs(st.lift.x - st.lift.target) < .004 && Math.abs(st.lift.v) < .04;   // .004 of the lift = .002 of scale (< ⅒ px on the 58-pt knob)
      const flexDone = !st.flex || (!st.flex.active && swFlexRest(st.flex));
      if (posDone) { st.pos.x = st.pos.target; st.pos.v = 0; }
      if (liftDone) { st.lift.x = st.lift.target; st.lift.v = 0; }
      if (flexDone && st.flex) { st.flex.out = { sx: 1, sy: 1, dx: 0 }; st.flex.sx = { x: 1, v: 0 }; st.flex.sy = { x: 1, v: 0 }; st.flex.dx = { x: 0, v: 0 }; }
      swWrite(sw, st);
      if (posDone && liftDone && flexDone && !st.held) { st.raf = 0; sw.classList.remove("drive"); return; }   // settled and released: the rest rules take over (same values)
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
    const retarget = () => { swSync(st); swAim(st.pos, target()); swRun(sw, st); };
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
          st.hangT = setTimeout(() => { swSync(st); swAim(st.lift, 0, T.unliftResp, T.unliftZeta); if (st.flex) st.flex.active = false; swRun(sw, st); }, wait);   // spec.unLiftSpring ζ .7 / .5; R70′: setLifted:NO → the flex deactivates (its floats settle on their spring)
        }
        if (on !== initialOn) input.dispatchEvent(new Event("change", { bubbles: true }));
      },
    })) { delete sw.dataset.pe; return; }
    if (!sw.classList.contains("drive")) { st.pos.x = st.pos.target = SW_BASE[initialOn ? 1 : 0]; st.pos.v = 0; }   // a rested switch starts at its rest position (a programmatic change may have moved it)
    st.pos.resp = T.posResp; st.liftSX = T.liftW / T.knobW; st.liftSY = T.liftH / T.knobH; st.liftW = T.liftW; st.liftH = T.liftH;
    if (FLEX_OK && !st.flex) st.flex = swFlexNew(T.liftW, T.liftH);
    clearTimeout(st.hangT); clearTimeout(st.pressT); st.held = true;
    swWrite(sw, st); sw.classList.add("drive");
    st.pressT = setTimeout(() => {   // longPress began at +.01 s: pressed
      sw.classList.add("pressed");
      swSync(st);
      if (!reduceMotion.matches) { liftAt = performance.now(); swAim(st.lift, 1, T.liftResp, T.liftZeta);   // spec.liftSpring (small variant: ζ .625 / .27 — overshoots 8 %: 58 → 59.7 at +173 ms)
        if (st.flex) { st.flex.active = true; st.flex.vi = flexIntegrator(); st.flex.spec = swFlexSpec(T.liftW, T.liftH); st.flex.trace = []; } }   // R70′: setLifted:YES → activation mode 3 (activateIfPermitted resets the integrator)
      retarget();
    }, T.press);
  });
  window.Switch = { version: "B13 3008bf5 → night", SW_BASE, flexOf: (sw) => (sw && sw._sw && sw._sw.flex) ? { active: sw._sw.flex.active, spec: { ...sw._sw.flex.spec }, out: { ...sw._sw.flex.out }, target: sw._sw.flex.tg, trace: sw._sw.flex.trace, lift: sw._sw.lift.x, liftSX: sw._sw.liftSX, liftSY: sw._sw.liftSY, written: sw._sw.written ? { ...sw._sw.written } : null } : null };   // lift: the UNCLAMPED lift value the scale is built from (the --lift var is clamped 0…1; accept A15)
  /* 界面-串2 ⑤ (09-23, simulator B frame tables BOARD/evidence/界面-串2-开关-新载首按*.json): the knob's first lift after a page load stalled the
     page 107–284 ms — WebKit builds its backdrop-filter pipeline (blur + saturate, switch.css .drive) on first use; the same first press with that
     filter removed ran at 60 fps, and a later press or another switch's first press did not stall (the cost is per page, not per element). The lift
     rose inside the stall, so the first visible lifted frame was already .84 and falling (2号 rec new-5「圆钮不再抬起成玻璃」). One 2 × 2 pt
     element with the same two functions for two frames after load builds it off the gesture path (measured: first press then smooth, max gap 33 ms). */
  const prewarm = () => { if (!document.body) return; const w = document.createElement("div");
    w.style.cssText = "position:fixed;left:0;top:0;width:2px;height:2px;pointer-events:none;z-index:2147483647;-webkit-backdrop-filter:blur(1px) saturate(1.5);backdrop-filter:blur(1px) saturate(1.5)";
    document.body.appendChild(w); requestAnimationFrame(() => requestAnimationFrame(() => { w.remove(); window.Switch.prewarmedAt = performance.now(); })); };
  if (document.readyState === "complete") setTimeout(prewarm, 300); else addEventListener("load", () => setTimeout(prewarm, 300), { once: true });
})();
