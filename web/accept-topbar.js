/* accept-topbar.js — acceptance for the top bar's scroll behaviour (BOARD.md #4, topbar.js / topbar.css; remote-ref/nav-bar-scroll-formula.md).
   Registers through ACCEPT.add(ctx): ctx.check(item, expect, got, ok) / ctx.num(item, expect, got, tol) / ctx.col(item, [r,g,b,a], got).
   The checks scroll the page programmatically and read the CSS variables topbar.js sets and the titles' computed styles. */
window.ACCEPT && ACCEPT.add(async (ctx) => {
  const { check, num, col, sleep } = ctx;
  const T = window.Topbar, root = document.documentElement, cs = (el, ps) => getComputedStyle(el, ps || null);
  const h1 = document.querySelector("header h1"), small = document.querySelector("#topbar span");
  check("顶栏 topbar.js 接管（window.Topbar 在）", "true", String(!!T), !!T);
  /* 真机坑 (A6): the stylesheet must be in effect before anything is measured — a lost / late topbar.css?v=0 leaves index.html's rules
     (translateY 6 px title, no header shift → p ≈ 1); report which sheets are here and the resource timing of topbar.css */
  const sheet = [...document.styleSheets].find((s) => s.href && /topbar\.css/.test(s.href));
  let rules = 0; try { rules = sheet ? sheet.cssRules.length : 0; } catch (e) { rules = -1; }
  const rt = performance.getEntriesByType("resource").find((e) => /topbar\.css/.test(e.name));
  check("topbar.css 已到并生效（styleSheets 含它，规则 ≥ 4；资源计时）", "≥ 4", `${rules} 规则, ${rt ? Math.round(rt.responseEnd) + " ms, " + rt.transferSize + " B" : "无资源计时"}, 表 ${document.styleSheets.length} 张`, rules >= 4);
  if (!T || !h1 || !small) return;
  const v = (n) => parseFloat(root.style.getPropertyValue(n)) || 0;
  const y0 = window.scrollY;
  const go = async (y) => { window.scrollTo(0, y); await sleep(60); T.apply(); await sleep(260); };   // 0.2 s opacity transitions settle
  const p = T.p, B = T.B, sw = p - 0.5;   // §10b ④: the switch when the zone is fully under the bar (probe), see topbar.js apply()
  const snapWas = T.snap; T.snap = false;   // the release snap (2.8) would move the programmatic scrolls to a resting point mid-check
  num("折叠范围 p = 大标题框底 + 7.67 − 栏底（§10b ①：标题区 52 的页面等价）", p, (h1.getBoundingClientRect().bottom + window.scrollY + T.ZONE_BELOW) - document.querySelector("#topbar").getBoundingClientRect().bottom, 0.6);
  num("大标题框顶距栏底 3.67（§10b ①）", 3.67, h1.getBoundingClientRect().top + window.scrollY - document.querySelector("#topbar").getBoundingClientRect().bottom, 0.6);
  /* progress formula (2.4): c = p − s, (c − b)/(p − b), b 14 */
  num("progress(s=0) = 1（2.4）", 1, T.progressOf(0), 0.001);
  num(`progress(s = p − b = ${(p - B).toFixed(1)}) = 0（2.4：c ≤ 0 ... c = b → 0）`, 0, T.progressOf(p - B), 0.001);
  num(`progress(s = ${(p / 2).toFixed(1)}) = ((p/2) − b)/(p − b)`, (p / 2 - B) / (p - B), T.progressOf(p / 2), 0.001);
  /* rest: large title alpha 1, small 0, no edge line, no clip */
  await go(0);
  num("静止：大标题 alpha 1（§4 item 1 不淡出）", 1, parseFloat(cs(h1).opacity), 0.01);
  num("静止：小标题 alpha 0", 0, parseFloat(cs(small).opacity), 0.01);
  num("静止：栏底线 --tb-edge 0（§3 shouldHideAtTop）", 0, v("--tb-edge"), 0.001);
  num("静止：裁切 0", 0, parseFloat(root.style.getPropertyValue("--tb-clip")) || 0, 0.01);
  num("静止：拉伸 1", 1, v("--tb-stretch"), 0.0001);
  /* under the bar but before the switch: still alpha 1, clipped, edge line on */
  const s1 = Math.max(1, Math.min(sw - 6, p - B - 2));
  await go(s1);
  num(`滚 ${s1.toFixed(1)}（切换前）：大标题 alpha 仍 1`, 1, parseFloat(cs(h1).opacity), 0.01);
  num(`滚 ${s1.toFixed(1)}：小标题 alpha 仍 0`, 0, parseFloat(cs(small).opacity), 0.01);
  num(`滚 ${s1.toFixed(1)}：栏底线 --tb-edge 1`, 1, v("--tb-edge"), 0.001);
  check(`滚 ${s1.toFixed(1)}：大标题被栏底裁切（--tb-clip > 0）`, "> 0", root.style.getPropertyValue("--tb-clip"), (parseFloat(root.style.getPropertyValue("--tb-clip")) || 0) > 0);
  /* the switch: progress < 0.05 ⇔ s > 0.95 (p − b) — one side, then the other */
  await go(sw - 1);
  num(`滚 ${(sw - 1).toFixed(1)}（阈值前 1 pt）：小标题 0`, 0, parseFloat(cs(small).opacity), 0.01);
  await go(sw + 1);
  num(`滚 ${(sw + 1).toFixed(1)}（阈值后 1 pt，§10b ④ 标题区全进栏下）：小标题 1`, 1, parseFloat(cs(small).opacity), 0.01);
  num(`滚 ${(sw + 1).toFixed(1)}：大标题 0`, 0, parseFloat(cs(h1).opacity), 0.01);
  check("切换过渡 0.2 s（2.5；小标题 transition-duration）", "0.2s", cs(small).transitionDuration, /^0\.2s/.test(cs(small).transitionDuration));
  check("切换过渡 0.2 s（大标题）", "0.2s", cs(h1).transitionDuration, /^0\.2s/.test(cs(h1).transitionDuration));
  check("小标题无位移（§6 item 8：只 alpha）", "none", cs(small).transform, cs(small).transform === "none");
  /* release snap (2.8): nearest resting point by the midpoint */
  num("松手吸附 s = p/2 − 1 → 0", 0, T.snapTarget(p / 2 - 1), 0.001);
  num("松手吸附 s = p/2 + 1 → p", p, T.snapTarget(p / 2 + 1), 0.001);
  num("吸附曲线 = §2.8b 标准减速 1 − .998^ms：+100 ms 进度 .181", 1 - Math.pow(0.998, 100), T.snapProgress(100), 0.0005);
  num("吸附曲线：+500 ms 进度 .632（τ ≈ .5 s）", 1 - Math.pow(0.998, 500), T.snapProgress(500), 0.0005);
  num("吸附曲线：+2000 ms 进度 .982", 1 - Math.pow(0.998, 2000), T.snapProgress(2000), 0.0005);
  check("吸附曲线无过冲（§2.8b；探针 11 % 过冲的表是栏高动画，BAR_P 只作记录）", "≤ 1", String(Math.max(T.snapProgress(300), T.snapProgress(3000))), T.snapProgress(3000) <= 1 && T.SNAP_R === 0.998);
  /* pull-down stretch (2.7): clamp(1 + over/(dpr × screenH × .66), 1, 1.1) */
  check("拉过顶不缩放（§10b ③ 探针：大标题只随内容平移）：--tb-stretch 恒 1", "1", root.style.getPropertyValue("--tb-stretch"), root.style.getPropertyValue("--tb-stretch") === "1");
  check("大标题 transform 无缩放", "matrix(1, 0, 0, 1, 0, 0) 或 none", cs(h1).transform, cs(h1).transform === "none" || cs(h1).transform === "matrix(1, 0, 0, 1, 0, 0)");
  /* 真机坑 (A6, the applicable ones): the edge line follows the theme token; the old view.js entry is guarded off */
  const line = getComputedStyle(document.querySelector("#topbar"), "::after").backgroundColor;
  const probe = document.createElement("i"); probe.style.cssText = "position:fixed;left:-9999px;top:0;color:var(--line)"; document.body.appendChild(probe);
  check("栏底线颜色 = 令牌 --line（切主题后跟令牌）", cs(probe).color, line, line === cs(probe).color); probe.remove();
  const edgeTr = getComputedStyle(document.querySelector("#topbar"), "::after").transitionDuration, edgeFn = getComputedStyle(document.querySelector("#topbar"), "::after").transitionTimingFunction;
  check("栏底线淡入 0.517 s（§10b ②：ScrollEdgeEffectView 31 帧）", "0.517s", edgeTr, /^0\.517s/.test(edgeTr));
  check("栏底线淡入曲线 = 探针 31 采样（linear()）", "linear(0 0%, 0.008 3.3%, 0.166 6.7%, …)", edgeFn.slice(0, 44), /^linear\(0 0%, 0\.008 3\.3\d*%, 0\.166 6\.6/.test(edgeFn));
  await go(sw + 1);
  check("旧入口 view.js onScroll 已让位（--big 不再由它驱动：为空或 0）", "空/0", root.style.getPropertyValue("--big") || "空", !(parseFloat(root.style.getPropertyValue("--big")) > 0));
  T.snap = snapWas; window.scrollTo(0, y0); await sleep(60); T.apply();
  /* R3 (2号) — the scroll pocket: the layer, its keys (nav-pocket-sdfdump §1 / §2, nav-bar-scroll-formula §6b), its alpha with the scroll, the copy on the page's pixels */
  { const P = window.TopbarPocket, el = P && P.el; if (!el) { check("口袋：层存在（topbar.js R3）", "有", "缺", false); }
    else { const th = P.theme(), k = P.keys(th), f = document.getElementById("topbar-pocket-f"), rp = f && f.querySelector("feFlood"), bl = f && f.querySelector('feGaussianBlur[result="blur"]'), bf = f && f.querySelector('feGaussianBlur[result="bf"]'), dl = f && f.querySelector('feComposite[result="dl"]'), nm = f && f.querySelector('feComposite[result="c"]'), cm = f && f.querySelector("feColorMatrix");
      const er = el.getBoundingClientRect(), br = document.querySelector("#topbar").getBoundingClientRect();
      num("口袋：高 = 状态栏 + 收起栏 54（dump 440 × 116 = 62 + 54；此处 safe-area + 54）", br.bottom, er.bottom, 0.5); num("口袋：从屏顶起", 0, er.top, 0.5);
      check(`口袋 Replay 平罩 = 白 .5 亮 / 黑 .6 暗（§6b replayLight/DarkModeAlpha；dump opacity .5 / .6）（${th}）`, `${k.replay.slice(0, 3).join(",")} α ${k.replay[3]}`, rp ? `${rp.getAttribute("flood-color")} α ${rp.getAttribute("flood-opacity")}` : "无", !!rp && rp.getAttribute("flood-opacity") === String(k.replay[3]) && rp.getAttribute("flood-color") === `rgb(${k.replay[0]},${k.replay[1]},${k.replay[2]})`);
      num("口袋 模糊 σ = inputRadius 2 ÷ scale .5 = 4 pt（采样单位换算同 alert-pipeline-plan §1.3）", 4, bl ? parseFloat(bl.getAttribute("stdDeviation")) : NaN, 0.01);
      num("口袋 BlurFill bf σ = 16 ÷ .5 = 32（近似 mip）", 32, bf ? parseFloat(bf.getAttribute("stdDeviation")) : NaN, 0.01);
      check(`口袋 BlurFill darken / lighten / normal = ${k.darken} / ${k.lighten} / ${k.normal}（dump §2）`, `${k.darken} · ${k.lighten} · ${k.normal}`, dl && nm ? `${dl.getAttribute("k2")} · ${dl.getAttribute("k3")} · ${nm.getAttribute("k3")}` : "无", !!dl && !!nm && +dl.getAttribute("k2") === k.darken && +dl.getAttribute("k3") === k.lighten && +nm.getAttribute("k3") === k.normal);
      check("口袋 colorMatrix = dump 的 4 × 5（对角 1.1969 / 1.0712 / 1.232，偏置 .03）", k.matrix.slice(0, 5).join(" "), cm ? cm.getAttribute("values").split(/\s+/).slice(0, 5).join(" ") : "无", !!cm && cm.getAttribute("values").split(/\s+/).slice(0, 15).map(Number).every((v, i) => Math.abs(v - k.matrix[i]) < 1e-6));
      const hair = el.querySelector(".topbar-pocket-hair"); const hr = hair && hair.getBoundingClientRect();
      check(`口袋 发丝线 ⅓ pt 在口袋底，${th === "dark" ? "白" : "黑"} α .1`, `bottom = 口袋底 · rgba(…,0.1) · h ⅓`, hair ? `${(er.bottom - hr.bottom).toFixed(2)} · ${getComputedStyle(hair).backgroundColor} · ${hr.height.toFixed(2)}` : "无", !!hair && Math.abs(er.bottom - hr.bottom) < 0.5 && /0\.1\)$/.test(getComputedStyle(hair).backgroundColor) && Math.abs(hr.height - 1 / 3) < 0.2);
      const y1 = window.scrollY; window.scrollTo(0, 0); await sleep(700); num("口袋 静止（顶部）alpha 0（shouldHideAtTop）", 0, parseFloat(getComputedStyle(el).opacity), 0.001);
      window.scrollTo(0, 40); await sleep(700); num("口袋 滚后 alpha 1（同边线的 .517 s 淡入）", 1, parseFloat(getComputedStyle(el).opacity), 0.001);
      const copy = el.querySelector(".topbar-pocket-copy"), mr = document.getElementById("app").getBoundingClientRect(), tm = /matrix\(([^)]+)\)/.exec(getComputedStyle(copy).transform), ty = tm ? parseFloat(tm[1].split(",")[5]) : NaN;
      num("口袋 内容复本贴着页面像素（translateY = 页 top）", mr.top, ty, 1.5);
      check("口袋 遮罩：1 × 384 竖向遮罩的像素值未读（imgdump）→ 先全幅模糊，记录不判", "记录", "记录", true);
      window.scrollTo(0, y1); await sleep(60); } }
});
