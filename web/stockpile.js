/* 库存 page (M4, user 2026-09-23 08:09), built to remote-mock/v4/inventory-plan.md:
   the pushed page behind the 终末地 tab's 「库存 ›」 row. For every material the newest
   six-star's full build uses: icon, name, 「库存 1,234 · 需 472」, and on the right how many
   builds the stock covers, 「2.6 人份」 (plan §4.3 as written; user 2026-09-23 08:23
   「2.6 人份也行，按原方案走」).

   Data: Inventory.refresh() (web/inventory.js) - the page signs its own 森空岛 request
   (calculate/user-game-data) with the session stored on this phone; the game machine
   being off does not matter. Need: web/data/need.json (scripts/mac/build-need-tables.py,
   calculate/rules values). Reads only on open and on 「刷新」; no timers.

   Sections = the rows' `group` (the use sections of need.json, data bd80492), in
   games[].groups order, else the order the file first names them (plan §4.1); rows
   without a group (materials this build does not use, the exp cards folded into
   干员经验 / 武器经验) are not shown. Inside a section: multiple ascending, ties by stock
   ascending, rows without a need last (§4.3).

   M4i (user 2026-09-23 09:20, three points): a row that covers one build drops 「需 N」 from
   its subtitle (「库存 6 + 箱 110 · 理智关卡」, right value 「x.x 人份」); only a short row
   keeps 「需 N」 and 「差 N」. Numbers from 10,000 up read in thousands, 22,639k (footnote
   「k = 千」). The box row is a conversion note, not a 人份: 「133 个 · 换成缺的材料用了
   131 个」, 「剩 2 个」; the footnote's 人份 line speaks of materials only.

   Self-select box (M4g; user 2026-09-23 09:05 「按照不足的资源用资源箱去折算。然后还不足的就
   标出来说不足，否则就算已经充足。然后折算的时候依旧按人数去算多少倍」): Inventory.applyBox
   (data 8c6b6b9) tops up the short rows; the right value reads the row's `short` (still
   short after the boxes → 「差 N」, covered → 「x.x 人份」 of (库存 + 箱) ÷ 需), a topped-up
   row's subtitle reads 「库存 6 + 箱 110 · 需 116」, and the box gets a last section of its
   own (reworded in M4i below). Footnote adds games[].box.note.

   How it is obtained: the end of the subtitle names the first non-empty list of the
   row's `origin` (采集 / 理智关卡 / 其它, the same order `origin.kind` is picked in;
   plan §10), e.g. 「库存 354 · 需 136 · 采集」. A subtitle wider than its column wraps and
   the row grows by one sub line per extra line — nothing is cut (OPEN.md 08:44 item, the
   data session's probe 09-23 17:18, remote-ref/tools/uiprobe-cellcfg/cellcfg.json:
   UIListContentConfiguration subtitleCell() secondaryTextProperties.numberOfLines = 0;
   only the sidebar cells are 1). Replaces M4c's one-line ellipsis and M4h's cut counts.
   The line height is the page's own row (AX-35), not the probe cell's 20 pt.

   Entry (the 终末地 row is view.js's, owned by 界面): Stockpile.open() - pushes through
   view.js's global openPage (Nav.open when nav.js is loaded). */
