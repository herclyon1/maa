/* accept-page.js — the page's own rows (界面): the static structure / token rows that were accept.js's "page" sections (root font, colours, cards,
   rows, headers, footers, the device card, the state colours on synthetic controls, the value row and the sheet's static geometry, theme-color) and
   the page-behaviour interactions (Stamina placeholders, receipts + the pushed page, the HH:MM input, the late view.js iframe, no sync confirm()).
   S4-tags.md (e): release-only — the daily batch skips this file; ?layer=release runs it first (the static rows measure the untouched page).
   Split out of accept.js 2026-09-20 (BOARD 收尾单 ②); the row texts and expected values are unchanged. */
(function () {
  if (!window.ACCEPT) return;
  ACCEPT.add(async function acceptPage(ctx) {
    const { check, num, col, sleep, settle, raf, sec, segRest, tabRest, fadeRest, at, pev, cs, px, T, dark, near, rgb, same, fmt, satTop, varColor, probe, q, bs, onText, thisShift, R } = ctx;
    sec("static", { layer: "release-only" });
  const root = px(cs(document.documentElement).fontSize);
  num("根字号 17（--ios-body-size）", 17, root, 0.01);
  num("正文行框 20.33（--ios-body-lh）", 20.33, px(cs(document.body).lineHeight), 0.05);
  const ff = cs(document.body).fontFamily;
  check("字体栈含 -apple-system 或 PingFang（--ios-font）", "是", /-apple-system|PingFang/i.test(ff) ? "是" : ff.slice(0, 40), /-apple-system|PingFang/i.test(ff));
  col("tint（--ios-tint）", T.tint, varColor("--accent", probe));
  col("蓝字行 link（--ios-link）", T.link, varColor("--link", probe));
  col("页底色（--ios-grouped-bg）", T.bg, cs(document.body).backgroundColor);

  const main = document.querySelector("main");
  if (main) num("卡片距屏边 20（--ios-card-inset）", 20, px(cs(main).paddingLeft));
  const group = document.querySelector("section .group:not(.tiles):not(.nums):not(.devcard):not(.notice)");
  if (group) {
    num("卡片圆角 26（--ios-card-radius）", 26, px(cs(group).borderTopLeftRadius));
    col("卡片底色（--ios-card-bg）", T.card, cs(group).backgroundColor);
    const r = group.getBoundingClientRect();
    num("卡片左边 = 20", 20, r.left);
    num("卡片宽 = 视口 − 40", innerWidth - 40, r.width);
  }
  const row = document.querySelector(".row:has(> .sw), .row:has(> select)") || document.querySelector(".row");
  if (row) {
    num("行高 ≥ 53.33（--ios-row-h）", 53.33, Math.min(row.getBoundingClientRect().height, 53.33));
    num("行左内边距 20（--ios-row-text-x）", 20, px(cs(row).paddingLeft));
    const a = cs(row, "::after");
    const sy = /matrix\([^,]+,[^,]+,[^,]+,\s*([\d.]+)/.exec(a.transform);
    num("分隔线 1.0 pt（--ios-separator-h；探针 1.0，不是 1/3）", 1, px(a.height) * (sy ? parseFloat(sy[1]) : 1), 0.02);
    col("分隔线色（--ios-separator）", T.sep, a.backgroundColor);
    num("分隔线左缩进 20（--ios-separator-inset-l）", 20, px(a.left));
    num("分隔线右缩进 20（--ios-separator-inset-r）", 20, px(a.right));
  }
  const sw = document.querySelector(".sw");
  if (sw) {
    const r = sw.getBoundingClientRect();
    num("开关宽 63（--ios-switch-w）", 63, r.width); num("开关高 28（--ios-switch-h）", 28, r.height);
    num("开关圆角 14（--ios-switch-radius）", 14, px(cs(sw.querySelector("span")).borderTopLeftRadius));
    const knob = cs(sw.querySelector("span"), "::after");
    num("开关圆钮宽 37（--ios-switch-knob-w）", 37, px(knob.width)); num("开关圆钮高 24（--ios-switch-knob-h）", 24, px(knob.height));
    const rr = sw.closest(".row");
    if (rr) num("开关距卡片右边 18（--ios-switch-inset）", 18, rr.getBoundingClientRect().right - r.right);
  }
  /* A plain header: not the first section (10 under the large title, 待 tokens) and
     not one right after a footer (the footer already carries the group gap). */
  const h2 = [...document.querySelectorAll("section h2")].find((h) => {
    const sec = h.parentElement, prev = sec.previousElementSibling;
    if (!prev || prev.tagName !== "SECTION") return false;
    return !(prev.lastElementChild && prev.lastElementChild.classList.contains("foot"));
  });
  if (h2) {
    const c = cs(h2);
    num("段头字号 17（--ios-body-size）", 17, px(c.fontSize), 0.05); check("段头字重 600（--ios-headline-weight）", 600, c.fontWeight, String(c.fontWeight) === "600");
    num("段头上边距 18.67（--ios-header-text-top）", 18.67, px(c.paddingTop), 0.05);
    num("段头下边距 6.33（45.33 − 18.67 − 20.33：--ios-header-h）", 6.33, px(c.paddingBottom), 0.05);
    num("段头文字内缩 20（--ios-row-text-x）", 20, px(c.paddingLeft));
    col("段头色 secondaryLabel（--ios-secondary-label）", T.dim, c.color);
  }
  /* The footer under the number tiles sits 8 below them (tiles have no card edge); measure a plain one. */
  const foot = [...document.querySelectorAll("section .foot")].find((f) => !(f.previousElementSibling && f.previousElementSibling.classList.contains("nums")));
  if (foot) {
    const c = cs(foot);
    num("段尾字号 13（--ios-footnote-size）", 13, px(c.fontSize), 0.05); num("段尾行框 15.67（--ios-footnote-lh）", 15.67, px(c.lineHeight), 0.05);
    num("段尾上边距 7.67（--ios-footer-text-top）", 7.67, px(c.paddingTop), 0.05);
    num("段尾下边距 24.66（30.33 − 7.67 − 15.67 + 17.67：--ios-footer-h + --ios-group-gap）", 24.66, px(c.paddingBottom), 0.05);
  }
  /* 2026-09-18: the device card is a Settings value row (46 Apple 账户页), no icon. */
  const dev = document.querySelector(".devcard");
  if (dev) {
    /* 2026-09-19 layout item: a two-line row (AX-35 geometry) — dot + 「游戏机 · 开机中」 single line, the detail below in secondaryLabel */
    num("状态卡 = 两行行 62 起（--ios-row2-h，AX-35）", 62, Math.min(dev.getBoundingClientRect().height, 62)); const s2 = dev.querySelector(".dsub"), n2 = dev.querySelector(".dname");
    if (s2) { col("状态卡第二行 secondaryLabel（--ios-secondary-label）", T.dim, cs(s2).color); num("状态卡第二行 15/18（--ios-sub-size/-lh）", 15, px(cs(s2).fontSize)); check("状态卡第二行左对齐、可换行", "left normal", `${cs(s2).textAlign} ${cs(s2).whiteSpace}`, cs(s2).textAlign === "left" && cs(s2).whiteSpace === "normal"); }
    if (n2) { check("状态卡第一行不换行、尾部省略", "nowrap ellipsis", `${cs(n2).whiteSpace} ${cs(n2).textOverflow}`, cs(n2).whiteSpace === "nowrap" && cs(n2).textOverflow === "ellipsis");
      num("状态卡第一行顶 = 卡顶 + 9（--ios-row2-title-top，AX-35）", 9, n2.getBoundingClientRect().top - dev.getBoundingClientRect().top, 0.5);
      if (s2) num("状态卡第二行顶 = 卡顶 + 32.33（--ios-row2-sub-top，AX-35）", 32.33, s2.getBoundingClientRect().top - dev.getBoundingClientRect().top, 0.5);
      check("状态卡第一行 = 「游戏机 · <状态>」", "游戏机 · …", n2.textContent, /^游戏机/.test(n2.textContent)); }
    const dot = dev.querySelector(".dot"); if (dot && n2) { num("状态点 11（--ios-status-dot，AX-58 信息未读点）", 11, dot.getBoundingClientRect().width); num("状态点到字 8（--ios-value-gap）", 8, n2.getBoundingClientRect().left - dot.getBoundingClientRect().right);
      num("状态点与第一行文字居中", 0, (dot.getBoundingClientRect().top + dot.getBoundingClientRect().height / 2) - (n2.getBoundingClientRect().top + n2.getBoundingClientRect().height / 2), 0.5); }
    /* site-wide: value rows keep the title on one line and ellipsise the value (Settings AX-41 / AX-46: every title and value single-line) */
    { const lab = document.querySelector("#app .row > label"); if (lab) check("值行标题不换行、尾部省略（全站）", "nowrap ellipsis", `${cs(lab).whiteSpace} ${cs(lab).textOverflow}`, cs(lab).whiteSpace === "nowrap" && cs(lab).textOverflow === "ellipsis"); }
    /* 2026-09-19 (ui2): setStatus splits 「<state> · <detail>」 — the state joins the title, the detail is the second line; no 「 · 」 = all detail.
       The copy has no parentheses and no 「…是…的」 (PHONE-COPY-RULES): 「实时 · 配置 1 分钟前」. A re-render must keep the dot's state colour. */
    if (typeof setStatus === "function" && document.querySelector("#status") && n2 && s2) {
      const was = document.querySelector("#status").textContent, wasDot = (document.querySelector("#dot") || {}).className || "";
      const title = () => (document.querySelector(".devcard .dname") || {}).textContent || "", detail = () => (document.querySelector("#status2") || {}).textContent || "";
      setStatus("开机中 · 实时 · 配置 1 分钟前", "on");
      check("状态拆行：「开机中 · 实时 · 配置 1 分钟前」→ 标题「游戏机 · 开机中」+ 第二行「实时 · 配置 1 分钟前」", "游戏机 · 开机中 | 实时 · 配置 1 分钟前", `${title().replace("（演示）", "")} | ${detail()}`,
            title().replace("（演示）", "") === "游戏机 · 开机中" && detail() === "实时 · 配置 1 分钟前" && (document.querySelector("#dot2") || {}).classList?.contains("on"));
      setStatus("正在读取…", "");
      check("状态拆行：没有「 · 」的整句进第二行，标题只剩「游戏机」", "游戏机 | 正在读取…", `${title().replace("（演示）", "")} | ${detail()}`, title().replace("（演示）", "") === "游戏机" && detail() === "正在读取…");
      if (typeof render === "function" && typeof snap !== "undefined" && snap) {
        setStatus("开机中 · 实时", "on"); render();
        const d3 = document.querySelector("#dot2");
        check("重画后状态卡保持状态：点仍绿、标题仍带「开机中」、第二行仍在", "on · 游戏机 · 开机中 · 实时", `${d3 && d3.classList.contains("on") ? "on" : "grey"} · ${title().replace("（演示）", "")} · ${detail()}`,
              !!d3 && d3.classList.contains("on") && title().replace("（演示）", "") === "游戏机 · 开机中" && detail() === "实时");
      }
      setStatus(was, /\bon\b/.test(wasDot) ? "on" : /\boff\b/.test(wasDot) ? "off" : "");
    }
  }
  /* Site-wide (2026-09-19, ui2): a synthetic row with an over-long name + a long hint + an over-long read-only value, a navigation row
     with an over-long value, and an over-long section header: the name, the values and the header stay one 20.33 line with a tail
     ellipsis; the hint under the name still wraps (a paragraph, AX-33d subtitle rows); the value keeps its own width — a long hint
     must not squeeze it (the 手机 tab's 「已配置 / 没有」 row showed 「没..」 when the label's basis was auto). */
  { const wl = document.createElement("div"); wl.style.cssText = "position:fixed;left:20px;top:0;width:400px;visibility:hidden;z-index:-1";
    wl.innerHTML = `<div class="group"><div class="row"><label>${"名字很长".repeat(10)}<span class="hint">${"副题要换行".repeat(9)}</span></label><span class="ro">${"值也很长".repeat(10)}</span></div>` +
                   `<div class="row"><label>已配置<span class="hint">${"副题要换行".repeat(9)}</span></label><span class="ro">没有</span></div>` +
                   `<div class="row nav"><label>名</label><span class="val">${"选项".repeat(40)}</span><i class="sf chev"></i></div></div><section><h2>${"段头很长".repeat(12)}</h2></section>`;
    document.body.appendChild(wl);
    const lab0 = wl.querySelector(".row > label"), ro = wl.querySelector(".ro"), val = wl.querySelector(".val"), hh = wl.querySelector("h2"), hint = lab0.querySelector(".hint");
    const rg = document.createRange(); rg.selectNodeContents(lab0.firstChild); const nameLines = new Set([...rg.getClientRects()].map((r) => Math.round(r.top))).size;
    const nameH = lab0.getBoundingClientRect().height - hint.getBoundingClientRect().height - px(cs(hint).marginTop);
    check("值行标题一行 20.33（nowrap + 尾部省略；长名字）", "nowrap ellipsis 1 行 20.33", `${cs(lab0).whiteSpace} ${cs(lab0).textOverflow} ${nameLines} 行 ${Math.round(nameH * 100) / 100}`, cs(lab0).whiteSpace === "nowrap" && cs(lab0).textOverflow === "ellipsis" && nameLines === 1 && near(nameH, 20.33, 0.6));
    check("值行标题下的副题照常换行（white-space normal，多行）", "normal ≥ 2 行", `${cs(hint).whiteSpace} ${Math.round(hint.getBoundingClientRect().height / 18)} 行`, cs(hint).whiteSpace === "normal" && hint.getBoundingClientRect().height >= 36);
    check("只读值一行、尾部省略（.ro）", "nowrap ellipsis 20.33", `${cs(ro).whiteSpace} ${cs(ro).textOverflow} ${Math.round(ro.getBoundingClientRect().height * 100) / 100}`, cs(ro).whiteSpace === "nowrap" && cs(ro).textOverflow === "ellipsis" && near(ro.getBoundingClientRect().height, 20.33, 0.6));
    check("导航值一行、尾部省略（.nav .val）", "nowrap ellipsis 20.33", `${cs(val).whiteSpace} ${cs(val).textOverflow} ${Math.round(val.getBoundingClientRect().height * 100) / 100}`, cs(val).whiteSpace === "nowrap" && cs(val).textOverflow === "ellipsis" && near(val.getBoundingClientRect().height, 20.33, 0.6));
    { const lr = lab0.getBoundingClientRect(), rr = ro.getBoundingClientRect(), side = rr.left >= lr.right && rr.top < lr.bottom && rr.bottom > lr.top;
      check("名字和值并排同一行（值行不折成两行）", "并排", side ? "并排" : `值在 y+${Math.round(rr.top - lr.bottom)}`, side); }
    { const ro2 = wl.querySelectorAll(".ro")[1], probeW = (() => { const i = document.createElement("span"); i.className = "ro"; i.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap"; i.textContent = "没有"; wl.querySelector(".row").appendChild(i); const w = i.getBoundingClientRect().width; i.remove(); return w; })();
      num("短值不被长副题挤瘦（「没有」保持自然宽，label flex-basis 0）", probeW, ro2.getBoundingClientRect().width, 0.6); }
    check("段头一行、尾部省略", "nowrap ellipsis 20.33", `${cs(hh).whiteSpace} ${cs(hh).textOverflow} ${Math.round((hh.getBoundingClientRect().height - px(cs(hh).paddingTop) - px(cs(hh).paddingBottom)) * 100) / 100}`, cs(hh).whiteSpace === "nowrap" && cs(hh).textOverflow === "ellipsis" && near(hh.getBoundingClientRect().height - px(cs(hh).paddingTop) - px(cs(hh).paddingBottom), 20.33, 0.6));
    wl.remove(); }
  /* State colours, probed on synthetic controls so they are checked whatever the
     data happens to show: a switch on/off, the danger tile title, the selected
     tab, the edit bar's two capsules. 2026-09-15 the green track rule vanished
     and nobody noticed until the phone showed grey everywhere. */
  const lab = document.createElement("div"); lab.style.cssText = "position:fixed;left:-9999px;top:0";
  lab.innerHTML = `<label class="sw"><input type="checkbox" checked><span></span></label><label class="sw"><input type="checkbox"><span></span></label>` +
    `<button class="tile danger"><span class="ttitle">x</span></button><nav class="tabs"><div class="seg"><button class="on">x</button></div></nav>` +
    `<div class="topbar editing"><button class="navbtn" id="_d">x</button><button class="navbtn" id="_s">x</button></div>` +
    `<div class="group"><div class="row"><label>x</label><span class="sent">已寄出 10:00</span></div><div class="row"><label>y</label><input type="text" class="short" value="08:30"></div><div class="acts"><button>开始刷</button></div></div>`;
  document.body.appendChild(lab);
  const [on, off] = lab.querySelectorAll(".sw span");
  /* A tap through the page's own pointer handling, followed by the click the
     browser fires anyway: the switch must flip exactly once and `change` fire
     once (12:0x: it flipped twice and stayed put). */
  const tapSw = lab.querySelectorAll(".sw")[1], tapIn = tapSw.querySelector("input"); let changes = 0;
  tapIn.addEventListener("change", () => changes++);
  const was = tapIn.checked;
  const pe = (type, target) => target.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: 7, clientX: 10, clientY: 10, isPrimary: true }));
  pe("pointerdown", tapIn); pe("pointerup", tapSw); tapIn.click();
  check("轻点一下：开关翻转一次", !was, tapIn.checked, tapIn.checked === !was);
  check("轻点一下：change 只发一次", 1, changes, changes === 1);
  col("停止一切标题 = 红（--ios-red）", T.red, cs(lab.querySelector(".ttitle")).color);
  col("选中的标签 = tint（--ios-tint）", T.tint, cs(lab.querySelector("nav.tabs button.on")).color);
  col("蓝字行 = link（--ios-link）", T.link, cs(lab.querySelector(".acts button")).color);
  const cap = lab.querySelector(".sent");
  num("三态小字 11（--ios-caption2-size）", 11, px(cs(cap).fontSize), 0.05); num("三态小字行框 13.13（--ios-caption2-lh）", 13.13, px(cs(cap).lineHeight), 0.05);
  col("三态小字色 secondaryLabel（--ios-secondary-label）", T.dim, cs(cap).color);
  /* navigation value row 「已选 N/M ›」 (AX-37 value row + disclosure) and the check-list sheet (AX-38) */
  lab.insertAdjacentHTML("beforeend", `<div class="group" style="width:400px"><div class="row nav"><label>多选</label><span class="val">已选 1/3</span><i class="sf chev"></i></div></div>`);
  { const nr = lab.querySelector(".row.nav"), ch = nr.querySelector(".chev"), vl = nr.querySelector(".val"), rr = nr.getBoundingClientRect(), cr = ch.getBoundingClientRect();
    num("值行箭头 10.33×14（--ios-chevron-w/-h，AX-45）", 10.33, cr.width, 0.05); num("值行箭头高 14", 14, cr.height, 0.05);
    num("值行箭头距右 20（--ios-chevron-inset）", 20, rr.right - cr.right); col("值行箭头色 tertiaryLabel", dark ? [235, 235, 245, .298] : [60, 60, 67, .298], cs(ch).backgroundColor);
    col("值行的值 secondaryLabel（AX-37）", T.dim, cs(vl).color); num("值到箭头 8（--ios-value-gap）", 8, cr.left - vl.getBoundingClientRect().right); }
  if (typeof openPicker === "function" && document.querySelector("#picker")) {
    openPicker({ title: "测", multi: true, opts: [[["甲"], "a"], [["乙"], "b"], [["丙"], "c"]], on: new Set(["a"]), icons: false }, () => true);
    const sh = document.querySelector("#picker"), card = sh.querySelector(".card"), nav = sh.querySelector(".pnav"), back = sh.querySelector(".pback"), done = sh.querySelector(".pdone");
    /* Behaviour 5: present = card from the screen bottom (translateY(100 %) = 894) to y 62 and dimming 0 → .2 on the sheet spring
       (pagesheet-motion.md: m 3 / k 1000 / c 500 → critical ω 18.5; tokens --ios-motion-sheet-duration 0.5 s / -easing) */
    { const tr = cs(card).transform, m = /matrix\(1, 0, 0, 1, 0, ([\d.]+)\)/.exec(tr) || /translateY\(([\d.]+)px\)/.exec(tr);
      check("勾选页出现：从屏底起（t=0 位移 = 卡高 894 = 956 − 62）", "≈ 894", tr, !!m && Math.abs(parseFloat(m[1]) - card.getBoundingClientRect().height) < 2);
      check("勾选页出现时长 0.5 s（--ios-motion-sheet-duration，pagesheet-motion.md 弹簧 m3/k1000/c500）", "0.5s", cs(card).transitionDuration, cs(card).transitionDuration === "0.5s");
      check("勾选页出现曲线 = 弹簧 linear()（--ios-motion-sheet-easing）", "linear(…)", cs(card).transitionTimingFunction.slice(0, 12), /^linear\(/.test(cs(card).transitionTimingFunction));
      const dim = sh.querySelector(".dim"); check("勾选页遮罩同一条曲线淡入（0 → .2）", "0.5s linear", `${cs(dim).transitionDuration} ${cs(dim).transitionTimingFunction.slice(0, 6)}`, cs(dim).transitionDuration === "0.5s" && /^linear/.test(cs(dim).transitionTimingFunction));
      card.style.transition = "none"; dim.style.transition = "none"; }   // snap to the settled state for the geometry below
    const cr2 = card.getBoundingClientRect(), nr2 = nav.getBoundingClientRect(), br = back.getBoundingClientRect(), dr = done.getBoundingClientRect(), sat = satTop();
    num("勾选页顶 = 安全区顶（standalone 62 = --ios-status-h，AX-38 表 y 62；浏览器里 0）", sat, cr2.top); num("勾选页顶角 38（--ios-sheet-radius-top）", 38, px(cs(card).borderTopLeftRadius));
    col("勾选页底 = elevated systemGroupedBackground（--ios-grouped-bg-elevated：暗 (28,28,30)，探针 levels）", dark ? [28, 28, 30] : [242, 242, 247], cs(card).backgroundColor);
    { const pg = sh.querySelector(".plist .group"); if (pg) col("勾选页卡 = elevated secondarySystemGroupedBackground（--ios-card-bg-elevated：暗 (44,44,46)）", dark ? [44, 44, 46] : [255, 255, 255], cs(pg).backgroundColor); }
    num("勾选页导航栏 54 在安全区顶 + 20（AX-38 y 82 = 62 + 20，--ios-modal-nav-top − --ios-status-h）", sat + 20, nr2.top); num("导航栏高 54", 54, nr2.height);
    num("返回圆钮 44 at x 20（AX-38 BackButton）", 44, br.width); num("返回圆钮 x 20", 20, br.left);
    num("完成圆钮 36（--ios-modal-button，AX-38 (380,86,36,36)）", 36, dr.width); num("完成圆钮 x 380", 380, dr.left); num("完成圆钮 y = 安全区顶 + 24（AX-38 y 86）", sat + 24, dr.top);
    const rows = [...sh.querySelectorAll(".row.check")], r0 = rows[0].getBoundingClientRect(), ck = rows[0].querySelector(".ck").getBoundingClientRect(), lb = rows[0].querySelector("label").getBoundingClientRect();
    num("勾选行高 53.33（--ios-row-h，AX-38）", 53.33, r0.height); num("勾选行文字 x 40（AX-38）", 40, lb.left); num("勾选页首行 = 安全区顶 + 91.67（AX-38 y 153.67 = 导航底 136 + 17.67）", sat + 91.67, r0.top, 0.5);
    num("✓ 19×17.33（AX-38 checkmark 帧）", 19, ck.width, 0.05); num("✓ 右缘距行右 22.5（AX-38：397.5 = 420 − 22.5）", 22.5, r0.right - ck.right, 0.05);
    col("✓ 色 tint（--ios-tint）", T.tint, cs(rows[0].querySelector(".ck")).backgroundColor);
    check("未选行不画 ✓", "hidden", cs(rows[1].querySelector(".ck")).visibility, cs(rows[1].querySelector(".ck")).visibility === "hidden");
    rows[1].click(); check("点行切 ✓（多选）", "2 on", `${sh.querySelectorAll(".row.check.on").length} on`, sh.querySelectorAll(".row.check.on").length === 2);
    back.click(); check("返回关闭勾选页（.in 去掉，走同一条弹簧回屏底，0.5 s 后隐藏）", "closing", sh.classList.contains("in") ? "open" : "closing", !sh.classList.contains("in"));
    card.style.transition = ""; sh.querySelector(".dim").style.transition = "";
  }
  const vb = lab.querySelector("input.short");
  num("值框圆角 8（--ios-value-box-radius，NUMBERS 49）", 8, px(cs(vb).borderTopLeftRadius)); num("值框内距上下 6（--ios-value-box-pad-y）", 6, px(cs(vb).paddingTop)); num("值框内距左右 11（--ios-value-box-pad-x）", 11, px(cs(vb).paddingLeft));
  col("值框底 tertiaryFill（--ios-tertiary-fill）", dark ? [118, 118, 128, .24] : [118, 118, 128, .12], cs(vb).backgroundColor);
  lab.querySelector("#_d").id = "discard"; lab.querySelector("#_s").id = "save";
  check("编辑栏 ✓ = tint 底白符号（--ios-tint）", fmt(T.tint), cs(lab.querySelector("#save")).backgroundColor, same(cs(lab.querySelector("#save")).backgroundColor, T.tint) && same(cs(lab.querySelector("#save")).color, [255, 255, 255]));
  num("编辑栏圆钮 44（--ios-nav-button）", 44, lab.querySelector("#save").getBoundingClientRect().height); num("编辑栏圆钮宽 44（--ios-nav-button）", 44, lab.querySelector("#save").getBoundingClientRect().width);
  num("编辑栏圆钮距边 20（--ios-nav-side）", 20, px(cs(lab.querySelector("#discard")).left));
  { const tb = lab.querySelector(".topbar"); num("编辑栏圆钮在 54 栏里居中（上下各 5 ← AX-45）", 5, lab.querySelector("#save").getBoundingClientRect().top - tb.getBoundingClientRect().top - px(cs(tb).paddingTop)); }
  check("编辑栏圆钮是圆的", "50%", cs(lab.querySelector("#save")).borderRadius, cs(lab.querySelector("#save")).borderRadius === "50%" || px(cs(lab.querySelector("#save")).borderRadius) >= 22);
  lab.remove();
  const meta = document.querySelector('meta[name="theme-color"]');
  check("theme-color 存在", "是", meta ? "是" : "缺", !!meta);

  if (sec("stamina", { layer: "release-only" }) && window.Stamina && typeof numTiles === "function") {
    const had = localStorage.getItem("ark-remote-tokens"), hadCache = localStorage.getItem("ark-remote-stamina"), d0 = Stamina.data, at0 = Stamina.at;
    try {
      localStorage.setItem("ark-remote-tokens", JSON.stringify({ sk: { cred: "x", token: "y" } })); Stamina.tokens = null; Stamina.data = null;
      const h = numTiles(null), tmp = document.createElement("div"); tmp.innerHTML = h;
      check("体力：没读到前画三格占位（图标 + 名字 + 数字/脚注灰块，HIG Loading）", "3 tiles · 6 ph", `${tmp.querySelectorAll(".num").length} tiles · ${tmp.querySelectorAll(".ph").length} ph`, tmp.querySelectorAll(".num").length === 3 && tmp.querySelectorAll(".ph").length === 6);
      localStorage.setItem("ark-remote-stamina", JSON.stringify({ at: 1, data: { "明日方舟": { "理智": 77, "上限": 135 }, "终末地": { "理智": 12, "上限": 240 }, "鸣潮": { "波片": 200, "上限": 240 }, "取自": "08:15" } }));
      Stamina.loadCache(); const h2 = numTiles(null); tmp.innerHTML = h2;
      check("体力：上次读数立刻显示（状态恢复），脚注写读取时刻", "77 · 08:15 读取", `${(tmp.querySelector(".num .big") || {}).textContent} · ${(tmp.querySelector(".foot") || {}).textContent}`, /^77/.test((tmp.querySelector(".num .big") || {}).textContent || "") && /08:15/.test((tmp.querySelector(".foot") || {}).textContent || ""));
      check("体力：缓存读数不占一分钟复用（at = 0，后台刷新马上跑）", "cached at 0", `cached=${Stamina.cached} at=${Stamina.at}`, Stamina.cached === true && Stamina.at === 0);
    } finally {
      if (had == null) localStorage.removeItem("ark-remote-tokens"); else localStorage.setItem("ark-remote-tokens", had);
      if (hadCache == null) localStorage.removeItem("ark-remote-stamina"); else localStorage.setItem("ark-remote-stamina", hadCache);
      Stamina.tokens = null; Stamina.data = d0; Stamina.at = at0; Stamina.cached = false;
    }
  }
  /* Behaviour 4: the home keeps the newest 3 receipts + 「查看全部 ›」; the pushed page groups by day */
  if (sec("receipts", { layer: "release-only" })) { const secs = [...document.querySelectorAll("#app > section")].filter((s) => /机器最近的回执/.test((s.querySelector("h2") || {}).textContent || ""));
    const sec = secs[0], rows = sec ? sec.querySelectorAll(".row:not(.nav)") : [], more = sec && sec.querySelector('.row.nav[data-page="receipts"]');
    if (sec) {
      check("首页回执最多 3 条 + 「查看全部 ›」（AX-13 显示所有健康数据 ›）", "≤3 + 查看全部", `${rows.length} + ${more ? "查看全部 " + more.querySelector(".val").textContent : "-"}`, rows.length <= 3 && (!more || rows.length === 3));
      if (more) {
        const pg = document.querySelector("#subpage"); more.click(); await sleep(80);
        check("推入页打开（.in）、标题「回执」", "in 回执", `${pg.classList.contains("in") ? "in" : "-"} ${pg.querySelector(".ptitle").textContent}`, pg.classList.contains("in") && pg.querySelector(".ptitle").textContent === "回执");
        { const x80 = pg.getBoundingClientRect().left; check("推入 +80 ms：新页从右边滑入中（440 → 0，0.35 s）", "0 < x < 440", `x ${Math.round(x80)}`, x80 > 0 && x80 < 440); }
        await settle(() => !pg.classList.contains("nav-live"), 400);   // S1: nav.js's push spring at rest (nav-live off), ≤ the old 400
        const pr = pg.querySelector(".pnav").getBoundingClientRect(), bb = pg.querySelector(".pback").getBoundingClientRect(), sat = satTop();
        num("推入页导航栏 54 在安全区顶（AX-11 / AX-46 (0,62,440,54)）", sat, pr.top); num("推入页导航栏高 54", 54, pr.height);
        num("推入页返回钮 44 at x 20（AX-11 BackButton (20,62,44,44)）", 44, bb.width); num("推入页返回钮 x 20", 20, bb.left);
        check("推入页按日分组（Health 显示所有数据 AX-11：一天一组）", "≥1 组 h2 月日", `${pg.querySelectorAll(".pbody h2").length} 组 ${(pg.querySelector(".pbody h2") || {}).textContent}`, pg.querySelectorAll(".pbody h2").length >= 1 && /\d+月\d+日/.test((pg.querySelector(".pbody h2") || {}).textContent || ""));
        check("推入 0.35 s（--ios-motion-nav-push-duration）、旧页视差 30 %", "0.35s pushed", `${getComputedStyle(pg).transitionDuration} ${document.body.classList.contains("pushed") ? "pushed" : "-"}`, getComputedStyle(pg).transitionDuration === "0.35s" && document.body.classList.contains("pushed"));
        pg.querySelector(".pback").click(); await settle(() => pg.hidden && !pg.classList.contains("nav-live"), 450);   // S1: the pop's own end
        check("推入页返回：弹出后隐藏、旧页回位", "hidden", `${pg.hidden ? "hidden" : "shown"} ${document.body.classList.contains("pushed") ? "pushed" : "back"}`, pg.hidden && !document.body.classList.contains("pushed"));
      }
    }
  }
  /* 数据终核 181053 ⑤2: the 刷到几点 input takes HH:MM only — 08:930 rolls back to the last valid value, nothing enters the pending edits */
  if (sec("time-input", { layer: "release-only" })) { const ti = document.querySelector("input[data-time]");
    if (ti) { const before = ti.value, n0 = Object.keys(edits).length; ti.value = "08:930"; ti.dispatchEvent(new Event("change", { bubbles: true })); const back = ti.value;
      ti.value = "9:05"; ti.dispatchEvent(new Event("change", { bubbles: true })); const norm = ti.value; ti.value = before; ti.dispatchEvent(new Event("change", { bubbles: true }));
      check("时间输入只收 HH:MM：08:930 回滚成原值、9:05 规整成 09:05、待保存数不变", `${before} · 09:05 · edits ${n0}`, `${back} · ${norm} · edits ${Object.keys(edits).length}`, back === before && norm === "09:05" && Object.keys(edits).length === n0); }
    else check("时间输入只收 HH:MM（页面上此刻没有 data-time 输入框：刷声骸块未渲染，不核）", "-", "no input", true); }
  /* 验收 09-19 18:0x: view.js arriving 3 s late (slow network) must not throw in live.js's timers / events (window.__viewReady gate): the page in an iframe with
     ?viewdelay=5500 (live.js's 5 s updateLive tick fires first), its error / unhandledrejection events counted for 7 s */
  if (sec("viewdelay", { layer: "release-only" })) { const fr = document.createElement("iframe"); fr.style.cssText = "position:fixed;left:-2000px;top:0;width:440px;height:956px;opacity:0;pointer-events:none"; fr.src = "index.html?demo=1&viewdelay=5500";
    const errs = []; document.body.appendChild(fr);
    await new Promise((r) => { fr.onload = r; setTimeout(r, 3000); });
    try { fr.contentWindow.addEventListener("error", (e) => errs.push(String(e.message || e.error || e))); fr.contentWindow.addEventListener("unhandledrejection", (e) => errs.push("rejection " + String(e.reason))); } catch (e) { errs.push("no access " + e); }
    await sleep(7000);
    let ready = null; try { ready = fr.contentWindow.__viewReady === true; } catch (e) {}
    check("view.js 延迟 5.5 s 装载（live.js 的 5 s updateLive 定时器先到）：不报错（__viewReady 闸），装载后页面起来", "0 errors · ready", `${errs.length} errors ${errs.slice(0, 2).join(" | ")} · ready ${ready}`, errs.length === 0 && ready === true);
    fr.remove(); }
  /* the page's own action rows must not block the main thread: no synchronous confirm() left in view.js except ask()'s no-dialog fallback */
  if (sec("confirm", { layer: "release-only" })) {
  try { const src = await (await fetch("view.js?v=" + Date.now())).text(); const n = (src.match(/\bconfirm\(/g) || []).length;
    check("行动作不再同步 confirm()（view.js 里只剩 ask() 的无 dialog 兜底那一处）", 1, n, n === 1); } catch (e) { check("行动作不再同步 confirm()", 1, "读不到 view.js", false); }
  }
  }, { layer: "release-only" });
})();
