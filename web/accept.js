/* 验收：页面地址加 ?accept 时加载，在这台设备的浏览器里量 DOM，逐项和
   docs/HIG-CHECKLIST.md 的数字比。只认 iOS Safari 的数（桌面 Chromium 的
   -apple-system-body 是 16，也没有安全区）。结果存进 localStorage 的 ark-accept，
   scripts/mac/phone-accept.sh 从模拟器的存储里读出来；不加 &quiet 时左上角盖一张表。
   方法照 ~/Money/transit/ui/accept.js（另一个会话 2026-09-15 定型）。 */
(function () {
  const q = new URLSearchParams(location.search);
  if (!q.has("accept")) return;
  const rows = [];
  const near = (a, b, tol = 0.6) => Math.abs(a - b) <= tol;
  const cs = (el, pseudo) => el ? getComputedStyle(el, pseudo || null) : null;
  const px = (v) => parseFloat(v) || 0;
  function check(item, expect, got, ok) {
    rows.push({ item, expect: String(expect), got: got === undefined || got === null ? "缺" : String(typeof got === "number" ? Math.round(got * 100) / 100 : got), ok: !!ok });
  }
  function num(item, expect, got, tol) { check(item, expect, got, typeof got === "number" && near(got, expect, tol)); }

  function run() {
    const root = px(cs(document.documentElement).fontSize);
    num("根字号（正文 17）", 17, root, 0.01);
    const ff = cs(document.body).fontFamily;
    check("字体栈含 -apple-system 或 PingFang", "是", /-apple-system|PingFang/i.test(ff) ? "是" : ff.slice(0, 40), /-apple-system|PingFang/i.test(ff));
    const tint = cs(document.documentElement).getPropertyValue("--accent").trim();
    check("tint", "#0088ff / #0a84ff", tint, /^#0088ff$|^#0a84ff$/i.test(tint));

    const main = document.querySelector("main");
    if (main) num("卡片距屏边（main 左内边距）", 20, px(cs(main).paddingLeft));
    const group = document.querySelector("section .group:not(.tiles):not(.nums):not(.devcard):not(.notice)");
    if (group) {
      num("卡片圆角", 26, px(cs(group).borderTopLeftRadius));
      const r = group.getBoundingClientRect();
      num("卡片左边 = 20", 20, r.left);
      num("卡片宽 = 视口 − 40", innerWidth - 40, r.width);
    }
    const row = document.querySelector(".row:has(> .sw), .row:has(> select)") || document.querySelector(".row");
    if (row) {
      num("行高 ≥ 53.33（单行）", 53.33, Math.min(row.getBoundingClientRect().height, 53.33));
      num("行左内边距", 20, px(cs(row).paddingLeft));
      const a = cs(row, "::after");
      const sy = /matrix\([^,]+,[^,]+,[^,]+,\s*([\d.]+)/.exec(a.transform);
      num("分隔线 = 1 设备像素（1px × scaleY .34）", 0.34, px(a.height) * (sy ? parseFloat(sy[1]) : 1), 0.02);
      num("分隔线左缩进", 20, px(a.left));
      num("分隔线右缩进", 20, px(a.right));
    }
    const sw = document.querySelector(".sw");
    if (sw) {
      const r = sw.getBoundingClientRect();
      num("开关宽", 63, r.width); num("开关高", 28, r.height);
      const knob = cs(sw.querySelector("span"), "::after");
      num("开关圆钮宽", 38, px(knob.width)); num("开关圆钮高", 24, px(knob.height));
      const rr = sw.closest(".row");
      if (rr) num("开关距卡片右边", 18, rr.getBoundingClientRect().right - r.right);
    }
    const h2 = document.querySelector("section h2");
    if (h2) {
      const c = cs(h2);
      num("段头字号", 17, px(c.fontSize), 0.05); check("段头字重 600", 600, c.fontWeight, String(c.fontWeight) === "600");
      num("段头上边距", 28, px(c.paddingTop)); num("段头下边距", 6, px(c.paddingBottom));
      num("段头文字内缩", 20, px(c.paddingLeft));
    }
    const foot = document.querySelector("section .foot");
    if (foot) {
      const c = cs(foot);
      num("段尾字号", 13, px(c.fontSize), 0.05); num("段尾上边距", 6, px(c.paddingTop)); num("段尾下边距", 24, px(c.paddingBottom));
    }
    const tile = document.querySelector(".tile");
    if (tile) {
      const r = tile.getBoundingClientRect();
      num("动作磁贴高 ≥ 80", 80, Math.min(r.height, 80)); num("动作磁贴圆角", 16, px(cs(tile).borderTopLeftRadius));
      num("磁贴间距", 8, px(cs(tile.parentElement).columnGap));
      const ico = tile.querySelector(".tico"); if (ico) num("磁贴图标圆", 28, ico.getBoundingClientRect().width);
    }
    const numT = document.querySelector(".num");
    if (numT) {
      const r = numT.getBoundingClientRect();
      num("数字磁贴高 ≥ 80.33", 80.33, Math.min(r.height, 80.33)); num("数字磁贴圆角", 16, px(cs(numT).borderTopLeftRadius));
      const ico = numT.querySelector(".nico"); if (ico) num("数字磁贴图标圆", 32, ico.getBoundingClientRect().width);
      const big = numT.querySelector(".big"); if (big) num("数字磁贴大数字号", 24, px(cs(big).fontSize), 0.1);
      const lab = numT.querySelector(".lab"); if (lab) num("数字磁贴名字字号", 15, px(cs(lab).fontSize), 0.1);
    }
    const dev = document.querySelector(".devcard");
    if (dev) { num("设备卡最小高", 72, Math.min(dev.getBoundingClientRect().height, 72)); const i = dev.querySelector(".dico"); if (i) num("设备卡图标框", 44, i.getBoundingClientRect().width); }
    const seg = document.querySelector("nav.tabs .seg");
    if (seg) {
      const r = seg.getBoundingClientRect();
      num("标签栏胶囊高", 62, r.height);
      const gap = innerHeight - r.bottom;
      const standalone = matchMedia("(display-mode: standalone)").matches;
      if (standalone) num("标签栏底边距屏底（主屏幕 app）", 22, gap);
      else check("标签栏在 Safari 地址栏之上", "> 0", Math.round(gap), gap > 0);
      const b = seg.querySelector("button"); if (b) { const w = b.getBoundingClientRect().width; num("标签按钮高", 54, b.getBoundingClientRect().height); check("标签按钮宽 ≥ 72", "≥ 72", w, w >= 71.5); num("标签文字", 10, px(cs(b).fontSize), 0.05); }
      const ico = seg.querySelector(".ico"); if (ico) num("标签符号框", 28, ico.getBoundingClientRect().height);
    }
    const top = document.querySelector(".topbar");
    if (top) {
      const probe = document.createElement("div"); probe.style.cssText = "position:fixed;top:0;left:0;width:1px;padding-top:env(safe-area-inset-top);visibility:hidden";
      document.body.appendChild(probe); const sat = px(cs(probe).paddingTop); probe.remove();
      num("顶栏高 = 安全区 + 44", 44, top.getBoundingClientRect().height - sat);
    }
    const h1 = document.querySelector("header h1");
    if (h1) { num("大标题字号", 34, px(cs(h1).fontSize), 0.1); check("大标题字重 700", 700, cs(h1).fontWeight, String(cs(h1).fontWeight) === "700"); }
    const meta = document.querySelector('meta[name="theme-color"]');
    check("theme-color 存在", "是", meta ? "是" : "缺", !!meta);

    const fails = rows.filter((r) => !r.ok).length;
    const out = { at: new Date().toISOString(), href: location.href, viewport: `${innerWidth}×${innerHeight}`,
                  standalone: matchMedia("(display-mode: standalone)").matches,
                  dark: matchMedia("(prefers-color-scheme: dark)").matches, total: rows.length, fails, rows };
    try { localStorage.setItem("ark-accept", JSON.stringify(out)); } catch {}
    document.title = `验收 ${rows.length - fails}/${rows.length}`;
    if (!q.has("quiet")) {
      const box = document.createElement("pre");
      box.style.cssText = "position:fixed;left:8px;top:60px;z-index:99;max-height:70vh;overflow:auto;background:rgba(0,0,0,.82);color:#fff;font:11px/1.35 -apple-system,monospace;padding:8px;border-radius:8px;margin:0;white-space:pre";
      box.textContent = `${out.viewport}${out.standalone ? " 主屏幕" : " Safari"}${out.dark ? " 深色" : ""}  ${rows.length - fails}/${rows.length}\n` +
        rows.map((r) => `${r.ok ? "✓" : "✗"} ${r.item}  ${r.got}${r.ok ? "" : "（要 " + r.expect + "）"}`).join("\n");
      document.body.appendChild(box);
    }
  }
  /* The page renders after its first snapshot and the number tiles after the game
     APIs answer: measure once the tiles exist (or after 8 s). */
  let tries = 0;
  const t = setInterval(() => { tries++; if (document.querySelector(".num") || tries > 80) { clearInterval(t); run(); } }, 100);
})();