(function () {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  // 千分位 1,234 (plan §4.3); M4i (user 09-23 09:20 「大额…用k去表示」): from 10,000 up, rounded to
  // thousands with a k, 22,639,400 → 22,639k; the footnote says k = 千 when one is on the page
  let usedK = false;
  const num = (n) => {
    const x = Number(n || 0);
    if (Math.abs(x) < 10000) return x.toLocaleString("en-US");
    usedK = true;
    return Math.round(x / 1000).toLocaleString("en-US") + "k";
  };
  const mult = (x) => x.toFixed(1) + " 人份";                       // x is already floored to one decimal (Inventory.servingsOf)
  const BOX_SECTION = "资源箱";                                      // M4g: the box's own last section
  // plan §10 origin: {kind, 采集: [..], 理智关卡: [..], 其它: [..]}; kind is the first non-empty of these
  const originOf = (r) => (r.origin ? ["采集", "理智关卡", "其它"].find((k) => (r.origin[k] || []).length) || "" : "");
  let lastGood = null, lastErr = "";

  /* Geometry per plan §4.2 / §3 / §5; every value is a tokens.css variable except the
     刷新 button box, AX-11 Button「编辑」(358, 66, 58, 36) = nav top + 4, right inset 24.
     P4 (plan §5 first state): the loading row is a one-line cell (--ios-row-h 53.33, text x 40) with the page's
     UIActivityIndicatorView (.ai, index.html) 20 × 20 at x 380, i.e. 40 from the screen's right edge (tokens.css
     --ios-spinner-inset, probe); its vertical place is the flex centre — 待读 (not in the probe line).
     P4: the sections sit in #stockbody, so index.html's pushed-page rule for the first header (.page > .pbody > section > h2,
     text at the bar's bottom + --ios-header-text-top) missed them and the main page's `section:first-child > h2 {padding-top:10px}`
     won: the first card was 9 lower than bar + --ios-header-h. The same rule, one level deeper. */
  function style() {
    if (document.getElementById("stockpile-css")) return;
    const st = document.createElement("style");
    st.id = "stockpile-css";
    st.textContent = `
.stk-card{margin:0;background:var(--ios-card-bg);border-radius:var(--ios-card-radius);overflow:hidden}
.stk-row{position:relative;height:var(--ios-row2-h)}
.stk-row img,.stk-row .noimg{position:absolute;left:var(--ios-row2-icon-x);top:17px;width:var(--ios-row2-icon);height:var(--ios-row2-icon);object-fit:contain}
.stk-row .t{position:absolute;left:var(--ios-row2-text-x);top:var(--ios-row2-title-top);right:calc(20px + var(--stk-vw, 0px));font-size:var(--ios-body-size);line-height:var(--ios-body-lh);color:var(--ios-label);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stk-row .s{position:absolute;left:var(--ios-row2-text-x);top:var(--ios-row2-sub-top);right:calc(20px + var(--stk-vw, 0px));font-size:var(--ios-sub-size);line-height:var(--ios-sub-lh);color:var(--ios-settings-subtitle);white-space:normal;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.stk-row .s .o{white-space:pre-wrap}
.stk-row .v{position:absolute;right:20px;top:50%;transform:translateY(-50%);font-size:var(--ios-body-size);line-height:var(--ios-body-lh);color:var(--ios-secondary-label);white-space:nowrap;font-variant-numeric:tabular-nums}
.stk-row:not(:last-child)::after{content:"";position:absolute;left:var(--ios-row2-text-x);right:20px;bottom:0;height:var(--ios-separator-h);background:var(--ios-separator)}
.stk-foot{margin:0;padding:var(--ios-footer-text-top) 20px 0;font-size:var(--ios-footnote-size);line-height:var(--ios-footnote-lh);color:var(--ios-secondary-label)}
.stk-load{position:relative;height:var(--ios-row-h);display:flex;align-items:center;padding:0 20px;font-size:var(--ios-body-size);color:var(--ios-label)}
.stk-load .ai{position:absolute;right:calc(var(--ios-spinner-inset) - var(--ios-card-inset))}
#stockbody > section:first-child > h2{padding-top:calc(var(--ios-header-text-top) - var(--ios-group-gap))}
.stk-empty{text-align:center;padding:48px 20px}
.stk-empty .ttl{font-size:var(--ios-empty-title-size);font-weight:600;color:var(--ios-label);margin-top:8px}
.stk-empty .txt{font-size:var(--ios-sub-size);line-height:var(--ios-sub-lh);color:var(--ios-secondary-label);margin:6px auto 14px;max-width:var(--ios-empty-caption-w)}
.stk-empty button{height:var(--ios-empty-button-h);padding:0 18px;border-radius:calc(var(--ios-empty-button-h) / 2);border:0;background:var(--ios-tint);color:#fff;font-size:var(--ios-sub-size)}
.stk-zero{margin:40px auto;max-width:var(--ios-empty-caption-w);text-align:center;font-size:var(--ios-body-size);color:var(--ios-empty-text)}
.pnav .stk-refresh{position:absolute;top:4px;right:24px;width:58px;height:36px;border:0;background:none;padding:0;font-size:var(--ios-body-size);font-weight:500;color:var(--ios-tint)}
.pnav .stk-refresh:disabled{opacity:var(--ios-disabled-opacity)}
#subpage:not(:has(#stockbody)) .stk-refresh{display:none}`;
    document.head.appendChild(st);
  }

  function rowHtml(r) {
    // bbs.hycdn.cn answers 403 to any off-site Referer (200 with none), so the icon is fetched
    // without one; referrerpolicy on <img> is in Safari / iOS Safari since 14 (MDN compat data)
    const icon = r.icon ? `<img src="${esc(r.icon)}" alt="" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">` : `<span class="noimg"></span>`;
    const have = r.box > 0 ? `库存 ${num(r.have)} + 箱 ${num(r.box)}` : `库存 ${num(r.have)}`;
    const from = originOf(r);
    // user 09-23 08:40: short of one build reads 「差 N」, not 「0.x 人份」; M4g: N = `short`
    // (need − have − box, after the self-select box); a row the box covers shows its 人份
    const short = r.short != null ? r.short : Math.max(0, r.need - r.have);
    // M4i (user 09-23 09:20 「满足了一个人用的份额之外，还在显示需要多少」): 需 N only on a short row
    const sub = `<span class="n">${r.need == null || short <= 0 ? have : `${have} · 需 ${num(r.need)}`}</span>` + (from ? `<span class="o"> · ${esc(from)}</span>` : "");
    const v = r.servings == null ? "" : short > 0 ? `差 ${num(short)}` : mult(r.servings);
    return `<div class="stk-row">${icon}<span class="t">${esc(r.name)}</span>`
      + `<span class="s">${sub}</span>${v ? `<span class="v">${v}</span>` : ""}</div>`;
  }
  /* M4i (user 09-23 09:20 「资源箱为什么也要算人数」): the box is no one's need, only what it
     was turned into: 「133 个 · 换成缺的材料用了 131 个」, 「剩 2 个」 */
  function boxRowHtml(r, box) {
    const icon = r.icon ? `<img src="${esc(r.icon)}" alt="" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">` : `<span class="noimg"></span>`;
    return `<div class="stk-row">${icon}<span class="t">${esc(box.name || r.name)}</span>`
      + `<span class="s"><span class="n">${num(r.have)} 个 · 换成缺的材料用了 ${num(r.boxUsed)} 个</span></span><span class="v">剩 ${num(r.boxLeft)} 个</span></div>`;
  }
  const order = (a, b) => (a.servings == null) - (b.servings == null) || (a.servings || 0) - (b.servings || 0) || a.have - b.have;

  function listHtml(g, d, err) {
    const groups = [];
    usedK = false;
    for (const r of g.rows || []) {
      if (!r.group) continue;
      let sec = groups.find((x) => x.name === r.group);
      if (!sec) groups.push(sec = { name: r.group, rows: [] });
      sec.rows.push(r);
    }
    if (!groups.length) return `<p class="stk-zero">森空岛没有返回仓库数据。</p>`;
    const rank = (n) => { const i = (g.groups || []).indexOf(n); return i < 0 ? Infinity : i; };
    groups.sort((a, b) => rank(a.name) - rank(b.name));             // stable: unnamed ones keep file order
    let secs = groups.map((s) => `<section><h2>${esc(s.name)}</h2><div class="stk-card">${s.rows.slice().sort(order).map(rowHtml).join("")}</div></section>`).join("");
    const box = g.box && g.box.id ? g.box : null;
    const own = box && (g.rows || []).find((r) => r.id === box.id);
    if (own && own.boxUsed != null && own.have > 0)
      secs += `<section><h2>${BOX_SECTION}</h2><div class="stk-card">${boxRowHtml(own, box)}</div></section>`;
    const boxed = (g.rows || []).some((r) => r.group && r.box > 0);
    const first = err ? `${esc(d["取自"])} 读取的数据；这次没读到：${esc(err)}` : `${esc(d["取自"])} 从森空岛读取`;
    const lag = g.lagNote ? `<br>${esc(g.lagNote)}` : "";
    const boxNote = box && box.note ? `<br>${esc(box.note)}` : "";
    // M4i: 人份 speaks of materials only; the box line (games[].box.note) does not
    return secs + `<p class="stk-foot">${first}<br>人份 = 材料库存 ÷ 一人所需${boxed ? "（缺的先用资源箱补）" : ""}`
      + (g.caliber ? `<br>一人所需 = ${esc(g.caliber)}` : "")
      + `<br>差 N = ${boxed ? "补箱后" : "库存"}不够一人份，还差 N（需 − 库存${boxed ? " − 箱" : ""}）${boxNote}${usedK ? "<br>k = 千" : ""}${lag}</p>`;
  }
  function emptyHtml(title, text, btn, act) {
    return `<div class="stk-empty"><svg width="60" height="60" viewBox="0 0 24 24" fill="none" stroke="var(--ios-secondary-label)" stroke-width="1.2" stroke-linejoin="round"><path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/></svg>`
      + `<div class="ttl">${esc(title)}</div><div class="txt">${esc(text)}</div><button type="button" data-act="${act}">${esc(btn)}</button></div>`;
  }

  function paint(d) {
    const el = document.getElementById("stockbody");
    if (!el) return;
    const g = d && d.games && d.games[0];
    const err = g ? g["错误"] : "没有读数";
    if (g && !err) { lastGood = d; lastErr = ""; }
    else lastErr = err;
    if (lastGood) el.innerHTML = listHtml(lastGood.games[0], lastGood, lastErr);
    else if (err === "没配森空岛") el.innerHTML = emptyHtml("没配森空岛", "库存从森空岛读；在「手机」页填好密钥串再来。", "去手机页", "phone");
    else el.innerHTML = emptyHtml("读不到库存", err, "重试", "retry");
    // plan §4.2: text column (title and subtitle) max width = 400 − 83 − value width − 8 (--ios-value-gap); the value's
    // width is measured, not estimated from its character count
    for (const v of el.querySelectorAll(".stk-row .v")) v.parentNode.style.setProperty("--stk-vw", `calc(${v.getBoundingClientRect().width}px + var(--ios-value-gap))`);
    // a wrapped subtitle (numberOfLines 0): the row grows by the extra lines (read after the value width is set, since it narrows the column)
    for (const sub of el.querySelectorAll(".stk-row .s")) { const lh = parseFloat(getComputedStyle(sub).lineHeight), n = lh > 0 ? Math.max(1, Math.round(sub.getBoundingClientRect().height / lh)) : 1;
      if (n > 1) sub.parentNode.style.height = `calc(var(--ios-row2-h) + ${n - 1} * var(--ios-sub-lh))`; else sub.parentNode.style.removeProperty("height"); }
    const b = el.querySelector("[data-act]");
    if (b) b.onclick = () => (b.dataset.act === "phone" ? toPhone() : load(true));
  }
  function toPhone() {
    // P4: through the back button itself, so its once-listener takes 「刷新」 along (Nav.back() alone left it in the bar)
    const bk = document.querySelector("#subpage .pback");
    if (bk) bk.click(); else if (window.Nav && Nav.back) Nav.back();
    const t = document.querySelector('button[data-tab="手机"]');
    if (t) t.click();
  }
  function busy(on) {
    const b = document.querySelector("#subpage .stk-refresh");
    if (b) b.disabled = on;
  }
  async function load(force) {
    const el = document.getElementById("stockbody");
    if (el && !lastGood) el.innerHTML = `<div class="stk-card"><div class="stk-load">正在从森空岛读取…<span class="ai on">${"<i></i>".repeat(8)}</span></div></div>`;
    busy(true);
    try { paint(await Inventory.refresh(force)); }
    catch (e) { paint({ games: [{ "错误": e.message }] }); }
    finally { busy(false); }
  }
  function open(openPage = window.openPage) {
    style();
    openPage("库存", `<div id="stockbody"></div>`);
    const bar = document.querySelector("#subpage .pnav");
    if (bar && !bar.querySelector(".stk-refresh")) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "stk-refresh"; b.textContent = "刷新";
      b.onclick = () => load(true);
      bar.appendChild(b);
      /* #subpage is shared with the 回执 page: the button leaves with this page (P4: a pop that is not a click on the back
         button — the edge swipe, nav-edge.js — leaves it in the bar; the stylesheet hides it on any page without #stockbody) */
      const back = bar.querySelector(".pback");
      if (back) back.addEventListener("click", () => b.remove(), { once: true });
    }
    load(false);
  }

  // reset: forget the last good read (web/accept-stockpile.js walks the no-data states first; nothing on the page calls it)
  window.Stockpile = { open, load, listHtml, reset: () => { lastGood = null; lastErr = ""; } };
})();
