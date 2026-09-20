/* accept-nav.js — push / pop of #subpage against nav-native-formula.md §0 (BOARD.md #2): the one spring ζ 1 / .3 drives the new page's x,
   the old page's parallax, the dimming and the nav items; rest states are index.html's classes. Samples are the last rAF tick's values,
   so each is accepted if it matches the closed form at t, t − 17 or t − 33 ms (frame granularity). */
ACCEPT.add(async function nav({ check, num, sleep }) {
  const N = window.Nav, pg = document.querySelector("#subpage");
  check("nav.js：window.Nav 接管 openPage（view.js 首行守卫）", "Nav.open", N && typeof N.open === "function" ? "Nav.open" : "缺", !!N && typeof N.open === "function" && !!pg);
  if (!N || !pg) return;
  const W = window.innerWidth, crit = (t) => { const u = 2 * Math.PI / .3 * t; return t <= 0 ? 0 : 1 - (1 + u) * Math.exp(-u); };
  /* S1: every wait is the drive's own frames — tick = one rAF; atEl(t) = until the drive's elapsed ≥ t s (or it ended); settled = until the drive class
     is gone; cssDone = a CSS transition's transitionend (capped). No wall-clock sleep: under load or virtual time the samples still land on the drive's own clock. */
  const tick = () => new Promise(requestAnimationFrame);
  const live = () => pg.classList.contains("nav-live");
  const atEl = async (sec, cap = 600) => { for (let i = 0; i < cap && live() && (N.state.elapsed || 0) < sec; i++) await tick(); };
  const settled = async (cap = 6000) => { const t0 = performance.now(); await tick(); while (live() && performance.now() - t0 < cap) await tick(); };
  const cssDone = async (el, prop, want, cap = 900) => { const t0 = performance.now(); await tick(); await tick(); while (getComputedStyle(el)[prop] !== want && performance.now() - t0 < cap) await tick(); };   // a CSS transition (armed by the drive's afterPaint, so two frames later): wait until the computed value has arrived (transitionend can precede the listener)
  /* S5: one row per gesture — sample every frame of the drive (computed style vs the closed form at the drive's own elapsed, frame tolerance t, t − 17, t − 33 ms)
     and report the largest deviation with its frame */
  const sampler = (read) => { const fr = []; let on = true; const loop = () => { if (!on) return; if (live()) fr.push({ el: N.state.elapsed || 0, ...read() }); requestAnimationFrame(loop); }; requestAnimationFrame(loop); return { frames: fr, stop: () => { on = false; } }; };
  const dev3 = (want, got) => Math.min(...[0, .017, .033].map((d) => Math.abs(want(d) - got)));
  const worst = (frames, key, want) => { let m = { dev: -1, i: -1, el: 0 }; frames.forEach((f, i) => { const d = dev3((dd) => want(f.el - dd), f[key]); if (d > m.dev) m = { dev: d, i, el: f.el }; }); return m; };
  const near3 = (want, got, tol) => Math.abs(want(0) - got) <= tol;   // el is the last tick's own time (N.state.tickAt − t0): the value must sit on the closed form there
  const tx = (el) => { const m = getComputedStyle(el).transform; if (!m || m === "none") return 0; const a = m.match(/matrix\(([^)]+)\)/); return a ? parseFloat(a[1].split(",")[4]) : 0; };
  const main = document.querySelector("body > main"), header = document.querySelector("body > header");
  const tr = (el) => { const v = getComputedStyle(el).translate; if (!v || v === "none") return 0; return parseFloat(v); };
  const tOpen = performance.now(); const back = N.open("验收", "<section><div class=\"group\"><div class=\"row\"><label>x</label></div></div></section>");
  const S = sampler(() => ({ x: tx(pg), from: tr(main), dim: parseFloat(getComputedStyle(document.querySelector(".nav-dim")).opacity), edge: parseFloat(getComputedStyle(pg, "::before").opacity) }));
  await atEl(.1);
  check("推入：open() 到弹簧第一帧的延迟（只报不判；真机首帧延迟另计）", "ms", Math.round((N.state.first || performance.now()) - tOpen) + " ms", true);
  { const el = N.state.elapsed;
    { const b = getComputedStyle(pg, "::before"), img = b.backgroundImage;   // R21d: _UIVerticalEdgeShadowView (−9, 0, 9, H), alpha 1 − p, image = 27 black pixels @3x α 12…18/255
      check(`推入 +${Math.round(el * 1000)} ms：左缘阴影条 宽 9、左 −9`, "9px, -9px", `${b.width}, ${b.left}`, b.width === "9px" && b.left === "-9px");
      const want27 = [12,12,12,13,13,13,13,14,14,14,14,15,15,15,16,16,16,16,16,17,17,17,17,17,17,18,18], got = [...img.matchAll(/rgba\(0, 0, 0, ([\d.]+)\) ([\d.]+)%/g)].map((m) => [Math.round(parseFloat(m[1]) * 255), parseFloat(m[2])]);
      const seg = []; for (let i = 0; i + 1 < got.length; i += 2) seg.push(got[i][0]);   // each 1/3 pt segment is serialized as two colour stops (start, end); the alpha comes back as the shortest string for its 8-bit value → compare ×255
      check("左缘阴影条剖面：27 段黑 α 12,12,12,13,…,18,18 /255，每段 1/3 pt（§9 imgdump 逐像素）", want27.join(" "), seg.join(" "), seg.length === 27 && seg.every((a, i) => a === want27[i]) && Math.abs(got[1][1] - 100 / 27) < .01); }
    { const back = pg.querySelector(".pback"), tr = getComputedStyle(back, "::before").translate, got = (tr === "none" ? "0px 0px" : tr).split(" ").map(parseFloat);   // R21e′: chevron offset = (dx, dy)·(1 − p) at the last tick's p
      const p0 = N.state.p, dx = N.state.backDx, dy = N.state.backDy, h1 = document.querySelector("body > header h1");
      const kc0 = N.seg && N.KF ? N.seg(N.KF.chev, p0) : 1, ex = dx * (1 - p0) + 7 * (1 - kc0), ey = dy * (1 - p0) + 5 * (1 - kc0);   // R47′: the chevron's own keyframe start (+7, +5) rides on top until the [.9, 1] pop-out
      check(`推入 +${Math.round(el * 1000)} ms：返回 chevron 从根页大标题文字中心出发（§5d d = label.center − 内容左上，二维），偏移 = d·(1 − p) + R47′ 关键帧起点 (+7, +5)·(1 − kc)`, `${ex.toFixed(1)} ${ey.toFixed(1)} px（d ${dx.toFixed(1)} ${dy.toFixed(1)}）`, `${got[0].toFixed(1)} ${(got[1] || 0).toFixed(1)} px`, !!h1 && Math.abs(dx) > 10 && Math.abs(got[0] - ex) < .6 && Math.abs((got[1] || 0) - ey) < .6); }
    const p = N.state.p, title = pg.querySelector(".ptitle"), want = N.fIn(N.u2(p));
    check("推入中：新页标题 alpha = f_in(u₂)，f_in = cubic-bezier(.75,.1,.75,.1)，u₂ 段 [.425, 1]；返回钮本体 alpha 1（R47′ §5g prepare，内容另走关键帧）", want.toFixed(3) + " · 1", parseFloat(getComputedStyle(title).opacity).toFixed(3) + " · " + getComputedStyle(pg.querySelector(".pback")).opacity, Math.abs(parseFloat(getComputedStyle(title).opacity) - want) < .02 && parseFloat(getComputedStyle(pg.querySelector(".pback")).opacity) === 1);
    check("推入中：过渡卡片圆角 62 / 影 r12 α.04 (0,−3)（_UIParallaxTransitionCardView）", "62px, 0 -3px 12px α.04", `${getComputedStyle(pg).borderTopLeftRadius}, ${getComputedStyle(pg).boxShadow.slice(0, 40)}`, getComputedStyle(pg).borderTopLeftRadius === "62px" && /rgba\(0, 0, 0, 0\.04\) 0px -3px 12px/.test(getComputedStyle(pg).boxShadow)); }
  await settled(); S.stop();
  { const F = S.frames, wx = worst(F, "x", (t) => W * (1 - crit(t))), wf = worst(F, "from", (t) => -(W - Math.round(.7 * W)) * crit(t)), wd = worst(F, "dim", (t) => crit(t)), we = worst(F, "edge", (t) => 1 - crit(t));
    check(`推入逐帧 ${F.length} 帧（S5，一手势一行）：新页 x = W(1 − p)、旧页视差 −132·p、暗幕 α = p、左缘条 α = 1 − p，p = 1 − (1 + ωt)e^{−ωt} ω 20.94，按弹簧自己的时间（容 t / t − 17 / t − 33 ms）`, "x ± 2 · 视差 ± 1 · 暗幕 ± .01 · 边条 ± .01", `x ${wx.dev.toFixed(2)} @${wx.i} (${Math.round(wx.el * 1000)} ms) · 视差 ${wf.dev.toFixed(2)} @${wf.i} · 暗幕 ${wd.dev.toFixed(3)} @${wd.i} · 边条 ${we.dev.toFixed(3)} @${we.i}`, F.length >= 3 && wx.dev <= 2 && wf.dev <= 1 && wd.dev <= .01 && we.dev <= .01);
    check("暗幕颜色 黑 .1", "rgba(0, 0, 0, 0.1)", getComputedStyle(document.querySelector(".nav-dim")).backgroundColor, getComputedStyle(document.querySelector(".nav-dim")).backgroundColor === "rgba(0, 0, 0, 0.1)"); }
  back();
  const P = sampler(() => ({ x: tx(pg), from: tr(main) }));
  await atEl(.1);
  { const p = N.state.p, want = 1 - N.fOut(N.u1(1 - p));
    check("返回中：顶页标题 / 返回钮 alpha = 1 − f_out(u₁)，f_out = cubic-bezier(.25,.9,.25,.9)，u₁ 段 [0, .575]", want.toFixed(3), parseFloat(getComputedStyle(pg.querySelector(".ptitle")).opacity).toFixed(3), Math.abs(parseFloat(getComputedStyle(pg.querySelector(".ptitle")).opacity) - want) < .02); }
  await settled(); P.stop();
  { const F = P.frames, wx = worst(F, "x", (t) => W * crit(t)), wf = worst(F, "from", (t) => -(W - Math.round(.7 * W)) * (1 - crit(t)));
    check(`返回逐帧 ${F.length} 帧（S5）：顶页 x = W·p′、下页视差 −132·(1 − p′)（同一弹簧，角色互换）`, "x ± 2 · 视差 ± 1", `x ${wx.dev.toFixed(2)} @${wx.i} (${Math.round(wx.el * 1000)} ms) · 视差 ${wf.dev.toFixed(2)} @${wf.i}`, F.length >= 3 && wx.dev <= 2 && wf.dev <= 1); }
  check("返回落定：页 hidden、body.pushed 去掉、视差 0", "hidden, -, 0", `${pg.hidden ? "hidden" : "shown"}, ${document.body.classList.contains("pushed") ? "pushed" : "-"}, ${tr(main)}`, pg.hidden && !document.body.classList.contains("pushed") && Math.abs(tr(main)) < .5);
  /* interrupt: pop while the push is mid-flight continues from the current p / v (no jump) */
  N.open("验收", "<p>y</p>"); await atEl(.12); const pMid = N.state.p, xMid = tx(pg); N.back(); await tick(); await tick();
  check("推入中途返回：从当前 p / 速度续算，不跳变（打断后一帧内位移 < 60 px）", "< 60", Math.round(Math.abs(tx(pg) - xMid)), Math.abs(tx(pg) - xMid) < 60 && pMid > .5);
  await settled();
  check("中途返回落定：hidden", "hidden", pg.hidden ? "hidden" : "shown", pg.hidden);
}, { layer: "timing", dark: false });

