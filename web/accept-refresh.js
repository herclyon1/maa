/* accept-refresh.js — acceptance of the pull-to-refresh control (BOARD.md #8, night batch). Registered through ACCEPT.add; runs in accept.js's
   page (light and dark). Every expected number is the decompiled value of remote-ref/refresh-native-formula.md §2 recomputed here:
   ① threshold: Refresh.maxSnap() = 112.5 × max(H, 372) / 568 with H = the visual viewport's height (no title) — and not the old page's 72;
   ② reveal: at pull = maxSnap / 2 (show .5) the 8 arms' opacities are clamp(1 + i·(show − 1), 0, 1) × show = .5 / .25 / 0 / 0 …, state 1;
   ③ trigger with the finger still down at pull = maxSnap (f ≥ 1, isTracking): state 3 at once, no release needed; k = clamp(|v| × 48.333, 5, 150)
      (v 800 pt/s → 150), the rotation follows the ζ 1 / ω √150 = 12.25 spring to 3.1316 rad = 179.43° (closed form x(t) = target − Δ·e^(−ωt)(1 + ωt));
      sampled every frame for .8 s, rms ≤ 2°;
   ④ tick: after the spring settles the rotation advances in 45° steps every 125 ms, discrete — two reads 250 ms apart differ by 90 ± 45° and every
      read is base + n·45;
   ⑤ end: endRefreshing → state 4, the indicator's opacity reaches 0 within 0.3 s, then state 0 and rotation 0;
   ⑥ a release before f reached 1 (pull = maxSnap / 2, finger up) → state 0 and the refresh callback not called;
   ⑦ real-device template (the applicable ones): the old view.js path is off (its #ptr reference is null under the guard) so a pull cannot arm twice;
   R5′ / R39 (§11, §11a), all read off Refresh.trace / Refresh.backTrace = the driver's own frames (A15):
   ⑧ bloom: from the trigger each arm's transform carries scale 1 + .2b and 2b pt outward with b = t/.05 linear, then 1 − easeInOut((t − .05)/.15)
      ((.42,0,.58,1)); by .2 s the inline transforms are gone (the stylesheet's rotate(i·45°) alone);
   ⑨ spun α: in every frame arm i α = clamp((1 − p) + i·.08·p, 0, 1) with p = rot / 179.43 (the same spring), and after the spring settles the table
      0 / .08 / .16 / .24 / .32 / .40 / .48 / .56 — not all-1 any more;
   ⑩ inset (R68′): after the trigger the header's margin-top is still 0 while the finger is down (the browser holds the content under the finger); at
      the release body gets .ptr-inset and body > header margin-top 60px — the large title and the list go down together (§12: the refresh item
      stacks above the large-title item), the spinner sitting centred in the freed band (safe-area + 54…114);
   ⑪ scroll-back: endRefreshing with the finger up drives the margin from 60 to 0 over .3 s with progress sin²(π/2 · t/.3) — rms ≤ .5 px against that
      formula on the driver's frames — and ends at margin 0 with the class removed.
   Real-device items for the morning sweep (A23), not judged here: whether the title and list settle 60 lower at the release without a visible hop
   (the browser's bounce-back is its own). */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptRefresh(ctx) {
    const { check, num, sleep } = ctx;
    const R = window.Refresh;
    if (!R) { check("下拉刷新：Refresh 未装载（refresh.js）", "Refresh", "缺", false); return; }
    const ptr = document.getElementById("ptr"), ai = document.getElementById("ptrai"), arms = [...ai.querySelectorAll("i")], app = document.querySelector("body > header"), host = document.body;   // R68′: the inset is the header's top margin, the class on body
    const H = window.visualViewport ? window.visualViewport.height : innerHeight, want = 112.5 * Math.max(H, 372) / 568;
    const rotOf = () => { const m = /rotate\(([-\d.]+)deg\)/.exec(ai.style.transform || ""); return m ? parseFloat(m[1]) : 0; };
    let calls = 0, done; R.onRefresh = () => { calls++; return new Promise((r) => { done = r; }); };
    try {
      R.reset(); window.scrollTo(0, 0);   // the pull model needs the page at the top (an earlier row may have left it scrolled)
      /* ① */
      num("下拉刷新 ① 阈值 maxSnap = 112.5 × max(H, 372) / 568（refresh-native-formula.md §2；H = 可视视口高 " + Math.round(H) + "，不是旧页的 72）", want, R.maxSnap(), 0.01);
      check("下拉刷新 ① 旧路径已让位（view.js 的 #ptr 引用为 null，不会再 72 pt 就 arm）", "no .arm", ptr.classList.contains("arm") ? "arm!" : "no .arm", !ptr.classList.contains("arm"));
      /* ② */
      R.__drive({ pull: want / 2, v: 0, down: true }); await new Promise(requestAnimationFrame);
      const got = arms.map((a) => parseFloat(a.style.opacity)), exp = arms.map((_, i) => Math.max(0, Math.min(1, 1 + i * (0.5 - 1))) * 0.5);
      check("下拉刷新 ② 拉到 maxSnap/2（show .5）：8 臂 α = clamp(1 + i·(show − 1), 0, 1) × show = .5 / .25 / 0 … 逐根点亮（§0 instanceAlphaOffset −1 → 0）、状态 1、未触发", exp.map((v) => v.toFixed(3)).join(" ") + " · state 1 · calls 0", got.map((v) => v.toFixed(3)).join(" ") + ` · state ${R.state} · calls ${calls}`, got.every((v, i) => Math.abs(v - exp[i]) < 0.002) && R.state === 1 && calls === 0);
      /* ⑥ release before f ≥ 1 */
      R.__drive({ down: false }); await new Promise(requestAnimationFrame);
      check("下拉刷新 ⑥ 未到阈值就松手：不触发（trigger 要 f ≥ 1 且手指在），回状态 0、臂灭", "state 0 · calls 0 · arms 0", `state ${R.state} · calls ${calls} · arm0 ${arms[0].style.opacity}`, R.state === 0 && calls === 0 && parseFloat(arms[0].style.opacity) === 0);
      /* ③ trigger with the finger down */
      R.__drive({ pull: want / 2, v: 800, down: true }); await new Promise(requestAnimationFrame);
      const t0 = performance.now(); R.__drive({ pull: want, v: 800, down: true });
      const stAt = R.state, k = R.lastK, w = Math.sqrt(150), target = 179.43;
      check("下拉刷新 ③ 手指仍在、拉到 maxSnap（f ≥ 1）：立刻进刷新（状态 3，不等松手），刷新回调调用 1 次，k = clamp(|v| 800 × 48.333, 5, 150) = 150", "state 3 · calls 1 · k 150", `state ${stAt} · calls ${calls} · k ${k}`, stAt === 3 && calls === 1 && k === 150);
      const samples = []; const tEnd = performance.now() + 800;
      while (performance.now() < tEnd) { await new Promise(requestAnimationFrame); samples.push({ t: (performance.now() - t0) / 1000, r: rotOf() }); }
      const closed = (t) => target - target * Math.exp(-w * t) * (1 + w * t);   // ζ 1 from 0 with v0 0: x = T − T·e^(−ωt)(1 + ωt)
      const springS = samples.filter((s) => s.t < 0.6), rms = Math.sqrt(springS.reduce((a, s) => a + Math.pow(s.r - closed(s.t), 2), 0) / Math.max(1, springS.length));
      num("下拉刷新 ③ 转起：旋转逐帧对临界弹簧 ω = √150 = 12.25 /s、目标 3.1316 rad = 179.43°（m 1、k 150、c 5000，allowsOverdamping 默认 false → ζ 1）：前 .6 s 的 rms（°）", 0, rms, 2);
      /* ④ tick */
      await sleep(400); const rA = rotOf(); await sleep(250); const rB = rotOf();
      const stepOK = Math.abs(((rB - rA) - 90)) <= 45 + 0.01, gridOK = Math.abs(((rA - target) / 45) - Math.round((rA - target) / 45)) < 0.02 && Math.abs(((rB - target) / 45) - Math.round((rB - target) / 45)) < 0.02;
      check("下拉刷新 ④ 刷新中每 125 ms 跳 45°（离散、1 s 一圈）：250 ms 内前后两读差 90 ± 45°，且都落在 179.43 + n·45 的格上", "Δ 90 ± 45 · on grid", `${rA.toFixed(1)} → ${rB.toFixed(1)} (Δ ${(rB - rA).toFixed(1)})`, stepOK && gridOK);
      /* ⑧ bloom, ⑨ spun α (refresh-native-formula.md §11 item 3 / §11a) — read off the driver's frames */
      { const tr = R.trace.slice(), ease = R.easeInOut, bExp = (t) => t < 0.05 ? t / 0.05 : t < 0.2 ? 1 - ease((t - 0.05) / 0.15) : 0;
        const inBloom = tr.filter((s) => s.t > 0.004 && s.t < 0.19), afterBloom = tr.filter((s) => s.t >= 0.22);
        const xfOK = inBloom.every((s) => { const m = /translateY\((-?[\d.]+)px\) scale\(([\d.]+)\) translateY\(10px\)/.exec(s.xf); if (!m) return false; const b = bExp(s.t); return /^rotate\(315deg\)/.test(s.xf) && Math.abs(parseFloat(m[2]) - (1 + 0.2 * b)) < 0.003 && Math.abs(parseFloat(m[1]) - (-2 * b - 10)) < 0.03; });
        const peak = inBloom.reduce((m, s) => Math.max(m, s.b), 0);
        check("下拉刷新 ⑧ 触发瞬间的 bloom（§11a：_bloom .05 s linear → 种子 scale 1.2 + 外移 2；completion _unbloom .15 s easeInOut 回 identity）：0…190 ms 每帧臂 7 的 transform = rotate(315°) · 外移 2b · scale(1 + .2b)，b 按 t/.05 再 1 − easeInOut((t − .05)/.15)；≥ 220 ms 内联 transform 已清", `${inBloom.length}+ frames on formula · peak b > .5 · cleared`, `${inBloom.length} frames ${xfOK ? "on formula" : "OFF"} · peak b ${peak.toFixed(2)} · after .22 s: ${afterBloom.length ? (afterBloom.every((s) => s.xf === "") ? "cleared" : "still inline") : "no frame"}`, inBloom.length >= 4 && xfOK && peak > 0.5 && afterBloom.length > 0 && afterBloom.every((s) => s.xf === ""));
        const aOK = tr.every((s) => { const p = Math.max(0, Math.min(1, s.rot / target)); return s.a.every((v, i) => Math.abs(v - Math.max(0, Math.min(1, (1 - p) + i * 0.08 * p))) < 0.003); });
        const first = tr[0], mid = tr.find((s) => s.p > 0.3 && s.p < 0.9);
        check("下拉刷新 ⑨ 转起时臂 α 随同一根弹簧从全亮走到「已转」表（_setSpunAppearance：instanceColor α 1 → 0、instanceAlphaOffset 0 → .08）：每帧 α_i = clamp((1 − p) + i·.08·p)，p = rot / 179.43", "every frame on formula · frame 0 ≈ all 1", `${tr.length} frames ${aOK ? "on formula" : "OFF"} · frame 0 p ${first ? first.p.toFixed(3) : "-"} α ${first ? first.a.map((v) => v.toFixed(2)).join("/") : "-"}${mid ? ` · mid p ${mid.p.toFixed(2)} α ${mid.a.map((v) => v.toFixed(2)).join("/")}` : ""}`, tr.length > 10 && aOK && !!first && first.a.every((v) => v > 0.9));
        const rest = arms.map((x) => parseFloat(x.style.opacity)), tbl = arms.map((_, i) => i * 0.08);
        check("下拉刷新 ⑨ 弹簧到位后 8 臂 α = i × .08 = 0 / .08 / .16 / .24 / .32 / .40 / .48 / .56（尾巴淡出的转轮，最亮 .56），随 tick 整体跳转", tbl.map((v) => v.toFixed(2)).join("/"), rest.map((v) => v.toFixed(2)).join("/"), !R.spin && rest.every((v, i) => Math.abs(v - tbl[i]) < 0.002)); }
      /* ⑩ inset: nothing under the finger, 60 at the release */
      const mtDown = app ? getComputedStyle(app).marginTop : "-";
      R.__drive({ down: false }); await new Promise(requestAnimationFrame);
      const mtUp = app ? getComputedStyle(app).marginTop : "-";
      check("下拉刷新 ⑩ 刷新中大标题连列表整体下推 60（§11 第 4 条控件高 60；§12 刷新项叠在大标题之上；网页规则：手指在时不动内容，松手那一刻加上，由浏览器自己的回弹落到新位置）", "down 0px → up 60px (header margin) · body.ptr-inset", `down ${mtDown} → up ${mtUp} · ${host.classList.contains("ptr-inset") ? "body.ptr-inset" : "no class"}`, mtDown === "0px" && mtUp === "60px" && host.classList.contains("ptr-inset") && R.insetOn);
      { const hb = document.querySelector("body > header h1").getBoundingClientRect(), box = ai.getBoundingClientRect(), cy = box.top + box.height / 2, sat = (() => { const pr = document.createElement("div"); pr.style.cssText = "position:fixed;top:0;left:0;width:1px;padding-top:env(safe-area-inset-top);visibility:hidden"; document.body.appendChild(pr); const v = parseFloat(getComputedStyle(pr).paddingTop) || 0; pr.remove(); return v; })();
        const navH = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ios-nav-h")) || 54, bandTop = sat + navH, bandBot = bandTop + 60;
        check("下拉刷新 R68′ 带的位置：旋钮中心 = 栏底 + 30（带 安全区 + 54…114 的正中，§12 centerY 约束），大标题文字盒顶 = 带底 + 3.67（推到带之下；3.67 = topbar.css §10b ① 标签盒距栏区），不再是「标题 / 列表间隙、高 6.6」", `cy ${(bandTop + 30).toFixed(1)} · h1 top ${(bandBot + 3.67).toFixed(1)}`, `cy ${cy.toFixed(1)} · h1 top ${hb.top.toFixed(1)}`, Math.abs(cy - (bandTop + 30)) < 0.6 && Math.abs(hb.top - (bandBot + 3.67)) < 0.6); }
      /* ⑤ end */
      window.scrollTo(0, 0); const syEnd = window.scrollY;   // at the top: the whole 60 scrolls back (scrolled ≥ 60 the content would stay put instead)
      const tE = performance.now(); done(); await sleep(60);
      const st4 = R.state, midBack = R.back && app ? { t: (performance.now() - R.back.t0) / 1000, m: parseFloat(getComputedStyle(app).marginTop) } : null;   // ⑪: a layout sample mid-way
      let opAt = null; await sleep(300); const opEnd = parseFloat(ai.style.opacity || "1"); await sleep(120);
      check("下拉刷新 ⑤ 结束：状态 4（.3 s ease-in-out (.42,0,.58,1) 淡出 + 再转 3.1316 rad + 缩到 .001，§11a）→ 状态 0，指示器回 0°、透明度回默认", "4 → 0 · rotation 0", `after 60 ms state ${st4} · after 360 ms opacity ${isNaN(opEnd) ? "(default)" : opEnd} · now state ${R.state} · rotation ${R.rotation}`, st4 === 4 && R.state === 0 && R.rotation === 0);
      /* ⑪ the scroll-back (§11 item 1: _setAbsoluteContentOffset:animated: → curve 0, .3 s, progress sin²(π/2 · f)) on the driver's frames */
      { const bt = R.backTrace.slice(), exp = (t) => 60 * (1 - Math.pow(Math.sin(Math.PI / 2 * Math.min(1, t / 0.3)), 2));
        const rmsB = Math.sqrt(bt.reduce((s, r) => s + Math.pow(r.m - exp(r.t), 2), 0) / Math.max(1, bt.length));
        const mtEnd = app ? getComputedStyle(app).marginTop : "-";
        num("下拉刷新 ⑪ 结束后缩进 .3 s 滚回：逐帧 margin 对 60 × (1 − sin²(π/2 · t/.3)) 的 rms（px，" + bt.length + " 帧）", 0, rmsB, 0.5);
        check("下拉刷新 ⑪ 滚回中途版面真在动：+60 ms 左右读到的 computed margin-top 在 0 与 60 之间、与该时刻公式值差 ≤ 6 px（一帧的斜率）", "0 < m < 60 · |Δ| ≤ 6", midBack ? `t ${midBack.t.toFixed(3)} m ${midBack.m.toFixed(1)} vs ${exp(midBack.t).toFixed(1)}` : "no sample", !!midBack && midBack.m > 0 && midBack.m < 60 && Math.abs(midBack.m - exp(midBack.t)) <= 6);
        check("下拉刷新 ⑪ 滚回收尾：header margin 0、body.ptr-inset 已除、滚回动画结束", "0px · no class · back null", `${mtEnd} · ${host.classList.contains("ptr-inset") ? "body.ptr-inset" : "no class"} · back ${R.back ? "running" : "null"} · ${bt.length} frames · scrollY at end ${syEnd}`, bt.length >= 8 && mtEnd === "0px" && !host.classList.contains("ptr-inset") && !R.back && !R.insetOn); }
      /* R5 — the arms' geometry (refresh-native-formula.md §10, probe): 8 arms, each 3.667 × 10 with corner 1.833, inner end 5 pt from the centre (outer 15),
         every 45°; the box centred at safe-area top + 54 + 30; colour token --ios-refresh-arm (R61′: instanceColor × seed = secondaryLabel squared at α .6 —
         light rgb(14 14 18 / .6), dark rgb(217 217 235 / .6)) */
      { const box = ai.getBoundingClientRect(), cx = box.left + box.width / 2, cy = box.top + box.height / 2, a0 = arms[0], c0 = getComputedStyle(a0);
        const rot = (el) => { const m = /matrix\(([-\d.e]+), ([-\d.e]+)/.exec(getComputedStyle(el).transform || ""); return m ? Math.round(Math.atan2(parseFloat(m[2]), parseFloat(m[1])) * 180 / Math.PI) : 0; };
        const angles = arms.map(rot).map((d) => (d + 360) % 360).sort((x, y) => x - y), want = [0, 45, 90, 135, 180, 225, 270, 315];
        R.__drive({ pull: 1, v: 0, down: true }); await new Promise(requestAnimationFrame);   // state 1 so the indicator is on
        const r0 = a0.getBoundingClientRect();   // arm 0 is the unrotated one (rotate(0)): its bottom = the inner end
        const inner = cy - r0.bottom, outer = cy - r0.top;
        const sat = (() => { const pr = document.createElement("div"); pr.style.cssText = "position:fixed;top:0;left:0;width:1px;padding-top:env(safe-area-inset-top);visibility:hidden"; document.body.appendChild(pr); const v = parseFloat(getComputedStyle(pr).paddingTop) || 0; pr.remove(); return v; })();
        const navH = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ios-nav-h")) || 54;
        const tok = getComputedStyle(document.documentElement).getPropertyValue("--ios-refresh-arm").trim(), darkT = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light" || document.documentElement.dataset.theme === "dark";
        check("下拉刷新 R61′ 臂色令牌 = 复制层合成色 instanceColor × 种子色（secondaryLabel 分量平方 @ α .6；§10 R61）", darkT ? "rgb(217 217 235 / .6)" : "rgb(14 14 18 / .6)", tok, tok === (darkT ? "rgb(217 217 235 / .6)" : "rgb(14 14 18 / .6)"));
        const probe = document.createElement("i"); probe.style.cssText = "position:fixed;left:-9999px;background:" + tok; document.body.appendChild(probe); const tokRgb = getComputedStyle(probe).backgroundColor; probe.remove();
        check("下拉刷新 R5 臂几何（§10 探针）：每根 3.667 × 10、圆角 1.833、8 根每 45°", "3.667×10 r1.833 · 0/45/…/315", `${c0.width}×${c0.height} r${c0.borderTopLeftRadius} · ${angles.join("/")}`, Math.abs(parseFloat(c0.width) - 3.667) < 0.02 && Math.abs(parseFloat(c0.height) - 10) < 0.02 && Math.abs(parseFloat(c0.borderTopLeftRadius) - 1.833) < 0.02 && angles.length === 8 && angles.every((d, i) => Math.abs(d - want[i]) <= 1));
        check("下拉刷新 R5 臂到中心：内端 5 pt、外端 15 pt（环半径 5、臂长 10）", "inner 5 · outer 15", `inner ${inner.toFixed(2)} · outer ${outer.toFixed(2)}`, Math.abs(inner - 5) < 0.15 && Math.abs(outer - 15) < 0.15);
        check("下拉刷新 R5 位置与色：指示器中心 = 安全区顶 + 栏 54 + 30（控件 60 高的中心）、臂色 = --ios-refresh-arm（R61′ 合成色）", `cy ${Math.round(sat + navH + 30)} · ${tokRgb}`, `cy ${cy.toFixed(1)} · ${c0.backgroundColor}`, Math.abs(cy - (sat + navH + 30)) < 0.6 && c0.backgroundColor === tokRgb);
        R.__drive({ down: false }); await new Promise(requestAnimationFrame); }
    } finally { R.onRefresh = null; R.reset(); }
  });
})();
