/* accept-textfit.js — 串3 (2号): list text wraps instead of ending in an ellipsis (textfit.css; the user 18:45).
   Originals: remote-ref/tools/uiprobe-cellcfg/cellcfg.json (UIListContentConfiguration numberOfLines 0 for cell / subtitleCell / valueCell / groupedHeader;
   valueCell stacked: value x = title x, full width, top = title bottom + 4) and UIListContentConfiguration.h:86 (side by side only "if there is sufficient space").
   Rows: (1) no rendered list text is set to one line with an ellipsis; (2) a short value row stays side by side; (3) a long value row stacks as measured;
   (4) a long title beside a switch wraps and the switch keeps its place; (5) a long nav value wraps under the title and the chevron stays centred at the trailing edge. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptTextfit(ctx) {
    const { check } = ctx;
    const frame = () => new Promise((r) => requestAnimationFrame(r));
    const one = [];
    for (const e of document.querySelectorAll("h2, .dname, .row > label, .row > .ro, .row.nav > .val, .stk-row .t")) { const cs = getComputedStyle(e); if (cs.whiteSpace === "nowrap" || cs.textOverflow === "ellipsis") one.push((e.className || e.tagName) + "「" + (e.textContent || "").trim().slice(0, 12) + "」"); }
    check("列表文字不省略（cell / valueCell / 组头 numberOfLines 0，cellcfg.json）：组头、设备名、行标题、行值、导航值、库存标题都不是单行省略", "0 处", `${one.length} 处${one.length ? " · " + one.slice(0, 6).join("、") : ""}`, one.length === 0);
    const g0 = [...document.querySelectorAll(".group")].filter((g) => g.getBoundingClientRect().width > 0 && g.querySelector(".row"))[0];
    if (!g0) { check("列表换行几何：页面上没有可见的列表组", "有组", "无", false); return; }
    const swSrc = document.querySelector(".row > .sw");
    const LONG = "库存 1,234,000 · 需 1,792,290 · 自选箱 112 个可补足缺口 · 按人份折算还差 0.4 人份的材料";   // cellcfg.swift:15, the probe's own string
    const g = document.createElement("div"); g.className = "group"; g.dataset.textfitProbe = "1";
    g.innerHTML = `<div class="row"><label>短标题</label><span class="ro short">12 条</span></div>`
      + `<div class="row"><label>中级作战记录</label><span class="ro short">${LONG}</span></div>`
      + `<div class="row"><label>${LONG}</label></div>`
      + `<div class="row nav"><label>中级作战记录</label><span class="val">${LONG}</span><i class="sf chev"></i></div>`;
    if (swSrc) g.children[2].appendChild(swSrc.cloneNode(true));
    g0.after(g); await frame(); await frame();
    try {
      const R = (e) => e.getBoundingClientRect(), [r1, r2, r3, r4] = g.children;
      { const l = R(r1.querySelector("label")), v = R(r1.querySelector(".ro")), row = R(r1), pr = parseFloat(getComputedStyle(r1).paddingRight);
        check("值行 · 空间够：标题与值同一行、值贴右（valueCell 并排）", "同行 · 右缘 = 行右 − 内距", `顶差 ${(v.top - l.top).toFixed(1)} · 右缘差 ${(row.right - pr - v.right).toFixed(1)}`, Math.abs(v.top - l.top) < 1 && Math.abs(row.right - pr - v.right) < 1); }
      { const l = R(r2.querySelector("label")), ve = r2.querySelector(".ro"), v = R(ve), lh = parseFloat(getComputedStyle(ve).lineHeight) || 20.33, n = Math.round(v.height / lh);
        check("值行 · 空间不够：值另起一行、与标题左齐、在标题下 4、换行不截断（cellcfg.json rows[3]：x 80 = 标题 x、y = 标题底 + 4、3 行）", "左齐 · 下 4 · 多行 · 不截断", `左差 ${(v.left - l.left).toFixed(1)} · 下 ${(v.top - l.bottom).toFixed(1)} · ${n} 行 · ${ve.scrollWidth > ve.clientWidth + 0.5 ? "截断" : "全显"}`,
          Math.abs(v.left - l.left) < 0.6 && Math.abs(v.top - l.bottom - 4) < 0.6 && n >= 2 && ve.scrollWidth <= ve.clientWidth + 0.5); }
      { const le = r3.querySelector("label"), l = R(le), sw = r3.querySelector(".sw"), lh = parseFloat(getComputedStyle(le).lineHeight) || 20.33, row = R(r3), s = sw && R(sw);
        check("开关行 · 长标题：标题在开关左侧换行，开关不掉行、在行中线上", "多行 · 标题右 ≤ 开关左 · 开关居中", sw ? `${Math.round(l.height / lh)} 行 · 右 ${(l.right - s.left).toFixed(1)} · 中线差 ${((s.top + s.bottom) / 2 - (row.top + row.bottom) / 2).toFixed(1)}` : "页面上没有开关可借",
          !!sw && Math.round(l.height / lh) >= 2 && l.right <= s.left + 0.5 && Math.abs((s.top + s.bottom) / 2 - (row.top + row.bottom) / 2) < 1); }
      { const l = R(r4.querySelector("label")), v = R(r4.querySelector(".val")), c = R(r4.querySelector(".chev")), row = R(r4), inset = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ios-chevron-inset")) || 20;
        check("导航值行 · 长值：值在标题下、左齐；箭头仍在右 20、整行竖中", "值下移左齐 · 箭头右 20 · 竖中", `左差 ${(v.left - l.left).toFixed(1)} · 下 ${(v.top - l.bottom).toFixed(1)} · 箭头右 ${(row.right - c.right).toFixed(1)} · 中线差 ${((c.top + c.bottom) / 2 - (row.top + row.bottom) / 2).toFixed(1)}`,
          Math.abs(v.left - l.left) < 0.6 && Math.abs(v.top - l.bottom - 4) < 0.6 && Math.abs(row.right - c.right - inset) < 0.6 && Math.abs((c.top + c.bottom) / 2 - (row.top + row.bottom) / 2) < 0.6); }
    } finally { g.remove(); }
  });
})();
