/* accept-alert.js — acceptance of the alert panel's glass (BOARD R57; alert-glass.js). Registered through ACCEPT.add; runs in accept.js's page.
   Rows: the keys in the code = the dump (uiprobe-deep-alert-glasskeys.json, light); the layer exists while the dialog is open (light) and the pane's
   sampled substitute is off; the filter's numbers = the formulas (level σ = std ÷ .25, the face matrix from white 1.03 / black .4, the maps' scale, the
   highlight's vibrant matrix = the dump); the dark theme keeps the substitute (keys unread, recorded); the layer is stripped on close. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptAlert(ctx) {
    const { check, num, sleep } = ctx;
    if (!window.AlertGlass) { check("弹窗玻璃：AlertGlass 未装载（alert-glass.js 未到）", "AlertGlass", "缺", false); return; }
    const A = window.AlertGlass, K = A.keys;
    check("弹窗玻璃 键 = uiprobe-deep-alert-glasskeys.json（模糊 5 / .8 .4 .5 / −86 −1 0；面 1.03 / .4；内折射 −60/20 外 43/34.4 折射 .6；钳 1.0696；阴影 0 / .4 / 24 / (0,8)）", "见左", `${K.BlurRadius} · ${K.BlurOpacity0}/${K.BlurOpacity1}/${K.BlurOpacity2} · ${K.BlurDistance0}/${K.BlurDistance1}/${K.BlurDistance2} · ${K.FaceColorMatrixWhite}/${K.FaceColorMatrixBlack} · ${K.InnerRefractionAmount}/${K.InnerRefractionHeight} ${K.OuterRefractionAmount}/${K.OuterRefractionHeight} ${K.RefractionOpacity} · ${K.Clamp} · ${K.ShadowAmount}/${K.ShadowOpacity}/${K.ShadowRadius}`,
      K.BlurRadius === 5 && K.BlurOpacity0 === 0.8 && K.BlurOpacity1 === 0.4 && K.BlurOpacity2 === 0.5 && K.BlurDistance0 === -86 && K.BlurDistance1 === -1 && K.BlurDistance2 === 0 && K.FaceColorMatrixWhite === 1.03 && K.FaceColorMatrixBlack === 0.4 && K.InnerRefractionAmount === -60 && K.InnerRefractionHeight === 20 && K.OuterRefractionAmount === 43 && K.OuterRefractionHeight === 34.4 && K.RefractionOpacity === 0.6 && K.Clamp === 1.0696 && K.ShadowAmount === 0 && K.ShadowOpacity === 0.4 && K.ShadowRadius === 24);
    const th = A.theme(); const dlg = document.getElementById("alert"); if (!dlg || typeof ask !== "function") { check("弹窗玻璃：#alert / ask() 不可用", "有", "缺", false); return; }
    const p = ask("检查", "弹窗玻璃检查", "好", false); await sleep(120);
    const layer = A.layer, pane = dlg.querySelector(".pane"), cs = pane && getComputedStyle(pane), f = document.getElementById("alert-glass-f");
    if (th === "light") {
      check("弹窗玻璃（亮）：层在（#app 复本经 #alert-glass-f）、pane 的采样替代关（backdrop-filter none、背景透明）、glass-read 类", "层 · none · transparent · glass-read", `${layer ? "层" : "无"} · ${cs ? (cs.webkitBackdropFilter || cs.backdropFilter) : "-"} · ${cs ? cs.backgroundColor : "-"} · ${dlg.classList.contains("glass-read") ? "glass-read" : "-"}`, !!layer && !!cs && /none/.test(cs.webkitBackdropFilter || cs.backdropFilter || "none") && /rgba\(0, 0, 0, 0\)|transparent/.test(cs.backgroundColor) && dlg.classList.contains("glass-read"));
      const sig = f ? f.dataset.sigma.split(",").map(Number) : [NaN, NaN];
      check("弹窗玻璃 模糊：两级金字塔 σ = 级 std ÷ 捕获比 .25（2.147 / 4.694 → 8.588 / 18.776 pt；实测阶跃 σ 19.5）、权图 / 折射两图 / 高光两图在", "8.588 / 18.776 · 6 图", `${sig.map((v) => v.toFixed(3)).join(" / ")} · ${f ? f.querySelectorAll("feImage").length : 0} 图`, Math.abs(sig[0] - 2.147 / 0.25) < 0.002 && Math.abs(sig[1] - 4.694 / 0.25) < 0.002 && !!f && f.querySelectorAll("feImage").length === 5);
      const dm = f ? [...f.querySelectorAll("feDisplacementMap")] : [];
      check("弹窗玻璃 折射：内 −60/20、外 43/34.4 两张位移图（feDisplacementMap scale = 图的 S）、按 .6·sat((d+11)/8) 混", "2 · scale 128", `${dm.length} · scale ${dm.map((e) => e.getAttribute("scale")).join("/")}`, dm.length === 2 && dm.every((e) => +e.getAttribute("scale") === A.images(dlg.offsetWidth, dlg.offsetHeight).S));
      const fm = f && f.querySelector('feColorMatrix[result="face"]'); const want = A.faceMatrix().split(/\s+/).map(Number), got = fm ? fm.getAttribute("values").split(/\s+/).map(Number) : [];
      check("弹窗玻璃 面矩阵 = YCC⁻¹·diag(1.03 − .4, 1, 1 | .4)·YCC（set_ycc_composite）", want.slice(0, 5).map((v) => v.toFixed(4)).join(" "), got.slice(0, 5).map((v) => v.toFixed(4)).join(" "), got.length === 20 && got.every((v, i) => Math.abs(v - want[i]) < 1e-5));
      const vb = f && f.querySelector('feColorMatrix[result="vib"]'); const vv = vb ? vb.getAttribute("values").split(/\s+/).map(Number) : [];
      check("弹窗玻璃 高光层：vibrantColorMatrix = dump 4×5（1.1202 −.1894 −.019 | .1471 …）两段带（主 1 pt + 漫 8 pt，spread 1.5344）", "1.1202 -0.1894 -0.019 0 0.1471", vv.slice(0, 5).join(" "), vv.length === 20 && Math.abs(vv[0] - 1.1202) < 1e-4 && Math.abs(vv[4] - 0.1471) < 1e-4 && !!f && !!f.querySelector('feImage[data-alert-img="hl2"]'));
      const sh = cs && cs.filter; check("弹窗玻璃 软影：drop-shadow 0 8 24 α .12（.3 × ShadowOpacity .4，§7.3 剖面近似）", "0px 8px 24px rgba(0, 0, 0, 0.12)", sh, !!sh && /drop-shadow\(rgba\(0, 0, 0, 0\.12\) 0px 8px 24px\)/.test(sh));
      const im = f && f.querySelector('feImage[data-alert-img="wimg"]'); const fr = f && { x: +f.getAttribute("x"), y: +f.getAttribute("y") }; const dr = dlg.getBoundingClientRect(), mr = document.getElementById("app").getBoundingClientRect();
      const px = dr.left + dr.width / 2 - dlg.offsetWidth / 2 - mr.left, py = dr.top + dr.height / 2 - dlg.offsetHeight / 2 - mr.top;
      check("弹窗玻璃 对位：图与滤镜区落在面板框（复本坐标 = 弹窗框 − #app 框）", `img (${px.toFixed(1)}, ${py.toFixed(1)}) · region −60.2`, `img (${im ? im.getAttribute("x") : "-"}, ${im ? im.getAttribute("y") : "-"}) · region ${fr ? (fr.x - px).toFixed(1) : "-"}`, !!im && Math.abs(+im.getAttribute("x") - px) < 0.6 && Math.abs(+im.getAttribute("y") - py) < 0.6 && !!fr && Math.abs(fr.x - px + 60.2) < 0.6);
      check("弹窗玻璃 不可表达 / 未读记录：Bleed（400/500/.2 的 clamp-to-edge 取样）、钳 no-op、着色器内 KeyFill 高 0、环影 stroke 0、d′、椭圆化、暗色 26 键、面板内部抬亮项（白底 231 vs 实测 238）", "8 项", `${Object.keys(A.unbuilt).length} 项`, Object.keys(A.unbuilt).length === 8);
    } else {
      await sleep(600);   // the substitute's backdrop-filter arrives with .settled after the appear animation (the Chrome path in index.html)
      const bfd = cs ? (cs.webkitBackdropFilter || cs.backdropFilter) : "-";
      check("弹窗玻璃（暗）：26 键未读 → 采样替代 --ios-alert-glass-filter 照旧（记录，待读）", "无层 · backdrop-filter 在", `${layer ? "层" : "无层"} · ${bfd}`, !layer && !!cs && !/none/.test(bfd || "none"));
    }
    document.getElementById("alert-cancel").click(); await p; await sleep(500);
    check("弹窗玻璃：关掉后层撤", "无", A.layer ? "层" : "无", !A.layer);
  });
})();
