/* accept-menu.js — acceptance of the value row's pull-down menu (BOARD.md #3, night batch). Registered through ACCEPT.add; runs inside
   accept.js's page (light and dark runs).
   What is checked, and the numbers it is checked against:
   ① appear: the panel's left / top / width / height each follow the closed-form spring ζ .8 / response .3 s (menu-motion-formula.md §0 table
      "出现（长大）弹簧", §2) from the anchor button's rect to the resting menu rect. Per frame two readings — the driver's spring value and clock
      (Menu.state().x / .t) and the panel's getBoundingClientRect() — and two checks: the spring value is x(t) = target + (start − target)·
      e^(−ζωt)(cos ωd t + ζω/ωd · sin ωd t), ω = 2π/.3, on the driver's own clock (rms ≤ .01 pt: the analytic step is exact), and the DOM shows
      the spring value (rect − x, rms ≤ 1 pt = twice the rounding of a rect read at 1 px).
   ② dismiss: the same four properties follow ζ .8 / .3 — the same liquidMorph spec as the appear (menu-motion-formula.md §8b ①, R19″: liquidMorphShrink
      ζ .9 has no reader in AnimationKit) — from the resting rect back to the anchor's rect, same two checks; one step, no intermediate shape, no .03 s
      second step (§8b ③: useIntermediateShape 0 everywhere) — Menu.morph says so and the springs' sole target is the destination rect.
   ③ no dimming: the scrim's background alpha is 0 (§0 "压暗": _hasVisibleBackground NO).
   ④ geometry at rest: width 250, corner 32 (menu-card-material.md §1.2: defaultMenuWidth, menuCornerRadius).
   ⑤ real-device template (BOARD A6, the applicable ones): hidden → the menu is gone (state stripped); the panel's resting background equals the
      page's --alert-fill token in this theme (the material itself is untouched tonight — A5). */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptMenu(ctx) {
    const { check, num, sleep } = ctx;
    const cs = (el) => getComputedStyle(el);
    if (!window.Menu) { check("菜单：Menu 未装载（motion.js 未到 → 旧路径）", "Menu", "缺", false); return; }
    const btn = document.querySelector("main .menubtn"); const sel = btn && btn.previousElementSibling;
    if (!btn || !sel || sel.tagName !== "SELECT") { check("菜单：页面上没有值行按钮可测", "有", "缺", false); return; }
    /* long values (NATIVE-GAP 省略号三处, 数据 20:18): the native popup button wraps by word (titleLabel numberOfLines 0) and grows taller;
       a clone beside the real button, 120 wide, carries a long value — it must take more than one 22 line and cut nothing */
    {
      const c = btn.cloneNode(false); c.style.width = "120px"; c.style.maxWidth = "120px"; c.textContent = "Tokyo Shinjuku Shibuya Ikebukuro Ueno";
      btn.parentNode.insertBefore(c, btn.nextSibling);
      const h = c.getBoundingClientRect().height, cut = c.scrollWidth > c.clientWidth + 0.5 || cs(c).textOverflow === "ellipsis";
      c.remove();
      check("值行按钮长值按词换行、随之长高、不截断（popbtn numberOfLines 0）", "高 > 22 · 不截", `高 ${h.toFixed(1)} · ${cut ? "截" : "不截"}`, h > 22.5 && !cut);
    }
    for (const [k, q] of [["通知横幅标题", ".ntitle"], ["磁贴标题", ".ttitle"]]) {
      const el = document.querySelector(q); if (!el) continue;
      const s = cs(el);
      check(`${k}一行尾部省略、不缩字（lineBreakMode 4）`, "nowrap · ellipsis", `${s.whiteSpace} · ${s.textOverflow}`, s.whiteSpace === "nowrap" && s.textOverflow === "ellipsis" && s.overflow === "hidden");
    }
    /* the closed-form spring, ζ < 1 (the same expression view.js springStep / Motion.spring integrate) */
    const closed = (start, target, zeta, resp, t, v0 = 0) => { const w = 2 * Math.PI / resp, wd = w * Math.sqrt(1 - zeta * zeta), e = Math.exp(-zeta * w * t), dx = start - target;
      return target + e * (dx * Math.cos(wd * t) + ((v0 + zeta * w * dx) / wd) * Math.sin(wd * t)); };   // v0: the start velocity (0 for a morph from rest; the dismiss leaves the "in" rest with |v| < 1 pt/s, menu.js settled — v0 = 0 there read rms .01 = the tolerance, both clocks)
    const rms = (a) => Math.sqrt(a.reduce((s, v) => s + v * v, 0) / Math.max(1, a.length));
    const rect = (el) => { const r = el.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width, height: r.height }; };
    /* the shape the page shows: while it morphs the panel stays on its rest box and the shape is the glass layer's clip-path inset (menu.js setMorph);
       at rest (no clip-path) it is the panel's own box */
    const shown = (panel) => { const g = panel.querySelector(".menu-glass"), m = g && /^inset\(([-\d.]+)px ([-\d.]+)px ([-\d.]+)px ([-\d.]+)px/.exec(g.style.clipPath);
      if (!m) return rect(panel); const r = g.getBoundingClientRect(), [t, rt, b, l] = m.slice(1).map(Number); return { left: r.left + l, top: r.top + t, width: r.width - l - rt, height: r.height - t - b }; };
    /* t = the frame's timestamp − the spring's start (Menu.state().t0, the open / close call's performance.now()): the page integrates the same
       closed form step by step on these timestamps, so the sample of frame k must equal x(t_k) exactly (up to the rect's rounding) */
    /* two readings per frame: the panel's rect (what the DOM shows) and the driver's own state (Menu.state(): x = the spring's value, t = its clock).
       Two checks come out of them (验收 00:2x: the one-piece check "rect vs closed form on the sampler's timestamps" read 6–7 pt under load — a frame
       in which the sampler and the driver did not run together, whichever side it was): ① the DOM shows the driver's value (rect − x, ≤ 1 pt = twice
       the rounding of a rect read at 1 px); ② the driver's value is the closed form on its own clock (x − x(t), ≤ .01 pt: the analytic step is exact) */
    /* S1 (SPEED2, 2号 13:1x): the sampler ends at the driver's own flags — Menu.state().settled (the "in" morph at rest, menu.js) or the panel gone (the "out"
       morph stripped) — with ms as the cap; the fixed sleeps below are waits on the same flags, capped at the old length */
    const frame = () => new Promise((r) => requestAnimationFrame(r));
    const until = async (cond, cap) => { const t0 = performance.now(); while (!cond()) { if (performance.now() - t0 >= cap) return null; await frame(); } return performance.now() - t0; };
    const sample = (panel, ms) => new Promise((resolve) => { const out = []; let first = null;
      const tick = (now) => { if (first === null) first = now; if (!panel.isConnected) { resolve(out); return; }   // removed on settle (the dismiss): the frame's read would be zeros
        const st = Menu.state(); if (st) { const bd = panel.querySelector(".menu-body"), bs = bd ? cs(bd) : null, bm = bs ? /blur\(([\d.]+)px\)/.exec(bs.filter) : null; out.push({ t: st.t, r: shown(panel), x: { ...st.x }, op: parseFloat(cs(panel).opacity), bo: bs ? parseFloat(bs.opacity) : NaN, bb: bm ? +bm[1] : 0, ...btnLayer() }); } if (now - first < ms && !(st && st.settled)) requestAnimationFrame(tick); else resolve(out); };
      requestAnimationFrame(tick); });
    const btnLayer = () => { const s = cs(btn), m = /blur\(([\d.]+)px\)/.exec(s.filter), tm = /^matrix\(([^)]+)\)/.exec(s.transform), mv = tm ? tm[1].split(",").map(Number) : [1, 0, 0, 1, 0, 0], ci = /^inset\(0px ([-\d.]+)px/.exec(s.clipPath);
      return { ao: parseFloat(s.opacity), ab: m ? +m[1] : 0, bs: mv[0], bx: mv[4], by: mv[5], bc: ci ? +ci[1] : 0 }; };   // the hidden layer (G22): the anchor button; bs / bx / by / bc = its morph (scale, translate, side clip; menu.js btnMorph)
    const fit = (samples, from, to, zeta, resp, v0) => { const res = {}; for (const k of ["left", "top", "width", "height"]) {
      res[k] = { dom: rms(samples.map((s) => s.r[k] - s.x[k])), model: rms(samples.map((s) => s.x[k] - closed(from[k], to[k], zeta, resp, s.t, v0 ? v0[k] : 0))) }; } return res; };
    btn.scrollIntoView({ block: "center" }); await until(() => { const r = btn.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }, 100);   // the value row on screen, as a finger would find it
    const a0 = rect(btn);
    /* ① appear */
    btn.click(); await new Promise((r) => requestAnimationFrame(r));
    const panel = document.querySelector(".menu.morph"); if (!panel) { check("菜单：点值行后有 .menu.morph 面板", "有", "缺", false); return; }
    const st = Menu.state(); const open = await sample(panel, 900); await frame();   // one paint after the settle: the full chain / stroke rows below read the rested panel
    const fin = fit(open, st.from, st.to, 0.75, 0.35);
    /* the open's corner (BOARD/菜单-圆角淡出变宽-数据-0924.md ④): on screen min(short side / 2, R × width / 250); R = 125 − 93p on the page's first open,
       else the layer's half height 125 − 73p to p .9238 and then the probe's per-frame R (采样替代) to 32 — checked against that rule frame by frame */
    { const st9 = Menu.state(), fr = open.filter((o) => o.x.r != null && o.t > 0 && o.x.width > 0), last = fr[fr.length - 1];
      const expect = (o) => { const p = o.x.p, lay = st9.first ? 125 - 93 * p : (st9.turn == null || o.t < st9.turn ? 125 - 73 * p : null); return lay == null ? null : Math.min(o.x.width / 2, o.x.height / 2, lay * o.x.width / 250); };
      const pre = fr.filter((o) => expect(o) != null);
      num(`菜单出现 圆角 = min(短边 / 2, R × 宽 / 250) rms（pt，${pre.length} 帧，${st9.first ? "首开 R = 125 − 93p" : "再开 转点前 R = 125 − 73p"}；④ 1–3）`, 0, pre.length ? rms(pre.map((o) => o.x.r - expect(o))) : NaN, 0.01);
      if (!st9.first) check("菜单出现 再开 p 过 .9238 后转到逐帧 R 表（④ 3，采样替代）", "有转点 · 落定 32", `转点 ${st9.turn == null ? "无" : (st9.turn * 1000).toFixed(0) + " ms"} · 末帧 ${last ? last.x.r.toFixed(2) : "无"}`, st9.turn != null && !!last && Math.abs(last.x.r - 32) < 0.05); }
    for (const k of ["left", "top", "width", "height"]) { num(`菜单出现 ${k}：弹簧值对 ζ.75/r.35 闭式 rms（pt，${open.length} 帧，驱动自己的时钟；几何与 p 同一根，数据 00:11 运行条目 + R18a 逐帧）`, 0, fin[k].model, 0.01); num(`菜单出现 ${k}：面板矩形 = 弹簧值 rms（pt）`, 0, fin[k].dom, 1); }
    /* G22 (NATIVE-GAP G22 driver ① ③): the menu content is the morph's shown layer — opacity p, gaussianBlur 4(1 − p) (σ = inputRadius, G8) — and p rides its own
       spring ζ .75 / .35 from 0 (Parameters.morphSpring, probe uiprobe-motion-g22spring10-A.json), not the geometry's ζ .8 / .3 */
    { const ps = open.filter((o) => o.x.p != null && o.t > 0), clamp = (v) => Math.max(0, Math.min(1, v));
      num(`菜单出现 交叉模糊 p：对 ζ.75/r.35 闭式 0→1 rms（${ps.length} 帧，驱动自己的时钟）`, 0, rms(ps.map((o) => o.x.p - closed(0, 1, 0.75, 0.35, o.t))), 0.001);
      num("菜单出现 内容透明度 = clamp(p) rms（G22：显出层透明度 = p）", 0, rms(ps.map((o) => o.bo - clamp(o.x.p))), 0.01);
      num("菜单出现 内容模糊 = 4(1 − p) rms（px；G22：半径 = 4 ×（1 − p））", 0, rms(ps.map((o) => o.bb - Math.max(0, 4 * (1 - o.x.p)))), 0.02);
      num("菜单出现 按钮（隐去层）透明度 = clamp(1 − p) rms（G22：隐去层 p_h = 1 − p）", 0, rms(ps.map((o) => o.ao - clamp(1 - o.x.p))), 0.01);
      num("菜单出现 按钮模糊 = 4p rms（px；G22：隐去层半径 = 4 × p）", 0, rms(ps.map((o) => o.ab - Math.max(0, 4 * o.x.p))), 0.02);
      /* the button's own morph (菜单-原生无底框按钮形状-数据-0924.md, MagicMorphView #1): scale 1 → .25, centre a quarter of the way to the panel's centre,
         bounds clipped about the centre from the button's width to BTN_H 34.3333 — all on p. The strip it fixes (剩余第 3 条): the button's right end, arrows
         included, showing beside the panel for ~.2 s after the open; natively covered from the 3rd frame on (rowS table) */
      const mv = st.move || { x: NaN, y: NaN }, BH = 34.3333, bw = a0.width;
      num("菜单出现 按钮缩放 = 1 − .75p rms（原生 #1 落定 .25）", 0, rms(ps.map((o) => o.bs - (1 - 0.75 * o.x.p))), 0.002);
      num("菜单出现 按钮位移 = p · ¼(菜单中心 − 按钮中心) rms（pt）", 0, rms(ps.flatMap((o) => [o.bx - mv.x * o.x.p, o.by - mv.y * o.x.p])), 0.01);
      num("菜单出现 按钮两侧裁 = (宽 − 34.3333)·p / 2 rms（pt；原生 #1 边界变 高×高）", 0, rms(ps.map((o) => o.bc - Math.max(0, (mv.w - BH) * o.x.p / 2))), 0.01);
      num("菜单出现 按钮宽 = 打开前量的宽（pt）", a0.width, mv.w, 0.01);
      num("菜单出现 目标位移 = ¼(静止框中心 − 按钮中心)（x，pt）", 0.25 * (st.to.left + st.to.width / 2 - a0.left - a0.width / 2), mv.x, 0.01);
      const strip = ps.slice(3).filter((o) => { const right = a0.left + a0.width / 2 + o.bx + o.bs * (bw / 2 - o.bc); return o.ao > 0.02 && right > o.r.left + o.r.width + 0.5; });
      check("菜单出现 第 3 帧后按钮右端不露在面板外（原生第 3 帧起盖住）", "0 帧", `${strip.length} 帧${strip.length ? `（首个 t ${strip[0].t.toFixed(3)}）` : ""}`, strip.length === 0);
      const f1 = ps[0]; check("菜单出现 首帧内容几乎透明且糊（p 从 0 起，原生显出层呈现透明度 0 → .0979 → …）", "p < .2, 模糊 > 3", f1 ? `p ${f1.x.p.toFixed(3)}, 模糊 ${f1.bb.toFixed(2)}` : "无帧", !!f1 && f1.x.p < 0.2 && f1.bb > 3); }
    /* R19 (menu-motion-formula.md §7b, R18b): no per-item delay — every item is fully opaque and in place on the first frame after the open (the
       list view has no stagger); the intermediate shape (a geometry step) waits for its rect's formula (待读), so nothing else to check */
    { const items = [...panel.querySelectorAll(".menu-body button")]; const ops = items.map((b) => parseFloat(cs(b).opacity)); const rects = items.map((b) => b.getBoundingClientRect().height);
      check(`菜单项无逐项延迟（§7b）：首帧后 ${items.length} 项 opacity 全 1、各 42 高`, "全 1 · 42", `${ops.map((v) => v.toFixed(2)).join("/")} · ${rects.map((h) => h.toFixed(0)).join("/")}`, items.length > 0 && ops.every((v) => v === 1) && rects.every((h) => Math.abs(h - 42) <= 0.5)); }
    /* ④ rest geometry */
    const rr = rect(panel); num("菜单静止宽（menu-card-material §1.2 defaultMenuWidth）", 250, rr.width, 0.5);
    num("菜单静止圆角（§1.2 menuCornerRadius）", 32, parseFloat(cs(panel).borderTopLeftRadius), 0.5);
    num("菜单静止位置 = 目标（top）", st.to.top, rr.top, 0.5); num("菜单静止位置 = 目标（left）", st.to.left, rr.left, 0.5);
    /* the native start / end shapes (数据 09-24 11:43, BOARD/菜单-原生无底框按钮形状-数据-0924.md, rowS / rowL-motion.json): a 17.1667 pt square on the
       button's centre; at rest the panel's top on the 34.3333 pt button frame's top, its right on the button's right */
    const cx = a0.left + a0.width / 2, cy = a0.top + a0.height / 2, fitsBelow = cy - 34.3333 / 2 + rr.height <= innerHeight - 8;
    num("菜单出现起点 = 按钮中心 17.1667 方块（width）", 17.1667, st.from.width, 0.01); num("菜单出现起点 = 按钮中心 17.1667 方块（中心 x 偏差）", 0, st.from.left + st.from.width / 2 - cx, 0.01); num("菜单出现起点 = 按钮中心 17.1667 方块（中心 y 偏差）", 0, st.from.top + st.from.height / 2 - cy, 0.01);
    if (fitsBelow) num("菜单静止上边 = 原生按钮框上边（按钮中心 − 34.3333/2）", cy - 34.3333 / 2, rr.top, 0.5);
    if (innerWidth - (a0.left + a0.width) >= 8) num("菜单静止右边 = 按钮右边", a0.left + a0.width, rr.left + rr.width, 0.5);
    /* ③ no dimming */
    const scrim = document.querySelector(".menu-scrim"); const m = /rgba?\([^)]*?,\s*([\d.]+)\)$/.exec(scrim ? cs(scrim).backgroundColor : "");
    check("菜单后无压暗（scrim α = 0）", 0, scrim ? (m ? +m[1] : (cs(scrim).backgroundColor === "transparent" ? 0 : cs(scrim).backgroundColor)) : "无 scrim", !!scrim && (cs(scrim).backgroundColor === "transparent" || (m && +m[1] === 0) || cs(scrim).backgroundColor === "rgba(0, 0, 0, 0)"));
    /* R1 — the glass layer: keys = menu-glass-sdfdump-2026-09-19.md §2 (the table below is that table's light column + the dark differences), the
       layer exists, the built terms carry the keys (feGaussianBlur σ = BlurRadius × 4, the face matrix with the premultiplied fill, the ring band .06 / 8 / 4 / σ 5, clipped), the
       old sampled substitute is off (background transparent, no backdrop-filter, no box-shadow); nothing pixel-wise (BOARD A15) */
    { const DOC = { light: { GradientOvalization: 0.5,   // 数据 R109 (R63″)
        BlurRadius: 5, BlurDistance0: -83.5, BlurDistance1: -1, BlurDistance2: 0, BlurDistance3: 0, BlurOpacity0: 0.8, BlurOpacity1: 0.4, BlurOpacity2: 0.5, BlurOpacity3: 1, BlurFillBlurRadius: 8, BlurFillDarkenOpacity: 0, BlurFillLightenOpacity: 0.9, BlurFillNormalOpacity: 0.5,
        FaceColorMatrixWhite: 1.03, FaceColorMatrixBlack: 0.4, FaceColorMatrixSaturation: 1.2, FaceColorMatrixFillColor: [1, 1, 1, 0.2], FaceColorMatrixMaxLuma: 1, FaceColorMatrixMaxLumaSDR: 0.94, FaceOpacity: 1, Clamp: 1.07, ClampPreserveHue: 0,
        InnerRefractionAmount: -60, InnerRefractionHeight: 20, OuterRefractionAmount: 41.75, OuterRefractionHeight: 33.4, RefractionOpacity: 0.6, RefractionDistance0: -1, RefractionDistance1: 0,
        KeyFillHighlightAmount: 0.4, KeyFillHighlightAngle: 1.571, KeyFillHighlightColorBias: -0.3, KeyFillHighlightEffectOffset: -0.5333, KeyFillHighlightHeight: 0.5333, KeyFillHighlightSpread: 1.676, KeyFillHighlightSpreadSDR: 1.85,
        RingShadowOpacity: 0.06, RingShadowOffset: 8, RingShadowStrokeWidth: 4, RingShadowBlurRadius: 5, RingShadowMask: 1,
        BleedAmount: 58.45, BleedBlurRadius: 58.45, BleedHeight: 58.45, BleedOpacity: 0.5, BleedColorMatrixBlack: 0.9, BleedColorMatrixSaturation: 1.2, BleedColorMatrixWhite: 1, BleedDarkenBlend: 1, BleedDistance0: 1, BleedDistance1: 0,
        ShadowAmount: 0, ShadowOpacity: 0.4, ShadowRadius: 24, ShadowOffset: [0, 8], ShadowColorMatrixFillColor: [0, 0, 0, 0.3] },
      dark: { BlurFillDarkenOpacity: 0.9, BlurFillLightenOpacity: 0, FaceColorMatrixWhite: 1.125, FaceColorMatrixBlack: 0.125, FaceColorMatrixSaturation: 1.3, FaceColorMatrixFillColor: [0, 0, 0, 0], FaceColorMatrixMaxLuma: 0.35, FaceColorMatrixMaxLumaSDR: 0.35, Clamp: 1.308, KeyFillHighlightSpread: 1.309, KeyFillHighlightSpreadSDR: 1.309, BleedOpacity: 0.8, BleedColorMatrixBlack: 0.125, BleedColorMatrixSaturation: 1, BleedColorMatrixWhite: 0.5, BleedDarkenBlend: 0, ShadowOpacity: 0.6 } };
      const theme = Menu.glass ? Menu.glass.theme() : "light"; const want = { ...DOC.light, ...(theme === "dark" ? DOC.dark : {}) }; const got = Menu.glass ? Menu.glass.keys(theme) : {};
      const bad = Object.keys(want).filter((k) => JSON.stringify(want[k]) !== JSON.stringify(got[k]));
      check(`菜单玻璃键表 = sdfdump §2（${theme}，${Object.keys(want).length} 键）`, "全同", bad.length ? "差：" + bad.join(",") : "全同", bad.length === 0);
      const layer = panel.querySelector(".menu-glass"), copy = panel.querySelector(".menu-glass-copy"), f = document.getElementById("menu-glass-f"), blur = f && f.querySelector("feGaussianBlur"), ringP = panel.querySelector(".menu-glass-ring path"), fr = document.getElementById("menu-glass-ring");
      check("菜单玻璃层存在（#app 复本 + 环影），在项之下", "layer+copy+ring", `${layer ? "layer" : "-"}+${copy ? "copy" : "-"}+${ringP ? "ring" : "-"}`, !!layer && !!copy && !!ringP && layer === panel.firstElementChild);
      num("菜单玻璃 模糊 σ = BlurRadius 5 × 4 pt（1/4 分辨率采样，alert-pipeline-plan §1.3）", 20, blur ? parseFloat(blur.getAttribute("stdDeviation")) : NaN, 0.01);
      /* R57′: the fill is folded into the face matrix, premultiplied (alert-native-formula §4 ⑦ set_ycc_composite): grey bias = (1 − a)·Black + a·1 → .52 light (a .2), .125 dark (a 0) */
      { const fm = f && f.querySelector('feColorMatrix[result="out"]'), gm = fm ? fm.getAttribute("values").split(/\s+/).map(Number) : [], a = want.FaceColorMatrixFillColor[3], bias = (1 - a) * want.FaceColorMatrixBlack + a * want.FaceColorMatrixFillColor[0], gain = (1 - a) * (want.FaceColorMatrixWhite - want.FaceColorMatrixBlack);
        check(`菜单玻璃 面矩阵含预乘填充（白 α ${a}）：灰增益 (1 − a)(W − B) = ${gain.toFixed(4)}、偏置 (1 − a)B + a = ${bias.toFixed(4)}；无单独 flood`, `${gain.toFixed(4)} · ${bias.toFixed(4)} · 无 fill flood`, gm.length === 20 ? `${(gm[0] + gm[1] + gm[2]).toFixed(4)} · ${gm[4].toFixed(4)} · ${f.querySelector('feFlood[result="fill"]') ? "有 fill flood" : "无 fill flood"}` : "-", gm.length === 20 && Math.abs(gm[0] + gm[1] + gm[2] - gain) < 1e-3 && Math.abs(gm[4] - bias) < 1e-3 && !f.querySelector('feFlood[result="fill"]')); }
      check("菜单玻璃 环影带：α .06、偏移 8、带宽 4、σ 5、裁到面板（mask 1）", ".06 · 8 · 4 · σ5 · clip", ringP ? `${ringP.getAttribute("fill-opacity")} · ${/M\S+ (\S+)/.exec(ringP.getAttribute("d") || "")?.[1]} · ${fr ? fr.querySelector("feGaussianBlur").getAttribute("stdDeviation") : "-"} · ${layer ? cs(layer).overflow : "-"}` : "无", !!ringP && ringP.getAttribute("fill-opacity") === "0.06" && /^M\S+ 8H/.test(ringP.getAttribute("d") || "") && !!fr && fr.querySelector("feGaussianBlur").getAttribute("stdDeviation") === "5" && !!layer && cs(layer).overflow === "hidden" && cs(ringP.parentElement).mixBlendMode === "multiply");
      check("菜单面板旧底（采样替代）关：background transparent、无 backdrop-filter、无 box-shadow", "transparent · none · none", `${cs(panel).backgroundColor} · ${cs(panel).backdropFilter || cs(panel).webkitBackdropFilter} · ${cs(panel).boxShadow}`, cs(panel).backgroundColor === "rgba(0, 0, 0, 0)" && (cs(panel).backdropFilter || cs(panel).webkitBackdropFilter) === "none" && cs(panel).boxShadow === "none");
      const outer = panel.querySelector(".menu-glass-w3") || copy;   // R63: the translate sits on the outermost wrapper (three nested filtered elements)
      const mr = document.getElementById("app").getBoundingClientRect(), pr2 = panel.getBoundingClientRect(), tm = /matrix\(([^)]+)\)/.exec(cs(outer).transform), tx = tm ? tm[1].split(",").map(parseFloat) : null;
      check("菜单玻璃 复本对齐页面（translate = 页 − 面板）", `${(mr.left - pr2.left).toFixed(1)}, ${(mr.top - pr2.top).toFixed(1)}`, tx ? `${tx[4].toFixed(1)}, ${tx[5].toFixed(1)}` : "-", !!tx && Math.abs(tx[4] - (mr.left - pr2.left)) <= 1 && Math.abs(tx[5] - (mr.top - pr2.top)) <= 1);
      /* R1′ (menu-card-material.md §7): BlurFill, MaxLuma, the face matrix, the soft shadow — the filter's primitives carry the keys */
      const fm = f && f.querySelector('feColorMatrix[result="out"]');
      { const bfb2 = f && f.querySelector('feGaussianBlur[result="bfb"]'), offs = f ? [...f.querySelectorAll('feOffset[result="bfp"], feOffset[result="bfm"]')].map((e) => +e.getAttribute("dx")) : [];
        check("菜单玻璃 BlurFill（§7c R82 更正）：b = 未折射捕获在 mip 3（级 std 9.581 ÷ .25 = σ 38.32 pt）取本像素 ±.75 纹素（±24 pt）平均，与折射无关", "σ 38.32 · ±24 · SourceGraphic", `σ ${bfb2 ? bfb2.getAttribute("stdDeviation") : "-"} · ${offs.join("/")} · ${bfb2 ? bfb2.getAttribute("in") : "-"}`, !!bfb2 && Math.abs(+bfb2.getAttribute("stdDeviation") - 9.581 / 0.25) < 0.02 && offs.length === 2 && offs[0] === 24 && offs[1] === -24 && bfb2.getAttribute("in") === "SourceGraphic"); }
      { const dl = f && f.querySelector('feComposite[result="dl"]'), cmix = f && f.querySelector('feComposite[result="c0"]'), a1 = f && f.querySelector('feComponentTransfer[result="c"] feFuncA');
        check("菜单玻璃 BlurFill：darken·min + lighten·max + (1−d−l)·c，再 mix(·, bf, normal)（§7.2），末了 α 归 1（R57′：算术合成让 α 走到 .992，后面每个 feBlend 多加 (1 − α)·底）", `${want.BlurFillDarkenOpacity} · ${want.BlurFillLightenOpacity} · normal ${want.BlurFillNormalOpacity} · α[1]`, dl && cmix ? `${dl.getAttribute("k2")} · ${dl.getAttribute("k3")} · normal ${cmix.getAttribute("k3")} · ${a1 ? `α[${a1.getAttribute("tableValues")}]` : "-"}` : "无", !!dl && !!cmix && +dl.getAttribute("k2") === want.BlurFillDarkenOpacity && +dl.getAttribute("k3") === want.BlurFillLightenOpacity && +cmix.getAttribute("k3") === want.BlurFillNormalOpacity && !!a1 && a1.getAttribute("tableValues") === "1"); }
      /* R57′: MaxLuma as c·A(Y) − B(Y) (A = k(1.3 − .3k), B = .3(1 − k)kY, k = 1 − comp·Y — §7.1's formula regrouped by Y) in two 33-sample luma LUTs, α kept 1 */
      { const comp = 1 - want.FaceColorMatrixMaxLumaSDR, kOf = (Y) => 1 - comp * Y, Aw = (Y) => kOf(Y) * (1.3 - 0.3 * kOf(Y)), iBw = (Y) => 1 - 4 * 0.3 * (1 - kOf(Y)) * kOf(Y) * Y;
        const lA = f && f.querySelector('feComponentTransfer[result="A"] feFuncR'), lB = f && f.querySelector('feComponentTransfer[result="iB4"] feFuncR'), mlc = f && f.querySelector('feComposite[result="ml"]'), tA = lA ? lA.getAttribute("tableValues").split(/\s+/).map(Number) : [], tB = lB ? lB.getAttribute("tableValues").split(/\s+/).map(Number) : [];
        check(`菜单玻璃 MaxLuma 压亮（§7.1）：k = 1 − ${comp.toFixed(2)}·Y，c′ = c·A(Y) − B(Y)，A / (1 − 4B) 各 33 样 LUT（A(1) = ${Aw(1).toFixed(4)}，1 − 4B(1) = ${iBw(1).toFixed(4)}），合成 k3 .25 / k4 −.25`, `${Aw(1).toFixed(4)} · ${iBw(1).toFixed(4)} · 33 · .25/−.25`, `${tA.length ? tA[32].toFixed(4) : "-"} · ${tB.length ? tB[32].toFixed(4) : "-"} · ${tA.length} · ${mlc ? `${mlc.getAttribute("k3")}/${mlc.getAttribute("k4")}` : "-"}`, tA.length === 33 && tB.length === 33 && Math.abs(tA[32] - Aw(1)) < 1e-4 && Math.abs(tB[32] - iBw(1)) < 1e-4 && Math.abs(tA[16] - Aw(0.5)) < 1e-4 && !!mlc && mlc.getAttribute("k3") === ".25" && mlc.getAttribute("k4") === "-.25"); }
      { const expect = (() => { const W = want.FaceColorMatrixWhite, Bk = want.FaceColorMatrixBlack, sat = want.FaceColorMatrixSaturation; const white = [.2126, .7152, .0722]; const r0 = white.map((w) => (W - Bk) * w); // the Y row through YCC⁻¹ contributes (W−B)·luma to each channel; a full check re-derives the R row: R = Y' + 1.5748 Cr' − .7874
          const Cr = [.5, -.4542, -.0458], a = want.FaceColorMatrixFillColor[3]; const R = white.map((w, i) => (1 - a) * ((W - Bk) * w + 1.5748 * sat * Cr[i])); const Roff = (1 - a) * (Bk + 1.5748 * (sat * .5 + .5 - .5 * sat) - .7874) + a * want.FaceColorMatrixFillColor[0]; return { R, Roff }; })();   // R57′: × (1 − a), + a·fill (premultiplied fill folded in)
        const got = fm ? fm.getAttribute("values").split(/\s+/).map(parseFloat) : null;
        check("菜单玻璃 面矩阵 = (1 − a)·YCC⁻¹·D·YCC + a·fill（Rec.709；R 行核：(1 − a)((W−B)·luma + 1.5748·sat·Cr)，偏置 (1 − a)(B + 1.5748(.5 − .5sat + .5) − .7874) + a）", expect.R.map((v) => v.toFixed(4)).join(" ") + " | " + expect.Roff.toFixed(4), got ? got.slice(0, 3).map((v) => v.toFixed(4)).join(" ") + " | " + got[4].toFixed(4) : "无", !!got && expect.R.every((v, i) => Math.abs(v - got[i]) < 1e-4) && Math.abs(expect.Roff - got[4]) < 1e-4); }
      { const sh = cs(panel).filter; const m = /drop-shadow\(rgba\(0, 0, 0, ([\d.]+)\) 0px 8px 16.9706px\)/.exec(sh);
        check("菜单玻璃 软影（§7.3：amount 0 仍画）：黑 α .3 × ShadowOpacity、R 24 → σ 24/√2 = 16.9706（§7.3b：剖面 .5·erfc(d/R)，直边精确）、偏移 (0, 8)", `α ${(0.3 * want.ShadowOpacity).toFixed(2)} · 0 8 16.9706`, sh, !!m && Math.abs(parseFloat(m[1]) - 0.3 * want.ShadowOpacity) < 0.005); }
      /* R63: refraction (two displacement maps on the blurred backdrop, mixed by .6·sat((d + 1)/1)), the highlight layer (two stages through the dumped
         vibrant matrix), the bleed (σ 293 blur → outward map → bleed YCC matrix, weight Opacity · w · (luma or 1 − luma)⁴); the in-shader KeyFill = stroke_mode 1 → 待读 */
      { const dm = f ? [...f.querySelectorAll("feDisplacementMap")] : [], imgs = f ? [...f.querySelectorAll("feImage")].map((e) => e.dataset.menuImg) : [];
        check("菜单玻璃 折射（R63）：内 −60/20、外 41.75/33.4 两张位移图（scale 128）在模糊底上，权 .6·sat((d+1)/1)，再进 BlurFill", "c1 c2 · mapi mapo · wr", `${dm.filter((e) => /c[12]/.test(e.getAttribute("result"))).map((e) => e.getAttribute("result")).join(" ")} · ${imgs.filter((n) => /map[io]/.test(n)).map((n) => n.replace(/0$/, "")).join(" ")} · ${f && f.querySelector('feColorMatrix[result="wr"]') ? "wr" : "-"}`, dm.filter((e) => /c[12]/.test(e.getAttribute("result")) && +e.getAttribute("scale") === 128).length === 2 && imgs.includes("mapi0") && imgs.includes("mapo0") && !!f.querySelector('feComposite[result="blur"]'));
        const bb = f && f.querySelector('feGaussianBlur[result="bb"]'), tile = f && f.querySelector('feTile[result="tiled"]'), cb = f && f.querySelector('feColorMatrix[result="cb"]'), w4 = f && f.querySelector('feComponentTransfer[result="w4"] feFuncR'), lx = f && f.querySelector('feComponentTransfer[result="lx"] feFuncR');
        const bs = Menu.glass.bleedSigma ? Menu.glass.bleedSigma() : NaN, tw = w4 ? w4.getAttribute("tableValues").split(/\s+/).map(Number) : [];
        /* R57′: the bleed target = the capture box (panel ± 60, clamped to the copy) tiled and blurred σ = min(292.6, 300/3) = its mean (Chrome ignores edgeMode); the weight Opacity·L⁴ = one 65-sample LUT × w(d) */
        check(`菜单玻璃 Bleed（R63 / R57′）：捕获框平铺 + σ = min(级混 std(lod 5.87) ÷ .25 = ${bs.toFixed(1)}, 100) = 框均值、外推位移图、色矩阵 YCC(白 ${want.BleedColorMatrixWhite} 黑 ${want.BleedColorMatrixBlack} 饱和 ${want.BleedColorMatrixSaturation})、权 ${want.BleedOpacity}·(${want.BleedDarkenBlend ? "L" : "1 − L"})⁴ 65 样 LUT × w(d)`, `tile · σ ${Math.min(bs, 100).toFixed(2)} · cb · 65 样 末 ${want.BleedOpacity} · slope ${want.BleedDarkenBlend ? 1 : -1}`, `${tile ? "tile" : "-"} · σ ${bb ? bb.getAttribute("stdDeviation") : "-"} · ${cb ? "cb" : "-"} · ${tw.length} 样 末 ${tw.length ? tw[tw.length - 1] : "-"} · slope ${lx ? lx.getAttribute("slope") : "-"}`, !!tile && !!bb && Math.abs(parseFloat(bb.getAttribute("stdDeviation")) - Math.min(bs, 100)) < 0.01 && !!cb && tw.length === 65 && Math.abs(tw[64] - want.BleedOpacity) < 1e-5 && Math.abs(tw[32] - want.BleedOpacity / 16) < 1e-4 && !!lx && +lx.getAttribute("slope") === (want.BleedDarkenBlend ? 1 : -1));
        const v1 = f && f.querySelector('feColorMatrix[result="v1"]'), vv = v1 ? v1.getAttribute("values").split(/\s+/).map(Number) : [];
        check("菜单玻璃 高光层（R63）：两段带（主 1 pt + 漫 8 pt，spread 1.5253）经 dump 的 vibrantColorMatrix（1.1202 … .1471），两次 mix", "hl hl2 · 1.1202 · final", `${imgs.filter((n) => /^hl/.test(n)).map((n) => n.replace(/0$/, "")).join(" ")} · ${vv[0]} · ${f && f.querySelector('feComposite[result="final"]') ? "final" : "-"}`, imgs.includes("hl0") && imgs.includes("hl20") && Math.abs(vv[0] - 1.1202) < 1e-4 && Math.abs(vv[4] - 0.1471) < 1e-4 && !!f.querySelector('feComposite[result="final"]'));
        const pr3 = panel.getBoundingClientRect(), im0 = f && f.querySelector('feImage[data-menu-img="mapi0"]'), mr3 = document.getElementById("app").getBoundingClientRect();
        check("菜单玻璃 图与滤镜区随面板（复本坐标 = 面板框 − #app 框，宽高 = 面板）", `(${(pr3.left - mr3.left).toFixed(1)}, ${(pr3.top - mr3.top).toFixed(1)}) ${pr3.width.toFixed(0)}×${pr3.height.toFixed(0)}`, im0 ? `(${(+im0.getAttribute("x")).toFixed(1)}, ${(+im0.getAttribute("y")).toFixed(1)}) ${(+im0.getAttribute("width")).toFixed(0)}×${(+im0.getAttribute("height")).toFixed(0)}` : "-", !!im0 && Math.abs(+im0.getAttribute("x") - (pr3.left - mr3.left)) <= 1 && Math.abs(+im0.getAttribute("y") - (pr3.top - mr3.top)) <= 1 && Math.abs(+im0.getAttribute("width") - pr3.width) <= 1);
        await until(() => !!document.querySelector(".menu-stroke"), 200);   // f1 + f2 + f3 from the open's first frame and the stroke layer two frames later (menu.js glassMorph)
        /* R63′ (keyfill-highlight.md §2c): the in-shader KeyFill in stroke mode = a band OUTSIDE the panel (edge − fw/2 … edge + .5333 pt), its own fixed layer under the panel
           with a second page copy through #menu-stroke-f; k on the outer device pixel: sides 1 (n·dir = ±1), top / bottom 2 × .216/(1 + .5·.784) = .31 light (S = cos 1.85), 0 dark (S = cos 1.309 > 0) */
        { const sk = document.querySelector(".menu-stroke"), sf = document.getElementById("menu-stroke-f"), wantTop = theme === "dark" ? 0 : 2 * (0.216 / (1 + 0.5 * (1 - 0.216))), Sw = Math.cos(want.KeyFillHighlightSpreadSDR);
          check(`菜单玻璃 着色器内 KeyFill 描边（R63′ §2c，stroke_mode 1）：落定后描边层在 body（面板之前、z 8）、k 图 dpr 级：左右边外 1 px k 1、上下 ${wantTop.toFixed(2)}（S = cos SpreadSDR ${want.KeyFillHighlightSpreadSDR} = ${Sw.toFixed(3)}）、链 ${want.KeyFillHighlightColorBias < 0 ? "darken" : "lighten"} + (3x − 2x²) LUT + k4 保 α`, `层 · side 1 · top ${wantTop.toFixed(2)} · S ${Sw.toFixed(3)} · darken · LUT 33 · bias .3`,
            sk && sf ? `${sk.previousElementSibling === panel || sk.nextElementSibling === panel ? "层" : "层(位置?)"} · side ${sf.dataset.kside} · top ${sf.dataset.ktop} · S ${sf.dataset.s} · ${sf.querySelector('feBlend[result="bmin"]')?.getAttribute("mode")} · LUT ${(sf.querySelector('feComponentTransfer[result="qh"] feFuncR')?.getAttribute("tableValues") || "").split(/\s+/).length} · bias ${sf.dataset.bias}` : "无描边层",
            !!sk && !!sf && sk.nextElementSibling === panel && Math.abs(+sf.dataset.kside - 1) <= 0.02 && Math.abs(+sf.dataset.ktop - wantTop) <= 0.03 && Math.abs(+sf.dataset.s - Sw) < 1e-3 && sf.querySelector('feBlend[result="bmin"]')?.getAttribute("mode") === (want.KeyFillHighlightColorBias < 0 ? "darken" : "lighten") && (sf.querySelector('feComponentTransfer[result="qh"] feFuncR')?.getAttribute("tableValues") || "").split(/\s+/).length === 33 && +sf.dataset.bias === -want.KeyFillHighlightColorBias);
          check("菜单玻璃 描边层裁到形外一圈（clip-path evenodd：外 = 面板 + .5333 + fw、内 = 面板 − fw/2）、第二份页面复本对齐（复本 left = #app − 层）", "clip evenodd · 复本对齐", sk ? `${/evenodd/.test(sk.style.clipPath) ? "clip evenodd" : "clip?"} · ${(() => { const c = sk.querySelector(".menu-stroke-page"); if (!c) return "无复本"; const cr = c.getBoundingClientRect(), ar = document.getElementById("app").getBoundingClientRect(); return Math.abs(cr.left - ar.left) < 0.6 && Math.abs(cr.top - ar.top) < 0.6 ? "复本对齐" : `复本偏 ${(cr.left - ar.left).toFixed(1)},${(cr.top - ar.top).toFixed(1)}`; })()}` : "无描边层",
            !!sk && /evenodd/.test(sk.style.clipPath) && (() => { const c = sk.querySelector(".menu-stroke-page"); if (!c) return false; const cr = c.getBoundingClientRect(), ar = document.getElementById("app").getBoundingClientRect(); return Math.abs(cr.left - ar.left) < 0.6 && Math.abs(cr.top - ar.top) < 0.6; })());
          /* R63″ (数据 R109: the menu's elements' gradientOvalization .5; §4 ⑨): the map directions on g = normalize(mix(shape normal, normalize((x, hw/hh·y)), .5)) — read back from the inner map at the top edge x = +90 (2 pt inside) */
      { const im = Menu.glass.images(250, panel.offsetHeight, want), W = 250, H = panel.offsetHeight, xq = 90.25, yq = -H / 2 + 2.25, gs = Menu.glass.sdf(xq, yq, W / 2, H / 2, 32), gA = Menu.glass.gOval(xq, yq, W / 2, H / 2, gs[1], gs[2], want.GradientOvalization), ang = Math.atan2(gA[0], -gA[1]) * 180 / Math.PI, angS = Math.atan2(gs[1], -gs[2]) * 180 / Math.PI;
        const dec = await new Promise((res) => { const img = new Image(); img.onload = () => { const c = document.createElement("canvas"); c.width = img.width; c.height = img.height; const x = c.getContext("2d"); x.drawImage(img, 0, 0); const ppp = img.width / W, px = Math.round((W / 2 + 90) * ppp), py = Math.round(2 * ppp); const d = x.getImageData(px, py, 1, 1).data; res([(d[0] - 128) / 255 * 128, (d[1] - 128) / 255 * 128]); }; img.onerror = () => res(null); img.src = im.inner; });
        const sgn = Math.sign(want.InnerRefractionAmount) || 1, angMap = dec ? Math.atan2(sgn * dec[0], -sgn * dec[1]) * 180 / Math.PI : NaN;
        check(`菜单玻璃 梯度椭圆化 .5（R109 键；§4 ⑨ 只改梯度）：键 .5；顶边 x = +90（内 2 pt）形法线 ${angS.toFixed(1)}° → 椭圆化后 ${ang.toFixed(1)}°，内折射图同点 ${isNaN(angMap) ? "-" : angMap.toFixed(1)}°（±3°）`, ".5 · 椭圆化后 > 形法线 · 图 = 式 ± 3°", `${want.GradientOvalization} · ${angS.toFixed(1)}° → ${ang.toFixed(1)}° · 图 ${isNaN(angMap) ? "-" : angMap.toFixed(1)}°`, want.GradientOvalization === 0.5 && ang > angS + 5 && !isNaN(angMap) && Math.abs(angMap - ang) < 3); }
      check("菜单玻璃 着色器内 KeyFill 已建（Menu.glass.built，撤 R63 待读）", "built", Menu.glass.built["KeyFillHighlight* (in-shader, stroke_mode 1)"] ? "built" : "-", !!Menu.glass.built["KeyFillHighlight* (in-shader, stroke_mode 1)"] && !Menu.glass.unbuilt["KeyFillHighlight* (in-shader)"]); }
        /* the rest chain runs split over three nested elements (f1 blur + refraction on the copy, f2 BlurFill … fill on wrapper 2, f3 bleed + highlight on wrapper 3) ; all three run
           through the whole morph (one material, no swap; w3 is its own compositing layer so WebKit keeps f3's image: menu.js glassMorph); f0 is no longer used */
        const w2 = panel.querySelector(".menu-glass-w2"), w3 = panel.querySelector(".menu-glass-w3");
        check("菜单玻璃 三段链全程就位（复本 f1 · 包 2 f2 · 包 3 f3）", "f1 · f2 · f3", `${copy && copy.style.filter} · ${w2 && w2.style.filter} · ${w3 && w3.style.filter}`, !!copy && /menu-glass-f1/.test(copy.style.filter) && !!w2 && /menu-glass-f2/.test(w2.style.filter) && !!w3 && /menu-glass-f3/.test(w3.style.filter)); }
      /* R57′: the five-grey flat check (scripts/mac/glass-flat.py menu: the page a flat grey with only the button kept, the menu opened and settled, the panel's centre sampled in
         headless Chrome at dpr 3) against alert-native-formula §4 ⑦'s closed chain from the menu's keys (no dimming: the menu has no UIDimmingView); the numbers are this build's run (2026-09-20) */
      { const comp = 1 - want.FaceColorMatrixMaxLumaSDR, a = want.FaceColorMatrixFillColor[3], chain = (Dv) => { const c1 = Dv * (1 - comp * Dv), c2 = (1 - a) * ((want.FaceColorMatrixWhite - want.FaceColorMatrixBlack) * c1 + want.FaceColorMatrixBlack) + a;
          const w = (want.BleedDarkenBlend ? c2 ** 4 : ((1 - c2) ** 2) ** 2) * want.BleedOpacity, cb = (want.BleedColorMatrixWhite - want.BleedColorMatrixBlack) * Dv + want.BleedColorMatrixBlack; return (c2 + w * (cb - c2)) * 255; };
        const measured = theme === "dark" ? [122, 128, 115, 81, 33] : [254, 232, 204, 170, 136], pred = [255, 192, 128, 64, 0].map((g) => chain(g / 255)), dmax = Math.max(...measured.map((m, i) => Math.abs(m - pred[i])));
        check(`菜单玻璃 五灰阶平底核（${theme === "dark" ? "暗" : "亮"}，⑦ 闭链不调暗：${pred.map((v) => v.toFixed(1)).join(" / ")}；无头 Chrome 实测记录）`, "|Δ| ≤ 1.25/255", `${measured.join(" / ")} · |Δ|max ${dmax.toFixed(2)}`, dmax <= 1.25); }
      check("菜单玻璃 未接项已列（Menu.glass.unbuilt）", "≥ 4 项", Menu.glass ? Object.keys(Menu.glass.unbuilt).length + " 项" : "-", !!Menu.glass && Object.keys(Menu.glass.unbuilt).length >= 4); }
    /* ② dismiss (the scrim tap = cancel = the reverse morph) */
    const from2 = rect(panel), v0 = (Menu.state() || {}).v, p0 = ((Menu.state() || {}).x || {}).p ?? 1; scrim.click(); await new Promise((r) => requestAnimationFrame(r));   // v0: the rested "in" springs' velocities (the loop stopped at settle: frozen until the close)
    const st2 = Menu.state(); const close = await sample(panel, 900);
    const fout = fit(close, st2.from, st2.to, 0.8, 0.49, v0);
    /* G22 dismiss (data probe 09-24 00:1x, NATIVE-GAP last rows): p runs back 1 → 0 on its own spring ζ .8 / response .49 (stiffness 164.42; the four
       destinations one spring), the same two layer formulas — content opacity p / blur 4(1 − p), button opacity 1 − p / blur 4p */
    check("菜单收回 点击后首帧停在起点、次帧才动（g22-blur-table 7.732 写模型 → 7.760 仍旧值 → 7.794 起动）", "t 0 · p = 起点 · 框不动", `t ${st2.t} · p ${st2.x.p === p0 ? "= 起点" : st2.x.p} · Δw ${(st2.x.width - st2.from.width).toFixed(3)}`, st2.t === 0 && st2.x.p === p0 && st2.x.width === st2.from.width && st2.x.top === st2.from.top);
    { const cp = close.filter((o) => o.x.p != null && o.t > 0), clamp = (v) => Math.max(0, Math.min(1, v)), vp = v0 && v0.p ? v0.p : 0;
      num(`菜单收回 交叉模糊 p：对 ζ.8/r.49 闭式 1→0 rms（${cp.length} 帧，驱动自己的时钟）`, 0, cp.length ? rms(cp.map((o) => o.x.p - closed(p0, 0, 0.8, 0.49, o.t, vp))) : NaN, 0.001);
      num("菜单收回 内容透明度 = clamp(p) rms", 0, cp.length ? rms(cp.map((o) => o.bo - clamp(o.x.p))) : NaN, 0.01);
      num("菜单收回 内容模糊 = 4(1 − p) rms（px）", 0, cp.length ? rms(cp.map((o) => o.bb - Math.max(0, 4 * (1 - o.x.p)))) : NaN, 0.02);
      num("菜单收回 按钮透明度 = clamp(1 − p) rms", 0, cp.length ? rms(cp.map((o) => o.ao - clamp(1 - o.x.p))) : NaN, 0.01);
      num("菜单收回 按钮模糊 = 4p rms（px）", 0, cp.length ? rms(cp.map((o) => o.ab - Math.max(0, 4 * o.x.p))) : NaN, 0.02);
      /* the tail's corner (BOARD/菜单-圆角淡出变宽-数据-0924.md ①): natively a circle — on-screen radius = the short side / 2 within .17 pt from 540 ms on (frame
         ≤ 32.8 pt), the end square 17.2 at 8.58. The open's corner: ④, checked with the open above */
      const tail = close.filter((o) => o.x.r != null && Math.max(o.x.width, o.x.height) <= 32.8);
      num(`菜单收回 尾巴圆角 = 短边 / 2 rms（pt，${tail.length} 帧，框 ≤ 32.8；原生差 ≤ .17）`, 0, tail.length ? rms(tail.map((o) => o.x.r - Math.min(o.x.width, o.x.height) / 2)) : NaN, 0.17); }
    check("菜单变形一步走（R19″ / §8b ③）：无中间形、无 .03 s 第二步；几何弹簧 = p 的运行条目 开 ζ.75/.35、关 ζ.8/.49（数据 00:11，R18a 逐帧核）；RM ζ1/.15；crossBlur 探针读到 1（G22 19:05）、出现与收回两段接上（G22；收回 p ζ.8/.49 数据 00:1x）", "oneStep · intermediate 0 · appear .75/.35 · dismiss .8/.49 · reduce 1/.15 · crossBlur 1 appear+dismiss · p .75/.35 → .8/.49", Menu.morph ? `${Menu.morph.oneStep ? "oneStep" : "steps"} · intermediate ${Menu.morph.useIntermediateShape} · appear ${Menu.springs.appear.join("/")} · dismiss ${Menu.springs.dismiss.join("/")} · reduce ${Menu.springs.reduce.join("/")} · crossBlur ${Menu.morph.crossBlur.read} ${/^appear \+ dismiss/.test(String(Menu.morph.crossBlur.wired)) ? "appear+dismiss" : "?"} · p ${Menu.springs.cross.join("/")} → ${Menu.springs.crossOut.join("/")}` : "no Menu.morph", !!Menu.morph && Menu.morph.oneStep && Menu.morph.useIntermediateShape === 0 && Menu.springs.appear[0] === 0.75 && Menu.springs.appear[1] === 0.35 && Menu.springs.dismiss[0] === 0.8 && Menu.springs.dismiss[1] === 0.49 && Menu.springs.reduce[0] === 1 && Menu.springs.reduce[1] === 0.15 && Menu.morph.crossBlur.read === 1 && /^appear \+ dismiss/.test(String(Menu.morph.crossBlur.wired)) && Menu.springs.crossOut[0] === 0.8 && Menu.springs.crossOut[1] === 0.49);
    for (const k of ["left", "top", "width", "height"]) { num(`菜单收回 ${k}：弹簧值对 ζ.8/r.49 闭式 rms（pt，${close.length} 帧，自静止态的 x / v 起；几何与收回 p 同一根，数据 00:11；解析步精确，.01 = 浮点余量）`, 0, fout[k].model, 0.01); num(`菜单收回 ${k}：面板矩形 = 弹簧值 rms（pt）`, 0, fout[k].dom, 1); }
    num("菜单收回目标 = 按钮中心 17.1667 方块（width）", 17.1667, st2.to.width, 0.01); num("菜单收回目标 = 按钮中心 17.1667 方块（top）", a0.top + a0.height / 2 - 17.1667 / 2, st2.to.top, 0.5); num("菜单收回起点 = 静止框（width）", from2.width, st2.from.width, 0.5);
    await until(() => !Menu.state(), 300); check("菜单收回后面板移除", "无", document.querySelector(".menu.morph") ? "还在" : "无", !document.querySelector(".menu.morph"));
    check("菜单收回后描边层移除（R63′；描边开后两帧建、随形变移）", "无", document.querySelector(".menu-stroke") ? "还在" : "无", !document.querySelector(".menu-stroke"));
    /* R32 — reduce motion (menu-motion-formula.md §0 "减少动态效果": liquidMorphReduceMotion ζ 1 / response .15, a cross-fade): the geometry is at the
       resting rect from the first frame, the opacity follows ζ 1 / .15 from 0 to 1 on the driver's clock; the dismiss fades to 0 the same way, geometry
       unchanged. Forced through Menu.open's hook (the runner cannot set prefers-reduced-motion) */
    { Menu.open(btn, sel, { reduced: true }); await new Promise((r) => requestAnimationFrame(r)); const pr = document.querySelector(".menu.morph"), sr = Menu.state();
      const critical = (start, target, resp, t, v0 = 0) => { const w = 2 * Math.PI / resp, dx = start - target; return target + (dx + (v0 + w * dx) * t) * Math.exp(-w * t); };   // ζ 1 with the start velocity
      const smp = await sample(pr, 500);
      const geo = rms(smp.flatMap((s) => ["left", "top", "width", "height"].map((k) => s.r[k] - sr.to[k])));
      num("菜单减少动态效果：几何从首帧起 = 静止框（rms，pt）", 0, geo, 1);
      num(`菜单减少动态效果：opacity 对 ζ1/.15 闭式 0 → 1 rms（${smp.length} 帧，驱动时钟）`, 0, rms(smp.map((s) => s.x.a - critical(0, 1, 0.15, s.t))), 0.01);
      num("菜单减少动态效果：面板计算 opacity = 弹簧值（同帧读，rms）", 0, rms(smp.map((s) => s.op - s.x.a)), 0.02);
      const before = Menu.state(); document.querySelector(".menu-scrim").click(); await new Promise((r) => requestAnimationFrame(r)); const s2 = Menu.state(); const out2 = await sample(pr, 500);
      num("菜单减少动态效果 收回：opacity 对 ζ1/.15 闭式 → 0 rms（自静止态的 a / v 起）", 0, rms(out2.map((s) => s.x.a - critical(before.x.a, 0, 0.15, s.t, before.v ? before.v.a : 0))), 0.01);
      num("菜单减少动态效果 收回：几何不动（rms，pt）", 0, rms(out2.flatMap((s) => ["left", "top", "width", "height"].map((k) => s.r[k] - s2.from[k]))), 1);
      await until(() => !Menu.state(), 200); check("菜单减少动态效果 收回后面板移除", "无", document.querySelector(".menu.morph") ? "还在" : "无", !document.querySelector(".menu.morph")); }
    /* ④ a later open (BOARD/菜单-圆角淡出变宽-数据-0924.md ④ 3, rdrv.py rowS segment 2): R = 125 − 73p up to p .9238, then the probe's per-frame R
       (ms after that crossing; 采样替代) — the screen corner = min(short side / 2, R × width / 250) */
    { const T = [[0, 57.56], [17, 53.5], [33, 45.84], [50, 39.96], [67, 35.63], [84, 32.61], [100, 30.64], [117, 29.48], [134, 28.92], [150, 28.78], [167, 28.92], [184, 29.23],
        [200, 29.63], [217, 30.05], [234, 30.46], [250, 30.83], [267, 31.16], [284, 31.42], [300, 31.63], [317, 31.79], [334, 31.91], [350, 31.99], [367, 32]];
      const tab = (ms) => { if (ms >= 367) return 32; let i = 1; while (T[i][0] < ms) i++; const [a, ra] = T[i - 1], [b, rb] = T[i]; return ra + (rb - ra) * Math.max(0, ms - a) / (b - a); };
      Menu.open(btn, sel); const pr = document.querySelector(".menu.morph"), ro = await sample(pr, 1500), sr = Menu.state(), fr = ro.filter((o) => o.x.r != null && o.t > 0 && o.x.width > 0), last = fr[fr.length - 1];
      const lay = (o) => sr.turn == null || o.t < sr.turn ? 125 - 73 * o.x.p : tab((o.t - sr.turn) * 1000), ex = (o) => Math.min(o.x.width / 2, o.x.height / 2, lay(o) * o.x.width / 250);
      const pb = fr.filter((o) => sr.turn != null && o.t < sr.turn), pa = fr.filter((o) => sr.turn != null && o.t >= sr.turn), at = fr.find((o) => sr.turn != null && o.t >= sr.turn);
      check("菜单再开 不是首开、p 过 .9238 有转点（④ 3）", "再开 · 有转点", `${sr.first ? "首开" : "再开"} · 转点 ${sr.turn == null ? "无" : (sr.turn * 1000).toFixed(0) + " ms"}`, !sr.first && sr.turn != null);
      num(`菜单再开 转点前圆角 = min(短边 / 2, (125 − 73p) × 宽 / 250) rms（pt，${pb.length} 帧）`, 0, pb.length ? rms(pb.map((o) => o.x.r - ex(o))) : NaN, 0.01);
      num(`菜单再开 转点后圆角 = min(短边 / 2, 逐帧 R 表 × 宽 / 250) rms（pt，${pa.length} 帧，采样替代）`, 0, pa.length ? rms(pa.map((o) => o.x.r - ex(o))) : NaN, 0.01);
      num("菜单再开 落定圆角 32", 32, last ? last.x.r : NaN, 0.05);
      Menu.close(); await until(() => !Menu.state(), 1500); }
    /* ⑤ hidden strips the state */
    btn.click(); await until(() => !!Menu.state(), 50); document.dispatchEvent(new Event("visibilitychange", { bubbles: true })); Menu.onHidden(true); await until(() => !Menu.state(), 50);
    check("菜单：页面 hidden 时菜单剥掉", "无", document.querySelector(".menu.morph") ? "还在" : "无", !document.querySelector(".menu.morph"));
    /* ⑥ a re-render while the menu is up (live.js updateLive → render): view.js holds it until the menu is gone ("menu-closed"), so the button the
       menu is anchored to stays on the page through the retract (UITargetedPreview init(view:): "This view must be in a window") and the dismiss morphs
       back to it; the held render runs once after the close */
    if (typeof window.render === "function") {
      const b1 = document.querySelector("main .menubtn"); b1.click(); await until(() => !!Menu.state(), 50);
      window.render(); await new Promise((r) => requestAnimationFrame(r));
      const r1 = (() => { const tf = b1.style.transform; b1.style.transform = ""; const r = rect(b1); b1.style.transform = tf; return r; })();   // the button's own frame: its morph transform (menu.js btnMorph) is off in the menu's read too
      const r0 = window.render; let runs = 0; window.render = (...a) => { if (!Menu.state()) runs++; return r0(...a); };   // view.js's "menu-closed" listener calls the global render; only the calls that run count — a call while the menu is up is the one held (headless 09-24 11:0x: the hidden step's visibilitychange → live.js updateLive → render landed here while the menu was up, held, and was counted as a second render)
      const sc = document.querySelector(".menu-scrim"); if (sc) sc.click(); await new Promise((r) => requestAnimationFrame(r)); const s6 = Menu.state(), kept = b1.isConnected;
      check("菜单：开着时页面重绘先压住，收回回到原按钮（不缩到左上角）", `没换 · top ${(r1.top + r1.height / 2 - 17.1667 / 2).toFixed(1)}`, `${kept ? "没换" : "换了按钮"} · top ${s6 && s6.to ? s6.to.top.toFixed(1) : "-"}`,
        kept && !!s6 && !!s6.to && Math.abs(s6.to.top - (r1.top + r1.height / 2 - 17.1667 / 2)) < 0.5 && s6.to.width > 0);   // the end square on the button's centre (menu.js SEED)
      await until(() => !Menu.state(), 1500); window.render = r0;   // the driver's own end (strip), capped: the dismiss outlasts 300 ms on a loaded run
      check("菜单：收回后补一次压住的重绘", "1 次", `${runs} 次`, runs === 1);
    }
  }, { layer: "timing", dark: true });   // S4 file-level tags (数据 S4-tags.md (e), 2号 13:5x): timing = waits on the drivers, so ?layer=daily and release both run it; dark true = the glass keys / face matrix change with the theme (R74 / R109 dark values)
})();
