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
  const restRect = (anchor, h) => { const r = anchor.getBoundingClientRect(); const sw = document.documentElement.clientWidth, right = Math.max(EDGE, sw - r.right), left = sw - right - W;   // screen width: innerWidth counts overflow (nav.js W)
    const bt = r.top + r.height / 2 - BTN_H / 2;   // the native button frame's top (see BTN_H); the fallback when the panel does not fit below it is the page's old rule (not read on iOS)
    const top = bt + h <= innerHeight - EDGE ? bt : Math.max(EDGE, r.top - GAP - h); return { left, top, width: W, height: h }; };
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
  const seedRect = (anchor) => { const r = anchorRect(anchor); return { left: r.left + r.width / 2 - SEED / 2, top: r.top + r.height / 2 - SEED / 2, width: SEED, height: SEED }; };   // the morph's start / end square (see SEED)
  /* the corner (数据 09-24 15:50–15:52, BOARD/菜单-圆角淡出变宽-数据-0924.md ①): natively a round end — the start / end square's on-screen radius is
     8.58 = 17.2 / 2 (tables 4 / 6), and through the dismiss the MagicMorphView's layer (250 wide, scaled to the frame) springs its own radius 32 → 125
     (= 250 / 2) while the screen shows layer radius × frame width / 250 (table 1: 39.37 × 231.5 / 250 = 36.46 …), so the tail is a circle, radius = the
     short side / 2 within .17 pt, overshoot included (690 ms 13.6 wide, 6.82). The dismiss carries r in those layer units (cur.rl); the open too (④ below).
     The radius never exceeds half the short side: the layer's own clamp, min(layer short side / 2, R) (④ 2 — the stored cornerRadii is h / 2 exactly) */
  const cornerNow = (s) => { const w = s.width.x, h = s.height.x, r = cur && cur.rl ? s.r.x * w / W : s.r.x; return Math.max(0, Math.min(r, w / 2, h / 2)); };
  /* the open's layer radius R (same file ④, tools/数据-菜单形状/rdrv.py over rowS-deep-motion.json): two regimes, three reopens alike —
     the page's first open (the process's first, segment 0): R = 125 − 93p, p the geometry / opacity progress (f圆角 = f高 to 4 places, 525–975 ms,
     overshoot included: 29.36 @ 775 ms) — never under the clamp, so the screen corner falls from the square's half side on p.
     every later open (segment 2; rowW segments 4 / 6 the same to ≤ .07): R is held at the layer's half height (stored 125 − 73p on the 104-tall menu,
     h = 250 − 146p) up to p .9238 (559 ms), then drops on its own clock below it and undershoots to 28.78 before 32 — per-frame probe values from
     559 ms on (REOPEN_R, ms after the crossing; 采样替代: its driver is not read — AnimationKit's MagicMorphLayer radii write, ④ 4; 已查 BOARD/菜单-圆角淡出变宽-数据-0924.md + NATIVE-GAP G22，缺 the curve that writes the layer radius after the crossing). Menus taller than
     two rows: R before the crossing is not read (it hides under their higher clamp only in part); they take the same 125 − 73p there */
  const REOPEN_R = [[0, 57.56], [17, 53.5], [33, 45.84], [50, 39.96], [67, 35.63], [84, 32.61], [100, 30.64], [117, 29.48], [134, 28.92], [150, 28.78], [167, 28.92], [184, 29.23],
    [200, 29.63], [217, 30.05], [234, 30.46], [250, 30.83], [267, 31.16], [284, 31.42], [300, 31.63], [317, 31.79], [334, 31.91], [350, 31.99], [367, 32]], REOPEN_P = 0.9238;
  let opened = 0;   // opens this page load: the first one is the process's first (segment 0)
  const openR = (c, pPrev) => { const p = c.s.p.x; if (c.first) return W / 2 - 93 * p;
    if (c.turn == null && p >= REOPEN_P) c.turn = c.t - (p - REOPEN_P) / Math.max(1e-6, p - pPrev) * (c.t - (c.tPrev || 0));   // the crossing's time, between the two frames
    if (c.turn == null) return W / 2 - 73 * p;
    const ms = (c.t - c.turn) * 1000, T = REOPEN_R; if (ms >= T[T.length - 1][0]) return R; let i = 1; while (T[i][0] < ms) i++;
    const [t0, r0] = T[i - 1], [t1, r1] = T[i]; return r0 + (r1 - r0) * Math.max(0, ms - t0) / (t1 - t0); };
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
         shape, d_r = the shape's SDF at p + (0, 8); built as an SVG ring band (the rounded rect shifted 8 pt down, the 4 pt band inside its edge)
         blurred σ 5 and multiplied over the glass (col·(1 − term)), clipped to the panel (mask 1);
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
    RingShadowOpacity: "SVG band ring σ 5, multiplied (keyfill-highlight §4)", RingShadowOffset: "the band's shape shifted (0, 8)", RingShadowStrokeWidth: "band width 4 inside the shifted edge", RingShadowBlurRadius: "feGaussianBlur σ 5", RingShadowMask: "clipped to the panel (mask 1)",
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
  const glassImages = (() => { const cache = {}; return (W, H, k) => { const key = `${W}x${H} ${JSON.stringify(k)}`; if (cache[key]) return cache[key]; const hw = W / 2, hh = H / 2, r = 32, w = Math.round(W * PXG), h = Math.round(H * PXG);
    const mk = () => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; }; const cin = mk(), cout = mk(), chl = mk(), chl2 = mk(), cbl = mk(), cw = mk();
    const iin = cin.getContext("2d").createImageData(w, h), iout = cout.getContext("2d").createImageData(w, h), ihl = chl.getContext("2d").createImageData(w, h), ihl2 = chl2.getContext("2d").createImageData(w, h), ibl = cbl.getContext("2d").createImageData(w, h), iw = cw.getContext("2d").createImageData(w, h);
    const cosK = Math.cos(HLK.spread), cosD = Math.cos(HLK.diffuseSpreadScale * HLK.spread), biasD = 1 / (HLK.diffuseAmountScale * HLK.amount) - 2, hD = HLK.diffuseHeightScale * HLK.height, fw = 1 / 3;
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const x = (i + 0.5) / PXG - hw, y = (j + 0.5) / PXG - hh; const [d, gsx, gsy] = sdfSuper(x, y, hw, hh, r); const [gx, gy] = gOval(x, y, hw, hh, gsx, gsy, k.GradientOvalization); const o = (j * w + i) * 4;   // R63″: the ovalized gradient drives the directions
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
      ihl.data[o] = ihl.data[o + 1] = ihl.data[o + 2] = Math.round(255 * satf(a1)); ihl.data[o + 3] = 255; ihl2.data[o] = ihl2.data[o + 1] = ihl2.data[o + 2] = Math.round(255 * satf(a2)); ihl2.data[o + 3] = 255; }
    cin.getContext("2d").putImageData(iin, 0, 0); cout.getContext("2d").putImageData(iout, 0, 0); chl.getContext("2d").putImageData(ihl, 0, 0); chl2.getContext("2d").putImageData(ihl2, 0, 0); cbl.getContext("2d").putImageData(ibl, 0, 0); cw.getContext("2d").putImageData(iw, 0, 0);
    cache[key] = { inner: cin.toDataURL("image/png"), outer: cout.toDataURL("image/png"), hl: chl.toDataURL("image/png"), hl2: chl2.toDataURL("image/png"), bleed: cbl.toDataURL("image/png"), weights: cw.toDataURL("image/png"), W, H }; return cache[key]; }; })();
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
      + head("menu-glass-f3", 2) + `${highlight.replace(/in="ob"/g, 'in="SourceGraphic"')}</filter>`   /* f3's region = the panel box + 2: its primitives are all per pixel (no blur, no offset) and .menu-glass clips to the panel, so the ±120 margin was full-resolution work nobody saw (≈ 45 ms of the settle frame, 09-24 14:4x) */
      + head("menu-glass-f") + `${levelBlur}${refraction}${blurFill}${maxLuma}${faceCM}${bleed}${highlight}</filter>`
      + head("menu-glass-f0") + `<feGaussianBlur in="SourceGraphic" stdDeviation="${k.BlurRadius * 4}" result="blur"/>${blurFill}${maxLuma}${faceCM}</filter>`
      + `<filter id="menu-glass-ring" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="${k.RingShadowBlurRadius}"/></filter>`; const g = gres(); for (const id of ["menu-glass-f0", "menu-glass-f1", "menu-glass-f2"]) shrink(document.getElementById(id), g); return k; };
  /* the ring band: the rounded rect (the panel's box) shifted RingShadowOffset down, the band = the shape minus the same shape inset by the stroke width (evenodd) */
  const ringPath = (w, h, r, off, sw) => { const rr = (x, y, ww, hh, rad) => { const q = Math.max(0, Math.min(rad, ww / 2, hh / 2)); return `M${x + q} ${y}H${x + ww - q}A${q} ${q} 0 0 1 ${x + ww} ${y + q}V${y + hh - q}A${q} ${q} 0 0 1 ${x + ww - q} ${y + hh}H${x + q}A${q} ${q} 0 0 1 ${x} ${y + hh - q}V${y + q}A${q} ${q} 0 0 1 ${x + q} ${y}Z`; };
    return rr(0, off, w, h, r) + " " + rr(sw, off + sw, w - 2 * sw, h - 2 * sw, Math.max(0, r - sw)); };
  const buildGlass = (panel, W, H) => { const theme = glassTheme(), k = ensureFilter(theme, W, H); const main = document.getElementById("app"); if (!main) return null;
    const layer = document.createElement("div"); layer.className = "menu-glass"; const page = main.cloneNode(true); page.removeAttribute("id"); page.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); page.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim").forEach((e) => e.remove()); page.querySelectorAll(".held").forEach((e) => e.classList.remove("held")); page.className = "menu-glass-page"; page.setAttribute("aria-hidden", "true"); page.inert = true;
    const G = gres(), mr = main.getBoundingClientRect(), ph = Math.max(mr.height, innerHeight + 200); page.style.cssText = `position:absolute;left:0;top:0;width:${mr.width}px;min-height:${ph}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor};transform:scale(${1 / G});transform-origin:0 0`;
    const copy = document.createElement("div"); copy.className = "menu-glass-copy"; copy.style.cssText = `position:absolute;left:0;top:0;width:${mr.width / G}px;height:${ph / G}px;pointer-events:none;filter:url(#menu-glass-f0)`; copy.appendChild(page);   // the morph's chain; the full chain once settled (R63); the page colour under #app (body's, #app paints none — R57′: a transparent-backed copy blurred to α < 1 let the live page through the glass)
    const ring = document.createElementNS(NS, "svg"); ring.setAttribute("class", "menu-glass-ring"); ring.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;mix-blend-mode:multiply;pointer-events:none;overflow:visible"; const path = document.createElementNS(NS, "path"); path.setAttribute("fill", "#000"); path.setAttribute("fill-rule", "evenodd"); path.setAttribute("fill-opacity", String(k.RingShadowOpacity)); path.setAttribute("filter", "url(#menu-glass-ring)"); ring.appendChild(path);
    const w2 = document.createElement("div"), w3 = document.createElement("div"); w2.className = "menu-glass-w2"; w3.className = "menu-glass-w3"; for (const w of [w2, w3]) w.style.cssText = "position:absolute;left:0;top:0;width:100%;pointer-events:none";
    const up = document.createElement("div"); up.className = "menu-glass-up"; up.style.cssText = `position:absolute;left:0;top:0;width:100%;pointer-events:none;transform:scale(${G});transform-origin:0 0`;   // the glass background back to page units (gres)
    w2.appendChild(copy); up.appendChild(w2); w3.appendChild(up); layer.append(w3, ring); panel.insertBefore(layer, panel.firstChild);
    return { layer, copy, page, w2, w3, outer: w3, ring, path, mr, theme, keys: k }; };
  const placeGlass = (g, s, U) => { if (!g) return; const w = s.width.x, h = s.height.x, r = cornerNow(s);
    if (U) { g.path.setAttribute("transform", `translate(${s.left.x - U.left} ${s.top.x - U.top})`); g.path.setAttribute("d", ringPath(w, h, r, g.keys.RingShadowOffset, g.keys.RingShadowStrokeWidth)); return; }   // morphing: the layer sits on U (setMorph), the copy's translate is fixed there, only the ring's path moves
    g.path.removeAttribute("transform"); g.outer.style.transform = `translate(${g.mr.left - s.left.x}px, ${g.mr.top - s.top.x}px)`;   // the copy (in its wrappers) stays on the page's pixels while the panel moves

    g.ring.setAttribute("viewBox", `0 0 ${Math.max(1, w)} ${Math.max(1, h)}`); g.path.setAttribute("d", ringPath(w, h, r, g.keys.RingShadowOffset, g.keys.RingShadowStrokeWidth)); };
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
  const strokeMaps = {}, strokeMap = (W, H, r, k, dpr) => { const key = `${W}x${H} ${r} ${dpr} ${JSON.stringify(k)}`; if (strokeMaps[key]) return strokeMaps[key]; const E = 3, S = Math.cos(k.KeyFillHighlightSpreadSDR), a = 1 / k.KeyFillHighlightAmount - 2, h = k.KeyFillHighlightHeight, fw = 1 / dpr, dir = [Math.sin(k.KeyFillHighlightAngle), -Math.cos(k.KeyFillHighlightAngle)];
    const w = Math.round((W + 2 * E) * dpr), hh = Math.round((H + 2 * E) * dpr), c = document.createElement("canvas"); c.width = w; c.height = hh; const ctx = c.getContext("2d"), id = ctx.createImageData(w, hh); let kmax = 0, kside = 0, ktop = 0;
    for (let j = 0; j < hh; j++) for (let i = 0; i < w; i++) { const x = (i + .5) / dpr - E - W / 2, y = (j + .5) / dpr - E - H / 2; const [d, gsx, gsy] = sdfSuper(x, y, W / 2, H / 2, r); const [gx, gy] = gOval(x, y, W / 2, H / 2, gsx, gsy, k.GradientOvalization); const o = (j * w + i) * 4; let kk = 0;   // R63″: n·dir on the ovalized normal
      const cov = satf(0.5 - d / fw);
      if (!(d - h >= fw / 2 || cov >= 1)) { const e = h - d, v = (1 - cov) * satf(e / fw + 0.5), nd = gx * dir[0] + gy * dir[1];
        for (const sgn of [1, -1]) { const ang = satf((sgn * nd - S) / (1 - S)), va = v * ang; kk += va / (1 + a * (1 - va)); } kk = Math.min(1, kk); }
      id.data[o] = id.data[o + 1] = id.data[o + 2] = Math.round(255 * kk); id.data[o + 3] = 255; kmax = Math.max(kmax, kk);
      if (Math.abs(y) < 0.5 && x < -W / 2 && x > -W / 2 - 1.5 * fw) kside = Math.max(kside, kk); if (Math.abs(x) < 0.5 && y < -H / 2 && y > -H / 2 - 1.5 * fw) ktop = Math.max(ktop, kk); }
    ctx.putImageData(id, 0, 0); return (strokeMaps[key] = { href: c.toDataURL("image/png"), E, dpr, kmax, kside, ktop, key }); };
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
    el.style.cssText = `position:fixed;left:${L}px;top:${T}px;width:${W + 2 * E}px;height:${H + 2 * E}px;overflow:hidden;pointer-events:none;z-index:8;clip-path:path(evenodd, "${roundRect(E - h - fw, E - h - fw, W + 2 * (h + fw), H + 2 * (h + fw), r + h + fw)} ${roundRect(E + fw / 2, E + fw / 2, W - fw, H - fw, Math.max(0, r - fw / 2))}")`;
    const page = main.cloneNode(true); page.removeAttribute("id"); page.querySelectorAll("[id]").forEach((e) => e.removeAttribute("id")); page.querySelectorAll("canvas, .lens-clip, script, .menu, .menu-scrim, .menu-stroke").forEach((e) => e.remove()); page.querySelectorAll(".held").forEach((e) => e.classList.remove("held")); page.className = "menu-stroke-page"; page.inert = true;
    const mr = g.mr; page.style.cssText = `position:absolute;left:${mr.left - L}px;top:${mr.top - T}px;width:${mr.width}px;min-height:${Math.max(mr.height, innerHeight + 200)}px;pointer-events:none;background:${getComputedStyle(document.body).backgroundColor}`;
    /* the filter sits on a box at the layer's origin, the page inside it: WebKit took this userSpaceOnUse region from the layer's origin, not from the filtered element's
       own box (simulator D 09-24 11:4x: a red feFlood on the page-sized copy at x 149 / y 502 painted nothing, at 0 / 0 it filled the layer's box), so the region
       placed in the copy's own units missed the band and the stroke came out empty. Both engines read (0, 0) here as the layer's corner. */
    const copy = document.createElement("div"); copy.className = "menu-stroke-copy"; copy.style.cssText = `position:absolute;left:0;top:0;width:${W + 2 * E}px;height:${H + 2 * E}px;pointer-events:none;filter:url(#menu-stroke-f)`; copy.appendChild(page);
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
    requestAnimationFrame(() => requestAnimationFrame(() => { if (cur && cur.glass === g && cur.panel && !g.stroke) { g.stroke = buildStroke(g, cur.panel, cur.to, R); followStroke(); } })); };   // the stroke one frame after the chain (the staging below); followStroke puts it on the moving box in the frame it is built
  /* the morph's geometry (menu-open fix, simulator D 09-24 00:51–01:0x, mrun frame stamps + Timeline Paint rects): WebKit re-rendered the copy's whole url() filter
     region every frame the panel's left / top / width / height changed — its clip box moved (only the panel's box frozen gave frames: 15 in 700 ms vs 2–3; frozen size
     or frozen position alone, a fixed-size glass layer, no drop-shadow, no clip: all still 120–170 ms a frame). So while it morphs the panel stays on its rest box,
     unclipped, and the shape is a clip-path: the glass layer sits on a fixed box U (source ∪ target, plus the spring's first overshoot) cut by inset(… round r), the
     content layer moves by a transform and is cut the same way (14–15 frames in 700 ms). At rest the old styles come back (restStyles), so the menu paints as before. */
  const OVER = Math.exp(-APPEAR[0] * Math.PI / Math.sqrt(1 - APPEAR[0] ** 2));   // an underdamped spring's first overshoot per unit of travel (ζ .8: 1.52 %; DISMISS shares ζ)
  const boxOf = (s) => ({ left: s.left.x, top: s.top.x, width: s.width.x, height: s.height.x });
  const morphBox = (a, b) => { const l = Math.min(a.left, b.left), t = Math.min(a.top, b.top), r = Math.max(a.left + a.width, b.left + b.width), bt = Math.max(a.top + a.height, b.top + b.height);
    const m = 2 + Math.ceil(OVER * Math.max(Math.abs(a.left - b.left) + Math.abs(a.width - b.width), Math.abs(a.top - b.top) + Math.abs(a.height - b.height)));   // an edge travels ≤ |Δleft| + |Δwidth|
    return { left: Math.floor(l - m), top: Math.floor(t - m), width: Math.ceil(r - l + 2 * m), height: Math.ceil(bt - t + 2 * m) }; };
  const setMorph = (U) => { const p = cur.panel.style, T = cur.rest, g = cur.glass; cur.U = U;
    p.left = T.left + "px"; p.top = T.top + "px"; p.width = T.width + "px"; p.height = T.height + "px"; p.overflow = "visible"; p.borderRadius = "";
    if (g) { const l = g.layer.style; l.inset = "auto"; l.left = U.left - T.left + "px"; l.top = U.top - T.top + "px"; l.width = U.width + "px"; l.height = U.height + "px"; l.borderRadius = "0";
      g.ring.setAttribute("viewBox", `0 0 ${U.width} ${U.height}`); g.outer.style.transform = `translate(${g.mr.left - U.left}px, ${g.mr.top - U.top}px)`; } };
  const restStyles = () => { const p = cur.panel.style, s = cur.s, g = cur.glass; cur.U = null; p.overflow = ""; cur.body.style.transform = ""; cur.body.style.clipPath = "";
    cur.body.style.opacity = cur.body.style.filter = "";   // settled() stops within .001 of p = 1: the last frame's blur(0.001px) left on the body rendered as a visible blur on WebKit once the glass copy was filtered again (simulator D 09-24 11:3x: text edge gradient 27 with it, 248 with blur(0px))
    p.left = s.left.x + "px"; p.top = s.top.x + "px"; p.width = s.width.x + "px"; p.height = s.height.x + "px"; p.borderRadius = s.r.x + "px";
    if (g) { const l = g.layer.style; l.inset = l.left = l.top = l.width = l.height = l.borderRadius = l.clipPath = ""; g.ring.setAttribute("viewBox", `0 0 ${Math.max(1, s.width.x)} ${Math.max(1, s.height.x)}`); }
    placeGlass(g, s); };
  const apply = () => { const p = cur.panel.style, s = cur.s, T = cur.rest; let U = cur.U; p.opacity = String(Math.max(0, Math.min(1, s.a.x)));
    if (s.left.x < U.left || s.top.x < U.top || s.left.x + s.width.x > U.left + U.width || s.top.x + s.height.x > U.top + U.height) setMorph(U = morphBox(U, boxOf(s)));   // past U (a dismiss from a panel still moving): grow it, one repaint
    const x = s.left.x - U.left, y = s.top.x - U.top, w = s.width.x, h = s.height.x, r = cornerNow(s);   // ≥ 0: a negative round() makes the whole clip-path invalid and the old one stays
    if (cur.glass) cur.glass.layer.style.clipPath = `inset(${y}px ${U.width - x - w}px ${U.height - y - h}px ${x}px round ${r}px)`;
    const bs = cur.body.style; bs.transform = `translate(${s.left.x - T.left}px, ${s.top.x - T.top}px)`; bs.clipPath = `inset(0 ${cur.bw - w}px ${cur.bh - h}px 0 round ${r}px)`;   // the content at the shape's corner, cut by the same shape
    /* G22 (NATIVE-GAP G22 driver ①, AnimationKit 0x1de425df0, crossBlurWhenMorphing 1 read by probe G22 19:05): the shown layer (the menu content) has opacity p and a
       gaussianBlur inputRadius 4(1 − p) (σ = inputRadius, NATIVE-GAP G8); p's overshoot above 1 is clamped by CSS opacity and a blur cannot be negative */
    const b = cur.body.style, q = s.p.x; b.opacity = q >= 1 ? "" : String(Math.max(0, q)); b.filter = q >= 1 ? "" : `blur(${(4 * (1 - q)).toFixed(3)}px)`;
    /* the hidden layer = the button (the source, hidden by the morph and shown through its copy): its own progress runs 1 → 0 on the same spring (the g22 blur table:
       the two layers' presented opacities sum to 1 on every frame, 6.71 s …), so opacity 1 − p, radius 4p; at rest open it stays at 0, the dismiss brings it back */
    if (!cur.reduced && cur.anchor) { const a = cur.anchor.style; a.opacity = q <= 0 ? "" : String(Math.max(0, Math.min(1, 1 - q))); a.filter = q <= 0 ? "" : `blur(${(4 * Math.max(0, q)).toFixed(3)}px)`; btnRaise(cur.anchor); btnMorph(cur.anchor, q, cur.move); }
    /* the tail is gone once the button is back (p ≤ 0): native shows nothing of #0 around the button from +350 ms of the dismiss on (nat.mov, 2号 0924-白点
       halo2.png, frames 3870–4120 ms), while the page's 17-pt tail kept its glass / rim / stroke / drop-shadow under the raised button until the strip at +800 ms
       (≤ 8 levels through the title, w7 vs w8 Chrome 394×2.75). Hidden at the first p ≤ 0 frame (+364 ms, w8 DOM); the spring runs on to its settle and strips
       as before. The button-area change that goes on to ~+700 ms is the button's own overshoot (scale ≤ 1.0113 at +450 ms, DISMISS ζ .8 / .49), as native's
       (its title 48.67 → 49.33 pt wide at +392–485 ms, back by +517 ms, nat.mov). 近似: 已查 菜单-圆角淡出变宽-数据-0924.md 表 1 (#0 view and PivotView α stay 1 to the end)，缺 why native's glass draws no
       shadow / rim for the tail inside the button */
    /* dark: the dismiss tail's glass is 12–17 levels brighter than the page and shows through the button title's gaps from +171 ms (验收 0924, dot-dark.png; native
       dark stays within ±2 levels of the rest button from +193 ms, 菜单-复核-数据-0924.md item 1): on the dismiss the glass (w3, ring) goes out ahead of the shown layer,
       α p². Background pixels in the button's 24-pt box over the rest frame, Chrome 394×2.75 dark (2号 0924-暗圆 gap.py): before 41–44 levels at +171–286 ms;
       α p 23–30 with the disc still seen to +246 ms (dotF-dark.png); α p² 21–25 (dotS-dark.png), the same as the glass taken out entirely, 19–25 (dZ.json: the
       rest is the button's own blur 4p, as native's PivotView). On WebKit with w3 not a layer of its own (f3 waits for rest, glassFull) the fade costs no frame:
       close 46–47 frames / 800 ms, the only > 25 ms one the f3-off step at +20 ms, as without it (simulator D 22:4x, 2号 mo2.js). Not the stroke: its opacity cost
       one 232 ms frame (d1.json; no filter re-run while it only moves) and hiding it changed nothing (dZ2.json). 近似: 已查 菜单-圆角淡出变宽-数据-0924.md 表 1，缺 the
       reason native's small tail matches the page */
    if (cur.phase === "out" && cur.glass) { const g = cur.glass, ga = q >= 1 ? "" : String(Math.max(0, q) ** 2); g.w3.style.opacity = g.ring.style.opacity = ga; }
    if (cur.phase === "out" && q <= 0 && !cur.tailHidden) { cur.tailHidden = true; cur.panel.style.visibility = "hidden"; if (cur.glass && cur.glass.stroke) cur.glass.stroke.style.visibility = "hidden"; }
    placeGlass(cur.glass, s, U); followStroke(); };
  /* the stroke comes on before the tail has settled (see tick): it is built on the rest box, so until rest it is moved and scaled onto the panel's box by a transform
     (the box ratio, no re-render of its filter); the corner differs from the panel's by the tail's r change (≤ 1.1 pt at the diagonal: first open R 125 − 93·1.028) */
  const followStroke = () => { const g = cur && cur.glass; if (!g || !g.stroke) return; const st = g.stroke.style; if (!cur.U) { st.transform = ""; return; }
    const s = cur.s, T = cur.rest; st.transform = `translate(${s.left.x + s.width.x / 2 - T.left - T.width / 2}px, ${s.top.x + s.height.x / 2 - T.top - T.height / 2}px) scale(${s.width.x / T.width}, ${s.height.x / T.height})`; };
  const settled = (goal) => Object.keys(goal).every((k) => k === "p" ? Math.abs(cur.s.p.x - goal.p) < 0.001 && Math.abs(cur.s.p.v) < 0.02 : Math.abs(cur.s[k].x - goal[k]) < 0.05 && Math.abs(cur.s[k].v) < 1);   // p is a 0…1 opacity: .05 would end the loop on a visible step
  const strip = () => { if (!cur) return; cancelAnimationFrame(cur.raf); if (cur.anchor) btnClear(cur.anchor); if (cur.glass && cur.glass.stroke) { cur.glass.stroke.remove(); cur.glass.stroke = null; } cur.panel.remove(); cur.scrim.remove(); removeEventListener("keydown", onKey); cur = null; document.dispatchEvent(new Event("menu-closed")); };   // view.js holds a re-render while a menu is up and runs it here
  const tick = (now) => { if (!cur) return;
    if (now <= cur.prev) { cur.raf = requestAnimationFrame(tick); return; }
    if (cur.hold) { cur.hold = false; cur.prev = cur.t0 = now; cur.t = 0; cur.frame = 1; apply(); cur.raf = requestAnimationFrame(tick); return; }   // the dismiss's first frame shows the start value, the spring starts on this frame (g22-blur-table.txt: model written 7.732, presented 7.760 still the old value, moving from 7.794 — 2 frames after the write)   // a frame stamped before the spring's start (Chrome: rAF's `now` is the frame's start, which can precede the call): nothing to integrate yet, the time base stays
    const dt = Math.min(1, (now - cur.prev) / 1000); cur.prev = now;   // time-based like a CA spring: a stalled frame lands where the clock says (the analytic step is exact for any dt); no 40 ms clamp — that clamp made the panel fall behind its own closed form after every long frame (验收 00:2x: rms 7 pt under load), only a > 1 s stall is cut
    const goal = cur.phase === "in" ? cur.goalIn : cur.goalOut, spec = cur.phase === "in" ? (cur.reduced ? REDUCE : APPEAR) : (cur.reduced ? REDUCE : DISMISS);
    const derivedR = cur.phase === "in" && !cur.reduced, pPrev = cur.s.p.x;   // the open's r is derived (openR), not sprung
    for (const k of Object.keys(goal)) if (!(derivedR && k === "r")) Motion.spring(cur.s[k], goal[k], k === "p" && !cur.reduced ? (cur.phase === "in" ? CROSS : CROSS_OUT) : spec, dt);   // p: its own spring (G22), the dismiss's its own
    cur.tPrev = cur.t; cur.t = (now - cur.t0) / 1000; cur.frame = (cur.frame || 0) + 1;   // the driver's own clock: every frame's x is the closed form at this t (the analytic step is exact)
    if (derivedR) { cur.s.r.x = openR(cur, pPrev); cur.s.r.v = 0; }
    apply();
    /* 渲染有延迟 (用户 09-24 20:47 / 21:34): the finished edge used to come on late (7aec6ba: at p's first pass of 1; before it at the settle) — the stroke and
       f1 + f2 are now on from the open's first frame (glassMorph), only f3 waits for rest (glassFull) */
    if (settled(derivedR ? { ...goal, r: cur.s.r.x } : goal) && (!derivedR || cur.first || cur.s.r.x === R)) { if (cur.phase === "out") { strip(); return; } cur.raf = 0; for (const k of Object.keys(goal)) { cur.s[k].x = goal[k]; cur.s[k].v = 0; } restStyles();   // rests ON the goal (a spring ends at its target): the stroke map below is then the same key every open (cached)
       followStroke(); glassFull(cur.glass, true); return; }   // "in" settled: the panel rests, the loop stops; f3 comes on (see glassFull)
    cur.raf = requestAnimationFrame(tick); };
  const run = () => { if (cur.raf) cancelAnimationFrame(cur.raf); cur.prev = performance.now(); cur.raf = requestAnimationFrame(tick); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function open(anchor, sel, o) {   // o.reduced: the reduce-motion path forced (the acceptance's hook; the page never passes it — the media query decides)
    strip();
    const scrim = document.createElement("div"); scrim.className = "menu-scrim";
    const panel = document.createElement("div"); panel.className = "menu morph"; panel.setAttribute("role", "menu");
    const body = document.createElement("div"); body.className = "menu-body"; panel.appendChild(body);
    for (const o of sel.options) {
      const b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "menuitemradio"); if (o.selected) b.classList.add("on");
      const ck = document.createElement("i"); ck.className = "ck"; const sym = typeof SYM !== "undefined" && SYM["checkmark"];   // view.js's SYM is a top-level const (not on window)
      if (sym) ck.setAttribute("style", `-webkit-mask-image:url(${sym});mask-image:url(${sym})`);
      b.appendChild(ck); b.appendChild(document.createTextNode(o.textContent));
      b.onclick = () => { const t = cur ? livePair(cur.sel, cur.anchor).sel : sel, to = [...t.options].some((x) => x.value === o.value) ? t : sel;   // the select on screen now (see livePair)
        if (to.value !== o.value) { to.value = o.value; to.dispatchEvent(new Event("change", { bubbles: true })); } close(); };
      body.appendChild(b);
    }
    scrim.onclick = close;
    document.body.append(scrim, panel);
    const h = body.offsetHeight;   // items × 42 + the 10 / 10 insets
    const glass = buildGlass(panel, 250, h);
    const from = seedRect(anchor), to = restRect(anchor, h), reduced = o && o.reduced != null ? !!o.reduced : reduce();
    placeGlassRest(glass, to);
    const start = reduced ? { ...to } : from;
    const s = { left: { x: start.left, v: 0 }, top: { x: start.top, v: 0 }, width: { x: start.width, v: 0 }, height: { x: start.height, v: 0 }, r: { x: reduced ? R : W / 2, v: 0 }, a: { x: reduced ? 0 : 1, v: 0 }, p: { x: reduced ? 1 : 0, v: 0 } };
    cur = { panel, body, scrim, sel, anchor, from, to, s, reduced, glass, phase: "in", goalIn: { left: to.left, top: to.top, width: to.width, height: to.height, r: R, a: 1, p: 1 }, goalOut: null, prev: 0, raf: 0, t0: 0, rest: to, bw: body.offsetWidth, bh: h, U: null, move: btnMove(anchor, to), rl: !reduced, first: opened++ === 0, turn: null };   // rl: r in the layer's units from the start (the seed square's 125 → its half side 8.58)
    setMorph(morphBox(start, to)); apply(); addEventListener("keydown", onKey); run(); cur.t0 = cur.prev; glassMorph(glass);   // one material from the first frame (see glassFull)   // t0 = the spring's start (the call's performance.now()): the closed form x(t) holds at t = frame timestamp − t0
  }
  function close() {
    if (!cur) return;
    if (cur.phase === "out") return;
    const lp = livePair(cur.sel, cur.anchor); if (lp.anchor !== cur.anchor) { btnClear(cur.anchor); cur.move = btnMove(lp.anchor, cur.rest); } cur.sel = lp.sel; cur.anchor = lp.anchor;   // a re-render while open replaced the button: morph back to the one on screen
    const back = cur.anchor.isConnected ? seedRect(cur.anchor) : cur.from;   // the start square on the button now (the page may have scrolled); an unfindable button: where it was at the open
    cur.phase = "out"; cur.from = { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x }; cur.to = back;
    cur.goalOut = cur.reduced ? { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x, r: R, a: 0 } : { left: back.left, top: back.top, width: back.width, height: back.height, r: W / 2, a: 1, p: 0 };
    if (!cur.reduced) { const k = W / Math.max(1, cur.s.width.x); cur.s.r.x = cornerNow(cur.s) * k; cur.s.r.v *= k; cur.rl = true; }   // r into the layer's units (see cornerNow): at rest k = 1
    cur.scrim.style.pointerEvents = "none"; setMorph(morphBox(boxOf(cur.s), back)); glassFull(cur.glass, false); run(); cur.t0 = cur.prev; cur.t = 0; cur.frame = 0; cur.hold = !cur.reduced;   // the dismiss morph on the light chain (R63); hold: see tick
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
  document.addEventListener("pointerdown", (e) => { if (!e.isPrimary || e.button !== 0) return; const b = e.target.closest && e.target.closest("main .menubtn"); unhold(); if (b) { held = b; b.classList.add("held"); } }, true);
  document.addEventListener("pointerup", (e) => { if (!held || !e.isPrimary) return; const b = held, r = b.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) { unhold(); return; }
    clearTimeout(heldT); heldT = setTimeout(() => { if (held === b) unhold(); }, HELD_UP); }, true);
  document.addEventListener("pointercancel", unhold, true);
  const onHidden = (force) => { if (force || document.hidden) { unhold(); strip(); } };
  document.addEventListener("visibilitychange", () => onHidden(false));
  /* first open as fast as the second (验收 09-24 14:19, 菜单打开 首开 101.7 每秒卡顿; simulator D tl2 / tl3: the first open spent 122 ms in glassImages / ensureFilter, every
     settle 45–72 ms in strokeMap): the glass maps and the stroke's k map for every menu on the page (W 250, H = options × 42 + 20 = what open() measures, r = R at rest)
     are made in idle slots after load, the way alert-glass.js warms its stroke */
  const idle = (fn) => (window.requestIdleCallback ? requestIdleCallback(fn, { timeout: 3000 }) : setTimeout(fn, 1500));
  const warmUp = () => { try { const th = glassTheme(), k = glassKeys(th), dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1));
    for (const H of new Set([...document.querySelectorAll("main select.native")].map((s) => s.options.length * 42 + 20))) { idle(() => glassImages(W, H, k)); idle(() => strokeMap(W, H, R, k, dpr)); } } catch (e) {} };
  if (document.readyState === "complete") idle(warmUp); else addEventListener("load", () => idle(warmUp), { once: true });
  window.Menu = { glass: { keys: glassKeys, built: BUILT, unbuilt: UNBUILT, gOval, sdf: sdfSuper, theme: glassTheme, bleedSigma: () => mixStd(lod(glassKeys(glassTheme()).BleedBlurRadius)) / CAPTURE, images: glassImages }, morph: MORPH, springs: { appear: [...APPEAR], dismiss: [...DISMISS], reduce: [...REDUCE], cross: [...CROSS], crossOut: [...CROSS_OUT] }, open, close, onHidden, state: () => cur ? { phase: cur.phase, from: { ...cur.from }, to: { ...cur.to }, reduced: cur.reduced, t0: cur.t0, t: cur.t || 0, frame: cur.frame || 0, settled: !cur.raf, first: !!cur.first, turn: cur.turn,   // settled: read-only (S1, 2号 13:1x) — the "in" morph rests (its loop stopped, the full glass on); the "out" morph strips cur, so state() null = closed
    x: { left: cur.s.left.x, top: cur.s.top.x, width: cur.s.width.x, height: cur.s.height.x, a: cur.s.a.x, p: cur.s.p.x, r: cornerNow(cur.s) }, move: { ...cur.move },
    v: { left: cur.s.left.v, top: cur.s.top.v, width: cur.s.width.v, height: cur.s.height.v, a: cur.s.a.v, p: cur.s.p.v } } : null };   // v: read-only (2号 14:4x) — the springs' velocities (pt/s, opacity/s): the dismiss starts from the rested "in" state, whose |v| < 1 pt/s (settled) is not 0, so the acceptance's closed form takes it
})();
