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
      back on view.js's box; the keyboard rule's two lines (view.js __tabKbd) as in accept.js. */
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
    /* ① + ② press another item */
    ev(other, "pointerdown", ox, oy); const dLift = await waitClass("lift", 600);
    const delay = px("--ios-touch-tab-glide-delay", 140);
    check(`按下未选中项 +${delay} ms 抬起（.lift）`, `${delay}…${delay + 50} ms`, dLift === null ? "没抬" : Math.round(dLift) + " ms", dLift !== null && dLift >= delay - 5 && dLift <= delay + 50);
    await new Promise((r) => requestAnimationFrame(r)); const L0 = window.__tabLens;
    if (!L0) { check("标签栏：抬起后驱动在跑（window.__tabLens）", "有", "缺", false); ev(other, "pointerup", ox, oy); return; }
    const lift = await sample(600, L0.t0);
    num(`抬起 宽 对 ζ1/.25 闭式 rms（${lift.length} 帧；${w0} → ${w0 + 16}）`, 0, rms(lift.map((s) => s.width - crit(w0, w0 + 16, 0.25, s.t))), 1);
    num(`抬起 高 对 ζ1/.25 闭式 rms（${h0} → ${h0 + 16}）`, 0, rms(lift.map((s) => s.height - crit(h0, h0 + 16, 0.25, s.t))), 1);
    num("抬起 中心 x 对 ζ.85/.4 闭式 rms（旧项中心 → 按下项中心）", 0, rms(lift.map((s) => s.cx - under(r0.cx, ox, 0.85, 0.4, s.t))), 1);
    num("抬满后 宽 = w0 + 16", w0 + 16, rect().width, 0.5); num("抬满后 高 = 54 + 16", h0 + 16, rect().height, 0.5);
    num("抬满后 圆角 = 高 / 2（胶囊，999px）", (h0 + 16) / 2, Math.min(parseFloat(getComputedStyle(g).borderTopLeftRadius), rect().height / 2), 0.5);
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
    ev(selB, "pointerdown", sx, sy, 5); const dSel = await waitClass("lift-sel", 600); const selDelay = px("--ios-touch-tab-selected-lift-delay", 125);
    check(`按下已选中项 +${selDelay} ms 抬起（.lift-sel）`, `${selDelay}…${selDelay + 50} ms`, dSel === null ? "没抬" : Math.round(dSel) + " ms", dSel !== null && dSel >= selDelay - 5 && dSel <= selDelay + 50);
    await sleep(150); const hiddenDesc = Object.getOwnPropertyDescriptor(Document.prototype, "hidden"); Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true })); await sleep(30);
    check("抬起中 hidden → 驱动停、glide 回 view.js 的框", "无 .tl-on", nav.classList.contains("tl-on") ? "还在" : "无 .tl-on", !nav.classList.contains("tl-on"));
    delete document.hidden; if (hiddenDesc) Object.defineProperty(Document.prototype, "hidden", hiddenDesc);
    ev(selB, "pointerup", sx, sy, 5); await sleep(700);
    if (typeof window.__tabKbd === "function") { window.__tabKbd(innerHeight - 300); await sleep(50); check("视口矮 300 后 nav.tabs display none（键盘规则）", "none", getComputedStyle(nav).display, getComputedStyle(nav).display === "none");
      window.__tabKbd(null); await sleep(50); const nb = nav.getBoundingClientRect(); check("复原后 nav.tabs 回到底部（innerHeight − bottom < 120）", "< 120", Math.round(innerHeight - nb.bottom), getComputedStyle(nav).display !== "none" && innerHeight - nb.bottom < 120); }
  });
})();
