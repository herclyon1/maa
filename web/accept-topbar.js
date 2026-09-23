/* accept-topbar.js — acceptance for the top bar's scroll behaviour (BOARD.md #4, topbar.js / topbar.css; remote-ref/nav-bar-scroll-formula.md).
   Registers through ACCEPT.add(ctx): ctx.check(item, expect, got, ok) / ctx.num(item, expect, got, tol) / ctx.col(item, [r,g,b,a], got).
   The checks scroll the page programmatically and read the CSS variables topbar.js sets and the titles' computed styles. */
/* S4 (BOARD/S4-tags.md): file-level tags — timing (scrolls + transitions), dark:true only for the 栏底线 = --line token row (the rest is geometry / curves) */
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
  /* S1 (SPEED2): no fixed sleeps — after a programmatic scroll + apply(), wait for the driver's own CSS transitions (h1 / small title 0.2 s,
     #topbar::after 0.517 s) to finish via the Web Animations API; nothing pending = continue at once (max 800 ms guard) */
  const frame = () => new Promise(requestAnimationFrame);
  const settle = async (els, maxMs = 800) => { await frame(); const anims = els.flatMap((el) => el ? el.getAnimations({ subtree: true }) : []); if (!anims.length) return; await Promise.race([Promise.all(anims.map((a) => a.finished.catch(() => {}))), sleep(maxMs)]); };
  const go = async (y) => { window.scrollTo(0, y); await frame(); T.apply(); await settle([h1, small, document.querySelector("#topbar")]); };
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
  /* A15/A16: judge against the driver's CURRENT p (T.p is re-measured whenever apply() runs at scrollY 0 — the go(0) above — and a
     first dark run measured 51.89 there vs 52.406 at the start of this check: a font / layout settle, not the snap curve); the drift is
     reported as its own row so a real page change still shows */
  const pNow = T.p;
  num("吸附行读的 p = 检查开头的 p（apply() 在顶部重量；漂移 ≤ 1 pt = 字体 / 版式落定，非曲线）", p, pNow, 1);
  num("松手吸附 s = p/2 − 1 → 0", 0, T.snapTarget(pNow / 2 - 1), 0.001);
  num("松手吸附 s = p/2 + 1 → p（驱动器当前 p）", pNow, T.snapTarget(pNow / 2 + 1), 0.001);
  num("吸附曲线 = §2.8b 标准减速 1 − .998^ms：+100 ms 进度 .181", 1 - Math.pow(0.998, 100), T.snapProgress(100), 0.0005);
  num("吸附曲线：+500 ms 进度 .632（τ ≈ .5 s）", 1 - Math.pow(0.998, 500), T.snapProgress(500), 0.0005);
  num("吸附曲线：+2000 ms 进度 .982", 1 - Math.pow(0.998, 2000), T.snapProgress(2000), 0.0005);
  check("吸附曲线无过冲（§2.8b；探针 11 % 过冲的表 = 带速松手越过顶边的回弹，不是栏高动画：G16 数据核 §2.8c，BAR_P 只作记录）", "≤ 1", String(Math.max(T.snapProgress(300), T.snapProgress(3000))), T.snapProgress(3000) <= 1 && T.SNAP_R === 0.998);
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
  T.snap = snapWas; window.scrollTo(0, y0); await frame(); T.apply();
  /* R3 (2号) — the scroll pocket: the layer, its keys (nav-pocket-sdfdump §1 / §2, nav-bar-scroll-formula §6b), its alpha with the scroll, the copy on the page's pixels */
  { const P = window.TopbarPocket, el = P && P.el; if (!el) { check("口袋：层存在（topbar.js R3）", "有", "缺", false); }
    else { const th = P.theme(), k = P.keys(th), f = document.getElementById("topbar-pocket-f"), rp = f && f.querySelector("feFlood"), bf = f && f.querySelector('feGaussianBlur[result="bf"]'), dl = f && f.querySelector('feComposite[result="dl"]'), nm = f && f.querySelector('feComposite[result="c"]'), cm = f && f.querySelector('feColorMatrix[result="cm"]');
      const er = el.getBoundingClientRect(), br = document.querySelector("#topbar").getBoundingClientRect();
      num("口袋：高 = 状态栏 + 收起栏 54（dump 440 × 116 = 62 + 54；此处 safe-area + 54）", br.bottom, er.bottom, 0.5); num("口袋：从屏顶起", 0, er.top, 0.5);
      check(`口袋 Replay 平罩 = 白 .5 亮 / 黑 .6 暗（§6b replayLight/DarkModeAlpha；dump opacity .5 / .6）（${th}）`, `${k.replay.slice(0, 3).join(",")} α ${k.replay[3]}`, rp ? `${rp.getAttribute("flood-color")} α ${rp.getAttribute("flood-opacity")}` : "无", !!rp && rp.getAttribute("flood-opacity") === String(k.replay[3]) && rp.getAttribute("flood-color") === `rgb(${k.replay[0]},${k.replay[1]},${k.replay[2]})`);
      /* R3″ (nav-bar-scroll-formula §3.4b, the read shaders): the blur is the pyramid level L(y) = log2(1.6·2·base·mask.R(y)) (r ≥ 2; log2(1 + r/2) below), mixed
         per row from three Gaussian levels (σ_k = the level's std ÷ base, base = dpr × .5 px/pt) + the source, weights from a 1 × 384 image; BlurFill = the
         level mix's std at L_fill = log2(1.6·16·base) */
      { const V = P.vb, base = V.base(), b = [1, 2, 3].map((lv) => f && f.querySelector(`feGaussianBlur[result="b${lv}"]`)), sig = b.map((e) => (e ? parseFloat(e.getAttribute("stdDeviation")) : NaN)), want = [1, 2, 3].map((lv) => V.std[lv] / base);
        check(`口袋 模糊（R3″）：三级金字塔 σ = 各级核 std ÷ base（base = dpr ${window.devicePixelRatio} × .5 = ${base} px/pt；std 2.147 / 4.694 / 9.581）`, want.map((v) => v.toFixed(3)).join(" / "), sig.map((v) => v.toFixed(3)).join(" / "), sig.every((v, i) => Math.abs(v - want[i]) < 0.002));
        const Lfill = V.level(V.k * V.fill * base), bfw = V.mixStd(Lfill) / base;
        num(`口袋 BlurFill bf σ = 层级混合 std(L_fill ${Lfill.toFixed(3)}) ÷ base（r = 1.6 × 16 × base）`, bfw, bf ? parseFloat(bf.getAttribute("stdDeviation")) : NaN, 0.01);
        const im = f && f.querySelector("feImage"), w = f && f.querySelector('feColorMatrix[result="w3"]'), p0 = f && f.querySelector('feBlend[result="p0"]'), sum = f && f.querySelector('feComposite[result="blur"]');
        const row = (i) => { const L = V.level(V.k * V.radius * base * V.maskR(i)); return [0, 1, 2, 3].map((kk) => Math.max(0, 1 - Math.abs(L - kk))); };
        const r204 = row(204), r383 = row(383);
        check("口袋 模糊（R3″）：逐行权重图（feImage 1 × 384 data:png，R/G/B = 级 0/1/2 权，级 3 = 1 − 和）× 四级 multiply 后相加；行 204 = 全强、行 383 = 遮罩 .247", `img · w3 · p0 · sum · 204 [${r204.map((v) => v.toFixed(2)).join(",")}] · 383 [${r383.map((v) => v.toFixed(2)).join(",")}]`, `${im ? "img" : "-"} · ${w ? "w3" : "-"} · ${p0 ? "p0" : "-"} · ${sum ? "sum" : "-"} · L204 ${V.level(V.k * V.radius * base * V.maskR(204)).toFixed(3)} · L383 ${V.level(V.k * V.radius * base * V.maskR(383)).toFixed(3)}`, !!im && !!w && !!p0 && !!sum && (im.getAttribute("href") || "").startsWith("data:image/png") && Math.abs(r204.reduce((a, c) => a + c, 0) - 1) < 1e-6 && Math.abs(r383.reduce((a, c) => a + c, 0) - 1) < 1e-6 && V.maskR(204) === 1 && Math.abs(V.maskR(383) - 63 / 255) < 1e-6);
        const fr = f && { x: +f.getAttribute("x"), y: +f.getAttribute("y"), w: +f.getAttribute("width"), h: +f.getAttribute("height") }, imy = im ? +im.getAttribute("y") : NaN, imh = im ? +im.getAttribute("height") : NaN;
        check("口袋 模糊（R3″）：滤镜区与权重图跟着口袋走（复本坐标 y = scrollY − top0，高 = 口袋高）", `img y = scrollY − top0 = ${(window.scrollY - P.top0).toFixed(1)} · h ${el.offsetHeight}`, `img y ${imy} h ${imh} · region ${fr ? `${fr.y}…${fr.y + fr.h}` : "-"}`, !!fr && imh === el.offsetHeight && Math.abs(imy - (window.scrollY - P.top0)) < 0.01 && fr.y <= imy && fr.y + fr.h >= imy + imh);
        check("口袋 模糊（R3″）：inputFade = 1 的淡出项 saturate((r − .02)/.08) 对本遮罩每行 = 1（最小 r = 1.6·2·base·.247 ≥ .1）→ 不缩 alpha", "≥ .1", `min r ${(V.k * V.radius * base * 63 / 255).toFixed(3)}`, V.k * V.radius * base * 63 / 255 >= 0.1);
        /* R3⁗ (R50, nav-bar-scroll-formula §6c): the mask is sampled through (T·diag(bounds w, h))⁻¹ — stretched over the layer's full height, row i at
           y = (i + ½)/384 × H; the weights image here is 384 rows over the pocket's height, so its row centres land there by construction */
        { const H = el.offsetHeight, y204 = H * 204.5 / 384, y383 = H * 383.5 / 384, wimg = f && f.querySelector("feImage");
          const ih = wimg ? +wimg.getAttribute("height") : NaN, ph = wimg ? /height=(\d+)/.exec(wimg.getAttribute("href") || "") : null;
          check("口袋 遮罩（R3⁗ / R50 §6c）：1 × 384 表拉到层全高（uv = (T·diag(w,h))⁻¹·p）——权图高 = 口袋高 H，行 204 / 383 落在 H × 204.5/384 / H × 383.5/384", `img h ${H} · y204 ${y204.toFixed(2)} · y383 ${y383.toFixed(2)} · 384 行`, `img h ${ih} · y204 ${(ih * 204.5 / 384).toFixed(2)} · y383 ${(ih * 383.5 / 384).toFixed(2)} · ${V.maskRows} 行`, ih === H && V.maskRows === 384 && Math.abs(ih * 204.5 / 384 - y204) < 1e-6); }
        check("口袋 模糊（R3‴）：每级核 = 同 std 高斯代 13 抽头金字塔核，剖面近似——偏差 ≤ 1.4/255（边）/ 1.0/255（线），精确核逐帧 ≈ 2.1 G 乘加不可用（§3.4b、tools/vb_gauss_dev.py）：记录", "记录", "记录", true); }
      check(`口袋 BlurFill darken / lighten / normal = ${k.darken} / ${k.lighten} / ${k.normal}（dump §2）`, `${k.darken} · ${k.lighten} · ${k.normal}`, dl && nm ? `${dl.getAttribute("k2")} · ${dl.getAttribute("k3")} · ${nm.getAttribute("k3")}` : "无", !!dl && !!nm && +dl.getAttribute("k2") === k.darken && +dl.getAttribute("k3") === k.lighten && +nm.getAttribute("k3") === k.normal);
      check("口袋 colorMatrix = dump 的 4 × 5（对角 1.1969 / 1.0712 / 1.232，偏置 .03）", k.matrix.slice(0, 5).join(" "), cm ? cm.getAttribute("values").split(/\s+/).slice(0, 5).join(" ") : "无", !!cm && cm.getAttribute("values").split(/\s+/).slice(0, 15).map(Number).every((v, i) => Math.abs(v - k.matrix[i]) < 1e-6));
      const hair = el.querySelector(".topbar-pocket-hair"); const hr = hair && hair.getBoundingClientRect();
      check(`口袋 发丝线 ⅓ pt 在口袋底，${th === "dark" ? "白" : "黑"} α .1`, `bottom = 口袋底 · rgba(…,0.1) · h ⅓`, hair ? `${(er.bottom - hr.bottom).toFixed(2)} · ${getComputedStyle(hair).backgroundColor} · ${hr.height.toFixed(2)}` : "无", !!hair && Math.abs(er.bottom - hr.bottom) < 0.5 && /0\.1\)$/.test(getComputedStyle(hair).backgroundColor) && Math.abs(hr.height - 1 / 3) < 0.2);
      const y1 = window.scrollY; window.scrollTo(0, 0); await frame(); T.apply(); await settle([el]); num("口袋 静止（顶部）alpha 0（shouldHideAtTop）", 0, parseFloat(getComputedStyle(el).opacity), 0.001);
      window.scrollTo(0, 40); await frame(); T.apply(); await settle([el]); num("口袋 滚后 alpha 1（同边线的 .517 s 淡入）", 1, parseFloat(getComputedStyle(el).opacity), 0.001);
      const copy = el.querySelector(".topbar-pocket-copy"), mr = document.getElementById("app").getBoundingClientRect(), tm = /matrix\(([^)]+)\)/.exec(getComputedStyle(copy).transform), ty = tm ? parseFloat(tm[1].split(",")[5]) : NaN;
      num("口袋 内容复本贴着页面像素（translateY = 页 top）", mr.top, ty, 1.5);
      { const bg = getComputedStyle(el).backgroundColor, rpk = k.replay; const bm = /rgba?\(([\d.]+), ([\d.]+), ([\d.]+)(?:, ([\d.]+))?\)/.exec(bg);
        check("口袋 Replay 平罩在模糊层之下（口袋自身背景 = replay 键；R3′）", `rgba(${rpk.join(",")})`, bg, !!bm && +bm[1] === rpk[0] && +bm[2] === rpk[1] && +bm[3] === rpk[2] && Math.abs((bm[4] == null ? 1 : +bm[4]) - rpk[3]) < 0.01);
        check("口袋 遮罩：R3′ 的 alpha 遮罩已撤（复本无 mask-image；R3″ 按式改为逐行模糊级）", "无", getComputedStyle(copy).webkitMaskImage || getComputedStyle(copy).maskImage || "none", /^none$/.test(getComputedStyle(copy).webkitMaskImage || getComputedStyle(copy).maskImage || "none")); }
      window.scrollTo(0, y1); await frame(); } }
  /* I3 (acceptance 09-23 08:54): after a field focus / the keyboard the page never rests with the large title part-way under the bar. view.js target(h, base):
     scrollRectToVisible (the least scroll that shows the field, none when it shows) from the scroll at focus, then 2.8's resting point that keeps it shown */
  /* 顶栏红 (老网页 09-23, simulator A): the first matching field was often inside a hidden section (#efuntil, rect 0 × 0) — focus() fails, __kbdTarget
     returns null for every K and the row passed with nothing judged; and K 120 under a 62-pt safe area leaves no room at all (bar bottom 116 + 8 >
     120 − 8): no scroll can show a field there, so it is not a case, not a violation. Now: the first visible page field plus two probe fields (the top
     and the end of #app) are judged; a K whose band (K − 8) − (bar bottom + 8) is shorter than the field is listed as unreachable; judging nothing fails. */
  if (typeof window.__kbdTarget === "function") {
    const app = document.getElementById("app"), y2 = window.scrollY, rows = [], skip = new Set(); let bad = 0, judged = 0;
    const mk = (where) => { const e = document.createElement("input"); e.type = "text"; e.inputMode = "numeric"; e.dataset.acceptProbe = "i3"; e.style.cssText = "display:block;width:120px;height:44px;margin:8px 16px"; where === "top" ? app.prepend(e) : app.append(e); return e; };
    const real = [...app.querySelectorAll('input[type="text"], input[data-time], input[inputmode]')].find((e) => e.getClientRects().length && e.getBoundingClientRect().height > 0);
    const probes = [mk("top"), mk("end")], fields = (real ? [real] : []).concat(probes);
    for (const fi of fields) { fi.focus({ preventScroll: true }); if (document.activeElement !== fi) { rows.push(`${fi.dataset.acceptProbe ? "探" : "页"}字段聚焦失败`); bad++; continue; }
      for (const K of [120, 200, 260, 320, 400, 520, innerHeight]) for (const b of [0, 10, 30, p - 5]) {
        window.scrollTo(0, b); await sleep(20); const lo = document.querySelector("#topbar").getBoundingClientRect().height + 8, fh = fi.getBoundingClientRect().height;
        if (K - 8 - lo < fh) { skip.add(K); continue; }
        const t = window.__kbdTarget(K, b); if (t == null) continue; judged++;
        const r = fi.getBoundingClientRect(), a = r.top - (t - window.scrollY), z = r.bottom - (t - window.scrollY);
        const mid = t > 0.5 && t < p - 0.5, hid = a < lo - 0.5 || z > K - 8 + 0.5; if (mid || hid) { bad++; if (rows.length < 4) rows.push(`${fi.dataset.acceptProbe ? "探" : "页"}K${K}/b${Math.round(b)}→${t.toFixed(1)}${mid ? " 半截" : ""}${hid ? " 字段看不见" : ""}`); } }
      fi.blur(); }
    probes.forEach((e) => e.remove()); window.scrollTo(0, y2); await sleep(60);
    check(`I3 键盘 / 聚焦后停点：大标题不停在半截（0 或 ≥ p），字段在栏底与键盘之间（scrollRectToVisible 最少滚动 + 2.8 停点）；判 ${judged} 处（${real ? "页字段 + " : ""}探针字段 2）${skip.size ? `，K ${[...skip].join(" / ")} 带宽容不下字段不判` : ""}`, "0 处违例 · 判 > 0", bad ? rows.join(" · ") : `0 处违例 · 判 ${judged}`, bad === 0 && judged > 0);
    const fi = real || null; if (fi) { window.scrollTo(0, 0); await sleep(20); fi.focus({ preventScroll: true }); const b0 = document.activeElement === fi && fi.getBoundingClientRect().bottom < innerHeight - 8 && fi.getBoundingClientRect().top > document.querySelector("#topbar").getBoundingClientRect().height + 8 ? window.__kbdTarget(innerHeight, 0) : 0; fi.blur(); window.scrollTo(0, y2); await sleep(60);
      check("I3 字段本来就看得见：不滚（scrollRectToVisible「already visible → does nothing」）", "0", String(b0), b0 === 0 || b0 == null); } }
});
