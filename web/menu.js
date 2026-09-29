/* menu.js — the value row's pull-down menu: a geometry morph from a square on the button to the panel, in place of the old scale-and-fade
   (BOARD.md #3, night batch: geometry and timing only, no material).
   Basis (read values): menu-motion-formula.md §0 table / §2 / §8b — one spring each for position x / y, width, height (and the corner); the springs
   are the running progress entries, open ζ .75 / .35 and close ζ .8 / .49 (APPEAR / DISMISS below: data springtrace 09-24 00:11 and the R18a frames),
   not the settings' liquidMorph ζ .8 / .3 that LiquidMorphAnimation copies into Parameters (0x1de4106cc–0x1de410734, §8b ①) — the settings'
   liquidMorphShrink ζ .9 / .3 has no reader outside MorphAnimationSettings itself (R19″ / R72′; the old §0 "消失 ζ .9" row is the unwired default); reduce-motion = liquidMorphReduceMotion ζ 1 / .15
   cross-fade (0x1de41065c–0x1de4106c4, R32); no dimming (_hasVisibleBackground NO, the scrim stays transparent); the source is the trigger button's own frame
   (morphPreviewFromAttachmentPoint, anchor (.5, .5)) — measured since as a 17.1667 pt square on the button's centre (SEED below); the corner follows the same spring from the button's corner to
   the menu's (§4.1). menu-card-material.md §1.2 — width 250 (defaultMenuWidth), corner 32 (menuCornerRadius), section insets 10 / 10, item 42
   (the item rules stay index.html's `.menu button`). The panel's placement: top on the button's top, right on the button's right (≥ 8 pt from the edges) — the
   native rest frame (BTN_H below); above the value when there is no room is the page's old rule (view.js openMenu), not read.
   Read since (menu-motion-formula.md §7b, R18b): the panel's items have NO per-item delay (the list view has no stagger path; the cells' state
   update does not touch alpha / transform) — the items sit in the panel from the first frame, as here. §8b ③ (R72′): the intermediate shape
   (§7c) and the .03 s second step are NOT walked on iOS 27.0 — Parameters.useIntermediateShape is 0 on all five AnimationKit and four UIKit
   construction paths, and the milestone builder 0x1de415fd4 / secondStepDelay are read only inside that dead branch — so the morph is the source
   geometry → the target geometry in ONE step on the six liquidMorph springs, which is what runs here (the springs were already straight; the
   "待读" is closed). crossBlurWhenMorphing = 2 (auto, §8b ②): off when the content is match-moved, otherwise a Background witness Bool whose
   property is unread — not wired (noted in Menu.morph.crossBlur); the refraction lens on the morphing shape (lensingSDFLayer) is 不可表达 here;
   contentScale = 1 (§8b ①).
   Springs come from web/motion.js only (BOARD A7, #1). Without Motion this file defines nothing and view.js's old openMenu stays in charge
   (its first line is `if (window.Menu) return Menu.open(anchor, sel);`). */
