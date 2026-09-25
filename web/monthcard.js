/* 月卡 (user 2026-09-26 02:47, spec ~/Money/styl-work/BOARD/月卡到期提示-规格.md): one row per game on the 状态 page, pushing a
   page where a top-up (「充值了 N 次」) or the day count shown in the game (「游戏里显示还剩 X 天」) is registered.

   Data: relay.月卡 = { 明日方舟: { 最后领取: "2026-09-29", 还剩: 3, 已过期: false }, … } (spec 「接口」, 中继一 09-26 02:51); a game never
   registered is absent. The relay owns the dates: this page only shows them and sends
     { action: "monthcard", game, add: N }   N 1–12, each one 30 days
     { action: "monthcard", game, left: X }  X 0–400, the 「还剩 X 天」 the game shows
   The alert before sending previews the new last day with the spec's rule (§2: not expired → last + 30 × N; expired / never registered →
   the day of registering is day 1, so today + 30 × N − 1; left X → today + X); the receipt and the next snapshot are what count.

   Controls (iOS 26 Settings forms): the rows are .row.nav (chevron → push); 「充值了 N 次」 is a UIStepper row — probe uiprobe-list.json
   UIStepper 94 × 32 at the cell's right inset 20, halves 46.33 / 46.67, minus bar 13.33 × 2 at (17, 15), plus 13.33 × 13.33 at (63.67, 9.33),
   divider 1 × 24 at (46.67, 4) in rgb(60 60 67 / .298) = tertiaryLabel. The capsule fill is drawn by SwiftUI and is not in the probe:
   tertiarySystemFill (近似). 「游戏里显示还剩」 is the page's numeric text field (index.html .row input.short). The send is a blue action row
   (.acts button, the page's own). Entry: view.js render() adds MonthCard.section(relay) after the 机器 section (动效's line). */
