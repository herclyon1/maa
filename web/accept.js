/* 验收：页面地址加 ?accept 时加载，在这台设备的浏览器里量 DOM，逐项和
   docs/HIG-CHECKLIST.md 的数字比。只认 iOS Safari 的数（桌面 Chromium 没有安全区）。
   结果存进 localStorage 的 ark-accept，scripts/mac/phone-accept.sh 从模拟器的存储里
   读出来；不加 &quiet 时左上角盖一张表。
   方法照 ~/Money/transit/ui/accept.js（另一个会话 2026-09-15 定型）。
   2026-09-18：期望值改成 web/tokens.css 的原值（每项后面写变量名；出处在 tokens.css
   该变量上一行的注释：UIProbe 探针 / AX json / Kit NUMBERS）。期望值故意写死在这里，
   不从 tokens.css 读——两边同源的话 tokens 写错也会「通过」。颜色比对解析 rgb，不比字串。 */
/* night batch (BOARD.md A6): per-control acceptance files register through ACCEPT.add(fn); accept.js loads them in index.html hook order and runs
   each fn(ctx) after its own rows, ctx = { check, num, col, sleep }. A file that is still a shell registers nothing. */
window.ACCEPT = window.ACCEPT || { fns: [], add(fn) { this.fns.push(fn); } };
(function () {
  const q = new URLSearchParams(location.search);
  if (!q.has("accept")) return;
  /* the per-control files are appended dynamically; headless Chrome occasionally drops one of those fetches (night 00:3x: accept-sheet.js never
     requested in one run → 17 rows silently missing). Each load is tracked; a file that has not loaded when the checks start is re-appended, and
     a file still missing gets a ✗ row so the total never drops silently. */
  window.ACCEPT.files = ["motion","nav","nav-edge","sheet","menu","topbar","refresh","glassbtn","switch","tabbar"]; window.ACCEPT.loaded = new Set();
  window.ACCEPT.load = (c) => new Promise((res) => { const s = document.createElement("script"); s.src = "accept-" + c + ".js?r=" + Math.random().toString(36).slice(2, 7); s.onload = () => { window.ACCEPT.loaded.add(c); res(true); }; s.onerror = () => res(false); document.head.appendChild(s); setTimeout(() => res(false), 4000); });
  for (const c of window.ACCEPT.files) window.ACCEPT.load(c);
  const rows = [];
  const near = (a, b, tol = 0.6) => Math.abs(a - b) <= tol;
  const cs = (el, pseudo) => el ? getComputedStyle(el, pseudo || null) : null;
  const px = (v) => parseFloat(v) || 0;
  /* top safe-area inset as the page sees it: 62 in the standalone web clip (black-translucent, web view covers the whole 956),
     0 in a browser viewport — the geometry below is expressed relative to it, the way the page's own CSS is */
  const satTop = () => { const pr = document.createElement("div"); pr.style.cssText = "position:fixed;top:0;left:0;width:1px;padding-top:env(safe-area-inset-top);visibility:hidden";
    document.body.appendChild(pr); const v = px(cs(pr).paddingTop); pr.remove(); return v; };
  function check(item, expect, got, ok) {
    rows.push({ item, expect: String(expect), got: got === undefined || got === null ? "缺" : String(typeof got === "number" ? Math.round(got * 100) / 100 : got), ok: !!ok });
  }
  function num(item, expect, got, tol) { check(item, expect, got, typeof got === "number" && near(got, expect, tol)); }
  /* Colours: computed styles come back as rgb(r, g, b) / rgba(r, g, b, a); compare the
     numbers (tolerance 3 per channel, .02 alpha), never the string. */
  const rgb = (c) => { const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/.exec(c || ""); return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null; };
  const same = (c, want, tol = 3) => { const a = rgb(c); return !!a && a.slice(0, 3).every((v, i) => Math.abs(v - want[i]) <= tol) && Math.abs(a[3] - (want[3] === undefined ? 1 : want[3])) <= 0.02; };
  const fmt = (want) => want.length > 3 && want[3] !== 1 ? `rgba(${want[0]},${want[1]},${want[2]},${want[3]})` : `rgb(${want[0]},${want[1]},${want[2]})`;
  function col(item, want, got) { check(item, fmt(want), got, same(got, want)); }
  /* A page variable's colour, resolved by the browser (var(--accent) → rgb). */
  const varColor = (name, probe) => { probe.style.color = `var(${name})`; return cs(probe).color; };

  function run() {
    const dark = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light" || document.documentElement.dataset.theme === "dark";
    /* tokens.css semantic colours (UIProbe colour table, light / dark) */
    const T = {
      tint: dark ? [0, 145, 255] : [0, 136, 255],               // --ios-tint
      link: dark ? [9, 132, 255] : [0, 122, 255],               // --ios-link
      red: dark ? [255, 66, 69] : [255, 56, 60],                // --ios-red
      green: dark ? [48, 209, 88] : [52, 199, 89],              // --ios-green / --ios-switch-on
      swOff: dark ? [235, 235, 245, .298] : [60, 60, 67, .298], // --ios-switch-off
      sep: dark ? [84, 84, 88, .5] : [60, 60, 67, .12],         // --ios-separator
      card: dark ? [28, 28, 30] : [255, 255, 255],              // --ios-card-bg
      bg: dark ? [0, 0, 0] : [242, 242, 247],                   // --ios-grouped-bg
      dim: dark ? [235, 235, 245, .6] : [60, 60, 67, .6],       // --ios-secondary-label
    };
    const probe = document.createElement("i"); probe.style.cssText = "position:fixed;left:-9999px;top:0"; document.body.appendChild(probe);

    check("view.js 就绪后才量（window.__viewReady，accept.js 等它 ≤ 60 s）", "true", String(window.__viewReady), window.__viewReady === true);
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
    const tile = document.querySelector(".tile");
    if (tile) {
      const r = tile.getBoundingClientRect();
      num("动作磁贴高 ≥ 80.33（--ios-tile-h，AX-57）", 80.33, Math.min(r.height, 80.33)); num("动作磁贴圆角 16（--ios-tile-radius，提醒事项 layer.cornerRadius）", 16, px(cs(tile).borderTopLeftRadius));
      num("磁贴间距 8（--ios-tile-gap）", 8, px(cs(tile.parentElement).columnGap));
      const ico = tile.querySelector(".tico"); if (ico) { const ir = ico.getBoundingClientRect(); num("磁贴徽章 48（--ios-tile-icon）", 48, ir.width); num("磁贴徽章 x 6（--ios-tile-icon-x）", 6, ir.left - r.left); num("磁贴徽章 y 2（--ios-tile-icon-y）", 2, ir.top - r.top); }
      const tt = tile.querySelector(".ttitle"); if (tt) { const tr = tt.getBoundingClientRect(); num("磁贴标题 17（--ios-tile-label-size）", 17, px(cs(tt).fontSize), 0.05); num("磁贴标题行框 20.33（--ios-tile-label-lh）", 20.33, px(cs(tt).lineHeight), 0.05); check("磁贴标题字重 600（--ios-tile-label-weight）", 600, cs(tt).fontWeight, String(cs(tt).fontWeight) === "600"); num("磁贴标题 x 12（--ios-tile-label-x）", 12, tr.left - r.left); num("磁贴标题 y 52（--ios-tile-label-top）", 52, tr.top - r.top); check("磁贴字族 ui-rounded 优先（--ios-tile-number-font）", "ui-rounded", cs(tt).fontFamily.slice(0, 10), /^ui-rounded/.test(cs(tt).fontFamily)); }
    }
    const numT = document.querySelector(".num");
    if (numT) {
      const r = numT.getBoundingClientRect();
      num("数字磁贴高 ≥ 80.33（--ios-tile-h）", 80.33, Math.min(r.height, 80.33)); num("数字磁贴圆角 16（--ios-tile-radius）", 16, px(cs(numT).borderTopLeftRadius));
      const big = numT.querySelector(".big"); if (big) { const br = big.getBoundingClientRect(); num("数字右内缩 10（--ios-tile-number-inset）", 10, r.right - br.right); num("数字顶 9（--ios-tile-number-top）", 9, br.top - r.top); num("数字字号 28（--ios-tile-number-size）", 28, px(cs(big).fontSize), 0.1); num("数字行框 33.67（--ios-tile-number-lh）", 33.67, px(cs(big).lineHeight), 0.05); check("数字字重 700（--ios-tile-number-weight）", 700, cs(big).fontWeight, String(cs(big).fontWeight) === "700"); }
      const ico = numT.querySelector(".nico"); if (ico) num("数字磁贴徽章 48（--ios-tile-icon）", 48, ico.getBoundingClientRect().width);
      const lab = numT.querySelector(".lab"); if (lab) { const lr = lab.getBoundingClientRect(); num("数字磁贴标签 17（--ios-tile-label-size）", 17, px(cs(lab).fontSize), 0.1); num("数字磁贴标签 x 12（--ios-tile-label-x）", 12, lr.left - r.left); num("数字磁贴标签 y 52（--ios-tile-label-top）", 52, lr.top - r.top); }
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
    /* Segmented control (状态 tab, 早班/晚班; 34 屏幕时间) */
    const segc = document.querySelector(".segctl");
    if (segc) {
      const r = segc.getBoundingClientRect();
      num("分段控件高 32（--ios-segment-h）", 32, r.height); num("分段控件圆角 16（--ios-segment-radius）", 16, px(cs(segc).borderTopLeftRadius));
      col("分段轨道 tertiarySystemFill（--ios-segment-track）", dark ? [118, 118, 128, .24] : [118, 118, 128, .12], cs(segc).backgroundColor);
      num("分段控件宽 = 卡片宽", innerWidth - 40, r.width);
      const lens = segc.querySelector(".lens"), b = segc.querySelector("button");
      if (lens) { num("分段透镜高 28（--ios-segment-lens-h）", 28, lens.getBoundingClientRect().height); num("分段透镜圆角 14（--ios-segment-lens-radius）", 14, px(cs(lens).borderTopLeftRadius)); num("分段透镜内缩 2（--ios-segment-lens-pad）", 2, lens.getBoundingClientRect().top - r.top);
        col("分段选中段 = _controlForegroundColor（--ios-segment-selected-bg）", dark ? [235, 235, 245, .3] : [255, 255, 255], cs(lens).backgroundColor);
        check("分段选中段无阴影（--ios-segment-selected-shadow）", "none", cs(lens).boxShadow, cs(lens).boxShadow === "none");
        check("分段静止平台普通合成（menu-card-material.md §2 更正：kCAFilterPlusL 只在 useSpringBoardVibrancy 位置位的分支 0x1c4135084–0x1c413508c；探针 sdfdump ④ compositingFilter 无）→ source-over，不加 blend / isolation", "normal · auto", `${cs(lens).mixBlendMode} · ${cs(segc).isolation}`, cs(lens).mixBlendMode === "normal" && cs(segc).isolation === "auto");
        check("分段选中段无滤镜（--ios-segment-selected-filter）", "none", (cs(lens).backdropFilter || cs(lens).webkitBackdropFilter || "none"), /^none$/.test(cs(lens).backdropFilter || cs(lens).webkitBackdropFilter || "none")); }
      if (b) { num("分段文字 13（--ios-segment-label-size）", 13, px(cs(b).fontSize), 0.05); check("分段选中字重 500（--ios-medium-weight）", 500, cs(segc.querySelector("button.on") || b).fontWeight, String(cs(segc.querySelector("button.on") || b).fontWeight) === "500"); }
    }
    /* The confirm alert (closed, but its computed geometry is there) */
    const alert = document.querySelector("dialog#alert");
    if (alert) {
      num("弹窗宽 320（--ios-alert-w）", 320, px(cs(alert).width)); num("弹窗圆角 34（--ios-alert-radius）", 34, px(cs(alert).borderTopLeftRadius));
      const ab = alert.querySelector(".acts button"); if (ab) { num("弹窗按钮高 48（--ios-alert-button-h）", 48, px(cs(ab).height)); num("弹窗按钮圆角 24（--ios-alert-button-radius）", 24, px(cs(ab).borderTopLeftRadius)); }
      /* materials (spec-extract ⑨, end-to-end measured): pane = blur 20 (5 ÷ backdrop scale .25) · saturate 1.94 · brightness 1.071 + white .538 (dark 1.73 / .755 / .135) */
      const bf = (el) => cs(el).backdropFilter || cs(el).webkitBackdropFilter || "";
      const pane = alert.querySelector(".pane"), wantPane = dark ? "blur(20px) saturate(1.73) brightness(0.755)" : "blur(20px) saturate(1.94) brightness(1.071)";
      check("弹窗玻璃层是独立的 .pane（按钮的混合要看得见它）", "pane", pane ? "pane" : "缺", !!pane);
      check("弹窗玻璃滤镜链 = 端到端实测（--ios-alert-glass-filter：blur 20 · saturate · brightness）", wantPane, pane ? bf(pane).replace(/\s+/g, " ") : "缺", !!pane && bf(pane).replace(/\s+/g, " ") === wantPane);
      col("弹窗叠白（--ios-alert-glass-white .538 / 暗 .135）", dark ? [255, 255, 255, .135] : [255, 255, 255, .538], pane ? cs(pane).backgroundColor : "");
      col("弹窗遮罩（--ios-alert-dimming）", dark ? [0, 0, 0, .48] : [0, 0, 0, .2], varColor("--ios-alert-dimming", probe));
      check("弹窗玻璃无描边无阴影（pipeline #10）", "none", pane ? cs(pane).boxShadow : "缺", !!pane && cs(pane).boxShadow === "none");
      if (pane) { const pr = cs(pane); check("弹窗玻璃层外扩 60 pt 再用 clip-path 裁回 r34（marginWidth 60.2 ← ⑨；Safari 合成层不吃 overflow 圆角）", "top -60px / inset(60px round 34px)", `${pr.top} / ${pr.clipPath}`, /-60px/.test(pr.top) && /inset\(60px round 34px\)/.test(pr.clipPath)); check("dialog 上没有 clip-path（Chrome 会把它当 backdrop root，模糊失效）", "none", cs(alert).clipPath, cs(alert).clipPath === "none"); }
      { const want = innerHeight / 2 + 14, gotTop = px(cs(alert).top);   // 50dvh + 14 = 492 只在 web view 盖满 956 时成立（black-translucent；数据会话 fd61e71：default/black 下 web view 只有 894 高，中心 522）
        check("弹窗位置 = 整屏原生 frame（中心 = 屏高/2 + 14 → y 406 于 956，④）", `${Math.round(want * 10) / 10}px & translate -50%`, `${cs(alert).top} ${cs(alert).translate}`, Math.abs(gotTop - want) < 1 && /-50%/.test(cs(alert).translate)); }
      const at2 = alert.querySelector("h2"), am = alert.querySelector(".dlg-b");
      check("弹窗标题左对齐、labelColor（④ 帧 (30,22,260) / pipeline §1.9）", "left label", `${cs(at2).textAlign} ${cs(at2).color}`, cs(at2).textAlign === "left" && same(cs(at2).color, dark ? [255, 255, 255] : [0, 0, 0]));
      check("弹窗说明左对齐，底距 20.33（按钮顶 108 − 49.67 − 38，④）", "left 20.33px", `${cs(am).textAlign} ${cs(am).paddingBottom}`, cs(am).textAlign === "left" && near(px(cs(am).paddingBottom), 20.33, 0.05));
      if (CSS.supports("mix-blend-mode", "plus-darker")) check("弹窗说明字 = 面板 −0.4 / +0.3（pipeline §1.9：plus-darker rgb(153) / plus-lighter rgb(77)）", dark ? "rgb(77) plus-lighter" : "rgb(153) plus-darker", `${cs(am).color} ${cs(am).mixBlendMode}`, same(cs(am).color, dark ? [77, 77, 77] : [153, 153, 153]) && cs(am).mixBlendMode === (dark ? "plus-lighter" : "plus-darker"));
      else col("弹窗说明字 Chrome 常量（236 − 102 / 暗 35 + 76.5）", dark ? [111, 111, 111] : [134, 134, 135], cs(am).color);
      const cbtn = alert.querySelector("#alert-cancel"), okb = alert.querySelector("#alert-ok");
      if (cbtn) col("「取消」字 = labelColor（pipeline §1.9，不是 tint）", dark ? [255, 255, 255] : [0, 0, 0], cs(cbtn).color);
      if (okb) { okb.classList.add("danger"); col("「停止」字 = M_red × 按钮底（白底亮色实测 (235,42,45)，pipeline §1.9）", dark ? [255, 105, 108] : [235, 42, 45], cs(okb).color); check("「停止」按钮底透明（不再被 .acts button.danger 的白底盖住）", "rgba(0, 0, 0, 0)", cs(okb).backgroundColor, cs(okb).backgroundColor === "rgba(0, 0, 0, 0)"); okb.classList.remove("danger"); okb.classList.add("primary"); }
      check("弹窗面板无字区取样目标 ≈ (236,236,237)±3 亮 / 列表底 — 数据会话模拟器截图取样（accept 量不到像素）", "236±3", "见数据会话取样", true);
      const dbtn = alert.querySelector(".acts button:not(.primary)");
      if (dbtn) {
        const ov = cs(dbtn, "::before"), pd = CSS.supports("mix-blend-mode", "plus-darker");
        if (pd) { col("弹窗按钮 = 面板 −30.9/255：plus-darker 叠 rgb(224)（暗 +27.9 plus-lighter rgb(28)，pipeline §1.8）", dark ? [28, 28, 28] : [224, 224, 224], ov.backgroundColor); check("弹窗按钮混合模式", dark ? "plus-lighter" : "plus-darker", ov.mixBlendMode, ov.mixBlendMode === (dark ? "plus-lighter" : "plus-darker")); }
        else col("弹窗按钮 Chrome 等值常量 α .131 / .127（--ios-alert-button-fallback）", dark ? [255, 255, 255, .127] : [0, 0, 0, .131], ov.backgroundColor);
      }
    }
    /* Tab bar: hidden when the snapshot has a single tab (nav.hidden = present.size < 2);
       measure a synthetic one then, so the run does not depend on the data. */
    let seg = document.querySelector("nav.tabs:not([hidden]) .seg"), fakeNav = null;
    if (!seg) {
      fakeNav = document.createElement("nav"); fakeNav.className = "tabs"; fakeNav.style.visibility = "hidden";
      fakeNav.innerHTML = `<div class="plat"></div><i class="glide"></i><div class="seg"><button type="button" class="on"><span class="ico"><i class="sf"></i></span>状态</button><button type="button"><span class="ico"><i class="sf"></i></span>手机</button></div>`;
      document.body.appendChild(fakeNav); seg = fakeNav.querySelector(".seg");
    }
    if (seg) {
      const r = seg.getBoundingClientRect();
      num("标签栏胶囊高 62（--ios-tab-capsule-h，探针平台 274×62）", 62, r.height);
      num("标签栏胶囊内缩 4（--ios-tab-button-pad）", 4, px(cs(seg).paddingLeft));
      if (!fakeNav) {
        const gap = innerHeight - r.bottom;
        const standalone = matchMedia("(display-mode: standalone)").matches;
        if (standalone) num("标签栏底边距屏底 21（--ios-tab-capsule-bottom）", 21, gap);
        else check("标签栏在 Safari 地址栏之上", "> 0", Math.round(gap), gap > 0);
      }
      const bs = seg.querySelectorAll("button"), b = bs[0];
      if (b) {
        const w = b.getBoundingClientRect().width, want = Math.min(94, (r.width - 8) / bs.length);
        num("标签按钮高 54（--ios-tab-button-h）", 54, b.getBoundingClientRect().height);
        num(`标签按钮宽 ${Math.round(want * 100) / 100}（--ios-tab-button-w 94，${bs.length} 个标签放不下时等比缩）`, want, w);
        num("标签文字 10（--ios-tab-label-size）", 10, px(cs(b).fontSize), 0.05); num("标签按钮圆角 27（--ios-tab-lens-radius）", 27, px(cs(b).borderTopLeftRadius));
        const lb = [...b.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim()) || b.querySelector("span:not(.ico)");
        if (lb) { const rg = document.createRange(); rg.selectNodeContents(lb); const lr = rg.getBoundingClientRect(); num("标签文字顶 = 胶囊顶 + 39（--ios-tab-label-top）", 39, lr.top - r.top, 1.5); }
      }
      const ico = seg.querySelector(".ico"); if (ico) num("标签符号框 28（--ios-tab-symbol-box，探针 27–31）", 28, ico.getBoundingClientRect().height);
      const plat = seg.parentElement.querySelector(".plat") || seg, segbf = cs(plat).backdropFilter || cs(plat).webkitBackdropFilter || "";
      check("标签栏平台玻璃 blur 10（= --ios-glass-blur 5 ÷ backdrop scale .5 ← ⑨）", "blur(10px)", (/blur\([\d.]+px\)/.exec(segbf) || [])[0], /blur\(10px\)/.test(segbf));
      check("透镜不嵌在平台里（平台 backdrop-filter 是 backdrop root）", "sibling", seg.parentElement.querySelector(":scope > .glide") ? "sibling" : "nested", !!seg.parentElement.querySelector(":scope > .glide"));
      const gl = seg.parentElement.querySelector(".glide"); if (gl) { const gbf = cs(gl).backdropFilter || cs(gl).webkitBackdropFilter || "";
        check("标签栏选中透镜 blur 2（--ios-lens-blur）", "blur(2px)", (/blur\([\d.]+px\)/.exec(gbf) || [])[0], /blur\(2px\)/.test(gbf));
        const wantF = dark ? "blur(2px) saturate(1.379) brightness(0.763) contrast(1.14)" : "blur(2px) saturate(1.062) brightness(0.807) contrast(1.4)";
        check("标签栏透镜滤镜链 = 矩阵（--ios-lens-filter：blur · saturate · brightness · contrast）", wantF, gbf.replace(/\s+/g, " "), gbf.replace(/\s+/g, " ") === wantF);
        check("标签栏透镜无叠层（::after 不参与）", "none", cs(gl, "::after").content, cs(gl, "::after").content === "none");
        check("透镜滑动 0.55 s（--ios-motion-lens-duration，dampingRatio .85 / response .4）", "0.55s", cs(gl).transitionDuration.split(",")[0].trim(), /^0\.55s/.test(cs(gl).transitionDuration)); }
    }
    if (fakeNav) fakeNav.remove();
    const top = document.querySelector(".topbar");
    if (top) {
      const sat = satTop();
      num("顶栏高 = 安全区 + 54（--ios-nav-h，AX-45 NavigationBar (0,62,440,54)）", 54, top.getBoundingClientRect().height - sat);
    }
    const h1 = document.querySelector("header h1");
    if (h1) { num("大标题字号 34（--ios-large-title-size）", 34, px(cs(h1).fontSize), 0.1); num("大标题行框 40.57（--ios-large-title-lh）", 40.57, px(cs(h1).lineHeight), 0.05); check("大标题字重 700（NUMBERS 56）", 700, cs(h1).fontWeight, String(cs(h1).fontWeight) === "700"); }
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
    col("开关开 = 系统绿（--ios-switch-on）", T.green, cs(on).backgroundColor);
    col("开关关 = 灰（--ios-switch-off）", T.swOff, cs(off).backgroundColor);
    num("开关开：圆钮位移 22（--ios-switch-travel = 63 − 37 − 2×2）", 22, px(cs(on, "::after").translate));
    /* Finger down: the knob settles at 58×38 (spec §3 L*, Kit Toggle Pressed) = scale 1.568 × 1.583 of 37×24. */
    const held = lab.querySelectorAll(".sw")[1]; held.classList.add("live", "hold");
    check("按住：旋钮抬起动画 knob-lift（37×24 → 60.5×40 → 58×38，spec §3 L*）", "knob-lift .2s", `${cs(held.querySelector("span"), "::after").animationName} ${cs(held.querySelector("span"), "::after").animationDuration}`, cs(held.querySelector("span"), "::after").animationName === "knob-lift");
    check("按住：圆钮变半透明玻璃", "非纯白", cs(held.querySelector("span"), "::after").backgroundImage.slice(0, 15), /gradient/.test(cs(held.querySelector("span"), "::after").backgroundImage));
    held.classList.remove("hold");
    /* Motion tokens (spec-extract.md ⑤): knob 0.35 s on the probed spring, track 0.2 s. */
    const kt = cs(on, "::after");
    check("开关圆钮动效 0.35 s（--ios-motion-switch-knob-duration）", "0.35s", kt.transitionDuration.split(",")[0].trim(), /^0\.35s/.test(kt.transitionDuration));
    check("开关圆钮曲线 linear()（--ios-motion-switch-knob-easing）", "linear(…)", kt.transitionTimingFunction.slice(0, 12), /^linear\(/.test(kt.transitionTimingFunction));
    check("开关轨道交叉淡 0.2 s（--ios-motion-switch-track-duration）", "0.2s", cs(on).transitionDuration, /^0\.2s/.test(cs(on).transitionDuration));
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
    lab.remove(); probe.remove();
    const meta = document.querySelector('meta[name="theme-color"]');
    check("theme-color 存在", "是", meta ? "是" : "缺", !!meta);

    /* Interaction replays, one item per rule of remote-ref/interaction-spec.md (iOS 27 injected measurements, 2026-09-18).
       Events are synthetic PointerEvents with coordinates, so they exercise the page's own state machines exactly as a finger would
       (the browser's tap-vs-scroll disambiguation is not involved: the controls set touch-action: none). */
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const at = (el, fx = .5, fy = .5, dx = 0, dy = 0) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width * fx + dx, y: r.top + r.height * fy + dy }; };
    const pev = (el, type, p, id = 11) => el.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: id, clientX: p.x, clientY: p.y, isPrimary: true, button: 0, buttons: type === "pointerup" ? 0 : 1, pointerType: "touch" }));
    async function interactions() {
      /* Behaviour 5: the sheet element is hidden once the dismiss has travelled */
      { const sh = document.querySelector("#picker"); if (sh) { await sleep(600); check("勾选页关闭 0.5 s 后隐藏（open 去掉）", "hidden", sh.hasAttribute("open") ? "open" : "hidden", !sh.hasAttribute("open") && getComputedStyle(sh).display === "none"); } }
      /* Behaviour 1: one alert at a time; Chrome runs the pane flat until the appear animation ends (.settled), WebKit keeps it from frame 1 */
      if (typeof ask === "function" && document.querySelector("#alert")) {
        const d = document.querySelector("#alert"), pane = d.querySelector(".pane"), bf = (el) => getComputedStyle(el).backdropFilter || getComputedStyle(el).webkitBackdropFilter || "";
        const p1 = ask("测", "一", "好"); const p2 = ask("测二", "二", "好");
        const second = await Promise.race([p2.then((v) => `resolved ${v}`), sleep(50).then(() => "pending")]);
        check("弹窗重入保护：开着时再 ask 立即回 false，不叠第二层", "resolved false · 1 open", `${second} · ${document.querySelectorAll("dialog[open]").length} open`, second === "resolved false" && document.querySelectorAll("dialog[open]").length === 1);
        const chrome = !CSS.supports("mix-blend-mode", "plus-darker");
        check(chrome ? "弹窗出现动画期间玻璃层先走平底（Chrome 路：无 backdrop-filter）" : "弹窗出现动画期间玻璃层就是精确层（WebKit 路）", chrome ? "none" : "blur", bf(pane), chrome ? bf(pane) === "none" : /blur/.test(bf(pane)));
        await sleep(520);
        check("弹窗出现动画结束 → .settled，玻璃层到位（--ios-alert-glass-filter）", "settled + blur", `${d.classList.contains("settled") ? "settled" : "-"} + ${bf(pane).slice(0, 10)}`, d.classList.contains("settled") && /blur/.test(bf(pane)));
        check("弹窗首帧时间戳记录（?diag：alert f1/f2）", "f1 ≤ 40 ms", window.ALERT_T ? `f1 +${Math.round(ALERT_T.f1 - ALERT_T.open)} f2 +${Math.round(ALERT_T.f2 - ALERT_T.open)} ms` : "缺", !!window.ALERT_T && ALERT_T.f1 - ALERT_T.open <= 40);
        document.querySelector("#alert-cancel").click(); await sleep(450); await p1;
        check("弹窗取消后关闭", "closed", d.open ? "open" : "closed", !d.open);
      }
      /* Behaviour 2: placeholders before the first reading; the cached reading restores at once */
      if (window.Stamina && typeof numTiles === "function") {
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
      { const secs = [...document.querySelectorAll("#app > section")].filter((s) => /机器最近的回执/.test((s.querySelector("h2") || {}).textContent || ""));
        const sec = secs[0], rows = sec ? sec.querySelectorAll(".row:not(.nav)") : [], more = sec && sec.querySelector('.row.nav[data-page="receipts"]');
        if (sec) {
          check("首页回执最多 3 条 + 「查看全部 ›」（AX-13 显示所有健康数据 ›）", "≤3 + 查看全部", `${rows.length} + ${more ? "查看全部 " + more.querySelector(".val").textContent : "-"}`, rows.length <= 3 && (!more || rows.length === 3));
          if (more) {
            const pg = document.querySelector("#subpage"); more.click(); await sleep(80);
            check("推入页打开（.in）、标题「回执」", "in 回执", `${pg.classList.contains("in") ? "in" : "-"} ${pg.querySelector(".ptitle").textContent}`, pg.classList.contains("in") && pg.querySelector(".ptitle").textContent === "回执");
            { const x80 = pg.getBoundingClientRect().left; check("推入 +80 ms：新页从右边滑入中（440 → 0，0.35 s）", "0 < x < 440", `x ${Math.round(x80)}`, x80 > 0 && x80 < 440); }
            await sleep(400);
            const pr = pg.querySelector(".pnav").getBoundingClientRect(), bb = pg.querySelector(".pback").getBoundingClientRect(), sat = satTop();
            num("推入页导航栏 54 在安全区顶（AX-11 / AX-46 (0,62,440,54)）", sat, pr.top); num("推入页导航栏高 54", 54, pr.height);
            num("推入页返回钮 44 at x 20（AX-11 BackButton (20,62,44,44)）", 44, bb.width); num("推入页返回钮 x 20", 20, bb.left);
            check("推入页按日分组（Health 显示所有数据 AX-11：一天一组）", "≥1 组 h2 月日", `${pg.querySelectorAll(".pbody h2").length} 组 ${(pg.querySelector(".pbody h2") || {}).textContent}`, pg.querySelectorAll(".pbody h2").length >= 1 && /\d+月\d+日/.test((pg.querySelector(".pbody h2") || {}).textContent || ""));
            check("推入 0.35 s（--ios-motion-nav-push-duration）、旧页视差 30 %", "0.35s pushed", `${getComputedStyle(pg).transitionDuration} ${document.body.classList.contains("pushed") ? "pushed" : "-"}`, getComputedStyle(pg).transitionDuration === "0.35s" && document.body.classList.contains("pushed"));
            pg.querySelector(".pback").click(); await sleep(450);
            check("推入页返回：弹出后隐藏、旧页回位", "hidden", `${pg.hidden ? "hidden" : "shown"} ${document.body.classList.contains("pushed") ? "pushed" : "back"}`, pg.hidden && !document.body.classList.contains("pushed"));
          }
        }
      }
      const q = () => document.querySelector("#queueseg"), bs = () => [...document.querySelectorAll("#queueseg button")];
      const onText = () => (document.querySelector("#queueseg button.on") || {}).textContent || "";
      const thisShift = (name) => { const sec = [...document.querySelectorAll("#app section")].find((x) => ((x.querySelector("h2") || {}).textContent || "").trim() === "这一趟"); return !!sec && [...sec.querySelectorAll(".row label")].some((l) => l.textContent.includes(name + " · ")); };
      /* count page renders synchronously (a MutationObserver fires a microtask later than the same-tick assertions need) */
      let renders = 0; const origRender = window.render; window.render = function () { renders++; return origRender.apply(this, arguments); };
      if (q()) {
        const start = onText();
        /* §1 G15: touch-down on the unselected segment - value, lens and content unchanged; its label dims towards .2 over .43 s */
        let seg = q(), other = bs().find((b) => !b.classList.contains("on")), want = other.textContent, i0 = seg.style.getPropertyValue("--i");
        const r0 = renders; pev(seg, "pointerdown", at(other));
        check("分段 G15 按下未选中段：index / 透镜 / 内容都不动", start, `${onText()} --i=${seg.style.getPropertyValue("--i")} renders+${renders - r0}`, onText() === start && seg.style.getPropertyValue("--i") === i0 && renders === r0 && thisShift(start));
        check("分段 G15 按下未选中段：标签变暗 .2 / .43 s ease-out（--ios-touch-segment-dim-*）", "opacity→.2 .43s", `${cs(other).opacity}→${other.classList.contains("dim") ? ".2" : "?"} ${cs(other).transitionDuration}`, other.classList.contains("dim") && /0\.43s/.test(cs(other).transitionDuration));
        /* §1 G3: a 300 ms hold still selects nothing */
        await sleep(300);
        check("分段 G3 按住 300 ms 不选中", start, onText(), onText() === start && renders === r0);
        /* §1 G1–G3 + B3: the up commits index + change + content together, in the up's own task (view.js SEG_VC_NOW, 换值即抬手 — 监督局 09-19 15:5x; the native's
           switch shows at up +50…92 in its recordings, seg-value-change-content.md §0, the page's with the +66 ms timer at +136…143 on the phone, data 78284dd) */
        const t0 = performance.now(); pev(seg, "pointerup", at(other)); const dt = performance.now() - t0;
        check("分段 G1 抬手 +0：换值即抬手——选中态（标签 .on）与内容同一任务一帧替换（view.js SEG_VC_NOW；原 +66 计时器 + vcsplit 在真机落到抬手 +136…143，原生 +50…92 ← seg-value-change-content.md §0 / 数据 78284dd；?vcnow=0 回计时器）", `${want} renders+1`, `${onText()} renders+${renders - r0}`, onText() === want && renders === r0 + 1);
        await sleep(100);
        check("分段 G1 抬手 +100 ms：选中态与内容保持已换（只重画一次）；透镜由点按链自抬手起动", want, `${onText()} renders+${renders - r0}`, onText() === want && thisShift(want) && renders === r0 + 1);
        { const gone = document.querySelectorAll(".flipgone"), moved = [...document.querySelectorAll("#app > section")].filter((s) => /translateY\((-?[\d.]+)px\)/.test(s.style.transform) && Math.abs(parseFloat(s.style.transform.match(/translateY\((-?[\d.]+)px\)/)[1])) > 20);
          const elF = performance.now() - t0, wantF = tabAt(FLIP_DEL_FADE, elF);   // the switch is at the up itself now: the clone's opacity read against view.js's §1 table at the actual elapsed time
          check("分段 B3 换值后 +100 ms：卡片内容已换（renders+1）；删的行原地克隆在淡出途中（起 .72，+193 到 .04，切换即抬手：按实际时刻查 FLIP_DEL_FADE ± .15，一帧 rAF 步进的滞后）、下方内容仍从原位（+行高）上滑（seg-value-change-content.md §0/§1，采样）", `clone ${wantF.toFixed(2)} ± .15 @ ${elF.toFixed(0)} ms · sections offset`, `${gone.length} clones ${gone.length ? cs(gone[0]).opacity : "-"} · ${moved.length} sections offset ${moved.length ? moved[0].style.transform : "-"}`, gone.length > 0 && Math.abs(parseFloat(cs(gone[0]).opacity) - wantF) <= .15 && moved.length > 0); }
        const lensNow = q().querySelector(".lens");
        { const lp0 = q().__lensLoop; check("分段 G1 抬手：点按走 segLens 点按链（seg-lens-refraction §4.4：up +82 抬起几何 ζ1/.25 原位、+92 材质、+98 换值行程 ζ.85/.4、+443/+450 落回；view.js SEG_TAP_T），不再走 CSS 关键帧滑行", "loop phase tap · no lens-stretch", `${lp0 ? (lp0.state.done ? "done" : (lp0.diag ? lp0.diag.phase : "no tick")) : "no loop"} · ${cs(lensNow).animationName}`, !!lp0 && !lp0.state.done && !!lp0.diag && lp0.diag.phase === "tap" && cs(lensNow).animationName !== "lens-stretch"); }
        await sleep(192);
        { const lr = lensNow.getBoundingClientRect(), sr = q().getBoundingClientRect(), lp = parseFloat(q().style.getPropertyValue("--lp") || "0"), c = lr.left + lr.width / 2 - sr.left, el = (performance.now() - t0) / 1000;
          const NT = [[.236, 229.65, 230.3], [.253, 240.8, 235.8], [.271, 249.8, 240.8], [.286, 257.15, 242.9], [.303, 263.6, 241.6], [.320, 269.25, 238.3], [.336, 274.6, 233.8], [.353, 279.55, 228.5], [.370, 284.2, 222.8]];   // native seg-native-tap-frames.json: t since up → lens centre (control coords = page − 20), width
          let nc = NT[NT.length - 1][1], nw = NT[NT.length - 1][2]; for (let i = 1; i < NT.length; i++) if (el <= NT[i][0]) { const a = NT[i - 1], b = NT[i], u = Math.max(0, (el - a[0]) / (b[0] - a[0])); nc = a[1] + (b[1] - a[1]) * u; nw = a[2] + (b[2] - a[2]) * u; break; }
          check("分段 G1 抬手 +272 ms：玻璃滑行中（--lp ≥ .8）、拉长（原生 seg-native-tap-frames.json 同时刻插值：中心 / 宽，控件坐标；容 ± 12；计时器实际时刻一并报）", `lp ≥ .8 · w ${nw.toFixed(1)} ± 12 · centre ${nc.toFixed(1)} ± 12 @ ${el.toFixed(3)}`, `lp ${lp.toFixed(3)} · w ${lr.width.toFixed(1)} · centre ${c.toFixed(1)}`, lp >= .8 && Math.abs(lr.width - nw) <= 12 && Math.abs(c - nc) <= 12); }
        { const gone = document.querySelectorAll(".flipgone"), moved = [...document.querySelectorAll("#app > section")].filter((s) => /translateY/.test(s.style.transform)), insR = [...document.querySelectorAll("#app .row")].filter((r) => r.style.opacity !== "" && parseFloat(r.style.opacity) < 1);
          const elI = performance.now() - t0, wantI = tabAt(FLIP_INS, elI);   // the inserted rows against view.js's §2 table at the actual elapsed time (the switch is at the up)
          check("分段 B3 抬手 +292 ms：删的行淡到 ≤ .10（§1 +193 .04）、下方内容上滑途中（§0 +177 剩 24/133，+400 到位）、插的行淡入途中（§2 表按实际时刻查 FLIP_INS ± .15）", `clone ≤ .12 · sections still offset · inserted ${wantI.toFixed(2)} ± .15 @ ${elI.toFixed(0)} ms`, `${gone.length ? cs(gone[0]).opacity : "no clone"} · ${moved.length} moving · ${insR.length} fading in ${insR.length ? insR[0].style.opacity : ""}`, gone.length > 0 && parseFloat(cs(gone[0]).opacity) <= 0.12 && moved.length > 0 && (insR.length > 0 ? Math.abs(parseFloat(insR[0].style.opacity) - wantI) <= .15 : wantI >= .95)); }
        await sleep(284);
        { const lr = lensNow.getBoundingClientRect(), sr = q().getBoundingClientRect(), lw = lensNow.offsetWidth, toI = parseFloat(q().style.getPropertyValue("--i")), fromI = toI === 1 ? 0 : 1;
          const segW = (sr.width / bs().length - 4), pos = (lr.left + lr.width / 2 - sr.left - 2 - segW / 2) / segW;   // centre-based in segment units (the lens now moves by `left`, its width breathes)
          num("分段 G1 抬手 +556 ms：透镜在目标外过冲途中（原生 seg-native-tap-frames.json up+.553 中心 307.55 → 行程 1.038；换值弹簧 ζ.85/.4 + flex 漂移）", 1.038, (pos - fromI) / (toI - fromI), 0.05); }
        check("分段 B3 +476 ms：内容过渡收尾（+400 到位 → 克隆移除、transform / opacity 内联清空）", "clean", `${document.querySelectorAll(".flipgone").length} clones · ${[...document.querySelectorAll("#app > section, #app .row")].filter((e) => e.style.transform || e.style.opacity).length} inline`, !document.querySelectorAll(".flipgone").length && ![...document.querySelectorAll("#app > section, #app .row")].some((e) => e.style.transform || e.style.opacity));
        await sleep(800);
        /* §1 G4/G16: touch-down on the selected segment lifts the lens after ~100 ms (196×28 → 220×44), no event */
        seg = q(); let sel = bs().find((b) => b.classList.contains("on")), unsel = bs().find((b) => !b.classList.contains("on"));
        const r1 = renders; pev(seg, "pointerdown", at(sel)); const lens0 = seg.querySelector(".lens");
        check("分段 G4 按下已选中段：+0 ms 透镜未抬、无事件", "no lift", lens0.classList.contains("lift") ? "lift" : "no lift", !lens0.classList.contains("lift") && renders === r1);
        await sleep(160);
        const h160 = lens0.getBoundingClientRect().height;
        check("分段 G16 按下已选中段 +160 ms：透镜抬起中（+109 ms 起，--ios-motion-seg-lift-easing .35 s 到 220×44；seg-lens-refraction §4.1）", "lift, 28 < h < 44", `${lens0.classList.contains("lift") ? "lift" : "-"} h ${h160.toFixed(1)}`, lens0.classList.contains("lift") && h160 > 28.5 && h160 < 43.5);
        /* lifted lens = glass ABOVE the labels + punched-out labels + a warped copy inside (uiprobe-lensdiff-seg: ClearGlassView / DestOutView /
           liftedContentWarpWrapper); --lp on the lenstrace curve (lens-refraction §4.1: 86 % at 153 ms) drives glass + warp */
        const GLON = seg.classList.contains("gl");   // WebGL lens (view.js segGlCreate, lens-webgl.js): the SVG stack is built but hidden — its checks are recorded, not judged
        const svgcheck = GLON ? ((name, want) => check(name + "【GL 模式：SVG 栈隐藏，不核】", want, "gl", true)) : check, svgnum = GLON ? ((name, want) => check(name + "【GL 模式：SVG 栈隐藏，不核】", String(want), "gl", true)) : num;
        { const lp = parseFloat(seg.style.getPropertyValue("--lp")), warp = seg.querySelector(".warp"), warpl = seg.querySelector(".warpl"), cb = warpl ? warpl.querySelectorAll(".copy .cb").length : 0;
          check("分段抬起 +160 ms：玻璃/位移进度 --lp = 透镜尺寸进度（§4.1：尺寸、圆角、位移量、白平台同一条曲线）", "0 < lp < 1, = (h−28)/16", `${lp} vs ${((lens0.getBoundingClientRect().height - 28) / 16).toFixed(3)}`, lp > 0 && lp < 1 && Math.abs(lp - (lens0.getBoundingClientRect().height - 28) / 16) < 0.12);
          svgcheck("分段抬起：透镜层在标签之上（z 2）", "2", cs(lens0).zIndex, cs(lens0).zIndex === "2" && seg.classList.contains("lift"));
          { const br = px(cs(lens0).borderRadius), hh = lens0.getBoundingClientRect().height; check("分段抬起：几何走 width/height（真胶囊：圆角 = 高/2，14 → 22 与尺寸同曲线；seg-lens-refraction §0 220×44 r22）", "r ≈ h/2", `r ${br.toFixed(1)} h ${hh.toFixed(1)}`, Math.abs(br - hh / 2) < 1.2 && cs(lens0).scale === "1"); }
          { const punch = warp && warp.querySelector(".disp .punch"), pcp = punch && punch.querySelector(".copy .cb"), SSa = window.LENS_SS || 1;   // 引擎校正 2 (lens-supersample.js): the filtered layer is SS× the box inside a wrapper scaled 1/SS
            svgcheck("分段抬起：底图复本 .warp 过 #seg-lens-f-bg-220、标签复本 .warpl 过 #seg-lens-f-lab-220（220 组，滤镜层 = 透镜盒 overflow hidden ← ui2 README §0.3）；B4-c' §4b：标签复本 = 整盒先裁胶囊再位移、无 196×28 门户；底图复本带 .punch（标签复本挖掉胶囊 = DestOut，clip-path evenodd）", `${bs().length} cb · disp url(#seg-lens-f-bg-220) · displ url(#seg-lens-f-lab-220) · no .portal · punch evenodd`, `${cb} cb · ${warp ? cs(warp.querySelector(".disp")).filter.slice(0, 26) : "-"} · ${warpl ? cs(warpl.querySelector(".displ")).filter.slice(0, 27) : "-"} · ${warpl && warpl.querySelector(".portal") ? "portal!" : "no .portal"} · ${punch ? (cs(punch).clipPath.startsWith("path(evenodd") ? "punch evenodd" : cs(punch).clipPath.slice(0, 20)) : "no punch"} ${pcp ? "+labels" : ""}`, !!warp && !!warpl && cb === bs().length && bs().length === 2 && /inset/.test(cs(warp).clipPath) && /inset/.test(cs(warpl).clipPath) && /url\("?#seg-lens-f-bg-220"?\)/.test(cs(warp.querySelector(".disp")).filter) && cs(warp.querySelector(".disp")).overflow === "hidden" && Math.abs(warp.querySelector(".disp").getBoundingClientRect().width - warp.getBoundingClientRect().width) < 0.5 && Math.abs(warp.querySelector(".disp").offsetWidth - SSa * warp.getBoundingClientRect().width) < 1 && /url\("?#seg-lens-f-lab-220"?\)/.test(cs(warpl.querySelector(".displ")).filter) && !warpl.querySelector(".portal") && Math.abs(px(cs(warpl.querySelector(".displ")).borderRadius) - SSa * warpl.getBoundingClientRect().height / 2) < 1.5 * SSa && !!punch && cs(punch).clipPath.startsWith("path(evenodd") && !!pcp); }
          { const cp = warp && warp.querySelector(".copy"), cpl = warpl && warpl.querySelector(".copy"), bgw = cp && cp.querySelector(".cbgwrap");
            check("分段抬起：复本不放大（mag-x 1.00 / label-mag 1.00，zoom 1）、底不透明、底不过色矩阵（透镜内亮度 = 底）", "zoom 1 · opaque · no filter", `${cp ? cs(cp).zoom : "-"} / ${cpl ? cs(cpl).zoom : "-"} · bg ${cs(cp.querySelector(".cbg")).backgroundColor.slice(0, 4)} · ${bgw ? cs(bgw).filter : "-"}`, !!cp && !!cpl && cs(cp).zoom === "1" && cs(cpl).zoom === "1" && /^rgb\(/.test(cs(cp.querySelector(".cbg")).backgroundColor) && !!bgw && cs(bgw).filter === "none" && !!cp.querySelector(".cbgwrap .ctrack"));   // cp = the first .copy of .warp (the page + track one)
            const fd = document.querySelector("#seg-lens-f-bg-220 feDisplacementMap"); svgcheck("分段抬起：位移量 scale = S × SS × 进度（S = 该组 filter 的 data-s0 / data-s，220 组 40 ← ui2 c4efe4b；SS = 引擎校正 2 的倍数 window.LENS_SS，lens-supersample.js 把 data-s 写成 S × SS；同一条曲线）", `≈ 40·${window.LENS_SS || 1}·lp`, `${fd ? fd.getAttribute("scale") : "-"} (data-s ${document.querySelector("#seg-lens-f-bg-220").getAttribute("data-s")})`, !!fd && (document.querySelector("#seg-lens-f-bg-220").getAttribute("data-s0") || document.querySelector("#seg-lens-f-bg-220").getAttribute("data-s")) === "40" && Math.abs(parseFloat(fd.getAttribute("scale")) - 40 * (window.LENS_SS || 1) * lp) < 0.8 * (window.LENS_SS || 1));
            const pl = seg.querySelector(".plat"); check("分段抬起：白平台层 .plat 在底复本之上、标签复本之下（z 5 / 7；B6 的 .rimb 在两者之间 z 6），opacity = 1 − lp（restingBackground 1 → 0，seg-keys -platter-keys）；底复本 opacity = DestOut（前 3 帧到 1，-destout-keys）；标签复本不淡", "1−lp · warp 1 · warpl 1 · z 5/7", `${pl ? cs(pl).opacity : "-"} · ${cs(warp).opacity} · ${cs(warpl).opacity} · z ${pl ? cs(pl).zIndex : "-"}/${cs(warpl).zIndex}`, !!pl && Math.abs(parseFloat(cs(pl).opacity) - (1 - lp)) < 0.03 && parseFloat(cs(warp).opacity) > 0.95 && cs(warpl).opacity === "1" && cs(pl).zIndex === "5" && cs(warpl).zIndex === "7"); }
          if (warp) { const wr = warp.getBoundingClientRect(), lr = lens0.getBoundingClientRect();
            svgnum("分段抬起：复本框 = 透镜呈现框（左）", lr.left, wr.left, 0.6); svgnum("分段抬起：复本框 = 透镜呈现框（宽）", lr.width, wr.width, 0.6); }
          check("分段抬起：真标签不挖洞（不透明复本盖住 = DestOut 冲掉的视觉），透镜层自身不画阴影（B6：无 ::after、无 box-shadow）", "no mask · none", `${cs(sel).maskImage} · ${cs(lens0, "::after").content} ${cs(lens0).boxShadow}`, cs(sel).maskImage === "none" && cs(lens0, "::after").content === "none" && cs(lens0).boxShadow === "none"); }
        await sleep(240);
        { const r4 = lens0.getBoundingClientRect(), segW = seg.getBoundingClientRect().width / bs().length - 4;
          check("分段 G16 +400 ms：透镜到 220×44（段宽 + 24 × 44；几何 +359 ms 到位 ← seg-lens-refraction §4.1；--ios-touch-segment-lift-x 12 / -y 8）", `${(segW + 24).toFixed(1)}×44`, `${r4.width.toFixed(1)}×${r4.height.toFixed(1)}`, Math.abs(r4.width - (segW + 24)) < 0.8 && Math.abs(r4.height - 44) < 0.8); }
        check("分段抬起 +400 ms：--lp 到 1", "≈ 1", seg.style.getPropertyValue("--lp"), parseFloat(seg.style.getPropertyValue("--lp")) > 0.97);
        /* B6: the lifted lens's lines and shadows from the decompiled formulas (index.html "B6" block, view.js SEG_RIM; keyfill-highlight.md §2 / §4 / §5.1 / §5.2, keys seg-lens-refraction.md §1c(g)) */
        { svgcheck("分段抬起满：透镜内亮度 = 底（seg-lens-refraction §3 平灰 128 → 126：可见层不套 vibrantColorMatrix、不模糊）", "no filter", (cs(lens0).backdropFilter || "none") + " · " + cs(seg.querySelector(".warp .disp")).filter.slice(0, 26), (cs(lens0).backdropFilter || "none") === "none" && /url/.test(cs(seg.querySelector(".warp .disp")).filter));
          const rb = seg.querySelector(".rimb"), hlAll = [...seg.querySelectorAll(".hlk, .hlw")], hk = seg.querySelector(".hlk.m"), hw = seg.querySelector(".hlw.m"), lpNow = parseFloat(seg.style.getPropertyValue("--lp"));
          check("分段抬起满 B6：边线分两层——.rimb（标签复本之下 z 6：内阴影 + ring shadow + 外侧暗线）、.hlk/.hlw（之上 z 8：高光黑栈 / 白 plus-lighter 栈，三次合成的顺序 = 黑主带、白主带、黑漫射、白漫射），随 --lp 淡入", "z 6 / 8 · k.m w.m k.d w.d · plus-lighter · lp", `z ${rb ? cs(rb).zIndex : "-"} / ${hk ? cs(hk).zIndex : "-"} · ${hlAll.map((e) => e.getAttribute("class").replace(/^hl/, "").split(" ").join(".")).join(" ")} · ${hw ? cs(hw).mixBlendMode : "-"} · ${hw ? cs(hw).opacity : "-"}`, !!rb && !!hk && !!hw && cs(rb).zIndex === "6" && hlAll.length === 4 && hlAll.every((e) => cs(e).zIndex === "8") && hlAll.map((e) => e.getAttribute("class")).join("|") === "hlk m|hlw m|hlk d|hlw d" && cs(hw).mixBlendMode === "plus-lighter" && cs(hk).mixBlendMode === "normal" && Math.abs(parseFloat(cs(hw).opacity) - lpNow) < 0.03 && Math.abs(parseFloat(cs(rb.firstElementChild).opacity) - lpNow) < 0.03);
          const ish = rb && rb.querySelector(".ish"), rs = rb && rb.querySelector("rect.rs"), kfs = rb ? [...rb.querySelectorAll("rect.kf")] : [];
          { const f = document.querySelector("#seg-lens-f-ish"), off = f && f.querySelector("feOffset"), bl = f && f.querySelector("feGaussianBlur"), fa = f && f.querySelector("feFuncA");
            check("分段抬起满 B6 ④：内阴影 #21 = op·M·blur_σ3(M − M↓7)（keyfill §5.2c，2号 #seg-lens-f-ish：feOffset 7 → out → blur 3 → in → α × .06，黑胶囊 = 透镜盒；dy / σ / slope 随 --lp）", `filter #seg-lens-f-ish · bg #000 · dy ${(7 * lpNow).toFixed(2)} σ ${(3 * lpNow).toFixed(2)} slope ${(.06 * lpNow).toFixed(3)}`, ish ? `${cs(ish).filter.slice(0, 24)} · ${cs(ish).backgroundColor} · dy ${off ? off.getAttribute("dy") : "-"} σ ${bl ? bl.getAttribute("stdDeviation") : "-"} slope ${fa ? fa.getAttribute("slope") : "-"}` : "no .ish", !!ish && /seg-lens-f-ish/.test(cs(ish).filter) && cs(ish).backgroundColor === "rgb(0, 0, 0)" && !!off && Math.abs(parseFloat(off.getAttribute("dy")) - 7 * lpNow) < 0.1 && Math.abs(parseFloat(bl.getAttribute("stdDeviation")) - 3 * lpNow) < 0.05 && Math.abs(parseFloat(fa.getAttribute("slope")) - .06 * lpNow) < 0.002); }
          svgcheck("分段抬起满 B6 ③：ring shadow = 胶囊下移 8、内缩 2 的 4 宽描边 黑 .1 + feGaussianBlur 3（keys offset 8 / opacity .1 / stroke 4 / blur 3 / mask 0）", "y 10 · x 2 · rx h/2 − 2 · sw 4 · .1 · blur", rs ? `y ${rs.getAttribute("y")} x ${rs.getAttribute("x")} rx ${parseFloat(rs.getAttribute("rx")).toFixed(2)} · sw ${cs(rs).strokeWidth} · ${cs(rs).strokeOpacity} · ${cs(rs).filter.slice(0, 20)}` : "-", !!rs && rs.getAttribute("y") === "10" && rs.getAttribute("x") === "2" && Math.abs(parseFloat(rs.getAttribute("rx")) - (lens0.getBoundingClientRect().height / 2 - 2)) < 0.15 && cs(rs).strokeWidth === "4px" && cs(rs).strokeOpacity === "0.1" && /url/.test(cs(rs).filter) && rb.querySelector("feGaussianBlur").getAttribute("stdDeviation") === "3");
          const darkT = matchMedia("(prefers-color-scheme: dark)").matches || document.documentElement.dataset.theme === "dark", expA = darkT ? [0.728, 0.520, 0.312] : [0.317, 0.226, 0.136];   // B6-c §1: k_tip = v (.875 / .625 / .375), × .3 × (3 − 2B_track) (light B ≈ .897 → 1.206; dark ≈ .114 → 2.773)
          const kfa = kfs.map((k) => parseFloat(k.getAttribute("stroke-opacity"))), kfW = kfs.map((k) => parseFloat(k.getAttribute("stroke-width"))), kfY = kfs.map((k) => parseFloat(k.getAttribute("y")));
          svgcheck("分段抬起满 B6 ②：外侧暗线 = 三个 1/3 pt 描边环（中线 y −.5 / −.167 / +.167：胶囊外 .667 → 内 .333），黑 α = .3·k_tip·(3 − 2B_track)（k_tip = v .875 / .625 / .375，B6-c §1 去压缩；" + (darkT ? "暗 B ≈ 29/255" : "亮 B ≈ 229/255") + "），横向渐变 = k(x)/k_tip、纵向遮罩 = 页面因子", `3 rings · α ≈ ${expA.join("/")} · y −.5/−.167/.167 · gradient + mask`, `${kfs.length} rings · α ${kfa.map((x) => x.toFixed(3)).join("/")} · y ${kfY.map((x) => x.toFixed(3)).join("/")} · w ${kfW.map((x) => x.toFixed(3)).join("/")} · ${kfs.length && /url/.test(kfs[0].getAttribute("stroke")) ? "gradient" : "-"} ${kfs.length && kfs[0].parentElement.getAttribute("mask") ? "mask" : "-"}`,
            kfs.length === 3 && kfa.every((x, n) => Math.abs(x - expA[n]) < 0.012) && kfY.every((y, n) => Math.abs(y - [-0.5, -1 / 6, 1 / 6][n]) < 0.001) && kfW.every((w) => Math.abs(w - 1 / 3) < 0.001) && kfs.every((k) => /url/.test(k.getAttribute("stroke"))) && !!kfs[0].parentElement.getAttribute("mask"));
          const hkR = hk ? [...hk.querySelectorAll("line")] : [], hwR = hw ? [...hw.querySelectorAll("line")] : [], hdR = [...seg.querySelectorAll(".hlk.d rect")], hdW = [...seg.querySelectorAll(".hlw.d rect")];
          svgcheck("分段抬起满 B6 ①：内侧亮线 + 高光尾 = #36 层公式：黑栈 stroke-opacity .0882·α / 白栈 .1471·α，主带 3 环 × 上下两条直线（B6-c §4b：只画直边 x ∈ [R, W−R]，纯色；首环 α .875）+ 漫射 10 环（首环 .803，渐变描边）", "6+6 lines · 10+10 · .0772/.1287 · .0708/.1181 · x1 R x2 W−R", `${hkR.length}+${hwR.length} · ${hdR.length}+${hdW.length} · ${hkR.length ? hkR[0].getAttribute("stroke-opacity") : "-"}/${hwR.length ? hwR[0].getAttribute("stroke-opacity") : "-"} · ${hdR.length ? hdR[0].getAttribute("stroke-opacity") : "-"}/${hdW.length ? hdW[0].getAttribute("stroke-opacity") : "-"} · ${hkR.length ? `x1 ${hkR[0].getAttribute("x1")} x2 ${hkR[0].getAttribute("x2")} ${hkR[0].getAttribute("stroke")}` : "-"}`,
            hkR.length === 6 && hwR.length === 6 && hdR.length === 10 && hdW.length === 10 && Math.abs(parseFloat(hkR[0].getAttribute("stroke-opacity")) - 0.0882 * 0.875) < 0.001 && Math.abs(parseFloat(hwR[0].getAttribute("stroke-opacity")) - 0.1471 * 0.875) < 0.001 && Math.abs(parseFloat(hdR[0].getAttribute("stroke-opacity")) - 0.0882 * 0.803) < 0.001 && Math.abs(parseFloat(hdW[0].getAttribute("stroke-opacity")) - 0.1471 * 0.803) < 0.001 && hkR.every((l) => l.getAttribute("stroke") === "#000") && hdR.every((r) => /url/.test(r.getAttribute("stroke"))) && Math.abs(parseFloat(hkR[0].getAttribute("stroke-width")) - 1 / 3) < 0.001 && Math.abs(parseFloat(hkR[0].getAttribute("x1")) - lens0.getBoundingClientRect().height / 2) < 0.6 && Math.abs(parseFloat(hkR[0].getAttribute("x2")) - (lens0.getBoundingClientRect().width - lens0.getBoundingClientRect().height / 2)) < 0.6);
          if (GLON) { const c = seg.querySelector("canvas.glens"), g = seg.__gl, sr = seg.getBoundingClientRect(), cr = c && c.getBoundingClientRect(), lr = lens0.getBoundingClientRect(), fr0 = g ? g.lens.stats.frames : 0, F1 = window.LensWebGL ? LensWebGL.FS1 + LensWebGL.FS2 + LensWebGL.COMMON : "";
            check("分段 WebGL：canvas.glens 盖住控件 ± 24 pt（宽 = 控件，高 = 控件 + 48；README §0.8.7：包裹 = 透镜 ± 16 + 抬起外扩 6，环影下延 11），指针穿透，z 9", "box = seg ± 24 · pointer-events none · z 9", c ? `dx ${(cr.left - sr.left).toFixed(1)} dy ${(cr.top - sr.top).toFixed(1)} w ${(cr.width - sr.width).toFixed(1)} h ${(cr.height - sr.height).toFixed(1)} · ${cs(c).pointerEvents} · z ${cs(c).zIndex}` : "no canvas", !!c && Math.abs(cr.left - sr.left) < .6 && Math.abs(cr.top - sr.top + 24) < .6 && Math.abs(cr.width - sr.width) < .6 && Math.abs(cr.height - sr.height - 48) < .6 && cs(c).pointerEvents === "none" && cs(c).zIndex === "9");
            check("分段 WebGL：LensWebGL 实例走 220 组（README §0.3：抬起与拖动都在模型宽的那组），有帧在画（stats.frames 递增、set 220）", "set 220 · frames > 0", g ? `set ${g.lens.stats.set} · frames ${g.lens.stats.frames} · gpu ${g.lens.stats.gpuMs.toFixed(2)} ms` : "no instance", !!g && g.lens.stats.set === 220 && g.lens.stats.frames > 0);
            check("分段 WebGL：flex 变换加在 canvas 上、原点 = 透镜中心（canvas 坐标 = 透镜盒中心 + 24 pt）", "origin = lens centre", c ? `${c.style.transformOrigin || "-"} vs ${(lr.left - sr.left + lr.width / 2).toFixed(1)}px ${(lr.top - sr.top + 24 + lr.height / 2).toFixed(1)}px` : "-", !!c && (() => { const m = /([\d.]+)px ([\d.]+)px/.exec(c.style.transformOrigin || ""); return !!m && Math.abs(parseFloat(m[1]) - (lr.left - sr.left + lr.width / 2)) < 1.5 && Math.abs(parseFloat(m[2]) - (lr.top - sr.top + 24 + lr.height / 2)) < 1.5; })());
            check("分段 WebGL：白平台淡出在 shader 里（dc2af2a u_platter：位移底图之上、边线/标签之下，alpha 1 − p，_controlForegroundColor 令牌），.lens 抬起时透明如 SVG 路径", "u_platter · .lens transparent z 2", `${F1 && F1.includes("u_platter") ? "u_platter" : "no u_platter"} · ${cs(lens0).backgroundColor} z ${cs(lens0).zIndex}`, !!F1 && F1.includes("u_platter") && /rgba\(0, 0, 0, 0\)|transparent/.test(cs(lens0).backgroundColor) && cs(lens0).zIndex === "2");
            check("分段 WebGL：SVG 栈隐藏（.stack / .rimo / .hlk / .hlw display none）", "none ×4", [".stack", ".rimo", ".hlk", ".hlw"].map((q) => { const e = seg.querySelector(q); return e ? cs(e).display : "-"; }).join(" "), [".stack", ".rimo", ".hlk", ".hlw"].every((q) => { const e = seg.querySelector(q); return !e || cs(e).display === "none"; }));
            check("分段 WebGL：着色器里是反编译常量（暗线 EffectOffset −.6667 / colorBias −.3、vibrant V = min(1, .9118·b + .1471)、环影 8 / 4 / σ3 / .1；色散 Δ 与 aberration 2.3158 在贴图里）", "all present", ["0.6667", "-0.3", "0.9118", "0.1471"].map((k) => (F1.includes(k) ? "✓" : "✗") + k).join(" "), ["0.6667", "-0.3", "0.9118", "0.1471"].every((k) => F1.includes(k))); }
          check("分段抬起满 B6：不再有采样剖面（--seg-rim-* 渐变、半圆帽、11 px 暗带、透镜 box-shadow 实心影）", "gone", `${getComputedStyle(document.documentElement).getPropertyValue("--seg-rim-top") ? "rim-top" : "-"} ${seg.querySelector(".capL") ? "capL" : "-"} ${cs(lens0).boxShadow}`, !getComputedStyle(document.documentElement).getPropertyValue("--seg-rim-top") && !seg.querySelector(".capL") && cs(lens0).boxShadow === "none"); }
        /* §1 G4/G22: sliding onto the other segment moves the lens, the index does not change until the up */
        { const a0 = at(sel), a1 = at(unsel), lensD = seg.querySelector(".lens"); let wMax = 0, hMin = 99;
          for (let k = 1; k <= 10; k++) { pev(seg, "pointermove", { x: a0.x + (a1.x - a0.x) * k / 10, y: a1.y }); /* at() returns {x, y}; the old array form gave clientX 0 (the far left) and only the hard clamp made the check pass */ await sleep(16); const r = lensD.getBoundingClientRect(); wMax = Math.max(wMax, r.width); hMin = Math.min(hMin, r.height); }   // the native abc recording: 10 × 20 pt every ~17 ms
          for (let k = 0; k < 6; k++) { await sleep(16); const r = lensD.getBoundingClientRect(); wMax = Math.max(wMax, r.width); hMin = Math.min(hMin, r.height); }
          check("分段 G22 按住滑到另一段：透镜跟手（模型位置 ζ.85/.2 → 呈现跟踪 ζ.6533/.4559，seg-lens-refraction §4.4 原值）；跟手中拉长、变矮（占位：B 段逐帧表回放，等原理）", "w > 232 · h < 40", `w ${wMax.toFixed(1)} · h ${hMin.toFixed(1)}`, wMax > 232 && hMin < 40);
          await sleep(300); const lr = lensD.getBoundingClientRect(), ur = unsel.getBoundingClientRect();
          check("分段 G22 按住滑到另一段 +400 ms：透镜到手指下（呈现中心 = 位置弹簧过冲 + flex drift，原生 B 段过冲 10 pt；本页位置弹簧多过冲 ~4 pt（B2-a 已知差），容 ± 16）、index 不改", `${onText()} centre ${(ur.left + ur.width / 2).toFixed(0)}`, `${onText()} centre ${(lr.left + lr.width / 2).toFixed(1)} ${lr.width.toFixed(1)}×${lr.height.toFixed(1)}`, onText() === sel.textContent && Math.abs(lr.left + lr.width / 2 - (ur.left + ur.width / 2)) < 16 && renders === r1);
          await sleep(500); { const lr2 = lensD.getBoundingClientRect(); check("分段 G22 按住滑到另一段 +900 ms：透镜落定在手指下（中心 ± 3 pt）、220×44（flex 随位置弹簧余动仍在收敛，容 ± 3）", `centre ${(ur.left + ur.width / 2).toFixed(0)} · ${((seg.getBoundingClientRect().width / bs().length - 4) + 24).toFixed(0)}×44`, `centre ${(lr2.left + lr2.width / 2).toFixed(1)} · ${lr2.width.toFixed(1)}×${lr2.height.toFixed(1)}`, Math.abs(lr2.left + lr2.width / 2 - (ur.left + ur.width / 2)) < 3 && Math.abs(lr2.height - 44) < 1.5 && Math.abs(lr2.width - ((seg.getBoundingClientRect().width / bs().length - 4) + 24)) < 3); } }
        /* §1 G23: slide back and release on the original - no event */
        pev(seg, "pointermove", at(sel)); pev(seg, "pointerup", at(sel));
        check("分段 G23 滑回原段抬手：无事件，透镜回位", sel.textContent, `${onText()} renders+${renders - r1}`, onText() === sel.textContent && renders === r1 && q().style.getPropertyValue("--i") === String(bs().indexOf(sel)));
        await sleep(120); { const lp = parseFloat(seg.style.getPropertyValue("--lp")), hr = seg.querySelector(".lens").getBoundingClientRect().height; check("分段松手 +120 ms：几何从 +31 ms 起沿 ζ1/.25 弹簧回落（§4.4 落回几何；途中 28 < h < 44）；材质沿 ζ1/.4 退回（§4.4 落回材质；+89 ms 剩 ≈ .59）", "29 < h < 43 · .45 < lp < .75", `h ${hr.toFixed(1)} · lp ${lp}`, hr > 29 && hr < 43 && lp > 0.45 && lp < 0.75); }
        await sleep(200); { const lr = seg.querySelector(".lens").getBoundingClientRect(), sr = seg.getBoundingClientRect(); check("分段松手 +320 ms：模型尺寸回到 196×28（ζ1/.25：+289 ms 达 99.4 %），呈现上还叠着 flex 的松手回弹（原生 C 段 +308 196.9×28.1，本页更大），容 ± 10 %", `${((sr.width / bs().length - 4)).toFixed(1)}×28 ±10%`, `${lr.width.toFixed(1)}×${lr.height.toFixed(1)}`, Math.abs(lr.height - 28) < 2.8 && Math.abs(lr.width - (sr.width / bs().length - 4)) < 19.6); }
        await sleep(1180); { const lr = seg.querySelector(".lens").getBoundingClientRect(), sr = seg.getBoundingClientRect(); check("分段松手 +1.5 s：位置落定回原段（行程 ζ.85/.4 → 跟踪 ζ.56/.444，§4.4）、玻璃退净、复本收起、透镜内联几何清掉", "rest · no inline · at rest left", `${seg.classList.contains("lift") ? "lift" : "rest"} ${seg.style.getPropertyValue("--lp") || "-"} · ${seg.querySelector(".lens").style.width || "no inline"} · ${lr.left.toFixed(1)}`, !seg.classList.contains("lift") && !seg.querySelector(".lens").style.width && Math.abs(lr.left - (sr.left + 2 + bs().indexOf(sel) * (sr.width / bs().length))) < 0.6); }
        /* acceptance requirement 4: pointercancel after a lift → glass + warp fall on the same curve, never a cut */
        { const sg = q(), on = bs().find((b) => b.classList.contains("on")); pev(sg, "pointerdown", at(on)); await sleep(360); const lpUp = parseFloat(sg.style.getPropertyValue("--lp"));
          pev(sg, "pointercancel", at(on)); await sleep(60); const lp60 = parseFloat(sg.style.getPropertyValue("--lp"));
          check("分段 pointercancel：玻璃/折弯沿同曲线退回（+60 ms 仍在途中，不瞬切）", "lift 1 → 0 < lp60 < lpUp", `${lpUp} → ${lp60}`, lpUp > 0.95 && lp60 > 0.05 && lp60 < lpUp);
          await sleep(640); check("分段 pointercancel +700 ms：退净", "rest", sg.classList.contains("lift") ? "lift" : "rest", !sg.classList.contains("lift")); }
        /* §1 G4/G21: lift, slide to the other segment, release there - commits at the up */
        seg = q(); sel = bs().find((b) => b.classList.contains("on")); unsel = bs().find((b) => !b.classList.contains("on"));
        pev(seg, "pointerdown", at(sel)); await sleep(400); pev(seg, "pointermove", at(unsel)); await sleep(500); const r2 = renders, parent0 = seg.parentNode, lens21 = seg.querySelector(".lens"); pev(seg, "pointerup", at(unsel)); const q21 = document.querySelector("#queue").value; await sleep(60);
        check("分段 G21 抬起后滑到另一段抬手：选中那段（模型在抬手即改，内容 +25 ms 切 ← --seg-commit-delay-drag；vcsplit 重画在其后一帧，+60 ms 看）", unsel.textContent, `${onText()} model ${q21}`, q21 === unsel.dataset.q && onText() === unsel.textContent && thisShift(unsel.textContent) && renders === r2 + 1);
        check("分段 G21 换值重画：#queueseg 及其父节点原地保留（replaceKeeping，不摘下再插回 → 过渡不被取消；B2-b）", "same node · same parent", `${q() === seg ? "same node" : "new node"} · ${q().parentNode === parent0 ? "same parent" : "new parent"}`, q() === seg && q().parentNode === parent0);
        { const h1 = lens21.getBoundingClientRect().height; await sleep(16); const h2 = lens21.getBoundingClientRect().height;
          check("分段 G21 松手 +1 帧：透镜仍是抬起尺寸、随后逐帧回落（B2-b：不瞬回 28）", "h ≥ 39 at +0, > 36 at +16 ms", `${h1.toFixed(1)} → ${h2.toFixed(1)}`, h1 >= 39 && h2 > 36); }
        await sleep(200); { const lr = lens21.getBoundingClientRect(); check("分段 G21 松手 +216 ms：几何回落途中，叠着 flex 回弹（原生 C 段 +204 ms h 31.8；B5 后本页 24 < h < 40）", "24 < h < 40", lr.height.toFixed(1), lr.height > 24 && lr.height < 40); }
        await sleep(600); { const lr = lens21.getBoundingClientRect(), sr = seg.getBoundingClientRect(); check("分段 G21 松手 +816 ms：落定 196×28 于目标段（flex 回弹收敛；位置 ζ.85/.4 → ζ.56/.444）", `196×28 at ${(sr.left + 2 + bs().indexOf(unsel) * (sr.width / bs().length)).toFixed(1)}`, `${lr.width.toFixed(1)}×${lr.height.toFixed(1)} at ${lr.left.toFixed(1)}`, Math.abs(lr.height - 28) < 0.6 && Math.abs(lr.width - (sr.width / bs().length - 4)) < 0.8 && Math.abs(lr.left - (sr.left + 2 + bs().indexOf(unsel) * (sr.width / bs().length))) < 1.5); }
        await sleep(50);
        /* §1 G5: press the unselected one, slide onto the selected one, release - no event */
        seg = q(); sel = bs().find((b) => b.classList.contains("on")); unsel = bs().find((b) => !b.classList.contains("on"));
        const r3 = renders; pev(seg, "pointerdown", at(unsel)); pev(seg, "pointermove", at(sel)); pev(seg, "pointerup", at(sel));
        check("分段 G5 按未选中段滑到已选中段抬手：无事件", sel.textContent, `${onText()} renders+${renders - r3}`, onText() === sel.textContent && renders === r3 && !unsel.classList.contains("dim"));
        /* §1 G17/G18/G26: release 60 pt below the control still selects, 100 pt below cancels (--ios-touch-inside-slop 70) */
        seg = q(); sel = bs().find((b) => b.classList.contains("on")); unsel = bs().find((b) => !b.classList.contains("on"));
        const r4 = renders; pev(seg, "pointerdown", at(unsel)); pev(seg, "pointermove", at(unsel, .5, .5, 0, 100)); pev(seg, "pointerup", at(unsel, .5, .5, 0, 100));
        check("分段 G18 竖向滑出 100 pt 抬手：取消、无事件、标签回 1", sel.textContent, `${onText()} renders+${renders - r4}`, onText() === sel.textContent && renders === r4 && !unsel.classList.contains("dim"));
        seg = q(); const r5 = renders; pev(seg, "pointerdown", at(unsel)); pev(seg, "pointermove", at(unsel, .5, .5, 0, 60)); pev(seg, "pointerup", at(unsel, .5, .5, 0, 60)); await sleep(100);
        check("分段 G17 竖向滑出 60 pt 抬手：仍选中（余量 70；内容 +66 ms 切，vcsplit 重画在其后一帧，+100 ms 看）", unsel.textContent, `${onText()} renders+${renders - r5}`, onText() === unsel.textContent && renders === r5 + 1);
        await sleep(50);
        /* pointercancel = cancel */
        seg = q(); sel = bs().find((b) => b.classList.contains("on")); unsel = bs().find((b) => !b.classList.contains("on"));
        const r6 = renders; pev(seg, "pointerdown", at(unsel)); pev(seg, "pointercancel", at(unsel));
        check("分段 pointercancel：不提交、标签回 1", sel.textContent, `${onText()} renders+${renders - r6}`, onText() === sel.textContent && renders === r6 && !unsel.classList.contains("dim"));
        /* §1 G12/G13: ten alternating taps 30 ms down / 30 ms gap - every up counts, no debounce (--ios-touch-debounce 0) */
        const r7 = renders; let last = null, lastQ = null, everyTick = true;
        for (let k = 0; k < 10; k++) { const b = bs()[k % 2]; last = b.textContent; lastQ = b.dataset.q; const sg = q(); pev(sg, "pointerdown", at(b)); await sleep(30); pev(sg, "pointerup", at(b)); if (document.querySelector("#queue").value !== lastQ) everyTick = false; await sleep(30); }
        await sleep(100);
        check("分段 G12 快速交替 10 次（30 ms 点 / 30 ms 间隔）：每下模型都改（抬手即改）、终态 = 最后一次；内容重画在 valueChanged 时刻，被更新的值追上的那次不再画（快速连点 未量）", last, `${onText()} renders+${renders - r7}${everyTick ? "" : "（某下抬手时模型未改）"}`, onText() === last && renders >= r7 + 1 && renders <= r7 + 10 && everyTick && thisShift(last));
        let stable = true; for (let k = 0; k < 6; k++) { await sleep(100); if (onText() !== last) stable = false; }
        check("分段 G12 快速交替后 600 ms 内不回跳", last, onText(), stable && onText() === last);
        /* BOARD #9①: a quick tap on the SELECTED segment (up at 60 ms, before the 109 ms lift) — the lens never lifted, so no frame may carry .lift, the resting
           platter (.lens background) must stay opaque, the GL package must draw nothing (stats.frames unchanged) and __segLens.p must read 0 */
        await sleep(1300);   // the previous gesture's loop (G14's taps) has ended: the control is at rest with its opaque platter
        { const sg = q(), selB = bs().find((b) => b.classList.contains("on")), lensQ = sg.querySelector(".lens"), gl = sg.__gl, f0 = gl ? gl.lens.stats.frames : null, r9 = renders;
          const bg0 = cs(lensQ).backgroundColor, alphaOf = (c) => { const m = rgb(c); return m ? m[3] : 1; };
          pev(sg, "pointerdown", at(selB)); await sleep(60); pev(sg, "pointerup", at(selB));
          let liftFrames = 0, transFrames = 0, pMax = 0, n = 0; const tEnd = performance.now() + 500;
          while (performance.now() < tEnd) { await new Promise(requestAnimationFrame); n++; if (sg.classList.contains("lift")) liftFrames++; if (cs(lensQ).backgroundColor !== bg0) transFrames++; const L = window.__segLens; if (L && typeof L.p === "number" && L.p > pMax) pMax = L.p; }
          const f1 = gl ? gl.lens.stats.frames : null;
          check("分段 #9① 快速点已选中段（60 ms 抬手，抬起 109 ms 未到）：没抬过就不走落回——500 ms 内无一帧带 .lift、.lens 背景每帧 = 静止值（亮 白 / 暗 令牌 rgba(235,235,245,.3)，不变透明）、GL 包一帧不画（stats.frames 不变）、__segLens.p 为 0、不换值", `0 lift frames · 0 changed · frames = · p 0 · renders =`, `${n} frames sampled · lift ${liftFrames} · bg changed ${transFrames} (rest ${bg0}) · gl frames ${f0} → ${f1} · pMax ${pMax} · renders+${renders - r9}`, n > 10 && alphaOf(bg0) > 0 && liftFrames === 0 && transFrames === 0 && (f0 === null || f1 === f0) && pMax === 0 && renders === r9); }
        /* a page re-render (heartbeat / snapshot) while the lens rests on a segment must not move it (the carry-over reads the lens box, not the % translate) */
        { await sleep(1300); const sg = q(), ln = sg.querySelector(".lens"), lb = ln.getBoundingClientRect().left; window.render(); const ln2 = q().querySelector(".lens"); const lb2 = ln2.getBoundingClientRect().left; await sleep(120); const lb3 = q().querySelector(".lens").getBoundingClientRect().left;
          check("重画时透镜不动（心跳/快照 render 不会让它跳）", `${Math.round(lb)}`, `${Math.round(lb2)} → ${Math.round(lb3)} ${q().querySelector(".lens").classList.contains("spring") ? "spring!" : ""}`, Math.abs(lb2 - lb) < 1 && Math.abs(lb3 - lb) < 1 && !q().querySelector(".lens").classList.contains("spring")); }
        /* §1 G14: the same segment tapped three times - one event */
        const sameName = (bs().find((x) => !x.classList.contains("on")) || bs()[0]).textContent;
        const r8 = renders; for (let k = 0; k < 3; k++) { const b = bs().find((x) => x.textContent === sameName); const sg = q(); pev(sg, "pointerdown", at(b)); pev(sg, "pointerup", at(b)); await sleep(40); }
        check("分段 G14 同段连点 3 下：只 1 次事件", 1, renders - r8, renders - r8 === 1);
        const back = bs().find((b) => b.textContent === start); if (back && onText() !== start) { const sg = q(); pev(sg, "pointerdown", at(back)); pev(sg, "pointerup", at(back)); }
        /* 验收 09-19 17:5x: a one-queue page (one segment, 400 wide) re-rendered twice showed a lifted capsule (the preloaded set's width, left) on the resting
           control — the package's warm-up frame put back by the next warm-up (view.js segGlRedraw). Here: one segment, two re-renders 400 ms apart, then
           the package must have drawn exactly ONE frame per re-render (its warm-up; the put-back would be a second) and the control must be at rest. */
        if (q().classList.contains("gl") && typeof snap === "object" && snap && Array.isArray(snap.queues) && snap.queues.length > 1) {
          await sleep(900); const savedQ = snap.queues, savedCur = curQueue; snap.queues = savedQ.slice(0, 1); curQueue = snap.queues[0]["名"]; window.render(); await sleep(1500);
          const s1 = q(), g1 = s1 && s1.__gl, f0 = g1 ? g1.lens.stats.frames : -1;
          window.render(); await sleep(400); const f1 = q().__gl ? q().__gl.lens.stats.frames : -1;
          window.render(); await sleep(400); const f2 = q().__gl ? q().__gl.lens.stats.frames : -1; const s2 = q();
          check("一段控件重渲染两次：包每次只画预热那一帧（frames +1/+1，不把上一帧「放回」——放回即幽灵胶囊；view.js segGlRedraw），控件静止（无 .lift，一个 canvas）", "+1 / +1 · rest", `${s2.querySelectorAll("button").length} seg · frames ${f0} → ${f1} → ${f2} · ${s2.classList.contains("lift") ? "lift!" : "rest"} · ${s2.querySelectorAll("canvas.glens").length} canvas`, s2.querySelectorAll("button").length === 1 && f1 - f0 === 1 && f2 - f1 === 1 && !s2.classList.contains("lift") && s2.querySelectorAll("canvas.glens").length === 1);
          snap.queues = savedQ; curQueue = savedCur; window.render(); await sleep(600);
        }
      }
      /* 验收 09-19 18:0x: with the page unscrolled, the ask() dialog opened from the 停止一切 tile must show its title (the dialog is overflow:clip — not a scroll
         container — and ask() resets scrollTop; before: .pane's −60 inset gave 60 px of scrollable overflow and the title scrolled out of the box) */
      { const tile = document.querySelector("#estop"), dlg = document.querySelector("#alert");
        if (tile && dlg && !dlg.open) { scrollTo(0, 0); await sleep(100); tile.click(); await sleep(700);
          const dr = dlg.getBoundingClientRect(), tr = dlg.querySelector("#alert-t").getBoundingClientRect(); dlg.scrollTop = 60; const st = dlg.scrollTop;
          check("顶部未滚动时点磁贴弹窗：标题在弹窗盒内（盒顶 ≤ 标题顶，标题有高度）、弹窗不可滚（overflow clip，scrollTop 设 60 读回 0）", "title inside · scrollTop 0", `open ${dlg.open} · box ${Math.round(dr.top)}…${Math.round(dr.bottom)} title ${Math.round(tr.top)}…${Math.round(tr.bottom)} "${dlg.querySelector("#alert-t").textContent}" · scrollTop ${st} · overflow ${getComputedStyle(dlg).overflow}`, dlg.open && tr.height > 10 && tr.top >= dr.top - 0.5 && tr.bottom <= dr.bottom + 0.5 && st === 0);
          const cancel = dlg.querySelector("#alert-cancel"); if (cancel) cancel.click(); await sleep(600); } }
      /* 数据终核 181053 ⑤1/3: with the keyboard up (visual viewport > 120 px shorter) the tab capsule is hidden (html.kbd), and comes back when it closes */
      { const nav0 = document.querySelector("nav.tabs"), on = window.__tabKbd && window.__tabKbd(innerHeight - 300), hid = nav0 ? getComputedStyle(nav0).display : "-";
        const off = window.__tabKbd && window.__tabKbd(null), shown = nav0 ? getComputedStyle(nav0).display : "-", nb = nav0 ? nav0.getBoundingClientRect() : null;
        check("键盘弹出（视口矮 300）时底部标签胶囊藏起（html.kbd → display none），收起后回到屏底（原生 tab bar 被键盘盖住，不浮到键盘上）", "kbd hidden → shown at bottom", `kbd ${on} ${hid} → ${off} ${shown} bottom gap ${nb ? Math.round(innerHeight - nb.bottom) : "-"}`, on === true && hid === "none" && off === false && shown !== "none" && !!nb && innerHeight - nb.bottom >= 0 && innerHeight - nb.bottom < 120);
        const fi = document.querySelector("input[data-time]") || document.querySelector('#app input[type="text"]');
        if (fi && nav0) { const sy0 = scrollY; fi.focus({ preventScroll: true }); const hasF = document.hasFocus(); await sleep(360); const dF = !document.documentElement.classList.contains("kbd") && getComputedStyle(nav0).display !== "none";
          /* the reveal (数据 190821: the first focus of the time field stayed under the keyboard): with a pretended 300 px visible height the active field must be scrolled into it */
          scrollTo(0, 0); const r0 = fi.getBoundingClientRect().top, did = window.__kbdReveal && window.__kbdReveal(300); await sleep(700); const r1 = fi.getBoundingClientRect(); const inside = r1.top >= 0 && r1.bottom <= 300;
          fi.blur(); await sleep(120); const dB = !document.documentElement.classList.contains("kbd") && getComputedStyle(nav0).display !== "none"; scrollTo(0, sy0);
          check("聚焦本身不动胶囊（只认视口变矮，监督局 19:3x）：文本框聚焦 360 ms 后胶囊仍在，失焦后仍在", "focus shown · blur shown", `hasFocus ${hasF} · focus ${dF ? "shown" : "hidden!"} · blur ${dB ? "shown" : "hidden!"}`, dF && dB);
          check("键盘露出 300 px 时聚焦的字段滚进可见区中央（visualViewport resize 后下一帧 scrollBy 到可见区中心；190821 首次聚焦字段留在键盘下）", "field inside 0…300", `top ${Math.round(r0)} → ${Math.round(r1.top)}…${Math.round(r1.bottom)} · scrolled ${did}`, hasF ? (did === true && inside) : true); } }
      /* 监督局 19:4x: keyboard state = viewport evidence only. Android shrinks innerHeight itself (vv.height = innerHeight): H0 − innerHeight > 120 hides; the
         viewport recovering shows — with a text field focused the whole time (the keyboard may go without a blur: iOS tap on the segments, Android back key) */
      { const fi2 = document.querySelector("input[data-time]"), nv2 = document.querySelector("nav.tabs");
        if (fi2 && nv2) { fi2.focus({ preventScroll: true }); const a1 = window.__tabKbd(innerHeight - 300, innerHeight - 300), d1 = getComputedStyle(nv2).display;
          const a2 = window.__tabKbd(null), d2 = getComputedStyle(nv2).display; const a3 = window.__tabKbd(innerHeight - 300), d3 = getComputedStyle(nv2).display; const a4 = window.__tabKbd(null), d4 = getComputedStyle(nv2).display; fi2.blur();
          check("键盘只信视口：安卓式 innerHeight 缩 300（H0 基线）→ 藏，回高 → 放回；iOS 式 vv 缩 300 → 藏，回高 → 放回；全程字段保持聚焦（不经失焦收键盘也放回）", "hidden shown hidden shown", `${a1} ${d1} · ${a2} ${d2} · ${a3} ${d3} · ${a4} ${d4}`, a1 === true && d1 === "none" && a2 === false && d2 !== "none" && a3 === true && d3 === "none" && a4 === false && d4 !== "none"); } }
      /* 监督局 19:3x: a segment tap must not flash — the buttons carry no tap highlight and no pointer focus ring (unchanged since 181053), and a render must not
         rebuild the tab bar's nodes (the platter's backdrop-filter layer / glide / buttons stay the same elements) */
      { const sb = document.querySelector("#queueseg button"), nv = document.querySelector("nav.tabs"), plat0 = nv && nv.querySelector(".plat"), gl0 = nv && nv.querySelector(".glide"), b0 = nv && nv.querySelector(".seg > button");
        const th = sb ? getComputedStyle(sb).webkitTapHighlightColor : "-", fv = sb ? sb.matches(":focus-visible") : null;
        window.render(); await sleep(50); window.render(); await sleep(50);
        const same = nv && plat0 === nv.querySelector(".plat") && gl0 === nv.querySelector(".glide") && b0 === nv.querySelector(".seg > button");
        check("分段按钮无点按高亮（-webkit-tap-highlight-color transparent，index.html:82）、无指针焦点环（:focus-visible 不匹配）；重画两次后标签栏节点不重建（.plat / .glide / 按钮同一元素）", "transparent · no ring · same nodes", `${th} · focus-visible ${fv} · nodes ${same ? "same" : "REBUILT"}`, /rgba\(0, 0, 0, 0\)|transparent/.test(th) && fv === false && same === true); }
      /* 数据终核 181053 ⑤2: the 刷到几点 input takes HH:MM only — 08:930 rolls back to the last valid value, nothing enters the pending edits */
      { const ti = document.querySelector("input[data-time]");
        if (ti) { const before = ti.value, n0 = Object.keys(edits).length; ti.value = "08:930"; ti.dispatchEvent(new Event("change", { bubbles: true })); const back = ti.value;
          ti.value = "9:05"; ti.dispatchEvent(new Event("change", { bubbles: true })); const norm = ti.value; ti.value = before; ti.dispatchEvent(new Event("change", { bubbles: true }));
          check("时间输入只收 HH:MM：08:930 回滚成原值、9:05 规整成 09:05、待保存数不变", `${before} · 09:05 · edits ${n0}`, `${back} · ${norm} · edits ${Object.keys(edits).length}`, back === before && norm === "09:05" && Object.keys(edits).length === n0); }
        else check("时间输入只收 HH:MM（页面上此刻没有 data-time 输入框：刷声骸块未渲染，不核）", "-", "no input", true); }
      /* 验收 09-19 18:0x: view.js arriving 3 s late (slow network) must not throw in live.js's timers / events (window.__viewReady gate): the page in an iframe with
         ?viewdelay=5500 (live.js's 5 s updateLive tick fires first), its error / unhandledrejection events counted for 7 s */
      { const fr = document.createElement("iframe"); fr.style.cssText = "position:fixed;left:-2000px;top:0;width:440px;height:956px;opacity:0;pointer-events:none"; fr.src = "index.html?demo=1&viewdelay=5500";
        const errs = []; document.body.appendChild(fr);
        await new Promise((r) => { fr.onload = r; setTimeout(r, 3000); });
        try { fr.contentWindow.addEventListener("error", (e) => errs.push(String(e.message || e.error || e))); fr.contentWindow.addEventListener("unhandledrejection", (e) => errs.push("rejection " + String(e.reason))); } catch (e) { errs.push("no access " + e); }
        await sleep(7000);
        let ready = null; try { ready = fr.contentWindow.__viewReady === true; } catch (e) {}
        check("view.js 延迟 5.5 s 装载（live.js 的 5 s updateLive 定时器先到）：不报错（__viewReady 闸），装载后页面起来", "0 errors · ready", `${errs.length} errors ${errs.slice(0, 2).join(" | ")} · ready ${ready}`, errs.length === 0 && ready === true);
        fr.remove(); }
      /* §2 UITabBar */
      const nav = document.querySelector("nav.tabs:not([hidden])"), tseg = nav && nav.querySelector(".seg"), tbs = nav ? [...nav.querySelectorAll(".seg button")] : [];
      if (nav && tbs.length > 1) {
        const tOn = () => (nav.querySelector(".seg button.on") || {}).dataset.tab, g = nav.querySelector(".glide"), startTab = tOn();
        const other = tbs.find((b) => !b.classList.contains("on")), cur = tbs.find((b) => b.classList.contains("on"));
        const shown = () => [...document.querySelectorAll("#app > section:not([hidden])")].map((x) => x.dataset.tab).filter((v, i, a) => a.indexOf(v) === i).join(",");
        pev(tseg, "pointerdown", at(other));
        check("标签栏 T1 按下未选中项 +0 ms：不选中、透镜未动", startTab, `${tOn()} lift=${g.classList.contains("lift")}`, tOn() === startTab && !g.classList.contains("lift"));
        await sleep(60);
        check("标签栏 T1 +60 ms：透镜还没动（--ios-touch-tab-glide-delay 140）", "no lift", g.classList.contains("lift") ? "lift" : "no lift", !g.classList.contains("lift"));
        await sleep(140);
        check("标签栏 T1 +200 ms：透镜抬起中并滑向被按项（+140 ms 起，~350 ms 到）", `left→${other.offsetLeft}, lift`, `left ${g.style.left} ${g.classList.contains("lift") ? "lift" : "-"} ${cs(g).scale}`, g.classList.contains("lift") && g.style.left === other.offsetLeft + "px" && parseFloat(cs(g).scale) > 1.0);
        await sleep(400);
        check("标签栏 T5 按住 600 ms：仍不选中，透镜停在目标 119×64（--ios-touch-tab-lift-w 25 / -h 10）", `${startTab} 1.266 1.185`, `${tOn()} ${cs(g).scale}`, tOn() === startTab && /^1\.26/.test(cs(g).scale));
        const t1 = performance.now(); pev(tseg, "pointerup", at(other)); const d1 = performance.now() - t1;
        check("标签栏 T1 抬手：+0 ms 选中、内容同步切", other.dataset.tab, `${tOn()} 显示 ${shown()} +${Math.round(d1 * 10) / 10} ms`, tOn() === other.dataset.tab && shown() === other.dataset.tab && d1 < 50);
        /* Behaviour 3: scroll offsets are kept per tab (Health: 0 px difference after switching away and back, tabscroll/README §1) */
        { const nv = document.querySelector("nav.tabs"), sg = nv.querySelector(".seg"), bb = [...sg.querySelectorAll("button")], startB = bb.find((b) => b.dataset.tab === startTab), otherB = bb.find((b) => b.dataset.tab === other.dataset.tab);
          window.scrollTo(0, 150); const y1 = window.scrollY;
          pev(sg, "pointerdown", at(startB)); pev(sg, "pointerup", at(startB)); await sleep(30); const yStart = window.scrollY;
          pev(sg, "pointerdown", at(otherB)); pev(sg, "pointerup", at(otherB)); await sleep(30);
          check("切标签保留各自滚动位置（切走 → 切回差 0，Health 实测）", `${y1} → ${y1}`, `${y1} → ${yStart} → ${window.scrollY}`, y1 > 0 && yStart === 0 && Math.abs(window.scrollY - y1) < 1);
          /* tap on the selected tab: to the top on the ω 12 spring (tabscroll/README §2: 0.2 s 71 %, 0.33 s 92 %, 0.5 s 98 %) */
          const y2 = window.scrollY; pev(sg, "pointerdown", at(otherB)); pev(sg, "pointerup", at(otherB)); await sleep(200); const y200 = window.scrollY; await sleep(300); const y500 = window.scrollY; await sleep(300);
          check("点已选中标签回顶：ω 12 弹簧（0.2 s ≈ 69–71 %，0.5 s ≈ 98 %，0.8 s 到 0）", "≈31 % · ≈2 % · 0", `${Math.round(y200 / y2 * 100)} % · ${Math.round(y500 / y2 * 100)} % · ${window.scrollY}`, y2 > 0 && Math.abs(y200 / y2 - 0.31) < 0.08 && y500 / y2 < 0.05 && window.scrollY === 0);
          window.scrollTo(0, 0); }
        { const sg = document.querySelector("#queueseg"); check("班次分段只在「状态」页（别的标签页隐藏）", "hidden", sg ? (sg.hidden ? "hidden" : "shown") : "缺", !!sg && sg.hidden && getComputedStyle(sg).display === "none"); }
        /* T7/T8: release 250 pt above still selects */
        const nav2 = document.querySelector("nav.tabs"), seg2 = nav2.querySelector(".seg"), b2 = [...seg2.querySelectorAll("button")];
        const back = b2.find((b) => b.dataset.tab === startTab);
        pev(seg2, "pointerdown", at(back)); pev(seg2, "pointermove", at(back, .5, .5, 0, -250)); pev(seg2, "pointerup", at(back, .5, .5, 0, -250));
        check("标签栏 T7 竖向滑出 250 pt 抬手：仍选中被按项（无距离取消）", startTab, (nav2.querySelector(".seg button.on") || {}).dataset.tab, (nav2.querySelector(".seg button.on") || {}).dataset.tab === startTab);
        /* T3/T9: pressing the selected tab, releasing on it - no event */
        const nav3 = document.querySelector("nav.tabs"), seg3 = nav3.querySelector(".seg"), on3 = seg3.querySelector("button.on");
        const before = (nav3.querySelector(".seg button.on") || {}).dataset.tab, g3 = nav3.querySelector(".glide"); pev(seg3, "pointerdown", at(on3)); await sleep(100);
        check("标签栏 T3 按下已选中项 +100 ms：透镜还没抬（--ios-touch-tab-selected-lift-delay 125）", "no lift", g3.classList.contains("lift-sel") ? "lift" : "no lift", !g3.classList.contains("lift-sel"));
        await sleep(120);
        check("标签栏 T3 +220 ms：透镜抬到 103×63（--ios-touch-tab-selected-lift-done 180）", "1.096 1.167", cs(g3).scale, /^1\.09/.test(cs(g3).scale));
        pev(seg3, "pointerup", at(on3));
        check("标签栏 T3 按下已选中项抬手：无事件", before, (nav3.querySelector(".seg button.on") || {}).dataset.tab, (nav3.querySelector(".seg button.on") || {}).dataset.tab === before && !g3.classList.contains("lift-sel"));
      }
      /* §3 UISwitch on a synthetic switch through the page's own pointer handling */
      const swLab = document.createElement("div"); swLab.style.cssText = "position:fixed;left:20px;top:200px;z-index:99;opacity:0";
      swLab.innerHTML = `<label class="sw"><input type="checkbox"><span></span></label>`; document.body.appendChild(swLab);
      const sw = swLab.querySelector(".sw"), inp = sw.querySelector("input"); let flips = 0; inp.addEventListener("change", () => flips++);
      const kn = () => sw.querySelector("span");
      pev(sw, "pointerdown", at(sw));
      check("开关 L200 按下 +0 ms：不翻、旋钮未抬", "off, no lift", `${inp.checked ? "on" : "off"}, ${sw.classList.contains("hold") ? "lift" : "no lift"}`, !inp.checked && !sw.classList.contains("hold"));
      await sleep(120);
      check("开关 L200 +120 ms：旋钮还没抬（--ios-touch-switch-lift-delay 195）", "no lift", sw.classList.contains("hold") ? "lift" : "no lift", !sw.classList.contains("hold"));
      await sleep(120);
      check("开关 L260 +240 ms：旋钮抬起（.hold）", "lift", sw.classList.contains("hold") ? "lift" : "no lift", sw.classList.contains("hold"));
      await sleep(220);
      check("开关 L400 +460 ms：旋钮落定 58×38（scale 1.568 1.583）", "1.568 1.583", cs(kn(), "::after").scale, /^1\.5[67]/.test(cs(kn(), "::after").scale));
      const t2 = performance.now(); pev(sw, "pointerup", at(sw)); const d2 = performance.now() - t2;
      check("开关 S1 抬手：立刻翻转一次（--ios-touch-switch-flip-delay 0）", "on ×1", `${inp.checked ? "on" : "off"} ×${flips} +${Math.round(d2 * 10) / 10} ms`, inp.checked && flips === 1 && d2 < 50);
      /* X: drag −10 (against the direction) and release - still flips */
      pev(sw, "pointerdown", at(sw)); pev(sw, "pointermove", at(sw, .5, .5, 10, 0)); pev(sw, "pointerup", at(sw, .5, .5, 10, 0));
      check("开关 X 反方向拖 10 抬手：仍翻转", "off ×2", `${inp.checked ? "on" : "off"} ×${flips}`, !inp.checked && flips === 2);
      /* N2–N4: drag beyond the far end (+40 > travel 22) and back to +5 - no flip */
      pev(sw, "pointerdown", at(sw)); pev(sw, "pointermove", at(sw, .5, .5, 40, 0)); pev(sw, "pointermove", at(sw, .5, .5, 5, 0)); pev(sw, "pointerup", at(sw, .5, .5, 5, 0));
      check("开关 N2 拖过远端外 (+40) 再拖回 (+5) 抬手：不翻转", "off ×2", `${inp.checked ? "on" : "off"} ×${flips}`, !inp.checked && flips === 2);
      /* X11: dragged beyond the far end and released there - flips */
      pev(sw, "pointerdown", at(sw)); pev(sw, "pointermove", at(sw, .5, .5, 40, 0)); pev(sw, "pointerup", at(sw, .5, .5, 40, 0));
      check("开关 X11 拖过远端外直接抬手：翻转", "on ×3", `${inp.checked ? "on" : "off"} ×${flips}`, inp.checked && flips === 3);
      /* pointercancel: no flip */
      pev(sw, "pointerdown", at(sw)); pev(sw, "pointercancel", at(sw));
      check("开关 pointercancel：不翻转", "on ×3", `${inp.checked ? "on" : "off"} ×${flips}`, inp.checked && flips === 3 && !sw.classList.contains("hold"));
      swLab.remove();
      /* §4 UIButton on a synthetic tile; alert action on a synthetic open dialog */
      const bLab = document.createElement("div"); bLab.style.cssText = "position:fixed;left:20px;top:300px;z-index:99;opacity:0";
      bLab.innerHTML = `<div class="group tiles"><button type="button" class="tile"><span class="ttitle">x</span></button></div>`; document.body.appendChild(bLab);
      const tile = bLab.querySelector(".tile"); let clicks = 0; tile.addEventListener("click", () => clicks++);
      const t3 = performance.now(); pev(tile, "pointerdown", at(tile)); const d3 = performance.now() - t3;
      check("按钮 U1 按下：立刻 highlighted（.pressed，--ios-touch-button-highlight-delay 0）", "pressed", tile.classList.contains("pressed") ? `pressed +${Math.round(d3 * 10) / 10} ms` : "not pressed", tile.classList.contains("pressed"));
      pev(tile, "pointermove", at(tile, .5, 1, 0, 50));
      check("按钮 U3 拖出边界 50 pt：仍高亮（余量 70）", "pressed", tile.classList.contains("pressed") ? "pressed" : "not pressed", tile.classList.contains("pressed"));
      pev(tile, "pointermove", at(tile, .5, 1, 0, 80));
      check("按钮 U3 拖出边界 80 pt：高亮灭（touchDragExit）", "not pressed", tile.classList.contains("pressed") ? "pressed" : "not pressed", !tile.classList.contains("pressed"));
      pev(tile, "pointermove", at(tile, .5, 1, 0, 30));
      check("按钮 U4 拖回：高亮亮（touchDragEnter）", "pressed", tile.classList.contains("pressed") ? "pressed" : "not pressed", tile.classList.contains("pressed"));
      pev(tile, "pointerup", at(tile, .5, 1, 0, 50)); await sleep(10);
      check("按钮 U3 在边界外 50 pt 抬手：触发一次（touchUpInside）", 1, clicks, clicks === 1);
      pev(tile, "pointerdown", at(tile)); pev(tile, "pointermove", at(tile, .5, 1, 0, 100)); pev(tile, "pointerup", at(tile, .5, 1, 0, 100)); await sleep(10);
      check("按钮 U6 在边界外 100 pt 抬手：不触发（touchUpOutside）", 1, clicks, clicks === 1 && !tile.classList.contains("pressed"));
      const dlg = document.createElement("dialog"); dlg.style.cssText = "position:fixed;left:20px;top:400px;z-index:99;opacity:0"; dlg.innerHTML = `<div class="acts"><button type="button" id="_a">a</button><button type="button" id="_b">b</button></div>`;
      document.body.appendChild(dlg); dlg.show(); const ba = dlg.querySelector("#_a"), bb = dlg.querySelector("#_b"); let ca = 0, cb = 0; ba.addEventListener("click", () => ca++); bb.addEventListener("click", () => cb++);
      pev(ba, "pointerdown", at(ba)); pev(ba, "pointermove", at(bb));
      check("弹窗按钮 A3 滑到相邻按钮：高亮转移", "b pressed", `${ba.classList.contains("pressed") ? "a" : ""}${bb.classList.contains("pressed") ? "b" : ""} pressed`, !ba.classList.contains("pressed") && bb.classList.contains("pressed"));
      pev(ba, "pointermove", at(bb, .5, 1, 0, 6));
      check("弹窗按钮 A4 出边 6 pt：高亮灭（无余量，--ios-touch-alert-slop 0）", "none pressed", `${ba.classList.contains("pressed") ? "a" : ""}${bb.classList.contains("pressed") ? "b" : ""} pressed`, !ba.classList.contains("pressed") && !bb.classList.contains("pressed"));
      pev(ba, "pointerup", at(bb, .5, 1, 0, 6)); await sleep(10);
      check("弹窗按钮 A2 出边抬手：不触发", "0 / 0", `${ca} / ${cb}`, ca === 0 && cb === 0);
      pev(ba, "pointerdown", at(ba)); pev(ba, "pointermove", at(bb)); pev(ba, "pointerup", at(bb)); await sleep(10);
      check("弹窗按钮 A3/A6 从 a 滑到 b 抬手：触发 b", "0 / 1", `${ca} / ${cb}`, ca === 0 && cb === 1);
      /* ghost click (data session 862de97): the action closes the dialog on the up, then the browser's own click lands on
         whatever is under the finger - a tile below opened a second dialog. The tile sits under button a; a's handler closes
         the dialog; the browser's click is replayed as a plain click on the element now at that point. */
      { const p = at(ba); ba.addEventListener("click", () => dlg.close(), { once: true }); const c0 = clicks;
        pev(ba, "pointerdown", p); pev(ba, "pointerup", p);                                    // the action closes the dialog on the up
        tile.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, clientX: p.x, clientY: p.y }));   // = the browser's click, now landing on the tile under the finger
        await sleep(10);
        check("弹窗按钮抬手关掉弹窗后，浏览器补的 click 不穿到底下的磁贴", `tile ${c0}, closed`, `tile ${clicks}, ${dlg.open ? "open" : "closed"}`, clicks === c0 && !dlg.open); }
      dlg.close(); dlg.remove(); bLab.remove(); window.render = origRender;
      /* §5 B14 UITableViewCell press (remote-ref/cell-native.md §0 probe originals, state-tables/cell.md C*) on a synthetic .row.nav and an
         action row inside a .group, through controls.js. Colours: --ios-cell-highlight light (209,209,214) / dark (58,58,60); the fade
         .5 s cubic-bezier(.42,0,.58,1) checked against the curve at the sampled instant (the same easeInOut UIView used). */
      const rLab = document.createElement("div"); rLab.style.cssText = "position:fixed;left:20px;top:500px;width:400px;z-index:99;opacity:0";
      rLab.innerHTML = `<div class="group"><div class="row nav"><label>上一行</label><span class="val">值</span><i class="sf chev"></i></div><div class="row nav"><label>行</label><span class="val">值</span><i class="sf chev"></i></div><div class="acts"><button type="button">蓝字行</button></div></div>`;
      document.body.appendChild(rLab);
      const [row0, row] = rLab.querySelectorAll(".row.nav"), act = rLab.querySelector(".acts button"); let rsel = 0, asel = 0;
      const seq = []; new MutationObserver(() => seq.push([performance.now(), row.className])).observe(row, { attributes: true, attributeFilter: ["class"] });
      row.addEventListener("click", () => { rsel++; seq.push([performance.now(), "click"]); }); act.addEventListener("click", () => asel++);
      const HL = dark ? [58, 58, 60] : [209, 209, 214], bgOf = (el) => cs(el).backgroundColor, lit = (el) => same(bgOf(el), HL);
      const bez = (x) => { let lo = 0, hi = 1; for (let i = 0; i < 40; i++) { const t = (lo + hi) / 2, cx = 3 * .42 * t * (1 - t) * (1 - t) + 3 * .58 * t * t * (1 - t) + t * t * t; if (cx < x) lo = t; else hi = t; } const t = (lo + hi) / 2; return 3 * 0 * t * (1 - t) * (1 - t) + 3 * 1 * t * t * (1 - t) + t * t * t; };   // cubic-bezier(.42,0,.58,1)
      /* C3: hold 400 ms — nothing until +150, then the instant highlight; the fade from the up */
      pev(row, "pointerdown", at(row)); await sleep(100);
      check("列表行 C3 按下 +100 ms：无变化（延迟 150，--ios-touch-highlight-delay）", "rest", lit(row) ? "highlight" : "rest", !lit(row));
      await sleep(80);
      col("列表行 C3 按下 +180 ms：底色 = 高亮色（--ios-cell-highlight，cell-native.md §0）", HL, bgOf(row));
      check("列表行 C3 高亮中分隔线 opacity 0", "0", cs(row, "::after").opacity, cs(row, "::after").opacity === "0");
      check("列表行 C3 高亮中上一行的分隔线也 opacity 0（数据真机核 ④）", "0", cs(row0, "::after").opacity, cs(row0, "::after").opacity === "0");
      await sleep(220);
      const tUp = performance.now(); pev(row, "pointerup", at(row));
      await sleep(45);                                                                   // the device's own click comes 40–60 ms after the up
      row.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));   // = the browser's own click for this touch: swallowed
      check("列表行 抬手 +45 ms 浏览器自己的 click 被吞（data-rc；选中由页面在淡出首帧后发，此时已 1 次）", "1", rsel, rsel === 1);
      await sleep(15);
      check("列表行 C3 抬手 +60 ms：选中 1 次（淡出首帧之后一帧）、淡出中（.hl-out）", "1, fading", `${rsel}, ${row.classList.contains("hl-out") ? "fading" : "not fading"}`, rsel === 1 && row.classList.contains("hl-out"));
      { const t = cs(row).transitionDuration, e = cs(row).transitionTimingFunction, pr = cs(row).transitionProperty;
        check("列表行 淡出 = background-color .5 s cubic-bezier(.42,0,.58,1)（--ios-motion-row-release-duration / --ios-motion-ease-in-out）", "background-color 0.5s cubic-bezier(0.42, 0, 0.58, 1)", `${pr} ${t} ${e}`, pr === "background-color" && t === "0.5s" && e === "cubic-bezier(0.42, 0, 0.58, 1)"); }
      await sleep(200);
      { const el = performance.now() - tUp - 16, c = rgb(bgOf(row)), want = T.card[0] + (HL[0] - T.card[0]) * (1 - bez(Math.max(0, Math.min(1, el / 500))));   // the fade starts one frame after the up
        check(`列表行 抬手 +${Math.round(el)} ms：R 在曲线上（±8；原生 +235 ms 亮 227 / 暗 46）`, Math.round(want), c ? Math.round(c[0]) : "缺", !!c && Math.abs(c[0] - want) <= 8); }
      await sleep(420);
      col("列表行 抬手 +660 ms：回到静止色 = 卡片色（--ios-card-bg）", T.card, bgOf(row));
      check("列表行 淡完后类名清空", "clean", row.className, !row.classList.contains("hl") && !row.classList.contains("hl-out"));
      /* C1: a 100 ms tap — no highlight at the up; one frame of highlight at +150 and the fade from there; selected once */
      pev(row, "pointerdown", at(row)); await sleep(100); pev(row, "pointerup", at(row));
      check("列表行 C1 短点 100 ms 抬手时：还没高亮", "rest", lit(row) ? "highlight" : "rest", !lit(row));
      seq.length = 0; await sleep(170);
      { const names = seq.map((e) => e[1]), iH = names.findIndex((n) => /\bhl\b/.test(n) && !/hl-out/.test(n)), iF = names.findIndex((n) => /hl-out/.test(n)), iC = names.indexOf("click");
        const gapHF = iH >= 0 && iF > iH ? seq[iF][0] - seq[iH][0] : -1, gapFC = iF >= 0 && iC > iF ? seq[iC][0] - seq[iF][0] : -1;
        check("列表行 C1 短点：高亮帧 → 淡出帧 → 选中，三者依次、各隔一次上屏（rAF + setTimeout 0；数据真机核 ②：confirm()/推页不得吞掉高亮帧）", "hl < hl-out < click", `${iH} < ${iF} < ${iC}, 间隔 ${Math.round(gapHF)} / ${Math.round(gapFC)} ms`, iH >= 0 && iF > iH && iC > iF); }   // the gaps are JS timestamps (the paint sits between rAF and the timeout; headless Chrome renders in < 1 ms): reported, not judged
      check("列表行 C1 按下 +270 ms：高亮已亮过并在淡出（.hl-out）、选中 1 次", "fading, 2", `${row.classList.contains("hl-out") ? "fading" : row.classList.contains("hl") ? "lit" : "rest"}, ${rsel}`, row.classList.contains("hl-out") && rsel === 2);
      await sleep(620);
      /* C6: vertical 12 pt after the highlight — off at once, the up selects nothing */
      pev(row, "pointerdown", at(row)); await sleep(200); pev(row, "pointermove", at(row, .5, .5, 0, 12));
      check("列表行 C6 竖滑 12 pt：高亮瞬时灭（touchesCancelled → animated:NO）", "rest, no fade", `${lit(row) ? "highlight" : "rest"}, ${row.classList.contains("hl-out") ? "fade" : "no fade"}`, !lit(row) && !row.classList.contains("hl-out"));
      pev(row, "pointerup", at(row, .5, .5, 0, 12)); await sleep(40);
      check("列表行 C6 竖滑后抬手：不选中", 2, rsel, rsel === 2);
      /* C9: a fast swipe never highlights */
      pev(row, "pointerdown", at(row)); pev(row, "pointermove", at(row, .5, .5, 0, 20)); await sleep(200);
      check("列表行 C9 快滑 20 pt：不高亮", "rest", lit(row) ? "highlight" : "rest", !lit(row));
      pev(row, "pointerup", at(row, .5, .5, 0, 20)); await sleep(40);
      /* C7/C10: 100 pt sideways inside the card keeps the press and selects; C11: 16 pt past the card's edge cancels */
      pev(row, "pointerdown", at(row)); await sleep(200); pev(row, "pointermove", at(row, .5, .5, 100, 0));
      check("列表行 C10 横滑 100 pt（行内）：仍高亮", "highlight", lit(row) ? "highlight" : "rest", lit(row));
      pev(row, "pointerup", at(row, .5, .5, 100, 0)); await sleep(60);
      check("列表行 C10 横滑 100 pt 抬手：选中", 3, rsel, rsel === 3);
      await sleep(620);
      pev(row, "pointerdown", at(row)); await sleep(200); pev(row, "pointermove", at(row, 1, .5, 16, 0));
      check("列表行 C11 出卡片边 16 pt：高亮灭", "rest", lit(row) ? "highlight" : "rest", !lit(row));
      await sleep(30);
      col("列表行 C11 出边 +30 ms：底色已是静止色（瞬灭，无淡回）", T.card, bgOf(row));
      pev(row, "pointerup", at(row, 1, .5, 16, 0)); await sleep(40);
      check("列表行 C11 出边抬手：不选中", 3, rsel, rsel === 3);
      /* the action row (.acts button) is the same cell */
      /* the 「开始刷」 path: the row's click opens the page's alert (ask(), the way view.js's action rows now do instead of the browser's blocking
         confirm dialog); a rAF loop logs the row's class at every frame (a rAF tick sees what that frame paints): a highlight frame and a fade
         frame must have been logged before the alert opened, and the fade must keep running under the open alert (native: deselectRow's .5 s
         fade runs while the alert presents) */
      const frames = []; let logging = true; const logFrame = (ts) => { frames.push([ts, act.className]); if (logging) requestAnimationFrame(logFrame); }; requestAnimationFrame(logFrame);
      let blockedAt = 0, askP = null; act.addEventListener("click", () => { blockedAt = performance.now(); askP = ask("开始刷？", "验收：弹窗打开后淡回仍在走", "开始刷"); });
      const framesBefore = () => { const fr = frames.filter((f) => f[0] < blockedAt); return { hl: fr.some((f) => /\bhl\b/.test(f[1]) && !/hl-out/.test(f[1])), out: fr.some((f) => /hl-out/.test(f[1])) }; };
      pev(act, "pointerdown", at(act)); await sleep(100); pev(act, "pointerup", at(act)); await sleep(60);
      const alertEl = document.querySelector("#alert"), r60 = rgb(bgOf(act));
      await sleep(200); const r210 = rgb(bgOf(act)), openAt60 = !!(alertEl && alertEl.open);   // the click (and the alert) comes ~2 frames after the +150 ms highlight of a 100 ms tap
      await sleep(400);
      { const b = framesBefore(); check("蓝字行 短点 100 ms，click 开页面弹窗（ask）：弹窗前已有高亮帧与淡出帧上屏（数据真机核 ②）", "hl 帧, hl-out 帧, 弹窗开（up +260）, 触发 1", `${b.hl ? "hl 帧" : "无 hl 帧"}, ${b.out ? "hl-out 帧" : "无 hl-out 帧"}, ${openAt60 ? "弹窗开" : "弹窗未开"}, 触发 ${asel}`, b.hl && b.out && openAt60 && asel === 1);
        const moving = !!(r60 && r210) && (dark ? r210[0] < r60[0] - 2 : r210[0] > r60[0] + 2), rest = same(bgOf(act), T.card);
        check("蓝字行 弹窗打开后淡回仍在走（up +60 → +260 ms 底色继续向静止色走，+660 到静止）", "走, 到静止", `${moving ? "走" : "停"}（R ${r60 ? Math.round(r60[0]) : "?"} → ${r210 ? Math.round(r210[0]) : "?"}）, ${rest ? "到静止" : "未到"}`, moving && rest); }
      if (alertEl && alertEl.open) { document.querySelector("#alert-cancel").click(); await sleep(450); }
      if (askP) await askP;
      frames.length = 0; blockedAt = 0;
      pev(act, "pointerdown", at(act)); await sleep(200);
      col("蓝字行 按下 +200 ms：底色 = 高亮色（同 cell）", HL, bgOf(act));
      pev(act, "pointerup", at(act)); await sleep(80);
      { const b = framesBefore(); check("蓝字行 长按抬手 +80 ms：淡出首帧已上屏后才触发（弹窗），触发 2 次", "hl-out 帧在前, 2", `${b.out ? "hl-out 帧在前" : "无"}, ${asel}`, b.out && asel === 2); }
      logging = false;
      if (alertEl && alertEl.open) { document.querySelector("#alert-cancel").click(); await sleep(450); }
      if (askP) await askP;
      await sleep(620);
      pev(act, "pointerdown", at(act)); await sleep(200); pev(act, "pointermove", at(act, 1, .5, 16, 0)); await sleep(30);
      col("蓝字行 出卡片边 16 pt +30 ms：瞬灭到静止色（数据真机核 ①：不走基础 .5 s transition）", T.card, bgOf(act));
      pev(act, "pointerup", at(act, 1, .5, 16, 0)); await sleep(60);
      check("蓝字行 出边抬手：不触发", 2, asel, asel === 2);
      /* the rest colour follows the theme's --card token and no press state outlives a press: after everything above, every action row / nav
         row in the document rests on the current theme's card colour with no state class or mark left (the device's dark → light report) */
      await sleep(200);
      { const leftovers = [...document.querySelectorAll(".row.nav, .group .acts button")].filter((el) => el.classList.contains("hl") || el.classList.contains("hl-out") || el.classList.contains("hl-cut") || el.dataset.rp || el.dataset.rc);
        check("行静止底 = 当前主题卡片色（--ios-card-bg），无残留状态类 / 标记（切主题后不留旧色）", `${fmt(T.card)}, 0 残留`, `${bgOf(act)}, ${leftovers.length} 残留`, same(bgOf(act), T.card) && same(bgOf(row), T.card) && leftovers.length === 0);
        document.dispatchEvent(new Event("visibilitychange")); }   // the strip on hide runs without error (a hidden page cannot be simulated here)
      /* the page's own action rows must not block the main thread: no synchronous confirm() left in view.js except ask()'s no-dialog fallback */
      try { const src = await (await fetch("view.js?v=" + Date.now())).text(); const n = (src.match(/\bconfirm\(/g) || []).length;
        check("行动作不再同步 confirm()（view.js 里只剩 ask() 的无 dialog 兜底那一处）", 1, n, n === 1); } catch (e) { check("行动作不再同步 confirm()", 1, "读不到 view.js", false); }
      rLab.remove();
    }
    const finish = () => {
      const fails = rows.filter((r) => !r.ok).length;
      const out = { at: new Date().toISOString(), href: location.href, viewport: `${innerWidth}×${innerHeight}`,
                    standalone: matchMedia("(display-mode: standalone)").matches,
                    dark, total: rows.length, fails, rows };
      try { localStorage.setItem("ark-accept", JSON.stringify(out)); } catch {}
      document.title = `验收 ${rows.length - fails}/${rows.length}`;
      if (!q.has("quiet")) {
        const box = document.createElement("pre");
        box.style.cssText = "position:fixed;left:8px;top:60px;z-index:99;max-height:70vh;overflow:auto;background:rgba(0,0,0,.82);color:#fff;font:11px/1.35 -apple-system,monospace;padding:8px;border-radius:8px;margin:0;white-space:pre";
        box.textContent = `${out.viewport}${out.standalone ? " 主屏幕" : " Safari"}${out.dark ? " 深色" : ""}  ${rows.length - fails}/${rows.length}\n` +
          rows.map((r) => `${r.ok ? "✓" : "✗"} ${r.item}  ${r.got}${r.ok ? "" : "（要 " + r.expect + "）"}`).join("\n");
        document.body.appendChild(box);
      }
    };
    const extra = async () => {
      if (window.ACCEPT) { for (const c of window.ACCEPT.files) { if (!window.ACCEPT.loaded.has(c)) await window.ACCEPT.load(c); if (!window.ACCEPT.loaded.has(c)) await window.ACCEPT.load(c);
          check(`accept-${c}.js 已加载（动态脚本，丢了会重取两次）`, "已加载", window.ACCEPT.loaded.has(c) ? "已加载" : "缺", window.ACCEPT.loaded.has(c)); } }
      for (const fn of (window.ACCEPT ? window.ACCEPT.fns : [])) { try { await fn({ check, num, col, sleep: (ms) => new Promise((r) => setTimeout(r, ms)) }); } catch (e) { check("控件检查文件出错 " + (fn.name || ""), "", String(e), false); } } };
    interactions().then(extra, (e) => { check("交互测试脚本出错", "", String(e), false); }).then(finish, (e) => { check("控件检查出错", "", String(e), false); finish(); });
  }
  /* The page renders after its first snapshot and the number tiles after the game
     APIs answer: measure once the tiles exist (or after 8 s) — never before view.js's top-level bindings exist (window.__viewReady, set at the
     end of view.js; the inline loader can deliver it late) and never while a runner holds the start (window.__acceptHold: scripts/mac/accept-run.py
     sets it before any page script and clears it once its snapshot / stamina data is injected). 60 s hard cap so a stuck page still reports. */
  let tries = 0;
  const t = setInterval(() => { tries++;
    const ready = window.__viewReady === true && !window.__acceptHold;
    if ((ready && (document.querySelector(".num") || tries > 80)) || tries > 600) { clearInterval(t); run(); } }, 100);
})();
