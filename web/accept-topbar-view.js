/* accept-topbar-view.js — the top bar's static rows from accept.js (bar height 54 under the safe area, the large title 34 / 40.57; 界面).
   accept-topbar.js (数据) holds the large-title collapse rows. Split out of accept.js 2026-09-20 (BOARD 收尾单 ②). */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptTopbarView(ctx) {
    const { check, num, col, sleep, settle, raf, sec, segRest, tabRest, fadeRest, at, pev, cs, px, T, dark, near, rgb, same, fmt, satTop, varColor, probe, q, bs, onText, thisShift, R } = ctx;
    sec("static", { layer: "static" });
  const top = document.querySelector(".topbar");
  if (top) {
    const sat = satTop();
    num("顶栏高 = 安全区 + 54（--ios-nav-h，AX-45 NavigationBar (0,62,440,54)）", 54, top.getBoundingClientRect().height - sat);
  }
  const h1 = document.querySelector("header h1");
  if (h1) { num("大标题字号 34（--ios-large-title-size）", 34, px(cs(h1).fontSize), 0.1); num("大标题行框 40.57（--ios-large-title-lh）", 40.57, px(cs(h1).lineHeight), 0.05); check("大标题字重 700（NUMBERS 56）", 700, cs(h1).fontWeight, String(cs(h1).fontWeight) === "700"); }
  }, { layer: "static" });
})();
