/* accept-toast.js — G8 (2号): the toast (#toast) against the native HUD it maps to, UIAccessibilityHUDView (NATIVE-GAP G8;
   remote-ref/tools/uiprobe/uiprobe-subtree-g8-hud-light.json): centred on the screen (centre (220, 478) of 440×956), the inner UIVisualEffectView
   cornerRadius 17, no shadow; the material = its backdrop chain (luminanceCurveMap → colorSaturate → colorBrightness → gaussianBlur, toast-glass.js
   with the formula sources). Runs in both themes (dark: true): the chain's values differ per theme. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptToast(ctx) {
    const { check } = ctx;
    const tt = document.getElementById("toast");
    if (!tt) { check("轻提示外形：页面上没有 #toast", "有", "无", false); return; }
    const was = tt.classList.contains("show"); tt.style.transition = "none"; tt.classList.add("show");
    const r = tt.getBoundingClientRect(), cs = getComputedStyle(tt), dy = (r.top + r.bottom) / 2 - innerHeight / 2, rad = cs.borderTopLeftRadius, sh = cs.boxShadow;
    if (!was) tt.classList.remove("show"); void tt.offsetWidth; tt.style.transition = "";
    check("轻提示外形 = 原生 HUD：屏幕正中、圆角 17、无阴影（uiprobe-subtree-g8-hud-light.json，NATIVE-GAP G8）", "中线差 0 · 17px · none", `中线差 ${dy.toFixed(1)} · ${rad} · ${sh}`,
      Math.abs(dy) < 0.6 && rad === "17px" && sh === "none");
    const G = window.ToastGlass; if (!G) { check("轻提示材质：toast-glass.js 未加载", "已加载", "无", false); return; }
    /* show it the way view.js toast() does (textContent, then .show, one task): the glass must be in place when the task ends — before the frame paints */
    const keep = tt.textContent, wasShow = tt.classList.contains("show"); tt.style.transition = "none"; tt.textContent = "验收"; tt.classList.add("show"); await Promise.resolve();
    try {
      const th = G.theme(), m = G.MAT[th], lay = tt.firstElementChild, copy = lay && lay.querySelector(".toast-glass-copy"), f = document.getElementById("toast-glass-f"), prims = f ? [...f.children] : [];
      check(`轻提示材质 层在：显示同一任务内 .toast-glass 为首个子、#app 静态复本带 url(#toast-glass-f)、面板本身无底色无背景滤镜（${th === "dark" ? "暗" : "亮"}）`, "层 · url · none · none",
        `${lay && lay.classList.contains("toast-glass") ? "层" : "无层"} · ${copy ? copy.style.filter : "-"} · ${getComputedStyle(tt).backgroundImage} · ${getComputedStyle(tt).webkitBackdropFilter || getComputedStyle(tt).backdropFilter || "none"}`,
        !!lay && lay.classList.contains("toast-glass") && !!copy && copy.style.filter === 'url("#toast-glass-f")' && getComputedStyle(tt).backgroundColor === "rgba(0, 0, 0, 0)" && (getComputedStyle(tt).webkitBackdropFilter || getComputedStyle(tt).backdropFilter || "none") === "none");
      const y = G.curve(m), tab = prims[1] && prims[1].querySelector("feFuncG"), tv = tab ? tab.getAttribute("tableValues").split(" ").map(Number) : [], row = prims[3] ? prims[3].getAttribute("values").trim().split(/\s+/).map(Number) : [];
      const s = m.saturate, wantRow = [0.2126 + 0.7874 * s, 0.7152 * (1 - s), 0.0722 * (1 - s), 0, m.brightness];
      const order = prims.map((e) => e.tagName.replace(/^fe/, "")).join("→");
      check(`轻提示材质 链（HUD 背景层 ${th === "dark" ? "暗" : "亮"}：亮度曲线 ${m.amount} (${m.values.join(", ")}) → 饱和 ${s}${m.brightness ? " + 亮度 " + m.brightness : ""} → 高斯 ${m.radius} → 边归一）：曲线表 L 0 / .2 / 1、混合比、饱和矩阵首行、σ`,
        `ColorMatrix→ComponentTransfer→Composite→ColorMatrix→GaussianBlur→ComponentTransfer · ${[0, 0.2, 1].map((L) => y(L).toFixed(4)).join(" / ")} · ${(1 - m.amount).toFixed(2)}/${m.amount} · ${wantRow.map((v) => +v.toFixed(4)).join(" ")} · ${m.radius} × ${G.K}`,
        `${order} · ${tv.length === 256 ? [0, 51, 255].map((i) => tv[i].toFixed(4)).join(" / ") : "表长 " + tv.length} · ${prims[2] ? prims[2].getAttribute("k2") + "/" + prims[2].getAttribute("k3") : "-"} · ${row.slice(0, 5).join(" ")} · ${prims[4] ? prims[4].getAttribute("stdDeviation") / G.K + " × " + G.K : "-"}`,
        order === "ColorMatrix→ComponentTransfer→Composite→ColorMatrix→GaussianBlur→ComponentTransfer" && tv.length === 256 && Math.abs(tv[0] - y(0)) < 1e-5 && Math.abs(tv[255] - y(1)) < 1e-5 && Math.abs(tv[51] - y(0.2)) < 1e-5
          && Math.abs(+prims[2].getAttribute("k3") - m.amount) < 1e-9 && wantRow.every((v, i) => Math.abs(row[i] - v) < 1e-5) && Math.abs(+prims[4].getAttribute("stdDeviation") - m.radius * G.K) < 1e-9);
      const b = G.box, mr = document.getElementById("app").getBoundingClientRect(), M = f ? +f.dataset.margin : NaN, up = lay && lay.querySelector(".toast-glass-up"), tr = up ? (up.style.transform.match(/-?[\d.]+/g) || []).map(Number) : [], K = G.K;
      check(`轻提示材质 对位：背景层采样比例 ${K}（kvc.scale）：复本按 ${K} 排版、滤镜区 = 面板 ± 3σ（89）× ${K}、再 ×${1 / K} 放回、平移 = #app 框 − 面板框`, `(${b ? (mr.left - b.l).toFixed(1) : "-"}, ${b ? (mr.top - b.t).toFixed(1) : "-"}) ×${1 / K} · ±89`, `(${tr[0]}, ${tr[1]}) ×${tr[2]} · ±${M}`,
        !!b && Math.abs(tr[0] - (mr.left - b.l)) < 0.6 && Math.abs(tr[1] - (mr.top - b.t)) < 0.6 && tr[2] === 1 / K && M === Math.ceil(3 * m.radius) && Math.abs(+f.getAttribute("x") / K + tr[0] + M) < 0.6 && Math.abs(+f.getAttribute("width") / K - b.W - 2 * M) < 0.6
          && getComputedStyle(copy.firstElementChild).transform === `matrix(${K}, 0, 0, ${K}, 0, 0)`);
      const wc = []; for (const e of document.querySelectorAll(".toast-glass-page, .toast-glass-page *")) for (const ps of [null, "::before", "::after"]) { const v = getComputedStyle(e, ps).willChange; if (v !== "auto") wc.push((e.className || e.tagName) + (ps || "") + " " + v); }
      check("轻提示材质 副本里不合成：复本及其 ::before / ::after 的 will-change 全为 auto（合成的后代让 url() 滤镜在 iOS 上被跳过，alert-glass.css 同理）", "0 处", `${wc.length} 处${wc.length ? " · " + wc.slice(0, 3).join("、") : ""}`, wc.length === 0);
      /* the five-grey flat check (scratchpad toast-flat.py: the page emptied to a flat grey, the toast shown, its empty right part sampled in headless Chrome at dpr 3, G channel)
         against the closed chain (a flat field: the blur is the identity, the matrix rows sum to 1): the numbers are the harness's run of this build (2026-09-23 21:5x);
         g 64 reads 207 or 208 across runs (Chrome's 8-bit rounding between the six primitives). iOS 27 Safari on D, same test: 197 / 224 / 245 for g 0 / 128 / 255. */
      const greys = [255, 192, 128, 64, 0], measured = th === "dark" ? [83, 71, 64, 53, 30] : [245, 239, 225, 208, 198], pred = greys.map((g) => Math.max(0, Math.min(1, (1 - m.amount) * (g / 255) + m.amount * y(g / 255) + m.brightness)) * 255);
      const dmax = Math.max(...measured.map((v, i) => Math.abs(v - pred[i])));
      check(`轻提示材质 五灰阶平底核（${th === "dark" ? "暗" : "亮"}，闭链：${pred.map((v) => v.toFixed(1)).join(" / ")}；无头 Chrome 实测记录）`, "|Δ| ≤ 1.25/255", `${measured.join(" / ")} · |Δ|max ${dmax.toFixed(2)}`, dmax <= 1.25);
    } finally { tt.textContent = keep; if (!wasShow) tt.classList.remove("show"); void tt.offsetWidth; tt.style.transition = ""; }
  }, { dark: true });
})();
