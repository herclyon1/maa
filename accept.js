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
    /* A header right after a footer gets 4 (the footer's 24 is the gap); measure a plain one. */
    const h2 = [...document.querySelectorAll("section h2")].find((h) => { const prev = h.parentElement.previousElementSibling; return !(prev && prev.lastElementChild && prev.lastElementChild.classList.contains("foot")); });
    if (h2) {
      const c = cs(h2);
      num("段头字号", 17, px(c.fontSize), 0.05); check("段头字重 600", 600, c.fontWeight, String(c.fontWeight) === "600");
      num("段头上边距", 28, px(c.paddingTop)); num("段头下边距", 6, px(c.paddingBottom));
      num("段头文字内缩", 20, px(c.paddingLeft));
    }
    /* The footer under the number tiles sits 8 below them (tiles have no card edge); measure a plain one. */
    const foot = [...document.querySelectorAll("section .foot")].find((f) => !(f.previousElementSibling && f.previousElementSibling.classList.contains("nums")));
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
    /* State colours, probed on synthetic controls so they are checked whatever the
       data happens to show: a switch on/off, the danger tile title, the selected
       tab, the edit bar's two capsules. 2026-09-15 the green track rule vanished
       and nobody noticed until the phone showed grey everywhere. */
    const lab = document.createElement("div"); lab.style.cssText = "position:fixed;left:-9999px;top:0";
    lab.innerHTML = `<label class="sw"><input type="checkbox" checked><span></span></label><label class="sw"><input type="checkbox"><span></span></label>` +
      `<button class="tile danger"><span class="ttitle">x</span></button><nav class="tabs"><div class="seg"><button class="on">x</button></div></nav>` +
      `<div class="topbar editing"><button class="navbtn" id="_d">x</button><button class="navbtn" id="_s">x</button></div>`;
    document.body.appendChild(lab);
    const rgb = (c) => { const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)/.exec(c || ""); return m ? m.slice(1, 4).map(Number) : null; };
    const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
    const same = (c, h, tol = 3) => { const a = rgb(c), b = hex(h); return !!a && a.every((v, i) => Math.abs(v - b[i]) <= tol); };
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    const okC = dark ? "#30d158" : "#34c759", tintC = dark ? "#0a84ff" : "#0088ff", badC = dark ? "#ff453a" : "#ff383c";
    const [on, off] = lab.querySelectorAll(".sw span");
    check("开关开 = 系统绿", okC, cs(on).backgroundColor, same(cs(on).backgroundColor, okC));
    check("开关关 = 灰", "rgba(60,60,67,.3)", cs(off).backgroundColor, /60,\s*60,\s*67/.test(cs(off).backgroundColor));
    const kx = /matrix\([^)]*,\s*([-\d.]+),\s*[-\d.]+\)$/.exec(cs(on, "::after").transform);
    num("开关开：圆钮位移 21", 21, kx ? parseFloat(kx[1]) : NaN);
    /* Finger down: the kit's Pressed knob is 58×38 (scale 1.526 × 1.583 of 38×24). */
    const held = lab.querySelectorAll(".sw")[1]; held.classList.add("hold");
    const hm = /matrix\(([-\d.]+),\s*[-\d.]+,\s*[-\d.]+,\s*([-\d.]+)/.exec(cs(held.querySelector("span"), "::after").transform);
    num("按住：圆钮放大成 58 宽", 1.526, hm ? parseFloat(hm[1]) : NaN, 0.02); num("按住：圆钮放大成 38 高", 1.583, hm ? parseFloat(hm[2]) : NaN, 0.02);
    check("按住：圆钮变半透明玻璃", "非纯白", cs(held.querySelector("span"), "::after").backgroundImage.slice(0, 15), /gradient/.test(cs(held.querySelector("span"), "::after").backgroundImage));
    held.classList.remove("hold");
    check("停止一切标题 = 红", badC, cs(lab.querySelector(".ttitle")).color, same(cs(lab.querySelector(".ttitle")).color, badC));
    check("选中的标签 = tint", tintC, cs(lab.querySelector("nav.tabs button.on")).color, same(cs(lab.querySelector("nav.tabs button.on")).color, tintC));
    lab.querySelector("#_d").id = "discard"; lab.querySelector("#_s").id = "save";
    check("编辑栏 ✓ = tint 底白符号", tintC, cs(lab.querySelector("#save")).backgroundColor, same(cs(lab.querySelector("#save")).backgroundColor, tintC) && same(cs(lab.querySelector("#save")).color, "#ffffff"));
    num("编辑栏圆钮 44", 44, lab.querySelector("#save").getBoundingClientRect().height); num("编辑栏圆钮宽 44", 44, lab.querySelector("#save").getBoundingClientRect().width);
    num("编辑栏圆钮距边 20", 20, px(cs(lab.querySelector("#discard")).left));
    check("编辑栏圆钮是圆的", "50%", cs(lab.querySelector("#save")).borderRadius, cs(lab.querySelector("#save")).borderRadius === "50%" || px(cs(lab.querySelector("#save")).borderRadius) >= 22);
    lab.remove();
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
