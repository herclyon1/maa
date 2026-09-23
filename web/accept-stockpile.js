/* accept-stockpile.js — acceptance of the pushed 库存 page (stockpile.js; WORKLIST P4 = remote-mock/v4/inventory-plan.md §8, with the M4g–M4i
   wording the user set on 09-23: 「差 N」, 「库存 6 + 箱 110」, k from 10,000, the box as a conversion note). Registered through ACCEPT.add; runs in
   accept.js's page (light and dark). Inventory.refresh is stubbed (no 森空岛 request); each state is reached by the page's own controls, action →
   visible response:
   ① the 终末地 tab's first group: a single-row card with no header, row 53.33, text x 40, chevron (389.67, +19.33, 10.33 × 14) tertiaryLabel (§2);
   ② tap 「库存」 → pushed: bar (0, sat, 440, 54), title 「库存」 Semibold 17 centred, back (20, sat, 44, 44), 「刷新」 (358, sat + 4, 58, 36) Medium 17
      tint, tab bar still there with 终末地 selected (§3); while reading: one card, one row 53.33, text x 40, spinner 20 × 20 at x 380, card top
      sat + 54 + 17.67, 「刷新」 disabled (opacity .5) (§5);
   ③ 没配森空岛 (no data yet) → empty state: icon 60, title 22, button 34.67 「去手机页」 (§5);
   ④ 「刷新」 → an error with no data yet → empty state 「读不到库存」 + the error text + 「重试」 (§5);
   ⑤ 「重试」 → the list: sections = `group` in games[].groups order, rows without a group not shown, inside a section 人份 ascending, ties by stock,
      rows without a need last and without a right value (§4.1, §4.3); every row 62, icon (40, +17, 28, 28), title (83, +9) 17 label, subtitle
      (83, +32.33) 15 settings-subtitle, right value 17 secondaryLabel right edge 400 and centred, separator 83 → 400 1 pt, none under the last
      row (§4.2); texts: 千分位, k from 10,000, 「差 N」 / 「需 N」 only on short rows, 「库存 6 + 箱 110」, origin tail, servingsOf(354, 136) = 2.6,
      the box section 「133 个 · 换成缺的材料用了 131 个」 / 「剩 2 个」; a failed icon keeps its 28 slot hidden; footnote lines (§4.3, M4i);
   ⑥ 「刷新」 → an error with the old list → the list stays, not dimmed, footnote first line 「HH:MM 读取的数据；这次没读到：<error>」 (§5);
   ⑦ the lag sentence only when the data carries one (§4.3); ⑧ 0 rows → the centred grey caption, width 312 (§5);
   ⑨ 「去手机页」 → popped, 手机 selected, 「刷新」 gone from the bar.
   Dark: the same rows (accept-run.py dark); the subtitle colour is checked in light only — tokens.css has no dark value for
   --ios-settings-subtitle (待读: Settings not captured in dark). Not judged here: the spinner's vertical place (待读), the row press highlight
   (界面's view.js, §2 无来源). */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptStockpile(ctx) {
    const { check, num, col } = ctx;
    const I = window.Inventory, S = window.Stockpile;
    if (!I || !S || !S.reset) { check("库存：Inventory / Stockpile 未装载（inventory.js / stockpile.js）", "装载", "缺", false); return; }
    const dark = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light" || document.documentElement.dataset.theme === "dark";
    const C = dark
      ? { label: [255, 255, 255], sec: [235, 235, 245, 0.6], ter: [235, 235, 245, 0.298], sep: [84, 84, 88, 0.5], tint: [0, 145, 255], grey: [142, 142, 147] }
      : { label: [0, 0, 0], sec: [60, 60, 67, 0.6], ter: [60, 60, 67, 0.298], sep: [60, 60, 67, 0.12], tint: [0, 136, 255], grey: [142, 142, 147], sub: [128, 128, 128] };
    const sat = (() => { const pr = document.createElement("div"); pr.style.cssText = "position:fixed;top:0;padding-top:env(safe-area-inset-top);visibility:hidden"; document.body.appendChild(pr); const v = parseFloat(getComputedStyle(pr).paddingTop) || 0; pr.remove(); return v; })();
    const frames = async (ms, ok) => { const t = performance.now() + ms; while (!ok() && performance.now() < t) await new Promise(requestAnimationFrame); return ok(); };
    const R = (el) => el.getBoundingClientRect(), r2 = (v) => Math.round(v * 100) / 100, cs = (el, p) => getComputedStyle(el, p || null);
    const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";
    const BAD = "data:image/png;base64,AAAA";
    const row = (o) => Object.assign({ icon: PNG, box: 0, short: 0, origin: null }, o);
    const good = (extra) => ({ "取自": "12:34", games: [Object.assign({ game: "终末地", "错误": "", caliber: "测试口径", groups: ["干员精英化", "武器突破"],
      box: { id: "box1", name: "高阶培养自选箱Ⅰ", note: "箱 N = 测试句" },
      rows: [
        row({ id: "a", name: "甲", have: 354, need: 136, servings: I.servingsOf(354, 136), group: "武器突破", origin: { 采集: ["某处"] } }),
        row({ id: "b", name: "乙", have: 6, need: 116, servings: 1, box: 110, group: "干员精英化", origin: { 理智关卡: ["某关"] } }),
        row({ id: "c", name: "丙", icon: BAD, have: 5, need: 100, servings: 0, short: 95, group: "干员精英化" }),
        row({ id: "d", name: "丁", have: 22639400, need: 1000000, servings: 22.6, group: "干员精英化" }),
        row({ id: "e", name: "戊", have: 3, need: null, servings: null, short: null, group: "干员精英化" }),
        row({ id: "f", name: "己", have: 9, need: 10, servings: 0.9, short: 1, group: null }),
        row({ id: "g", name: "庚", have: 1, need: 100, servings: 0, short: 99, group: "干员精英化" }),
        row({ id: "box1", name: "高阶培养自选箱Ⅰ", have: 133, need: null, servings: null, short: null, group: null, boxUsed: 131, boxLeft: 2 })] }, extra || {})] });
    let pend = null;
    const orig = I.refresh;
    I.refresh = () => new Promise((res) => { pend = res; });
    const answer = async (d) => { await frames(1000, () => pend); const p = pend; pend = null; if (p) p(d); await frames(1000, () => !document.querySelector("#stockbody .stk-load")); await new Promise(requestAnimationFrame); };
    const body = () => document.getElementById("stockbody");
    const refreshBtn = () => document.querySelector("#subpage .stk-refresh");
    const tabs = document.getElementById("tabs");
    const tabOn = () => { const b = tabs && tabs.querySelector("button.on"); return b ? b.dataset.tab : "缺"; };
    const startTab = tabOn();
    try {
      S.reset();
      /* ① */
      const tb = tabs && tabs.querySelector('button[data-tab="终末地"]');
      if (tb) tb.click();
      await frames(1000, () => { const e = document.querySelector('.row.nav[data-page="stockpile"]'); return e && R(e).height > 0; });
      const entry = document.querySelector('.row.nav[data-page="stockpile"]');
      if (!entry || !R(entry).height) { check("库存 ① 终末地页「库存 ›」入口行", "在", "缺", false); return; }
      const sec = entry.closest("section"), card = entry.closest(".group"), lab = entry.querySelector("label"), chev = entry.querySelector(".chev");
      const er = R(entry), cr = R(card), lr = R(lab), vr = chev ? R(chev) : { left: 0, top: 0, width: 0, height: 0 };
      const firstSec = [...document.querySelectorAll("main section, #app section")].find((s) => R(s).height > 0);
      check("库存 ① 入口 = 终末地页首组、无组头、单行卡（方案 §2，AX-46）", "首组 · 无 h2 · 1 行", `${firstSec === sec ? "首组" : "非首组"} · ${sec.querySelector("h2") ? "有 h2" : "无 h2"} · ${card.querySelectorAll(".row").length} 行`, firstSec === sec && !sec.querySelector("h2") && card.querySelectorAll(".row").length === 1);
      check("库存 ① 入口行几何：卡 x 20 宽 400、行高 53.33、文字 x 40、箭头 (389.67, 行顶 + 19.33, 10.33 × 14)（§2，AX-46）", "20 · 400 · 53.33 · 40 · 389.67 / 19.33 / 10.33×14",
        `${r2(cr.left)} · ${r2(cr.width)} · ${r2(er.height)} · ${r2(lr.left)} · ${r2(vr.left)} / ${r2(vr.top - er.top)} / ${r2(vr.width)}×${r2(vr.height)}`,
        Math.abs(cr.left - 20) < 0.6 && Math.abs(cr.width - 400) < 0.6 && Math.abs(er.height - 53.33) < 0.6 && Math.abs(lr.left - 40) < 0.6 && Math.abs(vr.left - 389.67) < 0.6 && Math.abs(vr.top - er.top - 19.33) < 0.6 && Math.abs(vr.width - 10.33) < 0.1 && Math.abs(vr.height - 14) < 0.1);
      if (chev) col("库存 ① 入口箭头色 = tertiaryLabel（§2）", C.ter, cs(chev).backgroundColor);
      /* ② */
      entry.click();
      await frames(2000, () => document.body.classList.contains("pushed") && body() && Math.abs(R(document.getElementById("subpage")).left) < 0.5);
      await frames(1000, () => window.Nav && Nav.state && !Nav.state.anim);
      const pg = document.getElementById("subpage"), bar = pg.querySelector(".pnav"), ttl = pg.querySelector(".ptitle"), back = pg.querySelector(".pback"), rb = refreshBtn();
      const br = R(bar), tr = R(ttl), bk = R(back), rr = rb ? R(rb) : { left: 0, top: 0, width: 0, height: 0 };
      check("库存 ② 推入：导航栏 (0, 安全区, 440, 54)、标题「库存」Semibold 17 居中、返回钮 (20, 安全区, 44, 44)（§3，AX-11 / AX-46）",
        `0/${sat}/440/54 · 库存 600 17 · 中 220 · 20/${sat}/44/44`,
        `${r2(br.left)}/${r2(br.top)}/${r2(br.width)}/${r2(br.height)} · ${ttl.textContent} ${cs(ttl).fontWeight} ${parseFloat(cs(ttl).fontSize)} · 中 ${r2((tr.left + tr.right) / 2)} · ${r2(bk.left)}/${r2(bk.top)}/${r2(bk.width)}/${r2(bk.height)}`,
        Math.abs(br.left) < 0.6 && Math.abs(br.top - sat) < 0.6 && Math.abs(br.width - 440) < 0.6 && Math.abs(br.height - 54) < 0.6 && ttl.textContent === "库存" && cs(ttl).fontWeight === "600" && parseFloat(cs(ttl).fontSize) === 17
          && Math.abs((tr.left + tr.right) / 2 - 220) < 1 && Math.abs(bk.left - 20) < 0.6 && Math.abs(bk.top - sat) < 0.6 && Math.abs(bk.width - 44) < 0.6 && Math.abs(bk.height - 44) < 0.6);
      check("库存 ② 「刷新」文字钮 (358, 安全区 + 4, 58, 36) Medium 17（§3，AX-11「编辑」）", `358/${sat + 4}/58/36 · 500 17`,
        `${r2(rr.left)}/${r2(rr.top)}/${r2(rr.width)}/${r2(rr.height)} · ${rb ? cs(rb).fontWeight : "缺"} ${rb ? parseFloat(cs(rb).fontSize) : "缺"}`,
        !!rb && Math.abs(rr.left - 358) < 0.6 && Math.abs(rr.top - sat - 4) < 0.6 && Math.abs(rr.width - 58) < 0.6 && Math.abs(rr.height - 36) < 0.6 && cs(rb).fontWeight === "500" && parseFloat(cs(rb).fontSize) === 17);
      if (rb) col("库存 ② 「刷新」色 = tint（§3，spec-table §2）", C.tint, cs(rb).color);
      check("库存 ② 推入页仍有标签栏、选中「终末地」（§3，AX-11）", "显示 · 终末地", `${tabs && cs(tabs).display !== "none" && !tabs.hidden ? "显示" : "不显示"} · ${tabOn()}`, !!tabs && cs(tabs).display !== "none" && !tabs.hidden && tabOn() === "终末地");
      const ld = body().querySelector(".stk-load"), ai = ld && ld.querySelector(".ai");
      const ldr = ld ? R(ld) : { left: 0, top: 0, height: 0 }, air = ai ? R(ai) : { left: 0, width: 0, height: 0 }, ldCard = ld ? R(ld.parentNode) : { top: 0 };
      const txr = (() => { if (!ld) return { left: 0 }; const rg = document.createRange(); rg.selectNodeContents(ld.firstChild); return rg.getBoundingClientRect(); })();
      check("库存 ② 读取中：一卡一行「正在从森空岛读取…」，行高 53.33、文字 x 40、首卡顶 = 安全区 + 54 + 17.67、转圈 20 × 20 在 x 380（§5 / §3，探针 UIActivityIndicatorView）",
        `正在从森空岛读取… · 53.33 · 40 · ${r2(sat + 71.67)} · 380/20×20`,
        ld ? `${ld.textContent} · ${r2(ldr.height)} · ${r2(txr.left)} · ${r2(ldCard.top)} · ${r2(air.left)}/${r2(air.width)}×${r2(air.height)}` : "缺",
        !!ld && ld.textContent === "正在从森空岛读取…" && Math.abs(ldr.height - 53.33) < 0.6 && Math.abs(txr.left - 40) < 0.6 && Math.abs(ldCard.top - sat - 71.67) < 0.6 && !!ai && Math.abs(air.left - 380) < 0.6 && Math.abs(air.width - 20) < 0.1 && Math.abs(air.height - 20) < 0.1);
      check("库存 ② 读取中「刷新」灰掉：disabled、不透明度 .5（§5，--ios-disabled-opacity）", "disabled · 0.5", rb ? `${rb.disabled ? "disabled" : "可点"} · ${cs(rb).opacity}` : "缺", !!rb && rb.disabled && parseFloat(cs(rb).opacity) === 0.5);
      /* ③ */
      await answer({ games: [{ "错误": "没配森空岛" }] });
      const emptyOf = () => { const e = body().querySelector(".stk-empty"); if (!e) return null; const sv = e.querySelector("svg"), t = e.querySelector(".ttl"), x = e.querySelector(".txt"), b = e.querySelector("button");
        return { sv: R(sv), t: t.textContent, tfs: parseFloat(cs(t).fontSize), x: x.textContent, b: b.textContent, bh: R(b).height }; };
      let em = emptyOf();
      check("库存 ③ 没配森空岛 → 空状态：图标 60、标题 22「没配森空岛」、说明原文、钮 34.67「去手机页」（§5，AX-55b）", "60×60 · 没配森空岛 22 · 库存从森空岛读；在「手机」页填好密钥串再来。 · 去手机页 34.67",
        em ? `${r2(em.sv.width)}×${r2(em.sv.height)} · ${em.t} ${em.tfs} · ${em.x} · ${em.b} ${r2(em.bh)}` : "缺",
        !!em && Math.abs(em.sv.width - 60) < 0.1 && Math.abs(em.sv.height - 60) < 0.1 && em.t === "没配森空岛" && em.tfs === 22 && em.x === "库存从森空岛读；在「手机」页填好密钥串再来。" && em.b === "去手机页" && Math.abs(em.bh - 34.67) < 0.1);
      check("库存 ③ 读完「刷新」恢复可点", "可点", rb && !rb.disabled ? "可点" : "disabled", !!rb && !rb.disabled);
      /* ④ */
      rb.click();
      await answer({ games: [{ "错误": "网络不通" }] });
      em = emptyOf();
      check("库存 ④ 点「刷新」→ 读失败、没旧数据 → 空状态「读不到库存」+ 错误原文 +「重试」（§5）", "读不到库存 · 网络不通 · 重试", em ? `${em.t} · ${em.x} · ${em.b}` : "缺", !!em && em.t === "读不到库存" && em.x === "网络不通" && em.b === "重试");
      /* ⑤ */
      body().querySelector(".stk-empty button").click();
      await answer(good());
      await frames(1000, () => { const b = body().querySelector('img[src="' + BAD + '"]'); return b && b.style.visibility === "hidden"; });
      const secs = [...body().querySelectorAll("section")];
      check("库存 ⑤ 点「重试」→ 列表：节名 = group 原文、按 games[].groups 顺序、无 group 的行不显示、资源箱自成末节（§4.1，M4g）", "干员精英化 / 武器突破 / 资源箱 · 无「己」",
        `${secs.map((s) => s.querySelector("h2").textContent).join(" / ")} · ${body().textContent.includes("己") ? "有「己」" : "无「己」"}`,
        secs.map((s) => s.querySelector("h2").textContent).join("/") === "干员精英化/武器突破/资源箱" && !body().textContent.includes("己"));
      const names = (s) => [...s.querySelectorAll(".stk-row .t")].map((t) => t.textContent).join(" ");
      check("库存 ⑤ 节内排序：人份升序、同人份按库存升序、无需求的行在末（§4.3）", "庚 丙 乙 丁 戊", secs[0] ? names(secs[0]) : "缺", !!secs[0] && names(secs[0]) === "庚 丙 乙 丁 戊");
      const byName = (n) => [...body().querySelectorAll(".stk-row")].find((r) => r.querySelector(".t").textContent === n);
      const txt = (n) => { const r = byName(n); return r ? `${r.querySelector(".s").textContent} | ${r.querySelector(".v") ? r.querySelector(".v").textContent : "（无右值）"}` : "缺"; };
      const want = {
        庚: "库存 1 · 需 100 | 差 99", 丙: "库存 5 · 需 100 | 差 95", 乙: "库存 6 + 箱 110 · 理智关卡 | 1.0 人份", 丁: "库存 22,639k | 22.6 人份", 戊: "库存 3 | （无右值）",
        甲: "库存 354 · 采集 | 2.6 人份", 高阶培养自选箱Ⅰ: "133 个 · 换成缺的材料用了 131 个 | 剩 2 个" };
      for (const [n, w] of Object.entries(want)) check(`库存 ⑤ 行文字「${n}」：千分位、≥ 10,000 写 k、只有缺的行写「需 N」「差 N」、箱写「+ 箱 N」、尾写来源（§4.3，M4g–M4i）`, w, txt(n), txt(n) === w);
      const wrapCheck = (tag, mustWrap) => { const rows = [...document.querySelectorAll("#subpage .stk-row")].filter((r) => r.querySelector(".s")), bad = [];
        for (const r of rows) { const s = r.querySelector(".s"), lh = parseFloat(cs(s).lineHeight), n = Math.round(R(s).height / lh), want = 62 + (n - 1) * lh;
          if (s.scrollWidth > s.clientWidth + .5 || Math.abs(R(r).height - want) > .5 || cs(s).whiteSpace !== "normal") bad.push(`${r.querySelector(".t").textContent} ${n} 行 ${R(r).height.toFixed(2)}`); }
        const wrapped = rows.filter((r) => Math.round(R(r.querySelector(".s")).height / parseFloat(cs(r.querySelector(".s")).lineHeight)) > 1).map((r) => `${r.querySelector(".t").textContent} ${r2(R(r).height)}`);
        if (mustWrap && !wrapped.length) bad.push("没有折行的行");
        check(`库存 ${tag} 副标题超宽折行、不省略，行高 = 62 + (行数 − 1) × 副标题行高（UIListContentConfiguration subtitleCell numberOfLines 0，数据探针 cellcfg.json 09-23 17:18）`, "全行合 · 无截断",
          bad.length ? bad.join(" / ") : `全行合 · 无截断（${rows.length} 行${wrapped.length ? "，折行：" + wrapped.join("、") : "，本数据无折行"}）`, bad.length === 0); };
      wrapCheck("⑤", false);
      num("库存 ⑤ 人份固定样例 servingsOf(354, 136) = 2.6（一位小数向下取，§8.5）", 2.6, I.servingsOf(354, 136), 0.001);
      const bad = body().querySelector('img[src="' + BAD + '"]');
      check("库存 ⑤ 图标读不到：留 28 的空位、不放替代图（§4.2）", "hidden · 28×28", bad ? `${bad.style.visibility} · ${r2(R(bad).width)}×${r2(R(bad).height)}` : "缺", !!bad && bad.style.visibility === "hidden" && Math.abs(R(bad).width - 28) < 0.1 && Math.abs(R(bad).height - 28) < 0.1);
      const card1 = secs[0] && secs[0].querySelector(".stk-card"), h1t = secs[0] ? R(secs[0].querySelector("h2")).top + parseFloat(cs(secs[0].querySelector("h2")).paddingTop) : 0;
      check("库存 ⑤ 首节：组头文字顶 = 栏底 + 18.67、首卡顶 = 安全区 + 54 + 组头 45.33（index.html .page > .pbody 首个 h2；--ios-header-h）", `${r2(sat + 54 + 45.33)} · 组头文字顶 ${r2(sat + 54 + 18.67)}`, card1 ? `${r2(R(card1).top)} · 组头文字顶 ${r2(h1t)}` : "缺", !!card1 && Math.abs(R(card1).top - sat - 54 - 45.33) < 0.6 && Math.abs(h1t - sat - 54 - 18.67) < 0.6);
      const rowsAll = [...body().querySelectorAll(".stk-row")];
      const geo = rowsAll.map((r) => { const rr0 = R(r), im = R(r.querySelector("img, .noimg")), t = R(r.querySelector(".t")), s = R(r.querySelector(".s")), v = r.querySelector(".v");
        return { h: rr0.height, ix: im.left, iy: im.top - rr0.top, iw: im.width, ih: im.height, tx: t.left, ty: t.top - rr0.top, sx: s.left, sy: s.top - rr0.top, vr: v ? R(v).right : null, vc: v ? (R(v).top + R(v).bottom) / 2 - rr0.top : null }; });
      const bad3 = geo.filter((g) => Math.abs(g.h - 62) > 0.6 || Math.abs(g.ix - 40) > 0.6 || Math.abs(g.iy - 17) > 0.6 || Math.abs(g.iw - 28) > 0.1 || Math.abs(g.ih - 28) > 0.1 || Math.abs(g.tx - 83) > 0.6 || Math.abs(g.ty - 9) > 0.6 || Math.abs(g.sx - 83) > 0.6 || Math.abs(g.sy - 32.33) > 0.6 || (g.vr != null && (Math.abs(g.vr - 400) > 0.6 || Math.abs(g.vc - 31) > 0.6)));
      check(`库存 ⑤ 每行几何（${geo.length} 行）：高 62、图标 (40, +17, 28 × 28)、标题 (83, +9)、副标题 (83, +32.33)、右值右缘 400 且竖向居中 31（§4.2，AX-35 / AX-33d / AX-41）`, "全部合", bad3.length ? JSON.stringify(bad3[0]) : "全部合", geo.length === 7 && !bad3.length);
      const r0 = rowsAll[0], t0 = r0.querySelector(".t"), s0 = r0.querySelector(".s"), v0 = r0.querySelector(".v");
      check("库存 ⑤ 字号：标题 17、副标题 15、右值 17（§4.2）", "17 · 15 · 17", `${parseFloat(cs(t0).fontSize)} · ${parseFloat(cs(s0).fontSize)} · ${parseFloat(cs(v0).fontSize)}`, parseFloat(cs(t0).fontSize) === 17 && parseFloat(cs(s0).fontSize) === 15 && parseFloat(cs(v0).fontSize) === 17);
      col("库存 ⑤ 标题色 = label（§4.2）", C.label, cs(t0).color);
      if (C.sub) col("库存 ⑤ 副标题色 = (128,128,128)（设置两行行写死的灰，AX-35 ⑧；暗色待读）", C.sub, cs(s0).color);
      col("库存 ⑤ 右值色 = secondaryLabel（§4.2）", C.sec, cs(v0).color);
      const sp0 = cs(r0, "::after"), last = secs[0].querySelector(".stk-row:last-child"), rr0 = R(r0), c0r = R(card1);
      check("库存 ⑤ 分隔线：1 pt、x 83 → 400、每节末行没有（§4.2，AX-35 (83, y+61, 317, 1)）", "83 → 400 · 1 · 末行 none",
        `${r2(c0r.left + parseFloat(sp0.left))} → ${r2(c0r.right - parseFloat(sp0.right))} · ${parseFloat(sp0.height)} · 末行 ${cs(last, "::after").content}`,
        Math.abs(c0r.left + parseFloat(sp0.left) - 83) < 0.6 && Math.abs(c0r.right - parseFloat(sp0.right) - 400) < 0.6 && parseFloat(sp0.height) === 1 && cs(last, "::after").content === "none" && rr0.height > 0);
      col("库存 ⑤ 分隔线色 = separator（§4.2）", C.sep, sp0.backgroundColor);
      const foot = () => { const f = body().querySelector(".stk-foot"); return f ? f.innerText.split("\n") : []; };
      const f5 = foot();
      const want5 = ["12:34 从森空岛读取", "人份 = 材料库存 ÷ 一人所需（缺的先用资源箱补）", "一人所需 = 测试口径", "差 N = 补箱后不够一人份，还差 N（需 − 库存 − 箱）", "箱 N = 测试句", "k = 千"];
      check("库存 ⑤ 脚注：取自时刻 + 人份口径 + caliber + 差 N 口径 + 箱句 + 页上有 k 才写「k = 千」；数据没给延迟句就不写（§4.3，M4i）", want5.join(" / "), f5.join(" / "), f5.join("/") === want5.join("/"));
      /* ⑥ */
      rb.click();
      await answer({ games: [{ "错误": "超时" }] });
      const f6 = foot(), rowsNow = body().querySelectorAll(".stk-row").length;
      check("库存 ⑥ 点「刷新」→ 读失败、有旧数据：旧列表照显示、不灰化，脚注首行「HH:MM 读取的数据；这次没读到：<错误原文>」（§5）", "7 行 · 不透明度 1 · 12:34 读取的数据；这次没读到：超时",
        `${rowsNow} 行 · 不透明度 ${cs(body().querySelector(".stk-row")).opacity} · ${f6[0]}`, rowsNow === 7 && cs(body().querySelector(".stk-row")).opacity === "1" && f6[0] === "12:34 读取的数据；这次没读到：超时");
      /* ⑦ */
      rb.click();
      { const d7 = good({ lagNote: "测试延迟句" }); Object.assign(d7.games[0].rows[0], { have: 9999, box: 9999, need: 99999, short: 80003, servings: 0, origin: { 理智关卡: ["某关"] } }); await answer(d7); }
      await frames(1000, () => body().textContent.includes("箱 9,999"));
      wrapCheck("⑦ 四位数带箱带需", true);
      const f7 = foot();
      check("库存 ⑦ 数据带了延迟句才显示，在脚注末行（§4.3）", "测试延迟句 · 首行 12:34 从森空岛读取", `${f7[f7.length - 1]} · 首行 ${f7[0]}`, f7[f7.length - 1] === "测试延迟句" && f7[0] === "12:34 从森空岛读取");
      /* ⑧ */
      rb.click();
      await answer({ "取自": "12:35", games: [{ game: "终末地", "错误": "", rows: [] }] });
      const z = body().querySelector(".stk-zero");
      check("库存 ⑧ 读到了但 0 行：居中灰字「森空岛没有返回仓库数据。」宽 312 居中、17（§5，AX-34）", "森空岛没有返回仓库数据。 · 312 · 中 220 · 17",
        z ? `${z.textContent} · ${r2(R(z).width)} · 中 ${r2((R(z).left + R(z).right) / 2)} · ${parseFloat(cs(z).fontSize)}` : "缺",
        !!z && z.textContent === "森空岛没有返回仓库数据。" && Math.abs(R(z).width - 312) < 0.6 && Math.abs((R(z).left + R(z).right) / 2 - 220) < 0.6 && cs(z).textAlign === "center" && parseFloat(cs(z).fontSize) === 17);
      if (z) col("库存 ⑧ 空态灰字色 = systemGray（§5，AX-34）", C.grey, cs(z).color);
      /* ⑨ */
      S.reset(); rb.click();
      await answer({ games: [{ "错误": "没配森空岛" }] });
      const go = body().querySelector('.stk-empty button[data-act="phone"]');
      if (go) go.click();
      await frames(2000, () => !document.body.classList.contains("pushed") && tabOn() === "手机");
      const left = refreshBtn();
      check("库存 ⑨ 点「去手机页」→ 弹回、切到「手机」、「刷新」离开导航栏（§5）", "弹回 · 手机 · 无刷新", `${document.body.classList.contains("pushed") ? "仍推入" : "弹回"} · ${tabOn()} · ${left && cs(left).display !== "none" ? "刷新还在" : "无刷新"}`,
        !document.body.classList.contains("pushed") && tabOn() === "手机" && !(left && cs(left).display !== "none"));
    } finally {
      I.refresh = orig; S.reset();
      if (pend) pend({ games: [{ "错误": "验收结束" }] });
      if (document.body.classList.contains("pushed")) { const bk = document.querySelector("#subpage .pback"); if (bk) bk.click(); await frames(2000, () => !document.body.classList.contains("pushed")); }
      const t0 = tabs && tabs.querySelector(`button[data-tab="${startTab}"]`); if (t0 && tabOn() !== startTab) t0.click();
    }
  });
})();