/* R47′ — the root's large title and the back chevron during push / pop (nav-native-formula.md §5g; nav.js R47′). Judged on the driver's own frames
   (Nav.state.trace: p and the values it wrote, A15) and on computed style right after a frame: the h1's transform matrix = scale(1 + (w_chev / w_h1 − 1)p,
   1 + (h_chev / h_h1 − 1)p) with translate(−d·p − parallax·p, −d_y·p) (the header's parallax compensated), opacity = 1 − clamp(p / .6); the chevron's
   ::before opacity = clamp((p − .5) / .5) × clamp((p − .9) / .1), scale .7 → 1 and offset (+7, +5) → 0 in [.9, 1] on top of the R21e′ ride; the back
   button's body opacity 1 on the push; every push frame of the trace on those formulas, and frames past p .9 exist (the pop-out ran); at rest all vars
   are gone (h1 transform none, opacity 1); the pop runs the same functions of p backwards (its own keyframes unread) with the body fading as the items. */
ACCEPT.add(async function navLargeTitle({ check, num, sleep }) {
  const N = window.Nav, pg = document.querySelector("#subpage"), h1 = document.querySelector("body > header h1"), pback = pg && pg.querySelector(".pback");
  if (!N || !pg || !h1 || !pback || !N.KF) { check("R47′：Nav.KF / #subpage / 大标题 h1 缺", "有", "缺", false); return; }
  const tick = () => new Promise(requestAnimationFrame), live = () => pg.classList.contains("nav-live");   // S1: waits on the drive's own frames
  const atEl = async (sec, cap = 600) => { for (let i = 0; i < cap && live() && (N.state.elapsed || 0) < sec; i++) await tick(); };
  const atP = async (cond, cap = 600) => { for (let i = 0; i < cap && live() && !cond(); i++) await tick(); };
  const settled = async (cap = 6000) => { const t0 = performance.now(); await tick(); while (live() && performance.now() - t0 < cap) await tick(); };
  const cssDone = async (el, prop, want, cap = 900) => { const t0 = performance.now(); await tick(); await tick(); while (getComputedStyle(el)[prop] !== want && performance.now() - t0 < cap) await tick(); };   // a CSS transition (armed by the drive's afterPaint, so two frames later): wait until the computed value has arrived (transitionend can precede the listener)
  const mat = (el) => { const m = getComputedStyle(el).transform; const x = /matrix\(([^)]+)\)/.exec(m || ""); return x ? x[1].split(",").map(parseFloat) : (m === "none" || !m ? [1, 0, 0, 1, 0, 0] : null); };
  const seg = (s, e, p) => Math.max(0, Math.min(1, (p - s) / (e - s)));
  const near = (a, b, tol) => Math.abs(a - b) <= tol;
  window.scrollTo(0, 0); document.documentElement.style.removeProperty("--big");
  N.open("R47′", "<section><p>t</p></section>");
  await atEl(.04); await tick();
  const H = N.state.h1, tr = N.state.trace;
  check("R47′ 量到大标题的缩放参照（mode 2：chevron bounds / 文字 bounds，绕文字中心）与 d（R21e′ 的同一个 d）", "sx, sy < 1 · d ≠ 0", H ? `sx ${H.sx.toFixed(4)} (${H.cw}/${H.w.toFixed(1)}) · sy ${H.sy.toFixed(4)} (${H.ch}/${H.h.toFixed(1)}) · d (${N.state.backDx.toFixed(1)}, ${N.state.backDy.toFixed(1)}) · origin (${H.ox.toFixed(1)}, ${H.oy.toFixed(1)})` : "no h1 metrics", !!H && H.sx > 0 && H.sx < 1 && H.sy > 0 && H.sy < 1 && N.state.backDx !== 0);
  { const s = tr[tr.length - 1], m = mat(h1), op = parseFloat(getComputedStyle(h1).opacity), cb = getComputedStyle(pback, "::before"), body = parseFloat(getComputedStyle(pback).opacity);
    const okM = !!s && !!s.h1 && !!m && near(m[0], s.h1.sx, .002) && near(m[3], s.h1.sy, .002) && near(m[4], s.h1.dx, .5) && near(m[5], s.h1.dy, .5) && near(m[1], 0, 1e-6) && near(m[2], 0, 1e-6);
    check(`推入 +${s ? Math.round(s.el * 1000) : "?"} ms（p ${s ? s.p.toFixed(3) : "?"}）：大标题 transform = 绕文字中心 scale(1 + (sx − 1)p, 1 + (sy − 1)p)、平移 (−d_x·p − 视差·p, −d_y·p)（屏幕上中心走 −d·p）`, s && s.h1 ? `matrix(${s.h1.sx.toFixed(3)}, 0, 0, ${s.h1.sy.toFixed(3)}, ${s.h1.dx.toFixed(1)}, ${s.h1.dy.toFixed(1)})` : "-", m ? `matrix(${m.map((v, i) => i < 4 ? v.toFixed(3) : v.toFixed(1)).join(", ")})` : "none", okM);
    check(`推入 +${s ? Math.round(s.el * 1000) : "?"} ms：大标题 alpha = 1 − clamp(p / .6)（关键帧 [0, .6] → 0，文字不同）`, s && s.h1 ? s.h1.a.toFixed(3) : "-", op.toFixed(3), !!s && !!s.h1 && near(op, s.h1.a, .01));
    check(`推入 +${s ? Math.round(s.el * 1000) : "?"} ms：返回钮本体 alpha 1（prepare），chevron 内容 alpha = [.5,1] 段 × [.9,1] 段 = 0、scale .7、偏 (+7, +5) 叠在 R21e′ 的 d(1 − p) 上`, "1 · 0 · 0.7 · +7 +5", `${body} · ${cb.opacity} · ${cb.scale} · ${cb.translate}`, body === 1 && parseFloat(cb.opacity) === 0 && near(parseFloat(cb.scale), .7, .001) && !!s && near(parseFloat(cb.translate.split(" ")[0]), N.state.backDx * (1 - s.p) + 7, .6) && near(parseFloat(cb.translate.split(" ")[1]), N.state.backDy * (1 - s.p) + 5, .6)); }
  await atP(() => N.state.p >= .6); await tick();
  { const s = tr[tr.length - 1], op = parseFloat(getComputedStyle(h1).opacity), cb = getComputedStyle(pback, "::before");
    check(`推入 +${s ? Math.round(s.el * 1000) : "?"} ms（p ${s ? s.p.toFixed(3) : "?"} ≥ .6）：大标题 alpha 已到 0，chevron 仍 0（p < .9）`, "0 · 0", `${op} · ${cb.opacity}`, !!s && s.p >= .6 && s.p < .9 && op === 0 && parseFloat(cb.opacity) === 0); }
  await settled(); await cssDone(h1, "opacity", "1");   // topbar.css's h1 opacity transition (.2 s linear, --tb-large) runs once the drive's own value is removed
  { const push = tr.filter((s) => s.dir > 0 && s.h1), K = N.KF, C = N.CHEV0;
    const onF = push.every((s) => near(s.h1.a, 1 - seg(0, .6, s.p), 1e-6) && near(s.back.ca, seg(.5, 1, s.p) * seg(.9, 1, s.p), 1e-6) && near(s.back.cs, .7 + .3 * seg(.9, 1, s.p), 1e-6) && near(s.back.kx, 7 * (1 - seg(.9, 1, s.p)), 1e-6) && near(s.back.ky, 5 * (1 - seg(.9, 1, s.p)), 1e-6) && s.back.a === 1);
    const late = push.filter((s) => s.p > .9 && s.p < .999);
    check(`R47′ 推入全程 ${push.length} 帧：关键帧常量 [0,.6] / [.5,1] / [.9,1]、.7×、(+7,+5) 逐帧成立；p ∈ (.9, .999) 有 ${late.length} 帧（弹出段真走过）；KF ${JSON.stringify(K)} CHEV0 ${JSON.stringify(C)}`, "on formula · late ≥ 3", `${onF ? "on formula" : "OFF"} · late ${late.length}`, push.length > 10 && onF && late.length >= 3 && !!K.popBackOut && K.popBackOut[1] === .6 && !!K.popH1In && K.popH1In[0] === .5);
    const m = mat(h1), cb = getComputedStyle(pback, "::before");
    check("推入落定：大标题 transform 恒等、alpha 1（变量已清）；chevron opacity 1、scale 1、偏移 0", "identity · 1 · 1 · none/1 · 0", `${m ? m.map((v) => +v.toFixed(3)).join(",") : "?"} · ${getComputedStyle(h1).opacity} · ${cb.opacity} · ${cb.scale} · ${cb.translate}`, !!m && near(m[0], 1, 1e-6) && near(m[3], 1, 1e-6) && near(m[4], 0, 1e-6) && parseFloat(getComputedStyle(h1).opacity) === 1 && parseFloat(cb.opacity) === 1 && (cb.scale === "none" || parseFloat(cb.scale) === 1) && (cb.translate === "none" || parseFloat(cb.translate) === 0)); }
  N.back();
  await atEl(.1); await tick();
  { const tr2 = N.state.trace, s = tr2[tr2.length - 1], m = mat(h1), op = parseFloat(getComputedStyle(h1).opacity), body = parseFloat(getComputedStyle(pback).opacity), cb = getComputedStyle(pback, "::before");
    const u = s ? 1 - s.p : 0, wantA = seg(.5, 1, u);
    check(`返回 +${s ? Math.round(s.el * 1000) : "?"} ms（p ${s ? s.p.toFixed(3) : "?"}，u = 1 − p ${u.toFixed(3)}）：大标题 scale / 平移 = 推入倒放（mode 5），alpha = Pop 自己的关键帧 [.5, 1] → 1（前半压 0，§5g′ kf2 / kf3）`, s && s.h1 ? `${s.h1.sx.toFixed(3)} ${s.h1.sy.toFixed(3)} ${s.h1.dx.toFixed(1)} ${s.h1.dy.toFixed(1)} · α ${wantA.toFixed(3)}` : "-", m ? `${m[0].toFixed(3)} ${m[3].toFixed(3)} ${m[4].toFixed(1)} ${m[5].toFixed(1)} · α ${op.toFixed(3)}` : "none", !!s && s.dir < 0 && !!s.h1 && !!m && near(m[0], s.h1.sx, .002) && near(m[3], s.h1.sy, .002) && near(m[4], s.h1.dx, .5) && near(op, wantA, .01) && near(s.h1.a, wantA, 1e-6));
    const wantCa = (1 - seg(0, .6, u)) * seg(.9, 1, s ? s.p : 0), wantCs = .7 + .3 * seg(.9, 1, s ? s.p : 0);
    check(`返回 +${s ? Math.round(s.el * 1000) : "?"} ms：返回钮本体随栏项淡出（1 − f_out(u₁)）；内容 alpha = Pop kf1 [0, .6] → 0 × chevron 头 10 % 缩出（scale → .7、偏 (+7, +5)、alpha 0，§5g′ block_6 = 推入 [.9, 1] 倒读）`, s ? `${s.back.a.toFixed(3)} · ${wantCa.toFixed(3)} · ${wantCs.toFixed(3)}` : "-", `${body.toFixed(3)} · ${cb.opacity} · ${cb.scale}`, !!s && near(body, s.back.a, .01) && near(parseFloat(cb.opacity), wantCa, .01) && near(parseFloat(cb.scale), wantCs, .002)); }
  await settled(); await cssDone(h1, "opacity", "1");
  { const tr2 = N.state.trace, pop = tr2.filter((s) => s.dir < 0 && s.h1), onP = pop.every((s) => { const u = 1 - s.p; return near(s.h1.a, seg(.5, 1, u), 1e-6) && near(s.back.ca, (1 - seg(0, .6, u)) * seg(.9, 1, s.p), 1e-6) && near(s.back.cs, .7 + .3 * seg(.9, 1, s.p), 1e-6) && near(s.back.kx, 7 * (1 - seg(.9, 1, s.p)), 1e-6); }), early = pop.filter((s) => 1 - s.p > 0 && 1 - s.p < .1);
    check(`R69′ 返回全程 ${pop.length} 帧：大标题 α = seg[.5,1](u)、返回钮内容 α = (1 − seg[0,.6](u)) × chevron 段、chevron scale / 偏移按 p 的 [.9,1] 段逐帧成立；u ∈ (0, .1) 有 ${early.length} 帧（缩出段真走过）`, "on formula · early ≥ 1", `${onP ? "on formula" : "OFF"} · early ${early.length}`, pop.length > 10 && onP && early.length >= 1); }
  { const m = mat(h1); check("返回落定：大标题恒等、alpha 1、body 变量已清", "identity · 1 · no vars", `${m ? m.map((v) => +v.toFixed(3)).join(",") : "?"} · ${getComputedStyle(h1).opacity} · ${document.body.style.getPropertyValue("--nav-h1-a") === "" ? "no vars" : "vars left"}`, !!m && near(m[0], 1, 1e-6) && near(m[4], 0, 1e-6) && parseFloat(getComputedStyle(h1).opacity) === 1 && document.body.style.getPropertyValue("--nav-h1-a") === ""); }
}, { layer: "timing", dark: false });