(function () {
  if (!window.Motion || typeof Motion.spring !== "function") return;
  const APPEAR = [0.75, 0.35], DISMISS = [0.8, 0.49], REDUCE = [1, 0.15], CROSS = [0.75, 0.35], CROSS_OUT = [0.8, 0.49];   // CROSS: G22 the cross-blur progress p (MorphDestination.progress) on Parameters.morphSpring ζ .75 / .35 (NATIVE-GAP G22 driver ③, probe uiprobe-motion-g22spring10-A.json); CROSS_OUT: the dismiss's p, ζ .8 / response .49 (stiffness 164.42, the four destinations one spring — data probe 09-24 00:1x, NATIVE-GAP last rows, tools/uiprobe/g22/)
    // [ζ, response s]. The geometry runs on the SAME springs as the cross-blur progress p (2号 09-24 10:5x): the running entries are one spring for all four
    // destinations — open ζ .75 / .35, close ζ .8 / .49 (data springtrace 09-24 00:11, NATIVE-GAP row 134) — and the native panel's frame follows them, not the
    // settings' liquidMorph ζ .8 / .3: R18a (remote-ref/tools/touch/seg-native-r18a-MagicMorphView-motion.json) panel scale, panel height and button centre per
    // frame agree with ζ .75 / .35 (a check only — the values are the probe's memory read of the running entries above, not a frame fit) with rms .0006 (of .91) / .047 pt (of 82) / .009 pt (ζ .8 / .3 on the same frames: 10–18× worse); the dismiss's panel scale undershoots
    // 1.51 % (ζ .8: 1.52 %) at +.41 s (ζ .8 / .49 peak .408 s). Reduce motion liquidMorphReduceMotion.
  const MORPH = { oneStep: true, useIntermediateShape: 0, secondStepDelay: null, contentScale: 1, crossBlur: { params: 2, meaning: "auto: 0 when source and target share a magicMoveIdentifier, else the item Background's witness Bool (property unread)", read: 1, wired: "appear + dismiss: the menu content (shown layer) opacity p, blur 4(1 − p); the button (hidden layer, its own p = 1 − p on the same spring) opacity 1 − p, blur 4p; the button copy's shrink to a 10 × 10 point (MagicMorphView #1) unread; reduce motion: one destination per layer, no cross-blur (data 00:1x)" } };   // §8b, R19″
  const W = 250, R = 32, GAP = 6, EDGE = 8;
  /* the native start / end shapes (数据 09-24 11:43–11:47, BOARD/菜单-原生无底框按钮形状-数据-0924.md; UIProbe `menurow`, a settings row's
     UIButton.Configuration.plain() pop-up button, raw json ~/Money/styl-work/tools/数据-菜单形状/rowS|rowL-motion.json): the button's frame is
     34.3333 tall (buttonInWindow h, both widths 75.67 / 192.67); MagicMorphView #0 (the panel) starts as a 17.1667 × 17.1667 square on the
     button's centre (first presInWindow (369.4167, 297.4167, 17.1667, 17.1667), centre (378.0, 306.0) vs the button's (378.17, 306.0)) and the
     dismiss (a pick or a tap outside) ends on the same square (last presInWindow 369.5833 / 311.0833, 297.4167, 17.1667); the panel rests with
     its top on the button's top (288.6667 vs 288.8333) and its right edge on the button's right (166 + 250 = 416 = 340.33 + 75.67). The page's
     .menubtn is that control drawn smaller (22 pt tall), so the native frame is placed on its centre: BTN_H / SEED are those raw values. */
  const BTN_H = 34.3333, SEED = 17.1667;
  let cur = null;   // the open menu: { panel, scrim, sel, from, to, s: { left, top, width, height, r, a }, phase: "in" | "out", prev, raf }
  const reduce = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  /* OFF by default (验收 09-30 03:3x): on the user's phone the sessions of v20260930022225 / 022953 (warm-up on) had gestures 0.4–10 s after load with
     frames of 133–656 ms, rs ≈ dur, no script (中继二 BOARD/evidence/中继二-0930-载入长帧/README.md §四); v20260930020337 (no warm-up) 17–66. Until the
     phone records clear it, ?gpuwarm=1 turns it on (the A / B arm). */
  /* the GPU warm-up's state and its teardown (gpuTry / gpuSchedule below the map worker): here, before open() and the pointerdown / hidden listeners that call
     gpuDrop — as consts next to gpuTry they sat in the temporal dead zone for those callers, and a throw anywhere in between at load left every later open on a
     ReferenceError (验收 code-review 09-30 02:2x) */
  const gpu = { state: /[?&]gpuwarm=1\b/.test(location.search) ? "idle" : "off", at: null, ms: null, end: null, tries: 0, yields: 0, theme: null, H: null, to: null, done: new Set(), live: null };
  const gpuDrop = (why) => { const l = gpu.live; if (!l) return; gpu.live = null; cancelAnimationFrame(l.raf); l.panel.remove(); if (l.stroke) l.stroke.remove(); if (l.btn) l.btn.remove();
    gpu.end = performance.now(); gpu.state = why || "aborted"; performance.mark("m-gpuwarm1"); };
  const restRect = (anchor, h) => { const r = anchor.getBoundingClientRect(); const sw = document.documentElement.clientWidth, right = Math.max(EDGE, sw - r.right), left = sw - right - W;   // screen width: innerWidth counts overflow (nav.js W)
    const bt = r.top + r.height / 2 - BTN_H / 2;   // the native button frame's top (see BTN_H); the fallback when the panel does not fit below it is the page's old rule (not read on iOS)
    const top = bt + h <= innerHeight - EDGE ? bt : Math.max(EDGE, bt + BTN_H - h); return { left, top, width: W, height: h }; };   // no room below: the panel's bottom on the button frame's bottom (数据 09-30 r4 low: button 829 + 34.33 = 863.33 = 717.33 + 146; was the page's old rule, top − 6 − h)
  /* the page re-renders on its own clock (a live.js tick, a snapshot arriving) and dressSelects() builds new <select> + .menubtn nodes, so the
     pair the menu was opened from can be detached by the time it closes or an item is chosen. A detached button reads a 0×0 rect at (0, 0):
     the dismiss morph collapsed into the top-left corner, and a choice went to a select no longer on screen (2026-09-23: the dark acceptance
     run, anchor.isConnected false at close — the three 菜单收回 rows). The live pair is found again by the select's id / data-id; every
     select the page builds carries one (view.js: #efboss, #queue, select[data-id]). */
  const livePair = (sel, anchor) => {
    if (sel.isConnected && anchor.isConnected) return { sel, anchor };
    const key = sel.id ? `select#${CSS.escape(sel.id)}` : sel.dataset && sel.dataset.id ? `select[data-id="${CSS.escape(sel.dataset.id)}"]` : null;
    const s2 = key && document.querySelector(key), b2 = s2 && s2.nextElementSibling;
    return s2 && b2 && b2.classList.contains("menubtn") ? { sel: s2, anchor: b2 } : { sel, anchor };
  };
  const anchorRect = (anchor) => { const a = anchor.style, tf = a.transform; if (tf) a.transform = "";   // the button's own frame: its morph transform (btnMorph) taken off for the read
    const r = anchor.getBoundingClientRect(); if (tf) a.transform = tf; return { left: r.left, top: r.top, width: r.width, height: r.height }; };
  /* the button's own MagicMorphView (#1, same probe, rowS / rowL / cap120): its bounds go from the button frame to a height × height square
     (pres (0, 0, 34.3333, 34.3333) / (0, 0, 40, 40)), its scale to .25 (rest presInWindow 8.5833 / 10.0 square) and its centre a quarter of the way
     to the panel's centre (rowS rest centre (356.2, 314.2) = (378.2, 306.0) + .25 · ((291.0, 340.7) − (378.2, 306.0)) within .5 pt; rowL, cap120 alike),
     one step on the geometry spring — here p, which the geometry shares (APPEAR = CROSS, DISMISS = CROSS_OUT). The bounds' shrink is a clip about the
     centre (the square is BTN_H, the native frame, as SEED); q past 1 / below 0 (the spring's overshoot) is carried, as the panel's is */
  const btnMorph = (a, q, m) => { const s = a.style, x = Math.max(0, (m.w - BTN_H) * q / 2);
    s.transform = q === 0 ? "" : `translate(${(m.x * q).toFixed(3)}px, ${(m.y * q).toFixed(3)}px) scale(${(1 - 0.75 * q).toFixed(4)})`; s.clipPath = x > 0 ? `inset(0 ${x.toFixed(3)}px)` : ""; };
  /* the button draws OVER the panel while the menu is up: natively the button's MagicMorphView (#1) is the later sibling of the panel's (#0) in the morph
     container (menu-motion-formula.md §7 ② layer tree), so its image (α 1 − p, blur 4p) is composited above the panel's glass — simulator D 09-24 21:35
     screen recording of UIProbe rowS (2号 tools/2号-菜单量具/0924-白点, nat.mov): on the dismiss the title shows through the shrinking shape from the
     first frames and is sharp over it from +238 ms, the shape's tail never covers it. With the button under the panel (z 8) the page's tail was a white
     17-pt disc over the title for 30 frames (+266 → +784 ms after the lift, Chrome 394×2.75, w1.json). No hits while raised: a tap there is outside the
     menu and goes to the scrim (z 7) */
  const btnRaise = (a) => { const s = a.style; if (s.zIndex === "9") return; s.position = "relative"; s.zIndex = "9"; s.pointerEvents = "none"; };
  const btnClear = (a) => { const s = a.style; s.opacity = s.filter = s.transform = s.clipPath = s.position = s.zIndex = s.pointerEvents = ""; };
  const btnMove = (anchor, rest) => { const r = anchorRect(anchor); return { w: r.width, x: 0.25 * (rest.left + rest.width / 2 - r.left - r.width / 2), y: 0.25 * (rest.top + rest.height / 2 - r.top - r.height / 2) }; };
  const seqSide = (h) => SEED * W / Math.max(W, h || 0);   // the square's side: the W-wide layer starts square (W × W, or W × h when taller) at scale SEED / max(W, h) — 17.17 up to 250 tall, 15.78 on the 272-tall six-row menu (数据 09-30 r4 / xfall, 4 / 4 dismiss ends)
  const seedRect = (anchor, h) => { const r = anchorRect(anchor), q = seqSide(h); return { left: r.left + r.width / 2 - q / 2, top: r.top + r.height / 2 - q / 2, width: q, height: q }; };   // the morph's start / end square (see SEED)
  /* the corner (数据 09-24 15:50–15:52, BOARD/菜单-圆角淡出变宽-数据-0924.md ①): natively a round end — the start / end square's on-screen radius is
     8.58 = 17.2 / 2 (tables 4 / 6), and through the dismiss the MagicMorphView's layer (250 wide, scaled to the frame) springs its own radius 32 → 125
     (= 250 / 2) while the screen shows layer radius × frame width / 250 (table 1: 39.37 × 231.5 / 250 = 36.46 …), so the tail is a circle, radius = the
     short side / 2 within .17 pt, overshoot included (690 ms 13.6 wide, 6.82). The dismiss carries r in those layer units (cur.rl); the open too (④ below).
     The radius never exceeds half the short side: the layer's own clamp, min(layer short side / 2, R) (④ 2 — the stored cornerRadii is h / 2 exactly) */
  const cornerNow = (s) => { const g = shownBox(s), w = g.width, h = g.height, r = cur && cur.rl ? s.r.x * w / W : s.r.x; return Math.max(0, Math.min(r, w / 2, h / 2)); };
  /* the open's layer radius R: two regimes (数据 09-24 rdrv.py over rowS-deep-motion.json; 09-30 rad.py) — the page's first open (the process's
     first): R = 125 − 93p, p the geometry / opacity progress (f圆角 = f高 to 4 places, overshoot included: 29.36 @ 775 ms), never under the clamp,
     so the screen corner falls from the square's half side on p (one native sample on 09-30 held the capsule to +417 ms instead: not changed,
     more first opens to read); every later open: RAD below */
  let opened = 0;   // opens this page load: the first one is the process's first (segment 0)
  /* every later open (数据 09-30 rad.py, BOARD/菜单-positionY-数据-0930.md 圆角节): the screen corner is min(short side / 2, RAD(t)) — the capsule
     until one curve, the same for every menu height (104 / 146 / 188 / 272, 10 native runs: 188 54.49 → 47.31 → 41.43 → 36.91, 146 54.65 → 47.41 →
     41.49 → 36.93 …), comes under it, down to 29.1 and back to 32. RAD is that curve per 1/60 s of the p spring's clock (median of the runs; null
     before any run leaves the capsule). The time it leaves varies ±20 ms between runs of one menu, not tied to p — 采样替代: 已查 r4-first3more /
     rnd0930 deep 段，缺 the layer-radius driver (AnimationKit MagicMorphLayer radii write). Replaces REOPEN_R (two rows, from the crossing p .9238)
     and REOPEN146. Leave-one-run-out: median .19, 90 % 4.1, max 24 pt (was 25–35 max on 4 / 5 / 6 rows) */
  const RAD = [null, null, null, null, null, null, null, 79.79, 75.73, 69.07, 61.55, 54.54, 48.63, 43.66, 38.61, 34.82, 32.19, 30.53, 29.57, 29.2, 29.07, 29.24, 29.55, 29.92, 30.3, 30.67, 31.0, 31.28, 31.51, 31.69, 31.85, 31.96, 32.0, 32.0, 32.0, 32.0, 32.0, 32.0, 32.0, 32.0, 32.0, 32.0, 32.0, 32.0, 32.0];
  const openR = (c) => { const p = c.s.p.x; if (c.first) return W / 2 - 93 * p;
    const half = (W + (c.rest.height - W) * p) / 2, i = Math.max(0, c.t) * 60, k = Math.floor(i);   // half: the layer's half height (the capsule)
    if (k + 1 >= RAD.length) return R;
    const a = RAD[k], b = RAD[k + 1]; if (a == null || b == null) return half;
    if (c.turn == null) c.turn = c.t;   // the first frame off the table's capsule (accept-menu reads it)
    return (a + (b - a) * (i - k)) * W / Math.max(1, c.s.width.x); };   // screen pt → the layer's units (cornerNow scales by width / W and clamps to the short side / 2)
  /* ---- the panel's glass (BOARD R1; material by the read keys only, BOARD A20) ----
     Keys: menu-glass-sdfdump-2026-09-19.md §2 (the glassBackground filter's 70 inputs on the menu's CABackdropLayer, light / dark) and §3 (the
     highlight layer). Formula: alert-native-formula.md §1 (the same glassBackground shader, the alert's keys → uniforms) and keyfill-highlight.md §4
     (the ring shadow). What this layer does, per term:
       BlurRadius 5 → the backdrop (a clone of #app under the panel) through feGaussianBlur σ 20 pt: §1.3 of alert-pipeline-plan — the 5 is in
         samples of the 1/4-resolution capture (5 ÷ .25 = 20 pt); the edge reduction (BlurDistance0/1 −83.5 / −1: r → 0 within 1 pt of the rim) is
         R1's note (not built); since built as the alert's level mix (09-25, levelBlur below: r(d) over BlurDistance0 → 1 → 2, levels 1 / 2 = σ 8.59 / 18.78 pt);
       FaceColorMatrixFillColor (1,1,1,.2) light / (0,0,0,0) dark → the fill mix after the face matrix (§1: "再 mix 填充色"): out = mix(c, fill, .2),
         a white flood composited at .2; the face matrix's white 1.03 / black .4 / saturation 1.2 (dark 1.125 / .125 / 1.3) act in YCC — the luma
         weights of CA::ColorMatrix::set_ycc_composite were not read at R1 — since read (Rec.709, menu-card-material §7.1, 0x1c398265c) and built (R1′ below, BUILT);
       RingShadow opacity .06 / offset 8 / stroke 4 / blur 5 / mask 1 → keyfill-highlight.md §4: term = .06 · (N((d_r + 4)/5) − N(d_r/5)) inside the
         shape, d_r = the shape's SDF at p + (0, 8); a term of the glassBackground material itself (menu-glass-sdfdump-2026-09-19.md:79–83, not a layer of its
         own), so built as the last stage of f3: the band (the rounded rect shifted 8 pt down, the 4 pt band inside its edge) blurred σ 5 into a map (glassImages
         ring) and composited over the glass (black α term: col·(1 − term)), clipped to the panel (mask 1);
       Clamp 1.07 / 1.308 (clamp(c/a, −.75, limit) at the output) → no effect on 8-bit sRGB values (they never exceed 1): nothing to build;
       ShadowAmount 0 with ShadowOpacity .4 / .6, Radius 24, Offset (0, 8) → §1: amount 0 takes the no-displacement branch; whether a soft shadow
         remains was 待读 at R1 — since read (§7.3: it remains) and drawn (R1′ below); the page's old box-shadow (the alert's sampled substitute) is removed with the old background.
       Not built, 待读 / 不可表达 (listed in keys()): InnerRefraction −60 / 20 and OuterRefraction 41.75 / 33.4 with RefractionOpacity .6 (a
         displacement map for the r32 rounded rect — the segment lens's generator makes capsules only), the in-shader KeyFill highlight (amount .4,
         angle 1.571, bias −.3, offset −.5333, height .5333, spread 1.676 / 1.309), the highlight layer of §3 (CASDFKeyFillHighlightEffect), Bleed
         (58.45 / .5 light .8 dark, the SDF-distance bleed of alert-pipeline-plan §1.3 variant e), BlurFill (8, lighten .9 / darken .9, normal .5:
         formula not read), FaceColorMatrixMaxLuma (1 / .35: formula not read). — R1's list; R1′ / R63 below built all but the EDR MaxLuma
         (已查 menu-card-material.md §7 未读, 缺 whether k_EDR is 0 on an SDR screen; UNBUILT). */
  const GLASS_KEYS = {
    light: { GradientOvalization: 0.5,   // 数据 R109: the menu's glass elements' gradientOvalization (materials[13]/[14] and the elements under the LensingSDFLayer) = .5 (alert-native-formula §4 ⑨: the gradient only)
      BlurRadius: 5, BlurDistance0: -83.5, BlurDistance1: -1, BlurDistance2: 0, BlurDistance3: 0, BlurOpacity0: 0.8, BlurOpacity1: 0.4, BlurOpacity2: 0.5, BlurOpacity3: 1, BlurFillBlurRadius: 8, BlurFillDarkenOpacity: 0, BlurFillLightenOpacity: 0.9, BlurFillNormalOpacity: 0.5,
      FaceColorMatrixWhite: 1.03, FaceColorMatrixBlack: 0.4, FaceColorMatrixSaturation: 1.2, FaceColorMatrixFillColor: [1, 1, 1, 0.2], FaceColorMatrixMaxLuma: 1, FaceColorMatrixMaxLumaSDR: 0.94, FaceOpacity: 1, Clamp: 1.07, ClampPreserveHue: 0,
      InnerRefractionAmount: -60, InnerRefractionHeight: 20, OuterRefractionAmount: 41.75, OuterRefractionHeight: 33.4, RefractionOpacity: 0.6, RefractionDistance0: -1, RefractionDistance1: 0,
      KeyFillHighlightAmount: 0.4, KeyFillHighlightAngle: 1.571, KeyFillHighlightColorBias: -0.3, KeyFillHighlightEffectOffset: -0.5333, KeyFillHighlightHeight: 0.5333, KeyFillHighlightSpread: 1.676, KeyFillHighlightSpreadSDR: 1.85,
      RingShadowOpacity: 0.06, RingShadowOffset: 8, RingShadowStrokeWidth: 4, RingShadowBlurRadius: 5, RingShadowMask: 1,
      BleedAmount: 58.45, BleedBlurRadius: 58.45, BleedHeight: 58.45, BleedOpacity: 0.5, BleedColorMatrixBlack: 0.9, BleedColorMatrixSaturation: 1.2, BleedColorMatrixWhite: 1, BleedDarkenBlend: 1, BleedDistance0: 1, BleedDistance1: 0,
      ShadowAmount: 0, ShadowOpacity: 0.4, ShadowRadius: 24, ShadowOffset: [0, 8], ShadowColorMatrixFillColor: [0, 0, 0, 0.3], ShadowBlurRadius: 0, ShadowHeight: 0, ShadowDistanceOffset: 0, ShadowVibrancyContribution: 0, ShadowColorMatrixWhite: 1, ShadowColorMatrixBlack: 0, ShadowColorMatrixSaturation: 1,
      SDRGradientDistance0: 0, SDRGradientDistance1: 0, SDRHoldingToneEnabled: 0, SDRHoldingToneWhite: 1, SDRShadowOpacity: 0, MaxHeadroom: 9999 },
    dark: { BlurFillDarkenOpacity: 0.9, BlurFillLightenOpacity: 0, FaceColorMatrixWhite: 1.125, FaceColorMatrixBlack: 0.125, FaceColorMatrixSaturation: 1.3, FaceColorMatrixFillColor: [0, 0, 0, 0], FaceColorMatrixMaxLuma: 0.35, FaceColorMatrixMaxLumaSDR: 0.35, Clamp: 1.308,
      KeyFillHighlightSpread: 1.309, KeyFillHighlightSpreadSDR: 1.309, BleedOpacity: 0.8, BleedColorMatrixBlack: 0.125, BleedColorMatrixSaturation: 1, BleedColorMatrixWhite: 0.5, BleedDarkenBlend: 0, ShadowOpacity: 0.6 } };
  const BUILT = { BlurRadius: "the level mix r(d) = 5·(.8 − .4·s1 − .5·s2) → lod → pyramid levels 1 / 2 = σ 8.59 / 18.78 pt (VB_STD ÷ .25; alert-native-formula §1–§2, alert-glass.js f1)", "BlurDistance*/BlurOpacity*": "the rim's blur reduction: the per-pixel level weights image (glassImages weights, 09-25)", FaceColorMatrixFillColor: "folded into the face matrix, premultiplied (matrix × (1 − a), bias + rgb·a; alert-native-formula §4 ⑦ set_ycc_composite)",
    RingShadowOpacity: "f3's last stage: the band map (black α .06 · blurred coverage), composited over the glass = col·(1 − term) (keyfill-highlight §4)", RingShadowOffset: "the band's shape shifted (0, 8)", RingShadowStrokeWidth: "band width 4 inside the shifted edge", RingShadowBlurRadius: "σ 5, three box passes baked into the map (glassImages ring)", RingShadowMask: "clipped to the panel (mask 1)",
    Clamp: "no-op on 8-bit values (never above 1)", ShadowAmount: "0 → the no-displacement branch (alert-native-formula §1); no shadow drawn" };
  Object.assign(BUILT, { "FaceColorMatrixWhite/Black/Saturation": "feColorMatrix = YCC⁻¹·D·YCC (Rec.709, menu-card-material §7.1)", FaceColorMatrixMaxLumaSDR: "the pre-compression k = sat(1 − Y·(1 − MaxLumaSDR)), c′ = c·k + .3(1 − k)(c·k − Y·k) (§7.1) as c·A(Y) − B(Y): two luma LUTs, α kept 1 (R57′)", "BlurFillBlurRadius/Darken/Lighten/Normal": "b = the unrefracted capture at mip 3 (level std 9.581 → σ 38.32 pt) sampled at ±.75 mip texels (±24 pt) and averaged, then darken / lighten blends + arithmetic mixes on the refracted c (§7.2 / §7c, R63′)", "ShadowOpacity/Radius/Offset/ColorMatrixFillColor": "drop-shadow 0 8 16.9706 rgba(0,0,0,.3 × opacity) on the panel (§7.3 / §7.3b: σ = R/√2 of the shader's .5·erfc(d/R), exact on straight edges; corners 表达差异; the colour matrix: 已查 §7.3 未读，缺 how ShadowColorMatrix* build shadow_cm — identity until read)" });
  const UNBUILT = { "FaceColorMatrixMaxLuma (EDR)": "SDR screen: MaxLumaSDR used (k_EDR 0, §7.1)",
 "ShadowColorMatrixWhite/Black/Saturation": "待读: 已查 menu-card-material.md §7.3 / 未读 (line 102) + set_ycc_composite 0x1c398265c，缺 how the four shadow colour keys build shadow_cm", "Bleed capture edge": "近似: the capture box (panel ± marginWidth 58.45 (R84), clamped to the copy) tiled and blurred σ 100 = its mean; native clamp_to_edge replicates the edge column instead (R57′); 已查 menu-card-material.md §7b′ R57′，缺 an SVG filter primitive that samples clamp-to-edge (不可表达)" };
  Object.assign(BUILT, { GradientOvalization: "R63″: .5 (数据 R109) — g = normalize(mix(shape normal, normalize((x, hw/hh·y)), .5)) on the refraction / bleed maps and the highlight / stroke n·dir (alert-native-formula §4 ⑨)",
    "KeyFillHighlight* (in-shader, stroke_mode 1)": "R63′: keyfill-highlight §2c — the band outside the shape (edge − fw/2 … edge + .5333), k per pixel from the SDF normal and SpreadSDR, colour B″ = mix(B, min(face(B), B), k)·(1 + ColorBias·k·(3 − 2B″)) on a second page copy in its own layer (#menu-stroke-f); at rest only",
    "InnerRefraction*/OuterRefraction*/RefractionOpacity/RefractionDistance*": "R63: two feDisplacementMaps (maps from the supercircle SDF, formula §3 uv1/uv2) mixed by .6·sat((d + 1)/1)", "Bleed*": "R63 / R57′: the capture box's mean (feTile + σ 100 blur; lod 5.87 ≈ a 128-pt texel) displaced outward 58.45·Dc through the bleed YCC matrix, weight Opacity·w(d)·(luma or 1 − luma)⁴ as one 65-sample LUT (alert-native-formula §4 ⑦)", "highlight layer (menu-glass-sdfdump §3)": "R63: the KeyFill bands (main + diffuse, spread 1.5253) through the dumped vibrantColorMatrix, two stages" });
  const glassTheme = () => (matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light") || document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const glassKeys = (theme) => ({ ...GLASS_KEYS.light, ...(theme === "dark" ? GLASS_KEYS.dark : {}) });
  const NS = "http://www.w3.org/2000/svg";
  /* R1′ (menu-card-material.md §7, R35 — the glassBackground shader's IR): the three terms that were 待读, now built in the SVG chain, in the shader's order
     blur → BlurFill → MaxLuma → face matrix → fill mix:
       BlurFill (§7.2): bf = the backdrop at mip log2(r) (r = BlurFillBlurRadius 8 → mip 3; here feGaussianBlur σ = 8 × 4 pt on the same 1/4-resolution
         reading as the main blur — the mip's two-point average is 近似 mip, as the read says — superseded by §7c R82, see BlurFill below: mip lod 3 ± .75 texel, read values); out = darken·min(c, bf) + lighten·max(c, bf) +
         (1 − darken − lighten)·c; final = mix(out, bf, normal) — min / max = feBlend darken / lighten, the mixes = feComposite arithmetic (exact);
       MaxLuma (§7.1, before the face matrix): complement = 1 − MaxLumaSDR (SDR screen, k_EDR 0): light .06 / dark .65; Y = .2126 R + .7152 G + .0722 B;
         k = saturate(1 − Y·complement); c′ = mix(Y·k, c·k, 1 + .3(1 − k)) = c·k + .3(1 − k)·(c·k − Y·k) — the products through feComposite arithmetic
         k1 (i1·i2), the signed difference as its positive and negative parts (SVG clamps intermediates at 0), then c·k + P − N;
       face matrix (§7.1): M = YCC⁻¹ · D · YCC with Rec.709 YCC (Y = .2126/.7152/.0722; Cb = −.1146/−.3854/.5 + .5; Cr = .5/−.4542/−.0458 + .5), D:
         Y′ = (White − Black)·Y + Black, Cb′ / Cr′ = sat·(·) + (.5 − .5 sat), YCC⁻¹ (R = Y + 1.5748 Cr − .7874; G = Y − .18732 Cb − .46812 Cr + .32772;
         B = Y + 1.8556 Cb − .9278) — one feColorMatrix computed here from those constants (exact); then the fill mix (a flood at the fill's alpha);
       the soft shadow (§7.3): ShadowAmount 0 only skips the displacement — the shadow is drawn: black α .3 × ShadowOpacity (.4 light / .6 dark), radius 24,
         offset (0, 8), the panel's shape — CSS drop-shadow on the panel; the shader's profile is .5·erfc(d/R) = a Gaussian edge of σ = R/√2 = 16.9706 (§7.3b), so
         drop-shadow's σ argument is 16.9706 — exact on straight edges, corners (convolution vs SDF distance) remain 表达差异. */
  const mul = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((acc, v, i) => acc + v * B[i][j], 0)));   // 4×4 affine (3×3 + offset column as homogeneous)
  const faceMatrix = (k) => { const W = k.FaceColorMatrixWhite, Bk = k.FaceColorMatrixBlack, sat = k.FaceColorMatrixSaturation, fill = k.FaceColorMatrixFillColor;
    const YCC = [[.2126, .7152, .0722, 0], [-.1146, -.3854, .5, .5], [.5, -.4542, -.0458, .5], [0, 0, 0, 1]];
    const D = [[W - Bk, 0, 0, Bk], [0, sat, 0, .5 - .5 * sat], [0, 0, sat, .5 - .5 * sat], [0, 0, 0, 1]];
    const INV = [[1, 0, 1.5748, -.7874], [1, -.18732, -.46812, .32772], [1, 1.8556, 0, -.9278], [0, 0, 0, 1]];
    let M = mul(mul(INV, D), YCC); const r = (v) => (+v.toFixed(5)).toString();
    /* the fill (alert-native-formula §4 ⑦, set_ycc_composite 0x1c3982748–0x1c39827a0): the whole matrix × (1 − a), the PREMULTIPLIED fill (rgb·a) added to the bias — one
       matrix instead of a flood composited after it (R57′: the extra 8-bit step cost a unit on the five-grey check) */
    if (fill && fill[3] > 0) M = M.map((row, i) => i < 3 ? row.map((v, j) => v * (1 - fill[3]) + (j === 3 ? fill[i] * fill[3] : 0)) : row);
    return [0, 1, 2].map((i) => `${r(M[i][0])} ${r(M[i][1])} ${r(M[i][2])} 0 ${r(M[i][3])}`).join(" ") + " 0 0 0 1 0"; };
  /* ---- R63: the three items left open by R1 / R1′ — refraction, the highlight layer, bleed (plus the in-shader KeyFill, which turns out 待读) ----
     Refraction (glass-displacement-formula.md §3 %299–%557): uv1 = uv + InnerRefractionAmount·(1 − sqrt(t(2 − t)))·g, t = sat(−d/InnerRefractionHeight);
       uv2 the same with the Outer keys; c = mix(c1, c2, RefractionOpacity·sat((d − Distance0)/(Distance1 − Distance0))) — the menu's keys −60 / 20,
       41.75 / 33.4, .6, distances −1 / 0 (menu-glass-sdfdump §2): two feDisplacementMaps from maps generated here on the panel's rest box and a
       per-pixel mix weight; the shape = the continuous-corner rounded rect (cornerRadii 32 continuous → the supercircle branch, label-end-tear §7 ②).
     Highlight layer (menu-glass-sdfdump §3: CASDFKeyFillHighlightEffect curvature .75, key / fill height 1, spread 1.5253 both, amount .5, diffuse
       .15 / ×8 / ×.65, angles 0 / π; vibrantColorMatrix = the dumped 4×5): keyfill-highlight.md §2 bands — main (key from the top + fill from the
       bottom) then diffuse, each stage out ← (1 − α)·out + α·V(out) (the three-emit rule) — generated α images, the matrix as feColorMatrix.
     Bleed (alert-native-formula §3 variant e with the menu's keys: Amount / Height / BlurRadius 58.45, Opacity .5 light / .8 dark, colour matrix
       white 1 / black .9 / sat 1.2 light (dark .5 / .125 / 1), DarkenBlend 1 light / 0 dark, Distance 1 / 0): uv_b = uv + 58.45·(1 − sqrt(t(2 − t)))·g,
       t = sat(−d/58.45); c_b = bleed_cm·backdrop_blurred(uv_b) (BleedBlurRadius 58.45 → lod 5.87 → the level mix's std ÷ .25 = 293 pt: one
       feGaussianBlur with edgeMode duplicate for the capture's clamp_to_edge); darken = ((x·luma(c) + y)²·w)², (x, y) = (1, 0) light / (−1, 1)
       dark, w = sat((d − 1)/(0 − 1)) = 1 inside; c′ = mix(c, c_b, Opacity·darken) — luma⁴ through feComponentTransfer gamma 4.
     In-shader KeyFill (keyfill §5.1): the menu's Height .5333 with EffectOffset −.5333 gives stroke_mode = (offset < 0) ∧ |height + offset| < .001 = 1
       (0x1c3a68418–0x1c3a68444) — at R63 the stroke-mode branch was unread; since read (keyfill-highlight.md §2c) and built (R63′ below, BUILT). */
  const KR = 1.528665, satf = (x) => Math.max(0, Math.min(1, x));
  const scPoly = (rho) => (((-0.926054 * rho + 3.15601) * rho - 3.64122) * rho + 1.26803) * rho + 0.268531;
  /* R63″ (数据 R109: gradientOvalization .5; alert-native-formula §4 ⑨ R83): g = normalize(mix(g_shape, normalize((x, (hw/hh)·y)), o)) — the gradient only, d untouched; the refraction / bleed
     map directions and the highlight / stroke n·dir turn towards the centre along the long edges */
  const gOval = (x, y, hw, hh, gx, gy, o) => { if (!(o > 0)) return [gx, gy]; const rx = x, ry = (hw / hh) * y, rn = Math.hypot(rx, ry) || 1; const mx = gx + (rx / rn - gx) * o, my = gy + (ry / rn - gy) * o, mn = Math.hypot(mx, my) || 1; return [mx / mn, my / mn]; };
  const sdfSuper = (x, y, hw, hh, r) => { const R = KR * r; const cx = Math.abs(x) - hw, cy = Math.abs(y) - hh; const qx = cx + R, qy = cy + R;
    const ux = Math.max(0, qx / R), uy = Math.max(0, qy / R); const umax = Math.max(ux, uy); const rho = umax > 0 ? Math.min(ux, uy) / umax : 0; const ul = Math.hypot(ux, uy);
    const kk = rho * rho * satf(ul) * scPoly(rho); const f = ul + 1 - 1 / (1 - kk); const d = R * (f - 1) + Math.min(Math.max(qx, qy), 0);
    let gx, gy; if (qx + qy > 0) { gx = Math.max(0, qx); gy = Math.max(0, qy); } else if (qx > qy) { gx = 1; gy = 0; } else { gx = 0; gy = 1; }
    const gn = Math.hypot(gx, gy) || 1; return [d, (gx / gn) * (x >= 0 ? 1 : -1), (gy / gn) * (y >= 0 ? 1 : -1)]; };
  const Dc = (t) => 1 - Math.sqrt(Math.max(0, 2 * t - t * t));
  const bandf = (e, h, cosS, bias, curv, ndir, fw) => { const t = satf(e / h); const prof = (t < 1 ? 1 : 0) * (1 - curv) + (1 - t) * curv; const aa = satf(e / fw + 0.5) * satf((h - e) / fw + 0.5);
    const ang = satf((ndir - cosS) / (1 - cosS)); const vv = e < -5 ? 0 : prof * aa * ang; return vv / (1 + bias * (1 - vv)); };
  const HLK = { curvature: 0.75, height: 1, spread: 1.5253, amount: 0.5, diffuseAmountScale: 0.15, diffuseHeightScale: 8, diffuseSpreadScale: 0.65, vibrant: [1.1202, -0.1894, -0.019, 0, 0.1471, -0.0563, 0.9871, -0.0191, 0, 0.1471, -0.0563, -0.1893, 1.1574, 0, 0.1471] };
  const VB_STD = [0, 2.147, 4.694, 9.581, 19.263, 38.579, 77.023], CAPTURE = 0.25;   // the pyramid levels' stds (capture px; tools/vb_kernel.py) and the capture scale (as the alert's, alert-native-formula §0)
  /* first-frame stall (simulator D 09-24 10:5x, eb891a9, real taps): the frame after open ran 119–124 ms and after close 109–127 ms while open's JS took 4–7 ms; with
     .menu-glass hidden, or the copy without its filters, no stall — WebKit renders a CSS filter:url() at the device scale (alert-glass.js 串3), so f0's first paint
     at open and f1/f2/f3 → f0 at close cost ~120 ms and the time-based springs jumped to ~80 % / half-way. The native backdrop is captured at CAPTURE .25, so as in
     alert-glass.js f0 / f1 / f2 run on the page laid out at 1 / G (G = dpr / CAPTURE), every length of those filters ÷ G, the result scaled back ×G; f3 (highlight) and
     the stroke stay at full resolution. ?glassres=full keeps G = 1 (instrument) */
  const gres = () => (/[?&]glassres=full\b/.test(location.search) ? 1 : (window.devicePixelRatio || 1) / CAPTURE);
  const shrink = (f, g) => { if (!f) return; f.dataset.gres = String(g); if (g === 1) return; for (const a of ["width", "height"]) f.setAttribute(a, String(+f.getAttribute(a) / g));
    for (const e of f.children) for (const a of ["x", "y", "width", "height", "stdDeviation", "dx", "dy", "scale"]) { if (!e.hasAttribute(a) || (a === "scale" && e.tagName !== "feDisplacementMap")) continue; e.setAttribute(a, String(+e.getAttribute(a) / g)); } };
  const mixStd = (L) => { const k0 = Math.min(Math.floor(L), VB_STD.length - 2), f = L - k0; return Math.sqrt((1 - f) * VB_STD[k0] ** 2 + f * VB_STD[k0 + 1] ** 2); };
  const lod = (r) => Math.max(0, r >= 2 ? Math.log2(r) : Math.log2(1 + r / 2));
  const PXG = 2, MAPS = 128;
  /* the ring band: the rounded rect (the panel's box) shifted RingShadowOffset down, the band = the shape minus the same shape inset by the stroke width (evenodd) */
  const ringPath = (w, h, r, off, sw) => { const rr = (x, y, ww, hh, rad) => { const q = Math.max(0, Math.min(rad, ww / 2, hh / 2)); return `M${x + q} ${y}H${x + ww - q}A${q} ${q} 0 0 1 ${x + ww} ${y + q}V${y + hh - q}A${q} ${q} 0 0 1 ${x + ww - q} ${y + hh}H${x + q}A${q} ${q} 0 0 1 ${x} ${y + hh - q}V${y + q}A${q} ${q} 0 0 1 ${x + q} ${y}Z`; };
    return rr(0, off, w, h, r) + " " + rr(sw, off + sw, w - 2 * sw, h - 2 * sw, Math.max(0, r - sw)); };
  /* a map built as a generator job, run in slices (warmUp) or to the end (the sync entries: more = () => true): at least one step per call, then on while more();
     true once it has finished. A thrown job is dropped, so the next call starts it again and throws as the unsliced code did */
  const drive = (jobs, key, make, more) => { const it = jobs[key] || (jobs[key] = make()); let s; try { do s = it.next(); while (!s.done && more()); } catch (e) { delete jobs[key]; throw e; } if (s.done) delete jobs[key]; return s.done; };
  const domCanvas = (w, h) => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; };   // the worker's source defines its own (an OffscreenCanvas)
  const glassPx = function* (W, H, k, mkc) { const hw = W / 2, hh = H / 2, r = 32, w = Math.round(W * PXG), h = Math.round(H * PXG);
    const mk = () => mkc(w, h); const cin = mk(), cout = mk(), chl = mk(), chl2 = mk(), cbl = mk(), cw = mk();
    const iin = cin.getContext("2d").createImageData(w, h), iout = cout.getContext("2d").createImageData(w, h), ihl = chl.getContext("2d").createImageData(w, h), ihl2 = chl2.getContext("2d").createImageData(w, h), ibl = cbl.getContext("2d").createImageData(w, h), iw = cw.getContext("2d").createImageData(w, h);
    const cosK = Math.cos(HLK.spread), cosD = Math.cos(HLK.diffuseSpreadScale * HLK.spread), biasD = 1 / (HLK.diffuseAmountScale * HLK.amount) - 2, hD = HLK.diffuseHeightScale * HLK.height, fw = 1 / 3;
    for (let j = 0; j < h; j++) { if (j) yield; for (let i = 0; i < w; i++) { const x = (i + 0.5) / PXG - hw, y = (j + 0.5) / PXG - hh; const [d, gsx, gsy] = sdfSuper(x, y, hw, hh, r); const [gx, gy] = gOval(x, y, hw, hh, gsx, gsy, k.GradientOvalization); const o = (j * w + i) * 4;   // R63″: the ovalized gradient drives the directions
      /* the rim's blur reduction (alert-native-formula §1–§2, built in alert-glass.js mapPixels): r(d) = BlurRadius·(BlurOpacity0 − BlurOpacity1·s1 − BlurOpacity2·s2), s1 / s2 the
         ramps over BlurDistance0 → 1 → 2 (menu keys −83.5 / −1 / 0, menu-glass-sdfdump §2) → level lod(r), the weights of the pyramid levels 0 / 1 / 2 in R / G / B (0 outside) */
      { const s1 = satf((d - k.BlurDistance0) / (k.BlurDistance1 - k.BlurDistance0)), s2 = satf((d - k.BlurDistance1) / (k.BlurDistance2 - k.BlurDistance1));
        const L = d > 0 ? 0 : lod(Math.max(0, k.BlurRadius * (k.BlurOpacity0 - k.BlurOpacity1 * s1 - k.BlurOpacity2 * s2)));
        for (let c = 0; c < 3; c++) iw.data[o + c] = Math.round(255 * Math.max(0, 1 - Math.abs(L - c))); iw.data[o + 3] = 255; }
      const di = k.InnerRefractionAmount * Dc(satf(-d / k.InnerRefractionHeight)), dout = k.OuterRefractionAmount * Dc(satf(-d / k.OuterRefractionHeight));
      const wr = Math.round(255 * k.RefractionOpacity * satf((d - k.RefractionDistance0) / (k.RefractionDistance1 - k.RefractionDistance0)));
      iin.data[o] = Math.round(128 + di * gx * 255 / MAPS); iin.data[o + 1] = Math.round(128 + di * gy * 255 / MAPS); iin.data[o + 2] = wr; iin.data[o + 3] = 255;
      iout.data[o] = Math.round(128 + dout * gx * 255 / MAPS); iout.data[o + 1] = Math.round(128 + dout * gy * 255 / MAPS); iout.data[o + 2] = 0; iout.data[o + 3] = 255;
      const db = k.BleedAmount * Dc(satf(-d / k.BleedHeight)); const wb = Math.round(255 * satf((d - k.BleedDistance0) / (k.BleedDistance1 - k.BleedDistance0)));   // the bleed map (outward) and w(d)
      ibl.data[o] = Math.round(128 + db * gx * 255 / MAPS); ibl.data[o + 1] = Math.round(128 + db * gy * 255 / MAPS); ibl.data[o + 2] = wb; ibl.data[o + 3] = 255;
      const e = -d; let a1 = 0, a2 = 0;
      if (d <= 0) { for (const dy of [-1, 1]) { const nd = gy * dy; a1 += bandf(e, HLK.height, cosK, 0, HLK.curvature, nd, fw); a2 = 1 - (1 - a2) * (1 - satf(bandf(e, hD, cosD, biasD, 1, nd, fw))); } }
      ihl.data[o] = ihl.data[o + 1] = ihl.data[o + 2] = Math.round(255 * satf(a1)); ihl.data[o + 3] = 255; ihl2.data[o] = ihl2.data[o + 1] = ihl2.data[o + 2] = Math.round(255 * satf(a2)); ihl2.data[o + 3] = 255; } }
    cin.getContext("2d").putImageData(iin, 0, 0); cout.getContext("2d").putImageData(iout, 0, 0); chl.getContext("2d").putImageData(ihl, 0, 0); chl2.getContext("2d").putImageData(ihl2, 0, 0); cbl.getContext("2d").putImageData(ibl, 0, 0); cw.getContext("2d").putImageData(iw, 0, 0);
    /* the ring band (RingShadow*, menu-glass-sdfdump-2026-09-19.md:79–83): the band's coverage drawn RingShadowOffset taller than the box (the shifted shape's bottom
       band lies below it and its blur reaches back inside), blurred σ RingShadowBlurRadius here — three box passes of width ⌊σ·3√(2π)/4 + .5⌋ (odd), the
       approximation WebKit's feGaussianBlur uses — and cropped to the box: black, α = RingShadowOpacity · blurred coverage. Baked, not an in-chain feGaussianBlur:
       a blur primitive in f3 moved the whole glass under it by up to 5 levels (a different render of the chain; simulator B 09-29, interior ≥ 20 pt from the
       band: 0 levels without it, ≤ 5.7 with it) */
    yield; const off = k.RingShadowOffset, rh = Math.round((H + off) * PXG), cb = mkc(w, rh);
    { const x = cb.getContext("2d"); x.scale(w / W, rh / (H + off)); x.fill(new Path2D(ringPath(W, H, r, off, k.RingShadowStrokeWidth)), "evenodd"); }
    const cov = cb.getContext("2d").getImageData(0, 0, w, rh).data, A = new Float32Array(w * rh), T = new Float32Array(Math.max(w, rh)), sg = k.RingShadowBlurRadius * w / W, bw = Math.max(1, Math.floor(sg * 3 * Math.sqrt(2 * Math.PI) / 4 + 0.5)) | 1, bh = (bw - 1) / 2;
    for (let i = 0; i < w * rh; i++) A[i] = cov[i * 4 + 3] / 255;
    const box = (n, at) => { let acc = 0; for (let i = 0; i < Math.min(bh, n); i++) acc += A[at(i)]; for (let i = 0; i < n; i++) { if (i + bh < n) acc += A[at(i + bh)]; T[i] = acc / bw; if (i - bh >= 0) acc -= A[at(i - bh)]; } for (let i = 0; i < n; i++) A[at(i)] = T[i]; };   // a centred box, 0 outside
    for (let pass = 0; pass < 3; pass++) { for (let j = 0; j < rh; j++) { yield; box(w, (i) => j * w + i); } for (let i = 0; i < w; i++) { yield; box(rh, (j) => j * w + i); } }   // a slice per row / column; each pass still all rows, then all columns
    yield; const cr = mk(), ir = cr.getContext("2d").createImageData(w, h); for (let i = 0; i < w * h; i++) ir.data[i * 4 + 3] = Math.round(255 * k.RingShadowOpacity * A[i]); cr.getContext("2d").putImageData(ir, 0, 0);
    return [cin, cout, chl, chl2, cbl, cw, cr]; };
  const glassPack = (u, W, H) => ({ inner: u[0], outer: u[1], hl: u[2], hl2: u[3], bleed: u[4], weights: u[5], ring: u[6], W, H });
  const glassImages = (() => { const cache = {}, jobs = {}, keyOf = (W, H, k) => `${W}x${H} ${JSON.stringify(k)}`; const work = function* (W, H, k, key) { const cs = yield* glassPx(W, H, k, domCanvas);
    const u = []; for (const c of cs) { yield; u.push(c.toDataURL("image/png")); }   // one encode a slice (the largest step that cannot be cut)
    cache[key] = glassPack(u, W, H); };
    const step = (W, H, k, more) => { const key = keyOf(W, H, k); return !!cache[key] || drive(jobs, key, () => work(W, H, k, key), more); };   // warmUp's sliced entry
    const f = (W, H, k) => { const key = keyOf(W, H, k); if (!cache[key]) step(W, H, k, () => true); return cache[key]; }; f.step = step;
    f.has = (W, H, k) => !!cache[keyOf(W, H, k)]; f.put = (W, H, k, v) => { const key = keyOf(W, H, k); if (cache[key]) return false; cache[key] = v; delete jobs[key]; return true; };   // put: a map the worker built (a half-built main-thread job is dropped)
    return f; })();   // sync: a job warmUp left half-done is finished from where it stopped
  const yccMatrix = (W, Bk, sat) => { const YCC = [[.2126, .7152, .0722, 0], [-.1146, -.3854, .5, .5], [.5, -.4542, -.0458, .5], [0, 0, 0, 1]];
    const D = [[W - Bk, 0, 0, Bk], [0, sat, 0, .5 - .5 * sat], [0, 0, sat, .5 - .5 * sat], [0, 0, 0, 1]]; const INV = [[1, 0, 1.5748, -.7874], [1, -.18732, -.46812, .32772], [1, 1.8556, 0, -.9278], [0, 0, 0, 1]];
    const M = mul(mul(INV, D), YCC); const r = (v) => (+v.toFixed(5)).toString(); return [0, 1, 2].map((i) => `${r(M[i][0])} ${r(M[i][1])} ${r(M[i][2])} 0 ${r(M[i][3])}`).join(" ") + " 0 0 0 1 0"; };
  const selCh = (src, ch, name) => `<feColorMatrix in="${src}" type="matrix" values="${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  ${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  ${[0, 1, 2, 3].map((c) => (c === ch ? "1" : "0")).join(" ")} 0  0 0 0 0 1" result="${name}"/>`;
  const invert = (src, name) => `<feComponentTransfer in="${src}" result="${name}"><feFuncR type="linear" slope="-1" intercept="1"/><feFuncG type="linear" slope="-1" intercept="1"/><feFuncB type="linear" slope="-1" intercept="1"/></feComponentTransfer>`;
  /* MaxLuma (menu-card-material §7.1; alert-native-formula §4 ⑦, IR %568–%584): c′ = c·k + .3(1 − k)(c·k − Y·k), k = sat(1 − comp·Y). Arranged as c′ = c·A(Y) − B(Y)
     with A = k(1.3 − .3k), B = .3(1 − k)kY (the same formula, regrouped by Y): two luma LUTs (feComponentTransfer table, 33 samples of a quadratic) and two
     arithmetic composites whose α stays 1 — the earlier form's difference terms (c·k − Y·k) had α 0 in Chrome's premultiplied 8-bit buffers (clamped to 0: the
     chroma term silently vanished) */
  const lut = (fn, n = 33) => Array.from({ length: n }, (_, i) => (+fn(i / (n - 1)).toFixed(5)).toString()).join(" ");
  const tf3 = (name, src, values) => `<feComponentTransfer in="${src}" result="${name}"><feFuncR type="table" tableValues="${values}"/><feFuncG type="table" tableValues="${values}"/><feFuncB type="table" tableValues="${values}"/></feComponentTransfer>`;
  const maxLumaChain = (src, comp, luma) => { const kOf = (Y) => Math.max(0, Math.min(1, 1 - comp * Y)), A = (Y) => { const k = kOf(Y); return k * (1.3 - .3 * k); }, iB4 = (Y) => { const k = kOf(Y); return 1 - 4 * .3 * (1 - k) * k * Y; };   // B ≤ .017 light / .068 dark: stored ×4 (feComponentTransfer truncates to 8 bits — 1 − B would lose a whole unit)
    return comp > 0 && comp < 1 ? `<feColorMatrix in="${src}" type="matrix" values="${luma} 0 0 ${luma} 0 0 ${luma} 0 0 0 0 0 1 0" result="Y"/>` + tf3("A", "Y", lut(A)) + tf3("iB4", "Y", lut(iB4))
      + `<feComposite in="${src}" in2="A" operator="arithmetic" k1="1" result="cA"/><feComposite in="cA" in2="iB4" operator="arithmetic" k2="1" k3=".25" k4="-.25" result="ml"/>` : `<feComposite in="${src}" in2="${src}" operator="over" result="ml"/>`; };
  /* α reset: BlurFill's arithmetic mixes pass through α .9 and come back to ≈ .992, not 1 (Chrome rounds each premultiplied 8-bit buffer); every later feBlend then adds
     (1 − α)·backdrop (+2/255 on a 128 grey) — un-premultiply and pin α = 1 (feFuncA discrete [1]); inside the panel clip the source is opaque everywhere */
  const alphaOne = (src, name) => `<feComponentTransfer in="${src}" result="${name}"><feFuncA type="discrete" tableValues="1"/></feComponentTransfer>`;
  const ensureFilter = (theme, W, H) => { const k = glassKeys(theme); let svg = document.getElementById("menu-glass-svg"); if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "menu-glass-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    const im = glassImages(W || 250, H || 167, k), M = 120, bleedSig = mixStd(lod(k.BleedBlurRadius)) / CAPTURE, bleedCM = yccMatrix(k.BleedColorMatrixWhite, k.BleedColorMatrixBlack, k.BleedColorMatrixSaturation), dk = k.BleedDarkenBlend ? [1, 0] : [-1, 1];
    const img = (href, name) => `<feImage href="${href}" preserveAspectRatio="none" x="0" y="0" width="${im.W}" height="${im.H}" result="${name}" data-menu-img="${name}"/>`;
    const fill = k.FaceColorMatrixFillColor, comp = 1 - k.FaceColorMatrixMaxLumaSDR, d = k.BlurFillDarkenOpacity, l = k.BlurFillLightenOpacity, n = k.BlurFillNormalOpacity, luma = ".2126 .7152 .0722";
    const faceCM = `<feColorMatrix in="ml" type="matrix" values="${faceMatrix(k)}" result="out"/>`;   // the face matrix with the fill folded in (faceMatrix) — its output is the face `out`
    /* BlurFill (menu-card-material §7c, R82 correction): b = the UNREFRACTED capture's mip lod = log2(BlurFillBlurRadius 8) = 3 (level std 9.581 capture px → σ 38.32 pt) sampled at
       uv ± .75 mip-3 texels (a texel = 8 capture px = 32 pt → ±24 pt, on both axes) and averaged; c′ = Darken·min(c, b) + Lighten·max(c, b) + (1 − D − L)·c, c″ = mix(c′, b, Normal), c = the
       refracted colour. So the stage lives in f1 (which has both the source and the refracted mix) — no σ-in-quadrature over the refracted output (R63's 近似) */
    const bfSig = mixStd(lod(k.BlurFillBlurRadius)) / CAPTURE, bfOff = 0.75 * 8 / CAPTURE;
    /* the main blur as the alert's per-pixel level mix (alert-glass.js f1): levels 1 / 2 = σ VB_STD ÷ .25 = 8.59 / 18.78 pt, level 0 = the plain capture; deep inside r = 5·.8 = 4 → level 2,
       towards the rim r → 2 (level 1) over BlurDistance0 → 1 and → 0 in the last pt. The weights image is made opaque red beyond the panel box (level 0 there: the page itself) */
    const lvSig = [1, 2].map((lv) => VB_STD[lv] / CAPTURE);
    const levelBlur = `<feGaussianBlur in="SourceGraphic" stdDeviation="${lvSig[0].toFixed(3)}" result="lb1"/><feGaussianBlur in="SourceGraphic" stdDeviation="${lvSig[1].toFixed(3)}" result="lb2"/>`
      + img(im.weights, "lwi") + `<feFlood flood-color="rgb(255,0,0)" result="lwo"/><feComposite in="lwi" in2="lwo" operator="over" result="lw"/>` + selCh("lw", 0, "lw0") + selCh("lw", 1, "lw1") + selCh("lw", 2, "lw2")
      + `<feBlend in="SourceGraphic" in2="lw0" mode="multiply" result="lp0"/><feBlend in="lb1" in2="lw1" mode="multiply" result="lp1"/><feBlend in="lb2" in2="lw2" mode="multiply" result="lp2"/>`
      + `<feComposite in="lp0" in2="lp1" operator="arithmetic" k2="1" k3="1" result="l01"/><feComposite in="l01" in2="lp2" operator="arithmetic" k2="1" k3="1" result="lmix"/><feComposite in="lmix" in2="SourceGraphic" operator="over" result="blur0"/>`;
    const blurFill = `<feGaussianBlur in="SourceGraphic" stdDeviation="${bfSig.toFixed(2)}" result="bfb"/><feOffset in="bfb" dx="${bfOff}" dy="${bfOff}" result="bfp"/><feOffset in="bfb" dx="${-bfOff}" dy="${-bfOff}" result="bfm"/><feComposite in="bfp" in2="bfm" operator="arithmetic" k2=".5" k3=".5" result="bf"/>`
      + `<feBlend in="blur" in2="bf" mode="darken" result="mn"/><feBlend in="blur" in2="bf" mode="lighten" result="mx"/>`
      + `<feComposite in="mn" in2="mx" operator="arithmetic" k2="${d}" k3="${l}" result="dl"/><feComposite in="dl" in2="blur" operator="arithmetic" k2="1" k3="${1 - d - l}" result="bfo"/>`
      + `<feComposite in="bfo" in2="bf" operator="arithmetic" k2="${1 - n}" k3="${n}" result="c0"/>` + alphaOne("c0", "c");
    const maxLuma = maxLumaChain("c", comp, luma);
    /* every generated image is made opaque beyond the panel box (R57′: feBlend multiply leaks (1 − α)·source at a half-transparent image edge — a bright ring the blurs spread inward): maps over (128,128,0) = no displacement / zero weight, band images over black */
    const refraction = img(im.inner, "mapi0") + img(im.outer, "mapo0") + `<feFlood flood-color="rgb(128,128,0)" result="mid"/><feComposite in="mapi0" in2="mid" operator="over" result="mapi"/><feComposite in="mapo0" in2="mid" operator="over" result="mapo"/>` + selCh("mapi", 2, "wr") + invert("wr", "wri")
      + `<feDisplacementMap in="blur0" in2="mapi" scale="${MAPS}" xChannelSelector="R" yChannelSelector="G" result="c1"/><feDisplacementMap in="blur0" in2="mapo" scale="${MAPS}" xChannelSelector="R" yChannelSelector="G" result="c2"/>`
      + `<feBlend in="c1" in2="wri" mode="multiply" result="q1"/><feBlend in="c2" in2="wr" mode="multiply" result="q2"/><feComposite in="q1" in2="q2" operator="arithmetic" k2="1" k3="1" result="blur"/>`;
    /* bleed: the backdrop's capture average displaced outward by the bleed map, through the bleed colour matrix; the weight = Opacity · w(d) · darken(luma).
       The average: the capture box (panel ± CAPM, the menu's own marginWidth 58.45 — see CAPM) TILED, then blurred with σ = min(293, M2 / 3) inside
       f2's wider region — Chrome ignores feGaussianBlur's edgeMode (a σ 293 blur in a 120 margin blurred in transparency), and a tiled box's blur is its mean (R57′) */
    const CAPM = k.BleedBlurRadius, M2 = 300, bleedBlur = Math.min(bleedSig, M2 / 3);   // CAPM: the menu backdrop's marginWidth 58.45 = BleedBlurRadius (数据 R84, menu-glass-sdfdump §2 layers[32]; UIKit takes the largest of four keys — bleed's is the BlurRadius)
    const bleed = img(im.bleed, "mapb0") + `<feFlood flood-color="rgb(128,128,0)" result="midb"/><feComposite in="mapb0" in2="midb" operator="over" result="mapb"/>` + selCh("mapb", 2, "wb")
      + `<feOffset in="SourceGraphic" dx="0" dy="0" x="${-CAPM}" y="${-CAPM}" width="${im.W + 2 * CAPM}" height="${im.H + 2 * CAPM}" result="cap" data-menu-cap="${CAPM}"/><feTile in="cap" result="tiled"/><feGaussianBlur in="tiled" stdDeviation="${bleedBlur.toFixed(2)}" result="bb"/>`
      + `<feDisplacementMap in="bb" in2="mapb" scale="${MAPS}" xChannelSelector="R" yChannelSelector="G" result="bd"/><feColorMatrix in="bd" type="matrix" values="${bleedCM}" result="cb"/>`
      + `<feColorMatrix in="out" type="matrix" values="${luma} 0 0 ${luma} 0 0 ${luma} 0 0 0 0 0 1 0" result="lm"/><feComponentTransfer in="lm" result="lx"><feFuncR type="linear" slope="${dk[0]}" intercept="${dk[1]}"/><feFuncG type="linear" slope="${dk[0]}" intercept="${dk[1]}"/><feFuncB type="linear" slope="${dk[0]}" intercept="${dk[1]}"/></feComponentTransfer>`
      + tf3("w4", "lx", lut((L) => k.BleedOpacity * L ** 4, 65))   /* w = Opacity · L⁴ as one luma LUT (65 samples of the quartic), then × w(d) from the map */
      + `<feBlend in="w4" in2="wb" mode="multiply" result="wbl"/>` + invert("wbl", "wbli")
      + `<feBlend in="out" in2="wbli" mode="multiply" result="o0"/><feBlend in="cb" in2="wbl" mode="multiply" result="o1"/><feComposite in="o0" in2="o1" operator="arithmetic" k2="1" k3="1" result="ob"/>`;
    /* the highlight layer: two stages (main bands, then diffuse), each out ← (1 − α)·out + α·V(out) */
    const highlight = img(im.hl, "hl0") + img(im.hl2, "hl20") + `<feFlood flood-color="rgb(0,0,0)" result="blk"/><feComposite in="hl0" in2="blk" operator="over" result="hl"/><feComposite in="hl20" in2="blk" operator="over" result="hl2"/>` + `<feColorMatrix in="ob" type="matrix" values="${HLK.vibrant.join(" ")} 0 0 0 1 0" result="v1"/>` + invert("hl", "hli")
      + `<feBlend in="ob" in2="hli" mode="multiply" result="h0"/><feBlend in="v1" in2="hl" mode="multiply" result="h1"/><feComposite in="h0" in2="h1" operator="arithmetic" k2="1" k3="1" result="oh"/>`
      + `<feColorMatrix in="oh" type="matrix" values="${HLK.vibrant.join(" ")} 0 0 0 1 0" result="v2"/>` + invert("hl2", "hl2i")
      + `<feBlend in="oh" in2="hl2i" mode="multiply" result="g0"/><feBlend in="v2" in2="hl2" mode="multiply" result="g1"/><feComposite in="g0" in2="g1" operator="arithmetic" k2="1" k3="1" result="final"/>`;
    /* the ring shadow, a stage of the same material (glassBackground RingShadow*, menu-glass-sdfdump-2026-09-19.md:79–83 — natively not a layer of its own): the
       blurred band map (black, α = term) composited over the glass = col·(1 − term) where the glass is opaque — the same pixels as the separate ring's mix-blend
       multiply of a black band (multiply by black is black: that blend was a plain source-over). Placed on the rest box once per open like every map
       (placeGlassRest). f3 only (full resolution, on at rest): during the open morph and the dismiss it is off with f3 */
    const ringStage = img(im.ring, "rg0") + `<feComposite in="rg0" in2="final" operator="over" result="ringed" data-menu-ring="over"/>`;
    /* two filters (R63): the chain with refraction + bleed + highlight is ~35 primitives with a σ 293 blur — Chrome paints a url() filter every frame the panel
       repaints (it is not composited), which starved the morph (3–7 frames per 1.5 s vs 70 without it); that was the whole chain on a moving
       panel; the morph now keeps the panel's box fixed and clips it (setMorph), and runs f1 + f2 + the stroke from the first frame, f3 at rest (glassFull).
       #menu-glass-f0 (the R1 / R1′ chain) is no longer used by the morph */
    const head = (id, m = M) => `<filter id="${id}" filterUnits="userSpaceOnUse" x="${-m}" y="${-m}" width="${im.W + 2 * m}" height="${im.H + 2 * m}" color-interpolation-filters="sRGB" data-theme="${theme}" data-margin="${m}" data-blur-radius="${k.BlurRadius}" data-sigma="${k.BlurRadius * 4}" data-bf-sigma="${bfSig.toFixed(2)}" data-bf-off="${bfOff}" data-maxluma-complement="${comp}" data-face="${faceMatrix(k)}" data-bleed-sigma="${bleedSig.toFixed(2)}" data-bleed-blur="${bleedBlur.toFixed(2)}" data-bleed-cm="${bleedCM}" data-size="${im.W}x${im.H}">`;
    /* the rest chain is split over three nested elements (copy: f1 = blur + refraction; wrapper 2: f2 = BlurFill + MaxLuma + face + fill; wrapper 3: f3 = bleed + highlight):
       Blink turns a filter graph into a tree — every `in` reference re-evaluates its subtree — and one 56-primitive chain with its fan-outs wedged headless Chrome
       (bleed + highlight together; either alone ran); each element's SourceGraphic is a raster, so the fan-outs stay cheap */
    svg.innerHTML = head("menu-glass-f1", 220) + `${levelBlur}${refraction}${blurFill}</filter>`   /* f1 = blur + refraction + BlurFill (b from the unrefracted source, §7c); its region 220 ≥ f2's 300 − its blurs' reach: f2 samples an opaque raster wherever its σ 100 tile blur reads */
      + head("menu-glass-f2", M2) + `${maxLumaChain("SourceGraphic", comp, luma)}${faceCM}${bleed}</filter>`   /* the bleed's capture sample = this filter's SourceGraphic (the BlurFilled refracted mix, negligible under σ 100), its weight from `out` (R57′: it had been sampling the face output) */
      + head("menu-glass-f3", 2) + `${highlight.replace(/in="ob"/g, 'in="SourceGraphic"')}${ringStage}</filter>`   /* f3's region = the panel box + 2: its primitives are all per pixel (no blur, no offset; the ring's blur is baked into its map) and .menu-glass clips to the panel, so the ±120 margin was full-resolution work nobody saw (≈ 45 ms of the settle frame, 09-24 14:4x) */
      + head("menu-glass-f") + `${levelBlur}${refraction}${blurFill}${maxLuma}${faceCM}${bleed}${highlight}</filter>`
      + head("menu-glass-f0") + `<feGaussianBlur in="SourceGraphic" stdDeviation="${k.BlurRadius * 4}" result="blur"/>${blurFill}${maxLuma}${faceCM}</filter>`; const g = gres(); for (const id of ["menu-glass-f0", "menu-glass-f1", "menu-glass-f2"]) shrink(document.getElementById(id), g); return k; };
  const buildGlass = (panel, W, H) => { const theme = glassTheme(), k = ensureFilter(theme, W, H); const main = document.getElementById("app"); if (!main) return null;
    const layer = document.createElement("div"); layer.className = "menu-glass"; const page = main.cloneNode(true); page.removeAttribute("id"); page.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); page.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim").forEach((e) => e.remove()); page.querySelectorAll(".held").forEach((e) => e.classList.remove("held")); page.className = "menu-glass-page"; page.setAttribute("aria-hidden", "true"); page.inert = true;
    const G = gres(), mr = main.getBoundingClientRect(), ph = Math.max(mr.height, innerHeight + 200); page.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;min-height:${ph}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor};transform:scale(${1 / G});transform-origin:0 0`;
    const copy = document.createElement("div"); copy.className = "menu-glass-copy"; copy.style.cssText = `position:absolute;left:0;top:0;width:${mr.width / G}px;height:${ph / G}px;pointer-events:none;filter:url(#menu-glass-f0)`; copy.appendChild(page);   // the morph's chain; the full chain once settled (R63); the page colour under #app (body's, #app paints none — R57′: a transparent-backed copy blurred to α < 1 let the live page through the glass)
    const w2 = document.createElement("div"), w3 = document.createElement("div"); w2.className = "menu-glass-w2"; w3.className = "menu-glass-w3"; for (const w of [w2, w3]) w.style.cssText = "position:absolute;left:0;top:0;width:100%;pointer-events:none";
    const up = document.createElement("div"); up.className = "menu-glass-up"; up.style.cssText = `position:absolute;left:0;top:0;width:100%;pointer-events:none;transform:scale(${G});transform-origin:0 0`;   // the glass background back to page units (gres)
    w2.appendChild(copy); up.appendChild(w2); w3.appendChild(up); layer.append(w3); panel.insertBefore(layer, panel.firstChild);
    return { layer, copy, page, w2, w3, outer: w3, mr, theme, keys: k }; };
  const placeGlass = (g, s, U) => { if (!g || U) return;   // morphing: the layer sits on U (setMorph), the copy's translate is fixed there
    g.outer.style.transform = `translate(${g.mr.left - s.left.x}px, ${g.mr.top - s.top.x}px)`; };   // the copy (in its wrappers) stays on the page's pixels while the panel moves
  /* R63: the filter's region and its generated images are set ONCE per open on the panel's REST box in the copy's coordinates (a per-frame attribute change
     would re-render the whole chain every frame of the morph; the copy's transform alone does not): during the .3 s morph the maps / bands sit at the rest
     box while the panel is still growing towards it — 记录 */
  const placeGlassRest = (g, to) => { if (!g) return; const px = to.left - g.mr.left, py = to.top - g.mr.top, w = to.width, h = to.height;
    for (const id of ["menu-glass-f", "menu-glass-f0", "menu-glass-f1", "menu-glass-f2", "menu-glass-f3"]) { const fx = document.getElementById(id); if (!fx) continue; const m = +fx.dataset.margin || 120, q = +fx.dataset.gres || 1;   // each filter's own margin (f1 220, f2 300 for the bleed's tile blur, the rest 120 — the bleed map reaches ≤ 58.45 pt outside)
      fx.setAttribute("x", String((px - m) / q)); fx.setAttribute("y", String((py - m) / q)); fx.setAttribute("width", String((w + 2 * m) / q)); fx.setAttribute("height", String((h + 2 * m) / q));   // q: f0 / f1 / f2 in the copy's 1 / G units (gres)
      for (const im of fx.querySelectorAll("feImage")) { im.setAttribute("x", String(px / q)); im.setAttribute("y", String(py / q)); im.setAttribute("width", String(w / q)); im.setAttribute("height", String(h / q)); }
      /* the capture box, clamped to the copy's own box (a panel near the page's edge: the copy has no pixels beyond it — native clamp_to_edge would replicate the edge column; the clamped box's mean drops that strip instead) */
      const cap = fx.querySelector("[data-menu-cap]"); if (cap) { const cm = +cap.dataset.menuCap || 58.45, cw = g.page.offsetWidth, ch = g.page.offsetHeight, x0 = Math.max(0, px - cm), y0 = Math.max(0, py - cm), x1 = Math.min(cw, px + w + cm), y1 = Math.min(ch, py + h + cm); cap.setAttribute("x", String(x0 / q)); cap.setAttribute("y", String(y0 / q)); cap.setAttribute("width", String(Math.max(1, x1 - x0) / q)); cap.setAttribute("height", String(Math.max(1, y1 - y0) / q)); } } };
  /* ---- R63′: the in-shader KeyFill's STROKE mode (keyfill-highlight.md §2c; keys menu-glass-sdfdump §2: Amount .4, Angle 1.571, ColorBias −.3, EffectOffset −.5333,
     Height .5333, SpreadSDR 1.85 light / 1.309 dark). stroke_mode = (EffectOffset < 0) ∧ |Height + EffectOffset| < .001 = 1 → the band is OUTSIDE the shape: from
     half a device pixel inside the edge to h = .5333 pt beyond it (prof 1, aa_in = 1 − cov, aa_out = sat(e/fw + .5), e = h − d, fw = one device pixel), per pixel
     k = Σ_{key, fill} v·ang / (1 + a·(1 − v·ang)), a = 1/Amount − 2 = .5, ang = sat((±n·dir − S)/(1 − S)), S = cos(SpreadSDR) (f_EDR 0), dir = (sin Angle, −cos Angle) =
     (1, 0): the left / right sides get k 1 on the outer pixel, the top / bottom sat(−S/(1 − S)) = .216 twice (.31 after the compression) light and 0 dark.
     Colour (§2c %727–%853, α < 1 pixels): B = the capture under the pixel, B′ = face_cm(B) (with the MaxLuma compression), ColorBias < 0 → min(B′, B), B″ = mix(B, ·, k),
     rgb′ = B″·(1 + ColorBias·k·(3 − 2·B″)), extension 1 → α′ = k → on screen the pixel IS rgb′. The panel clips its children (overflow hidden), so the stroke is
     its own fixed layer under the panel (z 8, inserted before it): a second copy of #app clipped by clip-path to the ring [edge − fw/2, edge + h + fw] and filtered
     by #menu-stroke-f (the k map at devicePixelRatio px/pt over the panel box ± 3 pt, the chain above in feBlend darken / multiply / a 3x − 2x² LUT). Built once on
     the rest box two frames into the open and moved / scaled onto the morphing box by a transform (followStroke) until rest; removed at close (strip). */
  const strokePx = function* (W, H, r, k, dpr, mkc) { const E = 3, S = Math.cos(k.KeyFillHighlightSpreadSDR), a = 1 / k.KeyFillHighlightAmount - 2, h = k.KeyFillHighlightHeight, fw = 1 / dpr, dir = [Math.sin(k.KeyFillHighlightAngle), -Math.cos(k.KeyFillHighlightAngle)];
    const w = Math.round((W + 2 * E) * dpr), hh = Math.round((H + 2 * E) * dpr), c = mkc(w, hh); const ctx = c.getContext("2d"), id = ctx.createImageData(w, hh); let kmax = 0, kside = 0, ktop = 0;
    for (let j = 0; j < hh; j++) { if (j) yield; for (let i = 0; i < w; i++) { const x = (i + .5) / dpr - E - W / 2, y = (j + .5) / dpr - E - H / 2; const [d, gsx, gsy] = sdfSuper(x, y, W / 2, H / 2, r); const [gx, gy] = gOval(x, y, W / 2, H / 2, gsx, gsy, k.GradientOvalization); const o = (j * w + i) * 4; let kk = 0;   // R63″: n·dir on the ovalized normal
      const cov = satf(0.5 - d / fw);
      if (!(d - h >= fw / 2 || cov >= 1)) { const e = h - d, v = (1 - cov) * satf(e / fw + 0.5), nd = gx * dir[0] + gy * dir[1];
        for (const sgn of [1, -1]) { const ang = satf((sgn * nd - S) / (1 - S)), va = v * ang; kk += va / (1 + a * (1 - va)); } kk = Math.min(1, kk); }
      id.data[o] = id.data[o + 1] = id.data[o + 2] = Math.round(255 * kk); id.data[o + 3] = 255; kmax = Math.max(kmax, kk);
      if (Math.abs(y) < 0.5 && x < -W / 2 && x > -W / 2 - 1.5 * fw) kside = Math.max(kside, kk); if (Math.abs(x) < 0.5 && y < -H / 2 && y > -H / 2 - 1.5 * fw) ktop = Math.max(ktop, kk); } }
    ctx.putImageData(id, 0, 0); return { c, E, kmax, kside, ktop }; };   // a slice per row
  const strokeMaps = {}, strokeJobs = {}, strokeKey = (W, H, r, k, dpr) => `${W}x${H} ${r} ${dpr} ${JSON.stringify(k)}`, strokeWork = function* (W, H, r, k, dpr, key) { const m = yield* strokePx(W, H, r, k, dpr, domCanvas);
    yield; strokeMaps[key] = { href: m.c.toDataURL("image/png"), E: m.E, dpr, kmax: m.kmax, kside: m.kside, ktop: m.ktop, key }; },   // the encode its own slice
    strokeStep = (W, H, r, k, dpr, more) => { const key = strokeKey(W, H, r, k, dpr); return !!strokeMaps[key] || drive(strokeJobs, key, () => strokeWork(W, H, r, k, dpr, key), more); },   // warmUp's sliced entry
    strokeMap = (W, H, r, k, dpr) => { const key = strokeKey(W, H, r, k, dpr); if (!strokeMaps[key]) strokeStep(W, H, r, k, dpr, () => true); return strokeMaps[key]; };   // sync: finishes a job warmUp left half-done
  const strokeFilter = (theme, W, H, r) => { const k = glassKeys(theme), dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1)), m = strokeMap(W, H, r, k, dpr), E = m.E, comp = 1 - k.FaceColorMatrixMaxLumaSDR, luma = ".2126 .7152 .0722", bias = -k.KeyFillHighlightColorBias;
    let svg = document.getElementById("menu-stroke-svg"); if (!svg) { svg = document.createElementNS(NS, "svg"); svg.id = "menu-stroke-svg"; svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.cssText = "position:absolute;width:0;height:0"; document.body.appendChild(svg); }
    const mode = k.KeyFillHighlightColorBias < 0 ? "darken" : "lighten", qmax = 9 / 8;   // 3x − 2x² peaks at 1.125 (x = .75): the LUT stores it ÷ 1.125
    const fkey = `${theme} ${m.key}`; if (svg.dataset.key === fkey && svg.firstChild) return { E, dpr, map: m }; svg.dataset.key = fkey;
    svg.innerHTML = `<filter id="menu-stroke-f" filterUnits="userSpaceOnUse" x="${-E}" y="${-E}" width="${W + 2 * E}" height="${H + 2 * E}" color-interpolation-filters="sRGB" data-theme="${theme}" data-e="${E}" data-dpr="${dpr}" data-kmax="${m.kmax.toFixed(3)}" data-kside="${m.kside.toFixed(3)}" data-ktop="${m.ktop.toFixed(3)}" data-s="${Math.cos(k.KeyFillHighlightSpreadSDR).toFixed(4)}" data-bias="${bias}">`
      + `<feImage href="${m.href}" preserveAspectRatio="none" x="${-E}" y="${-E}" width="${W + 2 * E}" height="${H + 2 * E}" result="k0" data-stroke-img="1"/><feFlood flood-color="rgb(0,0,0)" result="blk"/><feComposite in="k0" in2="blk" operator="over" result="kk"/>` + invert("kk", "kki")
      + maxLumaChain("SourceGraphic", comp, luma) + `<feColorMatrix in="ml" type="matrix" values="${faceMatrix(k)}" result="face"/><feBlend in="SourceGraphic" in2="face" mode="${mode}" result="bmin"/>`
      + `<feBlend in="SourceGraphic" in2="kki" mode="multiply" result="t1"/><feBlend in="bmin" in2="kk" mode="multiply" result="t2"/><feComposite in="t1" in2="t2" operator="arithmetic" k2="1" k3="1" result="bmix"/>`
      + tf3("qh", "bmix", lut((x) => (3 * x - 2 * x * x) / qmax)) + `<feBlend in="qh" in2="kk" mode="multiply" result="t"/>` + invert("t", "ti")
      + `<feComposite in="bmix" in2="ti" operator="arithmetic" k2="1" k3="${(bias * qmax).toFixed(5)}" k4="${(-bias * qmax).toFixed(5)}" result="out"/></filter>`;   // rgb′ = B″ − bias·k·(3B″ − 2B″²): + c·(1 − t) − c keeps α 1
    return { E, dpr, map: m }; };
  const roundRect = (x, y, w, h, r) => { const q = Math.max(0, Math.min(r, w / 2, h / 2)); return `M${x + q} ${y}H${x + w - q}A${q} ${q} 0 0 1 ${x + w} ${y + q}V${y + h - q}A${q} ${q} 0 0 1 ${x + w - q} ${y + h}H${x + q}A${q} ${q} 0 0 1 ${x} ${y + h - q}V${y + q}A${q} ${q} 0 0 1 ${x + q} ${y}Z`; };
  const buildStroke = (g, panel, to, r) => { if (!g || !g.copy) return null; const main = document.getElementById("app"); if (!main) return null; const W = to.width, H = to.height, th = g.theme, f = strokeFilter(th, W, H, r), E = f.E, fw = 1 / f.dpr, h = g.keys.KeyFillHighlightHeight;
    const el = document.createElement("div"); el.className = "menu-stroke"; el.setAttribute("aria-hidden", "true"); const L = to.left - E, T = to.top - E;
    el.style.cssText = `position:fixed;left:${L}px;top:${T}px;width:${W + 2 * E}px;height:${H + 2 * E}px;overflow:hidden;pointer-events:none;z-index:8;will-change:transform;clip-path:path(evenodd, "${roundRect(E - h - fw, E - h - fw, W + 2 * (h + fw), H + 2 * (h + fw), r + h + fw)} ${roundRect(E + fw / 2, E + fw / 2, W - fw, H - fw, Math.max(0, r - fw / 2))}")`;
    const page = main.cloneNode(true); page.removeAttribute("id"); page.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); page.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim, .menu-stroke").forEach((e) => e.remove()); page.querySelectorAll(".held").forEach((e) => e.classList.remove("held")); page.className = "menu-stroke-page"; page.inert = true;
    const mr = g.mr; page.style.cssText = `position:absolute;left:${mr.left - L}px;top:${mr.top - T}px;width:${mr.width}px;min-height:${Math.max(mr.height, innerHeight + 200)}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor}`;
    /* the filter sits on a box at the layer's origin, the page inside it: WebKit took this userSpaceOnUse region from the layer's origin, not from the filtered element's
       own box (simulator D 09-24 11:4x: a red feFlood on the page-sized copy at x 149 / y 502 painted nothing, at 0 / 0 it filled the layer's box), so the region
       placed in the copy's own units missed the band and the stroke came out empty. Both engines read (0, 0) here as the layer's corner. */
    const copy = document.createElement("div"); copy.className = "menu-stroke-copy"; copy.style.cssText = `position:absolute;left:0;top:0;width:${W + 2 * E}px;height:${H + 2 * E}px;pointer-events:none;filter:url(#menu-stroke-f)`; const fs = document.createElement("fieldset"); fs.disabled = true; fs.style.display = "contents"; page.querySelectorAll("a[href]").forEach((a) => a.removeAttribute("href")); fs.appendChild(page); copy.appendChild(fs);   // no clickable content (see pressStroke)
    const fx = document.getElementById("menu-stroke-f"); fx.setAttribute("x", "0"); fx.setAttribute("y", "0"); const im = fx.querySelector("feImage"); im.setAttribute("x", "0"); im.setAttribute("y", "0");
    el.appendChild(copy); document.body.insertBefore(el, panel); return el; };
  /* the rest chain comes on over three frames: f1 + f2 (the 1 / G copy), then f3 (the full-resolution highlight), then the stroke layer (R63′: only at rest). All
     three in one frame were one 93–114 ms frame on every open (simulator D, 9323, 09-24 14:4x: scripted opens, rAF gaps; f3 alone ≈ 45 ms, the stroke ≈ 25 ms);
     staged, the longest frame is 25–30 ms, the morph's own. tok: a close / re-open between the frames drops the rest of the stages */
  /* one material through the morph (验收 21:38, 用户 21:34「另一个渲染延迟」「接的时候没接好」): natively the glass is one live material from the first frame to the
     last (the morph container's _GlassGroupView tracks both MagicMorphViews' shapes, menu-motion-formula.md §7 ②); the page ran the morph on f0 without the
     edge and switched to f1 + f2 + f3 + the stroke at rest — the "finished look" arrived 28 frames after the shape (7aec6ba) and the dismiss switched back.
     Now f1 + f2 (refraction / bleed at 1 / G) and the stroke are on from the open's first frame to the dismiss's last. f3 (the full-resolution highlight)
     comes on at rest and goes off for the dismiss: kept on through the morph it re-rendered every frame on WebKit — simulator D 09-24 21:47–21:49, 3 runs
     each, rAF frames in 800 ms: open 26–28 / close 31–33 with it vs 44–48 / 48 before; open 44–47 without it (2号 0924-白点 mo2.js) — its step at rest
     is ≤ 3 levels in light, ≤ 43 levels on 2519 px of the edge in dark (Chrome 394×2.75 capture, f3shot.py) */
  const glassFull = (g, on) => { if (!g || !g.copy) return; const tok = (g.full = (g.full || 0) + 1);
    if (!on) { g.w3.style.filter = ""; return; }   // the dismiss: f3 off, the rest of the chain and the stroke stay
    requestAnimationFrame(() => { if (g.full === tok) g.w3.style.filter = "url(#menu-glass-f3)"; }); };
  const glassMorph = (g) => { if (!g || !g.copy) return; g.copy.style.filter = "url(#menu-glass-f1)"; g.w2.style.filter = "url(#menu-glass-f2)";
    const p = takePressed(g, cur && cur.to); if (p) { g.stroke = p; followStroke(); return; }
    requestAnimationFrame(() => requestAnimationFrame(() => { if (cur && cur.glass === g && cur.panel && !g.stroke) { g.stroke = buildStroke(g, cur.panel, cur.to, R); followStroke(); } })); };   // the stroke one frame after the chain (the staging below); followStroke puts it on the moving box in the frame it is built
  /* the stroke built at the press (菜单-打开剩一帧, 验收 09-25 18:5x): the stroke filter's first render is one 45–57 ms frame on WebKit (simulator D, the GPU
     process's software FE*SoftwareApplier chain, sample 09-25 19:1x), two frames into the morph when built at the open. Built at the pointerdown on the value
     button instead, the render lands in the still press (nothing moves; the press dim is the only change) and the open reuses the layer. Hidden by the morph's
     own first-frame transform (the seed square, see seedRect: a 250-pt ring scaled by ≈ .07, a 0.1-px band) — not by opacity: taking opacity (.01 → 1) or
     z-index off at the open re-ran the filter (the same 45 ms at +118 ms), an off-screen layer was not painted until the open, a .01 scale re-rendered at the open;
     the seed transform then moves on 3D transforms only (followStroke). The copy sits under a disabled fieldset: WebKit's content-change observer drops the
     tap's click when content that responds to clicks (the page copy's buttons / selects) appears during the touch (WebCore page/cocoa/ContentChangeObserver.cpp
     isConsideredActionableContent → HTMLButton/Select/InputElement willRespondToMouseClickEvents = !isDisabledFormControl) — without it no menu opened (vP1).
     Simulator D 09-25 19:0x–19:3x, scratchpad fluD vP1–vP7 / one.sh. */
  let pressed = null;
  const pressKey = (th, mr, to) => `${th} ${mr.left} ${mr.top} ${mr.width} ${to.left} ${to.top} ${to.width} ${to.height}`;
  const dropPressed = () => { btnPreDrop(); if (!pressed) return; clearTimeout(pressed.t); pressed.el.remove(); pressed = null; };
  const takePressed = (g, to) => { if (!pressed || !to) return null; const { el, key } = pressed; clearTimeout(pressed.t); pressed = null; if (key === pressKey(g.theme, g.mr, to)) return el; el.remove(); return null; };
  const pressStroke = (b) => { dropPressed(); const sel = b.previousElementSibling, main = document.getElementById("app"); if (cur || !sel || sel.tagName !== "SELECT" || !main || reduce()) return;
    const h = [...sel.options].filter((o) => !o.hidden).length * 42 + 20, th = glassTheme(), k = glassKeys(th), mr = main.getBoundingClientRect(), to = restRect(b, h), f = seedRect(b, h);   // h: open()'s body height (hidden options skipped there too)
    const el = buildStroke({ copy: 1, theme: th, keys: k, mr }, null, to, R); if (!el) return;
    el.style.transform = `translate3d(${f.left + f.width / 2 - to.left - to.width / 2}px, ${f.top + f.height / 2 - to.top - to.height / 2}px, 0px) scale3d(${f.width / to.width}, ${f.height / to.height}, 1)`;
    pressed = { el, key: pressKey(th, mr, to), t: 0 }; };
  const pressEnd = (open) => { if (pressed) { clearTimeout(pressed.t); pressed.t = open ? setTimeout(dropPressed, 1000) : 0; if (!open) dropPressed(); } };   // lifted on the button: the click follows at once, a second's grace; else gone
  /* the morph's geometry (menu-open fix, simulator D 09-24 00:51–01:0x, mrun frame stamps + Timeline Paint rects): WebKit re-rendered the copy's whole url() filter
     region every frame the panel's left / top / width / height changed — its clip box moved (only the panel's box frozen gave frames: 15 in 700 ms vs 2–3; frozen size
     or frozen position alone, a fixed-size glass layer, no drop-shadow, no clip: all still 120–170 ms a frame). So while it morphs the panel stays on its rest box,
     unclipped, and the shape is a clip-path: the glass layer sits on a fixed box U (source ∪ target, plus the spring's first overshoot) cut by inset(… round r), the
     content layer moves by a transform and is cut the same way (14–15 frames in 700 ms). At rest the old styles come back (restStyles), so the menu paints as before. */
  const OVER = Math.exp(-APPEAR[0] * Math.PI / Math.sqrt(1 - APPEAR[0] ** 2));   // an underdamped spring's first overshoot per unit of travel (ζ .8: 1.52 %; DISMISS shares ζ)
  const boxOf = (s) => ({ left: s.left.x, top: s.top.x, width: s.width.x, height: s.height.x });
  /* the native layer path (数据 09-30, BOARD/随机模式菜单-逐帧差表-数据-0930.md ①②; probe rnd0930-motion.json, simulator A iOS 27.0, menurowal 三项 ×6):
     MagicMorphView #0 is ONE layer of the rest width (pres width 250 on every frame) whose own height runs 250 → 146 while a uniform scale runs
     17.17 / 250 → 1 (presInWindow / pres the same on x and y), both on the same progress p (every frame (250 − H) / 104 = (s − .0687) / .9313, open4
     p .422: H 206.1, s .462) — on screen w = 250·s, h = H·s. The page's springs ran the screen width and height straight from the 17.17 square
     (h ±24 pt off at mid-morph). p here is the width spring's progress (its open ζ .75 / .35, close .8 / .49 fit the probe's s to ≤ 7e-4). The
     centre x is p (every frame); the centre y is not a spring of p (open: past its end by 28 % at +150 ms; close: first 21 % the wrong way):
     CY_IN / CY_OUT are the probe's own centre-y fraction per 1/60 s from the p spring's start (median of 6 runs, start fitted per run, rms ≤ 4e-4),
     beyond the table 1 — 采样替代: 已查 rnd0930-motion.json + menu-motion-formula.md §8 (six springs morph / width / height / positionX / positionY /
     transform), 缺 the positionY driver (not read line by line). At rest and in reduce motion the springs' own box. */
  const CY_IN = [0.0, 0.129, 0.258, 0.4368, 0.6765, 0.9091, 1.0876, 1.204, 1.2641, 1.2801, 1.2657, 1.2332, 1.1927, 1.151, 1.1122, 1.0789, 1.0517, 1.0306, 1.015, 1.004, 0.9971, 0.9931, 0.991, 0.9903, 0.9906, 0.9914, 0.9926, 0.9938, 0.9951, 0.9962, 0.9972, 0.9981];
  const CY_OUT = [0.0, -0.1117, -0.1976, -0.193, -0.1225, -0.0119, 0.1181, 0.2527, 0.3821, 0.5027, 0.6093, 0.6966, 0.7682, 0.8268, 0.8739, 0.9112, 0.9403, 0.9627, 0.9796, 0.9921, 1.001, 1.0072, 1.0112, 1.0136, 1.0148, 1.0151, 1.0147, 1.0138, 1.0127, 1.0114, 1.0101, 1.0087, 1.0074, 1.0062, 1.0051, 1.0041, 1.0033, 1.0026, 1.0019];
  const cyAt = (tab, t) => { const i = Math.max(0, t) * 60, k = Math.floor(i); return k >= tab.length - 1 ? 1 : tab[k] + (tab[k + 1] - tab[k]) * (i - k); };
  /* pure (no cur): the per-frame path (shownBox) and a pre-sampled one (element.animate) both call these. hAt: the screen height for the screen width w
     of a menu resting at rest {width, height} (W-wide layer: height W → rest.height on p, uniform scale w / rest.width) — held on three menus (the
     two-row 104 and the capsule 167 of 0924 to ≤ .12 pt, xval.py). yAt: the centre y's fraction of its travel at t s on the p spring's clock, or null.
     The table is NOT general (数据 09-30 xval.py, leave-one-menu-out: hits ≤ .5 pt 29–64 %; the two-row menu peaks 1.11, three rows 1.28, the
     capsule 2.02): it is used for the 146-tall menu it was read on only (same menu, leave-one-run-out, reopens: median ≤ .3, max ≤ 4.4 pt); any other
     height keeps the old path (the centre on p) until the positionY driver is read */
  const CY_104 = { in: [0.0, 0.076, 0.2511, 0.4635, 0.7087, 0.9218, 1.0821, 1.1838, 1.2336, 1.244, 1.228, 1.1972, 1.1603, 1.1234, 1.09, 1.0616, 1.0389, 1.0216, 1.0093, 1.0005, 0.995, 0.9919, 0.9905, 0.9903, 0.9908, 0.9918, 0.9931, 0.9943, 0.9956, 0.9967, 0.9976, 0.9984], out: [0.0, -0.1737, -0.3474, -0.384, -0.3227, -0.2003, -0.047, 0.1155, 0.2724, 0.4151, 0.5397, 0.6448, 0.7315, 0.8012, 0.8564, 0.8995, 0.9326, 0.9577, 0.9763, 0.99, 0.9997, 1.0064, 1.0108, 1.0134, 1.0147, 1.0151, 1.0147, 1.014, 1.0129, 1.0116, 1.0103, 1.0089, 1.0077, 1.0064, 1.0053, 1.0043, 1.0035, 1.0027, 1.0021, 1.0015] };
  const CY_146U = { in: [0.0, 0.0747, 0.237, 0.4314, 0.6524, 0.8525, 1.0065, 1.1093, 1.1658, 1.1864, 1.1821, 1.1627, 1.1362, 1.1078, 1.0811, 1.0578, 1.0386, 1.0236, 1.0125, 1.0044, 0.9989, 0.9956, 0.9938, 0.9931, 0.9931, 0.9936, 0.9944, 0.9953, 0.9962, 0.9971, 0.9978, 0.9985], out: [0.0, -0.1224, -0.2537, -0.2732, -0.211, -0.0934, 0.0431, 0.1883, 0.3299, 0.459, 0.5724, 0.6685, 0.7481, 0.8127, 0.8642, 0.9047, 0.936, 0.9598, 0.9777, 0.9908, 1.0002, 1.0067, 1.0109, 1.0135, 1.0147, 1.015, 1.0147, 1.0139, 1.0128, 1.0115, 1.0102, 1.0088, 1.0075, 1.0063, 1.0052, 1.0042, 1.0034, 1.0026, 1.002, 1.0015] };
  const CY_188 = { in: [0.0, 0.1241, 0.2482, 0.4544, 0.7012, 0.9329, 1.1095, 1.2237, 1.2809, 1.2936, 1.2758, 1.2403, 1.1971, 1.1533, 1.1131, 1.0786, 1.0507, 1.0293, 1.0135, 1.0029, 0.9955, 0.9912, 0.9892, 0.9887, 0.9892, 0.9902, 0.9916, 0.9931, 0.9945, 0.9958, 0.997, 0.9979, 0.9987], out: [0.0, -0.1254, -0.2475, -0.2714, -0.2061, -0.0919, 0.0479, 0.1939, 0.3349, 0.4629, 0.5754, 0.6707, 0.7497, 0.8138, 0.865, 0.9052, 0.9363, 0.9601, 0.9779, 0.991, 1.0004, 1.0068, 1.011, 1.0136, 1.0148, 1.0151, 1.0147, 1.0139, 1.0128, 1.0115, 1.0102, 1.0088, 1.0075, 1.0063, 1.0052, 1.0042, 1.0034, 1.0026, 1.002, 1.0015] };
  const CY_230 = { in: [0.0, 0.129, 0.258, 0.4186, 0.6574, 0.8828, 1.0568, 1.1725, 1.235, 1.2549, 1.2451, 1.2174, 1.1812, 1.1432, 1.1075, 1.0764, 1.0508, 1.0309, 1.0159, 1.0053, 0.9982, 0.9938, 0.9915, 0.9906, 0.9907, 0.9915, 0.9925, 0.9938, 0.995, 0.9961, 0.9971, 0.998, 0.9987], out: [0.0, -0.1118, -0.2263, -0.2315, -0.1639, -0.0506, 0.0845, 0.225, 0.36, 0.4831, 0.5907, 0.6822, 0.7582, 0.82, 0.8694, 0.9084, 0.9385, 0.9616, 0.9789, 0.9917, 1.0008, 1.0071, 1.0112, 1.0137, 1.0148, 1.0151, 1.0147, 1.0139, 1.0127, 1.0115, 1.0101, 1.0088, 1.0075, 1.0063, 1.0052, 1.0042, 1.0033, 1.0026, 1.002, 1.0015] };
  const CY_272 = { in: [0.0, 0.06, 0.2096, 0.3884, 0.5882, 0.7719, 0.9181, 1.0216, 1.0852, 1.117, 1.1257, 1.1195, 1.105, 1.0869, 1.0684, 1.0514, 1.0367, 1.0247, 1.0153, 1.0082, 1.0031, 0.9997, 0.9975, 0.9963, 0.9958, 0.9958, 0.9961, 0.9965, 0.9971, 0.9976, 0.9981], out: [0.0, -0.0853, -0.1733, -0.1642, -0.093, 0.016, 0.1434, 0.2746, 0.4, 0.5143, 0.6144, 0.6999, 0.771, 0.8292, 0.8759, 0.9129, 0.9417, 0.9638, 0.9805, 0.9927, 1.0015, 1.0075, 1.0115, 1.0138, 1.0149, 1.0151, 1.0146, 1.0138, 1.0126, 1.0113, 1.01, 1.0086, 1.0074, 1.0062, 1.0051, 1.0041, 1.0033, 1.0025, 1.0019] };
  const CY_314 = { in: [0.0, 0.0844, 0.1969, 0.3672, 0.5654, 0.7508, 0.8996, 1.0067, 1.0741, 1.1093, 1.121, 1.1173, 1.1045, 1.0877, 1.07, 1.0533, 1.0387, 1.0266, 1.017, 1.01, 1.0044, 1.0007, 0.9983, 0.9969, 0.9962, 0.996, 0.9962, 0.9966, 0.9971, 0.9976, 0.9981], out: [0.0, -0.0648, -0.1243, -0.1061, -0.0315, 0.0745, 0.1953, 0.3186, 0.4358, 0.5424, 0.6361, 0.716, 0.7828, 0.8376, 0.8818, 0.9169, 0.9445, 0.9657, 0.9817, 0.9936, 1.0021, 1.0079, 1.0117, 1.0139, 1.0149, 1.0151, 1.0146, 1.0137, 1.0125, 1.0112, 1.0099, 1.0085, 1.0073, 1.0061, 1.005, 1.004, 1.0032, 1.0025, 1.0019] };
  const CY = { 104: CY_104, 146: { in: CY_IN, out: CY_OUT }, "146u": CY_146U, 188: CY_188, 230: CY_230, 272: CY_272, 314: CY_314 };   // 数据 09-30 buildcy.py (r4-first3more + xfall + r5 + r6, 5–16 native runs per height; leave-one-run-out median ≤ .2 pt) — 采样替代 as 146. "146u" = the three-row menu opening upward (no room below). Dismiss tables: only the runs whose centre first moves the wrong way (AnimationKit Parameters.kick applied — 22 of 31 dismisses; the other 9 have no kick, why not read: Parameters.init zeroes kick on a Bool, 0x1de41d42c) and not the process's first dismiss
  const hAt = (w, rest) => { const q = seqSide(rest.height), p = (w - q) / (rest.width - q); return Math.max(0, (rest.width + (rest.height - rest.width) * p) * w / rest.width); };
  const yAt = (phase, t, rest, up) => { const T = CY[Math.round(rest.height) + (up ? "u" : "")]; return T ? cyAt(phase === "in" ? T.in : T.out, t) : null; };   // up: opening upward, its own table where read ("146u")
  const shownAt = (s, t, phase, A, T, to) => { const w = s.width.x, h = hAt(w, T), B = phase === "in" ? T : to, ya = A.top + A.height / 2, yb = B.top + B.height / 2;   // pure: s at t s on the p spring's clock (外观: the pre-sampled open / dismiss call it per sample)
    const up = T.top + T.height / 2 < (phase === "in" ? A : B).top;   // opening upward (no room below): the tables were read opening down — on p there
    const f = yAt(phase, t || 0, T, up) ?? (s.width.x - A.width) / ((B.width - A.width) || 1);   // no table: the centre on the width spring's progress, as before
    return { left: s.left.x, top: ya + (yb - ya) * f - h / 2, width: w, height: h }; };
  const shownBox = (s) => (!cur || cur.reduced || !cur.U ? boxOf(s) : shownAt(s, cur.t, cur.phase, cur.from, cur.rest, cur.to));
  const padY = (U, a, b) => { const d = Math.ceil(0.3 * Math.abs(b.top + b.height / 2 - a.top - a.height / 2)); return { ...U, top: U.top - d, height: U.height + 2 * d }; };   // the centre y's overshoot (28 % open / 21 % close of its travel): inside U from the start, no mid-morph setMorph
  const morphBox = (a, b) => { const l = Math.min(a.left, b.left), t = Math.min(a.top, b.top), r = Math.max(a.left + a.width, b.left + b.width), bt = Math.max(a.top + a.height, b.top + b.height);
    const m = 2 + Math.ceil(OVER * Math.max(Math.abs(a.left - b.left) + Math.abs(a.width - b.width), Math.abs(a.top - b.top) + Math.abs(a.height - b.height)));   // an edge travels ≤ |Δleft| + |Δwidth|
    return { left: Math.floor(l - m), top: Math.floor(t - m), width: Math.ceil(r - l + 2 * m), height: Math.ceil(bt - t + 2 * m) }; };
  const setMorph = (U) => { const p = cur.panel.style, T = cur.rest, g = cur.glass; cur.U = U;
    p.left = T.left + "px"; p.top = T.top + "px"; p.width = T.width + "px"; p.height = T.height + "px"; p.overflow = "visible"; p.borderRadius = "";
    if (g) { const l = g.layer.style; l.inset = "auto"; l.left = U.left - T.left + "px"; l.top = U.top - T.top + "px"; l.width = U.width + "px"; l.height = U.height + "px"; l.borderRadius = "0";
      g.outer.style.transform = `translate(${g.mr.left - U.left}px, ${g.mr.top - U.top}px)`; } };
  const restStyles = () => { const p = cur.panel.style, s = cur.s, g = cur.glass; cur.U = null; p.overflow = ""; cur.body.style.transform = ""; cur.body.style.clipPath = "";
    cur.body.style.opacity = cur.body.style.filter = "";   // settled() stops within .001 of p = 1: the last frame's blur(0.001px) left on the body rendered as a visible blur on WebKit once the glass copy was filtered again (simulator D 09-24 11:3x: text edge gradient 27 with it, 248 with blur(0px))
    p.left = s.left.x + "px"; p.top = s.top.x + "px"; p.width = s.width.x + "px"; p.height = s.height.x + "px"; p.borderRadius = s.r.x + "px";
    if (g) { const l = g.layer.style; l.inset = l.left = l.top = l.width = l.height = l.borderRadius = l.clipPath = ""; }
    placeGlass(g, s); };
  const hideTail = (q) => { if (cur.phase === "out" && q <= 0 && !cur.tailHidden) { cur.tailHidden = true; cur.panel.style.visibility = "hidden"; if (cur.glass && cur.glass.stroke) cur.glass.stroke.style.visibility = "hidden";
    if (cur.anims) for (const a of cur.anims.list) a.cancel(); } };   // hidden, nothing of the panel is on screen: its animations are dropped and nothing is written to the strip — kept, they fail compositing (compositeFailed 131072) and the old per-frame writes on the hidden panel cost as much (gate3 04:3x mlz: close PACU 42–47 either way, 21–22 without)
  const apply = () => { if (cur.anims) { hideTail(cur.s.p.x); if (!STROKE_WAAPI) followStroke(); return; }   // the open / the dismiss run on their Web Animations (animOpen / playOut): only the two blur radii move here
    const p = cur.panel.style, s = cur.s, T = cur.rest; let U = cur.U; p.opacity = String(Math.max(0, Math.min(1, s.a.x)));
    const G = shownBox(s); if (G.left < U.left || G.top < U.top || G.left + G.width > U.left + U.width || G.top + G.height > U.top + U.height) setMorph(U = morphBox(U, G));   // past U (a dismiss from a panel still moving): grow it, one repaint
    const x = G.left - U.left, y = G.top - U.top, w = G.width, h = G.height, r = cornerNow(s);   // ≥ 0: a negative round() makes the whole clip-path invalid and the old one stays
    if (cur.glass) cur.glass.layer.style.clipPath = `inset(${y}px ${U.width - x - w}px ${U.height - y - h}px ${x}px round ${r}px)`;
    const bs = cur.body.style; bs.transform = `translate(${G.left - T.left}px, ${G.top - T.top}px)`; bs.clipPath = `inset(0 ${cur.bw - w}px ${cur.bh - h}px 0 round ${r}px)`;   // the content at the shape's corner, cut by the same shape
    /* G22 (NATIVE-GAP G22 driver ①, AnimationKit 0x1de425df0, crossBlurWhenMorphing 1 read by probe G22 19:05): the shown layer (the menu content) has opacity p and a
       gaussianBlur inputRadius 4(1 − p) (σ = inputRadius, NATIVE-GAP G8); p's overshoot above 1 is clamped by CSS opacity and a blur cannot be negative */
    const b = cur.body.style, q = s.p.x; b.opacity = q >= 1 ? "" : String(Math.max(0, q)); b.filter = cur.xf ? "" : q >= 1 ? "" : `blur(${(4 * (1 - q)).toFixed(3)}px)`; if (cur.xf) xfSet(q);   // cur.xf: the blur is the copies' cross-fade (xfBuild)
    /* the hidden layer = the button (the source, hidden by the morph and shown through its copy): its own progress runs 1 → 0 on the same spring (the g22 blur table:
       the two layers' presented opacities sum to 1 on every frame, 6.71 s …), so opacity 1 − p, radius 4p; at rest open it stays at 0, the dismiss brings it back */
    if (!cur.reduced && cur.anchor) { const a = cur.anchor.style; a.opacity = q <= 0 ? "" : String(Math.max(0, Math.min(1, 1 - q))); a.filter = (cur.xf && cur.xf.btn) || q <= 0 ? "" : `blur(${(4 * Math.max(0, q)).toFixed(3)}px)`; btnRaise(cur.anchor); btnMorph(cur.anchor, q, cur.move); }
    /* the tail is gone once the button is back (p ≤ 0): native shows nothing of #0 around the button from +350 ms of the dismiss on (nat.mov, 2号 0924-白点
       halo2.png, frames 3870–4120 ms), while the page's 17-pt tail kept its glass / rim / stroke / drop-shadow under the raised button until the strip at +800 ms
       (≤ 8 levels through the title, w7 vs w8 Chrome 394×2.75). Hidden at the first p ≤ 0 frame (+364 ms, w8 DOM); the spring runs on to its settle and strips
       as before. The button-area change that goes on to ~+700 ms is the button's own overshoot (scale ≤ 1.0113 at +450 ms, DISMISS ζ .8 / .49), as native's
       (its title 48.67 → 49.33 pt wide at +392–485 ms, back by +517 ms, nat.mov). 近似: 已查 菜单-圆角淡出变宽-数据-0924.md 表 1 (#0 view and PivotView α stay 1 to the end)，缺 why native's glass draws no
       shadow / rim for the tail inside the button */
    /* dark: the dismiss tail's glass is 12–17 levels brighter than the page and shows through the button title's gaps from +171 ms (验收 0924, dot-dark.png; native
       dark stays within ±2 levels of the rest button from +193 ms, 菜单-复核-数据-0924.md item 1): on the dismiss the glass (w3) goes out ahead of the shown layer,
       α p². Background pixels in the button's 24-pt box over the rest frame, Chrome 394×2.75 dark (2号 0924-暗圆 gap.py): before 41–44 levels at +171–286 ms;
       α p 23–30 with the disc still seen to +246 ms (dotF-dark.png); α p² 21–25 (dotS-dark.png), the same as the glass taken out entirely, 19–25 (dZ.json: the
       rest is the button's own blur 4p, as native's PivotView). On WebKit with w3 not a layer of its own (f3 waits for rest, glassFull) the fade costs no frame:
       close 46–47 frames / 800 ms, the only > 25 ms one the f3-off step at +20 ms, as without it (simulator D 22:4x, 2号 mo2.js). Not the stroke: its opacity cost
       one 232 ms frame (d1.json; no filter re-run while it only moves) and hiding it changed nothing (dZ2.json). 近似: 已查 菜单-圆角淡出变宽-数据-0924.md 表 1，缺 the
       reason native's small tail matches the page */
    if (cur.phase === "out" && cur.glass) { const g = cur.glass, ga = q >= 1 ? "" : String(Math.max(0, q) ** 2); g.layer.style.opacity = ga; }   // on the layer (w3 its only child): WebKit drew nothing of the glass under an opacity < 1 on w3 (#10, simulator B 09-29: w3 α .95 at rest → the fill gone, the layer α .95 → drawn at .95)
    hideTail(q);
    placeGlass(cur.glass, s, U); followStroke(); };
  /* the stroke comes on before the tail has settled (see tick): it is built on the rest box, so until rest it is moved and scaled onto the panel's box by a transform
     (the box ratio, no re-render of its filter); the corner differs from the panel's by the tail's r change (≤ 1.1 pt at the diagonal: first open R 125 − 93·1.028) */
  /* 3D: with a 2D transform WebKit re-ran the stroke's filter when the transform came off at rest (a 47–52 ms frame at +800 ms) and once early in the dismiss
     (+170 ms, 46–59 ms; 45247df on); translate3d / scale3d and translate3d(0, 0, 0) at rest keep it one composited layer — no re-render, the rest frame the
     same (areacmp over the open menu vs 815c885: SAME). Simulator D 09-25 18:2x, scratchpad fluD vF (no follow: both gone) / vH */
  /* will-change (Chrome, 数据 09-29 14:2x): Chrome re-rasters a layer whenever its transform scale changes unless it has will-change: transform
     (developer.chrome.com/blog/re-rastering-composite) — the stroke's scale3d re-rastered it every frame of the open / dismiss, its page copy through the
     url() filter each time: 390–413 ms of raster per open, 72–84 per close (mlayers.py, 394×790 dpr 3.25, CPU ×4); Android flu records, warm: 33–75 ms
     frames through every open (12 / 12) and close (10 / 11). With will-change from the build: 8–18 / 5–6 ms. At rest it comes off: with it kept, Chrome
     keeps the raster translation it picked mid-morph (cc/layers/picture_layer_impl.cc CanRecreateHighResTilingForLCDTextAndRasterTransform: "Keep the non-ideal raster
     translation unchanged … AffectedByWillChangeTransformHint()"), and the resting ring came out resampled, 16–20 levels darker (areacmp DIFFERENT, 76
     cells ≤ ΔE 3.2); off at rest the rest frame is the old one pixel for pixel, and it goes back on with the dismiss's first morph frame (scale 1,
     aligned). Mid-morph frames: sharpness cells 0 (strokemid.py). WebKit keeps the layer composited by the 3D transform either way (the note above).
     Native basis (Apple, Core Animation Programming Guide › Core Animation Basics › The Layer-Based Drawing Model, developer.apple.com/library/archive/
     documentation/Cocoa/Conceptual/CoreAnimation_guide/CoreAnimationBasics/CoreAnimationBasics.html): "a layer captures the content your app provides and
     caches it in a bitmap … When a change triggers an animation, Core Animation passes the layer’s bitmap and state information to the graphics hardware,
     which does the work of rendering the bitmap using the new information" — a native layer's scale is drawn from its cached bitmap, not redrawn; will-change
     makes Chrome do the same. */
  const followStroke = () => { const g = cur && cur.glass; if (!g || !g.stroke) return; const st = g.stroke.style; if (cur.anims && STROKE_WAAPI) { animStroke(g.stroke); return; }
    if (!cur.U) { st.transform = "translate3d(0px, 0px, 0px)"; st.willChange = "auto"; return; }
    st.willChange = "transform"; const G = shownBox(cur.s), T = cur.rest; st.transform = `translate3d(${G.left + G.width / 2 - T.left - T.width / 2}px, ${G.top + G.height / 2 - T.top - T.height / 2}px, 0px) scale3d(${G.width / T.width}, ${G.height / T.height}, 1)`; };
  const settled = (goal, S = cur.s) => Object.keys(goal).every((k) => k === "p" ? Math.abs(S.p.x - goal.p) < 0.001 && Math.abs(S.p.v) < 0.02 : Math.abs(S[k].x - goal[k]) < 0.05 && Math.abs(S[k].v) < 1);   // p is a 0…1 opacity: .05 would end the loop on a visible step
  /* the open on the compositor (外观 09-30, BOARD/玻璃卡顿-0929.md:440–463, evidence/数据-0929-Layerize/lzsum.txt): ANY per-frame inline write of transform / opacity /
     filter / clip-path made Chrome rebuild its layers (PaintArtifactCompositor::Update) every frame of the open — paint_property_tree_builder.cc:5072 → :5079 for any change
     above kChangedOnlyCompositedValues; a transform takes the direct path only under a running compositor animation (transform_paint_property_node.h:343–348); with all four
     gone 2 rebuilds per open, with Web Animations on transform / opacity / clip-path inset(… round) 4–5. So the open's geometry is sampled once at the open: the same springs
     (APPEAR / CROSS, the same start x / v) stepped at PRE_DT = 1/120 s with Motion.spring (the closed form: each step is x(t) exactly) up to the same settled() rule, r derived
     per step as tick does (openR on the step before), and every element's value written as apply() writes it — then played by element.animate, linear between the samples,
     all from one startTime = cur.t0 (the tick's own clock origin: Menu.state()'s t and the animations' local time are the same number). tick keeps the spring math every
     frame (Menu.state(), settled(), restStyles, glassFull read cur.s) and writes nothing while the animations run (apply: only hideTail). U is the box over the whole sampled path (setMorph once).
     Blur: a radius that changes moves the filter's output bounds → a full rebuild every frame even as a compositor animation (effect_paint_property_node.cc:24;
     wa_filt 48–50 per open; an SVG stdDeviation per frame 14, here 26–34 with both) — so it is a cross-fade of static blurs (xfBuild below, 近似). At settle: the goal state inline (the old apply), restStyles, then the animations cancelled — one task, no
     frame between. A dismiss during the open: the current state inline, then cancelled; the dismiss and reduce motion run the old per-frame path unchanged */
  const PRE_DT = 1 / 240;   // the keyframes are linear between samples: at 1 / 120 the button clip (35 pt × p) was off by rms .01 pt against the spring (accept-menu); 1 / 240 quarters it
  /* the blur without a per-frame filter (acceptance 09-30 02:27): a radius that changes moves the filter's output bounds and rebuilds the layers every frame — as an
     SVG stdDeviation (26–34 per open with it, 7 without) and as a Web Animations CSS blur alike (mlz v-wblur: the body's alone 13–14 per open vs 7).
     近似: each blurred layer is a ladder of copies under STATIC blurs (XF_L radii), α on the compositor: the body (radius 4(1 − p)), the button (radius 4p);
     a frame weights only the two levels next to the radius, linearly (clamped: p's overshoot is no blur, as the CSS clamp). The levels are summed with
     mix-blend-mode plus-lighter inside an isolated group (weights sum to 1, premultiplied), then the group's own opacity (mid: p, the button: 1 − p).
     What it does not keep: two neighbouring Gaussians mixed are not the Gaussian in between (areacmp in the README frz3). The copies are clones made at
     the open (aria-hidden, inert, no pointer events) and stay until the strip; the button's by children over its own content (its text node is view.js's:
     the button's own text and chevron are made transparent, the children draw them) */
  /* blur ladder: static copies at each XF_L radius; a frame cross-fades only the two levels next to the current radius (r 2.6: 2.5 px 0.8 + 3 px 0.2); 9 levels: 5 left text-body ghosting at 100 ms (README frz3) */
  /* XF_BTN false (acceptance 03:4x ①): the button keeps the old per-element CSS blur 4p (a WAAPI filter keyframe, main thread): its copies drew a hard-edged fill */
  const XF_BTN = true;   // ① measured 09-30 03:43: PACU per open 35 / 42 vs 12 / 12 with the ladder -> the ladder stays; the button box keeps ~25 cells at 100 ms (README)
  /* 4.5: neither radius is capped above in the old apply (blur(4p), blur(4(1 − p))): the open's p overshoot (≤ 1.03, the button) and the dismiss's undershoot
     (the body) need a level past 4 */
  const XF_L = [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5], xfW = (r, L = XF_L) => { const w = L.map(() => 0), n = L.length - 1; r = Math.max(0, Math.min(L[n], r));
    let k = 0; while (k < n - 1 && r > L[k + 1]) k++; const t = (r - L[k]) / (L[k + 1] - L[k]); w[k] = 1 - t; w[k + 1] = t; return w; };
  const xfBody = (q) => xfW(4 * (1 - Math.min(1, q))), xfBtn = (q) => xfW(4 * Math.max(0, q));   // body r = 4(1 − p) (0 past p 1, as the old clamp), button r = 4p
  const xfHost = (a) => { let host = a.querySelector(":scope > .menu-btn-xf"); if (!host) { host = document.createElement("span"); host.className = "menu-btn-xf"; host.setAttribute("aria-hidden", "true"); host.style.display = "contents"; host.attachShadow({ mode: "open" }); a.appendChild(host); } return host; };
  /* the hosts go into every menu button at load (外观 09-30 06:1x): inserted at the first press, the host's insertion was #app's one light-DOM change, and
     WebKit's first press stalled 294 ms and the close after it 214 ms (the pocket rebuild; simulator B, first load). At the load event topbar.js's pocket
     observer is not yet watching (it starts at its first build, an idle round after load), so these insertions reach no one; a button rendered later
     gets its host at its first press, as before */
  const xfHostsWarm = () => { if (!XF_BTN) return; for (const b of document.querySelectorAll("main .menubtn")) xfHost(b); };
  const xfBtnMake = (a) => { const cs = getComputedStyle(a), box = `position:absolute;left:0;top:0;right:0;bottom:0;box-sizing:border-box;pointer-events:none;padding:${cs.padding};background:${cs.backgroundImage} ${cs.backgroundPosition} / ${cs.backgroundSize} ${cs.backgroundRepeat};-webkit-text-fill-color:currentcolor;text-align:${cs.textAlign};display:flex;flex-direction:column;justify-content:center;overflow:${cs.overflow};white-space:${cs.whiteSpace};text-overflow:${cs.textOverflow}`;
      const host = xfHost(a);   // the copies live in the shadow root of one host kept in the button: topbar.js's pocket observer watches #app's light DOM (childList, subtree) and rebuilt the pocket (a clone of the page, 150–215 ms on simulator F) after every close when the copies went in and out of the button (外观 09-30 F: 20 of 20 closes, main 0 of 10); a shadow tree's mutations are not the light DOM's, so only the host's first insertion reaches it. display: contents lays the copies out as the button's own children (as before), inheritance follows the flat tree
      const text = a.textContent, root = host.shadowRoot, mk = (k, f, r) => { const e = document.createElement("span"); e.className = k; e.dataset.r = r; e.textContent = text; e.style.cssText = box + f; root.appendChild(e); return e; };   // read once: a.textContent grows with each copy appended (every copy after the first held the label k times)
      const btn = XF_L.map((r) => (r ? mk("menu-btn-bl", `;filter:blur(${r}px);mix-blend-mode:plus-lighter`, r) : mk("menu-btn-sh", "", 0)));
      a.style.isolation = "isolate"; a.style.webkitTextFillColor = "transparent"; a.style.backgroundImage = "none"; a.style.overflow = "visible"; return btn; }   // the old blur(4p) is over the button AFTER its overflow clip: each copy clips its own content (the button's overflow) and its blur spills past the box as the old one did — the button's own overflow: hidden cut that halo flat top and bottom (frz3 100 ms: the button-box cells)
  /* the button's copies at the press (外观 09-30 05:4x): built on pointerdown with the rest weights (level 0 at 1, the blurred ones at 0 — not painted), so the
     press frame pays their first paint (the copy's background image decoded 0.93 ms, gate5 r1-new click frame: button paint 1.83 ms vs main 0.01) and the
     click frame only animates them; a press that does not open drops them (dropPressed: the next press / the grace timeout / hidden) */
  let btnPre = null;
  const btnPreDrop = () => { const p = btnPre; if (!p) return; btnPre = null; if (cur && cur.anchor === p.a) return; xfClear(p.a, { btn: p.btn }); if (p.pos) p.a.style.position = ""; };
  const btnPreMake = (b) => { btnPreDrop(); if (!XF_BTN || cur || reduce()) return; const pos = getComputedStyle(b).position === "static"; if (pos) b.style.position = "relative";
    const btn = xfBtnMake(b), w = xfBtn(0); btn.forEach((e, k) => (e.style.opacity = String(w[k]))); btnPre = { a: b, btn, pos }; };
  const takeBtnPre = (a) => { const p = btnPre; if (!p || p.a !== a || !p.btn.every((e) => e.isConnected)) { btnPreDrop(); return null; } btnPre = null; return p.btn; };
  const xfBuild = (c, mid, inner) => { mid.style.position = "relative"; mid.style.isolation = "isolate";
    const body = [inner, ...XF_L.slice(1).map((r) => { const bl = inner.cloneNode(true); bl.className = "menu-body-bl"; bl.dataset.r = r; bl.setAttribute("aria-hidden", "true"); bl.inert = true;
      bl.style.cssText = `position:absolute;left:0;top:0;width:100%;pointer-events:none;filter:blur(${r}px);mix-blend-mode:plus-lighter`;
      const fs = document.createElement("fieldset"); fs.disabled = true; fs.style.display = "contents"; fs.append(...bl.childNodes); bl.appendChild(fs);   // rows under a disabled fieldset, as the stroke's page copy (see pressStroke)
      mid.appendChild(bl); return bl; })];
    /* 外观 09-30 06:3x: each copy is the rows' clone — <button>s, content that responds to clicks — and a copy's opacity goes 0 → > 0 whenever the radius
       reaches its level, all through the open. A scrim tap in the open then lost its click on WebKit (ContentChangeObserver: actionable content appeared
       at the tap's synthetic mousemove; simulator F n6 / n8 / n9: mouseover + mousemove on .menu-scrim, no mousedown / click). Measured with a copy
       flipped 0 → .5 inside the scrim tap's mousemove on a settled menu (rwi/harness.js): the rows' copy dropped the click (h1), the same copy with its
       buttons made non-buttons kept it (h4), the button's copy (spans) kept it (h3). Disabled, the buttons are not actionable (willRespondToMouseClickEvents
       = !isDisabledFormControl); :disabled matches but not index.html's button[disabled] (opacity .45), the rows keep their look */
    const xf = { body, btn: null }, a = XF_BTN ? c.anchor : null;
    if (a) xf.btn = takeBtnPre(a) || xfBtnMake(a);
    c.xf = xf; };
  const xfClear = (a, xf) => { if (!xf || !a) return; if (xf.btn) xf.btn.forEach((e) => e.remove()); a.style.isolation = a.style.webkitTextFillColor = a.style.backgroundImage = a.style.overflow = ""; };
  const xfSet = (q) => { const x = cur.xf; if (!x) return; const wb = xfBody(q); x.body.forEach((e, k) => (e.style.opacity = String(wb[k]))); if (x.btn) { const wa = xfBtn(q); x.btn.forEach((e, k) => (e.style.opacity = String(wa[k]))); } };   // the old path's static weights (settle / an interrupting dismiss / the hold frame)
  const animOpen = () => { const c = cur; if (c.reduced || !Element.prototype.animate) return;
    const S = JSON.parse(JSON.stringify(c.s)), goal = c.goalIn, sim = { s: S, first: c.first, turn: null, t: 0, tPrev: 0, rest: c.rest }, path = [];
    for (let i = 0; i < 2400; i++) { if (i) { const pPrev = S.p.x; for (const k of Object.keys(goal)) if (k !== "r") Motion.spring(S[k], goal[k], k === "p" ? CROSS : APPEAR, PRE_DT); sim.tPrev = sim.t; sim.t = i * PRE_DT; S.r.x = openR(sim, pPrev); S.r.v = 0; }
      const done = i && settled({ ...goal, r: S.r.x }, S) && (sim.first || S.r.x === R); if (done) for (const k of Object.keys(goal)) S[k].x = goal[k];   // the last sample ON the goal, as the settle writes it
      const G = shownAt(S, sim.t, "in", c.from, c.rest, c.to); path.push({ ...G, r: Math.max(0, Math.min(S.r.x * G.width / W, G.width / 2, G.height / 2)), a: S.a.x, q: S.p.x }); if (done) break; }   // the box shownBox / cornerNow (rl) give at that sample: 数据's layer path (hAt / yAt)
    /* U from morphBox(start, rest) grown over the sampled path, not open()'s padY box: the path covers the centre-y overshoot exactly, and the padded U
       (30 % of the travel above and below) put the open back to a rebuild every frame (gate3 04:28, mlz: open PACU 34 / 39 with it, 18 / 20 without) */
    let U = morphBox(c.from, c.rest); for (const b of path) if (b.left < U.left || b.top < U.top || b.left + b.width > U.left + U.width || b.top + b.height > U.top + U.height) U = morphBox(U, b);
    setMorph(U); apply();   // the overshoot past morphBox's margin: U grown once for the whole path (was: per frame in apply)
    c.body.style.filter = "";   // the open's first apply() wrote blur(4px) on the body: the blur is the inner wrapper's now
    const A0 = {}, T = c.rest, g = c.glass;
    /* the panel's drop-shadow (menu.css .menu.morph): a filter's output bounds follow its content, so the body's transform animation moving under it rebuilt the layers
       every frame it moved (effect_paint_property_node.cc:24; mlz 09-30 02:0x: body transform alone PACU every frame 60–225 ms, 13 per open; with the panel's filter
       off 3; overflow: clip on the panel did not help, 11–13). For the open the shadow is on a box around the glass layer only (.menu-glass-sh, absolute on the panel's
       box, so the layer's coordinates stay): the shape cuts the glass and the body alike and the body lies inside it, so the shadow of the glass is the panel's.
       The layer is moved in the open's own task, before its first paint. At the settle / an interrupting dismiss the panel's own filter comes back (unanim) */
    /* acceptance 09-30 03:4x: the box is not shipped — the panel keeps its own drop-shadow (PACU per open 12 / 12 with it, README frz3); c.sh stays unset */
    const mid = document.createElement("div"), inner = document.createElement("div"); mid.className = "menu-body-op"; inner.className = "menu-body-in"; while (c.body.firstChild) inner.appendChild(c.body.firstChild); mid.appendChild(inner); c.body.appendChild(mid); c.inner = inner;   // block boxes: the items' layout the same
    /* three nodes: the body's transform + clip-path, mid's opacity, inner's url() blur — an opacity animation on the node that also runs the clip-path animation
       rebuilt the layers every frame while it moved (mlz 09-30 02:0x, variant without blur / button: PACU every frame 60–225 ms = while p < 1, then none to the settle) */
    c.mid = mid; c.sh = A0.sh; xfBuild(c, mid, inner); c.anchor && (c.anchor.style.filter = ""); playAll(c, { ...A0, list: [], path, T, st: null, t0: c.t0 }, U, false); };
  /* the sampled path's keyframes, each element's value written as apply() writes it; out: the dismiss adds the glass layer's α p² (see apply) */
  /* the keyframes: only the samples a straight line between kept ones cannot stand in for (every field within KF_EPS of the sampled value) — the
     animate() calls with every 1/240 s sample (157 keyframes × 26 effects) were 8–17 ms of the click task (probe 09-30 05:0x) */
  const KF_EPS = { left: 0.01, top: 0.01, width: 0.01, height: 0.01, r: 0.01, q: 1e-4, a: 1e-4 };
  const thin = (P) => { const n = P.length - 1; P.forEach((b, i) => (b.o = n ? i / n : 1)); if (n < 2) return P; const out = [P[0]]; let k = 0;
    const fits = (j) => { for (let i = k + 1; i < j; i++) { const f = (i - k) / (j - k); for (const key in KF_EPS) if (Math.abs(P[k][key] + (P[j][key] - P[k][key]) * f - P[i][key]) > KF_EPS[key]) return false; } return true; };
    while (k < n) { let j = k + 2; while (j <= n && fits(j)) j++; k = j - 1; out.push(P[k]); } return out; };
  const playAll = (c, A, U, out) => { const n = A.path.length - 1, dur = n * PRE_DT * 1000, path = (A.kf = thin(A.path)), T = A.T, m = c.move, off = (i) => path[i].o, g = c.glass, mid = c.mid;
    /* clip-path always in an effect of its own (中继二 09-30, BOARD/evidence/中继二-0930-收起重建: clip-path with another property in one KeyframeEffect is
       compositeFailed 8192 unsupportedProperties [clip-path], the whole effect on the main thread — the glass's clip + α p² rebuilt the dismiss every frame) */
    const go = (el, frames) => { const a = el.animate(frames, { duration: dur, easing: "linear", fill: "forwards" }); a.startTime = A.t0; A.list.push(a); };
    const play = (el, frames) => { if (!el) return; const other = frames.some((f) => Object.keys(f).some((k) => k !== "offset" && k !== "clipPath"));
      if (!other || !frames.some((f) => f.clipPath != null)) { go(el, frames); return; }
      go(el, frames.map((f) => ({ offset: f.offset, clipPath: f.clipPath }))); go(el, frames.map(({ clipPath, ...f }) => f)); };
    if (path.some((b) => b.a !== path[0].a)) play(c.panel, path.map((b, i) => ({ offset: off(i), opacity: String(Math.max(0, Math.min(1, b.a))) })));
    if (g) play(g.layer, path.map((b, i) => { const x = b.left - U.left, y = b.top - U.top, f = { offset: off(i), clipPath: `inset(${y}px ${U.width - x - b.width}px ${U.height - y - b.height}px ${x}px round ${b.r}px)` }; if (out) f.opacity = String(b.q >= 1 ? 1 : Math.max(0, b.q) ** 2); return f; }));
    play(c.body, path.map((b, i) => ({ offset: off(i), transform: `translate(${b.left - T.left}px, ${b.top - T.top}px)`, clipPath: `inset(0 ${c.bw - b.width}px ${c.bh - b.height}px 0 round ${b.r}px)` })));
    c.body.style.opacity = ""; play(mid, path.map((b, i) => ({ offset: off(i), opacity: String(b.q >= 1 ? 1 : Math.max(out ? 0 : 0.001, b.q)) })));
    /* the open's floor .001, not 0 (外观 09-30 06:5x): mid holds the real rows (<button>s with click handlers), and WebKit's ContentChangeObserver takes an
       element going from opacity 0 (isVisuallyHidden: opacity isTransparent) to visible with clickable descendants, at a tap's synthetic mousemove, as a
       hover menu and drops the click (ContentChangeObserver.cpp isVisuallyHidden / isConsideredActionableContent / StyleChangeScope). On the compositor the
       open's first keyframe 0 can still be mid's style when a scrim tap restyles it (simulator F r6: 131 ms, no click; k1: mid set to 0 on a settled menu,
       then .5 in the scrim tap's mousemove: no click). .001 is not transparent, so mid is never "hidden" in the open; it draws nothing a frame shows */   // apply() wrote the body's opacity: mid carries it
    if (c.anchor) { btnRaise(c.anchor); play(c.anchor, path.map((b, i) => { const q = b.q, x = Math.max(0, (m.w - BTN_H) * q / 2);   // btnMorph's values; q 0 as the identity (a keyframe cannot interpolate from "")
      return { offset: off(i), opacity: String(q <= 0 ? 1 : Math.max(0, Math.min(1, 1 - q))), transform: `translate(${(m.x * q).toFixed(3)}px, ${(m.y * q).toFixed(3)}px) scale(${(1 - 0.75 * q).toFixed(4)})`, clipPath: `inset(0 ${x.toFixed(3)}px)`, ...(c.xf && c.xf.btn ? {} : { filter: `blur(${(4 * Math.max(0, q)).toFixed(3)}px)` }) }; })); }   // no ladder: the old apply's blur 4p (XF_BTN)
    const x = c.xf; if (x) { const wb = path.map((b) => xfBody(b.q)); x.body.forEach((e, k) => play(e, path.map((b, i) => ({ offset: off(i), opacity: String(wb[i][k]) }))));   // the blur ladder's weights (xfBuild)
      if (x.btn) { const wa = path.map((b) => xfBtn(b.q)); x.btn.forEach((e, k) => play(e, path.map((b, i) => ({ offset: off(i), opacity: String(wa[i][k]) })))); } }
    c.anims = A; if (out && g && g.stroke && STROKE_WAAPI) animStroke(g.stroke); };
  /* the dismiss on the compositor (acceptance 09-30 02:2x): the same sampling as the open, from the state at the close — x AND v of every spring (a dismiss that
     interrupts a moving open starts where the open was, at its speed; the open's animations are cancelled first, unanim in close) — on DISMISS ζ .8 / .49 and
     CROSS_OUT ζ .8 / .49 for p, r sprung in the layer's units (close() converts it), up to the same settled() rule (the loop strips there; the last sample is not
     snapped). The hold frame (tick) writes the start state inline as before and starts every animation with startTime = that frame's time — the spring's own t0 —
     so the first frame shows the start value. The panel keeps its own drop-shadow (no box: acceptance 03:4x). Blur: the same ladder
     (xfBuild), weights on the dismiss's p. tailHidden at the first p ≤ 0 and strip() at the settle are the live tick's, unchanged */
  const planOut = () => { const c = cur; c.outPlan = null; if (c.reduced || !c.inner || !c.mid || !Element.prototype.animate) return;
    const S = JSON.parse(JSON.stringify(c.s)), goal = c.goalOut, path = [];
    for (let i = 0; i < 2400; i++) { if (i) for (const k of Object.keys(goal)) Motion.spring(S[k], goal[k], k === "p" ? CROSS_OUT : DISMISS, PRE_DT);
      const G = shownAt(S, i * PRE_DT, "out", c.from, c.rest, c.to); path.push({ ...G, r: Math.max(0, Math.min(S.r.x * G.width / W, G.width / 2, G.height / 2)), a: S.a.x, q: S.p.x }); if (i && settled(goal, S)) break; }   // shownBox / cornerNow (rl) at that sample
    let U = morphBox(c.from, c.to); for (const b of path) if (b.left < U.left || b.top < U.top || b.left + b.width > U.left + U.width || b.top + b.height > U.top + U.height) U = morphBox(U, b);   // as animOpen: the path's own box, not close()'s padY one
    setMorph(U); c.outPlan = { path }; };
  const playOut = (t0) => { const c = cur, P = c.outPlan; c.outPlan = null; if (!P) return;
    if (c.sh) { c.sh.style.filter = getComputedStyle(c.panel).filter; c.panel.style.filter = "none"; } c.body.style.filter = ""; if (c.anchor) c.anchor.style.filter = "";
    playAll(c, { sh: c.sh, list: [], path: P.path, T: c.rest, st: null, t0 }, c.U, true); };
  /* STROKE_WAAPI false (外观 09-30 05:4x): the stroke follows the panel by a per-frame transform write (main's followStroke), not a Web Animation. On a
     transform animation Chrome rasters the layer at the animation's largest scale, so the stroke's filter chain (#menu-stroke-f over its page copy) ran
     at full size on the first open, ~2 frames in: RasterTask 13.4 ms (gate5 r1-new, layer 383; lm/new: div.menu-stroke 27 ms concurrent) against main's
     1.4–2.7 ms at the small scale it has when built (will-change: transform keeps that scale while it moves), and the next commit waited for it
     (LayerTreeHost::WaitForCommitCompletion 13.6–15.1 ms: the first open's longest frame, 22–24 ms vs main 12–15). A transform write on its own layer
     is not a paint (no PACU). */
  const STROKE_WAAPI = false;
  const animStroke = (el) => { const A = cur.anims; if (A.st === el) return; A.st = el; const T = A.T, n = A.path.length - 1, K = A.kf || A.path; el.style.willChange = "transform";   // built two frames in (or at the press): the same startTime, so it joins the path where the others are
    const a = el.animate(K.map((b) => ({ offset: b.o ?? 1, transform: `translate3d(${b.left + b.width / 2 - T.left - T.width / 2}px, ${b.top + b.height / 2 - T.top - T.height / 2}px, 0px) scale3d(${b.width / T.width}, ${b.height / T.height}, 1)` })), { duration: n * PRE_DT * 1000, easing: "linear", fill: "forwards" });
    a.startTime = A.t0; A.list.push(a); };
  const unanim = (write, an) => { const A = an || (cur && cur.anims); if (!A) return; if (cur && cur.anims === A) { cur.anims = null; if (write) apply(); }   // write: the current state inline first (the old path), so the cancel shows no stale frame
    if (A.sh) { A.sh.style.filter = "none"; if (cur) cur.panel.style.filter = ""; } for (const a of A.list) a.cancel(); A.list.length = 0; };   // the panel's own drop-shadow back (its box stays, unfiltered)
  const strip = () => { if (!cur) return; cancelAnimationFrame(cur.raf); unanim(false); if (cur.anchor) { xfClear(cur.anchor, cur.xf); btnClear(cur.anchor); } if (cur.glass && cur.glass.stroke) { cur.glass.stroke.remove(); cur.glass.stroke = null; } cur.panel.remove(); cur.scrim.remove(); removeEventListener("keydown", onKey); cur = null; document.dispatchEvent(new Event("menu-closed")); };   // view.js holds a re-render while a menu is up and runs it here
  const tick = (now) => { if (!cur) return;
    if (cur.anims || cur.outPlan) { const tl = document.timeline.currentTime; if (tl != null) now = tl; }   // while Web Animations draw the morph, the driver runs on their timeline: in a browser the same time as the frame's rAF timestamp; under a virtual clock (accept-run's rAF queue) the rAF time ran a frame ahead of what the animations showed (accept 72 / 93)
    if (now <= cur.prev) { cur.raf = requestAnimationFrame(tick); return; }
    if (cur.hold) { cur.hold = false; cur.prev = cur.t0 = now; cur.t = 0; cur.frame = 1; apply(); if (cur.outPlan) playOut(now); cur.raf = requestAnimationFrame(tick); return; }   // the dismiss's first frame shows the start value, the spring starts on this frame (g22-blur-table.txt: model written 7.732, presented 7.760 still the old value, moving from 7.794 — 2 frames after the write)   // a frame stamped before the spring's start (Chrome: rAF's `now` is the frame's start, which can precede the call): nothing to integrate yet, the time base stays
    const dt = Math.min(1, (now - cur.prev) / 1000); cur.prev = now;   // time-based like a CA spring: a stalled frame lands where the clock says (the analytic step is exact for any dt); no 40 ms clamp — that clamp made the panel fall behind its own closed form after every long frame (验收 00:2x: rms 7 pt under load), only a > 1 s stall is cut
    const goal = cur.phase === "in" ? cur.goalIn : cur.goalOut, spec = cur.phase === "in" ? (cur.reduced ? REDUCE : APPEAR) : (cur.reduced ? REDUCE : DISMISS);
    const derivedR = cur.phase === "in" && !cur.reduced, pPrev = cur.s.p.x;   // the open's r is derived (openR), not sprung
    for (const k of Object.keys(goal)) if (!(derivedR && k === "r")) Motion.spring(cur.s[k], goal[k], k === "p" && !cur.reduced ? (cur.phase === "in" ? CROSS : CROSS_OUT) : spec, dt);   // p: its own spring (G22), the dismiss's its own
    cur.tPrev = cur.t; cur.t = (now - cur.t0) / 1000; cur.frame = (cur.frame || 0) + 1;   // the driver's own clock: every frame's x is the closed form at this t (the analytic step is exact)
    if (derivedR) { cur.s.r.x = openR(cur, pPrev); cur.s.r.v = 0; }
    apply();
    /* 渲染有延迟 (用户 09-24 20:47 / 21:34): the finished edge used to come on late (7aec6ba: at p's first pass of 1; before it at the settle) — the stroke and
       f1 + f2 are now on from the open's first frame (glassMorph), only f3 waits for rest (glassFull) */
    if (settled(derivedR ? { ...goal, r: cur.s.r.x } : goal) && (!derivedR || cur.first || cur.s.r.x === R)) { if (cur.phase === "out") { strip(); return; } cur.raf = 0; for (const k of Object.keys(goal)) { cur.s[k].x = goal[k]; cur.s[k].v = 0; } const an = cur.anims; if (an) { cur.anims = null; apply(); } restStyles();   // rests ON the goal (a spring ends at its target): the stroke map below is then the same key every open (cached)
       followStroke(); if (an) unanim(false, an); glassFull(cur.glass, true); return; }   // "in" settled: the panel rests, the loop stops; f3 comes on (see glassFull)
    cur.raf = requestAnimationFrame(tick); };
  const run = () => { if (cur.raf) cancelAnimationFrame(cur.raf); cur.prev = performance.now(); cur.raf = requestAnimationFrame(tick); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const menuItem = (o) => { const b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "menuitemradio"); if (o.selected) b.classList.add("on");   // one row of the panel (open(), and gpuWarm's stand-in)
    const ck = document.createElement("i"); ck.className = "ck"; const sym = typeof SYM !== "undefined" && SYM["checkmark"];   // view.js's SYM is a top-level const (not on window)
    if (sym) ck.setAttribute("style", `-webkit-mask-image:url(${sym});mask-image:url(${sym})`);
    b.appendChild(ck); b.appendChild(document.createTextNode(o.textContent)); return b; };
  function open(anchor, sel, o) {   // o.reduced: the reduce-motion path forced (the acceptance's hook; the page never passes it — the media query decides)
    gpuDrop(); strip();
    const scrim = document.createElement("div"); scrim.className = "menu-scrim";
    const panel = document.createElement("div"); panel.className = "menu morph"; panel.setAttribute("role", "menu");
    const body = document.createElement("div"); body.className = "menu-body"; panel.appendChild(body);
    for (const o of sel.options) {
      if (o.hidden) continue;   // view.js's 「未设」 placeholder (a master value the machine has not set yet) names the button, it is not a choice
      const b = menuItem(o);
      b.onclick = () => { const t = cur ? livePair(cur.sel, cur.anchor).sel : sel, to = [...t.options].some((x) => x.value === o.value) ? t : sel;   // the select on screen now (see livePair)
        if (to.value !== o.value) { to.value = o.value; to.dispatchEvent(new Event("change", { bubbles: true })); } close(); };
      body.appendChild(b);
    }
    scrim.onclick = close;
    document.body.append(scrim, panel);
    const h = body.offsetHeight;   // items × 42 + the 10 / 10 insets
    const glass = buildGlass(panel, 250, h);
    const from = seedRect(anchor, h), to = restRect(anchor, h), reduced = o && o.reduced != null ? !!o.reduced : reduce();
    placeGlassRest(glass, to);
    const start = reduced ? { ...to } : from;
    const s = { left: { x: start.left, v: 0 }, top: { x: start.top, v: 0 }, width: { x: start.width, v: 0 }, height: { x: start.height, v: 0 }, r: { x: reduced ? R : W / 2, v: 0 }, a: { x: reduced ? 0 : 1, v: 0 }, p: { x: reduced ? 1 : 0, v: 0 } };
    cur = { panel, body, scrim, sel, anchor, from, to, s, reduced, glass, phase: "in", goalIn: { left: to.left, top: to.top, width: to.width, height: to.height, r: R, a: 1, p: 1 }, goalOut: null, prev: 0, raf: 0, t0: 0, rest: to, bw: body.offsetWidth, bh: h, U: null, move: btnMove(anchor, to), rl: !reduced, first: opened++ === 0, turn: null };   // rl: r in the layer's units from the start (the seed square's 125 → its half side 8.58)
    setMorph(reduced ? morphBox(start, to) : padY(morphBox(start, to), start, to)); apply(); addEventListener("keydown", onKey); run(); cur.t0 = cur.prev; animOpen(); glassMorph(glass);   // one material from the first frame (see glassFull)   // t0 = the spring's start (the call's performance.now()): the closed form x(t) holds at t = frame timestamp − t0
  }
  function close() {
    if (!cur) return;
    if (cur.phase === "out") return;
    unanim(true);   // a dismiss during the open: the current spring state written inline (the old path), then the open's animations cancelled — the dismiss is unchanged
    const lp = livePair(cur.sel, cur.anchor); if (lp.anchor !== cur.anchor) { btnClear(cur.anchor); cur.move = btnMove(lp.anchor, cur.rest); } cur.sel = lp.sel; cur.anchor = lp.anchor;   // a re-render while open replaced the button: morph back to the one on screen
    const back = cur.anchor.isConnected ? seedRect(cur.anchor, cur.rest.height) : cur.from;   // the start square on the button now (the page may have scrolled); an unfindable button: where it was at the open
    const shown = shownBox(cur.s); cur.phase = "out"; cur.from = shown; cur.to = back;   // the box on screen (an open cut short shows the layer path, not the springs' box)
    cur.goalOut = cur.reduced ? { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x, r: R, a: 0 } : { left: back.left, top: back.top, width: back.width, height: back.height, r: W / 2, a: 1, p: 0 };
    if (!cur.reduced) { const k = W / Math.max(1, cur.s.width.x); cur.s.r.x = cornerNow(cur.s) * k; cur.s.r.v *= k; cur.rl = true; }   // r into the layer's units (see cornerNow): at rest k = 1
    cur.scrim.style.pointerEvents = "none"; setMorph(cur.reduced ? morphBox(boxOf(cur.s), back) : padY(morphBox(shown, back), shown, back)); cur.t = 0; apply(); planOut(); glassFull(cur.glass, false); run(); cur.t0 = cur.prev; cur.t = 0; cur.frame = 0; cur.hold = !cur.reduced;   // apply: the clip on the new U at once — the first tick can skip (now ≤ prev) and the layer then painted a frame uncut (restStyles cleared its clip-path; simulator A 09-30 m3-close3: 280×210, r 0)   // the dismiss morph on the light chain (R63); hold: see tick
  }
  /* hidden strips the state at once (BOARD A6 template): nothing animates while the page is away and a half-open menu must not come back */
  /* the press: the value-row popup button (plain configuration) dims its title while the finger is down — light α × .75, dark .8c + .2 (state-tables/button.md:23-24,
     R14 plain; the .held rule in index.html) — and nothing else on it (its view α stays 1 into the morph, rowS-deep-table.md 525 ms). Driven by pointerdown, not :active:
     Android Chrome puts :active on only after the lift (0a0c1fd, diag 20260924-194355). highlighted goes true 0.7–1.5 ms after the down; when the tap opens the menu it
     goes false by touchCancel 100.4–107.3 ms after the up (7 taps rowS / rowL / rowS2 / rowL2 open + reopen, touch-local.uiprobe-m0924 / -m0924b; HELD_UP = their
     median 104.1, 采样替代; 已查 touch-local.uiprobe-m0924 / -m0924b，缺 the UIKit rule that times the touchCancel — the context-menu interaction's own delay is not read). Lifted outside the button (no click, no menu): off at the lift (the native drag-out rule is not read). */
  const HELD_UP = 104.1;
  let held = null, heldT = 0;
  const unhold = () => { clearTimeout(heldT); if (held) held.classList.remove("held"); held = null; };
  document.addEventListener("pointerdown", (e) => { if (!e.isPrimary || e.button !== 0) return; const b = e.target.closest && e.target.closest("main .menubtn"); unhold(); dropPressed(); if (b) gpuDrop(); if (b) { held = b; b.classList.add("held"); pressStroke(b); btnPreMake(b); } }, true);
  document.addEventListener("pointerup", (e) => { if (!held || !e.isPrimary) return; const b = held, r = b.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) { unhold(); pressEnd(false); return; }
    pressEnd(true); clearTimeout(heldT); heldT = setTimeout(() => { if (held === b) unhold(); }, HELD_UP); }, true);
  document.addEventListener("pointercancel", () => { unhold(); pressEnd(false); }, true);
  const onHidden = (force) => { if (force || document.hidden) { unhold(); dropPressed(); gpuDrop(); strip(); } };
  document.addEventListener("visibilitychange", () => onHidden(false));
  /* first open as fast as the second (验收 09-24 14:19, 菜单打开 首开 101.7 每秒卡顿; simulator D tl2 / tl3: the first open spent 122 ms in glassImages / ensureFilter, every
     settle 45–72 ms in strokeMap): the glass maps and the stroke's k map for every menu on the page (W 250, H = options × 42 + 20 = what open() measures, r = R at rest)
     are made in idle slots after load, the way alert-glass.js warms its stroke. Sliced (玻璃卡顿-0929.md, simulator A cold loads: from ≈ 3 s after load the warm-up
     held the main thread as TimerFire ×7 = 482 ms, the longest 97 ms (×11 = 630 ms, 106 ms on the second run), and a tap landed 167 ms late in it — each idle callback
     built a whole map, and the 3 s timeout ran it whether idle or not): an idle callback works only while IdleDeadline.timeRemaining() lasts (W3C Cooperative
     Scheduling of Background Tasks, "Idle Periods" (≤ 50 ms) / "The IdleDeadline interface": timeRemaining = deadline − now), no timeout; each map is a job (glassImages.step / strokeStep) cut per pixel row, per
     blur row / column, one PNG encode a slice (the largest step that cannot be cut — toDataURL was 81 of the 403 profile samples — so one can overrun a short deadline), and resumed by the next callback. An open() that meets a
     half-built job finishes it synchronously from where it stopped. Without requestIdleCallback: a setTimeout slice with a fixed 8 ms budget (1500 ms before the first). A slice also stops after IDLE_SLICE 10 ms: with nothing
     to render Chrome hands out 50 ms idle periods, and a tap that lands in one waits it out (headless Chrome dpr 3, ?demo=1: slices of 31–55 ms without the cap) */
  const IDLE_BUDGET = 8, IDLE_SLICE = 10, idle = (fn, wait = 0) => (window.requestIdleCallback ? requestIdleCallback(fn) : setTimeout(() => { const t = performance.now() + IDLE_BUDGET; fn({ didTimeout: false, timeRemaining: () => Math.max(0, t - performance.now()) }); }, wait));
  /* a finished map's PNGs are decoded in the same idle slice (HTMLImageElement.decode(), HTML "Decoding images"): the first open decoded all nine glass maps in its
     first frame (玻璃卡顿-0929.md:261/:267, Chrome: dataURL load / Decode Image / GPU upload ×9 at the first open, 0 at the second; 随机模式 on the phone 149 vs 58 ms).
     The Images are kept so their decoded data stay with the resource; the upload to the GPU still happens at the first open. No output byte changes */
  const decoded = [], predecode = (o) => { for (const v of Object.values(o)) if (typeof v === "string" && v.startsWith("data:image/")) { const im = new Image(); im.src = v; decoded.push(im); if (im.decode) im.decode().catch(() => {}); } return true; };
  /* Order and size (动效 09-29 13:5x; the phone's record ark-diag/flu/20260929131032-3efcd70a-1.json: the first 「单倍领取」 open 5.4 s after load, click proc 217 ms):
     the whole warm-up is ≈ 356 ms of script at CPU ×1 on the Mac (work 214 / strokeWork 130, headless Chrome dpr 3.25), cut into ≤ 10 ms idle slices, so on the
     phone it runs for seconds — and the sizes went in document order (the 状态 / 方舟 sections first), the page on screen (终末地, restored from ark-remote-tab)
     fourth and fifth: its first open finished them synchronously (Chrome CPU ×10, 5.4 s: open 307 ms, ensureFilter 272 / buildStroke 209). The menus on screen
     (no hidden ancestor) go first, top to bottom, then the rest. H counts the items open() lays out: it skips the hidden 「未设」 placeholder (view.js:503; open's `if (o.hidden) continue`).
     Menu.warm(): the jobs left, the sizes as found and the queue (sizes, a glass and a stroke job each), for the fluency recorder (was the warm-up done at the tap) */
  const warm = { left: 0, sizes: [] }, warmQ = [], warmed = new Set(); let pumping = false, started = false;
  /* A scan, not a one-off: the menus come with the data (render → dressSelects, view.js:2529), and a snapshot that lands after the load-time scan left its
     menus cold (验收 13:3x). Each scan queues the sizes not seen yet and moves the sizes on screen to the front (a half-built job keeps its place in `jobs`
     and resumes when its turn comes back); Menu.prewarm() runs one after the current task — from dressSelects and from a tab switch — once the load-time scan has run (before it: nothing, the
     load-time wait stays as it was) */
  const pump = (dl) => { const end = performance.now() + IDLE_SLICE, more = () => dl.timeRemaining() > 1 && performance.now() < end; try { while (warmQ.length && warmQ[0].run(more)) { warmQ.shift(); if (!more()) break; } } catch (e) { warmQ.shift(); } warm.left = warmQ.length; if (warmQ.length) idle(pump); else pumping = false; };   // a job that throws is dropped, the rest go on
  /* the map worker (验收 13:4x; the phone 13:46, ark-diag/flu/20260929134627-e94ee1e7-1.json pn 4045: 4.0 s after load the warm-up had built 1 of its 10 jobs —
     idle periods hardly come on the phone — and the first 「无音区」 press / click built the stroke / glass maps on the main thread, 91 + 191 ms): glassPx /
     strokePx and their helpers by source text in a Worker (the way alert-glass.js builds the alert's maps), each canvas an OffscreenCanvas PNG-encoded there
     (convertToBlob → FileReaderSync data URL). The main thread only files the result (glassImages.put / strokeMaps) and predecodes it. Sizes go to the worker
     as the scan finds them, on-screen first. No worker (no OffscreenCanvas / FileReaderSync, or it fails): the idle slices below, as before. An open() before
     the worker's answer still builds that map itself, as before — never a menu without its glass (验收 13:5x).
     One job at a time (中继二 09-30 01:5x): with an async onmessage each await convertToBlob let the next message's draw in, so all 10 draws ran before any
     job came back — every job 0.5–1.6 s, the on-screen size among the last (split timings, 4× CPU: draw 45–123 ms, base64 0–11 ms, the rest waiting on the
     other draws). Chained, the on-screen size comes back first; mapWorker().sp holds each job's split (q wait / draw / blob / b64 / all, ms) */
  const mapWorker = { w: null, state: "idle", pending: {}, ms: {} };
  const workerSrc = () => `const PXG = ${PXG}, MAPS = ${MAPS}, KR = ${KR}, HLK = ${JSON.stringify(HLK)}; const satf = ${satf}; const scPoly = ${scPoly}; const gOval = ${gOval}; const sdfSuper = ${sdfSuper};
const Dc = ${Dc}; const bandf = ${bandf}; const lod = ${lod}; const ringPath = ${ringPath}; const glassPx = ${glassPx}; const strokePx = ${strokePx};
const T = () => performance.timeOrigin + performance.now(), mkc = (w, h) => new OffscreenCanvas(w, h), drain = (g) => { let s; do s = g.next(); while (!s.done); return s.value; };
const enc = async (c, sp) => { let t = T(); const b = await c.convertToBlob({ type: "image/png" }); sp.blob += T() - t; t = T(); const u = new FileReaderSync().readAsDataURL(b); sp.b64 += T() - t; sp.bytes += b.size; return u; };
let chain = Promise.resolve(); onmessage = (e) => { chain = chain.then(() => job(e.data)).catch(() => {}); };
const job = async (m) => { const t0 = T(), sp = { q: t0 - m.tPost, draw: 0, blob: 0, b64: 0, bytes: 0 }; try { let out, t = T();
  if (m.kind === "glass") { const cs = drain(glassPx(m.W, m.H, m.k, mkc)), urls = []; sp.draw = T() - t; for (const c of cs) urls.push(await enc(c, sp)); out = { urls }; }
  else { const p = drain(strokePx(m.W, m.H, m.r, m.k, m.dpr, mkc)); sp.draw = T() - t; out = { urls: [await enc(p.c, sp)], E: p.E, kmax: p.kmax, kside: p.kside, ktop: p.ktop }; }
  for (const k in sp) sp[k] = Math.round(sp[k]); sp.all = Math.round(T() - t0); sp.tDone = T();
  postMessage(Object.assign(out, { id: m.id, ms: sp.all, sp })); } catch (err) { postMessage({ id: m.id, error: String(err && err.message || err) }); } };`;
  const spawn = () => { if (mapWorker.state.startsWith("main")) return false;   // the worker made once (toWorker's first job, or menu.js's own run below)
    try { if (!mapWorker.w) { if (typeof OffscreenCanvas !== "function" || typeof Worker !== "function") { mapWorker.state = "main: no OffscreenCanvas"; return false; }
        mapWorker.w = new Worker(URL.createObjectURL(new Blob([workerSrc()], { type: "text/javascript" }))); mapWorker.state = "worker";
        const back = (why) => { mapWorker.state = "main: " + why; try { mapWorker.w.terminate(); } catch (e) {} const p = mapWorker.pending; mapWorker.pending = {}; for (const k of Object.keys(p)) p[k](null); };   // every job still out goes to the idle slices
        mapWorker.w.onmessage = (e) => { const m = e.data, f = mapWorker.pending[m.id]; if (!f) return; if (m.error) { back(m.error); return; } delete mapWorker.pending[m.id]; mapWorker.ms[m.id] = m.ms; (mapWorker.sp = mapWorker.sp || {})[m.id] = Object.assign(m.sp, { back: Math.round(performance.timeOrigin + performance.now() - m.sp.tDone), tDone: Math.round(m.sp.tDone - performance.timeOrigin) }); f(m); };   // an error: back() hands every job still out, this one included, to the idle slices
        mapWorker.w.onerror = (e) => { e.preventDefault && e.preventDefault(); back(e.message || "worker error"); }; } }
    catch (err) { mapWorker.state = "main: " + String(err && err.message || err); return false; } return true; };
  const toWorker = (id, msg, done) => { if (!spawn()) return false;
    mapWorker.pending[id] = done; mapWorker.w.postMessage(Object.assign({ id, tPost: performance.timeOrigin + performance.now() }, msg)); return true; };
  /* the worker from menu.js's own run on (验收 02:0x; the phone, ark-diag/flu/20260929164704-e38020a1-1.json: a 随机模式 tap 1.1 s after load, its maps
     not built — menu_maps h 146 img / stroke false — BUTTON.onclick 161 ms): made by warmUp's first job at load, the worker's start (its source compiled,
     215–530 ms) and the on-screen size's draw (45–123 ms) were both still ahead at a tap right at ready, so open() built the maps on the main thread.
     Now it is made here (its source compiles while the page parses) and the scan runs at DOMContentLoaded, not at load — the on-screen size goes out first;
     load's warmUp finds those sizes taken (warmed). Not on the next task: a timer there runs between the later scripts and pushed DOMContentLoaded back */
  if (typeof OffscreenCanvas === "function" && spawn()) { const early = () => { if (!started) warmUp(); };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", early, { once: true }); else setTimeout(early, 0); }
  const warmUp = () => { started = true; try { const th = glassTheme(), k = glassKeys(th), dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1)), q = [];
    const sels = [...document.querySelectorAll("main select.native")], shown = (s) => !s.closest("[hidden]"), hOf = (s) => [...s.options].filter((o) => !o.hidden).length * 42 + 20;
    for (const H of new Set([...sels.filter(shown), ...sels.filter((s) => !shown(s))].map(hOf))) { const id = `${th} ${H}`;
      if (warmed.has(id)) { q.push(...warmQ.filter((e) => e.id === id)); continue; } warmed.add(id); warm.sizes.push(H);
      const gj = { id, run: (more) => glassImages.step(W, H, k, more) && predecode(glassImages(W, H, k)) }, sj = { id, run: (more) => strokeStep(W, H, R, k, dpr, more) && predecode(strokeMap(W, H, R, k, dpr)) };
      const idleJob = (j) => { warmQ.push(j); warm.left = warmQ.length; if (!pumping) { pumping = true; idle(pump); } };   // the worker failed: this job to the idle slices
      if (!toWorker("g " + id, { kind: "glass", W, H, k }, (m) => { if (!m) return idleJob(gj); if (glassImages.put(W, H, k, glassPack(m.urls, W, H))) predecode(glassImages(W, H, k)); })) q.push(gj);
      const sk = strokeKey(W, H, R, k, dpr);
      if (!toWorker("s " + id, { kind: "stroke", W, H, r: R, k, dpr }, (m) => { if (!m) return idleJob(sj); if (!strokeMaps[sk]) { strokeMaps[sk] = { href: m.urls[0], E: m.E, dpr, kmax: m.kmax, kside: m.kside, ktop: m.ktop, key: sk }; delete strokeJobs[sk]; predecode(strokeMaps[sk]); } })) q.push(sj); }
    q.push(...warmQ.filter((e) => !q.includes(e))); warmQ.splice(0, warmQ.length, ...q); warm.left = warmQ.length;
    if (warmQ.length && !pumping) { pumping = true; idle(pump); } } catch (e) {} };
  /* ---- the GPU warm-up (补四, 动效 09-30): the phone's first open per load has two long frames (108 / 232 ms) with almost no script, the reopens 17–50 ms.
     Mac trace (BOARD/evidence/动效-0929-菜单GPU/sum.md 结论 1): what only the first open does is the GPU's first compile of the shaders / pipelines of this
     material — 84–127 GPU cache blobs written in 0–800 ms after the first click (browser GpuHostImpl::StoreBlobToDisk), 0–6 at the reopen; the long frames
     are the first open's DoEndRasterCHROMIUM::Flush (f1 / f2 rastered in the morph's first frames, r1) and a 476 ms FinishPaintRenderPass at rest (f3 on w3,
     glassFull, r2 +204 ms). So, once per load and theme, once the maps for the first menu on screen are cached (never the sync builders), a stand-in of a
     real open is drawn for a few frames at opacity .01 and removed: the panel as open() builds it (class, body rows, buildGlass, placeGlassRest, the copy
     placed as restStyles / placeGlass do), f1 + f2 + f3 and the stroke layer (buildStroke). The first frames carry the morph's extra paint (the glass layer's
     clip-path, the body's blur / opacity, the button's blur, the stroke's will-change scale3d) over five frames, then the rest state — the glass in one task, the
     stroke and the button in a second (below); torn down two frames after the second's rest. Drawn for real: opacity 0 /
     visibility hidden / display none / off-screen are not painted, so nothing would compile. It leaves nothing: the next open() rebuilds
     #menu-glass-svg (ensureFilter's innerHTML) and re-places every filter / feImage on its own rest box (placeGlassRest), buildStroke sets #menu-stroke-f's
     x / y again, and `opened` (the first open's corner) is not touched. A press on a menu button, an open or a hidden page removes it at once.
     requestIdleCallback with a timeout plus a setTimeout guard: idle periods hardly come on the phone after load (see the map worker above). ?gpuwarm=0 turns
     it off (the A / B arm); Menu.gpuWarm() = { state, at, ms, … } and the marks m-gpuwarm0 / m-gpuwarm1 for the trace tools (remote-ref/tools/menu/mtrace-g.py) */
  const GPU_TRIES = 30, GPU_RETRY = 300, GPU_YIELDS = 3, GPU_QUIET = 1000;   // gpu / gpuDrop: defined at the top of this closure (open() and the listeners call gpuDrop)
  const gpuSoon = (fn) => { let ran = false; const go = () => { if (!ran) { ran = true; fn(); } }; if (window.requestIdleCallback) requestIdleCallback(go, { timeout: 1000 }); setTimeout(go, 1200); };
  const gpuTry = () => { if (gpu.state === "off" || gpu.live) return; const th = glassTheme(); if (gpu.done.has(th)) return;
    const later = (why) => { gpu.state = "wait: " + why; if (++gpu.tries < GPU_TRIES) setTimeout(() => gpuSoon(gpuTry), GPU_RETRY); else { gpu.state = "gave up: " + why; gpu.done.add(th); } };
    if (opened) { gpu.state = "skipped: opened"; gpu.done.add(th); return; }   // a real open has compiled it already
    if (cur || pressed) return later("menu"); if (reduce()) { gpu.state = "reduce"; gpu.done.add(th); return; }
    const main = document.getElementById("app"); if (!main) return later("no #app");
    const btns = [...document.querySelectorAll("main .menubtn")].filter((b) => !b.closest("[hidden]") && b.previousElementSibling && b.previousElementSibling.tagName === "SELECT" && b.getBoundingClientRect().height > 0);
    const b = btns.find((x) => { const r = x.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }) || btns[0]; if (!b) return later("no button");
    const sel = b.previousElementSibling, h = [...sel.options].filter((o) => !o.hidden).length * 42 + 20, k = glassKeys(th), dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1));
    if (!glassImages.has(W, h, k) || !strokeMaps[strokeKey(W, h, R, k, dpr)]) return later("maps");   // buildGlass / buildStroke would build a missing map synchronously
    const t0 = performance.now(); performance.mark("m-gpuwarm0"); let panel = null;
    /* two tasks, each with its own frames: A = the panel + glass (f1 / f2 / f3), B = the stroke layer + the button's copy. In one task (the first version,
       warm-w2 / w6) it was one 86–96 ms task at CPU ×4 — the two #app clones' style recalc (UpdateLayoutTree 31–34 ms, forced by buildStroke's
       getComputedStyle) plus the filter svg's innerHTML (ParseHTML 13 ms) — longer than the first open's own long frame it takes away (66 ms median);
       split, the style recalc of each clone lands in its own frame. Every rect is read before anything is inserted (no forced layout of a clone) */
    try { const r0 = restRect(b, h), to = { ...r0, top: Math.max(EDGE, Math.min(r0.top, innerHeight - EDGE - h)) };   // on screen (a panel off the viewport is not drawn)
      const br = b.getBoundingClientRect(), mv = btnMove(b, to);
      panel = document.createElement("div"); panel.className = "menu morph"; panel.setAttribute("aria-hidden", "true"); panel.inert = true;
      panel.style.cssText = `left:${to.left}px;top:${to.top}px;width:${to.width}px;height:${to.height}px;border-radius:${R}px;opacity:.01;pointer-events:none`;
      const body = document.createElement("div"); body.className = "menu-body"; for (const o of sel.options) if (!o.hidden) body.appendChild(menuItem(o)); panel.appendChild(body);
      document.body.appendChild(panel);
      const g = buildGlass(panel, W, h); if (!g) { panel.remove(); return later("no glass"); }
      const live = { panel, stroke: null, btn: null, raf: 0 }; gpu.live = live;
      placeGlassRest(g, to); placeGlass(g, { left: { x: to.left }, top: { x: to.top } });
      g.copy.style.filter = "url(#menu-glass-f1)"; g.w2.style.filter = "url(#menu-glass-f2)"; g.w3.style.filter = "url(#menu-glass-f3)";
      /* the morph's paint at p = .1 … .9, one p a frame (setMorph / apply: the glass layer's clip-path, the body's transform / clip-path / opacity p / blur 4(1 − p);
         in B the button's copy on btnMorph with opacity 1 − p / blur 4p and the stroke on will-change scale3d — followStroke): each blur radius is its own GPU
         program (a probe with one morph frame left 38 blobs at +102 … +289 ms of the first open, the morph's frames: 动效-0929-菜单GPU/warm-sum.md), then the
         rest state (restStyles, followStroke at rest; set in the frame's own rAF, which runs before it paints) */
      const PS = [0.1, 0.3, 0.5, 0.7, 0.9], bs = body.style;
      const glassAt = (p) => { const y = (1 - p) * 20; g.layer.style.clipPath = `inset(${y.toFixed(3)}px round ${R}px)`; bs.transform = `translate(0px, ${(-y / 2).toFixed(3)}px)`;
        bs.clipPath = `inset(0px 0px ${y.toFixed(3)}px 0px round ${R}px)`; bs.opacity = String(p); bs.filter = `blur(${(4 * (1 - p)).toFixed(3)}px)`; };
      const glassRest = () => { g.layer.style.clipPath = ""; bs.transform = bs.clipPath = bs.opacity = bs.filter = ""; };
      const frames = (at, rest, done) => { const step = (n) => { if (gpu.live !== live) return; if (cur || pressed) { gpuDrop("aborted"); return; }
          if (n < PS.length) at(PS[n]); else if (n === PS.length) rest(); else if (n >= PS.length + 2) { done(); return; }
          live.raf = requestAnimationFrame(() => step(n + 1)); };
        at(PS[0]); live.raf = requestAnimationFrame(() => step(1)); };
      const partB = () => { if (gpu.live !== live) return; if (cur || pressed) { gpuDrop("aborted"); return; } const t1 = performance.now();
        try { const st = buildStroke(g, panel, to, R); live.stroke = st; const bw = document.createElement("div"), bc = b.cloneNode(true); live.btn = bw;
          bw.style.cssText = `position:fixed;left:${br.left}px;top:${br.top}px;width:${br.width}px;height:${br.height}px;z-index:9;opacity:.01;pointer-events:none`; bw.setAttribute("aria-hidden", "true"); bw.inert = true;
          bc.style.margin = "0"; bw.appendChild(bc); document.body.appendChild(bw); if (st) { st.style.opacity = ".01"; st.style.willChange = "transform"; }
          gpu.msB = +(performance.now() - t1).toFixed(1); gpu.ms = +(gpu.msA + gpu.msB).toFixed(1);
          frames((p) => { glassAt(p); btnMorph(bc, p, mv); bc.style.opacity = String(1 - p); bc.style.filter = `blur(${(4 * p).toFixed(3)}px)`;
              if (st) st.style.transform = `translate3d(0px, 0px, 0px) scale3d(${(0.9 + 0.1 * p).toFixed(4)}, ${(0.9 + 0.1 * p).toFixed(4)}, 1)`; },
            () => { glassRest(); bw.remove(); if (st) { st.style.willChange = "auto"; st.style.transform = "translate3d(0px, 0px, 0px)"; } }, () => gpuDrop("done")); }
        catch (e) { gpuDrop(); gpu.state = "error: " + String(e && e.message || e); } };
      gpu.state = "up"; gpu.at = t0; gpu.msA = +(performance.now() - t0).toFixed(1); gpu.msB = null; gpu.ms = gpu.msA; gpu.theme = th; gpu.H = h; gpu.to = { ...to }; gpu.done.add(th);
      frames(glassAt, glassRest, () => gpuSoon(partB));   // B after A's frames, in an idle slot of its own (with the same timeout / setTimeout guard)
    } catch (e) { gpuDrop(); if (panel) panel.remove(); gpu.state = "error: " + String(e && e.message || e); gpu.done.add(th); } };
  const gpuSchedule = () => { if (gpu.state === "off" || gpu.live || gpu.done.has(glassTheme()) || gpu.state.startsWith("wait")) return; gpu.state = "wait"; gpu.tries = 0; gpuSoon(gpuTry); };
  /* any press or key while the stand-in is up (its frames, or the idle gap before part B) takes it down at once, so the warm-up's frames and part B's task never
     queue ahead of the control the user touched (验收 code-review 09-30 02:2x: a segment tapped right after load); the theme is warmed again later, from idle, at
     most GPU_YIELDS times per load. A press on a menu button is the pointerdown listener above (the open that follows compiles it for real) */
  const gpuYield = (e) => { if (!gpu.live || (e.type === "pointerdown" && !e.isPrimary)) return; const th = gpu.theme; gpuDrop("input"); gpu.done.delete(th);
    if (++gpu.yields <= GPU_YIELDS) { gpu.state = "input"; setTimeout(gpuSchedule, GPU_QUIET); } else gpu.state = "gave up: input"; };   // after GPU_QUIET ms, not in the user's next frames
  document.addEventListener("pointerdown", gpuYield, true); document.addEventListener("keydown", gpuYield, true);
  /* a theme change after load (prefers-color-scheme, or view.js's data-theme): the other theme's maps and GPU programs were never made — warm both again */
  const reTheme = () => { if (!started) return; setTimeout(warmUp, 0); gpuSchedule(); };
  try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", reTheme); new MutationObserver(reTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] }); } catch (e) {}
  const kick = () => { xfHostsWarm(); (typeof OffscreenCanvas === "function" ? setTimeout(warmUp, 0) : idle(warmUp, 1500)); gpuSchedule(); };   // the worker from load on (it costs the main thread only the filing); else the idle warm-up as before
  if (document.readyState === "complete") kick(); else addEventListener("load", kick, { once: true });
  window.Menu = { layer: { hAt, yAt, cy: CY }, warm: () => ({ left: warm.left, sizes: [...warm.sizes], queue: warmQ.map((e) => e.id.split(" ")[1]).join(" "), worker: mapWorker.state }), prewarm: () => { if (started) { setTimeout(warmUp, 0); gpuSchedule(); } },
    gpuWarm: () => ({ state: gpu.state, at: gpu.at, ms: gpu.ms, msA: gpu.msA, msB: gpu.msB, end: gpu.end, tries: gpu.tries, yields: gpu.yields, live: !!gpu.live, theme: gpu.theme, H: gpu.H, to: gpu.to && { ...gpu.to } }), glass: { keys: glassKeys, built: BUILT, unbuilt: UNBUILT, gOval, sdf: sdfSuper, theme: glassTheme, warmLeft: () => (started ? warmQ.length + Object.keys(mapWorker.pending).length : null), cachedFor: (H) => { const k = glassKeys(glassTheme()), dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1)); return { img: glassImages.has(W, H, k), stroke: !!strokeMaps[strokeKey(W, H, R, k, dpr)] }; },   // read-only (数据 390c682): are a menu's maps built
     mapWorker: () => ({ state: mapWorker.state, left: Object.keys(mapWorker.pending).length, ms: { ...mapWorker.ms }, sp: { ...mapWorker.sp } }), bleedSigma: () => mixStd(lod(glassKeys(glassTheme()).BleedBlurRadius)) / CAPTURE, images: glassImages }, morph: MORPH, springs: { appear: [...APPEAR], dismiss: [...DISMISS], reduce: [...REDUCE], cross: [...CROSS], crossOut: [...CROSS_OUT] }, open, close, onHidden, state: () => cur ? { phase: cur.phase, from: { ...cur.from }, to: { ...cur.to }, reduced: cur.reduced, t0: cur.t0, t: cur.t || 0, frame: cur.frame || 0, settled: !cur.raf, first: !!cur.first, turn: cur.turn,   // settled: read-only (S1, 2号 13:1x) — the "in" morph rests (its loop stopped, the full glass on); the "out" morph strips cur, so state() null = closed
    x: { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x, a: cur.s.a.x, p: cur.s.p.x, r: cornerNow(cur.s) }, shown: shownBox(cur.s), move: { ...cur.move },
    v: { left: cur.s.left.v, top: cur.s.top.v, width: cur.s.width.v, height: cur.s.height.v, a: cur.s.a.v, p: cur.s.p.v } } : null };   // v: read-only (2号 14:4x) — the springs' velocities (pt/s, opacity/s): the dismiss starts from the rested "in" state, whose |v| < 1 pt/s (settled) is not 0, so the acceptance's closed form takes it
})();
