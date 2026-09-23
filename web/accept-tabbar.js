/* accept-tabbar.js — acceptance of the tab bar's lifted selection lens, geometry mode (BOARD.md #7a; web/assets/lens/tab-lens.js). Registered
   through ACCEPT.add; runs in accept.js's page (light and dark).
   ① delay: pressing another item, the glide gets .lift after the page's +140 ms (tokens.css --ios-touch-tab-glide-delay; interaction spec §2 T1);
      pressing the selected item, .lift-sel after +125 ms (--ios-touch-tab-selected-lift-delay, T3) — measured from the pointerdown, ± one frame + the
      timer's slack (accepted window [delay − 5, delay + 50] ms).
   ② lift: from the lift's start (window.__tabLens.t0) the glide's width and height follow ζ 1 / .25 (tab-lens-motion.md §0 "抬起") from the item's
      box w0 × 54 to (w0 + 16) × (54 + 16) (§0 / §4: 94×54 → 110×70 = +16 on both axes); the box centre x follows ζ .85 / .4 (§3, the jump to a
      pressed item) from the old centre to the pressed item's; rms ≤ 1 pt per quantity (twice the rounding of a rect read at 1 px — the page
      integrates the same closed form on the same frame timestamps).
   ③ drop: from the up the width / height follow ζ 1 / .4 (§0 "落回") from the value at the up back to w0 × 54; rms ≤ 1 pt.
   ④ rest: after the drop the driver is off (nav without .tl-on) and the glide shows view.js's box for the selected item (left = its offsetLeft,
      width = its offsetWidth, height 54).
   ⑤ template (BOARD A6): the bar's .plat is the same node after the gesture (no rebuild); hidden while lifted → the driver stops and the glide is
      back on view.js's box; the keyboard rule's two lines (view.js __tabKbd) as in accept.js.
   #7b the drag (tab-lens-motion.md §6.5 / §6.6): the target while dragging = finger x − a·W + W/2 (a = .5 when pressed at the centre → the finger),
      the centre vs the closed form ζ .85 / .2 from the value and velocity before the move (rms ≤ 1 pt), the hard clamp at the items' run, the up:
      target = the centre of the item under the finger, ζ .85 / .4 (R106: §6.9's "no gesture" pair) from the value and velocity at the up, that item selected, driver off at rest;
      hidden mid-drag stops the driver. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptTabBar(ctx) {
    const { check, num, sleep } = ctx;
    const nav = document.querySelector("nav.tabs"); if (!nav) { check("标签栏：页面无 nav.tabs", "有", "缺", false); return; }
    if (!nav.classList.contains("tlens")) { check("标签栏：tab-lens.js 未接（nav 无 .tlens：挂钩行 / motion.js）", "tlens", nav.className, false); return; }
    const seg = nav.querySelector(".seg"), g = nav.querySelector(".glide"), bs = [...seg.querySelectorAll("button")], plat0 = nav.querySelector(".plat");
    const crit = (start, target, resp, t) => { const w = 2 * Math.PI / resp; return target + (start - target) * (1 + w * t) * Math.exp(-w * t); };   // ζ 1
    const under = (start, target, zeta, resp, t) => { const w = 2 * Math.PI / resp, wd = w * Math.sqrt(1 - zeta * zeta), e = Math.exp(-zeta * w * t); return target + (start - target) * e * (Math.cos(wd * t) + (zeta * w / wd) * Math.sin(wd * t)); };
    const rms = (a) => Math.sqrt(a.reduce((s, v) => s + v * v, 0) / Math.max(1, a.length));
    const rect = () => { const r = g.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width, height: r.height, cx: r.left + r.width / 2 }; };
    const ev = (el, t, x, y, id = 4) => el.dispatchEvent(new PointerEvent(t, { bubbles: true, cancelable: true, pointerId: id, isPrimary: true, pointerType: "touch", clientX: x, clientY: y, button: 0, buttons: t === "pointerup" ? 0 : 1 }));
    const sample = (ms, t0) => new Promise((resolve) => { const out = []; let first = null; const tick = (now) => { if (first === null) first = now; out.push({ t: (now - t0) / 1000, ...rect(), p: window.__tabLens ? window.__tabLens.p : null }); if (now - first < ms) requestAnimationFrame(tick); else resolve(out); }; requestAnimationFrame(tick); });
    const px = (name, fb) => { const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)); return Number.isNaN(v) ? fb : v; };
    const waitClass = async (cls, ms) => { const t0 = performance.now(); while (performance.now() - t0 < ms) { if (g.classList.contains(cls)) return performance.now() - t0; await sleep(4); } return null; };
    const on0 = bs.findIndex((b) => b.classList.contains("on")); const other = bs[on0 === 0 ? 1 : 0]; const w0 = other.offsetWidth, h0 = g.offsetHeight;
    const r0 = rect(); const or = other.getBoundingClientRect(), ox = or.left + or.width / 2, oy = or.top + or.height / 2;
    /* ① + ② press another item — R59′d (老网页 R108, tab-lens-motion.md §6.9 ⑤): the lift has NO delay: the driver starts on the down (its first tick = t0), the width leaves w0 on ζ 1 / .25
       towards w0 + 22.7 (the probe's 94 → 116.7), the height towards 74; the probe's five points as width increments from the down: +47 1.76 / +97 11.07 / +130 16.14 / +180 20.55 / +197 21.34 (± 1 pt,
       t0 = the frame after the down); the +140 / +125 ms tokens were the recording's latency — view.js's class still arrives then (界面 R59′c withdraws it), the driver no longer waits for it */
    const LW = 116.7 - 94, LH = 74 - 54, tDown = performance.now(); ev(other, "pointerdown", ox, oy); let L0 = null, nf0 = 0; for (; nf0 < 4 && !L0; nf0++) { await new Promise((r) => requestAnimationFrame(r)); L0 = window.__tabLens; }
    check(`R59′d 按下即抬：驱动器在按下后 ≤ 2 帧起（t0 +${L0 ? Math.round(L0.t0 - tDown) : "-"} ms）、抬起目标 = 按下项、p 在升`, "≤ 2 帧 · lift/move · p > 0", L0 ? `${nf0} 帧 · ${L0.phase} · p ${L0.p.toFixed(3)}` : "无驱动", !!L0 && nf0 <= 2 && L0.t0 - tDown <= 40 && (L0.phase === "lift" || L0.phase === "move"));
    if (!L0) { check("标签栏：按下后驱动在跑（window.__tabLens）", "有", "缺", false); ev(other, "pointerup", ox, oy); return; }
    const lift = await sample(600, L0.t0);
    num(`抬起 宽 对 ζ1/.25 闭式 rms（${lift.length} 帧；${w0} → ${(w0 + LW).toFixed(1)}，R108 探针 94 → 116.7）`, 0, rms(lift.map((s) => s.width - crit(w0, w0 + LW, 0.25, s.t))), 1);
    num(`抬起 高 对 ζ1/.25 闭式 rms（${h0} → ${h0 + LH}，探针 54 → 74.0）`, 0, rms(lift.map((s) => s.height - crit(h0, h0 + LH, 0.25, s.t))), 1);
    { const pts = [[47, 1.76], [97, 11.07], [130, 16.14], [180, 20.55], [197, 21.34]]; const at = (ms) => { const t = (ms - 30) / 1000; return LW * (1 - Math.exp(-2 * Math.PI / 0.25 * t) * (1 + 2 * Math.PI / 0.25 * t)); };   // the probe's points vs the same closed form from t0 = +30 (the frame after the down), as increments
      const dmax = Math.max(...pts.map(([ms, dw]) => Math.abs(at(ms) - dw)));
      num(`R59′d 探针五点（+47/+97/+130/+180/+197 宽增 1.76/11.07/16.14/20.55/21.34）对 ζ1/.25 → +22.7 自 +30 的最大差（pt）`, 0, dmax, 1); }
    num("抬起 中心 x 对 ζ.85/.4 闭式 rms（旧项中心 → 按下项中心）", 0, rms(lift.map((s) => s.cx - under(r0.cx, ox, 0.85, 0.4, s.t))), 1);
    num("抬满后 宽 = w0 + 22.7（R108）", w0 + LW, rect().width, 0.5); num("抬满后 高 = 74（R108 探针 +464 行）", h0 + LH, rect().height, 0.5);
    num("抬满后 圆角 = 高 / 2（胶囊，999px）", (h0 + LH) / 2, Math.min(parseFloat(getComputedStyle(g).borderTopLeftRadius), rect().height / 2), 0.5);
    { const dLift = g.classList.contains("lift") ? 0 : await waitClass("lift", 600); check("view.js 的 .lift 类 = 高亮，自按下即在（R59′e 撤了 +140 定时器；驱动器不等它）", "到", dLift === null ? "没到" : "到", dLift !== null); }
    /* ③ drop */
    /* the drop's time base = the last frame before the up (window.__tabLens.tf): the retarget keeps the loop's clock, the state at that frame is `up` */
    const up = rect(); const Lup = window.__tabLens; ev(other, "pointerup", ox, oy); await new Promise((r) => requestAnimationFrame(r));
    const drop = await sample(700, Lup ? Lup.tf : performance.now());
    num(`落回 宽 对 ζ1/.4 闭式 rms（${drop.filter((s) => s.p !== null).length} 帧）`, 0, rms(drop.filter((s) => s.p !== null).map((s) => s.width - crit(up.width, w0, 0.4, s.t))), 1);
    num("落回 高 对 ζ1/.4 闭式 rms", 0, rms(drop.filter((s) => s.p !== null).map((s) => s.height - crit(up.height, h0, 0.4, s.t))), 1);
    /* ④ rest */
    await sleep(200); const onNow = bs.find((b) => b.classList.contains("on")); const rr = rect();
    check("落回后驱动停（nav 无 .tl-on）", "无", nav.classList.contains("tl-on") ? "还在" : "无", !nav.classList.contains("tl-on"));
    num("静止：glide 宽 = 选中项宽", onNow ? onNow.offsetWidth : w0, rr.width, 0.5); num("静止：glide 高 = 54", h0, rr.height, 0.5);
    num("静止：glide 左 = 选中项 offsetLeft", onNow ? nav.getBoundingClientRect().left + onNow.offsetLeft + seg.offsetLeft : rr.left, rr.left, 1);
    /* ⑤ template */
    check("手势后 .plat 是同一节点（未重建）", "同", nav.querySelector(".plat") === plat0 ? "同" : "新节点", nav.querySelector(".plat") === plat0);
    const selB = bs.find((b) => b.classList.contains("on")); const sr = selB.getBoundingClientRect(), sx = sr.left + sr.width / 2, sy = sr.top + sr.height / 2;
    ev(selB, "pointerdown", sx, sy, 5); let Ls = null; for (let k = 0; k < 4 && !Ls; k++) { await new Promise((r) => requestAnimationFrame(r)); Ls = window.__tabLens; }   // V1c: like the first press (≤ 4 frames) — tab-lens.js skips a rAF stamped at / before its start (`now <= last`), so one rAF read null 4/40 (main f548aca) · 6/40 (92909d1), two rAF 0/130
    const dSel = await waitClass("lift-sel", 600);
    check("R59′d 按下已选中项：驱动器同样在按下后即抬（不等 +125 的 .lift-sel 类，该令牌作废 = 录像口径）", "驱动在 · p 升", Ls ? `驱动在 · p ${Ls.p.toFixed(3)} · 类 ${dSel === null ? "没到" : "+" + Math.round(dSel) + " ms"}` : "无驱动", !!Ls && Ls.phase !== "rm");
    await sleep(150); const hiddenDesc = Object.getOwnPropertyDescriptor(Document.prototype, "hidden"); Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true })); await sleep(30);
    check("抬起中 hidden → 驱动停、glide 回 view.js 的框", "无 .tl-on", nav.classList.contains("tl-on") ? "还在" : "无 .tl-on", !nav.classList.contains("tl-on"));
    delete document.hidden; if (hiddenDesc) Object.defineProperty(Document.prototype, "hidden", hiddenDesc);
    ev(selB, "pointerup", sx, sy, 5); await sleep(700);
    /* ---- R33 (tab-lens-motion.md §3a): a quick tap on another item — the lens lifts (ζ 1 / .25) and slides (ζ .85 / .4) from the tap together, and falls
       (ζ 1 / .4) from the frame the slide arrives (first within .5 pt of the target), not at the up; the selection changes at the up (view.js) */
    { const sel0 = bs.find((b) => b.classList.contains("on")), tgt = bs[bs.indexOf(sel0) === 0 ? 1 : 0], tr = tgt.getBoundingClientRect(), tx = tr.left + tr.width / 2, ty = tr.top + tr.height / 2, navL2 = nav.getBoundingClientRect().left;
      const cxNav2 = () => rect().cx - navL2; const c0 = cxNav2();
      ev(tgt, "pointerdown", tx, ty, 12); await sleep(40); ev(tgt, "pointerup", tx, ty, 12);
      let L0 = null; for (let i = 0; i < 30 && !L0; i++) { await new Promise((r) => requestAnimationFrame(r)); L0 = window.__tabLens; }   // the selection's render and the driver's first frame follow the up within a few frames
      const samples = []; await new Promise((res) => { let first = null; const tick = (now) => { if (first === null) first = now; const L = window.__tabLens; samples.push({ t: now, cx: cxNav2(), h: rect().height, p: L ? L.p : null, ph: L ? L.phase : null, x: L ? L.x : null, target: L ? L.target : null }); if (now - first < 900) requestAnimationFrame(tick); else res(); }; requestAnimationFrame(tick); });
      const target = tx - navL2; const tapFrames = samples.filter((s) => s.ph === "tap" || s.ph === "slide" || s.ph === "lift" || s.ph === "move"), dropIdx = samples.findIndex((s) => s.ph === "drop"), atDrop = dropIdx > 0 ? samples[dropIdx - 1] : null, firstDrop = dropIdx >= 0 ? samples[dropIdx] : null;
      /* R59′d: the lift and the slide begin at the down itself (R108), so after a 40 ms up the driver is already lifting and sliding (phase lift / move, then slide once the highlight is gone) */
      check("R33 / R59′d 快速点另一项：按下即抬 + 滑行，松手后仍在滑（无高亮：slide），p > 0", "lift/move/slide · p > 0 · x 在动", L0 ? `${L0.phase} · p ${L0.p.toFixed(3)} · x ${cxNav2().toFixed(1)}→${target.toFixed(1)}` : "无驱动", !!L0 && ["tap", "slide", "lift", "move", "drop"].includes(L0.phase) && L0.p > 0 && tapFrames.length >= 3);
      /* R106 (tab-lens-motion.md §6.9 ①): the fall (setLifted false) begins on the frame the lens is within 8 pt of its target with no highlight — 0x1c50e8634–0x1c50e8650; R33's ".5 pt arrival" was that rule read off the tap trace */
      check(`R33 / R106 到目标 8 pt 内那帧起落回（§6.9 ①：无高亮且 |目标 − 呈现| < 8）：drop 首帧 |Δx| < 8、前一帧 ≥ 8、drop 前高仍在抬起（${atDrop ? atDrop.h.toFixed(1) : "-"} > 54）`, "|Δx| < 8 · 前帧 ≥ 8 · h > 54", firstDrop && atDrop ? `|Δx| ${Math.abs(firstDrop.x - firstDrop.target).toFixed(2)}（前一帧 ${Math.abs(atDrop.x - atDrop.target).toFixed(2)}）· h ${atDrop.h.toFixed(1)} · ${tapFrames.length} tap 帧` : "无 drop", !!firstDrop && !!atDrop && Math.abs(firstDrop.x - firstDrop.target) < 8 && Math.abs(atDrop.x - atDrop.target) >= 8 && atDrop.h > 54);
      const dropS = samples.slice(dropIdx).filter((s) => s.ph === "drop"); const pDrop = dropS.map((s) => s.p);
      check("R33 落回：高沿 ζ1/.4 单调回到 54（p 单调降）", "单调 · 末 54", `${pDrop.length} 帧 · 末 h ${samples[samples.length - 1].h.toFixed(1)}`, pDrop.length >= 5 && pDrop.every((v, i) => i === 0 || v <= pDrop[i - 1] + 1e-6) && Math.abs(samples[samples.length - 1].h - 54) <= 0.5);
      const onNow = bs.find((b) => b.classList.contains("on")); check("R33 松手即选中被点项、胶囊落定在其中心", tgt.dataset.tab, `${onNow ? onNow.dataset.tab : "-"} · ${cxNav2().toFixed(1)} vs ${target.toFixed(1)}`, onNow === tgt && Math.abs(cxNav2() - target) <= 1.5);
      delete seg.dataset.pe; await sleep(200);
      /* back to the original tab for the flows below (a second quick tap; the same path) */
      const sr0 = sel0.getBoundingClientRect(); ev(sel0, "pointerdown", sr0.left + sr0.width / 2, sr0.top + sr0.height / 2, 13); await sleep(40); ev(sel0, "pointerup", sr0.left + sr0.width / 2, sr0.top + sr0.height / 2, 13); await sleep(1200); delete seg.dataset.pe; }
    /* ---- R2 (b) the material overlay (tab-lens.js glAttach → lens-webgl.js): the canvas over the bar, the tab5 family's nine sets with the filters' keys
       (data-s 40, 48 for the 98 set, fringe 16; heights 54 … 70 from lens-field.json), the lift riding the 98 set with frames drawn, cleared at rest */
    { const g = window.__tabLensGL && window.__tabLensGL();
      if (!g) check("R2 标签栏透镜材质：WebGL 覆盖层（?tlens-gl=0 关）", "有", window.LensWebGL ? "缺（无 webgl2 或家族未载）" : "缺 LensWebGL", false);
      else { await g.lens.ready; const L = g.lens; const sets = Object.keys(L.sets).map(Number).sort((a, b) => a - b);
        check("R2 材质：tab5 家族九组已载（82 … 98）", "82,84,…,98", sets.join(","), sets.length === 9 && sets[0] === 82 && sets[8] === 98);
        check("R2 材质键 = 家族滤镜 data-s（bg/lab S 40，98 组 48；色散 S_ab 16）、高 54 … 70（lens-field.json）", "S 40/48 · Sab 16 · h 54/70", `S ${L.sets[82] && L.sets[82].S}/${L.sets[98] && L.sets[98].S} · Sab ${L.sets[82] && L.sets[82].Sab} · h ${L.sets[82] && L.sets[82].h}/${L.sets[98] && L.sets[98].h}`, !!L.sets[82] && !!L.sets[98] && L.sets[82].S === 40 && L.sets[98].S === 48 && L.sets[82].Sab === 16 && L.sets[82].h === 54 && L.sets[98].h === 70);
        const cr = g.canvas.getBoundingClientRect(), nr = nav.getBoundingClientRect();
        num("R2 材质：canvas 盖 nav 每边 +24（抬起 98×70 与色散包 16 都在内）", 24, nr.left - cr.left, 0.5); num("R2 材质：canvas 高 = nav + 48", nr.height + 48, cr.height, 0.5);
        const selB3 = bs.find((b) => b.classList.contains("on")); const r3 = selB3.getBoundingClientRect(); const f0 = L.stats.frames;
        ev(selB3, "pointerdown", r3.left + r3.width / 2, r3.top + r3.height / 2, 11); await waitClass("lift-sel", 600); await sleep(300);
        const fLift = L.stats.frames - f0, setLift = L.stats.set, lastLift = L.stats.last;
        check("R2 材质：抬起中包在画帧（stats.frames 增）、走 98 组（抬起骑最大组，README §0.3）、pd = lift", "frames > 5 · set 98 · pd = lift", `frames +${fLift} · set ${setLift} · lift ${lastLift ? lastLift.lift.toFixed(3) : "-"} pd ${lastLift ? lastLift.pd.toFixed(3) : "-"}`, fLift > 5 && setLift === 98 && !!lastLift && Math.abs(lastLift.lift - lastLift.pd) < 1e-6);
        ev(selB3, "pointerup", r3.left + r3.width / 2, r3.top + r3.height / 2, 11); await sleep(900); delete seg.dataset.pe;
        check("R2 材质：落定后画布清（最后一帧 lift 0）、无 JS 错", "lift 0 · no error", `lift ${L.stats.last ? L.stats.last.lift : "-"} · ${window.__tabLensErr || "no error"}`, !!L.stats.last && L.stats.last.lift === 0 && !window.__tabLensErr);
        check("R2 材质：平台里透出的页面、项复本 1.16 缩放——未画（不可表达 / 待做，tab-lens.js 注释）", "记录", "记录", true);
        /* R37: the tab lens is a capsule r = h/2 (tab-lens-native.md §0 cornerRadii 35 = 70/2 — the outline terms took the segment lens's r 22 before), its label stack
           ContentLensing −14 / 11.2 then ClearGlass −17.5 / 11.2 (tab-lens-native.md §3, tab/lens-field.json), the field in float (closed) */
        /* R38c: the glassForeground's 7-tap dispersion (formula §3b.2, the rim band e(d) of §3b.5) runs in pass 2 over pass 1's raster — which already holds the label
           copy — so the label copy IS dispersed (数据 R98: that dispersion is the lifted state's softening); the closed form with the same band on the native label bitmap
           reproduces three of R98's five numbers (end 267 = 267, core .852 vs .857, black columns 52 vs 49; the total 863 vs 792 and the mid-tones 526 vs 876 are the
           material term 老网页 R99 reads — tools/tear_cbg.py fg); ?glfields=0 = the three fields off (stats.fields), the state of those measurements */
        check("R38c 色散在标签复本上：pass 2 的 7 抽头（k 1/⅔/⅓，R/2 G/3 B/2）取样 pass 1 栅格（含标签复本）× 带 e(d)；三场开关默认开（?glfields=0 关）；闭式核 R98：端 267 = 267、核心 .852 对 .857、到黑列 52 对 49，总 863 / 中间调 526 对 792 / 876 = 材质项（R99）", "7 抽头 over pass 1 · fields 1", `${/A\(v \+ sg\[i\] \* ks\[i\] \* D\)/.test(LensWebGL.FS2) && /ks\[7\] = float\[7\]\(1\.0, 2\.0 \/ 3\.0, 1\.0 \/ 3\.0, 0\.0/.test(LensWebGL.FS2) ? "7 抽头 over pass 1" : "?"} · fields ${L.stats.fields}`, /A\(v \+ sg\[i\] \* ks\[i\] \* D\)/.test(LensWebGL.FS2) && L.stats.fields === 1);
        /* R38d (老网页 R99, label-end-tear §7g): inside the lens the label copy meets the glass background in #33's linear-light source surface — L′ = enc(lin(bg)·(1 − c) + lin(ink)·c),
           not the sRGB over — so the same coverage darkens less and near-threshold ink drops out (native drag-mid, fields + aberration off: 807 / 279; the linear model 799 / 286, the
           sRGB model 1018 / 385); pass 1 does that composite when u_lincomp = 1 (?gllin=0 = the old over). Headless 3× lifted 早班 on this page: I>.56 1145 (linear) vs 1238 (sRGB), mid-tones 683 vs 645 */
        check("R38d 透镜内标签复本线性光合成（R99 §7g：L′ = enc(lin(bg)(1 − c) + lin(ink)c)，胶囊外仍 sRGB over）：pass 1 有 linv/encv 合成、stats.linComp 1（?gllin=0 关）；本页无头抬起态 I>.56 1145 对 sRGB 1238", "linv·encv · linComp 1", `${/linv\(ic\) \* lc\.a \+ linv\(col\.rgb\) \* \(1\.0 - lc\.a\)/.test(LensWebGL.FS1) ? "linv·encv" : "?"} · linComp ${L.stats.linComp}`, /linv\(ic\) \* lc\.a \+ linv\(col\.rgb\) \* \(1\.0 - lc\.a\)/.test(LensWebGL.FS1) && L.stats.linComp === 1);
        check("R2/R37 材质：胶囊 r = h/2（rmax ≥ 35）、标签两级 −14/11.2 → −17.5/11.2、场按式逐像素（closed）", "rmax ≥ 35 · −14/11.2,−17.5/11.2 · closed", `rmax ${L.stats.rmax} · ${(L.stats.labelStages || []).join("/")} · ${L.stats.labMode}`, L.stats.rmax >= 35 && (L.stats.labelStages || []).join(",") === "-14,11.2,-17.5,11.2" && L.stats.labMode === "closed"); } }
    /* ---- #7b the drag (tab-lens-motion.md §6.5 / §6.6): while the selected item is held and lifted, the capsule's centre springs (ζ .85 / .2, retargeted
       on every move) to finger x − a·W + W/2 (a = where in the item the finger went down; pressed at the centre a = .5 → the target is the finger), the
       left edge hard-clamped to the items' run; at the up ζ .85 / .4 (R106) to the centre of the item under the finger, which becomes the selection */
    { const selB2 = bs.find((b) => b.classList.contains("on")), idx2 = bs.indexOf(selB2), nbr = bs[idx2 === bs.length - 1 ? idx2 - 1 : idx2 + 1], dir = bs.indexOf(nbr) > idx2 ? 1 : -1;
      const sr2 = selB2.getBoundingClientRect(), sx2 = sr2.left + sr2.width / 2, sy2 = sr2.top + sr2.height / 2, navL = nav.getBoundingClientRect().left, w0b = selB2.offsetWidth;
      const underDamped = (x0, v0, target, zeta, resp, t) => { const w = 2 * Math.PI / resp, wd = w * Math.sqrt(1 - zeta * zeta), dx = x0 - target, e = Math.exp(-zeta * w * t); return target + e * (dx * Math.cos(wd * t) + ((v0 + zeta * w * dx) / wd) * Math.sin(wd * t)); };
      const cxNav = () => rect().cx - navL;
      const sampleX = (ms, t0) => new Promise((resolve) => { const out = []; let first = null; const tick = (now) => { if (first === null) first = now; out.push({ t: (now - t0) / 1000, cx: cxNav() }); if (now - first < ms) requestAnimationFrame(tick); else resolve(out); }; requestAnimationFrame(tick); });
      ev(selB2, "pointerdown", sx2, sy2, 6); const dl = await waitClass("lift-sel", 600); await sleep(450);   // lifted and settled
      if (dl === null) check("7b：按住已选中项抬起", "lift-sel", "没抬", false);
      else {
        const Lm = window.__tabLens; const xm = Lm ? Lm.x : cxNav(), vm = Lm ? Lm.xv : 0, tfm = Lm ? Lm.tf : performance.now();
        const fx1 = sx2 + dir * 40; ev(selB2, "pointermove", fx1, sy2, 6); await new Promise((r) => requestAnimationFrame(r));
        const Lt = window.__tabLens; const want1 = fx1 - navL;   // a = .5: target = the finger (nav coordinates)
        num("7b 拖动目标 = 手指 x − a·W + W/2（按在中心 a = .5 → 手指 x，nav 坐标）", want1, Lt ? Lt.target : NaN, 0.5);
        check("7b 拖动中 nav.drag + 驱动 phase drag", "drag", `${nav.classList.contains("drag") ? "drag" : "-"} ${Lt ? Lt.phase : "-"}`, nav.classList.contains("drag") && !!Lt && Lt.phase === "drag");
        /* R64: the presented centre now carries the flex drift (sX·dx) — the position spring is judged on the driver's own x, the drift on the rect */
        const mv = []; await new Promise((resolve) => { let first = null; const tick = (now) => { if (first === null) first = now; const L = window.__tabLens; mv.push({ t: (now - tfm) / 1000, cx: cxNav(), x: L ? L.x : cxNav(), xc: L ? L.xc : cxNav(), fx: L && L.flex ? { ...L.flex, trace: undefined } : null, wp: L ? L.wp : NaN, hp: L ? L.hp : NaN, w: L ? L.w : NaN, h: L ? L.h : NaN, r: rect() }); if (now - first < 400) requestAnimationFrame(tick); else resolve(); }; requestAnimationFrame(tick); });
        num(`7b 拖动 位置弹簧 x 对 ζ.85/.2 闭式 rms（${mv.length} 帧，自移动前一帧的 x / v 起；驱动器本帧值）`, 0, rms(mv.map((s) => s.x - underDamped(xm, vm, want1, 0.85, 0.2, s.t))), 1);
        { const withF = mv.filter((s) => s.fx), peak = withF.reduce((m, s) => (s.fx.sx > m ? s.fx.sx : m), 1), dip = withF.reduce((m, s) => (s.fx.sy < m ? s.fx.sy : m), 1), spec0 = withF.length ? withF[0].fx.spec : null;
          check("R64 拖动中 flex 变体 = loupe（模型 (w0+16)×(h0+16) → d 70 → t 1；flex-interaction.md §2 / tab-lens-motion.md §6.4：pts 100、min .75、max 1.15、N 2500、ζ 1/.5、tracking .9/.5），手指在时走 tracking 弹簧", "pts 100 · .75/1.15 · N 2500 · ζ 1/.5 · tracking .9/.5 · sp .9/.5", spec0 ? `pts ${spec0.pts} · ${spec0.min}/${spec0.max} · N ${spec0.N} · ζ ${spec0.zeta}/${spec0.resp} · tracking ${spec0.tzeta}/${spec0.tresp} · sp ${withF[0].fx.sp.join("/")}` : "no flex", !!spec0 && spec0.pts === 100 && spec0.min === .75 && spec0.max === 1.15 && spec0.N === 2500 && spec0.zeta === 1 && spec0.resp === .5 && spec0.tzeta === .9 && spec0.tresp === .5 && withF[0].fx.sp[0] === .9 && withF[0].fx.sp[1] === .5);
          check("R64 拖动加速时 X 伸 Y 缩（§3：sX = lerp(1, hi, a/N) 钳 [.9, 1.1] 目标，sY 反向）：拖动段 sX 峰 > 1、sY 谷 < 1，目标不出 [.9, 1.1]", "peak sX > 1.005 · dip sY < .995 · targets in [.9, 1.1]", `peak sX ${peak.toFixed(4)} · dip sY ${dip.toFixed(4)} · targets ${withF.every((s) => s.fx.target.sX >= .9 - 1e-9 && s.fx.target.sX <= 1.1 + 1e-9 && s.fx.target.sY >= .9 - 1e-9 && s.fx.target.sY <= 1.1 + 1e-9) ? "in" : "OUT"}`, withF.length > 10 && peak > 1.005 && dip < .995 && withF.every((s) => s.fx.target.sX >= .9 - 1e-9 && s.fx.target.sX <= 1.1 + 1e-9 && s.fx.target.sY >= .9 - 1e-9 && s.fx.target.sY <= 1.1 + 1e-9));
          const geoOK = withF.every((s) => Math.abs(s.r.width - s.w * s.fx.sx) < .6 && Math.abs(s.r.height - s.h * s.fx.sy) < .6 && Math.abs((s.cx) - (s.x + s.fx.sx * s.fx.dx)) < .6);
          check("R64 呈现盒 = W·sX × H·sY，中心 = 位置弹簧 + sX·drift（§6.6 / §6.4 先缩放后平移）——逐帧对驱动器本帧值（± .6 px）", "every frame", geoOK ? "every frame" : "OFF", withF.length > 10 && geoOK);
          /* the three floats integrate the analytic flex spring toward that frame's targets from the previous frame's state (the driver's own dt) */
          const tr = window.__tabLens && window.__tabLens.flex ? window.__tabLens.flex.trace : [], stepRef = (x, v, target, [z, r], dt) => { const w = 2 * Math.PI / r, dx = x - target; if (z < 1) { const wd = w * Math.sqrt(1 - z * z), B = (v + z * w * dx) / wd, e = Math.exp(-z * w * dt); return target + e * (dx * Math.cos(wd * dt) + B * Math.sin(wd * dt)); } const e = Math.exp(-w * dt), B = v + w * dx; return target + e * (dx + B * dt); };
          let maxErr = 0, n = 0; for (let i = 1; i < tr.length; i++) { const a0 = tr[i - 1], b0 = tr[i]; if (!(b0.dt > 0)) continue; maxErr = Math.max(maxErr, Math.abs(stepRef(a0.sx, a0.vsx, b0.tSx, b0.sp, b0.dt) - b0.sx), Math.abs(stepRef(a0.sy, a0.vsy, b0.tSy, b0.sp, b0.dt) - b0.sy), Math.abs(stepRef(a0.dx, a0.vdx, b0.tDx, b0.sp, b0.dt) - b0.dx)); n++; }
          check(`R64 三个 flex 浮点逐帧 = 解析弹簧一步（自上一帧的值 / 速度，向本帧目标，本帧 dt；${n} 帧，最大差）`, "≤ 1e-6", maxErr.toExponential(2), n > 10 && maxErr <= 1e-6); }
        const segR = seg.getBoundingClientRect(), padR = parseFloat(getComputedStyle(seg).paddingRight) || 0, padL = parseFloat(getComputedStyle(seg).paddingLeft) || 0;
        const far = dir > 0 ? sx2 + 400 : sx2 - 400; ev(selB2, "pointermove", far, sy2, 6); await new Promise((r) => requestAnimationFrame(r)); const Lc = window.__tabLens;
        const clampWant = dir > 0 ? segR.right - navL - padR - w0b / 2 : segR.left - navL + padL + w0b / 2;
        num("7b 拖过端点：目标硬钳在轨道端（§6.6 无橡皮筋）", clampWant, Lc ? Lc.target : NaN, 0.5);
        const nr = nbr.getBoundingClientRect(), nx = nr.left + nr.width / 2; ev(selB2, "pointermove", nx, sy2, 6); await sleep(350);   // over the neighbour, settled there
        const Lu = window.__tabLens; const xu = Lu ? Lu.x : cxNav(), vu = Lu ? Lu.xv : 0, tfu = Lu ? Lu.tf : performance.now();
        ev(selB2, "pointerup", nx, sy2, 6); await new Promise((r) => requestAnimationFrame(r)); const Lr = window.__tabLens;
        num("7b 松手目标 = 手指下那项的中心（§6.5 落点）", nx - navL, Lr ? Lr.target : NaN, 0.5);
        const rl = await sampleX(500, tfu);
        num(`7b / R106 松手 中心 x 对 ζ.85/.4 闭式 rms（${rl.length} 帧，自松手前一帧的 x / v 起；§6.9 ③「无手势」支 0x1c50e8774）`, 0, rms(rl.map((s) => s.cx - underDamped(xu, vu, nx - navL, 0.85, 0.4, s.t))), 1);
        await sleep(400); const onB = bs.find((b) => b.classList.contains("on"));
        check("7b 松手后选中 = 手指下那项", nbr.dataset.tab || "邻项", onB ? (onB.dataset.tab || "?") : "-", onB === nbr);
        num("7b 落定：胶囊中心 = 该项中心", nx - navL, cxNav(), 1); check("7b 落定后驱动停（无 .tl-on）", "无", nav.classList.contains("tl-on") ? "还在" : "无", !nav.classList.contains("tl-on"));
        num("R64 落定后 flex 归位：胶囊宽 = 项宽（sX → 1，drift → 0）", w0b, rect().width, 1);
        /* template: hidden mid-drag strips the driver */
        const b3 = bs.find((b) => b.classList.contains("on")); const r3 = b3.getBoundingClientRect(), x3 = r3.left + r3.width / 2, y3 = r3.top + r3.height / 2;
        ev(b3, "pointerdown", x3, y3, 7); await waitClass("lift-sel", 600); ev(b3, "pointermove", x3 + 20, y3, 7); await sleep(100);
        const hd = Object.getOwnPropertyDescriptor(Document.prototype, "hidden"); Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
        document.dispatchEvent(new Event("visibilitychange", { bubbles: true })); await sleep(30);
        check("7b 拖动中 hidden → 驱动停", "无 .tl-on", nav.classList.contains("tl-on") ? "还在" : "无 .tl-on", !nav.classList.contains("tl-on"));
        delete document.hidden; if (hd) Object.defineProperty(Document.prototype, "hidden", hd);
        ev(b3, "pointerup", x3, y3, 7); await sleep(600);
      } }
    /* ---- R59′b / R59′b″ Reduce Motion (page-inventory.md §12b ② decompiled: no setLifted:, no .95 platter scale; tab-lens-motion.md §6.9 = 老网页 R105: the bar's
       tracker _UITabBarVisualProvider_Floating uses ζ .9 / .2 for position and size under Reduce Motion (0x1c50e8690 / 0x1c50e86c4), the target = the finger rule;
       R94: the selection frame and the lens move as one): forced through window.__forceRM like view.js's 段 rows. Pressing another item: the driver starts at the
       down (phase rm), the centre follows ζ .9 / .2 to the item's centre, width / height never leave w0 × 54 and p stays 0 (no lift, no flex); while the finger is
       held the driver stays on and the lens is parked on the item; the up selects it and the driver stops at rest on view.js's box; a drag under RM: no lift, the
       target = the finger rule. Records vs that spring: the slide-at-down .11 pt rms (start +42.6), the R94 held slide 1.15 with the 2-frame delivery latency (§6.9 ④). */
    { window.__forceRM = true; try {
      const closedRM = (x0, target, t) => { const w = 2 * Math.PI / 0.2, z = 0.9, wd = w * Math.sqrt(1 - z * z), e = Math.exp(-z * w * t); return target + (x0 - target) * e * (Math.cos(wd * t) + (z * w / wd) * Math.sin(wd * t)); };
      const navL4 = nav.getBoundingClientRect().left, cx4 = () => rect().cx - navL4;
      const sel4 = bs.find((b) => b.classList.contains("on")), tgt4 = bs[bs.indexOf(sel4) === 0 ? 1 : 0], tr4 = tgt4.getBoundingClientRect(), tx4 = tr4.left + tr4.width / 2, ty4 = tr4.top + tr4.height / 2, w04 = tgt4.offsetWidth, c04 = cx4();
      const tDown = performance.now(); ev(tgt4, "pointerdown", tx4, ty4, 21); let L4 = null, nf = 0; for (; nf < 4 && !L4; nf++) { await new Promise((r) => requestAnimationFrame(r)); L4 = window.__tabLens; }   // the driver's first integrated frame: a rAF stamped before the start re-ticks (tab-lens.js frame0), so the state appears on the first or second frame
      check(`R59′b RM 按下另一项：驱动在按下后 ≤ 2 帧起（不等 +140 抬起；起点 +${L4 ? Math.round(L4.t0 - tDown) : "-"} ms）、phase rm、p 0、目标 = 该项中心`, "≤ 2 帧 · rm · p 0 · 目标 = 中心", L4 ? `${nf} 帧 · ${L4.phase} · p ${L4.p.toFixed(3)} · 目标 ${L4.target.toFixed(1)} vs ${(tx4 - navL4).toFixed(1)}` : `无驱动（${JSON.stringify(window.__tabLensRM || null)} stop ${JSON.stringify(window.__tabLensStop || null)} err ${window.__tabLensErr || "-"}）`, !!L4 && nf <= 2 && L4.phase === "rm" && L4.rm === true && L4.p === 0 && Math.abs(L4.target - (tx4 - navL4)) <= 0.5 && L4.t0 - tDown <= 40);
      const sl = []; await new Promise((res) => { let first = null; const tick = (now) => { if (first === null) first = now; const L = window.__tabLens; sl.push({ t: (now - (L4 ? L4.t0 : tDown)) / 1000, cx: cx4(), w: rect().width, h: rect().height, p: L ? L.p : null, ph: L ? L.phase : null, on: nav.classList.contains("tl-on") }); if (now - first < 450) requestAnimationFrame(tick); else res(); }; requestAnimationFrame(tick); });
      num(`R59′b″ RM 滑动 中心 x 对 ζ.9/.2 闭式 rms（${sl.length} 帧，自驱动起点；§6.9 ③ RM 分支原值 0x1c50e8690，一根弹簧驱动框与透镜）`, 0, rms(sl.map((s) => s.cx - closedRM(c04, tx4 - navL4, s.t))), 1);
      check(`R59′b RM 全程不抬不拉伸：每帧 宽 = ${w04}、高 = ${h0}、p = 0（§12b ②：无 setLifted、无 .95 平台缩放）`, "every frame", sl.every((s) => Math.abs(s.w - w04) <= 0.5 && Math.abs(s.h - h0) <= 0.5 && s.p === 0) ? "every frame" : `OFF（宽 ${Math.max(...sl.map((s) => s.w)).toFixed(1)} 高 ${Math.max(...sl.map((s) => s.h)).toFixed(1)} p ${Math.max(...sl.map((s) => s.p || 0)).toFixed(3)}）`, sl.length > 10 && sl.every((s) => Math.abs(s.w - w04) <= 0.5 && Math.abs(s.h - h0) <= 0.5 && s.p === 0));
      check("R59′b RM 按住 450 ms：驱动仍在（.tl-on）、透镜停在按下项中心（|Δ| ≤ .5；选择在 touch-down 发生，抬手才换页）", "tl-on · |Δ| ≤ .5", `${nav.classList.contains("tl-on") ? "tl-on" : "off"} · |Δ| ${Math.abs(cx4() - (tx4 - navL4)).toFixed(2)}`, nav.classList.contains("tl-on") && Math.abs(cx4() - (tx4 - navL4)) <= 0.5);
      /* a drag under RM: the target follows the finger rule, still no lift */
      ev(tgt4, "pointermove", tx4 + 30, ty4, 21); await new Promise((r) => requestAnimationFrame(r)); const Lm4 = window.__tabLens;
      check("R59′b RM 拖动：目标 = 手指规则（x − a·W + W/2）、无 lift（高 54、p 0）", "目标 = 手指 + 30 · h 54 · p 0", Lm4 ? `目标 ${Lm4.target.toFixed(1)} vs ${(tx4 + 30 - navL4).toFixed(1)} · h ${rect().height.toFixed(1)} · p ${Lm4.p}` : "无驱动", !!Lm4 && Math.abs(Lm4.target - (tx4 + 30 - navL4)) <= 0.5 && Math.abs(rect().height - h0) <= 0.5 && Lm4.p === 0);
      ev(tgt4, "pointermove", tx4, ty4, 21); await sleep(300);
      ev(tgt4, "pointerup", tx4, ty4, 21); await sleep(600); const on4 = bs.find((b) => b.classList.contains("on"));
      check("R59′b RM 抬手：选中被按项、驱动停（无 .tl-on）、胶囊在其中心", `${tgt4.dataset.tab} · off · 中心`, `${on4 ? on4.dataset.tab : "-"} · ${nav.classList.contains("tl-on") ? "tl-on" : "off"} · |Δ| ${Math.abs(cx4() - (tx4 - navL4)).toFixed(2)}`, on4 === tgt4 && !nav.classList.contains("tl-on") && Math.abs(cx4() - (tx4 - navL4)) <= 1);
      delete seg.dataset.pe;
      /* back to the original tab, still under RM (the same path) */
      const sr4 = sel4.getBoundingClientRect(); ev(sel4, "pointerdown", sr4.left + sr4.width / 2, sr4.top + sr4.height / 2, 22); await sleep(350); ev(sel4, "pointerup", sr4.left + sr4.width / 2, sr4.top + sr4.height / 2, 22); await sleep(700); delete seg.dataset.pe;
      check("R59′b RM 再按回原项：回到原项、驱动停", `${sel4.dataset.tab} · off`, `${(bs.find((b) => b.classList.contains("on")) || {}).dataset?.tab || "-"} · ${nav.classList.contains("tl-on") ? "tl-on" : "off"}`, bs.find((b) => b.classList.contains("on")) === sel4 && !nav.classList.contains("tl-on"));
      /* the record against the read spring: tools/touch/seg-native-r59-motion.json tabhold, frames +75.3 … +275.2 ms after the down, start +42.6 ms (the touch log marks a 41 ms
         stall there; the tap record starts +21.2): ζ .9 / .2 leaves .11 pt rms; the R94 held slide: the finger rule + ζ .9 / .2 + a 2-frame delivery latency 1.15 (§6.9 ④) */
      const rec = [[75.3, 209.49], [91.9, 175.24], [108.6, 146.58], [125.3, 125.07], [142.0, 110.08], [158.6, 100.23], [175.3, 94.10], [192.0, 90.48], [208.7, 88.46], [225.2, 87.42], [241.9, 86.94], [258.5, 86.77], [275.2, 87.0]];
      const recRms = rms(rec.map(([t, x]) => x - closedRM(259, 87, (t - 42.6) / 1000)));
      num("R59′b″ 记录核：R59″ tabhold 13 帧（259 → 87）对 ζ.9/.2 闭式（起点 +42.6）rms（pt；R94 按住滑动 + 2 帧送达延迟 1.15，§6.9 ④）", 0, recRms, 0.2);
    } finally { window.__forceRM = null; } }
    /* ---- R59′b‴ / R106 ② the up's commit rules (tab-lens-motion.md §6.9 ② handleSelectionGesture 0x1c50e9078; view.js attachTabBar): an up outside the window inset by 8 only
       clears the highlight (no selection); the already selected item dragged ≥ 4 pt in x is not reselected (no scroll-to-top); otherwise the item under the finger is selected at
       once and the lens's target is its frame (the 7b / R33 rows above show the last) */
    { const on6 = bs.find((b) => b.classList.contains("on")), o6 = bs[bs.indexOf(on6) === 0 ? 1 : 0], r6 = o6.getBoundingClientRect(), x6 = r6.left + r6.width / 2, y6 = r6.top + r6.height / 2;
      ev(o6, "pointerdown", x6, y6, 51); await sleep(250); ev(o6, "pointermove", 3, y6, 51); await sleep(60); ev(o6, "pointerup", 3, y6, 51); await sleep(1400); delete seg.dataset.pe;   // the lens slides back from the track's end (.85 / .4) and falls within 8 pt (ζ 1 / .4): ≈ 1.2 s to rest
      const onAfter = bs.find((b) => b.classList.contains("on"));
      check("R106 ② 抬在窗口内缩 8 之外（x = 3）：只清高亮不选（选中项不变、透镜回原项、驱动停）", `${on6.dataset.tab} · off`, `${onAfter ? onAfter.dataset.tab : "-"} · ${nav.classList.contains("tl-on") ? "tl-on" : "off"} · |Δ| ${Math.abs(rect().cx - (on6.getBoundingClientRect().left + on6.getBoundingClientRect().width / 2)).toFixed(1)}`, onAfter === on6 && !nav.classList.contains("tl-on") && Math.abs(rect().cx - (on6.getBoundingClientRect().left + on6.getBoundingClientRect().width / 2)) <= 1.5);
      const app6 = document.getElementById("app"), mh6 = app6.style.minHeight; app6.style.minHeight = (innerHeight + 600) + "px";   // the current tab's page may be short: make it scrollable for the two scroll-to-top rows
      window.scrollTo(0, 240); await sleep(80); const y0s = window.scrollY; const sr6 = on6.getBoundingClientRect(), sx6 = sr6.left + sr6.width / 2, sy6 = sr6.top + sr6.height / 2;
      ev(on6, "pointerdown", sx6, sy6, 52); await sleep(200); ev(on6, "pointermove", sx6 + 5, sy6, 52); await sleep(60); ev(on6, "pointerup", sx6 + 5, sy6, 52); await sleep(400); delete seg.dataset.pe;
      const stA = window.ScrollTop && window.ScrollTop.state, movedTop = !!stA && stA.t0 > performance.now() - 700;
      check("R106 ② 已选项按住拖 ≥ 4 pt（+5）再抬：不重选（不回顶，scrollY 不动），选中不变", `不回顶 · scrollY ${y0s}`, `${movedTop ? "回顶了" : "不回顶"} · scrollY ${window.scrollY} · ${(bs.find((b) => b.classList.contains("on")) || {}).dataset?.tab}`, !movedTop && y0s > 0 && Math.abs(window.scrollY - y0s) < 2 && bs.find((b) => b.classList.contains("on")) === on6);
      ev(on6, "pointerdown", sx6, sy6, 53); await sleep(60); ev(on6, "pointerup", sx6 + 2, sy6, 53); await sleep(80); const stB = window.ScrollTop && window.ScrollTop.state, tappedTop = !!stB && stB !== stA; await sleep(1900); delete seg.dataset.pe;   // the driver's state is read while the scroll runs (it is cleared when done)
      check("R106 ② 已选项按住拖 < 4 pt（+2）再抬：仍算重选（回顶，scrollY → 0）", "回顶 · scrollY 0", `${tappedTop ? "回顶" : "没回顶"} · scrollY ${window.scrollY}`, tappedTop && window.scrollY === 0);
      window.scrollTo(0, 0); app6.style.minHeight = mh6; await sleep(100); }
    /* ---- R96 (页面 bug): the lens canvases must not paint past the viewport — with five tabs nav ± 24 reaches x 452 / y 968, the segment canvas is scaled × ≤ 1.15 by the
       flex transform while dragging; a mobile browser widens the layout viewport to the content (界面's frame log: innerWidth 440 → 455, the fixed bar 3 px lower = the user's
       bug ②) or pans sideways. Each canvas now sits in a .lens-clip box = its nominal box clamped to the viewport (LensWebGL.clipCanvas); checked in every state: the
       clip boxes inside [0, innerWidth] (× [0, innerHeight] for the bar), the canvases' own transformed boxes may exceed (they are clipped), scrollWidth = innerWidth. */
    { const clips = () => [...document.querySelectorAll(".lens-clip")].map((w) => { const r = w.getBoundingClientRect(); return { who: w.querySelector("canvas") ? w.querySelector("canvas").className : "?", l: r.left, t: r.top, r: r.right, b: r.bottom, y: w.parentElement && w.parentElement.matches("nav.tabs") }; });
      const inside = (c) => c.l >= -0.5 && c.r <= innerWidth + 0.5 && (!c.y || (c.t >= -0.5 && c.b <= innerHeight + 0.5));
      const states = []; const rec = (tag) => states.push({ tag, sw: document.documentElement.scrollWidth, iw: innerWidth, clips: clips(), bad: clips().filter((c) => !inside(c)).map((c) => `${c.who} ${Math.round(c.l)}…${Math.round(c.r)}${c.y ? `/${Math.round(c.t)}…${Math.round(c.b)}` : ""}`) });
      rec("rest");
      const on9 = bs.find((b) => b.classList.contains("on")), o9 = bs[bs.indexOf(on9) === 0 ? 1 : 0], r9 = o9.getBoundingClientRect(), x9 = r9.left + r9.width / 2, y9 = r9.top + r9.height / 2;
      ev(o9, "pointerdown", x9, y9, 31); await waitClass("lift", 600); await sleep(300); rec("tab lift"); ev(o9, "pointermove", x9 + 80, y9, 31); await sleep(250); rec("tab drag"); ev(o9, "pointermove", x9, y9, 31); await sleep(200); ev(o9, "pointerup", x9, y9, 31); await sleep(900); delete seg.dataset.pe;
      const qseg9 = document.querySelector("#queueseg"), qb9 = qseg9 ? [...qseg9.querySelectorAll("button")] : [];
      if (qb9.length >= 2) { const b9 = qb9.find((b) => b.classList.contains("on")) || qb9[0], rr9 = b9.getBoundingClientRect(), bx = rr9.left + rr9.width / 2, by = rr9.top + rr9.height / 2;
        ev(b9, "pointerdown", bx, by, 32); await sleep(450); rec("seg lift"); ev(b9, "pointermove", bx + 60, by, 32); await sleep(250); rec("seg drag"); ev(b9, "pointermove", bx, by, 32); await sleep(150); ev(b9, "pointerup", bx, by, 32); await sleep(900); delete qseg9.dataset.pe; }
      const wraps = [...document.querySelectorAll("#app .lens-clip, nav.tabs .lens-clip")], orphans = wraps.filter((w) => !w.querySelector("canvas")).length, tabWraps = nav.querySelectorAll(":scope > .lens-clip, :scope > canvas.tlens-gl").length;   // the live page only (a glass layer's page copy drops the canvases and, since R96, their wrappers)
      check(`R96 透镜画布钳进视口：画布都在 .lens-clip 裁框里（标签栏框还裁到 innerHeight；标签栏里恰一张画布、无空裁框）；静止 / 标签抬起 / 标签拖动 / 分段抬起 / 分段拖动 ${states.length} 态裁框都在 [0, ${innerWidth}]，scrollWidth = innerWidth`, "标签栏 1 张 · 空裁框 0 · 全态在内 · scrollWidth = innerWidth", `标签栏 ${tabWraps} 张 · 空裁框 ${orphans}（裁框共 ${wraps.length}） · ${states.every((st) => st.bad.length === 0) ? "全态在内" : "越界 " + states.filter((st) => st.bad.length).map((st) => `${st.tag}: ${st.bad.join(" ")}`).join("; ")} · ${states.map((st) => `${st.tag} sw ${st.sw}`).join(", ")}`,
        tabWraps === 1 && orphans === 0 && wraps.length >= 2 && states.every((st) => st.bad.length === 0 && st.sw === st.iw)); }
    /* ---- R0② the tab set changes under the bar (the user's bug 2: 切晚班再切早班 the capsule flashed downward — the bar was rebuilt): view.js keeps the
       nodes (R0①) and tells the driver with "tabs-changed"; per frame through 早 → 晚 → 早: nav's top unchanged, never display none, .plat / .glide / .seg
       the same elements, the button count never 0, the glide 54 high and on the selected button (≤ 1 pt), the driver idle (no __tabLens, no .tl-on) */
    { const qseg = document.querySelector("#queueseg"); const qbs = qseg ? [...qseg.querySelectorAll("button")] : [];
      if (qbs.length >= 2) {
        const plat = nav.querySelector(".plat"), gl0 = nav.querySelector(".glide"), sg0 = nav.querySelector(".seg"), r00 = nav.getBoundingClientRect(), top0 = r00.top, navH0 = r00.height, cur0 = qbs.findIndex((b) => b.classList.contains("on"));
        /* A16 (this row went red 6 times on first runs after merges, "nav top 4 frames", never reproduced here in 10+ runs): the nav is position:fixed at
           bottom = env(safe-area) + 12, so its top can move for two reasons — the page (its height or a transform: the user's bug) or the harness's viewport
           (a headless emulation / scrollbar / visual-viewport hiccup). Each frame the nav's top is judged against where its own CSS puts it, expTop =
           clientHeight − bottom − height: a page cause shows as |top − expTop| > .5 or a height change (`top` / `h`, red); a viewport change moves top and
           expTop together (`vp`, recorded, not red); the first deviating frames are printed with their numbers so a red run says why. */
        const bad = { top: 0, none: 0, node: 0, zero: 0, h: 0, pos: 0, drv: 0, vp: 0 }; let frames = 0, events = 0; const onEv = () => events++; nav.addEventListener("tabs-changed", onEv); const dev = [];
        const watch = (ms) => new Promise((res) => { let first = null; const tick = (now) => { if (first === null) first = now; frames++;
          const r = nav.getBoundingClientRect(), g = nav.querySelector(".glide"), on = nav.querySelector(".seg button.on"), n = nav.querySelectorAll(".seg button").length;
          /* the nav's CSS position from either viewport height the browser reports: innerHeight (the initial containing block of position:fixed) or documentElement.clientHeight —
             in headless Chrome the two diverge for a frame or two during the tab-set change (seen 2026-09-20 09:1x dark run: innerHeight 959 vs clientHeight 956 for frames 14–15,
             the nav at 885 = 959 − 12 − 62 while top0 was 882): the page is where its CSS puts it, the viewport moved — `vp`, not a page bug */
          const cs = getComputedStyle(nav), bot = parseFloat(cs.bottom) || 0, expInner = innerHeight - bot - r.height, expClient = document.documentElement.clientHeight - bot - r.height, dTop = r.top - top0, dExp = Math.min(Math.abs(r.top - expInner), Math.abs(r.top - expClient));
          if (Math.abs(dTop) > 0.5) { if (dExp > 0.5 || Math.abs(r.height - navH0) > 0.5 || !/^matrix\(1, 0, 0, 1, [-\d.]+, 0\)$|^none$/.test(cs.transform)) bad.top++; else bad.vp++;
            if (dev.length < 6) dev.push({ f: frames, top: +r.top.toFixed(2), d: +dTop.toFixed(2), expI: +expInner.toFixed(2), expC: +expClient.toFixed(2), h: +r.height.toFixed(2), ch: document.documentElement.clientHeight, ih: innerHeight, vv: window.visualViewport ? +visualViewport.height.toFixed(1) : null, sy: +scrollY.toFixed(1), tf: cs.transform, b: cs.bottom, cls: nav.className, kbd: document.documentElement.classList.contains("kbd") }); }
          if (Math.abs(r.height - navH0) > 0.5) bad.h++;
          if (getComputedStyle(nav).display === "none") bad.none++;
          if (nav.querySelector(".plat") !== plat || g !== gl0 || nav.querySelector(".seg") !== sg0) bad.node++; if (n === 0) bad.zero++;
          if (g) { const gr = g.getBoundingClientRect(); if (Math.abs(gr.height - 54) > 0.5) bad.gh = (bad.gh || 0) + 1; if (on) { const or = on.getBoundingClientRect(); if (Math.abs(gr.left - or.left) > 1 || Math.abs(gr.width - or.width) > 1) bad.pos++; } }
          if (window.__tabLens || nav.classList.contains("tl-on")) bad.drv++;
          if (now - first < ms) requestAnimationFrame(tick); else res(); }; requestAnimationFrame(tick); });
        const other = qbs[cur0 === 0 ? 1 : 0], back = qbs[cur0];
        delete qseg.dataset.pe; other.click(); await watch(500); delete qseg.dataset.pe; back.click(); await watch(500);   // the press flag of an earlier synthetic press (no browser click consumed it) would eat the click
        nav.removeEventListener("tabs-changed", onEv);
        const tabsNow = [...nav.querySelectorAll(".seg button")].map((b) => b.dataset.tab).join(",");
        const pageBad = Object.entries(bad).filter(([k]) => k !== "vp").every(([, v]) => v === 0);
        check(`R0② 切班次两次（${frames} 帧）：nav 在自己 CSS 的位置（top = clientHeight − bottom − 高，不变高、无 transform）/ 无 display none / 节点不重建 / 按钮数不为 0 / glide 高 54 / glide 在选中项 / 驱动不起（vp = 视口本身变的帧，只记不判）`, "页面项全 0", `${JSON.stringify(bad)} · tabs-changed ×${events} · ${tabsNow}${dev.length ? " · 偏帧 " + JSON.stringify(dev) : ""}`, pageBad);
        check("R0② 集合变时 nav 派发 tabs-changed（ui 807da64 接口）", "≥ 1", String(events), events >= 1 || tabsNow.split(",").length === 0);
        { const w9 = document.querySelector("nav.tabs .lens-clip"), r9 = w9 && w9.getBoundingClientRect(); check("R96 切班次后标签栏画布裁框仍在视口内（重建后重钳）", "在内", r9 ? `${Math.round(r9.left)}…${Math.round(r9.right)} / ${Math.round(r9.top)}…${Math.round(r9.bottom)}` : "无裁框", !!r9 && r9.left >= -0.5 && r9.right <= innerWidth + 0.5 && r9.top >= -0.5 && r9.bottom <= innerHeight + 0.5); }
      } else check("R0② 页面无两段可切（demo 应有早班/晚班）", "≥ 2 段", qbs.length + " 段", false); }
    if (typeof window.__tabKbd === "function") { window.__tabKbd(innerHeight - 300); await sleep(50); check("视口矮 300 后 nav.tabs display none（键盘规则）", "none", getComputedStyle(nav).display, getComputedStyle(nav).display === "none");
      window.__tabKbd(null); await sleep(50); const nb = nav.getBoundingClientRect(); check("复原后 nav.tabs 回到底部（innerHeight − bottom < 120）", "< 120", Math.round(innerHeight - nb.bottom), getComputedStyle(nav).display !== "none" && innerHeight - nb.bottom < 120); }
  });
})();
