/* 验收：页面地址加 ?accept 时加载，在这台设备的浏览器里量 DOM，逐项和
   docs/HIG-CHECKLIST.md 的数字比。只认 iOS Safari 的数（桌面 Chromium 没有安全区）。
   结果存进 localStorage 的 ark-accept，scripts/mac/phone-accept.sh 从模拟器的存储里
   读出来；不加 &quiet 时左上角盖一张表。
   方法照 ~/Money/transit/ui/accept.js（另一个会话 2026-09-15 定型）。
   2026-09-18：期望值改成 web/tokens.css 的原值（每项后面写变量名；出处在 tokens.css
   该变量上一行的注释：UIProbe 探针 / AX json / Kit NUMBERS）。期望值故意写死在这里，
   不从 tokens.css 读——两边同源的话 tokens 写错也会「通过」。颜色比对解析 rgb，不比字串。 */
(function () {
  const q = new URLSearchParams(location.search);
  if (!q.has("accept")) return;
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
      num("设备行高 ≥ 53.33（--ios-row-h）", 53.33, Math.min(dev.getBoundingClientRect().height, 53.33)); const s2 = dev.querySelector(".dsub"); if (s2) col("设备行右灰值 secondaryLabel（--ios-secondary-label）", T.dim, cs(s2).color);
      const dot = dev.querySelector(".dot"); if (dot) { num("设备行状态点 11（--ios-status-dot，AX-58 信息未读点）", 11, dot.getBoundingClientRect().width); num("状态点到字 8（--ios-value-gap）", 8, px(cs(s2).columnGap)); }
    }
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
            const pg = document.querySelector("#subpage"); more.click(); await sleep(30);
            check("推入页打开（.in）、标题「回执」", "in 回执", `${pg.classList.contains("in") ? "in" : "-"} ${pg.querySelector(".ptitle").textContent}`, pg.classList.contains("in") && pg.querySelector(".ptitle").textContent === "回执");
            { const x30 = pg.getBoundingClientRect().left; check("推入 +30 ms：新页从右边滑入中（440 → 0）", "0 < x < 440", `x ${Math.round(x30)}`, x30 > 0 && x30 < 440); }
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
        /* §1 G1–G3: the up commits index + change + content in the same tick (--ios-touch-segment-commit-delay 0) */
        const t0 = performance.now(); pev(seg, "pointerup", at(other)); const dt = performance.now() - t0;
        check("分段 G1 抬手：同一刻改 index + change + 内容切（--ios-touch-segment-commit-delay 0）", want, `${onText()} +${Math.round(dt * 10) / 10} ms renders+${renders - r0}`, onText() === want && thisShift(want) && renders === r0 + 1 && dt < 50);
        const lensNow = q().querySelector(".lens");
        check("分段 G1 抬手：透镜走实测 x 路径 1.209 s（--ios-touch-segment-lens-x-keys）+ 边跑边胀关键帧", "1.209s linear(…) lens-stretch", `${cs(lensNow).transitionDuration.split(",")[0].trim()} ${cs(lensNow).transitionTimingFunction.slice(0, 7)} ${cs(lensNow).animationName}`, /^1\.209s/.test(cs(lensNow).transitionDuration) && /^linear\(/.test(cs(lensNow).transitionTimingFunction) && cs(lensNow).animationName === "lens-stretch");
        await sleep(192); const sc192 = cs(lensNow).scale.split(" ").map(parseFloat);
        num("分段 G1 +192 ms：透镜最宽 ×1.24（--ios-touch-segment-lens-w-keys）", 1.24, sc192[0], 0.06);
        await sleep(284);
        { const lr = lensNow.getBoundingClientRect(), sr = q().getBoundingClientRect(), lw = lensNow.offsetWidth, toI = parseFloat(q().style.getPropertyValue("--i")), fromI = toI === 1 ? 0 : 1;
          const pos = (lr.left + lr.width / 2 - sr.left - lensNow.offsetLeft - lw / 2) / lw;   // centre-based, scale-proof
          num("分段 G1 +476 ms：透镜过冲到行程 1.075（--ios-touch-segment-lens-x-keys）", 1.075, (pos - fromI) / (toI - fromI), 0.04); }
        await sleep(800);
        /* §1 G4/G16: touch-down on the selected segment lifts the lens after ~100 ms (196×28 → 220×44), no event */
        seg = q(); let sel = bs().find((b) => b.classList.contains("on")), unsel = bs().find((b) => !b.classList.contains("on"));
        const r1 = renders; pev(seg, "pointerdown", at(sel)); const lens0 = seg.querySelector(".lens");
        check("分段 G4 按下已选中段：+0 ms 透镜未抬、无事件", "no lift", lens0.classList.contains("lift") ? "lift" : "no lift", !lens0.classList.contains("lift") && renders === r1);
        await sleep(160);
        const sc160 = parseFloat(cs(lens0).scale);
        check("分段 G16 按下已选中段 +160 ms：透镜抬起中（+100 ms 起，.25 s 到 220×44）", "lift, scale > 1", `${lens0.classList.contains("lift") ? "lift" : "-"} ${cs(lens0).scale}`, lens0.classList.contains("lift") && sc160 > 1.0);
        await sleep(240);
        check("分段 G16 +400 ms：透镜 220×44 到位（--ios-touch-segment-lift-x 12 / -y 8）", "1.1224 1.5714", cs(lens0).scale, /^1\.12/.test(cs(lens0).scale) && /1\.57/.test(cs(lens0).scale));
        /* §1 G4/G22: sliding onto the other segment moves the lens, the index does not change until the up */
        pev(seg, "pointermove", at(unsel)); await sleep(30);
        const fracI = parseFloat(seg.style.getPropertyValue("--i"));
        check("分段 G22 按住滑到另一段：透镜跟手、index 不改", `${onText()} lens→${bs().indexOf(unsel)}`, `${onText()} --i=${fracI}`, onText() === sel.textContent && Math.abs(fracI - bs().indexOf(unsel)) < 0.5 && renders === r1);
        /* §1 G23: slide back and release on the original - no event */
        pev(seg, "pointermove", at(sel)); pev(seg, "pointerup", at(sel));
        check("分段 G23 滑回原段抬手：无事件，透镜回位", sel.textContent, `${onText()} renders+${renders - r1}`, onText() === sel.textContent && renders === r1 && q().style.getPropertyValue("--i") === String(bs().indexOf(sel)));
        /* §1 G4/G21: lift, slide to the other segment, release there - commits at the up */
        seg = q(); sel = bs().find((b) => b.classList.contains("on")); unsel = bs().find((b) => !b.classList.contains("on"));
        pev(seg, "pointerdown", at(sel)); await sleep(160); pev(seg, "pointermove", at(unsel)); const r2 = renders; pev(seg, "pointerup", at(unsel));
        check("分段 G21 抬起后滑到另一段抬手：选中那段", unsel.textContent, onText(), onText() === unsel.textContent && thisShift(unsel.textContent) && renders === r2 + 1);
        await sleep(50);
        /* §1 G5: press the unselected one, slide onto the selected one, release - no event */
        seg = q(); sel = bs().find((b) => b.classList.contains("on")); unsel = bs().find((b) => !b.classList.contains("on"));
        const r3 = renders; pev(seg, "pointerdown", at(unsel)); pev(seg, "pointermove", at(sel)); pev(seg, "pointerup", at(sel));
        check("分段 G5 按未选中段滑到已选中段抬手：无事件", sel.textContent, `${onText()} renders+${renders - r3}`, onText() === sel.textContent && renders === r3 && !unsel.classList.contains("dim"));
        /* §1 G17/G18/G26: release 60 pt below the control still selects, 100 pt below cancels (--ios-touch-inside-slop 70) */
        seg = q(); sel = bs().find((b) => b.classList.contains("on")); unsel = bs().find((b) => !b.classList.contains("on"));
        const r4 = renders; pev(seg, "pointerdown", at(unsel)); pev(seg, "pointermove", at(unsel, .5, .5, 0, 100)); pev(seg, "pointerup", at(unsel, .5, .5, 0, 100));
        check("分段 G18 竖向滑出 100 pt 抬手：取消、无事件、标签回 1", sel.textContent, `${onText()} renders+${renders - r4}`, onText() === sel.textContent && renders === r4 && !unsel.classList.contains("dim"));
        seg = q(); const r5 = renders; pev(seg, "pointerdown", at(unsel)); pev(seg, "pointermove", at(unsel, .5, .5, 0, 60)); pev(seg, "pointerup", at(unsel, .5, .5, 0, 60));
        check("分段 G17 竖向滑出 60 pt 抬手：仍选中（余量 70）", unsel.textContent, `${onText()} renders+${renders - r5}`, onText() === unsel.textContent && renders === r5 + 1);
        await sleep(50);
        /* pointercancel = cancel */
        seg = q(); sel = bs().find((b) => b.classList.contains("on")); unsel = bs().find((b) => !b.classList.contains("on"));
        const r6 = renders; pev(seg, "pointerdown", at(unsel)); pev(seg, "pointercancel", at(unsel));
        check("分段 pointercancel：不提交、标签回 1", sel.textContent, `${onText()} renders+${renders - r6}`, onText() === sel.textContent && renders === r6 && !unsel.classList.contains("dim"));
        /* §1 G12/G13: ten alternating taps 30 ms down / 30 ms gap - every up counts, no debounce (--ios-touch-debounce 0) */
        const r7 = renders; let last = null, everyTick = true;
        for (let k = 0; k < 10; k++) { const b = bs()[k % 2]; last = b.textContent; const sg = q(); pev(sg, "pointerdown", at(b)); await sleep(30); pev(sg, "pointerup", at(b)); if (onText() !== last) everyTick = false; await sleep(30); }
        check("分段 G12 快速交替 10 次（30 ms 点 / 30 ms 间隔）：每下都算、终态 = 最后一次", last, `${onText()} renders+${renders - r7}${everyTick ? "" : "（某下抬手时未切）"}`, onText() === last && renders === r7 + 10 && everyTick && thisShift(last));
        let stable = true; for (let k = 0; k < 6; k++) { await sleep(100); if (onText() !== last) stable = false; }
        check("分段 G12 快速交替后 600 ms 内不回跳", last, onText(), stable && onText() === last);
        /* a page re-render (heartbeat / snapshot) while the lens rests on a segment must not move it (the carry-over reads the lens box, not the % translate) */
        { await sleep(1300); const sg = q(), ln = sg.querySelector(".lens"), lb = ln.getBoundingClientRect().left; window.render(); const ln2 = q().querySelector(".lens"); const lb2 = ln2.getBoundingClientRect().left; await sleep(120); const lb3 = q().querySelector(".lens").getBoundingClientRect().left;
          check("重画时透镜不动（心跳/快照 render 不会让它跳）", `${Math.round(lb)}`, `${Math.round(lb2)} → ${Math.round(lb3)} ${q().querySelector(".lens").classList.contains("spring") ? "spring!" : ""}`, Math.abs(lb2 - lb) < 1 && Math.abs(lb3 - lb) < 1 && !q().querySelector(".lens").classList.contains("spring")); }
        /* §1 G14: the same segment tapped three times - one event */
        const sameName = (bs().find((x) => !x.classList.contains("on")) || bs()[0]).textContent;
        const r8 = renders; for (let k = 0; k < 3; k++) { const b = bs().find((x) => x.textContent === sameName); const sg = q(); pev(sg, "pointerdown", at(b)); pev(sg, "pointerup", at(b)); await sleep(40); }
        check("分段 G14 同段连点 3 下：只 1 次事件", 1, renders - r8, renders - r8 === 1);
        const back = bs().find((b) => b.textContent === start); if (back && onText() !== start) { const sg = q(); pev(sg, "pointerdown", at(back)); pev(sg, "pointerup", at(back)); }
      }
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
    interactions().then(finish, (e) => { check("交互测试脚本出错", "", String(e), false); finish(); });
  }
  /* The page renders after its first snapshot and the number tiles after the game
     APIs answer: measure once the tiles exist (or after 8 s). */
  let tries = 0;
  const t = setInterval(() => { tries++; if (document.querySelector(".num") || tries > 80) { clearInterval(t); run(); } }, 100);
})();