(() => {
  const GAMES = ["明日方舟", "终末地", "鸣潮"];   // the three names the relay takes (spec 「接口」)
  const DAYS = 30;   // one purchase: PRTS 月卡兑换凭证 / PS Store UB0018-PPSA18538_00-ZMDPS5GL0MONTHLY / 鸣潮 商城说明 (spec 「查到的事实」)
  const MAX_ADD = 12, MAX_LEFT = 400;

  const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });   // the relay counts days in Shanghai time
  const plus = (iso, n) => { const d = new Date(iso + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const md = (iso) => `${+iso.slice(5, 7)}月${+iso.slice(8, 10)}日`;   // the page's date form (AX-11 「2026年9月17日」 without the year; receipts page)
  const valid = (e) => e && /^\d{4}-\d\d-\d\d$/.test(String(e["最后领取"] || ""));
  const expired = (e) => !!e["已过期"] || Number(e["还剩"]) < 0;
  const line = (e) => !valid(e) ? "未登记" : expired(e) ? "已过期" : `最后一次领取：${md(e["最后领取"])}（还剩 ${e["还剩"]} 天）`;
  const tone = (e) => !valid(e) ? "" : expired(e) ? " mc-bad" : Number(e["还剩"]) <= 5 ? " mc-soon" : "";   // 5: the reminder starts 5 days before (spec §4)
  const sfx = (name, cls) => (window.sf ? window.sf(name, cls) : "");

  let relayNow = {};
  const entry = (g) => ((relayNow || {})["月卡"] || {})[g];

  (function css() {
    if (document.getElementById("mc-css")) return;
    const st = document.createElement("style"); st.id = "mc-css";
    st.textContent = `
.row .mc-sub{display:block;color:var(--ios-settings-subtitle);font-size:var(--ios-sub-size);line-height:var(--ios-sub-lh);margin-top:1px;white-space:normal}   /* index.html .row .hint, under another name: layoutTabs moves every label > .hint to the footer, and this line is data, not an explanation */
.row .mc-soon{color:var(--ios-orange)}
.row .mc-bad{color:var(--bad)}
.mc-step{flex:none;display:flex;align-items:center;width:var(--ios-stepper-w);height:var(--ios-stepper-h);border-radius:calc(var(--ios-stepper-h) / 2);background:var(--ios-tertiary-fill);position:relative;overflow:hidden}
.mc-step button{flex:1;height:100%;border:0;margin:0;padding:0;background:none;display:flex;align-items:center;justify-content:center;touch-action:manipulation;-webkit-tap-highlight-color:transparent}
.mc-step button:active{background:var(--ios-tertiary-fill)}
.mc-step button i{display:block;background:var(--ios-label)}
.mc-step button[disabled] i{background:var(--ios-tertiary-label)}
.mc-step .mn i{width:13.33px;height:2px;border-radius:1px}
.mc-step .pl i{width:13.33px;height:13.33px;-webkit-mask:linear-gradient(#000,#000) center/100% 2px no-repeat,linear-gradient(#000,#000) center/2px 100% no-repeat;mask:linear-gradient(#000,#000) center/100% 2px no-repeat,linear-gradient(#000,#000) center/2px 100% no-repeat;border-radius:1px}
.mc-step::after{content:"";position:absolute;left:46.67px;top:4px;width:1px;height:24px;border-radius:.5px;background:var(--ios-tertiary-label)}
.row .mc-days{display:flex;align-items:center;gap:6px;flex:none}
.row .mc-days input{min-width:64px;max-width:80px}`;
    document.head.appendChild(st);
  })();

  /* the 状态 page's group: one row per game */
  function section(relay) {
    relayNow = relay || {};
    refreshPage();
    return `<section><h2>月卡</h2>${GAMES.map((g) => {
      const e = entry(g);
      return `<div class="row nav" data-page="monthcard" data-game="${g}"><label>${g}<span class="mc-sub${tone(e)}">${line(e)}</span></label>${sfx("chevron.right", "chev")}</div>`;
    }).join("")}</section>`;
  }

  function statusRows(g) {
    const e = entry(g);
    if (!valid(e)) return `<div class="row"><label>还没登记<span class="mc-sub">买过月卡的话，用下面任一种登记一次</span></label></div>`;
    return `<div class="row"><label>最后一次领取</label><span class="ro short">${md(e["最后领取"])}</span></div>
      <div class="row"><label>还剩</label><span class="ro short${tone(e)}">${expired(e) ? "已过期" : e["还剩"] + " 天"}</span></div>`;
  }

  function pageHtml(g) {
    return `<div id="mcbody" data-game="${g}">
      <section><div class="group" id="mcstat">${statusRows(g)}</div>
        <div class="foot"><p>有效期内每天登录领一次；还剩 1 天＝明天登录那次是最后一次领取。还剩 5 天起每天提醒一次。</p></div></section>
      <section><h2>登记充值</h2><div class="group">
        <div class="row"><label id="mcn">充值了 1 次</label>
          <span class="mc-step"><button type="button" class="mn" aria-label="减一次" disabled><i></i></button><button type="button" class="pl" aria-label="加一次"><i></i></button></span></div>
        <div class="acts"><button type="button" id="mcadd">登记</button></div></div>
        <div class="foot"><p>付完钱在这里登记。买一次加 ${DAYS} 天，接在最后一次领取日后面；已经过期的从登记当天算第 1 天。</p></div></section>
      <section><h2>按游戏里的天数对准</h2><div class="group">
        <div class="row"><label>游戏里显示还剩</label><span class="mc-days"><input type="text" class="short" id="mcleft" inputmode="numeric" pattern="[0-9]*" placeholder="天数" autocomplete="off"><span class="ro short">天</span></span></div>
        <div class="acts"><button type="button" id="mcset">对准</button></div></div>
        <div class="foot"><p>第一次用或者日期对不上时，照游戏里显示的「还剩 X 天」填。</p></div></section>
    </div>`;
  }

  function refreshPage() {
    const body = document.getElementById("mcbody"), st = document.getElementById("mcstat");
    if (body && st) { const h = statusRows(body.dataset.game); if (st.innerHTML !== h) st.innerHTML = h; }
  }

  /* spec §2 */
  function after(g, add) {
    const e = entry(g);
    return valid(e) && !expired(e) ? plus(e["最后领取"], DAYS * add) : plus(today(), DAYS * add - 1);
  }

  async function sendOrder(body, okText) {
    if (window.oneShot) return window.oneShot(body, okText);
    try { await window.send(body); } catch (err) { if (window.toast) window.toast("发不出去：" + err.message); }
  }

  function open(g, openPage = window.openPage) {
    if (!GAMES.includes(g) || !openPage) return;
    openPage(`${g}月卡`, pageHtml(g));
    const body = document.getElementById("mcbody"); if (!body) return;
    let n = 1;
    const lab = body.querySelector("#mcn"), mn = body.querySelector(".mc-step .mn"), pl = body.querySelector(".mc-step .pl");
    const set = (v) => { n = Math.max(1, Math.min(MAX_ADD, v)); lab.textContent = `充值了 ${n} 次`; mn.disabled = n <= 1; pl.disabled = n >= MAX_ADD; };
    mn.onclick = () => set(n - 1); pl.onclick = () => set(n + 1);
    body.querySelector("#mcadd").onclick = async () => {
      const to = after(g, n);
      if (!(await window.ask(`登记充值 ${n} 次？`, `${g}月卡加 ${DAYS * n} 天，最后一次领取改到 ${md(to)}。`, "登记"))) return;
      await sendOrder({ action: "monthcard", game: g, add: n }, `已登记${g}月卡充值 ${n} 次`);
      set(1);
    };
    const inp = body.querySelector("#mcleft");
    body.querySelector("#mcset").onclick = async () => {
      const s = String(inp.value || "").trim().replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
      if (!/^\d{1,3}$/.test(s) || +s > MAX_LEFT) { if (window.toast) window.toast(`填 0 到 ${MAX_LEFT} 的整数天数`); inp.focus(); return; }
      const x = +s;
      if (!(await window.ask(`对准为还剩 ${x} 天？`, `${g}月卡最后一次领取改到 ${md(plus(today(), x))}。`, "对准"))) return;
      await sendOrder({ action: "monthcard", game: g, left: x }, `已对准${g}月卡`);
      inp.value = ""; inp.blur();
    };
  }

  /* the rows are redrawn on every render: one delegated listener on the live page (topbar.js's pocket copies are not #app) */
  document.addEventListener("click", (e) => {
    const r = e.target.closest && e.target.closest('#app .row.nav[data-page="monthcard"]');
    if (r) open(r.dataset.game);
  });

  window.MonthCard = { section, open, line, after };
})();
