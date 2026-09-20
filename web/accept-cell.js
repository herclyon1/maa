/* accept-cell.js — B14 UITableViewCell press through controls.js on a synthetic .row.nav and an action row (remote-ref/cell-native.md §0,
   state-tables/cell.md C*; 界面): C1 / C3 / C6 / C7 / C9 / C10 / C11, the 「开始刷」 alert path, the rest colour after a theme change. Split out of
   accept.js 2026-09-20 (BOARD 收尾单 ②); row texts and expected values unchanged. R.n = the page's render() count. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptCell(ctx) {
    const { check, num, col, sleep, settle, raf, sec, segRest, tabRest, fadeRest, at, pev, cs, px, T, dark, near, rgb, same, fmt, satTop, varColor, probe, q, bs, onText, thisShift, R } = ctx;
  /* §5 B14 UITableViewCell press (remote-ref/cell-native.md §0 probe originals, state-tables/cell.md C*) on a synthetic .row.nav and an
     action row inside a .group, through controls.js. Colours: --ios-cell-highlight light (209,209,214) / dark (58,58,60); the fade
     .5 s cubic-bezier(.42,0,.58,1) checked against the curve at the sampled instant (the same easeInOut UIView used). */
  if (sec("press", { layer: "timing", dark: true })) {   // cell press colours (the rest-colour row after a theme change included)
  const rLab = document.createElement("div"); rLab.style.cssText = "position:fixed;left:20px;top:500px;width:400px;z-index:99;opacity:0";
  rLab.innerHTML = `<div class="group"><div class="row nav"><label>上一行</label><span class="val">值</span><i class="sf chev"></i></div><div class="row nav"><label>行</label><span class="val">值</span><i class="sf chev"></i></div><div class="acts"><button type="button">蓝字行</button></div></div>`;
  document.body.appendChild(rLab);
  const [row0, row] = rLab.querySelectorAll(".row.nav"), act = rLab.querySelector(".acts button"); let rsel = 0, asel = 0;
  /* 收尾④ (两钟同读): the fade is read from the CSSTransition itself at the moment .hl-out is set (MutationObserver microtask; getAnimations() flushes
     style) — under the runner's virtual time the .5 s transition completes within one stepped frame, so a row sampled later sees the class gone */
  let fadeSeen = null; const fadeOf = (el) => { const a = el.getAnimations().find((x) => x.transitionProperty === "background-color"); if (!a) return null; const tm = a.effect.getTiming(); return { t: performance.now(), dur: tm.duration, easing: tm.easing, prop: a.transitionProperty }; };
  const seq = []; new MutationObserver(() => { seq.push([performance.now(), row.className]); if (row.classList.contains("hl-out")) { const f = fadeOf(row); if (f) fadeSeen = f; } }).observe(row, { attributes: true, attributeFilter: ["class"] });
  row.addEventListener("click", () => { rsel++; seq.push([performance.now(), "click"]); }); act.addEventListener("click", () => asel++);
  const HL = dark ? [58, 58, 60] : [209, 209, 214], bgOf = (el) => cs(el).backgroundColor, lit = (el) => same(bgOf(el), HL);
  const bez = (x) => { let lo = 0, hi = 1; for (let i = 0; i < 40; i++) { const t = (lo + hi) / 2, cx = 3 * .42 * t * (1 - t) * (1 - t) + 3 * .58 * t * t * (1 - t) + t * t * t; if (cx < x) lo = t; else hi = t; } const t = (lo + hi) / 2; return 3 * 0 * t * (1 - t) * (1 - t) + 3 * 1 * t * t * (1 - t) + t * t * t; };   // cubic-bezier(.42,0,.58,1)
  /* C3: hold 400 ms — nothing until +150, then the instant highlight; the fade from the up */
  pev(row, "pointerdown", at(row)); await sleep(100);
  check("列表行 C3 按下 +100 ms：无变化（延迟 150，--ios-touch-highlight-delay）", "rest", lit(row) ? "highlight" : "rest", !lit(row));
  await sleep(80);
  col("列表行 C3 按下 +180 ms：底色 = 高亮色（--ios-cell-highlight，cell-native.md §0）", HL, bgOf(row));
  check("列表行 C3 高亮中分隔线 opacity 0", "0", cs(row, "::after").opacity, cs(row, "::after").opacity === "0");
  check("列表行 C3 高亮中上一行的分隔线也 opacity 0（数据真机核 ④）", "0", cs(row0, "::after").opacity, cs(row0, "::after").opacity === "0");
  await sleep(220);
  const tUp = performance.now(); pev(row, "pointerup", at(row));
  await sleep(45);                                                                   // the device's own click comes 40–60 ms after the up
  row.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));   // = the browser's own click for this touch: swallowed
  check("列表行 抬手 +45 ms 浏览器自己的 click 被吞（data-rc；选中由页面在淡出首帧后发，此时已 1 次）", "1", rsel, rsel === 1);
  await sleep(15);
  { const fading = row.classList.contains("hl-out"), seen = !!fadeSeen && fadeSeen.t >= tUp && !row.classList.contains("hl");   // seen: the fade's transition started after the up (page clock) — the class may already be gone under a stepped clock
    check("列表行 C3 抬手 +60 ms：选中 1 次（淡出首帧之后一帧）、淡出中（.hl-out 在，或抬手后过渡对象已见——两钟同读）", "1, fading", `${rsel}, ${fading ? "fading" : seen ? "fade seen +" + Math.round(fadeSeen.t - tUp) + " ms" : "not fading"}`, rsel === 1 && (fading || seen)); }
  { const f = fadeSeen || {}, t = f.dur, e = f.easing, pr = f.prop;   // read from the transition object when .hl-out was set (收尾④), not from the computed style at +60
    check("列表行 淡出 = background-color .5 s cubic-bezier(.42,0,.58,1)（--ios-motion-row-release-duration / --ios-motion-ease-in-out；过渡对象自身的 duration / easing）", "background-color 500 cubic-bezier(0.42, 0, 0.58, 1)", `${pr} ${t} ${e}`, pr === "background-color" && t === 500 && e === "cubic-bezier(0.42, 0, 0.58, 1)"); }
  await sleep(200);
  { const el = performance.now() - tUp - 16, c = rgb(bgOf(row)), want = T.card[0] + (HL[0] - T.card[0]) * (1 - bez(Math.max(0, Math.min(1, el / 500))));   // the fade starts one frame after the up
    check(`列表行 抬手 +${Math.round(el)} ms：R 在曲线上（±8；原生 +235 ms 亮 227 / 暗 46）`, Math.round(want), c ? Math.round(c[0]) : "缺", !!c && Math.abs(c[0] - want) <= 8); }
  await sleep(420);
  col("列表行 抬手 +660 ms：回到静止色 = 卡片色（--ios-card-bg）", T.card, bgOf(row));
  check("列表行 淡完后类名清空", "clean", row.className, !row.classList.contains("hl") && !row.classList.contains("hl-out"));
  /* C1: a 100 ms tap — no highlight at the up; one frame of highlight at +150 and the fade from there; selected once */
  fadeSeen = null; const tUp1 = performance.now() + 100; pev(row, "pointerdown", at(row)); await sleep(100); pev(row, "pointerup", at(row));
  check("列表行 C1 短点 100 ms 抬手时：还没高亮", "rest", lit(row) ? "highlight" : "rest", !lit(row));
  seq.length = 0; await sleep(170);
  { const names = seq.map((e) => e[1]), iH = names.findIndex((n) => /\bhl\b/.test(n) && !/hl-out/.test(n)), iF = names.findIndex((n) => /hl-out/.test(n)), iC = names.indexOf("click");
    const gapHF = iH >= 0 && iF > iH ? seq[iF][0] - seq[iH][0] : -1, gapFC = iF >= 0 && iC > iF ? seq[iC][0] - seq[iF][0] : -1;
    check("列表行 C1 短点：高亮帧 → 淡出帧 → 选中，三者依次、各隔一次上屏（rAF + setTimeout 0；数据真机核 ②：confirm()/推页不得吞掉高亮帧）", "hl < hl-out < click", `${iH} < ${iF} < ${iC}, 间隔 ${Math.round(gapHF)} / ${Math.round(gapFC)} ms`, iH >= 0 && iF > iH && iC > iF); }   // the gaps are JS timestamps (the paint sits between rAF and the timeout; headless Chrome renders in < 1 ms): reported, not judged
  { const fading = row.classList.contains("hl-out"), seen = !!fadeSeen && fadeSeen.t >= tUp1 - 1 && !row.classList.contains("hl");
    check("列表行 C1 按下 +270 ms：高亮已亮过并在淡出（.hl-out 在，或过渡对象已见——两钟同读）、选中 1 次", "fading, 2", `${fading ? "fading" : seen ? "fade seen" : row.classList.contains("hl") ? "lit" : "rest"}, ${rsel}`, (fading || seen) && rsel === 2); }
  await fadeRest(row, 620);   // S1: the .5 s release fade is a CSS transition — wait for its own end
  /* C6: vertical 12 pt after the highlight — off at once, the up selects nothing */
  pev(row, "pointerdown", at(row)); await sleep(200); pev(row, "pointermove", at(row, .5, .5, 0, 12));
  check("列表行 C6 竖滑 12 pt：高亮瞬时灭（touchesCancelled → animated:NO）", "rest, no fade", `${lit(row) ? "highlight" : "rest"}, ${row.classList.contains("hl-out") ? "fade" : "no fade"}`, !lit(row) && !row.classList.contains("hl-out"));
  pev(row, "pointerup", at(row, .5, .5, 0, 12)); await sleep(40);
  check("列表行 C6 竖滑后抬手：不选中", 2, rsel, rsel === 2);
  /* C9: a fast swipe never highlights */
  pev(row, "pointerdown", at(row)); pev(row, "pointermove", at(row, .5, .5, 0, 20)); await sleep(200);
  check("列表行 C9 快滑 20 pt：不高亮", "rest", lit(row) ? "highlight" : "rest", !lit(row));
  pev(row, "pointerup", at(row, .5, .5, 0, 20)); await sleep(40);
  /* C7/C10: 100 pt sideways inside the card keeps the press and selects; C11: 16 pt past the card's edge cancels */
  pev(row, "pointerdown", at(row)); await sleep(200); pev(row, "pointermove", at(row, .5, .5, 100, 0));
  check("列表行 C10 横滑 100 pt（行内）：仍高亮", "highlight", lit(row) ? "highlight" : "rest", lit(row));
  pev(row, "pointerup", at(row, .5, .5, 100, 0)); await sleep(60);
  check("列表行 C10 横滑 100 pt 抬手：选中", 3, rsel, rsel === 3);
  await fadeRest(row, 620);
  pev(row, "pointerdown", at(row)); await sleep(200); pev(row, "pointermove", at(row, 1, .5, 16, 0));
  check("列表行 C11 出卡片边 16 pt：高亮灭", "rest", lit(row) ? "highlight" : "rest", !lit(row));
  await sleep(30);
  col("列表行 C11 出边 +30 ms：底色已是静止色（瞬灭，无淡回）", T.card, bgOf(row));
  pev(row, "pointerup", at(row, 1, .5, 16, 0)); await sleep(40);
  check("列表行 C11 出边抬手：不选中", 3, rsel, rsel === 3);
  /* the action row (.acts button) is the same cell */
  /* the 「开始刷」 path: the row's click opens the page's alert (ask(), the way view.js's action rows now do instead of the browser's blocking
     confirm dialog); a rAF loop logs the row's class at every frame (a rAF tick sees what that frame paints): a highlight frame and a fade
     frame must have been logged before the alert opened, and the fade must keep running under the open alert (native: deselectRow's .5 s
     fade runs while the alert presents) */
  const frames = []; let logging = true; const logFrame = () => { frames.push([performance.now(), act.className]); if (logging) requestAnimationFrame(logFrame); }; requestAnimationFrame(logFrame);   // 收尾④: the page clock (the rAF timestamp is a second clock under virtual time; blockedAt is performance.now())
  const actSeq = []; new MutationObserver(() => actSeq.push([performance.now(), act.className])).observe(act, { attributes: true, attributeFilter: ["class"] });   // the class sequence itself (page clock): under a stepped clock the fade class can come and go between two rAF frames
  let blockedAt = 0, askP = null; act.addEventListener("click", () => { blockedAt = performance.now(); askP = ask("开始刷？", "验收：弹窗打开后淡回仍在走", "开始刷"); });
  const framesBefore = () => { const fr = frames.concat(actSeq).filter((f) => f[0] < blockedAt); return { hl: fr.some((f) => /\bhl\b/.test(f[1]) && !/hl-out/.test(f[1])), out: fr.some((f) => /hl-out/.test(f[1])) }; };
  pev(act, "pointerdown", at(act)); await sleep(100); pev(act, "pointerup", at(act)); await sleep(60);
  const alertEl = document.querySelector("#alert"), r60 = rgb(bgOf(act));
  await sleep(200); const r210 = rgb(bgOf(act)), openAt60 = !!(alertEl && alertEl.open);   // the click (and the alert) comes ~2 frames after the +150 ms highlight of a 100 ms tap
  await sleep(400);
  { const b = framesBefore(); check("蓝字行 短点 100 ms，click 开页面弹窗（ask）：弹窗前已有高亮帧与淡出帧上屏（数据真机核 ②）", "hl 帧, hl-out 帧, 弹窗开（up +260）, 触发 1", `${b.hl ? "hl 帧" : "无 hl 帧"}, ${b.out ? "hl-out 帧" : "无 hl-out 帧"}, ${openAt60 ? "弹窗开" : "弹窗未开"}, 触发 ${asel}`, b.hl && b.out && openAt60 && asel === 1);
    const moving = !!(r60 && r210) && (dark ? r210[0] < r60[0] - 2 : r210[0] > r60[0] + 2), rest = same(bgOf(act), T.card);
    check("蓝字行 弹窗打开后淡回仍在走（up +60 → +260 ms 底色继续向静止色走，+660 到静止）", "走, 到静止", `${moving ? "走" : "停"}（R ${r60 ? Math.round(r60[0]) : "?"} → ${r210 ? Math.round(r210[0]) : "?"}）, ${rest ? "到静止" : "未到"}`, moving && rest); }
  if (alertEl && alertEl.open) { document.querySelector("#alert-cancel").click(); await settle(() => !alertEl.open, 450); }
  if (askP) await askP;
  frames.length = 0; actSeq.length = 0; blockedAt = 0;
  pev(act, "pointerdown", at(act)); await sleep(200);
  col("蓝字行 按下 +200 ms：底色 = 高亮色（同 cell）", HL, bgOf(act));
  pev(act, "pointerup", at(act)); await sleep(80);
  { const b = framesBefore(); check("蓝字行 长按抬手 +80 ms：淡出首帧已上屏后才触发（弹窗），触发 2 次", "hl-out 帧在前, 2", `${b.out ? "hl-out 帧在前" : "无"}, ${asel}`, b.out && asel === 2); }
  logging = false;
  if (alertEl && alertEl.open) { document.querySelector("#alert-cancel").click(); await settle(() => !alertEl.open, 450); }
  if (askP) await askP;
  await fadeRest(act, 620);
  pev(act, "pointerdown", at(act)); await sleep(200); pev(act, "pointermove", at(act, 1, .5, 16, 0)); await sleep(30);
  col("蓝字行 出卡片边 16 pt +30 ms：瞬灭到静止色（数据真机核 ①：不走基础 .5 s transition）", T.card, bgOf(act));
  pev(act, "pointerup", at(act, 1, .5, 16, 0)); await sleep(60);
  check("蓝字行 出边抬手：不触发", 2, asel, asel === 2);
  /* the rest colour follows the theme's --card token and no press state outlives a press: after everything above, every action row / nav
     row in the document rests on the current theme's card colour with no state class or mark left (the device's dark → light report) */
  await sleep(200);
  { const leftovers = [...document.querySelectorAll(".row.nav, .group .acts button")].filter((el) => el.classList.contains("hl") || el.classList.contains("hl-out") || el.classList.contains("hl-cut") || el.dataset.rp || el.dataset.rc);
    check("行静止底 = 当前主题卡片色（--ios-card-bg），无残留状态类 / 标记（切主题后不留旧色）", `${fmt(T.card)}, 0 残留`, `${bgOf(act)}, ${leftovers.length} 残留`, same(bgOf(act), T.card) && same(bgOf(row), T.card) && leftovers.length === 0);
    document.dispatchEvent(new Event("visibilitychange")); }   // the strip on hide runs without error (a hidden page cannot be simulated here)
  rLab.remove(); }
  }, { layer: "timing", dark: true });
})();
