/* 库存 page (M4, user 2026-09-23 08:09), built to remote-mock/v4/inventory-plan.md:
   the pushed page behind the 终末地 tab's 「库存 ›」 row. For every material the newest
   six-star's full build uses: icon, name, 「库存 1,234 · 需 472」, and on the right how many
   builds the stock covers, 「2.6x」 (user's wording 2026-09-23; plan §4.3 said 「人份」).

   Data: Inventory.refresh() (web/inventory.js) - the page signs its own 森空岛 request
   (calculate/user-game-data) with the session stored on this phone; the game machine
   being off does not matter. Need: web/data/need.json (scripts/mac/build-need-tables.py,
   calculate/rules values). Reads only on open and on 「刷新」; no timers.

   Sections = the rows' `group`, in the order the file first names them (plan §4.1);
   rows without a group (materials this build does not use, the exp cards folded into
   干员经验 / 武器经验) are not shown. Inside a section: multiple ascending, ties by stock
   ascending, rows without a need last (§4.3).

   Entry (the 终末地 row is view.js's, owned by 界面): Stockpile.open() - pushes through
   view.js's global openPage (Nav.open when nav.js is loaded). */
(function () {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const num = (n) => Number(n || 0).toLocaleString("en-US");        // 千分位 1,234 (plan §4.3)
  const mult = (x) => x.toFixed(1) + "x";                           // x is already floored to one decimal (Inventory.servingsOf)
  let lastGood = null, lastErr = "";

  /* Geometry per plan §4.2 / §3 / §5; every value is a tokens.css variable except the
     刷新 button box, AX-11 Button「编辑」(358, 66, 58, 36) = nav top + 4, right inset 24. */
  function style() {
    if (document.getElementById("stockpile-css")) return;
    const st = document.createElement("style");
    st.id = "stockpile-css";
    st.textContent = `
.stk-card{margin:0 var(--ios-card-inset);width:var(--ios-card-w);max-width:calc(100% - 2 * var(--ios-card-inset));background:var(--ios-card-bg);border-radius:var(--ios-card-radius);overflow:hidden}
.stk-row{position:relative;height:var(--ios-row2-h)}
.stk-row img,.stk-row .noimg{position:absolute;left:calc(var(--ios-row2-icon-x) - var(--ios-card-inset));top:17px;width:var(--ios-row2-icon);height:var(--ios-row2-icon);object-fit:contain}
.stk-row .t{position:absolute;left:calc(var(--ios-row2-text-x) - var(--ios-card-inset));top:var(--ios-row2-title-top);right:calc(20px + var(--stk-vw, 0px));font-size:var(--ios-body-size);line-height:var(--ios-body-lh);color:var(--ios-label);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stk-row .s{position:absolute;left:calc(var(--ios-row2-text-x) - var(--ios-card-inset));top:var(--ios-row2-sub-top);right:20px;font-size:var(--ios-sub-size);line-height:var(--ios-sub-lh);color:var(--ios-settings-subtitle);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}
.stk-row .v{position:absolute;right:20px;top:50%;transform:translateY(-50%);font-size:var(--ios-body-size);line-height:var(--ios-body-lh);color:var(--ios-secondary-label);white-space:nowrap;font-variant-numeric:tabular-nums}
.stk-row:not(:last-child)::after{content:"";position:absolute;left:calc(var(--ios-row2-text-x) - var(--ios-card-inset));right:20px;bottom:0;height:var(--ios-separator-h);background:var(--ios-separator)}
.stk-foot{margin:0 var(--ios-card-inset);padding:var(--ios-footer-text-top) 20px 0;font-size:var(--ios-footnote-size);line-height:var(--ios-footnote-lh);color:var(--ios-secondary-label)}
.stk-load{position:relative;height:var(--ios-row2-h);display:flex;align-items:center;padding:0 20px;font-size:var(--ios-body-size);color:var(--ios-label)}
.stk-empty{text-align:center;padding:48px 20px}
.stk-empty .ttl{font-size:var(--ios-empty-title-size);font-weight:600;color:var(--ios-label);margin-top:8px}
.stk-empty .txt{font-size:var(--ios-sub-size);line-height:var(--ios-sub-lh);color:var(--ios-secondary-label);margin:6px auto 14px;max-width:var(--ios-empty-caption-w)}
.stk-empty button{height:var(--ios-empty-button-h);padding:0 18px;border-radius:calc(var(--ios-empty-button-h) / 2);border:0;background:var(--ios-tint);color:#fff;font-size:var(--ios-sub-size)}
.stk-zero{margin:40px auto;max-width:var(--ios-empty-caption-w);text-align:center;font-size:var(--ios-body-size);color:var(--ios-empty-text)}
.pnav .stk-refresh{position:absolute;top:4px;right:24px;width:58px;height:36px;border:0;background:none;padding:0;font-size:var(--ios-body-size);font-weight:500;color:var(--ios-tint)}
.pnav .stk-refresh:disabled{opacity:var(--ios-disabled-opacity)}`;
    document.head.appendChild(st);
  }

  function rowHtml(r) {
    const icon = r.icon ? `<img src="${esc(r.icon)}" alt="" onerror="this.style.visibility='hidden'">` : `<span class="noimg"></span>`;
    const sub = r.need == null ? `库存 ${num(r.have)}` : `库存 ${num(r.have)} · 需 ${num(r.need)}`;
    const v = r.servings == null ? "" : mult(r.servings);
    return `<div class="stk-row" style="--stk-vw:${v ? v.length * 10 + 8 : 0}px">${icon}<span class="t">${esc(r.name)}</span>`
      + `<span class="s">${sub}</span>${v ? `<span class="v">${v}</span>` : ""}</div>`;
  }
  const order = (a, b) => (a.servings == null) - (b.servings == null) || (a.servings || 0) - (b.servings || 0) || a.have - b.have;

  function listHtml(g, d, err) {
    const groups = [];
    for (const r of g.rows || []) {
      if (!r.group) continue;
      let sec = groups.find((x) => x.name === r.group);
      if (!sec) groups.push(sec = { name: r.group, rows: [] });
      sec.rows.push(r);
    }
    if (!groups.length) return `<p class="stk-zero">森空岛没有返回仓库数据。</p>`;
    const secs = groups.map((s) => `<section><h2>${esc(s.name)}</h2><div class="stk-card">${s.rows.slice().sort(order).map(rowHtml).join("")}</div></section>`).join("");
    const first = err ? `${esc(d["取自"])} 读取的数据；这次没读到：${esc(err)}` : `${esc(d["取自"])} 从森空岛读取`;
    const lag = g.lagNote ? `<br>${esc(g.lagNote)}` : "";
    return secs + `<p class="stk-foot">${first}<br>倍数 = 库存 ÷ ${esc(g.caliber || "")}${lag}</p>`;
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
    const b = el.querySelector("[data-act]");
    if (b) b.onclick = () => (b.dataset.act === "phone" ? toPhone() : load(true));
  }
  function toPhone() {
    if (window.Nav && Nav.back) Nav.back(); else { const bk = document.querySelector("#subpage .pback"); if (bk) bk.click(); }
    const t = document.querySelector('button[data-tab="手机"]');
    if (t) t.click();
  }
  function busy(on) {
    const b = document.querySelector("#subpage .stk-refresh");
    if (b) b.disabled = on;
  }
  async function load(force) {
    const el = document.getElementById("stockbody");
    if (el && !lastGood) el.innerHTML = `<div class="stk-card"><div class="stk-load">正在从森空岛读取…</div></div>`;
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
      /* #subpage is shared with the 回执 page: the button leaves with this page */
      const back = bar.querySelector(".pback");
      if (back) back.addEventListener("click", () => b.remove(), { once: true });
    }
    load(false);
  }

  window.Stockpile = { open, load, listHtml };
})();
